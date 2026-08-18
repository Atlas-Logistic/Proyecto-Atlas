"""Bloque ONELOGIS/DESTINO/KM -- re-enriquecimiento telemétrico SIN OCR de
filas ya procesadas cuya telemetría existe en caché pero nunca se persistió
en el dataset (ver `docs/BITACORA_TECNICA_CRONOLOGICA.md`: 7 casos reales
del lote 15, p. ej. 464624/BDFG50 -- el trip ya estaba cacheado, la fila no
tenía ningún campo de telemetría).

Todos los tests son unitarios/deterministas: la caché de telemetría se
prepara a mano con `RepositorioTelemetria`, nunca se toca la red real.
"""
from __future__ import annotations

import csv
from datetime import date

import pytest

from atlas_core.catalogo_plantas import CatalogoPlantas, EstadoCalidad
from atlas_core.procesamiento_masivo import COLUMNAS
from atlas_core.revalidacion_documental import revalidar_telemetria_sin_ocr
from atlas_core.rutas.modelos import Coordenadas
from atlas_core.telemetria.modelos import PosicionTelemetria, ViajeTelemetria
from atlas_core.telemetria.proveedor import ProveedorTelemetriaSoloCache
from atlas_core.telemetria.repositorio import RepositorioTelemetria
from atlas_core.telemetria.servicio import ServicioTelemetria

COORD_AZA_RENCA = Coordenadas(-70.685226, -33.401595)
COORD_AZA_COLINA = Coordenadas(-70.665977, -33.137558)
FECHA_DOC = "11-08-2026"  # DD-MM-YYYY, formato documental real
FECHA_ISO = date(2026, 8, 11)


def _fila_csv(**overrides):
    fila = {c: "" for c in COLUMNAS}
    fila.update({
        "archivo": "464624.jpeg", "estado_procesamiento": "OK", "numero_guia": "464624",
        "numero_transporte": "0000352804", "fecha": FECHA_DOC, "chofer": "CHOFER PRUEBA",
        "cliente": "CLIENTE PRUEBA", "obra_destino": "OBRA PRUEBA",
        "patente_tracto": "BDFG50", "patente_rampla": "No encontrado",
        "descripcion_material": "MATERIAL", "tipo_carga": "OTRO",
        "indicador_revision": "REVISAR",
        "motivos_revision_documento": "",
        "hora_entrada_aza": "10:30", "hora_salida_aza": "11:48",
        "planta_origen_id": "", "planta_origen_nombre": "",
        "origen_determinado_por": "", "evidencia_origen": "",
        # Campos de ruta/km ya calculados de un procesamiento previo -- se
        # usan para verificar que esta función nunca los toca (fuera de
        # alcance, requiere ORS).
        "distancia_km": "", "estado_ruta": "REQUIERE_REVISION",
        "motivo_ruta": "MULTIPLES_UBICACIONES_DISPERSAS(5)",
    })
    fila.update(overrides)
    return fila


def _escribir_csv(ruta, filas):
    with ruta.open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader()
        escritor.writerows(filas)


def _leer_csv(ruta):
    with ruta.open("r", newline="", encoding="utf-8-sig") as archivo:
        return list(csv.DictReader(archivo, delimiter=";"))


@pytest.fixture
def entorno(tmp_path):
    catalogos = tmp_path / "catalogos_privados"
    catalogos.mkdir()
    catalogo = CatalogoPlantas(catalogos / "plantas.json")
    catalogo.crear(
        nombre="AZA RENCA", pais="CHILE", fuente="PRUEBA",
        direccion="LA UNION 3070", comuna="RENCA", region="RM",
        latitud=COORD_AZA_RENCA.latitud, longitud=COORD_AZA_RENCA.longitud,
        estado_calidad=EstadoCalidad.CONFIRMADA,
    )
    catalogo.crear(
        nombre="AZA COLINA", pais="CHILE", fuente="PRUEBA",
        direccion="AV. PDTE. EDUARDO FREI MONTALVA 18500", comuna="COLINA", region="RM",
        latitud=COORD_AZA_COLINA.latitud, longitud=COORD_AZA_COLINA.longitud,
        estado_calidad=EstadoCalidad.CONFIRMADA,
    )
    dataset = tmp_path / "analisis_completo_guias.csv"
    return {"catalogos": catalogos, "dataset": dataset}


