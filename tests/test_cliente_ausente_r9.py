"""Bloque R9 -- CLIENTE_AUSENTE: cierra un hueco real encontrado en el
lote nuevo (guías 472238/472239, mismo transporte 0000354443, cliente
"No encontrado"): `CLIENTE_AUSENTE` es un motivo bloqueante real
(`motivos_revision_documento`) sin NINGUNA decisión asociada -- el
documento quedaba huérfano en REQUIERE_REVISION para siempre, invisible
en Revisión de Atlas. Distinto de CLIENTE_DESCONOCIDO/CLIENTE_CANDIDATO/
ALIAS_CANDIDATO (todos exigen algún texto documental de partida): aquí no
hay ningún nombre que corroborar, sólo un humano puede escribir la razón
social real."""
from __future__ import annotations

import csv
import json

from atlas_core.aplicacion_decisiones import ErrorAplicacionDecision, aplicar_decision_obra
from atlas_core.catalogo_clientes import CatalogoClientes
from atlas_core.decisiones_pendientes import crear_decision, detectar_decision_cliente_ausente, generar_artefacto
from atlas_core.procesamiento_masivo import COLUMNAS
from atlas_core.revalidacion_documental import (
    detectar_decisiones_cliente_ausente_sin_ocr,
    reconciliar_decisiones_cliente_ausente,
)

FECHA = "20-08-2026"


def _fila_csv(**overrides):
    fila = {c: "" for c in COLUMNAS}
    fila.update({
        "archivo": "472238.jpeg", "estado_procesamiento": "OK", "numero_guia": "472238",
        "numero_transporte": "0000354443", "fecha": FECHA, "chofer": "WLADIMIR AGUILAR",
        "cliente": "No encontrado", "obra_destino": "VISTA CLARA 2351 CERRILLOS",
        "indicador_revision": "REVISAR", "motivos_revision_documento": "CLIENTE_AUSENTE",
        "planta_origen_id": "planta-colina", "planta_origen_nombre": "AZA COLINA",
    })
    fila.update(overrides)
    return fila


def _escribir_csv(ruta, filas):
    with ruta.open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader(); escritor.writerows(filas)


def _leer_csv(ruta):
    with ruta.open(encoding="utf-8-sig", newline="") as archivo:
        return {f["archivo"]: f for f in csv.DictReader(archivo, delimiter=";")}


def _entorno(tmp_path, *, filas_csv):
    raiz = tmp_path / "Atlas"
    catalogos = raiz / "catalogos_privados"
    actual = raiz / "operacion" / "actual"
    catalogos.mkdir(parents=True)
    actual.mkdir(parents=True)
    for nombre, contenido in {
        "clientes.json": {"version_formato": 1, "clientes": []},
        "empresas.json": {},
        "vehiculos.json": {"version": 1, "vehiculos": []},
        "obras_destinos.json": {"version_formato": 1, "obras": [], "relaciones": []},
        "destinos_maestros.json": {"version_formato": 1, "destinos": []},
        "plantas.json": {"version_formato": 1, "plantas": []},
    }.items():
        (catalogos / nombre).write_text(json.dumps(contenido), encoding="utf-8")
    dataset = actual / "analisis_completo_guias.csv"
    _escribir_csv(dataset, filas_csv)
    return {"raiz": raiz, "catalogos": catalogos, "actual": actual, "dataset": dataset}


def _publicar(entorno, decision):
    generar_artefacto(
        ruta_dataset=entorno["dataset"], carpeta_catalogos=entorno["catalogos"],
        decisiones=[decision], ruta_salida=entorno["actual"] / "decisiones_pendientes.json",
    )


# ============================================================
# Detección (pura)
# ============================================================


def test_genera_decision_para_cliente_genuinamente_ausente():
    decision = detectar_decision_cliente_ausente(archivo="472238.jpeg", fila=_fila_csv())
    assert decision is not None
    assert decision["tipo"] == "CLIENTE_AUSENTE"
    assert set(decision["acciones_permitidas"]) == {"REGISTRAR_CLIENTE_MANUAL", "NO_PUEDO_DETERMINAR", "POSPONER"}


def test_no_genera_decision_si_cliente_tiene_algun_valor():
    """Nombre presente (aunque no corroborable) -- eso lo cubren
    CLIENTE_CANDIDATO/CLIENTE_DESCONOCIDO/ALIAS_CANDIDATO, no este tipo."""
    fila = _fila_csv(cliente="EMPRESA X", motivos_revision_documento="")
    assert detectar_decision_cliente_ausente(archivo="x", fila=fila) is None


def test_no_genera_decision_si_el_motivo_ya_no_esta_presente():
    fila = _fila_csv(motivos_revision_documento="MATERIAL_AUSENTE")
    assert detectar_decision_cliente_ausente(archivo="x", fila=fila) is None


# ============================================================
# Escaneo del dataset completo
# ============================================================


def test_deteccion_de_dataset_completo_caso_real_472238_472239(tmp_path):
    entorno = _entorno(tmp_path, filas_csv=[
        _fila_csv(numero_guia="472238", archivo="472238.jpeg"),
        _fila_csv(numero_guia="472239", archivo="472239.jpeg"),
        _fila_csv(numero_guia="472162", archivo="472162.jpeg", cliente="ACMA SA", motivos_revision_documento=""),
    ])
    candidatas = detectar_decisiones_cliente_ausente_sin_ocr(raiz_atlas=entorno["raiz"])
    assert {c["documento"]["numero_guia"] for c in candidatas} == {"472238", "472239"}


