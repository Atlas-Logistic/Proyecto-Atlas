"""Revisión humana siempre con tarjeta (RULESET 26).

Casos reales del 06-10-2026 en los que el Motor sabía que hacía falta una
persona pero `decisiones_pendientes.json` quedaba vacío:
- 475413: cliente sólo en el catálogo legado bloquea la pregunta de obra;
- 474708: PATENTE_SIN_HOMOLOGAR sin tarjeta de vehículo;
- 473263/473424: peso total del viaje fuera de rango.
Todo sintético en `tmp_path`, sin red.
"""
from __future__ import annotations

import json

from atlas_core.aplicacion_decisiones import aplicar_decision_obra
from atlas_core.decisiones_pendientes import (
    crear_decision, detectar_decisiones_peso_viaje_implausible, regenerar_decisiones_persistidas,
)
from atlas_core.gestor_viajes import MotivoRevision, agrupar_viajes, pesos_viaje_confirmados_por_ledger
from atlas_core.revalidacion_documental import (
    _leer_filas, reconciliar_decisiones_peso_viaje,
    regenerar_decisiones_obra_faltantes_sin_ocr, regenerar_decisiones_vehiculo_faltantes_sin_ocr,
)
from test_ciclo_pendientes_tecnicos_simulado import Operacion, _escribir_csv, _fila, _proveedor
from test_p0_asignacion_chofer_vehiculo import _catalogos_vacios, _confirmar
from test_p0_asignacion_chofer_vehiculo import _escribir_csv as _escribir_csv_p0
from test_p0_asignacion_chofer_vehiculo import _fila as _fila_p0



def _tarjetas(op: Operacion, guia: str) -> list[dict]:
    return [d for d in op.decisiones() if d["documento"]["numero_guia"] == guia]


# -------------------------------------------------- cliente legado 475413


def _operacion_cliente_legado(tmp_path) -> Operacion:
    op = Operacion(tmp_path)
    (op.catalogos / "empresas.json").write_text(json.dumps({
        "947070002": {"nombre": "FERRETERIA COVADONGA LTDA", "codigo_cliente": "0001001230"},
    }), encoding="utf-8")
    _escribir_csv(op.dataset, [_fila(
        "475413", "COORDENADA_NO_CONFIRMADA(5)", op.planta_id, numero_transporte="0000362423",
        cliente="FERRETERIA COVADONGA LTDA", rut_cliente="94.707.000-2",
        obra_destino="CONSTRUCTORA MONTANO SPA", indicador_revision="REVISAR",
        motivos_revision_documento="OBRA_DESTINO_SIN_CORROBORAR",
    )])
    return op


def _red_obra(op: Operacion, pendientes=()) -> list[dict]:
    return regenerar_decisiones_obra_faltantes_sin_ocr(
        ruta_dataset=op.dataset, carpeta_catalogos=op.catalogos, decisiones_pendientes=list(pendientes),
        ruta_ledger=op.actual / "decisiones_aplicadas.json",
    )


def test_cliente_solo_en_catalogo_legado_pregunta_registrar_cliente(tmp_path):
    op = _operacion_cliente_legado(tmp_path)

    (decision,) = _red_obra(op)

    assert decision["tipo"] == "CLIENTE_DESCONOCIDO"
    assert decision["valor_documental"] == "FERRETERIA COVADONGA LTDA"
    assert "REGISTRAR" in decision["acciones_permitidas"]
    tipos_evidencia = {e["tipo"] for e in decision["evidencias"]}
    assert tipos_evidencia == {"RUT_VALIDO", "EMPRESA_CATALOGO_LEGADO"}
    assert _red_obra(op, [decision]) == [decision]  # nunca duplica


def test_cliente_registrado_encadena_la_pregunta_de_obra(tmp_path):
    op = _operacion_cliente_legado(tmp_path)
    datos = json.loads((op.catalogos / "clientes.json").read_text(encoding="utf-8"))
    nuevo = dict(datos["clientes"][0], cliente_id="cliente-covadonga", razon_social="FERRETERIA COVADONGA LTDA",
                 nombre_normalizado="FERRETERIA COVADONGA LTDA", rut="94707000-2")
    datos["clientes"].append(nuevo)
    (op.catalogos / "clientes.json").write_text(json.dumps(datos), encoding="utf-8")

    tipos = {d["tipo"] for d in _red_obra(op)}

    assert "OBRA_DESCONOCIDA" in tipos and "CLIENTE_DESCONOCIDO" not in tipos


