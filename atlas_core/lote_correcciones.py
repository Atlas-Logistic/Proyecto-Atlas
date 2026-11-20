"""Contrato y preview puro de correcciones; no autoriza ni ejecuta escrituras.

El llamador debe suministrar una instantánea completa y coherente de UNA empresa,
con ledger, bandeja y archivos en investigación ya verificados por sus canales
oficiales. No abrir archivos aquí ni interpretar la ausencia de datos como éxito.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Mapping

from atlas_core.campos_documentales import CAMPOS_DOCUMENTALES_CONTROLADOS
from atlas_core.credibilidad_campos import NivelCredibilidad, evaluar_credibilidad_direccion
from atlas_core.decisiones_pendientes import _actor_es_humano
from atlas_core.destino_operacional import TIPO, _folios_anteriores, proyectar_destino
from atlas_core.direccion_equivalente import comuna_oficial
from atlas_core.revalidacion_documental import _hay_decision_humana_para_campo
from atlas_core.reprocesamiento_reparador import _resolver_fila_por_archivo


@dataclass(frozen=True)
class ReferenciaDocumento:
    numero_guia: str
    archivo: str | None = None
    empresa_id: str | None = None
    estado_esperado: str | None = None


@dataclass(frozen=True)
class DestinoOperacional:
    direccion: str
    comuna: str


@dataclass(frozen=True)
class SolicitudLote:
    operacion_id: str
    empresa_id: str
    campo: str
    valor: str | DestinoOperacional
    documentos: tuple[ReferenciaDocumento, ...]
    tipo_entidad: str = "DOCUMENTO"


@dataclass(frozen=True)
class InstantaneaLote:
    empresa_id: str
    filas: tuple[Mapping[str, object], ...]
    aplicaciones: tuple[Mapping[str, object], ...]
    decisiones: tuple[Mapping[str, object], ...]
    archivos_en_investigacion: frozenset[str]


def _hash(objeto: object) -> str:
    datos = json.dumps(objeto, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(datos.encode("utf-8")).hexdigest()


def _ordenar(items):
    return sorted(items, key=lambda x: json.dumps(x, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def previsualizar_lote(solicitud: SolicitudLote, instantanea: InstantaneaLote) -> dict:
    """Devuelve plan completo determinista; no produce token ni modifica entradas."""
    if not isinstance(solicitud, SolicitudLote) or not isinstance(instantanea, InstantaneaLote):
        raise TypeError("Se requieren SolicitudLote e InstantaneaLote")
    if (not isinstance(solicitud.operacion_id, str) or not solicitud.operacion_id.strip()
            or not isinstance(solicitud.empresa_id, str) or not solicitud.empresa_id.strip()
            or solicitud.tipo_entidad != "DOCUMENTO" or not solicitud.documentos
            or solicitud.campo not in {"FECHA_EMISION", "DESTINO_OPERACIONAL"}):
        raise ValueError("Contrato de lote inválido")
    if solicitud.empresa_id != instantanea.empresa_id:
        raise ValueError("EMPRESA_DISTINTA_DE_INSTANTANEA")
    if not all(isinstance(r, ReferenciaDocumento) for r in solicitud.documentos):
        raise ValueError("Referencia documental inválida")
    campo = solicitud.campo
    if campo == "FECHA_EMISION":
        valor = solicitud.valor.strip() if isinstance(solicitud.valor, str) else ""
        valido = bool(valor and CAMPOS_DOCUMENTALES_CONTROLADOS["fecha"](valor))
    else:
        d = solicitud.valor
        direccion = d.direccion.strip() if isinstance(d, DestinoOperacional) and isinstance(d.direccion, str) else ""
        comuna = comuna_oficial(d.comuna) if isinstance(d, DestinoOperacional) and isinstance(d.comuna, str) else ""
        valor = {"direccion": direccion, "comuna": comuna or (d.comuna.strip() if isinstance(d, DestinoOperacional) and isinstance(d.comuna, str) else "")}
        valido = bool(comuna and evaluar_credibilidad_direccion(direccion).nivel == NivelCredibilidad.CONFIABLE)
    aplicaciones = [dict(a) for a in instantanea.aplicaciones]
    protegidas = [a for a in aplicaciones if a.get("tipo") != "CORRECCION_DOCUMENTAL_OPERADOR"
                  and _actor_es_humano(a.get("actor"))]
    ledger = {"aplicaciones": aplicaciones}
    refs = list(solicitud.documentos)
    claves = [(str(r.numero_guia).strip(), str(r.archivo or "").strip(), str(r.empresa_id or solicitud.empresa_id).strip()) for r in refs]
    conteos = {g: sum(1 for x in claves if x[0] == g) for g, _, _ in claves}
    resultados = []
    for r, (guia, archivo, empresa) in zip(refs, claves):
        motivos = []
        if not re.fullmatch(r"\d{3,12}", guia): motivos.append("GUIA_INVALIDA")
        if empresa != solicitud.empresa_id: motivos.append("EMPRESA_DISTINTA")
        if conteos[guia] > 1:
            motivos.append("GUIA_DUPLICADA" if len({x for x in claves if x[0] == guia}) == 1 else "REFERENCIAS_CONTRADICTORIAS")
        candidatas = [f for f in instantanea.filas if str(f.get("numero_guia", "")).strip() == guia]
        if archivo:
            candidatas = [f for f in candidatas if str(f.get("archivo", "")).strip() == archivo]
        if not candidatas: motivos.append("DOCUMENTO_NO_ENCONTRADO")
        elif len(candidatas) != 1 or not str(candidatas[0].get("archivo", "")).strip(): motivos.append("DOCUMENTO_AMBIGUO")
        fila = dict(candidatas[0]) if len(candidatas) == 1 and str(candidatas[0].get("archivo", "")).strip() else None
        huella_candidatas = _hash(_ordenar([dict(f) for f in candidatas]))
        actual, dependencias, huella_estado = None, {}, None
        destino_confirmado = False
        if fila:
            archivo_resuelto = str(fila["archivo"]).strip()
            resuelta, _ = _resolver_fila_por_archivo([dict(f) for f in instantanea.filas], archivo_resuelto, numero_guia=guia)
            if resuelta is None:
                motivos.append("DOCUMENTO_AMBIGUO")
            if fila.get("empresa_id") and str(fila["empresa_id"]).strip() != solicitud.empresa_id:
                motivos.append("EMPRESA_DISTINTA")
            if archivo_resuelto in instantanea.archivos_en_investigacion: motivos.append("EN_INVESTIGACION")
            campos = ("fecha",) if campo == "FECHA_EMISION" else ("direccion_entrega", "localidad_entrega")
            if any(_hay_decision_humana_para_campo(protegidas, fila=fila, campo=c) for c in campos):
                motivos.append("CAMPO_PROTEGIDO")
            proyectada = proyectar_destino(fila, ledger) if campo == "DESTINO_OPERACIONAL" else fila
            if campo == "DESTINO_OPERACIONAL":
                for entrada, folios in _folios_anteriores(fila, aplicaciones):
                    doc = entrada.get("documento") if isinstance(entrada, Mapping) else None
                    destino = entrada.get("destino_operacional") if isinstance(entrada, Mapping) else None
                    if (entrada.get("tipo") == TIPO and isinstance(doc, Mapping) and isinstance(destino, Mapping)
                            and str(doc.get("archivo") or "").strip() == archivo_resuelto
                            and str(doc.get("numero_guia") or "").strip() in folios
                            and (str(doc.get("numero_guia") or "").strip() == guia or
                                 str(doc.get("numero_transporte") or "").strip() == str(fila.get("numero_transporte") or "").strip())
                            and destino.get("direccion") and destino.get("comuna")):
                        destino_confirmado = True
                        break
            actual = (str(fila.get("fecha", "")).strip() if campo == "FECHA_EMISION" else
                      {"direccion": str(proyectada.get("direccion_entrega") or fila.get("despachar_a_crudo") or "").strip(),
                       "comuna": comuna_oficial(str(proyectada.get("localidad_entrega") or "")) or str(proyectada.get("localidad_entrega") or "").strip()})
            tarjetas = [dict(x) for x in instantanea.decisiones if isinstance(x.get("documento"), Mapping)
                        and str(x["documento"].get("archivo", "")).strip() == archivo_resuelto]
            dependencias = {"transporte": str(fila.get("numero_transporte", "")).strip(), "tarjetas": _ordenar(tarjetas),
                            "reconciliacion": "PENDIENTE_EVALUACION", "reporte": "PENDIENTE_EVALUACION"}
            if campo == "DESTINO_OPERACIONAL":
                dependencias.update(destino_operacional_confirmado=destino_confirmado, destino_documental=str(fila.get("despachar_a_crudo") or ""),
                                    ruta_y_coordenadas="PENDIENTE_EVALUACION")
            relacionadas = [a for a in aplicaciones if isinstance(a.get("documento"), Mapping) and
                            (str(a["documento"].get("archivo", "")).strip() == archivo_resuelto or
                             str(a["documento"].get("numero_guia", "")).strip() == guia)]
            huella_estado = _hash({"empresa_id": empresa, "fila": fila, "ledger": relacionadas,
                                   "tarjetas": _ordenar(tarjetas), "investigacion": archivo_resuelto in instantanea.archivos_en_investigacion})
            if r.estado_esperado is not None and r.estado_esperado != huella_estado: motivos.append("ESTADO_DIFERENTE")
        if not valido: motivos.append("VALOR_INVALIDO")
        resultado = "BLOQUEADA" if motivos else "SIN_CAMBIOS" if actual == valor and (campo == "FECHA_EMISION" or destino_confirmado) else "CAMBIARIA"
        resultados.append({"empresa_id": empresa, "numero_guia": guia, "archivo_solicitado": archivo or None,
                           "archivo": str(fila["archivo"]).strip() if fila else None,
                           "transporte": str(fila.get("numero_transporte", "")).strip() if fila else None,
                           "campo": campo, "valor_actual": actual, "valor_propuesto": valor,
                           "resultado": resultado, "motivos": sorted(set(motivos)),
                           "dependencias": dependencias, "huella_estado": huella_estado, "huella_candidatas": huella_candidatas,
                           "estado_esperado": r.estado_esperado})
    resultados = _ordenar(resultados)
    conteo = {s: sum(x["resultado"] == s for x in resultados) for s in ("CAMBIARIA", "SIN_CAMBIOS", "BLOQUEADA")}
    estado = "NO_APLICABLE" if conteo["BLOQUEADA"] else "SIN_CAMBIOS" if not conteo["CAMBIARIA"] else "PREVIEW"
    plan = {"version": 1, "operacion_id": solicitud.operacion_id.strip(), "empresa_id": solicitud.empresa_id,
            "tipo_entidad": solicitud.tipo_entidad, "campo": campo, "valor_propuesto": valor,
            "huella_instantanea": _hash({"filas": _ordenar([dict(f) for f in instantanea.filas]),
                                        "ledger": aplicaciones, "decisiones": _ordenar([dict(d) for d in instantanea.decisiones]),
                                        "investigacion": sorted(instantanea.archivos_en_investigacion)}),
            "documentos": resultados, "resumen": {"total": len(resultados), **conteo}, "estado": estado}
    return {**plan, "huella_plan": _hash(plan), "autoriza_escritura": False}
