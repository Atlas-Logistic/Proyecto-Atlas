"""Alta de un documento del expediente digital desde Desktop.

Sólo se invoca por el canal operacional (`desktop_operacion.ESCRITORES`), que
ya mantiene la sesión de escritura. La licencia de conducir no entra por aquí:
su fuente única es `registrar_licencia_chofer.py`.
"""
import argparse
import contextlib
import json
import sys

from atlas_core.expediente_digital import empresa_del_proceso, registrar_documento, registrar_documento_vehiculo_desktop
from atlas_core.fichas_choferes import _tipo_archivo_licencia
from atlas_core.fichas_vehiculos import TIPOS_VEHICULO

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
    contenido = origen.read_bytes()
    if args.entidad == 'VEHICULO' and args.tipo.upper() in TIPOS_VEHICULO:
        from atlas_core.ocr_provider import crear_proveedor_ocr
        # El contrato del canal es JSON por stdout; el proveedor puede imprimir diagnósticos.
        with contextlib.redirect_stdout(sys.stderr):
            documento = registrar_documento_vehiculo_desktop(
                args.raiz_atlas, empresa=empresa_del_proceso(), referencia=args.referencia, tipo=args.tipo.upper(),
                contenido=contenido, mime_type=_MIME[extension], fabrica_ocr=crear_proveedor_ocr,
                fecha_emision_informada=args.fecha_emision, fecha_vencimiento_informada=args.fecha_vencimiento)
    else:
        documento = registrar_documento(
            args.raiz_atlas, empresa=empresa_del_proceso(), entidad=args.entidad, referencia=args.referencia, tipo=args.tipo,
            fecha_emision=args.fecha_emision, fecha_vencimiento=args.fecha_vencimiento,
            contenido=contenido, mime_type=_MIME[extension], actor='DESKTOP')
    print(json.dumps(documento, ensure_ascii=True))
