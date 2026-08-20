"""Bloque ATLAS IA A2 -- lote real de casos vehiculares.

Runner de experimento (nunca parte de la suite de tests, nunca se
ejecuta automáticamente): construye `ContextoRazonamiento` REALES --
evidencia real ya reunida por `atlas_core.decisiones_pendientes.
evaluar_evidencia_patente`, el Motor determinista de vehículos ya en
producción -- para un lote curado de casos históricos reales, intenta
razonar sobre cada uno con un proveedor real en SHADOW MODE, valida cada
hipótesis con los validadores de A1 y guarda el resultado en un artefacto
JSONL dentro de este mismo directorio (`resultados/`) -- NUNCA en
`operacion/actual`, nunca en Drive.

SEGURIDAD -- este script es de SOLO LECTURA sobre Drive: copia
`analisis_completo_guias.csv` y `vehiculos.json` a un directorio temporal
del sistema (nunca dentro del repo, nunca los reescribe) antes de
leerlos, exactamente igual que las verificaciones de bloques anteriores
de este proyecto. Nunca escribe en `G:\\Mi unidad\\Atlas`, nunca aplica
ninguna decisión, nunca toca el ledger ni ningún catálogo real.

Selección de casos (elegidos empíricamente, consultando el Motor
determinista contra los datos reales -- nunca fabricados): ver
`CASOS_REALES_VEHICULOS` más abajo, con la categoría y el resultado real
que el Motor determinista ya produce para cada uno ANTES de que
cualquier IA intervenga.
"""

from __future__ import annotations

import csv
import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

# Este script vive en un subdirectorio (a diferencia de generar_reporte_viajes.py
# y demás CLIs en la raíz del repo, que ya encuentran atlas_core sin ayuda) --
# se agrega la raíz del repo al path antes de importar, sin depender de que
# quien lo ejecute haya configurado PYTHONPATH.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from atlas_core.atlas_ia.adaptadores import contexto_desde_resultado_evaluar_evidencia_patente
from atlas_core.atlas_ia.proveedor import ProveedorModeloIA
from atlas_core.atlas_ia.proveedor_anthropic import CredencialProveedorIAAusente, ProveedorModeloIAAnthropic
from atlas_core.atlas_ia.proveedor_ollama import ProveedorModeloIAOllama
from atlas_core.atlas_ia.shadow import ejecutar_shadow
from atlas_core.catalogo_vehiculos import cargar_catalogo_vehiculos
from atlas_core.decisiones_pendientes import evaluar_evidencia_patente

_AUSENTES = {"", "No encontrado"}

RUTA_DATASET_REAL = Path(r"G:\Mi unidad\Atlas\operacion\actual\analisis_completo_guias.csv")
RUTA_CATALOGO_REAL = Path(r"G:\Mi unidad\Atlas\catalogos_privados\vehiculos.json")
RUTA_RESULTADOS = Path(__file__).parent / "resultados"

