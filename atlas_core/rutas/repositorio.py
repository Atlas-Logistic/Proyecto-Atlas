"""Repositorio JSON privado de rutas con escritura atómica e historial."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import replace
from pathlib import Path
from typing import Iterable

from atlas_core.rutas.modelos import ErrorRutas, RegistroRuta


VERSION_FORMATO = 1


class CatalogoRutasCorruptoError(ErrorRutas):
    pass


class RutaDuplicadaError(ErrorRutas):
    pass


class RutaNoEncontradaError(ErrorRutas):
    pass


class RepositorioRutas:
    def __init__(self, ruta: str | Path = "catalogos/rutas.json") -> None:
        self.ruta = Path(ruta)

    def listar(self) -> list[RegistroRuta]:
        return list(self._leer())

    def obtener(self, ruta_id: str) -> RegistroRuta:
        for ruta in self._leer():
            if ruta.ruta_id == str(ruta_id).strip():
                return ruta
        raise RutaNoEncontradaError(f"No existe la ruta {ruta_id!r}")

    def buscar_vigente(
        self, clave: tuple[str, str, str, str, str],
        huella_origen: str, huella_destino: str,
    ) -> RegistroRuta | None:
        for ruta in self._leer():
            if (ruta.vigente and ruta.clave_logica == clave
                    and ruta.huella_direccion_origen == huella_origen
                    and ruta.huella_direccion_destino == huella_destino):
                return ruta
        return None

    def guardar(self, nueva: RegistroRuta) -> RegistroRuta:
        rutas = self._leer()
        if any(r.ruta_id == nueva.ruta_id for r in rutas):
            raise RutaDuplicadaError("ruta_id duplicado")
        for existente in rutas:
            if (existente.clave_logica == nueva.clave_logica
                    and existente.huella_direccion_origen == nueva.huella_direccion_origen
                    and existente.huella_direccion_destino == nueva.huella_direccion_destino):
                raise RutaDuplicadaError("la ruta lógica vigente ya fue calculada")
        rutas = [
            replace(r, vigente=False, fecha_modificacion=nueva.fecha_modificacion)
            if r.vigente and r.clave_logica == nueva.clave_logica else r
            for r in rutas
        ]
        rutas.append(nueva)
        self._escribir(rutas)
        return nueva

    def _leer(self) -> list[RegistroRuta]:
        if not self.ruta.exists():
            return []
        try:
            contenido = json.loads(self.ruta.read_text(encoding="utf-8"))
            if (not isinstance(contenido, dict)
                    or contenido.get("version_formato") != VERSION_FORMATO
                    or not isinstance(contenido.get("rutas"), list)):
                raise CatalogoRutasCorruptoError("raíz o versión incompatible")
            rutas = [RegistroRuta.desde_dict(item) for item in contenido["rutas"]]
        except (OSError, json.JSONDecodeError, ErrorRutas, TypeError) as error:
            if isinstance(error, CatalogoRutasCorruptoError):
                raise
            raise CatalogoRutasCorruptoError(str(error)) from error
        ids = [ruta.ruta_id for ruta in rutas]
        if len(ids) != len(set(ids)):
            raise CatalogoRutasCorruptoError("IDs duplicados")
        vigentes = [ruta.clave_logica for ruta in rutas if ruta.vigente]
        if len(vigentes) != len(set(vigentes)):
            raise CatalogoRutasCorruptoError("claves lógicas vigentes duplicadas")
        return rutas

    def _escribir(self, rutas: Iterable[RegistroRuta]) -> None:
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        temporal: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", newline="\n", dir=self.ruta.parent,
                prefix=f".{self.ruta.name}.", suffix=".tmp", delete=False,
            ) as archivo:
                temporal = Path(archivo.name)
                json.dump({"version_formato": VERSION_FORMATO,
                           "rutas": [ruta.a_dict() for ruta in rutas]},
                          archivo, ensure_ascii=False, indent=2)
                archivo.write("\n")
                archivo.flush()
                os.fsync(archivo.fileno())
            os.replace(temporal, self.ruta)
        except OSError:
            if temporal is not None:
                temporal.unlink(missing_ok=True)
            raise
