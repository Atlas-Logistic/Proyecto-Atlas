"""Resolución de planta de origen por evidencia documental (Bloque PLANTA-P1).

Adaptado de ``_resolver_origen_documental`` (rama remota no fusionada
``origin/feature-cobertura-origen-fase1``, commit ``2c5c764``, validado con
9 guías reales: cobertura 7/9, los 2 casos restantes correctamente sin
origen por desenfoque/omisión de OCR -- 0 falsos positivos conocidos) para
operar sobre el texto OCR de página completa que ya produce el proveedor
activo.

Diferencia deliberada con el original: el original releía un recorte focal
del encabezado con EasyOCR (``lector.readtext()`` directo, igual que otros
focales ya migrados en bloques anteriores -- API no soportada por
PaddleOCR) y exigía consenso entre 2 de 3 variantes de esa relectura, para
compensar el ruido de una imagen pequeña/recortada. Con PaddleOCR el
encabezado del emisor ya se lee, con confianza alta, dentro del texto de
página completa que `procesar_archivo` obtiene igual — no hace falta una
relectura focal aparte. Por eso esta versión trabaja directamente sobre
`textos` (la misma lista que ya usa el resto del extractor) y no requiere
consenso entre variantes; conserva intacta la exigencia de planta única
sin ambigüedad, que es la que evita los falsos positivos.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Iterable


def _normalizar(texto: object) -> str:
    valor = unicodedata.normalize("NFD", str(texto or ""))
    return "".join(c for c in valor if unicodedata.category(c) != "Mn").upper()


def _distancia_token(a: str, b: str) -> int:
    """Distancia de edición (Levenshtein), acotada: tokens de largo muy
    distinto nunca se consideran la misma palabra con ruido OCR."""
    if abs(len(a) - len(b)) > 1:
        return 99
    anterior = list(range(len(b) + 1))
    for indice_a, caracter_a in enumerate(a, 1):
        actual = [indice_a]
        for indice_b, caracter_b in enumerate(b, 1):
            actual.append(min(
                actual[-1] + 1,
                anterior[indice_b] + 1,
                anterior[indice_b - 1] + (caracter_a != caracter_b),
            ))
        anterior = actual
    return anterior[-1]


def _tokens_encabezado_origen(texto: str) -> list[str]:
    """Recorta los tokens a la porción del encabezado que SÍ podría traer
    evidencia real de origen -- nunca el domicilio legal/casa matriz
    societaria ni el listado de sucursales de contacto, ninguno de los
    dos es la planta física real de despacho (Bloque CORRECCIÓN
    ESTRUCTURAL DE ORIGEN DOCUMENTAL -- caso real 472647/472648: guía
    AZA con "... CASA MATRIZ PLANTA RENCA, LA UNIÓN 3070, RENCA
    SANTIAGO..." impreso arriba, IDÉNTICO en cada guía que emite esa
    empresa, sin importar la planta real de despacho -- Javier confirma
    que el membrete/encabezado corporativo NUNCA debe tratarse como
    evidencia de origen, bajo ningún contexto).

    "CASA MATRIZ" es terminología SII/comercial chilena estándar (RUT +
    razón social + domicilio registrado), no un dato propio de ninguna
    empresa -- excluirla es universal, nunca específico de AZA/RENCA.
    El encabezado de una guía también suele continuar con un listado
    fijo de sucursales ("Sucursal <ciudad>...") impreso como información
    de contacto, no como planta de despacho -- si esas ciudades también
    existen como plantas confirmadas en el catálogo (p. ej. "Sucursal
    Colina"), comparar contra el texto completo genera una segunda
    coincidencia y anula el voto de la planta real.

    Se conserva únicamente el tramo ANTERIOR a la primera mención
    tolerante a ruido OCR de "CASA MATRIZ" o de "SUCURSAL" -- lo que
    aparezca primero. Nunca infiere que "no hay nada antes" signifique
    buscar más abajo: sin texto utilizable antes de cualquiera de esos
    dos marcadores, no hay encabezado de origen que evaluar.

    Hallazgo REVISIÓN DE ATLAS (caso real 472624 -- guía AZA, "CASA
    MATRIZ PLANTA RENCA" impreso igual que en 472647/472648 arriba):
    `"MATRIZ"` ya no se exige INMEDIATAMENTE después de `"CASA"` en el
    texto de página completa (`textos` unido) -- se busca dentro de una
    ventana corta de los tokens siguientes. `textos` llega en el ORDEN
    que devuelve el proveedor OCR por bloque, no necesariamente en orden
    de lectura visual estricto; un bloque de ruido intercalado entre
    "CASA" y "MATRIZ" (p. ej. una leyenda/logo superpuesto en esa misma
    zona del membrete) bastaba para que la adyacencia exacta nunca se
    detectara -- "MATRIZ" (y todo lo que sigue, "PLANTA RENCA" incluido)
    quedaba entonces DENTRO del encabezado evaluable en vez de excluido.
    Ensanchar la ventana sólo puede excluir MÁS texto, nunca menos --
    conservador por diseño: nunca se corre el riesgo de tratar el
    membrete como evidencia real de origen por esta fragilidad."""
    tokens_completos = re.findall(r"[A-Z0-9]+", _normalizar(texto))
    VENTANA_CASA_MATRIZ = 3

    def _es_inicio_casa_matriz(indice: int) -> bool:
        if _distancia_token(tokens_completos[indice], "CASA") > 1:
            return False
        limite_ventana = min(indice + 1 + VENTANA_CASA_MATRIZ, len(tokens_completos))
        return any(
            _distancia_token(tokens_completos[siguiente], "MATRIZ") <= 1
            for siguiente in range(indice + 1, limite_ventana)
        )

    limite = next(
        (
            indice for indice, token in enumerate(tokens_completos)
            if _distancia_token(token, "SUCURSAL") <= 1 or _es_inicio_casa_matriz(indice)
        ),
        len(tokens_completos),
    )
    return tokens_completos[:limite]


def resolver_origen_documental(
    textos: Iterable[str], plantas: Iterable[object]
) -> object | None:
    """`plantas`: objetos con `nombre`, `estado_calidad`, `estado_vigencia`
    (p. ej. `atlas_core.catalogo_plantas.Planta`). Devuelve el objeto planta
    si exactamente una coincide sin ambigüedad con el encabezado (cortado
    antes de "SUCURSAL"); `None` si no hay ninguna o hay más de una —
    nunca infiere por descarte ni por cercanía a otro campo."""
    texto_completo = "\n".join(str(t) for t in textos)
    tokens = _tokens_encabezado_origen(texto_completo)
    if not tokens:
        return None
    coincidencias = []
    for planta in plantas:
        if str(getattr(planta, "estado_vigencia", "")).upper() not in {"ACTIVA", "ACTIVO"}:
            continue
        if str(getattr(planta, "estado_calidad", "")).upper() not in {
            "CONFIRMADA", "CONFIRMADO", "CONFIRMADO_DOCUMENTAL",
        }:
            continue
        nombre = str(getattr(planta, "nombre", "")).strip()
        nombre_tokens = re.findall(r"[A-Z0-9]+", _normalizar(nombre))
        if nombre_tokens and all(
            any(_distancia_token(observado, esperado) <= 1 for observado in tokens)
            for esperado in nombre_tokens
        ):
            coincidencias.append(planta)
    if len(coincidencias) == 1:
        return coincidencias[0]
    return None
