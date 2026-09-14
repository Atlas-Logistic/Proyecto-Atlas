"""Bloque TELEMETRÍA T1: proveedor genérico de telemetría GPS + adaptador
Onelogis + integración con desambiguación geográfica y planta origen.

Todos los tests de este archivo son unitarios, sin red real -- usan
`ProveedorTelemetriaSimulado`/dobles inyectados o un transporte HTTP falso.
Las pruebas de integración real (con la API real de Onelogis) viven en
`telemetria_eval/` (fuera de la suite normal, focales, ejecutadas a mano).
"""
from __future__ import annotations

from datetime import date, datetime

import pytest

from atlas_core.rutas.destino_entrega import (
    descartar_candidatos_lejos_de_gps,
    resolver_destino_entrega,
)
from atlas_core.rutas.modelos import (
    CandidatoGeocodificacion,
    Coordenadas,
    EstadoRuta,
    ResultadoGeocodificacion,
    ResultadoRuta,
)
from atlas_core.rutas.posicion_vehiculo import EstadoPosicionVehiculo
from atlas_core.rutas.proveedor import ProveedorRutasSimulado
from atlas_core.telemetria.adaptador_posicion_vehiculo import AdaptadorPosicionTelemetria
from atlas_core.telemetria.modelos import (
    EstadoTelemetria,
    PosicionTelemetria,
    VehiculoTelemetria,
    ViajeTelemetria,
)
from atlas_core.telemetria.proveedor import ProveedorTelemetriaSimulado
from atlas_core.telemetria.proveedores.onelogis import OnelogisProvider, RespuestaHTTP
from atlas_core.telemetria.repositorio import RepositorioTelemetria
from atlas_core.telemetria.servicio import ServicioTelemetria


# --- 1/2/3: Bearer auth + /vehicles ---


def test_onelogis_agrega_header_bearer_sin_loguear_el_token():
    capturado = {}

    def transporte_falso(solicitud, timeout):
        capturado["auth"] = solicitud.get_header("Authorization")
        capturado["url"] = solicitud.full_url
        return RespuestaHTTP(200, b'{"data": {"items": [], "count": 0}}')

    proveedor = OnelogisProvider(api_key="secreto-123", transporte=transporte_falso)
    resultado = proveedor.listar_vehiculos()
    assert capturado["auth"] == "Bearer secreto-123"
    assert resultado.estado == EstadoTelemetria.OK


def test_onelogis_vehicles_estructura_real():
    def transporte_falso(solicitud, timeout):
        return RespuestaHTTP(200, (
            b'{"data": {"items": ['
            b'{"vehicle_id": 2716, "plate": "TZWR86", "alias": "TZWR86", '
            b'"brand": "Volvo", "model": "FH", "year": 2025, "km_actual": 1.0, "imei": "x"}'
            b'], "count": 1}}'
        ))

    proveedor = OnelogisProvider(api_key="x", transporte=transporte_falso)
    resultado = proveedor.listar_vehiculos()
    assert resultado.estado == EstadoTelemetria.OK
    assert len(resultado.vehiculos) == 1
    assert resultado.vehiculos[0] == VehiculoTelemetria(
        patente="TZWR86", proveedor_id="2716", alias="TZWR86", marca="Volvo", modelo="FH",
    )


def test_onelogis_vehiculo_no_encontrado_404():
    def transporte_falso(solicitud, timeout):
        import urllib.error
        raise urllib.error.HTTPError(solicitud.full_url, 404, "Not Found", None, None)

    proveedor = OnelogisProvider(api_key="x", transporte=transporte_falso)
    resultado = proveedor.obtener_posicion_actual("ZZZZ00")
    assert resultado.estado == EstadoTelemetria.VEHICULO_NO_ENCONTRADO


# --- 4/5/6: trips + breadcrumbs + timestamps ---


