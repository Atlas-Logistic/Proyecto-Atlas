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


def test_raiz_atlas_explicita_ubica_el_cache_bajo_esa_raiz(tmp_path):
    """Bloque P0 AISLAMIENTO DE CACHÉ -- requisito (a): `raiz_atlas`
    explícita resuelve el archivo de caché DENTRO de esa raíz (mismo
    layout `cache/geocodificacion/...` que ya usa la raíz portable)."""
    scratch = tmp_path / "Atlas_scratch"
    repositorio = RepositorioCacheGeocodificacion(raiz_atlas=scratch)
    assert repositorio.ruta == scratch / "cache" / "geocodificacion" / "geocodificacion_cache.json"


def test_raiz_atlas_explicita_nunca_resuelve_hacia_g_aunque_g_exista(tmp_path, monkeypatch):
    """Bloque P0 AISLAMIENTO DE CACHÉ -- requisito (b): aunque la
    autodetección de Drive encontraría un G:\\ real (simulado aquí con un
    directorio que SÍ existe y SÍ parece una raíz de Drive válida),
    entregar `raiz_atlas` explícita hace que jamás se consulte esa
    autodetección -- ni siquiera se importa/llama."""
    g_simulado = tmp_path / "G_simulado" / "Mi unidad" / "Atlas"
    g_simulado.mkdir(parents=True)
    (g_simulado / "cache" / "geocodificacion").mkdir(parents=True)

    def _autodetectar_no_debe_llamarse():
        raise AssertionError("autodetectar_raiz_drive no debe consultarse cuando raiz_atlas es explícita")

    monkeypatch.setattr(
        "atlas_core.almacenamiento_portable.autodetectar_raiz_drive", _autodetectar_no_debe_llamarse,
    )
    scratch = tmp_path / "scratch_explicito"
    repositorio = RepositorioCacheGeocodificacion(raiz_atlas=scratch)
    assert repositorio.ruta == scratch / "cache" / "geocodificacion" / "geocodificacion_cache.json"
    assert g_simulado not in repositorio.ruta.parents
    # Ejercitar lectura/escritura real -- nunca toca `g_simulado`.
    interno = ProveedorRutasSimulado(geocodificaciones={"DIRECCION X": _resultado_ok()})
    ProveedorRutasConCacheGeocodificacion(interno, repositorio).geocodificar("DIRECCION X")
    assert not (g_simulado / "cache" / "geocodificacion" / "geocodificacion_cache.json").exists()
    assert (scratch / "cache" / "geocodificacion" / "geocodificacion_cache.json").exists()


def test_sin_raiz_ni_ruta_explicita_conserva_autodeteccion_productiva(tmp_path, monkeypatch):
    """Bloque P0 AISLAMIENTO DE CACHÉ -- requisito (c): la autodetección
    SÓLO puede existir cuando el caller no entrega ni `ruta` ni
    `raiz_atlas` -- comportamiento productivo idéntico al de siempre
    (mismo mecanismo que ya cubre `test_ruta_predeterminada_deriva_de_
    la_raiz_portable` vía variable de entorno; aquí se ejercita la otra
    vía de resolución productiva, la autodetección de Drive, para
    confirmar que sigue intacta)."""
    g_simulado = tmp_path / "G_simulado" / "Mi unidad" / "Atlas"
    g_simulado.mkdir(parents=True)
    monkeypatch.setattr(
        "atlas_core.almacenamiento_portable.autodetectar_raiz_drive", lambda: g_simulado,
    )
    monkeypatch.delenv("ATLAS_DATA_DIR", raising=False)
    repositorio = RepositorioCacheGeocodificacion()
    assert repositorio.ruta == g_simulado / "cache" / "geocodificacion" / "geocodificacion_cache.json"


def test_raiz_atlas_se_ignora_si_ruta_ya_viene_explicita(tmp_path):
    """`ruta` explícita (el caso ya usado por todos los tests de este
    archivo/por los tests que inyectan su propio archivo) sigue ganando
    sobre `raiz_atlas` -- compatibilidad total, nunca un comportamiento
    sorpresa para un caller que ya construye su propia ruta."""
    ruta_directa = tmp_path / "mi_cache_propio.json"
    otra_raiz = tmp_path / "raiz_que_debe_ignorarse"
    repositorio = RepositorioCacheGeocodificacion(ruta_directa, raiz_atlas=otra_raiz)
    assert repositorio.ruta == ruta_directa


def test_lectura_escritura_respeta_la_raiz_resuelta_por_raiz_atlas(tmp_path):
    """Bloque P0 AISLAMIENTO DE CACHÉ -- requisito (d): dos instancias
    construidas con la MISMA `raiz_atlas` comparten caché (una escribe,
    otra lee del disco); una tercera instancia con una `raiz_atlas`
    DISTINTA no ve nada -- el aislamiento por raíz es real, no sólo en
    el atributo `.ruta` calculado."""
    raiz_a = tmp_path / "Atlas_A"
    raiz_b = tmp_path / "Atlas_B"

    interno_1 = ProveedorRutasSimulado(geocodificaciones={"DIRECCION AISLADA": _resultado_ok()})
    ProveedorRutasConCacheGeocodificacion(
        interno_1, RepositorioCacheGeocodificacion(raiz_atlas=raiz_a),
    ).geocodificar("DIRECCION AISLADA")

    # Misma raíz A -- cache hit, nunca vuelve a llamar al proveedor interno.
    interno_2 = ProveedorRutasSimulado()
    resultado_misma_raiz = ProveedorRutasConCacheGeocodificacion(
        interno_2, RepositorioCacheGeocodificacion(raiz_atlas=raiz_a),
    ).geocodificar("DIRECCION AISLADA")
    assert interno_2.llamadas_geocodificacion == 0
    assert resultado_misma_raiz.estado == EstadoRuta.REQUIERE_REVISION

    # Raíz B distinta -- nunca ve lo que escribió la raíz A.
    interno_3 = ProveedorRutasSimulado(geocodificaciones={"DIRECCION AISLADA": _resultado_ok()})
    ProveedorRutasConCacheGeocodificacion(
        interno_3, RepositorioCacheGeocodificacion(raiz_atlas=raiz_b),
    ).geocodificar("DIRECCION AISLADA")
    assert interno_3.llamadas_geocodificacion == 1  # miss real -- raíz distinta, sin cache compartido
    assert (raiz_a / "cache" / "geocodificacion" / "geocodificacion_cache.json").exists()
    assert (raiz_b / "cache" / "geocodificacion" / "geocodificacion_cache.json").exists()


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
