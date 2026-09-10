"""Bloque COHERENCIA DIRECCIÓN DOCUMENTAL <-> GEOCODIFICACIÓN.

Una geocodificación no puede considerarse válida ni producir
RUTA_CALCULADA si contradice materialmente una dirección documental clara
o degrada una dirección específica a una ubicación demasiado genérica.

Casos testigo:
- 464170: doc "ALMTE. LATORRE 843 MEJILLONES" -> "898 Avenida Almirante
  Latorre" (número 843 != 898).
- 464653: doc "PDTE. BRESCO 6903 LAS CONDES" -> "Avenida Las Condes 6903"
  (la calle geocodificada es sólo el nombre de la comuna).
- 464746: doc "CAM. EL NOVICIADO LAMPA" -> "Lampa, RM, Chile" (sólo
  comuna/región, sin calle).
"""
from __future__ import annotations

import csv

from atlas_core.procesamiento_masivo import COLUMNAS
from atlas_core.decisiones_pendientes import MOTIVOS_DESTINO_NO_RESUELTO
from atlas_core.revalidacion_documental import (
    revalidar_destino_contra_comuna_documental_sin_ocr,
)
from atlas_core.rutas.destino_entrega import (
    ESTADO_RESUELTO, ESTADO_REVISAR, motivo_incoherencia_destino_documental,
    resolver_destino_entrega_validado,
)
from atlas_core.rutas.modelos import (
    CandidatoGeocodificacion, Coordenadas, EstadoRuta, ResultadoGeocodificacion,
)
from atlas_core.rutas.proveedor import ProveedorRutasSimulado


# ============================================================
# 1. La función de coherencia -- unidad
# ============================================================


def _m(doc, geo, loc="", region=""):
    return motivo_incoherencia_destino_documental(
        despachar_a_crudo=doc, etiqueta_geocodificada=geo, localidad=loc, region=region,
    )


def test_numero_documental_distinto_es_incoherente_464170():
    m = _m("AV. ALMTE. LATORRE 843 MEJILLONES MEJILLONES",
           "898 Avenida Almirante Latorre, Mejillones, AN, Chile", "Mejillones", "De Antofagasta")
    assert m == "GEOCODIFICACION_NUMERO_INCOMPATIBLE: 843 != 898"


def test_calle_degradada_al_nombre_de_la_comuna_es_incoherente_464653():
    assert _m("PDTE. BRESCO 6903 LAS CONDES LAS CONDES",
              "Avenida Las Condes 6903", "Las Condes", "Metropolitana") == "GEOCODIFICACION_DEMASIADO_GENERICA"


def test_geocodificacion_solo_comuna_region_es_incoherente_464746():
    assert _m("CAM. EL NOVICIADO LAMPA LAMPA", "Lampa, RM, Chile", "Lampa", "Metropolitana") == \
        "GEOCODIFICACION_DEMASIADO_GENERICA"


def test_calle_materialmente_distinta_es_incoherente():
    m = _m("GENERAL VELASQUEZ 100 SANTIAGO", "Avenida Matucana 100, Santiago", "Santiago", "Metropolitana")
    assert m.startswith("GEOCODIFICACION_CALLE_DOCUMENTAL_DISTINTA")


def test_abreviaturas_y_ruido_ocr_solo_para_el_nombre_de_la_calle():
    # abreviatura ALMTE -> ALMIRANTE, mismo número -> coherente
    assert _m("AV. ALMTE. LATORRE 843 MEJILLONES", "Avenida Almirante Latorre 843, Mejillones") == ""
    # ruido OCR en el NOMBRE de la calle ("MELIFILLA" ~ "MELIPILLA") -- el
    # geocodificador recuperó la calle real; el número documental no es
    # claro ("1OBOD"), así que no hay nada que contrastar ahí: coherente
    assert _m("CAMINO A MELIFILLA 1OBOD SANTIAGO MAIPU",
              "CAMINO A MELIPILLA 10800 SANTIAGO MAIPU", "Maipu") == ""


