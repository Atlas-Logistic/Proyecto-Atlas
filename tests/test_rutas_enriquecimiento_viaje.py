from datetime import datetime, timedelta, timezone

import pytest

from atlas_core.catalogo_destinos import CatalogoDestinos, EstadoCalidadDestino
from atlas_core.catalogo_clientes import CatalogoClientes
from atlas_core.catalogo_plantas import CatalogoPlantas, EstadoCalidad
from atlas_core.rutas.enriquecimiento_viaje import (
    calcular_ruta_para_viaje,
    resolver_destino_canonico,
    resolver_planta_origen,
)
from atlas_core.rutas.geocerca import resolver_planta_por_posicion
from atlas_core.rutas.modelos import Coordenadas, EstadoRuta, ResultadoRuta
from atlas_core.rutas.posicion_vehiculo import (
    EstadoPosicionVehiculo,
    ProveedorPosicionVehiculoSimulado,
    ResultadoPosicionVehiculo,
)
from atlas_core.rutas.proveedor import ProveedorRutasSimulado
from atlas_core.rutas.repositorio import RepositorioRutas
from atlas_core.rutas.servicio import ServicioRutas

INSTANTE_SALIDA = datetime(2026, 8, 11, 12, 0, tzinfo=timezone.utc)

# Coordenadas reales ya usadas/confirmadas en bloques previos (RUTAS-EVAL R1
# / validación real ORS).
COORD_AZA_RENCA = Coordenadas(-70.685226, -33.401595)
COORD_AZA_COLINA = Coordenadas(-70.665964, -33.137640)
COORD_LEJANA = Coordenadas(-70.65, -18.47)  # Arica, a >1500 km


@pytest.fixture
def entorno(tmp_path):
    ruta_plantas = tmp_path / "plantas.json"
    ruta_clientes = tmp_path / "clientes.json"
    ruta_destinos = tmp_path / "destinos_maestros.json"

    plantas_repo = CatalogoPlantas(ruta_plantas)
    planta_renca = plantas_repo.crear(
        nombre="AZA RENCA", pais="CHILE", fuente="PRUEBA",
        direccion="LA UNION 3070", comuna="RENCA", region="RM",
        latitud=COORD_AZA_RENCA.latitud, longitud=COORD_AZA_RENCA.longitud,
        estado_calidad=EstadoCalidad.CONFIRMADA,
    )
    planta_colina = plantas_repo.crear(
        nombre="AZA COLINA", pais="CHILE", fuente="PRUEBA",
        direccion="AV. PDTE. EDUARDO FREI MONTALVA 18500", comuna="COLINA", region="RM",
        latitud=COORD_AZA_COLINA.latitud, longitud=COORD_AZA_COLINA.longitud,
        estado_calidad=EstadoCalidad.CONFIRMADA,
    )

    clientes_repo = CatalogoClientes(ruta_clientes)
    cliente = clientes_repo.crear(razon_social="EBEMA SA", fuente="PRUEBA")

    destinos_repo = CatalogoDestinos(ruta_destinos, ruta_clientes=ruta_clientes)
    destino_valido = destinos_repo.crear(
        cliente_id=cliente.cliente_id, nombre_destino="GALVARINO 8501",
        pais="CHILE", fuente="PRUEBA", direccion="GALVARINO 8501", comuna="QUILICURA", region="RM",
        latitud=-33.370934, longitud=-70.716168,
        estado_calidad=EstadoCalidadDestino.CONFIRMADO,
    )
    destino_fuera_de_rango = destinos_repo.crear(
        cliente_id=cliente.cliente_id, nombre_destino="SAN MIGUEL ERRONEO",
        pais="CHILE", fuente="PRUEBA", direccion="CARMEN MENA 529", comuna="SAN MIGUEL", region="RM",
        latitud=-30.8143, longitud=-70.6034,  # mismo error real detectado en RUTAS-EVAL R1
        estado_calidad=EstadoCalidadDestino.CONFIRMADO,
    )

    return {
        "plantas": plantas_repo.listar(),
        "planta_renca": planta_renca, "planta_colina": planta_colina,
        "catalogo_destinos": destinos_repo,
        "destino_valido": destino_valido, "destino_fuera_de_rango": destino_fuera_de_rango,
    }


