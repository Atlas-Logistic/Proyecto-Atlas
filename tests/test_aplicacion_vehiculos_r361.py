import csv
import json
from datetime import datetime, timezone

import pytest

import atlas_core.aplicacion_decisiones as modulo
from atlas_core.aplicacion_decisiones import DecisionObsoletaError, ErrorAplicacionDecision, aplicar_decision_obra
from atlas_core.catalogo_vehiculos import TipoVehiculo, cargar_catalogo_vehiculos, confirmar_vehiculo
from atlas_core.decisiones_pendientes import detectar_decisiones_documento, generar_artefacto
from atlas_core.procesamiento_masivo import COLUMNAS


def _entorno(tmp_path, *, tracto="KN5439", rampla="JF6468"):
    raiz = tmp_path / "Atlas"
    catalogos = raiz / "catalogos_privados"
    actual = raiz / "operacion" / "actual"
    catalogos.mkdir(parents=True); actual.mkdir(parents=True)
    for nombre, contenido in {
        "clientes.json": {"version_formato": 1, "clientes": []},
        "empresas.json": {}, "vehiculos.json": {"version": 1, "vehiculos": []},
        "obras_destinos.json": {"version_formato": 1, "obras": [], "relaciones": []},
        "destinos_maestros.json": {"version_formato": 1, "destinos": []},
    }.items():
        (catalogos / nombre).write_text(json.dumps(contenido), encoding="utf-8")
    dataset = actual / "analisis_completo_guias.csv"
    # R3.6.2: REGISTRAR ahora puede disparar la revalidación de
    # PATENTE_SIN_HOMOLOGAR (ver aplicacion_decisiones.py), que exige el
    # esquema oficial de columnas -- no el CSV mínimo histórico de este
    # archivo. Sin ningún motivo catalogal en la fila, la revalidación es
    # deliberadamente un no-op (no cambia nada) y no afecta las
    # aserciones de este módulo, que versan sobre el catálogo/bandeja.
    fila = {columna: "" for columna in COLUMNAS}
    fila.update({
        "archivo": "100.png", "estado_procesamiento": "OK", "numero_guia": "100",
        "numero_transporte": "T1", "patente_tracto": tracto, "patente_rampla": rampla,
        "indicador_revision": "REVISAR",
    })
    with dataset.open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader()
        escritor.writerow(fila)
    datos = {
        "número de guía": "100", "número de transporte": "T1",
        "patente del tracto": tracto, "patente del carro": rampla,
    }
    decisiones = detectar_decisiones_documento(
        archivo="100.png", datos=datos, carpeta_catalogos=catalogos,
    )
    generar_artefacto(
        ruta_dataset=dataset, carpeta_catalogos=catalogos, decisiones=decisiones,
        ruta_salida=actual / "decisiones_pendientes.json",
    )
    return raiz, catalogos, actual, decisiones


def _vehiculos(catalogos):
    return cargar_catalogo_vehiculos(catalogos / "vehiculos.json").vehiculos


def _pendientes(actual):
    return json.loads((actual / "decisiones_pendientes.json").read_text(encoding="utf-8"))["decisiones"]


def test_par_documental_clasifica_y_registra_tracto_y_carro_consecutivamente(tmp_path):
    raiz, catalogos, actual, decisiones = _entorno(tmp_path)
    por_campo = {d["campo"]: d for d in decisiones if d["tipo"] == "VEHICULO_DESCONOCIDO"}
    assert por_campo["patente_tracto"]["tipo_resolucion"] == "INEQUIVOCO"
    assert por_campo["patente_tracto"]["tipo_vehiculo_propuesto"] == "TRACTO"
    assert por_campo["patente_rampla"]["tipo_resolucion"] == "INEQUIVOCO"
    assert por_campo["patente_rampla"]["tipo_vehiculo_propuesto"] == "CARRO"

    aplicar_decision_obra(
        raiz_atlas=raiz, decision_id=por_campo["patente_tracto"]["decision_id"], accion="REGISTRAR",
    )
    aplicar_decision_obra(
        raiz_atlas=raiz, decision_id=por_campo["patente_rampla"]["decision_id"], accion="REGISTRAR",
    )
    vehiculos = {v.patente_canonica: v for v in _vehiculos(catalogos)}
    assert {p: v.tipo for p, v in vehiculos.items()} == {"KN5439": "TRACTO", "JF6468": "CARRO"}
    assert all(v.estado_calidad == "CONFIRMADO" and v.estado_vigencia == "ACTIVO" for v in vehiculos.values())
    assert all(v.confirmado_por == "JAVIER_MBT" for v in vehiculos.values())
    assert _pendientes(actual) == []
    nuevas = detectar_decisiones_documento(
        archivo="101.png", datos={"número de guía": "101", "número de transporte": "T2",
                                   "patente del tracto": "KN5439", "patente del carro": "JF6468"},
        carpeta_catalogos=catalogos,
    )
    assert not any(d["tipo"] == "VEHICULO_DESCONOCIDO" for d in nuevas)
    assert all(not hasattr(v, "chofer_id") and not hasattr(v, "conductor_asignado") for v in vehiculos.values())


