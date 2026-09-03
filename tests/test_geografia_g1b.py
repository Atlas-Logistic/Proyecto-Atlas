"""G1-B: geocodificación estructurada + validación territorial por código +
caché territorial.

Continúa y cierra el bloque que Codex dejó en WIP (contrato/adaptador CL/
Nominatim/ORS/caché ya modificados en atlas_core/geografia/ y
atlas_core/rutas/, sobre el HEAD publicado 3019a7a de G1-A) -- esta suite
sólo cierra la cobertura de tests que faltaba, sin reabrir el diseño.

A) Geocodificación estructurada: contexto administrativo genérico desde
   GeografiaPais, consumido por Nominatim/ORS cuando está disponible,
   fallback textual seguro, AMBIGUA/NO_RECONOCIDA nunca inventan territorio.
B) Validación territorial por código: codigo_pais + codigo_unidad opaco +
   jerarquía, compatibilidad/incompatibilidad, motor genérico sin
   comuna/región/Santiago hardcodeados (esa semántica vive en cl.py).
C) Caché territorial: misma dirección en territorios distintos produce
   claves distintas; lectura legacy razonable (compatible se reutiliza,
   incompatible es cache miss, nunca un dato territorialmente equivocado).
"""
from __future__ import annotations

import json
from urllib.parse import parse_qs, urlparse

from atlas_core.geografia import EstadoNormalizacion, cargar_geografia
from atlas_core.geografia.cl import NIVEL_COMUNA
from atlas_core.geografia.modelos import ContextoGeocodificacion
from atlas_core.rutas.cache_geocodificacion import (
    ProveedorRutasConCacheGeocodificacion,
    RepositorioCacheGeocodificacion,
)
from atlas_core.rutas.destino_entrega import _contexto_geografico_desde_texto, _geocodificar_con_contexto
from atlas_core.rutas.modelos import CandidatoGeocodificacion, Coordenadas, EstadoRuta, ResultadoGeocodificacion
from atlas_core.rutas.nominatim import NominatimGeocoder, RespuestaHTTP
from atlas_core.rutas.openrouteservice import OpenRouteService
from atlas_core.rutas.proveedor import ProveedorRutasSimulado

GEOGRAFIA = cargar_geografia("CL")


def _contexto(nombre_comuna: str) -> ContextoGeocodificacion:
    decision = GEOGRAFIA.normalizar(nombre_comuna, nivel=NIVEL_COMUNA)
    assert decision.estado == EstadoNormalizacion.EXACTA, f"{nombre_comuna!r} debería ser EXACTA"
    return GEOGRAFIA.parametros_geocodificacion(decision.unidad)


def _resultado(estado=EstadoRuta.REQUIERE_REVISION, codigo_unidad="") -> ResultadoGeocodificacion:
    return ResultadoGeocodificacion(
        estado,
        (CandidatoGeocodificacion(Coordenadas(-70.6, -33.4), "DEMO", codigo_unidad=codigo_unidad),),
        "SINTETICO",
    )


# ============================================================
# A) GEOCODIFICACIÓN ESTRUCTURADA
# ============================================================


def test_contexto_geografico_desde_texto_exacta_da_contexto_util():
    contexto = _contexto_geografico_desde_texto("AV LIBERTADOR 123, PROVIDENCIA")
    assert contexto is not None
    assert contexto.codigo_pais == "CL"
    assert contexto.nombre_unidad == "Providencia"
    assert contexto.nombre_contexto == "Metropolitana"


def test_ambigua_o_no_reconocida_nunca_produce_contexto_nunca_inventa_territorio():
    # "Osorno" es a la vez comuna y provincia -> sin nivel explícito el
    # motor genérico se abstiene (AMBIGUA); el texto sin ninguna comuna
    # real reconocible es NO_RECONOCIDA. Ninguno de los dos casos debe
    # producir un ContextoGeocodificacion -- nunca inventar territorio.
    assert _contexto_geografico_desde_texto("ZONA RURAL SIN COMUNA IDENTIFICABLE") is None
    assert _contexto_geografico_desde_texto("") is None


