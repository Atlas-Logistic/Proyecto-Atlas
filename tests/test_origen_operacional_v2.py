"""Bloque ORIGEN OPERACIONAL V2 -- integración de extremo a extremo:
`resolver_entrega_documento`/`calcular_ruta_entrega_para_viaje` con
`codigo_planta_mobile`/`categoria_documento`, y regresión del caso real
472593 (envío Mobile `36e7aa53-214e-48b0-a96c-14989b60e9aa`, guía
`472593`) usando los valores REALMENTE persistidos (Sección "PRUEBAS
OBLIGATORIAS" #10 del ticket) -- nunca vuelve a correr OCR sobre la foto
real, nunca modifica el envío real."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from atlas_core.catalogo_plantas import CatalogoPlantas, EstadoCalidad
from atlas_core.decisiones_pendientes import detectar_decision_origen_no_confirmado
from atlas_core.rutas.destino_entrega import resolver_entrega_documento
from atlas_core.rutas.modelos import Coordenadas
from atlas_core.rutas.proveedor import ProveedorRutasSimulado

COORD_AZA_COLINA = Coordenadas(-70.6739, -33.1975)
COORD_AZA_RENCA = Coordenadas(-70.685226, -33.401595)

# Mismo texto de encabezado real ya usado en `test_rutas_destino_entrega.py`
# para el mismo emisor -- letterhead societario real de AZA, casa matriz
# RENCA, presente en TODAS sus guías sin importar la planta física real de
# despacho (confirmado por Javier).
TEXTOS_ENCABEZADO_RENCA = ("ACEROS AZA S A CASA MATRIZ PLANTA RENCA LA UNION 3070 RENCA SANTIAGO CHILE",)


@pytest.fixture
def plantas_colina_renca(tmp_path):
    """Réplica fiel del catálogo real (mismos IDs, mismos nombres,
    `G:\\Mi unidad\\Atlas\\catalogos_privados\\plantas.json`) más la
    regla operacional confirmada por Javier para este bloque -- nunca
    toca el catálogo real."""
    repo = CatalogoPlantas(tmp_path / "plantas.json")
    colina = repo.crear(
        nombre="AZA COLINA", pais="CHILE", fuente="PRUEBA",
        latitud=COORD_AZA_COLINA.latitud, longitud=COORD_AZA_COLINA.longitud,
        estado_calidad=EstadoCalidad.CONFIRMADA, categorias_permitidas=("BARRAS", "ROLLOS"),
    )
    renca = repo.crear(
        nombre="AZA RENCA", pais="CHILE", fuente="PRUEBA",
        latitud=COORD_AZA_RENCA.latitud, longitud=COORD_AZA_RENCA.longitud,
        estado_calidad=EstadoCalidad.CONFIRMADA, categorias_permitidas=("ANGULOS",),
    )
    return repo.listar(), colina, renca


# --- Regresión real 472593 ---

def test_regresion_472593_mobile_colina_no_es_sobrescrito_por_encabezado_renca(plantas_colina_renca):
    """Valores REALMENTE persistidos en el envío/documento reales:
    `planta_origen_informada="AZA_COLINA"` (envio.json real), `tipo_carga
    ="BARRAS"` (datos_ocr real), encabezado documental real de AZA
    (misma casa matriz RENCA que ya usan otros tests de este repo).
    Antes de este bloque, `origen_determinado_por` terminaba en
    `DOCUMENTO`/`evidencia_origen=ENCABEZADO_GUIA`, publicando
    "AZA RENCA" -- incorrecto, confirmado por Javier. Con la regla de
    compatibilidad configurada, debe conservar AZA COLINA."""
    plantas, colina, _renca = plantas_colina_renca
    resultado = resolver_entrega_documento(
        TEXTOS_ENCABEZADO_RENCA, plantas, ProveedorRutasSimulado(),
        codigo_planta_mobile="AZA_COLINA", categoria_documento="BARRAS",
    )
    assert resultado["planta_origen_id"] == colina.planta_id
    assert resultado["planta_origen_nombre"] == "AZA COLINA"
    assert resultado["origen_determinado_por"] == "MOBILE"
    assert resultado["evidencia_origen"] == "MOBILE_COMPATIBLE_DOCUMENTO_CONTRADICE_REGLA"


def test_regresion_472593_sin_este_bloque_habria_publicado_renca(plantas_colina_renca):
    """Control -- reproduce el comportamiento ANTERIOR a este bloque
    (sin `codigo_planta_mobile`/`categoria_documento`, exactamente la
    llamada que hacía `resolver_entrega_documento` antes): confirma que
    el bug real (472593 publicado como AZA RENCA) es reproducible con
    esta misma fixture, y por lo tanto que el fix de arriba es el que
    lo corrige -- nunca una coincidencia de datos."""
    plantas, _colina, renca = plantas_colina_renca
    resultado = resolver_entrega_documento(TEXTOS_ENCABEZADO_RENCA, plantas, ProveedorRutasSimulado())
    assert resultado["planta_origen_id"] == renca.planta_id
    assert resultado["origen_determinado_por"] == "DOCUMENTO"
    assert resultado["evidencia_origen"] == "ENCABEZADO_GUIA"


# --- Integración: `codigo_planta_mobile`/`categoria_documento` a través
# de `resolver_entrega_documento` (encabezado + ruta) ---

def test_sin_mobile_ni_categoria_comportamiento_identico_a_antes(plantas_colina_renca):
    """Compatibilidad hacia atrás explícita: ningún parámetro nuevo
    informado (Desktop/procesamiento por lote histórico, sin Mobile) --
    el documento resuelve exactamente igual que antes de este bloque."""
    plantas, _colina, renca = plantas_colina_renca
    resultado = resolver_entrega_documento(TEXTOS_ENCABEZADO_RENCA, plantas, ProveedorRutasSimulado())
    assert resultado["planta_origen_nombre"] == "AZA RENCA"
    assert resultado["origen_determinado_por"] == "DOCUMENTO"


def test_mobile_sin_documento_resuelve_directo(plantas_colina_renca):
    plantas, colina, _renca = plantas_colina_renca
    resultado = resolver_entrega_documento(
        (), plantas, ProveedorRutasSimulado(), codigo_planta_mobile="AZA_COLINA", categoria_documento="ROLLOS",
    )
    assert resultado["planta_origen_id"] == colina.planta_id
    assert resultado["origen_determinado_por"] == "MOBILE"


def test_mobile_con_contradiccion_real_sin_corroboracion_queda_sin_determinar(plantas_colina_renca):
    """Sección CONTRADICCIONES del ticket: Mobile informa RENCA con
    material BARRAS (incompatible con la regla) y sin documento que
    corrobore -- nunca se autocorrige a COLINA, nunca se acepta RENCA a
    ciegas -- queda `ORIGEN_NO_DETERMINADO` con el motivo de
    contradicción, listo para `ORIGEN_NO_CONFIRMADO`."""
    plantas, _colina, _renca = plantas_colina_renca
    resultado = resolver_entrega_documento(
        (), plantas, ProveedorRutasSimulado(), codigo_planta_mobile="AZA_RENCA", categoria_documento="BARRAS",
    )
    assert resultado["planta_origen_id"] == ""
    assert resultado["estado_ruta"] == "ORIGEN_NO_DETERMINADO"
    assert resultado["motivo_ruta"].startswith("CONTRADICCION_OPERACIONAL_ORIGEN")


def test_codigo_mobile_desconocido_no_bloquea_ni_lanza(plantas_colina_renca):
    """Un código que no calza con ninguna planta del catálogo (typo,
    empresa/rubro sin ese código configurado) se ignora limpiamente --
    nunca lanza, nunca inventa una planta."""
    plantas, _colina, renca = plantas_colina_renca
    resultado = resolver_entrega_documento(
        TEXTOS_ENCABEZADO_RENCA, plantas, ProveedorRutasSimulado(),
        codigo_planta_mobile="PLANTA_QUE_NO_EXISTE", categoria_documento="ANGULOS",
    )
    assert resultado["planta_origen_id"] == renca.planta_id  # cae al documento, compatible con ANGULOS


# --- Contradicción real -> queda lista para ORIGEN_NO_CONFIRMADO (Sección
# CONTRADICCIONES del ticket: "última instancia, confirmación humana") ---

def test_contradiccion_operacional_genera_decision_origen_no_confirmado(plantas_colina_renca):
    """La contradicción real (Mobile RENCA + BARRAS, sin documento que
    corrobore) deja `motivo_ruta` listo para que
    `detectar_decision_origen_no_confirmado` -- el MISMO mecanismo ya
    usado para conflictos GPS -- la ofrezca como pregunta humana, con
    ambas plantas evaluadas como candidatas y su compatibilidad real."""
    plantas, colina, renca = plantas_colina_renca
    resultado = resolver_entrega_documento(
        (), plantas, ProveedorRutasSimulado(), codigo_planta_mobile="AZA_RENCA", categoria_documento="BARRAS",
    )
    fila = {
        "numero_guia": "472593", "numero_transporte": "0000355419",
        "estado_ruta": resultado["estado_ruta"], "motivo_ruta": resultado["motivo_ruta"],
        "planta_origen_id": resultado["planta_origen_id"], "tipo_carga": "BARRAS",
    }
    decision = detectar_decision_origen_no_confirmado(archivo="472593.jpg", fila=fila, plantas=plantas)
    assert decision is not None
    assert decision["tipo"] == "ORIGEN_NO_CONFIRMADO"
    assert decision["motivos"] == ["CONTRADICCION_OPERACIONAL_ORIGEN"]
    # Única fuente real (Mobile) -- se ofrece como candidata con su
    # compatibilidad ya evaluada; el humano sigue pudiendo elegir otra
    # planta del catálogo vía SELECCIONAR_OTRA_PLANTA (nunca se limita a
    # los candidatos sugeridos -- mismo contrato ya usado por
    # ORIGEN_GPS_CONFLICTO/ESTADIA_SIN_PLANTA).
    assert {c["planta_nombre"] for c in decision["candidatos"]} == {"AZA RENCA"}
    assert "incompatible" in decision["candidatos"][0]["evidencia_resumen"]
    assert set(decision["acciones_permitidas"]) == {
        "CONFIRMAR_PLANTA", "SELECCIONAR_OTRA_PLANTA", "NO_PUEDO_DETERMINAR", "POSPONER",
    }


def test_contradiccion_con_dos_fuentes_ofrece_ambas_plantas_como_candidatas(plantas_colina_renca):
    """Mobile y documento discrepan y la categoría no está configurada
    para ninguna regla que desempate -- ambas plantas quedan como
    candidatas reales, ninguna se descarta en silencio."""
    plantas, colina, renca = plantas_colina_renca
    resultado = resolver_entrega_documento(
        TEXTOS_ENCABEZADO_RENCA, plantas, ProveedorRutasSimulado(),
        codigo_planta_mobile="AZA_COLINA", categoria_documento="MATERIAL_SIN_REGLA_CONFIGURADA",
    )
    fila = {
        "numero_guia": "999999", "numero_transporte": "0000999999",
        "estado_ruta": resultado["estado_ruta"], "motivo_ruta": resultado["motivo_ruta"],
        "planta_origen_id": resultado["planta_origen_id"], "tipo_carga": "MATERIAL_SIN_REGLA_CONFIGURADA",
    }
    decision = detectar_decision_origen_no_confirmado(archivo="999999.jpg", fila=fila, plantas=plantas)
    assert decision is not None
    assert {c["planta_nombre"] for c in decision["candidatos"]} == {"AZA COLINA", "AZA RENCA"}


def test_documento_con_origen_ya_resuelto_no_genera_decision(plantas_colina_renca):
    """El caso real 472593, YA resuelto por la fusión (Mobile COLINA
    compatible), nunca genera una pregunta -- `planta_origen_id`
    presente es suficiente para abstenerse, igual que hoy."""
    plantas, colina, _renca = plantas_colina_renca
    resultado = resolver_entrega_documento(
        TEXTOS_ENCABEZADO_RENCA, plantas, ProveedorRutasSimulado(),
        codigo_planta_mobile="AZA_COLINA", categoria_documento="BARRAS",
    )
    fila = {
        "numero_guia": "472593", "numero_transporte": "0000355419",
        "estado_ruta": resultado["estado_ruta"], "motivo_ruta": resultado["motivo_ruta"],
        "planta_origen_id": resultado["planta_origen_id"], "tipo_carga": "BARRAS",
    }
    assert detectar_decision_origen_no_confirmado(archivo="472593.jpg", fila=fila, plantas=plantas) is None
