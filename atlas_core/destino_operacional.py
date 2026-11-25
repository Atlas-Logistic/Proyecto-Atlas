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
# Ubicación del destino (independiente de la planta de origen).
CAMPOS_UBICACION = ("latitud_entrega", "longitud_entrega", "region_entrega", "codigo_pais", "codigo_unidad",
                    "codigo_contexto")
RUTA_CALCULADA = "RUTA_CALCULADA"
# Tarjetas que preguntan por el destino de un documento: la decisión humana
# las responde. Las demás revisiones de la misma guía siguen vigentes.
TIPOS_TARJETA_DESTINO = frozenset({"DESTINO_NO_RESUELTO", "DESTINO_SIN_CONFIRMAR"})


def _identidad(documento: Mapping[str, object]) -> tuple[str, str]:
    return str(documento.get("archivo") or "").strip(), str(documento.get("numero_guia") or "").strip()


def _correccion_folio_humana(entrada: Mapping[str, object]) -> bool:
    from atlas_core.decisiones_pendientes import _actor_es_humano
    actor = str(entrada.get("actor") or "").strip()
    confirmante = str(entrada.get("confirmado_por") or "").strip()
    if actor.upper() == "B1":
        return bool(confirmante and _actor_es_humano(confirmante))
    return bool(actor and _actor_es_humano(actor) and (not confirmante or _actor_es_humano(confirmante)))


def _folios_anteriores(fila: Mapping[str, object], aplicaciones: list):
    """Identidades anteriores unidas por correcciones auditadas del mismo documento.

    Se recorre hacia atrás para respetar el orden de las correcciones y nunca
    inferir una relación por folio o transporte por sí solos.
    """
    archivo, guia = _identidad(fila)
    transporte = str(fila.get("numero_transporte") or "").strip()
    vigentes = {guia}
    for entrada in reversed(aplicaciones):
        yield entrada, vigentes
        if not isinstance(entrada, Mapping) or not archivo or not transporte:
            continue
        doc = entrada.get("documento")
        if not isinstance(doc, Mapping):
            continue
        anterior = str(entrada.get("valor_documental") or "").strip()
        nuevo = str(entrada.get("valor_corregido") or "").strip()
        if (entrada.get("tipo") == "CORRECCION_DOCUMENTAL_OPERADOR"
                and entrada.get("accion") == "CORREGIR_NUMERO_GUIA"
                and entrada.get("campo") == "numero_guia" and _correccion_folio_humana(entrada)
                and _identidad(doc) == (archivo, nuevo)
                and str(doc.get("numero_transporte") or "").strip() == transporte
                and nuevo in vigentes and anterior and anterior != nuevo):
            vigentes.add(anterior)


def ruta_valida(ruta: object, comuna: str) -> bool:
    return (isinstance(ruta, Mapping) and ruta.get("estado_ruta") == RUTA_CALCULADA
            and bool(str(ruta.get("distancia_km") or "").strip())
            and str(ruta.get("comuna") or "").strip() == comuna)


TIPO_CORRECCION_ORIGEN = "CORRECCION_ORIGEN_OPERACIONAL"
MOTIVO_RUTA_ORIGEN_PENDIENTE = "ORIGEN_MODIFICADO_RUTA_PENDIENTE"


def destino_vigente(fila: Mapping[str, object], ledger: Mapping[str, object]) -> dict | None:
    """Decisión humana de destino vigente para ESTE documento (archivo y
    folio exactos, siguiendo sus correcciones de folio auditadas), o None.

    `origen_corregido_despues` indica si, después de esa decisión, una
    corrección de origen auditada cambió la planta del documento: una ruta
    guardada sin planta registrada ya no puede atribuirse a la planta actual.
    """
    archivo, guia = _identidad(fila)
    aplicaciones = ledger.get("aplicaciones", []) if isinstance(ledger, Mapping) else None
    if not archivo or not guia or not isinstance(aplicaciones, list):
        return None
    ultimo = len(aplicaciones) - 1
    for k, (entrada, folios) in enumerate(_folios_anteriores(fila, aplicaciones)):
        if not isinstance(entrada, Mapping) or entrada.get("tipo") != TIPO:
            continue
        documento = entrada.get("documento")
        destino = entrada.get("destino_operacional")
        if not isinstance(documento, Mapping) or not isinstance(destino, Mapping):
            continue
        archivo_entrada, guia_entrada = _identidad(documento)
        if archivo_entrada != archivo or guia_entrada not in folios:
            continue
        if guia_entrada != guia and str(documento.get("numero_transporte") or "").strip() != str(fila.get("numero_transporte") or "").strip():
            continue
        direccion = str(destino.get("direccion") or "").strip()
        comuna = str(destino.get("comuna") or "").strip()
        if direccion and comuna:
            posicion = ultimo - k
            return {"decision_id": str(entrada.get("decision_id") or ""), "direccion": direccion,
                    "comuna": comuna, "ruta": entrada.get("ruta_operacional"),
                    "conservar": bool(entrada.get("conservar_estado_operacional")),
                    "origen_corregido_despues": _origen_corregido_despues(aplicaciones[posicion + 1:], archivo)}
    return None


