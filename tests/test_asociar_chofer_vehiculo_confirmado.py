"""Bloque ASIGNACIONES CANÓNICAS CHOFER->VEHÍCULO --
`asociar_chofer_a_vehiculo_confirmado`. Caso real: TG8925/JF9575 ya
confirmados por Javier (lote CONFIRMACION_HUMANA_VEHICULOS_R2) SIN
vínculo a un chofer/RUT concreto -- esta función cierra ese hueco sin
re-confirmar el vehículo desde cero (lo que `confirmar_vehiculo`
rechaza con `VehiculoDuplicadoError`). Tests puramente sintéticos,
nunca tocan G:."""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from atlas_core.catalogo_vehiculos import (
    ErrorCatalogoVehiculos,
    TipoVehiculo,
    asociar_chofer_a_vehiculo_confirmado,
    cargar_catalogo_vehiculos,
    confirmar_vehiculo,
)


def _fecha():
    return datetime(2026, 9, 18, tzinfo=timezone.utc)


def _catalogo_vacio(ruta):
    ruta.write_text(json.dumps({"version": 1, "vehiculos": []}), encoding="utf-8")
    return ruta


def test_agrega_rut_chofer_asociado_sin_re_confirmar(tmp_path):
    ruta = _catalogo_vacio(tmp_path / "vehiculos.json")
    confirmar_vehiculo(
        ruta, patente="TG8925", tipo=TipoVehiculo.TRACTO, actor="JAVIER_MBT",
        fuente_decision="CONFIRMACION_HUMANA_VEHICULOS_R2", fecha=_fecha(),
        observaciones="Confirmación operacional previa, sin chofer asociado.",
    )
    vehiculo = asociar_chofer_a_vehiculo_confirmado(
        ruta, patente="TG8925", actor="JAVIER_MBT", fuente_decision="ASIGNACION_MBT_SALOMON_PIZARRO",
        fecha=_fecha(), rut_chofer_asociado="18091588-5",
        observaciones="Asignación operacional confirmada por Javier (MBT).",
    )
    assert vehiculo.patente_canonica == "TG8925"
    assert len(vehiculo.evidencias) == 2  # append-only: la original se conserva
    assert vehiculo.evidencias[0].campos_observados.get("rut_chofer_asociado") is None
    assert vehiculo.evidencias[1].campos_observados["rut_chofer_asociado"] == "18091588-5"


def test_nunca_crea_vehiculo_nuevo_si_la_patente_no_existe(tmp_path):
    ruta = tmp_path / "vehiculos.json"
    (ruta).write_text(json.dumps({"version": 1, "vehiculos": []}), encoding="utf-8")
    with pytest.raises(ErrorCatalogoVehiculos):
        asociar_chofer_a_vehiculo_confirmado(
            ruta, patente="TG8925", actor="JAVIER_MBT", fuente_decision="X",
            fecha=_fecha(), rut_chofer_asociado="18091588-5",
        )
    contenido = json.loads(ruta.read_text(encoding="utf-8"))
    assert contenido["vehiculos"] == []


def test_rechaza_vehiculo_inactivo(tmp_path):
    ruta = _catalogo_vacio(tmp_path / "vehiculos.json")
    confirmar_vehiculo(
        ruta, patente="ZZ0001", tipo=TipoVehiculo.TRACTO, actor="JAVIER_MBT",
        fuente_decision="X", fecha=_fecha(),
    )
    contenido = json.loads(ruta.read_text(encoding="utf-8"))
    for v in contenido["vehiculos"]:
        v["estado_vigencia"] = "INACTIVO"
    ruta.write_text(json.dumps(contenido), encoding="utf-8")
    with pytest.raises(ErrorCatalogoVehiculos):
        asociar_chofer_a_vehiculo_confirmado(
            ruta, patente="ZZ0001", actor="JAVIER_MBT", fuente_decision="X",
            fecha=_fecha(), rut_chofer_asociado="18091588-5",
        )


def test_resultado_es_utilizable_por_resolver_patente_operacional(tmp_path):
    """Confirma que la evidencia agregada por esta función es la MISMA
    que ya lee `_vehiculos_confirmados_para_rut` -- ningún mecanismo
    paralelo."""
    ruta = _catalogo_vacio(tmp_path / "vehiculos.json")
    confirmar_vehiculo(
        ruta, patente="TG8925", tipo=TipoVehiculo.TRACTO, actor="JAVIER_MBT",
        fuente_decision="CONFIRMACION_HUMANA_VEHICULOS_R2", fecha=_fecha(),
    )
    asociar_chofer_a_vehiculo_confirmado(
        ruta, patente="TG8925", actor="JAVIER_MBT", fuente_decision="ASIGNACION_MBT",
        fecha=_fecha(), rut_chofer_asociado="18091588-5",
    )
    vehiculos = list(cargar_catalogo_vehiculos(ruta).homologables())

    from atlas_core.convergencia_identidad_conocida import (
        RESULTADO_RESUELTO,
        resolver_patente_operacional_canonica_por_chofer,
    )
    choferes = {"180915885": {"nombre": "SALOMÓN PIZARRO", "activo": True}}
    resultado = resolver_patente_operacional_canonica_por_chofer(
        nombre_documental="SALOMÓN PIZARRO", rut_documental="18.091.588-5",
        choferes=choferes, vehiculos=vehiculos,
    )
    assert resultado.resultado == RESULTADO_RESUELTO
    assert resultado.patente == "TG8925"
