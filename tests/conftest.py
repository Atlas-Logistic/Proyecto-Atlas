"""Fixtures compartidas -- INFRAESTRUCTURA S2.1.

Aísla la suite de pruebas del entorno portable real (``ATLAS_DATA_DIR`` y
la autodetección de Google Drive) para que ningún test pueda escribir
accidentalmente en el Drive real de quien ejecuta `pytest`, sin importar
qué tenga configurado su PC.
"""

from __future__ import annotations

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
    monkeypatch.setattr(
        "atlas_core.almacenamiento_portable.autodetectar_raiz_drive",
        lambda: None,
    )
