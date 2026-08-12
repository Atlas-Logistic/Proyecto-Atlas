"""Bloque E2E R1.1: cierre del pipeline logístico real.

Casos reales que motivaron este bloque (bloque anterior, E2E R1):

- guía 463594: DESPACHAR A quedaba capturado como "PATENTE : BDFG50" --
  fallo de asociación semántica/layout, no de OCR.
- guía 463630: geocodificación de un DESPACHAR A real ("...CORONEL") no
  usaba contexto territorial y devolvía ambigüedad sin depurar.
- guía 463630: cliente quedaba ausente pese a que el documento trae
  nombre + RUT válido -- causa: la etiqueta "R.U.T." (con puntos) no
  calzaba con la exclusión "RUT" (sin puntos) del selector geométrico de
  cliente, compitiendo como candidato y produciendo ambigüedad falsa.
"""
from __future__ import annotations

import pytest

from atlas_core.extractor import (
    _despachar_a_lineal_contaminado,
    _extraer_asociaciones_geometricas,
    _extraer_despachar_a_geometrico,
    _es_etiqueta_rut,
)
from atlas_core.ocr import BloqueOCR
from atlas_core.rutas.destino_entrega import (
    _candidatos_con_soporte_textual,
    _misma_localidad,
    resolver_destino_entrega,
)
from atlas_core.rutas.modelos import (
    CandidatoGeocodificacion,
    Coordenadas,
    EstadoRuta,
    ResultadoGeocodificacion,
)
from atlas_core.rutas.proveedor import ProveedorRutasSimulado


def _bloque(texto, x1, y1, x2, y2, confianza=0.9):
    return BloqueOCR(texto, ((x1, y1), (x2, y1), (x2, y2), (x1, y2)), confianza)


# --- 1/2/3/4: DESPACHAR A geométrico ---


def test_despachar_a_no_absorbe_etiqueta_patente_geometrica():
    """Aunque PATENTE quede geométricamente más cerca que la dirección
    real, nunca se acepta como candidato -- es una etiqueta estructural."""
    bloques = [
        _bloque("DESPACHAR A", 10, 100, 90, 118),
        _bloque("PATENTE", 95, 100, 150, 118),  # etiqueta ajena, muy cerca
        _bloque("BDFG50", 155, 100, 210, 118),  # valor de esa etiqueta ajena
        _bloque("AV DEMO 123", 10, 125, 110, 143),  # dirección real, debajo
    ]
    resultado = _extraer_despachar_a_geometrico(bloques)
    assert resultado.get("valor") == "AV DEMO 123"


def test_despachar_a_multilinea_misma_direccion():
    bloques = [
        _bloque("DESPACHAR A", 10, 100, 90, 118),
        _bloque("AV DEMO 123", 10, 122, 110, 140),
        _bloque("CORONEL CHILE", 10, 143, 110, 161),
    ]
    resultado = _extraer_despachar_a_geometrico(bloques)
    assert resultado.get("valor") == "AV DEMO 123 CORONEL CHILE"


def test_despachar_a_corta_en_la_siguiente_etiqueta_estructural():
    """La cadena multilínea nunca cruza una etiqueta estructural (RUT,
    PATENTE, HORA, ...) -- se corta ahí, no sigue absorbiendo texto."""
    bloques = [
        _bloque("DESPACHAR A", 10, 100, 90, 118),
        _bloque("AV DEMO 123", 10, 122, 110, 140),
        _bloque("RUT", 10, 143, 40, 161),
        _bloque("11.111.111-1", 10, 164, 90, 182),
    ]
    resultado = _extraer_despachar_a_geometrico(bloques)
    assert resultado.get("valor") == "AV DEMO 123"


def test_despachar_a_geometrico_se_abstiene_ante_ambiguedad_real():
    """Dos etiquetas DESPACHAR A (documento con dos guías/layout raro) con
    candidatos igual de plausibles y distintos -- se abstiene."""
    bloques = [
        _bloque("DESPACHAR A", 10, 100, 90, 118),
        _bloque("AV UNO 123", 10, 122, 110, 140),
        _bloque("DESPACHAR A", 400, 100, 480, 118),
        _bloque("AV DOS 456", 400, 122, 500, 140),
    ]
    resultado = _extraer_despachar_a_geometrico(bloques)
    assert resultado == {}


