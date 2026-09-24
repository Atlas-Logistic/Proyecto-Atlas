"""Regresión: una asociación humana única prevalece sobre OCR incierto."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from atlas_core.atlas_ia.convergencia import CONTRADICCION_FUERTE, MANTENER_REVISION, RESOLVER_SILENCIOSO
from atlas_core.atlas_ia.evidencia_dominios import convergencia_vehiculo
from atlas_core.catalogo_vehiculos import TipoVehiculo, confirmar_vehiculo


RUT = "14.293.816-2"
FECHA = datetime(2026, 9, 21, tzinfo=timezone.utc)


def _catalogo(tmp_path):
    carpeta = tmp_path / "catalogos"
    carpeta.mkdir()
    (carpeta / "vehiculos.json").write_text(
        json.dumps({"version": 1, "vehiculos": []}), encoding="utf-8",
    )
    return carpeta


def _confirmar(carpeta, patente):
    confirmar_vehiculo(
        carpeta / "vehiculos.json", patente=patente, tipo=TipoVehiculo.CARRO,
        actor="TEST", fuente_decision="TEST", fecha=FECHA,
        rut_chofer_asociado=RUT,
    )


def _filas(valor):
    return [{
        "numero_guia": "1", "numero_transporte": "T-1", "rut_chofer": RUT,
        "patente_tracto": "DD2494", "patente_rampla": valor,
    }]


def test_confirmacion_unica_absorbe_ocr_de_un_caracter_y_preserva_el_original(tmp_path):
    carpeta = _catalogo(tmp_path)
    _confirmar(carpeta, "JB8529")

    resultado = convergencia_vehiculo(
        campo="patente_rampla", valor_documental="JBH529", rut_chofer=RUT,
        numero_transporte="T-1", filas=_filas("JBH529"), carpeta_catalogos=carpeta,
    )

    assert resultado.decision == RESOLVER_SILENCIOSO
    assert resultado.valor_canonico == "JB8529"
    assert resultado.valor_ocr_original == "JBH529"


def test_confirmacion_unica_no_evita_el_techo_de_distancia_ante_ocr_radicalmente_distinto(tmp_path):
    # Bloque P0 CONVERGENCIA VEHÍCULO -- esta prueba antes exigía
    # RESOLVER_SILENCIOSO aquí (título original: "...sin_usar_distancia_
    # como_conflicto"), asumiendo que una asociación humana ÚNICA bastaba
    # para ignorar la distancia OCR por completo. Eso es exactamente el
    # bloqueo P0 corregido: "JB8529" (confirmado) vs "ZZ0000" (documental)
    # tiene distancia 6 -- muy por encima del techo calibrado incluso con
    # ancla humana (`_DISTANCIA_MAXIMA_ANCLA_HUMANA = 2`). Una asociación
    # única SÍ absorbe OCR incierto (ver el test anterior, distancia 1),
    # pero nunca vuelve la distancia ilimitada: algo radicalmente distinto
    # exige revisión humana, nunca una corrección silenciosa.
    carpeta = _catalogo(tmp_path)
    _confirmar(carpeta, "JB8529")

    resultado = convergencia_vehiculo(
        campo="patente_rampla", valor_documental="ZZ0000", rut_chofer=RUT,
        numero_transporte="T-1", filas=_filas("ZZ0000"), carpeta_catalogos=carpeta,
    )

    assert resultado.decision == MANTENER_REVISION


def test_dos_asociaciones_humanas_plausibles_conservan_revision(tmp_path):
    carpeta = _catalogo(tmp_path)
    _confirmar(carpeta, "JB8529")
    _confirmar(carpeta, "JC8529")

    resultado = convergencia_vehiculo(
        campo="patente_rampla", valor_documental="ZZ0000", rut_chofer=RUT,
        numero_transporte="T-1", filas=_filas("ZZ0000"), carpeta_catalogos=carpeta,
    )

    assert resultado.decision == MANTENER_REVISION


def test_evidencia_visual_clara_de_otra_patente_si_conserva_revision(tmp_path):
    carpeta = _catalogo(tmp_path)
    _confirmar(carpeta, "JB8529")

    resultado = convergencia_vehiculo(
        campo="patente_rampla", valor_documental="AB1234", rut_chofer=RUT,
        numero_transporte="T-1", filas=_filas("AB1234"), carpeta_catalogos=carpeta,
        evidencia_visual_clara_distinta=True,
    )

    assert resultado.decision == CONTRADICCION_FUERTE
