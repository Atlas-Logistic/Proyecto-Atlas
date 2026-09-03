"""Catálogo Maestro de Destinos asociado al Catálogo Maestro de Clientes."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Callable, Iterable
from uuid import uuid4

from atlas_core.almacenamiento_portable import bloqueo_sesion
from atlas_core.geografia import texto_normalizado
from atlas_core.catalogo_clientes import (
    CatalogoClientes,
    ClienteNoEncontradoError,
    EstadoVigenciaCliente,
)


VERSION_FORMATO = 1
# Bloque CONSISTENCIA OPERACIONAL -- lock físico propio de este catálogo
# (mismo patrón ya establecido para obras_destinos/vehículos/evidencia/
# incidencias/clientes). `crear_o_reutilizar_global` NO lo adquiere
# directamente -- delega enteramente en `editar`/`crear` (que sí lo
# adquieren cada uno), evitando una reentrada del mismo lock no
# reentrante.
NOMBRE_LOCK_CATALOGO_DESTINOS = "catalogo_destinos"


class ErrorCatalogoDestinos(ValueError):
    """Error base del catálogo de destinos."""


class DestinoNoEncontradoError(ErrorCatalogoDestinos):
    """El destino solicitado no existe."""


class DestinoDuplicadoError(ErrorCatalogoDestinos):
    """Ya existe un destino con la misma identidad dentro del cliente."""


class AliasDestinoDuplicadoError(ErrorCatalogoDestinos):
    """El alias ya pertenece a un destino del mismo cliente."""


class ClienteDestinoInvalidoError(ErrorCatalogoDestinos):
    """El cliente asociado no existe o no está activo."""


class CatalogoDestinosCorruptoError(ErrorCatalogoDestinos):
    """El archivo no cumple el contrato del Catálogo Maestro de Destinos."""


class ModificacionDestinoProtegidaError(ErrorCatalogoDestinos):
    """Un destino confirmado requiere una operación manual explícita."""


class EstadoCalidadDestino(str, Enum):
    PENDIENTE = "PENDIENTE"
    CONFIRMADO = "CONFIRMADO"
    REQUIERE_REVISION = "REQUIERE_REVISION"


class EstadoVigenciaDestino(str, Enum):
    ACTIVO = "ACTIVO"
    INACTIVO = "INACTIVO"


class EstadoBusquedaDestino(str, Enum):
    COINCIDENCIA = "COINCIDENCIA"
    SIN_COINCIDENCIA = "SIN_COINCIDENCIA"
    AMBIGUA = "AMBIGUA"


@dataclass(frozen=True)
class ResultadoBusquedaDestino:
    estado: EstadoBusquedaDestino
    destino: "Destino | None" = None
    cantidad_coincidencias: int = 0


def normalizar_nombre_destino(nombre: str) -> str:
    """Normaliza para comparación exacta sin modificar el texto original."""
    return texto_normalizado(nombre)


def _texto_direccion_normalizado(texto: str) -> str:
    return normalizar_nombre_destino(texto)


def clave_fisica_destino(direccion: str, comuna: str = "", region: str = "") -> tuple[str, str, str]:
    """Clave global exacta y conservadora; nunca fuzzy."""
    direccion_n = _texto_direccion_normalizado(direccion)
    if not direccion_n:
        raise ErrorCatalogoDestinos("dirección insuficiente para una identidad física")
    return direccion_n, normalizar_nombre_destino(comuna), normalizar_nombre_destino(region)


def _ahora_utc() -> datetime:
    return datetime.now(timezone.utc)


def _obligatorio(valor: str, campo: str) -> str:
    limpio = str(valor or "").strip()
    if not limpio:
        raise ErrorCatalogoDestinos(f"{campo} es obligatorio")
    return limpio


def _opcional(valor: str | None) -> str:
    return str(valor or "").strip()


def _validar_coordenadas(
    latitud: float | None, longitud: float | None
) -> tuple[float | None, float | None]:
    if (latitud is None) != (longitud is None):
        raise ErrorCatalogoDestinos("latitud y longitud deben informarse juntas")
    if latitud is not None and not -90 <= latitud <= 90:
        raise ErrorCatalogoDestinos("latitud debe estar entre -90 y 90")
    if longitud is not None and not -180 <= longitud <= 180:
        raise ErrorCatalogoDestinos("longitud debe estar entre -180 y 180")
    return latitud, longitud


def _validar_fecha(valor: str, campo: str) -> None:
    try:
        fecha = datetime.fromisoformat(valor)
    except (TypeError, ValueError) as error:
        raise ErrorCatalogoDestinos(f"{campo} debe ser una fecha ISO válida") from error
    if fecha.tzinfo is None:
        raise ErrorCatalogoDestinos(f"{campo} debe incluir zona horaria")


@dataclass(frozen=True)
class Destino:
    destino_id: str
    cliente_id: str
    nombre_destino: str
    nombre_normalizado: str
    codigo_destino: str
    direccion: str
    comuna: str
    region: str
    pais: str
    latitud: float | None
    longitud: float | None
    aliases: tuple[str, ...]
    estado_calidad: str
    estado_vigencia: str
    fuente: str
    observacion: str
    fecha_creacion: str
    fecha_modificacion: str

    def a_dict(self) -> dict[str, object]:
        datos = asdict(self)
        datos["aliases"] = list(self.aliases)
        return datos

    @classmethod
    def desde_dict(cls, datos: object) -> "Destino":
        if not isinstance(datos, dict):
            raise CatalogoDestinosCorruptoError("cada destino debe ser un objeto JSON")
        campos = set(cls.__dataclass_fields__)
        if set(datos) != campos or not isinstance(datos.get("aliases"), list):
            raise CatalogoDestinosCorruptoError("campos de destino incompatibles")
        try:
            destino = cls(**{**datos, "aliases": tuple(datos["aliases"])})
            _validar_destino(destino)
        except (TypeError, ErrorCatalogoDestinos) as error:
            raise CatalogoDestinosCorruptoError(str(error)) from error
        return destino


def _claves_identidad(destino: Destino) -> set[str]:
    return {
        normalizar_nombre_destino(valor)
        for valor in [destino.nombre_destino, *destino.aliases]
        if _opcional(valor)
    }


def _validar_destino(destino: Destino) -> None:
    _obligatorio(destino.destino_id, "destino_id")
    # `cliente_id` queda como procedencia histórica opcional; no es identidad.
    nombre = _obligatorio(destino.nombre_destino, "nombre_destino")
    if destino.nombre_normalizado != normalizar_nombre_destino(nombre):
        raise ErrorCatalogoDestinos("nombre_normalizado no corresponde a nombre_destino")
    _obligatorio(destino.pais, "pais")
    _obligatorio(destino.fuente, "fuente")
    try:
        EstadoCalidadDestino(destino.estado_calidad)
        EstadoVigenciaDestino(destino.estado_vigencia)
    except ValueError as error:
        raise ErrorCatalogoDestinos("estado de calidad o vigencia no permitido") from error
    _validar_coordenadas(destino.latitud, destino.longitud)
    claves_alias = [normalizar_nombre_destino(alias) for alias in destino.aliases]
    if any(not clave for clave in claves_alias):
        raise ErrorCatalogoDestinos("los alias no pueden estar vacíos")
    if len(claves_alias) != len(set(claves_alias)):
        raise ErrorCatalogoDestinos("el destino contiene alias duplicados")
    if destino.nombre_normalizado in claves_alias:
        raise ErrorCatalogoDestinos("un alias no puede duplicar el nombre del destino")
    _validar_fecha(destino.fecha_creacion, "fecha_creacion")
    _validar_fecha(destino.fecha_modificacion, "fecha_modificacion")


class CatalogoDestinos:
    """Administra destinos y valida su cliente al crear o reasignar."""

    def __init__(
        self,
        ruta: str | Path = "catalogos/destinos.json",
        *,
        ruta_clientes: str | Path = "catalogos/clientes.json",
        reloj: Callable[[], datetime] = _ahora_utc,
        generador_id: Callable[[], object] = uuid4,
    ) -> None:
        self.ruta = Path(ruta)
        self.ruta_clientes = Path(ruta_clientes)
        self._reloj = reloj
        self._generador_id = generador_id

    def listar(self, *, cliente_id: str | None = None) -> list[Destino]:
        destinos = self._leer()
        if cliente_id is None:
            return destinos
        buscado = str(cliente_id).strip()
        return [destino for destino in destinos if destino.cliente_id == buscado]

    def obtener(self, destino_id: str) -> Destino:
        destinos = self._leer()
        return destinos[self._indice(destinos, destino_id)]

    def buscar(
        self, texto: str, *, cliente_id: str | None = None
    ) -> ResultadoBusquedaDestino:
        clave = normalizar_nombre_destino(_obligatorio(texto, "texto"))
        destinos = [d for d in self.listar() if d.estado_vigencia == EstadoVigenciaDestino.ACTIVO.value]
        coincidencias = [destino for destino in destinos if clave in _claves_identidad(destino)]
        if len(coincidencias) == 1:
            return ResultadoBusquedaDestino(
                EstadoBusquedaDestino.COINCIDENCIA, coincidencias[0], 1
            )
        if len(coincidencias) > 1:
            return ResultadoBusquedaDestino(
                EstadoBusquedaDestino.AMBIGUA, None, len(coincidencias)
            )
        return ResultadoBusquedaDestino(EstadoBusquedaDestino.SIN_COINCIDENCIA)

    def resolver_direccion_global(self, direccion: str, *, comuna: str = "", region: str = "") -> ResultadoBusquedaDestino:
        clave = clave_fisica_destino(direccion, comuna, region)
        coincidencias = [d for d in self.listar() if d.estado_vigencia == EstadoVigenciaDestino.ACTIVO.value and clave_fisica_destino(d.direccion, d.comuna, d.region) == clave]
        if len(coincidencias) == 1:
            return ResultadoBusquedaDestino(EstadoBusquedaDestino.COINCIDENCIA, coincidencias[0], 1)
        if len(coincidencias) > 1:
            return ResultadoBusquedaDestino(EstadoBusquedaDestino.AMBIGUA, None, len(coincidencias))
        return ResultadoBusquedaDestino(EstadoBusquedaDestino.SIN_COINCIDENCIA)

    def crear_o_reutilizar_global(
        self, *, nombre_destino: str, direccion: str, comuna: str = "", region: str = "",
        pais: str = "CHILE", fuente: str, latitud: float | None = None, longitud: float | None = None,
        estado_calidad: EstadoCalidadDestino | str = EstadoCalidadDestino.PENDIENTE,
    ) -> Destino:
        resuelto = self.resolver_direccion_global(direccion, comuna=comuna, region=region)
        if resuelto.estado == EstadoBusquedaDestino.COINCIDENCIA:
            destino = resuelto.destino
            # Bloque RESOLUCIÓN R16 -- una dirección global ya existente
            # (misma clave física) que un llamador confirma ahora con
            # evidencia humana/externa nueva debe promoverse a CONFIRMADO
            # -- nunca quedarse en PENDIENTE para siempre sólo porque ya
            # existía. Nunca DEGRADA un destino (sólo promueve PENDIENTE/
            # REQUIERE_REVISION -> CONFIRMADO; jamás CONFIRMADO -> otra
            # cosa aquí), y sólo agrega coordenadas cuando el destino
            # existente aún no las tenía -- nunca sobrescribe una
            # coordenada ya presente con una nueva silenciosamente.
            estado_calidad_valor = EstadoCalidadDestino(estado_calidad).value
            necesita_coordenadas = (
                latitud is not None and longitud is not None
                and destino.latitud is None and destino.longitud is None
            )
            if (
                estado_calidad_valor == EstadoCalidadDestino.CONFIRMADO.value
                and destino.estado_calidad != EstadoCalidadDestino.CONFIRMADO.value
            ) or necesita_coordenadas:
                destino = self.editar(
                    destino.destino_id, modificacion_manual=True,
                    estado_calidad=(
                        EstadoCalidadDestino.CONFIRMADO
                        if estado_calidad_valor == EstadoCalidadDestino.CONFIRMADO.value else None
                    ),
                    latitud=latitud if necesita_coordenadas else None,
                    longitud=longitud if necesita_coordenadas else None,
                )
            return destino
        if resuelto.estado == EstadoBusquedaDestino.AMBIGUA:
            raise ErrorCatalogoDestinos("dirección global ambigua")
        return self.crear(
            cliente_id="", nombre_destino=nombre_destino, direccion=direccion, comuna=comuna,
            region=region, pais=pais, fuente=fuente, latitud=latitud, longitud=longitud,
            estado_calidad=estado_calidad,
        )

    def crear(
        self,
        *,
        cliente_id: str,
        nombre_destino: str,
        pais: str,
        fuente: str,
        codigo_destino: str = "",
        direccion: str = "",
        comuna: str = "",
        region: str = "",
        latitud: float | None = None,
        longitud: float | None = None,
        aliases: Iterable[str] = (),
        estado_calidad: EstadoCalidadDestino | str = EstadoCalidadDestino.PENDIENTE,
        observacion: str = "",
    ) -> Destino:
        with bloqueo_sesion(self.ruta.parent, NOMBRE_LOCK_CATALOGO_DESTINOS):
            destinos = self._leer()
            cliente_limpio = self._validar_cliente_activo(cliente_id) if str(cliente_id or "").strip() else ""
            nombre = _obligatorio(nombre_destino, "nombre_destino")
            latitud, longitud = _validar_coordenadas(latitud, longitud)
            instante = self._instante_iso()
            destino = Destino(
                destino_id=str(self._generador_id()),
                cliente_id=cliente_limpio,
                nombre_destino=nombre,
                nombre_normalizado=normalizar_nombre_destino(nombre),
                codigo_destino=_opcional(codigo_destino),
                direccion=_opcional(direccion),
                comuna=_opcional(comuna),
                region=_opcional(region),
                pais=_obligatorio(pais, "pais"),
                latitud=latitud,
                longitud=longitud,
                aliases=tuple(_obligatorio(alias, "alias") for alias in aliases),
                estado_calidad=EstadoCalidadDestino(estado_calidad).value,
                estado_vigencia=EstadoVigenciaDestino.ACTIVO.value,
                fuente=_obligatorio(fuente, "fuente"),
                observacion=_opcional(observacion),
                fecha_creacion=instante,
                fecha_modificacion=instante,
            )
            _validar_destino(destino)
            self._validar_duplicado(destinos, destino)
            destinos.append(destino)
            self._escribir(destinos)
            return destino

    def editar(
        self,
        destino_id: str,
        *,
        modificacion_manual: bool = False,
        cliente_id: str | None = None,
        nombre_destino: str | None = None,
        codigo_destino: str | None = None,
        direccion: str | None = None,
        comuna: str | None = None,
        region: str | None = None,
        pais: str | None = None,
        latitud: float | None = None,
        longitud: float | None = None,
        limpiar_coordenadas: bool = False,
        estado_calidad: EstadoCalidadDestino | str | None = None,
        fuente: str | None = None,
        observacion: str | None = None,
    ) -> Destino:
        with bloqueo_sesion(self.ruta.parent, NOMBRE_LOCK_CATALOGO_DESTINOS):
            destinos = self._leer()
            indice = self._indice(destinos, destino_id)
            actual = destinos[indice]
            self._proteger(actual, modificacion_manual)
            cliente_nuevo = actual.cliente_id if cliente_id is None else (self._validar_cliente_activo(cliente_id) if str(cliente_id).strip() else "")
            nombre = actual.nombre_destino if nombre_destino is None else _obligatorio(nombre_destino, "nombre_destino")
            if limpiar_coordenadas:
                if latitud is not None or longitud is not None:
                    raise ErrorCatalogoDestinos("no combine limpiar_coordenadas con coordenadas")
                latitud_nueva = longitud_nueva = None
            elif latitud is None and longitud is None:
                latitud_nueva, longitud_nueva = actual.latitud, actual.longitud
            else:
                latitud_nueva, longitud_nueva = _validar_coordenadas(latitud, longitud)
            editado = Destino(
                destino_id=actual.destino_id,
                cliente_id=cliente_nuevo,
                nombre_destino=nombre,
                nombre_normalizado=normalizar_nombre_destino(nombre),
                codigo_destino=actual.codigo_destino if codigo_destino is None else _opcional(codigo_destino),
                direccion=actual.direccion if direccion is None else _opcional(direccion),
                comuna=actual.comuna if comuna is None else _opcional(comuna),
                region=actual.region if region is None else _opcional(region),
                pais=actual.pais if pais is None else _obligatorio(pais, "pais"),
                latitud=latitud_nueva,
                longitud=longitud_nueva,
                aliases=actual.aliases,
                estado_calidad=actual.estado_calidad if estado_calidad is None else EstadoCalidadDestino(estado_calidad).value,
                estado_vigencia=actual.estado_vigencia,
                fuente=actual.fuente if fuente is None else _obligatorio(fuente, "fuente"),
                observacion=actual.observacion if observacion is None else _opcional(observacion),
                fecha_creacion=actual.fecha_creacion,
                fecha_modificacion=self._instante_iso(),
            )
            _validar_destino(editado)
            self._validar_duplicado(destinos, editado, excluir_id=actual.destino_id)
            destinos[indice] = editado
            self._escribir(destinos)
            return editado

    def agregar_alias(
        self, destino_id: str, alias: str, *, modificacion_manual: bool = False
    ) -> Destino:
        with bloqueo_sesion(self.ruta.parent, NOMBRE_LOCK_CATALOGO_DESTINOS):
            destinos = self._leer()
            indice = self._indice(destinos, destino_id)
            actual = destinos[indice]
            self._proteger(actual, modificacion_manual)
            editado = replace(
                actual,
                aliases=(*actual.aliases, _obligatorio(alias, "alias")),
                fecha_modificacion=self._instante_iso(),
            )
            _validar_destino(editado)
            self._validar_duplicado(
                destinos, editado, excluir_id=actual.destino_id, error_alias=True
            )
            destinos[indice] = editado
            self._escribir(destinos)
            return editado

    def desactivar(
        self, destino_id: str, *, modificacion_manual: bool = False
    ) -> Destino:
        with bloqueo_sesion(self.ruta.parent, NOMBRE_LOCK_CATALOGO_DESTINOS):
            destinos = self._leer()
            indice = self._indice(destinos, destino_id)
            actual = destinos[indice]
            self._proteger(actual, modificacion_manual)
            if actual.estado_vigencia == EstadoVigenciaDestino.INACTIVO.value:
                return actual
            editado = replace(
                actual,
                estado_vigencia=EstadoVigenciaDestino.INACTIVO.value,
                fecha_modificacion=self._instante_iso(),
            )
            destinos[indice] = editado
            self._escribir(destinos)
            return editado

    def _validar_cliente_activo(self, cliente_id: str) -> str:
        buscado = _obligatorio(cliente_id, "cliente_id")
        try:
            cliente = CatalogoClientes(self.ruta_clientes).obtener(buscado)
        except ClienteNoEncontradoError as error:
            raise ClienteDestinoInvalidoError("cliente_id no existe") from error
        if cliente.estado_vigencia != EstadoVigenciaCliente.ACTIVO.value:
            raise ClienteDestinoInvalidoError("cliente_id está inactivo")
        return cliente.cliente_id

    @staticmethod
    def _proteger(destino: Destino, modificacion_manual: bool) -> None:
        if destino.estado_calidad == EstadoCalidadDestino.CONFIRMADO.value and not modificacion_manual:
            raise ModificacionDestinoProtegidaError(
                "El destino está confirmado; use una modificación manual explícita"
            )

    def _instante_iso(self) -> str:
        instante = self._reloj()
        if instante.tzinfo is None:
            instante = instante.replace(tzinfo=timezone.utc)
        return instante.astimezone(timezone.utc).isoformat()

    def _leer(self) -> list[Destino]:
        if not self.ruta.exists():
            return []
        try:
            with self.ruta.open("r", encoding="utf-8") as archivo:
                contenido = json.load(archivo)
        except (OSError, json.JSONDecodeError) as error:
            raise CatalogoDestinosCorruptoError(f"No se pudo leer el catálogo: {error}") from error
        if not isinstance(contenido, dict) or contenido.get("version_formato") != VERSION_FORMATO:
            raise CatalogoDestinosCorruptoError("raíz o versión de formato no compatible")
        registros = contenido.get("destinos")
        if not isinstance(registros, list):
            raise CatalogoDestinosCorruptoError("destinos debe ser una lista")
        destinos = [Destino.desde_dict(registro) for registro in registros]
        ids = [destino.destino_id for destino in destinos]
        if len(ids) != len(set(ids)):
            raise CatalogoDestinosCorruptoError("el catálogo contiene IDs duplicados")
        try:
            for destino in destinos:
                self._validar_duplicado(destinos, destino, excluir_id=destino.destino_id)
        except ErrorCatalogoDestinos as error:
            raise CatalogoDestinosCorruptoError(str(error)) from error
        return destinos

    def _escribir(self, destinos: Iterable[Destino]) -> None:
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        contenido = {
            "version_formato": VERSION_FORMATO,
            "destinos": [destino.a_dict() for destino in destinos],
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
    def _indice(destinos: list[Destino], destino_id: str) -> int:
        buscado = str(destino_id or "").strip()
        for indice, destino in enumerate(destinos):
            if destino.destino_id == buscado:
                return indice
        raise DestinoNoEncontradoError(f"No existe el destino {buscado!r}")

    @staticmethod
    def _validar_duplicado(
        destinos: Iterable[Destino], candidato: Destino, *, excluir_id: str | None = None,
        error_alias: bool = False,
    ) -> None:
        for existente in destinos:
            if existente.destino_id == excluir_id:
                continue
            if candidato.estado_vigencia != EstadoVigenciaDestino.ACTIVO.value or existente.estado_vigencia != EstadoVigenciaDestino.ACTIVO.value:
                continue
            # Compatibilidad V1: los nombres/codigos/aliases no pueden chocar
            # dentro de una misma procedencia historica. Entre clientes no
            # definen identidad fisica y una busqueda textual se abstiene.
            if candidato.cliente_id and candidato.cliente_id == existente.cliente_id:
                if _claves_identidad(candidato) & _claves_identidad(existente):
                    error = AliasDestinoDuplicadoError if error_alias else DestinoDuplicadoError
                    raise error("El nombre, codigo o alias ya identifica otro destino")
            if (
                candidato.direccion and existente.direccion
                and _texto_direccion_normalizado(candidato.direccion)
                == _texto_direccion_normalizado(existente.direccion)
                and normalizar_nombre_destino(candidato.comuna)
                == normalizar_nombre_destino(existente.comuna)
                and normalizar_nombre_destino(candidato.region)
                == normalizar_nombre_destino(existente.region)
            ):
                raise DestinoDuplicadoError("La dirección ya pertenece a otro destino global activo")
