"""Integración conjunta multiempresa (26/11/2026): ciclo operativo completo.

Une en UN solo recorrido las piezas ya validadas por separado (no repite sus
verificaciones: validar_alta, validar_identidad, validar_plantas y la prueba
Electron de identidad siguen siendo la referencia de cada una):

  Motor (este checkout: plantas 4b6ba30 ⊃ identidad e1fa560, + b0b42e4 + b09bd28)
  Cloud (Worker real fcc2051 ⊃ 117899d, D1/R2 en memoria, HTTPS local)
  Mobile (código real 94099ef: auth.js + sync-core.js en Node)
  Desktop (Electron real 5665982, fase opcional: --desktop)

Transportes Andes y MBT, ambas FICTICIAS, en un mundo sintético:

  alta integral → identidad (admin, supervisor, lector) → plantas propias
  publicadas por el PULL → chofer Mobile ve sólo sus plantas y envía una guía
  → PULL con OCR real la recibe y procesa → consulta → corrección con
  confirmación → informe regenerado; aislamiento, permisos y dependencias de
  AZA/MBT medidas en cada paso.

    python -B scripts/validacion_multiempresa/validar_integracion.py <mundo> <cloud> <mobile> <desktop> <python-rapidocr> [--desktop]

<mundo> debe estar bajo C:\\Atlas\\pruebas; se borra y recrea. Nunca toca G:,
el LOCALAPPDATA real, Cloudflare, PULL ni instalaciones. Evidencia en
<mundo>/../evidencia/validacion_integracion.json; sale 1 si algo falla.
"""
from __future__ import annotations

import csv
import io
import json
import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path

_ARGS = [a for a in sys.argv[1:] if not a.startswith("--")]
CON_DESKTOP = "--desktop" in sys.argv
MUNDO, CLOUD, MOBILE, DESKTOP, PY_OCR = (Path(a).resolve() for a in _ARGS[:5])
if not str(MUNDO).lower().startswith("c:\\atlas\\pruebas\\"):
    sys.exit("el mundo debe estar bajo C:\\Atlas\\pruebas")
sys.argv = [sys.argv[0], str(MUNDO), str(CLOUD), str(DESKTOP)]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import validar_alta as va  # noqa: E402
import validar_identidad as vi  # noqa: E402

MOTOR, MBT, ANDES, LOCAL, PY = va.MOTOR, va.MBT, va.ANDES, va.LOCAL, va.PY
ANDES_ID, ANDES_CLOUD, CLOUD_MBT = va.ANDES_ID, va.ANDES_CLOUD, va.CLOUD_MBT
GUIA_ANDES, GUIA_MBT = "7001234", "7005678"
TRANSPORTE_ANDES = "0000700123"
ENVIO_ANDES, ENVIO_MBT = "guia-andes-7001234-integracion", "guia-mbt-7005678-integracion"
CLAVE_LECTOR = "clave-andes-lector-1"
PLANTAS_ANDES = ("Puerto Norte ANDESMARCA", "Bodega Lampa ANDESMARCA")

resultados: list[dict] = []
dependencias: list[dict] = []
estado: dict = {}


def registrar(etapa: str, prueba: str, ok: bool, detalle: object = "") -> None:
    resultados.append({"etapa": etapa, "prueba": prueba, "ok": bool(ok), "detalle": detalle})
    print(("OK   " if ok else "FALLA") + f" [{etapa}] {prueba}" + ("" if ok else f" :: {str(detalle)[:900]}"), flush=True)


def dependencia(componente: str, descripcion: str, evidencia: object) -> None:
    """Dependencia funcional pendiente: se registra, no se desarrolla aquí."""
    dependencias.append({"componente": componente, "descripcion": descripcion, "evidencia": evidencia})
    print(f"DEP  [{componente}] {descripcion}", flush=True)


def env_empresa(empresa: str, sesion: str | None = None, **extra) -> dict:
    env = va.env_mbt() if empresa == "mbt" else va.env_empresa(ANDES_ID, ANDES)
    env.update(ATLAS_CLOUD_MOBILE_URL=vi.W.url, ATLAS_OCR_PROVIDER="rapidocr", ATLAS_RAPIDOCR_PYTHON=str(PY_OCR))
    env.pop("ATLAS_SESION", None)
    if sesion:
        env["ATLAS_SESION"] = sesion
    env.update(extra)
    return env


def motor(empresa: str, *args: str, sesion: str | None = None, entrada: str | None = None, **extra) -> subprocess.CompletedProcess:
    return va.correr([PY, "-B", *args], env_empresa(empresa, sesion, **extra), entrada=entrada)


def ultima_json(texto: str) -> dict:
    for linea in reversed(texto.strip().splitlines()):
        try:
            v = json.loads(linea)
            if isinstance(v, dict):
                return v
        except ValueError:
            continue
    try:
        return json.loads(texto)
    except ValueError:
        return {"_salida": texto[-1500:]}