def test_un_solo_digito_distinto_en_el_numero_es_incompatible_sin_evidencia_ocr():
    # 843 vs 848: un dígito distinto NO se tolera por parecido/distancia
    # de edición -- sólo con confusión OCR documentada para ese carácter
    # (tabla vacía por diseño).
    assert _m("APOQUINDO 843 LAS CONDES", "Apoquindo 848, Las Condes", "Las Condes") == \
        "GEOCODIFICACION_NUMERO_INCOMPATIBLE: 843 != 848"
    assert _m("URUGUAY 15 LA CISTERNA", "Uruguay 16, La Cisterna", "La Cisterna") == \
        "GEOCODIFICACION_NUMERO_INCOMPATIBLE: 15 != 16"


def test_numero_coincide_exacto_o_solo_ceros_a_la_izquierda():
    assert _m("SAN DAMIAN 0100 VITACURA", "San Damian 100, Vitacura", "Vitacura") == ""
    assert _m("SAN DAMIAN 100 VITACURA", "San Damian 0100, Vitacura", "Vitacura") == ""


def test_direccion_coherente_no_marca_nada():
    assert _m("PUERTA DEL SOL 83 LAS CONDES", "Puerta del Sol 83, Las Condes", "Las Condes") == ""
    assert _m("SAN DIEGO 1234 SANTIAGO", "San Diego 1234, Santiago", "Santiago") == ""


def test_documento_sin_calle_clara_no_exige_calle_geocodificada():
    # el propio documento no fija una calle distinta de la comuna
    assert _m("AVENIDA LAS CONDES 6903 LAS CONDES", "Avenida Las Condes 6903", "Las Condes") == ""
    # documento sin número ni calle -> nada que contrastar
    assert _m("LAMPA", "Lampa, RM, Chile", "Lampa") == ""


def test_motivo_calle_distinta_es_callejon_sin_salida_de_destino():
    assert "GEOCODIFICACION_CALLE_DOCUMENTAL_DISTINTA" in MOTIVOS_DESTINO_NO_RESUELTO


# ============================================================
# 2. Reconciliación retroactiva sin OCR
# ============================================================


def _fila(numero_guia, *, despachar, direccion, localidad, region, estado_ruta="RUTA_CALCULADA",
          km="20", dur="30", **over):
    fila = {c: "" for c in COLUMNAS}
    fila.update(
        archivo=f"{numero_guia}.jpeg", estado_procesamiento="OK", numero_guia=numero_guia,
        numero_transporte=f"T{numero_guia}", despachar_a_crudo=despachar,
        direccion_entrega=direccion, localidad_entrega=localidad, region_entrega=region,
        estado_ruta=estado_ruta, estado_entrega="RESUELTO" if estado_ruta == "RUTA_CALCULADA" else "NO_INTENTADO",
        distancia_km=km if estado_ruta == "RUTA_CALCULADA" else "",
        duracion_min=dur if estado_ruta == "RUTA_CALCULADA" else "",
        proveedor_ruta="openrouteservice" if estado_ruta == "RUTA_CALCULADA" else "",
        codigo_pais="CL", codigo_unidad="13114", codigo_contexto="13",
        indicador_revision="OK", estado_documental="OK", estado_operacional="OK",
    )
    fila.update(over)
    return fila


def _escribir(ruta, filas):
    with ruta.open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNAS, delimiter=";")
        w.writeheader()
        w.writerows(filas)


def _leer(ruta):
    with ruta.open(newline="", encoding="utf-8-sig") as fh:
        return {f["numero_guia"]: f for f in csv.DictReader(fh, delimiter=";")}


