"""B1 OPERADOR -- lenguaje natural -> acciones canónicas. Sólo fixtures
sintéticas: nunca G: ni datos productivos."""
from __future__ import annotations

import csv
import json
from datetime import datetime, timedelta, timezone

import pytest

from atlas_core.acciones_operacionales import CapaAccionesOperacionales
from atlas_core.b1_operador import OperadorB1, es_confirmacion, interpretar_determinista
from atlas_core.procesamiento_masivo import COLUMNAS

RUT_PIZARRO, RUT_REYES, RUT_JUAN_A, RUT_JUAN_B = "15432876-9", "12345678-5", "16789012-1", "17345678-6"


def _vehiculo(patente, tipo):
    evidencia = {"tipo": "CONFIRMACION_HUMANA", "identificador_fuente": "TEST", "referencia_hash": "",
                 "campos_observados": {"patente": patente, "tipo": tipo, "observacion": ""},
                 "fecha": "2026-01-01T00:00:00+00:00", "actor_proceso": "TEST", "resultado": "SOPORTA"}
    return {"vehiculo_id": patente, "patente_canonica": patente, "tipo": tipo, "estado_calidad": "CONFIRMADO",
            "estado_vigencia": "ACTIVO", "aliases": [], "evidencias": [evidencia],
            "procedencia": "CONFIRMACION_HUMANA", "confirmado_por": "TEST",
            "fecha_confirmacion": "2026-01-01T00:00:00+00:00", "observaciones": "",
            "fecha_creacion": "2026-01-01T00:00:00+00:00", "fecha_modificacion": "2026-01-01T00:00:00+00:00"}


@pytest.fixture
def raiz(tmp_path):
    raiz = tmp_path / "AtlasCopia"
    cat, actual = raiz / "catalogos_privados", raiz / "operacion" / "actual"
    cat.mkdir(parents=True)
    actual.mkdir(parents=True)
    (cat / "choferes.json").write_text(json.dumps({
        "154328769": {"nombre": "SALOMON PIZARRO", "rut": RUT_PIZARRO, "aliases": [], "activo": True},
        "123456785": {"nombre": "LUIS REYES", "rut": RUT_REYES, "aliases": [], "activo": True},
        "167890121": {"nombre": "JUAN PEREZ", "rut": RUT_JUAN_A, "aliases": [], "activo": True},
        "173456786": {"nombre": "JUAN PEREZ SOTO", "rut": RUT_JUAN_B, "aliases": [], "activo": True},
    }), encoding="utf-8")
    (cat / "vehiculos.json").write_text(json.dumps({"version": 1, "vehiculos": [
        _vehiculo("JF9575", "CARRO"), _vehiculo("KN5439", "TRACTO")]}), encoding="utf-8")
    with (actual / "analisis_completo_guias.csv").open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader()
        fila = {c: "" for c in COLUMNAS}
        fila.update({"archivo": "500001.jpeg", "numero_guia": "500001", "numero_transporte": "0000900001",
                     "chofer": "SALOMON PIZARRO", "rut_chofer": RUT_PIZARRO, "obra_destino": "OBRA UNO"})
        escritor.writerow(fila)
    return raiz


def _choferes(raiz):
    return json.loads((raiz / "catalogos_privados" / "choferes.json").read_text(encoding="utf-8"))


def _auditoria(raiz):
    return CapaAccionesOperacionales(raiz).auditoria()


# 1 ----------------------------------------------------------------------


def test_pizarro_usa_jf9575_preview_y_si_ejecuta(raiz):
    b1 = OperadorB1(raiz)
    r = b1.atender("conv1", "Pizarro usa JF9575")
    assert r["estado"] == "PREVIEW_PENDIENTE", r
    assert r["accion"] == "CHOFER_ASIGNAR_VEHICULO"
    assert r["preview"]["valor_propuesto"] == {"rut_chofer": "154328769", "patente": "JF9575", "tipo": "RAMPLA"}
    assert r["preview"]["riesgo"] == "OPERACIONAL_REVERSIBLE" and "token" not in r["preview"]
    assert "¿Confirmas?" in r["mensaje"] and "JF9575" in r["mensaje"]
    assert _auditoria(raiz) == []  # el preview no escribe

    e = b1.atender("conv1", "Sí")
    assert e["estado"] == "EJECUTADA", e
    assert e["resultado"]["revalidacion"] is not None
    vehiculos = json.loads((raiz / "catalogos_privados" / "vehiculos.json").read_text(encoding="utf-8"))["vehiculos"]
    jf = next(v for v in vehiculos if v["patente_canonica"] == "JF9575")
    assert jf["evidencias"][-1]["campos_observados"].get("rut_chofer_asociado") == "154328769", jf["evidencias"]
    auditoria = _auditoria(raiz)
    assert len(auditoria) == 1 and auditoria[0]["confirmado_por"] == "JAVIER" and auditoria[0]["origen"] == "B1"
    assert auditoria[0]["referencia"] == "Pizarro usa JF9575"
    # el pendiente se consumió: otro "sí" no hace nada
    assert b1.atender("conv1", "sí")["estado"] == "SIN_PREVIEW_PENDIENTE"
    assert len(_auditoria(raiz)) == 1


