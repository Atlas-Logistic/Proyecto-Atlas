"""P0 04/11/2026: un número dentro del OCR nunca reemplaza la guía completa.

Hasta 7360b18, `extraer_datos` tenía siete reglas de desarrollo que fijaban
TODOS los campos (guía, transporte, cliente, obra, RUT, chofer, patentes,
horas y peso) cuando "461878", "462395", "462491", "462544", "462793",
"462833" o "462871" aparecía como subcadena en cualquier parte del texto. Un
número SAP, una orden de compra, una colada o un teléfono que lo contuviera
convertía una guía real en otra inventada.

Las lecturas son de guías operacionales reales (ingresadas desde el
22/09/2026; ninguna del lote inicial). Cada número se inserta dentro de los
campos no extraídos de esas lecturas y la extracción debe quedar idéntica a la
de la lectura original.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from atlas_core.extractor import extraer_datos

FIXTURE = Path(__file__).parent / "fixtures" / "guias_fijas" / "lecturas_operacionales.json"
DOCUMENTOS = json.loads(FIXTURE.read_text(encoding="utf-8"))["documentos"]

NUMEROS_RETIRADOS = ("461878", "462395", "462491", "462544", "462793", "462833", "462871")

# Valores que imponían las reglas retiradas y que no aparecen en ninguna de
# las lecturas operacionales del fixture.
VALORES_IMPUESTOS = {
    "número de transporte": {"0000346370", "0000347265", "0000347401", "0000345062",
                             "0000346760", "0000347469", "0000346245"},
    "obra destino": {"FERROLUSAC PEDRO DE OÑA", "DSI UNDERGROUND CHILE SPA",
                     "CONSTRUCTORA SAN CRISTOBAL LTDA", "HG CONSTRUCTORA SPA",
                     "CONST CERRO APOQUINDO CUATRO"},
    "chofer": {"CRISTOPHER RETAMAL", "SALOMÓN PIZARRO", "LEANDRO TOLEDO", "RODRIGO NAHUELÑIR"},
    "patente del tracto": {"BPHR67", "AL1879", "TG8925", "BKYK63", "SB6486"},
}

# Campo documental -> (patrón, reemplazo con el número dentro). Ninguno de
# estos campos se extrae como dato operacional.
SITIOS = {
    "numero_sap": (re.compile(r"(?<!\d)0080\d{6}(?!\d)"), lambda n: "0080" + n),
    "orden_compra": (re.compile(r"(?<!\d)(?:67\d{8}|0030\d{6})(?!\d)"),
                     lambda n: "6701" + n),
    "colada": (re.compile(r"(?i)(?<=coladas)(\s*:?\s*)\d{10}(?!\d)"),
               lambda n: r"\g<1>2617" + n),
    "codigo_material": (re.compile(r"(?<![\d.,])110\d{6}(?!\d)"), lambda n: "110" + n),
}


def _inyectar(lineas: list[str], sitio: str, numero: str) -> tuple[list[str], int]:
    if sitio == "observacion":
        return [*lineas, f"OBS CONTACTO 9{numero}55"], 1
    patron, reemplazo = SITIOS[sitio]
    total = 0
    salida = []
    for linea in lineas:
        nueva, cantidad = patron.subn(reemplazo(numero), linea)
        salida.append(nueva)
        total += cantidad
    return salida, total


@pytest.mark.parametrize("documento", DOCUMENTOS, ids=[d["numero_guia"] for d in DOCUMENTOS])
def test_numero_retirado_dentro_de_otro_campo_no_cambia_la_extraccion(documento):
    original = extraer_datos(documento["lineas"])
    sitios_usados = set()
    for sitio in (*SITIOS, "observacion"):
        for numero in NUMEROS_RETIRADOS:
            lineas, inyecciones = _inyectar(documento["lineas"], sitio, numero)
            if not inyecciones:
                continue
            sitios_usados.add(sitio)
            assert any(numero in linea for linea in lineas)
            modificada = extraer_datos(lineas)
            assert modificada == original, (documento["numero_guia"], sitio, numero)
    # Cada lectura real ejercita al menos dos campos además de la observación.
    assert len(sitios_usados - {"observacion"}) >= 2, (documento["numero_guia"], sitios_usados)


@pytest.mark.parametrize("documento", DOCUMENTOS, ids=[d["numero_guia"] for d in DOCUMENTOS])
def test_ningun_campo_toma_valores_de_las_reglas_retiradas(documento):
    for numero in NUMEROS_RETIRADOS:
        lineas = [*documento["lineas"], f"Numero SAP 0080{numero}", f"Coladas: 2617{numero}"]
        datos = extraer_datos(lineas)
        assert datos["número de guía"] not in NUMEROS_RETIRADOS, (documento["numero_guia"], numero)
        for campo, impuestos in VALORES_IMPUESTOS.items():
            assert datos[campo] not in impuestos, (documento["numero_guia"], numero, campo, datos[campo])


def test_el_numero_de_guia_propio_sigue_extrayendose_sin_completar_campos():
    """Una guía cuyo número coincide con uno retirado se lee como cualquier
    otra: el número sí, el resto solo si está en el texto."""
    datos = extraer_datos(["RUT: 92.176.000-0 GUIA DE DESPACHO ELECTRONICA N? 462491",
                           "Numero SAP 0080577916"])
    assert datos["número de guía"] == "462491"
    for campo in ("número de transporte", "cliente", "obra destino", "chofer",
                  "RUT del chofer", "patente del tracto", "peso"):
        assert datos[campo] == "No encontrado", (campo, datos)
