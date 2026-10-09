"""Comprobantes AZA: evidencia, nunca una guía ni un viaje."""
from __future__ import annotations

import csv
import uuid

from atlas_core.comprobantes_pesaje import extraer_comprobante_pesaje_aza, tickets_pesaje_para_desktop
from atlas_core.ingesta_pdf import leer_evidencias_adicionales
from atlas_core.mobile import RepositorioEnviosMobile, procesar_envio_mobile
from atlas_core.procesamiento_masivo import COLUMNAS


TEXTO_480997 = [
    "AZA CERTIFICADO DE PESOS", "Comprobante de Pesaje", "Unidad 1111 - AZA Colina",
    "Emisión 08.10.2026", "Patente SB6486", "Nro.Documento 480997",
    "Rut. Conductor 0154542973", "Nombre Conductor RODRIGO NAHUELÑIR",
    "Peso Neto 17.460 kg", "483436 33.340 kg BRUTO", "1000458096 15.880 kg TARA",
]


def _datos_ticket() -> dict:
    campos = extraer_comprobante_pesaje_aza(TEXTO_480997)
    assert campos is not None
    return {
        "tipo_documental": "COMPROBANTE_PESAJE", "comprobante_pesaje": campos,
        "indicador_revision": "OK", "estado_documental": "OK", "estado_operacional": "OK",
    }


def test_reconoce_y_extrae_comprobante_aza_480997() -> None:
    campos = extraer_comprobante_pesaje_aza(TEXTO_480997)
    assert campos == {
        "numero": "480997", "fecha": "08.10.2026", "planta": "1111 - AZA COLINA",
        "patente": "SB6486", "chofer": "RODRIGO NAHUELNIR", "rut_chofer": "0154542973",
        "peso_bruto_kg": "33340", "tara_kg": "15880", "peso_neto_kg": "17460",
    }


def test_no_basta_una_mencion_aislada_de_peso() -> None:
    assert extraer_comprobante_pesaje_aza(["PESO NETO 17460 KG", "GUIA DE DESPACHO"]) is None


def test_480997_se_guarda_como_evidencia_sin_fila_ni_revision(tmp_path) -> None:
    raiz = tmp_path / "atlas"
    dataset = raiz / "operacion" / "actual" / "analisis_completo_guias.csv"
    dataset.parent.mkdir(parents=True)
    with dataset.open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader()
        escritor.writerow({**{c: "" for c in COLUMNAS}, "archivo": "guia-480997.jpg", "numero_guia": "480997",
                           "numero_transporte": "0000363202", "patente_tracto": "SB6486",
                           "rut_chofer": "15.454.297-3", "chofer": "RODRIGO NAHUELNIR"})
    repo = RepositorioEnviosMobile(raiz)
    envio = str(uuid.uuid4())
    repo.recibir(envio_id=envio, imagen=b"ticket", mime="image/jpeg", metadata={"chofer_id": "154542973", "planta_origen_informada": "AZA_COLINA"})
    resultado = procesar_envio_mobile(repo, envio, dataset=dataset, procesador=lambda _: _datos_ticket())
    assert resultado["estado"] == "EVIDENCIA_ASOCIADA"
    assert resultado["tipo_documental"] == "COMPROBANTE_PESAJE"
    with dataset.open(encoding="utf-8-sig", newline="") as archivo:
        assert len(list(csv.DictReader(archivo, delimiter=";"))) == 1
    evidencias = leer_evidencias_adicionales(raiz / "operacion" / "evidencia_pdf")
    assert len(evidencias) == 1
    assert evidencias[0]["documento"]["numero_guia"] == "480997"
    assert evidencias[0]["evidencia"]["tipo_documental"] == "COMPROBANTE_PESAJE"
    assert tickets_pesaje_para_desktop(evidencias) == [{
        "archivo": f"mobile/{envio}/original.jpg", "numero_guia": "480997", "numero_transporte": "0000363202",
        "campos": resultado["comprobante_pesaje"]["campos"], "motivo_asociacion": "COMPROBANTE_PESAJE_AZA",
    }]


def test_ticket_sin_identidad_suficiente_queda_pendiente_no_revision(tmp_path) -> None:
    raiz = tmp_path / "atlas"; raiz.mkdir(); dataset = raiz / "datos.csv"; dataset.write_text(";".join(COLUMNAS) + "\n", encoding="utf-8-sig")
    repo = RepositorioEnviosMobile(raiz); envio = str(uuid.uuid4())
    repo.recibir(envio_id=envio, imagen=b"ticket", mime="image/jpeg", metadata={"chofer_id": "x", "planta_origen_informada": "AZA_COLINA"})
    resultado = procesar_envio_mobile(repo, envio, dataset=dataset, procesador=lambda _: _datos_ticket())
    assert resultado["estado"] == "PENDIENTE_ASOCIACION"
    assert resultado["comprobante_pesaje"]["motivo"] == "SIN_COINCIDENCIA_INEQUIVOCA"
