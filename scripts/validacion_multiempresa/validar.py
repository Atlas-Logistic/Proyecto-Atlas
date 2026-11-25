"""Primera validación operativa multiempresa (25/11/2026).

Habilita una segunda empresa FICTICIA (``andes-prueba``) junto a una MBT
FICTICIA, en un mundo sintético local, y demuestra el aislamiento efectivo con
la arquitectura multiempresa existente (``aislamiento_empresas``, Worker con
``CLOUD_MOTOR_TOKENS_JSON``, selector de empresa de Desktop). No crea
mecanismos nuevos: cada etapa corre en un proceso con el entorno de su empresa,
como lo lanzan Desktop y el PULL.

    python scripts/validacion_multiempresa/validar.py <mundo> <checkout cloud>

Nunca toca G:, el LOCALAPPDATA real, Cloudflare ni datos de MBT: ``<mundo>`` se
recrea desde cero y el Worker es el real sobre SQLite en memoria
(``test/servidor_local.js`` del repositorio Cloud). Escribe
``<mundo>/../evidencia/validacion.json`` y sale con código 1 si algo falla.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

MOTOR = Path(__file__).resolve().parents[2]
MUNDO = Path(sys.argv[1]).resolve()
CLOUD = Path(sys.argv[2]).resolve()
EVIDENCIA = MUNDO.parent / "evidencia"

DRIVE = MUNDO / "drive"
MBT = DRIVE / "Atlas"
ANDES_ID, ANDES_NOMBRE, ANDES_CLOUD = "andes-prueba", "Transportes Andes (ficticia)", "cloud-andes-prueba"
ANDES = DRIVE / "Atlas_empresas" / ANDES_ID
LOCAL = MUNDO / "LocalAppData"
CLOUD_MBT = "empresa-prueba-javier"  # identificador Cloud que el Motor asigna a MBT
TOKEN_MBT, TOKEN_ANDES = "token-motor-mbt-ficticio", "token-motor-andes-ficticio"
# Marcadores únicos: cualquier aparición fuera de su empresa es contaminación.
MARCA = {"mbt": "MBTMARCA", ANDES_ID: "ANDESMARCA"}
GUIA_COMUN, TRANSPORTE_COMUN, RUT_COMUN, PATENTE_COMUN = "900001", "0000900001", "12.345.678-5", "KN5439"

resultados: list[dict] = []


def registrar(etapa: str, prueba: str, ok: bool, detalle: object = "") -> None:
    resultados.append({"etapa": etapa, "prueba": prueba, "ok": bool(ok), "detalle": detalle.decode("utf-8", "replace") if isinstance(detalle, bytes) else detalle})
    print(("OK   " if ok else "FALLA") + f" [{etapa}] {prueba}" + ("" if ok else f" :: {str(detalle)[:600]}"), flush=True)


def entorno(empresa: str, **extra: str) -> dict[str, str]:
    """Entorno de un proceso del Motor de `empresa`, sin ninguna variable ATLAS_* real."""
    env = {k: v for k, v in os.environ.items() if not k.startswith(("ATLAS_", "OPENROUTER", "CLOUD_"))}
    env.update(PYTHONPATH=str(MOTOR), LOCALAPPDATA=str(LOCAL), PYTHONIOENCODING="utf-8", PYTHONUTF8="1",
               ATLAS_CLOUD_MOTOR_TOKEN=TOKEN_MBT, SSL_CERT_FILE=str(MUNDO / "tls" / "cert.pem"))
    if empresa == "mbt":
        env.update(ATLAS_DATA_DIR=str(MBT), ATLAS_OPERACION_CONFIG=str(LOCAL / "Atlas" / "desktop_operacion.json"),
                   ATLAS_PULL_AUTORIZACION=str(LOCAL / "Atlas" / "pull_autorizacion.json"))
    else:
        env.update(ATLAS_DATA_DIR=str(ANDES), ATLAS_EMPRESA_ID=ANDES_ID, ATLAS_RAIZ_MBT=str(MBT),
                   ATLAS_CLOUD_MOTOR_TOKEN__ANDES_PRUEBA=TOKEN_ANDES)
    env.update(extra)
    return env


PRELUDIO = textwrap.dedent("""\
    import os, sys, json, csv, hashlib
    from pathlib import Path
    import atlas_core
    import atlas_core.aislamiento_empresas as ae
    RAIZ = Path(os.environ["ATLAS_DATA_DIR"])
    MBT, ANDES = Path(sys.argv[1]), Path(sys.argv[2])
    def vetado(f):
        try:
            f()
        except ae.ErrorAislamiento as e:
            return e.codigo
        return None
    """)


def python(empresa: str, cuerpo: str, **extra: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-B", "-c", PRELUDIO + textwrap.dedent(cuerpo), str(MBT), str(ANDES)],
                          capture_output=True, text=True, encoding="utf-8", env=entorno(empresa, **extra),
                          cwd=MOTOR, timeout=600)


def python_json(empresa: str, cuerpo: str, **extra: str) -> dict:
    r = python(empresa, cuerpo, **extra)
    for linea in reversed(r.stdout.splitlines()):
        if linea.startswith("@@"):
            return json.loads(linea[2:])
    raise RuntimeError(f"sin resultado ({r.returncode}): {r.stderr[-2500:]}\n{r.stdout[-800:]}")


def cli(empresa: str, *args: str, **extra: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-B", *args], capture_output=True, text=True, encoding="utf-8",
                          env=entorno(empresa, **extra), cwd=MOTOR, timeout=600)


def inventario(raiz: Path, excluir: tuple[Path, ...] = ()) -> dict[str, str]:
    salida = {}
    for p in sorted(raiz.rglob("*")):
        if p.is_file() and not any(p.is_relative_to(x) for x in excluir):
            salida[p.relative_to(raiz).as_posix()] = hashlib.sha256(p.read_bytes()).hexdigest()
    return salida


def buscar_marcador(raiz: Path, marcador: str, excluir: tuple[Path, ...] = ()) -> list[str]:
    """Archivos bajo `raiz` que contienen `marcador` en UTF-8, UTF-16 o JSON escapado."""
    formas = {marcador.encode("utf-8"), marcador.encode("utf-16-le")}
    hallados = []
    if not raiz.exists():
        return hallados
    for p in raiz.rglob("*"):
        if p.is_file() and not any(p.is_relative_to(x) for x in excluir):
            datos = p.read_bytes()
            if any(f in datos for f in formas):
                hallados.append(str(p.relative_to(raiz)))
    return hallados


# ----------------------------------------------------------------- 0. datos
SEMBRAR = """
    from atlas_core.procesamiento_masivo import COLUMNAS
    from atlas_core.catalogo_clientes import CatalogoClientes, EstadoCalidadCliente
    from atlas_core.decisiones_pendientes import generar_artefacto
    from atlas_core import almacenamiento_portable as ap
    M = MARCA_EMPRESA
    cat = RAIZ / "catalogos_privados"; actual = RAIZ / "operacion" / "actual"
    cat.mkdir(parents=True, exist_ok=True); actual.mkdir(parents=True, exist_ok=True)
    def escribir(nombre, valor):
        ap.escribir_json_atomico(cat / nombre, valor)
    escribir("choferes.json", {
        "123456785": {"nombre": f"LUIS {M} REYES", "rut": RUT_COMUN, "aliases": [], "activo": True},
        "222222222": {"nombre": f"ANA {M} SOTO", "rut": "22.222.222-2", "aliases": [], "activo": False}})
    from tests.test_acciones_operacionales import _vehiculo
    def vehiculo(p):
        v = _vehiculo(p); v["observaciones"] = f"tracto {M}"; return v
    escribir("vehiculos.json", {"version": 1, "vehiculos": [vehiculo(PATENTE_COMUN), vehiculo("ZZ" + ("1111" if M == "MBTMARCA" else "2222"))]})
    escribir("clientes.json", {"version_formato": 1, "clientes": []})
    escribir("destinos_maestros.json", {"version_formato": 1, "destinos": []})
    escribir("obras_destinos.json", {"version_formato": 1, "obras": [], "relaciones": []})
    for nombre, contenido in {"empresas.json": {}, "plantas.json": {"plantas": []}, "rutas.json": {"rutas": []}}.items():
        escribir(nombre, contenido)
    CatalogoClientes(cat / "clientes.json").crear(razon_social=f"CONSTRUCTORA {M} SA", rut="76.111.111-6", fuente="PRUEBA",
                                                    estado_calidad=EstadoCalidadCliente.CONFIRMADO)
    def fila(guia, transporte, peso, **extra):
        f = {c: "" for c in COLUMNAS}
        f.update({"archivo": f"{guia}.jpeg", "estado_procesamiento": "OK", "numero_guia": guia, "numero_transporte": transporte,
                  "cliente": f"CONSTRUCTORA {M} SA", "rut_cliente": "76.111.111-6", "chofer": f"LUIS {M} REYES",
                  "rut_chofer": RUT_COMUN, "patente_tracto": PATENTE_COMUN, "obra_destino": f"OBRA {M}",
                  "despachar_a_crudo": f"CALLE {M} 200 SANTIAGO", "estado_ruta": "RUTA_CALCULADA", "peso_kg": peso,
                  "descripcion_material": f"ARIDO {M}", "fecha": "20-11-2026", "distancia_km": "31.2", "duracion_min": "44"})
        f.update(extra)
        return f
    filas = FILAS
    dataset = actual / "analisis_completo_guias.csv"
    with dataset.open("w", newline="", encoding="utf-8-sig") as h:
        w = csv.DictWriter(h, fieldnames=COLUMNAS, delimiter=";"); w.writeheader(); w.writerows(filas)
    ap.escribir_json_atomico(actual / "decisiones_aplicadas.json", {"schema_version": 1, "aplicaciones": []})
    generar_artefacto(ruta_dataset=dataset, carpeta_catalogos=cat, decisiones=[])
    print("@@" + json.dumps({"filas": len(filas)}))
