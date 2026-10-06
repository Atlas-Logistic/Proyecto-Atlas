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


# ---- viaje creado por la misma guía (caso real 474562 -> 0000360111)

def _publicar_reporte(raiz, viajes):
    """Reporte vigente mínimo: `viajes` = [(numero_transporte, [envio_id, ...])]."""
    from atlas_core.almacenamiento_portable import escribir_estado_operacion

    carpeta = raiz / "reportes" / ("r-" + uuid.uuid4().hex)
    carpeta.mkdir(parents=True)
    with (carpeta / "viajes.csv").open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=["viaje_id", "numero_transporte", "evidencias_documentos"], delimiter=";")
        escritor.writeheader()
        for transporte, envios in viajes:
            escritor.writerow({
                "viaje_id": str(uuid.uuid4()), "numero_transporte": transporte,
                "evidencias_documentos": json.dumps([{"archivo": f"mobile/{e}/original.jpg"} for e in envios]),
            })
    escribir_estado_operacion(reporte_vigente=carpeta, raiz=raiz)


def _guia_que_crea_viaje(repo, dataset, guia, transporte, tipos='["ESPERA_AUTORIZACION_ESTADIA"]'):
    envio = _recibir(repo, tipos_novedad=tipos)
    _procesar_guia(repo, envio, dataset, guia, transporte)
    registro = repo.cargar(envio)
    assert registro["estado"] == "ASOCIADO"
    assert registro["resultado_asociacion"]["estado"] == "SIN_ASOCIACION"
    assert registro["resultado_asociacion"]["numero_transporte"] == ""
    return envio


def test_viaje_creado_por_la_misma_guia_proyecta_espera_estadia(operacion) -> None:
    repo, dataset = operacion
    envio = _guia_que_crea_viaje(repo, dataset, "474562", "0000360111")
    _publicar_reporte(repo.raiz_atlas, [("0000360111", [envio])])

    registrar_eventos_canonicos_mobile(repo)
    registrar_eventos_canonicos_mobile(repo)  # idempotente

    eventos = reo.leer_eventos_operacionales(raiz=repo.raiz_atlas)["eventos"]
    assert len(eventos) == 1
    estadia = eventos[0]
    assert (estadia["tipo_evento"], estadia["numero_transporte"]) == ("TIENE_ESTADIA", "0000360111")
    assert estadia["estado"] == "ACTIVO" and estadia["estado_incidencia"] == "ESPERA_ESTADIA"
    registro = repo.cargar(envio)
    marca = registro["eventos_canonicos"]["ESPERA_AUTORIZACION_ESTADIA"]
    assert marca["resultado"] == "CREADO" and marca["via"] == "VIAJE_CREADO_CON_ESTA_GUIA"
    # la asociación NUNCA se reescribe (regla anti-autoasociación intacta)
    assert registro["resultado_asociacion"]["estado"] == "SIN_ASOCIACION"
    assert registro["resultado_asociacion"]["numero_transporte"] == ""


def test_viaje_creado_sin_coincidencia_en_reporte_no_proyecta_y_se_reintenta(operacion) -> None:
    repo, dataset = operacion
    envio = _guia_que_crea_viaje(repo, dataset, "474548", "0000360098")
    _publicar_reporte(repo.raiz_atlas, [("0000360098", ["otro-envio"])])  # 0 coincidencias

    assert registrar_eventos_canonicos_mobile(repo) == []
    assert reo.leer_eventos_operacionales(raiz=repo.raiz_atlas)["eventos"] == []
    assert repo.cargar(envio).get("eventos_canonicos") is None  # sin marca: queda reintentable

    _publicar_reporte(repo.raiz_atlas, [("0000360098", [envio])])  # el reporte ya lo incluye
    registrar_eventos_canonicos_mobile(repo)
    eventos = reo.leer_eventos_operacionales(raiz=repo.raiz_atlas)["eventos"]
    assert [(e["numero_transporte"], e["estado_incidencia"]) for e in eventos] == [("0000360098", "ESPERA_ESTADIA")]


def test_viaje_creado_con_dos_coincidencias_no_proyecta(operacion) -> None:
    repo, dataset = operacion
    envio = _guia_que_crea_viaje(repo, dataset, "474570", "0000360120")
    _publicar_reporte(repo.raiz_atlas, [("0000360120", [envio]), ("0000360121", [envio])])

    assert registrar_eventos_canonicos_mobile(repo) == []
    assert reo.leer_eventos_operacionales(raiz=repo.raiz_atlas)["eventos"] == []
    assert repo.cargar(envio).get("eventos_canonicos") is None


