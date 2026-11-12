"""Corrección manual de fechas de emisión y vencimiento de un documento de ficha, desde Desktop.

Sólo se invoca por el canal operacional (`desktop_operacion.ESCRITORES`), que
mantiene la sesión de escritura. Exige la clave de la vista previa
(`construir_fichas_catalogos.py --expediente-fechas-documento`) y la
confirmación explícita de la persona que revisó el original.
"""
import argparse
import json

from atlas_core.correccion_fechas_documentales import corregir_fechas_documento
from atlas_core.expediente_digital import empresa_del_proceso


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--raiz-atlas', required=True)
    parser.add_argument('--entidad', required=True, choices=('CHOFER', 'VEHICULO'))
    parser.add_argument('--referencia', required=True)
    parser.add_argument('--documento-id', required=True)
    parser.add_argument('--sha256', default='')
    parser.add_argument('--propuesta', required=True, help='JSON con fecha_emision y/o fecha_vencimiento (AAAA-MM-DD)')
    parser.add_argument('--autor', required=True)
    parser.add_argument('--motivo', default='')
    parser.add_argument('--clave', required=True)
    parser.add_argument('--confirmo-revision-humana', action='store_true',
                        help='Obligatorio: la persona revisó el original y confirma estas fechas')
    args = parser.parse_args()
    print(json.dumps(corregir_fechas_documento(
        args.raiz_atlas, empresa=empresa_del_proceso(), entidad=args.entidad, referencia=args.referencia,
        documento_id=args.documento_id, sha256=args.sha256, propuesta=json.loads(args.propuesta), autor=args.autor,
        motivo=args.motivo, clave=args.clave, confirmacion_humana=args.confirmo_revision_humana, actor='DESKTOP',
    ), ensure_ascii=True))
