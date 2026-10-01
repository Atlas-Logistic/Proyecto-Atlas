"""Identidad de fila en correcciones puntuales: una corrección dirigida a una
guía Mobile nunca escribe en otra fila. Todas las capturas Mobile se llaman
``mobile/<uuid>/original.jpg``; identificar la fila por el nombre de archivo
hacía caer la corrección en la PRIMERA fila Mobile del dataset. Fixtures
sintéticas; nunca G:."""
from __future__ import annotations

import csv
import hashlib
import json

import pytest

from atlas_core.acciones_operacionales import CapaAccionesOperacionales, TIPO_LEDGER_CORRECCION
from atlas_core.reprocesamiento_reparador import (
    FILA_AMBIGUA, FILA_CONTRADICE_GUIA, FILA_NO_ENCONTRADA, _fila_por_archivo, _resolver_fila_por_archivo,
    reparar_documento_focal_con_valores_conocidos,
)
from tests.test_acciones_operacionales import entorno  # noqa: F401 -- fixture

MOBILE_A = "mobile/aaaaaaaa-0000-4000-8000-000000000001/original.jpg"
MOBILE_B = "mobile/bbbbbbbb-0000-4000-8000-000000000002/original.jpg"


def _filas():
    return [{"archivo": MOBILE_B, "numero_guia": "200"}, {"archivo": MOBILE_A, "numero_guia": "100"},
            {"archivo": "lote_1/300.jpeg", "numero_guia": "300"}]


# ------------------------------------------------------------ resolución de fila


def test_dos_mobile_con_el_mismo_nombre_no_se_confunden():
    filas = _filas()
    assert _fila_por_archivo(filas, MOBILE_A)["numero_guia"] == "100"
    assert _fila_por_archivo(filas, MOBILE_B)["numero_guia"] == "200"
    assert _fila_por_archivo(filas, MOBILE_A.replace("/", "\\"))["numero_guia"] == "100"


def test_nombre_suelto_original_jpg_nunca_elige_una_fila_mobile():
    assert _resolver_fila_por_archivo(_filas(), "original.jpg") == (None, FILA_AMBIGUA)
    # ni siquiera si hubiera una sola fila Mobile: el nombre no la identifica
    assert _resolver_fila_por_archivo([{"archivo": MOBILE_A, "numero_guia": "100"}], "original.jpg") \
        == (None, FILA_AMBIGUA)


def test_ruta_completa_distinta_no_coincide():
    otra = "mobile/cccccccc-0000-4000-8000-000000000003/original.jpg"
    assert _resolver_fila_por_archivo(_filas(), otra) == (None, FILA_NO_ENCONTRADA)


def test_guia_objetivo_que_contradice_la_fila_se_abstiene():
    assert _resolver_fila_por_archivo(_filas(), MOBILE_A, numero_guia="200") == (None, FILA_CONTRADICE_GUIA)
    assert _resolver_fila_por_archivo(_filas(), MOBILE_A, numero_guia="100")[0]["numero_guia"] == "100"


def test_mas_de_una_coincidencia_se_abstiene():
    filas = _filas() + [{"archivo": MOBILE_A, "numero_guia": "101"}]
    assert _resolver_fila_por_archivo(filas, MOBILE_A) == (None, FILA_AMBIGUA)
    filas = [{"archivo": "lote_1/9.jpeg", "numero_guia": "9"}, {"archivo": "lote_2/9.jpeg", "numero_guia": "99"}]
    assert _resolver_fila_por_archivo(filas, "9.jpeg") == (None, FILA_AMBIGUA)


def test_cero_coincidencias_se_abstiene():
    assert _resolver_fila_por_archivo(_filas(), "no_existe.jpeg") == (None, FILA_NO_ENCONTRADA)
    assert _resolver_fila_por_archivo(_filas(), "") == (None, FILA_NO_ENCONTRADA)


def test_documentos_no_mobile_conservan_compatibilidad():
    filas = _filas()
    assert _fila_por_archivo(filas, "lote_1/300.jpeg")["numero_guia"] == "300"
    assert _fila_por_archivo(filas, "300.jpeg")["numero_guia"] == "300"  # nombre del manifiesto de lote


# ------------------------------------------------------------ escritura real


