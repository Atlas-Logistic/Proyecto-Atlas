"""Capa canónica de ACCIONES OPERACIONALES -- aceptación sobre copias
sintéticas (nunca datos productivos). Cubre el contrato común: preview
estructurado, token, confirmación, estado base (PREVIEW_OBSOLETO),
respaldo/restauración, reconciliación, auditoría e idempotencia."""
from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from atlas_core.acciones_operacionales import (
    ACCIONES, CapaAccionesOperacionales, DESTRUCTIVA, LECTURA, OPERACIONAL_REVERSIBLE, SENSIBLE,
    TIPO_LEDGER_CORRECCION, catalogo_acciones,
)
from atlas_core.catalogo_clientes import CatalogoClientes, EstadoCalidadCliente
from atlas_core.catalogo_obras_destinos import CatalogoObrasDestinos
from atlas_core.decisiones_pendientes import crear_decision, generar_artefacto
from atlas_core.procesamiento_masivo import COLUMNAS

RUT_ACTIVO = "12345678-5"
RUT_INACTIVO = "11111111-1"


def _vehiculo(patente, tipo="TRACTO"):
    evidencia = {"tipo": "CONFIRMACION_HUMANA", "identificador_fuente": "TEST", "referencia_hash": "",
                 "campos_observados": {"patente": patente, "tipo": tipo, "observacion": ""},
                 "fecha": "2026-01-01T00:00:00+00:00", "actor_proceso": "TEST", "resultado": "SOPORTA"}
    return {"vehiculo_id": patente, "patente_canonica": patente, "tipo": tipo, "estado_calidad": "CONFIRMADO",
            "estado_vigencia": "ACTIVO", "aliases": [], "evidencias": [evidencia],
            "procedencia": "CONFIRMACION_HUMANA", "confirmado_por": "TEST",
            "fecha_confirmacion": "2026-01-01T00:00:00+00:00", "observaciones": "",
            "fecha_creacion": "2026-01-01T00:00:00+00:00", "fecha_modificacion": "2026-01-01T00:00:00+00:00"}


def _fila(guia, **extra):
    fila = {c: "" for c in COLUMNAS}
    fila.update({"archivo": f"{guia}.jpeg", "estado_procesamiento": "OK", "numero_guia": guia,
                 "numero_transporte": "0000900001", "cliente": "CLIENTE UNO SA", "chofer": "LUIS REYES",
                 "rut_chofer": RUT_ACTIVO, "patente_tracto": "KN5439", "obra_destino": "OBRA VIEJA",
                 "despachar_a_crudo": "CALLE DOS 200 SANTIAGO", "estado_ruta": "RUTA_CALCULADA"})
    fila.update(extra)
    return fila


@pytest.fixture
def entorno(tmp_path):
    raiz = tmp_path / "AtlasCopia"
    cat = raiz / "catalogos_privados"
    actual = raiz / "operacion" / "actual"
    cat.mkdir(parents=True)
    actual.mkdir(parents=True)
    (cat / "choferes.json").write_text(json.dumps({
        "123456785": {"nombre": "LUIS REYES", "rut": RUT_ACTIVO, "aliases": [], "activo": True},
        "111111111": {"nombre": "ANA SOTO", "rut": RUT_INACTIVO, "aliases": [], "activo": False},
    }), encoding="utf-8")
    (cat / "vehiculos.json").write_text(json.dumps({"version": 1, "vehiculos": [_vehiculo("KN5439")]}),
                                         encoding="utf-8")
    (cat / "clientes.json").write_text(json.dumps({"version_formato": 1, "clientes": []}), encoding="utf-8")
    (cat / "destinos_maestros.json").write_text(json.dumps({"version_formato": 1, "destinos": []}), encoding="utf-8")
    (cat / "obras_destinos.json").write_text(json.dumps({"version_formato": 1, "obras": [], "relaciones": []}),
                                             encoding="utf-8")
    for nombre, contenido in {"empresas.json": {}, "plantas.json": {"plantas": []}, "rutas.json": {"rutas": []}}.items():
        (cat / nombre).write_text(json.dumps(contenido), encoding="utf-8")
    cliente = CatalogoClientes(cat / "clientes.json").crear(
        razon_social="CLIENTE UNO SA", rut="76.111.111-6", fuente="TEST", estado_calidad=EstadoCalidadCliente.CONFIRMADO,
    )
    dataset = actual / "analisis_completo_guias.csv"
    with dataset.open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader()
        escritor.writerows([_fila("500001"), _fila("500002", obra_destino="OBRA OTRA")])
    (actual / "decisiones_aplicadas.json").write_text(json.dumps({"schema_version": 1, "aplicaciones": []}),
                                                      encoding="utf-8")
    decision = crear_decision(
        tipo="OBRA_DESCONOCIDA", entidad="OBRA", archivo="500001.jpeg", numero_guia="500001",
        numero_transporte="0000900001", campo="obra_destino", valor_documental="OBRA VIEJA",
        valor_normalizado="OBRA VIEJA", identidad_resuelta=None, candidatos=(),
        motivos=("OBRA_NO_EXISTE_PARA_CLIENTE",),
        evidencias=({"tipo": "CLIENTE_RESUELTO", "entidad_id": cliente.cliente_id},),
        acciones_permitidas=("REGISTRAR", "NO_REGISTRAR", "POSPONER"),
        contexto={"cliente_id": cliente.cliente_id, "cliente_canonico": cliente.razon_social, "destino_documental": ""},
    )
    generar_artefacto(ruta_dataset=dataset, carpeta_catalogos=cat, decisiones=[decision])
    return {"raiz": raiz, "cat": cat, "actual": actual, "cliente": cliente, "decision": decision, "dataset": dataset}


def _sha(ruta: Path) -> str:
    return hashlib.sha256(ruta.read_bytes()).hexdigest()


def _choferes(entorno):
    return json.loads((entorno["cat"] / "choferes.json").read_text(encoding="utf-8"))


def _bandeja(entorno):
    return json.loads((entorno["actual"] / "decisiones_pendientes.json").read_text(encoding="utf-8"))


# ------------------------------------------------------------ chofer (caso obligatorio)


def test_chofer_consulta_preview_ejecucion_auditoria_e_idempotencia(entorno):
    capa = CapaAccionesOperacionales(entorno["raiz"])
    # 1. consulta (LECTURA: sin confirmación ni token, sin escritura)
    inactivos = capa.previsualizar("CHOFER_CONSULTAR", {"estado": "INACTIVO"}, actor="B1", origen="B1")
    assert inactivos["estado"] == "RESULTADO" and inactivos["requiere_confirmacion"] is False
    assert [c["nombre"] for c in inactivos["resultado"]["choferes"]] == ["ANA SOTO"]
    assert not (entorno["actual"] / "acciones_operacionales.json").exists()


    # 2. preview: estructura completa y ningún dato operacional escrito
    antes = _sha(entorno["cat"] / "choferes.json")
    preview = capa.previsualizar("CHOFER_CAMBIAR_ESTADO", {"chofer": RUT_ACTIVO, "activo": False},
                                 actor="B1", origen="B1", referencia="orden: dejar inactivo a Luis Reyes")
    assert preview["estado"] == "PREVIEW"
    for clave in ("accion", "entidad", "valor_actual", "valor_propuesto", "afectados", "consecuencias",
                  "revalidaciones", "riesgo", "requiere_confirmacion", "token"):
        assert clave in preview
    assert preview["riesgo"] == OPERACIONAL_REVERSIBLE and preview["requiere_confirmacion"] is True
    assert preview["valor_actual"] == {"activo": True} and preview["valor_propuesto"] == {"activo": False}
    assert preview["afectados"]["guias"] == ["500001", "500002"]
    assert _sha(entorno["cat"] / "choferes.json") == antes

    # sin confirmación humana explícita no se ejecuta
    assert capa.ejecutar(preview["token"], actor="B1", origen="B1")["codigo"] == "CONFIRMACION_REQUERIDA"

    # 3. ejecución confirmada
    resultado = capa.ejecutar(preview["token"], actor="B1", origen="B1", confirmado_por="JAVIER")
    assert resultado["estado"] == "APLICADA", resultado
    assert _choferes(entorno)["123456785"]["activo"] is False
    assert _choferes(entorno)["123456785"]["nombre"] == "LUIS REYES"  # nunca borra ni toca identidad
    assert resultado["reconciliacion"]["ejecutado"] is True
    assert _bandeja(entorno)["catalogos_sha256"]["choferes"] == _sha(entorno["cat"] / "choferes.json").upper()
    assert Path(entorno["raiz"] / resultado["respaldo"] / "choferes.json").is_file()

    # 4. auditoría
    auditoria = capa.auditoria()
    assert len(auditoria) == 1
    entrada = auditoria[0]
    assert entrada["actor"] == "B1" and entrada["confirmado_por"] == "JAVIER"
    assert entrada["accion"] == "CHOFER_CAMBIAR_ESTADO" and entrada["resultado"] == "APLICADA"
    assert entrada["antes"] == {"activo": True} and entrada["despues"] == {"activo": False}
    assert entrada["referencia"] == "orden: dejar inactivo a Luis Reyes" and entrada["timestamp"]

    # 5. segunda ejecución idempotente (mismo token): sin escritura ni auditoría nueva
    despues = _sha(entorno["cat"] / "choferes.json")
    repetido = capa.ejecutar(preview["token"], actor="B1", origen="B1", confirmado_por="JAVIER")
    assert repetido["estado"] == "APLICADA" and repetido["idempotente"] is True
    assert _sha(entorno["cat"] / "choferes.json") == despues and len(capa.auditoria()) == 1
    # y la misma orden vuelta a pedir no produce nada que confirmar
    otra = capa.previsualizar("CHOFER_CAMBIAR_ESTADO", {"chofer": "123456785", "activo": False}, actor="B1", origen="B1")
    assert otra["estado"] == "SIN_CAMBIOS" and otra["token"] is None and otra["requiere_confirmacion"] is False
    assert otra["auditoria_previa"] == entrada["auditoria_id"]

    activos = capa.consultar("CHOFER_CONSULTAR", {"estado": "ACTIVO"}, actor="B1", origen="B1")
    assert activos["resultado"]["total"] == 0


