"""B1 -- corrección humana del MATERIAL de una guía por el canal oficial
(DOCUMENTO_CORREGIR_CAMPO, campo `descripcion_material`): interpretación,
documento exacto, validación, vista previa, confirmación explícita,
aplicación con respaldo, ledger y auditoría, protección frente a la
reextracción y aislamiento. Sólo fixtures sintéticas: nunca G: ni datos
productivos. Los números de guía de las frases son ejemplos."""
from __future__ import annotations

import csv
import hashlib
import json
import shutil

import pytest

from atlas_core import acciones_operacionales as ao
from atlas_core import recuperacion_material as rm
from atlas_core.acciones_operacionales import CapaAccionesOperacionales
from atlas_core.b1_operador import ErrorContratoInterpretacion, OperadorB1, interpretar_determinista
from atlas_core.clasificador_material import clasificar_material
from atlas_core.procesamiento_masivo import COLUMNAS
from atlas_core.recuperacion_incremental import cargar_protecciones
from atlas_core.trazabilidad_ocr import ruta_traza_ocr
from tests.test_acciones_operacionales import _EscritorDisponible, entorno  # noqa: F401 -- fixture compartida
from tests.test_b1_material_faltante import sin_material  # noqa: F401 -- fixture compartida

GUIA = "500001"
ARCHIVO = f"{GUIA}.jpeg"
# Columnas que una corrección de material puede cambiar; el resto queda idéntico.
PERMITIDAS = {"descripcion_material", "tipo_carga", "motivos_revision_documento", "indicador_revision",
              "estado_documental", "estado_operacional"}


def _filas(e):
    with e["dataset"].open(encoding="utf-8-sig", newline="") as archivo:
        return list(csv.DictReader(archivo, delimiter=";"))


def _escribir(e, filas):
    with e["dataset"].open("w", encoding="utf-8-sig", newline="") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader()
        escritor.writerows(filas)


def _fila(e, guia=GUIA):
    return next(f for f in _filas(e) if f["numero_guia"] == guia)


def _sha(ruta):
    return hashlib.sha256(ruta.read_bytes()).hexdigest()


def _ledger(e):
    return json.loads((e["actual"] / "decisiones_aplicadas.json").read_text(encoding="utf-8"))["aplicaciones"]


def _agregar_ledger(e, entrada):
    ruta = e["actual"] / "decisiones_aplicadas.json"
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    datos["aplicaciones"].append(entrada)
    ruta.write_text(json.dumps(datos), encoding="utf-8")


def _correcciones(e):
    return [a for a in _ledger(e) if a.get("campo") == "descripcion_material"]


_REGISTROS_DE_SESION = {"b1_operador_conversaciones.json", "acciones_operacionales.json"}


def _huellas(e, raiz=None):
    """Todo el contenido de la raíz salvo los registros de sesión del canal."""
    raiz = raiz or e["raiz"]
    return {p.relative_to(raiz): _sha(p) for p in raiz.rglob("*")
            if p.is_file() and p.name not in _REGISTROS_DE_SESION and ".lock" not in p.name}


def _auditoria(b1):
    return [a for a in b1.capa.auditoria() if a["accion"] == "DOCUMENTO_CORREGIR_CAMPO"]


@pytest.fixture
def guia(sin_material):
    """500001 con material mal leído, original y traza OCR en disco."""
    e = sin_material
    filas = _filas(e)
    for f in filas:
        if f["numero_guia"] == GUIA:
            f.update(descripcion_material="ROLLO 8MM ILEGIBLE", tipo_carga=clasificar_material("ROLLO 8MM ILEGIBLE").value,
                     motivos_revision_documento="MATERIAL_OCR_NO_CONFIABLE", estado_ruta="CALCULADA",
                     distancia_km="31.2", duracion_min="44")
    _escribir(e, filas)
    original = e["raiz"] / ARCHIVO
    original.write_bytes(b"\xff\xd8 original sintetico \xff\xd9")
    traza = ruta_traza_ocr(e["raiz"] / "operacion" / "trazas_ocr", ARCHIVO)
    traza.parent.mkdir(parents=True, exist_ok=True)
    traza.write_text(json.dumps({"imagen": {"referencia": ARCHIVO}, "ocr": {
        "backend": {"nombre": "sintetico"}, "lineas": ["DESCRIPCION", "ROLLO 8MM ILEGIBLE"]}}), encoding="utf-8")
    e.update(original=original, traza=traza)
    return e


