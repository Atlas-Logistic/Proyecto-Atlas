"""Incidencias Documentales -- errores del CONTENIDO humano/documental,
nunca de la calidad de imagen o de una lectura OCR ambigua. Esta
distinción está estructuralmente protegida aquí: `MOTIVOS_NUNCA_INCIDENCIA`
existe como lista positiva de lo que NUNCA debe registrarse, y los tests
de este archivo verifican ambos lados de la frontera."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from atlas_core.incidencias_documentales import (
    ClasificacionDocumental,
    MOTIVO_CALIDAD_DOCUMENTAL_O_IMAGEN, MOTIVO_PROBLEMA_LECTURA, MOTIVOS_NUNCA_INCIDENCIA,
    TIPO_CAMPO_DOCUMENTAL_INCORRECTO, TIPO_IDENTIDAD_CLIENTE_INCONSISTENTE,
    TIPO_PATENTE_DOCUMENTAL_INCORRECTA,
    AlmacenIncidenciasDocumentales, EstadoIncidencia, ErrorIncidenciasDocumentales,
)
from atlas_core.clasificacion_documental import evaluar_incidencia
from atlas_core.aplicacion_decisiones import _confirma_discrepancia_documental, _emitir_incidencia_documental_confirmada

FECHA = datetime(2026, 8, 19, tzinfo=timezone.utc)


def _almacen(tmp_path):
    return AlmacenIncidenciasDocumentales(tmp_path / "incidencias_documentales.json")


def test_registrar_incidencia_persiste_y_se_puede_releer(tmp_path):
    almacen = _almacen(tmp_path)
    incidencia = almacen.registrar(
        contexto="EBEMA SA", numero_guia="1", numero_transporte="T-1", campo="cliente",
        valor_documental="PPP CONSTRUCCIONES", valor_canonico="EBEMA SA",
        tipo_incidencia=TIPO_IDENTIDAD_CLIENTE_INCONSISTENTE, evidencia=("RUT_CANONICO_COINCIDE",),
        fecha=FECHA, fuente_resolucion="MOTOR_EVIDENCIA_CLIENTES",
    )
    assert incidencia.estado == EstadoIncidencia.DETECTADA.value
    releida = AlmacenIncidenciasDocumentales(almacen.ruta).listar()
    assert len(releida) == 1
    assert releida[0].incidencia_id == incidencia.incidencia_id


def test_registrar_la_misma_incidencia_dos_veces_es_idempotente(tmp_path):
    almacen = _almacen(tmp_path)
    kwargs = dict(
        contexto="EBEMA SA", numero_guia="1", numero_transporte="T-1", campo="cliente",
        valor_documental="PPP CONSTRUCCIONES", valor_canonico="EBEMA SA",
        tipo_incidencia=TIPO_IDENTIDAD_CLIENTE_INCONSISTENTE, evidencia=(), fecha=FECHA,
    )
    almacen.registrar(**kwargs)
    almacen.registrar(**kwargs)
    assert len(almacen.listar()) == 1


def test_valor_documental_igual_a_canonico_no_es_incidencia(tmp_path):
    """Si el documento y el canónico coinciden, no hay nada que registrar
    -- protege contra registrar "incidencias" vacías por error de
    llamada."""
    almacen = _almacen(tmp_path)
    with pytest.raises(ErrorIncidenciasDocumentales):
        almacen.registrar(
            contexto="EBEMA SA", numero_guia="1", numero_transporte="T-1", campo="cliente",
            valor_documental="EBEMA SA", valor_canonico="EBEMA SA",
            tipo_incidencia=TIPO_IDENTIDAD_CLIENTE_INCONSISTENTE, evidencia=(), fecha=FECHA,
        )


def test_listar_filtra_por_estado(tmp_path):
    almacen = _almacen(tmp_path)
    almacen.registrar(
        contexto="A", numero_guia="1", numero_transporte="T-1", campo="cliente",
        valor_documental="X", valor_canonico="Y", tipo_incidencia=TIPO_IDENTIDAD_CLIENTE_INCONSISTENTE,
        evidencia=(), fecha=FECHA, estado=EstadoIncidencia.CONFIRMADA,
    )
    almacen.registrar(
        contexto="A", numero_guia="2", numero_transporte="T-2", campo="patente_tracto",
        valor_documental="XF3662", valor_canonico="XF3629", tipo_incidencia=TIPO_PATENTE_DOCUMENTAL_INCORRECTA,
        evidencia=(), fecha=FECHA, estado=EstadoIncidencia.DETECTADA,
    )
    assert len(almacen.listar(estado=EstadoIncidencia.CONFIRMADA.value)) == 1
    assert len(almacen.listar(estado=EstadoIncidencia.DETECTADA.value)) == 1
    assert len(almacen.listar()) == 2


# ============================================================
# La frontera obligatoria: error OCR/calidad de imagen != incidencia
# documental. No hay una función que "decida" esto automáticamente en
# este módulo (la decisión vive en cada motor de evidencia, que nunca
# debe invocar `registrar()` para estos casos) -- lo que este test
# protege es que el vocabulario de "nunca incidencia" existe, está
# separado del vocabulario real de incidencias, y no se solapan.
# ============================================================


def test_motivos_nunca_incidencia_no_se_solapan_con_tipos_de_incidencia_reales():
    tipos_reales = {TIPO_IDENTIDAD_CLIENTE_INCONSISTENTE, TIPO_PATENTE_DOCUMENTAL_INCORRECTA}
    assert not (set(MOTIVOS_NUNCA_INCIDENCIA) & tipos_reales)


def test_problema_de_lectura_y_calidad_documental_estan_explicitamente_nombrados():
    assert MOTIVO_PROBLEMA_LECTURA in MOTIVOS_NUNCA_INCIDENCIA
    assert MOTIVO_CALIDAD_DOCUMENTAL_O_IMAGEN in MOTIVOS_NUNCA_INCIDENCIA


def test_caso_d_foto_borrosa_no_debe_registrarse_como_incidencia(tmp_path):
    """CASO D del bloque: 'EBEMA 5A' por foto borrosa -- el llamador
    (motor de evidencia / pipeline de detección) debe reconocer que el
    motivo es PROBLEMA_LECTURA/CALIDAD_DOCUMENTAL_O_IMAGEN y NUNCA llamar
    a `registrar()` con ese motivo como `tipo_incidencia`. El almacén no
    impone la taxonomía (la responsabilidad es del llamador), pero SÍ
    puede negarse activamente a registrar un motivo de calidad como si
    fuera una incidencia real -- ver `registrar()`."""
    almacen = _almacen(tmp_path)
    with pytest.raises(ErrorIncidenciasDocumentales):
        almacen.registrar(
            contexto="EBEMA SA", numero_guia="1", numero_transporte="T-1", campo="cliente",
            valor_documental="EBEMA 5A", valor_canonico="EBEMA SA",
            tipo_incidencia=MOTIVO_PROBLEMA_LECTURA, evidencia=("OCR_BAJA_CONFIANZA",), fecha=FECHA,
        )
    with pytest.raises(ErrorIncidenciasDocumentales):
        almacen.registrar(
            contexto="EBEMA SA", numero_guia="1", numero_transporte="T-1", campo="cliente",
            valor_documental="EBEMA 5A", valor_canonico="EBEMA SA",
            tipo_incidencia=MOTIVO_CALIDAD_DOCUMENTAL_O_IMAGEN, evidencia=(), fecha=FECHA,
        )


def test_emisor_confirmado_es_general_y_exige_marca_humana(tmp_path):
    """No basta una diferencia automática: la rama humana debe marcarla."""
    ruta = tmp_path / "incidencias_documentales.json"
    base = {
        "decision_id": "d-1", "accion": "CONFIRMAR", "campo": "direccion_entrega",
        "valor_documental": "CAMINO VIEJO 12", "valor_canonico": "RUTA 5 SUR KM 12",
        "documento": {"numero_guia": "472958", "numero_transporte": "14"},
        "discrepancia_documental_confirmada": True,
    }
    automatica = _emitir_incidencia_documental_confirmada(
        aplicacion={**base, "actor": "ATLAS_AUTOMATICO"}, ruta_incidencias=ruta, reloj=lambda: FECHA,
    )
    assert automatica is None
    assert _almacen(tmp_path).listar() == []

    incidencia = _emitir_incidencia_documental_confirmada(
        aplicacion={**base, "actor": "JAVIER_MBT"}, ruta_incidencias=ruta, reloj=lambda: FECHA,
    )
    assert incidencia is not None
    assert incidencia.tipo_incidencia == TIPO_CAMPO_DOCUMENTAL_INCORRECTO
    assert incidencia.estado == EstadoIncidencia.CONFIRMADA.value
    assert incidencia.valor_documental == "CAMINO VIEJO 12"
    assert incidencia.valor_canonico == "RUTA 5 SUR KM 12"
    # Misma decisión y misma discrepancia: el modelo existente deduplica.
    _emitir_incidencia_documental_confirmada(
        aplicacion={**base, "actor": "JAVIER_MBT"}, ruta_incidencias=ruta, reloj=lambda: FECHA,
    )
    assert len(_almacen(tmp_path).listar()) == 1


def test_ausencia_ocr_con_rut_vigente_es_hallazgo_atlas_no_incidencia_vigente(tmp_path):
    incidencia = _almacen(tmp_path).registrar(
        contexto="X", numero_guia="1", numero_transporte="T", campo="RUT del chofer",
        valor_documental="(campo ausente en el documento)", valor_canonico="12.345.678-5",
        tipo_incidencia="RUT_CHOFER_AUSENTE_DOCUMENTAL", evidencia=(), fecha=FECHA,
    )
    evaluacion = evaluar_incidencia(incidencia, {"rut_chofer": "12.345.678-5"})
    assert evaluacion.clasificacion is ClasificacionDocumental.ATLAS_EXTRACCION_ERRONEA
    assert evaluacion.vigente_documental is False


def test_ausencia_sin_evidencia_visual_no_acusa_documento(tmp_path):
    incidencia = _almacen(tmp_path).registrar(
        contexto="X", numero_guia="1", numero_transporte="T", campo="RUT del chofer",
        valor_documental="(campo ausente en el documento)", valor_canonico="12.345.678-5",
        tipo_incidencia="RUT_CHOFER_AUSENTE_DOCUMENTAL", evidencia=(), fecha=FECHA,
    )
    evaluacion = evaluar_incidencia(incidencia, {"rut_chofer": "No encontrado"})
    assert evaluacion.clasificacion is ClasificacionDocumental.NO_VERIFICABLE
    assert evaluacion.vigente_documental is False


def test_error_ocr_obra_o_patente_sin_confirmacion_explicita_no_es_emision(tmp_path):
    incidencia = _almacen(tmp_path).registrar(
        contexto="X", numero_guia="1", numero_transporte="T", campo="obra_destino",
        valor_documental="RELSINSKI", valor_canonico="HELSINSKI",
        tipo_incidencia="OBRA_DOCUMENTAL_INCONSISTENTE", evidencia=("OCR",), fecha=FECHA,
    )
    assert evaluar_incidencia(incidencia).clasificacion is ClasificacionDocumental.NO_VERIFICABLE


def test_rut_invalido_automatico_sin_revision_visual_tampoco_es_incidencia_visible(tmp_path):
    incidencia = _almacen(tmp_path).registrar(
        contexto="X", numero_guia="1", numero_transporte="T", campo="RUT del chofer",
        valor_documental="55.555.555-5", valor_canonico="12.345.678-5",
        tipo_incidencia="RUT_DOCUMENTAL_INVALIDO", evidencia=("OCR",), fecha=FECHA,
    )
    evaluacion = evaluar_incidencia(incidencia)
    assert evaluacion.clasificacion is ClasificacionDocumental.NO_VERIFICABLE
    assert evaluacion.vigente_documental is False


def test_decision_operacional_no_equivale_a_confirmacion_documental():
    assert not _confirma_discrepancia_documental({
        "tipo": "VEHICULO_DESCONOCIDO", "accion": "USAR_PATENTE_EXISTENTE", "actor": "JAVIER_MBT",
    })
    assert _confirma_discrepancia_documental({"discrepancia_documental_confirmada": True})


def test_475096_negativa_las_ausencias_y_contaminacion_no_crean_emision_confirmada(tmp_path):
    for campo, observado in (("chofer", "No encontrado"), ("material", ""), ("despachar_a_crudo", "PUT CHOFER RUT")):
        incidencia = _almacen(tmp_path).registrar(
            contexto="X", numero_guia="475096", numero_transporte="T", campo=campo,
            valor_documental=observado or "(no encontrado)", valor_canonico="valor operacional",
            tipo_incidencia="CAMPO_DOCUMENTAL_INCORRECTO", evidencia=(), fecha=FECHA,
        )
        assert evaluar_incidencia(incidencia).clasificacion is ClasificacionDocumental.NO_VERIFICABLE
