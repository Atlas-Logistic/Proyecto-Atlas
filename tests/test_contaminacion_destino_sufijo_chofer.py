"""Bloque CONTAMINACIÓN ENTRE CAMPOS (sufijo) -- DESPACHAR A + valor de
RETIRA pegado AL FINAL (caso real transporte 0000360025, 3 guías, un
solo destino; una guía salió con el nombre del chofer pegado al final de
la dirección y el viaje se partió en 2 entregas falsas).

Causa raíz: foto levemente girada -- PaddleOCR lee "RETIRA" ANTES que
"DESPACHAR A", y el valor de RETIRA (nombre del chofer) cae en el texto
lineal justo DESPUÉS de la dirección real. El regex de DESPACHAR A sólo
corta en una etiqueta conocida (PATENTE), `limpiar_sufijo_rut_pegado`
retira el RUT del chofer, pero el nombre sobrevivía: `_despachar_a_
lineal_contaminado` (472523) sólo detecta el chofer como valor COMPLETO.

Reglas GENERALES: ningún test usa el nombre, guía ni transporte del caso
real -- sólo la forma del layout."""
from __future__ import annotations

import csv

from atlas_core.extractor import limpiar_sufijo_chofer_pegado
from atlas_core.gestor_viajes import agrupar_viajes
from atlas_core.revalidacion_documental import (
    COLUMNAS,
    revalidar_destino_rut_pegado_persistido_sin_ocr,
)
from atlas_core.rutas.destino_entrega import resolver_entrega_documento

DIRECCION = "AV LOS ALERCES 4500 SANTIAGO PUDAHUEL"
CHOFER = "PEDRO SOTO"
RUT_CHOFER = "12345678-5"


# ============================================================
# 1 -- limpiar_sufijo_chofer_pegado (regla pura)
# ============================================================


def test_nombre_del_chofer_pegado_al_final_se_retira():
    assert limpiar_sufijo_chofer_pegado(f"{DIRECCION} {CHOFER}", CHOFER) == DIRECCION


def test_tolerante_a_acentos_y_un_caracter_ocr_en_el_nombre():
    assert limpiar_sufijo_chofer_pegado(f"{DIRECCION} PEDR0 SOTO", "Pedro Soto") == DIRECCION
    assert limpiar_sufijo_chofer_pegado(f"{DIRECCION} JOSÉ MUÑOZ", "JOSE MUNOZ") == DIRECCION


def test_direccion_limpia_queda_intacta():
    assert limpiar_sufijo_chofer_pegado(DIRECCION, CHOFER) == DIRECCION


def test_sin_chofer_resuelto_comportamiento_identico():
    assert limpiar_sufijo_chofer_pegado(f"{DIRECCION} {CHOFER}", "") == f"{DIRECCION} {CHOFER}"


def test_nombre_en_medio_de_la_direccion_nunca_se_toca():
    """Una calle con el mismo nombre que el chofer es una calle real."""
    valor = "PASAJE PEDRO SOTO 123 SANTIAGO"
    assert limpiar_sufijo_chofer_pegado(valor, CHOFER) == valor


def test_resto_sin_numeracion_se_abstiene():
    """Si quitar el sufijo deja algo sin numeración, podría ser una calle
    real nombrada como el chofer -- nunca se recorta."""
    valor = "AVENIDA PEDRO SOTO"
    assert limpiar_sufijo_chofer_pegado(valor, CHOFER) == valor


def test_chofer_de_una_sola_palabra_nunca_recorta():
    valor = f"{DIRECCION} SOTO"
    assert limpiar_sufijo_chofer_pegado(valor, "SOTO") == valor


def test_nombre_distinto_al_chofer_nunca_se_recorta():
    valor = f"{DIRECCION} JUAN ROJAS"
    assert limpiar_sufijo_chofer_pegado(valor, CHOFER) == valor


def test_valor_que_es_solo_el_chofer_no_se_vacia():
    """Ese caso lo cubre `_despachar_a_lineal_contaminado` (472523) con
    reintento geométrico -- esta regla nunca devuelve vacío."""
    assert limpiar_sufijo_chofer_pegado(CHOFER, CHOFER) == CHOFER


# ============================================================
# 2 -- primer pase: resolver_entrega_documento con el orden de lectura
# real (RETIRA antes que DESPACHAR A, nombre + RUT tras la dirección)
# ============================================================


def _textos_lineal_rotado(direccion, chofer, rut):
    return [
        "PESO KG.", ":1.000,00",
        "RETIRA",
        "DESPACHAR A",
        f": {direccion}",
        chofer,
        f":{rut}",
        "PATENTE",
        "AA1234 CARRO:BB5678",
        "RUT CHOFER",
        "FECHA SALIDA", ":01-01-2026",
    ]


