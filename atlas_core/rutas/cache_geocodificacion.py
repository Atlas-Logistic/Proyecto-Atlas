"""Caché persistente de geocodificación (Pelias/ORS), Bloque INFRAESTRUCTURA S2.1.

Objetivo explícito del bloque: si casa ya geocodificó exactamente una
dirección, oficina no debe pagar otra llamada. Mismo patrón que
``atlas_core.rutas.repositorio.RepositorioRutas`` /
``atlas_core.telemetria.repositorio.RepositorioTelemetria`` (JSON con
escritura atómica) -- sin construir una base de datos nueva.

No cachea ``calcular_ruta``: ese resultado ya se cachea a nivel de
``ServicioRutas``/``RepositorioRutas`` una vez confirmado por un humano
(clave lógica planta/destino/perfil/proveedor). Cachear aquí además
duplicaría la fuente de verdad -- este módulo cubre específicamente el
hueco real: ``ProveedorRutas.geocodificar()`` se llamaba sin caché
alguna en cada `ServicioRutas.preparar()`.

La clave de caché depende únicamente de lo que cambia el resultado de
Pelias: identidad del proveedor (nombre + versión) y el texto de
dirección normalizado -- igual que ``huella_direccion`` en
``atlas_core.rutas.servicio``.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from atlas_core.almacenamiento_portable import (
    bloqueo_sesion,
    escribir_json_atomico,
    ruta_cache,
)
from atlas_core.rutas.modelos import (
    CandidatoGeocodificacion,
    Coordenadas,
    EstadoRuta,
    ResultadoGeocodificacion,
)
from atlas_core.rutas.proveedor import ProveedorRutas

VERSION_FORMATO = 1
NOMBRE_ARCHIVO_PREDETERMINADO = "geocodificacion_cache.json"


def _normalizar_direccion(direccion: str) -> str:
    texto = unicodedata.normalize("NFKD", str(direccion).strip())
    texto = "".join(c for c in texto if not unicodedata.combining(c)).upper()
    return " ".join(re.findall(r"[A-Z0-9]+", texto))


def _clave(proveedor_nombre: str, proveedor_version: str, direccion: str) -> str:
    return "|".join((proveedor_nombre, proveedor_version, _normalizar_direccion(direccion)))


class RepositorioCacheGeocodificacion:
    """JSON con escritura atómica; ubicación predeterminada portable (Drive)."""

    def __init__(self, ruta: str | Path | None = None) -> None:
        self.ruta = Path(ruta) if ruta is not None else (
            ruta_cache("geocodificacion") / NOMBRE_ARCHIVO_PREDETERMINADO
        )

    def buscar(
        self, proveedor_nombre: str, proveedor_version: str, direccion: str
    ) -> ResultadoGeocodificacion | None:
        contenido = self._leer()
        crudo = contenido.get("consultas", {}).get(
            _clave(proveedor_nombre, proveedor_version, direccion)
        )
        if crudo is None:
            return None
        return _resultado_desde_dict(crudo)

    def guardar(
        self,
        proveedor_nombre: str,
        proveedor_version: str,
        direccion: str,
        resultado: ResultadoGeocodificacion,
    ) -> None:
        with bloqueo_sesion(self.ruta.parent, "geocodificacion"):
            contenido = self._leer()
            contenido.setdefault("consultas", {})[
                _clave(proveedor_nombre, proveedor_version, direccion)
            ] = _dict_desde_resultado(resultado)
            self._escribir(contenido)

    def _leer(self) -> dict:
        if not self.ruta.exists():
            return {"version_formato": VERSION_FORMATO, "consultas": {}}
        try:
            contenido = json.loads(self.ruta.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            # Una caché corrupta nunca debe romper Atlas -- se trata como
            # vacía; la próxima consulta real la reconstruye.
            return {"version_formato": VERSION_FORMATO, "consultas": {}}
        if not isinstance(contenido, dict):
            return {"version_formato": VERSION_FORMATO, "consultas": {}}
        contenido.setdefault("consultas", {})
        return contenido

    def _escribir(self, contenido: dict) -> None:
        escribir_json_atomico(self.ruta, contenido)


def _dict_desde_resultado(resultado: ResultadoGeocodificacion) -> dict:
    return {
        "estado": resultado.estado.value,
        "motivo": resultado.motivo,
        "candidatos": [
            {
                "longitud": c.coordenadas.longitud,
                "latitud": c.coordenadas.latitud,
                "etiqueta": c.etiqueta,
                "confianza": c.confianza,
                "localidad": c.localidad,
                "region": c.region,
            }
            for c in resultado.candidatos
        ],
        "guardado_en": datetime.now(timezone.utc).isoformat(),
    }


def _resultado_desde_dict(crudo: dict) -> ResultadoGeocodificacion:
    candidatos = tuple(
        CandidatoGeocodificacion(
            Coordenadas(c["longitud"], c["latitud"]),
            c["etiqueta"],
            c.get("confianza"),
            c.get("localidad", ""),
            c.get("region", ""),
        )
        for c in crudo.get("candidatos", [])
    )
    return ResultadoGeocodificacion(EstadoRuta(crudo["estado"]), candidatos, crudo.get("motivo", ""))


@dataclass(eq=False)
class ProveedorRutasConCacheGeocodificacion:
    """Decorador: envuelve un ``ProveedorRutas`` y cachea ``geocodificar``.

    ``calcular_ruta`` se delega sin cambios -- no duplica la caché que ya
    mantiene ``RepositorioRutas`` a nivel de ``ServicioRutas``.

    ``eq=False`` deliberado: se mantiene igualdad/hash por identidad
    (como cualquier objeto normal) en vez de la igualdad por valor que
    ``@dataclass`` generaría por defecto -- el proveedor interno que
    envuelve no necesariamente es hasheable/comparable, y el código que
    consume ``ProveedorRutas`` (p. ej. para verificar que la misma
    instancia se reutiliza en todo un lote) espera identidad normal.
    """

    interno: ProveedorRutas
    repositorio: RepositorioCacheGeocodificacion

    def __post_init__(self) -> None:
        self.nombre = self.interno.nombre
        self.version = self.interno.version

    def geocodificar(self, direccion: str) -> ResultadoGeocodificacion:
        cache = self.repositorio.buscar(self.interno.nombre, self.interno.version, direccion)
        if cache is not None:
            return cache
        resultado = self.interno.geocodificar(direccion)
        # Solo se cachean resultados estables del proveedor -- nunca fallos
        # transitorios (sin conexión, límite de cuota, credencial ausente):
        # esos deben poder reintentarse en la próxima ejecución sin quedar
        # "pegados" en la caché.
        if resultado.estado in _ESTADOS_CACHEABLES:
            self.repositorio.guardar(self.interno.nombre, self.interno.version, direccion, resultado)
        return resultado

    def calcular_ruta(self, origen: Coordenadas, destino: Coordenadas, perfil: str):
        return self.interno.calcular_ruta(origen, destino, perfil)


_ESTADOS_CACHEABLES = frozenset(
    {
        EstadoRuta.REQUIERE_REVISION,
        EstadoRuta.RESULTADO_AMBIGUO,
        EstadoRuta.DIRECCION_NO_ENCONTRADA,
    }
)
