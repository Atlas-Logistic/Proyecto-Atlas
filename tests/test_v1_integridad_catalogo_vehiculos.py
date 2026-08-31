"""Bloque V1 -- INTEGRIDAD DEL CATÁLOGO DE VEHÍCULOS/PATENTES.

Causa raíz real confirmada por auditoría (catálogo real de producción,
25 vehículos): `migrar_v0_a_v1` promueve TODO lo que ya estaba en el
catálogo legacy a `estado_calidad=CONFIRMADO` con sólo una evidencia
`MIGRACION_LEGACY` -- nunca una revisión real. Eso permitió que una
patente mal leída por OCR ("BKYX63", 1 aparición histórica total,
0 en la operación real desde la infraestructura vigente) quedara
registrada como su propio vehículo "CONFIRMADO", pese a que el
catálogo YA reconoce -- vía `_CONFUSIONES_OCR`, calibrada
específicamente para este caso real (K/X, 13 guías de "BKYK63" mismo
chofer/RUT, incluida una del mismo día que la única guía de
"BKYX63") -- que es una confusión de trazo de "BKYK63" (302+
apariciones reales, GPS-corroboradas). Antes de este bloque, un
documento futuro que leyera "BKYX63" limpiamente habría resuelto
COINCIDENCIA_EXACTA contra el registro contaminado, en vez de
ALIAS contra el vehículo real -- el "error OCR convertido en verdad
sólo por estar en el catálogo" que este bloque cierra.

Este bloque NUNCA hardcodea BKYX63/BKYK63 en el código de producción
(`atlas_core/catalogo_vehiculos.py`) -- las dos funciones nuevas son
generales, reciben la patente y la justificación del llamador."""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from atlas_core.catalogo_vehiculos import (
    ErrorCatalogoVehiculos,
    ResultadoResolucionPatente,
    cargar_catalogo_vehiculos,
    fusionar_vehiculo_como_alias_ocr,
    resolver_patente,
    revisar_estado_calidad_vehiculo,
)

FECHA = datetime(2026, 8, 31, 12, 0, tzinfo=timezone.utc)


def _vehiculo(
    patente, *, tipo="TRACTO", calidad="CONFIRMADO", vigencia="ACTIVO",
    procedencia="CATALOGO_LEGACY", confirmado_por="", fecha_confirmacion="",
    evidencia_tipo="MIGRACION_LEGACY",
):
    return {
        "vehiculo_id": f"id-{patente}", "patente_canonica": patente, "tipo": tipo,
        "estado_calidad": calidad, "estado_vigencia": vigencia, "aliases": [],
        "evidencias": [{
            "tipo": evidencia_tipo, "identificador_fuente": "vehiculos.json",
            "referencia_hash": "", "campos_observados": {"patente": patente, "tipo": tipo},
            "fecha": "2026-08-14T02:26:07+00:00", "actor_proceso": "MIGRACION_V0_A_V1",
            "resultado": "SOPORTA",
        }],
        "procedencia": procedencia, "confirmado_por": confirmado_por,
        "fecha_confirmacion": fecha_confirmacion, "observaciones": "",
        "fecha_creacion": "2026-08-14T02:26:07+00:00", "fecha_modificacion": "2026-08-14T02:26:07+00:00",
    }


def _guardar(tmp_path, *registros):
    ruta = tmp_path / "vehiculos.json"
    ruta.write_text(json.dumps({"version": 1, "vehiculos": list(registros)}), encoding="utf-8")
    return ruta


# ============================================================
# fusionar_vehiculo_como_alias_ocr
# ============================================================


def test_fusion_pliega_la_sospechosa_como_alias_y_preserva_evidencia(tmp_path):
    """Reconstrucción real (sin hardcodear las patentes en producción):
    un registro legacy standalone ("BKYX63"-equivalente, 0 respaldo
    real) se pliega dentro de su confusión OCR calibrada ya CONFIRMADA
    con respaldo real ("BKYK63"-equivalente)."""
    ruta = _guardar(
        tmp_path,
        _vehiculo("BKYX63"),
        _vehiculo("BKYK63", confirmado_por="", fecha_confirmacion=""),
    )
    resultado = fusionar_vehiculo_como_alias_ocr(
        ruta, patente_sospechosa="BKYX63", patente_canonica="BKYK63",
        actor="AUDITORIA_V1", motivo="Auditoría V1: 0 apariciones reales post-infraestructura, "
        "confusión OCR calibrada K/X con respaldo real de BKYK63.",
        fecha=FECHA, referencia_hash="hash-auditoria",
    )
    assert resultado.patente_canonica == "BKYK63"
    assert "BKYX63" in resultado.aliases
    # Evidencia del origen preservada íntegra (nunca se pierde trazabilidad).
    tipos_evidencia = [e.tipo for e in resultado.evidencias]
    assert tipos_evidencia.count("MIGRACION_LEGACY") == 2  # una de cada lado
    assert "AUDITORIA_ALIAS_OCR" in tipos_evidencia
    evidencia_fusion = next(e for e in resultado.evidencias if e.tipo == "AUDITORIA_ALIAS_OCR")
    assert evidencia_fusion.campos_observados["alias"] == "BKYX63"
    assert evidencia_fusion.resultado == "SOPORTA"

    catalogo = cargar_catalogo_vehiculos(ruta)
    patentes = {v.patente_canonica for v in catalogo.vehiculos}
    assert "BKYX63" not in patentes  # ya no existe como vehículo standalone
    assert "BKYK63" in patentes
    assert len(catalogo.vehiculos) == 1