def test_tipo_declarado_distinto_del_catalogo_pide_aclaracion(raiz):
    r = OperadorB1(raiz).atender("c", "El tracto de Pizarro es JF9575")
    assert r["estado"] == "ACLARACION_REQUERIDA"
    assert OperadorB1(raiz).pendiente("c") is None


# 2 ----------------------------------------------------------------------


def test_pon_inactivo_preview_confirmacion_cambio_auditoria(raiz):
    b1 = OperadorB1(raiz)
    r = b1.atender("conv2", "Pon inactivo a Luis Reyes")
    assert r["estado"] == "PREVIEW_PENDIENTE" and r["accion"] == "CHOFER_CAMBIAR_ESTADO"
    assert r["preview"]["valor_propuesto"] == {"activo": False}
    assert _choferes(raiz)["123456785"]["activo"] is True
    e = b1.atender("conv2", "confirma")
    assert e["estado"] == "EJECUTADA", e
    assert _choferes(raiz)["123456785"]["activo"] is False
    entrada = _auditoria(raiz)[-1]
    assert entrada["accion"] == "CHOFER_CAMBIAR_ESTADO" and entrada["antes"] == {"activo": True}
    assert entrada["despues"] == {"activo": False} and entrada["actor"] == "B1"
    # repetir la orden: ya está así, nada que confirmar
    assert b1.atender("conv2", "Deja inactivo a Luis Reyes")["estado"] == "SIN_CAMBIOS"
    # reactivar a un chofer inactivo también se resuelve
    assert b1.atender("conv2", "Reactiva a Luis Reyes")["estado"] == "PREVIEW_PENDIENTE"


# 3 ----------------------------------------------------------------------


def test_lectura_directa_sin_confirmacion_y_sin_tocar_pendiente(raiz):
    b1 = OperadorB1(raiz)
    b1.atender("c3", "Pon inactivo a Luis Reyes")
    token = b1.pendiente("c3")["token"]
    r = b1.atender("c3", "¿Qué choferes están activos?")
    assert r["estado"] == "RESULTADO_LECTURA" and r["accion"] == "CHOFER_CONSULTAR"
    assert "LUIS REYES" in r["mensaje"] and r["resultado"]["total"] == 4
    assert b1.pendiente("c3")["token"] == token  # la lectura no reemplaza el pendiente
    assert _auditoria(raiz) == []


# 4 ----------------------------------------------------------------------


def test_orden_ambigua_pregunta_y_no_adivina(raiz):
    b1 = OperadorB1(raiz)
    r = b1.atender("c4", "Pon inactivo a Juan")
    assert r["estado"] == "ACLARACION_REQUERIDA"
    assert {c["rut"].replace(".", "") for c in r["candidatos"]} == {RUT_JUAN_A, RUT_JUAN_B}
    assert b1.pendiente("c4") is None
    assert b1.atender("c4", "sí")["estado"] == "SIN_PREVIEW_PENDIENTE"
    desconocido = b1.atender("c4", "Pon inactivo a Pedro Nadie")
    assert desconocido["estado"] == "ACLARACION_REQUERIDA" and desconocido["candidatos"] == []
    # con el RUT la orden es inequívoca
    assert b1.atender("c4", f"Pon inactivo a {RUT_JUAN_B}")["preview"]["entidad"]["id"] == "173456786"
    assert all(c["activo"] for c in _choferes(raiz).values())


# 5 ----------------------------------------------------------------------


def test_si_sin_preview_no_ejecuta_nada(raiz):
    antes = (raiz / "catalogos_privados" / "choferes.json").read_bytes()
    for palabra in ("sí", "Si, confirma", "aplica", "dale", "ok"):
        assert OperadorB1(raiz).atender("vacia", palabra)["estado"] == "SIN_PREVIEW_PENDIENTE"
    assert (raiz / "catalogos_privados" / "choferes.json").read_bytes() == antes
    assert _auditoria(raiz) == []


