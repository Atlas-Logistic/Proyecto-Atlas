"""Bloque FIX RUT DOCUMENTAL / ID PLACEHOLDER -- caso real WLADIMIR
AGUILAR (viaje 0000354443, ID interno de catálogo `PENDIENTE00000006`,
sin RUT canónico separado).

Un ID interno placeholder NO debe impedir corroborar una entidad activa
única y conocida cuando el documento trae un RUT estructuralmente válido
y no contradictorio. Nunca desambigua por fuzzy, nunca acepta un RUT
contradictorio, nunca crea un segundo chofer.
"""

from __future__ import annotations

import csv
import json

from atlas_core.catalogos import (
    corroborar_chofer_por_nombre_y_rut_documental,
    rut_canonico_de_registro_chofer,
)
from atlas_core.procesamiento_masivo import COLUMNAS
from atlas_core.revalidacion_documental import (
    revalidar_chofer_sin_corroborar_por_catalogo_sin_ocr,
)

RUT_WLADIMIR = "26.646.499-1"
CAT_PLACEHOLDER = {
    "PENDIENTE00000006": {
        "nombre": "WLADIMIR AGUILAR", "activo": True,
        "aliases": ["WLADIKIR AGUILAR", "RLADIMIR AGUILAR"],
    },
    "10833150K": {"nombre": "JOSE LAZCANO", "activo": True},
}


# --------------------------------------------------------------------------
# helper puro
# --------------------------------------------------------------------------

def test_rut_canonico_placeholder_es_none_pero_id_rut_real_se_extrae():
    assert rut_canonico_de_registro_chofer("PENDIENTE00000006", {"nombre": "X", "activo": True}) is None
    assert rut_canonico_de_registro_chofer("10833150K", {"nombre": "X"}) == "10.833.150-K"
    # campo `rut` explícito (mecanismo aditivo para separar ID de RUT)
    assert rut_canonico_de_registro_chofer(
        "PENDIENTE00000006", {"nombre": "X", "rut": "26.646.499-1"}
    ) == RUT_WLADIMIR


def test_1_id_placeholder_mas_rut_documental_valido_corrobora():
    assert corroborar_chofer_por_nombre_y_rut_documental(
        CAT_PLACEHOLDER, "WLADIMIR AGUILAR", RUT_WLADIMIR
    ) == ("WLADIMIR AGUILAR", RUT_WLADIMIR)
    # también por alias exacto -> nombre canónico
    assert corroborar_chofer_por_nombre_y_rut_documental(
        CAT_PLACEHOLDER, "WLADIKIR AGUILAR", RUT_WLADIMIR
    ) == ("WLADIMIR AGUILAR", RUT_WLADIMIR)


def test_2_rut_contradictorio_sigue_bloqueando():
    # entidad CON RUT canónico (ID es un RUT real) + RUT documental VÁLIDO
    # DISTINTO -> no se corrobora (contradicción, nunca en silencio).
    assert corroborar_chofer_por_nombre_y_rut_documental(
        CAT_PLACEHOLDER, "JOSE LAZCANO", RUT_WLADIMIR
    ) is None
    # entidad con campo `rut` X + documento con RUT válido Y != X -> bloquea
    cat = {"PENDIENTE00000006": {"nombre": "WLADIMIR AGUILAR", "activo": True, "rut": "12.345.678-5"}}
    assert corroborar_chofer_por_nombre_y_rut_documental(cat, "WLADIMIR AGUILAR", RUT_WLADIMIR) is None
    # ID placeholder + RUT documental INVÁLIDO -> sigue bloqueando
    assert corroborar_chofer_por_nombre_y_rut_documental(
        CAT_PLACEHOLDER, "WLADIMIR AGUILAR", "55.555.555-5"
    ) is None
    # ID placeholder + RUT documental ausente -> bloquea
    assert corroborar_chofer_por_nombre_y_rut_documental(
        CAT_PLACEHOLDER, "WLADIMIR AGUILAR", ""
    ) is None


def test_3_dos_entidades_competitivas_no_autoconfirma():
    cat = dict(CAT_PLACEHOLDER)
    cat["PENDIENTE00000099"] = {"nombre": "WLADIMIR AGUILAR", "activo": True}
    assert corroborar_chofer_por_nombre_y_rut_documental(cat, "WLADIMIR AGUILAR", RUT_WLADIMIR) is None
    # nombre desconocido -> None
    assert corroborar_chofer_por_nombre_y_rut_documental(CAT_PLACEHOLDER, "PEDRO PICAPIEDRA", RUT_WLADIMIR) is None


def test_2b_entidad_con_rut_canonico_y_documental_consistente_corrobora_con_el_canonico():
    assert corroborar_chofer_por_nombre_y_rut_documental(
        CAT_PLACEHOLDER, "JOSE LAZCANO", "10.833.150-K"
    ) == ("JOSE LAZCANO", "10.833.150-K")


# --------------------------------------------------------------------------
# revalidador _sin_ocr (reconciliación de filas ya persistidas)
# --------------------------------------------------------------------------