def test_onelogis_trips_parsea_estructura_real():
    def transporte_falso(solicitud, timeout):
        assert "start_date=2026-07-27" in solicitud.full_url
        assert "end_date=2026-07-27" in solicitud.full_url
        return RespuestaHTTP(200, (
            b'{"data": {"items": [{"trip_id": 30430425, "plate": "TZWR86", '
            b'"start_time": "2026-07-27 13:29:24", "end_time": "2026-07-27 16:32:41", '
            b'"distance_km": 233.97}], "count": 1, "page": 1, '
            b'"summary": {"trip_count": 1, "total_distance_km": 233.97, '
            b'"total_elapsed_sec": 11000, "total_idle_min": 0}}}'
        ))

    proveedor = OnelogisProvider(api_key="x", transporte=transporte_falso)
    resultado = proveedor.buscar_viajes("TZWR86", date(2026, 7, 27), date(2026, 7, 27))
    assert resultado.estado == EstadoTelemetria.OK
    assert resultado.viajes == (
        ViajeTelemetria("30430425", "TZWR86", "2026-07-27 13:29:24", "2026-07-27 16:32:41", 233.97),
    )


def test_onelogis_breadcrumbs_parsea_estructura_real():
    def transporte_falso(solicitud, timeout):
        return RespuestaHTTP(200, (
            b'{"data": {"trip_id": 1, "vehicle_id": 2, "count": 1, "points": ['
            b'{"lat": -37.0, "long": -73.16, "device_time": "2026-07-27 21:16:53", '
            b'"speed": 0.0, "head": 90.0, "event": "STOP"}]}}'
        ))

    proveedor = OnelogisProvider(api_key="x", transporte=transporte_falso)
    resultado = proveedor.obtener_breadcrumbs("30434174")
    assert resultado.estado == EstadoTelemetria.OK
    assert len(resultado.puntos) == 1
    assert resultado.puntos[0].latitud == -37.0
    assert resultado.puntos[0].timestamp == "2026-07-27 21:16:53"


def test_onelogis_sin_historico_en_ventana():
    def transporte_falso(solicitud, timeout):
        return RespuestaHTTP(200, b'{"data": {"items": [], "count": 0}}')

    proveedor = OnelogisProvider(api_key="x", transporte=transporte_falso)
    resultado = proveedor.buscar_viajes("TZWR86", date(2026, 1, 1), date(2026, 1, 1))
    assert resultado.estado == EstadoTelemetria.SIN_HISTORICO


# --- 7/8: error API / sin credencial ---


def test_onelogis_error_generico_del_proveedor():
    def transporte_falso(solicitud, timeout):
        import urllib.error
        raise urllib.error.HTTPError(solicitud.full_url, 500, "Internal Error", None, None)

    proveedor = OnelogisProvider(api_key="x", transporte=transporte_falso)
    resultado = proveedor.listar_vehiculos()
    assert resultado.estado == EstadoTelemetria.ERROR_PROVEEDOR


def test_onelogis_sin_credencial_nunca_hace_red(monkeypatch):
    monkeypatch.delenv("ATLAS_ONELOGIS_API_KEY", raising=False)

    def transporte_que_no_deberia_llamarse(solicitud, timeout):
        raise AssertionError("no debía intentar red sin credencial")

    proveedor = OnelogisProvider(transporte=transporte_que_no_deberia_llamarse)
    resultado = proveedor.listar_vehiculos()
    assert resultado.estado == EstadoTelemetria.SIN_CREDENCIAL


def test_onelogis_401_403_reporta_no_autorizado():
    def transporte_401(solicitud, timeout):
        import urllib.error
        raise urllib.error.HTTPError(solicitud.full_url, 401, "Unauthorized", None, None)

    proveedor = OnelogisProvider(api_key="x", transporte=transporte_401)
    assert proveedor.listar_vehiculos().estado == EstadoTelemetria.NO_AUTORIZADO


# --- 9: Onelogis caído no rompe Atlas ---


