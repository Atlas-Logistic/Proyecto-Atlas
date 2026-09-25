"""Observabilidad del mantenimiento técnico: el resultado de una pasada
distingue lo que hizo con las elegibles de lo que hizo la reparación de
limbos (`_asegurar_via_humana`), que corre sobre TODA la cola.

Regresión del diagnóstico real del 25-09-2026: una pasada informó sólo
`elegibles=[474597]`/`pendientes=[474597]` aunque además publicó tarjetas
para dos guías ajenas y degradó otras dos a SIN_PREGUNTA_PUBLICABLE.
Todo sobre `tmp_path`, proveedores simulados, sin red.
"""
from __future__ import annotations

import json

import pytest

from atlas_core import mantenimiento_pendientes_tecnicos as mantenimiento
from atlas_core import reconciliacion_estado_derivado as reconciliacion
from test_ciclo_pendientes_tecnicos_simulado import AHORA, Operacion, _fila

AGOTABLE = "COORDENADA_NO_CONFIRMADA(5)"
DETERMINISTA = "GEOCODIFICACION_NUMERO_INCOMPATIBLE: 38 != 3800"
ELEGIBLE, LIMBO_CON_TARJETA, LIMBO_SIN_PREGUNTA = "480010", "480021", "480033"


def _sembrar_escenario(op: Operacion, *, con_elegible: bool = True) -> None:
    """Una elegible (AGOTABLE en cooldown vencido, 1 intento) + dos limbos
    ajenos: un AGOTABLE ya agotado (con pregunta publicable) y un
    DETERMINISTA cuya pregunta la política suprime."""
    op.confirmar_destino_de_obra(con_coordenadas=False)
    filas = [_fila(LIMBO_CON_TARJETA, AGOTABLE, op.planta_id), _fila(LIMBO_SIN_PREGUNTA, DETERMINISTA, op.planta_id)]
    if con_elegible:
        filas.insert(0, _fila(ELEGIBLE, AGOTABLE, op.planta_id))
    op.sembrar(filas)
    registros = op.pendientes()
    registros[LIMBO_CON_TARJETA]["intentos_misma_evidencia"] = 3
    op.escribir_pendientes(list(registros.values()))


@pytest.fixture
def op(tmp_path):
    return Operacion(tmp_path)


def test_una_elegible_y_dos_limbos_ajenos_quedan_distinguidos(op):
    _sembrar_escenario(op)
    resultado = op.mantener()

    assert [e["numero_guia"] for e in resultado["elegibles"]] == [ELEGIBLE]
    assert resultado["pendientes"] == [ELEGIBLE] and resultado["resueltas"] == []
    assert resultado["reporte_regenerado"] is False
    limbos = resultado["limbos"]
    assert limbos["detectados"] == [LIMBO_CON_TARJETA, LIMBO_SIN_PREGUNTA]
    assert limbos["fuera_de_elegibles"] == [LIMBO_CON_TARJETA, LIMBO_SIN_PREGUNTA]
    assert limbos["reparados_con_tarjeta"] == [LIMBO_CON_TARJETA]
    assert limbos["sin_pregunta_publicable"] == [LIMBO_SIN_PREGUNTA]
    assert limbos["ya_evaluados_sin_cambio"] == []


def test_tarjeta_publicada_por_reparacion_aparece_con_su_id_y_origen(op):
    _sembrar_escenario(op)
    resultado = op.mantener()
    (tarjeta,) = [d for d in op.decisiones() if d["documento"]["numero_guia"] == LIMBO_CON_TARJETA]
    assert resultado["tarjetas_publicadas"] == [{
        "decision_id": tarjeta["decision_id"], "numero_guia": LIMBO_CON_TARJETA,
        "tipo": "DESTINO_NO_RESUELTO", "origen": "REPARACION_LIMBO",
    }]
    assert resultado["tarjetas_retiradas"] == []


def test_guia_sin_pregunta_publicable_queda_explicita_y_con_su_estado(op):
    _sembrar_escenario(op)
    resultado = op.mantener()
    assert resultado["limbos"]["sin_pregunta_publicable"] == [LIMBO_SIN_PREGUNTA]
    registro = op.pendientes()[LIMBO_SIN_PREGUNTA]
    assert registro["estado_espera"] == "ESPERANDO_EVIDENCIA_NUEVA"
    assert registro["causa_siguiente_accion"] == reconciliacion.CAUSA_SIN_PREGUNTA_HUMANA_PUBLICABLE
    assert not [d for d in op.decisiones() if d["documento"]["numero_guia"] == LIMBO_SIN_PREGUNTA]