def test_despachar_a_lineal_contaminado_detecta_etiqueta_ajena():
    assert _despachar_a_lineal_contaminado("PATENTE : BDFG50") is True
    assert _despachar_a_lineal_contaminado("RETIRA") is True
    assert _despachar_a_lineal_contaminado("AV. FORESTAL - MANZANA 1 1014 CORONEL") is False
    assert _despachar_a_lineal_contaminado("") is False


# --- 5/6/7/8: geocodificación territorial ---


def test_pais_operacion_se_envia_como_boundary_country():
    """`boundary.country` es un parámetro estructurado de Pelias, no un
    hardcode global -- solo se envía si quien construye el proveedor lo
    pide explícitamente."""
    from atlas_core.rutas.openrouteservice import OpenRouteService

    capturado = {}

    def transporte_falso(solicitud, timeout):
        capturado["url"] = solicitud.full_url
        raise TimeoutError("no importa, solo se audita la URL")

    proveedor_con_pais = OpenRouteService(api_key="x", transporte=transporte_falso, pais="CL")
    proveedor_con_pais.geocodificar("AV DEMO 123")
    assert "boundary.country=CL" in capturado["url"]

    proveedor_sin_pais = OpenRouteService(api_key="x", transporte=transporte_falso)
    proveedor_sin_pais.geocodificar("AV DEMO 123")
    assert "boundary.country" not in capturado["url"]


def test_caso_real_coronel_descarta_localidad_sin_soporte_textual():
    """Reproduce el caso real 463630: Pelias devuelve 4 candidatos para
    "...CORONEL" -- 2 "Coronel, Biobío" (variantes), 1 "Coronel, Maule" y
    1 "Ránquil, Biobío" (vecino administrativo sin ningún respaldo en el
    texto). "Ránquil" se descarta por no tener respaldo textual; los dos
    "Coronel" (nombres iguales, regiones distintas) siguen siendo una
    ambigüedad real -- correcto abstenerse, nunca elegir "el más
    conocido"."""
    texto = "AV. FORESTAL - MANZANA 1 1014 CORONEL CORONE"
    coronel_bio_bio = CandidatoGeocodificacion(
        Coordenadas(-73.163227, -37.002896), "Coronel, BI, Chile", 0.6, "Coronel", "Del Bio-Bio",
    )
    coronel_maule = CandidatoGeocodificacion(
        Coordenadas(-72.372437, -36.026889), "Coronel, ML, Chile", 0.6, "Coronel", "Del Maule",
    )
    ranquil = CandidatoGeocodificacion(
        Coordenadas(-72.539256, -36.602308), "Ránquil, BI, Chile", 0.6, "Ránquil", "Del Bio-Bio",
    )
    candidatos = (coronel_bio_bio, coronel_maule, ranquil)

    filtrados = _candidatos_con_soporte_textual(candidatos, texto)
    assert ranquil not in filtrados
    assert coronel_bio_bio in filtrados
    assert coronel_maule in filtrados

    consulta = f"{texto}, Chile"
    proveedor = ProveedorRutasSimulado(geocodificaciones={
        consulta: ResultadoGeocodificacion(EstadoRuta.RESULTADO_AMBIGUO, candidatos, "MULTIPLES_CANDIDATOS")
    })
    resultado = resolver_destino_entrega(texto, proveedor)
    # Ambigüedad real (dos lugares reales distintos llamados "Coronel") --
    # nunca se fuerza una elección para que la demo se vea completa.
    assert resultado.estado == "REVISAR"
    assert "MULTIPLES_UBICACIONES_DISPERSAS" in resultado.motivo


def test_candidatos_de_la_misma_localidad_se_fusionan_aunque_esten_a_2km():
    """Dos candidatos que Pelias nombra igual (misma localidad+región) no
    son ambigüedad real -- son el mismo lugar con coordenadas imprecisas
    (más lejos que `MARGEN_MISMO_LUGAR_KM`, que solo cubre variación de
    número de casa)."""
    a = CandidatoGeocodificacion(
        Coordenadas(-73.163227, -37.002896), "Coronel, BI, Chile", 0.6, "Coronel", "Del Bio-Bio",
    )
    b = CandidatoGeocodificacion(
        Coordenadas(-73.151, -37.019549), "Coronel, BI, Chile", 0.7, "Coronel", "Del Bio-Bio",
    )
    assert _misma_localidad(a, b) is True

    consulta = "CALLE DEMO CORONEL, Chile"
    proveedor = ProveedorRutasSimulado(
        geocodificaciones={
            consulta: ResultadoGeocodificacion(EstadoRuta.RESULTADO_AMBIGUO, (a, b), "MULTIPLES_CANDIDATOS")
        },
    )
    resultado = resolver_destino_entrega("CALLE DEMO CORONEL", proveedor)
    assert resultado.estado == "RESUELTO"
    assert resultado.confianza == 0.7  # el de mayor confianza entre "el mismo lugar"


