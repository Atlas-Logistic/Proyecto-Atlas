"""B1 operador -- DESTINO de una guía en lenguaje natural ("El destino de la
guía N es X"). Mismo camino que Revisión: la decisión pendiente
DESTINO_NO_RESUELTO se aplica con REGISTRAR_DIRECCION vía DECISION_APLICAR
(aplicar_decision_obra), sólo tras confirmación. Fixtures sintéticas
(reutiliza las de R6) y proveedor de rutas simulado; nunca G: ni red."""
from __future__ import annotations

import hashlib
import json

import pytest

from atlas_core.acciones_operacionales import CapaAccionesOperacionales
from atlas_core.b1_operador import OperadorB1, interpretar_determinista
from atlas_core.decisiones_pendientes import detectar_decision_destino_no_resuelto
from tests.test_destino_no_resuelto_r6 import (
    _cliente_dict, _entorno, _fila_csv, _leer_csv, _obra_dict, _proveedor_direccion_valida, _publicar,
)

DIRECCION = "AVENIDA APOQUINDO 1234"


def _sha(ruta):
    return hashlib.sha256(ruta.read_bytes()).hexdigest() if ruta.exists() else None


def _preparar(tmp_path, *, publicar=True):
    entorno = _entorno(tmp_path, filas_csv=[_fila_csv()], clientes=[_cliente_dict()], obras=[_obra_dict()])
    decision = detectar_decision_destino_no_resuelto(archivo="472037.jpeg", fila=_fila_csv())
    if publicar:
        _publicar(entorno, decision)
    capa = CapaAccionesOperacionales(entorno["raiz"], proveedor_rutas=_proveedor_direccion_valida(DIRECCION))
    return entorno, decision, OperadorB1(entorno["raiz"], capa=capa)


@pytest.mark.parametrize("texto", [
    "El destino de la guía 472037 es Avenida Apoquindo 1234",
    "el destino de la guia 472037: Avenida Apoquindo 1234",
    "Destino guía N° 472037 es avenida apoquindo 1234.",
    "La guía 472037 va a Avenida Apoquindo 1234",
    "La guía 472037 se entregó en Avenida Apoquindo 1234",
    "Corrige el destino de la guía 472037 a Avenida Apoquindo 1234",
    "Cambia la dirección de entrega de la guía 472037 por Avenida Apoquindo 1234",
    "La dirección de la guía 472037 es Avenida Apoquindo 1234",
])
def test_variantes_de_la_misma_intencion(texto):
    intencion = interpretar_determinista(texto)
    assert intencion is not None and intencion.accion == "DECISION_APLICAR"
    assert intencion.parametros == {"accion_decision": "REGISTRAR_DIRECCION", "direccion_manual": DIRECCION}
    assert intencion.menciones == {"guia_destino": "472037"}


def test_comuna_explicita_viaja_separada():
    intencion = interpretar_determinista("El destino de la guía 472037 es San Damián 0100, comuna Las Condes")
    assert intencion.parametros == {"accion_decision": "REGISTRAR_DIRECCION",
                                    "direccion_manual": "SAN DAMIÁN 0100", "comuna_manual": "LAS CONDES"}


def test_no_captura_otras_intenciones():
    assert interpretar_determinista("¿Cuál es el destino de la guía 472037?") is None
    assert interpretar_determinista("corrige la obra de la guía 472037 a OBRA DOS").accion == "DOCUMENTO_ASIGNAR_OBRA"


def test_destino_por_lenguaje_natural_preview_confirmacion_y_aplicacion(tmp_path):
    entorno, decision, b1 = _preparar(tmp_path)
    dataset, actual = entorno["dataset"], entorno["actual"]
    huellas = {n: _sha(actual / n) for n in ("analisis_completo_guias.csv", "decisiones_aplicadas.json",
                                             "decisiones_pendientes.json")}

    r = b1.atender("c", "El destino de la guía 472037 es Avenida Apoquindo 1234")
    assert r["estado"] == "PREVIEW_PENDIENTE", r
    assert r["accion"] == "DECISION_APLICAR"
    assert r["preview"]["entidad"]["id"] == decision["decision_id"]
    assert r["preview"]["valor_propuesto"] == {"accion": "REGISTRAR_DIRECCION", "direccion_manual": DIRECCION}
    assert "guía 472037" in r["mensaje"] and DIRECCION in r["mensaje"] and "¿Confirmas?" in r["mensaje"]
    # nada escrito antes de confirmar
    assert {n: _sha(actual / n) for n in huellas} == huellas

    e = b1.atender("c", "sí")
    assert e["estado"] == "EJECUTADA", e
    fila = _leer_csv(dataset)[0]
    assert fila["despachar_a_crudo"] == DIRECCION
    assert fila["estado_ruta"] == "RUTA_CALCULADA"
    bandeja = json.loads((actual / "decisiones_pendientes.json").read_text(encoding="utf-8"))
    assert decision["decision_id"] not in {d["decision_id"] for d in bandeja["decisiones"]}
    ledger = json.loads((actual / "decisiones_aplicadas.json").read_text(encoding="utf-8"))["aplicaciones"]
    aplicadas = [a for a in ledger if a["decision_id"] == decision["decision_id"]]
    assert len(aplicadas) == 1 and aplicadas[0]["accion"] == "REGISTRAR_DIRECCION" and aplicadas[0]["actor"] == "B1"
    auditoria = b1.capa.auditoria()
    assert len(auditoria) == 1 and auditoria[0]["accion"] == "DECISION_APLICAR"
    assert auditoria[0]["confirmado_por"] == "JAVIER" and auditoria[0]["resultado"] == "APLICADA"

    # idempotencia: el mismo token no reaplica y la misma orden ya no tiene nada pendiente
    token = auditoria[0]["token"]
    antes = _sha(dataset)
    assert b1.capa.ejecutar(token, actor="B1", origen="B1", confirmado_por="JAVIER")["idempotente"] is True
    otra = b1.atender("c", "El destino de la guía 472037 es Avenida Apoquindo 1234")
    assert otra["estado"] == "ACLARACION_REQUERIDA"
    assert _sha(dataset) == antes and len(b1.capa.auditoria()) == 1
    assert len([a for a in json.loads((actual / "decisiones_aplicadas.json").read_text(encoding="utf-8"))["aplicaciones"]
                if a["decision_id"] == decision["decision_id"]]) == 1


def test_sin_revision_de_destino_pendiente_pide_aclaracion_y_no_escribe(tmp_path):
    entorno, _decision, b1 = _preparar(tmp_path, publicar=False)
    antes = _sha(entorno["dataset"])
    r = b1.atender("c", "El destino de la guía 472037 es Avenida Apoquindo 1234")
    assert r["estado"] == "ACLARACION_REQUERIDA"
    assert "no tiene una revisión de destino pendiente" in r["mensaje"]
    assert b1.pendiente("c") is None
    assert b1.atender("c", "sí")["estado"] == "SIN_PREVIEW_PENDIENTE"
    assert _sha(entorno["dataset"]) == antes


def test_guia_de_otra_revision_no_se_confunde(tmp_path):
    entorno, _decision, b1 = _preparar(tmp_path)
    r = b1.atender("c", "El destino de la guía 999999 es Avenida Apoquindo 1234")
    assert r["estado"] == "ACLARACION_REQUERIDA" and "999999" in r["mensaje"]
