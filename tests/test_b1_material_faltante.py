"""B1 -- material faltante de una guía: propuesta desde la evidencia (OCR),
abstención sin evidencia suficiente y valor indicado por el usuario, siempre
con preview, confirmación explícita y auditoría. Reutiliza
DOCUMENTO_RECUPERAR_MATERIAL y DOCUMENTO_CORREGIR_CAMPO. Sólo fixtures
sintéticas: nunca G: ni datos productivos; el OCR se simula."""
from __future__ import annotations

import csv
import hashlib
import json

import pytest

from atlas_core import acciones_operacionales as ao
from atlas_core import recuperacion_material as rm
from atlas_core.acciones_operacionales import CapaAccionesOperacionales
from atlas_core.almacenamiento_portable import leer_estado_operacion
from atlas_core.b1_operador import OperadorB1, interpretar_determinista
from atlas_core.procesamiento_masivo import COLUMNAS
from atlas_core.responder_consulta_atlas import responder_consulta_atlas
from tests.test_acciones_operacionales import _EscritorDisponible, entorno  # noqa: F401 -- fixture compartida

GUIA = "500001"
ARCHIVO = f"{GUIA}.jpeg"
LINEAS_OCR = ["DESCRIPCION", "CANTIDAD", "CODIGO", "BHORMIGON16MM 11MA630-420H(N)", "27.569110002930"]
MATERIAL_OCR = "B HORMIGON 16MM 11MA630-420H(N)"
# Campos que una corrección de material nunca puede tocar.
INTOCABLES = ("numero_guia", "numero_transporte", "peso_kg", "fecha", "chofer", "rut_chofer", "patente_tracto",
              "cliente", "obra_destino", "despachar_a_crudo", "direccion_entrega", "estado_ruta", "archivo")


def _filas(entorno):
    with entorno["dataset"].open(encoding="utf-8-sig", newline="") as archivo:
        return list(csv.DictReader(archivo, delimiter=";"))


def _sha(ruta):
    return hashlib.sha256(ruta.read_bytes()).hexdigest()


def _ledger(entorno):
    return json.loads((entorno["actual"] / "decisiones_aplicadas.json").read_text(encoding="utf-8"))["aplicaciones"]


@pytest.fixture
def sin_material(entorno, monkeypatch):
    """500001 sin material (NO DETERMINADO), como la 483633 real; OCR simulado."""
    filas = _filas(entorno)
    for f in filas:
        if f["numero_guia"] == GUIA:
            f.update(descripcion_material="", tipo_carga="NO DETERMINADO", motivos_revision_documento="MATERIAL_AUSENTE",
                     peso_kg="27000", fecha="20-10-2026")
        else:
            f.update(descripcion_material="ACERO 12MM", tipo_carga="FIERRO")
    with entorno["dataset"].open("w", encoding="utf-8-sig", newline="") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader()
        escritor.writerows(filas)
    lectura = {"actual": rm.material_desde_lineas(LINEAS_OCR)}
    monkeypatch.setattr(ao, "_leer_material_evidencia", lambda ctx, archivo: lectura["actual"])
    entorno["lectura"] = lectura
    entorno["b1"] = OperadorB1(entorno["raiz"], usuario="JAVIER", capa=CapaAccionesOperacionales(
        entorno["raiz"], fabrica_escritor=lambda: _EscritorDisponible()))
    return entorno


def _protegidos(entorno):
    return {n: _sha(entorno["actual"] / n) for n in ("analisis_completo_guias.csv", "decisiones_aplicadas.json")}


def _viajes_sin_material(entorno):
    reporte = (leer_estado_operacion(raiz=entorno["raiz"]) or {})["reporte_vigente"]
    r = responder_consulta_atlas("Cuantos viajes no tienen material", ruta_viajes=entorno["raiz"] / reporte / "viajes.csv")
    return r.resultado.resultado, entorno["raiz"] / reporte / "viajes.csv"


# ------------------------------------------------------------ interpretación


@pytest.mark.parametrize("texto", ["Recupera el material de la guía 500001", "propón el material de la guia N° 500001",
                                   "lee el material de la guía 500001"])
def test_recuperar_material_se_interpreta_como_propuesta_desde_la_evidencia(texto):
    intencion = interpretar_determinista(texto)
    assert intencion.accion == "DOCUMENTO_RECUPERAR_MATERIAL"
    assert intencion.parametros == {"numero_guia": GUIA, "referencia": texto}


@pytest.mark.parametrize("texto", ["El material de la guía 500001 es fierro 12mm", "material de la guia 500001: Fierro 12MM",
                                   "Corrige el material de la guía 500001 a FIERRO 12MM"])
def test_material_indicado_por_el_usuario_es_correccion_documental(texto):
    intencion = interpretar_determinista(texto)
    assert intencion.accion == "DOCUMENTO_CORREGIR_CAMPO"
    assert intencion.parametros == {"numero_guia": GUIA, "campo": "descripcion_material", "valor": "FIERRO 12MM",
                                    "referencia": texto}


