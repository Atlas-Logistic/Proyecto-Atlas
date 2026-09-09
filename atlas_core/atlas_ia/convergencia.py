"""Bloque AUTORIDAD OPERACIONAL / CONVERGENCIA -- criterio GENERAL (nunca
por entidad, nunca una tabla de sustituciones de caracteres) para decidir
si el conocimiento acumulado de Atlas es lo bastante fuerte como para
absorber SILENCIOSAMENTE una pequeña variación OCR y resolver al valor
canónico, sin convertirla en trabajo humano.

PRINCIPIO: un error pequeño de OCR/tipeo no puede transformar un
conocimiento fuertemente establecido en conocimiento desconocido. La
tolerancia contextual ante una variación crece con la evidencia
acumulada -- confirmaciones humanas, catálogo canónico, aliases,
cantidad de documentos históricos consistentes, RUT, relaciones
chofer↔vehículo / cliente↔obra / obra↔destino, ausencia de competidores.

Este módulo NO hace fuzzy matching: recibe candidatos YA reunidos por los
Motores deterministas (`evaluar_evidencia_patente`, `evaluar_evidencia_
cliente`, `evaluar_evidencia_obra`, resolvedores de obra por variación
ortográfica) y sólo decide, con reglas de seguridad explícitas:

  RESOLVER_SILENCIOSO  -- candidato único fuertemente respaldado, dentro de
                          la distancia tolerada por su fuerza, sin competidor
                          plausible y sin contradicción fuerte.
  MANTENER_REVISION    -- dos candidatos razonables, o evidencia insuficiente,
                          o la variación es demasiado grande para la fuerza
                          disponible (algo "radicalmente distinto" nunca se
                          fuerza).
  CONTRADICCION_FUERTE -- hay evidencia fuerte que apunta a OTRA identidad
                          (p. ej. un RUT válido atribuible sin ambigüedad a
                          otra empresa) -- nunca se oculta ni se resuelve.

Criterio de seguridad (las cuatro condiciones son obligatorias para
RESOLVER_SILENCIOSO):
  1. existe un candidato canónico FUERTE;
  2. tiene al menos DOS señales de evidencia independientes;
  3. no hay otro candidato con fuerza al menos PLAUSIBLE;
  4. no hay ninguna contradicción fuerte.
"""
from __future__ import annotations

from dataclasses import dataclass, field

RESOLVER_SILENCIOSO = "RESOLVER_SILENCIOSO"
MANTENER_REVISION = "MANTENER_REVISION"
CONTRADICCION_FUERTE = "CONTRADICCION_FUERTE"

# Métodos de desempate -- traza de observabilidad de cómo se llegó a una
# resolución/abstención de VEHÍCULO (nunca cambian la decisión, sólo la
# explican). Vocabulario cerrado.
METODO_CONTEXTO_DETERMINISTA = "CONTEXTO_DETERMINISTA"
METODO_B1_EVIDENCIA_INTERNA = "B1_EVIDENCIA_INTERNA"
METODO_ABSTENCION_AMBIGUA = "ABSTENCION_AMBIGUA"

# Señales de evidencia INDEPENDIENTE que suman fuerza a un candidato.
# Cada una debe venir de una fuente distinta -- nunca dos lecturas del
# mismo documento, nunca dos guías del mismo transporte (esa
# deduplicación la hacen los Motores antes de llegar aquí).
SEÑAL_CONFIRMACION_HUMANA = "CONFIRMACION_HUMANA"
SEÑAL_CATALOGO_CANONICO = "CATALOGO_CANONICO"
SEÑAL_ALIAS_CONOCIDO = "ALIAS_CONOCIDO"
SEÑAL_RUT_COINCIDE = "RUT_COINCIDE"
SEÑAL_RELACION_CHOFER_VEHICULO = "RELACION_CHOFER_VEHICULO"
SEÑAL_RELACION_CLIENTE_OBRA = "RELACION_CLIENTE_OBRA"
SEÑAL_RELACION_OBRA_DESTINO = "RELACION_OBRA_DESTINO"
SEÑAL_HISTORIAL_CONSISTENTE = "HISTORIAL_CONSISTENTE"  # >= 2 transportes independientes
SEÑAL_DIRECCION_COMUNA_COINCIDE = "DIRECCION_COMUNA_COINCIDE"

# Señales que, por sí solas, ya constituyen un ancla FUERTE de identidad
# (una confirmación humana explícita, o el catálogo canónico). El resto
# son señales de apoyo: suman para llegar al mínimo de DOS
# independientes, pero una sola de ellas no basta.
_SEÑALES_ANCLA_FUERTE = frozenset({SEÑAL_CONFIRMACION_HUMANA, SEÑAL_CATALOGO_CANONICO})

# Distancia OCR máxima tolerada según la fuerza del candidato. "Distancia"
# es responsabilidad del llamador (diferencia posicional para patentes,
# distancia de edición de un único token para nombres) -- este módulo sólo
# la compara contra el techo. `None` = sin límite de distancia declarado
# por el llamador (coincidencia exacta/alias ya garantizada aguas arriba).
_DISTANCIA_MAXIMA_POR_ANCLA = 2   # confirmación humana / catálogo canónico + apoyo
_DISTANCIA_MAXIMA_APOYO = 1       # sólo señales de apoyo convergentes


