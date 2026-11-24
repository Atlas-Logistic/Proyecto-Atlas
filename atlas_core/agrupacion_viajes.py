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
- La separación (`evaluar_separacion`/`separar_agrupacion`) saca
  transportes COMPLETOS de una agrupación sin borrar el registro, y
  `revertir_separacion` la deshace.
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


# =============================================================== SEPARACIÓN
#
# Deshace (total o parcialmente) una agrupación confirmada por un humano.
# Distingue los dos niveles de identidad:
# - TRANSPORTE AZA: la carga que AZA despachó; sus guías son indivisibles
#   (nunca se reparten entre viajes Atlas).
# - VIAJE FÍSICO ATLAS: uno o más transportes AZA completos.
# Por eso sólo se separan transportes COMPLETOS de una agrupación ACTIVA. Una
# guía que "no pertenece" a su propio transporte es un error documental (su
# número de transporte), que se corrige por la vía documental, no aquí.
#
# El registro nunca se borra: la agrupación queda SEPARADA (con quién, cuándo
# y desde qué acción) y, si quedan 2+ transportes, nace una agrupación ACTIVA
# derivada con los restantes. Revertir reactiva la original y retira la
# derivada (REVERTIDA), también sin borrar nada.

ESTADO_SEPARADA = "SEPARADA"
ESTADO_REVERTIDA = "REVERTIDA"


def _transporte_valido(transporte: str) -> bool:
    return bool(re.fullmatch(r"\d{4,15}", transporte or ""))


def _guias_de_transporte(filas: Iterable[Mapping[str, str]], transporte: str) -> list[str]:
    return [str(f.get("numero_guia", "") or "").strip() for f in filas
            if _clave(f.get("numero_transporte")) == transporte]


def _lista_guias(guias: Iterable[str], *, articulo: bool = True) -> str:
    guias = list(guias)
    if len(guias) == 1:
        return f"{'La guía' if articulo else 'la guía'} {guias[0]}"
    return f"{'Las guías' if articulo else 'las guías'} {', '.join(guias[:-1])} y {guias[-1]}"


@dataclass
class EvaluacionSeparacion:
    guias: list[str]
    agrupacion: dict = field(default_factory=dict)
    transportes_separados: list[str] = field(default_factory=list)
    transportes_restantes: list[str] = field(default_factory=list)
    guias_por_transporte: dict[str, list[str]] = field(default_factory=dict)
    ya_separadas: bool = False
    motivo_rechazo: str = ""
    codigo: str = "PRECONDICION_FALLIDA"

    @property
    def grupos_resultantes(self) -> list[list[str]]:
        """Viajes físicos resultantes (listas ordenadas de transportes): cada
        transporte separado queda como viaje propio y los restantes siguen
        juntos (si son 2+) o solos."""
        grupos = [[t] for t in self.transportes_separados]
        if self.transportes_restantes:
            grupos.append(list(self.transportes_restantes))
        return sorted(grupos, key=lambda g: g[0])


def _rechazo(evaluacion: EvaluacionSeparacion, motivo: str, codigo: str = "PRECONDICION_FALLIDA") -> EvaluacionSeparacion:
    evaluacion.motivo_rechazo, evaluacion.codigo = motivo, codigo
    return evaluacion


