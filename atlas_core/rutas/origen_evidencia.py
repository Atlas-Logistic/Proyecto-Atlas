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

import re
from dataclasses import dataclass
from typing import Iterable

from atlas_core.catalogo_destinos import normalizar_nombre_destino
from atlas_core.catalogo_plantas import Planta, normalizar_nombre_planta
from atlas_core.clasificador_material import TipoCarga

FUENTE_MOBILE = "MOBILE"
FUENTE_DOCUMENTO = "DOCUMENTO"
# Bloque ORIGEN V3 -- CONVERGENCIA DE EVIDENCIA ANTES DE PREGUNTAR: fuente
# que no depende de ningún origen informado (Mobile o encabezado) -- ver
# `resolver_planta_unica_por_categoria`, más abajo.
FUENTE_CATEGORIA_DESTINO_EXTERNO = "CATEGORIA_DESTINO_EXTERNO"

_PATRON_SOLAPE_CONFLICTO = re.compile(r"solape=(\d+(?:\.\d+)?)%")


def conflicto_gps_tiene_evidencia_real(motivo_origen_gps: str) -> bool:
    """Bloque ORIGEN V3 -- CONVERGENCIA DE EVIDENCIA ANTES DE PREGUNTAR:
    distingue un `CONFLICTO_REAL_EN_VENTANA` (ver
    `atlas_core.telemetria.seleccion_recorrido`) con evidencia física
    genuina (al menos una planta candidata con solape > 0% dentro de la
    ventana documental -- una detención real, así sea breve) de uno
    donde TODAS las plantas candidatas miden 0.0% de solape -- caso real
    464730 (AZA_COLINA:score=0.0026,solape=0.0%;AZA_RENCA:score=0.0,
    solape=0.0%): ningún candidato tocó realmente la ventana de forma
    medible, la etiqueta "conflicto" sólo refleja que ambos, por igual
    de débiles, superaron el piso mínimo de `_toca_la_ventana` (un solo
    breadcrumb alcanza). Ese empate en cero NO es evidencia real
    apuntando a otra planta -- nunca debe bloquear una conclusión ya
    respaldada por categoría/destino (ver `resolver_planta_unica_por_
    categoria`, más abajo, y sus llamadores). Cualquier solape > 0% en
    CUALQUIER candidato sigue siendo evidencia real que nunca se pisa
    (mismo principio que `DETENCION_REAL_FUERA_DE_TODA_GEOCERCA`, que
    cada llamador sigue tratando como bloqueante por separado). Si el
    texto no es reconocible como `CONFLICTO_REAL_EN_VENTANA` o no se
    puede parsear ningún `solape=`, se trata como evidencia real por
    cautela -- nunca se decide sobre un formato que no se entiende."""
    texto = str(motivo_origen_gps or "")
    if not texto.startswith("CONFLICTO_REAL_EN_VENTANA"):
        return False
    solapes = [float(v) for v in _PATRON_SOLAPE_CONFLICTO.findall(texto)]
    if not solapes:
        return True  # formato inesperado -- nunca se asume "sin evidencia" a ciegas
    return any(s > 0.0 for s in solapes)

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


# Bloque R2.3 (adición -- RESOLUCIÓN OPERACIONAL DE PLANTA ORIGEN) --
# motivo persistido cuando la resolución automática de abajo SÍ pudo
# concluir un origen (por eliminación, nunca adivinado): el encabezado
# documental proponía una planta incompatible con la categoría real de
# carga, y existe EXACTAMENTE una planta vigente alternativa compatible
# con esa misma categoría que además no es, ella misma, el destino del
# despacho (nunca confunde un traslado interno HACIA esa planta con un
# despacho a cliente DESDE ella). Reconocido por
# `decisiones_pendientes.detectar_decision_origen_no_confirmado`, que ya
# se abstiene en cuanto `planta_origen_id` está presente -- la pregunta
# ORIGEN_NO_CONFIRMADO desaparece sola, nunca hace falta borrarla aparte.
MOTIVO_RESUELTO_POR_ELIMINACION_CATEGORIA = "ORIGEN_RESUELTO_POR_ELIMINACION_DE_CATEGORIA"


def _planta_vigente(planta: Planta) -> bool:
    return (
        str(planta.estado_calidad).upper() in {"CONFIRMADA", "CONFIRMADO", "CONFIRMADO_DOCUMENTAL"}
        and str(planta.estado_vigencia).upper() in {"ACTIVA", "ACTIVO"}
    )