def test_corregir_identidad_documental_chofer_activa_es_focal_y_auditable(entorno, monkeypatch):
    """La corrección de operador cambia ambos campos sin reconciliar globalmente."""
    _escribir_dataset(entorno, [_fila("500001", chofer="No encontrado", rut_chofer="No encontrado"),
                                _fila("500002")])
    bandeja_antes = _sha(entorno["actual"] / "decisiones_pendientes.json")
    forzadas: list[set[str]] = []
    _sin_mantenimiento_real(monkeypatch, forzadas)
    capa = CapaAccionesOperacionales(entorno["raiz"])

    preview = capa.previsualizar(
        "DOCUMENTO_CORREGIR_IDENTIDAD_CHOFER",
        {"numero_guia": "500001", "chofer": "LUIS REYES", "rut_chofer": RUT_ACTIVO}, actor="JAVIER",
    )
    assert preview["estado"] == "PREVIEW", preview
    assert preview["valor_actual"] == {"chofer": "No encontrado", "rut_chofer": "No encontrado"}
    assert preview["valor_propuesto"] == {"chofer": "LUIS REYES", "rut_chofer": "12.345.678-5"}
    assert preview["afectados"]["guias"] == ["500001", "500002"]
    assert preview["revalidaciones"] == ["MANTENIMIENTO_FOCAL_GUIAS_DEL_VIAJE"]

    resultado = capa.ejecutar(preview["token"], actor="JAVIER", confirmado_por="JAVIER")
    assert resultado["estado"] == "APLICADA", resultado
    filas = _filas_dataset(entorno)
    assert (filas["500001.jpeg"]["chofer"], filas["500001.jpeg"]["rut_chofer"]) == ("LUIS REYES", "12.345.678-5")
    assert filas["500002.jpeg"]["chofer"] == "LUIS REYES"  # no fue modificado
    assert forzadas == [{"500001", "500002"}]
    assert resultado["reconciliacion"] is None and resultado["revalidacion"]["reporte"] is None
    assert _sha(entorno["actual"] / "decisiones_pendientes.json") == bandeja_antes
    aplicaciones = json.loads((entorno["actual"] / "decisiones_aplicadas.json").read_text(encoding="utf-8"))["aplicaciones"]
    correcciones = [a for a in aplicaciones if a["accion"] == "CORREGIR_IDENTIDAD_CHOFER"]
    assert [(a["campo"], a["valor_documental"], a["valor_corregido"]) for a in correcciones] == [
        ("chofer", "No encontrado", "LUIS REYES"), ("rut_chofer", "No encontrado", "12.345.678-5"),
    ]


def test_corregir_identidad_documental_chofer_rechaza_nombre_o_rut_contradictorios(entorno):
    capa = CapaAccionesOperacionales(entorno["raiz"])
    nombre = capa.previsualizar(
        "DOCUMENTO_CORREGIR_IDENTIDAD_CHOFER",
        {"numero_guia": "500001", "chofer": "ANA SOTO", "rut_chofer": RUT_ACTIVO}, actor="JAVIER",
    )
    assert nombre["codigo"] == "PRECONDICION_FALLIDA" and "nombre no coincide" in nombre["mensaje"]
    inactivo = capa.previsualizar(
        "DOCUMENTO_CORREGIR_IDENTIDAD_CHOFER",
        {"numero_guia": "500001", "chofer": "ANA SOTO", "rut_chofer": RUT_INACTIVO}, actor="JAVIER",
    )
    assert inactivo["codigo"] == "PRECONDICION_FALLIDA" and "inactivo" in inactivo["mensaje"]


def test_preview_obsoleto_si_la_entidad_cambio(entorno):
    capa = CapaAccionesOperacionales(entorno["raiz"])
    preview = capa.previsualizar("CHOFER_CAMBIAR_ESTADO", {"chofer": RUT_ACTIVO, "activo": False}, actor="JAVIER")
    catalogo = _choferes(entorno)
    catalogo["123456785"]["aliases"] = ["LUCHO REYES"]  # cambio concurrente de la misma entidad
    (entorno["cat"] / "choferes.json").write_text(json.dumps(catalogo), encoding="utf-8")

    resultado = capa.ejecutar(preview["token"], actor="JAVIER", confirmado_por="JAVIER")
    assert resultado["estado"] == "PREVIEW_OBSOLETO"
    assert _choferes(entorno)["123456785"]["activo"] is True  # nada ejecutado en silencio
    nuevo = resultado["preview_nuevo"]
    assert nuevo["estado"] == "PREVIEW" and nuevo["token"] != preview["token"]
    assert capa.ejecutar(preview["token"], actor="JAVIER", confirmado_por="JAVIER")["codigo"] == "TOKEN_DESCONOCIDO"
    assert capa.ejecutar(nuevo["token"], actor="JAVIER", confirmado_por="JAVIER")["estado"] == "APLICADA"
    assert _choferes(entorno)["123456785"] == {"nombre": "LUIS REYES", "rut": RUT_ACTIVO,
                                               "aliases": ["LUCHO REYES"], "activo": False}


def test_cambio_ajeno_a_la_entidad_no_invalida_el_preview(entorno):
    capa = CapaAccionesOperacionales(entorno["raiz"])
    preview = capa.previsualizar("CHOFER_CAMBIAR_ESTADO", {"chofer": RUT_ACTIVO, "activo": False}, actor="JAVIER")
    catalogo = _choferes(entorno)
    catalogo["111111111"]["aliases"] = ["ANITA"]
    (entorno["cat"] / "choferes.json").write_text(json.dumps(catalogo), encoding="utf-8")
    assert capa.ejecutar(preview["token"], actor="JAVIER", confirmado_por="JAVIER")["estado"] == "APLICADA"


def test_preview_expirado(entorno):
    instante = [datetime(2026, 9, 28, 12, tzinfo=timezone.utc)]
    capa = CapaAccionesOperacionales(entorno["raiz"], reloj=lambda: instante[0])
    preview = capa.previsualizar("CHOFER_CAMBIAR_ESTADO", {"chofer": RUT_ACTIVO, "activo": False}, actor="JAVIER")
    instante[0] += timedelta(hours=1)
    # expirado y ya depurado del registro: nunca ejecutable
    assert capa.ejecutar(preview["token"], actor="JAVIER", confirmado_por="JAVIER")["codigo"] in {
        "PREVIEW_EXPIRADO", "TOKEN_DESCONOCIDO"}
    assert _choferes(entorno)["123456785"]["activo"] is True


def test_token_no_ejecuta_otra_accion(entorno):
    capa = CapaAccionesOperacionales(entorno["raiz"])
    preview = capa.previsualizar("CHOFER_CAMBIAR_ESTADO", {"chofer": RUT_ACTIVO, "activo": False}, actor="JAVIER")
    r = capa.ejecutar(preview["token"], actor="JAVIER", confirmado_por="JAVIER", accion_esperada="OBRA_REGISTRAR")
    assert r["codigo"] == "TOKEN_NO_CORRESPONDE"
    assert _choferes(entorno)["123456785"]["activo"] is True


# ------------------------------------------------------------ obras / destinos


