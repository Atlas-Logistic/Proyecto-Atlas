"""Servicio de aplicación de rutas, aislado de OCR y producción."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import datetime, timezone
from typing import Callable
from uuid import uuid4

from atlas_core.rutas.modelos import (
    Coordenadas, EstadoRuta, RegistroRuta, ResultadoServicioRutas,
)
from atlas_core.rutas.proveedor import ProveedorRutas
from atlas_core.rutas.repositorio import RepositorioRutas


class ServicioRutas:
    def __init__(
        self, proveedor: ProveedorRutas, repositorio: RepositorioRutas,
        *, reloj: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        generador_id: Callable[[], object] = uuid4,
    ) -> None:
        self.proveedor = proveedor
        self.repositorio = repositorio
        self._reloj = reloj
        self._generador_id = generador_id

    def preparar(self, planta: object, destino: object, perfil: str) -> ResultadoServicioRutas:
        error = self._validar_entidades(planta, destino)
        if error:
            return ResultadoServicioRutas(EstadoRuta.REQUIERE_REVISION, error)
        direccion_origen = construir_direccion(planta)
        direccion_destino = construir_direccion(destino)
        huella_origen = huella_direccion(direccion_origen)
        huella_destino = huella_direccion(direccion_destino)
        clave = self._clave(planta, destino, perfil)
        cache = self.repositorio.buscar_vigente(clave, huella_origen, huella_destino)
        if cache:
            return ResultadoServicioRutas(
                EstadoRuta.RESULTADO_DESDE_CACHE, "RUTA_REUTILIZADA", ruta=cache
            )
        origen = self.proveedor.geocodificar(direccion_origen)
        if origen.estado != EstadoRuta.REQUIERE_REVISION:
            return ResultadoServicioRutas(origen.estado, origen.motivo, origen=origen)
        destino_geo = self.proveedor.geocodificar(direccion_destino)
        if destino_geo.estado != EstadoRuta.REQUIERE_REVISION:
            return ResultadoServicioRutas(
                destino_geo.estado, destino_geo.motivo, origen=origen, destino=destino_geo
            )
        return ResultadoServicioRutas(
            EstadoRuta.REQUIERE_REVISION, "CONFIRMAR_CANDIDATOS",
            origen=origen, destino=destino_geo,
        )

    def confirmar_y_calcular(
        self, planta: object, destino: object, perfil: str,
        coordenadas_origen: Coordenadas, coordenadas_destino: Coordenadas,
        *, confirmacion_explicita: bool,
    ) -> ResultadoServicioRutas:
        if not confirmacion_explicita:
            return ResultadoServicioRutas(
                EstadoRuta.REQUIERE_REVISION, "FALTA_CONFIRMACION_EXPLICITA"
            )
        error = self._validar_entidades(planta, destino)
        if error:
            return ResultadoServicioRutas(EstadoRuta.REQUIERE_REVISION, error)
        direccion_origen = construir_direccion(planta)
        direccion_destino = construir_direccion(destino)
        huella_origen = huella_direccion(direccion_origen)
        huella_destino = huella_direccion(direccion_destino)
        clave = self._clave(planta, destino, perfil)
        cache = self.repositorio.buscar_vigente(clave, huella_origen, huella_destino)
        if cache:
            return ResultadoServicioRutas(
                EstadoRuta.RESULTADO_DESDE_CACHE, "RUTA_REUTILIZADA", ruta=cache
            )
        calculo = self.proveedor.calcular_ruta(
            coordenadas_origen, coordenadas_destino, perfil
        )
        if calculo.estado != EstadoRuta.RUTA_CALCULADA:
            return ResultadoServicioRutas(calculo.estado, calculo.motivo)
        instante = self._instante()
        ruta = RegistroRuta(
            ruta_id=str(self._generador_id()), planta_id=planta.planta_id,
            destino_id=destino.destino_id, perfil_ruta=perfil,
            proveedor=self.proveedor.nombre, version_proveedor=self.proveedor.version,
            distancia_km=calculo.distancia_km, duracion_estimada_min=calculo.duracion_estimada_min,
            longitud_origen=coordenadas_origen.longitud, latitud_origen=coordenadas_origen.latitud,
            longitud_destino=coordenadas_destino.longitud, latitud_destino=coordenadas_destino.latitud,
            direccion_origen_normalizada=normalizar_direccion(direccion_origen),
            direccion_destino_normalizada=normalizar_direccion(direccion_destino),
            huella_direccion_origen=huella_origen, huella_direccion_destino=huella_destino,
            estado=EstadoRuta.RUTA_CALCULADA.value, motivo="CONFIRMACION_EXPLICITA",
            vigente=True, fecha_calculo=instante, fecha_creacion=instante,
            fecha_modificacion=instante,
        )
        self.repositorio.guardar(ruta)
        return ResultadoServicioRutas(EstadoRuta.RUTA_CALCULADA, ruta=ruta)

    def _clave(self, planta: object, destino: object, perfil: str):
        return (planta.planta_id, destino.destino_id, str(perfil).strip(),
                self.proveedor.nombre, self.proveedor.version)

    @staticmethod
    def _validar_entidades(planta: object, destino: object) -> str:
        if planta is None or destino is None:
            return "ENTIDAD_NO_EXISTE"
        if getattr(planta, "estado_calidad", "") != "CONFIRMADA":
            return "PLANTA_NO_CONFIRMADA"
        if getattr(planta, "estado_vigencia", "") != "ACTIVA":
            return "PLANTA_INACTIVA"
        if getattr(destino, "estado_calidad", "") != "CONFIRMADO":
            return "DESTINO_NO_CONFIRMADO"
        if getattr(destino, "estado_vigencia", "") != "ACTIVO":
            return "DESTINO_INACTIVO"
        for entidad, prefijo in ((planta, "PLANTA"), (destino, "DESTINO")):
            if any(not str(getattr(entidad, campo, "")).strip()
                   for campo in ("direccion", "comuna", "region", "pais")):
                return f"{prefijo}_DIRECCION_INCOMPLETA"
        return ""

    def _instante(self) -> str:
        instante = self._reloj()
        if instante.tzinfo is None:
            instante = instante.replace(tzinfo=timezone.utc)
        return instante.astimezone(timezone.utc).isoformat()


def construir_direccion(entidad: object) -> str:
    return ", ".join(str(getattr(entidad, campo)).strip()
                     for campo in ("direccion", "comuna", "region", "pais"))


def normalizar_direccion(direccion: str) -> str:
    texto = unicodedata.normalize("NFKD", direccion.strip())
    texto = "".join(c for c in texto if not unicodedata.combining(c)).upper()
    return " ".join(re.findall(r"[A-Z0-9]+", texto))


def huella_direccion(direccion: str) -> str:
    return hashlib.sha256(normalizar_direccion(direccion).encode("utf-8")).hexdigest()
