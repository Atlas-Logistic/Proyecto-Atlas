"""Bloque OPERACIÓN O1.2: corrección dirigida de peso y hora salida.

Corrige exclusivamente los 2 patrones demostrados por la validación ciega
independiente de O1.1 (16 guías reales, ver docs/BITACORA_TECNICA_CRONOLOGICA.md):

1. HORA: el OCR a veces pega un dígito extra al inicio de un valor horario
   ("112:15:18" en vez de "12:15:18"). El extractor anterior podía
   "rescatar" un sub-match con forma válida pero equivocada dentro de ese
   token corrupto. Ahora exige que el tramo MAXIMAL de dígitos/dos-puntos
   calce completo con un horario válido (00-23/00-59/00-59) -- nunca un
   sub-match -- y nunca emite una hora fuera de rango.

2. PESO: "PESO KG" puede estar separado de su valor por una línea no
   relacionada intercalada (caso real: "ENTREGA 06.08 08:00 AM"). Ahora
   se busca dentro de una ventana corta y controlada, exigiendo que haya
   exactamente un candidato con forma de peso chileno -- ante ambigüedad,
   abstención.

NO se introdujo ninguna regla específica por archivo/guía. El caso
464367 (dígito OCR equivocado dentro de un valor por lo demás bien
formado, "27.410,00" vs real "27.610,00") queda documentado como
ERROR_OCR -- el extractor reproduce fielmente lo que el OCR entregó, y
no existe una señal general (sin acoplarse a esta guía específica) para
detectarlo sin arriesgar cobertura en otros casos reales.
"""
from atlas_core.extractor import extraer_datos

ENCABEZADO = [
    "ACEROS AZA S.A GUIA DE DESPACHO ELECTRONICA N 464170",
    "SEÑOR(ES) : EBEMA SA",
]


def _con_horas(entrada_cruda: str, salida_cruda: str) -> list[str]:
    return ENCABEZADO + ["HORA ENTRADA", entrada_cruda, "HORA SALIDA", salida_cruda, "CANTIDAD"]


# --- 1: horario limpio, sin corrupción ---

def test_horario_limpio_valido():
    datos = extraer_datos(_con_horas(":09:40:00", ":11:14:08"))
    assert datos["hora de entrada"] == "09:40"
    assert datos["hora de salida"] == "11:14"


# --- 2: dígito extra pegado al inicio no produce un sub-match ---

def test_digito_extra_al_inicio_no_produce_submatch():
    # Caso real (guías 464264 y 463630): "112:15:18" -- nunca debe
    # devolver "12:15" ni "15:18", debe abstenerse para esa hora.
    datos = extraer_datos(_con_horas(":09:32:00", ":112:15:18"))
    assert datos["hora de salida"] == "No encontrado"
    assert datos["hora de salida"] != "12:15"
    assert datos["hora de salida"] != "15:18"


# --- 3: dígito extra pegado al final tampoco produce sub-match ---

def test_digito_extra_al_final_no_produce_submatch():
    datos = extraer_datos(_con_horas(":09:32:00", ":12:15:181"))
    assert datos["hora de salida"] == "No encontrado"
    assert datos["hora de salida"] != "12:15"


# --- 4: hora fuera de rango (>23) se rechaza ---

def test_hora_mayor_a_23_rechazada():
    # Caso real (guía 463630): "112:29:55" -- un sub-match ingenuo
    # produciría "29:55" (hora inválida). Nunca debe emitirse.
    datos = extraer_datos(_con_horas(":10:05:00", ":112:29:55"))
    assert datos["hora de salida"] == "No encontrado"
    assert datos["hora de salida"] != "29:55"


# --- 5: minutos fuera de rango (>59) se rechazan ---

def test_minutos_mayor_a_59_rechazados():
    datos = extraer_datos(_con_horas(":09:32:00", ":12:75:00"))
    assert datos["hora de salida"] == "No encontrado"


# --- 6: segundos fuera de rango (>59) se rechazan ---

def test_segundos_mayor_a_59_rechazados():
    datos = extraer_datos(_con_horas(":09:32:00", ":12:15:75"))
    assert datos["hora de salida"] == "No encontrado"


# --- 6b/6c: corrupción de SALIDA con ENTRADA duplicada en la ventana --
# no debe "recuperarse" reutilizando el valor de ENTRADA ---

def test_salida_corrupta_con_entrada_duplicada_no_reutiliza_entrada():
    # Caso real guía 464264: el layout AZA repite el valor de ENTRADA
    # justo tras la etiqueta "HORA SALIDA" (bug de layout ya conocido,
    # ver comentario Bloque O1), y el valor real de SALIDA aparece más
    # adelante en la misma ventana pero corrupto ("112:15:18"). El
    # fallback "asumir ENTRADA == SALIDA" NO debe activarse aquí -- hay
    # evidencia de corrupción, así que corresponde abstenerse, nunca
    # reutilizar 09:32 como si fuera la salida real.
    textos = ENCABEZADO + [
        "HORA ENTRADA", ":09:32:00", "COMUNA", ": QUILICURA",
        "HORA SALIDA", ":09:32:00", "PESO KG.", ":112:15:18", "CANTIDAD",
    ]
    datos = extraer_datos(textos)
    assert datos["hora de entrada"] == "09:32"
    assert datos["hora de salida"] == "No encontrado"
    assert datos["hora de salida"] != "09:32"


