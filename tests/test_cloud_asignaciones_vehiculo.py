from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from atlas_core.cloud_asignaciones_vehiculo import (
    AsignacionPublicable, ErrorPublicacionAsignaciones, construir_snapshot_asignaciones, publicar_snapshot_asignaciones,
)


AHORA = datetime(2026, 10, 22, tzinfo=timezone.utc)


def _vehiculo(patente, rut, *, fecha=AHORA, activo=True):
    evidencia = SimpleNamespace(tipo="CONFIRMACION_HUMANA", resultado="SOPORTA", fecha=fecha.isoformat(),
                                campos_observados={"rut_chofer_asociado": rut})
    return SimpleNamespace(patente_canonica=patente, estado_calidad="CONFIRMADO",
                           estado_vigencia="ACTIVO" if activo else "INACTIVO", evidencias=(evidencia,))


def _snapshot(vehiculos, mapeo):
    return construir_snapshot_asignaciones(
        choferes={"111111111": {"activo": True}, "222222222": {"activo": True}}, vehiculos=vehiculos,
        ahora=AHORA, resolver_chofer_cloud=lambda rut: mapeo.get(rut),
    )


def test_publica_solo_confirmada_unica_y_mapeada():
    asignaciones, descartes = _snapshot([_vehiculo("AB1234", "11.111.111-1")], {"111111111": "chofer-a"})
    assert [(a.chofer_id, a.patente) for a in asignaciones] == [("chofer-a", "AB1234")]
    assert descartes == []


def test_cambio_vehiculo_ambiguo_revoca_por_snapshot_vacio():
    asignaciones, descartes = _snapshot(
        [_vehiculo("AB1234", "11.111.111-1"), _vehiculo("CD5678", "11.111.111-1")],
        {"111111111": "chofer-a"},
    )
    assert asignaciones == []
    assert descartes == [{"rut": "111111111", "patente": "", "motivo": "ASIGNACION_AMBIGUA"}]


def test_inexistente_antigua_o_de_otra_empresa_no_sale_en_snapshot():
    antigua = _vehiculo("AB1234", "11.111.111-1", fecha=AHORA - timedelta(days=32))
    inexistente = _vehiculo("CD5678", "22.222.222-2")
    asignaciones, descartes = _snapshot([antigua, inexistente], {"111111111": "chofer-a"})
    assert asignaciones == []
    assert descartes == [{"rut": "222222222", "patente": "CD5678", "motivo": "CHOFER_CLOUD_NO_MAPEADO"}]


def test_publicador_no_envia_empresa_y_exige_https(monkeypatch):
    with pytest.raises(ErrorPublicacionAsignaciones, match="HTTPS"):
        publicar_snapshot_asignaciones(base_url="http://cloud.local", token_motor="secreto", asignaciones=[])

    vistos = []
    class Respuesta:
        def read(self): return b'{"estado":"SNAPSHOT_APLICADO","revocadas":0}'
        def __enter__(self): return self
        def __exit__(self, *_): return False
    monkeypatch.setattr("urllib.request.urlopen", lambda solicitud, timeout: vistos.append(solicitud) or Respuesta())
    publicar_snapshot_asignaciones(
        base_url="https://cloud.local", token_motor="token-empresa-a",
        asignaciones=[AsignacionPublicable("chofer-a", "AB1234", AHORA.isoformat())],
    )
    cuerpo = vistos[0].data.decode("utf-8")
    # Empresa A/B se separan en Cloud por el token Motor; el cliente no puede
    # introducir una empresa distinta en el cuerpo y saltar ese aislamiento.
    assert "empresa_id" not in cuerpo
    assert vistos[0].get_header("Authorization") == "Bearer token-empresa-a"
