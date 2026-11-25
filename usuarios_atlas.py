"""Usuarios y sesiones de Atlas por empresa (ver docs/IDENTIDAD_PERMISOS.md).

Corre con el entorno de la empresa (como Desktop y alta_empresa.py). Las
contraseñas se leen de la primera línea de stdin, nunca de argumentos. La
sesión se pasa en la variable ATLAS_SESION. Salida: una línea JSON.

  iniciar-sesion --usuario U [--plataforma]       (stdin: contraseña) -> {"sesion": ...}
  cerrar-sesion | quien-soy
  listar
  crear --usuario U --nombre "N" --rol administrador_empresa|supervisor   (stdin: contraseña)
  desactivar|reactivar --usuario U
  cambiar-rol --usuario U --rol R
  restablecer-contrasena --usuario U          (stdin: contraseña nueva)
  exigir-identidad --activar|--desactivar
  desactivar-chofer|reactivar-chofer --usuario U [--cloud-repo R] [--d1 produccion|local:<url>]
  plataforma-inicializar --usuario U --nombre "N"  (stdin; sólo si no existe el registro de plataforma)

Códigos: 0 hecho, 2 rechazado (datos), 77 sin sesión o sin permiso.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from atlas_core import identidad as idn

DENEGADOS = {"SIN_SESION", "SESION_INVALIDA", "SESION_EXPIRADA", "SESION_REVOCADA", "SESION_DE_OTRA_EMPRESA",
             "PERMISO_DENEGADO", "CREDENCIALES_INVALIDAS", "DEMASIADOS_INTENTOS"}
MOTOR = Path(__file__).resolve().parent


def _password() -> str:
    return sys.stdin.readline().rstrip("\r\n")


def _d1_chofer(args, activo: bool) -> None:
    """Revocación efectiva primero: D1 (el Worker valida `activo` en cada petición)."""
    ctx = idn.contexto()
    catalogos = ctx.catalogos()
    comando = [sys.executable, "-B", str(Path(args.cloud_repo) / "scripts" / "migrar_usuario_mobile_cloud.py"),
               "--usuario", args.usuario, "--empresa-id", ctx.cloud_id or "empresa-prueba-javier",
               "--usuarios-json", str(catalogos / "usuarios_mobile.json"), "--choferes-json", str(catalogos / "choferes.json"),
               "--reactivar" if activo else "--desactivar"]
    if args.d1.startswith("local:"):
        comando += ["--d1-local", args.d1[len("local:"):]]
    elif args.d1 != "produccion":
        raise idn.ErrorIdentidad("D1_INVALIDO", args.d1)
    r = subprocess.run(comando, capture_output=True, text=True, encoding="utf-8", errors="replace",
                       env={**os.environ, "ATLAS_MOTOR_DIR": str(MOTOR)}, timeout=300)
    if r.returncode != 0:
        raise idn.ErrorIdentidad("D1_NO_APLICADO", (r.stderr or r.stdout)[-400:])


def ejecutar(args) -> dict:
    c = args.comando
    if c == "plataforma-inicializar":
        return {"resultado": "PLATAFORMA_INICIALIZADA", "cuenta": idn.inicializar_plataforma(args.usuario, args.nombre, _password())}
    if c == "iniciar-sesion":
        return idn.iniciar_sesion(args.usuario, _password(), plataforma=args.plataforma)
    if c == "cerrar-sesion":
        return {"cerrada": idn.cerrar_sesion()}
    sesion = idn.validar_sesion()
    if c == "quien-soy":
        return {k: sesion.get(k) for k in ("tipo", "empresa_id", "usuario", "nombre", "rol")}
    if c == "listar":
        return {"usuarios": idn.listar_usuarios(sesion=sesion)}
    if c == "crear":
        return {"resultado": "CREADO", "cuenta": idn.crear_usuario(args.usuario, args.nombre, args.rol, _password(), sesion=sesion)}
    if c in ("desactivar", "reactivar"):
        return {"resultado": c.upper(), "cuenta": idn.modificar_usuario(args.usuario, c, sesion=sesion)}
    if c == "cambiar-rol":
        return {"resultado": "ROL_CAMBIADO", "cuenta": idn.modificar_usuario(args.usuario, "cambiar_rol", rol=args.rol, sesion=sesion)}
    if c == "restablecer-contrasena":
        return {"resultado": "CONTRASENA_RESTABLECIDA",
                "cuenta": idn.modificar_usuario(args.usuario, "restablecer", password=_password(), sesion=sesion)}
    if c == "exigir-identidad":
        return idn.fijar_exigencia(args.activar, sesion=sesion)
    if c in ("desactivar-chofer", "reactivar-chofer"):
        idn.exigir(idn.GESTIONAR, sesion)
        activo = c == "reactivar-chofer"
        if idn._cuenta_chofer(idn.contexto(), args.usuario) is None:
            raise idn.ErrorIdentidad("USUARIO_INEXISTENTE", f"{args.usuario} no es chofer de esta empresa")
        _d1_chofer(args, activo)
        return {"resultado": c.upper().replace("-", "_"), "cuenta": idn.fijar_chofer_activo(args.usuario, activo, sesion=sesion)}
    raise idn.ErrorIdentidad("COMANDO_INVALIDO", c)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("comando")
    p.add_argument("--usuario")
    p.add_argument("--nombre")
    p.add_argument("--rol")
    p.add_argument("--plataforma", action="store_true")
    grupo = p.add_mutually_exclusive_group()
    grupo.add_argument("--activar", action="store_true", default=None)
    grupo.add_argument("--desactivar", dest="activar", action="store_false")
    p.add_argument("--cloud-repo", default=str(MOTOR.parent / "Atlas-Mobile-Cloud"))
    p.add_argument("--d1", default="produccion")
    args = p.parse_args(argv)
    try:
        salida, codigo = ejecutar(args), 0
    except idn.ErrorIdentidad as error:
        salida = {"resultado": "DENEGADO" if error.codigo in DENEGADOS else "RECHAZADO", "codigo": error.codigo,
                  "detalle": error.detalle}
        codigo = idn.SALIDA_DENEGADO if error.codigo in DENEGADOS else 2
    print(json.dumps(salida, ensure_ascii=False))
    return codigo


if __name__ == "__main__":
    raise SystemExit(main())
