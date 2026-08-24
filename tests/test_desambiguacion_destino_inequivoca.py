"""Bloque DESTINOS D1 -- resolución de `MULTIPLES_UBICACIONES_DISPERSAS`
SÓLO cuando existe evidencia inequívoca (catálogo `CONFIRMADO` y/o GPS que
descarta a todos los rivales), nunca "el candidato más cercano".

Principio (Javier, verbatim): "Atlas puede sugerir. Atlas no debe
adivinar." -- cada control negativo verifica una forma concreta de
ambigüedad real que debe seguir en abstención.
"""
from __future__ import annotations

from datetime import datetime, timezone

from atlas_core.catalogo_destinos import Destino
from atlas_core.rutas.destino_entrega import (
    ResultadoDesambiguacionInequivoca,
    resolver_destino_ambiguo_con_evidencia_inequivoca,
)
from atlas_core.rutas.modelos import CandidatoGeocodificacion, Coordenadas

FECHA = datetime(2026, 1, 1, tzinfo=timezone.utc).isoformat()


def _candidato(lat, lon, etiqueta="Candidato", confianza=0.8, localidad="", region=""):
    return CandidatoGeocodificacion(Coordenadas(lon, lat), etiqueta, confianza, localidad, region)


def _destino_confirmado(direccion, lat, lon, *, estado_calidad="CONFIRMADO", estado_vigencia="ACTIVO"):
    return Destino(
        destino_id="d-1", cliente_id="", nombre_destino=direccion,
        nombre_normalizado=direccion.upper(), codigo_destino="",
        direccion=direccion, comuna="", region="", pais="CHILE",
        latitud=lat, longitud=lon, aliases=(), estado_calidad=estado_calidad,
        estado_vigencia=estado_vigencia, fuente="TEST", observacion="",
        fecha_creacion=FECHA, fecha_modificacion=FECHA,
    )


def _punto(lat, lon):
    return Coordenadas(lon, lat)


# ============================================================
# CONTROLES NEGATIVOS -- deben abstenerse (resuelto=False)
# ============================================================


def test_no_es_ambiguedad_real_con_un_solo_candidato():
    candidatos = (_candidato(-33.0, -70.0),)
    r = resolver_destino_ambiguo_con_evidencia_inequivoca("DIRECCION 123", candidatos)
    assert r.resuelto is False
    assert r.motivo == "NO_ES_UNA_AMBIGUEDAD_REAL"


def test_dos_candidatos_gps_casi_equivalentes_se_abstiene():
    """Dos candidatos DENTRO del mismo radio GPS -- ninguno queda
    descartado, sobreviven ambos -- abstención."""
    candidatos = (_candidato(-33.40, -70.68, "A"), _candidato(-33.41, -70.69, "B"))
    breadcrumbs = (_punto(-33.405, -70.685),)  # cerca de ambos
    r = resolver_destino_ambiguo_con_evidencia_inequivoca(
        "CAMINO X 100", candidatos, breadcrumbs=breadcrumbs, radio_gps_km=50.0
    )
    assert r.resuelto is False


def test_candidatos_agrupados_a_pocos_km_sin_catalogo_se_abstiene():
    """Candidatos muy cerca entre sí (como el caso real Camino Lo Ruiz) --
    sin un destino CONFIRMADO que los respalde, la sola cercanía entre
    ellos no es evidencia de nada -- abstención."""
    candidatos = (
        _candidato(-33.4025, -70.6865, "A"), _candidato(-33.4023, -70.6867, "B"),
        _candidato(-33.4008, -70.6874, "C"),
    )
    r = resolver_destino_ambiguo_con_evidencia_inequivoca("CAMINO Y 200", candidatos)
    assert r.resuelto is False
    assert r.motivo == "SIN_EVIDENCIA_INEQUIVOCA"


def test_gps_lejos_de_todos_los_candidatos_se_abstiene():
    """Si el descarte deja la lista vacía, se conserva la lista original
    completa (nunca inventa) -- sigue habiendo más de un candidato ->
    abstención."""
    candidatos = (_candidato(-33.0, -70.0, "A"), _candidato(-34.0, -71.0, "B"))
    breadcrumbs = (_punto(-10.0, -70.0),)  # a cientos de km de ambos
    r = resolver_destino_ambiguo_con_evidencia_inequivoca(
        "DIRECCION LEJANA 1", candidatos, breadcrumbs=breadcrumbs, radio_gps_km=50.0
    )
    assert r.resuelto is False


