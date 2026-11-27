"""Edición integral de la ficha B1 por el canal oficial de B1.

Desktop envía los cambios de la ficha como UN turno de conversación B1 con un
marcador interno (``@ficha-lote:<base64 JSON>``, nunca visible), por el mismo
IPC que cualquier corrección. Aquí cada cambio se traduce a la acción canónica
que ya corrige ese campo (``DOCUMENTO_CORREGIR_CAMPO``,
``DOCUMENTO_CORREGIR_DESTINO_OPERACIONAL``, ``DOCUMENTO_ASIGNAR_OBRA``,
``DOCUMENTO_CORREGIR_CHOFER_OPERACIONAL``, ``DOCUMENTO_CORREGIR_PLANTA_ORIGEN``,
``DOCUMENTO_CORREGIR_NUMERO_GUIA``): la capa de acciones hace el preview, guarda
la auditoría, exige la confirmación humana, respalda, protege el valor en el
ledger y recalcula lo derivado (bandeja, ruta, reporte). No hay otro camino de
escritura.

El lote se previsualiza completo antes de confirmar: si algún cambio no es
válido no queda nada pendiente. Al confirmar, cada acción se ejecuta con su
token; si una corrección anterior del mismo documento dejó obsoleto el
preview de otra, ésta sólo se ejecuta si su valor anterior y su valor nuevo
son exactamente los que la persona vio.
"""
from __future__ import annotations

import base64
import binascii
import json
import re

MARCADOR = "@ficha-lote:"
VERSION_LOTE = 1
MAXIMO_CAMBIOS = 200

# Campo de la ficha -> etiqueta visible. Son los campos operacionales que la
# ficha permite editar; los demás (RUT, región, tipo de carga, estados,
# permanencia) se derivan de éstos.
CAMPOS_EDITABLES = {
    "numero_guia": "N° de guía",
    "numero_transporte": "Transporte",
    "fecha": "Fecha",
    "cliente": "Cliente",
    "obra_destino": "Obra",
    "direccion_entrega": "Dirección de entrega",
    "localidad_entrega": "Comuna de entrega",
    "descripcion_material": "Materiales",
    "peso_kg": "Peso",
    "chofer": "Chofer",
    "patente_tracto": "Patente tracto",
    "patente_rampla": "Patente rampla",
    "planta_origen_nombre": "Planta de origen",
    "hora_entrada_aza": "Hora de entrada",
    "hora_salida_aza": "Hora de salida",
}
_CAMPO_DOCUMENTAL = {"numero_transporte", "fecha", "cliente", "descripcion_material", "peso_kg",
                     "patente_tracto", "patente_rampla", "hora_entrada_aza", "hora_salida_aza"}
# Orden de ejecución: la identidad del documento (transporte y folio) al
# final, para que las demás correcciones sigan citando el folio vigente.
_ORDEN = {"numero_transporte": 8, "numero_guia": 9, "DESTINO": 5}


class ErrorLoteFicha(ValueError):
    pass