def _repositorio(catalogos):
    return RepositorioTelemetria(catalogos / "telemetria_cache.json")


def _proveedor_solo_cache():
    return ProveedorTelemetriaSoloCache(nombre="onelogis")


# --- CASO 1: cache disponible ahora -> re-enriquecimiento la incorpora ---


def test_caso1_cache_disponible_incorpora_telemetria(entorno):
    repo = _repositorio(entorno["catalogos"])
    repo.guardar_viajes(
        "onelogis", "BDFG50", FECHA_ISO, FECHA_ISO,
        (ViajeTelemetria("t1", "BDFG50", "2026-08-11 11:40:00", "2026-08-11 11:50:00", 1.0),),
    )
    repo.guardar_breadcrumbs(
        "onelogis", "t1",
        (PosicionTelemetria(COORD_AZA_RENCA.latitud, COORD_AZA_RENCA.longitud, "2026-08-11 11:45:00"),),
    )
    _escribir_csv(entorno["dataset"], [_fila_csv()])

    resultado = revalidar_telemetria_sin_ocr(
        ruta_dataset=entorno["dataset"], carpeta_catalogos=entorno["catalogos"],
    )

    assert resultado["guias_actualizadas"] == ["464624"]
    filas = _leer_csv(entorno["dataset"])
    assert filas[0]["proveedor_telemetria"] == "onelogis"
    assert filas[0]["estado_telemetria"]
    assert filas[0]["origen_gps"] == "ORIGEN_GPS_CONFIRMADO"
    assert filas[0]["planta_origen_nombre"] == "AZA RENCA"
    assert filas[0]["origen_determinado_por"] == "TELEMETRIA_GPS"


# --- CASO 2: ya enriquecido -> idempotente ---


def test_caso2_fila_ya_enriquecida_es_idempotente(entorno):
    repo = _repositorio(entorno["catalogos"])
    repo.guardar_viajes(
        "onelogis", "BDFG50", FECHA_ISO, FECHA_ISO,
        (ViajeTelemetria("t1", "BDFG50", "2026-08-11 11:40:00", "2026-08-11 11:50:00", 1.0),),
    )
    fila = _fila_csv(estado_telemetria="SELECCIONADO", origen_gps="ORIGEN_GPS_CONFIRMADO")
    _escribir_csv(entorno["dataset"], [fila])

    resultado = revalidar_telemetria_sin_ocr(
        ruta_dataset=entorno["dataset"], carpeta_catalogos=entorno["catalogos"],
    )

    assert resultado["guias_actualizadas"] == []
    filas = _leer_csv(entorno["dataset"])
    assert filas[0] == fila

    # Reejecutar de nuevo no cambia nada (verdadera idempotencia).
    resultado_2 = revalidar_telemetria_sin_ocr(
        ruta_dataset=entorno["dataset"], carpeta_catalogos=entorno["catalogos"],
    )
    assert resultado_2["guias_actualizadas"] == []


# --- CASO 3: sin ningún trip cacheado (equivalente a SIN_HISTORICO real,
# que nunca se persiste en caché) -> no inventa telemetría ---


def test_caso3_sin_historico_en_cache_no_inventa_nada(entorno):
    # Repositorio vacío -- ninguna entrada para BDFG50/11-08-2026.
    fila_original = _fila_csv()
    _escribir_csv(entorno["dataset"], [fila_original])

    resultado = revalidar_telemetria_sin_ocr(
        ruta_dataset=entorno["dataset"], carpeta_catalogos=entorno["catalogos"],
    )

    assert resultado["guias_actualizadas"] == []
    filas = _leer_csv(entorno["dataset"])
    assert filas[0] == fila_original
    assert filas[0]["estado_telemetria"] == ""  # nunca sintetiza un estado


# --- CASO 4: patente/fecha no calzan con ninguna entrada de caché ---


