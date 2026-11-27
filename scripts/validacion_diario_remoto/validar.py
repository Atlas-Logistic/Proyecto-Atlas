"""Validación aislada P0.1 + P0.2: el turno de un equipo eliminado por
completo se recupera desde otro equipo usando sólo Cloud. SOLO PRUEBA.

Worker real (src/worker.js del commit desplegado) sobre D1/R2 en memoria
(test/servidor_local.js, envuelto por test/servidor_reloj.mjs para desplazar
el reloj). Cada equipo = un proceso con LOCALAPPDATA y raíz propios.

  python scripts/validacion_diario_remoto/validar.py <cloud_dir> <salida_dir>

1. A siembra la custodia; B y C reciben esa copia por "Drive".
2. A ingesta una guía con el escritor real (append directo + punto de
   control) y un envío, y muere (taskkill /F) sin confirmar. Drive alcanzó a
   llevar su dataset a C. Se borra todo A.
3. B lee el diario (--diarios): íntegro, ligado a empresa/versión/turno.
4. C recupera el turno (--recuperar-turno, previa y --aplicar): queda en
   Cloud exactamente lo que A escribió; un segundo intento no duplica.
5. B alinea y ve la guía una sola vez.
6. E escribe y muere; B confirma después otra guía: recuperar E se bloquea
   (VERSION_POSTERIOR) sin tocar Cloud.
"""
from __future__ import annotations

import csv
import hashlib
import io
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
DATASET = "operacion/actual/analisis_completo_guias.csv"
OPENSSL = next((p for p in (shutil.which("openssl"), r"C:\Program Files\Git\usr\bin\openssl.exe",
                             r"C:\Program Files\Git\ucrt64\bin\openssl.exe") if p and Path(p).is_file()), None)
CHECKS: list[dict] = []
sys.path.insert(0, str(MOTOR))


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

    def vigentes(self) -> dict:
        salida: dict = {}
        for f in self.tabla("estado_operativo_archivos"):
            if f["ruta"] not in salida or f["version"] > salida[f["ruta"]][1]:
                salida[f["ruta"]] = (f["sha256"], f["version"])
        return {r: s for r, (s, _v) in salida.items()}

    def version(self) -> int:
        return self.tabla("estado_operativo_marca")[0]["version"]

    def faltantes(self, huellas: list[str]) -> list[str]:
        req = urllib.request.Request(f"{self.url}/api/motor/estado/faltantes", method="POST",
                                     data=json.dumps({"sha256": huellas}).encode(),
                                     headers={"authorization": f"Bearer {TOKEN}", "content-type": "application/json"})
        with urllib.request.urlopen(req, timeout=30, context=self.ssl) as r:
            return json.loads(r.read())["faltantes"]

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


def equipo(env: dict, *args: str, esperar: bool = True):
    comando = [sys.executable, str(Path(__file__).with_name("equipo.py")), *args]
    if not esperar:
        return subprocess.Popen(comando, cwd=MOTOR, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, encoding="utf-8")
    r = subprocess.run(comando, cwd=MOTOR, env=env, capture_output=True, text=True, encoding="utf-8", timeout=600)
    linea = (r.stdout.strip().splitlines() or [""])[-1]
    return (json.loads(linea.split(" ", 1)[1]) if linea.startswith("TURNO ") else None), (linea or r.stderr[-1500:])


def matar(proceso) -> None:
    subprocess.run(["taskkill", "/F", "/T", "/PID", str(proceso.pid)], capture_output=True)
    proceso.wait(timeout=30)


def sha_archivo(ruta: Path) -> str | None:
    return hashlib.sha256(ruta.read_bytes()).hexdigest() if ruta.is_file() else None


def guias(ruta: Path) -> list[str]:
    lector = csv.DictReader(io.StringIO(ruta.read_text(encoding="utf-8-sig"), newline=""), delimiter=";")
    return [f["numero_guia"] for f in lector]


