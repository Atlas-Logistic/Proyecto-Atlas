"""Bloque CONSULTAS ATLAS V1 -- contrato, validador y ejecutor
determinístico (Bloque 2/3/4/8/9/13/18/20 del ticket). Todos los tests
son sintéticos/deterministas -- fixtures propias, nunca el dataset real
(el E2E real vive en `tests/test_consultas_atlas_e2e.py`)."""
from __future__ import annotations

from datetime import date

import pytest

from atlas_core.consultas_atlas import (
    ConsultaAtlas,
    ErrorConsultaAtlas,
    ejecutar_consulta_atlas,
    resolver_periodo,
    validar_consulta,
)

SEP = " | "


def _viaje(**overrides):
    base = {
        "viaje_id": "v1", "numero_transporte": "T1", "fecha": "18-08-2026", "estado": "CONFIRMADO",
        "numeros_guia": "1", "clientes": "CLIENTE A", "obras_destino": "OBRA A",
        "choferes": "JUAN PEREZ", "patentes_tracto": "AA1111", "patentes_rampla": "",
        "materiales": "ROLLO HORMIGON 10MM (N)", "tipos_carga": "ROLLOS",
        "peso_total_viaje_kg": "1000", "distancia_km": "10.0", "duracion_min": "20.0",
        "direccion_entrega": "CALLE FALSA 123", "localidad_entrega": "MAIPU",
    }
    base.update(overrides)
    return base


# --- Bloque 20: validador -- rechaza campos inventados ---

def test_validar_consulta_rechaza_metrica_inventada():
    with pytest.raises(ErrorConsultaAtlas):
        validar_consulta(ConsultaAtlas(metrica="SUM_MAGIA"))


def test_validar_consulta_rechaza_filtro_inventado():
    with pytest.raises(ErrorConsultaAtlas):
        validar_consulta(ConsultaAtlas(metrica="COUNT_VIAJES", filtros={"campo_inventado": "X"}))


def test_validar_consulta_rechaza_agrupacion_inventada():
    with pytest.raises(ErrorConsultaAtlas):
        validar_consulta(ConsultaAtlas(metrica="COUNT_VIAJES", agrupacion="planeta"))


def test_validar_consulta_rechaza_periodo_inventado():
    with pytest.raises(ErrorConsultaAtlas):
        validar_consulta(ConsultaAtlas(metrica="COUNT_VIAJES", filtros={"periodo": "PROXIMO_SIGLO"}))


def test_validar_consulta_rechaza_fecha_invalida():
    with pytest.raises(ErrorConsultaAtlas):
        validar_consulta(ConsultaAtlas(metrica="COUNT_VIAJES", filtros={"fecha_desde": "no-es-fecha"}))


def test_validar_consulta_acepta_consulta_valida():
    validar_consulta(ConsultaAtlas(metrica="COUNT_VIAJES", filtros={"chofer": "JUAN PEREZ"}))


# --- Bloque 5: períodos -- resolución determinística ---

def test_resolver_periodo_hoy():
    hoy = date(2026, 8, 24)
    assert resolver_periodo("HOY", hoy=hoy) == (hoy, hoy)


def test_resolver_periodo_ayer():
    hoy = date(2026, 8, 24)
    assert resolver_periodo("AYER", hoy=hoy) == (date(2026, 8, 23), date(2026, 8, 23))


def test_resolver_periodo_este_mes():
    hoy = date(2026, 8, 24)
    assert resolver_periodo("ESTE_MES", hoy=hoy) == (date(2026, 8, 1), hoy)


def test_resolver_periodo_mes_pasado():
    hoy = date(2026, 8, 5)
    assert resolver_periodo("MES_PASADO", hoy=hoy) == (date(2026, 7, 1), date(2026, 7, 31))


def test_resolver_periodo_esta_semana_y_semana_pasada():
    hoy = date(2026, 8, 26)  # miércoles
    inicio_esta = date(2026, 8, 24)  # lunes
    assert resolver_periodo("ESTA_SEMANA", hoy=hoy) == (inicio_esta, hoy)
    assert resolver_periodo("SEMANA_PASADA", hoy=hoy) == (date(2026, 8, 17), date(2026, 8, 23))


# --- Bloque 3: métricas ---

def test_count_viajes_simple():
    viajes = [_viaje(numero_transporte="T1"), _viaje(numero_transporte="T2")]
    r = ejecutar_consulta_atlas(ConsultaAtlas(metrica="COUNT_VIAJES"), viajes)
    assert r.resultado == 2
    assert r.total_coincidencias == 2
    assert len(r.viajes_soporte) == 2


def test_count_guias_suma_guias_multivalor():
    viajes = [_viaje(numeros_guia=f"1{SEP}2"), _viaje(numeros_guia="3")]
    r = ejecutar_consulta_atlas(ConsultaAtlas(metrica="COUNT_GUIAS"), viajes)
    assert r.resultado == 3


def test_sum_peso_km_tiempo():
    viajes = [_viaje(peso_total_viaje_kg="1000", distancia_km="10.5", duracion_min="20"),
              _viaje(peso_total_viaje_kg="2000", distancia_km="5.5", duracion_min="15")]
    assert ejecutar_consulta_atlas(ConsultaAtlas(metrica="SUM_PESO"), viajes).resultado == 3000.0
    assert ejecutar_consulta_atlas(ConsultaAtlas(metrica="SUM_KM"), viajes).resultado == 16.0
    assert ejecutar_consulta_atlas(ConsultaAtlas(metrica="SUM_TIEMPO"), viajes).resultado == 35.0


