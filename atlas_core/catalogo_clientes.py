"""Catálogo Maestro de Clientes con búsqueda exacta y persistencia atómica."""

from __future__ import annotations

import json
import os
import re
import tempfile
import unicodedata
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Callable, Iterable
from uuid import uuid4


VERSION_FORMATO = 1


class ErrorCatalogoClientes(ValueError):
    """Error base del catálogo de clientes."""


class ClienteNoEncontradoError(ErrorCatalogoClientes):
    """El cliente solicitado no existe."""


class ClienteDuplicadoError(ErrorCatalogoClientes):
    """La identidad o clave normalizada ya pertenece a otro cliente."""


class AliasDuplicadoError(ErrorCatalogoClientes):
    """El alias ya está registrado como nombre o alias de otro cliente."""


class CatalogoClientesCorruptoError(ErrorCatalogoClientes):
    """El archivo existe, pero no cumple el contrato del catálogo."""


class ModificacionClienteProtegidaError(ErrorCatalogoClientes):
    """Un cliente confirmado requiere una operación manual explícita."""


class EstadoCalidadCliente(str, Enum):
    PENDIENTE = "PENDIENTE"
    CONFIRMADO = "CONFIRMADO"
    REQUIERE_REVISION = "REQUIERE_REVISION"


class EstadoVigenciaCliente(str, Enum):
    ACTIVO = "ACTIVO"
    INACTIVO = "INACTIVO"


class EstadoBusquedaCliente(str, Enum):
    COINCIDENCIA = "COINCIDENCIA"
    SIN_COINCIDENCIA = "SIN_COINCIDENCIA"
    AMBIGUA = "AMBIGUA"


@dataclass(frozen=True)
class ResultadoBusquedaCliente:
    estado: EstadoBusquedaCliente
    cliente: "Cliente | None" = None
    cantidad_coincidencias: int = 0


def normalizar_nombre_cliente(nombre: str) -> str:
    """Crea una clave comparable sin reemplazar el texto empresarial original."""
    texto = unicodedata.normalize("NFKD", str(nombre or "").strip())
    texto = "".join(
        caracter for caracter in texto if not unicodedata.combining(caracter)
    ).upper()
    tokens = re.findall(r"[A-Z0-9]+", texto)
    # Las variantes finales SA, S.A. y SOCIEDAD ANONIMA representan el mismo sufijo.
    if len(tokens) >= 2 and tokens[-2:] == ["SOCIEDAD", "ANONIMA"]:
        tokens = tokens[:-2]
    elif tokens and tokens[-1] == "SA":
        tokens = tokens[:-1]
    elif len(tokens) >= 2 and tokens[-2:] == ["S", "A"]:
        tokens = tokens[:-2]
    return " ".join(tokens)


def normalizar_rut_cliente(rut: str | None) -> str:
    """Valida un RUT chileno y devuelve su forma canónica sin puntos."""
    if rut is None or not str(rut).strip():
        return ""
    limpio = re.sub(r"[^0-9Kk]", "", str(rut)).upper()
    if len(limpio) < 8 or len(limpio) > 9 or not limpio[:-1].isdigit():
        raise ErrorCatalogoClientes("RUT inválido")
    cuerpo, verificador = limpio[:-1], limpio[-1]
    suma = sum(
        int(digito) * factor
        for digito, factor in zip(reversed(cuerpo), (2, 3, 4, 5, 6, 7) * 2)
    )
    resultado = 11 - suma % 11
    esperado = "0" if resultado == 11 else "K" if resultado == 10 else str(resultado)
    if verificador != esperado:
        raise ErrorCatalogoClientes("RUT inválido")
    return f"{int(cuerpo)}-{verificador}"


def _ahora_utc() -> datetime:
    return datetime.now(timezone.utc)


def _obligatorio(valor: str, campo: str) -> str:
    limpio = str(valor or "").strip()
    if not limpio:
        raise ErrorCatalogoClientes(f"{campo} es obligatorio")
    return limpio


def _opcional(valor: str | None) -> str:
    return str(valor or "").strip()