def test_registrar_obra_y_vincular_destino_idempotente(entorno):
    capa = CapaAccionesOperacionales(entorno["raiz"])
    cliente_id = entorno["cliente"].cliente_id
    p = capa.previsualizar("OBRA_REGISTRAR", {"cliente_id": cliente_id, "nombre_obra": "Edificio Norte"}, actor="JAVIER")
    assert p["estado"] == "PREVIEW" and p["valor_actual"] is None
    r = capa.ejecutar(p["token"], actor="JAVIER", confirmado_por="JAVIER")
    assert r["estado"] == "APLICADA", r
    obra_id = r["despues"]["obra_id"]
    repetida = capa.previsualizar("OBRA_REGISTRAR", {"cliente_id": cliente_id, "nombre_obra": "EDIFICIO  norte"},
                                  actor="JAVIER")
    assert repetida["estado"] == "SIN_CAMBIOS"

    d = capa.previsualizar("DESTINO_REGISTRAR", {"direccion": "AV NORTE 100", "comuna": "SANTIAGO"}, actor="JAVIER")
    rd = capa.ejecutar(d["token"], actor="JAVIER", confirmado_por="JAVIER")
    assert rd["estado"] == "APLICADA", rd
    destino_id = rd["despues"]["destino_id"]
    assert capa.previsualizar("DESTINO_REGISTRAR", {"direccion": "AV NORTE 100", "comuna": "SANTIAGO"},
                              actor="JAVIER")["estado"] == "SIN_CAMBIOS"

    v = capa.previsualizar("OBRA_VINCULAR_DESTINO", {"obra_id": obra_id, "destino_id": destino_id}, actor="JAVIER")
    assert v["estado"] == "PREVIEW" and v["valor_propuesto"]["estado"] == "CONFIRMADA"
    rv = capa.ejecutar(v["token"], actor="JAVIER", confirmado_por="JAVIER")
    assert rv["estado"] == "APLICADA", rv
    catalogo = CatalogoObrasDestinos(ruta=entorno["cat"] / "obras_destinos.json",
                                     ruta_clientes=entorno["cat"] / "clientes.json",
                                     ruta_destinos=entorno["cat"] / "destinos_maestros.json")
    relaciones = catalogo.listar_relaciones()
    assert len(relaciones) == 1 and relaciones[0].estado == "CONFIRMADA"
    assert catalogo.resolver_obra_destino_confirmada_global(nombre_obra="EDIFICIO NORTE").destino.destino_id == destino_id
    # repetir la vinculación no duplica relación ni evidencia
    assert capa.previsualizar("OBRA_VINCULAR_DESTINO", {"obra_id": obra_id, "destino_id": destino_id},
                              actor="JAVIER")["estado"] == "SIN_CAMBIOS"
    assert len(catalogo.listar_relaciones()) == 1
    assert [a["accion"] for a in capa.auditoria()] == ["OBRA_REGISTRAR", "DESTINO_REGISTRAR", "OBRA_VINCULAR_DESTINO"]


def test_corregir_obra_rechaza_colision(entorno):
    capa = CapaAccionesOperacionales(entorno["raiz"])
    cliente_id = entorno["cliente"].cliente_id
    ids = []
    for nombre in ("OBRA A", "OBRA B"):
        p = capa.previsualizar("OBRA_REGISTRAR", {"cliente_id": cliente_id, "nombre_obra": nombre}, actor="JAVIER")
        ids.append(capa.ejecutar(p["token"], actor="JAVIER", confirmado_por="JAVIER")["despues"]["obra_id"])
    choque = capa.previsualizar("OBRA_CORREGIR", {"obra_id": ids[0], "nombre_canonico": "OBRA B"}, actor="JAVIER")
    assert choque["codigo"] == "CONFLICTO"
    ok = capa.previsualizar("OBRA_CORREGIR", {"obra_id": ids[0], "nombre_canonico": "OBRA A1", "aliases": ["OBRA A"]},
                            actor="JAVIER")
    assert capa.ejecutar(ok["token"], actor="JAVIER", confirmado_por="JAVIER")["despues"] == {
        "nombre_canonico": "OBRA A1", "aliases": ["OBRA A"]}


def test_corregir_obra_promueve_alias_existente_a_canonico(entorno):
    capa = CapaAccionesOperacionales(entorno["raiz"])
    cliente_id = entorno["cliente"].cliente_id
    p = capa.previsualizar("OBRA_REGISTRAR", {"cliente_id": cliente_id, "nombre_obra": "OBRA TALCANUANO",
                                              "alias_documental": "OBRA TALCAHUANO"}, actor="JAVIER")
    obra_id = capa.ejecutar(p["token"], actor="JAVIER", confirmado_por="JAVIER")["despues"]["obra_id"]
    parametros = {"obra_id": obra_id, "nombre_canonico": "OBRA TALCAHUANO", "aliases": ["OBRA TALCANUANO"]}
    ok = capa.previsualizar("OBRA_CORREGIR", parametros, actor="JAVIER")
    assert capa.ejecutar(ok["token"], actor="JAVIER", confirmado_por="JAVIER")["despues"] == {
        "nombre_canonico": "OBRA TALCAHUANO", "aliases": ["OBRA TALCANUANO"]}
    assert capa.previsualizar("OBRA_CORREGIR", parametros, actor="JAVIER")["estado"] == "SIN_CAMBIOS"


class _EscritorDisponible:
    vigente = True

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.adquisiciones = 0
        self.cerrado = False

    def adquirir(self):
        self.adquisiciones += 1
        return True

    def cerrar(self):
        self.cerrado = True


def _registrar_obra(capa, cliente_id, nombre):
    preview = capa.previsualizar("OBRA_REGISTRAR", {"cliente_id": cliente_id, "nombre_obra": nombre}, actor="JAVIER")
    return capa.ejecutar(preview["token"], actor="JAVIER", confirmado_por="JAVIER")["despues"]["obra_id"]


def test_consolidar_obra_duplicada_preview_respaldo_idempotencia_y_sin_documentos(entorno):
    escritor = _EscritorDisponible()
    capa = CapaAccionesOperacionales(
        entorno["raiz"], fabrica_escritor=lambda: escritor,
    )
    cliente_id = entorno["cliente"].cliente_id
    principal_id = _registrar_obra(capa, cliente_id, "CONSTRUCTORA INMOBILIARIA E")
    destino = capa.previsualizar("DESTINO_REGISTRAR", {"direccion": "AV VINA 3451", "comuna": "SAN JOAQUIN"}, actor="JAVIER")
    destino_id = capa.ejecutar(destino["token"], actor="JAVIER", confirmado_por="JAVIER")["despues"]["destino_id"]
    vinculo = capa.previsualizar("OBRA_VINCULAR_DESTINO", {"obra_id": principal_id, "destino_id": destino_id}, actor="JAVIER")
    assert capa.ejecutar(vinculo["token"], actor="JAVIER", confirmado_por="JAVIER")["estado"] == "APLICADA"
    duplicada_id = _registrar_obra(capa, cliente_id, "CONSTRUCTORA INMOBILIARIA")
    filas = list(csv.DictReader(entorno["dataset"].open(encoding="utf-8-sig", newline=""), delimiter=";"))
    filas[0]["obra_destino"] = "CONSTRUCTORA INMOBILIARIA"
    with entorno["dataset"].open("w", encoding="utf-8-sig", newline="") as archivo:
        salida = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        salida.writeheader()
        salida.writerows(filas)
    antes_dataset = _sha(entorno["dataset"])
    antes_duplicada = next(o for o in CatalogoObrasDestinos(
        ruta=entorno["cat"] / "obras_destinos.json", ruta_clientes=entorno["cat"] / "clientes.json",
        ruta_destinos=entorno["cat"] / "destinos_maestros.json").listar_obras() if o.obra_id == duplicada_id).evidencias

    preview = capa.previsualizar("OBRA_CONSOLIDAR_DUPLICADA", {
        "obra_principal_id": principal_id, "obra_duplicada_id": duplicada_id, "referencia": "evidencia documental única",
    }, actor="JAVIER")
    assert preview["estado"] == "PREVIEW"
    assert preview["valor_propuesto"]["conservar_obra_id"] == principal_id
    assert preview["afectados"]["guias"] == ["500001"]
    assert preview["afectados"]["relaciones_duplicada"] == []
    resultado = capa.ejecutar(preview["token"], actor="JAVIER", confirmado_por="JAVIER")
    assert resultado["estado"] == "APLICADA", resultado
    assert escritor.adquisiciones == 1 and escritor.cerrado is True
    assert Path(entorno["raiz"] / resultado["respaldo"] / "obras_destinos.json").is_file()
    assert _sha(entorno["dataset"]) == antes_dataset
    catalogo = CatalogoObrasDestinos(ruta=entorno["cat"] / "obras_destinos.json",
                                     ruta_clientes=entorno["cat"] / "clientes.json",
                                     ruta_destinos=entorno["cat"] / "destinos_maestros.json")
    obras = {o.obra_id: o for o in catalogo.listar_obras()}
    assert obras[principal_id].estado == "CONFIRMADA"
    assert "CONSTRUCTORA INMOBILIARIA" in obras[principal_id].aliases_documentales
    assert obras[duplicada_id].estado == "INACTIVA" and obras[duplicada_id].estado_vigencia == "INACTIVO"
    assert obras[duplicada_id].evidencias == antes_duplicada
    assert capa.previsualizar("OBRA_CONSOLIDAR_DUPLICADA", {
        "obra_principal_id": principal_id, "obra_duplicada_id": duplicada_id,
    }, actor="JAVIER")["estado"] == "SIN_CAMBIOS"


