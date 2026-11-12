"""Revisión de documentos Mobile en su almacén de origen.

Esta capa no copia documentos al expediente. Los reemplazos entre almacenes
se mantienen pendientes: no existe una transacción atómica entre ambos JSON.
"""
from __future__ import annotations

import copy
import hashlib
import json
from datetime import timezone
from pathlib import Path

from atlas_core.almacenamiento_portable import bloqueo_sesion
from atlas_core.catalogo_vehiculos import cargar_catalogo_vehiculos, normalizar_patente_vehiculo
from atlas_core.fichas_choferes import leer_almacen, ruta_almacen
from atlas_core.fichas_vehiculos import PENDIENTES
from atlas_core.identificacion_patentes import _ficha_vehiculo, _ubicaciones
from atlas_core import expediente_digital as exp


def _buscar(datos, documento_id):
    hallados = [(patente, d) for patente, d in _ubicaciones(datos)
                if d.get('documento_id') == documento_id and d.get('origen') == 'MOBILE']
    if len(hallados) != 1:
        raise exp.ErrorExpedienteDigital('El documento no existe en esta empresa')
    patente, documento = hallados[0]
    if any(d is not documento and d.get('sha256') == documento.get('sha256')
           and (d.get('revision_humana') or d.get('rechazo')) for _, d in _ubicaciones(datos)):
        raise exp.ErrorExpedienteDigital('El original ya tiene una decisión humana en otra ficha')
    if (documento.get('estado_revision') != 'PENDIENTE_EXTRACCION' or documento.get('revision_humana')
            or documento.get('rechazo') or documento.get('reemplazado_por') or documento.get('transicion_programada')):
        raise exp.ErrorExpedienteDigital('El documento ya no está pendiente de revisión')
    return patente, documento


def _original(raiz, empresa, documento):
    carpeta = ruta_almacen(raiz, empresa).parent.resolve()
    ruta = (carpeta / str(documento.get('archivo') or '')).resolve()
    if not documento.get('archivo') or not ruta.is_relative_to(carpeta) or not ruta.is_file():
        raise exp.ErrorExpedienteDigital('El original no está disponible')
    if hashlib.sha256(ruta.read_bytes()).hexdigest() != documento.get('sha256'):
        raise exp.ErrorExpedienteDigital('El original no está íntegro')


def _lectura_ficha(doc):
    lectura = copy.deepcopy(doc.get('extraccion_automatica') or {})
    archivos = lectura.get('archivos') or []
    if len(archivos) != 1 or archivos[0].get('sha256') != doc.get('sha256') or archivos[0].get('archivo') != doc.get('archivo'):
        return {}
    lectura['sha256'] = doc['sha256']
    identificacion = doc.get('identificacion_patente') or {}
    patente = identificacion.get('patente')
    lectura.setdefault('campos', {})['patente'] = {
        'valor': patente, 'estado': 'EXTRAIDO' if patente and identificacion.get('evidencia') else 'PENDIENTE_REVISION',
        'motivo': identificacion.get('motivo') or '', 'evidencia': identificacion.get('evidencia') or []}
    # El estado del OCR de vencimiento puede ser SIN_DATOS aunque el tipo y
    # la patente sí tengan evidencia. La revisión permite completar faltantes.
    lectura['estado'] = 'COMPLETA'
    return lectura


