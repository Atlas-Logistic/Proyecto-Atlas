"""Motor de Evidencia -- capa genérica compartida por los motores de
razonamiento determinista de Atlas (vehículos, clientes/entidades, y en el
futuro obras/destinos). Nunca IA generativa, nunca LLM, nunca red externa
por sí solo -- combina señales ya disponibles (internas y, cuando se le
entregan explícitamente, externas) en una jerarquía de precedencia por
niveles, nunca pesos numéricos arbitrarios.

Extrae el patrón general que ya demostró funcionar en producción para
`VEHICULO_DESCONOCIDO` (`atlas_core.decisiones_pendientes.evaluar_evidencia_patente`):

    OBSERVACION -> CANDIDATOS -> EVIDENCIAS -> CONTRADICCIONES ->
    CONFIRMACIONES -> RESULTADO -> EXPLICACION

Este módulo NO reemplaza ni reescribe el motor de vehículos (evitar un
refactor de una pieza ya validada en producción); formaliza la forma común
para que los motores nuevos (clientes/entidades) la reutilicen desde el
principio, en vez de reinventarla.

Vocabulario de resultado, 5 estados (ampliación del 3-estado de vehículos
para dominios donde además puede haber una entidad genuinamente nueva o
una contradicción documental detectable sin llegar a resolverla sola):

- RESUELTO_AUTOMATICAMENTE: la evidencia converge sin ambigüedad -- nunca
  requiere intervención humana para ESTA decisión puntual. Puramente
  informativo/clasificatorio: nunca dispara una escritura por sí mismo.
- SUGERENCIA_HUMANA: hay un candidato preferido y explicable, pero la
  evidencia no alcanza para resolver sin que un humano confirme.
- CONTRADICCION_DOCUMENTAL: la evidencia demuestra con razonable certeza
  que el documento trae un dato distinto del real, pero esa certeza
  todavía no es suficiente (o falta la corroboración humana acumulada)
  para operar automáticamente -- se sugiere la corrección, nunca se aplica
  sola.
- ALTA_NUEVA: no hay ningún candidato existente que coincida, y nada
  contradice que sea una entidad genuinamente nueva.
- ABSTENCION_REAL: Atlas agotó las fuentes disponibles y no puede, con
  responsabilidad, producir ninguna de las clasificaciones anteriores.
"""
from __future__ import annotations

from dataclasses import dataclass, field

RESULTADO_RESUELTO_AUTOMATICAMENTE = "RESUELTO_AUTOMATICAMENTE"
RESULTADO_SUGERENCIA_HUMANA = "SUGERENCIA_HUMANA"
RESULTADO_CONTRADICCION_DOCUMENTAL = "CONTRADICCION_DOCUMENTAL"
RESULTADO_ALTA_NUEVA = "ALTA_NUEVA"
RESULTADO_ABSTENCION_REAL = "ABSTENCION_REAL"

RESULTADOS_VALIDOS = (
    RESULTADO_RESUELTO_AUTOMATICAMENTE, RESULTADO_SUGERENCIA_HUMANA,
    RESULTADO_CONTRADICCION_DOCUMENTAL, RESULTADO_ALTA_NUEVA, RESULTADO_ABSTENCION_REAL,
)

# Jerarquía de precedencia por NIVELES, no por puntaje. El orden de esta
# tupla ES la jerarquía -- de mayor a menor certeza. Un candidato de un
# nivel siempre le gana a uno de un nivel inferior, sin importar cuánta
# evidencia auxiliar traiga el segundo (evita que "más documentos" o "más
# fuentes débiles" desplacen a una confirmación humana real).
NIVEL_CONFIRMACION_HUMANA = "CONFIRMACION_HUMANA"
NIVEL_EXTERNO_OFICIAL = "EXTERNO_OFICIAL"
NIVEL_EXTERNO_CORPORATIVO = "EXTERNO_CORPORATIVO"
NIVEL_DOCUMENTAL_INDEPENDIENTE = "DOCUMENTAL_INDEPENDIENTE"
NIVEL_EXTERNO_DIRECTORIO = "EXTERNO_DIRECTORIO"
NIVEL_EXTERNO_AUXILIAR = "EXTERNO_AUXILIAR"
NIVEL_DOCUMENTAL_DEBIL = "DOCUMENTAL_DEBIL"

