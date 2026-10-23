"""Asignación vigente única chofer-camión y homologación de errores menores.

Cada camión tiene un único chofer vigente (su asignación confirmada más
reciente, `CHOFER_ASIGNAR_VEHICULO`/`confirmar_vehiculo`). Con el chofer
identificado y su camión vigente confirmado, una lectura a una edición
(sustitución, omisión, adición, transposición) se homologa sola; los choferes
históricos no compiten y nunca se deduce una asignación de los viajes.
Casos reales: 482995 (JF9557 -> JF9575) y 483017 (A21879 -> AL1879).
"""
from __future__ import annotations

from datetime import datetime, timezone

from atlas_core.catalogo_vehiculos import TipoVehiculo, asociar_chofer_a_vehiculo_confirmado, cargar_catalogo_vehiculos
from atlas_core.catalogos import normalizar_rut
from atlas_core.decisiones_pendientes import (
    RESULTADO_RESUELTO_AUTOMATICAMENTE,
    _asignaciones_vigentes,
    evaluar_evidencia_patente,
)
from tests.test_motor_evidencia_vehiculos import _catalogo, _confirmar, _fila

SALOMON, RENE, LAZCANO = "18091588-5", "9708225-1", "10833150-K"


def _asignar(ruta, patente, rut, dia):
    asociar_chofer_a_vehiculo_confirmado(
        ruta, patente=patente, actor="JAVIER", fuente_decision="TEST", rut_chofer_asociado=rut,
        fecha=datetime(2026, 10, dia, tzinfo=timezone.utc),
    )


def _evaluar(ruta, *, campo, valor, rut, tipo=None, filas=()):
    return evaluar_evidencia_patente(
        campo=campo, valor_documental=valor, rut_chofer=rut, tipo_esperado=tipo,
        numero_transporte_actual="T-ACTUAL", filas=list(filas), vehiculos=cargar_catalogo_vehiculos(ruta).homologables(),
    )


def _flota(tmp_path):
    ruta = _catalogo(tmp_path)
    for patente, tipo in (("TG8925", TipoVehiculo.TRACTO), ("JF9575", TipoVehiculo.CARRO), ("AL1879", TipoVehiculo.TRACTO),
                          ("JK2501", TipoVehiculo.CARRO), ("ND6443", TipoVehiculo.TRACTO), ("JB6878", TipoVehiculo.CARRO)):
        _confirmar(ruta, patente, tipo)
    _asignar(ruta, "TG8925", SALOMON, 1)
    _asignar(ruta, "JF9575", SALOMON, 1)
    _asignar(ruta, "ND6443", LAZCANO, 1)
    _asignar(ruta, "JB6878", LAZCANO, 1)
    return ruta


def _resuelve(resultado, patente):
    return resultado["resultado"] == RESULTADO_RESUELTO_AUTOMATICAMENTE and resultado["ganadora"] == patente


def test_482995_transposicion_al_carro_vigente_se_homologa(tmp_path):
    ruta = _flota(tmp_path)
    assert _resuelve(_evaluar(ruta, campo="patente_rampla", valor="JF9557", rut=SALOMON, tipo="CARRO"), "JF9575")


def test_483017_sin_asignacion_vigente_conserva_revision_aunque_haya_historial(tmp_path):
    ruta = _flota(tmp_path)
    historial = [_fila(numero_guia=str(i), numero_transporte=f"T-{i}", rut_chofer=RENE, patente_tracto="AL1879")
                 for i in range(14)]
    resultado = _evaluar(ruta, campo="patente_tracto", valor="A21879", rut=RENE, filas=historial)
    assert resultado["resultado"] != RESULTADO_RESUELTO_AUTOMATICAMENTE  # el historial no es asignación
    assert resultado["candidatos"][0]["patente"] == "AL1879"


def test_483017_con_asignacion_vigente_se_homologa_sin_tipo_propuesto(tmp_path):
    ruta = _flota(tmp_path)
    _asignar(ruta, "AL1879", RENE, 2)
    assert _resuelve(_evaluar(ruta, campo="patente_tracto", valor="A21879", rut=RENE), "AL1879")


