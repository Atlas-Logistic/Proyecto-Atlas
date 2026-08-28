"""Procesamiento reanudable de carpetas de guías de despacho."""

from __future__ import annotations

import csv
import json
import logging
import os
import re
import time
import tempfile
import unicodedata
from concurrent.futures import ThreadPoolExecutor
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
    resolver_nombre_chofer_difuso,
    resolver_nombre_empresa_difuso,
    resolver_patente_canonica,
)
from atlas_core.normalizacion_semantica import normalizar_nombre_societario
from atlas_core.validadores import (
    EstadoValidacion,
    rut_documentalmente_confirmado_invalido,
    validar_rut_chileno,
)
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
from atlas_core.catalogo_vehiculos import cargar_catalogo_vehiculos
from atlas_core.catalogo_clientes import (
    CatalogoClientes,
    ErrorCatalogoClientes,
    EstadoBusquedaCliente,
    EstadoCalidadCliente,
    EstadoVigenciaCliente,
    normalizar_rut_cliente,
)
from atlas_core.catalogo_destinos import normalizar_nombre_destino
from atlas_core.catalogo_obras_destinos import (
    CatalogoObrasDestinos,
    ErrorCatalogoObrasDestinos,
    ResolucionObraDestino,
)
from atlas_core.decisiones_pendientes import detectar_decisiones_documento
from atlas_core.rutas.destino_entrega import (
    CAMPOS_ENTREGA_DOCUMENTO,
    calcular_ruta_con_planta_conocida,
    resolver_entrega_documento,
)
from atlas_core.rutas.destino_estructurado import extraer_identificadores_destino
from atlas_core.rutas.modelos import EstadoRuta
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
    "estado_documental",
    "estado_operacional",
    "metricas_procesamiento_json",
    "resultado_atlas_ia_json",
    "evidencia_documentos_relacionados",
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
    # Bloque RUT CLIENTE V1: el RUT del cliente/destinatario YA se
    # extraía, validaba y usaba internamente para corroboración (ver
    # `datos["RUT del cliente"]`, `_extraer_rut_cliente_geometrico`,
    # `MotivoRevisionDocumento.RUT_CLIENTE_INVALIDO`), pero nunca se
    # exponía como su propia columna estructurada -- se perdía antes de
    # persistir (caso real guía 472593/PRODALAM SA). Mismo criterio que
    # `rut_chofer`: el valor final (RUT canónico validado, o "No
    # encontrado"); estado de validación/corroboración y método de
    # recuperación ya viajan en `motivos_revision_documento`/
    # `metodos_recuperacion_documento` -- no se duplica esa
    # información en una columna aparte. Agregada al final --
    # backward-compatible, un dataset existente sin esta columna sigue
    # leyéndose igual (csv.DictReader por nombre de columna).
    "rut_cliente",
]

_COLUMNAS_R4_NUEVAS = {
    "estado_documental", "estado_operacional", "metricas_procesamiento_json",
    "resultado_atlas_ia_json", "evidencia_documentos_relacionados",
}
COLUMNAS_PRE_R4 = [columna for columna in COLUMNAS if columna not in _COLUMNAS_R4_NUEVAS]

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


# Confusiones de OCR ya confirmadas contra guías reales para la palabra
# HORMIGON: {H,B} y {M,H} (guía 464265, "BORHIGON"), {R,M} (guía 464264,
# "HOMMIGON"). Igual que `_CONFUSIONES_OCR_ETIQUETA_VEHICULAR` en
# extractor.py, es una tabla pequeña y acotada -- nunca distancia de edición
# abierta -- y sólo decide si una línea se CONSERVA como evidencia de
# material; nunca reescribe el texto OCR que termina en descripcion_material.
_CONFUSIONES_OCR_MATERIAL = tuple(map(frozenset, ({"H", "B"}, {"M", "H"}, {"R", "M"})))


def _coincide_con_tolerancia_ocr(token: str, termino: str) -> bool:
    if len(token) != len(termino):
        return False
    diferencias = [(a, b) for a, b in zip(token, termino) if a != b]
    if not diferencias or len(diferencias) > 2:
        return False
    return all(frozenset(par) in _CONFUSIONES_OCR_MATERIAL for par in diferencias)


def extraer_descripcion_material(textos: Iterable[str]) -> str:
    """Conserva líneas OCR con evidencia explícita de material."""
    terminos = re.compile(
        r"\b(HORMIGON|BARRAS?|ROLLOS?|ALAMBRON|BOBINAS?|"
        r"ANGULOS?|REDONDOS?|CUADRADOS?|PLANAS?|PERFILES?|VIGAS?|MALLAS?)\b"
    )
    encontradas: list[str] = []
    for bloque in textos:
        for linea in str(bloque).splitlines():
            limpia = re.sub(r"\s+", " ", linea).strip()
            if not limpia:
                continue
            normalizada = _normalizar(limpia)
            tiene_evidencia = terminos.search(normalizada) or any(
                _coincide_con_tolerancia_ocr(token, "HORMIGON")
                for token in re.findall(r"[A-Z]+", normalizada)
            )
            if tiene_evidencia:
                # Confusiones OCR acotadas al contexto inequívoco de una línea
                # de acero: B/3/D al inicio y 8/B antes de MM.
                limpia = re.sub(r"^[D3]\s+(?=HORMIGON\b)", "B ", limpia, flags=re.IGNORECASE)
                limpia = re.sub(r"(?<=HORMIGON\s)B(?=MM\b)", "8", limpia, flags=re.IGNORECASE)
                encontradas.append(limpia)
    return " | ".join(dict.fromkeys(encontradas))


