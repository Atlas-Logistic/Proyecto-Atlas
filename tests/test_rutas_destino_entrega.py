"""Bloque ENTREGAS E1: DESPACHAR A como fuente autoritativa de la ruta.

Regla de negocio (Javier, prevalece sobre D2/D3/D3.1): la ruta debe ser
PLANTA ORIGEN -> DESPACHAR A, nunca PLANTA ORIGEN -> dirección del
cliente/sitio registrado. Ante ambigüedad de geocodificación, abstención
(REVISAR) -- nunca se elige el candidato más cercano a una planta AZA.
"""
from datetime import datetime, timezone

import pytest

from atlas_core.catalogo_plantas import CatalogoPlantas, EstadoCalidad
from atlas_core.rutas.destino_entrega import (
    ESTADO_REVISAR,
    ESTADO_RESUELTO,
    ESTADO_SIN_DATO,
    _comuna_documental_inequivoca,
    _comunas_explicitas,
    calcular_ruta_entrega_para_viaje,
    resolver_destino_entrega,
)
from atlas_core.rutas.modelos import (
    CandidatoGeocodificacion,
    Coordenadas,
    EstadoRuta,
    ResultadoGeocodificacion,
    ResultadoRuta,
)
from atlas_core.rutas.proveedor import ProveedorRutasSimulado

COORD_AZA_RENCA = Coordenadas(-70.685226, -33.401595)
COORD_MEJILLONES = Coordenadas(-70.4500, -23.0985)  # real, Región de Antofagasta

TEXTOS_ENCABEZADO_RENCA = "GUIA DESPACHO PLANTA ORIGEN RENCA ACEROS AZA S A CASA MATRIZ PLANTA RENCA LA UNION 3070 RENCA SANTIAGO CHILE"


@pytest.fixture
def planta_renca(tmp_path):
    plantas_repo = CatalogoPlantas(tmp_path / "plantas.json")
    planta = plantas_repo.crear(
        nombre="AZA RENCA", pais="CHILE", fuente="PRUEBA",
        direccion="LA UNION 3070", comuna="RENCA", region="RM",
        latitud=COORD_AZA_RENCA.latitud, longitud=COORD_AZA_RENCA.longitud,
        estado_calidad=EstadoCalidad.CONFIRMADA,
    )
    return plantas_repo.listar(), planta


# --- resolver_destino_entrega: niveles básicos ---

def test_sin_despachar_a_es_sin_dato():
    proveedor = ProveedorRutasSimulado()
    resultado = resolver_destino_entrega("", proveedor)
    assert resultado.estado == ESTADO_SIN_DATO
    assert proveedor.llamadas_geocodificacion == 0


def test_candidato_unico_con_confianza_suficiente_resuelve():
    consulta = "AV. ALMTE. LATORRE 843, MEJILLONES, Chile"
    proveedor = ProveedorRutasSimulado(geocodificaciones={
        consulta: ResultadoGeocodificacion(
            EstadoRuta.REQUIERE_REVISION,
            (CandidatoGeocodificacion(COORD_MEJILLONES, "Av. Almte. Latorre 843, Mejillones", 0.8),),
            "REQUIERE_CONFIRMACION_HUMANA",
        )
    })
    resultado = resolver_destino_entrega("AV. ALMTE. LATORRE 843, MEJILLONES", proveedor)
    assert resultado.estado == ESTADO_RESUELTO
    assert resultado.coordenadas == COORD_MEJILLONES
    assert resultado.confianza == 0.8
    assert resultado.despachar_a_crudo == "AV. ALMTE. LATORRE 843, MEJILLONES"


def test_candidato_unico_con_confianza_insuficiente_revisa():
    consulta = "CALLE AMBIGUA 100, Chile"
    proveedor = ProveedorRutasSimulado(geocodificaciones={
        consulta: ResultadoGeocodificacion(
            EstadoRuta.REQUIERE_REVISION,
            (CandidatoGeocodificacion(Coordenadas(-70.0, -33.0), "Calle Ambigua 100", 0.2),),
            "REQUIERE_CONFIRMACION_HUMANA",
        )
    })
    resultado = resolver_destino_entrega("CALLE AMBIGUA 100", proveedor)
    assert resultado.estado == ESTADO_REVISAR
    assert resultado.motivo == "CONFIANZA_INSUFICIENTE"


