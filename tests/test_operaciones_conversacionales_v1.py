import csv
import json
from pathlib import Path

from atlas_core.operaciones_conversacionales import proponer_asociacion_chofer_vehiculo, confirmar_asociacion_chofer_vehiculo


def _entorno(tmp_path: Path, asociaciones=()):
    raiz = tmp_path / "Atlas"; cat = raiz / "catalogos_privados"; (raiz / "operacion" / "actual").mkdir(parents=True); cat.mkdir()
    cat.joinpath("choferes.json").write_text(json.dumps({"12345678-9": {"nombre": "LUIS REYES", "estado": "ACTIVO"}, "11111111-1": {"nombre": "SALOMON PIZARRO", "estado": "ACTIVO"}}), encoding="utf8")
    def v(p, rut, tipo="TRACTO"):
        campos = {"patente": p, "tipo": tipo, "observacion": ""}
        if rut:
            campos["rut_chofer_asociado"] = rut
        return {"vehiculo_id": p, "patente_canonica": p, "tipo": tipo, "estado_calidad": "CONFIRMADO", "estado_vigencia": "ACTIVO", "aliases": [], "evidencias": [{"tipo":"CONFIRMACION_HUMANA","identificador_fuente":"TEST","referencia_hash":"","campos_observados":campos,"fecha":"2026-01-01T00:00:00+00:00","actor_proceso":"TEST","resultado":"SOPORTA"}], "procedencia":"CONFIRMACION_HUMANA","confirmado_por":"TEST","fecha_confirmacion":"2026-01-01T00:00:00+00:00","observaciones":"","fecha_creacion":"2026-01-01T00:00:00+00:00","fecha_modificacion":"2026-01-01T00:00:00+00:00"}
    asociaciones = set(asociaciones)
    ruts = {"KN5439": "123456789", "TG8925": "123456789", "JF9575": "111111111"}
    def rut_asociado(patente):
        return ruts[patente] if patente in asociaciones else ""
    cat.joinpath("vehiculos.json").write_text(json.dumps({"version":1,"vehiculos":[v("KN5439", rut_asociado("KN5439")), v("TG8925", rut_asociado("TG8925")), v("JF9575", rut_asociado("JF9575"), "CARRO")] }), encoding="utf8")
    return raiz


def test_preview_confirmacion_e_idempotencia(tmp_path):
    raiz = _entorno(tmp_path)
    p = proponer_asociacion_chofer_vehiculo(raiz_atlas=raiz, texto="asocia KN5439 a Luis Reyes")
    assert p["estado"] == "PREVIEW" and not (raiz / "operacion" / "actual" / "operaciones_conversacionales.json").exists()
    r = confirmar_asociacion_chofer_vehiculo(raiz_atlas=raiz, propuesta=p, actor="JAVIER")
    assert r["estado"] == "APLICADA" and r["aplicado"]
    assert confirmar_asociacion_chofer_vehiculo(raiz_atlas=raiz, propuesta=p, actor="JAVIER")["idempotente"]


def test_abstiene_patente_y_chofer_invalidos(tmp_path):
    raiz = _entorno(tmp_path)
    assert proponer_asociacion_chofer_vehiculo(raiz_atlas=raiz, texto="asocia XX a Luis Reyes")["estado"] == "ABSTENCION"
    assert proponer_asociacion_chofer_vehiculo(raiz_atlas=raiz, texto="asocia KN5439 a Nadie")["estado"] == "ABSTENCION"


def test_variantes_de_orden_producen_preview_sin_escritura(tmp_path):
    raiz = _entorno(tmp_path)
    ledger = raiz / "operacion" / "actual" / "operaciones_conversacionales.json"
    for texto in (
        "El tracto de Luis Reyes es KN5439",
        "el camión de Luis Reyes es KN5439",
        "Luis Reyes usa KN5439",
    ):
        propuesta = proponer_asociacion_chofer_vehiculo(raiz_atlas=raiz, texto=texto)
        assert propuesta["estado"] == "PREVIEW"
        assert propuesta["objetivo"]["chofer"] == "LUIS REYES"
        assert propuesta["cambios_tipados"] == {
            "rut_chofer": "123456789", "patente": "KN5439", "tipo": "TRACTO",
        }
    assert not ledger.exists()  # proponer nunca confirma ni escribe


