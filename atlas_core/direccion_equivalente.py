"""Equivalencia conservadora de direcciones que sólo difieren en un sufijo
geográfico (comuna / ciudad / región / país) después de calle + número.

Caso real 0000362325 (guías 475368/475369/475370): las tres guías imprimen
"CAMINO LO RUIZ 2901 SANTIAGO RENCA", pero el OCR dejó una lectura sin el
sufijo ("CAMINO LO RUIZ 2901") y Atlas las trató como dos destinos. Lo mismo
en 0000354852 ("AV PEHUENCHE 1177" / "... TALCA TALCA") y 0000356332
("... 3396 SANTIAGO SAN BERNARDO" / "... 3396, SAN BERNARDO, CHILE").

Nunca es fuzzy matching: el núcleo calle + número se fija con
`calle_numero_normalizado` (el mismo criterio de "documento hermano con
comuna explícita" de `revalidacion_documental`, caso 464784/464491), el
número de casa debe ser idéntico, y TODO lo que sigue al número debe ser un
nombre del catálogo territorial oficial (comunas INE, regiones) o un
genérico de ciudad/país. Cualquier otro token (DEPTO, LOCAL, SECTOR, otro
número, ruido OCR) hace que se abstenga. Las comunas nombradas no pueden
contradecirse entre sí ni con la comuna ya conocida de cada documento.
"""

from __future__ import annotations

import re
from typing import Callable, Iterable, Sequence

from atlas_core.catalogo_destinos import normalizar_nombre_destino
from atlas_core.territorio_chile import _GEOGRAFIA, _INDICE_COMUNAS

# "SANTIAGO" también es comuna, pero en los documentos AZA suele ser la
# ciudad que acompaña a la comuna real ("... SANTIAGO RENCA"). Sólo cuenta
# como comuna cuando es la única nombrada (ver `_comunas_efectivas`).
_CIUDAD_GENERICA = "SANTIAGO"
_GENERICOS = frozenset({"CHILE", "RM", "REGION", "REG", "METROPOLITANA", "REGION METROPOLITANA"})
_REGIONES = frozenset(
    normalizar_nombre_destino(u.nombre_normalizado) for u in _GEOGRAFIA.unidades if u.nivel == 1
)
_COMUNAS = frozenset(normalizar_nombre_destino(c) for c in _INDICE_COMUNAS)
_MAX_TOKENS_NOMBRE = max(len(nombre.split()) for nombre in _COMUNAS | _REGIONES | _GENERICOS)


def calle_numero_normalizado(texto: str) -> str | None:
    """Prefijo "calle + número" normalizado de un texto de destino libre
    (calle, posiblemente varias palabras, seguida del primer número que
    aparece) -- `None` si no trae ningún número. Usado para comparar
    calle+número SIN exigir que el resto del texto (comuna/ciudad) sea
    idéntico -- eso es exactamente lo que un documento hermano con comuna
    explícita agrega."""
    match = re.search(r"\d+", texto)
    if not match:
        return None
    return normalizar_nombre_destino(texto[: match.end()])


def comunas_en_sufijo(tokens: Sequence[str]) -> set[str] | None:
    """Comunas nombradas en `tokens` si TODOS son nombres geográficos
    oficiales (comuna, región, ciudad/país genérico); `None` si queda
    cualquier token sin cubrir. Empareja de izquierda a derecha el nombre
    más largo posible ("SAN BERNARDO" antes que "SAN")."""
    comunas: set[str] = set()
    i = 0
    while i < len(tokens):
        for largo in range(min(_MAX_TOKENS_NOMBRE, len(tokens) - i), 0, -1):
            nombre = " ".join(tokens[i:i + largo])
            if nombre in _COMUNAS:
                comunas.add(nombre)
            elif not (nombre in _REGIONES or nombre in _GENERICOS):
                continue
            i += largo
            break
        else:
            return None
    return comunas


def comuna_oficial(texto: str) -> str:
    """Nombre normalizado si `texto` es exactamente una comuna oficial."""
    nombre = normalizar_nombre_destino(texto or "")
    return nombre if nombre in _COMUNAS else ""


def comuna_por_codigo(codigo_unidad: str) -> str:
    unidad = _GEOGRAFIA.motor.por_codigo.get(str(codigo_unidad or "").strip())
    return comuna_oficial(unidad.nombre_normalizado) if unidad is not None else ""


