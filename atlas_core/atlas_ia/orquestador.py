"""Orquestador multicampo read-only de Atlas IA B1."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Mapping

from atlas_core.atlas_ia.contratos import (
    ContextoRazonamiento,
    HipotesisIA,
    RESULTADO_HIPOTESIS_ABSTENCION,
    RESULTADO_HIPOTESIS_PROPUESTA,
    RESULTADO_HIPOTESIS_REQUIERE_HERRAMIENTA,
    ResultadoValidacionHipotesis,
)
from atlas_core.atlas_ia.herramientas import HerramientaEvidencia
from atlas_core.atlas_ia.proveedor import ProveedorModeloIA
from atlas_core.atlas_ia.proveedor_anthropic import ErrorProveedorModeloIA
from atlas_core.atlas_ia.validadores import validar_hipotesis_multicampo

RESUELTO_POR_IA = "RESUELTO_POR_IA"
ABSTENCION_IA = "ABSTENCION_IA"
REQUIERE_HERRAMIENTA = "REQUIERE_HERRAMIENTA"
BLOQUEADO_POR_VALIDACION = "BLOQUEADO_POR_VALIDACION"
NO_APLICA_IA = "NO_APLICA_IA"
ERROR_PROVEEDOR = "ERROR_PROVEEDOR"

CLASIFICACION_A = "A_AUTONOMIA_CANDIDATA"
CLASIFICACION_B = "B_ASISTENCIA"
CLASIFICACION_C = "C_ABSTENCION"
CLASIFICACION_D = "D_BLOQUEO"

# Bloque B1 INVESTIGADOR -- antes 2 rondas fijas (una sola oportunidad de
# pedir UNA herramienta). El ciclo "investigo -> observo -> vuelvo a
# investigar si hace falta -> concluyo" necesita más de una ronda de
# herramienta antes de la respuesta final -- acotado (nunca sin límite,
# ver Bloque "Performance/costo"): hasta 3 rondas de herramienta + 1
# ronda final de conclusión.
RONDAS_MAXIMAS = 4


@dataclass(frozen=True)
class ResultadoOrquestacion:
    estado: str
    clasificacion: str
    contexto_final: ContextoRazonamiento
    hipotesis: HipotesisIA | None = None
    validacion: ResultadoValidacionHipotesis | None = None
    rondas: int = 0
    herramientas_usadas: tuple[str, ...] = ()
    detalle: str = ""
    # Bloque SIMPLIFICAR/AVANZAR A B1 -- traza auditable de CADA ronda
    # (hipótesis estructurada del proveedor + cuántas evidencias tenía
    # disponibles en ese momento), no sólo la hipótesis final. Aditivo y
    # opcional (`()` por defecto): nunca cambia el comportamiento de
    # decisión del orquestador, sólo agrega visibilidad para auditoría.
    # Nunca contiene razonamiento libre del proveedor -- sólo los mismos
    # campos estructurados que ya valida `HipotesisIA`.
    traza: tuple[dict[str, object], ...] = ()

    def a_dict(self) -> dict[str, object]:
        return {
            "estado": self.estado, "clasificacion": self.clasificacion,
            "contexto_final": self.contexto_final.a_dict(),
            "hipotesis": self.hipotesis.a_dict() if self.hipotesis else None,
            "validacion": self.validacion.a_dict() if self.validacion else None,
            "rondas": self.rondas, "herramientas_usadas": list(self.herramientas_usadas),
            "detalle": self.detalle, "traza": list(self.traza),
        }


def _clasificar_propuesta(contexto: ContextoRazonamiento, hipotesis: HipotesisIA) -> str:
    soportes = [e for e in contexto.evidencias if e.valor == hipotesis.valor_propuesto]
    fuerte = any(
        evidencia.nivel in ("CONFIRMACION_HUMANA", "EXTERNO_OFICIAL")
        and not evidencia.en_contra for evidencia in soportes
    )
    return CLASIFICACION_A if fuerte else CLASIFICACION_B


class OrquestadorAtlasIA:
    def __init__(
        self, *, proveedor: ProveedorModeloIA,
        herramientas: Mapping[str, HerramientaEvidencia] | None = None,
    ) -> None:
        self._proveedor = proveedor
        self._herramientas = dict(herramientas or {})

    def resolver(self, contexto: ContextoRazonamiento) -> ResultadoOrquestacion:
        if contexto.resultado_motor == "RESUELTO_AUTOMATICAMENTE":
            return ResultadoOrquestacion(NO_APLICA_IA, CLASIFICACION_A, contexto)

        actual = contexto
        usadas: list[str] = []
        traza: list[dict[str, object]] = []
        for ronda in range(1, RONDAS_MAXIMAS + 1):
            try:
                hipotesis = self._proveedor.razonar(actual)
            except ErrorProveedorModeloIA as error:
                return ResultadoOrquestacion(
                    ERROR_PROVEEDOR, CLASIFICACION_D, actual, rondas=ronda,
                    herramientas_usadas=tuple(usadas), detalle=str(error), traza=tuple(traza),
                )
            traza.append({
                "ronda": ronda, "evidencias_disponibles": len(actual.evidencias),
                "hipotesis": hipotesis.a_dict(),
            })

            if hipotesis.resultado == RESULTADO_HIPOTESIS_REQUIERE_HERRAMIENTA:
                nombre = hipotesis.herramienta_faltante.strip()
                herramienta = self._herramientas.get(nombre)
                if ronda == RONDAS_MAXIMAS or herramienta is None or nombre not in actual.herramientas_disponibles:
                    return ResultadoOrquestacion(
                        REQUIERE_HERRAMIENTA, CLASIFICACION_C, actual, hipotesis=hipotesis,
                        rondas=ronda, herramientas_usadas=tuple(usadas),
                        detalle=f"Herramienta no disponible o límite de rondas: {nombre}",
                        traza=tuple(traza),
                    )
                nuevas = herramienta.consultar(actual)
                existentes = {e.identificador for e in actual.evidencias}
                agregadas = tuple(e for e in nuevas if e.identificador not in existentes)
                # Bloque B1 INVESTIGADOR -- si esta misma herramienta ya se
                # usó y esta vuelta no aportó NADA nuevo (mismo contexto,
                # misma consulta -- cacheada), volver a preguntarle al
                # proveedor sería la misma pregunta con la misma evidencia:
                # nunca produce progreso, sólo gasta rondas. Se detiene
                # aquí, en vez de agotar `RONDAS_MAXIMAS` sin avanzar.
                if not agregadas and nombre in usadas:
                    return ResultadoOrquestacion(
                        REQUIERE_HERRAMIENTA, CLASIFICACION_C, actual, hipotesis=hipotesis,
                        rondas=ronda, herramientas_usadas=tuple(usadas),
                        detalle=f"La herramienta {nombre} ya se agotó sin evidencia nueva.",
                        traza=tuple(traza),
                    )
                traza[-1]["herramienta_consultada"] = nombre
                traza[-1]["evidencia_nueva"] = [e.a_dict() for e in agregadas]
                usadas.append(nombre)
                actual = replace(actual, evidencias=(*actual.evidencias, *agregadas))
                continue

            validacion = validar_hipotesis_multicampo(hipotesis, actual)
            if not validacion.aceptada:
                return ResultadoOrquestacion(
                    BLOQUEADO_POR_VALIDACION, CLASIFICACION_D, actual,
                    hipotesis=hipotesis, validacion=validacion, rondas=ronda,
                    herramientas_usadas=tuple(usadas), traza=tuple(traza),
                )
            if hipotesis.resultado == RESULTADO_HIPOTESIS_ABSTENCION:
                return ResultadoOrquestacion(
                    ABSTENCION_IA, CLASIFICACION_C, actual, hipotesis=hipotesis,
                    validacion=validacion, rondas=ronda, herramientas_usadas=tuple(usadas),
                    traza=tuple(traza),
                )
            if hipotesis.resultado == RESULTADO_HIPOTESIS_PROPUESTA:
                return ResultadoOrquestacion(
                    RESUELTO_POR_IA, _clasificar_propuesta(actual, hipotesis), actual,
                    hipotesis=hipotesis, validacion=validacion, rondas=ronda,
                    herramientas_usadas=tuple(usadas), traza=tuple(traza),
                )

        raise AssertionError(f"El orquestador excedió el máximo de {RONDAS_MAXIMAS} rondas")