@pytest.mark.parametrize("texto", ["¿Qué material tiene la guía 500001?", "¿El material de la guía 500001 es fierro?"])
def test_preguntas_sobre_material_nunca_son_correcciones(texto):
    intencion = interpretar_determinista(texto)
    assert intencion is None or intencion.accion not in {"DOCUMENTO_CORREGIR_CAMPO", "DOCUMENTO_RECUPERAR_MATERIAL"}


def test_canal_desktop_deriva_las_ordenes_de_material_al_operador(sin_material):
    for texto in ("Recupera el material de la guía 500001", "El material de la guía 500001 es FIERRO 12MM"):
        assert sin_material["b1"].consultar(texto, derivar_operacionales=True) == {"estado": "REQUIERE_OPERADOR"}
        assert sin_material["b1"].consultar(texto)["estado"] == "RECHAZADA"


# ------------------------------------------------------------ propuesta OCR


def test_propuesta_ocr_muestra_guia_actual_propuesto_y_origen_sin_escribir(sin_material):
    antes = _protegidos(sin_material)
    r = sin_material["b1"].atender("conv-mat", "Recupera el material de la guía 500001")
    assert r["estado"] == "PREVIEW_PENDIENTE", r
    assert "Material de la guía 500001: actual sin material" in r["mensaje"]
    assert f"propuesto «{MATERIAL_OCR}»" in r["mensaje"]
    assert "Origen: lectura OCR de la evidencia original (RECUPERAR)" in r["mensaje"]
    assert "no es una decisión humana" in r["mensaje"] and r["mensaje"].endswith("¿Confirmas? (sí / no)")
    assert r["preview"]["entidad"]["id"] == ARCHIVO and "token" not in r["preview"]
    assert _protegidos(sin_material) == antes


def test_confirmar_propuesta_ocr_solo_cambia_material_audita_y_no_es_decision_humana(sin_material):
    original = {f["archivo"]: f for f in _filas(sin_material)}
    ledger = _sha(sin_material["actual"] / "decisiones_aplicadas.json")
    b1 = sin_material["b1"]
    b1.atender("conv-mat", "Recupera el material de la guía 500001")
    r = b1.atender("conv-mat", "sí")
    assert r["estado"] == "EJECUTADA", r
    assert r["mensaje"].startswith(f"Listo: la guía 500001 quedó con material «{MATERIAL_OCR}», leído de la evidencia original.")
    despues = {f["archivo"]: f for f in _filas(sin_material)}
    fila = despues[ARCHIVO]
    assert fila["descripcion_material"] == MATERIAL_OCR and fila["tipo_carga"] != "NO DETERMINADO"
    assert "MATERIAL_AUSENTE" not in fila["motivos_revision_documento"]
    for campo in INTOCABLES:
        assert fila[campo] == original[ARCHIVO][campo], campo
    assert despues["500002.jpeg"] == original["500002.jpeg"]
    # El OCR confirmado no se registra como decisión humana en el ledger.
    assert _sha(sin_material["actual"] / "decisiones_aplicadas.json") == ledger
    auditoria = [a for a in b1.capa.auditoria() if a["accion"] == "DOCUMENTO_RECUPERAR_MATERIAL"]
    assert len(auditoria) == 1 and auditoria[0]["confirmado_por"] == "JAVIER"
    # La consulta de B1 refleja la corrección.
    total, viajes = _viajes_sin_material(sin_material)
    assert total == 0
    assert MATERIAL_OCR in viajes.read_text(encoding="utf-8-sig")


def test_sin_confirmacion_no_se_escribe_nada(sin_material):
    antes = _protegidos(sin_material)
    b1 = sin_material["b1"]
    b1.atender("conv-mat", "Recupera el material de la guía 500001")
    assert b1.atender("conv-mat", "no")["estado"] == "CANCELADA"
    assert b1.atender("conv-mat", "sí")["estado"] == "SIN_PREVIEW_PENDIENTE"
    assert _protegidos(sin_material) == antes


def test_sin_evidencia_suficiente_se_abstiene_y_ofrece_indicar_el_material(sin_material):
    sin_material["lectura"]["actual"] = rm.material_desde_lineas(["DESCRIPCION", "CANTIDAD"])
    antes = _protegidos(sin_material)
    r = sin_material["b1"].atender("conv-mat", "Recupera el material de la guía 500001")
    assert r["estado"] == "SIN_CAMBIOS", r
    assert "La evidencia original no permite proponer un material confiable para la guía 500001" in r["mensaje"]
    assert "(resultado SIN_EVIDENCIA" in r["mensaje"] and "No se cambió nada." in r["mensaje"]
    assert "«el material de la guía 500001 es …»" in r["mensaje"]
    assert sin_material["b1"].atender("conv-mat", "sí")["estado"] == "SIN_PREVIEW_PENDIENTE"
    assert _protegidos(sin_material) == antes


