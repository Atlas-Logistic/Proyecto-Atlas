"""Ciclo focal técnico; nunca accede a la operación real ni a la red."""
from __future__ import annotations

import csv
import json
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from atlas_core import mantenimiento_pendientes_tecnicos as mantenimiento
from atlas_core.politica_pendientes_tecnicos import conocimiento_para_guia, elegibilidad
from atlas_core.procesamiento_masivo import COLUMNAS
from atlas_core.reconciliacion_estado_derivado import _huella_ruta
from atlas_core.revalidacion_reactiva_tecnica import revalidar_tras_cambio_catalogo
from atlas_core.catalogo_destinos import Destino, normalizar_nombre_destino
from atlas_core.catalogo_plantas import CatalogoPlantas, EstadoCalidad
from atlas_core.rutas.destino_entrega import (
    FUENTE_COORDENADA_CANONICA_CONFIRMADA, calcular_ruta_con_planta_conocida,
)
from atlas_core.rutas.proveedor import ProveedorRutasSimulado

AHORA = datetime(2026, 9, 25, 14, 0, tzinfo=timezone.utc)
RELOJ = lambda: AHORA


def _escribir_csv(ruta: Path, filas: list[dict]) -> None:
    with ruta.open("w", encoding="utf-8-sig", newline="") as f:
        escritor = csv.DictWriter(f, fieldnames=COLUMNAS, delimiter=";", extrasaction="ignore")
        escritor.writeheader()
        escritor.writerows(filas)


def _entorno(tmp_path, motivo="COORDENADA_NO_CONFIRMADA(5)", *, minutos=31, intentos=1):
    actual = tmp_path / "operacion" / "actual"
    actual.mkdir(parents=True)
    catalogos = tmp_path / "catalogos_privados"
    catalogos.mkdir()
    (catalogos / "destinos_maestros.json").write_text(json.dumps({"destinos": [{
        "destino_id": "d1", "direccion": "LAS HORTENSIAS 3800", "aliases": [],
        "latitud": None, "longitud": None, "comuna": "",
    }]}), encoding="utf-8")
    (catalogos / "obras_destinos.json").write_text(json.dumps({"obras": [], "relaciones": []}), encoding="utf-8")
    fila = {c: "" for c in COLUMNAS}
    fila.update(numero_guia="474597", numero_transporte="0000360122", archivo="guia.jpg",
                planta_origen_id="planta-1", despachar_a_crudo="LAS HORTENSIAS 3800",
                cliente="SALOMON SACK SA", obra_destino="OBRA LAS HORTENSIAS",
                indicador_revision="OK", estado_documental="OK", estado_operacional="REQUIERE_REVISION",
                estado_ruta="REQUIERE_REVISION", motivo_ruta=motivo)
    resuelta = {c: "" for c in COLUMNAS}
    resuelta.update(numero_guia="474598", numero_transporte="0000360122", estado_ruta="RUTA_CALCULADA",
                    estado_operacional="OK", indicador_revision="OK")
    dataset = actual / "analisis_completo_guias.csv"
    _escribir_csv(dataset, [fila, resuelta])
    huella = conocimiento_para_guia(
        fila, catalogos=catalogos, decisiones_aplicadas=actual / "decisiones_aplicadas.json",
        version_reglas=mantenimiento.RULESET_VERSION,
        versiones_capacidades=mantenimiento.versiones_actuales(),
    )
    anterior = AHORA - timedelta(minutes=minutos)
    registro = {"numero_guia": "474597", "huella_datos": _huella_ruta(fila),
                "huella_conocimiento": huella, "motivo_actual": motivo,
                "intentos_misma_evidencia": intentos, "ultimo_intento": anterior.isoformat(),
                "historial_resultados": []}
    (actual / "pendientes_tecnicos.json").write_text(
        json.dumps({"schema_version": 1, "pendientes": [registro]}), encoding="utf-8")
    return tmp_path, dataset


def _parches_sin_red(monkeypatch, *, resolver=False):
    llamadas = {"interno": [], "externo": [], "reporte": 0}

    def interno(**kwargs):
        llamadas["interno"].append(kwargs["guias_objetivo"])
        if resolver:
            ruta = Path(kwargs["ruta_dataset"])
            with ruta.open(encoding="utf-8-sig", newline="") as f:
                filas = list(csv.DictReader(f, delimiter=";"))
            for fila in filas:
                if fila["numero_guia"] == "474597":
                    fila.update(estado_ruta="RUTA_CALCULADA", motivo_ruta="", estado_operacional="OK")
            _escribir_csv(ruta, filas)
        return {"guias_actualizadas": ["474597"] if resolver else []}

    def externo(**kwargs):
        llamadas["externo"].append(kwargs["guias_objetivo"])
        return {"guias_actualizadas": []}

    def reporte(_dataset, salida, **kwargs):
        llamadas["reporte"] += 1
        salida.mkdir(parents=True)
        (salida / "viajes.csv").write_text("estado\nOK\n", encoding="utf-8")
        return {"totales": {"viajes": 1}}

    monkeypatch.setattr(mantenimiento, "revalidar_ruta_con_destino_confirmado_en_catalogo_sin_ocr", interno)
    monkeypatch.setattr(mantenimiento, "revalidar_ruta_sin_destino_calculado_sin_ocr", externo)
    monkeypatch.setattr(mantenimiento, "reconciliar_decisiones_destino_no_resuelto", lambda **kw: {"decisiones_publicadas": 0})
    monkeypatch.setattr(mantenimiento, "generar_reporte_viajes", reporte)
    return llamadas


