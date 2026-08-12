"""Catálogo Maestro de Plantas con persistencia JSON local y auditable."""

from __future__ import annotations

import json
import os
import tempfile
import unicodedata
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Callable, Iterable
from uuid import uuid4


VERSION_FORMATO = 1


class ErrorCatalogoPlantas(ValueError):
    """Error base del catálogo de plantas."""


class PlantaNoEncontradaError(ErrorCatalogoPlantas):
    """La planta solicitada no existe."""


class PlantaDuplicadaError(ErrorCatalogoPlantas):
    """Ya existe una planta con el mismo nombre normalizado."""


class CatalogoCorruptoError(ErrorCatalogoPlantas):
    """El archivo existe, pero no cumple el formato esperado."""


class ModificacionProtegidaError(ErrorCatalogoPlantas):
    """Una planta confirmada requiere una modificación manual explícita."""


class EstadoCalidad(str, Enum):
    PENDIENTE = "PENDIENTE"
    CONFIRMADA = "CONFIRMADA"
    REQUIERE_REVISION = "REQUIERE_REVISION"


class EstadoVigencia(str, Enum):
    ACTIVA = "ACTIVA"
    INACTIVA = "INACTIVA"


class TipoGeocerca(str, Enum):
    """Bloque PLANTAS P3 -- una planta puede modelarse como punto+radio
    (histórico, sigue siendo el default) o como un recinto operacional
    poligonal cuando un punto+radio pequeño no representa bien un
    complejo real amplio (accesos, patios, varias naves) -- ver
    `atlas_core.rutas.geocerca.punto_en_poligono`."""

    CIRCULAR = "CIRCULAR"
    POLIGONAL = "POLIGONAL"


def normalizar_nombre_planta(nombre: str) -> str:
    """Normaliza únicamente para comparar, sin reemplazar el texto original."""
    texto = unicodedata.normalize("NFKD", str(nombre or "").strip())
    sin_acentos = "".join(
        caracter for caracter in texto if not unicodedata.combining(caracter)
    )
    return " ".join(sin_acentos.upper().split())


def _ahora_utc() -> datetime:
    return datetime.now(timezone.utc)


def _texto_obligatorio(valor: str, campo: str) -> str:
    limpio = str(valor or "").strip()
    if not limpio:
        raise ErrorCatalogoPlantas(f"{campo} es obligatorio")
    return limpio


def _texto_opcional(valor: str | None) -> str:
    return str(valor or "").strip()


def _validar_coordenadas(
    latitud: float | None, longitud: float | None
) -> tuple[float | None, float | None]:
    if (latitud is None) != (longitud is None):
        raise ErrorCatalogoPlantas("latitud y longitud deben informarse juntas")
    if latitud is not None and not -90 <= latitud <= 90:
        raise ErrorCatalogoPlantas("latitud debe estar entre -90 y 90")
    if longitud is not None and not -180 <= longitud <= 180:
        raise ErrorCatalogoPlantas("longitud debe estar entre -180 y 180")
    return latitud, longitud


