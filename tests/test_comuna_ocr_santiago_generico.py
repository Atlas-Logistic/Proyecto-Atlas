"""P0 falsa confianza geográfica -- caso real 0000369696 (guías 484436/484437).

Ambas guías imprimen "SANTA ISABEL 585 SANTIAGO LAMPA". El OCR de 484437 leyó
"SANTA ISABEL SSS SANTIAGO LAVPA": sin número ni comuna reconocible, la única
comuna del texto era el "SANTIAGO" que AZA usa como etiqueta de ciudad, y el
geocodificador ubicó "Santa Isabel, Santiago, RM, Chile" (13101, 24,8 km en vez
de 5). Atlas lo publicó como destino confiable y el viaje se partió en dos.

La puerta en vivo ya no acepta una comuna geocodificada que sólo descansa en esa
etiqueta, y reconoce una comuna con UN carácter sustituido por OCR sólo cuando
la coincidencia es única dentro de la región de Santiago.
"""
from __future__ import annotations

import pytest

from atlas_core import territorio_chile
from atlas_core.catalogo_plantas import CatalogoPlantas, EstadoCalidad
from atlas_core.rutas import destino_entrega as de
from atlas_core.rutas.destino_entrega import (
    ESTADO_RESUELTO,
    ESTADO_REVISAR,
    LECTURA_COMUNA_EXACTA,
    LECTURA_COMUNA_ILEGIBLE,
    LECTURA_COMUNA_OCR_UN_CARACTER,
    calcular_ruta_entrega_para_viaje,
    leer_comuna_tras_etiqueta_santiago,
    resolver_destino_entrega_validado,
)
from atlas_core.rutas.modelos import (
    CandidatoGeocodificacion,
    Coordenadas,
    EstadoRuta,
    ResultadoGeocodificacion,
    ResultadoRuta,
)
from atlas_core.rutas.proveedor import ProveedorRutasSimulado


class _ProvFijo(ProveedorRutasSimulado):
    """Devuelve siempre el mismo candidato (técnica de
    tests/test_coherencia_direccion_geocodificacion.py)."""

    def __init__(self, *, etiqueta, localidad, region="Metropolitana", confianza=0.95,
                 codigo_unidad=""):
        super().__init__(resultado_ruta=ResultadoRuta(EstadoRuta.RUTA_CALCULADA, 24.78, 30.0, "SINTETICO"))
        self._cand = CandidatoGeocodificacion(
            Coordenadas(-70.65, -33.45), etiqueta, confianza, localidad, region,
            codigo_pais="CL" if codigo_unidad else "", codigo_unidad=codigo_unidad,
            codigo_contexto="13" if codigo_unidad else "",
        )
        self.consultas: list[str] = []

    def geocodificar(self, direccion):
        self.consultas.append(direccion)
        return ResultadoGeocodificacion(EstadoRuta.REQUIERE_REVISION, (self._cand,), "")

    def geocodificar_estructurado(self, direccion, contexto):
        return self.geocodificar(direccion)


def _santiago(etiqueta):
    return _ProvFijo(etiqueta=etiqueta, localidad="Santiago", codigo_unidad="13101")


def _resolver(texto, proveedor):
    return resolver_destino_entrega_validado(texto, proveedor, contexto_territorial="Chile")


def _rechazado_solo_santiago(resultado):
    assert resultado.estado == ESTADO_REVISAR
    assert resultado.motivo.startswith("GEOCODIFICACION_CONTRADICE_COMUNA_DOCUMENTAL:")
    assert "SOLO_SANTIAGO_GENERICO" in resultado.motivo
    # Nada de la comuna inferida se expone como destino.
    assert resultado.etiqueta_geocodificada == ""
    assert resultado.localidad == ""
    assert resultado.region == ""


# ---------------------------------------------------------------- lectura de la comuna documental

@pytest.mark.parametrize("texto, estado, comuna", [
    ("SANTA ISABEL SSS SANTIAGO LAVPA", LECTURA_COMUNA_OCR_UN_CARACTER, "Lampa"),   # 484437
    ("SANTA ISABEL 585 SANTIAGO LANPA", LECTURA_COMUNA_OCR_UN_CARACTER, "Lampa"),   # 482661
    ("AVDA IRARRAZAVAL 5497 SANTIAGO SUNOA", LECTURA_COMUNA_OCR_UN_CARACTER, "Ñuñoa"),  # 472937
    ("EANTA ISABEL S85 SANTIAGO LAPA", LECTURA_COMUNA_ILEGIBLE, ""),   # 473481: eliminación, no sustitución
    ("SANTA ISABEL 585 SANTIAGO LAMPA", LECTURA_COMUNA_EXACTA, "Lampa"),            # 484436
    ("SANTA ISABEL 585 SANTIAGO LAMPA FECHA 1083315", LECTURA_COMUNA_EXACTA, "Lampa"),
    ("MONJITAS 392 SANTIAGO", "", ""),          # "SANTIAGO" puede ser la comuna real
    ("MONJITAS 392 SANTIAGO CENTRO", "", ""),   # nivel genérico, no una comuna ilegible
    ("UNION AMERN CANA 151 SANTIAGO SASTTAGO", "", ""),  # 474097: SANTIAGO repetido mal leído
])
def test_lee_la_comuna_que_el_documento_declara_tras_santiago(texto, estado, comuna):
    lectura = leer_comuna_tras_etiqueta_santiago(texto)
    assert lectura.estado == estado
    assert lectura.comuna == comuna


