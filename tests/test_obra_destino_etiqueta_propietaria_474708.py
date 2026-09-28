"""Casos reales 474708 y 474699 -- degradación documental de OBRA DESTINO y
DESPACHAR A, diagnosticada etapa por etapa sobre la traza OCR persistida.

474708: el OCR SÍ leyó la obra ("CONSTRUMART SA CONCEDCION", misma fila y a
la derecha de la etiqueta OBRA DESTINO), pero con la foto inclinada el orden
de lectura dejó el valor de COMUNA ("QUELICURA", columna izquierda) entre
"OBRA DESTINO" y "COD DESTINATARIO"; el regex lineal lo tomó como obra y la
geometría nunca se consultó porque el campo ya "tenía" valor. La dirección
"AV. O HIGGENS, J61 TALCAHUANO TALCAHUAND" la produjo el propio proveedor OCR:
no se reconstruye.

474699: el proveedor OCR leyó la obra como "SALCMIHE KACH YA EAN NEPIARDO" y
el número 3396 como "NNA"; la asignación de campos fue correcta. Nada que
recuperar sin inventar: ni fuzzy ni conocimiento histórico.

Coordenadas congeladas de las trazas reales (sin depender de G:).
"""
from __future__ import annotations

from unittest.mock import Mock

from atlas_core import procesamiento_masivo
from atlas_core.extractor import (
    _extraer_asociaciones_geometricas,
    _extraer_despachar_a_geometrico,
    etiqueta_propietaria_valor_encabezado,
    extraer_datos,
)
from atlas_core.ocr import BloqueOCR
from atlas_core.procesamiento_masivo import procesar_archivo
from atlas_core.rutas.destino_entrega import resolver_direccion_canonica_mas_limpia


def _b(texto, x1, y1, x2, y2, conf=0.95):
    return BloqueOCR(texto=texto, bounding_box=((x1, y1), (x2, y1), (x2, y2), (x1, y2)), confianza=conf)


def _encabezado_474708(valor_obra=("CONSTRUMART SA CONCEDCION",), extra=()):
    """Encabezado real 474708 (PaddleOCR, foto inclinada): el valor de cada
    fila de la columna izquierda queda medio renglón más abajo que su
    etiqueta."""
    obra = [_b(texto, 488 + 120 * i, 341, 596 + 120 * i, 352) for i, texto in enumerate(valor_obra)]
    return [
        _b("FECHA DE EMISION", 125, 297, 199, 312),
        _b("SEÑOR(ES)", 123, 306, 169, 320),
        _b("26-09-2026", 242, 304, 292, 317),
        _b("R.U.T.", 123, 315, 149, 329),
        _b("CONSTRUNART SA", 243, 314, 310, 327),
        _b("ORDEN DE COMPRA", 392, 311, 463, 323),
        _b("4205270128/", 489, 313, 542, 324),
        _b("0030024233", 541, 315, 587, 325),
        _b("SOLICITANTE", 392, 321, 441, 331),
        _b("CONSTRUMART", 491, 325, 538, 332),
        _b("SA CONCEPCION", 539, 326, 595, 333),
        _b("GIRO", 122, 324, 148, 338),
        _b("96.511.460-2", 241, 323, 301, 336),
        _b("DIRECCION", 123, 334, 169, 347),
        _b("CONSTRUCCION OZ KBI", 242, 331, 329, 347),
        _b("TELEFONO", 390, 328, 433, 341),
        _b("992766139", 490, 333, 534, 343),
        _b("COMUNA", 122, 343, 161, 356),
        _b(": PANAMERICANA MORTE 9215", 238, 341, 346, 356),
        _b("OBRA DESTINO", 392, 338, 448, 350),
        _b("QUELICURA", 243, 350, 289, 363),
        _b("COD DESTINATARIO", 392, 347, 464, 360),
        *obra,
        _b("CIUDAD", 122, 352, 156, 365),
        _b(": SANTIASO", 238, 359, 285, 373),
        _b("HORA ENTRADA", 391, 356, 451, 368),
        _b("0002009624", 489, 351, 535, 361),
        *extra,
    ]


def _despacho_474708():
    return [
        _b("DESPACHAR A", 117, 626, 175, 636),
        _b("AV. O HIGGENS, J61 TALCAHUANO TALCAHUAND", 208, 627, 386, 639, 0.897),
        _b("RETIRA", 417, 629, 447, 639),
        _b("CARLOS SIMON", 466, 631, 519, 638),
        _b("RUT CHOFER", 117, 635, 170, 645),
        _b("15489424-1", 205, 636, 258, 646),
        _b("PATENTE", 416, 637, 454, 647),
        _b("BJCH72 CARRO:JE6159", 464, 637, 553, 648),
    ]


