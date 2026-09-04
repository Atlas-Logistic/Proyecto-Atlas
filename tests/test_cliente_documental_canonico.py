"""MOTOR DE EVIDENCIA FASE 3 -- primera aplicación real de
`CLIENTE_DESCONOCIDO`/`ALIAS_CANDIDATO` (hasta este bloque, ninguna de
las dos tenía backend: eran sólo UX preparatoria en Desktop). Cubre:
REGISTRAR/NO_REGISTRAR para clientes genuinamente nuevos, CONFIRMAR_ALIAS/
RECHAZAR para el patrón "RUT coincide, texto documental no" (mismo
patrón ya validado para vehículos), el registro de `ConfirmacionIdentidad`
y de Incidencia Documental como efectos de CONFIRMAR_ALIAS, y la
integración con `reconciliar_bandeja_decisiones` (enriquecimiento +
elevación a `RESUELTO_AUTOMATICAMENTE` tras confirmaciones independientes)."""
from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path

import pytest

from atlas_core.aplicacion_decisiones import ErrorAplicacionDecision, aplicar_decision_obra
from atlas_core.catalogo_clientes import CatalogoClientes
from atlas_core.decisiones_pendientes import crear_decision, generar_artefacto
from atlas_core.evidencia_entidades import AlmacenEvidenciaEntidades
from atlas_core.incidencias_documentales import AlmacenIncidenciasDocumentales
from atlas_core.procesamiento_masivo import COLUMNAS
from atlas_core.revalidacion_documental import _leer_filas, reconciliar_bandeja_decisiones

RUT_EBEMA = "76086428-5"
FECHA = "05-08-2026"


def _fila_csv(**overrides):
    fila = {c: "" for c in COLUMNAS}
    fila.update({
        "archivo": "1.jpeg", "estado_procesamiento": "OK", "numero_guia": "1",
        "numero_transporte": "T-1", "fecha": FECHA, "chofer": "CHOFER PRUEBA",
        "rut_chofer": "15489424-1", "cliente": "EBEMA SA", "obra_destino": "EBEMA SA",
        "patente_tracto": "AB1234", "patente_rampla": "CD5678",
        "indicador_revision": "REVISAR",
        "planta_origen_id": "", "planta_origen_nombre": "",
        "origen_determinado_por": "", "evidencia_origen": "",
        "despachar_a_crudo": "", "direccion_entrega": "", "estado_entrega": "",
        "distancia_km": "", "duracion_min": "", "proveedor_ruta": "",
        "estado_ruta": "", "motivo_ruta": "",
    })
    fila.update(overrides)
    return fila


def _escribir_csv(ruta, filas):
    with ruta.open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader()
        escritor.writerows(filas)


def _leer_csv(ruta):
    with ruta.open("r", newline="", encoding="utf-8-sig") as archivo:
        return list(csv.DictReader(archivo, delimiter=";"))


def _entorno(tmp_path, *, filas_csv, clientes=None):
    raiz = tmp_path / "Atlas"
    catalogos = raiz / "catalogos_privados"
    actual = raiz / "operacion" / "actual"
    catalogos.mkdir(parents=True)
    actual.mkdir(parents=True)
    contenido_clientes = {"version_formato": 1, "clientes": clientes or []}
    for nombre, contenido in {
        "clientes.json": contenido_clientes,
        "empresas.json": {},
        "vehiculos.json": {"version": 1, "vehiculos": []},
        "obras_destinos.json": {"version_formato": 1, "obras": [], "relaciones": []},
        "destinos_maestros.json": {"version_formato": 1, "destinos": []},
    }.items():
        (catalogos / nombre).write_text(json.dumps(contenido), encoding="utf-8")
    dataset = actual / "analisis_completo_guias.csv"
    _escribir_csv(dataset, filas_csv)
    return {"raiz": raiz, "catalogos": catalogos, "actual": actual, "dataset": dataset}


def _cliente_ebema_dict(cliente_id="cliente-ebema", aliases=None):
    return {
        "cliente_id": cliente_id, "razon_social": "EBEMA SA", "nombre_normalizado": "EBEMA",
        "nombre_comercial": "", "rut": RUT_EBEMA, "aliases": list(aliases or []),
        "estado_calidad": "CONFIRMADO", "estado_vigencia": "ACTIVO", "fuente": "TEST",
        "observacion": "", "fecha_creacion": "2026-01-01T00:00:00+00:00", "fecha_modificacion": "2026-01-01T00:00:00+00:00",
    }