def test_consolidar_obra_duplicada_falla_cerrado_si_no_hay_escritor_global(entorno):
    class EscritorOcupado(_EscritorDisponible):
        def adquirir(self):
            return False

    capa_normal = CapaAccionesOperacionales(entorno["raiz"])
    principal_id = _registrar_obra(capa_normal, entorno["cliente"].cliente_id, "OBRA PRINCIPAL")
    # La principal se confirma por la vía canónica antes de intentar consolidar.
    destino = capa_normal.previsualizar("DESTINO_REGISTRAR", {"direccion": "CALLE PRINCIPAL 1"}, actor="JAVIER")
    destino_id = capa_normal.ejecutar(destino["token"], actor="JAVIER", confirmado_por="JAVIER")["despues"]["destino_id"]
    vinculo = capa_normal.previsualizar("OBRA_VINCULAR_DESTINO", {"obra_id": principal_id, "destino_id": destino_id}, actor="JAVIER")
    capa_normal.ejecutar(vinculo["token"], actor="JAVIER", confirmado_por="JAVIER")
    duplicada_id = _registrar_obra(capa_normal, entorno["cliente"].cliente_id, "OBRA DUPLICADA")
    antes = _sha(entorno["cat"] / "obras_destinos.json")
    capa = CapaAccionesOperacionales(entorno["raiz"], fabrica_escritor=lambda: EscritorOcupado())
    preview = capa.previsualizar("OBRA_CONSOLIDAR_DUPLICADA", {
        "obra_principal_id": principal_id, "obra_duplicada_id": duplicada_id,
    }, actor="JAVIER")
    resultado = capa.ejecutar(preview["token"], actor="JAVIER", confirmado_por="JAVIER")
    assert resultado["codigo"] == "ESCRITOR_OCUPADO"
    assert _sha(entorno["cat"] / "obras_destinos.json") == antes


# ------------------------------------------------------------ documento


def test_corregir_campo_documental_retira_y_recalcula_decisiones_obsoletas(entorno):
    capa = CapaAccionesOperacionales(entorno["raiz"])
    vieja = entorno["decision"]["decision_id"]
    assert [d["decision_id"] for d in _bandeja(entorno)["decisiones"]] == [vieja]
    p = capa.previsualizar("DOCUMENTO_CORREGIR_CAMPO",
                           {"numero_guia": "500001", "campo": "obra_destino", "valor": "OBRA NUEVA SA"},
                           actor="B1", origen="B1")
    assert p["estado"] == "PREVIEW", p
    assert p["valor_actual"] == {"obra_destino": "OBRA VIEJA"}
    assert [d["decision_id"] for d in p["afectados"]["decisiones_obsoletas"]] == [vieja]

    r = capa.ejecutar(p["token"], actor="B1", origen="B1", confirmado_por="JAVIER")
    assert r["estado"] == "APLICADA", r
    filas = {f["numero_guia"]: f for f in csv.DictReader(
        entorno["dataset"].open(encoding="utf-8-sig", newline=""), delimiter=";")}
    assert filas["500001"]["obra_destino"] == "OBRA NUEVA SA"
    assert filas["500002"]["obra_destino"] == "OBRA OTRA"  # nada fuera del documento
    bandeja = _bandeja(entorno)
    assert vieja not in {d["decision_id"] for d in bandeja["decisiones"]}
    assert vieja in r["decisiones_retiradas"]
    # la pregunta vigente, si la hay, es por el valor NUEVO
    assert all(d["valor_documental"] == "OBRA NUEVA SA" for d in bandeja["decisiones"] if d["campo"] == "obra_destino")
    assert bandeja["dataset_sha256"] == _sha(entorno["dataset"]).upper()
    ledger = json.loads((entorno["actual"] / "decisiones_aplicadas.json").read_text(encoding="utf-8"))
    proteccion = [a for a in ledger["aplicaciones"] if a["tipo"] == TIPO_LEDGER_CORRECCION]
    assert len(proteccion) == 1 and proteccion[0]["campo"] == "obra_destino"
    assert proteccion[0]["valor_documental"] == "OBRA VIEJA" and proteccion[0]["valor_corregido"] == "OBRA NUEVA SA"

    # idempotencia: repetir la corrección no escribe ni duplica protección
    otra = capa.previsualizar("DOCUMENTO_CORREGIR_CAMPO",
                              {"numero_guia": "500001", "campo": "OBRA_DESTINO", "valor": "OBRA NUEVA SA"}, actor="B1",
                              origen="B1")
    assert otra["estado"] == "SIN_CAMBIOS"
    # reversible: el operador puede volver a corregir su propia corrección
    rev = capa.previsualizar("DOCUMENTO_CORREGIR_CAMPO",
                             {"numero_guia": "500001", "campo": "obra_destino", "valor": "OBRA VIEJA"}, actor="JAVIER")
    assert rev["estado"] == "PREVIEW"


def test_campo_documental_no_autorizado_o_invalido(entorno):
    capa = CapaAccionesOperacionales(entorno["raiz"])
    assert capa.previsualizar("DOCUMENTO_CORREGIR_CAMPO", {"numero_guia": "500001", "campo": "peso_kg", "valor": "1"},
                              actor="JAVIER")["codigo"] == "PARAMETRO_INVALIDO"
    assert capa.previsualizar("DOCUMENTO_CORREGIR_CAMPO",
                              {"numero_guia": "500001", "campo": "rut_cliente", "valor": "99.999.999-0"},
                              actor="JAVIER")["codigo"] == "PARAMETRO_INVALIDO"
    assert capa.previsualizar("DOCUMENTO_CORREGIR_CAMPO", {"numero_guia": "999999", "campo": "cliente", "valor": "X"},
                              actor="JAVIER")["codigo"] == "ENTIDAD_NO_ENCONTRADA"


def test_campo_fijado_por_decision_de_revision_no_se_pisa(entorno):
    ruta = entorno["actual"] / "decisiones_aplicadas.json"
    ruta.write_text(json.dumps({"schema_version": 1, "aplicaciones": [{
        "decision_id": "x", "tipo": "OBRA_DESCONOCIDA", "accion": "REGISTRAR", "campo": "obra_destino",
        "documento": {"archivo": "500001.jpeg", "numero_guia": "500001"}}]}), encoding="utf-8")
    capa = CapaAccionesOperacionales(entorno["raiz"])
    r = capa.previsualizar("DOCUMENTO_CORREGIR_CAMPO",
                           {"numero_guia": "500001", "campo": "obra_destino", "valor": "OTRA"}, actor="JAVIER")
    assert r["codigo"] == "CAMPO_FIJADO_POR_DECISION_HUMANA"


# ------------------------------------------------------------ vehículo / decisión


def test_asignar_vehiculo_y_repetir(entorno):
    capa = CapaAccionesOperacionales(entorno["raiz"])
    p = capa.previsualizar("CHOFER_ASIGNAR_VEHICULO", {"chofer": RUT_ACTIVO, "patente": "kn-5439"}, actor="JAVIER")
    assert p["estado"] == "PREVIEW" and p["valor_propuesto"] == {"rut_chofer": "123456785", "patente": "KN5439",
                                                                  "tipo": "TRACTO"}
    assert capa.ejecutar(p["token"], actor="JAVIER", confirmado_por="JAVIER")["estado"] == "APLICADA"
    vehiculos = json.loads((entorno["cat"] / "vehiculos.json").read_text(encoding="utf-8"))["vehiculos"]
    assert len(vehiculos[0]["evidencias"]) == 2
    assert capa.previsualizar("CHOFER_ASIGNAR_VEHICULO", {"chofer": RUT_ACTIVO, "patente": "KN5439"},
                              actor="JAVIER")["estado"] == "SIN_CAMBIOS"
    assert capa.previsualizar("CHOFER_ASIGNAR_VEHICULO", {"chofer": RUT_INACTIVO, "patente": "KN5439"},
                              actor="JAVIER")["codigo"] == "PRECONDICION_FALLIDA"
    assert capa.previsualizar("CHOFER_ASIGNAR_VEHICULO", {"chofer": RUT_ACTIVO, "patente": "ZZ9999"},
                              actor="JAVIER")["codigo"] == "PRECONDICION_FALLIDA"


