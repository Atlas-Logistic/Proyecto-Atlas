"""Bloque EVENTOS OPERACIONALES CANÓNICOS V1 -- fuente canónica
`operacion/actual/eventos_operacionales.json` (alta idempotente,
anulación sin borrado, reactivación del mismo hecho lógico,
multiempresa, enriquecimiento que nunca inventa, lock/escritura
atómica).
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone

import pytest

from atlas_core.almacenamiento_portable import escribir_estado_operacion
from atlas_core.registro_eventos_operacionales import (
    CONTEXTO_EMPRESARIAL_SIN_ASIGNAR,
    ESTADO_ACTIVO,
    ESTADO_ANULADO,
    EventosOperacionalesCorruptosError,
    anular_evento,
    leer_eventos_operacionales,
    listar_eventos_por_transporte,
    registrar_evento,
    resolver_enriquecimiento_transporte,
    ruta_eventos_operacionales,
)


def _reloj_fijo(iso="2026-09-07T12:00:00+00:00"):
    momento = datetime.fromisoformat(iso)
    return lambda: momento


def _reg(raiz, **kw):
    kw.setdefault("tipo_evento", "TIENE_ESTADIA")
    kw.setdefault("numero_transporte", "0000352552")
    kw.setdefault("origen", "TEST")
    return registrar_evento(raiz=raiz, **kw)


# --- 1: alta repetida no duplica -------------------------------------------

def test_alta_repetida_no_duplica(tmp_path):
    primero = _reg(tmp_path, nota="tiene estadia")
    segundo = _reg(tmp_path, nota="tiene estadia")

    assert primero["creado"] is True
    assert segundo["creado"] is False
    assert segundo["cambio"] is False
    assert primero["evento"]["evento_id"] == segundo["evento"]["evento_id"]

    documento = leer_eventos_operacionales(raiz=tmp_path)
    assert len(documento["eventos"]) == 1
    # 2ª alta idéntica no reescribe el archivo (revisión estable).
    assert documento["revision"] == 1


# --- 2: marcar -> desmarcar -> reactivar conserva el mismo hecho lógico ----

def test_marcar_desmarcar_reactivar_mismo_hecho_logico(tmp_path):
    creado = _reg(tmp_path, nota="n1")
    evento_id = creado["evento"]["evento_id"]

    anulado = anular_evento(
        raiz=tmp_path, tipo_evento="TIENE_ESTADIA", numero_transporte="0000352552",
        origen="TEST", motivo="humano desmarca",
    )
    assert anulado["anulado"] is True
    assert anulado["evento"]["estado"] == ESTADO_ANULADO
    assert anulado["evento"]["evento_id"] == evento_id

    reactivado = _reg(tmp_path, nota="n1")
    assert reactivado["reactivado"] is True
    assert reactivado["creado"] is False
    assert reactivado["evento"]["evento_id"] == evento_id
    assert reactivado["evento"]["estado"] == ESTADO_ACTIVO

    documento = leer_eventos_operacionales(raiz=tmp_path)
    assert len(documento["eventos"]) == 1
    acciones = [h["accion"] for h in documento["eventos"][0]["historial"]]
    assert acciones.count("CREADO") == 1
    assert "ANULADO" in acciones and "REACTIVADO" in acciones


def test_anular_es_idempotente(tmp_path):
    _reg(tmp_path)
    uno = anular_evento(raiz=tmp_path, tipo_evento="TIENE_ESTADIA", numero_transporte="0000352552", origen="TEST")
    dos = anular_evento(raiz=tmp_path, tipo_evento="TIENE_ESTADIA", numero_transporte="0000352552", origen="TEST")
    assert uno["anulado"] is True
    assert dos["anulado"] is False and dos["ya_anulado"] is True


def test_anular_evento_inexistente_es_noop_exitoso(tmp_path):
    r = anular_evento(raiz=tmp_path, tipo_evento="DOBLE_VUELTA", numero_transporte="999", origen="TEST")
    assert r == {"ok": True, "encontrado": False, "anulado": False, "ya_anulado": False, "evento": None}


# --- 3: tipos distintos del mismo viaje son independientes -----------------

def test_tipos_distintos_del_mismo_viaje_son_independientes(tmp_path):
    _reg(tmp_path, tipo_evento="TIENE_ESTADIA")
    _reg(tmp_path, tipo_evento="DEVOLUCION_PARCIAL")

    anular_evento(raiz=tmp_path, tipo_evento="TIENE_ESTADIA", numero_transporte="0000352552", origen="TEST")

    activos = listar_eventos_por_transporte(
        raiz=tmp_path, numero_transporte="0000352552", incluir_anulados=False
    )
    assert {e["tipo_evento"] for e in activos} == {"DEVOLUCION_PARCIAL"}
    todos = listar_eventos_por_transporte(raiz=tmp_path, numero_transporte="0000352552")
    assert len(todos) == 2


# --- 4: mismo tipo en contextos/tenants distintos no colisiona ------------

def test_mismo_tipo_en_contextos_distintos_no_colisiona(tmp_path):
    a = _reg(tmp_path, contexto_empresarial="EMPRESA_A", nota="a")
    b = _reg(tmp_path, contexto_empresarial="EMPRESA_B", nota="b")
    assert a["evento"]["evento_id"] != b["evento"]["evento_id"]
    assert a["evento"]["clave_idempotencia"] != b["evento"]["clave_idempotencia"]

    documento = leer_eventos_operacionales(raiz=tmp_path)
    assert len(documento["eventos"]) == 2

    solo_a = listar_eventos_por_transporte(
        raiz=tmp_path, numero_transporte="0000352552", contexto_empresarial="EMPRESA_A"
    )
    assert len(solo_a) == 1 and solo_a[0]["nota"] == "a"


def test_contexto_por_defecto_es_identificador_transitorio_explicito(tmp_path):
    r = _reg(tmp_path)
    assert r["evento"]["contexto_empresarial"] == CONTEXTO_EMPRESARIAL_SIN_ASIGNAR
    assert CONTEXTO_EMPRESARIAL_SIN_ASIGNAR == "__SIN_ASIGNAR__"


# --- 5: la nota se preserva ----------------------------------------------

def test_nota_se_preserva_exactamente(tmp_path):
    nota = "ESTE VIAJE TIENE ESTADIA, SE ENVIO GUÍA FIRMADA AL CORREO\n"
    r = _reg(tmp_path, nota=nota)
    assert r["evento"]["nota"] == nota
    # persistida sin normalizar
    disco = json.loads(ruta_eventos_operacionales(raiz=tmp_path).read_text(encoding="utf-8"))
    assert disco["eventos"][0]["nota"] == nota


def test_reactivar_actualiza_nota_si_cambia(tmp_path):
    _reg(tmp_path, nota="vieja")
    anular_evento(raiz=tmp_path, tipo_evento="TIENE_ESTADIA", numero_transporte="0000352552", origen="TEST")
    r = _reg(tmp_path, nota="nueva")
    assert r["evento"]["nota"] == "nueva"
    acciones = [h["accion"] for h in r["evento"]["historial"]]
    assert "NOTA_ACTUALIZADA" in acciones


# --- 6: asociación ausente/ambigua no inventa datos ----------------------

def _operacion_vigente(raiz, filas):
    columnas = [
        "viaje_id", "numero_transporte", "fecha", "numeros_guia", "clientes",
        "obras_destino", "choferes", "ruts_chofer", "patentes_tracto", "patentes_rampla",
    ]
    carpeta_reporte = raiz / "reportes" / "r1"
    carpeta_reporte.mkdir(parents=True, exist_ok=True)
    ruta_csv = carpeta_reporte / "viajes.csv"
    lineas = [";".join(columnas)]
    for fila in filas:
        lineas.append(";".join(str(fila.get(c, "")) for c in columnas))
    ruta_csv.write_text("﻿" + "\n".join(lineas) + "\n", encoding="utf-8")
    escribir_estado_operacion(
        reporte_vigente=carpeta_reporte, dataset_operacional=None, raiz=raiz,
    )
    return ruta_csv


def test_enriquecimiento_sin_viaje_asociado_no_inventa(tmp_path):
    _operacion_vigente(tmp_path, [])
    enr = resolver_enriquecimiento_transporte(raiz=tmp_path, numero_transporte="0000352552")
    assert enr["vinculo_completo"] is False
    assert enr["motivo_vinculo_incompleto"] == "SIN_VIAJE_ASOCIADO"
    assert enr["snapshot"] == {} and enr["numeros_guia"] == []

    r = _reg(tmp_path, enriquecimiento=enr)
    assert r["evento"]["vinculo_completo"] is False
    assert r["evento"]["viaje_id"] == ""
    assert r["evento"]["snapshot"] == {}


def test_enriquecimiento_transporte_ambiguo_no_inventa(tmp_path):
    _operacion_vigente(tmp_path, [
        {"viaje_id": "v1", "numero_transporte": "0000352552", "choferes": "A"},
        {"viaje_id": "v2", "numero_transporte": "0000352552", "choferes": "B"},
    ])
    enr = resolver_enriquecimiento_transporte(raiz=tmp_path, numero_transporte="0000352552")
    assert enr["vinculo_completo"] is False
    assert enr["motivo_vinculo_incompleto"] == "TRANSPORTE_AMBIGUO"


def test_enriquecimiento_inequivoco_completa_viaje_guias_chofer(tmp_path):
    _operacion_vigente(tmp_path, [{
        "viaje_id": "723db36b", "numero_transporte": "0000352552", "fecha": "10-08-2026",
        "numeros_guia": "464534 | 464535", "choferes": "PATRICIO VILLAGRA",
        "ruts_chofer": "11.111.111-1", "patentes_tracto": "BDFG50",
    }])
    enr = resolver_enriquecimiento_transporte(raiz=tmp_path, numero_transporte="0000352552")
    assert enr["vinculo_completo"] is True
    assert enr["viaje_id"] == "723db36b"
    assert enr["numeros_guia"] == ["464534", "464535"]
    assert enr["fecha_operacional"] == "2026-08-10"
    assert enr["snapshot"]["chofer"] == "PATRICIO VILLAGRA"
    assert enr["snapshot"]["patentes_tracto"] == ["BDFG50"]

    r = _reg(tmp_path, enriquecimiento=enr)
    assert r["evento"]["vinculo_completo"] is True
    assert r["evento"]["numeros_guia"] == ["464534", "464535"]


def test_enriquecimiento_sin_operacion_vigente(tmp_path):
    enr = resolver_enriquecimiento_transporte(raiz=tmp_path, numero_transporte="1")
    assert enr["vinculo_completo"] is False
    assert enr["motivo_vinculo_incompleto"] == "SIN_OPERACION_VIGENTE"


# --- 7: escritura atómica / lock ---------------------------------------

def test_no_deja_archivo_a_medio_escribir_ante_fallo(tmp_path, monkeypatch):
    _reg(tmp_path, nota="ok")
    original = leer_eventos_operacionales(raiz=tmp_path)

    import atlas_core.registro_eventos_operacionales as mod

    def _boom(*a, **k):
        raise OSError("disco lleno")

    monkeypatch.setattr(mod, "escribir_json_atomico", _boom)
    with pytest.raises(OSError):
        _reg(tmp_path, tipo_evento="DEVOLUCION_TOTAL")

    # El archivo previo quedó intacto y legible.
    assert leer_eventos_operacionales(raiz=tmp_path) == original


def test_lock_serializa_escrituras_concurrentes(tmp_path):
    """El lock de sesión de Atlas NO encola: o entras, o `SesionOcupada`.
    La garantía real es "nunca se pierde una escritura ya confirmada ni
    queda un archivo a medias" -- con un reintento breve las 6 altas
    distintas terminan las 6 en el archivo, cada una contando su propia
    revisión (0 lost-update)."""
    import time

    from atlas_core.almacenamiento_portable import SesionOcupadaError

    barrera = threading.Barrier(6)
    otros_errores: list[Exception] = []

    def worker(i):
        barrera.wait()
        for _ in range(200):
            try:
                registrar_evento(
                    raiz=tmp_path, tipo_evento=f"TIPO_{i}", numero_transporte="0000352552",
                    origen="TEST", nota=f"n{i}",
                )
                return
            except SesionOcupadaError:
                time.sleep(0.01)
            except Exception as e:  # noqa: BLE001
                otros_errores.append(e)
                return

    hilos = [threading.Thread(target=worker, args=(i,)) for i in range(6)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join()

    assert not otros_errores
    documento = leer_eventos_operacionales(raiz=tmp_path)
    assert len(documento["eventos"]) == 6
    assert documento["revision"] == 6  # ninguna escritura se perdió
    # El archivo en disco quedó siempre como JSON válido.
    json.loads(ruta_eventos_operacionales(raiz=tmp_path).read_text(encoding="utf-8"))


def test_archivo_canonico_corrupto_no_se_clobberea(tmp_path):
    ruta = ruta_eventos_operacionales(raiz=tmp_path)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text("{ esto no es json", encoding="utf-8")
    with pytest.raises(EventosOperacionalesCorruptosError):
        _reg(tmp_path)
    assert ruta.read_text(encoding="utf-8") == "{ esto no es json"
    # La lectura tolerante para mostrar nunca lanza.
    assert leer_eventos_operacionales(raiz=tmp_path)["eventos"] == []
