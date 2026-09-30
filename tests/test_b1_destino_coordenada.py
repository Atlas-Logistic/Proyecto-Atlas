"""B1 operador -- coordenada canónica de un destino EXISTENTE confirmada por
un humano ("la coordenada del destino X es LAT, LON"). Caso de validación:
CAM. EL NOVICIADO LAMPA LAMPA (guías 464746/473149/473324/474064). Se aplica
por CatalogoDestinos.confirmar_coordenada_canonica tras confirmación; el
ruteo reutiliza la coordenada por coincidencia documental exacta. Copias
sintéticas y proveedor simulado; nunca G: ni red."""
from __future__ import annotations

import hashlib
import json

import pytest

from atlas_core.acciones_operacionales import CapaAccionesOperacionales
from atlas_core.b1_operador import OperadorB1, interpretar_determinista
from atlas_core.catalogo_destinos import CatalogoDestinos
from atlas_core.rutas.destino_entrega import FUENTE_COORDENADA_CANONICA_CONFIRMADA
from atlas_core.rutas.proveedor import ProveedorRutasSimulado
from tests.test_destino_no_resuelto_r6 import _cliente_dict, _entorno, _fila_csv, _leer_csv

NOVICIADO = "CAM. EL NOVICIADO LAMPA LAMPA"
GUIAS = ("464746", "473149", "473324", "474064")
LAT, LON = -33.35318, -70.84763
ORDEN = f"La coordenada del destino {NOVICIADO} es {LAT}, {LON}"


def _destino(destino_id, direccion, *, estado="PENDIENTE"):
    return {"destino_id": destino_id, "cliente_id": "", "nombre_destino": direccion,
            "nombre_normalizado": direccion.replace(".", ""), "codigo_destino": "", "direccion": direccion,
            "comuna": "", "region": "", "pais": "CHILE", "latitud": None, "longitud": None, "aliases": [],
            "estado_calidad": estado, "estado_vigencia": "ACTIVO", "fuente": "DECISION_HUMANA_R3_4:x",
            "observacion": "", "fecha_creacion": "2026-08-18T12:51:40+00:00",
            "fecha_modificacion": "2026-08-18T12:51:40+00:00"}


def _fila(guia, destino=NOVICIADO):
    return _fila_csv(archivo=f"{guia}.jpeg", numero_guia=guia, numero_transporte=f"0000{guia}",
                     cliente="EASY RETAIL SA", obra_destino="EMPRESA CONSTRUCTORA MENA Y", indicador_revision="OK",
                     despachar_a_crudo=destino, estado_ruta="REQUIERE_REVISION",
                     motivo_ruta="GEOCODIFICACION_DEMASIADO_GENERICA", estado_operacional="REQUIERE_REVISION")


@pytest.fixture
def entorno(tmp_path):
    filas = [_fila(g) for g in GUIAS] + [_fila("499999", NOVICIADO + " 2")]
    entorno = _entorno(tmp_path, filas_csv=filas, clientes=[_cliente_dict()])
    (entorno["catalogos"] / "destinos_maestros.json").write_text(json.dumps({"version_formato": 1, "destinos": [
        _destino("destino-noviciado", NOVICIADO),
        _destino("destino-vecino", NOVICIADO + " 2"),
        _destino("sur-a", "EDIFICIO SUR 1", estado="CONFIRMADO"),
    ]}), encoding="utf-8")
    (entorno["actual"] / "decisiones_aplicadas.json").write_text(
        json.dumps({"schema_version": 1, "aplicaciones": []}), encoding="utf-8")
    return entorno


