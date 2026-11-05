"""Recover one documented Mobile row under an already acquired custody lease."""
from __future__ import annotations
import csv
import hashlib
import json
from pathlib import Path
from datetime import datetime, timezone
from atlas_core.almacenamiento_portable import bloqueo_sesion, escribir_json_atomico
from atlas_core.mobile import NOMBRE_LOCK_DATASET_OPERACIONAL
from atlas_core.procesamiento_masivo import COLUMNAS
from atlas_core.revalidacion_documental import _escribir_filas_completas
from atlas_core.estado_confirmado import _activas, sha256_archivo


def _filas(path):
    csv.field_size_limit(max(csv.field_size_limit(), 100_000_000))
    with path.open(encoding='utf-8-sig', newline='') as f:
        reader = csv.DictReader(f, delimiter=';', strict=True)
        rows = list(reader)
        if reader.fieldnames != COLUMNAS or any(None in r or any(v is None for v in r.values()) for r in rows):
            raise ValueError('Dataset incompatible o incompleto')
        return rows


def recuperar_fila(*, raiz, origen, envio_id, guia, transporte, lease):
    raiz, origen = Path(raiz), Path(origen)
    if not lease.vigente or lease.custodia not in _activas or lease.custodia.raiz != raiz.resolve():
        raise ValueError('Lease y custodia activos requeridos')
    dataset = raiz / 'operacion/actual/analisis_completo_guias.csv'
    base = raiz / 'operacion/mobile/envios' / envio_id
    registro = json.loads((base / 'envio.json').read_text(encoding='utf-8'))
    identidad = f'mobile/{envio_id}/original.jpg'
    if registro.get('envio_id') != envio_id or registro.get('foto_original') != 'original.jpg':
        raise ValueError('Identidad Mobile inconsistente')
    if sha256_archivo(base / 'original.jpg') != registro.get('imagen_sha256'):
        raise ValueError('Original no coincide con hash Mobile')
    fuente = [r for r in _filas(origen) if r.get('archivo') == identidad]
    if len(fuente) != 1 or fuente[0].get('numero_guia') != guia or fuente[0].get('numero_transporte') != transporte:
        raise ValueError('Fila fuente no inequívoca')
    ocr = registro.get('datos_ocr') or {}
    if ocr.get('numero_guia') != guia or ocr.get('numero_transporte') != transporte:
        raise ValueError('OCR no coincide con fila fuente')
    fila = fuente[0]
    audit = raiz / 'operacion/actual/recuperaciones' / f'{envio_id}.json'
    with bloqueo_sesion(dataset.parent, NOMBRE_LOCK_DATASET_OPERACIONAL):
        if not lease.vigente:
            raise ValueError('Lease perdido')
        filas = _filas(dataset)
        encontradas = [r for r in filas if r['archivo'] == identidad]
        otros = [r for r in filas if r['numero_guia'] == guia or r['numero_transporte'] == transporte]
        if encontradas:
            if len(encontradas) != 1 or encontradas[0] != fila or len(otros) != 1:
                raise ValueError('Fila existente incompatible')
            if not audit.is_file():
                raise ValueError('Fila presente sin auditoria de recuperacion')
            evidencia = json.loads(audit.read_text(encoding='utf-8'))
            if (evidencia.get('envio_id') != envio_id or evidencia.get('fuente_sha256') != sha256_archivo(origen)
                    or evidencia.get('guia') != guia or evidencia.get('transporte') != transporte):
                raise ValueError('Auditoria incompatible')
            if evidencia.get('estado') == 'PREPARADA':
                evidencia.update(estado='INSERTADA', dataset_despues_sha256=sha256_archivo(dataset))
                escribir_json_atomico(audit, evidencia)
            elif evidencia.get('estado') != 'INSERTADA':
                raise ValueError('Auditoria en estado desconocido')
            return {'estado': 'YA_PRESENTE'}
        if otros:
            raise ValueError('Guia o transporte ya presente; no se inserta')
        antes = sha256_archivo(dataset)
        evidencia = {'estado': 'PREPARADA', 'envio_id': envio_id, 'guia': guia, 'transporte': transporte,
                     'fuente_sha256': sha256_archivo(origen), 'original_sha256': registro['imagen_sha256'],
                     'dataset_antes_sha256': antes, 'fecha_utc': datetime.now(timezone.utc).isoformat()}
        escribir_json_atomico(audit, evidencia)
        if not lease.vigente:
            raise ValueError('Lease perdido antes de escribir')
        _escribir_filas_completas(dataset, filas + [fila])
        evidencia.update(estado='INSERTADA', dataset_despues_sha256=sha256_archivo(dataset))
        escribir_json_atomico(audit, evidencia)
        return evidencia
