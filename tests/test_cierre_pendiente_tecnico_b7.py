"""Bloque CIERRE OPERACIONAL DE PENDIENTE_TECNICO / REVISIÓN HUMANA
(RULESET_VERSION 13 -> 14).

Casos reales de referencia:

- 0000353055 / guía 464715: `MULTIPLES_UBICACIONES_DISPERSAS`. Hoy
  quedaba INCOMPLETO_TECNICO y Revisión de Atlas NO generaba tarjeta,
  porque `reconciliar_decisiones_destino_no_resuelto` sólo corría tras
  una decisión / envío Mobile, nunca en la carga/drop de Desktop. Ahora
  se conecta a `reconciliar_estado_derivado`: un motivo de destino que
  ya es callejón sin salida (`MOTIVOS_DESTINO_NO_RESUELTO`) genera su
  tarjeta `DESTINO_NO_RESUELTO` accionable de inmediato, sin esperar 3
  reintentos, y refrescar/reconciliar de nuevo NUNCA la duplica.

- 0000353062 / guía 464717: cliente == obra_destino == "AMERICAN SCREW
  CHILE SPA", ruta ya calculada. Quedaba bloqueado por
  `OBRA_DESTINO_SIN_CORROBORAR`. `revalidar_obra_destino_sin_ocr` (que
  ya retira ese motivo cuando la obra ES la sede del propio cliente)
  también se conecta aquí -- salvo que exista una obra homónima real de
  OTRO cliente en el catálogo, en cuyo caso la corroboración se conserva.
"""
from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path

from atlas_core.almacenamiento_portable import escribir_estado_operacion
from atlas_core.catalogo_plantas import CatalogoPlantas, EstadoCalidad
from atlas_core.decisiones_pendientes import MOTIVOS_DESTINO_NO_RESUELTO
from atlas_core.procesamiento_masivo import COLUMNAS
from atlas_core.reporte_viajes import _sha256_archivo
from atlas_core.reconciliacion_estado_derivado import RULESET_VERSION, reconciliar_estado_derivado
from atlas_core.revalidacion_documental import (
    reconciliar_decisiones_destino_no_resuelto,
    revalidar_obra_destino_sin_ocr,
)

RELOJ = lambda: datetime(2026, 9, 7, 18, 0, tzinfo=timezone.utc)
COORD_AZA_COLINA = (-70.665977, -33.137558)


def _fila_base(numero_guia: str, transporte: str, planta_id: str) -> dict[str, str]:
    fila = {c: "" for c in COLUMNAS}
    fila.update({
        "archivo": f"{numero_guia}.jpeg", "estado_procesamiento": "OK",
        "numero_guia": numero_guia, "numero_transporte": transporte, "fecha": "27-08-2026",
        "chofer": "CHOFER PRUEBA", "patente_tracto": "BPHR67",
        "planta_origen_id": planta_id, "planta_origen_nombre": "AZA COLINA",
        "origen_determinado_por": "CONFIRMACION_HUMANA", "evidencia_origen": "DECISION_HUMANA:x",
    })
    return fila


def _escribir_dataset(dataset: Path, filas: list[dict[str, str]]) -> None:
    with dataset.open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader()
        escritor.writerows(filas)


def _leer_dataset(dataset: Path) -> dict[str, dict[str, str]]:
    with dataset.open(encoding="utf-8-sig", newline="") as archivo:
        return {f["numero_guia"]: f for f in csv.DictReader(archivo, delimiter=";")}


def _cliente_dict(cliente_id: str, razon_social: str, rut: str = "76086428-5") -> dict[str, object]:
    return {
        "cliente_id": cliente_id, "razon_social": razon_social,
        "nombre_normalizado": razon_social, "nombre_comercial": "", "rut": rut,
        "aliases": [], "estado_calidad": "CONFIRMADO", "estado_vigencia": "ACTIVO", "fuente": "TEST",
        "observacion": "", "fecha_creacion": "2026-01-01T00:00:00+00:00",
        "fecha_modificacion": "2026-01-01T00:00:00+00:00",
    }


def _obra_dict(obra_id: str, cliente_id: str, nombre: str) -> dict[str, object]:
    return {
        "obra_id": obra_id, "cliente_id": cliente_id, "nombre_canonico": nombre,
        "nombre_normalizado": nombre, "aliases_documentales": [],
        "estado": "OBSERVADA", "estado_vigencia": "ACTIVO", "evidencias": [],
        "fecha_creacion": "2026-01-01T00:00:00+00:00", "fecha_modificacion": "2026-01-01T00:00:00+00:00",
    }