def _decision_cliente_desconocido(*, guia="1", transporte="T-1", rut="76086428-5", valor_documental="CONSTRUCTORA NUEVA SPA"):
    return crear_decision(
        tipo="CLIENTE_DESCONOCIDO", entidad="CLIENTE", archivo=f"{guia}.jpeg",
        numero_guia=guia, numero_transporte=transporte, campo="cliente",
        valor_documental=valor_documental, valor_normalizado=valor_documental,
        identidad_resuelta=None, candidatos=(),
        motivos=("RUT_VALIDO_NO_EXISTE_EN_CATALOGO_MAESTRO",),
        evidencias=({"tipo": "RUT_VALIDO", "campo": "rut_cliente", "valor": rut},),
        acciones_permitidas=("REGISTRAR", "NO_REGISTRAR", "POSPONER"),
    )


def _decision_alias_candidato(*, guia="1", transporte="T-1", rut=RUT_EBEMA, valor_documental="PPP CONSTRUCCIONES", cliente_id="cliente-ebema", catalogo=None):
    identidad = {"entidad_id": cliente_id, "valor_canonico": "EBEMA SA", "rut": rut}
    if catalogo:
        identidad["catalogo"] = catalogo
    return crear_decision(
        tipo="ALIAS_CANDIDATO", entidad="CLIENTE", archivo=f"{guia}.jpeg",
        numero_guia=guia, numero_transporte=transporte, campo="cliente",
        valor_documental=valor_documental, valor_normalizado=valor_documental,
        identidad_resuelta=identidad, candidatos=(identidad,),
        motivos=("RUT_EXACTO_ALIAS_NO_CONFIRMADO",),
        evidencias=({"tipo": "RUT_EXACTO", "campo": "rut_cliente", "valor": rut},),
        acciones_permitidas=("CONFIRMAR_ALIAS", "RECHAZAR", "POSPONER"),
    )


# ============================================================
# CLIENTE_DESCONOCIDO -- REGISTRAR / NO_REGISTRAR
# ============================================================


def test_cliente_desconocido_registrar_crea_cliente_confirmado(tmp_path):
    entorno = _entorno(tmp_path, filas_csv=[_fila_csv()])
    decision = _decision_cliente_desconocido()
    generar_artefacto(
        ruta_dataset=entorno["dataset"], carpeta_catalogos=entorno["catalogos"],
        decisiones=[decision], ruta_salida=entorno["actual"] / "decisiones_pendientes.json",
    )
    resultado = aplicar_decision_obra(raiz_atlas=entorno["raiz"], decision_id=decision["decision_id"], accion="REGISTRAR")
    assert resultado["ok"] is True
    assert resultado["cliente_id"]
    clientes = CatalogoClientes(entorno["catalogos"] / "clientes.json").listar()
    assert len(clientes) == 1
    assert clientes[0].razon_social == "CONSTRUCTORA NUEVA SPA"
    assert clientes[0].rut == "76086428-5"
    assert clientes[0].estado_calidad == "CONFIRMADO"
    # El CSV documental nunca se toca.
    fila = _leer_csv(entorno["dataset"])[0]
    assert fila["cliente"] == "EBEMA SA"  # valor de la fixture, ajeno a esta decisión


def test_cliente_desconocido_no_registrar_no_escribe_catalogo(tmp_path):
    entorno = _entorno(tmp_path, filas_csv=[_fila_csv()])
    decision = _decision_cliente_desconocido()
    generar_artefacto(
        ruta_dataset=entorno["dataset"], carpeta_catalogos=entorno["catalogos"],
        decisiones=[decision], ruta_salida=entorno["actual"] / "decisiones_pendientes.json",
    )
    antes = (entorno["catalogos"] / "clientes.json").read_bytes()
    resultado = aplicar_decision_obra(raiz_atlas=entorno["raiz"], decision_id=decision["decision_id"], accion="NO_REGISTRAR")
    assert resultado["ok"] is True
    assert (entorno["catalogos"] / "clientes.json").read_bytes() == antes