def test_fusion_corrige_la_resolucion_futura_de_la_patente_contaminada(tmp_path):
    """El bug real que este bloque cierra: ANTES de la fusión, un
    documento futuro que lea "BKYX63" limpiamente resuelve
    COINCIDENCIA_EXACTA contra el registro contaminado (el error OCR
    se trata como verdad sólo por estar en el catálogo). DESPUÉS,
    resuelve ALIAS contra el vehículo real."""
    ruta = _guardar(tmp_path, _vehiculo("BKYX63"), _vehiculo("BKYK63"))

    antes = resolver_patente(ruta, "BKYX63", tipo_esperado="TRACTO")
    assert antes.estado == "COINCIDENCIA_EXACTA"
    assert antes.valor_resultado == "BKYX63"  # <- el error OCR "confirmado" tal cual

    fusionar_vehiculo_como_alias_ocr(
        ruta, patente_sospechosa="BKYX63", patente_canonica="BKYK63",
        actor="AUDITORIA_V1", motivo="Auditoría V1", fecha=FECHA,
    )

    despues = resolver_patente(ruta, "BKYX63", tipo_esperado="TRACTO")
    assert despues.estado == "ALIAS"
    assert despues.valor_resultado == "BKYK63"  # <- ahora resuelve al vehículo real


def test_fusion_exige_confusion_ocr_calibrada_nunca_arbitraria(tmp_path):
    ruta = _guardar(tmp_path, _vehiculo("AA1111"), _vehiculo("ZZ9999"))
    with pytest.raises(ErrorCatalogoVehiculos, match="confusión OCR"):
        fusionar_vehiculo_como_alias_ocr(
            ruta, patente_sospechosa="AA1111", patente_canonica="ZZ9999",
            actor="AUDITORIA_V1", motivo="motivo", fecha=FECHA,
        )


def test_fusion_exige_que_el_destino_este_confirmado_y_activo(tmp_path):
    ruta = _guardar(
        tmp_path, _vehiculo("BKYX63"), _vehiculo("BKYK63", calidad="CANDIDATO"),
    )
    with pytest.raises(ErrorCatalogoVehiculos, match="CONFIRMADO\\+ACTIVO"):
        fusionar_vehiculo_como_alias_ocr(
            ruta, patente_sospechosa="BKYX63", patente_canonica="BKYK63",
            actor="AUDITORIA_V1", motivo="motivo", fecha=FECHA,
        )


def test_fusion_exige_mismo_tipo_de_vehiculo(tmp_path):
    ruta = _guardar(
        tmp_path, _vehiculo("BKYX63", tipo="TRACTO"), _vehiculo("BKYK63", tipo="CARRO"),
    )
    with pytest.raises(ErrorCatalogoVehiculos, match="mismo tipo"):
        fusionar_vehiculo_como_alias_ocr(
            ruta, patente_sospechosa="BKYX63", patente_canonica="BKYK63",
            actor="AUDITORIA_V1", motivo="motivo", fecha=FECHA,
        )


def test_fusion_exige_actor_y_motivo(tmp_path):
    ruta = _guardar(tmp_path, _vehiculo("BKYX63"), _vehiculo("BKYK63"))
    with pytest.raises(ErrorCatalogoVehiculos, match="actor"):
        fusionar_vehiculo_como_alias_ocr(
            ruta, patente_sospechosa="BKYX63", patente_canonica="BKYK63",
            actor="", motivo="motivo", fecha=FECHA,
        )
    with pytest.raises(ErrorCatalogoVehiculos, match="motivo"):
        fusionar_vehiculo_como_alias_ocr(
            ruta, patente_sospechosa="BKYX63", patente_canonica="BKYK63",
            actor="AUDITORIA_V1", motivo="", fecha=FECHA,
        )


