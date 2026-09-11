"""Regresiones generales para anclas AZA truncadas por el borde."""

from atlas_core.extractor import (
    _extraer_despachar_a_geometrico,
    detectar_captura_recortada_posible,
    extraer_datos,
)
from atlas_core.ocr import BloqueOCR
from atlas_core.procesamiento_masivo import COLUMNAS, extraer_peso_kg_etiquetado


def _bloque(texto, x, y, ancho=None, alto=18):
    ancho = ancho if ancho is not None else max(30, len(texto) * 8)
    return BloqueOCR(
        texto=texto,
        bounding_box=((x, y), (x + ancho, y), (x + ancho, y + alto), (x, y + alto)),
        confianza=0.95,
    )


def _zona_entrega(ancla):
    return [
        _bloque(ancla, 4, 100, 92),
        _bloque("VICUNA MACKENNA 655 SANTIAGO", 105, 100, 245),
        _bloque("RETIRA", 390, 100, 58),
        _bloque("LUIS REYES", 455, 100, 85),
        _bloque("PATENTE", 390, 124, 65),
    ]


def test_a_despachar_a_completo_conserva_comportamiento():
    resultado = _extraer_despachar_a_geometrico(_zona_entrega("DESPACHAR A"))
    assert resultado["valor"] == "VICUNA MACKENNA 655 SANTIAGO"
    assert "senal_calidad_captura" not in resultado


def test_b_espachar_a_en_borde_y_zona_esperada_recupera_destino():
    resultado = _extraer_despachar_a_geometrico(_zona_entrega("ESPACHAR A"))
    assert resultado == {
        "valor": "VICUNA MACKENNA 655 SANTIAGO",
        "senal_calidad_captura": "CAPTURA_RECORTADA_POSIBLE",
    }


def test_c_fragmentos_ambiguos_se_abstienen():
    for fragmento in ("AR A", "A"):
        assert _extraer_despachar_a_geometrico(_zona_entrega(fragmento)) == {}


def test_d_peso_kg_completo_permanece_intacto():
    assert extraer_peso_kg_etiquetado(["PESO KG", "9.231,00"]) == "9231"


def test_e_eso_kg_truncado_se_recupera():
    assert extraer_peso_kg_etiquetado(["ESO KG", "9.231,00"]) == "9231"


def test_f_etiqueta_ausente_sin_evidencia_de_borde_no_marca_recorte():
    bloques = [_bloque("CALLE DEMO 123", 140, 100), _bloque("RETIRA", 390, 100)]
    assert detectar_captura_recortada_posible(bloques) is False


def test_g_recorte_detectado_sin_valor_no_inventa_destino():
    bloques = [_bloque("ESPACHAR A", 3, 100, 90), _bloque("RETIRA", 390, 100)]
    assert detectar_captura_recortada_posible(bloques) is True
    assert _extraer_despachar_a_geometrico(bloques) == {}


def test_g_recorte_severo_requiere_dos_fragmentos_y_no_los_usa_como_ancla():
    uno_solo = [_bloque("AR A", 2, 100, 35), _bloque("CALLE DEMO 123", 105, 100)]
    recorte_fuerte = uno_solo + [_bloque("UT CHOFER", 2, 124, 70)]
    assert detectar_captura_recortada_posible(uno_solo) is False
    assert detectar_captura_recortada_posible(recorte_fuerte) is True
    assert _extraer_despachar_a_geometrico(recorte_fuerte) == {}


def test_espachar_a_fuera_del_borde_no_es_ancla():
    bloques = _zona_entrega("ESPACHAR A")
    desplazados = [
        _bloque(b.texto, 80 if i == 0 else b.bounding_box[0][0], b.bounding_box[0][1],
                b.bounding_box[1][0] - b.bounding_box[0][0])
        for i, b in enumerate(bloques)
    ]
    assert _extraer_despachar_a_geometrico(desplazados) == {}
    assert detectar_captura_recortada_posible(desplazados) is False


def test_h_extraccion_normal_no_regresa_y_columna_de_calidad_es_explicita():
    datos = extraer_datos([
        "GUIA DE DESPACHO ELECTRONICA N 123456",
        "OBRA DESTINO OBRA SEGURA SA COD DESTINATARIO 0001",
        "PESO KG 12.345,00",
    ])
    assert datos["número de guía"] == "123456"
    assert datos["obra destino"] == "OBRA SEGURA SA"
    assert datos["peso"] == "12.345,00"
    assert "senal_calidad_captura" in COLUMNAS


def test_peso_bruto_menos_tara_documentado_pero_no_usado_como_nueva_regla():
    bruto, tara = 39359, 15240
    assert bruto - tara == 24119
    # Sin ancla PESO KG el extractor conserva la regla vigente; este bloque
    # no agrega una derivacion aritmetica del peso neto.
    assert extraer_peso_kg_etiquetado(["Tara 15.240,000 Peso Bruto 39.359,000"]) == "No encontrado"
