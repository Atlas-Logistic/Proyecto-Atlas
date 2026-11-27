"""Actualización automática de Atlas (P0.5).

Al iniciar Atlas (scripts/iniciar_atlas.ps1, antes de abrir Desktop):

    python -B actualizar_atlas.py

compara Motor y Desktop instalados con la versión publicada en la custodia
Cloud de la empresa y, si difiere, actualiza con respaldo y vuelta atrás
automática (ver atlas_core/actualizacion_atlas.py). Siempre termina con
código 0 salvo error de uso: Atlas arranca con lo que quede instalado.

Publicar una versión (bajo lease, desde un equipo con la custodia alineada):

    python actualizar_atlas.py --publicar --version 2026.11.27-1 --rama <rama> --commit <sha>
        [--desktop-recursos "<...>\\Atlas Viajes\\resources"] --nivel-minimo 1 --raiz-atlas <raiz>
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

MOTOR = Path(__file__).resolve().parent
# Antes de leer argumentos: al importar atlas_core, una --raiz-atlas que es
# la raíz publicada (Drive) pasa a la de trabajo (P0.6).
import atlas_core  # noqa: E402,F401


def _config() -> dict:
    from atlas_core.aislamiento_empresas import base_local
    try:
        return json.loads((base_local() / "desktop_operacion.json").read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}


def _recursos_por_defecto() -> Path | None:
    ruta = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Atlas Viajes" / "resources"
    return ruta if (ruta / "app.asar").is_file() else None


def _ejecutable(args, recursos: Path | None) -> Path | None:
    """Atlas Viajes.exe junto a resources (instalación de electron-builder)."""
    if args.desktop_exe:
        return Path(args.desktop_exe)
    if recursos is None:
        return None
    candidato = Path(recursos).parent / args.proceso_desktop
    return candidato if candidato.is_file() else None


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--motor", default=str(MOTOR), help="Motor instalado (repositorio git)")
    parser.add_argument("--desktop-recursos", default=None, help="Carpeta resources de Atlas Viajes")
    parser.add_argument("--sin-desktop", action="store_true", help="No gestionar Desktop")
    parser.add_argument("--desktop-exe", default=None,
                        help="Ejecutable de Atlas Viajes para la prueba de arranque real (por defecto, junto a resources)")
    parser.add_argument("--raiz-atlas", default=None, help="Raíz operacional (turno local y lease)")
    parser.add_argument("--proceso-desktop", default="Atlas Viajes.exe")
    parser.add_argument("--estado", default=None, help="Carpeta de estado (por defecto LOCALAPPDATA\\Atlas\\actualizacion)")
    parser.add_argument("--publicar", action="store_true")
    parser.add_argument("--version")
    parser.add_argument("--rama")
    parser.add_argument("--commit")
    parser.add_argument("--nivel-minimo", type=int)
    args = parser.parse_args(argv)

    from atlas_core import actualizacion_atlas as aa
    from atlas_core.aislamiento_empresas import base_local
    from atlas_core.escritor_operativo import URL_CLOUD_POR_DEFECTO, lease_desde_entorno

    config = _config()
    from atlas_core.raiz_publicada import operativa
    raiz = args.raiz_atlas or (operativa(config["raiz"]) if config.get("raiz") else None)
    recursos = None if args.sin_desktop else (Path(args.desktop_recursos) if args.desktop_recursos else _recursos_por_defecto())

    if args.publicar:
        faltan = [n for n in ("version", "rama", "commit", "nivel_minimo") if getattr(args, n) is None]
        if faltan or not raiz:
            parser.error(f"--publicar exige --version, --rama, --commit, --nivel-minimo y --raiz-atlas ({faltan})")
        lease = lease_desde_entorno(raiz=raiz)
        if lease is None:
            parser.error("Falta ATLAS_CLOUD_MOTOR_TOKEN")
        paquete = aa.empaquetar_desktop(recursos) if recursos is not None else None
        with lease:
            if not lease.adquirir():
                print(json.dumps({"publicada": None, "motivo": lease.motivo or "ESCRITOR_OCUPADO"}))
                return 1
            resultado = aa.publicar_version(lease, version=args.version, rama=args.rama, commit=args.commit,
                                            motor=Path(args.motor), paquete_desktop=paquete, nivel_minimo=args.nivel_minimo)
        print(json.dumps(resultado, ensure_ascii=False))
        return 0

    token = os.environ.get("ATLAS_CLOUD_MOTOR_TOKEN", "").strip()
    if not token:
        print(json.dumps({"estado": "SIN_VERIFICAR", "detalle": "sin ATLAS_CLOUD_MOTOR_TOKEN"}))
        return 0
    from atlas_core.estado_confirmado import ClienteEstado
    cliente = ClienteEstado(os.environ.get("ATLAS_CLOUD_MOBILE_URL", "").strip() or URL_CLOUD_POR_DEFECTO, token, 30.0)
    actualizador = aa.Actualizador(motor=Path(args.motor), recursos=recursos, cliente=cliente,
                                   estado=Path(args.estado) if args.estado else base_local() / "actualizacion",
                                   python=config.get("python") or sys.executable, raiz=Path(raiz) if raiz else None,
                                   proceso_desktop=args.proceso_desktop, desktop_exe=_ejecutable(args, recursos))
    try:
        resultado = actualizador.actualizar()
    except Exception as error:  # noqa: BLE001 - Atlas arranca igual con lo instalado
        logging.getLogger(__name__).exception("Actualización no realizada")
        resultado = {"estado": "ERROR", "detalle": f"{type(error).__name__}: {error}"}
    print(json.dumps(resultado, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    raise SystemExit(main())
