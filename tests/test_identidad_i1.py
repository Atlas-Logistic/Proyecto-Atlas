"""Bloque IDENTIDAD I1: auditoría de normalizaciones hardcodeadas de
identidad en `atlas_core/extractor.py`.

Principio: el extractor base debe extraer lo que dice el documento. No
debe convertir silenciosamente "CONSTRUCTORA SIGRO SA" en "EMPRESA CONST
SIGRO" solo porque ambas contienen "SIGRO" -- caso real que lo demostró
incorrecto: guía 383295 (ver docs/BITACORA_TECNICA_CRONOLOGICA.md, bloque
ESTADOS S2.2).

Reglas retiradas (sin evidencia de que hicieran falta, o con evidencia de
que producían un valor incorrecto):
- `normalizar_obra_destino`: SIGRO, POCURO, AMERICAN SCREW ya no
  reescriben la identidad -- solo limpian formato.
- `buscar_obra_destino`: el fallback POCURO/SIGRO ya no adivina un nombre
  de empresa con solo la subcadena en cualquier parte del documento.
- `buscar_cliente`: los atajos AMERICAN SCREW/PRODALA*/ACMA que
  devolvían de inmediato un cliente sin pasar por el campo SEÑOR(ES) real.
- `buscar_rut_cliente` (ACMA): el fallback que aceptaba "92"/"190" como
  evidencia con solo aparecer en cualquier parte del documento.
- `buscar_rut_chofer`: el fallback sin comentario que asignaba el RUT
  "18098153-5" con solo esa cadena de dígitos en cualquier parte.

Reglas conservadas (evidencia real de que hacen falta, sin evidencia de
daño):
- `normalizar_cliente`: PRODALA*/AMERICAN SCREW/ACMA -- aplicadas sobre
  el valor YA capturado del campo SEÑOR(ES) real, no sobre el documento
  entero. Evidencia real (CSV masivo, `estado_revision_eval/`): 21
  variantes de OCR distintas de "PRODALAM" (PRODALAK, PRODALAX, PRODALAY,
  etc.), un solo RUT real detrás (93.772.000, `empresas.json`).
- `buscar_obra_destino`: fallback AMERICAN SCREW -- evidencia real (guía
  histórica 462474, `tests/test_atlas.py`) de un layout con "OBRA
  DESTINO" y su valor en bloques de OCR completamente separados, sin
  ningún candidato capturable por el regex de layout.
- `normalizar_chofer`: "PAIRICIO"->"PATRICIO" -- corrección OCR de un
  solo carácter sobre un nombre ya identificado como campo chofer, no
  una sustitución de identidad.
"""
from atlas_core.extractor import extraer_datos


def _textos_base(**overrides):
    base = {
        "encabezado": "ACEROS AZA S.A GUIA DE DESPACHO ELECTRONICA N 999999",
        "senor": "SEÑOR(ES) : CLIENTE GENERICO SA RUT : 11.111.111-1 GIRO",
        "obra": "OBRA DESTINO",
        "obra_valor": "CANTIDAD",
    }
    base.update(overrides)
    return list(base.values())


# --- SIGRO: caso real 383295 -- el extractor NO debe reescribir la identidad ---

def test_sigro_obra_destino_documental_no_se_reescribe():
    """Regresión obligatoria (guía 383295, Fase H): el campo OBRA DESTINO
    trae "CONSTRUCTORA SIGRO SA" -- el extractor debe conservarlo, no
    convertirlo en "EMPRESA CONST SIGRO"."""
    textos = [
        "ACEROS AZA S.A GUIA DE DESPACHO ELECTRONICA N 383295",
        "SEÑOR(ES) : SALOMON SACK SA RUT : 90.970.000-0 GIRO",
        "OBRA DESTINO CONSTRUCTORA SIGRO SA COD DESTINATARIO",
        "CANTIDAD",
    ]
    datos = extraer_datos(textos)
    assert datos["obra destino"] == "CONSTRUCTORA SIGRO SA"
    assert datos["obra destino"] != "EMPRESA CONST SIGRO"


