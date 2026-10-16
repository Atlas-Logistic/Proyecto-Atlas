"""Caso real 482136 -- un chofer confirmado por un humano en Revisión
(CHOFER_CANDIDATO/CONFIRMAR) debe retirar ``CHOFER_SIN_CORROBORAR`` y
sincronizar el RUT de ESE documento, aunque el ``rut_chofer`` extraído sea
un RUT válido distinto ("10800-6", sacado de la dirección "MELIPILLA
10800"). La confirmación vale sólo para la misma guía, la misma lectura de
nombre y un chofer activo del catálogo; la lectura original queda en el
ledger.
"""

from __future__ import annotations

import csv
import json

from atlas_core.aplicacion_decisiones import resolver_choferes_confirmados_por_ledger
from atlas_core.procesamiento_masivo import COLUMNAS
from atlas_core.revalidacion_documental import revalidar_chofer_sin_corroborar_por_catalogo_sin_ocr

CATALOGO = {"180915885": {"nombre": "SALOMÓN PIZARRO", "activo": True, "aliases": []}}


def _fila(**over):
    fila = {c: "" for c in COLUMNAS}
    fila.update({
        "archivo": "mobile/e9ad/original.jpg", "estado_procesamiento": "OK", "numero_guia": "482136",
        "numero_transporte": "0000363876", "chofer": "SALOMÓN PIZARRO", "rut_chofer": "10800-6",
        "estado_ruta": "RUTA_CALCULADA", "motivos_revision_documento": "CHOFER_SIN_CORROBORAR",
        "indicador_revision": "REVISAR", "estado_documental": "REQUIERE_REVISION",
        "estado_operacional": "REQUIERE_REVISION", "metodos_recuperacion_documento": "GEOMETRICO",
    })
    fila.update(over)
    return fila


def _confirmacion(**over):
    aplicacion = {
        "decision_id": "d1", "tipo": "CHOFER_CANDIDATO", "accion": "CONFIRMAR", "actor": "OPERADOR",
        "documento": {"archivo": "original.jpg", "numero_guia": "482136", "numero_transporte": "0000363876"},
        "campo": "chofer", "valor_documental": "SALOMÓN PIZARRO", "rut_documental": "10800-6",
        "chofer_confirmado": {"rut": "18091588-5", "nombre": "SALOMÓN PIZARRO"},
    }
    aplicacion.update(over)
    return aplicacion


def _raiz(tmp_path, *, filas, aplicaciones, choferes=CATALOGO):
    raiz = tmp_path / "Atlas"
    actual = raiz / "operacion" / "actual"
    actual.mkdir(parents=True)
    (raiz / "catalogos_privados").mkdir(parents=True)
    with (actual / "analisis_completo_guias.csv").open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader(); escritor.writerows(filas)
    (raiz / "catalogos_privados" / "choferes.json").write_text(json.dumps(choferes), encoding="utf-8")
    (actual / "decisiones_aplicadas.json").write_text(json.dumps({"aplicaciones": aplicaciones}), encoding="utf-8")
    return raiz


def _leer(raiz):
    with (raiz / "operacion" / "actual" / "analisis_completo_guias.csv").open(newline="", encoding="utf-8-sig") as archivo:
        return {f["numero_guia"]: f for f in csv.DictReader(archivo, delimiter=";")}


def test_confirmacion_humana_corrobora_pese_a_rut_extraido_contradictorio(tmp_path):
    raiz = _raiz(tmp_path, filas=[_fila()], aplicaciones=[_confirmacion()])
    ledger_antes = (raiz / "operacion" / "actual" / "decisiones_aplicadas.json").read_text(encoding="utf-8")
    catalogo_antes = (raiz / "catalogos_privados" / "choferes.json").read_text(encoding="utf-8")

    resultado = revalidar_chofer_sin_corroborar_por_catalogo_sin_ocr(raiz_atlas=raiz)

    assert resultado["guias_actualizadas"] == ["482136"]
    fila = _leer(raiz)["482136"]
    assert fila["chofer"] == "SALOMÓN PIZARRO"
    assert fila["rut_chofer"].replace(".", "") == "18091588-5"
    assert fila["motivos_revision_documento"] == ""
    assert fila["estado_documental"] == "OK"
    assert "CATALOGO" in fila["metodos_recuperacion_documento"]
    # la lectura original sigue auditada en el ledger; ni ledger ni catálogo cambian
    assert (raiz / "operacion" / "actual" / "decisiones_aplicadas.json").read_text(encoding="utf-8") == ledger_antes
    assert json.loads(ledger_antes)["aplicaciones"][0]["rut_documental"] == "10800-6"
    assert (raiz / "catalogos_privados" / "choferes.json").read_text(encoding="utf-8") == catalogo_antes
    assert revalidar_chofer_sin_corroborar_por_catalogo_sin_ocr(raiz_atlas=raiz)["guias_actualizadas"] == []


def test_sin_confirmacion_el_rut_contradictorio_sigue_bloqueando(tmp_path):
    raiz = _raiz(tmp_path, filas=[_fila()], aplicaciones=[])
    assert revalidar_chofer_sin_corroborar_por_catalogo_sin_ocr(raiz_atlas=raiz)["guias_actualizadas"] == []
    assert _leer(raiz)["482136"]["rut_chofer"] == "10800-6"


def test_confirmacion_de_otra_guia_no_se_extiende(tmp_path):
    filas = [_fila(), _fila(numero_guia="482999", archivo="otra.jpg")]
    confirmacion = _confirmacion(documento={"archivo": "x", "numero_guia": "482999", "numero_transporte": "1"})
    raiz = _raiz(tmp_path, filas=filas, aplicaciones=[confirmacion])
    assert revalidar_chofer_sin_corroborar_por_catalogo_sin_ocr(raiz_atlas=raiz)["guias_actualizadas"] == ["482999"]
    assert _leer(raiz)["482136"]["motivos_revision_documento"] == "CHOFER_SIN_CORROBORAR"


def test_lectura_distinta_a_la_confirmada_no_corrobora(tmp_path):
    raiz = _raiz(tmp_path, filas=[_fila(chofer="OTRO NOMBRE")], aplicaciones=[_confirmacion()])
    assert revalidar_chofer_sin_corroborar_por_catalogo_sin_ocr(raiz_atlas=raiz)["guias_actualizadas"] == []


def test_chofer_confirmado_inactivo_no_corrobora(tmp_path):
    catalogo = {"180915885": {"nombre": "SALOMÓN PIZARRO", "activo": False}}
    raiz = _raiz(tmp_path, filas=[_fila()], aplicaciones=[_confirmacion()], choferes=catalogo)
    assert revalidar_chofer_sin_corroborar_por_catalogo_sin_ocr(raiz_atlas=raiz)["guias_actualizadas"] == []


def test_indice_ignora_rechazos_y_aplicaciones_sin_chofer_confirmado(tmp_path):
    ruta = tmp_path / "ledger.json"
    ruta.write_text(json.dumps({"aplicaciones": [
        _confirmacion(),
        _confirmacion(accion="NO_CONFIRMAR", chofer_confirmado=None,
                      documento={"numero_guia": "1"}),
        {"tipo": "CLIENTE_CANDIDATO", "accion": "CONFIRMAR", "documento": {"numero_guia": "2"}},
    ]}), encoding="utf-8")
    assert resolver_choferes_confirmados_por_ledger(ruta) == {"482136": ("SALOMÓN PIZARRO", "18091588-5")}
    assert resolver_choferes_confirmados_por_ledger(tmp_path / "no_existe.json") == {}
