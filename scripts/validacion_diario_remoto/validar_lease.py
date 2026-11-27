"""Validación aislada P0.3: el escritor anterior no sobrescribe al nuevo
aunque su lease venza a mitad de una escritura y él se crea vigente.
SOLO PRUEBA. Mismo Worker local que validar.py (b28d594 sobre D1/R2 en
memoria, reloj desplazable).

  python scripts/validacion_diario_remoto/validar_lease.py <cloud_dir> <salida_dir>

1. A siembra; B recibe la copia por "Drive".
2. A, sin heartbeat, abre el dataset y escribe media fila (lease vigente).
3. El lease de A vence en Cloud; B lo adquiere e ingesta una guía.
4. A termina su escritura (bytes en SU disco), intenta custodiarla y escribir
   otro archivo, y cierra: todo rechazado por Cloud.
5. "Drive" lleva el dataset de A a B a mitad del turno de B: B se niega a
   escribir sobre él y confirma lo que él escribió, no lo que hay en disco.
6. Siguiente turno de B: la copia de A trae un documento que Cloud no tiene;
   la protección previa del dataset detiene a B sin escribir (requiere
   revisión humana, como el 26/11). Apartada esa copia, B sigue y el turno de
   A no puede recuperarse encima de B.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import validar as v  # noqa: E402  (mismos argumentos: <cloud_dir> <salida_dir>)

DATASET = v.DATASET
CATALOGO = "catalogos_privados/vehiculos.json"


def leer(proceso, prefijo: str) -> dict | None:
    linea = proceso.stdout.readline().strip()
    if not linea.startswith(prefijo + " "):
        v.registrar(f"proceso anuncia {prefijo}", False, linea or proceso.stderr.read()[-2000:])
        return None
    return json.loads(linea.split(" ", 1)[1])


def descargar(worker, sha: str) -> bytes:
    import urllib.request
    req = urllib.request.Request(f"{worker.url}/api/motor/estado/objetos/{sha}", headers={"authorization": f"Bearer {v.TOKEN}"})
    with urllib.request.urlopen(req, timeout=30, context=worker.ssl) as r:
        return r.read()


def seguir(proceso) -> None:
    proceso.stdin.write("seguir\n")
    proceso.stdin.flush()


def popen(env: dict, *args: str):
    return subprocess.Popen([sys.executable, str(Path(v.__file__).with_name("equipo.py")), *args], cwd=v.MOTOR, env=env,
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8")


def main() -> int:
    if v.MUNDO.exists():
        shutil.rmtree(v.MUNDO)
    v.MUNDO.mkdir(parents=True)
    worker = v.Worker()
    try:
        assert worker.url.startswith("https://127.0.0.1:")
        dirs = {n: v.MUNDO / f"equipo-{n}" for n in "ab"}
        raiz = {n: d / "Atlas" for n, d in dirs.items()}
        env = {n: v.entorno(worker, d / "local") for n, d in dirs.items()}
        v.raiz_inicial(raiz["a"])
        codigo, sembrado, err = v.cli(env["a"], "--raiz-atlas", str(raiz["a"]), "--sembrar")
        v.registrar("A siembra la custodia", codigo == 0 and sembrado and sembrado.get("sembrado"), sembrado or err[-800:])
        shutil.copytree(raiz["a"], raiz["b"])
        base = worker.vigentes()

        # 2. A abre una escritura larga con el lease vigente.
        a = popen(env["a"], "escritura_larga", str(raiz["a"]), "900010")
        abierto = leer(a, "ABIERTO")
        if abierto is None:
            return 1
        v.registrar("A escribe media fila del dataset con lease vigente", abierto["vigente_local"] is True, abierto)

        # 3. Vence en Cloud; B adquiere e ingesta.
        worker.avanzar(11 * 60)
        b = popen(env["b"], "turno_pausado", str(raiz["b"]), "900011", "900012")
        pausa = leer(b, "PAUSA")
        if pausa is None:
            return 1
        estado = worker.tabla("escritores_operativos")[0]
        v.registrar("B tiene el lease (otro escritor, época nueva)", estado["escritor_id"] == pausa["escritor_id"]
                    and pausa["escritor_id"] != abierto["escritor_id"], {k: estado[k] for k in ("escritor_id", "epoca")})

        # 4. A termina: sus bytes caen en SU disco, pero nada más pasa.
        seguir(a)
        resultado_a = leer(a, "RESULTADO")
        a.wait(timeout=120)
        if resultado_a is None:
            return 1
        v.registrar("A seguía creyéndose vigente al terminar la escritura", resultado_a["vigente_local_antes"] is True, resultado_a)
        v.registrar("custodiar la escritura de A es rechazado", resultado_a["punto_de_control"] is False)
        v.registrar("otra escritura de A es rechazada y no toca su destino",
                    resultado_a["rechazo_escritura"] in {"EscritorSustituido", "DiarioNoPersistido"} and resultado_a["catalogo_intacto"],
                    resultado_a["rechazo_escritura"])
        vig = worker.vigentes()
        v.registrar("ningún dato de A llegó a Cloud", vig[DATASET] == base[DATASET] and vig[CATALOGO] == base[CATALOGO])
        diario_a = abierto["diario"]
        _c, leidos, _e = v.cli(env["b"], "--raiz-atlas", str(raiz["b"]), "--diarios")
        de_a = [d for d in (leidos or {}).get("diarios", []) if d["ruta"] == diario_a]
        v.registrar("el diario de A no custodia el contenido escrito tras vencer",
                    len(de_a) == 1 and de_a[0]["diario"]["pendientes"] == [DATASET] and DATASET not in de_a[0]["diario"]["contenido"],
                    de_a[0]["diario"] if de_a else leidos)

        # 5. "Drive" trae a B el dataset de A a mitad del turno de B.
        dataset_a = (raiz["a"] / DATASET).read_bytes()
        (raiz["b"] / DATASET).write_bytes(dataset_a)
        seguir(b)
        resultado_b = leer(b, "RESULTADO")
        b.wait(timeout=120)
        if resultado_b is None:
            return 1
        v.registrar("B no escribe sobre el dataset traído de A (ContenidoAjeno)",
                    resultado_b["rechazo_segunda_ingesta"] == "ContenidoAjeno", resultado_b)
        vig = worker.vigentes()
        v.registrar("B confirma lo que él escribió, no lo que había en disco",
                    vig[DATASET] == resultado_b["contenido"][DATASET] and resultado_b["ajenos_descartados"] == [DATASET],
                    {"cloud": vig[DATASET], "b": resultado_b["contenido"][DATASET]})
        v.registrar("el catálogo de B quedó confirmado", vig[CATALOGO] != base[CATALOGO])

        # 6. Siguiente turno de B: la copia de A trae un documento que Cloud no
        #    tiene; la protección previa del dataset (incidente 26/11) no lo
        #    descarta sola: B no escribe hasta una revisión humana.
        worker.avanzar(60)
        version = worker.version()
        turno, linea = v.equipo(env["b"], "turno", str(raiz["b"]))
        v.registrar("siguiente turno de B se detiene sin escribir (ESTADO_NO_VERIFICADO)",
                    turno is None and "ESTADO_NO_VERIFICADO" in linea and worker.version() == version, linea)
        # Resolución humana: se aparta la copia de A y se repone lo confirmado.
        apartado = v.MUNDO / "revision-humana" / "analisis_completo_guias.csv"
        apartado.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(raiz["b"] / DATASET), apartado)
        (raiz["b"] / DATASET).write_bytes(descargar(worker, resultado_b["contenido"][DATASET]))
        worker.avanzar(60)
        turno, linea = v.equipo(env["b"], "turno", str(raiz["b"]))
        v.registrar("tras apartar la copia de A, B vuelve a trabajar", turno is not None, turno or linea)
        guias_b = v.guias(raiz["b"] / DATASET)
        v.registrar("dataset de B: su guía sí, la de A no, la rechazada no",
                    "900011" in guias_b and "900010" not in guias_b and "900012" not in guias_b, guias_b)
        worker.avanzar(60)
        codigo, bloqueo, err = v.cli(env["b"], "--raiz-atlas", str(raiz["b"]), "--recuperar-turno", diario_a, "--aplicar")
        v.registrar("el turno de A no puede recuperarse encima de B (código 3)",
                    codigo == 3 and bloqueo and bloqueo["estado"] == "BLOQUEADO", bloqueo or err[-1500:])
        v.registrar("Cloud sigue con los datos de B", worker.vigentes()[DATASET] == resultado_b["contenido"][DATASET])
    finally:
        worker.cerrar()
        (v.SALIDA / "validacion_lease.json").write_text(json.dumps(v.CHECKS, ensure_ascii=False, indent=2), encoding="utf-8")
    fallas = [c for c in v.CHECKS if not c["ok"]]
    print(f"{len(v.CHECKS) - len(fallas)}/{len(v.CHECKS)} checks aprobados", flush=True)
    return 1 if fallas else 0


if __name__ == "__main__":
    raise SystemExit(main())