def opciones_edicion(ctx) -> dict[str, list[str]]:
    """Valores válidos de los campos con catálogo, para elegir en la ficha.
    Una lista vacía (catálogo ilegible) no impide escribir el valor: el
    preview oficial lo valida igual."""
    from atlas_core.direccion_equivalente import _COMUNAS
    opciones: dict[str, list[str]] = {"localidad_entrega": sorted(_COMUNAS)}
    from atlas_core.catalogo_plantas import CatalogoCorruptoError, CatalogoPlantas
    try:
        ruta = ctx.catalogos / "plantas.json"
        opciones["planta_origen_nombre"] = sorted(
            p.nombre for p in (CatalogoPlantas(ruta).listar() if ruta.is_file() else [])
            if p.estado_calidad == "CONFIRMADA" and p.estado_vigencia == "ACTIVA")
    except (OSError, ValueError, CatalogoCorruptoError):
        opciones["planta_origen_nombre"] = []
    try:
        opciones["obra_destino"] = sorted({o.nombre_canonico for o in ctx.catalogo_obras().listar_obras()
                                           if o.estado_vigencia == "ACTIVO" and o.estado not in {"RECHAZADA", "INACTIVA"}})
    except (OSError, ValueError):
        opciones["obra_destino"] = []
    try:
        opciones["chofer"] = sorted({str(r.get("nombre") or "").strip() for r in ctx.choferes().values()
                                     if isinstance(r, dict) and r.get("activo", True) and str(r.get("nombre") or "").strip()})
    except (OSError, ValueError, AttributeError):
        opciones["chofer"] = []
    try:
        from atlas_core.catalogo_clientes import CatalogoClientes
        opciones["cliente"] = sorted({c.razon_social for c in CatalogoClientes(ctx.archivos["clientes"]).listar()
                                      if c.estado_vigencia == "ACTIVO"})
    except (OSError, ValueError):
        opciones["cliente"] = []
    return opciones


def es_lote_ficha(texto: str) -> bool:
    return str(texto or "").lstrip().startswith(MARCADOR)


def codificar_lote(cambios: list[dict]) -> str:
    """Inverso de :func:`decodificar_lote` (Desktop hace lo mismo en JS)."""
    datos = json.dumps({"version": VERSION_LOTE, "cambios": cambios}, ensure_ascii=False).encode("utf-8")
    return MARCADOR + base64.urlsafe_b64encode(datos).decode("ascii")


def decodificar_lote(texto: str) -> list[dict[str, str]]:
    crudo = str(texto or "").strip()[len(MARCADOR):].strip()
    try:
        datos = json.loads(base64.urlsafe_b64decode(crudo + "=" * (-len(crudo) % 4)).decode("utf-8"))
    except (binascii.Error, UnicodeDecodeError, ValueError) as error:
        raise ErrorLoteFicha("El lote de cambios de la ficha no es legible.") from error
    if not isinstance(datos, dict) or datos.get("version") != VERSION_LOTE or not isinstance(datos.get("cambios"), list):
        raise ErrorLoteFicha("El lote de cambios de la ficha no tiene el formato esperado.")
    cambios, vistos = [], set()
    for cambio in datos["cambios"]:
        if not isinstance(cambio, dict):
            raise ErrorLoteFicha("Cada cambio de la ficha debe indicar documento, campo y valor.")
        archivo = str(cambio.get("archivo") or "").strip()
        guia = str(cambio.get("numero_guia") or "").strip()
        campo = str(cambio.get("campo") or "").strip()
        valor = " ".join(str(cambio.get("valor") or "").split())
        if not archivo or len(archivo) > 260 or campo not in CAMPOS_EDITABLES or not valor or len(valor) > 200:
            raise ErrorLoteFicha(f"Cambio inválido en la ficha ({campo or 'sin campo'}).")
        if re.search(r"[\x00-\x1f\x7f]", valor):
            raise ErrorLoteFicha("Un valor de la ficha contiene caracteres de control.")
        if (archivo, campo) in vistos:
            raise ErrorLoteFicha(f"El campo {CAMPOS_EDITABLES[campo]} aparece dos veces para el mismo documento.")
        vistos.add((archivo, campo))
        cambios.append({"archivo": archivo, "numero_guia": guia, "campo": campo, "valor": valor})
    if not cambios:
        raise ErrorLoteFicha("No hay cambios que revisar en la ficha.")
    if len(cambios) > MAXIMO_CAMBIOS:
        raise ErrorLoteFicha(f"Demasiados cambios en un solo lote (máximo {MAXIMO_CAMBIOS}).")
    return cambios


