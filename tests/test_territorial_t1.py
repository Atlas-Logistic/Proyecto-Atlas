"""Bloque TERRITORIAL T1 -- corrige dos causas reales de falsos rechazos
por `GEOCODIFICACION_CONTRADICE_COMUNA_DOCUMENTAL`:

1. Comparación de niveles territoriales distintos: "Santiago" usado como
   etiqueta de ciudad/área metropolitana (documental o del
   geocodificador) contra una comuna específica real (Cerrillos, Renca,
   Maipú, Quilicura, San Bernardo, etc.) de la MISMA región -- caso real
   472238/472239 (VISTA CLARA 2351 CERRILLOS).
2. Nombres compuestos de calle mal partidos: la primera palabra de una
   calle compuesta ("Vicuña Mackenna") coincide, por sí sola, con una
   comuna real distinta (Vicuña, Coquimbo) -- caso real 472037.

Ambas correcciones reutilizan el catálogo territorial ya existente
(`territorio_chile.normalizar_comuna`, comuna -> región) -- nunca una
lista propia de comunas/calles hardcodeada."""
from atlas_core.catalogo_plantas import CatalogoPlantas, EstadoCalidad
from atlas_core.rutas.destino_entrega import (
    _comuna_documental_inequivoca,
    _comunas_explicitas,
    _comunas_territorialmente_compatibles,
    calcular_ruta_con_planta_conocida,
)
from atlas_core.rutas.modelos import (
    CandidatoGeocodificacion, Coordenadas, EstadoRuta, ResultadoGeocodificacion, ResultadoRuta,
)
from atlas_core.rutas.proveedor import ProveedorRutasSimulado

COORD_AZA_COLINA = Coordenadas(-70.669, -33.201)


def _planta(tmp_path):
    plantas = CatalogoPlantas(tmp_path / "plantas.json")
    return plantas.crear(
        nombre="AZA COLINA", pais="CHILE", fuente="TEST",
        direccion="RUTA 5", comuna="COLINA", region="RM",
        latitud=COORD_AZA_COLINA.latitud, longitud=COORD_AZA_COLINA.longitud,
        estado_calidad=EstadoCalidad.CONFIRMADA,
    )


# --- 1. Cerrillos vs Santiago: niveles territoriales compatibles ---

def test_cerrillos_y_santiago_son_compatibles_misma_region():
    assert _comunas_territorialmente_compatibles("Cerrillos", "Santiago") is True
    assert _comunas_territorialmente_compatibles("Santiago", "Cerrillos") is True


def test_renca_maipu_quilicura_san_bernardo_tambien_compatibles_con_santiago():
    for comuna in ("Renca", "Maipú", "Quilicura", "San Bernardo"):
        assert _comunas_territorialmente_compatibles(comuna, "Santiago") is True, comuna


def test_vista_clara_cerrillos_ya_no_rechaza_pese_a_etiqueta_santiago(tmp_path):
    """Caso real 472238/472239 -- E2E completo: origen+destino confiables
    deben producir km/tiempo automáticamente, sin exigir confirmación
    humana, cuando la única discrepancia es el nivel territorial."""
    planta = _planta(tmp_path)
    consulta = "VISTA CLARA 2351 CERRILLOS, Chile"
    proveedor = ProveedorRutasSimulado(
        geocodificaciones={
            consulta: ResultadoGeocodificacion(
                EstadoRuta.REQUIERE_REVISION,
                (CandidatoGeocodificacion(Coordenadas(-70.71, -33.50), "Vista Clara 2351, Santiago, RM, Chile", 1.0, "Santiago", "Metropolitana"),),
                "RESUELTO",
            )
        },
        resultado_ruta=ResultadoRuta(EstadoRuta.RUTA_CALCULADA, 12.3, 18.0, "SINTETICO"),
    )
    resultado = calcular_ruta_con_planta_conocida(
        planta=planta, despachar_a_crudo="VISTA CLARA 2351 CERRILLOS", proveedor_rutas=proveedor,
    )
    assert resultado.estado_ruta == EstadoRuta.RUTA_CALCULADA.value
    assert resultado.distancia_km == "12.3"
    assert resultado.duracion_min == "18.0"
    assert resultado.motivo_ruta == ""