def test_bandeja_legacy_vigente_se_enriquece_antes_de_aplicar(tmp_path):
    raiz, catalogos, actual, decisiones = _entorno(tmp_path)
    legacy = []
    for original in decisiones:
        decision = dict(original)
        decision.pop("tipo_resolucion", None)
        decision.pop("tipo_vehiculo_propuesto", None)
        legacy.append(decision)
    generar_artefacto(
        ruta_dataset=actual / "analisis_completo_guias.csv", carpeta_catalogos=catalogos,
        decisiones=legacy, ruta_salida=actual / "decisiones_pendientes.json",
    )
    tracto = next(d for d in legacy if d.get("campo") == "patente_tracto")
    resultado = aplicar_decision_obra(
        raiz_atlas=raiz, decision_id=tracto["decision_id"], accion="REGISTRAR",
    )
    assert resultado["tipo_vehiculo"] == "TRACTO"
    pendiente = _pendientes(actual)
    assert pendiente[0]["tipo_resolucion"] == "INEQUIVOCO"
    assert pendiente[0]["tipo_vehiculo_propuesto"] == "CARRO"


@pytest.mark.parametrize("tipo", ["TRACTO", "CAMION_RIGIDO"])
def test_tracto_aislado_exige_y_registra_tipo_humano_permitido(tmp_path, tipo):
    raiz, catalogos, actual, decisiones = _entorno(tmp_path, tracto="XF3629", rampla="No encontrado")
    decision = next(d for d in decisiones if d["tipo"] == "VEHICULO_DESCONOCIDO")
    assert decision["tipo_resolucion"] == "REQUIERE_CONFIRMACION_HUMANA"
    assert decision["tipo_vehiculo_propuesto"] is None
    with pytest.raises(ErrorAplicacionDecision, match="Seleccione Tracto o Camión rígido"):
        aplicar_decision_obra(raiz_atlas=raiz, decision_id=decision["decision_id"], accion="REGISTRAR")
    resultado = aplicar_decision_obra(
        raiz_atlas=raiz, decision_id=decision["decision_id"], accion="REGISTRAR", tipo_vehiculo=tipo,
    )
    assert resultado["tipo_vehiculo"] == tipo
    assert [(v.patente_canonica, v.tipo) for v in _vehiculos(catalogos)] == [("XF3629", tipo)]


def test_tracto_aislado_rechaza_carro(tmp_path):
    raiz, catalogos, actual, decisiones = _entorno(tmp_path, tracto="XF3629", rampla="No encontrado")
    decision = next(d for d in decisiones if d["tipo"] == "VEHICULO_DESCONOCIDO")
    with pytest.raises(ErrorAplicacionDecision):
        aplicar_decision_obra(
            raiz_atlas=raiz, decision_id=decision["decision_id"], accion="REGISTRAR", tipo_vehiculo="CARRO",
        )
    assert _vehiculos(catalogos) == ()


def test_no_registrar_no_alta_y_ledger_suprime_solo_esa_decision(tmp_path):
    raiz, catalogos, actual, decisiones = _entorno(tmp_path, tracto="XF3629", rampla="No encontrado")
    decision = next(d for d in decisiones if d["tipo"] == "VEHICULO_DESCONOCIDO")
    aplicar_decision_obra(raiz_atlas=raiz, decision_id=decision["decision_id"], accion="NO_REGISTRAR")
    assert _vehiculos(catalogos) == () and _pendientes(actual) == []
    ledger = json.loads((actual / "decisiones_aplicadas.json").read_text(encoding="utf-8"))
    assert ledger["aplicaciones"][0]["accion"] == "NO_REGISTRAR"
    nueva = detectar_decisiones_documento(
        archivo="otra.png", datos={"número de guía": "101", "número de transporte": "T2",
                                     "patente del tracto": "XF3629", "patente del carro": "No encontrado"},
        carpeta_catalogos=catalogos,
    )
    assert any(d["tipo"] == "VEHICULO_DESCONOCIDO" for d in nueva)