@pytest.fixture
def b1(entorno):
    proveedor = ProveedorRutasSimulado()
    proveedor.destinos_ruteados = []
    calcular = proveedor.calcular_ruta
    proveedor.calcular_ruta = lambda o, d, *a: proveedor.destinos_ruteados.append((d.latitud, d.longitud)) or calcular(o, d, *a)
    capa =CapaAccionesOperacionales(entorno["raiz"], proveedor_rutas=proveedor)
    operador = OperadorB1(entorno["raiz"], capa=capa)
    operador.proveedor_rutas = proveedor
    revalidar = capa._revalidar_guias
    operador.revalidadas = []
    capa._revalidar_guias = lambda guias: operador.revalidadas.append(set(guias)) or revalidar(guias)
    return operador


def _sha(ruta):
    return hashlib.sha256(ruta.read_bytes()).hexdigest() if ruta.exists() else None


def _huellas(entorno):
    return {n: _sha(p) for n, p in {"dataset": entorno["dataset"],
                                     "destinos": entorno["catalogos"] / "destinos_maestros.json",
                                     "ledger": entorno["actual"] / "decisiones_aplicadas.json"}.items()}


def _catalogo(entorno):
    return {d.destino_id: d for d in CatalogoDestinos(entorno["catalogos"] / "destinos_maestros.json").listar()}


@pytest.mark.parametrize("texto", [
    ORDEN,
    f"Las coordenadas de {NOVICIADO} son {LAT} {LON}",
    f"El destino {NOVICIADO} está en {LAT}, {LON}",
    f"Confirma la coordenada {LAT}, {LON} para el destino {NOVICIADO}",
    f"Confirma la coordenada del destino {NOVICIADO}: {LAT}, {LON}",
    f"Fija las coordenadas de {NOVICIADO} en {LAT}, {LON}",
])
def test_formas_de_la_instruccion(texto):
    intencion = interpretar_determinista(texto)
    assert intencion is not None and intencion.accion == "DESTINO_CONFIRMAR_COORDENADA"
    assert intencion.parametros == {"latitud": LAT, "longitud": LON}
    assert intencion.menciones == {"destino": NOVICIADO}


def test_no_captura_preguntas_ni_otras_ordenes():
    assert interpretar_determinista(f"¿Cuál es la coordenada del destino {NOVICIADO}?") is None
    assert interpretar_determinista("El destino de la guía 472037 es Avenida Apoquindo 1234").accion == "DECISION_APLICAR"