def test_cliente_ya_decidido_por_humano_no_se_vuelve_a_preguntar(tmp_path):
    op = _operacion_cliente_legado(tmp_path)
    (op.actual / "decisiones_aplicadas.json").write_text(json.dumps({"aplicaciones": [{
        "decision_id": "c-1", "tipo": "CLIENTE_DESCONOCIDO", "accion": "NO_REGISTRAR",
        "documento": {"numero_guia": "475413"},
    }]}), encoding="utf-8")
    assert _red_obra(op) == []


# -------------------------------------------------------- rampla 474708


def test_patente_sin_homologar_sin_tarjeta_regenera_vehiculo_desconocido(tmp_path):
    carpeta = _catalogos_vacios(tmp_path)
    dataset = tmp_path / "analisis_completo_guias.csv"
    _escribir_csv_p0(dataset, [
        _fila_p0(archivo="474708.jpeg", numero_guia="474708", patente_tracto="", patente_rampla="JE6159",
                 motivos_revision_documento="PATENTE_SIN_HOMOLOGAR", indicador_revision="REVISAR"),
        _fila_p0(archivo="otra.jpeg", numero_guia="474709", patente_tracto="", patente_rampla="JE6160"),
    ])

    (decision,) = regenerar_decisiones_vehiculo_faltantes_sin_ocr(
        ruta_dataset=dataset, carpeta_catalogos=carpeta, decisiones_pendientes=[],
    )

    assert decision["tipo"] == "VEHICULO_DESCONOCIDO"
    assert (decision["campo"], decision["valor_documental"]) == ("patente_rampla", "JE6159")
    assert regenerar_decisiones_vehiculo_faltantes_sin_ocr(
        ruta_dataset=dataset, carpeta_catalogos=carpeta, decisiones_pendientes=[decision],
    ) == [decision]


def test_asignacion_del_chofer_no_retira_tarjeta_con_motivo_vigente(tmp_path):
    """Antes la convergencia chofer->vehículo retiraba la tarjeta aunque
    ningún revalidador retirara el motivo: viaje bloqueado sin pregunta."""
    carpeta = _catalogos_vacios(tmp_path)
    _confirmar(carpeta, "KN5439", rut_chofer_asociado="7814310-K")
    dataset = tmp_path / "analisis_completo_guias.csv"
    _escribir_csv_p0(dataset, [_fila_p0(patente_tracto="KW5439", motivos_revision_documento="PATENTE_SIN_HOMOLOGAR")])
    decision = crear_decision(
        tipo="VEHICULO_DESCONOCIDO", entidad="VEHICULO", archivo="473442.jpeg", numero_guia="473442",
        numero_transporte="No encontrado", campo="patente_tracto", valor_documental="KW5439",
        valor_normalizado="KW5439", identidad_resuelta=None, candidatos=[],
        motivos=("SIN_VEHICULO_CONFIRMADO_COMPATIBLE",), evidencias=(),
        acciones_permitidas=("REGISTRAR", "NO_REGISTRAR", "POSPONER"),
        tipo_resolucion="REQUIERE_CONFIRMACION_HUMANA", tipo_vehiculo_propuesto=None,
    )
    restantes = regenerar_decisiones_persistidas(decisiones=[decision], carpeta_catalogos=carpeta, ruta_dataset=dataset)
    assert [d["decision_id"] for d in restantes] == [decision["decision_id"]]


# ------------------------------------------------- peso 473263 / 473424


def _filas_peso(op: Operacion) -> list[dict]:
    return [
        _fila("473263", "", op.planta_id, numero_transporte="0000356721", peso_kg="56940",
              estado_ruta="RUTA_CALCULADA", estado_operacional="OK"),
        _fila("473424", "", op.planta_id, numero_transporte="0000357311", peso_kg="42868",
              estado_ruta="RUTA_CALCULADA", estado_operacional="OK"),
        # duplicado de la misma guía (otra foto): nunca pregunta de peso
        _fila("472238", "", op.planta_id, numero_transporte="0000354443", peso_kg="23512", archivo="472230.jpeg",
              estado_ruta="RUTA_CALCULADA", estado_operacional="OK"),
        _fila("472238", "", op.planta_id, numero_transporte="0000354443", peso_kg="23512", archivo="472238.jpeg",
              estado_ruta="RUTA_CALCULADA", estado_operacional="OK"),
        # peso normal
        _fila("473000", "", op.planta_id, numero_transporte="0000350000", peso_kg="27000",
              estado_ruta="RUTA_CALCULADA", estado_operacional="OK"),
    ]