def test_observabilidad_no_cambia_elegibilidad_intentos_ni_artefactos(tmp_path, monkeypatch):
    """Misma pasada con y sin el informe: idénticos elegibles, intentos,
    pendientes_tecnicos.json y bandeja."""
    con_informe = Operacion(tmp_path / "a")
    _sembrar_escenario(con_informe)
    resultado = con_informe.mantener()

    sin_informe = Operacion(tmp_path / "b")
    _sembrar_escenario(sin_informe)
    original = reconciliacion._asegurar_via_humana
    monkeypatch.setattr(mantenimiento, "_asegurar_via_humana",
                        lambda **kw: original(**{k: v for k, v in kw.items() if k != "informe"}))
    monkeypatch.setattr(mantenimiento, "_observabilidad", lambda **kw: {})
    base = sin_informe.mantener()

    assert resultado["elegibles"] == base["elegibles"]
    assert resultado["pendientes"] == base["pendientes"]
    # huellas: incluyen ids aleatorios (planta, catálogos) de cada operación temporal.
    campos = ("numero_guia", "intentos_misma_evidencia", "ultimo_intento", "estado_espera",
              "causa_siguiente_accion", "clase_fallo", "proxima_oportunidad")
    vista = lambda op: {g: {c: r.get(c) for c in campos} for g, r in op.pendientes().items()}
    assert vista(con_informe) == vista(sin_informe)
    assert con_informe.pendientes()[ELEGIBLE]["intentos_misma_evidencia"] == 2
    assert con_informe.pendientes()[LIMBO_SIN_PREGUNTA]["intentos_misma_evidencia"] == 1
    tarjetas = lambda op: sorted((d["documento"]["numero_guia"], d["tipo"], d["estado"], tuple(d["motivos"]))
                                 for d in op.decisiones())
    assert tarjetas(con_informe) == tarjetas(sin_informe)


def test_sin_elegibles_tambien_reporta_reparaciones_de_limbo(op):
    _sembrar_escenario(op, con_elegible=False)
    resultado = op.mantener()
    assert resultado["ejecutado"] is False and resultado["elegibles"] == []
    # Rama sin elegibles: la reparación cambió la cola, por eso no es SIN_ELEGIBLES.
    assert resultado["motivo"] == "HUELLAS_ACTUALIZADAS"
    assert resultado["reporte_regenerado"] is False
    assert resultado["limbos"]["reparados_con_tarjeta"] == [LIMBO_CON_TARJETA]
    assert resultado["limbos"]["sin_pregunta_publicable"] == [LIMBO_SIN_PREGUNTA]
    assert [t["numero_guia"] for t in resultado["tarjetas_publicadas"]] == [LIMBO_CON_TARJETA]

    # Segunda pasada: la guía sin pregunta vuelve a detectarse pero NO se
    # reconsulta (misma evidencia): queda visible como ya evaluada.
    segunda = op.mantener()
    assert segunda["motivo"] == "SIN_ELEGIBLES"
    assert segunda["limbos"]["detectados"] == [LIMBO_SIN_PREGUNTA]
    assert segunda["limbos"]["ya_evaluados_sin_cambio"] == [LIMBO_SIN_PREGUNTA]
    assert segunda["limbos"]["reparados_con_tarjeta"] == segunda["limbos"]["sin_pregunta_publicable"] == []
    assert segunda["tarjetas_publicadas"] == segunda["tarjetas_retiradas"] == []


def test_resultado_es_json_serializable_para_el_log(op):
    _sembrar_escenario(op)
    json.dumps(op.mantener(), ensure_ascii=False)


def test_asegurar_via_humana_sin_informe_conserva_contrato(op):
    """El parámetro `informe` es opcional: el llamador de siempre
    (reconciliación) no cambia."""
    op.confirmar_destino_de_obra(con_coordenadas=False)
    op.sembrar([_fila(LIMBO_CON_TARJETA, AGOTABLE, op.planta_id)], intentos=3)
    registros = list(op.pendientes().values())
    for r in registros:
        r["estado_espera"] = "ESPERANDO_ACCION_HUMANA"
    informe: dict = {}
    assert reconciliacion._asegurar_via_humana(
        raiz=op.raiz, registros=registros, previos={}, instante=AHORA,
        persistir=op.escribir_pendientes, informe=informe,
    ) == []
    assert informe["limbos_con_tarjeta"] == [LIMBO_CON_TARJETA]


