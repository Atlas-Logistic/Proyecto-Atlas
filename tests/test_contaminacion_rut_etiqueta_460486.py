"""Bloque CONTAMINACIÓN RUT+ETIQUETA (caso real 460486): "10833150-K
FECHA" -- el mismo RUT ya resuelto como `rut_chofer` de esta guía,
seguido de la etiqueta "FECHA" truncada de "FECHA SALIDA" -- nunca es
una dirección real. Generaliza la regla existente (un valor que ES
íntegramente un RUT) al caso en que el RUT queda seguido de una o más
etiquetas administrativas y nada más."""
from __future__ import annotations

import json

from atlas_core.extractor import (
    _despachar_a_lineal_contaminado, _es_rut_seguido_de_etiqueta_administrativa,
)
from atlas_core.procesamiento_masivo import COLUMNAS
from atlas_core.revalidacion_documental import revalidar_destino_contaminado_rut_etiqueta_sin_ocr


def test_rut_seguido_de_etiqueta_administrativa_es_contaminacion():
    assert _es_rut_seguido_de_etiqueta_administrativa("10833150-K FECHA") is True


def test_rut_seguido_de_dos_etiquetas_tambien_es_contaminacion():
    assert _es_rut_seguido_de_etiqueta_administrativa("10.833.150-K FECHA HORA") is True


def test_rut_seguido_de_direccion_real_no_es_contaminacion():
    """Control -- si sobra CUALQUIER texto que no sea una etiqueta
    administrativa conocida (aquí, una dirección real), nunca se
    descarta: podría ser una dirección real con un RUT pegado adelante."""
    assert _es_rut_seguido_de_etiqueta_administrativa("10833150-K AV LIBERTADOR 123") is False


def test_rut_invalido_seguido_de_etiqueta_no_es_contaminacion():
    """Control -- el dígito verificador debe validar; un número parecido
    a un RUT pero inválido no activa esta regla (podría ser cualquier
    otro número documental)."""
    assert _es_rut_seguido_de_etiqueta_administrativa("11111111-1 FECHA") is False


def test_solo_etiqueta_sin_rut_no_es_contaminacion():
    assert _es_rut_seguido_de_etiqueta_administrativa("FECHA") is False


def test_despachar_a_lineal_contaminado_reconoce_rut_mas_etiqueta():
    assert _despachar_a_lineal_contaminado("10833150-K FECHA") is True


def _fila_csv(**overrides):
    fila = {c: "" for c in COLUMNAS}
    fila.update({
        "archivo": "460486.jpeg", "numero_guia": "460486", "numero_transporte": "0000350638",
        "rut_chofer": "10.833.150-K", "despachar_a_crudo": "10833150-K FECHA",
        "estado_ruta": "REQUIERE_REVISION", "motivo_ruta": "MULTIPLES_UBICACIONES_DISPERSAS(2)",
        "planta_origen_id": "planta-1",
    })
    fila.update(overrides)
    return fila


def _escribir_csv(ruta, filas):
    import csv
    with ruta.open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader()
        escritor.writerows(filas)


def _leer_csv(ruta):
    import csv
    with ruta.open("r", newline="", encoding="utf-8-sig") as archivo:
        return list(csv.DictReader(archivo, delimiter=";"))


def test_revalidador_limpia_destino_contaminado_real(tmp_path):
    dataset = tmp_path / "analisis_completo_guias.csv"
    _escribir_csv(dataset, [_fila_csv()])

    resultado = revalidar_destino_contaminado_rut_etiqueta_sin_ocr(ruta_dataset=dataset)

    assert resultado["guias_actualizadas"] == ["460486"]
    fila = _leer_csv(dataset)[0]
    assert fila["despachar_a_crudo"] == ""
    assert fila["estado_ruta"] == ""
    assert fila["motivo_ruta"] == ""
    assert fila["estado_entrega"] == "NO_INTENTADO"


def test_revalidador_nunca_toca_una_direccion_real(tmp_path):
    dataset = tmp_path / "analisis_completo_guias.csv"
    _escribir_csv(dataset, [_fila_csv(
        despachar_a_crudo="AV LIBERTADOR 123 SANTIAGO",
        estado_ruta="RUTA_CALCULADA", motivo_ruta="",
    )])

    resultado = revalidar_destino_contaminado_rut_etiqueta_sin_ocr(ruta_dataset=dataset)

    assert resultado["guias_actualizadas"] == []
    fila = _leer_csv(dataset)[0]
    assert fila["despachar_a_crudo"] == "AV LIBERTADOR 123 SANTIAGO"
    assert fila["estado_ruta"] == "RUTA_CALCULADA"


def test_revalidador_nunca_toca_obra_ni_cliente(tmp_path):
    dataset = tmp_path / "analisis_completo_guias.csv"
    _escribir_csv(dataset, [_fila_csv(obra_destino="PRODALAM SA B", cliente="ACEROS AZA SA")])

    revalidar_destino_contaminado_rut_etiqueta_sin_ocr(ruta_dataset=dataset)

    fila = _leer_csv(dataset)[0]
    assert fila["obra_destino"] == "PRODALAM SA B"
    assert fila["cliente"] == "ACEROS AZA SA"
