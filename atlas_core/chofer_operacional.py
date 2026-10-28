"""Chofer OPERACIONAL de una guía fijado por un humano (B1 / Revisión).

El dataset documental (`analisis_completo_guias.csv`) conserva siempre lo
leído: `chofer`, `rut_chofer` impreso, OCR, fotografía. La corrección vive
SÓLO en el ledger auditado `decisiones_aplicadas.json` (tipo
`CHOFER_OPERACIONAL_DOCUMENTO`, append-only, última por documento gana) y se
aplica como VALOR OPERACIONAL al generar el reporte de viajes -- mismo patrón
que las patentes confirmadas (`resolver_patentes_confirmadas_por_ledger`).

Una relectura OCR, el PULL o una revalidación reescriben el dataset, nunca
este ledger: la corrección persiste y estas funciones vuelven a retirar la
tarjeta de chofer y los motivos de identidad de ESE documento. Nunca toca
otras guías del mismo transporte ni asignaciones chofer-vehículo.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, Mapping

TIPO_LEDGER_CHOFER_OPERACIONAL = "CHOFER_OPERACIONAL_DOCUMENTO"
# Motivos que sólo expresan "identidad de chofer no resuelta"; una
# corrección humana los resuelve para ESE documento.
MOTIVOS_IDENTIDAD_CHOFER = frozenset({"CHOFER_SIN_CORROBORAR", "CHOFER_AUSENTE", "RUT_CHOFER_INVALIDO"})
TIPOS_DECISION_CHOFER = frozenset({"CHOFER_DESCONOCIDO", "CHOFER_CANDIDATO"})
_SEPARADOR_MOTIVOS = " | "


def indice_choferes_operacionales(ledger: Mapping[str, object]) -> dict[str, dict[str, str]]:
    """``archivo`` -> corrección vigente (la última aplicada) con
    ``nombre``, ``rut``, ``chofer_id``, ``numero_guia``, ``numero_transporte``.
    Entradas incompletas se ignoran; nunca lanza."""
    indice: dict[str, dict[str, str]] = {}
    aplicaciones = ledger.get("aplicaciones") if isinstance(ledger, Mapping) else None
    for aplicacion in aplicaciones if isinstance(aplicaciones, list) else []:
        if not isinstance(aplicacion, Mapping) or aplicacion.get("tipo") != TIPO_LEDGER_CHOFER_OPERACIONAL:
            continue
        documento = aplicacion.get("documento") or {}
        chofer = aplicacion.get("chofer_operacional") or {}
        if not isinstance(documento, Mapping) or not isinstance(chofer, Mapping):
            continue
        archivo = str(documento.get("archivo", "")).strip()
        nombre, rut = str(chofer.get("nombre", "")).strip(), str(chofer.get("rut", "")).strip()
        if not archivo or not nombre or not rut:
            continue
        indice[archivo] = {
            "nombre": nombre, "rut": rut, "chofer_id": str(aplicacion.get("chofer_id", "")).strip(),
            "numero_guia": str(documento.get("numero_guia", "")).strip(),
            "numero_transporte": str(documento.get("numero_transporte", "")).strip(),
            "decision_id": str(aplicacion.get("decision_id", "")),
        }
    return indice


def choferes_operacionales_por_ledger(ruta_ledger: str | Path) -> dict[str, dict[str, str]]:
    """Ver `indice_choferes_operacionales`. Ausencia/corrupción = sin correcciones."""
    try:
        ledger = json.loads(Path(ruta_ledger).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}
    return indice_choferes_operacionales(ledger)


def correccion_de_documento(indice: Mapping[str, Mapping[str, str]],
                            documento: Mapping[str, object]) -> Mapping[str, str] | None:
    """Corrección aplicable a un documento: por ``archivo`` exacto, o -- para
    tarjetas antiguas que sólo traen "original.jpg" -- por guía Y transporte
    exactos de la corrección registrada."""
    archivo = str(documento.get("archivo", "")).strip()
    if archivo in indice:
        return indice[archivo]
    guia = str(documento.get("numero_guia", "")).strip()
    transporte = str(documento.get("numero_transporte", "")).strip()
    if not guia or not transporte:
        return None
    return next((c for c in indice.values()
                 if c["numero_guia"] == guia and c["numero_transporte"] == transporte), None)


def retirar_decisiones_chofer_operacional(
    decisiones: Iterable[Mapping[str, object]], *, ruta_ledger: str | Path,
) -> list[Mapping[str, object]]:
    """Quita las tarjetas de chofer de los documentos con chofer operacional
    ya fijado por un humano. Las demás tarjetas quedan intactas."""
    decisiones = list(decisiones)
    if not any(d.get("tipo") in TIPOS_DECISION_CHOFER for d in decisiones):
        return decisiones
    indice = choferes_operacionales_por_ledger(ruta_ledger)
    if not indice:
        return decisiones
    return [d for d in decisiones
            if not (d.get("tipo") in TIPOS_DECISION_CHOFER
                    and correccion_de_documento(indice, d.get("documento") or {}) is not None)]


def revalidar_motivos_choferes_operacionales_sin_ocr(*, ruta_dataset: str | Path) -> dict[str, object]:
    """Pase del ciclo del PULL: una relectura que vuelve a traer un motivo de
    identidad de chofer a un documento con chofer operacional fijado lo
    pierde otra vez. Sólo esas filas; nunca `chofer`/`rut_chofer`."""
    from atlas_core.almacenamiento_portable import bloqueo_sesion
    from atlas_core.revalidacion_documental import _escribir_filas_completas, _leer_filas

    ruta = Path(ruta_dataset)
    operacionales = choferes_operacionales_por_ledger(ruta.parent / "decisiones_aplicadas.json")
    if not operacionales:
        return {"guias_actualizadas": []}
    with bloqueo_sesion(ruta.parent, "revalidacion_dataset"):
        try:
            filas = _leer_filas(ruta)
        except (OSError, ValueError):
            return {"guias_actualizadas": []}
        actualizadas = [str(f.get("numero_guia", "")) for f in filas
                        if str(f.get("archivo", "")).strip() in operacionales and retirar_motivos_identidad_chofer(f)]
        if actualizadas:
            _escribir_filas_completas(ruta, filas)
    return {"guias_actualizadas": actualizadas}


def retirar_motivos_identidad_chofer(fila: dict[str, str]) -> bool:
    """Retira de la fila los motivos de identidad de chofer y recalcula sus
    estados con la misma regla del revalidador de chofer. Nunca toca
    `chofer`, `rut_chofer` ni otro dato documental. True si cambió algo."""
    from atlas_core.procesamiento_masivo import MOTIVOS_NO_BLOQUEANTES

    motivos = [m.strip() for m in str(fila.get("motivos_revision_documento", "")).split("|") if m.strip()]
    vigentes = [m for m in motivos if m not in MOTIVOS_IDENTIDAD_CHOFER]
    if vigentes == motivos:
        return False
    fila["motivos_revision_documento"] = _SEPARADOR_MOTIVOS.join(vigentes)
    fila["indicador_revision"] = "REVISAR" if any(m not in MOTIVOS_NO_BLOQUEANTES for m in vigentes) else "OK"
    fila["estado_documental"] = "REQUIERE_REVISION" if fila["indicador_revision"] == "REVISAR" else "OK"
    fila["estado_operacional"] = (
        "REQUIERE_REVISION"
        if fila["estado_documental"] == "REQUIERE_REVISION"
        or str(fila.get("estado_ruta", "")).strip() != "RUTA_CALCULADA"
        else "OK"
    )
    return True