_TESTIGOS = [
    dict(numero_guia="464170", despachar="AV. ALMTE. LATORRE 843 MEJILLONES MEJILLONES",
         direccion="898 Avenida Almirante Latorre, Mejillones, AN, Chile",
         localidad="Mejillones", region="De Antofagasta",
         motivo="GEOCODIFICACION_NUMERO_INCOMPATIBLE: 843 != 898"),
    dict(numero_guia="464653", despachar="PDTE. BRESCO 6903 LAS CONDES LAS CONDES",
         direccion="Avenida Las Condes 6903", localidad="Las Condes", region="Metropolitana",
         motivo="GEOCODIFICACION_DEMASIADO_GENERICA"),
    dict(numero_guia="464746", despachar="CAM. EL NOVICIADO LAMPA LAMPA",
         direccion="Lampa, RM, Chile", localidad="Lampa", region="Metropolitana",
         motivo="GEOCODIFICACION_DEMASIADO_GENERICA"),
]


def test_reconcilia_los_tres_testigos_sin_ocr(tmp_path):
    ruta = tmp_path / "guias.csv"
    _escribir(ruta, [_fila(t["numero_guia"], despachar=t["despachar"], direccion=t["direccion"],
                           localidad=t["localidad"], region=t["region"]) for t in _TESTIGOS])
    res = revalidar_destino_contra_comuna_documental_sin_ocr(ruta_dataset=ruta)
    assert set(res["guias_actualizadas"]) == {"464170", "464653", "464746"}
    filas = _leer(ruta)
    for t in _TESTIGOS:
        f = filas[t["numero_guia"]]
        assert f["estado_ruta"] == "REQUIERE_REVISION"
        assert f["motivo_ruta"] == t["motivo"]
        assert f["direccion_entrega"] == "" and f["localidad_entrega"] == "" and f["region_entrega"] == ""
        assert f["distancia_km"] == "" and f["duracion_min"] == "" and f["proveedor_ruta"] == ""
        assert f["estado_entrega"] == "NO_INTENTADO"
        assert f["codigo_pais"] == "" and f["codigo_unidad"] == "" and f["codigo_contexto"] == ""
        # criterio 7: la evidencia documental NUNCA se sobrescribe
        assert f["despachar_a_crudo"] == t["despachar"]


def test_reconciliacion_es_idempotente(tmp_path):
    ruta = tmp_path / "guias.csv"
    _escribir(ruta, [_fila(t["numero_guia"], despachar=t["despachar"], direccion=t["direccion"],
                           localidad=t["localidad"], region=t["region"]) for t in _TESTIGOS])
    assert len(revalidar_destino_contra_comuna_documental_sin_ocr(ruta_dataset=ruta)["guias_actualizadas"]) == 3
    assert revalidar_destino_contra_comuna_documental_sin_ocr(ruta_dataset=ruta)["guias_actualizadas"] == []


def test_no_toca_una_geocodificacion_coherente(tmp_path):
    ruta = tmp_path / "guias.csv"
    _escribir(ruta, [
        _fila("900001", despachar="PUERTA DEL SOL 83 LAS CONDES",
              direccion="Puerta del Sol 83, Las Condes", localidad="Las Condes", region="Metropolitana"),
        _fila("900002", despachar="CAMINO A MELIFILLA 1OBOD SANTIAGO MAIPU",
              direccion="CAMINO A MELIPILLA 10800 SANTIAGO MAIPU", localidad="Maipu", region="Metropolitana"),
    ])
    assert revalidar_destino_contra_comuna_documental_sin_ocr(ruta_dataset=ruta)["guias_actualizadas"] == []


