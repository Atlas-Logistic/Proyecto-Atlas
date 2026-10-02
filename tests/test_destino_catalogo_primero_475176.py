"""Catálogo primero: relación obra->destino confirmada antes de geocodificar.

Regresión real 475176 (EBEMA SA): el DESPACHAR A se leyó "GALVARINO B501
QUILICURA" y Atlas ya tenía confirmada por humano la relación de esa obra
con "GALVARINO 8501, QUILICURA" (con coordenadas). El primer pase igual
geocodificó el texto corrupto, aceptó el centroide de Quilicura y calculó
una ruta falsa que después hubo que re-anclar. Ahora el ruteo del primer
pase consulta esa relación ANTES de cualquier geocodificador; si resuelve
de forma inequívoca, no se llama a ninguno y `despachar_a_crudo` sigue
siendo el OCR original. Ante ambigüedad, contradicción o falta de
coordenadas, el pipeline normal sigue igual que antes.
"""
from __future__ import annotations

from dataclasses import replace

import pytest

from atlas_core.catalogo_destinos import Destino
from atlas_core.catalogo_plantas import CatalogoPlantas, EstadoCalidad
from atlas_core.procesamiento_masivo import _destinos_relacion_confirmada_para_obra
from atlas_core.rutas.destino_entrega import (
    METODO_RELACION_OBRA_DESTINO_CONFIRMADA,
    calcular_ruta_con_planta_conocida,
    destino_por_relacion_confirmada,
    resolver_entrega_documento,
)
from atlas_core.rutas.modelos import (
    CandidatoGeocodificacion,
    Coordenadas,
    EstadoRuta,
    ResultadoGeocodificacion,
    ResultadoRuta,
)
from atlas_core.rutas.proveedor import ProveedorRutasSimulado
from tests.test_destino_numeracion_b_ocho_475176 import _entorno

DOCUMENTAL_475176 = "GALVARINO B501 QUILICURA"
DIRECCION_CANONICA = "GALVARINO 8501, QUILICURA, CHILE"
COORD_DESTINO = Coordenadas(-70.716168, -33.370934)
CENTROIDE_QUILICURA = CandidatoGeocodificacion(
    Coordenadas(-70.728749, -33.365227), "Quilicura, Metropolitana, Chile", 0.6, "Quilicura", "Metropolitana",
)
FECHA = "2026-08-14T00:00:00+00:00"


def _destino(**cambios) -> Destino:
    base = Destino(
        destino_id="destino-galvarino", cliente_id="cliente-ebema", nombre_destino="GALVARINO 8501",
        nombre_normalizado="GALVARINO 8501", codigo_destino="", direccion=DIRECCION_CANONICA,
        comuna="QUILICURA", region="RM", pais="CHILE",
        latitud=COORD_DESTINO.latitud, longitud=COORD_DESTINO.longitud, aliases=(),
        estado_calidad="PENDIENTE", estado_vigencia="ACTIVO", fuente="TEST", observacion="",
        fecha_creacion=FECHA, fecha_modificacion=FECHA,
    )
    return replace(base, **cambios)


class _GeocodificacionesCentroide(dict):
    """Toda consulta devuelve lo que ORS devolvió en 475176: sólo el
    centroide de Quilicura."""

    def get(self, clave, defecto=None):
        return ResultadoGeocodificacion(EstadoRuta.REQUIERE_REVISION, (CENTROIDE_QUILICURA,), "SOLO_COMUNA")


def _proveedores():
    principal = ProveedorRutasSimulado(
        geocodificaciones=_GeocodificacionesCentroide(),
        resultado_ruta=ResultadoRuta(EstadoRuta.RUTA_CALCULADA, 13.1788, 19.5, "TEST"),
    )
    return principal, ProveedorRutasSimulado(geocodificaciones=_GeocodificacionesCentroide())


@pytest.fixture()
def planta(tmp_path):
    return CatalogoPlantas(tmp_path / "plantas.json").crear(
        nombre="AZA COLINA", pais="CHILE", fuente="TEST", direccion="AV EJEMPLO 1", comuna="COLINA",
        region="RM", latitud=-33.137558, longitud=-70.665977, estado_calidad=EstadoCalidad.CONFIRMADA,
    )


