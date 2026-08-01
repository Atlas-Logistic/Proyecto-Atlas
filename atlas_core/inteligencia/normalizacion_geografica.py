"""Normalización geográfica chilena y comparación conservadora de direcciones."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from atlas_core.inteligencia.motor import normalizar


REGION_METROPOLITANA = "REGIÓN METROPOLITANA"

_ALIAS_REGIONES_CHILE = {
    "REGION METROPOLITANA": REGION_METROPOLITANA,
    "METROPOLITANA": REGION_METROPOLITANA,
    "RM": REGION_METROPOLITANA,
    "REGION METROPOLITANA DE SANTIAGO": REGION_METROPOLITANA,
    "METROPOLITANA DE SANTIAGO": REGION_METROPOLITANA,
}

_TIPOS_VIA = {
    "AV": "AVENIDA",
    "AVENIDA": "AVENIDA",
    "CAM": "CAMINO",
    "CAMINO": "CAMINO",
    "PDTE": "PRESIDENTE",
    "PRESIDENTE": "PRESIDENTE",
}

_PALABRAS_GENERICAS = frozenset({
    "CHILE", "REGION", "METROPOLITANA", "SANTIAGO", "RM",
})


class EstadoCoincidenciaDireccion(str, Enum):
    COINCIDENCIA_EXACTA = "COINCIDENCIA_EXACTA"
    COINCIDENCIA_NORMALIZADA = "COINCIDENCIA_NORMALIZADA"
    COINCIDENCIA_PARCIAL_SIN_NUMERO = "COINCIDENCIA_PARCIAL_SIN_NUMERO"
    COINCIDENCIA_SOLO_CALLE = "COINCIDENCIA_SOLO_CALLE"
    COINCIDENCIA_SOLO_COMUNA_REGION = "COINCIDENCIA_SOLO_COMUNA_REGION"
    CONTRADICCION_NUMERO = "CONTRADICCION_NUMERO"
    CONTRADICCION_COMUNA = "CONTRADICCION_COMUNA"
    CONTRADICCION_REGION = "CONTRADICCION_REGION"
    RESPUESTA_GENERICA = "RESPUESTA_GENERICA"
    AMBIGUA = "AMBIGUA"
    SIN_RESULTADO = "SIN_RESULTADO"


@dataclass(frozen=True)
class ResultadoNormalizacionGeografica:
    original: str
    canonico: str
    reconocido: bool
    transformaciones: tuple[str, ...]


@dataclass(frozen=True)
class ComponentesDireccion:
    original: str
    via: str
    numero: str
    complemento: str
    sin_numero: bool


@dataclass(frozen=True)
class ComparacionDireccion:
    estado: EstadoCoincidenciaDireccion
    calle_coincide: bool
    numero_coincide: bool
    comuna_coincide: bool
    region_coincide: bool
    coordenadas_validas: bool
    confirmable: bool
    componentes_esperados: ComponentesDireccion
    componentes_encontrados: ComponentesDireccion
    region_esperada: ResultadoNormalizacionGeografica
    region_encontrada: ResultadoNormalizacionGeografica
    explicacion: tuple[str, ...]


def normalizar_region_chile(valor: object) -> ResultadoNormalizacionGeografica:
    original = str(valor or "").strip()
    comparable = _texto_comparable(original)
    canonico = _ALIAS_REGIONES_CHILE.get(comparable, original)
    reconocido = comparable in _ALIAS_REGIONES_CHILE
    transformaciones = []
    if original and comparable != original.upper():
        transformaciones.append("MAYUSCULAS_TILDES_Y_PUNTUACION_NORMALIZADAS")
    if reconocido and normalizar(original) != normalizar(canonico):
        transformaciones.append(f"ALIAS_CONTROLADO:{comparable}->{canonico}")
    elif reconocido and original != canonico:
        transformaciones.append(f"FORMA_CANONICA:{canonico}")
    return ResultadoNormalizacionGeografica(
        original, canonico, reconocido, tuple(transformaciones)
    )


def regiones_equivalentes(esperada: object, encontrada: object) -> bool:
    a = normalizar_region_chile(esperada)
    b = normalizar_region_chile(encontrada)
    if a.reconocido and b.reconocido:
        return a.canonico == b.canonico
    return bool(a.original.strip()) and _texto_comparable(a.original) == _texto_comparable(
        b.original
    )


def comunas_equivalentes(esperada: object, encontrada: object) -> bool:
    a, b = _texto_comparable(esperada), _texto_comparable(encontrada)
    return bool(a) and a == b


def separar_direccion(valor: object) -> ComponentesDireccion:
    original = str(valor or "").strip()
    segmento_via = original.split(",", 1)[0]
    texto = _texto_comparable(segmento_via)
    tokens = texto.split()
    normalizados = [_TIPOS_VIA.get(token, token) for token in tokens]
    sin_numero = _contiene_sin_numero(normalizados)
    if sin_numero:
        normalizados = _quitar_marca_sin_numero(normalizados)
        indice_numero = None
    else:
        indice_numero = next(
            (i for i, token in enumerate(normalizados) if re.fullmatch(r"\d+[A-Z]?", token)),
            None,
        )
    numero = (
        "S/N" if sin_numero
        else ("" if indice_numero is None else normalizados[indice_numero])
    )
    if indice_numero == 0:
        via_tokens = normalizados[1:]
        complemento_tokens = []
    else:
        fin_via = indice_numero if indice_numero is not None else len(normalizados)
        via_tokens = normalizados[:fin_via]
        complemento_tokens = (
            normalizados[indice_numero + 1:] if indice_numero is not None else []
        )
    via = " ".join(via_tokens).strip()
    complemento = " ".join(complemento_tokens).strip()
    return ComponentesDireccion(original, via, numero, complemento, sin_numero)


def comparar_direccion(
    *,
    direccion_esperada: str,
    direccion_encontrada: str,
    comuna_esperada: str,
    comuna_encontrada: str,
    region_esperada: str,
    region_encontrada: str,
    coordenadas_validas: bool,
) -> ComparacionDireccion:
    esperado = separar_direccion(direccion_esperada)
    encontrado = separar_direccion(direccion_encontrada)
    region_a = normalizar_region_chile(region_esperada)
    region_b = normalizar_region_chile(region_encontrada)
    region_ok = regiones_equivalentes(region_esperada, region_encontrada)
    comuna_ok = comunas_equivalentes(comuna_esperada, comuna_encontrada)
    calle_ok = _calles_equivalentes(esperado.via, encontrado.via)
    numero_ok = bool(esperado.numero) and esperado.numero == encontrado.numero
    explicacion = [
        f"Calle equivalente: {'sí' if calle_ok else 'no'}.",
        f"Número equivalente: {'sí' if numero_ok else 'no'}.",
        f"Comuna equivalente: {'sí' if comuna_ok else 'no'}.",
        f"Región equivalente: {'sí' if region_ok else 'no'}.",
    ]

    if not direccion_encontrada.strip() or _es_generica(encontrado):
        estado = EstadoCoincidenciaDireccion.RESPUESTA_GENERICA
    elif not region_ok:
        estado = EstadoCoincidenciaDireccion.CONTRADICCION_REGION
    elif not comuna_ok:
        estado = EstadoCoincidenciaDireccion.CONTRADICCION_COMUNA
    elif calle_ok and esperado.numero and encontrado.numero and not numero_ok:
        estado = EstadoCoincidenciaDireccion.CONTRADICCION_NUMERO
    elif calle_ok and esperado.numero and not encontrado.numero:
        estado = EstadoCoincidenciaDireccion.COINCIDENCIA_PARCIAL_SIN_NUMERO
    elif calle_ok and numero_ok:
        estado = (
            EstadoCoincidenciaDireccion.COINCIDENCIA_EXACTA
            if _texto_comparable(direccion_esperada)
            == _texto_comparable(direccion_encontrada)
            else EstadoCoincidenciaDireccion.COINCIDENCIA_NORMALIZADA
        )
    elif calle_ok:
        estado = EstadoCoincidenciaDireccion.COINCIDENCIA_SOLO_CALLE
    elif comuna_ok and region_ok:
        estado = EstadoCoincidenciaDireccion.COINCIDENCIA_SOLO_COMUNA_REGION
    else:
        estado = EstadoCoincidenciaDireccion.RESPUESTA_GENERICA

    confirmable = (
        estado in {
            EstadoCoincidenciaDireccion.COINCIDENCIA_EXACTA,
            EstadoCoincidenciaDireccion.COINCIDENCIA_NORMALIZADA,
        }
        and calle_ok and numero_ok and comuna_ok and region_ok and coordenadas_validas
    )
    explicacion.append(
        "Confirmación automática permitida."
        if confirmable else "Se conserva el original y se requiere revisión."
    )
    return ComparacionDireccion(
        estado, calle_ok, numero_ok, comuna_ok, region_ok, coordenadas_validas,
        confirmable, esperado, encontrado, region_a, region_b, tuple(explicacion),
    )


def _texto_comparable(valor: object) -> str:
    texto = normalizar(valor)
    texto = re.sub(r"[^A-Z0-9]+", " ", texto)
    return " ".join(texto.split())


def _contiene_sin_numero(tokens: list[str]) -> bool:
    unidos = " ".join(tokens)
    return bool(re.search(r"\bS\s*N\b|\bSIN NUMERO\b", unidos))


def _quitar_marca_sin_numero(tokens: list[str]) -> list[str]:
    resultado = list(tokens)
    if len(resultado) >= 2 and resultado[-2:] == ["S", "N"]:
        return resultado[:-2]
    if len(resultado) >= 2 and resultado[-2:] == ["SIN", "NUMERO"]:
        return resultado[:-2]
    return resultado


def _calles_equivalentes(a: str, b: str) -> bool:
    tokens_a = [t for t in a.split() if t not in _PALABRAS_GENERICAS]
    tokens_b = [t for t in b.split() if t not in _PALABRAS_GENERICAS]
    if not tokens_a or not tokens_b:
        return False
    return tokens_a == tokens_b or set(tokens_a) <= set(tokens_b) or set(tokens_b) <= set(tokens_a)


def _es_generica(componentes: ComponentesDireccion) -> bool:
    tokens = set(componentes.via.split())
    significativos = tokens - _PALABRAS_GENERICAS
    return not significativos
