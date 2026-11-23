"""B1: corregir la OBRA de una guía cuando la obra pedida no existe en el
catálogo de OBRAS (caso 488504: OCR «ACEHOS AZA SA», cliente ACEROS AZA SA,
Javier pide «ACEROS AZA SA», que sólo existe como CLIENTE).

B1 no crea nada por sí mismo: ofrece el registro oficial (OBRA_REGISTRAR con
cliente explícito, vista previa y confirmación) y, si la persona lo pide en el
mensaje siguiente, encadena la corrección de la guía (DOCUMENTO_ASIGNAR_OBRA)
con su propia vista previa y confirmación. Copias sintéticas; nunca G:."""
from __future__ import annotations

import csv
import hashlib
import json

import pytest

from atlas_core.acciones_operacionales import CapaAccionesOperacionales, TIPO_LEDGER_CORRECCION
from atlas_core.b1_operador import OperadorB1
from atlas_core.catalogo_clientes import CatalogoClientes, EstadoCalidadCliente
from atlas_core.decisiones_pendientes import crear_decision, generar_artefacto
from atlas_core.procesamiento_masivo import COLUMNAS
from tests.test_acciones_operacionales import _fila, entorno  # noqa: F401 -- fixture compartida

GUIA, ARCHIVO, OCR, OBRA = "488504", "488504.jpeg", "ACEHOS AZA SA", "ACEROS AZA SA"


def _sha(ruta):
    return hashlib.sha256(ruta.read_bytes()).hexdigest() if ruta.exists() else None


def _huellas(entorno):
    return {n: _sha(p) for n, p in {
        "dataset": entorno["dataset"], "obras": entorno["cat"] / "obras_destinos.json",
        "clientes": entorno["cat"] / "clientes.json",
        "ledger": entorno["actual"] / "decisiones_aplicadas.json",
        "bandeja": entorno["actual"] / "decisiones_pendientes.json"}.items()}


def _filas(entorno):
    with entorno["dataset"].open(encoding="utf-8-sig", newline="") as archivo:
        return {f["archivo"]: f for f in csv.DictReader(archivo, delimiter=";")}


def _obras(entorno):
    return json.loads((entorno["cat"] / "obras_destinos.json").read_text(encoding="utf-8"))["obras"]


def _en(decision_id, texto):
    return f"@revision:{decision_id} {texto}"


@pytest.fixture
def caso(entorno):  # noqa: F811
    """488504 con su tarjeta OBRA_DESCONOCIDA y otra guía AZA cuyo texto de
    obra ya dice ACEROS AZA SA (como las 13 guías reales), sin obra en catálogo."""
    CatalogoClientes(entorno["cat"] / "clientes.json").crear(
        razon_social=OBRA, rut="92.176.000-0", fuente="TEST", estado_calidad=EstadoCalidadCliente.CONFIRMADO)
    filas = [_fila(GUIA, archivo=ARCHIVO, numero_transporte="0000371852", cliente=OBRA, obra_destino=OCR),
             _fila("488503", numero_transporte="0000371851", cliente=OBRA, obra_destino=OBRA),
             _fila("500002", obra_destino="OBRA OTRA")]
    with entorno["dataset"].open("w", encoding="utf-8-sig", newline="") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader()
        escritor.writerows(filas)
    tarjeta = crear_decision(
        tipo="OBRA_DESCONOCIDA", entidad="OBRA", archivo=ARCHIVO, numero_guia=GUIA, numero_transporte="0000371852",
        campo="obra_destino", valor_documental=OCR, valor_normalizado=OCR, identidad_resuelta=None, candidatos=(),
        motivos=("OBRA_NO_EXISTE_PARA_CLIENTE",), evidencias=(),
        acciones_permitidas=("REGISTRAR", "NO_REGISTRAR", "POSPONER"))
    generar_artefacto(ruta_dataset=entorno["dataset"], carpeta_catalogos=entorno["cat"], decisiones=[tarjeta])
    capa = CapaAccionesOperacionales(entorno["raiz"])
    revalidadas: list[set[str]] = []
    capa._revalidar_guias = lambda guias: revalidadas.append(set(guias)) or {"ejecutado": True}
    operador = OperadorB1(entorno["raiz"], capa=capa)
    entorno.update(b1=operador, tarjeta=tarjeta["decision_id"], revalidadas=revalidadas)
    return entorno


