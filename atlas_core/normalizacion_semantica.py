"""Normalización semántica controlada de nombres de entidades (Bloque
INTELIGENCIA N1).

Principio de diseño: un valor OCR (`VALOR OCR`) no es la verdad, pero
tampoco se adivina -- se normaliza (`VALOR NORMALIZADO`) solo cuando la
evidencia lo permite, y se corrobora (`VALOR CANÓNICO`) solo contra un
catálogo/RUT/código real. Este módulo se ocupa del primer paso
(OCR -> normalizado): limpieza estructural de un nombre de entidad
(razón social/obra), nunca de decidir su identidad canónica -- eso vive
en `atlas_core.catalogos` (RUT/fuzzy contra catálogo).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# --- Fase E: formas societarias chilenas, como tokens estructurales ---
#
# Lista acotada a formas realmente vistas en datos reales del proyecto
# (catálogos + tanda operacional) y las formas legales chilenas de uso
# corriente equivalentes -- no una lista exhaustiva inventada. Se separan
# en dos grupos porque su patrón de corrupción OCR típico es distinto:
# las abreviaturas (SA/SPA/LTDA/EIRL) son cortas y una sola letra mal
# leída ya cambia el token entero; las palabras descriptivas
# (CONSTRUCTORA, INGENIERIA, ...) son largas y toleran más distancia.

FORMAS_LEGALES_ABREVIADAS: tuple[str, ...] = (
    "SA", "SPA", "LTDA", "LIMITADA", "EIRL",
)

PALABRAS_SOCIETARIAS_COMUNES: tuple[str, ...] = (
    # Vistas en `empresas.json`/`destinos.json` o en la tanda real
    # (Bloque N1, Fase A): CONSTRUCTORA (OCR "CONETRUCTORA"),
    # CONSTRUCCIONES, INGENIERIA, INMOBILIARIA (abrev. "INMOB"),
    # FERRETERIA, METALURGICA -- ya en catálogo real.
    "SOCIEDAD", "CONSTRUCTORA", "CONSTRUCCIONES", "COMERCIAL", "INDUSTRIAL",
    "INMOBILIARIA", "TRANSPORTES", "SERVICIOS", "INGENIERIA", "DISTRIBUIDORA",
    "EXPORTADORA", "IMPORTADORA", "INVERSIONES", "AGRICOLA", "MINERA",
    "EMPRESA", "EMPRESAS", "METALURGICA", "FERRETERIA", "FUNDICION",
)

_VOCABULARIO_SOCIETARIO: tuple[str, ...] = FORMAS_LEGALES_ABREVIADAS + PALABRAS_SOCIETARIAS_COMUNES


def _distancia_edicion_acotada(a: str, b: str, limite: int) -> int:
    """Distancia de Levenshtein (inserción/eliminación/sustitución, costo
    1 cada una) con salida temprana si supera `limite` -- suficiente para
    palabras cortas de vocabulario cerrado, sin dependencias externas."""
    if a == b:
        return 0
    if abs(len(a) - len(b)) > limite:
        return limite + 1
    fila_anterior = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        fila_actual = [i] + [0] * len(b)
        for j, cb in enumerate(b, 1):
            costo = 0 if ca == cb else 1
            fila_actual[j] = min(
                fila_anterior[j] + 1,
                fila_actual[j - 1] + 1,
                fila_anterior[j - 1] + costo,
            )
        fila_anterior = fila_actual
    return fila_anterior[-1]


_LONGITUD_MAXIMA_FORMA_CORTA = 4


def _distancia_candidato(token: str, palabra: str) -> tuple[int, int]:
    """Devuelve (distancia, límite) para comparar `token` contra `palabra`.

    Las formas abreviadas cortas (SA, SPA, LTDA, EIRL -- <= 4 caracteres)
    SOLO aceptan sustitución en la MISMA longitud (nunca inserción ni
    eliminación): un token de otra longitud nunca es candidato. Esto es
    deliberado -- una tolerancia de edición normal (Levenshtein general)
    dejaría "SAN" (una palabra real y común en topónimos chilenos, "SAN
    BERNARDO") a distancia 1 de "SA" por simple eliminación de una letra,
    lo que la corrompería igual que si fuera OCR -- bug real encontrado
    y corregido durante este mismo bloque. Las palabras descriptivas
    largas (CONSTRUCTORA, LIMITADA, ...) sí tardan una tolerancia de
    edición completa, porque a esa longitud una coincidencia accidental
    con una palabra real distinta es extremadamente improbable."""
    if len(palabra) <= _LONGITUD_MAXIMA_FORMA_CORTA:
        if len(token) != len(palabra):
            return 999, 1
        return sum(1 for a, b in zip(token, palabra) if a != b), 1
    limite = 1 if len(palabra) <= 6 else 2
    return _distancia_edicion_acotada(token, palabra, limite), limite


def normalizar_token_societario(token: str) -> str | None:
    """Si `token` es una corrupción OCR seguramente única de una forma
    societaria conocida (Fase E), devuelve la forma canónica; si ya es
    exacto, o no hay candidato suficientemente cercano, o hay más de uno
    empatado, devuelve `None` (no toca el token). Nunca se aplica a
    tokens de menos de 3 caracteres -- demasiado riesgo de coincidir con
    un fragmento real de un nombre propio (p. ej. "OCL")."""
    token_simple = re.sub(r"[.\s]", "", str(token or "")).upper()
    if len(token_simple) < 3:
        return None

    candidatos: list[tuple[int, str]] = []
    for palabra in _VOCABULARIO_SOCIETARIO:
        distancia, limite = _distancia_candidato(token_simple, palabra)
        if distancia <= limite:
            candidatos.append((distancia, palabra))

    if not candidatos:
        return None
    candidatos.sort()
    mejor_distancia, mejor_palabra = candidatos[0]
    if mejor_distancia == 0:
        return None  # ya es exactamente esa forma -- nada que normalizar
    empatados = {palabra for distancia, palabra in candidatos if distancia == mejor_distancia}
    if len(empatados) > 1:
        return None  # ambiguo entre dos formas igual de cercanas -- abstención
    return mejor_palabra


def _quitar_prefijo_caracter_suelto(texto: str) -> str:
    """Quita un carácter aislado al inicio de un valor (seguido de
    espacio y el resto del contenido) cuando el resto sigue siendo un
    valor nominal plausible -- artefacto OCR real y recurrente en la
    tanda (un separador de campo, ":"/"|", leído como una letra suelta;
    casos reales: "I SOC CONSTRUCTORA...", "I TORRES OCARANZA...").
    Nunca toca un valor de una sola palabra ni uno cuyo resto quede en
    una sola palabra -- para no arriesgar una inicial real de un nombre
    de persona/empresa corta."""
    texto = str(texto or "").strip()
    partes = texto.split(" ", 1)
    if len(partes) == 2 and len(partes[0]) == 1 and partes[0].isalpha():
        resto = partes[1].strip()
        if len(resto.split()) >= 2:
            return resto
    return texto


@dataclass(frozen=True)
class ResultadoNormalizacionNombre:
    """Trazabilidad OCR -> normalizado (Fase G): `valor_ocr` nunca se
    pierde, incluso cuando `cambio` es True."""

    valor_ocr: str
    valor_normalizado: str
    cambio: bool
    tokens_corregidos: tuple[tuple[str, str], ...] = ()


def normalizar_nombre_societario(nombre: str) -> ResultadoNormalizacionNombre:
    """Normaliza un nombre de entidad (cliente/obra destino/razón social)
    token por token contra las formas societarias conocidas (Fase E),
    más el artefacto de prefijo suelto (arriba). Nunca reordena ni
    elimina palabras que no reconoce -- solo corrige las que matchean de
    forma única y seguirá. Ejemplo real (Fase G):
    "SOC CONETRUCTORA OCL LIMITAD" -> "SOC CONSTRUCTORA OCL LIMITADA"."""
    original = str(nombre or "")
    sin_prefijo = _quitar_prefijo_caracter_suelto(original)

    palabras = sin_prefijo.split(" ")
    corregidas: list[str] = []
    cambios: list[tuple[str, str]] = []
    for palabra in palabras:
        if not palabra:
            corregidas.append(palabra)
            continue
        # Conserva puntuación final (p. ej. "LTDA." -> compara sin punto,
        # pero el reemplazo nunca inventa puntuación que el original no
        # tenía).
        candidato = normalizar_token_societario(palabra)
        if candidato:
            corregidas.append(candidato)
            cambios.append((palabra, candidato))
        else:
            corregidas.append(palabra)

    normalizado = " ".join(corregidas)
    cambio = normalizado != original
    return ResultadoNormalizacionNombre(
        valor_ocr=original,
        valor_normalizado=normalizado,
        cambio=cambio,
        tokens_corregidos=tuple(cambios),
    )