"""
FILAS = {
    "mbt": '[fila(GUIA_COMUN, TRANSPORTE_COMUN, "28000"), fila("900003", "0000900003", "27500")]',
    ANDES_ID: '[fila(GUIA_COMUN, TRANSPORTE_COMUN, "1245", motivos_revision_documento="PESO_OPERACIONALMENTE_ATIPICO", '
              'indicador_revision="REVISAR", estado_documental="REQUIERE_REVISION"), fila("900002", "0000900002", "26000")]',
}


def sembrar() -> None:
    if MUNDO.exists():
        shutil.rmtree(MUNDO)
    (MBT / "catalogos_privados").mkdir(parents=True)
    LOCAL.mkdir(parents=True)
    # Alta de la segunda empresa con la API existente (marca + raíz propia).
    r = python("mbt", f"""
        c = ae.inicializar_empresa(MBT, "{ANDES_ID}", nombre="{ANDES_NOMBRE}", cloud_id="{ANDES_CLOUD}")
        print("@@" + json.dumps({{"raiz": str(c.raiz), "cloud": c.cloud_id, "registro": c.registro_id,
                                  "empresas": ae.listar_empresas(MBT)}}))
    """)
    alta = json.loads(r.stdout.splitlines()[-1][2:]) if r.returncode == 0 else {"error": r.stderr[-1500:]}
    registrar("alta", "inicializar_empresa crea andes-prueba con marca propia", alta.get("raiz") == str(ANDES)
              and alta.get("empresas") == ["mbt", ANDES_ID], alta)
    for empresa in ("mbt", ANDES_ID):
        cuerpo = (SEMBRAR.replace("MARCA_EMPRESA", repr(MARCA[empresa])).replace("FILAS", FILAS[empresa])
                  .replace("RUT_COMUN", repr(RUT_COMUN)).replace("PATENTE_COMUN", repr(PATENTE_COMUN))
                  .replace("GUIA_COMUN", repr(GUIA_COMUN)).replace("TRANSPORTE_COMUN", repr(TRANSPORTE_COMUN)))
        try:
            registrar("alta", f"{empresa}: choferes, vehículos, cliente y viajes sintéticos", python_json(empresa, cuerpo)["filas"] == 2)
        except RuntimeError as e:
            registrar("alta", f"{empresa}: choferes, vehículos, cliente y viajes sintéticos", False, str(e))
        salida = (MBT if empresa == "mbt" else ANDES) / "reportes" / "vigente-inicial"
        r = cli(empresa, "generar_reporte_viajes.py", str((MBT if empresa == "mbt" else ANDES) / "operacion" / "actual" / "analisis_completo_guias.csv"),
                str(salida), "--catalogos", str((MBT if empresa == "mbt" else ANDES) / "catalogos_privados"))
        registrar("reportes", f"{empresa}: reporte de viajes generado en su raíz", r.returncode == 0 and (salida / "viajes.csv").is_file(),
                  (r.stderr or r.stdout)[-1500:])


# --------------------------------------------------------- 1. Worker local
OPENSSL = next((p for p in (shutil.which("openssl"), r"C:\Program Files\Git\usr\bin\openssl.exe",
                             r"C:\Program Files\Git\ucrt64\bin\openssl.exe") if p and Path(p).is_file()), None)


def certificado_local() -> Path:
    """Certificado autofirmado sólo para 127.0.0.1: el Motor exige HTTPS hacia Cloud
    y sólo los procesos de esta prueba confían en él (SSL_CERT_FILE)."""
    tls = MUNDO / "tls"
    tls.mkdir(parents=True, exist_ok=True)
    subprocess.run([OPENSSL, "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1", "-subj", "/CN=127.0.0.1",
                    "-addext", "subjectAltName=IP:127.0.0.1", "-keyout", str(tls / "key.pem"), "-out", str(tls / "cert.pem")],
                   check=True, capture_output=True)
    return tls


def autorizar_pull() -> None:
    """Política PULL lease_cloud por empresa con el mecanismo existente
    (desktop_operacion.json + pull_autorizacion.json), cada una en SU carpeta local."""
    from datetime import datetime, timedelta, timezone
    vence = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
    for carpeta, raiz in ((LOCAL / "Atlas", MBT), (LOCAL / "Atlas" / "empresas" / ANDES_ID, ANDES)):
        carpeta.mkdir(parents=True, exist_ok=True)
        (carpeta / "desktop_operacion.json").write_text(json.dumps({
            "modo_escritor": "lease_cloud", "autorizada": True, "habilitada": True, "raiz": str(raiz),
            "raiz_mbt": str(MBT), "proyecto": str(MOTOR)}), encoding="utf-8")
        (carpeta / "pull_autorizacion.json").write_text(json.dumps({
            "autor": "Javier", "exclusividad_verificada": True, "modo": "temporal", "habilitada": True,
            "revocada": False, "vence_utc": vence}), encoding="utf-8")


class Worker:
    def __init__(self) -> None:
        config = MUNDO / "worker_config.json"
        tls = certificado_local()
        self.ssl = __import__("ssl").create_default_context(cafile=str(tls / "cert.pem"))
        sha = lambda t: hashlib.sha256(t.encode()).hexdigest()
        config.write_text(json.dumps({
            "env": {"CLOUD_MOTOR_AUTH_SECRET": TOKEN_MBT, "CLOUD_MOTOR_EMPRESA_ID": CLOUD_MBT,
                    "CLOUD_MOBILE_AUTH_SECRET": "secreto-mobile-ficticio",
                    "CLOUD_MOTOR_TOKENS_JSON": json.dumps({sha(TOKEN_ANDES): ANDES_CLOUD})},
            "usuarios": [
                {"usuario_id": "u-mbt-1", "empresa_id": CLOUD_MBT, "chofer_id": "chofer-001", "nombre_usuario": "mbt-chofer-prueba",
                 "nombre_chofer": "LUIS MBTMARCA REYES", "password": "clave-mbt-1"},
                {"usuario_id": "u-andes-1", "empresa_id": ANDES_CLOUD, "chofer_id": "chofer-001", "nombre_usuario": "andes-chofer1",
                 "nombre_chofer": "LUIS ANDESMARCA REYES", "password": "clave-andes-1"}],
            "tls": {"cert": str(tls / "cert.pem"), "key": str(tls / "key.pem")}}), encoding="utf-8")
        self.p = subprocess.Popen(["node", str(CLOUD / "test" / "servidor_local.js"), str(config)], stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, text=True, cwd=CLOUD)
        linea = self.p.stdout.readline().strip()
        if not linea.startswith("LISTO "):
            raise RuntimeError("Worker local no inició: " + linea + self.p.stderr.read()[-1500:])
        self.url = f"https://127.0.0.1:{linea.split()[1]}"

    def pedir(self, metodo: str, ruta: str, token: str | None = None, cuerpo: bytes | None = None,
              tipo: str = "application/json") -> tuple[int, bytes]:
        h = {"content-type": tipo}
        if token:
            h["authorization"] = f"Bearer {token}"
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


def jpeg_sintetico(marcador: str) -> bytes:
    """JPEG mínimo válido con el marcador en un segmento COM."""
    com = f"GUIA SINTETICA {marcador}".encode()
    return (b"\xff\xd8" + b"\xff\xfe" + (len(com) + 2).to_bytes(2, "big") + com +
            bytes.fromhex("ffdb004300") + bytes(range(1, 65)) +
            bytes.fromhex("ffc0000b080001000101011100ffc4001f0000010501010101010100000000000000000102030405060708090a0bffda0008010100003f00d2cf20ffd9"))


def multipart(campos: dict[str, str], archivo: bytes) -> tuple[bytes, str]:
    limite = "----atlas" + uuid.uuid4().hex
    partes = []
    for k, v in campos.items():
        partes.append(f'--{limite}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
    partes.append(f'--{limite}\r\nContent-Disposition: form-data; name="imagen"; filename="guia.jpg"\r\n'
                  f'Content-Type: image/jpeg\r\n\r\n'.encode() + archivo + b"\r\n")
    partes.append(f"--{limite}--\r\n".encode())
    return b"".join(partes), f"multipart/form-data; boundary={limite}"


ENVIO = "guia-900001-prueba"  # mismo envio_id en ambas empresas: colisión deliberada


def mobile(w: Worker) -> dict[str, str]:
    sesiones = {}
    for empresa, usuario, clave in (("mbt", "mbt-chofer-prueba", "clave-mbt-1"), (ANDES_ID, "andes-chofer1", "clave-andes-1")):
        s, b = w.json("POST", "/api/mobile/login", cuerpo={"usuario": usuario, "password": clave})
        registrar("mobile", f"{empresa}: login del chofer", s == 200 and b.get("chofer_id") == "chofer-001", b)
        sesiones[empresa] = b.get("token", "")
        cuerpo, tipo = multipart({"envio_id": ENVIO, "observacion": f"observacion {MARCA[empresa]}",
                                  "planta_origen_informada": "AZA_COLINA", "capturado_en": "2026-11-25T10:00:00Z"},
                                 jpeg_sintetico(MARCA[empresa]))
        s, b = w.pedir("POST", "/api/mobile/envios", sesiones[empresa], cuerpo, tipo)
        registrar("mobile", f"{empresa}: envío de guía con el contrato de la PWA", s == 200, b[:300])
    s, b = w.json("POST", "/api/mobile/login", cuerpo={"usuario": "andes-chofer1", "password": "clave-mbt-1"})
    registrar("acceso-cruzado", "Mobile: clave de MBT no abre el usuario de Andes", s == 401, b)
    for empresa, token in sesiones.items():
        s, _ = w.json("GET", "/api/motor/envios/pendientes", token)
        registrar("acceso-cruzado", f"Mobile: sesión de chofer {empresa} no accede a la API del Motor", s == 401, s)
    envios = w.tabla("envios_cloud")
    docs = w.tabla("documentos_cloud")
    por = {e["empresa_id"]: e for e in envios}
    registrar("mobile", "D1: mismo envio_id guardado una vez por empresa, con la empresa del usuario autenticado",
              sorted(por) == sorted([CLOUD_MBT, ANDES_CLOUD]) and por[ANDES_CLOUD]["usuario_id"] == "u-andes-1"
              and MARCA[ANDES_ID] in por[ANDES_CLOUD]["observacion"] and MARCA["mbt"] in por[CLOUD_MBT]["observacion"], envios)
    registrar("mobile", "R2: cada documento bajo el prefijo de su empresa",
              len(docs) == 2 and all(d["r2_key"].startswith(f"empresas/{d['empresa_id']}/") for d in docs), [d["r2_key"] for d in docs])
    # API del Motor por token: cada empresa ve sólo lo suyo; un token desconocido, nada.
    for empresa, token, cloud in (("mbt", TOKEN_MBT, CLOUD_MBT), (ANDES_ID, TOKEN_ANDES, ANDES_CLOUD)):
        s, b = w.json("GET", "/api/motor/envios/pendientes", token)
        lista = (b or {}).get("envios", []) if isinstance(b, dict) else []
        registrar("acceso-cruzado", f"Worker: token Motor {empresa} lista sólo su envío", s == 200 and len(lista) == 1
                  and MARCA[empresa] in json.dumps(lista, ensure_ascii=False) and MARCA[otra(empresa)] not in json.dumps(lista, ensure_ascii=False), b)
    s, _ = w.json("GET", "/api/motor/envios/pendientes", "token-inventado")
    registrar("acceso-cruzado", "Worker: token Motor desconocido rechazado", s == 401, s)
    s, _ = w.json("GET", f"/api/motor/documentos/doc-{ENVIO}", TOKEN_ANDES)
    s2, b2 = w.pedir("GET", f"/api/motor/documentos/{docs[0]['documento_id']}", TOKEN_ANDES)
    registrar("acceso-cruzado", "Worker: descarga directa con token Andes nunca entrega bytes de MBT",
              MARCA["mbt"].encode() not in b2, {"status": s2})
    return sesiones


def otra(empresa: str) -> str:
    return ANDES_ID if empresa == "mbt" else "mbt"


# ------------------------------------------------------------ 2. PULL
def sembrar_custodia(w: Worker) -> None:
    """Paso de alta documentado (AISLAMIENTO_EMPRESAS.md, Recuperación): la
    primera línea base de cada empresa en Cloud, bajo su propio lease."""
    for empresa, raiz in (("mbt", MBT), (ANDES_ID, ANDES)):
        r = cli(empresa, "-m", "atlas_core.estado_confirmado", "--raiz-atlas", str(raiz), "--sembrar", ATLAS_CLOUD_MOBILE_URL=w.url)
        registrar("alta", f"{empresa}: custodia Cloud sembrada con su token", r.returncode == 0 and '"sembrado": true' in r.stdout,
                  (r.stdout + r.stderr)[-800:])
    marcas = {m["empresa_id"]: m for m in w.tabla("estado_operativo_marca")}
    archivos = w.tabla("estado_operativo_archivos")
    registrar("alta", "D1: una marca de custodia por empresa y archivos sólo bajo su empresa_id",
              sorted(marcas) == sorted([CLOUD_MBT, ANDES_CLOUD]) and all(a["empresa_id"] in marcas for a in archivos)
              and any(a["empresa_id"] == ANDES_CLOUD and "empresa_identidad.json" in a.get("ruta", "") for a in archivos),
              {"marcas": sorted(marcas), "archivos": len(archivos)})


def pull(w: Worker) -> None:
    for empresa, raiz in (("mbt", MBT), (ANDES_ID, ANDES)):
        r = cli(empresa, "sincronizar_mobile_cloud.py", "--sin-procesar", "--base-url", w.url, "--consumidor", f"pc-{empresa}")
        envio = raiz / "operacion" / "mobile" / "envios" / ENVIO
        originales = list(envio.glob("original.*")) if envio.is_dir() else []
        contenido = originales[0].read_bytes() if originales else b""
        registrar("pull", f"{empresa}: PULL descarga sólo su guía a su raíz",
                  r.returncode == 0 and MARCA[empresa].encode() in contenido and MARCA[otra(empresa)].encode() not in contenido,
                  {"rc": r.returncode, "salida": r.stdout[-1200:], "err": r.stderr[-1500:]})
    # Segunda pasada sin envíos nuevos: corre la recuperación incremental (E1).
    r = cli(ANDES_ID, "sincronizar_mobile_cloud.py", "--sin-procesar", "--base-url", w.url, "--consumidor", f"pc-{ANDES_ID}")
    texto = r.stdout + r.stderr
    registrar("pull", "andes: segunda pasada PULL con recuperación incremental sin ErrorAislamiento (E1)",
              r.returncode == 0 and "ACCESO_ENTRE_EMPRESAS" not in texto and "omitida" not in texto, texto[-1500:])
    registrar("pull", "andes: marca de la pasada PULL en su carpeta local, no en la de MBT",
              [str(p.relative_to(LOCAL)) for p in LOCAL.rglob("recuperacion_incremental_ultima_pasada.json")]
              == [str(Path("Atlas", "empresas", ANDES_ID, "cache", "recuperacion_incremental_ultima_pasada.json"))],
              sorted(str(p.relative_to(LOCAL)) for p in LOCAL.rglob("recuperacion_incremental_ultima_pasada.json")))


def pull_token_ajeno() -> None:
    """Proceso Andes con el token de MBT, en un Worker aparte con un envío MBT
    pendiente y sin escritor previo: el lease de otra empresa se rechaza antes
    de descargar y nada de MBT llega a Andes."""
    w = Worker()
    try:
        _s, b = w.json("POST", "/api/mobile/login", cuerpo={"usuario": "mbt-chofer-prueba", "password": "clave-mbt-1"})
        cuerpo, tipo = multipart({"envio_id": "guia-cruce-mbt", "observacion": "cruce MBTMARCA", "planta_origen_informada": "AZA_COLINA"},
                                 jpeg_sintetico(MARCA["mbt"]))
        w.pedir("POST", "/api/mobile/envios", b.get("token"), cuerpo, tipo)
        antes = inventario(ANDES)
        r = cli(ANDES_ID, "sincronizar_mobile_cloud.py", "--sin-procesar", "--base-url", w.url, "--token", TOKEN_MBT)
        texto = r.stdout + r.stderr
        pendiente = [e for e in w.tabla("envios_cloud") if e["envio_id"] == "guia-cruce-mbt"]
        registrar("acceso-cruzado", "PULL: proceso Andes con token de MBT no descarga ni escribe nada de MBT",
                  inventario(ANDES) == antes and not buscar_marcador(ANDES, MARCA["mbt"])
                  and not (ANDES / "operacion" / "mobile" / "envios" / "guia-cruce-mbt").exists()
                  and pendiente and pendiente[0]["estado"] == "RECIBIDO" and not pendiente[0].get("confirmado_en"),
                  {"rc": r.returncode, "motivo": [l for l in texto.splitlines() if "EMPRESA" in l or "motivo" in l][:6]})
    finally:
        w.cerrar()


# ------------------------------------------------------------- 3. B1
def _json_cli(r: subprocess.CompletedProcess) -> tuple[int, dict | str]:
    try:
        return r.returncode, json.loads(r.stdout.strip())
    except ValueError:
        return r.returncode or 1, (r.stdout + r.stderr)[-1200:]


def viajes_vigente(raiz: Path) -> Path:
    estado = json.loads((raiz / "operacion" / "actual" / "estado_operacion.json").read_text(encoding="utf-8"))
    return raiz / estado["reporte_vigente"] / "viajes.csv"


def b1_consulta(empresa: str, raiz: Path, texto: str, viajes: Path | None = None) -> tuple[int, dict | str]:
    """La misma secuencia que Desktop (atlas_viajes.html + main.js): B1 primero
    (atlas:b1-atender) y, si no es suyo, Consultas Atlas (atlas:consultar-atlas)
    sobre el reporte de viajes cargado."""
    rc, r = _json_cli(cli(empresa, "b1_consulta_cli.py", "--raiz-atlas", str(raiz), "--texto", texto))
    if rc != 0 or not isinstance(r, dict) or r.get("estado") != "NO_INTERPRETADA":
        return rc, r
    viajes = viajes or viajes_vigente(raiz)
    return _json_cli(cli(empresa, "consultar_atlas.py", texto, "--viajes", str(viajes), "--incidencias",
                         str(raiz / "catalogos_privados" / "incidencias_documentales.json"), "--raiz-atlas", str(raiz)))


def b1() -> None:
    for empresa, raiz in (("mbt", MBT), (ANDES_ID, ANDES)):
        for pregunta in (f"¿Qué cliente tiene la guía {GUIA_COMUN}?", f"¿Quién es el chofer de la guía {GUIA_COMUN}?"):
            rc, r = b1_consulta(empresa, raiz, pregunta)
            texto = json.dumps(r, ensure_ascii=False)
            registrar("b1", f"{empresa}: «{pregunta}» (folio repetido en ambas) responde sólo con su empresa",
                      rc == 0 and MARCA[empresa] in texto and MARCA[otra(empresa)] not in texto, texto[:700])
        ajena = ANDES if empresa == "mbt" else MBT
        rc, r = b1_consulta(empresa, raiz, f"¿Qué cliente tiene la guía {GUIA_COMUN}?", viajes=viajes_vigente(ajena))
        texto = json.dumps(r, ensure_ascii=False)
        registrar("acceso-cruzado", f"B1 {empresa}: Consultas Atlas sobre el reporte de viajes de la otra empresa bloqueada sin datos ajenos",
                  "ACCESO_ENTRE_EMPRESAS" in texto and MARCA[otra(empresa)] not in texto, texto[-500:])
        try:
            v = python_json(empresa, """
                from atlas_core.b1_operador import OperadorB1
                ajena = ANDES if RAIZ == MBT else MBT
                print("@@" + json.dumps({
                    "operador": vetado(lambda: OperadorB1(ajena).atender("x", "En la guía 900001 el peso correcto es 1 kg")),
                    "dataset": vetado(lambda: (ajena / "operacion" / "actual" / "analisis_completo_guias.csv").read_bytes()),
                    "catalogo": vetado(lambda: (ajena / "catalogos_privados" / "choferes.json").read_text()),
                    "escritura": vetado(lambda: (ajena / "catalogos_privados" / "intruso.json").write_text("x"))}))
            """)
        except RuntimeError as e:
            v = {"error": str(e)}
        registrar("acceso-cruzado", f"B1 {empresa}: corrección, lectura y escritura sobre la otra empresa bloqueadas (ErrorAislamiento)",
                  set(v.values()) == {"ACCESO_ENTRE_EMPRESAS"}, v)
    # Entorno ambiguo: proceso Andes apuntando a la raíz de MBT aborta al importar.
    r = python(ANDES_ID, "print('no debía llegar')", ATLAS_DATA_DIR=str(MBT))
    registrar("acceso-cruzado", "Motor: proceso Andes con ATLAS_DATA_DIR de MBT aborta antes de operar",
              r.returncode != 0 and "no debía llegar" not in r.stdout, r.stderr[-400:])
    # Escritura B1 en Andes con confirmación humana.
    mbt_antes = inventario(MBT)
    try:
        r = python_json(ANDES_ID, """
            from atlas_core.b1_operador import OperadorB1
            b1 = OperadorB1(RAIZ, usuario="OPERADOR_ANDES")
            p = b1.atender("validacion-peso", "En la guía 900001 el peso correcto es 12.450 kg")
            c = b1.atender("validacion-peso", "sí")
            filas = list(csv.DictReader((RAIZ / "operacion/actual/analisis_completo_guias.csv").open(encoding="utf-8-sig"), delimiter=";"))
            ledger = json.loads((RAIZ / "operacion/actual/decisiones_aplicadas.json").read_text(encoding="utf-8"))["aplicaciones"]
            reportes = sorted(RAIZ.rglob("viajes.csv"), key=lambda p: p.stat().st_mtime)
            print("@@" + json.dumps({"preview": p.get("estado"), "confirmacion": c.get("estado"), "mensaje": c.get("mensaje"),
                "peso": next(f["peso_kg"] for f in filas if f["numero_guia"] == "900001"),
                "ledger": [(a.get("campo"), a.get("confirmado_por")) for a in ledger],
                "reporte": reportes[-1].read_text(encoding="utf-8-sig") if reportes else ""}, ensure_ascii=False))
        """)
    except RuntimeError as e:
        registrar("b1", "andes: corrección B1 de peso con confirmación", False, str(e)); return
    registrar("b1", "andes: corrección B1 de peso (preview + confirmación humana) escrita en Andes",
              r["preview"] == "PREVIEW_PENDIENTE" and r["confirmacion"] == "EJECUTADA" and r["peso"] == "12450"
              and ["peso_kg", "OPERADOR_ANDES"] in r["ledger"], {k: r[k] for k in ("preview", "confirmacion", "mensaje", "peso", "ledger")})
    registrar("reportes", "andes: reporte regenerado tras la corrección contiene el peso nuevo y sólo datos de Andes",
              "12450" in r["reporte"] and MARCA[ANDES_ID] in r["reporte"] and MARCA["mbt"] not in r["reporte"], r["reporte"][:400])
    cambios = sorted(set(mbt_antes.items()) ^ set(inventario(MBT).items()))
    registrar("aislamiento", "MBT ficticia byte a byte idéntica tras la escritura B1 en Andes", not cambios, cambios[:10])
    viajes_mbt = sorted(MBT.rglob("viajes.csv"))
    texto_mbt = "".join(p.read_text(encoding="utf-8-sig") for p in viajes_mbt)
    registrar("reportes", "MBT: su reporte conserva su peso (28000) y no contiene datos de Andes",
              "28000" in texto_mbt and MARCA[ANDES_ID] not in texto_mbt and "12450" not in texto_mbt, [str(p) for p in viajes_mbt])


# ------------------------------------------------------- 4. catálogos
def catalogos() -> None:
    for nombre in ("choferes.json", "vehiculos.json", "clientes.json"):
        a = (MBT / "catalogos_privados" / nombre).read_text(encoding="utf-8")
        b = (ANDES / "catalogos_privados" / nombre).read_text(encoding="utf-8")
        registrar("catalogos", f"{nombre}: un archivo por empresa, cada uno sólo con su marcador",
                  MARCA["mbt"] in a and MARCA[ANDES_ID] not in a and MARCA[ANDES_ID] in b and MARCA["mbt"] not in b)
    for empresa, raiz in (("mbt", MBT), (ANDES_ID, ANDES)):
        rc, r = b1_consulta(empresa, raiz, "¿Quiénes están inactivos?")
        texto = json.dumps(r, ensure_ascii=False)
        registrar("catalogos", f"{empresa}: B1 consulta choferes inactivos sólo de su catálogo",
                  rc == 0 and f"ANA {MARCA[empresa]} SOTO" in texto and MARCA[otra(empresa)] not in texto, texto[:500])


# ----------------------------------------------- 5. verificador final
def barrido(etapa: str) -> None:
    local_mbt = LOCAL / "Atlas"
    local_andes = local_mbt / "empresas" / ANDES_ID
    zonas = {
        "mbt": [(MBT, ()), (local_mbt, (local_mbt / "empresas",))],
        ANDES_ID: [(ANDES, ()), (local_andes, ())],
    }
    for empresa, lugares in zonas.items():
        ajeno = MARCA[otra(empresa)]
        hallados = [f"{r.name}/{h}" for r, ex in lugares for h in buscar_marcador(r, ajeno, ex)]
        registrar(etapa, f"barrido: ningún marcador de {otra(empresa)} en raíz ni estado local de {empresa}", not hallados, hallados[:20])
    # Mutación de control: el verificador debe detectar una contaminación inyectada.
    with tempfile.TemporaryDirectory() as t:
        copia = Path(t) / "andes"
        shutil.copytree(ANDES, copia)
        (copia / "operacion" / "actual" / "intruso.json").write_text(json.dumps({"x": MARCA["mbt"]}), encoding="utf-16")
        registrar(etapa, "mutación de control: el barrido detecta un marcador de MBT inyectado en Andes",
                  bool(buscar_marcador(copia, MARCA["mbt"])))


def main() -> int:
    EVIDENCIA.mkdir(parents=True, exist_ok=True)
    sembrar()
    autorizar_pull()
    w = Worker()
    try:
        sembrar_custodia(w)
        mobile(w)
        pull(w)
        (EVIDENCIA / "d1_envios_cloud.json").write_text(json.dumps(w.tabla("envios_cloud"), indent=1, ensure_ascii=False), encoding="utf-8")
        (EVIDENCIA / "d1_documentos_cloud.json").write_text(json.dumps(w.tabla("documentos_cloud"), indent=1), encoding="utf-8")
    finally:
        w.cerrar()
    pull_token_ajeno()
    b1()
    catalogos()
    barrido("aislamiento")
    (EVIDENCIA / "inventario_mbt_ficticia.json").write_text(json.dumps(inventario(MBT), indent=1), encoding="utf-8")
    (EVIDENCIA / "inventario_andes.json").write_text(json.dumps(inventario(ANDES), indent=1), encoding="utf-8")
    fallas = [r for r in resultados if not r["ok"]]
    (EVIDENCIA / "validacion.json").write_text(json.dumps({
        "fecha": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "motor": subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=MOTOR).stdout.strip(),
        "cloud": subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=CLOUD).stdout.strip(),
        "mundo": str(MUNDO), "total": len(resultados), "fallas": len(fallas), "resultados": resultados}, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"\n{len(resultados) - len(fallas)}/{len(resultados)} OK")
    return 1 if fallas else 0


if __name__ == "__main__":
    raise SystemExit(main())