@dataclass(frozen=True)
class CandidatoConvergencia:
    """Un candidato canónico ya reunido por un Motor determinista."""

    valor_canonico: str
    distancia_ocr: int | None  # None si el llamador ya garantizó exacto/alias
    señales: frozenset[str] = frozenset()

    @property
    def tiene_ancla_fuerte(self) -> bool:
        return bool(self.señales & _SEÑALES_ANCLA_FUERTE)

    @property
    def señales_independientes(self) -> int:
        return len(self.señales)

    @property
    def es_fuerte(self) -> bool:
        # FUERTE = ancla fuerte (confirmación humana o catálogo canónico)
        # + al menos una señal independiente adicional. Un único indicio
        # nunca es "fuerte", por definición del principio.
        return self.tiene_ancla_fuerte and self.señales_independientes >= 2

    @property
    def es_plausible(self) -> bool:
        # PLAUSIBLE = cualquier candidato con al menos una señal real
        # (aunque no llegue a fuerte). Sirve para detectar "dos candidatos
        # razonables" -> nunca autoconfirmar.
        return self.señales_independientes >= 1

    def _distancia_tolerada(self) -> int:
        return _DISTANCIA_MAXIMA_POR_ANCLA if self.tiene_ancla_fuerte else _DISTANCIA_MAXIMA_APOYO

    @property
    def dentro_de_tolerancia(self) -> bool:
        if self.distancia_ocr is None:
            return True
        return 0 <= self.distancia_ocr <= self._distancia_tolerada()


@dataclass(frozen=True)
class ResultadoConvergencia:
    decision: str
    valor_canonico: str = ""
    valor_ocr_original: str = ""
    metodo: str = ""
    evidencias: tuple[str, ...] = ()
    confianza: str = ""  # "ALTA" | "MEDIA" | ""
    competidores: tuple[str, ...] = ()
    contradiccion: str = ""
    # Traza de observabilidad del desempate (candidatos considerados,
    # evidencias/fuentes independientes por candidato, contradicciones,
    # método, valor OCR original y valor canónico aplicado). Vacío cuando
    # no se intentó ningún desempate. Nunca influye en `decision`.
    desempate: dict = field(default_factory=dict)

    def a_dict(self) -> dict[str, object]:
        salida = {
            "decision": self.decision, "valor_canonico": self.valor_canonico,
            "valor_ocr_original": self.valor_ocr_original, "metodo": self.metodo,
            "evidencias": list(self.evidencias), "confianza": self.confianza,
            "competidores": list(self.competidores), "contradiccion": self.contradiccion,
        }
        if self.desempate:
            salida["desempate"] = self.desempate
        return salida


def evaluar_convergencia(
    *,
    dominio: str,
    valor_ocr: str,
    candidatos: tuple[CandidatoConvergencia, ...],
    metodo: str,
    contradicciones_fuertes: tuple[str, ...] = (),
    exigir_diferencia: bool = True,
) -> ResultadoConvergencia:
    """Aplica el criterio de seguridad general. `metodo` es la etiqueta de
    trazabilidad que quedará registrada si se resuelve (p. ej.
    "CONVERGENCIA_VEHICULO").

    `exigir_diferencia` (default True): para patente/obra, un candidato
    IDÉNTICO al valor OCR no es una "resolución" (ya está bien) y se
    descarta. Para CLIENTE se pasa False: un nombre exacto pero con RUT
    ausente/corrupto SÍ necesita que la identidad canónica se confirme
    silenciosamente (si no, se crearía CLIENTE_CANDIDATO)."""
    valor_ocr = str(valor_ocr or "").strip()

    if contradicciones_fuertes:
        return ResultadoConvergencia(
            decision=CONTRADICCION_FUERTE, valor_ocr_original=valor_ocr, metodo=metodo,
            contradiccion="; ".join(contradicciones_fuertes),
        )

    def _norm(texto: str) -> str:
        return " ".join(str(texto or "").upper().split())

    # Si el valor OCR YA coincide exactamente con un canónico conocido, no
    # hay nada que "arreglar silenciosamente" -- y nunca se resuelve a un
    # canónico DISTINTO (patente/obra): el camino de coincidencia exacta
    # que ya existe aguas arriba se encarga.
    if exigir_diferencia and any(
        _norm(c.valor_canonico) == _norm(valor_ocr) for c in candidatos
    ):
        return ResultadoConvergencia(
            decision=MANTENER_REVISION, valor_ocr_original=valor_ocr, metodo=metodo,
        )

    # Sólo candidatos DISTINTOS del valor OCR (una coincidencia exacta no
    # es una "resolución", ya está bien) y dentro de la distancia que su
    # propia fuerza tolera -- algo radicalmente distinto queda fuera aquí.
    alcanzables = tuple(
        c for c in candidatos
        if (not exigir_diferencia or _norm(c.valor_canonico) != _norm(valor_ocr))
        and c.dentro_de_tolerancia
    )
    fuertes = tuple(c for c in alcanzables if c.es_fuerte)
    plausibles_distintos = {
        _norm(c.valor_canonico) for c in alcanzables if c.es_plausible
    }

    if len(fuertes) == 1 and len(plausibles_distintos) == 1:
        ganador = fuertes[0]
        confianza = "ALTA" if SEÑAL_CONFIRMACION_HUMANA in ganador.señales else "MEDIA"
        return ResultadoConvergencia(
            decision=RESOLVER_SILENCIOSO, valor_canonico=ganador.valor_canonico,
            valor_ocr_original=valor_ocr, metodo=metodo,
            evidencias=tuple(sorted(ganador.señales)), confianza=confianza,
        )

    competidores = tuple(sorted(plausibles_distintos))
    return ResultadoConvergencia(
        decision=MANTENER_REVISION, valor_ocr_original=valor_ocr, metodo=metodo,
        competidores=competidores,
    )
