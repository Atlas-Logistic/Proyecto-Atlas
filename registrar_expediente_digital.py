"""Alta de un documento del expediente digital desde Desktop.

Sólo se invoca por el canal operacional (`desktop_operacion.ESCRITORES`), que
ya mantiene la sesión de escritura. La licencia de conducir no entra por aquí:
su fuente única es `registrar_licencia_chofer.py`.
"""
import argparse
import json

from atlas_core.expediente_digital import empresa_del_proceso, registrar_documento
from atlas_core.fichas_choferes import _tipo_archivo_licencia

_MIME = {'.pdf': 'application/pdf', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--raiz-atlas', required=True)
    parser.add_argument('--entidad', required=True, choices=('CHOFER', 'VEHICULO'))
    parser.add_argument('--referencia', required=True)
    parser.add_argument('--tipo', required=True)
    parser.add_argument('--fecha-emision', default='')
    parser.add_argument('--fecha-vencimiento', default='')
    parser.add_argument('--archivo', required=True)
    args = parser.parse_args()
    if args.tipo.upper() == 'LICENCIA_CONDUCIR':
        raise ValueError('La licencia de conducir se adjunta desde la sección Documentos de la ficha.')
    origen, extension, _ = _tipo_archivo_licencia(args.archivo)
    print(json.dumps(registrar_documento(
        args.raiz_atlas, empresa=empresa_del_proceso(), entidad=args.entidad, referencia=args.referencia, tipo=args.tipo,
        fecha_emision=args.fecha_emision, fecha_vencimiento=args.fecha_vencimiento,
        contenido=origen.read_bytes(), mime_type=_MIME[extension], actor='DESKTOP',
    ), ensure_ascii=True))