def extraer_peso_kg_etiquetado(textos: Iterable[str]) -> str:
    """Recupera PESO KG desde su etiqueta estructural, no desde números libres."""
    lineas = [re.sub(r"\s+", " ", str(t)).strip() for t in textos]
    for indice, linea in enumerate(lineas):
        if not re.search(r"\b(?:PESO|ESO)\s*KG\b", _normalizar(linea)):
            continue
        ventana = " ".join(lineas[indice: indice + 4])
        cola = re.split(r"(?:PESO|ESO)\s*KG\.?", _normalizar(ventana), maxsplit=1)[-1]
        for candidato in re.findall(r"\d{1,3}(?:[.,]\d{3})+(?:[.,]\d{2,3})?|\d{3,5}", cola):
            normalizado = _normalizar_peso_kg(candidato)
            if normalizado != "No encontrado":
                return normalizado
    return "No encontrado"


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
        fecha_sel = _valor_fecha_a_date(str(seleccionado["valor"]))
        if fecha_sel is not None:
            conteos: dict[date, int] = {}
            for candidato in candidatos:
                if candidato is seleccionado or int(candidato["prioridad"]) not in (1, 2):
                    continue
                fecha_otra = _valor_fecha_a_date(str(candidato["valor"]))
                if fecha_otra is not None and (fecha_otra.day, fecha_otra.month) == (fecha_sel.day, fecha_sel.month):
                    conteos[fecha_otra] = conteos.get(fecha_otra, 0) + 1
            consensos = [fecha for fecha, cantidad in conteos.items() if cantidad >= 2 and fecha != fecha_sel]
            if len(consensos) == 1:
                return consensos[0].strftime("%d-%m-%Y")
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
    # Bloque R5 I -- variante NO bloqueante de TRANSPORTE_AUSENTE: la
    # etiqueta "NRO...TRANSPORTE" nunca aparece en el texto OCR (no un
    # número ilegible, la etiqueta misma) y el documento no está degradado
    # en general -- omisión documental atribuible al mandante, se registra
    # como Incidencia Documental (ver `incidencias_documentales`), nunca
    # como pendiente de Revisión de Atlas. Ver criterio exacto de
    # abstención junto al punto donde se dispara, más abajo.
    TRANSPORTE_AUSENTE_SIN_ETIQUETA = "TRANSPORTE_AUSENTE_SIN_ETIQUETA"
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
    # El candidato geométrico (anclado inequívocamente a FECHA DE EMISIÓN,
    # ver `_extraer_fecha_geometrico`) difiere del valor lineal ya
    # aceptado, y la relectura focal con consenso no logró confirmar cuál
    # de los dos es correcto -- ninguno se descarta a ciegas.
    FECHA_SIN_CORROBORAR = "FECHA_SIN_CORROBORAR"
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
    # Bloque FIX RUT DOCUMENTAL -- caso real: guía de WLADIMIR AGUILAR con
    # "55.555.555-5" impreso (dígito verificador correcto, cuerpo
    # implausible -- ver `validar_rut_chileno`/`_cuerpo_implausible`).
    # Distinto de CHOFER_SIN_CORROBORAR/CLIENTE_SIN_CORROBORAR: ahí la
    # identidad misma es incierta (podría ser un error de OCR en el
    # nombre); acá la identidad de la entidad SÍ está establecida
    # (nombre coincide exacto en catálogo o histórico), el problema es
    # específicamente que el RUT documental no pasa validación
    # estructural. Nunca se usa el valor documental como dato
    # operacional; se conserva sólo como evidencia del error real de la
    # guía.
    RUT_CHOFER_INVALIDO = "RUT_CHOFER_INVALIDO"
    RUT_CLIENTE_INVALIDO = "RUT_CLIENTE_INVALIDO"
    # Bloque RUT CLIENTE V1 -- distinto de RUT_CLIENTE_INVALIDO: acá el RUT
    # documental SÍ es estructuralmente válido (dígito verificador
    # correcto) y SÍ existe en `empresas.json`, pero identifica una
    # empresa DISTINTA de la que dice el nombre impreso en la guía (Sección
    # 5 del bloque: "nombre coincide pero RUT válido contradice al
    # catálogo -> conflicto real"). A diferencia de RUT_CHOFER_INVALIDO/
    # RUT_CLIENTE_INVALIDO (identidad ya establecida por nombre, sólo el
    # RUT está mal -> Incidencia Documental automática), acá no hay forma
    # segura de saber cuál de los dos datos documentales es el correcto --
    # requiere revisión humana, nunca se resuelve solo. BLOQUEANTE (no
    # está en MOTIVOS_NO_BLOQUEANTES).
    RUT_CLIENTE_CONTRADICE_CATALOGO = "RUT_CLIENTE_CONTRADICE_CATALOGO"