def _fecha_iso(valor: str, campo: str) -> None:
    try:
        fecha = datetime.fromisoformat(valor)
    except (TypeError, ValueError) as error:
        raise ErrorCatalogoClientes(f"{campo} debe ser una fecha ISO válida") from error
    if fecha.tzinfo is None:
        raise ErrorCatalogoClientes(f"{campo} debe incluir zona horaria")


@dataclass(frozen=True)
class Cliente:
    cliente_id: str
    razon_social: str
    nombre_normalizado: str
    nombre_comercial: str
    rut: str
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
    def desde_dict(cls, datos: object) -> "Cliente":
        if not isinstance(datos, dict):
            raise CatalogoClientesCorruptoError("cada cliente debe ser un objeto JSON")
        campos = set(cls.__dataclass_fields__)
        if set(datos) != campos or not isinstance(datos.get("aliases"), list):
            raise CatalogoClientesCorruptoError("campos de cliente incompatibles")
        try:
            cliente = cls(**{**datos, "aliases": tuple(datos["aliases"])})
            _validar_cliente(cliente)
        except (TypeError, ErrorCatalogoClientes) as error:
            raise CatalogoClientesCorruptoError(str(error)) from error
        return cliente


def _claves_cliente(cliente: Cliente) -> set[str]:
    valores = [cliente.razon_social, cliente.nombre_comercial, *cliente.aliases]
    return {normalizar_nombre_cliente(valor) for valor in valores if _opcional(valor)}


def _claves_identidad(cliente: Cliente) -> set[str]:
    """Claves únicas: razón social y alias; el nombre comercial puede ser compartido."""
    return {
        normalizar_nombre_cliente(valor)
        for valor in [cliente.razon_social, *cliente.aliases]
        if _opcional(valor)
    }


def _validar_cliente(cliente: Cliente) -> None:
    _obligatorio(cliente.cliente_id, "cliente_id")
    razon = _obligatorio(cliente.razon_social, "razon_social")
    normalizado = normalizar_nombre_cliente(razon)
    if not normalizado or cliente.nombre_normalizado != normalizado:
        raise ErrorCatalogoClientes("nombre_normalizado no corresponde a razon_social")
    _obligatorio(cliente.fuente, "fuente")
    if cliente.rut and normalizar_rut_cliente(cliente.rut) != cliente.rut:
        raise ErrorCatalogoClientes("RUT no está en formato canónico")
    try:
        EstadoCalidadCliente(cliente.estado_calidad)
        EstadoVigenciaCliente(cliente.estado_vigencia)
    except ValueError as error:
        raise ErrorCatalogoClientes("estado de calidad o vigencia no permitido") from error
    if any(not _opcional(alias) for alias in cliente.aliases):
        raise ErrorCatalogoClientes("los alias no pueden estar vacíos")
    claves_alias = [normalizar_nombre_cliente(alias) for alias in cliente.aliases]
    if len(claves_alias) != len(set(claves_alias)):
        raise ErrorCatalogoClientes("el cliente contiene alias duplicados")
    if cliente.nombre_normalizado in claves_alias:
        raise ErrorCatalogoClientes("un alias no puede duplicar la razón social")
    _fecha_iso(cliente.fecha_creacion, "fecha_creacion")
    _fecha_iso(cliente.fecha_modificacion, "fecha_modificacion")