def filas_dataset(raiz: Path) -> list[dict]:
    ruta = raiz / "operacion" / "actual" / "analisis_completo_guias.csv"
    if not ruta.is_file():
        return []
    return list(csv.DictReader(io.StringIO(ruta.read_text(encoding="utf-8-sig")), delimiter=";"))


def viajes_vigentes(raiz: Path) -> str:
    try:
        e = json.loads((raiz / "operacion" / "actual" / "estado_operacion.json").read_text(encoding="utf-8"))
        return (raiz / e["reporte_vigente"] / "viajes.csv").read_text(encoding="utf-8-sig")
    except (OSError, KeyError, ValueError):
        return ""


# --------------------------------------------------------------- guías sintéticas
def guia_sintetica(destino: Path, lineas: list[str]) -> Path:
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new("RGB", (1400, 1900), "white")
    d = ImageDraw.Draw(img)
    fuente = ImageFont.truetype(r"C:\Windows\Fonts\arial.ttf", 40)
    y = 80
    for linea in lineas:
        d.text((70, y), linea, fill="black", font=fuente)
        y += 78
    destino.parent.mkdir(parents=True, exist_ok=True)
    img.save(destino, "JPEG", quality=92)
    return destino


def lineas_guia(numero: str, marca: str, emisor: str) -> list[str]:
    return [f"{emisor}", "GUIA DE DESPACHO ELECTRONICA", f"N° {numero}", "FECHA EMISION: 25-11-2026",
            f"SEÑOR(ES): CONSTRUCTORA {marca} SA", "RUT: 76.111.111-6",
            f"DESPACHAR A: CALLE {marca} 200, LAMPA", f"CHOFER: LUIS {marca} REYES  RUT 12.345.678-5",
            "PATENTE TRACTO: KN5439", f"ARIDO {marca}   CANTIDAD 25.000 KG", "PESO NETO: 25.000 KG"]


# ------------------------------------------------------------------ A. preparación
def preparar() -> None:
    """Alta e identidad con los procedimientos existentes (validados aparte):
    validar_identidad.preparar (alta Andes con su token en el Worker) más las
    plantas propias de Andes como catálogo inicial del alta."""
    original = va.preparar

    def preparar_con_plantas() -> None:
        original()
        r = va.correr([PY, "-B", "-c", textwrap.dedent(f"""
            from atlas_core.catalogo_plantas import CatalogoPlantas
            c = CatalogoPlantas(r"{MUNDO / 'iniciales_andes' / 'plantas.json'}")
            for n in {list(PLANTAS_ANDES)!r}:
                c.crear(nombre=n, pais="Chile", fuente="integracion", estado_calidad="CONFIRMADA")
        """)], va.env_mbt())
        if r.returncode:
            raise RuntimeError(r.stderr[-1500:])

    va.preparar = preparar_con_plantas
    vi.preparar()
    # MBT ficticia: política PULL lease_cloud propia (a Andes se la deja el alta).
    from datetime import datetime, timedelta, timezone
    (LOCAL / "Atlas" / "desktop_operacion.json").write_text(json.dumps({
        "modo_escritor": "lease_cloud", "autorizada": True, "habilitada": True, "raiz": str(MBT), "raiz_mbt": str(MBT),
        "proyecto": str(MOTOR), "nota": "MBTMARCA"}), encoding="utf-8")
    (LOCAL / "Atlas" / "pull_autorizacion.json").write_text(json.dumps({
        "autor": "Javier", "exclusividad_verificada": True, "modo": "temporal", "habilitada": True, "revocada": False,
        "vence_utc": (datetime.now(timezone.utc) + timedelta(hours=3)).isoformat()}), encoding="utf-8")
    plantas = json.loads((ANDES / "catalogos_privados" / "plantas.json").read_text(encoding="utf-8"))
    lista = plantas.get("plantas", plantas) if isinstance(plantas, dict) else plantas
    estado["plantas"] = {p["nombre"]: p["planta_id"] for p in lista}
    registrar("alta", "alta integral de Andes con sus plantas propias como catálogo inicial (sin plantas AZA)",
              sorted(estado["plantas"]) == sorted(PLANTAS_ANDES) and not any("AZA" in n.upper() for n in estado["plantas"]),
              estado["plantas"])
    sa = vi.fase_plataforma()
    s = vi.fase_arranque(sa)
    rc, r = vi.ua("andes", "crear", "--usuario", "andes.sup", "--nombre", "Supervisor Andes", "--rol", "supervisor",
                  sesion=s["aa"], clave=vi.CLAVE["andes.sup"])
    rc2, r2 = vi.ua("andes", "crear", "--usuario", "andes.lector", "--nombre", "Lector Andes", "--rol", "consulta",
                    sesion=s["aa"], clave=CLAVE_LECTOR)
    estado["sesiones"] = s
    registrar("identidad", "Andes con administrador y supervisor; exigencia de identidad activa en ambas empresas",
              rc == 0 and all(x["ok"] for x in vi.resultados), (r, [x for x in vi.resultados if not x["ok"]]))
    if rc2:
        dependencia("Motor identidad", "No se puede crear un usuario de sólo consulta: usuarios_atlas.py admite sólo "
                    "administrador_empresa y supervisor (ROLES_EMPRESA), aunque PERMISOS y Desktop reconocen 'consulta'", r2)


