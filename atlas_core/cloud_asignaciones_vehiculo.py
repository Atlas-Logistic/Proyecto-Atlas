"""Publicación segura Motor -> Cloud de asignaciones chofer--vehículo.

Contrato propuesto para el Worker documental de Cloud ``b634413`` (aún no
desplegado): ``POST /api/motor/asignaciones-vehiculo/snapshot`` usa la misma
autenticación Bearer de Motor. Cloud determina ``empresa_id`` desde ese token
(nunca desde el body), valida los datos y reemplaza *sólo* las filas de esa
empresa en ``asignaciones_vehiculo_cloud``. Por eso una omisión del snapshot
es una revocación explícita y no puede afectar a otra empresa.

Esta pieza no se engancha al PULL ni se ejecuta por agenda. Su invocación
requiere una decisión de despliegue/activación independiente.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable, Iterable, Mapping

from atlas_core.catalogos import normalizar_rut

RUTA_SNAPSHOT = "/api/motor/asignaciones-vehiculo/snapshot"
VERSION_CONTRATO = 1
MAX_EDAD_DIAS_PREDETERMINADA = 31


class ErrorPublicacionAsignaciones(RuntimeError):
    pass


@dataclass(frozen=True)
class AsignacionPublicable:
    chofer_id: str
    patente: str
    vigente_desde: str


def _fecha_evidencia(valor: object) -> datetime | None:
    try:
        fecha = datetime.fromisoformat(str(valor))
    except (TypeError, ValueError):
        return None
    return fecha if fecha.tzinfo else None


def construir_snapshot_asignaciones(
    *, choferes: Mapping[str, object], vehiculos: Iterable[object], ahora: datetime,
    resolver_chofer_cloud: Callable[[str], str | None], max_edad_dias: int = MAX_EDAD_DIAS_PREDETERMINADA,
) -> tuple[list[AsignacionPublicable], list[dict[str, str]]]:
    """Devuelve sólo vínculos humanos, activos, recientes y no ambiguos.

    La identidad de Cloud se recibe desde una tabla/mapeo explícito del
    operador; nunca se inventa a partir de nombre, patente Mobile u OCR.
    Dos patentes candidatas para un RUT son ambigüedad, incluso si una parece
    más reciente: la siguiente publicación la omite y Cloud revoca la previa.
    """
    if ahora.tzinfo is None:
        raise ValueError("ahora debe incluir zona horaria")
    if max_edad_dias < 1:
        raise ValueError("max_edad_dias debe ser positivo")
    limite = ahora.astimezone(timezone.utc) - timedelta(days=max_edad_dias)
    candidatas: dict[str, list[tuple[str, datetime]]] = {}
    descartes: list[dict[str, str]] = []
    for vehiculo in vehiculos:
        if getattr(vehiculo, "estado_calidad", "") != "CONFIRMADO" or getattr(vehiculo, "estado_vigencia", "") != "ACTIVO":
            continue
        patente = str(getattr(vehiculo, "patente_canonica", "")).strip()
        for evidencia in getattr(vehiculo, "evidencias", ()):
            campos = getattr(evidencia, "campos_observados", {})
            rut = normalizar_rut(str(campos.get("rut_chofer_asociado", ""))) if isinstance(campos, Mapping) else ""
            fecha = _fecha_evidencia(getattr(evidencia, "fecha", ""))
            if (getattr(evidencia, "tipo", "") != "CONFIRMACION_HUMANA"
                    or getattr(evidencia, "resultado", "") != "SOPORTA" or not rut or not fecha or fecha < limite):
                continue
            registro = choferes.get(rut)
            if not isinstance(registro, Mapping) or not bool(registro.get("activo")):
                descartes.append({"rut": rut, "patente": patente, "motivo": "CHOFER_NO_ACTIVO"})
                continue
            candidatas.setdefault(rut, []).append((patente, fecha))

    publicables: list[AsignacionPublicable] = []
    usados_cloud: set[str] = set()
    for rut, opciones in sorted(candidatas.items()):
        patentes = {patente for patente, _fecha in opciones}
        if len(patentes) != 1:
            descartes.append({"rut": rut, "patente": "", "motivo": "ASIGNACION_AMBIGUA"})
            continue
        chofer_cloud = str(resolver_chofer_cloud(rut) or "").strip()
        if not chofer_cloud:
            descartes.append({"rut": rut, "patente": next(iter(patentes)), "motivo": "CHOFER_CLOUD_NO_MAPEADO"})
            continue
        if chofer_cloud in usados_cloud:
            descartes.append({"rut": rut, "patente": next(iter(patentes)), "motivo": "CHOFER_CLOUD_AMBIGUO"})
            continue
        usados_cloud.add(chofer_cloud)
        patente = next(iter(patentes))
        vigente = max(fecha for p, fecha in opciones if p == patente).astimezone(timezone.utc).isoformat()
        publicables.append(AsignacionPublicable(chofer_id=chofer_cloud, patente=patente, vigente_desde=vigente))
    return publicables, descartes


def publicar_snapshot_asignaciones(
    *, base_url: str, token_motor: str, asignaciones: Iterable[AsignacionPublicable], timeout: float = 30.0,
) -> dict:
    """Publica un snapshot atómico usando el token Motor existente.

    No acepta ``empresa_id``: el Worker debe tomarla exclusivamente del token
    ``CLOUD_MOTOR_EMPRESA_ID``. Un Cloud sin el endpoint responde error y no
    hay fallback local ni escritura sobre datos operativos.
    """
    url = base_url.rstrip("/") + RUTA_SNAPSHOT
    if urllib.parse.urlparse(url).scheme != "https":
        raise ErrorPublicacionAsignaciones("la publicación Motor--Cloud requiere HTTPS")
    cuerpo = {
        "version": VERSION_CONTRATO,
        "asignaciones": [a.__dict__ for a in sorted(asignaciones, key=lambda a: a.chofer_id)],
    }
    solicitud = urllib.request.Request(url, method="POST", data=json.dumps(cuerpo).encode("utf-8"), headers={
        "Authorization": f"Bearer {token_motor}", "Content-Type": "application/json",
        "User-Agent": "Atlas-Motor-Cloud/1.0",
    })
    try:
        with urllib.request.urlopen(solicitud, timeout=timeout) as respuesta:
            datos = json.loads(respuesta.read())
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as error:
        raise ErrorPublicacionAsignaciones(f"Cloud no aceptó snapshot de asignaciones: {error}") from error
    if datos.get("estado") != "SNAPSHOT_APLICADO":
        raise ErrorPublicacionAsignaciones("respuesta Cloud inválida para snapshot de asignaciones")
    return datos