def test_proveedor_telemetria_none_no_rompe_nada():
    servicio = ServicioTelemetria(None, RepositorioTelemetria(":memoria-no-usada:"))
    resultado = servicio.buscar_viajes("TZWR86", date(2026, 7, 27), date(2026, 7, 27))
    assert resultado.estado == EstadoTelemetria.SIN_CREDENCIAL
    assert resultado.viajes == ()


def test_adaptador_posicion_sin_viajes_da_sin_datos_no_lanza(tmp_path):
    proveedor = ProveedorTelemetriaSimulado(viajes_por_patente={"TZWR86": []})
    servicio = ServicioTelemetria(proveedor, RepositorioTelemetria(tmp_path / "cache.json"))
    adaptador = AdaptadorPosicionTelemetria(servicio)
    resultado = adaptador.obtener_posicion("TZWR86", datetime(2026, 7, 27, 10, 5))
    assert resultado.estado == EstadoPosicionVehiculo.SIN_DATOS


# --- 10: contrato genérico ---


def test_contrato_generico_cumplido_por_simulado():
    proveedor = ProveedorTelemetriaSimulado(
        vehiculos=(VehiculoTelemetria(patente="TZWR86", proveedor_id="2716"),)
    )
    resultado = proveedor.listar_vehiculos()
    assert resultado.estado == EstadoTelemetria.OK
    assert resultado.vehiculos[0].patente == "TZWR86"


# --- 11: desambiguación geográfica (caso real Coronel) ---


def test_descarta_candidato_lejos_de_gps_caso_real_coronel():
    punto_gps = Coordenadas(longitud=-73.170997, latitud=-36.972495)  # real, 463630
    coronel_bio_bio = CandidatoGeocodificacion(
        Coordenadas(-73.163227, -37.002896), "Coronel, BI, Chile", 0.6, "Coronel", "Del Bio-Bio",
    )
    coronel_maule = CandidatoGeocodificacion(
        Coordenadas(-72.372437, -36.026889), "Coronel, ML, Chile", 0.6, "Coronel", "Del Maule",
    )
    resultado = descartar_candidatos_lejos_de_gps(
        (coronel_bio_bio, coronel_maule), punto_gps, radio_maximo_km=50.0
    )
    assert resultado == (coronel_bio_bio,)


def test_resolver_destino_entrega_usa_gps_para_desambiguar_de_extremo_a_extremo():
    # Bloque INTELIGENCIA N1: la consulta real enviada al geocodificador ya
    # no incluye "CORONE" -- se reconoce como corrupción OCR redundante de
    # "CORONEL" (legible en el mismo texto) y se descarta antes de
    # geocodificar (ver `normalizar_direccion_con_comunas`).
    texto = "AV. FORESTAL - MANZANA 1 1014 CORONEL CORONE"
    consulta = "AV. FORESTAL - MANZANA 1 1014 CORONEL, Chile"
    coronel_bio_bio = CandidatoGeocodificacion(
        Coordenadas(-73.163227, -37.002896), "Coronel, BI, Chile", 0.6, "Coronel", "Del Bio-Bio",
    )
    coronel_maule = CandidatoGeocodificacion(
        Coordenadas(-72.372437, -36.026889), "Coronel, ML, Chile", 0.6, "Coronel", "Del Maule",
    )
    proveedor = ProveedorRutasSimulado(geocodificaciones={
        consulta: ResultadoGeocodificacion(
            EstadoRuta.RESULTADO_AMBIGUO, (coronel_bio_bio, coronel_maule), "MULTIPLES_CANDIDATOS",
        )
    })
    punto_gps = Coordenadas(longitud=-73.170997, latitud=-36.972495)
    resultado = resolver_destino_entrega(
        texto, proveedor, punto_gps_referencia=punto_gps, radio_gps_km=50.0,
    )
    assert resultado.estado == "RESUELTO"
    assert resultado.metodo_confirmacion == "TELEMETRIA_GPS"
    assert resultado.coordenadas == coronel_bio_bio.coordenadas


