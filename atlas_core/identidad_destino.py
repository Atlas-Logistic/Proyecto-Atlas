"""Identidad física del destino de un documento, separada de su texto OCR.

Caso real 0000371984 (Salomón Pizarro, 23/11/2026, guías 485458/485459):
ambas guías imprimen "SANTA ISABEL 585 SANTIAGO LAMPA", pero el OCR leyó
"SANTA ISABEL S85 ..." en una y "SANTAISABEL 585 ..." en la otra. Las dos
resolvieron el MISMO destino confirmado del catálogo (misma ruta, 8,52 km),
pero la derivación de entregas compara el TEXTO de cada guía con una
tolerancia propia y más estrecha que la del catálogo. Esa tolerancia admite
un espacio perdido o una letra cambiada, pero no las dos cosas a la vez,
ni una letra dentro del número. Por eso el viaje se partía en dos
entregas.

La equivalencia vigente del catálogo (`direccion_confirmada_coincide`,
número y estructura como anclas exactas, numeración OCR "S85"/"O1148" sólo
contra el número confirmado) ya decide en todo el Motor que ese texto
documental ES el destino confirmado. Aquí se reutiliza tal cual para dar a
cada documento una IDENTIDAD física -- la clave del catálogo
(`_clave_fisica_destino`: calle + numeración + comuna) -- independiente de
cómo la escribió el OCR. Dos documentos con la misma identidad van al mismo
lugar; la representación textual (cuál de las lecturas se muestra) pasa a
ser una decisión aparte.

Conservador por construcción; se abstiene (``None``) ante:

* ningún destino ACTIVO y CONFIRMADO coincidente (dirección nueva o
  distinta -- "SANTA ISABEL 586" nunca coincide con "SANTA ISABEL 585");
* coincidencias con más de una identidad física (ambigüedad: nunca "la
  primera");
* lecturas del mismo documento (DESPACHAR A / dirección resuelta) que
  apunten a identidades distintas o que no coincidan con ninguna;
* una comuna del documento (localidad resuelta, código territorial o
  comuna impresa) distinta de la del destino, o ninguna comuna conocida;
* un texto no confiable (fragmento truncado o contaminado).

Sólo lectura: no modifica el dataset, el catálogo, las rutas ni los
originales/OCR, y nunca se aplica a un documento con destino confirmado por
un humano (esa identidad la fija la decisión, ver `entregas`).
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping

from atlas_core.catalogo_destinos import (
    CatalogoDestinos,
    _clave_fisica_destino,
    consolidar_destinos_equivalentes,
    direccion_confirmada_coincide,
    normalizar_nombre_destino,
)
from atlas_core.credibilidad_campos import NivelCredibilidad, evaluar_credibilidad_direccion
from atlas_core.direccion_equivalente import (
    _CIUDAD_GENERICA,
    _COMUNAS,
    _GENERICOS,
    _MAX_TOKENS_NOMBRE,
    _REGIONES,
    comuna_oficial,
    comuna_por_codigo,
)

_AUSENTES = {"", "NO ENCONTRADO", "REVISAR", "ILEGIBLE", "NO DISPONIBLE"}


@dataclass(frozen=True)
class IdentidadDestino:
    """`clave`: identidad física comparable (calle + numeración, comuna).
    `direccion`/`comuna`: representación canónica tomada del catálogo."""

    clave: str
    direccion: str
    comuna: str


def _comunas_impresas(texto: str) -> set[str]:
    """Comunas nombradas al final del texto (después de la numeración).
    Recorre desde el final nombres oficiales completos (comuna, región o
    genérico) y se detiene en el primer token que no lo sea."""
    tokens = normalizar_nombre_destino(texto).split()
    comunas: set[str] = set()
    fin = len(tokens)
    while fin > 0:
        for largo in range(min(_MAX_TOKENS_NOMBRE, fin), 0, -1):
            nombre = " ".join(tokens[fin - largo:fin])
            if nombre in _COMUNAS:
                comunas.add(nombre)
            elif not (nombre in _REGIONES or nombre in _GENERICOS):
                continue
            fin -= largo
            break
        else:
            break
    return comunas


def _efectivas(comunas: Iterable[str]) -> set[str]:
    # "SANTIAGO" acompaña a la comuna real en los documentos AZA.
    efectivas = {c for c in comunas if c}
    if len(efectivas) > 1:
        efectivas.discard(_CIUDAD_GENERICA)
    return efectivas


def _texto_confiable(texto: str) -> bool:
    limpio = str(texto or "").strip()
    return (
        limpio.upper() not in _AUSENTES
        and evaluar_credibilidad_direccion(limpio).nivel == NivelCredibilidad.CONFIABLE
    )


def _calle(texto: str) -> str:
    return normalizar_nombre_destino(str(texto or "").split(",", 1)[0])


class IndiceIdentidadDestinos:
    """Destinos ACTIVOS y CONFIRMADOS del catálogo con calle numerada,
    agrupados por identidad física."""

    def __init__(self, destinos: Iterable[object]) -> None:
        # (calle comparable, comuna oficial, clave física)
        self._calles: list[tuple[str, str, tuple]] = []
        self._destinos: dict[tuple, list] = {}
        representaciones: dict[tuple, Counter] = {}
        for destino in destinos:
            if (getattr(destino, "estado_vigencia", "") != "ACTIVO"
                    or getattr(destino, "estado_calidad", "") != "CONFIRMADO"):
                continue
            comuna = comuna_oficial(getattr(destino, "comuna", ""))
            calle = _calle(getattr(destino, "direccion", ""))
            if not comuna or not any(ch.isdigit() for ch in calle):
                continue
            clave = _clave_fisica_destino(destino)
            self._destinos.setdefault(clave, []).append(destino)
            representaciones.setdefault(clave, Counter())[
                (str(getattr(destino, "direccion", "")).split(",", 1)[0].strip(),
                 str(getattr(destino, "comuna", "")).strip())] += 1
            vistas = {calle}
            for alias in getattr(destino, "aliases", ()) or ():
                alias_calle = _calle(alias)
                if any(ch.isdigit() for ch in alias_calle):
                    vistas.add(alias_calle)
            self._calles.extend((c, comuna, clave) for c in sorted(vistas))
        # Representación determinista: la escritura más usada en el
        # catálogo para esa identidad; ante empate, la de más palabras
        # (conserva los espacios) y luego orden alfabético.
        self._representacion = {
            clave: max(conteo.items(), key=lambda par: (par[1], len(par[0][0].split()), par[0]))[0]
            for clave, conteo in representaciones.items()
        }

    @classmethod
    def desde_carpeta(cls, carpeta_catalogos: str | Path) -> "IndiceIdentidadDestinos":
        """Índice vacío si el catálogo no existe o no se puede leer: sin
        catálogo no hay identidad, y la derivación conserva su regla
        documental."""
        ruta = Path(carpeta_catalogos) / "destinos_maestros.json"
        try:
            return cls(CatalogoDestinos(ruta).listar() if ruta.is_file() else ())
        except (OSError, ValueError):
            return cls(())

    def _identidad_de_texto(self, texto: str, comuna: str) -> tuple | None:
        claves = {
            clave for calle, comuna_destino, clave in self._calles
            if comuna_destino == comuna
            and direccion_confirmada_coincide(calle, texto, comuna_confirmada=comuna_destino)
        }
        return next(iter(claves)) if len(claves) == 1 else None

    def identificar(
        self, textos: Iterable[str], *, comunas_conocidas: Iterable[str] = (),
    ) -> IdentidadDestino | None:
        """Identidad física común a todas las lecturas del documento."""
        if not self._calles:
            return None
        textos = [str(t).strip() for t in textos if str(t or "").strip().upper() not in _AUSENTES]
        if not textos or not all(_texto_confiable(t) for t in textos):
            return None
        comunas = set(comunas_conocidas)
        for texto in textos:
            comunas |= _comunas_impresas(texto)
        comunas = _efectivas(comunas)
        if len(comunas) != 1:
            return None
        comuna = next(iter(comunas))
        claves = {self._identidad_de_texto(texto, comuna) for texto in textos}
        if len(claves) != 1 or None in claves:
            return None
        clave = next(iter(claves))
        direccion, comuna_texto = self._representacion[clave]
        return IdentidadDestino(
            clave=_texto_clave(clave), direccion=direccion, comuna=comuna_texto,
        )

    def destino_con_coordenadas(self, direccion: str, comuna: str) -> object | None:
        """Destino del catálogo cuyas coordenadas CONFIRMADAS ubican una
        dirección ya confirmada por un humano (dirección + comuna), o
        ``None``.

        Casos reales 492111/483526 (VISTA CLARA 2351, CERRILLOS): la
        decisión humana nombra un lugar que el catálogo ya conoce con
        coordenadas verificadas; geocodificar de nuevo su texto devolvió
        "Santiago" y dejó la ruta pendiente. La identidad es la de
        `identificar` (misma tolerancia, misma comuna exigida); además, los
        registros de esa identidad deben ser un solo punto
        (`consolidar_destinos_equivalentes`, <=150 m). Caso real 485242
        (SANTA ISABEL 585, LAMPA): dos destinos confirmados de la misma
        obra a 535 m -- ambigüedad real, se abstiene."""
        puntos = self.puntos_confirmados(direccion, comuna)
        return puntos[0] if puntos is not None and len(puntos) == 1 else None

    def puntos_confirmados(self, direccion: str, comuna: str) -> list | None:
        """Puntos distintos (coordenadas válidas, consolidados a <=150 m)
        que el catálogo confirma para esta dirección + comuna. ``None`` si
        el catálogo no conoce esa identidad; ``[]`` si la conoce sin
        coordenadas; más de uno = ambigüedad (nunca se elige)."""
        identidad = self.identificar((direccion,), comunas_conocidas={comuna_oficial(comuna)} - {""})
        if identidad is None:
            return None
        clave = next(c for c in self._destinos if _texto_clave(c) == identidad.clave)
        validos = []
        for destino in self._destinos[clave]:
            try:
                latitud, longitud = float(destino.latitud), float(destino.longitud)
            except (TypeError, ValueError):
                continue
            if -90 <= latitud <= 90 and -180 <= longitud <= 180:
                validos.append(destino)
        return consolidar_destinos_equivalentes(validos)


def _texto_clave(clave: tuple) -> str:
    return " ".join(clave[0]) + "@" + clave[1]


def comunas_conocidas_de_fila(fila: Mapping[str, object]) -> set[str]:
    """Comunas ya establecidas para la fila: localidad resuelta y código
    territorial opaco (mismo criterio que `entregas._comunas_conocidas`)."""
    return {
        c for c in (
            comuna_oficial(str(fila.get("localidad_entrega") or "")),
            comuna_por_codigo(str(fila.get("codigo_unidad") or "")),
        ) if c
    }


def identidad_de_fila(fila: Mapping[str, object], indice: IndiceIdentidadDestinos) -> IdentidadDestino | None:
    """Identidad física de una fila documental del dataset (DESPACHAR A y
    dirección resuelta deben converger en el mismo destino confirmado)."""
    return indice.identificar(
        (fila.get("despachar_a_crudo") or "", fila.get("direccion_entrega") or ""),
        comunas_conocidas=comunas_conocidas_de_fila(fila),
    )
