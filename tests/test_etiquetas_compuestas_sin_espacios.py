"""Etiquetas compuestas AZA leídas sin espacios por RapidOCR.

Casos reales 482740, 482908/482909, 483208 y 483223 (diagnóstico
pruebas/revision-13-decisiones-20261027): el OCR entregó "OBRADESTINO",
"CODDESTINATARIO", "DESPACHARA" y "RUTCHOFER". Los extractores geométricos
comparaban contra la forma espaciada, así que la obra y el código no se
anclaban, DESPACHAR A caía a la lectura lineal (contaminada con el RUT y
FECHA LLEGADA en 482740) y el corte lineal dejaba pegada la etiqueta
siguiente ("... LAMPA RUTCHOFER" en 483223). Coordenadas de las lecturas
reales; valores sintéticos.
"""
from __future__ import annotations

import pytest

from atlas_core.extractor import (
    _canonizar_etiqueta_compuesta,
    _extraer_asociaciones_geometricas,
    _extraer_chofer_geometrico,
    _extraer_despachar_a_geometrico,
    _extraer_patentes_geometrico,
    _extraer_rut_chofer_geometrico,
    _normalizar_bloques_geometricos,
)
from atlas_core.ocr import BloqueOCR
from atlas_core.rutas.destino_entrega import despachar_a_documental
from atlas_core.rutas.destino_estructurado import extraer_identificadores_destino

OBRA = "OBRA SINTETICA LTDA"
CODIGO = "0009990001"
DIRECCION = "CALLE SINTETICA 525 SANTIAGO"
DIRECCION_LAMPA = "AVENIDA SINTETICA 22650 SANTIAGO LAMPA"
CHOFER = "PEDRO SINTETICO"
RUT = "12345678-5"

FORMAS = {
    "OBRA DESTINO": ("OBRA DESTINO", "OBRADESTINO", "OBRADESTINO:"),
    "COD DESTINATARIO": ("COD DESTINATARIO", "CODDESTINATARIO"),
    "DESPACHAR A": ("DESPACHAR A", "DESPACHARA"),
    "RUT CHOFER": ("RUT CHOFER", "RUTCHOFER"),
}


def _bloque(texto, x1, y1, x2, y2):
    return BloqueOCR(texto=texto, bounding_box=((x1, y1), (x2, y1), (x2, y2), (x1, y2)), confianza=0.95)


def _encabezado_482740(obra, cod):
    # Columna derecha del membrete, filas apretadas: HORA ENTRADA queda a
    # 10 px del renglón de COD DESTINATARIO.
    return [
        _bloque("TELEFONO", 474, 420, 547, 444),
        _bloque("5550000", 629, 418, 697, 435),
        _bloque(obra, 476, 436, 574, 461),
        _bloque(OBRA, 630, 428, 785, 454),
        _bloque(cod, 476, 452, 601, 477),
        _bloque(CODIGO, 630, 449, 718, 469),
        _bloque("HORA ENTRADA", 476, 469, 579, 494),
        _bloque("07:22:00", 629, 462, 705, 487),
        _bloque("HORA SALIDA", 477, 487, 565, 509),
        _bloque("10:33:31", 630, 480, 703, 503),
    ]


def _pie_482740(despachar, rut_chofer):
    # Foto inclinada: la dirección queda por encima de su etiqueta y el RUT
    # del chofer por debajo, junto a FECHA LLEGADA de la columna derecha.
    return [
        _bloque("RETIRA", 531, 921, 583, 943),
        _bloque(CHOFER, 602, 917, 682, 939),
        _bloque(DIRECCION, 200, 933, 364, 962),
        _bloque("PATENTE", 532, 934, 593, 955),
        _bloque("XY1234CARRO:ZW5678", 590, 927, 749, 953),
        _bloque(despachar, 55, 944, 152, 970),
        _bloque(RUT, 202, 953, 282, 973),
        _bloque("FECHA", 534, 949, 580, 966),
        _bloque("LLEGADA", 535, 962, 594, 979),
        _bloque(rut_chofer, 57, 960, 143, 982),
        _bloque("FECHA SALIDA", 58, 979, 153, 1002),
    ]


def _pie_483223(despachar, rut_chofer):
    return [
        _bloque(despachar, 20, 1119, 113, 1139),
        _bloque(DIRECCION_LAMPA, 155, 1121, 460, 1142),
        _bloque(rut_chofer, 19, 1134, 104, 1154),
        _bloque("RETIRA", 521, 1126, 572, 1144),
        _bloque(CHOFER, 590, 1126, 687, 1150),
        _bloque(RUT, 157, 1139, 241, 1153),
        _bloque("PATENTE", 520, 1139, 585, 1159),
        _bloque("XY1234", 580, 1142, 670, 1164),
        _bloque("FECHA SALIDA", 19, 1157, 111, 1174),
        _bloque("FECHA", 521, 1156, 569, 1173),
        _bloque("LLEGADA", 519, 1168, 585, 1190),
    ]


# --- reconocimiento de la etiqueta ---


@pytest.mark.parametrize("canonica, formas", FORMAS.items())
def test_forma_compacta_y_espaciada_son_la_misma_etiqueta(canonica, formas):
    for forma in formas:
        assert _canonizar_etiqueta_compuesta(forma.strip(":")) == canonica


