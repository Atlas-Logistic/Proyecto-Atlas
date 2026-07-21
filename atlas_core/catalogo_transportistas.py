"""Contratos básicos del Catálogo Maestro de Transportistas."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from uuid import UUID


class EstadoCalidadTransportista(str, Enum):
    PENDIENTE = "PENDIENTE"
    CONFIRMADO = "CONFIRMADO"
    REQUIERE_REVISION = "REQUIERE_REVISION"


class EstadoVigenciaTransportista(str, Enum):
    ACTIVO = "ACTIVO"
    INACTIVO = "INACTIVO"


class EstadoVigenciaAliasTransportista(str, Enum):
    ACTIVO = "ACTIVO"
    INACTIVO = "INACTIVO"


class TipoAliasTransportista(str, Enum):
    ALIAS = "ALIAS"
    RAZON_SOCIAL_ANTERIOR = "RAZON_SOCIAL_ANTERIOR"
    NOMBRE_COMERCIAL_ANTERIOR = "NOMBRE_COMERCIAL_ANTERIOR"


class EstadoBusquedaTransportista(str, Enum):
    COINCIDENCIA = "COINCIDENCIA"
    REQUIERE_REACTIVACION = "REQUIERE_REACTIVACION"
    PROPUESTA_EXISTENTE = "PROPUESTA_EXISTENTE"
    EN_REVISION = "EN_REVISION"
    AMBIGUA = "AMBIGUA"
    SIN_COINCIDENCIA = "SIN_COINCIDENCIA"


class MotivoRevisionBusquedaTransportista(str, Enum):
    ESTADO_CALIDAD = "ESTADO_CALIDAD"
    ALIAS_INACTIVO = "ALIAS_INACTIVO"


class TipoOrigenCoincidenciaTransportista(str, Enum):
    RAZON_SOCIAL = "RAZON_SOCIAL"
    NOMBRE_COMERCIAL = "NOMBRE_COMERCIAL"
    ALIAS_ACTIVO = "ALIAS_ACTIVO"
    ALIAS_INACTIVO = "ALIAS_INACTIVO"


class ErrorCatalogoTransportistas(ValueError):
    """Error base propio del catálogo de transportistas."""


class ErrorValidacionTransportista(ErrorCatalogoTransportistas):
    """Un valor no cumple el contrato estructural del catálogo."""


class ErrorRutTransportista(ErrorValidacionTransportista):
    """Un RUT no cumple su estructura o dígito verificador."""


_GUIONES_UNICODE = dict.fromkeys(
    map(ord, "\u2010\u2011\u2012\u2013\u2014\u2015\u2212\ufe58\ufe63\uff0d"), "-"
)
_APOSTROFOS_TIPOGRAFICOS = dict.fromkeys(
    map(ord, "\u2018\u2019\u201a\u201b\u2032\u2035\uff07"), "'"
)
_SUFIJOS_TERMINALES = (
    (re.compile(r"(?:\s+|[,.]\s*)L\.?\s*T\.?\s*D\.?\s*A\.?$"), "LTDA"),
    (re.compile(r"(?:\s+|[,.]\s*)S\.?\s*P\.?\s*A\.?$"), "SPA"),
    (re.compile(r"(?:\s+|[,.]\s*)S\.?\s*A\.?$"), "SA"),
)


def normalizar_nombre_transportista(valor: object) -> str:
    """Genera una clave exacta conservadora sin equivalencias semánticas."""
    if valor is None:
        raise ErrorValidacionTransportista("el nombre es obligatorio")
    try:
        texto = str(valor).strip()
    except Exception as error:
        raise ErrorValidacionTransportista("el nombre no puede convertirse a texto") from error
    if not texto:
        raise ErrorValidacionTransportista("el nombre es obligatorio")

    texto = texto.translate(_GUIONES_UNICODE).translate(_APOSTROFOS_TIPOGRAFICOS)
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(caracter for caracter in texto if not unicodedata.combining(caracter))
    texto = " ".join(texto.upper().split())

    for patron, sufijo in _SUFIJOS_TERMINALES:
        coincidencia = patron.search(texto)
        if coincidencia is not None:
            texto = f"{texto[:coincidencia.start()].rstrip()} {sufijo}"
            break
    return texto


def normalizar_rut_transportista(valor: object) -> str:
    """Valida un RUT chileno y devuelve su forma canónica sin puntos."""
    if valor is None or not str(valor).strip():
        return ""
    texto = str(valor).strip()
    if re.search(r"[^0-9Kk.\-\s]", texto):
        raise ErrorRutTransportista("RUT inválido")
    compacto = re.sub(r"\s", "", texto)
    if not re.fullmatch(r"(?:[0-9]{1,8}|[0-9]{1,2}(?:\.[0-9]{3}){2})-?[0-9Kk]", compacto):
        raise ErrorRutTransportista("RUT inválido")
    limpio = re.sub(r"[.\-]", "", compacto).upper()

    cuerpo, verificador = limpio[:-1], limpio[-1]
    suma = 0
    factor = 2
    for digito in reversed(cuerpo):
        suma += int(digito) * factor
        factor = factor + 1 if factor < 7 else 2
    resultado = 11 - suma % 11
    esperado = "0" if resultado == 11 else "K" if resultado == 10 else str(resultado)
    if verificador != esperado:
        raise ErrorRutTransportista("RUT inválido")
    return f"{int(cuerpo)}-{verificador}"


def validar_uuid_transportista(valor: object) -> str:
    """Acepta UUID textual, recorta espacios exteriores y lo canoniza."""
    if type(valor) is not str or not valor.strip():
        raise ErrorValidacionTransportista("UUID inválido")
    try:
        return str(UUID(valor.strip()))
    except (ValueError, AttributeError) as error:
        raise ErrorValidacionTransportista("UUID inválido") from error


def validar_fecha_iso8601_transportista(
    valor: object, *, permitir_vacia: bool = False
) -> str:
    """Valida una fecha-hora ISO 8601 consciente de zona y la canoniza."""
    if type(valor) is not str:
        raise ErrorValidacionTransportista("la fecha debe ser texto ISO 8601")
    texto = valor.strip()
    if not texto:
        if permitir_vacia:
            return ""
        raise ErrorValidacionTransportista("la fecha es obligatoria")
    try:
        fecha = datetime.fromisoformat(texto)
    except ValueError as error:
        raise ErrorValidacionTransportista("la fecha debe ser ISO 8601 válida") from error
    if fecha.tzinfo is None or fecha.utcoffset() is None:
        raise ErrorValidacionTransportista("la fecha debe incluir zona horaria")
    return fecha.isoformat()


def _texto_obligatorio(valor: object, campo: str) -> str:
    if type(valor) is not str or not valor.strip():
        raise ErrorValidacionTransportista(f"{campo} debe ser texto no vacío")
    return valor


def _texto_opcional(valor: object, campo: str) -> str:
    if type(valor) is not str:
        raise ErrorValidacionTransportista(f"{campo} debe ser texto")
    return valor


def _fecha_validada(valor: object, campo: str, *, permitir_vacia: bool = False) -> datetime | None:
    try:
        canonica = validar_fecha_iso8601_transportista(valor, permitir_vacia=permitir_vacia)
    except ErrorValidacionTransportista as error:
        raise ErrorValidacionTransportista(f"{campo} inválida") from error
    return None if not canonica else datetime.fromisoformat(canonica)


def _exigir_campos_exactos(datos: object, campos: tuple[str, ...], modelo: str) -> dict[str, object]:
    if type(datos) is not dict:
        raise ErrorValidacionTransportista(f"{modelo} debe ser un objeto")
    recibidos = set(datos)
    esperados = set(campos)
    if recibidos != esperados:
        raise ErrorValidacionTransportista(f"campos de {modelo} incompatibles")
    return datos


def _enum_desde_texto(valor: object, enum: type[Enum], campo: str) -> Enum:
    if type(valor) is not str:
        raise ErrorValidacionTransportista(f"{campo} debe ser texto")
    try:
        return enum(valor)
    except ValueError as error:
        raise ErrorValidacionTransportista(f"{campo} contiene un valor desconocido") from error


@dataclass(frozen=True)
class AliasTransportista:
    alias_id: str
    valor: str
    tipo: TipoAliasTransportista
    estado_vigencia: EstadoVigenciaAliasTransportista
    fuente: str
    observacion: str
    fecha_confirmacion_valor: str
    fecha_creacion: str
    fecha_modificacion: str

    _CAMPOS = (
        "alias_id", "valor", "tipo", "estado_vigencia", "fuente", "observacion",
        "fecha_confirmacion_valor", "fecha_creacion", "fecha_modificacion",
    )

    def __post_init__(self) -> None:
        if validar_uuid_transportista(self.alias_id) != self.alias_id:
            raise ErrorValidacionTransportista("alias_id debe ser un UUID canónico")
        _texto_obligatorio(self.valor, "valor")
        if not isinstance(self.tipo, TipoAliasTransportista):
            raise ErrorValidacionTransportista("tipo de alias inválido")
        if not isinstance(self.estado_vigencia, EstadoVigenciaAliasTransportista):
            raise ErrorValidacionTransportista("vigencia de alias inválida")
        _texto_obligatorio(self.fuente, "fuente")
        _texto_opcional(self.observacion, "observacion")
        confirmacion = _fecha_validada(self.fecha_confirmacion_valor, "fecha_confirmacion_valor")
        creacion = _fecha_validada(self.fecha_creacion, "fecha_creacion")
        modificacion = _fecha_validada(self.fecha_modificacion, "fecha_modificacion")
        assert confirmacion is not None and creacion is not None and modificacion is not None
        if not confirmacion <= creacion <= modificacion:
            raise ErrorValidacionTransportista("orden temporal del alias inválido")

    def a_dict(self) -> dict[str, object]:
        return {
            "alias_id": self.alias_id,
            "valor": self.valor,
            "tipo": self.tipo.value,
            "estado_vigencia": self.estado_vigencia.value,
            "fuente": self.fuente,
            "observacion": self.observacion,
            "fecha_confirmacion_valor": self.fecha_confirmacion_valor,
            "fecha_creacion": self.fecha_creacion,
            "fecha_modificacion": self.fecha_modificacion,
        }

    @classmethod
    def desde_dict(cls, datos: object) -> "AliasTransportista":
        contenido = _exigir_campos_exactos(datos, cls._CAMPOS, "alias")
        try:
            return cls(
                alias_id=contenido["alias_id"],
                valor=contenido["valor"],
                tipo=_enum_desde_texto(contenido["tipo"], TipoAliasTransportista, "tipo"),
                estado_vigencia=_enum_desde_texto(
                    contenido["estado_vigencia"],
                    EstadoVigenciaAliasTransportista,
                    "estado_vigencia",
                ),
                fuente=contenido["fuente"],
                observacion=contenido["observacion"],
                fecha_confirmacion_valor=contenido["fecha_confirmacion_valor"],
                fecha_creacion=contenido["fecha_creacion"],
                fecha_modificacion=contenido["fecha_modificacion"],
            )
        except (ValueError, TypeError, ErrorValidacionTransportista) as error:
            if isinstance(error, ErrorValidacionTransportista):
                raise
            raise ErrorValidacionTransportista("alias inválido") from error


@dataclass(frozen=True)
class Transportista:
    transportista_id: str
    razon_social: str
    fuente_razon_social: str
    fecha_confirmacion_razon_social: str
    nombre_normalizado: str
    nombre_comercial: str
    rut: str
    aliases: tuple[AliasTransportista, ...]
    pais: str
    estado_calidad: EstadoCalidadTransportista
    estado_vigencia: EstadoVigenciaTransportista
    fuente: str
    observacion: str
    fecha_creacion: str
    fecha_modificacion: str

    _CAMPOS = (
        "transportista_id", "razon_social", "fuente_razon_social",
        "fecha_confirmacion_razon_social", "nombre_normalizado", "nombre_comercial",
        "rut", "aliases", "pais", "estado_calidad", "estado_vigencia", "fuente",
        "observacion", "fecha_creacion", "fecha_modificacion",
    )

    def __post_init__(self) -> None:
        if validar_uuid_transportista(self.transportista_id) != self.transportista_id:
            raise ErrorValidacionTransportista("transportista_id debe ser un UUID canónico")
        _texto_obligatorio(self.razon_social, "razon_social")
        _texto_obligatorio(self.fuente_razon_social, "fuente_razon_social")
        _texto_opcional(self.fecha_confirmacion_razon_social, "fecha_confirmacion_razon_social")
        _texto_obligatorio(self.nombre_normalizado, "nombre_normalizado")
        if self.nombre_normalizado != normalizar_nombre_transportista(self.razon_social):
            raise ErrorValidacionTransportista("nombre_normalizado inconsistente")
        _texto_opcional(self.nombre_comercial, "nombre_comercial")
        _texto_opcional(self.rut, "rut")
        if self.rut:
            try:
                if normalizar_rut_transportista(self.rut) != self.rut:
                    raise ErrorRutTransportista("RUT no canónico")
            except ErrorRutTransportista as error:
                raise ErrorValidacionTransportista(
                    "RUT del transportista inválido o no canónico"
                ) from error
        if type(self.aliases) is not tuple or not all(
            type(alias) is AliasTransportista for alias in self.aliases
        ):
            raise ErrorValidacionTransportista("aliases debe ser una tupla de AliasTransportista")
        if self.pais != "CL":
            raise ErrorValidacionTransportista("pais debe ser CL")
        if not isinstance(self.estado_calidad, EstadoCalidadTransportista):
            raise ErrorValidacionTransportista("estado_calidad inválido")
        if not isinstance(self.estado_vigencia, EstadoVigenciaTransportista):
            raise ErrorValidacionTransportista("estado_vigencia inválido")
        _texto_obligatorio(self.fuente, "fuente")
        _texto_opcional(self.observacion, "observacion")
        creacion = _fecha_validada(self.fecha_creacion, "fecha_creacion")
        modificacion = _fecha_validada(self.fecha_modificacion, "fecha_modificacion")
        assert creacion is not None and modificacion is not None
        if creacion > modificacion:
            raise ErrorValidacionTransportista("orden temporal del transportista inválido")

        confirmacion = _fecha_validada(
            self.fecha_confirmacion_razon_social,
            "fecha_confirmacion_razon_social",
            permitir_vacia=True,
        )
        if self.estado_calidad is EstadoCalidadTransportista.PENDIENTE and confirmacion is not None:
            raise ErrorValidacionTransportista("un transportista pendiente no puede estar confirmado")
        if self.estado_calidad is EstadoCalidadTransportista.CONFIRMADO and confirmacion is None:
            raise ErrorValidacionTransportista("un transportista confirmado requiere fecha")
        if confirmacion is not None and confirmacion > modificacion:
            raise ErrorValidacionTransportista("fecha de confirmación posterior a modificación")

        ids = [alias.alias_id for alias in self.aliases]
        if len(ids) != len(set(ids)):
            raise ErrorValidacionTransportista("alias_id repetido dentro del transportista")
        claves = [normalizar_nombre_transportista(alias.valor) for alias in self.aliases]
        if len(claves) != len(set(claves)):
            raise ErrorValidacionTransportista("valor de alias repetido dentro del transportista")
        if self.nombre_normalizado in claves:
            raise ErrorValidacionTransportista("alias coincide con la razón social vigente")
        if self.nombre_comercial:
            comercial = normalizar_nombre_transportista(self.nombre_comercial)
            if comercial in claves:
                raise ErrorValidacionTransportista("alias coincide con el nombre comercial vigente")

    def a_dict(self) -> dict[str, object]:
        return {
            "transportista_id": self.transportista_id,
            "razon_social": self.razon_social,
            "fuente_razon_social": self.fuente_razon_social,
            "fecha_confirmacion_razon_social": self.fecha_confirmacion_razon_social,
            "nombre_normalizado": self.nombre_normalizado,
            "nombre_comercial": self.nombre_comercial,
            "rut": self.rut,
            "aliases": [alias.a_dict() for alias in self.aliases],
            "pais": self.pais,
            "estado_calidad": self.estado_calidad.value,
            "estado_vigencia": self.estado_vigencia.value,
            "fuente": self.fuente,
            "observacion": self.observacion,
            "fecha_creacion": self.fecha_creacion,
            "fecha_modificacion": self.fecha_modificacion,
        }

    @classmethod
    def desde_dict(cls, datos: object) -> "Transportista":
        contenido = _exigir_campos_exactos(datos, cls._CAMPOS, "transportista")
        if type(contenido["aliases"]) is not list:
            raise ErrorValidacionTransportista("aliases debe ser una lista")
        try:
            aliases = tuple(AliasTransportista.desde_dict(item) for item in contenido["aliases"])
            return cls(
                transportista_id=contenido["transportista_id"],
                razon_social=contenido["razon_social"],
                fuente_razon_social=contenido["fuente_razon_social"],
                fecha_confirmacion_razon_social=contenido["fecha_confirmacion_razon_social"],
                nombre_normalizado=contenido["nombre_normalizado"],
                nombre_comercial=contenido["nombre_comercial"],
                rut=contenido["rut"],
                aliases=aliases,
                pais=contenido["pais"],
                estado_calidad=_enum_desde_texto(
                    contenido["estado_calidad"], EstadoCalidadTransportista, "estado_calidad"
                ),
                estado_vigencia=_enum_desde_texto(
                    contenido["estado_vigencia"], EstadoVigenciaTransportista, "estado_vigencia"
                ),
                fuente=contenido["fuente"],
                observacion=contenido["observacion"],
                fecha_creacion=contenido["fecha_creacion"],
                fecha_modificacion=contenido["fecha_modificacion"],
            )
        except (ValueError, TypeError, ErrorValidacionTransportista) as error:
            if isinstance(error, ErrorValidacionTransportista):
                raise
            raise ErrorValidacionTransportista("transportista inválido") from error


@dataclass(frozen=True)
class ResultadoBusquedaTransportista:
    estado: EstadoBusquedaTransportista
    motivo_revision: MotivoRevisionBusquedaTransportista | None
    transportista: Transportista | None
    cantidad_candidatos: int
    transportista_ids: tuple[str, ...]
    origenes_coincidencia: tuple[TipoOrigenCoincidenciaTransportista, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.estado, EstadoBusquedaTransportista):
            raise ErrorValidacionTransportista("estado de búsqueda inválido")
        if self.motivo_revision is not None and not isinstance(
            self.motivo_revision, MotivoRevisionBusquedaTransportista
        ):
            raise ErrorValidacionTransportista("motivo de revisión inválido")
        if type(self.cantidad_candidatos) is not int or self.cantidad_candidatos < 0:
            raise ErrorValidacionTransportista("cantidad de candidatos inválida")
        if type(self.transportista_ids) is not tuple:
            raise ErrorValidacionTransportista("transportista_ids debe ser una tupla")
        for identificador in self.transportista_ids:
            if validar_uuid_transportista(identificador) != identificador:
                raise ErrorValidacionTransportista("transportista_id no canónico en resultado")
        if len(self.transportista_ids) != len(set(self.transportista_ids)):
            raise ErrorValidacionTransportista("transportista_ids repetidos")
        if self.transportista_ids != tuple(sorted(self.transportista_ids)):
            raise ErrorValidacionTransportista("transportista_ids sin orden determinista")
        if type(self.origenes_coincidencia) is not tuple or not all(
            type(origen) is TipoOrigenCoincidenciaTransportista
            for origen in self.origenes_coincidencia
        ):
            raise ErrorValidacionTransportista("orígenes de coincidencia inválidos")
        if len(self.origenes_coincidencia) != len(set(self.origenes_coincidencia)):
            raise ErrorValidacionTransportista("orígenes de coincidencia repetidos")

        con_transportista = {
            EstadoBusquedaTransportista.COINCIDENCIA,
            EstadoBusquedaTransportista.REQUIERE_REACTIVACION,
            EstadoBusquedaTransportista.PROPUESTA_EXISTENTE,
            EstadoBusquedaTransportista.EN_REVISION,
        }
        if self.estado in con_transportista:
            if type(self.transportista) is not Transportista:
                raise ErrorValidacionTransportista("el resultado requiere transportista")
            if self.cantidad_candidatos != 1 or self.transportista_ids != (
                self.transportista.transportista_id,
            ):
                raise ErrorValidacionTransportista("candidato individual inconsistente")
            if not self.origenes_coincidencia:
                raise ErrorValidacionTransportista("el resultado con candidato requiere origen")
        elif self.transportista is not None:
            raise ErrorValidacionTransportista("el estado no admite transportista")

        if self.estado is EstadoBusquedaTransportista.EN_REVISION:
            if self.motivo_revision not in tuple(MotivoRevisionBusquedaTransportista):
                raise ErrorValidacionTransportista("EN_REVISION requiere motivo")
            if (
                self.motivo_revision is MotivoRevisionBusquedaTransportista.ALIAS_INACTIVO
                and TipoOrigenCoincidenciaTransportista.ALIAS_INACTIVO
                not in self.origenes_coincidencia
            ):
                raise ErrorValidacionTransportista(
                    "la revisión por alias inactivo requiere ese origen"
                )
        elif self.motivo_revision is not None:
            raise ErrorValidacionTransportista("el estado no admite motivo de revisión")

        if self.estado is EstadoBusquedaTransportista.AMBIGUA:
            if self.cantidad_candidatos <= 1 or self.cantidad_candidatos != len(
                self.transportista_ids
            ):
                raise ErrorValidacionTransportista("resultado ambiguo inconsistente")
            if not self.origenes_coincidencia:
                raise ErrorValidacionTransportista("el resultado ambiguo requiere origen")
        if self.estado is EstadoBusquedaTransportista.SIN_COINCIDENCIA:
            if self.cantidad_candidatos != 0 or self.transportista_ids or self.origenes_coincidencia:
                raise ErrorValidacionTransportista("resultado sin coincidencia inconsistente")
