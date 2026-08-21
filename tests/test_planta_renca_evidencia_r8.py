"""Bloque R8 -- evidencia operacional real de AZA RENCA (Javier, OneLogis)
incorporada al mecanismo YA existente de plantas/geocercas/histórico
(Bloque PLANTAS P3/TELEMETRÍA T3/ORIGEN D1/R7) -- nunca una memoria
paralela. Demuestra, con datos GPS reales (`fixtures_telemetria_renca_r8`,
extraídos tal cual de `cache/telemetria/telemetria_cache.json` real):

CASO 1 -- patrón conocido de RENCA: Atlas identifica/favorece AZA RENCA
usando permanencia real (múltiples puntos, detenido/apagado/encendido),
nunca un solo ping.
CASO 2 -- patrón NO compatible con RENCA (mismo vehículo, zona de AZA
COLINA): Atlas identifica AZA COLINA, nunca fuerza RENCA.
CASO 3 -- caso real ambiguo (472037, conflicto real RENCA/COLINA):
B1 recibe evidencia estructurada (nunca una lista cruda de GPS) y
propone/se abstiene con motivo trazable, sin autoaplicar."""
from __future__ import annotations

from datetime import date, datetime

from atlas_core.catalogo_plantas import CatalogoPlantas, EstadoCalidad
from atlas_core.rutas.geocerca import RADIO_GEOCERCA_KM_PREDETERMINADO
from atlas_core.telemetria.modelos import PosicionTelemetria, ViajeTelemetria
from atlas_core.telemetria.proveedor import ProveedorTelemetriaSoloCache
from atlas_core.telemetria.repositorio import RepositorioTelemetria
from atlas_core.telemetria.servicio import ServicioTelemetria
from atlas_core.telemetria.seleccion_recorrido import (
    ORIGEN_GPS_CONFIRMADO,
    resolver_planta_origen_gps,
)

from tests.fixtures_telemetria_renca_r8 import (
    BREADCRUMBS_30539854_ZONA_COLINA,
    BREADCRUMBS_30539854_ZONA_RENCA,
    BREADCRUMBS_30540537,
    BREADCRUMBS_30542187,
    VIAJES_SB6486_20260806,
)

# Coordenadas reales ya confirmadas en catalogos_privados/plantas.json
# (producción) -- nunca fabricadas.
COORD_AZA_RENCA = (-33.401595, -70.685226)
COORD_AZA_COLINA = (-33.294885, -70.729)  # centroide real del polígono ya confirmado


def _plantas(tmp_path):
    catalogo = CatalogoPlantas(tmp_path / "plantas.json")
    renca = catalogo.crear(
        nombre="AZA RENCA", pais="CHILE", fuente="TEST", direccion="LA UNION 3070",
        comuna="RENCA", region="RM", latitud=COORD_AZA_RENCA[0], longitud=COORD_AZA_RENCA[1],
        estado_calidad=EstadoCalidad.CONFIRMADA,
    )
    colina = catalogo.crear(
        nombre="AZA COLINA", pais="CHILE", fuente="TEST", latitud=COORD_AZA_COLINA[0],
        longitud=COORD_AZA_COLINA[1], estado_calidad=EstadoCalidad.CONFIRMADA,
    )
    return [renca, colina]


def _servicio(tmp_path, *, breadcrumbs_por_trip: dict[str, list[dict]]):
    repo = RepositorioTelemetria(tmp_path / "telemetria_cache.json")
    repo.guardar_viajes(
        "onelogis", "SB6486", date(2026, 8, 6), date(2026, 8, 6),
        tuple(ViajeTelemetria(**v) for v in VIAJES_SB6486_20260806),
    )
    for trip_id, puntos in breadcrumbs_por_trip.items():
        repo.guardar_breadcrumbs(
            "onelogis", trip_id, tuple(PosicionTelemetria(**p) for p in puntos),
        )
    return ServicioTelemetria(ProveedorTelemetriaSoloCache(nombre="onelogis"), repo)


# ============================================================
# CASO 1 -- patrón real de RENCA: permanencia larga y real gana
# ============================================================


