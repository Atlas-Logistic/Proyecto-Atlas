"""Agrupación de VIAJE FÍSICO confirmada por un humano (multitransporte AZA).

Por defecto un viaje Atlas = un `numero_transporte` AZA (`gestor_viajes.
agrupar_viajes`). Pero un mismo viaje/reparto físico puede cubrir varios
transportes AZA distintos (caso real: dos cargas en la misma planta, el
mismo día, mismo chofer y camión, un solo reparto). Atlas NO lo infiere:
sólo un humano lo confirma, y queda como una regla explícita en
`operacion/actual/agrupaciones_viaje.json`.

Semántica (mínima y reversible):
- Una agrupación une TRANSPORTES COMPLETOS (todas sus guías), nunca guías
  sueltas: un transporte AZA sigue siendo indivisible.
- No toca el dataset documental: cada guía conserva su `numero_transporte`
  AZA y todos sus datos. El reporte de viajes aplica la regla al agrupar.
- El viaje resultante conserva el `viaje_id`/`numero_transporte` del
  transporte PRINCIPAL (el menor), y declara todos en `transportes_aza`.
- Sólo se permite si la evidencia estructural no lo contradice (misma
  fecha, mismo chofer, mismo tracto y rampla cuando están presentes) y si
  ningún transporte ya pertenece a otra agrupación o tiene eventos
  operacionales propios (estadías, etc., que están indexados por
  transporte y quedarían huérfanos).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping
from uuid import NAMESPACE_URL, uuid5

from atlas_core.almacenamiento_portable import bloqueo_sesion, escribir_json_atomico

NOMBRE_REGISTRO = "agrupaciones_viaje.json"
SCHEMA_VERSION = 1
_AUSENTES = {"", "NO ENCONTRADO", "REVISAR", "ILEGIBLE"}


def ruta_registro(carpeta_actual: str | Path) -> Path:
    return Path(carpeta_actual) / NOMBRE_REGISTRO


def _clave(transporte: object) -> str:
    return re.sub(r"\s+", "", str(transporte or "")).upper()


def _leer(ruta: Path) -> dict:
    try:
        contenido = json.loads(ruta.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"schema_version": SCHEMA_VERSION, "agrupaciones": []}
    if contenido.get("schema_version") != SCHEMA_VERSION or not isinstance(contenido.get("agrupaciones"), list):
        raise ValueError("registro de agrupaciones de viaje inválido")
    return contenido


def agrupaciones_activas(carpeta_actual: str | Path) -> list[dict]:
    try:
        return [a for a in _leer(ruta_registro(carpeta_actual))["agrupaciones"]
                if isinstance(a, dict) and a.get("estado") == "ACTIVA"]
    except (OSError, ValueError):
        return []


def mapa_transporte_a_grupo(agrupaciones: Iterable[Mapping[str, object]]) -> dict[str, str]:
    """{clave de cada transporte agrupado: clave del transporte principal}.
    Un transporte presente en dos agrupaciones activas es inconsistente: se
    ignoran ambas (nunca se elige una) y el viaje vuelve al agrupamiento por
    transporte."""
    grupos = [sorted({_clave(t) for t in agrupacion.get("transportes") or [] if _clave(t)})
              for agrupacion in agrupaciones]
    grupos = [g for g in grupos if len(g) >= 2]
    apariciones: dict[str, int] = {}
    for grupo in grupos:
        for transporte in grupo:
            apariciones[transporte] = apariciones.get(transporte, 0) + 1
    mapa: dict[str, str] = {}
    for grupo in grupos:
        if all(apariciones[t] == 1 for t in grupo):
            mapa.update({t: grupo[0] for t in grupo})
    return mapa


def identificador_agrupacion(transportes: Iterable[str]) -> str:
    return str(uuid5(NAMESPACE_URL, "atlas:agrupacion-viaje:" + "|".join(sorted({_clave(t) for t in transportes}))))


@dataclass
class EvaluacionAgrupacion:
    guias: list[str]
    transportes: list[str] = field(default_factory=list)
    documentos: dict[str, list[dict[str, str]]] = field(default_factory=dict)
    ya_agrupadas: bool = False
    motivo_rechazo: str = ""

    @property
    def principal(self) -> str:
        return self.transportes[0] if self.transportes else ""


def _valor(fila: Mapping[str, str], campo: str) -> str:
    valor = str(fila.get(campo, "") or "").strip()
    return "" if valor.upper() in _AUSENTES else valor


def evaluar_agrupacion(
    *, guias: Iterable[str], filas: Iterable[Mapping[str, str]],
    agrupaciones: Iterable[Mapping[str, object]], eventos: Iterable[Mapping[str, object]] = (),
) -> EvaluacionAgrupacion:
    """Decide si las guías pueden declararse un mismo viaje físico. Nunca
    escribe. `motivo_rechazo` vacío + `ya_agrupadas` False = agrupación
    aplicable."""
    guias = sorted({str(g).strip() for g in guias if str(g).strip()})
    evaluacion = EvaluacionAgrupacion(guias=guias)
    if len(guias) < 2:
        evaluacion.motivo_rechazo = "Se necesitan al menos dos guías distintas."
        return evaluacion
    filas = list(filas)
    transporte_por_guia: dict[str, str] = {}
    for guia in guias:
        propias = [f for f in filas if str(f.get("numero_guia", "")).strip() == guia]
        transportes = {_clave(f.get("numero_transporte")) for f in propias} - {""}
        if not propias:
            evaluacion.motivo_rechazo = f"La guía {guia} no existe en el dataset."
            return evaluacion
        if len(transportes) != 1:
            evaluacion.motivo_rechazo = (f"La guía {guia} no tiene un único transporte AZA válido "
                                         f"({', '.join(sorted(transportes)) or 'sin transporte'}).")
            return evaluacion
        transporte_por_guia[guia] = transportes.pop()
    transportes = sorted(set(transporte_por_guia.values()))
    evaluacion.transportes = transportes
    evaluacion.documentos = {
        t: [{"numero_guia": str(f.get("numero_guia", "")).strip(), "archivo": str(f.get("archivo", "")),
             "fecha": _valor(f, "fecha"), "chofer": _valor(f, "chofer"),
             "hora_entrada_aza": _valor(f, "hora_entrada_aza"), "hora_salida_aza": _valor(f, "hora_salida_aza"),
             "planta_origen_nombre": _valor(f, "planta_origen_nombre"),
             "direccion_entrega": _valor(f, "direccion_entrega") or _valor(f, "despachar_a_crudo")}
            for f in filas if _clave(f.get("numero_transporte")) == t]
        for t in transportes
    }
    if len(transportes) == 1:
        evaluacion.ya_agrupadas = True  # mismo transporte AZA = ya es el mismo viaje
        return evaluacion
    mapa = mapa_transporte_a_grupo(agrupaciones)
    grupos_actuales = {mapa.get(t, t) for t in transportes}
    if len(grupos_actuales) == 1:
        evaluacion.ya_agrupadas = True
        return evaluacion
    ya_en_otra = sorted(t for t in transportes if t in mapa)
    if ya_en_otra:
        evaluacion.motivo_rechazo = (f"El transporte {', '.join(ya_en_otra)} ya pertenece a otra agrupación de viaje; "
                                     "no se amplían agrupaciones existentes desde aquí.")
        return evaluacion
    todas = [f for f in filas if _clave(f.get("numero_transporte")) in set(transportes)]
    for campo, etiqueta, normalizar in (
        ("fecha", "fecha", str),
        ("rut_chofer", "chofer (RUT)", lambda v: re.sub(r"[^0-9K]", "", v.upper())),
        ("patente_tracto", "tracto", lambda v: re.sub(r"[^A-Z0-9]", "", v.upper())),
        ("patente_rampla", "rampla", lambda v: re.sub(r"[^A-Z0-9]", "", v.upper())),
    ):
        valores = {normalizar(_valor(f, campo)) for f in todas} - {""}
        if len(valores) > 1:
            evaluacion.motivo_rechazo = (f"No es seguro agruparlas: los documentos tienen {etiqueta} distinto "
                                         f"({', '.join(sorted(valores))}).")
            return evaluacion
    if not {re.sub(r"[^0-9K]", "", _valor(f, "rut_chofer").upper()) for f in todas} - {""}:
        evaluacion.motivo_rechazo = "No es seguro agruparlas: ningún documento identifica al chofer por RUT."
        return evaluacion
    absorbidos = set(transportes[1:])
    con_eventos = sorted({_clave(e.get("numero_transporte")) for e in eventos
                          if e.get("estado", "ACTIVO") == "ACTIVO" and _clave(e.get("numero_transporte")) in absorbidos})
    if con_eventos:
        evaluacion.motivo_rechazo = (f"El transporte {', '.join(con_eventos)} tiene eventos operacionales propios "
                                     "(p. ej. estadía); agruparlo los dejaría sin viaje. Resuélvelos primero.")
    return evaluacion


def registrar_agrupacion(
    carpeta_actual: str | Path, *, transportes: Iterable[str], guias: Iterable[str], actor: str,
    confirmado_por: str, fuente: str, referencia: str = "", reloj=lambda: datetime.now(timezone.utc),
) -> tuple[dict, bool]:
    """Agrega la agrupación ACTIVA; idempotente por conjunto de transportes.
    Devuelve (agrupación, creada)."""
    transportes = sorted({_clave(t) for t in transportes if _clave(t)})
    if len(transportes) < 2:
        raise ValueError("una agrupación necesita al menos dos transportes")
    ruta = ruta_registro(carpeta_actual)
    with bloqueo_sesion(ruta.parent, "agrupaciones_viaje"):
        contenido = _leer(ruta)
        agrupacion_id = identificador_agrupacion(transportes)
        existente = next((a for a in contenido["agrupaciones"]
                          if a.get("agrupacion_id") == agrupacion_id and a.get("estado") == "ACTIVA"), None)
        if existente is not None:
            return existente, False
        ocupados = set(mapa_transporte_a_grupo(a for a in contenido["agrupaciones"] if a.get("estado") == "ACTIVA"))
        if ocupados & set(transportes):
            raise ValueError("algún transporte ya pertenece a otra agrupación activa")
        agrupacion = {
            "agrupacion_id": agrupacion_id, "estado": "ACTIVA", "tipo": "VIAJE_FISICO_MULTITRANSPORTE",
            "transportes": transportes, "transporte_principal": transportes[0],
            "guias": sorted({str(g).strip() for g in guias if str(g).strip()}),
            "actor": actor, "confirmado_por": confirmado_por, "fuente": fuente, "referencia": referencia,
            "fecha": reloj().astimezone(timezone.utc).isoformat(),
        }
        contenido["agrupaciones"].append(agrupacion)
        escribir_json_atomico(ruta, contenido)
        return agrupacion, True
