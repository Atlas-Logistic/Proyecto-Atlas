"""Bloque MOBILE CONTRATO V2 -- incidencias múltiples + guía firmada como
evidencia adicional. Todo sintético en `tmp_path`; nunca G:\\ ni datos reales.

- `tipos_novedad`: lista de los MISMOS códigos de `TIPOS_NOVEDAD`;
  `tipo_novedad` (v1) sigue siendo compatible.
- `rol_documento`: GUIA (defecto) o EVIDENCIA_FIRMADA (sin OCR ni dataset,
  asociada sólo a UN documento inequívoco; si no, PENDIENTE_ASOCIACION).
- Incidencias de guías ASOCIADAS -> registro canónico `eventos_operacionales
  .json`, con la misma idempotencia que Desktop."""
from __future__ import annotations

import csv
import json
import uuid
from pathlib import Path

import pytest

from atlas_core import mobile
from atlas_core import registro_eventos_operacionales as reo
from atlas_core.eventos_operacionales import construir_eventos_operacionales
from atlas_core.ingesta_pdf import leer_evidencias_adicionales
from atlas_core.mobile import (
    ErrorEnvioMobile, RepositorioEnviosMobile, asociar_evidencia_firmada_mobile,
    asociar_evidencia_firmada_mobile_manual, normalizar_tipos_novedad, procesar_envio_mobile,
    registrar_eventos_canonicos_mobile, reintentar_evidencias_firmadas_pendientes,
)
from atlas_core.procesamiento_masivo import COLUMNAS

BASE = {"chofer_id": "chofer-1", "usuario": "chofer.prueba", "planta_origen_informada": "AZA_COLINA"}


@pytest.fixture()
def operacion(tmp_path):
    raiz = tmp_path / "atlas"
    dataset = raiz / "operacion" / "actual" / "analisis_completo_guias.csv"
    dataset.parent.mkdir(parents=True)
    with dataset.open("w", newline="", encoding="utf-8-sig") as archivo:
        csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";").writeheader()
    return RepositorioEnviosMobile(raiz), dataset


def _recibir(repo, *, imagen=None, **metadata) -> str:
    envio_id = str(uuid.uuid4())
    repo.recibir(envio_id=envio_id, imagen=imagen or uuid.uuid4().bytes, mime="image/jpeg", metadata={**BASE, **metadata})
    return envio_id


def _procesar_guia(repo, envio_id, dataset, guia, transporte):
    """Procesa una guía con el MISMO `procesar_envio_mobile` (OCR simulado)."""
    return procesar_envio_mobile(
        repo, envio_id, dataset=dataset,
        procesador=lambda ruta: {"numero_guia": guia, "numero_transporte": transporte},
    )


