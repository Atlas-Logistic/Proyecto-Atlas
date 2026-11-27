"""Mundo MBT SINTÉTICO para la validación integral P0.6 (sin datos reales).

Catálogos de la MBT ficticia de la validación multiempresa (marcador
MBTMARCA), un dataset con guías sintéticas, estado de operación y reporte de
viajes generados por el Motor real. También genera imágenes de guía
sintéticas legibles por OCR.

  python mundo_mbt.py <raiz_destino> [cantidad_guias]
"""
from __future__ import annotations

import csv
import io
import json
import shutil
import subprocess
import sys
from pathlib import Path

MOTOR = Path(__file__).resolve().parents[2]
CATALOGOS_ORIGEN = Path(r"C:\Atlas\pruebas\multiempresa-validacion-20261125\mundo\drive\Atlas\catalogos_privados")
M = "MBTMARCA"


def fila(guia: str, peso: str = "28000") -> dict:
    from atlas_core.procesamiento_masivo import COLUMNAS
    f = {c: "" for c in COLUMNAS}
    f.update({"archivo": f"{guia}.jpeg", "estado_procesamiento": "OK", "numero_guia": guia,
              "numero_transporte": "0000" + guia, "cliente": f"CONSTRUCTORA {M} SA", "rut_cliente": "76.111.111-6",
              "chofer": f"LUIS {M} REYES", "rut_chofer": "12.345.678-5", "patente_tracto": "KN5439",
              "obra_destino": f"OBRA {M}", "despachar_a_crudo": f"CALLE {M} 200 SANTIAGO", "estado_ruta": "RUTA_CALCULADA",
              "peso_kg": peso, "descripcion_material": f"ARIDO {M}", "fecha": "26-11-2026", "distancia_km": "31.2",
              "duracion_min": "44"})
    return f


def construir(raiz: Path, guias: list[str]) -> None:
    from atlas_core.procesamiento_masivo import COLUMNAS
    from atlas_core.almacenamiento_portable import escribir_json_atomico
    raiz.mkdir(parents=True)
    shutil.copytree(CATALOGOS_ORIGEN, raiz / "catalogos_privados")
    actual = raiz / "operacion" / "actual"
    actual.mkdir(parents=True)
    (raiz / "operacion" / "mobile" / "envios").mkdir(parents=True)
    with (actual / "analisis_completo_guias.csv").open("w", newline="", encoding="utf-8-sig") as h:
        w = csv.DictWriter(h, fieldnames=COLUMNAS, delimiter=";")
        w.writeheader()
        w.writerows(fila(g, str(27000 + i * 100)) for i, g in enumerate(guias))
    escribir_json_atomico(actual / "decisiones_aplicadas.json", {"schema_version": 1, "aplicaciones": []})
    salida = raiz / "reportes" / "vigente-inicial"
    r = subprocess.run([sys.executable, "-B", str(MOTOR / "generar_reporte_viajes.py"), str(actual / "analisis_completo_guias.csv"),
                        str(salida), "--catalogos", str(raiz / "catalogos_privados")], cwd=MOTOR, capture_output=True, text=True,
                       encoding="utf-8", env={**__import__("os").environ, "ATLAS_DATA_DIR": str(raiz), "PYTHONIOENCODING": "utf-8"})
    if r.returncode != 0 or not (salida / "viajes.csv").is_file():
        raise RuntimeError("reporte inicial no generado: " + (r.stderr or r.stdout)[-1500:])
    estado = actual / "estado_operacion.json"  # lo deja generar_reporte_viajes.py
    if not estado.is_file():
        escribir_json_atomico(estado, {"schema_version": 1, "reporte_vigente": "reportes/vigente-inicial",
                                       "dataset_operacional": "operacion/actual/analisis_completo_guias.csv",
                                       "decisiones_pendientes": "operacion/actual/decisiones_pendientes.json"})
    else:
        datos = json.loads(estado.read_text(encoding="utf-8"))
        datos["reporte_vigente"] = "reportes/vigente-inicial"
        escribir_json_atomico(estado, datos)


def imagen_guia(guia: str, *, peso: str = "26500") -> bytes:
    """Guía de despacho SINTÉTICA, texto grande y nítido (OCR real)."""
    from PIL import Image, ImageDraw, ImageFont
    try:
        fuente = ImageFont.truetype(r"C:\Windows\Fonts\arial.ttf", 34)
        chica = ImageFont.truetype(r"C:\Windows\Fonts\arial.ttf", 28)
    except OSError:
        fuente = chica = ImageFont.load_default()
    img = Image.new("RGB", (1240, 1754), "white")
    d = ImageDraw.Draw(img)
    lineas = [
        (fuente, "ACEROS AZA S.A.   R.U.T. 92.176.000-0"),
        (fuente, f"GUIA DE DESPACHO ELECTRONICA N° {guia}"),
        (chica, "FECHA EMISION: 26-11-2026"),
        (chica, f"SEÑOR(ES): CONSTRUCTORA {M} SA"),
        (chica, "R.U.T.: 76.111.111-6"),
        (chica, f"OBRA: OBRA {M}"),
        (chica, f"DESPACHAR A: CALLE {M} 200 SANTIAGO"),
        (chica, f"TRANSPORTE: 0000{guia}"),
        (chica, f"CHOFER: LUIS {M} REYES   RUT 12.345.678-5"),
        (chica, "PATENTE CAMION: KN5439"),
        (chica, f"MATERIAL: ARIDO {M}"),
        (chica, f"PESO NETO KG: {peso}"),
    ]
    y = 80
    for f, texto in lineas:
        d.text((80, y), texto, fill="black", font=f)
        y += 90
    salida = io.BytesIO()
    img.save(salida, format="JPEG", quality=92)
    return salida.getvalue()


if __name__ == "__main__":
    sys.path.insert(0, str(MOTOR))
    destino = Path(sys.argv[1])
    cantidad = int(sys.argv[2]) if len(sys.argv) > 2 else 2
    construir(destino, [str(900001 + i) for i in range(cantidad)])
    print(json.dumps({"raiz": str(destino), "guias": cantidad}))
