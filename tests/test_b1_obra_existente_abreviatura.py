"""B1: obra EXISTENTE escrita con otra abreviatura (caso real 492040).

Guía 492040, cliente SODIMAC SA. El OCR leyó «1SODIMAC SA RZNCA BOD 121» y la
tarjeta es OBRA_DESCONOCIDA. Javier escribe «la obra es SODIMAC SA RENCA
BODEGA 721»; el catálogo la tiene como «SODIMAC SA RENCA BOD 721». Antes B1
exigía coincidencia exacta, respondía que la obra no existía y ofrecía
registrarla (un duplicado). Ahora la reconoce entre las obras del cliente de la
guía, sin crear nada y sin confundirla con BOD 209 ni con obras de otro
cliente. Copias sintéticas; nunca G:."""
from __future__ import annotations

import csv
import hashlib
import json
from types import SimpleNamespace

import pytest

from atlas_core.acciones_operacionales import CapaAccionesOperacionales
from atlas_core.b1_operador import OperadorB1, obra_equivale_por_abreviatura, resolver_obra
from atlas_core.catalogo_clientes import CatalogoClientes, EstadoCalidadCliente
from atlas_core.catalogo_obras_destinos import CatalogoObrasDestinos, Evidencia, TipoEvidencia
from atlas_core.decisiones_pendientes import crear_decision, generar_artefacto
from atlas_core.procesamiento_masivo import COLUMNAS
from tests.test_acciones_operacionales import _fila, entorno  # noqa: F401 -- fixture compartida

GUIA, ARCHIVO, OCR = "492040", "492040.jpeg", "1SODIMAC SA RZNCA BOD 121"
SODIMAC, OTRO = "SODIMAC SA", "CONSTRUCTORA OTRA SA"
BOD_721, BOD_209 = "SODIMAC SA RENCA BOD 721", "SODIMAC SA RENCA BOD 209"
DEL_OTRO = "SODIMAC SA RENCA BOD 500"  # mismo texto base, pero registrada para OTRO cliente


def _sha(ruta):
    return hashlib.sha256(ruta.read_bytes()).hexdigest() if ruta.exists() else None


def _huellas(entorno):
    return {n: _sha(p) for n, p in {
        "dataset": entorno["dataset"], "obras": entorno["cat"] / "obras_destinos.json",
        "clientes": entorno["cat"] / "clientes.json",
        "ledger": entorno["actual"] / "decisiones_aplicadas.json"}.items()}


def _filas(entorno):
    with entorno["dataset"].open(encoding="utf-8-sig", newline="") as archivo:
        return {f["archivo"]: f for f in csv.DictReader(archivo, delimiter=";")}


def _obras(entorno):
    return json.loads((entorno["cat"] / "obras_destinos.json").read_text(encoding="utf-8"))["obras"]


def _en(decision_id, texto):
    return f"@revision:{decision_id} {texto}"


def _evidencia(ident):
    return Evidencia(tipo=TipoEvidencia.GUIA.value, identificador_fuente=ident, referencia_hash="a" * 64,
                     campos_observados={"obra": "X"}, fecha="2026-01-01T00:00:00+00:00",
                     actor_proceso="test", resultado="SOPORTA")