def _proveedor_gps(patente, coordenadas, *, timestamp=INSTANTE_SALIDA, estado=EstadoPosicionVehiculo.POSICION_ENCONTRADA):
    return ProveedorPosicionVehiculoSimulado(posiciones={
        patente: ResultadoPosicionVehiculo(
            estado, coordenadas=coordenadas, timestamp_gps=timestamp.isoformat(),
            proveedor="simulado",
        )
    })


# --- 1/2/3: geocerca ---

def test_posicion_dentro_geocerca_renca_resuelve_renca(entorno):
    resultado = resolver_planta_por_posicion(COORD_AZA_RENCA, entorno["plantas"])
    assert resultado.determinada
    assert resultado.planta_id == entorno["planta_renca"].planta_id


def test_posicion_dentro_geocerca_colina_resuelve_colina(entorno):
    resultado = resolver_planta_por_posicion(COORD_AZA_COLINA, entorno["plantas"])
    assert resultado.determinada
    assert resultado.planta_id == entorno["planta_colina"].planta_id


def test_posicion_fuera_de_ambas_geocercas_no_determinada(entorno):
    resultado = resolver_planta_por_posicion(COORD_LEJANA, entorno["plantas"])
    assert not resultado.determinada
    assert resultado.motivo == "FUERA_DE_GEOCERCA"


# --- 4: dato GPS demasiado antiguo ---

def test_posicion_gps_demasiado_antigua_no_determinada(entorno):
    proveedor = _proveedor_gps("ABCD12", COORD_AZA_RENCA, timestamp=INSTANTE_SALIDA - timedelta(hours=10))
    planta, motivo, determinado_por, evidencia = resolver_planta_origen(
        patente="ABCD12", instante_salida=INSTANTE_SALIDA,
        proveedor_posicion=proveedor, plantas=entorno["plantas"],
    )
    assert planta is None
    assert motivo == "POSICION_GPS_DEMASIADO_ANTIGUA"
    assert determinado_por == ""
    assert evidencia == ""


# --- 5: planta válida + destino válido -> ORS ---

def test_planta_y_destino_validos_calcula_ruta_real(entorno, tmp_path):
    proveedor_gps = _proveedor_gps("ABCD12", COORD_AZA_RENCA)
    proveedor_rutas = ProveedorRutasSimulado(
        resultado_ruta=ResultadoRuta(EstadoRuta.RUTA_CALCULADA, 7.43, 12.06, "")
    )
    servicio = ServicioRutas(proveedor_rutas, RepositorioRutas(tmp_path / "rutas.json"))

    resultado = calcular_ruta_para_viaje(
        obra_destino_texto="GALVARINO 8501", patente="ABCD12", instante_salida=INSTANTE_SALIDA,
        catalogo_destinos=entorno["catalogo_destinos"], plantas=entorno["plantas"],
        proveedor_posicion=proveedor_gps, servicio_rutas=servicio,
    )

    assert resultado.estado_ruta == EstadoRuta.RUTA_CALCULADA.value
    assert resultado.planta_origen_nombre == "AZA RENCA"
    assert resultado.destino_nombre == "GALVARINO 8501"
    assert resultado.distancia_km == "7.43"
    assert resultado.duracion_min == "12.06"
    assert resultado.proveedor_ruta == "simulado"
    assert resultado.origen_determinado_por == "ONELOGIS_GPS"
    assert proveedor_rutas.llamadas_ruta == 1


# --- 6: segunda ejecución -> caché, sin nueva llamada al proveedor ---

