"""Equipo OPERACIONAL (tracto/rampla) de una guía frente a lo impreso por AZA.

Dos fuentes, en este orden, siempre por documento (`archivo`) y nunca
propagadas a guías hermanas:

1. Error documental AZA confirmado por el administrador: entrada
   `ERROR_DOCUMENTAL_AZA` del ledger `decisiones_aplicadas.json`
   (append-only, la última por documento gana) con, por campo, el valor
   impreso y el operacional confirmado. Vale mientras la lectura vigente
   siga siendo la registrada; persiste frente a OCR, PULL y revalidación.
2. Regla general (`equipo_por_asignacion_vigente`, P0 patentes por
   asignación vigente 17/11/2026): chofer identificado de forma inequívoca +
   exactamente una asignación vigente confirmada por un humano para el rol
   del campo (tracto/camión rígido o rampla), desde una fecha no posterior a
   la de la guía. Si la guía muestra otra patente (conocida o no por el
   catálogo) o no muestra ninguna, el valor operacional es la patente
   asignada; el motivo queda registrado (`MOTIVO_*`). Se abstiene ante
   identidad ambigua o contradictoria, asignación variable o múltiple del
   rol, asignación posterior a la guía (nunca se infiere hacia atrás) o una
   decisión humana sobre ese campo de ese documento (siempre prevalece).

El dataset documental nunca se modifica aquí: la patente impresa (o su
ausencia) queda tal cual y el valor operacional se aplica en reporte,
revalidación y tarjetas. Cada sustitución automática queda visible como
incidencia `PATENTE_CORREGIDA_POR_ASIGNACION` (leída, aplicada, motivo).
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime
from pathlib import Path
from typing import Iterable, Mapping

TIPO_LEDGER_ERROR_DOCUMENTAL_AZA = "ERROR_DOCUMENTAL_AZA"
TIPO_INCIDENCIA_ERROR_DOCUMENTAL_AZA = "ERROR_DOCUMENTAL_AZA"
CAMPOS_EQUIPO = {"patente_tracto": "TRACTO", "patente_rampla": "CARRO"}
# Rol operacional de cada campo: el campo tracto también lleva un camión
# rígido (sin rampla). Un chofer con tracto Y camión rígido vigentes es
# ambiguo para ese campo y se abstiene.
TIPOS_POR_CAMPO = {"patente_tracto": ("TRACTO", "CAMION_RIGIDO"), "patente_rampla": ("CARRO",)}
TIPO_INCIDENCIA_PATENTE_POR_ASIGNACION = "PATENTE_CORREGIDA_POR_ASIGNACION"
FUENTE_ASIGNACION_VIGENTE = "ASIGNACION_VIGENTE_CONFIRMADA"
MOTIVO_PATENTE_AUSENTE = "PATENTE_AUSENTE"
MOTIVO_PATENTE_DISTINTA = "PATENTE_DISTINTA"
MOTIVO_LECTURA_OCR_CERCANA = "LECTURA_OCR_CERCANA"
MOTIVO_UBICACION_INTERCAMBIADA = "PATENTE_EN_CAMPO_INTERCAMBIADO"
# Tipos del ledger cuyo `campo` patente fija, por decisión humana, el valor
# de ese documento: la regla automática nunca lo contradice.
_TIPOS_DECISION_PATENTE = frozenset({"VEHICULO_DESCONOCIDO", "CORRECCION_DOCUMENTAL_OPERADOR"})
# Distancia de edición desde la que una patente impresa distinta deja de
# parecer ruido OCR: sólo entonces es una discrepancia documental.
DISTANCIA_MINIMA_DISCREPANCIA_DOCUMENTAL = 3
_PATENTE_CHILENA = re.compile(r"^(?:[A-Z]{2}\d{4}|[A-Z]{4}\d{2})$")
_AUSENTES = {"", "NOENCONTRADO", "NOENCONTRADA", "REVISAR", "ILEGIBLE"}


def _patente(valor: object) -> str:
    texto = re.sub(r"[\s.\-]", "", str(valor or "")).upper()
    return "" if texto in _AUSENTES else texto


def _fecha_guia(fila: Mapping[str, object]) -> date | None:
    texto = str(fila.get("fecha", "")).strip()
    for formato in ("%d-%m-%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(texto, formato).date()
        except ValueError:
            continue
    return None


# ------------------------------------------------------------------ ledger


def indice_errores_documentales_aza(ledger: Mapping[str, object]) -> dict[str, dict[str, dict[str, str]]]:
    """``archivo`` -> ``{campo: {valor_documental, valor_operacional}}`` de la
    última confirmación del administrador. Entradas incompletas se ignoran."""
    indice: dict[str, dict[str, dict[str, str]]] = {}
    aplicaciones = ledger.get("aplicaciones") if isinstance(ledger, Mapping) else None
    for aplicacion in aplicaciones if isinstance(aplicaciones, list) else []:
        if not isinstance(aplicacion, Mapping) or aplicacion.get("tipo") != TIPO_LEDGER_ERROR_DOCUMENTAL_AZA:
            continue
        archivo = str((aplicacion.get("documento") or {}).get("archivo", "")).strip()
        campos: dict[str, dict[str, str]] = {}
        for discrepancia in aplicacion.get("discrepancias") or []:
            if not isinstance(discrepancia, Mapping):
                continue
            campo = str(discrepancia.get("campo", ""))
            operacional = str(discrepancia.get("valor_operacional", "")).strip()
            if campo and operacional:
                campos[campo] = {"valor_documental": str(discrepancia.get("valor_documental", "")).strip(),
                                 "valor_operacional": operacional}
        if archivo and campos:
            indice[archivo] = campos
    return indice


def errores_documentales_aza_por_ledger(ruta_ledger: str | Path) -> dict[str, dict[str, dict[str, str]]]:
    try:
        ledger = json.loads(Path(ruta_ledger).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}
    return indice_errores_documentales_aza(ledger)


def _es_humano(aplicacion: Mapping[str, object]) -> bool:
    from atlas_core.decisiones_pendientes import _actor_es_humano

    actor = str(aplicacion.get("actor") or "").strip()
    confirmante = str(aplicacion.get("confirmado_por") or "").strip()
    return bool(actor and _actor_es_humano(actor)) or bool(confirmante and _actor_es_humano(confirmante))


def indice_decisiones_humanas_patente(ledger: Mapping[str, object]) -> set[tuple[str, str, str]]:
    """``{("ARCHIVO"|"GUIA", identificador, campo)}`` con una decisión humana
    sobre esa patente de ese documento (corrección de campo, elección o
    registro de vehículo, error documental AZA). Una decisión automática
    (ATLAS_*, B1 sin confirmación humana) no cuenta. Una entrada antigua sin
    `archivo` se identifica por número de guía."""
    indice: set[tuple[str, str, str]] = set()
    aplicaciones = ledger.get("aplicaciones") if isinstance(ledger, Mapping) else None
    for aplicacion in aplicaciones if isinstance(aplicaciones, list) else []:
        if not isinstance(aplicacion, Mapping) or not _es_humano(aplicacion):
            continue
        documento = aplicacion.get("documento") if isinstance(aplicacion.get("documento"), Mapping) else {}
        tipo = str(aplicacion.get("tipo") or "")
        if tipo == TIPO_LEDGER_ERROR_DOCUMENTAL_AZA:
            campos = {str(d.get("campo", "")) for d in aplicacion.get("discrepancias") or [] if isinstance(d, Mapping)}
        elif tipo in _TIPOS_DECISION_PATENTE:
            campos = {str(aplicacion.get("campo") or "")}
        else:
            continue
        archivo = str(documento.get("archivo") or "").strip()
        guia = str(documento.get("numero_guia") or "").strip()
        for campo in campos & set(CAMPOS_EQUIPO):
            if archivo:
                indice.add(("ARCHIVO", archivo, campo))
            elif guia:
                indice.add(("GUIA", guia, campo))
    return indice


def _decision_humana_sobre(indice: set[tuple[str, str, str]], fila: Mapping[str, object], campo: str) -> bool:
    return (("ARCHIVO", str(fila.get("archivo", "")).strip(), campo) in indice
            or ("GUIA", str(fila.get("numero_guia", "")).strip(), campo) in indice)


def motivo_sustitucion(documental: str, aplicada: str, *, otras_asignadas: Iterable[str] = ()) -> str:
    """Motivo legible de una sustitución automática (leída -> aplicada)."""
    from atlas_core.decisiones_pendientes import _distancia_edicion_patente

    leida = _patente(documental)
    if not leida:
        return MOTIVO_PATENTE_AUSENTE
    if leida in set(otras_asignadas):
        return MOTIVO_UBICACION_INTERCAMBIADA
    if _distancia_edicion_patente(leida, _patente(aplicada)) < DISTANCIA_MINIMA_DISCREPANCIA_DOCUMENTAL:
        return MOTIVO_LECTURA_OCR_CERCANA
    return MOTIVO_PATENTE_DISTINTA


# ------------------------------------------------------------------ regla general


def asignaciones_vigentes_con_fecha(vehiculos: Iterable[object]) -> dict[str, tuple[str, str, str]]:
    """``{patente: (rut_normalizado, tipo, fecha_iso)}`` -- misma fuente y
    regla que `decisiones_pendientes._asignaciones_vigentes`, conservando la
    fecha de la asignación vigente."""
    from atlas_core.catalogos import normalizar_rut

    vigentes: dict[str, tuple[str, str, str]] = {}
    for v in vehiculos:
        if v.estado_calidad != "CONFIRMADO" or v.estado_vigencia != "ACTIVO":
            continue
        asignaciones = [
            (str(e.fecha), normalizar_rut(str(e.campos_observados.get("rut_chofer_asociado", ""))))
            for e in v.evidencias
            if e.tipo == "CONFIRMACION_HUMANA" and str(e.campos_observados.get("rut_chofer_asociado", "")).strip()
        ]
        if asignaciones:
            fecha, rut = max(asignaciones)
            vigentes[v.patente_canonica] = (rut, v.tipo, fecha)
    return vigentes


def rut_chofer_inequivoco(
    fila: Mapping[str, object], *, choferes: Mapping[str, object],
    choferes_operacionales: Mapping[str, Mapping[str, str]],
) -> str:
    """RUT normalizado del chofer de ESTA fila, o "" si no es inequívoco:
    chofer operacional fijado por un humano, o nombre y RUT impresos que
    corroboran la misma identidad activa del catálogo."""
    from atlas_core.catalogos import corroborar_chofer_por_nombre_y_rut_documental, normalizar_rut

    correccion = choferes_operacionales.get(str(fila.get("archivo", "")).strip())
    if correccion:
        return normalizar_rut(str(correccion.get("rut", "")))
    nombre = str(fila.get("chofer", "")).strip()
    if not nombre or nombre.upper() == "NO ENCONTRADO":
        return ""
    corroborado = corroborar_chofer_por_nombre_y_rut_documental(
        choferes, nombre, str(fila.get("rut_chofer", "")).strip())
    return normalizar_rut(corroborado[1]) if corroborado else ""


def equipo_por_asignacion_vigente(
    fila: Mapping[str, object], *, choferes: Mapping[str, object], vehiculos: Iterable[object],
    choferes_operacionales: Mapping[str, Mapping[str, str]],
    vigentes: Mapping[str, tuple[str, str, str]] | None = None,
    decisiones_humanas: set[tuple[str, str, str]] | None = None,
) -> dict[str, dict[str, str]]:
    """``{campo: {valor_documental, valor_operacional, motivo}}`` para cada
    campo cuya patente impresa (o su ausencia, ``valor_documental`` "")
    difiere de la asignación vigente única del chofer para ese rol."""
    from atlas_core.catalogos import normalizar_rut
    from atlas_core.convergencia_identidad_conocida import FLAG_ASIGNACION_VARIABLE

    rut = rut_chofer_inequivoco(fila, choferes=choferes, choferes_operacionales=choferes_operacionales)
    if not rut:
        return {}
    registro = next((r for k, r in choferes.items() if isinstance(r, Mapping) and normalizar_rut(k) == rut), None)
    if isinstance(registro, Mapping) and registro.get(FLAG_ASIGNACION_VARIABLE):
        return {}
    vehiculos = list(vehiculos)
    vigentes = vigentes if vigentes is not None else asignaciones_vigentes_con_fecha(vehiculos)
    fecha_guia = _fecha_guia(fila)
    if fecha_guia is None:
        return {}
    asignadas_rut = {p: (t, f) for p, (r, t, f) in vigentes.items() if r == rut}
    resultado: dict[str, dict[str, str]] = {}
    for campo, tipos in TIPOS_POR_CAMPO.items():
        if decisiones_humanas and _decision_humana_sobre(decisiones_humanas, fila, campo):
            continue  # una decisión humana sobre esta patente siempre prevalece
        propias = [(p, f) for p, (t, f) in asignadas_rut.items() if t in tipos]
        if len(propias) != 1:
            continue  # sin asignación del rol o ambigua: nunca se elige
        canonica, fecha_asignacion = propias[0]
        if fecha_guia < datetime.fromisoformat(fecha_asignacion).date():
            continue  # la asignación vigente es posterior a la guía: no se infiere hacia atrás
        documental = _patente(fila.get(campo))
        if documental == canonica:
            continue
        resultado[campo] = {
            "valor_documental": documental, "valor_operacional": canonica,
            "motivo": motivo_sustitucion(documental, canonica, otras_asignadas=set(asignadas_rut) - {canonica}),
        }
    return resultado


class ResolutorEquipoOperacional:
    """Valor operacional por (archivo, campo, valor documental): primero la
    confirmación del administrador, luego la regla general. Carga catálogos
    y ledger una vez por operación (reporte, revalidación, bandeja)."""

    def __init__(self, *, carpeta_catalogos: str | Path, ruta_ledger: str | Path) -> None:
        from atlas_core.catalogo_vehiculos import cargar_catalogo_vehiculos
        from atlas_core.catalogos import cargar_catalogo_json
        from atlas_core.chofer_operacional import choferes_operacionales_por_ledger

        carpeta = Path(carpeta_catalogos)
        try:
            self._vehiculos = list(cargar_catalogo_vehiculos(carpeta / "vehiculos.json").vehiculos)
        except Exception:  # noqa: BLE001 -- sin catálogo legible no hay regla general
            self._vehiculos = []
        try:
            self._choferes = cargar_catalogo_json(carpeta / "choferes.json")
        except (OSError, ValueError):
            self._choferes = {}
        self._operacionales = choferes_operacionales_por_ledger(ruta_ledger)
        try:
            ledger = json.loads(Path(ruta_ledger).read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            ledger = {}
        self._confirmados = indice_errores_documentales_aza(ledger)
        self._decisiones_humanas = indice_decisiones_humanas_patente(ledger)
        self._vigentes = asignaciones_vigentes_con_fecha(self._vehiculos)

    def discrepancias(self, fila: Mapping[str, object]) -> dict[str, dict[str, str]]:
        """Campos con valor operacional distinto del impreso, con su fuente."""
        archivo = str(fila.get("archivo", "")).strip()
        confirmados = {
            campo: {**datos, "fuente": "CONFIRMACION_ADMINISTRADOR"}
            for campo, datos in self._confirmados.get(archivo, {}).items()
            if campo in CAMPOS_EQUIPO and datos["valor_documental"] == _patente(fila.get(campo))
        }
        regla = equipo_por_asignacion_vigente(
            fila, choferes=self._choferes, vehiculos=self._vehiculos,
            choferes_operacionales=self._operacionales, vigentes=self._vigentes,
            decisiones_humanas=self._decisiones_humanas)
        return {**{c: {**d, "fuente": "ASIGNACION_VIGENTE"} for c, d in regla.items()}, **confirmados}

    def decision_humana_sobre(self, fila: Mapping[str, object], campo: str) -> bool:
        return _decision_humana_sobre(self._decisiones_humanas, fila, campo)

    def nombre_chofer(self, fila: Mapping[str, object]) -> str:
        from atlas_core.catalogos import normalizar_rut

        rut = rut_chofer_inequivoco(fila, choferes=self._choferes, choferes_operacionales=self._operacionales)
        if not rut:
            return ""
        registro = next((r for k, r in self._choferes.items()
                         if isinstance(r, Mapping) and normalizar_rut(k) == rut), None)
        return str((registro or {}).get("nombre", "")).strip() if isinstance(registro, Mapping) else ""

    def patente_operacional(self, fila: Mapping[str, object], campo: str) -> str | None:
        datos = self.discrepancias(fila).get(campo)
        return datos["valor_operacional"] if datos else None


def retirar_decisiones_vehiculo_resueltas(
    decisiones: Iterable[Mapping[str, object]], *, filas_por_archivo: Mapping[str, Mapping[str, object]],
    resolutor: ResolutorEquipoOperacional,
) -> list[Mapping[str, object]]:
    """Una discrepancia documental ya resuelta (confirmada o por la regla
    general) no vuelve a pedir revisión de esa patente en ese documento."""
    salida = []
    for decision in decisiones:
        documento = decision.get("documento") or {}
        fila = filas_por_archivo.get(str(documento.get("archivo", "")).strip())
        campo = str(decision.get("campo", ""))
        if (decision.get("tipo") == "VEHICULO_DESCONOCIDO" and fila is not None and campo in CAMPOS_EQUIPO
                and _patente(decision.get("valor_documental")) == _patente(fila.get(campo))
                and resolutor.patente_operacional(fila, campo)):
            continue
        salida.append(decision)
    return salida


def es_discrepancia_documental(valor_documental: str, valor_operacional: str) -> bool:
    """Patente impresa bien formada y lejana de la operacional: no es ruido
    de lectura (6/8, D/0...), que nunca se registra como incidencia."""
    from atlas_core.decisiones_pendientes import _distancia_edicion_patente

    documental = _patente(valor_documental)
    return bool(_PATENTE_CHILENA.match(documental)) and _distancia_edicion_patente(
        documental, _patente(valor_operacional)) >= DISTANCIA_MINIMA_DISCREPANCIA_DOCUMENTAL


def proyectar_incidencias_equipo_por_asignacion(
    *, filas: Iterable[Mapping[str, object]], resolutor: ResolutorEquipoOperacional,
    ruta_incidencias: str | Path, reloj,
) -> dict[str, int]:
    """Registra como DETECTADA cada sustitución automática de patente vigente
    (las confirmadas por el administrador ya se registran como CONFIRMADA al
    aplicarse): patente leída (o «campo ausente»), patente aplicada y motivo.
    Incluye las sustituciones hechas al procesar la guía, cuya lectura OCR
    original quedó en las métricas. Una sustitución que dejó de aplicar (p.
    ej. por una decisión humana posterior) pasa a DESCARTADA. Idempotente:
    sin cambios no reescribe el almacén."""
    from atlas_core.incidencias_documentales import (
        VALOR_DOCUMENTAL_CAMPO_AUSENTE, AlmacenIncidenciasDocumentales, EstadoIncidencia,
    )

    almacen = AlmacenIncidenciasDocumentales(ruta_incidencias)
    vigentes: set[str] = set()
    guias: set[str] = set()
    registradas = 0
    for fila in filas:
        guia = str(fila.get("numero_guia", "")).strip()
        guias.add(guia)
        nombre = resolutor.nombre_chofer(fila)
        for campo, datos in sustituciones_automaticas_patente(fila, resolutor=resolutor).items():
            incidencia = almacen.registrar(
                contexto=str(fila.get("cliente", "")).strip(), numero_guia=guia,
                numero_transporte=str(fila.get("numero_transporte", "")), campo=campo,
                valor_documental=datos["valor_documental"] or VALOR_DOCUMENTAL_CAMPO_AUSENTE,
                valor_canonico=datos["valor_operacional"],
                tipo_incidencia=TIPO_INCIDENCIA_PATENTE_POR_ASIGNACION,
                evidencia=(f"MOTIVO:{datos['motivo']}", "CHOFER_INEQUIVOCO", FUENTE_ASIGNACION_VIGENTE,
                           *([f"CHOFER_IDENTIFICADO_POR_NOMBRE:{nombre}"] if nombre else []),
                           f"ORIGEN:{datos['origen']}"),
                fecha=reloj(), estado=EstadoIncidencia.DETECTADA, fuente_resolucion=FUENTE_ASIGNACION_VIGENTE,
                clasificacion="NO_VERIFICABLE", procedencia=(f"ARCHIVO:{fila.get('archivo', '')}",),
            )
            vigentes.add(incidencia.incidencia_id)
            registradas += 1
    descartadas = almacen.descartar_no_vigentes(
        tipo_incidencia=TIPO_INCIDENCIA_PATENTE_POR_ASIGNACION, numeros_guia=guias, vigentes=vigentes)
    return {"incidencias_evaluadas": registradas, "incidencias_descartadas": descartadas}


def sustituciones_automaticas_patente(
    fila: Mapping[str, object], *, resolutor: ResolutorEquipoOperacional,
) -> dict[str, dict[str, str]]:
    """``{campo: {valor_documental, valor_operacional, motivo, origen}}`` de
    las sustituciones automáticas vigentes de esta fila:

    - ``PROYECCION``: la regla general sobre la patente documental conservada.
    - ``PROCESAMIENTO``: la guía se procesó reubicando/completando patentes
      por asignación (métricas ``patentes_por_asignacion_chofer`` o
      ``reclasificacion_patentes`` con la lectura OCR original) y el dataset
      todavía conserva el valor aplicado.
    Nunca cuenta un campo con decisión humana."""
    resultado = {c: {**d, "origen": "PROYECCION"} for c, d in resolutor.discrepancias(fila).items()
                 if d.get("fuente") == "ASIGNACION_VIGENTE"}
    try:
        metricas = json.loads(str(fila.get("metricas_procesamiento_json") or "{}"))
    except (TypeError, ValueError):
        metricas = {}
    if not isinstance(metricas, dict):
        return resultado
    lecturas: dict[str, tuple[str, str]] = {}
    asignacion = metricas.get("patentes_por_asignacion_chofer")
    if isinstance(asignacion, dict) and asignacion.get("resultado") == "RESUELTO":
        ocr, aplicado = asignacion.get("valor_ocr") or {}, asignacion.get("valor_aplicado") or {}
        for campo in CAMPOS_EQUIPO:
            lecturas[campo] = (str(ocr.get(campo, "")), str(aplicado.get(campo, "")))
    reclasificacion = metricas.get("reclasificacion_patentes")
    if isinstance(reclasificacion, dict):
        for campo, (leida, aplicada) in {
            "patente_tracto": ("tracto_leido", "tracto"), "patente_rampla": ("carro_leido", "carro"),
        }.items():
            lecturas.setdefault(campo, (str(reclasificacion.get(leida, "")), str(reclasificacion.get(aplicada, ""))))
    aplicadas = {_patente(a) for _l, a in lecturas.values() if _patente(a)}
    for campo, (leida, aplicada) in lecturas.items():
        leida_n, aplicada_n = _patente(leida), _patente(aplicada)
        if (campo in resultado or not aplicada_n or leida_n == aplicada_n
                or _patente(fila.get(campo)) != aplicada_n or resolutor.decision_humana_sobre(fila, campo)):
            continue
        resultado[campo] = {
            "valor_documental": leida_n, "valor_operacional": aplicada_n,
            "motivo": motivo_sustitucion(leida_n, aplicada_n, otras_asignadas=aplicadas - {aplicada_n}),
            "origen": "PROCESAMIENTO", "fuente": "ASIGNACION_VIGENTE",
        }
    return resultado