@pytest.fixture
def caso(entorno):  # noqa: F811
    clientes = CatalogoClientes(entorno["cat"] / "clientes.json")
    sodimac = clientes.crear(razon_social=SODIMAC, rut="96.792.430-K", fuente="TEST",
                             estado_calidad=EstadoCalidadCliente.CONFIRMADO)
    otro = clientes.crear(razon_social=OTRO, rut="76.222.222-1", fuente="TEST",
                          estado_calidad=EstadoCalidadCliente.CONFIRMADO)
    catalogo = CatalogoObrasDestinos(entorno["cat"] / "obras_destinos.json", ruta_clientes=entorno["cat"] / "clientes.json",
                                     ruta_destinos=entorno["cat"] / "destinos_maestros.json")
    ids = {}
    for nombre, cliente in ((BOD_721, sodimac), (BOD_209, sodimac), (DEL_OTRO, otro)):
        ids[nombre] = catalogo.registrar_observacion(cliente_id=cliente.cliente_id, nombre_obra=nombre,
                                                     evidencia=_evidencia(nombre)).obra.obra_id
    filas = [_fila(GUIA, archivo=ARCHIVO, numero_transporte="0060372254", cliente=SODIMAC, obra_destino=OCR),
             _fila("500002", obra_destino="OBRA OTRA")]
    with entorno["dataset"].open("w", encoding="utf-8-sig", newline="") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader()
        escritor.writerows(filas)
    tarjeta = crear_decision(
        tipo="OBRA_DESCONOCIDA", entidad="OBRA", archivo=ARCHIVO, numero_guia=GUIA, numero_transporte="0060372254",
        campo="obra_destino", valor_documental=OCR, valor_normalizado=OCR, identidad_resuelta=None, candidatos=(),
        motivos=("OBRA_NO_EXISTE_PARA_CLIENTE",), evidencias=(),
        acciones_permitidas=("REGISTRAR", "NO_REGISTRAR", "POSPONER"))
    generar_artefacto(ruta_dataset=entorno["dataset"], carpeta_catalogos=entorno["cat"], decisiones=[tarjeta])
    capa = CapaAccionesOperacionales(entorno["raiz"])
    capa._revalidar_guias = lambda guias: {"ejecutado": True}
    entorno.update(b1=OperadorB1(entorno["raiz"], capa=capa), tarjeta=tarjeta["decision_id"], ids=ids,
                   sodimac=sodimac.cliente_id, otro=otro.cliente_id)
    return entorno


def test_492040_reconoce_la_obra_existente_y_corrige_sin_crear_ni_duplicar(caso):
    b1, tarjeta = caso["b1"], caso["tarjeta"]
    antes = _huellas(caso)
    r = b1.atender("t", _en(tarjeta, "la obra es SODIMAC SA RENCA BODEGA 721"))
    assert r["estado"] == "PREVIEW_PENDIENTE", r
    assert r["accion"] == "DOCUMENTO_ASIGNAR_OBRA"
    assert "registro_ofrecido" not in r and "no está registrada" not in r["mensaje"]
    assert r["preview"]["valor_actual"] == {"obra_destino": OCR}
    assert r["preview"]["valor_propuesto"] == {"obra_destino": BOD_721, "obra_id": caso["ids"][BOD_721]}
    assert _huellas(caso) == antes  # la vista previa no escribe

    hecha = b1.atender("t", _en(tarjeta, "sí"))
    assert hecha["estado"] == "EJECUTADA", hecha
    assert _filas(caso)[ARCHIVO]["obra_destino"] == BOD_721
    assert _filas(caso)["500002.jpeg"]["obra_destino"] == "OBRA OTRA"
    assert sorted(o["nombre_canonico"] for o in _obras(caso)) == sorted([BOD_721, BOD_209, DEL_OTRO])
    assert [a["accion"] for a in b1.capa.auditoria()] == ["DOCUMENTO_ASIGNAR_OBRA"]
    assert _sha(caso["cat"] / "clientes.json") == antes["clientes"]


def test_el_numero_distingue_obras_bod_209_no_es_bod_721(caso):
    r = caso["b1"].atender("t", _en(caso["tarjeta"], "la obra es SODIMAC SA RENCA BODEGA 209"))
    assert r["estado"] == "PREVIEW_PENDIENTE", r
    assert r["preview"]["valor_propuesto"]["obra_id"] == caso["ids"][BOD_209]


def test_numero_inexistente_sigue_siendo_obra_desconocida(caso):
    antes = _huellas(caso)
    r = caso["b1"].atender("t", _en(caso["tarjeta"], "la obra es SODIMAC SA RENCA BODEGA 999"))
    assert r["estado"] == "ACLARACION_REQUERIDA", r
    assert "no está registrada en el catálogo de obras" in r["mensaje"]
    assert _huellas(caso) == antes and caso["b1"].capa.auditoria() == []


def test_no_asocia_obra_de_otro_cliente_por_abreviatura(caso):
    antes = _huellas(caso)
    r = caso["b1"].atender("t", _en(caso["tarjeta"], "la obra es SODIMAC SA RENCA BODEGA 500"))
    assert r["estado"] == "ACLARACION_REQUERIDA", r
    assert caso["ids"][DEL_OTRO] not in json.dumps(r.get("preview") or {})
    assert _huellas(caso) == antes and caso["b1"].capa.auditoria() == []


