"""Alta controlada de licencia de chofer desde Desktop.

Sin `--automatica`: la persona escribe clase y vencimiento (uso original).
Con `--automatica`: se conserva el original y se lee en el acto si es un PDF
con texto embebido; los datos confiables se registran solos y lo que necesita
OCR (imagen o PDF escaneado) lo lee el próximo ciclo PULL.
"""
import argparse
import json

from atlas_core.fichas_choferes import EMPRESA_ACTUAL, registrar_licencia_chofer


def adjuntar_automatica(raiz, *, empresa, ficha_id, referencia_catalogo, archivo):
    from atlas_core.desktop_operacion import sesion
    from atlas_core.extraccion_licencias import extraer_licencias_pendientes
    from atlas_core.fichas_choferes import adjuntar_licencia_desktop

    with sesion(raiz, reutilizar=True) as comprobar:
        adjunta = adjuntar_licencia_desktop(raiz, empresa=empresa, ficha_id=ficha_id,
                                            referencia_catalogo=referencia_catalogo, archivo_origen=archivo)
        try:
            lectura = extraer_licencias_pendientes(raiz, comprobar=comprobar, fabrica_ocr=None, empresa=empresa,
                                                   actor='DESKTOP', documento_id=adjunta['documento_id'],
                                                   permitir_ocr=False)
        except Exception as error:  # noqa: BLE001 -- el original ya quedó guardado; PULL lo leerá
            lectura = {'extraidas': [], 'diferidas': [], 'errores': [{'error': str(error)}]}
    extraida = next((e for e in lectura['extraidas'] if e['documento_id'] == adjunta['documento_id']), None)
    registro = (extraida or {}).get('registro') or {}
    if registro.get('registrada'):
        estado = 'REGISTRADA'
    elif extraida:
        estado = 'POR_COMPLETAR'
    else:
        estado = 'LECTURA_PENDIENTE'
    return {'ok': True, 'documento_id': adjunta['documento_id'], 'ficha_id': adjunta['ficha_id'],
            'sha256': adjunta['sha256'], 'estado': estado, 'vencimiento': registro.get('vencimiento'),
            'registrados': registro.get('registrados', []),
            'por_completar': registro.get('por_completar', []) if extraida else [],
            'reemplazados': registro.get('reemplazados', 0)}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--raiz-atlas', required=True)
    parser.add_argument('--ficha-id', required=True)
    parser.add_argument('--referencia-catalogo', required=True)
    parser.add_argument('--vencimiento')
    parser.add_argument('--clase')
    parser.add_argument('--archivo', required=True)
    parser.add_argument('--automatica', action='store_true',
                        help='Conserva el original y registra solo los datos leídos con confianza')
    args = parser.parse_args()
    if args.automatica:
        if args.vencimiento or args.clase:
            parser.error('--automatica no admite --vencimiento ni --clase')
        resultado = adjuntar_automatica(args.raiz_atlas, empresa=EMPRESA_ACTUAL, ficha_id=args.ficha_id,
                                        referencia_catalogo=args.referencia_catalogo, archivo=args.archivo)
    else:
        if not args.vencimiento or not args.clase:
            parser.error('Indique --vencimiento y --clase, o use --automatica')
        resultado = registrar_licencia_chofer(
            args.raiz_atlas, empresa=EMPRESA_ACTUAL, ficha_id=args.ficha_id,
            referencia_catalogo=args.referencia_catalogo, vencimiento=args.vencimiento,
            clase=args.clase, archivo_origen=args.archivo, actor='DESKTOP',
        )
    print(json.dumps(resultado, ensure_ascii=True))
