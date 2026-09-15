"""Contrato del núcleo puro de deduplicación, aún sin integración de ingesta."""
from __future__ import annotations

from io import BytesIO

import pytest
from PIL import Image

from atlas_core.deduplicacion_ingesta import (
    ClasificacionDuplicado,
    EntradaLedgerIngesta,
    EvidenciaIngesta,
    HuellaPerceptual,
    clasificar_ingesta,
    entrada_ledger_desde_dict,
    hash_perceptual,
    sha256_binario,
    validar_ledger_ingestas,
)


def _png(pixeles):
    imagen = Image.new("L", (9, 8))
    imagen.putdata(pixeles)
    salida = BytesIO()
    imagen.save(salida, format="PNG")
    return salida.getvalue()


def _jpeg(pixeles):
    imagen = Image.new("L", (9, 8))
    imagen.putdata(pixeles)
    salida = BytesIO()
    imagen.save(salida, format="JPEG", quality=95)
    return salida.getvalue()


def _evidencia(identificador, contenido, *, guia="", transporte="", perceptual=True):
    return EvidenciaIngesta(
        ingesta_id=identificador, nombre_archivo=f"{identificador}.jpeg",
        imagen_sha256=sha256_binario(contenido), numero_guia=guia,
        numero_transporte=transporte,
        perceptual=hash_perceptual(contenido) if perceptual else None,
    )


def test_mismo_binario_con_nombre_diferente_es_duplicado_exacto():
    contenido = _png([0, 255] * 36)
    existente = _evidencia("primera", contenido)
    candidata = _evidencia("renombrada", contenido)

    assert clasificar_ingesta(candidata, [existente]) is ClasificacionDuplicado.DUPLICADO_EXACTO


def test_imagen_distinta_no_se_rechaza_solo_por_misma_guia_y_transporte():
    primera = _evidencia("primera", _png([0] * 72), guia="123456", transporte="0000123456", perceptual=False)
    segunda = _evidencia("segunda", _png([255] * 72), guia="123456", transporte="0000123456", perceptual=False)

    assert clasificar_ingesta(segunda, [primera]) is ClasificacionDuplicado.NUEVO


def test_hash_perceptual_por_si_solo_solo_propone_candidato():
    contenido_a = _png([0, 255] * 36)
    contenido_b = _png([0, 255] * 36) + b"metadato-distinto"
    existente = _evidencia("primera", contenido_a)
    candidata = _evidencia("segunda", contenido_b)

    assert candidata.imagen_sha256 != existente.imagen_sha256
    assert clasificar_ingesta(candidata, [existente]) is ClasificacionDuplicado.CANDIDATO_DUPLICADO


def test_mismo_numero_guia_sin_evidencia_suficiente_no_elimina_documento():
    primera = _evidencia("primera", _png(list(range(72))), guia="472238", transporte="0000350001", perceptual=False)
    segunda = _evidencia("segunda", _png(list(reversed(range(72)))), guia="472238", transporte="0000350001", perceptual=False)

    assert clasificar_ingesta(segunda, [primera]) is ClasificacionDuplicado.NUEVO


def test_ledger_exige_canonica_para_duplicado_confirmado_y_referencias_existentes():
    canonica = EntradaLedgerIngesta(
        "uno", "uno.jpeg", "a" * 64, ClasificacionDuplicado.NUEVO,
    )
    duplicada = EntradaLedgerIngesta(
        "dos", "dos.jpeg", "b" * 64, ClasificacionDuplicado.DUPLICADO_CONFIRMADO,
        ingesta_canonica_id="uno", motivo="revision_humana",
    )

    validar_ledger_ingestas([canonica, duplicada])
    with pytest.raises(ValueError, match="canónica"):
        validar_ledger_ingestas([EntradaLedgerIngesta(
            "tres", "tres.jpeg", "c" * 64, ClasificacionDuplicado.DUPLICADO_CONFIRMADO,
        )])


def test_ledger_deserializa_y_valida_version_de_hash_perceptual():
    entrada = entrada_ledger_desde_dict({
        "ingesta_id": "uno", "nombre_archivo": "uno.jpeg", "imagen_sha256": "a" * 64,
        "clasificacion": "NUEVO", "perceptual": {"version": "dhash-v1", "valor_hex": "00ff"},
    })

    assert entrada.perceptual == HuellaPerceptual("dhash-v1", "00ff")


def test_hash_perceptual_es_determinista_para_jpeg_y_png():
    pixeles = [0, 255] * 36

    assert hash_perceptual(_png(pixeles)) == hash_perceptual(_png(pixeles))
    assert hash_perceptual(_jpeg(pixeles)) == hash_perceptual(_jpeg(pixeles))


def test_hash_perceptual_reporta_bytes_no_imagen_con_error_controlado():
    with pytest.raises(ValueError, match="imagen válida"):
        hash_perceptual(b"no es una imagen")
