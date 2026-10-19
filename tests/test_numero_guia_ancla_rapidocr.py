"""Regresión: RapidOCR pega "GUIA DE DESPACHO" como "GUIA DEDESPACHO".

Casos reales 482399 (envío 9d487020) y 482483 (envío 1162388b), Mobile,
ingresados por el PULL con RapidOCR el 2026-10-19 con número de guía
"No encontrado". Diagnóstico de sólo lectura sobre copias de las fotos: el
folio sí se leyó ("N482399"/"N482483", marcador absorbido ya soportado),
pero sin reconocer el ancla el fallback geométrico se abstenía. Los bloques
de abajo son los reales de RapidOCR (texto, polígono y confianza), recortados
a la zona del encabezado.
"""
from __future__ import annotations

import pytest

from atlas_core.extractor import _es_ancla_guia_despacho, _extraer_numero_guia_geometrico
from atlas_core.ocr import BloqueOCR


def _real(texto, caja, conf):
    return BloqueOCR(texto=texto, bounding_box=tuple(caja), confianza=conf)


def _encabezado_real_482399():
    return [
        _real("ACEROSAZAS.A", [(388, 842), (843, 846), (843, 898), (388, 894)], 0.979),
        _real("GIRO:FUNDICION-LAMINACION-EXPORTACION", [(382, 886), (1167, 890), (1167, 935), (382, 931)], 0.9713),
        _real("R.U.T.:92.176.000-0", [(1485, 869), (1938, 863), (1938, 914), (1485, 919)], 0.9682),
        _real("CASAMATRIZPLANTARENCA", [(378, 925), (773, 927), (773, 966), (378, 964)], 0.9792),
        _real("LA UNION3070.RENCASANTIAGO,CHILE.CODPOSTAL7464522",
              [(378, 958), (1215, 960), (1215, 999), (378, 997)], 0.9549),
        _real("GUIA DEDESPACHO", [(1470, 948), (1956, 939), (1956, 991), (1470, 1001)], 0.9587),
        _real("FONO.(56)226779100 www.aza.cl", [(382, 993), (831, 993), (831, 1026), (382, 1026)], 0.8908),
        _real("ELECTRONICA", [(1539, 1001), (1890, 995), (1890, 1047), (1539, 1053)], 0.9926),
        _real("SuursTemucoCalMiano3605.Baiodstril.CiudadTemucoFon452252103",
              [(69, 1051), (1180, 1061), (1180, 1113), (69, 1103)], 0.7846),
        _real("SucursalTacahuano.JaimieRepullo 1014Caudsd Talcahuano",
              [(71, 1086), (833, 1094), (833, 1140), (71, 1132)], 0.8799),
        _real("N482399", [(1599, 1080), (1832, 1076), (1832, 1128), (1599, 1132)], 0.996),
        _real("Suursal Colna.PanamericanaNorteKM.18Cona,Santago.Fono (56)226779501",
              [(71, 1117), (1155, 1121), (1155, 1171), (71, 1167)], 0.8065),
        _real("S.II.-SANTIAGO PONIENTE", [(1537, 1181), (1911, 1177), (1911, 1215), (1537, 1219)], 0.8946),
        _real("Codigo Cliente:0001006226", [(87, 1248), (557, 1260), (557, 1305), (87, 1293)], 0.9507),
        _real("Numero SAP", [(1518, 1245), (1705, 1245), (1705, 1283), (1518, 1283)], 0.9591),
        _real("0080558925", [(1768, 1243), (1983, 1239), (1983, 1277), (1768, 1281)], 0.9846),
    ]


