"""Bloque B1 EXPOSICIÓN -- traduce el resultado de B1 (Bloque B1
INVESTIGADOR, ya persistido en `resultado_atlas_ia_json`) a lenguaje
operacional dentro de la decisión `DESTINO_NO_RESUELTO` -- misma fuente
de verdad, sin memoria paralela."""
from __future__ import annotations

import json

from atlas_core.decisiones_pendientes import (
    detectar_decision_destino_no_resuelto,
    regenerar_decisiones_persistidas,
    resumen_hallazgo_b1,
)
from atlas_core.procesamiento_masivo import COLUMNAS


def _traza_b1(*, estado, clasificacion, explicacion, valor_propuesto="", evidencias_externas=()):
    return {
        "dominio": "DESTINO", "campo": "despachar_a_crudo", "llamada_realizada": True,
        "estado": estado, "clasificacion": clasificacion,
        "hipotesis": {"explicacion": explicacion, "valor_propuesto": valor_propuesto},
        "contexto_final": {"evidencias": [
            {"tipo_fuente": "EXTERNO", "referencias_fuente": [f"{t} <{u}>"]}
            for t, u in evidencias_externas
        ]},
    }


def _fila(**overrides):
    fila = {c: "" for c in COLUMNAS}
    fila.update({
        "numero_guia": "472037", "despachar_a_crudo": "VICUÑA MACKENNA 655",
        "obra_destino": "ING Y CONST FUNDAMENTA SPA", "planta_origen_id": "planta-1",
        "estado_ruta": "REQUIERE_REVISION", "motivo_ruta": "MULTIPLES_UBICACIONES_DISPERSAS(5)",
    })
    fila.update(overrides)
    return fila


def test_sin_resultado_atlas_ia_json_devuelve_none():
    assert resumen_hallazgo_b1(_fila(resultado_atlas_ia_json=""), dominio="DESTINO", campo="despachar_a_crudo") is None


def test_llamada_no_realizada_devuelve_none():
    fila = _fila(resultado_atlas_ia_json=json.dumps([
        {"dominio": "DESTINO", "campo": "despachar_a_crudo", "llamada_realizada": False},
    ]))
    assert resumen_hallazgo_b1(fila, dominio="DESTINO", campo="despachar_a_crudo") is None


def test_abstencion_sin_explicacion_ni_evidencia_devuelve_none():
    """Caso 7 -- B1 realmente no encontró nada útil."""
    fila = _fila(resultado_atlas_ia_json=json.dumps([
        _traza_b1(estado="ABSTENCION_IA", clasificacion="C_ABSTENCION", explicacion=""),
    ]))
    assert resumen_hallazgo_b1(fila, dominio="DESTINO", campo="despachar_a_crudo") is None


def test_caso_472037_evidencia_fuerte_no_confirmable_automaticamente():
    """Caso real 472037 -- evidencia externa real, pero `valor_propuesto`
    ("Sí") no tiene forma de dirección -- nunca se ofrece "Confirmar"
    sobre un valor así, aunque el hallazgo sí se muestra."""
    fila = _fila(resultado_atlas_ia_json=json.dumps([
        _traza_b1(
            estado="BLOQUEADO_POR_VALIDACION", clasificacion="D_BLOQUEO",
            explicacion="Ambas fuentes externas confirman que Vicuña Mackenna 655 existe y está asociada al proyecto Fundamenta en Santiago.",
            valor_propuesto="Sí",
            evidencias_externas=[("SNIFA", "https://snifa.sma.gob.cl/x"), ("Fundamenta", "https://fundamenta.cl/x")],
        ),
    ]))
    hallazgo = resumen_hallazgo_b1(fila, dominio="DESTINO", campo="despachar_a_crudo")
    assert hallazgo is not None
    assert "Fundamenta" in hallazgo["b1_resumen_hallazgo"]
    assert hallazgo["b1_propuesta"] == ""  # "Sí" no es confirmable
    assert "2 fuentes" in hallazgo["b1_evidencia_resumida"]
    assert hallazgo["b1_fuentes_resumidas"] == ["SNIFA", "Fundamenta"]
    assert hallazgo["b1_pregunta_humana"] == "¿Puede indicar la dirección real de entrega?"


