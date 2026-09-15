"""Eventos operacionales: join read-only con viajes y fecha del hecho."""
from __future__ import annotations

import csv

from atlas_core.consultas_atlas import (
    DOMINIO_EVENTOS, METRICA_COUNT_EVENTOS, ConsultaAtlas,
    DOMINIO_INCIDENCIAS_DOCUMENTALES, METRICA_COUNT_INCIDENCIAS,
    ejecutar_consulta_eventos, ejecutar_consulta_incidencias_documentales, enriquecer_eventos_operacionales,
)
from atlas_core.registro_eventos_operacionales import registrar_evento
from atlas_core.responder_consulta_atlas import ESTADO_OK, responder_consulta_atlas
from atlas_core.interpretador_consultas import CatalogosConsulta, interpretar_consulta_determinista


def _viaje(transporte, obra, cliente, chofer, fecha):
    return {"viaje_id": f"v-{transporte}", "numero_transporte": transporte,
            "obras_destino": obra, "clientes": cliente, "choferes": chofer,
            "fecha": fecha, "numeros_guia": f"g-{transporte}", "patentes_tracto": "AA1111"}


def _evento(transporte, fecha_evento=""):
    return {"evento_id": f"e-{transporte}", "estado": "ACTIVO", "tipo_evento": "TIENE_ESTADIA",
            "numero_transporte": transporte, "fecha_evento": fecha_evento,
            # created intentionally disagrees: it must never define cuándo ocurrió.
            "creado_en": "2026-09-15T12:00:00+00:00"}


def _consulta(*, agrupacion, periodo=None, dias=None, limite=None, orden="DESC"):
    filtros = {"tipo_evento": "TIENE_ESTADIA"}
    if periodo: filtros.update({"periodo": periodo, "dias": str(dias)})
    return ConsultaAtlas(metrica=METRICA_COUNT_EVENTOS, dominio=DOMINIO_EVENTOS,
                         filtros=filtros, agrupacion=agrupacion, limite=limite, orden=orden)


def test_evento_historico_sin_obra_se_enriquece_y_top_obra_soporta_solo_ganador():
    viajes = [
        _viaje("T1", "OBRA NORTE", "CLIENTE A", "JUAN", "12-09-2026"),
        _viaje("T2", "OBRA NORTE", "CLIENTE A", "JUAN", "11-09-2026"),
        _viaje("T3", "OBRA SUR", "CLIENTE B", "PEDRO", "10-09-2026"),
    ]
    eventos = enriquecer_eventos_operacionales([_evento("T1"), _evento("T2"), _evento("T3")], viajes)
    resultado = ejecutar_consulta_eventos(_consulta(agrupacion="obra", periodo="ULTIMOS_N_DIAS", dias=30, limite=1), eventos)
    assert resultado.resultado == ({"grupo": "OBRA NORTE", "valor": 2},)
    assert {e["numero_transporte"] for e in resultado.viajes_soporte} == {"T1", "T2"}
    assert all(e["obra"] == "OBRA NORTE" for e in resultado.viajes_soporte)
    # La proyección no muta ni duplica los hechos fuente.
    assert len(eventos) == 3 and all("obra" not in _evento(t) for t in ("T1", "T2", "T3"))


def test_dimensiones_cliente_chofer_top_y_minimo_salen_del_mismo_join():
    viajes = [
        _viaje("T1", "O1", "CLIENTE A", "JUAN", "12-09-2026"),
        _viaje("T2", "O2", "CLIENTE A", "JUAN", "11-09-2026"),
        _viaje("T3", "O3", "CLIENTE B", "PEDRO", "10-09-2026"),
    ]
    eventos = enriquecer_eventos_operacionales([_evento("T1"), _evento("T2"), _evento("T3")], viajes)
    assert ejecutar_consulta_eventos(_consulta(agrupacion="cliente", limite=1), eventos).resultado == ({"grupo": "CLIENTE A", "valor": 2},)
    assert ejecutar_consulta_eventos(_consulta(agrupacion="chofer", limite=1), eventos).resultado == ({"grupo": "JUAN", "valor": 2},)
    assert ejecutar_consulta_eventos(_consulta(agrupacion="obra", limite=1, orden="ASC"), eventos).resultado == ({"grupo": "O1", "valor": 1},)


