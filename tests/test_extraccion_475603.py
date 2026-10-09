"""Caso real 475603 (Mobile, YOLITO BALART HNOS LTDA, obra CASA HELSINSKI).

PaddleOCR leyó bien la guía, pero el orden de lectura intercaló columnas:
- DESPACHAR A lineal = "12-10-2026 :17576134-9 LLEGADA" (FECHA LLEGADA y
  RUT CHOFER); la geometría tenía la dirección impresa.
- OBRA DESTINO = "INMOB CASA HELSINS", recortada por el borde del campo.
- PESO KG = 5810, la numeración de "HELSINSKI 5810" tres líneas después de
  la etiqueta; el valor ":10.700,00" quedó antes de ella (Bruto 19.590 -
  Tara 8.890 = 10.700).

Los bloques de abajo son la geometría real de la zona inferior de la guía."""
from __future__ import annotations

from types import SimpleNamespace

from atlas_core.catalogo_clientes import CatalogoClientes, EstadoCalidadCliente
from atlas_core.catalogo_destinos import CatalogoDestinos
from atlas_core.catalogo_obras_destinos import CatalogoObrasDestinos, Evidencia, Obra, TipoEvidencia
from atlas_core.motor_evidencia_obras import resolver_obra_por_recorte_corroborado_por_destino
from atlas_core.ocr import BloqueOCR
from atlas_core.procesamiento_masivo import (
    _corroborar_obra_destino_confirmada,
    extraer_peso_kg_corroborado_tara_bruto,
    extraer_peso_kg_etiquetado,
)
from atlas_core.rutas.destino_entrega import despachar_a_documental
from atlas_core.rutas.destino_estructurado import extraer_identificadores_destino

# (texto, x1, y1, x2, y2) en el orden de lectura de PaddleOCR.
_ZONA_INFERIOR_475603 = (
    ("Tara : 8.890,000 Peso Bruto : 19.590,000", 629, 2071, 1251, 2133),
    ("FECHA", 1181, 2150, 1278, 2181),
    ("FOLIO", 777, 2170, 867, 2209),
    ("MOTIVO", 1650, 2167, 1765, 2198),
    ("TIPO DE DOCUMENTO", 228, 2192, 531, 2231),
    ("12.10 en Obra", 617, 2219, 1379, 2299),
    ("VALORTOTAL:10.400.400", 136, 2272, 540, 2319),
    ("RETIRA", 1224, 2309, 1325, 2337),
    (":10.700,00", 339, 2311, 524, 2347),
    (": CRISTOPHER RETAMAL", 1366, 2312, 1690, 2358),
    ("PESO KG.", 135, 2319, 278, 2356),
    ("PATENTE", 1222, 2336, 1350, 2366),
    (": BPHR67", 1366, 2340, 1498, 2375),
    (": HELSINSKI 5810 LA REINA SANTIAGO", 450, 2330, 991, 2393),
    ("FECHA", 1221, 2365, 1319, 2396),
    ("DESPACHAR A", 135, 2368, 347, 2409),
    (":12-10-2026", 1366, 2379, 1563, 2425),
    (":17576134-9", 451, 2381, 650, 2424),
    ("LLEGADA", 1222, 2394, 1351, 2424),
    ("RUT CHOFER", 136, 2400, 327, 2440),
    (":08-10-2026", 453, 2425, 650, 2469),
    ("FECHA SALIDA", 138, 2441, 352, 2488),
)
_TEXTOS = [texto for texto, *_ in _ZONA_INFERIOR_475603]
_BLOQUES = [
    BloqueOCR(texto=texto, bounding_box=((x1, y1), (x2, y1), (x2, y2), (x1, y2)), confianza=0.97)
    for texto, x1, y1, x2, y2 in _ZONA_INFERIOR_475603
]


# ============================================================
# DESPACHAR A
# ============================================================


def test_lineal_475603_esta_contaminada_por_fecha_y_rut():
    assert extraer_identificadores_destino(_TEXTOS).despachar_a == "12-10-2026 :17576134-9 LLEGADA"


def test_despachar_a_contaminado_por_fecha_rut_etiqueta_cede_ante_la_geometria():
    assert despachar_a_documental(
        _TEXTOS, _BLOQUES, chofer_resuelto="CRISTOPHER RETAMAL",
    ) == "HELSINSKI 5810 LA REINA SANTIAGO"