def test_letras_cambiadas_no_se_toleran(caso):
    r = caso["b1"].atender("t", _en(caso["tarjeta"], "la obra es SODIMAC SA RZNCA BODEGA 721"))
    assert r["estado"] == "ACLARACION_REQUERIDA", r


def test_registrar_la_misma_obra_abreviada_distinto_es_rechazado_sin_crear(caso):
    b1 = caso["b1"]
    antes = _huellas(caso)
    r = b1.atender("x", "registra la obra SODIMAC SA RENCA BODEGA 721 para el cliente SODIMAC SA")
    assert r["estado"] == "ACLARACION_REQUERIDA", r
    assert BOD_721 in r["mensaje"] and "No se crea otra obra" in r["mensaje"]
    assert b1.pendiente("x") is None
    assert b1.atender("x", "sí")["estado"] == "SIN_PREVIEW_PENDIENTE"
    assert _huellas(caso) == antes and len(_obras(caso)) == 3


def test_registrar_obra_realmente_nueva_sigue_ofreciendo_vista_previa(caso):
    r = caso["b1"].atender("x", "registra la obra SODIMAC SA RENCA BODEGA 999 para el cliente SODIMAC SA")
    assert r["estado"] == "PREVIEW_PENDIENTE", r
    assert r["accion"] == "OBRA_REGISTRAR"


@pytest.mark.parametrize("a,b,esperado", [
    ("SODIMAC SA RENCA BODEGA 721", "SODIMAC SA RENCA BOD 721", True),
    ("SODIMAC SA RENCA BOD. 721", "SODIMAC S.A. RENCA BODEGA 721", True),
    ("EDIF CENTRAL TORRE 2", "EDIFICIO CENTRAL TORRE 2", True),
    ("SODIMAC SA RENCA BODEGA 721", "SODIMAC SA RENCA BOD 209", False),   # número distinto
    ("SODIMAC SA RENCA BODEGA 721", "SODIMAC SA RENCA BOD 7210", False),  # números nunca se abrevian
    ("SODIMAC SA RZNCA BODEGA 721", "SODIMAC SA RENCA BOD 721", False),   # letra cambiada
    ("SODIMAC SA BODEGA 721", "SODIMAC SA RENCA BOD 721", False),         # palabra faltante
    ("SODIMAC SA RENCA BO 721", "SODIMAC SA RENCA BODEGA 721", False),    # abreviatura < 3 letras
    ("SODIMAC SA RENCA BOD 721", "SODIMAC SA RENCA BOD 721", False),      # igual: lo resuelve la exacta
])
def test_equivalencia_por_abreviatura(a, b, esperado):
    assert obra_equivale_por_abreviatura(a, b) is esperado
    assert obra_equivale_por_abreviatura(b, a) is esperado


def _obra(obra_id, nombre, cliente_id="c1", aliases=()):
    return SimpleNamespace(obra_id=obra_id, nombre_canonico=nombre, aliases_documentales=tuple(aliases),
                           cliente_id=cliente_id, estado="CONFIRMADA", estado_vigencia="ACTIVO")


def test_resolver_obra_se_abstiene_ante_dos_equivalentes_del_mismo_cliente():
    obras = [_obra("a", "X BODEGA 1"), _obra("b", "X BODEGON 1")]
    r = resolver_obra(obras, "X BOD 1", "c1")
    assert r["estado"] == "AMBIGUO" and {c["obra_id"] for c in r["candidatos"]} == {"a", "b"}


def test_resolver_obra_sin_cliente_conserva_la_regla_exacta():
    obras = [_obra("a", "X BODEGA 1")]
    assert resolver_obra(obras, "X BOD 1")["estado"] == "DESCONOCIDO"
    assert resolver_obra(obras, "x bodega 1")["estado"] == "RESUELTO"


def test_resolver_obra_usa_alias_y_respeta_inactivas():
    obras = [_obra("a", "OTRO NOMBRE", aliases=("X BODEGA 1",)),
             SimpleNamespace(**{**vars(_obra("z", "X BODEGA 2")), "estado_vigencia": "INACTIVO"})]
    assert resolver_obra(obras, "X BOD 1", "c1")["obra_id"] == "a"
    assert resolver_obra(obras, "X BOD 2", "c1")["estado"] == "DESCONOCIDO"
