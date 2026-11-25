"""Validación del ALTA INTEGRAL de una empresa (alta_empresa.py), 25/11/2026.

Prueba sólo el procedimiento nuevo y su aislamiento (las 58 verificaciones de
validar.py no se repiten), en un mundo sintético local:

  * MBT ficticia con datos y usuario Mobile propio; Worker real en proceso
    (test/servidor_local.js del repositorio Cloud) sobre SQLite en memoria.
  * Raíces tratadas como compartidas (ATLAS_EXCLUSION_RAICES): toda escritura
    del alta debe ir con turno/escritor, como en Drive.
  * Transportes Andes (ficticia): revisión, alta con el Worker aún sin su token
    (PENDIENTE), paso humano (secreto del Worker), repetición que completa,
    repetición idempotente, uso real (login, envío, PULL) y casos rechazados.
  * Tercera empresa: el alta de la N-ésima empresa funciona.

    python scripts/validacion_multiempresa/validar_alta.py <mundo> <checkout cloud> <checkout desktop>

Nunca toca G:, el LOCALAPPDATA ni el registro reales, Cloudflare ni MBT real.
Escribe <mundo>/../evidencia/validacion_alta.json; sale 1 si algo falla.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

MOTOR = Path(__file__).resolve().parents[2]
MUNDO = Path(sys.argv[1]).resolve()
CLOUD = Path(sys.argv[2]).resolve()
DESKTOP = Path(sys.argv[3]).resolve()
EVIDENCIA = MUNDO.parent / "evidencia"
PY = sys.executable

DRIVE = MUNDO / "drive"
MBT = DRIVE / "Atlas"
EMPRESAS = DRIVE / "Atlas_empresas"
LOCAL = MUNDO / "LocalAppData"
CREDENCIALES = MUNDO / "credenciales_prueba.json"
CLOUD_MBT, TOKEN_MBT = "empresa-prueba-javier", "token-motor-mbt-ficticio"
ANDES_ID, ANDES_NOMBRE, ANDES_CLOUD = "andes-prueba", "Transportes Andes (ficticia)", "cloud-andes-prueba"
ANDES = EMPRESAS / ANDES_ID
CORD_ID = "cordillera-prueba"
MARCA = {"mbt": "MBTMARCA", ANDES_ID: "ANDESMARCA"}
CLAVES = {"andes.luis": "clave-andes-luis-1", "andes.ana": "clave-andes-ana-1"}

resultados: list[dict] = []


def registrar(etapa: str, prueba: str, ok: bool, detalle: object = "") -> None:
    resultados.append({"etapa": etapa, "prueba": prueba, "ok": bool(ok), "detalle": detalle})
    print(("OK   " if ok else "FALLA") + f" [{etapa}] {prueba}" + ("" if ok else f" :: {str(detalle)[:700]}"), flush=True)


def base_env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("ATLAS_", "OPENROUTER", "CLOUD_"))}
    env.update(LOCALAPPDATA=str(LOCAL), PYTHONIOENCODING="utf-8", PYTHONUTF8="1", SSL_CERT_FILE=str(MUNDO / "tls" / "cert.pem"),
               # Como en Drive: escrituras sin turno se rechazan en todas las raíces.
               ATLAS_EXCLUSION_RAICES=os.pathsep.join(str(r) for r in (MBT, ANDES, EMPRESAS / CORD_ID, EMPRESAS / "pirata")))
    return env


def env_mbt() -> dict[str, str]:
    env = base_env()
    env.update(PYTHONPATH=str(MOTOR), ATLAS_DATA_DIR=str(MBT), ATLAS_CLOUD_MOTOR_TOKEN=TOKEN_MBT)
    return env


def env_empresa(empresa: str, raiz: Path, **extra) -> dict[str, str]:
    env = base_env()
    token = json.loads(CREDENCIALES.read_text(encoding="utf-8")).get(f"ATLAS_CLOUD_MOTOR_TOKEN__{empresa.upper().replace('-', '_')}", "")
    env.update(PYTHONPATH=str(MOTOR), ATLAS_DATA_DIR=str(raiz), ATLAS_EMPRESA_ID=empresa, ATLAS_RAIZ_MBT=str(MBT))
    env[f"ATLAS_CLOUD_MOTOR_TOKEN__{empresa.upper().replace('-', '_')}"] = token
    env.update(extra)
    return env


def correr(cmd: list[str], env: dict, entrada: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, input=entrada, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          env=env, cwd=MOTOR, timeout=900)


def inventario(raiz: Path, excluir: tuple[Path, ...] = ()) -> dict[str, str]:
    if not raiz.exists():
        return {}
    return {p.relative_to(raiz).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(raiz.rglob("*")) if p.is_file() and not any(p.is_relative_to(x) for x in excluir)}


def buscar(raiz: Path, marcador: str, excluir: tuple[Path, ...] = ()) -> list[str]:
    formas = (marcador.encode("utf-8"), marcador.encode("utf-16-le"))
    return [str(p.relative_to(raiz)) for p in (raiz.rglob("*") if raiz.exists() else [])
            if p.is_file() and not any(p.is_relative_to(x) for x in excluir) and any(f in p.read_bytes() for f in formas)]


# ------------------------------------------------------------------ mundo
def preparar() -> None:
    if MUNDO.exists():
        shutil.rmtree(MUNDO)
    cat = MBT / "catalogos_privados"
    cat.mkdir(parents=True)
    (MBT / "operacion" / "actual").mkdir(parents=True)
    LOCAL.mkdir(parents=True)
    (cat / "choferes.json").write_text(json.dumps({"123456785": {"nombre": "LUIS MBTMARCA REYES", "activo": True}}), encoding="utf-8")
    (cat / "usuarios_mobile.json").write_text(json.dumps({"schema_version": 1, "usuarios": {
        "mbt.luis": {"chofer_id": "123456785", "password_hash": "x"}}}), encoding="utf-8")
    (cat / "vehiculos.json").write_text(json.dumps({"version": 1, "vehiculos": [], "nota": "MBTMARCA"}), encoding="utf-8")
    (MBT / "operacion" / "actual" / "estado.json").write_text(json.dumps({"marcador": "MBTMARCA"}), encoding="utf-8")
    (LOCAL / "Atlas").mkdir()
    (LOCAL / "Atlas" / "desktop_operacion.json").write_text(json.dumps({"raiz": str(MBT), "nota": "MBTMARCA"}), encoding="utf-8")
    # Catálogos iniciales de Andes (los aporta quien da el alta).
    iniciales = MUNDO / "iniciales_andes"
    iniciales.mkdir()
    (iniciales / "choferes.json").write_text(json.dumps({"116405008": {"nombre": "ANA ANDESMARCA SOTO", "activo": True}}), encoding="utf-8")
    (iniciales / "vehiculos.json").write_text(json.dumps({"version": 1, "vehiculos": [], "nota": "ANDESMARCA"}), encoding="utf-8")
    plan("andes", ANDES_ID, ANDES_NOMBRE, ANDES_CLOUD, [
        {"usuario": "andes.luis", "rut": "12.345.678-5", "nombre": "LUIS ANDESMARCA REYES"},
        {"usuario": "andes.ana", "rut": "11.640.500-8", "nombre": "ANA ANDESMARCA SOTO"}], iniciales=iniciales)
    tls = MUNDO / "tls"
    tls.mkdir()
    openssl = next(p for p in (shutil.which("openssl"), r"C:\Program Files\Git\usr\bin\openssl.exe") if p and Path(p).is_file())
    subprocess.run([openssl, "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1", "-subj", "/CN=127.0.0.1",
                    "-addext", "subjectAltName=IP:127.0.0.1", "-keyout", str(tls / "key.pem"), "-out", str(tls / "cert.pem")],
                   check=True, capture_output=True)


def plan(nombre_archivo: str, empresa: str, nombre: str, cloud: str, choferes: list, iniciales: Path | None = None) -> Path:
    ruta = MUNDO / f"plan_{nombre_archivo}.json"
    datos = {"version": 1, "empresa_id": empresa, "nombre": nombre, "cloud_id": cloud, "choferes_mobile": choferes}
    if iniciales:
        datos["catalogos_iniciales"] = str(iniciales)
    ruta.write_text(json.dumps(datos, ensure_ascii=False), encoding="utf-8")
    return ruta


# ----------------------------------------------------------------- Worker
class Worker:
    def __init__(self, tokens: dict[str, str]) -> None:
        import ssl
        self.ssl = ssl.create_default_context(cafile=str(MUNDO / "tls" / "cert.pem"))
        config = MUNDO / f"worker_{uuid.uuid4().hex[:6]}.json"
        config.write_text(json.dumps({
            "env": {"CLOUD_MOTOR_AUTH_SECRET": TOKEN_MBT, "CLOUD_MOTOR_EMPRESA_ID": CLOUD_MBT,
                    "CLOUD_MOBILE_AUTH_SECRET": "secreto-mobile-ficticio", "CLOUD_MOTOR_TOKENS_JSON": json.dumps(tokens)},
            "usuarios": [{"usuario_id": "u-mbt-1", "empresa_id": CLOUD_MBT, "chofer_id": "123456785", "nombre_usuario": "mbt.luis",
                          "nombre_chofer": "LUIS MBTMARCA REYES", "password": "clave-mbt-1"}],
            "tls": {"cert": str(MUNDO / "tls" / "cert.pem"), "key": str(MUNDO / "tls" / "key.pem")}}), encoding="utf-8")
        self.p = subprocess.Popen(["node", str(CLOUD / "test" / "servidor_local.js"), str(config)], stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, text=True, cwd=CLOUD)
        linea = self.p.stdout.readline().strip()
        if not linea.startswith("LISTO "):
            raise RuntimeError("Worker local no inició: " + linea + self.p.stderr.read()[-1500:])
        self.url = f"https://127.0.0.1:{linea.split()[1]}"

    def pedir(self, metodo, ruta, token=None, cuerpo=None, tipo="application/json"):
        h = {"content-type": tipo, **({"authorization": f"Bearer {token}"} if token else {})}
        req = urllib.request.Request(self.url + ruta, data=cuerpo, method=metodo, headers=h)
        try:
            with urllib.request.urlopen(req, timeout=30, context=self.ssl) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    def json(self, metodo, ruta, token=None, cuerpo=None):
        s, b = self.pedir(metodo, ruta, token, None if cuerpo is None else json.dumps(cuerpo).encode())
        try:
            return s, json.loads(b or b"null")
        except ValueError:
            return s, b.decode("utf-8", "replace")

    def tabla(self, nombre):
        return self.json("GET", f"/__prueba/tabla/{nombre}")[1]

    def cerrar(self):
        self.p.kill()


def alta(w: Worker, plan_ruta: Path, *opciones: str, claves: list[str] | None = None) -> tuple[int, dict, str]:
    informe = MUNDO / f"informe_{uuid.uuid4().hex[:6]}.json"
    cmd = [PY, "-B", str(MOTOR / "alta_empresa.py"), "--plan", str(plan_ruta), "--raiz-mbt", str(MBT),
           "--credenciales", f"archivo:{CREDENCIALES}", "--cloud-url", w.url, "--cloud-repo", str(CLOUD),
           "--d1", f"local:{w.url}", "--url-login", f"{w.url}/api/mobile/login", "--informe", str(informe), *opciones]
    if claves is not None:
        cmd.append("--password-stdin")
    r = correr(cmd, base_env(), entrada="\n".join(claves or []) + "\n")
    datos = json.loads(informe.read_text(encoding="utf-8")) if informe.is_file() else {}
    pasos = {p["paso"]: p for p in datos.get("pasos", [])}
    return r.returncode, pasos, r.stdout + r.stderr


def estados(pasos: dict) -> dict:
    return {k: v.get("estado") for k, v in pasos.items()}


def zonas_mbt() -> dict:
    return {"raiz": inventario(MBT), "local": inventario(LOCAL / "Atlas", (LOCAL / "Atlas" / "empresas",))}


# ------------------------------------------------------------------ fases
def fase_revision(w: Worker) -> None:
    antes = inventario(MUNDO, (MUNDO / "evidencia",))
    rc, pasos, salida = alta(w, MUNDO / "plan_andes.json", "--revisar")
    despues = inventario(MUNDO, (MUNDO / "evidencia",))
    nuevos = sorted(set(despues) - set(antes))
    registrar("revision", "--revisar informa el registro pendiente y no escribe nada (sólo su informe)",
              rc == 0 and estados(pasos) == {"registro": "SE_HARIA"} and all(n.startswith("informe_") for n in nuevos)
              and not EMPRESAS.exists() and {k: v for k, v in despues.items() if k in antes} == antes, (rc, estados(pasos), nuevos, salida[-600:]))


def fase_pendiente(w: Worker, mbt_antes: dict) -> dict:
    rc, pasos, salida = alta(w, MUNDO / "plan_andes.json", "--autorizar-pull-horas", "2")
    e = estados(pasos)
    registrar("alta", "sin el token en el Worker: registro, estructura, credencial y PULL hechos; cloud PENDIENTE; resto BLOQUEADO (código 3)",
              rc == 3 and e.get("registro") == e.get("estructura") == e.get("credencial") == "HECHO"
              and e.get("pull-config") == e.get("pull-autorizacion") == "HECHO" and e.get("cloud") == "PENDIENTE"
              and e.get("custodia") == e.get("mobile") == e.get("verificar") == "BLOQUEADO", (rc, e, salida[-1200:]))
    marca = json.loads((ANDES / "catalogos_privados" / "empresa_identidad.json").read_text(encoding="utf-8"))
    registrar("alta", "marca de Andes con su id, nombre y cloud_id",
              marca == {"version": 1, "empresa_id": ANDES_ID, "nombre": ANDES_NOMBRE, "cloud_id": ANDES_CLOUD}, marca)
    choferes = json.loads((ANDES / "catalogos_privados" / "choferes.json").read_text(encoding="utf-8"))
    faltan = [n for n in ("usuarios_mobile.json", "vehiculos.json", "clientes.json", "destinos_maestros.json", "obras_destinos.json",
                          "empresas.json", "plantas.json", "rutas.json") if not (ANDES / "catalogos_privados" / n).is_file()]
    registrar("alta", "estructura: catálogos base completos y catálogos iniciales aportados (choferes, vehículos)",
              not faltan and "ANA ANDESMARCA SOTO" in json.dumps(choferes) and
              "ANDESMARCA" in (ANDES / "catalogos_privados" / "vehiculos.json").read_text(encoding="utf-8"), faltan)
    creds = json.loads(CREDENCIALES.read_text(encoding="utf-8"))
    token = creds.get("ATLAS_CLOUD_MOTOR_TOKEN__ANDES_PRUEBA", "")
    pendiente = json.loads((LOCAL / "Atlas" / "empresas" / ANDES_ID / "alta" / "cloud_motor_token.json").read_text(encoding="utf-8"))
    fragmento = pendiente["fragmento_CLOUD_MOTOR_TOKENS_JSON"]
    registrar("credencial", "token Motor propio (ATLAS_CLOUD_MOTOR_TOKEN__ANDES_PRUEBA) y fragmento sha256→cloud_id sin el token",
              len(token) >= 40 and token != TOKEN_MBT and list(creds) == ["ATLAS_CLOUD_MOTOR_TOKEN__ANDES_PRUEBA"]
              and fragmento == {hashlib.sha256(token.encode()).hexdigest(): ANDES_CLOUD}
              and token not in salida and not buscar(MUNDO, token, (CREDENCIALES,)), {"fragmento": fragmento})
    config = json.loads((LOCAL / "Atlas" / "empresas" / ANDES_ID / "desktop_operacion.json").read_text(encoding="utf-8"))
    tarea = pasos.get("pull-tarea", {})
    argumentos = (tarea.get("plan") or {}).get("Arguments", "") if isinstance(tarea.get("plan"), dict) else ""
    registrar("pull", "configuración PULL en la carpeta local de Andes y plan de tarea propia (-Empresa, deshabilitada)",
              config["raiz"] == str(ANDES) and config["raiz_mbt"] == str(MBT) and config["modo_escritor"] == "lease_cloud"
              and tarea.get("estado") == "OMITIDO" and f'-Empresa "{ANDES_ID}"' in argumentos
              and "empresas\\andes-prueba\\desktop_operacion.json" in argumentos and tarea["plan"]["TaskName"].startswith("Atlas PULL andes-prueba"),
              tarea)
    r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(MOTOR / "scripts" / "pull_pc_nuevo.ps1"),
                        "-Empresa", ANDES_ID, "-Validar"], capture_output=True, text=True, encoding="utf-8", errors="replace",
                       env={**env_empresa(ANDES_ID, ANDES), "ATLAS_RAPIDOCR_PYTHON": PY}, cwd=MOTOR, timeout=300)
    registrar("pull", "pull_pc_nuevo.ps1 -Empresa andes-prueba -Validar acepta la configuración y la autorización creadas por el alta",
              r.returncode == 0 and str(ANDES) in r.stdout.replace("\\\\", "\\") and ANDES_ID in r.stdout, (r.stdout + r.stderr)[-800:])
    registrar("alta", "Cloud no recibió nada de Andes mientras el token no era reconocido",
              not [f for t in ("estado_operativo_marca", "estado_operativo_archivos", "mobile_usuarios_cloud")
                   for f in w.tabla(t) if f.get("empresa_id") == ANDES_CLOUD])
    registrar("aislamiento", "MBT ficticia (raíz y estado local) byte a byte idéntica tras el alta parcial", zonas_mbt() == mbt_antes)
    return fragmento


def fase_completa(w: Worker, mbt_antes: dict) -> None:
    marca_mbt = {m["empresa_id"]: m for m in w.tabla("estado_operativo_marca")}.get(CLOUD_MBT)
    rc, pasos, salida = alta(w, MUNDO / "plan_andes.json", "--autorizar-pull-horas", "2", claves=[CLAVES["andes.luis"], CLAVES["andes.ana"]])
    e = estados(pasos)
    registrar("alta", "repetición tras el paso humano: completa lo pendiente y no rehace lo hecho (código 0)",
              rc == 0 and e.get("registro") == e.get("estructura") == e.get("credencial") == e.get("pull-config") == "YA_ESTABA"
              and e.get("pull-autorizacion") == "YA_ESTABA" and e.get("cloud") == "YA_ESTABA" and e.get("custodia") == "HECHO"
              and e.get("mobile:andes.luis") == e.get("mobile:andes.ana") == "HECHO"
              and e.get("registro-desktop") == e.get("verificar") == "YA_ESTABA", (rc, e, salida[-1500:]))
    registrar("mobile", "chofer nuevo (andes.luis) creado en catálogo y credencial; chofer del catálogo inicial (andes.ana) sólo credencial",
              pasos.get("mobile:andes.luis", {}).get("local") == "creado" and pasos.get("mobile:andes.ana", {}).get("login_cloud") == 200
              and "LUIS ANDESMARCA REYES" in (ANDES / "catalogos_privados" / "choferes.json").read_text(encoding="utf-8"),
              [pasos.get("mobile:andes.luis"), pasos.get("mobile:andes.ana")])
    usuarios = {u["nombre_usuario"]: u for u in w.tabla("mobile_usuarios_cloud")}
    registrar("mobile", "D1: usuarios Andes con empresa cloud-andes-prueba; usuario MBT intacto",
              usuarios["andes.luis"]["empresa_id"] == usuarios["andes.ana"]["empresa_id"] == ANDES_CLOUD
              and usuarios["mbt.luis"]["empresa_id"] == CLOUD_MBT and usuarios["mbt.luis"]["usuario_id"] == "u-mbt-1", usuarios)
    marcas = {m["empresa_id"]: m for m in w.tabla("estado_operativo_marca")}
    archivos = w.tabla("estado_operativo_archivos")
    registrar("custodia", "custodia Cloud de Andes sembrada bajo su empresa, con su marca; la de MBT sin cambios",
              ANDES_CLOUD in marcas and marcas.get(CLOUD_MBT) == marca_mbt
              and any(a["empresa_id"] == ANDES_CLOUD and a.get("ruta", "").endswith("empresa_identidad.json") for a in archivos)
              and not [a for a in archivos if a["empresa_id"] == ANDES_CLOUD and "MBT" in json.dumps(a)], sorted(marcas))
    r = correr(["node", "-e", f"const e=require({json.dumps(str(DESKTOP / 'src' / 'empresa_desktop.js'))});"
                f"console.log(JSON.stringify(e.listarEmpresas({json.dumps(str(MBT))})))"], base_env())
    lista = json.loads(r.stdout.strip().splitlines()[-1]) if r.returncode == 0 else r.stderr
    registrar("desktop", "Desktop (empresa_desktop.listarEmpresas) ofrece MBT y «Transportes Andes (ficticia)»",
              lista == [{"id": "mbt", "nombre": "MBT"}, {"id": ANDES_ID, "nombre": ANDES_NOMBRE}], lista)
    registrar("aislamiento", "MBT ficticia byte a byte idéntica tras el alta completa", zonas_mbt() == mbt_antes)


def fase_idempotente(w: Worker) -> None:
    ledger = LOCAL / "Atlas" / "empresas" / ANDES_ID / "alta"
    antes = (inventario(ANDES), inventario(LOCAL / "Atlas" / "empresas" / ANDES_ID, (ledger, LOCAL / "Atlas" / "empresas" / ANDES_ID / "cache")),
             w.tabla("mobile_usuarios_cloud"), w.tabla("estado_operativo_marca"))
    rc, pasos, salida = alta(w, MUNDO / "plan_andes.json", "--autorizar-pull-horas", "2", claves=[])
    despues = (inventario(ANDES), inventario(LOCAL / "Atlas" / "empresas" / ANDES_ID, (ledger, LOCAL / "Atlas" / "empresas" / ANDES_ID / "cache")),
               w.tabla("mobile_usuarios_cloud"), w.tabla("estado_operativo_marca"))
    e = estados(pasos)
    registrar("idempotencia", "tercera ejecución: todo YA_ESTABA (sin pedir contraseñas) y nada cambia en raíz, estado local ni D1",
              rc == 0 and set(e.values()) <= {"YA_ESTABA", "OMITIDO"} and antes == despues, (rc, e, salida[-800:]))


def fase_uso(w: Worker) -> None:
    def jpeg(m):
        com = f"GUIA SINTETICA {m}".encode()
        return (b"\xff\xd8\xff\xfe" + (len(com) + 2).to_bytes(2, "big") + com + bytes.fromhex("ffdb004300") + bytes(range(1, 65)) +
                bytes.fromhex("ffc0000b080001000101011100ffc4001f0000010501010101010100000000000000000102030405060708090a0bffda0008010100003f00d2cf20ffd9"))

    def enviar(usuario, clave, marcador):
        s, b = w.json("POST", "/api/mobile/login", cuerpo={"usuario": usuario, "password": clave})
        limite = "----atlas" + uuid.uuid4().hex
        campos = {"envio_id": "guia-alta-900001", "observacion": f"obs {marcador}", "planta_origen_informada": "AZA_COLINA",
                  "capturado_en": "2026-11-25T10:00:00Z"}
        cuerpo = b"".join([f'--{limite}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode() for k, v in campos.items()]
                          + [f'--{limite}\r\nContent-Disposition: form-data; name="imagen"; filename="g.jpg"\r\nContent-Type: image/jpeg\r\n\r\n'.encode()
                             + jpeg(marcador) + b"\r\n", f"--{limite}--\r\n".encode()])
        s2, _ = w.pedir("POST", "/api/mobile/envios", b.get("token") if isinstance(b, dict) else None, cuerpo,
                        f"multipart/form-data; boundary={limite}")
        return s, b, s2

    s, b, s2 = enviar("andes.luis", CLAVES["andes.luis"], "ANDESMARCA")
    registrar("uso", "chofer dado de alta inicia sesión (empresa cloud-andes-prueba) y envía una guía", s == 200 and s2 == 200, (s, s2))
    enviar("mbt.luis", "clave-mbt-1", "MBTMARCA")
    r = correr([PY, "-B", "sincronizar_mobile_cloud.py", "--sin-procesar", "--base-url", w.url, "--consumidor", "pc-andes"],
               env_empresa(ANDES_ID, ANDES))
    envio = ANDES / "operacion" / "mobile" / "envios" / "guia-alta-900001"
    original = next(iter(envio.glob("original.*")), None) if envio.is_dir() else None
    contenido = original.read_bytes() if original else b""
    registrar("uso", "PULL de Andes con la configuración y el token del alta descarga sólo su guía a su raíz",
              r.returncode == 0 and b"ANDESMARCA" in contenido and b"MBTMARCA" not in contenido, (r.returncode, (r.stdout + r.stderr)[-1200:]))
    pendientes_mbt = [e for e in w.tabla("envios_cloud") if e["empresa_id"] == CLOUD_MBT]
    registrar("uso", "el envío de MBT (mismo envio_id) sigue pendiente para MBT", len(pendientes_mbt) == 1
              and pendientes_mbt[0]["estado"] == "RECIBIDO", pendientes_mbt)


def fase_rechazos(w: Worker, mbt_antes: dict) -> None:
    usuarios_andes = (ANDES / "catalogos_privados" / "usuarios_mobile.json").read_bytes()
    d1_antes = w.tabla("mobile_usuarios_cloud")
    p = plan("colision", ANDES_ID, ANDES_NOMBRE, ANDES_CLOUD, [{"usuario": "mbt.luis", "rut": "16.284.917-4",
                                                               "nombre": "PEDRO ANDESMARCA ROJAS"}])
    rc, pasos, salida = alta(w, p, claves=["clave-pirata-123"])
    s, _ = w.json("POST", "/api/mobile/login", cuerpo={"usuario": "mbt.luis", "password": "clave-mbt-1"})
    registrar("rechazo", "usuario Mobile homónimo de otra empresa: USUARIO_DE_OTRA_EMPRESA antes de escribir; usuario MBT intacto",
              rc == 2 and pasos.get("mobile:mbt.luis", {}).get("codigo") == "USUARIO_DE_OTRA_EMPRESA"
              and (ANDES / "catalogos_privados" / "usuarios_mobile.json").read_bytes() == usuarios_andes
              and w.tabla("mobile_usuarios_cloud") == d1_antes and s == 200, (rc, pasos.get("mobile:mbt.luis"), s))
    for nombre, empresa, cloud, codigo in (("cloud-mbt", "pirata", CLOUD_MBT, "CLOUD_ID_EN_USO"),
                                            ("cloud-andes", "pirata", ANDES_CLOUD, "CLOUD_ID_EN_USO"),
                                            ("andes-otro-cloud", ANDES_ID, "cloud-otro", "CLOUD_ID_DISTINTO")):
        antes = inventario(DRIVE)
        rc, pasos, salida = alta(w, plan(nombre, empresa, "X", cloud, []))
        obtenido = next((v.get("codigo") for v in pasos.values() if v.get("estado") == "ERROR"), None)
        registrar("rechazo", f"plan {empresa} con cloud_id {cloud}: {codigo}, nada escrito",
                  rc == 2 and obtenido in (codigo, "EMPRESA_YA_DEFINIDA") and inventario(DRIVE) == antes
                  and not (EMPRESAS / "pirata").exists(), (rc, obtenido, salida[-500:]))
    rc, _p, salida = alta(w, plan("mbt", "mbt", "MBT", "x", []))
    registrar("rechazo", "empresa_id 'mbt' rechazado por el procedimiento", rc != 0 and "inválido" in salida, salida[-300:])
    # Las escrituras del alta pasan por turno: sin él, la raíz (tratada como compartida) las rechaza.
    r = correr([PY, "-B", "-c", "import atlas_core, os; from pathlib import Path\n"
                "try:\n open(os.path.join(os.environ['ATLAS_DATA_DIR'],'catalogos_privados','x.json'),'w').write('1'); print('ESCRIBIO')\n"
                "except PermissionError as e: print('RECHAZADA', type(e).__name__)"], env_empresa(ANDES_ID, ANDES))
    registrar("rechazo", "control: escribir en la raíz de Andes sin turno se rechaza (EscrituraSinTurno)",
              "RECHAZADA EscrituraSinTurno" in r.stdout, (r.stdout + r.stderr)[-400:])
    registrar("aislamiento", "MBT ficticia byte a byte idéntica tras los rechazos", zonas_mbt() == mbt_antes)


def fase_tercera(w: Worker, mbt_antes: dict) -> None:
    andes_antes = inventario(ANDES)
    rc, pasos, salida = alta(w, plan("cordillera", CORD_ID, "Transportes Cordillera (ficticia)", "cloud-cordillera-prueba", []))
    e = estados(pasos)
    registrar("tercera", "alta de una tercera empresa (antes imposible: ACCESO_ENTRE_EMPRESAS): registro y estructura hechos, cloud PENDIENTE",
              rc == 3 and e.get("registro") == e.get("estructura") == "HECHO" and e.get("cloud") == "PENDIENTE", (rc, e, salida[-800:]))
    r = correr([PY, "-B", "-c", "import atlas_core.aislamiento_empresas as ae, os\n"
                f"base=r'{EMPRESAS}'\n"
                "print('LISTA', ae.listar_empresas(os.environ['ATLAS_RAIZ_MBT']))\n"
                "try:\n open(os.path.join(base,'andes-prueba','catalogos_privados','choferes.json')).read(); print('LEYO')\n"
                "except ae.ErrorAislamiento as x: print('VETADO', x.codigo)\n"
                "try:\n open(os.path.join(base,'andes-prueba','catalogos_privados','empresa_identidad.json'),'a'); print('ESCRIBIO')\n"
                "except ae.ErrorAislamiento as x: print('VETADO', x.codigo)"],
               env_empresa(CORD_ID, EMPRESAS / CORD_ID, ATLAS_EMPRESA_ALTA=CORD_ID, ATLAS_EXCLUSION_LOCAL="desactivada"))
    registrar("tercera", "proceso de alta: ve el registro de empresas pero no lee datos ni escribe la marca de otra",
              "LISTA ['mbt', 'andes-prueba', 'cordillera-prueba']" in r.stdout and r.stdout.count("VETADO ACCESO_ENTRE_EMPRESAS") == 2,
              (r.stdout + r.stderr)[-600:])
    r = correr([PY, "-B", "-c", "import atlas_core, os\ntry:\n os.listdir(os.path.join(os.path.dirname(os.environ['ATLAS_RAIZ_MBT']),'Atlas_empresas')); print('LISTO')\n"
                "except Exception as x: print('VETADO', type(x).__name__)"], env_empresa(ANDES_ID, ANDES))
    registrar("tercera", "un proceso normal de Andes sigue sin poder listar las otras empresas", "VETADO ErrorAislamiento" in r.stdout,
              (r.stdout + r.stderr)[-300:])
    registrar("tercera", "Andes y MBT intactas tras el alta de la tercera", inventario(ANDES) == andes_antes and zonas_mbt() == mbt_antes)


def barrido() -> None:
    local = LOCAL / "Atlas"
    for nombre, raiz, excl, ajeno in (("mbt", MBT, (), "ANDESMARCA"), ("mbt local", local, (local / "empresas",), "ANDESMARCA"),
                                      (ANDES_ID, ANDES, (), "MBTMARCA"), (f"{ANDES_ID} local", local / "empresas" / ANDES_ID, (), "MBTMARCA"),
                                      (CORD_ID, EMPRESAS / CORD_ID, (), "MARCA"), (f"{CORD_ID} local", local / "empresas" / CORD_ID, (), "MARCA")):
        hallados = buscar(raiz, ajeno, excl)
        registrar("barrido", f"{nombre}: sin datos de otra empresa ({ajeno})", not hallados, hallados[:10])


def main() -> int:
    EVIDENCIA.mkdir(parents=True, exist_ok=True)
    preparar()
    mbt_antes = zonas_mbt()
    w = Worker({})
    try:
        fase_revision(w)
        fragmento = fase_pendiente(w, mbt_antes)
    finally:
        w.cerrar()
    # Paso humano simulado: el fragmento que dejó el alta se agrega al secreto del Worker.
    w = Worker(fragmento)
    try:
        r = correr([PY, "-B", "-m", "atlas_core.estado_confirmado", "--raiz-atlas", str(MBT), "--sembrar"],
                   {**env_mbt(), "ATLAS_CLOUD_MOBILE_URL": w.url})
        registrar("preparacion", "custodia de MBT ficticia sembrada (referencia para verificar que el alta no la toca)",
                  r.returncode == 0, (r.stdout + r.stderr)[-500:])
        mbt_antes = zonas_mbt()
        fase_completa(w, mbt_antes)
        fase_idempotente(w)
        fase_uso(w)
        fase_rechazos(w, mbt_antes)
        fase_tercera(w, mbt_antes)
    finally:
        w.cerrar()
    barrido()
    fallas = [r for r in resultados if not r["ok"]]
    (EVIDENCIA / "validacion_alta.json").write_text(json.dumps({
        "fecha": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "motor": subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=MOTOR).stdout.strip(),
        "cloud": subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=CLOUD).stdout.strip(),
        "total": len(resultados), "fallas": len(fallas), "resultados": resultados}, indent=1, ensure_ascii=False, default=str),
        encoding="utf-8")
    print(f"\n{len(resultados) - len(fallas)}/{len(resultados)} OK")
    return 1 if fallas else 0


if __name__ == "__main__":
    raise SystemExit(main())
