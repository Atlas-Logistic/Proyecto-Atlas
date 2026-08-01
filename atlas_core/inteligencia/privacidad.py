"""Minimización y redacción antes de cualquier proveedor reemplazable."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Mapping


_SENSIBLES = {"rut", "rut_chofer", "chofer", "nombre", "direccion"}
_IMAGENES = {"imagen", "imagen_completa", "bytes_imagen"}
_SECRETOS = re.compile(r"(api[_-]?key|token|secret|clave)", re.IGNORECASE)


@dataclass(frozen=True)
class EnvioAutorizado:
    datos: Mapping[str, object]
    campos_permitidos: tuple[str, ...]
    campos_bloqueados: tuple[str, ...]


def preparar_envio(
    datos: Mapping[str, object], permitidos: set[str]
) -> EnvioAutorizado:
    salida: dict[str, object] = {}
    bloqueados: list[str] = []
    aceptados: list[str] = []
    for campo in sorted(datos):
        if campo not in permitidos or campo in _IMAGENES or _SECRETOS.search(campo):
            bloqueados.append(campo)
            continue
        valor = datos[campo]
        salida[campo] = "[REDACTADO]" if campo in _SENSIBLES else valor
        aceptados.append(campo)
    return EnvioAutorizado(salida, tuple(aceptados), tuple(bloqueados))
