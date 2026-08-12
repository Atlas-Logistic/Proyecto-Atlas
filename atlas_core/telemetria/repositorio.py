"""Caché JSON simple de telemetría (Bloque TELEMETRÍA T1, Fase M).

Objetivo explícito del bloque: "una consulta histórica real no se vuelve
a pagar cada vez que abrimos Desktop". Persistencia mínima, misma familia
de patrón que `atlas_core.rutas.repositorio.RepositorioRutas` (JSON con
escritura atómica) -- sin construir una base de datos nueva.

No cachea breadcrumbs completos dentro de `viajes.csv` -- viven aquí,
separados (Bloque N, observabilidad).
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import date
from pathlib import Path

from atlas_core.telemetria.modelos import PosicionTelemetria, ViajeTelemetria

VERSION_FORMATO = 1


def _clave_viajes(proveedor: str, patente: str, desde: date, hasta: date) -> str:
    return f"{proveedor}|{patente.strip().upper()}|{desde.isoformat()}|{hasta.isoformat()}"


def _clave_breadcrumbs(proveedor: str, trip_id: str) -> str:
    return f"{proveedor}|{trip_id}"


class RepositorioTelemetria:
    def __init__(self, ruta: str | Path = "catalogos/telemetria_cache.json") -> None:
        self.ruta = Path(ruta)

    def buscar_viajes(
        self, proveedor: str, patente: str, desde: date, hasta: date
    ) -> list[ViajeTelemetria] | None:
        contenido = self._leer()
        crudo = contenido.get("viajes", {}).get(_clave_viajes(proveedor, patente, desde, hasta))
        if crudo is None:
            return None
        return [ViajeTelemetria(**item) for item in crudo]

    def guardar_viajes(
        self, proveedor: str, patente: str, desde: date, hasta: date,
        viajes: tuple[ViajeTelemetria, ...],
    ) -> None:
        contenido = self._leer()
        contenido.setdefault("viajes", {})[_clave_viajes(proveedor, patente, desde, hasta)] = [
            v.a_dict() for v in viajes
        ]
        self._escribir(contenido)

    def buscar_breadcrumbs(
        self, proveedor: str, trip_id: str
    ) -> list[PosicionTelemetria] | None:
        contenido = self._leer()
        crudo = contenido.get("breadcrumbs", {}).get(_clave_breadcrumbs(proveedor, trip_id))
        if crudo is None:
            return None
        return [PosicionTelemetria(**item) for item in crudo]

    def guardar_breadcrumbs(
        self, proveedor: str, trip_id: str, puntos: tuple[PosicionTelemetria, ...]
    ) -> None:
        contenido = self._leer()
        contenido.setdefault("breadcrumbs", {})[_clave_breadcrumbs(proveedor, trip_id)] = [
            p.a_dict() for p in puntos
        ]
        self._escribir(contenido)

    def _leer(self) -> dict:
        if not self.ruta.exists():
            return {"version_formato": VERSION_FORMATO, "viajes": {}, "breadcrumbs": {}}
        try:
            contenido = json.loads(self.ruta.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            # Una caché corrupta nunca debe romper Atlas -- se trata como
            # vacía; la próxima consulta real la reconstruye.
            return {"version_formato": VERSION_FORMATO, "viajes": {}, "breadcrumbs": {}}
        if not isinstance(contenido, dict):
            return {"version_formato": VERSION_FORMATO, "viajes": {}, "breadcrumbs": {}}
        contenido.setdefault("viajes", {})
        contenido.setdefault("breadcrumbs", {})
        return contenido

    def _escribir(self, contenido: dict) -> None:
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        temporal: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", newline="\n", dir=self.ruta.parent,
                prefix=f".{self.ruta.name}.", suffix=".tmp", delete=False,
            ) as archivo:
                temporal = Path(archivo.name)
                json.dump(contenido, archivo, ensure_ascii=False, indent=2)
                archivo.write("\n")
                archivo.flush()
                os.fsync(archivo.fileno())
            os.replace(temporal, self.ruta)
        except OSError:
            if temporal is not None:
                temporal.unlink(missing_ok=True)
            raise