def test_la_tolerancia_ocr_no_cruza_de_region():
    """"LAJE" está a una sustitución de Laja (Biobío): la etiqueta SANTIAGO
    fija la región de Santiago, así que no se reconoce."""
    assert leer_comuna_tras_etiqueta_santiago("CALLE 1 123 SANTIAGO LAJE").estado == LECTURA_COMUNA_ILEGIBLE


def test_la_tolerancia_ocr_exige_al_menos_cinco_letras():
    # "BUIM" está a una sustitución de Buin, pero 4 letras no bastan.
    assert leer_comuna_tras_etiqueta_santiago("CAMINO 1 SANTIAGO BUIM").estado == LECTURA_COMUNA_ILEGIBLE


def test_coincidencia_ambigua_no_se_reconoce(monkeypatch):
    """Dos comunas de la región a una sustitución: nunca se elige."""
    region = territorio_chile._INDICE_COMUNAS["SANTIAGO"][1]
    indice = dict(territorio_chile._INDICE_COMUNAS)
    indice["LAMPO"] = ("Lampo", region)
    monkeypatch.setattr(territorio_chile, "_INDICE_COMUNAS", indice)
    lectura = leer_comuna_tras_etiqueta_santiago("SANTA ISABEL 585 SANTIAGO LAMPE")
    assert lectura.estado == LECTURA_COMUNA_ILEGIBLE
    assert lectura.comuna == ""


def test_la_lectura_nunca_altera_numeros_ni_direccion():
    texto = "SANTA ISABEL SSS SANTIAGO LAVPA"
    lectura = leer_comuna_tras_etiqueta_santiago(texto)
    assert lectura.cola == "LAVPA"
    assert texto == "SANTA ISABEL SSS SANTIAGO LAVPA"


# ---------------------------------------------------------------- puerta en vivo: casos reales

def test_484437_santiago_inferido_no_se_publica():
    texto = "SANTA ISABEL SSS SANTIAGO LAVPA"
    resultado = _resolver(texto, _santiago("Santa Isabel, Santiago, RM, Chile"))
    _rechazado_solo_santiago(resultado)
    assert "Lampa" in resultado.motivo
    assert resultado.despachar_a_crudo == texto


def test_473481_comuna_ilegible_y_santiago_inferido_no_se_publica():
    resultado = _resolver("EANTA ISABEL S85 SANTIAGO LAPA", _santiago("Santa Isabel, Santiago, RM, Chile"))
    _rechazado_solo_santiago(resultado)
    assert "ILEGIBLE" in resultado.motivo


def test_482661_santiago_inferido_no_se_publica():
    resultado = _resolver(
        "SANTA ISABEL 585 SANTIAGO LANPA", _santiago("Santa Isabel 585, Santiago, RM, Chile"),
    )
    _rechazado_solo_santiago(resultado)


def test_482661_comuna_reconocida_por_ocr_acepta_el_destino_coherente():
    resultado = _resolver(
        "SANTA ISABEL 585 SANTIAGO LANPA",
        _ProvFijo(etiqueta="Santa Isabel 585, Lampa, RM, Chile", localidad="Lampa"),
    )
    assert resultado.estado == ESTADO_RESUELTO
    assert resultado.localidad == "Lampa"


def test_482661_comuna_reconocida_por_ocr_contradice_otra_comuna():
    resultado = _resolver(
        "SANTA ISABEL 585 SANTIAGO LANPA",
        _ProvFijo(etiqueta="Santa Isabel 585, Maipú, RM, Chile", localidad="Maipú"),
    )
    assert resultado.estado == ESTADO_REVISAR
    assert resultado.motivo.startswith("GEOCODIFICACION_CONTRADICE_COMUNA_DOCUMENTAL: Lampa")


def test_472937_santiago_inferido_en_vez_de_nunoa_no_se_publica():
    resultado = _resolver(
        "AVDA IRARRAZAVAL 5497 SANTIAGO SUNOA",
        _santiago("Avenida Irarrázaval 5497, Santiago, RM, Chile"),
    )
    _rechazado_solo_santiago(resultado)
    assert "Ñuñoa" in resultado.motivo