def test_sin_bloques_se_conserva_la_lectura_lineal():
    assert despachar_a_documental(_TEXTOS, None) == "12-10-2026 :17576134-9 LLEGADA"


def test_geometrica_tambien_contaminada_no_reemplaza_a_la_lineal():
    bloques = [
        b if "HELSINSKI" not in b.texto else BloqueOCR(
            texto=": 12-10-2026 LLEGADA", bounding_box=b.bounding_box, confianza=b.confianza,
        )
        for b in _BLOQUES
    ]
    textos = [": 12-10-2026 LLEGADA" if "HELSINSKI" in t else t for t in _TEXTOS]
    assert despachar_a_documental(textos, bloques) == "12-10-2026 :17576134-9 LLEGADA"


def test_lineal_limpia_no_se_reemplaza():
    textos = ["DESPACHAR A", ": AV LAS CONDES 7090 LAS CONDES", "RUT CHOFER", ":17576134-9"]
    bloques = [
        BloqueOCR(texto="DESPACHAR A", bounding_box=((100, 100), (300, 100), (300, 130), (100, 130)), confianza=0.97),
        BloqueOCR(texto=": OTRA CALLE 1 RENCA", bounding_box=((320, 100), (700, 100), (700, 130), (320, 130)), confianza=0.97),
    ]
    assert despachar_a_documental(textos, bloques) == "AV LAS CONDES 7090 LAS CONDES"


# ============================================================
# PESO KG
# ============================================================


def test_numeracion_de_la_direccion_no_es_peso():
    assert extraer_peso_kg_etiquetado(_TEXTOS) == "No encontrado"


def test_fecha_telefono_o_texto_pegado_no_son_peso():
    """Formas reales vistas en trazas (472708, 473263, 473324)."""
    assert extraer_peso_kg_etiquetado(["PESO KG.", "FECHA", ":27-08-2026"]) == "No encontrado"
    assert extraer_peso_kg_etiquetado(["PESOKG", "07AM JORGE +56940274743"]) == "No encontrado"
    assert extraer_peso_kg_etiquetado(["PESO KG", "329J 5001"]) == "No encontrado"


def test_peso_sin_separador_tras_la_etiqueta_sigue_aceptado():
    assert extraer_peso_kg_etiquetado(["PESO KG.", ": 7756"]) == "7756"
    assert extraer_peso_kg_etiquetado(["PESO KG: 7756 PATENTE"]) == "7756"
    assert extraer_peso_kg_etiquetado(["PESO KG.", "PATENTE", ": 9.231,00"]) == "9231"


def test_peso_neto_corroborado_por_bruto_menos_tara():
    assert extraer_peso_kg_corroborado_tara_bruto(_TEXTOS) == "10700"


def test_bruto_menos_tara_sin_valor_impreso_igual_se_abstiene():
    textos = [t for t in _TEXTOS if t != ":10.700,00"]
    assert extraer_peso_kg_corroborado_tara_bruto(textos) == "No encontrado"
    otro = [":10.500,00" if t == ":10.700,00" else t for t in _TEXTOS]
    assert extraer_peso_kg_corroborado_tara_bruto(otro) == "No encontrado"


def test_sin_tara_o_bruto_se_abstiene():
    textos = [t for t in _TEXTOS if not t.startswith("Tara")]
    assert extraer_peso_kg_corroborado_tara_bruto(textos) == "No encontrado"


# ============================================================
# OBRA DESTINO recortada
# ============================================================


def _obra(nombre, *, aliases=(), obra_id="obra-helsinski") -> Obra:
    return Obra(
        obra_id=obra_id, cliente_id="cliente-x", nombre_canonico=nombre, nombre_normalizado=nombre,
        aliases_documentales=tuple(aliases), estado="CONFIRMADA", estado_vigencia="ACTIVO", evidencias=(),
        fecha_creacion="2026-01-01T00:00:00+00:00", fecha_modificacion="2026-01-01T00:00:00+00:00",
    )


def _recorte(nombre, obras, *, direccion="HELSINSKI 5810 LA REINA SANTIAGO", destinos=("HELSINSKI 5810 LA REINA SANTIAGO",)):
    return resolver_obra_por_recorte_corroborado_por_destino(
        nombre_documental=nombre, direccion_documental=direccion, obras_confirmadas_mismo_cliente=tuple(obras),
        destinos_confirmados_de_obra=lambda obra: [SimpleNamespace(direccion=d) for d in destinos],
    )


