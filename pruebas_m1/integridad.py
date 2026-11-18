"""Oráculo sintético de integridad. No realiza restauraciones ni usa red."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


class Bloqueado(ValueError):
    pass


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def validar(snapshot: dict, esperado: dict) -> None:
    """Verifica contra un oráculo externo; falla cerrado ante evidencia incompleta."""
    if not isinstance(snapshot, dict) or not isinstance(esperado, dict):
        raise Bloqueado('FORMATO_INVALIDO')
    for key in ('empresa', 'generacion', 'archivos', 'documentos', 'decisiones', 'reporte'):
        if key not in snapshot or key not in esperado:
            raise Bloqueado('EVIDENCIA_INCOMPLETA:' + key)
    if snapshot['empresa'] != esperado['empresa'] or snapshot['generacion'] != esperado['generacion']:
        raise Bloqueado('GENERACION_O_EMPRESA_INCORRECTA')
    archivos = snapshot['archivos']
    for ruta, hash_esperado in esperado['archivos'].items():
        contenido = archivos.get(ruta)
        if not isinstance(contenido, bytes) or digest(contenido) != hash_esperado:
            raise Bloqueado('ARCHIVO_AUSENTE_O_ALTERADO:' + ruta)
    if set(archivos) != set(esperado['archivos']):
        raise Bloqueado('INVENTARIO_DISTINTO')
    if snapshot['documentos'] != esperado['documentos']:
        raise Bloqueado('DOCUMENTOS_DISTINTOS')
    if snapshot['reporte'] != esperado['reporte'] or snapshot['reporte'] not in archivos:
        raise Bloqueado('REPORTE_NO_VERIFICADO')
    decisiones = snapshot['decisiones']
    if not isinstance(decisiones, list):
        raise Bloqueado('DECISIONES_INVALIDAS')
    ids = [x.get('id') for x in decisiones]
    if len(ids) != len(set(ids)) or set(ids) != set(esperado['decisiones']):
        raise Bloqueado('DECISIONES_PERDIDAS_O_DUPLICADAS')
    for d in decisiones:
        if d != esperado['decisiones'][d['id']]:
            raise Bloqueado('AUTORIA_O_DECISION_ALTERADA:' + str(d['id']))
        if d['tipo'] == 'HUMANA' and not d.get('confirmante'):
            raise Bloqueado('CONFIRMACION_SIN_EVIDENCIA')
        if d['tipo'] != 'HUMANA' and d.get('confirmante'):
            raise Bloqueado('CONFIRMACION_FABRICADA')


def envios_posteriores(backup: list[dict], cloud: list[dict]) -> list[dict]:
    """Sólo identifica diferencias; no escribe ni reingresa envíos."""
    campos = ('empresa', 'envio', 'documento', 'sha256')
    def clave(item):
        if any(not item.get(k) for k in campos):
            raise Bloqueado('ENVIO_SIN_IDENTIDAD')
        return tuple(item[k] for k in campos)
    claves = [clave(x) for x in backup]
    if len(claves) != len(set(claves)):
        raise Bloqueado('ENVIO_DUPLICADO')
    ids = {}
    for item in backup + cloud:
        k = clave(item)
        ident = k[:2]
        if ident in ids and ids[ident] != k:
            raise Bloqueado('ENVIO_CONFLICTIVO')
        ids[ident] = k
    return [dict(x, recuperacion='PENDIENTE') for x in cloud
            if x.get('estado') == 'COMPLETADO' and clave(x) not in claves]


def cargar_json_seguro(root: Path, rel: str):
    """Lee solamente bajo el recinto dado; rechaza rutas y enlaces externos."""
    root = root.resolve(strict=True)
    ruta = (root / rel).resolve(strict=True)
    if not ruta.is_relative_to(root) or ruta == root:
        raise Bloqueado('RUTA_FUERA_DEL_RECINTO')
    return json.loads(ruta.read_text(encoding='utf-8'))


def restaurar_sintetico(root: Path, snapshot: dict, esperado: dict) -> None:
    """Copia bytes ficticios sólo después de validar todo; exige destino vacío."""
    validar(snapshot, esperado)
    root = Path(root).resolve(strict=True)
    if not root.name.startswith('m1-sintetico-') or any(root.iterdir()):
        raise Bloqueado('DESTINO_NO_ES_RECINTO_VACIO')
    for rel in snapshot['archivos']:
        path = Path(rel)
        if path.is_absolute() or '..' in path.parts or not path.parts:
            raise Bloqueado('RUTA_INVALIDA')
        if not (root / path).resolve().is_relative_to(root):
            raise Bloqueado('RUTA_FUERA_DEL_RECINTO')
    for rel, contenido in snapshot['archivos'].items():
        destino = root / rel
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_bytes(contenido)
