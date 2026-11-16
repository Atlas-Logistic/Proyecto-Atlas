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
    parser.add_argument('--decision', required=True, choices=('CONFIRMAR', 'RECHAZAR', 'DESCARTAR'))
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
    if args.decision == 'DESCARTAR':
        from pathlib import Path
        from atlas_core.desktop_operacion import _sesion_actual
        from atlas_core.descarte_documento_mobile import decidir
        sesion = _sesion_actual.get()
        if not sesion or Path(args.raiz_atlas).resolve() != sesion[0]:
            raise PermissionError('Se requiere la sesión de escritura de Desktop')
        if args.referencia != 'SIN_CLASIFICAR' or propuesta:
            raise ErrorExpedienteDigital('Sólo se descartan documentos sin clasificar')
        documento = decidir(args.raiz_atlas, empresa=empresa_del_proceso(), documento_id=args.documento_id,
            sha256=args.sha256, decision='DESCARTAR', autor=args.autor, actor='DESKTOP',
            confirmacion_humana=args.confirmo_revision_humana, comprobar=sesion[1], motivo=args.motivo,
            revisor_no_declarado=args.revisor_no_declarado)
        print(json.dumps({'ok': True, 'estado': documento['estado']}, ensure_ascii=True))
        raise SystemExit(0)
    documento = resolver_documento_pendiente(
        args.raiz_atlas, empresa=empresa_del_proceso(), referencia=args.referencia, documento_id=args.documento_id,
        sha256=args.sha256, decision=args.decision, autor=args.autor, motivo=args.motivo, propuesta=propuesta,
        clave_consecuencia=args.clave_consecuencia, confirmacion_humana=args.confirmo_revision_humana, actor='DESKTOP',
        revisor_no_declarado=args.revisor_no_declarado, confirmo_original=args.confirmo_original)
    print(json.dumps({k: documento[k] for k in ('documento_id', 'estado', 'tipo', 'pendiente_revision')}, ensure_ascii=True))
