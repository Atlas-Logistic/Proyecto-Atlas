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
from atlas_core.atlas_ia.registro_problemas import detectar_problemas_elegibles
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


def _lectura_original(raiz: Path, fila: dict, proveedor_ocr=None) -> dict:
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
    if not bloques:
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
    from atlas_core.extractor import _extraer_despachar_a_geometrico
    destino = str(_extraer_despachar_a_geometrico(bloques).get("valor", ""))
    if not destino and fuente != "OCR_NUEVO":
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


def investigar_revision(numero_guia: str, *, raiz_atlas: str | Path | None = None,
                        orquestador=None, proveedor_ocr=None,
                        investigar_externo: bool = True) -> dict:
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
    lectura = _lectura_original(raiz, fila, proveedor_ocr)
    catalogos = raiz / "catalogos_privados"
    # Se reutiliza el constructor productivo de herramientas, pero sólo sus
    # objetos consultables. No se invoca el pipeline que aplica decisiones.
    if orquestador is None:
        from atlas_core.procesamiento_masivo import _crear_orquestador_ia_configurado
        orquestador = _crear_orquestador_ia_configurado(filas=filas, carpeta_catalogos=catalogos)
    casos = []
    for tipo, motivo in detectar_problemas_elegibles(fila):
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
        # En investigación explícita se consulta la misma herramienta web
        # existente antes de B1: así un fallo/cuota del razonador no oculta
        # fuentes externas disponibles. Sólo escribe la caché de búsqueda.
        if investigar_externo and orquestador is not None and tipo.dominio in {"OBRA_DESTINO", "DESTINO"}:
            from dataclasses import replace
            from atlas_core.procesamiento_masivo import _herramientas_b1_disponibles
            herramienta = _herramientas_b1_disponibles(filas=filas, carpeta_catalogos=catalogos).get("VERIFICACION_EXTERNA")
            if herramienta is not None:
                consulta = replace(contexto, valor_documental=documental) if documental else contexto
                externas = herramienta.consultar(consulta)
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
        casos.append({
            "CAMPO": tipo.campo, "MOTIVO": motivo,
            "HECHOS_DOCUMENTALES": {"valor_extraido": str(fila.get(tipo.campo, "")),
                                     "destino_original": documental, "ocr_lineas": lectura["lineas"]},
            "HECHOS_ATLAS": _seccion(hechos, ("CATALOGO",)),
            "HISTORIAL_CONFIRMADO": confirmados,
            "HISTORIAL_OBSERVADO": observados,
            "EVIDENCIA_EXTERNA": _seccion(hechos, ("EXTERNO",)),
            "CONTRADICCIONES": evaluacion["contradicciones"],
            "INFERENCIAS": [evaluacion["inferencia"]] if evaluacion["inferencia"] else [],
            "PROPUESTA": evaluacion["propuesta"],
            "NIVEL_EVIDENCIA": evaluacion["nivel"],
            "ACCION_RECOMENDADA": "REVISAR_ORIGINAL_Y_CONFIRMAR" if evaluacion["bloqueada"] else (
                "PROPONER_A_HUMANO" if evaluacion["propuesta"] else "ABSTENERSE"),
            "REQUIERE_CONFIRMACION_HUMANA": True,
            "RAZON_ABSTENCION": evaluacion["razon"],
            "RESULTADO_B1": resultado.a_dict() if resultado else None,
        })
    return {"schema_version": 1, "numero_guia": str(numero_guia),
            "numero_transporte": str(fila.get("numero_transporte", "")),
            "archivo": str(fila.get("archivo", "")), "documento_original": {
                k: v for k, v in lectura.items() if k != "lineas"},
            "expedientes": casos, "escrituras_productivas": 0}