def test_viaje_creado_con_envio_en_revision_si_proyecta(operacion) -> None:
    # Antes del caso real 475413 esto NO proyectaba: cualquier revisión
    # documental borraba la incidencia aunque el viaje estuviera demostrado.
    repo, dataset = operacion
    envio = _guia_que_crea_viaje(repo, dataset, "474571", "0000360122")
    registro = repo.cargar(envio)
    registro["estado"] = "REQUIERE_REVISION"
    repo.guardar(envio, registro)
    _publicar_reporte(repo.raiz_atlas, [("0000360122", [envio])])

    registrar_eventos_canonicos_mobile(repo)

    estadia = _eventos(repo.raiz_atlas)[("TIENE_ESTADIA", "0000360122")]
    assert estadia["estado_incidencia"] == "ESPERA_ESTADIA"
    assert repo.cargar(envio)["eventos_canonicos"]["ESPERA_AUTORIZACION_ESTADIA"]["via"] == "DOCUMENTO_EN_VIAJE_DEL_REPORTE"


def test_viaje_creado_espera_y_luego_tiene_estadia_pasa_a_aprobada(operacion) -> None:
    repo, dataset = operacion
    espera = _guia_que_crea_viaje(repo, dataset, "474572", "0000360123")
    _publicar_reporte(repo.raiz_atlas, [("0000360123", [espera])])
    registrar_eventos_canonicos_mobile(repo)
    inicial = reo.leer_eventos_operacionales(raiz=repo.raiz_atlas)["eventos"]
    assert [e["estado_incidencia"] for e in inicial] == ["ESPERA_ESTADIA"]

    aprobada = _recibir(repo, tipos_novedad='["TIENE_ESTADIA"]')  # misma guía, más tarde
    _procesar_guia(repo, aprobada, dataset, "474572", "0000360123")
    registrar_eventos_canonicos_mobile(repo)

    eventos = reo.leer_eventos_operacionales(raiz=repo.raiz_atlas)["eventos"]
    assert len(eventos) == 1
    assert eventos[0]["estado_incidencia"] == "ESTADIA_APROBADA" and eventos[0]["estado_gestion"] == "APROBADA"
    assert "via" not in repo.cargar(aprobada)["eventos_canonicos"]["TIENE_ESTADIA"]  # viaje ya existente: vía normal


def test_viaje_ya_existente_conserva_via_normal_sin_reporte(operacion) -> None:
    repo, dataset = operacion
    _asegurar_transportes(dataset, "0000360030")
    envio = _recibir(repo, tipos_novedad='["ESPERA_AUTORIZACION_ESTADIA"]')
    _procesar_guia(repo, envio, dataset, "474541", "0000360030")
    assert repo.cargar(envio)["resultado_asociacion"]["numero_transporte"] == "0000360030"

    registrar_eventos_canonicos_mobile(repo)  # sin reporte vigente: igual que antes

    estadia = _eventos(repo.raiz_atlas)[("TIENE_ESTADIA", "0000360030")]
    assert estadia["estado_incidencia"] == "ESPERA_ESTADIA"
    marca = repo.cargar(envio)["eventos_canonicos"]["ESPERA_AUTORIZACION_ESTADIA"]
    assert marca["resultado"] == "CREADO" and "via" not in marca


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


# ---- guía en revisión con viaje demostrado (caso real 475413 -> 0000362423)
#
# La incidencia la declara el chofer sobre el VIAJE; una duda documental
# independiente (obra/destino/cliente) no la hace desaparecer. El vínculo
# documento -> viaje sigue exigiendo la MISMA prueba: el propio documento
# del envío figura en exactamente un viaje del reporte vigente.

def _guia_en_revision(repo, dataset, guia, transporte, *, tipos='["DEVOLUCION_TOTAL"]', **metadata):
    """Mismo `procesar_envio_mobile`: el Core marca la guía REVISAR por una
    duda de obra (independiente del vínculo con el viaje)."""
    envio = _recibir(repo, tipos_novedad=tipos, **metadata)
    procesar_envio_mobile(
        repo, envio, dataset=dataset,
        procesador=lambda ruta: {
            "numero_guia": guia, "numero_transporte": transporte,
            "indicador_revision": "REVISAR", "motivos_revision_documento": "OBRA_DESTINO_SIN_CORROBORAR",
        },
    )
    registro = repo.cargar(envio)
    assert registro["estado"] == "REQUIERE_REVISION"
    assert registro["problema_captura"] is False
    return envio