def test_catalogo_pendiente_nunca_autoriza_resolucion_automatica():
    """Una relación PENDIENTE (no confirmada) jamás resuelve, aunque su
    dirección coincida exacto y sus coordenadas calcen con un candidato."""
    candidatos = (_candidato(-33.30, -70.75, "A"), _candidato(-33.45, -70.63, "B"))
    destino_pendiente = _destino_confirmado(
        "PANAMERICANA NORTE 22650", -33.30, -70.75, estado_calidad="PENDIENTE"
    )
    r = resolver_destino_ambiguo_con_evidencia_inequivoca(
        "PANAMERICANA NORTE 22650 SANTIAGO LAMPA", candidatos,
        destinos_confirmados=(destino_pendiente,),
    )
    assert r.resuelto is False


def test_direccion_historica_repetida_sin_evidencia_propia_se_abstiene():
    """Misma dirección que OTRO viaje ya resolvió, pero sin GPS ni
    catálogo confirmado propios de ESTE viaje -- nunca se hereda la
    resolución de otro viaje."""
    candidatos = (
        _candidato(-36.4, -71.9, "San Carlos"), _candidato(-33.45, -70.63, "Santiago"),
    )
    # Sin breadcrumbs, sin destinos_confirmados -- exactamente lo que le
    # queda a un viaje sin telemetría propia aunque su dirección ya se
    # haya resuelto para otra guía distinta.
    r = resolver_destino_ambiguo_con_evidencia_inequivoca("AV EJEMPLO 3451 COMUNA X", candidatos)
    assert r.resuelto is False


def test_candidato_geocodificado_fuera_de_la_comuna_correcta_no_se_favorece():
    """El candidato que NO corresponde a la comuna documental no debe
    quedar seleccionado sólo por estar primero en la lista o por
    confianza -- sin evidencia GPS/catálogo, se abstiene sin importar el
    orden de los candidatos."""
    candidatos = (
        _candidato(-38.7, -72.5, "Comuna equivocada", confianza=1.0),
        _candidato(-33.45, -70.63, "Comuna correcta", confianza=0.6),
    )
    r = resolver_destino_ambiguo_con_evidencia_inequivoca("DIRECCION Z 500 COMUNA CORRECTA", candidatos)
    assert r.resuelto is False


def test_ausencia_de_gps_sin_catalogo_se_abstiene():
    candidatos = (_candidato(-33.0, -70.0), _candidato(-33.5, -70.5))
    r = resolver_destino_ambiguo_con_evidencia_inequivoca(
        "DIRECCION SIN GPS 1", candidatos, breadcrumbs=(), destinos_confirmados=(),
    )
    assert r.resuelto is False


def test_breadcrumbs_insuficientes_un_solo_punto_ambiguo_se_abstiene():
    """Un único breadcrumb que queda igual de cerca de dos candidatos no
    alcanza para descartar a ninguno."""
    candidatos = (_candidato(-33.40, -70.68), _candidato(-33.40, -70.681))
    breadcrumbs = (_punto(-33.40, -70.6805),)
    r = resolver_destino_ambiguo_con_evidencia_inequivoca(
        "DIRECCION CERCANA 1", candidatos, breadcrumbs=breadcrumbs, radio_gps_km=50.0
    )
    assert r.resuelto is False


def test_multiples_candidatos_siguen_plausibles_tras_descarte_se_abstiene():
    """Tres candidatos, dos sobreviven el descarte GPS (ambos dentro del
    radio) -- sigue habiendo más de un sobreviviente -> abstención, nunca
    se elige "el más cercano de los dos"."""
    candidatos = (
        _candidato(-33.10, -70.60, "A"), _candidato(-33.12, -70.62, "B"),
        _candidato(-38.0, -72.0, "C"),
    )
    breadcrumbs = (_punto(-33.11, -70.61),)
    r = resolver_destino_ambiguo_con_evidencia_inequivoca(
        "DIRECCION TRIPLE 1", candidatos, breadcrumbs=breadcrumbs, radio_gps_km=50.0
    )
    assert r.resuelto is False


def test_dos_destinos_confirmados_en_conflicto_se_abstiene():
    """Dos entradas CONFIRMADAS respaldan candidatos DISTINTOS -- conflicto
    real, nunca se elige una al azar."""
    candidatos = (_candidato(-33.10, -70.60, "A"), _candidato(-33.50, -70.90, "B"))
    d1 = _destino_confirmado("DIRECCION CONFLICTO 1", -33.10, -70.60)
    d2 = Destino(
        destino_id="d-2", cliente_id="", nombre_destino="otro",
        nombre_normalizado="OTRO", codigo_destino="", direccion="DIRECCION CONFLICTO 1",
        comuna="", region="", pais="CHILE", latitud=-33.50, longitud=-70.90,
        aliases=(), estado_calidad="CONFIRMADO", estado_vigencia="ACTIVO",
        fuente="TEST", observacion="", fecha_creacion=FECHA, fecha_modificacion=FECHA,
    )
    r = resolver_destino_ambiguo_con_evidencia_inequivoca(
        "DIRECCION CONFLICTO 1 COMUNA", candidatos, destinos_confirmados=(d1, d2),
    )
    assert r.resuelto is False
    assert r.motivo == "CONFLICTO_ENTRE_DESTINOS_CONFIRMADOS"


