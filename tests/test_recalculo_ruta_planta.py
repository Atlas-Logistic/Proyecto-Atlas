"""Recálculo explícito y acotado de rutas hacia una planta confirmada.

Casos reales 477043, 477449, 477355.jpeg (número "No encontrado") y 488100
(destino operacional confirmado por Javier con la ruta pendiente congelada):
rutas derivadas antes de que el Motor reconociera AZA COLINA como destino.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from atlas_core.catalogo_plantas import CatalogoPlantas, EstadoCalidad
from atlas_core.destino_operacional import TIPO, proyectar_destino
from atlas_core.procesamiento_masivo import COLUMNAS
from atlas_core.recalculo_ruta_planta import (
    CLAVE_AUDITORIA,
    CLAVE_RUTA_OPERACIONAL,
    recalcular_rutas_hacia_planta_conocida,
)
from atlas_core.reconciliacion_estado_derivado import reconciliar_estado_derivado
from atlas_core.rutas.destino_entrega import motivo_incoherencia_destino_documental
from atlas_core.rutas.modelos import EstadoRuta, ResultadoRuta
from atlas_core.rutas.proveedor import ProveedorRutasSimulado

PUNTO_COLINA = (-33.294752, -70.730387)
DOC_HISTORICO = "PARAMERICANA NORTE 18500 SANTIAGO COLINA"
DECISION_488100 = "ACCION_OPERACIONAL:644a9257bb4f425ea134dff084d4bc81"


class Proveedor(ProveedorRutasSimulado):
    """Proveedor que registra cada destino pedido (la ruta la calcula él)."""

    def __init__(self, resultado=None):
        super().__init__(resultado_ruta=resultado or ResultadoRuta(EstadoRuta.RUTA_CALCULADA, 13.8198, 14.125, ""))
        self.destinos = []

    def calcular_ruta(self, origen, destino, perfil):
        self.destinos.append((destino.latitud, destino.longitud))
        return super().calcular_ruta(origen, destino, perfil)


def _fila(**valores):
    fila = {c: "" for c in COLUMNAS}
    fila.update(valores)
    return fila


def _historica(archivo, guia, transporte, **extra):
    base = dict(
        archivo=archivo, numero_guia=guia, numero_transporte=transporte, estado_procesamiento="OK",
        cliente="ACEROS AZA SA", descripcion_material="CHATARRA C PESADA PARA PROCESAR", peso_kg="18500",
        despachar_a_crudo=DOC_HISTORICO, direccion_entrega=DOC_HISTORICO, localidad_entrega="Colina",
        region_entrega="Metropolitana", estado_entrega="RESUELTO", codigo_pais="CL", codigo_unidad="13301",
        codigo_contexto="13", distancia_km="28.338", duracion_min="36.5", proveedor_ruta="openrouteservice",
        estado_ruta="RUTA_CALCULADA", estado_operacional="OK", indicador_revision="OK", estado_documental="OK",
        origen_determinado_por="TELEMETRIA_GPS", metricas_procesamiento_json="{}",
    )
    return _fila(**{**base, **extra})


@pytest.fixture
def raiz(tmp_path):
    actual = tmp_path / "operacion" / "actual"
    actual.mkdir(parents=True)
    catalogos = tmp_path / "catalogos_privados"
    catalogos.mkdir()
    repo = CatalogoPlantas(catalogos / "plantas.json")
    base = dict(pais="CHILE", fuente="PRUEBA", region="RM", estado_calidad=EstadoCalidad.CONFIRMADA)
    renca = repo.crear(nombre="AZA RENCA", direccion="LA UNIÓN 3070", comuna="RENCA",
                       latitud=-33.401595, longitud=-70.685226,
                       punto_ruteo_latitud=-33.399989, punto_ruteo_longitud=-70.687632, **base)
    repo.crear(nombre="AZA COLINA", direccion="AV. PDTE. EDUARDO FREI MONTALVA 18500", comuna="COLINA",
               latitud=-33.137558, longitud=-70.665977,
               punto_ruteo_latitud=PUNTO_COLINA[0], punto_ruteo_longitud=PUNTO_COLINA[1], **base)
    filas = [
        _historica("477043.jpeg", "477043", "0000355829", planta_origen_id=renca.planta_id,
                   planta_origen_nombre="AZA RENCA"),
        _historica("477355.jpeg", "No encontrado", "0000357789", planta_origen_id=renca.planta_id,
                   planta_origen_nombre="AZA RENCA", peso_kg="No encontrado"),
        _historica("otro.jpeg", "No encontrado", "0000357091", planta_origen_id=renca.planta_id,
                   planta_origen_nombre="AZA RENCA", despachar_a_crudo="PANAMERICANA NORTE 22650 SANTIAGO LAMPA",
                   direccion_entrega="PANAMERICANA NORTE 22650 SANTIAGO LAMPA", localidad_entrega="Lampa",
                   distancia_km="8.52"),
        _fila(archivo="mobile/82f1/original.jpg", numero_guia="488100", numero_transporte="0000368436",
              estado_procesamiento="OK", despachar_a_crudo="PARAMERICANA NORTE 185O0 SANTIAGO COLINA",
              planta_origen_id=renca.planta_id, planta_origen_nombre="AZA RENCA", origen_determinado_por="MOBILE",
              estado_ruta="REQUIERE_REVISION", motivo_ruta="GEOCODIFICACION_DIRECCION_NO_ENCONTRADA",
              estado_entrega="REVISAR", peso_kg="24570", descripcion_material="CHATARRA C PESADA PARA PROCESAR",
              estado_operacional="REQUIERE_REVISION", metricas_procesamiento_json="{}"),
    ]
    _escribir(tmp_path, filas)
    ledger = {"schema_version": 1, "aplicaciones": [
        {"decision_id": DECISION_488100, "tipo": TIPO, "accion": "CORREGIR_DESTINO_OPERACIONAL",
         "actor": "B1", "confirmado_por": "JAVIER_DESKTOP",
         "documento": {"archivo": "mobile/82f1/original.jpg", "numero_guia": "488100",
                       "numero_transporte": "0000368436"},
         "destino_operacional": {"direccion": "PARAMERICANA NORTE 18500", "comuna": "COLINA"},
         "ruta_operacional": {"estado_ruta": "PENDIENTE", "motivo": "MULTIPLES_UBICACIONES_DISPERSAS(5)"}},
        {"decision_id": "PESO", "tipo": "CORRECCION_DOCUMENTAL_OPERADOR", "accion": "CORREGIR_CAMPO",
         "documento": {"archivo": "mobile/82f1/original.jpg", "numero_guia": "488100",
                       "numero_transporte": "0000368436"}, "campo": "peso_kg", "valor_corregido": "24570"},
    ]}
    (actual / "decisiones_aplicadas.json").write_text(json.dumps(ledger), encoding="utf-8")
    return tmp_path


def _escribir(raiz, filas):
    with (raiz / "operacion/actual/analisis_completo_guias.csv").open("w", encoding="utf-8-sig", newline="") as f:
        escritor = csv.DictWriter(f, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader()
        escritor.writerows(filas)


def _filas(raiz):
    with (raiz / "operacion/actual/analisis_completo_guias.csv").open(encoding="utf-8-sig", newline="") as f:
        return {r["archivo"]: r for r in csv.DictReader(f, delimiter=";")}


def _ledger(raiz):
    return json.loads((raiz / "operacion/actual/decisiones_aplicadas.json").read_text(encoding="utf-8"))


# --- positivos ------------------------------------------------------------

def test_ruta_historica_se_recalcula_con_el_proveedor_hacia_el_punto_gps(raiz):
    antes = _filas(raiz)
    proveedor = Proveedor()
    r = recalcular_rutas_hacia_planta_conocida(raiz_atlas=raiz, archivos=["477043.jpeg"], proveedor_rutas=proveedor)
    assert proveedor.destinos == [PUNTO_COLINA]
    assert [x["archivo"] for x in r["recalculadas"]] == ["477043.jpeg"] and not r["abstenciones"]
    fila = _filas(raiz)["477043.jpeg"]
    assert (fila["distancia_km"], fila["estado_ruta"]) == ("13.8198", "RUTA_CALCULADA")
    assert fila["direccion_entrega"] == "AV. PDTE. EDUARDO FREI MONTALVA 18500, COLINA"
    # Documento, origen, material, peso y transporte intactos; la ruta anterior queda auditada.
    for campo in ("despachar_a_crudo", "planta_origen_id", "origen_determinado_por", "descripcion_material",
                  "peso_kg", "numero_transporte", "numero_guia"):
        assert fila[campo] == antes["477043.jpeg"][campo]
    auditoria = json.loads(fila["metricas_procesamiento_json"])[CLAVE_AUDITORIA][-1]
    assert auditoria["ruta_anterior"]["distancia_km"] == "28.338"
    # Ninguna otra fila cambia.
    despues = _filas(raiz)
    assert all(despues[a] == antes[a] for a in antes if a != "477043.jpeg")


def test_documento_sin_folio_se_identifica_por_archivo(raiz):
    antes = _filas(raiz)
    r = recalcular_rutas_hacia_planta_conocida(raiz_atlas=raiz, archivos=["477355.jpeg"], proveedor_rutas=Proveedor())
    assert [x["archivo"] for x in r["recalculadas"]] == ["477355.jpeg"]
    despues = _filas(raiz)
    assert despues["477355.jpeg"]["distancia_km"] == "13.8198"
    assert despues["477355.jpeg"]["estado_operacional"] == "OK" or antes["477355.jpeg"]["estado_operacional"] == "OK"
    assert despues["otro.jpeg"] == antes["otro.jpeg"]  # mismo número "No encontrado", intacta


def test_destino_humano_conserva_la_decision_y_proyecta_la_ruta_recalculada(raiz):
    ledger_antes = _ledger(raiz)
    antes = _filas(raiz)["mobile/82f1/original.jpg"]
    r = recalcular_rutas_hacia_planta_conocida(raiz_atlas=raiz, archivos=["mobile/82f1/original.jpg"],
                                               proveedor_rutas=Proveedor())
    assert r["recalculadas"][0]["decision_destino_id"] == DECISION_488100
    assert _ledger(raiz) == ledger_antes  # nunca crea ni modifica decisiones
    fila = _filas(raiz)["mobile/82f1/original.jpg"]
    # Columnas de ruta protegidas del destino humano: no se reescriben.
    assert all(fila[c] == antes[c] for c in ("distancia_km", "estado_ruta", "direccion_entrega", "peso_kg"))
    registro = json.loads(fila["metricas_procesamiento_json"])[CLAVE_RUTA_OPERACIONAL]
    assert (registro["decision_id"], registro["direccion"], registro["comuna"]) == (
        DECISION_488100, "PARAMERICANA NORTE 18500", "COLINA")
    proyectada = proyectar_destino(fila, ledger_antes)
    assert proyectada["direccion_entrega"] == "PARAMERICANA NORTE 18500"
    assert proyectada["localidad_entrega"] == "COLINA"
    assert (proyectada["estado_ruta"], proyectada["distancia_km"]) == ("RUTA_CALCULADA", "13.8198")


def test_decision_humana_posterior_anula_la_ruta_recalculada(raiz):
    recalcular_rutas_hacia_planta_conocida(raiz_atlas=raiz, archivos=["mobile/82f1/original.jpg"],
                                           proveedor_rutas=Proveedor())
    fila = _filas(raiz)["mobile/82f1/original.jpg"]
    ledger = _ledger(raiz)
    ledger["aplicaciones"].append({
        "decision_id": "ACCION_OPERACIONAL:posterior", "tipo": TIPO,
        "documento": {"archivo": "mobile/82f1/original.jpg", "numero_guia": "488100",
                      "numero_transporte": "0000368436"},
        "destino_operacional": {"direccion": "OTRA CALLE 123", "comuna": "QUILICURA"},
        "ruta_operacional": {"estado_ruta": "PENDIENTE"}})
    proyectada = proyectar_destino(fila, ledger)
    assert proyectada["direccion_entrega"] == "OTRA CALLE 123"
    assert proyectada["distancia_km"] == "" and proyectada["estado_ruta"] == ""


def test_reconciliacion_focal_con_recalculo_explicito(raiz):
    proveedor = Proveedor()
    resultado = reconciliar_estado_derivado(
        raiz_atlas=raiz, proveedor_rutas=proveedor, proveedor_rutas_fallback=proveedor,
        guias_objetivo={"477043"}, omitir_coordenadas_catalogo=True,
        recalcular_rutas_archivos=["477043.jpeg"],
    )
    assert resultado["reconciliado"]
    assert [x["archivo"] for x in resultado["rutas_recalculadas_planta"]["recalculadas"]] == ["477043.jpeg"]
    assert _filas(raiz)["477043.jpeg"]["distancia_km"] == "13.8198"


def test_reconciliacion_sin_parametro_no_toca_rutas_calculadas(raiz):
    proveedor = Proveedor()
    reconciliar_estado_derivado(raiz_atlas=raiz, proveedor_rutas=proveedor, proveedor_rutas_fallback=proveedor,
                                guias_objetivo={"477043"}, omitir_coordenadas_catalogo=True)
    assert _filas(raiz)["477043.jpeg"]["distancia_km"] == "28.338"
    assert proveedor.destinos == []


def test_recalculo_explicito_exige_reconciliacion_focal(raiz):
    with pytest.raises(ValueError):
        reconciliar_estado_derivado(raiz_atlas=raiz, recalcular_rutas_archivos=["477043.jpeg"])


def test_idempotente(raiz):
    recalcular_rutas_hacia_planta_conocida(raiz_atlas=raiz, archivos=["477043.jpeg"], proveedor_rutas=Proveedor())
    antes = _filas(raiz)
    r = recalcular_rutas_hacia_planta_conocida(raiz_atlas=raiz, archivos=["477043.jpeg"], proveedor_rutas=Proveedor())
    assert r["abstenciones"] == [{"archivo": "477043.jpeg", "motivo": "SIN_CAMBIO"}]
    assert _filas(raiz) == antes


# --- negativos --------------------------------------------------------------

def _sin_cambios(raiz, archivos, proveedor=None):
    antes, ledger = _filas(raiz), _ledger(raiz)
    r = recalcular_rutas_hacia_planta_conocida(raiz_atlas=raiz, archivos=archivos,
                                               proveedor_rutas=proveedor or Proveedor())
    assert _filas(raiz) == antes and _ledger(raiz) == ledger and not r["recalculadas"]
    return [a["motivo"] for a in r["abstenciones"]]


def test_archivo_duplicado_o_inexistente_se_abstiene(raiz):
    filas = list(_filas(raiz).values())
    _escribir(raiz, filas + [dict(filas[0], numero_transporte="0000999999")])
    assert _sin_cambios(raiz, ["477043.jpeg", "no-existe.jpg"]) == ["DOCUMENTO_NO_UNICO:2", "DOCUMENTO_NO_UNICO:0"]


def test_destino_ajeno_no_se_recalcula(raiz):
    proveedor = Proveedor()
    assert _sin_cambios(raiz, ["otro.jpeg"], proveedor) == ["DESTINO_NO_ES_PLANTA_CONOCIDA_INEQUIVOCA"]
    assert proveedor.destinos == []


def test_otra_decision_humana_sobre_el_documento_se_respeta(raiz):
    ledger = _ledger(raiz)
    ledger["aplicaciones"].append({"decision_id": "X", "tipo": "DESTINO_NO_RESUELTO", "accion": "REGISTRAR_DIRECCION",
                                   "documento": {"archivo": "477043.jpeg", "numero_guia": "477043",
                                                 "numero_transporte": "0000355829"}})
    (raiz / "operacion/actual/decisiones_aplicadas.json").write_text(json.dumps(ledger), encoding="utf-8")
    assert _sin_cambios(raiz, ["477043.jpeg"]) == ["DECISION_HUMANA_AFECTA_RUTA:DESTINO_NO_RESUELTO"]


def test_destino_humano_que_conserva_estado_recibe_su_comprobacion(raiz):
    # "Conservar estado" deja la ruta de la dirección confirmada por
    # comprobar; el recálculo explícito la hace sin tocar la decisión ni la
    # fila documental, y la proyección la publica como calculada.
    ledger = _ledger(raiz)
    ledger["aplicaciones"][0]["conservar_estado_operacional"] = True
    (raiz / "operacion/actual/decisiones_aplicadas.json").write_text(json.dumps(ledger), encoding="utf-8")
    antes = _filas(raiz)["mobile/82f1/original.jpg"]
    r = recalcular_rutas_hacia_planta_conocida(raiz_atlas=raiz, archivos=["mobile/82f1/original.jpg"],
                                               proveedor_rutas=Proveedor())
    assert [x["numero_guia"] for x in r["recalculadas"]] == ["488100"] and _ledger(raiz) == ledger
    fila = _filas(raiz)["mobile/82f1/original.jpg"]
    assert all(fila[c] == antes[c] for c in ("distancia_km", "estado_ruta", "estado_operacional"))
    vista = proyectar_destino(fila, ledger)
    assert (vista["estado_ruta"], vista["distancia_km"]) == ("RUTA_CALCULADA", "13.8198")
    assert vista["estado_operacional"] == antes["estado_operacional"]  # conservado


def test_destino_humano_hacia_otra_direccion_no_se_recalcula(raiz):
    ledger = _ledger(raiz)
    ledger["aplicaciones"][0]["destino_operacional"] = {"direccion": "GALVARINO 8501", "comuna": "QUILICURA"}
    (raiz / "operacion/actual/decisiones_aplicadas.json").write_text(json.dumps(ledger), encoding="utf-8")
    assert _sin_cambios(raiz, ["mobile/82f1/original.jpg"]) == ["DESTINO_NO_ES_PLANTA_CONOCIDA_INEQUIVOCA"]


def test_proveedor_no_disponible_no_escribe(raiz):
    caido = Proveedor(ResultadoRuta(EstadoRuta.PROVEEDOR_NO_DISPONIBLE, motivo="PROVEEDOR_NO_DISPONIBLE"))
    assert _sin_cambios(raiz, ["477043.jpeg"], caido) == ["RUTA_NO_CALCULADA:PROVEEDOR_NO_DISPONIBLE"]


def test_origen_igual_al_destino_se_abstiene(raiz):
    filas = list(_filas(raiz).values())
    colina = next(p for p in CatalogoPlantas(raiz / "catalogos_privados/plantas.json").listar() if p.nombre == "AZA COLINA")
    for fila in filas:
        if fila["archivo"] == "477043.jpeg":
            fila["planta_origen_id"] = colina.planta_id
    _escribir(raiz, filas)
    assert _sin_cambios(raiz, ["477043.jpeg"]) == ["DESTINO_NO_ES_PLANTA_CONOCIDA_INEQUIVOCA"]


# --- coherencia documental de la dirección resuelta -------------------------

@pytest.mark.parametrize("documental", [
    "PARAMERICANA NORTE 1850O SANTIAGO COLINA", "PARAMERICANA NORTE 18500 SANTIAGO COLINA",
])
def test_nombre_comun_de_la_via_no_es_incoherencia(documental):
    assert motivo_incoherencia_destino_documental(
        despachar_a_crudo=documental, etiqueta_geocodificada="AV. PDTE. EDUARDO FREI MONTALVA 18500, COLINA",
        localidad="Colina") == ""


@pytest.mark.parametrize("documental,localidad", [
    ("PARAMERICANA NORTE 18600 SANTIAGO COLINA", "Colina"),
    ("PANAMERICANA NORTE 18500 SANTIAGO LAMPA", "Lampa"),
    ("PARAMERICANA NORTE 18500", "Colina"),
    ("VICUNA MACKENNA 825 LA CISTERNA", "La Cisterna"),
])
def test_incoherencias_reales_se_siguen_detectando(documental, localidad):
    assert motivo_incoherencia_destino_documental(
        despachar_a_crudo=documental, etiqueta_geocodificada="AV. PDTE. EDUARDO FREI MONTALVA 18500, COLINA",
        localidad=localidad) != ""
