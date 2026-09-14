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
    """Bloque OPTIMIZACIÓN SEGURA DE LATENCIA EN TELEMETRÍA -- causa raíz
    medida (2026-09-14): `_leer()` releía y reparseaba `telemetria_cache.
    json` completo (~6,4 MB) en CADA llamada -- una sola aplicación de
    decisión disparaba 741 relecturas del mismo archivo dentro de
    `revalidar_ruta_por_convergencia_gps_historica_sin_ocr` (~39s de los
    ~64s totales). El contenido nunca cambia entre dos llamadas de la
    MISMA instancia salvo que ESA MISMA instancia lo escriba -- por eso
    basta con una caché EN MEMORIA por instancia (`self._cache`), nunca
    global/singleton (cada revalidador sigue construyendo su propia
    instancia, con su propio alcance -- nunca una vida artificialmente
    extendida ni compartida entre revalidadores distintos). Primera
    lectura toca disco; lecturas posteriores de la misma instancia
    reutilizan `self._cache`; `guardar_viajes`/`guardar_breadcrumbs`
    actualizan `self._cache` en el mismo momento en que escriben a disco
    -- nunca queda desincronizado dentro de la vida de la instancia.
    Cambios externos al archivo hechos por OTRA instancia/proceso
    durante la vida de ÉSTA no se ven -- exactamente el mismo supuesto
    ya vigente para cualquier revalidador de una sola pasada (construye
    su propia instancia, la usa, la descarta)."""

    def __init__(self, ruta: str | Path = "catalogos/telemetria_cache.json") -> None:
        self.ruta = Path(ruta)
        self._cache: dict | None = None

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
        """Contenido vigente para ESTA instancia -- disco sólo en la
        PRIMERA llamada (`self._cache is None`); de ahí en más, la copia
        en memoria (ver docstring de la clase). Devuelve el mismo objeto
        `dict` en cada llamada (nunca una copia) a propósito:
        `guardar_viajes`/`guardar_breadcrumbs` mutan ese mismo objeto
        antes de persistirlo, así que la caché queda al día sin ningún
        paso adicional."""
        if self._cache is None:
            self._cache = self._leer_desde_disco()
        return self._cache

    def _leer_desde_disco(self) -> dict:
        """Lectura real de disco -- nunca se llama más de una vez por
        instancia (ver `_leer`). Separada de `_leer` para que un test
        pueda espiar/contar exactamente cuántas veces se tocó el disco,
        sin depender de mockear `Path.read_text` directamente."""
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
        # La escritura tuvo éxito -- `contenido` (ya mutado por
        # `guardar_viajes`/`guardar_breadcrumbs`) pasa a ser la caché
        # vigente de esta instancia, para que una lectura inmediatamente
        # posterior (misma instancia) vea el dato recién escrito sin
        # volver a tocar disco.
        self._cache = contenido