def test_caso_1_patron_real_de_renca_es_identificado_por_permanencia(tmp_path):
    plantas = _plantas(tmp_path)
    servicio = _servicio(tmp_path, breadcrumbs_por_trip={
        "30539854": BREADCRUMBS_30539854_ZONA_COLINA + BREADCRUMBS_30539854_ZONA_RENCA,
        "30540537": BREADCRUMBS_30540537,
        "30542187": BREADCRUMBS_30542187,
    })
    # Ventana documental centrada en la permanencia real de RENCA -- igual
    # que cualquier guía real, el margen de 4h (MARGEN_HORAS_PLANTA_
    # PREDETERMINADO) también alcanza a cubrir el paso breve por COLINA
    # (09:59-10:14): la permanencia REAL y prolongada en RENCA (~10:26-
    # 12:22, con 2 ciclos ENGINE_OFF/ON reales) debe pesar más que ese
    # paso corto -- nunca un ping aislado decidiendo.
    resultado = resolver_planta_origen_gps(
        servicio, patente="SB6486", fecha=date(2026, 8, 6),
        hora_entrada=datetime(2026, 8, 6, 10, 30), hora_salida=datetime(2026, 8, 6, 12, 15),
        plantas=plantas,
    )
    assert resultado.estado == ORIGEN_GPS_CONFIRMADO
    assert resultado.planta_nombre == "AZA RENCA"


def test_caso_1_geocerca_por_defecto_cubre_el_punto_real_de_renca():
    """El radio circular por defecto (1.5 km) ya cubre, sin ningún cambio
    de código, el punto real donde el vehículo permaneció (~0.29 km del
    punto documental de AZA RENCA) -- confirma que no hace falta ampliar
    ni tocar el radio para esta evidencia."""
    from atlas_core.rutas.geocerca import distancia_km_haversine
    from atlas_core.rutas.modelos import Coordenadas

    from tests.fixtures_telemetria_renca_r8 import PUNTO_RUTEO_RENCA_REAL

    distancia = distancia_km_haversine(
        Coordenadas(PUNTO_RUTEO_RENCA_REAL[1], PUNTO_RUTEO_RENCA_REAL[0]),
        Coordenadas(COORD_AZA_RENCA[1], COORD_AZA_RENCA[0]),
    )
    assert distancia < RADIO_GEOCERCA_KM_PREDETERMINADO


# ============================================================
# CASO 2 -- patrón NO compatible con RENCA: nunca se fuerza
# ============================================================


def test_caso_2_patron_de_colina_no_fuerza_renca(tmp_path):
    plantas = _plantas(tmp_path)
    # Sólo el tramo real de COLINA -- ninguna evidencia de RENCA ese día
    # para este vehículo.
    repo = RepositorioTelemetria(tmp_path / "telemetria_cache.json")
    repo.guardar_viajes(
        "onelogis", "SB6486", date(2026, 8, 6), date(2026, 8, 6),
        (ViajeTelemetria("30539854", "SB6486", "2026-08-06 09:59:42", "2026-08-06 10:14:30", 0.5),),
    )
    repo.guardar_breadcrumbs(
        "onelogis", "30539854",
        tuple(PosicionTelemetria(**p) for p in BREADCRUMBS_30539854_ZONA_COLINA),
    )
    servicio = ServicioTelemetria(ProveedorTelemetriaSoloCache(nombre="onelogis"), repo)
    resultado = resolver_planta_origen_gps(
        servicio, patente="SB6486", fecha=date(2026, 8, 6),
        hora_entrada=datetime(2026, 8, 6, 10, 0), hora_salida=datetime(2026, 8, 6, 10, 14),
        plantas=plantas,
    )
    assert resultado.estado == ORIGEN_GPS_CONFIRMADO
    assert resultado.planta_nombre == "AZA COLINA"  # nunca RENCA sin evidencia