def test_segunda_ejecucion_usa_cache_no_llama_proveedor_de_nuevo(entorno, tmp_path):
    proveedor_gps = _proveedor_gps("ABCD12", COORD_AZA_RENCA)
    proveedor_rutas = ProveedorRutasSimulado(
        resultado_ruta=ResultadoRuta(EstadoRuta.RUTA_CALCULADA, 7.43, 12.06, "")
    )
    servicio = ServicioRutas(proveedor_rutas, RepositorioRutas(tmp_path / "rutas.json"))
    kwargs = dict(
        obra_destino_texto="GALVARINO 8501", patente="ABCD12", instante_salida=INSTANTE_SALIDA,
        catalogo_destinos=entorno["catalogo_destinos"], plantas=entorno["plantas"],
        proveedor_posicion=proveedor_gps, servicio_rutas=servicio,
    )

    primera = calcular_ruta_para_viaje(**kwargs)
    segunda = calcular_ruta_para_viaje(**kwargs)

    assert primera.estado_ruta == EstadoRuta.RUTA_CALCULADA.value
    assert segunda.estado_ruta == EstadoRuta.RESULTADO_DESDE_CACHE.value
    assert segunda.distancia_km == primera.distancia_km == "7.43"
    assert segunda.duracion_min == primera.duracion_min == "12.06"
    assert proveedor_rutas.llamadas_ruta == 1  # no se repite la llamada real


# --- 7: destino inválido -> no se consulta ORS ---

@pytest.mark.parametrize(
    "obra_destino_texto",
    ["TEXTO OCR SIN HOMOLOGAR", "SAN MIGUEL ERRONEO", "", "No encontrado"],
)
def test_destino_invalido_no_consulta_ors(entorno, tmp_path, obra_destino_texto):
    proveedor_gps = _proveedor_gps("ABCD12", COORD_AZA_RENCA)
    proveedor_rutas = ProveedorRutasSimulado()
    servicio = ServicioRutas(proveedor_rutas, RepositorioRutas(tmp_path / "rutas.json"))

    resultado = calcular_ruta_para_viaje(
        obra_destino_texto=obra_destino_texto, patente="ABCD12", instante_salida=INSTANTE_SALIDA,
        catalogo_destinos=entorno["catalogo_destinos"], plantas=entorno["plantas"],
        proveedor_posicion=proveedor_gps, servicio_rutas=servicio,
    )

    assert resultado.estado_ruta == EstadoRuta.DESTINO_NO_VALIDO.value
    assert resultado.distancia_km == ""
    assert proveedor_rutas.llamadas_ruta == 0


# --- 8: Onelogis sin datos -> el enriquecimiento se abstiene sin lanzar ---

def test_onelogis_sin_datos_no_falla_y_no_consulta_ors(entorno, tmp_path):
    proveedor_gps = ProveedorPosicionVehiculoSimulado()  # sin posiciones inyectadas
    proveedor_rutas = ProveedorRutasSimulado()
    servicio = ServicioRutas(proveedor_rutas, RepositorioRutas(tmp_path / "rutas.json"))

    resultado = calcular_ruta_para_viaje(
        obra_destino_texto="GALVARINO 8501", patente="ABCD12", instante_salida=INSTANTE_SALIDA,
        catalogo_destinos=entorno["catalogo_destinos"], plantas=entorno["plantas"],
        proveedor_posicion=proveedor_gps, servicio_rutas=servicio,
    )

    assert resultado.estado_ruta == EstadoRuta.ORIGEN_NO_DETERMINADO.value
    assert resultado.motivo_ruta == "GPS_SIN_DATOS"
    assert proveedor_rutas.llamadas_ruta == 0


def test_sin_proveedor_posicion_no_falla_se_abstiene(entorno, tmp_path):
    """Sin proveedor de posición configurado (Onelogis no disponible), el
    viaje sigue siendo válido -- solo el enriquecimiento queda pendiente."""
    proveedor_rutas = ProveedorRutasSimulado()
    servicio = ServicioRutas(proveedor_rutas, RepositorioRutas(tmp_path / "rutas.json"))

    resultado = calcular_ruta_para_viaje(
        obra_destino_texto="GALVARINO 8501", patente="ABCD12", instante_salida=INSTANTE_SALIDA,
        catalogo_destinos=entorno["catalogo_destinos"], plantas=entorno["plantas"],
        proveedor_posicion=None, servicio_rutas=servicio,
    )

    assert resultado.estado_ruta == EstadoRuta.ORIGEN_NO_DETERMINADO.value
    assert resultado.motivo_ruta == "SIN_EVIDENCIA_GPS"


# --- PLANTA-P1: fallback documental + política de conflicto GPS/documento ---

