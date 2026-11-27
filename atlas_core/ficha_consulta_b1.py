"""Ficha integral de consulta B1 (solo lectura).

«Datos de la guía 492295», «Datos del viaje 0000372894» o «Datos del
transporte 0000372894» devuelven una ficha con todos los campos
operacionales de cada guía y los consolidados de su viaje.

Fuentes, ambas de solo lectura:
- Extracción: ``operacion/actual/analisis_completo_guias.csv`` (una fila por
  documento, con las correcciones ya aplicadas).
- Reporte Desktop: ``viajes.csv`` del reporte vigente (lo que muestra Desktop):
  la evidencia por documento, las entregas y los consolidados del viaje.

Nada se infiere ni se elige en silencio: un valor ausente se informa como
ausente y dos valores distintos para el mismo dato se informan en conflicto,
con su origen. La ficha no ofrece confirmar nada; cada campo lleva su
identificador estable (``campo``/``nivel``) y la identidad del documento para
una futura edición integral, que todavía no existe.
"""
from __future__ import annotations

import csv
import json
import re
import unicodedata
from pathlib import Path

VERSION_FICHA = 1

# Marcadores con los que la extracción y el reporte expresan "sin dato".
_AUSENTES = {"", "NO ENCONTRADO", "NO DISPONIBLE", "NO DETERMINADO", "NONE", "NULL", "NAN", "SIN DATO",
             "NO INFORMADO"}

_PATRON = re.compile(
    r"(?:(?:MUESTRAME|MUESTRA|MOSTRAR|VER|DAME|QUIERO VER|CONSULTAR|CONSULTA|ABRE|ABRIR)\s+)?"
    r"(?:(?:LOS|LAS|LA|EL)\s+)?"
    r"(?:DATOS|FICHA|DETALLE|DETALLES|INFORMACION|INFO)(?:\s+(?:COMPLETOS?|COMPLETA|INTEGRAL))?\s+"
    r"(?:DE\s+LA|DEL|DE)\s+(?P<tipo>GUIA|VIAJE|TRANSPORTE)\s+"
    r"(?:(?:N|NRO|NUMERO)\s+)?(?P<numero>\d{3,12})")

# (campo, etiqueta, grupo, editable). ``campo`` es la columna de la
# extracción: identificador estable para la futura edición integral.
CAMPOS_GUIA = (
    ("numero_guia", "N° de guía", "Documento", True),
    ("numero_transporte", "Transporte", "Documento", True),
    ("fecha", "Fecha", "Documento", True),
    ("cliente", "Cliente", "Cliente y entrega", True),
    ("rut_cliente", "RUT cliente", "Cliente y entrega", False),
    ("obra_destino", "Obra", "Cliente y entrega", True),
    ("direccion_entrega", "Dirección de entrega", "Cliente y entrega", True),
    ("despachar_a_crudo", "Dirección impresa en la guía", "Cliente y entrega", False),
    ("localidad_entrega", "Comuna de entrega", "Cliente y entrega", True),
    ("region_entrega", "Región", "Cliente y entrega", False),
    ("descripcion_material", "Materiales", "Carga", True),
    ("tipo_carga", "Tipo de carga", "Carga", False),
    ("peso_kg", "Peso", "Carga", True),
    ("chofer", "Chofer", "Transporte", True),
    ("rut_chofer", "RUT chofer", "Transporte", False),
    ("patente_tracto", "Patente tracto", "Transporte", True),
    ("patente_rampla", "Patente rampla", "Transporte", True),
    ("planta_origen_nombre", "Planta de origen", "Origen y horario", True),
    ("hora_entrada_aza", "Hora de entrada", "Origen y horario", True),
    ("hora_salida_aza", "Hora de salida", "Origen y horario", True),
    ("permanencia_minutos", "Permanencia", "Origen y horario", False),
    ("estado_operacional", "Estado operacional", "Estado", False),
    ("estado_documental", "Estado documental", "Estado", False),
    ("estado_entrega", "Estado de la entrega", "Estado", False),
    ("motivos_revision_documento", "Motivos de revisión", "Estado", False),
)