def _entorno(tmp_path: Path, *, filas, clientes=None, obras=None, version_previa=None) -> tuple[Path, Path]:
    raiz = tmp_path / "Atlas"
    catalogos = raiz / "catalogos_privados"
    actual = raiz / "operacion" / "actual"
    catalogos.mkdir(parents=True)
    actual.mkdir(parents=True)
    for nombre, contenido in {
        "clientes.json": {"version_formato": 1, "clientes": clientes or []},
        "empresas.json": {}, "vehiculos.json": {"version": 1, "vehiculos": []},
        "obras_destinos.json": {"version_formato": 1, "obras": obras or [], "relaciones": []},
        "destinos_maestros.json": {"version_formato": 1, "destinos": []},
    }.items():
        (catalogos / nombre).write_text(json.dumps(contenido), encoding="utf-8")

    plantas = CatalogoPlantas(catalogos / "plantas.json")
    planta = plantas.crear(
        nombre="AZA COLINA", pais="CHILE", fuente="TEST",
        direccion="AV EJEMPLO 1", comuna="COLINA", region="RM",
        latitud=COORD_AZA_COLINA[1], longitud=COORD_AZA_COLINA[0],
        estado_calidad=EstadoCalidad.CONFIRMADA,
    )
    for fila in filas:
        if fila.get("planta_origen_id") == "planta-colina":
            fila["planta_origen_id"] = planta.planta_id

    dataset = actual / "analisis_completo_guias.csv"
    _escribir_dataset(dataset, filas)
    decisiones = actual / "decisiones_pendientes.json"
    decisiones.write_text(json.dumps({"schema_version": 1, "decisiones": []}), encoding="utf-8")

    reporte_previo = raiz / "reportes" / "previo"
    reporte_previo.mkdir(parents=True)
    escribir_estado_operacion(
        reporte_vigente=reporte_previo, dataset_operacional=dataset,
        decisiones_pendientes=decisiones, raiz=raiz, reloj=RELOJ,
        version_estado_derivado=RULESET_VERSION - 1 if version_previa is None else version_previa,
        dataset_sha256=_sha256_archivo(dataset),
    )
    return raiz, dataset


def _decisiones_destino(raiz: Path, numero_guia: str) -> list[dict]:
    bandeja = json.loads((raiz / "operacion" / "actual" / "decisiones_pendientes.json").read_text(encoding="utf-8"))
    return [
        d for d in bandeja.get("decisiones", [])
        if d.get("tipo") == "DESTINO_NO_RESUELTO"
        and str((d.get("documento") or {}).get("numero_guia", "")) == numero_guia
    ]


# ---------------------------------------------------------------------------
# OBJETIVO 1 -- pendientes técnicos accionables
# ---------------------------------------------------------------------------

def test_multiples_ubicaciones_dispersas_genera_decision_accionable_desde_reconciliacion(tmp_path):
    """464715-style: el drop/carga (reconciliar_estado_derivado) genera la
    tarjeta DESTINO_NO_RESUELTO de inmediato, sin esperar 3 reintentos."""
    fila = _fila_base("464715", "0000353055", "planta-colina")
    fila.update({
        "cliente": "CLIENTE PRUEBA SPA", "obra_destino": "OBRA PRUEBA",
        "despachar_a_crudo": "CALLE INEXISTENTE 123", "direccion_entrega": "CALLE INEXISTENTE 123",
        "estado_entrega": "REQUIERE_REVISION",
        "estado_ruta": "REQUIERE_REVISION", "motivo_ruta": "MULTIPLES_UBICACIONES_DISPERSAS(5)",
        "indicador_revision": "REVISAR",
    })
    raiz, _ = _entorno(tmp_path, filas=[fila])

    resultado = reconciliar_estado_derivado(raiz_atlas=raiz, reloj=RELOJ)
    assert resultado["reconciliado"] is True

    decisiones = _decisiones_destino(raiz, "464715")
    assert len(decisiones) == 1, "debe existir exactamente una tarjeta DESTINO_NO_RESUELTO"
    decision = decisiones[0]
    assert decision["estado"] == "PENDIENTE"
    # El motivo puede afinarse durante la reconciliación (p. ej. de
    # DISPERSAS a DEMASIADO_GENERICA para el mismo texto sin salida) --
    # lo que importa es que siga siendo un callejón sin salida accionable.
    assert set(decision["motivos"]) <= MOTIVOS_DESTINO_NO_RESUELTO
    assert "REGISTRAR_DIRECCION" in decision["acciones_permitidas"]
    assert resultado["decisiones_destino_no_resuelto_publicadas"] >= 1