# ---------------------------------------------------------------- B. plantas + Mobile
CLIENTE_MOBILE = textwrap.dedent("""\
    // Código REAL de Mobile 0.17.24: login, catálogo de plantas por sesión y envío.
    const fs = require("node:fs");
    const [mobile, base, usuario, password, especificacion] = process.argv.slice(2);
    const moduloAuth = require(mobile + "/src/auth.js");
    const { AtlasSyncCore } = require(mobile + "/src/sync-core.js");
    (async () => {
      const config = { apiBaseUrl: base, rutaLoginMobile: "/api/mobile/login" };
      moduloAuth.ATLAS_CONFIG = config;
      const login = await new moduloAuth.AtlasAuth.ProveedorAutenticacionRemota().iniciarSesion(usuario, password, config);
      if (!login.ok) { console.log("@@" + JSON.stringify({ login })); return; }
      const plantas = await moduloAuth.AtlasAuth.obtenerPlantas(login.sesion.token);
      const envios = [];
      for (const e of JSON.parse(especificacion)) {
        const blob = new Blob([fs.readFileSync(e.imagen)], { type: "image/jpeg" });
        let registro;
        try {
          registro = await AtlasSyncCore.construirRegistroPendiente({ envioId: e.envio_id, blobImagen: blob, tipoNovedad: "",
            guiaFirmadaCorreo: false, plantaOrigen: e.planta, observacion: e.observacion || "" });
        } catch (error) { envios.push({ envio_id: e.envio_id, local: String(error.message) }); continue; }
        const r = await fetch(base + "/api/mobile/envios", { method: "POST", headers: { Authorization: "Bearer " + login.sesion.token },
          body: AtlasSyncCore.construirFormData(Object.assign({}, registro, { imagen: blob })) });
        envios.push({ envio_id: e.envio_id, status: r.status, cuerpo: await r.json() });
      }
      console.log("@@" + JSON.stringify({ login: { ok: true, chofer: login.sesion.chofer_id || null }, plantas, envios }));
    })().catch((e) => { console.error(e); process.exit(1); });
    """)


def mobile(usuario: str, clave: str, envios: list[dict]) -> dict:
    script = MUNDO / "cliente_mobile.cjs"
    script.write_text(CLIENTE_MOBILE, encoding="utf-8")
    env = {**os.environ, "NODE_EXTRA_CA_CERTS": str(MUNDO / "tls" / "cert.pem")}
    r = subprocess.run(["node", str(script), MOBILE.as_posix(), vi.W.url, usuario, clave, json.dumps(envios)],
                       capture_output=True, text=True, encoding="utf-8", env=env, timeout=180)
    for linea in reversed(r.stdout.splitlines()):
        if linea.startswith("@@"):
            return json.loads(linea[2:])
    raise RuntimeError(f"cliente Mobile falló: {r.stderr[-1500:]}")


def pull(empresa: str, procesar: bool = True) -> tuple[int, dict, str]:
    args = ["sincronizar_mobile_cloud.py", "--base-url", vi.W.url, "--consumidor", f"pc-integracion-{empresa}"]
    if not procesar:
        args.append("--sin-procesar")
    r = motor(empresa, *args)
    return r.returncode, ultima_json(r.stdout), (r.stdout + r.stderr)