def test_localidad_contradictoria_sin_respaldo_no_cambia_ambiguedad_real():
    """Si TODOS los candidatos tienen respaldo textual (o ninguno lo
    tiene), el filtro no reduce nada -- nunca inventa evidencia donde no
    la hay (mismo comportamiento que antes de este bloque)."""
    a = CandidatoGeocodificacion(Coordenadas(-70.686, -33.402), "Santa Isabel 585, Renca", 0.9)
    b = CandidatoGeocodificacion(Coordenadas(-72.59, -38.74), "Santa Isabel 585, Temuco", 0.85)
    filtrados = _candidatos_con_soporte_textual((a, b), "SANTA ISABEL 585")
    assert filtrados == (a, b)


# --- 9/10/11: cliente por RUT + regresión 463594/463630 (geometría sintética) ---


def test_etiqueta_rut_con_puntos_no_compite_como_nombre_de_cliente():
    """Caso real 463630: `_es_etiqueta_rut` reconoce "R.U.T" (con puntos)
    como etiqueta -- antes de este bloque solo se excluía la subcadena
    "RUT" (sin puntos), que nunca calzaba contra "R.U.T.", así que ese
    bloque competía como candidato de nombre de cliente."""
    assert _es_etiqueta_rut("R.U.T") is True
    assert _es_etiqueta_rut("RUT") is True
    assert _es_etiqueta_rut("R.U.T.") is True
    assert _es_etiqueta_rut("ATRUTINADO") is False


def test_cliente_se_resuelve_pese_a_etiqueta_rut_geometricamente_cercana():
    """Reproduce, con coordenadas sintéticas equivalentes a las reales de
    463630 (SEÑOR(ES) en y=407-418, R.U.T. justo debajo en y=419-433, el
    nombre real del cliente a la derecha en la misma fila), que el nombre
    gana sin que R.U.T. compita como candidato rival."""
    bloques = [
        _bloque("SEÑOR(ES)", 32, 407, 88, 418),
        _bloque("TORRES OCARANZA LTDA", 168, 407, 298, 417),
        _bloque("R.U.T", 30, 419, 63, 433),
        _bloque("SOLICITANTE", 384, 404, 451, 415),
        _bloque("TORRES OCARANZA LTDA CORONEL", 495, 403, 671, 415),
    ]
    resultado = _extraer_asociaciones_geometricas(bloques)
    assert resultado.get("cliente") == "TORRES OCARANZA LTDA"


def test_regresion_463594_despachar_a_no_es_patente():
    """Regresión focal (geometría real recuperada de la guía 463594): la
    etiqueta DESPACHAR A queda lejos, en otra columna, de "PATENTE :
    BDFG50" -- la dirección real está en otra posición de la imagen."""
    bloques = [
        _bloque("DESPACHAR A", 66, 1010, 160, 1024),
        _bloque("PATENTE", 240, 1010, 300, 1024),
        _bloque("BDFG50", 305, 1010, 360, 1024),
        _bloque("POETA PEDRO PRADO 1548", 66, 985, 260, 999),
        _bloque("METROPOLITANA METROPO", 66, 1000, 260, 1009),
    ]
    resultado = _extraer_despachar_a_geometrico(bloques)
    valor = resultado.get("valor", "")
    assert "PATENTE" not in valor.upper()
    assert "BDFG50" not in valor.upper()


def test_regresion_463630_cliente_no_queda_ausente():
    bloques = [
        _bloque("SEÑOR(ES)", 32, 407, 88, 418),
        _bloque("TORRES OCARANZA LTDA", 168, 407, 298, 417),
        _bloque("R.U.T", 30, 419, 63, 433),
    ]
    resultado = _extraer_asociaciones_geometricas(bloques)
    assert resultado.get("cliente") not in (None, "", "No encontrado")
