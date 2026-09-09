"""Bloque GEOGRAFÍA 2B -- CICLO DE VIDA REAL DE INCOMPLETO_TECNICO.

INCOMPLETO_TECNICO deja de ser "quedó guardado y quizá algún día se
arregle": cada pendiente técnico tiene una `clase_fallo`, un
`estado_espera` explícito, una `causa_siguiente_accion` y una
`proxima_oportunidad` (fecha ISO real o null). Ningún caso queda en
limbo: converge a RESUELTO, a REQUIERE_REVISION con tarjeta real, o a
INCOMPLETO_TECNICO esperando una condición explícita no humana.
"""
from __future__ import annotations

import csv
import json
from datetime import datetime, timedelta, timezone

import pytest

from atlas_core import reconciliacion_estado_derivado as recon
from atlas_core.decisiones_pendientes import (
    MOTIVOS_DESTINO_TECNICO_AGOTABLE,
    UMBRAL_INTENTOS_TECNICOS_AGOTADOS,
    _guias_con_direccion_confirmada_por_humano,
    _guias_destino_terminado_por_humano,
    clasificar_fallo_tecnico,
    detectar_decision_destino_no_resuelto,
)
from atlas_core.procesamiento_masivo import COLUMNAS

RELOJ = lambda: datetime(2026, 9, 9, 12, 0, tzinfo=timezone.utc)


# ============================================================
# 1. CLASIFICACIÓN EXPLÍCITA DE FALLOS TÉCNICOS
# ============================================================


@pytest.mark.parametrize("motivo", [
    "SIN_CONEXION", "PROVEEDOR_NO_DISPONIBLE", "LIMITE_CUOTA", "RESPUESTA_INVALIDA",
    "GEOCODIFICACION_SIN_CONEXION", "GEOCODIFICACION_PROVEEDOR_NO_DISPONIBLE",
    "GEOCODIFICACION_LIMITE_CUOTA",
])
def test_clasifica_transitorio(motivo):
    assert clasificar_fallo_tecnico(motivo) == "TRANSITORIO"


@pytest.mark.parametrize("motivo", [
    "CONFIANZA_INSUFICIENTE", "COORDENADA_NO_CONFIRMADA", "COORDENADA_NO_CONFIRMADA(5)",
])
def test_clasifica_agotable(motivo):
    assert clasificar_fallo_tecnico(motivo) == "AGOTABLE"


@pytest.mark.parametrize("motivo", [
    "GEOCODIFICACION_NUMERO_INCOMPATIBLE: 15 != 1545",
    "GEOCODIFICACION_CONTRADICE_COMUNA_DOCUMENTAL: La Cisterna != Temuco",
    "MULTIPLES_UBICACIONES_DISPERSAS(5)",
    "GEOCODIFICACION_FUERA_DE_CHILE: Córdoba",
    "GEOCODIFICACION_DIRECCION_NO_ENCONTRADA",
    "UN_MOTIVO_NUEVO_NUNCA_VISTO",
])
def test_clasifica_determinista(motivo):
    assert clasificar_fallo_tecnico(motivo) == "DETERMINISTA"


# ============================================================
# 2/5. `_ciclo_vida_pendiente` -- estado de espera explícito y convergente
# ============================================================


def _registro(motivo, *, intentos=0, ultimo=None):
    return {
        "numero_guia": "1", "motivo_actual": motivo,
        "intentos_misma_evidencia": intentos,
        "ultimo_intento": ultimo,
    }


def _cv(motivo, *, intentos=0, ultimo=None, confirmada=False, terminado=False):
    return recon._ciclo_vida_pendiente(
        _registro(motivo, intentos=intentos, ultimo=ultimo),
        instante=RELOJ(),
        direccion_confirmada_por_humano=confirmada,
        destino_terminado_por_humano=terminado,
    )


def test_transitorio_dentro_del_maximo_espera_cooldown_con_fecha_real():
    ultimo = (RELOJ() - timedelta(hours=1)).isoformat()
    cv = _cv("GEOCODIFICACION_SIN_CONEXION", intentos=2, ultimo=ultimo)
    assert cv["clase_fallo"] == "TRANSITORIO"
    assert cv["estado_espera"] == "ESPERANDO_COOLDOWN"
    esperada = (datetime.fromisoformat(ultimo) + recon.COOLDOWN_REINTENTO_TRANSITORIO).isoformat()
    assert cv["proxima_oportunidad"] == esperada


