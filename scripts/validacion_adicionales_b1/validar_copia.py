"""P1.3 sobre una COPIA de la raíz real (nunca la operativa).

    python scripts/validacion_adicionales_b1/validar_copia.py <raíz copia> <trabajo>

Aplica por el canal B1 (vista previa + «sí») las frases reales de adicionales y
verifica: una observación por viaje (también en viajes agrupados), guías no
encontradas nombradas, observaciones previas conservadas, nada de material y
que la consulta de adicionales vea el resultado. Sin red ni datos reales.
"""
from __future__ import annotations

import csv
import glob
import hashlib
import json
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
csv.field_size_limit(2**31 - 1)


def main() -> int:
    origen, trabajo = Path(sys.argv[1]), Path(sys.argv[2])
    assert "pruebas" in str(origen).lower() and "pruebas" in str(trabajo).lower()
    raiz = trabajo / f"V{int(time.time())}" / "Atlas"
    shutil.copytree(origen, raiz)
    huella_origen = {p.relative_to(origen): hashlib.sha256(p.read_bytes()).hexdigest() for p in origen.rglob("*") if p.is_file()}
    import os
    # La copia NUNCA toma el escritor real: el escritor operativo usa el lease
    # de Cloud del equipo (bloquearía el PULL de producción). Escritor simulado
    # y sin credencial en el entorno.
    if any(k in os.environ for k in ("ATLAS_CLOUD_MOTOR_TOKEN", "ATLAS_CLOUD_MOTOR_URL")):
        print("ERROR: quite ATLAS_CLOUD_MOTOR_TOKEN/URL del entorno antes de validar sobre una copia.")
        return 2

    class EscritorSimulado:
        vigente = True

        def adquirir(self):
            return True

        def cerrar(self):
            pass

    from atlas_core.acciones_operacionales import CapaAccionesOperacionales
    from atlas_core.b1_operador import OperadorB1
    from atlas_core.registro_eventos_operacionales import leer_eventos_operacionales
    b1 = OperadorB1(raiz, usuario="JAVIER_DESKTOP",
                    capa=CapaAccionesOperacionales(raiz, fabrica_escritor=lambda: EscritorSimulado()))
    dataset = raiz / "operacion" / "actual" / "analisis_completo_guias.csv"
    antes_dataset = hashlib.sha256(dataset.read_bytes()).hexdigest()
    verificaciones: list[tuple[str, bool]] = []
    informe: dict[str, object] = {}

    def check(nombre, ok):
        verificaciones.append((nombre, bool(ok)))
        print(("OK  " if ok else "FALLA ") + nombre)

    def notas():
        return {e["numero_transporte"]: e["nota"] for e in leer_eventos_operacionales(raiz=raiz)["eventos"]
                if e.get("tipo_evento") == "OBSERVACION_OPERACIONAL" and e.get("estado") == "ACTIVO"}

    def turno(nombre, frase):
        consulta = b1.consultar(frase, derivar_operacionales=True)
        r = b1.atender("validacion", frase) if consulta.get("estado") == "REQUIERE_OPERADOR" else consulta
        informe[nombre] = {"consultar": consulta.get("estado"), "estado": r.get("estado"), "accion": r.get("accion"),
                           "mensaje": r.get("mensaje"),
                           "tablas": r.get("tablas")}
        return consulta, r

    previas = notas()
    # 1. Las guías 483732 y 483934 (dos viajes, Portezuelo).
    c, r = turno("portezuelo", "Las guías 483732 y 483934 tienen adicional de 30.000 por retiro de materiales en Portezuelo.")
    filas = {f[0]: f for f in (r.get("tablas") or [{}])[0].get("filas", [])}
    check("Portezuelo: vista previa con un viaje por guía (2 viajes)", r["estado"] == "PREVIEW_PENDIENTE" and len(filas) == 2)
    check("Portezuelo: acción de observación, no material", r.get("accion") == "VIAJE_AGREGAR_OBSERVACION")
    resultado = b1.atender("validacion", "sí")
    check("Portezuelo: aplicado", resultado["estado"] == "EJECUTADA")
    n = notas()
    for t in filas:
        check(f"Portezuelo: viaje {t} con el motivo nuevo y el resto conservado",
              "RETIRO DE MATERIALES EN PORTEZUELO" in n[t]
              and all(l in n[t] for l in previas.get(t, "").splitlines() if "ADICIONAL" not in l))
    # 2. La guía 482634 (frase declarativa singular).
    c, r = turno("versalles_declarativa", "La guía 482634 tiene adicional de 30.000 por carga en Versalles.")
    check("Versalles declarativa: antes no se interpretaba; ahora vista previa", c["estado"] == "REQUIERE_OPERADOR"
          and r["estado"] == "PREVIEW_PENDIENTE")
    check("Versalles declarativa: aplicada", b1.atender("validacion", "sí")["estado"] == "EJECUTADA")
    # 3. Misma orden en forma imperativa: ya registrada, sin duplicar ni confirmar.
    c, r = turno("versalles_orden", "Agrega un adicional de $30.000 por carga en Versalles al viaje de la guía 482634.")
    check("Versalles orden: reconocida y sin duplicar (sin confirmación)", r["estado"] == "SIN_CAMBIOS"
          and b1.pendiente("validacion") is None)
    n = notas()
    check("Versalles: una sola línea de adicional en 0000365167",
          sum("ADICIONAL" in l for l in n["0000365167"].splitlines()) == 1 and "POR CARGA EN VERSALLES" in n["0000365167"])
    # 4. Viaje agrupado (0000360122 + 0000360179) y una guía inexistente.
    c, r = turno("agrupado", "Agrega un adicional de $20.000 por espera en obra a las guías 474597, 480603 y 999999")
    tablas = r.get("tablas") or []
    check("Agrupado: un solo viaje en la vista previa", r["estado"] == "PREVIEW_PENDIENTE"
          and [f[0] for f in tablas[0]["filas"]] == ["0000360122"])
    check("Agrupado: guía 999999 nombrada como no encontrada", "guía 999999" in r["mensaje"]
          and tablas[1]["filas"][0][0] == "guía 999999")
    check("Agrupado: aplicado", b1.atender("validacion", "sí")["estado"] == "EJECUTADA")
    n = notas()
    check("Agrupado: registrado una vez, en el transporte principal", "ESPERA EN OBRA" in n.get("0000360122", "")
          and "ESPERA EN OBRA" not in n.get("0000360179", ""))
    # 5. Ninguna válida: sin confirmación.
    c, r = turno("ninguna", "Las guías 999998 y 999999 tienen adicional de 10.000 por espera")
    check("Ninguna válida: sin cambios, sin pendiente, no encontradas nombradas",
          r["estado"] == "SIN_CAMBIOS" and b1.pendiente("validacion") is None and "guía 999998" in r["mensaje"])
    # 6. Sin monto: aclaración, nunca consulta/incidencias.
    c, r = turno("sin_monto", "La guía 482634 tiene adicional por carga en Versalles")
    check("Sin monto: aclaración por B1", c["estado"] == "REQUIERE_OPERADOR" and r["estado"] == "ACLARACION_REQUERIDA")
    # 7. Nada fuera de las observaciones cambió; la consulta de adicionales lo ve.
    check("Dataset intacto (no es una corrección de material)", hashlib.sha256(dataset.read_bytes()).hexdigest() == antes_dataset)
    from atlas_core.responder_consulta_atlas import responder_consulta_atlas
    estado = json.loads((raiz / "operacion" / "actual" / "estado_operacion.json").read_text(encoding="utf-8-sig"))
    ruta = raiz / estado["reporte_vigente"] / "viajes.csv"
    consulta = responder_consulta_atlas("viajes con adicional por carga en Versalles", ruta_viajes=ruta, raiz_atlas=raiz)
    informe["consulta_versalles"] = consulta.texto_respuesta
    check("Consulta de adicionales ve 0000365167 con carga en Versalles",
          consulta.resultado is not None and any(v.get("numero_transporte") == "0000365167"
                                                 for v in consulta.resultado.viajes_soporte))
    check("Origen de la copia intacto", {p.relative_to(origen): hashlib.sha256(p.read_bytes()).hexdigest()
                                         for p in origen.rglob("*") if p.is_file()} == huella_origen)
    informe["verificaciones"] = verificaciones
    (trabajo / "informe_adicionales.json").write_text(json.dumps(informe, ensure_ascii=False, indent=2, default=str),
                                                     encoding="utf-8")
    shutil.rmtree(raiz.parent)
    fallas = [v for v, ok in verificaciones if not ok]
    print(f"{len(verificaciones) - len(fallas)}/{len(verificaciones)} verificaciones")
    return 1 if fallas else 0


if __name__ == "__main__":
    sys.exit(main())
