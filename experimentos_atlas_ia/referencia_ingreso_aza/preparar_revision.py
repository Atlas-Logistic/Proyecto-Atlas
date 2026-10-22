"""Prepara la revisión humana por lotes de las propuestas visuales del agente.

Sólo lee la referencia y las lecturas del agente; no modifica ninguna de las
dos. Escribe, en el directorio de propuestas:

- `propuestas_agente.csv`: una fila por lectura, con el agente como fuente,
  la ubicación (recorte y caja normalizada) y, en columnas aparte, el valor y
  estado vigentes de la referencia humana. Nunca se mezclan.
- `lotes/lote_NN.html`: página estática local con cada recorte junto a su
  propuesta (sin scripts ni recursos externos).
- `lotes/lote_NN_decisiones.csv`: plantilla para registrar ACEPTAR, CORREGIR
  o DUDA por fila; la persona la completa en Excel.

Uso:
  python -I preparar_revision.py --referencia <dir_privado>\\referencia \
      --propuestas <dir_privado>\\propuestas_visuales_AAAAMMDD [--max-filas 50]
"""

from __future__ import annotations

import argparse
import csv
import html
import json
from pathlib import Path

COLUMNAS = [
    "id_muestra", "campo", "archivo_copia", "estado_propuesta", "valor_propuesto", "motivo_duda",
    "recorte", "caja_normalizada", "fuente", "leido_en", "estado_referencia_humana",
    "valor_referencia_humana", "coincide_con_referencia",
]
COLUMNAS_DECISION = [
    "id_muestra", "campo", "valor_propuesto", "estado_propuesta", "decision", "valor_corregido",
    "estado_corregido", "revisor", "fecha_revision", "comentario",
]
ORDEN_CAMPOS = [
    "fecha_emision", "numero_guia", "numero_transporte", "cliente", "rut_cliente", "obra_destino",
    "cod_destinatario", "direccion_destino", "comuna", "despachar_a", "chofer", "rut_chofer",
    "patente_tracto", "patente_rampla", "descripcion_material", "peso_kg", "hora_entrada", "hora_salida",
]


