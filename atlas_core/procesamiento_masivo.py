"""Procesamiento reanudable de carpetas de guías de despacho."""

from __future__ import annotations

import csv
import logging
import re
import time
import unicodedata
from datetime import date
from pathlib import Path
from typing import Callable, Iterable, Mapping

from atlas_core.catalogos import (
    buscar_chofer_por_rut,
    cargar_catalogo_json,
    enriquecer_datos_con_catalogos,
    resolver_nombre_chofer_difuso,
    resolver_patente_canonica,
)
from atlas_core.clasificador_material import clasificar_material
from atlas_core.experimento_numero_guia_contextual import decidir_bloques_ocr
from atlas_core.extractor import (
    _chofer_lineal_contaminado,
    _consensuar_transporte_focal,
    _extraer_asociaciones_geometricas,
    _extraer_fecha_geometrico,
    _extraer_patentes_geometrico,
    _extraer_rut_cliente_geometrico,
    _extraer_transporte_geometrico,
    _extraer_chofer_geometrico,
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


logger = logging.getLogger(__name__)


EXTENSIONES_PERMITIDAS = frozenset(
    {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff"}
)
RUTA_CATALOGO_CHOFERES = Path("catalogos/choferes.json")

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


def procesar_archivo(
    ruta: Path,
    lector_ocr: object = None,
    fecha_desde: date | None = None,
    fecha_hasta: date | None = None,
    proveedor: object = None,
    carpeta_catalogos: str | Path | None = None,
) -> dict[str, str]:
    """Procesa una guía reutilizando el OCR y extractor actuales.

    `proveedor` (ProveedorOCR, opcional) permite usar cualquier motor OCR
    que cumpla el contrato de atlas_core.ocr_provider en vez de EasyOCR
    directo. Si no se entrega, el comportamiento es idéntico al anterior
    (EasyOCR vía `lector_ocr`) — no hay cambio de comportamiento por
    defecto.
    """

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
    recuperacion_geometrica = False
    recuperacion_chofer = False
    recuperacion_patentes = False
    homologacion_patente = False
    transporte_corregido = False
    bloques_guia = None
    campos_ausentes = any(
        datos.get(campo) in {None, "", "No encontrado"}
        for campo in (
            "cliente", "obra destino", "número de transporte",
            "patente del tracto", "patente del carro", "RUT del cliente",
        )
    ) or datos.get("chofer") in {None, "", "No encontrado"} or _chofer_lineal_contaminado(datos.get("chofer"))
    if campos_ausentes:
        try:
            bloques_guia = _leer_bloques()
            asociaciones = _extraer_asociaciones_geometricas(bloques_guia)
            for campo in ("cliente", "obra destino"):
                if datos.get(campo) in {None, "", "No encontrado"} and asociaciones.get(campo):
                    datos[campo] = asociaciones[campo]
                    recuperacion_geometrica = True
                    logger.info("%s recuperado mediante asociacion-geometrica-conservadora-v1", campo)
            if datos.get("RUT del cliente") in {None, "", "No encontrado"}:
                decision_rut_cliente = _extraer_rut_cliente_geometrico(bloques_guia)
                if decision_rut_cliente.get("valor"):
                    datos["RUT del cliente"] = decision_rut_cliente["valor"]
                    recuperacion_geometrica = True
                    logger.info("RUT del cliente recuperado mediante rut-cliente-geometrico-conservador-v1")
            chofer_actual = datos.get("chofer", "No encontrado")
            if chofer_actual in {None, "", "No encontrado"} or _chofer_lineal_contaminado(chofer_actual):
                decision_chofer = _extraer_chofer_geometrico(bloques_guia)
                if decision_chofer.get("valor"):
                    datos["chofer"] = decision_chofer["valor"]
                    recuperacion_chofer = True
                    logger.info("chofer recuperado mediante asociacion-geometrica-conservadora-v1")
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
                            transporte_corregido = True
                            logger.info("numero_transporte recuperado mediante consenso-focal-v1")
                    else:
                        datos["número de transporte"] = decision_transporte["valor"]
                        logger.info("numero_transporte recuperado mediante transporte-contextual-numerico-v1")
            patente_tracto_actual = str(datos.get("patente del tracto", "No encontrado"))
            patente_carro_actual = str(datos.get("patente del carro", "No encontrado"))
            if patente_tracto_actual == "No encontrado" or patente_carro_actual == "No encontrado":
                decision_patentes = _extraer_patentes_geometrico(bloques_guia)
                if patente_tracto_actual == "No encontrado" and decision_patentes.get("tracto"):
                    datos["patente del tracto"] = decision_patentes["tracto"]
                    recuperacion_patentes = True
                    logger.info("patente_tracto recuperado mediante patentes-geometrico-conservador-v1")
                if patente_carro_actual == "No encontrado" and decision_patentes.get("carro"):
                    datos["patente del carro"] = decision_patentes["carro"]
                    recuperacion_patentes = True
                    logger.info("patente_carro recuperado mediante patentes-geometrico-conservador-v1")
        except Exception as exc:
            logger.warning("Asociación geométrica omitida: %s: %s", type(exc).__name__, exc)

    if carpeta_catalogos is not None:
        # La geometría puede recuperar valores después de la extracción lineal;
        # reaplicar la misma fuente al final conserva el nombre canónico.
        datos = enriquecer_datos_con_catalogos(datos, textos, carpeta_catalogos)

        # P2: homologación conservadora de patentes contra el catálogo canónico
        # de vehículos. Se aplica después de la recuperación geométrica (P1) para
        # cubrir el valor final, sea cual sea su origen. Nunca inventa una
        # patente nueva; ver jerarquía en resolver_patente_canonica.
        try:
            vehiculos = cargar_catalogo_json(Path(carpeta_catalogos) / "vehiculos.json")
            for campo, tipo_esperado in (
                ("patente del tracto", "TRACTO"),
                ("patente del carro", "CARRO"),
            ):
                valor_actual = str(datos.get(campo, "No encontrado"))
                decision_patente = resolver_patente_canonica(
                    vehiculos, valor_actual, tipo_esperado=tipo_esperado
                )
                if decision_patente.estado in {"ALIAS", "CORRECCION_OCR_SEGURA"}:
                    datos[campo] = decision_patente.valor_resultado
                    homologacion_patente = True
                    logger.info(
                        "%s homologado mediante resolucion-patente-catalogo-v1 (%s): %s -> %s",
                        campo, decision_patente.estado,
                        decision_patente.valor_original, decision_patente.valor_resultado,
                    )
                elif decision_patente.estado == "COINCIDENCIA_EXACTA":
                    datos[campo] = decision_patente.valor_resultado
                elif decision_patente.estado == "AMBIGUO":
                    homologacion_patente = True
                    logger.info(
                        "%s homologacion abstenida por ambiguedad de catalogo: %s",
                        campo, decision_patente.valor_original,
                    )
        except Exception as exc:
            logger.warning("Homologación de patente omitida: %s: %s", type(exc).__name__, exc)

    nombre_chofer = str(datos.get("chofer", "No encontrado")).strip()
    if nombre_chofer not in {"", "No encontrado"}:
        ruta_choferes = (
            Path(carpeta_catalogos) / "choferes.json"
            if carpeta_catalogos is not None
            else RUTA_CATALOGO_CHOFERES
        )
        catalogo_choferes = cargar_catalogo_json(ruta_choferes)
        rut_chofer = str(datos.get("RUT del chofer", "No encontrado")).strip()
        if buscar_chofer_por_rut(catalogo_choferes, rut_chofer) is None:
            decision_fuzzy = resolver_nombre_chofer_difuso(
                catalogo_choferes, nombre_chofer
            )
            if decision_fuzzy.estado == "COINCIDENCIA_SEGURA":
                datos["chofer"] = decision_fuzzy.valor_resultado
            logger.info(
                "fuzzy-matching-catalogo-choferes-v1 estado=%s similitud=%s",
                decision_fuzzy.estado,
                (
                    f"{decision_fuzzy.similitud:.3f}"
                    if decision_fuzzy.similitud is not None
                    else "n/a"
                ),
            )
    numero_guia_actual = str(datos.get("número de guía", "No encontrado")).strip()
    if numero_guia_actual in {"", "No encontrado"}:
        try:
            if bloques_guia is None:
                bloques_guia = _leer_bloques()
            decision_guia = decidir_bloques_ocr(bloques_guia, numero_guia_actual)
            candidato_guia = str(decision_guia["valor"])
            if decision_guia["emitida"] and re.fullmatch(r"\d{5,8}", candidato_guia):
                datos["número de guía"] = candidato_guia
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
                    fecha_recuperada_focal = True
                    logger.info("fecha recuperada mediante consenso-focal-v1")
        except Exception as exc:  # El OCR secundario nunca invalida el procesamiento principal.
            logger.warning("Recuperación focal de fecha omitida: %s: %s", type(exc).__name__, exc)

    descripcion = extraer_descripcion_material(textos)
    valores_clave = (
        numero_guia_actual,
        datos.get("número de transporte"),
        datos.get("chofer"),
        datos.get("cliente"),
    )
    requiere_revision = (
        any(not valor or valor == "No encontrado" for valor in valores_clave)
        or not descripcion
        or recuperacion_geometrica
        or transporte_corregido
        or recuperacion_chofer
        or recuperacion_patentes
        or homologacion_patente
        or fecha_recuperada_focal
        or _documento_degradado(datos, descripcion)
    )

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
) -> dict[str, int | float]:
    """Procesa secuencialmente una carpeta, persistiendo avances periódicos.

    Sin `procesador` ni `lector_ocr` explícitos, se construye **un solo**
    `ProveedorOCR` (vía `crear_proveedor_ocr()` — PaddleOCR si está
    disponible, si no EasyOCR) para todo el lote, y se reutiliza para cada
    archivo — el modelo no se recarga por imagen. Si se entrega
    `lector_ocr` explícito, se conserva el camino EasyOCR directo de
    siempre, sin pasar por el proveedor (compatibilidad).
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

    def ejecutar(ruta: Path) -> Mapping[str, object]:
        nonlocal lector_compartido, proveedor_compartido
        if procesador is not None:
            return procesador(ruta)

        argumentos_archivo: dict[str, object] = {}
        if carpeta_catalogos is not None:
            argumentos_archivo["carpeta_catalogos"] = carpeta_catalogos

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