@dataclass(frozen=True)
class Planta:
    planta_id: str
    nombre: str
    nombre_normalizado: str
    direccion: str
    comuna: str
    region: str
    pais: str
    latitud: float | None
    longitud: float | None
    estado_calidad: str
    estado_vigencia: str
    fuente: str
    observacion: str
    fecha_creacion: str
    fecha_modificacion: str
    # Bloque PLANTAS P3 -- opcionales con default, agregados AL FINAL para
    # no romper catálogos existentes (ver `desde_dict`, que rellena estos
    # dos con su default cuando un registro antiguo no los trae: "una
    # planta antigua sin tipo se comporta como CIRCULAR", tal cual antes
    # de este bloque). `vertices`: secuencia de (latitud, longitud) --
    # solo tiene sentido con `tipo_geocerca=POLIGONAL`.
    tipo_geocerca: str = TipoGeocerca.CIRCULAR.value
    vertices: tuple[tuple[float, float], ...] = ()
    # Bloque PLANTAS P3 -- separado A PROPÓSITO de `latitud`/`longitud`:
    # esos dos siguen siendo la dirección/punto histórico de la planta
    # (pueden quedar imprecisos frente a evidencia real nueva, como pasó
    # con AZA COLINA -- geocodificado de texto de dirección, 18,4 km del
    # recinto operacional real evidenciado por telemetría). `punto_ruteo_*`
    # es el punto REAL desde donde debe iniciar/terminar una ruta ORS --
    # el acceso de camiones hacia la red vial, validado contra
    # cartografía/telemetría, nunca inventado. Sin `punto_ruteo_*`
    # (`None`, default -- toda planta existente antes de este bloque),
    # el ruteo sigue usando `latitud`/`longitud` exactamente como
    # siempre (fallback explícito, ver `destino_entrega.py`).
    punto_ruteo_latitud: float | None = None
    punto_ruteo_longitud: float | None = None

    # Campos que pueden faltar en un registro serializado antiguo sin
    # romper la carga -- ver `desde_dict`. Todo campo nuevo agregado
    # backward-compatible a este dataclass debe listarse aquí también.
    CAMPOS_OPCIONALES_LEGADO = (
        "tipo_geocerca", "vertices", "punto_ruteo_latitud", "punto_ruteo_longitud",
    )

    @classmethod
    def desde_dict(cls, datos: object) -> "Planta":
        if not isinstance(datos, dict):
            raise CatalogoCorruptoError("cada planta debe ser un objeto JSON")
        campos = set(cls.__dataclass_fields__)
        faltantes = campos - set(datos)
        desconocidos = set(datos) - campos
        if desconocidos or (faltantes - set(cls.CAMPOS_OPCIONALES_LEGADO)):
            raise CatalogoCorruptoError(
                "los campos de una planta no coinciden con el formato vigente"
            )
        datos = dict(datos)
        for campo in faltantes:
            datos[campo] = cls.__dataclass_fields__[campo].default
        datos["vertices"] = tuple(tuple(vertice) for vertice in (datos["vertices"] or ()))
        try:
            planta = cls(**datos)
            _validar_planta(planta)
        except (TypeError, ErrorCatalogoPlantas) as error:
            raise CatalogoCorruptoError(str(error)) from error
        return planta

    def a_dict(self) -> dict[str, object]:
        # `vertices` se deja como tupla de tuplas (no lista) -- json.dump
        # serializa tuplas como arreglos igual que listas, y así
        # `Planta(**planta.a_dict())` (ver `desactivar`) sigue
        # construyendo un dataclass válido/hasheable sin reconversión.
        return asdict(self)


def _validar_fecha_iso(valor: str, campo: str) -> None:
    try:
        fecha = datetime.fromisoformat(valor)
    except (TypeError, ValueError) as error:
        raise ErrorCatalogoPlantas(f"{campo} debe ser una fecha ISO válida") from error
    if fecha.tzinfo is None:
        raise ErrorCatalogoPlantas(f"{campo} debe incluir zona horaria")


def _validar_planta(planta: Planta) -> None:
    _texto_obligatorio(planta.planta_id, "planta_id")
    nombre = _texto_obligatorio(planta.nombre, "nombre")
    if planta.nombre_normalizado != normalizar_nombre_planta(nombre):
        raise ErrorCatalogoPlantas("nombre_normalizado no corresponde a nombre")
    _texto_obligatorio(planta.pais, "pais")
    _texto_obligatorio(planta.fuente, "fuente")
    try:
        EstadoCalidad(planta.estado_calidad)
        EstadoVigencia(planta.estado_vigencia)
    except ValueError as error:
        raise ErrorCatalogoPlantas("estado de calidad o vigencia no permitido") from error
    _validar_coordenadas(planta.latitud, planta.longitud)
    _validar_coordenadas(planta.punto_ruteo_latitud, planta.punto_ruteo_longitud)
    _validar_fecha_iso(planta.fecha_creacion, "fecha_creacion")
    _validar_fecha_iso(planta.fecha_modificacion, "fecha_modificacion")
    _validar_geocerca(planta.tipo_geocerca, planta.vertices)


def _validar_geocerca(tipo_geocerca: str, vertices: tuple[tuple[float, float], ...]) -> None:
    try:
        tipo = TipoGeocerca(tipo_geocerca)
    except ValueError as error:
        raise ErrorCatalogoPlantas("tipo_geocerca no permitido") from error
    if tipo == TipoGeocerca.CIRCULAR:
        if vertices:
            raise ErrorCatalogoPlantas("una planta CIRCULAR no debe tener vértices")
        return
    # POLIGONAL
    if len(vertices) < 3:
        raise ErrorCatalogoPlantas(
            "una planta POLIGONAL requiere al menos 3 vértices"
        )
    for vertice in vertices:
        if len(vertice) != 2:
            raise ErrorCatalogoPlantas("cada vértice debe ser [latitud, longitud]")
        _validar_coordenadas(vertice[0], vertice[1])


