"""Audita qué evidencia explícita respalda cada estado del bloque A.

Sólo lectura. No modifica `referencia_campos.csv`: escribe un archivo aparte
con el respaldo de cada (muestra, campo) para que el comparador pueda
filtrar por la solidez de la evidencia.

Hechos verificables en las planillas (ver README):
- La planilla v1 fue creada por un script (openpyxl) y guardada después por
  una persona en Excel. La versión prellenada es salida del script.
- Los colores de celda (verde/amarillo) son idénticos en el prellenado: los
  puso el generador, no son marca humana.
- `VALIDADO`: 10 filas ya traían "SÍ" desde el prellenado (sin marca humana
  posterior); 20 pasaron de "REVISAR" a "SI" (marca explícita de fila).
- `muestra_fechas_revision_actualizada.xlsx` tiene `fecha_real_validada`
  completada por una persona sobre una plantilla vacía: único respaldo
  explícito por campo.

Uso:
  python -I auditar_respaldo_a.py --raiz-atlas "G:\\Mi unidad\\Atlas" \
      --referencia <dir_privado>\\referencia --salida <archivo.csv>
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from construir_referencia import CAMPOS, fecha_serial  # noqa: E402
from leer_xlsx import leer  # noqa: E402

COLUMNAS = [
    "id_muestra", "campo", "estado_referencia", "respaldo", "respaldo_explicito_por_campo",
    "marca_fila", "valor_cambio_vs_prellenado", "sin_respaldo_explicito", "detalle",
]


def _filas(ruta: Path) -> dict:
    hoja = next(v for k, v in leer(ruta).items() if k.startswith("Datos"))
    cab = hoja[2]
    return {f[1]: dict(zip(cab, f + [""] * (len(cab) - len(f)))) for f in hoja[3:]}


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--raiz-atlas", required=True, type=Path)
    p.add_argument("--referencia", required=True, type=Path)
    p.add_argument("--salida", required=True, type=Path)
    a = p.parse_args()

    dp = a.raiz_atlas / "datos_privados"
    v1 = _filas(dp / "ground_truth" / "validacion_atlas_30_guias_v1.xlsx")
    pre = _filas(dp / "validaciones_historicas" / "validacion_completa_30_guias_prellenada.xlsx")
    hf = next(iter(leer(dp / "validaciones_historicas" / "muestra_fechas_revision_actualizada.xlsx").values()))
    fechas = {}
    for f in hf[3:]:
        fila = dict(zip(hf[2], f + [""] * (len(hf[2]) - len(f))))
        fechas[fila["nombre_archivo"]] = fecha_serial(str(fila["fecha_real_validada"]).strip())

    with open(a.referencia / "manifiesto.csv", encoding="utf-8-sig") as f:
        archivo_por_id = {m["id_muestra"]: m["nombre_origen"] for m in csv.DictReader(f) if m["id_muestra"][0] == "A"}
    with open(a.referencia / "referencia_campos.csv", encoding="utf-8-sig") as f:
        referencia = [r for r in csv.DictReader(f) if r["id_muestra"][0] == "A"]
    columna = dict(CAMPOS)

    salida = []
    for r in referencia:
        nombre = archivo_por_id[r["id_muestra"]]
        fila, previa = v1[nombre], pre[nombre]
        col = columna[r["campo"]]
        marca_previa = previa["VALIDADO"].strip().upper()
        marca = fila["VALIDADO"].strip().upper()
        if marca_previa == "REVISAR" and marca in ("SI", "SÍ"):
            marca_fila = "SI_PUESTO_TRAS_PRELLENADO"
        elif marca in ("SI", "SÍ") and marca_previa == marca:
            marca_fila = "SI_DESDE_PRELLENADO"
        else:
            marca_fila = f"{marca_previa or 'VACIO'}->{marca or 'VACIO'}"
        cambio = ""
        if col:
            cambio = "SI" if str(fila.get(col, "")).strip() != str(previa.get(col, "")).strip() else "NO"

        explicito_campo = False
        if r["campo"] == "fecha_emision" and fechas.get(nombre):
            explicito_campo = True
            if fechas[nombre] == r["valor_referencia"]:
                respaldo = "EXPLICITO_CAMPO_REVISION_FECHAS"
                detalle = "fecha_real_validada (revisión humana de fechas) coincide"
            else:
                respaldo = "CONFLICTO_ENTRE_FUENTES_HUMANAS"
                detalle = "fecha_real_validada (revisión humana de fechas) difiere"
        elif col is None:
            respaldo, detalle = "SIN_FUENTE", "campo no registrado en la planilla"
        elif marca_fila == "SI_PUESTO_TRAS_PRELLENADO":
            respaldo = "EXPLICITO_FILA"
            detalle = ("fila marcada SI tras el prellenado en archivo guardado por persona; "
                       + ("valor distinto del prellenado (autoría del cambio por campo no acreditada)"
                          if cambio == "SI" else "valor igual al prellenado (sin evidencia individual del campo)"))
        elif marca_fila == "SI_DESDE_PRELLENADO":
            respaldo = "NINGUNO"
            detalle = ("VALIDADO=SÍ y color verde ya venían del generador; "
                       + ("valor distinto del prellenado sin marca humana de fila"
                          if cambio == "SI" else "sin evidencia de revisión humana posterior"))
        else:
            respaldo, detalle = "NINGUNO", f"marca de fila {marca_fila}"

        salida.append({
            "id_muestra": r["id_muestra"], "campo": r["campo"], "estado_referencia": r["estado"],
            "respaldo": respaldo, "respaldo_explicito_por_campo": "SI" if explicito_campo else "NO",
            "marca_fila": marca_fila, "valor_cambio_vs_prellenado": cambio,
            "sin_respaldo_explicito": "SI" if respaldo in ("NINGUNO", "SIN_FUENTE") else "NO",
            "detalle": detalle,
        })

    with open(a.salida, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNAS)
        w.writeheader()
        w.writerows(salida)


if __name__ == "__main__":
    main()
