"""Destino operacional confirmado por un humano para UNA guía.

El ledger (`decisiones_aplicadas.json`, tipo DESTINO_OPERACIONAL_DOCUMENTO)
es la fuente de verdad: el CSV documental, el OCR y la fotografía no se
modifican. La identidad es exacta (archivo + número de guía), nunca el
transporte, así que las guías hermanas no heredan la corrección.

La proyección invalida todo lo derivado del destino anterior (ruta,
coordenadas, códigos territoriales). Sólo una ruta calculada al confirmar,
para ESA dirección y comuna, vuelve a publicarse.
"""
from __future__ import annotations
from typing import Mapping

TIPO = "DESTINO_OPERACIONAL_DOCUMENTO"
DERIVADOS = ("latitud_entrega", "longitud_entrega", "distancia_km", "duracion_min",
             "proveedor_ruta", "estado_ruta", "motivo_ruta", "region_entrega", "estado_entrega",
             "codigo_pais", "codigo_unidad", "codigo_contexto")
# Campos que una ruta recalculada para el destino confirmado puede publicar.
CAMPOS_RUTA = ("latitud_entrega", "longitud_entrega", "distancia_km", "duracion_min", "proveedor_ruta",
               "estado_ruta", "region_entrega", "codigo_pais", "codigo_unidad", "codigo_contexto")
RUTA_CALCULADA = "RUTA_CALCULADA"
# Tarjetas que preguntan por el destino de un documento: la decisión humana
# las responde. Las demás revisiones de la misma guía siguen vigentes.
TIPOS_TARJETA_DESTINO = frozenset({"DESTINO_NO_RESUELTO", "DESTINO_SIN_CONFIRMAR"})


def _identidad(documento: Mapping[str, object]) -> tuple[str, str]:
    return str(documento.get("archivo") or "").strip(), str(documento.get("numero_guia") or "").strip()


def ruta_valida(ruta: object, comuna: str) -> bool:
    return (isinstance(ruta, Mapping) and ruta.get("estado_ruta") == RUTA_CALCULADA
            and bool(str(ruta.get("distancia_km") or "").strip())
            and str(ruta.get("comuna") or "").strip() == comuna)


def proyectar_destino(fila: Mapping[str, object], ledger: Mapping[str, object]) -> dict:
    """Devuelve copia; exige archivo y guía exactos, nunca agrupa por transporte."""
    salida = dict(fila)
    archivo, guia = _identidad(fila)
    if not archivo or not guia:
        return salida
    aplicaciones = ledger.get("aplicaciones", [])
    if not isinstance(aplicaciones, list):
        return salida
    vigente = None
    for entrada in aplicaciones:
        if not isinstance(entrada, Mapping) or entrada.get("tipo") != TIPO:
            continue
        documento = entrada.get("documento")
        destino = entrada.get("destino_operacional")
        if not isinstance(documento, Mapping) or not isinstance(destino, Mapping):
            continue
        if _identidad(documento) != (archivo, guia):
            continue
        direccion = str(destino.get("direccion") or "").strip()
        comuna = str(destino.get("comuna") or "").strip()
        if direccion and comuna:
            vigente = direccion, comuna, entrada.get("ruta_operacional")
    if vigente:
        direccion, comuna, ruta = vigente
        for campo in DERIVADOS:
            salida[campo] = ""
        salida["direccion_entrega"], salida["localidad_entrega"] = direccion, comuna
        salida["estado_entrega"] = "NO_INTENTADO"
        if ruta_valida(ruta, comuna):
            for campo in CAMPOS_RUTA:
                salida[campo] = str(ruta.get(campo) or "")
            salida["estado_entrega"] = "RESUELTO"
        # Casos reales 483491/483526: el estado operacional documental
        # reflejaba la ruta que faltaba; con el destino confirmado se
        # recalcula con la regla de siempre (documento en revisión o ruta no
        # calculada), así el viaje no queda en revisión por una ruta ya
        # resuelta ni sale de ella si la ruta sigue pendiente.
        salida["estado_operacional"] = (
            "REQUIERE_REVISION"
            if str(fila.get("estado_documental", "")).strip() == "REQUIERE_REVISION"
            or str(fila.get("indicador_revision", "")).strip().casefold() == "revisar"
            or salida["estado_ruta"] != RUTA_CALCULADA
            else "OK"
        )
    return salida


