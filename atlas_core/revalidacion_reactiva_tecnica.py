"""Disparador focal posterior a cambios de conocimiento geográfico."""
from __future__ import annotations

import json
from pathlib import Path

from atlas_core.catalogo_destinos import Destino, normalizar_nombre_destino
from atlas_core.catalogo_obras_destinos import normalizar_nombre_obra


def revalidar_tras_cambio_catalogo(
    ruta_catalogo: str | Path, *, destino: Destino | None = None,
    obra_id: str = "",
) -> dict[str, object]:
    """Revalida sólo pendientes vinculables al destino/obra modificado.

    Se llama *después* de soltar el lock de catálogo. Una decisión humana
    en curso ya posee su propio plan de impacto; se deja a ese plan y a la
    tarea periódica cualquier reintento que no sea seguro aquí. Nunca
    falla hacia el llamador: el catálogo ya quedó escrito, y la huella de
    conocimiento persistida garantiza que la tarea periódica lo retome.
    """
    try:
        return _revalidar_tras_cambio_catalogo(ruta_catalogo, destino=destino, obra_id=obra_id)
    except Exception as error:  # noqa: BLE001 -- el guardado del catálogo ya ocurrió
        return {"ejecutado": False, "motivo": "ERROR_REVALIDACION_REACTIVA",
                "error": f"{type(error).__name__}: {error}"}


def _revalidar_tras_cambio_catalogo(
    ruta_catalogo: str | Path, *, destino: Destino | None, obra_id: str,
) -> dict[str, object]:
    ruta = Path(ruta_catalogo)
    if ruta.parent.name != "catalogos_privados":
        return {"ejecutado": False, "motivo": "CATALOGO_NO_OPERACIONAL"}
    raiz = ruta.parent.parent
    actual = raiz / "operacion" / "actual"
    if not (actual / "analisis_completo_guias.csv").is_file():
        return {"ejecutado": False, "motivo": "SIN_DATASET"}
    if (actual / ".atlas_lock_aplicar_decision_obra").exists():
        return {"ejecutado": False, "motivo": "DECISION_EN_CURSO"}

    from atlas_core.reconciliacion_estado_derivado import _pendientes_ruta, NOMBRE_ARTEFACTO
    from atlas_core.mantenimiento_pendientes_tecnicos import mantener_pendientes_tecnicos

    nombres_obra: set[str] = set()
    if destino is not None or obra_id:
        try:
            contenido = json.loads((ruta.parent / "obras_destinos.json").read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            contenido = {}
        relaciones = contenido.get("relaciones", [])
        ids_obras = {obra_id} if obra_id else set()
        if destino is not None:
            ids_obras.update(r.get("obra_id") for r in relaciones
                             if isinstance(r, dict) and r.get("destino_id") == destino.destino_id)
        for obra in contenido.get("obras", []):
            if isinstance(obra, dict) and obra.get("obra_id") in ids_obras:
                nombres_obra.update(
                    normalizar_nombre_obra(str(v)) for v in
                    (obra.get("nombre_canonico", ""), *obra.get("aliases_documentales", [])) if v
                )
    claves_direccion = set()
    if destino is not None:
        claves_direccion = {
            normalizar_nombre_destino(v) for v in (destino.direccion, *destino.aliases) if v
        }
    afectadas = {
        str(fila.get("numero_guia", "")).strip()
        for fila in _pendientes_ruta(actual / "analisis_completo_guias.csv", actual / NOMBRE_ARTEFACTO)
        if (normalizar_nombre_destino(str(fila.get("despachar_a_crudo", ""))) in claves_direccion
            or normalizar_nombre_obra(str(fila.get("obra_destino", ""))) in nombres_obra)
    }
    afectadas.discard("")
    if not afectadas:
        return {"ejecutado": False, "motivo": "SIN_GUIAS_AFECTADAS"}
    return mantener_pendientes_tecnicos(
        raiz_atlas=raiz, solo_cambios=True, guias_forzadas=afectadas,
    )
