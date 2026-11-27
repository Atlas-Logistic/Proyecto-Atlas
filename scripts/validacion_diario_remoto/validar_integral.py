"""Validación integral P0.6 (P0.1-P0.5) con componentes REALES. SOLO PRUEBA.

Dos instalaciones aisladas (X, Y), cada una con: Motor = clon git real
(origin local de prueba, nunca GitHub) con .venv del Motor instalado;
Desktop = copia del Atlas Viajes instalado (Electron real, inspeccionado por
CDP); raíz publicada D ("Drive", protegida por la guardia como G:) y raíz de
trabajo L; LOCALAPPDATA propio. Worker b28d594 real sobre D1/R2 en memoria
con métricas. PULL real (sincronizar_mobile_cloud.py) con OCR RapidOCR real,
B1 real desde la ventana de Desktop. Datos 100 % sintéticos (MBTMARCA).

  python validar_integral.py <cloud_dir> <salida_dir> <desktop_base> <paquetes_dir>

<desktop_base> = copia del Atlas Viajes instalado; <paquetes_dir>/{v2,v3} =
resources de prueba (v2 válida con título "[P0.6 v2]", v3 rota).
"""
from __future__ import annotations

import base64
import csv
import hashlib
import io
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import validar as v  # noqa: E402  (argv: <cloud_dir> <salida_dir> ...)
import validar_pull as vp  # noqa: E402
import mundo_mbt  # noqa: E402

DESKTOP_BASE = Path(sys.argv[3])
PAQUETES = Path(sys.argv[4])
VENV = Path(r"C:\Atlas\Proyecto-Atlas\.venv")
RAPIDOCR = Path(os.environ.get("LOCALAPPDATA", "")) / "Atlas" / "runtime" / "rapidocr" / "Scripts" / "python.exe"
RAMA = "prueba/p0-integral"
DATASET = v.DATASET
CDP = Path(__file__).with_name("cdp.mjs")
METRICAS: dict = {}


