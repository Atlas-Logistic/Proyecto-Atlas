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
from datetime import date, datetime
from typing import Mapping

from atlas_core.agrupacion_viajes import _clave as _clave_transporte, _valor as _valor_agrupacion
from atlas_core.campos_documentales import CAMPOS_DOCUMENTALES_CONTROLADOS
from atlas_core.catalogo_vehiculos import Vehiculo
from atlas_core.catalogos import normalizar_rut
from atlas_core.chofer_operacional import indice_choferes_operacionales
from atlas_core.credibilidad_campos import NivelCredibilidad, evaluar_credibilidad_direccion
from atlas_core.decisiones_pendientes import _actor_es_humano
from atlas_core.destino_operacional import TIPO, _folios_anteriores, proyectar_destino
from atlas_core.direccion_equivalente import comuna_oficial
from atlas_core.equipo_operacional import (
    ResolutorEquipoOperacional, asignaciones_vigentes_con_fecha, indice_decisiones_humanas_patente,
    indice_errores_documentales_aza, rut_chofer_inequivoco, sustituciones_automaticas_patente,
)
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
class EquipoOperacionalInstantanea:
    """Catálogos que fundamentan la patente operacional por asignación
    vigente, ya leídos y validados por sus lectores oficiales: `vehiculos` =
    `cargar_catalogo_vehiculos(...).vehiculos`; `choferes` = contenido de
    choferes.json (`cargar_catalogo_json`). El ledger es el de la instantánea."""
    vehiculos: tuple[Vehiculo, ...]
    choferes: Mapping[str, object]


@dataclass(frozen=True)
class InstantaneaLote:
    empresa_id: str
    filas: tuple[Mapping[str, object], ...]
    aplicaciones: tuple[Mapping[str, object], ...]
    decisiones: tuple[Mapping[str, object], ...]
    archivos_en_investigacion: frozenset[str]
    # Dependencias de FECHA_EMISION, de la MISMA instantánea. None = no
    # suministrada: bloquea (nunca se asume que no existe). Tupla vacía o
    # catálogos vacíos = verificado que no hay ninguna.
    # `agrupaciones`: entradas de agrupaciones_viaje.json; cada una la
    # confirmó una persona (Atlas no las infiere). Sólo cuentan las ACTIVAS.
    agrupaciones: tuple[Mapping[str, object], ...] | None = None
    equipo: EquipoOperacionalInstantanea | None = None