def _mobile(entorno):  # noqa: F811
    """Reescribe el dataset de la fixture con dos guías Mobile; la de la otra
    guía (500002) queda PRIMERA, como en el caso real."""
    ruta = entorno["dataset"]
    with ruta.open(encoding="utf-8-sig", newline="") as flujo:
        lector = csv.DictReader(flujo, delimiter=";")
        columnas, filas = lector.fieldnames, list(lector)
    for fila in filas:
        fila["archivo"] = MOBILE_A if fila["numero_guia"] == "500001" else MOBILE_B
    filas.sort(key=lambda f: f["numero_guia"] != "500002")
    with ruta.open("w", encoding="utf-8-sig", newline="") as flujo:
        escritor = csv.DictWriter(flujo, fieldnames=columnas, delimiter=";")
        escritor.writeheader()
        escritor.writerows(filas)
    return ruta


def _por_guia(ruta):
    with ruta.open(encoding="utf-8-sig", newline="") as flujo:
        return {f["numero_guia"]: f for f in csv.DictReader(flujo, delimiter=";")}


def test_correccion_de_guia_a_modifica_solo_a(entorno):  # noqa: F811
    ruta = _mobile(entorno)
    antes = _por_guia(ruta)
    r = reparar_documento_focal_con_valores_conocidos(
        raiz_atlas=entorno["raiz"], archivo=MOBILE_A, numero_guia="500001",
        valores={"obra_destino": "OBRA NUEVA"}, dry_run=False, reconciliar=False)
    assert (r["archivo"], r["numero_guia"]) == (MOBILE_A, "500001")
    despues = _por_guia(ruta)
    assert despues["500001"]["obra_destino"] == "OBRA NUEVA"
    assert despues["500002"] == antes["500002"]  # B lógicamente intacta


def test_guia_contradictoria_no_escribe_nada(entorno):  # noqa: F811
    ruta = _mobile(entorno)
    sha = hashlib.sha256(ruta.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match=FILA_CONTRADICE_GUIA):
        reparar_documento_focal_con_valores_conocidos(
            raiz_atlas=entorno["raiz"], archivo=MOBILE_A, numero_guia="500002",
            valores={"obra_destino": "OBRA NUEVA"}, dry_run=False, reconciliar=False)
    with pytest.raises(ValueError, match=FILA_AMBIGUA):
        reparar_documento_focal_con_valores_conocidos(
            raiz_atlas=entorno["raiz"], archivo="original.jpg",
            valores={"obra_destino": "OBRA NUEVA"}, dry_run=False, reconciliar=False)
    assert hashlib.sha256(ruta.read_bytes()).hexdigest() == sha  # byte a byte


def test_accion_controlada_audita_la_misma_guia_que_modifica(entorno):  # noqa: F811
    ruta = _mobile(entorno)
    antes = _por_guia(ruta)
    capa = CapaAccionesOperacionales(entorno["raiz"])
    capa._revalidar_guias = lambda guias: {"ejecutado": True}
    preview = capa.previsualizar("DOCUMENTO_CORREGIR_CAMPO",
                                 {"numero_guia": "500001", "campo": "obra_destino", "valor": "OBRA NUEVA"},
                                 actor="B1", origen="B1")
    assert preview["estado"] == "PREVIEW", preview
    assert preview["entidad"]["numero_guia"] == "500001" and preview["entidad"]["id"] == MOBILE_A
    resultado = capa.ejecutar(preview["token"], actor="B1", origen="B1", confirmado_por="JAVIER")
    assert resultado["estado"] == "APLICADA", resultado
    despues = _por_guia(ruta)
    assert despues["500001"]["obra_destino"] == "OBRA NUEVA"
    assert despues["500002"] == antes["500002"]
    auditoria = capa.auditoria()[-1]
    assert auditoria["entidad"]["numero_guia"] == "500001" and auditoria["entidad"]["id"] == MOBILE_A
    ledger = json.loads((entorno["actual"] / "decisiones_aplicadas.json").read_text(encoding="utf-8"))["aplicaciones"]
    correccion = [a for a in ledger if a["tipo"] == TIPO_LEDGER_CORRECCION][-1]
    assert correccion["documento"]["archivo"] == MOBILE_A and correccion["documento"]["numero_guia"] == "500001"
    assert correccion["valor_documental"] == antes["500001"]["obra_destino"]  # antes de A, no de B