def test_confirmacion_solo_ejecuta_su_conversacion_y_la_ultima_instruccion(raiz):
    b1 = OperadorB1(raiz)
    b1.atender("a", "Pon inactivo a Luis Reyes")
    assert b1.atender("b", "sí")["estado"] == "SIN_PREVIEW_PENDIENTE"  # otra conversación
    b1.atender("a", "Pon inactivo a Salomon Pizarro")  # reemplaza el pendiente anterior
    assert b1.atender("a", "sí")["estado"] == "EJECUTADA"
    choferes = _choferes(raiz)
    assert choferes["154328769"]["activo"] is False and choferes["123456785"]["activo"] is True
    assert [a["entidad"]["id"] for a in _auditoria(raiz)] == ["154328769"]


def test_cancelar_descarta(raiz):
    b1 = OperadorB1(raiz)
    b1.atender("c", "Pon inactivo a Luis Reyes")
    assert b1.atender("c", "no, cancela")["estado"] == "CANCELADA"
    assert b1.atender("c", "sí")["estado"] == "SIN_PREVIEW_PENDIENTE"
    assert _choferes(raiz)["123456785"]["activo"] is True
    assert not es_confirmacion("sí, pero antes cambia la patente")


# 6 ----------------------------------------------------------------------


def test_preview_obsoleto_no_ejecuta_y_muestra_el_nuevo(raiz):
    b1 = OperadorB1(raiz)
    b1.atender("c6", "Pon inactivo a Luis Reyes")
    catalogo = _choferes(raiz)
    catalogo["123456785"]["aliases"] = ["LUCHO"]
    (raiz / "catalogos_privados" / "choferes.json").write_text(json.dumps(catalogo), encoding="utf-8")
    r = b1.atender("c6", "sí")
    assert r["estado"] == "PREVIEW_RENOVADO" and r["ejecutado"] is False
    assert "¿Confirmas?" in r["mensaje"]
    assert _choferes(raiz)["123456785"]["activo"] is True and _auditoria(raiz) == []
    assert b1.atender("c6", "sí")["estado"] == "EJECUTADA"  # sólo tras confirmar el nuevo
    assert _choferes(raiz)["123456785"]["activo"] is False


def test_preview_expirado_no_ejecuta(raiz):
    instante = [datetime(2026, 9, 28, 12, tzinfo=timezone.utc)]
    b1 = OperadorB1(raiz, reloj=lambda: instante[0])
    b1.atender("c", "Pon inactivo a Luis Reyes")
    instante[0] += timedelta(hours=2)
    r = b1.atender("c", "sí")
    assert r["estado"] == "PREVIEW_RENOVADO" and r["ejecutado"] is False
    assert _choferes(raiz)["123456785"]["activo"] is True


# 7 ----------------------------------------------------------------------


def test_accion_sensible_bloqueada_y_destructiva_rechazada(raiz):
    b1 = OperadorB1(raiz)
    r = b1.atender("c7", "Reprocesa el transporte 0000900001")
    assert r["estado"] == "REQUIERE_AUTORIZACION_SENSIBLE" and r["accion"] == "TRANSPORTE_REVALIDAR"
    assert "token" not in r["preview"] and b1.pendiente("c7") is None
    assert b1.atender("c7", "sí")["estado"] == "SIN_PREVIEW_PENDIENTE"
    d = b1.atender("c7", "Borra al chofer Luis Reyes")
    assert d["estado"] == "RECHAZADA" and d["codigo"] == "ACCION_PROHIBIDA"
    assert _auditoria(raiz) == [] and _choferes(raiz)["123456785"]["activo"] is True


# 8 ----------------------------------------------------------------------


class _ModeloSimulado:
    def __init__(self, propuesta):
        self.propuesta = propuesta
        self.contrato = None

    def interpretar(self, texto, contrato):
        self.contrato = contrato
        return self.propuesta


