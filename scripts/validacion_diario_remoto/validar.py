"""Validación aislada P0.1: el diario de recuperación sobrevive a la pérdida
definitiva del equipo que inició el turno. SOLO PRUEBA.

Worker real (src/worker.js del commit desplegado) sobre D1/R2 en memoria
(test/servidor_local.js, envuelto por test/servidor_reloj.mjs para desplazar
el reloj). Dos equipos = dos procesos con LOCALAPPDATA y raíz propios.

  python scripts/validacion_diario_remoto/validar.py <cloud_dir> <salida_dir>

1. A siembra la custodia (CLI real --sembrar); B recibe esa copia por "Drive".
2. A abre turno, escribe dataset y envío, y muere (taskkill /F): sin confirmar.
3. Se borra todo A (raíz y LOCALAPPDATA): pérdida definitiva.
4. B lee el diario (CLI real --diarios): íntegro, mismo contenido, vigente.
5. B verifica (--verificar), espera vencimientos y trabaja un turno normal:
   el diario de A sigue intacto en Cloud, no se restaura a la raíz de B.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import ssl
import subprocess
import sys
import urllib.request
from pathlib import Path

MOTOR = Path(__file__).resolve().parents[2]
CLOUD = Path(sys.argv[1]).resolve()
SALIDA = Path(sys.argv[2]).resolve()
MUNDO = SALIDA / "mundo"
TOKEN = "token-motor-prueba-diario-remoto"
EMPRESA_CLOUD = "empresa-prueba-diario"
OPENSSL = next((p for p in (shutil.which("openssl"), r"C:\Program Files\Git\usr\bin\openssl.exe",
                             r"C:\Program Files\Git\ucrt64\bin\openssl.exe") if p and Path(p).is_file()), None)
CHECKS: list[dict] = []


def registrar(nombre: str, ok: bool, detalle=None) -> None:
    CHECKS.append({"check": nombre, "ok": bool(ok), "detalle": detalle})
    print(("OK   " if ok else "FALLA") + " " + nombre, flush=True)


class Worker:
    def __init__(self) -> None:
        tls = MUNDO / "tls"
        tls.mkdir(parents=True)
        subprocess.run([OPENSSL, "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1", "-subj", "/CN=127.0.0.1",
                        "-addext", "subjectAltName=IP:127.0.0.1", "-keyout", str(tls / "key.pem"), "-out", str(tls / "cert.pem")],
                       check=True, capture_output=True)
        self.cert = tls / "cert.pem"
        self.ssl = ssl.create_default_context(cafile=str(self.cert))
        config = MUNDO / "worker_config.json"
        config.write_text(json.dumps({
            "env": {"CLOUD_MOTOR_AUTH_SECRET": TOKEN, "CLOUD_MOTOR_EMPRESA_ID": EMPRESA_CLOUD,
                    "CLOUD_MOBILE_AUTH_SECRET": "secreto-mobile-prueba"},
            "usuarios": [], "tls": {"cert": str(self.cert), "key": str(tls / "key.pem")}}), encoding="utf-8")
        self.p = subprocess.Popen(["node", str(CLOUD / "test" / "servidor_reloj.mjs"), str(config)], cwd=CLOUD,
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        linea = self.p.stdout.readline().strip()
        if not linea.startswith("LISTO "):
            raise RuntimeError("Worker local no inició: " + linea + self.p.stderr.read()[-1500:])
        self.url = f"https://127.0.0.1:{linea.split()[1]}"

    def avanzar(self, segundos: int) -> None:
        self.p.stdin.write(f"avanzar {segundos}\n")
        self.p.stdin.flush()
        if not self.p.stdout.readline().startswith("RELOJ "):
            raise RuntimeError("reloj del Worker no avanzó")

    def tabla(self, nombre: str):
        with urllib.request.urlopen(f"{self.url}/__prueba/tabla/{nombre}", timeout=30, context=self.ssl) as r:
            return json.loads(r.read())

    def cerrar(self) -> None:
        self.p.kill()


def entorno(worker: Worker, local: Path) -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith("ATLAS_")}
    env.update(LOCALAPPDATA=str(local), ATLAS_CLOUD_MOTOR_TOKEN=TOKEN, ATLAS_CLOUD_MOBILE_URL=worker.url,
               SSL_CERT_FILE=str(worker.cert), PYTHONPATH=str(MOTOR), PYTHONIOENCODING="utf-8")
    return env


def cli(env: dict, *args: str) -> tuple[int, dict | None, str]:
    r = subprocess.run([sys.executable, "-m", "atlas_core.estado_confirmado", *args], cwd=MOTOR, env=env,
                       capture_output=True, text=True, encoding="utf-8", timeout=300)
    try:
        return r.returncode, json.loads(r.stdout.strip().splitlines()[-1]), r.stderr
    except (ValueError, IndexError):
        return r.returncode, None, r.stdout + r.stderr


def raiz_inicial(raiz: Path) -> None:
    (raiz / "operacion" / "actual").mkdir(parents=True)
    (raiz / "catalogos_privados").mkdir(parents=True)
    (raiz / "operacion" / "actual" / "analisis_completo_guias.csv").write_text(
        "archivo;numero_guia;estado_procesamiento\nlocal/g1.jpg;100001;OK\nlocal/g2.jpg;100002;OK\n", encoding="utf-8")
    (raiz / "catalogos_privados" / "vehiculos.json").write_text(json.dumps({"vehiculos": ["AAAA11"]}), encoding="utf-8")


def main() -> int:
    if MUNDO.exists():
        shutil.rmtree(MUNDO)
    MUNDO.mkdir(parents=True)
    worker = Worker()
    try:
        assert worker.url.startswith("https://127.0.0.1:")
        a_dir, b_dir = MUNDO / "equipo-a", MUNDO / "equipo-b"
        raiz_a, raiz_b = a_dir / "Atlas", b_dir / "Atlas"
        env_a, env_b = entorno(worker, a_dir / "local"), entorno(worker, b_dir / "local")
        raiz_inicial(raiz_a)

        # 1. Siembra en A y copia "Drive" en B.
        codigo, sembrado, err = cli(env_a, "--raiz-atlas", str(raiz_a), "--sembrar")
        registrar("A siembra la custodia (CLI real)", codigo == 0 and sembrado and sembrado.get("sembrado"), sembrado or err[-800:])
        shutil.copytree(raiz_a, raiz_b)
        version_sembrada = worker.tabla("estado_operativo_marca")[0]["version"]

        # 2. A trabaja y muere sin confirmar.
        proceso = subprocess.Popen([sys.executable, str(Path(__file__).with_name("equipo.py")), "trabajar", str(raiz_a)],
                                   cwd=MOTOR, env=env_a, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8")
        linea = proceso.stdout.readline().strip()
        registrar("A escribe datos operacionales bajo lease", linea.startswith("ESCRITO "), linea or proceso.stderr.read()[-1500:])
        if not linea.startswith("ESCRITO "):
            return 1
        a = json.loads(linea[len("ESCRITO "):])
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proceso.pid)], capture_output=True)
        proceso.wait(timeout=30)
        registrar("A muere sin confirmar ni liberar (taskkill /F)", proceso.returncode != 0, proceso.returncode)
        marca = worker.tabla("estado_operativo_marca")[0]
        registrar("la marca Cloud sólo avanzó por el diario (ningún dato confirmado)",
                  marca["version"] == a["version"] and a["version_base"] == version_sembrada,
                  {"marca": marca["version"], "base": a["version_base"]})

        # 3. Pérdida definitiva de A.
        shutil.rmtree(a_dir)
        registrar("equipo A eliminado (raíz y LOCALAPPDATA)", not a_dir.exists())

        # 4. B lee el diario desde Cloud.
        codigo, leidos, err = cli(env_b, "--raiz-atlas", str(raiz_b), "--diarios")
        diarios = (leidos or {}).get("diarios", [])
        registrar("B lee exactamente un diario abierto (CLI real --diarios)", codigo == 0 and len(diarios) == 1, leidos or err[-800:])
        if len(diarios) != 1:
            return 1
        d = diarios[0]
        contenido = d["diario"]
        bytes_canonicos = json.dumps(contenido, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("ascii")
        registrar("diario íntegro: misma huella que publicó A y contenido que la reproduce",
                  d["sha256"] == a["sha256"] and hashlib.sha256(bytes_canonicos).hexdigest() == a["sha256"], d["sha256"])
        registrar("diario ligado al turno de A (escritor, época, ruta)",
                  contenido["escritor_id"] == a["escritor_id"] and contenido["epoca"] == a["epoca"] and d["ruta"] == a["diario"],
                  {k: contenido[k] for k in ("escritor_id", "epoca")})
        registrar("diario ligado a la empresa y a la versión base", contenido["empresa_id"] == "mbt"
                  and contenido["version_base"] == version_sembrada, {k: contenido[k] for k in ("empresa_id", "version_base")})
        registrar("diario lista las rutas escritas y sus huellas base", contenido["rutas"] == a["rutas"] and
                  contenido["huellas_base"]["operacion/mobile/envios/env-perdido/envio.json"] is None and
                  contenido["huellas_base"]["operacion/actual/analisis_completo_guias.csv"] is not None, contenido["rutas"])
        registrar("diario vigente: nadie confirmó después", d["vigente"] is True)
        objetos = worker.tabla("estado_operativo_archivos")
        filas = [f for f in objetos if f["ruta"] == a["diario"]]
        registrar("D1 guarda el puntero del diario para la empresa Cloud",
                  filas and all(f["empresa_id"] == EMPRESA_CLOUD for f in filas) and filas[-1]["sha256"] == a["sha256"], filas)

        codigo, verificacion, err = cli(env_b, "--raiz-atlas", str(raiz_b), "--verificar")
        registrar("B verifica su copia sin escribir: 0 distintos y el diario abierto informado",
                  codigo == 0 and verificacion and verificacion["distintos"] == 0 and verificacion["diarios_abiertos"] == [a["diario"]],
                  verificacion or err[-800:])

        # 5. B trabaja un turno normal tras los vencimientos.
        worker.avanzar(11 * 60)
        r = subprocess.run([sys.executable, str(Path(__file__).with_name("equipo.py")), "turno", str(raiz_b)], cwd=MOTOR,
                           env=env_b, capture_output=True, text=True, encoding="utf-8", timeout=300)
        linea = (r.stdout.strip().splitlines() or [""])[-1]
        turno = json.loads(linea[len("TURNO "):]) if linea.startswith("TURNO ") else None
        registrar("B obtiene el lease y trabaja un turno normal", r.returncode == 0 and turno is not None, linea or r.stderr[-1500:])
        if turno:
            registrar("B es otro escritor y ve el diario abierto de A sin adoptarlo",
                      turno["escritor_id"] != a["escritor_id"] and turno["resumen"]["diarios_abiertos"] == [a["diario"]]
                      and turno["resumen"]["restaurados"] == [] and turno["resumen"]["pendiente_confirmado"] == 0, turno)
        registrar("el diario no se restaura a la raíz de B", not (raiz_b / ".atlas_custodia").exists())
        codigo, leidos2, err = cli(env_b, "--raiz-atlas", str(raiz_b), "--diarios")
        d2 = (leidos2 or {}).get("diarios", [])
        registrar("tras el turno de B el diario de A sigue íntegro en Cloud (ya no vigente)",
                  codigo == 0 and len(d2) == 1 and d2[0]["sha256"] == a["sha256"] and d2[0]["vigente"] is False, leidos2 or err[-800:])
        diarios_b = [f for f in worker.tabla("estado_operativo_archivos")
                     if turno and f["ruta"].startswith(f".atlas_custodia/diarios/{turno['escritor_id']}/")]
        registrar("el diario propio de B quedó cerrado al confirmar", bool(diarios_b) and diarios_b[-1]["sha256"] is None, diarios_b)
    finally:
        worker.cerrar()
        (SALIDA / "validacion.json").write_text(json.dumps(CHECKS, ensure_ascii=False, indent=2), encoding="utf-8")
    fallas = [c for c in CHECKS if not c["ok"]]
    print(f"{len(CHECKS) - len(fallas)}/{len(CHECKS)} checks aprobados", flush=True)
    return 1 if fallas else 0


if __name__ == "__main__":
    raise SystemExit(main())