def _encabezado_474699():
    return [
        _b("SOLICITANTE", 473, 422, 554, 441),
        _b("SALCMON SACK SA SAW RAPOMARDO", 618, 417, 818, 435, 0.80),
        _b("R.U.T.", 64, 445, 101, 463),
        _b("1N0.970.000-0", 223, 446, 323, 459),
        _b("TELEFONO", 473, 437, 541, 457),
        _b("GIRO", 66, 461, 101, 479),
        _b(": VTA AL X MLNOR HAT C", 227, 461, 378, 475),
        _b("OBRA DESTINO", 473, 454, 565, 473),
        _b("SALCMIHE KACH YA EAN NEPIARDO", 615, 449, 817, 468, 0.767),
        _b("DIRECCION", 68, 477, 136, 494),
        _b("AV PNKSID EDO FREI MONTALVA 9770", 236, 474, 458, 491),
        _b("COD DESTINATARIO", 474, 469, 592, 489),
        _b("0082003280", 611, 468, 691, 484),
        _b("COMUNA", 70, 493, 125, 510),
        _b("QUILICURA", 239, 493, 305, 507),
    ]


# Líneas OCR reales (orden de lectura PaddleOCR) del encabezado de 474708.
LINEAS_474708 = [
    "GUIA DE DESPACHO", "ELECTRÓNICA", "N° 474708", "SEÑOR(ES)", "FECHA DE EMISION", "26-09-2026",
    "R.U.T.", "CONSTRUNART SA", "ORDEN DE COMPRA", "SOLICITANTE", "4205270128/", "GIRO", "96.511.460-2",
    "0030024233", "DIRECCION", "CONSTRUCCION OZ KBI", "TELEFONO", "992766139", "CONSTRUMART",
    "SA CONCEPCION", "COMUNA", ": PANAMERICANA MORTE 9215", "OBRA DESTINO", "QUELICURA",
    "COD DESTINATARIO", "CONSTRUMART SA CONCEDCION", "CIUDAD", ": SANTIASO", "HORA ENTRADA",
]


# ======================================================== 474708: diagnóstico


def test_474708_etapa_extraccion_lineal_toma_la_comuna_por_orden_de_lectura():
    # Reproduce la causa: el regex lineal captura lo que el OCR ordenó entre
    # "OBRA DESTINO" y "COD DESTINATARIO" -- la comuna.
    assert extraer_datos(LINEAS_474708).get("obra destino") == "QUELICURA"


def test_474708_la_geometria_ubica_la_obra_real_que_el_ocr_si_leyo():
    assert _extraer_asociaciones_geometricas(_encabezado_474708()).get("obra destino") == "CONSTRUMART SA CONCEDCION"


def test_474708_quelicura_pertenece_a_una_etiqueta_de_la_columna_izquierda():
    propietaria = etiqueta_propietaria_valor_encabezado(_encabezado_474708(), "QUELICURA")
    assert propietaria in {"COMUNA", "CIUDAD"}
    assert etiqueta_propietaria_valor_encabezado(_encabezado_474708(), "CONSTRUMART SA CONCEDCION") == "OBRA DESTINO"


def _procesar(tmp_path, monkeypatch, *, obra_lineal, bloques):
    datos = {
        "número de guía": "474708", "número de transporte": "0000360212",
        "cliente": "CONSTRUMART SA", "obra destino": obra_lineal, "chofer": "CARLOS SIMON",
        # Un campo ausente hace que el procesamiento lea los bloques OCR,
        # como ocurrió en la corrida real.
        "RUT del cliente": "No encontrado", "RUT del chofer": "15.489.424-1",
        "patente del tracto": "BJCH72", "patente del carro": "JE6159",
    }
    monkeypatch.setattr(procesamiento_masivo, "extraer_datos", Mock(return_value=datos))

    class _Proveedor:
        def leer_texto(self, ruta):
            return ["sin fecha reconocible"]

        def leer_bloques(self, ruta):
            return bloques

        def leer_focal(self, ruta, caja, allowlist):
            return {"lecturas": []}

    return procesar_archivo(tmp_path / "474708.jpg", proveedor=_Proveedor())


def test_474708_quelicura_no_termina_como_obra_y_se_usa_la_obra_documental(tmp_path, monkeypatch):
    resultado = _procesar(tmp_path, monkeypatch, obra_lineal="QUELICURA", bloques=_encabezado_474708())
    assert resultado["obra_destino"] != "QUELICURA"
    assert resultado["obra_destino"] == "CONSTRUMART SA CONCEDCION"
    assert "GEOMETRICO" in resultado["metodos_recuperacion_documento"]


