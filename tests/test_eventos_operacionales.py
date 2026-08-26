"""Bloque UNIVERSAL V1 -- adaptador `construir_eventos_operacionales`
(join envío Mobile <-> viaje real) y prueba arquitectónica de que el
motor de EVENTOS es genuinamente universal, no MBT/AZA (Bloque 20/21
del ticket): un fixture de otro rubro (transporte de alimentos) se
consulta con el MISMO ejecutor, sin ningún código específico nuevo."""
from __future__ import annotations

from atlas_core.consultas_atlas import DOMINIO_EVENTOS, METRICA_COUNT_EVENTOS, ConsultaAtlas, ejecutar_consulta_eventos
from atlas_core.eventos_operacionales import construir_eventos_operacionales


def _viaje(**overrides):
    base = {
        "numero_transporte": "T1", "choferes": "JUAN PEREZ", "clientes": "CLIENTE A",
        "obras_destino": "OBRA A", "fecha": "20-08-2026",
    }
    base.update(overrides)
    return base


def _envio(**overrides):
    base = {
        "envio_id": "e1", "tipo_novedad": "TIENE_ESTADIA",
        "resultado_asociacion": {"numero_transporte": "T1", "numero_guia": "G1"},
        "recibido_en": "2026-08-20T10:00:00+00:00",
    }
    base.update(overrides)
    return base


# --- Bloque 9/13: join envío <-> viaje real, nunca por chofer_id opaco ---

def test_evento_se_enlaza_al_viaje_real_por_numero_transporte():
    viajes = [_viaje(numero_transporte="T1", choferes="CRISTOPHER RETAMAL", clientes="CLIENTE X")]
    envios = [_envio(resultado_asociacion={"numero_transporte": "T1", "numero_guia": "G1"})]
    eventos = construir_eventos_operacionales(envios, viajes)
    assert len(eventos) == 1
    assert eventos[0]["chofer"] == "CRISTOPHER RETAMAL"
    assert eventos[0]["cliente"] == "CLIENTE X"
    assert eventos[0]["numero_guia"] == "G1"


def test_envio_sin_tipo_novedad_no_es_un_evento():
    viajes = [_viaje()]
    envios = [_envio(tipo_novedad="")]
    assert construir_eventos_operacionales(envios, viajes) == []


def test_envio_no_asociado_a_ningun_viaje_sigue_contando_como_evento():
    """Un envío con novedad pero sin viaje asociado todavía (pendiente)
    NUNCA se descarta -- el evento real ya ocurrió aunque el viaje no se
    haya podido enlazar todavía."""
    envios = [_envio(resultado_asociacion={})]
    eventos = construir_eventos_operacionales(envios, [])
    assert len(eventos) == 1
    assert eventos[0]["chofer"] == ""
    assert eventos[0]["tipo_evento"] == "TIENE_ESTADIA"


def test_usa_numero_transporte_de_datos_ocr_si_no_hay_resultado_asociacion():
    viajes = [_viaje(numero_transporte="T9", choferes="LUIS VARAS")]
    envios = [_envio(resultado_asociacion=None, datos_ocr={"numero_transporte": "T9", "numero_guia": "G9"})]
    eventos = construir_eventos_operacionales(envios, viajes)
    assert eventos[0]["chofer"] == "LUIS VARAS"
    assert eventos[0]["numero_guia"] == "G9"


def test_envios_corruptos_o_no_dict_no_rompen_la_construccion():
    eventos = construir_eventos_operacionales([{"tipo_novedad": "TIENE_ESTADIA", "resultado_asociacion": "no-es-un-dict"}], [])
    assert len(eventos) == 1
    assert eventos[0]["numero_transporte"] == ""


# --- Bloque 20/21 del ticket: PRUEBA ARQUITECTÓNICA -- otro rubro,
# cero código específico. Transporte de ALIMENTOS: chofer, vehículo,
# cliente supermercado, centro de distribución, carga "Pallet
# refrigerado", evento "RECHAZO_TEMPERATURA" -- ninguno de estos
# nombres existe en ninguna tabla de vocabulario de este Motor. Se
# consulta con el MISMO `ejecutar_consulta_eventos` que ya usa
# MBT/AZA -- si esto pasa, el motor es universal de verdad. ---

def test_otro_rubro_alimentos_rechazos_por_temperatura_sin_codigo_especifico():
    viajes_alimentos = [
        {
            "numero_transporte": "ALM-001", "choferes": "MARIA CONTRERAS",
            "clientes": "SUPERMERCADO LIDER", "obras_destino": "CENTRO DE DISTRIBUCION SANTIAGO",
            "fecha": "20-08-2026",
        },
        {
            "numero_transporte": "ALM-002", "choferes": "MARIA CONTRERAS",
            "clientes": "SUPERMERCADO LIDER", "obras_destino": "CENTRO DE DISTRIBUCION SANTIAGO",
            "fecha": "21-08-2026",
        },
        {
            "numero_transporte": "ALM-003", "choferes": "MARIA CONTRERAS",
            "clientes": "SUPERMERCADO TOTTUS", "obras_destino": "CENTRO DE DISTRIBUCION NORTE",
            "fecha": "22-08-2026",
        },
    ]
    envios_alimentos = [
        _envio(
            envio_id="alm-e1", tipo_novedad="RECHAZO_TEMPERATURA",
            resultado_asociacion={"numero_transporte": "ALM-001", "numero_guia": "G-ALM-001"},
        ),
        _envio(
            envio_id="alm-e2", tipo_novedad="RECHAZO_TEMPERATURA",
            resultado_asociacion={"numero_transporte": "ALM-002", "numero_guia": "G-ALM-002"},
        ),
        _envio(
            envio_id="alm-e3", tipo_novedad="RECHAZO_TEMPERATURA",
            resultado_asociacion={"numero_transporte": "ALM-003", "numero_guia": "G-ALM-003"},
        ),
    ]
    eventos = construir_eventos_operacionales(envios_alimentos, viajes_alimentos)

    # "¿Cuántos rechazos por temperatura tuvo el cliente SUPERMERCADO LIDER?"
    resultado = ejecutar_consulta_eventos(
        ConsultaAtlas(
            metrica=METRICA_COUNT_EVENTOS, dominio=DOMINIO_EVENTOS,
            filtros={"tipo_evento": "RECHAZO_TEMPERATURA", "cliente": "SUPERMERCADO LIDER"},
        ),
        eventos,
    )
    assert resultado.resultado == 2
    assert {v["numero_transporte"] for v in resultado.viajes_soporte} == {"ALM-001", "ALM-002"}

    # Agrupado por cliente -- ambos supermercados, sin ninguna lógica
    # de "materiales de acero" ni "obra de construcción" involucrada.
    agrupado = ejecutar_consulta_eventos(
        ConsultaAtlas(
            metrica=METRICA_COUNT_EVENTOS, dominio=DOMINIO_EVENTOS,
            filtros={"tipo_evento": "RECHAZO_TEMPERATURA"}, agrupacion="cliente",
        ),
        eventos,
    )
    assert dict((f["grupo"], f["valor"]) for f in agrupado.resultado) == {
        "SUPERMERCADO LIDER": 2, "SUPERMERCADO TOTTUS": 1,
    }