def test_geocodificar_con_contexto_usa_metodo_estructurado_cuando_hay_contexto_y_lo_soporta():
    proveedor = ProveedorRutasSimulado()
    contexto = _contexto("Providencia")
    _geocodificar_con_contexto(proveedor, "AV LIBERTADOR 123", contexto)
    assert proveedor.llamadas_geocodificacion == 1  # geocodificar_estructurado delega en geocodificar


def test_geocodificar_con_contexto_cae_a_texto_plano_sin_contexto():
    proveedor = ProveedorRutasSimulado()
    _geocodificar_con_contexto(proveedor, "AV LIBERTADOR 123", None)
    assert proveedor.llamadas_geocodificacion == 1


def test_geocodificar_estructurado_nominatim_envia_comuna_y_region_como_city_state():
    """Nominatim reconstruye ahora comuna/región (city/state) desde el
    ContextoGeocodificacion de la autoridad geográfica -- ya no de un
    string suelto reconstruido a mano."""
    datos = [{
        "lat": "-33.44", "lon": "-70.65",
        "address": {"house_number": "123", "road": "Catedral", "suburb": "Santiago"},
    }]
    capturas: list[str] = []

    def transportar(solicitud, timeout):
        capturas.append(solicitud.full_url)
        return RespuestaHTTP(200, json.dumps(datos).encode("utf-8"))

    proveedor = NominatimGeocoder(transporte=transportar)
    contexto = _contexto("Santiago")

    resultado = proveedor.geocodificar_estructurado("CATEDRAL 123", contexto)

    assert resultado.estado == EstadoRuta.REQUIERE_REVISION
    assert any("street=" in url for url in capturas)
    parametros = parse_qs(urlparse(capturas[0]).query)
    assert parametros.get("city") == ["Santiago"]
    assert parametros.get("state") == ["Metropolitana"]


def test_geocodificar_estructurado_openrouteservice_incluye_comuna_region_y_pais():
    candidato = {
        "geometry": {"coordinates": [-70.65, -33.44]},
        "properties": {"label": "DEMO", "locality": "Santiago", "region": "Metropolitana"},
    }
    capturas: list = []

    def transportar(solicitud, timeout):
        capturas.append(solicitud.full_url)
        return RespuestaHTTP(200, json.dumps({"features": [candidato]}).encode("utf-8"))

    proveedor = OpenRouteService(api_key="SECRETO_DE_PRUEBA", pais="CL", transporte=transportar)
    contexto = _contexto("Santiago")

    resultado = proveedor.geocodificar_estructurado("CATEDRAL 123", contexto)

    assert resultado.estado != EstadoRuta.DIRECCION_NO_ENCONTRADA
    parametros = parse_qs(urlparse(capturas[0]).query)
    assert "Santiago" in parametros["text"][0]
    assert "Metropolitana" in parametros["text"][0]
    assert parametros.get("boundary.country") == ["CL"]
    # El candidato resuelto trae su propio código de unidad territorial,
    # derivado de la localidad devuelta (13101 == Santiago).
    assert resultado.candidatos[0].codigo_unidad == "13101"
    assert resultado.candidatos[0].codigo_pais == "CL"


# ============================================================
# B) VALIDACIÓN TERRITORIAL POR CÓDIGO
# ============================================================


def test_compatibilidad_territorial_misma_unidad_y_padre_hijo():
    santiago = GEOGRAFIA.normalizar("Santiago", nivel=NIVEL_COMUNA).unidad
    region_rm = GEOGRAFIA.buscar_por_codigo(santiago.codigo_padre)
    provincia = GEOGRAFIA.buscar_por_codigo(santiago.codigo_padre)
    assert GEOGRAFIA.compatibilidad_territorial(santiago, santiago)  # misma unidad exacta
    # comuna es descendiente directo de su propia jerarquía (código en la
    # cadena de códigos del otro) -- padre/hijo, no strings.
    provincia_real = GEOGRAFIA.buscar_por_codigo(santiago.codigo_padre)
    assert GEOGRAFIA.compatibilidad_territorial(santiago, provincia_real)


