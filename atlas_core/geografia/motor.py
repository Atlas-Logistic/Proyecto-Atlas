"""Motor determinista de normalización, parametrizado por cada país."""
from __future__ import annotations

import difflib
import re
import unicodedata
from collections import defaultdict
from collections.abc import Iterable

from .modelos import EstadoNormalizacion, ResultadoNormalizacion, UnidadAdministrativa

UMBRAL_DIFUSO_PREDETERMINADO = 0.87
MARGEN_AMBIGUEDAD_PREDETERMINADO = 0.06
LONGITUD_MINIMA_DIFUSA_PREDETERMINADA = 4


def texto_normalizado(texto: str) -> str:
    valor = unicodedata.normalize("NFKD", str(texto or "").strip())
    valor = "".join(c for c in valor if not unicodedata.combining(c)).upper()
    return " ".join(re.findall(r"[A-Z0-9]+", valor))


class MotorNormalizacion:
    def __init__(
        self,
        unidades: Iterable[UnidadAdministrativa],
        *,
        palabras_estructurales: Iterable[str] = (),
        umbral: float = UMBRAL_DIFUSO_PREDETERMINADO,
        margen_ambiguedad: float = MARGEN_AMBIGUEDAD_PREDETERMINADO,
        longitud_minima: int = LONGITUD_MINIMA_DIFUSA_PREDETERMINADA,
    ) -> None:
        self.unidades = tuple(unidades)
        self.por_codigo = {unidad.codigo: unidad for unidad in self.unidades}
        self.palabras_estructurales = frozenset(texto_normalizado(x) for x in palabras_estructurales)
        self.umbral = umbral
        self.margen_ambiguedad = margen_ambiguedad
        self.longitud_minima = longitud_minima
        self._indices: dict[int, dict[str, tuple[UnidadAdministrativa, ...]]] = {}
        por_nivel: dict[int, dict[str, list[UnidadAdministrativa]]] = defaultdict(lambda: defaultdict(list))
        for unidad in self.unidades:
            claves = {unidad.nombre_normalizado, *(texto_normalizado(x) for x in unidad.aliases)}
            for clave in claves:
                por_nivel[unidad.nivel][clave].append(unidad)
        self._indices = {
            nivel: {clave: tuple(valores) for clave, valores in indice.items()}
            for nivel, indice in por_nivel.items()
        }

    def normalizar(self, texto: str, nivel: int | None = None) -> ResultadoNormalizacion:
        original = str(texto or "").strip()
        simple = texto_normalizado(original)
        niveles = (nivel,) if nivel is not None else tuple(sorted(self._indices))
        indice: dict[str, tuple[UnidadAdministrativa, ...]] = defaultdict(tuple)
        for actual in niveles:
            for clave, unidades in self._indices.get(actual, {}).items():
                indice[clave] += unidades
        if not simple:
            return self._resultado(EstadoNormalizacion.NO_RECONOCIDA, original)
        exactas = indice.get(simple, ())
        if len(exactas) == 1:
            return self._resultado(EstadoNormalizacion.EXACTA, original, exactas[0], 1.0)
        if len(exactas) > 1:
            return self._resultado(EstadoNormalizacion.AMBIGUA, original, similitud=1.0)
        if len(simple) < self.longitud_minima or simple in self.palabras_estructurales or not indice:
            return self._resultado(EstadoNormalizacion.NO_RECONOCIDA, original)
        # Los aliases son evidencia alternativa de una misma unidad, no
        # competidores entre sí. Conservamos sólo el mejor score por código.
        por_unidad: dict[str, tuple[float, UnidadAdministrativa]] = {}
        for clave, unidades in indice.items():
            puntuacion = difflib.SequenceMatcher(None, simple, clave).ratio()
            for unidad in unidades:
                anterior = por_unidad.get(unidad.codigo)
                if anterior is None or puntuacion > anterior[0]:
                    por_unidad[unidad.codigo] = (puntuacion, unidad)
        puntuados = sorted(
            por_unidad.values(), key=lambda item: (-item[0], item[1].codigo)
        )
        mejor, unidad = puntuados[0]
        if mejor < self.umbral:
            return self._resultado(EstadoNormalizacion.NO_RECONOCIDA, original, similitud=mejor)
        if len(puntuados) > 1 and mejor - puntuados[1][0] < self.margen_ambiguedad:
            return self._resultado(EstadoNormalizacion.AMBIGUA, original, similitud=mejor)
        return self._resultado(EstadoNormalizacion.NORMALIZADA_SEGURA, original, unidad, mejor)

    def _resultado(self, estado, original, unidad=None, similitud=None):
        return ResultadoNormalizacion(estado, original, unidad, similitud, _buscar_codigo=self.por_codigo.get)

    def normalizar_direccion(self, texto: str, *, nivel: int) -> str:
        original = str(texto or "")
        palabras = original.split()
        simples = [texto_normalizado(p) for p in palabras]
        resultado: list[str] = []
        for posicion, palabra in enumerate(palabras):
            decision = self.normalizar(palabra, nivel=nivel)
            if decision.estado != EstadoNormalizacion.NORMALIZADA_SEGURA or decision.unidad is None:
                resultado.append(palabra)
                continue
            canonica = decision.unidad.nombre_normalizado
            if any(i != posicion and otro == canonica for i, otro in enumerate(simples)):
                continue
            resultado.append(decision.unidad.nombre_canonico)
        limpio = " ".join(resultado)
        return limpio if limpio else original
