"""Cabecera parcialmente tapada: bloques OCR de 477355 y limites de seguridad."""
from atlas_core.extractor import _extraer_numero_guia_geometrico
from atlas_core.ocr import BloqueOCR


def bloque(texto, caja):
    return BloqueOCR(texto=texto, bounding_box=caja, confianza=0.99)


def cabecera():
    return [
        bloque('GUIA DE', ((572,151),(672,149),(672,166),(572,168))),
        bloque('ELECTRONIOA', ((600,168),(738,166),(739,183),(600,185))),
        bloque('N\u00ba 477355', ((627,195),(718,195),(718,213),(627,213))),
    ]


def test_recupera_folio_de_bloques_reales():
    assert _extraer_numero_guia_geometrico(cabecera()) == {'valor': '477355'}


def test_no_acepta_cabecera_sin_apoyo_o_otra_deformacion():
    b = cabecera()
    assert _extraer_numero_guia_geometrico([b[0], b[2]]) == {}
    b[1] = bloque('ELECTRONIBA', b[1].bounding_box)
    assert _extraer_numero_guia_geometrico(b) == {}


def test_se_abstiene_si_el_apoyo_esta_lejos_o_hay_folios_en_conflicto():
    b = cabecera()
    b[1] = bloque('ELECTRONIOA', ((100,168),(238,166),(239,183),(100,185)))
    assert _extraer_numero_guia_geometrico(b) == {}
    b = cabecera()
    b.append(bloque('N\u00ba 477356', ((627,220),(718,220),(718,235),(627,235))))
    assert _extraer_numero_guia_geometrico(b) == {}