def evaluar_separacion(
    *, guias: Iterable[str], filas: Iterable[Mapping[str, str]], agrupaciones: Iterable[Mapping[str, object]],
    guia_viaje: str = "",
) -> EvaluacionSeparacion:
    """Decide si las guías pueden sacarse del viaje agrupado en que están.
    Nunca escribe. `guia_viaje` (opcional) es otra guía del MISMO viaje que
    debe quedar en él, para identificarlo sin ambigüedad.

    Rechaza (motivo + código) toda situación sin resultado único: guía
    inexistente o repetida, transporte inválido, guías de viajes distintos,
    transporte AZA nombrado sólo en parte, documento sin folio en un
    transporte del viaje, registro de agrupaciones contradictorio, o todos
    los transportes de un viaje de 3+ (no se sabe cuáles siguen juntos)."""
    guias = sorted({str(g).strip() for g in guias if str(g).strip()})
    guia_viaje = str(guia_viaje or "").strip()
    evaluacion = EvaluacionSeparacion(guias=guias)
    if not guias:
        return _rechazo(evaluacion, "Indica al menos una guía a separar.", "PARAMETRO_INVALIDO")
    filas = list(filas)
    agrupaciones = [a for a in agrupaciones if isinstance(a, Mapping)]
    transporte_por_guia: dict[str, str] = {}
    for guia in [*guias, *([guia_viaje] if guia_viaje else [])]:
        propias = [f for f in filas if str(f.get("numero_guia", "") or "").strip() == guia]
        if not propias:
            return _rechazo(evaluacion, f"La guía {guia} no existe en el dataset.", "ENTIDAD_NO_ENCONTRADA")
        if len(propias) > 1:
            return _rechazo(evaluacion, f"La guía {guia} aparece en {len(propias)} documentos; no se puede saber "
                                        "cuál separar. Corrige primero el folio repetido.", "ENTIDAD_AMBIGUA")
        transporte = _clave(propias[0].get("numero_transporte"))
        if not _transporte_valido(transporte):
            return _rechazo(evaluacion, f"La guía {guia} no tiene un número de transporte AZA válido; "
                                        "corrígelo primero.")
        transporte_por_guia[guia] = transporte
    # Registro contradictorio: un transporte en dos agrupaciones activas.
    apariciones: dict[str, int] = {}
    for agrupacion in agrupaciones:
        for t in {_clave(x) for x in agrupacion.get("transportes") or []}:
            apariciones[t] = apariciones.get(t, 0) + 1
    contradictorios = sorted(t for t in set(transporte_por_guia.values()) if apariciones.get(t, 0) > 1)
    if contradictorios:
        return _rechazo(evaluacion, f"El transporte {', '.join(contradictorios)} figura en dos agrupaciones "
                                    "activas; el registro es inconsistente y requiere revisión técnica.",
                        "ESTADO_ILEGIBLE")
    separados = sorted({transporte_por_guia[g] for g in guias})
    mapa = mapa_transporte_a_grupo(agrupaciones)
    if not any(t in mapa for t in separados):
        # Ningún transporte agrupado: cada viaje Atlas ES su transporte AZA.
        for t in separados:
            otras = sorted(set(_guias_de_transporte(filas, t)) - set(guias))
            if otras:
                propias = [g for g in guias if transporte_por_guia[g] == t]
                return _rechazo(evaluacion, (
                    f"{_lista_guias(propias)} y {_lista_guias(otras, articulo=False)} forman el transporte AZA "
                    f"{t}: Atlas trata un transporte AZA como un solo viaje físico y nunca lo divide. Si una guía "
                    "tiene mal leído su número de transporte, corrige ese número (con su propia vista previa)."))
        evaluacion.ya_separadas = True  # cada guía ya está en un viaje propio
        evaluacion.transportes_separados = separados
        evaluacion.guias_por_transporte = {t: sorted(_guias_de_transporte(filas, t)) for t in separados}
        return evaluacion
    sueltos = [t for t in separados if t not in mapa]
    if sueltos:
        sueltas = [g for g in guias if transporte_por_guia[g] in sueltos]
        return _rechazo(evaluacion, f"{_lista_guias(sueltas)} ya forma un viaje propio (transporte "
                                    f"{', '.join(sueltos)}); separa sólo guías de un mismo viaje agrupado.",
                        "ENTIDAD_AMBIGUA")
    principales = {mapa[t] for t in separados}
    if len(principales) > 1:
        return _rechazo(evaluacion, "Las guías indicadas pertenecen a viajes agrupados distintos; separa las de "
                                    "un viaje a la vez.", "ENTIDAD_AMBIGUA")
    principal = principales.pop()
    agrupacion = next(a for a in agrupaciones if principal in {_clave(t) for t in a.get("transportes") or []})
    transportes = sorted({_clave(t) for t in agrupacion.get("transportes") or []})
    evaluacion.agrupacion = dict(agrupacion)
    evaluacion.guias_por_transporte = {t: sorted(_guias_de_transporte(filas, t)) for t in transportes}
    for t in transportes:
        documentos = evaluacion.guias_por_transporte[t]
        if not documentos:
            return _rechazo(evaluacion, f"El transporte {t} del viaje no tiene documentos en el dataset; "
                                        "el viaje requiere revisión antes de separarlo.")
        if any(not g for g in documentos) or len(set(documentos)) != len(documentos):
            return _rechazo(evaluacion, f"El transporte {t} del viaje tiene documentos sin folio o con folio "
                                        "repetido; corrígelos antes de separar (ninguna guía puede perderse).",
                            "ENTIDAD_AMBIGUA")
    for t in separados:
        faltan = sorted(set(evaluacion.guias_por_transporte[t]) - set(guias))
        if faltan:
            propias = [g for g in guias if transporte_por_guia[g] == t]
            return _rechazo(evaluacion, (
                f"{_lista_guias(propias)} comparte el transporte AZA {t} con "
                f"{_lista_guias(faltan, articulo=False)}; un transporte AZA no se divide. Para sacar ese "
                f"transporte del viaje nombra todas sus guías ({', '.join(sorted(set(propias) | set(faltan)))}). "
                "Si una guía tiene mal leído su número de transporte, corrige ese número."))
    restantes = [t for t in transportes if t not in separados]
    if not restantes:
        if len(transportes) > 2:
            return _rechazo(evaluacion, (
                f"Nombraste las guías de los {len(transportes)} transportes del viaje; no se sabe cuáles deben "
                "seguir juntos. Indica sólo las guías que salen del viaje."), "ENTIDAD_AMBIGUA")
        # Dos transportes nombrados completos: deshacer la agrupación (cada
        # transporte vuelve a ser su propio viaje). Único resultado posible.
        separados, restantes = separados[1:], separados[:1]
    if guia_viaje and guia_viaje not in guias:
        referencia = transporte_por_guia[guia_viaje]
        if referencia not in transportes:
            return _rechazo(evaluacion, f"La guía {guia_viaje} no pertenece al viaje agrupado de las guías "
                                        "indicadas.", "ENTIDAD_AMBIGUA")
        if referencia in separados:
            return _rechazo(evaluacion, f"La guía {guia_viaje} está en un transporte que se separa; no puede "
                                        "identificar el viaje que queda.", "ENTIDAD_AMBIGUA")
    evaluacion.transportes_separados, evaluacion.transportes_restantes = separados, restantes
    return evaluacion


