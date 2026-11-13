"""Resolución humana de un documento vehicular pendiente del expediente, desde Desktop.

Sólo se invoca por el canal operacional (`desktop_operacion.ESCRITORES`). Confirmar
exige la huella de la consecuencia mostrada en la vista previa; la decisión la toma
`renovacion_documental` dentro de `expediente_digital.resolver_documento_pendiente`.
"""
import argparse
import json

from atlas_core.expediente_digital import ErrorExpedienteDigital, empresa_del_proceso, resolver_documento_pendiente


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--raiz-atlas', required=True)
    parser.add_argument('--referencia', required=True)
    parser.add_argument('--documento-id', required=True)
    parser.add_argument('--sha256', required=True)
    parser.add_argument('--decision', required=True, choices=('CONFIRMAR', 'RECHAZAR'))
    # Con nombre (--autor) o, desde Desktop, explícitamente sin nombre (--revisor-no-declarado); nunca ambos.
    parser.add_argument('--autor', default='')
    parser.add_argument('--revisor-no-declarado', action='store_true',
                        help='Desktop acepta o rechaza sin nombre: queda persona no declarada, canal y equipo')
    parser.add_argument('--confirmo-original', action='store_true',
                        help='Los datos completados a mano (tipo, patente, inicio, reemplazado) aparecen en el original')
    parser.add_argument('--motivo', default='')
    parser.add_argument('--propuesta', default='{}')
    parser.add_argument('--clave-consecuencia', default='')
    parser.add_argument('--confirmo-revision-humana', action='store_true',
                        help='Obligatorio: una persona revisó el original y decide')
    args = parser.parse_args()
    try:
        propuesta = json.loads(args.propuesta)
    except ValueError as error:
        raise ErrorExpedienteDigital('propuesta de revisión ilegible') from error
    if not isinstance(propuesta, dict):
        raise ErrorExpedienteDigital('propuesta de revisión ilegible')
    documento = resolver_documento_pendiente(
        args.raiz_atlas, empresa=empresa_del_proceso(), referencia=args.referencia, documento_id=args.documento_id,
        sha256=args.sha256, decision=args.decision, autor=args.autor, motivo=args.motivo, propuesta=propuesta,
        clave_consecuencia=args.clave_consecuencia, confirmacion_humana=args.confirmo_revision_humana, actor='DESKTOP',
        revisor_no_declarado=args.revisor_no_declarado, confirmo_original=args.confirmo_original)
    print(json.dumps({k: documento[k] for k in ('documento_id', 'estado', 'tipo', 'pendiente_revision')}, ensure_ascii=True))