def test_caso4_patente_no_matchea_cache_se_abstiene(entorno):
    repo = _repositorio(entorno["catalogos"])
    # Cache tiene datos, pero de OTRA patente.
    repo.guardar_viajes(
        "onelogis", "TZWR86", FECHA_ISO, FECHA_ISO,
        (ViajeTelemetria("t1", "TZWR86", "2026-08-11 11:40:00", "2026-08-11 11:50:00", 1.0),),
    )
    fila_original = _fila_csv(patente_tracto="BDFG50")
    _escribir_csv(entorno["dataset"], [fila_original])

    resultado = revalidar_telemetria_sin_ocr(
        ruta_dataset=entorno["dataset"], carpeta_catalogos=entorno["catalogos"],
    )

    assert resultado["guias_actualizadas"] == []
    assert _leer_csv(entorno["dataset"])[0] == fila_original


def test_caso4_fecha_no_matchea_cache_se_abstiene(entorno):
    repo = _repositorio(entorno["catalogos"])
    # Cache tiene datos de la misma patente, pero OTRO día.
    repo.guardar_viajes(
        "onelogis", "BDFG50", date(2026, 8, 12), date(2026, 8, 12),
        (ViajeTelemetria("t1", "BDFG50", "2026-08-12 11:40:00", "2026-08-12 11:50:00", 1.0),),
    )
    fila_original = _fila_csv()  # fecha = 11-08-2026
    _escribir_csv(entorno["dataset"], [fila_original])

    resultado = revalidar_telemetria_sin_ocr(
        ruta_dataset=entorno["dataset"], carpeta_catalogos=entorno["catalogos"],
    )

    assert resultado["guias_actualizadas"] == []
    assert _leer_csv(entorno["dataset"])[0] == fila_original


# --- CASO 5: telemetría parcial -- origen confirmado, recorrido de
# entrega no seleccionado -- conserva el estado parcial correcto ---


def test_caso5_telemetria_parcial_conserva_estado_correcto(entorno):
    repo = _repositorio(entorno["catalogos"])
    # Un único trip corto (0.1km, "no sustancial") cerca de la hora de
    # salida -- resuelve origen (ventana ancha, sin filtro de distancia)
    # pero NO selecciona un "recorrido operacional" de entrega (T2, exige
    # >=5km) -- distancia_gps_km/evidencia_telemetria deben quedar vacíos.
    repo.guardar_viajes(
        "onelogis", "BDFG50", FECHA_ISO, FECHA_ISO,
        (ViajeTelemetria("t1", "BDFG50", "2026-08-11 11:44:00", "2026-08-11 11:46:00", 0.1),),
    )
    repo.guardar_breadcrumbs(
        "onelogis", "t1",
        (PosicionTelemetria(COORD_AZA_RENCA.latitud, COORD_AZA_RENCA.longitud, "2026-08-11 11:45:00"),),
    )
    _escribir_csv(entorno["dataset"], [_fila_csv()])

    revalidar_telemetria_sin_ocr(
        ruta_dataset=entorno["dataset"], carpeta_catalogos=entorno["catalogos"],
    )

    fila = _leer_csv(entorno["dataset"])[0]
    assert fila["origen_gps"] == "ORIGEN_GPS_CONFIRMADO"
    assert fila["planta_origen_nombre"] == "AZA RENCA"
    assert fila["distancia_gps_km"] == ""  # recorrido de entrega no seleccionado
    assert fila["evidencia_telemetria"] == ""


# --- CASO 6: nunca cambia OCR/cliente/obra/material/patentes/otros datos ---


