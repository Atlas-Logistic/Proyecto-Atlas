"""Bloque P1.1 -- cierre de los 3 BLOQUEANTES reales encontrados por
revisión independiente (Codex) sobre P1.

BLOQUEANTE 2 (recuperación falsa desde documento hermano): compartir
`numero_transporte` demuestra relación de VIAJE, nunca igualdad de
cliente/obra/destino -- un transporte puede llevar múltiples entregas/
obras/clientes reales. `atlas_core.gestor_viajes.Viaje` ya NO recupera
cliente/obra/destino desde un documento hermano únicamente por eso.

BLOQUEANTE 3 (falsos CONFIABLES estructurales): reproduce exactamente
los 4 casos reportados por Codex y certifica que ninguno vuelve a pasar
como CONFIABLE, cuidando explícitamente no introducir falsos positivos
sobre nombres/direcciones reales."""
from __future__ import annotations

from atlas_core.credibilidad_campos import (
    NivelCredibilidad,
    evaluar_credibilidad_direccion,
    evaluar_credibilidad_entidad_nombre,
    evaluar_credibilidad_material,
)
from atlas_core.gestor_viajes import agrupar_viajes
from atlas_core.procesamiento_masivo import COLUMNAS


def _fila(**overrides):
    fila = {c: "" for c in COLUMNAS}
    fila.update({
        "archivo": "1.jpeg", "estado_procesamiento": "OK", "fecha": "26-08-2026",
        "indicador_revision": "OK", "estado_ruta": "RUTA_CALCULADA",
        "planta_origen_nombre": "AZA COLINA", "numero_transporte": "0000900001",
        "patente_tracto": "AB1234",
    })
    fila.update(overrides)
    return fila


# ============================================================
# BLOQUEANTE 2 -- aceptación 4/5/6: mismo transporte, campos distintos
# reales, nunca se contaminan entre sí.
# ============================================================


def test_mismo_transporte_distinto_cliente_no_se_contamina():
    """4: dos documentos reales del mismo transporte, cada uno con su
    PROPIO cliente real y confiable -- ninguno debe heredar el del otro
    (sería falso incluso si ambos fueran confiables: nada demuestra que
    compartan cliente sólo por compartir transporte)."""
    doc_a = _fila(archivo="a.jpeg", numero_guia="A", cliente="EMPRESA UNO SPA")
    doc_b = _fila(archivo="b.jpeg", numero_guia="B", cliente="EMPRESA DOS LTDA")
    viajes, _ = agrupar_viajes([doc_a, doc_b])
    viaje = viajes[0]
    assert set(viaje.clientes) == {"EMPRESA UNO SPA", "EMPRESA DOS LTDA"}


def test_mismo_transporte_una_obra_dudosa_no_hereda_la_del_hermano():
    """5: un documento con obra CONFIABLE real, otro con obra DUDOSA
    (etiqueta genérica) -- el dudoso NUNCA debe terminar mostrando la
    obra del hermano; debe quedar NO DETERMINADO."""
    doc_confiable = _fila(archivo="a.jpeg", numero_guia="A", obra_destino="OBRA REAL DEL SUR")
    doc_dudoso = _fila(archivo="b.jpeg", numero_guia="B", obra_destino="TRANSPORTES")
    viajes, _ = agrupar_viajes([doc_confiable, doc_dudoso])
    viaje = viajes[0]
    assert "OBRA REAL DEL SUR" in viaje.obras_destino
    assert "TRANSPORTES" not in viaje.obras_destino
    assert "NO DETERMINADO" in viaje.obras_destino


def test_mismo_transporte_destino_truncado_no_hereda_direccion_del_hermano():
    """6/caso real 472624: un documento con destino real y completo, el
    hermano con un fragmento truncado ("SAN") -- el consolidado del
    VIAJE nunca debe quedar en la dirección del hermano (sería
    atribuirle al documento truncado una entrega que nunca demostró
    compartir)."""
    doc_completo = _fila(archivo="a.jpeg", numero_guia="A", despachar_a_crudo="SAN LUIS 1201 QUILICURA")
    doc_truncado = _fila(archivo="b.jpeg", numero_guia="B", despachar_a_crudo="SAN")
    viajes, _ = agrupar_viajes([doc_completo, doc_truncado])
    viaje = viajes[0]
    assert viaje.despachar_a == ""  # nunca "SAN LUIS 1201 QUILICURA"


def test_documento_dudoso_sin_evidencia_adicional_queda_no_determinado():
    """7: documento dudoso + hermano limpio, SIN evidencia adicional de
    correspondencia (sólo comparten transporte) -> NO DETERMINADO,
    nunca recuperado."""
    doc_dudoso = _fila(archivo="a.jpeg", numero_guia="A", cliente="96.792.430-K")
    doc_limpio = _fila(archivo="b.jpeg", numero_guia="B", cliente="SODIMAC SA")
    viajes, _ = agrupar_viajes([doc_dudoso, doc_limpio])
    viaje = viajes[0]
    assert "NO DETERMINADO" in viaje.clientes
    assert "96.792.430-K" not in viaje.clientes
    assert "SODIMAC SA" in viaje.clientes  # el valor propio y confiable del hermano sigue visible, no se oculta


def test_material_nunca_se_hereda_de_hermano_mismo_transporte():
    """Control explícito: material sigue sin heredarse (ya lo garantizaba
    P1; BLOQUEANTE 2 no lo cambia)."""
    doc_a = _fila(archivo="a.jpeg", numero_guia="A", descripcion_material="HORMIGON 8MM 12M A630-420H (N)")
    doc_b = _fila(archivo="b.jpeg", numero_guia="B", descripcion_material="96.792.430-K")
    viajes, _ = agrupar_viajes([doc_a, doc_b])
    viaje = viajes[0]
    assert "HORMIGON 8MM 12M A630-420H (N)" in viaje.materiales
    assert "NO DETERMINADO" in viaje.materiales
    assert "96.792.430-K" not in viaje.materiales