def _valor_visible(valor: object) -> str:
    from atlas_core.ficha_consulta_b1 import ausente
    if isinstance(valor, dict):
        valor = {k: ("" if isinstance(v, str) and ausente(v) else v) for k, v in valor.items()}
        partes = [str(v) for k, v in valor.items() if v not in (None, "") and k in {
            "direccion", "comuna", "obra_destino", "obra", "chofer", "planta_origen", "planta",
            "numero_guia", "numero_transporte", "fecha", "peso_kg", "descripcion_material", "cliente",
            "patente_tracto", "patente_rampla", "hora_entrada_aza", "hora_salida_aza", "nombre"}]
        if partes:
            return " · ".join(partes)
        return " · ".join(str(v) for v in valor.values() if isinstance(v, (str, int, float)) and str(v))
    return "" if valor is None or (isinstance(valor, str) and ausente(valor)) else str(valor)


def traducir_cambios(operador, cambios: list[dict[str, str]]) -> tuple[list[dict], list[dict]]:
    """(acciones, errores). Cada acción: accion, parametros, campos, guia,
    archivo, etiqueta y el valor pedido. Nada se escribe."""
    from atlas_core.b1_operador import resolver_obra, resolver_planta
    ctx = operador.capa._ctx
    filas = ctx.filas()
    por_archivo: dict[str, list[dict]] = {}
    for fila in filas:
        por_archivo.setdefault(str(fila.get("archivo") or ""), []).append(fila)
    acciones: list[dict] = []
    errores: list[dict] = []
    destinos: dict[str, dict] = {}

    def error(cambio, mensaje):
        errores.append({"numero_guia": cambio["numero_guia"], "campo": CAMPOS_EDITABLES[cambio["campo"]],
                        "valor": cambio["valor"], "mensaje": mensaje})

    for cambio in cambios:
        candidatas = por_archivo.get(cambio["archivo"]) or []
        if len(candidatas) != 1:
            error(cambio, "el documento ya no está (o no es único) en la extracción vigente; vuelve a abrir la ficha")
            continue
        fila = candidatas[0]
        guia = str(fila.get("numero_guia") or "").strip()
        if cambio["numero_guia"] and cambio["numero_guia"] != guia:
            error(cambio, f"el folio del documento cambió a {guia}; vuelve a abrir la ficha")
            continue
        base = {"numero_guia": guia, "archivo": cambio["archivo"], "referencia": "Edición integral de la ficha B1"}
        campo, valor = cambio["campo"], cambio["valor"]
        accion = {"guia": guia, "archivo": cambio["archivo"], "campos": [campo], "pedido": {campo: valor}}
        if campo in _CAMPO_DOCUMENTAL:
            if campo in {"patente_tracto", "patente_rampla"}:
                valor = re.sub(r"[\s.\-]", "", valor).upper()
            accion.update(accion="DOCUMENTO_CORREGIR_CAMPO", parametros={**base, "campo": campo, "valor": valor})
        elif campo in {"direccion_entrega", "localidad_entrega"}:
            # Dirección y comuna del mismo documento son UN destino operacional.
            destino = destinos.get(cambio["archivo"])
            if destino is None:
                destino = destinos[cambio["archivo"]] = {
                    "guia": guia, "archivo": cambio["archivo"], "campos": [], "pedido": {},
                    "accion": "DOCUMENTO_CORREGIR_DESTINO_OPERACIONAL", "parametros": {**base}}
                acciones.append(destino)
            destino["campos"].append(campo)
            destino["pedido"][campo] = valor
            destino["parametros"]["direccion" if campo == "direccion_entrega" else "comuna"] = valor
            continue
        elif campo == "obra_destino":
            resolucion = resolver_obra(ctx.catalogo_obras().listar_obras(), valor, "")
            if resolucion["estado"] != "RESUELTO":
                candidatos = "; ".join(c["nombre"] for c in resolucion.get("candidatos") or [])
                error(cambio, (f"«{valor}» coincide con varias obras: {candidatos}" if resolucion["estado"] == "AMBIGUO"
                               else f"«{valor}» no es una obra del catálogo"
                               + (f" (¿{candidatos}?)" if candidatos else "")
                               + "; regístrala primero desde B1 («registra la obra … para el cliente …»)"))
                continue
            accion.update(accion="DOCUMENTO_ASIGNAR_OBRA", parametros={**base, "obra_id": resolucion["obra_id"]})
            accion["pedido"] = {campo: resolucion["nombre"]}
        elif campo == "chofer":
            from atlas_core.b1_operador import resolver_chofer
            resolucion = resolver_chofer(ctx.choferes(), valor, incluir_inactivos=False)
            if resolucion["estado"] != "RESUELTO":
                nombres = "; ".join(str(c.get("nombre")) for c in resolucion.get("candidatos") or [])
                error(cambio, (f"«{valor}» coincide con varios choferes: {nombres}" if nombres
                               else f"«{valor}» no es un chofer activo del catálogo"))
                continue
            accion.update(accion="DOCUMENTO_CORREGIR_CHOFER_OPERACIONAL",
                          parametros={**base, "chofer": resolucion["chofer"]})
            accion["pedido"] = {campo: str(resolucion.get("nombre") or valor)}
        elif campo == "planta_origen_nombre":
            from atlas_core.catalogo_plantas import CatalogoCorruptoError, CatalogoPlantas
            ruta = ctx.catalogos / "plantas.json"
            try:
                plantas = CatalogoPlantas(ruta).listar() if ruta.is_file() else []
            except (OSError, ValueError, CatalogoCorruptoError):
                error(cambio, "el catálogo de plantas no se puede leer; no se corrige el origen")
                continue
            planta = resolver_planta(plantas, valor)
            if planta["estado"] != "RESUELTO":
                listado = "; ".join(c["nombre"] for c in planta.get("candidatos") or [])
                error(cambio, f"«{valor}» no es una planta confirmada única del catálogo"
                              + (f" ({listado})" if listado else ""))
                continue
            accion.update(accion="DOCUMENTO_CORREGIR_PLANTA_ORIGEN", parametros={**base, "planta_id": planta["planta_id"]})
            accion["pedido"] = {campo: planta["nombre"]}
        elif campo == "numero_guia":
            # La persona tiene el original a la vista en la ficha.
            accion.update(accion="DOCUMENTO_CORREGIR_NUMERO_GUIA", parametros={
                **base, "numero_guia_corregido": valor, "confirmado_contra_original": True})
        acciones.append(accion)
    for destino in destinos.values():
        if "comuna" not in destino["parametros"]:
            # Sólo cambió la dirección: se conserva la comuna vigente.
            from atlas_core.destino_operacional import proyectar_destino
            from atlas_core.acciones_operacionales import _leer_json
            fila = por_archivo[destino["archivo"]][0]
            vigente = proyectar_destino(fila, _leer_json(ctx.archivos["ledger_decisiones"], {"aplicaciones": []}))
            comuna = str(vigente.get("localidad_entrega") or "").strip()
            if not comuna:
                errores.append({"numero_guia": destino["guia"], "campo": CAMPOS_EDITABLES["direccion_entrega"],
                                "valor": destino["pedido"]["direccion_entrega"],
                                "mensaje": "la guía no tiene comuna de entrega; indícala junto con la dirección"})
                acciones.remove(destino)
                continue
            destino["parametros"]["comuna"] = comuna
    acciones.sort(key=lambda a: _ORDEN.get(a["campos"][0], _ORDEN["DESTINO"] if a["accion"].endswith("DESTINO_OPERACIONAL") else 0))
    return acciones, errores