def calcular_ruta_operacional(fila: Mapping[str, object], direccion: str, comuna: str, *,
                              carpeta_catalogos, proveedor_rutas=None, proveedor_rutas_fallback=None) -> dict:
    """Ruta planta -> destino confirmado, sin leer el documento ni escribir
    el dataset. Sólo es válida si se calcula y la comuna resuelta coincide
    con la confirmada; si no, queda pendiente con su motivo."""
    from pathlib import Path
    from atlas_core.catalogo_plantas import CatalogoPlantas
    from atlas_core.direccion_equivalente import comuna_oficial
    from atlas_core.rutas.destino_entrega import calcular_ruta_con_planta_conocida

    carpeta = Path(carpeta_catalogos)
    planta_id = str(fila.get("planta_origen_id") or "").strip()
    try:
        planta = next((p for p in CatalogoPlantas(carpeta / "plantas.json").listar() if p.planta_id == planta_id),
                      None) if planta_id else None
    except (OSError, ValueError):
        planta = None
    if planta is None:
        return {"estado_ruta": "PENDIENTE", "motivo": "PLANTA_ORIGEN_DESCONOCIDA"}
    if proveedor_rutas is None:
        from atlas_core.revalidacion_documental import (
            _proveedor_rutas_fallback_predeterminado, _proveedor_rutas_ors_predeterminado)
        proveedor_rutas = _proveedor_rutas_ors_predeterminado(raiz_atlas=carpeta.parent)
        if proveedor_rutas_fallback is None:
            proveedor_rutas_fallback = _proveedor_rutas_fallback_predeterminado(raiz_atlas=carpeta.parent)
    try:
        from atlas_core.geografia.base_local import cargar_base_geografica_local_ine
        base_local = cargar_base_geografica_local_ine(raiz=carpeta.parent)
    except (OSError, ValueError):
        base_local = None
    try:
        resultado = calcular_ruta_con_planta_conocida(
            planta=planta, despachar_a_crudo=direccion, proveedor_rutas=proveedor_rutas,
            origen_determinado_por=str(fila.get("origen_determinado_por") or ""),
            evidencia_origen=str(fila.get("evidencia_origen") or ""),
            proveedor_geocodificacion_fallback=proveedor_rutas_fallback,
            comuna_territorial_conocida=comuna, comuna_confirmada_humano=comuna,
            base_geografica_local=base_local,
        )
    except Exception as error:  # noqa: BLE001 -- un fallo del proveedor deja la ruta pendiente
        return {"estado_ruta": "PENDIENTE", "motivo": f"ERROR_PROVEEDOR: {type(error).__name__}"}
    if resultado.estado_ruta != RUTA_CALCULADA:
        return {"estado_ruta": "PENDIENTE", "motivo": str(resultado.motivo_ruta or resultado.estado_ruta)}
    if comuna_oficial(str(resultado.localidad_entrega or "")) != comuna:
        return {"estado_ruta": "PENDIENTE", "motivo": "GEOCODIFICACION_CONTRADICE_COMUNA_CONFIRMADA",
                "comuna_resuelta": str(resultado.localidad_entrega or "")}
    ruta = {campo: str(getattr(resultado, campo, "") or "") for campo in CAMPOS_RUTA}
    ruta["comuna"] = comuna
    ruta["planta_origen_id"] = planta_id
    return ruta


def identidades_destino_confirmado(ruta_ledger):
    import json
    from pathlib import Path
    try:
        ledger = json.loads(Path(ruta_ledger).read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return frozenset()
    # Fail closed si el ledger existe pero esta danado: no volver a interpretar
    # un documento como si nunca se hubiera confirmado.
    aplicaciones = ledger.get("aplicaciones", []) if isinstance(ledger, Mapping) else None
    if not isinstance(aplicaciones, list):
        raise ValueError("Ledger de decisiones sin aplicaciones validas")
    identidades = set()
    for e in aplicaciones:
        if not isinstance(e, Mapping) or e.get("tipo") != TIPO:
            continue
        d, v = e.get("documento"), e.get("destino_operacional")
        if not isinstance(d, Mapping) or not isinstance(v, Mapping):
            raise ValueError("Decision de destino invalida")
        archivo, guia = _identidad(d)
        if not archivo or not guia or not v.get("direccion") or not v.get("comuna"):
            raise ValueError("Decision de destino incompleta")
        identidades.add((archivo, guia))
    return frozenset(identidades)


def retirar_decisiones_destino_operacional(decisiones, *, ruta_ledger):
    identidades = identidades_destino_confirmado(ruta_ledger)
    return [d for d in decisiones if not (
        d.get("tipo") in TIPOS_TARJETA_DESTINO and _identidad(d.get("documento") or {}) in identidades)]


def tiene_destino_confirmado(fila, identidades):
    return _identidad(fila) in identidades