def test_transitorio_agotado_espera_proveedor_sin_proxima():
    cv = _cv("GEOCODIFICACION_SIN_CONEXION", intentos=5, ultimo=RELOJ().isoformat())
    assert cv["estado_espera"] == "ESPERANDO_PROVEEDOR"
    assert cv["proxima_oportunidad"] is None


def test_determinista_con_accion_humana_espera_accion_humana():
    cv = _cv("GEOCODIFICACION_NUMERO_INCOMPATIBLE: 15 != 1545")
    assert cv["clase_fallo"] == "DETERMINISTA"
    assert cv["estado_espera"] == "ESPERANDO_ACCION_HUMANA"
    assert cv["proxima_oportunidad"] is None


def test_determinista_sin_accion_humana_util_espera_evidencia_nueva():
    cv = _cv("UN_MOTIVO_NUEVO_NUNCA_VISTO")
    assert cv["estado_espera"] == "ESPERANDO_EVIDENCIA_NUEVA"


def test_direccion_confirmada_por_humano_nunca_re_pregunta():
    # Aunque el motivo tenga acción humana asociada, si el humano YA
    # confirmó la dirección se queda ESPERANDO_EVIDENCIA_NUEVA -- nunca
    # una tarjeta repetida (spec 2/7).
    cv = _cv("GEOCODIFICACION_NUMERO_INCOMPATIBLE: 15 != 1545", confirmada=True)
    assert cv["estado_espera"] == "ESPERANDO_EVIDENCIA_NUEVA"
    assert "CONFIRMADA_POR_HUMANO" in cv["causa_siguiente_accion"]


def test_destino_terminado_por_humano_queda_agotado():
    cv = _cv("MULTIPLES_UBICACIONES_DISPERSAS(5)", terminado=True)
    assert cv["estado_espera"] == "AGOTADO"


def test_agotable_dentro_del_maximo_espera_cooldown():
    ultimo = (RELOJ() - timedelta(hours=1)).isoformat()
    cv = _cv("CONFIANZA_INSUFICIENTE", intentos=1, ultimo=ultimo)
    assert cv["clase_fallo"] == "AGOTABLE"
    assert cv["estado_espera"] == "ESPERANDO_COOLDOWN"
    assert cv["proxima_oportunidad"] == (
        datetime.fromisoformat(ultimo) + recon.INTERVALO_REINTENTO
    ).isoformat()


def test_agotable_agotado_converge_a_accion_humana():
    cv = _cv("CONFIANZA_INSUFICIENTE", intentos=UMBRAL_INTENTOS_TECNICOS_AGOTADOS)
    assert cv["estado_espera"] == "ESPERANDO_ACCION_HUMANA"


# ============================================================
# Helpers de ledger
# ============================================================


def _ledger(tmp_path, aplicaciones):
    ruta = tmp_path / "decisiones_aplicadas.json"
    ruta.write_text(json.dumps({"aplicaciones": aplicaciones}), encoding="utf-8")
    return ruta


def test_guias_direccion_confirmada_lee_registrar_direccion():
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        ruta = _ledger(Path(tmp), [
            {"tipo": "DESTINO_NO_RESUELTO", "accion": "REGISTRAR_DIRECCION",
             "documento": {"numero_guia": "464784"}},
            {"tipo": "DESTINO_NO_RESUELTO", "accion": "NO_PUEDO_DETERMINAR",
             "documento": {"numero_guia": "999"}},
        ])
        assert _guias_con_direccion_confirmada_por_humano(ruta) == frozenset({"464784"})
        assert _guias_destino_terminado_por_humano(ruta) == frozenset({"999"})


def test_ledger_ausente_o_corrupto_es_frozenset_vacio(tmp_path):
    assert _guias_con_direccion_confirmada_por_humano(tmp_path / "no_existe.json") == frozenset()
    (tmp_path / "roto.json").write_text("{no json", encoding="utf-8")
    assert _guias_destino_terminado_por_humano(tmp_path / "roto.json") == frozenset()


# ============================================================
# 2. CONFIANZA_INSUFICIENTE no queda huérfana + guard de dirección humana
# ============================================================