def _contexto(raiz, empresa, referencia, documento_id, propuesta, reloj, carpeta_catalogos=None):
    fichas = leer_almacen(raiz, empresa=empresa)
    if not fichas or fichas.get('version') != 2:
        raise exp.ErrorExpedienteDigital('Almacén de fichas no disponible')
    patente_actual, doc = _buscar(fichas, documento_id)
    _original(raiz, empresa, doc)
    if not patente_actual and referencia != 'SIN_CLASIFICAR':
        raise exp.ErrorExpedienteDigital('El documento no pertenece a este vehículo')
    catalogos = exp._carpeta(raiz, carpeta_catalogos)
    catalogo_ruta = catalogos / 'vehiculos.json'
    catalogo = cargar_catalogo_vehiculos(catalogo_ruta)
    seleccion = normalizar_patente_vehiculo(str((propuesta or {}).get('patente') or patente_actual or
                                                (doc.get('identificacion_patente') or {}).get('patente') or ''))
    coincidentes = [v for v in catalogo.homologables() if seleccion in (v.patente_canonica, *v.aliases)] if seleccion else []
    vehiculo = coincidentes[0] if len(coincidentes) == 1 else None
    if patente_actual:
        if exp._vehiculo_de(raiz, carpeta_catalogos, referencia) != exp._vehiculo_de(raiz, carpeta_catalogos, patente_actual):
            raise exp.ErrorExpedienteDigital('El documento no pertenece a este vehículo')
    if patente_actual and vehiculo and exp._vehiculo_de(raiz, carpeta_catalogos, patente_actual) != vehiculo.vehiculo_id:
        raise exp.ErrorExpedienteDigital('La patente no corresponde al vehículo de la ficha')
    clave = vehiculo.vehiculo_id if vehiculo else ''
    expediente = exp.leer_expediente(raiz, empresa=empresa)
    if any(d.get('documento_id') == documento_id for d in expediente['documentos']):
        raise exp.ErrorExpedienteDigital('El identificador del documento es ambiguo entre almacenes')
    relacionados = exp._buscar_expediente(expediente, exp.VEHICULO, [clave]) if clave else None
    anteriores, vista_anteriores = [], []
    if relacionados:
        for d in expediente['documentos']:
            if (d.get('expediente_id') == relacionados['expediente_id'] and d.get('estado') == exp.ACTIVO
                    and (not d.get('pendiente_revision') or d.get('transicion_programada'))
                    and exp._dias_para_vencer(d.get('fecha_vencimiento') or '', reloj().date()) is not None):
                anteriores.append({'documento_id': d['documento_id'], 'tipo': d['tipo'],
                                   'vencimiento': d['fecha_vencimiento'], 'coberturas': exp._coberturas_documento(d),
                                   'origenes': [d['documento_id']], 'fuente': 'EXPEDIENTE'})
                vista_anteriores.append(exp._resumen_documento(d))
    for p, d in _ubicaciones(fichas):
        if (not p or not clave or exp._vehiculo_de(raiz, carpeta_catalogos, p) != clave or d is doc
                or d.get('reemplazado_por') or d.get('rechazo')):
            continue
        vencimiento = d.get('vencimiento') or ''
        if exp._dias_para_vencer(vencimiento, reloj().date()) is None:
            continue
        revision = d.get('revision_humana') or {}
        cobertura = revision.get('coberturas') if revision.get('sha256') == d.get('sha256') else exp._coberturas_extraidas(d.get('extraccion_automatica') or {})
        anteriores.append({'documento_id': d['documento_id'], 'tipo': d['tipo'], 'vencimiento': vencimiento,
                           'coberturas': cobertura or [], 'origenes': [d['documento_id'], d.get('origen_documento_id'), *d.get('origenes_adicionales', [])], 'fuente': 'FICHA_VEHICULO'})
        vista_anteriores.append({'documento_id': d['documento_id'], 'tipo': d['tipo'], 'fecha_emision': '',
                                 'fecha_vencimiento': vencimiento, 'coberturas': cobertura or [],
                                 'archivo': d.get('archivo', ''), 'registrado_en': d.get('recibido_en', '')})
    virtual = {'documento_id': doc['documento_id'], 'expediente_id': 'revision', 'entidad': exp.VEHICULO,
               'tipo': doc.get('tipo'), 'tipo_informado': doc.get('tipo_informado'), 'estado': exp.ACTIVO,
               'sha256': doc.get('sha256'), 'archivo': doc.get('archivo'), 'pendiente_revision': True,
               'posible_reemplazo': doc.get('posible_reemplazo'), 'extraccion_automatica': _lectura_ficha(doc),
               'fecha_emision': '', 'fecha_vencimiento': '', 'registrado_en': doc.get('recibido_en', '')}
    datos_virtuales = {'expedientes': [{'expediente_id': 'revision', 'referencias': [clave]}]}
    evaluacion = exp._evaluar_revision(raiz, datos_virtuales, virtual, propuesta, reloj().astimezone(timezone.utc).date(), carpeta_catalogos, anteriores)
    # Mientras no haya una operación recuperable entre dos JSON, no se retira
    # un anterior de expediente. Tampoco se programa una transición que no puede
    # materializarse de forma segura por el ciclo de fichas.
    ids_expediente = {a['documento_id'] for a in anteriores if a['fuente'] == 'EXPEDIENTE'}
    if evaluacion['accion'] in ('REEMPLAZAR', 'PROGRAMAR') and ids_expediente.intersection(evaluacion['documentos']):
        evaluacion.update(accion='PENDIENTE', motivo='RENOVACION_ENTRE_ALMACENES')
    elif evaluacion['accion'] == 'PROGRAMAR':
        evaluacion.update(accion='PENDIENTE', motivo='TRANSICION_HUMANA_NO_DISPONIBLE')
    huella = hashlib.sha256(json.dumps({'fichas': fichas, 'expediente': expediente,
                                      'catalogo': hashlib.sha256(catalogo_ruta.read_bytes()).hexdigest(),
                                      'original': doc['sha256'], 'evaluacion': evaluacion},
                                     sort_keys=True, ensure_ascii=True).encode()).hexdigest()[:32]
    return fichas, patente_actual, doc, virtual, evaluacion, vista_anteriores, huella, vehiculo


