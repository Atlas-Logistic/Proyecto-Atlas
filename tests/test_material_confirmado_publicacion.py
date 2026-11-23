"""Corrección humana de MATERIAL y publicación del reporte: contrato de
lectura `material_confirmado_vigente` frente al orden real del canal
DOCUMENTO_CORREGIR_CAMPO (preview -> «sí» -> respaldo -> reparador ->
ledger -> bandeja -> REPORTE -> auditoría APLICADA), con cortes en cada
etapa y recuperación con el mismo token. Sólo fixtures sintéticas."""
from __future__ import annotations

import csv
import json

import pytest

import atlas_core.acciones_operacionales as acciones
import atlas_core.reporte_viajes as reporte_viajes
from atlas_core.acciones_operacionales import CapaAccionesOperacionales
from atlas_core.campos_documentales import material_confirmado_vigente, materiales_confirmados_vigentes
from atlas_core.credibilidad_campos import evaluar_credibilidad_material, valor_publicable
from tests.test_acciones_operacionales import entorno  # noqa: F401 -- fixture compartida
from tests.test_b1_corregir_material import ARCHIVO, GUIA, _fila, _filas, guia  # noqa: F401
from tests.test_b1_material_faltante import sin_material  # noqa: F401 -- fixture compartida

# 96 caracteres: válido para el canal, DUDOSO (LONGITUD_ATIPICA) para la
# heurística OCR. Es el caso que hoy se publica como NO DETERMINADO.
LARGO = "FIERRO 8MM " + "X" * 85
CORTO = "BARRAS 12MM"


def _ledger(e) -> dict:
    return json.loads((e["actual"] / "decisiones_aplicadas.json").read_text(encoding="utf-8"))


def _vigentes(e) -> dict[str, dict]:
    return materiales_confirmados_vigentes(_ledger(e), _filas(e))


def _preview(capa, valor, guia_=GUIA):
    p = capa.previsualizar("DOCUMENTO_CORREGIR_CAMPO", {
        "numero_guia": guia_, "campo": "descripcion_material", "valor": valor}, actor="B1", origen="B1")
    assert p["estado"] == "PREVIEW", p
    return p["token"]


def _ejecutar(capa, token):
    return capa.ejecutar(token, actor="B1", origen="B1", confirmado_por="JAVIER")


def _proyeccion_material(fila, ledger) -> str:
    """Proyección de referencia (sólo prueba, no es la de Codex): un
    material humano vigente se publica tal cual; lo demás sigue la
    heurística OCR sin cambios."""
    vigente = material_confirmado_vigente(ledger, fila)
    if vigente is not None:
        return vigente["valor"]
    return valor_publicable(fila.get("descripcion_material", ""), evaluar_credibilidad_material)


@pytest.fixture
def espia_reporte(monkeypatch):
    """Captura, en el instante exacto en que el canal genera el reporte,
    lo que el contrato reconoce y si la auditoría ya dice APLICADA."""
    original = reporte_viajes.generar_reporte_viajes
    vistas: list[dict] = []

    def generar(dataset, salida, *args, ruta_ledger=None, **kwargs):
        with open(dataset, encoding="utf-8-sig", newline="") as f:
            filas = list(csv.DictReader(f, delimiter=";"))
        ledger = json.loads(open(ruta_ledger, encoding="utf-8").read()) if ruta_ledger else {}
        registro = dataset.parent / "acciones_operacionales.json"
        auditoria = json.loads(registro.read_text(encoding="utf-8")).get("auditoria", []) if registro.is_file() else []
        vistas.append({
            "vigentes": materiales_confirmados_vigentes(ledger, filas),
            "proyectado": {f["archivo"]: _proyeccion_material(f, ledger) for f in filas},
            "aplicadas": [a["token"] for a in auditoria if a.get("resultado") == "APLICADA"],
        })
        return original(dataset, salida, *args, ruta_ledger=ruta_ledger, **kwargs)

    monkeypatch.setattr(reporte_viajes, "generar_reporte_viajes", generar)
    return vistas


# ------------------------------------------------------------ orden real


