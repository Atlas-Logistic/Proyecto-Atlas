"""Investigación B1 de una revisión, de sólo lectura sobre el estado operacional.

Reutiliza el registro de problemas, sus recolectores y el orquestador B1. El
expediente es una salida separada; esta ruta nunca llama aplicadores ni
regenera dataset, catálogo, ledger o bandeja.
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
import unicodedata
from pathlib import Path

from atlas_core.atlas_ia.contratos import ContextoRazonamiento, EvidenciaIA
from atlas_core.atlas_ia.registro_problemas import REGISTRO_PROBLEMAS_IA, detectar_problemas_elegibles
from atlas_core.almacenamiento_portable import resolver_raiz_atlas


def _normalizar(valor: str) -> str:
    texto = unicodedata.normalize("NFKD", str(valor or "").upper())
    return " ".join(re.findall(r"[A-Z0-9]+", "".join(c for c in texto if not unicodedata.combining(c))))


def _leer_json(ruta: Path) -> dict:
    try:
        return json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _documento_original(raiz: Path, archivo: str) -> Path | None:
    # El resolvedor canónico valida el identificador y resuelve Mobile/entrada.
    from atlas_core.evidencia_documental import resolver_ruta_evidencia

    try:
        ruta = resolver_ruta_evidencia(raiz, archivo).ruta
    except (OSError, ValueError):
        return None
    return ruta if ruta is not None and ruta.is_file() else None


def _lectura_original(raiz: Path, fila: dict, proveedor_ocr=None, *, permitir_ocr_nuevo: bool = True) -> dict:
    archivo = str(fila.get("archivo", ""))
    ruta = _documento_original(raiz, archivo)
    if ruta is None:
        return {"ruta": None, "sha256": None, "lineas": [], "destino_geometrico": "", "error": "ORIGINAL_NO_DISPONIBLE"}
    sha = hashlib.sha256(ruta.read_bytes()).hexdigest()
    trazas = raiz / "operacion" / "trazas_ocr"
    bloques = []
    lineas = []
    fuente = "OCR_NUEVO"
    for candidata in sorted(trazas.glob(f"{fila.get('numero_guia', '')}--*.json")):
        traza = _leer_json(candidata)
        if str(traza.get("imagen", {}).get("referencia", "")) == archivo:
            ocr = traza.get("ocr", {})
            lineas = list(ocr.get("lineas") or [])
            bloques = list(ocr.get("bloques") or [])
            fuente = str(candidata)
            break
    if not bloques and permitir_ocr_nuevo:
        try:
            if proveedor_ocr is None:
                from atlas_core.ocr_provider import crear_proveedor_ocr
                proveedor_ocr = crear_proveedor_ocr()
            leidos = proveedor_ocr.leer_bloques(ruta)
            bloques = list(leidos)
            lineas = [b.texto for b in bloques]
        except Exception as error:
            return {"ruta": str(ruta), "sha256": sha, "lineas": lineas,
                    "destino_geometrico": "", "fuente": fuente, "error": f"OCR_NO_DISPONIBLE:{type(error).__name__}"}
    if not bloques:
        return {"ruta": str(ruta), "sha256": sha, "lineas": lineas,
                "destino_geometrico": "", "fuente": fuente,
                "error": "OCR_NO_REEJECUTADO"}
    from atlas_core.extractor import _extraer_despachar_a_geometrico
    destino = str(_extraer_despachar_a_geometrico(bloques).get("valor", ""))
    if not destino and fuente != "OCR_NUEVO" and permitir_ocr_nuevo:
        # La traza puede conservar una lectura anterior degradada. Una
        # nueva lectura del mismo original es consultiva; no altera OCR.
        try:
            if proveedor_ocr is None:
                from atlas_core.ocr_provider import crear_proveedor_ocr
                proveedor_ocr = crear_proveedor_ocr()
            recientes = list(proveedor_ocr.leer_bloques(ruta))
            nuevo = str(_extraer_despachar_a_geometrico(recientes).get("valor", ""))
            if nuevo:
                destino, fuente = nuevo, "OCR_NUEVO_SOBRE_ORIGINAL"
                lineas = [b.texto for b in recientes]
        except Exception:
            pass
    return {"ruta": str(ruta), "sha256": sha, "lineas": lineas,
            "destino_geometrico": destino, "fuente": fuente, "error": ""}


def _seccion(evidencias: list[dict], tipos: tuple[str, ...]) -> list[dict]:
    return [e for e in evidencias if e["tipo_fuente"] in tipos]


def _evidencia_web_cacheada(contexto: ContextoRazonamiento) -> tuple[EvidenciaIA, ...]:
    """Sólo reutiliza búsquedas reales previas si la consulta nueva falló."""
    from atlas_core.atlas_ia.buscador_web import RepositorioCacheBusquedaWeb
    from atlas_core.atlas_ia.herramientas import herramienta_verificacion_externa

    repositorio = RepositorioCacheBusquedaWeb()

    class SoloCache:
        def buscar(self, consulta):
            resultado = repositorio.buscar(consulta)
            if resultado is None:
                raise LookupError("Consulta no cacheada")
            return resultado

    return herramienta_verificacion_externa(SoloCache()).consultar(contexto)


def _evaluar_propuesta(resultado, documental: str, historicos: list[dict],
                      observado: str = "", motivo: str = "") -> dict:
    """Compuerta de expediente: B1 validado nunca vence el original."""
    contradicciones = [
        {"documento": documental, "evidencia_historica": e["identificador"],
         "valor_historico": e["valor"]}
        for e in historicos
        if documental and _normalizar(e["valor"]) != _normalizar(documental)
    ]
    hipotesis = resultado.hipotesis if resultado else None
    validada = bool(resultado and resultado.estado == "RESUELTO_POR_IA"
                    and resultado.validacion and resultado.validacion.aceptada)
    valor = hipotesis.valor_propuesto if validada and hipotesis else ""
    bloqueada = bool(documental and valor and _normalizar(valor) != _normalizar(documental))
    candidatos = {_normalizar(e["valor"]) for e in historicos if e.get("valor")}
    ambiguedad = bool(not documental and valor and len(candidatos) > 1)
    sin_correccion = bool(valor and "CONTAMINADO" in motivo and
                          _normalizar(valor) == _normalizar(observado))
    propuesta = "" if bloqueada or sin_correccion or ambiguedad else valor
    nivel = ("CONTRADICCION_DOCUMENTAL" if contradicciones or bloqueada else
             "DOCUMENTAL_CONVERGENTE" if documental and propuesta else
             "PROPUESTA_NO_CONFIRMADA" if propuesta else "INSUFICIENTE")
    razon = ("Propuesta histórica contradice DESPACHAR A del original" if bloqueada else
             "Dos o más candidatos históricos razonables sin original resolutivo" if ambiguedad else
             "B1 repitió el valor OCR marcado como contaminado sin corroboración independiente" if sin_correccion else
             "B1 no produjo una propuesta validada; falta corroboración" if not propuesta else "")
    return {"contradicciones": contradicciones, "propuesta": propuesta,
            "nivel": nivel, "razon": razon, "bloqueada": bloqueada,
            "inferencia": hipotesis.a_dict() if hipotesis else None}


def preview_operacional(expediente: dict) -> dict | None:
    """Vista humana mínima de una propuesta B1, sin auditoría interna."""
    propuesta = str(expediente.get("PROPUESTA") or "").strip()
    if not propuesta:
        return None
    campo = str(expediente.get("CAMPO") or "")
    actual = str((expediente.get("HECHOS_DOCUMENTALES") or {}).get("valor_extraido") or "")
    efecto = ("La guía quedará asociada al nombre operacional propuesto tras su confirmación."
              if campo == "obra_destino" else
              "La guía podrá usar esta dirección operacional para su resolución de entrega tras su confirmación.")
    evaluacion = expediente.get("EVALUACION_CANDIDATOS_EXTERNOS") or {}
    return {
        "valor_actual": actual,
        "valor_propuesto": propuesta,
        "evidencia_relevante": str(evaluacion.get("razon") or "Evidencia documental y pública convergente."),
        "consecuencia_operacional": efecto,
    }


def investigar_revision(numero_guia: str, *, raiz_atlas: str | Path | None = None,
                        orquestador=None, proveedor_ocr=None,
                        investigar_externo: bool = True, buscador_externo=None,
                        leer_fuente=None, campos_solicitados: tuple[str, ...] | None = None,
                        permitir_ocr_nuevo: bool = True) -> dict:
    """Devuelve un expediente reproducible, sin escritura productiva.

    El proveedor OCR y el orquestador son inyectables para pruebas. Si B1
    no está configurado, conserva toda la investigación disponible y se
    abstiene con causa explícita.
    """
    raiz = resolver_raiz_atlas(raiz_atlas)
    dataset = raiz / "operacion" / "actual" / "analisis_completo_guias.csv"
    with dataset.open(encoding="utf-8-sig", newline="") as flujo:
        filas = list(csv.DictReader(flujo, delimiter=";"))
    candidatas = [f for f in filas if f.get("numero_guia") == str(numero_guia)]
    if len(candidatas) != 1:
        raise ValueError(f"La guía {numero_guia} tiene {len(candidatas)} filas vigentes")
    fila = candidatas[0]
    # Conserva la firma histórica para inyectores de pruebas ya existentes.
    lectura = (_lectura_original(raiz, fila, proveedor_ocr, permitir_ocr_nuevo=False)
               if not permitir_ocr_nuevo else _lectura_original(raiz, fila, proveedor_ocr))
    from atlas_core.procesamiento_masivo import extraer_descripcion_material
    material_original = extraer_descripcion_material(lectura["lineas"])
    catalogos = raiz / "catalogos_privados"
    # Se reutiliza el constructor productivo de herramientas, pero sólo sus
    # objetos consultables. No se invoca el pipeline que aplica decisiones.
    if orquestador is None:
        from atlas_core.procesamiento_masivo import _crear_orquestador_ia_configurado
        orquestador = _crear_orquestador_ia_configurado(filas=filas, carpeta_catalogos=catalogos)
    investigacion_adaptativa = None
    evaluacion_externa = None
    evaluacion_nombre_obra = None
    if investigar_externo:
        from atlas_core.atlas_ia.candidatos_externos import (
            buscar_adaptativamente, evaluar_candidatos, evaluar_nombre_obra, localidad_documental,
            obtener_texto_fuente,
        )
        if buscador_externo is None:
            from atlas_core.atlas_ia.credenciales import resolver_openrouter_api_key
            if resolver_openrouter_api_key():
                from atlas_core.atlas_ia.buscador_web import (
                    BuscadorWebConCache, BuscadorWebOpenRouter, RepositorioCacheBusquedaWeb,
                )
                buscador_externo = BuscadorWebConCache(BuscadorWebOpenRouter(), RepositorioCacheBusquedaWeb())
        if buscador_externo is not None:
            direccion_base = str(lectura.get("destino_geometrico") or fila.get("despachar_a_crudo") or "")
            localidad = localidad_documental(direccion_base)
            investigacion_adaptativa = buscar_adaptativamente(
                buscador=buscador_externo,
                entidad=str(fila.get("obra_destino") or fila.get("cliente") or ""),
                direccion=direccion_base, localidad=localidad,
                leer_fuente=leer_fuente or obtener_texto_fuente,
            )
            evaluacion_externa = evaluar_candidatos(
                candidatos=investigacion_adaptativa.candidatos,
                obra=str(fila.get("obra_destino") or ""), cliente=str(fila.get("cliente") or ""),
                rut_cliente=str(fila.get("rut_cliente") or ""),
                direccion_documental=direccion_base, localidad=localidad,
            )
            evaluacion_nombre_obra = evaluar_nombre_obra(
                candidatos=investigacion_adaptativa.candidatos,
                obra_documental=str(fila.get("obra_destino") or ""),
            )
    casos = []
    problemas = detectar_problemas_elegibles(fila)
    # Una consulta explícita puede investigar obra o destino aunque la guía
    # no tenga precisamente ese motivo abierto. Reutiliza los mismos tipos
    # registrados y sus recolectores; no crea una ruta ni una regla nueva.
    for campo in campos_solicitados or ():
        if any(tipo.campo == campo for tipo, _ in problemas):
            continue
        tipo = next((entrada for entradas in REGISTRO_PROBLEMAS_IA.values()
                     for entrada in entradas
                     if entrada.campo == campo and entrada.dominio in {"OBRA_DESTINO", "DESTINO"}), None)
        if tipo is not None:
            problemas.append((tipo, "INVESTIGACION_SOLICITADA"))
    for tipo, motivo in problemas:
        if tipo.dominio not in {"OBRA_DESTINO", "DESTINO", "MATERIAL"}:
            continue
        evidencias = list(tipo.recopilar_evidencia(fila, filas, carpeta_catalogos=catalogos))
        documental = str(lectura.get("destino_geometrico") or "") if tipo.dominio == "DESTINO" else ""
        if documental:
            evidencias.append(EvidenciaIA(
                identificador=f"original:{lectura['sha256'][:16]}:despachar_a",
                campo=tipo.campo, valor=documental, tipo_fuente="DOCUMENTAL",
                nivel="LECTURA_GEOMETRICA_ORIGINAL", independencia=1,
                procedencia="atlas_core.extractor._extraer_despachar_a_geometrico",
                referencias_fuente=(str(lectura["ruta"]), f"sha256={lectura['sha256']}"),
            ))
        # El texto OCR íntegro es hecho documental, nunca candidato
        # canónico fabricado. Se entrega aparte para auditar campos ausentes.
        contexto = ContextoRazonamiento(
            campo=tipo.campo, valor_documental=str(fila.get(tipo.campo, "")),
            rut_chofer=str(fila.get("rut_chofer", "")), numero_guia=str(numero_guia),
            numero_transporte=str(fila.get("numero_transporte", "")),
            evidencias=tuple(evidencias), resultado_motor="REQUIERE_REVISION",
            explicacion_motor=motivo, identidad_documento=str(fila.get("archivo", "")),
            identidad_operacional={"obra_destino": str(fila.get("obra_destino", "")),
                                   "cliente": str(fila.get("cliente", "")),
                                   "direccion_entrega": documental or str(fila.get("despachar_a_crudo", ""))},
            herramientas_disponibles=tipo.herramientas,
            restricciones_dominio=("NO_INVENTAR_DATOS", "NO_ESCRIBIR_CATALOGOS", "CONTRASTE_ORIGINAL"),
        )
        # Candidatos verificados llegan al mismo ContextoRazonamiento B1:
        # B1 puede contrastarlos, y el expediente conserva la evaluación
        # estructural aun si el proveedor B1 agota su cuota.
        if investigacion_adaptativa and tipo.dominio in {"OBRA_DESTINO", "DESTINO"}:
            from dataclasses import replace
            externas = tuple(EvidenciaIA(
                identificador="externo:" + hashlib.sha256((c.url + c.direccion + c.numero).encode()).hexdigest()[:16],
                campo=tipo.campo,
                valor=(f"{c.direccion} {c.numero}, {c.comuna}" if tipo.dominio == "DESTINO" else c.nombre),
                tipo_fuente="EXTERNO", nivel="FUENTE_WEB_VERIFICADA",
                independencia=1, procedencia="atlas_ia.candidatos_externos",
                referencias_fuente=(c.url, c.fragmento_fuente, f"consultado_en={c.consultado_en}"),
            ) for c in investigacion_adaptativa.candidatos if c.verificacion == "VERIFICADA" and
                (c.direccion if tipo.dominio == "DESTINO" else c.nombre))
            if not externas and any(t["error"] for t in investigacion_adaptativa.traza):
                consulta_cache = replace(contexto, valor_documental=documental) if documental else contexto
                externas = _evidencia_web_cacheada(consulta_cache)
            contexto = replace(contexto, evidencias=(*contexto.evidencias, *externas))
        resultado = orquestador.resolver(contexto) if orquestador else None
        final = resultado.contexto_final if resultado else contexto
        hechos = [e.a_dict() for e in final.evidencias]
        historicos = _seccion(hechos, ("HISTORICO", "DECISION_HUMANA"))
        confirmados = [e for e in historicos if e.get("es_decision_humana") or
                       "CONFIRMAD" in str(e.get("nivel", "")).upper()]
        observados = [e for e in historicos if e not in confirmados]
        evaluacion = _evaluar_propuesta(resultado, documental, historicos,
                                        str(fila.get(tipo.campo, "")), motivo)
        propuesta_evidencia = ""
        evaluacion_dominio = (evaluacion_nombre_obra if tipo.dominio == "OBRA_DESTINO"
                              else evaluacion_externa)
        if evaluacion_dominio and evaluacion_dominio["estado"] == "PROPUESTA_RESOLUBLE":
            ganador = evaluacion_dominio["propuesta"]
            if tipo.dominio == "DESTINO":
                propuesta_evidencia = ganador["direccion"]
            elif tipo.dominio == "OBRA_DESTINO" and ganador["nombre_candidato"]:
                propuesta_evidencia = ganador["nombre_candidato"]
        propuesta_final = propuesta_evidencia or (evaluacion["propuesta"] if tipo.dominio != "DESTINO" else "")
        nivel_final = "PROPUESTA_RESOLUBLE" if propuesta_evidencia else evaluacion["nivel"]
        razones = [] if propuesta_evidencia else [evaluacion["razon"]]
        if not propuesta_evidencia and tipo.dominio in {"OBRA_DESTINO", "DESTINO"}:
            if evaluacion_dominio:
                razones.append(evaluacion_dominio["razon"])
            if investigacion_adaptativa and any(t["error"] for t in investigacion_adaptativa.traza):
                razones.append("Una búsqueda externa falló; ver BUSQUEDA_ADAPTATIVA")
            if tipo.dominio == "DESTINO" and evaluacion_externa and not evaluacion_externa["numero_documental"]:
                razones.append("El original no aporta número; sólo se propone si fuentes independientes lo publican literalmente")
        if not propuesta_evidencia and tipo.dominio == "MATERIAL" and not material_original:
            razones.append("La extracción de material del OCR original/alternativo no recuperó una descripción exacta")
        casos.append({
            "CAMPO": tipo.campo, "MOTIVO": motivo,
            "HECHOS_DOCUMENTALES": {"valor_extraido": str(fila.get(tipo.campo, "")),
                                     "destino_original": documental,
                                     "material_original_extraido": material_original if tipo.dominio == "MATERIAL" else "",
                                     "ocr_lineas": lectura["lineas"]},
            "HECHOS_ATLAS": _seccion(hechos, ("CATALOGO",)),
            "HISTORIAL_CONFIRMADO": confirmados,
            "HISTORIAL_OBSERVADO": observados,
            "EVIDENCIA_EXTERNA": _seccion(hechos, ("EXTERNO",)),
            "CONTRADICCIONES": evaluacion["contradicciones"],
            "INFERENCIAS": [evaluacion["inferencia"]] if evaluacion["inferencia"] else [],
            "PROPUESTA": propuesta_final,
            "NIVEL_EVIDENCIA": nivel_final,
            "ACCION_RECOMENDADA": "PROPONER_A_HUMANO" if propuesta_evidencia else (
                "REVISAR_ORIGINAL_Y_CONFIRMAR" if evaluacion["bloqueada"] else
                "PROPONER_A_HUMANO" if propuesta_final else "ABSTENERSE"),
            "REQUIERE_CONFIRMACION_HUMANA": True,
            "RAZON_ABSTENCION": "; ".join(r for r in razones if r),
            "EVALUACION_CANDIDATOS_EXTERNOS": evaluacion_dominio if tipo.dominio in {"OBRA_DESTINO", "DESTINO"} else None,
            "RESULTADO_B1": resultado.a_dict() if resultado else None,
        })
        casos[-1]["PREVIEW_OPERACIONAL"] = preview_operacional(casos[-1])
    return {"schema_version": 1, "numero_guia": str(numero_guia),
            "numero_transporte": str(fila.get("numero_transporte", "")),
            "archivo": str(fila.get("archivo", "")), "documento_original": {
                k: v for k, v in lectura.items() if k != "lineas"},
            "expedientes": casos,
            "BUSQUEDA_ADAPTATIVA": investigacion_adaptativa.traza if investigacion_adaptativa else [],
            "escrituras_productivas": 0}
