"""Bloque R1 -- EVIDENCIA VISUAL EN REVISIONES.

Pruebas con fixtures (nunca contra la operación real -- Atlas debe
seguir en 0 guías/0 viajes/0 decisiones al terminar este bloque)."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from atlas_core.evidencia_documental import (
    RETENCION_EVIDENCIA_RESUELTA_DIAS,
    UBICACION_ACTIVA_DESKTOP,
    UBICACION_ACTIVA_MOBILE,
    UBICACION_EVIDENCIA_RESUELTA,
    UBICACION_NO_ENCONTRADA,
    UBICACION_PURGADA,
    documentos_con_revision_pendiente,
    mover_evidencia_resuelta_sin_revision_pendiente,
    purgar_evidencia_resuelta_vencida,
    resolver_ruta_evidencia,
)

FECHA_BASE = datetime(2026, 8, 31, 12, 0, tzinfo=timezone.utc)


def _decision(archivo, *, estado="PENDIENTE", decision_id=None):
    return {
        "decision_id": decision_id or f"id-{archivo}-{estado}",
        "estado": estado,
        "documento": {"archivo": archivo, "numero_guia": "1", "numero_transporte": "1"},
    }


def _bandeja(*decisiones):
    return {"schema_version": 1, "decisiones": list(decisiones)}


def _crear_entrada_desktop(raiz: Path, lote: str, archivo: str, contenido: bytes = b"foto-desktop"):
    ruta = raiz / "operacion" / "entradas" / lote / archivo
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_bytes(contenido)
    return ruta


def _crear_envio_mobile(raiz: Path, envio_id: str, foto: str = "original.jpg", contenido: bytes = b"foto-mobile"):
    ruta = raiz / "operacion" / "mobile" / "envios" / envio_id / foto
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_bytes(contenido)
    return ruta


# ============================================================
# 1/9. Resolución básica -- una revisión, imagen disponible; varias
#      revisiones del mismo documento comparten la misma referencia.
# ============================================================


def test_1_guia_con_una_revision_imagen_disponible(tmp_path):
    _crear_entrada_desktop(tmp_path, "20260831_100000", "472700.jpeg")
    resultado = resolver_ruta_evidencia(tmp_path, "472700.jpeg")
    assert resultado.ubicacion == UBICACION_ACTIVA_DESKTOP
    assert resultado.ruta is not None and resultado.ruta.is_file()


def test_2_guia_con_tres_revisiones_una_sola_imagen_referenciada(tmp_path):
    """Caso real del bloque: 472700 con CLIENTE/OBRA_DESTINO/PATENTE --
    las 3 decisiones referencian el MISMO `archivo`; resolver_ruta_
    evidencia siempre devuelve la misma ruta física, nunca 3 copias."""
    _crear_entrada_desktop(tmp_path, "20260831_100000", "472700.jpeg")
    bandeja = _bandeja(
        _decision("472700.jpeg", decision_id="d1"),
        _decision("472700.jpeg", decision_id="d2"),
        _decision("472700.jpeg", decision_id="d3"),
    )
    pendientes = documentos_con_revision_pendiente(bandeja)
    assert pendientes == frozenset({"472700.jpeg"})
    r1 = resolver_ruta_evidencia(tmp_path, "472700.jpeg")
    r2 = resolver_ruta_evidencia(tmp_path, "472700.jpeg")
    assert r1.ruta == r2.ruta
    # Un único archivo físico en disco -- nunca 3.
    assert list((tmp_path / "operacion" / "entradas" / "20260831_100000").iterdir()) == [r1.ruta]


# ============================================================
# 3/4. Resolver 1 de 3 -> imagen permanece activa. Resolver 3 de 3 ->
#      imagen pasa a evidencia resuelta.
# ============================================================


def test_3_resolver_una_de_tres_la_imagen_permanece_activa(tmp_path):
    _crear_entrada_desktop(tmp_path, "20260831_100000", "472700.jpeg")
    bandeja = _bandeja(
        _decision("472700.jpeg", decision_id="d1"),
        _decision("472700.jpeg", decision_id="d2", estado="RESUELTA"),
        _decision("472700.jpeg", decision_id="d3", estado="RESUELTA"),
    )
    resultado = mover_evidencia_resuelta_sin_revision_pendiente(
        tmp_path, decisiones_pendientes=bandeja, reloj=lambda: FECHA_BASE,
    )
    assert resultado["movidos"] == []
    r = resolver_ruta_evidencia(tmp_path, "472700.jpeg")
    assert r.ubicacion == UBICACION_ACTIVA_DESKTOP


def test_4_resolver_las_tres_la_imagen_pasa_a_evidencia_resuelta(tmp_path):
    _crear_entrada_desktop(tmp_path, "20260831_100000", "472700.jpeg")
    bandeja = _bandeja(
        _decision("472700.jpeg", decision_id="d1", estado="RESUELTA"),
        _decision("472700.jpeg", decision_id="d2", estado="RESUELTA"),
        _decision("472700.jpeg", decision_id="d3", estado="RESUELTA"),
    )
    resultado = mover_evidencia_resuelta_sin_revision_pendiente(
        tmp_path, decisiones_pendientes=bandeja, reloj=lambda: FECHA_BASE,
    )
    assert resultado["movidos"] == ["472700.jpeg"]
    r = resolver_ruta_evidencia(tmp_path, "472700.jpeg")
    assert r.ubicacion == UBICACION_EVIDENCIA_RESUELTA
    assert r.ruta is not None and r.ruta.is_file()
    # El lote vacío se retira; la imagen ya no está en "activa".
    assert not (tmp_path / "operacion" / "entradas" / "20260831_100000").exists()
    # Metadata permanente correcta.
    carpeta = next((tmp_path / "operacion" / "evidencia_resuelta").iterdir())
    metadata = json.loads((carpeta / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["archivo"] == "472700.jpeg"
    assert metadata["procedencia"] == "DESKTOP"
    assert metadata["hash_sha256"]
    assert metadata["fecha_resolucion"] == FECHA_BASE.isoformat()
    assert metadata["binario_eliminado"] is False


# ============================================================
# 5/6/7. Política de 30 días.
# ============================================================


def _mover_y_avanzar_reloj(tmp_path, *, dias_desde_resolucion):
    _crear_entrada_desktop(tmp_path, "20260801_000000", "472701.jpeg")
    bandeja_resuelta = _bandeja(_decision("472701.jpeg", estado="RESUELTA"))
    mover_evidencia_resuelta_sin_revision_pendiente(
        tmp_path, decisiones_pendientes=bandeja_resuelta, reloj=lambda: FECHA_BASE,
    )
    reloj_purga = lambda: FECHA_BASE + timedelta(days=dias_desde_resolucion)
    return bandeja_resuelta, reloj_purga


def test_5_imagen_resuelta_antes_de_30_dias_permanece(tmp_path):
    bandeja, reloj_purga = _mover_y_avanzar_reloj(tmp_path, dias_desde_resolucion=29)
    resultado = purgar_evidencia_resuelta_vencida(tmp_path, decisiones_pendientes=bandeja, reloj=reloj_purga)
    assert resultado["purgados"] == []
    r = resolver_ruta_evidencia(tmp_path, "472701.jpeg")
    assert r.ubicacion == UBICACION_EVIDENCIA_RESUELTA


def test_6_imagen_resuelta_despues_de_30_dias_es_purgable(tmp_path):
    bandeja, reloj_purga = _mover_y_avanzar_reloj(tmp_path, dias_desde_resolucion=31)
    resultado = purgar_evidencia_resuelta_vencida(tmp_path, decisiones_pendientes=bandeja, reloj=reloj_purga)
    assert resultado["purgados"] == ["472701.jpeg"]
    r = resolver_ruta_evidencia(tmp_path, "472701.jpeg")
    assert r.ubicacion == UBICACION_PURGADA  # nunca NO_ENCONTRADA -- se distingue
    # Metadata permanente sigue existiendo tras purgar el binario.
    carpeta = next((tmp_path / "operacion" / "evidencia_resuelta").iterdir())
    metadata = json.loads((carpeta / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["binario_eliminado"] is True
    assert metadata["archivo"] == "472701.jpeg"
    assert metadata["hash_sha256"]
    assert metadata["fecha_resolucion"]
    assert metadata["procedencia"] == "DESKTOP"
    assert "purgado_en" in metadata


def test_7_documento_con_revision_reabierta_nunca_se_purga_aunque_pase_el_plazo(tmp_path):
    """Salvaguarda activa: si el documento vuelve a tener una decisión
    PENDIENTE (p. ej. reabierta), purgar_evidencia_resuelta_vencida
    nunca borra su binario, sin importar la antigüedad."""
    _, reloj_purga = _mover_y_avanzar_reloj(tmp_path, dias_desde_resolucion=90)
    bandeja_reabierta = _bandeja(_decision("472701.jpeg", estado="PENDIENTE"))
    resultado = purgar_evidencia_resuelta_vencida(
        tmp_path, decisiones_pendientes=bandeja_reabierta, reloj=reloj_purga,
    )
    assert resultado["purgados"] == []
    r = resolver_ruta_evidencia(tmp_path, "472701.jpeg")
    assert r.ubicacion == UBICACION_EVIDENCIA_RESUELTA
    assert r.ruta is not None and r.ruta.is_file()


def test_retencion_por_defecto_es_30_dias():
    assert RETENCION_EVIDENCIA_RESUELTA_DIAS == 30


# ============================================================
# 8/9. Mobile y Desktop resolubles.
# ============================================================


def test_8_documento_mobile_es_resoluble(tmp_path):
    _crear_envio_mobile(tmp_path, "16cda9ea-fbe9-4db1-a77a-631f39fc6cdf", "original.jpg")
    r = resolver_ruta_evidencia(tmp_path, "mobile/16cda9ea-fbe9-4db1-a77a-631f39fc6cdf/original.jpg")
    assert r.ubicacion == UBICACION_ACTIVA_MOBILE
    assert r.ruta is not None and r.ruta.is_file()


def test_9_documento_desktop_es_resoluble(tmp_path):
    _crear_entrada_desktop(tmp_path, "20260831_100000", "472702.jpeg")
    r = resolver_ruta_evidencia(tmp_path, "472702.jpeg")
    assert r.ubicacion == UBICACION_ACTIVA_DESKTOP


def test_documento_inexistente_nunca_inventa_una_ruta(tmp_path):
    r = resolver_ruta_evidencia(tmp_path, "no-existe.jpeg")
    assert r.ubicacion == UBICACION_NO_ENCONTRADA
    assert r.ruta is None


def test_evidencia_mobile_nunca_se_mueve_ni_se_purga(tmp_path):
    """Fuera de alcance deliberado (ver docstring del módulo): mover_
    evidencia_resuelta_sin_revision_pendiente sólo opera sobre
    evidencia de origen Desktop -- Mobile permanece exactamente donde
    el sistema ya la deja."""
    _crear_envio_mobile(tmp_path, "9fb768e4-b385-4beb-a1ca-e8baa306cefe", "original.jpg")
    bandeja = _bandeja()  # sin ninguna decisión pendiente
    resultado = mover_evidencia_resuelta_sin_revision_pendiente(
        tmp_path, decisiones_pendientes=bandeja, reloj=lambda: FECHA_BASE,
    )
    assert resultado["movidos"] == []
    r = resolver_ruta_evidencia(tmp_path, "mobile/9fb768e4-b385-4beb-a1ca-e8baa306cefe/original.jpg")
    assert r.ubicacion == UBICACION_ACTIVA_MOBILE


def test_documentos_con_revision_pendiente_ignora_resueltas_y_pospuestas_correctamente():
    bandeja = _bandeja(
        _decision("A.jpeg", estado="PENDIENTE"),
        _decision("B.jpeg", estado="RESUELTA"),
    )
    assert documentos_con_revision_pendiente(bandeja) == frozenset({"A.jpeg"})


def test_bandeja_vacia_o_invalida_nunca_lanza():
    assert documentos_con_revision_pendiente({}) == frozenset()
    assert documentos_con_revision_pendiente({"decisiones": "no-es-lista"}) == frozenset()