def test_sigro_sin_campo_obra_destino_capturable_se_abstiene():
    """Sin un valor real capturable en el campo OBRA DESTINO (a diferencia
    de AMERICAN SCREW, sin evidencia real de que un fallback por
    subcadena para SIGRO haga falta), el extractor se abstiene en vez de
    adivinar."""
    textos = [
        "ACEROS AZA S.A GUIA DE DESPACHO ELECTRONICA N 111111",
        "SEÑOR(ES) : OTRO CLIENTE SA RUT : 11.111.111-1 GIRO",
        "menciona SIGRO en otra parte del documento sin ser el campo",
        "CANTIDAD",
    ]
    datos = extraer_datos(textos)
    assert datos["obra destino"] == "No encontrado"


# --- POCURO: mismo criterio que SIGRO -- no hay evidencia de que el ---
# --- fallback por subcadena haga falta, se retira igual ---

def test_pocuro_sin_campo_obra_destino_capturable_se_abstiene():
    textos = [
        "ACEROS AZA S.A GUIA DE DESPACHO ELECTRONICA N 222222",
        "SEÑOR(ES) : OTRO CLIENTE SA RUT : 11.111.111-1 GIRO",
        "menciona POCURO en otra parte del documento sin ser el campo",
        "CANTIDAD",
    ]
    datos = extraer_datos(textos)
    assert datos["obra destino"] == "No encontrado"


def test_pocuro_obra_destino_documental_se_conserva_tal_cual():
    textos = [
        "ACEROS AZA S.A GUIA DE DESPACHO ELECTRONICA N 222223",
        "SEÑOR(ES) : OTRO CLIENTE SA RUT : 11.111.111-1 GIRO",
        "OBRA DESTINO CONSTRUCTORA POCURO SPA COD DESTINATARIO",
        "CANTIDAD",
    ]
    datos = extraer_datos(textos)
    assert datos["obra destino"] == "CONSTRUCTORA POCURO SPA"


# --- AMERICAN SCREW: única regla de fallback por subcadena conservada, ---
# --- con evidencia real de que hace falta (guía histórica 462474) ---

def test_american_screw_layout_scrambleado_sigue_resuelto_por_fallback_acotado():
    """No regresión: reproduce el patrón real de la guía 462474
    (`tests/test_atlas.py`) -- "OBRA DESTINO" y su valor en bloques de
    OCR separados, sin match posible del regex de layout."""
    textos = [
        "Código Cliente 0001000197 FECHA DE EMISIÓN 03-07-2026 SEÑOR(ES) AMERICAN SCREW CHILE SPA RUT 91.410.000 GIRO",
        "ORDEN DE COMPRA SOLICITANTE TELEFONO OBRA DESTINO COD DESTINATARIO HORA ENTRADA HORA SALIDA Nro. TRANSPORTE",
        "AMERICAN SCREW CHILE SPA 0001000197 06:59 00 09:30 : 10 0000346352",
        "CANTIDAD",
    ]
    datos = extraer_datos(textos)
    assert datos["obra destino"] == "AMERICAN SCREW CHILE SPA"


def test_american_screw_obra_destino_documental_directa_sigue_funcionando():
    textos = [
        "ACEROS AZA S.A GUIA DE DESPACHO ELECTRONICA N 333333",
        "SEÑOR(ES) : AMERICAN SCREW CHILE SPA RUT : 91.410.000-3 GIRO",
        "OBRA DESTINO AMERICAN SCREW CHILE SPA COD DESTINATARIO",
        "CANTIDAD",
    ]
    datos = extraer_datos(textos)
    assert datos["obra destino"] == "AMERICAN SCREW CHILE SPA"
    assert datos["cliente"] == "AMERICAN SCREW CHILE SPA"


# --- PRODALA/PRODALAM: corrección OCR conservada -- 21 variantes reales ---
# --- distintas confirmadas en el CSV masivo, un solo RUT real detrás ---