# ------------------------------------------------------------ interpretación


@pytest.mark.parametrize("texto,valor", [
    ("El material de la guía 482816 es barras.", "BARRAS"),
    ("Corrige el material de la guía 482816 a rollos", "ROLLOS"),
    ("Cambia el material de la guía N° 482816 por rollo 8mm", "ROLLO 8MM"),
    ("El material de la guía 482816 es barras y rollos", "BARRAS Y ROLLOS"),
    # Caso real 484838: la cola de la orden nunca forma parte del material.
    ("El material de la guía 484838 es fierro 12mm, corrígelo", "FIERRO 12MM"),
    ("El material de la guía 482816 es, ROLLO 8MM, corrígelo por favor", "ROLLO 8MM"),
    ("Corrige el material de la guía 482816 a rollos, no cambies nada más", "ROLLOS"),
    ("El material de la guía 482816 es barras, confírmalo", "BARRAS"),
])
def test_instruccion_valida_identifica_guia_campo_y_valor(texto, valor):
    intencion = interpretar_determinista(texto)
    assert intencion.accion == "DOCUMENTO_CORREGIR_CAMPO"
    assert intencion.parametros["campo"] == "descripcion_material" and intencion.parametros["valor"] == valor
    assert intencion.parametros["numero_guia"] in {"482816", "484838"}


@pytest.mark.parametrize("texto", [
    "El material de la guía 482816 es sí", "el material de la guia 482816 es 12345",
    "El material de la guía 482816 es barras y el peso es 30000",
    "El material de la guía 482816 es barras y la patente es KN5439",
    "El material de las guías 482816 y 482817 es barras",
    "El material de la guía 482816 y 482817 es barras",
    "Corrige el material de la guía 482816 a rollos como la guía 482817",
])
def test_instrucciones_invalidas_se_rechazan_con_explicacion(texto):
    with pytest.raises(ErrorContratoInterpretacion) as exc:
        interpretar_determinista(texto)
    assert "No se corrigió nada" in str(exc.value)


# ------------------------------------------------------------ flujo completo


def test_preview_muestra_anterior_propuesto_y_tipo_sin_escribir(guia):
    b1, antes = guia["b1"], _huellas(guia)
    r = b1.atender("c1", "El material de la guía 500001 es barras")
    assert r["estado"] == "PREVIEW_PENDIENTE", r
    assert ("material actual «ROLLO 8MM ILEGIBLE», material propuesto «BARRAS». Origen: indicado por el usuario "
            "(decisión humana).") in r["mensaje"]
    assert "El tipo de carga pasa de" in r["mensaje"] and r["mensaje"].rstrip().endswith("(sí / no)")
    assert _huellas(guia) == antes and not _auditoria(b1)


def test_propuesta_con_orden_de_confirmar_no_es_confirmacion(guia):
    antes = _huellas(guia)
    r = guia["b1"].atender("c1", "El material de la guía 500001 es barras, confírmalo")
    assert r["estado"] == "PREVIEW_PENDIENTE"
    assert _huellas(guia) == antes and not _correcciones(guia)