TEXTO_DOCUMENTAL_RENCA = ["GUIA DESPACHO PLANTA ORIGEN RENCA ACEROS AZA S A CASA MATRIZ PLANTA RENCA LA UNION 3070 RENCA SANTIAGO CHILE"]
TEXTO_DOCUMENTAL_COLINA = [
    "GUIA DESPACHO PLANTA ORIGEN COLINA ACEROS AZA S A CASA MATRIZ PLANTA COLINA PANAMERICANA NORTE 18500 COLINA SANTIAGO CHILE"
]


def test_gps_no_alcanza_cae_a_fallback_documental(entorno, tmp_path):
    """GPS demasiado antiguo (no útil) -> el enriquecimiento recurre al
    fallback documental y sí determina la planta."""
    proveedor_gps = _proveedor_gps("ABCD12", COORD_AZA_RENCA, timestamp=INSTANTE_SALIDA - timedelta(hours=10))
    proveedor_rutas = ProveedorRutasSimulado(
        resultado_ruta=ResultadoRuta(EstadoRuta.RUTA_CALCULADA, 7.43, 12.06, "")
    )
    servicio = ServicioRutas(proveedor_rutas, RepositorioRutas(tmp_path / "rutas.json"))

    resultado = calcular_ruta_para_viaje(
        obra_destino_texto="GALVARINO 8501", patente="ABCD12", instante_salida=INSTANTE_SALIDA,
        catalogo_destinos=entorno["catalogo_destinos"], plantas=entorno["plantas"],
        proveedor_posicion=proveedor_gps, servicio_rutas=servicio,
        textos_documento=TEXTO_DOCUMENTAL_RENCA,
    )

    assert resultado.planta_origen_nombre == "AZA RENCA"
    assert resultado.origen_determinado_por == "DOCUMENTO"
    assert resultado.evidencia_origen == "ENCABEZADO_GUIA"
    assert resultado.estado_ruta == EstadoRuta.RUTA_CALCULADA.value


def test_conflicto_gps_vs_documento_gana_gps_siempre(entorno, tmp_path):
    """Política conservadora ante conflicto: si el GPS SÍ determina una
    planta, esa gana siempre -- el documento nunca se usa para desempatar
    ni para contradecir un GPS válido."""
    proveedor_gps = _proveedor_gps("ABCD12", COORD_AZA_RENCA)  # GPS real: RENCA
    proveedor_rutas = ProveedorRutasSimulado(
        resultado_ruta=ResultadoRuta(EstadoRuta.RUTA_CALCULADA, 7.43, 12.06, "")
    )
    servicio = ServicioRutas(proveedor_rutas, RepositorioRutas(tmp_path / "rutas.json"))

    resultado = calcular_ruta_para_viaje(
        obra_destino_texto="GALVARINO 8501", patente="ABCD12", instante_salida=INSTANTE_SALIDA,
        catalogo_destinos=entorno["catalogo_destinos"], plantas=entorno["plantas"],
        proveedor_posicion=proveedor_gps, servicio_rutas=servicio,
        textos_documento=TEXTO_DOCUMENTAL_COLINA,  # documento dice COLINA
    )

    assert resultado.planta_origen_nombre == "AZA RENCA"  # gana el GPS
    assert resultado.origen_determinado_por == "ONELOGIS_GPS"


def test_sin_evidencia_gps_ni_documental_origen_no_determinado(entorno, tmp_path):
    proveedor_rutas = ProveedorRutasSimulado()
    servicio = ServicioRutas(proveedor_rutas, RepositorioRutas(tmp_path / "rutas.json"))

    resultado = calcular_ruta_para_viaje(
        obra_destino_texto="GALVARINO 8501", patente=None, instante_salida=None,
        catalogo_destinos=entorno["catalogo_destinos"], plantas=entorno["plantas"],
        proveedor_posicion=None, servicio_rutas=servicio,
        textos_documento=["GUIA SIN NINGUNA MENCION DE PLANTA"],
    )

    assert resultado.estado_ruta == EstadoRuta.ORIGEN_NO_DETERMINADO.value
    assert resultado.planta_origen_nombre == ""
    assert proveedor_rutas.llamadas_ruta == 0