# --- 2. Vicuña Mackenna: calle, no comuna "Vicuña" ---

def test_vicuna_mackenna_nunca_se_lee_como_comuna_vicuna():
    texto = "VICUÑA MACKENNA 655"
    assert _comunas_explicitas(texto) == ()
    assert _comuna_documental_inequivoca(texto) == ""


def test_vicuna_mackenna_ya_no_bloquea_geocodificacion_valida(tmp_path):
    """Caso real 472037 -- E2E: sin ninguna comuna documental inequívoca
    que contradecir, el resultado del geocodificador se acepta tal cual."""
    planta = _planta(tmp_path)
    consulta = "VICUÑA MACKENNA 655, Chile"
    proveedor = ProveedorRutasSimulado(
        geocodificaciones={
            consulta: ResultadoGeocodificacion(
                EstadoRuta.REQUIERE_REVISION,
                (CandidatoGeocodificacion(Coordenadas(-70.62, -33.45), "Vicuña Mackenna, Santiago, RM, Chile", 1.0, "Santiago", "Metropolitana"),),
                "RESUELTO",
            )
        },
        resultado_ruta=ResultadoRuta(EstadoRuta.RUTA_CALCULADA, 8.1, 14.0, "SINTETICO"),
    )
    resultado = calcular_ruta_con_planta_conocida(
        planta=planta, despachar_a_crudo="VICUÑA MACKENNA 655", proveedor_rutas=proveedor,
    )
    assert resultado.estado_ruta == EstadoRuta.RUTA_CALCULADA.value
    assert resultado.distancia_km == "8.1"


# --- 3. San Bernardo vs Angol: contradicción real sigue bloqueada ---

def test_san_bernardo_vs_angol_sigue_siendo_contradiccion_real(tmp_path):
    """Caso real 460807 -- regiones distintas (Metropolitana vs La
    Araucanía), ninguna es "Santiago": nunca se debilita esta protección."""
    assert _comunas_territorialmente_compatibles("San Bernardo", "Angol") is False
    planta = _planta(tmp_path)
    consulta = "INTERIOR NUEVA 1148 SAN BERNARDO SAN BERNARDO, Chile"
    proveedor = ProveedorRutasSimulado(
        geocodificaciones={
            consulta: ResultadoGeocodificacion(
                EstadoRuta.REQUIERE_REVISION,
                (CandidatoGeocodificacion(Coordenadas(-72.71, -37.80), "Angol, La Araucanía, Chile", 1.0, "Angol", "La Araucanía"),),
                "RESUELTO",
            )
        },
        resultado_ruta=ResultadoRuta(EstadoRuta.RUTA_CALCULADA, 500.0, 400.0, "SINTETICO"),
    )
    resultado = calcular_ruta_con_planta_conocida(
        planta=planta, despachar_a_crudo="INTERIOR NUEVA 1148 SAN BERNARDO SAN BERNARDO", proveedor_rutas=proveedor,
    )
    assert resultado.estado_ruta == EstadoRuta.REQUIERE_REVISION.value
    assert "GEOCODIFICACION_CONTRADICE_COMUNA_DOCUMENTAL" in resultado.motivo_ruta
    assert resultado.distancia_km == ""  # nunca inventa una ruta de 500 km


# --- 4. Comuna compuesta: nunca truncar a la primera palabra ---

def test_comuna_compuesta_pedro_aguirre_cerda_no_se_trunca():
    texto = "AVENIDA CENTRAL 100 PEDRO AGUIRRE CERDA"
    assert _comunas_explicitas(texto) == ("Pedro Aguirre Cerda",)
    # Nunca detecta "Pedro" solo, ni ninguna sub-frase parcial.
    assert "Pedro" not in _comunas_explicitas(texto)


