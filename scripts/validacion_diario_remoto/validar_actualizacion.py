"""Validación aislada P0.5: dos equipos en versiones distintas se actualizan
solos al iniciar, con cortes, versión rota y vuelta atrás. SOLO PRUEBA.

Worker b28d594 real sobre D1/R2 en memoria. Motor de cada equipo = clon git
real del Motor (origin = repositorio bare local, nunca GitHub) con su
actualizar_atlas.py; Desktop = carpeta resources con app.asar sintético.

  python scripts/validacion_diario_remoto/validar_actualizacion.py <cloud_dir> <salida_dir>

Versiones (rama local prueba/actualizacion del origin de prueba):
  C1 = HEAD de esta rama (nivel de custodia 1); C2 = C1 con nivel 2;
  C3 = C2 roto (el Motor no importa).
1. X en C2 + Desktop v2 siembra y publica la versión C2 (nivel 2 + Desktop v2).
2. Y en C1 + Desktop v1 no puede escribir (MOTOR_INCOMPATIBLE).
3. Y inicia y se corta a mitad (tras aplicar el Motor): queda a medias.
4. Y inicia de nuevo: revierte solo, reintenta y queda en C2 + Desktop v2;
   luego trabaja normalmente.
5. X publica C3 (roto): Y revierte a C2 dos veces y luego lo omite; sigue
   trabajando en C2.
6. Worker con protocolo_minimo=3: un Motor de protocolo anterior no obtiene
   lease; el actual sí.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import struct
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import validar as v  # noqa: E402

RAMA = "prueba/actualizacion"


def git(cwd: Path, *args: str) -> str:
    r = subprocess.run(["git", "-c", "user.name=prueba", "-c", "user.email=prueba@example.invalid",
                        "-c", "core.autocrlf=false", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8")
    if r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {r.stderr}")
    return r.stdout.strip()


def asar(contenido: dict[str, bytes]) -> bytes:
    archivos, offset, datos = {}, 0, b""
    for nombre, cuerpo in contenido.items():
        archivos[nombre] = {"size": len(cuerpo), "offset": str(offset)}
        offset += len(cuerpo)
        datos += cuerpo
    indice = json.dumps({"files": archivos}).encode()
    relleno = indice + b"\0" * (-len(indice) % 4)
    payload = 4 + len(relleno)
    return struct.pack("<4I", 4, payload + 4, payload, len(indice)) + relleno + datos


def desktop(recursos: Path, version: str) -> None:
    (recursos / "app.asar.unpacked" / "src").mkdir(parents=True, exist_ok=True)
    (recursos / "app.asar").write_bytes(asar({"main.js": f"desktop {version}".encode(), "index.html": b"<html/>"}))
    (recursos / "app.asar.unpacked" / "src" / "consulta_python.py").write_text(f"# {version}\n", encoding="utf-8")


def sha(ruta: Path) -> str:
    return hashlib.sha256(ruta.read_bytes()).hexdigest()


class EquipoInstalado:
    def __init__(self, nombre: str, worker, origen: Path, commit: str, version_desktop: str):
        self.dir = v.MUNDO / f"equipo-{nombre}"
        self.motor, self.recursos, self.raiz = self.dir / "motor", self.dir / "resources", self.dir / "Atlas"
        git(v.MUNDO, "clone", "-q", "--shared", str(origen), str(self.motor))
        git(self.motor, "checkout", "-q", "-B", "instalado", commit)
        desktop(self.recursos, version_desktop)
        self.env = v.entorno(worker, self.dir / "local")
        self.env["PYTHONPATH"] = str(self.motor)

    def correr(self, *args: str, extra: dict | None = None, timeout: int = 600) -> tuple[int, dict | None, str]:
        r = subprocess.run([sys.executable, "-B", *args], cwd=self.motor, env={**self.env, **(extra or {})},
                           capture_output=True, text=True, encoding="utf-8", timeout=timeout)
        lineas = [l for l in r.stdout.strip().splitlines() if l.startswith("{")]
        try:
            return r.returncode, json.loads(lineas[-1]) if lineas else None, (r.stdout + r.stderr)[-2500:]
        except ValueError:
            return r.returncode, None, (r.stdout + r.stderr)[-2500:]

    def iniciar(self, extra: dict | None = None):
        """Lo que hace scripts/iniciar_atlas.ps1 antes de abrir Desktop."""
        return self.correr("actualizar_atlas.py", "--desktop-recursos", str(self.recursos), "--raiz-atlas", str(self.raiz),
                           "--proceso-desktop", "AtlasPruebaInexistente.exe", extra=extra)

    def turno(self):
        r = subprocess.run([sys.executable, "-B", str(self.motor / "scripts" / "validacion_diario_remoto" / "equipo.py"),
                            "turno", str(self.raiz)], cwd=self.motor, env=self.env, capture_output=True, text=True,
                           encoding="utf-8", timeout=600)
        return (r.stdout.strip().splitlines() or [""])[-1] or r.stderr[-1500:]

    def head(self) -> str:
        return git(self.motor, "rev-parse", "HEAD")

    def unpacked(self) -> str:
        return (self.recursos / "app.asar.unpacked" / "src" / "consulta_python.py").read_text(encoding="utf-8")


def main() -> int:
    if v.MUNDO.exists():
        shutil.rmtree(v.MUNDO)
    v.MUNDO.mkdir(parents=True)
    worker = v.Worker()
    try:
        assert worker.url.startswith("https://127.0.0.1:")
        # Origin de prueba con C1, C2 (nivel 2) y C3 (roto).
        c1 = git(v.MOTOR, "rev-parse", "HEAD")
        origen, taller = v.MUNDO / "origin.git", v.MUNDO / "taller"
        git(v.MUNDO, "clone", "-q", "--bare", "--shared", str(v.MOTOR), str(origen))
        git(v.MUNDO, "clone", "-q", "--shared", str(origen), str(taller))
        git(taller, "checkout", "-q", "-b", RAMA, c1)
        modulo = taller / "atlas_core" / "actualizacion_atlas.py"
        texto = modulo.read_text(encoding="utf-8")
        assert "NIVEL_CUSTODIA = 1\n" in texto.replace("\r\n", "\n")
        modulo.write_bytes(modulo.read_bytes().replace(b"NIVEL_CUSTODIA = 1", b"NIVEL_CUSTODIA = 2"))
        git(taller, "commit", "-q", "-am", "prueba: nivel de custodia 2")
        c2 = git(taller, "rev-parse", "HEAD")
        roto = taller / "atlas_core" / "escritor_operativo.py"
        roto.write_bytes(roto.read_bytes() + b"\nraise RuntimeError('version rota de prueba')\n")
        git(taller, "commit", "-q", "-am", "prueba: version rota")
        c3 = git(taller, "rev-parse", "HEAD")
        git(taller, "push", "-q", "origin", RAMA)

        x = EquipoInstalado("x", worker, origen, c2, "v2")
        y = EquipoInstalado("y", worker, origen, c1, "v1")
        v.raiz_inicial(x.raiz)
        shutil.copytree(x.raiz, y.raiz)
        asar_v1, asar_v2 = sha(y.recursos / "app.asar"), sha(x.recursos / "app.asar")

        # 1. X siembra y publica C2 + Desktop v2, nivel 2.
        codigo, r, salida = x.correr("-m", "atlas_core.estado_confirmado", "--raiz-atlas", str(x.raiz), "--sembrar")
        v.registrar("X (C2) siembra la custodia", codigo == 0 and r and r.get("sembrado"), r or salida)
        codigo, r, salida = x.correr("actualizar_atlas.py", "--publicar", "--version", "2026.11.27-2", "--rama", RAMA,
                                     "--commit", c2, "--desktop-recursos", str(x.recursos), "--nivel-minimo", "2",
                                     "--raiz-atlas", str(x.raiz))
        v.registrar("X publica la versión C2 + Desktop v2 (nivel 2)", codigo == 0 and r and r.get("publicada") == "2026.11.27-2",
                    r or salida)

        # 2. Y (C1, nivel 1) no escribe.
        worker.avanzar(11 * 60)
        version = worker.version()
        linea = y.turno()
        v.registrar("Y en C1 no puede escribir (MOTOR_INCOMPATIBLE)", "MOTOR_INCOMPATIBLE" in linea and worker.version() == version, linea)

        # 3. Y inicia y se corta tras aplicar el Motor.
        codigo, r, salida = y.iniciar({"ATLAS_PRUEBA_CORTE_ACTUALIZACION": "motor"})
        v.registrar("inicio de Y cortado a mitad (código 9): Motor nuevo, Desktop viejo, diario pendiente",
                    codigo == 9 and y.head() == c2 and sha(y.recursos / "app.asar") == asar_v1
                    and (y.dir / "local" / "Atlas" / "actualizacion" / "actualizacion_en_curso.json").is_file(),
                    {"codigo": codigo, "salida": salida[-400:]})

        # 4. Y inicia de nuevo, sin intervención.
        codigo, r, salida = y.iniciar()
        v.registrar("siguiente inicio: revierte el corte y completa la actualización",
                    codigo == 0 and r and r.get("recuperacion", {}).get("estado") == "REVERTIDA_TRAS_CORTE"
                    and r["recuperacion"]["reversion"]["motor"] == c1 and r.get("estado") == "ACTUALIZADA", r or salida)
        v.registrar("Y queda en C2 + Desktop v2 (asar y unpacked)", y.head() == c2 and sha(y.recursos / "app.asar") == asar_v2
                    and y.unpacked() == "# v2\n" and sha(y.recursos / "app.asar.antes-2026.11.27-2") == asar_v1)
        worker.avanzar(60)
        linea = y.turno()
        v.registrar("Y trabaja con la versión nueva", linea.startswith("TURNO "), linea)
        codigo, r, _s = y.iniciar()
        v.registrar("inicio siguiente: AL_DIA", r and r.get("estado") == "AL_DIA", r)

        # 5. Versión rota.
        worker.avanzar(11 * 60)
        codigo, r, salida = x.correr("actualizar_atlas.py", "--publicar", "--version", "2026.11.27-3", "--rama", RAMA,
                                     "--commit", c3, "--desktop-recursos", str(x.recursos), "--nivel-minimo", "2",
                                     "--raiz-atlas", str(x.raiz))
        v.registrar("X publica C3 (rota)", codigo == 0 and r and r.get("publicada") == "2026.11.27-3", r or salida)
        estados = []
        for _ in range(3):
            codigo, r, salida = y.iniciar()
            estados.append((r or {}).get("estado"))
            v.registrar(f"inicio de Y con C3 publicado ({len(estados)}): queda en C2 + Desktop v2",
                        y.head() == c2 and sha(y.recursos / "app.asar") == asar_v2, r or salida)
        v.registrar("C3 se revierte dos veces y luego se omite (sin bucle)",
                    estados == ["REVERTIDA", "REVERTIDA", "VERSION_FALLIDA_OMITIDA"], estados)
        worker.avanzar(11 * 60)
        linea = y.turno()
        v.registrar("Y sigue trabajando en C2 tras la versión rota", linea.startswith("TURNO "), linea)

        # 6. Protocolo: el Worker deja fuera a un Motor anterior.
        worker.p.stdin.write("sql UPDATE estado_operativo_marca SET protocolo_minimo = 3\n")
        worker.p.stdin.flush()
        v.registrar("Worker con protocolo_minimo=3", worker.p.stdout.readline().startswith("SQL OK"))
        worker.avanzar(60)
        codigo, r, salida = y.correr("-c", (
            "import json; from atlas_core import estado_confirmado as ec; ec.PROTOCOLO = 2; "
            "from atlas_core.escritor_operativo import lease_desde_entorno; "
            f"l = lease_desde_entorno(raiz=r'{y.raiz}'); ok = l.adquirir(); l.cerrar(); "
            "print(json.dumps({'adquirido': ok, 'motivo': l.motivo}))"))
        v.registrar("Motor de protocolo 2 no obtiene lease", r == {"adquirido": False, "motivo": "ESCRITOR_PROTOCOLO_OBSOLETO"},
                    r or salida)
        linea = y.turno()
        v.registrar("Motor actual (protocolo 3) sí trabaja", linea.startswith("TURNO "), linea)
    finally:
        worker.cerrar()
        (v.SALIDA / "validacion_actualizacion.json").write_text(json.dumps(v.CHECKS, ensure_ascii=False, indent=2),
                                                               encoding="utf-8")
    fallas = [c for c in v.CHECKS if not c["ok"]]
    print(f"{len(v.CHECKS) - len(fallas)}/{len(v.CHECKS)} checks aprobados", flush=True)
    return 1 if fallas else 0


if __name__ == "__main__":
    raise SystemExit(main())
