"""Revalidación territorial explícita de rutas ya publicadas (25/11/2026).

Casos reales: HELSINSKI 5810 LA REINA publicada con «Santiago» y un punto en
Conchalí (14,51 km); VICUÑA MACKENNA 3451 SAN JOAQUIN publicada con «Santiago»
(25,41 km) mientras otras guías del mismo destino ya estaban en San Joaquín.
"""
from __future__ import annotations

import csv
import json
from types import SimpleNamespace

import pytest

import atlas_core.rutas.destino_entrega as de
from atlas_core.catalogo_plantas import CatalogoPlantas, EstadoCalidad
from atlas_core.procesamiento_masivo import COLUMNAS
from atlas_core.recalculo_ruta_planta import CLAVE_AUDITORIA_TERRITORIAL, revalidar_rutas_territoriales
from atlas_core.rutas.destino_entrega import MOTIVO_FUERA_DE_COMUNA_CONOCIDA, coordenada_de_destino_fuera_de_su_comuna


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
    planta = CatalogoPlantas(catalogos / "plantas.json").crear(
        nombre="AZA COLINA", direccion="AV. PDTE. EDUARDO FREI MONTALVA 18500", comuna="COLINA",
        latitud=-33.137558, longitud=-70.665977, punto_ruteo_latitud=-33.294752, punto_ruteo_longitud=-70.730387,
        pais="CHILE", fuente="PRUEBA", region="RM", estado_calidad=EstadoCalidad.CONFIRMADA)
    (catalogos / "destinos_maestros.json").write_text(json.dumps({"version_formato": 1, "destinos": []}),
                                                      encoding="utf-8")
    publicada = dict(planta_origen_id=planta.planta_id, estado_procesamiento="OK", indicador_revision="OK",
                     estado_documental="OK", estado_operacional="OK", estado_ruta="RUTA_CALCULADA",
                     estado_entrega="RESUELTO", localidad_entrega="Santiago", codigo_unidad="13101",
                     distancia_km="14.5114", duracion_min="20", proveedor_ruta="openrouteservice",
                     metricas_procesamiento_json="{}")
    filas = [
        _fila(archivo="472096.jpeg", numero_guia="472096", despachar_a_crudo="HELSINSKI 5810 LA REINA SANTIAGO",
              direccion_entrega="HELSINSKI 5810 LA REINA SANTIAGO", **publicada),
        _fila(archivo="475542.jpeg", numero_guia="475542",
              despachar_a_crudo="AV. VICUNA MACKENNA 3451 SAN JOAQUIN SAN JOAQUIN",
              direccion_entrega="AV. VICUNA MACKENNA 3451", **{**publicada, "distancia_km": "25.4058"}),
        _fila(archivo="464715.jpeg", numero_guia="464715",
              despachar_a_crudo="AV. VICUNA MACKENNA 3451 SAN JOAQUIN SAN JOAQUIN",
              **{**publicada, "localidad_entrega": "San Joaquín", "distancia_km": "29.7897"}),
        _fila(archivo="83277.jpg", numero_guia="83277", despachar_a_crudo="HELSINSKI 5810", **publicada),
        _fila(archivo="sin_comuna.jpg", numero_guia="1", despachar_a_crudo="HELSINSKI 5810", **publicada),
    ]
    with (actual / "analisis_completo_guias.csv").open("w", encoding="utf-8-sig", newline="") as f:
        escritor = csv.DictWriter(f, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader()
        escritor.writerows(filas)
    ledger = {"schema_version": 1, "aplicaciones": [
        {"decision_id": "C", "tipo": "DESTINO_SIN_CONFIRMAR", "accion": "CONFIRMAR", "actor": "JAVIER_DESKTOP",
         "documento": {"archivo": "83277.jpg", "numero_guia": "83277", "numero_transporte": ""},
         "destino_id": "77a085b2"},
    ]}
    (actual / "decisiones_aplicadas.json").write_text(json.dumps(ledger), encoding="utf-8")
    (catalogos / "destinos_maestros.json").write_text(json.dumps({"version_formato": 1, "destinos": [{
        "destino_id": "77a085b2", "cliente_id": "", "nombre_destino": "HELSINSKI 5810",
        "nombre_normalizado": "HELSINSKI 5810", "codigo_destino": "", "direccion": "HELSINSKI 5810",
        "comuna": "LA REINA", "region": "RM", "pais": "CHILE", "latitud": -33.375286, "longitud": -70.674204,
        "aliases": [], "estado_calidad": "CONFIRMADO", "estado_vigencia": "ACTIVO", "fuente": "PRUEBA",
        "observacion": "", "fecha_creacion": "2026-10-28T00:00:00+00:00",
        "fecha_modificacion": "2026-10-28T00:00:00+00:00"}]}), encoding="utf-8")
    return tmp_path


def _filas(raiz):
    with (raiz / "operacion/actual/analisis_completo_guias.csv").open(encoding="utf-8-sig", newline="") as f:
        return {r["archivo"]: r for r in csv.DictReader(f, delimiter=";")}


class Resolucion:
    """Sustituye la resolución real: devuelve, por texto, aceptación o rechazo territorial."""

    def __init__(self, resultados):
        self.resultados, self.llamadas = resultados, []

    def __call__(self, **kw):
        self.llamadas.append((kw["despachar_a_crudo"], kw.get("comuna_confirmada_humano")))
        return self.resultados[kw["despachar_a_crudo"]]


def _rechazo(comuna):
    return SimpleNamespace(estado_ruta="REQUIERE_REVISION", distancia_km="",
                           motivo_ruta=f"{MOTIVO_FUERA_DE_COMUNA_CONOCIDA}: {comuna} (punto en Conchalí)")


ACEPTADA_SAN_JOAQUIN = SimpleNamespace(
    estado_ruta="RUTA_CALCULADA", distancia_km="29.7878", duracion_min="27", motivo_ruta="",
    direccion_entrega_geocodificada="VICUÑA MACKENNA 3451, San Joaquín [INE]", localidad_entrega="San Joaquín",
    region_entrega="Metropolitana", codigo_pais="CL", codigo_unidad="13129", codigo_contexto="13",
    proveedor_ruta="openrouteservice")


@pytest.fixture
def resolucion(monkeypatch):
    r = Resolucion({
        "HELSINSKI 5810 LA REINA SANTIAGO": _rechazo("La Reina"),
        "HELSINSKI 5810": _rechazo("La Reina"),
        "AV. VICUNA MACKENNA 3451 SAN JOAQUIN SAN JOAQUIN": ACEPTADA_SAN_JOAQUIN,
    })
    monkeypatch.setattr(de, "calcular_ruta_con_planta_conocida", r)
    return r


def test_retira_km_fuera_de_comuna_y_recupera_con_evidencia(raiz, resolucion):
    antes = _filas(raiz)
    ledger = (raiz / "operacion/actual/decisiones_aplicadas.json").read_bytes()
    r = revalidar_rutas_territoriales(raiz_atlas=raiz, archivos=["472096.jpeg", "475542.jpeg", "83277.jpg"])
    filas = _filas(raiz)
    assert {x["numero_guia"] for x in r["retiradas"]} == {"472096", "83277"}
    assert [x["numero_guia"] for x in r["recalculadas"]] == ["475542"]
    helsinski = filas["472096.jpeg"]
    assert (helsinski["distancia_km"], helsinski["estado_ruta"], helsinski["localidad_entrega"]) == (
        "", "REQUIERE_REVISION", "")
    assert helsinski["motivo_ruta"].startswith(MOTIVO_FUERA_DE_COMUNA_CONOCIDA)
    assert helsinski["estado_operacional"] == "OK"  # se preserva
    assert helsinski["despachar_a_crudo"] == antes["472096.jpeg"]["despachar_a_crudo"]
    vicuna = filas["475542.jpeg"]
    assert (vicuna["distancia_km"], vicuna["localidad_entrega"], vicuna["estado_ruta"]) == (
        "29.7878", "San Joaquín", "RUTA_CALCULADA")
    auditoria = json.loads(helsinski["metricas_procesamiento_json"])[CLAVE_AUDITORIA_TERRITORIAL][-1]
    assert auditoria["ruta_anterior"]["distancia_km"] == "14.5114" and auditoria["resultado"] == "retiradas"
    assert (raiz / "operacion/actual/decisiones_aplicadas.json").read_bytes() == ledger
    # La comuna del destino que Javier confirmó (83277) es la de control.
    assert ("HELSINSKI 5810", "LA REINA") in resolucion.llamadas


def test_abstenciones(raiz, resolucion):
    antes = _filas(raiz)
    r = revalidar_rutas_territoriales(raiz_atlas=raiz, archivos=["464715.jpeg", "sin_comuna.jpg", "no.jpg"])
    assert {a["archivo"]: a["motivo"] for a in r["abstenciones"]} == {
        "464715.jpeg": "PUBLICADA_EN_SU_COMUNA", "sin_comuna.jpg": "SIN_COMUNA_CONOCIDA",
        "no.jpg": "DOCUMENTO_NO_UNICO:0"}
    assert _filas(raiz) == antes and resolucion.llamadas == []


def test_resultado_no_concluyente_no_escribe(raiz, monkeypatch):
    monkeypatch.setattr(de, "calcular_ruta_con_planta_conocida", lambda **kw: SimpleNamespace(
        estado_ruta="REQUIERE_REVISION", distancia_km="", motivo_ruta="PROVEEDOR_NO_DISPONIBLE"))
    antes = _filas(raiz)
    r = revalidar_rutas_territoriales(raiz_atlas=raiz, archivos=["472096.jpeg"])
    assert r["abstenciones"] == [{"archivo": "472096.jpeg",
                                  "motivo": "SIN_RESULTADO_CONCLUYENTE:PROVEEDOR_NO_DISPONIBLE"}]
    assert _filas(raiz) == antes


def test_destino_humano_vigente_se_abstiene(raiz, resolucion):
    ruta = raiz / "operacion/actual/decisiones_aplicadas.json"
    ledger = json.loads(ruta.read_text(encoding="utf-8"))
    ledger["aplicaciones"].append({"decision_id": "D", "tipo": "DESTINO_OPERACIONAL_DOCUMENTO",
                                   "documento": {"archivo": "472096.jpeg", "numero_guia": "472096"},
                                   "destino_operacional": {"direccion": "HELSINSKI 5810", "comuna": "LA REINA"}})
    ruta.write_text(json.dumps(ledger), encoding="utf-8")
    r = revalidar_rutas_territoriales(raiz_atlas=raiz, archivos=["472096.jpeg"])
    assert r["abstenciones"] == [{"archivo": "472096.jpeg", "motivo": "DESTINO_HUMANO_VIGENTE"}]


def test_segunda_pasada_no_cambia_nada(raiz, resolucion):
    revalidar_rutas_territoriales(raiz_atlas=raiz, archivos=["472096.jpeg", "475542.jpeg"])
    antes = _filas(raiz)
    r = revalidar_rutas_territoriales(raiz_atlas=raiz, archivos=["472096.jpeg", "475542.jpeg"])
    assert r["retiradas"] == [] and r["recalculadas"] == [] and _filas(raiz) == antes


class Base:
    def __init__(self, cubiertas):
        self.cubiertas = set(cubiertas)

    def comuna_cubre_punto(self, *, comuna, latitud, longitud, radio_m):
        return comuna in self.cubiertas


def test_coordenada_de_destino_fuera_de_su_comuna(monkeypatch):
    monkeypatch.setattr(de, "_candidato_geocodificacion_desde_base_local", lambda *a, **k: None)
    destino = SimpleNamespace(direccion="HELSINSKI 5810", comuna="LA REINA", latitud=-33.375286, longitud=-70.674204)
    assert coordenada_de_destino_fuera_de_su_comuna(destino, Base({"Conchalí"})).endswith("(punto en Conchalí)")
    assert coordenada_de_destino_fuera_de_su_comuna(destino, Base({"La Reina"})) == ""
    assert coordenada_de_destino_fuera_de_su_comuna(SimpleNamespace(direccion="X", comuna="LA REINA",
                                                                    latitud=None, longitud=None), Base(())) == ""


def test_reconciliacion_exige_alcance_focal(raiz):
    from atlas_core.reconciliacion_estado_derivado import reconciliar_estado_derivado
    with pytest.raises(ValueError, match="revalidar_territorio_archivos"):
        reconciliar_estado_derivado(raiz_atlas=raiz, revalidar_territorio_archivos=["472096.jpeg"])