@pytest.mark.parametrize("valor", [CORTO, LARGO])
def test_reporte_reconoce_la_correccion_antes_de_la_auditoria_aplicada(guia, espia_reporte, valor):
    capa = guia["b1"].capa
    token = _preview(capa, valor)
    resultado = _ejecutar(capa, token)
    assert resultado["estado"] == "APLICADA", resultado
    assert resultado["revalidacion"]["reporte"]["regenerado"]
    [vista] = espia_reporte
    # El reporte se generó ANTES de la auditoría APLICADA...
    assert token not in vista["aplicadas"]
    # ...y aun así el contrato ya reconoce la decisión humana del ledger.
    vigente = vista["vigentes"][ARCHIVO]
    assert vigente["valor"] == valor and vigente["confirmado_por"] == "JAVIER"
    assert vigente["decision_id"] == f"ACCION_OPERACIONAL:{token}"
    assert vista["proyectado"][ARCHIVO] == valor
    # Sin el contrato, la heurística OCR ocultaba el material largo.
    if valor == LARGO:
        assert valor_publicable(valor, evaluar_credibilidad_material) == "NO DETERMINADO"
    # Sólo el documento corregido: las demás guías siguen la heurística.
    assert set(vista["vigentes"]) == {ARCHIVO}


def test_flujo_b1_completo_reconoce_la_correccion(guia, espia_reporte):
    b1 = guia["b1"]
    assert b1.atender("c1", f"El material de la guía {GUIA} es {LARGO.lower()}")["estado"] == "PREVIEW_PENDIENTE"
    assert not espia_reporte and not _vigentes(guia)
    assert b1.atender("c1", "sí")["estado"] == "EJECUTADA"
    assert espia_reporte[-1]["vigentes"][ARCHIVO]["valor"] == LARGO
    assert espia_reporte[-1]["proyectado"][ARCHIVO] == LARGO


# ------------------------------------------------- nunca se publica sin asiento


def test_propuesta_sin_confirmar_no_se_reconoce(guia, espia_reporte):
    _preview(guia["b1"].capa, LARGO)
    assert not _vigentes(guia) and not espia_reporte


def test_propuesta_rechazada_no_se_reconoce(guia, espia_reporte):
    b1 = guia["b1"]
    b1.atender("c1", f"El material de la guía {GUIA} es {LARGO.lower()}")
    b1.atender("c1", "no")
    assert not _vigentes(guia) and not espia_reporte
    assert _fila(guia)["descripcion_material"] == "ROLLO 8MM ILEGIBLE"


def test_ejecucion_sin_confirmacion_humana_no_se_reconoce(guia, espia_reporte):
    capa = guia["b1"].capa
    token = _preview(capa, LARGO)
    r = capa.ejecutar(token, actor="B1", origen="B1", confirmado_por="ATLAS_AUTOMATICO")
    assert r["estado"] != "APLICADA", r
    assert not _vigentes(guia) and not espia_reporte


def test_fallo_del_reparador_restaura_y_no_se_reconoce(guia, espia_reporte, monkeypatch):
    import atlas_core.reprocesamiento_reparador as reparador
    capa = guia["b1"].capa
    token = _preview(capa, LARGO)
    original = reparador.reparar_documento_focal_con_valores_conocidos

    def reparar(**kwargs):
        if kwargs.get("dry_run") is False:  # la simulación del plan sí corre
            raise RuntimeError("fallo simulado del reparador")
        return original(**kwargs)

    monkeypatch.setattr(reparador, "reparar_documento_focal_con_valores_conocidos", reparar)
    r = _ejecutar(capa, token)
    assert r["estado"] == "FALLIDA" and r["respaldo_restaurado"], r
    assert _fila(guia)["descripcion_material"] == "ROLLO 8MM ILEGIBLE"
    assert not _vigentes(guia) and not espia_reporte


def test_fallo_al_asentar_el_ledger_restaura_y_no_se_reconoce(guia, espia_reporte, monkeypatch):
    capa = guia["b1"].capa
    token = _preview(capa, LARGO)
    escribir = acciones.escribir_json_atomico

    def fallar(ruta, contenido):
        if ruta.name == "decisiones_aplicadas.json":
            raise OSError("disco lleno simulado")
        return escribir(ruta, contenido)

    monkeypatch.setattr(acciones, "escribir_json_atomico", fallar)
    r = _ejecutar(capa, token)
    assert r["estado"] == "FALLIDA" and r["respaldo_restaurado"], r
    assert _fila(guia)["descripcion_material"] == "ROLLO 8MM ILEGIBLE"
    assert not _vigentes(guia) and not espia_reporte