def test_evidencia_no_disponible_tambien_ofrece_indicar_el_material(sin_material, monkeypatch):
    def sin_evidencia(ctx, archivo):
        raise ao.ErrorAccionOperacional("PRECONDICION_FALLIDA", "evidencia original no disponible (drive)")
    monkeypatch.setattr(ao, "_leer_material_evidencia", sin_evidencia)
    r = sin_material["b1"].atender("conv-mat", "Recupera el material de la guía 500001")
    assert r["estado"] == "RECHAZADA" and "evidencia original no disponible" in r["mensaje"]
    assert "«el material de la guía 500001 es …»" in r["mensaje"]


# ------------------------------------------------------------ valor del usuario


def test_material_del_usuario_con_preview_ledger_auditoria_y_consulta_posterior(sin_material):
    original = {f["archivo"]: f for f in _filas(sin_material)}
    b1 = sin_material["b1"]
    texto = "El material de la guía 500001 es fierro 12mm"
    antes = _protegidos(sin_material)
    r = b1.atender("conv-mat", texto)
    assert r["estado"] == "PREVIEW_PENDIENTE", r
    assert ("Corregir el material de la guía 500001 (transporte 0000900001): material actual sin material, "
            "material propuesto «FIERRO 12MM». Origen: indicado por el usuario (decisión humana).") in r["mensaje"]
    assert _protegidos(sin_material) == antes
    r = b1.atender("conv-mat", "sí")
    assert r["estado"] == "EJECUTADA", r
    assert r["mensaje"].startswith("Listo: la guía 500001 quedó con material «FIERRO 12MM» (antes sin material).")
    fila = {f["archivo"]: f for f in _filas(sin_material)}[ARCHIVO]
    assert fila["descripcion_material"] == "FIERRO 12MM"
    assert "MATERIAL_AUSENTE" not in fila["motivos_revision_documento"]
    for campo in INTOCABLES:
        assert fila[campo] == original[ARCHIVO][campo], campo
    [registro] = [a for a in _ledger(sin_material) if a.get("campo") == "descripcion_material"]
    assert registro["tipo"] == "CORRECCION_DOCUMENTAL_OPERADOR" and registro["confirmado_por"] == "JAVIER"
    assert (registro["valor_documental"], registro["valor_corregido"]) == ("", "FIERRO 12MM")
    assert registro["documento"]["archivo"] == ARCHIVO and registro["referencia"] == texto
    assert [a["confirmado_por"] for a in b1.capa.auditoria() if a["accion"] == "DOCUMENTO_CORREGIR_CAMPO"] == ["JAVIER"]
    assert _viajes_sin_material(sin_material)[0] == 0
    # Protegido: una nueva propuesta OCR ya no puede reemplazar la decisión humana.
    otra = b1.atender("conv-mat", "Recupera el material de la guía 500001")
    assert otra["estado"] == "RECHAZADA" and otra["codigo"] == "CAMPO_FIJADO_POR_DECISION_HUMANA"


def _tipo_carga_tras_corregir(entorno, material, tipo_inicial=None):
    if tipo_inicial is not None:
        filas = _filas(entorno)
        for f in filas:
            if f["numero_guia"] == GUIA:
                f["tipo_carga"] = tipo_inicial
        with entorno["dataset"].open("w", encoding="utf-8-sig", newline="") as archivo:
            escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
            escritor.writeheader()
            escritor.writerows(filas)
    b1 = entorno["b1"]
    b1.atender("conv-tipo", f"El material de la guía 500001 es {material}")
    assert b1.atender("conv-tipo", "sí")["estado"] == "EJECUTADA"
    return next(f for f in _filas(entorno) if f["numero_guia"] == GUIA)["tipo_carga"]


def test_material_del_usuario_recalcula_el_tipo_de_carga_derivado(sin_material):
    assert _tipo_carga_tras_corregir(sin_material, MATERIAL_OCR) == "BARRAS"


def test_tipo_de_carga_fijado_aparte_se_respeta(sin_material):
    assert _tipo_carga_tras_corregir(sin_material, MATERIAL_OCR, tipo_inicial="PERFILES") == "PERFILES"


@pytest.mark.parametrize("valor", ["NO DETERMINADO", "no_determinado", "No encontrado"])
def test_un_marcador_de_ausencia_nunca_es_un_material(sin_material, valor):
    antes = _protegidos(sin_material)
    r = sin_material["b1"].atender("conv-mat", f"El material de la guía 500001 es {valor}")
    assert r["estado"] == "RECHAZADA", r
    assert _protegidos(sin_material) == antes


def test_guia_inexistente_se_rechaza_sin_escribir(sin_material):
    antes = _protegidos(sin_material)
    r = sin_material["b1"].atender("conv-mat", "El material de la guía 999999 es FIERRO")
    assert r["estado"] == "RECHAZADA" and r["codigo"] == "ENTIDAD_NO_ENCONTRADA"
    assert _protegidos(sin_material) == antes