def test_caso6_no_toca_datos_documentales_ni_ruta_previa(entorno):
    repo = _repositorio(entorno["catalogos"])
    repo.guardar_viajes(
        "onelogis", "BDFG50", FECHA_ISO, FECHA_ISO,
        (ViajeTelemetria("t1", "BDFG50", "2026-08-11 11:40:00", "2026-08-11 11:50:00", 1.0),),
    )
    repo.guardar_breadcrumbs(
        "onelogis", "t1",
        (PosicionTelemetria(COORD_AZA_RENCA.latitud, COORD_AZA_RENCA.longitud, "2026-08-11 11:45:00"),),
    )
    fila_original = _fila_csv()
    _escribir_csv(entorno["dataset"], [dict(fila_original)])

    revalidar_telemetria_sin_ocr(
        ruta_dataset=entorno["dataset"], carpeta_catalogos=entorno["catalogos"],
    )

    fila = _leer_csv(entorno["dataset"])[0]
    campos_documentales = (
        "chofer", "cliente", "obra_destino", "patente_tracto", "patente_rampla",
        "descripcion_material", "tipo_carga", "numero_guia", "numero_transporte",
        "fecha", "hora_entrada_aza", "hora_salida_aza",
    )
    for campo in campos_documentales:
        assert fila[campo] == fila_original[campo], campo
    # Ruta/km ya calculados antes -- fuera de alcance, no se recalculan aquí.
    assert fila["distancia_km"] == ""
    assert fila["estado_ruta"] == "REQUIERE_REVISION"
    assert fila["motivo_ruta"] == "MULTIPLES_UBICACIONES_DISPERSAS(5)"


def test_breadcrumbs_no_cacheados_nunca_disparan_red_real(entorno):
    """La lista de viajes del día SÍ está cacheada (así que `buscar_viajes`
    nunca llega al proveedor -- `llamadas_viajes == 0`), pero breadcrumbs
    de "t1" NO lo están: `ServicioTelemetria.obtener_breadcrumbs` cae al
    proveedor, que SÍ recibe esa llamada (`llamadas_breadcrumbs == 1`) --
    pero ese proveedor es `ProveedorTelemetriaSoloCache`, que nunca abre
    una conexión real; sólo se abstiene con `SIN_CONEXION` en memoria.
    Esto es justamente lo que garantiza que, sin importar qué tan
    incompleta esté la caché a nivel de breadcrumbs individuales, jamás se
    dispara una llamada real a Onelogis -- nunca lanza, nunca se cuelga."""
    repo = _repositorio(entorno["catalogos"])
    repo.guardar_viajes(
        "onelogis", "BDFG50", FECHA_ISO, FECHA_ISO,
        (ViajeTelemetria("t1", "BDFG50", "2026-08-11 11:40:00", "2026-08-11 11:50:00", 1.0),),
    )
    # Deliberadamente NO se guardan breadcrumbs de "t1".
    proveedor = _proveedor_solo_cache()
    servicio = ServicioTelemetria(proveedor, repo)
    _escribir_csv(entorno["dataset"], [_fila_csv()])

    resultado = revalidar_telemetria_sin_ocr(
        ruta_dataset=entorno["dataset"], carpeta_catalogos=entorno["catalogos"],
        servicio_telemetria=servicio,
    )

    assert resultado["guias_actualizadas"] == ["464624"]
    assert proveedor.llamadas_viajes == 0  # la lista de viajes SÍ estaba cacheada
    assert proveedor.llamadas_vehiculos == 0
    assert proveedor.llamadas_posicion == 0
    # El proveedor solo-caché sí es invocado (breadcrumb no cacheado), pero
    # nunca toca red -- se abstiene en memoria, nunca lanza ni bloquea.
    assert proveedor.llamadas_breadcrumbs >= 1
    fila = _leer_csv(entorno["dataset"])[0]
    assert fila["origen_gps"] == "ORIGEN_GPS_NO_DETERMINADO"


# --- Fase R1.1: sin confirmación GPS con telemetría real, el origen
# documental heredado se descarta, nunca se conserva en silencio ---


