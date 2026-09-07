"""Bloque CONVERGENCIA DE ESTADO TÉCNICO STALE -- caso real: viaje
0000356332, guías 477145+477146 (SALOMON SACK SA, chofer JOSE LAZCANO,
origen AZA RENCA, destino CAMINO LOS PINOS 3396 SAN BERNARDO ya con ruta
calculada 21,76 km / 33,13 min).

Causa raíz: el pendiente técnico (`estado_documental`/`estado_operacional`
= `REQUIERE_REVISION`) se fijó cuando todavía faltaba routing. Una
reconciliación posterior resolvió origen+ruta (`estado_ruta` =
`RUTA_CALCULADA`, `indicador_revision` = `OK`, sin ningún motivo
documental real), pero el estado derivado del documento/viaje quedó sin
recalcular -- y ninguna vía automática volvía a tocarlo: `migracion` da
`False` (versión ya vigente), `por_reintentar` está vacío (la ruta YA está
calculada) y `reporte_desactualizado` da `False` (el dataset no volvió a
cambiar tras la última publicación). El viaje seguía `INCOMPLETO_TECNICO`
indefinidamente sin intervención humana.

Estas pruebas demuestran que `reconciliar_estado_derivado` detecta esa
incoherencia INTERNA por sí sola (`_estado_derivado_incoherente`), la
converge en una sola pasada (dataset + viaje), es idempotente en el
rerun, y NO degrada un viaje con revisión humana genuina -- control:
0000356848, guía 473210, `OBRA_DESTINO_SIN_CORROBORAR` real, sigue
`REQUIERE_REVISION`.
"""
from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path

from atlas_core.almacenamiento_portable import escribir_estado_operacion
from atlas_core.gestor_viajes import EstadoViaje, agrupar_viajes
from atlas_core.procesamiento_masivo import COLUMNAS
from atlas_core.reporte_viajes import _sha256_archivo
from atlas_core.reconciliacion_estado_derivado import (
    RULESET_VERSION,
    _estado_derivado_incoherente,
    reconciliar_estado_derivado,
)

RELOJ = lambda: datetime(2026, 9, 7, 18, 0, tzinfo=timezone.utc)

TTE_B = "0000356332"  # convergible: sin motivo real, ruta ya calculada
TTE_A = "0000356848"  # control: revisión humana genuina (obra sin corroborar)


def _fila_base(numero_guia: str, transporte: str) -> dict[str, str]:
    fila = {c: "" for c in COLUMNAS}
    fila.update({
        "archivo": f"mobile/{numero_guia}/original.jpg", "estado_procesamiento": "OK",
        "numero_guia": numero_guia, "numero_transporte": transporte, "fecha": "31-08-2026",
        "chofer": "JOSE LAZCANO", "cliente": "SALOMON SACK SA",
        "despachar_a_crudo": "CAMINO LOS PINOS 3396 SANTIAGO SAN BERNARDO",
        "direccion_entrega": "CAMINO LOS PINOS 3396 SANTIAGO SAN BERNARDO",
        "localidad_entrega": "San Bernardo", "region_entrega": "Metropolitana",
        "estado_ruta": "RUTA_CALCULADA", "motivo_ruta": "",
        "distancia_km": "21.7619", "duracion_min": "33.13", "proveedor_ruta": "openrouteservice",
        "planta_origen_id": "42d5df3b-5fe8-4677-a0e2-c283ab26a085",
        "planta_origen_nombre": "AZA RENCA", "origen_determinado_por": "CATEGORIA",
        "evidencia_origen": "CATEGORIA=ANGULOS;UNICA_PLANTA_COMPATIBLE",
    })
    return fila