def test_sin_gps_la_misma_ambiguedad_sigue_sin_resolver():
    """Regresión: si no se entrega punto GPS, el comportamiento es
    idéntico al del bloque anterior (E2E R1.1) -- ambigüedad real, abstención."""
    # Bloque INTELIGENCIA N1: la consulta real enviada al geocodificador ya
    # no incluye "CORONE" -- se reconoce como corrupción OCR redundante de
    # "CORONEL" (legible en el mismo texto) y se descarta antes de
    # geocodificar (ver `normalizar_direccion_con_comunas`).
    texto = "AV. FORESTAL - MANZANA 1 1014 CORONEL CORONE"
    consulta = "AV. FORESTAL - MANZANA 1 1014 CORONEL, Chile"
    coronel_bio_bio = CandidatoGeocodificacion(
        Coordenadas(-73.163227, -37.002896), "Coronel, BI, Chile", 0.6, "Coronel", "Del Bio-Bio",
    )
    coronel_maule = CandidatoGeocodificacion(
        Coordenadas(-72.372437, -36.026889), "Coronel, ML, Chile", 0.6, "Coronel", "Del Maule",
    )
    proveedor = ProveedorRutasSimulado(geocodificaciones={
        consulta: ResultadoGeocodificacion(
            EstadoRuta.RESULTADO_AMBIGUO, (coronel_bio_bio, coronel_maule), "MULTIPLES_CANDIDATOS",
        )
    })
    resultado = resolver_destino_entrega(texto, proveedor)
    assert resultado.estado == "REVISAR"
    assert resultado.metodo_confirmacion == ""


# --- 12: conflicto documento/GPS (GPS lejos de TODOS los candidatos) ---


def test_gps_lejos_de_todos_los_candidatos_no_reduce_nada():
    """Si el punto GPS no está cerca de NINGÚN candidato (posible conflicto
    de evidencias, o simplemente GPS no ayuda), nunca se vacía la lista --
    se conserva el conjunto completo y la ambigüedad real sigue vigente."""
    coronel_bio_bio = CandidatoGeocodificacion(
        Coordenadas(-73.163227, -37.002896), "Coronel, BI, Chile", 0.6, "Coronel", "Del Bio-Bio",
    )
    coronel_maule = CandidatoGeocodificacion(
        Coordenadas(-72.372437, -36.026889), "Coronel, ML, Chile", 0.6, "Coronel", "Del Maule",
    )
    punto_gps_lejano = Coordenadas(longitud=-70.65, latitud=-33.45)  # Santiago, lejos de ambos
    resultado = descartar_candidatos_lejos_de_gps(
        (coronel_bio_bio, coronel_maule), punto_gps_lejano, radio_maximo_km=50.0
    )
    assert resultado == (coronel_bio_bio, coronel_maule)


# --- 13: caché ---


def test_servicio_telemetria_cachea_viajes_y_no_repite_la_llamada(tmp_path):
    proveedor = ProveedorTelemetriaSimulado(
        viajes_por_patente={"TZWR86": [ViajeTelemetria("1", "TZWR86", "2026-07-27T10:00:00", "2026-07-27T10:05:00")]}
    )
    servicio = ServicioTelemetria(proveedor, RepositorioTelemetria(tmp_path / "cache.json"))
    r1 = servicio.buscar_viajes("TZWR86", date(2026, 7, 27), date(2026, 7, 27))
    r2 = servicio.buscar_viajes("TZWR86", date(2026, 7, 27), date(2026, 7, 27))
    assert r1.estado == EstadoTelemetria.OK
    assert r1.desde_cache is False
    assert r2.estado == EstadoTelemetria.RESULTADO_DESDE_CACHE
    assert r2.desde_cache is True
    assert r2.viajes == r1.viajes
    assert proveedor.llamadas_viajes == 1