def revisar(raiz, *, empresa, referencia, documento_id, propuesta, reloj, carpeta_catalogos=None):
    fichas, patente, doc, virtual, evaluacion, anteriores, clave, _ = _contexto(
        raiz, empresa, referencia, documento_id, propuesta, reloj, carpeta_catalogos)
    lectura = exp._lectura(virtual)
    tipos = exp.tipos_documento(exp.leer_expediente(raiz, empresa=empresa))
    from atlas_core.fichas_vehiculos import TIPOS_VEHICULO
    return {'empresa': empresa, 'documento': {**exp._resumen_documento(virtual),
            'tipo_informado': doc.get('tipo_informado') or doc.get('tipo'), 'datos_informados': {}, 'sha256': doc['sha256']},
            'leido': lectura['leido'], 'motivos': lectura['motivos'], 'inicios_observados': lectura['inicios_observados'],
            'editables': [c for c in exp._CAMPOS_REVISION if not lectura['leido'][c]],
            'tipos': [{'tipo': t, 'nombre': tipos[t]['nombre']} for t in TIPOS_VEHICULO], 'anteriores': anteriores,
            'consecuencia': {**{c: evaluacion[c] for c in ('accion', 'motivo', 'campo', 'detalle', 'documentos', 'fecha')}, 'clave': clave},
            'puede_confirmar': evaluacion['accion'] in ('ACTIVAR', 'REEMPLAZAR')}