def _hash(objeto: object) -> str:
    datos = json.dumps(objeto, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(datos.encode("utf-8")).hexdigest()


def _ordenar(items):
    return sorted(items, key=lambda x: json.dumps(x, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


class _ResolutorEquipoInstantanea(ResolutorEquipoOperacional):
    """Mismo resolutor que usa la corrección individual de fecha, construido
    desde la instantánea en vez de leer catálogos y ledger del disco."""

    def __init__(self, equipo: EquipoOperacionalInstantanea, aplicaciones: list[dict]) -> None:  # noqa: D107
        ledger = {"aplicaciones": aplicaciones}
        self._vehiculos = list(equipo.vehiculos)
        self._choferes = dict(equipo.choferes)
        self._operacionales = indice_choferes_operacionales(ledger)
        self._confirmados = indice_errores_documentales_aza(ledger)
        self._decisiones_humanas = indice_decisiones_humanas_patente(ledger)
        self._vigentes = asignaciones_vigentes_con_fecha(self._vehiculos)


def _fecha_dmy(valor: object) -> date | None:
    try:
        return datetime.strptime(str(valor or "").strip(), "%d-%m-%Y").date()
    except ValueError:
        return None


def _desde(vigente) -> date | None:
    try:
        return datetime.fromisoformat(str(vigente[2])).date() if vigente else None
    except (TypeError, ValueError):
        return None


def _dependencias_fecha(fila: Mapping[str, object], nueva: str | None, instantanea: InstantaneaLote,
                        cambiados: set[str], resolutor: _ResolutorEquipoInstantanea | None) -> dict:
    """Protecciones de la corrección individual de fecha
    (`acciones_operacionales._precondiciones_cambio_fecha`) evaluadas sobre la
    instantánea y el lote completo. `motivos` bloquean; `advertencias` no.
    `nueva` es None si la fecha propuesta no es válida (ya bloqueada)."""
    motivos: list[str] = []
    advertencias: list[dict] = []
    dependencias: dict[str, object] = {}
    archivo = str(fila.get("archivo", "")).strip()
    transporte = _clave_transporte(fila.get("numero_transporte"))
    # 1. Agrupación de viaje confirmada por una persona: exige una sola fecha
    #    en todos los documentos de sus transportes. Se evalúa con el lote
    #    completo aplicado; nunca se deshace ni se reinterpreta.
    if instantanea.agrupaciones is None:
        motivos.append("DEPENDENCIA_AUSENTE_AGRUPACIONES")
        dependencias["agrupaciones"] = "NO_SUMINISTRADA"
    else:
        evaluadas = []
        for agrupacion in instantanea.agrupaciones:
            if str(agrupacion.get("estado") or "") != "ACTIVA":
                continue
            transportes = sorted({_clave_transporte(t) for t in agrupacion.get("transportes") or []
                                  if _clave_transporte(t)})
            if not transporte or transporte not in transportes:
                continue
            fechas = set()
            for otra in instantanea.filas:
                if _clave_transporte(otra.get("numero_transporte")) in transportes:
                    cambia = nueva is not None and str(otra.get("archivo", "")).strip() in cambiados
                    valor = nueva if cambia else _valor_agrupacion(dict(otra), "fecha")
                    if valor:
                        fechas.add(valor)
            compatible = nueva is not None and len(fechas) <= 1
            evaluadas.append({"agrupacion_id": str(agrupacion.get("agrupacion_id") or ""), "transportes": transportes,
                              "fechas_resultantes": sorted(fechas), "compatible": compatible})
            if not compatible:
                motivos.append("AGRUPACION_HUMANA_INCOMPATIBLE")
        dependencias["agrupaciones"] = _ordenar(evaluadas)
    # 2. Patente operacional por asignación vigente (tracto y rampla).
    if resolutor is None:
        motivos.append("DEPENDENCIA_AUSENTE_EQUIPO")
        dependencias["equipo_operacional"] = "NO_SUMINISTRADA"
    elif nueva is None:
        dependencias["equipo_operacional"] = "NO_EVALUADA_VALOR_INVALIDO"
    else:
        fecha_nueva = _fecha_dmy(nueva)
        antes = sustituciones_automaticas_patente(dict(fila), resolutor=resolutor)
        fijadas = []
        # Patente que el procesamiento ESCRIBIÓ en la guía por la asignación:
        # el canal no la rehace, así que la nueva fecha debe seguir respaldándola.
        for campo, datos in sorted(antes.items()):
            if datos.get("origen") != "PROCESAMIENTO":
                continue
            desde = _desde(resolutor._vigentes.get(str(datos["valor_operacional"])))
            respaldada = bool(desde and fecha_nueva and fecha_nueva >= desde)
            fijadas.append({"campo": campo, "patente": str(datos["valor_operacional"]),
                            "asignacion_desde": desde.isoformat() if desde else None, "respaldada": respaldada})
            if not respaldada:
                motivos.append("FECHA_ANTERIOR_A_ASIGNACION" if desde else "ASIGNACION_NO_VERIFICABLE")
        # Patente PROYECTADA sobre la impresa: el canal existente la recalcula
        # con la nueva fecha; aquí sólo se informa, nunca se ejecuta.
        proyectadas = {c: d for c, d in antes.items() if d.get("origen") == "PROYECCION"}
        despues = {c: d for c, d in resolutor.discrepancias({**dict(fila), "fecha": nueva}).items()
                   if d.get("fuente") == "ASIGNACION_VIGENTE"}
        recalculo = []
        for campo in sorted(set(proyectadas) | set(despues)):
            previo = str((proyectadas.get(campo) or {}).get("valor_operacional") or "")
            resultante = str((despues.get(campo) or {}).get("valor_operacional") or "")
            if previo != resultante:
                desde = _desde(resolutor._vigentes.get(resultante or previo))
                recalculo.append({"campo": campo, "patente_documental": str(fila.get(campo) or ""),
                                  "operacional_actual": previo or None, "operacional_resultante": resultante or None,
                                  "asignacion_desde": desde.isoformat() if desde else None,
                                  "ejecucion": "PENDIENTE_CANAL_EXISTENTE"})
        dependencias["equipo_operacional"] = {"patentes_fijadas": fijadas, "recalculo_proyectado": recalculo}
    # 3. Otras guías del mismo transporte que el lote no cambia y quedarían
    #    con otra fecha: advertencia (el viaje queda en revisión), no bloqueo.
    if nueva is not None and transporte:
        for otra in instantanea.filas:
            otro_archivo = str(otra.get("archivo", "")).strip()
            fecha_otra = str(otra.get("fecha", "")).strip()
            if (_clave_transporte(otra.get("numero_transporte")) == transporte and otro_archivo != archivo
                    and otro_archivo not in cambiados and _fecha_dmy(fecha_otra) is not None and fecha_otra != nueva):
                advertencias.append({"codigo": "FECHAS_DISTINTAS_EN_TRANSPORTE", "transporte": transporte,
                                     "numero_guia": str(otra.get("numero_guia", "")).strip(), "fecha": fecha_otra})
    return {"motivos": motivos, "advertencias": _ordenar(advertencias), "dependencias": dependencias,
            "estado": _estado_dependencias_fecha(fila, instantanea, resolutor)}


def _estado_dependencias_fecha(fila: Mapping[str, object], instantanea: InstantaneaLote,
                               resolutor: _ResolutorEquipoInstantanea | None) -> dict:
    """Entradas de las que dependen las protecciones de fecha de ESTE
    documento (no el resultado, que depende del lote): agrupaciones de su
    transporte, fechas de los documentos de esos viajes y fundamento de sus
    patentes operacionales. Cambia la huella del documento si cambian."""
    transporte = _clave_transporte(fila.get("numero_transporte"))
    agrupaciones = None
    transportes = {transporte} if transporte else set()
    if instantanea.agrupaciones is not None:
        agrupaciones = _ordenar([dict(a) for a in instantanea.agrupaciones
                                 if transporte and transporte in {_clave_transporte(t) for t in a.get("transportes") or []}])
        for a in agrupaciones:
            transportes |= {_clave_transporte(t) for t in a.get("transportes") or [] if _clave_transporte(t)}
    viaje = sorted({(str(f.get("archivo", "")).strip(), str(f.get("numero_guia", "")).strip(), str(f.get("fecha", "")).strip())
                    for f in instantanea.filas if transportes and _clave_transporte(f.get("numero_transporte")) in transportes})
    equipo = None
    if resolutor is not None:
        rut = rut_chofer_inequivoco(dict(fila), choferes=resolutor._choferes, choferes_operacionales=resolutor._operacionales)
        sustituciones = sustituciones_automaticas_patente(dict(fila), resolutor=resolutor)
        patentes = {str(d.get("valor_operacional") or "") for d in sustituciones.values()}
        equipo = {"rut": rut, "chofer": next((dict(r) for k, r in resolutor._choferes.items()
                                              if rut and isinstance(r, Mapping) and normalizar_rut(k) == rut), None),
                  "sustituciones": sustituciones,
                  "vigentes": {p: list(v) for p, v in sorted(resolutor._vigentes.items()) if p in patentes or (rut and v[0] == rut)}}
    return {"agrupaciones": agrupaciones, "viaje": viaje, "equipo": equipo}


def _equipo_serializable(equipo: EquipoOperacionalInstantanea | None) -> object:
    if equipo is None:
        return None
    return {"vehiculos": _ordenar([v.a_dict() for v in equipo.vehiculos]), "choferes": dict(equipo.choferes)}


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
    if instantanea.agrupaciones is not None and (not isinstance(instantanea.agrupaciones, tuple) or not all(
            isinstance(a, Mapping) for a in instantanea.agrupaciones)):
        raise ValueError("Agrupaciones de la instantánea inválidas")
    if instantanea.equipo is not None and (
            not isinstance(instantanea.equipo, EquipoOperacionalInstantanea)
            or not isinstance(instantanea.equipo.vehiculos, tuple)
            or not all(isinstance(v, Vehiculo) for v in instantanea.equipo.vehiculos)
            or not isinstance(instantanea.equipo.choferes, Mapping)):
        raise ValueError("Equipo operacional de la instantánea inválido")
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
    # Documentos que el lote completo cambiaría (política todo-o-nada): las
    # dependencias de fecha se evalúan con todos ellos ya corregidos.
    cambiados: set[str] = set()
    for guia, archivo, _ in claves:
        unicas = [f for f in instantanea.filas if str(f.get("numero_guia", "")).strip() == guia
                  and (not archivo or str(f.get("archivo", "")).strip() == archivo)]
        if len(unicas) == 1 and str(unicas[0].get("archivo", "")).strip():
            cambiados.add(str(unicas[0]["archivo"]).strip())
    resolutor = (_ResolutorEquipoInstantanea(instantanea.equipo, aplicaciones)
                 if campo == "FECHA_EMISION" and instantanea.equipo is not None else None)
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
        actual, dependencias, huella_estado, advertencias = None, {}, None, []
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
            estado_fecha = None
            if campo == "FECHA_EMISION":
                fecha = _dependencias_fecha(fila, valor if valido else None, instantanea, cambiados, resolutor)
                motivos.extend(fecha["motivos"])
                advertencias = fecha["advertencias"]
                dependencias.update(fecha["dependencias"])
                estado_fecha = fecha["estado"]
            relacionadas = [a for a in aplicaciones if isinstance(a.get("documento"), Mapping) and
                            (str(a["documento"].get("archivo", "")).strip() == archivo_resuelto or
                             str(a["documento"].get("numero_guia", "")).strip() == guia)]
            huella_estado = _hash({"empresa_id": empresa, "fila": fila, "ledger": relacionadas,
                                   "tarjetas": _ordenar(tarjetas), "investigacion": archivo_resuelto in instantanea.archivos_en_investigacion,
                                   **({"dependencias_fecha": estado_fecha} if campo == "FECHA_EMISION" else {})})
            if r.estado_esperado is not None and r.estado_esperado != huella_estado: motivos.append("ESTADO_DIFERENTE")
        if not valido: motivos.append("VALOR_INVALIDO")
        resultado = "BLOQUEADA" if motivos else "SIN_CAMBIOS" if actual == valor and (campo == "FECHA_EMISION" or destino_confirmado) else "CAMBIARIA"
        resultados.append({"empresa_id": empresa, "numero_guia": guia, "archivo_solicitado": archivo or None,
                           "archivo": str(fila["archivo"]).strip() if fila else None,
                           "transporte": str(fila.get("numero_transporte", "")).strip() if fila else None,
                           "campo": campo, "valor_actual": actual, "valor_propuesto": valor,
                           "resultado": resultado, "motivos": sorted(set(motivos)), "advertencias": advertencias,
                           "dependencias": dependencias, "huella_estado": huella_estado, "huella_candidatas": huella_candidatas,
                           "estado_esperado": r.estado_esperado})
    resultados = _ordenar(resultados)
    conteo = {s: sum(x["resultado"] == s for x in resultados) for s in ("CAMBIARIA", "SIN_CAMBIOS", "BLOQUEADA")}
    conteo["CON_ADVERTENCIAS"] = sum(bool(x["advertencias"]) for x in resultados)
    estado = "NO_APLICABLE" if conteo["BLOQUEADA"] else "SIN_CAMBIOS" if not conteo["CAMBIARIA"] else "PREVIEW"
    plan = {"version": 2, "operacion_id": solicitud.operacion_id.strip(), "empresa_id": solicitud.empresa_id,
            "tipo_entidad": solicitud.tipo_entidad, "campo": campo, "valor_propuesto": valor,
            "huella_instantanea": _hash({"filas": _ordenar([dict(f) for f in instantanea.filas]),
                                        "ledger": aplicaciones, "decisiones": _ordenar([dict(d) for d in instantanea.decisiones]),
                                        "investigacion": sorted(instantanea.archivos_en_investigacion),
                                        "agrupaciones": None if instantanea.agrupaciones is None
                                        else _ordenar([dict(a) for a in instantanea.agrupaciones]),
                                        "equipo": _equipo_serializable(instantanea.equipo)}),
            "documentos": resultados, "resumen": {"total": len(resultados), **conteo}, "estado": estado}
    return {**plan, "huella_plan": _hash(plan), "autoriza_escritura": False}