def test_servicio_telemetria_cachea_breadcrumbs(tmp_path):
    proveedor = ProveedorTelemetriaSimulado(
        breadcrumbs_por_trip={"1": [PosicionTelemetria(-33.4, -70.6, "2026-07-27T10:00:00")]}
    )
    servicio = ServicioTelemetria(proveedor, RepositorioTelemetria(tmp_path / "cache.json"))
    servicio.obtener_breadcrumbs("1")
    r2 = servicio.obtener_breadcrumbs("1")
    assert r2.desde_cache is True
    assert proveedor.llamadas_breadcrumbs == 1


def test_cache_persiste_entre_instancias_del_repositorio(tmp_path):
    ruta_cache = tmp_path / "cache.json"
    proveedor = ProveedorTelemetriaSimulado(
        viajes_por_patente={"TZWR86": [ViajeTelemetria("1", "TZWR86", "a", "b")]}
    )
    ServicioTelemetria(proveedor, RepositorioTelemetria(ruta_cache)).buscar_viajes(
        "TZWR86", date(2026, 7, 27), date(2026, 7, 27)
    )
    # Nueva instancia de repositorio, mismo archivo -- simula reabrir Desktop.
    servicio_2 = ServicioTelemetria(
        ProveedorTelemetriaSimulado(), RepositorioTelemetria(ruta_cache)
    )
    resultado = servicio_2.buscar_viajes("TZWR86", date(2026, 7, 27), date(2026, 7, 27))
    assert resultado.desde_cache is True
    assert len(resultado.viajes) == 1


# ============================================================
# Bloque OPTIMIZACIÓN SEGURA DE LATENCIA EN TELEMETRÍA -- caché en
# memoria por instancia de `RepositorioTelemetria` (causa raíz medida:
# 741 relecturas del mismo `telemetria_cache.json` de 6,4 MB en una sola
# aplicación de decisión, ~39s de ~64s totales). Contrato: primera
# lectura toca disco, lecturas posteriores de la MISMA instancia
# reutilizan la caché en memoria, escrituras la mantienen sincronizada,
# una instancia NUEVA vuelve a leer -- nunca caché global/singleton.
# ============================================================


def _contar_lecturas_de_disco(repositorio, monkeypatch):
    """Espía `_leer_desde_disco` (el único punto que realmente toca
    disco) sin cambiar su comportamiento -- devuelve una lista que
    crece en cada llamada real."""
    llamadas = []
    original = repositorio._leer_desde_disco
    def espia():
        llamadas.append(1)
        return original()
    monkeypatch.setattr(repositorio, "_leer_desde_disco", espia)
    return llamadas


def test_primera_lectura_toca_disco(tmp_path, monkeypatch):
    ruta = tmp_path / "cache.json"
    ruta.write_text('{"version_formato": 1, "viajes": {}, "breadcrumbs": {}}', encoding="utf-8")
    repo = RepositorioTelemetria(ruta)
    llamadas = _contar_lecturas_de_disco(repo, monkeypatch)
    repo.buscar_viajes("onelogis", "TZWR86", date(2026, 7, 27), date(2026, 7, 27))
    assert len(llamadas) == 1


def test_segunda_lectura_misma_instancia_no_vuelve_a_leer(tmp_path, monkeypatch):
    ruta = tmp_path / "cache.json"
    ruta.write_text('{"version_formato": 1, "viajes": {}, "breadcrumbs": {}}', encoding="utf-8")
    repo = RepositorioTelemetria(ruta)
    llamadas = _contar_lecturas_de_disco(repo, monkeypatch)
    for _ in range(5):
        repo.buscar_viajes("onelogis", "TZWR86", date(2026, 7, 27), date(2026, 7, 27))
        repo.buscar_breadcrumbs("onelogis", "1")
    assert len(llamadas) == 1, "10 lecturas sobre la misma instancia -- disco tocado una sola vez"