def test_catalogo_y_gps_discrepan_se_abstiene():
    """El catálogo confirmado respalda un candidato y el GPS descarta
    hasta dejar sobreviviente a OTRO distinto -- discrepancia real, nunca
    se prioriza una fuente sobre otra en silencio."""
    candidato_a = _candidato(-33.10, -70.60, "A")
    candidato_b = _candidato(-33.50, -70.90, "B")
    candidatos = (candidato_a, candidato_b)
    destino_confirmado = _destino_confirmado("DIRECCION DISCREPANCIA 1", -33.10, -70.60)
    breadcrumbs = (_punto(-33.50, -70.90),)  # sólo cerca de B, descarta A
    r = resolver_destino_ambiguo_con_evidencia_inequivoca(
        "DIRECCION DISCREPANCIA 1 COMUNA", candidatos,
        destinos_confirmados=(destino_confirmado,), breadcrumbs=breadcrumbs, radio_gps_km=5.0,
    )
    assert r.resuelto is False
    assert r.motivo == "CATALOGO_Y_GPS_DISCREPAN"


# ============================================================
# CONTROLES POSITIVOS -- deben resolver (resuelto=True)
# ============================================================


def test_gps_mas_catalogo_confirmado_coinciden_resuelve():
    """Patrón real (Camino Lo Ruiz / Santa Isabel): GPS muy cerca +
    catálogo CONFIRMADO con dirección exacta y coordenadas coincidentes."""
    ganador = _candidato(-33.4025, -70.6865, "Ganador")
    rival = _candidato(-34.5, -71.5, "Rival lejano")
    candidatos = (ganador, rival)
    destino = _destino_confirmado("CAMINO EJEMPLO 2901", -33.4025, -70.6865)
    breadcrumbs = (_punto(-33.4026, -70.6866),)
    r = resolver_destino_ambiguo_con_evidencia_inequivoca(
        "CAMINO EJEMPLO 2901 COMUNA X", candidatos,
        destinos_confirmados=(destino,), breadcrumbs=breadcrumbs, radio_gps_km=50.0,
    )
    assert r.resuelto is True
    assert r.candidato is ganador
    assert r.motivo == "CATALOGO_CONFIRMADO_Y_GPS_COINCIDEN"
    assert set(r.vias) == {"CATALOGO_CONFIRMADO", "GPS_DESCARTA_RIVALES"}


def test_brecha_geografica_inequivoca_solo_gps_resuelve():
    """Patrón real (Vicuña Mackenna / Carmen Mena): un candidato dentro
    del radio ya calibrado, todos los demás a cientos de km -- sin
    catálogo, sólo GPS."""
    ganador = _candidato(-33.45, -70.63, "RM")
    rivales = (
        _candidato(-36.4, -71.9, "Region lejana 1"),
        _candidato(-38.7, -72.5, "Region lejana 2"),
    )
    candidatos = (ganador, *rivales)
    breadcrumbs = (_punto(-33.44, -70.62),)
    r = resolver_destino_ambiguo_con_evidencia_inequivoca(
        "AV EJEMPLO 3451 COMUNA RM", candidatos, breadcrumbs=breadcrumbs, radio_gps_km=50.0,
    )
    assert r.resuelto is True
    assert r.candidato is ganador
    assert r.motivo == "GPS_DESCARTA_TODO_RIVAL_FUERA_DE_RADIO"
    assert r.vias == ("GPS_DESCARTA_RIVALES",)


def test_evidencia_canonica_convergente_solo_catalogo_resuelve():
    """Sin GPS disponible en absoluto, pero un catálogo CONFIRMADO con
    dirección exacta que calza únicamente con un candidato -- resuelve
    igual (la vía B es opcional, no obligatoria)."""
    ganador = _candidato(-33.31, -70.75, "Lampa")
    rival = _candidato(-33.45, -70.63, "Santiago")
    candidatos = (ganador, rival)
    destino = _destino_confirmado("SANTA ISABEL 585", -33.31, -70.75)
    r = resolver_destino_ambiguo_con_evidencia_inequivoca(
        "SANTA ISABEL 585 SANTIAGO LAMPA", candidatos, destinos_confirmados=(destino,),
    )
    assert r.resuelto is True
    assert r.candidato is ganador
    assert r.motivo == "CATALOGO_CONFIRMADO_COINCIDE_GEOCODIFICACION"
    assert r.vias == ("CATALOGO_CONFIRMADO",)