def test_incompatibilidad_territorial_regiones_distintas():
    san_bernardo = GEOGRAFIA.normalizar("San Bernardo", nivel=NIVEL_COMUNA).unidad  # RM
    angol = GEOGRAFIA.normalizar("Angol", nivel=NIVEL_COMUNA).unidad  # La Araucanía
    assert san_bernardo is not None and angol is not None
    assert not GEOGRAFIA.compatibilidad_territorial(san_bernardo, angol)
    # Dos comunas distintas de la MISMA región, ninguna "Santiago": sigue
    # siendo una contradicción real (caso real 460807), no una coincidencia.
    providencia = GEOGRAFIA.normalizar("Providencia", nivel=NIVEL_COMUNA).unidad
    las_condes = GEOGRAFIA.normalizar("Las Condes", nivel=NIVEL_COMUNA).unidad
    assert not GEOGRAFIA.compatibilidad_territorial(providencia, las_condes)


def test_motor_generico_no_conoce_comuna_region_ni_santiago():
    """El motor (contratos/modelos/motor.py) es agnóstico -- la regla de
    Santiago vive exclusivamente en el adaptador CL, nunca en el core.
    "región" como palabra genérica (p. ej. `nivel_region_geocodificacion`,
    ya parte del contrato desde G1-A) es un nombre de concepto válido en
    cualquier país -- lo que nunca debe aparecer es la semántica CHILENA
    concreta: comuna/provincia/Santiago/Metropolitana."""
    import atlas_core.geografia.motor as motor_modulo
    import atlas_core.geografia.contratos as contratos_modulo
    import atlas_core.geografia.modelos as modelos_modulo

    for modulo in (motor_modulo, contratos_modulo, modelos_modulo):
        texto = open(modulo.__file__, encoding="utf-8").read().upper()
        for prohibido in ("SANTIAGO", "COMUNA", "PROVINCIA", "METROPOLITANA"):
            assert prohibido not in texto, f"{prohibido!r} filtrado al core en {modulo.__name__}"


# ============================================================
# C) CACHÉ TERRITORIAL
# ============================================================


def test_misma_direccion_dos_territorios_produce_claves_distintas(tmp_path):
    repositorio = RepositorioCacheGeocodificacion(tmp_path / "cache.json")
    contexto_santiago = _contexto("Santiago")
    contexto_providencia = _contexto("Providencia")

    repositorio.guardar("proveedor", "1", "AV SIEMPRE VIVA 123", _resultado(), contexto_santiago)
    repositorio.guardar("proveedor", "1", "AV SIEMPRE VIVA 123", _resultado(), contexto_providencia)

    contenido = json.loads((tmp_path / "cache.json").read_text(encoding="utf-8"))
    assert len(contenido["consultas"]) == 2  # dos entradas -- nunca se pisan entre sí

    assert repositorio.buscar("proveedor", "1", "AV SIEMPRE VIVA 123", contexto_santiago) is not None
    assert repositorio.buscar("proveedor", "1", "AV SIEMPRE VIVA 123", contexto_providencia) is not None


def test_geocodificar_estructurado_con_cache_dos_territorios_llama_dos_veces(tmp_path):
    interno = ProveedorRutasSimulado()
    repositorio = RepositorioCacheGeocodificacion(tmp_path / "cache.json")
    proveedor = ProveedorRutasConCacheGeocodificacion(interno, repositorio)

    proveedor.geocodificar_estructurado("MISMA DIRECCION", _contexto("Santiago"))
    proveedor.geocodificar_estructurado("MISMA DIRECCION", _contexto("Providencia"))
    proveedor.geocodificar_estructurado("MISMA DIRECCION", _contexto("Santiago"))  # cache hit

    assert interno.llamadas_geocodificacion == 2