def test_confirmacion_aceptada_aplica_con_ledger_auditoria_y_respaldo(guia):
    b1, previo, otras = guia["b1"], _fila(guia), [f for f in _filas(guia) if f["numero_guia"] != GUIA]
    texto = "Corrige el material de la guía 500001 a rollos 8mm"
    assert b1.atender("c1", texto)["estado"] == "PREVIEW_PENDIENTE"
    r = b1.atender("c1", "sí")
    assert r["estado"] == "EJECUTADA", r
    fila = _fila(guia)
    assert fila["descripcion_material"] == "ROLLOS 8MM"
    assert fila["tipo_carga"] == clasificar_material("ROLLOS 8MM").value
    assert "MATERIAL_OCR_NO_CONFIABLE" not in fila["motivos_revision_documento"]
    # Campos ajenos y otras guías intactos (ruta, estado de ruta, peso, fecha, chofer, transporte...).
    assert {c: v for c, v in fila.items() if c not in PERMITIDAS} == \
        {c: v for c, v in previo.items() if c not in PERMITIDAS}
    assert [f for f in _filas(guia) if f["numero_guia"] != GUIA] == otras
    [registro] = _correcciones(guia)
    assert registro["tipo"] == "CORRECCION_DOCUMENTAL_OPERADOR" and registro["accion"] == "CORREGIR_CAMPO"
    assert registro["confirmado_por"] == "JAVIER" and registro["documento"]["archivo"] == ARCHIVO
    assert (registro["valor_documental"], registro["valor_corregido"]) == ("ROLLO 8MM ILEGIBLE", "ROLLOS 8MM")
    assert registro["referencia"] == texto and "reemplaza" not in registro
    [auditoria] = _auditoria(b1)
    assert auditoria["confirmado_por"] == "JAVIER" and auditoria["resultado"] == "APLICADA"
    assert auditoria["token"] and auditoria["respaldo"]
    respaldos = [p for p in (guia["raiz"] / "respaldos").rglob("*") if p.is_file()]
    assert any(b"ROLLO 8MM ILEGIBLE" in p.read_bytes() for p in respaldos), "sin respaldo del estado anterior"


def test_original_y_ocr_inmutables(guia):
    original, traza = _sha(guia["original"]), _sha(guia["traza"])
    b1 = guia["b1"]
    b1.atender("c1", "El material de la guía 500001 es barras")
    assert b1.atender("c1", "sí")["estado"] == "EJECUTADA"
    assert (_sha(guia["original"]), _sha(guia["traza"])) == (original, traza)


def test_confirmacion_rechazada_no_escribe(guia):
    b1, antes = guia["b1"], _huellas(guia)
    b1.atender("c1", "El material de la guía 500001 es barras")
    assert b1.atender("c1", "no")["estado"] == "CANCELADA"
    assert _huellas(guia) == antes and not _correcciones(guia)
    assert b1.atender("c1", "sí")["estado"] == "SIN_PREVIEW_PENDIENTE"   # nada quedó pendiente
    assert _huellas(guia) == antes


def test_confirmacion_repetida_aplica_una_sola_vez(guia):
    b1 = guia["b1"]
    b1.atender("c1", "El material de la guía 500001 es barras")
    assert b1.atender("c1", "sí")["estado"] == "EJECUTADA"
    despues = _huellas(guia)
    assert b1.atender("c1", "sí")["estado"] == "SIN_PREVIEW_PENDIENTE"
    assert _huellas(guia) == despues and len(_correcciones(guia)) == 1 and len(_auditoria(b1)) == 1


def test_guia_inexistente(guia):
    antes = _huellas(guia)
    r = guia["b1"].atender("c1", "El material de la guía 999999 es barras")
    assert r["estado"] == "RECHAZADA" and r["codigo"] == "ENTIDAD_NO_ENCONTRADA"
    assert _huellas(guia) == antes


@pytest.mark.parametrize("texto", ["El material de la guía 500001 es sí", "El material de la guía 500001 es 12345",
                                   "El material de la guía 500001 es NO DETERMINADO",
                                   "El material de la guía 500001 es barras y el peso es 30000"])
def test_material_invalido(guia, texto):
    antes = _huellas(guia)
    r = guia["b1"].atender("c1", texto)
    assert r["estado"] == "RECHAZADA", r
    assert _huellas(guia) == antes and not _correcciones(guia)


