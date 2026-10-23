"""Homologación de patente con número de guía ilegible (caso real 482995).

El envío Mobile ae70a62b (Salomón Pizarro, tracto TG8925, rampla impresa
"JF9557") se leyó con guía "No encontrado". `enriquecer_decisiones_vehiculo`
buscaba la fila del documento por número de guía y tomaba la PRIMERA fila con
esa guía -- 473316 de otro chofer -- y evaluaba con su RUT e historial:
proponía JB6878/JK2501 (ajenas) y dejaba la tarjeta abierta en vez de homologar
a JF9575, el carro confirmado del propio chofer.
"""
from __future__ import annotations

from atlas_core.catalogo_vehiculos import TipoVehiculo, cargar_catalogo_vehiculos
from atlas_core.decisiones_pendientes import (
    RESULTADO_RESUELTO_AUTOMATICAMENTE,
    RESULTADO_SUGERENCIA_HUMANA,
    crear_decision,
    enriquecer_decisiones_vehiculo,
)
from tests.test_motor_evidencia_vehiculos import _catalogo, _confirmar, _fila

RUT_SALOMON = "18091588-5"
RUT_LAZCANO = "10833150-K"
ARCHIVO = "mobile/ae70a62b/original.jpg"


def _tarjeta(*, archivo=ARCHIVO, guia="No encontrado", valor="JF9557"):
    return crear_decision(
        tipo="VEHICULO_DESCONOCIDO", entidad="VEHICULO", archivo=archivo, numero_guia=guia,
        numero_transporte="0000365827", campo="patente_rampla", valor_documental=valor, valor_normalizado=valor,
        identidad_resuelta=None, candidatos=(), motivos=("SIN_VEHICULO_CONFIRMADO_COMPATIBLE",), evidencias=(),
        acciones_permitidas=("REGISTRAR", "NO_REGISTRAR", "POSPONER"), tipo_vehiculo_propuesto="CARRO",
    )


def _escenario(tmp_path, *, rampla_documento="JF9557", extra_confirmados=()):
    """Salomón con JF9575 confirmado e historial; Lazcano (otra guía ilegible) con JB6878/JK2501."""
    ruta = _catalogo(tmp_path)
    _confirmar(ruta, "TG8925", TipoVehiculo.TRACTO, rut_chofer_asociado=RUT_SALOMON)
    _confirmar(ruta, "JF9575", TipoVehiculo.CARRO, rut_chofer_asociado=RUT_SALOMON)
    _confirmar(ruta, "ND6443", TipoVehiculo.TRACTO, rut_chofer_asociado=RUT_LAZCANO)
    _confirmar(ruta, "JB6878", TipoVehiculo.CARRO, rut_chofer_asociado=RUT_LAZCANO)
    _confirmar(ruta, "JK2501", TipoVehiculo.CARRO)
    for patente in extra_confirmados:
        _confirmar(ruta, patente, TipoVehiculo.CARRO, rut_chofer_asociado=RUT_SALOMON)
    filas = [
        # Otro documento con guía ilegible, primero en el dataset (473316 / 477355).
        _fila(archivo="473316.jpeg", numero_guia="No encontrado", numero_transporte="0000357091",
              rut_chofer=RUT_LAZCANO, patente_tracto="ND6443", patente_rampla="JB6878"),
        _fila(archivo="477355.jpeg", numero_guia="No encontrado", numero_transporte="0000357789",
              rut_chofer=RUT_LAZCANO, patente_tracto="ND6443", patente_rampla="JK2501"),
        # Historial independiente de Salomón con su carro confirmado.
        *(_fila(archivo=f"h{i}.jpeg", numero_guia=f"47500{i}", numero_transporte=f"00003610{i}",
                rut_chofer=RUT_SALOMON, patente_tracto="TG8925", patente_rampla="JF9575") for i in range(3)),
        # El propio documento.
        _fila(archivo=ARCHIVO, numero_guia="No encontrado", numero_transporte="0000365827",
              rut_chofer=RUT_SALOMON, patente_tracto="TG8925", patente_rampla=rampla_documento),
    ]
    return filas, cargar_catalogo_vehiculos(ruta).homologables()


def _evaluar(filas, vehiculos, tarjeta):
    salida = enriquecer_decisiones_vehiculo(decisiones=[tarjeta], filas=filas, vehiculos=vehiculos)[0]
    # Sin fila inequívoca no hay evaluación: la tarjeta queda tal cual, para revisión humana.
    resultado = (salida.get("evaluacion_evidencia") or {}).get("resultado")
    return resultado, [c["patente"] for c in salida.get("candidatos") or []]


def test_482995_guia_ilegible_homologa_al_carro_del_propio_chofer(tmp_path):
    filas, vehiculos = _escenario(tmp_path)
    resultado, patentes = _evaluar(filas, vehiculos, _tarjeta())
    assert resultado == RESULTADO_RESUELTO_AUTOMATICAMENTE
    assert patentes[0] == "JF9575"
    assert not {"JB6878", "JK2501"} & set(patentes)  # nunca el historial de otro chofer


def test_482995_mismo_resultado_con_la_guia_ya_corregida(tmp_path):
    filas, vehiculos = _escenario(tmp_path)
    filas[-1]["numero_guia"] = "482995"
    resultado, patentes = _evaluar(filas, vehiculos, _tarjeta(guia="482995"))
    assert (resultado, patentes[0]) == (RESULTADO_RESUELTO_AUTOMATICAMENTE, "JF9575")


def test_sustitucion_de_un_caracter_tambien_homologa(tmp_path):
    filas, vehiculos = _escenario(tmp_path, rampla_documento="JF9576")
    resultado, patentes = _evaluar(filas, vehiculos, _tarjeta(valor="JF9576"))
    assert (resultado, patentes[0]) == (RESULTADO_RESUELTO_AUTOMATICAMENTE, "JF9575")


def test_dos_candidatos_plausibles_del_mismo_chofer_conservan_revision_humana(tmp_path):
    filas, vehiculos = _escenario(tmp_path, extra_confirmados=("JF9555",))
    filas.extend(_fila(archivo=f"k{i}.jpeg", numero_guia=f"47600{i}", numero_transporte=f"00003620{i}",
                       rut_chofer=RUT_SALOMON, patente_tracto="TG8925", patente_rampla="JF9555") for i in range(3))
    resultado, patentes = _evaluar(filas, vehiculos, _tarjeta())
    assert resultado == RESULTADO_SUGERENCIA_HUMANA
    assert {"JF9575", "JF9555"} <= set(patentes)


def test_archivo_repetido_no_elige_una_fila_y_se_abstiene_de_homologar(tmp_path):
    filas, vehiculos = _escenario(tmp_path)
    filas.append(dict(filas[-1], rut_chofer=RUT_LAZCANO))  # dos filas para el mismo archivo
    resultado, patentes = _evaluar(filas, vehiculos, _tarjeta())
    assert resultado != RESULTADO_RESUELTO_AUTOMATICAMENTE
    assert patentes == []


def test_sin_archivo_la_guia_solo_sirve_si_es_legible_y_unica(tmp_path):
    filas, vehiculos = _escenario(tmp_path)
    sin_archivo = _tarjeta(archivo="")
    assert _evaluar(filas, vehiculos, sin_archivo)[1] == []  # "No encontrado" nunca identifica una fila
    filas[-1]["numero_guia"] = "482995"
    assert _evaluar(filas, vehiculos, _tarjeta(archivo="", guia="482995"))[1][0] == "JF9575"