def separar_agrupacion(
    carpeta_actual: str | Path, *, agrupacion_id: str, transportes_esperados: Iterable[str],
    transportes_separados: Iterable[str], guias_restantes: Iterable[str], actor: str, confirmado_por: str,
    fuente: str, referencia: str = "", reloj=lambda: datetime.now(timezone.utc),
) -> tuple[dict, dict | None]:
    """Marca SEPARADA la agrupación ACTIVA (que debe seguir teniendo
    exactamente `transportes_esperados`) y, si quedan 2+ transportes, crea la
    agrupación ACTIVA derivada con ellos. Devuelve (original, derivada|None).
    Nunca borra registros."""
    esperados = sorted({_clave(t) for t in transportes_esperados if _clave(t)})
    separados = sorted({_clave(t) for t in transportes_separados if _clave(t)})
    restantes = [t for t in esperados if t not in separados]
    if not separados or not set(separados) < set(esperados):
        raise ValueError("los transportes a separar deben ser parte (no todos) de la agrupación")
    ruta = ruta_registro(carpeta_actual)
    with bloqueo_sesion(ruta.parent, "agrupaciones_viaje"):
        contenido = _leer(ruta)
        activas = [a for a in contenido["agrupaciones"] if isinstance(a, dict) and a.get("estado") == "ACTIVA"]
        original = next((a for a in activas if a.get("agrupacion_id") == agrupacion_id), None)
        if original is None or sorted({_clave(t) for t in original.get("transportes") or []}) != esperados:
            raise ValueError("la agrupación cambió desde la vista previa")
        ahora = reloj().astimezone(timezone.utc).isoformat()
        derivada = None
        if len(restantes) >= 2:
            ocupados = set(mapa_transporte_a_grupo(a for a in activas if a is not original))
            if ocupados & set(restantes):
                raise ValueError("algún transporte restante ya pertenece a otra agrupación activa")
            derivada = {
                "agrupacion_id": identificador_agrupacion(restantes), "estado": "ACTIVA",
                "tipo": original.get("tipo") or "VIAJE_FISICO_MULTITRANSPORTE", "transportes": restantes,
                "transporte_principal": restantes[0],
                "guias": sorted({str(g).strip() for g in guias_restantes if str(g).strip()}),
                # La unión de los restantes la confirmó quien confirmó la original.
                "actor": original.get("actor", ""), "confirmado_por": original.get("confirmado_por", ""),
                "fuente": original.get("fuente", ""), "referencia": original.get("referencia", ""),
                "fecha": original.get("fecha", ""),
                "derivada_de": {"agrupacion_id": agrupacion_id, "separacion": fuente, "fecha": ahora},
            }
        original["estado"] = ESTADO_SEPARADA
        original["separacion"] = {
            "fecha": ahora, "actor": actor, "confirmado_por": confirmado_por, "fuente": fuente,
            "referencia": referencia, "transportes_separados": separados, "transportes_restantes": restantes,
            "agrupacion_derivada": derivada["agrupacion_id"] if derivada else None,
        }
        if derivada is not None:
            contenido["agrupaciones"].append(derivada)
        escribir_json_atomico(ruta, contenido)
        return original, derivada


