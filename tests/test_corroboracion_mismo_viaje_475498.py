"""Corroboración entre guías del MISMO viaje (caso real 475498 junto a
475497/475499, transporte 0000362665): una guía con OCR degradado toma de
sus hermanas buenas sólo los campos de viaje, nunca los propios de la guía,
y sólo con evidencia fuerte y no contradictoria de mismo viaje."""

from __future__ import annotations

import copy
import json

from atlas_core.procesamiento_masivo import (
    COLUMNAS,
    corroborar_campos_viaje_entre_guias_hermanas,
    entrega_corroborada_por_mismo_viaje,
)

# Líneas OCR reales (traza PaddleOCR de 475498) relevantes para el viaje.
OCR_475498 = [
    "N 475498", ",0001001424", "56-10-s924", "WO. TRANSPORTE", "0995542645",
    "ESPACHAR A", "1 CALVARINO 8501 QUSLIC9A", "UT CHOFER", "RETIRA", "19708225-1",
    "PATENTE", "2213 GARC1A", "AL1819 CX220:J82501", "CHA SALIDA", "1:06-10-2026",
]


def _fila(**valores: str) -> dict[str, str]:
    fila = {columna: "" for columna in COLUMNAS}
    fila.update(estado_procesamiento="OK", fecha="06-10-2026")
    fila.update(valores)
    return fila


def _buena(guia: str, **extra: str) -> dict[str, str]:
    base = dict(
        archivo=f"{guia}.jpeg", numero_guia=guia, numero_transporte="0000362665",
        chofer="RENÉ GARCÍA", rut_chofer="9708225-1", cliente="EBEMA SA", rut_cliente="83.585.400-0",
        codigo_cliente="0001001424", obra_destino="EBEMA SA", patente_tracto="AL1879", patente_rampla="JK2501",
        despachar_a_crudo="GALVARINO 8501 QUILICURA", direccion_entrega="GALVARINO 8501 QUILICURA",
        localidad_entrega="Quilicura", estado_entrega="RESUELTO", estado_ruta="RUTA_CALCULADA",
        distancia_km="13.1788", duracion_min="19.06", proveedor_ruta="openrouteservice",
        planta_origen_id="planta-colina", planta_origen_nombre="AZA COLINA",
        indicador_revision="OK", estado_documental="OK", estado_operacional="OK",
    )
    base.update(extra)
    return _fila(**base)


def _degradada(**extra: str) -> dict[str, str]:
    base = dict(
        archivo="475498.jpeg", numero_guia="475498", numero_transporte="No encontrado",
        chofer="No encontrado", rut_chofer="No encontrado", cliente="No encontrado",
        rut_cliente="No encontrado", codigo_cliente="No encontrado", obra_destino="No encontrado",
        patente_tracto="GARC1A", patente_rampla="No encontrado", peso_kg="No encontrado",
        descripcion_material="", despachar_a_crudo="1 CALVARINO 8501 QUSLIC9A",
        estado_entrega="NO_INTENTADO", indicador_revision="REVISAR",
        motivos_revision_documento=(
            "PATENTE_SIN_HOMOLOGAR | TRANSPORTE_AUSENTE | CHOFER_AUSENTE | CLIENTE_AUSENTE"
            " | MATERIAL_AUSENTE | DOCUMENTO_DEGRADADO"
        ),
    )
    base.update(extra)
    return _fila(**base)


def _caso(degradada=None, buenas=None, ocr=OCR_475498):
    filas = [*(buenas or [_buena("475497", peso_kg="4202"), _buena("475499", peso_kg="3059")]),
             degradada or _degradada()]
    resultado = corroborar_campos_viaje_entre_guias_hermanas(filas, {"475498.jpeg"}, {"475498.jpeg": ocr})
    return resultado, filas[-1]


def test_a_degradada_corrobora_campos_de_viaje_y_retira_revisiones_espurias():
    corroboradas, fila = _caso()
    assert corroboradas == ["475498.jpeg"]
    assert (fila["numero_transporte"], fila["chofer"], fila["rut_chofer"]) == ("0000362665", "RENÉ GARCÍA", "9708225-1")
    assert (fila["cliente"], fila["obra_destino"], fila["codigo_cliente"]) == ("EBEMA SA", "EBEMA SA", "0001001424")
    motivos = fila["motivos_revision_documento"].split(" | ")
    assert not {"PATENTE_SIN_HOMOLOGAR", "TRANSPORTE_AUSENTE", "CHOFER_AUSENTE", "CLIENTE_AUSENTE"} & set(motivos)
    assert {"MATERIAL_AUSENTE", "DOCUMENTO_DEGRADADO"} <= set(motivos)
    evidencia = json.loads(fila["evidencia_documentos_relacionados"])
    assert evidencia["regla"] == "MISMO_VIAJE"
    assert evidencia["archivos_fuente"] == ["475497.jpeg", "475499.jpeg"]