def test_catalogo_confirmado_no_matchea_texto_no_se_usa():
    """Un destino CONFIRMADO cuya dirección NO aparece en el texto
    documental nunca se usa como evidencia -- no basta con que exista en
    el catálogo, tiene que corresponder a ESTE despachar_a."""
    candidatos = (_candidato(-33.10, -70.60, "A"), _candidato(-33.50, -70.90, "B"))
    destino_no_relacionado = _destino_confirmado("OTRA DIRECCION TOTALMENTE DISTINTA", -33.10, -70.60)
    r = resolver_destino_ambiguo_con_evidencia_inequivoca(
        "DIRECCION QUE NO CALZA 1", candidatos, destinos_confirmados=(destino_no_relacionado,),
    )
    assert r.resuelto is False


def test_catalogo_confirmado_con_formato_real_calle_comuna_pais_resuelve():
    """`destinos_maestros.json` persiste `direccion` como "CALLE NUMERO,
    COMUNA, PAIS" (formato real de la migración) -- el documento nunca
    repite la coletilla ", CHILE"; debe seguir resolviendo comparando
    sólo la calle+número, sin volverse fuzzy."""
    ganador = _candidato(-33.4025, -70.6865, "Ganador")
    rival = _candidato(-34.5, -71.5, "Rival lejano")
    destino = _destino_confirmado("CALLE EJEMPLO 100, ALGUNA COMUNA, CHILE", -33.4025, -70.6865)
    r = resolver_destino_ambiguo_con_evidencia_inequivoca(
        "CALLE EJEMPLO 100 OTRA COMUNA DISTINTA", (ganador, rival),
        destinos_confirmados=(destino,),
    )
    assert r.resuelto is True
    assert r.candidato is ganador


# ============================================================
# Bloque CONFIRMACIÓN D2 -- `identidad_confirmada` se calcula SIEMPRE,
# independiente de si Vía A logra resolver un candidato (caso real
# 472037: destino CONFIRMADO sin coordenadas propias).
# ============================================================


def test_identidad_confirmada_true_aunque_destino_no_tenga_coordenadas():
    """Un destino CONFIRMADO cuya dirección coincide con el texto, pero
    SIN latitud/longitud propias (nunca pudo respaldar un candidato),
    igual marca `identidad_confirmada=True` -- la abstención geográfica
    sigue siendo legítima (`resuelto=False`), pero ya no es una
    ambigüedad de IDENTIDAD."""
    candidatos = (
        _candidato(-33.10, -70.60, "A"), _candidato(-33.50, -70.90, "B"),
        _candidato(-38.0, -72.0, "C"),
    )
    destino_sin_coordenadas = _destino_confirmado("VICUÑA MACKENNA 655", None, None)
    r = resolver_destino_ambiguo_con_evidencia_inequivoca(
        "VICUÑA MACKENNA 655", candidatos, destinos_confirmados=(destino_sin_coordenadas,),
    )
    assert r.resuelto is False
    assert r.identidad_confirmada is True


def test_identidad_confirmada_false_sin_destino_que_coincida():
    """Control -- sin ningún destino CONFIRMADO cuya dirección coincida
    textualmente, `identidad_confirmada` se mantiene False (comportamiento
    idéntico al de antes de este bloque)."""
    candidatos = (_candidato(-33.10, -70.60, "A"), _candidato(-33.50, -70.90, "B"))
    r = resolver_destino_ambiguo_con_evidencia_inequivoca("CALLE SIN CATALOGO 1", candidatos)
    assert r.resuelto is False
    assert r.identidad_confirmada is False


def test_identidad_confirmada_true_cuando_via_a_si_resuelve():
    """`identidad_confirmada` también es True en el camino feliz (Vía A
    con coordenadas que sí respaldan un candidato) -- nunca sólo en la
    abstención."""
    ganador = _candidato(-33.31, -70.75, "Lampa")
    rival = _candidato(-33.45, -70.63, "Santiago")
    destino = _destino_confirmado("SANTA ISABEL 585", -33.31, -70.75)
    r = resolver_destino_ambiguo_con_evidencia_inequivoca(
        "SANTA ISABEL 585 SANTIAGO LAMPA", (ganador, rival), destinos_confirmados=(destino,),
    )
    assert r.resuelto is True
    assert r.identidad_confirmada is True


def test_no_recalcula_ruta_ni_toca_km():
    """El resultado nunca incluye distancia/duración/ruta -- selección de
    destino y routing quedan estrictamente separados (Fase 8)."""
    ganador = _candidato(-33.45, -70.63)
    rival = _candidato(-38.7, -72.5)
    breadcrumbs = (_punto(-33.44, -70.62),)
    r = resolver_destino_ambiguo_con_evidencia_inequivoca(
        "DIRECCION SEPARACION 1", (ganador, rival), breadcrumbs=breadcrumbs, radio_gps_km=50.0,
    )
    assert r.resuelto is True
    assert not hasattr(r, "distancia_km")
    assert isinstance(r, ResultadoDesambiguacionInequivoca)