# (campo del reporte, etiqueta, grupo, campo de guía comparable, único por viaje)
CAMPOS_VIAJE = (
    ("numero_transporte", "Transporte", "Viaje", "numero_transporte", True),
    ("fecha", "Fecha", "Viaje", "fecha", True),
    ("estado", "Estado del viaje", "Viaje", None, False),
    ("motivos_revision", "Motivos de revisión", "Viaje", None, False),
    ("cantidad_documentos", "Guías", "Viaje", None, False),
    ("clientes", "Clientes", "Cliente y entrega", "cliente", False),
    ("obras_destino", "Obras", "Cliente y entrega", "obra_destino", False),
    ("direccion_entrega", "Dirección de entrega", "Cliente y entrega", None, False),
    ("localidad_entrega", "Comuna de entrega", "Cliente y entrega", None, False),
    ("region_entrega", "Región", "Cliente y entrega", None, False),
    ("estado_entrega", "Estado de la entrega", "Cliente y entrega", None, False),
    ("materiales", "Materiales", "Carga", "descripcion_material", False),
    ("tipos_carga", "Tipos de carga", "Carga", "tipo_carga", False),
    ("peso_total_viaje_kg", "Peso total", "Carga", None, False),
    ("choferes", "Chofer", "Transporte", "chofer", True),
    ("ruts_chofer", "RUT chofer", "Transporte", "rut_chofer", True),
    ("patentes_tracto", "Patente tracto", "Transporte", "patente_tracto", True),
    ("patentes_rampla", "Patente rampla", "Transporte", "patente_rampla", True),
    ("planta_origen_nombre", "Planta de origen", "Origen y horario", "planta_origen_nombre", True),
    ("hora_entrada_aza", "Hora de entrada", "Origen y horario", "hora_entrada_aza", True),
    ("hora_salida_aza", "Hora de salida", "Origen y horario", "hora_salida_aza", True),
    ("permanencia_minutos", "Permanencia", "Origen y horario", None, False),
    ("distancia_km", "Distancia", "Ruta", None, False),
    ("duracion_min", "Duración estimada", "Ruta", None, False),
    ("estado_ruta", "Estado de la ruta", "Ruta", None, False),
    ("motivo_ruta", "Motivo de la ruta", "Ruta", None, False),
)

FUENTE_EXTRACCION = "EXTRACCION"
FUENTE_REPORTE = "REPORTE_DESKTOP"
FUENTE_GUIAS = "GUIAS"


def _normalizar(texto: object) -> str:
    plano = unicodedata.normalize("NFD", str(texto or "").upper())
    plano = "".join(c for c in plano if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^A-Z0-9]+", " ", plano).split())


def interpretar_consulta_ficha(texto: str) -> tuple[str, str] | None:
    """(tipo, número) si el texto pide la ficha de una guía/viaje/transporte."""
    coincidencia = _PATRON.fullmatch(_normalizar(texto))
    if coincidencia is None:
        return None
    return coincidencia.group("tipo"), coincidencia.group("numero")


def ausente(valor: object) -> bool:
    # _normalizar convierte "NO_ENCONTRADO" y "-" en "NO ENCONTRADO" y "".
    return _normalizar(valor) in _AUSENTES


def _limpio(valor: object) -> str:
    return "" if ausente(valor) else " ".join(str(valor).split())


def _sin_comuna_final(direccion: str) -> str:
    """«MAESTRA LIDIA TORRES 92 SANTIAGO RECOLETA» y «MAESTRA LIDIA TORRES 92»
    son la misma dirección: se quitan al final una comuna oficial y/o SANTIAGO."""
    from atlas_core.direccion_equivalente import comuna_oficial
    palabras = _normalizar(direccion).split()
    for _ in range(2):
        for largo in range(min(4, len(palabras) - 1), 0, -1):
            cola = " ".join(palabras[-largo:])
            if cola == "SANTIAGO" or comuna_oficial(cola):
                palabras = palabras[:-largo]
                break
    return " ".join(palabras)


def _clave_comparable(campo: str, valor: str) -> str:
    if campo == "direccion_entrega":
        return _sin_comuna_final(valor)
    if campo in {"peso_kg", "permanencia_minutos"}:
        try:
            return str(round(float(valor.replace(",", "."))))
        except ValueError:
            pass
    if campo in {"numero_transporte", "numero_guia"}:
        return valor.lstrip("0") or "0"
    if campo in {"rut_chofer", "ruts_chofer", "rut_cliente", "patente_tracto", "patentes_tracto",
                 "patente_rampla", "patentes_rampla"}:
        # Puntos, guiones y espacios son formato, no otro valor.
        return _normalizar(valor).replace(" ", "")
    return _normalizar(valor)