def _origen_corregido_despues(posteriores: list, archivo: str) -> bool:
    for entrada in posteriores:
        if not isinstance(entrada, Mapping) or entrada.get("tipo") != TIPO_CORRECCION_ORIGEN:
            continue
        documentos = entrada.get("documentos_viaje")
        documentos = list(documentos) if isinstance(documentos, list) else []
        documentos.append(entrada.get("documento"))
        if any(isinstance(d, Mapping) and str(d.get("archivo") or "").strip() == archivo for d in documentos):
            return True
    return False


def ruta_de_planta_actual(ruta: object, fila: Mapping[str, object], *, origen_corregido_despues: bool) -> bool:
    """Una ruta hacia el destino confirmado sólo describe el viaje si salió
    de la planta que el documento tiene HOY. Con la planta registrada en la
    ruta, se compara; sin ella (rutas antiguas), sólo vale mientras ninguna
    corrección de origen posterior a la decisión haya cambiado la planta."""
    if not isinstance(ruta, Mapping):
        return False
    planta = str(ruta.get("planta_origen_id") or "").strip()
    if planta:
        return planta == str(fila.get("planta_origen_id") or "").strip()
    return not origen_corregido_despues


def proyectar_destino(fila: Mapping[str, object], ledger: Mapping[str, object]) -> dict:
    """Devuelve copia; exige archivo y guía exactos, nunca agrupa por transporte."""
    salida = dict(fila)
    vigente = destino_vigente(fila, ledger)
    if vigente:
        direccion, comuna, ruta = vigente["direccion"], vigente["comuna"], vigente["ruta"]
        conservar, decision_id = vigente["conservar"], vigente["decision_id"]
        # Caso real 488100: la ruta calculada al confirmar quedó PENDIENTE
        # porque el geocodificador no ubicaba AZA COLINA. Un recálculo
        # explícito posterior (`recalculo_ruta_planta`) para ESTA misma
        # decisión, dirección y comuna la reemplaza; la decisión no cambia.
        # Tras corregir la planta de origen, el recálculo desde la planta
        # nueva la reemplaza aunque haya quedado pendiente: la ruta de la
        # decisión salió de la planta anterior y nunca vuelve a publicarse.
        if not conservar:
            from atlas_core.recalculo_ruta_planta import ruta_operacional_recalculada
            corregido = vigente["origen_corregido_despues"]
            recalculada = ruta_operacional_recalculada(fila, decision_id=decision_id, direccion=direccion,
                                                       comuna=comuna)
            if (ruta_de_planta_actual(recalculada, fila, origen_corregido_despues=corregido)
                    and (ruta_valida(recalculada, comuna) or str(recalculada.get("planta_origen_id") or "").strip())):
                ruta = recalculada
            if not ruta_de_planta_actual(ruta, fila, origen_corregido_despues=corregido):
                ruta = None
        if conservar:
            salida["direccion_entrega"], salida["localidad_entrega"] = direccion, comuna
            salida["estado_ruta_historica"] = salida.get("estado_ruta", "")
            salida["estado_ruta"] = "REQUIERE_COMPROBACION"
            salida["ruta_requiere_comprobacion"] = True
            if vigente["origen_corregido_despues"]:
                # La distancia documental conservada salió de la planta
                # anterior (el dataset la protege): sólo se publica la
                # recalculada desde la planta actual; si no hay, ninguna.
                from atlas_core.recalculo_ruta_planta import ruta_operacional_recalculada
                recalculada = ruta_operacional_recalculada(fila, decision_id=decision_id, direccion=direccion,
                                                           comuna=comuna)
                valida = (ruta_de_planta_actual(recalculada, fila, origen_corregido_despues=True)
                          and recalculada.get("estado_ruta") == RUTA_CALCULADA)
                for campo in ("distancia_km", "duracion_min", "proveedor_ruta"):
                    salida[campo] = str(recalculada.get(campo) or "") if valida else ""
                if not valida:
                    salida["motivo_ruta"] = MOTIVO_RUTA_ORIGEN_PENDIENTE
            return salida
        for campo in DERIVADOS:
            salida[campo] = ""
        salida["direccion_entrega"], salida["localidad_entrega"] = direccion, comuna
        salida["estado_entrega"] = "NO_INTENTADO"
        if ruta_valida(ruta, comuna):
            for campo in CAMPOS_RUTA:
                salida[campo] = str(ruta.get(campo) or "")
            salida["estado_entrega"] = "RESUELTO"
        elif isinstance(ruta, Mapping) and ruta.get("coordenadas_confirmadas") and str(ruta.get("comuna") or "").strip() == comuna:
            # Planta corregida sin ruta calculable: el destino confirmado y
            # sus coordenadas siguen vigentes; sólo la distancia queda pendiente.
            for campo in CAMPOS_UBICACION:
                salida[campo] = str(ruta.get(campo) or "")
            salida["estado_entrega"] = "RESUELTO"
            salida["estado_ruta"] = "REQUIERE_REVISION"
            salida["motivo_ruta"] = MOTIVO_RUTA_ORIGEN_PENDIENTE
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