# ============================================================
# BLOQUEANTE 3 -- aceptación 8/9: los 4 falsos CONFIABLES reportados
# por Codex dejan de ser publicables; valores reales siguen pasando.
# ============================================================


def test_los_cuatro_falsos_confiables_de_codex_dejan_de_ser_publicables():
    assert evaluar_credibilidad_material("96.792.430-K").nivel != NivelCredibilidad.CONFIABLE
    assert evaluar_credibilidad_entidad_nombre("FECHA DE EMISION 26-08-2026").nivel != NivelCredibilidad.CONFIABLE
    assert evaluar_credibilidad_entidad_nombre("PATENTE BDFG50").nivel != NivelCredibilidad.CONFIABLE
    assert evaluar_credibilidad_direccion("XXXXX").nivel != NivelCredibilidad.CONFIABLE


def test_variantes_generales_de_los_mismos_patrones_tambien_se_detectan():
    """Control de generalidad (nunca reglas puntuales de estas 4
    guías/valores): cualquier RUT válido aislado, cualquier fecha/
    patente válida embebida en un nombre, y cualquier token alfabético
    de una sola palabra sin dígito, disparan igual -- no sólo los 4
    valores exactos reportados."""
    assert evaluar_credibilidad_material("12.345.678-5").nivel != NivelCredibilidad.CONFIABLE
    assert evaluar_credibilidad_entidad_nombre("RUT 11.111.111-1 CLIENTE").nivel != NivelCredibilidad.CONFIABLE
    assert evaluar_credibilidad_entidad_nombre("PATENTE JB6878").nivel != NivelCredibilidad.CONFIABLE
    assert evaluar_credibilidad_direccion("QWERTY").nivel != NivelCredibilidad.CONFIABLE
    assert evaluar_credibilidad_direccion("ABCDEFGHIJ").nivel != NivelCredibilidad.CONFIABLE


# ============================================================
# BLOQUEANTE 1 -- representación operacional por documento (nunca la
# lista agregada, nunca la evidencia cruda). Motor exporta la pieza que
# Desktop necesitaba; Desktop deja de usar evidencia como sustituto (ver
# Atlas-Viajes-Desktop-Restaurado/src/consolidacion_viaje.js).
# ============================================================


def test_documentos_operacionales_conserva_correspondencia_por_documento():
    """3: cada documento conserva su PROPIO valor operacional -- nunca
    la lista agregada de viaje (que pierde de vista qué guía es cuál)."""
    doc_limpio = _fila(archivo="472623.jpeg", numero_guia="472623", cliente="SODIMAC SA")
    doc_dudoso = _fila(
        archivo="472624.jpeg", numero_guia="472624", cliente="96.792.430-K", obra_destino="TRANSPORTES",
        descripcion_material="Codigo Cliente FECHA DE EMISION 26-08-2026 RUT VIA AL",
        despachar_a_crudo="SAN",
    )
    viajes, _ = agrupar_viajes([doc_limpio, doc_dudoso])
    viaje = viajes[0]
    por_archivo = {d["archivo"]: d for d in viaje.documentos_operacionales}

    assert por_archivo["472623.jpeg"]["cliente"] == "SODIMAC SA"
    assert por_archivo["472624.jpeg"]["cliente"] == "NO DETERMINADO"  # nunca "96.792.430-K"
    assert por_archivo["472624.jpeg"]["obra_destino"] == "NO DETERMINADO"  # nunca "TRANSPORTES"
    assert por_archivo["472624.jpeg"]["despachar_a_crudo"] == "NO DETERMINADO"  # nunca "SAN"
    assert "FECHA DE EMISION" not in por_archivo["472624.jpeg"]["descripcion_material"]

    # 2: la evidencia cruda sigue disponible íntegra, aparte.
    evidencia_472624 = next(d.evidencia for d in viaje.documentos if d.archivo == "472624.jpeg")
    assert evidencia_472624["cliente"] == "96.792.430-K"
    assert evidencia_472624["obra_destino"] == "TRANSPORTES"


def test_valores_normales_reales_continuan_siendo_publicables_sin_falsos_positivos():
    """9 -- cuidar falsos positivos: un nombre real no debe ocultarse
    sólo por contener una palabra que TAMBIÉN pueda aparecer en una
    etiqueta (nunca substring ingenuo)."""
    assert evaluar_credibilidad_material("HORMIGON 8MM 12M A630-420H (N)").nivel == NivelCredibilidad.CONFIABLE
    assert evaluar_credibilidad_entidad_nombre("SODIMAC SA").nivel == NivelCredibilidad.CONFIABLE
    assert evaluar_credibilidad_entidad_nombre("EMPRESA CONST SIGRO").nivel == NivelCredibilidad.CONFIABLE
    assert evaluar_credibilidad_entidad_nombre("TRANSPORTES ROJAS HNOS LTDA").nivel == NivelCredibilidad.CONFIABLE
    assert evaluar_credibilidad_entidad_nombre("CLIENTE NUBLE").nivel == NivelCredibilidad.CONFIABLE
    assert evaluar_credibilidad_direccion("SAN LUIS 1201 QUILICURA").nivel == NivelCredibilidad.CONFIABLE
    assert evaluar_credibilidad_direccion("AVENIDA APOQUINDO 1234").nivel == NivelCredibilidad.CONFIABLE