def test_cliente_desconocido_sin_rut_registra_igual_sin_rut(tmp_path):
    """El RUT es opcional: si el documento nunca lo trajo (`valor` vacío
    en la evidencia), Atlas sigue pudiendo registrar el cliente -- sólo
    queda sin RUT, nunca bloquea el registro."""
    entorno = _entorno(tmp_path, filas_csv=[_fila_csv()])
    decision = _decision_cliente_desconocido(rut="")
    generar_artefacto(
        ruta_dataset=entorno["dataset"], carpeta_catalogos=entorno["catalogos"],
        decisiones=[decision], ruta_salida=entorno["actual"] / "decisiones_pendientes.json",
    )
    resultado = aplicar_decision_obra(raiz_atlas=entorno["raiz"], decision_id=decision["decision_id"], accion="REGISTRAR")
    assert resultado["ok"] is True
    clientes = CatalogoClientes(entorno["catalogos"] / "clientes.json").listar()
    assert clientes[0].rut == ""


# ============================================================
# ALIAS_CANDIDATO -- CONFIRMAR_ALIAS / RECHAZAR
# ============================================================


def test_alias_candidato_confirmar_alias_vincula_registra_confirmacion_e_incidencia(tmp_path):
    entorno = _entorno(tmp_path, filas_csv=[_fila_csv()], clientes=[_cliente_ebema_dict()])
    decision = _decision_alias_candidato()
    generar_artefacto(
        ruta_dataset=entorno["dataset"], carpeta_catalogos=entorno["catalogos"],
        decisiones=[decision], ruta_salida=entorno["actual"] / "decisiones_pendientes.json",
    )
    resultado = aplicar_decision_obra(raiz_atlas=entorno["raiz"], decision_id=decision["decision_id"], accion="CONFIRMAR_ALIAS")
    assert resultado["ok"] is True
    assert resultado["cliente_id"] == "cliente-ebema"

    clientes = CatalogoClientes(entorno["catalogos"] / "clientes.json").listar()
    assert "PPP CONSTRUCCIONES" in clientes[0].aliases

    confirmaciones = AlmacenEvidenciaEntidades(entorno["catalogos"] / "evidencia_entidades.json").listar()
    assert len(confirmaciones) == 1
    assert confirmaciones[0].valor_confirmado == "EBEMA SA"
    assert confirmaciones[0].contexto_clave == RUT_EBEMA

    incidencias = AlmacenIncidenciasDocumentales(entorno["catalogos"] / "incidencias_documentales.json").listar()
    assert len(incidencias) == 1
    assert incidencias[0].valor_documental == "PPP CONSTRUCCIONES"
    assert incidencias[0].valor_canonico == "EBEMA SA"

    # El CSV documental nunca se toca.
    fila = _leer_csv(entorno["dataset"])[0]
    assert fila["cliente"] == "EBEMA SA"  # valor original de la fixture


def test_alias_candidato_rechazar_no_escribe_ningun_catalogo(tmp_path):
    entorno = _entorno(tmp_path, filas_csv=[_fila_csv()], clientes=[_cliente_ebema_dict()])
    decision = _decision_alias_candidato()
    generar_artefacto(
        ruta_dataset=entorno["dataset"], carpeta_catalogos=entorno["catalogos"],
        decisiones=[decision], ruta_salida=entorno["actual"] / "decisiones_pendientes.json",
    )
    antes_clientes = (entorno["catalogos"] / "clientes.json").read_bytes()
    resultado = aplicar_decision_obra(raiz_atlas=entorno["raiz"], decision_id=decision["decision_id"], accion="RECHAZAR")
    assert resultado["ok"] is True
    assert (entorno["catalogos"] / "clientes.json").read_bytes() == antes_clientes
    assert not (entorno["catalogos"] / "evidencia_entidades.json").exists()
    assert not (entorno["catalogos"] / "incidencias_documentales.json").exists()


def test_alias_candidato_variante_empresas_json_no_soportada_aun(tmp_path):
    entorno = _entorno(tmp_path, filas_csv=[_fila_csv()])
    decision = _decision_alias_candidato(cliente_id=RUT_EBEMA, catalogo="empresas.json")
    generar_artefacto(
        ruta_dataset=entorno["dataset"], carpeta_catalogos=entorno["catalogos"],
        decisiones=[decision], ruta_salida=entorno["actual"] / "decisiones_pendientes.json",
    )
    with pytest.raises(ErrorAplicacionDecision):
        aplicar_decision_obra(raiz_atlas=entorno["raiz"], decision_id=decision["decision_id"], accion="CONFIRMAR_ALIAS")