# ============================================================
# Bloque ORIGEN V3 -- CONVERGENCIA DE EVIDENCIA ANTES DE PREGUNTAR: sin
# GPS y sin ningún origen informado (ni Mobile ni documento), antes de
# rendirse se intenta resolver por categoría/destino solo -- casos
# reales del lote 2 (464730/464631/464529).
# ============================================================

@pytest.fixture
def entorno_categorias(tmp_path):
    ruta_plantas = tmp_path / "plantas.json"
    plantas_repo = CatalogoPlantas(ruta_plantas)
    planta_renca = plantas_repo.crear(
        nombre="AZA RENCA", pais="CHILE", fuente="PRUEBA",
        direccion="LA UNION 3070", comuna="RENCA", region="RM",
        latitud=COORD_AZA_RENCA.latitud, longitud=COORD_AZA_RENCA.longitud,
        estado_calidad=EstadoCalidad.CONFIRMADA, categorias_permitidas=("ANGULOS",),
    )
    planta_colina = plantas_repo.crear(
        nombre="AZA COLINA", pais="CHILE", fuente="PRUEBA",
        direccion="AV. PDTE. EDUARDO FREI MONTALVA 18500", comuna="COLINA", region="RM",
        latitud=COORD_AZA_COLINA.latitud, longitud=COORD_AZA_COLINA.longitud,
        estado_calidad=EstadoCalidad.CONFIRMADA, categorias_permitidas=("BARRAS", "ROLLOS"),
    )
    return {"plantas": plantas_repo.listar(), "renca": planta_renca, "colina": planta_colina}


def test_sin_gps_sin_mobile_sin_documento_resuelve_por_categoria_solo(entorno_categorias):
    """Caso real 464730/464631/464529: ningún origen informado -- ni
    Mobile ni encabezado -- pero la categoría real sólo la despacha una
    planta vigente del catálogo, y el destino no es esa misma planta."""
    planta, motivo, determinado_por, evidencia = resolver_planta_origen(
        patente=None, instante_salida=None, proveedor_posicion=None,
        plantas=entorno_categorias["plantas"],
        textos_documento=["GUIA SIN NINGUNA MENCION DE PLANTA"],
        categoria_documento="BARRAS", destino_texto="CALLE DE UN CLIENTE CUALQUIERA 500",
    )
    assert planta.planta_id == entorno_categorias["colina"].planta_id
    assert determinado_por == "CATEGORIA_DESTINO_EXTERNO"
    assert motivo == ""


def test_categoria_sin_regla_sigue_sin_determinar(entorno_categorias):
    """Sin categoría (o SIN_REGLA) nunca inventa -- 464367/464265, donde
    el material quedó NO_DETERMINADO."""
    planta, motivo, determinado_por, evidencia = resolver_planta_origen(
        patente=None, instante_salida=None, proveedor_posicion=None,
        plantas=entorno_categorias["plantas"],
        textos_documento=["GUIA SIN NINGUNA MENCION DE PLANTA"],
        categoria_documento="NO DETERMINADO", destino_texto="CUALQUIER DESTINO",
    )
    assert planta is None
    assert determinado_por == ""


def test_gps_sigue_siendo_superior_a_la_categoria(entorno_categorias):
    """GPS real (posición dentro de la geocerca) sigue ganando siempre,
    incluso si la categoría por sí sola apuntaría a otra planta."""
    proveedor_gps = _proveedor_gps("ABCD12", COORD_AZA_RENCA)  # GPS real: RENCA
    planta, motivo, determinado_por, evidencia = resolver_planta_origen(
        patente="ABCD12", instante_salida=INSTANTE_SALIDA, proveedor_posicion=proveedor_gps,
        plantas=entorno_categorias["plantas"],
        textos_documento=["GUIA SIN NINGUNA MENCION DE PLANTA"],
        categoria_documento="BARRAS", destino_texto="CUALQUIER DESTINO",
    )
    assert planta.planta_id == entorno_categorias["renca"].planta_id  # gana el GPS, aunque RENCA no maneje BARRAS
    assert determinado_por == "ONELOGIS_GPS"


