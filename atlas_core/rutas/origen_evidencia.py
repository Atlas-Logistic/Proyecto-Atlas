"""Bloque ORIGEN OPERACIONAL V2 -- fusión de evidencia de planta de
origen entre lo que Mobile informa y lo que dice el documento, cruzada
contra reglas de compatibilidad planta<->categoría CONFIGURABLES por
contexto/empresa (`atlas_core.catalogo_plantas.Planta.
categorias_permitidas`, dato, nunca lógica de Core).

Causa raíz que motiva este módulo (caso real 472593, guía Mobile):
Mobile informó `AZA_COLINA`; el pipeline terminó publicando `AZA RENCA`
por el encabezado documental de la guía -- el encabezado imprime
siempre la misma planta matriz societaria (casa central), nunca la
planta física real de despacho (confirmado por Javier). Ninguna
evidencia gana únicamente por existir: este módulo cruza Mobile,
documento y regla configurada, y sólo resuelve automáticamente cuando
la evidencia converge de forma explicable; cualquier otra combinación
es una CONTRADICCIÓN OPERACIONAL real, nunca una corrección silenciosa
ni una invención de origen -- queda para evidencia adicional (GPS,
histórico, B1) o, en último caso, confirmación humana (reutiliza
`ORIGEN_NO_CONFIRMADO`, ver `decisiones_pendientes.
detectar_decision_origen_no_confirmado`).

Universal por diseño (Bloque 20/21 del ticket): ninguna función de este
módulo conoce MBT/AZA/COLINA/RENCA/BARRAS/ROLLOS/ÁNGULOS -- sólo objetos
`Planta` (con su `categorias_permitidas`, un dato del contexto) y
strings de categoría genéricos."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from atlas_core.catalogo_plantas import Planta, normalizar_nombre_planta
from atlas_core.clasificador_material import TipoCarga

FUENTE_MOBILE = "MOBILE"
FUENTE_DOCUMENTO = "DOCUMENTO"

COMPATIBLE = "COMPATIBLE"
INCOMPATIBLE = "INCOMPATIBLE"
SIN_REGLA = "SIN_REGLA"

# Motivo persistido en `motivo_ruta` cuando la fusión no puede resolver
# automáticamente -- reconocido por
# `decisiones_pendientes.detectar_decision_origen_no_confirmado` para
# ofrecerlo como pregunta `ORIGEN_NO_CONFIRMADO`, nunca una bandeja
# paralela.
MOTIVO_CONTRADICCION_OPERACIONAL = "CONTRADICCION_OPERACIONAL_ORIGEN"

# Bloque CORRECCIÓN ESTRUCTURAL DE ORIGEN DOCUMENTAL AZA -- motivo
# persistido por `revalidacion_documental.revalidar_origen_encabezado_no_
# confiable_sin_ocr` cuando un origen quedó determinado ÚNICAMENTE por
# `evidencia_origen="ENCABEZADO_GUIA"` (membrete/casa matriz societaria,
# nunca la planta real de despacho -- ver `rutas.origen_documental`) y se
# revierte a sin-determinar. Reconocido igual por `detectar_decision_
# origen_no_confirmado` para ofrecer una pregunta `ORIGEN_NO_CONFIRMADO`
# NEUTRAL (sin candidato -- Atlas nunca vuelve a proponer la misma planta
# que acaba de invalidar).
MOTIVO_ENCABEZADO_NO_CONFIABLE = "ENCABEZADO_GUIA_NO_CONFIABLE"


def resolver_planta_por_codigo_mobile(codigo: str | None, plantas: Iterable[Planta]) -> Planta | None:
    """Traduce el código que Mobile informa (p. ej. `AZA_COLINA` --
    convención propia de Mobile, ver `atlas_core.mobile.
    PLANTAS_ORIGEN_MOBILE`, sin tocar en este bloque) contra el catálogo
    real de plantas -- genérico (guión bajo -> espacio + normalización
    ya existente de `catalogo_plantas`), nunca una comparación literal
    de un nombre de empresa hardcodeado. Sin coincidencia única y
    vigente (`CONFIRMADA`/`ACTIVA`): `None`, nunca adivina."""
    texto = str(codigo or "").strip()
    if not texto:
        return None
    objetivo = normalizar_nombre_planta(texto.replace("_", " "))
    candidatas = [
        p for p in plantas
        if p.nombre_normalizado == objetivo
        and str(p.estado_calidad).upper() in {"CONFIRMADA", "CONFIRMADO", "CONFIRMADO_DOCUMENTAL"}
        and str(p.estado_vigencia).upper() in {"ACTIVA", "ACTIVO"}
    ]
    return candidatas[0] if len(candidatas) == 1 else None


def evaluar_compatibilidad_planta_categoria(planta: Planta | None, categoria: str | None) -> str:
    """Bloque 3/6 del ticket -- nunca bloquea por ausencia de regla
    (Sección "COMPATIBILIDAD HACIA ATRÁS": "no bloquear viajes válidos
    sólo porque no exista configuración"). `SIN_REGLA` cuando la planta
    no trae `categorias_permitidas` configuradas o la categoría no se
    pudo determinar -- nunca se interpreta como incompatibilidad.

    Bloque M2-A -- causa raíz real (472624, Mobile): el string vacío no
    era la única forma en que "no se determinó categoría" llegaba
    aquí -- `TipoCarga.NO_DETERMINADO` ("NO DETERMINADO") es el
    centinela que el propio clasificador de material persiste cuando NO
    logró determinar nada, nunca una categoría real. Tratarlo como una
    categoría literal (que ninguna planta tiene configurada) producía
    INCOMPATIBLE por ausencia de evidencia, no por evidencia real de
    incompatibilidad -- exactamente lo que esta función ya declaraba
    evitar. Ausencia de evidencia != evidencia de incompatibilidad."""
    if planta is None:
        return SIN_REGLA
    categoria_normalizada = str(categoria or "").strip().upper()
    if categoria_normalizada == TipoCarga.NO_DETERMINADO.value:
        categoria_normalizada = ""
    permitidas = tuple(str(c).strip().upper() for c in planta.categorias_permitidas)
    if not permitidas or not categoria_normalizada:
        return SIN_REGLA
    return COMPATIBLE if categoria_normalizada in permitidas else INCOMPATIBLE


@dataclass(frozen=True)
class ResultadoFusionOrigen:
    """Salida de `fusionar_evidencia_origen` -- estructurada A PROPÓSITO
    (Bloque "B1/ATLAS IA" del ticket) para poder entregarse tal cual como
    evidencia a B1 el día que ese camino de razonamiento se conecte aquí:
    nunca un texto libre que B1 tendría que reinterpretar."""

    planta: Planta | None
    fuente: str  # FUENTE_MOBILE | FUENTE_DOCUMENTO | ""
    evidencia: str
    contradiccion: bool
    motivo: str = ""
    # Trazabilidad completa de lo evaluado -- nunca se pierde qué dijo
    # cada fuente, exista o no contradicción (Sección "no alterar
    # silenciosamente la evidencia original" del ticket), ni lo que cada
    # fuente propuso (Sección "B1/ATLAS IA": "origen informado; GPS si
    # existe; material/categoría; compatibilidades configuradas;
    # evidencia documental; contradicciones detectadas").
    planta_mobile: Planta | None = None
    compatibilidad_mobile: str = SIN_REGLA
    planta_documento: Planta | None = None
    compatibilidad_documento: str = SIN_REGLA
    categoria: str = ""

    def a_dict(self) -> dict[str, object]:
        """Bloque "B1/ATLAS IA" del ticket -- paquete de evidencia
        universal: nombres de campo genéricos (`planta_id`/`fuente`/
        `compatibilidad`...), nunca AZA/COLINA/RENCA/BARRAS escritos en
        el propio código -- esos son sólo los VALORES que trae este
        contexto/empresa. Listo para pasarse tal cual a un futuro
        proveedor B1 de razonamiento de origen (no conectado en este
        bloque -- ver Sección "NO configurar credenciales B1")."""
        def _planta_dict(planta: Planta | None) -> dict[str, str]:
            return {"planta_id": planta.planta_id, "planta_nombre": planta.nombre} if planta else {}

        return {
            "categoria": self.categoria,
            "mobile": {**_planta_dict(self.planta_mobile), "compatibilidad": self.compatibilidad_mobile},
            "documento": {**_planta_dict(self.planta_documento), "compatibilidad": self.compatibilidad_documento},
            "resultado": {
                "planta_id": self.planta.planta_id if self.planta else "",
                "planta_nombre": self.planta.nombre if self.planta else "",
                "fuente": self.fuente,
                "evidencia": self.evidencia,
            },
            "contradiccion": self.contradiccion,
            "motivo": self.motivo,
        }


def _motivo_texto(
    *, planta_mobile: Planta | None, compat_mobile: str,
    planta_documento: Planta | None, compat_documento: str,
) -> str:
    """Codifica lo evaluado en un texto parseable -- mismo criterio ya
    usado por `motivo_origen_gps` (Bloque ORIGEN D1: `_PATRON_
    CONFLICTO_ORIGEN`), nunca un objeto que sólo esta corrida en memoria
    puede leer. `detectar_decision_origen_no_confirmado` lo parsea para
    ofrecer los mismos candidatos como pregunta a un humano."""
    partes = []
    if planta_mobile is not None:
        nombre_token = planta_mobile.nombre.strip().upper().replace(" ", "_")
        partes.append(f"MOBILE={nombre_token}:{compat_mobile}")
    if planta_documento is not None:
        nombre_token = planta_documento.nombre.strip().upper().replace(" ", "_")
        partes.append(f"DOCUMENTO={nombre_token}:{compat_documento}")
    return f"{MOTIVO_CONTRADICCION_OPERACIONAL}[{'|'.join(partes)}]"


def fusionar_evidencia_origen(
    *, planta_mobile: Planta | None, planta_documento: Planta | None, categoria: str | None,
) -> ResultadoFusionOrigen:
    """Bloque 4/5 del ticket -- fusión de evidencia MOBILE/DOCUMENTO
    cruzada contra la regla de compatibilidad configurada. Se invoca
    SÓLO cuando GPS no determinó nada (GPS sigue siendo el tramo más
    confiable de la jerarquía existente, sin cambios en este bloque --
    ver `atlas_core.rutas.enriquecimiento_viaje.resolver_planta_origen`).

    Reglas (ninguna evidencia gana sólo por existir -- Sección
    "JERARQUÍA / FUSIÓN DE EVIDENCIAS" del ticket):

    1. Sin ninguna de las dos: sin origen (igual que hoy).
    2. Sólo MOBILE: si es compatible (o sin regla configurada) gana
       MOBILE; si es incompatible, es una contradicción -- una sola
       fuente violando una regla configurada nunca se acepta a ciegas
       ni se corrige sola (Sección "CONTRADICCIONES": "Atlas NO debe
       cambiar automáticamente a COLINA sólo por la regla").
    3. Sólo DOCUMENTO: igual que hoy (compatibilidad histórica) cuando
       es compatible o sin regla -- el encabezado societario sigue
       siendo el único fallback disponible para documentos sin Mobile.
       Si es incompatible con una regla configurada, es contradicción
       por el mismo principio del punto 2 (nunca se acepta un origen
       documental que la propia regla operacional contradice).
    4. Ambas coinciden en la misma planta: consistente, gana MOBILE
       (la fuente operacional, con el documento como corroboración).
    5. Ambas discrepan: si UNA es compatible (o sin regla) y la OTRA es
       incompatible, gana la compatible -- el encabezado societario ya
       es evidencia estructuralmente débil (Sección "ENCABEZADO
       SOCIETARIO / DOMICILIO DEL EMISOR != PLANTA FÍSICA DE ORIGEN DEL
       VIAJE"), así que una regla que lo contradice es corroboración
       real, no sólo "la regla decidió". Si ambas son compatibles, ambas
       incompatibles, o no hay regla para desempatar: contradicción
       real, nunca se elige a ciegas."""
    categoria_texto = str(categoria or "")

    def _resultado(*, planta: Planta | None, fuente: str, evidencia: str, contradiccion: bool, motivo: str = "") -> ResultadoFusionOrigen:
        return ResultadoFusionOrigen(
            planta=planta, fuente=fuente, evidencia=evidencia, contradiccion=contradiccion, motivo=motivo,
            planta_mobile=planta_mobile, compatibilidad_mobile=compat_mobile,
            planta_documento=planta_documento, compatibilidad_documento=compat_documento,
            categoria=categoria_texto,
        )

    if planta_mobile is None and planta_documento is None:
        compat_mobile = compat_documento = SIN_REGLA
        return _resultado(planta=None, fuente="", evidencia="", contradiccion=False)

    compat_mobile = evaluar_compatibilidad_planta_categoria(planta_mobile, categoria)
    compat_documento = evaluar_compatibilidad_planta_categoria(planta_documento, categoria)

    def _contradiccion() -> ResultadoFusionOrigen:
        return _resultado(
            planta=None, fuente="", evidencia="", contradiccion=True,
            motivo=_motivo_texto(
                planta_mobile=planta_mobile, compat_mobile=compat_mobile,
                planta_documento=planta_documento, compat_documento=compat_documento,
            ),
        )

    if planta_mobile is not None and planta_documento is None:
        if compat_mobile == INCOMPATIBLE:
            return _contradiccion()
        return _resultado(planta=planta_mobile, fuente=FUENTE_MOBILE, evidencia="MOBILE_INFORMADO", contradiccion=False)

    if planta_documento is not None and planta_mobile is None:
        if compat_documento == INCOMPATIBLE:
            return _contradiccion()
        return _resultado(planta=planta_documento, fuente=FUENTE_DOCUMENTO, evidencia="ENCABEZADO_GUIA", contradiccion=False)

    # Ambas presentes.
    if planta_mobile.planta_id == planta_documento.planta_id:
        return _resultado(
            planta=planta_mobile, fuente=FUENTE_MOBILE, evidencia="MOBILE_CORROBORADO_POR_DOCUMENTO", contradiccion=False,
        )

    mobile_ok = compat_mobile != INCOMPATIBLE
    documento_ok = compat_documento != INCOMPATIBLE
    if mobile_ok and not documento_ok:
        return _resultado(
            planta=planta_mobile, fuente=FUENTE_MOBILE,
            evidencia="MOBILE_COMPATIBLE_DOCUMENTO_CONTRADICE_REGLA", contradiccion=False,
        )
    return _contradiccion()