def _multivalor(valor: object) -> list[str]:
    return [v for v in (_limpio(x) for x in str(valor or "").split("|")) if v]


def _transporte(valor: object) -> str:
    return re.sub(r"\D", "", str(valor or "")).lstrip("0")


def _leer_viajes(ruta: Path) -> list[dict[str, str]]:
    from atlas_core.consultas_atlas import cargar_viajes  # fija el límite de campo CSV
    return cargar_viajes(ruta)


def _json_lista(valor: object) -> list[dict]:
    try:
        datos = json.loads(str(valor or "").strip() or "[]")
    except ValueError:
        return []
    return [d for d in datos if isinstance(d, dict)] if isinstance(datos, list) else []


def _campo_con_fuentes(campo: str, etiqueta: str, grupo: str, nivel: str, fuentes: list[tuple[str, str]],
                       *, editable: bool = False) -> dict:
    """Une los valores de varias fuentes en un único campo explícito."""
    presentes = [(f, v) for f, v in fuentes if v]
    distintos: dict[str, tuple[str, str]] = {}
    for fuente, valor in presentes:
        distintos.setdefault(_clave_comparable(campo, valor), (fuente, valor))
    if not presentes:
        estado, valor = "AUSENTE", None
    elif len(distintos) > 1:
        estado, valor = "CONFLICTO", None
    else:
        estado, valor = "OK", presentes[0][1]
    return {"campo": campo, "etiqueta": etiqueta, "grupo": grupo, "nivel": nivel, "estado": estado,
            "valor": valor, "valores": [{"fuente": f, "valor": v} for f, v in presentes],
            "editable": editable}


def _documento_reporte(viaje: dict[str, str] | None, archivo: str) -> dict:
    if viaje is None:
        return {}
    for documento in _json_lista(viaje.get("evidencias_documentos")):
        if str(documento.get("archivo") or "") == archivo:
            return documento
    for documento in _json_lista(viaje.get("documentos_operacionales")):
        if str(documento.get("archivo") or "") == archivo:
            return documento
    return {}


def _entrega_de(viaje: dict[str, str] | None, numero_guia: str) -> dict:
    if viaje is None or not numero_guia:
        return {}
    entregas = [e for e in _json_lista(viaje.get("entregas"))
                if numero_guia in [str(g).strip() for g in e.get("numeros_guia") or []]]
    return entregas[0] if len(entregas) == 1 else {}


def _ficha_guia(fila: dict[str, str], viaje: dict[str, str] | None, viaje_indice: int | None,
                revisiones: int) -> dict:
    archivo = str(fila.get("archivo") or "")
    numero_guia = _limpio(fila.get("numero_guia"))
    reporte = _documento_reporte(viaje, archivo)
    entrega = _entrega_de(viaje, numero_guia)
    # El destino de la guía en el reporte es el de su entrega (con las
    # decisiones de destino ya proyectadas); la evidencia por documento
    # conserva la lectura previa.
    desde_entrega = {"localidad_entrega": entrega.get("localidad_entrega"),
                     "region_entrega": entrega.get("region_entrega"),
                     "direccion_entrega": entrega.get("destino_operacional")}
    campos = []
    for campo, etiqueta, grupo, editable in CAMPOS_GUIA:
        fuentes = [(FUENTE_EXTRACCION, _limpio(fila.get(campo)))]
        valor_reporte = (_limpio(desde_entrega.get(campo)) or _limpio(reporte.get(campo))
                         if campo in desde_entrega else _limpio(reporte.get(campo)))
        fuentes.append((FUENTE_REPORTE, valor_reporte))
        campos.append(_campo_con_fuentes(campo, etiqueta, grupo, "GUIA", fuentes, editable=editable))
    return {
        "documento": {"archivo": archivo, "numero_guia": numero_guia,
                      "numero_transporte": _limpio(fila.get("numero_transporte"))},
        "viaje_indice": viaje_indice,
        "en_reporte": bool(reporte),
        "original": {"archivo": archivo, "disponible_para_abrir": bool(archivo)},
        "revisiones_pendientes": revisiones,
        "campos": campos,
    }