def test_fusion_no_toca_vehiculos_no_relacionados(tmp_path):
    """Un tercer vehículo cualquiera del catálogo permanece byte a byte
    intacto -- la fusión nunca es una operación global."""
    ruta = _guardar(
        tmp_path, _vehiculo("BKYX63"), _vehiculo("BKYK63"),
        _vehiculo("SB6486", confirmado_por="JAVIER_MBT", fecha_confirmacion="2026-08-14T02:26:32+00:00"),
    )
    fusionar_vehiculo_como_alias_ocr(
        ruta, patente_sospechosa="BKYX63", patente_canonica="BKYK63",
        actor="AUDITORIA_V1", motivo="motivo", fecha=FECHA,
    )
    catalogo = cargar_catalogo_vehiculos(ruta)
    sb6486 = next(v for v in catalogo.vehiculos if v.patente_canonica == "SB6486")
    assert sb6486.confirmado_por == "JAVIER_MBT"
    assert len(sb6486.evidencias) == 1


# ============================================================
# revisar_estado_calidad_vehiculo
# ============================================================


def test_revision_degrada_confirmado_a_candidato_preserva_historial(tmp_path):
    """Reconstrucción real ("JF9565"-equivalente): 0 apariciones en la
    operación real bajo la infraestructura vigente, sólo presente en
    histórico pre-infraestructura ya desestimado -- se degrada de
    CONFIRMADO a CANDIDATO, nunca se borra."""
    ruta = _guardar(tmp_path, _vehiculo("JF9565"))
    resultado = revisar_estado_calidad_vehiculo(
        ruta, patente="JF9565", nuevo_estado_calidad="CANDIDATO",
        actor="AUDITORIA_V1", motivo="Auditoría V1: 0 apariciones en la operación real desde la "
        "infraestructura vigente; sólo histórico pre-infraestructura ya desestimado, sin par OCR "
        "confiable identificado. Sin evidencia de que sea falso -- se conserva como candidato.",
        fecha=FECHA, referencia_hash="hash-auditoria",
    )
    assert resultado.estado_calidad == "CANDIDATO"
    assert resultado.confirmado_por == ""
    assert resultado.fecha_confirmacion == ""
    tipos_evidencia = [e.tipo for e in resultado.evidencias]
    assert "MIGRACION_LEGACY" in tipos_evidencia  # el historial original nunca se pierde
    assert "AUDITORIA_REVISION_INTEGRIDAD" in tipos_evidencia

    catalogo = cargar_catalogo_vehiculos(ruta)
    assert catalogo.vehiculos[0].patente_canonica == "JF9565"  # sigue en el catálogo
    assert catalogo.homologables() == ()  # pero ya no participa de la homologación


def test_revision_no_borra_ni_desactiva_el_registro(tmp_path):
    ruta = _guardar(tmp_path, _vehiculo("JF9565"))
    revisar_estado_calidad_vehiculo(
        ruta, patente="JF9565", nuevo_estado_calidad="CANDIDATO",
        actor="AUDITORIA_V1", motivo="motivo", fecha=FECHA,
    )
    catalogo = cargar_catalogo_vehiculos(ruta)
    assert len(catalogo.vehiculos) == 1
    assert catalogo.vehiculos[0].estado_vigencia == "ACTIVO"


def test_revision_rechaza_estado_identico(tmp_path):
    ruta = _guardar(tmp_path, _vehiculo("JF9565"))
    with pytest.raises(ErrorCatalogoVehiculos, match="ya tiene ese estado"):
        revisar_estado_calidad_vehiculo(
            ruta, patente="JF9565", nuevo_estado_calidad="CONFIRMADO",
            actor="AUDITORIA_V1", motivo="motivo", fecha=FECHA,
        )


def test_revision_exige_actor_y_motivo(tmp_path):
    ruta = _guardar(tmp_path, _vehiculo("JF9565"))
    with pytest.raises(ErrorCatalogoVehiculos, match="actor"):
        revisar_estado_calidad_vehiculo(
            ruta, patente="JF9565", nuevo_estado_calidad="CANDIDATO", actor="", motivo="motivo", fecha=FECHA,
        )
    with pytest.raises(ErrorCatalogoVehiculos, match="motivo"):
        revisar_estado_calidad_vehiculo(
            ruta, patente="JF9565", nuevo_estado_calidad="CANDIDATO",
            actor="AUDITORIA_V1", motivo="", fecha=FECHA,
        )


def test_revision_patente_inexistente_falla_sin_escribir(tmp_path):
    ruta = _guardar(tmp_path, _vehiculo("JF9565"))
    contenido_antes = ruta.read_text(encoding="utf-8")
    with pytest.raises(ErrorCatalogoVehiculos, match="no existe"):
        revisar_estado_calidad_vehiculo(
            ruta, patente="ZZ0000", nuevo_estado_calidad="CANDIDATO",
            actor="AUDITORIA_V1", motivo="motivo", fecha=FECHA,
        )
    assert ruta.read_text(encoding="utf-8") == contenido_antes
