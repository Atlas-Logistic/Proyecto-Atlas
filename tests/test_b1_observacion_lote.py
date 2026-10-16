"""B1 -- misma observación a varias guías (VIAJE_AGREGAR_OBSERVACION).
Sólo fixtures sintéticas: nunca G: ni datos productivos."""
from __future__ import annotations

import csv
import json

import pytest

from atlas_core.acciones_operacionales import CapaAccionesOperacionales
from atlas_core.b1_operador import OperadorB1, interpretar_determinista
from atlas_core.procesamiento_masivo import COLUMNAS
from atlas_core.registro_eventos_operacionales import leer_eventos_operacionales, registrar_evento

TEXTO = "ESTE VIAJE TIENE ADICIONAL DE 30.000 POR RETIRO FUERA DE AZA"
ORDEN = f"Agrega la observación {TEXTO} a las guías 500001, 500002, 500003, 599999"


@pytest.fixture
def raiz(tmp_path):
    raiz = tmp_path / "AtlasCopia"
    actual = raiz / "operacion" / "actual"
    actual.mkdir(parents=True)
    (raiz / "catalogos_privados").mkdir()
    with (actual / "analisis_completo_guias.csv").open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader()
        for guia, transporte in (("500001", "0000900001"), ("500002", "0000900002"), ("500003", "0000900003")):
            fila = {c: "" for c in COLUMNAS}
            fila.update({"archivo": f"{guia}.jpeg", "numero_guia": guia, "numero_transporte": transporte,
                         "obra_destino": "OBRA UNO"})
            escritor.writerow(fila)
    # 500002 ya tiene estadía con nota; 500003 ya tiene una observación previa.
    registrar_evento(raiz=raiz, tipo_evento="TIENE_ESTADIA", numero_transporte="0000900002",
                     nota="NOTA ESTADIA", origen="TEST")
    registrar_evento(raiz=raiz, tipo_evento="OBSERVACION_OPERACIONAL", numero_transporte="0000900003",
                     nota="OBSERVACION ANTERIOR", origen="TEST")
    return raiz


def _eventos(raiz):
    return leer_eventos_operacionales(raiz=raiz)["eventos"]


def _observacion(raiz, transporte):
    return next(e for e in _eventos(raiz) if e["tipo_evento"] == "OBSERVACION_OPERACIONAL"
                and e["numero_transporte"] == transporte)


def test_interpreta_ambos_ordenes_sin_tomar_el_monto_como_guia():
    a = interpretar_determinista(ORDEN)
    b = interpretar_determinista(f"Agrega a las guías 500001, 500002 y 500003 la observación: «{TEXTO}»")
    assert a.accion == b.accion == "VIAJE_AGREGAR_OBSERVACION"
    assert a.parametros == {"guias": ["500001", "500002", "500003", "599999"], "texto": TEXTO}
    assert b.parametros == {"guias": ["500001", "500002", "500003"], "texto": TEXTO}


def test_preview_conjunto_confirmacion_y_verificacion(raiz):
    b1 = OperadorB1(raiz)
    antes = json.dumps(_eventos(raiz), sort_keys=True)
    r = b1.atender("c", ORDEN)
    assert r["estado"] == "PREVIEW_PENDIENTE", r
    filas = {f[0]: f for f in r["tablas"][0]["filas"]}
    assert filas["599999"][2].startswith("No existe") and filas["500001"][2] == "Se agrega"
    assert "NOTA ESTADIA" in filas["500002"][3]
    assert json.dumps(_eventos(raiz), sort_keys=True) == antes  # el preview no escribe
    assert CapaAccionesOperacionales(raiz).auditoria() == []

    e = b1.atender("c", "sí")
    assert e["estado"] == "EJECUTADA", e
    assert e["resultado"]["despues"]["verificacion"]["persistida"] is True
    assert _observacion(raiz, "0000900001")["nota"] == TEXTO
    assert _observacion(raiz, "0000900002")["nota"] == TEXTO
    assert _observacion(raiz, "0000900003")["nota"] == f"OBSERVACION ANTERIOR\n{TEXTO}"
    estadia = next(x for x in _eventos(raiz) if x["tipo_evento"] == "TIENE_ESTADIA")
    assert estadia["nota"] == "NOTA ESTADIA"  # otros eventos intactos
    assert not any(x["numero_transporte"] == "" for x in _eventos(raiz))
    auditoria = CapaAccionesOperacionales(raiz).auditoria()
    assert len(auditoria) == 1 and auditoria[0]["confirmado_por"] == "JAVIER" and auditoria[0]["origen"] == "B1"
    dataset = (raiz / "operacion" / "actual" / "analisis_completo_guias.csv").read_text(encoding="utf-8-sig")
    assert TEXTO not in dataset  # no toca datos documentales

    # Repetir la orden: sin duplicados, nada que confirmar.
    otra = b1.atender("c", ORDEN)
    assert otra["estado"] == "SIN_CAMBIOS", otra
    assert _observacion(raiz, "0000900003")["nota"].count(TEXTO) == 1


def test_sin_confirmacion_no_escribe_y_cambio_intermedio_obsoleta(raiz):
    b1 = OperadorB1(raiz)
    assert b1.atender("c", ORDEN)["estado"] == "PREVIEW_PENDIENTE"
    assert b1.atender("c", "no")["estado"] != "EJECUTADA"
    assert all(e["numero_transporte"] != "0000900001" for e in _eventos(raiz))

    assert b1.atender("c", ORDEN)["estado"] == "PREVIEW_PENDIENTE"
    registrar_evento(raiz=raiz, tipo_evento="OBSERVACION_OPERACIONAL", numero_transporte="0000900001",
                     nota="OTRA OBSERVACION", origen="TEST")
    r = b1.atender("c", "sí")
    assert r["estado"] == "PREVIEW_RENOVADO" and r["ejecutado"] is False, r
    assert _observacion(raiz, "0000900001")["nota"] == "OTRA OBSERVACION"
    assert b1.atender("c", "sí")["estado"] == "EJECUTADA"
    assert _observacion(raiz, "0000900001")["nota"] == f"OTRA OBSERVACION\n{TEXTO}"


def test_ninguna_guia_existente_se_rechaza(raiz):
    r = OperadorB1(raiz).atender("c", f"Agrega la observación {TEXTO} a las guías 599998, 599999")
    assert r["estado"] == "RECHAZADA" and r["codigo"] == "PRECONDICION_FALLIDA"
