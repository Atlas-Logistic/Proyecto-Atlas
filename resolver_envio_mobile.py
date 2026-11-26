"""Confirma manualmente la asociación de un envío Mobile pendiente.

Casos reales 492295 / 492263 (26/11/2026): la asociación sólo marcaba el
envío como ASOCIADO_MANUALMENTE; el documento de la guía seguía con
transporte «No encontrado» y quedaba fuera del viaje elegido. Si el envío ya
tiene documento en el dataset, el transporte se corrige ANTES por la capa
oficial (DOCUMENTO_CORREGIR_CAMPO: preview, confirmación humana, ledger y
reconciliación). Sin documento (lectura fallida, nunca promovida) se
conserva la asociación de antes, que no crea documentos."""

from __future__ import annotations

import argparse
import csv
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from atlas_core.almacenamiento_portable import bloqueo_sesion, leer_estado_operacion, resolver_raiz_atlas
from atlas_core.mobile import (
    TIEMPO_EXPIRACION_LOCK_ENVIO_SEGUNDOS, RepositorioEnviosMobile, registrar_eventos_canonicos_mobile,
    reintentar_evidencias_firmadas_pendientes,
)

CONFIRMANTE_DESKTOP = "JAVIER_DESKTOP"
_TRANSPORTE_VALIDO = re.compile(r"\d{10}")


def _leer_filas(dataset: Path) -> list[dict[str, str]]:
    csv.field_size_limit(max(csv.field_size_limit(), 100_000_000))
    with dataset.open(encoding="utf-8-sig", newline="") as archivo:
        return list(csv.DictReader(archivo, delimiter=";"))


def _archivo_documento(envio_id: str, registro: dict) -> str:
    return str(registro.get("archivo_dataset") or f"mobile/{envio_id}/original.jpg")


def _incorporar_documento(raiz: Path, fila: dict[str, str], numero_transporte: str, *, envio_id: str,
                          capa=None) -> dict | None:
    """Lleva el documento del envío al transporte elegido por el canal oficial."""
    actual = (fila.get("numero_transporte") or "").strip()
    if actual == numero_transporte:
        return None
    if _TRANSPORTE_VALIDO.fullmatch(actual):
        # Nunca se mueve en silencio una guía que ya pertenece a otro viaje.
        raise ValueError(f"La guía {fila.get('numero_guia')} ya pertenece al transporte {actual}; "
                         "corríjalo con B1 si corresponde.")
    if capa is None:
        from atlas_core.acciones_operacionales import CapaAccionesOperacionales
        capa = CapaAccionesOperacionales(raiz)
    parametros = {"numero_guia": str(fila.get("numero_guia") or ""), "campo": "NUMERO_TRANSPORTE",
                  "valor": numero_transporte, "archivo": str(fila.get("archivo") or "")}
    referencia = f"Envíos Mobile: asociación manual del envío {envio_id} al transporte {numero_transporte}"
    preview = capa.previsualizar("DOCUMENTO_CORREGIR_CAMPO", parametros, actor=CONFIRMANTE_DESKTOP,
                                 referencia=referencia)
    if preview.get("estado") == "RECHAZADA":
        raise ValueError(preview.get("mensaje") or "No se pudo preparar la corrección del transporte.")
    if not preview.get("token"):
        return None
    resultado = capa.ejecutar(preview["token"], actor=CONFIRMANTE_DESKTOP, confirmado_por=CONFIRMANTE_DESKTOP,
                              accion_esperada="DOCUMENTO_CORREGIR_CAMPO")
    if resultado.get("estado") in ("RECHAZADA", "FALLIDA"):
        raise ValueError(resultado.get("mensaje") or "No se pudo corregir el transporte del documento.")
    return {"auditoria_id": resultado.get("auditoria_id"), "antes": actual, "despues": numero_transporte}


def resolver(raiz: Path, envio_id: str, numero_transporte: str, *, capa=None) -> dict:
    repo = RepositorioEnviosMobile(raiz)
    estado = leer_estado_operacion(raiz=raiz) or {}
    dataset = raiz / estado.get("dataset_operacional", "operacion/actual/analisis_completo_guias.csv")
    filas = _leer_filas(dataset)
    if numero_transporte not in {fila.get("numero_transporte", "") for fila in filas}:
        raise ValueError("El transporte indicado no existe en la operación vigente.")
    registro = repo.cargar(envio_id)
    if registro.get("estado") != "REQUIERE_REVISION":
        raise ValueError("El envío ya no está pendiente de revisión.")
    archivo = _archivo_documento(envio_id, registro)
    fila = next((f for f in filas if f.get("archivo") == archivo), None)
    # Primero el documento: si la corrección oficial se rechaza, el envío
    # sigue pendiente de revisión y nada queda a medias.
    correccion = _incorporar_documento(raiz, fila, numero_transporte, envio_id=envio_id, capa=capa) if fila else None
    # Bloque CONSISTENCIA OPERACIONAL -- lock por envío: esta confirmación
    # manual compite por el MISMO envio.json que `procesar_envio_mobile`/
    # un reproceso podrían estar tocando concurrentemente. Se relee fresco
    # DENTRO del lock -- nunca se decide sobre una copia obsoleta.
    with bloqueo_sesion(
        repo.raiz, f"mobile_{envio_id}", tiempo_expiracion_segundos=TIEMPO_EXPIRACION_LOCK_ENVIO_SEGUNDOS,
    ):
        registro = repo.cargar(envio_id)
        if registro.get("estado") != "REQUIERE_REVISION":
            raise ValueError("El envío ya no está pendiente de revisión.")
        registro["estado"] = "ASOCIADO"
        registro["resultado_asociacion"] = {
            "estado": "ASOCIADO_MANUALMENTE", "numero_transporte": numero_transporte,
            "numero_guia": str((registro.get("datos_ocr") or {}).get("numero_guia", "")),
            "candidatos": (registro.get("resultado_asociacion") or {}).get("candidatos", []),
            "motivo": "Confirmado por supervisor en Atlas Desktop.",
            "documento_incorporado": bool(fila),
        }
        if correccion:
            registro["resultado_asociacion"]["correccion_documental"] = correccion
        registro["asociado_manualmente_en"] = datetime.now(timezone.utc).isoformat()
        repo.guardar(envio_id, registro)
    # Bloque MOBILE CONTRATO V2 -- ya asociada a un viaje: sus incidencias
    # pasan al registro canónico y se reintentan las guías firmadas que
    # esperaban esta guía. Best-effort: nunca revierte la confirmación.
    try:
        registrar_eventos_canonicos_mobile(repo)
        reintentar_evidencias_firmadas_pendientes(repo, dataset=dataset)
    except Exception:
        pass
    return {"ok": True, "envio_id": envio_id, "numero_transporte": numero_transporte,
            "documento_incorporado": bool(fila), "correccion_documental": correccion}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raiz-atlas", type=Path, required=True)
    parser.add_argument("--envio-id", required=True)
    parser.add_argument("--numero-transporte", required=True)
    args = parser.parse_args()
    print(json.dumps(resolver(resolver_raiz_atlas(args.raiz_atlas), args.envio_id, args.numero_transporte)))


if __name__ == "__main__":
    main()