def test_devolucion_total_en_guia_en_revision_con_viaje_demostrado_genera_evento(operacion) -> None:
    repo, dataset = operacion
    envio = _guia_en_revision(repo, dataset, "475413", "0000362423")
    _publicar_reporte(repo.raiz_atlas, [("0000362423", [envio])])

    (salida,) = registrar_eventos_canonicos_mobile(repo)

    assert salida["numero_transporte"] == "0000362423"
    devolucion = _eventos(repo.raiz_atlas)[("DEVOLUCION_TOTAL", "0000362423")]
    assert devolucion["estado"] == "ACTIVO" and devolucion["nota"] == ""  # sin observación: nunca se inventa
    assert devolucion["procedencias"][0]["referencia"] == f"ENVIO_MOBILE:{envio}"
    marca = repo.cargar(envio)["eventos_canonicos"]["DEVOLUCION_TOTAL"]
    assert marca["resultado"] == "CREADO" and marca["via"] == "DOCUMENTO_EN_VIAJE_DEL_REPORTE"


def test_observacion_mobile_llega_como_nota_del_evento(operacion) -> None:
    repo, dataset = operacion
    observacion = "No se recibe por mal estado al ingreso y descarga de la obra. (Terreno lleno de barro)"
    envio = _guia_en_revision(repo, dataset, "475413", "0000362423", observacion=observacion)
    _publicar_reporte(repo.raiz_atlas, [("0000362423", [envio])])

    registrar_eventos_canonicos_mobile(repo)

    assert _eventos(repo.raiz_atlas)[("DEVOLUCION_TOTAL", "0000362423")]["nota"] == observacion


def test_observacion_mobile_nunca_pisa_la_nota_de_desktop(operacion) -> None:
    repo, dataset = operacion
    reo.registrar_evento(
        raiz=repo.raiz_atlas, tipo_evento="DEVOLUCION_TOTAL", numero_transporte="0000362423",
        nota="Nota de Javier", origen="DESKTOP:Javier",
    )
    envio = _guia_en_revision(repo, dataset, "475413", "0000362423", observacion="texto del chofer")
    _publicar_reporte(repo.raiz_atlas, [("0000362423", [envio])])

    registrar_eventos_canonicos_mobile(repo)

    devolucion = _eventos(repo.raiz_atlas)[("DEVOLUCION_TOTAL", "0000362423")]
    assert devolucion["nota"] == "Nota de Javier"
    assert repo.cargar(envio)["eventos_canonicos"]["DEVOLUCION_TOTAL"]["resultado"] == "EXISTENTE"


def test_observacion_llega_como_nota_tambien_en_guia_asociada(operacion) -> None:
    repo, dataset = operacion
    envio = _recibir(repo, tipos_novedad='["ESPERA_AUTORIZACION_ESTADIA"]', observacion="estadia a espera de firma")
    _procesar_guia(repo, envio, dataset, "475201", "0000361852")
    assert repo.cargar(envio)["estado"] == "ASOCIADO"
    _publicar_reporte(repo.raiz_atlas, [("0000361852", [envio])])

    registrar_eventos_canonicos_mobile(repo)

    estadia = _eventos(repo.raiz_atlas)[("TIENE_ESTADIA", "0000361852")]
    assert estadia["nota"] == "estadia a espera de firma" and estadia["estado_incidencia"] == "ESPERA_ESTADIA"


def test_guia_en_revision_sin_viaje_demostrado_no_genera_evento(operacion) -> None:
    repo, dataset = operacion
    envio = _guia_en_revision(repo, dataset, "475413", "0000362423")
    _publicar_reporte(repo.raiz_atlas, [("0000362423", ["otro-envio"])])  # 0 coincidencias

    assert registrar_eventos_canonicos_mobile(repo) == []
    assert reo.leer_eventos_operacionales(raiz=repo.raiz_atlas)["eventos"] == []
    assert repo.cargar(envio).get("eventos_canonicos") is None  # sin marca: reintentable

    _publicar_reporte(repo.raiz_atlas, [("0000362423", [envio]), ("0000362424", [envio])])  # 2 viajes: ambiguo
    assert registrar_eventos_canonicos_mobile(repo) == []
    assert reo.leer_eventos_operacionales(raiz=repo.raiz_atlas)["eventos"] == []


def test_guia_en_revision_con_transporte_asociado_distinto_al_viaje_no_genera_evento(operacion) -> None:
    repo, dataset = operacion
    envio = _guia_en_revision(repo, dataset, "475413", "0000362423")
    registro = repo.cargar(envio)
    registro["resultado_asociacion"] = {**registro["resultado_asociacion"], "numero_transporte": "0000999999"}
    repo.guardar(envio, registro)
    _publicar_reporte(repo.raiz_atlas, [("0000362423", [envio])])

    assert registrar_eventos_canonicos_mobile(repo) == []
    assert reo.leer_eventos_operacionales(raiz=repo.raiz_atlas)["eventos"] == []