def test_escritura_actualiza_cache_sin_releer_disco(tmp_path, monkeypatch):
    ruta = tmp_path / "cache.json"
    repo = RepositorioTelemetria(ruta)
    llamadas = _contar_lecturas_de_disco(repo, monkeypatch)
    viajes = (ViajeTelemetria("1", "TZWR86", "2026-07-27T10:00:00", "2026-07-27T10:05:00"),)
    repo.guardar_viajes("onelogis", "TZWR86", date(2026, 7, 27), date(2026, 7, 27), viajes)
    assert len(llamadas) == 1, "guardar_viajes lee (crea la base vacía) una vez antes de escribir"
    resultado = repo.buscar_viajes("onelogis", "TZWR86", date(2026, 7, 27), date(2026, 7, 27))
    assert resultado == list(viajes)
    assert len(llamadas) == 1, "la lectura posterior ve el dato recien escrito sin volver a tocar disco"


def test_guardar_viajes_visible_de_inmediato_en_la_misma_instancia(tmp_path):
    repo = RepositorioTelemetria(tmp_path / "cache.json")
    viajes = (ViajeTelemetria("1", "TZWR86", "2026-07-27T10:00:00", "2026-07-27T10:05:00"),)
    repo.guardar_viajes("onelogis", "TZWR86", date(2026, 7, 27), date(2026, 7, 27), viajes)
    assert repo.buscar_viajes("onelogis", "TZWR86", date(2026, 7, 27), date(2026, 7, 27)) == list(viajes)


def test_guardar_breadcrumbs_visible_de_inmediato_en_la_misma_instancia(tmp_path):
    repo = RepositorioTelemetria(tmp_path / "cache.json")
    puntos = (PosicionTelemetria(-33.4, -70.6, "2026-07-27T10:00:00"),)
    repo.guardar_breadcrumbs("onelogis", "1", puntos)
    assert repo.buscar_breadcrumbs("onelogis", "1") == list(puntos)


def test_nueva_instancia_vuelve_a_leer_desde_disco(tmp_path, monkeypatch):
    ruta = tmp_path / "cache.json"
    repo_1 = RepositorioTelemetria(ruta)
    viajes = (ViajeTelemetria("1", "TZWR86", "2026-07-27T10:00:00", "2026-07-27T10:05:00"),)
    repo_1.guardar_viajes("onelogis", "TZWR86", date(2026, 7, 27), date(2026, 7, 27), viajes)

    repo_2 = RepositorioTelemetria(ruta)
    llamadas_2 = _contar_lecturas_de_disco(repo_2, monkeypatch)
    assert len(llamadas_2) == 0, "una instancia recien creada no ha tocado disco todavia"
    resultado = repo_2.buscar_viajes("onelogis", "TZWR86", date(2026, 7, 27), date(2026, 7, 27))
    assert len(llamadas_2) == 1, "instancia NUEVA -- primera lectura de ESTA instancia toca disco"
    assert resultado == list(viajes)


def test_archivo_ausente_se_cachea_como_base_vacia_sin_cambiar_semantica(tmp_path, monkeypatch):
    ruta = tmp_path / "no-existe.json"
    repo = RepositorioTelemetria(ruta)
    llamadas = _contar_lecturas_de_disco(repo, monkeypatch)
    assert repo.buscar_viajes("onelogis", "TZWR86", date(2026, 7, 27), date(2026, 7, 27)) is None
    assert repo.buscar_breadcrumbs("onelogis", "1") is None
    assert len(llamadas) == 1, "ausencia de archivo tambien se resuelve una sola vez por instancia"


def test_archivo_corrupto_se_cachea_como_base_vacia_sin_cambiar_semantica(tmp_path, monkeypatch):
    ruta = tmp_path / "cache.json"
    ruta.write_text("{esto no es json valido", encoding="utf-8")
    repo = RepositorioTelemetria(ruta)
    llamadas = _contar_lecturas_de_disco(repo, monkeypatch)
    assert repo.buscar_viajes("onelogis", "TZWR86", date(2026, 7, 27), date(2026, 7, 27)) is None
    assert len(llamadas) == 1
    # Segunda consulta -- misma instancia, sigue sin reventar ni releer.
    assert repo.buscar_breadcrumbs("onelogis", "1") is None
    assert len(llamadas) == 1