def test_listar_viajes_devuelve_filas_reales():
    viajes = [_viaje(numero_transporte="T1"), _viaje(numero_transporte="T2")]
    r = ejecutar_consulta_atlas(ConsultaAtlas(metrica="LISTAR_VIAJES"), viajes)
    assert {v["numero_transporte"] for v in r.resultado} == {"T1", "T2"}
    assert r.viajes_soporte == r.resultado


# --- Bloque 2/9: filtros + trazabilidad (viajes_soporte siempre reales) ---

def test_filtro_chofer_exacto():
    viajes = [_viaje(choferes="JUAN PEREZ"), _viaje(choferes="PEDRO GOMEZ")]
    r = ejecutar_consulta_atlas(ConsultaAtlas(metrica="COUNT_VIAJES", filtros={"chofer": "JUAN PEREZ"}), viajes)
    assert r.resultado == 1
    assert r.viajes_soporte[0]["choferes"] == "JUAN PEREZ"


def test_filtro_tipo_carga_nunca_se_confunde_con_material():
    """Bloque 7 -- tipo_carga (enumeración cerrada) exige coincidencia
    EXACTA; material (texto libre) es SUBCADENA."""
    viajes = [
        _viaje(tipos_carga="ROLLOS", materiales="ROLLO HORMIGON 10MM (N)"),
        _viaje(tipos_carga="BARRAS", materiales="B HORMIGON 16MM (N)"),
    ]
    r_tipo = ejecutar_consulta_atlas(ConsultaAtlas(metrica="COUNT_VIAJES", filtros={"tipo_carga": "ROLLOS"}), viajes)
    assert r_tipo.resultado == 1
    r_material = ejecutar_consulta_atlas(ConsultaAtlas(metrica="COUNT_VIAJES", filtros={"material": "HORMIGON 16MM"}), viajes)
    assert r_material.resultado == 1
    assert r_material.viajes_soporte[0]["tipos_carga"] == "BARRAS"


def test_filtro_periodo_restringe_por_fecha():
    viajes = [_viaje(fecha="24-08-2026"), _viaje(fecha="01-01-2026")]
    r = ejecutar_consulta_atlas(
        ConsultaAtlas(metrica="COUNT_VIAJES", filtros={"fecha_desde": "2026-08-01", "fecha_hasta": "2026-08-31"}),
        viajes,
    )
    assert r.resultado == 1


def test_filtros_compuestos_interseccion():
    """Bloque 12 -- todos los filtros se aplican simultáneamente."""
    viajes = [
        _viaje(choferes="JUAN PEREZ", tipos_carga="ROLLOS", clientes="CLIENTE A"),
        _viaje(choferes="JUAN PEREZ", tipos_carga="BARRAS", clientes="CLIENTE A"),
        _viaje(choferes="PEDRO GOMEZ", tipos_carga="ROLLOS", clientes="CLIENTE A"),
    ]
    r = ejecutar_consulta_atlas(
        ConsultaAtlas(metrica="COUNT_VIAJES", filtros={"chofer": "JUAN PEREZ", "tipo_carga": "ROLLOS"}), viajes,
    )
    assert r.resultado == 1


# --- Bloque 13: cero resultados nunca es error ---

def test_sin_resultados_no_lanza_y_devuelve_cero():
    viajes = [_viaje(choferes="JUAN PEREZ")]
    r = ejecutar_consulta_atlas(ConsultaAtlas(metrica="COUNT_VIAJES", filtros={"chofer": "NADIE"}), viajes)
    assert r.resultado == 0
    assert r.total_coincidencias == 0
    assert r.viajes_soporte == ()


# --- Bloque 4: agrupaciones ---

def test_agrupacion_por_chofer():
    viajes = [
        _viaje(choferes="JUAN PEREZ", peso_total_viaje_kg="1000"),
        _viaje(choferes="JUAN PEREZ", peso_total_viaje_kg="500"),
        _viaje(choferes="PEDRO GOMEZ", peso_total_viaje_kg="2000"),
    ]
    r = ejecutar_consulta_atlas(ConsultaAtlas(metrica="SUM_PESO", agrupacion="chofer"), viajes)
    resultado = {f["grupo"]: f["valor"] for f in r.resultado}
    assert resultado == {"JUAN PEREZ": 1500.0, "PEDRO GOMEZ": 2000.0}


def test_agrupacion_por_mes():
    viajes = [_viaje(fecha="05-08-2026"), _viaje(fecha="20-08-2026"), _viaje(fecha="01-07-2026")]
    r = ejecutar_consulta_atlas(ConsultaAtlas(metrica="COUNT_VIAJES", agrupacion="mes"), viajes)
    resultado = {f["grupo"]: f["valor"] for f in r.resultado}
    assert resultado == {"2026-08": 2, "2026-07": 1}


def test_agrupacion_ordena_por_valor_descendente_por_defecto():
    viajes = [_viaje(choferes="A"), _viaje(choferes="B"), _viaje(choferes="B")]
    r = ejecutar_consulta_atlas(ConsultaAtlas(metrica="COUNT_VIAJES", agrupacion="chofer"), viajes)
    assert [f["grupo"] for f in r.resultado] == ["B", "A"]


def test_limite_restringe_agrupacion():
    viajes = [_viaje(choferes="A"), _viaje(choferes="B"), _viaje(choferes="C")]
    r = ejecutar_consulta_atlas(ConsultaAtlas(metrica="COUNT_VIAJES", agrupacion="chofer", limite=1), viajes)
    assert len(r.resultado) == 1
