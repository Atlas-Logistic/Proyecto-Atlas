"""Identidad persistente complementaria. No replica ni modifica catálogos.

La empresa viene del proceso backend (MBT en la instalación actual), nunca
de una selección del renderer. Las lecturas no crean archivos ni UUID.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path, PureWindowsPath

from atlas_core.almacenamiento_portable import bloqueo_sesion, escribir_json_atomico
from atlas_core.catalogos import rut_canonico_de_registro_chofer, normalizar_rut

EMPRESA_ACTUAL = 'MBT'
VERSION = 2
MAXIMO_ARCHIVO_LICENCIA = 20 * 1024 * 1024
EXTENSIONES_LICENCIA = frozenset({'.pdf', '.jpg', '.jpeg', '.png'})


def _ahora():
    return datetime.now(timezone.utc).isoformat()


def _fecha_vencimiento_valida(valor):
    texto = str(valor or '').strip()
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', texto):
        raise ValueError('La fecha de vencimiento debe usar AAAA-MM-DD')
    try:
        datetime.strptime(texto, '%Y-%m-%d')
    except ValueError as error:
        raise ValueError('La fecha de vencimiento no es válida') from error
    return texto


def _clase_licencia_valida(valor):
    texto = str(valor or '').strip().upper()
    if not re.fullmatch(r'[A-Z][0-9]{0,2}', texto):
        raise ValueError('La clase de licencia no es válida')
    return texto


def _tipo_archivo_licencia(ruta):
    ruta = Path(ruta)
    if ruta.is_symlink():
        raise ValueError('El archivo seleccionado no puede ser un enlace')
    ruta = ruta.resolve(strict=True)
    if not ruta.is_file():
        raise ValueError('El archivo seleccionado no es un archivo regular')
    extension = ruta.suffix.lower()
    if extension not in EXTENSIONES_LICENCIA:
        raise ValueError('Seleccione un PDF, JPG o PNG válido')
    tamano = ruta.stat().st_size
    if not 0 < tamano <= MAXIMO_ARCHIVO_LICENCIA:
        raise ValueError('El archivo debe tener entre 1 byte y 20 MB')
    cabecera = ruta.read_bytes()[:16]
    firmas = {
        '.pdf': cabecera.startswith(b'%PDF-'),
        '.jpg': cabecera.startswith(b'\xff\xd8\xff'),
        '.jpeg': cabecera.startswith(b'\xff\xd8\xff'),
        '.png': cabecera.startswith(b'\x89PNG\r\n\x1a\n'),
    }
    if not firmas[extension]:
        raise ValueError('El contenido no corresponde al tipo de archivo seleccionado')
    return ruta, extension, tamano


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


def _copiar_licencia_nueva(origen, destino, comprobar):
    """Copia por creación exclusiva y devuelve huella; nunca reutiliza nombre."""
    origen, extension, tamano_esperado = _tipo_archivo_licencia(origen)
    destino.parent.mkdir(parents=True, exist_ok=True)
    temporal = destino.with_name('.' + destino.name + '.tmp-' + uuid.uuid4().hex)
    digest = hashlib.sha256()
    total = 0
    try:
        with origen.open('rb') as entrada, temporal.open('xb') as salida:
            while bloque := entrada.read(1024 * 1024):
                comprobar()
                total += len(bloque)
                if total > MAXIMO_ARCHIVO_LICENCIA:
                    raise ValueError('El archivo supera el máximo permitido')
                digest.update(bloque)
                salida.write(bloque)
        if total != tamano_esperado or origen.stat().st_size != tamano_esperado:
            raise ValueError('El archivo cambió durante la copia; no se registró')
        # Nunca se reemplaza un adjunto: el destino fue generado por UUID y
        # `rename` en Windows falla si alguien ocupó ese nombre entre medio.
        if destino.exists():
            raise FileExistsError('Ya existe un adjunto con ese identificador')
        os.rename(temporal, destino)
    except Exception:
        temporal.unlink(missing_ok=True)
        raise
    return extension, total, digest.hexdigest()


def registrar_licencia_chofer(raiz, *, empresa, ficha_id, referencia_catalogo,
                              vencimiento, clase, archivo_origen, actor='DESKTOP'):
    """Registra una licencia nueva y conserva las anteriores como trazabilidad.

    La identidad se comprueba por UUID *y* referencia actual del catálogo; no
    se toma nombre ni RUT del renderer. Es una escritura documental aislada:
    jamás modifica catálogos, asignaciones ni viajes.
    """
    ficha_id = str(uuid.UUID(str(ficha_id)))
    referencia_catalogo = str(referencia_catalogo or '')
    vencimiento = _fecha_vencimiento_valida(vencimiento)
    clase = _clase_licencia_valida(clase)
    origen, extension, _ = _tipo_archivo_licencia(archivo_origen)
    from atlas_core.desktop_operacion import sesion
    with sesion(raiz) as comprobar:
        ruta = ruta_almacen(raiz, empresa)
        with bloqueo_sesion(Path(raiz) / 'operacion' / 'actual', 'fichas_choferes_' + empresa):
            catalogo_ruta = Path(raiz) / 'catalogos_privados' / 'choferes.json'
            catalogo_bytes = catalogo_ruta.read_bytes()
            catalogo = json.loads(catalogo_bytes.decode('utf-8-sig'))
            if referencia_catalogo not in catalogo:
                raise ValueError('La ficha ya no corresponde a un chofer vigente del catálogo')
            anterior = leer_almacen(raiz, empresa=empresa)
            if not anterior or anterior.get('version') != VERSION:
                raise ValueError('La base de fichas debe inicializarse antes de adjuntar una licencia')
            indice = fichas_por_referencia(anterior)
            ficha = indice.get(referencia_catalogo)
            if not ficha or ficha.get('ficha_id') != ficha_id:
                raise ValueError('La identidad de la ficha cambió; recargue Catálogos antes de adjuntar')
            propuesta = copy.deepcopy(anterior)
            ficha_nueva = fichas_por_referencia(propuesta)[referencia_catalogo]
            documento_id = str(uuid.uuid4())
            instante = _ahora()
            anterior_ids = [d['documento_id'] for d in ficha_nueva['documentos']
                            if d.get('tipo') == 'LICENCIA_CONDUCIR' and not d.get('reemplazado_por')]
            destino_relativo = Path('archivos') / 'choferes' / ficha_id / (documento_id + extension)
            destino = ruta.parent / destino_relativo
            destino.parent.mkdir(parents=True, exist_ok=True)
            if not destino.parent.resolve().is_relative_to(ruta.parent.resolve()):
                raise ValueError('La carpeta de adjuntos apunta fuera de la empresa')
            respaldo = Path(raiz) / 'respaldos' / 'fichas_choferes' / uuid.uuid4().hex
            respaldo.mkdir(parents=True)
            shutil.copy2(ruta, respaldo / ruta.name)
            extension, bytes_archivo, huella = _copiar_licencia_nueva(origen, destino, comprobar)
            documento = {
                'documento_id': documento_id, 'tipo': 'LICENCIA_CONDUCIR', 'clase': clase,
                'vencimiento': vencimiento, 'archivo': destino_relativo.as_posix(),
                'sha256': huella, 'bytes': bytes_archivo, 'creado_en': instante,
            }
            if anterior_ids:
                documento['reemplaza_documentos'] = anterior_ids
                for previo in ficha_nueva['documentos']:
                    if previo.get('documento_id') in anterior_ids:
                        previo['reemplazado_por'] = documento_id
            ficha_nueva['documentos'].append(documento)
            ficha_nueva['historial'].append({
                'accion': 'LICENCIA_REEMPLAZADA' if anterior_ids else 'LICENCIA_REGISTRADA',
                'actor': actor, 'fecha': instante, 'documento_id': documento_id,
                'reemplaza_documentos': anterior_ids, 'sha256': huella,
            })
            propuesta['revision'] = int(anterior['revision']) + 1
            _validar_v2(propuesta)
            escribir_json_atomico(respaldo / 'manifest.json', {
                'empresa': empresa, 'actor': actor, 'operacion': ficha_nueva['historial'][-1]['accion'],
                'ficha_id': ficha_id, 'documento_id': documento_id,
                'sha256': huella, 'bytes': bytes_archivo, 'revision_anterior': anterior['revision'],
                'ruta_relativa': str(ruta.relative_to(raiz)),
            })
            comprobar()
            if catalogo_ruta.read_bytes() != catalogo_bytes:
                destino.unlink(missing_ok=True)
                raise ValueError('El catálogo cambió durante la carga; no se publicó la licencia')
            try:
                escribir_json_atomico(ruta, propuesta)
            except Exception:
                destino.unlink(missing_ok=True)
                raise
            return {'ok': True, 'documento_id': documento_id, 'ficha_id': ficha_id,
                    'vencimiento': vencimiento, 'reemplazados': len(anterior_ids),
                    'revision': propuesta['revision'], 'sha256': huella,
                    'respaldo': str(respaldo)}


ESTADO_PENDIENTE_EXTRACCION = 'PENDIENTE_EXTRACCION'
_EXTENSION_POR_MIME = {'application/pdf': '.pdf', 'image/jpeg': '.jpg', 'image/png': '.png'}
_FIRMA_POR_EXTENSION = {'.pdf': b'%PDF-', '.jpg': b'\xff\xd8\xff', '.png': b'\x89PNG\r\n\x1a\n'}


def registrar_licencia_mobile_pendiente(raiz, *, empresa, referencia_catalogo, contenido, mime_type,
                                        sha256, origen_documento_id, recibido_en, comprobar,
                                        actor='MOBILE'):
    """Guarda en la ficha el original de una licencia enviada desde Mobile.

    Queda PENDIENTE_EXTRACCION: sin clase ni vencimiento, nunca vigente y sin
    reemplazar las licencias anteriores. La ficha se resuelve sólo por la
    referencia de catálogo (el `chofer_id` del token Mobile). Lo invoca el
    PULL bajo su propio lease: `comprobar` lanza si se perdió. Idempotente
    por `origen_documento_id` (el documento Cloud).
    """
    referencia_catalogo = str(referencia_catalogo or '')
    origen_documento_id = str(origen_documento_id or '')
    if not referencia_catalogo or not origen_documento_id:
        raise ValueError('Documento Mobile sin chofer o sin identificador')
    extension = _EXTENSION_POR_MIME.get(mime_type)
    if not extension or not contenido.startswith(_FIRMA_POR_EXTENSION[extension]):
        raise ValueError('El contenido no corresponde a un PDF, JPG o PNG')
    if not 0 < len(contenido) <= MAXIMO_ARCHIVO_LICENCIA:
        raise ValueError('El archivo debe tener entre 1 byte y 20 MB')
    huella = hashlib.sha256(contenido).hexdigest()
    if huella != str(sha256 or '').lower():
        raise ValueError('La huella del archivo recibido no coincide')
    comprobar()
    ruta = ruta_almacen(raiz, empresa)
    with bloqueo_sesion(Path(raiz) / 'operacion' / 'actual', 'fichas_choferes_' + empresa):
        catalogo_ruta = Path(raiz) / 'catalogos_privados' / 'choferes.json'
        catalogo_bytes = catalogo_ruta.read_bytes()
        if referencia_catalogo not in json.loads(catalogo_bytes.decode('utf-8-sig')):
            raise ValueError('El chofer de la sesión Mobile no es un chofer vigente del catálogo')
        anterior = leer_almacen(raiz, empresa=empresa)
        if not anterior or anterior.get('version') != VERSION:
            raise ValueError('La base de fichas debe inicializarse antes de recibir una licencia')
        for ficha in anterior['choferes']:
            for doc in ficha['documentos']:
                if doc.get('origen_documento_id') == origen_documento_id:
                    return {'ok': True, 'idempotente': True, 'documento_id': doc['documento_id'],
                            'ficha_id': ficha['ficha_id'], 'sha256': doc.get('sha256')}
        if referencia_catalogo not in fichas_por_referencia(anterior):
            raise ValueError('El chofer de la sesión Mobile no tiene ficha digital')
        propuesta = copy.deepcopy(anterior)
        ficha_nueva = fichas_por_referencia(propuesta)[referencia_catalogo]
        ficha_id = ficha_nueva['ficha_id']
        documento_id = str(uuid.uuid4())
        instante = _ahora()
        destino_relativo = Path('archivos') / 'choferes' / ficha_id / (documento_id + extension)
        destino = ruta.parent / destino_relativo
        destino.parent.mkdir(parents=True, exist_ok=True)
        if not destino.parent.resolve().is_relative_to(ruta.parent.resolve()):
            raise ValueError('La carpeta de adjuntos apunta fuera de la empresa')
        respaldo = Path(raiz) / 'respaldos' / 'fichas_choferes' / uuid.uuid4().hex
        respaldo.mkdir(parents=True)
        shutil.copy2(ruta, respaldo / ruta.name)
        temporal = destino.with_name('.' + destino.name + '.tmp-' + uuid.uuid4().hex)
        try:
            with temporal.open('xb') as salida:
                salida.write(contenido)
            if destino.exists():
                raise FileExistsError('Ya existe un adjunto con ese identificador')
            os.rename(temporal, destino)
        except Exception:
            temporal.unlink(missing_ok=True)
            raise
        documento = {
            'documento_id': documento_id, 'tipo': 'LICENCIA_CONDUCIR',
            'estado_revision': ESTADO_PENDIENTE_EXTRACCION, 'origen': 'MOBILE',
            'origen_documento_id': origen_documento_id, 'archivo': destino_relativo.as_posix(),
            'sha256': huella, 'bytes': len(contenido), 'creado_en': instante,
            'recibido_en': str(recibido_en or instante),
        }
        ficha_nueva['documentos'].append(documento)
        ficha_nueva['historial'].append({
            'accion': 'LICENCIA_RECIBIDA_MOBILE', 'actor': actor, 'fecha': instante,
            'documento_id': documento_id, 'origen_documento_id': origen_documento_id, 'sha256': huella,
        })
        propuesta['revision'] = int(anterior['revision']) + 1
        _validar_v2(propuesta)
        escribir_json_atomico(respaldo / 'manifest.json', {
            'empresa': empresa, 'actor': actor, 'operacion': 'LICENCIA_RECIBIDA_MOBILE',
            'ficha_id': ficha_id, 'documento_id': documento_id, 'origen_documento_id': origen_documento_id,
            'sha256': huella, 'bytes': len(contenido), 'revision_anterior': anterior['revision'],
            'ruta_relativa': str(ruta.relative_to(raiz)),
        })
        comprobar()
        if catalogo_ruta.read_bytes() != catalogo_bytes:
            destino.unlink(missing_ok=True)
            raise ValueError('El catálogo cambió durante la recepción; no se publicó la licencia')
        try:
            escribir_json_atomico(ruta, propuesta)
        except Exception:
            destino.unlink(missing_ok=True)
            raise
        return {'ok': True, 'idempotente': False, 'documento_id': documento_id, 'ficha_id': ficha_id,
                'revision': propuesta['revision'], 'sha256': huella, 'respaldo': str(respaldo)}