def _encabezado_real_482483():
    return [
        _real("ACEROS AZA S.A", [(521, 567), (928, 563), (928, 610), (521, 614)], 0.9286),
        _real("GIRO:FUNDICION-LAMINACION EXPORTACION", [(511, 606), (1225, 600), (1225, 646), (511, 652)], 0.977),
        _real("R.U.T.:92.176.000-0", [(1529, 588), (1946, 588), (1946, 627), (1529, 627)], 0.9825),
        _real("CASAMATRIZPLANTARENCA", [(513, 645), (862, 645), (862, 675), (513, 675)], 0.9803),
        _real("Sosienil0", [(326, 666), (480, 666), (480, 693), (326, 693)], 0.5668),
        _real("LAUNION3070.RENCASANTIAGO,CHILE.CODPOSTAL7464522,",
              [(511, 672), (1271, 672), (1271, 705), (511, 705)], 0.9534),
        _real("GUIA DEDESPACHO", [(1506, 658), (1958, 658), (1958, 703), (1506, 703)], 0.9646),
        _real("FONO.(56)226779100 www.aza.cl", [(507, 697), (914, 699), (914, 732), (507, 730)], 0.897),
        _real("ELECTRONICA", [(1568, 708), (1894, 708), (1894, 759), (1568, 759)], 0.9932),
        _real("SucursalAntofagusta.Calle HectorGomezCobo21.0oosectorNudoUrbe.CuidadAnlofagasta.",
              [(241, 734), (1281, 732), (1281, 776), (241, 778)], 0.8736),
        _real("SucursalTemuco:CallMilano03605.Beriolndustrial.CiudadTeuco.Fono452252103",
              [(241, 761), (1232, 761), (1232, 805), (241, 805)], 0.8085),
        _real("Sucursal Talcahuano.Jaine Repullo1014.Ciudad Talcahuana",
              [(245, 794), (910, 794), (910, 826), (245, 826)], 0.8886),
        _real("N482483", [(1618, 784), (1840, 788), (1840, 838), (1618, 834)], 0.9947),
        _real("Sucursal Colna:Panamericana Norte KM.18-Colina,Santiago.Fono.(56)226779501",
              [(239, 817), (1205, 821), (1205, 859), (239, 855)], 0.8965),
        _real("S..I.-SANTIAGOPONIENTE", [(1560, 879), (1909, 883), (1909, 921), (1560, 917)], 0.9407),
        _real("CodigoCliente:0001000197", [(241, 929), (654, 937), (654, 975), (241, 968)], 0.9609),
        _real("Numero SAP", [(1537, 939), (1714, 943), (1714, 981), (1537, 977)], 0.9576),
        _real("0080560224", [(1768, 948), (1971, 948), (1971, 981), (1768, 981)], 0.9804),
        _real("Nro.TRANSPORTE", [(1209, 1252), (1468, 1256), (1468, 1295), (1209, 1291)], 0.9763),
        _real("0000364731", [(1562, 1264), (1763, 1264), (1763, 1295), (1562, 1295)], 0.9804),
    ]


def test_regresion_482399_rapidocr_ancla_pegada_recupera_folio():
    assert _extraer_numero_guia_geometrico(_encabezado_real_482399()) == {"valor": "482399"}


def test_regresion_482483_rapidocr_ancla_pegada_recupera_folio():
    assert _extraer_numero_guia_geometrico(_encabezado_real_482483()) == {"valor": "482483"}


@pytest.mark.parametrize("texto", [
    "GUIA DE DESPACHO", "GUIA DEDESPACHO", "GUIADE DESPACHO", "GUIADEDESPACHO",
    "GUIA DE DESPAC", "GUIA DEDESPAC", "GUIADEDESP",
])
def test_ancla_acepta_palabras_pegadas_con_la_misma_tolerancia(texto):
    assert _es_ancla_guia_despacho(texto)


@pytest.mark.parametrize("texto", [
    "GUIA DE", "GUIADE", "GUIA DEDES", "GUIADEDES", "DESPACHO", "DESPACHAR A", "GUIA DE DOCUMENTO",
])
def test_ancla_sigue_rechazando_fragmentos_cortos_o_ajenos(texto):
    assert not _es_ancla_guia_despacho(texto)


def test_sin_ancla_el_folio_pegado_no_se_acepta():
    bloques = [b for b in _encabezado_real_482399() if b.texto != "GUIA DEDESPACHO"]
    assert _extraer_numero_guia_geometrico(bloques) == {}


def test_numero_marcado_fuera_del_encabezado_no_se_acepta():
    # Mismo formato de folio, pero lejos del encabezado (zona del cuerpo).
    bloques = [b for b in _encabezado_real_482399() if b.texto != "N482399"]
    bloques.append(_real("N475724", [(1599, 2600), (1832, 2600), (1832, 2652), (1599, 2652)], 0.99))
    assert _extraer_numero_guia_geometrico(bloques) == {}


def test_numero_sin_marcador_bajo_el_encabezado_no_se_acepta():
    bloques = [b for b in _encabezado_real_482483() if b.texto != "N482483"]
    bloques.append(_real("482483", [(1618, 784), (1840, 788), (1840, 838), (1618, 834)], 0.99))
    assert _extraer_numero_guia_geometrico(bloques) == {}


def test_segundo_folio_marcado_dentro_del_encabezado_se_abstiene():
    bloques = _encabezado_real_482399()
    bloques.append(_real("N482400", [(1599, 1140), (1832, 1140), (1832, 1190), (1599, 1190)], 0.99))
    assert _extraer_numero_guia_geometrico(bloques) == {}