def test_peso_total_fuera_de_rango_publica_una_tarjeta_por_viaje(tmp_path):
    op = Operacion(tmp_path)
    _escribir_csv(op.dataset, _filas_peso(op))

    reconciliar_decisiones_peso_viaje(raiz_atlas=op.raiz)

    tarjetas = {d["documento"]["numero_guia"]: d for d in op.decisiones()}
    assert set(tarjetas) == {"473263", "473424"}
    assert tarjetas["473263"]["tipo"] == "PESO_VIAJE_IMPLAUSIBLE"
    assert tarjetas["473263"]["contexto"]["peso_total_viaje_kg"] == 56940
    assert tarjetas["473263"]["acciones_permitidas"] == ["CONFIRMAR", "CORREGIR_PESO", "POSPONER"]
    assert reconciliar_decisiones_peso_viaje(raiz_atlas=op.raiz)["cambio"] is False  # idempotente


def test_peso_confirmado_por_humano_deja_de_marcar_el_viaje():
    fila = {"numero_transporte": "0000356721", "numero_guia": "473263", "archivo": "473263.jpeg",
            "peso_kg": "56940", "fecha": "03-09-2026"}
    (viaje,), _ = agrupar_viajes([fila], guias_revision_humana=())
    assert MotivoRevision.PESO_TOTAL_VIAJE_IMPLAUSIBLE in viaje.motivos_revision

    confirmados = pesos_viaje_confirmados_por_ledger({"aplicaciones": [{
        "tipo": "PESO_VIAJE_IMPLAUSIBLE", "accion": "CONFIRMAR",
        "numero_transporte_viaje": "0000356721", "peso_total_viaje_kg": "56940",
    }]})
    (viaje,), _ = agrupar_viajes([fila], guias_revision_humana=(), pesos_viaje_confirmados=confirmados)
    assert MotivoRevision.PESO_TOTAL_VIAJE_IMPLAUSIBLE not in viaje.motivos_revision
    # otro total (el documento cambió) vuelve a requerir revisión
    (viaje,), _ = agrupar_viajes([{**fila, "peso_kg": "57000"}], guias_revision_humana=(),
                                 pesos_viaje_confirmados=confirmados)
    assert MotivoRevision.PESO_TOTAL_VIAJE_IMPLAUSIBLE in viaje.motivos_revision
    assert detectar_decisiones_peso_viaje_implausible([fila], pesos_viaje_confirmados=confirmados) == []


def _aplicar_peso(op: Operacion, guia: str, accion: str, **extra) -> dict:
    (tarjeta,) = _tarjetas(op, guia)
    return aplicar_decision_obra(
        raiz_atlas=op.raiz, decision_id=tarjeta["decision_id"], accion=accion,
        proveedor_rutas=_proveedor(), proveedor_rutas_fallback=_proveedor(), **extra,
    )


def test_aplicar_confirmar_y_corregir_peso_cierran_las_tarjetas(tmp_path):
    op = Operacion(tmp_path)
    _escribir_csv(op.dataset, _filas_peso(op))
    reconciliar_decisiones_peso_viaje(raiz_atlas=op.raiz)

    assert _aplicar_peso(op, "473263", "CONFIRMAR")["ok"] is True
    assert _aplicar_peso(op, "473424", "CORREGIR_PESO", peso_corregido="22.868")["ok"] is True

    fila_corregida = next(f for f in _leer_filas(op.dataset) if f["numero_guia"] == "473424")
    assert fila_corregida["peso_kg"] == "22868"
    ledger = json.loads((op.actual / "decisiones_aplicadas.json").read_text(encoding="utf-8"))["aplicaciones"]
    assert [(a["accion"], a["peso_corregido"]) for a in ledger] == [("CONFIRMAR", None), ("CORREGIR_PESO", "22868")]
    reconciliar_decisiones_peso_viaje(raiz_atlas=op.raiz)
    assert [d for d in op.decisiones() if d["tipo"] == "PESO_VIAJE_IMPLAUSIBLE"] == []


def test_corregir_peso_exige_un_numero(tmp_path):
    op = Operacion(tmp_path)
    _escribir_csv(op.dataset, _filas_peso(op))
    reconciliar_decisiones_peso_viaje(raiz_atlas=op.raiz)
    try:
        _aplicar_peso(op, "473263", "CORREGIR_PESO", peso_corregido="veinte mil")
    except Exception as error:  # ErrorAplicacionDecision
        assert "kilos" in str(error)
    else:
        raise AssertionError("debió rechazar un peso no numérico")
    assert next(f for f in _leer_filas(op.dataset) if f["numero_guia"] == "473263")["peso_kg"] == "56940"