def test_traslado_interno_no_resuelve_por_categoria(entorno_categorias):
    planta, motivo, determinado_por, evidencia = resolver_planta_origen(
        patente=None, instante_salida=None, proveedor_posicion=None,
        plantas=entorno_categorias["plantas"],
        textos_documento=["GUIA SIN NINGUNA MENCION DE PLANTA"],
        categoria_documento="BARRAS",
        destino_texto="AV. PDTE. EDUARDO FREI MONTALVA 18500",  # la propia dirección de AZA COLINA
    )
    assert planta is None


def test_planta_determinada_sin_coordenadas_en_catalogo_no_lanza(tmp_path):
    """Caso real (AZA COLINA sin lat/lon cargados en plantas.json antes de
    este bloque): la planta se determina (documento) pero su registro de
    catálogo no tiene coordenadas -- nunca debe lanzar, se trata como
    origen no determinado."""
    ruta_plantas = tmp_path / "plantas.json"
    plantas_repo = CatalogoPlantas(ruta_plantas)
    planta_sin_coords = plantas_repo.crear(
        nombre="AZA COLINA", pais="CHILE", fuente="PRUEBA",
        direccion="AV. PDTE. EDUARDO FREI MONTALVA 18500", comuna="COLINA", region="RM",
        estado_calidad=EstadoCalidad.CONFIRMADA,
    )
    assert planta_sin_coords.latitud is None and planta_sin_coords.longitud is None

    ruta_clientes = tmp_path / "clientes.json"
    cliente = CatalogoClientes(ruta_clientes).crear(razon_social="CLIENTE PRUEBA", fuente="PRUEBA")
    destinos_repo = CatalogoDestinos(tmp_path / "destinos.json", ruta_clientes=ruta_clientes)
    destino = destinos_repo.crear(
        cliente_id=cliente.cliente_id, nombre_destino="DESTINO PRUEBA",
        pais="CHILE", fuente="PRUEBA", latitud=-33.45, longitud=-70.65,
        estado_calidad=EstadoCalidadDestino.CONFIRMADO,
    )

    proveedor_rutas = ProveedorRutasSimulado()
    servicio = ServicioRutas(proveedor_rutas, RepositorioRutas(tmp_path / "rutas.json"))

    resultado = calcular_ruta_para_viaje(
        obra_destino_texto="DESTINO PRUEBA", patente=None, instante_salida=None,
        catalogo_destinos=destinos_repo, plantas=[planta_sin_coords],
        proveedor_posicion=None, servicio_rutas=servicio,
        textos_documento=["GUIA DESPACHO PLANTA ORIGEN COLINA ACEROS AZA CASA MATRIZ PLANTA COLINA"],
    )

    assert resultado.estado_ruta == EstadoRuta.ORIGEN_NO_DETERMINADO.value
    assert resultado.motivo_ruta == "PLANTA_SIN_COORDENADAS_EN_CATALOGO"
    assert proveedor_rutas.llamadas_ruta == 0


# --- 9: km/min persistidos correctamente (perfil driving-hgv) ---

def test_km_min_persistidos_y_perfil_driving_hgv(entorno, tmp_path):
    capturas = []

    class ProveedorRutasCapturaPerfil(ProveedorRutasSimulado):
        def calcular_ruta(self, origen, destino, perfil):
            capturas.append(perfil)
            return super().calcular_ruta(origen, destino, perfil)

    proveedor_rutas = ProveedorRutasCapturaPerfil(
        resultado_ruta=ResultadoRuta(EstadoRuta.RUTA_CALCULADA, 33.17, 40.41, "")
    )
    servicio = ServicioRutas(proveedor_rutas, RepositorioRutas(tmp_path / "rutas.json"))
    proveedor_gps = _proveedor_gps("ABCD12", COORD_AZA_RENCA)

    resultado = calcular_ruta_para_viaje(
        obra_destino_texto="GALVARINO 8501", patente="ABCD12", instante_salida=INSTANTE_SALIDA,
        catalogo_destinos=entorno["catalogo_destinos"], plantas=entorno["plantas"],
        proveedor_posicion=proveedor_gps, servicio_rutas=servicio,
    )

    assert capturas == ["driving-hgv"]
    assert resultado.distancia_km == "33.17"
    assert resultado.duracion_min == "40.41"
