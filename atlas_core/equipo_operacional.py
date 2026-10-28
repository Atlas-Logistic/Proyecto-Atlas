"""Equipo OPERACIONAL (tracto/rampla) de una guía frente a lo impreso por AZA.

Dos fuentes, en este orden, siempre por documento (`archivo`) y nunca
propagadas a guías hermanas:

1. Error documental AZA confirmado por el administrador: entrada
   `ERROR_DOCUMENTAL_AZA` del ledger `decisiones_aplicadas.json`
   (append-only, la última por documento gana) con, por campo, el valor
   impreso y el operacional confirmado. Vale mientras la lectura vigente
   siga siendo la registrada; persiste frente a OCR, PULL y revalidación.
2. Regla general conservadora (`equipo_por_asignacion_vigente`): chofer
   identificado de forma inequívoca + exactamente una asignación vigente
   confirmada por un humano para ese tipo de vehículo, desde una fecha no
   posterior a la de la guía. Se abstiene ante identidad ambigua o
   contradictoria, asignación variable o múltiple, patente ausente (nunca
   completa lo que el documento no trae) o una patente impresa que el
   catálogo ya conoce (puede ser un cambio real de equipo).

El dataset documental nunca se modifica aquí: la patente impresa queda tal
cual y el valor operacional se aplica en reporte, revalidación y tarjetas.
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
# Distancia de edición desde la que una patente impresa distinta deja de
# parecer ruido OCR: sólo entonces es una discrepancia documental.
DISTANCIA_MINIMA_DISCREPANCIA_DOCUMENTAL = 3
_PATENTE_CHILENA = re.compile(r"^(?:[A-Z]{2}\d{4}|[A-Z]{4}\d{2})$")
_AUSENTES = {"", "NOENCONTRADO", "NOENCONTRADA"}


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
) -> dict[str, dict[str, str]]:
    """``{campo: {valor_documental, valor_operacional}}`` sólo para campos
    cuya patente impresa difiere de la asignación vigente única del chofer."""
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
    conocidas = {v.patente_canonica for v in vehiculos} | {a for v in vehiculos for a in (v.aliases or ())}
    fecha_guia = _fecha_guia(fila)
    resultado: dict[str, dict[str, str]] = {}
    for campo, tipo in CAMPOS_EQUIPO.items():
        propias = [(p, f) for p, (r, t, f) in vigentes.items() if r == rut and t == tipo]
        if len(propias) != 1:
            continue
        canonica, fecha_asignacion = propias[0]
        documental = _patente(fila.get(campo))
        if not documental or documental == canonica or documental in conocidas:
            continue
        if fecha_guia is None or fecha_guia < datetime.fromisoformat(fecha_asignacion).date():
            continue
        resultado[campo] = {"valor_documental": documental, "valor_operacional": canonica}
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
        self._confirmados = errores_documentales_aza_por_ledger(ruta_ledger)
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
            choferes_operacionales=self._operacionales, vigentes=self._vigentes)
        return {**{c: {**d, "fuente": "ASIGNACION_VIGENTE"} for c, d in regla.items()}, **confirmados}

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
    """Registra como DETECTADA cada discrepancia de la regla general (las
    confirmadas por el administrador ya se registran como CONFIRMADA al
    aplicarse). Idempotente por (guía, campo, impreso, operacional)."""
    from atlas_core.incidencias_documentales import AlmacenIncidenciasDocumentales, EstadoIncidencia

    almacen = AlmacenIncidenciasDocumentales(ruta_incidencias)
    registradas = 0
    for fila in filas:
        for campo, datos in resolutor.discrepancias(fila).items():
            if datos["fuente"] != "ASIGNACION_VIGENTE" or not es_discrepancia_documental(
                    datos["valor_documental"], datos["valor_operacional"]):
                continue
            almacen.registrar(
                contexto=datos["valor_operacional"], numero_guia=str(fila.get("numero_guia", "")),
                numero_transporte=str(fila.get("numero_transporte", "")), campo=campo,
                valor_documental=datos["valor_documental"], valor_canonico=datos["valor_operacional"],
                tipo_incidencia=TIPO_INCIDENCIA_ERROR_DOCUMENTAL_AZA,
                evidencia=("PATENTE_IMPRESA_DISTINTA_DE_ASIGNACION_VIGENTE", "CHOFER_INEQUIVOCO"),
                fecha=reloj(), estado=EstadoIncidencia.DETECTADA, fuente_resolucion="ASIGNACION_VIGENTE_CONFIRMADA",
                clasificacion="NO_VERIFICABLE", procedencia=(f"ARCHIVO:{fila.get('archivo', '')}",),
            )
            registradas += 1
    return {"incidencias_evaluadas": registradas}
