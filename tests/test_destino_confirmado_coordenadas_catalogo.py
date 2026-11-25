"""Destino confirmado por un humano que el catálogo ya conoce con coordenadas.

Casos reales 492111/483526 (VISTA CLARA 2351, CERRILLOS): Javier confirmó el
destino por B1; la confirmación volvió a geocodificar el texto, el
geocodificador devolvió "Santiago" y la ruta quedó PENDIENTE
(GEOCODIFICACION_CONTRADICE_COMUNA_CONFIRMADA), aunque el catálogo ya tenía
ese destino CONFIRMADO con coordenadas verificadas. Caso real 485242 (SANTA
ISABEL 585, LAMPA): dos destinos confirmados de la misma identidad a 535 m --
ambigüedad real, nunca se elige uno.
"""
from __future__ import annotations

import csv
import json
import uuid
from pathlib import Path

import pytest

from atlas_core.catalogo_plantas import CatalogoPlantas, EstadoCalidad
from atlas_core.destino_operacional import (
    METODO_UBICACION_CATALOGO,
    TIPO,
    calcular_ruta_operacional,
    proyectar_destino,
    recalcular_ruta_desde_planta,
)
from atlas_core.identidad_destino import IndiceIdentidadDestinos
from atlas_core.catalogo_destinos import CatalogoDestinos
from atlas_core.procesamiento_masivo import COLUMNAS
from atlas_core.recalculo_ruta_planta import CLAVE_RUTA_OPERACIONAL, recalcular_rutas_hacia_planta_conocida
from atlas_core.reconciliacion_estado_derivado import _pendientes_ruta
from atlas_core.rutas.modelos import EstadoRuta, ResultadoRuta
from atlas_core.rutas.proveedor import ProveedorRutasSimulado

VISTA_CLARA = (-33.524258, -70.7149958)
SANTA_ISABEL_A = (-33.310665, -70.737609)
SANTA_ISABEL_B = (-33.307635, -70.733135)  # 535 m de A
DECISION = "ACCION_OPERACIONAL:7a8f7d3f5d714b23bede4e4e063c33b5"


class Proveedor(ProveedorRutasSimulado):
    """Calcula rutas; geocodificar queda registrado (no debería ocurrir)."""

    def __init__(self, distancia=17.4211):
        super().__init__(resultado_ruta=ResultadoRuta(EstadoRuta.RUTA_CALCULADA, distancia, 21.5, ""))
        self.destinos, self.geocodificaciones = [], []

    def calcular_ruta(self, origen, destino, perfil):
        self.destinos.append((destino.latitud, destino.longitud))
        return super().calcular_ruta(origen, destino, perfil)

    def geocodificar(self, direccion):
        self.geocodificaciones.append(direccion)
        return super().geocodificar(direccion)

    def geocodificar_estructurado(self, *args, **kwargs):
        self.geocodificaciones.append(args)
        return super().geocodificar_estructurado(*args, **kwargs)


def _destino(direccion, comuna, punto, *, estado="CONFIRMADO", vigencia="ACTIVO"):
    return {
        "destino_id": str(uuid.uuid4()), "cliente_id": "", "nombre_destino": direccion.split(",")[0],
        "nombre_normalizado": direccion.split(",")[0], "codigo_destino": "", "direccion": direccion,
        "comuna": comuna, "region": "REGIÓN METROPOLITANA", "pais": "CHILE",
        "latitud": punto[0] if punto else None, "longitud": punto[1] if punto else None, "aliases": [],
        "estado_calidad": estado, "estado_vigencia": vigencia, "fuente": "PRUEBA", "observacion": "",
        "fecha_creacion": "2026-08-04T00:00:00+00:00", "fecha_modificacion": "2026-08-04T00:00:00+00:00",
    }


def _fila(**valores):
    fila = {c: "" for c in COLUMNAS}
    fila.update(valores)
    return fila


