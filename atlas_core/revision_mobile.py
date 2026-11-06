from __future__ import annotations
import hashlib, json, re
from datetime import datetime, timezone
from pathlib import Path
from atlas_core.almacenamiento_portable import bloqueo_sesion, escribir_json_atomico

ID = re.compile(r'^[A-Za-z0-9_-]{1,100}$')
SHA = re.compile(r'^[0-9a-f]{64}$')

def registrar(raiz, envio_id, sha256, accion, supervisor):
    if not ID.fullmatch(envio_id) or not SHA.fullmatch(sha256): raise ValueError('Identidad inválida')
    supervisor = supervisor.strip()
    if not supervisor or len(supervisor) > 100: raise ValueError('Indique el supervisor')
    if accion not in ('DESCARTAR', 'REVERTIR'): raise ValueError('Acción inválida')
    raiz = Path(raiz)
    carpeta = raiz / 'operacion' / 'mobile' / 'envios' / envio_id
    with bloqueo_sesion(raiz / 'operacion' / 'mobile' / 'envios', 'mobile_' + envio_id, tiempo_expiracion_segundos=300):
        envio = json.loads((carpeta / 'envio.json').read_text(encoding='utf-8'))
        nombre = envio.get('foto_original', '')
        if not nombre or Path(nombre).name != nombre: raise ValueError('Referencia de imagen inválida')
        actual = hashlib.sha256((carpeta / nombre).read_bytes()).hexdigest()
        if envio.get('envio_id') != envio_id or envio.get('imagen_sha256') != sha256 or actual != sha256: raise ValueError('La identidad de la imagen no coincide')
        ruta = raiz / 'operacion' / 'actual' / 'revision_mobile' / (envio_id + '.json')
        if ruta.exists():
            registro = json.loads(ruta.read_text(encoding='utf-8'))
            if registro.get('version') != 1 or registro.get('envio_id') != envio_id or registro.get('imagen_sha256') != sha256 or not isinstance(registro.get('eventos'), list) or not registro['eventos']: raise ValueError('Auditoría incompatible')
            anterior = registro['eventos'][-1].get('accion')
            if anterior not in ('DESCARTAR', 'REVERTIR'): raise ValueError('Auditoría incompatible')
        else:
            registro = {'version': 1, 'envio_id': envio_id, 'imagen_sha256': sha256, 'eventos': []}
            anterior = None
        if accion == 'DESCARTAR' and (anterior == 'DESCARTAR' or envio.get('estado') != 'REQUIERE_REVISION'): raise ValueError('El envío no está disponible para descarte')
        if accion == 'REVERTIR' and anterior != 'DESCARTAR': raise ValueError('No hay descarte activo')
        registro['eventos'].append({'accion': accion, 'supervisor': supervisor, 'fecha_utc': datetime.now(timezone.utc).isoformat(), 'motivo': 'No corresponde a una guía' if accion == 'DESCARTAR' else 'Reversión del descarte'})
        escribir_json_atomico(ruta, registro)
    return {'ok': True, 'envio_id': envio_id, 'accion': accion}
