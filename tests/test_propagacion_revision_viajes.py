"""Contrato de propagación conservadora desde filas OCR hasta viajes."""

import csv
from datetime import datetime, timezone

from atlas_core.gestor_viajes import (
    EstadoViaje,
    MotivoRevision,
    agrupar_viajes,
)
from atlas_core.procesamiento_masivo import COLUMNAS
from atlas_core.reporte_viajes import generar_reporte_viajes


RELOJ = lambda: datetime(2026, 7, 29, tzinfo=timezone.utc)


def _fila(**cambios):
    fila = {
        "archivo": "guia-sintetica.jpg",
        "estado_procesamiento": "OK",
        "error": "",
        "numero_guia": "SINT-001",
        "numero_transporte": "0000149935",
        "fecha": "27-07-2026",
        "chofer": "CHOFER SINTETICO",
        "rut_chofer": "",
        "cliente": "CLIENTE SINTETICO",
        "obra_destino": "",
        "patente_tracto": "",
        "patente_rampla": "",
        "descripcion_material": "",
        "tipo_carga": "NO DETERMINADO",
        "indicador_revision": "OK",
    }
    fila.update(cambios)
    return fila


def _un_viaje(filas):
    viajes, pendientes = agrupar_viajes(filas, reloj=RELOJ)
    assert not pendientes
    assert len(viajes) == 1
    return viajes[0]


def test_una_fila_confirmada_produce_viaje_confirmado():
    assert _un_viaje([_fila()]).estado == EstadoViaje.CONFIRMADO


def test_una_fila_revisar_produce_viaje_en_revision():
    viaje = _un_viaje([_fila(indicador_revision="REVISAR")])
    assert viaje.estado == EstadoViaje.REQUIERE_REVISION
    assert MotivoRevision.DOCUMENTO_REQUIERE_REVISION in viaje.motivos_revision


def test_dos_filas_confirmadas_producen_viaje_confirmado():
    viaje = _un_viaje(
        [_fila(archivo="a.jpg"), _fila(archivo="b.jpg", numero_guia="SINT-002")]
    )
    assert viaje.estado == EstadoViaje.CONFIRMADO


def test_confirmada_mas_revisar_produce_viaje_en_revision():
    viaje = _un_viaje(
        [
            _fila(archivo="a.jpg"),
            _fila(
                archivo="b.jpg",
                numero_guia="SINT-002",
                indicador_revision="REVISAR",
            ),
        ]
    )
    assert viaje.estado == EstadoViaje.REQUIERE_REVISION


def test_varias_filas_revisar_deduplican_el_mismo_motivo():
    viaje = _un_viaje(
        [
            _fila(archivo="a.jpg", indicador_revision="REVISAR"),
            _fila(
                archivo="b.jpg",
                numero_guia="SINT-002",
                indicador_revision="REVISAR",
            ),
        ]
    )
    assert viaje.motivos_revision.count(
        MotivoRevision.DOCUMENTO_REQUIERE_REVISION
    ) == 1


def test_motivos_diferentes_se_conservan_una_sola_vez():
    viaje = _un_viaje(
        [
            _fila(archivo="a.jpg", indicador_revision="REVISAR"),
            _fila(
                archivo="b.jpg",
                numero_guia="SINT-002",
                estado_procesamiento="ERROR",
                error="fallo OCR sintético",
                indicador_revision="REVISAR",
            ),
        ]
    )
    assert viaje.motivos_revision == [
        MotivoRevision.DOCUMENTO_REQUIERE_REVISION,
        MotivoRevision.ERROR_TECNICO_DOCUMENTO,
    ]


def test_revisar_sin_motivo_especifico_permanece_en_revision():
    viaje = _un_viaje([_fila(indicador_revision="REVISAR", error="")])
    assert viaje.estado == EstadoViaje.REQUIERE_REVISION
    assert viaje.motivos_revision


def test_error_tecnico_nunca_se_confirma_silenciosamente():
    viaje = _un_viaje(
        [_fila(estado_procesamiento="ERROR", error="fallo OCR sintético")]
    )
    assert viaje.estado == EstadoViaje.REQUIERE_REVISION
    assert MotivoRevision.ERROR_TECNICO_DOCUMENTO in viaje.motivos_revision


def test_ausencia_de_transporte_permanece_fuera_de_viajes_con_evidencia():
    fila = _fila(numero_transporte="", indicador_revision="REVISAR")
    viajes, pendientes = agrupar_viajes([fila], reloj=RELOJ)
    assert not viajes
    assert pendientes == [fila]


def test_orden_de_motivos_es_determinista():
    filas = [
        _fila(archivo="b.jpg", indicador_revision="REVISAR"),
        _fila(
            archivo="a.jpg",
            numero_guia="SINT-002",
            cliente="CLIENTE DISTINTO",
            estado_procesamiento="ERROR",
            error="fallo OCR sintético",
        ),
    ]
    primero = _un_viaje(filas)
    segundo = _un_viaje(list(reversed(filas)))
    assert primero.motivos_revision == segundo.motivos_revision


def test_regeneracion_es_semanticamente_identica():
    filas = [_fila(indicador_revision="REVISAR")]
    primero = _un_viaje(filas)
    segundo = _un_viaje(filas)
    assert primero.a_dict() == segundo.a_dict()


def test_alias_ocr_conserva_revision_y_motivos():
    viaje = _un_viaje(
        [_fila(chofer="PAIRICIO SINTETICO", indicador_revision="REVISAR")]
    )
    viajes, _ = agrupar_viajes(
        [_fila(chofer="PAIRICIO SINTETICO", indicador_revision="REVISAR")],
        normalizador_chofer=lambda _: "PATRICIO SINTETICO",
        reloj=RELOJ,
    )
    corregido = viajes[0]
    assert viaje.estado == EstadoViaje.REQUIERE_REVISION
    assert corregido.estado == EstadoViaje.REQUIERE_REVISION
    assert corregido.choferes == ["PATRICIO SINTETICO"]
    assert corregido.motivos_revision == viaje.motivos_revision


def test_reporte_csv_publica_revision_y_motivo_de_la_fila(tmp_path):
    origen = tmp_path / "entrada.csv"
    with origen.open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader()
        escritor.writerow(_fila(indicador_revision="REVISAR"))
    salida = tmp_path / "reporte"
    generar_reporte_viajes(origen, salida, reloj=RELOJ)
    with (salida / "viajes.csv").open(
        newline="", encoding="utf-8-sig"
    ) as archivo:
        viaje = next(csv.DictReader(archivo, delimiter=";"))
    assert viaje["estado"] == EstadoViaje.REQUIERE_REVISION.value
    assert (
        viaje["motivos_revision"]
        == MotivoRevision.DOCUMENTO_REQUIERE_REVISION.value
    )