def test_multiples_candidatos_nunca_elige_el_mas_cercano_a_aza():
    # Un candidato está a metros de AZA Renca, el otro a cientos de km --
    # el resolver NUNCA debe preferir el cercano; debe abstenerse.
    consulta = "SANTA ISABEL 585, Chile"
    cercano_a_aza = CandidatoGeocodificacion(
        Coordenadas(-70.686, -33.402), "Santa Isabel 585, Renca", 0.9
    )
    lejano = CandidatoGeocodificacion(
        Coordenadas(-72.59, -38.74), "Santa Isabel 585, Temuco", 0.85
    )
    proveedor = ProveedorRutasSimulado(geocodificaciones={
        consulta: ResultadoGeocodificacion(
            EstadoRuta.RESULTADO_AMBIGUO, (cercano_a_aza, lejano), "MULTIPLES_CANDIDATOS"
        )
    })
    resultado = resolver_destino_entrega("SANTA ISABEL 585", proveedor)
    assert resultado.estado == ESTADO_REVISAR
    assert resultado.coordenadas is None  # no elige ninguno de los dos
    assert "MULTIPLES_UBICACIONES_DISPERSAS" in resultado.motivo


def test_candidatos_dispersos_pero_cercanos_no_son_ambiguedad_real():
    # Caso real (Bloque E1): "AV. ALMTE. LATORRE 843, MEJILLONES" devolvió
    # 5 candidatos, todos confianza 1.0, todos en la misma cuadra de la
    # misma calle en Mejillones (Pelias no calzó el número exacto) --
    # eso NO es la ambigüedad de calles homónimas que hay que evitar.
    consulta = "AV. ALMTE. LATORRE 843 MEJILLONES, Chile"
    candidatos = (
        CandidatoGeocodificacion(Coordenadas(-70.445403, -23.100131), "898 Av. Latorre, Mejillones", 1.0),
        CandidatoGeocodificacion(Coordenadas(-70.447422, -23.100201), "792 Av. Latorre, Mejillones", 1.0),
        CandidatoGeocodificacion(Coordenadas(-70.446343, -23.100161), "866 Av. Latorre, Mejillones", 1.0),
        CandidatoGeocodificacion(Coordenadas(-70.448719, -23.100073), "637 Av. Latorre, Mejillones", 1.0),
        CandidatoGeocodificacion(Coordenadas(-70.448993, -23.100072), "611 Av. Latorre, Mejillones", 1.0),
    )
    proveedor = ProveedorRutasSimulado(geocodificaciones={
        consulta: ResultadoGeocodificacion(EstadoRuta.RESULTADO_AMBIGUO, candidatos, "MULTIPLES_CANDIDATOS")
    })
    resultado = resolver_destino_entrega("AV. ALMTE. LATORRE 843 MEJILLONES", proveedor)
    assert resultado.estado == ESTADO_RESUELTO
    assert resultado.coordenadas == candidatos[0].coordenadas
    assert resultado.confianza == 1.0


def test_fallo_de_geocodificacion_preserva_texto_crudo_y_explica():
    proveedor = ProveedorRutasSimulado(geocodificaciones={
        "DIRECCION INEXISTENTE, Chile": ResultadoGeocodificacion(
            EstadoRuta.DIRECCION_NO_ENCONTRADA, motivo="SIN_CANDIDATOS"
        )
    })
    resultado = resolver_destino_entrega("DIRECCION INEXISTENTE", proveedor)
    assert resultado.estado == ESTADO_REVISAR
    assert resultado.despachar_a_crudo == "DIRECCION INEXISTENTE"
    assert "DIRECCION_NO_ENCONTRADA" in resultado.motivo


# --- calcular_ruta_entrega_para_viaje: orquestación end-to-end ---