def _fila_tabla(item: dict) -> list[str]:
    return [item["guia"] or item["archivo"], " + ".join(CAMPOS_EDITABLES[c] for c in item["campos"]),
            item["antes"] or "(sin dato)", item["despues"]]


def previsualizar_lote(operador, estado: dict, conversacion_id: str, texto: str, *, actor: str, origen: str) -> dict:
    try:
        cambios = decodificar_lote(texto)
    except ErrorLoteFicha as error:
        return {"estado": "RECHAZADA", "accion": "FICHA_EDITAR", "mensaje": f"{error} No se cambió nada."}
    acciones, errores = traducir_cambios(operador, cambios)
    items, sin_cambios = [], []
    for accion in acciones:
        preview = operador.capa.previsualizar(accion["accion"], accion["parametros"], actor=actor, origen=origen,
                                              referencia=accion["parametros"]["referencia"])
        etiqueta = " + ".join(CAMPOS_EDITABLES[c] for c in accion["campos"])
        if preview.get("estado") == "SIN_CAMBIOS":
            sin_cambios.append(f"{accion['guia']} · {etiqueta}")
            continue
        if preview.get("estado") != "PREVIEW":
            errores.append({"numero_guia": accion["guia"], "campo": etiqueta,
                            "valor": " · ".join(accion["pedido"].values()),
                            "mensaje": str(preview.get("mensaje") or preview.get("codigo") or "no se puede preparar")})
            continue
        propuesto = preview.get("valor_propuesto") or {}
        if accion["accion"] == "DOCUMENTO_CORREGIR_CHOFER_OPERACIONAL" and propuesto.get("discrepancia_rut"):
            errores.append({"numero_guia": accion["guia"], "campo": etiqueta, "valor": accion["pedido"]["chofer"],
                            "mensaje": "el RUT impreso contradice al chofer propuesto: corrígelo con lenguaje natural "
                                       "para confirmar la discrepancia de forma explícita"})
            continue
        items.append({"accion": accion["accion"], "parametros": accion["parametros"], "token": preview["token"],
                      "guia": accion["guia"], "archivo": accion["archivo"], "campos": accion["campos"],
                      "antes": _valor_visible(preview.get("valor_actual")),
                      "despues": _valor_visible(propuesto),
                      "consecuencias": list(preview.get("consecuencias") or [])})
    if errores:
        operador._fijar_pendiente(estado, conversacion_id, None)
        filas = [[e["numero_guia"], e["campo"], e["valor"], e["mensaje"]] for e in errores]
        return {"estado": "RECHAZADA", "accion": "FICHA_EDITAR", "codigo": "LOTE_CON_ERRORES",
                "errores": errores,
                "tablas": [{"tipo": "ficha_lote_errores", "resumen": "",
                            "columnas": ["Guía", "Campo", "Valor", "Motivo"], "filas": filas}],
                "mensaje": (f"No preparé ningún cambio: {len(errores)} "
                            f"{'cambio no es válido' if len(errores) == 1 else 'cambios no son válidos'}. "
                            "Corrígelos en la ficha y vuelve a revisar. No se cambió nada.")}
    if not items:
        operador._fijar_pendiente(estado, conversacion_id, None)
        return {"estado": "SIN_CAMBIOS", "accion": "FICHA_EDITAR",
                "mensaje": "Los valores de la ficha ya están así; no hay nada que confirmar."}
    operador._fijar_pendiente(estado, conversacion_id, {
        "accion": "FICHA_EDITAR", "items": items, "referencia": "Edición integral de la ficha B1",
        "creado_en": operador.reloj().isoformat()})
    guias = sorted({i["guia"] for i in items})
    publico = {"tipo": "FICHA_EDITAR", "cambios": [
        {"numero_guia": i["guia"], "archivo": i["archivo"], "campos": i["campos"], "antes": i["antes"],
         "despues": i["despues"], "accion": i["accion"], "consecuencias": i["consecuencias"]} for i in items],
        **({"sin_cambios": sin_cambios} if sin_cambios else {})}
    return {"estado": "PREVIEW_PENDIENTE", "accion": "FICHA_EDITAR", "preview": publico,
            "tablas": [{"tipo": "ficha_lote", "resumen": "",
                        "columnas": ["Guía", "Campo", "Valor anterior", "Valor nuevo"],
                        "filas": [_fila_tabla(i) for i in items]}],
            "mensaje": (f"Revisa {len(items)} {'cambio' if len(items) == 1 else 'cambios'} en "
                        f"{len(guias)} {'guía' if len(guias) == 1 else 'guías'} "
                        "(valor anterior y nuevo). Al confirmar se aplican por el canal oficial, con auditoría, "
                        "y se recalculan el viaje, la ruta y las revisiones afectadas. ¿Confirmas? (sí / no)"
                        + (f" Sin cambios: {', '.join(sin_cambios)}." if sin_cambios else ""))}