def fase_plantas_y_mobile() -> None:
    rc, res, salida = pull("andes", procesar=False)
    registrar("plantas", "primer PULL de Andes (proceso de sistema, sin sesión) publica sus 2 plantas a Cloud",
              rc == 0 and (res.get("plantas_mobile") or {}).get("publicadas") == 2, {"rc": rc, "plantas": res.get("plantas_mobile"), "salida": salida[-800:]})
    rc, res, salida = pull("mbt", procesar=False)
    registrar("plantas", "PULL de MBT no publica catálogo (conserva AZA por compatibilidad)",
              rc == 0 and (res.get("plantas_mobile") or {}).get("publicadas") is None, {"rc": rc, "plantas": res.get("plantas_mobile")})

    norte = estado["plantas"][PLANTAS_ANDES[0]]
    img_andes = guia_sintetica(MUNDO / "guias" / "andes.jpg", lineas_guia(GUIA_ANDES, "ANDESMARCA", "TRANSPORTES ANDES (FICTICIA)"))
    img_mbt = guia_sintetica(MUNDO / "guias" / "mbt.jpg", lineas_guia(GUIA_MBT, "MBTMARCA", "MBT (FICTICIA)"))
    a = mobile("andes.luis", va.CLAVES["andes.luis"], [
        {"envio_id": ENVIO_ANDES, "planta": norte, "imagen": str(img_andes), "observacion": "integracion ANDESMARCA"},
        {"envio_id": "guia-andes-aza-rechazo-01", "planta": "AZA_COLINA", "imagen": str(img_andes)}])
    nombres = sorted(p.get("nombre") for p in a.get("plantas", []))
    registrar("mobile", "chofer Andes (alta integral) inicia sesión y Mobile ofrece sólo las plantas de Andes, sin Colina/Renca",
              a.get("login", {}).get("ok") and nombres == sorted(PLANTAS_ANDES), a.get("plantas"))
    est = {e["envio_id"]: e.get("status") for e in a.get("envios", [])}
    registrar("mobile", "Andes envía su guía con su planta (200); con AZA_COLINA se rechaza (400)",
              est == {ENVIO_ANDES: 200, "guia-andes-aza-rechazo-01": 400}, a.get("envios"))
    m = mobile("mbt.luis", "clave-mbt-1", [
        {"envio_id": ENVIO_MBT, "planta": "AZA_COLINA", "imagen": str(img_mbt), "observacion": "integracion MBTMARCA"},
        {"envio_id": "guia-mbt-cruce-andes-01", "planta": norte, "imagen": str(img_mbt)}])
    registrar("mobile", "chofer MBT ve Colina/Renca, envía con AZA_COLINA (200) y no puede usar una planta de Andes (400)",
              [p.get("planta_id") for p in m.get("plantas", [])] == ["AZA_COLINA", "AZA_RENCA"]
              and {e["envio_id"]: e.get("status") for e in m.get("envios", [])} == {ENVIO_MBT: 200, "guia-mbt-cruce-andes-01": 400},
              m)


# ------------------------------------------------------------- C. recepción + OCR
def fase_recepcion() -> None:
    mbt_antes = vi.zonas_mbt()
    t0 = time.time()
    rc, res, salida = pull("andes", procesar=True)
    estado["pull_andes"] = {"rc": rc, "segundos": round(time.time() - t0, 1), "resultado": res}
    (va.EVIDENCIA / "pull_andes.txt").write_text(salida, encoding="utf-8")
    envio = ANDES / "operacion" / "mobile" / "envios" / ENVIO_ANDES
    meta = json.loads((envio / "envio.json").read_text(encoding="utf-8")) if (envio / "envio.json").is_file() else {}
    registrar("recepcion", "PULL Andes con OCR real recibe su envío en su raíz con su planta_id",
              meta.get("planta_origen_informada") == estado["plantas"][PLANTAS_ANDES[0]], {"rc": rc, "meta": {k: meta.get(k) for k in ("envio_id", "estado", "planta_origen_informada")}})
    filas = [f for f in filas_dataset(ANDES) if ENVIO_ANDES in json.dumps(f) or f.get("numero_guia") == GUIA_ANDES]
    estado["fila_andes"] = filas[-1] if filas else {}
    registrar("procesamiento", "la guía de Andes queda procesada en el dataset de Andes",
              bool(filas), {"rc": rc, "res": {k: res.get(k) for k in ("procesados", "errores_procesamiento", "persistidos", "confirmados")},
                            "dataset": len(filas_dataset(ANDES)), "salida": salida[-1500:]})
    envios_cloud = {e["envio_id"]: e for e in vi.W.tabla("envios_cloud") if e.get("empresa_id") == ANDES_CLOUD}
    registrar("recepcion", "Cloud marca el envío de Andes como confirmado por el Motor de Andes",
              bool(envios_cloud.get(ENVIO_ANDES, {}).get("confirmado_en")), envios_cloud.get(ENVIO_ANDES))
    registrar("aislamiento", "MBT ficticia (raíz y estado local) idéntica tras recibir y procesar la guía de Andes",
              vi.zonas_mbt() == mbt_antes)
    rc, res, salida = pull("mbt", procesar=True)
    (va.EVIDENCIA / "pull_mbt.txt").write_text(salida, encoding="utf-8")
    filas_mbt = [f for f in filas_dataset(MBT) if f.get("numero_guia") == GUIA_MBT or ENVIO_MBT in json.dumps(f)]
    registrar("recepcion", "MBT recibe y procesa sólo su guía, en su raíz", bool(filas_mbt)
              and not [f for f in filas_dataset(MBT) if "ANDESMARCA" in json.dumps(f, ensure_ascii=False)],
              {"rc": rc, "filas": len(filas_mbt), "salida": salida[-800:]})