def test_ventana_usa_fecha_del_hecho_y_excluye_fuera_7_30_90_y_sin_viaje():
    viajes = [
        _viaje("T7", "O7", "C", "A", "12-09-2026"),
        _viaje("T30", "O30", "C", "A", "20-08-2026"),
        _viaje("T90", "O90", "C", "A", "20-06-2026"),
    ]
    eventos = enriquecer_eventos_operacionales([_evento("T7"), _evento("T30"), _evento("T90"), _evento("SIN_VIAJE")], viajes)
    for dias, esperado in ((7, 1), (30, 2), (90, 3)):
        r = ejecutar_consulta_eventos(_consulta(agrupacion="obra", periodo="ULTIMOS_N_DIAS", dias=dias), eventos)
        assert sum(f["valor"] for f in r.resultado) == esperado
    # SIN_VIAJE sólo tiene creado_en: abstención segura, no falsifica fecha/hecho ni grupo.
    assert not any(e.get("obra") for e in eventos if e["numero_transporte"] == "SIN_VIAJE")


def test_consulta_real_agrupa_por_obra_desde_evento_v1_sin_snapshot(tmp_path):
    viajes = [_viaje("T1", "OBRA NORTE", "C1", "JUAN", "12-09-2026"),
              _viaje("T2", "OBRA NORTE", "C1", "JUAN", "11-09-2026"),
              _viaje("T3", "OBRA SUR", "C2", "PEDRO", "10-09-2026")]
    ruta = tmp_path / "viajes.csv"
    with ruta.open("w", newline="", encoding="utf-8-sig") as archivo:
        w = csv.DictWriter(archivo, fieldnames=sorted({k for v in viajes for k in v}), delimiter=";")
        w.writeheader(); w.writerows(viajes)
    for transporte in ("T1", "T2", "T3"):
        registrar_evento(raiz=tmp_path, tipo_evento="TIENE_ESTADIA", numero_transporte=transporte, origen="TEST")
    respuesta = responder_consulta_atlas(
        "que obra genero mas estadias en los ultimos 30 dias", ruta_viajes=ruta, raiz_atlas=tmp_path,
    )
    assert respuesta.estado == ESTADO_OK
    assert respuesta.resultado.resultado == ({"grupo": "OBRA NORTE", "valor": 2},)
    assert "OBRA NORTE tuvo más estadías (2)" in respuesta.texto_respuesta
    assert {e["numero_transporte"] for e in respuesta.resultado.viajes_soporte} == {"T1", "T2"}


def test_incidencia_generica_es_operacional_y_documental_solo_con_calificador():
    catalogos = CatalogosConsulta(choferes=(), clientes=(), obras=(), tipos_carga=(), comunas=())
    generica, _ = interpretar_consulta_determinista("que viajes tuvieron incidencia en los ultimos 30 dias", catalogos=catalogos)
    operativa, _ = interpretar_consulta_determinista("incidencias operacionales de Toledo", catalogos=catalogos)
    documental, _ = interpretar_consulta_determinista("errores documentales de la guia 473263", catalogos=catalogos)
    guia_operativa, _ = interpretar_consulta_determinista("que incidencias tuvo la guia 473263", catalogos=catalogos)
    assert (generica.dominio, generica.metrica, generica.filtros["dias"]) == ("EVENTOS", "LIST_VIAJES", "30")
    assert operativa.dominio == "EVENTOS"
    assert (documental.dominio, documental.filtros) == ("INCIDENCIAS_DOCUMENTALES", {"numero_guia": "473263"})
    assert (guia_operativa.dominio, guia_operativa.filtros) == ("EVENTOS", {"numero_guia": "473263"})


def test_guia_con_ambos_dominios_no_mezcla_soportes():
    eventos = enriquecer_eventos_operacionales([_evento("T1")], [_viaje("T1", "O", "C", "A", "12-09-2026")])
    operativa = ejecutar_consulta_eventos(
        ConsultaAtlas(metrica=METRICA_COUNT_EVENTOS, dominio=DOMINIO_EVENTOS, filtros={"numero_guia": "g-T1"}), eventos,
    )
    documental = ejecutar_consulta_incidencias_documentales(
        ConsultaAtlas(metrica=METRICA_COUNT_INCIDENCIAS, dominio=DOMINIO_INCIDENCIAS_DOCUMENTALES, filtros={"numero_guia": "g-T1"}),
        [{"incidencia_id": "d1", "numero_guia": "g-T1", "tipo_incidencia": "RUT_DOCUMENTAL_INVALIDO"}],
    )
    assert operativa.resultado == 1 and all("tipo_evento" in e for e in operativa.viajes_soporte)
    assert documental.resultado == 1 and all("tipo_incidencia" in e for e in documental.viajes_soporte)
