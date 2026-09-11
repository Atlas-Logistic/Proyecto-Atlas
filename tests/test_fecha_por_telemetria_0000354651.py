"""Regresión explícita -- FECHA POR TELEMETRÍA (Codex 0000354651,
472276/472277, PRODALAM SA / CRISTOPHER RETAMAL).

472276 (21-08-2026) tiene GPS PROPIO confirmado ese mismo día
(`hora_entrada_gps`/`hora_salida_gps` dentro del 21-08-2026,
`origen_gps=ORIGEN_GPS_CONFIRMADO`); 472277 (23-08-2026) no trae ninguna
evidencia temporal propia. Mismo transporte, misma patente.
`revalidar_fecha_por_telemetria_de_transporte_compartido_sin_ocr` adopta
la fecha respaldada por GPS -- nunca mayoría de OCR, nunca inventa."""
from __future__ import annotations

import csv

from atlas_core.procesamiento_masivo import COLUMNAS
from atlas_core.revalidacion_documental import (
    revalidar_fecha_por_telemetria_de_transporte_compartido_sin_ocr,
)

TRANSPORTE = "0000354651"
PATENTE = "BPHR67"


def _fila(numero_guia, fecha, *, origen_gps="", hora_entrada_gps="", hora_salida_gps="",
          patente=PATENTE, transporte=TRANSPORTE):
    fila = {c: "" for c in COLUMNAS}
    fila.update(
        archivo=f"{numero_guia}.jpeg", numero_guia=numero_guia, numero_transporte=transporte,
        fecha=fecha, cliente="PRODALAM SA", chofer="CRISTOPHER RETAMAL",
        patente_tracto=patente, origen_gps=origen_gps,
        hora_entrada_gps=hora_entrada_gps, hora_salida_gps=hora_salida_gps,
    )
    return fila


def _escribir(ruta, filas):
    with ruta.open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNAS, delimiter=";")
        w.writeheader()
        w.writerows(filas)


def _leer(ruta):
    with ruta.open(newline="", encoding="utf-8-sig") as fh:
        return {f["numero_guia"]: f for f in csv.DictReader(fh, delimiter=";")}


# ============================================================
# 1. Caso real -- adopta la fecha respaldada por GPS propio
# ============================================================


def test_adopta_fecha_respaldada_por_gps_propio_caso_real_0000354651(tmp_path):
    ruta = tmp_path / "guias.csv"
    _escribir(ruta, [
        _fila("472276", "21-08-2026", origen_gps="ORIGEN_GPS_CONFIRMADO",
              hora_entrada_gps="2026-08-21 07:06:22", hora_salida_gps="2026-08-21 12:05:29"),
        _fila("472277", "23-08-2026"),  # sin evidencia temporal propia
    ])
    res = revalidar_fecha_por_telemetria_de_transporte_compartido_sin_ocr(ruta_dataset=ruta)
    assert res["guias_actualizadas"] == ["472277"]
    filas = _leer(ruta)
    assert filas["472277"]["fecha"] == "21-08-2026"
    assert filas["472276"]["fecha"] == "21-08-2026"  # el respaldado nunca se toca


def test_nunca_toca_otros_campos_de_la_fila_debil(tmp_path):
    ruta = tmp_path / "guias.csv"
    fila_debil = _fila("472277", "23-08-2026")
    fila_debil["estado_ruta"] = "RUTA_CALCULADA"
    fila_debil["motivo_ruta"] = ""
    fila_debil["descripcion_material"] = ""
    fila_debil["motivos_revision_documento"] = "MATERIAL_AUSENTE"
    _escribir(ruta, [
        _fila("472276", "21-08-2026", origen_gps="ORIGEN_GPS_CONFIRMADO",
              hora_entrada_gps="2026-08-21 07:06:22"),
        fila_debil,
    ])
    revalidar_fecha_por_telemetria_de_transporte_compartido_sin_ocr(ruta_dataset=ruta)
    f = _leer(ruta)["472277"]
    assert f["fecha"] == "21-08-2026"
    assert f["motivo_ruta"] == ""
    assert f["estado_ruta"] == "RUTA_CALCULADA"
    assert f["motivos_revision_documento"] == "MATERIAL_AUSENTE"  # intacto, otro bloque lo resuelve


# ============================================================
# 2. Abstención -- nunca corrige sin evidencia suficiente
# ============================================================


