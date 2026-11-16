"""Regresión caso real 484838 (viaje 0000370724): "SANTA ISABEL585 SANTIAGO
LAMPA" -- sólo falta el espacio entre calle y número -- terminaba en
GEOCODIFICACION_DEMASIADO_GENERICA (dos tarjetas DESTINO) mientras las guías
hermanas "SANTA ISABEL 585 SANTIAGO LAMPA" resolvían. Las respuestas del
geocodificador son las reales guardadas en la caché de CASA."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from atlas_core.catalogo_destinos import Destino
from atlas_core.rutas.destino_entrega import (
    ESTADO_RESUELTO,
    _texto_geocodificable_con_numeracion_separada,
    resolver_destino_entrega_validado,
)
from atlas_core.rutas.modelos import CandidatoGeocodificacion, Coordenadas, EstadoRuta, ResultadoGeocodificacion

FECHA = datetime(2026, 1, 1, tzinfo=timezone.utc).isoformat()
CALLE_SANTA_ISABEL = (Coordenadas(-70.737609, -33.310665), "Santa Isabel, Lampa, RM, Chile", 0.8, "Lampa", "Metropolitana")
SOLO_COMUNA_LAMPA = (Coordenadas(-70.753807, -33.311742), "Lampa, RM, Chile", 0.6, "Lampa", "Metropolitana")


class GeocodificadorGrabado:
    """Responde por prefijo de consulta; registra lo que se le pidió."""

    nombre, version = "grabado", "1"

    def __init__(self, respuestas):
        self.respuestas = respuestas
        self.consultas = []

    def _resolver(self, direccion):
        self.consultas.append(direccion)
        for prefijo, (estado, motivo, candidatos) in self.respuestas.items():
            if direccion.upper().startswith(prefijo):
                return ResultadoGeocodificacion(estado, tuple(CandidatoGeocodificacion(*c) for c in candidatos), motivo)
        return ResultadoGeocodificacion(EstadoRuta.DIRECCION_NO_ENCONTRADA, (), "SIN_RESULTADO")

    def geocodificar(self, direccion):
        return self._resolver(direccion)

    def geocodificar_estructurado(self, direccion, contexto):
        return self._resolver(direccion)

    def calcular_ruta(self, *args):
        raise AssertionError("no se calcula ruta aquí")


def _confirmado(direccion, lat, lon, comuna):
    return Destino(
        destino_id="d-" + direccion, cliente_id="", nombre_destino=direccion, nombre_normalizado=direccion,
        codigo_destino="", direccion=direccion, comuna=comuna, region="RM", pais="CHILE",
        latitud=lat, longitud=lon, aliases=(), estado_calidad="CONFIRMADO", estado_vigencia="ACTIVO",
        fuente="TEST", observacion="", fecha_creacion=FECHA, fecha_modificacion=FECHA,
    )


# Respuestas reales (caché CASA): con espacio, la calle; pegado, sólo la comuna.
RESPUESTAS_REALES = {
    "SANTA ISABEL 585 LAMPA": (EstadoRuta.REQUIERE_REVISION, "REQUIERE_CONFIRMACION_HUMANA", [CALLE_SANTA_ISABEL]),
    "SANTA ISABEL585 LAMPA": (EstadoRuta.RESULTADO_AMBIGUO, "MULTIPLES_CANDIDATOS", [SOLO_COMUNA_LAMPA, SOLO_COMUNA_LAMPA]),
}
SANTA_ISABEL_CONFIRMADO = _confirmado("SANTA ISABEL 585, LAMPA, CHILE", -33.310665, -70.737609, "LAMPA")


def _resolver(texto, respuestas=RESPUESTAS_REALES, confirmados=(SANTA_ISABEL_CONFIRMADO,)):
    geo = GeocodificadorGrabado(respuestas)
    return resolver_destino_entrega_validado(texto, geo, destinos_confirmados=confirmados), geo


def test_484838_numeracion_pegada_resuelve_igual_que_las_guias_hermanas():
    pegada, geo = _resolver("SANTA ISABEL585 SANTIAGO LAMPA")
    hermana, _ = _resolver("SANTA ISABEL 585 SANTIAGO LAMPA")
    assert hermana.estado == ESTADO_RESUELTO
    assert (pegada.estado, pegada.coordenadas, pegada.motivo) == (hermana.estado, hermana.coordenadas, hermana.motivo)
    assert all(c.upper().startswith("SANTA ISABEL 585 LAMPA") for c in geo.consultas)
    # La evidencia documental se conserva tal cual.
    assert pegada.despachar_a_crudo == "SANTA ISABEL585 SANTIAGO LAMPA"


@pytest.mark.parametrize("pegada, separada", [
    ("CAMINO LO RUIZ2901 RENCA", "CAMINO LO RUIZ 2901 RENCA"),
    ("AVENIDA PAJARITOS1234 MAIPU", "AVENIDA PAJARITOS 1234 MAIPU"),
])
def test_casos_equivalentes_resuelven_igual_que_con_espacio(pegada, separada):
    calle = (Coordenadas(-70.70, -33.40), "Calle, Comuna, RM, Chile", 0.8, "", "Metropolitana")
    respuestas = {separada.rsplit(" ", 1)[0]: (EstadoRuta.RUTA_CALCULADA, "", [calle])}
    a, geo_a = _resolver(pegada, respuestas, ())
    b, geo_b = _resolver(separada, respuestas, ())
    assert (a.estado, a.coordenadas, a.motivo) == (b.estado, b.coordenadas, b.motivo)
    assert geo_a.consultas == geo_b.consultas


def test_numeracion_distinta_pegada_no_se_oculta_y_sigue_en_revision():
    # Otro número pegado: el geocodificador sólo da la comuna; la tarjeta se mantiene.
    respuestas = {"SANTA ISABEL 5850 LAMPA": (EstadoRuta.RESULTADO_AMBIGUO, "MULTIPLES_CANDIDATOS",
                                              [SOLO_COMUNA_LAMPA, SOLO_COMUNA_LAMPA])}
    resultado, geo = _resolver("SANTA ISABEL5850 SANTIAGO LAMPA", respuestas)
    assert resultado.estado != ESTADO_RESUELTO
    assert geo.consultas[0].upper().startswith("SANTA ISABEL 5850 LAMPA")


def test_ambiguedad_real_entre_dos_calles_sigue_en_revision():
    lejos = (Coordenadas(-70.60, -33.45), "Santa Isabel, Santiago, RM, Chile", 0.8, "Santiago", "Metropolitana")
    respuestas = {"SANTA ISABEL 585 LAMPA": (EstadoRuta.RESULTADO_AMBIGUO, "MULTIPLES_CANDIDATOS",
                                             [CALLE_SANTA_ISABEL, lejos])}
    resultado, _ = _resolver("SANTA ISABEL585 SANTIAGO LAMPA", respuestas, ())
    assert resultado.estado != ESTADO_RESUELTO


@pytest.mark.parametrize("texto, esperado", [
    ("SANTA ISABEL585 SANTIAGO LAMPA", "SANTA ISABEL 585 SANTIAGO LAMPA"),
    ("RUTA68 KM20", "RUTA 68 KM20"),            # sigla corta KM20 intacta
    ("CL14 N585", "CL14 N585"),                  # 2 letras / una letra: intactos
    ("SANTA ISABEL 58S LAMPA", "SANTA ISABEL 58S LAMPA"),   # número con letra OCR: intacto
    ("SANTA ISABEL S85 LAMPA", "SANTA ISABEL S85 LAMPA"),
    ("PARCELA5B LAMPA", "PARCELA5B LAMPA"),      # letra tras el número: intacto
    ("ARMACERO MATCO", "ARMACERO MATCO"),
    ("calle Ñuble1020 Ñuñoa", "calle Ñuble 1020 Ñuñoa"),
])
def test_separacion_solo_palabra_seguida_de_numeracion(texto, esperado):
    assert _texto_geocodificable_con_numeracion_separada(texto) == esperado


# --- Supresión de DESTINO_SIN_CONFIRMAR: comparador de formato del catálogo ---

@pytest.mark.parametrize("documental, coincide", [
    ("SANTA ISABEL585 SANTIAGO LAMPA", True),     # 484838: sólo falta el espacio
    ("SANTA ISABEL 585 SANTIAGO LAMPA", True),    # guías hermanas
    ("SANTA ISABEL5850 SANTIAGO LAMPA", False),   # otro número
    ("SANTA ISABEL595 LAMPA", False),
    ("SANTA LUISA585 LAMPA", False),              # otra calle
    ("SANTA ISABEL S85 LAMPA", False),            # número con letra OCR: no es espaciado
    ("SANTA ISABEL585 700 LAMPA", False),         # dos numeraciones: nunca se elige
])
def test_calle_sin_via_con_numeracion_pegada_coincide_sin_comuna(documental, coincide):
    from atlas_core.catalogo_destinos import direccion_confirmada_coincide, normalizar_nombre_destino
    assert direccion_confirmada_coincide("SANTA ISABEL 585", normalizar_nombre_destino(documental)) is coincide


# --- Reintento único de guías con tarjeta DESTINO_NO_RESUELTO al avanzar GEOGRAFIA ---

def test_guias_con_tarjeta_destino_no_resuelto_son_reintentables(tmp_path):
    import csv
    import json
    from atlas_core.procesamiento_masivo import COLUMNAS
    from atlas_core.reconciliacion_estado_derivado import _guias_destino_no_resuelto_reintentables

    def fila(guia, **extra):
        base = {c: "" for c in COLUMNAS}
        base.update(archivo=f"{guia}.jpg", numero_guia=guia, indicador_revision="OK", planta_origen_id="p1",
                    despachar_a_crudo="SANTA ISABEL585 SANTIAGO LAMPA", estado_ruta="REQUIERE_REVISION")
        base.update(extra)
        return base

    dataset = tmp_path / "analisis_completo_guias.csv"
    with dataset.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNAS, delimiter=";")
        w.writeheader()
        w.writerows([fila("1"), fila("2", estado_ruta="RUTA_CALCULADA"), fila("3", indicador_revision="REVISAR"),
                     fila("4"), fila("5")])
    decisiones = tmp_path / "decisiones_pendientes.json"
    decisiones.write_text(json.dumps({"decisiones": [
        {"estado": "PENDIENTE", "tipo": "DESTINO_NO_RESUELTO", "documento": {"numero_guia": g}} for g in ("1", "2", "3")
    ] + [
        {"estado": "PENDIENTE", "tipo": "OBRA_DESCONOCIDA", "documento": {"numero_guia": "4"}},
        {"estado": "APLICADA", "tipo": "DESTINO_NO_RESUELTO", "documento": {"numero_guia": "5"}},
    ]}), encoding="utf-8")
    assert _guias_destino_no_resuelto_reintentables(dataset, decisiones) == ["1"]


def test_geografia_v6_declara_destino_no_resuelto():
    from atlas_core.capacidades_reevaluacion import DOMINIO_GEOGRAFIA, dominios_de_decision, versiones_actuales
    assert versiones_actuales()[DOMINIO_GEOGRAFIA] == 6
    assert DOMINIO_GEOGRAFIA in dominios_de_decision("DESTINO_NO_RESUELTO")