def test_reproduce_rechazo_y_distingue_cliente_de_obra_sin_escribir(caso):
    antes = _huellas(caso)
    r = caso["b1"].atender("t", _en(caso["tarjeta"], "la obra es ACEROS AZA SA"))
    assert r["estado"] == "ACLARACION_REQUERIDA", r
    assert "no está registrada en el catálogo de obras" in r["mensaje"]
    assert "sí existe como cliente" in r["mensaje"]
    assert "registra la obra ACEROS AZA SA para el cliente ACEROS AZA SA" in r["mensaje"]
    assert "No se corrigió ni se creó nada" in r["mensaje"]
    assert r["registro_ofrecido"] == {"obra": OBRA, "cliente": OBRA}
    assert caso["b1"].pendiente("t") is None
    assert caso["b1"].atender("t", _en(caso["tarjeta"], "sí"))["estado"] == "SIN_PREVIEW_PENDIENTE"
    assert _huellas(caso) == antes and caso["b1"].capa.auditoria() == []


def test_registro_ofrecido_y_correccion_encadenada_con_dos_confirmaciones(caso):
    b1, tarjeta = caso["b1"], caso["tarjeta"]
    antes = _huellas(caso)
    b1.atender("t", _en(tarjeta, "la obra es ACEROS AZA SA"))

    registro = b1.atender("t", _en(tarjeta, "registra la obra ACEROS AZA SA para el cliente ACEROS AZA SA"))
    assert registro["estado"] == "PREVIEW_PENDIENTE", registro
    assert registro["accion"] == "OBRA_REGISTRAR"
    assert registro["preview"]["valor_actual"] == {"nombre": "no existe"}
    assert registro["preview"]["valor_propuesto"] == {"nombre": OBRA, "cliente": OBRA}
    assert "corrección de la guía 488504" in registro["mensaje"]
    assert _huellas(caso) == antes

    creada = b1.atender("t", _en(tarjeta, "sí"))
    assert creada["aplicado_previo"] and creada["estado"] == "PREVIEW_PENDIENTE", creada
    assert creada["accion"] == "DOCUMENTO_ASIGNAR_OBRA"
    assert creada["preview"]["valor_actual"] == {"obra_destino": OCR}
    assert creada["preview"]["valor_propuesto"]["obra_destino"] == OBRA
    assert [o["nombre_canonico"] for o in _obras(caso)] == [OBRA]
    assert _filas(caso)[ARCHIVO]["obra_destino"] == OCR  # la guía aún no cambia

    hecha = b1.atender("t", _en(tarjeta, "sí"))
    assert hecha["estado"] == "EJECUTADA", hecha
    filas = _filas(caso)
    assert filas[ARCHIVO]["obra_destino"] == OBRA
    assert filas["488503.jpeg"]["obra_destino"] == OBRA and filas["500002.jpeg"]["obra_destino"] == "OBRA OTRA"
    assert [a["accion"] for a in b1.capa.auditoria()] == ["OBRA_REGISTRAR", "DOCUMENTO_ASIGNAR_OBRA"]
    assert all(a["confirmado_por"] == "JAVIER" for a in b1.capa.auditoria())
    ledger = json.loads((caso["actual"] / "decisiones_aplicadas.json").read_text(encoding="utf-8"))["aplicaciones"]
    # El OCR queda como valor documental: se corrige el dato operacional, no la lectura.
    assert [(a["campo"], a["valor_documental"], a["valor_corregido"]) for a in ledger
            if a["tipo"] == TIPO_LEDGER_CORRECCION] == [("obra_destino", OCR, OBRA)]
    assert tarjeta in hecha["resultado"]["decisiones_retiradas"]
    assert set().union(*caso["revalidadas"]) == {GUIA}  # sólo esta guía; las demás AZA no se tocan
    # El cliente no cambia y no se crean clientes.
    assert _sha(caso["cat"] / "clientes.json") == antes["clientes"]

    # Repetir no duplica nada.
    despues = _huellas(caso)
    assert b1.atender("t", "sí")["estado"] == "SIN_PREVIEW_PENDIENTE"
    assert b1.atender("t", f"La obra de la guía {GUIA} es ACEROS AZA SA")["estado"] == "SIN_CAMBIOS"
    assert _huellas(caso) == despues and len(_obras(caso)) == 1


