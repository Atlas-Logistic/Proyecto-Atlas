"""INFRAESTRUCTURA S2.1 -- caché portable de geocodificación (Pelias/ORS)."""

from __future__ import annotations

from atlas_core.rutas.cache_geocodificacion import (
    ProveedorRutasConCacheGeocodificacion,
    RepositorioCacheGeocodificacion,
)
from atlas_core.rutas.modelos import (
    CandidatoGeocodificacion,
    Coordenadas,
    EstadoRuta,
    ResultadoGeocodificacion,
)
from atlas_core.rutas.proveedor import ProveedorRutasSimulado


def _resultado_ok() -> ResultadoGeocodificacion:
    return ResultadoGeocodificacion(
        EstadoRuta.REQUIERE_REVISION,
        (CandidatoGeocodificacion(Coordenadas(-70.65, -33.45), "AV SIEMPRE VIVA 123"),),
        "REQUIERE_CONFIRMACION_HUMANA",
    )


def test_segunda_consulta_identica_no_llama_al_proveedor(tmp_path):
    interno = ProveedorRutasSimulado(
        geocodificaciones={
            "AV SIEMPRE VIVA 123, SANTIAGO, RM, CL": _resultado_ok(),
        }
    )
    repositorio = RepositorioCacheGeocodificacion(tmp_path / "geocodificacion_cache.json")
    proveedor = ProveedorRutasConCacheGeocodificacion(interno, repositorio)

    r1 = proveedor.geocodificar("AV SIEMPRE VIVA 123, SANTIAGO, RM, CL")
    r2 = proveedor.geocodificar("AV SIEMPRE VIVA 123, SANTIAGO, RM, CL")

    assert interno.llamadas_geocodificacion == 1  # la 2da consulta fue cache hit
    assert r1 == r2
    assert r2.estado == EstadoRuta.REQUIERE_REVISION


def test_cambio_de_direccion_invalida_la_clave_de_cache(tmp_path):
    interno = ProveedorRutasSimulado()
    repositorio = RepositorioCacheGeocodificacion(tmp_path / "geocodificacion_cache.json")
    proveedor = ProveedorRutasConCacheGeocodificacion(interno, repositorio)

    proveedor.geocodificar("DIRECCION A")
    proveedor.geocodificar("DIRECCION B")

    assert interno.llamadas_geocodificacion == 2


def test_variantes_de_mayusculas_y_acentos_comparten_cache(tmp_path):
    interno = ProveedorRutasSimulado()
    repositorio = RepositorioCacheGeocodificacion(tmp_path / "geocodificacion_cache.json")
    proveedor = ProveedorRutasConCacheGeocodificacion(interno, repositorio)

    proveedor.geocodificar("Avenida Ñuñoa 45, Santiago")
    proveedor.geocodificar("AVENIDA NUNOA 45,   santiago")

    assert interno.llamadas_geocodificacion == 1


def test_proveedores_distintos_no_comparten_cache(tmp_path):
    repositorio = RepositorioCacheGeocodificacion(tmp_path / "geocodificacion_cache.json")
    interno_a = ProveedorRutasSimulado(nombre="proveedor_a")
    interno_b = ProveedorRutasSimulado(nombre="proveedor_b")
    proveedor_a = ProveedorRutasConCacheGeocodificacion(interno_a, repositorio)
    proveedor_b = ProveedorRutasConCacheGeocodificacion(interno_b, repositorio)

    proveedor_a.geocodificar("MISMA DIRECCION")
    proveedor_b.geocodificar("MISMA DIRECCION")

    assert interno_a.llamadas_geocodificacion == 1
    assert interno_b.llamadas_geocodificacion == 1


def test_fallos_transitorios_no_se_cachean(tmp_path):
    from atlas_core.rutas.modelos import ResultadoGeocodificacion

    interno = ProveedorRutasSimulado(
        geocodificaciones={
            "DIRECCION SIN CONEXION": ResultadoGeocodificacion(EstadoRuta.SIN_CONEXION),
        }
    )
    repositorio = RepositorioCacheGeocodificacion(tmp_path / "geocodificacion_cache.json")
    proveedor = ProveedorRutasConCacheGeocodificacion(interno, repositorio)

    proveedor.geocodificar("DIRECCION SIN CONEXION")
    proveedor.geocodificar("DIRECCION SIN CONEXION")

    assert interno.llamadas_geocodificacion == 2  # se reintenta, no queda "pegado"


def test_archivo_de_cache_persistido_nunca_contiene_credenciales(tmp_path):
    # La caché de geocodificación solo debería persistir dirección/candidatos
    # -- nunca la api_key del proveedor (que ni siquiera pasa por este
    # decorador). Guarda contra una futura regresión que empiece a
    # serializar el proveedor completo.
    interno = ProveedorRutasSimulado()
    ruta = tmp_path / "geocodificacion_cache.json"
    proveedor = ProveedorRutasConCacheGeocodificacion(
        interno, RepositorioCacheGeocodificacion(ruta)
    )
    proveedor.geocodificar("DIRECCION CUALQUIERA")

    crudo = ruta.read_text(encoding="utf-8").lower()
    for patron in ("api_key", "authorization", "bearer", "secret", "token"):
        assert patron not in crudo


def test_calcular_ruta_se_delega_sin_cache_propia(tmp_path):
    interno = ProveedorRutasSimulado()
    repositorio = RepositorioCacheGeocodificacion(tmp_path / "geocodificacion_cache.json")
    proveedor = ProveedorRutasConCacheGeocodificacion(interno, repositorio)

    proveedor.calcular_ruta(Coordenadas(-70.6, -33.4), Coordenadas(-70.7, -33.5), "hgv")
    proveedor.calcular_ruta(Coordenadas(-70.6, -33.4), Coordenadas(-70.7, -33.5), "hgv")

    assert interno.llamadas_ruta == 2  # deliberado: esa cache vive en RepositorioRutas


def test_nombre_y_version_expuestos_igual_que_el_proveedor_interno(tmp_path):
    interno = ProveedorRutasSimulado(nombre="openrouteservice", version="v2")
    repositorio = RepositorioCacheGeocodificacion(tmp_path / "geocodificacion_cache.json")
    proveedor = ProveedorRutasConCacheGeocodificacion(interno, repositorio)

    assert proveedor.nombre == "openrouteservice"
    assert proveedor.version == "v2"


def test_ruta_predeterminada_deriva_de_la_raiz_portable(tmp_path, monkeypatch):
    monkeypatch.setenv("ATLAS_DATA_DIR", str(tmp_path / "Atlas"))
    repositorio = RepositorioCacheGeocodificacion()
    assert repositorio.ruta == tmp_path / "Atlas" / "cache" / "geocodificacion" / "geocodificacion_cache.json"


def test_cache_persiste_en_disco_entre_instancias_distintas(tmp_path):
    ruta = tmp_path / "geocodificacion_cache.json"
    interno_1 = ProveedorRutasSimulado()
    ProveedorRutasConCacheGeocodificacion(
        interno_1, RepositorioCacheGeocodificacion(ruta)
    ).geocodificar("DIRECCION PERSISTENTE")
    assert ruta.is_file()

    interno_2 = ProveedorRutasSimulado()
    resultado = ProveedorRutasConCacheGeocodificacion(
        interno_2, RepositorioCacheGeocodificacion(ruta)
    ).geocodificar("DIRECCION PERSISTENTE")

    assert interno_2.llamadas_geocodificacion == 0  # nunca se llamó -- vino de disco
    assert resultado.estado == EstadoRuta.REQUIERE_REVISION
