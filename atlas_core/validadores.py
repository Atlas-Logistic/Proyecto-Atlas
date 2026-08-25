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


def _cuerpo_implausible(rut_base: str) -> bool:
    """Un cuerpo de un solo dígito repetido (11111111, 55555555, ...)
    pasa el dígito verificador matemáticamente -- módulo 11 no distingue
    esto de un RUT real -- pero nunca es una asignación real de RUT
    chileno (caso real: guía de WLADIMIR AGUILAR con "55.555.555-5"
    impreso, dígito verificador correcto pero cuerpo evidentemente
    ficticio). Criterio general -- cualquier dígito repetido, nunca un
    valor concreto hardcodeado -- consistente con los validadores de
    RUT ya usados en la práctica en Chile."""
    return len(rut_base) > 1 and len(set(rut_base)) == 1


def rut_documentalmente_confirmado_invalido(valor: object) -> bool:
    """Bloque FIX RUT DOCUMENTAL -- True SÓLO cuando el RUT es
    estructuralmente inválido de una forma que NO es explicable por un
    simple error de lectura OCR: el dígito verificador CALZA
    matemáticamente (una lectura OCR con un carácter mal leído
    prácticamente nunca preserva el dígito verificador por azar -- 1 en
    11 posibilidades, y encima requiere que el cuerpo resultante sea
    justo un patrón implausible) pero el cuerpo es implausible (dígitos
    repetidos -- ver `_cuerpo_implausible`; caso real: guía de WLADIMIR
    AGUILAR con "55.555.555-5"). Esta es la distinción exigida antes de
    registrar una Incidencia Documental (evidencia de que la guía viene
    realmente impresa así) en vez de tratarlo como duda de OCR (dígito
    verificador que NO calza -- comúnmente un solo carácter mal leído --
    queda para Revisión de Atlas / B1, nunca una incidencia automática)."""
    if not isinstance(valor, str):
        return False
    coincidencia = re.fullmatch(
        r"\s*((?:[0-9]{1,8}|[0-9]{1,3}(?:\.[0-9]{3})+|[0-9]{1,3}(?: [0-9]{3})+))\s*-\s*([0-9Kk])\s*",
        valor,
    )
    if coincidencia is None:
        return False
    rut_base = re.sub(r"[. ]", "", coincidencia.group(1))
    digito_recibido = coincidencia.group(2).upper()
    if not 1 <= len(rut_base) <= 8:
        return False
    if digito_recibido != _digito_verificador(rut_base):
        return False
    return _cuerpo_implausible(rut_base)


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

    if _cuerpo_implausible(rut_base):
        return _campo_invalido(
            nombre,
            valor,
            fuente,
            confianza,
            revision_humana,
            "El RUT tiene un patrón implausible (dígitos repetidos) -- el dígito "
            "verificador calza matemáticamente pero nunca es una asignación real",
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
