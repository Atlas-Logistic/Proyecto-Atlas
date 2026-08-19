"""Verificación externa -- interfaz general, sin acoplarse a un buscador
concreto. Usa fixtures deterministas (nunca red real dentro de la suite);
el caso SIGRO usa una evidencia REAL capturada por el agente (ver
`tests/fixtures_verificacion_externa.py`), nunca inventada."""
from __future__ import annotations

import pytest

from atlas_core.verificacion_externa import (
    TIPO_FUENTE_AUXILIAR, TIPO_FUENTE_CORPORATIVO, TIPO_FUENTE_OFICIAL,
    CacheVerificacionExterna, EvidenciaExterna, ProveedorVerificacionFijo,
)


def test_evidencia_externa_rechaza_tipo_fuente_no_soportado():
    with pytest.raises(ValueError):
        EvidenciaExterna(fuente="x", tipo_fuente="INVENTADO", url="https://x", fecha_consulta="2026-08-19T00:00:00+00:00")


def test_evidencia_externa_serializa_y_reconstruye_completa():
    original = EvidenciaExterna(
        fuente="web.sigro.cl", tipo_fuente=TIPO_FUENTE_CORPORATIVO, url="https://web.sigro.cl/en/home/",
        fecha_consulta="2026-08-19T20:00:00+00:00", razon_social="SIGRO S.A.",
        campos_corroborados=("razon_social", "direccion"), contradicciones=(),
    )
    reconstruida = EvidenciaExterna.desde_dict(original.a_dict())
    assert reconstruida == original


def test_proveedor_fijo_nunca_hace_red_y_devuelve_tupla_vacia_sin_hallazgos():
    proveedor = ProveedorVerificacionFijo({})
    resultado = proveedor.consultar(razon_social="CUALQUIER COSA")
    assert resultado == ()


def test_proveedor_fijo_devuelve_exactamente_lo_guardado():
    evidencia = EvidenciaExterna(
        fuente="dequienes.cl", tipo_fuente=TIPO_FUENTE_AUXILIAR, url="https://dequienes.cl/x",
        fecha_consulta="2026-08-19T20:00:00+00:00", razon_social="EMPRESA CONSTRUCTORA SIGRO S.A.",
    )
    proveedor = ProveedorVerificacionFijo({"EMPRESA CONST SIGRO SA": (evidencia,)})
    resultado = proveedor.consultar(razon_social="EMPRESA CONST SIGRO SA")
    assert resultado == (evidencia,)


def test_cache_evita_reconsultar_una_entidad_ya_corroborada():
    cache = CacheVerificacionExterna()
    assert cache.obtener("89037500-6") is None
    evidencia = EvidenciaExterna(
        fuente="web.sigro.cl", tipo_fuente=TIPO_FUENTE_OFICIAL, url="https://web.sigro.cl",
        fecha_consulta="2026-08-19T20:00:00+00:00", razon_social="SIGRO S.A.",
    )
    cache.guardar("89037500-6", (evidencia,), fecha="2026-08-19T20:00:00+00:00")
    assert cache.obtener("89037500-6") == (evidencia,)


def test_cache_serializa_y_reconstruye():
    cache = CacheVerificacionExterna()
    evidencia = EvidenciaExterna(
        fuente="f", tipo_fuente=TIPO_FUENTE_AUXILIAR, url="https://f", fecha_consulta="2026-08-19T20:00:00+00:00",
    )
    cache.guardar("clave", (evidencia,), fecha="2026-08-19T20:00:00+00:00")
    reconstruida = CacheVerificacionExterna.desde_dict(cache.a_dict())
    assert reconstruida.obtener("clave") == (evidencia,)