def test_decision_aplicar_via_capa_y_consulta(entorno):
    capa = CapaAccionesOperacionales(entorno["raiz"])
    vieja = entorno["decision"]["decision_id"]
    consulta = capa.consultar("DECISION_CONSULTAR", {"numero_guia": "500001"}, actor="B1", origen="B1")
    assert [d["decision_id"] for d in consulta["resultado"]["decisiones"]] == [vieja]
    no_permitida = capa.previsualizar("DECISION_APLICAR", {"decision_id": vieja, "accion_decision": "CONFIRMAR_PLANTA"},
                                      actor="B1", origen="B1")
    assert no_permitida["codigo"] == "PARAMETRO_INVALIDO"
    p = capa.previsualizar("DECISION_APLICAR", {"decision_id": vieja, "accion_decision": "NO_REGISTRAR"},
                           actor="B1", origen="B1")
    assert p["estado"] == "PREVIEW"
    r = capa.ejecutar(p["token"], actor="B1", origen="B1", confirmado_por="JAVIER")
    assert r["estado"] == "APLICADA", r
    ledger = json.loads((entorno["actual"] / "decisiones_aplicadas.json").read_text(encoding="utf-8"))
    assert [a["decision_id"] for a in ledger["aplicaciones"]] == [vieja]
    assert capa.previsualizar("DECISION_APLICAR", {"decision_id": vieja, "accion_decision": "NO_REGISTRAR"},
                              actor="B1", origen="B1")["estado"] == "SIN_CAMBIOS"


def test_fallo_del_servicio_restaura_respaldo_y_audita(entorno, monkeypatch):
    capa = CapaAccionesOperacionales(entorno["raiz"])
    p = capa.previsualizar("CHOFER_CAMBIAR_ESTADO", {"chofer": RUT_ACTIVO, "activo": False}, actor="JAVIER")
    original = _sha(entorno["cat"] / "choferes.json")

    def falla(ruta, identificador, activo):
        catalogo = json.loads(Path(ruta).read_text(encoding="utf-8"))
        catalogo[identificador]["activo"] = activo
        Path(ruta).write_text(json.dumps(catalogo), encoding="utf-8")  # escritura parcial...
        raise OSError("disco lleno")  # ...y luego fallo

    monkeypatch.setattr("atlas_core.catalogos.cambiar_estado_chofer", falla)
    r = capa.ejecutar(p["token"], actor="JAVIER", confirmado_por="JAVIER")
    assert r["estado"] == "FALLIDA" and r["respaldo_restaurado"] is True
    assert _sha(entorno["cat"] / "choferes.json") == original
    assert capa.auditoria()[-1]["resultado"] == "FALLIDA"


# ------------------------------------------------------------ seguridad / riesgo


def test_accion_invalida_y_destructiva_rechazadas(entorno):
    capa = CapaAccionesOperacionales(entorno["raiz"])
    for accion in ("SQL_EXEC", "SHELL", "", None, "chofer_cambiar_estado_x", 42):
        assert capa.previsualizar(accion, {}, actor="B1", origen="B1")["codigo"] == "ACCION_INVALIDA"
    for accion in ("ENTIDAD_ELIMINAR", "EVIDENCIA_ELIMINAR", "HISTORIAL_ELIMINAR"):
        assert capa.previsualizar(accion, {}, actor="B1", origen="B1")["codigo"] == "ACCION_PROHIBIDA"
    assert capa.ejecutar("no-existe", actor="B1", origen="B1", confirmado_por="JAVIER")["codigo"] == "TOKEN_DESCONOCIDO"
    assert not (entorno["actual"] / "acciones_operacionales.json").exists()


def test_paths_y_comandos_arbitrarios_rechazados(entorno):
    capa = CapaAccionesOperacionales(entorno["raiz"])
    antes = {p.name: _sha(p) for p in entorno["cat"].iterdir()}
    casos = [
        ("CHOFER_CAMBIAR_ESTADO", {"chofer": "../../catalogos_privados/choferes.json", "activo": False}, "PARAMETRO_INVALIDO"),
        ("CHOFER_CAMBIAR_ESTADO", {"chofer": "1; rm -rf /", "activo": False}, "PARAMETRO_INVALIDO"),
        ("CHOFER_CAMBIAR_ESTADO", {"chofer": RUT_ACTIVO, "activo": "false"}, "PARAMETRO_INVALIDO"),
        ("CHOFER_CAMBIAR_ESTADO", {"chofer": RUT_ACTIVO, "activo": False, "ruta": "C:/Windows"}, "PARAMETRO_NO_PERMITIDO"),
        ("CHOFER_CAMBIAR_ESTADO", {"chofer": RUT_ACTIVO, "activo": False, "comando": "del *"}, "PARAMETRO_NO_PERMITIDO"),
        ("DOCUMENTO_CORREGIR_CAMPO", {"numero_guia": "500001", "campo": "cliente", "valor": "X",
                                      "archivo": "../../catalogos_privados/choferes.json"}, "PARAMETRO_INVALIDO"),
        ("DOCUMENTO_CORREGIR_CAMPO", {"numero_guia": "500001", "campo": "cliente", "valor": "X",
                                      "archivo": "C:\\Windows\\system32"}, "PARAMETRO_INVALIDO"),
        ("DOCUMENTO_CORREGIR_CAMPO", {"numero_guia": "500001", "campo": "../dataset", "valor": "X"}, "PARAMETRO_INVALIDO"),
        ("OBRA_REGISTRAR", {"cliente_id": "x", "nombre_obra": "Y\x00; DROP TABLE"}, "PARAMETRO_INVALIDO"),
        ("CHOFER_CAMBIAR_ESTADO", ["chofer", RUT_ACTIVO], "PARAMETRO_INVALIDO"),
    ]
    for accion, parametros, codigo in casos:
        assert capa.previsualizar(accion, parametros, actor="B1", origen="B1")["codigo"] == codigo, (accion, parametros)
    assert capa.previsualizar("CHOFER_CONSULTAR", {}, actor="../x", origen="B1")["codigo"] == "PARAMETRO_INVALIDO"
    assert {p.name: _sha(p) for p in entorno["cat"].iterdir()} == antes
    assert not (entorno["actual"] / "acciones_operacionales.json").exists()


def test_sensible_fuera_de_autonomia_b1(entorno):
    capa = CapaAccionesOperacionales(entorno["raiz"])
    p = capa.previsualizar("TRANSPORTE_REVALIDAR", {"numero_transporte": "0000900001"}, actor="B1", origen="B1")
    assert p["estado"] == "PREVIEW" and p["riesgo"] == SENSIBLE and p["autonomia_b1"] == "FUERA_DE_AUTONOMIA_B1"
    assert capa.ejecutar(p["token"], actor="B1", origen="B1", confirmado_por="JAVIER",
                         autorizacion_sensible=True)["codigo"] == "FUERA_DE_AUTONOMIA"
    assert capa.ejecutar(p["token"], actor="JAVIER", confirmado_por="JAVIER")["codigo"] == "FUERA_DE_AUTONOMIA"
    assert capa.auditoria() == []


def test_catalogo_de_acciones_y_clasificacion(entorno):
    catalogo = {a["accion"]: a for a in catalogo_acciones()}
    assert set(catalogo) == set(ACCIONES)
    riesgos = {a["riesgo"] for a in catalogo.values()}
    assert riesgos == {LECTURA, OPERACIONAL_REVERSIBLE, SENSIBLE, DESTRUCTIVA}
    assert catalogo["CHOFER_CONSULTAR"]["autonomia_b1"] == "AUTOMATICA"
    assert catalogo["CHOFER_CAMBIAR_ESTADO"]["autonomia_b1"] == "CONFIRMACION_HUMANA"
    assert catalogo["ENTIDAD_ELIMINAR"]["autonomia_b1"] == "PROHIBIDA"
    assert "obra_destino" in [o.lower() for o in catalogo["DOCUMENTO_CORREGIR_CAMPO"]["parametros"]["campo"]["opciones"]]
    json.dumps(catalogo)  # contrato serializable para B1