def test_corte_entre_dataset_y_ledger_no_se_reconoce_hasta_recuperar(guia, espia_reporte, monkeypatch):
    """Dataset ya escrito, ledger no: el valor nuevo está en la fila pero no
    hay decisión asentada -> no se publica como confirmado."""
    capa = guia["b1"].capa
    token = _preview(capa, LARGO)
    escribir = acciones.escribir_json_atomico

    def cortar(ruta, contenido):
        if ruta.name == "decisiones_aplicadas.json":
            raise SystemExit("corte antes del ledger")
        return escribir(ruta, contenido)

    monkeypatch.setattr(acciones, "escribir_json_atomico", cortar)
    with pytest.raises(SystemExit):
        _ejecutar(capa, token)
    monkeypatch.setattr(acciones, "escribir_json_atomico", escribir)
    assert _fila(guia)["descripcion_material"] == LARGO
    assert not _vigentes(guia) and not espia_reporte
    # El mismo token recupera por el canal oficial y entonces sí se reconoce.
    r = _ejecutar(CapaAccionesOperacionales(guia["raiz"]), token)
    assert r["estado"] == "APLICADA", r
    assert _vigentes(guia)[ARCHIVO]["valor"] == LARGO
    assert espia_reporte and espia_reporte[-1]["proyectado"][ARCHIVO] == LARGO


def test_corte_tras_ledger_antes_del_reporte_se_completa_con_el_mismo_token(guia, espia_reporte, monkeypatch):
    capa = guia["b1"].capa
    token = _preview(capa, LARGO)
    monkeypatch.setattr(capa, "_regenerar_reporte", lambda: (_ for _ in ()).throw(SystemExit("corte antes del reporte")))
    with pytest.raises(SystemExit):
        _ejecutar(capa, token)
    # Asiento firme: la decisión ya es reconocible aunque falten reporte y auditoría.
    assert _vigentes(guia)[ARCHIVO]["decision_id"] == f"ACCION_OPERACIONAL:{token}"
    nueva = CapaAccionesOperacionales(guia["raiz"])
    assert not [a for a in nueva.auditoria() if a["token"] == token]
    r = _ejecutar(nueva, token)
    assert r["estado"] == "APLICADA", r
    assert espia_reporte[-1]["proyectado"][ARCHIVO] == LARGO
    assert token not in espia_reporte[-1]["aplicadas"]
    asientos = [a for a in _ledger(guia)["aplicaciones"] if a.get("decision_id") == f"ACCION_OPERACIONAL:{token}"]
    assert len(asientos) == 1
    assert len([a for a in nueva.auditoria() if a["token"] == token]) == 1


def test_reporte_fallido_no_deshace_la_decision_y_el_siguiente_la_publica(guia, espia_reporte, monkeypatch):
    capa = guia["b1"].capa
    token = _preview(capa, LARGO)
    original = reporte_viajes.generar_reporte_viajes
    monkeypatch.setattr(reporte_viajes, "generar_reporte_viajes",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("fallo del reporte")))
    r = _ejecutar(capa, token)
    assert r["estado"] == "APLICADA" and not r["revalidacion"]["reporte"]["regenerado"], r
    assert _vigentes(guia)[ARCHIVO]["valor"] == LARGO
    monkeypatch.setattr(reporte_viajes, "generar_reporte_viajes", original)
    # El siguiente reporte (cualquier origen) ve la misma decisión vigente.
    assert _proyeccion_material(_fila(guia), _ledger(guia)) == LARGO


def test_corte_tras_reporte_antes_de_auditar_se_cierra_idempotente(guia, espia_reporte, monkeypatch):
    capa = guia["b1"].capa
    token = _preview(capa, LARGO)
    monkeypatch.setattr(capa, "_auditar", lambda *a, **k: (_ for _ in ()).throw(SystemExit("corte antes de auditar")))
    with pytest.raises(SystemExit):
        _ejecutar(capa, token)
    assert espia_reporte[-1]["proyectado"][ARCHIVO] == LARGO
    nueva = CapaAccionesOperacionales(guia["raiz"])
    r = _ejecutar(nueva, token)
    assert r["estado"] == "APLICADA", r
    assert _ejecutar(nueva, token)["idempotente"]
    assert len([a for a in _ledger(guia)["aplicaciones"]
                if a.get("decision_id") == f"ACCION_OPERACIONAL:{token}"]) == 1


# --------------------------------------------- vigencia, reemplazo y documento


