"""Publicación Motor -> Cloud de la asignación vigente confirmada de vehículo.

Sólo el tracto CONFIRMADO por asignación humana de choferes activos; nunca
el historial de viajes, un conflicto ni un catálogo ilegible (que no debe
revocar todo en Cloud). Catálogos sintéticos.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from atlas_core import cloud_asignaciones_vehiculo as modulo
from atlas_core.catalogo_vehiculos import TipoVehiculo, asociar_chofer_a_vehiculo_confirmado
from tests.test_motor_evidencia_vehiculos import _catalogo, _confirmar

SALOMON, LAZCANO, RENE, INACTIVO = "180915885", "10833150K", "97082251", "78143109"


def _asignar(ruta, patente, rut, dia):
    asociar_chofer_a_vehiculo_confirmado(
        ruta, patente=patente, actor="JAVIER", fuente_decision="TEST", rut_chofer_asociado=rut,
        fecha=datetime(2026, 10, dia, tzinfo=timezone.utc),
    )


@pytest.fixture
def raiz(tmp_path):
    carpeta = tmp_path / "catalogos_privados"
    carpeta.mkdir()
    ruta = _catalogo(carpeta)
    for patente, tipo in (("TG8925", TipoVehiculo.TRACTO), ("JF9575", TipoVehiculo.CARRO), ("ND6443", TipoVehiculo.TRACTO),
                          ("BB1234", TipoVehiculo.TRACTO), ("CC5678", TipoVehiculo.TRACTO), ("DD9012", TipoVehiculo.TRACTO)):
        _confirmar(ruta, patente, tipo)
    _asignar(ruta, "TG8925", SALOMON, 1)
    _asignar(ruta, "JF9575", SALOMON, 1)  # carro: no se publica
    _asignar(ruta, "ND6443", LAZCANO, 1)
    _asignar(ruta, "BB1234", LAZCANO, 2)  # dos tractos vigentes: conflicto
    _asignar(ruta, "DD9012", INACTIVO, 1)
    (carpeta / "choferes.json").write_text(json.dumps({
        SALOMON: {"nombre": "SALOMON SINTETICO", "activo": True},
        LAZCANO: {"nombre": "LAZCANO SINTETICO", "activo": True},
        RENE: {"nombre": "RENE SINTETICO", "activo": True},  # sin asignación (CC5678 sin chofer)
        INACTIVO: {"nombre": "INACTIVO SINTETICO", "activo": False},
    }), encoding="utf-8")
    return tmp_path


def test_publica_solo_tracto_confirmado_de_choferes_activos(raiz):
    assert modulo.asignaciones_publicables(raiz) == [{"chofer_id": SALOMON, "patente": "TG8925"}]


def test_viajes_historicos_no_crean_asignacion(raiz):
    # Un vehículo confirmado sin asignación humana no se asocia a nadie,
    # aunque el chofer haya viajado en él (los viajes no se leen).
    (raiz / "reportes").mkdir()
    assert all(a["patente"] != "CC5678" for a in modulo.asignaciones_publicables(raiz))


def test_envia_el_conjunto_completo_bajo_lease(raiz, monkeypatch):
    llamadas = []
    monkeypatch.setattr(modulo, "_json", lambda base, ruta, token, **kw: llamadas.append((ruta, kw)) or {"asignaciones": 1, "cambios": 1})
    r = modulo.publicar_asignaciones_cloud(base_url="https://cloud.local", token_motor="t", raiz=raiz, timeout=5, puede_continuar=lambda: True)
    assert r == {"publicadas": 1, "cambios": 1}
    assert llamadas == [("/api/motor/asignaciones/vehiculos", {"method": "POST", "body": {"asignaciones": [{"chofer_id": SALOMON, "patente": "TG8925"}]}, "timeout": 5})]
    llamadas.clear()
    r = modulo.publicar_asignaciones_cloud(base_url="https://cloud.local", token_motor="t", raiz=raiz, timeout=5, puede_continuar=lambda: False)
    assert r["detenido_por_escritor"] is True and llamadas == []


@pytest.mark.parametrize("dañar", ["vehiculos", "choferes"])
def test_catalogo_ilegible_no_publica_nada(raiz, monkeypatch, dañar):
    llamadas = []
    monkeypatch.setattr(modulo, "_json", lambda *a, **kw: llamadas.append(a) or {})
    (raiz / "catalogos_privados" / f"{dañar}.json").write_text("{roto", encoding="utf-8")
    r = modulo.publicar_asignaciones_cloud(base_url="https://cloud.local", token_motor="t", raiz=raiz, timeout=5, puede_continuar=lambda: True)
    assert r["publicadas"] is None and "catálogo no disponible" in r["error"]
    assert llamadas == []
