"""Entregas artificialmente separadas por truncamiento OCR de DESPACHAR A o
por un sufijo geográfico equivalente (caso real 0000362325: 475368/475369/
475370 imprimen "CAMINO LO RUIZ 2901 SANTIAGO RENCA"; también 0000354852 y
0000356332). Las reglas viven en `atlas_core.direccion_equivalente`; aquí
se prueban a través de `resolver_entrega_documento` (cambio 1) y de la
agrupación de entregas (cambio 2)."""
from __future__ import annotations

import pytest

from atlas_core.direccion_equivalente import (
    direcciones_equivalentes_por_sufijo_geografico,
    extension_geografica_compatible,
)
from atlas_core.gestor_viajes import agrupar_viajes
from atlas_core.ocr import BloqueOCR
from atlas_core.rutas.destino_entrega import resolver_entrega_documento


# ---------------------------------------------------------------------------
# CAMBIO 1 -- DESPACHAR A truncado en la lectura lineal
# ---------------------------------------------------------------------------
def _caja(texto, x1, y1, x2, y2):
    return BloqueOCR(texto=texto, bounding_box=((x1, y1), (x2, y1), (x2, y2), (x1, y2)), confianza=0.98)


# Cajas reales de la traza OCR de 475368: PaddleOCR partió la fila impresa
# en dos bloques y leyó "RUT CHOFER" (fila siguiente) entre ambos.
def _zona_475368(sufijo="SANTIAGO RENCA"):
    return [
        _caja("PESO KG.", 54, 731, 120, 745),
        _caja(":16.172,00", 135, 735, 213, 747),
        _caja("DESPACHAR A", 53, 753, 137, 767),
        _caja(": CAMINO LO RUIZ 2901", 180, 754, 327, 772),
        _caja("RUT CHOFER", 52, 766, 128, 780),
        _caja(sufijo, 322, 757, 322 + 8 * len(sufijo), 775),
        _caja(":10833150-K", 181, 767, 260, 781),
        _caja("RETIRA", 519, 760, 565, 774),
        _caja("JOSE LAZCANO", 594, 764, 690, 778),
        _caja("FECHA SALIDA", 50, 782, 140, 796),
        _caja("PATENTE", 519, 774, 575, 788),
        _caja(": ND6443 CARRO:JB6878", 582, 777, 740, 791),
        _caja(":05-10-2026", 179, 787, 260, 801),
    ]


def _textos_475368(sufijo="SANTIAGO RENCA", comuna_cabecera="RENCA"):
    return [
        "DIRECCION", ": CAMINO LO RUIZ 2901", "COMUNA", f": {comuna_cabecera}", "CIUDAD", ": SANTIAGO",
        "PESO KG.", ":16.172,00", "DESPACHAR A", ": CAMINO LO RUIZ 2901", "RUT CHOFER", sufijo,
        ":10833150-K", "RETIRA", "JOSE LAZCANO", "FECHA SALIDA", "PATENTE", ": ND6443 CARRO:JB6878",
    ]


def test_475368_recupera_el_despachar_a_completo_desde_la_evidencia_geometrica():
    resultado = resolver_entrega_documento(_textos_475368(), [], None, bloques=_zona_475368())
    assert resultado["despachar_a_crudo"] == "CAMINO LO RUIZ 2901 SANTIAGO RENCA"


def test_sin_bloques_la_lectura_lineal_se_conserva_como_antes():
    resultado = resolver_entrega_documento(_textos_475368(), [], None)
    assert resultado["despachar_a_crudo"] == "CAMINO LO RUIZ 2901"


@pytest.mark.parametrize("sufijo", ["SECTOR LA ESPERANZA", "LOCAL 4", "BODEGA SUR", "RENCA 2950"])
def test_extension_no_geografica_no_reemplaza_la_lectura_lineal(sufijo):
    resultado = resolver_entrega_documento(_textos_475368(sufijo), [], None, bloques=_zona_475368(sufijo))
    assert resultado["despachar_a_crudo"] == "CAMINO LO RUIZ 2901"


def test_extension_que_contradice_la_comuna_de_la_misma_direccion_se_abstiene():
    # La cabecera es la misma calle + número y dice QUILICURA: un sufijo
    # RENCA la contradice -> se conserva la lectura lineal.
    textos = _textos_475368(comuna_cabecera="QUILICURA")
    resultado = resolver_entrega_documento(textos, [], None, bloques=_zona_475368())
    assert resultado["despachar_a_crudo"] == "CAMINO LO RUIZ 2901"