def test_recorte_475603_resuelve_por_alias_y_destino_confirmado():
    obra = _obra("CASA HELSINSKI", aliases=("INMOB CASA RELSINSKI SPA", "INMOB CASA HELSINSKI SPA"))
    assert _recorte("INMOB CASA HELSINS", [obra]) is obra


def test_recorte_sin_destino_confirmado_en_el_documento_se_abstiene():
    obra = _obra("CASA HELSINSKI", aliases=("INMOB CASA HELSINSKI SPA",))
    assert _recorte("INMOB CASA HELSINS", [obra], direccion="12-10-2026 :17576134-9 LLEGADA") is None
    assert _recorte("INMOB CASA HELSINS", [obra], direccion="AV LAS CONDES 7090") is None
    assert _recorte("INMOB CASA HELSINS", [obra], destinos=()) is None


def test_recorte_con_dos_obras_candidatas_se_abstiene():
    a = _obra("INMOB CASA HELSINSKI SPA", obra_id="a")
    b = _obra("INMOB CASA HELSINSKIA NORTE", obra_id="b")
    assert _recorte("INMOB CASA HELSINS", [a, b]) is None


def test_recorte_demasiado_corto_se_abstiene():
    obra = _obra("INMOB CASA HELSINSKI SPA")
    assert _recorte("CASA HELSINS", [obra]) is None
    assert _recorte("INMOB CASA HEL", [obra]) is None


def test_recorte_que_es_otra_comuna_real_se_abstiene():
    """TALCA es una comuna real distinta de TALCAHUANO: no es un recorte."""
    obra = _obra("PRODALAM SA TALCAHUANO")
    assert _recorte(
        "PRODALAM SA TALCA", [obra], direccion="AMERICO VESPUCIO 730", destinos=("AMERICO VESPUCIO 730",),
    ) is None


def test_primer_pase_corrobora_obra_recortada_con_destino_documental(tmp_path):
    carpeta = tmp_path / "catalogos"
    clientes = carpeta / "clientes.json"
    cliente = CatalogoClientes(clientes).crear(
        razon_social="YOLITO BALART HNOS LTDA", rut="80.565.900-9", fuente="PRUEBA",
        estado_calidad=EstadoCalidadCliente.CONFIRMADO,
    )
    destino = CatalogoDestinos(carpeta / "destinos_maestros.json", ruta_clientes=clientes).crear(
        cliente_id=cliente.cliente_id, nombre_destino="HELSINSKI 5810 LA REINA SANTIAGO",
        direccion="HELSINSKI 5810 LA REINA SANTIAGO", comuna="LA REINA", region="", pais="CHILE", fuente="PRUEBA",
    )
    catalogo = CatalogoObrasDestinos(
        carpeta / "obras_destinos.json", ruta_clientes=clientes, ruta_destinos=carpeta / "destinos_maestros.json",
    )
    evidencia = Evidencia(
        tipo=TipoEvidencia.GUIA.value, identificador_fuente="472096", referencia_hash="a" * 64,
        campos_observados={"obra": "CASA HELSINSKI"}, fecha="2026-01-01T00:00:00+00:00",
        actor_proceso="test", resultado="SOPORTA",
    )
    observacion = catalogo.registrar_observacion(
        cliente_id=cliente.cliente_id, nombre_obra="CASA HELSINSKI", destino_id=destino.destino_id, evidencia=evidencia,
    )
    catalogo.confirmar_relacion(observacion.relacion.relacion_id, actor="HUMANO")
    catalogo.actualizar_identidad_obra(
        observacion.relacion.obra_id, nombre_canonico="CASA HELSINSKI",
        aliases_documentales=("INMOB CASA HELSINSKI SPA",), evidencia=evidencia,
    )

    def corroborar(direccion):
        return _corroborar_obra_destino_confirmada(
            carpeta, cliente_texto="YOLITO BALART HNOS LTDA", rut_cliente="80.565.900-9",
            obra_documental="INMOB CASA HELSINS", identidad_cliente_corroborada=True,
            direccion_documental=direccion,
        )

    resolucion = corroborar("HELSINSKI 5810 LA REINA SANTIAGO")
    assert resolucion is not None
    assert resolucion.obra.nombre_canonico == "CASA HELSINSKI"
    assert resolucion.destino.destino_id == destino.destino_id
    assert corroborar("12-10-2026 :17576134-9 LLEGADA") is None