def _fila_destino(**extra):
    fila = {c: "" for c in COLUMNAS}
    fila.update({
        "archivo": "g.jpeg", "numero_guia": "464784", "numero_transporte": "T1",
        "planta_origen_id": "p1", "despachar_a_crudo": "URUGUAY 15",
        "estado_ruta": "REQUIERE_REVISION", "motivo_ruta": "CONFIANZA_INSUFICIENTE",
        "obra_destino": "OBRA", "cliente": "CLIENTE",
    })
    fila.update(extra)
    return fila


def test_confianza_insuficiente_agotada_genera_tarjeta(tmp_path):
    decision = detectar_decision_destino_no_resuelto(
        archivo="g.jpeg", fila=_fila_destino(), carpeta_catalogos=tmp_path,
        intentos_misma_evidencia=UMBRAL_INTENTOS_TECNICOS_AGOTADOS,
    )
    assert decision is not None
    assert decision["tipo"] == "DESTINO_NO_RESUELTO"
    assert "CONFIANZA_INSUFICIENTE" in decision["motivos"]


def test_confianza_insuficiente_no_agotada_todavia_no_pregunta(tmp_path):
    decision = detectar_decision_destino_no_resuelto(
        archivo="g.jpeg", fila=_fila_destino(), carpeta_catalogos=tmp_path,
        intentos_misma_evidencia=UMBRAL_INTENTOS_TECNICOS_AGOTADOS - 1,
    )
    assert decision is None


def test_direccion_confirmada_por_humano_no_regenera_tarjeta(tmp_path):
    decision = detectar_decision_destino_no_resuelto(
        archivo="g.jpeg", fila=_fila_destino(), carpeta_catalogos=tmp_path,
        intentos_misma_evidencia=UMBRAL_INTENTOS_TECNICOS_AGOTADOS,
        guias_direccion_confirmada=frozenset({"464784"}),
    )
    assert decision is None


def test_forzar_ignora_el_guard_de_direccion_confirmada(tmp_path):
    decision = detectar_decision_destino_no_resuelto(
        archivo="g.jpeg", fila=_fila_destino(), carpeta_catalogos=tmp_path,
        guias_direccion_confirmada=frozenset({"464784"}), forzar=True,
    )
    assert decision is not None


# ============================================================
# `_falta_tarjeta_destino_accionable` -- AGOTABLE agotado dispara
# ============================================================


def _dataset_pendiente(tmp_path, *, motivo):
    actual = tmp_path / "operacion" / "actual"
    actual.mkdir(parents=True, exist_ok=True)
    dataset = actual / "analisis_completo_guias.csv"
    fila = {c: "" for c in COLUMNAS}
    fila.update({
        "archivo": "g.jpeg", "numero_guia": "464784", "numero_transporte": "T1",
        "indicador_revision": "OK", "planta_origen_id": "p1",
        "despachar_a_crudo": "URUGUAY 15", "estado_ruta": "REQUIERE_REVISION",
        "motivo_ruta": motivo, "obra_destino": "OBRA", "cliente": "CLIENTE",
    })
    with dataset.open("w", newline="", encoding="utf-8-sig") as archivo:
        w = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        w.writeheader(); w.writerow(fila)
    decisiones = actual / "decisiones_pendientes.json"
    decisiones.write_text('{"decisiones": []}', encoding="utf-8")
    return dataset, decisiones, actual


def test_falta_tarjeta_dispara_para_confianza_insuficiente_agotada(tmp_path):
    dataset, decisiones, actual = _dataset_pendiente(tmp_path, motivo="CONFIANZA_INSUFICIENTE")
    # sin intentos agotados -> no dispara todavía
    assert recon._falta_tarjeta_destino_accionable(dataset, decisiones) is False
    (actual / recon.NOMBRE_PENDIENTES_TECNICOS).write_text(json.dumps({
        "pendientes": [{"numero_guia": "464784",
                        "intentos_misma_evidencia": UMBRAL_INTENTOS_TECNICOS_AGOTADOS}],
    }), encoding="utf-8")
    assert recon._falta_tarjeta_destino_accionable(dataset, decisiones) is True


