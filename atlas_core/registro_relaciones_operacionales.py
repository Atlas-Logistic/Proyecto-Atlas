"""Registro portable de relaciones guía--transporte--chofer--patentes.

No es un reporte ni un cache: vive en la raíz Atlas sincronizada, se actualiza
por unión idempotente y conserva la procedencia de cada observación.  La
migración histórica es una operación explícita; el lector operacional jamás
abre ``reportes/*/viajes.csv``.
"""
from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping

from atlas_core.almacenamiento_portable import escribir_json_atomico

VERSION = 1
EMPRESA_LEGADA = "oficina"
CAMPOS = ("numero_guia", "numero_transporte", "rut_chofer", "patente_tracto", "patente_rampla")


def ruta_registro(raiz: str | Path) -> Path:
    """Archivo privado, portable y respaldable por Drive; no es la única copia."""
    return Path(raiz) / "catalogos_privados" / "registro_relaciones_operacionales.json"


def _vacio() -> dict[str, object]:
    return {"version": VERSION, "empresas": {}}


def _cargar(raiz: str | Path) -> dict[str, object]:
    try:
        valor = json.loads(ruta_registro(raiz).read_text(encoding="utf-8"))
        if not isinstance(valor, dict) or valor.get("version") != VERSION or not isinstance(valor.get("empresas"), dict):
            return _vacio()
        return valor
    except (OSError, json.JSONDecodeError):
        return _vacio()


def _clave(relacion: Mapping[str, object]) -> str:
    return "\x1f".join(str(relacion.get(c, "")).strip() for c in CAMPOS)


def _normalizar(fila: Mapping[str, object]) -> dict[str, str] | None:
    valor = {c: str(fila.get(c, "")).strip() for c in CAMPOS}
    # Mismo contrato del lector histórico: no inventa una asociación sin guía y RUT.
    return valor if valor["numero_guia"] and valor["rut_chofer"] else None


def leer_relaciones(raiz: str | Path, *, empresa_id: str = EMPRESA_LEGADA) -> list[dict[str, object]]:
    """Consulta operacional: sólo el registro; cero acceso a reportes."""
    empresa = _cargar(raiz).get("empresas", {}).get(empresa_id, {})
    relaciones = empresa.get("relaciones", []) if isinstance(empresa, dict) else []
    return [dict(r.get("relacion", {})) for r in relaciones if isinstance(r, dict) and isinstance(r.get("relacion"), dict)]


def incorporar_relaciones(
    raiz: str | Path, relaciones: Iterable[Mapping[str, object]], *, empresa_id: str = EMPRESA_LEGADA,
    procedencia: Mapping[str, object],
) -> dict[str, int]:
    """Unión idempotente. Nunca cambia una confirmación ni borra conflictos."""
    registro = _cargar(raiz)
    empresas = registro["empresas"]
    empresa = empresas.setdefault(empresa_id, {"relaciones": []})
    existentes = {str(r.get("clave", "")): r for r in empresa["relaciones"] if isinstance(r, dict)}
    agregadas = 0
    fuentes_agregadas = 0
    ahora = datetime.now(timezone.utc).isoformat()
    for cruda in relaciones:
        relacion = _normalizar(cruda)
        if relacion is None:
            continue
        clave = _clave(relacion)
        entrada = existentes.get(clave)
        fuente = dict(procedencia)
        fuente["observado_en"] = fuente.get("observado_en", ahora)
        if entrada is None:
            entrada = {"clave": clave, "relacion": relacion, "fuentes": [], "confirmaciones_humanas": [], "conflictos": []}
            # Valores documentales discrepantes se conservan, nunca se elige
            # uno ni se convierte evidencia en confirmación humana.
            base = tuple(relacion[c] for c in CAMPOS[:3])
            for otra in empresa["relaciones"]:
                if not isinstance(otra, dict) or not isinstance(otra.get("relacion"), dict):
                    continue
                otra_relacion = otra["relacion"]
                if tuple(str(otra_relacion.get(c, "")) for c in CAMPOS[:3]) == base and otra_relacion != relacion:
                    conflicto = {"tipo": "RELACION_DOCUMENTAL_DISCREPANTE", "con": str(otra.get("clave", ""))}
                    if conflicto not in entrada["conflictos"]:
                        entrada["conflictos"].append(conflicto)
                    reciproco = {"tipo": "RELACION_DOCUMENTAL_DISCREPANTE", "con": clave}
                    if reciproco not in otra.setdefault("conflictos", []):
                        otra["conflictos"].append(reciproco)
            empresa["relaciones"].append(entrada)
            existentes[clave] = entrada
            agregadas += 1
        fuentes = entrada.setdefault("fuentes", [])
        firma_fuente = json.dumps(fuente, ensure_ascii=False, sort_keys=True)
        if all(json.dumps(x, ensure_ascii=False, sort_keys=True) != firma_fuente for x in fuentes if isinstance(x, dict)):
            fuentes.append(fuente)
            fuentes_agregadas += 1
    escribir_json_atomico(ruta_registro(raiz), registro)
    return {"relaciones_agregadas": agregadas, "fuentes_agregadas": fuentes_agregadas, "total": len(empresa["relaciones"])}