def test_caso_472044_abstencion_con_hallazgo_util():
    """Caso real 472044 -- ABSTENCION honesta, pero con explicación e
    investigación reales que sí vale la pena mostrar."""
    fila = _fila(
        numero_guia="472044", despachar_a_crudo="PUERTA DEL SOL 83 LAS CONDES",
        motivo_ruta="SIN_ACCESO_VIAL", estado_ruta="SIN_ACCESO_VIAL",
        resultado_atlas_ia_json=json.dumps([
            _traza_b1(
                estado="ABSTENCION_IA", clasificacion="C_ABSTENCION",
                explicacion="Puerta del Sol 83 corresponde a una dirección real en Las Condes, pero ninguna fuente confirma el acceso vial requerido.",
                evidencias_externas=[("Edificio Puerta del Sol", "https://x.cl")],
            ),
        ]),
    )
    hallazgo = resumen_hallazgo_b1(fila, dominio="DESTINO", campo="despachar_a_crudo")
    assert hallazgo is not None
    assert hallazgo["b1_propuesta"] == ""
    assert hallazgo["b1_motivo_no_autoaplicable"].startswith("Atlas investigó")


def test_propuesta_con_numero_es_confirmable():
    fila = _fila(resultado_atlas_ia_json=json.dumps([
        _traza_b1(
            estado="RESUELTO_POR_IA", clasificacion="B_ASISTENCIA",
            explicacion="La dirección corregida es Vicuña Mackenna 655, Santiago.",
            valor_propuesto="Vicuña Mackenna 655, Santiago",
        ),
    ]))
    hallazgo = resumen_hallazgo_b1(fila, dominio="DESTINO", campo="despachar_a_crudo")
    assert hallazgo["b1_propuesta"] == "Vicuña Mackenna 655, Santiago"
    assert hallazgo["b1_pregunta_humana"] == "¿Confirma que este es el destino correcto?"


def test_detectar_decision_incluye_hallazgo_b1():
    fila = _fila(resultado_atlas_ia_json=json.dumps([
        _traza_b1(
            estado="ABSTENCION_IA", clasificacion="C_ABSTENCION",
            explicacion="Hallazgo real de prueba.", evidencias_externas=[("Fuente", "https://x.cl")],
        ),
    ]))
    decision = detectar_decision_destino_no_resuelto(archivo="472037.jpeg", fila=fila)
    assert decision is not None
    assert decision["contexto"]["b1_resumen_hallazgo"] == "Hallazgo real de prueba."


def test_regenerar_decisiones_refresca_hallazgo_de_decision_ya_publicada(tmp_path):
    """El hallazgo B1 puede aparecer DESPUÉS de que la tarjeta ya se
    publicó sin él -- `regenerar_decisiones_persistidas` debe
    refrescarlo sin cambiar el `decision_id` (nunca una tarjeta
    duplicada)."""
    import csv as _csv

    carpeta = tmp_path / "catalogos"; carpeta.mkdir()
    (carpeta / "clientes.json").write_text('{"version_formato": 1, "clientes": []}', encoding="utf-8")
    fila_sin_hallazgo = _fila(resultado_atlas_ia_json="")
    decision_vieja = detectar_decision_destino_no_resuelto(archivo="472037.jpeg", fila=fila_sin_hallazgo)
    assert "b1_resumen_hallazgo" not in decision_vieja["contexto"]

    fila_con_hallazgo = _fila(resultado_atlas_ia_json=json.dumps([
        _traza_b1(
            estado="ABSTENCION_IA", clasificacion="C_ABSTENCION",
            explicacion="Hallazgo nuevo tras investigar.", evidencias_externas=[("Fuente", "https://x.cl")],
        ),
    ]))
    dataset = tmp_path / "dataset.csv"
    with dataset.open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = _csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader(); escritor.writerow(fila_con_hallazgo)

    restantes = regenerar_decisiones_persistidas(
        decisiones=[decision_vieja], carpeta_catalogos=carpeta, ruta_dataset=dataset,
    )
    assert len(restantes) == 1
    assert restantes[0]["decision_id"] == decision_vieja["decision_id"]
    assert restantes[0]["contexto"]["b1_resumen_hallazgo"] == "Hallazgo nuevo tras investigar."
