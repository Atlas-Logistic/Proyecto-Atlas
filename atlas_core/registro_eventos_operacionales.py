"""Bloque EVENTOS OPERACIONALES CANÓNICOS V1 -- fuente canónica de los
hechos operacionales que hoy Desktop guarda aislados en electron-store
(`observaciones.json`: estadías, devoluciones parciales/totales, dobles
vueltas y su nota libre).

Este módulo es el ÚNICO dueño del archivo canónico

    ATLAS_DATA_DIR/operacion/actual/eventos_operacionales.json

Contrato (nunca una base de datos ni infraestructura nueva -- un solo
JSON pequeño, con las mismas garantías que ya usa el resto de Atlas para
`decisiones_pendientes.json` / `estado_operacion.json`):

- lock físico de sesión (``bloqueo_sesion``) para toda secuencia
  "releer -> mutar -> publicar";
- relectura BAJO el lock (nunca se fusiona contra una foto vieja);
- escritura atómica (``escribir_json_atomico``);
- idempotencia por ``clave_idempotencia`` -- alta repetida NO duplica;
- anulación sin borrado físico (``estado`` ACTIVO/ANULADO);
- reactivación del MISMO evento lógico (mismo ``evento_id``);
- historial mínimo de cambios por evento.

MULTIEMPRESA -- Atlas todavía NO tiene un campo/contexto empresarial
canónico y fiable en Core (no hay tenant en `viajes.csv` ni en los
catálogos; `JAVIER_MBT` es sólo un `actor` de auditoría, no un tenant).
Hasta que exista, cada evento lleva ``contexto_empresarial`` con un
identificador transitorio EXPLÍCITO y documentado
(``CONTEXTO_EMPRESARIAL_SIN_ASIGNAR``). La ``clave_idempotencia`` YA
incluye ese contexto, así que el día que exista un tenant real basta con
pasarlo -- sin migrar la forma de deduplicar.

NO cambia todavía el ejecutor EVENTOS de B1 ni
`eventos_operacionales.construir_eventos_operacionales` (el adaptador
read-only sobre envíos Mobile) -- eso es otro bloque, después de validar
esta fuente.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping
from uuid import uuid4

from atlas_core.almacenamiento_portable import (
    bloqueo_sesion,
    escribir_json_atomico,
    leer_estado_operacion,
    ruta_operacion,
)

SCHEMA_VERSION = 1
NOMBRE_ARCHIVO = "eventos_operacionales.json"
# Mismo criterio que `NOMBRE_LOCK_DECISIONES_PENDIENTES`: un único nombre
# de lock para este archivo en TODO el codebase, nunca uno por caller.
NOMBRE_LOCK = "eventos_operacionales"

# Identificador transitorio de contexto empresarial -- ver docstring del
# módulo. NUNCA se hardcodea aquí ninguna empresa concreta (MBT, AZA...).
CONTEXTO_EMPRESARIAL_SIN_ASIGNAR = "__SIN_ASIGNAR__"

ESTADO_ACTIVO = "ACTIVO"
ESTADO_ANULADO = "ANULADO"

# Los 4 tipos iniciales. Son MARCA_VIAJE: como máximo UN hecho activo del
# mismo tipo por viaje dentro del mismo contexto empresarial. La lista NO
# es cerrada -- un `tipo_evento` desconocido se acepta igual y se trata
# como MARCA_VIAJE por defecto (mismo anti-hardcode que el resto del
# dominio EVENTOS).
NATURALEZA_MARCA_VIAJE = "MARCA_VIAJE"
TIPOS_MARCA_VIAJE_INICIALES = frozenset(
    {"TIENE_ESTADIA", "DEVOLUCION_PARCIAL", "DEVOLUCION_TOTAL", "DOBLE_VUELTA"}
)

_RELOJ_UTC: Callable[[], datetime] = lambda: datetime.now(timezone.utc)


class EventosOperacionalesCorruptosError(RuntimeError):
    """El archivo canónico existe pero no es un documento válido.

    Nunca se sobrescribe en silencio (sería pérdida de datos): el caller
    debe intervenir. La lectura para SÓLO MOSTRAR (``listar_*``) sí
    tolera esto y devuelve vacío -- nunca escribe.
    """


# --------------------------------------------------------------------------
# Ubicación y lectura
# --------------------------------------------------------------------------

def ruta_eventos_operacionales(*, raiz: str | Path | None = None) -> Path:
    """``<raiz>/operacion/actual/eventos_operacionales.json``."""
    return ruta_operacion("actual", raiz=Path(raiz) if raiz is not None else None) / NOMBRE_ARCHIVO


def _documento_vacio() -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "revision": 0,
        "actualizado_en": None,
        "eventos": [],
    }


def _documento_valido(contenido: object) -> bool:
    return (
        isinstance(contenido, dict)
        and contenido.get("schema_version") == SCHEMA_VERSION
        and isinstance(contenido.get("eventos"), list)
    )


def leer_eventos_operacionales(*, raiz: str | Path | None = None) -> dict:
    """Lectura TOLERANTE para mostrar/consultar. Nunca lanza ni escribe.

    Un archivo ausente o corrupto devuelve el documento vacío -- "todavía
    no hay ningún evento canónico" (mismo criterio ya usado para
    incidencias / eventos Mobile).
    """
    ruta = ruta_eventos_operacionales(raiz=raiz)
    if not ruta.is_file():
        return _documento_vacio()
    try:
        contenido = json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _documento_vacio()
    if not _documento_valido(contenido):
        return _documento_vacio()
    return contenido


def _cargar_para_escritura(ruta: Path) -> dict:
    """Lectura ESTRICTA usada dentro del lock antes de mutar.

    Ausente -> documento vacío (caso normal la primera vez). Presente
    pero inválido -> ``EventosOperacionalesCorruptosError`` (nunca se
    clobberea un archivo que no entendemos).
    """
    if not ruta.is_file():
        return _documento_vacio()
    try:
        contenido = json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise EventosOperacionalesCorruptosError(
            f"{ruta} no se puede leer como JSON: {error}"
        ) from error
    if not _documento_valido(contenido):
        raise EventosOperacionalesCorruptosError(
            f"{ruta} no tiene la forma esperada (schema_version/eventos)."
        )
    return contenido


# --------------------------------------------------------------------------
# Idempotencia
# --------------------------------------------------------------------------

def clave_idempotencia(
    *, contexto_empresarial: str, tipo_evento: str, numero_transporte: str
) -> str:
    """Clave lógica de un hecho MARCA_VIAJE.

    ``(contexto_empresarial, tipo_evento, numero_transporte)`` -- el
    ``numero_transporte`` es la clave de viaje estable que ya usa TODO
    Atlas para unir documentos (``gestor_viajes``, ``mobile.asociar_
    documento``); ``viaje_id`` se guarda sólo como enriquecimiento. El
    contexto empresarial va PRIMERO y siempre presente para que el mismo
    tipo en tenants distintos nunca colisione.
    """
    base = "\x1f".join(
        (
            str(contexto_empresarial or "").strip(),
            str(tipo_evento or "").strip(),
            str(numero_transporte or "").strip(),
        )
    )
    return hashlib.sha256(base.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------
# Enriquecimiento desde la operación vigente (sólo cuando es INEQUÍVOCO)
# --------------------------------------------------------------------------

_PATRON_FECHA_DMY = re.compile(r"^(\d{1,2})[-/](\d{1,2})[-/](\d{4})$")
_PATRON_FECHA_ISO = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


def _fecha_operacional_iso(valor: object) -> str:
    texto = str(valor or "").strip()
    if not texto:
        return ""
    m = _PATRON_FECHA_ISO.match(texto)
    if m:
        return texto
    m = _PATRON_FECHA_DMY.match(texto)
    if m:
        dia, mes, anio = m.groups()
        return f"{anio}-{int(mes):02d}-{int(dia):02d}"
    return ""


def _multivalor(valor: object) -> list[str]:
    crudo = str(valor or "").strip()
    if not crudo:
        return []
    return [p.strip() for p in crudo.split("|") if p.strip()]


def _enriquecimiento_incompleto(motivo: str) -> dict:
    return {
        "viaje_id": "",
        "numeros_guia": [],
        "fecha_operacional": "",
        "snapshot": {},
        "vinculo_completo": False,
        "motivo_vinculo_incompleto": motivo,
    }


def resolver_enriquecimiento_transporte(
    *, raiz: str | Path, numero_transporte: str
) -> dict:
    """Busca la asociación VIGENTE por ``numero_transporte`` en el reporte
    oficial (`viajes.csv`, el mismo que ya consume Desktop) y devuelve
    viaje/guías/fecha/snapshot SÓLO si es inequívoca (exactamente un
    viaje). Nunca inventa datos: 0 viajes -> ``SIN_VIAJE_ASOCIADO``, >1
    -> ``TRANSPORTE_AMBIGUO``; en ambos casos ``vinculo_completo=False``.
    """
    numero_transporte = str(numero_transporte or "").strip()
    if not numero_transporte:
        return _enriquecimiento_incompleto("SIN_NUMERO_TRANSPORTE")
    raiz = Path(raiz)
    estado = leer_estado_operacion(raiz=raiz)
    if not estado:
        return _enriquecimiento_incompleto("SIN_OPERACION_VIGENTE")
    reporte_rel = str(estado.get("reporte_vigente", "")).strip()
    if not reporte_rel:
        return _enriquecimiento_incompleto("SIN_REPORTE_VIGENTE")
    ruta_viajes = raiz / reporte_rel / "viajes.csv"
    if not ruta_viajes.is_file():
        return _enriquecimiento_incompleto("REPORTE_VIGENTE_NO_ENCONTRADO")
    # Import perezoso: `consultas_atlas` arrastra medio Core y este módulo
    # lo usan CLIs muy chicos que no quieren pagar ese import si sólo
    # listan.
    from atlas_core.consultas_atlas import cargar_viajes

    try:
        filas = [
            f
            for f in cargar_viajes(ruta_viajes)
            if str(f.get("numero_transporte", "")).strip() == numero_transporte
        ]
    except OSError:
        return _enriquecimiento_incompleto("REPORTE_VIGENTE_NO_LEGIBLE")
    if not filas:
        return _enriquecimiento_incompleto("SIN_VIAJE_ASOCIADO")
    if len(filas) > 1:
        return _enriquecimiento_incompleto("TRANSPORTE_AMBIGUO")
    fila = filas[0]
    return {
        "viaje_id": str(fila.get("viaje_id", "")).strip(),
        "numeros_guia": _multivalor(fila.get("numeros_guia", "")),
        "fecha_operacional": _fecha_operacional_iso(fila.get("fecha", "")),
        "snapshot": {
            "chofer": str(fila.get("choferes", "")).strip(),
            "rut_chofer": str(fila.get("ruts_chofer", "")).strip(),
            "patentes_tracto": _multivalor(fila.get("patentes_tracto", "")),
            "patentes_rampla": _multivalor(fila.get("patentes_rampla", "")),
        },
        "vinculo_completo": True,
        "motivo_vinculo_incompleto": "",
    }


# --------------------------------------------------------------------------
# Escritura -- registrar / anular / reactivar
# --------------------------------------------------------------------------

def _procedencia_normalizada(origen: str, referencia: str, *, en: str) -> dict:
    return {
        "origen": str(origen or "").strip() or "DESCONOCIDO",
        "referencia": str(referencia or "").strip(),
        "registrado_en": en,
    }


def _mismo_par_procedencia(a: Mapping[str, object], b: Mapping[str, object]) -> bool:
    return (
        str(a.get("origen", "")) == str(b.get("origen", ""))
        and str(a.get("referencia", "")) == str(b.get("referencia", ""))
    )


def _aplicar_enriquecimiento(evento: dict, enriquecimiento: Mapping[str, object]) -> None:
    evento["viaje_id"] = str(enriquecimiento.get("viaje_id", "") or "")
    evento["numeros_guia"] = list(enriquecimiento.get("numeros_guia", []) or [])
    evento["fecha_operacional"] = str(enriquecimiento.get("fecha_operacional", "") or "")
    snapshot = enriquecimiento.get("snapshot") or {}
    evento["snapshot"] = dict(snapshot) if isinstance(snapshot, Mapping) else {}
    evento["vinculo_completo"] = bool(enriquecimiento.get("vinculo_completo", False))
    evento["motivo_vinculo_incompleto"] = str(
        enriquecimiento.get("motivo_vinculo_incompleto", "") or ""
    )


def registrar_evento(
    *,
    raiz: str | Path | None = None,
    tipo_evento: str,
    numero_transporte: str,
    nota: str = "",
    contexto_empresarial: str = CONTEXTO_EMPRESARIAL_SIN_ASIGNAR,
    origen: str,
    referencia: str = "",
    enriquecimiento: Mapping[str, object] | None = None,
    reloj: Callable[[], datetime] = _RELOJ_UTC,
) -> dict:
    """Registra (o reactiva, o deja igual) un hecho MARCA_VIAJE.

    Idempotente por ``clave_idempotencia``:

    - no existe        -> se crea ACTIVO (``creado=True``);
    - existe ACTIVO    -> no se duplica; sólo se fusiona nota/procedencia
      nuevas si las hay (``creado=False``);
    - existe ANULADO   -> se REACTIVA el MISMO ``evento_id``
      (``reactivado=True``), nunca se crea otro hecho lógico.

    ``enriquecimiento`` es el dict de ``resolver_enriquecimiento_
    transporte`` (o ``None`` -> el evento queda con vínculo incompleto
    explícito ``SIN_ENRIQUECIMIENTO``). Nunca inventa: si el
    enriquecimiento dice que la asociación es ambigua/ausente, el evento
    se guarda igual con ``vinculo_completo=False``.
    """
    tipo_evento = str(tipo_evento or "").strip()
    numero_transporte = str(numero_transporte or "").strip()
    contexto_empresarial = str(contexto_empresarial or "").strip() or CONTEXTO_EMPRESARIAL_SIN_ASIGNAR
    if not tipo_evento:
        raise ValueError("tipo_evento es obligatorio.")
    if not numero_transporte:
        raise ValueError("numero_transporte es obligatorio (clave de idempotencia MARCA_VIAJE).")

    ruta = ruta_eventos_operacionales(raiz=raiz)
    clave = clave_idempotencia(
        contexto_empresarial=contexto_empresarial,
        tipo_evento=tipo_evento,
        numero_transporte=numero_transporte,
    )

    with bloqueo_sesion(ruta.parent, NOMBRE_LOCK):
        documento = _cargar_para_escritura(ruta)
        ahora = reloj().astimezone(timezone.utc).isoformat()
        procedencia = _procedencia_normalizada(origen, referencia, en=ahora)

        existente = next(
            (e for e in documento["eventos"] if e.get("clave_idempotencia") == clave),
            None,
        )

        if existente is None:
            evento = {
                "evento_id": str(uuid4()),
                "version": 1,
                "contexto_empresarial": contexto_empresarial,
                "tipo_evento": tipo_evento,
                "naturaleza": NATURALEZA_MARCA_VIAJE,
                "numero_transporte": numero_transporte,
                "viaje_id": "",
                "numeros_guia": [],
                "fecha_operacional": "",
                "snapshot": {},
                "nota": str(nota or ""),
                "estado": ESTADO_ACTIVO,
                "vinculo_completo": False,
                "motivo_vinculo_incompleto": "SIN_ENRIQUECIMIENTO",
                "procedencias": [procedencia],
                "clave_idempotencia": clave,
                "creado_en": ahora,
                "actualizado_en": ahora,
                "historial": [
                    {
                        "accion": "CREADO",
                        "en": ahora,
                        "origen": procedencia["origen"],
                        "detalle": {"nota_presente": bool(str(nota or "").strip())},
                    }
                ],
            }
            if enriquecimiento is not None:
                _aplicar_enriquecimiento(evento, enriquecimiento)
                evento["historial"].append(
                    {
                        "accion": "ENRIQUECIDO",
                        "en": ahora,
                        "origen": procedencia["origen"],
                        "detalle": {
                            "vinculo_completo": evento["vinculo_completo"],
                            "motivo": evento["motivo_vinculo_incompleto"],
                        },
                    }
                )
            documento["eventos"].append(evento)
            _publicar(ruta, documento, ahora)
            return {
                "ok": True,
                "creado": True,
                "reactivado": False,
                "cambio": True,
                "evento": json.loads(json.dumps(evento)),
            }

        # Ya existe el hecho lógico -- nunca se crea otro.
        cambio = False
        reactivado = False

        if existente.get("estado") != ESTADO_ACTIVO:
            existente["estado"] = ESTADO_ACTIVO
            existente["historial"].append(
                {"accion": "REACTIVADO", "en": ahora, "origen": procedencia["origen"]}
            )
            cambio = True
            reactivado = True

        nota_nueva = str(nota or "")
        if nota_nueva and nota_nueva != str(existente.get("nota", "")):
            existente["nota"] = nota_nueva
            existente["historial"].append(
                {"accion": "NOTA_ACTUALIZADA", "en": ahora, "origen": procedencia["origen"]}
            )
            cambio = True

        procedencias = existente.setdefault("procedencias", [])
        if not any(_mismo_par_procedencia(procedencia, p) for p in procedencias):
            procedencias.append(procedencia)
            cambio = True

        # Sólo se intenta completar un vínculo que HOY está incompleto --
        # mejorar un vínculo incompleto con datos vigentes inequívocos no
        # es "inventar"; nunca se pisa un vínculo ya completo.
        if (
            enriquecimiento is not None
            and not existente.get("vinculo_completo")
            and enriquecimiento.get("vinculo_completo")
        ):
            _aplicar_enriquecimiento(existente, enriquecimiento)
            existente["historial"].append(
                {"accion": "VINCULO_COMPLETADO", "en": ahora, "origen": procedencia["origen"]}
            )
            cambio = True

        if cambio:
            existente["version"] = int(existente.get("version", 1)) + 1
            existente["actualizado_en"] = ahora
            _publicar(ruta, documento, ahora)

        return {
            "ok": True,
            "creado": False,
            "reactivado": reactivado,
            "cambio": cambio,
            "evento": json.loads(json.dumps(existente)),
        }


def anular_evento(
    *,
    raiz: str | Path | None = None,
    tipo_evento: str,
    numero_transporte: str,
    contexto_empresarial: str = CONTEXTO_EMPRESARIAL_SIN_ASIGNAR,
    origen: str,
    referencia: str = "",
    motivo: str = "",
    reloj: Callable[[], datetime] = _RELOJ_UTC,
) -> dict:
    """Anula el hecho lógico SIN borrarlo físicamente (``estado`` ->
    ANULADO). Idempotente: anular algo inexistente o ya anulado es un
    no-op exitoso (``anulado=False``).
    """
    tipo_evento = str(tipo_evento or "").strip()
    numero_transporte = str(numero_transporte or "").strip()
    contexto_empresarial = str(contexto_empresarial or "").strip() or CONTEXTO_EMPRESARIAL_SIN_ASIGNAR
    if not tipo_evento or not numero_transporte:
        raise ValueError("tipo_evento y numero_transporte son obligatorios.")

    ruta = ruta_eventos_operacionales(raiz=raiz)
    clave = clave_idempotencia(
        contexto_empresarial=contexto_empresarial,
        tipo_evento=tipo_evento,
        numero_transporte=numero_transporte,
    )

    with bloqueo_sesion(ruta.parent, NOMBRE_LOCK):
        documento = _cargar_para_escritura(ruta)
        ahora = reloj().astimezone(timezone.utc).isoformat()
        existente = next(
            (e for e in documento["eventos"] if e.get("clave_idempotencia") == clave),
            None,
        )
        if existente is None:
            return {"ok": True, "encontrado": False, "anulado": False, "ya_anulado": False, "evento": None}
        if existente.get("estado") == ESTADO_ANULADO:
            return {
                "ok": True,
                "encontrado": True,
                "anulado": False,
                "ya_anulado": True,
                "evento": json.loads(json.dumps(existente)),
            }
        existente["estado"] = ESTADO_ANULADO
        existente["version"] = int(existente.get("version", 1)) + 1
        existente["actualizado_en"] = ahora
        entrada = {"accion": "ANULADO", "en": ahora, "origen": str(origen or "").strip() or "DESCONOCIDO"}
        if str(motivo or "").strip():
            entrada["motivo"] = str(motivo).strip()
        existente["historial"].append(entrada)
        procedencia = _procedencia_normalizada(origen, referencia, en=ahora)
        procedencias = existente.setdefault("procedencias", [])
        if not any(_mismo_par_procedencia(procedencia, p) for p in procedencias):
            procedencias.append(procedencia)
        _publicar(ruta, documento, ahora)
        return {
            "ok": True,
            "encontrado": True,
            "anulado": True,
            "ya_anulado": False,
            "evento": json.loads(json.dumps(existente)),
        }


def _publicar(ruta: Path, documento: dict, ahora: str) -> None:
    documento["schema_version"] = SCHEMA_VERSION
    documento["revision"] = int(documento.get("revision", 0)) + 1
    documento["actualizado_en"] = ahora
    escribir_json_atomico(ruta, documento)


# --------------------------------------------------------------------------
# Lectura para Desktop / consultas
# --------------------------------------------------------------------------

def listar_eventos_por_transporte(
    *,
    raiz: str | Path | None = None,
    numero_transporte: str,
    contexto_empresarial: str | None = None,
    incluir_anulados: bool = True,
) -> list[dict]:
    """Todos los eventos canónicos de un ``numero_transporte`` (lo mínimo
    que Desktop necesita para pintar el estado). Read-only y tolerante.
    """
    numero_transporte = str(numero_transporte or "").strip()
    documento = leer_eventos_operacionales(raiz=raiz)
    salida: list[dict] = []
    for evento in documento.get("eventos", []):
        if str(evento.get("numero_transporte", "")).strip() != numero_transporte:
            continue
        if contexto_empresarial is not None and str(
            evento.get("contexto_empresarial", "")
        ) != str(contexto_empresarial):
            continue
        if not incluir_anulados and evento.get("estado") == ESTADO_ANULADO:
            continue
        salida.append(json.loads(json.dumps(evento)))
    return salida