def _pendiente(raiz):
    return json.loads((raiz / "operacion" / "actual" / "pendientes_tecnicos.json").read_text(encoding="utf-8"))["pendientes"]


def test_agotable_equivalente_474597_tiene_oportunidad_a_30_min_sin_repetir_red(tmp_path, monkeypatch):
    raiz, dataset = _entorno(tmp_path)
    original_resuelta = next(r for r in csv.DictReader(dataset.open(encoding="utf-8-sig"), delimiter=";") if r["numero_guia"] == "474598")
    llamadas = _parches_sin_red(monkeypatch)
    resultado = mantenimiento.mantener_pendientes_tecnicos(raiz_atlas=raiz, reloj=RELOJ)
    assert resultado["ejecutado"] is True
    assert resultado["elegibles"] == [{"numero_guia": "474597", "causa": "COOLDOWN_VENCIDO", "clase": "AGOTABLE"}]
    assert llamadas["interno"] == [{"474597"}]
    assert llamadas["externo"] == []
    pendiente = _pendiente(raiz)[0]
    assert pendiente["ultimo_intento"] == AHORA.isoformat()
    assert pendiente["proxima_oportunidad"] == (AHORA + timedelta(minutes=30)).isoformat()
    assert pendiente["intentos_misma_evidencia"] == 2
    resuelta = next(r for r in csv.DictReader(dataset.open(encoding="utf-8-sig"), delimiter=";") if r["numero_guia"] == "474598")
    assert resuelta == original_resuelta


def test_transitorio_vence_a_30_min_y_puede_reconsultar_proveedor(tmp_path, monkeypatch):
    raiz, _ = _entorno(tmp_path, "GEOCODIFICACION_SIN_CONEXION")
    llamadas = _parches_sin_red(monkeypatch)
    mantenimiento.mantener_pendientes_tecnicos(raiz_atlas=raiz, reloj=RELOJ)
    assert llamadas["externo"] == [{"474597"}]
    assert _pendiente(raiz)[0]["proxima_oportunidad"] == (AHORA + timedelta(minutes=30)).isoformat()


def test_determinista_no_se_consulta_por_reloj(tmp_path, monkeypatch):
    raiz, _ = _entorno(tmp_path, "GEOCODIFICACION_CONTRADICE_COMUNA_DOCUMENTAL", minutos=1440)
    llamadas = _parches_sin_red(monkeypatch)
    resultado = mantenimiento.mantener_pendientes_tecnicos(raiz_atlas=raiz, reloj=RELOJ)
    assert resultado["elegibles"] == []
    assert llamadas["interno"] == llamadas["externo"] == []


def test_cambio_catalogo_focal_resuelve_antes_de_geocodificar(tmp_path, monkeypatch):
    raiz, _ = _entorno(tmp_path, "GEOCODIFICACION_CONTRADICE_COMUNA_DOCUMENTAL")
    catalogo = raiz / "catalogos_privados" / "destinos_maestros.json"
    contenido = json.loads(catalogo.read_text(encoding="utf-8"))
    contenido["destinos"][0]["latitud"] = -33.5
    contenido["destinos"][0]["longitud"] = -70.6
    catalogo.write_text(json.dumps(contenido), encoding="utf-8")
    llamadas = _parches_sin_red(monkeypatch, resolver=True)
    resultado = mantenimiento.mantener_pendientes_tecnicos(
        raiz_atlas=raiz, reloj=RELOJ, solo_cambios=True,
    )
    assert resultado["resueltas"] == ["474597"]
    assert llamadas["interno"] == [{"474597"}]
    assert llamadas["externo"] == []
    assert _pendiente(raiz) == []


def test_catalogo_ajeno_no_despierta_guia(tmp_path):
    raiz, _ = _entorno(tmp_path)
    catalogo = raiz / "catalogos_privados" / "destinos_maestros.json"
    contenido = json.loads(catalogo.read_text(encoding="utf-8"))
    contenido["destinos"].append({"destino_id": "otro", "direccion": "OTRA 1", "aliases": []})
    catalogo.write_text(json.dumps(contenido), encoding="utf-8")
    assert mantenimiento.mantener_pendientes_tecnicos(
        raiz_atlas=raiz, reloj=RELOJ, solo_plan=True, solo_cambios=True,
    )["elegibles"] == []


