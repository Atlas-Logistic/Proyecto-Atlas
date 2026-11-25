"""Detección conservadora de una fecha documental alejada de la recepción.

La recepción no es la fecha de emisión: esta señal sólo propone revisión.
No escribe datos, no corrige fechas y no crea confirmaciones.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Iterable, Mapping

UMBRAL_DIAS = 365


def alerta_fecha(fila: Mapping[str, object], aplicaciones: Iterable[Mapping[str, object]] = ()) -> dict | None:
    """Devuelve una alerta, o None cuando falta evidencia o está confirmada.

    Para suprimirla se exige la misma identidad por archivo, una corrección
    explícita de fecha, un actor humano identificado y el valor vigente.
    Los registros automáticos y las decisiones sobre otros campos no cuentan.
    """
    from atlas_core.decisiones_pendientes import _actor_es_humano

    valor = str(fila.get('fecha') or '').strip()
    archivo = str(fila.get('archivo') or '').strip()
    if not archivo:
        return None
    try:
        fecha = datetime.strptime(valor, '%d-%m-%Y').date()
        metricas = json.loads(str(fila.get('metricas_procesamiento_json') or '{}'))
        texto = metricas.get('fecha_recepcion_utc')
        recepcion = datetime.fromisoformat(str(texto or '').replace('Z', '+00:00'))
        if recepcion.tzinfo is None or recepcion.utcoffset() is None:
            return None
        recibida = recepcion.astimezone(timezone.utc).date()
    except (ValueError, TypeError, AttributeError):
        return None
    diferencia = (recibida - fecha).days
    if abs(diferencia) <= UMBRAL_DIAS:
        return None
    for decision in aplicaciones:
        if not isinstance(decision, Mapping):
            continue
        documento = decision.get('documento')
        if not isinstance(documento, Mapping) or str(documento.get('archivo') or '').strip() != archivo:
            continue
        if decision.get('tipo') != 'CORRECCION_DOCUMENTAL_OPERADOR' or decision.get('campo') != 'fecha':
            continue
        if str(decision.get('valor_corregido') or '').strip() != valor:
            continue
        actor = str(decision.get('actor') or '').strip()
        confirmante = str(decision.get('confirmado_por') or '').strip()
        if ((confirmante and _actor_es_humano(confirmante))
                or (not confirmante and actor and _actor_es_humano(actor))):
            return None
    return {'archivo': archivo, 'numero_guia': str(fila.get('numero_guia') or '').strip(),
            'fecha_documental': valor, 'fecha_recepcion_utc': recepcion.astimezone(timezone.utc).isoformat(),
            'diferencia_dias': diferencia, 'motivo': 'FECHA_ALEJADA_RECEPCION'}


def actualizar_alertas(filas, decisiones, aplicaciones, *, guias_objetivo=None):
    """Fusiona únicamente alertas de fecha en el alcance; no modifica filas ni ledger."""
    from collections import Counter
    from atlas_core.decisiones_pendientes import crear_decision

    filas = list(filas)
    decisiones = list(decisiones)
    aplicaciones = list(aplicaciones)
    objetivo = None if guias_objetivo is None else set(guias_objetivo)
    archivos = Counter(str(f.get('archivo') or '').strip() for f in filas)
    guias = Counter(str(f.get('numero_guia') or '').strip() for f in filas)
    evaluables = {str(f.get('archivo') or '').strip(): f for f in filas
                  if str(f.get('archivo') or '').strip()
                  and archivos[str(f.get('archivo') or '').strip()] == 1
                  and str(f.get('numero_guia') or '').strip()
                  and guias[str(f.get('numero_guia') or '').strip()] == 1
                  and (objetivo is None or str(f.get('numero_guia') or '').strip() in objetivo)}
    salida = [d for d in decisiones if not (
        d.get('tipo') == 'FECHA_SOSPECHOSA'
        and str((d.get('documento') or {}).get('archivo') or '').strip() in evaluables)]
    for archivo, f in evaluables.items():
        aviso = alerta_fecha(f, aplicaciones)
        if aviso is None:
            continue
        salida.append(crear_decision(
            tipo='FECHA_SOSPECHOSA', entidad='DOCUMENTO', archivo=archivo,
            numero_guia=aviso['numero_guia'], numero_transporte=str(f.get('numero_transporte') or ''),
            campo='fecha', valor_documental=aviso['fecha_documental'], valor_normalizado=aviso['fecha_documental'],
            identidad_resuelta=None, candidatos=[], motivos=[aviso['motivo']],
            evidencias=[{'tipo': 'FECHA_RECEPCION', 'valor': aviso['fecha_recepcion_utc']}],
            acciones_permitidas=['POSPONER'], contexto={'fecha_recepcion_utc': aviso['fecha_recepcion_utc']}))
    return salida
