"""Validación aislada P0.3.1: dos escritores, cada uno con raíz de trabajo
local (fuera de Drive) y su copia de la raíz publicada (Drive), que el
orquestador sincroniza a mitad de la operación interrumpida. SOLO PRUEBA.
Worker b28d594 real sobre D1/R2 en memoria, reloj desplazable.

  python scripts/validacion_diario_remoto/validar_aislada.py <cloud_dir> <salida_dir>

1. Drive de A tiene la operación vigente; A y B preparan su raíz de trabajo
   (CLI --preparar-raiz-trabajo) y A siembra la custodia.
2. A, sin heartbeat, escribe media fila y un reporte; Drive sincroniza.
3. El lease de A vence; B lo toma, ingesta, Drive sincroniza otra vez y B
   ingesta de nuevo: sin contaminación ni bloqueo. B confirma y publica.
4. A termina rechazado. Ninguna copia de Drive tiene nada de A.
5. B sigue trabajando; A vuelve, su turno superado queda aislado y trabaja.
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import validar as v  # noqa: E402
from validar_lease import leer, popen, seguir  # noqa: E402

DATASET = v.DATASET
CATALOGO = "catalogos_privados/vehiculos.json"


def drive(origen: Path, destino: Path) -> None:
    shutil.copytree(origen, destino, dirs_exist_ok=True)


def main() -> int:
    if v.MUNDO.exists():
        shutil.rmtree(v.MUNDO)
    v.MUNDO.mkdir(parents=True)
    worker = v.Worker()
    try:
        assert worker.url.startswith("https://127.0.0.1:")
        dirs = {n: v.MUNDO / f"equipo-{n}" for n in "ab"}
        trabajo = {n: d / "Trabajo" / "Atlas" for n, d in dirs.items()}
        publicada = {n: d / "Drive" / "Atlas" for n, d in dirs.items()}
        env = {n: v.entorno(worker, d / "local") for n, d in dirs.items()}

        # 1. Drive con la operación vigente; raíces de trabajo; siembra.
        v.raiz_inicial(publicada["a"])
        drive(publicada["a"], publicada["b"])
        for n in "ab":
            codigo, r, err = v.cli(env[n], "--raiz-atlas", str(trabajo[n]), "--preparar-raiz-trabajo", str(publicada[n]))
            v.registrar(f"{n.upper()} prepara su raíz de trabajo fuera de Drive", codigo == 0 and r and r["copiada"], r or err[-800:])
        codigo, sembrado, err = v.cli(env["a"], "--raiz-atlas", str(trabajo["a"]), "--sembrar")
        v.registrar("A siembra la custodia", codigo == 0 and sembrado and sembrado.get("sembrado"), sembrado or err[-800:])
        codigo, r, err = v.cli(env["a"], "--raiz-atlas", str(publicada["a"]), "--sembrar")
        v.registrar("escribir sobre la raíz publicada se rechaza", codigo == 1 and r and r.get("motivo") == "ESTADO_NO_VERIFICADO",
                    r or err[-800:])
        base = worker.vigentes()
        dataset_base = (publicada["a"] / DATASET).read_bytes()

        # 2. A interrumpido a mitad; Drive sincroniza.
        a = popen(env["a"], "escritura_larga", str(trabajo["a"]), "900010")
        abierto = leer(a, "ABIERTO")
        if abierto is None:
            return 1
        drive(publicada["a"], publicada["b"])
        v.registrar("la escritura parcial y el reporte de A quedan sólo en su raíz de trabajo",
                    "900010" in (trabajo["a"] / DATASET).read_text(encoding="utf-8-sig")
                    and (trabajo["a"] / "reportes" / "turno-900010").is_dir()
                    and all((publicada[n] / DATASET).read_bytes() == dataset_base for n in "ab")
                    and not any((publicada[n] / "reportes" / "turno-900010").exists() for n in "ab"))

        # 3. B toma el lease, ingesta, Drive sincroniza, B ingesta otra vez.
        worker.avanzar(11 * 60)
        b = popen(env["b"], "turno_pausado", str(trabajo["b"]), "900011", "900012")
        pausa = leer(b, "PAUSA")
        if pausa is None:
            return 1
        v.registrar("B obtiene el lease sin bloqueo", True, pausa["escritor_id"])
        drive(publicada["a"], publicada["b"])
        seguir(b)
        resultado_b = leer(b, "RESULTADO")
        b.wait(timeout=120)
        if resultado_b is None:
            return 1
        v.registrar("B ingesta de nuevo sin contaminación ni bloqueo", resultado_b["rechazo_segunda_ingesta"] is None
                    and resultado_b["ajenos_descartados"] == [], resultado_b)

        # 4. A termina rechazado.
        seguir(a)
        resultado_a = leer(a, "RESULTADO")
        a.wait(timeout=120)
        v.registrar("A termina creyéndose vigente y es rechazado", resultado_a is not None
                    and resultado_a["vigente_local_antes"] is True and resultado_a["punto_de_control"] is False
                    and resultado_a["rechazo_escritura"] in {"EscritorSustituido", "DiarioNoPersistido"}, resultado_a)
        drive(publicada["b"], publicada["a"])
        vig = worker.vigentes()
        for n in "ab":
            guias = v.guias(publicada[n] / DATASET)
            v.registrar(f"Drive de {n.upper()}: las dos guías de B, nada de A",
                        "900011" in guias and "900012" in guias and "900010" not in guias
                        and v.sha_archivo(publicada[n] / DATASET) == vig[DATASET]
                        and not (publicada[n] / "reportes" / "turno-900010").exists(), guias)
        v.registrar("Cloud tiene lo de B y el catálogo de A no", vig[CATALOGO] != base[CATALOGO]
                    and v.sha_archivo(publicada["a"] / CATALOGO) == vig[CATALOGO])

        # 5. B sigue; A vuelve y queda alineado a Cloud.
        worker.avanzar(60)
        turno_b, linea = v.equipo(env["b"], "turno_dataset", str(trabajo["b"]), "900013")
        v.registrar("B sigue trabajando y publicando", turno_b is not None
                    and "900013" in v.guias(publicada["b"] / DATASET), turno_b or linea)
        drive(publicada["b"], publicada["a"])
        worker.avanzar(11 * 60)
        turno_a, linea = v.equipo(env["a"], "turno", str(trabajo["a"]))
        v.registrar("A vuelve: su turno superado queda en cuarentena y trabaja", turno_a is not None
                    and DATASET in turno_a["resumen"]["cuarentena"], turno_a or linea)
        guias_a = v.guias(trabajo["a"] / DATASET)
        v.registrar("la raíz de trabajo de A quedó igual a Cloud", "900010" not in guias_a
                    and v.sha_archivo(trabajo["a"] / DATASET) == worker.vigentes()[DATASET], guias_a)
    finally:
        worker.cerrar()
        (v.SALIDA / "validacion_aislada.json").write_text(json.dumps(v.CHECKS, ensure_ascii=False, indent=2), encoding="utf-8")
    fallas = [c for c in v.CHECKS if not c["ok"]]
    print(f"{len(v.CHECKS) - len(fallas)}/{len(v.CHECKS)} checks aprobados", flush=True)
    return 1 if fallas else 0


if __name__ == "__main__":
    raise SystemExit(main())