class CatalogoPlantas:
    """Administra plantas sin conectarlas al procesamiento productivo."""

    def __init__(
        self,
        ruta: str | Path = "catalogos/plantas.json",
        *,
        reloj: Callable[[], datetime] = _ahora_utc,
        generador_id: Callable[[], object] = uuid4,
    ) -> None:
        self.ruta = Path(ruta)
        self._reloj = reloj
        self._generador_id = generador_id

    def listar(self) -> list[Planta]:
        return list(self._leer())

    def obtener(self, planta_id: str) -> Planta:
        buscado = str(planta_id or "").strip()
        for planta in self._leer():
            if planta.planta_id == buscado:
                return planta
        raise PlantaNoEncontradaError(f"No existe la planta {buscado!r}")

    def crear(
        self,
        *,
        nombre: str,
        pais: str,
        fuente: str,
        direccion: str = "",
        comuna: str = "",
        region: str = "",
        latitud: float | None = None,
        longitud: float | None = None,
        estado_calidad: EstadoCalidad | str = EstadoCalidad.PENDIENTE,
        observacion: str = "",
        tipo_geocerca: TipoGeocerca | str = TipoGeocerca.CIRCULAR,
        vertices: Iterable[tuple[float, float]] = (),
        punto_ruteo_latitud: float | None = None,
        punto_ruteo_longitud: float | None = None,
    ) -> Planta:
        plantas = self._leer()
        nombre_limpio = _texto_obligatorio(nombre, "nombre")
        normalizado = normalizar_nombre_planta(nombre_limpio)
        self._validar_duplicado(plantas, normalizado)
        latitud, longitud = _validar_coordenadas(latitud, longitud)
        punto_ruteo_latitud, punto_ruteo_longitud = _validar_coordenadas(
            punto_ruteo_latitud, punto_ruteo_longitud
        )
        instante = self._instante_iso()
        planta = Planta(
            planta_id=str(self._generador_id()),
            nombre=nombre_limpio,
            nombre_normalizado=normalizado,
            direccion=_texto_opcional(direccion),
            comuna=_texto_opcional(comuna),
            region=_texto_opcional(region),
            pais=_texto_obligatorio(pais, "pais"),
            latitud=latitud,
            longitud=longitud,
            estado_calidad=EstadoCalidad(estado_calidad).value,
            estado_vigencia=EstadoVigencia.ACTIVA.value,
            fuente=_texto_obligatorio(fuente, "fuente"),
            observacion=_texto_opcional(observacion),
            fecha_creacion=instante,
            fecha_modificacion=instante,
            tipo_geocerca=TipoGeocerca(tipo_geocerca).value,
            vertices=tuple(tuple(v) for v in vertices),
            punto_ruteo_latitud=punto_ruteo_latitud,
            punto_ruteo_longitud=punto_ruteo_longitud,
        )
        _validar_planta(planta)
        plantas.append(planta)
        self._escribir(plantas)
        return planta

    def editar(
        self,
        planta_id: str,
        *,
        modificacion_manual: bool = False,
        nombre: str | None = None,
        direccion: str | None = None,
        comuna: str | None = None,
        region: str | None = None,
        pais: str | None = None,
        latitud: float | None = None,
        longitud: float | None = None,
        limpiar_coordenadas: bool = False,
        estado_calidad: EstadoCalidad | str | None = None,
        fuente: str | None = None,
        observacion: str | None = None,
        tipo_geocerca: TipoGeocerca | str | None = None,
        vertices: Iterable[tuple[float, float]] | None = None,
        punto_ruteo_latitud: float | None = None,
        punto_ruteo_longitud: float | None = None,
        limpiar_punto_ruteo: bool = False,
    ) -> Planta:
        plantas = self._leer()
        indice = self._indice(plantas, planta_id)
        actual = plantas[indice]
        if actual.estado_calidad == EstadoCalidad.CONFIRMADA.value and not modificacion_manual:
            raise ModificacionProtegidaError(
                "La planta está confirmada; use una modificación manual explícita"
            )
        nombre_nuevo = actual.nombre if nombre is None else _texto_obligatorio(nombre, "nombre")
        nombre_normalizado = normalizar_nombre_planta(nombre_nuevo)
        self._validar_duplicado(plantas, nombre_normalizado, excluir_id=actual.planta_id)
        if limpiar_coordenadas:
            if latitud is not None or longitud is not None:
                raise ErrorCatalogoPlantas(
                    "no combine limpiar_coordenadas con coordenadas nuevas"
                )
            latitud_nueva = longitud_nueva = None
        elif latitud is None and longitud is None:
            latitud_nueva, longitud_nueva = actual.latitud, actual.longitud
        else:
            latitud_nueva, longitud_nueva = _validar_coordenadas(latitud, longitud)
        if limpiar_punto_ruteo:
            if punto_ruteo_latitud is not None or punto_ruteo_longitud is not None:
                raise ErrorCatalogoPlantas(
                    "no combine limpiar_punto_ruteo con punto_ruteo nuevo"
                )
            punto_ruteo_lat_nuevo = punto_ruteo_lon_nuevo = None
        elif punto_ruteo_latitud is None and punto_ruteo_longitud is None:
            punto_ruteo_lat_nuevo = actual.punto_ruteo_latitud
            punto_ruteo_lon_nuevo = actual.punto_ruteo_longitud
        else:
            punto_ruteo_lat_nuevo, punto_ruteo_lon_nuevo = _validar_coordenadas(
                punto_ruteo_latitud, punto_ruteo_longitud
            )
        planta = Planta(
            planta_id=actual.planta_id,
            nombre=nombre_nuevo,
            nombre_normalizado=nombre_normalizado,
            direccion=actual.direccion if direccion is None else _texto_opcional(direccion),
            comuna=actual.comuna if comuna is None else _texto_opcional(comuna),
            region=actual.region if region is None else _texto_opcional(region),
            pais=actual.pais if pais is None else _texto_obligatorio(pais, "pais"),
            latitud=latitud_nueva,
            longitud=longitud_nueva,
            estado_calidad=(actual.estado_calidad if estado_calidad is None else EstadoCalidad(estado_calidad).value),
            estado_vigencia=actual.estado_vigencia,
            fuente=actual.fuente if fuente is None else _texto_obligatorio(fuente, "fuente"),
            observacion=actual.observacion if observacion is None else _texto_opcional(observacion),
            fecha_creacion=actual.fecha_creacion,
            fecha_modificacion=self._instante_iso(),
            tipo_geocerca=(
                actual.tipo_geocerca if tipo_geocerca is None else TipoGeocerca(tipo_geocerca).value
            ),
            vertices=(
                actual.vertices if vertices is None else tuple(tuple(v) for v in vertices)
            ),
            punto_ruteo_latitud=punto_ruteo_lat_nuevo,
            punto_ruteo_longitud=punto_ruteo_lon_nuevo,
        )
        _validar_planta(planta)
        plantas[indice] = planta
        self._escribir(plantas)
        return planta

    def desactivar(self, planta_id: str, *, modificacion_manual: bool = False) -> Planta:
        plantas = self._leer()
        indice = self._indice(plantas, planta_id)
        actual = plantas[indice]
        if actual.estado_calidad == EstadoCalidad.CONFIRMADA.value and not modificacion_manual:
            raise ModificacionProtegidaError(
                "La planta está confirmada; use una modificación manual explícita"
            )
        if actual.estado_vigencia == EstadoVigencia.INACTIVA.value:
            return actual
        planta = Planta(**{
            **actual.a_dict(),
            "estado_vigencia": EstadoVigencia.INACTIVA.value,
            "fecha_modificacion": self._instante_iso(),
        })
        _validar_planta(planta)
        plantas[indice] = planta
        self._escribir(plantas)
        return planta

    def _instante_iso(self) -> str:
        instante = self._reloj()
        if instante.tzinfo is None:
            instante = instante.replace(tzinfo=timezone.utc)
        return instante.astimezone(timezone.utc).isoformat()

    def _leer(self) -> list[Planta]:
        if not self.ruta.exists():
            return []
        try:
            with self.ruta.open("r", encoding="utf-8") as archivo:
                contenido = json.load(archivo)
        except (OSError, json.JSONDecodeError) as error:
            raise CatalogoCorruptoError(f"No se pudo leer el catálogo {self.ruta}: {error}") from error
        if not isinstance(contenido, dict):
            raise CatalogoCorruptoError("la raíz del catálogo debe ser un objeto")
        if contenido.get("version_formato") != VERSION_FORMATO:
            raise CatalogoCorruptoError("versión de formato no compatible")
        registros = contenido.get("plantas")
        if not isinstance(registros, list):
            raise CatalogoCorruptoError("plantas debe ser una lista")
        plantas = [Planta.desde_dict(registro) for registro in registros]
        ids = [planta.planta_id for planta in plantas]
        nombres = [planta.nombre_normalizado for planta in plantas]
        if len(ids) != len(set(ids)) or len(nombres) != len(set(nombres)):
            raise CatalogoCorruptoError("el catálogo contiene IDs o nombres duplicados")
        return plantas

    def _escribir(self, plantas: Iterable[Planta]) -> None:
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        contenido = {
            "version_formato": VERSION_FORMATO,
            "plantas": [planta.a_dict() for planta in plantas],
        }
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

    @staticmethod
    def _indice(plantas: list[Planta], planta_id: str) -> int:
        buscado = str(planta_id or "").strip()
        for indice, planta in enumerate(plantas):
            if planta.planta_id == buscado:
                return indice
        raise PlantaNoEncontradaError(f"No existe la planta {buscado!r}")

    @staticmethod
    def _validar_duplicado(
        plantas: Iterable[Planta], nombre_normalizado: str, excluir_id: str | None = None
    ) -> None:
        if any(
            planta.nombre_normalizado == nombre_normalizado and planta.planta_id != excluir_id
            for planta in plantas
        ):
            raise PlantaDuplicadaError(
                f"Ya existe una planta con el nombre normalizado {nombre_normalizado!r}"
            )
