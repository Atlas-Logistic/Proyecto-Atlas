"""Validadores de los campos documentales que un operador puede corregir.

Módulo liviano (sin OCR, NumPy ni E/S): lo usan la interpretación y la
validación de B1, que en Desktop corren bajo SOLO CONSULTA, y el reparador
(`reprocesamiento_reparador`), que los reexporta con los mismos nombres.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Iterable, Mapping

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


# Respuestas de una conversación, nunca la descripción de un material: una
# confirmación o negativa no puede quedar guardada como valor documental.
_RESPUESTAS_NO_MATERIAL = frozenset({
    "SI", "SÍ", "NO", "OK", "OKA", "OKEY", "DALE", "CONFIRMO", "CONFIRMADO", "CONFIRMAR", "ACEPTO", "ACEPTAR",
    "CANCELA", "CANCELAR", "CANCELADO", "LISTO", "GRACIAS",
})


def _material_documental_valido(valor: str) -> bool:
    # "NO DETERMINADO" es justamente la ausencia que se corrige: nunca un material.
    marcador = " ".join(str(valor).replace("_", " ").split()).upper()
    ausentes = {a.upper() for a in _AUSENTES} | {"NO DETERMINADO", "NO DETERMINADA"}
    # Un material se nombra con palabras ("BARRAS", "ROLLO 8MM"): sólo cifras o
    # signos, caracteres de control o una respuesta de conversación no lo son.
    return (valor not in _AUSENTES and marcador not in ausentes and len(valor) <= 200
            and re.search(r"[^\W\d_]{2}", valor) is not None
            and not re.search(r"[\x00-\x1f\x7f]", valor)
            and marcador.strip(" .,;:!¡?¿") not in _RESPUESTAS_NO_MATERIAL)


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


# ---------------------------------------------------------------------
# Material confirmado por una persona -- contrato de lectura para la
# proyección del reporte.
#
# Orden real de DOCUMENTO_CORREGIR_CAMPO: preview -> «sí» -> respaldo ->
# marca de publicación -> reparador (dataset) -> asiento en el ledger ->
# bandeja/revalidación -> REPORTE -> auditoría APLICADA. El reporte se
# genera antes de la auditoría, así que no puede exigir APLICADA. El
# asiento del ledger, en cambio, ya existe y es firme: si el reparador
# o el asiento fallan, el canal restaura el respaldo (dataset, bandeja y
# ledger) antes de cualquier reporte, y un corte posterior al asiento se
# completa con el mismo token sin deshacerlo (`recuperar_campo_documental`).
# Una propuesta sin «sí», un rechazo o un fallo nunca dejan asiento.
#
# No es una segunda fuente de verdad: lee el mismo ledger y la misma fila
# del dataset que ya usa el canal, y sólo reconoce la corrección si el
# valor de la fila sigue siendo el que la persona confirmó.
# ---------------------------------------------------------------------

TIPO_LEDGER_CORRECCION_OPERADOR = "CORRECCION_DOCUMENTAL_OPERADOR"
CAMPO_MATERIAL = "descripcion_material"


def _confirmacion_humana(entrada: Mapping[str, object]) -> bool:
    from atlas_core.decisiones_pendientes import _actor_es_humano
    confirmante = str(entrada.get("confirmado_por") or "").strip()
    # Con confirmante registrado decide él (B1 propone, la persona confirma);
    # sin él (ledger antiguo) decide el actor, igual que el resto del ledger.
    return _actor_es_humano(confirmante) if confirmante else _actor_es_humano(entrada.get("actor"))


def material_confirmado_vigente(ledger: Mapping[str, object], fila: Mapping[str, object]) -> dict | None:
    """Corrección humana de material vigente para `fila`, o None.

    Vigente = la ÚLTIMA corrección humana de `descripcion_material`
    asentada en el ledger para este documento (por archivo; por guía sólo
    en asientos antiguos sin archivo) y cuyo `valor_corregido` es
    exactamente el material actual de la fila. Si la fila ya no tiene ese
    valor, o la última corrección no la confirmó una persona, no hay
    material confirmado que publicar."""
    archivo = str(fila.get("archivo") or "").strip()
    guia = str(fila.get("numero_guia") or "").strip()
    actual = " ".join(str(fila.get(CAMPO_MATERIAL) or "").split())
    if not actual or (not archivo and not guia):
        return None
    ultima = None
    aplicaciones = ledger.get("aplicaciones") if hasattr(ledger, "get") else None
    for entrada in aplicaciones or []:
        if not hasattr(entrada, "get") or entrada.get("tipo") != TIPO_LEDGER_CORRECCION_OPERADOR:
            continue
        if str(entrada.get("campo") or "").strip().lower() != CAMPO_MATERIAL:
            continue
        documento = entrada.get("documento")
        if not hasattr(documento, "get"):
            continue
        doc_archivo = str(documento.get("archivo") or "").strip()
        if doc_archivo:
            if doc_archivo != archivo:
                continue
        elif not guia or str(documento.get("numero_guia") or "").strip() != guia:
            continue
        ultima = entrada
    if ultima is None or not _confirmacion_humana(ultima):
        return None
    if " ".join(str(ultima.get("valor_corregido") or "").split()) != actual:
        return None
    return {"valor": actual, "decision_id": ultima.get("decision_id"),
            "confirmado_por": ultima.get("confirmado_por") or ultima.get("actor"), "fecha": ultima.get("fecha")}


def materiales_confirmados_vigentes(ledger: Mapping[str, object],
                                    filas: Iterable[Mapping[str, object]]) -> dict[str, dict]:
    """`material_confirmado_vigente` para varias filas, por archivo."""
    resultado: dict[str, dict] = {}
    for fila in filas:
        vigente = material_confirmado_vigente(ledger, fila)
        if vigente is not None:
            resultado[str(fila.get("archivo") or "").strip()] = vigente
    return resultado