def test_obra_existente_se_selecciona_sin_ofrecer_registro_ni_duplicar(caso):
    b1 = caso["b1"]
    b1.atender("x", "registra la obra ACEROS AZA SA para el cliente ACEROS AZA SA")
    assert b1.atender("x", "sí")["estado"] == "EJECUTADA"
    # Variante sólo de puntuación: se propone la existente, nunca un registro duplicado.
    casi = b1.atender("t", _en(caso["tarjeta"], "la obra es Aceros AZA S.A."))
    assert casi["estado"] == "ACLARACION_REQUERIDA" and "registro_ofrecido" not in casi
    assert [c["nombre"] for c in casi["candidatos"]] == [OBRA] and "equivale a: ACEROS AZA SA" in casi["mensaje"]
    assert b1.atender("t", _en(caso["tarjeta"], "registra la obra ACEROS AZA S.A para el cliente ACEROS AZA SA")
                      )["estado"] == "ACLARACION_REQUERIDA"
    r = b1.atender("t", _en(caso["tarjeta"], "la obra es Aceros Aza SA"))
    assert r["estado"] == "PREVIEW_PENDIENTE" and r["accion"] == "DOCUMENTO_ASIGNAR_OBRA", r
    assert b1.atender("t", _en(caso["tarjeta"], "sí"))["estado"] == "EJECUTADA"
    assert len(_obras(caso)) == 1 and _filas(caso)[ARCHIVO]["obra_destino"] == OBRA


def test_cancelar_el_registro_no_escribe_ni_deja_correccion_pendiente(caso):
    b1, tarjeta = caso["b1"], caso["tarjeta"]
    antes = _huellas(caso)
    b1.atender("t", _en(tarjeta, "la obra es ACEROS AZA SA"))
    assert b1.atender("t", _en(tarjeta, "registra la obra ACEROS AZA SA para el cliente ACEROS AZA SA")
                      )["estado"] == "PREVIEW_PENDIENTE"
    assert b1.atender("t", _en(tarjeta, "no"))["estado"] == "CANCELADA"
    assert b1.atender("t", _en(tarjeta, "sí"))["estado"] == "SIN_PREVIEW_PENDIENTE"
    assert _huellas(caso) == antes and b1.capa.auditoria() == []


def test_rechazar_la_correccion_deja_solo_la_obra_registrada(caso):
    b1, tarjeta = caso["b1"], caso["tarjeta"]
    b1.atender("t", _en(tarjeta, "la obra es ACEROS AZA SA"))
    b1.atender("t", _en(tarjeta, "registra la obra ACEROS AZA SA para el cliente ACEROS AZA SA"))
    assert b1.atender("t", _en(tarjeta, "sí"))["estado"] == "PREVIEW_PENDIENTE"
    assert b1.atender("t", _en(tarjeta, "no"))["estado"] == "CANCELADA"
    assert _filas(caso)[ARCHIVO]["obra_destino"] == OCR
    assert [a["accion"] for a in b1.capa.auditoria()] == ["OBRA_REGISTRAR"]