# ------------------------------------------------ salidas de la cola

def _resolver_fuera_del_mantenimiento(op: Operacion, guia: str) -> None:
    """Otro flujo (p. ej. Mobile) calcula la ruta entre dos pasadas."""
    import csv
    from test_ciclo_pendientes_tecnicos_simulado import _escribir_csv
    with op.dataset.open(encoding="utf-8-sig", newline="") as f:
        filas = list(csv.DictReader(f, delimiter=";"))
    for fila in filas:
        if fila["numero_guia"] == guia:
            fila.update(estado_ruta="RUTA_CALCULADA", motivo_ruta="", estado_operacional="OK", distancia_km="522.3")
    _escribir_csv(op.dataset, filas)


def test_guia_resuelta_por_otro_flujo_aparece_en_salidas_de_cola(op):
    """Caso real 474597: estaba en la cola (cooldown vigente, no elegible) y
    otro flujo la dejó RUTA_CALCULADA; la pasada no tiene elegibles."""
    op.sembrar([_fila("474597", AGOTABLE, op.planta_id), _fila(LIMBO_SIN_PREGUNTA, DETERMINISTA, op.planta_id)],
               minutos=5)
    _resolver_fuera_del_mantenimiento(op, "474597")
    resultado = op.mantener()

    assert resultado["elegibles"] == [] and resultado["motivo"] == "HUELLAS_ACTUALIZADAS"
    assert resultado["salidas_de_cola"] == [{
        "numero_guia": "474597", "estado_ruta_actual": "RUTA_CALCULADA",
        "motivo_ruta_actual": "", "estado_operacional_actual": "OK",
    }]
    assert resultado["resueltas"] == [], "no se mezcla con lo resuelto por intentos de esta pasada"
    assert "474597" not in op.pendientes()
    # El resto del informe sigue presente.
    for clave in ("limbos", "tarjetas_publicadas", "tarjetas_retiradas", "pendientes", "reporte_regenerado"):
        assert clave in resultado


def test_salida_de_cola_no_se_reporta_de_nuevo_en_la_pasada_siguiente(op):
    op.sembrar([_fila("474597", AGOTABLE, op.planta_id), _fila(LIMBO_SIN_PREGUNTA, DETERMINISTA, op.planta_id)],
               minutos=5)
    _resolver_fuera_del_mantenimiento(op, "474597")
    op.mantener()
    segunda = op.mantener()
    assert segunda["salidas_de_cola"] == []
    assert segunda["motivo"] == "SIN_ELEGIBLES"


def test_resuelta_por_el_intento_de_la_pasada_va_en_resueltas_no_en_salidas(op):
    op.confirmar_destino_de_obra(con_coordenadas=True)
    op.sembrar([_fila("480001", AGOTABLE, op.planta_id)], intentos=2)
    resultado = op.mantener()
    assert resultado["resueltas"] == ["480001"]
    assert resultado["salidas_de_cola"] == []


def test_elegible_y_salida_ajena_en_la_misma_pasada(op):
    """Una elegible que sigue pendiente + una guía ajena que salió."""
    op.sembrar([_fila(ELEGIBLE, AGOTABLE, op.planta_id), _fila("474597", AGOTABLE, op.planta_id)])
    registros = op.pendientes()
    registros["474597"]["ultimo_intento"] = (AHORA).isoformat()  # cooldown vigente: no elegible
    op.escribir_pendientes(list(registros.values()))
    _resolver_fuera_del_mantenimiento(op, "474597")
    resultado = op.mantener()
    assert [e["numero_guia"] for e in resultado["elegibles"]] == [ELEGIBLE]
    assert resultado["pendientes"] == [ELEGIBLE] and resultado["resueltas"] == []
    assert [s["numero_guia"] for s in resultado["salidas_de_cola"]] == ["474597"]
    assert op.pendientes()[ELEGIBLE]["intentos_misma_evidencia"] == 2, "intentos intactos"