def _leer_csv(ruta: Path) -> list[dict]:
    with open(ruta, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def _escribir_csv(ruta: Path, filas: list[dict], columnas: list[str]) -> None:
    with open(ruta, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columnas)
        w.writeheader()
        w.writerows(filas)


def _cajas(ruta: Path) -> dict:
    cajas = {}
    if ruta.exists():
        for linea in ruta.read_text(encoding="utf-8").splitlines():
            partes = linea.split()
            if len(partes) >= 2:
                cajas[partes[0]] = " ".join(partes[1:])
    return cajas


def _comparable(valor: str) -> str:
    return "".join(valor.upper().split()).replace(".", "").replace(",00", "")


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--referencia", required=True, type=Path)
    p.add_argument("--propuestas", required=True, type=Path)
    p.add_argument("--max-filas", type=int, default=50)
    a = p.parse_args()

    archivo = {m["id_muestra"]: m["archivo_copia"] for m in _leer_csv(a.referencia / "manifiesto.csv")}
    ref = {(r["id_muestra"], r["campo"]): r for r in _leer_csv(a.referencia / "referencia_campos.csv")}
    cajas = _cajas(a.propuestas / "recortes" / "cajas.txt")
    with open(a.propuestas / "lecturas_agente.jsonl", encoding="utf-8") as f:
        lecturas = [json.loads(linea) for linea in f]

    filas = []
    for le in lecturas:
        r = ref[(le["id_muestra"], le["campo"])]
        zona = le["zona"]
        recorte = "" if zona.startswith("pdf_render") else f"{le['id_muestra']}_{zona}.png"
        if recorte and not (a.propuestas / "recortes" / recorte).exists():
            raise SystemExit(f"Falta el recorte {recorte}")
        humano = r["valor_referencia"] if r["estado"] != "PENDIENTE_CONFIRMACION" else ""
        filas.append({
            "id_muestra": le["id_muestra"], "campo": le["campo"], "archivo_copia": archivo[le["id_muestra"]],
            "estado_propuesta": le["estado_propuesta"], "valor_propuesto": le["valor_propuesto"],
            "motivo_duda": le["motivo_duda"], "recorte": recorte or zona,
            "caja_normalizada": cajas.get(recorte[:-4], "") if recorte else "render del PDF completo",
            "fuente": le["fuente"], "leido_en": le["leido_en"], "estado_referencia_humana": r["estado"],
            "valor_referencia_humana": r["valor_referencia"],
            "coincide_con_referencia": ("" if not humano or le["estado_propuesta"] != "PROPUESTA" else
                                        "SI" if _comparable(humano) == _comparable(le["valor_propuesto"]) else "NO"),
        })
    filas.sort(key=lambda f: (f["id_muestra"], ORDEN_CAMPOS.index(f["campo"])))
    _escribir_csv(a.propuestas / "propuestas_agente.csv", filas, COLUMNAS)

    # Lotes pequeños sin partir guías: primero A (pendientes), luego B y C.
    lotes, actual = [], []
    for idm in dict.fromkeys(f["id_muestra"] for f in filas):
        grupo = [f for f in filas if f["id_muestra"] == idm]
        if actual and (len(actual) + len(grupo) > a.max_filas or actual[0]["id_muestra"][0] != idm[0]):
            lotes.append(actual)
            actual = []
        actual += grupo
    if actual:
        lotes.append(actual)

    dir_lotes = a.propuestas / "lotes"
    dir_lotes.mkdir(exist_ok=True)
    for n, lote in enumerate(lotes, 1):
        nombre = f"lote_{n:02d}"
        _escribir_csv(dir_lotes / f"{nombre}_decisiones.csv",
                      [{c: f.get(c, "") for c in COLUMNAS_DECISION} for f in lote], COLUMNAS_DECISION)
        cuerpo = []
        for f in lote:
            img = (f'<img src="../recortes/{html.escape(f["recorte"])}" alt="">' if f["recorte"].endswith(".png")
                   else f'<a href="../../referencia/imagenes/{html.escape(f["archivo_copia"])}">abrir PDF</a>')
            humano = (f'<div class="h">Referencia humana ({html.escape(f["estado_referencia_humana"])}): '
                      f'{html.escape(f["valor_referencia_humana"]) or "—"}</div>')
            cuerpo.append(
                f'<tr class="{f["estado_propuesta"].lower()}"><td>{f["id_muestra"]}</td><td>{f["campo"]}</td>'
                f'<td><b>{html.escape(f["valor_propuesto"]) or "—"}</b><div>{f["estado_propuesta"]}</div>'
                f'<div class="d">{html.escape(f["motivo_duda"])}</div>{humano}</td><td>{img}'
                f'<div class="d"><a href="../../referencia/imagenes/{html.escape(f["archivo_copia"])}">'
                f'imagen completa</a></div></td></tr>')
        (dir_lotes / f"{nombre}.html").write_text(
            "<!doctype html><meta charset=utf-8><title>Revisión " + nombre + "</title><style>"
            "body{font:14px system-ui;margin:16px;background:#fff;color:#111}"
            "table{border-collapse:collapse;width:100%}td{border:1px solid #ccc;padding:6px;vertical-align:top}"
            "img{max-width:900px;width:100%}.d{color:#555;font-size:12px}.h{color:#035;font-size:12px}"
            "tr.ambiguo td,tr.ilegible td{background:#fff4d6}tr.ausente_en_documento td{background:#eef}"
            "</style><h1>Revisión " + nombre + " — propuestas del agente (no confirmadas)</h1>"
            f"<p>{len(lote)} filas. Registrar la decisión en <code>{nombre}_decisiones.csv</code>: "
            "ACEPTAR, CORREGIR (con valor_corregido) o DUDA.</p>"
            "<table><tr><th>Muestra</th><th>Campo</th><th>Propuesta</th><th>Evidencia</th></tr>"
            + "".join(cuerpo) + "</table>", encoding="utf-8")
    print(json.dumps({"filas": len(filas), "lotes": [len(l) for l in lotes]}))


if __name__ == "__main__":
    main()
