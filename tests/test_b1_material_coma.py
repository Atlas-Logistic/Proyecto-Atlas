"""B1 -- coma opcional tras "es" en la corrección de material (caso real
484418: "… es, ROLLO HORMIGON 10MM A630-420H (N)" quedaba no reconocida).
La descripción se conserva íntegra; el resto de las intenciones no cambia.
Sólo interpretación determinista: sin datos, OCR ni escritura."""
from __future__ import annotations

import pytest

from atlas_core.b1_operador import interpretar_determinista

MATERIAL = "ROLLO HORMIGON 10MM A630-420H (N)"


@pytest.mark.parametrize("texto", [
    f"El material de la guía 484418 es, {MATERIAL}",
    f"El material de la guía 484418 es {MATERIAL}",
    f"El material de la guía 484418 es,{MATERIAL}",
    f"El material de la guía 484418 es , {MATERIAL}",
    f"el material de la guia 484418 ES,  {MATERIAL}.",
    f"El material correcto de la guía 484418 es, {MATERIAL}",
    f"El material de la guía 484418 debe ser, {MATERIAL}",
    f"El material de la guía 484418 corresponde a, {MATERIAL}",
    f"Material de la guía 484418: {MATERIAL}",
])
def test_coma_opcional_tras_es_conserva_la_descripcion_integra(texto):
    intencion = interpretar_determinista(texto)
    assert intencion is not None and intencion.accion == "DOCUMENTO_CORREGIR_CAMPO", texto
    assert intencion.parametros == {"numero_guia": "484418", "campo": "descripcion_material",
                                    "valor": MATERIAL, "referencia": " ".join(texto.split())}


def test_comas_internas_de_la_descripcion_se_conservan():
    intencion = interpretar_determinista("El material de la guía 484418 es, ROLLO 10MM, A630-420H (N)")
    assert intencion.parametros["valor"] == "ROLLO 10MM, A630-420H (N)"


def test_es_no_se_separa_de_la_palabra_siguiente():
    # "ESTRIBO" no es "ES" + "TRIBO": sin espacio ni coma no hay corrección.
    intencion = interpretar_determinista("El material de la guía 484418 ESTRIBO 10MM")
    assert intencion is None or intencion.parametros.get("valor") != "TRIBO 10MM"
    assert intencion is None or intencion.accion != "DOCUMENTO_CORREGIR_CAMPO"


@pytest.mark.parametrize("texto", [
    "El material de la guía 484418 es,",
    "El material de la guía 484418 es, ",
    "El material de la guía 484418 es,,",
    "El material de la guía 484418 es, .",
    "El material de la guía 484418, ROLLO HORMIGON 10MM",
    "¿El material de la guía 484418 es, ROLLO HORMIGON 10MM?",
])
def test_sin_descripcion_o_pregunta_no_es_correccion(texto):
    intencion = interpretar_determinista(texto)
    assert intencion is None or intencion.accion != "DOCUMENTO_CORREGIR_CAMPO", (texto, intencion)


@pytest.mark.parametrize("texto", ["El peso de la guía 484418 es, 12.450 kg", "En la guía 484418, el peso es, 12450"])
def test_peso_no_cambia_con_esta_correccion(texto):
    # Fuera de alcance: el separador de peso sigue sin admitir la coma.
    intencion = interpretar_determinista(texto)
    assert intencion is None or intencion.parametros.get("campo") != "peso_kg"
