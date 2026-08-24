"""Bloque FINAL CORE V1 -- cierre de los 3 históricos residuales sin
ruta (460807/472008 -- familia AUSIN SAN BERNARDO; 464981 -- origen sin
GPS en su propia ventana). Nunca reinvestiga identidad ya conocida --
sólo reutiliza evidencia operacional ya persistida (GPS histórico
cacheado, vecinos temporales del mismo vehículo)."""
from __future__ import annotations

import csv
from datetime import date

from atlas_core.catalogo_plantas import CatalogoPlantas, EstadoCalidad
from atlas_core.catalogo_destinos import CatalogoDestinos, EstadoCalidadDestino
from atlas_core.procesamiento_masivo import COLUMNAS
from atlas_core.revalidacion_documental import (
    revalidar_origen_por_vecinos_temporales_gps_sin_ocr,
    revalidar_ruta_por_convergencia_gps_historica_sin_ocr,
)
from atlas_core.rutas.modelos import (
    CandidatoGeocodificacion, Coordenadas, EstadoRuta, ResultadoGeocodificacion, ResultadoRuta,
)
from atlas_core.rutas.proveedor import ProveedorRutasSimulado
from atlas_core.telemetria.modelos import PosicionTelemetria, ViajeTelemetria
from atlas_core.telemetria.proveedor import ProveedorTelemetriaSoloCache
from atlas_core.telemetria.repositorio import RepositorioTelemetria
from atlas_core.telemetria.servicio import ServicioTelemetria

COORD_AZA_COLINA = Coordenadas(-70.665977, -33.137558)
COORD_AZA_RENCA = Coordenadas(-70.685226, -33.401595)
COORD_AUSIN = Coordenadas(-70.704833, -33.543683)
COORD_LEJOS = Coordenadas(-70.5, -33.0)  # a más de MARGEN_MISMO_LUGAR_KM de COORD_AUSIN


