"""Procesamiento reanudable de carpetas de guías de despacho."""

from __future__ import annotations

import csv
import logging
import re
import time
import unicodedata
from datetime import date
from pathlib import Path
from typing import Callable, Collection, Iterable, Mapping

from atlas_core.catalogos import (
    cargar_catalogo_json,
    enriquecer_datos_con_catalogos,
)
from atlas_core.clasificador_material import clasificar_material
from atlas_core.experimento_numero_guia_contextual import decidir_bloques_ocr
from atlas_core.extractor import (
    _chofer_lineal_contaminado,
    _consensuar_transporte_focal,
    _extraer_asociaciones_geometricas,
    _extraer_transporte_geometrico,
    _extraer_chofer_geometrico,
    _extraer_cantidad_geometrica,
    _extraer_patentes_geometricas,
    extraer_datos,
)
from atlas_core.inteligencia.contrato_multicampo import (
    EstadoResolucion,
    ResultadoResolucion,
)
from atlas_core.inteligencia.orquestador_multicampo import (
    ResultadoOrquestacionSombra,
    SolicitudResolucionSombra,
    orquestar_multicampo_sombra,
)
from atlas_core.inteligencia.resolucion_chofer import resolver_chofer_rut
from atlas_core.inteligencia.resolucion_cliente import resolver_cliente_rut
from atlas_core.inteligencia.resolucion_destino import resolver_destino_ubicacion
from atlas_core.inteligencia.resolucion_material import resolver_material_tipo_carga
from atlas_core.ocr import (
    _leer_rut_cliente_focal,
    _leer_transporte_focal,
    _rut_chileno_canonico,
    crear_lector_ocr,
    leer_bloques_imagen,
    leer_encabezado_origen_focal,
    leer_texto_imagen,
)
from atlas_core.politica_activacion_multicampo import (
    EstadoOperacional,
    REGISTRO_ACTIVACION_MULTICAMPO_FASE1,
    decidir_publicacion,
)


logger = logging.getLogger(__name__)


EXTENSIONES_PERMITIDAS = frozenset(
    {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff"}
)
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
]
COLUMNAS_PUBLICACION = [*COLUMNAS, "peso", "cantidad", "origen"]
COLUMNAS_TRAZA_HISTORICA = [
    "numero_guia_fuente",
    "numero_guia_motivo",
    "rut_chofer_estado_validacion",
    "cliente_fuente",
    "obra_destino_fuente",
    "chofer_fuente",
]

Procesador = Callable[[Path], Mapping[str, object]]


def _distancia_token(a: str, b: str) -> int:
    if abs(len(a) - len(b)) > 1:
        return 99
    anterior = list(range(len(b) + 1))
    for indice_a, caracter_a in enumerate(a, 1):
        actual = [indice_a]
        for indice_b, caracter_b in enumerate(b, 1):
            actual.append(min(
                actual[-1] + 1,
                anterior[indice_b] + 1,
                anterior[indice_b - 1] + (caracter_a != caracter_b),
            ))
        anterior = actual
    return anterior[-1]


def _resolver_origen_documental(
    lecturas: Iterable[str], catalogo_plantas: Mapping[str, object]
) -> str | None:
    """Confirma una planta única por consenso OCR y catálogo aprobado."""
    plantas = catalogo_plantas.get("plantas", [])
    if not isinstance(plantas, list):
        return None
    votos: dict[str, int] = {}
    for lectura in lecturas:
        tokens = re.findall(r"[A-Z0-9]+", _normalizar(lectura))
        coincidencias = []
        for planta in plantas:
            if not isinstance(planta, Mapping):
                continue
            if str(planta.get("estado_vigencia", "")).upper() not in {"ACTIVA", "ACTIVO"}:
                continue
            if str(planta.get("estado_calidad", "")).upper() not in {"CONFIRMADA", "CONFIRMADO", "CONFIRMADO_DOCUMENTAL"}:
                continue
            nombre = str(planta.get("nombre", "")).strip()
            nombre_tokens = re.findall(r"[A-Z0-9]+", _normalizar(nombre))
            if nombre_tokens and all(
                any(_distancia_token(observado, esperado) <= 1 for observado in tokens)
                for esperado in nombre_tokens
            ):
                coincidencias.append(nombre)
        if len(coincidencias) == 1:
            votos[coincidencias[0]] = votos.get(coincidencias[0], 0) + 1
    aprobadas = [nombre for nombre, cantidad in votos.items() if cantidad >= 2]
    return aprobadas[0] if len(aprobadas) == 1 else None