def incorporar_dataset(raiz: str | Path, dataset: str | Path, *, empresa_id: str = EMPRESA_LEGADA) -> dict[str, int]:
    """Actualización incremental desde la fuente operacional, no desde reportes."""
    ruta = Path(dataset)
    try:
        with ruta.open("r", newline="", encoding="utf-8-sig") as archivo:
            filas = list(csv.DictReader(archivo, delimiter=";"))
    except (OSError, UnicodeDecodeError, csv.Error):
        return {"relaciones_agregadas": 0, "fuentes_agregadas": 0, "total": 0}
    huella = hashlib.sha256(ruta.read_bytes()).hexdigest() if ruta.is_file() else ""
    return incorporar_relaciones(raiz, filas, empresa_id=empresa_id, procedencia={
        "tipo": "dataset_operacional", "dataset": str(ruta.relative_to(Path(raiz))) if ruta.is_relative_to(Path(raiz)) else ruta.name,
        "sha256": huella,
    })


def extraer_reporte_historico(ruta: str | Path) -> list[dict[str, str]] | None:
    """Adaptador de migración explícita. No se importa desde el consumidor."""
    try:
        with Path(ruta).open("r", newline="", encoding="utf-8-sig") as archivo:
            salida: list[dict[str, str]] = []
            for viaje in csv.DictReader(archivo, delimiter=";"):
                try:
                    evidencias = json.loads(str(viaje.get("evidencias_documentos", "") or "[]"))
                except (json.JSONDecodeError, TypeError):
                    evidencias = []
                for evidencia in evidencias if isinstance(evidencias, list) else []:
                    if isinstance(evidencia, dict):
                        normalizada = _normalizar(evidencia)
                        if normalizada:
                            salida.append(normalizada)
            return salida
    except (OSError, UnicodeDecodeError, csv.Error):
        return None


def migrar_reportes_historicos(raiz: str | Path, *, empresa_id: str = EMPRESA_LEGADA, aplicar: bool = False) -> dict[str, object]:
    """Simula por defecto; aplicar=True es idempotente y conserva cada fuente."""
    base = Path(raiz)
    relaciones: list[dict[str, str]] = []
    fuentes: list[dict[str, object]] = []
    ilegibles: list[str] = []
    for ruta in sorted((base / "reportes").glob("*/viajes.csv")):
        extraidas = extraer_reporte_historico(ruta)
        relativa = str(ruta.relative_to(base))
        if extraidas is None:
            ilegibles.append(relativa)
            continue
        relaciones.extend(extraidas)
        fuentes.append({"ruta": relativa, "sha256": hashlib.sha256(ruta.read_bytes()).hexdigest(), "cantidad": len(extraidas)})
    unicas = {_clave(r): r for r in relaciones}
    resultado: dict[str, object] = {"modo": "aplicar" if aplicar else "simulacion", "reportes": len(fuentes), "relaciones_extraidas": len(unicas), "ilegibles": ilegibles, "fuentes": fuentes}
    if aplicar and not ilegibles:
        total_agregadas = total_fuentes = 0
        for fuente in fuentes:
            ruta = base / str(fuente["ruta"])
            cambio = incorporar_relaciones(base, extraer_reporte_historico(ruta) or [], empresa_id=empresa_id, procedencia={"tipo": "reporte_historico_migrado", "ruta": fuente["ruta"], "sha256": fuente["sha256"]})
            total_agregadas += cambio["relaciones_agregadas"]; total_fuentes += cambio["fuentes_agregadas"]
        resultado.update({"relaciones_agregadas": total_agregadas, "fuentes_agregadas": total_fuentes, "relaciones_registradas": len(leer_relaciones(base, empresa_id=empresa_id))})
    return resultado