def test_cli_catalogo_previsualizar_ejecutar(entorno, capsys):
    from acciones_operacionales_cli import main
    assert main(["catalogo"]) == 0
    assert "CHOFER_CAMBIAR_ESTADO" in capsys.readouterr().out
    main(["--raiz-atlas", str(entorno["raiz"]), "previsualizar", "--accion", "CHOFER_CAMBIAR_ESTADO",
          "--parametros", json.dumps({"chofer": RUT_ACTIVO, "activo": False}), "--actor", "JAVIER"])
    token = json.loads(capsys.readouterr().out)["token"]
    assert main(["--raiz-atlas", str(entorno["raiz"]), "ejecutar", "--token", token, "--actor", "JAVIER",
                 "--confirmado-por", "JAVIER"]) == 0
    assert json.loads(capsys.readouterr().out)["estado"] == "APLICADA"
    assert main(["--raiz-atlas", str(entorno["raiz"]), "previsualizar", "--accion", "SHELL", "--actor", "JAVIER"]) == 1


def test_asociacion_previa_con_rut_formateado_es_sin_cambios(entorno):
    # Caso real (copia de G:): TG8925 tenía el RUT asociado como "18091588-5";
    # la comparación cruda proponía duplicar la misma relación.
    from atlas_core.catalogo_vehiculos import asociar_chofer_a_vehiculo_confirmado
    asociar_chofer_a_vehiculo_confirmado(
        entorno["cat"] / "vehiculos.json", patente="KN5439", actor="TEST", fuente_decision="TEST",
        fecha=datetime(2026, 9, 1, tzinfo=timezone.utc), rut_chofer_asociado="12.345.678-5")
    capa = CapaAccionesOperacionales(entorno["raiz"])
    p = capa.previsualizar("CHOFER_ASIGNAR_VEHICULO", {"chofer": RUT_ACTIVO, "patente": "KN5439"}, actor="JAVIER")
    assert p["estado"] == "SIN_CAMBIOS", p


# ------------------------------------------------------------ numero_transporte (caso 480715)

T_ANTERIOR, T_NUEVO = "0000900001", "0000900002"
# Únicas columnas que una corrección de transporte puede tocar.
_DERIVADAS_TRANSPORTE = {"numero_transporte", "motivos_revision_documento", "indicador_revision",
                         "estado_documental", "estado_operacional"}


def _filas_dataset(entorno) -> dict[str, dict[str, str]]:
    with entorno["dataset"].open(encoding="utf-8-sig", newline="") as archivo:
        return {f["archivo"]: f for f in csv.DictReader(archivo, delimiter=";")}


def _escribir_dataset(entorno, filas) -> None:
    with entorno["dataset"].open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader()
        escritor.writerows(filas)


def _entorno_transporte(entorno, *extra):
    """500001 y 500002 en el viaje anterior; 500003 ya en el viaje destino.
    500001 trae poblados los campos no relacionados para verificar que
    ninguno cambia."""
    completa = _fila(
        "500001", fecha="2026-09-20", patente_rampla="JK1234", peso_kg="28000",
        descripcion_material="ARIDO", hora_entrada_aza="08:00", hora_salida_aza="08:40", planta_origen_id="P1",
        planta_origen_nombre="PLANTA UNO", origen_gps="GPS", planta_gps_nombre="PLANTA UNO",
        hora_entrada_gps="07:58", distancia_gps_km="31.2", evidencia_telemetria='{"x":1}', distancia_km="30.5",
        duracion_min="45", motivo_ruta="OK", metricas_procesamiento_json='{"ms":10}', rut_cliente="76.111.111-6",
        direccion_entrega="CALLE DOS 200", localidad_entrega="SANTIAGO",
        motivos_revision_documento="TRANSPORTE_AUSENTE_SIN_ETIQUETA | OBRA_DESTINO_SIN_CORROBORAR",
    )
    _escribir_dataset(entorno, [completa, _fila("500002", obra_destino="OBRA OTRA"),
                                _fila("500003", numero_transporte=T_NUEVO), *extra])
    otra = crear_decision(
        tipo="OBRA_DESCONOCIDA", entidad="OBRA", archivo="500002.jpeg", numero_guia="500002",
        numero_transporte=T_ANTERIOR, campo="obra_destino", valor_documental="OBRA OTRA",
        valor_normalizado="OBRA OTRA", identidad_resuelta=None, candidatos=(),
        motivos=("OBRA_NO_EXISTE_PARA_CLIENTE",),
        evidencias=({"tipo": "CLIENTE_RESUELTO", "entidad_id": entorno["cliente"].cliente_id},),
        acciones_permitidas=("REGISTRAR", "NO_REGISTRAR", "POSPONER"),
        contexto={"cliente_id": entorno["cliente"].cliente_id, "cliente_canonico": entorno["cliente"].razon_social,
                  "destino_documental": ""},
    )
    generar_artefacto(ruta_dataset=entorno["dataset"], carpeta_catalogos=entorno["cat"],
                      decisiones=[entorno["decision"], otra])
    return otra


def _preview_transporte(capa, valor=T_NUEVO, **extra):
    return capa.previsualizar("DOCUMENTO_CORREGIR_CAMPO",
                              {"numero_guia": "500001", "campo": "numero_transporte", "valor": valor, **extra},
                              actor="JAVIER")


def _sin_mantenimiento_real(monkeypatch, forzadas: list | None = None):
    import atlas_core.mantenimiento_pendientes_tecnicos as mantenimiento

    def registrar(**kw):
        if forzadas is not None:
            forzadas.append(set(kw["guias_forzadas"]))
        return {"ejecutado": True}
    monkeypatch.setattr(mantenimiento, "mantener_pendientes_tecnicos", registrar)


def test_corregir_transporte_aplica_preserva_y_retira_tarjeta_dependiente(entorno, monkeypatch):
    otra = _entorno_transporte(entorno)
    antes = _filas_dataset(entorno)
    forzadas: list[set[str]] = []
    _sin_mantenimiento_real(monkeypatch, forzadas)
    capa = CapaAccionesOperacionales(entorno["raiz"])
    vieja = entorno["decision"]["decision_id"]

    p = _preview_transporte(capa)
    assert p["estado"] == "PREVIEW", p
    assert p["valor_actual"] == {"numero_transporte": T_ANTERIOR}
    assert p["valor_propuesto"] == {"numero_transporte": T_NUEVO}
    af = p["afectados"]
    assert (af["transporte_anterior"], af["transporte_nuevo"]) == (T_ANTERIOR, T_NUEVO)
    assert af["guias"] == ["500001"] and af["archivo"] == "500001.jpeg"
    assert af["viaje_origen"] == {"numero_transporte": T_ANTERIOR, "guias_restantes": ["500002"]}
    assert af["viaje_destino"] == {"numero_transporte": T_NUEVO, "guias_existentes": ["500003"],
                                   "guias_resultantes": ["500001", "500003"]}
    assert af["guias_revalidar"] == ["500001", "500003"]
    assert [d["decision_id"] for d in af["decisiones_obsoletas"]] == [vieja]

    r = capa.ejecutar(p["token"], actor="JAVIER", confirmado_por="JAVIER")
    assert r["estado"] == "APLICADA", r
    despues = _filas_dataset(entorno)
    assert despues["500001.jpeg"]["numero_transporte"] == T_NUEVO
    # sólo el transporte y sus indicadores derivados; el motivo de otro campo se conserva
    assert despues["500001.jpeg"]["motivos_revision_documento"] == "OBRA_DESTINO_SIN_CORROBORAR"
    for columna in set(COLUMNAS) - _DERIVADAS_TRANSPORTE:
        assert despues["500001.jpeg"][columna] == antes["500001.jpeg"][columna], columna
    assert despues["500002.jpeg"] == antes["500002.jpeg"] and despues["500003.jpeg"] == antes["500003.jpeg"]

    # revalidación focal: guía corregida + guías del viaje destino
    assert forzadas == [{"500001", "500003"}]
    # la tarjeta del archivo ligada al transporte anterior se retira; la de otro archivo, no
    bandeja = _bandeja(entorno)["decisiones"]
    ids = {d["decision_id"] for d in bandeja}
    assert vieja not in ids and otra["decision_id"] in ids
    assert r["retiradas_por_red_de_seguridad"] == [vieja]
    assert all(d["documento"]["numero_transporte"] != T_ANTERIOR
               for d in bandeja if d["documento"]["archivo"] == "500001.jpeg")

    ledger = json.loads((entorno["actual"] / "decisiones_aplicadas.json").read_text(encoding="utf-8"))
    [entrada] = [a for a in ledger["aplicaciones"] if a["tipo"] == TIPO_LEDGER_CORRECCION]
    assert entrada["campo"] == "numero_transporte"
    assert (entrada["valor_documental"], entrada["valor_corregido"]) == (T_ANTERIOR, T_NUEVO)
    assert entrada["documento"] == {"archivo": "500001.jpeg", "numero_guia": "500001",
                                    "numero_transporte": T_ANTERIOR}
    auditoria = capa.auditoria()[-1]
    assert auditoria["antes"] == {"numero_transporte": T_ANTERIOR}
    assert auditoria["despues"] == {"numero_transporte": T_NUEVO}