def git(cwd: Path, *args: str) -> str:
    r = subprocess.run(["git", "-c", "user.name=prueba", "-c", "user.email=prueba@example.invalid", "-c", "core.autocrlf=false",
                        *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8")
    if r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {r.stderr}")
    return r.stdout.strip()


def borrar(ruta: Path) -> None:
    """rmtree que nunca entra en una junction (la .venv del Motor instalado)."""
    if not ruta.exists():
        return
    for raiz, dirs, _archivos in os.walk(ruta):
        for d in list(dirs):
            p = Path(raiz) / d
            if os.path.isjunction(p):
                os.rmdir(p)
                dirs.remove(d)

    def escribible(funcion, p, _exc):  # objetos git de sólo lectura
        os.chmod(p, 0o666)
        funcion(p)
    shutil.rmtree(ruta, onexc=escribible)


def sha(ruta: Path) -> str | None:
    return hashlib.sha256(ruta.read_bytes()).hexdigest() if ruta.is_file() else None


def filas(datos: bytes) -> list[dict]:
    csv.field_size_limit(10 ** 9)
    return list(csv.DictReader(io.StringIO(datos.decode("utf-8-sig"), newline=""), delimiter=";"))


def metricas(worker) -> dict:
    import urllib.request
    with urllib.request.urlopen(f"{worker.url}/__prueba/metricas", timeout=30, context=worker.ssl) as r:
        return json.loads(r.read())


def delta(antes: dict, despues: dict) -> dict:
    solicitudes = {k: despues["solicitudes"].get(k, 0) - antes["solicitudes"].get(k, 0) for k in despues["solicitudes"]}
    r2 = {p: {c: despues["r2"].get(p, {}).get(c, 0) - antes["r2"].get(p, {}).get(c, 0) for c in ("objetos", "bytes")}
          for p in set(despues["r2"]) | set(antes["r2"])}
    return {"solicitudes_total": sum(solicitudes.values()), "solicitudes": {k: n for k, n in solicitudes.items() if n},
            "bytes_entrada": despues["bytes_entrada"] - antes["bytes_entrada"],
            "bytes_salida": despues["bytes_salida"] - antes["bytes_salida"], "r2": r2,
            "d1_filas": {t: despues["d1_filas"][t] - antes["d1_filas"].get(t, 0) for t in despues["d1_filas"]}}


class Medir:
    def __init__(self, worker, nombre: str):
        self.worker, self.nombre = worker, nombre

    def __enter__(self):
        self.antes = metricas(self.worker)
        self.t = time.monotonic()
        return self

    def __exit__(self, *_):
        METRICAS[self.nombre] = {**delta(self.antes, metricas(self.worker)), "segundos": round(time.monotonic() - self.t, 1)}


class Instalacion:
    def __init__(self, nombre: str, worker, origen: Path, commit: str):
        self.nombre, self.worker = nombre, worker
        self.dir = v.MUNDO / f"pc-{nombre}"
        self.motor, self.app = self.dir / "motor", self.dir / "app"
        self.D, self.L, self.local = self.dir / "Drive" / "Atlas", self.dir / "Trabajo" / "Atlas", self.dir / "local"
        git(v.MUNDO, "clone", "-q", "--shared", str(origen), str(self.motor))
        git(self.motor, "checkout", "-q", "-B", "instalado", commit)
        subprocess.run(["cmd", "/c", "mklink", "/J", str(self.motor / ".venv"), str(VENV)], capture_output=True, check=True)
        shutil.copytree(DESKTOP_BASE, self.app)
        (self.local / "Atlas").mkdir(parents=True)
        self.config_desktop = self.dir / "config_desktop.json"
        self.config_desktop.write_text(json.dumps({"carpetaProyectoPython": str(self.motor)}), encoding="utf-8")
        self.config_operacion = self.local / "Atlas" / "desktop_operacion.json"
        self.config_operacion.write_text(json.dumps({
            "habilitada": True, "autorizada": True, "raiz": str(self.D), "proyecto": str(self.motor),
            "modo_escritor": "lease_cloud", "python": str(VENV / "Scripts" / "python.exe"),
            "rapidocr_python": str(RAPIDOCR), "ocr_provider": "rapidocr"}), encoding="utf-8")
        self.env = v.entorno(worker, self.local)
        self.env.update(PYTHONPATH=str(self.motor), ATLAS_EXCLUSION_RAICES=str(self.D), ATLAS_EXCLUSION_LOCAL="exigir",
                        ATLAS_OCR_PROVIDER="rapidocr", ATLAS_RAPIDOCR_PYTHON=str(RAPIDOCR),
                        ATLAS_OPERACION_CONFIG=str(self.config_operacion))
        self.desktop = None

    # --------------------------------------------------------- Motor
    def py(self, *args: str, timeout: int = 1800) -> tuple[int, dict | None, str]:
        r = subprocess.run([str(VENV / "Scripts" / "python.exe"), "-B", *args], cwd=self.motor, env=self.env,
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
        texto = r.stdout
        inicio = texto.find("{")
        datos = None
        if inicio >= 0:
            try:
                datos = json.loads(texto[inicio:])
            except ValueError:
                lineas = [l for l in texto.splitlines() if l.startswith("{")]
                try:
                    datos = json.loads(lineas[-1]) if lineas else None
                except ValueError:
                    datos = None
        return r.returncode, datos, (r.stdout + r.stderr)[-3000:]

    def preparar(self):
        return self.py("-m", "atlas_core.estado_confirmado", "--raiz-atlas", str(self.L), "--preparar-raiz-trabajo", str(self.D))

    def pull(self):
        # Como la tarea programada: con la raíz configurada (la publicada) -> se redirige a la de trabajo.
        return self.py("sincronizar_mobile_cloud.py", "--raiz-atlas", str(self.D))

    def iniciar_atlas(self):
        """Lo que hace scripts/iniciar_atlas.ps1 antes de abrir Desktop."""
        return self.py("actualizar_atlas.py", "--desktop-recursos", str(self.app / "resources"),
                       "--desktop-exe", str(self.app / "Atlas Viajes.exe"), "--raiz-atlas", str(self.D),
                       "--proceso-desktop", "AtlasPruebaInexistente.exe", timeout=900)

    # ------------------------------------------------------- Desktop
    def abrir_desktop(self) -> bool:
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            self.puerto = s.getsockname()[1]
        env = {**self.env, "ATLAS_DATA_DIR": str(self.D), "ATLAS_USER_DATA_PATH": str(self.dir / "userdata"),
               "ATLAS_CONFIG_PATH": str(self.config_desktop), "ATLAS_PYTHON": str(VENV / "Scripts" / "python.exe")}
        env.pop("ELECTRON_RUN_AS_NODE", None)
        env.pop("PYTHONPATH", None)
        self.registro_desktop = open(self.dir / f"desktop_{int(time.time())}.log", "wb")
        self.desktop = subprocess.Popen([str(self.app / "Atlas Viajes.exe"), f"--remote-debugging-port={self.puerto}"],
                                        env=env, stdout=self.registro_desktop, stderr=subprocess.STDOUT)
        limite = time.monotonic() + 90
        while time.monotonic() < limite:
            if self.cdp("document.readyState").get("valor") == "complete" and self.contador_viajes() is not None:
                return True
            time.sleep(1)
        return False

    def cdp(self, expresion: str) -> dict:
        r = subprocess.run(["node", str(CDP), str(self.puerto), expresion], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=600)
        try:
            return json.loads(r.stdout.strip().splitlines()[-1])
        except (ValueError, IndexError):
            return {"error": (r.stdout + r.stderr)[-500:]}

    def contador_viajes(self) -> int | None:
        texto = self.cdp("document.body ? document.body.innerText.slice(0, 300) : ''").get("valor") or ""
        m = re.search(r"·\s*(\d+)\s+viajes", texto)
        return int(m.group(1)) if m else None

    def refrescar(self) -> None:
        self.cdp("[...document.querySelectorAll('button')].find(b => b.textContent.includes('Refrescar datos'))?.click()")
        time.sleep(6)

    def datos_desktop(self) -> str:
        r = self.cdp("window.atlasAPI.cargarLocalRapido().then(r => JSON.stringify(r))")
        return r.get("valor") or ""

    def cerrar_desktop(self) -> None:
        if self.desktop is not None:
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(self.desktop.pid)], capture_output=True)
            try:
                self.desktop.wait(timeout=30)
            except subprocess.TimeoutExpired:
                pass
            self.registro_desktop.close()
            self.desktop = None


def drive_coherente(worker, D: Path) -> dict:
    """Ninguna escritura operacional directa en Drive: cada archivo custodiado
    de la raíz publicada es exactamente el confirmado en Cloud, y no hay
    archivos operacionales fuera de la marca."""
    from atlas_core.estado_confirmado import es_ruta_custodia, rastreable
    vig = {r: s for r, s in worker.vigentes().items() if not es_ruta_custodia(r)}
    distintos = sorted(r for r, s in vig.items() if sha(D.joinpath(*r.split("/"))) != s)
    fuera = sorted(p.relative_to(D).as_posix() for p in D.rglob("*") if p.is_file()
                   and rastreable(p.relative_to(D).as_posix()) and p.relative_to(D).as_posix() not in vig)
    return {"distintos": distintos[:10], "fuera_de_la_marca": fuera[:10], "ok": not distintos and not fuera}


def main() -> int:
    if v.MUNDO.exists():
        borrar(v.MUNDO)
    v.MUNDO.mkdir(parents=True)
    worker = v.Worker(usuarios=[vp.CHOFER])
    X = Y = None
    try:
        assert worker.url.startswith("https://127.0.0.1:")
        # ---------------------------------------------- E0 preparación
        c1 = git(v.MOTOR, "rev-parse", "HEAD")
        origen, taller = v.MUNDO / "origin.git", v.MUNDO / "taller"
        git(v.MUNDO, "clone", "-q", "--bare", "--shared", str(v.MOTOR), str(origen))
        git(v.MUNDO, "clone", "-q", "--shared", str(origen), str(taller))
        git(taller, "checkout", "-q", "-b", RAMA, c1)
        (taller / "docs" / "P0_6_VERSION_PRUEBA.md").parent.mkdir(exist_ok=True)
        (taller / "docs" / "P0_6_VERSION_PRUEBA.md").write_text("versión de prueba P0.6\n", encoding="utf-8")
        git(taller, "add", "-A")
        git(taller, "commit", "-q", "-m", "prueba P0.6: versión C2")
        c2 = git(taller, "rev-parse", "HEAD")
        git(taller, "push", "-q", "origin", RAMA)
        X, Y = Instalacion("x", worker, origen, c1), Instalacion("y", worker, origen, c1)
        mundo_mbt.construir(X.D, ["900001", "900002"])
        shutil.copytree(X.D, Y.D)  # Drive
        for pc in (X, Y):
            codigo, r, salida = pc.preparar()
            v.registrar(f"{pc.nombre.upper()}: raíz de trabajo preparada fuera de Drive", codigo == 0 and r and r["copiada"], r or salida)
        codigo, r, salida = X.py("-m", "atlas_core.estado_confirmado", "--raiz-atlas", str(X.D), "--sembrar")
        v.registrar("X siembra la custodia (recibe la raíz publicada, opera en la de trabajo)",
                    codigo == 0 and r and r.get("sembrado"), r or salida)

        # ---------------------------------------- E1 ingesta Mobile completa
        vp.jpeg = lambda marcador: mundo_mbt.imagen_guia(marcador.split("-")[-1])
        v.registrar("Mobile envía E1 (guía sintética 900101)", vp.enviar_mobile(worker, "envio-900101") == 200)
        with Medir(worker, "pull_ingesta_1_guia_ocr"):
            codigo, r1, salida = X.pull()
        vig = worker.vigentes()
        datos = vp.descargar(worker, vig[DATASET])
        transportes = [f["numero_transporte"] for f in filas(datos)]
        v.registrar("PULL real de X con OCR RapidOCR: E1 procesado y confirmado", codigo == 0 and r1
                    and "envio-900101" in (r1.get("confirmados") or []) and "0000900101" in transportes,
                    (r1 or {}).get("confirmados") if r1 else salida)
        estado = json.loads((X.D / "operacion/actual/estado_operacion.json").read_text(encoding="utf-8"))
        reporte = X.D / estado["reporte_vigente"] / "viajes.csv"
        v.registrar("Drive de X: dataset y reporte vigente publicados con E1",
                    sha(X.D / DATASET) == vig[DATASET] and reporte.is_file() and "0000900101" in reporte.read_text(encoding="utf-8-sig"))
        shutil.copytree(X.D, Y.D, dirs_exist_ok=True)  # Drive replica
        v.registrar("Desktop real de Y abre leyendo Drive", Y.abrir_desktop(), Y.dir.name)
        v.registrar("Desktop de Y muestra la guía Mobile (carga y contador visible)",
                    "0000900101" in Y.datos_desktop() and Y.contador_viajes() == 3, Y.contador_viajes())
        for pc in (X, Y):
            dc = drive_coherente(worker, pc.D)
            v.registrar(f"Drive de {pc.nombre.upper()} = estado confirmado (E1)", dc["ok"], dc)

        # ------------------ E2 Desktop sólo confirmado + pérdida del escritor
        from validar_lease import leer, popen
        a = popen(X.env, "trabajar", str(X.L), "900102")
        escrito = leer(a, "ESCRITO")
        v.registrar("X ingesta 900102 en su turno (sin confirmar)", escrito is not None and escrito["pendientes"] == [])
        v.registrar("Desktop real de X abre leyendo Drive", X.abrir_desktop())
        v.registrar("Desktop de X no ve el turno sin confirmar (900102 sólo en la raíz de trabajo)",
                    "900102" not in X.datos_desktop() and "900102" in (X.L / DATASET).read_text(encoding="utf-8-sig")
                    and "900102" not in (X.D / DATASET).read_text(encoding="utf-8-sig"))
        X.cerrar_desktop()
        v.matar(a)
        shutil.copytree(X.D, Y.D, dirs_exist_ok=True)
        borrar(X.dir)
        v.registrar("X eliminado por completo (Motor, Desktop, Drive, raíz de trabajo y LOCALAPPDATA)", not X.dir.exists())
        Y.refrescar()
        v.registrar("Desktop de Y tampoco ve el turno perdido", "900102" not in Y.datos_desktop() and Y.contador_viajes() == 3)

        # ------------------- E3 recuperación automática + continuidad en Y
        v.registrar("Mobile envía E2 (900103)", vp.enviar_mobile(worker, "envio-900103") == 200)
        worker.avanzar(11 * 60)
        with Medir(worker, "pull_recuperacion_y_1_guia_ocr"):
            codigo, r2, salida = Y.pull()
        rec = (r2 or {}).get("recuperacion_turnos", {})
        v.registrar("PULL real de Y recupera solo el turno de X", codigo == 0 and
                    [x["diario"] for x in rec.get("recuperados", [])] == [escrito["diario"]], rec or salida)
        lista = filas(vp.descargar(worker, worker.vigentes()[DATASET]))
        v.registrar("Cloud: 900102 una vez, E2 procesado, sin duplicados",
                    [f["numero_guia"] for f in lista].count("900102") == 1
                    and [f["numero_transporte"] for f in lista].count("0000900103") == 1
                    and len({f["archivo"] for f in lista}) == len(lista), [f["numero_guia"] for f in lista])
        Y.refrescar()
        datos_y = Y.datos_desktop()
        v.registrar("Desktop de Y muestra lo recuperado y lo nuevo", "900102" in datos_y and "0000900103" in datos_y
                    and Y.contador_viajes() == 5, Y.contador_viajes())
        worker.avanzar(60)
        with Medir(worker, "pull_ocioso"):
            codigo, r3, salida = Y.pull()
        v.registrar("PULL siguiente de Y sin nada que hacer (continuidad)", codigo == 0
                    and (r3 or {}).get("recuperacion_turnos") == {"recuperados": [], "en_revision": [], "omitidos": 0}, r3 or salida)
        dc = drive_coherente(worker, Y.D)
        v.registrar("Drive de Y = estado confirmado (E3)", dc["ok"], dc)

        # ----------------------------------- E4 corrección B1 desde Desktop
        worker.avanzar(60)
        with Medir(worker, "correccion_b1_desktop"):
            p = Y.cdp("window.atlasAPI.b1Atender('p06-peso', 'En la guía 900001 el peso correcto es 12.450 kg')")
            c = Y.cdp("window.atlasAPI.b1Atender('p06-peso', 'sí')")
        pv, cv = p.get("valor") or {}, c.get("valor") or {}
        peso = next(f["peso_kg"] for f in filas(vp.descargar(worker, worker.vigentes()[DATASET])) if f["numero_guia"] == "900001")
        v.registrar("B1 desde la ventana real: preview y confirmación humana ejecutadas en la raíz de trabajo",
                    peso == "12450" and cv.get("ok") is not False, {"preview": str(pv)[:600], "confirmacion": str(cv)[:600], "peso": peso})
        v.registrar("Drive de Y publica la corrección", "12450" in (Y.D / DATASET).read_text(encoding="utf-8-sig")
                    and drive_coherente(worker, Y.D)["ok"])

        # ------------------------------------------ E5 informes y exportación
        Y.refrescar()
        estado = json.loads((Y.D / "operacion/actual/estado_operacion.json").read_text(encoding="utf-8"))
        viajes = (Y.D / estado["reporte_vigente"] / "viajes.csv").read_text(encoding="utf-8-sig")
        v.registrar("informe de viajes vigente en Drive con la corrección y lo recuperado",
                    "12450" in viajes and "900102" in viajes and "0000900103" in viajes)
        # Las exportaciones siguen el filtro de fecha visible: como el operador, "Todo".
        Y.cdp("(() => { const s = document.getElementById('filtro-periodo'); s.value = 'todo'; "
              "s.dispatchEvent(new Event('change', {bubbles: true})); return s.value; })()")
        time.sleep(3)
        xlsx = Y.cdp("window.generarExcelPreactivacion().then(b => { let s=''; const u=new Uint8Array(b); "
                     "for (let i=0;i<u.length;i+=32768) s+=String.fromCharCode.apply(null,u.subarray(i,i+32768)); return btoa(s); })")
        texto_xlsx = ""
        if xlsx.get("valor"):
            import zipfile
            with zipfile.ZipFile(io.BytesIO(base64.b64decode(xlsx["valor"]))) as zf:  # xlsx = zip de XML
                texto_xlsx = " ".join(zf.read(n).decode("utf-8", "replace") for n in zf.namelist() if n.endswith(".xml"))
        claves = ("0000900001", "0000900002", "0000900102", "0000900101", "0000900103", "12450", "12.450")
        transportes = ("0000900001", "0000900002", "0000900102", "0000900101", "0000900103")
        v.registrar("exportación Excel real desde Desktop: los 5 viajes confirmados y el peso corregido",
                    all(t in texto_xlsx for t in transportes) and ("12450" in texto_xlsx or "12.450" in texto_xlsx),
                    xlsx.get("error") or {k: k in texto_xlsx for k in claves})
        html = Y.cdp("construirLibroMBTParaExportacion().then(e => e ? window.AtlasExportacionMBTPDF.htmlDesdeLibroMBT(e.libroMBT) : '')")
        texto_html = html.get("valor") or ""
        # El informe MBT no tiene columna de peso (Fecha, Origen, Chofer, Guía, Cliente, Transporte, Destino...).
        v.registrar("informe PDF MBT (HTML de impresión): los 5 viajes confirmados, con la guía recuperada",
                    all(t in texto_html for t in transportes) and ">900102<" in texto_html,
                    html.get("error") or {k: k in texto_html for k in claves})
        (v.SALIDA / "exportacion_mbt.html").write_text(texto_html, encoding="utf-8")
        if xlsx.get("valor"):
            (v.SALIDA / "exportacion.xlsx").write_bytes(base64.b64decode(xlsx["valor"]))
        Y.cerrar_desktop()

        # ------------------------------ E6 actualización automática real
        worker.avanzar(60)
        codigo, r, salida = Y.py("actualizar_atlas.py", "--publicar", "--version", "p06-2", "--rama", RAMA, "--commit", c2,
                                 "--desktop-recursos", str(PAQUETES / "v2"), "--nivel-minimo", "1", "--raiz-atlas", str(Y.D))
        v.registrar("versión p06-2 publicada (Motor C2 + Desktop v2)", codigo == 0 and r and r.get("publicada") == "p06-2", r or salida)
        asar_v2 = sha(PAQUETES / "v2" / "app.asar")
        with Medir(worker, "inicio_con_actualizacion"):
            codigo, r, salida = Y.iniciar_atlas()
        arranque = ((r or {}).get("salud") or {}).get("desktop_arranque") or {}
        v.registrar("inicio de Y: ACTUALIZADA con arranque real de Electron verificado",
                    r and r.get("estado") == "ACTUALIZADA" and arranque.get("pagina") == "atlas_viajes.html", r or salida)
        v.registrar("Y en Motor C2 + Desktop v2", git(Y.motor, "rev-parse", "HEAD") == c2 and sha(Y.app / "resources" / "app.asar") == asar_v2)
        v.registrar("Desktop v2 abre y muestra los datos", Y.abrir_desktop() and "P0.6 v2" in (Y.cdp("document.title").get("valor") or "")
                    and "900102" in Y.datos_desktop())
        Y.cerrar_desktop()
        worker.avanzar(60)
        codigo, r, salida = Y.py("actualizar_atlas.py", "--publicar", "--version", "p06-3", "--rama", RAMA, "--commit", c2,
                                 "--desktop-recursos", str(PAQUETES / "v3"), "--nivel-minimo", "1", "--raiz-atlas", str(Y.D))
        v.registrar("versión p06-3 publicada (Desktop roto)", codigo == 0 and r and r.get("publicada") == "p06-3", r or salida)
        codigo, r, salida = Y.iniciar_atlas()
        v.registrar("inicio de Y: Desktop roto no abre -> REVERTIDA", r and r.get("estado") == "REVERTIDA"
                    and "Desktop" in (r.get("detalle") or ""), r or salida)
        v.registrar("Y sigue en C2 + Desktop v2", git(Y.motor, "rev-parse", "HEAD") == c2 and sha(Y.app / "resources" / "app.asar") == asar_v2)
        v.registrar("Desktop abre normalmente tras la reversión", Y.abrir_desktop() and "900102" in Y.datos_desktop())
        Y.cerrar_desktop()

        # ------------------------------------- E7 sin escrituras en Drive
        dc = drive_coherente(worker, Y.D)
        v.registrar("Drive final = estado confirmado; nada operacional fuera de la marca", dc["ok"], dc)
        codigo, r, salida = Y.py("-c", f"import atlas_core; open(r'{Y.D / 'operacion' / 'actual' / 'intruso.csv'}', 'w').write('x')")
        v.registrar("un proceso del Motor no puede escribir directo en Drive (guardia)",
                    codigo != 0 and "EscrituraSinTurno" in salida and not (Y.D / "operacion/actual/intruso.csv").exists(), salida[-300:])
    finally:
        for pc in (X, Y):
            if pc is not None:
                pc.cerrar_desktop()
        METRICAS["final"] = metricas(worker)
        worker.cerrar()
        (v.SALIDA / "validacion_integral.json").write_text(json.dumps(v.CHECKS, ensure_ascii=False, indent=2), encoding="utf-8")
        (v.SALIDA / "metricas_cloud.json").write_text(json.dumps(METRICAS, ensure_ascii=False, indent=2), encoding="utf-8")
    fallas = [c for c in v.CHECKS if not c["ok"]]
    print(f"{len(v.CHECKS) - len(fallas)}/{len(v.CHECKS)} checks aprobados", flush=True)
    return 1 if fallas else 0


if __name__ == "__main__":
    raise SystemExit(main())
