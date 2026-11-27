"""Validación aislada P0.4: el PULL real (sincronizar_mobile_cloud.py)
recupera solo el turno de un equipo perdido y sigue recibiendo envíos
Mobile. SOLO PRUEBA. Worker b28d594 real sobre D1/R2 en memoria, reloj
desplazable; raíces de trabajo aisladas (P0.3.1).

  python scripts/validacion_diario_remoto/validar_pull.py <cloud_dir> <salida_dir>

1. Drive con la operación; A y B preparan su raíz de trabajo; A siembra.
2. Mobile envía E1. A ingesta una guía, muere (taskkill) y se elimina.
3. PULL de B: recupera el turno de A sin comandos manuales y recibe E1.
4. Segundo PULL: nada que recuperar, sin duplicados.
5. C escribe sin custodiar contenido y muere; Mobile envía E2. PULL de B:
   el turno de C queda en revisión y E2 entra igual; el ciclo siguiente lo
   omite sin reevaluar y recibe E3.
"""
from __future__ import annotations

import io
import json
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import validar as v  # noqa: E402
from validar_lease import descargar, leer, popen  # noqa: E402

DATASET = v.DATASET
CHOFER = {"usuario_id": "u-1", "empresa_id": v.EMPRESA_CLOUD, "chofer_id": "chofer-001",
          "nombre_usuario": "chofer-prueba", "nombre_chofer": "CHOFER PRUEBA", "password": "clave-prueba-1"}


def jpeg(marcador: str) -> bytes:
    com = f"GUIA SINTETICA {marcador}".encode()
    return (b"\xff\xd8" + b"\xff\xfe" + (len(com) + 2).to_bytes(2, "big") + com +
            bytes.fromhex("ffdb004300") + bytes(range(1, 65)) +
            bytes.fromhex("ffc0000b080001000101011100ffc4001f0000010501010101010100000000000000000102030405060708090a0bffda0008010100003f00d2cf20ffd9"))


def enviar_mobile(worker, envio_id: str) -> int:
    import urllib.error
    import urllib.request

    def pedir(ruta, cuerpo, tipo, token=None):
        h = {"content-type": tipo}
        if token:
            h["authorization"] = f"Bearer {token}"
        req = urllib.request.Request(worker.url + ruta, data=cuerpo, method="POST", headers=h)
        try:
            with urllib.request.urlopen(req, timeout=30, context=worker.ssl) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    _s, b = pedir("/api/mobile/login", json.dumps({"usuario": CHOFER["nombre_usuario"], "password": CHOFER["password"]}).encode(),
                  "application/json")
    token = json.loads(b)["token"]
    limite = "----atlas" + uuid.uuid4().hex
    partes = [f'--{limite}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{val}\r\n'.encode()
              for k, val in {"envio_id": envio_id, "planta_origen_informada": "AZA_COLINA",
                             "capturado_en": "2026-11-27T10:00:00Z"}.items()]
    partes.append(f'--{limite}\r\nContent-Disposition: form-data; name="imagen"; filename="guia.jpg"\r\n'
                  f'Content-Type: image/jpeg\r\n\r\n'.encode() + jpeg(envio_id) + b"\r\n")
    partes.append(f"--{limite}--\r\n".encode())
    s, _b = pedir("/api/mobile/envios", b"".join(partes), f"multipart/form-data; boundary={limite}", token)
    return s


def pull(env: dict, raiz: Path) -> tuple[int, dict | None, str]:
    r = subprocess.run([sys.executable, str(v.MOTOR / "sincronizar_mobile_cloud.py"), "--raiz-atlas", str(raiz), "--sin-procesar"],
                       cwd=v.MOTOR, env=env, capture_output=True, text=True, encoding="utf-8", timeout=600)
    texto = r.stdout
    inicio = texto.find("{")
    try:
        return r.returncode, json.loads(texto[inicio:]) if inicio >= 0 else None, r.stderr[-2000:]
    except ValueError:
        return r.returncode, None, (texto + r.stderr)[-2000:]


def guias_cloud(worker) -> list[str]:
    datos = descargar(worker, worker.vigentes()[DATASET])
    import csv
    return [f["numero_guia"] for f in csv.DictReader(io.StringIO(datos.decode("utf-8-sig"), newline=""), delimiter=";")]