def test_referencia_contextual_por_apellido_llega_a_preview_sin_escritura(tmp_path):
    raiz = _entorno(tmp_path)
    ledger = raiz / "operacion" / "actual" / "operaciones_conversacionales.json"
    propuesta = proponer_asociacion_chofer_vehiculo(
        raiz_atlas=raiz, texto="Pizarro usa la patente JF9575."
    )
    assert propuesta["estado"] == "PREVIEW"
    assert propuesta["objetivo"]["chofer"] == "SALOMON PIZARRO"
    assert propuesta["cambios_tipados"] == {
        "rut_chofer": "111111111", "patente": "JF9575", "tipo": "RAMPLA",
    }
    assert not ledger.exists()


def test_asociacion_rampla_ya_canonica_devuelve_sin_cambios_sin_escribir_ni_revalidar(tmp_path):
    raiz = _entorno(tmp_path, asociaciones=("JF9575",))
    ledger = raiz / "operacion" / "actual" / "operaciones_conversacionales.json"
    respuesta = proponer_asociacion_chofer_vehiculo(raiz_atlas=raiz, texto="Pizarro usa la patente JF9575.")
    assert respuesta["estado"] == "SIN_CAMBIOS"
    assert respuesta["asignacion_actual"] == "RAMPLA JF9575"
    assert respuesta["acciones"] == []
    assert not ledger.exists()
    assert not (raiz / "operacion" / "actual" / "decisiones_pendientes.json").exists()


def test_asociacion_tracto_ya_canonica_devuelve_sin_cambios(tmp_path):
    raiz = _entorno(tmp_path, asociaciones=("KN5439",))
    respuesta = proponer_asociacion_chofer_vehiculo(raiz_atlas=raiz, texto="Luis Reyes usa KN5439")
    assert respuesta["estado"] == "SIN_CAMBIOS"
    assert respuesta["asignacion_actual"] == "TRACTO KN5439"


def test_asociacion_distinta_sigue_generando_preview(tmp_path):
    raiz = _entorno(tmp_path, asociaciones=("KN5439",))
    respuesta = proponer_asociacion_chofer_vehiculo(raiz_atlas=raiz, texto="Luis Reyes usa TG8925")
    assert respuesta["estado"] == "PREVIEW"


def test_reintento_post_aplicacion_es_sin_cambios_y_no_agrega_auditoria(tmp_path):
    raiz = _entorno(tmp_path)
    primera = proponer_asociacion_chofer_vehiculo(raiz_atlas=raiz, texto="Pizarro usa la patente JF9575.")
    assert confirmar_asociacion_chofer_vehiculo(raiz_atlas=raiz, propuesta=primera, actor="JAVIER")["estado"] == "APLICADA"
    ledger = raiz / "operacion" / "actual" / "operaciones_conversacionales.json"
    auditoria_antes = ledger.read_bytes()
    reintento = proponer_asociacion_chofer_vehiculo(raiz_atlas=raiz, texto="Pizarro usa la patente JF9575.")
    assert reintento["estado"] == "SIN_CAMBIOS"
    assert ledger.read_bytes() == auditoria_antes


def test_tipo_explicito_se_valida_contra_catalogo_y_carro_llega_a_rampla(tmp_path):
    raiz = _entorno(tmp_path)
    correcto = proponer_asociacion_chofer_vehiculo(
        raiz_atlas=raiz, texto="La rampla de Pizarro usa JF9575"
    )
    assert correcto["estado"] == "PREVIEW"
    assert correcto["cambios_tipados"]["tipo"] == "RAMPLA"
    carro = proponer_asociacion_chofer_vehiculo(
        raiz_atlas=raiz, texto="El carro de Pizarro usa JF9575"
    )
    assert carro["estado"] == "PREVIEW"
    assert carro["cambios_tipados"]["tipo"] == "RAMPLA"
    incorrecto = proponer_asociacion_chofer_vehiculo(
        raiz_atlas=raiz, texto="El tracto de Pizarro usa JF9575"
    )
    assert incorrecto["estado"] == "ABSTENCION"
    assert "es CARRO, no TRACTO" in incorrecto["mensaje"]