def _fila_csv(**overrides):
    fila = {c: "" for c in COLUMNAS}
    fila.update({
        "archivo": "1.jpeg", "estado_procesamiento": "OK", "numero_guia": "1",
        "numero_transporte": "T1", "fecha": "18-08-2026",
        "cliente": "CLIENTE PRUEBA", "obra_destino": "AUSIN SAN BERNARDO",
        "despachar_a_crudo": "INTERIOR NUEVA O1148 SAN BERNARDO",
        "patente_tracto": "AL1879", "patente_rampla": "No encontrado",
        "hora_entrada_aza": "11:00", "hora_salida_aza": "12:00",
        "planta_origen_id": "", "planta_origen_nombre": "", "origen_determinado_por": "",
        "estado_ruta": "REQUIERE_REVISION", "motivo_ruta": "COORDENADA_NO_CONFIRMADA(3)",
        "distancia_km": "", "duracion_min": "", "indicador_revision": "OK",
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


def _catalogos(tmp_path):
    carpeta = tmp_path / "catalogos"
    carpeta.mkdir()
    plantas = CatalogoPlantas(carpeta / "plantas.json")
    planta_colina = plantas.crear(
        nombre="AZA COLINA", pais="CHILE", fuente="TEST",
        direccion="RUTA 5", comuna="COLINA", region="RM",
        latitud=COORD_AZA_COLINA.latitud, longitud=COORD_AZA_COLINA.longitud,
        estado_calidad=EstadoCalidad.CONFIRMADA,
    )
    planta_renca = plantas.crear(
        nombre="AZA RENCA", pais="CHILE", fuente="TEST",
        direccion="LA UNION 3070", comuna="RENCA", region="RM",
        latitud=COORD_AZA_RENCA.latitud, longitud=COORD_AZA_RENCA.longitud,
        estado_calidad=EstadoCalidad.CONFIRMADA,
    )
    return carpeta, planta_colina, planta_renca


# ========================================================================
# Bloque F -- revalidar_origen_por_vecinos_temporales_gps_sin_ocr
# (caso real 464981)
# ========================================================================

def test_caso_real_464981_tres_vecinos_gps_convergen_en_una_planta(tmp_path):
    carpeta, planta_colina, _ = _catalogos(tmp_path)
    dataset = tmp_path / "dataset.csv"
    _escribir_csv(dataset, [
        _fila_csv(
            numero_guia="464981", fecha="17-08-2026", patente_tracto="DD2494",
            planta_origen_id="", planta_origen_nombre="", origen_determinado_por="",
        ),
        _fila_csv(
            numero_guia="472018", fecha="18-08-2026", patente_tracto="DD2494",
            planta_origen_id=planta_colina.planta_id, planta_origen_nombre="AZA COLINA",
            origen_determinado_por="TELEMETRIA_GPS",
        ),
        _fila_csv(
            numero_guia="472099", fecha="19-08-2026", patente_tracto="DD2494",
            planta_origen_id=planta_colina.planta_id, planta_origen_nombre="AZA COLINA",
            origen_determinado_por="TELEMETRIA_GPS",
        ),
        _fila_csv(
            numero_guia="472162", fecha="19-08-2026", patente_tracto="DD2494",
            planta_origen_id=planta_colina.planta_id, planta_origen_nombre="AZA COLINA",
            origen_determinado_por="TELEMETRIA_GPS",
        ),
    ])
    resultado = revalidar_origen_por_vecinos_temporales_gps_sin_ocr(ruta_dataset=dataset)
    assert resultado["guias_actualizadas"] == ["464981"]
    fila = next(f for f in _leer_csv(dataset) if f["numero_guia"] == "464981")
    assert fila["planta_origen_id"] == planta_colina.planta_id
    assert fila["planta_origen_nombre"] == "AZA COLINA"
    assert fila["origen_determinado_por"] == "PATRON_VEHICULO_GPS_VECINOS"
    assert "472018" in fila["evidencia_origen"]


def test_una_sola_observacion_gps_no_basta(tmp_path):
    """Regresión F -- "una sola observación GPS aislada no basta"."""
    carpeta, planta_colina, _ = _catalogos(tmp_path)
    dataset = tmp_path / "dataset.csv"
    _escribir_csv(dataset, [
        _fila_csv(numero_guia="464981", fecha="17-08-2026", patente_tracto="DD2494"),
        _fila_csv(
            numero_guia="472018", fecha="18-08-2026", patente_tracto="DD2494",
            planta_origen_id=planta_colina.planta_id, planta_origen_nombre="AZA COLINA",
            origen_determinado_por="TELEMETRIA_GPS",
        ),
    ])
    resultado = revalidar_origen_por_vecinos_temporales_gps_sin_ocr(ruta_dataset=dataset)
    assert resultado["guias_actualizadas"] == []
    fila = next(f for f in _leer_csv(dataset) if f["numero_guia"] == "464981")
    assert fila["planta_origen_id"] == ""


def test_dos_plantas_plausibles_se_abstiene(tmp_path):
    """Regresión F -- "si hay dos plantas plausibles: abstenerse"."""
    carpeta, planta_colina, planta_renca = _catalogos(tmp_path)
    dataset = tmp_path / "dataset.csv"
    _escribir_csv(dataset, [
        _fila_csv(numero_guia="464981", fecha="17-08-2026", patente_tracto="DD2494"),
        _fila_csv(
            numero_guia="472018", fecha="18-08-2026", patente_tracto="DD2494",
            planta_origen_id=planta_colina.planta_id, planta_origen_nombre="AZA COLINA",
            origen_determinado_por="TELEMETRIA_GPS",
        ),
        _fila_csv(
            numero_guia="472099", fecha="19-08-2026", patente_tracto="DD2494",
            planta_origen_id=planta_renca.planta_id, planta_origen_nombre="AZA RENCA",
            origen_determinado_por="TELEMETRIA_GPS",
        ),
    ])
    resultado = revalidar_origen_por_vecinos_temporales_gps_sin_ocr(ruta_dataset=dataset)
    assert resultado["guias_actualizadas"] == []


def test_vecino_documental_no_gps_no_cuenta_como_evidencia(tmp_path):
    """Un origen `origen_determinado_por=DOCUMENTO` es, por diseño del
    resto del sistema, menos confiable que uno GPS-confirmado -- nunca
    cuenta como vecino convergente."""
    carpeta, planta_colina, planta_renca = _catalogos(tmp_path)
    dataset = tmp_path / "dataset.csv"
    _escribir_csv(dataset, [
        _fila_csv(numero_guia="464981", fecha="17-08-2026", patente_tracto="DD2494"),
        _fila_csv(
            numero_guia="472018", fecha="18-08-2026", patente_tracto="DD2494",
            planta_origen_id=planta_colina.planta_id, planta_origen_nombre="AZA COLINA",
            origen_determinado_por="TELEMETRIA_GPS",
        ),
        _fila_csv(
            numero_guia="472223", fecha="19-08-2026", patente_tracto="DD2494",
            planta_origen_id=planta_renca.planta_id, planta_origen_nombre="AZA RENCA",
            origen_determinado_por="DOCUMENTO",
        ),
    ])
    resultado = revalidar_origen_por_vecinos_temporales_gps_sin_ocr(ruta_dataset=dataset)
    # Sólo un vecino GPS-confirmado real (472018) -- sigue sin bastar.
    assert resultado["guias_actualizadas"] == []


def test_vecino_fuera_de_la_ventana_temporal_no_cuenta(tmp_path):
    carpeta, planta_colina, _ = _catalogos(tmp_path)
    dataset = tmp_path / "dataset.csv"
    _escribir_csv(dataset, [
        _fila_csv(numero_guia="464981", fecha="17-08-2026", patente_tracto="DD2494"),
        _fila_csv(
            numero_guia="A", fecha="01-08-2026", patente_tracto="DD2494",
            planta_origen_id=planta_colina.planta_id, planta_origen_nombre="AZA COLINA",
            origen_determinado_por="TELEMETRIA_GPS",
        ),
        _fila_csv(
            numero_guia="B", fecha="02-08-2026", patente_tracto="DD2494",
            planta_origen_id=planta_colina.planta_id, planta_origen_nombre="AZA COLINA",
            origen_determinado_por="TELEMETRIA_GPS",
        ),
    ])
    resultado = revalidar_origen_por_vecinos_temporales_gps_sin_ocr(ruta_dataset=dataset)
    assert resultado["guias_actualizadas"] == []


def test_fila_con_planta_ya_resuelta_nunca_se_reinvestiga(tmp_path):
    carpeta, planta_colina, planta_renca = _catalogos(tmp_path)
    dataset = tmp_path / "dataset.csv"
    _escribir_csv(dataset, [
        _fila_csv(
            numero_guia="464981", fecha="17-08-2026", patente_tracto="DD2494",
            planta_origen_id=planta_renca.planta_id, planta_origen_nombre="AZA RENCA",
            origen_determinado_por="CONFIRMACION_HUMANA",
        ),
        _fila_csv(
            numero_guia="472018", fecha="18-08-2026", patente_tracto="DD2494",
            planta_origen_id=planta_colina.planta_id, planta_origen_nombre="AZA COLINA",
            origen_determinado_por="TELEMETRIA_GPS",
        ),
        _fila_csv(
            numero_guia="472099", fecha="19-08-2026", patente_tracto="DD2494",
            planta_origen_id=planta_colina.planta_id, planta_origen_nombre="AZA COLINA",
            origen_determinado_por="TELEMETRIA_GPS",
        ),
    ])
    resultado = revalidar_origen_por_vecinos_temporales_gps_sin_ocr(ruta_dataset=dataset)
    assert resultado["guias_actualizadas"] == []
    fila = next(f for f in _leer_csv(dataset) if f["numero_guia"] == "464981")
    assert fila["planta_origen_nombre"] == "AZA RENCA"


# ========================================================================
# Bloque C -- revalidar_ruta_por_convergencia_gps_historica_sin_ocr
# (caso real 460807/472008 -- AUSIN SAN BERNARDO)
# ========================================================================

def _cachear_trip_con_destino(repositorio, *, patente, fecha_iso, fecha_doc, punto_destino):
    # Bloque TELEMETRÍA T2: el trip "sustancial" debe EMPEZAR cerca de la
    # hora de salida documental (ancla) -- representa al camión saliendo
    # de la planta hacia el destino, nunca antes. La fila de prueba usa
    # hora_entrada_aza="11:00"/hora_salida_aza="12:00" (ver _fila_csv).
    repositorio.guardar_viajes(
        "onelogis", patente, fecha_iso, fecha_iso,
        (ViajeTelemetria("t-" + patente + fecha_doc, patente, f"{fecha_doc} 12:05:00", f"{fecha_doc} 13:30:00", 15.0),),
    )
    repositorio.guardar_breadcrumbs(
        "onelogis", "t-" + patente + fecha_doc,
        (
            PosicionTelemetria(-33.40, -70.68, f"{fecha_doc} 12:10:00"),
            PosicionTelemetria(punto_destino.latitud, punto_destino.longitud, f"{fecha_doc} 13:25:00"),
        ),
    )


def test_caso_real_ausin_dos_entregas_convergen_y_resuelven_ruta(tmp_path):
    carpeta, planta_colina, planta_renca = _catalogos(tmp_path)
    dataset = tmp_path / "dataset.csv"
    _escribir_csv(dataset, [
        _fila_csv(
            numero_guia="460807", fecha="18-08-2026", patente_tracto="AL1879",
            hora_entrada_aza="11:00", hora_salida_aza="12:00",
            planta_origen_id=planta_renca.planta_id, planta_origen_nombre="AZA RENCA",
        ),
        _fila_csv(
            numero_guia="472008", fecha="19-08-2026", patente_tracto="AL1879",
            hora_entrada_aza="07:00", hora_salida_aza="09:00",
            planta_origen_id=planta_colina.planta_id, planta_origen_nombre="AZA COLINA",
        ),
    ])
    repo = RepositorioTelemetria(carpeta / "telemetria_cache.json")
    _cachear_trip_con_destino(repo, patente="AL1879", fecha_iso=date(2026, 8, 18), fecha_doc="2026-08-18", punto_destino=COORD_AUSIN)
    _cachear_trip_con_destino(repo, patente="AL1879", fecha_iso=date(2026, 8, 19), fecha_doc="2026-08-19", punto_destino=COORD_AUSIN)
    servicio = ServicioTelemetria(ProveedorTelemetriaSoloCache(nombre="onelogis"), repo)

    proveedor = ProveedorRutasSimulado(resultado_ruta=ResultadoRuta(EstadoRuta.RUTA_CALCULADA, 20.0, 30.0, "SINTETICO"))
    resultado = revalidar_ruta_por_convergencia_gps_historica_sin_ocr(
        ruta_dataset=dataset, carpeta_catalogos=carpeta, proveedor_rutas=proveedor,
        servicio_telemetria=servicio,
    )
    assert set(resultado["guias_actualizadas"]) == {"460807", "472008"}
    filas = {f["numero_guia"]: f for f in _leer_csv(dataset)}
    assert filas["460807"]["estado_ruta"] == "RUTA_CALCULADA"
    assert filas["460807"]["distancia_km"] == "20.0"
    assert filas["472008"]["estado_ruta"] == "RUTA_CALCULADA"
    # Nunca reemplaza el texto documental con un marcador sintético.
    assert filas["460807"]["direccion_entrega"] == "INTERIOR NUEVA O1148 SAN BERNARDO"


def test_una_sola_entrega_gps_no_basta_para_convergencia(tmp_path):
    carpeta, planta_colina, planta_renca = _catalogos(tmp_path)
    dataset = tmp_path / "dataset.csv"
    _escribir_csv(dataset, [
        _fila_csv(
            numero_guia="460807", fecha="18-08-2026", patente_tracto="AL1879",
            planta_origen_id=planta_renca.planta_id, planta_origen_nombre="AZA RENCA",
        ),
        _fila_csv(
            numero_guia="472008", fecha="19-08-2026", patente_tracto="AL1879",
            planta_origen_id=planta_colina.planta_id, planta_origen_nombre="AZA COLINA",
        ),
    ])
    repo = RepositorioTelemetria(carpeta / "telemetria_cache.json")
    _cachear_trip_con_destino(repo, patente="AL1879", fecha_iso=date(2026, 8, 18), fecha_doc="2026-08-18", punto_destino=COORD_AUSIN)
    # 472008 nunca queda cacheado -- sólo una observación GPS real.
    servicio = ServicioTelemetria(ProveedorTelemetriaSoloCache(nombre="onelogis"), repo)

    proveedor = ProveedorRutasSimulado(resultado_ruta=ResultadoRuta(EstadoRuta.RUTA_CALCULADA, 20.0, 30.0, "SINTETICO"))
    resultado = revalidar_ruta_por_convergencia_gps_historica_sin_ocr(
        ruta_dataset=dataset, carpeta_catalogos=carpeta, proveedor_rutas=proveedor,
        servicio_telemetria=servicio,
    )
    assert resultado["guias_actualizadas"] == []


def test_puntos_gps_no_convergentes_se_abstiene(tmp_path):
    """Regresión -- dos entregas del mismo cliente/obra pero en puntos
    lejanos entre sí (>1 km) no son "la misma zona" -- se abstiene en
    vez de promediar puntos genuinamente distintos."""
    carpeta, planta_colina, planta_renca = _catalogos(tmp_path)
    dataset = tmp_path / "dataset.csv"
    _escribir_csv(dataset, [
        _fila_csv(
            numero_guia="460807", fecha="18-08-2026", patente_tracto="AL1879",
            planta_origen_id=planta_renca.planta_id, planta_origen_nombre="AZA RENCA",
        ),
        _fila_csv(
            numero_guia="472008", fecha="19-08-2026", patente_tracto="AL1879",
            planta_origen_id=planta_colina.planta_id, planta_origen_nombre="AZA COLINA",
        ),
    ])
    repo = RepositorioTelemetria(carpeta / "telemetria_cache.json")
    _cachear_trip_con_destino(repo, patente="AL1879", fecha_iso=date(2026, 8, 18), fecha_doc="2026-08-18", punto_destino=COORD_AUSIN)
    _cachear_trip_con_destino(repo, patente="AL1879", fecha_iso=date(2026, 8, 19), fecha_doc="2026-08-19", punto_destino=COORD_LEJOS)
    servicio = ServicioTelemetria(ProveedorTelemetriaSoloCache(nombre="onelogis"), repo)

    proveedor = ProveedorRutasSimulado(resultado_ruta=ResultadoRuta(EstadoRuta.RUTA_CALCULADA, 20.0, 30.0, "SINTETICO"))
    resultado = revalidar_ruta_por_convergencia_gps_historica_sin_ocr(
        ruta_dataset=dataset, carpeta_catalogos=carpeta, proveedor_rutas=proveedor,
        servicio_telemetria=servicio,
    )
    assert resultado["guias_actualizadas"] == []


def test_fila_ya_ruta_calculada_nunca_se_toca(tmp_path):
    carpeta, planta_colina, planta_renca = _catalogos(tmp_path)
    dataset = tmp_path / "dataset.csv"
    _escribir_csv(dataset, [
        _fila_csv(
            numero_guia="460807", fecha="18-08-2026", patente_tracto="AL1879",
            planta_origen_id=planta_renca.planta_id, planta_origen_nombre="AZA RENCA",
            estado_ruta="RUTA_CALCULADA", distancia_km="99.0", duracion_min="120.0",
        ),
        _fila_csv(
            numero_guia="472008", fecha="19-08-2026", patente_tracto="AL1879",
            planta_origen_id=planta_colina.planta_id, planta_origen_nombre="AZA COLINA",
        ),
    ])
    repo = RepositorioTelemetria(carpeta / "telemetria_cache.json")
    _cachear_trip_con_destino(repo, patente="AL1879", fecha_iso=date(2026, 8, 18), fecha_doc="2026-08-18", punto_destino=COORD_AUSIN)
    _cachear_trip_con_destino(repo, patente="AL1879", fecha_iso=date(2026, 8, 19), fecha_doc="2026-08-19", punto_destino=COORD_AUSIN)
    servicio = ServicioTelemetria(ProveedorTelemetriaSoloCache(nombre="onelogis"), repo)

    proveedor = ProveedorRutasSimulado(resultado_ruta=ResultadoRuta(EstadoRuta.RUTA_CALCULADA, 20.0, 30.0, "SINTETICO"))
    resultado = revalidar_ruta_por_convergencia_gps_historica_sin_ocr(
        ruta_dataset=dataset, carpeta_catalogos=carpeta, proveedor_rutas=proveedor,
        servicio_telemetria=servicio,
    )
    assert resultado["guias_actualizadas"] == ["472008"]
    fila = next(f for f in _leer_csv(dataset) if f["numero_guia"] == "460807")
    assert fila["distancia_km"] == "99.0"  # intacto


def test_aprendizaje_persiste_coordenadas_en_destino_confirmado(tmp_path):
    carpeta, planta_colina, planta_renca = _catalogos(tmp_path)
    dataset = tmp_path / "dataset.csv"
    _escribir_csv(dataset, [
        _fila_csv(
            numero_guia="460807", fecha="18-08-2026", patente_tracto="AL1879",
            planta_origen_id=planta_renca.planta_id, planta_origen_nombre="AZA RENCA",
        ),
        _fila_csv(
            numero_guia="472008", fecha="19-08-2026", patente_tracto="AL1879",
            planta_origen_id=planta_colina.planta_id, planta_origen_nombre="AZA COLINA",
        ),
    ])
    catalogo_destinos = CatalogoDestinos(carpeta / "destinos_maestros.json", ruta_clientes=carpeta / "clientes.json")
    destino = catalogo_destinos.crear(
        cliente_id="", nombre_destino="INTERIOR NUEVA O1148 SAN BERNARDO",
        direccion="INTERIOR NUEVA O1148 SAN BERNARDO", pais="CHILE", fuente="TEST",
        estado_calidad=EstadoCalidadDestino.CONFIRMADO,
    )
    from atlas_core.catalogo_obras_destinos import CatalogoObrasDestinos, Evidencia, TipoEvidencia
    catalogo_obras = CatalogoObrasDestinos(
        ruta=carpeta / "obras_destinos.json", ruta_clientes=carpeta / "clientes.json",
        ruta_destinos=carpeta / "destinos_maestros.json",
    )
    from atlas_core.catalogo_clientes import CatalogoClientes, EstadoCalidadCliente
    cliente = CatalogoClientes(carpeta / "clientes.json").crear(
        razon_social="CLIENTE PRUEBA", rut="50.234.350-5", fuente="TEST", estado_calidad=EstadoCalidadCliente.CONFIRMADO,
    )
    resultado_obs = catalogo_obras.registrar_observacion(
        cliente_id=cliente.cliente_id, nombre_obra="AUSIN SAN BERNARDO", destino_id=destino.destino_id,
        evidencia=Evidencia(
            tipo=TipoEvidencia.GUIA.value, identificador_fuente="460807", referencia_hash="a" * 64,
            campos_observados={"obra": "AUSIN SAN BERNARDO"}, fecha="2026-01-01T00:00:00+00:00",
            actor_proceso="test", resultado="SOPORTA",
        ),
    )
    relacion = next(r for r in catalogo_obras.listar_relaciones() if r.obra_id == resultado_obs.obra.obra_id)
    catalogo_obras.confirmar_relacion(relacion.relacion_id, actor="test")

    repo = RepositorioTelemetria(carpeta / "telemetria_cache.json")
    _cachear_trip_con_destino(repo, patente="AL1879", fecha_iso=date(2026, 8, 18), fecha_doc="2026-08-18", punto_destino=COORD_AUSIN)
    _cachear_trip_con_destino(repo, patente="AL1879", fecha_iso=date(2026, 8, 19), fecha_doc="2026-08-19", punto_destino=COORD_AUSIN)
    servicio = ServicioTelemetria(ProveedorTelemetriaSoloCache(nombre="onelogis"), repo)

    proveedor = ProveedorRutasSimulado(resultado_ruta=ResultadoRuta(EstadoRuta.RUTA_CALCULADA, 20.0, 30.0, "SINTETICO"))
    resultado = revalidar_ruta_por_convergencia_gps_historica_sin_ocr(
        ruta_dataset=dataset, carpeta_catalogos=carpeta, proveedor_rutas=proveedor,
        servicio_telemetria=servicio,
    )
    assert destino.destino_id in resultado["destinos_aprendidos"]
    destino_actualizado = catalogo_destinos.obtener(destino.destino_id)
    assert destino_actualizado.latitud == COORD_AUSIN.latitud
    assert destino_actualizado.longitud == COORD_AUSIN.longitud