def _fila(**over):
    fila = {c: "" for c in COLUMNAS}
    fila.update({
        "archivo": "x.jpeg", "estado_procesamiento": "OK", "numero_guia": "1",
        "numero_transporte": "0000354443", "chofer": "WLADIMIR AGUILAR",
        "rut_chofer": RUT_WLADIMIR, "patente_tracto": "AL1879",
        "estado_ruta": "RUTA_CALCULADA", "estado_entrega": "RESUELTO",
        "motivos_revision_documento": "CHOFER_SIN_CORROBORAR",
        "indicador_revision": "REVISAR", "estado_documental": "REQUIERE_REVISION",
        "estado_operacional": "REQUIERE_REVISION",
        "metodos_recuperacion_documento": "GEOMETRICO | HOMOLOGADO",
    })
    fila.update(over)
    return fila


def _raiz(tmp_path, *, filas, choferes):
    raiz = tmp_path / "Atlas"
    actual = raiz / "operacion" / "actual"
    actual.mkdir(parents=True)
    (raiz / "catalogos_privados").mkdir(parents=True)
    with (actual / "analisis_completo_guias.csv").open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader(); escritor.writerows(filas)
    (raiz / "catalogos_privados" / "choferes.json").write_text(json.dumps(choferes), encoding="utf-8")
    return raiz


def _leer(raiz):
    with (raiz / "operacion" / "actual" / "analisis_completo_guias.csv").open(
        newline="", encoding="utf-8-sig"
    ) as archivo:
        return {f["numero_guia"]: f for f in csv.DictReader(archivo, delimiter=";")}


def test_revalidador_corrobora_placeholder_y_no_toca_catalogo_ni_crea_duplicado(tmp_path):
    filas = [
        _fila(numero_guia="472238"),
        _fila(numero_guia="472239", archivo="472239.jpeg"),
        # otra fila con motivo distinto -- nunca se toca
        _fila(numero_guia="900", archivo="900.jpeg", chofer="OTRO CHOFER",
              motivos_revision_documento="OBRA_DESTINO_SIN_CORROBORAR"),
    ]
    catalogo = json.loads(json.dumps(CAT_PLACEHOLDER))
    raiz = _raiz(tmp_path, filas=filas, choferes=catalogo)
    catalogo_antes = (raiz / "catalogos_privados" / "choferes.json").read_text(encoding="utf-8")

    resultado = revalidar_chofer_sin_corroborar_por_catalogo_sin_ocr(raiz_atlas=raiz)

    assert sorted(resultado["guias_actualizadas"]) == ["472238", "472239"]  # (4) nunca la fila 900
    por_guia = _leer(raiz)
    for g in ("472238", "472239"):
        assert por_guia[g]["motivos_revision_documento"] == ""
        assert por_guia[g]["indicador_revision"] == "OK"
        assert por_guia[g]["estado_operacional"] == "OK"
        assert por_guia[g]["rut_chofer"] == RUT_WLADIMIR
        assert "CATALOGO" in por_guia[g]["metodos_recuperacion_documento"]
    assert por_guia["900"]["motivos_revision_documento"] == "OBRA_DESTINO_SIN_CORROBORAR"
    # (4) catálogo intacto -- nunca se crea/renombra un chofer
    assert (raiz / "catalogos_privados" / "choferes.json").read_text(encoding="utf-8") == catalogo_antes

    # idempotente
    segundo = revalidar_chofer_sin_corroborar_por_catalogo_sin_ocr(raiz_atlas=raiz)
    assert segundo["guias_actualizadas"] == []


def test_revalidador_conserva_otros_motivos_de_la_misma_fila(tmp_path):
    filas = [_fila(numero_guia="472126", numero_transporte="No encontrado",
                   motivos_revision_documento="CHOFER_SIN_CORROBORAR | TRANSPORTE_AUSENTE")]
    raiz = _raiz(tmp_path, filas=filas, choferes=json.loads(json.dumps(CAT_PLACEHOLDER)))
    resultado = revalidar_chofer_sin_corroborar_por_catalogo_sin_ocr(raiz_atlas=raiz)
    assert resultado["guias_actualizadas"] == ["472126"]
    fila = _leer(raiz)["472126"]
    assert fila["motivos_revision_documento"] == "TRANSPORTE_AUSENTE"
    assert fila["indicador_revision"] == "REVISAR"  # TRANSPORTE_AUSENTE sigue bloqueando


def test_revalidador_no_corrobora_rut_documental_contradictorio(tmp_path):
    filas = [_fila(numero_guia="1", chofer="JOSE LAZCANO", rut_chofer=RUT_WLADIMIR)]
    raiz = _raiz(tmp_path, filas=filas, choferes=json.loads(json.dumps(CAT_PLACEHOLDER)))
    resultado = revalidar_chofer_sin_corroborar_por_catalogo_sin_ocr(raiz_atlas=raiz)
    assert resultado["guias_actualizadas"] == []
    assert _leer(raiz)["1"]["motivos_revision_documento"] == "CHOFER_SIN_CORROBORAR"


def test_revalidador_no_corrobora_con_dos_entidades_competitivas(tmp_path):
    catalogo = json.loads(json.dumps(CAT_PLACEHOLDER))
    catalogo["PENDIENTE00000099"] = {"nombre": "WLADIMIR AGUILAR", "activo": True}
    filas = [_fila(numero_guia="1")]
    raiz = _raiz(tmp_path, filas=filas, choferes=catalogo)
    resultado = revalidar_chofer_sin_corroborar_por_catalogo_sin_ocr(raiz_atlas=raiz)
    assert resultado["guias_actualizadas"] == []
    assert _leer(raiz)["1"]["motivos_revision_documento"] == "CHOFER_SIN_CORROBORAR"