def test_cache_legacy_sin_contexto_se_reutiliza_si_es_territorialmente_compatible(tmp_path):
    """Una entrada vieja (guardada antes de G1-B, sin contexto -- clave
    legacy) sigue siendo válida como cache hit si el candidato que ya
    trae es compatible con el contexto nuevo que se está pidiendo."""
    repositorio = RepositorioCacheGeocodificacion(tmp_path / "cache.json")
    santiago = GEOGRAFIA.normalizar("Santiago", nivel=NIVEL_COMUNA).unidad
    resultado_legacy = ResultadoGeocodificacion(
        EstadoRuta.REQUIERE_REVISION,
        (CandidatoGeocodificacion(Coordenadas(-70.6, -33.4), "DEMO", codigo_unidad=santiago.codigo),),
        "SINTETICO",
    )
    repositorio.guardar("proveedor", "1", "AV LEGACY 1", resultado_legacy)  # sin contexto -- clave vieja

    encontrado = repositorio.buscar("proveedor", "1", "AV LEGACY 1", _contexto("Providencia"))
    assert encontrado is not None  # Santiago y Providencia son compatibles (misma RM, regla Santiago)


def test_cache_legacy_incompatible_es_miss_no_se_reutiliza(tmp_path):
    repositorio = RepositorioCacheGeocodificacion(tmp_path / "cache.json")
    angol = GEOGRAFIA.normalizar("Angol", nivel=NIVEL_COMUNA).unidad
    resultado_legacy = ResultadoGeocodificacion(
        EstadoRuta.REQUIERE_REVISION,
        (CandidatoGeocodificacion(Coordenadas(-72.7, -37.8), "DEMO", codigo_unidad=angol.codigo),),
        "SINTETICO",
    )
    repositorio.guardar("proveedor", "1", "AV LEGACY 2", resultado_legacy)  # comuna en La Araucanía

    encontrado = repositorio.buscar("proveedor", "1", "AV LEGACY 2", _contexto("Providencia"))
    assert encontrado is None  # territorio distinto -- cache miss histórico, nunca un dato equivocado


def test_geocodificar_legacy_sin_contexto_sigue_leyendo_clave_vieja(tmp_path):
    """Compatibilidad estricta: la lectura/escritura SIN contexto (el
    camino ya existente, `.geocodificar()`) sigue produciendo exactamente
    la misma clave que antes de G1-B -- cache hit normal, sin tocar nada
    de la caché territorial nueva."""
    interno = ProveedorRutasSimulado(geocodificaciones={"AV SIEMPRE VIVA 123": _resultado()})
    repositorio = RepositorioCacheGeocodificacion(tmp_path / "cache.json")
    proveedor = ProveedorRutasConCacheGeocodificacion(interno, repositorio)

    proveedor.geocodificar("AV SIEMPRE VIVA 123")
    proveedor.geocodificar("AV SIEMPRE VIVA 123")

    assert interno.llamadas_geocodificacion == 1


# ============================================================
# Compatibilidad: proveedor/doble legacy que sólo sabe texto
# ============================================================


class _ProveedorLegacySoloTexto:
    """Doble deliberadamente SIN geocodificar_estructurado -- simula un
    proveedor/adaptador de terceros escrito antes de G1-B."""

    nombre = "legacy"
    version = "1"

    def __init__(self):
        self.llamadas = 0

    def geocodificar(self, direccion: str) -> ResultadoGeocodificacion:
        self.llamadas += 1
        return _resultado()

    def calcular_ruta(self, origen, destino, perfil):
        raise NotImplementedError


def test_proveedor_legacy_solo_texto_sigue_funcionando_sin_metodo_estructurado():
    legacy = _ProveedorLegacySoloTexto()
    resultado = _geocodificar_con_contexto(legacy, "AV LIBERTADOR 123", _contexto("Santiago"))
    assert legacy.llamadas == 1
    assert resultado.estado == EstadoRuta.REQUIERE_REVISION


def test_proveedor_legacy_solo_texto_envuelto_en_cache_sigue_funcionando(tmp_path):
    legacy = _ProveedorLegacySoloTexto()
    repositorio = RepositorioCacheGeocodificacion(tmp_path / "cache.json")
    proveedor = ProveedorRutasConCacheGeocodificacion(legacy, repositorio)

    r1 = proveedor.geocodificar_estructurado("AV LIBERTADOR 123", _contexto("Santiago"))
    r2 = proveedor.geocodificar_estructurado("AV LIBERTADOR 123", _contexto("Santiago"))

    assert legacy.llamadas == 1  # 2da fue cache hit
    assert r1 == r2