def test_calcula_ruta_real_planta_a_despachar_a(planta_renca):
    plantas, _ = planta_renca
    consulta = "AV. ALMTE. LATORRE 843, MEJILLONES, Chile"
    proveedor = ProveedorRutasSimulado(
        geocodificaciones={
            consulta: ResultadoGeocodificacion(
                EstadoRuta.REQUIERE_REVISION,
                (CandidatoGeocodificacion(COORD_MEJILLONES, "Av. Almte. Latorre 843, Mejillones", 0.8),),
                "REQUIERE_CONFIRMACION_HUMANA",
            )
        },
        resultado_ruta=ResultadoRuta(EstadoRuta.RUTA_CALCULADA, 1387.4, 960.2, "SINTETICO"),
    )
    resultado = calcular_ruta_entrega_para_viaje(
        despachar_a_crudo="AV. ALMTE. LATORRE 843, MEJILLONES",
        patente=None, instante_salida=None, plantas=plantas,
        proveedor_posicion=None, proveedor_rutas=proveedor,
        textos_documento=[TEXTOS_ENCABEZADO_RENCA],
    )
    assert resultado.estado_ruta == EstadoRuta.RUTA_CALCULADA.value
    assert resultado.planta_origen_nombre == "AZA RENCA"
    assert resultado.despachar_a_crudo == "AV. ALMTE. LATORRE 843, MEJILLONES"
    assert resultado.distancia_km == "1387.4"
    assert proveedor.llamadas_ruta == 1


def test_origen_no_determinado_nunca_geocodifica(planta_renca):
    plantas, _ = planta_renca
    proveedor = ProveedorRutasSimulado()
    resultado = calcular_ruta_entrega_para_viaje(
        despachar_a_crudo="AV. ALMTE. LATORRE 843, MEJILLONES",
        patente=None, instante_salida=None, plantas=plantas,
        proveedor_posicion=None, proveedor_rutas=proveedor,
        textos_documento=["GUIA SIN ENCABEZADO RECONOCIBLE"],
    )
    assert resultado.estado_ruta == EstadoRuta.ORIGEN_NO_DETERMINADO.value
    assert proveedor.llamadas_geocodificacion == 0
    assert proveedor.llamadas_ruta == 0


def test_entrega_ambigua_nunca_calcula_ruta(planta_renca):
    plantas, _ = planta_renca
    consulta = "SANTA ISABEL 585, Chile"
    proveedor = ProveedorRutasSimulado(geocodificaciones={
        consulta: ResultadoGeocodificacion(
            EstadoRuta.RESULTADO_AMBIGUO,
            (
                CandidatoGeocodificacion(Coordenadas(-70.686, -33.402), "Santa Isabel 585, Renca", 0.9),
                CandidatoGeocodificacion(Coordenadas(-72.59, -38.74), "Santa Isabel 585, Temuco", 0.85),
            ),
            "MULTIPLES_CANDIDATOS",
        )
    })
    resultado = calcular_ruta_entrega_para_viaje(
        despachar_a_crudo="SANTA ISABEL 585",
        patente=None, instante_salida=None, plantas=plantas,
        proveedor_posicion=None, proveedor_rutas=proveedor,
        textos_documento=[TEXTOS_ENCABEZADO_RENCA],
    )
    assert resultado.estado_ruta == EstadoRuta.REQUIERE_REVISION.value
    assert "MULTIPLES_UBICACIONES_DISPERSAS" in resultado.motivo_ruta
    assert proveedor.llamadas_ruta == 0


def test_destino_rechazado_por_confianza_no_expone_etiqueta_ni_localidad(planta_renca):
    """Bloque F (R4.10), caso real 472008: un candidato a confianza
    insuficiente (0.1, "Chile" sin localidad/región) no debe exponer su
    etiqueta como si fuera el destino operacional resuelto -- coordenadas/
    confianza sí se conservan (evidencia técnica), pero
    direccion_entrega_geocodificada/localidad/región quedan vacías."""
    plantas, _ = planta_renca
    consulta = "DIRECCION ILEGIBLE 999, Chile"
    proveedor = ProveedorRutasSimulado(geocodificaciones={
        consulta: ResultadoGeocodificacion(
            EstadoRuta.REQUIERE_REVISION,
            (CandidatoGeocodificacion(Coordenadas(-72.27, -38.17), "Chile", 0.1, localidad="", region=""),),
            "REQUIERE_CONFIRMACION_HUMANA",
        )
    })
    resultado = calcular_ruta_entrega_para_viaje(
        despachar_a_crudo="DIRECCION ILEGIBLE 999",
        patente=None, instante_salida=None, plantas=plantas,
        proveedor_posicion=None, proveedor_rutas=proveedor,
        textos_documento=[TEXTOS_ENCABEZADO_RENCA],
    )
    assert resultado.estado_ruta == EstadoRuta.REQUIERE_REVISION.value
    assert resultado.motivo_ruta == "CONFIANZA_INSUFICIENTE"
    assert resultado.direccion_entrega_geocodificada == ""
    assert resultado.localidad_entrega == ""
    assert resultado.region_entrega == ""
    # Evidencia técnica de auditoría -- se conserva.
    assert resultado.confianza_geocodificacion == "0.1"
    assert resultado.longitud_entrega and resultado.latitud_entrega


