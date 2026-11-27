"""Ensayo aislado de la migración coordinada P0 y su reversión. SOLO PRUEBA.

Equipo sintético con el Motor HOY instalado en CASA (48d6096, protocolo 2)
sobre una "Drive" sintética, Worker b28d594 real local. Ejecuta los scripts
REALES de scripts/migracion_p0 (sin tareas programadas: -SinTareas):

1. Motor anterior siembra y trabaja (PULL) contra la Drive.
2. preflight.ps1 -> LISTO; migrar_equipo.ps1 en simulación no cambia nada.
3. migrar_equipo.ps1 -Aplicar: respaldo remoto/local/Desktop/acceso directo,
   Motor P0 por fast-forward, raíz de trabajo, acceso directo a iniciar_atlas.
4. PULL real del Motor P0 ingesta un envío y publica en la Drive.
5. protocolo_minimo=3: un equipo aún en el Motor anterior queda fuera; el P0 sigue.
6. Reversión: protocolo_minimo=2 y revertir_equipo.ps1 -Aplicar: Motor
   anterior, acceso directo original; el Motor anterior trabaja sobre la
   Drive (que ya tenía lo confirmado) con 0 diferencias.

  python validar_migracion.py <cloud_dir> <salida_dir> <motor_anterior_commit> <desktop_base>
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import validar as v  # noqa: E402
import validar_pull as vp  # noqa: E402
import mundo_mbt  # noqa: E402
from validar_integral import borrar, git, VENV  # noqa: E402

ANTERIOR = sys.argv[3]
DESKTOP_BASE = Path(sys.argv[4])
SCRIPTS = v.MOTOR / "scripts" / "migracion_p0"
RAMA = "prueba/p0-migracion"


def ps(script: str, env: dict, *args: str) -> tuple[int, str]:
    r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(SCRIPTS / script), *args],
                       env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=1800)
    return r.returncode, (r.stdout + r.stderr)[-3000:]


def acceso_directo(ruta: Path) -> str:
    r = subprocess.run(["powershell", "-NoProfile", "-Command",
                        f"$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{ruta}'); \"$($s.TargetPath)|$($s.Arguments)\""],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.stdout.strip()


def main() -> int:
    if v.MUNDO.exists():
        borrar(v.MUNDO)
    v.MUNDO.mkdir(parents=True)
    worker = v.Worker(usuarios=[vp.CHOFER])
    try:
        assert worker.url.startswith("https://127.0.0.1:")
        nuevo = git(v.MOTOR, "rev-parse", "HEAD")
        origen = v.MUNDO / "origin.git"
        git(v.MUNDO, "clone", "-q", "--bare", "--shared", str(v.MOTOR), str(origen))
        git(origen, "branch", "-f", RAMA, nuevo)
        casa = v.MUNDO / "casa"
        motor, drive, trabajo, local = casa / "motor", casa / "Drive" / "Atlas", casa / "Trabajo" / "Atlas", casa / "local"
        desktop = casa / "Programs" / "Atlas Viajes"
        git(v.MUNDO, "clone", "-q", "--shared", str(origen), str(motor))
        git(motor, "checkout", "-q", "-B", "casa/instalado", ANTERIOR)
        subprocess.run(["cmd", "/c", "mklink", "/J", str(motor / ".venv"), str(VENV)], capture_output=True, check=True)
        (desktop / "resources").mkdir(parents=True)
        shutil.copy2(DESKTOP_BASE / "resources" / "app.asar", desktop / "resources" / "app.asar")
        (local / "Atlas").mkdir(parents=True)
        (local / "Atlas" / "desktop_operacion.json").write_text(json.dumps({
            "habilitada": True, "autorizada": True, "raiz": str(drive), "proyecto": str(motor), "modo_escritor": "lease_cloud"}),
            encoding="utf-8")
        lnk = casa / "Atlas Viajes.lnk"
        subprocess.run(["powershell", "-NoProfile", "-Command",
                        f"$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{lnk}'); $s.TargetPath='{desktop / 'Atlas Viajes.exe'}'; $s.Save()"],
                       check=True, capture_output=True)
        mundo_mbt.construir(drive, ["900001", "900002"])
        env = v.entorno(worker, local)
        env.update(PYTHONPATH=str(motor), ATLAS_EXCLUSION_RAICES=str(drive), ATLAS_OCR_PROVIDER="rapidocr",
                   ATLAS_RAPIDOCR_PYTHON=str(Path(os.environ["LOCALAPPDATA"]) / "Atlas" / "runtime" / "rapidocr" / "Scripts" / "python.exe"),
                   ATLAS_OPERACION_CONFIG=str(local / "Atlas" / "desktop_operacion.json"))
        python = str(VENV / "Scripts" / "python.exe")

        def motor_py(*args: str) -> tuple[int, str]:
            r = subprocess.run([python, "-B", *args], cwd=motor, env=env, capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=1800)
            return r.returncode, r.stdout + r.stderr

        # 1. Motor anterior (protocolo 2) sobre la Drive.
        codigo, salida = motor_py("-m", "atlas_core.estado_confirmado", "--raiz-atlas", str(drive), "--sembrar")
        v.registrar("Motor anterior (48d6096) siembra la custodia sobre la Drive", codigo == 0, salida[-300:])
        codigo, salida = motor_py("sincronizar_mobile_cloud.py", "--raiz-atlas", str(drive), "--sin-procesar")
        v.registrar("PULL del Motor anterior funciona antes de migrar", codigo == 0, salida[-300:])

        # 2. Comprobación previa y simulación.
        comunes = ["-Motor", str(motor), "-Raiz", str(drive), "-RaizTrabajo", str(trabajo), "-LocalAppData", str(local)]
        codigo, salida = ps("preflight.ps1", env, *comunes, "-CommitEsperado", ANTERIOR, "-DesktopRecursos", str(desktop / "resources"),
                            "-Python", python)
        v.registrar("preflight: LISTO para migrar", codigo == 0 and "LISTO para migrar" in salida, salida[-600:])
        migrar = [*comunes, "-Commit", nuevo, "-Rama", RAMA, "-Equipo", "CASA", "-DesktopDir", str(desktop),
                  "-AccesoDirecto", str(lnk), "-Python", python, "-SinTareas"]
        codigo, salida = ps("migrar_equipo.ps1", env, *migrar)
        v.registrar("migración simulada: nada cambia", codigo == 0 and git(motor, "rev-parse", "HEAD") == ANTERIOR
                    and not (local / "Atlas" / "raiz_publicada.json").exists() and not trabajo.exists(), salida[-600:])

        # 3. Migración aplicada.
        codigo, salida = ps("migrar_equipo.ps1", env, *migrar, "-Aplicar")
        v.registrar("migración aplicada (código 0)", codigo == 0, salida[-1500:])
        estado = json.loads((local / "Atlas" / "migracion_p0_estado.json").read_text(encoding="utf-8-sig"))
        v.registrar("respaldo remoto del Motor anterior en origin", git(origen, "rev-parse", estado["rama_respaldo"]) == ANTERIOR)
        v.registrar("respaldos locales: configuración, app.asar y acceso directo",
                    (Path(estado["respaldo_dir"]) / "desktop_operacion.json").is_file() and Path(estado["asar_respaldo"]).is_file()
                    and Path(estado["acceso_directo_respaldo"]).is_file())
        v.registrar("Motor P0 instalado por fast-forward", git(motor, "rev-parse", "HEAD") == nuevo)
        cfg = json.loads((local / "Atlas" / "raiz_publicada.json").read_text(encoding="utf-8"))
        v.registrar("raíz de trabajo preparada; Drive pasa a ser la publicada",
                    Path(cfg["raiz_trabajo"]) == trabajo and Path(cfg["raiz_publicada"]) == drive and (trabajo / v.DATASET).is_file())
        destino = acceso_directo(lnk)
        v.registrar("acceso directo de Atlas -> iniciar_atlas.ps1", "iniciar_atlas.ps1" in destino, destino)

        # 4. Motor P0 trabaja: ingesta real y publicación en la Drive.
        vp.jpeg = lambda _m: mundo_mbt.imagen_guia("900101")
        vp.enviar_mobile(worker, "envio-900101")
        worker.avanzar(60)
        codigo, salida = motor_py("sincronizar_mobile_cloud.py", "--raiz-atlas", str(drive))
        v.registrar("PULL del Motor P0 (OCR real) ingesta y publica en la Drive", codigo == 0
                    and "0000900101" in (drive / v.DATASET).read_text(encoding="utf-8-sig"), salida[-400:])

        # 5. Protocolo 3: un equipo aún en el Motor anterior queda fuera.
        codigo, salida = ps("protocolo_d1.ps1", env, "-Nivel", "3")
        v.registrar("protocolo_d1.ps1 en simulación muestra los comandos wrangler", codigo == 0
                    and "SET protocolo_minimo = 3" in salida and "SIMULACION" in salida, salida[-400:])
        worker.p.stdin.write("sql UPDATE estado_operativo_marca SET protocolo_minimo = 3\n")
        worker.p.stdin.flush()
        worker.p.stdout.readline()
        oficina = v.MUNDO / "oficina-motor"
        git(v.MUNDO, "clone", "-q", "--shared", str(origen), str(oficina))
        git(oficina, "checkout", "-q", ANTERIOR)
        worker.avanzar(11 * 60)
        r = subprocess.run([python, "-B", "-c", (
            "import json; from atlas_core.escritor_operativo import lease_desde_entorno; "
            f"l = lease_desde_entorno(raiz=r'{v.MUNDO / 'oficina-raiz'}'); ok = l.adquirir(); l.cerrar(); "
            "print(json.dumps({'ok': ok, 'motivo': l.motivo}))")], cwd=oficina,
            env={**v.entorno(worker, v.MUNDO / "oficina-local"), "PYTHONPATH": str(oficina)}, capture_output=True, text=True, encoding="utf-8")
        v.registrar("con protocolo 3, un Motor anterior no obtiene lease", '"ESCRITOR_PROTOCOLO_OBSOLETO"' in r.stdout, r.stdout + r.stderr[-300:])
        worker.avanzar(11 * 60)
        codigo, salida = motor_py("sincronizar_mobile_cloud.py", "--raiz-atlas", str(drive), "--sin-procesar")
        v.registrar("el Motor P0 sigue trabajando con protocolo 3", codigo == 0, salida[-300:])

        # 6. Reversión segura.
        worker.p.stdin.write("sql UPDATE estado_operativo_marca SET protocolo_minimo = 2\n")
        worker.p.stdin.flush()
        worker.p.stdout.readline()
        codigo, salida = ps("revertir_equipo.ps1", env, "-LocalAppData", str(local), "-Python", python, "-SinTareas")
        v.registrar("reversión simulada: nada cambia", codigo == 0 and git(motor, "rev-parse", "HEAD") == nuevo, salida[-400:])
        codigo, salida = ps("revertir_equipo.ps1", env, "-LocalAppData", str(local), "-Python", python, "-SinTareas", "-Aplicar")
        v.registrar("reversión aplicada (código 0)", codigo == 0, salida[-1500:])
        v.registrar("Motor anterior restaurado y raíz de trabajo desactivada", git(motor, "rev-parse", "HEAD") == ANTERIOR
                    and not (local / "Atlas" / "raiz_publicada.json").exists())
        v.registrar("acceso directo original restaurado", "Atlas Viajes.exe" in acceso_directo(lnk), acceso_directo(lnk))
        worker.avanzar(60)
        codigo, salida = motor_py("-m", "atlas_core.estado_confirmado", "--raiz-atlas", str(drive), "--verificar")
        verificacion = json.loads(salida.strip().splitlines()[-1]) if codigo == 0 else {}
        v.registrar("el Motor anterior ve la Drive igual a Cloud (0 diferencias, incluye lo hecho por el P0)",
                    verificacion.get("distintos") == 0, salida[-400:])
        codigo, salida = motor_py("sincronizar_mobile_cloud.py", "--raiz-atlas", str(drive), "--sin-procesar")
        v.registrar("el Motor anterior vuelve a trabajar (PULL código 0)", codigo == 0, salida[-400:])
    finally:
        worker.cerrar()
        (v.SALIDA / "validacion_migracion.json").write_text(json.dumps(v.CHECKS, ensure_ascii=False, indent=2), encoding="utf-8")
    fallas = [c for c in v.CHECKS if not c["ok"]]
    print(f"{len(v.CHECKS) - len(fallas)}/{len(v.CHECKS)} checks aprobados", flush=True)
    return 1 if fallas else 0


if __name__ == "__main__":
    raise SystemExit(main())
