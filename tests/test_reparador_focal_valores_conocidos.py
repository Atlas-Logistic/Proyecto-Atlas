"""Bloque CIERRE FOCAL PIZARRO+TORRES -- `reparar_documento_focal_con_
valores_conocidos`. Puramente sintético, nunca toca G:."""
from __future__ import annotations

import json

import pytest

from atlas_core import reprocesamiento_reparador as m
from atlas_core.procesamiento_masivo import COLUMNAS
from atlas_core.revalidacion_documental import _escribir_filas_completas, _leer_filas


def _raiz(tmp_path):
    raiz = tmp_path / "atlas"
    (raiz / "operacion" / "actual").mkdir(parents=True)
    return raiz


def _fila_base(**overrides):
    fila = {columna: "" for columna in COLUMNAS}
    fila.update({
        "archivo": "473442.jpeg", "numero_guia": "473442", "numero_transporte": "0000357091",
        "estado_procesamiento": "OK", "motivos_revision_documento": "", "indicador_revision": "OK",
        "estado_documental": "OK", "estado_operacional": "OK", "estado_ruta": "",
    })
    fila.update(overrides)
    return fila


def _escribir_dataset(raiz, filas):
    dataset = raiz / "operacion" / "actual" / "analisis_completo_guias.csv"
    _escribir_filas_completas(dataset, filas)
    return dataset


def _escribir_ledger(raiz, aplicaciones):
    ledger = raiz / "operacion" / "actual" / "decisiones_aplicadas.json"
    ledger.write_text(json.dumps({"aplicaciones": aplicaciones}), encoding="utf-8")


def test_persiste_valores_autorizados_y_retira_motivo(tmp_path):
    raiz = _raiz(tmp_path)
    fila = _fila_base(
        cliente="No encontrado", rut_cliente="No encontrado",
        motivos_revision_documento="CLIENTE_AUSENTE | RUT_CLIENTE_INVALIDO",
    )
    _escribir_dataset(raiz, [fila])
    _escribir_ledger(raiz, [])

    resultado = m.reparar_documento_focal_con_valores_conocidos(
        raiz_atlas=raiz, archivo="473442.jpeg", dry_run=False,
        valores={
            "cliente": "TORRES OCARANZA LTDA", "rut_cliente": "50.234.350-5",
            "codigo_cliente": "0001004443", "cod_destinatario": "0001004443",
            "obra_destino": "TORRES OCARANZA LTDA", "despachar_a_crudo": "VISTA CLARA 2351 CERRILLOS",
        },
    )
    assert resultado["campos_cambiados_total"] == 6
    filas_tras = _leer_filas(raiz / "operacion" / "actual" / "analisis_completo_guias.csv")
    fila_tras = filas_tras[0]
    assert fila_tras["cliente"] == "TORRES OCARANZA LTDA"
    assert fila_tras["rut_cliente"] == "50.234.350-5"
    assert fila_tras["codigo_cliente"] == "0001004443"
    assert fila_tras["cod_destinatario"] == "0001004443"
    assert fila_tras["obra_destino"] == "TORRES OCARANZA LTDA"
    assert fila_tras["despachar_a_crudo"] == "VISTA CLARA 2351 CERRILLOS"
    assert "CLIENTE_AUSENTE" not in fila_tras["motivos_revision_documento"]
    assert "RUT_CLIENTE_INVALIDO" not in fila_tras["motivos_revision_documento"]


def test_dry_run_no_escribe_nada(tmp_path):
    raiz = _raiz(tmp_path)
    _escribir_dataset(raiz, [_fila_base(cliente="No encontrado")])
    _escribir_ledger(raiz, [])
    resultado = m.reparar_documento_focal_con_valores_conocidos(
        raiz_atlas=raiz, archivo="473442.jpeg", dry_run=True,
        valores={"cliente": "TORRES OCARANZA LTDA"},
    )
    assert resultado["campos_cambiados_total"] == 1
    filas_tras = _leer_filas(raiz / "operacion" / "actual" / "analisis_completo_guias.csv")
    assert filas_tras[0]["cliente"] == "No encontrado"