METODO_UBICACION_CATALOGO = "IDENTIDAD_DESTINO_CONFIRMADO_CATALOGO"


def ubicacion_destino_catalogo(direccion: str, comuna: str, *, carpeta_catalogos) -> dict | None:
    """Ubicación del destino CONFIRMADO del catálogo que es, sin ambigüedad,
    esta dirección confirmada por un humano
    (`IndiceIdentidadDestinos.destino_con_coordenadas`): sus coordenadas
    confirmadas y la región/códigos oficiales de la comuna confirmada.
    None si no hay identidad única con coordenadas coherentes."""
    from atlas_core.geografia import EstadoNormalizacion, cargar_geografia
    from atlas_core.identidad_destino import IndiceIdentidadDestinos

    destino = IndiceIdentidadDestinos.desde_carpeta(carpeta_catalogos).destino_con_coordenadas(direccion, comuna)
    if destino is None:
        return None
    ubicacion = {"latitud_entrega": str(float(destino.latitud)), "longitud_entrega": str(float(destino.longitud)),
                 "region_entrega": "", "codigo_pais": "", "codigo_unidad": "", "codigo_contexto": ""}
    geografia = cargar_geografia("CL")
    normalizada = geografia.normalizar(comuna)
    if normalizada.estado == EstadoNormalizacion.EXACTA and normalizada.unidad is not None:
        contexto = geografia.parametros_geocodificacion(normalizada.unidad)
        ubicacion.update(region_entrega=contexto.nombre_contexto, codigo_pais=contexto.codigo_pais,
                         codigo_unidad=contexto.codigo_unidad, codigo_contexto=contexto.codigo_contexto)
    return {**ubicacion, "destino_id": str(destino.destino_id), "metodo_ubicacion": METODO_UBICACION_CATALOGO}


def calcular_ruta_operacional(fila: Mapping[str, object], direccion: str, comuna: str, *,
                              carpeta_catalogos, proveedor_rutas=None, proveedor_rutas_fallback=None) -> dict:
    """Ruta planta -> destino confirmado, sin leer el documento ni escribir
    el dataset. Sólo es válida si se calcula y la comuna resuelta coincide
    con la confirmada; si no, queda pendiente con su motivo.

    Si el catálogo ya conoce ese destino con coordenadas confirmadas
    (`ubicacion_destino_catalogo`), la dirección no se vuelve a
    geocodificar: sólo se pide al proveedor el recorrido desde la planta
    del documento hasta esas coordenadas. Si no, se geocodifica con la
    comuna confirmada como control."""
    from pathlib import Path
    from atlas_core.catalogo_plantas import CatalogoPlantas
    from atlas_core.direccion_equivalente import comuna_oficial
    from atlas_core.rutas.destino_entrega import calcular_ruta_con_planta_conocida

    carpeta = Path(carpeta_catalogos)
    planta_id = str(fila.get("planta_origen_id") or "").strip()
    ubicacion = ubicacion_destino_catalogo(direccion, comuna, carpeta_catalogos=carpeta)
    if ubicacion is not None:
        return ruta_hacia_ubicacion(planta_id, comuna, ubicacion, carpeta_catalogos=carpeta,
                                    proveedor_rutas=proveedor_rutas)
    try:
        plantas = tuple(CatalogoPlantas(carpeta / "plantas.json").listar())
    except (OSError, ValueError):
        plantas = ()
    planta = next((p for p in plantas if p.planta_id == planta_id), None) if planta_id else None
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
            base_geografica_local=base_local, plantas_conocidas=plantas,
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


