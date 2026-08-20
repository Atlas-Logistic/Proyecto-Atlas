"""Muestra real multicampo B1 con Groq, siempre read-only sobre Drive."""

from __future__ import annotations

import csv
import json
import shutil
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from atlas_core.atlas_ia.contratos import ContextoRazonamiento, EvidenciaIA
from atlas_core.atlas_ia.herramientas import herramienta_documentos_relacionados
from atlas_core.atlas_ia.orquestador import OrquestadorAtlasIA
from atlas_core.atlas_ia.proveedor_groq import ProveedorModeloIAGroq
from experimentos_atlas_ia.lote_vehiculos_a2 import (
    RUTA_RESULTADOS,
    _copiar_fuentes_reales_a_temporal,
    construir_casos_reales,
)

RAIZ_ATLAS_DRIVE = Path(r"G:\Mi unidad\Atlas")
ESTADO_OPERACION = RAIZ_ATLAS_DRIVE / "operacion" / "actual" / "estado_operacion.json"


def _leer_csv(ruta: Path) -> list[dict[str, str]]:
    with ruta.open(encoding="utf-8-sig", newline="") as archivo:
        return list(csv.DictReader(archivo, delimiter=";"))


def _contextos_documentales(
    filas: list[dict[str, str]], viajes: list[dict[str, str]],
) -> list[tuple[str, ContextoRazonamiento, str]]:
    """Selecciona conflictos reales vigentes; no inventa categorías ausentes."""
    por_transporte: dict[str, list[dict[str, str]]] = {}
    for fila in filas:
        por_transporte.setdefault(fila["numero_transporte"], []).append(fila)

    mapeo = {
        "CONFLICTO_FECHA": "fecha",
        "CONFLICTO_CLIENTE": "cliente",
        "CONFLICTO_OBRA_DESTINO": "obra_destino",
        "CONFLICTO_CHOFER": "chofer",
        "CONFLICTO_RUT_CHOFER": "rut_chofer",
    }
    casos: list[tuple[str, ContextoRazonamiento, str]] = []
    for viaje in viajes:
        motivos = {m.strip() for m in viaje["motivos_revision"].split("|")}
        for motivo, campo in mapeo.items():
            if motivo not in motivos:
                continue
            relacionadas = por_transporte.get(viaje["numero_transporte"], [])
            valores = {
                fila[campo].strip() for fila in relacionadas
                if fila.get(campo, "").strip() not in ("", "No encontrado")
            }
            if len(valores) < 2:
                continue
            observada = relacionadas[0]
            evidencias = tuple(
                EvidenciaIA(
                    identificador=f"documento:{fila['numero_guia']}:{campo}",
                    campo=campo, valor=fila[campo].strip(), tipo_fuente="DOCUMENTAL",
                    nivel="DOCUMENTAL_DEBIL", independencia=0,
                    en_contra=(motivo,),
                    procedencia="dataset_operacional_vigente",
                    referencias_fuente=(
                        f"guia={fila['numero_guia']};transporte={fila['numero_transporte']}",
                    ),
                )
                for fila in relacionadas
                if fila.get(campo, "").strip() not in ("", "No encontrado")
            )
            contexto = ContextoRazonamiento(
                campo=campo, valor_documental=observada[campo].strip(),
                rut_chofer=observada["rut_chofer"].strip(),
                numero_guia=observada["numero_guia"].strip(),
                numero_transporte=viaje["numero_transporte"].strip(),
                evidencias=evidencias, resultado_motor="CONTRADICCION_DOCUMENTAL",
                explicacion_motor=f"Viaje en revisión por {motivo}; valores={sorted(valores)}",
                identidad_documento=observada["archivo"].strip(),
                identidad_operacional={"viaje_id": viaje["viaje_id"]},
                herramientas_disponibles=("DOCUMENTOS_RELACIONADOS",),
                restricciones_dominio=(
                    "No elegir entre documentos contradictorios sin evidencia superior.",
                    "La repetición dentro del mismo transporte no es evidencia independiente.",
                ),
            )
            casos.append((f"{viaje['numero_transporte']}:{campo}", contexto, motivo))
            if len(casos) >= 4:
                return casos
    return casos


def construir_muestra() -> tuple[list[tuple[str, ContextoRazonamiento, str]], object]:
    estado = json.loads(ESTADO_OPERACION.read_text(encoding="utf-8-sig"))
    ruta_viajes = RAIZ_ATLAS_DRIVE / estado["reporte_vigente"] / "viajes.csv"
    dataset, catalogo = _copiar_fuentes_reales_a_temporal()
    try:
        filas = _leer_csv(dataset)
        vehiculos = construir_casos_reales(dataset, catalogo)[:2]
        documentales = _contextos_documentales(filas, _leer_csv(ruta_viajes))
    finally:
        shutil.rmtree(dataset.parent, ignore_errors=True)
    casos = [
        (f"{caso_id}:{contexto.campo}", contexto, "REVISION_VEHICULO")
        for caso_id, contexto, _ground_truth in vehiculos
    ] + documentales
    return casos[:10], herramienta_documentos_relacionados(filas)


def main() -> int:
    casos, herramienta = construir_muestra()
    orquestador = OrquestadorAtlasIA(
        proveedor=ProveedorModeloIAGroq(modelo="openai/gpt-oss-120b"),
        herramientas={herramienta.nombre: herramienta},
    )
    resultados = []
    for caso_id, contexto, motivo in casos:
        resultado = orquestador.resolver(contexto)
        registro = {
            "caso_id": caso_id, "motivo_original": motivo,
            "resultado": resultado.a_dict(),
            "habria_evitado_intervencion_humana": resultado.clasificacion == "A_AUTONOMIA_CANDIDATA",
            "ground_truth_humano": None,
        }
        resultados.append(registro)
        print(f"{caso_id}: {resultado.estado} / {resultado.clasificacion}")

    salida = RUTA_RESULTADOS / "muestra_multicampo_b1_groq.json"
    salida.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generado_en": datetime.now(timezone.utc).isoformat(),
        "proveedor": "groq", "modelo": "openai/gpt-oss-120b",
        "modo": "READ_ONLY", "cantidad": len(resultados),
        "clasificaciones": dict(Counter(r["resultado"]["clasificacion"] for r in resultados)),
        "resultados": resultados,
    }
    salida.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Resultados guardados en {salida}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
