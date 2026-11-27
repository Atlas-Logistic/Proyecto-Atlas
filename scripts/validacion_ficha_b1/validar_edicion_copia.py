"""Edición integral de la ficha B1 sobre una COPIA de la raíz (nunca la operativa).

    python scripts/validacion_ficha_b1/validar_edicion_copia.py <raíz copia> <carpeta trabajo>

Copia otra vez la raíz a <carpeta trabajo>, aplica por el canal B1 (lote de la
ficha + lenguaje natural) las correcciones de 492295, 492296, 483939 y un campo
común a las cinco guías de 0000368327, y verifica: preview con valor anterior y
nuevo, confirmación humana, auditoría y ledger, consolidado y motivos del viaje
recalculados, comuna en el reporte y originales intactos. La ruta se calcula
con un proveedor simulado: la validación no consulta servicios externos.
"""
from __future__ import annotations

import csv
import hashlib
import json
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
csv.field_size_limit(2**31 - 1)


def huella(ruta: Path) -> str:
    return hashlib.sha256(ruta.read_bytes()).hexdigest()


def main() -> int:
    origen, trabajo = Path(sys.argv[1]), Path(sys.argv[2])
    assert "pruebas" in str(origen).lower() and "pruebas" in str(trabajo).lower(), "sólo bajo C:/Atlas/pruebas"
    raiz = trabajo / f"V{int(time.time())}" / "Atlas"
    shutil.copytree(origen, raiz)
    originales = {p.relative_to(raiz): huella(p) for p in (raiz / "operacion" / "mobile").rglob("*") if p.is_file()}
    origen_antes = {p.relative_to(origen): huella(p) for p in origen.rglob("*") if p.is_file()}

    from atlas_core import destino_operacional
    from atlas_core.b1_operador import OperadorB1
    from atlas_core.edicion_ficha_b1 import codificar_lote

    rutas = []

    def ruta_simulada(fila, direccion, comuna, **_):
        rutas.append((fila.get("numero_guia"), direccion, comuna))
        return {"estado_ruta": destino_operacional.RUTA_CALCULADA, "distancia_km": "12.5", "duracion_min": "18",
                "proveedor_ruta": "SIMULADO_VALIDACION", "comuna": comuna}

    destino_operacional.calcular_ruta_operacional = ruta_simulada
    b1 = OperadorB1(raiz, usuario="JAVIER_DESKTOP")
    informe: dict[str, object] = {"raiz": str(raiz)}
    verificaciones: list[tuple[str, bool]] = []

    def ficha(texto):
        return b1.consultar(texto, derivar_operacionales=True)["ficha"]

    def campo(guia, nombre):
        return next(c for c in guia["campos"] if c["campo"] == nombre)

    def guia_de(f, numero):
        return next(g for g in f["guias"] if g["documento"]["numero_guia"] == numero)

    def check(nombre, condicion):
        verificaciones.append((nombre, bool(condicion)))
        print(("OK  " if condicion else "FALLA ") + nombre)

    # --- 1. Transporte 0000372894: 492296 sin dirección/comuna; 492295 con hora en conflicto.
    f = ficha("Datos del transporte 0000372894")
    g95, g96 = guia_de(f, "492295"), guia_de(f, "492296")
    check("ficha 372894: edición disponible con opciones de comuna",
          f["edicion"]["disponible"] and "QUILICURA" in f["edicion"]["opciones"]["localidad_entrega"])
    check("ficha 372894: 492296 con el destino vigente leído con O («989O»)",
          "989O" in str(campo(g96, "direccion_entrega")["valor"] or campo(g96, "direccion_entrega")["valores"]))
    lote = codificar_lote([
        # Dirección y comuna como campo común a las dos guías (selección explícita).
        *({"archivo": g["documento"]["archivo"], "numero_guia": g["documento"]["numero_guia"],
           "campo": c, "valor": v} for g in (g95, g96)
          for c, v in (("direccion_entrega", "CERRO SAN LUIS 9890 B"), ("localidad_entrega", "QUILICURA"))),
        {"archivo": g95["documento"]["archivo"], "numero_guia": "492295", "campo": "hora_entrada_aza", "valor": "07:12"},
        {"archivo": g95["documento"]["archivo"], "numero_guia": "492295", "campo": "hora_salida_aza", "valor": "07:40"},
        {"archivo": g96["documento"]["archivo"], "numero_guia": "492296", "campo": "hora_salida_aza", "valor": "07:40"},
    ])
    preview = b1.atender("ficha-validacion", lote)
    informe["preview_372894"] = preview
    filas = (preview.get("tablas") or [{}])[0].get("filas") or []
    check("preview 372894: 5 cambios con valor anterior y nuevo", preview["estado"] == "PREVIEW_PENDIENTE" and len(filas) == 5)
    check("preview 372894: ausente mostrado como (sin dato)", any(r[2] == "(sin dato)" and r[3] == "07:40" for r in filas))
    check("preview 372894: dirección+comuna de 492296 en un solo cambio",
          any(r[0] == "492296" and "Comuna" in r[1] and "QUILICURA" in r[3] for r in filas))
    check("preview 372894: hora de entrada 12:00 -> 07:12", any(r[0] == "492295" and r[2] == "12:00" and r[3] == "07:12" for r in filas))
    dataset = raiz / "operacion" / "actual" / "analisis_completo_guias.csv"
    antes_dataset = huella(dataset)
    check("preview no escribe el dataset", huella(dataset) == antes_dataset)
    resultado = b1.atender("ficha-validacion", "sí")
    informe["resultado_372894"] = resultado
    check("confirmación 372894 ejecutada", resultado["estado"] == "EJECUTADA")
    f = ficha("Datos del transporte 0000372894")
    g95, g96 = guia_de(f, "492295"), guia_de(f, "492296")
    viaje = f["viajes"][0]
    check("492296 con comuna QUILICURA", campo(g96, "localidad_entrega")["valor"] in {"QUILICURA", "Quilicura"})
    check("492296 con dirección corregida", "CERRO SAN LUIS 9890 B" in (campo(g96, "direccion_entrega")["valor"] or ""))
    check("viaje 372894: hora de entrada consolidada sin conflicto",
          campo(viaje, "hora_entrada_aza")["estado"] == "OK" and campo(viaje, "hora_entrada_aza")["valor"] == "07:12")
    check("viaje 372894: motivo CONFLICTO_HORA_ENTRADA retirado",
          "CONFLICTO_HORA_ENTRADA" not in (campo(viaje, "motivos_revision")["valor"] or ""))
    check("viaje 372894: ruta recalculada para 492296", any(r[0] == "492296" for r in rutas))

    # --- 2. 483939: dirección con el nombre del chofer pegado (lenguaje natural).
    natural = b1.atender("ficha-validacion", "La dirección de la guía 483939 es Maestra Lidia Torres 92, Recoleta")
    informe["natural_483939"] = natural
    check("483939 lenguaje natural: preview", natural["estado"] == "PREVIEW_PENDIENTE")
    natural_ok = b1.atender("ficha-validacion", "sí")
    check("483939 lenguaje natural: ejecutada", natural_ok["estado"] == "EJECUTADA")
    g39 = guia_de(ficha("Datos de la guía 483939"), "483939")
    check("483939 sin el nombre del chofer en la dirección",
          "PATRICK" not in (campo(g39, "direccion_entrega")["valor"] or "") and campo(g39, "localidad_entrega")["estado"] == "OK")

    # --- 3. Viaje de cinco guías: un campo común aplicado a todas (selección explícita en Desktop).
    f = ficha("Datos del viaje 0000368327")
    lote5 = codificar_lote([{"archivo": g["documento"]["archivo"], "numero_guia": g["documento"]["numero_guia"],
                             "campo": "hora_salida_aza", "valor": "11:45"} for g in f["guias"]])
    p5 = b1.atender("ficha-validacion", lote5)
    informe["preview_368327"] = p5
    check("viaje de cinco guías: 5 cambios en preview", p5["estado"] == "PREVIEW_PENDIENTE" and len(p5["tablas"][0]["filas"]) == 5)
    r5 = b1.atender("ficha-validacion", "sí")
    informe["resultado_368327"] = r5
    check("viaje de cinco guías: aplicado", r5["estado"] == "EJECUTADA")
    f = ficha("Datos del viaje 0000368327")
    check("viaje de cinco guías: hora de salida 11:45 en las cinco y en el consolidado",
          all(campo(g, "hora_salida_aza")["valor"] == "11:45" for g in f["guias"])
          and campo(f["viajes"][0], "hora_salida_aza")["valor"] == "11:45")

    # --- 4. Error en el lote: nada pendiente, nada escrito.
    antes = huella(dataset)
    malo = b1.atender("ficha-validacion", codificar_lote([
        {"archivo": g95["documento"]["archivo"], "numero_guia": "492295", "campo": "peso_kg", "valor": "13000"},
        {"archivo": g95["documento"]["archivo"], "numero_guia": "492295", "campo": "localidad_entrega", "valor": "NARNIA"}]))
    check("lote con un error: rechazado completo", malo["estado"] == "RECHAZADA" and b1.pendiente("ficha-validacion") is None)
    check("lote con un error: dataset intacto", huella(dataset) == antes)

    # --- 5. Auditoría, ledger y originales.
    ledger = json.loads((raiz / "operacion" / "actual" / "decisiones_aplicadas.json").read_text(encoding="utf-8"))
    humanas = [a for a in ledger.get("aplicaciones", []) if a.get("confirmado_por") == "JAVIER_DESKTOP"]
    check("ledger con correcciones confirmadas por la persona", len(humanas) >= 8)
    registro = json.loads((raiz / "operacion" / "actual" / "acciones_operacionales.json").read_text(encoding="utf-8"))
    auditoria = [a for a in registro.get("auditoria", []) if "ficha" in str(a.get("referencia", "")).lower()]
    check("auditoría de cada acción de la ficha", len(auditoria) >= 8)
    check("originales intactos", {p.relative_to(raiz): huella(p) for p in (raiz / "operacion" / "mobile").rglob("*")
                                  if p.is_file()} == originales)
    check("origen de la copia intacto", {p.relative_to(origen): huella(p) for p in origen.rglob("*") if p.is_file()} == origen_antes)

    # --- 6. Comuna en el reporte que leen Desktop, Excel y PDF.
    from atlas_core.consulta_revisiones_b1 import _ruta_viajes
    viajes = list(csv.DictReader(_ruta_viajes(b1.capa._ctx).open(encoding="utf-8-sig"), delimiter=";"))
    v372 = next(v for v in viajes if v["numero_transporte"] == "0000372894")
    check("reporte vigente: viaje 372894 con comuna", v372["localidad_entrega"].strip().upper() == "QUILICURA")
    check("reporte vigente: viaje 372894 con una sola entrega corregida",
          [e.get("destino_operacional") for e in json.loads(v372["entregas"])] == ["CERRO SAN LUIS 9890 B"])
    docs = {d["numero_guia"]: d for d in json.loads(v372["documentos_operacionales"])}
    check("reporte: destino operacional por documento (Excel/PDF)",
          all(docs[g].get("comuna_operacional") == "QUILICURA" and docs[g].get("direccion_operacional") == "CERRO SAN LUIS 9890 B"
              for g in ("492295", "492296")))
    v368 = next(v for v in viajes if v["numero_transporte"] == "0000368327")
    d39 = next(d for d in json.loads(v368["documentos_operacionales"]) if d["numero_guia"] == "483939")
    check("reporte: 483939 publica la dirección corregida sin el nombre del chofer",
          d39.get("direccion_operacional") == "MAESTRA LIDIA TORRES 92" and d39.get("comuna_operacional") == "RECOLETA")
    informe["reporte_372894"] = {k: v372[k] for k in ("localidad_entrega", "direccion_entrega", "hora_entrada_aza",
                                                      "hora_salida_aza", "motivos_revision", "estado", "entregas")}
    informe["verificaciones"] = verificaciones
    (trabajo / "informe_edicion.json").write_text(json.dumps(informe, ensure_ascii=False, indent=2, default=str),
                                                 encoding="utf-8")
    fallas = [n for n, ok in verificaciones if not ok]
    print(f"{len(verificaciones) - len(fallas)}/{len(verificaciones)} verificaciones")
    return 1 if fallas else 0


if __name__ == "__main__":
    sys.exit(main())