def _es_el_propio_destino(planta: Planta, destino_texto: str) -> bool:
    """Compartida por `resolver_planta_alternativa_por_categoria` y
    `resolver_planta_unica_por_categoria`: `destino_texto` (típicamente
    `despachar_a_crudo`) menciona, él mismo, a esta planta -- evidencia
    de un TRASLADO INTERNO hacia ella, nunca un despacho a cliente DESDE
    ella (caso real: barras despachadas hacia la propia planta candidata
    no prueban que la carga salió de ahí)."""
    if not destino_texto:
        return False
    if planta.nombre_normalizado == normalizar_nombre_planta(destino_texto):
        return True
    # El documento suele imprimir la DIRECCIÓN completa, no el nombre
    # corto de la planta -- mismo criterio ya usado en todo Atlas para
    # "¿esta dirección confirmada coincide con el texto documental?"
    # (ver revalidar_motivo_destino_ya_confirmado_sin_ocr): la primera
    # porción de la dirección registrada (antes de la primera coma)
    # aparece dentro del texto documental.
    destino_texto_normalizado = normalizar_nombre_destino(destino_texto)
    calle = normalizar_nombre_destino(str(planta.direccion or "").split(",", 1)[0])
    return bool(calle) and calle in destino_texto_normalizado


def resolver_planta_alternativa_por_categoria(
    *, planta_documental: Planta, categoria: str, plantas: Iterable[Planta], destino_texto: str = "",
) -> Planta | None:
    """Universal por diseño (mismo criterio que el resto del módulo --
    nunca conoce ninguna empresa/material en particular, sólo compara
    `categorias_permitidas` -- dato de catálogo, nunca lógica de Core):
    cuando la planta que indica el documento es INCOMPATIBLE con la
    categoría real de la carga, busca si existe EXACTAMENTE una planta
    alternativa vigente (CONFIRMADA+ACTIVA) cuya `categorias_permitidas`
    SÍ incluya esa categoría -- proceso de eliminación, nunca preferencia
    ni cercanía. Se abstiene (``None``, nunca adivina) si:
    - la planta documental no resultó realmente INCOMPATIBLE (nada que
      resolver por este camino);
    - hay cero o más de una planta alternativa compatible (ambigüedad
      real -- queda para `ORIGEN_NO_CONFIRMADO`);
    - la única candidata compatible es, ella misma, el destino del
      despacho (`destino_texto`) -- eso es evidencia de un TRASLADO
      INTERNO hacia esa planta, nunca un despacho a cliente DESDE ella
      (caso real: barras despachadas hacia la propia planta candidata no
      prueban que la carga salió de ahí)."""
    if evaluar_compatibilidad_planta_categoria(planta_documental, categoria) != INCOMPATIBLE:
        return None
    candidatas = [
        p for p in plantas
        if p.planta_id != planta_documental.planta_id
        and _planta_vigente(p)
        and evaluar_compatibilidad_planta_categoria(p, categoria) == COMPATIBLE
        and not _es_el_propio_destino(p, destino_texto)
    ]
    return candidatas[0] if len(candidatas) == 1 else None


# Bloque ORIGEN V3 -- CONVERGENCIA DE EVIDENCIA ANTES DE PREGUNTAR: causa
# raíz sistémica real (464730, 464631, 464529 -- lote 2). A diferencia de
# `resolver_planta_alternativa_por_categoria` (exige una planta
# DOCUMENTAL ya identificada e INCOMPATIBLE que "eliminar"), estos tres
# casos reales nunca tuvieron ningún origen informado por Mobile NI por
# el encabezado documental -- `resolver_planta_origen` se rendía de
# inmediato ("SIN_EVIDENCIA_GPS", un motivo genérico que ni siquiera
# refleja que GPS corrió después y encontró 0% de solape/conflicto) sin
# nunca cruzar la categoría real de la carga contra el catálogo, aunque
# esa evidencia por sí sola ya bastaba (B HORMIGON/barras y ALAMBRON/
# rollos hacia un cliente externo sólo los despacha AZA COLINA -- dato
# YA declarado en `categorias_permitidas`, nunca lógica nueva por
# empresa). Misma regla de "traslado interno" que la función hermana --
# nunca decide con SIN_REGLA (categoría no determinada o planta sin
# `categorias_permitidas` configuradas nunca cuenta como evidencia).
def resolver_planta_unica_por_categoria(
    *, categoria: str, plantas: Iterable[Planta], destino_texto: str = "",
) -> Planta | None:
    """Cuando NINGÚN origen fue informado (ni Mobile ni documento):
    resuelve por categoría SOLA si, y sólo si, existe EXACTAMENTE una
    planta vigente (CONFIRMADA+ACTIVA) cuyo `categorias_permitidas`
    declare explícitamente esa categoría -- nunca cuando ninguna o más
    de una calzan (`evaluar_compatibilidad_planta_categoria` ya
    distingue SIN_REGLA de COMPATIBLE: SIN_REGLA nunca cuenta acá).
    Misma abstención por traslado interno que `resolver_planta_
    alternativa_por_categoria` (`destino_texto` == la propia planta
    candidata)."""
    candidatas = [
        p for p in plantas
        if _planta_vigente(p)
        and evaluar_compatibilidad_planta_categoria(p, categoria) == COMPATIBLE
        and not _es_el_propio_destino(p, destino_texto)
    ]
    return candidatas[0] if len(candidatas) == 1 else None


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