def test_conflicto_gps_descarta_origen_documental_heredado(entorno):
    repo = _repositorio(entorno["catalogos"])
    # Dos trips con evidencia real cerca de DOS plantas distintas, en la
    # misma ventana documental -- conflicto real (score sin margen
    # suficiente para desempatar).
    repo.guardar_viajes(
        "onelogis", "BDFG50", FECHA_ISO, FECHA_ISO,
        (
            ViajeTelemetria("t1", "BDFG50", "2026-08-11 10:20:00", "2026-08-11 10:40:00", 8.0),
            ViajeTelemetria("t2", "BDFG50", "2026-08-11 11:20:00", "2026-08-11 11:40:00", 8.0),
        ),
    )
    repo.guardar_breadcrumbs(
        "onelogis", "t1",
        (
            PosicionTelemetria(COORD_AZA_RENCA.latitud, COORD_AZA_RENCA.longitud, "2026-08-11 10:25:00"),
            PosicionTelemetria(COORD_AZA_RENCA.latitud, COORD_AZA_RENCA.longitud, "2026-08-11 10:35:00"),
        ),
    )
    repo.guardar_breadcrumbs(
        "onelogis", "t2",
        (
            PosicionTelemetria(COORD_AZA_COLINA.latitud, COORD_AZA_COLINA.longitud, "2026-08-11 11:25:00"),
            PosicionTelemetria(COORD_AZA_COLINA.latitud, COORD_AZA_COLINA.longitud, "2026-08-11 11:35:00"),
        ),
    )
    fila_original = _fila_csv(
        planta_origen_id="PLANTA-HEREDADA", planta_origen_nombre="AZA RENCA (documental)",
        origen_determinado_por="DOCUMENTO", evidencia_origen="ENCABEZADO_DOCUMENTO",
        hora_entrada_aza="10:00", hora_salida_aza="11:48",
    )
    _escribir_csv(entorno["dataset"], [fila_original])

    revalidar_telemetria_sin_ocr(
        ruta_dataset=entorno["dataset"], carpeta_catalogos=entorno["catalogos"],
    )

    fila = _leer_csv(entorno["dataset"])[0]
    assert fila["origen_gps"] == "ORIGEN_GPS_CONFLICTO"
    assert fila["planta_origen_id"] == ""
    assert fila["planta_origen_nombre"] == ""
    assert fila["origen_determinado_por"] == ""


# --- origen cambia y había km ya calculados con el origen anterior --
# se invalidan (nunca queda un km que ya no corresponde), pero NO se
# recalculan (eso requeriría ORS, fuera de alcance) ---


def test_origen_cambia_invalida_km_previo_sin_recalcular(entorno):
    repo = _repositorio(entorno["catalogos"])
    repo.guardar_viajes(
        "onelogis", "BDFG50", FECHA_ISO, FECHA_ISO,
        (ViajeTelemetria("t1", "BDFG50", "2026-08-11 11:40:00", "2026-08-11 11:50:00", 1.0),),
    )
    repo.guardar_breadcrumbs(
        "onelogis", "t1",
        (PosicionTelemetria(COORD_AZA_COLINA.latitud, COORD_AZA_COLINA.longitud, "2026-08-11 11:45:00"),),
    )
    # La fila ya trae planta AZA RENCA (documental) con una ruta/km ya
    # calculados a partir de ese origen -- el GPS real confirma AZA COLINA.
    fila_original = _fila_csv(
        planta_origen_id="PLANTA-RENCA", planta_origen_nombre="AZA RENCA",
        origen_determinado_por="DOCUMENTO", evidencia_origen="ENCABEZADO_DOCUMENTO",
        distancia_km="16.73", duracion_min="25.0", proveedor_ruta="openrouteservice",
        estado_ruta="RUTA_CALCULADA", motivo_ruta="",
    )
    _escribir_csv(entorno["dataset"], [fila_original])

    revalidar_telemetria_sin_ocr(
        ruta_dataset=entorno["dataset"], carpeta_catalogos=entorno["catalogos"],
    )

    fila = _leer_csv(entorno["dataset"])[0]
    assert fila["planta_origen_nombre"] == "AZA COLINA"
    assert fila["origen_determinado_por"] == "TELEMETRIA_GPS"
    # El km del origen ANTERIOR (RENCA) queda invalidado, no recalculado.
    assert fila["distancia_km"] == ""
    assert fila["duracion_min"] == ""
    assert fila["proveedor_ruta"] == ""
    assert fila["estado_ruta"] == "REQUIERE_REVISION"
    assert fila["motivo_ruta"] == "ORIGEN_ACTUALIZADO_PENDIENTE_RECALCULO_RUTA"