def confirmar_lote(operador, estado: dict, conversacion_id: str, pendiente: dict, *, actor: str, origen: str) -> dict:
    resultados, aplicados, detenido = [], 0, None
    for item in pendiente["items"]:
        if detenido is not None:
            resultados.append([item["guia"], " + ".join(CAMPOS_EDITABLES[c] for c in item["campos"]),
                               item["antes"] or "(sin dato)", item["despues"], "No aplicado (lote detenido)"])
            continue
        resultado = operador.capa.ejecutar(item["token"], actor=actor, origen=origen,
                                           confirmado_por=operador.usuario, accion_esperada=item["accion"])
        if resultado.get("estado") == "PREVIEW_OBSOLETO":
            # Otra corrección del lote cambió el mismo documento: sólo se sigue
            # si este cambio es exactamente el que la persona vio.
            nuevo = resultado.get("preview_nuevo") or {}
            if (nuevo.get("estado") == "PREVIEW" and _valor_visible(nuevo.get("valor_actual")) == item["antes"]
                    and _valor_visible(nuevo.get("valor_propuesto")) == item["despues"]):
                resultado = operador.capa.ejecutar(nuevo["token"], actor=actor, origen=origen,
                                                   confirmado_por=operador.usuario, accion_esperada=item["accion"])
        etiqueta = " + ".join(CAMPOS_EDITABLES[c] for c in item["campos"])
        if resultado.get("estado") in {"APLICADA", "SIN_CAMBIOS"}:
            aplicados += resultado.get("estado") == "APLICADA"
            resultados.append([item["guia"], etiqueta, item["antes"] or "(sin dato)", item["despues"],
                               "Aplicado" if resultado.get("estado") == "APLICADA" else "Ya estaba así"])
        else:
            detenido = str(resultado.get("mensaje") or resultado.get("codigo") or resultado.get("estado"))
            resultados.append([item["guia"], etiqueta, item["antes"] or "(sin dato)", item["despues"],
                               f"No aplicado: {detenido}"])
    operador._fijar_pendiente(estado, conversacion_id, None)
    tabla = [{"tipo": "ficha_lote_resultado", "resumen": "",
              "columnas": ["Guía", "Campo", "Valor anterior", "Valor nuevo", "Resultado"], "filas": resultados}]
    total = len(pendiente["items"])
    if detenido is None:
        return {"estado": "EJECUTADA", "accion": "FICHA_EDITAR", "tablas": tabla, "resultado": {"aplicados": aplicados},
                "mensaje": (f"Listo: {aplicados} de {total} {'cambio aplicado' if total == 1 else 'cambios aplicados'} "
                            "y verificados. Quedaron registrados y protegidos; se recalcularon el viaje, la ruta y las "
                            "revisiones afectadas.")}
    return {"estado": "FALLIDA", "accion": "FICHA_EDITAR", "tablas": tabla, "resultado": {"aplicados": aplicados},
            "mensaje": (f"Apliqué {aplicados} de {total} cambios y me detuve: {detenido}. Los aplicados quedan "
                        "registrados; revisa la ficha antes de volver a intentar los demás.")}
