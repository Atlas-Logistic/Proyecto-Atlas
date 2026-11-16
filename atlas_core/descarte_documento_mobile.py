"""Decisiones humanas sobre documentos Mobile sin clasificar.

El llamador debe suministrar la guarda del escritor operativo en ``comprobar``.
La reversión devuelve el documento a revisión, nunca a procesamiento automático.
"""
from __future__ import annotations

import copy
import uuid
from datetime import datetime, timezone
from pathlib import Path

from atlas_core.almacenamiento_portable import bloqueo_sesion
from atlas_core.expediente_digital import ErrorExpedienteDigital, _actor, _autoria, _auditoria_autoria, _instante
from atlas_core.extraccion_vencimientos_vehiculos import _escribir
from atlas_core.fichas_choferes import leer_almacen, ruta_almacen
from atlas_core.fichas_vehiculos import PENDIENTES
from atlas_core.revision_vehiculo_mobile import _original

MOTIVOS = frozenset({'DUPLICADO', 'DOCUMENTO_INCORRECTO', 'NO_CORRESPONDE', 'OTRO'})


def decidir(raiz, *, empresa, documento_id, sha256, decision, autor, actor, confirmacion_humana,
            comprobar, motivo='', descarte_id='', revisor_no_declarado=False, reloj=lambda: datetime.now(timezone.utc)):
    """DESCARTAR o REVERTIR un descarte concreto; nunca mueve ni borra el original.

    REVERTIR exige el descarte_id vigente, y deja revisión manual obligatoria.
    Un consumidor productivo debe invocarlo dentro de su sesión de escritor.
    """
    actor = _actor(actor)
    autoria = _autoria(autor, revisor_no_declarado, actor)
    autor = autoria['autor']
    if confirmacion_humana is not True or decision not in ('DESCARTAR', 'REVERTIR'):
        raise ErrorExpedienteDigital('Se requiere una decisión humana explícita')
    if not callable(comprobar):
        raise ErrorExpedienteDigital('Se requiere la guarda del escritor')
    if decision == 'DESCARTAR' and motivo not in MOTIVOS:
        raise ErrorExpedienteDigital('Motivo de descarte no admitido')
    if decision == 'REVERTIR' and (not descarte_id or motivo):
        raise ErrorExpedienteDigital('Indique el descarte a revertir, sin motivo de descarte nuevo')
    ruta = ruta_almacen(raiz, empresa)
    comprobar()
    with bloqueo_sesion(Path(raiz) / 'operacion' / 'actual', 'fichas_choferes_' + empresa):
        anterior = leer_almacen(raiz, empresa=empresa)
        if not anterior or anterior.get('version') != 2:
            raise ErrorExpedienteDigital('Almacén de fichas no disponible')
        encontrados = [d for d in anterior.get(PENDIENTES, [])
                       if d.get('documento_id') == documento_id and d.get('origen') == 'MOBILE']
        if len(encontrados) != 1:
            raise ErrorExpedienteDigital('Documento Mobile sin clasificar no encontrado')
        original = encontrados[0]
        if not sha256 or original.get('sha256') != sha256:
            raise ErrorExpedienteDigital('La identidad del original cambió')
        _original(raiz, empresa, original)
        actual_descarte = original.get('descarte') or {}
        if decision == 'DESCARTAR':
            if (original.get('estado_revision') != 'PENDIENTE_EXTRACCION' or original.get('revision_humana')
                    or original.get('rechazo') or original.get('reemplazado_por')
                    or original.get('transicion_programada') or actual_descarte):
                raise ErrorExpedienteDigital('El documento no está disponible para descarte')
            identificador = str(uuid.uuid4())
        else:
            if (original.get('estado_revision') != 'RECHAZADO_EN_REVISION' or actual_descarte.get('id') != descarte_id
                    or (original.get('rechazo') or {}).get('id') != descarte_id
                    or (original.get('revision_humana') or {}).get('id') != descarte_id):
                raise ErrorExpedienteDigital('El descarte cambió o ya fue revertido')
            identificador = descarte_id
        datos = copy.deepcopy(anterior)
        doc = next(d for d in datos[PENDIENTES] if d.get('documento_id') == documento_id)
        instante = _instante(reloj)
        evento = {'accion': 'DOCUMENTO_DESCARTADO' if decision == 'DESCARTAR' else 'DOCUMENTO_DESCARTE_REVERTIDO',
                  'decision': decision, 'descarte_id': identificador, 'documento_id': documento_id,
                  'sha256': sha256, 'autor': autor, 'actor': actor, 'fecha': instante,
                  'motivo': motivo if decision == 'DESCARTAR' else actual_descarte['motivo'],
                  **_auditoria_autoria(autoria)}
        doc.setdefault('historial', []).append(evento)
        if decision == 'DESCARTAR':
            doc['descarte'] = {'id': identificador, 'motivo': motivo, 'autor': autor, 'actor': actor,
                               'en': instante, 'sha256': sha256, 'decision': decision,
                               **_auditoria_autoria(autoria)}
            doc['rechazo'] = copy.deepcopy(doc['descarte'])
            doc['revision_humana'] = copy.deepcopy(doc['descarte'])
            doc['estado_revision'] = 'RECHAZADO_EN_REVISION'
        else:
            doc.pop('descarte')
            doc.pop('rechazo')
            doc.pop('revision_humana')
            doc['estado_revision'] = 'PENDIENTE_EXTRACCION'
            doc['revision_manual_obligatoria'] = True

        def verificar():
            comprobar()
            _original(raiz, empresa, original)

        _escribir(raiz, ruta, empresa, anterior, datos, actor, evento['accion'], evento, verificar)
        return {'documento_id': documento_id, 'estado': doc['estado_revision'],
                'descarte_id': identificador, 'revision_manual_obligatoria': bool(doc.get('revision_manual_obligatoria'))}