def main() -> int:
    if v.MUNDO.exists():
        shutil.rmtree(v.MUNDO)
    v.MUNDO.mkdir(parents=True)
    worker = v.Worker(usuarios=[CHOFER])
    try:
        assert worker.url.startswith("https://127.0.0.1:")
        dirs = {n: v.MUNDO / f"equipo-{n}" for n in "abc"}
        trabajo = {n: d / "Trabajo" / "Atlas" for n, d in dirs.items()}
        publicada = {n: d / "Drive" / "Atlas" for n, d in dirs.items()}
        env = {n: v.entorno(worker, d / "local") for n, d in dirs.items()}

        # 1. Preparación.
        v.raiz_inicial(publicada["a"])
        for n in "bc":
            shutil.copytree(publicada["a"], publicada[n])
        for n in "abc":
            codigo, r, err = v.cli(env[n], "--raiz-atlas", str(trabajo[n]), "--preparar-raiz-trabajo", str(publicada[n]))
            if codigo != 0:
                v.registrar(f"{n.upper()} prepara su raíz de trabajo", False, r or err[-800:])
                return 1
        codigo, sembrado, err = v.cli(env["a"], "--raiz-atlas", str(trabajo["a"]), "--sembrar")
        v.registrar("A siembra la custodia", codigo == 0 and sembrado and sembrado.get("sembrado"), sembrado or err[-800:])

        # 2. Mobile envía E1; A ingesta y se pierde por completo.
        v.registrar("Mobile envía E1", enviar_mobile(worker, "envio-e1") == 200)
        a = popen(env["a"], "trabajar", str(trabajo["a"]), "900001")
        escrito = leer(a, "ESCRITO")
        if escrito is None:
            return 1
        v.matar(a)
        shutil.rmtree(dirs["a"])
        v.registrar("A ingesta 900001, muere sin confirmar y se elimina (raíz, Drive y LOCALAPPDATA)",
                    not dirs["a"].exists() and escrito["pendientes"] == [] and "900001" not in guias_cloud(worker))

        # 3. PULL de B: recuperación automática y recepción de E1.
        worker.avanzar(11 * 60)
        codigo, r1, err = pull(env["b"], trabajo["b"])
        rec = (r1 or {}).get("recuperacion_turnos", {})
        v.registrar("PULL de B termina bien (código 0)", codigo == 0 and r1 is not None, err if r1 is None else r1)
        v.registrar("el PULL recuperó el turno de A sin comandos manuales",
                    [x["diario"] for x in rec.get("recuperados", [])] == [escrito["diario"]]
                    and rec["recuperados"][0]["documentos_recuperados"] == ["mobile/env-900001/original.jpg"], rec)
        vig = worker.vigentes()
        v.registrar("Cloud: guía de A una vez y su diario cerrado", guias_cloud(worker).count("900001") == 1
                    and vig.get(escrito["diario"]) is None)
        v.registrar("el mismo PULL recibió E1", "operacion/mobile/envios/envio-e1/envio.json" in vig
                    and (trabajo["b"] / "operacion/mobile/envios/envio-e1/envio.json").is_file(), (r1 or {}).get("confirmados"))
        v.registrar("Drive de B publica la guía recuperada y E1",
                    "900001" in v.guias(publicada["b"] / DATASET)
                    and (publicada["b"] / "operacion/mobile/envios/envio-e1/envio.json").is_file())

        # 4. Segundo PULL: idempotente.
        worker.avanzar(60)
        codigo, r2, err = pull(env["b"], trabajo["b"])
        rec2 = (r2 or {}).get("recuperacion_turnos")
        v.registrar("segundo PULL: nada que recuperar ni revisar, sin duplicados",
                    codigo == 0 and rec2 == {"recuperados": [], "en_revision": [], "omitidos": 0}
                    and guias_cloud(worker).count("900001") == 1, rec2 or err)

        # 5. C escribe sin custodiar contenido y muere; el PULL sigue.
        worker.avanzar(11 * 60)
        c = popen(env["c"], "escritura_larga", str(trabajo["c"]), "900003")
        abierto = leer(c, "ABIERTO")
        if abierto is None:
            return 1
        v.matar(c)
        v.registrar("Mobile envía E2", enviar_mobile(worker, "envio-e2") == 200)
        worker.avanzar(11 * 60)
        codigo, r3, err = pull(env["b"], trabajo["b"])
        rec3 = (r3 or {}).get("recuperacion_turnos", {})
        revision = rec3.get("en_revision", [])
        v.registrar("el turno de C queda en revisión (contenido no custodiado) y se conserva",
                    [e["diario"] for e in revision] == [abierto["diario"]] and revision[0]["permanente"]
                    and revision[0]["bloqueos"][0]["codigo"] == "CONTENIDO_NO_CUSTODIADO"
                    and worker.vigentes().get(abierto["diario"]) is not None, rec3)
        v.registrar("el mismo PULL recibe E2 (sin bloqueo)", codigo == 0
                    and "operacion/mobile/envios/envio-e2/envio.json" in worker.vigentes(), err if r3 is None else r3.get("confirmados"))
        v.registrar("la escritura parcial de C no entró", "900003" not in guias_cloud(worker))
        v.registrar("Mobile envía E3", enviar_mobile(worker, "envio-e3") == 200)
        worker.avanzar(60)
        codigo, r4, err = pull(env["b"], trabajo["b"])
        rec4 = (r4 or {}).get("recuperacion_turnos", {})
        v.registrar("ciclo siguiente: C omitido sin reevaluar y E3 recibido", codigo == 0 and rec4.get("omitidos") == 1
                    and "operacion/mobile/envios/envio-e3/envio.json" in worker.vigentes(), rec4 or err)
        envios = {e["envio_id"]: e for e in worker.tabla("envios_cloud")}
        # --sin-procesar descarga sin OCR: el envío queda tomado (EN_LEASE);
        # COMPLETADO llega sólo tras el procesamiento, fuera de esta prueba.
        v.registrar("D1: E1, E2 y E3 tomados por el PULL de B (ninguno pendiente)",
                    all(envios.get(e, {}).get("consumo_estado") in ("EN_LEASE", "COMPLETADO")
                        for e in ("envio-e1", "envio-e2", "envio-e3")),
                    {e: envios.get(e, {}).get("consumo_estado") for e in ("envio-e1", "envio-e2", "envio-e3")})
    finally:
        worker.cerrar()
        (v.SALIDA / "validacion_pull.json").write_text(json.dumps(v.CHECKS, ensure_ascii=False, indent=2), encoding="utf-8")
    fallas = [c for c in v.CHECKS if not c["ok"]]
    print(f"{len(v.CHECKS) - len(fallas)}/{len(v.CHECKS)} checks aprobados", flush=True)
    return 1 if fallas else 0


if __name__ == "__main__":
    raise SystemExit(main())