def _rut_cliente_requiere_relectura(
    valor: object,
    cliente: object = "",
    *,
    etiqueta_rut_observada: bool = False,
) -> bool:
    texto = str(valor or "").strip()
    if texto in {"", "No encontrado"}:
        return (
            etiqueta_rut_observada
            and str(cliente or "").strip() not in {"", "No encontrado"}
        )
    formato_completo = re.fullmatch(
        r"\s*(?:\d{1,8}|\d{1,3}(?:\.\d{3})+)\s*-\s*[\dKk]\s*",
        texto,
    )
    return formato_completo is None or _rut_chileno_canonico(texto) is None


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
        if fecha_desde is not None and fecha_candidata < fecha_desde:
            continue
        if fecha_hasta is not None and fecha_candidata > fecha_hasta:
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
        if _fecha_dmy_valida(valor, fecha_desde, fecha_hasta):
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


def _integrar_resolucion_multicampo(
    *,
    campo: str,
    valor_ocr: str,
    valor_actual: object,
    resultado: ResultadoResolucion,
    etiqueta_log: str,
    propagar_revision_contrato: bool,
    registro_activacion: Mapping[str, EstadoOperacional | str],
    campos_controlados_autorizados: Collection[str],
) -> tuple[str, bool]:
    if resultado.estado is EstadoResolucion.CONFIRMADO:
        valor_resuelto = resultado.valor_canonico or valor_ocr
    else:
        valor_resuelto = valor_ocr or str(valor_actual or "").strip()
    valor_previo = valor_ocr or str(valor_actual or "").strip()
    publicacion = decidir_publicacion(
        campo,
        valor_previo,
        valor_resuelto,
        registro=registro_activacion,
        autorizacion_controlada=campo in campos_controlados_autorizados,
    )
    logger.info(
        "%s estado=%s via=%s estado_operacional=%s publicar=%s",
        etiqueta_log,
        resultado.estado.value,
        resultado.via_decision,
        publicacion.estado_operacional.value,
        publicacion.publicar,
    )
    requiere_revision = (
        propagar_revision_contrato
        and resultado.estado is not EstadoResolucion.CONFIRMADO
    )
    return publicacion.valor, requiere_revision


def _orquestar_destino_sombra(
    **argumentos_destino: object,
) -> ResultadoOrquestacionSombra:
    """Compone Destinos con el núcleo congelado, sin publicar su decisión."""
    return orquestar_multicampo_sombra((
        SolicitudResolucionSombra(
            "destino",
            resolver_destino_ubicacion,
            opciones=argumentos_destino,
        ),
    ))


def _orquestar_material_sombra(
    **argumentos_material: object,
) -> ResultadoOrquestacionSombra:
    """Compone Materiales con el núcleo congelado, sin publicar su decisión."""
    return orquestar_multicampo_sombra((
        SolicitudResolucionSombra(
            "material",
            resolver_material_tipo_carga,
            opciones=argumentos_material,
        ),
    ))


