"""Lector mínimo de .xlsx (sólo biblioteca estándar, sólo lectura).

Uso: python -I leer_xlsx.py <archivo.xlsx> [--json salida.json]
Imprime cada hoja con sus filas; no modifica el archivo de origen.
"""
import json
import re
import sys
import zipfile
import xml.etree.ElementTree as ET

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
      "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}


def _col(ref):
    letras = re.match(r"[A-Z]+", ref).group(0)
    n = 0
    for c in letras:
        n = n * 26 + ord(c) - 64
    return n - 1


def leer(ruta):
    with zipfile.ZipFile(ruta) as z:
        compartidas = []
        if "xl/sharedStrings.xml" in z.namelist():
            for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", NS):
                compartidas.append("".join(t.text or "" for t in si.iter(f"{{{NS['m']}}}t")))
        libro = ET.fromstring(z.read("xl/workbook.xml"))
        rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
        destino = {r.get("Id"): r.get("Target") for r in rels}
        hojas = {}
        for h in libro.find("m:sheets", NS):
            rid = h.get(f"{{{NS['r']}}}id")
            ruta_hoja = "xl/" + destino[rid].lstrip("/").removeprefix("xl/")
            filas = []
            for fila in ET.fromstring(z.read(ruta_hoja)).iter(f"{{{NS['m']}}}row"):
                valores = {}
                for c in fila.findall("m:c", NS):
                    v = c.find("m:v", NS)
                    tipo = c.get("t")
                    if tipo == "inlineStr":
                        texto = "".join(t.text or "" for t in c.iter(f"{{{NS['m']}}}t"))
                    elif v is None:
                        continue
                    elif tipo == "s":
                        texto = compartidas[int(v.text)]
                    else:
                        texto = v.text
                    valores[_col(c.get("r"))] = texto
                if valores:
                    filas.append([valores.get(i, "") for i in range(max(valores) + 1)])
            hojas[h.get("name")] = filas
        return hojas


if __name__ == "__main__":
    hojas = leer(sys.argv[1])
    if "--json" in sys.argv:
        with open(sys.argv[sys.argv.index("--json") + 1], "w", encoding="utf-8") as f:
            json.dump(hojas, f, ensure_ascii=False, indent=1)
    for nombre, filas in hojas.items():
        print(f"== {nombre}: {len(filas)} filas")
