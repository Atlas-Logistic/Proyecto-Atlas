"""Regresiones de asociación geométrica para el membrete AZA.

La composición reproduce la evidencia documental de las guías Retamal: las
columnas de cliente/GIRO y obra/código coexisten, y DESPACHAR A está en una
zona independiente. No hay reglas condicionadas a números de guía.
"""
from __future__ import annotations

from unittest.mock import Mock

from atlas_core import procesamiento_masivo
from atlas_core.extractor import (
    _extraer_asociaciones_geometricas,
    _extraer_despachar_a_geometrico,
)
from atlas_core.ocr import BloqueOCR


def _bloque(texto: str, x: int, y: int, ancho: int | None = None, alto: int = 24) -> BloqueOCR:
    ancho = ancho if ancho is not None else max(35, len(texto) * 9)
    return BloqueOCR(
        texto=texto,
        bounding_box=((x, y), (x + ancho, y), (x + ancho, y + alto), (x, y + alto)),
        confianza=0.98,
    )


def _membrete_aza_con_columnas_proximas() -> list[BloqueOCR]:
    return [
        _bloque("SEÑOR(ES)", 80, 100, 110),
        _bloque("EASY RETAIL SA", 250, 100, 185),
        _bloque("SOLICITANTE", 620, 100, 120),
        _bloque("EMPRESA CONSTRUCTORA BRAVO E", 805, 100, 280),
        _bloque("R.U.T.", 80, 134, 70),
        _bloque("76.568.660-1", 250, 134, 140),
        # Valor comercial de la columna izquierda: nunca obra ni cliente.
        _bloque("GIRO", 80, 168, 55),
        _bloque("VIA AL X MENOR ART", 250, 168, 205),
        _bloque("OBRA DESTINO", 620, 168, 135),
        _bloque("EMPRESA CONSTRUCTORA BRAVO E", 805, 168, 280),
        _bloque("TELEFONO", 80, 202, 95),
        _bloque("2222 2222", 250, 202, 110),
        _bloque("COD DESTINATARIO", 620, 202, 175),
        _bloque("0002013100", 805, 202, 120),
        _bloque("DESPACHAR A", 20, 500, 125),
        _bloque("AV. CAM. LOS TRAPENSES", 190, 500, 245),
        _bloque("LO BARNECHEA", 190, 530, 150),
        _bloque("RETIRA", 620, 500, 75),
        _bloque("CRISTOPHER RETAMAL", 750, 500, 190),
    ]


def test_membrete_aza_asocia_cada_etiqueta_con_su_columna_real():
    asociaciones = _extraer_asociaciones_geometricas(_membrete_aza_con_columnas_proximas())

    assert asociaciones == {
        "cliente": "EASY RETAIL SA",
        "obra destino": "EMPRESA CONSTRUCTORA BRAVO E",
        "cod destinatario": "0002013100",
    }


def test_despachar_a_ignora_giro_telefono_y_retira_de_otras_zonas():
    resultado = _extraer_despachar_a_geometrico(_membrete_aza_con_columnas_proximas())

    # La calle, que es la evidencia usada para la relación confirmada, queda
    # en la misma línea de DESPACHAR A; la comuna puede venir en otra línea.
    assert resultado["valor"] == "AV. CAM. LOS TRAPENSES"


def test_cod_destinatario_ambiguo_se_abstiene_en_vez_de_elegir_por_orden_ocr():
    bloques = _membrete_aza_con_columnas_proximas()
    bloques.append(_bloque("0002013999", 805, 203, 120))

    asociaciones = _extraer_asociaciones_geometricas(bloques)

    assert "cod destinatario" not in asociaciones


def test_procesamiento_prefiere_asociacion_geometrica_sobre_valor_lineal_contaminado(tmp_path, monkeypatch):
    """Una etiqueta explícita prevalece incluso si la contaminación parece
    nominal; GIRO/TELEFONO no siempre disparan el filtro de credibilidad."""
    monkeypatch.setattr(procesamiento_masivo, "leer_texto_imagen", Mock(return_value=[]))
    monkeypatch.setattr(procesamiento_masivo, "leer_bloques_imagen", Mock(return_value=[]))
    monkeypatch.setattr(
        procesamiento_masivo, "extraer_datos",
        Mock(return_value={
            "número de guía": "900001",
            "número de transporte": "0000363522",
            "cliente": "EASY RSTAIL SA TELEFONO",
            "obra destino": "VIA AL X MENOR ART GIRO",
            "cod destinatario": "DIRECCION",
            "RUT del cliente": "76.568.660-1",
            "chofer": "CRISTOPHER RETAMAL",
            "RUT del chofer": "17.576.134-9",
            "patente del tracto": "BPHR67",
            # Todos los campos que disparaban históricamente el fallback ya
            # están completos: el código contaminado debe bastar para activar
            # la lectura geométrica del membrete.
            "patente del carro": "CD5678",
        }),
    )
    monkeypatch.setattr(
        procesamiento_masivo,
        "_extraer_asociaciones_geometricas",
        Mock(return_value={
            "cliente": "EASY RETAIL SA",
            "obra destino": "EMPRESA CONSTRUCTORA BRAVO E",
            "cod destinatario": "0002013100",
        }),
    )

    resultado = procesamiento_masivo.procesar_archivo(tmp_path / "guia.jpg")

    assert resultado["cliente"] == "EASY RETAIL SA"
    assert resultado["obra_destino"] == "EMPRESA CONSTRUCTORA BRAVO E"
    assert resultado["cod_destinatario"] == "0002013100"