def test_comuna_compuesta_pedro_aguirre_cerda_valida_correctamente(tmp_path):
    planta = _planta(tmp_path)
    consulta = "AVENIDA CENTRAL 100 PEDRO AGUIRRE CERDA, Chile"
    proveedor = ProveedorRutasSimulado(
        geocodificaciones={
            consulta: ResultadoGeocodificacion(
                EstadoRuta.REQUIERE_REVISION,
                (CandidatoGeocodificacion(Coordenadas(-70.65, -33.48), "Avenida Central 100, Pedro Aguirre Cerda, RM, Chile", 1.0, "Pedro Aguirre Cerda", "Metropolitana"),),
                "RESUELTO",
            )
        },
        resultado_ruta=ResultadoRuta(EstadoRuta.RUTA_CALCULADA, 15.0, 22.0, "SINTETICO"),
    )
    resultado = calcular_ruta_con_planta_conocida(
        planta=planta, despachar_a_crudo="AVENIDA CENTRAL 100 PEDRO AGUIRRE CERDA", proveedor_rutas=proveedor,
    )
    assert resultado.estado_ruta == EstadoRuta.RUTA_CALCULADA.value


# --- 5/6. Dirección específica se conserva; etiqueta genérica nunca la reemplaza ---
# (cubierto en Bloque LOGÍSTICA L1, test_logistica_l1.py -- no se duplica aquí.)


# --- Región geocodificada fuera de Chile: contradicción real, incluso
#     sin evidencia documental de comuna con la que contrastar ---

def test_geocodificacion_fuera_de_chile_se_rechaza_aunque_no_haya_comuna_documental(tmp_path):
    """Caso real 472037, descubierto al corregir el falso positivo de
    "Vicuña Mackenna": sin comuna documental inequívoca con la que
    contradecir, el resultado del geocodificador se aceptaba tal cual --
    y en este caso real el proveedor devolvió una región de Argentina
    ("Córdoba"), nunca detectado porque nada validaba la región contra
    el universo cerrado de regiones chilenas. Protección independiente
    de la comuna documental -- corre siempre que se opera en Chile."""
    planta = _planta(tmp_path)
    consulta = "VICUÑA MACKENNA 655, Chile"
    proveedor = ProveedorRutasSimulado(
        geocodificaciones={
            consulta: ResultadoGeocodificacion(
                EstadoRuta.REQUIERE_REVISION,
                (CandidatoGeocodificacion(Coordenadas(-64.18, -31.42), "Vicuña Mackenna, Córdoba, Argentina", 0.9, "Córdoba", "Córdoba"),),
                "RESUELTO",
            )
        },
        resultado_ruta=ResultadoRuta(EstadoRuta.RUTA_CALCULADA, 781.5, 718.4, "SINTETICO"),
    )
    resultado = calcular_ruta_con_planta_conocida(
        planta=planta, despachar_a_crudo="VICUÑA MACKENNA 655", proveedor_rutas=proveedor,
    )
    assert resultado.estado_ruta != "RUTA_CALCULADA"
    assert "GEOCODIFICACION_FUERA_DE_CHILE" in resultado.motivo_ruta
    assert resultado.distancia_km == ""  # nunca inventa una ruta de 781 km a Argentina


# --- Controles adicionales: comuna real distinta a "Santiago", misma región ---

def test_dos_comunas_reales_de_la_misma_region_sin_santiago_siguen_siendo_contradiccion():
    """Control -- la compatibilidad es específica de "Santiago" como
    etiqueta de ciudad/metro, nunca una regla general de "misma región
    nunca contradice" (eso sí debilitaría la protección real)."""
    assert _comunas_territorialmente_compatibles("Renca", "Maipú") is False


def test_comuna_no_reconocida_nunca_se_declara_compatible():
    assert _comunas_territorialmente_compatibles("Cerrillos", "Comuna Inventada") is False