def test_caso_2_sin_ninguna_evidencia_cerca_de_ninguna_planta_no_determina_nada(tmp_path):
    plantas = _plantas(tmp_path)
    repo = RepositorioTelemetria(tmp_path / "telemetria_cache.json")
    repo.guardar_viajes(
        "onelogis", "XY9999", date(2026, 8, 6), date(2026, 8, 6),
        (ViajeTelemetria("t-lejos", "XY9999", "2026-08-06 09:00:00", "2026-08-06 09:10:00", 5.0),),
    )
    repo.guardar_breadcrumbs(
        "onelogis", "t-lejos",
        (PosicionTelemetria(latitud=-38.0, longitud=-72.5, timestamp="2026-08-06 09:05:00", velocidad=0.0, evento="PERIODIC_ON"),),
    )
    servicio = ServicioTelemetria(ProveedorTelemetriaSoloCache(nombre="onelogis"), repo)
    resultado = resolver_planta_origen_gps(
        servicio, patente="XY9999", fecha=date(2026, 8, 6),
        hora_entrada=datetime(2026, 8, 6, 9, 0), hora_salida=datetime(2026, 8, 6, 9, 10),
        plantas=plantas,
    )
    assert resultado.planta_nombre == ""  # nunca inventa ninguna planta


# ============================================================
# CASO 3 -- ambiguo real (472037): B1 recibe evidencia estructurada,
# propone o se abstiene, nunca autoaplica
# ============================================================


def test_caso_3_ambiguo_real_472037_b1_recibe_evidencia_estructurada_y_no_autoaplica(tmp_path):
    from atlas_core.atlas_ia.orquestador import OrquestadorAtlasIA
    from atlas_core.atlas_ia.proveedor import ProveedorModeloIASimulado, RespuestaSimulada
    from atlas_core.atlas_ia.contratos import RESULTADO_HIPOTESIS_ABSTENCION
    from atlas_core.procesamiento_masivo import COLUMNAS, _ejecutar_ia_operacional
    import csv

    catalogos = tmp_path / "catalogos"; catalogos.mkdir()
    CatalogoPlantas(catalogos / "plantas.json").crear(
        nombre="AZA RENCA", pais="CHILE", fuente="TEST", latitud=COORD_AZA_RENCA[0],
        longitud=COORD_AZA_RENCA[1], estado_calidad=EstadoCalidad.CONFIRMADA,
    )
    CatalogoPlantas(catalogos / "plantas.json").crear(
        nombre="AZA COLINA", pais="CHILE", fuente="TEST", latitud=COORD_AZA_COLINA[0],
        longitud=COORD_AZA_COLINA[1], estado_calidad=EstadoCalidad.CONFIRMADA,
    )

    fila = {c: "" for c in COLUMNAS}
    fila.update({
        "archivo": "472037.jpeg", "numero_guia": "472037", "numero_transporte": "0000354034",
        "estado_ruta": "ORIGEN_NO_DETERMINADO", "planta_origen_id": "",
        # Motivo real, persistido en producción para esta guía real (Bloque R5).
        "motivo_origen_gps": "CONFLICTO_REAL_EN_VENTANA(AZA_RENCA:score=0.104,solape=0.0%;AZA_COLINA:score=0.0559,solape=0.0%)",
    })
    ruta_csv = tmp_path / "datos.csv"
    with ruta_csv.open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader(); escritor.writerows([fila])

    proveedor = ProveedorModeloIASimulado(respuestas_por_valor_documental={
        "": RespuestaSimulada(resultado=RESULTADO_HIPOTESIS_ABSTENCION),
    })
    resumen = _ejecutar_ia_operacional(
        ruta_csv, {"472037.jpeg"}, OrquestadorAtlasIA(proveedor=proveedor), catalogos,
    )
    assert resumen["llamadas"] == 1
    assert resumen["C"] == 1  # abstención -- evidencia real, pero insuficiente para elegir

    # La evidencia que llegó al proveedor es estructurada (planta
    # candidata + score/solape resumidos), nunca una lista cruda de GPS.
    contexto_recibido = proveedor.contextos_recibidos[0]
    assert contexto_recibido.campo == "planta_origen"
    assert len(contexto_recibido.evidencias) == 2
    nombres = {e.identificador for e in contexto_recibido.evidencias}
    assert len(nombres) == 2  # una por planta_id candidata, no un dump de puntos
    for evidencia in contexto_recibido.evidencias:
        assert "score=" in evidencia.referencias_fuente[1]

    with ruta_csv.open(encoding="utf-8-sig", newline="") as archivo:
        salida = list(csv.DictReader(archivo, delimiter=";"))[0]
    assert salida["planta_origen_id"] == ""  # nunca se autoaplica