def resolver(raiz, *, empresa, referencia, documento_id, sha256, decision, autor, confirmacion_humana,
             motivo, propuesta, clave_consecuencia, actor, reloj, carpeta_catalogos=None):
    from atlas_core.extraccion_vencimientos_vehiculos import _escribir
    actor, autor = exp._actor(actor), exp._autor(autor)
    if confirmacion_humana is not True or decision not in ('CONFIRMAR', 'RECHAZAR'):
        raise exp.ErrorExpedienteDigital('Falta una decisión humana válida')
    motivo = exp._motivo(motivo) if decision == 'RECHAZAR' else ''
    ruta = ruta_almacen(raiz, empresa)
    # Los locks fallan inmediatamente si están ocupados: no se espera bajo
    # otro lock. Se mantienen hasta publicar la ficha, para que el expediente
    # y el catálogo usados en la decisión no cambien tras la comprobación.
    with bloqueo_sesion(Path(raiz) / 'operacion' / 'actual', 'fichas_choferes_' + empresa), \
         bloqueo_sesion(exp._carpeta(raiz, carpeta_catalogos), 'catalogo_vehiculos'), \
         bloqueo_sesion(exp.ruta_almacen_expediente(raiz, empresa).parent, 'expediente_documentos'):
        anterior, patente, doc, virtual, evaluacion, _, clave, vehiculo = _contexto(
            raiz, empresa, referencia, documento_id, propuesta, reloj, carpeta_catalogos)
        if doc.get('sha256') != sha256:
            raise exp.ErrorExpedienteDigital('El documento cambió desde la vista previa')
        if decision == 'CONFIRMAR' and (clave != clave_consecuencia or evaluacion['accion'] not in ('ACTIVAR', 'REEMPLAZAR')):
            raise exp.ErrorExpedienteDigital('La consecuencia cambió o queda pendiente por seguridad')
        datos = copy.deepcopy(anterior)
        ubicacion, actual = _buscar(datos, documento_id)
        instante = exp._instante(reloj)
        revision = {'autor': autor, 'actor': actor, 'en': instante, 'sha256': sha256, 'decision': decision,
                    'motivos_revisados': exp._lectura(virtual)['motivos']}
        if decision == 'RECHAZAR':
            actual['estado_revision'] = 'RECHAZADO_EN_REVISION'
            actual['rechazo'] = {**revision, 'motivo': motivo}
        else:
            valores = evaluacion['valores']
            if not vehiculo:
                raise exp.ErrorExpedienteDigital('La patente no corresponde a un vehículo confirmado')
            if not ubicacion:
                datos[PENDIENTES].remove(actual)
                _ficha_vehiculo(datos, vehiculo.patente_canonica)['documentos'].append(actual)
            actual.update(tipo=valores['tipo'], vencimiento=valores['fecha_vencimiento'], estado_revision='CONFIRMADO_HUMANO')
            actual['clasificacion_humana'] = {'patente': vehiculo.patente_canonica, 'autor': autor, 'fecha': instante}
            revision.update(patente=vehiculo.patente_canonica, inicio_vigencia=valores['inicio_vigencia'],
                            coberturas=valores['coberturas'], renovacion=evaluacion['accion'],
                            reemplaza=evaluacion['documentos'])
            for p, previo in _ubicaciones(datos):
                if previo.get('documento_id') in evaluacion['documentos']:
                    previo['reemplazado_por'] = documento_id
            actual.pop('posible_reemplazo', None)
        actual['revision_humana'] = revision
        actual.setdefault('historial', []).append({'accion': 'DOCUMENTO_REVISION_' + decision, 'actor': actor,
                                                   'autor': autor, 'fecha': instante, 'motivo': motivo,
                                                   'documento_id': documento_id, 'sha256': sha256,
                                                   'renovacion': revision.get('renovacion', '')})
        # _escribir usa la misma validación, respaldo y publicación atómica que PULL.
        def comprobar():
            # En el canal Desktop la sesión aporta la misma guarda que protege
            # las demás escrituras, incluidos lease y custodia.
            from atlas_core.desktop_operacion import _sesion_actual
            sesion = _sesion_actual.get()
            if sesion is not None:
                if Path(raiz).resolve() != sesion[0]:
                    raise PermissionError('La raíz no coincide con la sesión de escritura')
                sesion[1]()
            _original(raiz, empresa, doc)
            if decision == 'CONFIRMAR':
                reciente = _contexto(raiz, empresa, referencia, documento_id, propuesta, reloj, carpeta_catalogos)[6]
                if reciente != clave:
                    raise exp.ErrorExpedienteDigital('La consecuencia cambió durante la revisión')
        _escribir(raiz, ruta, empresa, anterior, datos, actor, 'REVISION_DOCUMENTO_MOBILE',
                  {'documento_id': documento_id, 'decision': decision}, comprobar)
        return {'documento_id': documento_id, 'estado': actual['estado_revision'], 'tipo': actual['tipo'],
                'pendiente_revision': False}