def test_b_garc1a_no_queda_como_vehiculo_si_el_grupo_demuestra_las_patentes():
    _, fila = _caso()
    assert (fila["patente_tracto"], fila["patente_rampla"]) == ("AL1879", "JK2501")
    senales = set(json.loads(fila["evidencia_documentos_relacionados"])["senales"])
    assert {"rut_chofer", "patente_tracto", "patente_rampla"} <= senales


def test_c_destino_degradado_converge_a_la_entrega_del_viaje_sin_tocar_el_crudo():
    _, fila = _caso()
    assert "destino" in json.loads(fila["evidencia_documentos_relacionados"])["senales"]
    assert fila["despachar_a_crudo"] == "1 CALVARINO 8501 QUSLIC9A"
    assert (fila["direccion_entrega"], fila["estado_ruta"], fila["distancia_km"]) == (
        "GALVARINO 8501 QUILICURA", "RUTA_CALCULADA", "13.1788",
    )
    assert fila["planta_origen_nombre"] == "AZA COLINA"
    assert entrega_corroborada_por_mismo_viaje(fila)


def test_c_destino_de_otra_calle_no_comparte_la_entrega():
    _, fila = _caso(degradada=_degradada(despachar_a_crudo="AV MATTA 1200 SANTIAGO"))
    assert fila["numero_transporte"] == "0000362665"  # el viaje sigue demostrado por RUT/patentes
    assert fila["direccion_entrega"] == "" and fila["estado_ruta"] == ""
    assert not entrega_corroborada_por_mismo_viaje(fila)


def test_d_campos_propios_de_la_guia_nunca_se_copian():
    _, fila = _caso()
    assert fila["numero_guia"] == "475498"
    assert fila["peso_kg"] == "No encontrado"
    assert fila["descripcion_material"] == ""
    assert fila["fecha"] == "06-10-2026"


def test_e_contradiccion_fuerte_propia_se_abstiene():
    contradicciones = (
        dict(numero_transporte="0000370001"),
        dict(rut_chofer="12.345.678-5"),
        dict(patente_tracto="KLMN12", motivos_revision_documento="CHOFER_AUSENTE"),
    )
    for propia in contradicciones:
        degradada = _degradada(**propia)
        original = copy.deepcopy(degradada)
        corroboradas, fila = _caso(degradada=degradada)
        assert corroboradas == [], propia
        assert fila == original, propia


def test_e_hermanas_en_desacuerdo_o_dos_viajes_candidatos_se_abstiene():
    desacuerdo = [_buena("475497"), _buena("475499", rut_chofer="12.345.678-5")]
    assert _caso(buenas=desacuerdo)[0] == []
    dos_viajes = [
        _buena("475497"), _buena("475499"),
        _buena("475600", numero_transporte="0000362700"), _buena("475601", numero_transporte="0000362700"),
    ]
    assert _caso(buenas=dos_viajes)[0] == []


def test_f_cargadas_juntas_sin_evidencia_de_mismo_viaje_no_se_contaminan():
    # Mismo lote y misma fecha, pero el OCR propio no lee RUT ni patentes.
    corroboradas, fila = _caso(ocr=["N 475498", "1 CALVARINO 8501 QUSLIC9A", ",0001001424"])
    assert corroboradas == []
    assert fila["numero_transporte"] == "No encontrado" and fila["patente_tracto"] == "GARC1A"
    # Otra fecha: nunca el mismo viaje, aunque todo lo demás coincida.
    assert _caso(degradada=_degradada(fecha="07-10-2026"))[0] == []
    # Una sola hermana buena no basta para establecer consenso.
    assert _caso(buenas=[_buena("475497")])[0] == []


def test_f_campo_presente_en_duda_no_se_pisa_ni_retira_motivo_semantico():
    buenas = [_buena("475497"), _buena("475499")]
    degradada = _degradada(cliente="EBEMA NUEVA", motivos_revision_documento="CLIENTE_NUEVA_ENTIDAD_NO_CATALOGADA")
    _, fila = _caso(degradada=degradada, buenas=buenas)
    assert fila["cliente"] == "EBEMA NUEVA"
    assert "CLIENTE_NUEVA_ENTIDAD_NO_CATALOGADA" in fila["motivos_revision_documento"]