def raiz_inicial(raiz: Path) -> None:
    from atlas_core.procesamiento_masivo import COLUMNAS
    (raiz / "operacion" / "actual").mkdir(parents=True)
    (raiz / "catalogos_privados").mkdir(parents=True)
    with (raiz / "operacion" / "actual" / "analisis_completo_guias.csv").open("w", encoding="utf-8-sig", newline="") as f:
        escritor = csv.DictWriter(f, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader()
        for g in ("100001", "100002"):
            fila = dict.fromkeys(COLUMNAS, "")
            fila.update(archivo=f"local/g{g}.jpg", numero_guia=g, estado_procesamiento="OK")
            escritor.writerow(fila)
    (raiz / "catalogos_privados" / "vehiculos.json").write_text(json.dumps({"vehiculos": ["AAAA11"]}), encoding="utf-8")


def main() -> int:
    if MUNDO.exists():
        shutil.rmtree(MUNDO)
    MUNDO.mkdir(parents=True)
    worker = Worker()
    try:
        assert worker.url.startswith("https://127.0.0.1:")
        dirs = {n: MUNDO / f"equipo-{n}" for n in "abce"}
        raiz = {n: d / "Atlas" for n, d in dirs.items()}
        env = {n: entorno(worker, d / "local") for n, d in dirs.items()}
        raiz_inicial(raiz["a"])

        # 1. Siembra en A; B y C reciben la copia por "Drive".
        codigo, sembrado, err = cli(env["a"], "--raiz-atlas", str(raiz["a"]), "--sembrar")
        registrar("A siembra la custodia (CLI real)", codigo == 0 and sembrado and sembrado.get("sembrado"), sembrado or err[-800:])
        for n in "bc":
            shutil.copytree(raiz["a"], raiz[n])
        version_sembrada = worker.version()
        base_dataset = worker.vigentes()[DATASET]

        # 2. A ingesta y muere sin confirmar; Drive alcanzó a llevar el dataset a C.
        proceso = equipo(env["a"], "trabajar", str(raiz["a"]), "900001", esperar=False)
        linea = proceso.stdout.readline().strip()
        registrar("A ingesta una guía con el escritor real bajo lease", linea.startswith("ESCRITO "), linea or proceso.stderr.read()[-1500:])
        if not linea.startswith("ESCRITO "):
            return 1
        a = json.loads(linea.split(" ", 1)[1])
        envio_a = "operacion/mobile/envios/env-900001/envio.json"
        dataset_a = sha_archivo(raiz["a"] / DATASET)
        envio_sha = sha_archivo(raiz["a"].joinpath(*envio_a.split("/")))
        registrar("el contenido escrito por A quedó custodiado antes de morir (sin pendientes)",
                  a["pendientes"] == [] and a["contenido"].get(DATASET) == dataset_a and a["contenido"].get(envio_a) == envio_sha,
                  {"pendientes": a["pendientes"], "contenido": a["contenido"]})
        registrar("R2 tiene el contenido de A", worker.faltantes([dataset_a, envio_sha]) == [])
        shutil.copy2(raiz["a"] / DATASET, raiz["c"] / DATASET)
        matar(proceso)
        registrar("A muere sin confirmar ni liberar (taskkill /F)", proceso.returncode != 0, proceso.returncode)
        registrar("ningún dato de A confirmado en la marca", worker.vigentes()[DATASET] == base_dataset)
        shutil.rmtree(dirs["a"])
        registrar("equipo A eliminado (raíz y LOCALAPPDATA)", not dirs["a"].exists())

        # 3. B lee el diario desde Cloud.
        codigo, leidos, err = cli(env["b"], "--raiz-atlas", str(raiz["b"]), "--diarios")
        diarios = (leidos or {}).get("diarios", [])
        registrar("B lee exactamente un diario abierto (CLI real --diarios)", codigo == 0 and len(diarios) == 1, leidos or err[-800:])
        if len(diarios) != 1:
            return 1
        d = diarios[0]["diario"]
        registrar("diario íntegro y ligado a empresa, versión base y turno de A",
                  diarios[0]["sha256"] == a["sha256"] and d["escritor_id"] == a["escritor_id"] and d["epoca"] == a["epoca"]
                  and d["empresa_id"] == "mbt" and d["version_base"] == version_sembrada and diarios[0]["vigente"],
                  {k: d[k] for k in ("escritor_id", "epoca", "empresa_id", "version_base")})

        # 4. C (con el dataset parcial de A traído por Drive) recupera desde Cloud.
        worker.avanzar(11 * 60)
        codigo, previa, err = cli(env["c"], "--raiz-atlas", str(raiz["c"]), "--recuperar-turno", a["diario"])
        registrar("C obtiene el lease pese al dataset de A en su Drive y la previa es RECUPERABLE",
                  codigo == 0 and previa and previa["estado"] == "RECUPERABLE"
                  and previa.get("documentos_recuperados") == ["mobile/env-900001/original.jpg"], previa or err[-1500:])
        registrar("la previa no confirma datos", worker.vigentes()[DATASET] == base_dataset)
        worker.avanzar(60)
        codigo, hecho, err = cli(env["c"], "--raiz-atlas", str(raiz["c"]), "--recuperar-turno", a["diario"], "--aplicar")
        registrar("C aplica la recuperación (CLI real --aplicar)", codigo == 0 and hecho and hecho["estado"] == "RECUPERADO",
                  hecho or err[-1500:])
        vig = worker.vigentes()
        registrar("Cloud contiene exactamente lo que A escribió", vig[DATASET] == dataset_a and vig[envio_a] == envio_sha,
                  {DATASET: vig.get(DATASET), envio_a: vig.get(envio_a)})
        registrar("la raíz de C coincide con lo que A escribió",
                  sha_archivo(raiz["c"] / DATASET) == dataset_a and sha_archivo(raiz["c"].joinpath(*envio_a.split("/"))) == envio_sha)
        auditoria = f"operacion/actual/recuperaciones_turno/{a['escritor_id']}__{a['epoca']}.json"
        registrar("diario de A cerrado junto con los datos y registro de auditoría confirmado",
                  vig.get(a["diario"]) is None and vig.get(auditoria) is not None, {"auditoria": vig.get(auditoria)})
        version = worker.version()
        worker.avanzar(60)
        codigo, otra, err = cli(env["c"], "--raiz-atlas", str(raiz["c"]), "--recuperar-turno", a["diario"], "--aplicar")
        registrar("segundo intento: YA_CERRADO, sin cambios en Cloud",
                  codigo == 0 and otra and otra["estado"] == "YA_CERRADO" and worker.version() == version and worker.vigentes() == vig,
                  otra or err[-800:])

        # 5. B alinea y ve la guía una sola vez.
        worker.avanzar(11 * 60)
        turno_b, linea = equipo(env["b"], "turno", str(raiz["b"]))
        registrar("B trabaja tras la recuperación: alinea lo recuperado", turno_b is not None
                  and sorted(turno_b["resumen"]["restaurados"]) == sorted([DATASET, envio_a, auditoria])
                  and turno_b["resumen"]["diarios_abiertos"] == [], turno_b or linea)
        registrar("la guía de A está una sola vez en el dataset de B", guias(raiz["b"] / DATASET).count("900001") == 1,
                  guias(raiz["b"] / DATASET))

        # 6. Versión posterior: E escribe y muere; B confirma otra guía; recuperar E se bloquea.
        shutil.copytree(raiz["b"], raiz["e"])
        worker.avanzar(11 * 60)
        proceso = equipo(env["e"], "trabajar", str(raiz["e"]), "900003", esperar=False)
        linea = proceso.stdout.readline().strip()
        registrar("E escribe bajo lease", linea.startswith("ESCRITO "), linea or proceso.stderr.read()[-1500:])
        e = json.loads(linea.split(" ", 1)[1]) if linea.startswith("ESCRITO ") else {}
        matar(proceso)
        shutil.rmtree(dirs["e"])
        worker.avanzar(11 * 60)
        turno_b, linea = equipo(env["b"], "turno_dataset", str(raiz["b"]), "900004")
        registrar("B confirma después otra guía (versión posterior del dataset)", turno_b is not None, linea)
        posterior, version = worker.vigentes()[DATASET], worker.version()
        worker.avanzar(60)
        codigo, bloqueo, err = cli(env["b"], "--raiz-atlas", str(raiz["b"]), "--recuperar-turno", e.get("diario", ""), "--aplicar")
        registrar("recuperar E se bloquea por VERSION_POSTERIOR (código 3)", codigo == 3 and bloqueo and bloqueo["estado"] == "BLOQUEADO"
                  and {"codigo": "VERSION_POSTERIOR", "rutas": [DATASET]} in bloqueo["bloqueos"], bloqueo or err[-1500:])
        registrar("Cloud intacta tras el bloqueo y el diario de E sigue disponible",
                  worker.vigentes()[DATASET] == posterior and worker.version() == version and worker.vigentes()[e["diario"]] == e["sha256"])
        registrar("la guía de E no entró al dataset de B", "900003" not in guias(raiz["b"] / DATASET))
    finally:
        worker.cerrar()
        (SALIDA / "validacion.json").write_text(json.dumps(CHECKS, ensure_ascii=False, indent=2), encoding="utf-8")
    fallas = [c for c in CHECKS if not c["ok"]]
    print(f"{len(CHECKS) - len(fallas)}/{len(CHECKS)} checks aprobados", flush=True)
    return 1 if fallas else 0


if __name__ == "__main__":
    raise SystemExit(main())