_ORDEN_NIVEL = {
    nivel: orden
    for orden, nivel in enumerate((
        NIVEL_CONFIRMACION_HUMANA, NIVEL_EXTERNO_OFICIAL, NIVEL_EXTERNO_CORPORATIVO,
        NIVEL_DOCUMENTAL_INDEPENDIENTE, NIVEL_EXTERNO_DIRECTORIO, NIVEL_EXTERNO_AUXILIAR,
        NIVEL_DOCUMENTAL_DEBIL,
    ))
}


def orden_nivel(nivel: str) -> int:
    """Posición de un nivel en la jerarquía (menor = más certeza). Un
    nivel desconocido se trata como el más débil posible -- nunca gana
    por accidente ante un nivel real."""
    return _ORDEN_NIVEL.get(nivel, len(_ORDEN_NIVEL))


@dataclass(frozen=True)
class CandidatoEvidencia:
    """Una posible identidad/valor canónico para el campo en duda, con su
    razonamiento completo y auditable -- nunca un score sin explicar."""

    identificador: str  # p.ej. cliente_id, vehiculo_id, obra_id
    valor_canonico: str  # p.ej. razón social, patente, nombre de obra
    nivel: str
    evidencias: tuple[str, ...] = ()
    conflictos: tuple[str, ...] = ()
    razon_legible: str = ""
    metadatos: dict[str, object] = field(default_factory=dict)

    def a_dict(self) -> dict[str, object]:
        return {
            "identificador": self.identificador,
            "valor_canonico": self.valor_canonico,
            "nivel": self.nivel,
            "evidencias": list(self.evidencias),
            "conflictos": list(self.conflictos),
            "razon_legible": self.razon_legible,
            "metadatos": dict(self.metadatos),
        }


@dataclass(frozen=True)
class ResultadoEvidencia:
    """Salida completa y auditable de una evaluación del motor de
    evidencia -- siempre uno de los 5 resultados de `RESULTADOS_VALIDOS`,
    la lista completa de candidatos considerados (nunca se ocultan los que
    perdieron) y una explicación en lenguaje humano, plantillada."""

    resultado: str
    candidatos: tuple[CandidatoEvidencia, ...] = ()
    explicacion: str = ""

    def __post_init__(self) -> None:
        if self.resultado not in RESULTADOS_VALIDOS:
            raise ValueError(f"resultado de evidencia no soportado: {self.resultado!r}")

    def a_dict(self) -> dict[str, object]:
        return {
            "resultado": self.resultado,
            "candidatos": [c.a_dict() for c in self.candidatos],
            "explicacion": self.explicacion,
        }


def elegir_mejor_candidato(candidatos: tuple[CandidatoEvidencia, ...]) -> CandidatoEvidencia | None:
    """Ordena por nivel (nunca por cantidad de evidencia dentro del mismo
    nivel) y devuelve el mejor -- o `None` si dos o más candidatos
    distintos empatan en el nivel más alto presente (un empate real nunca
    se resuelve arbitrariamente, ver `hay_empate_en_el_tope`)."""
    if not candidatos:
        return None
    return min(candidatos, key=lambda c: orden_nivel(c.nivel))


def hay_empate_en_el_tope(candidatos: tuple[CandidatoEvidencia, ...]) -> bool:
    """True si dos o más candidatos con IDENTIFICADOR distinto comparten
    el nivel más alto presente -- Atlas nunca elige entre ellos por su
    cuenta."""
    if len(candidatos) < 2:
        return False
    mejor_orden = min(orden_nivel(c.nivel) for c in candidatos)
    identificadores_en_el_tope = {
        c.identificador for c in candidatos if orden_nivel(c.nivel) == mejor_orden
    }
    return len(identificadores_en_el_tope) > 1