def test_ignora_campos_no_autorizados(tmp_path):
    raiz = _raiz(tmp_path)
    _escribir_dataset(raiz, [_fila_base(chofer="ORIGINAL", numero_transporte="0000000001")])
    _escribir_ledger(raiz, [])
    resultado = m.reparar_documento_focal_con_valores_conocidos(
        raiz_atlas=raiz, archivo="473442.jpeg", dry_run=False,
        valores={"chofer": "OTRO CHOFER", "numero_transporte": "0000999999"},
    )
    assert resultado["campos_ignorados_no_autorizados"] == ["chofer", "numero_transporte"]
    assert resultado["campos_cambiados_total"] == 0
    filas_tras = _leer_filas(raiz / "operacion" / "actual" / "analisis_completo_guias.csv")
    assert filas_tras[0]["chofer"] == "ORIGINAL"
    assert filas_tras[0]["numero_transporte"] == "0000000001"


def test_patente_tracto_y_rampla_estan_autorizados_y_estructuralmente_validados(tmp_path):
    """Bloque ASIGNACIONES CANÓNICAS CHOFER->VEHÍCULO: a diferencia de
    otros campos, patente_tracto/patente_rampla SÍ están autorizados --
    pero siguen exigiendo formato estructural válido, nunca aceptan
    cualquier texto."""
    raiz = _raiz(tmp_path)
    _escribir_dataset(raiz, [_fila_base(patente_tracto="1G8925", patente_rampla="No encontrado")])
    _escribir_ledger(raiz, [])
    resultado = m.reparar_documento_focal_con_valores_conocidos(
        raiz_atlas=raiz, archivo="473442.jpeg", dry_run=False,
        valores={"patente_tracto": "TG8925", "patente_rampla": "NO-ES-PATENTE"},
    )
    assert resultado["campos_ignorados_no_autorizados"] == []
    assert [c["campo"] for c in resultado["cambios"]] == ["patente_tracto"]
    filas_tras = _leer_filas(raiz / "operacion" / "actual" / "analisis_completo_guias.csv")
    assert filas_tras[0]["patente_tracto"] == "TG8925"
    assert filas_tras[0]["patente_rampla"] == "No encontrado"  # valor inválido nunca se promueve


def test_ledger_bloquea_campo_confirmado_por_humano(tmp_path):
    raiz = _raiz(tmp_path)
    _escribir_dataset(raiz, [_fila_base(cliente="OTRA COSA CONFIRMADA")])
    _escribir_ledger(raiz, [
        {"documento": {"archivo": "473442.jpeg", "numero_guia": "473442"}, "campo": "cliente", "valor": "OTRA COSA CONFIRMADA"},
    ])
    resultado = m.reparar_documento_focal_con_valores_conocidos(
        raiz_atlas=raiz, archivo="473442.jpeg", dry_run=False,
        valores={"cliente": "TORRES OCARANZA LTDA"},
    )
    assert resultado["campos_bloqueados_por_ledger"] == ["cliente"]
    assert resultado["campos_cambiados_total"] == 0
    filas_tras = _leer_filas(raiz / "operacion" / "actual" / "analisis_completo_guias.csv")
    assert filas_tras[0]["cliente"] == "OTRA COSA CONFIRMADA"


def test_rut_estructuralmente_invalido_nunca_se_promueve(tmp_path):
    raiz = _raiz(tmp_path)
    _escribir_dataset(raiz, [_fila_base(rut_cliente="No encontrado")])
    _escribir_ledger(raiz, [])
    resultado = m.reparar_documento_focal_con_valores_conocidos(
        raiz_atlas=raiz, archivo="473442.jpeg", dry_run=False,
        valores={"rut_cliente": "NO-ES-UN-RUT"},
    )
    assert resultado["campos_cambiados_total"] == 0


def test_archivo_inexistente_lanza_error_sin_crear_fila(tmp_path):
    raiz = _raiz(tmp_path)
    _escribir_dataset(raiz, [_fila_base()])
    _escribir_ledger(raiz, [])
    with pytest.raises(ValueError):
        m.reparar_documento_focal_con_valores_conocidos(
            raiz_atlas=raiz, archivo="no_existe.jpeg", dry_run=False, valores={"cliente": "X"},
        )
    filas_tras = _leer_filas(raiz / "operacion" / "actual" / "analisis_completo_guias.csv")
    assert len(filas_tras) == 1  # nunca crea una fila nueva


def test_valor_igual_al_actual_no_cuenta_como_cambio(tmp_path):
    raiz = _raiz(tmp_path)
    _escribir_dataset(raiz, [_fila_base(cliente="TORRES OCARANZA LTDA")])
    _escribir_ledger(raiz, [])
    resultado = m.reparar_documento_focal_con_valores_conocidos(
        raiz_atlas=raiz, archivo="473442.jpeg", dry_run=False,
        valores={"cliente": "TORRES OCARANZA LTDA"},
    )
    assert resultado["campos_cambiados_total"] == 0