MOTIVOS_NO_BLOQUEANTES = frozenset({
    MotivoRevisionDocumento.MATERIAL_AUSENTE.value,
    MotivoRevisionDocumento.CLIENTE_NUEVA_ENTIDAD_NO_CATALOGADA.value,
    # Bloque R5 I: no bloquea Revisión de Atlas -- se resuelve como
    # Incidencia Documental, un flujo separado (ver
    # `revalidacion_documental.detectar_incidencias_transporte_ausente_sin_ocr`).
    MotivoRevisionDocumento.TRANSPORTE_AUSENTE_SIN_ETIQUETA.value,
    # Bloque FIX RUT DOCUMENTAL: mismo criterio -- sólo se dispara cuando
    # la identidad (chofer/cliente) YA está establecida por nombre; nunca
    # bloquea Revisión de Atlas (esa cola es para incertidumbre de
    # identidad, no para un error documental ya identificado y
    # evidenciado). Se resuelve como Incidencia Documental.
    MotivoRevisionDocumento.RUT_CHOFER_INVALIDO.value,
    MotivoRevisionDocumento.RUT_CLIENTE_INVALIDO.value,
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
    direccion_documental: str = "",
) -> object | None:
    """Consulta read-only una obra confirmada; ante cualquier duda, se abstiene.

    Bloque DESTINOS INTERNOS V1 -- causa raíz real (caso 472593: la obra
    "EMPRESA CONST SIGRO", para PRODALAM SA, YA tiene DOS relaciones
    CONFIRMADAS por Javier -- guías históricas 464550 y 472227 -- ambas
    hacia el mismo lugar real (Avda Irarrázaval 5497, Ñuñoa), sólo que
    quedaron como dos `Destino` de texto ligeramente distinto -- mismo
    patrón ya documentado y resuelto para AUSIN SAN BERNARDO, ver
    `decisiones_pendientes.py`). `resolver_obra_destino_confirmada`
    exige EXACTAMENTE una relación confirmada -- ante DOS (evidencia
    REDUNDANTE, nunca una contradicción real) devuelve `None` como si no
    hubiera ninguna, y 472593 escalaba a B1/Internet por algo que Javier
    ya había confirmado dos veces. Mismo fix ya aplicado en
    `decisiones_pendientes.py` (Bloque REGENERACIÓN B1): si la búsqueda
    estricta no resuelve, se prueba `listar_destinos_confirmados_para_
    obra` (sin exigir unicidad) y se acepta si la dirección documental
    coincide LITERALMENTE (normalizada, nunca fuzzy) con CUALQUIERA de
    los destinos confirmados -- nunca "el primero" ni "el más nuevo"."""
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
        catalogo_obras = CatalogoObrasDestinos(
            ruta=carpeta / "obras_destinos.json",
            ruta_clientes=carpeta / "clientes.json",
            ruta_destinos=carpeta / "destinos_maestros.json",
        )
        resolucion = catalogo_obras.resolver_obra_destino_confirmada(
            cliente_id=cliente_id,
            nombre_obra=obra,
        )
        if resolucion is not None:
            return resolucion
        direccion = str(direccion_documental or "").strip()
        if direccion in {"", "No encontrado"}:
            return None
        texto_documental = normalizar_nombre_destino(direccion)
        destinos_confirmados_obra = catalogo_obras.listar_destinos_confirmados_para_obra(nombre_obra=obra)
        for destino in destinos_confirmados_obra:
            calle = normalizar_nombre_destino(destino.direccion.split(",", 1)[0])
            if calle and calle in texto_documental:
                return destino
        return None
    except (OSError, ValueError, ErrorCatalogoObrasDestinos):
        return None


def _corroborar_destino_historico_repetido(
    carpeta_catalogos: str | Path, *, cliente_id: str, textos: Iterable[str],
) -> dict[str, object] | None:
    """Corrobora por identidad exacta + dirección repetida; una observación aislada no basta."""
    ruta = Path(carpeta_catalogos) / "destinos_maestros.json"
    try:
        contenido = json.loads(ruta.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, TypeError):
        return None
    texto = _normalizar(" ".join(str(t) for t in textos))
    candidatos = []
    for destino in contenido.get("destinos", []):
        if destino.get("cliente_id") != cliente_id or destino.get("estado_vigencia") != "ACTIVO":
            continue
        nombre = _normalizar(destino.get("nombre_destino", ""))
        observacion = _normalizar(destino.get("observacion", ""))
        repeticion = re.search(r"\b(\d+)\s+VIAJES?\b", observacion)
        if nombre and nombre in texto and repeticion and int(repeticion.group(1)) >= 2:
            candidatos.append(destino)
    if len(candidatos) != 1:
        return None
    return {
        "destino_id": candidatos[0].get("destino_id", ""),
        "fuente": "DESTINO_HISTORICO_REPETIDO",
        "viajes_historicos": int(re.search(r"\b(\d+)\s+VIAJES?\b", _normalizar(candidatos[0]["observacion"])).group(1)),
    }


def procesar_archivo(
    ruta: Path,
    lector_ocr: object = None,
    fecha_desde: date | None = None,
    fecha_hasta: date | None = None,
    proveedor: object = None,
    carpeta_catalogos: str | Path | None = None,
    proveedor_rutas: object = None,
    pais_operacion: str = PAIS_OPERACION_PREDETERMINADO,
    recolector_decisiones: Callable[[list[dict[str, object]]], None] | None = None,
    servicio_telemetria: object = None,
    planta_origen_informada: str | None = None,
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
    multiempresa en el bloque E2E R1.

    `planta_origen_informada` (Bloque ORIGEN OPERACIONAL V2, opcional):
    código de planta que Mobile informó al capturar la foto (ver
    `atlas_core.mobile.PLANTAS_ORIGEN_MOBILE`) -- se fusiona con el
    encabezado documental y la regla de compatibilidad planta<->categoría
    configurada (ver `atlas_core.rutas.origen_evidencia`) en vez de dejar
    que el encabezado societario lo sustituya sin más. Sin este valor
    (Desktop/procesamiento por lote, sin Mobile), comportamiento IDÉNTICO
    a antes de este bloque."""

    inicio_documento = time.perf_counter()

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

    inicio_ocr = time.perf_counter()
    textos = _leer_texto()
    fin_ocr = time.perf_counter()
    datos = (
        extraer_datos(textos, carpeta_catalogos)
        if carpeta_catalogos is not None
        else extraer_datos(textos)
    )
    fin_extraccion = time.perf_counter()
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
            catalogo_vehiculos = cargar_catalogo_vehiculos(vehiculos)
            por_patente = {v.patente_canonica: v for v in catalogo_vehiculos.homologables()}
            rampla_documental_valida = _patente_valida(
                str(datos.get("patente del carro", "No encontrado"))
            )
            for campo, tipo_esperado in (
                ("patente del tracto", "TRACTO"),
                ("patente del carro", "CARRO"),
            ):
                valor_actual = str(datos.get(campo, "No encontrado"))
                # Una patente aislada puede ser TRACTO o CAMION_RIGIDO. La
                # identidad exacta conocida prevalece sobre la expectativa
                # provisional del campo, pero CARRO nunca es compatible.
                decision_sin_tipo = resolver_patente_canonica(vehiculos, valor_actual)
                vehiculo_exacto = por_patente.get(decision_sin_tipo.valor_resultado)
                tipo_efectivo = tipo_esperado
                if (
                    campo == "patente del tracto"
                    and not rampla_documental_valida
                    and decision_sin_tipo.estado in {"COINCIDENCIA_EXACTA", "ALIAS"}
                    and vehiculo_exacto is not None
                    and vehiculo_exacto.tipo in {"TRACTO", "CAMION_RIGIDO"}
                ):
                    tipo_efectivo = vehiculo_exacto.tipo
                decision_patente = resolver_patente_canonica(
                    vehiculos, valor_actual, tipo_esperado=tipo_efectivo
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
    # R3.1: una variante nueva respaldada por RUT exacto ya no se aprende
    # silenciosamente. La resolución sigue siendo read-only y la variante se
    # emite después como ALIAS_CANDIDATO para una decisión humana futura.
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
                # Bloque RUT CLIENTE V1 (Sección 5) -- el RUT documental es
                # válido y existe en el catálogo, pero eso NO corrobora la
                # identidad por sí solo si el nombre ORIGINALMENTE impreso
                # (`cliente_antes_catalogo` -- ANTES de que
                # `enriquecer_datos_con_catalogos`, arriba, ya haya
                # sustituido `datos["cliente"]` por el nombre del catálogo;
                # comparar contra el valor YA sustituido sería comparar un
                # texto contra sí mismo) es confiablemente OTRA empresa (RUT
                # correcto de un tercero impreso por error, por ejemplo).
                # Sólo se compara cuando la resolución difusa del nombre
                # documental original es lo bastante segura como para
                # nombrar una empresa CONCRETA Y DISTINTA (mismos estados
                # "seguros" que ya usa el resto de esta función) -- un
                # simple typo/variante OCR del mismo nombre (p. ej. "EDMA
                # SA" por "EBEMA SA") resuelve al MISMO registro y sigue
                # corroborando en silencio, exactamente como antes de este
                # bloque (ver `test_cliente_corroborado_via_rut_propone_
                # alias_sin_escribir_catalogo`); ante una lectura ambigua/no
                # catalogada, se sigue confiando en el RUT (no hay una
                # segunda lectura confiable con la que contradecirlo).
                nombre_catalogo_por_rut = str(registro_empresa.get("nombre", "")).strip()
                nombre_documental_original = str(cliente_antes_catalogo or "").strip()
                decision_nombre_vs_rut = resolver_nombre_empresa_difuso(
                    catalogo_empresas, nombre_documental_original
                )
                if (
                    nombre_catalogo_por_rut
                    and decision_nombre_vs_rut.estado in {"SIN_CAMBIO", "ALIAS", "COINCIDENCIA_SEGURA"}
                    and decision_nombre_vs_rut.valor_resultado != nombre_catalogo_por_rut
                ):
                    _motivo(MotivoRevisionDocumento.RUT_CLIENTE_CONTRADICE_CATALOGO)
                    logger.info(
                        "RUT del cliente valido resuelve a una empresa distinta del nombre documental: "
                        "rut=%s nombre_documental=%r nombre_catalogo=%r",
                        rut_cliente_actual, nombre_documental_original, nombre_catalogo_por_rut,
                    )
                else:
                    cliente_corroborado_n1 = True
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

    # Bloque FIX RUT DOCUMENTAL -- caso real WLADIMIR AGUILAR: el RUT
    # documental de la guía no pasó validación estructural (dígito
    # verificador correcto pero cuerpo implausible, o dígito verificador
    # incorrecto -- ver buscar_rut_chofer()/validar_rut_chileno). La
    # identidad del chofer YA está establecida por nombre (nombre_chofer
    # coincide exacto en catálogo, o al menos fue leído) -- esto nunca
    # reemplaza CHOFER_SIN_CORROBORAR (identidad incierta), es un motivo
    # distinto para un problema distinto: el RUT impreso en ESTE
    # documento es el que está mal, con o sin RUT canónico disponible
    # para sustituirlo. `_corroborar_documentos_relacionados` (batch)
    # puede corroborar un RUT canónico cruzando otros documentos del
    # mismo chofer si el catálogo todavía no tiene uno confirmado.
    #
    # Sólo se dispara cuando `rut_documentalmente_confirmado_invalido`
    # confirma que NO es explicable por una simple duda de OCR (dígito
    # verificador calza pero cuerpo implausible) -- un dígito verificador
    # que no calza queda para Revisión de Atlas/B1, nunca una Incidencia
    # Documental automática (Sección 2 del bloque).
    rut_chofer_invalido_documental = datos.get("RUT del chofer (documento, invalido)")
    if (
        rut_chofer_invalido_documental
        and nombre_chofer not in {"", "No encontrado"}
        and rut_documentalmente_confirmado_invalido(rut_chofer_invalido_documental)
    ):
        _motivo(MotivoRevisionDocumento.RUT_CHOFER_INVALIDO)

    rut_cliente_invalido_documental = datos.get("RUT del cliente (documento, invalido)")
    nombre_cliente_actual = str(datos.get("cliente", "No encontrado")).strip()
    if (
        rut_cliente_invalido_documental
        and nombre_cliente_actual not in {"", "No encontrado"}
        and rut_documentalmente_confirmado_invalido(rut_cliente_invalido_documental)
    ):
        _motivo(MotivoRevisionDocumento.RUT_CLIENTE_INVALIDO)

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

    # Corroboración geométrica de una fecha lineal YA presente (caso real
    # 464367): el orden de lectura del OCR puede asociar el candidato
    # correcto de FECHA DE EMISIÓN con una etiqueta vecina (FECHA SALIDA/
    # LLEGADA) cuando esa etiqueta y su propio valor quedan invertidos en
    # el texto linealizado de un layout de dos columnas -- `extraer_fecha`
    # (lineal) pierde ese candidato frente a un rival cuya etiqueta sí
    # quedó adyacente. `_extraer_fecha_geometrico` ubica por posición real
    # en la imagen (inmune al orden de lectura) y está diseñado
    # específicamente para anclarse sólo a FECHA DE EMISIÓN, abstenerse
    # ante cualquier candidato rival (FECHA SALIDA/LLEGADA) y ante
    # ambigüedad -- ver `test_fecha_geometrica_prioriza_emision_sobre_
    # salida_cercana` y `test_fecha_geometrica_no_toma_candidato_mas_
    # cercano_a_salida_que_a_emision`. Auditoría real read-only sobre 43
    # guías del histórico disponible (2026-08-18): 38 coinciden, 4 sin
    # candidato geométrico (sin cambio), 1 discrepancia real (464367) --
    # el candidato geométrico fue el correcto, verificado contra la
    # imagen. Nunca se confía en el texto geométrico bruto por sí solo:
    # se exige la MISMA relectura focal con doble confirmación ya usada
    # arriba para el caso "No encontrado" antes de aceptar el cambio.
    #
    # Alcance deliberadamente acotado: sólo se corrobora si `bloques_guia`
    # YA está cargado (por necesitarse para otro campo ausente/contaminado
    # más arriba en esta misma función) -- nunca se fuerza una carga nueva
    # sólo para esto. Preserva el invariante ya existente y ya probado de
    # que un documento cuyo texto lineal resuelve todos los campos nunca
    # toca bloques/geometría (ver `test_procesar_archivo_preserva_chofer_
    # lineal_limpio`, `test_procesar_archivo_fecha_global_valida_no_
    # dispara_focal`). En evidencia real, el único caso encontrado
    # (464367) ya cumple esta condición (tenía cliente/patentes ausentes),
    # así que no se pierde cobertura del caso demostrado.
    if fecha_actual != "No encontrado" and bloques_guia is not None:
        try:
            decision_fecha_corrob = _extraer_fecha_geometrico(bloques_guia)
            fecha_geo_comparable = (
                _valor_fecha_a_date(str(decision_fecha_corrob["valor"]))
                if decision_fecha_corrob.get("caja")
                else None
            )
            fecha_lineal_comparable = _valor_fecha_a_date(fecha_actual)
            if (
                fecha_geo_comparable is not None
                and fecha_lineal_comparable is not None
                and fecha_geo_comparable != fecha_lineal_comparable
            ):
                evidencia_focal_corrob = _leer_focal(
                    decision_fecha_corrob["caja"], ALLOWLIST_FECHA, _leer_fecha_focal
                )
                votos_por_fecha_corrob: dict[date, list[tuple[str, object]]] = {}
                for lectura in evidencia_focal_corrob["lecturas"]:
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
                    votos_por_fecha_corrob.setdefault(fecha_comparable, []).append(
                        (valor_focal, lectura.get("confianza"))
                    )
                coincidencias_corrob = {
                    fecha: votos
                    for fecha, votos in votos_por_fecha_corrob.items()
                    if len(votos) >= 2
                    and all(
                        isinstance(confianza, (int, float))
                        and confianza >= CONFIANZA_MINIMA_FECHA_FOCAL
                        for _, confianza in votos
                    )
                }
                if len(coincidencias_corrob) == 1:
                    ((fecha_confirmada, votos_ganadores_corrob),) = coincidencias_corrob.items()
                    if fecha_confirmada == fecha_geo_comparable:
                        # Confirmado con la misma exigencia de consenso que
                        # la recuperación: el candidato geométrico
                        # (semánticamente anclado a FECHA DE EMISIÓN)
                        # reemplaza al lineal, que en este layout quedó
                        # asociado al candidato equivocado.
                        fecha_actual = votos_ganadores_corrob[0][0]
                        metodos_documento.add(MetodoObtencionDocumento.FOCAL.value)
                        logger.info("fecha corregida mediante corroboracion-geometrica-focal-v1")
                    elif fecha_confirmada == fecha_lineal_comparable:
                        pass  # confirma el valor lineal ya aceptado -- la discrepancia inicial no era real
                    else:
                        # Consenso en una tercera fecha distinta a ambos
                        # candidatos -- ninguno de los tres se elige a ciegas.
                        _motivo(MotivoRevisionDocumento.FECHA_SIN_CORROBORAR)
                else:
                    # Sin consenso único -- la discrepancia queda sin
                    # resolver, se conserva el valor lineal tal cual.
                    _motivo(MotivoRevisionDocumento.FECHA_SIN_CORROBORAR)
        except Exception as exc:  # El OCR secundario nunca invalida el procesamiento principal.
            logger.warning("Corroboración geométrica de fecha omitida: %s: %s", type(exc).__name__, exc)

    descripcion = extraer_descripcion_material(textos)
    # Bloque ORIGEN OPERACIONAL V2 -- calculado aquí (no en la construcción
    # final de `datos`, más abajo) para poder cruzarlo con la fusión de
    # evidencia de origen (Mobile/documento) más adelante en esta misma
    # función -- función pura, sin efecto en el resultado ya existente.
    tipo_carga_preliminar = clasificar_material(descripcion).value

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
        # Bloque DESTINOS INTERNOS V1 -- lectura de sólo texto, barata
        # (mismo `textos` ya en memoria, sin OCR ni red nueva), para que
        # el fallback de "destinos confirmados redundantes" (ver
        # docstring de `_corroborar_obra_destino_confirmada`) pueda
        # comparar contra la dirección de entrega REAL del documento --
        # la resolución de ruta/geocodificación todavía no corrió a esta
        # altura de la función.
        direccion_documental_temprana = (extraer_identificadores_destino(textos).despachar_a or "").strip()
        obra_destino_corroborada = _corroborar_obra_destino_confirmada(
            carpeta_catalogos,
            cliente_texto=str(datos.get("cliente", "")),
            rut_cliente=str(datos.get("RUT del cliente", "")),
            obra_documental=obra_final,
            identidad_cliente_corroborada=cliente_corroborado_n1,
            direccion_documental=direccion_documental_temprana,
        )
        if obra_destino_corroborada is None:
            cliente_id_historico = _resolver_cliente_id_corroborado(
                carpeta_catalogos,
                cliente_texto=str(datos.get("cliente", "")),
                rut_cliente=str(datos.get("RUT del cliente", "")),
                identidad_cliente_corroborada=cliente_corroborado_n1,
            )
            if cliente_id_historico is not None:
                obra_destino_corroborada = _corroborar_destino_historico_repetido(
                    carpeta_catalogos, cliente_id=cliente_id_historico, textos=textos,
                )
        if obra_destino_corroborada is not None:
            campos_geometricos_sin_corroborar.discard("obra destino")
            metodos_documento.add(
                MetodoObtencionDocumento.CATALOGO_OBRA_DESTINO.value
            )
        else:
            # FIX falso-OK (lote controlado 20260818, guías 464395/464479):
            # una obra_destino leída limpiamente (sin fallback geométrico,
            # sin que el catálogo la reescribiera) nunca pasaba por ESTE
            # bloque salvo para *retirar* la sospecha -- si el cliente SÍ
            # resuelve a una identidad maestra concreta (hay contra qué
            # preguntar) pero ninguna obra/destino confirmada la respalda
            # todavía, la extracción correcta no equivale a corroboración
            # (ver comentario ESTADOS S2 más abajo) y el documento no puede
            # quedar OK silencioso. Mismo criterio de "cliente resoluble"
            # que ya usa `detectar_decisiones_documento` para decidir si
            # corresponde preguntar por la obra -- si el cliente no resuelve
            # (ver `_resolver_cliente_id_corroborado`), no hay base para
            # juzgar la obra y se conserva la abstención previa.
            cliente_id_para_obra = _resolver_cliente_id_corroborado(
                carpeta_catalogos,
                cliente_texto=str(datos.get("cliente", "")),
                rut_cliente=str(datos.get("RUT del cliente", "")),
                identidad_cliente_corroborada=cliente_corroborado_n1,
            )
            if cliente_id_para_obra is not None:
                campos_geometricos_sin_corroborar.add("obra destino")

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
    documento_degradado = _documento_degradado(datos, descripcion)
    if not numero_guia_actual or numero_guia_actual == "No encontrado":
        _motivo(MotivoRevisionDocumento.GUIA_AUSENTE)
    if not numero_transporte_actual or numero_transporte_actual == "No encontrado":
        # Bloque R5 I -- causa raíz: "sin número de transporte" mezclaba
        # tres situaciones muy distintas bajo un único motivo (una pestaña
        # manual, aparte de todo lo demás, que sólo mostraba el síntoma).
        # Un documento degradado en general (`documento_degradado`, ya
        # calculado arriba) ya lo cubre `DOCUMENTO_DEGRADADO` -- un problema
        # de calidad/captura del documento completo, no específico de este
        # campo. Descartado eso: si la propia etiqueta "NRO...TRANSPORTE"
        # nunca aparece en el texto OCR, el campo simplemente no está
        # impreso en el documento -- omisión atribuible al mandante, nunca
        # un problema de lectura de Atlas (ver
        # `atlas_core.incidencias_documentales` para la distinción y
        # `revalidacion_documental.detectar_incidencias_transporte_ausente_sin_ocr`
        # para el registro correspondiente). Si la etiqueta SÍ aparece pero
        # ningún número válido la acompaña, es Atlas quien no logró leerlo
        # -- eso sigue siendo `TRANSPORTE_AUSENTE` normal, bloqueante en
        # Revisión de Atlas, igual que siempre.
        if not documento_degradado and datos.get("_etiqueta_transporte_documental") == "NO":
            _motivo(MotivoRevisionDocumento.TRANSPORTE_AUSENTE_SIN_ETIQUETA)
        else:
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
    if documento_degradado:
        _motivo(MotivoRevisionDocumento.DOCUMENTO_DEGRADADO)

    requiere_revision = any(m not in MOTIVOS_NO_BLOQUEANTES for m in motivos_documento)

    # Bloque E2E R1: enriquecimiento logístico -- nunca participa de
    # `requiere_revision` (una ruta no disponible no es un motivo de
    # revisión documental, ver EstadoRuta.ORIGEN_NO_DETERMINADO/
    # REQUIERE_REVISION vs MotivoRevisionDocumento): es enriquecimiento
    # opcional a nivel de documento, igual que peso/horas en Bloque O1.
    # Nunca bloquea ni invalida el documento si falla o no aplica.
    fin_resolucion = time.perf_counter()
    inicio_rutas = fin_resolucion
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
                codigo_planta_mobile=planta_origen_informada,
                categoria_documento=tipo_carga_preliminar,
            )
            logger.info(
                "enriquecimiento-logistico-documento-v1 estado_ruta=%s motivo_ruta=%s estado_entrega=%s",
                resultado_entrega.get("estado_ruta") or "(vacio)",
                resultado_entrega.get("motivo_ruta") or "(vacio)",
                resultado_entrega.get("estado_entrega") or "(vacio)",
            )
        except Exception as exc:
            logger.warning("Enriquecimiento logístico omitido: %s: %s", type(exc).__name__, exc)
    fin_rutas = time.perf_counter()

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
    inicio_telemetria = time.perf_counter()
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
    fin_telemetria = time.perf_counter()

    if recolector_decisiones is not None and carpeta_catalogos is not None:
        try:
            recolector_decisiones(detectar_decisiones_documento(
                archivo=Path(ruta).name,
                datos=datos,
                carpeta_catalogos=carpeta_catalogos,
                cliente_documental_original=str(cliente_antes_catalogo or ""),
                # R3.4: dirección documental ya resuelta por
                # `resolver_entrega_documento` más arriba (nunca una nueva
                # extracción) -- permite que DESTINO_SIN_CONFIRMAR muestre
                # "Destino leído" sin que Desktop infiera nada.
                despachar_a_documental=str(resultado_entrega.get("despachar_a_crudo", "")),
            ))
        except Exception as exc:
            logger.warning(
                "Detección de decisiones pendientes omitida: %s: %s",
                type(exc).__name__, exc,
            )

    estado_documental = "REQUIERE_REVISION" if requiere_revision else "OK"
    estado_operacional = (
        "REQUIERE_REVISION"
        if requiere_revision or str(resultado_entrega.get("estado_ruta", "")) in {
            "REQUIERE_REVISION", "ORIGEN_NO_DETERMINADO", "DESTINO_NO_VALIDO"
        }
        else "OK"
    )
    fin_documento = time.perf_counter()
    metricas = {
        "carga_preprocesamiento_seg": 0.0,
        "ocr_seg": round(fin_ocr - inicio_ocr, 4),
        "extraccion_parsing_seg": round(fin_extraccion - fin_ocr, 4),
        "resolucion_corroboracion_seg": round(fin_resolucion - fin_extraccion, 4),
        "atlas_ia_seg": 0.0,
        "geocodificacion_routing_seg": round(fin_rutas - inicio_rutas, 4),
        "telemetria_seg": round(fin_telemetria - inicio_telemetria, 4),
        "total_documento_seg": round(fin_documento - inicio_documento, 4),
    }

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
        "tipo_carga": tipo_carga_preliminar,
        "indicador_revision": "REVISAR" if requiere_revision else "OK",
        # Bloque ESTADOS S2: calidad del dato (por qué, si acaso, requiere
        # revisión) separada de trazabilidad del método (cómo se obtuvo el
        # valor final). Ninguna columna reemplaza a `indicador_revision`
        # (compatibilidad hacia atrás intacta) -- se agregan al final.
        "motivos_revision_documento": " | ".join(motivos_documento),
        "metodos_recuperacion_documento": " | ".join(sorted(metodos_documento)),
        "estado_documental": estado_documental,
        "estado_operacional": estado_operacional,
        "metricas_procesamiento_json": json.dumps(metricas, ensure_ascii=False, sort_keys=True),
        "resultado_atlas_ia_json": "",
        "evidencia_documentos_relacionados": "",
        # Bloque O1: peso y horarios operacionales. La ausencia de estos
        # datos NUNCA por sí sola invalida el documento (no participan en
        # `requiere_revision`) -- "No encontrado"/"No determinada" ya es
        # el motivo trazable, sin degradar documentos que antes de este
        # bloque quedaban OK.
        "peso_kg": (
            _normalizar_peso_kg(datos.get("peso"))
            if _normalizar_peso_kg(datos.get("peso")) != "No encontrado"
            else extraer_peso_kg_etiquetado(textos)
        ),
        "hora_entrada_aza": str(datos.get("hora de entrada", "No encontrado")),
        "hora_salida_aza": str(datos.get("hora de salida", "No encontrado")),
        "permanencia_minutos": _calcular_permanencia_minutos(
            datos.get("hora de entrada"), datos.get("hora de salida")
        ),
        **resultado_entrega,
        **resultado_telemetria,
        # Bloque RUT CLIENTE V1 -- mismo criterio que `rut_chofer`: valor
        # final ya validado (dígito verificador correcto) o "No
        # encontrado". El estado de validación/corroboración vive en
        # `motivos_revision_documento` (RUT_CLIENTE_INVALIDO,
        # CLIENTE_SIN_CORROBORAR, CLIENTE_NUEVA_ENTIDAD_NO_CATALOGADA) y
        # el método de recuperación en `metodos_recuperacion_documento`
        # -- no se duplica esa información acá.
        "rut_cliente": str(datos.get("RUT del cliente", "No encontrado")),
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
        lector = csv.DictReader(archivo, delimiter=";")
        filas = list(lector)
        encabezado = list(lector.fieldnames or [])
    if encabezado != COLUMNAS:
        if encabezado != COLUMNAS_PRE_R4:
            raise ValueError(
                "El CSV existente tiene un esquema incompatible. "
                "Se esperaba el encabezado exacto separado por ';'."
            )
        temporal = ruta_csv.with_suffix(ruta_csv.suffix + ".r4.tmp")
        with temporal.open("w", newline="", encoding="utf-8-sig") as archivo:
            escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";", extrasaction="ignore")
            escritor.writeheader()
            escritor.writerows(filas)
        temporal.replace(ruta_csv)
    return bool(filas)


def _corroborar_documentos_relacionados(ruta_csv: Path, archivos_objetivo: set[str]) -> int:
    """Propaga sólo RUT de chofer con cuatro señales fuertes coincidentes."""
    if not archivos_objetivo or not ruta_csv.is_file():
        return 0
    with ruta_csv.open("r", newline="", encoding="utf-8-sig") as archivo:
        filas = list(csv.DictReader(archivo, delimiter=";"))
    cambios = 0
    for fila in filas:
        if fila.get("archivo") not in archivos_objetivo:
            continue
        motivos = [m.strip() for m in fila.get("motivos_revision_documento", "").split("|") if m.strip()]
        if "CHOFER_SIN_CORROBORAR" not in motivos:
            continue
        candidatas = []
        for otra in filas:
            if otra is fila or otra.get("rut_chofer") in {"", "No encontrado"}:
                continue
            # Bloque FIX RUT DOCUMENTAL -- causa raíz real (WLADIMIR
            # AGUILAR, 472230/472239.jpeg): dos documentos hermanos con
            # el MISMO RUT documental inválido ("55.555.555-5")
            # coincidían entre sí y esa mera coincidencia se aceptaba
            # como corroboración -- sin validar nunca que el valor
            # propagado fuera en sí un RUT estructuralmente válido. Se
            # exige ahora que el RUT de la fila FUENTE sea válido antes
            # de contar su coincidencia como corroboración; dos lecturas
            # igualmente inválidas nunca se confirman entre sí.
            if validar_rut_chileno(otra.get("rut_chofer", "")).estado != EstadoValidacion.VALIDO:
                continue
            senales = {
                "fecha": otra.get("fecha") == fila.get("fecha"),
                "chofer": _normalizar(otra.get("chofer")) == _normalizar(fila.get("chofer")),
                "patente": otra.get("patente_tracto") == fila.get("patente_tracto"),
                "obra": _normalizar(otra.get("obra_destino")) == _normalizar(fila.get("obra_destino")),
                "transporte": otra.get("numero_transporte") == fila.get("numero_transporte"),
            }
            if senales["chofer"] and senales["patente"] and sum(senales.values()) >= 4:
                candidatas.append((otra, senales))
        ruts = {normalizar_rut(c[0].get("rut_chofer", "")) for c in candidatas}
        ruts.discard("")
        if len(ruts) != 1:
            continue
        fuente, senales = candidatas[0]
        fila["rut_chofer"] = fuente["rut_chofer"]
        fila["motivos_revision_documento"] = " | ".join(m for m in motivos if m != "CHOFER_SIN_CORROBORAR")
        fila["indicador_revision"] = "REVISAR" if any(
            m not in MOTIVOS_NO_BLOQUEANTES for m in fila["motivos_revision_documento"].split(" | ") if m
        ) else "OK"
        fila["estado_documental"] = "REQUIERE_REVISION" if fila["indicador_revision"] == "REVISAR" else "OK"
        ruta_requiere_revision = fila.get("estado_ruta") in {
            "REQUIERE_REVISION", "ORIGEN_NO_DETERMINADO", "DESTINO_NO_VALIDO"
        }
        fila["estado_operacional"] = (
            "REQUIERE_REVISION"
            if fila["estado_documental"] == "REQUIERE_REVISION" or ruta_requiere_revision
            else "OK"
        )
        metodos = {m.strip() for m in fila.get("metodos_recuperacion_documento", "").split("|") if m.strip()}
        metodos.add("DOCUMENTO_RELACIONADO")
        fila["metodos_recuperacion_documento"] = " | ".join(sorted(metodos))
        fila["evidencia_documentos_relacionados"] = json.dumps({
            "campo": "rut_chofer", "archivo_fuente": fuente["archivo"],
            "senales": [nombre for nombre, coincide in senales.items() if coincide],
        }, ensure_ascii=False, sort_keys=True)
        cambios += 1
    if cambios:
        temporal = ruta_csv.with_suffix(ruta_csv.suffix + ".relacionados.tmp")
        with temporal.open("w", newline="", encoding="utf-8-sig") as archivo:
            escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";", extrasaction="ignore")
            escritor.writeheader(); escritor.writerows(filas)
        temporal.replace(ruta_csv)
    return cambios


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


def _crear_orquestador_ia_configurado():
    """Activa B1 con la credencial segura que también ve Desktop en Windows."""
    if os.getenv("ATLAS_IA_B1_OPERACIONAL", "1") == "0":
        return None
    from atlas_core.atlas_ia.orquestador import OrquestadorAtlasIA
    from atlas_core.atlas_ia.proveedor_groq import ProveedorModeloIAGroq, resolver_groq_api_key
    if not resolver_groq_api_key():
        return None
    return OrquestadorAtlasIA(proveedor=ProveedorModeloIAGroq(), herramientas=_herramientas_b1_disponibles())


def _herramientas_b1_disponibles() -> dict[str, object]:
    """Bloque B1 INVESTIGADOR -- herramientas reales que B1 puede
    solicitar en operación (nunca sólo durante desarrollo). Ausencia de
    credencial de búsqueda (`OPENROUTER_API_KEY`) no bloquea el resto de
    B1: la herramienta simplemente no queda registrada -- B1 sigue
    pudiendo razonar sobre evidencia ya reunida por el Motor, sólo no
    puede investigar más allá de eso (mismo criterio ya usado para
    GROQ_API_KEY ausente: B1 se desactiva, nunca lanza)."""
    import os as _os

    herramientas: dict[str, object] = {}
    if _os.getenv("OPENROUTER_API_KEY", "").strip():
        from atlas_core.atlas_ia.buscador_web import (
            BuscadorWebConCache, BuscadorWebOpenRouter, RepositorioCacheBusquedaWeb,
        )
        from atlas_core.atlas_ia.herramientas import herramienta_verificacion_externa

        buscador = BuscadorWebConCache(BuscadorWebOpenRouter(), RepositorioCacheBusquedaWeb())
        herramientas["VERIFICACION_EXTERNA"] = herramienta_verificacion_externa(buscador)
    return herramientas


def _fila_requiere_atencion_operacional(fila: Mapping[str, str]) -> bool:
    """Bloque R7 -- puerta de entrada barata (sin red, sin B1) para decidir
    si vale la pena siquiera preguntarle al registro universal de
    problemas: algún motivo documental presente, o una ruta/origen que
    todavía no llegó a un estado resuelto. Reemplaza la puerta anterior
    (`indicador_revision == "REVISAR"`), que sólo veía motivos
    documentales y dejaba invisibles los de ruta/origen (causa raíz de
    "B1 nunca interviene en destino/planta", Bloque R7)."""
    if str(fila.get("motivos_revision_documento", "")).strip():
        return True
    if str(fila.get("estado_ruta", "")).strip() not in ("", EstadoRuta.RUTA_CALCULADA.value):
        return True
    return False


def _ejecutar_ia_operacional(
    ruta_csv: Path, archivos_objetivo: set[str], orquestador: object,
    carpeta_catalogos: str | Path | None = None,
) -> dict[str, int | float]:
    """Bloque R7 -- escala a B1 CUALQUIER problema elegible (Motor primero
    siempre; ver `atlas_core.atlas_ia.registro_problemas`), no sólo los 4
    motivos documentales de antes. Aplica sólo autonomía A permitida por
    tipo de problema (`TipoProblemaIA.aplicable_automaticamente`); el
    resto (hoy: planta origen, destino) sólo aporta evidencia adicional a
    la decisión humana que ya existe (Bloque R5/R6) -- nunca se auto-
    aplica una planta o una dirección."""
    from atlas_core.atlas_ia.contratos import ContextoRazonamiento
    from atlas_core.atlas_ia.registro_problemas import (
        clasificar_motivo_no_registrado,
        codigos_residuales_no_registrados,
        detectar_problemas_elegibles,
    )

    resumen: dict[str, int | float] = {"llamadas": 0, "A": 0, "B": 0, "C": 0, "D": 0, "latencia_segundos": 0.0}
    if not ruta_csv.is_file():
        return resumen
    with ruta_csv.open("r", newline="", encoding="utf-8-sig") as archivo:
        filas = list(csv.DictReader(archivo, delimiter=";"))
    cambio = False
    for fila in filas:
        if fila.get("archivo") not in archivos_objetivo:
            continue
        if not _fila_requiere_atencion_operacional(fila):
            # Bloque B1 OBSERVADOR -- el Motor resolvió esta guía sin
            # ningún problema elegible: 0 llamadas LLM (nunca se invoca
            # al orquestador), pero se deja un registro OBSERVACIONAL
            # compacto en la MISMA columna/contrato ya existente
            # (`resultado_atlas_ia_json`, nunca una memoria paralela)
            # para que B1 pueda, más adelante, consultar "¿qué pasó con
            # una guía similar?" sin tener que releer el CSV completo ni
            # volver a razonar nada. Idempotente por diseño: sólo se
            # escribe la PRIMERA vez (columna todavía vacía) -- una
            # revalidación posterior de la MISMA guía ya resuelta nunca
            # vuelve a tocarla ni gasta ciclos de más.
            if not str(fila.get("resultado_atlas_ia_json", "")).strip():
                fila["resultado_atlas_ia_json"] = json.dumps([{
                    "problema": "OBSERVACION_OPERACIONAL", "dominio": "CICLO_GUIA",
                    "campo": "resultado_final", "elegible_ia": False, "llamada_realizada": False,
                    "resultado_motor": "RESUELTO",
                    "resumen": {
                        "estado_ruta": str(fila.get("estado_ruta", "")),
                        "origen_determinado_por": str(fila.get("origen_determinado_por", "")),
                        "planta_origen_nombre": str(fila.get("planta_origen_nombre", "")),
                        "obra_destino": str(fila.get("obra_destino", "")),
                        "cliente": str(fila.get("cliente", "")),
                    },
                }], ensure_ascii=False, sort_keys=True)
                cambio = True
            continue
        resultados = []
        motivos = {m.strip() for m in fila.get("motivos_revision_documento", "").split("|") if m.strip()}
        # Bloque PERFORMANCE V1 -- causa real (caso 472339: 4 llamadas B1
        # de un mismo documento, ~38.7 s sumados porque se disparaban una
        # tras otra) -- cada problema elegible de ESTE documento es
        # independiente de los demás (campo distinto, evidencia propia,
        # ninguno depende del resultado de otro) así que la espera de red
        # de cada `orquestador.resolver(...)` nunca necesitaba ser
        # secuencial. Se arma primero la lista completa de tareas (sin
        # llamar a nadie todavía -- esto NUNCA cambia: sigue siendo
        # puramente determinista y sin red), después se disparan EN
        # PARALELO sólo las que sí requieren una llamada real (I/O de
        # red, no CPU -- un hilo por llamada es seguro y barato), y por
        # último se aplican los resultados en el MISMO ORDEN de siempre,
        # de a uno, en el hilo principal -- la mutación de `fila`/
        # `motivos` (y por lo tanto qué motivo puede quedar resuelto
        # automáticamente y con qué explicación) es idéntica a la versión
        # secuencial, byte a byte; sólo cambia CUÁNDO se esperó la red,
        # nunca el resultado ni el orden en que se decide.
        tareas: list[tuple[object, str, object, dict | None]] = []
        for tipo, codigo in detectar_problemas_elegibles(fila):
            if orquestador is None:
                # B1 desactivado/sin credencial: el problema SIGUE siendo
                # elegible (hay evidencia potencial que analizar), pero no
                # hay con qué llamar -- explícito, nunca un silencio de
                # "0 llamadas" sin razón.
                tareas.append((tipo, codigo, None, {
                    "problema": codigo, "dominio": tipo.dominio, "campo": tipo.campo,
                    "elegible_ia": True, "llamada_realizada": False,
                    "razon_no_elegible": "SIN_PROVEEDOR_IA_CONFIGURADO",
                }))
                continue
            evidencias = tipo.recopilar_evidencia(fila, filas, carpeta_catalogos=carpeta_catalogos)
            # Bloque B1 INVESTIGADOR -- causa raíz real de que B1 nunca
            # investigara nada (0 llamadas reales, siempre
            # SIN_EVIDENCIA_PARA_RAZONAR): esta puerta terminaba el
            # problema ANTES de siquiera invocar a B1 cuando el Motor no
            # había pre-reunido evidencia -- sin importar si el propio
            # dominio tenía una herramienta capaz de INVESTIGAR y
            # producir evidencia nueva (p. ej. "VERIFICACION_EXTERNA").
            # Ahora sólo se descarta sin llamar cuando NO hay evidencia
            # previa NI ninguna herramienta disponible que pudiera
            # aportarla -- B1 recibe el problema con evidencia vacía y
            # puede solicitar la herramienta él mismo (ver
            # `atlas_ia.orquestador`, ya soporta esta ronda).
            if not evidencias and not tipo.herramientas:
                tareas.append((tipo, codigo, None, {
                    "problema": codigo, "dominio": tipo.dominio, "campo": tipo.campo,
                    "elegible_ia": True, "llamada_realizada": False,
                    "razon_no_elegible": "SIN_EVIDENCIA_PARA_RAZONAR",
                }))
                continue
            contexto = ContextoRazonamiento(
                campo=tipo.campo, valor_documental=fila.get(tipo.campo, ""),
                rut_chofer=fila.get("rut_chofer", ""), numero_guia=fila.get("numero_guia", ""),
                numero_transporte=fila.get("numero_transporte", ""), evidencias=evidencias,
                resultado_motor="REQUIERE_REVISION", explicacion_motor=codigo,
                identidad_documento=fila.get("archivo", ""),
                # Bloque B1 INVESTIGADOR -- contexto operacional mínimo y
                # genérico (nunca un volcado completo de la fila) para
                # que una herramienta de investigación pueda vincular el
                # problema con obra/cliente -- "Regla crítica para
                # destinos": nunca investigar una dirección como string
                # aislado si Atlas ya conoce su obra/cliente.
                #
                # Bloque OBRA/DESTINO V2 -- causa raíz real (caso 472593):
                # faltaba aquí la dirección de entrega documental
                # (`despachar_a_crudo`/`direccion_entrega`) -- sin ella,
                # una herramienta que investiga OBRA_DESTINO (un NOMBRE,
                # nunca una dirección) no tenía con qué relacionar ese
                # nombre a un punto de entrega real, y terminaba
                # comparando domicilios corporativos genéricos entre sí
                # (empresa vs. cliente) en vez de la relación real
                # empresa/obra <-> dirección de entrega. Se agrega el
                # mismo campo ya oficial del destino operacional (ver
                # `atlas_core.rutas.destino_entrega`, DESPACHAR A es la
                # fuente autoritativa del punto de entrega -- nunca la
                # sede corporativa del cliente/receptor).
                identidad_operacional={
                    "obra_destino": str(fila.get("obra_destino", "")),
                    "cliente": str(fila.get("cliente", "")),
                    "direccion_entrega": str(fila.get("despachar_a_crudo") or fila.get("direccion_entrega") or ""),
                },
                herramientas_disponibles=tipo.herramientas,
                restricciones_dominio=("NO_INVENTAR_DATOS", "NO_ESCRIBIR_CATALOGOS", "MAXIMO_RONDAS_B1"),
            )
            tareas.append((tipo, codigo, contexto, None))

        indices_con_llamada = [i for i, (_, _, ctx, _) in enumerate(tareas) if ctx is not None]
        resultados_llamada: dict[int, tuple[object, float]] = {}
        if len(indices_con_llamada) == 1:
            # Una sola llamada -- ningún beneficio de un hilo aparte, y
            # evita el costo fijo de crear un executor para el caso más
            # común (un solo problema elegible).
            i = indices_con_llamada[0]
            inicio = time.perf_counter()
            resultado = orquestador.resolver(tareas[i][2])
            resultados_llamada[i] = (resultado, time.perf_counter() - inicio)
        elif indices_con_llamada:
            def _resolver_con_tiempo(indice: int) -> tuple[int, object, float]:
                inicio_hilo = time.perf_counter()
                resultado_hilo = orquestador.resolver(tareas[indice][2])
                return indice, resultado_hilo, time.perf_counter() - inicio_hilo

            with ThreadPoolExecutor(max_workers=len(indices_con_llamada)) as pool:
                for indice, resultado, latencia in pool.map(_resolver_con_tiempo, indices_con_llamada):
                    resultados_llamada[indice] = (resultado, latencia)

        for indice, (tipo, codigo, contexto, traza_previa) in enumerate(tareas):
            if contexto is None:
                resultados.append(traza_previa)
                continue
            resultado, latencia = resultados_llamada[indice]
            resumen["llamadas"] += 1
            resumen["latencia_segundos"] += latencia
            clase = str(resultado.clasificacion)[:1]
            resumen[clase] = int(resumen.get(clase, 0)) + 1
            traza = resultado.a_dict()
            traza.update({
                "problema": codigo, "dominio": tipo.dominio, "campo": tipo.campo,
                "elegible_ia": True, "llamada_realizada": True,
                "latencia_segundos": round(latencia, 6),
            })
            aplicable_a = (
                tipo.aplicable_automaticamente and tipo.aplicar is not None
                and clase == "A" and resultado.hipotesis is not None
                and resultado.hipotesis.resultado == "PROPUESTA"
            )
            if aplicable_a:
                tipo.aplicar(fila, resultado.hipotesis.valor_propuesto)
                motivos.discard(codigo)
                fila["motivos_revision_documento"] = " | ".join(sorted(m for m in motivos if m))
                fila["indicador_revision"] = "REVISAR" if any(
                    m not in MOTIVOS_NO_BLOQUEANTES for m in motivos if m
                ) else "OK"
                fila["estado_documental"] = "REQUIERE_REVISION" if fila["indicador_revision"] == "REVISAR" else "OK"
            traza["aplicado_operacionalmente"] = aplicable_a
            traza["evito_intervencion_humana"] = aplicable_a and fila["indicador_revision"] == "OK"
            resultados.append(traza)
        # Bloque R12 -- red de seguridad UNIVERSAL (generaliza el bloque R7
        # que sólo cubría `motivo_ruta`): NUNCA un silencio de "0 llamadas"
        # sin explicación, para NINGUNA de las tres fuentes (documental,
        # ruta, origen GPS) -- incluye cualquier motivo/código que
        # `REGISTRO_PROBLEMAS_IA` todavía no reconozca hoy, o que se
        # agregue mañana sin haber sido registrado todavía. Antes de este
        # bloque, un motivo documental (p. ej. CLIENTE_AUSENTE/CHOFER_
        # AUSENTE antes de tener entrada propia) o de origen GPS sin
        # registro pasaba en absoluto silencio -- ni evaluado ni
        # explicado, el bypass real que este bloque cierra.
        for fuente, codigo in codigos_residuales_no_registrados(fila):
            dominio = {"MOTIVO_RUTA": "RUTA", "MOTIVO_ORIGEN_GPS": "PLANTA_ORIGEN"}.get(fuente, "DOCUMENTAL")
            campo = {"MOTIVO_RUTA": "motivo_ruta", "MOTIVO_ORIGEN_GPS": "motivo_origen_gps"}.get(fuente, "motivos_revision_documento")
            resultados.append({
                "problema": codigo, "dominio": dominio, "campo": campo,
                "elegible_ia": False, "llamada_realizada": False,
                "razon_no_elegible": clasificar_motivo_no_registrado(fuente=fuente, codigo=codigo),
            })
        if resultados:
            fila["resultado_atlas_ia_json"] = json.dumps(resultados, ensure_ascii=False, sort_keys=True)
            metricas = json.loads(fila.get("metricas_procesamiento_json") or "{}")
            metricas["atlas_ia_segundos"] = round(
                sum(r.get("latencia_segundos", 0) for r in resultados), 6
            )
            fila["metricas_procesamiento_json"] = json.dumps(metricas, sort_keys=True)
            cambio = True
    if cambio:
        temporal = ruta_csv.with_suffix(ruta_csv.suffix + ".ia.tmp")
        with temporal.open("w", newline="", encoding="utf-8-sig") as archivo:
            escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";", extrasaction="ignore")
            escritor.writeheader(); escritor.writerows(filas)
        temporal.replace(ruta_csv)
    return resumen


def escalar_resultado_ia_en_memoria(
    datos: Mapping[str, object], historial: Iterable[Mapping[str, object]],
    *, orquestador_ia: object = None, carpeta_catalogos: str | Path | None = None,
) -> tuple[dict[str, str], dict[str, int | float]]:
    """Entrada común para Mobile: reutiliza exactamente el escalamiento B1
    del lote (Bloque R7: el mismo registro universal, nunca un segundo
    camino de escalamiento para Mobile)."""
    fila = {columna: str(datos.get(columna, "")) for columna in COLUMNAS}
    fila["archivo"] = fila.get("archivo") or "__mobile_actual__"
    filas = [{columna: str(f.get(columna, "")) for columna in COLUMNAS} for f in historial]
    filas.append(fila)
    with tempfile.TemporaryDirectory(prefix="atlas_b1_") as temporal:
        ruta = Path(temporal) / "contexto.csv"
        with ruta.open("w", newline="", encoding="utf-8-sig") as archivo:
            escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";", extrasaction="ignore")
            escritor.writeheader(); escritor.writerows(filas)
        orquestador = orquestador_ia if orquestador_ia is not None else _crear_orquestador_ia_configurado()
        resumen = _ejecutar_ia_operacional(ruta, {fila["archivo"]}, orquestador, carpeta_catalogos)
        with ruta.open(newline="", encoding="utf-8-sig") as archivo:
            salida = list(csv.DictReader(archivo, delimiter=";"))[-1]
    return salida, resumen


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
    orquestador_ia: object = None,
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
    archivos_procesados_ahora: set[str] = set()
    pendientes: list[dict[str, str]] = []
    decisiones_pendientes: list[dict[str, object]] = []
    resumen: dict[str, object] = {
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
        "decisiones_pendientes": decisiones_pendientes,
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
            argumentos_archivo["recolector_decisiones"] = decisiones_pendientes.extend
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
            archivos_procesados_ahora.add(identificador)
            resumen["procesados"] += 1
            if len(pendientes) >= cada:
                _escribir_filas(ruta_csv, pendientes)
                pendientes.clear()
    finally:
        _escribir_filas(ruta_csv, pendientes)
        pendientes.clear()

    corroborados = 0
    for _ in range(len(archivos_procesados_ahora)):
        nuevos = _corroborar_documentos_relacionados(ruta_csv, archivos_procesados_ahora)
        corroborados += nuevos
        if not nuevos:
            break
    resumen["documentos_relacionados_corroborados"] = corroborados
    if orquestador_ia is None:
        orquestador_ia = _crear_orquestador_ia_configurado()
    resumen["atlas_ia"] = _ejecutar_ia_operacional(ruta_csv, archivos_procesados_ahora, orquestador_ia, carpeta_catalogos)

    tiempo_total = time.perf_counter() - inicio
    resumen["tiempo_total_segundos"] = tiempo_total
    resumen["promedio_segundos_archivo"] = (
        tiempo_total / resumen["procesados"] if resumen["procesados"] else 0.0
    )
    return resumen