def test_reconciliar_publica_ambas_en_la_bandeja(tmp_path):
    entorno = _entorno(tmp_path, filas_csv=[
        _fila_csv(numero_guia="472238", archivo="472238.jpeg"),
        _fila_csv(numero_guia="472239", archivo="472239.jpeg"),
    ])
    resultado = reconciliar_decisiones_cliente_ausente(raiz_atlas=entorno["raiz"])
    assert resultado["decisiones_candidatas"] == 2
    assert resultado["decisiones_publicadas"] == 2


# ============================================================
# Aplicación -- REGISTRAR_CLIENTE_MANUAL
# ============================================================


def test_registrar_cliente_manual_crea_cliente_y_resuelve_el_documento(tmp_path):
    entorno = _entorno(tmp_path, filas_csv=[_fila_csv()])
    decision = detectar_decision_cliente_ausente(archivo="472238.jpeg", fila=_fila_csv())
    _publicar(entorno, decision)

    resultado = aplicar_decision_obra(
        raiz_atlas=entorno["raiz"], decision_id=decision["decision_id"],
        accion="REGISTRAR_CLIENTE_MANUAL", razon_social_manual="COMERCIAL NUEVA SPA",
        rut_manual="76086428-5",
    )
    assert resultado["ok"] is True
    assert resultado["cliente_id"]

    clientes = CatalogoClientes(entorno["catalogos"] / "clientes.json").listar()
    assert len(clientes) == 1
    assert clientes[0].razon_social == "COMERCIAL NUEVA SPA"
    assert clientes[0].estado_calidad == "CONFIRMADO"

    fila = _leer_csv(entorno["dataset"])["472238.jpeg"]
    assert fila["cliente"] == "COMERCIAL NUEVA SPA"
    assert "CLIENTE_AUSENTE" not in fila["motivos_revision_documento"]
    assert fila["indicador_revision"] == "OK"

    bandeja = json.loads((entorno["actual"] / "decisiones_pendientes.json").read_text(encoding="utf-8"))
    assert bandeja["decisiones"] == []
    assert (entorno["raiz"] / "operacion" / "actual" / "estado_operacion.json").exists()


def test_registrar_cliente_manual_reutiliza_cliente_ya_existente(tmp_path):
    """Dos documentos del mismo transporte (caso real 472238/472239):
    registrar el mismo nombre dos veces reutiliza el mismo cliente_id, no
    crea un duplicado."""
    entorno = _entorno(tmp_path, filas_csv=[
        _fila_csv(numero_guia="472238", archivo="472238.jpeg"),
        _fila_csv(numero_guia="472239", archivo="472239.jpeg"),
    ])
    decision_238 = detectar_decision_cliente_ausente(archivo="472238.jpeg", fila=_fila_csv(numero_guia="472238", archivo="472238.jpeg"))
    decision_239 = detectar_decision_cliente_ausente(archivo="472239.jpeg", fila=_fila_csv(numero_guia="472239", archivo="472239.jpeg"))
    generar_artefacto(
        ruta_dataset=entorno["dataset"], carpeta_catalogos=entorno["catalogos"],
        decisiones=[decision_238, decision_239], ruta_salida=entorno["actual"] / "decisiones_pendientes.json",
    )

    r1 = aplicar_decision_obra(
        raiz_atlas=entorno["raiz"], decision_id=decision_238["decision_id"],
        accion="REGISTRAR_CLIENTE_MANUAL", razon_social_manual="COMERCIAL NUEVA SPA",
    )
    r2 = aplicar_decision_obra(
        raiz_atlas=entorno["raiz"], decision_id=decision_239["decision_id"],
        accion="REGISTRAR_CLIENTE_MANUAL", razon_social_manual="COMERCIAL NUEVA SPA",
    )
    assert r1["cliente_id"] == r2["cliente_id"]
    clientes = CatalogoClientes(entorno["catalogos"] / "clientes.json").listar()
    assert len(clientes) == 1


def test_registrar_cliente_manual_sin_texto_falla(tmp_path):
    entorno = _entorno(tmp_path, filas_csv=[_fila_csv()])
    decision = detectar_decision_cliente_ausente(archivo="472238.jpeg", fila=_fila_csv())
    _publicar(entorno, decision)
    try:
        aplicar_decision_obra(
            raiz_atlas=entorno["raiz"], decision_id=decision["decision_id"],
            accion="REGISTRAR_CLIENTE_MANUAL", razon_social_manual="   ",
        )
        assert False, "debía lanzar"
    except ErrorAplicacionDecision:
        pass


def test_no_puedo_determinar_es_terminal_y_no_toca_el_dataset(tmp_path):
    entorno = _entorno(tmp_path, filas_csv=[_fila_csv()])
    decision = detectar_decision_cliente_ausente(archivo="472238.jpeg", fila=_fila_csv())
    _publicar(entorno, decision)
    fila_antes = _leer_csv(entorno["dataset"])["472238.jpeg"]

    resultado = aplicar_decision_obra(
        raiz_atlas=entorno["raiz"], decision_id=decision["decision_id"], accion="NO_PUEDO_DETERMINAR",
    )
    assert resultado["ok"] is True
    fila_despues = _leer_csv(entorno["dataset"])["472238.jpeg"]
    assert fila_antes == fila_despues

    resultado_reconciliado = reconciliar_decisiones_cliente_ausente(raiz_atlas=entorno["raiz"])
    assert resultado_reconciliado["decisiones_publicadas"] == 0