def _coordenadas_confirmadas(ruta: object):
    from atlas_core.rutas.modelos import Coordenadas
    if not isinstance(ruta, Mapping):
        return None
    try:
        latitud = float(str(ruta.get("latitud_entrega") or "").strip())
        longitud = float(str(ruta.get("longitud_entrega") or "").strip())
        coordenadas = Coordenadas(longitud, latitud)
    except Exception:  # noqa: BLE001 -- coordenada ilegible o no finita: no se usa
        return None
    if not (-90 <= latitud <= 90 and -180 <= longitud <= 180):
        return None
    return coordenadas


def ubicacion_confirmada(fila: Mapping[str, object], vigente: Mapping[str, object]) -> dict | None:
    """Ruta guardada que lleva las coordenadas del destino confirmado (las
    coordenadas no dependen de la planta): primero el recálculo ligado a
    ESTA decisión, luego la ruta guardada al confirmar. None si ninguna."""
    from atlas_core.recalculo_ruta_planta import ruta_operacional_recalculada
    recalculada = ruta_operacional_recalculada(fila, decision_id=str(vigente.get("decision_id") or ""),
                                               direccion=str(vigente.get("direccion") or ""),
                                               comuna=str(vigente.get("comuna") or ""))
    for ruta in (recalculada, vigente.get("ruta")):
        if (_coordenadas_confirmadas(ruta) is not None
                and str(ruta.get("comuna") or vigente.get("comuna") or "").strip() == vigente.get("comuna")):
            return dict(ruta)
    return None


def recalcular_ruta_desde_planta(planta_id: str, direccion: str, comuna: str, ruta_anterior: object, *,
                                 fila: Mapping[str, object], carpeta_catalogos, proveedor_rutas=None,
                                 proveedor_rutas_fallback=None, perfil: str = "driving-hgv") -> dict:
    """Ruta desde una planta corregida hacia el destino YA confirmado.

    El destino no se vuelve a resolver: si la ruta anterior tenía
    coordenadas, se conservan (con región y códigos) y sólo se pide al
    proveedor el recorrido planta nueva -> esas coordenadas. Sin
    coordenadas previas se usa el mismo cálculo de la confirmación
    (`calcular_ruta_operacional`, con la comuna confirmada como control).
    Nunca reutiliza la distancia anterior: si el proveedor no la calcula,
    la ruta queda pendiente (conservando las coordenadas confirmadas).
    Siempre registra la planta de la que sale."""
    if _coordenadas_confirmadas(ruta_anterior) is None:
        ruta = calcular_ruta_operacional({**dict(fila), "planta_origen_id": planta_id}, direccion, comuna,
                                         carpeta_catalogos=carpeta_catalogos, proveedor_rutas=proveedor_rutas,
                                         proveedor_rutas_fallback=proveedor_rutas_fallback)
        return {**ruta, "comuna": comuna, "planta_origen_id": planta_id}
    ubicacion = {campo: str(ruta_anterior.get(campo) or "") for campo in CAMPOS_UBICACION}
    return ruta_hacia_ubicacion(planta_id, comuna, ubicacion, carpeta_catalogos=carpeta_catalogos,
                                proveedor_rutas=proveedor_rutas, perfil=perfil, pendiente_con_ubicacion=True)


