"""Identidad persistente complementaria. No replica ni modifica catálogos.

La empresa viene del proceso backend (MBT en la instalación actual), nunca
de una selección del renderer. Las lecturas no crean archivos ni UUID.
"""
from __future__ import annotations

import copy
import json
import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path, PureWindowsPath

from atlas_core.almacenamiento_portable import bloqueo_sesion, escribir_json_atomico
from atlas_core.catalogos import rut_canonico_de_registro_chofer, normalizar_rut

EMPRESA_ACTUAL = 'MBT'
VERSION = 2


def ruta_almacen(raiz, empresa):
    if not re.fullmatch(r'[A-Z0-9][A-Z0-9_-]{1,31}', str(empresa)):
        raise ValueError('Empresa inválida')
    base = Path(raiz) / 'fichas_digitales'
    ruta = base / empresa / 'fichas_documentales.json'
    if not ruta.resolve().is_relative_to(base.resolve() / empresa):
        raise ValueError('Almacén fuera de la empresa')
    return ruta


def _validar_v2(datos):
    if not isinstance(datos.get('choferes'), list) or not isinstance(datos.get('revision'), int) or datos['revision'] < 1:
        raise ValueError('Esquema de fichas inválido')
    ids, referencias, documentos = set(), set(), set()
    for ficha in datos['choferes']:
        ident = str(uuid.UUID(ficha['ficha_id']))
        refs = ficha.get('referencias_catalogo')
        if ident in ids or not isinstance(refs, list) or not refs or any(not isinstance(r, str) or not r for r in refs):
            raise ValueError('Identidad de ficha inválida o duplicada')
        if len(set(refs)) != len(refs) or referencias.intersection(refs):
            raise ValueError('Una referencia de catálogo identifica dos fichas')
        if {'nombre', 'rut', 'activo', 'aliases'} & set(ficha):
            raise ValueError('La identidad pertenece exclusivamente al catálogo')
        if not isinstance(ficha.get('complementarios'), dict) or not isinstance(ficha.get('documentos'), list) or not isinstance(ficha.get('historial'), list):
            raise ValueError('Datos complementarios inválidos')
        for doc in ficha['documentos']:
            if not isinstance(doc, dict) or not doc.get('documento_id') or not doc.get('tipo'):
                raise ValueError('Metadatos documentales inválidos')
            if doc['documento_id'] in documentos:
                raise ValueError('Identificador de documento duplicado')
            documentos.add(doc['documento_id'])
            archivo = doc.get('archivo')
            if archivo:
                p = PureWindowsPath(archivo)
                if p.is_absolute() or p.drive or '..' in p.parts or not p.parts or p.parts[0] != 'archivos':
                    raise ValueError('Adjunto fuera de la empresa')
        ids.add(ident); referencias.update(refs)


def leer_almacen(raiz, *, empresa):
    ruta = ruta_almacen(raiz, empresa)
    try:
        datos = json.loads(ruta.read_text(encoding='utf-8-sig'))
    except FileNotFoundError:
        return None
    if not isinstance(datos, dict) or datos.get('empresa') != empresa or datos.get('version') not in (1, VERSION):
        raise ValueError('Empresa o versión del almacén incompatible')
    if datos['version'] == VERSION:
        _validar_v2(datos)
    return datos


def fichas_por_referencia(datos):
    if not datos or datos['version'] != VERSION:
        return {}
    return {ref: f for f in datos['choferes'] for ref in f['referencias_catalogo']}


def asignaciones_de_chofer(rut, vehiculos):
    """Misma regla vigente del Motor; no infiere relaciones desde los viajes."""
    from atlas_core.decisiones_pendientes import _asignaciones_vigentes
    from types import SimpleNamespace
    confirmados = [SimpleNamespace(
        patente_canonica=v.patente_canonica, tipo=v.tipo,
        estado_calidad=v.estado_calidad, estado_vigencia=v.estado_vigencia,
        evidencias=tuple(e for e in v.evidencias if e.resultado == 'SOPORTA'),
    ) for v in vehiculos]
    vigentes = _asignaciones_vigentes(confirmados)
    resultado = {}
    for rol, tipo in (('tracto', 'TRACTO'), ('rampla', 'CARRO')):
        patentes = sorted(p for p, (r, t) in vigentes.items()
                          if rut and r == normalizar_rut(rut) and t == tipo)
        resultado[rol] = {'estado': 'CONFIRMADO' if len(patentes) == 1 else 'CONFLICTO' if patentes else 'SIN_ASIGNACION',
                          'patente': patentes[0] if len(patentes) == 1 else None, 'candidatos': patentes}
    return resultado