# ------------------------------------------------- D. puerta de identidad + reporte
def fase_reporte_inicial() -> None:
    s = estado["sesiones"]
    r = motor("andes", "b1_consulta_cli.py", "--raiz-atlas", str(ANDES), "--texto", f"¿Qué peso tiene la guía {GUIA_ANDES}?")
    registrar("permisos", "sin sesión, la consulta B1 sobre la guía recién procesada de Andes se niega (77 SIN_SESION)",
              r.returncode == 77 and "SIN_SESION" in r.stderr, (r.returncode, r.stderr[-300:]))
    estado["reporte_tras_pull"] = bool(viajes_vigentes(ANDES))
    if not estado["reporte_tras_pull"]:
        # Única vía manual: el CLI de reportes. En raíz compartida (Drive) no toma turno local.
        dataset = ANDES / "operacion" / "actual" / "analisis_completo_guias.csv"
        r = motor("andes", "generar_reporte_viajes.py", str(dataset), str(ANDES / "reportes" / "inicial"),
                  "--catalogos", str(ANDES / "catalogos_privados"), sesion=s["aa"])
        dependencia("Motor alta/PULL", "Empresa nueva sin reporte vigente: el PULL procesa la guía pero no publica el primer "
                    "reporte (revalidar_y_regenerar_reporte nunca fuerza una primera regeneración), el alta no lo crea, Desktop "
                    "ya no reconcilia al abrir y generar_reporte_viajes.py en raíz compartida falla sin turno local. "
                    "El primer reporte aparece recién con una corrección (B1) que actualiza la guía",
                    {"envio.reconciliacion_reporte": "reporte_regenerado=false, reporte_vigente=null",
                     "generar_reporte_viajes_admin": {"rc": r.returncode, "error": "EscrituraSinTurno" if "EscrituraSinTurno" in r.stderr else r.stderr[-300:]}})


# ------------------------------------------------------------------- E. Desktop
class Electron:
    """Electron real de Desktop (test/integracion_multiempresa_electron.js)."""

    def __init__(self) -> None:
        self.dir = MUNDO.parent / "electron"
        if self.dir.exists():
            import shutil
            shutil.rmtree(self.dir)
        (self.dir / "ctl").mkdir(parents=True)
        self.informe = self.dir / "informe.jsonl"
        self.exe = DESKTOP / "node_modules" / "electron" / "dist" / "electron.exe"
        (self.dir / "config.json").write_text(json.dumps({"carpetaProyectoPython": str(MOTOR)}), encoding="utf-8")
        (LOCAL / "Atlas" / "desktop_acceso.json").write_text(json.dumps(
            {"version": 1, "habilitado": True, "raiz_mbt": str(MBT), "carpeta_motor": str(MOTOR)}), encoding="utf-8")

    def leer(self) -> list[dict]:
        if not self.informe.exists():
            return []
        return [json.loads(l) for l in self.informe.read_text(encoding="utf-8").splitlines() if l.strip()]

    def esperar(self, pred, segundos=180, que=""):
        limite = time.time() + segundos
        while True:
            r = pred(self.leer())
            if r:
                return r
            if time.time() > limite:
                raise TimeoutError(f"{que}: {[json.dumps(x)[:300] for x in self.leer()[-5:]]}")
            time.sleep(0.25)

    def orden(self, pid: int, o: dict) -> None:
        f = self.dir / "ctl" / f"{pid}.json"
        f.with_suffix(".tmp").write_text(json.dumps(o), encoding="utf-8")
        os.replace(f.with_suffix(".tmp"), f)

    def entorno(self) -> dict:
        env = va.base_env()
        env.pop("ELECTRON_RUN_AS_NODE", None)
        # Raíces del mundo en C: = no compartidas: Desktop no toma lease ni turno (en Drive
        # sí). Forzarlas protegidas sólo para Desktop bloquearía su escritura sin turno; el
        # validador Electron de identidad tampoco las protege. Límite declarado en la evidencia.
        env.pop("ATLAS_EXCLUSION_RAICES", None)
        creds = json.loads(va.CREDENCIALES.read_text(encoding="utf-8"))
        env.update(creds, ATLAS_DATA_DIR=str(MBT), ATLAS_PYTHON=PY, ATLAS_H_DIR=str(self.dir),
                   ATLAS_USER_DATA_PATH=str(self.dir / "userdata"), ATLAS_CONFIG_PATH=str(self.dir / "config.json"),
                   ATLAS_DISABLE_UPDATER="1", PYTHONUTF8="1", ATLAS_CLOUD_MOBILE_URL=vi.W.url,
                   ATLAS_CLOUD_MOTOR_TOKEN=va.TOKEN_MBT)
        return env

    def entrar(self, empresa: str, usuario: str, clave: str) -> tuple[dict, dict | None]:
        n = len(self.leer())
        subprocess.Popen([str(self.exe), str(DESKTOP / "test" / "integracion_multiempresa_electron.js")], env=self.entorno(),
                         cwd=DESKTOP, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=0x00000008)
        pantalla = self.esperar(lambda l: next((x for x in l[n:] if x["rol"] == "acceso" and x["evento"] == "pantalla"), None),
                                120, "pantalla de acceso")
        n = len(self.leer())
        self.orden(pantalla["pid"], {"accion": "ingresar", "empresa": empresa, "usuario": usuario, "contrasena": clave})
        # El lanzador termina al abrir la sesión, a veces antes de anotar su «ingreso».
        evento = self.esperar(lambda l: next((x for x in l[n:] if x["evento"] == "ingreso"
                                              or (x["rol"] == "sesion" and x["evento"] == "reporte")), None), 240, "ingreso")
        if evento["evento"] == "ingreso" and not str(evento.get("mensaje", "")).startswith("Abriendo"):
            return {**pantalla, "ingreso": evento}, None
        sesion = self.esperar(lambda l: next((x for x in l[n:] if x["rol"] == "sesion" and x["evento"] == "reporte"), None),
                              240, "sesión")
        return {**pantalla, "ingreso": "Abriendo"}, sesion

    def js(self, pid: int, codigo: str, segundos: int = 300):
        ident = f"r{time.time_ns()}"
        self.orden(pid, {"accion": "js", "id": ident, "codigo": codigo})
        return self.esperar(lambda l: next((x for x in l if x.get("id") == ident), None), segundos, f"js {codigo[:60]}")["valor"]

    def informe_pdf(self, pid: int):
        ident = f"i{time.time_ns()}"
        self.orden(pid, {"accion": "informe", "id": ident})
        return self.esperar(lambda l: next((x for x in l if x.get("id") == ident and x["evento"] == "resultado"), None), 240, "informe")["valor"]

    def cerrar_todo(self) -> None:
        for x in self.leer():
            if x["evento"] == "inicio":
                subprocess.run(["taskkill", "/PID", str(x["pid"]), "/T", "/F"], capture_output=True)


