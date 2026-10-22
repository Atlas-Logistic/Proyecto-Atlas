"""Construye la referencia para evaluar la calidad de ingreso de guías AZA.

Sólo lectura de las fuentes: copia las imágenes seleccionadas a un
directorio privado, calcula SHA-256 y escribe un manifiesto y valores de
referencia por campo con estados explícitos. No ejecuta OCR, no escribe en
las fuentes y NUNCA usa resultados de Atlas (`datos_ocr`, dataset, reportes)
como valor de referencia ni como criterio de selección.

Uso:
  python -I construir_referencia.py --raiz-atlas "G:\\Mi unidad\\Atlas" \
      --motor C:\\Atlas\\Proyecto-Atlas --salida <dir_privado>

Estados por campo:
  CONFIRMADO_HUMANO       valor transcrito y validado por una persona, sin dudas registradas
  AUSENTE                 la persona registró que el campo no aparece en el documento
  ILEGIBLE                la persona marcó el documento ilegible y el campo quedó vacío
  NO_APLICA               el campo no corresponde a este documento (sólo si una persona lo declara)
  PENDIENTE_CONFIRMACION  sin referencia humana, con dudas registradas o con evidencia en conflicto
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from leer_xlsx import leer  # noqa: E402

ESTADOS = ("CONFIRMADO_HUMANO", "AUSENTE", "ILEGIBLE", "NO_APLICA", "PENDIENTE_CONFIRMACION")

# Campo de referencia -> columna de la planilla humana (hoja "Datos guías").
# `despachar_a` no existe en la planilla: según la regla E1 la ruta usa
# DESPACHAR A, distinto de OBRA/DIRECCIÓN registradas; queda pendiente.
CAMPOS = [
    ("fecha_emision", "FECHA EMISIÓN"),
    ("numero_guia", "N° GUÍA"),
    ("numero_transporte", "N° TRANSPORTE"),
    ("cliente", "CLIENTE"),
    ("rut_cliente", "RUT CLIENTE"),
    ("obra_destino", "OBRA / DESTINO"),
    ("cod_destinatario", "CÓDIGO DESTINATARIO"),
    ("direccion_destino", "DIRECCIÓN DESTINO"),
    ("comuna", "COMUNA"),
    ("despachar_a", None),
    ("chofer", "CHOFER"),
    ("rut_chofer", "RUT CHOFER"),
    ("patente_tracto", "PATENTE TRACTO"),
    ("patente_rampla", "PATENTE RAMPLA"),
    ("descripcion_material", "DESCRIPCIÓN MATERIAL"),
    ("peso_kg", "PESO KG"),
    ("hora_entrada", "HORA ENTRADA"),
    ("hora_salida", "HORA SALIDA"),
]
CAMPO_POR_COLUMNA = {col: campo for campo, col in CAMPOS if col}

# Discrepancias de la propia planilla documentadas en la bitácora técnica de
# Motor (bloque O1, 2026-08-11, "Auditoría real y hallazgo sobre la calidad
# del ground truth"). La alternativa la propuso una verificación visual de un
# agente, NO una persona: se anota, pero el campo queda pendiente. Se cargan
# desde un JSON privado (--discrepancias) porque contienen datos de guías.
DISCREPANCIAS_BITACORA: dict[tuple[str, str], str] = {}
NOTA_BITACORA = (
    "Bitácora técnica Motor, bloque O1 (2026-08-11): error de transcripción de la planilla "
    "detectado por verificación visual de un agente; alternativa no confirmada por una persona"
)

COLUMNAS_MANIFIESTO = [
    "id_muestra", "bloque", "canal", "archivo_copia", "sha256", "bytes", "formato", "ancho_px",
    "alto_px", "paginas_pdf", "ruta_origen", "nombre_origen", "fecha_origen", "criterio_seleccion",
    "pista_nombre_archivo", "tipo_documento_estado", "procedencia_original",
]
COLUMNAS_REFERENCIA = [
    "id_muestra", "campo", "valor_referencia", "estado", "valor_crudo_fuente", "fuente",
    "alternativa_no_confirmada", "nota",
]


# ---------------------------------------------------------------- utilidades

def sha256(ruta: Path) -> str:
    h = hashlib.sha256()
    with open(ruta, "rb") as f:
        for trozo in iter(lambda: f.read(1 << 20), b""):
            h.update(trozo)
    return h.hexdigest()


def dimensiones(ruta: Path) -> tuple[str, str, str]:
    """(ancho, alto, paginas) leyendo sólo cabeceras; vacío si no aplica."""
    datos = ruta.read_bytes()
    if datos[:8] == b"\x89PNG\r\n\x1a\n":
        ancho, alto = struct.unpack(">II", datos[16:24])
        return str(ancho), str(alto), ""
    if datos[:2] == b"\xff\xd8":
        i = 2
        while i < len(datos) - 9:
            if datos[i] != 0xFF:
                i += 1
                continue
            marca = datos[i + 1]
            if marca in (0xC0, 0xC1, 0xC2):
                alto, ancho = struct.unpack(">HH", datos[i + 5:i + 9])
                return str(ancho), str(alto), ""
            if marca in (0xD8, 0x01) or 0xD0 <= marca <= 0xD7:
                i += 2
                continue
            i += 2 + struct.unpack(">H", datos[i + 2:i + 4])[0]
        return "", "", ""
    if datos[:5] == b"%PDF-":
        return "", "", str(len(re.findall(rb"/Type\s*/Page(?!s)", datos)))
    return "", "", ""


def equidistantes(items: list, k: int) -> list:
    """Misma regla reproducible de la selección histórica: round(i*(N-1)/(k-1))."""
    if k <= 0 or not items:
        return []
    if k == 1 or len(items) == 1:
        return [items[len(items) // 2]]
    n = len(items)
    vistos, salida = set(), []
    for i in range(k):
        j = round(i * (n - 1) / (k - 1))
        if j not in vistos:
            vistos.add(j)
            salida.append(items[j])
    return salida


def fecha_serial(valor: str) -> str | None:
    if re.fullmatch(r"\d{5}", valor or ""):
        return (dt.date(1899, 12, 30) + dt.timedelta(days=int(valor))).isoformat()
    m = re.fullmatch(r"(\d{2})[-/](\d{2})[-/](\d{4})", valor or "")
    if m:
        return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    return None


def hora(valor: str) -> str | None:
    if re.fullmatch(r"\d{2}:\d{2}:\d{2}", valor or ""):
        return valor
    if re.fullmatch(r"0?\.\d+|0", valor or ""):
        segundos = round(float(valor) * 86400)
        return f"{segundos // 3600:02d}:{segundos % 3600 // 60:02d}:{segundos % 60:02d}"
    return None


def peso(valor: str) -> str | None:
    if re.fullmatch(r"\d{1,6}", valor or ""):
        return str(int(valor))
    m = re.fullmatch(r"(\d{1,3}(?:\.\d{3})*),(\d{2})", valor or "")
    if m and m.group(2) == "00":
        return str(int(m.group(1).replace(".", "")))
    return None


PATENTE_CHILENA = re.compile(r"[A-Z]{2}\d{4}|[A-Z]{4}\d{2}")


# ------------------------------------------------------- bloque A (humano)

def bloque_a(raiz: Path, motor: Path, salida: Path, manifiesto: list, referencia: list, conflictos: list):
    sys.path.insert(0, str(motor))
    from atlas_core.validadores import validar_rut_chileno  # sólo lectura, sin efectos
    from atlas_core.modelos import EstadoValidacion

    xlsx = raiz / "datos_privados" / "ground_truth" / "validacion_atlas_30_guias_v1.xlsx"
    xlsx_fechas = raiz / "datos_privados" / "validaciones_historicas" / "muestra_fechas_revision_actualizada.xlsx"
    fotos = raiz / "datos_privados" / "muestra_fechas_30"
    hojas = leer(xlsx)
    datos = next(v for k, v in hojas.items() if k.startswith("Datos"))
    pendientes = next(v for k, v in hojas.items() if k.startswith("Pendientes"))
    cab = datos[2]
    filas = [dict(zip(cab, f + [""] * (len(cab) - len(f)))) for f in datos[3:]]

    # La hoja "Pendientes de verificación" es la lista de dudas ANTERIOR a la
    # revisión humana: comparada con la versión prellenada, la persona cambió
    # la mayoría de esos campos y marcó la fila VALIDADO=SI. Un pendiente se
    # da por resuelto sólo si el valor final difiere del prellenado.
    xlsx_pre = raiz / "datos_privados" / "validaciones_historicas" / "validacion_completa_30_guias_prellenada.xlsx"
    datos_pre = next(v for k, v in leer(xlsx_pre).items() if k.startswith("Datos"))
    prellenado = {f[1]: dict(zip(datos_pre[2], f + [""] * (len(datos_pre[2]) - len(f)))) for f in datos_pre[3:]}
    dudas = {}
    for f in pendientes[3:]:
        if len(f) >= 4 and f[2] in CAMPO_POR_COLUMNA:
            dudas[(f[1], CAMPO_POR_COLUMNA[f[2]])] = (f[2], f[3])

    hf = next(iter(leer(xlsx_fechas).values()))
    cab_f = hf[2]
    fechas_revision = {}
    for f in hf[3:]:
        fila = dict(zip(cab_f, f + [""] * (len(cab_f) - len(f))))
        fechas_revision[fila["nombre_archivo"]] = fecha_serial(str(fila["fecha_real_validada"]).strip())

    choferes_por_rut = {}
    for fila in filas:
        choferes_por_rut.setdefault(fila["CHOFER"].strip().upper(), set()).add(fila["PATENTE TRACTO"].strip().upper())

    for fila in filas:
        nombre = fila["NOMBRE ARCHIVO"]
        id_m = f"A{int(fila['N° MUESTRA']):02d}"
        origen = fotos / nombre
        copia = salida / "imagenes" / f"{id_m}_{nombre}"
        shutil.copy2(origen, copia)
        h = sha256(origen)
        if sha256(copia) != h:
            raise SystemExit(f"Copia alterada: {copia}")
        ancho, alto, pags = dimensiones(origen)
        estado_doc = fila["ESTADO DOCUMENTO"].strip().upper()
        manifiesto.append({
            "id_muestra": id_m, "bloque": "A_REFERENCIA_HUMANA", "canal": "WHATSAPP_HISTORICO",
            "archivo_copia": copia.name, "sha256": h, "bytes": origen.stat().st_size,
            "formato": origen.suffix.lower().lstrip("."), "ancho_px": ancho, "alto_px": alto, "paginas_pdf": pags,
            "ruta_origen": str(origen), "nombre_origen": nombre, "fecha_origen": "",
            "criterio_seleccion": "muestra_fechas_30 completa (selección 2026-07-15, resumen_seleccion.md)",
            "pista_nombre_archivo": "",
            "tipo_documento_estado": "CONFIRMADO_HUMANO (guía de despacho electrónica AZA, resumen_seleccion.md)",
            "procedencia_original": "copia diagnóstica de los originales 'informe lunes' (resumen_seleccion.md)",
        })
        obs = fila.get("OBSERVACIONES", "").strip()
        for campo, col in CAMPOS:
            crudo = str(fila.get(col, "")).strip() if col else ""
            reg = {"id_muestra": id_m, "campo": campo, "valor_referencia": "", "estado": "",
                   "valor_crudo_fuente": crudo, "fuente": "validacion_atlas_30_guias_v1.xlsx / Datos guías",
                   "alternativa_no_confirmada": "", "nota": ""}
            notas = []
            if col is None:
                reg.update(estado="PENDIENTE_CONFIRMACION", fuente="",
                           nota="Campo no registrado en la planilla humana (DESPACHAR A, regla E1)")
                referencia.append(reg)
                continue
            if not crudo:
                if estado_doc == "ILEGIBLE":
                    reg["estado"] = "ILEGIBLE"
                elif estado_doc == "GUÍA INCOMPLETA":
                    reg["estado"] = "PENDIENTE_CONFIRMACION"
                    notas.append("Vacío en guía marcada INCOMPLETA: no distingue ausente de cortado")
                else:
                    reg["estado"] = "AUSENTE"
            else:
                normal = crudo.upper() if campo not in ("descripcion_material",) else crudo
                if campo == "fecha_emision":
                    normal = fecha_serial(crudo)
                elif campo in ("hora_entrada", "hora_salida"):
                    normal = hora(crudo)
                elif campo == "peso_kg":
                    normal = peso(crudo)
                elif campo in ("patente_tracto", "patente_rampla"):
                    normal = crudo.replace(" ", "").upper()
                    if not PATENTE_CHILENA.fullmatch(normal):
                        notas.append("Formato de patente no chileno (LLNNNN o LLLLNN)")
                        otras = choferes_por_rut.get(fila["CHOFER"].strip().upper(), set()) - {normal}
                        if otras:
                            notas.append("El mismo chofer registra en otras filas: " + ", ".join(sorted(otras)))
                elif campo in ("rut_chofer", "rut_cliente"):
                    if validar_rut_chileno(crudo).estado != EstadoValidacion.VALIDO:
                        notas.append("RUT no válido según validar_rut_chileno de Motor")
                if normal is None:
                    notas.append("Formato no interpretable sin suponer")
                if re.search(r"\?|REVISAR", crudo, re.I):
                    notas.append("Valor con duda explícita en la planilla")
                reg["valor_referencia"] = normal or ""
                reg["estado"] = "CONFIRMADO_HUMANO"
                if estado_doc == "ILEGIBLE":
                    notas.append("Documento marcado ILEGIBLE por el validador" + (f"; observación: {obs}" if obs else ""))
            previo = str(prellenado.get(nombre, {}).get(col, "")).strip()
            validada = fila["VALIDADO"].strip().upper() in ("SI", "SÍ")
            if (nombre, campo) in dudas:
                _, duda = dudas[(nombre, campo)]
                if validada and crudo and crudo != previo:
                    reg["fuente"] += f" (corregido en revisión humana; duda previa: {duda or 'vacío'})"
                else:
                    notas.append(f"Hoja 'Pendientes de verificación' sin resolver (duda: {duda or 'vacío'})")
            elif crudo and crudo != previo:
                reg["fuente"] += " (corregido en revisión humana)"
            elif crudo:
                reg["fuente"] += " (valor prellenado, fila validada por persona)"
            if (nombre, campo) in DISCREPANCIAS_BITACORA:
                reg["alternativa_no_confirmada"] = DISCREPANCIAS_BITACORA[(nombre, campo)]
                notas.append(NOTA_BITACORA)
            if campo == "fecha_emision":
                rev = fechas_revision.get(nombre)
                if rev and rev != reg["valor_referencia"]:
                    reg["alternativa_no_confirmada"] = rev
                    notas.append("muestra_fechas_revision_actualizada.xlsx (revisión humana) registra otra fecha")
            if campo == "cod_destinatario" and crudo and crudo == str(fila.get("CÓDIGO CLIENTE", "")).strip():
                notas.append("Igual al CÓDIGO CLIENTE: posible confusión de campo (hallazgo D3)")
            if notas and reg["estado"] == "CONFIRMADO_HUMANO":
                reg["estado"] = "PENDIENTE_CONFIRMACION"
            if notas and reg["estado"] in ("AUSENTE", "ILEGIBLE") and reg["alternativa_no_confirmada"]:
                reg["estado"] = "PENDIENTE_CONFIRMACION"
            reg["nota"] = " | ".join(notas)
            if reg["estado"] == "PENDIENTE_CONFIRMACION" and col:
                conflictos.append(reg)
            referencia.append(reg)
    return {"xlsx_referencia": (str(xlsx), sha256(xlsx)), "xlsx_fechas": (str(xlsx_fechas), sha256(xlsx_fechas)),
            "xlsx_prellenada": (str(xlsx_pre), sha256(xlsx_pre))}


# ------------------------------------------- bloques B y C (sin referencia)

def _pendientes(id_m: str, referencia: list, nota: str):
    for campo, _ in CAMPOS:
        referencia.append({"id_muestra": id_m, "campo": campo, "valor_referencia": "",
                           "estado": "PENDIENTE_CONFIRMACION", "valor_crudo_fuente": "", "fuente": "",
                           "alternativa_no_confirmada": "", "nota": nota})


# Únicas claves de envio.json que se leen: metadatos del chofer y de la
# recepción. `datos_ocr`, `resultado_asociacion`, `estado` y `atlas_ia` son
# salida de Atlas y no se consultan.
CLAVES_ENVIO = ("envio_id", "recibido_en", "chofer_id", "rol_documento", "tipos_novedad",
                "guia_firmada_correo", "imagen_sha256", "foto_original")


def bloque_b(raiz: Path, salida: Path, k: int, manifiesto: list, referencia: list, excluir: set):
    envios = []
    for d in sorted((raiz / "operacion" / "mobile" / "envios").iterdir()):
        bruto = json.loads((d / "envio.json").read_text(encoding="utf-8"))
        meta = {c: bruto.get(c) for c in CLAVES_ENVIO}
        meta["_dir"] = d
        if meta["rol_documento"] == "EVIDENCIA":
            continue  # no es una guía
        envios.append(meta)
    envios.sort(key=lambda e: (e["recibido_en"] or "", e["envio_id"]))
    elegidos, motivo = [], {}

    def tomar(e, m):
        if e["envio_id"] not in motivo and sha256(e["_dir"] / "original.jpg") not in excluir:
            elegidos.append(e)
            motivo[e["envio_id"]] = m

    for tipo in sorted({t for e in envios for t in (e["tipos_novedad"] or [])}):
        grupo = [e for e in envios if tipo in (e["tipos_novedad"] or [])]
        tomar(equidistantes(grupo, 1)[0], f"novedad declarada {tipo}")
    for e in equidistantes([e for e in envios if e["guia_firmada_correo"]], 2):
        tomar(e, "guía firmada por correo")
    for chofer in sorted({e["chofer_id"] for e in envios}, key=str):
        if not any(x["chofer_id"] == chofer for x in elegidos):
            tomar(equidistantes([e for e in envios if e["chofer_id"] == chofer], 1)[0], "cobertura de chofer")
    restantes = [e for e in envios if e["envio_id"] not in motivo]
    for e in equidistantes(restantes, max(0, k - len(elegidos))):
        tomar(e, "equidistante por fecha de recepción")

    choferes = {c: f"CH{i + 1:02d}" for i, c in enumerate(sorted({e["chofer_id"] for e in envios}, key=str))}
    for i, e in enumerate(sorted(elegidos, key=lambda e: e["recibido_en"] or "")[:k], 1):
        id_m = f"B{i:02d}"
        origen = e["_dir"] / "original.jpg"
        copia = salida / "imagenes" / f"{id_m}_{e['envio_id']}.jpg"
        shutil.copy2(origen, copia)
        h = sha256(origen)
        if sha256(copia) != h:
            raise SystemExit(f"Copia alterada: {copia}")
        ancho, alto, pags = dimensiones(origen)
        manifiesto.append({
            "id_muestra": id_m, "bloque": "B_CANAL_MOBILE", "canal": "MOBILE_PWA",
            "archivo_copia": copia.name, "sha256": h, "bytes": origen.stat().st_size, "formato": "jpg",
            "ancho_px": ancho, "alto_px": alto, "paginas_pdf": pags, "ruta_origen": str(origen),
            "nombre_origen": f"envio {e['envio_id']}", "fecha_origen": e["recibido_en"] or "",
            "criterio_seleccion": f"{motivo[e['envio_id']]}; chofer {choferes[e['chofer_id']]}; "
                                  f"rol {e['rol_documento'] or 'NO_INFORMADO'}; "
                                  f"novedades {','.join(e['tipos_novedad'] or []) or 'ninguna'}",
            "pista_nombre_archivo": "",
            "tipo_documento_estado": "PENDIENTE_CONFIRMACION (rol declarado por el chofer)",
            "procedencia_original": "imagen_sha256 declarado en envio.json: "
                                    + ("coincide" if e["imagen_sha256"] == h else f"NO coincide ({e['imagen_sha256']})"),
        })
        _pendientes(id_m, referencia, "Sin referencia humana: completar desde la imagen")
    return len(envios)


def bloque_c(raiz: Path, salida: Path, cuotas: dict, manifiesto: list, referencia: list, excluir: set):
    archivos = []
    for d in sorted((raiz / "operacion" / "entradas").iterdir()):
        for f in sorted(d.iterdir()):
            if f.suffix.lower() in (".jpeg", ".jpg", ".png", ".pdf"):
                archivos.append(f)
    vistos = set(excluir)
    elegidos = []
    for formato, k in cuotas.items():
        grupo = [f for f in archivos if f.suffix.lower().lstrip(".").replace("jpg", "jpeg") == formato]
        if formato == "pdf":
            # Cubrir ambos patrones de nombre: reenviados "[MBT] ... firmada" y numéricos.
            reenviados = [f for f in grupo if f.name.startswith("[MBT]")]
            otros = [f for f in grupo if not f.name.startswith("[MBT]")]
            candidatos = equidistantes(reenviados, k - min(2, len(otros))) + equidistantes(otros, min(2, len(otros)))
        else:
            candidatos = equidistantes(grupo, k)
        for f in candidatos:
            h = sha256(f)
            if h in vistos:
                continue
            vistos.add(h)
            elegidos.append((f, h, formato))
    for i, (f, h, formato) in enumerate(elegidos, 1):
        id_m = f"C{i:02d}"
        copia = salida / "imagenes" / f"{id_m}_{f.parent.name}{f.suffix.lower()}"
        shutil.copy2(f, copia)
        if sha256(copia) != h:
            raise SystemExit(f"Copia alterada: {copia}")
        ancho, alto, pags = dimensiones(f)
        pista = re.search(r"(?:nro|guia[-\s]?)\s*(\d{6})|^(\d{6})\.", f.name, re.I)
        manifiesto.append({
            "id_muestra": id_m, "bloque": "C_INGRESO_MANUAL", "canal": "DESKTOP_MANUAL",
            "archivo_copia": copia.name, "sha256": h, "bytes": f.stat().st_size, "formato": formato,
            "ancho_px": ancho, "alto_px": alto, "paginas_pdf": pags, "ruta_origen": str(f),
            "nombre_origen": f.name, "fecha_origen": f.parent.name[:15],
            "criterio_seleccion": f"formato {formato}, equidistante por carpeta de ingreso",
            "pista_nombre_archivo": (pista.group(1) or pista.group(2)) if pista else "",
            "tipo_documento_estado": "PENDIENTE_CONFIRMACION",
            "procedencia_original": "operacion/entradas (ingreso manual Desktop)",
        })
        _pendientes(id_m, referencia, "Sin referencia humana: completar desde la imagen; "
                                      "el número en el nombre de archivo es sólo una pista")
    return len(archivos)


# ---------------------------------------------------------------- principal

def escribir_csv(ruta: Path, filas: list, columnas: list):
    with open(ruta, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columnas)
        w.writeheader()
        w.writerows(filas)


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--raiz-atlas", required=True, type=Path)
    p.add_argument("--motor", required=True, type=Path)
    p.add_argument("--salida", required=True, type=Path)
    p.add_argument("--discrepancias", type=Path, help="JSON privado con discrepancias documentadas")
    p.add_argument("--mobile", type=int, default=20)
    a = p.parse_args()
    (a.salida / "imagenes").mkdir(parents=True, exist_ok=False)
    if a.discrepancias:
        for d in json.loads(a.discrepancias.read_text(encoding="utf-8"))["discrepancias"]:
            DISCREPANCIAS_BITACORA[(d["archivo"], d["campo"])] = d["alternativa"]

    manifiesto, referencia, conflictos = [], [], []
    fuentes = bloque_a(a.raiz_atlas, a.motor, a.salida, manifiesto, referencia, conflictos)
    excluir = {m["sha256"] for m in manifiesto}
    total_mobile = bloque_b(a.raiz_atlas, a.salida, a.mobile, manifiesto, referencia, excluir)
    excluir = {m["sha256"] for m in manifiesto}
    total_entradas = bloque_c(a.raiz_atlas, a.salida, {"png": 3, "pdf": 5, "jpeg": 7}, manifiesto, referencia, excluir)

    shas = [m["sha256"] for m in manifiesto]
    if len(shas) != len(set(shas)):
        raise SystemExit("SHA-256 duplicado en la muestra")
    assert all(r["estado"] in ESTADOS for r in referencia)

    escribir_csv(a.salida / "manifiesto.csv", manifiesto, COLUMNAS_MANIFIESTO)
    escribir_csv(a.salida / "referencia_campos.csv", referencia, COLUMNAS_REFERENCIA)
    escribir_csv(a.salida / "pendientes_confirmacion.csv", conflictos, COLUMNAS_REFERENCIA)

    # Planilla ancha para que una persona complete B, C y los pendientes de A.
    ancha = []
    for m in manifiesto:
        fila = {"id_muestra": m["id_muestra"], "archivo_copia": m["archivo_copia"]}
        for r in (r for r in referencia if r["id_muestra"] == m["id_muestra"]):
            fila[r["campo"]] = r["valor_referencia"]
            fila[r["campo"] + "__estado"] = r["estado"]
        ancha.append(fila)
    escribir_csv(a.salida / "planilla_confirmacion.csv", ancha,
                 ["id_muestra", "archivo_copia"] + [c for campo, _ in CAMPOS for c in (campo, campo + "__estado")])

    motor_head = subprocess.run(["git", "-C", str(a.motor), "rev-parse", "HEAD"],
                                capture_output=True, text=True).stdout.strip()
    resumen = {
        "generado_en": dt.datetime.now().isoformat(timespec="seconds"),
        "herramienta_sha256": sha256(Path(__file__)),
        "motor_head_validadores": motor_head,
        "fuentes": fuentes,
        "universo": {"mobile_envios_guia": total_mobile, "entradas_manual": total_entradas},
        "muestras": {b: sum(1 for m in manifiesto if m["bloque"] == b) for b in
                     ("A_REFERENCIA_HUMANA", "B_CANAL_MOBILE", "C_INGRESO_MANUAL")},
        "estados": {b: {e: sum(1 for r in referencia if r["id_muestra"][0] == b[0] and r["estado"] == e)
                        for e in ESTADOS} for b in ("A", "B", "C")},
        "estados_por_campo_A": {campo: {e: sum(1 for r in referencia if r["id_muestra"][0] == "A"
                                              and r["campo"] == campo and r["estado"] == e) for e in ESTADOS}
                                for campo, _ in CAMPOS},
    }
    (a.salida / "resumen.json").write_text(json.dumps(resumen, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: resumen[k] for k in ("universo", "muestras", "estados")}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
