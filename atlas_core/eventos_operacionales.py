"""Bloque UNIVERSAL V1 -- adaptador READ-ONLY del dominio EVENTOS sobre
la fuente real existente (envíos Mobile, `atlas_core.mobile.
RepositorioEnviosMobile`). Un evento operacional (estadía, espera
autorización, devolución total/parcial, doble vuelta -- y cualquier
tipo futuro, nunca una lista cerrada) es, hoy, un envío Mobile con
`tipo_novedad` no vacío. Este módulo sólo hace UNA cosa: unir cada
envío con el viaje real al que corresponde (vía `numero_transporte`,
la misma clave que ya usa `mobile.asociar_documento`) para poder
responder "¿cuántas estadías tuvo Retamal?" sin que Pregúntale a Atlas
tenga que conocer nada de la mecánica interna de Mobile -- Sección 13
del ticket: "fachada universal de consulta sobre datos existentes",
nunca una base de datos nueva.

Nunca escribe nada: ni al envío, ni al dataset, ni a ningún catálogo."""

from __future__ import annotations

from typing import Iterable, Mapping


def _numero_transporte_de(envio: Mapping[str, object]) -> str:
    resultado_asociacion = envio.get("resultado_asociacion") or {}
    if isinstance(resultado_asociacion, Mapping):
        nt = str(resultado_asociacion.get("numero_transporte", "")).strip()
        if nt:
            return nt
    datos_ocr = envio.get("datos_ocr") or {}
    if isinstance(datos_ocr, Mapping):
        return str(datos_ocr.get("numero_transporte", "")).strip()
    return ""


def _numero_guia_de(envio: Mapping[str, object]) -> str:
    resultado_asociacion = envio.get("resultado_asociacion") or {}
    if isinstance(resultado_asociacion, Mapping):
        guia = str(resultado_asociacion.get("numero_guia", "")).strip()
        if guia:
            return guia
    datos_ocr = envio.get("datos_ocr") or {}
    if isinstance(datos_ocr, Mapping):
        return str(datos_ocr.get("numero_guia", "")).strip()
    return ""


def construir_eventos_operacionales(
    envios: Iterable[Mapping[str, object]], viajes: Iterable[Mapping[str, str]],
) -> list[dict[str, str]]:
    """Bloque 9/13 -- un evento por cada envío con `tipo_novedad`
    real (nunca infiere eventos de otra forma). `chofer`/`cliente`/
    `obra`/`fecha` vienen SIEMPRE del viaje real asociado (join por
    `numero_transporte`) -- nunca del `chofer_id` opaco de Mobile, que
    no es un nombre canónico -- si el envío todavía no está asociado a
    ningún viaje, esos campos quedan vacíos (el evento SIGUE contando,
    sólo no puede agruparse/filtrarse por esos campos todavía)."""
    indice_viajes: dict[str, Mapping[str, str]] = {}
    for viaje in viajes:
        nt = str(viaje.get("numero_transporte", "")).strip()
        if nt:
            indice_viajes[nt] = viaje

    eventos: list[dict[str, str]] = []
    for envio in envios:
        # Bloque MOBILE CONTRATO V2 -- una guía firmada (EVIDENCIA_FIRMADA)
        # es evidencia, nunca un evento; un envío puede traer VARIAS
        # incidencias (`tipos_novedad`) -- cada una con identidad propia.
        if str(envio.get("rol_documento") or "GUIA") == "EVIDENCIA_FIRMADA":
            continue
        tipos = envio.get("tipos_novedad")
        if isinstance(tipos, list):
            tipos = [str(t).strip() for t in tipos if str(t).strip()]
        else:
            legado = str(envio.get("tipo_novedad", "")).strip()
            tipos = [legado] if legado else []
        numero_transporte = _numero_transporte_de(envio)
        viaje = indice_viajes.get(numero_transporte)
        for tipo in tipos:
            eventos.append(_evento_de_envio(envio, tipo, varios=len(tipos) > 1, numero_transporte=numero_transporte, viaje=viaje))
    return eventos


def _evento_de_envio(
    envio: Mapping[str, object], tipo: str, *, varios: bool,
    numero_transporte: str, viaje: Mapping[str, str] | None,
) -> dict[str, str]:
    """Un envío con una sola incidencia conserva `evento_id = envio_id`
    (igual que v1); con varias, cada una es `<envio_id>:<tipo>`."""
    envio_id = str(envio.get("envio_id", ""))
    return {
        "evento_id": f"{envio_id}:{tipo}" if varios else envio_id,
        "tipo_evento": tipo,
        "numero_transporte": numero_transporte,
        "numero_guia": _numero_guia_de(envio),
        "chofer": str(viaje.get("choferes", "")).strip() if viaje else "",
        "cliente": str(viaje.get("clientes", "")).strip() if viaje else "",
        "obra": str(viaje.get("obras_destino", "")).strip() if viaje else "",
        "fecha": str(viaje.get("fecha", "")).strip() if viaje else "",
        "recibido_en": str(envio.get("recibido_en", "")).strip(),
    }
