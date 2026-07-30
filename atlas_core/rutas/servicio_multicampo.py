"""Servicio aislado de cálculo vial para el Motor Multicampo 1E."""

from __future__ import annotations

import hashlib
import math
import re
import unicodedata
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Callable, Mapping

from atlas_core.rutas.cache_multicampo import CacheRutasMulticampo
from atlas_core.rutas.contrato_multicampo import (
    EstadoCalculoMulticampo,
    ResultadoRutaMulticampo,
    SolicitudRutaMulticampo,
)
from atlas_core.rutas.modelos import Coordenadas, ErrorRutas, EstadoRuta
from atlas_core.rutas.proveedor import ProveedorRutas


_PLANTAS = frozenset({"AZA COLINA", "AZA RENCA"})
_PERFIL = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class ServicioRutasMulticampo:
    def __init__(
        self,
        proveedor: ProveedorRutas,
        cache: CacheRutasMulticampo,
        *,
        reloj: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self.proveedor = proveedor
        self.cache = cache
        self._reloj = reloj

    def calcular(
        self, solicitud: SolicitudRutaMulticampo
    ) -> ResultadoRutaMulticampo:
        base = self._base(solicitud)
        abstencion = self._validar(solicitud, base)
        if abstencion is not None:
            return abstencion
        try:
            origen = _coordenadas(solicitud.coordenadas_origen)
            destino = _coordenadas(solicitud.coordenadas_destino)
        except (ErrorRutas, KeyError, TypeError, ValueError):
            return self._fallo(
                base,
                EstadoCalculoMulticampo.PENDIENTE_COORDENADAS,
                "COORDENADAS_INVALIDAS",
            )
        base["coordenadas_origen"] = origen.a_dict()
        base["coordenadas_destino"] = destino.a_dict()
        clave = self._clave(solicitud, origen, destino)
        anterior = self.cache.obtener(clave)
        if anterior is not None:
            return replace(
                anterior,
                razones=(*anterior.razones, "CACHE_REUTILIZADA"),
                desde_cache=True,
            )
        try:
            calculo = self.proveedor.calcular_ruta(
                origen, destino, solicitud.perfil_ruta
            )
        except Exception:  # frontera del proveedor; nunca expone el detalle
            return self._fallo(
                base,
                EstadoCalculoMulticampo.ERROR_PROVEEDOR,
                "EXCEPCION_CONTROLADA_DEL_PROVEEDOR",
            )
        if calculo.estado is not EstadoRuta.RUTA_CALCULADA:
            return self._fallo(
                base,
                _traducir_estado(calculo.estado),
                calculo.motivo or calculo.estado.value,
            )
        try:
            distancia = float(calculo.distancia_km)
            duracion = float(calculo.duracion_estimada_min)
            if any(
                not math.isfinite(valor) or valor <= 0
                for valor in (distancia, duracion)
            ):
                raise ValueError
        except (TypeError, ValueError):
            return self._fallo(
                base,
                EstadoCalculoMulticampo.ERROR_PROVEEDOR,
                "METRICAS_INVALIDAS_DEL_PROVEEDOR",
            )
        distancia_redondeada = _redondear(distancia, 3)
        resultado = ResultadoRutaMulticampo(
            **base,
            distancia_ida_km=distancia_redondeada,
            duracion_ida_minutos=_redondear(duracion, 2),
            distancia_ida_vuelta_km=(
                _redondear(distancia_redondeada * 2, 3)
                if solicitud.calcular_ida_vuelta else None
            ),
            fecha_calculo=self._fecha(),
            estado_calculo=EstadoCalculoMulticampo.CALCULADO,
            razones=("RUTA_VIAL_CALCULADA",),
            requiere_revision=False,
        )
        return self.cache.guardar(clave, resultado)

    def _validar(
        self,
        solicitud: SolicitudRutaMulticampo,
        base: dict[str, object],
    ) -> ResultadoRutaMulticampo | None:
        if not solicitud.planta_resuelta or not solicitud.id_origen_canonico:
            return self._fallo(
                base, EstadoCalculoMulticampo.PENDIENTE_PLANTA,
                "PLANTA_NO_RESUELTA",
            )
        if _normalizar(solicitud.planta_salida) not in _PLANTAS:
            return self._fallo(
                base, EstadoCalculoMulticampo.REQUIERE_REVISION,
                "PLANTA_NO_OPERACIONAL_O_CONTRADICTORIA",
            )
        if not solicitud.destino_resuelto or not solicitud.id_destino_canonico:
            return self._fallo(
                base, EstadoCalculoMulticampo.PENDIENTE_DESTINO,
                "DESTINO_NO_RESUELTO",
            )
        if solicitud.contradicciones:
            return self._fallo(
                base, EstadoCalculoMulticampo.REQUIERE_REVISION,
                "EVIDENCIA_CONTRADICTORIA",
            )
        if not solicitud.direccion_origen.strip() or not solicitud.direccion_destino.strip():
            return self._fallo(
                base, EstadoCalculoMulticampo.PENDIENTE_COORDENADAS,
                "DIRECCION_CANONICA_AUSENTE",
            )
        if (
            solicitud.coordenadas_origen is None
            or solicitud.coordenadas_destino is None
        ):
            return self._fallo(
                base, EstadoCalculoMulticampo.PENDIENTE_COORDENADAS,
                "COORDENADAS_AUSENTES",
            )
        if not solicitud.fuente_coordenadas.strip():
            return self._fallo(
                base, EstadoCalculoMulticampo.PENDIENTE_COORDENADAS,
                "FUENTE_COORDENADAS_AUSENTE",
            )
        if (
            solicitud.proveedor.strip() != self.proveedor.nombre
            or not solicitud.perfil_ruta.strip()
            or not _PERFIL.fullmatch(solicitud.perfil_ruta)
            or not solicitud.version_parametros.strip()
        ):
            return self._fallo(
                base, EstadoCalculoMulticampo.REQUIERE_REVISION,
                "PARAMETROS_DE_RUTA_INVALIDOS",
            )
        return None

    def _clave(
        self,
        solicitud: SolicitudRutaMulticampo,
        origen: Coordenadas,
        destino: Coordenadas,
    ) -> tuple[object, ...]:
        return (
            solicitud.id_origen_canonico,
            solicitud.id_destino_canonico,
            origen.longitud,
            origen.latitud,
            destino.longitud,
            destino.latitud,
            _huella(solicitud.direccion_origen),
            _huella(solicitud.direccion_destino),
            self.proveedor.nombre,
            self.proveedor.version,
            solicitud.perfil_ruta,
            solicitud.version_parametros,
        )

    @staticmethod
    def _base(solicitud: SolicitudRutaMulticampo) -> dict[str, object]:
        return {
            "id_origen_canonico": solicitud.id_origen_canonico,
            "planta_salida": solicitud.planta_salida,
            "direccion_origen": solicitud.direccion_origen,
            "coordenadas_origen": None,
            "id_destino_canonico": solicitud.id_destino_canonico,
            "destino": solicitud.destino,
            "direccion_destino": solicitud.direccion_destino,
            "coordenadas_destino": None,
            "proveedor": solicitud.proveedor,
            "perfil_ruta": solicitud.perfil_ruta,
            "version_parametros": solicitud.version_parametros,
            "fuente_coordenadas": solicitud.fuente_coordenadas,
        }

    @staticmethod
    def _fallo(
        base: Mapping[str, object],
        estado: EstadoCalculoMulticampo,
        razon: str,
    ) -> ResultadoRutaMulticampo:
        return ResultadoRutaMulticampo(
            **base,
            distancia_ida_km=None,
            duracion_ida_minutos=None,
            distancia_ida_vuelta_km=None,
            fecha_calculo=None,
            estado_calculo=estado,
            razones=(razon,),
            requiere_revision=True,
        )

    def _fecha(self) -> str:
        instante = self._reloj()
        if instante.tzinfo is None:
            instante = instante.replace(tzinfo=timezone.utc)
        return instante.astimezone(timezone.utc).isoformat()


def _coordenadas(valor: object) -> Coordenadas:
    if isinstance(valor, Coordenadas):
        return valor
    if isinstance(valor, Mapping):
        return Coordenadas(float(valor["longitud"]), float(valor["latitud"]))
    if isinstance(valor, (tuple, list)) and len(valor) == 2:
        return Coordenadas(float(valor[0]), float(valor[1]))
    raise TypeError("formato de coordenadas no soportado")


def _traducir_estado(estado: EstadoRuta) -> EstadoCalculoMulticampo:
    if estado is EstadoRuta.SIN_CREDENCIAL:
        return EstadoCalculoMulticampo.SIN_CREDENCIAL
    if estado is EstadoRuta.DIRECCION_NO_ENCONTRADA:
        return EstadoCalculoMulticampo.SIN_RUTA
    if estado in {EstadoRuta.RESULTADO_AMBIGUO, EstadoRuta.REQUIERE_REVISION}:
        return EstadoCalculoMulticampo.REQUIERE_REVISION
    return EstadoCalculoMulticampo.ERROR_PROVEEDOR


def _normalizar(valor: str) -> str:
    texto = unicodedata.normalize("NFKD", str(valor).strip())
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return " ".join(re.findall(r"[A-Z0-9]+", texto.upper()))


def _huella(valor: str) -> str:
    return hashlib.sha256(_normalizar(valor).encode("utf-8")).hexdigest()


def _redondear(valor: float, decimales: int) -> float:
    unidad = Decimal("1").scaleb(-decimales)
    return float(Decimal(str(valor)).quantize(unidad, rounding=ROUND_HALF_UP))