def _ficha_viaje(viaje: dict[str, str], guias: list[dict]) -> dict:
    campos = []
    por_campo_guia = {g["documento"]["archivo"]: {c["campo"]: c for c in g["campos"]} for g in guias}
    for campo, etiqueta, grupo, comparable, unico in CAMPOS_VIAJE:
        valores = _multivalor(viaje.get(campo))
        if comparable and unico:
            # Dato único por viaje: el reporte y cada guía deben coincidir.
            fuentes = [(FUENTE_REPORTE, v) for v in valores]
            for guia in guias:
                propio = por_campo_guia[guia["documento"]["archivo"]].get(comparable)
                if propio and propio["estado"] == "OK":
                    fuentes.append((f"GUIA {guia['documento']['numero_guia'] or guia['documento']['archivo']}",
                                    propio["valor"]))
                elif propio and propio["estado"] == "CONFLICTO":
                    fuentes.extend((f"GUIA {guia['documento']['numero_guia']} ({v['fuente']})", v["valor"])
                                   for v in propio["valores"])
            item = _campo_con_fuentes(campo, etiqueta, grupo, "VIAJE", fuentes)
            # Guías que no traen este dato único: se informan, nunca se rellenan.
            item["ausente_en"] = [g["documento"]["numero_guia"] or g["documento"]["archivo"] for g in guias
                                  if (por_campo_guia[g["documento"]["archivo"]].get(comparable) or {}).get("estado") == "AUSENTE"]
        else:
            item = {"campo": campo, "etiqueta": etiqueta, "grupo": grupo, "nivel": "VIAJE",
                    "estado": "AUSENTE" if not valores else "OK",
                    "valor": None if not valores else " | ".join(valores),
                    "valores": [{"fuente": FUENTE_REPORTE, "valor": v} for v in valores], "editable": False}
        if campo == "peso_total_viaje_kg":
            item = _peso_total(item, guias)
        campos.append(item)
    entregas = [{
        "comuna": _limpio(e.get("localidad_entrega")) or None,
        "destino": _limpio(e.get("destino_operacional")) or None,
        "region": _limpio(e.get("region_entrega")) or None,
        "clientes": [str(c) for c in e.get("clientes") or []],
        "obras": [str(o) for o in e.get("obras_destino") or []],
        "numeros_guia": [str(g) for g in e.get("numeros_guia") or []],
        "estado_ruta": _limpio(e.get("estado_ruta")) or None,
    } for e in _json_lista(viaje.get("entregas"))]
    return {"viaje_id": viaje.get("viaje_id") or "", "numero_transporte": _limpio(viaje.get("numero_transporte")),
            "fecha": _limpio(viaje.get("fecha")), "numeros_guia": _multivalor(viaje.get("numeros_guia")),
            "campos": campos, "entregas": entregas}


def _peso_total(item: dict, guias: list[dict]) -> dict:
    pesos = []
    for guia in guias:
        peso = next((c for c in guia["campos"] if c["campo"] == "peso_kg"), None)
        if peso is None or peso["estado"] != "OK":
            return item  # una guía sin peso: la suma no es comparable
        pesos.append(float(peso["valor"].replace(",", ".")) if re.fullmatch(r"\d+(?:[.,]\d+)?", peso["valor"]) else None)
    if not pesos or None in pesos:
        return item
    suma = str(round(sum(pesos)))
    fuentes = [(v["fuente"], v["valor"]) for v in item["valores"]] + [("SUMA_GUIAS", suma)]
    return _campo_con_fuentes(item["campo"], item["etiqueta"], item["grupo"], "VIAJE", fuentes)


def _revisiones_por_archivo(decisiones: list[dict]) -> dict[str, int]:
    conteo: dict[str, int] = {}
    for decision in decisiones:
        if str(decision.get("estado", "PENDIENTE")).upper() != "PENDIENTE":
            continue
        documento = decision.get("documento") if isinstance(decision.get("documento"), dict) else {}
        archivos = {str(decision.get("archivo") or "").strip(), str(documento.get("archivo") or "").strip()}
        archivos |= {str(d.get("archivo") or "").strip() for d in decision.get("documentos") or [] if isinstance(d, dict)}
        for archivo in archivos - {""}:
            conteo[archivo] = conteo.get(archivo, 0) + 1
    return conteo


