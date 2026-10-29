"""Validadores de los campos documentales que un operador puede corregir.

Módulo liviano (sin OCR, NumPy ni E/S): lo usan la interpretación y la
validación de B1, que en Desktop corren bajo SOLO CONSULTA, y el reparador
(`reprocesamiento_reparador`), que los reexporta con los mismos nombres.
"""
from __future__ import annotations

import re
from datetime import datetime

from atlas_core.extractor import _patente_valida
from atlas_core.modelos import EstadoValidacion
from atlas_core.validadores import validar_rut_chileno


_AUSENTES = {"", "No encontrado", "REVISAR", "Ilegible"}


def _fecha_emision_valida(valor: str) -> bool:
    """Fecha documental canónica: DD-MM-AAAA y dentro de un rango operativo.

    El dataset histórico de Atlas usa este formato (no ISO); validarla aquí
    impide que una corrección humana deje una fecha que los consumidores de
    viajes no puedan interpretar.
    """
    try:
        fecha = datetime.strptime(valor, "%d-%m-%Y").date()
    except ValueError:
        return False
    return 2000 <= fecha.year <= 2100


def _peso_documental_valido(valor: str) -> bool:
    # Kilogramos enteros: sin signo, decimales ni separadores ambiguos.
    return bool(re.fullmatch(r"[1-9][0-9]{0,5}", valor)) and int(valor) <= 100_000


def _hora_documental_valida(valor: str) -> bool:
    return bool(re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", valor))


def _material_documental_valido(valor: str) -> bool:
    # "NO DETERMINADO" es justamente la ausencia que se corrige: nunca un material.
    marcador = " ".join(str(valor).replace("_", " ").split()).upper()
    ausentes = {a.upper() for a in _AUSENTES} | {"NO DETERMINADO", "NO DETERMINADA"}
    return valor not in _AUSENTES and marcador not in ausentes and len(valor) <= 200


CAMPOS_FOCALES_CONOCIDOS: dict[str, object] = {
    "cliente": lambda v: v not in _AUSENTES,
    "rut_cliente": lambda v: validar_rut_chileno(v).estado == EstadoValidacion.VALIDO,
    "codigo_cliente": lambda v: v not in _AUSENTES,
    "cod_destinatario": lambda v: v not in _AUSENTES,
    "obra_destino": lambda v: v not in _AUSENTES,
    "despachar_a_crudo": lambda v: v not in _AUSENTES,
    "patente_tracto": lambda v: v not in _AUSENTES and _patente_valida(v),
    "patente_rampla": lambda v: v not in _AUSENTES and _patente_valida(v),
    # Caso 480715: número AZA completo, nunca un fragmento OCR -- más
    # estricto que `CAMPOS_REPARABLES` (\d{6,}) porque aquí no hay
    # reextracción que lo respalde, sólo el valor aportado por el operador.
    "numero_transporte": lambda v: bool(re.fullmatch(r"[0-9]{10}", v)),
}

# No se exponen al reparador genérico: únicamente
# DOCUMENTO_CORREGIR_CAMPO los habilita después de producir preview,
# confirmación humana, respaldo y auditoría. Así mantenemos la superficie
# previa del reparador (que también usan mantenimientos técnicos) acotada.
CAMPOS_DOCUMENTALES_CONTROLADOS: dict[str, object] = {
    # No gatillan OCR ni una reconciliación global; el ledger posterior
    # protege cada valor de OCR.
    "fecha": _fecha_emision_valida,
    "peso_kg": _peso_documental_valido,
    "hora_entrada_aza": _hora_documental_valida,
    "hora_salida_aza": _hora_documental_valida,
    "descripcion_material": _material_documental_valido,
}