def test_prodala_variante_ocr_se_corrige_via_campo_cliente_ya_capturado():
    textos = [
        "ACEROS AZA S.A GUIA DE DESPACHO ELECTRONICA N 444444",
        "SEÑOR(ES) : PRODALAK SA CORONEL RUT : 93.772.000-9 GIRO",
        "OBRA DESTINO PLANTA CORONEL COD DESTINATARIO",
        "CANTIDAD",
    ]
    datos = extraer_datos(textos)
    assert datos["cliente"] == "PRODALAM SA"


def test_prodala_layout_scrambleado_sigue_resuelto_por_fallback_acotado():
    """No regresión: reproduce el patrón real de la guía 464493 -- el
    campo SEÑOR(ES) no queda capturable por el regex de layout (label no
    leído limpiamente por el OCR), pero "PRODALAM SA" sí aparece en el
    texto -- a diferencia de SIGRO/POCURO (sin evidencia de que un
    fallback por subcadena haga falta), PRODALA* SÍ tiene evidencia real
    de que hace falta (128 apariciones reales en el CSV masivo, un solo
    RUT real detrás) y se conserva, acotado a esta empresa."""
    textos = [
        "ACEROS AZA S.A GUIA DE DESPACHO ELECTRONICA N 464493",
        "Código Cliente 0001003518 : PRODALAM SA",
        "OBRA DESTINO EMPRESA CONST SIGRO COD DESTINATARIO",
        "CANTIDAD",
    ]
    datos = extraer_datos(textos)
    assert datos["cliente"] == "PRODALAM SA"


# --- ACMA: conservado (regex \b, contextualmente acotado dentro de ---
# --- SEÑOR(ES)...RUT), fallback débil de RUT retirado ---

def test_acma_cliente_via_campo_senor_real_sigue_funcionando():
    textos = [
        "ACEROS AZA S.A GUIA DE DESPACHO ELECTRONICA N 555555",
        "SEÑOR(ES) : ACMA RUT : 92.190.000-7 GIRO",
        "OBRA DESTINO PLANTA ACMA COD DESTINATARIO",
        "CANTIDAD",
    ]
    datos = extraer_datos(textos)
    assert datos["cliente"] == "ACMA SA"


def test_acma_rut_sin_patron_industrias_se_abstiene_en_vez_de_adivinar():
    """El fallback retirado aceptaba "92" y "190" como evidencia con solo
    aparecer en cualquier parte del documento (subcadenas de 2-3 dígitos,
    sin relación posicional con ACMA) -- ahora, sin el patrón contextual
    "ACMA ... INDUSTRIAS", se abstiene."""
    textos = [
        "ACEROS AZA S.A GUIA DE DESPACHO ELECTRONICA N 555556",
        "SEÑOR(ES) : ACMA RUT GIRO",
        "FOLIO 92 FECHA 19-0 TELEFONO 190",
        "CANTIDAD",
    ]
    datos = extraer_datos(textos)
    assert datos["RUT del cliente"] == "No encontrado"


# --- RUT chofer: fallback sin comentario retirado ---

def test_rut_chofer_sin_etiqueta_no_se_asigna_por_coincidencia_de_digitos():
    """El fallback retirado asignaba "18098153-5" con solo esa cadena de
    8 dígitos en cualquier parte del documento (podría ser un folio, un
    teléfono, un número SAP). Sin la etiqueta "RUT CHOFER" ni el patrón
    "PDTE", se abstiene."""
    textos = [
        "ACEROS AZA S.A GUIA DE DESPACHO ELECTRONICA N 666666",
        "SEÑOR(ES) : CLIENTE GENERICO SA RUT : 11.111.111-1 GIRO",
        "Numero SAP 18098153",
        "CANTIDAD",
    ]
    datos = extraer_datos(textos)
    assert datos["RUT del chofer"] == "No encontrado"


def test_rut_chofer_con_etiqueta_real_sigue_funcionando():
    textos = [
        "ACEROS AZA S.A GUIA DE DESPACHO ELECTRONICA N 666667",
        "SEÑOR(ES) : CLIENTE GENERICO SA RUT : 11.111.111-1 GIRO",
        "RUT CHOFER :18098153-5",
        "CANTIDAD",
    ]
    datos = extraer_datos(textos)
    assert datos["RUT del chofer"] == "18098153-5"