def _asegurar_transportes(dataset, *transportes):
    """La asociación Mobile exige que el transporte exista en la operación."""
    with dataset.open("a", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        for t in transportes:
            escritor.writerow({**{c: "" for c in COLUMNAS}, "archivo": f"previo-{t}.jpg", "numero_guia": "1" + t[-5:], "numero_transporte": t})


def _filas(dataset):
    with dataset.open(encoding="utf-8-sig", newline="") as archivo:
        return list(csv.DictReader(archivo, delimiter=";"))


def _no_ocr(*_a, **_k):
    pytest.fail("una EVIDENCIA_FIRMADA nunca debe llegar al OCR")


# ------------------------------------------------------------ contrato

def test_envio_v1_sin_campos_nuevos_sigue_igual(operacion) -> None:
    repo, _ = operacion
    registro = repo.cargar(_recibir(repo, tipo_novedad="DOBLE_VUELTA"))
    assert registro["tipo_novedad"] == "DOBLE_VUELTA" and registro["tipos_novedad"] == ["DOBLE_VUELTA"]
    assert registro["rol_documento"] == "GUIA" and registro["evidencia_de_envio_id"] == ""
    sin = repo.cargar(_recibir(repo))
    assert sin["tipo_novedad"] == "" and sin["tipos_novedad"] == []


@pytest.mark.parametrize("tipos, legado, esperado", [
    ('["TIENE_ESTADIA","DOBLE_VUELTA","DEVOLUCION_PARCIAL"]', "", (["TIENE_ESTADIA", "DOBLE_VUELTA", "DEVOLUCION_PARCIAL"], "TIENE_ESTADIA")),
    (["DOBLE_VUELTA", "DOBLE_VUELTA"], "DOBLE_VUELTA", (["DOBLE_VUELTA"], "DOBLE_VUELTA")),
    ("", "", ([], "")),
    (None, "DEVOLUCION_TOTAL", (["DEVOLUCION_TOTAL"], "DEVOLUCION_TOTAL")),
    (["DEVOLUCION_PARCIAL", "DEVOLUCION_TOTAL"], "", (["DEVOLUCION_PARCIAL", "DEVOLUCION_TOTAL"], "DEVOLUCION_PARCIAL")),
])
def test_normalizacion_de_tipos(tipos, legado, esperado) -> None:
    assert normalizar_tipos_novedad(tipos, legado) == esperado


@pytest.mark.parametrize("tipos, legado", [
    ('["INVENTADO"]', ""), ('["TIENE_ESTADIA"', ""), ('{"a":1}', ""), (["", "DOBLE_VUELTA"], ""),
    (["ESPERA_AUTORIZACION_ESTADIA", "TIENE_ESTADIA"], ""),     # mismo hecho, dos estados
    (["DOBLE_VUELTA"], "TIENE_ESTADIA"),                        # legado fuera de la lista
])
def test_tipos_invalidos_se_rechazan(tipos, legado) -> None:
    with pytest.raises(ErrorEnvioMobile):
        normalizar_tipos_novedad(tipos, legado)


def test_rol_y_referencia_se_validan(operacion) -> None:
    repo, _ = operacion
    with pytest.raises(ErrorEnvioMobile):
        _recibir(repo, rol_documento="OTRO")
    with pytest.raises(ErrorEnvioMobile):
        _recibir(repo, rol_documento="GUIA", evidencia_de_envio_id="abcdefgh-1234")
    envio_id = str(uuid.uuid4())
    with pytest.raises(ErrorEnvioMobile):
        repo.recibir(envio_id=envio_id, imagen=b"x", mime="image/jpeg",
                     metadata={**BASE, "rol_documento": "EVIDENCIA_FIRMADA", "evidencia_de_envio_id": envio_id})


# ------------------------------------------------------------ evidencia firmada

def test_evidencia_firmada_no_pasa_por_ocr_ni_dataset(operacion, monkeypatch) -> None:
    repo, dataset = operacion
    monkeypatch.setattr(mobile, "procesar_archivo", _no_ocr)
    antes = dataset.read_bytes()
    evidencia = _recibir(repo, rol_documento="EVIDENCIA_FIRMADA")
    registro = procesar_envio_mobile(repo, evidencia, dataset=dataset, procesador=_no_ocr)
    assert registro["estado"] == "PENDIENTE_ASOCIACION"
    assert dataset.read_bytes() == antes
    with pytest.raises(ErrorEnvioMobile):
        mobile.reprocesar_envio_mobile_persistido(repo, evidencia, dataset=dataset)


def test_evidencia_vinculada_se_asocia_a_su_guia_e_idempotente(operacion) -> None:
    repo, dataset = operacion
    _asegurar_transportes(dataset, "0000357567")
    lote = "lote-" + uuid.uuid4().hex
    guia = _recibir(repo, lote_id=lote, tipos_novedad='["TIENE_ESTADIA"]')
    _procesar_guia(repo, guia, dataset, "473473", "0000357567")
    firmada_bytes = b"foto-guia-firmada-473473"
    evidencia = _recibir(repo, imagen=firmada_bytes, lote_id=lote, rol_documento="EVIDENCIA_FIRMADA", evidencia_de_envio_id=guia)
    filas_antes = _filas(dataset)

    resultado = asociar_evidencia_firmada_mobile(repo, evidencia, dataset=dataset)

    assert resultado["estado"] == "EVIDENCIA_ASOCIADA" and resultado["nueva"] is True
    documento_guia = f"mobile/{guia}/{repo.cargar(guia)['foto_original']}"
    (asociacion,) = leer_evidencias_adicionales(dataset.parent.parent / "evidencia_pdf")
    assert asociacion["documento"]["archivo"] == documento_guia
    assert asociacion["evidencia"]["archivo"] == f"mobile/{evidencia}/{repo.cargar(evidencia)['foto_original']}"
    assert asociacion["evidencia"]["envio_id"] == evidencia and asociacion["evidencia"]["chofer_id"] == "chofer-1"
    assert asociacion["evidencia"]["evidencia_de_envio_id"] == guia and asociacion["motivo"] == "EVIDENCIA_FIRMADA_MOBILE"
    assert _filas(dataset) == filas_antes  # ni filas nuevas ni cambios
    # idempotencia: reintentar y reenviar los mismos bytes en otro envío
    assert asociar_evidencia_firmada_mobile(repo, evidencia, dataset=dataset)["nueva"] is False
    otra = _recibir(repo, imagen=firmada_bytes, lote_id=lote, rol_documento="EVIDENCIA_FIRMADA", evidencia_de_envio_id=guia)
    assert asociar_evidencia_firmada_mobile(repo, otra, dataset=dataset)["nueva"] is False
    assert len(leer_evidencias_adicionales(dataset.parent.parent / "evidencia_pdf")) == 1


def test_tanda_con_varias_guias_sin_vinculo_explicito_queda_pendiente(operacion) -> None:
    repo, dataset = operacion
    _asegurar_transportes(dataset, "0000357567", "0000357595")
    lote = "lote-" + uuid.uuid4().hex
    g1 = _recibir(repo, lote_id=lote)
    g2 = _recibir(repo, lote_id=lote)
    _procesar_guia(repo, g1, dataset, "473473", "0000357567")
    _procesar_guia(repo, g2, dataset, "473523", "0000357595")
    sin_vinculo = _recibir(repo, lote_id=lote, rol_documento="EVIDENCIA_FIRMADA")
    con_vinculo = _recibir(repo, lote_id=lote, rol_documento="EVIDENCIA_FIRMADA", evidencia_de_envio_id=g2)

    assert asociar_evidencia_firmada_mobile(repo, sin_vinculo, dataset=dataset) == {
        "envio_id": sin_vinculo, "estado": "PENDIENTE_ASOCIACION", "motivo": "TANDA_CON_VARIAS_GUIAS",
    }
    asociada = asociar_evidencia_firmada_mobile(repo, con_vinculo, dataset=dataset)
    assert asociada["documento"] == f"mobile/{g2}/{repo.cargar(g2)['foto_original']}"


def test_evidencia_antes_que_su_guia_queda_pendiente_y_luego_se_asocia(operacion) -> None:
    repo, dataset = operacion
    _asegurar_transportes(dataset, "0000359308")
    lote = "lote-" + uuid.uuid4().hex
    guia = _recibir(repo, lote_id=lote)
    evidencia = _recibir(repo, lote_id=lote, rol_documento="EVIDENCIA_FIRMADA", evidencia_de_envio_id=guia)
    primera = asociar_evidencia_firmada_mobile(repo, evidencia, dataset=dataset)
    assert primera["estado"] == "PENDIENTE_ASOCIACION" and primera["motivo"] == "GUIA_DE_REFERENCIA_SIN_PROCESAR"
    _procesar_guia(repo, guia, dataset, "474172", "0000359308")
    (reintento,) = reintentar_evidencias_firmadas_pendientes(repo, dataset=dataset)
    assert reintento["estado"] == "EVIDENCIA_ASOCIADA"


def test_asociacion_manual_exige_un_unico_documento(operacion) -> None:
    repo, dataset = operacion
    _asegurar_transportes(dataset, "0000357567", "0000357595")
    evidencia = _recibir(repo, rol_documento="EVIDENCIA_FIRMADA")
    with pytest.raises(ErrorEnvioMobile):
        asociar_evidencia_firmada_mobile_manual(repo, evidencia, dataset=dataset, numero_guia="999999", actor="Javier")
    guia_unica = _filas(dataset)[0]["numero_guia"]
    resultado = asociar_evidencia_firmada_mobile_manual(repo, evidencia, dataset=dataset, numero_guia=guia_unica, actor="Javier")
    assert resultado["estado"] == "EVIDENCIA_ASOCIADA"
    (asociacion,) = leer_evidencias_adicionales(dataset.parent.parent / "evidencia_pdf")
    assert asociacion["motivo"] == "EVIDENCIA_FIRMADA_MOBILE_MANUAL" and asociacion["asociado_por"] == "Javier"
    # dos documentos con la misma guía -> nunca se elige uno
    repetida = _filas(dataset)[1]
    _asegurar_transportes(dataset, repetida["numero_transporte"])
    otra = _recibir(repo, rol_documento="EVIDENCIA_FIRMADA")
    with pytest.raises(ErrorEnvioMobile, match="2 documentos"):
        asociar_evidencia_firmada_mobile_manual(repo, otra, dataset=dataset, numero_guia=repetida["numero_guia"], actor="Javier")


# ------------------------------------------------------------ eventos canónicos

def _eventos(raiz):
    return {(e["tipo_evento"], e["numero_transporte"]): e for e in reo.leer_eventos_operacionales(raiz=raiz)["eventos"]}


def test_varias_incidencias_generan_eventos_canonicos_con_identidad_propia(operacion) -> None:
    repo, dataset = operacion
    _asegurar_transportes(dataset, "0000357567")
    lote = "lote-" + uuid.uuid4().hex
    tipos = '["ESPERA_AUTORIZACION_ESTADIA","DOBLE_VUELTA","DEVOLUCION_PARCIAL"]'
    g1 = _recibir(repo, lote_id=lote, tipos_novedad=tipos)
    g2 = _recibir(repo, lote_id=lote, tipos_novedad=tipos)  # otra foto de la misma tanda
    for g in (g1, g2):
        _procesar_guia(repo, g, dataset, "473473", "0000357567")

    registrar_eventos_canonicos_mobile(repo)
    registrar_eventos_canonicos_mobile(repo)  # idempotente

    eventos = _eventos(repo.raiz_atlas)
    assert sorted(eventos) == [("DEVOLUCION_PARCIAL", "0000357567"), ("DOBLE_VUELTA", "0000357567"), ("TIENE_ESTADIA", "0000357567")]
    estadia = eventos[("TIENE_ESTADIA", "0000357567")]
    assert estadia["estado_incidencia"] == "ESPERA_ESTADIA" and estadia["estado_gestion"] == "PENDIENTE_RESPUESTA"
    assert len({e["evento_id"] for e in eventos.values()}) == 3
    assert set(repo.cargar(g1)["eventos_canonicos"]) == {"ESPERA_AUTORIZACION_ESTADIA", "DOBLE_VUELTA", "DEVOLUCION_PARCIAL"}


def test_tiene_estadia_se_registra_aprobada_y_nunca_retrocede(operacion) -> None:
    repo, dataset = operacion
    _asegurar_transportes(dataset, "0000359308")
    aprobada = _recibir(repo, tipos_novedad='["TIENE_ESTADIA"]')
    _procesar_guia(repo, aprobada, dataset, "474172", "0000359308")
    registrar_eventos_canonicos_mobile(repo)
    tardia = _recibir(repo, tipos_novedad='["ESPERA_AUTORIZACION_ESTADIA"]')  # foto vieja que llega después
    _procesar_guia(repo, tardia, dataset, "474172", "0000359308")
    registrar_eventos_canonicos_mobile(repo)
    estadia = _eventos(repo.raiz_atlas)[("TIENE_ESTADIA", "0000359308")]
    assert estadia["estado_incidencia"] == "ESTADIA_APROBADA" and estadia["estado_gestion"] == "APROBADA"
    assert repo.cargar(tardia)["eventos_canonicos"]["ESPERA_AUTORIZACION_ESTADIA"]["resultado"] == "OMITIDO_ESTADIA_YA_APROBADA"


def test_evento_anulado_en_desktop_no_se_reactiva_desde_mobile(operacion) -> None:
    repo, dataset = operacion
    _asegurar_transportes(dataset, "0000357595")
    primero = _recibir(repo, tipos_novedad='["DOBLE_VUELTA"]')
    _procesar_guia(repo, primero, dataset, "473523", "0000357595")
    registrar_eventos_canonicos_mobile(repo)
    reo.anular_evento(raiz=repo.raiz_atlas, tipo_evento="DOBLE_VUELTA", numero_transporte="0000357595", origen="DESKTOP:Javier")
    otra_foto = _recibir(repo, tipos_novedad='["DOBLE_VUELTA"]')
    _procesar_guia(repo, otra_foto, dataset, "473523", "0000357595")
    registrar_eventos_canonicos_mobile(repo)
    assert _eventos(repo.raiz_atlas)[("DOBLE_VUELTA", "0000357595")]["estado"] == "ANULADO"


def test_evidencia_y_envio_sin_asociar_no_generan_eventos(operacion) -> None:
    repo, _ = operacion
    _recibir(repo, rol_documento="EVIDENCIA_FIRMADA", tipos_novedad='["TIENE_ESTADIA"]')
    _recibir(repo, tipos_novedad='["DOBLE_VUELTA"]')  # nunca procesado -> sin viaje
    assert registrar_eventos_canonicos_mobile(repo) == []
    assert reo.leer_eventos_operacionales(raiz=repo.raiz_atlas)["eventos"] == []


def test_adaptador_de_consultas_da_identidad_propia_a_cada_incidencia() -> None:
    envios = [
        {"envio_id": "v1", "tipo_novedad": "DOBLE_VUELTA"},
        {"envio_id": "v2", "tipos_novedad": ["TIENE_ESTADIA", "DEVOLUCION_TOTAL"], "tipo_novedad": "TIENE_ESTADIA"},
        {"envio_id": "ev", "tipos_novedad": ["TIENE_ESTADIA"], "rol_documento": "EVIDENCIA_FIRMADA"},
    ]
    eventos = construir_eventos_operacionales(envios, [])
    assert [(e["evento_id"], e["tipo_evento"]) for e in eventos] == [
        ("v1", "DOBLE_VUELTA"), ("v2:TIENE_ESTADIA", "TIENE_ESTADIA"), ("v2:DEVOLUCION_TOTAL", "DEVOLUCION_TOTAL"),
    ]
