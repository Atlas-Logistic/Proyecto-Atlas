"""Recuperación de comuna y región del viaje desde sus guías
(`Viaje._territorio_recuperado`). Datos sintéticos; reproducen los casos
reales 0000367068 (guías unánimes con km distintos), 0000362665 ("RM" frente
a "Metropolitana"), 0000365996 (comuna sin región), 0000355436 (dos
destinos), 0000365512 (misma dirección, comunas distintas) y 0000361121
(Chillán con región "Del Bio-Bio")."""
from __future__ import annotations

import copy

from atlas_core.gestor_viajes import agrupar_viajes
from atlas_core.procesamiento_masivo import COLUMNAS

T = "0000900123"


def _fila(guia, **extra):
    fila = {c: "" for c in COLUMNAS}
    fila.update({
        "archivo": f"{guia}.jpeg", "estado_procesamiento": "OK", "numero_guia": guia, "numero_transporte": T,
        "fecha": "26-09-2026", "chofer": "LUIS REYES", "rut_chofer": "12.345.678-5", "patente_tracto": "KN5439",
        "cliente": "CLIENTE UNO SA", "obra_destino": "CLIENTE UNO SA",
        "despachar_a_crudo": "CAMINO LO RUIZ 2901", "direccion_entrega": "CAMINO LO RUIZ 2901",
        "localidad_entrega": "Renca", "region_entrega": "Metropolitana", "estado_entrega": "RESUELTO",
        "planta_origen_id": "p-colina", "planta_origen_nombre": "AZA COLINA", "peso_kg": "12000",
        "estado_ruta": "RUTA_CALCULADA", "proveedor_ruta": "ors", "distancia_km": "20.1", "duracion_min": "30",
        "indicador_revision": "OK", "estado_documental": "OK", "estado_operacional": "OK",
    })
    fila.update(extra)
    return fila


def _viaje(*filas, **opciones):
    viajes, _ = agrupar_viajes(filas, guias_revision_humana=(), **opciones)
    assert len(viajes) == 1
    return viajes[0]


# ------------------------------------------------------------ recuperación segura


def test_guias_unanimes_con_rutas_distintas_recuperan_comuna_y_region():
    viaje = _viaje(_fila("1"), _fila("2", distancia_km="20.4"), _fila("3", distancia_km="19.8"))
    assert viaje.estado_ruta == ""  # sin ruta del viaje: antes ambos quedaban vacíos
    assert (viaje.localidad_entrega, viaje.region_entrega) == ("Renca", "Metropolitana")
    # sólo comuna y región: el resto del destino consolidado sigue igual
    assert viaje.direccion_entrega == "" and viaje.estado_entrega == ""


def test_variantes_del_nombre_de_region_son_la_misma_region():
    viaje = _viaje(_fila("1", region_entrega="RM"), _fila("2"), _fila("3"))
    assert viaje.estado_ruta == "RUTA_CALCULADA" and viaje.localidad_entrega == "Renca"
    assert viaje.region_entrega == "Metropolitana"  # el literal documental mayoritario


def test_comuna_oficial_sin_region_recupera_la_region_del_catalogo():
    viaje = _viaje(_fila("1", localidad_entrega="MAIPU", region_entrega=""))
    assert (viaje.localidad_entrega, viaje.region_entrega) == ("MAIPU", "Metropolitana")


# ------------------------------------------------------------ destinos múltiples


def test_destinos_distintos_en_la_misma_region_solo_recuperan_la_region():
    viaje = _viaje(
        _fila("1", localidad_entrega="Santiago", direccion_entrega="PANORAMICA NORTE 10750",
              despachar_a_crudo="PANORAMICA NORTE 10750"),
        _fila("2", localidad_entrega="Las Condes", direccion_entrega="PUERTA DEL SOL 83",
              despachar_a_crudo="PUERTA DEL SOL 83", distancia_km="31"),
    )
    assert len(viaje.entregas) == 2
    assert (viaje.localidad_entrega, viaje.region_entrega) == ("", "Metropolitana")


