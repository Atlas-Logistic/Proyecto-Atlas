"""Caché inmutable en memoria para rutas 1E, sin I/O productivo."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Hashable, Protocol

from atlas_core.rutas.contrato_multicampo import ResultadoRutaMulticampo


ClaveCacheRuta = tuple[Hashable, ...]


class CacheRutasMulticampo(Protocol):
    def obtener(self, clave: ClaveCacheRuta) -> ResultadoRutaMulticampo | None: ...

    def guardar(
        self, clave: ClaveCacheRuta, resultado: ResultadoRutaMulticampo
    ) -> ResultadoRutaMulticampo: ...


@dataclass
class CacheRutasMemoria:
    """Repositorios iguales reutilizan el registro; nunca guardan fallos."""

    _registros: dict[ClaveCacheRuta, ResultadoRutaMulticampo] = field(
        default_factory=dict
    )

    def obtener(self, clave: ClaveCacheRuta) -> ResultadoRutaMulticampo | None:
        return self._registros.get(clave)

    def guardar(
        self, clave: ClaveCacheRuta, resultado: ResultadoRutaMulticampo
    ) -> ResultadoRutaMulticampo:
        existente = self._registros.get(clave)
        if existente is not None:
            return existente
        self._registros[clave] = resultado
        return resultado

    def cantidad(self) -> int:
        return len(self._registros)