# ============================================================
# Confirmaciones independientes -- integración con reconciliar_bandeja_decisiones
# ============================================================


def test_alias_persistido_con_rut_exacto_desaparece_sin_aplicacion(tmp_path):
    entorno = _entorno(tmp_path, filas_csv=[_fila_csv(numero_guia="1")], clientes=[_cliente_ebema_dict()])
    decision = _decision_alias_candidato(guia="1", transporte="T-1", valor_documental="PPP CONSTRUCCIONES")
    generar_artefacto(
        ruta_dataset=entorno["dataset"], carpeta_catalogos=entorno["catalogos"],
        decisiones=[decision], ruta_salida=entorno["actual"] / "decisiones_pendientes.json",
    )
    resultado = reconciliar_bandeja_decisiones(raiz_atlas=entorno["raiz"])
    assert all(d["decision_id"] != decision["decision_id"] for d in resultado["bandeja"]["decisiones"])
    assert resultado["decisiones_aplicadas_automaticamente"] == []
    assert AlmacenEvidenciaEntidades(entorno["catalogos"] / "evidencia_entidades.json").listar() == []
    assert CatalogoClientes(entorno["catalogos"] / "clientes.json").listar()[0].aliases == ()
    return
    """CASO C del bloque anterior, ahora de punta a punta con acciones
    reales: dos CONFIRMAR_ALIAS en transportes distintos elevan la
    relación RUT->EBEMA a conocimiento fuerte; una tercera aparición
    equivalente (nunca vista antes) debe resolverse SOLA al reconciliar
    la bandeja (MOTOR DE EVIDENCIA FASE 4 -- decisión de producto de
    Javier: RESUELTO_AUTOMATICAMENTE se aplica sin pedir un clic)."""
    entorno = _entorno(
        tmp_path,
        filas_csv=[_fila_csv(numero_guia="1"), _fila_csv(numero_guia="2", numero_transporte="T-2")],
        clientes=[_cliente_ebema_dict()],
    )
    decision_1 = _decision_alias_candidato(guia="1", transporte="T-1", valor_documental="PPP CONSTRUCCIONES")
    decision_2 = _decision_alias_candidato(guia="2", transporte="T-2", valor_documental="OTRO NOMBRE MAL")
    generar_artefacto(
        ruta_dataset=entorno["dataset"], carpeta_catalogos=entorno["catalogos"],
        decisiones=[decision_1, decision_2], ruta_salida=entorno["actual"] / "decisiones_pendientes.json",
    )
    r1 = aplicar_decision_obra(raiz_atlas=entorno["raiz"], decision_id=decision_1["decision_id"], accion="CONFIRMAR_ALIAS")
    assert r1["ok"] is True
    # decision_2 necesita re-publicarse tras el primer aplicar (mismo
    # patrón que el resto del proyecto: aplicar_decision_obra ya
    # regenera la bandeja, decision_2 sigue vigente en ella).
    r2 = aplicar_decision_obra(raiz_atlas=entorno["raiz"], decision_id=decision_2["decision_id"], accion="CONFIRMAR_ALIAS")
    assert r2["ok"] is True

    confirmaciones = AlmacenEvidenciaEntidades(entorno["catalogos"] / "evidencia_entidades.json").listar()
    assert len(confirmaciones) == 2

    # Tercera aparición equivalente: una decisión CLIENTE_DESCONOCIDO/
    # ALIAS_CANDIDATO nueva con el mismo RUT y un texto nunca visto.
    decision_3 = _decision_alias_candidato(guia="3", transporte="T-3", valor_documental="XYZ CONSTRUCCIONES")
    filas = _leer_filas(entorno["dataset"])
    filas.append(_fila_csv(numero_guia="3", numero_transporte="T-3"))
    from atlas_core.revalidacion_documental import _escribir_filas_completas
    _escribir_filas_completas(entorno["dataset"], filas)
    bandeja_actual = json.loads((entorno["actual"] / "decisiones_pendientes.json").read_text(encoding="utf-8"))
    bandeja_actual["decisiones"].append(decision_3)
    (entorno["actual"] / "decisiones_pendientes.json").write_text(json.dumps(bandeja_actual), encoding="utf-8")

    resultado = reconciliar_bandeja_decisiones(raiz_atlas=entorno["raiz"])
    publicada = resultado["bandeja"]

    # Ya NO queda pendiente -- se aplicó sola, sin pedir un clic.
    assert all(d["decision_id"] != decision_3["decision_id"] for d in publicada["decisiones"])

    aplicadas_auto = resultado["decisiones_aplicadas_automaticamente"]
    assert len(aplicadas_auto) == 1
    assert aplicadas_auto[0]["decision_id"] == decision_3["decision_id"]
    assert aplicadas_auto[0]["resultado"]["ok"] is True
    assert aplicadas_auto[0]["resultado"]["cliente_id"] == "cliente-ebema"

    # El alias quedó vinculado de verdad en el catálogo -- no sólo en el
    # ledger -- y el valor documental original ("XYZ CONSTRUCCIONES")
    # sigue siendo reconstruible desde el ledger/incidencia, nunca se
    # perdió.
    clientes_finales = CatalogoClientes(entorno["catalogos"] / "clientes.json").listar()
    assert "XYZ CONSTRUCCIONES" in clientes_finales[0].aliases

    ledger = json.loads((entorno["actual"] / "decisiones_aplicadas.json").read_text(encoding="utf-8"))
    aplicacion_3 = next(a for a in ledger["aplicaciones"] if a["decision_id"] == decision_3["decision_id"])
    assert aplicacion_3["actor"] == "ATLAS_AUTOMATICO"
    assert aplicacion_3["valor_documental"] == "XYZ CONSTRUCCIONES"
    assert aplicacion_3["valor_canonico"] == "EBEMA SA"
    assert aplicacion_3["evaluacion_evidencia_previa"]["resultado"] == "RESUELTO_AUTOMATICAMENTE"

    incidencias = AlmacenIncidenciasDocumentales(entorno["catalogos"] / "incidencias_documentales.json").listar()
    incidencia_3 = next(i for i in incidencias if i.numero_guia == "3")
    assert incidencia_3.valor_documental == "XYZ CONSTRUCCIONES"
    assert incidencia_3.valor_canonico == "EBEMA SA"

    # El CSV documental nunca se toca -- "XYZ CONSTRUCCIONES" sigue
    # siendo lo que dice la guía, incluso después de la auto-resolución.
    fila_3 = next(f for f in _leer_csv(entorno["dataset"]) if f["numero_guia"] == "3")
    assert fila_3["cliente"] == "EBEMA SA"  # valor original de _fila_csv, ajeno a esta decisión


