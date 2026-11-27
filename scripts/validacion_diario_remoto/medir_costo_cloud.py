"""Medición de costo Cloud del P0 (P0.6) y proyección a la carga real de MBT.

SOLO PRUEBA: Worker b28d594 real sobre D1/R2 en memoria con métricas, PULL
real con OCR RapidOCR, guía Mobile sintética. Mide por guía: solicitudes,
versiones confirmadas, contenidos custodiados por ruta (desde los propios
diarios) y el ciclo ocioso; proyecta con los parámetros de MBT.

  python medir_costo_cloud.py <cloud_dir> <salida_dir> [guias_dia] [dataset_mb] [foto_mb] [fraccion_mobile]

Parámetros por defecto = MBT real, 27/11/2026 (sólo lectura): 12 guías/día
promedio 30 días (máx 21), dataset 5,7 MB, foto Mobile 2,6 MB, 43 % Mobile.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import validar as v  # noqa: E402
import validar_pull as vp  # noqa: E402
import validar_lease  # noqa: E402
import mundo_mbt  # noqa: E402

GUIAS_DIA = float(sys.argv[3]) if len(sys.argv) > 3 else 12.0
DATASET_MB = float(sys.argv[4]) if len(sys.argv) > 4 else 5.7
FOTO_MB = float(sys.argv[5]) if len(sys.argv) > 5 else 2.6
FRACCION_MOBILE = float(sys.argv[6]) if len(sys.argv) > 6 else 0.43
CICLOS_DIA = 24 * 60 / 2  # PULL cada 2 minutos
RAPIDOCR = Path(os.environ.get("LOCALAPPDATA", "")) / "Atlas" / "runtime" / "rapidocr" / "Scripts" / "python.exe"


def main() -> int:
    if v.MUNDO.exists():
        shutil.rmtree(v.MUNDO)
    v.MUNDO.mkdir(parents=True)
    w = v.Worker(usuarios=[vp.CHOFER])
    resultado: dict = {"parametros_mbt": {"guias_dia": GUIAS_DIA, "dataset_mb": DATASET_MB, "foto_mb": FOTO_MB,
                                          "fraccion_mobile": FRACCION_MOBILE, "ciclos_pull_dia": CICLOS_DIA}}
    try:
        raiz = v.MUNDO / "Atlas"
        mundo_mbt.construir(raiz, ["900001", "900002"])
        env = v.entorno(w, v.MUNDO / "local")
        env.update(ATLAS_OCR_PROVIDER="rapidocr", ATLAS_RAPIDOCR_PYTHON=str(RAPIDOCR))
        v.cli(env, "--raiz-atlas", str(raiz), "--sembrar")
        vp.jpeg = lambda _m: mundo_mbt.imagen_guia("900101")
        vp.enviar_mobile(w, "envio-900101")

        def metricas():
            with urllib.request.urlopen(f"{w.url}/__prueba/metricas", timeout=30, context=w.ssl) as r:
                return json.loads(r.read())

        def ciclo():
            a, filas = metricas(), {(f["ruta"], f["version"]) for f in w.tabla("estado_operativo_archivos")}
            rc = subprocess.run([sys.executable, str(v.MOTOR / "sincronizar_mobile_cloud.py"), "--raiz-atlas", str(raiz)],
                                cwd=v.MOTOR, env=env, capture_output=True, text=True, encoding="utf-8", timeout=1500).returncode
            d = metricas()
            nuevas = [f for f in w.tabla("estado_operativo_archivos") if (f["ruta"], f["version"]) not in filas]
            diario = sum(1 for f in nuevas if f["ruta"].startswith(".atlas_custodia/"))
            return {"rc": rc, "solicitudes": sum(d["solicitudes"].values()) - sum(a["solicitudes"].values()),
                    "filas_d1": len(nuevas), "versiones_diario": diario, "versiones_datos": len(nuevas) - diario,
                    "rutas_confirmadas": sorted({f["ruta"] for f in nuevas if not f["ruta"].startswith(".atlas_custodia/")})}

        resultado["ciclo_ingesta"] = ciclo()
        w.avanzar(120)
        resultado["ciclo_posterior"] = ciclo()
        w.avanzar(120)
        resultado["ciclo_ocioso"] = ciclo()
        distintos: dict[str, set] = {}
        for f in w.tabla("estado_operativo_archivos"):
            if f["ruta"].startswith(".atlas_custodia/diarios/") and f["sha256"]:
                for ruta, huella in (json.loads(validar_lease.descargar(w, f["sha256"])).get("contenido") or {}).items():
                    if huella:
                        distintos.setdefault(ruta, set()).add(huella)
        resultado["contenidos_custodiados_por_ruta"] = {r: len(s) for r, s in sorted(distintos.items())}
    finally:
        w.cerrar()
    ing, post, ocio = resultado["ciclo_ingesta"], resultado["ciclo_posterior"], resultado["ciclo_ocioso"]
    por_guia_sol = ing["solicitudes"] + post["solicitudes"]
    por_guia_d1 = ing["filas_d1"] + post["filas_d1"]
    datasets = resultado["contenidos_custodiados_por_ruta"].get(v.DATASET, 0)
    mb_guia = datasets * DATASET_MB + FOTO_MB * FRACCION_MOBILE
    ciclos_ocupados = 2 * GUIAS_DIA
    resultado["proyeccion_mbt_dia"] = {
        "solicitudes_worker": round(GUIAS_DIA * por_guia_sol + (CICLOS_DIA - ciclos_ocupados) * ocio["solicitudes"]),
        "filas_d1_estado": round(GUIAS_DIA * por_guia_d1),
        "versiones_marca": round(GUIAS_DIA * (ing["filas_d1"] + post["filas_d1"])),
        "r2_mb_custodia": round(GUIAS_DIA * mb_guia, 1),
        "subida_mb_desde_el_equipo": round(GUIAS_DIA * mb_guia, 1),
        "nota": "contenidos del dataset por guía x tamaño real del dataset + foto Mobile custodiada; sin compactación ni GC",
    }
    resultado["proyeccion_mbt_anio"] = {"filas_d1_estado": resultado["proyeccion_mbt_dia"]["filas_d1_estado"] * 365,
                                        "r2_gb_custodia": round(resultado["proyeccion_mbt_dia"]["r2_mb_custodia"] * 365 / 1024, 1)}
    (v.SALIDA / "costo_cloud.json").write_text(json.dumps(resultado, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(resultado, ensure_ascii=False, indent=2))
    return 0 if ing["rc"] == 0 and post["rc"] == 0 and ocio["rc"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