def test_omision_y_adicion_de_un_caracter_se_homologan_al_camion_vigente(tmp_path):
    ruta = _flota(tmp_path)
    _asignar(ruta, "AL1879", RENE, 2)
    assert _resuelve(_evaluar(ruta, campo="patente_tracto", valor="AL879", rut=RENE), "AL1879")
    assert _resuelve(_evaluar(ruta, campo="patente_tracto", valor="AL18799", rut=RENE), "AL1879")


def test_chofer_historico_no_compite_con_el_vigente(tmp_path):
    ruta = _flota(tmp_path)
    _asignar(ruta, "AL1879", RENE, 2)
    _asignar(ruta, "AL1879", LAZCANO, 5)  # reasignado explícitamente: René pasa a historial
    vigentes = _asignaciones_vigentes(cargar_catalogo_vehiculos(ruta).homologables())
    assert vigentes["AL1879"] == (normalizar_rut(LAZCANO), "TRACTO")
    assert not _resuelve(_evaluar(ruta, campo="patente_tracto", valor="AL1878", rut=RENE), "AL1879")


def test_cambio_explicito_de_camion_del_chofer(tmp_path):
    ruta = _flota(tmp_path)
    _confirmar(ruta, "BB1234", TipoVehiculo.TRACTO)
    # Javier informa el cambio: Salomón pasa a BB1234 y TG8925 queda con Luis Reyes.
    _asignar(ruta, "BB1234", SALOMON, 9)
    _asignar(ruta, "TG8925", "7814310-K", 9)
    vigentes = _asignaciones_vigentes(cargar_catalogo_vehiculos(ruta).homologables())
    assert vigentes["BB1234"] == (normalizar_rut(SALOMON), "TRACTO")
    assert vigentes["TG8925"] == (normalizar_rut("7814310-K"), "TRACTO")
    assert vigentes["JF9575"] == (normalizar_rut(SALOMON), "CARRO")  # el carro no cambia
    assert _resuelve(_evaluar(ruta, campo="patente_tracto", valor="BB1243", rut=SALOMON), "BB1234")
    assert not _resuelve(_evaluar(ruta, campo="patente_tracto", valor="TG8952", rut=SALOMON), "TG8925")


def test_dos_camiones_vigentes_del_mismo_tipo_son_contradiccion(tmp_path):
    ruta = _flota(tmp_path)
    _confirmar(ruta, "BB1234", TipoVehiculo.TRACTO)
    _asignar(ruta, "BB1234", SALOMON, 9)  # sin reasignar TG8925: dos tractos vigentes
    assert not _resuelve(_evaluar(ruta, campo="patente_tracto", valor="BB1243", rut=SALOMON), "BB1234")


def test_tracto_y_carro_no_se_corrigen_entre_si(tmp_path):
    ruta = _flota(tmp_path)
    # Una lectura del campo tracto parecida al CARRO vigente nunca se homologa al carro.
    resultado = _evaluar(ruta, campo="patente_tracto", valor="JF9557", rut=SALOMON)
    assert not _resuelve(resultado, "JF9575")


def test_patente_genuinamente_desconocida_mantiene_la_tarjeta(tmp_path):
    ruta = _flota(tmp_path)
    resultado = _evaluar(ruta, campo="patente_rampla", valor="XX0000", rut=SALOMON, tipo="CARRO")
    assert resultado["resultado"] != RESULTADO_RESUELTO_AUTOMATICAMENTE


def test_otro_vehiculo_igual_de_cercano_es_ambiguo(tmp_path):
    ruta = _flota(tmp_path)
    _confirmar(ruta, "JF9576", TipoVehiculo.CARRO)  # otro carro a una edición de la lectura
    resultado = _evaluar(ruta, campo="patente_rampla", valor="JF9570", rut=SALOMON, tipo="CARRO")
    assert resultado["resultado"] != RESULTADO_RESUELTO_AUTOMATICAMENTE
