"""Crea/actualiza una credencial Mobile administrada, con hash PBKDF2."""

from __future__ import annotations

import argparse
import getpass
import json
from pathlib import Path

from atlas_core.almacenamiento_portable import escribir_json_atomico, resolver_raiz_atlas
from atlas_core.mobile import hash_password


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raiz-atlas", type=Path)
    parser.add_argument("--usuario", required=True)
    parser.add_argument("--chofer-id", required=True)
    args = parser.parse_args()
    ruta = resolver_raiz_atlas(args.raiz_atlas) / "catalogos_privados" / "usuarios_mobile.json"
    contenido = json.loads(ruta.read_text(encoding="utf-8")) if ruta.is_file() else {"schema_version": 1, "usuarios": {}}
    password = getpass.getpass("Contraseña Mobile: ")
    if len(password) < 8:
        raise SystemExit("La contraseña debe tener al menos 8 caracteres.")
    contenido["usuarios"][args.usuario] = {
        "chofer_id": args.chofer_id, "password_hash": hash_password(password),
    }
    escribir_json_atomico(ruta, contenido)
    print(f"Usuario Mobile {args.usuario!r} guardado sin contraseña en texto plano.")


if __name__ == "__main__":
    main()
