from datetime import datetime, timezone
from dataclasses import replace

import pytest

from atlas_core.clasificacion_documental import evaluar_incidencia, simular_evaluaciones
from atlas_core.confirmacion_documental_humana import AlmacenConfirmacionesDocumentales
from atlas_core.incidencias_documentales import AlmacenIncidenciasDocumentales, ClasificacionDocumental


FECHA = datetime(2026, 10, 1, tzinfo=timezone.utc)


def _incidencia(tmp_path, guia="464264", documental="JD6659", canonico="JD8659"):
    return AlmacenIncidenciasDocumentales(tmp_path / "incidencias.json").registrar(
        contexto="X", numero_guia=guia, numero_transporte="T", campo="patente_rampla",
        valor_documental=documental, valor_canonico=canonico,
        tipo_incidencia="PATENTE_DOCUMENTAL_INCORRECTA", evidencia=("OCR_OBSERVADO",), fecha=FECHA,
    )


def test_confirmacion_humana_explicita_proyecta_documental_confirmada_e_idempotente(tmp_path):
    incidencia = _incidencia(tmp_path)
    almacen = AlmacenConfirmacionesDocumentales(tmp_path / "confirmaciones.json")
    primera = almacen.confirmar(incidencia=incidencia, numero_guia="464264", archivo="464264.jpeg",
                                actor="JAVIER_MBT", fecha=FECHA, procedencia=("HASH:abc",))
    segunda = almacen.confirmar(incidencia=incidencia, numero_guia="464264", archivo="464264.jpeg",
                                actor="JAVIER_MBT", fecha=FECHA, procedencia=("HASH:abc",))
    assert primera.confirmacion_id == segunda.confirmacion_id
    assert len(almacen.listar()) == 1
    assert evaluar_incidencia(incidencia, confirmaciones=almacen.listar()).clasificacion is ClasificacionDocumental.DOCUMENTAL_CONFIRMADA


def test_guia_incorrecta_o_valor_faltante_se_abstienen(tmp_path):
    almacen = AlmacenConfirmacionesDocumentales(tmp_path / "confirmaciones.json")
    with pytest.raises(ValueError):
        almacen.confirmar(incidencia=_incidencia(tmp_path), numero_guia="OTRA", archivo="464264.jpeg", actor="J", fecha=FECHA)
    with pytest.raises(ValueError):
        almacen.confirmar(incidencia=replace(_incidencia(tmp_path), valor_documental=""), numero_guia="464264", archivo="464264.jpeg", actor="J", fecha=FECHA)


def test_confirmacion_conserva_historial_tras_relectura(tmp_path):
    incidencia = _incidencia(tmp_path)
    almacen = AlmacenConfirmacionesDocumentales(tmp_path / "confirmaciones.json")
    almacen.confirmar(incidencia=incidencia, numero_guia="464264", archivo="464264.jpeg", actor="J", fecha=FECHA)
    assert evaluar_incidencia(incidencia, {"patente_rampla": "JD8659"}, almacen.listar()).vigente_documental
    assert len(almacen.listar()) == 1


def test_simulacion_cinco_confirmaciones_sube_solo_cinco_sin_hardcodear_produccion(tmp_path):
    incidencias = [_incidencia(tmp_path, guia=str(100 + n), documental=f"A{n}", canonico=f"B{n}") for n in range(5)]
    almacen = AlmacenConfirmacionesDocumentales(tmp_path / "confirmaciones.json")
    for incidencia in incidencias:
        almacen.confirmar(incidencia=incidencia, numero_guia=incidencia.numero_guia,
                         archivo=f"{incidencia.numero_guia}.jpeg", actor="J", fecha=FECHA)
    simulacion = simular_evaluaciones(incidencias, [], almacen.listar())
    assert simulacion["conteos"] == {"DOCUMENTAL_CONFIRMADA": 5}
