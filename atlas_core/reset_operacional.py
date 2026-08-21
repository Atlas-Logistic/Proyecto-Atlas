"""Reset transaccional del estado visible; nunca toca conocimiento Atlas."""
from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path

from atlas_core.procesamiento_masivo import COLUMNAS


def reset_operacional_aislado(raiz: str | Path) -> dict[str, int]:
    """Vacía sólo operación/reportes de una raíz marcada explícitamente."""
    raiz = Path(raiz).resolve()
    marcador = raiz / ".atlas_reset_aislado_autorizado"
    if not marcador.is_file():
        raise PermissionError("La raíz no está marcada como copia aislada autorizada")
    actual = raiz / "operacion" / "actual"
    reportes = raiz / "reportes" / "actual"
    actual.mkdir(parents=True, exist_ok=True)
    reportes.mkdir(parents=True, exist_ok=True)
    dataset = actual / "analisis_completo_guias.csv"
    with dataset.open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.writer(archivo, delimiter=";")
        escritor.writerow(COLUMNAS)
    (actual / "decisiones_pendientes.json").write_text(json.dumps({
        "schema_version": 1, "generado_en": datetime.now(timezone.utc).isoformat(),
        "dataset_sha256": "", "catalogos_sha256": {}, "decisiones": [],
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (actual / "estado_operacion.json").write_text(json.dumps({
        "schema_version": 1, "reporte_vigente": "reportes/actual",
        "dataset_operacional": "operacion/actual/analisis_completo_guias.csv",
        "decisiones_pendientes": "operacion/actual/decisiones_pendientes.json",
        "fecha_actualizacion": datetime.now(timezone.utc).isoformat(), "origen": "RESET_CONTROLADO",
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for ruta in reportes.iterdir():
        if ruta.is_file():
            ruta.unlink()
    (reportes / "viajes.csv").write_text("", encoding="utf-8")
    (reportes / "resumen_viajes.md").write_text("# Operación Atlas\n\n0 documentos · 0 viajes · 0 revisiones.\n", encoding="utf-8")
    return {"documentos": 0, "viajes": 0, "revisiones": 0}
