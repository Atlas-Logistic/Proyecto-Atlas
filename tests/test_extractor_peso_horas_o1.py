"""Bloque OPERACIÓN O1: extracción de peso y horarios operacionales.

Semántica confirmada con evidencia real (30 guías con ground truth,
6 con errores de transcripción detectados y corregidos por verificación
visual directa contra la imagen -- ver docs/BITACORA_TECNICA_CRONOLOGICA.md):
"PESO KG" es el peso NETO operacional de la carga (no "PESO BRUTO",
camión+carga). HORA ENTRADA/HORA SALIDA son el ingreso/egreso real del
camión a AZA. Ambos extractores toleran el layout AZA real (etiquetas
fuera de orden, "." o "," confundidos como separador de miles) sin
inventar nunca un valor cuando la evidencia es insuficiente.
"""
from atlas_core.extractor import extraer_datos
from atlas_core.procesamiento_masivo import (
    _calcular_permanencia_minutos,
    _normalizar_peso_kg,
)

ENCABEZADO = [
    "ACEROS AZA S.A GUIA DE DESPACHO ELECTRONICA N 464170",
    "SEÑOR(ES) : EBEMA SA",
]


# --- PESO ---

def test_peso_normal_resuelve_desde_peso_kg():
    textos = ENCABEZADO + ["Tara : 16.940,000 Peso Bruto : 43.939,000", "PESO KG.", ":26.999,00"]
    datos = extraer_datos(textos)
    assert datos["peso"] == "26.999,00"
    assert _normalizar_peso_kg(datos["peso"]) == "26999"


def test_peso_con_separador_de_miles_confundido_por_ocr():
    # Caso real (guía 410265): el OCR lee "," donde el documento imprime
    # "." como separador de miles -- "6,971,00" en vez de "6.971,00".
    assert _normalizar_peso_kg("6,971,00") == "6971"
    assert _normalizar_peso_kg("15,119,00") == "15119"


def test_peso_ilegible_o_anchor_roto_abstiene():
    # Caso real (guías 387557/390376): el OCR pierde la "P" inicial de
    # "PESO KG" ("ESO KG.") -- el anchor no debe inventar coincidencias
    # parciales.
    textos = ENCABEZADO + ["Tara : 8.800,000 Peso Bruto : 20.775,000", "ESO KG.", ":11.975,00"]
    datos = extraer_datos(textos)
    assert datos["peso"] == "No encontrado"
    assert _normalizar_peso_kg(datos["peso"]) == "No encontrado"


def test_multiples_numeros_cercanos_ancla_al_peso_neto_no_al_bruto():
    # PESO BRUTO y TARA aparecen primero en el documento -- el extractor
    # nunca debe anclarse a ellos si PESO KG (el neto operacional) está
    # presente. Caso real confirmado: guía 462491, Peso Bruto=12.242,000
    # vs PESO KG real=3.282,00 (evidencia visual directa).
    textos = ENCABEZADO + [
        "Tara : 8.960,000 Peso Bruto : 12.242,000",
        "PESO KG.",
        ":3.282,00",
    ]
    datos = extraer_datos(textos)
    assert datos["peso"] == "3.282,00"


def test_peso_fuera_de_rango_plausible_se_descarta():
    # Caso real (guía 383755): el OCR inserta un dígito espurio
    # ("127.983,00" en vez de "27.983,00") -- la corrección numérica
    # resultante (127.983 kg) excede el rango operativo plausible de un
    # camión y se descarta en vez de propagarse.
    assert _normalizar_peso_kg("127.983,00") == "No encontrado"


# --- HORAS ---

def test_hora_entrada_valida():
    textos = ENCABEZADO + ["HORA ENTRADA", ":07:16:00", "HORA SALIDA", ":09:03:16"]
    datos = extraer_datos(textos)
    assert datos["hora de entrada"] == "07:16"


def test_hora_salida_valida():
    textos = ENCABEZADO + ["HORA ENTRADA", ":07:16:00", "HORA SALIDA", ":09:03:16"]
    datos = extraer_datos(textos)
    assert datos["hora de salida"] == "09:03"


def test_hora_trunca_segundos_a_formato_interno_hh_mm():
    textos = ENCABEZADO + ["HORA ENTRADA", ":14:53:00", "HORA SALIDA", ":15:53:21"]
    datos = extraer_datos(textos)
    assert datos["hora de entrada"] == "14:53"
    assert datos["hora de salida"] == "15:53"


def test_layout_con_etiquetas_fuera_de_orden_no_intercambia_horas():
    # Caso real (guía 383548): el valor real de HORA ENTRADA queda
    # pegado a la etiqueta "HORA SALIDA" (recuadros de Paddle fuera de
    # orden), con el valor real de salida apareciendo más adelante junto
    # a "Nro. TRANSPORTE". El extractor no debe devolver la misma hora
    # para ambos campos cuando existe una segunda hora distinta.
    textos = ENCABEZADO + [
        "HORA ENTRADA",
        ":0001001424",
        "COMUNA",
        ": QUILICURA",
        "HORA SALIDA",
        ":07:16:00",
        "Nro. TRANSPORTE",
        ":09:03:16",
        "CANTIDAD",
    ]
    datos = extraer_datos(textos)
    assert datos["hora de entrada"] == "07:16"
    assert datos["hora de salida"] == "09:03"


def test_hora_invalida_abstiene():
    textos = ENCABEZADO + ["HORA ENTRADA", "sin dato legible", "HORA SALIDA", "tampoco"]
    datos = extraer_datos(textos)
    assert datos["hora de entrada"] == "No encontrado"
    assert datos["hora de salida"] == "No encontrado"


def test_no_confunde_fecha_ni_nro_transporte_con_hora():
    textos = ENCABEZADO + [
        "FECHA DE EMISIÓN",
        ":04-08-2026",
        "HORA ENTRADA",
        ":09:40:00",
        "HORA SALIDA",
        ":11:14:08",
        "Nro. TRANSPORTE",
        ":0000351177",
        "CANTIDAD",
    ]
    datos = extraer_datos(textos)
    assert datos["hora de entrada"] == "09:40"
    assert datos["hora de salida"] == "11:14"


# --- PERMANENCIA ---

def test_permanencia_calculo_normal():
    assert _calcular_permanencia_minutos("08:10", "09:25") == "75"


def test_permanencia_salida_antes_de_entrada_sin_evidencia_no_determinada():
    assert _calcular_permanencia_minutos("23:50", "00:10") == "No determinada"


def test_permanencia_sin_horas_no_encontrado():
    assert _calcular_permanencia_minutos("No encontrado", "09:00") == "No encontrado"
    assert _calcular_permanencia_minutos("08:00", "No encontrado") == "No encontrado"