def test_extension_geografica_exige_la_lectura_lineal_completa_y_no_solo_mas_larga():
    assert extension_geografica_compatible("CAMINO LO RUIZ 2901", "CAMINO LO RUIZ 2901 SANTIAGO RENCA")
    assert extension_geografica_compatible("AV PEHUENCHE 1177", "AV PEHUENCHE 1177, TALCA, CHILE")
    assert not extension_geografica_compatible("CAMINO LO RUIZ 2901", "CAMINO LO RUIZ 2950 SANTIAGO RENCA")
    assert not extension_geografica_compatible("CAMINO LO RUIZ 2901", "CAMINO LO RUI 2901 SANTIAGO RENCA")
    assert not extension_geografica_compatible("CAMINO LO RUIZ 2901", "CAMINO LO RUIZ 2901 DEPTO 5")
    assert not extension_geografica_compatible("CAMINO LO RUIZ 2901", "CAMINO LO RUIZ 2901 RENCA QUILICURA")
    assert not extension_geografica_compatible("CAMINO LO RUIZ 2901 RENCA", "CAMINO LO RUIZ 2901 RENCA QUILICURA")
    assert not extension_geografica_compatible("CAMINO LO RUIZ 2901", "CAMINO LO RUIZ 2901")


# ---------------------------------------------------------------------------
# CAMBIO 2 -- agrupación de entregas
# ---------------------------------------------------------------------------
def _fila(numero_guia, direccion, localidad="", **cambios):
    fila = {
        "archivo": f"{numero_guia}.jpg", "numero_guia": numero_guia, "numero_transporte": "0000362325",
        "fecha": "2026-10-05", "chofer": "JOSE LAZCANO", "rut_chofer": "10833150-K",
        "cliente": "ACEROS COX COMERCIAL SA", "obra_destino": "ACEROS COX COMERCIAL SA",
        "patente_tracto": "ND6443", "patente_rampla": "JB6878", "descripcion_material": "BARRAS",
        "tipo_carga": "BARRAS", "peso_kg": "1000", "hora_entrada_aza": "10:26", "hora_salida_aza": "11:40",
        "despachar_a_crudo": direccion, "direccion_entrega": direccion, "localidad_entrega": localidad,
        "region_entrega": "Metropolitana", "estado_entrega": "RESUELTO", "distancia_km": "15.9",
        "duracion_min": "21.9", "proveedor_ruta": "openrouteservice", "estado_ruta": "RUTA_CALCULADA",
        "motivo_ruta": "",
    }
    fila.update(cambios)
    return fila


def _grupos(filas):
    viajes, _ = agrupar_viajes(filas)
    assert len(viajes) == 1
    return sorted(e["numeros_guia"] for e in viajes[0].entregas)


def test_475368_69_70_forman_una_sola_entrega():
    grupos = _grupos([
        _fila("475368", "CAMINO LO RUIZ 2901", "RENCA"),
        _fila("475369", "CAMINO LO RUI2 2901 SANTIAGO RENCA", "Renca",
              codigo_pais="CL", codigo_unidad="13128", codigo_contexto="13"),
        _fila("475370", "CAMINO LO RUIZ 2901 SANTIAGO RENCA", "Renca"),
    ])
    assert grupos == [["475368", "475369", "475370"]]


def test_av_pehuenche_con_sufijo_talca_talca_es_una_sola_entrega():
    assert _grupos([
        _fila("472491", "AV PEHUENCHE 1177", cliente="SALOMON SACK SA", obra_destino=""),
        _fila("472492", "AV PEHUENCHE 1177 TALCA TALCA", cliente="SALOMON SACK SA", obra_destino=""),
    ]) == [["472491", "472492"]]


def test_camino_los_pinos_con_santiago_san_bernardo_chile_es_una_sola_entrega():
    assert _grupos([
        _fila("477145", "CAMINO LOS PINOS 3396 SANTIAGO SAN BERNARDO", "San Bernardo"),
        _fila("477146", "CAMINO LOS PINOS 3396, SAN BERNARDO, CHILE", "SAN BERNARDO"),
    ]) == [["477145", "477146"]]


@pytest.mark.parametrize("a, b", [
    # Con distinto sufijo, sólo la regla nueva podría unirlas: el número
    # debe ser idéntico y puramente numérico. (Con textos de igual largo
    # la tolerancia OCR previa de entregas.py decide, sin cambios.)
    ("AVDA IRARRAZAVAL 5497", "AVDA IRARRAZAVAL S197 SANTIAGO NUNOA"),
    ("CATEDRAL 759 CAUQUENES", "CATEDRAL 758 CAUQUENES CAUQUENES"),
    ("CATEDRAL 759", "CATEDRAL 7590 CAUQUENES"),
])
def test_numero_ausente_o_diferente_se_abstiene(a, b):
    assert _grupos([_fila("1", a), _fila("2", b)]) == [["1"], ["2"]]
    assert not direcciones_equivalentes_por_sufijo_geografico(a, b, calles_equivalentes=lambda x, y: x == y)