# Casos reales, seleccionados consultando directamente el Motor
# determinista contra los datos reales de la operación vigente
# (2026-08-20). "ground_truth" es lo que ya se sabe por el ledger de
# decisiones reales o, cuando no hubo decisión, se marca explícitamente
# como tal -- nunca se le entrega este valor al modelo, sólo se usa para
# comparar DESPUÉS de que responda.
CASOS_REALES_VEHICULOS = [
    {
        "numero_guia": "464036", "campo": "patente_tracto",
        "categoria": "A_correccion_esperada_pero_declinada_por_humano",
        "ground_truth": (
            "SIN_SUSTITUTO (NO_REGISTRAR / ERROR_DOCUMENTAL_MANDANTE -- Javier declinó "
            "explícitamente sustituir XF3662 por ningún valor, aunque XF3629 era el único "
            "candidato circunstancial que el propio Motor determinista ya encontraba)"
        ),
        "resultado_motor_esperado": "SUGERENCIA_HUMANA",
    },
    {
        "numero_guia": "464265", "campo": "patente_tracto",
        "categoria": "A_correccion_esperada",
        "ground_truth": "VP8521",
        "resultado_motor_esperado": "SUGERENCIA_HUMANA",
    },
    {
        "numero_guia": "464264", "campo": "patente_rampla",
        "categoria": "B_ya_resuelto_por_motor_deterministico",
        "ground_truth": "JD8659",
        "resultado_motor_esperado": "RESUELTO_AUTOMATICAMENTE",
    },
    {
        "numero_guia": "464698", "campo": "patente_rampla",
        "categoria": "B_ya_resuelto_por_motor_deterministico",
        "ground_truth": "JD8659",
        "resultado_motor_esperado": "RESUELTO_AUTOMATICAMENTE",
    },
    {
        "numero_guia": "463594", "campo": "patente_tracto",
        "categoria": "D_abstencion_esperada",
        "ground_truth": (
            "SIN_DECISION_REGISTRADA (ninguna decisión humana fue necesaria -- no existe "
            "evidencia circunstancial alguna para este vehículo/RUT)"
        ),
        "resultado_motor_esperado": "ABSTENCION",
    },
    {
        "numero_guia": "464424", "campo": "patente_tracto",
        "categoria": "D_abstencion_esperada",
        "ground_truth": (
            "SIN_DECISION_REGISTRADA (ninguna decisión humana fue necesaria -- no existe "
            "evidencia circunstancial alguna para este vehículo/RUT)"
        ),
        "resultado_motor_esperado": "ABSTENCION",
    },
]


def _copiar_fuentes_reales_a_temporal() -> tuple[Path, Path]:
    """Copia (solo lectura sobre Drive) el dataset y el catálogo de
    vehículos vigentes a un directorio temporal del sistema -- nunca
    dentro del repo, nunca se escribe de vuelta a Drive."""
    if not RUTA_DATASET_REAL.is_file() or not RUTA_CATALOGO_REAL.is_file():
        raise FileNotFoundError(
            "No se encontró el dataset/catálogo real en Drive -- verifique que "
            "G:\\Mi unidad\\Atlas esté disponible antes de ejecutar el experimento."
        )
    temporal = Path(tempfile.mkdtemp(prefix="atlas_ia_a2_"))
    dataset = temporal / "analisis_completo_guias.csv"
    catalogo = temporal / "vehiculos.json"
    shutil.copy(RUTA_DATASET_REAL, dataset)
    shutil.copy(RUTA_CATALOGO_REAL, catalogo)
    return dataset, catalogo


def _tipo_esperado_para(campo: str, fila: dict) -> str | None:
    """Reconstrucción simplificada, sólo para este experimento, del
    criterio real que usa la producción (`enriquecer_decisiones_vehiculo`,
    que en producción lee `tipo_vehiculo_propuesto` ya calculado al crear
    la decisión pendiente original). Aquí no se dispone de ese campo para
    guías arbitrarias fuera del ledger, así que se aproxima con la misma
    regla de compatibilidad ya usada en
    `atlas_core.revalidacion_documental.revalidar_patente_sin_homologar_sin_ocr`:
    rampla presente -> tracto espera TRACTO, rampla espera CARRO; sin
    rampla -> sin tipo esperado (permisivo). NUNCA se usa para aplicar
    ninguna decisión real -- sólo para construir evidencia de experimento
    fiel al comportamiento de producción."""
    rampla_presente = fila.get("patente_rampla", "").strip() not in _AUSENTES
    if campo == "patente_rampla":
        return "CARRO" if rampla_presente else None
    return "TRACTO" if rampla_presente else None


