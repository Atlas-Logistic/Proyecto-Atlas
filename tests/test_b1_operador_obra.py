"""B1 operador -- OBRA de una guía en lenguaje natural ("La obra de la guía N
es X"). La obra se resuelve contra el catálogo existente (coincidencia única,
nunca se crea obra ni alias) y se aplica por DOCUMENTO_ASIGNAR_OBRA sólo tras
confirmación humana. Copias sintéticas; nunca G:."""
from __future__ import annotations

import csv
import hashlib
import json

import pytest

from atlas_core.acciones_operacionales import CapaAccionesOperacionales, TIPO_LEDGER_CORRECCION
from atlas_core.b1_operador import OperadorB1, interpretar_determinista
from tests.test_acciones_operacionales import entorno  # noqa: F401 -- fixture

OBRA_ID = "obra-vieja-renca"
NOMBRE = "OBRA VIEJA SA, RENCA"


def _obra(obra_id, nombre, cliente_id, aliases=()):
    return {"obra_id": obra_id, "cliente_id": cliente_id, "nombre_canonico": nombre,
            "nombre_normalizado": " ".join(nombre.replace(",", " ").split()), "aliases_documentales": list(aliases),
            "estado": "OBSERVADA", "estado_vigencia": "ACTIVO", "evidencias": [],
            "fecha_creacion": "2026-01-01T00:00:00+00:00", "fecha_modificacion": "2026-01-01T00:00:00+00:00"}


@pytest.fixture
def b1(entorno):  # noqa: F811
    cliente_id = entorno["cliente"].cliente_id
    obras = [_obra(OBRA_ID, NOMBRE, cliente_id), _obra("obra-vieja-colina", "OBRA VIEJA SA, COLINA", cliente_id),
             _obra("sur-a", "EDIFICIO SUR", cliente_id), _obra("sur-b", "EDIFICIO SUR LTDA", cliente_id, ["EDIFICIO SUR"])]
    (entorno["cat"] / "obras_destinos.json").write_text(
        json.dumps({"version_formato": 1, "obras": obras, "relaciones": []}), encoding="utf-8")
    revalidadas: list[set[str]] = []
    capa = CapaAccionesOperacionales(entorno["raiz"])
    capa._revalidar_guias = lambda guias: revalidadas.append(set(guias)) or {"ejecutado": True}
    operador = OperadorB1(entorno["raiz"], capa=capa)
    operador.revalidadas = revalidadas
    return operador


def _sha(ruta):
    return hashlib.sha256(ruta.read_bytes()).hexdigest() if ruta.exists() else None


def _huellas(entorno):
    return {n: _sha(p) for n, p in {
        "dataset": entorno["dataset"], "obras": entorno["cat"] / "obras_destinos.json",
        "ledger": entorno["actual"] / "decisiones_aplicadas.json",
        "bandeja": entorno["actual"] / "decisiones_pendientes.json"}.items()}


def _fila(entorno, guia="500001"):
    return next(f for f in csv.DictReader(entorno["dataset"].open(encoding="utf-8-sig", newline=""), delimiter=";")
                if f["numero_guia"] == guia)


@pytest.mark.parametrize("texto", [
    "La obra de la guía 500001 es Obra Vieja SA, Renca",
    "obra de la guia N° 500001: Obra Vieja SA, Renca",
    "La guía 500001 pertenece a la obra Obra Vieja SA, Renca",
    "La guia 500001 corresponde a la obra OBRA VIEJA SA, RENCA",
    "Cambia la obra de la guía 500001 a Obra Vieja SA, Renca",
    "Corrige la obra de la guía 500001 por Obra Vieja SA, Renca",
    "Asigna la obra de la guía 500001 a Obra Vieja SA, Renca",
])
def test_tres_formas_de_instruccion(texto):
    intencion = interpretar_determinista(texto)
    assert intencion is not None and intencion.accion == "DOCUMENTO_ASIGNAR_OBRA"
    assert intencion.parametros == {"numero_guia": "500001"}
    assert intencion.menciones == {"obra": "OBRA VIEJA SA, RENCA"}


def test_prioridad_sobre_interpretacion_como_chofer():
    intencion = interpretar_determinista("La obra de la guía 480728 es PRODALAM SA, RENCA")
    assert intencion.accion == "DOCUMENTO_ASIGNAR_OBRA"
    assert "chofer" not in intencion.menciones
    assert intencion.menciones == {"obra": "PRODALAM SA, RENCA"}
    assert interpretar_determinista("¿Cuál es la obra de la guía 480728?") is None