def test_falta_tarjeta_no_dispara_si_el_humano_ya_confirmo(tmp_path):
    dataset, decisiones, actual = _dataset_pendiente(tmp_path, motivo="CONFIANZA_INSUFICIENTE")
    (actual / recon.NOMBRE_PENDIENTES_TECNICOS).write_text(json.dumps({
        "pendientes": [{"numero_guia": "464784",
                        "intentos_misma_evidencia": UMBRAL_INTENTOS_TECNICOS_AGOTADOS}],
    }), encoding="utf-8")
    _ledger(actual, [{"tipo": "DESTINO_NO_RESUELTO", "accion": "REGISTRAR_DIRECCION",
                      "documento": {"numero_guia": "464784"}}])
    assert recon._falta_tarjeta_destino_accionable(dataset, decisiones) is False


# ============================================================
# 8. MIGRACIÓN / COMPATIBILIDAD -- registro viejo sigue funcionando
# ============================================================


def _entorno_reconciliacion(tmp_path, *, motivo, pendientes_previos=None, version=None):
    from atlas_core.almacenamiento_portable import escribir_estado_operacion

    actual = tmp_path / "operacion" / "actual"
    actual.mkdir(parents=True)
    dataset = actual / "analisis_completo_guias.csv"
    fila = {c: "" for c in COLUMNAS}
    fila.update({
        "archivo": "g.jpeg", "numero_guia": "99", "numero_transporte": "T99",
        "indicador_revision": "OK", "estado_operacional": "REQUIERE_REVISION",
        "planta_origen_id": "p1", "despachar_a_crudo": "CALLE 123",
        "estado_ruta": "REQUIERE_REVISION", "motivo_ruta": motivo,
        "cliente": "CLIENTE", "obra_destino": "OBRA",
    })
    with dataset.open("w", newline="", encoding="utf-8-sig") as archivo:
        w = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        w.writeheader(); w.writerow(fila)
    (actual / "decisiones_pendientes.json").write_text('{"decisiones": []}', encoding="utf-8")
    (tmp_path / "catalogos_privados").mkdir()
    if pendientes_previos is not None:
        (actual / recon.NOMBRE_PENDIENTES_TECNICOS).write_text(
            json.dumps({"pendientes": pendientes_previos}), encoding="utf-8"
        )
    reporte = tmp_path / "reportes" / "anterior"; reporte.mkdir(parents=True)
    escribir_estado_operacion(
        reporte_vigente=reporte, dataset_operacional=dataset,
        decisiones_pendientes=actual / "decisiones_pendientes.json", raiz=tmp_path,
        reloj=RELOJ,
        **({"version_estado_derivado": version} if version is not None else {}),
    )
    return dataset, actual


def _stub_revalidadores(monkeypatch):
    def _reportar(_dataset, salida, **kwargs):
        salida.mkdir(parents=True)
        (salida / "viajes.csv").write_text("estado\nINCOMPLETO_TECNICO\n", encoding="utf-8")
        return {"totales": {"viajes": 1}}
    monkeypatch.setattr(recon, "generar_reporte_viajes", _reportar)


def test_registro_viejo_de_pendientes_tecnicos_se_migra_sin_perder_historial(tmp_path, monkeypatch):
    """Un `pendientes_tecnicos.json` previo a 2B (sin `clase_fallo` ni
    `estado_espera`) sigue siendo legible: se conservan `intentos_misma_
    evidencia` e `historial_resultados`, y se añaden los campos nuevos."""
    historial = [{"fecha": "2026-08-01T00:00:00+00:00", "resultado": "CONFIANZA_INSUFICIENTE"}]
    dataset, actual = _entorno_reconciliacion(
        tmp_path, motivo="CONFIANZA_INSUFICIENTE",
        pendientes_previos=[{
            "numero_guia": "99",
            "motivo_actual": "CONFIANZA_INSUFICIENTE",
            "huella_datos": recon._huella_ruta({
                "planta_origen_id": "p1", "despachar_a_crudo": "CALLE 123",
                "cliente": "CLIENTE", "obra_destino": "OBRA", "destino_id": "",
                "motivo_ruta": "CONFIANZA_INSUFICIENTE", "resultado_atlas_ia_json": "",
            }),
            "intentos_misma_evidencia": 2,
            "ultimo_intento": "2026-08-01T00:00:00+00:00",
            "ultimo_resultado": "CONFIANZA_INSUFICIENTE",
            "historial_resultados": historial,
            "proxima_oportunidad": "ARRANQUE_TRAS_24H_O_CAMBIO_DE_EVIDENCIA",
            "escalamiento": "REINTENTO_DEPENDENCIA",
        }],
    )
    _stub_revalidadores(monkeypatch)
    # migración: sube de una versión anterior a la vigente
    monkeypatch.setattr(recon, "RULESET_VERSION", recon.RULESET_VERSION)

    recon.reconciliar_estado_derivado(raiz_atlas=tmp_path, reloj=RELOJ)
    pend = json.loads((actual / recon.NOMBRE_PENDIENTES_TECNICOS).read_text())["pendientes"]
    assert len(pend) == 1
    reg = pend[0]
    assert reg["historial_resultados"][0] == historial[0]  # historial no se pierde
    assert reg["intentos_misma_evidencia"] >= 2  # nunca se resetea a ciegas
    assert reg["clase_fallo"] == "AGOTABLE"
    assert reg["estado_espera"] in {
        "ESPERANDO_COOLDOWN", "ESPERANDO_ACCION_HUMANA", "ESPERANDO_EVIDENCIA_NUEVA",
    }
    assert "causa_siguiente_accion" in reg


