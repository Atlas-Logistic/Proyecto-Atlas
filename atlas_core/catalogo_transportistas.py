"""Contratos básicos del Catálogo Maestro de Transportistas."""

from __future__ import annotations

import re
import unicodedata
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
    if not isinstance(valor, str) or not valor.strip():
        raise ErrorValidacionTransportista("UUID inválido")
    try:
        return str(UUID(valor.strip()))
    except (ValueError, AttributeError) as error:
        raise ErrorValidacionTransportista("UUID inválido") from error


def validar_fecha_iso8601_transportista(
    valor: object, *, permitir_vacia: bool = False
) -> str:
    """Valida una fecha-hora ISO 8601 consciente de zona y la canoniza."""
    if not isinstance(valor, str):
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
