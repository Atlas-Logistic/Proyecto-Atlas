"""Guardia de mutaciones del PULL bajo su lease; no sustituye arbitraje remoto."""
from contextlib import contextmanager
import os
from pathlib import Path
import sys

_activas = []


def _auditar(evento, args):
    if not _activas:
        return
    if evento == "open":
        ruta, modo, flags = args
        if not ((modo and any(c in modo for c in "wax+")) or
                (flags and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND))):
            return
        destinos = [ruta]
    elif evento in {"os.rename", "os.link", "os.symlink"}:
        destinos = args[:2]
    elif evento in {"os.mkdir", "os.remove", "os.rmdir", "os.chmod", "os.utime", "os.truncate"}:
        destinos = args[:1]
    else:
        return
    for destino in destinos:
        if isinstance(destino, int) or destino is None:
            continue
        real = Path(os.fsdecode(destino)).resolve()
        for raiz, vigente in tuple(_activas):
            if real.is_relative_to(raiz) and not vigente():
                raise PermissionError("Lease PULL perdido: escritura operacional detenida.")


sys.addaudithook(_auditar)


@contextmanager
def proteger_escrituras(raiz, vigente):
    entrada = (Path(raiz).resolve(), vigente)
    if not vigente():
        raise PermissionError("Lease PULL no vigente.")
    _activas.append(entrada)
    try:
        yield
    finally:
        _activas.remove(entrada)