def test_sin_evidencia_nueva_ni_vencimiento_no_hay_llamadas(tmp_path, monkeypatch):
    raiz, _ = _entorno(tmp_path, minutos=10)
    llamadas = _parches_sin_red(monkeypatch)
    mantenimiento.mantener_pendientes_tecnicos(raiz_atlas=raiz, reloj=RELOJ)
    assert llamadas["interno"] == llamadas["externo"] == []


def test_dos_ejecuciones_concurrentes_no_duplican_intento(tmp_path, monkeypatch):
    raiz, _ = _entorno(tmp_path)
    entro = threading.Event()
    liberar = threading.Event()
    llamadas = _parches_sin_red(monkeypatch)
    original = mantenimiento.revalidar_ruta_con_destino_confirmado_en_catalogo_sin_ocr

    def interno_lento(**kwargs):
        entro.set()
        assert liberar.wait(5)
        return original(**kwargs)

    monkeypatch.setattr(mantenimiento, "revalidar_ruta_con_destino_confirmado_en_catalogo_sin_ocr", interno_lento)
    resultados = []
    hilo = threading.Thread(target=lambda: resultados.append(
        mantenimiento.mantener_pendientes_tecnicos(raiz_atlas=raiz, reloj=RELOJ)))
    hilo.start()
    assert entro.wait(5)
    segundo = mantenimiento.mantener_pendientes_tecnicos(raiz_atlas=raiz, reloj=RELOJ)
    liberar.set()
    hilo.join(5)
    assert segundo["motivo"] == "OTRA_SESION_ACTIVA"
    assert len(llamadas["interno"]) == 1
    assert resultados[0]["ejecutado"] is True


def test_reinicio_relee_vencimiento_persistido_y_resuelta_desaparece(tmp_path, monkeypatch):
    raiz, _ = _entorno(tmp_path)
    llamadas = _parches_sin_red(monkeypatch)
    mantenimiento.mantener_pendientes_tecnicos(raiz_atlas=raiz, reloj=RELOJ)
    assert mantenimiento.mantener_pendientes_tecnicos(
        raiz_atlas=raiz, reloj=lambda: AHORA + timedelta(minutes=10), solo_plan=True,
    )["elegibles"] == []
    assert mantenimiento.mantener_pendientes_tecnicos(
        raiz_atlas=raiz, reloj=lambda: AHORA + timedelta(minutes=31), solo_plan=True,
    )["elegibles"][0]["numero_guia"] == "474597"
    assert len(llamadas["interno"]) == 1


def test_notificacion_de_catalogo_limita_alcance(tmp_path, monkeypatch):
    raiz, _ = _entorno(tmp_path, minutos=10)
    visto = []
    monkeypatch.setattr(mantenimiento, "mantener_pendientes_tecnicos", lambda **kw: visto.append(kw) or {"ejecutado": True})
    destino = SimpleNamespace(destino_id="d1", direccion="LAS HORTENSIAS 3800", aliases=())
    resultado = revalidar_tras_cambio_catalogo(
        raiz / "catalogos_privados" / "destinos_maestros.json", destino=destino,
    )
    assert resultado["ejecutado"] is True
    assert visto[0]["guias_forzadas"] == {"474597"}
    assert visto[0]["solo_cambios"] is True


def test_reintento_con_planta_conocida_usa_alias_canonico_antes_de_red(tmp_path):
    plantas = CatalogoPlantas(tmp_path / "plantas.json")
    planta = plantas.crear(
        nombre="AZA COLINA", pais="CHILE", fuente="PRUEBA",
        direccion="CAMINO", comuna="COLINA", region="RM",
        latitud=-33.2, longitud=-70.7, estado_calidad=EstadoCalidad.CONFIRMADA,
    )
    destino = Destino(
        destino_id="d1", cliente_id="", nombre_destino="GRAN VIA",
        nombre_normalizado=normalizar_nombre_destino("GRAN VIA"), codigo_destino="",
        direccion="URUGUAY 15", comuna="LA CISTERNA", region="RM", pais="CHILE",
        latitud=-33.529673, longitud=-70.660891,
        aliases=("URUGUAY 15 SANTIAGO LA CISTERNA",),
        estado_calidad="CONFIRMADO", estado_vigencia="ACTIVO",
        fuente=FUENTE_COORDENADA_CANONICA_CONFIRMADA, observacion="PRUEBA",
        fecha_creacion=AHORA.isoformat(), fecha_modificacion=AHORA.isoformat(),
    )
    proveedor = ProveedorRutasSimulado()
    resultado = calcular_ruta_con_planta_conocida(
        planta=planta, despachar_a_crudo="URUGUAY 15 SANTIAGO LA CISTERNA",
        proveedor_rutas=proveedor, destinos_confirmados=[destino],
    )
    assert resultado.estado_ruta == "RUTA_CALCULADA"
    assert resultado.metodo_confirmacion_destino == "COORDENADA_CANONICA_CATALOGO"
    assert proveedor.llamadas_geocodificacion == 0
    assert proveedor.llamadas_ruta == 1