def procesar_archivo(
    ruta: Path,
    lector_ocr: object = None,
    fecha_desde: date | None = None,
    fecha_hasta: date | None = None,
    carpeta_catalogos: str | Path | None = None,
    registro_activacion: Mapping[str, EstadoOperacional | str] = (
        REGISTRO_ACTIVACION_MULTICAMPO_FASE1
    ),
    campos_controlados_autorizados: Collection[str] = frozenset(),
) -> dict[str, str]:
    """Procesa una guía reutilizando el OCR y extractor actuales."""
    textos = leer_texto_imagen(ruta, lector=lector_ocr)
    # Primero conserva el OCR y completa geometría; solo después aplica catálogos.
    # Así un RUT conocido no oculta el nombre bruto necesario para fuzzy y trazabilidad.
    datos = extraer_datos(textos)
    recuperacion_geometrica = False
    recuperacion_chofer = False
    recuperacion_patentes = False
    transporte_corregido = False
    bloques_guia = None
    campos_ausentes = any(
        datos.get(campo) in {None, "", "No encontrado"}
        for campo in ("cliente", "obra destino", "número de transporte")
    ) or datos.get("chofer") in {None, "", "No encontrado"} or _chofer_lineal_contaminado(datos.get("chofer"))
    if campos_ausentes:
        try:
            bloques_guia = leer_bloques_imagen(ruta, lector=lector_ocr)
            asociaciones = _extraer_asociaciones_geometricas(bloques_guia)
            for campo in ("cliente", "obra destino"):
                if datos.get(campo) in {None, "", "No encontrado"} and asociaciones.get(campo):
                    datos[campo] = asociaciones[campo]
                    recuperacion_geometrica = True
                    logger.info("%s recuperado mediante asociacion-geometrica-conservadora-v1", campo)
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
                        evidencia_focal = _leer_transporte_focal(
                            ruta,
                            decision_transporte["caja"],
                            lector=lector_ocr,
                        )
                        consenso = _consensuar_transporte_focal(
                            evidencia_focal["lecturas"],
                            str(decision_transporte.get("texto_global", "")),
                        )
                        if consenso.get("valor"):
                            datos["número de transporte"] = consenso["valor"]
                            transporte_corregido = True
                            logger.info("numero_transporte recuperado mediante consenso-focal-v1")
                        elif consenso.get("motivo") in {
                            "evidencia-baja-confianza-sin-respaldo",
                            "sin-mayoria-posicion-0",
                            "sin-mayoria-posicion-1",
                            "sin-mayoria-posicion-2",
                            "sin-mayoria-posicion-3",
                            "sin-mayoria-posicion-4",
                            "sin-mayoria-posicion-5",
                            "sin-mayoria-posicion-6",
                            "sin-mayoria-posicion-7",
                            "sin-mayoria-posicion-8",
                            "sin-mayoria-posicion-9",
                            "menos-de-dos-lecturas-focales-validas",
                        }:
                            datos["número de transporte"] = "No encontrado"
                            logger.info("numero_transporte abstiene por consenso-focal-conservador-v1")
                    else:
                        datos["número de transporte"] = decision_transporte["valor"]
                        logger.info("numero_transporte recuperado mediante transporte-contextual-numerico-v1")
        except Exception as exc:
            logger.warning("Asociación geométrica omitida: %s: %s", type(exc).__name__, exc)

    rut_cliente_inicial = str(datos.get("RUT del cliente", "No encontrado")).strip()
    if _rut_cliente_requiere_relectura(
        rut_cliente_inicial,
        datos.get("cliente", "No encontrado"),
        etiqueta_rut_observada=any(
            re.search(r"\bR\.?\s*U\.?\s*T\.?\b", _normalizar(texto))
            for texto in textos
        ),
    ):
        try:
            if bloques_guia is None:
                bloques_guia = leer_bloques_imagen(ruta, lector=lector_ocr)
            evidencia_rut_cliente = _leer_rut_cliente_focal(
                ruta, bloques_guia, lector=lector_ocr
            )
            if evidencia_rut_cliente.get("valor"):
                datos["RUT del cliente"] = str(evidencia_rut_cliente["valor"])
                logger.info(
                    "rut_cliente recuperado mediante consenso-focal-estructurado-v1"
                )
            else:
                logger.info(
                    "rut_cliente focal abstiene motivo=%s",
                    evidencia_rut_cliente.get("motivo", "sin-evidencia"),
                )
        except Exception as exc:
            logger.warning(
                "Relectura focal de RUT cliente omitida: %s: %s",
                type(exc).__name__, exc,
            )

    nombre_chofer_original = str(datos.get("chofer", "No encontrado")).strip()
    nombre_cliente_original = str(datos.get("cliente", "No encontrado")).strip()
    destino_original = str(datos.get("obra destino", "No encontrado")).strip()
    datos = enriquecer_datos_con_catalogos(
        datos, textos, carpeta_catalogos or "catalogos"
    )
    carpeta_catalogos_activa = Path(carpeta_catalogos or "catalogos")
    catalogo_vehiculos_cargado = cargar_catalogo_json(
        carpeta_catalogos_activa / "vehiculos.json"
    )
    catalogo_vehiculos = {
        clave: registro
        for clave, registro in catalogo_vehiculos_cargado.items()
        if isinstance(registro, dict)
        and str(registro.get("tipo", "")).strip().upper() in {"TRACTO", "CARRO"}
    }
    patentes_actuales = {
        "patente_tracto": str(datos.get("patente del tracto", "No encontrado")),
        "patente_rampla": str(datos.get("patente del carro", "No encontrado")),
    }
    if catalogo_vehiculos and any(
        valor in {"", "No encontrado"} or valor not in catalogo_vehiculos
        for valor in patentes_actuales.values()
    ):
        if bloques_guia is None:
            bloques_guia = leer_bloques_imagen(ruta, lector=lector_ocr)
        decision_patentes = _extraer_patentes_geometricas(
            bloques_guia, catalogo_vehiculos
        )
        for campo_publico, campo_datos in (
            ("patente_tracto", "patente del tracto"),
            ("patente_rampla", "patente del carro"),
        ):
            candidata = decision_patentes.get(campo_publico)
            actual = patentes_actuales[campo_publico]
            actual_valida = actual in catalogo_vehiculos
            if candidata and (not actual_valida or actual == candidata):
                datos[campo_datos] = candidata
                recuperacion_patentes = recuperacion_patentes or actual != candidata
            elif candidata and actual_valida and actual != candidata:
                datos[campo_datos] = "No encontrado"
                recuperacion_patentes = True
                logger.info("%s abstiene por conflicto OCR/catalogo", campo_publico)
    cantidad = (
        _extraer_cantidad_geometrica(bloques_guia)
        if bloques_guia is not None else None
    )
    origen = None
    catalogo_plantas = cargar_catalogo_json(
        carpeta_catalogos_activa / "plantas.json"
    )
    if isinstance(catalogo_plantas.get("plantas"), list):
        try:
            lecturas_origen = leer_encabezado_origen_focal(ruta, lector=lector_ocr)
            origen = _resolver_origen_documental(
                lecturas_origen, catalogo_plantas
            )
        except Exception as exc:
            logger.warning("Relectura focal de origen omitida: %s: %s", type(exc).__name__, exc)
    nombre_chofer_ocr = nombre_chofer_original
    rut_chofer = str(datos.get("RUT del chofer", "No encontrado")).strip()
    rut_cliente = str(datos.get("RUT del cliente", "No encontrado")).strip()
    nombre_cliente_ocr = nombre_cliente_original
    decision_cliente = None
    catalogo_clientes = None
    contexto_cliente = {
        "fuente": "procesamiento_masivo",
        "destino": str(datos.get("obra destino", "No encontrado")).strip(),
    }
    if nombre_cliente_ocr not in {"", "No encontrado"} or rut_cliente not in {"", "No encontrado"}:
        catalogo_clientes = cargar_catalogo_json(
            Path(carpeta_catalogos or "catalogos") / "clientes.json"
        )
        decision_cliente = resolver_cliente_rut(
            nombre_cliente_ocr,
            rut_cliente,
            catalogo_clientes,
            contexto=contexto_cliente,
        )
        datos["cliente"], requiere_revision_cliente = _integrar_resolucion_multicampo(
            campo="cliente",
            valor_ocr=nombre_cliente_ocr,
            valor_actual=datos.get("cliente", "No encontrado"),
            resultado=decision_cliente,
            etiqueta_log="resolucion-cliente-multicampo-v1",
            propagar_revision_contrato=True,
            registro_activacion=registro_activacion,
            campos_controlados_autorizados=campos_controlados_autorizados,
        )
    else:
        requiere_revision_cliente = False
    if catalogo_clientes is None:
        catalogo_clientes = cargar_catalogo_json(
            Path(carpeta_catalogos or "catalogos") / "clientes.json"
        )
    resultado_destino_sombra = _orquestar_destino_sombra(
        obra_destino=destino_original,
        catalogo_destinos=cargar_catalogo_json(
            Path(carpeta_catalogos or "catalogos") / "destinos.json"
        ),
        catalogo_clientes=catalogo_clientes,
        catalogo_plantas=cargar_catalogo_json(
            Path(carpeta_catalogos or "catalogos") / "plantas.json"
        ),
        id_cliente_canonico=(
            decision_cliente.identificador_canonico
            if decision_cliente is not None
            and decision_cliente.estado is EstadoResolucion.CONFIRMADO
            else ""
        ),
        cliente_canonico=(
            decision_cliente.valor_canonico
            if decision_cliente is not None
            and decision_cliente.estado is EstadoResolucion.CONFIRMADO
            else nombre_cliente_original
        ),
        contexto={"fuente": "procesamiento_masivo"},
    )
    if resultado_destino_sombra.completo:
        resumen_destino = resultado_destino_sombra.resumenes["destino"]
        decision_destino = resultado_destino_sombra.resultados["destino"]
        logger.info(
            "orquestador-destino-sombra-v1 estado=%s via=%s "
            "confianza=%.3f contradicciones=%d",
            resumen_destino.estado.value,
            decision_destino.via_decision,
            resumen_destino.confianza,
            resumen_destino.cantidad_contradicciones,
        )
        publicacion_destino = decidir_publicacion(
            "destino",
            str(datos.get("obra destino", "No encontrado")),
            decision_destino.destino_canonico or destino_original,
            registro=registro_activacion,
            autorizacion_controlada=(
                "destino" in campos_controlados_autorizados
            ),
        )
        datos["obra destino"] = publicacion_destino.valor
        logger.info(
            "politica-activacion campo=destino estado_operacional=%s "
            "publicar=%s motivo=%s",
            publicacion_destino.estado_operacional.value,
            publicacion_destino.publicar,
            publicacion_destino.motivo,
        )
    else:
        logger.warning(
            "orquestador-destino-sombra-v1 fallo=%s",
            resultado_destino_sombra.fallos["destino"].tipo_error,
        )
    if nombre_chofer_ocr not in {"", "No encontrado"} or rut_chofer not in {"", "No encontrado"}:
        catalogo_choferes = cargar_catalogo_json(
            Path(carpeta_catalogos or "catalogos") / "choferes.json"
        )
        decision_chofer = resolver_chofer_rut(
            nombre_chofer_ocr,
            rut_chofer,
            catalogo_choferes,
            contexto={"fuente": "procesamiento_masivo"},
        )
        datos["chofer"], requiere_revision_chofer = _integrar_resolucion_multicampo(
            campo="chofer",
            valor_ocr=nombre_chofer_ocr,
            valor_actual=datos.get("chofer", "No encontrado"),
            resultado=decision_chofer,
            etiqueta_log="resolucion-chofer-multicampo-v1",
            propagar_revision_contrato=True,
            registro_activacion=registro_activacion,
            campos_controlados_autorizados=campos_controlados_autorizados,
        )
    else:
        requiere_revision_chofer = False
    numero_guia_actual = str(datos.get("número de guía", "No encontrado")).strip()
    if numero_guia_actual in {"", "No encontrado"}:
        try:
            if bloques_guia is None:
                bloques_guia = leer_bloques_imagen(ruta, lector=lector_ocr)
            decision_guia = decidir_bloques_ocr(bloques_guia, numero_guia_actual)
            candidato_guia = str(decision_guia["valor"])
            if decision_guia["emitida"] and re.fullmatch(r"\d{5,8}", candidato_guia):
                datos["número de guía"] = candidato_guia
                logger.info("numero_guia recuperado mediante numero-guia-contextual-conservador-v1")
        except Exception as exc:  # El OCR secundario nunca invalida el procesamiento principal.
            logger.warning("Fallback espacial de numero_guia omitido: %s: %s", type(exc).__name__, exc)
    descripcion = extraer_descripcion_material(textos)
    tipo_carga_actual = clasificar_material(descripcion).value
    resultado_material_sombra = _orquestar_material_sombra(
        descripcion_material_ocr=descripcion,
        tipo_carga_ocr=tipo_carga_actual,
        catalogo_materiales=cargar_catalogo_json(
            Path(carpeta_catalogos or "catalogos") / "materiales.json"
        ),
        contexto={"fuente": "procesamiento_masivo"},
    )
    if resultado_material_sombra.completo:
        resumen_material = resultado_material_sombra.resumenes["material"]
        decision_material = resultado_material_sombra.resultados["material"]
        logger.info(
            "orquestador-material-sombra-v1 estado=%s via=%s "
            "confianza=%.3f contradicciones=%d",
            resumen_material.estado.value,
            decision_material.via_decision,
            resumen_material.confianza,
            resumen_material.cantidad_contradicciones,
        )
        publicacion_material = decidir_publicacion(
            "material",
            (descripcion, tipo_carga_actual),
            (
                decision_material.material_canonico or descripcion,
                decision_material.tipo_carga_canonico or tipo_carga_actual,
            ),
            registro=registro_activacion,
            autorizacion_controlada=(
                "material" in campos_controlados_autorizados
            ),
        )
        descripcion, tipo_carga_actual = publicacion_material.valor
        logger.info(
            "politica-activacion campo=material estado_operacional=%s "
            "publicar=%s motivo=%s",
            publicacion_material.estado_operacional.value,
            publicacion_material.publicar,
            publicacion_material.motivo,
        )
    else:
        logger.warning(
            "orquestador-material-sombra-v1 fallo=%s",
            resultado_material_sombra.fallos["material"].tipo_error,
        )
    valores_clave = (
        numero_guia_actual,
        datos.get("número de transporte"),
        datos.get("chofer"),
        datos.get("cliente"),
    )
    requiere_revision = any(
        not valor or valor == "No encontrado" for valor in valores_clave
    ) or recuperacion_geometrica or transporte_corregido or recuperacion_chofer or recuperacion_patentes
    if requiere_revision_chofer:
        requiere_revision = True
    if requiere_revision_cliente:
        requiere_revision = True

    return {
        "numero_guia": str(datos.get("número de guía", "No encontrado")),
        "numero_transporte": str(datos.get("número de transporte", "No encontrado")),
        "fecha": extraer_fecha(
            textos, fecha_desde=fecha_desde, fecha_hasta=fecha_hasta
        ),
        "chofer": str(datos.get("chofer", "No encontrado")),
        "rut_chofer": str(datos.get("RUT del chofer", "No encontrado")),
        "cliente": str(datos.get("cliente", "No encontrado")),
        "obra_destino": str(datos.get("obra destino", "No encontrado")),
        "patente_tracto": str(datos.get("patente del tracto", "No encontrado")),
        "patente_rampla": str(datos.get("patente del carro", "No encontrado")),
        "descripcion_material": descripcion,
        "tipo_carga": tipo_carga_actual,
        "indicador_revision": "REVISAR" if requiere_revision else "OK",
        "peso": str(datos.get("peso", "No encontrado")),
        "cantidad": str(cantidad or "No encontrado"),
        "origen": str(origen or "No encontrado"),
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
        encabezado = lector.fieldnames
        filas = list(lector)
    if encabezado is None or encabezado[: len(COLUMNAS)] != COLUMNAS:
        raise ValueError(
            "El CSV existente tiene un esquema incompatible. "
            "Se esperaba el encabezado Atlas separado por ';'."
        )
    permitidas = set(COLUMNAS_PUBLICACION + COLUMNAS_TRAZA_HISTORICA)
    if len(encabezado) != len(set(encabezado)) or any(
        columna not in permitidas for columna in encabezado
    ):
        raise ValueError(
            "El CSV existente tiene un esquema incompatible. "
            "Contiene columnas desconocidas o repetidas."
        )
    faltantes = [
        columna for columna in ("peso", "cantidad", "origen")
        if columna not in encabezado
    ]
    if faltantes:
        encabezado_nuevo = [*encabezado, *faltantes]
        temporal = ruta_csv.with_suffix(ruta_csv.suffix + ".tmp")
        try:
            with temporal.open("w", newline="", encoding="utf-8-sig") as archivo:
                escritor = csv.DictWriter(
                    archivo, fieldnames=encabezado_nuevo, delimiter=";",
                    extrasaction="ignore",
                )
                escritor.writeheader()
                escritor.writerows(filas)
            temporal.replace(ruta_csv)
        finally:
            if temporal.exists():
                temporal.unlink()
    return bool(filas)


def _escribir_filas(ruta_csv: Path, filas: list[dict[str, str]]) -> None:
    if not filas:
        return
    ruta_csv.parent.mkdir(parents=True, exist_ok=True)
    existe_con_contenido = ruta_csv.exists() and ruta_csv.stat().st_size > 0
    columnas_salida = COLUMNAS_PUBLICACION
    if existe_con_contenido:
        with ruta_csv.open("r", newline="", encoding="utf-8-sig") as archivo:
            columnas_existentes = next(csv.reader(archivo, delimiter=";"), None)
        if columnas_existentes:
            columnas_salida = columnas_existentes
    with ruta_csv.open("a", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(
            archivo, fieldnames=columnas_salida, delimiter=";", extrasaction="ignore"
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
    carpeta_catalogos: str | Path | None = None,
    registro_activacion: Mapping[str, EstadoOperacional | str] | None = None,
    campos_controlados_autorizados: Collection[str] | None = None,
) -> dict[str, int | float]:
    """Procesa secuencialmente una carpeta, persistiendo avances periódicos."""
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

    def ejecutar(ruta: Path) -> Mapping[str, object]:
        nonlocal lector_compartido
        if procesador is not None:
            return procesador(ruta)
        if lector_compartido is None:
            lector_compartido = crear_lector_ocr()
        if fecha_desde is None and fecha_hasta is None:
            argumentos = {"lector_ocr": lector_compartido}
        else:
            argumentos = {
                "lector_ocr": lector_compartido,
                "fecha_desde": fecha_desde,
                "fecha_hasta": fecha_hasta,
            }
        if carpeta_catalogos is not None:
            argumentos["carpeta_catalogos"] = carpeta_catalogos
        if registro_activacion is not None:
            argumentos["registro_activacion"] = registro_activacion
        if campos_controlados_autorizados is not None:
            argumentos["campos_controlados_autorizados"] = (
                campos_controlados_autorizados
            )
        return procesar_archivo(ruta, **argumentos)

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
                    for columna in COLUMNAS_PUBLICACION
                }
                fila.update(
                    archivo=identificador,
                    estado_procesamiento="OK",
                    error="",
                )
            except Exception as error:  # cada documento es una unidad independiente
                fila = {columna: "" for columna in COLUMNAS_PUBLICACION}
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