def test_comuna_documental_inequivoca_encuentra_una_comuna_repetida():
    """Caso real 460807: "SAN BERNARDO" aparece dos veces (misma comuna) --
    una sola comuna DISTINTA, evidencia inequívoca."""
    texto = "INTERIOR NUEVA O1148 SAN BERNARDO SAN BERNAR"
    assert _comunas_explicitas(texto) == ("San Bernardo",)
    assert _comuna_documental_inequivoca(texto) == "San Bernardo"


def test_comuna_documental_inequivoca_ya_no_confunde_calle_con_comuna():
    """Bloque TERRITORIAL T1 -- caso real 472002: "Galvarino" es aquí el
    nombre de la CALLE (antes del número), nunca una comuna documental --
    aunque también exista una comuna real con ese nombre en otra región,
    su posición ANTES del número la excluye por construcción (formato
    chileno convencional CALLE NÚMERO COMUNA). "Quilicura" (después del
    número) es la única comuna real candidata -- ya no hay ambigüedad
    que forzara la abstención de antes; se resuelve directo."""
    texto = "GALVARINO 8501 QUILICURA"
    comunas = _comunas_explicitas(texto)
    assert comunas == ("Quilicura",)
    assert _comuna_documental_inequivoca(texto) == "Quilicura"


def test_comuna_documental_inequivoca_vacia_sin_ninguna_comuna_reconocida():
    assert _comuna_documental_inequivoca("DIRECCION SIN NINGUNA COMUNA VALIDA 123") == ""


def test_caso_real_464170_apunta_a_mejillones_no_a_galvarino(planta_renca):
    """Caso real que motivó la regla de negocio: cliente EBEMA SA,
    DIRECCION=GALVARINO 8501/QUILICURA, pero DESPACHAR A=AV. ALMTE.
    LATORRE 843, MEJILLONES. La ruta debe terminar en Mejillones --
    Galvarino 8501 no debe usarse como destino de esta ruta."""
    plantas, _ = planta_renca
    despachar_a_real = "AV. ALMTE. LATORRE 843 MEJILLONES MEJILLONES"
    consulta = f"{despachar_a_real}, Chile"
    proveedor = ProveedorRutasSimulado(
        geocodificaciones={
            consulta: ResultadoGeocodificacion(
                EstadoRuta.REQUIERE_REVISION,
                (CandidatoGeocodificacion(COORD_MEJILLONES, "Av. Almte. Latorre 843, Mejillones", 0.75),),
                "REQUIERE_CONFIRMACION_HUMANA",
            )
        },
        resultado_ruta=ResultadoRuta(EstadoRuta.RUTA_CALCULADA, 1387.4, 960.2, "SINTETICO"),
    )
    resultado = calcular_ruta_entrega_para_viaje(
        despachar_a_crudo=despachar_a_real,
        patente=None, instante_salida=None, plantas=plantas,
        proveedor_posicion=None, proveedor_rutas=proveedor,
        textos_documento=[
            TEXTOS_ENCABEZADO_RENCA,
            "SEÑOR(ES) : EBEMA SA DIRECCION : GALVARINO 8501 COMUNA QUILICURA",
        ],
    )
    assert resultado.estado_ruta == EstadoRuta.RUTA_CALCULADA.value
    assert resultado.latitud_entrega == str(COORD_MEJILLONES.latitud)
    assert resultado.longitud_entrega == str(COORD_MEJILLONES.longitud)
    # Nunca las coordenadas de Galvarino 8501 (Quilicura, RM).
    assert resultado.latitud_entrega != "-33.370934"