def _fila_stale_tecnica(numero_guia: str) -> dict[str, str]:
    """Estado REAL observado en 477145/477146: `indicador_revision` ya
    `OK` (sin motivo documental), pero `estado_documental`/
    `estado_operacional` congelados en `REQUIERE_REVISION` desde cuando
    faltaba routing."""
    fila = _fila_base(numero_guia, TTE_B)
    fila.update({
        "obra_destino": "SALOMON SACK SA SAN BERNARDO",
        "motivos_revision_documento": "",
        "indicador_revision": "OK",
        "estado_documental": "REQUIERE_REVISION",
        "estado_operacional": "REQUIERE_REVISION",
    })
    return fila


def _fila_revision_humana(numero_guia: str) -> dict[str, str]:
    """Control: motivo documental real -- NUNCA debe converger a OK."""
    fila = _fila_base(numero_guia, TTE_A)
    fila.update({
        "cliente": "SODIMAC SA", "obra_destino": "CONSTRUCTORA CBI SPA",
        "despachar_a_crudo": "ING. EDUARDO DOMINGUEZ 920 MAIPU MAIPU",
        "direccion_entrega": "ING. EDUARDO DOMINGUEZ 920 MAIPU MAIPU",
        "localidad_entrega": "Maipú",
        "motivos_revision_documento": "OBRA_DESTINO_SIN_CORROBORAR",
        "indicador_revision": "REVISAR",
        "estado_documental": "REQUIERE_REVISION",
        "estado_operacional": "REQUIERE_REVISION",
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


def _entorno(tmp_path: Path) -> tuple[Path, Path]:
    raiz = tmp_path / "Atlas"
    catalogos = raiz / "catalogos_privados"
    actual = raiz / "operacion" / "actual"
    catalogos.mkdir(parents=True)
    actual.mkdir(parents=True)
    for nombre, contenido in {
        "clientes.json": {"version_formato": 1, "clientes": []},
        "empresas.json": {}, "vehiculos.json": {"version": 1, "vehiculos": []},
        "obras_destinos.json": {"version_formato": 1, "obras": [], "relaciones": []},
        "destinos_maestros.json": {"version_formato": 1, "destinos": []},
    }.items():
        (catalogos / nombre).write_text(json.dumps(contenido), encoding="utf-8")

    dataset = actual / "analisis_completo_guias.csv"
    _escribir_dataset(dataset, [
        _fila_stale_tecnica("477145"), _fila_stale_tecnica("477146"),
        _fila_revision_humana("473210"),
    ])
    decisiones = actual / "decisiones_pendientes.json"
    decisiones.write_text(json.dumps({"schema_version": 1, "decisiones": []}), encoding="utf-8")

    # Estado publicado EXACTAMENTE como quedaría tras una reconciliación
    # anterior YA cerrada: versión vigente + hash del dataset actual. Sin
    # esto, `reporte_desactualizado` daría `True` y taparía el disparador
    # que esta prueba valida.
    reporte_previo = raiz / "reportes" / "previo"
    reporte_previo.mkdir(parents=True)
    escribir_estado_operacion(
        reporte_vigente=reporte_previo, dataset_operacional=dataset,
        decisiones_pendientes=decisiones, raiz=raiz, reloj=RELOJ,
        version_estado_derivado=RULESET_VERSION,
        dataset_sha256=_sha256_archivo(dataset),
    )
    return raiz, dataset


# ---------------------------------------------------------------------------
# unidad -- el detector, aislado
# ---------------------------------------------------------------------------

def test_detector_marca_incoherente_solo_la_fila_stale_tecnica(tmp_path):
    dataset = tmp_path / "d.csv"
    _escribir_dataset(dataset, [_fila_stale_tecnica("477145"), _fila_revision_humana("473210")])
    assert _estado_derivado_incoherente(dataset) is True


def test_detector_no_marca_dataset_con_solo_revision_humana_real(tmp_path):
    dataset = tmp_path / "d.csv"
    _escribir_dataset(dataset, [_fila_revision_humana("473210")])
    assert _estado_derivado_incoherente(dataset) is False


def test_detector_no_marca_dataset_ya_convergido(tmp_path):
    dataset = tmp_path / "d.csv"
    fila = _fila_stale_tecnica("477145")
    fila.update({"estado_documental": "OK", "estado_operacional": "OK"})
    _escribir_dataset(dataset, [fila, _fila_revision_humana("473210")])
    assert _estado_derivado_incoherente(dataset) is False


def test_detector_no_marca_al_reves_fila_menos_estricta_que_lo_canonico(tmp_path):
    # `estado_ruta` sin calcular + fila que dice OK -- esa dirección la
    # arregla `revalidar_indicadores_documentales_sin_ocr` (bidireccional)
    # cuando ya se entra al bloque; NUNCA debe disparar el bloque por sí
    # sola desde aquí.
    dataset = tmp_path / "d.csv"
    fila = _fila_stale_tecnica("477145")
    fila.update({"estado_ruta": "REQUIERE_REVISION", "indicador_revision": "OK",
                 "estado_documental": "OK", "estado_operacional": "OK"})
    _escribir_dataset(dataset, [fila])
    assert _estado_derivado_incoherente(dataset) is False


# ---------------------------------------------------------------------------
# integración -- reconciliación real, sin OCR, sin edición manual
# ---------------------------------------------------------------------------

def test_estado_tecnico_stale_converge_sin_migracion_ni_dataset_desactualizado(tmp_path):
    raiz, dataset = _entorno(tmp_path)

    resultado = reconciliar_estado_derivado(raiz_atlas=raiz, reloj=RELOJ)

    # El disparador fue la incoherencia interna -- NO una migración ni un
    # reporte desactualizado (los dos caminos que ya existían).
    assert resultado["reconciliado"] is True
    assert resultado["reporte_regenerado_por_estado_derivado_incoherente"] is True
    assert resultado["reporte_regenerado_por_dataset_desactualizado"] is False

    filas = _leer_dataset(dataset)

    # -- viaje B: los tres campos derivados convergen a OK; la ruta y sus
    #    magnitudes se preservan intactas.
    for guia in ("477145", "477146"):
        fila = filas[guia]
        assert fila["indicador_revision"] == "OK"
        assert fila["estado_documental"] == "OK"
        assert fila["estado_operacional"] == "OK"
        assert fila["estado_ruta"] == "RUTA_CALCULADA"
        assert fila["distancia_km"] == "21.7619"
        assert fila["duracion_min"] == "33.13"

    # -- control A: motivo documental real intacto, sigue en revisión.
    control = filas["473210"]
    assert control["motivos_revision_documento"] == "OBRA_DESTINO_SIN_CORROBORAR"
    assert control["indicador_revision"] == "REVISAR"
    assert control["estado_documental"] == "REQUIERE_REVISION"
    assert control["estado_operacional"] == "REQUIERE_REVISION"

    # -- viajes: B CONFIRMADO (ya no INCOMPLETO_TECNICO); A NO confirmado.
    viajes, _ = agrupar_viajes(list(filas.values()), guias_revision_humana=set())
    por_tte = {v.numero_transporte: v for v in viajes}
    assert por_tte[TTE_B].estado == EstadoViaje.CONFIRMADO
    assert por_tte[TTE_A].estado != EstadoViaje.CONFIRMADO


def test_rerun_es_idempotente_no_op(tmp_path):
    raiz, dataset = _entorno(tmp_path)

    primero = reconciliar_estado_derivado(raiz_atlas=raiz, reloj=RELOJ)
    assert primero["reconciliado"] is True

    huella_tras_primero = _sha256_archivo(dataset)
    segundo = reconciliar_estado_derivado(raiz_atlas=raiz, reloj=RELOJ)

    assert segundo["reconciliado"] is False
    assert segundo["motivo"] == "VERSION_VIGENTE_SIN_REINTENTO_PENDIENTE"
    # El dataset no volvió a moverse en el segundo pase.
    assert _sha256_archivo(dataset) == huella_tras_primero
