"""Contratos propios de Atlas IA -- Bloque A1.

Esta capa NUNCA modifica ni reemplaza los contratos productivos de
`atlas_core.motor_evidencia` (`CandidatoEvidencia`/`ResultadoEvidencia`)
ni el resultado real de
`atlas_core.decisiones_pendientes.evaluar_evidencia_patente` -- el Motor
determinista de vehículos ya validado en producción. Sólo LEE evidencia
ya reunida por ese Motor y produce hipótesis auditables; nunca escribe,
nunca autorresuelve, nunca aplica una decisión.

Por qué contratos propios y no extender los productivos (decisión A0,
ratificada en el ajuste 1 de A1): el contrato productivo ya sostiene al
Motor determinista en operación real -- cualquier cambio ahí tiene una
superficie de regresión grande. Primero se descubre, con uso real de
Atlas IA, qué metadatos hacen falta; la posible unificación se decide
después, con evidencia, no por adelantado.

Deliberadamente NO se introduce aquí ningún nivel nuevo dentro de la
jerarquía de `atlas_core.motor_evidencia` (nada de `NIVEL_INFERENCIA_IA`
en el Motor productivo) -- una inferencia de Atlas IA vive únicamente en
`HipotesisIA`, nunca mezclada con evidencia real dentro de
`EvidenciaIA`/`ContextoRazonamiento`.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Mapping

# ---------------------------------------------------------------------
# EvidenciaIA
# ---------------------------------------------------------------------

# Tipos de fuente que puede traer una evidencia ya reunida por el Motor
# determinista, traducida para consumo del razonador. Nunca incluye
# "INFERENCIA_IA" -- eso es exactamente lo que distingue una evidencia
# (lo que el Motor determinista ya comprobó) de una hipótesis (lo que
# Atlas IA propone a partir de esa evidencia, ver HipotesisIA más abajo).
TIPOS_FUENTE_IA = (
    "DOCUMENTAL",       # lo que dice/leyó el propio documento en cuestión
    "HISTORICO",        # coincidencia observada en otros documentos/transportes del mismo chofer
    "CATALOGO",         # entidad ya conocida en un catálogo (confirmada o no)
    "DECISION_HUMANA",  # una decisión ya aplicada por un humano (ledger de decisiones_aplicadas.json)
    "EXTERNO",          # verificación externa (hoy sin proveedor real conectado, ver A0 sección B)
)


@dataclass(frozen=True)
class EvidenciaIA:
    """Una evidencia YA reunida por el Motor determinista, empaquetada de
    sólo lectura para el razonador. Nunca se construye con datos
    inventados a mano en código de producción -- siempre la deriva un
    adaptador (`adaptadores.py`) a partir de un resultado real."""

    identificador: str  # p.ej. vehiculo_id, o cualquier id estable del candidato
    campo: str  # "patente_tracto" / "patente_rampla" / ...
    valor: str  # el valor concreto que esta evidencia respalda
    tipo_fuente: str  # uno de TIPOS_FUENTE_IA
    nivel: str  # nivel/autoridad tal cual lo asignó el Motor determinista -- nunca reinterpretado aquí
    a_favor: tuple[str, ...] = ()  # códigos de evidencia a favor, ya calculados por el Motor
    en_contra: tuple[str, ...] = ()  # códigos de conflicto, ya calculados por el Motor
    independencia: int = 0  # transportes/eventos independientes, si el Motor lo calculó
    es_decision_humana: bool = False  # True sólo si, trazablemente, viene del ledger
    procedencia: str = ""  # qué función/módulo determinista la produjo

    def __post_init__(self) -> None:
        if self.tipo_fuente not in TIPOS_FUENTE_IA:
            raise ValueError(f"tipo_fuente no soportado: {self.tipo_fuente!r}")
        if self.es_decision_humana and self.tipo_fuente != "DECISION_HUMANA":
            raise ValueError("es_decision_humana=True exige tipo_fuente='DECISION_HUMANA'")

    def a_dict(self) -> dict[str, object]:
        return {
            "identificador": self.identificador, "campo": self.campo, "valor": self.valor,
            "tipo_fuente": self.tipo_fuente, "nivel": self.nivel,
            "a_favor": list(self.a_favor), "en_contra": list(self.en_contra),
            "independencia": self.independencia, "es_decision_humana": self.es_decision_humana,
            "procedencia": self.procedencia,
        }


# ---------------------------------------------------------------------
# ContextoRazonamiento
# ---------------------------------------------------------------------


@dataclass(frozen=True)
class ContextoRazonamiento:
    """Lo mínimo que el razonador necesita para UN caso -- nunca la base
    de datos completa (minimización de contexto desde el diseño, ver A0
    sección J). Se construye siempre mediante un adaptador a partir de
    evidencia real ya reunida por el Motor determinista."""

    campo: str
    valor_documental: str
    rut_chofer: str
    numero_guia: str
    numero_transporte: str
    evidencias: tuple[EvidenciaIA, ...] = ()
    resultado_motor: str = ""  # el resultado que ya devolvió el Motor determinista (p.ej. SUGERENCIA_HUMANA)
    explicacion_motor: str = ""  # la explicación en lenguaje humano que ya generó el Motor

    def valores_evidencia(self) -> tuple[str, ...]:
        """Todos los valores presentes en la evidencia reunida -- única
        fuente autorizada de "candidatos reales" para el validador V2
        (una hipótesis nunca puede proponer un valor fuera de este
        conjunto)."""
        return tuple(sorted({e.valor for e in self.evidencias}))

    def a_dict(self) -> dict[str, object]:
        return {
            "campo": self.campo, "valor_documental": self.valor_documental,
            "rut_chofer": self.rut_chofer, "numero_guia": self.numero_guia,
            "numero_transporte": self.numero_transporte,
            "evidencias": [e.a_dict() for e in self.evidencias],
            "resultado_motor": self.resultado_motor, "explicacion_motor": self.explicacion_motor,
        }


# ---------------------------------------------------------------------
# HipotesisIA + identidad determinista
# ---------------------------------------------------------------------

RESULTADO_HIPOTESIS_PROPUESTA = "PROPUESTA"
RESULTADO_HIPOTESIS_ABSTENCION = "ABSTENCION"
RESULTADO_HIPOTESIS_REQUIERE_HERRAMIENTA = "REQUIERE_HERRAMIENTA"

RESULTADOS_HIPOTESIS = (
    RESULTADO_HIPOTESIS_PROPUESTA,
    RESULTADO_HIPOTESIS_ABSTENCION,
    RESULTADO_HIPOTESIS_REQUIERE_HERRAMIENTA,
)


def _payload_canonico_hipotesis(contexto: ContextoRazonamiento, valor_propuesto: str) -> str:
    """Payload EXACTO que entra al hash de `hipotesis_id` -- documentado
    aquí, en un único lugar. Incluye: campo, valor documental, RUT del
    chofer, número de guía y de transporte (el "mismo problema"), la
    evidencia considerada (identificador+valor+nivel de cada una, en
    orden estable -- nunca el orden de iteración original) y el valor
    propuesto. Cualquier cambio a la evidencia considerada (una guía
    nueva, un nivel que subió) cambia el hash -- por diseño: mismo
    problema + misma evidencia = mismo id; evidencia nueva = id nuevo."""
    evidencia_ordenada = sorted(
        (e.identificador, e.valor, e.nivel) for e in contexto.evidencias
    )
    payload = {
        "campo": contexto.campo,
        "valor_documental": contexto.valor_documental,
        "rut_chofer": contexto.rut_chofer,
        "numero_guia": contexto.numero_guia,
        "numero_transporte": contexto.numero_transporte,
        "evidencia": evidencia_ordenada,
        "valor_propuesto": valor_propuesto,
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def calcular_hipotesis_id(contexto: ContextoRazonamiento, valor_propuesto: str) -> str:
    """`hipotesis_id` reproducible -- nunca un UUID aleatorio. Ver
    `_payload_canonico_hipotesis` para qué entra exactamente al hash."""
    payload = _payload_canonico_hipotesis(contexto, valor_propuesto)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class HipotesisIA:
    """Salida validable por software de un `ProveedorModeloIA` -- nunca
    texto libre. NO otorga autonomía por sí sola: sólo después de pasar
    por `validadores.py` puede siquiera considerarse, y ninguna vía de
    A1 la aplica a ningún dato operacional."""

    hipotesis_id: str
    campo: str
    valor_observado: str
    valor_propuesto: str  # "" si resultado es ABSTENCION o REQUIERE_HERRAMIENTA
    resultado: str  # uno de RESULTADOS_HIPOTESIS
    evidencia_usada: tuple[str, ...] = ()  # identificadores de EvidenciaIA
    evidencia_en_contra: tuple[str, ...] = ()
    explicacion: str = ""
    herramienta_faltante: str = ""  # sólo si resultado == REQUIERE_HERRAMIENTA
    proveedor: str = ""
    modelo: str = ""
    metadata: Mapping[str, object] = field(default_factory=dict)  # p.ej. confianza auto-reportada por el modelo -- nunca decide autonomía

    def __post_init__(self) -> None:
        if self.resultado not in RESULTADOS_HIPOTESIS:
            raise ValueError(f"resultado de hipótesis no soportado: {self.resultado!r}")
        if self.resultado == RESULTADO_HIPOTESIS_PROPUESTA and not self.valor_propuesto:
            raise ValueError("una hipótesis PROPUESTA exige valor_propuesto")
        if self.resultado == RESULTADO_HIPOTESIS_REQUIERE_HERRAMIENTA and not self.herramienta_faltante:
            raise ValueError("REQUIERE_HERRAMIENTA exige herramienta_faltante")
        object.__setattr__(self, "metadata", dict(self.metadata))

    def a_dict(self) -> dict[str, object]:
        return {
            "hipotesis_id": self.hipotesis_id, "campo": self.campo,
            "valor_observado": self.valor_observado, "valor_propuesto": self.valor_propuesto,
            "resultado": self.resultado, "evidencia_usada": list(self.evidencia_usada),
            "evidencia_en_contra": list(self.evidencia_en_contra), "explicacion": self.explicacion,
            "herramienta_faltante": self.herramienta_faltante, "proveedor": self.proveedor,
            "modelo": self.modelo, "metadata": dict(self.metadata),
        }


# ---------------------------------------------------------------------
# ResultadoValidacionHipotesis
# ---------------------------------------------------------------------

MOTIVO_FORMATO_INVALIDO = "FORMATO_INVALIDO"
MOTIVO_VALOR_NO_RESPALDADO = "VALOR_NO_RESPALDADO_POR_EVIDENCIA"
MOTIVO_CONTRADICE_EVIDENCIA_SUPERIOR = "CONTRADICE_EVIDENCIA_SUPERIOR"
MOTIVO_ESTRUCTURA_INVALIDA = "ESTRUCTURA_INVALIDA"

MOTIVOS_RECHAZO_VALIDOS = (
    MOTIVO_FORMATO_INVALIDO, MOTIVO_VALOR_NO_RESPALDADO,
    MOTIVO_CONTRADICE_EVIDENCIA_SUPERIOR, MOTIVO_ESTRUCTURA_INVALIDA,
)


@dataclass(frozen=True)
class ResultadoValidacionHipotesis:
    """Resultado, siempre determinista, de pasar una `HipotesisIA` por los
    validadores post-proveedor. `aceptada=True` nunca implica autonomía --
    sólo implica que estructuralmente la hipótesis no viola ninguna
    barrera anti-alucinación conocida."""

    aceptada: bool
    motivo_rechazo: str = ""  # "" si aceptada
    detalle: str = ""

    def __post_init__(self) -> None:
        if not self.aceptada and self.motivo_rechazo not in MOTIVOS_RECHAZO_VALIDOS:
            raise ValueError(f"motivo_rechazo inválido o ausente: {self.motivo_rechazo!r}")
        if self.aceptada and self.motivo_rechazo:
            raise ValueError("una hipótesis aceptada no debe traer motivo_rechazo")

    def a_dict(self) -> dict[str, object]:
        return {"aceptada": self.aceptada, "motivo_rechazo": self.motivo_rechazo, "detalle": self.detalle}


# ---------------------------------------------------------------------
# ResultadoShadow
# ---------------------------------------------------------------------


@dataclass(frozen=True)
class ResultadoShadow:
    """Resultado completo y auditable de ejecutar un caso por el shadow
    harness -- permite comparar, más adelante, Motor actual / hipótesis
    Atlas IA / ground truth humano / validación. NO calcula ninguna
    métrica cognitiva (ver ajuste 3 de A1) -- eso exige un proveedor
    real, fuera de alcance de este bloque."""

    caso_id: str  # identificador legible del caso, p.ej. "464036"
    contexto: ContextoRazonamiento
    hipotesis: HipotesisIA
    validacion: ResultadoValidacionHipotesis
    resultado_motor: str  # duplicado explícito de contexto.resultado_motor, para comparación directa
    ground_truth_humano: str = ""  # valor que un humano confirmó, si se conoce -- sólo para comparación offline

    def a_dict(self) -> dict[str, object]:
        return {
            "caso_id": self.caso_id, "contexto": self.contexto.a_dict(),
            "hipotesis": self.hipotesis.a_dict(), "validacion": self.validacion.a_dict(),
            "resultado_motor": self.resultado_motor, "ground_truth_humano": self.ground_truth_humano,
        }