def test_referencia_contextual_ambigua_expone_eleccion_y_no_aplica(tmp_path):
    raiz = _entorno(tmp_path)
    ruta = raiz / "catalogos_privados" / "choferes.json"
    choferes = json.loads(ruta.read_text(encoding="utf8"))
    choferes["22222222-2"] = {"nombre": "PEDRO PIZARRO", "activo": True}
    ruta.write_text(json.dumps(choferes), encoding="utf8")
    respuesta = proponer_asociacion_chofer_vehiculo(raiz_atlas=raiz, texto="Pizarro usa JF9575")
    assert respuesta["estado"] == "ABSTENCION"
    assert respuesta["candidatos"] == ["PEDRO PIZARRO", "SALOMON PIZARRO"]
    assert respuesta["acciones"] == ["ELEGIR_CHOFER", "CANCELAR"]


def test_referencia_con_tilde_y_error_leve_unica_se_resuelve(tmp_path):
    raiz = _entorno(tmp_path)
    propuesta = proponer_asociacion_chofer_vehiculo(raiz_atlas=raiz, texto="Pizárr0 utiliza JF9575")
    assert propuesta["estado"] == "PREVIEW"
    assert propuesta["objetivo"]["chofer"] == "SALOMON PIZARRO"


def test_obsoleta_si_cambia_catalogo(tmp_path):
    raiz = _entorno(tmp_path); p = proponer_asociacion_chofer_vehiculo(raiz_atlas=raiz, texto="asocia KN5439 a Luis Reyes")
    ruta = raiz / "catalogos_privados" / "choferes.json"; ruta.write_text(ruta.read_text() + " ", encoding="utf8")
    assert confirmar_asociacion_chofer_vehiculo(raiz_atlas=raiz, propuesta=p, actor="JAVIER")["estado"] == "OBSOLETA"


def test_confirmacion_revalida_solo_decision_tracto_afectada(tmp_path):
    raiz = _entorno(tmp_path); actual = raiz / "operacion" / "actual"
    ruta_csv = actual / "analisis_completo_guias.csv"
    campos = ["archivo", "numero_guia", "chofer", "rut_chofer"]
    with ruta_csv.open("w", newline="", encoding="utf8") as salida:
        w = csv.DictWriter(salida, fieldnames=campos, delimiter=";"); w.writeheader()
        w.writerows([
            {"archivo": "a.jpeg", "numero_guia": "1", "chofer": "LUIS REYES", "rut_chofer": "12345678-9"},
            {"archivo": "b.jpeg", "numero_guia": "2", "chofer": "LUIS REYES", "rut_chofer": "12345678-9"},
        ])
    def d(ident, archivo, campo):
        return {"decision_id": ident, "tipo": "VEHICULO_DESCONOCIDO", "campo": campo,
                "documento": {"archivo": archivo, "numero_guia": archivo[0]}}
    bandeja = actual / "decisiones_pendientes.json"
    bandeja.write_text(json.dumps({"decisiones": [d("tracto", "a.jpeg", "patente_tracto"), d("rampla", "b.jpeg", "patente_rampla")]}), encoding="utf8")
    propuesta = proponer_asociacion_chofer_vehiculo(raiz_atlas=raiz, texto="El tracto de Luis Reyes es KN5439")
    respuesta = confirmar_asociacion_chofer_vehiculo(raiz_atlas=raiz, propuesta=propuesta, actor="JAVIER")
    impacto = respuesta["resultado"]["revalidacion_focal"]
    assert impacto["decisiones_retiradas"] == 1 and impacto["viajes_revalidados"] == 1
    restantes = json.loads(bandeja.read_text(encoding="utf8"))["decisiones"]
    assert [x["decision_id"] for x in restantes] == ["rampla"]  # tipo distinto, no tocado
    assert confirmar_asociacion_chofer_vehiculo(raiz_atlas=raiz, propuesta=propuesta, actor="JAVIER")["idempotente"]