def preparar_almacen(datos, catalogo, *, empresa, vinculos=None, actor='OPERADOR', ahora=None):
    """Plan puro. Un cambio de clave exige vínculo explícito; jamás por nombre.

    Si desaparecen claves y aparecen otras, se abstiene hasta que se indique
    su correspondencia. Renombrar la persona o corregir su RUT en el mismo
    registro no cambia ficha_id. No elimina fichas ni documentos históricos.
    """
    instante = ahora or datetime.now(timezone.utc).isoformat()
    original = copy.deepcopy(datos)
    if datos is not None and datos.get('empresa') != empresa:
        raise ValueError('No se puede migrar otra empresa')
    nuevo = copy.deepcopy(datos) if datos else {
        'version': VERSION, 'empresa': empresa, 'revision': 1,
        'plazos_alerta_dias': {}, 'choferes': [], 'vehiculos': [],
    }
    if nuevo.get('version') not in (1, VERSION):
        raise ValueError('Versión desconocida; no se modifica')
    legado = nuevo['version'] == 1
    pendientes_legacy = nuevo.get('choferes', []) if legado else []
    if legado:
        nuevo.update(version=VERSION, revision=1, choferes=[])
    else:
        _validar_v2(nuevo)
    indice = fichas_por_referencia(nuevo)
    for anterior, actual in (vinculos or {}).items():
        if anterior not in indice or actual not in catalogo:
            raise ValueError('Vínculo de catálogo inexistente')
        ficha = indice[anterior]
        if actual in indice and indice[actual]['ficha_id'] != ficha['ficha_id']:
            raise ValueError('El nuevo identificador ya pertenece a otra ficha')
        if anterior != actual and anterior in catalogo:
            raise ValueError('La clave anterior todavía identifica a otro registro del catálogo')
        if actual not in ficha['referencias_catalogo']:
            ficha['referencias_catalogo'].append(actual)
            ficha['historial'].append({'accion': 'VINCULAR_REFERENCIA', 'actor': actor, 'fecha': instante,
                                       'anterior': anterior, 'actual': actual})
            indice[actual] = ficha
    nuevas = set(catalogo) - set(indice)
    huerfanas = [f for f in nuevo['choferes'] if not set(f['referencias_catalogo']) & set(catalogo)]
    if nuevas and huerfanas:
        raise ValueError('Hay claves retiradas y nuevas: indique el vínculo explícito antes de continuar')
    for referencia in sorted(nuevas):
        ficha = {'ficha_id': str(uuid.uuid4()), 'referencias_catalogo': [referencia],
                 'complementarios': {'contacto': {'telefono': '', 'correo': ''},
                                     'personales': {'domicilio': '', 'fecha_nacimiento': None}},
                 'documentos': [], 'historial': [{'accion': 'FICHA_CREADA', 'actor': actor, 'fecha': instante}]}
        nuevo['choferes'].append(ficha); indice[referencia] = ficha
    if legado:
        sin_vincular = []
        for entrada in pendientes_legacy:
            rut = normalizar_rut(str(entrada.get('rut', '')))
            referencias = [k for k, v in catalogo.items()
                           if rut and normalizar_rut(rut_canonico_de_registro_chofer(k, v) or '') == rut]
            if len(referencias) != 1:
                sin_vincular.append(entrada); continue
            ficha = indice[referencias[0]]
            for documento in entrada.get('documentos', []):
                doc = copy.deepcopy(documento)
                doc.setdefault('documento_id', str(uuid.uuid4()))
                ficha['documentos'].append(doc)
        if sin_vincular:
            nuevo['choferes_legacy_sin_vincular'] = sin_vincular
    if original != nuevo:
        nuevo['revision'] = 1 if original is None else int(original.get('revision', 0)) + 1
    _validar_v2(nuevo)
    return nuevo


def inicializar_almacen(raiz, *, empresa, actor, vinculos=None):
    """Mantenimiento explícito bajo sesión oficial; nunca durante una consulta."""
    from atlas_core.desktop_operacion import sesion
    with sesion(raiz) as comprobar:
        ruta = ruta_almacen(raiz, empresa)
        with bloqueo_sesion(Path(raiz) / 'operacion' / 'actual', 'fichas_choferes_' + empresa):
            catalogo_ruta = Path(raiz) / 'catalogos_privados' / 'choferes.json'
            catalogo_bytes = catalogo_ruta.read_bytes()
            catalogo = json.loads(catalogo_bytes.decode('utf-8-sig'))
            anterior = leer_almacen(raiz, empresa=empresa)
            propuesto = preparar_almacen(anterior, catalogo, empresa=empresa, actor=actor, vinculos=vinculos)
            if anterior == propuesto:
                return {'modificado': False, 'fichas': len(propuesto['choferes']), 'revision': propuesto['revision']}
            respaldo = Path(raiz) / 'respaldos' / 'fichas_choferes' / uuid.uuid4().hex
            respaldo.mkdir(parents=True)
            if ruta.is_file():
                shutil.copy2(ruta, respaldo / ruta.name)
            escribir_json_atomico(respaldo / 'manifest.json', {
                'empresa': empresa, 'actor': actor, 'operacion': 'INICIALIZAR_BASE',
                'existia_almacen': anterior is not None, 'ruta_relativa': str(ruta.relative_to(raiz)),
                'revision_anterior': anterior.get('revision') if anterior else None,
            })
            comprobar()
            if catalogo_ruta.read_bytes() != catalogo_bytes:
                raise ValueError('El catálogo cambió durante la preparación; no se publica')
            escribir_json_atomico(ruta, propuesto)
            return {'modificado': True, 'fichas': len(propuesto['choferes']),
                    'revision': propuesto['revision'], 'respaldo': str(respaldo)}