def ruta_hacia_ubicacion(planta_id: str, comuna: str, ubicacion: Mapping[str, object], *, carpeta_catalogos,
                         proveedor_rutas=None, perfil: str = "driving-hgv",
                         pendiente_con_ubicacion: bool = False) -> dict:
    """Recorrido planta -> coordenadas ya confirmadas del destino, sin
    geocodificar. La ubicación (coordenadas, región, códigos y su
    procedencia) se copia tal cual; sólo la distancia y la duración vienen
    del proveedor. Si no se calcula, la ruta queda pendiente con su motivo
    (con `pendiente_con_ubicacion`, conservando la ubicación como
    confirmada: planta corregida sin ruta calculable)."""
    from pathlib import Path
    from atlas_core.catalogo_plantas import CatalogoPlantas
    from atlas_core.rutas.geocerca import coordenada_ruteo_planta
    from atlas_core.rutas.modelos import EstadoRuta

    destino = _coordenadas_confirmadas(ubicacion)
    ubicacion = {campo: str(valor or "") for campo, valor in ubicacion.items()}
    base = {"comuna": comuna, "planta_origen_id": planta_id}
    pendiente = {**ubicacion, **base, "estado_ruta": "PENDIENTE"}
    if pendiente_con_ubicacion:
        pendiente["coordenadas_confirmadas"] = True
    if destino is None:
        return {**pendiente, "motivo": "COORDENADAS_DESTINO_INVALIDAS"}
    carpeta = Path(carpeta_catalogos)
    try:
        plantas = tuple(CatalogoPlantas(carpeta / "plantas.json").listar())
    except (OSError, ValueError):
        plantas = ()
    planta = next((p for p in plantas if p.planta_id == planta_id), None) if planta_id else None
    if planta is None:
        return {**pendiente, "motivo": "PLANTA_ORIGEN_DESCONOCIDA"}
    origen = coordenada_ruteo_planta(planta)
    if origen is None:
        return {**pendiente, "motivo": "PLANTA_SIN_COORDENADAS_EN_CATALOGO"}
    if proveedor_rutas is None:
        from atlas_core.revalidacion_documental import _proveedor_rutas_ors_predeterminado
        proveedor_rutas = _proveedor_rutas_ors_predeterminado(raiz_atlas=carpeta.parent)
    try:
        resultado = proveedor_rutas.calcular_ruta(origen, destino, perfil)
    except Exception as error:  # noqa: BLE001 -- un fallo del proveedor deja la ruta pendiente
        return {**pendiente, "motivo": f"ERROR_PROVEEDOR: {type(error).__name__}"}
    if resultado.estado != EstadoRuta.RUTA_CALCULADA or not resultado.distancia_km:
        return {**pendiente, "motivo": str(resultado.motivo or resultado.estado.value)}
    return {**ubicacion, **base, "coordenadas_confirmadas": True,
            "distancia_km": str(resultado.distancia_km), "duracion_min": str(resultado.duracion_estimada_min),
            "proveedor_ruta": str(getattr(proveedor_rutas, "nombre", "") or ""), "estado_ruta": RUTA_CALCULADA}


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
        if not isinstance(e, Mapping):
            continue
        if (e.get("tipo") == "CORRECCION_DOCUMENTAL_OPERADOR" and e.get("accion") == "CORREGIR_NUMERO_GUIA"
                and e.get("campo") == "numero_guia" and _correccion_folio_humana(e)
                and isinstance(e.get("documento"), Mapping)):
            d = e["documento"]
            archivo, nuevo = _identidad(d)
            transporte = str(d.get("numero_transporte") or "").strip()
            anterior = str(e.get("valor_documental") or "").strip()
            if (archivo and transporte and anterior and nuevo and anterior != nuevo
                    and nuevo == str(e.get("valor_corregido") or "").strip()
                    and (archivo, anterior, transporte) in identidades):
                identidades.remove((archivo, anterior, transporte))
                identidades.add((archivo, nuevo, transporte))
            continue
        if e.get("tipo") != TIPO:
            continue
        d, v = e.get("documento"), e.get("destino_operacional")
        if not isinstance(d, Mapping) or not isinstance(v, Mapping):
            raise ValueError("Decision de destino invalida")
        archivo, guia = _identidad(d)
        if not archivo or not guia or not v.get("direccion") or not v.get("comuna"):
            raise ValueError("Decision de destino incompleta")
        identidades.add((archivo, guia, str(d.get("numero_transporte") or "").strip()))
    return frozenset((archivo, guia) for archivo, guia, _ in identidades)


def retirar_decisiones_destino_operacional(decisiones, *, ruta_ledger):
    identidades = identidades_destino_confirmado(ruta_ledger)
    return [d for d in decisiones if not (
        d.get("tipo") in TIPOS_TARJETA_DESTINO and _identidad(d.get("documento") or {}) in identidades)]


def tiene_destino_confirmado(fila, identidades):
    return _identidad(fila) in identidades