def test_noviciado_preview_confirmacion_ruteo_idempotencia(entorno, b1):
    antes = _huellas(entorno)
    r = b1.atender("c", ORDEN)
    assert r["estado"] == "PREVIEW_PENDIENTE", r
    p = r["preview"]
    assert p["accion"] == "DESTINO_CONFIRMAR_COORDENADA" and p["entidad"]["id"] == "destino-noviciado"
    assert p["valor_propuesto"] == {"latitud": LAT, "longitud": LON, "estado_calidad": "CONFIRMADO",
                                    "fuente": FUENTE_COORDENADA_CANONICA_CONFIRMADA}
    assert p["afectados"]["guias"] == sorted(GUIAS)  # coincidencia exacta: el vecino "… 2" no
    # el mensaje muestra sólo destino, coordenada y consecuencias operacionales
    assert r["mensaje"].startswith(f"Confirmar la coordenada del destino {NOVICIADO!r}: {LAT}, {LON}.")
    for texto in ("sin geocodificar", "4 guía(s)", ", ".join(GUIAS), "PENDIENTE a CONFIRMADO", "¿Confirmas?"):
        assert texto in r["mensaje"]
    assert "destino-noviciado" not in r["mensaje"] and "fuente" not in r["mensaje"]
    assert _huellas(entorno) == antes and b1.revalidadas == []  # preview sin escritura

    e = b1.atender("c", "sí")
    assert e["estado"] == "EJECUTADA", e
    destinos = _catalogo(entorno)
    noviciado = destinos["destino-noviciado"]
    assert (noviciado.latitud, noviciado.longitud) == (LAT, LON)
    assert noviciado.estado_calidad == "CONFIRMADO" and noviciado.fuente == FUENTE_COORDENADA_CANONICA_CONFIRMADA
    assert "actor=B1/JAVIER" in noviciado.observacion
    assert destinos["destino-vecino"].latitud is None and destinos["destino-vecino"].estado_calidad == "PENDIENTE"
    assert len(destinos) == 3  # ningún destino nuevo

    # revalidación focal: sólo las 4 guías, y el ruteo reutiliza la coordenada canónica
    assert b1.revalidadas == [set(GUIAS)]
    filas = {f["numero_guia"]: f for f in _leer_csv(entorno["dataset"])}
    for guia in GUIAS:
        assert filas[guia]["estado_ruta"] == "RUTA_CALCULADA", filas[guia]
        assert filas[guia]["distancia_km"] and filas[guia]["direccion_entrega"] == NOVICIADO
        assert filas[guia]["despachar_a_crudo"] == NOVICIADO  # el documento no se edita
    assert filas["499999"]["estado_ruta"] == "REQUIERE_REVISION"
    assert b1.proveedor_rutas.llamadas_geocodificacion == 0  # sin geocoder: coordenada canónica
    assert set(b1.proveedor_rutas.destinos_ruteados) == {(LAT, LON)}
    assert len(b1.proveedor_rutas.destinos_ruteados) == len(GUIAS)

    auditoria = b1.capa.auditoria()
    assert len(auditoria) == 1 and auditoria[0]["confirmado_por"] == "JAVIER"
    assert auditoria[0]["antes"]["estado_calidad"] == "PENDIENTE" and auditoria[0]["antes"]["latitud"] is None

    # idempotencia: otro "sí", el mismo token o la misma orden no reescriben
    catalogo = _sha(entorno["catalogos"] / "destinos_maestros.json")
    assert b1.atender("c", "sí")["estado"] == "SIN_PREVIEW_PENDIENTE"
    assert b1.capa.ejecutar(auditoria[0]["token"], actor="B1", origen="B1", confirmado_por="JAVIER")["idempotente"]
    assert b1.atender("c", ORDEN)["estado"] == "SIN_CAMBIOS"
    assert _sha(entorno["catalogos"] / "destinos_maestros.json") == catalogo
    assert len(b1.capa.auditoria()) == 1 and len(b1.revalidadas) == 1


def test_destino_inexistente_o_ambiguo_se_abstiene(entorno, b1):
    antes = _huellas(entorno)
    r = b1.atender("c", f"La coordenada del destino CAM. EL NOVICIADO es {LAT}, {LON}")
    assert r["estado"] == "ACLARACION_REQUERIDA" and "No creo destinos" in r["mensaje"]
    assert {c["destino_id"] for c in r["candidatos"]} == {"destino-noviciado", "destino-vecino"}
    # dos destinos activos con el mismo texto -> ambiguo
    contenido = json.loads((entorno["catalogos"] / "destinos_maestros.json").read_text(encoding="utf-8"))
    duplicado = {**_destino("sur-b", "EDIFICIO SUR 1B"), "aliases": ["EDIFICIO SUR 1"]}
    contenido["destinos"].append(duplicado)
    (entorno["catalogos"] / "destinos_maestros.json").write_text(json.dumps(contenido), encoding="utf-8")
    antes = _huellas(entorno)
    r = b1.atender("c", f"El destino Edificio Sur 1 está en {LAT}, {LON}")
    assert r["estado"] == "ACLARACION_REQUERIDA" and "más de un destino" in r["mensaje"]
    assert b1.pendiente("c") is None and b1.atender("c", "sí")["estado"] == "SIN_PREVIEW_PENDIENTE"
    assert _huellas(entorno) == antes


def test_coordenada_fuera_de_chile_se_rechaza(entorno, b1):
    antes = _huellas(entorno)
    r = b1.atender("c", f"La coordenada del destino {NOVICIADO} es 33.35318, 70.84763")
    assert r["estado"] == "RECHAZADA" and r["codigo"] == "PARAMETRO_INVALIDO"
    assert b1.pendiente("c") is None and _huellas(entorno) == antes