def test_segunda_correccion_reemplaza_y_solo_la_ultima_es_vigente(guia, espia_reporte):
    capa = guia["b1"].capa
    assert _ejecutar(capa, _preview(capa, CORTO))["estado"] == "APLICADA"
    token = _preview(capa, LARGO)
    assert _ejecutar(capa, token)["estado"] == "APLICADA"
    vigente = _vigentes(guia)[ARCHIVO]
    assert vigente["valor"] == LARGO and vigente["decision_id"] == f"ACCION_OPERACIONAL:{token}"
    assert espia_reporte[-1]["proyectado"][ARCHIVO] == LARGO


def test_fila_cambiada_despues_deja_de_ser_vigente(guia):
    capa = guia["b1"].capa
    assert _ejecutar(capa, _preview(capa, LARGO))["estado"] == "APLICADA"
    fila = dict(_fila(guia), descripcion_material="OTRO VALOR")
    assert material_confirmado_vigente(_ledger(guia), fila) is None


def test_correccion_de_otro_documento_no_se_reconoce(guia):
    capa = guia["b1"].capa
    assert _ejecutar(capa, _preview(capa, LARGO))["estado"] == "APLICADA"
    ledger = _ledger(guia)
    otras = [f for f in _filas(guia) if f["archivo"] != ARCHIVO]
    assert otras
    for fila in otras:
        # Aun copiando el mismo material en otra guía, no hereda la decisión.
        assert material_confirmado_vigente(ledger, dict(fila, descripcion_material=LARGO)) is None
    # Mismo número de guía, otro archivo (duplicado): tampoco.
    assert material_confirmado_vigente(ledger, dict(_fila(guia), archivo="otro.jpeg")) is None


@pytest.mark.parametrize("entrada,esperado", [
    ({"actor": "B1", "confirmado_por": "JAVIER"}, True),
    ({"actor": "JAVIER"}, True),  # asiento antiguo sin confirmante
    ({"actor": "B1", "confirmado_por": ""}, False),
    ({"actor": "B1", "confirmado_por": "ATLAS_AUTOMATICO"}, False),
    ({"actor": "ATLAS_REPARADOR"}, False),
])
def test_solo_confirmacion_humana(entrada, esperado):
    fila = {"archivo": "a.jpeg", "numero_guia": "1", "descripcion_material": "BARRAS"}
    ledger = {"aplicaciones": [{"tipo": "CORRECCION_DOCUMENTAL_OPERADOR", "campo": "descripcion_material",
                                "documento": {"archivo": "a.jpeg", "numero_guia": "1"},
                                "valor_corregido": "BARRAS", "decision_id": "x", **entrada}]}
    assert (material_confirmado_vigente(ledger, fila) is not None) is esperado


def test_ultima_correccion_automatica_anula_la_humana_anterior():
    fila = {"archivo": "a.jpeg", "numero_guia": "1", "descripcion_material": "BARRAS"}
    base = {"tipo": "CORRECCION_DOCUMENTAL_OPERADOR", "campo": "descripcion_material",
            "documento": {"archivo": "a.jpeg", "numero_guia": "1"}, "valor_corregido": "BARRAS"}
    ledger = {"aplicaciones": [{**base, "actor": "B1", "confirmado_por": "JAVIER"},
                               {**base, "actor": "ATLAS_AUTOMATICO"}]}
    assert material_confirmado_vigente(ledger, fila) is None


def test_asiento_antiguo_sin_archivo_por_guia_y_otros_tipos_ignorados():
    fila = {"archivo": "a.jpeg", "numero_guia": "1", "descripcion_material": "BARRAS"}
    antiguo = {"tipo": "CORRECCION_DOCUMENTAL_OPERADOR", "campo": "descripcion_material", "actor": "JAVIER",
               "documento": {"numero_guia": "1"}, "valor_corregido": "BARRAS"}
    assert material_confirmado_vigente({"aplicaciones": [antiguo]}, fila) is not None
    assert material_confirmado_vigente({"aplicaciones": [dict(antiguo, documento={"numero_guia": "2"})]}, fila) is None
    for otro in ({**antiguo, "tipo": "RECUPERACION_MATERIAL"}, {**antiguo, "campo": "peso_kg"}):
        assert material_confirmado_vigente({"aplicaciones": [otro]}, fila) is None
    assert material_confirmado_vigente({}, fila) is None
    assert material_confirmado_vigente({"aplicaciones": None}, fila) is None