def test_filas_sin_destino_operacional_estables_472477_472623_472624(tmp_path):
    ruta = tmp_path / "guias.csv"
    filas = [
        _fila("472477", despachar="", direccion="", localidad="", region="",
              estado_ruta="REQUIERE_REVISION", motivos_revision_documento="MATERIAL_AUSENTE | DESTINO_CONTAMINADO_POR_OTRA_SECCION",
              indicador_revision="REVISAR", estado_documental="REQUIERE_REVISION", estado_operacional="REQUIERE_REVISION",
              codigo_pais="", codigo_unidad="", codigo_contexto=""),
        _fila("472623", despachar="", direccion="", localidad="", region="",
              estado_ruta="REQUIERE_REVISION", motivo_ruta="DESTINO_RECHAZADO_POR_EVIDENCIA_B1",
              motivos_revision_documento="DESTINO_CONTAMINADO_POR_OTRA_SECCION",
              indicador_revision="REVISAR", estado_documental="REQUIERE_REVISION", estado_operacional="REQUIERE_REVISION",
              codigo_pais="", codigo_unidad="", codigo_contexto=""),
        _fila("472624", despachar="", direccion="", localidad="", region="",
              estado_ruta="REQUIERE_REVISION", motivo_ruta="DESTINO_RECHAZADO_POR_EVIDENCIA_B1",
              motivos_revision_documento="DESTINO_CONTAMINADO_POR_OTRA_SECCION",
              indicador_revision="REVISAR", estado_documental="REQUIERE_REVISION", estado_operacional="REQUIERE_REVISION",
              codigo_pais="", codigo_unidad="", codigo_contexto=""),
    ]
    _escribir(ruta, filas)
    antes = _leer(ruta)
    assert revalidar_destino_contra_comuna_documental_sin_ocr(ruta_dataset=ruta)["guias_actualizadas"] == []
    assert _leer(ruta) == antes


# ============================================================
# 3. Puerta en vivo -- resolver_destino_entrega_validado
# ============================================================


class _ProvFijo(ProveedorRutasSimulado):
    """Devuelve SIEMPRE el mismo candidato -- misma técnica que
    tests/test_validacion_geografica_lote10.py."""

    def __init__(self, *, etiqueta, localidad, region, confianza=0.95):
        from atlas_core.rutas.modelos import ResultadoRuta
        super().__init__(resultado_ruta=ResultadoRuta(EstadoRuta.RUTA_CALCULADA, 12.0, 20.0, "SINTETICO"))
        self._cand = CandidatoGeocodificacion(
            Coordenadas(-70.4, -23.1), etiqueta, confianza, localidad, region,
        )

    def geocodificar(self, direccion):
        return ResultadoGeocodificacion(EstadoRuta.REQUIERE_REVISION, (self._cand,), "")

    def geocodificar_estructurado(self, direccion, contexto):
        return self.geocodificar(direccion)


def _proveedor_con_candidato(consulta, etiqueta, *, localidad, region, confianza=0.95):
    return _ProvFijo(etiqueta=etiqueta, localidad=localidad, region=region, confianza=confianza)


def test_puerta_en_vivo_rechaza_numero_incoherente():
    texto = "AV. ALMTE. LATORRE 843 MEJILLONES MEJILLONES"
    proveedor = _proveedor_con_candidato(
        f"{texto}, Chile", "898 Avenida Almirante Latorre, Mejillones, AN, Chile",
        localidad="Mejillones", region="De Antofagasta",
    )
    r = resolver_destino_entrega_validado(texto, proveedor)
    assert r.estado == ESTADO_REVISAR
    assert r.motivo == "GEOCODIFICACION_NUMERO_INCOMPATIBLE: 843 != 898"
    assert r.despachar_a_crudo == texto           # criterio 7
    assert r.localidad == "" and r.region == ""   # etiqueta rechazada nunca se expone


def test_puerta_en_vivo_rechaza_degradacion_a_comuna():
    texto = "PDTE. BRESCO 6903 LAS CONDES LAS CONDES"
    proveedor = _proveedor_con_candidato(
        f"{texto}, Chile", "Avenida Las Condes 6903", localidad="Las Condes", region="Metropolitana",
    )
    r = resolver_destino_entrega_validado(texto, proveedor)
    assert r.estado == ESTADO_REVISAR
    assert r.motivo == "GEOCODIFICACION_DEMASIADO_GENERICA"


def test_puerta_en_vivo_acepta_candidato_coherente():
    texto = "PUERTA DEL SOL 83 LAS CONDES"
    proveedor = _proveedor_con_candidato(
        f"{texto}, Chile", "Puerta del Sol 83, Las Condes", localidad="Las Condes", region="Metropolitana",
    )
    r = resolver_destino_entrega_validado(texto, proveedor)
    assert r.estado == ESTADO_RESUELTO
