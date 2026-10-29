"""Entrada B1 exclusivamente lectora, sin confirmaciones ni persistencia."""
import argparse
import json
import sys
import traceback
from atlas_core.b1_operador import OperadorB1

# Desktop corre este CLI bajo SOLO CONSULTA y muestra el stderr de un proceso
# fallido: un error inesperado se responde como turno FALLIDA comprensible;
# la traza queda en stderr y en `diagnostico` (no se muestra en el mensaje).
MENSAJE_FALLA = 'B1 no pudo procesar esta consulta por un error interno. No se modificó nada.'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--raiz-atlas', required=True)
    parser.add_argument('--texto', required=True)
    parser.add_argument('--derivar-operacionales', action='store_true')
    args = parser.parse_args()
    try:
        respuesta = OperadorB1(args.raiz_atlas).consultar(args.texto, derivar_operacionales=args.derivar_operacionales)
    except Exception as error:  # noqa: BLE001 -- el turno siempre devuelve un JSON
        traza = traceback.format_exc()
        print(traza, file=sys.stderr)
        respuesta = {'estado': 'FALLIDA', 'mensaje': MENSAJE_FALLA,
                     'diagnostico': {'tipo': type(error).__name__, 'detalle': str(error)[:500], 'traza': traza[-4000:]}}
    print(json.dumps(respuesta, ensure_ascii=True))

if __name__ == '__main__':
    main()