def test_preview_sin_escritura_confirmacion_una_vez_idempotencia_y_revalidacion_focal(entorno, b1):  # noqa: F811
    antes = _huellas(entorno)
    vieja = entorno["decision"]["decision_id"]
    r = b1.atender("c", "La obra de la guía 500001 es Obra Vieja SA, Renca")
    assert r["estado"] == "PREVIEW_PENDIENTE", r
    p = r["preview"]
    assert p["accion"] == "DOCUMENTO_ASIGNAR_OBRA"
    assert p["entidad"]["numero_guia"] == "500001" and p["entidad"]["obra_id"] == OBRA_ID
    assert p["valor_actual"] == {"obra_destino": "OBRA VIEJA"}
    assert p["valor_propuesto"] == {"obra_destino": NOMBRE, "obra_id": OBRA_ID}
    assert [d["decision_id"] for d in p["afectados"]["decisiones_obsoletas"]] == [vieja]
    assert "MANTENIMIENTO_FOCAL_GUIA" in p["revalidaciones"]
    for texto in ("guía 500001", "'OBRA VIEJA'", repr(NOMBRE), OBRA_ID, "no crea obra nueva", "¿Confirmas?"):
        assert texto in r["mensaje"]
    assert _huellas(entorno) == antes and b1.revalidadas == []

    e = b1.atender("c", "sí")
    assert e["estado"] == "EJECUTADA", e
    assert _fila(entorno)["obra_destino"] == NOMBRE
    assert _fila(entorno, "500002")["obra_destino"] == "OBRA OTRA"
    assert vieja in e["resultado"]["decisiones_retiradas"]
    assert b1.revalidadas == [{"500001"}]  # sólo la guía afectada
    auditoria = b1.capa.auditoria()
    assert len(auditoria) == 1 and auditoria[0]["confirmado_por"] == "JAVIER"
    assert auditoria[0]["despues"] == {"obra_destino": NOMBRE, "obra_id": OBRA_ID}
    ledger = json.loads((entorno["actual"] / "decisiones_aplicadas.json").read_text(encoding="utf-8"))["aplicaciones"]
    assert [(a["campo"], a["valor_documental"], a["valor_corregido"]) for a in ledger
            if a["tipo"] == TIPO_LEDGER_CORRECCION] == [("obra_destino", "OBRA VIEJA", NOMBRE)]
    # catálogo intacto: ni obra nueva ni alias del valor anterior
    assert _sha(entorno["cat"] / "obras_destinos.json") == antes["obras"]

    # confirmar otra vez / reintentar el token / repetir la orden: nada se reescribe
    despues = _huellas(entorno)
    assert b1.atender("c", "sí")["estado"] == "SIN_PREVIEW_PENDIENTE"
    assert b1.capa.ejecutar(auditoria[0]["token"], actor="B1", origen="B1", confirmado_por="JAVIER")["idempotente"]
    otra = b1.atender("c", "La guía 500001 pertenece a la obra Obra Vieja SA, Renca")
    assert otra["estado"] == "SIN_CAMBIOS"
    assert _huellas(entorno) == despues and len(b1.capa.auditoria()) == 1 and b1.revalidadas == [{"500001"}]


def test_obra_inexistente_se_abstiene_sin_crear(entorno, b1):  # noqa: F811
    antes = _huellas(entorno)
    r = b1.atender("c", "La obra de la guía 500001 es Obra Vieja")
    assert r["estado"] == "ACLARACION_REQUERIDA"
    assert {c["obra_id"] for c in r["candidatos"]} == {OBRA_ID, "obra-vieja-colina"}  # sugerencias, no elección
    assert "No creo obras nuevas" in r["mensaje"]
    r = b1.atender("c", "La obra de la guía 500001 es Torre Inventada")
    assert r["estado"] == "ACLARACION_REQUERIDA" and r["candidatos"] == []
    assert b1.pendiente("c") is None and b1.atender("c", "sí")["estado"] == "SIN_PREVIEW_PENDIENTE"
    assert _huellas(entorno) == antes


def test_obra_ambigua_se_abstiene(entorno, b1):  # noqa: F811
    antes = _huellas(entorno)
    r = b1.atender("c", "Asigna la obra de la guía 500001 a Edificio Sur")
    assert r["estado"] == "ACLARACION_REQUERIDA"
    assert {c["obra_id"] for c in r["candidatos"]} == {"sur-a", "sur-b"}
    assert "más de una obra" in r["mensaje"] and b1.pendiente("c") is None
    assert _huellas(entorno) == antes


def test_guia_inexistente_rechaza_sin_escribir(entorno, b1):  # noqa: F811
    antes = _huellas(entorno)
    r = b1.atender("c", "La obra de la guía 999999 es Obra Vieja SA, Renca")
    assert r["estado"] == "RECHAZADA" and r["codigo"] == "ENTIDAD_NO_ENCONTRADA"
    assert b1.pendiente("c") is None and _huellas(entorno) == antes