def test_destinos_en_regiones_distintas_no_recuperan_nada():
    viaje = _viaje(
        _fila("1", localidad_entrega="Talcahuano", region_entrega="Del Bio-Bio",
              direccion_entrega="LAS HORTENSIAS 3800", despachar_a_crudo="LAS HORTENSIAS 3800"),
        _fila("2", localidad_entrega="La Serena", region_entrega="De Coquimbo",
              direccion_entrega="LAS PALMERAS 520", despachar_a_crudo="LAS PALMERAS 520", distancia_km="470"),
    )
    assert (viaje.localidad_entrega, viaje.region_entrega) == ("", "")


# ------------------------------------------------------------ contradicción


def test_misma_direccion_con_comunas_distintas_no_recupera_la_comuna():
    viaje = _viaje(_fila("1", localidad_entrega="Santiago"),
                   _fila("2", localidad_entrega="San Bernardo", distancia_km="25"))
    assert (viaje.localidad_entrega, viaje.region_entrega) == ("", "Metropolitana")


def test_region_que_contradice_la_comuna_abstiene_ambos_campos():
    # Chillán es de Ñuble: "Del Bio-Bio" contradice el catálogo territorial
    viaje = _viaje(_fila("1", localidad_entrega="Chillán", region_entrega="Del Bio-Bio"),
                   _fila("2", localidad_entrega="Chillán", region_entrega="Del Bio-Bio", distancia_km="410"))
    assert (viaje.localidad_entrega, viaje.region_entrega) == ("", "")


def test_santiago_como_ciudad_generica_no_basta_para_la_comuna():
    viaje = _viaje(
        _fila("1", localidad_entrega="SANTIAGO", direccion_entrega="UNION AMERICANA 151",
              despachar_a_crudo="UNION AMERICANA 151"),
        _fila("2", localidad_entrega="Santiago", direccion_entrega="AVDA SANTA ROSA 9402",
              despachar_a_crudo="AVDA SANTA ROSA 9402", distancia_km="31"),
    )
    assert (viaje.localidad_entrega, viaje.region_entrega) == ("", "Metropolitana")


def test_comuna_no_oficial_no_se_recupera():
    viaje = _viaje(_fila("1", localidad_entrega="SECTOR LOS PINOS"), _fila("2", distancia_km="25"))
    assert viaje.localidad_entrega == ""


# ------------------------------------------------------------ evidencia insuficiente


def test_guia_con_destino_en_revision_abstiene_aunque_traiga_comuna():
    viaje = _viaje(_fila("1", localidad_entrega="QUINTA NORMAL", region_entrega="", direccion_entrega="",
                         estado_ruta="REQUIERE_REVISION", motivo_ruta="CONFIANZA_INSUFICIENTE",
                         distancia_km="", duracion_min="", proveedor_ruta=""))
    assert (viaje.localidad_entrega, viaje.region_entrega) == ("", "")


def test_guia_con_entrega_revisar_no_es_destino_resuelto():
    viaje = _viaje(_fila("1", localidad_entrega="VITACURA", region_entrega="", estado_entrega="REVISAR"))
    assert viaje.localidad_entrega == "VITACURA"  # ya consolidada por la ruta: se conserva
    assert viaje.region_entrega == ""


def test_una_guia_sin_dato_impide_recuperar():
    viaje = _viaje(_fila("1"), _fila("2", localidad_entrega="", region_entrega="", estado_entrega="REVISAR",
                                     distancia_km="20.4"))
    assert (viaje.localidad_entrega, viaje.region_entrega) == ("", "")


# ------------------------------------------------------------ conservación


def test_valor_ya_consolidado_no_se_reemplaza():
    viaje = _viaje(_fila("1", localidad_entrega="San Bernardo", region_entrega="Metropolitana"))
    assert viaje.estado_ruta == "RUTA_CALCULADA"
    assert (viaje.localidad_entrega, viaje.region_entrega) == ("San Bernardo", "Metropolitana")


def test_recuperar_no_modifica_guias_ni_registra_confirmacion_humana():
    filas = [_fila("1", region_entrega="RM"), _fila("2", distancia_km="20.4")]
    originales = copy.deepcopy(filas)
    viaje = _viaje(*filas)
    datos = viaje.a_dict()
    assert (datos["localidad_entrega"], datos["region_entrega"]) == ("Renca", "RM")
    assert filas == originales
    assert [(d.localidad_entrega, d.region_entrega) for d in viaje.documentos] == [
        ("Renca", "RM"), ("Renca", "Metropolitana")]
    assert not any(d.destino_operacional_confirmado for d in viaje.documentos)
