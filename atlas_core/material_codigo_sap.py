"""Materiales AZA, fase 1: código SAP por ítem y señales de material OCR
no confiable.

Casos reales 482229 ("ROLLO HORNIOON 12HéE AE30-420N (N)", código leído
pegado a la cantidad "27,871110002701"), 473309 ("ROLLO HORMIGON 8MM
A630-420B (N)") y 474216 ("3 HORMIGON BM4 12H A630-420H (N)"): el material
ilegible se publicaba como dato confiable (estado OK sin motivo), y el código
SAP de la columna CODIGO -- la mejor evidencia del producto -- nunca se
extraía.

Este módulo SÓLO observa: nunca reemplaza, normaliza ni completa la
descripción. Devuelve, por ítem, el texto OCR original, el código SAP
asociado (si hay evidencia documental suficiente), la confianza OCR y las
señales que lo vuelven no confiable. Nada aquí es un catálogo: las
`referencias` código->descripción para detectar contradicciones las aporta
el llamador; sin ellas no se infiere ninguna.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass, field
from typing import Iterable, Mapping, Sequence

# Código SAP de producto AZA: 9 dígitos "1100xxxxx". El OCR suele pegarlo a
# la cantidad de la columna anterior ("27,871110002701" = 27,871 +
# 110002701), así que nunca se exige un límite a la izquierda; sí a la
# derecha (un dígito más ya no es este código).
_CODIGO_SAP = re.compile(r"1100\d{5}(?!\d)")

UMBRAL_CONFIANZA_MATERIAL = 0.80

SENAL_CARACTER_NO_ESPERADO = "CARACTER_NO_ESPERADO"
SENAL_FAMILIA_DEFORMADA = "FAMILIA_DEFORMADA"
SENAL_MEDIDA_DEFORMADA = "MEDIDA_DEFORMADA"
SENAL_CALIDAD_DEFORMADA = "CALIDAD_DEFORMADA"
SENAL_DETALLE_ILEGIBLE = "DETALLE_ILEGIBLE"
SENAL_CONFIANZA_BAJA = "CONFIANZA_OCR_BAJA"
SENAL_LARGO_DEFORMADO = "LARGO_DEFORMADO"
SENAL_NO_ES_MATERIAL = "FRAGMENTO_NO_MATERIAL"
SENAL_ENCABEZADO = "ENCABEZADO_DE_TABLA_EN_MATERIAL"
# Advertencia, no señal: caso real 475346 -- la descripción "18MM 12M" era
# correcta y el OCR leyó mal el CÓDIGO (110002938 -> "...936"). Una
# contradicción código/descripción sólo pide confirmar; por sí sola nunca
# vuelve no confiable el material.
ADVERTENCIA_CONTRADICCION_CODIGO = "CONTRADICCION_CODIGO_DESCRIPCION"

EVIDENCIA_MISMA_FILA = "MISMA_FILA_GEOMETRICA"
EVIDENCIA_UNICO_ITEM_TEXTO = "UNICO_ITEM_UNICO_CODIGO_TEXTO"
EVIDENCIA_AMBIGUA = "AMBIGUA"
EVIDENCIA_SIN_CODIGO = "SIN_CODIGO"

_FAMILIAS = ("HORMIGON", "ALAMBRON", "REDONDO", "ANGULO", "PLANA", "CUADRADO", "HEXAGONO", "CHATARRA", "ROLLO")
# Familias cuyos ítems AZA siempre declaran diámetro "<n>MM" y calidad
# "A630-420H"/"A440-280H" (con o sin S). Otras familias (perfiles,
# chatarra, SAFEROCK, alambrón SAE/AZA) no se juzgan por esa gramática.
_DIAMETRO = re.compile(r"(?<![A-Z0-9])\d{1,2}(?:,\d)?MM(?![A-Z])")
# Calidad legible aunque el OCR cambie el guion por espacio, pegue el largo
# ("6MA630-420H") o lea un cero como O ("A630-42OH"): un humano la lee sin
# ambigüedad. Una letra distinta (A630-420B/N/E/R, "4630", "AE30") no.
_CALIDAD_HORMIGON = re.compile(r"(?<![A-LN-Z0-9])A[\dO]{3}[\s-]?[\dO]{3}\s?HS?(?![A-Z0-9])")
_PALABRA = re.compile(r"[A-Z]+")


@dataclass
class ItemMaterialOCR:
    descripcion_ocr: str
    codigo_sap: str = ""
    evidencia_codigo: str = EVIDENCIA_SIN_CODIGO
    confianza_ocr: float | None = None
    senales: list[str] = field(default_factory=list)
    advertencias: list[str] = field(default_factory=list)

    @property
    def no_confiable(self) -> bool:
        return bool(self.senales)

    def como_dict(self) -> dict:
        return asdict(self)


def _sin_acentos(texto: str) -> str:
    valor = unicodedata.normalize("NFD", str(texto or ""))
    return "".join(c for c in valor if unicodedata.category(c) != "Mn").upper()


def codigos_sap_en_texto(texto: str) -> list[str]:
    """Códigos SAP del texto, separados de una cantidad pegada, sin repetir."""
    return list(dict.fromkeys(_CODIGO_SAP.findall(str(texto or ""))))


# --------------------------------------------------------------- geometría


def _caja(bloque) -> tuple[float, float, float, float] | None:
    caja = getattr(bloque, "bounding_box", None)
    if caja is None and isinstance(bloque, Mapping):
        caja = bloque.get("bounding_box")
    try:
        xs = [float(p[0]) for p in caja]
        ys = [float(p[1]) for p in caja]
    except (TypeError, ValueError, IndexError):
        return None
    return min(xs), min(ys), max(xs), max(ys)


def _texto(bloque) -> str:
    return str(getattr(bloque, "texto", None) if not isinstance(bloque, Mapping) else bloque.get("texto") or "")


def _confianza(bloque) -> float | None:
    valor = getattr(bloque, "confianza", None) if not isinstance(bloque, Mapping) else bloque.get("confianza")
    try:
        return float(valor)
    except (TypeError, ValueError):
        return None


def _tokens(texto: str) -> set[str]:
    return set(re.findall(r"[A-Z0-9]+", _sin_acentos(texto)))


def _bloque_del_item(item: str, bloques: Sequence) -> object | None:
    """El bloque OCR que contiene el ítem: mayor solapamiento de tokens, y
    al menos 60 % de los tokens del ítem (el extractor sólo recorta prefijos
    y membretes; nunca reescribe el ítem)."""
    tokens_item = _tokens(item)
    if not tokens_item:
        return None
    puntajes = []
    for bloque in bloques:
        comunes = len(tokens_item & _tokens(_texto(bloque)))
        if comunes / len(tokens_item) >= 0.6:
            puntajes.append((comunes, bloque))
    if not puntajes:
        return None
    puntajes.sort(key=lambda p: -p[0])
    if len(puntajes) > 1 and puntajes[0][0] == puntajes[1][0]:
        return None  # dos bloques igual de parecidos: no se elige
    return puntajes[0][1]


def _codigo_en_misma_fila(caja_item, bloques_codigo) -> tuple[str, str]:
    """Un código está en la fila del ítem si su centro vertical cae dentro
    de la altura del ítem (con media altura de holgura) y queda a su
    izquierda (columna CODIGO antes que DESCRIPCION)."""
    x0, y0, x1, y1 = caja_item
    alto = max(y1 - y0, 1.0)
    candidatos = set()
    for codigo, (cx0, cy0, cx1, cy1) in bloques_codigo:
        centro = (cy0 + cy1) / 2
        if y0 - alto / 2 <= centro <= y1 + alto / 2 and cx1 <= x0 + alto:
            candidatos.add(codigo)
    if len(candidatos) == 1:
        return candidatos.pop(), EVIDENCIA_MISMA_FILA
    return "", (EVIDENCIA_AMBIGUA if candidatos else EVIDENCIA_SIN_CODIGO)


# --------------------------------------------------------------- señales


def _distancia(a: str, b: str) -> int:
    anterior = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        actual = [i]
        for j, cb in enumerate(b, 1):
            actual.append(min(anterior[j] + 1, actual[j - 1] + 1, anterior[j - 1] + (ca != cb)))
        anterior = actual
    return anterior[-1]


def _familia_deformada(palabras: list[str]) -> bool:
    """Una palabra a 1-2 letras de una familia que NO aparece escrita bien
    ("HORNIOON" junto a un "ROLLO" correcto sigue siendo HORMIGON deformado)."""
    for palabra in palabras:
        if palabra in _FAMILIAS:
            continue
        for familia in (f for f in _FAMILIAS if f not in palabras):
            limite = 2 if len(familia) >= 7 else 1
            if abs(len(palabra) - len(familia)) <= limite and 0 < _distancia(palabra, familia) <= limite:
                return True
    return False


def _diametro_legible(texto: str) -> str:
    """Diámetro con dígitos limpios en la posición de medida (p. ej. el "12"
    de "12HéE"); vacío si no hay dígitos legibles."""
    m = _DIAMETRO.search(texto)
    if m:
        return m.group(0)[:-2]
    # Sólo dos dígitos limpios: "1DMM"/"1BMM" no dicen si es 10, 16 o 18.
    m = re.search(r"(?:HORMIGON|ALAMBRON|ROLLO\s+\S+)\s+(\d{2})(?=[A-Z])", texto)
    return m.group(1) if m else ""


def _largo_deformado(texto: str, diametro: re.Match) -> bool:
    """Barra (no rollo): tras el diámetro viene el largo "<n>M" (con o sin
    separador "/", "-", "*", "."). Sin largo legible -- "7N", "12H", "9K",
    "AM", "-/M" -- el largo no se puede leer."""
    resto = texto[diametro.end():].lstrip(" /-*.")
    if not _hay_contenido(resto):
        return False  # texto que termina: largo ausente, no deformado
    return re.match(r"\d{1,2}M(?![A-Z0-9])|\d{1,2}M(?=A[\dO]{3})", resto) is None


def _hay_contenido(texto: str) -> bool:
    """Algo más que "(N)"/"(I)" y puntuación."""
    return bool(re.sub(r"\((?:N|I)\)|[^A-Z0-9]", "", texto))


def _familia_partida(texto: str) -> bool:
    """Familia cortada por un dígito o espacio OCR ("RORM3 GON")."""
    tokens = re.findall(r"[A-Z0-9]+", texto)
    for a, b in zip(tokens, tokens[1:]):
        junta = re.sub(r"\d", "", a + b)
        if junta in _FAMILIAS or not junta.isalpha():
            continue
        for familia in (f for f in _FAMILIAS if len(f) >= 7 and f not in tokens):
            if abs(len(junta) - len(familia)) <= 2 and _distancia(junta, familia) <= 2:
                return True
    return False


def senales_material(descripcion: str, *, confianza: float | None = None, codigo_sap: str = "",
                     referencias: Mapping[str, str] | None = None) -> tuple[list[str], list[str]]:
    """(señales, advertencias) de un ítem de material. Las señales lo vuelven
    NO confiable; las advertencias sólo piden confirmación. No corrige nada."""
    original = str(descripcion or "").strip()
    if not original:
        return [], []
    texto = _sin_acentos(original)
    senales: list[str] = []
    advertencias: list[str] = []
    # Letras/símbolos ajenos ("é", "ä", "€"); la puntuación de ancho completo
    # "（N）" es sólo forma, no contenido.
    if any(ord(c) > 127 and c not in "Ññº" and unicodedata.category(c)[0] in "LS" for c in original):
        senales.append(SENAL_CARACTER_NO_ESPERADO)
    if "ILEGIBLE" in texto:
        senales.append(SENAL_DETALLE_ILEGIBLE)
    palabras = _PALABRA.findall(texto)
    familia_deformada = _familia_deformada(palabras) or _familia_partida(texto)
    if familia_deformada:
        senales.append(SENAL_FAMILIA_DEFORMADA)
    if len({"CANTIDAD", "CODIGO", "DESCRIPCION"} & set(palabras)) >= 2:
        senales.append(SENAL_ENCABEZADO)
    diametro = _DIAMETRO.search(texto)
    if ("HORMIGON" in palabras or "ALAMBRON" in palabras) and "ILEGIBLE" not in texto:
        familia = "HORMIGON" if "HORMIGON" in palabras else "ALAMBRON"
        if diametro is None:
            if _hay_contenido(texto.split(familia, 1)[1]):
                senales.append(SENAL_MEDIDA_DEFORMADA)
        elif "HORMIGON" in palabras and "ROLLO" not in palabras and _largo_deformado(texto, diametro):
            senales.append(SENAL_LARGO_DEFORMADO)
        # Calidad deformada sólo si tras el diámetro/largo HAY un token que
        # no la cumple; un texto que termina antes es calidad ausente.
        if "HORMIGON" in palabras and not _CALIDAD_HORMIGON.search(texto):
            resto = texto[diametro.end():] if diametro else texto.split("HORMIGON", 1)[1]
            resto = re.sub(r"^[\s/*.-]*\d{1,2}M(?![A-Z0-9])", "", resto)
            if _hay_contenido(resto):
                senales.append(SENAL_CALIDAD_DEFORMADA)
    if not familia_deformada and diametro is None and not any(p in _FAMILIAS for p in palabras):
        senales.append(SENAL_NO_ES_MATERIAL)
    if confianza is not None and confianza < UMBRAL_CONFIANZA_MATERIAL:
        senales.append(SENAL_CONFIANZA_BAJA)
    referencia = (referencias or {}).get(codigo_sap) if codigo_sap else None
    if referencia:
        ref = _sin_acentos(referencia)
        diametro_ref, diametro_doc = _diametro_legible(ref), _diametro_legible(texto)
        familia_ref = "ROLLO" if ref.startswith("ROLLO") else ("BARRA" if "HORMIGON" in ref else "")
        familia_doc = "" if familia_deformada else (
            "ROLLO" if "ROLLO" in palabras else ("BARRA" if "HORMIGON" in palabras else ""))
        if (diametro_doc and diametro_ref and diametro_doc != diametro_ref) or (
                familia_doc and familia_ref and familia_doc != familia_ref):
            advertencias.append(ADVERTENCIA_CONTRADICCION_CODIGO)
    return senales, advertencias


# --------------------------------------------------------------- orquestación


def analizar_items_material(descripcion: str, *, textos: Iterable[str] = (), bloques: Sequence | None = None,
                            referencias: Mapping[str, str] | None = None) -> list[ItemMaterialOCR]:
    """Un `ItemMaterialOCR` por ítem de `descripcion` (separados por " | ",
    igual que los persiste el extractor). Con `bloques` (geometría OCR ya
    leída) el código se asocia por fila; sin ellos, sólo cuando hay un único
    ítem y un único código en todo el texto."""
    items = [i.strip() for i in str(descripcion or "").split(" | ") if i.strip()]
    salida: list[ItemMaterialOCR] = []
    bloques = list(bloques or [])
    bloques_codigo = []
    for bloque in bloques:
        caja = _caja(bloque)
        if caja is None:
            continue
        for codigo in codigos_sap_en_texto(_texto(bloque)):
            bloques_codigo.append((codigo, caja))
    codigos_texto = codigos_sap_en_texto(" ".join(str(t) for t in textos))
    asignados: dict[str, int] = {}
    for item in items:
        resultado = ItemMaterialOCR(descripcion_ocr=item)
        bloque = _bloque_del_item(item, bloques) if bloques else None
        if bloque is not None:
            resultado.confianza_ocr = _confianza(bloque)
            caja = _caja(bloque)
            if caja is not None:
                resultado.codigo_sap, resultado.evidencia_codigo = _codigo_en_misma_fila(caja, bloques_codigo)
        elif not bloques and len(items) == 1 and len(codigos_texto) == 1:
            resultado.codigo_sap, resultado.evidencia_codigo = codigos_texto[0], EVIDENCIA_UNICO_ITEM_TEXTO
        if resultado.codigo_sap:
            asignados[resultado.codigo_sap] = asignados.get(resultado.codigo_sap, 0) + 1
        salida.append(resultado)
    # Un mismo código asociado a dos ítems distintos no identifica a ninguno.
    for resultado in salida:
        if resultado.codigo_sap and asignados[resultado.codigo_sap] > 1:
            resultado.codigo_sap, resultado.evidencia_codigo = "", EVIDENCIA_AMBIGUA
        resultado.senales, resultado.advertencias = senales_material(
            resultado.descripcion_ocr, confianza=resultado.confianza_ocr,
            codigo_sap=resultado.codigo_sap, referencias=referencias)
    return salida


# --------------------------------------------------------------- filas omitidas
#
# Casos reales 482396 (falta "B HORMIGON 22MM 6M", 4.695 kg) y 472818: la
# tabla trae N filas CANTIDAD/CODIGO, pero sólo N-1 descripciones llegaron
# al dataset, sin ningún motivo. Las filas se reconocen por su código SAP y
# su cantidad (en AZA, la suma de CANTIDAD es exactamente PESO KG). Sólo
# observa: nunca agrega ítems, motivos ni estados.

FILAS_SIN_EVIDENCIA = "SIN_EVIDENCIA"
FILAS_SIN_OMISION = "SIN_OMISION"
FILAS_OMISION_CONFIRMADA = "OMISION_CONFIRMADA"
# Faltan filas con certeza (conteo + suma = PESO KG), pero no se sabe cuáles:
# algún ítem leído no tiene código propio que lo ate a su fila.
FILAS_OMISION_SIN_IDENTIFICAR = "OMISION_SIN_IDENTIFICAR"
FILAS_NO_CONCLUYENTE = "NO_CONCLUYENTE"

MOTIVO_CODIGO_REPETIDO = "CODIGO_REPETIDO"
MOTIVO_CANTIDAD_NO_LEIDA = "CANTIDAD_NO_LEIDA"
MOTIVO_PESO_AUSENTE = "PESO_AUSENTE"
MOTIVO_SUMA_DISTINTA_PESO = "SUMA_DISTINTA_PESO"
MOTIVO_FILAS_NO_SUPERAN_ITEMS = "FILAS_NO_SUPERAN_ITEMS"

TOLERANCIA_PESO_KG = 1

# Cantidad AZA en kg con separador de miles ("4.695", "27,871" con la coma
# leída por el OCR) o hasta 3 dígitos ("270"). Sin decimales: otra forma no
# es una cantidad legible y se abstiene.
_CANTIDAD_KG = r"\d{1,3}(?:[.,]\d{3})+|\d{1,3}"
_CANTIDAD_PEGADA = re.compile(rf"(?<![\d.,/])({_CANTIDAD_KG})\s*(1100\d{{5}})(?!\d)")
_CANTIDAD_SOLA = re.compile(rf"^(?:{_CANTIDAD_KG})$")


def _kg(cantidad: str) -> int:
    return int(re.sub(r"[.,]", "", cantidad))


@dataclass
class FilaMaterialDocumental:
    codigo_sap: str
    cantidad_kg: int | None = None
    fuente_cantidad: str = ""  # PEGADA_AL_CODIGO | MISMA_FILA_GEOMETRICA | ""


def _cantidad_en_misma_fila(caja_codigo, bloques) -> int | None:
    """Única cantidad suelta a la izquierda del código, en su misma fila."""
    x0, y0, _x1, y1 = caja_codigo
    alto = max(y1 - y0, 1.0)
    candidatas = set()
    for bloque in bloques:
        caja = _caja(bloque)
        texto = _texto(bloque).strip()
        if caja is None or not _CANTIDAD_SOLA.fullmatch(texto):
            continue
        centro = (caja[1] + caja[3]) / 2
        if y0 - alto / 2 <= centro <= y1 + alto / 2 and caja[2] <= x0 + alto:
            candidatas.add(_kg(texto))
    return candidatas.pop() if len(candidatas) == 1 else None


def filas_material_documentales(*, textos: Iterable[str] = (), bloques: Sequence | None = None
                                ) -> list[FilaMaterialDocumental]:
    """Una fila por aparición de código SAP en la tabla, con su cantidad si
    está pegada al código o (con geometría) sola en la misma fila."""
    filas: list[FilaMaterialDocumental] = []
    bloques = list(bloques or [])
    fuentes = [(_texto(b), _caja(b)) for b in bloques] if bloques else [(str(t), None) for t in textos]
    for texto, caja in fuentes:
        pegadas = {m.group(2): _kg(m.group(1)) for m in _CANTIDAD_PEGADA.finditer(texto)}
        for codigo in _CODIGO_SAP.findall(texto):
            if codigo in pegadas:
                filas.append(FilaMaterialDocumental(codigo, pegadas[codigo], "PEGADA_AL_CODIGO"))
                continue
            cantidad = _cantidad_en_misma_fila(caja, bloques) if caja is not None else None
            filas.append(FilaMaterialDocumental(codigo, cantidad, EVIDENCIA_MISMA_FILA if cantidad is not None else ""))
    return filas


def detectar_filas_material_omitidas(items: Sequence[ItemMaterialOCR], *, peso_kg: str,
                                     textos: Iterable[str] = (), bloques: Sequence | None = None) -> dict:
    """Compara las filas documentales (código + cantidad) con los ítems
    leídos. `OMISION_CONFIRMADA` sólo si hay códigos de la tabla sin ítem,
    toda fila tiene cantidad, la suma es PESO KG (±1 kg) y cada ítem leído
    tiene su propio código: así los faltantes quedan identificados sin
    ambigüedad. Ante cualquier duda devuelve otro estado con su motivo."""
    filas = filas_material_documentales(textos=textos, bloques=bloques)
    resultado: dict = {
        "estado": FILAS_SIN_EVIDENCIA, "motivo": "", "items_leidos": len(items),
        "filas_documentales": [asdict(f) for f in filas], "peso_kg": peso_kg,
        "suma_cantidades_kg": None, "filas_faltantes": 0, "faltantes": [],
    }
    if not filas:
        return resultado
    codigos = [f.codigo_sap for f in filas]
    con_codigo = {i.codigo_sap for i in items if i.codigo_sap}
    sin_item = [f for f in filas if f.codigo_sap not in con_codigo]
    completas = all(f.cantidad_kg is not None for f in filas)
    suma = sum(f.cantidad_kg for f in filas) if completas else None
    peso = int(peso_kg) if re.fullmatch(r"\d{1,6}", str(peso_kg or "")) else None
    suma_coincide = suma is not None and peso is not None and abs(suma - peso) <= TOLERANCIA_PESO_KG
    resultado.update(suma_cantidades_kg=suma, suma_coincide_peso=suma_coincide)

    def no_concluyente(motivo: str) -> dict:
        resultado.update(estado=FILAS_NO_CONCLUYENTE, motivo=motivo)
        return resultado

    if len(set(codigos)) != len(codigos):
        return no_concluyente(MOTIVO_CODIGO_REPETIDO)
    if not sin_item:
        resultado["estado"] = FILAS_SIN_OMISION
        return resultado
    if not completas:
        return no_concluyente(MOTIVO_CANTIDAD_NO_LEIDA)
    if peso is None:
        return no_concluyente(MOTIVO_PESO_AUSENTE)
    if not suma_coincide:
        return no_concluyente(MOTIVO_SUMA_DISTINTA_PESO)
    if len(filas) <= len(items):
        return no_concluyente(MOTIVO_FILAS_NO_SUPERAN_ITEMS)
    resultado["filas_faltantes"] = len(filas) - len(items)
    if len(con_codigo) != len(items):
        resultado["estado"] = FILAS_OMISION_SIN_IDENTIFICAR
        return resultado
    resultado.update(estado=FILAS_OMISION_CONFIRMADA,
                     faltantes=[{"codigo_sap": f.codigo_sap, "cantidad_kg": f.cantidad_kg} for f in sin_item])
    return resultado