def construir_casos_reales(
    dataset_path: Path, catalogo_path: Path,
) -> list[tuple[str, object, str]]:
    """Construye, para cada entrada de `CASOS_REALES_VEHICULOS`, un
    `ContextoRazonamiento` real -- llamando exactamente al mismo Motor
    determinista que usa producción (`evaluar_evidencia_patente`) sobre
    los datos reales ya copiados. Devuelve una lista de
    `(caso_id, contexto, ground_truth)`, lista para `ejecutar_shadow`."""
    with dataset_path.open(encoding="utf-8-sig", newline="") as archivo:
        filas = list(csv.DictReader(archivo, delimiter=";"))
    vehiculos = cargar_catalogo_vehiculos(catalogo_path).homologables()
    filas_por_guia = {f["numero_guia"]: f for f in filas}

    casos: list[tuple[str, object, str]] = []
    for caso in CASOS_REALES_VEHICULOS:
        fila = filas_por_guia[caso["numero_guia"]]
        campo = caso["campo"]
        valor_documental = fila[campo].strip()
        tipo_esperado = _tipo_esperado_para(campo, fila)
        resultado_evidencia = evaluar_evidencia_patente(
            campo=campo, valor_documental=valor_documental, rut_chofer=fila["rut_chofer"],
            tipo_esperado=tipo_esperado, numero_transporte_actual=fila["numero_transporte"],
            filas=filas, vehiculos=vehiculos,
        )
        contexto = contexto_desde_resultado_evaluar_evidencia_patente(
            campo=campo, valor_documental=valor_documental, rut_chofer=fila["rut_chofer"],
            numero_guia=caso["numero_guia"], numero_transporte=fila["numero_transporte"],
            resultado_evidencia=resultado_evidencia,
        )
        casos.append((caso["numero_guia"], contexto, caso["ground_truth"]))
    return casos


def ejecutar_experimento(
    *, proveedor: ProveedorModeloIA, ruta_salida: Path | None = None,
) -> list:
    """Orquesta el experimento completo: copia read-only de Drive,
    construcción de contextos reales, razonamiento en shadow, validación,
    y persistencia del artefacto JSONL. Nunca toca `operacion/actual` ni
    ningún catálogo/ledger real."""
    dataset, catalogo = _copiar_fuentes_reales_a_temporal()
    try:
        casos = construir_casos_reales(dataset, catalogo)
    finally:
        shutil.rmtree(dataset.parent, ignore_errors=True)

    ruta_salida = ruta_salida or (RUTA_RESULTADOS / "lote_vehiculos_a2.json")
    return ejecutar_shadow(casos=casos, proveedor=proveedor, persistir=True, ruta_salida=ruta_salida)


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark real Atlas IA en SHADOW")
    parser.add_argument("--proveedor", choices=("anthropic", "ollama"), default="anthropic")
    parser.add_argument("--modelo", default=None)
    parser.add_argument("--salida", type=Path, default=None)
    args = parser.parse_args()

    if args.proveedor == "ollama":
        proveedor = ProveedorModeloIAOllama(modelo=args.modelo or "qwen3:4b")
        ruta_salida = args.salida or (RUTA_RESULTADOS / "lote_vehiculos_a2_ollama_qwen3_4b.json")
    else:
        proveedor = ProveedorModeloIAAnthropic(modelo=args.modelo or "claude-sonnet-5")
        ruta_salida = args.salida
    try:
        resultados = ejecutar_experimento(proveedor=proveedor, ruta_salida=ruta_salida)
    except CredencialProveedorIAAusente as error:
        print("BLOQUEADO -- no se ejecutó ninguna llamada real.")
        print(str(error))
        return 1
    for resultado in resultados:
        print(
            f"{resultado.caso_id}: motor={resultado.resultado_motor} "
            f"modelo={resultado.hipotesis.resultado}({resultado.hipotesis.valor_propuesto!r}) "
            f"validacion={'ACEPTADA' if resultado.validacion.aceptada else resultado.validacion.motivo_rechazo} "
            f"ground_truth={resultado.ground_truth_humano!r}"
        )
    print(f"Resultados guardados en: {ruta_salida or (RUTA_RESULTADOS / 'lote_vehiculos_a2.json')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