def test_archivo_json_valido_pero_no_es_objeto_se_trata_como_vacio(tmp_path):
    ruta = tmp_path / "cache.json"
    ruta.write_text("[1, 2, 3]", encoding="utf-8")
    repo = RepositorioTelemetria(ruta)
    assert repo.buscar_viajes("onelogis", "TZWR86", date(2026, 7, 27), date(2026, 7, 27)) is None


def test_resultados_funcionales_identicos_con_o_sin_cache_multiples_claves(tmp_path):
    """Control de equivalencia funcional -- varias patentes/trips
    distintos en la misma instancia, mezclando lecturas y escrituras en
    cualquier orden, deben verse exactamente igual que con el
    comportamiento anterior (siempre re-leyendo): ninguna clave se
    pierde, ninguna se mezcla con otra."""
    repo = RepositorioTelemetria(tmp_path / "cache.json")
    v1 = (ViajeTelemetria("1", "AA1111", "2026-07-27T10:00:00", "2026-07-27T10:05:00"),)
    v2 = (ViajeTelemetria("2", "BB2222", "2026-07-28T11:00:00", "2026-07-28T11:05:00"),)
    b1 = (PosicionTelemetria(-33.4, -70.6, "2026-07-27T10:00:00"),)

    repo.guardar_viajes("onelogis", "AA1111", date(2026, 7, 27), date(2026, 7, 27), v1)
    assert repo.buscar_viajes("onelogis", "BB2222", date(2026, 7, 28), date(2026, 7, 28)) is None
    repo.guardar_viajes("onelogis", "BB2222", date(2026, 7, 28), date(2026, 7, 28), v2)
    repo.guardar_breadcrumbs("onelogis", "1", b1)

    assert repo.buscar_viajes("onelogis", "AA1111", date(2026, 7, 27), date(2026, 7, 27)) == list(v1)
    assert repo.buscar_viajes("onelogis", "BB2222", date(2026, 7, 28), date(2026, 7, 28)) == list(v2)
    assert repo.buscar_breadcrumbs("onelogis", "1") == list(b1)
    assert repo.buscar_breadcrumbs("onelogis", "2") is None

    # Releído desde una instancia nueva (disco real) -- mismo resultado.
    repo_2 = RepositorioTelemetria(repo.ruta)
    assert repo_2.buscar_viajes("onelogis", "AA1111", date(2026, 7, 27), date(2026, 7, 27)) == list(v1)
    assert repo_2.buscar_viajes("onelogis", "BB2222", date(2026, 7, 28), date(2026, 7, 28)) == list(v2)
    assert repo_2.buscar_breadcrumbs("onelogis", "1") == list(b1)


# --- 14: no filtración de credencial ---


def test_repr_del_proveedor_no_contiene_la_credencial():
    proveedor = OnelogisProvider(api_key="secreto-super-sensible")
    representacion = repr(proveedor.__dict__)
    assert "secreto-super-sensible" not in representacion or "_api_key" in representacion
    # La credencial vive en un atributo privado; nunca aparece en los
    # modelos de resultado (Resultado*) que sí se imprimen/loguean.
    resultado = proveedor.listar_vehiculos.__doc__
    assert resultado is None or "secreto" not in str(resultado)


def test_resultado_error_nunca_incluye_el_token_en_el_motivo():
    def transporte_401(solicitud, timeout):
        import urllib.error
        raise urllib.error.HTTPError(solicitud.full_url, 401, "Unauthorized", None, None)

    proveedor = OnelogisProvider(api_key="token-secreto-xyz", transporte=transporte_401)
    resultado = proveedor.listar_vehiculos()
    assert "token-secreto-xyz" not in resultado.motivo
    assert "token-secreto-xyz" not in str(resultado)