def test_corregir_transporte_replay_e_idempotencia_del_ledger(entorno, monkeypatch):
    from atlas_core.reprocesamiento_reparador import _reparar_campos_documento
    _entorno_transporte(entorno)
    _sin_mantenimiento_real(monkeypatch)
    capa = CapaAccionesOperacionales(entorno["raiz"])
    p = _preview_transporte(capa)
    primera = capa.ejecutar(p["token"], actor="JAVIER", confirmado_por="JAVIER")
    assert primera["estado"] == "APLICADA", primera
    huella = _sha(entorno["dataset"])
    repetida = capa.ejecutar(p["token"], actor="JAVIER", confirmado_por="JAVIER")
    assert repetida["idempotente"] is True and repetida["auditoria_id"] == primera["auditoria_id"]
    assert _preview_transporte(capa)["estado"] == "SIN_CAMBIOS"
    assert _sha(entorno["dataset"]) == huella
    aplicaciones = json.loads((entorno["actual"] / "decisiones_aplicadas.json").read_text(
        encoding="utf-8"))["aplicaciones"]
    assert len([a for a in aplicaciones if a["tipo"] == TIPO_LEDGER_CORRECCION]) == 1
    # replay de reproceso/OCR: aun con el documento degradado y el OCR
    # leyendo el transporte anterior, el ledger gana
    fila = _filas_dataset(entorno)["500001.jpeg"]
    cambios = _reparar_campos_documento(fila, {"numero_transporte": T_ANTERIOR}, aplicaciones,
                                        documento_degradado=True)
    assert [c for c in cambios if c.campo == "numero_transporte"] == []


def test_corregir_transporte_duplicado_guia_transporte_bloquea(entorno):
    from atlas_core.reprocesamiento_reparador import reparar_documento_focal_con_valores_conocidos
    _entorno_transporte(entorno, _fila("500001", archivo="500001_b.jpeg", numero_transporte=T_NUEVO))
    huella = _sha(entorno["dataset"])
    r = _preview_transporte(CapaAccionesOperacionales(entorno["raiz"]), archivo="500001.jpeg")
    assert r["codigo"] == "PRECONDICION_FALLIDA" and "500001_b.jpeg" in r["mensaje"], r
    directo = reparar_documento_focal_con_valores_conocidos(
        raiz_atlas=entorno["raiz"], archivo="500001.jpeg", valores={"numero_transporte": T_NUEVO}, dry_run=False,
        reconciliar=False,
    )
    assert directo["cambios"] == [] and directo["duplicados_guia_transporte"] == ["500001_b.jpeg"]
    assert _sha(entorno["dataset"]) == huella


def test_corregir_transporte_eventos_activos_bloquean(entorno):
    _entorno_transporte(entorno)
    ruta = entorno["actual"] / "eventos_operacionales.json"
    ruta.write_text(json.dumps({"eventos": [
        {"numero_transporte": T_ANTERIOR, "tipo_evento": "TIENE_ESTADIA", "estado": "ANULADO"}]}), encoding="utf-8")
    capa = CapaAccionesOperacionales(entorno["raiz"])
    assert _preview_transporte(capa)["estado"] == "PREVIEW"  # un evento anulado no bloquea
    ruta.write_text(json.dumps({"eventos": [
        {"numero_transporte": T_ANTERIOR, "tipo_evento": "TIENE_ESTADIA", "estado": "ACTIVO"}]}), encoding="utf-8")
    huella = _sha(entorno["dataset"])
    r = _preview_transporte(capa)
    assert r["codigo"] == "PRECONDICION_FALLIDA" and "evento" in r["mensaje"], r
    assert _sha(entorno["dataset"]) == huella


def test_corregir_transporte_agrupacion_activa_bloquea(entorno):
    from atlas_core.agrupacion_viajes import SCHEMA_VERSION as SCHEMA_AGRUPACION
    _entorno_transporte(entorno)
    (entorno["actual"] / "agrupaciones_viaje.json").write_text(json.dumps({
        "schema_version": SCHEMA_AGRUPACION,
        "agrupaciones": [{"agrupacion_id": "g1", "estado": "ACTIVA", "transportes": [T_ANTERIOR, "0000900009"]}],
    }), encoding="utf-8")
    huella = _sha(entorno["dataset"])
    r = _preview_transporte(CapaAccionesOperacionales(entorno["raiz"]))
    assert r["codigo"] == "PRECONDICION_FALLIDA" and "agrupación" in r["mensaje"], r
    assert _sha(entorno["dataset"]) == huella


def test_corregir_transporte_eventos_activos_del_transporte_nuevo_bloquean(entorno):
    _entorno_transporte(entorno)
    (entorno["actual"] / "eventos_operacionales.json").write_text(json.dumps({"eventos": [
        {"numero_transporte": T_NUEVO, "tipo_evento": "TIENE_ESTADIA", "estado": "ACTIVO"}]}), encoding="utf-8")
    huella = _sha(entorno["dataset"])
    r = _preview_transporte(CapaAccionesOperacionales(entorno["raiz"]))
    assert r["codigo"] == "PRECONDICION_FALLIDA" and T_NUEVO in r["mensaje"] and "evento" in r["mensaje"], r
    assert _sha(entorno["dataset"]) == huella


def test_corregir_transporte_agrupacion_activa_del_transporte_nuevo_bloquea(entorno):
    from atlas_core.agrupacion_viajes import SCHEMA_VERSION as SCHEMA_AGRUPACION
    _entorno_transporte(entorno)
    (entorno["actual"] / "agrupaciones_viaje.json").write_text(json.dumps({
        "schema_version": SCHEMA_AGRUPACION,
        "agrupaciones": [{"agrupacion_id": "g2", "estado": "ACTIVA", "transportes": [T_NUEVO, "0000900009"]}],
    }), encoding="utf-8")
    huella = _sha(entorno["dataset"])
    r = _preview_transporte(CapaAccionesOperacionales(entorno["raiz"]))
    assert r["codigo"] == "PRECONDICION_FALLIDA" and T_NUEVO in r["mensaje"] and "agrupación" in r["mensaje"], r
    assert _sha(entorno["dataset"]) == huella


@pytest.mark.parametrize("valor", ["000090002", "00009000021", "00009A0002", "0000 900002"])
def test_corregir_transporte_exige_exactamente_diez_digitos(entorno, valor):
    _entorno_transporte(entorno)
    r = _preview_transporte(CapaAccionesOperacionales(entorno["raiz"]), valor=valor)
    assert r["codigo"] == "PARAMETRO_INVALIDO", r


def test_corregir_transporte_preview_obsoleto_si_cambia_el_viaje_destino(entorno):
    _entorno_transporte(entorno)
    capa = CapaAccionesOperacionales(entorno["raiz"])
    p = _preview_transporte(capa)
    filas = list(_filas_dataset(entorno).values())
    _escribir_dataset(entorno, [*filas, _fila("500004", numero_transporte=T_NUEVO)])  # otra guía entra al destino
    r = capa.ejecutar(p["token"], actor="JAVIER", confirmado_por="JAVIER")
    assert r["estado"] == "PREVIEW_OBSOLETO", r
    assert _filas_dataset(entorno)["500001.jpeg"]["numero_transporte"] == T_ANTERIOR
    assert r["preview_nuevo"]["afectados"]["viaje_destino"]["guias_existentes"] == ["500003", "500004"]


def _sin_reporte_real(monkeypatch, llamadas: list):
    monkeypatch.setattr(CapaAccionesOperacionales, "_regenerar_reporte",
                        lambda self: llamadas.append("reporte") or {"ok": True})