def ledger(raiz: Path) -> list[dict]:
    ruta = raiz / "operacion" / "actual" / "decisiones_aplicadas.json"
    try:
        return json.loads(ruta.read_text(encoding="utf-8")).get("aplicaciones", [])
    except (OSError, ValueError):
        return []


def fase_desktop() -> None:
    e = Electron()
    estado["electron"] = str(e.dir)
    try:
        mbt_antes = vi.zonas_mbt()
        pantalla, sup = e.entrar(ANDES_ID, "andes.sup", vi.CLAVE["andes.sup"])
        registrar("desktop", "el supervisor de Andes entra a Desktop (pantalla con MBT y Andes) con sesión Motor de Andes",
                  pantalla.get("empresas") == ["mbt", ANDES_ID] and bool(sup and sup.get("huellaMotor")) and sup.get("empresa") == ANDES_ID,
                  {"empresas": pantalla.get("empresas"), "ingreso": pantalla.get("ingreso"), "sesion": sup and {k: sup.get(k) for k in ("empresa", "usuario", "rolSesion")}})
        if not sup:
            return
        pid = sup["pid"]
        carga = e.js(pid, "window.atlasAPI.cargarLocalRapido().then((r) => JSON.stringify(r))")
        estado["carga_inicial_desktop"] = str(carga)[:600]
        registrar("aislamiento", "la carga inicial de Desktop en Andes no contiene datos de MBT",
                  isinstance(carga, str) and "MBTMARCA" not in carga and GUIA_MBT not in carga, str(carga)[:600])
        hist = e.js(pid, "window.atlasAPI.cargarEnviosMobileHistorial().then((r) => JSON.stringify(r))")
        registrar("consulta", "historial Mobile de Desktop muestra el envío de Andes y ninguno de MBT",
                  isinstance(hist, str) and ENVIO_ANDES in hist and ENVIO_MBT not in hist, str(hist)[:500])
        def corregir(conv: str, instruccion: str) -> tuple[str, str]:
            p = e.js(pid, f"window.atlasAPI.b1Atender('{conv}', {json.dumps(instruccion)}).then((r) => JSON.stringify(r), (x) => 'ERROR ' + x)")
            c = e.js(pid, f"window.atlasAPI.b1Atender('{conv}', 'sí').then((r) => JSON.stringify(r), (x) => 'ERROR ' + x)")
            return str(p), str(c)

        # El OCR (pipeline AZA) no encuentra el «número de transporte» de la guía de Andes: sin él
        # la guía no forma viaje. Se corrige primero, igual que lo haría el supervisor desde B1.
        pt, ct = corregir("int-correccion-transporte", f"En la guía {GUIA_ANDES} el número de transporte es {TRANSPORTE_ANDES}")
        pp, cp = corregir("int-correccion-peso", f"En la guía {GUIA_ANDES} el peso correcto es 25.000 kg")
        estado["b1_correcciones"] = {"transporte": {"preview": pt, "confirmacion": ct}, "peso": {"preview": pp, "confirmacion": cp}}
        fila = next((f for f in filas_dataset(ANDES) if f.get("numero_guia") == GUIA_ANDES), {})
        registrar("correccion", "dos correcciones B1 desde Desktop (vista previa + confirmación humana): transporte y peso escritos en el dataset de Andes",
                  all('"PREVIEW_PENDIENTE"' in x for x in (pt, pp)) and all('"EJECUTADA"' in x for x in (ct, cp))
                  and fila.get("numero_transporte") == TRANSPORTE_ANDES and fila.get("peso_kg") == "25000",
                  {"transporte": (pt[:300], ct[:300]), "peso": (pp[:300], cp[:300]),
                   "fila": {k: fila.get(k) for k in ("numero_transporte", "peso_kg", "estado_documental")}})
        dependencia("Motor modelo de viaje", "El viaje se identifica por el «número de transporte» de la guía AZA: una guía de otra "
                    "empresa procesada sin ese dato queda en documentos_sin_transporte y no aparece en viajes, consultas ni "
                    "informe hasta que una persona le asigna un transporte por B1",
                    {"fila_tras_ocr": {k: estado.get("fila_andes", {}).get(k) for k in ("numero_guia", "numero_transporte")}})
        aplicaciones = [a for a in ledger(ANDES) if a.get("campo") in ("peso_kg", "numero_transporte")]
        actores = sorted({str(a.get("confirmado_por") or "") for a in aplicaciones})
        estado["actores_correccion"] = actores
        registrar("correccion", "las correcciones quedan en el ledger de Andes atribuidas a la persona identificada (andes-prueba:andes.sup), no a JAVIER_DESKTOP",
                  len(aplicaciones) == 2 and actores == [f"{ANDES_ID}:andes.sup"], {"actores": actores, "ledger": aplicaciones[-1:]})
        texto = viajes_vigentes(ANDES)
        registrar("reporte", "tras la corrección el Motor publica el reporte vigente de Andes con la guía y el peso nuevo",
                  GUIA_ANDES in texto and "25000" in texto and "MBTMARCA" not in texto, texto[:400])
        carga = e.js(pid, "window.atlasAPI.cargarLocalRapido().then((r) => JSON.stringify(r))")
        registrar("consulta", "Desktop carga ese reporte: la guía recibida por Mobile, corregida, sin datos de MBT",
                  isinstance(carga, str) and GUIA_ANDES in carga and "MBTMARCA" not in carga and GUIA_MBT not in carga, str(carga)[:600])
        e.js(pid, "(location.reload(), true)", 60)
        time.sleep(3)
        cargados = e.js(pid, "(async () => { for (let i = 0; i < 200 && !VIAJES.length; i++) await new Promise((r) => setTimeout(r, 150)); return VIAJES.length; })()")
        # Misma secuencia que la caja de consultas de atlas_viajes.html: B1 primero y,
        # si no es suya, Consultas Atlas sobre el reporte cargado (RUTA_VIAJES_ACTUAL).
        pregunta = f"¿Qué peso tiene la guía {GUIA_ANDES}?"
        consulta = e.js(pid, f"""(async () => {{
            const b1 = await window.atlasAPI.b1Atender('int-consulta-1', {json.dumps(pregunta)});
            if (b1 && b1.estado !== 'NO_INTERPRETADA') return JSON.stringify({{ via: 'B1', r: b1 }});
            const r = await window.atlasAPI.consultarAtlas({json.dumps(pregunta)}, RUTA_VIAJES_ACTUAL);
            return JSON.stringify({{ via: 'CONSULTAS_ATLAS', ruta: RUTA_VIAJES_ACTUAL, r }});
          }})().catch((x) => 'ERROR ' + (x && x.message || x))""")
        estado["consulta_desktop"] = consulta
        registrar("consulta", "consulta desde Desktop sobre la guía de Andes (B1 → Consultas Atlas) responde con su peso corregido y la ruta de Andes",
                  isinstance(consulta, str) and not consulta.startswith("ERROR") and GUIA_ANDES in consulta
                  and ("25000" in consulta or "25.000" in consulta) and ANDES_ID in consulta and "MBTMARCA" not in consulta,
                  str(consulta)[:900])
        inf = e.informe_pdf(pid)
        html = str((inf.get("armado") or {}).get("html", "")) if isinstance(inf, dict) else ""
        estado["informe"] = {k: v for k, v in (inf or {}).items() if k != "armado"} if isinstance(inf, dict) else inf
        estado["informe"]["html_longitud"] = len(html)
        (va.EVIDENCIA / "informe_andes.html").write_text(html, encoding="utf-8")
        # El formato de informe vigente (columnas MBT) no lleva peso: el peso corregido se
        # verifica en el reporte y en la consulta; aquí, guía y transporte corregido.
        registrar("informe", "Desktop arma el informe de viajes de Andes con el exportador real (guía con su transporte corregido, sin MBT) y abre su vista previa PDF",
                  cargados == 1 and GUIA_ANDES in html and TRANSPORTE_ANDES in html and "MBTMARCA" not in html and GUIA_MBT not in html
                  and inf.get("vista"),
                  {"viajes": cargados, "vista": inf.get("vista") if isinstance(inf, dict) else None, "titulo": inf.get("titulo") if isinstance(inf, dict) else None,
                   "resultado": inf.get("resultado") if isinstance(inf, dict) else inf})
        rotulos = sorted({t for t in ("MBT",) if t in html or t in str(inf.get("titulo") or "")}) if isinstance(inf, dict) else []
        if rotulos:
            dependencia("Desktop informe", "El informe de viajes de otra empresa usa el formato y el rótulo de MBT "
                        "(exportador AtlasExportacionMBT*, vista previa «Informe MBT PDF»); falta un rótulo/plantilla por empresa",
                        {"titulo_vista_previa": inf.get("titulo"), "html_contiene_MBT": "MBT" in html})
        img = MUNDO / "guias" / "andes.jpg"
        ingreso = e.js(pid, f"window.atlasAPI.procesarImagenes([{json.dumps(str(img))}]).then((r) => 'OK ' + JSON.stringify(r), (x) => 'RECHAZO ' + (x && x.message || x))")
        estado["ingreso_desktop"] = ingreso
        entradas = list((ANDES / "operacion" / "entradas").glob("*")) if (ANDES / "operacion" / "entradas").exists() else []
        registrar("aislamiento", "ingreso de guías por Desktop en Andes se detiene antes de copiar (sin perfil documental propio; nunca cae en AZA)",
                  str(ingreso).startswith("RECHAZO") and not entradas, {"respuesta": str(ingreso)[:500], "entradas": [p.name for p in entradas]})
        dependencia("Motor perfil documental", "No existe implementador de perfil documental para otra empresa: Desktop bloquea su "
                    "ingreso (FORMATO_DOCUMENTAL_DESCONOCIDO), pero la recepción Mobile/PULL procesa sus guías con el pipeline AZA "
                    "(procesar_archivo sin perfil = PERFIL_AZA): la guía de Andes queda REQUIERE_REVISION con campos AZA",
                  {"ingreso_desktop": str(ingreso)[:300], "fila_andes": {k: estado.get("fila_andes", {}).get(k) for k in
                   ("estado_documental", "motivos_revision_documento", "hora_entrada_aza")}})
        despues = vi.zonas_mbt()
        # LocalAppData/Atlas/acceso es el perfil Chromium de la ventana de acceso (lanzador
        # común a todas las empresas, antes de elegir empresa): no es estado de MBT.
        cambios = {z: sorted(k for k in set(mbt_antes[z]) | set(despues[z])
                             if mbt_antes[z].get(k) != despues[z].get(k) and not (z == "local" and k.startswith("acceso/")))
                   for z in despues}
        registrar("aislamiento", "MBT ficticia (raíz y estado local, fuera del perfil del lanzador) idéntica tras toda la operación de Andes en Desktop",
                  not any(cambios.values()), cambios)
        dependencia("Motor/Desktop atribución", "Resuelto sólo en b1_operador_cli (identidad.actor_operacion): otros escritores que "
                    "Desktop invoca con actor fijo siguen registrando JAVIER_DESKTOP/DESKTOP con identidad exigida",
                    ["confirmar_incidencias_operacionales.py --actor JAVIER_DESKTOP (main.js)",
                     "asociar_evidencia_mobile.py --actor DESKTOP (main.js)",
                     "aplicar_decisiones_multiples.py --actor JAVIER_DESKTOP (por defecto)",
                     "operaciones_conversacionales_cli.py --actor JAVIER_DESKTOP (por defecto)",
                     "acciones_operacionales_cli.py --actor/--confirmado-por (lo fija el llamador)"])
        e.orden(pid, {"accion": "salir"})
    finally:
        e.cerrar_todo()


# -------------------------------------------------------------------------- main
def main() -> int:
    va.EVIDENCIA.mkdir(parents=True, exist_ok=True)
    try:
        preparar()
        fase_plantas_y_mobile()
        fase_recepcion()
        fase_reporte_inicial()
        if CON_DESKTOP:
            fase_desktop()
    finally:
        if vi.W:
            vi.W.cerrar()
    fallas = [r for r in resultados if not r["ok"]]
    commit = lambda d: subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, cwd=d).stdout.strip()
    (va.EVIDENCIA / "validacion_integracion.json").write_text(json.dumps({
        "fecha": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "commits": {"motor": commit(MOTOR), "cloud": commit(CLOUD), "mobile": commit(MOBILE), "desktop": commit(DESKTOP)},
        "total": len(resultados), "fallas": len(fallas), "resultados": resultados, "dependencias_pendientes": dependencias,
        "estado": estado}, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"\n{len(resultados) - len(fallas)}/{len(resultados)} OK · {len(dependencias)} dependencias registradas")
    return 1 if fallas else 0


if __name__ == "__main__":
    raise SystemExit(main())