class CatalogoClientes:
    """Administra identidades de clientes sin conectarlas al extractor."""

    def __init__(
        self,
        ruta: str | Path = "catalogos/clientes.json",
        *,
        reloj: Callable[[], datetime] = _ahora_utc,
        generador_id: Callable[[], object] = uuid4,
    ) -> None:
        self.ruta = Path(ruta)
        self._reloj = reloj
        self._generador_id = generador_id

    def listar(self) -> list[Cliente]:
        return list(self._leer())

    def obtener(self, cliente_id: str) -> Cliente:
        clientes = self._leer()
        return clientes[self._indice(clientes, cliente_id)]

    def buscar(self, texto: str) -> ResultadoBusquedaCliente:
        clave = normalizar_nombre_cliente(_obligatorio(texto, "texto"))
        coincidencias = [cliente for cliente in self._leer() if clave in _claves_cliente(cliente)]
        if len(coincidencias) == 1:
            return ResultadoBusquedaCliente(
                EstadoBusquedaCliente.COINCIDENCIA, coincidencias[0], 1
            )
        if len(coincidencias) > 1:
            return ResultadoBusquedaCliente(
                EstadoBusquedaCliente.AMBIGUA, None, len(coincidencias)
            )
        return ResultadoBusquedaCliente(EstadoBusquedaCliente.SIN_COINCIDENCIA)

    def crear(
        self,
        *,
        razon_social: str,
        fuente: str,
        nombre_comercial: str = "",
        rut: str = "",
        aliases: Iterable[str] = (),
        estado_calidad: EstadoCalidadCliente | str = EstadoCalidadCliente.PENDIENTE,
        observacion: str = "",
    ) -> Cliente:
        clientes = self._leer()
        razon = _obligatorio(razon_social, "razon_social")
        alias_limpios = tuple(_obligatorio(alias, "alias") for alias in aliases)
        instante = self._instante_iso()
        cliente = Cliente(
            cliente_id=str(self._generador_id()),
            razon_social=razon,
            nombre_normalizado=normalizar_nombre_cliente(razon),
            nombre_comercial=_opcional(nombre_comercial),
            rut=normalizar_rut_cliente(rut),
            aliases=alias_limpios,
            estado_calidad=EstadoCalidadCliente(estado_calidad).value,
            estado_vigencia=EstadoVigenciaCliente.ACTIVO.value,
            fuente=_obligatorio(fuente, "fuente"),
            observacion=_opcional(observacion),
            fecha_creacion=instante,
            fecha_modificacion=instante,
        )
        _validar_cliente(cliente)
        self._validar_identidad(clientes, cliente)
        clientes.append(cliente)
        self._escribir(clientes)
        return cliente

    def editar(
        self,
        cliente_id: str,
        *,
        modificacion_manual: bool = False,
        razon_social: str | None = None,
        nombre_comercial: str | None = None,
        rut: str | None = None,
        limpiar_rut: bool = False,
        estado_calidad: EstadoCalidadCliente | str | None = None,
        fuente: str | None = None,
        observacion: str | None = None,
    ) -> Cliente:
        clientes = self._leer()
        indice = self._indice(clientes, cliente_id)
        actual = clientes[indice]
        self._proteger(actual, modificacion_manual)
        if limpiar_rut and rut is not None:
            raise ErrorCatalogoClientes("no combine limpiar_rut con un RUT nuevo")
        razon = actual.razon_social if razon_social is None else _obligatorio(razon_social, "razon_social")
        rut_nuevo = "" if limpiar_rut else actual.rut if rut is None else normalizar_rut_cliente(rut)
        editado = Cliente(
            cliente_id=actual.cliente_id,
            razon_social=razon,
            nombre_normalizado=normalizar_nombre_cliente(razon),
            nombre_comercial=actual.nombre_comercial if nombre_comercial is None else _opcional(nombre_comercial),
            rut=rut_nuevo,
            aliases=actual.aliases,
            estado_calidad=actual.estado_calidad if estado_calidad is None else EstadoCalidadCliente(estado_calidad).value,
            estado_vigencia=actual.estado_vigencia,
            fuente=actual.fuente if fuente is None else _obligatorio(fuente, "fuente"),
            observacion=actual.observacion if observacion is None else _opcional(observacion),
            fecha_creacion=actual.fecha_creacion,
            fecha_modificacion=self._instante_iso(),
        )
        _validar_cliente(editado)
        self._validar_identidad(clientes, editado, excluir_id=actual.cliente_id)
        clientes[indice] = editado
        self._escribir(clientes)
        return editado

    def agregar_alias(
        self, cliente_id: str, alias: str, *, modificacion_manual: bool = False
    ) -> Cliente:
        clientes = self._leer()
        indice = self._indice(clientes, cliente_id)
        actual = clientes[indice]
        self._proteger(actual, modificacion_manual)
        alias_limpio = _obligatorio(alias, "alias")
        editado = replace(
            actual,
            aliases=(*actual.aliases, alias_limpio),
            fecha_modificacion=self._instante_iso(),
        )
        _validar_cliente(editado)
        self._validar_identidad(clientes, editado, excluir_id=actual.cliente_id, error_alias=True)
        clientes[indice] = editado
        self._escribir(clientes)
        return editado

    def desactivar(
        self, cliente_id: str, *, modificacion_manual: bool = False
    ) -> Cliente:
        clientes = self._leer()
        indice = self._indice(clientes, cliente_id)
        actual = clientes[indice]
        self._proteger(actual, modificacion_manual)
        if actual.estado_vigencia == EstadoVigenciaCliente.INACTIVO.value:
            return actual
        editado = replace(
            actual,
            estado_vigencia=EstadoVigenciaCliente.INACTIVO.value,
            fecha_modificacion=self._instante_iso(),
        )
        clientes[indice] = editado
        self._escribir(clientes)
        return editado

    @staticmethod
    def _proteger(cliente: Cliente, modificacion_manual: bool) -> None:
        if cliente.estado_calidad == EstadoCalidadCliente.CONFIRMADO.value and not modificacion_manual:
            raise ModificacionClienteProtegidaError(
                "El cliente está confirmado; use una modificación manual explícita"
            )

    def _instante_iso(self) -> str:
        instante = self._reloj()
        if instante.tzinfo is None:
            instante = instante.replace(tzinfo=timezone.utc)
        return instante.astimezone(timezone.utc).isoformat()

    def _leer(self) -> list[Cliente]:
        if not self.ruta.exists():
            return []
        try:
            with self.ruta.open("r", encoding="utf-8") as archivo:
                contenido = json.load(archivo)
        except (OSError, json.JSONDecodeError) as error:
            raise CatalogoClientesCorruptoError(f"No se pudo leer el catálogo: {error}") from error
        if not isinstance(contenido, dict) or contenido.get("version_formato") != VERSION_FORMATO:
            raise CatalogoClientesCorruptoError("raíz o versión de formato no compatible")
        registros = contenido.get("clientes")
        if not isinstance(registros, list):
            raise CatalogoClientesCorruptoError("clientes debe ser una lista")
        clientes = [Cliente.desde_dict(registro) for registro in registros]
        try:
            for cliente in clientes:
                self._validar_identidad(clientes, cliente, excluir_id=cliente.cliente_id)
        except ErrorCatalogoClientes as error:
            raise CatalogoClientesCorruptoError(str(error)) from error
        ids = [cliente.cliente_id for cliente in clientes]
        if len(ids) != len(set(ids)):
            raise CatalogoClientesCorruptoError("el catálogo contiene IDs duplicados")
        return clientes

    def _escribir(self, clientes: Iterable[Cliente]) -> None:
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        contenido = {
            "version_formato": VERSION_FORMATO,
            "clientes": [cliente.a_dict() for cliente in clientes],
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
    def _indice(clientes: list[Cliente], cliente_id: str) -> int:
        buscado = str(cliente_id or "").strip()
        for indice, cliente in enumerate(clientes):
            if cliente.cliente_id == buscado:
                return indice
        raise ClienteNoEncontradoError(f"No existe el cliente {buscado!r}")

    @staticmethod
    def _validar_identidad(
        clientes: Iterable[Cliente], candidato: Cliente, *, excluir_id: str | None = None,
        error_alias: bool = False,
    ) -> None:
        claves_candidato = _claves_identidad(candidato)
        for existente in clientes:
            if existente.cliente_id == excluir_id:
                continue
            if candidato.rut and existente.rut == candidato.rut:
                raise ClienteDuplicadoError("Ya existe un cliente con ese RUT")
            if claves_candidato & _claves_identidad(existente):
                error = AliasDuplicadoError if error_alias else ClienteDuplicadoError
                raise error("El nombre o alias normalizado ya pertenece a otro cliente")