def test_corregir_numero_guia_nueve_absorbido_es_focal_y_auditable(entorno, monkeypatch):
    """Caso real 9482179 -> 482179: sólo cambia el folio, deja la lectura OCR
    en el ledger y no reconcilia la bandeja."""
    _escribir_dataset(entorno, [_fila("9482179", archivo="482179.jpeg", numero_transporte="No encontrado",
                                      motivos_revision_documento="TRANSPORTE_AUSENTE", indicador_revision="REVISAR",
                                      estado_documental="REQUIERE_REVISION", estado_operacional="REQUIERE_REVISION"),
                                _fila("500002")])
    bandeja_antes = _sha(entorno["actual"] / "decisiones_pendientes.json")
    antes = _filas_dataset(entorno)
    forzadas: list[set[str]] = []
    reportes: list[str] = []
    _sin_mantenimiento_real(monkeypatch, forzadas)
    _sin_reporte_real(monkeypatch, reportes)
    capa = CapaAccionesOperacionales(entorno["raiz"])

    preview = capa.previsualizar("DOCUMENTO_CORREGIR_NUMERO_GUIA",
                                 {"numero_guia": "9482179", "numero_guia_corregido": "482179"}, actor="JAVIER")
    assert preview["estado"] == "PREVIEW", preview
    assert (preview["valor_actual"], preview["valor_propuesto"]) == ({"numero_guia": "9482179"}, {"numero_guia": "482179"})

    resultado = capa.ejecutar(preview["token"], actor="JAVIER", confirmado_por="JAVIER")
    assert resultado["estado"] == "APLICADA", resultado
    filas = _filas_dataset(entorno)
    fila = filas["482179.jpeg"]
    assert fila["numero_guia"] == "482179"
    assert {k: v for k, v in fila.items() if k != "numero_guia"} == {
        k: v for k, v in antes["482179.jpeg"].items() if k != "numero_guia"}  # ningún otro campo cambia
    assert filas["500002.jpeg"] == antes["500002.jpeg"]
    assert forzadas == [{"482179"}] and reportes == ["reporte"]
    assert resultado["reconciliacion"] is None
    assert _sha(entorno["actual"] / "decisiones_pendientes.json") == bandeja_antes
    aplicaciones = json.loads((entorno["actual"] / "decisiones_aplicadas.json").read_text(encoding="utf-8"))["aplicaciones"]
    assert [(a["accion"], a["campo"], a["valor_documental"], a["valor_corregido"], a["documento"]["numero_guia"])
            for a in aplicaciones if a["tipo"] == "CORRECCION_DOCUMENTAL_OPERADOR"] == [
        ("CORREGIR_NUMERO_GUIA", "numero_guia", "9482179", "482179", "482179")]


def test_corregir_numero_guia_rechaza_folio_ajeno_patron_distinto_o_tarjetas(entorno):
    _escribir_dataset(entorno, [_fila("9482179", archivo="482179.jpeg"), _fila("482180"), _fila("500001")])
    capa = CapaAccionesOperacionales(entorno["raiz"])

    def preview(actual, nuevo):
        return capa.previsualizar("DOCUMENTO_CORREGIR_NUMERO_GUIA",
                                  {"numero_guia": actual, "numero_guia_corregido": nuevo}, actor="JAVIER")

    assert preview("9482179", "482180")["codigo"] == "PRECONDICION_FALLIDA"  # no es "9" + folio
    assert preview("500001", "500002")["codigo"] == "PRECONDICION_FALLIDA"   # folio sin 9 absorbido
    assert preview("9482179", "48217")["codigo"] == "PARAMETRO_INVALIDO"
    _escribir_dataset(entorno, [_fila("9482180", archivo="otro.jpeg"), _fila("482180")])
    duplicado = preview("9482180", "482180")
    assert duplicado["codigo"] == "PRECONDICION_FALLIDA" and "otro documento" in duplicado["mensaje"]
    # 500001 tiene una tarjeta pendiente en la bandeja del entorno
    _escribir_dataset(entorno, [_fila("9500001", archivo="x.jpeg")])
    bandeja = json.loads((entorno["actual"] / "decisiones_pendientes.json").read_text(encoding="utf-8"))
    bandeja["decisiones"][0]["documento"]["numero_guia"] = "9500001"
    (entorno["actual"] / "decisiones_pendientes.json").write_text(json.dumps(bandeja), encoding="utf-8")
    assert "tarjetas pendientes" in preview("9500001", "500001")["mensaje"]


def test_reparador_no_habilita_numero_guia_sin_la_accion_tipada(entorno):
    from atlas_core.reprocesamiento_reparador import reparar_documento_focal_con_valores_conocidos
    _escribir_dataset(entorno, [_fila("9482179", archivo="482179.jpeg")])
    resultado = reparar_documento_focal_con_valores_conocidos(
        raiz_atlas=entorno["raiz"], archivo="482179.jpeg", valores={"numero_guia": "482179"},
        dry_run=False, reconciliar=False)
    assert resultado["campos_ignorados_no_autorizados"] == ["numero_guia"]
    assert _filas_dataset(entorno)["482179.jpeg"]["numero_guia"] == "9482179"


def test_corregir_numero_guia_ausente_es_focal_y_auditable(entorno, monkeypatch):
    """Casos reales 482352/482350 (Mobile): folio "No encontrado" leído de la
    foto; sólo cambia el folio y sus estados, la lectura queda en el ledger."""
    ausente = dict(numero_guia="No encontrado", numero_transporte="0000364476",
                   motivos_revision_documento="GUIA_AUSENTE", indicador_revision="REVISAR",
                   estado_documental="REQUIERE_REVISION", estado_operacional="REQUIERE_REVISION")
    _escribir_dataset(entorno, [_fila("x", archivo="mobile/bd45/original.jpg", **ausente),
                                _fila("y", archivo="mobile/otro/original.jpg",
                                      **{**ausente, "numero_transporte": "0000364455"})])
    antes = _filas_dataset(entorno)
    bandeja_antes = _sha(entorno["actual"] / "decisiones_pendientes.json")
    forzadas: list[set[str]] = []
    reportes: list[str] = []
    _sin_mantenimiento_real(monkeypatch, forzadas)
    _sin_reporte_real(monkeypatch, reportes)
    capa = CapaAccionesOperacionales(entorno["raiz"])

    sin_archivo = capa.previsualizar("DOCUMENTO_CORREGIR_NUMERO_GUIA",
                                     {"numero_guia": "No encontrado", "numero_guia_corregido": "482350"},
                                     actor="JAVIER")
    assert sin_archivo["codigo"] == "PARAMETRO_INVALIDO"
    preview = capa.previsualizar("DOCUMENTO_CORREGIR_NUMERO_GUIA",
                                 {"numero_guia": "No encontrado", "numero_guia_corregido": "482350",
                                  "archivo": "mobile/bd45/original.jpg"}, actor="JAVIER")
    assert preview["estado"] == "PREVIEW", preview
    resultado = capa.ejecutar(preview["token"], actor="JAVIER", confirmado_por="JAVIER")
    assert resultado["estado"] == "APLICADA", resultado

    filas = _filas_dataset(entorno)
    fila = filas["mobile/bd45/original.jpg"]
    assert (fila["numero_guia"], fila["motivos_revision_documento"], fila["estado_documental"]) == ("482350", "", "OK")
    derivados = {"numero_guia", "motivos_revision_documento", "indicador_revision", "estado_documental",
                 "estado_operacional"}
    assert {k: v for k, v in fila.items() if k not in derivados} == {
        k: v for k, v in antes["mobile/bd45/original.jpg"].items() if k not in derivados}
    assert filas["mobile/otro/original.jpg"] == antes["mobile/otro/original.jpg"]
    assert forzadas == [{"482350"}] and reportes == ["reporte"] and resultado["reconciliacion"] is None
    assert _sha(entorno["actual"] / "decisiones_pendientes.json") == bandeja_antes
    aplicaciones = json.loads((entorno["actual"] / "decisiones_aplicadas.json").read_text(encoding="utf-8"))["aplicaciones"]
    assert [(a["accion"], a["valor_documental"], a["valor_corregido"]) for a in aplicaciones
            if a["tipo"] == "CORRECCION_DOCUMENTAL_OPERADOR"] == [("CORREGIR_NUMERO_GUIA", "No encontrado", "482350")]


def test_corregir_numero_guia_ausente_rechaza_duplicado_y_tarjetas_del_mismo_documento(entorno):
    ausente = dict(numero_guia="No encontrado", numero_transporte="0000364476")
    _escribir_dataset(entorno, [_fila("x", archivo="mobile/bd45/original.jpg", **ausente), _fila("482350")])
    capa = CapaAccionesOperacionales(entorno["raiz"])

    def preview(nuevo):
        return capa.previsualizar("DOCUMENTO_CORREGIR_NUMERO_GUIA",
                                  {"numero_guia": "No encontrado", "numero_guia_corregido": nuevo,
                                   "archivo": "mobile/bd45/original.jpg"}, actor="JAVIER")

    assert "otro documento" in preview("482350")["mensaje"]
    bandeja = json.loads((entorno["actual"] / "decisiones_pendientes.json").read_text(encoding="utf-8"))
    tarjeta = bandeja["decisiones"][0]
    tarjeta["documento"].update({"numero_guia": "No encontrado", "numero_transporte": "0000999999"})
    (entorno["actual"] / "decisiones_pendientes.json").write_text(json.dumps(bandeja), encoding="utf-8")
    assert preview("482351")["estado"] == "PREVIEW"  # tarjeta de OTRO documento sin folio: no bloquea
    tarjeta["documento"]["numero_transporte"] = "0000364476"
    (entorno["actual"] / "decisiones_pendientes.json").write_text(json.dumps(bandeja), encoding="utf-8")
    assert "tarjetas pendientes" in preview("482351")["mensaje"]
