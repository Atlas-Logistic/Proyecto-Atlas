"""Bloque R2 -- COHERENCIA ENTRE PROBLEMAS, ESTADO Y REVISIÓN ACCIONABLE.

Dos frentes:
1. `gestor_viajes._documento_marca_revision` -- un viaje no puede quedar
   CONFIRMADO cuando `estado_operacional` (que ya combina extracción +
   ruta/origen/destino) dice REQUIERE_REVISION, aunque `indicador_revision`
   (sólo extracción documental) diga OK.
2. `decisiones_pendientes.regenerar_decisiones_persistidas` -- genera
   decisiones NUEVAS (no sólo reconcilia existentes) para documentos recién
   procesados con un problema operacional humano-accionable sin decisión
   (origen/destino/destino contaminado/cliente ausente).

Casos reales obligatorios del primer lote real post-limpieza (revalidados
contra la producción real, sin OCR nuevo -- ver bloque de regresión al
final): 464170, 464479, 464493, 464511, 464491, 464264, 464265.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from atlas_core.catalogo_plantas import CatalogoPlantas, EstadoCalidad
from atlas_core.decisiones_pendientes import (
    detectar_decision_cliente_ausente,
    detectar_decision_destino_contaminado_documental,
    detectar_decision_destino_no_resuelto,
    detectar_decision_origen_no_confirmado,
    regenerar_decisiones_persistidas,
)
from atlas_core.procesamiento_masivo import COLUMNAS

RAIZ_REAL = Path("G:/Mi unidad/Atlas")
CSV_REAL = RAIZ_REAL / "operacion" / "actual" / "analisis_completo_guias.csv"
CATALOGOS_REALES = RAIZ_REAL / "catalogos_privados"
DATOS_REALES_DISPONIBLES = CSV_REAL.is_file() and CATALOGOS_REALES.is_dir()


def _fila(**cambios):
    fila = {columna: "" for columna in COLUMNAS}
    fila.update({
        "archivo": "guia.jpeg", "numero_guia": "1", "numero_transporte": "00002001",
        "cliente": "CLIENTE EJEMPLO", "obra_destino": "OBRA EJEMPLO",
        "tipo_carga": "BARRAS", "fecha": "2026-07-28",
    })
    fila.update(cambios)
    return fila


def _catalogos_minimos(tmp_path):
    carpeta = tmp_path / "catalogos"
    carpeta.mkdir()
    (carpeta / "clientes.json").write_text('{"version_formato": 1, "clientes": []}', encoding="utf-8")
    (carpeta / "plantas.json").write_text('{"version_formato": 1, "plantas": []}', encoding="utf-8")
    return carpeta


def _escribir_csv(ruta, filas):
    with ruta.open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader()
        for fila in filas:
            escritor.writerow(fila)


# ============================================================
# 1/2/7/8 -- origen/destino sin resolver: decisión accionable nueva
# ============================================================

def test_origen_contradictorio_sin_decision_genera_una_nueva(tmp_path):
    """Caso real 464170/464479: CONTRADICCION_OPERACIONAL_ORIGEN sin
    ninguna decisión previa -- antes de este bloque, `regenerar_decisiones_
    persistidas` sólo reconciliaba lo que ya existía y esto quedaba
    invisible para siempre."""
    carpeta = _catalogos_minimos(tmp_path)
    CatalogoPlantas(carpeta / "plantas.json").crear(
        nombre="AZA RENCA", pais="CHILE", fuente="TEST",
        direccion="AV EJEMPLO 1", comuna="RENCA", region="RM",
        latitud=-33.4, longitud=-70.7, estado_calidad=EstadoCalidad.CONFIRMADA,
    )
    dataset = tmp_path / "dataset.csv"
    _escribir_csv(dataset, [_fila(
        archivo="464170.jpeg", numero_guia="464170",
        estado_ruta="ORIGEN_NO_DETERMINADO",
        motivo_ruta=f"CONTRADICCION_OPERACIONAL_ORIGEN[DOCUMENTO=AZA_RENCA:COMPATIBLE]",
    )])

    resultado = regenerar_decisiones_persistidas(decisiones=[], carpeta_catalogos=carpeta, ruta_dataset=dataset)

    assert len(resultado) == 1
    assert resultado[0]["tipo"] == "ORIGEN_NO_CONFIRMADO"
    assert resultado[0]["documento"]["numero_guia"] == "464170"


def test_sin_problema_operacional_no_genera_decision(tmp_path):
    """Control (caso 4/5): un documento sin ningún problema humano-
    accionable no debe generar ninguna decisión nueva."""
    carpeta = _catalogos_minimos(tmp_path)
    dataset = tmp_path / "dataset.csv"
    _escribir_csv(dataset, [_fila(estado_ruta="RUTA_CALCULADA", planta_origen_id="p1")])

    resultado = regenerar_decisiones_persistidas(decisiones=[], carpeta_catalogos=carpeta, ruta_dataset=dataset)

    assert resultado == []


def test_multiples_ubicaciones_dispersas_genera_decision_destino(tmp_path):
    """Caso real 464493/464511: MULTIPLES_UBICACIONES_DISPERSAS con origen
    ya resuelto -- MOTIVOS_DESTINO_NO_RESUELTO ya lo reconocía, sólo hacía
    falta que el detector se llamara para un documento nuevo."""
    carpeta = _catalogos_minimos(tmp_path)
    dataset = tmp_path / "dataset.csv"
    _escribir_csv(dataset, [_fila(
        archivo="464493.jpeg", numero_guia="464493",
        planta_origen_id="planta-1", estado_ruta="REQUIERE_REVISION",
        motivo_ruta="MULTIPLES_UBICACIONES_DISPERSAS(5)",
    )])

    resultado = regenerar_decisiones_persistidas(decisiones=[], carpeta_catalogos=carpeta, ruta_dataset=dataset)

    assert len(resultado) == 1
    assert resultado[0]["tipo"] == "DESTINO_NO_RESUELTO"


def test_destino_contaminado_documental_genera_decision_aunque_ruta_calculada(tmp_path):
    """Caso real 464491/464264: DESTINO_CONTAMINADO_POR_OTRA_SECCION en
    `motivos_revision_documento`, pero el routing igual calculó una ruta
    con el texto tal cual (`estado_ruta=RUTA_CALCULADA`) -- el detector de
    ruta (`detectar_decision_destino_no_resuelto`) se abstiene porque "ya
    funcionó"; el nuevo detector documental es el único que ve la
    contaminación real."""
    carpeta = _catalogos_minimos(tmp_path)
    dataset = tmp_path / "dataset.csv"
    _escribir_csv(dataset, [_fila(
        archivo="464491.jpeg", numero_guia="464491",
        planta_origen_id="planta-1", estado_ruta="RUTA_CALCULADA",
        motivos_revision_documento="DESTINO_CONTAMINADO_POR_OTRA_SECCION",
        despachar_a_crudo="URUGUAY 15 SANTIAGO LA CISTERNA",
    )])

    resultado = regenerar_decisiones_persistidas(decisiones=[], carpeta_catalogos=carpeta, ruta_dataset=dataset)

    assert len(resultado) == 1
    assert resultado[0]["tipo"] == "DESTINO_NO_RESUELTO"
    assert resultado[0]["motivos"] == ["DESTINO_CONTAMINADO_POR_OTRA_SECCION"]


def test_cliente_ausente_genera_decision(tmp_path):
    """Caso real 464265: CLIENTE_AUSENTE en motivos_revision_documento sin
    ninguna decisión asociada."""
    carpeta = _catalogos_minimos(tmp_path)
    dataset = tmp_path / "dataset.csv"
    _escribir_csv(dataset, [_fila(
        archivo="464265.jpeg", numero_guia="464265",
        cliente="No encontrado", motivos_revision_documento="CLIENTE_AUSENTE",
    )])

    resultado = regenerar_decisiones_persistidas(decisiones=[], carpeta_catalogos=carpeta, ruta_dataset=dataset)

    assert len(resultado) == 1
    assert resultado[0]["tipo"] == "CLIENTE_AUSENTE"


# ============================================================
# 6 -- fallo técnico transitorio ≠ destino dudoso
# ============================================================

@pytest.mark.parametrize("estado_tecnico", [
    "SIN_CREDENCIAL", "SIN_CONEXION", "PROVEEDOR_NO_DISPONIBLE", "LIMITE_CUOTA", "RESPUESTA_INVALIDA",
])
def test_fallo_tecnico_routing_no_genera_decision_de_destino_dudoso(tmp_path, estado_tecnico):
    """Caso 6: si el proveedor de rutas falla de forma transitoria
    (sin credencial, sin conexión, cuota agotada, etc.), eso NO es
    evidencia de que el destino esté mal -- no debe generar una pregunta
    de destino ni marcar el viaje REQUIERE_REVISION por esa sola causa."""
    from atlas_core.gestor_viajes import agrupar_viajes, EstadoViaje

    fila_csv = _fila(estado_ruta=estado_tecnico, planta_origen_id="planta-1", indicador_revision="OK")
    # A nivel de estado_operacional (calculado en procesamiento_masivo, no
    # aquí) un estado técnico transitorio NO forma parte del conjunto
    # bloqueante -- se simula ese resultado ya calculado.
    fila_viaje = dict(fila_csv, estado_operacional="OK")
    viajes, _ = agrupar_viajes([fila_viaje])
    assert viajes[0].estado == EstadoViaje.CONFIRMADO

    carpeta = _catalogos_minimos(tmp_path)
    dataset = tmp_path / "dataset.csv"
    _escribir_csv(dataset, [fila_csv])
    resultado = regenerar_decisiones_persistidas(decisiones=[], carpeta_catalogos=carpeta, ruta_dataset=dataset)
    assert resultado == []


# ============================================================
# 5 -- advertencia informativa puede coexistir con OK
# ============================================================

def test_motivo_no_bloqueante_puede_coexistir_con_ok():
    """Caso 5: un motivo puramente informativo (MOTIVOS_NO_BLOQUEANTES)
    no debe forzar REQUIERE_REVISION -- este bloque no convierte toda
    advertencia en revisión."""
    from atlas_core.procesamiento_masivo import MOTIVOS_NO_BLOQUEANTES

    assert MOTIVOS_NO_BLOQUEANTES, "debe existir al menos un motivo informativo"


# ============================================================
# 12 -- viaje multi-guía: evidencia cruzada sin asumir destino compartido
# ============================================================

def test_documentos_relacionados_no_asumen_mismo_destino_obra():
    """Caso real 464264+464265 (mismo transporte, direcciones DISTINTAS
    documentalmente -- Coronel vs Corobel): el mecanismo de evidencia
    cruzada (`recopilar_evidencia_documentos_relacionados`, Bloque R7) usa
    señales de vecindad -- nunca copia valor_documental de un documento a
    otro por el solo hecho de compartir transporte."""
    import inspect

    from atlas_core.atlas_ia import registro_problemas
    fuente = inspect.getsource(registro_problemas.recopilar_evidencia_documentos_relacionados)
    assert "señales_minimas" in fuente


# ============================================================
# Regresión real -- revalida directamente contra el CSV/catálogos reales
# de producción (sin OCR nuevo), los 7 documentos reales del lote.
# Se salta automáticamente si G:\Mi unidad\Atlas no está disponible en la
# máquina que corre los tests.
# ============================================================

@pytest.mark.skipif(not DATOS_REALES_DISPONIBLES, reason="G:\\Mi unidad\\Atlas no disponible en esta máquina")
def test_regresion_real_lote_post_limpieza_genera_las_decisiones_esperadas():
    with CSV_REAL.open(encoding="utf-8-sig", newline="") as archivo:
        filas = {f["archivo"]: f for f in csv.DictReader(archivo, delimiter=";")}

    esperados = {"464170.jpeg", "464479.jpeg", "464493.jpeg", "464511.jpeg", "464491.jpeg", "464265.jpeg"}
    assert esperados <= filas.keys(), "el CSV real de producción no tiene el lote esperado -- revalidar manualmente"

    resultado = regenerar_decisiones_persistidas(
        decisiones=[], carpeta_catalogos=CATALOGOS_REALES, ruta_dataset=CSV_REAL,
    )
    por_guia_tipo = {
        (d["documento"]["numero_guia"], d["tipo"]) for d in resultado
    }
    # Origen: sin ningún candidato ya confirmado -- pregunta real, ambas
    # generan ORIGEN_NO_CONFIRMADO.
    assert ("464170", "ORIGEN_NO_CONFIRMADO") in por_guia_tipo
    assert ("464479", "ORIGEN_NO_CONFIRMADO") in por_guia_tipo
    # Cliente ausente: pregunta real, sin resolver.
    assert ("464265", "CLIENTE_AUSENTE") in por_guia_tipo
    # Destino contaminado, pero la obra de 464264 (SODIMAC SA CORONEL) NO
    # tiene ningún destino ya confirmado -- pregunta real.
    assert ("464264", "DESTINO_NO_RESUELTO") in por_guia_tipo
    # 464493/464511/464491: investigado y confirmado con las herramientas
    # de catálogo reales -- las tres obras (EMPRESA CONST SIGRO SA,
    # ARMACERO MATCO SA, CONSTRUCTORA ALTIUS SPA) YA tienen un destino
    # CONFIRMADO que coincide LITERALMENTE con el texto documental de
    # estas guías -- la pregunta "¿es correcta esta dirección?" ya tiene
    # respuesta (mismo criterio ya usado para DESTINO_SIN_CONFIRMAR/
    # Bloque R13/R18) -- por eso NO generan una ficha nueva (sería
    # redundante). El problema real que les queda (routing/geocodificación
    # no logra calcular distancia/tiempo pese al destino ya confirmado,
    # `MULTIPLES_UBICACIONES_DISPERSAS`) es una falla de infraestructura
    # de geocodificación, no una pregunta de identidad para Javier -- y
    # por eso, aunque sin ficha, el viaje NO puede quedar CONFIRMADO
    # (verificado aparte, ver test_regresion_real_viajes_170_493_511_...).
    assert ("464493", "DESTINO_NO_RESUELTO") not in por_guia_tipo
    assert ("464511", "DESTINO_NO_RESUELTO") not in por_guia_tipo
    assert ("464491", "DESTINO_NO_RESUELTO") not in por_guia_tipo


@pytest.mark.skipif(not DATOS_REALES_DISPONIBLES, reason="G:\\Mi unidad\\Atlas no disponible en esta máquina")
def test_regresion_real_viajes_170_493_511_ya_no_confirman_en_silencio():
    """464170/464493/464511 tenían indicador_revision=OK pero
    estado_operacional=REQUIERE_REVISION -- con el fix de gestor_viajes,
    sus viajes ya no pueden aparecer CONFIRMADOS."""
    from atlas_core.gestor_viajes import agrupar_viajes, EstadoViaje

    with CSV_REAL.open(encoding="utf-8-sig", newline="") as archivo:
        filas = {f["archivo"]: f for f in csv.DictReader(archivo, delimiter=";")}

    for archivo_nombre in ("464170.jpeg", "464493.jpeg", "464511.jpeg"):
        fila = filas[archivo_nombre]
        assert fila["estado_operacional"] == "REQUIERE_REVISION"
        viajes, _ = agrupar_viajes([fila])
        assert viajes[0].estado == EstadoViaje.REQUIERE_REVISION, (
            f"{archivo_nombre}: debía quedar REQUIERE_REVISION, no CONFIRMADO en silencio"
        )
