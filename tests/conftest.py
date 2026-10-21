"""Fixtures compartidas -- INFRAESTRUCTURA S2.1.

Aísla la suite de pruebas del entorno portable real (``ATLAS_DATA_DIR`` y
la autodetección de Google Drive) para que ningún test pueda escribir
accidentalmente en el Drive real de quien ejecuta `pytest`, sin importar
qué tenga configurado su PC.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _aislar_almacenamiento_portable(monkeypatch):
    """Nunca dejar que un test real toque ATLAS_DATA_DIR ni Drive real.

    - Elimina ATLAS_DATA_DIR del entorno para cada test (algunos tests
      lo definen explícitamente vía `monkeypatch.setenv`, lo cual sigue
      funcionando porque `monkeypatch` restaura el valor original al
      final del test, no lo que este fixture hizo).
    - Reemplaza `autodetectar_raiz_drive` por una versión que siempre
      devuelve `None`, salvo que un test la reemplace explícitamente
      (p. ej. para probar la propia autodetección con un `tmp_path`).
    """
    monkeypatch.delenv("ATLAS_DATA_DIR", raising=False)
    # Sin token Cloud ningún test puede tomar el lease real de escritor
    # (lo usa el PULL de producción en este mismo PC).
    monkeypatch.delenv("ATLAS_CLOUD_MOTOR_TOKEN", raising=False)
    monkeypatch.setattr(
        "atlas_core.almacenamiento_portable.autodetectar_raiz_drive",
        lambda: None,
    )


# Perfil separado antes de importar/coleccionar tests, ademas de uno por test.
# Los hijos Python heredan estas rutas aunque no carguen fixtures de pytest.
def _entorno_perfil(raiz):
    home = Path(raiz) / "usuario"
    local = home / "AppData" / "Local"
    roaming = home / "AppData" / "Roaming"
    local.mkdir(parents=True, exist_ok=True)
    roaming.mkdir(parents=True, exist_ok=True)
    return {
        "LOCALAPPDATA": str(local),
        "APPDATA": str(roaming),
        "USERPROFILE": str(home),
        "HOME": str(home),
        "HOMEDRIVE": home.drive,
        "HOMEPATH": str(home)[len(home.drive):],
        "ATLAS_CACHE_DIR": str(local / "Atlas" / "cache"),
        "ATLAS_DIAGNOSTICO_DIR": str(local / "Atlas" / "diagnostico"),
        "ATLAS_OPERACION_CONFIG": str(local / "Atlas" / "desktop_operacion.json"),
        "ATLAS_PADDLE_RUNTIME": str(local / "Atlas" / "runtime" / "paddleocr"),
        "ATLAS_PULL_LOG_DIR": str(local / "Atlas" / "logs" / "pull_ciclos"),
    }


def _guardia_escrituras_atlas(raices):
    """Defensa de tests ante rutas absolutas/overrides mal configurados.

    Protege el Atlas real y las operaciones sobre sus padres (rename/rmtree).
    No cambia funciones productivas, permisos, autorizacion ni exclusividad.
    """
    protegidas = tuple(Path(r).resolve() for r in raices)

    def auditar(evento, args):
        if evento == "open":
            ruta, modo, flags = args
            if not ((modo and any(c in modo for c in "wax+")) or
                    (flags and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND))):
                return
            destinos = [ruta]
        elif evento in {"os.rename", "os.link", "os.symlink"}:
            destinos = args[:2]
        elif evento in {"os.remove", "os.rmdir", "os.mkdir", "os.chmod", "os.chown",
                        "os.utime", "os.truncate", "shutil.rmtree"}:
            destinos = args[:1]
        else:
            return
        for ruta in destinos:
            if isinstance(ruta, int) or ruta is None:
                continue
            real = Path(os.fsdecode(ruta)).resolve()
            if any(real.is_relative_to(p) or p.is_relative_to(real) for p in protegidas):
                raise PermissionError("Pytest: configuracion real de Atlas protegida: " + str(real))

    return auditar


def pytest_configure(config):
    # Capturar las rutas REALES antes de sustituir cualquier variable.
    home_real = Path.home()
    local_real = Path(os.environ.get("LOCALAPPDATA") or home_real / "AppData" / "Local")
    guardia = _guardia_escrituras_atlas({local_real / "Atlas",
                                               home_real / "AppData" / "Local" / "Atlas",
                                               home_real / ".local" / "Atlas"})
    sys.addaudithook(guardia)
    temporal = tempfile.TemporaryDirectory(prefix="atlas-pytest-perfil-")
    entorno = _entorno_perfil(temporal.name)
    anteriores = {k: os.environ.get(k) for k in entorno}
    os.environ.update(entorno)
    config._atlas_perfil_aislado = (temporal, anteriores)


def pytest_unconfigure(config):
    perfil = getattr(config, "_atlas_perfil_aislado", None)
    if perfil is None:
        return
    temporal, anteriores = perfil
    try:
        temporal.cleanup()
    finally:
        for clave, valor in anteriores.items():
            if valor is None:
                os.environ.pop(clave, None)
            else:
                os.environ[clave] = valor
        # El hook sigue protegiendo hasta salir del proceso, incluido atexit.


@pytest.fixture(autouse=True)
def _aislar_perfil_atlas(tmp_path_factory, monkeypatch):
    # LOCALAPPDATA y home cubren consumidores que ignoran overrides de Atlas,
    # y continuan aislados si el test elimina esos overrides para probar fallbacks.
    for clave, valor in _entorno_perfil(tmp_path_factory.mktemp("perfil_atlas")).items():
        monkeypatch.setenv(clave, valor)