def _comunas_efectivas(comunas: Iterable[str]) -> set[str]:
    efectivas = {c for c in comunas if c}
    if len(efectivas) > 1:
        efectivas.discard(_CIUDAD_GENERICA)
    return efectivas


def _descomponer(texto: str) -> tuple[str, str, list[str]] | None:
    """(calle, número, sufijo): el número de casa es el primer token
    puramente numérico y la calle todo lo anterior (con letras). `None` si
    no hay núcleo calle+número reconocible (sin número, "SIN NRO", número
    alfanumérico tipo "S197"/"O1148"). A diferencia de
    `calle_numero_normalizado` (corta en el primer dígito), un dígito OCR
    dentro de una palabra de la calle ("LO RUI2") sigue siendo calle: la
    compara después la tolerancia OCR del llamador."""
    tokens = normalizar_nombre_destino(texto or "").split()
    indice = next((i for i, t in enumerate(tokens) if re.fullmatch(r"\d{1,6}", t)), None)
    if indice is None:
        return None
    calle = tokens[:indice]
    if not any(any(c.isalpha() for c in t) for t in calle):
        return None
    # Un número alfanumérico antes del de casa ("S197 ...") no es calle.
    if any(re.fullmatch(r"[A-Z]?\d+[A-Z]?", t) for t in calle):
        return None
    return " ".join(calle), tokens[indice], tokens[indice + 1:]


def direcciones_equivalentes_por_sufijo_geografico(
    direccion_a: str,
    direccion_b: str,
    *,
    calles_equivalentes: Callable[[str, str], bool],
    comunas_conocidas_a: Iterable[str] = (),
    comunas_conocidas_b: Iterable[str] = (),
) -> bool:
    """True si ambas direcciones comparten núcleo calle + número (la calle
    comparada con `calles_equivalentes`, que aporta la tolerancia OCR ya
    existente del llamador; el número siempre exacto) y lo que sigue al
    número es, en ambas, sólo geografía oficial sin comunas en conflicto.
    `comunas_conocidas_*`: comunas ya establecidas para cada documento
    (localidad resuelta, código territorial); también deben concordar."""
    a = _descomponer(direccion_a)
    b = _descomponer(direccion_b)
    if a is None or b is None:
        return False
    calle_a, numero_a, sufijo_a = a
    calle_b, numero_b, sufijo_b = b
    if numero_a != numero_b or not calles_equivalentes(calle_a, calle_b):
        return False
    comunas_a = comunas_en_sufijo(sufijo_a)
    comunas_b = comunas_en_sufijo(sufijo_b)
    if comunas_a is None or comunas_b is None:
        return False
    todas = _comunas_efectivas(
        comunas_a | comunas_b | set(comunas_conocidas_a) | set(comunas_conocidas_b)
    )
    return len(todas) <= 1


def extension_geografica_compatible(
    lineal: str, extendida: str, *, comunas_conocidas: Iterable[str] = (),
) -> bool:
    """True si `extendida` es `lineal` completa (palabra por palabra) más un
    sufijo sólo geográfico, sin comunas en conflicto entre sí ni con
    `comunas_conocidas`. Nunca acepta un texto distinto sólo por ser más
    largo."""
    tokens_lineal = normalizar_nombre_destino(lineal or "").split()
    tokens_extendida = normalizar_nombre_destino(extendida or "").split()
    if not tokens_lineal or len(tokens_extendida) <= len(tokens_lineal):
        return False
    if tokens_extendida[:len(tokens_lineal)] != tokens_lineal:
        return False
    if not any(any(c.isalpha() for c in t) for t in tokens_lineal):
        return False
    comunas = comunas_en_sufijo(tokens_extendida[len(tokens_lineal):])
    if comunas is None:
        return False
    # Una comuna que la lectura lineal ya nombraba tras el número también
    # cuenta: el sufijo agregado no puede contradecirla.
    nucleo_lineal = _descomponer(lineal)
    ya_nombradas = (comunas_en_sufijo(nucleo_lineal[2]) or set()) if nucleo_lineal else set()
    return len(_comunas_efectivas(comunas | ya_nombradas | set(comunas_conocidas))) <= 1
