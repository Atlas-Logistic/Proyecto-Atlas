"""Procesamiento reanudable de carpetas de guías de despacho."""

from __future__ import annotations

import csv
import logging
import re
import time
import unicodedata
from datetime import date
from enum import Enum
from pathlib import Path
from typing import Callable, Iterable, Mapping

from atlas_core.catalogos import (
    buscar_chofer_por_nombre_exacto,
    buscar_chofer_por_rut,
    buscar_empresa_por_rut,
    cargar_catalogo_json,
    enriquecer_datos_con_catalogos,
    normalizar_rut,
    registrar_alias_seguro,
    resolver_nombre_chofer_difuso,
    resolver_nombre_empresa_difuso,
    resolver_patente_canonica,
)
from atlas_core.normalizacion_semantica import normalizar_nombre_societario
from atlas_core.validadores import EstadoValidacion, validar_rut_chileno
from atlas_core.clasificador_material import clasificar_material
from atlas_core.experimento_numero_guia_contextual import decidir_bloques_ocr
from atlas_core.extractor import (
    _chofer_lineal_contaminado,
    _consensuar_transporte_focal,
    _extraer_asociaciones_geometricas,
    _extraer_fecha_geometrico,
    _extraer_identidad_cliente_recortada_geometrica,
    _extraer_patentes_geometrico,
    _extraer_rut_chofer_geometrico,
    _extraer_rut_cliente_geometrico,
    _extraer_transporte_geometrico,
    _extraer_chofer_geometrico,
    _patente_valida,
    extraer_datos,
)
from atlas_core.ocr import (
    ALLOWLIST_FECHA,
    ALLOWLIST_TRANSPORTE,
    _leer_fecha_focal,
    _leer_transporte_focal,
    crear_lector_ocr,
    leer_bloques_imagen,
    leer_texto_imagen,
)
from atlas_core.ocr_provider import crear_proveedor_ocr
from atlas_core.catalogo_plantas import CatalogoPlantas
from atlas_core.catalogo_clientes import (
    CatalogoClientes,
    ErrorCatalogoClientes,
    EstadoBusquedaCliente,
    EstadoCalidadCliente,
    EstadoVigenciaCliente,
    normalizar_rut_cliente,
)
from atlas_core.catalogo_obras_destinos import (
    CatalogoObrasDestinos,
    ErrorCatalogoObrasDestinos,
    ResolucionObraDestino,
)
from atlas_core.rutas.destino_entrega import (
    CAMPOS_ENTREGA_DOCUMENTO,
    calcular_ruta_con_planta_conocida,
    resolver_entrega_documento,
)
from atlas_core.telemetria.modelos import EstadoSeleccionRecorrido
from atlas_core.telemetria.seleccion_recorrido import (
    ORIGEN_GPS_CONFIRMADO,
    ORIGEN_GPS_CONFLICTO,
    ORIGEN_GPS_ESTADIA_SIN_PLANTA,
    ORIGEN_GPS_NO_DETERMINADO,
)
from atlas_core.telemetria.enriquecimiento import (
    CAMPOS_TELEMETRIA_DOCUMENTO,
    enriquecer_documento_con_telemetria,
)


logger = logging.getLogger(__name__)