def test_entrada_igual_salida_sin_corrupcion_se_acepta():
    # Caso real confirmado (guía 387789, ver auditoría O1): cuando de
    # verdad no hay ningún otro token horario -- ni siquiera uno
    # corrupto -- en la ventana de SALIDA, se acepta que coincida con
    # ENTRADA en vez de abstenerse (no hay evidencia de que exista un
    # valor distinto que se esté perdiendo).
    textos = ENCABEZADO + [
        "HORA ENTRADA", ":11:21:00", "COMUNA", ": QUILICURA",
        "HORA SALIDA", ":11:21:00", "CANTIDAD",
    ]
    datos = extraer_datos(textos)
    assert datos["hora de entrada"] == "11:21"
    assert datos["hora de salida"] == "11:21"


# --- 7/8: no regresión -- casos históricos reales de entrada/salida válidas ---

def test_no_regresion_entrada_valida_historica():
    # Caso real guía 383548 (D2/O1): valor real pegado a la etiqueta
    # vecina por scrambling de OCR, sin dígito corrupto -- debe seguir
    # resolviendo igual que antes de O1.2.
    textos = ENCABEZADO + [
        "HORA ENTRADA", ":0001001424", "COMUNA", ": QUILICURA",
        "HORA SALIDA", ":07:16:00", "Nro. TRANSPORTE", ":09:03:16", "CANTIDAD",
    ]
    datos = extraer_datos(textos)
    assert datos["hora de entrada"] == "07:16"


def test_no_regresion_salida_valida_historica():
    textos = ENCABEZADO + [
        "HORA ENTRADA", ":0001001424", "COMUNA", ": QUILICURA",
        "HORA SALIDA", ":07:16:00", "Nro. TRANSPORTE", ":09:03:16", "CANTIDAD",
    ]
    datos = extraer_datos(textos)
    assert datos["hora de salida"] == "09:03"


# --- 9: PESO KG directo (adyacente, sin línea intermedia) ---

def test_peso_kg_directo_sin_linea_intermedia():
    textos = ENCABEZADO + ["Tara : 16.940,000 Peso Bruto : 43.939,000", "PESO KG.", ":26.999,00"]
    datos = extraer_datos(textos)
    assert datos["peso"] == "26.999,00"


# --- 10: PESO KG con una línea intermedia no relacionada (caso real) ---

def test_peso_kg_con_linea_intermedia_valida():
    # Caso real guía 464264: "PESO KG." seguido de una línea de entrega
    # no relacionada, y solo después el valor real.
    textos = ENCABEZADO + [
        "Tara : 15.390,000 Peso Bruto : 32.540,000",
        "PESO KG.",
        "ENTREGA 06.08 08:00 AM",
        ":17.150,00",
    ]
    datos = extraer_datos(textos)
    assert datos["peso"] == "17.150,00"


# --- 11: múltiples candidatos con forma de peso en la ventana -> abstención ---

def test_multiples_candidatos_de_peso_en_ventana_abstiene():
    textos = ENCABEZADO + [
        "Tara : 15.390,000 Peso Bruto : 32.540,000",
        "PESO KG.",
        "REF 12.345,00 OTRO DATO",
        ":17.150,00",
    ]
    datos = extraer_datos(textos)
    assert datos["peso"] == "No encontrado"


# --- 12: no regresión de la política multiguía (peso/horas ya probada en O1) ---

def test_no_regresion_multiguia_horas_conflictivas_siguen_detectandose():
    from atlas_core.gestor_viajes import MotivoRevision, agrupar_viajes

    filas = [
        {"archivo": "a.jpg", "numero_transporte": "0000351135", "hora_entrada_aza": "09:32", "hora_salida_aza": "12:15"},
        {"archivo": "b.jpg", "numero_transporte": "0000351135", "hora_entrada_aza": "09:32", "hora_salida_aza": "15:18"},
    ]
    viajes, _ = agrupar_viajes(filas)
    assert MotivoRevision.CONFLICTO_HORA_SALIDA in viajes[0].motivos_revision
    assert viajes[0].hora_salida_aza == ""


# --- Documentación explícita del error OCR puro que queda sin corregir ---

def test_error_ocr_puro_no_se_corrige_por_heuristica_especifica():
    """Caso real guía 464367: el propio OCR lee un dígito equivocado
    dentro de un valor por lo demás limpio y sin corrupción estructural
    ("27.410,00" en vez de "27.610,00"). El extractor NO debe intentar
    adivinar/corregir esto -- reproduce fielmente el dígito que el OCR
    entregó, documentado como ERROR_OCR, no como falla del extractor."""
    textos = ENCABEZADO + ["Tara : 14.450,000 Peso Bruto : 42.060,000", "PESO KG.", ":27.410,00"]
    datos = extraer_datos(textos)
    assert datos["peso"] == "27.410,00"