def test_primer_pase_retira_chofer_y_rut_pegados_al_final():
    resultado = resolver_entrega_documento(
        _textos_lineal_rotado(DIRECCION, CHOFER, RUT_CHOFER), [], None, chofer_resuelto=CHOFER,
    )
    assert resultado["despachar_a_crudo"] == DIRECCION


def test_primer_pase_sin_chofer_resuelto_comportamiento_previo():
    resultado = resolver_entrega_documento(
        _textos_lineal_rotado(DIRECCION, CHOFER, RUT_CHOFER), [], None,
    )
    assert resultado["despachar_a_crudo"] == f"{DIRECCION} {CHOFER}"


def test_primer_pase_orden_normal_queda_intacto():
    textos = [
        "DESPACHAR A", f": {DIRECCION}", "RETIRA", CHOFER,
        "RUT CHOFER", f":{RUT_CHOFER}", "PATENTE", "AA1234",
    ]
    resultado = resolver_entrega_documento(textos, [], None, chofer_resuelto=CHOFER)
    assert resultado["despachar_a_crudo"] == DIRECCION


# ============================================================
# 3 -- retroactivo + agrupación: 3 guías del mismo viaje, una
# contaminada, convergen a UNA entrega; un destino realmente distinto
# sigue separado.
# ============================================================


def _fila(numero_guia, destino, chofer=CHOFER):
    fila = {c: "" for c in COLUMNAS}
    fila.update({
        "archivo": f"{numero_guia}.jpg",
        "estado_procesamiento": "OK",
        "numero_guia": numero_guia,
        "numero_transporte": "0000900001",
        "fecha": "01-01-2026",
        "chofer": chofer,
        "rut_chofer": RUT_CHOFER,
        "cliente": "CLIENTE SINTETICO SPA",
        "obra_destino": "CLIENTE SINTETICO SPA",
        "patente_tracto": "AA1234",
        "patente_rampla": "BB5678",
        "descripcion_material": "BARRAS",
        "tipo_carga": "BARRAS",
        "peso_kg": "1000",
        "hora_entrada_aza": "07:00",
        "hora_salida_aza": "09:00",
        "despachar_a_crudo": destino,
        "direccion_entrega": destino,
        "localidad_entrega": "Pudahuel",
        "region_entrega": "Metropolitana",
        "estado_entrega": "RESUELTO",
        "estado_ruta": "RUTA_CALCULADA",
    })
    return fila


def _escribir(ruta, filas):
    with ruta.open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader()
        escritor.writerows(filas)


def _leer(ruta):
    with ruta.open("r", newline="", encoding="utf-8-sig") as archivo:
        return list(csv.DictReader(archivo, delimiter=";"))


def test_retroactivo_limpia_fila_contaminada_y_el_viaje_queda_con_una_entrega(tmp_path):
    ruta = tmp_path / "analisis_completo_guias.csv"
    _escribir(ruta, [
        _fila("900001", DIRECCION),
        _fila("900002", DIRECCION),
        _fila("900003", f"{DIRECCION} {CHOFER}"),
    ])
    viajes_antes, _ = agrupar_viajes(_leer(ruta))
    assert len(viajes_antes) == 1 and len(viajes_antes[0].entregas) == 2  # el bug

    resultado = revalidar_destino_rut_pegado_persistido_sin_ocr(ruta_dataset=ruta)
    assert resultado["guias_actualizadas"] == ["900003"]

    filas = _leer(ruta)
    assert all(f["despachar_a_crudo"] == DIRECCION for f in filas)
    assert all(f["direccion_entrega"] == DIRECCION for f in filas)
    viajes, _ = agrupar_viajes(filas)
    assert len(viajes) == 1
    assert len(viajes[0].entregas) == 1
    assert CHOFER not in str(viajes[0].entregas[0])

    # Idempotente.
    assert revalidar_destino_rut_pegado_persistido_sin_ocr(ruta_dataset=ruta)["guias_actualizadas"] == []


def test_retroactivo_no_fusiona_destinos_realmente_distintos(tmp_path):
    otra = "CALLE LAS ACACIAS 120 SANTIAGO QUILICURA"
    ruta = tmp_path / "analisis_completo_guias.csv"
    _escribir(ruta, [
        _fila("900011", DIRECCION),
        _fila("900012", f"{otra} {CHOFER}"),
    ])
    revalidar_destino_rut_pegado_persistido_sin_ocr(ruta_dataset=ruta)
    filas = _leer(ruta)
    assert [f["despachar_a_crudo"] for f in filas] == [DIRECCION, otra]
    viajes, _ = agrupar_viajes(filas)
    assert len(viajes) == 1 and len(viajes[0].entregas) == 2
