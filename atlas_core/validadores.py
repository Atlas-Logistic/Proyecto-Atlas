"""Validadores especializados y deterministas para datos de documentos."""

import re
from datetime import date

from atlas_core.modelos import CampoProcesado, EstadoValidacion, FuenteCampo


def _digito_verificador(rut_base: str) -> str:
    suma = 0
    multiplicador = 2
    for digito in reversed(rut_base):
        suma += int(digito) * multiplicador
        multiplicador = multiplicador + 1 if multiplicador < 7 else 2

    resto = 11 - (suma % 11)
    if resto == 11:
        return "0"
    if resto == 10:
        return "K"
    return str(resto)


def _formato_canonico(rut_base: str, digito: str) -> str:
    if len(rut_base) <= 3:
        base_formateada = rut_base
    else:
        grupos = []
        restante = rut_base
        while restante:
            grupos.append(restante[-3:])
            restante = restante[:-3]
        base_formateada = ".".join(reversed(grupos))
    return f"{base_formateada}-{digito}"


def _campo_invalido(
    nombre: str,
    valor: object,
    fuente: FuenteCampo,
    confianza: float,
    revision_humana: bool,
    advertencia: str,
) -> CampoProcesado:
    return CampoProcesado(
        nombre=nombre,
        valor=valor,
        fuente=fuente,
        estado=EstadoValidacion.INVALIDO,
        confianza=confianza,
        revision_humana=revision_humana,
        advertencias=[advertencia],
    )


def validar_rut_chileno(
    valor: object,
    nombre: str = "rut",
    fuente: FuenteCampo = FuenteCampo.EXTRACCION,
    confianza: float = 0.0,
    revision_humana: bool = False,
) -> CampoProcesado:
    """Valida un RUT chileno sin corregir ni consultar fuentes externas."""
    if valor is None or (isinstance(valor, str) and not valor.strip()):
        return CampoProcesado(
            nombre=nombre,
            valor=None,
            fuente=fuente,
            estado=EstadoValidacion.AUSENTE,
            confianza=confianza,
            revision_humana=revision_humana,
        )

    if not isinstance(valor, str):
        return _campo_invalido(
            nombre,
            valor,
            fuente,
            confianza,
            revision_humana,
            "El RUT debe recibirse como texto y conservar su dígito verificador",
        )

    coincidencia = re.fullmatch(
        r"\s*((?:[0-9]{1,8}|[0-9]{1,3}(?:\.[0-9]{3})+|[0-9]{1,3}(?: [0-9]{3})+))\s*-\s*([0-9Kk])\s*",
        valor,
    )
    if coincidencia is None:
        return _campo_invalido(
            nombre,
            valor,
            fuente,
            confianza,
            revision_humana,
            "El RUT tiene un formato inválido; se requiere una base numérica y dígito verificador",
        )

    rut_base = re.sub(r"[. ]", "", coincidencia.group(1))
    digito_recibido = coincidencia.group(2).upper()
    if not 1 <= len(rut_base) <= 8:
        return _campo_invalido(
            nombre,
            valor,
            fuente,
            confianza,
            revision_humana,
            "El RUT tiene una longitud inválida",
        )

    digito_esperado = _digito_verificador(rut_base)
    if digito_recibido != digito_esperado:
        return _campo_invalido(
            nombre,
            valor,
            fuente,
            confianza,
            revision_humana,
            f"El dígito verificador es incorrecto; se esperaba {digito_esperado}",
        )

    valor_canonico = _formato_canonico(rut_base, digito_esperado)
    valor_original = valor if valor != valor_canonico else None
    return CampoProcesado(
        nombre=nombre,
        valor=valor_canonico,
        fuente=fuente,
        estado=EstadoValidacion.VALIDO,
        confianza=confianza,
        revision_humana=revision_humana,
        valor_original=valor_original,
    )


def validar_fecha(
    valor: object,
    nombre: str = "fecha",
    fuente: FuenteCampo = FuenteCampo.EXTRACCION,
    confianza: float = 0.0,
    revision_humana: bool = False,
    formato_esperado: str = "YYYY-MM-DD",
) -> CampoProcesado:
    """Valida una fecha explícita y la normaliza al formato ISO."""
    formatos = {"YYYY-MM-DD", "DD/MM/YYYY"}
    if formato_esperado not in formatos:
        raise ValueError(
            "Formato de fecha no soportado; use YYYY-MM-DD o DD/MM/YYYY"
        )

    if valor is None or (isinstance(valor, str) and not valor.strip()):
        return CampoProcesado(
            nombre=nombre,
            valor=None,
            fuente=fuente,
            estado=EstadoValidacion.AUSENTE,
            confianza=confianza,
            revision_humana=revision_humana,
        )

    if not isinstance(valor, str):
        return CampoProcesado(
            nombre=nombre,
            valor=valor,
            fuente=fuente,
            estado=EstadoValidacion.INVALIDO,
            confianza=confianza,
            revision_humana=revision_humana,
            advertencias=["La fecha debe recibirse como texto"],
        )

    texto = valor.strip()
    patron = r"([0-9]{4})-([0-9]{2})-([0-9]{2})" if formato_esperado == "YYYY-MM-DD" else r"([0-9]{2})/([0-9]{2})/([0-9]{4})"
    coincidencia = re.fullmatch(patron, texto)
    if coincidencia is None:
        return CampoProcesado(
            nombre=nombre,
            valor=valor,
            fuente=fuente,
            estado=EstadoValidacion.INVALIDO,
            confianza=confianza,
            revision_humana=revision_humana,
            advertencias=[f"La fecha no cumple el formato esperado {formato_esperado}"],
        )

    if formato_esperado == "YYYY-MM-DD":
        anio, mes, dia = (int(parte) for parte in coincidencia.groups())
    else:
        dia, mes, anio = (int(parte) for parte in coincidencia.groups())

    try:
        fecha = date(anio, mes, dia)
    except ValueError:
        return CampoProcesado(
            nombre=nombre,
            valor=valor,
            fuente=fuente,
            estado=EstadoValidacion.INVALIDO,
            confianza=confianza,
            revision_humana=revision_humana,
            advertencias=["La fecha no existe en el calendario"],
        )

    valor_canonico = fecha.isoformat()
    return CampoProcesado(
        nombre=nombre,
        valor=valor_canonico,
        fuente=fuente,
        estado=EstadoValidacion.VALIDO,
        confianza=confianza,
        revision_humana=revision_humana,
        valor_original=valor if valor != valor_canonico else None,
    )