def test_refrescar_reconciliar_no_duplica_la_decision(tmp_path):
    """Idempotencia: reconciliar de nuevo -- por cualquier vía -- nunca
    crea una segunda tarjeta para el mismo callejón sin salida."""
    fila = _fila_base("464715", "0000353055", "planta-colina")
    fila.update({
        "cliente": "CLIENTE PRUEBA SPA", "obra_destino": "OBRA PRUEBA",
        "despachar_a_crudo": "CALLE INEXISTENTE 123", "direccion_entrega": "CALLE INEXISTENTE 123",
        "estado_ruta": "REQUIERE_REVISION", "motivo_ruta": "MULTIPLES_UBICACIONES_DISPERSAS(5)",
        "indicador_revision": "REVISAR",
    })
    raiz, _ = _entorno(tmp_path, filas=[fila])

    reconciliar_estado_derivado(raiz_atlas=raiz, reloj=RELOJ)
    assert len(_decisiones_destino(raiz, "464715")) == 1

    # refrescos repetidos: la reconciliación completa hace no-op (versión
    # vigente) y la detección directa deduplica por decision_id.
    for _ in range(3):
        reconciliar_estado_derivado(raiz_atlas=raiz, reloj=RELOJ)
        reconciliar_decisiones_destino_no_resuelto(raiz_atlas=raiz, reloj=RELOJ)
    assert len(_decisiones_destino(raiz, "464715")) == 1


# ---------------------------------------------------------------------------
# OBJETIVO 3 -- entrega a sede del propio cliente
# ---------------------------------------------------------------------------

def _fila_obra_es_cliente(numero_guia: str) -> dict[str, str]:
    fila = _fila_base(numero_guia, "0000353062", "planta-colina")
    fila.update({
        "cliente": "AMERICAN SCREW CHILE SPA", "obra_destino": "AMERICAN SCREW CHILE SPA",
        "despachar_a_crudo": "PANAMERICANA NORTE 5900 QUILICURA",
        "direccion_entrega": "PANAMERICANA NORTE 5900 QUILICURA",
        "localidad_entrega": "Quilicura", "region_entrega": "Metropolitana",
        "estado_entrega": "CONFIRMADO",
        "estado_ruta": "RUTA_CALCULADA", "motivo_ruta": "",
        "distancia_km": "35.3", "duracion_min": "49.0", "proveedor_ruta": "openrouteservice",
        "motivos_revision_documento": "OBRA_DESTINO_SIN_CORROBORAR",
        "indicador_revision": "REVISAR",
    })
    return fila


def test_obra_es_la_sede_del_propio_cliente_retira_obra_destino_sin_corroborar(tmp_path):
    """464717: cliente == obra, ruta resuelta, sin obra distinta real ->
    el motivo se retira en la reconciliación de la carga."""
    raiz, dataset = _entorno(
        tmp_path, filas=[_fila_obra_es_cliente("464717")],
        clientes=[_cliente_dict("cli-amscrew", "AMERICAN SCREW CHILE SPA")],
    )

    reconciliar_estado_derivado(raiz_atlas=raiz, reloj=RELOJ)

    fila = _leer_dataset(dataset)["464717"]
    assert "OBRA_DESTINO_SIN_CORROBORAR" not in fila["motivos_revision_documento"]


def test_obra_homonima_real_de_otro_cliente_conserva_la_corroboracion(tmp_path):
    """Contraejemplo: existe en catálogo una obra ACTIVA con el mismo
    nombre que pertenece a OTRO cliente -- NO es 'el mismo hecho dos
    veces', la revisión se conserva."""
    raiz, dataset = _entorno(
        tmp_path, filas=[_fila_obra_es_cliente("464717")],
        clientes=[
            _cliente_dict("cli-amscrew", "AMERICAN SCREW CHILE SPA", rut="76086428-5"),
            _cliente_dict("cli-otro", "OTRO CLIENTE LTDA", rut="77123456-9"),
        ],
        obras=[_obra_dict("obra-homonima", "cli-otro", "AMERICAN SCREW CHILE SPA")],
    )

    reconciliar_estado_derivado(raiz_atlas=raiz, reloj=RELOJ)

    fila = _leer_dataset(dataset)["464717"]
    assert "OBRA_DESTINO_SIN_CORROBORAR" in fila["motivos_revision_documento"]


def test_revalidador_obra_destino_aislado_obra_es_cliente_sin_catalogo(tmp_path):
    """La unidad: sin catálogo de obras, obra == cliente retira el motivo
    (comparación puramente textual dentro del mismo documento)."""
    raiz, dataset = _entorno(
        tmp_path, filas=[_fila_obra_es_cliente("464717")],
        clientes=[_cliente_dict("cli-amscrew", "AMERICAN SCREW CHILE SPA")],
        version_previa=RULESET_VERSION,  # sin migración: aislamos el revalidador
    )
    catalogos = raiz / "catalogos_privados"
    actual = raiz / "operacion" / "actual"

    resultado = revalidar_obra_destino_sin_ocr(
        ruta_dataset=dataset, carpeta_catalogos=catalogos,
        ruta_ledger=actual / "ledger_decisiones.jsonl",
    )
    assert "464717" in resultado["guias_actualizadas"]
    fila = _leer_dataset(dataset)["464717"]
    assert "OBRA_DESTINO_SIN_CORROBORAR" not in fila["motivos_revision_documento"]