def test_envio_en_revision_por_asociacion_ambigua_o_captura_no_genera_evento(operacion) -> None:
    repo, dataset = operacion
    ambiguo = _guia_en_revision(repo, dataset, "475413", "0000362423")
    registro = repo.cargar(ambiguo)
    registro["resultado_asociacion"] = {**registro["resultado_asociacion"], "estado": "PROPUESTA_REQUIERE_REVISION"}
    repo.guardar(ambiguo, registro)
    ilegible = _guia_en_revision(repo, dataset, "475414", "0000362425")
    registro = repo.cargar(ilegible)
    registro["problema_captura"] = True
    repo.guardar(ilegible, registro)
    _publicar_reporte(repo.raiz_atlas, [("0000362423", [ambiguo]), ("0000362425", [ilegible])])

    assert registrar_eventos_canonicos_mobile(repo) == []
    assert reo.leer_eventos_operacionales(raiz=repo.raiz_atlas)["eventos"] == []


def test_estadia_en_guia_en_revision_con_viaje_demostrado_genera_evento(operacion) -> None:
    repo, dataset = operacion
    envio = _guia_en_revision(repo, dataset, "475419", "0000362421", tipos='["ESPERA_AUTORIZACION_ESTADIA"]')
    _publicar_reporte(repo.raiz_atlas, [("0000362421", [envio])])

    registrar_eventos_canonicos_mobile(repo)

    estadia = _eventos(repo.raiz_atlas)[("TIENE_ESTADIA", "0000362421")]
    assert estadia["estado_incidencia"] == "ESPERA_ESTADIA" and estadia["estado_gestion"] == "PENDIENTE_RESPUESTA"


def test_reintentos_de_guia_en_revision_no_duplican_eventos(operacion) -> None:
    repo, dataset = operacion
    envio = _guia_en_revision(repo, dataset, "475413", "0000362423", observacion="barro")
    _publicar_reporte(repo.raiz_atlas, [("0000362423", [envio])])
    registrar_eventos_canonicos_mobile(repo)
    revision_inicial = reo.leer_eventos_operacionales(raiz=repo.raiz_atlas)["revision"]

    assert registrar_eventos_canonicos_mobile(repo) == []  # ya marcado en el envío
    # aunque se pierda la marca del envío (reproceso), la clave de idempotencia evita el duplicado
    registro = repo.cargar(envio)
    registro.pop("eventos_canonicos")
    repo.guardar(envio, registro)
    (salida,) = registrar_eventos_canonicos_mobile(repo)
    assert salida["eventos"]["DEVOLUCION_TOTAL"]["resultado"] == "EXISTENTE"

    eventos = reo.leer_eventos_operacionales(raiz=repo.raiz_atlas)
    assert len(eventos["eventos"]) == 1 and eventos["revision"] == revision_inicial
    # y si más tarde el envío converge a ASOCIADO, tampoco se repite
    registro = repo.cargar(envio)
    registro["estado"] = "ASOCIADO"
    repo.guardar(envio, registro)
    assert registrar_eventos_canonicos_mobile(repo) == []
    assert len(reo.leer_eventos_operacionales(raiz=repo.raiz_atlas)["eventos"]) == 1


def test_incidencia_y_pendiente_tecnico_independiente_conviven(operacion) -> None:
    repo, dataset = operacion
    envio = _guia_en_revision(repo, dataset, "475413", "0000362423")
    _publicar_reporte(repo.raiz_atlas, [("0000362423", [envio])])
    antes = repo.cargar(envio)
    fila_antes = next(f for f in _filas(dataset) if f["archivo"] == f"mobile/{envio}/original.jpg")

    registrar_eventos_canonicos_mobile(repo)

    despues = repo.cargar(envio)
    assert ("DEVOLUCION_TOTAL", "0000362423") in _eventos(repo.raiz_atlas)
    # el pendiente documental sigue intacto: ni el envío ni la fila cambian de estado
    assert despues["estado"] == "REQUIERE_REVISION"
    assert despues["resultado_asociacion"] == antes["resultado_asociacion"]
    fila_despues = next(f for f in _filas(dataset) if f["archivo"] == f"mobile/{envio}/original.jpg")
    assert fila_despues == fila_antes
    assert fila_despues["indicador_revision"] == "REVISAR"
    assert fila_despues["motivos_revision_documento"] == "OBRA_DESTINO_SIN_CORROBORAR"
