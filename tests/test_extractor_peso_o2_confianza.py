"""Bloque O2 -- defensa evidencial contra un dígito espurio al inicio de
PESO KG, activada sólo con corroboración geométrica independiente de alta
confianza (nunca por heurística ciega -- ver `test_error_ocr_puro_no_se_
corrige_por_heuristica_especifica` en test_extractor_peso_horas_o1_2.py,
que sigue vigente y sin cambios: sin confianza baja + corroboración, un
dígito OCR equivocado no se toca).

Caso real que motiva este bloque: viaje 0000359510 (chofer SALOMÓN
PIZARRO, guías 474285/474286/474287, ver traza OCR real en
G:\\Mi unidad\\Atlas\\operacion\\trazas_ocr\\474285--*.json y
474287--*.json). EasyOCR leyó "19.307.00" (confianza 0.8249, real:
9.307,00) y "18.937,00" (confianza 0.9008, real: 8.937,00) -- ambos
exactamente +10.000 kg, con el resto del documento en confianza
0.93-0.9999. En ambos casos el valor correcto aparece, sin el "1" y con
confianza 0.999+, en otro bloque OCR independiente (columna de peso por
ítem junto a la descripción de material). 474286 (correcto, sin el "1")
sirve de control: no debe activar nada.
"""
from dataclasses import dataclass

from atlas_core.extractor import _reexaminar_peso_por_baja_confianza


@dataclass
class _BloqueFalso:
    texto: str
    confianza: float


# --- Caso real 474285: 19307 (confianza baja) corregido a 9307 por el
# bloque de item independiente "9.307110002945" (confianza alta) ---

def test_caso_real_474285_corrige_por_corroboracion_alta_confianza():
    bloques = [
        _BloqueFalso("9.307110002945", 0.9996),  # columna de peso por item
        _BloqueFalso("B HORMIGON 22HM 6H A630-420H (N)", 0.9329),
        _BloqueFalso("PESOKG.", 0.9507),
        _BloqueFalso("19.307.00", 0.8249),  # lectura de baja confianza, +10.000 espurio
        _BloqueFalso("Tara : 14.750,000 Peso Bruto : 24.057,000", 0.9336),
    ]
    valor, motivo = _reexaminar_peso_por_baja_confianza("19307", bloques)
    assert valor == "9307"
    assert motivo is not None
    assert "19307->9307" in motivo


# --- Caso real 474287: mismo patrón, 18937 -> 8937 ---

def test_caso_real_474287_corrige_por_corroboracion_alta_confianza():
    bloques = [
        _BloqueFalso("8.937110002927", 0.9997),
        _BloqueFalso("B HORMIGON 25MM 7M A630-420H (N)", 0.9906),
        _BloqueFalso("PESO KG.", 0.9888),
        _BloqueFalso("18.937,00", 0.9008),
        _BloqueFalso("Tara : 14.750,000 Peso Bruto : 23.687,000", 0.9778),
    ]
    valor, motivo = _reexaminar_peso_por_baja_confianza("18937", bloques)
    assert valor == "8937"
    assert motivo is not None


# --- Caso real 474286 (control, correcto de origen): nada que corregir,
# no debe activarse (el valor ni siquiera empieza con "1") ---

def test_caso_real_474286_control_no_activa_nada():
    bloques = [
        _BloqueFalso("PESO KG.", 0.9837),
        _BloqueFalso(":9.535.00", 0.97),
        _BloqueFalso("Tara : 14,750,000 Peso Bruto : 24.285,000", 0.9828),
    ]
    valor, motivo = _reexaminar_peso_por_baja_confianza("9535", bloques)
    assert valor == "9535"
    assert motivo is None


# --- Sin bloques (p. ej. estado_bloques NO_DISPONIBLES): no cambia nada ---

def test_sin_bloques_no_cambia_nada():
    valor, motivo = _reexaminar_peso_por_baja_confianza("19307", None)
    assert valor == "19307"
    assert motivo is None


# --- Confianza ALTA en el valor original: nunca se toca, aunque empiece
# con "1" y exista un valor recortado con forma de peso -- un peso real de
# 5 dígitos que empieza con 1 (caso histórico "14.270,000") no debe verse
# afectado sólo por tener esa forma ---

def test_confianza_alta_en_origen_nunca_se_corrige_aunque_empiece_con_1():
    bloques = [
        _BloqueFalso("PESO KG.", 0.99),
        _BloqueFalso("14.270,000", 0.995),  # lectura de ALTA confianza: es el peso real
        _BloqueFalso("4270", 0.999),  # coincidencia casual irrelevante, no debe usarse
    ]
    valor, motivo = _reexaminar_peso_por_baja_confianza("14270", bloques)
    assert valor == "14270"
    assert motivo is None


# --- Confianza baja pero SIN corroboración independiente: se abstiene,
# igual que el caso histórico 464367 (no se adivina sin evidencia) ---

def test_confianza_baja_sin_corroboracion_no_corrige_y_se_abstiene():
    bloques = [
        _BloqueFalso("PESO KG.", 0.95),
        _BloqueFalso("19.307.00", 0.80),
        # Ningún otro bloque con "9307" al inicio y confianza alta.
        _BloqueFalso("B HORMIGON 22HM 6H A630-420H (N)", 0.93),
    ]
    valor, motivo = _reexaminar_peso_por_baja_confianza("19307", bloques)
    assert valor == "19307"
    assert motivo is None


# --- La corroboración NUNCA puede venir de un bloque de Tara/Peso Bruto
# (evitaría reintroducir exactamente la confusión tara/bruto que este
# extractor ya rechaza en `buscar_peso`) ---

def test_corroboracion_nunca_toma_un_bloque_de_tara_o_bruto():
    bloques = [
        _BloqueFalso("PESO KG.", 0.95),
        _BloqueFalso("19.307.00", 0.80),
        # Un bloque de Tara/Bruto que por pura coincidencia empieza con
        # "9307" NO debe usarse como corroboración, aunque tenga confianza alta.
        _BloqueFalso("Tara : 9307,000 Peso Bruto : 24.057,000", 0.999),
    ]
    valor, motivo = _reexaminar_peso_por_baja_confianza("19307", bloques)
    assert valor == "19307"
    assert motivo is None


# --- Corroboración con confianza mediana (por debajo del umbral de
# corroboración) tampoco basta ---

def test_corroboracion_de_confianza_insuficiente_no_corrige():
    bloques = [
        _BloqueFalso("PESO KG.", 0.95),
        _BloqueFalso("19.307.00", 0.80),
        _BloqueFalso("9307", 0.95),  # por debajo de UMBRAL_CONFIANZA_COROBORACION_PESO (0.99)
    ]
    valor, motivo = _reexaminar_peso_por_baja_confianza("19307", bloques)
    assert valor == "19307"
    assert motivo is None


# --- Valor de 3 dígitos o menos: nunca se toca (no tiene forma de "1" +
# peso plausible más corto) ---

def test_valor_corto_no_se_toca():
    bloques = [_BloqueFalso("PESO KG.", 0.5), _BloqueFalso("150", 0.999)]
    valor, motivo = _reexaminar_peso_por_baja_confianza("150", bloques)
    assert valor == "150"
    assert motivo is None