def _primer_pase(planta, despachar_a, destinos_relacion):
    principal, respaldo = _proveedores()
    resultado = resolver_entrega_documento(
        ["DESPACHAR A", f": {despachar_a}"], [planta], principal,
        codigo_planta_mobile="AZA_COLINA",
        proveedor_geocodificacion_fallback=respaldo,
        destinos_relacion_confirmada=destinos_relacion,
    )
    return resultado, principal, respaldo


# --- 1. regresión 475176: la relación confirmada resuelve antes del geocoder ---

def test_475176_relacion_confirmada_resuelve_sin_geocodificar(planta):
    resultado, principal, respaldo = _primer_pase(planta, DOCUMENTAL_475176, [_destino()])

    assert resultado["despachar_a_crudo"] == DOCUMENTAL_475176  # OCR original intacto
    assert resultado["direccion_entrega"] == DIRECCION_CANONICA
    assert resultado["localidad_entrega"] == "QUILICURA"
    assert resultado["estado_ruta"] == "RUTA_CALCULADA"
    assert resultado["distancia_km"] == "13.1788"
    # Etapas costosas evitadas: 0 consultas a geocodificador principal y de respaldo.
    assert principal.llamadas_geocodificacion == 0
    assert respaldo.llamadas_geocodificacion == 0
    assert principal.llamadas_ruta == 1


def test_475176_sin_relacion_comportamiento_previo_y_etapas_medidas(planta):
    """Línea base: sin el conocimiento confirmado, el mismo texto llega al
    geocodificador (y al respaldo) y queda anclado al centroide. Es el
    costo que la relación confirmada evita."""
    resultado, principal, respaldo = _primer_pase(planta, DOCUMENTAL_475176, [])

    assert principal.llamadas_geocodificacion == 1
    assert resultado["estado_ruta"] == "RUTA_CALCULADA"  # ruta falsa al centroide
    assert resultado["direccion_entrega"] != DIRECCION_CANONICA


def test_texto_literal_sigue_el_camino_historico(planta):
    """Sin ruido OCR el texto no está corrupto: se geocodifica (caché) igual
    que todas las guías históricas a ese lugar; los km no cambian de fuente."""
    assert destino_por_relacion_confirmada("GALVARINO 8501 QUILICURA", [_destino()]) is None
    _, principal, _ = _primer_pase(planta, "GALVARINO 8501 QUILICURA", [_destino()])
    assert principal.llamadas_geocodificacion == 1


def test_planta_conocida_gps_tampoco_regeocodifica(planta):
    principal, respaldo = _proveedores()
    ruta = calcular_ruta_con_planta_conocida(
        planta=planta, despachar_a_crudo=DOCUMENTAL_475176, proveedor_rutas=principal,
        proveedor_geocodificacion_fallback=respaldo, destinos_relacion_confirmada=[_destino()],
    )
    assert ruta.estado_ruta == "RUTA_CALCULADA"
    assert ruta.direccion_entrega_geocodificada == DIRECCION_CANONICA
    assert ruta.despachar_a_crudo == DOCUMENTAL_475176
    assert ruta.metodo_confirmacion_destino == METODO_RELACION_OBRA_DESTINO_CONFIRMADA
    assert principal.llamadas_geocodificacion == respaldo.llamadas_geocodificacion == 0


# --- 2. controles negativos: el catálogo no siempre gana ---

@pytest.mark.parametrize("documental", [
    "GALVARINO B502 QUILICURA",   # otro número
    "GALVARINO 501 QUILICURA",    # otro número sin B
    "GALVARINO 9999 QUILICURA",   # otra numeración real
    "GALVAN 8501 QUILICURA",      # otra calle
    "LOS ALERCES 120 QUILICURA",  # otro destino: posible cambio real
    "GALVARINO 8501 RENCA",       # contradicción documental de comuna
    "GALVARINO B501 RENCA",       # B->8 exige la comuna confirmada
    "GALVARINO B501 QUILICURA RENCA",  # comuna explícita incompatible
])
def test_contradiccion_o_no_coincidencia_sigue_pipeline_normal(planta, documental):
    assert destino_por_relacion_confirmada(documental, [_destino()]) is None
    resultado, principal, _ = _primer_pase(planta, documental, [_destino()])
    assert resultado["despachar_a_crudo"] == documental
    assert resultado["direccion_entrega"] != DIRECCION_CANONICA
    assert principal.llamadas_geocodificacion >= 1  # nunca se oculta: decide el pipeline normal