@pytest.mark.parametrize("intermedio", [None, "¿qué choferes están activos?"])
def test_registro_sin_oferta_inmediata_sigue_las_reglas_de_la_tarjeta(caso, intermedio):
    """Sin ofrecimiento previo (o con otro mensaje entre medio) la tarjeta no
    registra obras: la oferta no se reutiliza ni se infiere."""
    b1, tarjeta = caso["b1"], caso["tarjeta"]
    antes = _huellas(caso)
    if intermedio:
        b1.atender("t", _en(tarjeta, "la obra es ACEROS AZA SA"))
        b1.atender("t", intermedio)
    r = b1.atender("t", _en(tarjeta, "registra la obra ACEROS AZA SA para el cliente ACEROS AZA SA"))
    assert r["estado"] == "ACLARACION_REQUERIDA" and b1.pendiente("t") is None
    assert _huellas(caso) == antes


def test_oferta_no_cruza_conversaciones_ni_nombres_distintos(caso):
    b1, tarjeta = caso["b1"], caso["tarjeta"]
    b1.atender("t", _en(tarjeta, "la obra es ACEROS AZA SA"))
    otra = b1.atender("otra", _en(tarjeta, "registra la obra ACEROS AZA SA para el cliente ACEROS AZA SA"))
    assert otra["estado"] == "ACLARACION_REQUERIDA"
    b1.atender("t", _en(tarjeta, "la obra es ACEROS AZA SA"))
    distinta = b1.atender("t", _en(tarjeta, "registra la obra ACEROS AZA COLINA para el cliente ACEROS AZA SA"))
    assert distinta["estado"] == "ACLARACION_REQUERIDA"
    assert _obras(caso) == [] and b1.capa.auditoria() == []


def test_chat_general_por_numero_de_guia(caso):
    b1 = caso["b1"]
    r = b1.atender("g", f"La obra de la guía {GUIA} es ACEROS AZA SA")
    assert r["estado"] == "ACLARACION_REQUERIDA" and "registra la obra ACEROS AZA SA" in r["mensaje"]
    assert b1.atender("g", "registra la obra ACEROS AZA SA para el cliente ACEROS AZA SA")["estado"] == "PREVIEW_PENDIENTE"
    siguiente = b1.atender("g", "sí")
    assert siguiente["estado"] == "PREVIEW_PENDIENTE" and siguiente["accion"] == "DOCUMENTO_ASIGNAR_OBRA"
    assert b1.atender("g", "sí")["estado"] == "EJECUTADA"
    assert _filas(caso)[ARCHIVO]["obra_destino"] == OBRA


def test_registro_con_cliente_distinto_es_explicito_y_se_muestra(caso):
    b1, tarjeta = caso["b1"], caso["tarjeta"]
    b1.atender("t", _en(tarjeta, "la obra es ACEROS AZA SA"))
    r = b1.atender("t", _en(tarjeta, "registra la obra ACEROS AZA SA para el cliente Cliente Uno SA"))
    assert r["estado"] == "PREVIEW_PENDIENTE" and r["preview"]["valor_propuesto"]["cliente"] == "CLIENTE UNO SA"


def test_obra_ya_registrada_entre_oferta_y_registro_no_duplica(caso):
    b1, tarjeta = caso["b1"], caso["tarjeta"]
    b1.atender("t", _en(tarjeta, "la obra es ACEROS AZA SA"))
    b1.atender("otro", "registra la obra ACEROS AZA SA para el cliente ACEROS AZA SA")
    b1.atender("otro", "sí")
    r = b1.atender("t", _en(tarjeta, "registra la obra ACEROS AZA SA para el cliente ACEROS AZA SA"))
    assert r["estado"] == "PREVIEW_PENDIENTE" and r["accion"] == "DOCUMENTO_ASIGNAR_OBRA", r
    assert "ya existe; no se crea otra" in r["mensaje"]
    assert len(_obras(caso)) == 1