@pytest.mark.parametrize("valor", ["12345", "SÍ", "ok", "--", "BARRAS\x00", ""])
def test_canal_oficial_valida_el_material_sin_depender_de_b1(guia, valor):
    capa = CapaAccionesOperacionales(guia["raiz"], fabrica_escritor=lambda: _EscritorDisponible())
    antes = _huellas(guia)
    try:
        r = capa.previsualizar("DOCUMENTO_CORREGIR_CAMPO", {"numero_guia": GUIA, "campo": "descripcion_material",
                                                            "valor": valor}, actor="JAVIER")
    except ao.ErrorAccionOperacional:
        r = {"estado": "RECHAZADA"}
    assert r["estado"] == "RECHAZADA", r
    assert _huellas(guia) == antes


def test_documento_ambiguo(guia):
    filas = _filas(guia)
    filas.append(dict(_fila(guia), archivo="500001_b.jpeg", numero_transporte="0000900077"))
    _escribir(guia, filas)
    antes = _huellas(guia)
    r = guia["b1"].atender("c1", "El material de la guía 500001 es barras")
    assert r["estado"] == "RECHAZADA" and r["codigo"] == "ENTIDAD_AMBIGUA"
    assert _huellas(guia) == antes


# ------------------------------------------------------------ conflictos


def test_conflicto_con_correccion_humana_previa_se_muestra_y_se_registra(guia):
    b1 = guia["b1"]
    b1.atender("c1", "El material de la guía 500001 es barras")
    assert b1.atender("c1", "sí")["estado"] == "EJECUTADA"
    [primera] = _correcciones(guia)
    r = b1.atender("c2", "Corrige el material de la guía 500001 a rollos 8mm")
    assert r["estado"] == "PREVIEW_PENDIENTE"
    assert ("Atención: esta guía ya tiene el material corregido por una persona («BARRAS», confirmado por "
            "JAVIER") in r["mensaje"] and "esta corrección la reemplaza" in r["mensaje"]
    assert len(_correcciones(guia)) == 1                       # la propuesta no reemplaza nada
    assert b1.atender("c2", "sí")["estado"] == "EJECUTADA"
    segunda = _correcciones(guia)[-1]
    assert segunda["reemplaza"] == [primera["decision_id"]]
    assert (segunda["valor_documental"], segunda["valor_corregido"]) == ("BARRAS", "ROLLOS 8MM")


def test_correccion_concurrente_deja_obsoleta_la_vista_previa(guia):
    b1 = guia["b1"]
    assert b1.atender("c1", "El material de la guía 500001 es barras")["estado"] == "PREVIEW_PENDIENTE"
    b1.atender("c2", "El material de la guía 500001 es rollos")
    assert b1.atender("c2", "sí")["estado"] == "EJECUTADA"
    despues = _huellas(guia)
    r = b1.atender("c1", "sí")
    assert r["estado"] != "EJECUTADA", r
    assert _huellas(guia) == despues and [c["valor_corregido"] for c in _correcciones(guia)] == ["ROLLOS"]


def test_decision_de_revision_sobre_el_material_bloquea(guia):
    _agregar_ledger(guia, {"decision_id": "REV-1", "tipo": "MATERIAL_REVISION", "actor": "JAVIER",
                           "documento": {"archivo": ARCHIVO, "numero_guia": GUIA}, "campo": "descripcion_material",
                           "valor_corregido": "ROLLO 8MM"})
    antes = _huellas(guia)
    r = guia["b1"].atender("c1", "El material de la guía 500001 es barras")
    assert r["estado"] == "RECHAZADA" and r["codigo"] == "CAMPO_FIJADO_POR_DECISION_HUMANA"
    assert _huellas(guia) == antes


