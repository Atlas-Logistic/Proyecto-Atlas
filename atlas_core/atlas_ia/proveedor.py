"""Abstracción de proveedor de modelo de razonamiento -- Bloque A1.

Mismo patrón que ya usa toda la base de código de Atlas en producción
para cualquier dependencia externa: `Protocol` mínimo + un doble
determinista sin red (ver `atlas_core.ocr_provider.ProveedorOCR`,
`atlas_core.rutas.proveedor.ProveedorRutas`,
`atlas_core.telemetria.proveedor.ProveedorTelemetria`,
`atlas_core.verificacion_externa.ProveedorVerificacionEntidades`). Cambiar
de proveedor/modelo en el futuro será cambiar la implementación inyectada
detrás de `ProveedorModeloIA`, nunca el código que la consume.

Este bloque NO implementa ningún proveedor real: sin SDK, sin variables de
entorno de API, sin red, sin selección de modelo. `ProveedorModeloIASimulado`
existe únicamente para demostrar que el contrato funciona -- nunca para
simular capacidad de razonamiento (ver AJUSTE 3 del bloque A1: un
proveedor simulado no es un benchmark de IA)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Protocol

from atlas_core.atlas_ia.contratos import (
    ContextoRazonamiento,
    HipotesisIA,
    RESULTADO_HIPOTESIS_ABSTENCION,
    calcular_hipotesis_id,
)


class ProveedorModeloIA(Protocol):
    """Contrato que debe cumplir cualquier proveedor real de razonamiento.
    `razonar` recibe únicamente el `ContextoRazonamiento` ya minimizado --
    nunca acceso directo a catálogos, Drive ni al dataset."""

    def razonar(self, contexto: ContextoRazonamiento) -> HipotesisIA: ...


@dataclass(frozen=True)
class RespuestaSimulada:
    """Plantilla de lo que `ProveedorModeloIASimulado` debe responder para
    un `valor_documental` dado. El `hipotesis_id` real siempre se calcula
    con `calcular_hipotesis_id` en el momento de responder -- nunca se fija
    a mano en la plantilla, precisamente para que la identidad reproducible
    (T7) sea una propiedad real del contrato, no una coincidencia de
    fixture."""

    resultado: str  # uno de RESULTADOS_HIPOTESIS
    valor_propuesto: str = ""
    evidencia_usada: tuple[str, ...] = ()
    evidencia_en_contra: tuple[str, ...] = ()
    explicacion: str = ""
    herramienta_faltante: str = ""


class ProveedorModeloIASimulado:
    """Doble determinista para tests y para el shadow harness. Nunca
    razona de verdad -- sólo devuelve, para cada `valor_documental`, la
    respuesta ya configurada por quien construye el proveedor. Sirve para
    probar el enchufe (contrato, validadores, orquestación), nunca para
    medir capacidad de razonamiento.

    Sin red, sin SDK externo, sin variables de entorno, sin acceso a
    Drive -- el estado completo del proveedor vive en el diccionario que
    se le entrega al construirlo."""

    def __init__(
        self,
        *,
        respuestas_por_valor_documental: Mapping[str, RespuestaSimulada],
        proveedor: str = "SIMULADO",
        modelo: str = "simulado-v1",
    ) -> None:
        self._respuestas = dict(respuestas_por_valor_documental)
        self._proveedor = proveedor
        self._modelo = modelo
        self.contextos_recibidos: list[ContextoRazonamiento] = []

    def razonar(self, contexto: ContextoRazonamiento) -> HipotesisIA:
        self.contextos_recibidos.append(contexto)
        plantilla = self._respuestas.get(
            contexto.valor_documental,
            RespuestaSimulada(resultado=RESULTADO_HIPOTESIS_ABSTENCION),
        )
        hipotesis_id = calcular_hipotesis_id(contexto, plantilla.valor_propuesto)
        return HipotesisIA(
            hipotesis_id=hipotesis_id,
            campo=contexto.campo,
            valor_observado=contexto.valor_documental,
            valor_propuesto=plantilla.valor_propuesto,
            resultado=plantilla.resultado,
            evidencia_usada=plantilla.evidencia_usada,
            evidencia_en_contra=plantilla.evidencia_en_contra,
            explicacion=plantilla.explicacion,
            herramienta_faltante=plantilla.herramienta_faltante,
            proveedor=self._proveedor,
            modelo=self._modelo,
        )