def test_posponer_no_escribe_y_permanece(tmp_path):
    raiz, catalogos, actual, decisiones = _entorno(tmp_path, tracto="XF3629", rampla="No encontrado")
    decision = next(d for d in decisiones if d["tipo"] == "VEHICULO_DESCONOCIDO")
    antes = (actual / "decisiones_pendientes.json").read_bytes()
    aplicar_decision_obra(raiz_atlas=raiz, decision_id=decision["decision_id"], accion="POSPONER")
    assert (actual / "decisiones_pendientes.json").read_bytes() == antes
    assert _vehiculos(catalogos) == () and not (actual / "decisiones_aplicadas.json").exists()


def test_doble_aplicacion_no_duplica(tmp_path):
    raiz, catalogos, actual, decisiones = _entorno(tmp_path, tracto="XF3629", rampla="No encontrado")
    decision = next(d for d in decisiones if d["tipo"] == "VEHICULO_DESCONOCIDO")
    aplicar_decision_obra(raiz_atlas=raiz, decision_id=decision["decision_id"], accion="REGISTRAR", tipo_vehiculo="TRACTO")
    segunda = aplicar_decision_obra(raiz_atlas=raiz, decision_id=decision["decision_id"], accion="REGISTRAR", tipo_vehiculo="TRACTO")
    assert segunda["idempotente"] is True and len(_vehiculos(catalogos)) == 1


def test_patente_ya_registrada_se_reutiliza_sin_duplicar(tmp_path):
    raiz, catalogos, actual, decisiones = _entorno(tmp_path, tracto="XF3629", rampla="No encontrado")
    decision = next(d for d in decisiones if d["tipo"] == "VEHICULO_DESCONOCIDO")
    confirmar_vehiculo(
        catalogos / "vehiculos.json", patente="XF3629", tipo=TipoVehiculo.TRACTO,
        actor="TEST", fuente_decision="PREVIA", fecha=datetime.now(timezone.utc),
    )
    generar_artefacto(
        ruta_dataset=actual / "analisis_completo_guias.csv", carpeta_catalogos=catalogos,
        decisiones=[decision], ruta_salida=actual / "decisiones_pendientes.json",
    )
    resultado = aplicar_decision_obra(
        raiz_atlas=raiz, decision_id=decision["decision_id"], accion="REGISTRAR", tipo_vehiculo="TRACTO",
    )
    assert resultado["ok"] and len(_vehiculos(catalogos)) == 1


def test_obsolescencia_y_fallo_no_dejan_estado_parcial(tmp_path, monkeypatch):
    raiz, catalogos, actual, decisiones = _entorno(tmp_path, tracto="XF3629", rampla="No encontrado")
    decision = next(d for d in decisiones if d["tipo"] == "VEHICULO_DESCONOCIDO")
    (actual / "analisis_completo_guias.csv").write_text("cambio externo", encoding="utf-8")
    with pytest.raises(DecisionObsoletaError):
        aplicar_decision_obra(
            raiz_atlas=raiz, decision_id=decision["decision_id"], accion="REGISTRAR", tipo_vehiculo="TRACTO",
        )
    assert _vehiculos(catalogos) == ()

    raiz, catalogos, actual, decisiones = _entorno(tmp_path / "fallo", tracto="XF3629", rampla="No encontrado")
    decision = next(d for d in decisiones if d["tipo"] == "VEHICULO_DESCONOCIDO")
    antes = {p: p.read_bytes() for p in [catalogos / "vehiculos.json", actual / "decisiones_pendientes.json"]}
    monkeypatch.setattr(modulo, "generar_artefacto", lambda **k: (_ for _ in ()).throw(OSError("fallo")))
    with pytest.raises(OSError):
        aplicar_decision_obra(
            raiz_atlas=raiz, decision_id=decision["decision_id"], accion="REGISTRAR", tipo_vehiculo="TRACTO",
        )
    assert antes == {p: p.read_bytes() for p in antes}
    assert not (actual / "decisiones_aplicadas.json").exists()
