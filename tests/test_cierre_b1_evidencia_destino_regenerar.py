"""Bloque CIERRE B1 EVIDENCIA DESTINO (Codex 472623/472624).

Causa raíz real: una decisión `DESTINO_NO_RESUELTO` con el motivo
sintético `OBRA_AUSENTE_BLOQUEA_RUTEO` (Bloque BLOQUEO PREVIO AL RUTEO)
nunca corresponde a un `motivo_ruta` real -- ningún mecanismo de
`regenerar_decisiones_persistidas` la reconocía como obsoleta, así que
seguía viva PARA SIEMPRE incluso después de que B1 aceptara el valor de
`despachar_a_crudo` con evidencia real -- y mientras siguiera viva,
`_pendientes_ruta` excluía la guía de todo reintento automático de
ruteo: bloqueo circular real (472623/472624)."""
from __future__ import annotations

import csv
import json

from atlas_core.decisiones_pendientes import crear_decision, regenerar_decisiones_persistidas
from atlas_core.procesamiento_masivo import COLUMNAS


def _fila_csv(**overrides):
    fila = {c: "" for c in COLUMNAS}
    fila.update({
        "archivo": "sim.jpg", "estado_procesamiento": "OK", "numero_guia": "SIM-1",
        "numero_transporte": "T-SIM-1", "fecha": "26-08-2026", "chofer": "CHOFER TEST",
        "cliente": "CLIENTE TEST", "obra_destino": "No encontrado",
        "patente_tracto": "AB1234", "indicador_revision": "OK",
        "despachar_a_crudo": "SAN LUIS 1201 QUILICURA",
        "planta_origen_id": "planta-1",
    })
    fila.update(overrides)
    return fila


def _escribir_csv(ruta, filas):
    with ruta.open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader()
        escritor.writerows(filas)


def _decision_obra_ausente_bloquea_ruteo(**overrides):
    datos = {
        "tipo": "DESTINO_NO_RESUELTO", "entidad": "DESTINO", "archivo": "sim.jpg",
        "numero_guia": "SIM-1", "numero_transporte": "T-SIM-1", "campo": "despachar_a_crudo",
        "valor_documental": "SAN LUIS 1201 QUILICURA", "valor_normalizado": "",
        "identidad_resuelta": None, "candidatos": [], "motivos": ["OBRA_AUSENTE_BLOQUEA_RUTEO"],
        "evidencias": [], "acciones_permitidas": ["REGISTRAR_DIRECCION", "NO_PUEDO_DETERMINAR", "POSPONER"],
    }
    datos.update(overrides)
    return crear_decision(**datos)


def _traza_destino(*, aceptada: bool):
    return [{
        "campo": "despachar_a_crudo", "dominio": "DESTINO",
        "aplicado_operacionalmente": False,
        "estado": "RESUELTO_POR_IA" if aceptada else "BLOQUEADO_POR_VALIDACION",
        "validacion": {"aceptada": aceptada, "motivo_rechazo": "" if aceptada else "VALOR_NO_RESPALDADO_POR_EVIDENCIA"},
    }]


def test_tarjeta_obra_ausente_bloquea_ruteo_se_retira_cuando_b1_acepta_destino(tmp_path):
    dataset = tmp_path / "analisis_completo_guias.csv"
    _escribir_csv(dataset, [_fila_csv(
        resultado_atlas_ia_json=json.dumps(_traza_destino(aceptada=True)),
    )])
    decision = _decision_obra_ausente_bloquea_ruteo()

    vigentes = regenerar_decisiones_persistidas(
        decisiones=[decision], carpeta_catalogos=tmp_path / "catalogos", ruta_dataset=dataset,
    )

    assert vigentes == []


def test_tarjeta_obra_ausente_bloquea_ruteo_se_conserva_sin_evidencia_b1_aceptada(tmp_path):
    """Control -- sin evidencia B1 aceptada (o sin traza en absoluto), la
    pregunta sigue siendo real: nunca se retira sin motivo."""
    dataset = tmp_path / "analisis_completo_guias.csv"
    _escribir_csv(dataset, [_fila_csv(resultado_atlas_ia_json="")])
    decision = _decision_obra_ausente_bloquea_ruteo()

    vigentes = regenerar_decisiones_persistidas(
        decisiones=[decision], carpeta_catalogos=tmp_path / "catalogos", ruta_dataset=dataset,
    )

    assert len(vigentes) == 1
    assert vigentes[0]["decision_id"] == decision["decision_id"]


def test_tarjeta_obra_ausente_bloquea_ruteo_se_conserva_si_b1_rechazo_evidencia(tmp_path):
    """Control -- traza presente pero B1 RECHAZÓ el valor (evidencia
    insuficiente): la pregunta sigue siendo real."""
    dataset = tmp_path / "analisis_completo_guias.csv"
    _escribir_csv(dataset, [_fila_csv(
        resultado_atlas_ia_json=json.dumps(_traza_destino(aceptada=False)),
    )])
    decision = _decision_obra_ausente_bloquea_ruteo()

    vigentes = regenerar_decisiones_persistidas(
        decisiones=[decision], carpeta_catalogos=tmp_path / "catalogos", ruta_dataset=dataset,
    )

    assert len(vigentes) == 1


def test_otro_motivo_destino_no_resuelto_nunca_se_retira_por_este_mecanismo(tmp_path):
    """Control -- una decisión DESTINO_NO_RESUELTO con un motivo REAL
    (no sintético) nunca se retira por esta vía nueva, aunque B1 acepte
    el valor -- ese motivo sigue gobernado por su propio mecanismo de
    obsolescencia (motivo_ruta), no por éste."""
    dataset = tmp_path / "analisis_completo_guias.csv"
    _escribir_csv(dataset, [_fila_csv(
        motivo_ruta="GEOCODIFICACION_DEMASIADO_GENERICA",
        resultado_atlas_ia_json=json.dumps(_traza_destino(aceptada=True)),
    )])
    decision = _decision_obra_ausente_bloquea_ruteo(motivos=["GEOCODIFICACION_DEMASIADO_GENERICA"])

    vigentes = regenerar_decisiones_persistidas(
        decisiones=[decision], carpeta_catalogos=tmp_path / "catalogos", ruta_dataset=dataset,
    )

    assert len(vigentes) == 1