def construir_ficha(tipo: str, numero: str, *, filas: list[dict[str, str]], viajes: list[dict[str, str]] | None,
                    decisiones: list[dict] | None = None, ledger: dict | None = None) -> dict:
    """Respuesta B1 completa para una consulta de ficha. Nunca escribe."""
    if ledger is not None:
        # Valor vigente de cada guía: la extracción con las decisiones de
        # destino ya confirmadas (lo mismo que publica el reporte).
        from atlas_core.destino_operacional import proyectar_destino
        filas = [proyectar_destino(f, ledger) for f in filas]
    viajes_lista = viajes or []
    por_archivo = {str(f.get("archivo") or ""): f for f in filas}
    revisiones = _revisiones_por_archivo(decisiones or [])
    numero_transporte = _transporte(numero)

    def viajes_de_transporte():
        return [v for v in viajes_lista
                if numero_transporte and (_transporte(v.get("numero_transporte")) == numero_transporte
                                          or numero_transporte in {_transporte(t) for t in
                                                                   str(v.get("transportes_aza") or "").split("|")})]

    def viajes_con_archivo(archivo):
        return [v for v in viajes_lista if archivo in [d.strip() for d in str(v.get("documentos") or "").split("|")]]

    elegidos: list[dict[str, str]] = []
    filas_guia: list[dict[str, str]] = []
    if tipo == "GUIA":
        filas_guia = [f for f in filas if _limpio(f.get("numero_guia")) == numero]
        for fila in filas_guia:
            for viaje in viajes_con_archivo(str(fila.get("archivo") or "")):
                if viaje not in elegidos:
                    elegidos.append(viaje)
    else:
        elegidos = viajes_de_transporte()
        por_transporte = bool(elegidos) or tipo == "TRANSPORTE"
        if tipo == "VIAJE" and not elegidos:
            # «viaje 492295»: el viaje que contiene esa guía.
            for fila in (f for f in filas if _limpio(f.get("numero_guia")) == numero):
                for viaje in viajes_con_archivo(str(fila.get("archivo") or "")):
                    if viaje not in elegidos:
                        elegidos.append(viaje)
        for viaje in elegidos:
            for archivo in (d.strip() for d in str(viaje.get("documentos") or "").split("|")):
                if archivo and archivo in por_archivo and por_archivo[archivo] not in filas_guia:
                    filas_guia.append(por_archivo[archivo])
        if numero_transporte and por_transporte:
            # Guías del transporte que el reporte todavía no agrupa en un viaje.
            for fila in filas:
                if _transporte(fila.get("numero_transporte")) == numero_transporte and fila not in filas_guia:
                    filas_guia.append(fila)

    nombre = {"GUIA": "la guía", "VIAJE": "el viaje", "TRANSPORTE": "el transporte"}[tipo]
    if not filas_guia and not elegidos:
        return {"estado": "RESULTADO_LECTURA", "accion": "FICHA_CONSULTA", "solo_lectura": True, "ficha": None,
                "mensaje": f"No encontré {nombre} {numero} en la extracción ni en el reporte vigente. No se cambió nada."}

    def ficha_documento(archivo: str, fila: dict[str, str] | None) -> dict:
        propios = [i for i, v in enumerate(elegidos) if v in viajes_con_archivo(archivo)]
        indice = propios[0] if len(propios) == 1 else None
        viaje = elegidos[indice] if indice is not None else None
        if fila is not None:
            guia = _ficha_guia(fila, viaje, indice, revisiones.get(archivo, 0))
            guia["en_extraccion"] = True
            return guia
        # Documento del reporte sin fila en la extracción: se muestra igual,
        # sólo con lo que el reporte trae.
        documento = _documento_reporte(viaje, archivo) or {"archivo": archivo}
        guia = _ficha_guia({"archivo": archivo}, viaje, indice, revisiones.get(archivo, 0))
        guia["en_extraccion"] = False
        guia["campos"] = [_campo_con_fuentes(c["campo"], c["etiqueta"], c["grupo"], "GUIA",
                                             [(FUENTE_REPORTE, _limpio(documento.get(c["campo"])))],
                                             editable=c["editable"]) for c in guia["campos"]]
        guia["documento"]["numero_guia"] = _limpio(documento.get("numero_guia"))
        return guia

    def documentos_de(viaje: dict[str, str]) -> list[str]:
        return [d.strip() for d in str(viaje.get("documentos") or "").split("|") if d.strip()]

    guias = [ficha_documento(str(f.get("archivo") or ""), f) for f in filas_guia]
    if tipo != "GUIA":
        mostrados = {g["documento"]["archivo"] for g in guias}
        for viaje in elegidos:
            guias.extend(ficha_documento(a, None) for a in documentos_de(viaje)
                         if a not in por_archivo and a not in mostrados)

    def orden(guia: dict) -> tuple:
        numero_guia = guia["documento"]["numero_guia"]
        indice = guia["viaje_indice"]
        return (len(elegidos) if indice is None else indice, 0 if numero_guia.isdigit() else 1,
                int(numero_guia) if numero_guia.isdigit() else 0, guia["documento"]["archivo"])

    guias.sort(key=orden)

    # El consolidado de cada viaje compara SIEMPRE todas sus guías, aunque la
    # consulta pida una sola (si no, una guía aislada nunca mostraría el
    # conflicto que el viaje sí tiene).
    por_archivo_mostrado = {g["documento"]["archivo"]: g for g in guias}
    fichas_viaje = []
    for viaje in elegidos:
        del_viaje = [por_archivo_mostrado.get(a) or ficha_documento(a, por_archivo.get(a)) for a in documentos_de(viaje)]
        fichas_viaje.append(_ficha_viaje(viaje, del_viaje))
    avisos = []
    if len(elegidos) > 1:
        avisos.append(f"{nombre.capitalize()} {numero} aparece en {len(elegidos)} viajes del reporte vigente; "
                      "cada guía indica a cuál pertenece.")
    if tipo == "GUIA" and len(filas_guia) > 1:
        avisos.append(f"El número de guía {numero} está en {len(filas_guia)} documentos distintos.")
    sin_viaje = [g for g in guias if g["viaje_indice"] is None]
    if sin_viaje:
        avisos.append(f"{len(sin_viaje)} guía(s) no tienen viaje en el reporte vigente.")
    conflictos = sum(1 for g in guias for c in g["campos"] if c["estado"] == "CONFLICTO") + \
        sum(1 for v in fichas_viaje for c in v["campos"] if c["estado"] == "CONFLICTO")
    total = len(guias)
    resumen = f"Ficha {'de la guía' if tipo == 'GUIA' else 'del ' + nombre.split()[1]} {numero}: {total} {'guía' if total == 1 else 'guías'}"
    if conflictos:
        resumen += f", {conflictos} {'dato en conflicto' if conflictos == 1 else 'datos en conflicto'}"
    return {
        "estado": "FICHA", "accion": "FICHA_CONSULTA", "solo_lectura": True,
        "mensaje": resumen + ". Solo lectura: no se cambió nada.",
        "ficha": {
            "version": VERSION_FICHA, "consulta": {"tipo": tipo, "numero": numero},
            "guias": guias, "viajes": fichas_viaje, "avisos": avisos,
            # Edición integral: Desktop envía los cambios al canal B1
            # (`atlas_core.edicion_ficha_b1`); las opciones las agrega
            # `responder_ficha`, que conoce los catálogos.
            "edicion": {"disponible": True, "campos_editables": [c for c, _e, _g, editable in CAMPOS_GUIA if editable],
                        "opciones": {}},
        },
    }


def responder_ficha(ctx, texto: str) -> dict | None:
    """Ficha para el texto, o ``None`` si no es una consulta de ficha."""
    pedido = interpretar_consulta_ficha(texto)
    if pedido is None:
        return None
    instantanea = ctx.instantanea_documental()
    viajes = None
    try:
        from atlas_core.consulta_revisiones_b1 import _ruta_viajes
        ruta = _ruta_viajes(ctx)
        if ruta.is_file():
            viajes = _leer_viajes(ruta)
    except (OSError, ValueError, csv.Error):
        viajes = None
    respuesta = construir_ficha(pedido[0], pedido[1], filas=instantanea["filas"], viajes=viajes,
                                decisiones=instantanea["decisiones"], ledger=instantanea["ledger"])
    if respuesta.get("ficha"):
        from atlas_core.edicion_ficha_b1 import opciones_edicion
        respuesta["ficha"]["edicion"]["opciones"] = opciones_edicion(ctx)
    if viajes is None and respuesta.get("ficha"):
        respuesta["ficha"]["avisos"].insert(0, "No pude leer el reporte vigente: solo se muestran datos de la extracción.")
    return respuesta
