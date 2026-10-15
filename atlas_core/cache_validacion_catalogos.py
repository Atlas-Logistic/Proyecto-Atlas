"""Veredictos de validación de catálogos, por contenido exacto de archivo.

Caso medido (reconciliación focal real, 182 s): `CatalogoDestinos._leer`
y `CatalogoObrasDestinos._leer` vuelven a validar el catálogo COMPLETO en
cada consulta -- la comprobación de duplicados de destinos compara cada
destino contra todos los demás (~0,2 s de CPU por lectura) y la de obras
además relee clientes y destinos para comprobar referencias. Una sola
reconciliación hacía cientos de esas lecturas sobre el mismo contenido.

Aquí sólo se recuerda QUE un contenido exacto ya pasó la validación: la
lectura, el parseo y la construcción de objetos siguen haciéndose en cada
llamada con el código de siempre (objetos nuevos, nunca compartidos). La
clave es el sha256 de cada archivo del que depende la validación; si
cualquiera cambia -- desde este proceso o desde otro --, la clave cambia y
se valida de nuevo. Una validación fallida nunca se recuerda: el mismo
contenido inválido vuelve a lanzar la misma excepción.

`ATLAS_CACHE_VALIDACION_CATALOGOS=0` lo desactiva (validación completa en
cada lectura, como antes)."""
from __future__ import annotations

import hashlib
import os
import threading
from pathlib import Path

VARIABLE_DESACTIVAR = "ATLAS_CACHE_VALIDACION_CATALOGOS"
_MAXIMO_VEREDICTOS = 64

_validados: dict[tuple[object, ...], None] = {}
_lock = threading.Lock()


def _activo() -> bool:
    return os.environ.get(VARIABLE_DESACTIVAR, "1").strip() != "0"


def huella_contenido(tipo: str, *rutas: str | Path) -> tuple[object, ...] | None:
    """Huella (tipo + ruta absoluta + sha256 del contenido) de los archivos
    de los que depende una validación. `None` si el caché está desactivado
    o algún archivo no se pudo leer -- el llamador valida como siempre."""
    if not _activo():
        return None
    partes: list[object] = [tipo]
    for ruta in rutas:
        try:
            contenido = Path(ruta).read_bytes()
        except OSError:
            return None
        partes.append((os.path.normcase(os.path.abspath(ruta)), hashlib.sha256(contenido).hexdigest()))
    return tuple(partes)


def ya_validado(huella: tuple[object, ...] | None) -> bool:
    if huella is None:
        return False
    with _lock:
        return huella in _validados


def registrar_validado(huella: tuple[object, ...] | None) -> None:
    if huella is None:
        return
    with _lock:
        _validados.pop(huella, None)
        _validados[huella] = None
        while len(_validados) > _MAXIMO_VEREDICTOS:
            _validados.pop(next(iter(_validados)))


def limpiar() -> None:
    with _lock:
        _validados.clear()