def test_5497_vs_s197_nunca_es_equivalente_por_sufijo_geografico():
    assert not direcciones_equivalentes_por_sufijo_geografico(
        "AVDA IRARRAZAVAL 5497 SANTIAGO NUNOA", "AVDA IRARRAZAVAL S197 SANTIAGO NUNOA",
        calles_equivalentes=lambda x, y: True,
    )


@pytest.mark.parametrize("sufijo", [
    "SECTOR LA ESPERANZA", "LOCAL 4", "BODEGA 2", "DEPTO 501", "LOTE 27", "KM 20",
    "VILLA LOS ANDES", "PARCELA 3", "OF 12", "BLOCK B", "RENCA 2950", "SANIIAGO RENCA",
])
def test_sufijo_no_geografico_no_se_elimina(sufijo):
    assert _grupos([
        _fila("1", "CAMINO LO RUIZ 2901"),
        _fila("2", f"CAMINO LO RUIZ 2901 {sufijo}"),
    ]) == [["1"], ["2"]]


@pytest.mark.parametrize("a, b", [
    (("CAMINO LO RUIZ 2901 RENCA", ""), ("CAMINO LO RUIZ 2901 SANTIAGO QUILICURA", "")),
    (("CAMINO LO RUIZ 2901", "RENCA"), ("CAMINO LO RUIZ 2901 QUILICURA", "")),
    (("CAMINO LO RUIZ 2901", "RENCA"), ("CAMINO LO RUIZ 2901 SANTIAGO", "QUILICURA")),
])
def test_comunas_contradictorias_se_abstienen(a, b):
    assert _grupos([_fila("1", a[0], a[1]), _fila("2", b[0], b[1])]) == [["1"], ["2"]]


def test_codigo_territorial_contradictorio_se_abstiene():
    # Un código territorial de Quilicura contradice el sufijo RENCA.
    assert _grupos([
        _fila("1", "CAMINO LO RUIZ 2901", codigo_pais="CL", codigo_unidad="13125", codigo_contexto="13"),
        _fila("2", "CAMINO LO RUIZ 2901 SANTIAGO RENCA"),
    ]) == [["1"], ["2"]]


@pytest.mark.parametrize("campo, otro", [
    ("cliente", "OTRO CLIENTE SPA"),
    ("obra_destino", "OTRA OBRA"),
])
def test_cliente_u_obra_contradictorios_siguen_separados(campo, otro):
    assert _grupos([
        _fila("1", "CAMINO LO RUIZ 2901", "RENCA"),
        _fila("2", "CAMINO LO RUIZ 2901 SANTIAGO RENCA", "Renca", **{campo: otro}),
    ]) == [["1"], ["2"]]


@pytest.mark.parametrize("direccion", ["MANZANA K SIN NRO", "Coihueco, BI, Chile", "INTERIOR NUEVA O1148 SAN BERNARDO"])
def test_direccion_no_reconocible_o_sin_numero_se_abstiene(direccion):
    assert not direcciones_equivalentes_por_sufijo_geografico(
        direccion, f"{direccion} SANTIAGO", calles_equivalentes=lambda a, b: a == b,
    )


def test_la_guia_debe_ser_compatible_con_todos_los_miembros_de_la_entrega():
    # "2" calza con "1" por sufijo geográfico, pero "3" sólo calza con "1"
    # (misma comuna implícita) y contradice a "2" (QUILICURA vs RENCA).
    assert _grupos([
        _fila("1", "CAMINO LO RUIZ 2901"),
        _fila("2", "CAMINO LO RUIZ 2901 SANTIAGO RENCA"),
        _fila("3", "CAMINO LO RUIZ 2901 QUILICURA"),
    ]) == [["1", "2"], ["3"]]


def test_destinos_realmente_diferentes_siguen_siendo_reparto():
    viajes, _ = agrupar_viajes([
        _fila("475352", "EL PERAL 2030", "Contulmo", cliente="EASY RETAIL SA", obra_destino=""),
        _fila("475353", "AMERICO VESPUCIO 730 TALCAHUANO TALCAHUANO", "TALCAHUANO",
              cliente="PRODALAM SA", obra_destino=""),
        _fila("475354", "EL PERAL 2030 SANTIAGO RENCA", "", cliente="EASY RETAIL SA", obra_destino=""),
    ])
    assert len(viajes[0].entregas) == 3


def test_tolerancia_previa_de_igual_longitud_sigue_intacta():
    assert _grupos([
        _fila("1", "SANTA ISADEL 585 SANTIAGO LAMPA", "Lampa"),
        _fila("2", "SANTA ISABEL 585 SANTIAGO LAMPA", "Lampa"),
    ]) == [["1", "2"]]