def _reversion_posible(agrupaciones: list[dict], original: Mapping[str, object]) -> bool:
    separacion = original.get("separacion") or {}
    derivada_id = separacion.get("agrupacion_derivada")
    transportes = {_clave(t) for t in original.get("transportes") or []}
    activas = [a for a in agrupaciones if a.get("estado") == "ACTIVA"]
    derivada = next((a for a in activas if a.get("agrupacion_id") == derivada_id), None) if derivada_id else None
    if derivada_id and (derivada is None or sorted({_clave(t) for t in derivada.get("transportes") or []})
                        != sorted({_clave(t) for t in separacion.get("transportes_restantes") or []})):
        return False
    return not any(transportes & {_clave(t) for t in a.get("transportes") or []}
                   for a in activas if a is not derivada)


def ultima_separacion_reversible(carpeta_actual: str | Path, transporte: str) -> dict | None:
    """Agrupación SEPARADA más reciente que contenía `transporte`, si su
    resultado sigue intacto (derivada aún ACTIVA con los mismos transportes
    y ningún transporte de la original en otra agrupación activa)."""
    clave = _clave(transporte)
    try:
        agrupaciones = [a for a in _leer(ruta_registro(carpeta_actual))["agrupaciones"] if isinstance(a, dict)]
    except (OSError, ValueError):
        return None
    candidatas = [a for a in agrupaciones if a.get("estado") == ESTADO_SEPARADA
                  and clave in {_clave(t) for t in a.get("transportes") or []}]
    if not candidatas:
        return None
    original = max(candidatas, key=lambda a: str((a.get("separacion") or {}).get("fecha", "")))
    return dict(original) if _reversion_posible(agrupaciones, original) else None


def revertir_separacion(
    carpeta_actual: str | Path, *, agrupacion_id: str, fecha_separacion: str, actor: str, confirmado_por: str,
    fuente: str, referencia: str = "", reloj=lambda: datetime.now(timezone.utc),
) -> dict:
    """Reactiva la agrupación SEPARADA (id + fecha de su separación) y marca
    REVERTIDA su derivada. Exige que el resultado de la separación siga
    intacto. Devuelve la agrupación reactivada."""
    ruta = ruta_registro(carpeta_actual)
    with bloqueo_sesion(ruta.parent, "agrupaciones_viaje"):
        contenido = _leer(ruta)
        agrupaciones = [a for a in contenido["agrupaciones"] if isinstance(a, dict)]
        original = next((a for a in agrupaciones if a.get("agrupacion_id") == agrupacion_id
                         and a.get("estado") == ESTADO_SEPARADA
                         and (a.get("separacion") or {}).get("fecha") == fecha_separacion), None)
        if original is None or not _reversion_posible(agrupaciones, original):
            raise ValueError("la separación ya no se puede revertir: el registro cambió desde la vista previa")
        ahora = reloj().astimezone(timezone.utc).isoformat()
        derivada_id = (original.get("separacion") or {}).get("agrupacion_derivada")
        for a in agrupaciones:
            if derivada_id and a.get("agrupacion_id") == derivada_id and a.get("estado") == "ACTIVA":
                a["estado"] = ESTADO_REVERTIDA
                a["reversion"] = {"fecha": ahora, "actor": actor, "confirmado_por": confirmado_por,
                                  "fuente": fuente}
        historial = list(original.get("historial") or [])
        historial.append({"separacion": original.pop("separacion"), "revertida": {
            "fecha": ahora, "actor": actor, "confirmado_por": confirmado_por, "fuente": fuente,
            "referencia": referencia}})
        original["historial"] = historial
        original["estado"] = "ACTIVA"
        escribir_json_atomico(ruta, contenido)
        return original