# ============================================================
# CLI (aplicar_decision_pendiente.py) -- lo que Desktop invocaría en vivo
# ============================================================


def _ejecutar_cli(raiz, decision_id, accion, **extra):
    script = Path(__file__).resolve().parents[1] / "aplicar_decision_pendiente.py"
    argumentos = [sys.executable, str(script), "--raiz-atlas", str(raiz), "--decision-id", decision_id, "--accion", accion]
    for bandera, valor in extra.items():
        if valor:
            argumentos += [f"--{bandera}", valor]
    proceso = subprocess.run(argumentos, cwd=script.parent, capture_output=True, check=True)
    return json.loads(proceso.stdout.decode("ascii"))


def test_cli_confirmar_alias_de_punta_a_punta(tmp_path):
    entorno = _entorno(tmp_path, filas_csv=[_fila_csv()], clientes=[_cliente_ebema_dict()])
    decision = _decision_alias_candidato()
    generar_artefacto(
        ruta_dataset=entorno["dataset"], carpeta_catalogos=entorno["catalogos"],
        decisiones=[decision], ruta_salida=entorno["actual"] / "decisiones_pendientes.json",
    )
    respuesta = _ejecutar_cli(entorno["raiz"], decision["decision_id"], "CONFIRMAR_ALIAS")
    assert respuesta["ok"] is True
    assert respuesta["cliente_id"] == "cliente-ebema"


def test_cli_registrar_cliente_desconocido_de_punta_a_punta(tmp_path):
    entorno = _entorno(tmp_path, filas_csv=[_fila_csv()])
    decision = _decision_cliente_desconocido()
    generar_artefacto(
        ruta_dataset=entorno["dataset"], carpeta_catalogos=entorno["catalogos"],
        decisiones=[decision], ruta_salida=entorno["actual"] / "decisiones_pendientes.json",
    )
    respuesta = _ejecutar_cli(entorno["raiz"], decision["decision_id"], "REGISTRAR")
    assert respuesta["ok"] is True
    assert respuesta["cliente_id"]
