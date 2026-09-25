"""Elegibilidad focal de pendientes de ruta a partir de evidencia persistida.

No consulta proveedores ni modifica la operación. Las huellas se calculan por
guía: una edición de otro destino no despierta pendientes ajenos.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Mapping

from atlas_core.catalogo_destinos import normalizar_nombre_destino
from atlas_core.catalogo_obras_destinos import normalizar_nombre_obra
from atlas_core.decisiones_pendientes import clasificar_fallo_tecnico
from atlas_core.capacidades_reevaluacion import dominios_de_motivo_tecnico

INTERVALO_MAXIMO = timedelta(minutes=30)
LIMITES = {"AGOTABLE": 3, "TRANSITORIO": 5, "DETERMINISTA": 0}


_CACHE_JSON: dict[str, tuple[tuple[int, int], dict]] = {}


def _leer_json(ruta: Path) -> dict:
    """Lectura memoizada por (mtime, tamaño): la huella se calcula por guía
    y no debe releer los catálogos una vez por cada pendiente."""
    try:
        info = ruta.stat()
        firma = (info.st_mtime_ns, info.st_size)
        previo = _CACHE_JSON.get(str(ruta))
        if previo is not None and previo[0] == firma:
            return previo[1]
        valor = json.loads(ruta.read_text(encoding="utf-8-sig"))
        valor = valor if isinstance(valor, dict) else {}
    except (OSError, ValueError):
        return {}
    _CACHE_JSON[str(ruta)] = (firma, valor)
    return valor


def conocimiento_para_guia(
    fila: Mapping[str, str], *, catalogos: Path, decisiones_aplicadas: Path,
    version_reglas: int, versiones_capacidades: Mapping[str, int],
) -> str:
    """Huella de la identidad de destino y de las decisiones de esta guía."""
    destino_texto = normalizar_nombre_destino(str(fila.get("despachar_a_crudo", "")))
    obra_texto = normalizar_nombre_obra(str(fila.get("obra_destino", "")))
    guia = str(fila.get("numero_guia", "")).strip()
    catalogo_destinos = _leer_json(catalogos / "destinos_maestros.json")
    catalogo_obras = _leer_json(catalogos / "obras_destinos.json")
    ledger = _leer_json(decisiones_aplicadas)
    obras = [o for o in catalogo_obras.get("obras", []) if isinstance(o, dict)
             and obra_texto and obra_texto in {
                 normalizar_nombre_obra(str(v)) for v in (
                     o.get("nombre_canonico", ""), o.get("nombre_normalizado", ""),
                     *o.get("aliases_documentales", []),
                 ) if v
             }]
    ids_obras = {o.get("obra_id") for o in obras}
    relaciones = [r for r in catalogo_obras.get("relaciones", []) if isinstance(r, dict)
                  and r.get("obra_id") in ids_obras]
    ids_destinos = {r.get("destino_id") for r in relaciones}
    destinos = [d for d in catalogo_destinos.get("destinos", []) if isinstance(d, dict)
                and (d.get("destino_id") in ids_destinos or (
                    destino_texto and destino_texto in {
                        normalizar_nombre_destino(str(v)) for v in
                        (d.get("direccion", ""), *d.get("aliases", [])) if v
                    }
                ))]
    decisiones = [d for d in ledger.get("aplicaciones", []) if isinstance(d, dict)
                  and str((d.get("documento") or {}).get("numero_guia", "")).strip() == guia]
    contenido = {
        "obras": obras, "relaciones": relaciones, "destinos": destinos,
        "decisiones": decisiones,
        "evidencia_b1": str(fila.get("resultado_atlas_ia_json", "")),
        "version_reglas": version_reglas,
        "versiones_capacidades": {
            k: versiones_capacidades[k]
            for k in sorted(dominios_de_motivo_tecnico(str(fila.get("motivo_ruta", ""))))
            if k in versiones_capacidades
        },
    }
    serial = json.dumps(contenido, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(serial.encode("utf-8")).hexdigest()


def elegibilidad(
    registro: Mapping[str, object], *, huella_actual: str, instante: datetime,
) -> tuple[bool, str]:
    """Devuelve (elegible, causa). La primera lectura legacy no inventa cambio."""
    anterior = registro.get("huella_conocimiento")
    if anterior and anterior != huella_actual:
        return True, "CONOCIMIENTO_CAMBIO"
    clase = clasificar_fallo_tecnico(str(registro.get("motivo_actual", "")))
    intentos = int(registro.get("intentos_misma_evidencia", 0) or 0)
    if clase == "DETERMINISTA":
        return False, "SIN_CAMBIO"
    if intentos >= LIMITES[clase]:
        return False, "AGOTADO"
    ultimo = registro.get("ultimo_intento")
    if not ultimo:
        return True, "PRIMERA_OPORTUNIDAD"
    try:
        vencido = instante - datetime.fromisoformat(str(ultimo)) >= INTERVALO_MAXIMO
    except ValueError:
        vencido = True
    return (vencido, "COOLDOWN_VENCIDO" if vencido else "ESPERANDO_COOLDOWN")
