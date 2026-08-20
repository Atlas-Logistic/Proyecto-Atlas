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

    def a_dict(self) -> dict[str, object]:
        return {
            "estado": self.estado, "clasificacion": self.clasificacion,
            "contexto_final": self.contexto_final.a_dict(),
            "hipotesis": self.hipotesis.a_dict() if self.hipotesis else None,
            "validacion": self.validacion.a_dict() if self.validacion else None,
            "rondas": self.rondas, "herramientas_usadas": list(self.herramientas_usadas),
            "detalle": self.detalle,
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
        for ronda in (1, 2):
            try:
                hipotesis = self._proveedor.razonar(actual)
            except ErrorProveedorModeloIA as error:
                return ResultadoOrquestacion(
                    ERROR_PROVEEDOR, CLASIFICACION_D, actual, rondas=ronda,
                    herramientas_usadas=tuple(usadas), detalle=str(error),
                )

            if hipotesis.resultado == RESULTADO_HIPOTESIS_REQUIERE_HERRAMIENTA:
                nombre = hipotesis.herramienta_faltante.strip()
                herramienta = self._herramientas.get(nombre)
                if ronda == 2 or herramienta is None or nombre not in actual.herramientas_disponibles:
                    return ResultadoOrquestacion(
                        REQUIERE_HERRAMIENTA, CLASIFICACION_C, actual, hipotesis=hipotesis,
                        rondas=ronda, herramientas_usadas=tuple(usadas),
                        detalle=f"Herramienta no disponible o límite de rondas: {nombre}",
                    )
                nuevas = herramienta.consultar(actual)
                existentes = {e.identificador for e in actual.evidencias}
                agregadas = tuple(e for e in nuevas if e.identificador not in existentes)
                usadas.append(nombre)
                actual = replace(actual, evidencias=(*actual.evidencias, *agregadas))
                continue

            validacion = validar_hipotesis_multicampo(hipotesis, actual)
            if not validacion.aceptada:
                return ResultadoOrquestacion(
                    BLOQUEADO_POR_VALIDACION, CLASIFICACION_D, actual,
                    hipotesis=hipotesis, validacion=validacion, rondas=ronda,
                    herramientas_usadas=tuple(usadas),
                )
            if hipotesis.resultado == RESULTADO_HIPOTESIS_ABSTENCION:
                return ResultadoOrquestacion(
                    ABSTENCION_IA, CLASIFICACION_C, actual, hipotesis=hipotesis,
                    validacion=validacion, rondas=ronda, herramientas_usadas=tuple(usadas),
                )
            if hipotesis.resultado == RESULTADO_HIPOTESIS_PROPUESTA:
                return ResultadoOrquestacion(
                    RESUELTO_POR_IA, _clasificar_propuesta(actual, hipotesis), actual,
                    hipotesis=hipotesis, validacion=validacion, rondas=ronda,
                    herramientas_usadas=tuple(usadas),
                )

        raise AssertionError("El orquestador excedió el máximo de dos rondas")