def test_determinista_no_se_reintenta_solo_por_paso_del_tiempo(tmp_path, monkeypatch):
    """Un DETERMINISTA con un intento ya hecho y `ultimo_intento` viejo NO
    vuelve a reintentarse sólo porque pasó el cooldown -- sólo un cambio
    de evidencia (huella) o de reglas lo reactiva."""
    huella = recon._huella_ruta({
        "planta_origen_id": "p1", "despachar_a_crudo": "CALLE 123", "cliente": "CLIENTE",
        "obra_destino": "OBRA", "destino_id": "",
        "motivo_ruta": "MULTIPLES_UBICACIONES_DISPERSAS(5)", "resultado_atlas_ia_json": "",
    })
    dataset, actual = _entorno_reconciliacion(
        tmp_path, motivo="MULTIPLES_UBICACIONES_DISPERSAS(5)",
        version=recon.RULESET_VERSION,  # sin migración
        pendientes_previos=[{
            "numero_guia": "99", "motivo_actual": "MULTIPLES_UBICACIONES_DISPERSAS(5)",
            "huella_datos": huella, "intentos_misma_evidencia": 1,
            "ultimo_intento": (RELOJ() - timedelta(days=30)).isoformat(),
            "ultimo_resultado": "MULTIPLES_UBICACIONES_DISPERSAS(5)",
            "historial_resultados": [],
        }],
    )
    _stub_revalidadores(monkeypatch)
    llamadas = {"recuperar": 0}

    def _recuperar(**kwargs):
        llamadas["recuperar"] += 1
        return {"guias_actualizadas": []}
    monkeypatch.setattr(recon, "revalidar_ruta_sin_destino_calculado_sin_ocr", _recuperar)

    # Sin migración, sin cambio de evidencia y motivo DETERMINISTA ->
    # nada que reintentar por tiempo. Sí entra al bloque igualmente (para
    # publicar la tarjeta accionable), pero el reintento técnico no corre.
    recon.reconciliar_estado_derivado(raiz_atlas=tmp_path, reloj=RELOJ)
    assert llamadas["recuperar"] == 0


def test_segunda_reconciliacion_inmediata_es_idempotente(tmp_path, monkeypatch):
    dataset, actual = _entorno_reconciliacion(tmp_path, motivo="GEOCODIFICACION_SIN_CONEXION")
    _stub_revalidadores(monkeypatch)
    monkeypatch.setattr(
        recon, "revalidar_ruta_sin_destino_calculado_sin_ocr",
        lambda **k: {"guias_actualizadas": []},
    )
    primera = recon.reconciliar_estado_derivado(raiz_atlas=tmp_path, reloj=RELOJ)
    pend_1 = (actual / recon.NOMBRE_PENDIENTES_TECNICOS).read_text()
    segunda = recon.reconciliar_estado_derivado(raiz_atlas=tmp_path, reloj=RELOJ)
    pend_2 = (actual / recon.NOMBRE_PENDIENTES_TECNICOS).read_text()
    assert primera["reconciliado"] is True
    # nada cambió entre corridas: la segunda no reintenta (cooldown 6h) y
    # el archivo de pendientes queda igual salvo el timestamp de cabecera.
    assert json.loads(pend_1)["pendientes"] == json.loads(pend_2)["pendientes"]
