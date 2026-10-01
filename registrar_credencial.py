"""Registra UNA credencial de Atlas para el usuario de Windows actual.

    py -3 registrar_credencial.py TAVILY_API_KEY

El valor se pide de forma interactiva y sin eco; nunca se acepta como
argumento ni se imprime. Se guarda en HKCU\\Environment (local a este
usuario/PC, nunca Git ni G:). Ejecutar una vez por usuario/PC; ver
docs/CREDENCIALES_LOCALES.md."""
import argparse
import getpass
import sys

from atlas_core.atlas_ia.credenciales import CREDENCIALES_PERMITIDAS, registrar_credencial_usuario


def main(argv=None, *, leer_secreto=getpass.getpass, interactivo=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("nombre", choices=CREDENCIALES_PERMITIDAS)
    args = parser.parse_args(argv)
    if not (sys.stdin.isatty() if interactivo is None else interactivo):
        print("Ejecuta este comando en una consola interactiva; el valor no se acepta por tubería.", file=sys.stderr)
        return 2
    try:
        valor = leer_secreto(f"Valor de {args.nombre} (no se mostrará): ")
    except (EOFError, KeyboardInterrupt):
        print("Registro cancelado.", file=sys.stderr)
        return 1
    try:
        registrar_credencial_usuario(args.nombre, valor)
    except (ValueError, OSError) as error:
        print(f"No se registró {args.nombre}: {error}", file=sys.stderr)
        return 1
    finally:
        valor = None
    print(f"{args.nombre} registrada para este usuario de Windows. "
          "Cierra y vuelve a abrir Atlas Desktop para que la use.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