@pytest.mark.parametrize("compacta, canonica", (
    ("HORAENTRADA", "HORA ENTRADA"), ("HORASALIDA", "HORA SALIDA"), ("FECHASALIDA", "FECHA SALIDA"),
    ("FECHALLEGADA", "FECHA LLEGADA"), ("INDICADORTRASLADO", "INDICADOR TRASLADO"),
    ("ORDENDECOMPRA", "ORDEN DE COMPRA"), ("EMPRESATRANSPORTE", "EMPRESA TRANSPORTE"),
))
def test_etiquetas_vecinas_tambien_delimitan(compacta, canonica):
    assert _canonizar_etiqueta_compuesta(compacta) == canonica


@pytest.mark.parametrize("valor", (
    "DESPACHARA:CALLE 1", "OBRADESTINO CONSTRUCTORA SPA", "CONSTRUCTORA DESTINO SPA", "LA ESTERA 525",
    "RUTA 68 KM 20", "OBRA", "DESTINO", "RUT", "FECHADEEMISION", "NRO.TRANSPORTE", "XY1234CARRO:ZW5678",
))
def test_valores_y_etiquetas_con_reconocimiento_propio_no_se_tocan(valor):
    assert _canonizar_etiqueta_compuesta(valor) == valor


def test_el_texto_ocr_original_se_conserva():
    item = _normalizar_bloques_geometricos([_bloque("OBRADESTINO", 0, 0, 10, 10)])[0]
    assert item["texto"] == "OBRADESTINO"
    assert item["simple"] == "OBRA DESTINO"


# --- encabezado: obra y COD DESTINATARIO ---


@pytest.mark.parametrize("obra", FORMAS["OBRA DESTINO"])
@pytest.mark.parametrize("cod", FORMAS["COD DESTINATARIO"])
def test_obra_y_codigo_se_anclan_con_etiquetas_compactas(obra, cod):
    asociaciones = _extraer_asociaciones_geometricas(_encabezado_482740(obra, cod))
    assert asociaciones.get("obra destino") == OBRA
    assert asociaciones.get("cod destinatario") == CODIGO


def test_hora_de_la_fila_vecina_no_compite_como_codigo():
    bloques = [b for b in _encabezado_482740("OBRA DESTINO", "COD DESTINATARIO") if b.texto != CODIGO]
    assert "cod destinatario" not in _extraer_asociaciones_geometricas(bloques)


# --- pie: destino, chofer, RUT y patentes sin mezclarse ---


@pytest.mark.parametrize("despachar", FORMAS["DESPACHAR A"])
@pytest.mark.parametrize("rut_chofer", FORMAS["RUT CHOFER"])
def test_pie_inclinado_482740_separa_destino_rut_chofer_y_patentes(despachar, rut_chofer):
    bloques = _pie_482740(despachar, rut_chofer)
    assert _extraer_despachar_a_geometrico(bloques).get("valor") == DIRECCION
    assert _extraer_rut_chofer_geometrico(bloques).get("valor") == "12.345.678-5"
    assert _extraer_chofer_geometrico(bloques).get("valor") == CHOFER
    assert _extraer_patentes_geometrico(bloques) == {"tracto": "XY1234", "carro": "ZW5678"}


@pytest.mark.parametrize("despachar", FORMAS["DESPACHAR A"])
@pytest.mark.parametrize("rut_chofer", FORMAS["RUT CHOFER"])
def test_pie_483223_destino_sin_etiqueta_siguiente(despachar, rut_chofer):
    bloques = _pie_483223(despachar, rut_chofer)
    assert _extraer_despachar_a_geometrico(bloques).get("valor") == DIRECCION_LAMPA
    assert _extraer_rut_chofer_geometrico(bloques).get("valor") == "12.345.678-5"
    assert _extraer_chofer_geometrico(bloques).get("valor") == CHOFER
    assert _extraer_patentes_geometrico(bloques).get("tracto") == "XY1234"


def test_482740_destino_documental_prefiere_la_fila_impresa_a_la_lectura_contaminada():
    bloques = _pie_482740("DESPACHARA", "RUT CHOFER")
    # Orden de lectura real: la dirección antes de su etiqueta; tras ella,
    # el RUT del chofer y la FECHA LLEGADA de la columna vecina.
    lineas = [b.texto for b in bloques]
    assert despachar_a_documental(lineas, bloques, chofer_resuelto=CHOFER) == DIRECCION


# --- corte lineal de DESPACHAR A ---


@pytest.mark.parametrize("rut_chofer", FORMAS["RUT CHOFER"])
def test_corte_lineal_no_arrastra_la_etiqueta_siguiente(rut_chofer):
    texto = ["DESPACHARA", DIRECCION_LAMPA, rut_chofer, RUT]
    assert extraer_identificadores_destino(texto).despachar_a == DIRECCION_LAMPA


@pytest.mark.parametrize("retira", ("RETIRA", "RETRA"))
def test_corte_lineal_no_arrastra_retira_ni_chofer(retira):
    # Caso real 482813: RETIRA leído "RETRA", con el chofer y RUTCHOFER detrás.
    texto = ["DESPACHARA", DIRECCION, retira, CHOFER, "RUTCHOFER", RUT]
    assert extraer_identificadores_destino(texto).despachar_a == DIRECCION


@pytest.mark.parametrize("direccion", (
    "RUTA 68 KM 20 CURACAVI", "CAMINO LA OBRA 45 SANTIAGO", "PASAJE HORACIO 12 MAIPU", "AV FECHAS 10 RENCA",
    "AV RETRAMAL 300 LA FLORIDA",
))
def test_direcciones_legitimas_no_se_cortan(direccion):
    assert extraer_identificadores_destino(["DESPACHAR A", direccion, "RUT CHOFER", RUT]).despachar_a == direccion