def test_origen_no_cambia_conserva_km_previo_intacto(entorno):
    """Si la planta GPS confirmada COINCIDE con la ya documental, no hay
    nada que invalidar -- el km previo (calculado con el origen correcto
    desde el principio) se conserva byte a byte."""
    repo = _repositorio(entorno["catalogos"])
    repo.guardar_viajes(
        "onelogis", "BDFG50", FECHA_ISO, FECHA_ISO,
        (ViajeTelemetria("t1", "BDFG50", "2026-08-11 11:40:00", "2026-08-11 11:50:00", 1.0),),
    )
    repo.guardar_breadcrumbs(
        "onelogis", "t1",
        (PosicionTelemetria(COORD_AZA_RENCA.latitud, COORD_AZA_RENCA.longitud, "2026-08-11 11:45:00"),),
    )
    catalogo_plantas = CatalogoPlantas(entorno["catalogos"] / "plantas.json")
    planta_renca_id = next(p.planta_id for p in catalogo_plantas.listar() if p.nombre == "AZA RENCA")
    fila_original = _fila_csv(
        planta_origen_id=planta_renca_id, planta_origen_nombre="AZA RENCA",
        origen_determinado_por="DOCUMENTO", evidencia_origen="ENCABEZADO_DOCUMENTO",
        distancia_km="16.73", duracion_min="25.0", proveedor_ruta="openrouteservice",
        estado_ruta="RUTA_CALCULADA", motivo_ruta="",
    )
    _escribir_csv(entorno["dataset"], [fila_original])

    revalidar_telemetria_sin_ocr(
        ruta_dataset=entorno["dataset"], carpeta_catalogos=entorno["catalogos"],
    )

    fila = _leer_csv(entorno["dataset"])[0]
    assert fila["planta_origen_nombre"] == "AZA RENCA"
    assert fila["origen_determinado_por"] == "TELEMETRIA_GPS"
    assert fila["distancia_km"] == "16.73"
    assert fila["estado_ruta"] == "RUTA_CALCULADA"


# --- CASO 7: dos documentos del mismo viaje -- después gestor_viajes
# puede consolidar origen con la jerarquía ya publicada ---


def test_caso7_dos_documentos_revalidados_permiten_consolidar_origen_del_viaje(entorno):
    from atlas_core.gestor_viajes import Viaje, _documento_desde_fila

    repo = _repositorio(entorno["catalogos"])
    repo.guardar_viajes(
        "onelogis", "BDFG50", FECHA_ISO, FECHA_ISO,
        (ViajeTelemetria("t1", "BDFG50", "2026-08-11 11:40:00", "2026-08-11 11:50:00", 1.0),),
    )
    repo.guardar_breadcrumbs(
        "onelogis", "t1",
        (PosicionTelemetria(COORD_AZA_RENCA.latitud, COORD_AZA_RENCA.longitud, "2026-08-11 11:45:00"),),
    )
    fila_a = _fila_csv(numero_guia="464624", archivo="464624.jpeg")
    fila_b = _fila_csv(
        numero_guia="464625", archivo="464625.jpeg",
        # documento hermano sin evidencia GPS propia -- no debe degradar
        # al viaje una vez que el otro documento sí resolvió por GPS.
    )
    _escribir_csv(entorno["dataset"], [fila_a, fila_b])

    revalidar_telemetria_sin_ocr(
        ruta_dataset=entorno["dataset"], carpeta_catalogos=entorno["catalogos"],
    )

    filas = _leer_csv(entorno["dataset"])
    documentos = [
        _documento_desde_fila(f, normalizador_chofer=None) for f in filas
    ]
    viaje = Viaje(
        viaje_id="viaje-prueba", numero_transporte="0000352804",
        fecha=FECHA_DOC, documentos=documentos,
    )

    assert viaje.origen_determinado_por == "TELEMETRIA_GPS"
    assert viaje.planta_origen_nombre == "AZA RENCA"