def test_abstiene_si_ninguna_fecha_tiene_gps_propio(tmp_path):
    ruta = tmp_path / "guias.csv"
    _escribir(ruta, [
        _fila("472276", "21-08-2026"),
        _fila("472277", "23-08-2026"),
    ])
    res = revalidar_fecha_por_telemetria_de_transporte_compartido_sin_ocr(ruta_dataset=ruta)
    assert res["guias_actualizadas"] == []


def test_abstiene_si_ambas_fechas_tienen_gps_propio_contradictorio(tmp_path):
    """Empate real entre dos evidencias fuertes -- nunca 'la primera'."""
    ruta = tmp_path / "guias.csv"
    _escribir(ruta, [
        _fila("472276", "21-08-2026", origen_gps="ORIGEN_GPS_CONFIRMADO",
              hora_entrada_gps="2026-08-21 07:06:22"),
        _fila("472277", "23-08-2026", origen_gps="ORIGEN_GPS_CONFIRMADO",
              hora_entrada_gps="2026-08-23 08:00:00"),
    ])
    res = revalidar_fecha_por_telemetria_de_transporte_compartido_sin_ocr(ruta_dataset=ruta)
    assert res["guias_actualizadas"] == []
    filas = _leer(ruta)
    assert filas["472276"]["fecha"] == "21-08-2026"
    assert filas["472277"]["fecha"] == "23-08-2026"


def test_abstiene_si_patentes_distintas_en_el_grupo(tmp_path):
    """Sin coherencia de vehículo, 'mismo transporte' no basta."""
    ruta = tmp_path / "guias.csv"
    _escribir(ruta, [
        _fila("472276", "21-08-2026", origen_gps="ORIGEN_GPS_CONFIRMADO",
              hora_entrada_gps="2026-08-21 07:06:22", patente="BPHR67"),
        _fila("472277", "23-08-2026", patente="XX1234"),
    ])
    res = revalidar_fecha_por_telemetria_de_transporte_compartido_sin_ocr(ruta_dataset=ruta)
    assert res["guias_actualizadas"] == []


def test_abstiene_si_hay_tres_fechas_distintas(tmp_path):
    ruta = tmp_path / "guias.csv"
    _escribir(ruta, [
        _fila("472276", "21-08-2026", origen_gps="ORIGEN_GPS_CONFIRMADO",
              hora_entrada_gps="2026-08-21 07:06:22"),
        _fila("472277", "23-08-2026"),
        _fila("472278", "22-08-2026"),
    ])
    res = revalidar_fecha_por_telemetria_de_transporte_compartido_sin_ocr(ruta_dataset=ruta)
    assert res["guias_actualizadas"] == []


def test_abstiene_si_el_gps_propio_no_es_autoconsistente_con_su_propia_fecha(tmp_path):
    """origen_gps=CONFIRMADO pero el timestamp GPS cae en OTRO día que el
    documental -- eso es una fila que se contradice a sí misma, nunca
    evidencia de respaldo."""
    ruta = tmp_path / "guias.csv"
    _escribir(ruta, [
        _fila("472276", "21-08-2026", origen_gps="ORIGEN_GPS_CONFIRMADO",
              hora_entrada_gps="2026-08-20 23:50:00"),  # no cae en 21-08
        _fila("472277", "23-08-2026"),
    ])
    res = revalidar_fecha_por_telemetria_de_transporte_compartido_sin_ocr(ruta_dataset=ruta)
    assert res["guias_actualizadas"] == []


def test_no_toca_transporte_de_una_sola_guia(tmp_path):
    ruta = tmp_path / "guias.csv"
    _escribir(ruta, [
        _fila("472276", "21-08-2026", origen_gps="ORIGEN_GPS_CONFIRMADO",
              hora_entrada_gps="2026-08-21 07:06:22", transporte="0000000001"),
    ])
    res = revalidar_fecha_por_telemetria_de_transporte_compartido_sin_ocr(ruta_dataset=ruta)
    assert res["guias_actualizadas"] == []


def test_idempotente(tmp_path):
    ruta = tmp_path / "guias.csv"
    _escribir(ruta, [
        _fila("472276", "21-08-2026", origen_gps="ORIGEN_GPS_CONFIRMADO",
              hora_entrada_gps="2026-08-21 07:06:22"),
        _fila("472277", "23-08-2026"),
    ])
    assert revalidar_fecha_por_telemetria_de_transporte_compartido_sin_ocr(ruta_dataset=ruta)["guias_actualizadas"] == ["472277"]
    assert revalidar_fecha_por_telemetria_de_transporte_compartido_sin_ocr(ruta_dataset=ruta)["guias_actualizadas"] == []