@pytest.mark.parametrize("propuesta", [
    {"accion": "os.system", "parametros": {"cmd": "rm -rf /"}},
    {"accion": "SHELL", "parametros": {}},
    {"accion": "CHOFER_CAMBIAR_ESTADO", "parametros": {"activo": False, "ruta": "C:/Atlas/choferes.json"},
     "menciones": {"chofer": "Luis Reyes"}},
    {"accion": "CHOFER_CAMBIAR_ESTADO", "parametros": {"activo": False}, "menciones": {"chofer": "../../choferes.json"}},
    {"accion": "OBRA_REGISTRAR", "parametros": {"cliente_id": "x", "nombre_obra": "__import__('os').system('del *')"}},
    {"accion": "OBRA_REGISTRAR", "parametros": {"cliente_id": "x", "nombre_obra": "A; powershell -c x"}},
    {"accion": "CHOFER_CAMBIAR_ESTADO", "parametros": {"activo": False}, "menciones": {"chofer": "Luis Reyes"},
     "codigo": "print(1)"},
    {"accion": "CHOFER_CAMBIAR_ESTADO", "parametros": {"activo": False}, "menciones": {"archivo": "x"}},
    "rm -rf /",
])
def test_modelo_que_genera_paths_comandos_o_codigo_es_rechazado(raiz, propuesta):
    b1 = OperadorB1(raiz, proveedor=_ModeloSimulado(propuesta))
    antes = (raiz / "catalogos_privados" / "choferes.json").read_bytes()
    r = b1.atender("c8", "haz lo que tengas que hacer con el archivo de choferes")
    assert r["estado"] == "RECHAZADA", r
    assert (raiz / "catalogos_privados" / "choferes.json").read_bytes() == antes
    assert b1.pendiente("c8") is None and _auditoria(raiz) == []


def test_modelo_valido_llega_a_preview_por_el_mismo_contrato(raiz):
    modelo = _ModeloSimulado({"accion": "CHOFER_CAMBIAR_ESTADO", "parametros": {"activo": False},
                              "menciones": {"chofer": "Luis Reyes"}})
    r = OperadorB1(raiz, proveedor=modelo).atender("c", "saca de la lista de activos a Luis Reyes")
    assert r["estado"] == "PREVIEW_PENDIENTE" and r["preview"]["entidad"]["id"] == "123456785"
    assert {a["accion"] for a in modelo.contrato} >= {"CHOFER_CAMBIAR_ESTADO", "CHOFER_ASIGNAR_VEHICULO"}


def test_texto_con_comando_no_se_interpreta_ni_ejecuta(raiz):
    b1 = OperadorB1(raiz)
    for texto in ("ejecuta rm -rf C:/Atlas", "Pon inactivo a Luis Reyes; del choferes.json",
                  "abre C:\\Atlas\\catalogos_privados\\choferes.json y cambia activo a false"):
        assert b1.atender("c", texto)["estado"] in {"NO_INTERPRETADA", "RECHAZADA", "ACLARACION_REQUERIDA"}
        assert b1.pendiente("c") is None
    assert _auditoria(raiz) == []


def test_interprete_determinista_y_cli(raiz, capsys):
    assert interpretar_determinista("Pon inactivo a Juan Pérez").menciones == {"chofer": "JUAN PÉREZ"}
    assert interpretar_determinista("corrige la obra de la guía 500001 a OBRA DOS").parametros == {
        "numero_guia": "500001", "campo": "obra_destino", "valor": "OBRA DOS"}
    assert interpretar_determinista("hola") is None
    from b1_operador_cli import main
    assert main(["--raiz-atlas", str(raiz), "--conversacion", "cli", "--texto", "Pizarro usa JF9575"]) == 0
    assert json.loads(capsys.readouterr().out)["estado"] == "PREVIEW_PENDIENTE"
    assert main(["--raiz-atlas", str(raiz), "--conversacion", "cli", "--texto", "sí"]) == 0
    assert json.loads(capsys.readouterr().out)["estado"] == "EJECUTADA"


@pytest.mark.parametrize("texto", [
    "¿Qué choferes trabajaron este mes?", "Cuántos choferes hubo hoy", "¿Qué estadías pendientes hay?",
    "Muéstrame las incidencias pendientes", "Qué obras tuvieron más viajes", "cuales guias estan pendientes de revision",
    "¿Qué revisiones de estadías hay?", "¿En qué guías aparece JF4288?",
])
def test_preguntas_de_consultas_no_las_toma_b1(texto):
    # Integración Desktop: B1 va primero en el panel Consultas; una pregunta
    # sobre la operación debe seguir llegando a Consultas/Incidencias.
    assert interpretar_determinista(texto) is None


def test_lecturas_de_catalogo_siguen_en_b1():
    assert interpretar_determinista("¿Qué choferes están inactivos?").parametros == {"estado": "INACTIVO"}
    assert interpretar_determinista("Muéstrame los choferes activos").parametros == {"estado": "ACTIVO"}
    assert interpretar_determinista("¿Qué decisiones hay de la guía 500001?").accion == "DECISION_CONSULTAR"
    assert interpretar_determinista("busca la obra Edificio Norte").parametros == {"nombre": "EDIFICIO NORTE"}
