"""Validación integrada: plantas de origen configurables por empresa.

Motor real (publicación + PULL) contra el Worker real (test/servidor_local.js
del repo Cloud, D1/R2 en memoria, HTTPS local) y el código real de Mobile
(src/auth.js + src/sync-core.js en Node). MBT frente a Transportes Andes
ficticia. Nada toca Cloudflare, G:, PULL ni datos reales.

  py -3 scripts/validacion_multiempresa/validar_plantas.py <mundo> <repo-cloud> <repo-mobile>

<mundo> se borra y recrea; la evidencia queda en <mundo>/resultado.json.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import textwrap
from datetime import datetime, timedelta, timezone
from pathlib import Path

MOTOR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(MOTOR))

MUNDO, CLOUD, MOBILE = (Path(a).resolve() for a in sys.argv[1:4])
MBT = MUNDO / "drive" / "Atlas"
ANDES = MUNDO / "drive" / "Atlas_empresas" / "transportes-andes-ficticia"
CLOUD_MBT, CLOUD_ANDES = "empresa-prueba-javier", "cloud-andes-ficticia"
TOKEN_MBT, TOKEN_ANDES = "token-motor-mbt-ficticio", "token-motor-andes-ficticio"
OPENSSL = next((p for p in (shutil.which("openssl"), r"C:\Program Files\Git\usr\bin\openssl.exe",
                            r"C:\Program Files\Git\mingw64\bin\openssl.exe") if p and Path(p).is_file()), None)

resultados: list[dict] = []


def registrar(prueba: str, ok: bool, detalle: object = "") -> None:
    resultados.append({"prueba": prueba, "ok": bool(ok), "detalle": detalle})
    print(("OK   " if ok else "FALLA") + f" {prueba}" + ("" if ok else f" :: {str(detalle)[:400]}"), flush=True)


def preparar() -> dict[str, str]:
    if MUNDO.exists():
        shutil.rmtree(MUNDO)
    (MUNDO / "tls").mkdir(parents=True)
    subprocess.run([OPENSSL, "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1", "-subj", "/CN=127.0.0.1",
                    "-addext", "subjectAltName=IP:127.0.0.1", "-keyout", str(MUNDO / "tls" / "key.pem"),
                    "-out", str(MUNDO / "tls" / "cert.pem")], check=True, capture_output=True)
    from atlas_core.catalogo_plantas import CatalogoPlantas
    ids = {}
    mbt = CatalogoPlantas(MBT / "catalogos_privados" / "plantas.json", generador_id=lambda: "mbt-aza-colina")
    mbt.crear(nombre="AZA COLINA", pais="Chile", fuente="validacion", estado_calidad="CONFIRMADA")
    andes = CatalogoPlantas(ANDES / "catalogos_privados" / "plantas.json")
    for nombre, calidad in (("Puerto Norte", "CONFIRMADA"), ("Bodega Lampa", "CONFIRMADA"), ("Patio en evaluación", "PENDIENTE")):
        ids[nombre] = andes.crear(nombre=nombre, pais="Chile", fuente="validacion", estado_calidad=calidad).planta_id
    return ids


class Worker:
    def __init__(self) -> None:
        sha = hashlib.sha256(TOKEN_ANDES.encode()).hexdigest()
        config = {
            "env": {"CLOUD_MOBILE_AUTH_SECRET": "mobile-validacion", "CLOUD_MOTOR_AUTH_SECRET": TOKEN_MBT,
                    "CLOUD_MOTOR_EMPRESA_ID": CLOUD_MBT, "CLOUD_MOTOR_TOKENS_JSON": json.dumps({sha: CLOUD_ANDES}),
                    "CLOUD_MOTOR_DOWNLOAD_SECRET": "descarga-validacion"},
            "usuarios": [
                {"usuario_id": "u-mbt", "empresa_id": CLOUD_MBT, "chofer_id": "chofer-mbt", "nombre_usuario": "chofer.mbt", "password": "ClaveMbt-2026"},
                {"usuario_id": "u-andes", "empresa_id": CLOUD_ANDES, "chofer_id": "chofer-andes", "nombre_usuario": "chofer.andes", "password": "ClaveAndes-2026"},
            ],
            "tls": {"cert": str(MUNDO / "tls" / "cert.pem"), "key": str(MUNDO / "tls" / "key.pem")},
        }
        ruta = MUNDO / "worker.json"
        ruta.write_text(json.dumps(config), encoding="utf-8")
        self.p = subprocess.Popen(["node", str(CLOUD / "test" / "servidor_local.js"), str(ruta)], cwd=CLOUD,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        linea = self.p.stdout.readline().strip()
        if not linea.startswith("LISTO "):
            raise RuntimeError(f"Worker local no arrancó: {linea} {self.p.stderr.read()[:800]}")
        self.url = f"https://127.0.0.1:{linea.split()[1]}"

    def cerrar(self) -> None:
        self.p.terminate()


CLIENTE_MOBILE = textwrap.dedent("""\
    // Código REAL de Mobile: login, catálogo por sesión y armado del envío.
    const [mobile, base, usuario, password, especificacion] = process.argv.slice(2);
    const moduloAuth = require(mobile + "/src/auth.js");
    const { AtlasSyncCore } = require(mobile + "/src/sync-core.js");
    (async () => {
      const config = { apiBaseUrl: base, rutaLoginMobile: "/api/mobile/login" };
      moduloAuth.ATLAS_CONFIG = config;
      const login = await new moduloAuth.AtlasAuth.ProveedorAutenticacionRemota().iniciarSesion(usuario, password, config);
      if (!login.ok) throw new Error("login: " + JSON.stringify(login));
      const plantas = await moduloAuth.AtlasAuth.obtenerPlantas(login.sesion.token);
      const envios = [];
      for (const e of JSON.parse(especificacion)) {
        const blob = new Blob([new Uint8Array([0xff, 0xd8, 0xff, 0xe0, 1, 2, 3])], { type: "image/jpeg" });
        let registro;
        try {
          registro = await AtlasSyncCore.construirRegistroPendiente({ envioId: e.envio_id, blobImagen: blob, tipoNovedad: "",
            guiaFirmadaCorreo: false, plantaOrigen: e.planta });
        } catch (error) { envios.push({ envio_id: e.envio_id, local: String(error.message) }); continue; }
        if (e.capturado_en) registro.capturado_en = e.capturado_en;
        const r = await fetch(base + "/api/mobile/envios", { method: "POST", headers: { Authorization: "Bearer " + login.sesion.token },
          body: AtlasSyncCore.construirFormData(Object.assign({}, registro, { imagen: blob })) });
        envios.push({ envio_id: e.envio_id, status: r.status, cuerpo: await r.json() });
      }
      console.log("@@" + JSON.stringify({ plantas, envios }));
    })().catch((e) => { console.error(e); process.exit(1); });
    """)


def mobile(w: Worker, usuario: str, password: str, envios: list[dict]) -> dict:
    script = MUNDO / "cliente_mobile.cjs"
    script.write_text(CLIENTE_MOBILE, encoding="utf-8")
    env = {**os.environ, "NODE_EXTRA_CA_CERTS": str(MUNDO / "tls" / "cert.pem")}
    r = subprocess.run(["node", str(script), MOBILE.as_posix(), w.url, usuario, password, json.dumps(envios)],
                       capture_output=True, text=True, encoding="utf-8", env=env, timeout=120)
    for linea in reversed(r.stdout.splitlines()):
        if linea.startswith("@@"):
            return json.loads(linea[2:])
    raise RuntimeError(f"cliente Mobile falló: {r.stderr[-1500:]}")


def publicar(w: Worker, raiz: Path, token: str) -> dict:
    from atlas_core.cloud_plantas_mobile import publicar_plantas_cloud
    return publicar_plantas_cloud(base_url=w.url, token_motor=token, raiz=raiz, timeout=20, puede_continuar=lambda: True)


def pull(w: Worker, raiz: Path, token: str) -> dict:
    from atlas_core.cloud_mobile_sync_cliente import sincronizar_envios_cloud
    from atlas_core.mobile import RepositorioEnviosMobile
    return sincronizar_envios_cloud(base_url=w.url, token_motor=token, consumidor="validacion-plantas",
                                    repositorio=RepositorioEnviosMobile(raiz), timeout=20, procesar=False)


def plantas_aterrizadas(raiz: Path) -> dict[str, str]:
    salida = {}
    for registro in raiz.rglob("envio.json"):
        datos = json.loads(registro.read_text(encoding="utf-8"))
        salida[datos.get("envio_id", registro.parent.name)] = datos.get("planta_origen_informada")
    return salida


def contiene(raiz: Path, textos: list[str]) -> list[str]:
    hallados = []
    for p in raiz.rglob("*"):
        if p.is_file() and p.name != "plantas.json":
            datos = p.read_bytes()
            hallados += [f"{p.relative_to(raiz)}:{t}" for t in textos if t.encode() in datos]
    return hallados


def main() -> int:
    ids = preparar()
    os.environ["SSL_CERT_FILE"] = str(MUNDO / "tls" / "cert.pem")
    norte, lampa, pendiente = ids["Puerto Norte"], ids["Bodega Lampa"], ids["Patio en evaluación"]
    w = Worker()
    try:
        r = publicar(w, MBT, TOKEN_MBT)
        registrar("MBT no publica catálogo (conserva AZA)", r.get("publicadas") is None and "omitido" in r, r)
        r = publicar(w, ANDES, TOKEN_ANDES)
        registrar("Andes publica sus 2 plantas confirmadas (no la pendiente)", r == {"publicadas": 2, "cambios": 2}, r)
        r = publicar(w, ANDES, TOKEN_ANDES)
        registrar("republicar sin cambios no escribe", r.get("cambios") == 0, r)

        antes_baja = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        m = mobile(w, "chofer.mbt", "ClaveMbt-2026", [
            {"envio_id": "guia-mbt-colina-0001", "planta": "AZA_COLINA"},
            {"envio_id": "guia-mbt-cruce-0001", "planta": norte},
        ])
        registrar("Mobile MBT recibe Colina/Renca", m["plantas"] == [{"planta_id": "AZA_COLINA", "nombre": "Colina"}, {"planta_id": "AZA_RENCA", "nombre": "Renca"}], m["plantas"])
        estados = {e["envio_id"]: e.get("status") for e in m["envios"]}
        registrar("MBT envía AZA_COLINA (200) y no una planta de Andes (400)",
                  estados == {"guia-mbt-colina-0001": 200, "guia-mbt-cruce-0001": 400}, m["envios"])

        a = mobile(w, "chofer.andes", "ClaveAndes-2026", [
            {"envio_id": "guia-andes-norte-0001", "planta": norte},
            {"envio_id": "guia-andes-aza-0001", "planta": "AZA_COLINA"},
            {"envio_id": "guia-andes-pendiente-0001", "planta": pendiente},
        ])
        registrar("Mobile Andes recibe sólo su catálogo, por nombre",
                  a["plantas"] == [{"planta_id": lampa, "nombre": "Bodega Lampa"}, {"planta_id": norte, "nombre": "Puerto Norte"}], a["plantas"])
        estados = {e["envio_id"]: e.get("status") for e in a["envios"]}
        registrar("Andes: su planta 200; AZA_COLINA y planta no publicada 400",
                  estados == {"guia-andes-norte-0001": 200, "guia-andes-aza-0001": 400, "guia-andes-pendiente-0001": 400}, a["envios"])

        # Baja de Bodega Lampa en el catálogo de Andes tras una captura offline.
        from atlas_core.catalogo_plantas import CatalogoPlantas
        CatalogoPlantas(ANDES / "catalogos_privados" / "plantas.json").desactivar(lampa, modificacion_manual=True)
        r = publicar(w, ANDES, TOKEN_ANDES)
        # 2 cambios: desactiva Bodega Lampa y Puerto Norte pasa a ser la primera.
        registrar("baja publicada (queda 1 planta)", r == {"publicadas": 1, "cambios": 2}, r)
        despues = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat().replace("+00:00", "Z")
        b = mobile(w, "chofer.andes", "ClaveAndes-2026", [
            {"envio_id": "guia-andes-offline-0001", "planta": lampa, "capturado_en": antes_baja},
            {"envio_id": "guia-andes-tras-baja-0001", "planta": lampa, "capturado_en": despues},
        ])
        registrar("tras la baja Mobile ya no ofrece Bodega Lampa", b["plantas"] == [{"planta_id": norte, "nombre": "Puerto Norte"}], b["plantas"])
        estados = {e["envio_id"]: e.get("status") for e in b["envios"]}
        registrar("cola offline capturada antes de la baja se recibe; captura posterior se rechaza",
                  estados == {"guia-andes-offline-0001": 200, "guia-andes-tras-baja-0001": 400}, b["envios"])

        p_mbt = pull(w, MBT, TOKEN_MBT)
        p_andes = pull(w, ANDES, TOKEN_ANDES)
        # Sin OCR (procesar=False) el PULL persiste y valida; confirma a Cloud tras procesar.
        resumen = {n: {k: p.get(k) for k in ("encontrados", "persistidos", "fallidos")} for n, p in (("mbt", p_mbt), ("andes", p_andes))}
        registrar("PULL de cada empresa persiste sólo lo suyo, sin rechazos del Motor",
                  sorted(p_mbt.get("persistidos") or []) == ["guia-mbt-colina-0001"]
                  and sorted(p_andes.get("persistidos") or []) == ["guia-andes-norte-0001", "guia-andes-offline-0001"]
                  and not p_mbt.get("fallidos") and not p_andes.get("fallidos"), resumen)
        registrar("Motor MBT aterriza su envío con AZA_COLINA", plantas_aterrizadas(MBT) == {"guia-mbt-colina-0001": "AZA_COLINA"}, plantas_aterrizadas(MBT))
        registrar("Motor Andes aterriza sus envíos con sus planta_id (incluida la dada de baja después)",
                  plantas_aterrizadas(ANDES) == {"guia-andes-norte-0001": norte, "guia-andes-offline-0001": lampa}, plantas_aterrizadas(ANDES))
        registrar("aislamiento: ningún ID de Andes en MBT ni código AZA en Andes",
                  not contiene(MBT, [norte, lampa]) and not contiene(ANDES, ["AZA_COLINA", "AZA_RENCA"]),
                  contiene(MBT, [norte, lampa]) + contiene(ANDES, ["AZA_COLINA", "AZA_RENCA"]))
    finally:
        w.cerrar()
    commits = {n: subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, cwd=d).stdout.strip()
               for n, d in (("motor", MOTOR), ("cloud", CLOUD), ("mobile", MOBILE))}
    fallas = [r for r in resultados if not r["ok"]]
    (MUNDO / "resultado.json").write_text(json.dumps({"commits": commits, "resultados": resultados}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n{len(resultados) - len(fallas)}/{len(resultados)} aprobadas · {commits}")
    return 1 if fallas else 0


if __name__ == "__main__":
    raise SystemExit(main())