def test_474708_obra_lineal_correcta_no_se_toca(tmp_path, monkeypatch):
    resultado = _procesar(
        tmp_path, monkeypatch, obra_lineal="CONSTRUMART SA CONCEDCION", bloques=_encabezado_474708()
    )
    assert resultado["obra_destino"] == "CONSTRUMART SA CONCEDCION"


def test_474708_numero_de_destino_no_se_sustituye_ni_se_inventa():
    despacho = _extraer_despachar_a_geometrico(_despacho_474708())
    assert despacho.get("valor") == "AV. O HIGGENS, J61 TALCAHUANO TALCAHUAND"
    # Sin evidencia documental compatible, ninguna vía de "dirección más
    # limpia" inventa el 361.
    assert resolver_direccion_canonica_mas_limpia(
        texto_objetivo="AV. O HIGGENS, J61 TALCAHUANO TALCAHUAND", candidatos=[]
    ) is None


# ======================================================== negativos


def test_comuna_sin_obra_destino_legible_queda_no_encontrado(tmp_path, monkeypatch):
    # OBRA DESTINO sin valor legible a su derecha: la comuna nunca pasa a obra.
    resultado = _procesar(tmp_path, monkeypatch, obra_lineal="QUELICURA", bloques=_encabezado_474708(valor_obra=()))
    assert resultado["obra_destino"] == "No encontrado"


def test_dos_candidatos_de_obra_se_abstiene(tmp_path, monkeypatch):
    bloques = _encabezado_474708(extra=(_b("OBRAS NORTE LIMITADA", 488, 336, 590, 347),))
    assert _extraer_asociaciones_geometricas(bloques).get("obra destino") is None
    resultado = _procesar(tmp_path, monkeypatch, obra_lineal="QUELICURA", bloques=bloques)
    assert resultado["obra_destino"] == "No encontrado"


def test_etiqueta_desplazada_o_ruido_no_permite_juzgar_y_conserva_lo_lineal():
    # Valor sin ninguna etiqueta a su izquierda en su fila: no se afirma dueño.
    bloques = [_b("OBRA DESTINO", 392, 338, 448, 350), _b("CONSTRUCTORA SUR", 20, 500, 120, 512)]
    assert etiqueta_propietaria_valor_encabezado(bloques, "CONSTRUCTORA SUR") is None
    # El mismo texto en dos filas con dueños distintos: ambiguo.
    ambiguo = _encabezado_474708(extra=(_b("QUELICURA", 489, 342, 530, 351),))
    assert etiqueta_propietaria_valor_encabezado(ambiguo, "QUELICURA") is None
    # Un valor unido de varias cajas no calza con ningún bloque completo.
    assert etiqueta_propietaria_valor_encabezado(_encabezado_474708(), "CONSTRUMART SA CONCEPCION") is None
    assert etiqueta_propietaria_valor_encabezado(_encabezado_474708(), "") is None


# ======================================================== 474699


def test_474699_obra_asignada_a_su_etiqueta_se_conserva_sin_fuzzy():
    bloques = _encabezado_474699()
    assert etiqueta_propietaria_valor_encabezado(bloques, "SALCMIHE KACH YA EAN NEPIARDO") == "OBRA DESTINO"
    assert _extraer_asociaciones_geometricas(bloques).get("obra destino") == "SALCMIHE KACH YA EAN NEPIARDO"


def test_474699_3396_se_conserva_cuando_la_evidencia_ocr_lo_contiene():
    bloques = [_b("DESPACHAR A", 85, 935, 170, 950), _b("CAMINO LOS PINOS 3396 SANTIAGO SAN BERNARDO", 218, 925, 512, 940)]
    assert _extraer_despachar_a_geometrico(bloques).get("valor") == "CAMINO LOS PINOS 3396 SANTIAGO SAN BERNARDO"


def test_474699_conocimiento_historico_no_inventa_3396():
    degradado = "CAMINO LS PINDS NNA ZANTIAGO SAN BERNARDO"
    bloques = [_b("DESPACHAR A", 85, 935, 170, 950), _b(degradado, 218, 925, 512, 940, 0.7)]
    assert _extraer_despachar_a_geometrico(bloques).get("valor") == degradado
    historico = ["CAMINO LOS PINOS 3396 SANTIAGO SAN BERNARDO"]
    assert resolver_direccion_canonica_mas_limpia(texto_objetivo=degradado, candidatos=historico) is None
    # Un número realmente ilegible tampoco se completa desde un pariente.
    assert resolver_direccion_canonica_mas_limpia(
        texto_objetivo="CAMINO LOS PINOS SANTIAGO SAN BERNARDO", candidatos=historico
    ) is None