def test_dos_destinos_confirmados_compatibles_se_abstiene(planta):
    otro = _destino(destino_id="destino-galvarino-2", latitud=-33.343356, longitud=-70.700882)
    assert destino_por_relacion_confirmada(DOCUMENTAL_475176, [_destino(), otro]) is None
    _, principal, _ = _primer_pase(planta, DOCUMENTAL_475176, [_destino(), otro])
    assert principal.llamadas_geocodificacion >= 1


def test_destino_confirmado_sin_coordenadas_no_inventa(planta):
    sin_coords = _destino(latitud=None, longitud=None)
    assert destino_por_relacion_confirmada(DOCUMENTAL_475176, [sin_coords]) is None
    _, principal, _ = _primer_pase(planta, DOCUMENTAL_475176, [sin_coords])
    assert principal.llamadas_geocodificacion >= 1


def test_ruido_en_el_maestro_y_no_en_el_documento_no_usa_el_catalogo():
    """Casos reales 480676/475036: el documento trae "01148"/"730" sano y el
    maestro confirmado quedó "O1148"/"73O"; el texto documental manda."""
    maestro_o = _destino(direccion="INTERIOR NUEVA O1148 SAN BERNARDO", comuna="SAN BERNARDO")
    assert destino_por_relacion_confirmada("INTERIOR NUEVA 01148 SAN BERNARDO", [maestro_o]) is None
    maestro_b = _destino(direccion="GALVARINO B501, QUILICURA")
    assert destino_por_relacion_confirmada("GALVARINO 8501 QUILICURA", [maestro_b]) is None


def test_truncamiento_documental_con_maestro_sano_resuelve():
    """Caso real 474607 (Coronel): documento recortado, maestro confirmado completo."""
    maestro = _destino(direccion="CALLE D LOTE 27 Y 28 PARQUE INDUSTRIAL", comuna="CORONEL", region="BIOBIO")
    assert destino_por_relacion_confirmada("CALLE D LOTE 27 Y 28 PARQUE INDUST CORONEL", [maestro]) is maestro


def test_destino_inactivo_o_degradado_no_resuelve():
    assert destino_por_relacion_confirmada(DOCUMENTAL_475176, [_destino(estado_vigencia="INACTIVO")]) is None
    assert destino_por_relacion_confirmada("QUILICURA", [_destino(direccion="QUILICURA")]) is None
    assert destino_por_relacion_confirmada(
        "AV. CAM. LOS TRAPENSES LO BARNECHEA", [_destino(direccion="AV. CAM. LOS TRAPENSES", comuna="")],
    ) is None


def test_comuna_santiago_como_ciudad_no_es_contradiccion():
    assert destino_por_relacion_confirmada("GALVARINO B501 SANTIAGO QUILICURA", [_destino()]) is not None


# --- 3. fuente: sólo relaciones CONFIRMADAS de la obra identificada ---

def test_destinos_relacion_se_leen_del_catalogo_real(tmp_path):
    _, catalogos = _entorno(tmp_path, [])
    destinos = _destinos_relacion_confirmada_para_obra(catalogos, obra_documental="EBEMA SA")
    assert [d.destino_id for d in destinos] == ["destino-galvarino"]
    assert _destinos_relacion_confirmada_para_obra(catalogos, obra_documental="OBRA DESCONOCIDA") == []
    assert _destinos_relacion_confirmada_para_obra(catalogos, obra_documental="No encontrado") == []
    assert _destinos_relacion_confirmada_para_obra(tmp_path / "no_existe", obra_documental="EBEMA SA") == []