def test_472937_nunoa_coherente_se_acepta():
    resultado = _resolver(
        "AVDA IRARRAZAVAL 5497 SANTIAGO SUNOA",
        _ProvFijo(etiqueta="Avenida Irarrázaval 5497, Ñuñoa, RM, Chile", localidad="Ñuñoa"),
    )
    assert resultado.estado == ESTADO_RESUELTO
    assert resultado.localidad == "Ñuñoa"


# ---------------------------------------------------------------- no regresión

def test_santa_isabel_700_se_resuelve_sin_confundirse_con_585():
    resultado = _resolver(
        "SANTA ISABEL 700 SANTIAGO LAMPA",
        _ProvFijo(etiqueta="Santa Isabel 700, Lampa, RM, Chile", localidad="Lampa"),
    )
    assert resultado.estado == ESTADO_RESUELTO
    assert "700" in resultado.etiqueta_geocodificada
    assert resultado.localidad == "Lampa"


def test_santa_isabel_700_sigue_rechazando_el_numero_585():
    resultado = _resolver(
        "SANTA ISABEL 700 SANTIAGO LAMPA",
        _ProvFijo(etiqueta="Santa Isabel 585, Lampa, RM, Chile", localidad="Lampa"),
    )
    assert resultado.estado == ESTADO_REVISAR
    assert "NUMERO_INCOMPATIBLE" in resultado.motivo


def test_comuna_exacta_conserva_la_regla_territorial_de_siempre():
    """Con la comuna impresa y leída EXACTA, "Santiago" sigue siendo
    compatible como nivel ciudad (Bloque T1, 472238): fuera de alcance."""
    resultado = _resolver(
        "VISTA CLARA 2351 SANTIAGO CERRILLOS",
        _ProvFijo(etiqueta="Vista Clara 2351, Santiago, RM, Chile", localidad="Santiago"),
    )
    assert resultado.estado == ESTADO_RESUELTO


def test_santiago_como_ultima_palabra_sigue_aceptandose():
    resultado = _resolver("MONJITAS 392 SANTIAGO", _santiago("Monjitas 392, Santiago, RM, Chile"))
    assert resultado.estado == ESTADO_RESUELTO
    assert resultado.localidad == "Santiago"


def test_comuna_ilegible_no_contradice_a_otra_comuna_distinta_de_santiago():
    """Ausencia de evidencia no es contradicción: sin comuna legible, un
    destino en otra comuna sigue pasando por las demás guardas de siempre."""
    resultado = _resolver(
        "EANTA ISABEL S85 SANTIAGO LAPA",
        _ProvFijo(etiqueta="Santa Isabel, Lampa, RM, Chile", localidad="Lampa"),
    )
    assert "SOLO_SANTIAGO_GENERICO" not in resultado.motivo


# ---------------------------------------------------------------- extremo a extremo: sin ruta ni km

def _plantas(tmp_path):
    catalogo = CatalogoPlantas(tmp_path / "plantas.json")
    catalogo.crear(
        nombre="AZA COLINA", pais="CHILE", fuente="PRUEBA",
        direccion="PANAMERICANA NORTE KM 18", comuna="COLINA", region="RM",
        latitud=-33.2, longitud=-70.7, estado_calidad=EstadoCalidad.CONFIRMADA,
    )
    return catalogo.listar()


def test_484437_sin_destino_ni_ruta_ni_kilometros(tmp_path):
    proveedor = _santiago("Santa Isabel, Santiago, RM, Chile")
    ruta = calcular_ruta_entrega_para_viaje(
        despachar_a_crudo="SANTA ISABEL SSS SANTIAGO LAVPA", patente=None, instante_salida=None,
        plantas=_plantas(tmp_path), proveedor_posicion=None, proveedor_rutas=proveedor,
        textos_documento=["GUIA DE DESPACHO AZA COLINA PANAMERICANA NORTE"],
    )
    assert ruta.direccion_entrega_geocodificada == ""
    assert ruta.localidad_entrega == ""
    assert ruta.codigo_unidad == ""
    assert ruta.distancia_km == ""
    assert ruta.duracion_min == ""
    assert ruta.estado_ruta != EstadoRuta.RUTA_CALCULADA.value
    assert "SOLO_SANTIAGO_GENERICO" in ruta.motivo_ruta


def test_modulo_expone_las_constantes_de_la_regla():
    assert de.LONGITUD_MINIMA_COMUNA_OCR == 5
    assert de.MOTIVO_COMUNA_CONTRADICE == "GEOCODIFICACION_CONTRADICE_COMUNA_DOCUMENTAL"