def test_tipo_de_carga_fijado_por_decision_humana_se_conserva(guia):
    tipo = _fila(guia)["tipo_carga"]
    assert tipo == clasificar_material("ROLLO 8MM ILEGIBLE").value != clasificar_material("BARRAS 12MM").value
    _agregar_ledger(guia, {"decision_id": "REV-2", "tipo": "TIPO_CARGA_REVISION", "actor": "JAVIER",
                           "documento": {"archivo": ARCHIVO, "numero_guia": GUIA}, "campo": "tipo_carga",
                           "valor_corregido": tipo})
    b1 = guia["b1"]
    r = b1.atender("c1", "El material de la guía 500001 es barras 12mm")
    assert f"El tipo de carga se conserva en {tipo} porque lo fijó una decisión humana." in r["mensaje"]
    assert b1.atender("c1", "sí")["estado"] == "EJECUTADA"
    assert (_fila(guia)["descripcion_material"], _fila(guia)["tipo_carga"]) == ("BARRAS 12MM", tipo)


def test_reextraccion_automatica_no_reemplaza_ni_confirma(guia):
    b1 = guia["b1"]
    b1.atender("c1", "El material de la guía 500001 es barras")
    assert b1.atender("c1", "sí")["estado"] == "EJECUTADA"
    ledger, auditoria = _ledger(guia), _auditoria(b1)
    fila = _fila(guia)
    lectura = rm.material_desde_lineas(["DESCRIPCION", "ROLLO 10MM A630-420H"])
    assert rm.evaluar_recuperacion(fila, lectura, ledger) == (rm.PROTEGIDO_POR_DECISION, {})
    assert "descripcion_material" in cargar_protecciones(guia["actual"]).por_archivo.get(ARCHIVO, set())
    assert _ledger(guia) == ledger and _auditoria(b1) == auditoria   # nada nuevo confirmado por nadie


# ------------------------------------------------------------ fallos y aislamiento


def test_fallo_durante_la_aplicacion_restaura_todo(guia, monkeypatch):
    b1 = guia["b1"]
    assert b1.atender("c1", "El material de la guía 500001 es barras")["estado"] == "PREVIEW_PENDIENTE"
    antes = _huellas(guia)
    original = ao.escribir_json_atomico

    def fallar_en_ledger(ruta, *args, **kwargs):
        if str(ruta).endswith("decisiones_aplicadas.json"):
            raise OSError("disco lleno (simulado)")
        return original(ruta, *args, **kwargs)

    monkeypatch.setattr(ao, "escribir_json_atomico", fallar_en_ledger)
    r = b1.atender("c1", "sí")
    assert r["estado"] != "EJECUTADA", r
    # Ni el dataset (ya escrito por el reparador) ni el ledger quedan a medias.
    restantes = {k: v for k, v in _huellas(guia).items() if "respaldos" not in k.parts}
    assert restantes == {k: v for k, v in antes.items() if "respaldos" not in k.parts}
    assert _fila(guia)["descripcion_material"] == "ROLLO 8MM ILEGIBLE" and not _correcciones(guia)
    assert [a["resultado"] for a in _auditoria(b1)] == ["FALLIDA"]


def test_aislamiento_entre_empresas(guia, tmp_path):
    otra = tmp_path / "EmpresaB"
    shutil.copytree(guia["raiz"], otra)
    dataset_b = otra / "operacion" / "actual" / "analisis_completo_guias.csv"
    texto = dataset_b.read_text(encoding="utf-8-sig").replace("500002", "600002")
    dataset_b.write_text(texto, encoding="utf-8-sig")
    antes_b = _huellas(guia, otra)
    b1 = guia["b1"]
    # La guía de la otra empresa no existe para esta raíz.
    r = b1.atender("c1", "El material de la guía 600002 es barras")
    assert r["estado"] == "RECHAZADA" and r["codigo"] == "ENTIDAD_NO_ENCONTRADA"
    # La misma guía en ambas: sólo cambia la de esta empresa.
    b1.atender("c1", "El material de la guía 500001 es barras")
    assert b1.atender("c1", "sí")["estado"] == "EJECUTADA"
    assert _huellas(guia, otra) == antes_b
    assert _fila(guia)["descripcion_material"] == "BARRAS"