@pytest.fixture
def raiz(tmp_path):
    actual = tmp_path / "operacion" / "actual"
    actual.mkdir(parents=True)
    catalogos = tmp_path / "catalogos_privados"
    catalogos.mkdir()
    renca = CatalogoPlantas(catalogos / "plantas.json").crear(
        nombre="AZA RENCA", direccion="LA UNIÓN 3070", comuna="RENCA", latitud=-33.401595, longitud=-70.685226,
        punto_ruteo_latitud=-33.399989, punto_ruteo_longitud=-70.687632, pais="CHILE", fuente="PRUEBA",
        region="RM", estado_calidad=EstadoCalidad.CONFIRMADA)
    destinos = [
        _destino("VISTA CLARA 2351, CERRILLOS, REGIÓN METROPOLITANA, CHILE", "CERRILLOS", VISTA_CLARA),
        # Duplicado retirado con comuna "Santiago": no participa.
        _destino("VISTA CLARA 2351, CERRILLOS", "Santiago", (-33.524092, -70.715003), vigencia="INACTIVO"),
        _destino("SANTA ISABEL 585, LAMPA, CHILE", "LAMPA", SANTA_ISABEL_A),
        _destino("SANTA ISABEL 585", "LAMPA", SANTA_ISABEL_B),
        _destino("GALVARINO 8501", "QUILICURA", None),
    ]
    (catalogos / "destinos_maestros.json").write_text(
        json.dumps({"version_formato": 1, "destinos": destinos}, ensure_ascii=False), encoding="utf-8")
    comunes = dict(estado_procesamiento="OK", planta_origen_id=renca.planta_id, planta_origen_nombre="AZA RENCA",
                   indicador_revision="OK", estado_documental="OK", estado_ruta="REQUIERE_REVISION",
                   motivo_ruta="GEOCODIFICACION_DIRECCION_NO_ENCONTRADA", estado_operacional="REQUIERE_REVISION",
                   metricas_procesamiento_json="{}")
    filas = [
        _fila(archivo="mobile/7cf1/original.jpg", numero_guia="492111", numero_transporte="No encontrado",
              despachar_a_crudo="VISTA CLARA 23SI CERRILLOS", **comunes),
        _fila(archivo="485242.jpeg", numero_guia="485242", numero_transporte="0000371601",
              despachar_a_crudo="SANTA ISABEL SBS SANTIAGO LAMPA", **comunes),
        _fila(archivo="485469.jpeg", numero_guia="485469", numero_transporte="0000371700",
              despachar_a_crudo="GALVARINO 85O1 QUILICURA", **comunes),
    ]
    with (actual / "analisis_completo_guias.csv").open("w", encoding="utf-8-sig", newline="") as f:
        escritor = csv.DictWriter(f, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader()
        escritor.writerows(filas)

    def decision(decision_id, archivo, guia, transporte, direccion, comuna, ruta, conservar=False):
        return {"decision_id": decision_id, "tipo": TIPO, "accion": "CORREGIR_DESTINO_OPERACIONAL",
                "actor": "B1", "confirmado_por": "JAVIER_DESKTOP",
                "documento": {"archivo": archivo, "numero_guia": guia, "numero_transporte": transporte},
                "destino_operacional": {"direccion": direccion, "comuna": comuna},
                "ruta_operacional": ruta, "conservar_estado_operacional": conservar}

    pendiente = {"estado_ruta": "PENDIENTE", "motivo": "GEOCODIFICACION_CONTRADICE_COMUNA_CONFIRMADA",
                 "comuna_resuelta": "Santiago"}
    ledger = {"schema_version": 1, "aplicaciones": [
        decision(DECISION, "mobile/7cf1/original.jpg", "492111", "No encontrado", "VISTA CLARA 2351", "CERRILLOS",
                 pendiente),
        decision("D-485242", "485242.jpeg", "485242", "0000371601", "SANTA ISABEL 585", "LAMPA",
                 {"estado_ruta": "PENDIENTE"}),
        decision("D-485469", "485469.jpeg", "485469", "0000371700", "GALVARINO 8501", "QUILICURA",
                 {"estado_ruta": "PENDIENTE"}),
    ]}
    (actual / "decisiones_aplicadas.json").write_text(json.dumps(ledger), encoding="utf-8")
    return tmp_path


def _filas(raiz):
    with (raiz / "operacion/actual/analisis_completo_guias.csv").open(encoding="utf-8-sig", newline="") as f:
        return {r["archivo"]: r for r in csv.DictReader(f, delimiter=";")}


def _ledger(raiz):
    return json.loads((raiz / "operacion/actual/decisiones_aplicadas.json").read_text(encoding="utf-8"))


def _indice(raiz):
    return IndiceIdentidadDestinos(CatalogoDestinos(raiz / "catalogos_privados/destinos_maestros.json").listar())


# --- identidad ------------------------------------------------------------

def test_identidad_unica_con_coordenadas_confirmadas(raiz):
    destino = _indice(raiz).destino_con_coordenadas("VISTA CLARA 2351", "CERRILLOS")
    assert destino is not None and (destino.latitud, destino.longitud) == VISTA_CLARA


@pytest.mark.parametrize("direccion,comuna", [
    ("SANTA ISABEL 585", "LAMPA"),       # dos registros confirmados a 535 m
    ("VISTA CLARA 2351", "MAIPU"),       # otra comuna
    ("VISTA CLARA 2353", "CERRILLOS"),   # otro número
    ("GALVARINO 8501", "QUILICURA"),     # confirmado sin coordenadas
])
def test_identidad_se_abstiene(raiz, direccion, comuna):
    assert _indice(raiz).destino_con_coordenadas(direccion, comuna) is None


def test_mismo_punto_con_otro_formato_es_una_sola_identidad(raiz):
    ruta = raiz / "catalogos_privados/destinos_maestros.json"
    contenido = json.loads(ruta.read_text(encoding="utf-8"))
    contenido["destinos"].append(_destino("VISTA CLARA 2351", "CERRILLOS", (-33.5243, -70.7150)))
    ruta.write_text(json.dumps(contenido), encoding="utf-8")
    assert _indice(raiz).destino_con_coordenadas("VISTA CLARA 2351", "CERRILLOS") is not None


# --- confirmación ---------------------------------------------------------

def test_confirmar_usa_coordenadas_del_catalogo_sin_geocodificar(raiz):
    fila = _filas(raiz)["mobile/7cf1/original.jpg"]
    proveedor = Proveedor()
    ruta = calcular_ruta_operacional(fila, "VISTA CLARA 2351", "CERRILLOS",
                                     carpeta_catalogos=raiz / "catalogos_privados", proveedor_rutas=proveedor,
                                     proveedor_rutas_fallback=proveedor)
    assert proveedor.geocodificaciones == []
    assert proveedor.destinos == [VISTA_CLARA]
    assert ruta["estado_ruta"] == "RUTA_CALCULADA" and ruta["distancia_km"] == "17.4211"
    assert ruta["comuna"] == "CERRILLOS" and ruta["planta_origen_id"] == fila["planta_origen_id"]
    assert ruta["metodo_ubicacion"] == METODO_UBICACION_CATALOGO and ruta["destino_id"]
    assert (ruta["latitud_entrega"], ruta["codigo_unidad"]) == (str(VISTA_CLARA[0]), "13102")


def test_confirmar_ambiguo_sigue_por_el_geocodificador(raiz):
    fila = _filas(raiz)["485242.jpeg"]
    proveedor = Proveedor()
    ruta = calcular_ruta_operacional(fila, "SANTA ISABEL 585", "LAMPA",
                                     carpeta_catalogos=raiz / "catalogos_privados", proveedor_rutas=proveedor,
                                     proveedor_rutas_fallback=proveedor)
    assert proveedor.geocodificaciones  # sin identidad inequívoca: camino de siempre
    assert "metodo_ubicacion" not in ruta


def test_planta_desconocida_deja_pendiente_sin_publicar_ubicacion(raiz):
    fila = {**_filas(raiz)["mobile/7cf1/original.jpg"], "planta_origen_id": "desconocida"}
    ruta = calcular_ruta_operacional(fila, "VISTA CLARA 2351", "CERRILLOS",
                                     carpeta_catalogos=raiz / "catalogos_privados", proveedor_rutas=Proveedor())
    assert ruta["estado_ruta"] == "PENDIENTE" and ruta["motivo"] == "PLANTA_ORIGEN_DESCONOCIDA"
    assert "coordenadas_confirmadas" not in ruta
    ledger = {"aplicaciones": [{**_ledger(raiz)["aplicaciones"][0], "ruta_operacional": ruta}]}
    vista = proyectar_destino(fila, ledger)
    assert vista["estado_ruta"] == "" and vista["latitud_entrega"] == ""


def test_planta_corregida_sin_coordenadas_previas_usa_el_catalogo(raiz):
    fila = _filas(raiz)["mobile/7cf1/original.jpg"]
    proveedor = Proveedor()
    ruta = recalcular_ruta_desde_planta(fila["planta_origen_id"], "VISTA CLARA 2351", "CERRILLOS",
                                        {"estado_ruta": "PENDIENTE"}, fila=fila,
                                        carpeta_catalogos=raiz / "catalogos_privados", proveedor_rutas=proveedor)
    assert proveedor.geocodificaciones == [] and ruta["estado_ruta"] == "RUTA_CALCULADA"


# --- decisiones existentes: recálculo explícito ----------------------------

def test_recalculo_explicito_publica_ruta_de_decision_existente(raiz):
    proveedor = Proveedor()
    ledger_antes = _ledger(raiz)
    r = recalcular_rutas_hacia_planta_conocida(raiz_atlas=raiz, archivos=["mobile/7cf1/original.jpg"],
                                               proveedor_rutas=proveedor)
    assert [x["numero_guia"] for x in r["recalculadas"]] == ["492111"] and r["abstenciones"] == []
    assert proveedor.geocodificaciones == [] and proveedor.destinos == [VISTA_CLARA]
    assert _ledger(raiz) == ledger_antes  # la decisión humana no cambia
    fila = _filas(raiz)["mobile/7cf1/original.jpg"]
    registro = json.loads(fila["metricas_procesamiento_json"])[CLAVE_RUTA_OPERACIONAL]
    assert registro["decision_id"] == DECISION and registro["destino_id"]
    vista = proyectar_destino(fila, ledger_antes)
    assert (vista["direccion_entrega"], vista["localidad_entrega"]) == ("VISTA CLARA 2351", "CERRILLOS")
    assert vista["estado_ruta"] == "RUTA_CALCULADA" and vista["distancia_km"] == "17.4211"
    # Fila documental intacta salvo la métrica ligada a la decisión.
    assert fila["despachar_a_crudo"] == "VISTA CLARA 23SI CERRILLOS" and fila["estado_ruta"] == "REQUIERE_REVISION"
    # Idempotente.
    r2 = recalcular_rutas_hacia_planta_conocida(raiz_atlas=raiz, archivos=["mobile/7cf1/original.jpg"],
                                                proveedor_rutas=Proveedor())
    assert r2["abstenciones"] == [{"archivo": "mobile/7cf1/original.jpg", "motivo": "SIN_CAMBIO"}]


def test_recalculo_explicito_se_abstiene_ante_ambiguedad(raiz):
    proveedor = Proveedor()
    r = recalcular_rutas_hacia_planta_conocida(raiz_atlas=raiz, archivos=["485242.jpeg", "485469.jpeg"],
                                               proveedor_rutas=proveedor)
    assert r["recalculadas"] == [] and proveedor.destinos == [] and proveedor.geocodificaciones == []
    assert {a["archivo"]: a["motivo"] for a in r["abstenciones"]} == {
        "485242.jpeg": "DESTINO_CATALOGO_AMBIGUO",
        "485469.jpeg": "DESTINO_NO_ES_PLANTA_CONOCIDA_INEQUIVOCA",
    }


def test_conservar_estado_con_identidad_de_catalogo_se_comprueba(raiz):
    ruta = raiz / "operacion/actual/decisiones_aplicadas.json"
    ledger = _ledger(raiz)
    ledger["aplicaciones"][0]["conservar_estado_operacional"] = True
    ruta.write_text(json.dumps(ledger), encoding="utf-8")
    proveedor = Proveedor()
    r = recalcular_rutas_hacia_planta_conocida(raiz_atlas=raiz, archivos=["mobile/7cf1/original.jpg"],
                                               proveedor_rutas=proveedor)
    assert [x["numero_guia"] for x in r["recalculadas"]] == ["492111"]
    assert proveedor.geocodificaciones == [] and proveedor.destinos == [VISTA_CLARA]
    assert _ledger(raiz) == ledger
    vista = proyectar_destino(_filas(raiz)["mobile/7cf1/original.jpg"], ledger)
    assert (vista["estado_ruta"], vista["distancia_km"], vista["ruta_requiere_comprobacion"]) == (
        "RUTA_CALCULADA", "17.4211", False)
    assert vista["estado_operacional"] == "REQUIERE_REVISION"  # conservado


def test_recalculo_explicito_sin_ruta_del_proveedor_no_escribe(raiz):
    proveedor = Proveedor()
    proveedor.resultado_ruta = ResultadoRuta(EstadoRuta.SIN_CONEXION, None, None, "SIN_CONEXION")
    antes = (raiz / "operacion/actual/analisis_completo_guias.csv").read_bytes()
    r = recalcular_rutas_hacia_planta_conocida(raiz_atlas=raiz, archivos=["mobile/7cf1/original.jpg"],
                                               proveedor_rutas=proveedor)
    assert r["recalculadas"] == [] and r["abstenciones"][0]["motivo"].startswith("RUTA_NO_CALCULADA:")
    assert (raiz / "operacion/actual/analisis_completo_guias.csv").read_bytes() == antes


# --- cola técnica ---------------------------------------------------------

def test_cola_tecnica_excluye_ruta_resuelta_por_destino_humano(raiz):
    actual = raiz / "operacion/actual"
    def cola():
        return sorted(f["numero_guia"] for f in _pendientes_ruta(actual / "analisis_completo_guias.csv",
                                                                   actual / "decisiones_pendientes.json"))
    assert cola() == ["485242", "485469", "492111"]
    recalcular_rutas_hacia_planta_conocida(raiz_atlas=raiz, archivos=["mobile/7cf1/original.jpg"],
                                           proveedor_rutas=Proveedor())
    assert cola() == ["485242", "485469"]


def test_conservar_con_destino_ambiguo_no_se_geocodifica(raiz):
    # Caso real 485242: "conservar estado" + SANTA ISABEL 585 con dos puntos
    # confirmados distintos. La comprobación no puede desempatar
    # geocodificando: se abstiene.
    ruta = raiz / "operacion/actual/decisiones_aplicadas.json"
    ledger = _ledger(raiz)
    ledger["aplicaciones"][1]["conservar_estado_operacional"] = True
    ruta.write_text(json.dumps(ledger), encoding="utf-8")
    proveedor = Proveedor()
    r = recalcular_rutas_hacia_planta_conocida(raiz_atlas=raiz, archivos=["485242.jpeg"], proveedor_rutas=proveedor)
    assert r["recalculadas"] == [] and proveedor.geocodificaciones == [] and proveedor.destinos == []
    assert r["abstenciones"] == [{"archivo": "485242.jpeg", "motivo": "DESTINO_CATALOGO_AMBIGUO"}]


@pytest.mark.parametrize("entrada,recalcula", [
    ({"tipo": "CORRECCION_DOCUMENTAL_OPERADOR", "accion": "CORREGIR_CAMPO", "campo": "cliente"}, True),
    ({"tipo": "CORRECCION_DOCUMENTAL_OPERADOR", "accion": "CORREGIR_CAMPO", "campo": "patente_rampla"}, True),
    ({"tipo": "CHOFER_OPERACIONAL_DOCUMENTO", "accion": "CORREGIR_CHOFER_OPERACIONAL"}, True),
    ({"tipo": "CORRECCION_DOCUMENTAL_OPERADOR", "accion": "CORREGIR_CAMPO", "campo": "planta_origen_id"}, False),
    ({"tipo": "CORRECCION_DOCUMENTAL_OPERADOR", "accion": "CORREGIR_CAMPO", "campo": "despachar_a_crudo"}, False),
    ({"tipo": "DESTINO_NO_RESUELTO", "accion": "REGISTRAR_DIRECCION"}, False),
    ({"tipo": "ORIGEN_NO_CONFIRMADO", "accion": "CONFIRMAR"}, False),
])
def test_correcciones_sin_efecto_en_la_ruta_del_destino_humano(raiz, entrada, recalcula):
    ruta = raiz / "operacion/actual/decisiones_aplicadas.json"
    ledger = _ledger(raiz)
    ledger["aplicaciones"].insert(0, {**entrada, "decision_id": "X", "documento": {
        "archivo": "mobile/7cf1/original.jpg", "numero_guia": "492111", "numero_transporte": "No encontrado"}})
    ruta.write_text(json.dumps(ledger), encoding="utf-8")
    r = recalcular_rutas_hacia_planta_conocida(raiz_atlas=raiz, archivos=["mobile/7cf1/original.jpg"],
                                               proveedor_rutas=Proveedor())
    assert bool(r["recalculadas"]) is recalcula, r["abstenciones"]