EXTENSIONES_PERMITIDAS = frozenset(
    {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff"}
)
RUTA_CATALOGO_CHOFERES = Path("catalogos/choferes.json")

# Bloque E2E R1.1: código ISO 3166-1 alfa-2 del país de operación actual de
# Atlas (documentos AZA, todos chilenos) -- usado como filtro estructurado
# de geocodificación (`OpenRouteService(pais=...)`, `boundary.country` en
# Pelias) SOLO cuando `procesar_archivo`/`procesar_carpeta` construyen el
# proveedor de rutas por defecto. Parámetro explícito y sustituible, no un
# hardcode enterrado en el geocodificador: cualquier llamador puede pasar
# `pais_operacion` distinto, o inyectar su propio `proveedor_rutas` y no
# usar este valor en absoluto (ver límites multiempresa, Bloque N).
PAIS_OPERACION_PREDETERMINADO = "CL"

# Guarda de plausibilidad temporal: cuando el llamador no entrega
# fecha_desde/fecha_hasta explícitos, igual se descartan años que ningún
# documento real de Atlas podría tener (OCR corrompido, p. ej. "7025").
# Centralizado aquí para no hardcodear el rango dentro de los regex de
# extraer_fecha ni duplicarlo entre la pasada estricta y la tolerante.
ANIO_MINIMO_PLAUSIBLE = 2015
ANIO_MAXIMO_PLAUSIBLE = 2035
FECHA_MINIMA_PLAUSIBLE = date(ANIO_MINIMO_PLAUSIBLE, 1, 1)
FECHA_MAXIMA_PLAUSIBLE = date(ANIO_MAXIMO_PLAUSIBLE, 12, 31)

# Umbral de confianza para el consenso de fecha por OCR focal (F2.2): un
# candidato con >=2 variantes coincidentes solo se acepta si TODAS esas
# variantes tienen confianza >= este umbral; si no, se prefiere abstenerse
# ("No encontrado") antes que aceptar un consenso débil. Validado sobre una
# muestra real limitada (7 casos con caja geométrica de la muestra histórica
# de 30 guías) — separa con margen los votos correctos observados (~0.90-0.98
# de confianza) de los votos incorrectos observados (~0.47-0.82), pero NO
# demuestra suficiencia general del motor OCR; requiere seguimiento con más
# muestra antes de tratarse como calibración definitiva.
CONFIANZA_MINIMA_FECHA_FOCAL = 0.70

# Bloque O1 -- rango operativo plausible de peso de carga (kg), a
# propósito generoso ("sin usar límites demasiado estrechos"): cubre
# holgadamente toda carga real observada en la muestra de validación
# (994-27.983 kg) sin acercarse al límite legal de un camión en Chile
# (~45.000 kg combinado tracto+rampla+carga). Un valor fuera de este
# rango se trata como no confiable (posible error de OCR) antes que
# propagarlo -- abstención preferible a un dato erróneo.
PESO_KG_MINIMO_PLAUSIBLE = 1
PESO_KG_MAXIMO_PLAUSIBLE = 60000


def _normalizar_peso_kg(peso_crudo: str | None) -> str:
    """Convierte el peso crudo ya extraído (formato chileno, p. ej.
    "7.756,00") a un valor numérico limpio en kg ("7756"). Nunca inventa:
    sin valor, no numérico o fuera del rango operativo plausible ->
    "No encontrado".

    Tolera que el OCR confunda "." y "," entre sí como separador de
    miles (caso real confirmado: "6,971,00" en vez de "6.971,00") -- se
    parte el valor por cualquiera de los dos separadores y, si el último
    grupo son puros ceros de 2-3 dígitos (los decimales, siempre
    observados en cero -- kilogramos enteros), se descarta; el resto se
    concatena como la parte entera, sin importar qué carácter separaba
    cada grupo."""
    texto = str(peso_crudo or "").strip()
    if not texto or texto == "No encontrado":
        return "No encontrado"
    grupos = [grupo for grupo in re.split(r"[.,]", texto) if grupo]
    if not grupos or not all(grupo.isdigit() for grupo in grupos):
        return "No encontrado"
    if len(grupos) >= 2 and len(grupos[-1]) in (2, 3) and set(grupos[-1]) <= {"0"}:
        grupos = grupos[:-1]
    parte_entera = "".join(grupos)
    if not parte_entera.isdigit():
        return "No encontrado"
    valor = int(parte_entera)
    if not (PESO_KG_MINIMO_PLAUSIBLE <= valor <= PESO_KG_MAXIMO_PLAUSIBLE):
        return "No encontrado"
    return str(valor)


def _calcular_permanencia_minutos(hora_entrada: str | None, hora_salida: str | None) -> str:
    """`permanencia_minutos = hora_salida_aza - hora_entrada_aza`, en
    minutos, solo si ambas horas son válidas. Bloque O1, Fase E: nunca
    asume automáticamente un cruce de medianoche (+24h) sin evidencia de
    fecha que lo respalde -- a nivel de documento no hay evidencia de
    fechas de entrada/salida distintas disponible, así que una salida
    anterior a la entrada se marca "No determinada" (motivo trazable) en
    vez de inventar una permanencia negativa o forzar +24h."""
    if hora_entrada in (None, "", "No encontrado") or hora_salida in (None, "", "No encontrado"):
        return "No encontrado"
    try:
        hora_e, minuto_e = (int(x) for x in str(hora_entrada).split(":"))
        hora_s, minuto_s = (int(x) for x in str(hora_salida).split(":"))
    except (ValueError, AttributeError):
        return "No encontrado"
    minutos_entrada = hora_e * 60 + minuto_e
    minutos_salida = hora_s * 60 + minuto_s
    if minutos_salida < minutos_entrada:
        return "No determinada"
    return str(minutos_salida - minutos_entrada)


def _parsear_fecha_dd_mm_yyyy(texto: str | None) -> date | None:
    """Bloque TELEMETRÍA T2 -- `fecha_actual` ya viene en este formato
    (DD-MM-YYYY) desde `extraer_fecha`; se parsea solo para consultar
    telemetría por fecha, nunca para reinterpretar el dato documental."""
    coincidencia = re.fullmatch(r"(\d{2})-(\d{2})-(\d{4})", str(texto or "").strip())
    if not coincidencia:
        return None
    dia, mes, anio = (int(x) for x in coincidencia.groups())
    try:
        return date(anio, mes, dia)
    except ValueError:
        return None


def _combinar_fecha_hora(fecha: date, hora_texto: str | None):
    """Bloque TELEMETRÍA T2 -- combina la fecha documental con una hora
    "HH:MM" ya normalizada (`extraer_datos`); `None` si la hora está
    ausente/es inválida -- nunca inventa una hora."""
    from datetime import datetime

    texto = str(hora_texto or "").strip()
    coincidencia = re.fullmatch(r"([01]?\d|2[0-3]):([0-5]\d)", texto)
    if not coincidencia:
        return None
    hora, minuto = (int(x) for x in coincidencia.groups())
    return datetime(fecha.year, fecha.month, fecha.day, hora, minuto)


COLUMNAS = [
    "archivo",
    "estado_procesamiento",
    "error",
    "numero_guia",
    "numero_transporte",
    "fecha",
    "chofer",
    "rut_chofer",
    "cliente",
    "obra_destino",
    "patente_tracto",
    "patente_rampla",
    "descripcion_material",
    "tipo_carga",
    "indicador_revision",
    # Bloque O1: peso y horarios operacionales de planta. Agregadas al
    # final -- backward-compatible, un lector de CSV por nombre de
    # columna (csv.DictReader, como usa todo el pipeline) no se ve
    # afectado por columnas nuevas al final del encabezado.
    "peso_kg",
    "hora_entrada_aza",
    "hora_salida_aza",
    "permanencia_minutos",
    # Bloque ESTADOS S2: calidad del dato (motivos EXPLÍCITOS de por qué
    # requiere revisión, si acaso) separada de trazabilidad del método
    # (cómo se obtuvo el valor final) -- ver `MotivoRevisionDocumento` /
    # `MetodoObtencionDocumento`. Agregadas al final -- backward-compatible,
    # `indicador_revision` conserva su semántica REVISAR/OK de siempre.
    "motivos_revision_documento",
    "metodos_recuperacion_documento",
    # Bloque E2E R1: enriquecimiento logístico por documento (planta origen
    # documental + DESPACHAR A + geocodificación + ORS driving-hgv).
    # Agregadas al final -- backward-compatible; sin catálogo de plantas ni
    # proveedor de rutas conectado, quedan vacías y el CSV es idéntico al
    # de antes de este bloque. `despachar_a_crudo` es la única de este
    # grupo que no depende de red: es lectura local del propio OCR, igual
    # que `obra_destino`.
    *CAMPOS_ENTREGA_DOCUMENTO,
    # Bloque TELEMETRÍA T2: enriquecimiento GPS opcional, resumen (sin
    # breadcrumbs -- viven en la caché de telemetría, no en este CSV).
    # Agregadas al final -- backward-compatible; sin
    # `servicio_telemetria` conectado, quedan vacías y el CSV es idéntico
    # al de antes de este bloque.
    *CAMPOS_TELEMETRIA_DOCUMENTO,
]

Procesador = Callable[[Path], Mapping[str, object]]


def descubrir_archivos(carpeta: str | Path) -> list[Path]:
    """Devuelve archivos procesables de la carpeta y sus subcarpetas."""
    raiz = Path(carpeta)
    if not raiz.exists():
        raise FileNotFoundError(f"La carpeta no existe: {raiz}")
    if not raiz.is_dir():
        raise NotADirectoryError(f"La ruta no es una carpeta: {raiz}")

    return sorted(
        (
            ruta
            for ruta in raiz.rglob("*")
            if ruta.is_file() and ruta.suffix.lower() in EXTENSIONES_PERMITIDAS
        ),
        key=lambda ruta: ruta.relative_to(raiz).as_posix().casefold(),
    )


def _normalizar(texto: object) -> str:
    valor = unicodedata.normalize("NFD", str(texto or ""))
    return "".join(c for c in valor if unicodedata.category(c) != "Mn").upper()


def extraer_descripcion_material(textos: Iterable[str]) -> str:
    """Conserva líneas OCR con evidencia explícita de material."""
    terminos = re.compile(r"\b(HORMIGON|BARRAS?|ROLLOS?|ALAMBRON|BOBINAS?)\b")
    encontradas: list[str] = []
    for bloque in textos:
        for linea in str(bloque).splitlines():
            limpia = re.sub(r"\s+", " ", linea).strip()
            if limpia and terminos.search(_normalizar(limpia)):
                encontradas.append(limpia)
    return " | ".join(dict.fromkeys(encontradas))


def _clasificar_contexto_fecha(
    contexto: str,
    inicio_candidato: int,
    fin_candidato: int,
) -> tuple[int, str]:
    etiquetas = (
        (re.compile(r"FECHA\s+(?:DE\s+)?EMISION"), 0, "FECHA DE EMISION"),
        (re.compile(r"FECHA\s+(?:DE\s+)?SALIDA"), 1, "FECHA SALIDA"),
        (re.compile(r"FECHA\s+(?:DE\s+)?LLEGADA"), 2, "FECHA LLEGADA"),
        (re.compile(r"\bFECHA\b"), 2, "OTRA ETIQUETA DE FECHA"),
    )
    encontradas: list[tuple[int, int, int, str]] = []
    for patron, prioridad, tipo in etiquetas:
        for coincidencia in patron.finditer(contexto):
            if coincidencia.end() <= inicio_candidato:
                distancia = inicio_candidato - coincidencia.end()
                despues = 0
            elif coincidencia.start() >= fin_candidato:
                distancia = coincidencia.start() - fin_candidato
                despues = 1
            else:
                distancia = 0
                despues = 0
            encontradas.append((distancia, despues, prioridad, tipo))

    if encontradas:
        _, _, prioridad, tipo = min(encontradas)
        return prioridad, tipo
    return 3, "GLOBAL"


def _limites_temporales_efectivos(
    fecha_desde: date | None,
    fecha_hasta: date | None,
) -> tuple[date, date]:
    """Resuelve los límites reales a aplicar durante la extracción de fecha.

    Un límite explícito siempre prevalece. Cuando el llamador no entrega
    fecha_desde y/o fecha_hasta, se completa con la guarda de plausibilidad
    temporal por defecto en vez de dejar ese lado sin cota.
    """
    efectivo_desde = fecha_desde if fecha_desde is not None else FECHA_MINIMA_PLAUSIBLE
    efectivo_hasta = fecha_hasta if fecha_hasta is not None else FECHA_MAXIMA_PLAUSIBLE
    return efectivo_desde, efectivo_hasta


def _valor_fecha_a_date(valor: str) -> date | None:
    """Convierte un valor ya devuelto por extraer_fecha a un date comparable.

    Solo se usa para comparar variantes focales entre sí (p. ej. "01-07-2026"
    contra "01/07/2026"); no reimplementa ni reemplaza el reconocimiento de
    extraer_fecha, que ya validó el valor antes de devolverlo.
    """
    coincidencia = re.fullmatch(r"(\d{2})[-/](\d{2})[-/](\d{4})", valor)
    if coincidencia:
        dia, mes, anio = (int(parte) for parte in coincidencia.groups())
    else:
        coincidencia = re.fullmatch(r"(\d{4})[-/](\d{2})[-/](\d{2})", valor)
        if not coincidencia:
            return None
        anio, mes, dia = (int(parte) for parte in coincidencia.groups())
    try:
        return date(anio, mes, dia)
    except ValueError:
        return None


def _fecha_dmy_valida(
    valor: str,
    fecha_desde: date | None,
    fecha_hasta: date | None,
) -> bool:
    dia, mes, anio = (int(parte) for parte in re.split(r"[-/]", valor))
    try:
        fecha_candidata = date(anio, mes, dia)
    except ValueError:
        return False
    if fecha_desde is not None and fecha_candidata < fecha_desde:
        return False
    if fecha_hasta is not None and fecha_candidata > fecha_hasta:
        return False
    return True


def _normalizaciones_fecha_unicas(
    propuestas: list[dict[str, int | str]],
) -> list[dict[str, int | str]]:
    """Conserva solo transformaciones con una interpretacion por tramo OCR."""
    por_tramo: dict[tuple[int, int, str], list[dict[str, int | str]]] = {}
    for propuesta in propuestas:
        clave = (
            int(propuesta["posicion"]),
            int(propuesta["fin"]),
            str(propuesta["valor_original"]),
        )
        por_tramo.setdefault(clave, []).append(propuesta)

    unicas: list[dict[str, int | str]] = []
    for grupo in por_tramo.values():
        valores = {str(propuesta["valor_normalizado"]) for propuesta in grupo}
        if len(valores) == 1:
            unicas.append(grupo[0])
    return unicas


def extraer_fecha(
    textos: Iterable[str],
    fecha_desde: date | None = None,
    fecha_hasta: date | None = None,
) -> str:
    """Extrae el mejor candidato que representa una fecha de calendario válida."""
    if (
        fecha_desde is not None
        and fecha_hasta is not None
        and fecha_desde > fecha_hasta
    ):
        raise ValueError("fecha_desde no puede ser posterior a fecha_hasta")

    fecha_desde_efectiva, fecha_hasta_efectiva = _limites_temporales_efectivos(
        fecha_desde, fecha_hasta
    )

    texto = "\n".join(str(valor) for valor in textos)
    texto_normalizado = _normalizar(texto)
    patron_fecha = re.compile(
        r"\b(?:"
        r"\d{2}(?P<separador_dmy>[-/])\d{2}(?P=separador_dmy)\d{4}"
        r"|"
        r"\d{4}(?P<separador_iso>[-/])\d{2}(?P=separador_iso)\d{2}"
        r")\b"
    )

    candidatos: list[dict[str, int | str]] = []
    for coincidencia in patron_fecha.finditer(texto):
        valor = coincidencia.group(0)
        partes = [int(parte) for parte in re.split(r"[-/]", valor)]
        if coincidencia.group("separador_iso") is not None:
            anio, mes, dia = partes
        else:
            dia, mes, anio = partes

        try:
            fecha_candidata = date(anio, mes, dia)
        except ValueError:
            continue
        if fecha_candidata < fecha_desde_efectiva or fecha_candidata > fecha_hasta_efectiva:
            continue

        inicio_contexto = max(0, coincidencia.start() - 120)
        fin_contexto = min(len(texto_normalizado), coincidencia.end() + 40)
        contexto = texto_normalizado[inicio_contexto:fin_contexto]
        prioridad, tipo_contexto = _clasificar_contexto_fecha(
            contexto,
            coincidencia.start() - inicio_contexto,
            coincidencia.end() - inicio_contexto,
        )

        candidatos.append(
            {
                "valor": valor,
                "valor_original": valor,
                "valor_normalizado": valor,
                "posicion": coincidencia.start(),
                "contexto": contexto,
                "tipo_contexto": tipo_contexto,
                "prioridad": prioridad,
                "regla_aplicada": "ESTRICTA",
                "normalizado": 0,
            }
        )

    patrones_tolerantes = (
        (
            re.compile(
                r"(?<!\d)(?P<dia>\d{2})(?P<sep>[-/])"
                r"(?P<mes>\d{2})(?P<anio>\d{4})(?!\d)"
            ),
            "INSERTAR_SEPARADOR_ANTES_ANIO",
            lambda m: (
                f'{m.group("dia")}{m.group("sep")}{m.group("mes")}'
                f'{m.group("sep")}{m.group("anio")}'
            ),
        ),
        (
            re.compile(
                r"(?<!\d)(?P<dia>\d{2})(?P<sep>[-/])"
                r"(?P<mes>\d{2}) (?P<anio>\d{4})(?!\d)"
            ),
            "SUSTITUIR_ESPACIO_POR_SEPARADOR",
            lambda m: (
                f'{m.group("dia")}{m.group("sep")}{m.group("mes")}'
                f'{m.group("sep")}{m.group("anio")}'
            ),
        ),
        (
            re.compile(
                r"(?<!\d)(?P<dia>\d{2})(?P<inesperado>[^\s/-])"
                r"(?P<mes>\d{2})(?P<sep>[-/])(?P<anio>\d{4})(?!\d)"
            ),
            "SUSTITUIR_CARACTER_POR_SEPARADOR",
            lambda m: (
                f'{m.group("dia")}{m.group("sep")}{m.group("mes")}'
                f'{m.group("sep")}{m.group("anio")}'
            ),
        ),
    )
    propuestas: list[dict[str, int | str]] = []
    for patron, regla, normalizar in patrones_tolerantes:
        for coincidencia in patron.finditer(texto):
            inicio_contexto = max(0, coincidencia.start() - 120)
            fin_contexto = min(len(texto_normalizado), coincidencia.end() + 40)
            contexto = texto_normalizado[inicio_contexto:fin_contexto]
            prioridad, tipo_contexto = _clasificar_contexto_fecha(
                contexto,
                coincidencia.start() - inicio_contexto,
                coincidencia.end() - inicio_contexto,
            )
            if prioridad == 3:
                continue
            propuestas.append(
                {
                    "valor": normalizar(coincidencia),
                    "valor_original": coincidencia.group(0),
                    "valor_normalizado": normalizar(coincidencia),
                    "posicion": coincidencia.start(),
                    "fin": coincidencia.end(),
                    "contexto": contexto,
                    "tipo_contexto": tipo_contexto,
                    "prioridad": prioridad,
                    "regla_aplicada": regla,
                    "normalizado": 1,
                }
            )

    for propuesta in _normalizaciones_fecha_unicas(propuestas):
        valor = str(propuesta["valor_normalizado"])
        if _fecha_dmy_valida(valor, fecha_desde_efectiva, fecha_hasta_efectiva):
            candidatos.append(propuesta)

    if candidatos:
        seleccionado = min(
            candidatos,
            key=lambda candidato: (
                int(candidato["normalizado"]),
                int(candidato["prioridad"]),
                int(candidato["posicion"]),
            ),
        )
        return str(seleccionado["valor"])
    return "No encontrado"


# Guarda documental (M1): señal estructural mínima de degradación global del
# documento. Cuenta cuántos de estos campos volvieron vacíos/"No encontrado"
# a la vez; si son demasiados, el documento probablemente esté degradado en
# su conjunto (mala foto, guía ilegible) y no solo en un campo puntual. Esta
# señal solo puede EMPUJAR indicador_revision hacia "REVISAR" — nunca
# modifica un valor ya extraído (incluida la fecha) ni lo descarta.
CAMPOS_GUARDA_DOCUMENTAL = (
    "número de guía", "número de transporte", "cliente", "obra destino",
    "chofer", "patente del tracto", "patente del carro",
)
UMBRAL_CAMPOS_FALTANTES_DOCUMENTO_DEGRADADO = 5


def _documento_degradado(datos: dict, descripcion: str) -> bool:
    faltantes = sum(
        1 for campo in CAMPOS_GUARDA_DOCUMENTAL
        if datos.get(campo) in {None, "", "No encontrado"}
    )
    if not descripcion:
        faltantes += 1
    return faltantes >= UMBRAL_CAMPOS_FALTANTES_DOCUMENTO_DEGRADADO


# Bloque ESTADOS S2: separa explícitamente CALIDAD DEL DATO (¿requiere
# revisión humana, y por qué?) de TRAZABILIDAD DEL MÉTODO (¿cómo se obtuvo
# el valor final?). Antes de este bloque, el mero USO de un método de
# recuperación conservador (geometría, fuzzy, homologación, consenso focal)
# forzaba `indicador_revision="REVISAR"` sin dejar rastro de la causa real
# -- ver auditoría real en estado_revision_eval/ (bloque ESTADOS S1): 442
# documentos "REVISAR" correspondían a viajes que el reporte productivo
# consideraba CONFIRMADO, y ~27% de una muestra representativa de esos 442
# resultaron ser recuperaciones técnicas correctas y ya corroboradas
# (REVISAR_TECNICO), no problemas reales (REVISAR_LEGITIMO).
#
# Un método nunca fuerza revisión por sí solo. Solo la fuerzan: un dato
# realmente ausente, una ambigüedad real (varios candidatos igual de
# plausibles), un conflicto, o una recuperación SIN corroboración
# independiente suficiente (ver cada motivo abajo para su criterio
# concreto). La trazabilidad del método SIEMPRE se conserva, se haya
# corroborado o no -- nunca se descarta la evidencia de cómo se obtuvo el
# valor final.
class MetodoObtencionDocumento(str, Enum):
    """Cómo se obtuvo el valor final de uno o más campos -- puramente
    informativo, nunca decide por sí solo si el documento requiere
    revisión (ver `MotivoRevisionDocumento`)."""

    GEOMETRICO = "GEOMETRICO"
    CONTEXTUAL = "CONTEXTUAL"
    FUZZY = "FUZZY"
    HOMOLOGADO = "HOMOLOGADO"
    CORREGIDO = "CORREGIDO"
    FOCAL = "FOCAL"
    # Bloque ESTADOS S2.2: `enriquecer_datos_con_catalogos()` (mecanismo
    # preexistente, anterior a S1/S2) puede cambiar cliente/chofer/obra
    # destino contra los catálogos maestros -- ver criterio de
    # corroboración por campo junto a cada uso en `procesar_archivo()`.
    CATALOGO = "CATALOGO"
    CATALOGO_OBRA_DESTINO = "CATALOGO_OBRA_DESTINO"
    # Bloque INTELIGENCIA N1: limpieza estructural de un nombre de entidad
    # (sufijos societarios/prefijo suelto, ver `normalizar_nombre_societario`)
    # -- nunca decide identidad, solo corrige una corrupción OCR segura del
    # propio texto documental.
    NORMALIZADO = "NORMALIZADO"


class MotivoRevisionDocumento(str, Enum):
    """Motivo EXPLÍCITO por el que un documento requiere revisión humana.
    Nunca es el nombre de un método (eso vive en
    `MetodoObtencionDocumento`) -- cada motivo aquí representa una
    incertidumbre real: un campo clave ausente, una recuperación sin
    corroboración independiente, una ambigüedad real, o degradación
    documental."""

    GUIA_AUSENTE = "GUIA_AUSENTE"
    TRANSPORTE_AUSENTE = "TRANSPORTE_AUSENTE"
    CLIENTE_AUSENTE = "CLIENTE_AUSENTE"
    CHOFER_AUSENTE = "CHOFER_AUSENTE"
    DOCUMENTO_DEGRADADO = "DOCUMENTO_DEGRADADO"
    # Recuperado (geometría), pero sin una segunda señal independiente que
    # lo corrobore -- criterio concreto de corroboración documentado junto
    # a cada uso más abajo (RUT válido para cliente/chofer; catálogo para
    # patente). Sin esa segunda señal, un error de OCR en la recuperación
    # geométrica no tendría forma de detectarse.
    CLIENTE_SIN_CORROBORAR = "CLIENTE_SIN_CORROBORAR"
    CHOFER_SIN_CORROBORAR = "CHOFER_SIN_CORROBORAR"
    OBRA_DESTINO_SIN_CORROBORAR = "OBRA_DESTINO_SIN_CORROBORAR"
    PATENTE_SIN_HOMOLOGAR = "PATENTE_SIN_HOMOLOGAR"
    # Ambigüedad real (ALIAS con >1 candidato, o corrección OCR con >1
    # candidato igual de plausible) -- nunca se resuelve arbitrariamente.
    PATENTE_AMBIGUA = "PATENTE_AMBIGUA"
    # Informativo únicamente (ver MOTIVOS_NO_BLOQUEANTES) -- mismo
    # criterio ya establecido en el Bloque O1 para peso/horas: la ausencia
    # de un campo operacional secundario (no de identidad) se registra
    # pero nunca por sí sola invalida el documento completo.
    MATERIAL_AUSENTE = "MATERIAL_AUSENTE"
    # Bloque INTELIGENCIA N1 (Fase I) -- informativo únicamente: el cliente
    # trae un RUT chileno válido y un nombre documental consistente, pero
    # ese RUT no existe (todavía) en `empresas.json` ni el nombre calzó por
    # fuzzy contra ninguna entidad conocida. Nunca se inventa una identidad
    # -- se distingue explícitamente de "OCR dudoso" (CLIENTE_SIN_CORROBORAR)
    # porque la evidencia documental en sí es internamente consistente.
    CLIENTE_NUEVA_ENTIDAD_NO_CATALOGADA = "CLIENTE_NUEVA_ENTIDAD_NO_CATALOGADA"


MOTIVOS_NO_BLOQUEANTES = frozenset({
    MotivoRevisionDocumento.MATERIAL_AUSENTE.value,
    MotivoRevisionDocumento.CLIENTE_NUEVA_ENTIDAD_NO_CATALOGADA.value,
})


def _resolver_cliente_id_corroborado(
    carpeta_catalogos: str | Path,
    *,
    cliente_texto: str,
    rut_cliente: str,
    identidad_cliente_corroborada: bool,
) -> str | None:
    """Resuelve una identidad ya corroborada al ID maestro, sin fuzzy."""
    catalogo = CatalogoClientes(Path(carpeta_catalogos) / "clientes.json")
    try:
        clientes = catalogo.listar()
        rut = normalizar_rut_cliente(rut_cliente)
    except ErrorCatalogoClientes:
        return None
    if rut:
        coincidencias = [
            cliente for cliente in clientes
            if cliente.rut == rut
            and cliente.estado_vigencia == EstadoVigenciaCliente.ACTIVO.value
            and cliente.estado_calidad == EstadoCalidadCliente.CONFIRMADO.value
        ]
        return coincidencias[0].cliente_id if len(coincidencias) == 1 else None
    if not identidad_cliente_corroborada:
        return None
    try:
        resultado = catalogo.buscar(cliente_texto)
    except ErrorCatalogoClientes:
        return None
    if (
        resultado.estado == EstadoBusquedaCliente.COINCIDENCIA
        and resultado.cliente is not None
        and resultado.cliente.estado_vigencia == EstadoVigenciaCliente.ACTIVO.value
    ):
        return resultado.cliente.cliente_id
    return None


def _corroborar_obra_destino_confirmada(
    carpeta_catalogos: str | Path,
    *,
    cliente_texto: str,
    rut_cliente: str,
    obra_documental: str,
    identidad_cliente_corroborada: bool,
) -> ResolucionObraDestino | None:
    """Consulta read-only una obra confirmada; ante cualquier duda, se abstiene."""
    obra = str(obra_documental or "").strip()
    if obra in {"", "No encontrado"}:
        return None
    obra = normalizar_nombre_societario(obra).valor_normalizado
    carpeta = Path(carpeta_catalogos)
    try:
        cliente_id = _resolver_cliente_id_corroborado(
            carpeta,
            cliente_texto=cliente_texto,
            rut_cliente=rut_cliente,
            identidad_cliente_corroborada=identidad_cliente_corroborada,
        )
        if cliente_id is None:
            return None
        return CatalogoObrasDestinos(
            ruta=carpeta / "obras_destinos.json",
            ruta_clientes=carpeta / "clientes.json",
            ruta_destinos=carpeta / "destinos_maestros.json",
        ).resolver_obra_destino_confirmada(
            cliente_id=cliente_id,
            nombre_obra=obra,
        )
    except (OSError, ValueError, ErrorCatalogoObrasDestinos):
        return None


def procesar_archivo(
    ruta: Path,
    lector_ocr: object = None,
    fecha_desde: date | None = None,
    fecha_hasta: date | None = None,
    proveedor: object = None,
    carpeta_catalogos: str | Path | None = None,
    proveedor_rutas: object = None,
    pais_operacion: str = PAIS_OPERACION_PREDETERMINADO,
    servicio_telemetria: object = None,
) -> dict[str, str]:
    """Procesa una guía reutilizando el OCR y extractor actuales.

    `servicio_telemetria` (Bloque TELEMETRÍA T2, opcional --
    `atlas_core.telemetria.servicio.ServicioTelemetria`): sin esto (por
    defecto), el documento se procesa exactamente igual que antes de este
    bloque -- telemetría es puramente opt-in, nunca automática por
    defecto ni obligatoria. Con un servicio conectado, se consulta SOLO
    cuando aporta valor real (planta sin determinar, o destino con
    ambigüedad real de geocodificación) -- nunca "para todo" (ver Fase I,
    política de eficiencia).

    `proveedor` (ProveedorOCR, opcional) permite usar cualquier motor OCR
    que cumpla el contrato de atlas_core.ocr_provider en vez de EasyOCR
    directo. Si no se entrega, el comportamiento es idéntico al anterior
    (EasyOCR vía `lector_ocr`) — no hay cambio de comportamiento por
    defecto.

    `proveedor_rutas` (Bloque E2E R1, opcional): objeto con el contrato de
    `atlas_core.rutas.proveedor.ProveedorRutas` (p. ej.
    `OpenRouteService()`) usado para geocodificar `DESPACHAR A` y calcular
    la ruta planta->entrega (`driving-hgv`). Sin `carpeta_catalogos` no se
    intenta nada de esto (no hay catálogo de plantas que resolver contra);
    con `carpeta_catalogos` pero sin `proveedor_rutas`, se construye un
    `OpenRouteService()` por defecto (lee `OPENROUTESERVICE_API_KEY` del
    entorno; sin credencial, se abstiene con motivo explícito -- nunca
    lanza). Este módulo nunca decide *cuál* proveedor de rutas usar salvo
    ese valor por defecto explícito y sustituible -- ver límites
    multiempresa en el bloque E2E R1."""

    def _leer_texto() -> list[str]:
        if proveedor is not None:
            return proveedor.leer_texto(ruta)
        return leer_texto_imagen(ruta, lector=lector_ocr)

    def _leer_bloques() -> list:
        if proveedor is not None:
            return proveedor.leer_bloques(ruta)
        return leer_bloques_imagen(ruta, lector=lector_ocr)

    def _leer_focal(caja, allowlist: str, funcion_easyocr) -> dict:
        if proveedor is not None:
            return proveedor.leer_focal(ruta, caja, allowlist=allowlist)
        return funcion_easyocr(ruta, caja, lector=lector_ocr)

    textos = _leer_texto()
    datos = (
        extraer_datos(textos, carpeta_catalogos)
        if carpeta_catalogos is not None
        else extraer_datos(textos)
    )
    # Bloque ESTADOS S2: `metodos_documento` es puramente informativo
    # (trazabilidad). `campos_geometricos_sin_corroborar` acumula qué
    # campos de identidad se recuperaron por geometría en ESTE documento
    # -- se resuelve más abajo, después de conocer el estado final de
    # RUT/homologación, si cada uno quedó corroborado o no.
    metodos_documento: set[str] = set()
    motivos_documento: list[str] = []

    def _motivo(motivo: MotivoRevisionDocumento) -> None:
        if motivo.value not in motivos_documento:
            motivos_documento.append(motivo.value)

    campos_geometricos_sin_corroborar: set[str] = set()
    cliente_corroborado_n1 = False
    obra_destino_corroborada = None
    chofer_geometrico = False
    patentes_geometricas_sin_homologar: set[str] = set()
    bloques_guia = None
    campos_ausentes = any(
        datos.get(campo) in {None, "", "No encontrado"}
        for campo in (
            "cliente", "obra destino", "número de transporte",
            "patente del tracto", "patente del carro", "RUT del cliente",
            "RUT del chofer",
        )
    ) or datos.get("chofer") in {None, "", "No encontrado"} or _chofer_lineal_contaminado(datos.get("chofer"))
    if campos_ausentes:
        try:
            bloques_guia = _leer_bloques()
            asociaciones = _extraer_asociaciones_geometricas(bloques_guia)
            if datos.get("cliente") in {None, "", "No encontrado"}:
                identidad_recortada = _extraer_identidad_cliente_recortada_geometrica(
                    bloques_guia
                )
                if identidad_recortada:
                    asociaciones["cliente"] = identidad_recortada["cliente"]
                    if datos.get("RUT del cliente") in {None, "", "No encontrado"}:
                        datos["RUT del cliente"] = identidad_recortada["rut"]
                    metodos_documento.add(MetodoObtencionDocumento.GEOMETRICO.value)
            for campo in ("cliente", "obra destino"):
                if datos.get(campo) in {None, "", "No encontrado"} and asociaciones.get(campo):
                    datos[campo] = asociaciones[campo]
                    metodos_documento.add(MetodoObtencionDocumento.GEOMETRICO.value)
                    campos_geometricos_sin_corroborar.add(campo)
                    logger.info("%s recuperado mediante asociacion-geometrica-conservadora-v1", campo)
            if datos.get("RUT del cliente") in {None, "", "No encontrado"}:
                decision_rut_cliente = _extraer_rut_cliente_geometrico(bloques_guia)
                if decision_rut_cliente.get("valor"):
                    datos["RUT del cliente"] = decision_rut_cliente["valor"]
                    metodos_documento.add(MetodoObtencionDocumento.GEOMETRICO.value)
                    logger.info("RUT del cliente recuperado mediante rut-cliente-geometrico-conservador-v1")
            chofer_actual = datos.get("chofer", "No encontrado")
            if chofer_actual in {None, "", "No encontrado"} or _chofer_lineal_contaminado(chofer_actual):
                decision_chofer = _extraer_chofer_geometrico(bloques_guia)
                if decision_chofer.get("valor"):
                    datos["chofer"] = decision_chofer["valor"]
                    metodos_documento.add(MetodoObtencionDocumento.GEOMETRICO.value)
                    chofer_geometrico = True
                    logger.info("chofer recuperado mediante asociacion-geometrica-conservadora-v1")
            rut_chofer_actual = str(datos.get("RUT del chofer", "No encontrado"))
            if rut_chofer_actual in {"", "No encontrado"}:
                decision_rut_chofer = _extraer_rut_chofer_geometrico(bloques_guia)
                if decision_rut_chofer.get("valor"):
                    datos["RUT del chofer"] = decision_rut_chofer["valor"]
                    metodos_documento.add(MetodoObtencionDocumento.GEOMETRICO.value)
                    logger.info("rut_chofer recuperado mediante rut-chofer-geometrico-conservador-v1")
            transporte_actual = str(datos.get("número de transporte", "No encontrado"))
            if not re.fullmatch(r"\d{10}", transporte_actual):
                decision_transporte = _extraer_transporte_geometrico(
                    bloques_guia, incluir_traza=True
                )
                if decision_transporte.get("valor"):
                    requiere_focal = bool(decision_transporte.get("corregido")) or float(
                        decision_transporte.get("confianza", 0.0)
                    ) < 0.65
                    if requiere_focal:
                        evidencia_focal = _leer_focal(
                            decision_transporte["caja"], ALLOWLIST_TRANSPORTE, _leer_transporte_focal
                        )
                        consenso = _consensuar_transporte_focal(
                            evidencia_focal["lecturas"],
                            str(decision_transporte.get("texto_global", "")),
                        )
                        if consenso.get("valor"):
                            datos["número de transporte"] = consenso["valor"]
                            # Corroborado por diseño: _consensuar_transporte_focal
                            # exige >=2 lecturas focales concordantes con
                            # confianza suficiente (ver su propio umbral) --
                            # nunca acepta una lectura focal aislada. No
                            # requiere un motivo de revisión adicional.
                            metodos_documento.add(MetodoObtencionDocumento.CORREGIDO.value)
                            metodos_documento.add(MetodoObtencionDocumento.FOCAL.value)
                            logger.info("numero_transporte recuperado mediante consenso-focal-v1")
                    else:
                        datos["número de transporte"] = decision_transporte["valor"]
                        metodos_documento.add(MetodoObtencionDocumento.GEOMETRICO.value)
                        logger.info("numero_transporte recuperado mediante transporte-contextual-numerico-v1")
            patente_tracto_actual = str(datos.get("patente del tracto", "No encontrado"))
            patente_carro_actual = str(datos.get("patente del carro", "No encontrado"))
            if patente_tracto_actual == "No encontrado" or patente_carro_actual == "No encontrado":
                decision_patentes = _extraer_patentes_geometrico(bloques_guia)
                if patente_tracto_actual == "No encontrado" and decision_patentes.get("tracto"):
                    datos["patente del tracto"] = decision_patentes["tracto"]
                    metodos_documento.add(MetodoObtencionDocumento.GEOMETRICO.value)
                    patentes_geometricas_sin_homologar.add("patente del tracto")
                    logger.info("patente_tracto recuperado mediante patentes-geometrico-conservador-v1")
                if patente_carro_actual == "No encontrado" and decision_patentes.get("carro"):
                    datos["patente del carro"] = decision_patentes["carro"]
                    metodos_documento.add(MetodoObtencionDocumento.GEOMETRICO.value)
                    patentes_geometricas_sin_homologar.add("patente del carro")
                    logger.info("patente_carro recuperado mediante patentes-geometrico-conservador-v1")
        except Exception as exc:
            logger.warning("Asociación geométrica omitida: %s: %s", type(exc).__name__, exc)

    # Bloque ESTADOS S2.2 -- caso real guía 383295: `enriquecer_datos_con_catalogos`
    # puede reemplazar cliente/chofer/obra_destino contra los catálogos
    # maestros por una vía completamente distinta a la recuperación
    # geométrica (`_extraer_asociaciones_geometricas`), que hasta este
    # bloque no dejaba ningún rastro de método ni de motivo -- un
    # documento podía terminar "OK" con un dato introducido por catálogo
    # sin ninguna corroboración documental. Se compara antes/después para
    # detectar exactamente qué cambió cada campo.
    cliente_antes_catalogo = datos.get("cliente")
    chofer_antes_catalogo = datos.get("chofer")
    obra_destino_antes_catalogo = datos.get("obra destino")
    if carpeta_catalogos is not None:
        # La geometría puede recuperar valores después de la extracción lineal;
        # reaplicar la misma fuente al final conserva el nombre canónico.
        datos = enriquecer_datos_con_catalogos(datos, textos, carpeta_catalogos)

        # P2: homologación conservadora de patentes contra el catálogo canónico
        # de vehículos. Se aplica después de la recuperación geométrica (P1) para
        # cubrir el valor final, sea cual sea su origen. Nunca inventa una
        # patente nueva; ver jerarquía en resolver_patente_canonica.
        try:
            vehiculos = Path(carpeta_catalogos) / "vehiculos.json"
            for campo, tipo_esperado in (
                ("patente del tracto", "TRACTO"),
                ("patente del carro", "CARRO"),
            ):
                valor_actual = str(datos.get(campo, "No encontrado"))
                decision_patente = resolver_patente_canonica(
                    vehiculos, valor_actual, tipo_esperado=tipo_esperado
                )
                if decision_patente.estado in {"ALIAS", "CORRECCION_OCR_SEGURA", "COINCIDENCIA_EXACTA"}:
                    datos[campo] = decision_patente.valor_resultado
                    metodos_documento.add(MetodoObtencionDocumento.HOMOLOGADO.value)
                    # Corroborado por diseño: catálogo confirma un único
                    # candidato determinista (coincidencia exacta, alias
                    # declarado, o corrección OCR de una sola posición sin
                    # ambigüedad) -- ya no necesita revisión solo por haber
                    # llegado ahí vía geometría.
                    patentes_geometricas_sin_homologar.discard(campo)
                    logger.info(
                        "%s homologado mediante resolucion-patente-catalogo-v1 (%s): %s -> %s",
                        campo, decision_patente.estado,
                        decision_patente.valor_original, decision_patente.valor_resultado,
                    )
                elif decision_patente.estado == "AMBIGUO":
                    _motivo(MotivoRevisionDocumento.PATENTE_AMBIGUA)
                    logger.info(
                        "%s homologacion abstenida por ambiguedad de catalogo: %s",
                        campo, decision_patente.valor_original,
                    )
        except Exception as exc:
            logger.warning("Homologación de patente omitida: %s: %s", type(exc).__name__, exc)
    if patentes_geometricas_sin_homologar:
        # Recuperada por geometría pero sin confirmación de catálogo (sin
        # carpeta_catalogos, catálogo vacío, o sin candidato) -- a
        # diferencia de una homologación exitosa, esta lectura no tiene una
        # segunda señal independiente que la corrobore.
        _motivo(MotivoRevisionDocumento.PATENTE_SIN_HOMOLOGAR)

    # Bloque INTELIGENCIA N1 -- normalización semántica + corroboración
    # ampliada de CLIENTE. Orden: (1) limpieza estructural de sufijos
    # societarios/prefijo suelto (Fase E, siempre -- nunca publicar una
    # deformación OCR evitable, corrobore o no); (2) RUT exacto contra
    # `empresas.json` (Fase F, NIVEL MUY FUERTE -- ya intentado antes por
    # `enriquecer_datos_con_catalogos`, pero eso solo dispara si el RUT
    # extraído calzó ahí; el bug real de extracción geométrica de RUT
    # cliente se corrigió aparte, ver `_extraer_rut_cliente_geometrico`);
    # (3) si el RUT no calza, fuzzy contra el nombre canónico (Fase F,
    # NIVEL FUERTE -- mismo criterio que chofer). RUT exacto que corrobora
    # también dispara Fase K (alias controlado): si el nombre documental
    # normalizado difiere del nombre canónico, se aprende como alias del
    # MISMO registro para no tener que resolver la misma corrupción OCR
    # de nuevo -- `registrar_alias_seguro` ya exige identidad única y sin
    # conflicto, así que nunca aprende algo ambiguo.
    if carpeta_catalogos is not None:
        ruta_empresas = Path(carpeta_catalogos) / "empresas.json"
        catalogo_empresas = cargar_catalogo_json(ruta_empresas)
        nombre_cliente_actual = str(datos.get("cliente", "No encontrado")).strip()
        if nombre_cliente_actual not in {"", "No encontrado"}:
            normalizado_cliente = normalizar_nombre_societario(nombre_cliente_actual)
            if normalizado_cliente.cambio:
                datos["cliente"] = normalizado_cliente.valor_normalizado
                metodos_documento.add(MetodoObtencionDocumento.NORMALIZADO.value)
                logger.info(
                    "cliente normalizado mediante normalizacion-societaria-v1: %r -> %r",
                    normalizado_cliente.valor_ocr, normalizado_cliente.valor_normalizado,
                )
                nombre_cliente_actual = datos["cliente"]

            rut_cliente_actual = str(datos.get("RUT del cliente", "No encontrado")).strip()
            cliente_id_maestro = _resolver_cliente_id_corroborado(
                carpeta_catalogos,
                cliente_texto=nombre_cliente_actual,
                rut_cliente=rut_cliente_actual,
                identidad_cliente_corroborada=False,
            )
            registro_empresa = buscar_empresa_por_rut(catalogo_empresas, rut_cliente_actual)
            if cliente_id_maestro is not None:
                # El RUT exacto resuelve una identidad maestra Ãºnica,
                # CONFIRMADA y ACTIVA. El nombre documental no se sustituye:
                # el ID se usa solamente para corroboraciÃ³n interna.
                cliente_corroborado_n1 = True
            elif registro_empresa is not None:
                cliente_corroborado_n1 = True
                # Fase K: el alias a aprender es el texto ORIGINAL antes de
                # que `enriquecer_datos_con_catalogos` ya lo haya podido
                # corregir por este mismo RUT (`cliente_antes_catalogo`) --
                # si se usara `nombre_cliente_actual` aquí, en el camino
                # normal ya sería idéntico al nombre canónico (nada que
                # aprender) aunque el documento SÍ trajera una variante
                # OCR real distinta.
                variante_ocr = str(cliente_antes_catalogo or "").strip()
                try:
                    if variante_ocr and registrar_alias_seguro(
                        ruta_empresas, normalizar_rut(rut_cliente_actual), variante_ocr
                    ):
                        logger.info(
                            "alias-controlado-v1 aprendido para cliente RUT=%s: %r",
                            rut_cliente_actual, variante_ocr,
                        )
                except OSError as exc:
                    logger.warning("No se pudo persistir alias de cliente: %s", exc)
            else:
                decision_fuzzy_cliente = resolver_nombre_empresa_difuso(
                    catalogo_empresas, nombre_cliente_actual
                )
                if decision_fuzzy_cliente.estado in {"ALIAS", "COINCIDENCIA_SEGURA"}:
                    datos["cliente"] = decision_fuzzy_cliente.valor_resultado
                    metodos_documento.add(MetodoObtencionDocumento.FUZZY.value)
                    cliente_corroborado_n1 = True
                else:
                    # OPERACIÓN REAL R2: dos campos impresos e independientes
                    # pueden corroborar la misma identidad aun cuando el OCR
                    # del cliente aislado quede justo bajo el umbral normal.
                    # Solo se acepta si (a) obra destino resuelve de forma
                    # segura con el umbral normal, (b) cliente resuelve con
                    # candidato único y margen conservando al menos 0.80, y
                    # (c) ambos convergen exactamente en la misma empresa.
                    nombre_obra_para_corroborar = str(
                        datos.get("obra destino", "No encontrado")
                    ).strip()
                    decision_fuzzy_obra = resolver_nombre_empresa_difuso(
                        catalogo_empresas, nombre_obra_para_corroborar
                    )
                    decision_cliente_cruzada = resolver_nombre_empresa_difuso(
                        catalogo_empresas, nombre_cliente_actual, umbral=0.80
                    )
                    estados_seguros = {"SIN_CAMBIO", "ALIAS", "COINCIDENCIA_SEGURA"}
                    if (
                        decision_fuzzy_obra.estado in estados_seguros
                        and decision_cliente_cruzada.estado in estados_seguros
                        and decision_fuzzy_obra.valor_resultado
                        == decision_cliente_cruzada.valor_resultado
                    ):
                        datos["cliente"] = decision_cliente_cruzada.valor_resultado
                        metodos_documento.add(MetodoObtencionDocumento.FUZZY.value)
                        cliente_corroborado_n1 = True
                logger.info(
                    "fuzzy-matching-catalogo-empresas-v1 estado=%s similitud=%s",
                    decision_fuzzy_cliente.estado,
                    (
                        f"{decision_fuzzy_cliente.similitud:.3f}"
                        if decision_fuzzy_cliente.similitud is not None else "n/a"
                    ),
                )

            if cliente_corroborado_n1:
                campos_geometricos_sin_corroborar.discard("cliente")
                decision_obra_corroborada = resolver_nombre_empresa_difuso(
                    catalogo_empresas,
                    str(datos.get("obra destino", "No encontrado")).strip(),
                )
                if (
                    decision_obra_corroborada.estado
                    in {"SIN_CAMBIO", "ALIAS", "COINCIDENCIA_SEGURA"}
                    and decision_obra_corroborada.valor_resultado
                    == datos.get("cliente")
                ):
                    # Dos campos impresos independientes convergen en la
                    # identidad de cliente ya corroborada; no queda una duda
                    # adicional propia de obra destino.
                    campos_geometricos_sin_corroborar.discard("obra destino")
            elif (
                validar_rut_chileno(rut_cliente_actual).estado == EstadoValidacion.VALIDO
                and "cliente" in campos_geometricos_sin_corroborar
            ):
                # Fase I -- RUT válido + nombre documental consistente,
                # pero identidad genuinamente no catalogada: nunca se
                # inventa (no se toca `datos["cliente"]`), pero tampoco se
                # trata igual que un OCR dudoso -- motivo informativo
                # separado, no bloqueante.
                campos_geometricos_sin_corroborar.discard("cliente")
                _motivo(MotivoRevisionDocumento.CLIENTE_NUEVA_ENTIDAD_NO_CATALOGADA)

        # Fase E/H -- limpieza estructural de OBRA DESTINO (nunca decide
        # identidad ni corrobora: el criterio de corroboración de este
        # campo se mantiene deliberadamente conservador, ver más abajo).
        # Fase H: esto es la entidad/proyecto documental (`obra destino`),
        # nunca el punto físico de entrega (`despachar_a`/DESTINO ENTREGA)
        # -- esta normalización nunca toca `despachar_a_crudo` ni la ruta.
        nombre_obra_actual = str(datos.get("obra destino", "No encontrado")).strip()
        if nombre_obra_actual not in {"", "No encontrado"}:
            normalizado_obra = normalizar_nombre_societario(nombre_obra_actual)
            if normalizado_obra.cambio:
                datos["obra destino"] = normalizado_obra.valor_normalizado
                metodos_documento.add(MetodoObtencionDocumento.NORMALIZADO.value)
                logger.info(
                    "obra_destino normalizado mediante normalizacion-societaria-v1: %r -> %r",
                    normalizado_obra.valor_ocr, normalizado_obra.valor_normalizado,
                )

    chofer_corroborado = False
    nombre_chofer = str(datos.get("chofer", "No encontrado")).strip()
    if nombre_chofer not in {"", "No encontrado"}:
        ruta_choferes = (
            Path(carpeta_catalogos) / "choferes.json"
            if carpeta_catalogos is not None
            else RUTA_CATALOGO_CHOFERES
        )
        catalogo_choferes = cargar_catalogo_json(ruta_choferes)
        rut_chofer = str(datos.get("RUT del chofer", "No encontrado")).strip()
        if buscar_chofer_por_rut(catalogo_choferes, rut_chofer) is not None:
            # Corroborado: el RUT del chofer (independiente del nombre)
            # identifica un único chofer conocido en catálogo.
            chofer_corroborado = True
        else:
            coincidencia_exacta = buscar_chofer_por_nombre_exacto(
                catalogo_choferes, nombre_chofer
            )
            if coincidencia_exacta is not None:
                rut_catalogo, registro_chofer = coincidencia_exacta
                datos["chofer"] = str(
                    registro_chofer.get("nombre", nombre_chofer)
                ).strip()
                rut_limpio = normalizar_rut(rut_catalogo)
                rut_con_guion = (
                    f"{rut_limpio[:-1]}-{rut_limpio[-1]}"
                    if len(rut_limpio) >= 2 else rut_limpio
                )
                rut_validado = validar_rut_chileno(rut_con_guion)
                if rut_validado.estado == EstadoValidacion.VALIDO:
                    datos["RUT del chofer"] = rut_validado.valor
                    metodos_documento.add(MetodoObtencionDocumento.CATALOGO.value)
                    chofer_corroborado = True
            decision_fuzzy = resolver_nombre_chofer_difuso(
                catalogo_choferes, nombre_chofer
            )
            if (
                not chofer_corroborado
                and decision_fuzzy.estado in {"ALIAS", "COINCIDENCIA_SEGURA"}
            ):
                datos["chofer"] = decision_fuzzy.valor_resultado
                metodos_documento.add(MetodoObtencionDocumento.FUZZY.value)
                # Corroborado por diseño: resolver_nombre_chofer_difuso solo
                # marca "COINCIDENCIA_SEGURA" con margen suficiente sobre el
                # resto de candidatos (ver UMBRAL/MARGEN en catalogos.py) --
                # nunca aplica un match ambiguo.
                chofer_corroborado = True
            logger.info(
                "fuzzy-matching-catalogo-choferes-v1 estado=%s similitud=%s",
                decision_fuzzy.estado,
                (
                    f"{decision_fuzzy.similitud:.3f}"
                    if decision_fuzzy.similitud is not None
                    else "n/a"
                ),
            )
    if chofer_geometrico and not chofer_corroborado:
        # Recuperado por geometría pero sin RUT de catálogo ni fuzzy seguro
        # que lo respalde -- sin esa segunda señal, un error de OCR en la
        # asociación geométrica no tendría forma de detectarse.
        _motivo(MotivoRevisionDocumento.CHOFER_SIN_CORROBORAR)

    numero_guia_actual = str(datos.get("número de guía", "No encontrado")).strip()
    if numero_guia_actual in {"", "No encontrado"}:
        try:
            if bloques_guia is None:
                bloques_guia = _leer_bloques()
            decision_guia = decidir_bloques_ocr(bloques_guia, numero_guia_actual)
            candidato_guia = str(decision_guia["valor"])
            if decision_guia["emitida"] and re.fullmatch(r"\d{5,8}", candidato_guia):
                datos["número de guía"] = candidato_guia
                # Corroborado por diseño: decidir_bloques_ocr solo "emite" un
                # candidato cuando hay una cadena única guía->marcador->valor
                # (ver experimento_numero_guia_contextual.py), y aquí además
                # se exige formato numérico de 5-8 dígitos.
                metodos_documento.add(MetodoObtencionDocumento.CONTEXTUAL.value)
                numero_guia_actual = candidato_guia
                logger.info("numero_guia recuperado mediante numero-guia-contextual-conservador-v1")
        except Exception as exc:  # El OCR secundario nunca invalida el procesamiento principal.
            logger.warning("Fallback espacial de numero_guia omitido: %s: %s", type(exc).__name__, exc)

    fecha_actual = extraer_fecha(textos, fecha_desde=fecha_desde, fecha_hasta=fecha_hasta)
    fecha_recuperada_focal = False
    if fecha_actual == "No encontrado":
        try:
            if bloques_guia is None:
                bloques_guia = _leer_bloques()
            decision_fecha = _extraer_fecha_geometrico(bloques_guia)
            if decision_fecha.get("caja"):
                evidencia_focal = _leer_focal(decision_fecha["caja"], ALLOWLIST_FECHA, _leer_fecha_focal)
                votos_por_fecha: dict[date, list[tuple[str, object]]] = {}
                for lectura in evidencia_focal["lecturas"]:
                    valor_focal = extraer_fecha(
                        [str(lectura.get("texto", ""))],
                        fecha_desde=fecha_desde,
                        fecha_hasta=fecha_hasta,
                    )
                    if valor_focal == "No encontrado":
                        continue
                    fecha_comparable = _valor_fecha_a_date(valor_focal)
                    if fecha_comparable is None:
                        continue
                    votos_por_fecha.setdefault(fecha_comparable, []).append(
                        (valor_focal, lectura.get("confianza"))
                    )
                coincidencias = {
                    fecha: votos
                    for fecha, votos in votos_por_fecha.items()
                    if len(votos) >= 2
                    and all(
                        isinstance(confianza, (int, float))
                        and confianza >= CONFIANZA_MINIMA_FECHA_FOCAL
                        for _, confianza in votos
                    )
                }
                if len(coincidencias) == 1:
                    ((_, votos_ganadores),) = coincidencias.items()
                    fecha_actual = votos_ganadores[0][0]
                    # Corroborado por diseño: exige >=2 lecturas focales
                    # concordantes con confianza >= CONFIANZA_MINIMA_FECHA_FOCAL
                    # y una única fecha ganadora sin empate -- nunca acepta
                    # una lectura focal aislada.
                    metodos_documento.add(MetodoObtencionDocumento.FOCAL.value)
                    logger.info("fecha recuperada mediante consenso-focal-v1")
        except Exception as exc:  # El OCR secundario nunca invalida el procesamiento principal.
            logger.warning("Recuperación focal de fecha omitida: %s: %s", type(exc).__name__, exc)

    descripcion = extraer_descripcion_material(textos)

    # OPERACION REAL R2: el catálogo relacional solo corrobora una obra
    # documental que ya existe y que ningún catálogo anterior sustituyó.
    # La consulta es read-only; cualquier ausencia, corrupción o ambigüedad
    # termina en abstención conservadora.
    obra_documental = str(obra_destino_antes_catalogo or "").strip()
    obra_final = str(datos.get("obra destino", "")).strip()
    obra_documental_normalizada = (
        normalizar_nombre_societario(obra_documental).valor_normalizado
        if obra_documental not in {"", "No encontrado"}
        else obra_documental
    )
    if (
        carpeta_catalogos is not None
        and obra_documental not in {"", "No encontrado"}
        and obra_final == obra_documental_normalizada
    ):
        obra_destino_corroborada = _corroborar_obra_destino_confirmada(
            carpeta_catalogos,
            cliente_texto=str(datos.get("cliente", "")),
            rut_cliente=str(datos.get("RUT del cliente", "")),
            obra_documental=obra_final,
            identidad_cliente_corroborada=cliente_corroborado_n1,
        )
        if obra_destino_corroborada is not None:
            campos_geometricos_sin_corroborar.discard("obra destino")
            metodos_documento.add(
                MetodoObtencionDocumento.CATALOGO_OBRA_DESTINO.value
            )

    # Bloque ESTADOS S2 -- corroboración de cliente/obra_destino recuperados
    # por geometría. Único criterio de corroboración disponible hoy para
    # cliente: un RUT con dígito verificador válido (ver validar_rut_chileno)
    # identifica de forma prácticamente única a un contribuyente chileno --
    # mismo criterio que ya usaba `rut_chofer_estado_validacion` en el
    # esquema histórico. `obra destino` no tiene hoy una señal de
    # corroboración independiente equivalente (no hay "RUT de destino") --
    # se mantiene deliberadamente conservador (sigue pidiendo revisión)
    # hasta que exista una, para no relajar sin evidencia (ver Fase C/D del
    # bloque ESTADOS S2).
    if "cliente" in campos_geometricos_sin_corroborar:
        rut_cliente_valido = (
            validar_rut_chileno(datos.get("RUT del cliente")).estado
            == EstadoValidacion.VALIDO
        )
        if not rut_cliente_valido:
            _motivo(MotivoRevisionDocumento.CLIENTE_SIN_CORROBORAR)
    if "obra destino" in campos_geometricos_sin_corroborar:
        _motivo(MotivoRevisionDocumento.OBRA_DESTINO_SIN_CORROBORAR)

    # Bloque ESTADOS S2.2 -- trazabilidad y corroboración de lo que cambió
    # `enriquecer_datos_con_catalogos()` (comparación contra el snapshot
    # tomado antes de llamarla, ver arriba).
    #
    # Cliente/chofer: `buscar_empresa_por_rut`/`buscar_chofer_por_rut` solo
    # cambian el valor cuando el RUT (ya extraído, por lo demás) calza
    # EXACTO con un registro del catálogo -- un RUT exacto identifica de
    # forma prácticamente única a un contribuyente/persona, igual que la
    # corroboración geométrica por RUT ya usada arriba. Se registra el
    # método, sin motivo de revisión.
    if datos.get("cliente") != cliente_antes_catalogo:
        metodos_documento.add(MetodoObtencionDocumento.CATALOGO.value)
    if datos.get("chofer") != chofer_antes_catalogo:
        metodos_documento.add(MetodoObtencionDocumento.CATALOGO.value)
    # Obra destino: `_buscar_destino_en_textos` resuelve por "COD
    # DESTINATARIO" contra el catálogo de destinos -- a diferencia de
    # cliente/chofer, esto puede completar (o reemplazar) `obra destino`
    # SIN que el campo "OBRA DESTINO" del propio documento tuviera nunca
    # un valor (caso real guía 383295: campo en blanco en la guía, pero
    # terminaba "OK" con un nombre de catálogo). "OBRA DESTINO" no es lo
    # mismo que "cliente" ni que "DESPACHAR A" (ver semántica de producto,
    # bloque E1) -- un código administrativo no es evidencia documental
    # directa de esa obra en ESTE documento. Deliberadamente conservador:
    # cualquier cambio de catálogo en este campo pide revisión, sin
    # excepción, tanto si el campo estaba vacío como si el catálogo
    # contradice un valor que el documento sí traía.
    if datos.get("obra destino") != obra_destino_antes_catalogo:
        metodos_documento.add(MetodoObtencionDocumento.CATALOGO.value)
        if obra_destino_corroborada is None:
            _motivo(MotivoRevisionDocumento.OBRA_DESTINO_SIN_CORROBORAR)

    numero_transporte_actual = datos.get("número de transporte")
    chofer_actual_final = datos.get("chofer")
    cliente_actual_final = datos.get("cliente")
    if not numero_guia_actual or numero_guia_actual == "No encontrado":
        _motivo(MotivoRevisionDocumento.GUIA_AUSENTE)
    if not numero_transporte_actual or numero_transporte_actual == "No encontrado":
        _motivo(MotivoRevisionDocumento.TRANSPORTE_AUSENTE)
    if not chofer_actual_final or chofer_actual_final == "No encontrado":
        _motivo(MotivoRevisionDocumento.CHOFER_AUSENTE)
    if not cliente_actual_final or cliente_actual_final == "No encontrado":
        _motivo(MotivoRevisionDocumento.CLIENTE_AUSENTE)
    if not descripcion:
        # Informativo (ver MOTIVOS_NO_BLOQUEANTES): un campo operacional
        # secundario ausente se registra, pero -- mismo criterio que Bloque
        # O1 para peso/horas -- nunca por sí solo fuerza revisión completa
        # del documento si el resto de identidad/operación está resuelto.
        _motivo(MotivoRevisionDocumento.MATERIAL_AUSENTE)
    if _documento_degradado(datos, descripcion):
        _motivo(MotivoRevisionDocumento.DOCUMENTO_DEGRADADO)

    requiere_revision = any(m not in MOTIVOS_NO_BLOQUEANTES for m in motivos_documento)

    # Bloque E2E R1: enriquecimiento logístico -- nunca participa de
    # `requiere_revision` (una ruta no disponible no es un motivo de
    # revisión documental, ver EstadoRuta.ORIGEN_NO_DETERMINADO/
    # REQUIERE_REVISION vs MotivoRevisionDocumento): es enriquecimiento
    # opcional a nivel de documento, igual que peso/horas en Bloque O1.
    # Nunca bloquea ni invalida el documento si falla o no aplica.
    resultado_entrega = {campo: "" for campo in CAMPOS_ENTREGA_DOCUMENTO}
    if carpeta_catalogos is not None:
        try:
            proveedor_rutas_efectivo = proveedor_rutas
            if proveedor_rutas_efectivo is None:
                from atlas_core.rutas.openrouteservice import OpenRouteService
                from atlas_core.rutas.cache_geocodificacion import (
                    ProveedorRutasConCacheGeocodificacion,
                    RepositorioCacheGeocodificacion,
                )

                # INFRAESTRUCTURA S2.1: caché portable (Drive) de
                # geocodificación -- una dirección ya geocodificada en
                # casa/oficina no vuelve a pagar otra llamada a Pelias.
                proveedor_rutas_efectivo = ProveedorRutasConCacheGeocodificacion(
                    OpenRouteService(pais=pais_operacion),
                    RepositorioCacheGeocodificacion(),
                )
            plantas_catalogo = CatalogoPlantas(Path(carpeta_catalogos) / "plantas.json").listar()
            if bloques_guia is None:
                bloques_guia = _leer_bloques()
            resultado_entrega = resolver_entrega_documento(
                textos, plantas_catalogo, proveedor_rutas_efectivo,
                bloques=bloques_guia,
            )
            logger.info(
                "enriquecimiento-logistico-documento-v1 estado_ruta=%s motivo_ruta=%s estado_entrega=%s",
                resultado_entrega.get("estado_ruta") or "(vacio)",
                resultado_entrega.get("motivo_ruta") or "(vacio)",
                resultado_entrega.get("estado_entrega") or "(vacio)",
            )
        except Exception as exc:
            logger.warning("Enriquecimiento logístico omitido: %s: %s", type(exc).__name__, exc)

    # Bloque TELEMETRÍA T2 / corregido en OPERACIÓN REAL R1 -- causa raíz
    # encontrada: el encabezado de una guía AZA siempre imprime la misma
    # planta matriz ("CASA MATRIZ PLANTA RENCA"), sin importar desde qué
    # planta despachó realmente el camión -- la guía NO contiene la
    # dirección real de origen. Por eso, cuando hay `servicio_telemetria`
    # conectado, el origen SIEMPRE se intenta corroborar por GPS (Fase
    # G): GPS inequívoco gana siempre, incluso si "coincide" con lo que
    # ya decía el documento -- nunca se asume una planta por defecto.
    # Destino, en cambio, solo se reintenta con GPS cuando hace falta
    # (ambigüedad real de geocodificación) -- política de eficiencia
    # (Fase I), no toda guía necesita desambiguación de destino.
    # Nunca bloquea ni invalida el documento; nunca sobrescribe
    # hora_entrada_aza/hora_salida_aza documentales (son horas reales
    # registradas en planta, no aproximadas -- Fase B/H).
    resultado_telemetria = {campo: "" for campo in CAMPOS_TELEMETRIA_DOCUMENTO}
    if servicio_telemetria is not None and carpeta_catalogos is not None:
        try:
            patente_actual = str(datos.get("patente del tracto", "")).strip().upper()
            if _patente_valida(patente_actual):
                fecha_documento = _parsear_fecha_dd_mm_yyyy(fecha_actual)
                hora_entrada_dt = (
                    _combinar_fecha_hora(fecha_documento, datos.get("hora de entrada"))
                    if fecha_documento is not None else None
                )
                hora_salida_dt = (
                    _combinar_fecha_hora(fecha_documento, datos.get("hora de salida"))
                    if fecha_documento is not None else None
                )
                if fecha_documento is not None and (hora_entrada_dt or hora_salida_dt):
                    resultado_gps = enriquecer_documento_con_telemetria(
                        servicio=servicio_telemetria, patente=patente_actual,
                        fecha=fecha_documento, hora_entrada=hora_entrada_dt,
                        hora_salida=hora_salida_dt, plantas=plantas_catalogo,
                    )
                    resultado_telemetria.update(resultado_gps.campos)
                    logger.info(
                        "enriquecimiento-telemetria-documento-v1 estado_telemetria=%s origen_gps=%s planta_gps=%s",
                        resultado_telemetria.get("estado_telemetria") or "(vacio)",
                        resultado_telemetria.get("origen_gps") or "(vacio)",
                        resultado_telemetria.get("planta_gps_nombre") or "(vacio)",
                    )

                    planta_gps_id = resultado_telemetria.get("planta_gps_id", "")
                    if resultado_telemetria.get("origen_gps") == ORIGEN_GPS_CONFIRMADO and planta_gps_id:
                        planta_origen_id_previo = resultado_entrega.get("planta_origen_id", "")
                        origen_cambio = planta_gps_id != planta_origen_id_previo
                        resultado_entrega["planta_origen_id"] = planta_gps_id
                        resultado_entrega["planta_origen_nombre"] = resultado_telemetria.get(
                            "planta_gps_nombre", ""
                        )
                        resultado_entrega["origen_determinado_por"] = "TELEMETRIA_GPS"
                        resultado_entrega["evidencia_origen"] = resultado_telemetria.get(
                            "evidencia_telemetria", ""
                        ) or "GEOCERCA_PLANTA"
                        if origen_cambio:
                            # Fase I -- cualquier ruta ya calculada asumía la
                            # planta documental (posiblemente equivocada, ver
                            # causa raíz arriba): se invalida y se recalcula
                            # con la planta ya corroborada por GPS, nunca se
                            # reutiliza.
                            planta_confirmada = next(
                                (p for p in plantas_catalogo if p.planta_id == planta_gps_id), None
                            )
                            despachar_a_actual = resultado_entrega.get("despachar_a_crudo", "")
                            if planta_confirmada is not None and despachar_a_actual:
                                ruta_recalculada = calcular_ruta_con_planta_conocida(
                                    planta=planta_confirmada, despachar_a_crudo=despachar_a_actual,
                                    proveedor_rutas=proveedor_rutas_efectivo,
                                    origen_determinado_por="TELEMETRIA_GPS",
                                    evidencia_origen=resultado_entrega["evidencia_origen"],
                                    punto_gps_destino=resultado_gps.punto_gps_destino,
                                )
                                resultado_entrega.update({
                                    "direccion_entrega": ruta_recalculada.direccion_entrega_geocodificada,
                                    "localidad_entrega": ruta_recalculada.localidad_entrega,
                                    "region_entrega": ruta_recalculada.region_entrega,
                                    "estado_entrega": (
                                        "RESUELTO" if ruta_recalculada.direccion_entrega_geocodificada
                                        else "REVISAR"
                                    ),
                                    "distancia_km": ruta_recalculada.distancia_km,
                                    "duracion_min": ruta_recalculada.duracion_min,
                                    "proveedor_ruta": ruta_recalculada.proveedor_ruta,
                                    "estado_ruta": ruta_recalculada.estado_ruta,
                                    "motivo_ruta": ruta_recalculada.motivo_ruta,
                                })
                            else:
                                # Sin DESPACHAR A o sin coordenadas de planta que
                                # recalcular -- igual se invalida cualquier
                                # distancia/duración que hubiera quedado del
                                # origen equivocado, nunca se deja una ruta
                                # calculada desde la planta incorrecta.
                                resultado_entrega["distancia_km"] = ""
                                resultado_entrega["duracion_min"] = ""
                                resultado_entrega["estado_ruta"] = "ORIGEN_NO_DETERMINADO" if planta_confirmada is None else resultado_entrega.get("estado_ruta", "")
                            logger.info(
                                "telemetria-corrige-origen-v1 planta_antes=%s planta_gps=%s",
                                planta_origen_id_previo or "(vacio)", planta_gps_id,
                            )
                    elif (
                        resultado_telemetria.get("estado_telemetria")
                        == EstadoSeleccionRecorrido.SELECCIONADO.value
                        and resultado_telemetria.get("origen_gps")
                        in (ORIGEN_GPS_CONFLICTO, ORIGEN_GPS_NO_DETERMINADO, ORIGEN_GPS_ESTADIA_SIN_PLANTA)
                    ):
                        # Bloque OPERACIÓN REAL R1.1 -- causa raíz: el
                        # encabezado corporativo ("CASA MATRIZ PLANTA X")
                        # NUNCA es evidencia de origen operacional (se
                        # imprime igual sin importar la planta real de
                        # despacho). Antes de este bloque, cuando la
                        # telemetría corría con datos reales y no
                        # confirmaba una planta única (conflicto o sin
                        # evidencia GPS suficientemente cercana a
                        # ninguna geocerca conocida), se conservaba en
                        # silencio el valor que `resolver_origen_documental`
                        # había sacado del encabezado -- casi siempre
                        # "AZA RENCA", por ser la planta matriz impresa.
                        # Se elimina esa conservación: sin confirmación
                        # GPS, el origen queda explícitamente sin
                        # determinar, nunca con un valor heredado del
                        # documento. Solo aplica cuando la telemetría
                        # efectivamente corrió sobre datos reales
                        # (`estado_telemetria == SELECCIONADO`) -- si no
                        # hay servicio conectado, o el proveedor no pudo
                        # ni conectar (sin credencial, vehículo no
                        # encontrado), el comportamiento documental
                        # previo no cambia (no hay señal GPS real que lo
                        # reemplace).
                        planta_origen_id_previo = resultado_entrega.get("planta_origen_id", "")
                        if planta_origen_id_previo:
                            resultado_entrega["planta_origen_id"] = ""
                            resultado_entrega["planta_origen_nombre"] = ""
                            resultado_entrega["origen_determinado_por"] = ""
                            resultado_entrega["evidencia_origen"] = resultado_telemetria.get("origen_gps", "")
                            resultado_entrega["distancia_km"] = ""
                            resultado_entrega["duracion_min"] = ""
                            resultado_entrega["proveedor_ruta"] = ""
                            resultado_entrega["estado_ruta"] = "ORIGEN_NO_DETERMINADO"
                            resultado_entrega["motivo_ruta"] = resultado_telemetria.get("origen_gps", "")
                            logger.info(
                                "telemetria-descarta-fallback-documental-v1 "
                                "planta_documental_descartada=%s origen_gps=%s",
                                planta_origen_id_previo, resultado_telemetria.get("origen_gps", ""),
                            )

                    destino_ambiguo = str(resultado_entrega.get("motivo_ruta", "")).startswith(
                        "MULTIPLES_UBICACIONES_DISPERSAS"
                    )
                    if destino_ambiguo and resultado_gps.punto_gps_destino is not None:
                        planta_para_destino = next(
                            (
                                p for p in plantas_catalogo
                                if p.planta_id == resultado_entrega.get("planta_origen_id", "")
                            ),
                            None,
                        )
                        if planta_para_destino is not None:
                            ruta_desambiguada = calcular_ruta_con_planta_conocida(
                                planta=planta_para_destino,
                                despachar_a_crudo=resultado_entrega.get("despachar_a_crudo", ""),
                                proveedor_rutas=proveedor_rutas_efectivo,
                                origen_determinado_por=resultado_entrega.get("origen_determinado_por", ""),
                                evidencia_origen=resultado_entrega.get("evidencia_origen", ""),
                                punto_gps_destino=resultado_gps.punto_gps_destino,
                            )
                            if ruta_desambiguada.estado_ruta:
                                resultado_entrega.update({
                                    "direccion_entrega": ruta_desambiguada.direccion_entrega_geocodificada,
                                    "localidad_entrega": ruta_desambiguada.localidad_entrega,
                                    "region_entrega": ruta_desambiguada.region_entrega,
                                    "estado_entrega": (
                                        "RESUELTO" if ruta_desambiguada.direccion_entrega_geocodificada
                                        else resultado_entrega.get("estado_entrega", "")
                                    ),
                                    "distancia_km": ruta_desambiguada.distancia_km,
                                    "duracion_min": ruta_desambiguada.duracion_min,
                                    "proveedor_ruta": ruta_desambiguada.proveedor_ruta,
                                    "estado_ruta": ruta_desambiguada.estado_ruta,
                                    "motivo_ruta": ruta_desambiguada.motivo_ruta,
                                })
                                logger.info(
                                    "telemetria-desambigua-destino-v1 estado_ruta=%s",
                                    ruta_desambiguada.estado_ruta,
                                )
        except Exception as exc:
            logger.warning("Enriquecimiento con telemetría omitido: %s: %s", type(exc).__name__, exc)

    return {
        "numero_guia": str(datos.get("número de guía", "No encontrado")),
        "numero_transporte": str(datos.get("número de transporte", "No encontrado")),
        "fecha": fecha_actual,
        "chofer": str(datos.get("chofer", "No encontrado")),
        "rut_chofer": str(datos.get("RUT del chofer", "No encontrado")),
        "cliente": str(datos.get("cliente", "No encontrado")),
        "obra_destino": str(datos.get("obra destino", "No encontrado")),
        "patente_tracto": str(datos.get("patente del tracto", "No encontrado")),
        "patente_rampla": str(datos.get("patente del carro", "No encontrado")),
        "descripcion_material": descripcion,
        "tipo_carga": clasificar_material(descripcion).value,
        "indicador_revision": "REVISAR" if requiere_revision else "OK",
        # Bloque ESTADOS S2: calidad del dato (por qué, si acaso, requiere
        # revisión) separada de trazabilidad del método (cómo se obtuvo el
        # valor final). Ninguna columna reemplaza a `indicador_revision`
        # (compatibilidad hacia atrás intacta) -- se agregan al final.
        "motivos_revision_documento": " | ".join(motivos_documento),
        "metodos_recuperacion_documento": " | ".join(sorted(metodos_documento)),
        # Bloque O1: peso y horarios operacionales. La ausencia de estos
        # datos NUNCA por sí sola invalida el documento (no participan en
        # `requiere_revision`) -- "No encontrado"/"No determinada" ya es
        # el motivo trazable, sin degradar documentos que antes de este
        # bloque quedaban OK.
        "peso_kg": _normalizar_peso_kg(datos.get("peso")),
        "hora_entrada_aza": str(datos.get("hora de entrada", "No encontrado")),
        "hora_salida_aza": str(datos.get("hora de salida", "No encontrado")),
        "permanencia_minutos": _calcular_permanencia_minutos(
            datos.get("hora de entrada"), datos.get("hora de salida")
        ),
        **resultado_entrega,
        **resultado_telemetria,
    }


def _archivos_ya_procesados(ruta_csv: Path) -> set[str]:
    if not ruta_csv.exists():
        return set()
    with ruta_csv.open("r", newline="", encoding="utf-8-sig") as archivo:
        return {
            fila.get("archivo", "")
            for fila in csv.DictReader(archivo, delimiter=";")
            if fila.get("archivo")
        }


def _validar_csv_existente(ruta_csv: Path) -> bool:
    """Valida el encabezado y devuelve si el CSV contiene filas de datos."""
    if not ruta_csv.exists() or ruta_csv.stat().st_size == 0:
        return False
    if not ruta_csv.is_file():
        raise ValueError(f"La salida existente no es un archivo: {ruta_csv}")

    with ruta_csv.open("r", newline="", encoding="utf-8-sig") as archivo:
        lector = csv.reader(archivo, delimiter=";")
        encabezado = next(lector, None)
        if encabezado != COLUMNAS:
            raise ValueError(
                "El CSV existente tiene un esquema incompatible. "
                "Se esperaba el encabezado exacto separado por ';'."
            )
        return next(lector, None) is not None


def _escribir_filas(ruta_csv: Path, filas: list[dict[str, str]]) -> None:
    if not filas:
        return
    ruta_csv.parent.mkdir(parents=True, exist_ok=True)
    existe_con_contenido = ruta_csv.exists() and ruta_csv.stat().st_size > 0
    with ruta_csv.open("a", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(
            archivo, fieldnames=COLUMNAS, delimiter=";", extrasaction="ignore"
        )
        if not existe_con_contenido:
            escritor.writeheader()
        escritor.writerows(filas)


def procesar_carpeta(
    carpeta: str | Path,
    salida: str | Path,
    *,
    reprocesar: bool = False,
    cada: int = 20,
    procesador: Procesador | None = None,
    lector_ocr: object = None,
    fecha_desde: date | None = None,
    fecha_hasta: date | None = None,
    proveedor: object = None,
    carpeta_catalogos: str | Path | None = None,
    proveedor_rutas: object = None,
    pais_operacion: str = PAIS_OPERACION_PREDETERMINADO,
    servicio_telemetria: object = None,
) -> dict[str, int | float]:
    """Procesa secuencialmente una carpeta, persistiendo avances periódicos.

    `servicio_telemetria` (Bloque TELEMETRÍA T2, opcional): se propaga
    igual que `proveedor_rutas` -- NUNCA se construye uno por defecto
    aquí (a diferencia de OCR/rutas). Telemetría es opt-in explícito: sin
    `servicio_telemetria`, el lote se procesa exactamente igual que antes
    de este bloque.

    Sin `procesador` ni `lector_ocr` explícitos, se construye **un solo**
    `ProveedorOCR` (vía `crear_proveedor_ocr()` — PaddleOCR si está
    disponible, si no EasyOCR) para todo el lote, y se reutiliza para cada
    archivo — el modelo no se recarga por imagen. Si se entrega
    `lector_ocr` explícito, se conserva el camino EasyOCR directo de
    siempre, sin pasar por el proveedor (compatibilidad).

    `proveedor_rutas` (Bloque E2E R1, opcional): igual patrón que
    `proveedor` pero para rutas -- se construye **un solo**
    `OpenRouteService()` para todo el lote (una sola credencial leída, una
    sola conexión reutilizada) si hay `carpeta_catalogos` y no se entrega
    uno explícito.
    """
    if cada < 1:
        raise ValueError("La frecuencia de guardado debe ser mayor que cero")
    if (
        fecha_desde is not None
        and fecha_hasta is not None
        and fecha_desde > fecha_hasta
    ):
        raise ValueError("fecha_desde no puede ser posterior a fecha_hasta")

    inicio = time.perf_counter()
    raiz = Path(carpeta).resolve()
    ruta_csv = Path(salida)
    contiene_datos = _validar_csv_existente(ruta_csv)
    if reprocesar and contiene_datos:
        raise FileExistsError(
            "No se puede usar --reprocesar con un CSV que ya contiene datos. "
            "Use una ruta de salida nueva o inexistente."
        )
    archivos = descubrir_archivos(raiz)
    procesados = set() if reprocesar else _archivos_ya_procesados(ruta_csv)
    pendientes: list[dict[str, str]] = []
    resumen: dict[str, int | float] = {
        "encontrados": len(archivos),
        "procesados": 0,
        "omitidos": 0,
        "errores": 0,
        "barras": 0,
        "rollos": 0,
        "mixtos": 0,
        "no_determinados": 0,
        "tiempo_total_segundos": 0.0,
        "promedio_segundos_archivo": 0.0,
    }
    lector_compartido = lector_ocr
    proveedor_compartido = proveedor
    proveedor_rutas_compartido = proveedor_rutas

    def ejecutar(ruta: Path) -> Mapping[str, object]:
        nonlocal lector_compartido, proveedor_compartido, proveedor_rutas_compartido
        if procesador is not None:
            return procesador(ruta)

        argumentos_archivo: dict[str, object] = {}
        if carpeta_catalogos is not None:
            argumentos_archivo["carpeta_catalogos"] = carpeta_catalogos
            if proveedor_rutas_compartido is None:
                from atlas_core.rutas.openrouteservice import OpenRouteService
                from atlas_core.rutas.cache_geocodificacion import (
                    ProveedorRutasConCacheGeocodificacion,
                    RepositorioCacheGeocodificacion,
                )

                # INFRAESTRUCTURA S2.1: mismo motivo que en
                # `procesar_archivo` -- caché portable de geocodificación
                # compartida por todo el lote.
                proveedor_rutas_compartido = ProveedorRutasConCacheGeocodificacion(
                    OpenRouteService(pais=pais_operacion),
                    RepositorioCacheGeocodificacion(),
                )
                logger.info(
                    "procesar_carpeta: proveedor de rutas creado una sola vez para todo el lote (%s)",
                    type(proveedor_rutas_compartido).__name__,
                )
            argumentos_archivo["proveedor_rutas"] = proveedor_rutas_compartido
            if servicio_telemetria is not None:
                # A diferencia del proveedor OCR/rutas, nunca se
                # construye un servicio de telemetría por defecto aquí --
                # requiere credencial/configuración explícita del
                # llamador (Fase J, opt-in).
                argumentos_archivo["servicio_telemetria"] = servicio_telemetria

        if lector_ocr is not None:
            # Compatibilidad: EasyOCR explícito, sin pasar por el proveedor.
            if fecha_desde is None and fecha_hasta is None:
                return procesar_archivo(
                    ruta, lector_ocr=lector_compartido, **argumentos_archivo
                )
            return procesar_archivo(
                ruta, lector_ocr=lector_compartido,
                fecha_desde=fecha_desde, fecha_hasta=fecha_hasta,
                **argumentos_archivo,
            )

        if proveedor_compartido is None:
            proveedor_compartido = crear_proveedor_ocr()
            logger.info(
                "procesar_carpeta: proveedor OCR creado una sola vez para todo el lote (%s)",
                type(proveedor_compartido).__name__,
            )
        if fecha_desde is None and fecha_hasta is None:
            return procesar_archivo(
                ruta, proveedor=proveedor_compartido, **argumentos_archivo
            )
        return procesar_archivo(
            ruta, proveedor=proveedor_compartido,
            fecha_desde=fecha_desde, fecha_hasta=fecha_hasta,
            **argumentos_archivo,
        )

    try:
        for indice, ruta in enumerate(archivos, start=1):
            identificador = ruta.relative_to(raiz).as_posix()
            print(f"[{indice}/{len(archivos)}] {identificador}")
            if identificador in procesados:
                resumen["omitidos"] += 1
                continue

            try:
                resultado = dict(ejecutar(ruta))
                fila = {
                    columna: str(resultado.get(columna, ""))
                    for columna in COLUMNAS
                }
                fila.update(
                    archivo=identificador,
                    estado_procesamiento="OK",
                    error="",
                )
            except Exception as error:  # cada documento es una unidad independiente
                fila = {columna: "" for columna in COLUMNAS}
                fila.update(
                    archivo=identificador,
                    estado_procesamiento="ERROR",
                    error=f"{type(error).__name__}: {error}",
                    tipo_carga="NO DETERMINADO",
                    indicador_revision="REVISAR",
                )
                resumen["errores"] += 1

            contador_tipo = {
                "BARRAS": "barras",
                "ROLLOS": "rollos",
                "MIXTO": "mixtos",
                "NO DETERMINADO": "no_determinados",
            }.get(fila["tipo_carga"], "no_determinados")
            resumen[contador_tipo] += 1

            pendientes.append(fila)
            resumen["procesados"] += 1
            if len(pendientes) >= cada:
                _escribir_filas(ruta_csv, pendientes)
                pendientes.clear()
    finally:
        _escribir_filas(ruta_csv, pendientes)
        pendientes.clear()

    tiempo_total = time.perf_counter() - inicio
    resumen["tiempo_total_segundos"] = tiempo_total
    resumen["promedio_segundos_archivo"] = (
        tiempo_total / resumen["procesados"] if resumen["procesados"] else 0.0
    )
    return resumen
