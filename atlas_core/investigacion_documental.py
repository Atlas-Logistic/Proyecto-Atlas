"""Cuarentena reversible de un documento: EN_INVESTIGACION.

Un documento EN_INVESTIGACION no es un documento incorrecto: su evidencia o
su interpretación está bajo investigación y, mientras tanto, no debe
producir decisiones humanas ni aprendizaje. Nunca es una respuesta humana:
no escribe en el ledger (`decisiones_aplicadas.json`), no toca dataset,
catálogos, viajes ni rutas, y conserva la evidencia.

Registro: ``operacion/actual/documentos_en_investigacion.json`` (junto al
ledger). Identidad estable del documento: su ``archivo`` (el mismo
identificador de dataset/bandeja/evidencia) más el SHA-256 de su evidencia
cuando está disponible -- otro documento con el mismo nombre pero otro
contenido nunca queda en cuarentena por accidente.

Mientras está ACTIVA:
- `decisiones_pendientes._generar_artefacto_sin_lock` (el único escritor de
  la bandeja) y `regenerar_decisiones_persistidas` excluyen sus decisiones:
  ningún detector, regeneración ni mantenimiento puede republicarlas;
- las decisiones que estaban pendientes quedan RETENIDAS en el registro
  (trazabilidad) y vuelven a evaluarse al levantarla;
- `aplicar_decision_obra` rechaza aplicar una decisión suya;
- B1 no la investiga ni la usa como historial;
- su evidencia no se mueve a "resuelta" ni se purga.
"""
from __future__ import annotations

import csv
import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping

from atlas_core.almacenamiento_portable import bloqueo_sesion, escribir_json_atomico

NOMBRE_REGISTRO = "documentos_en_investigacion.json"
ESTADO_ACTIVA = "ACTIVA"
ESTADO_LEVANTADA = "LEVANTADA"
ESTADO_CUARENTENA = "EN_INVESTIGACION"


def _actual(raiz_atlas: str | Path) -> Path:
    return Path(raiz_atlas) / "operacion" / "actual"


def ruta_registro(raiz_atlas: str | Path) -> Path:
    return _actual(raiz_atlas) / NOMBRE_REGISTRO


def raiz_desde_actual(carpeta_actual: str | Path) -> Path | None:
    """Raíz Atlas si `carpeta_actual` es ``<raiz>/operacion/actual``."""
    carpeta = Path(carpeta_actual)
    if carpeta.name == "actual" and carpeta.parent.name == "operacion":
        return carpeta.parent.parent
    return None


def leer_registro(raiz_atlas: str | Path) -> dict:
    try:
        contenido = json.loads(ruta_registro(raiz_atlas).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"schema_version": 1, "registros": []}
    if not isinstance(contenido, dict) or not isinstance(contenido.get("registros"), list):
        return {"schema_version": 1, "registros": []}
    return contenido


def _sha256(ruta: Path) -> str:
    digest = hashlib.sha256()
    with ruta.open("rb") as flujo:
        for bloque in iter(lambda: flujo.read(1024 * 1024), b""):
            digest.update(bloque)
    return digest.hexdigest()


def _sha_evidencia(raiz: Path, archivo: str) -> str | None:
    from atlas_core.evidencia_documental import resolver_ruta_evidencia

    try:
        ruta = resolver_ruta_evidencia(raiz, archivo).ruta
    except Exception:
        return None
    return _sha256(ruta) if ruta is not None and ruta.is_file() else None


def _vigente(raiz: Path, registro: Mapping[str, object]) -> bool:
    """Cuarentena ACTIVA que corresponde a la evidencia vigente de su
    `archivo`. Con hash registrado y evidencia disponible con OTRO hash, es
    otro documento: no aplica. Sin evidencia (p. ej. purgada) se conserva
    por identificador -- conservador."""
    if registro.get("estado") != ESTADO_ACTIVA:
        return False
    sha = registro.get("sha256_evidencia")
    if not sha:
        return True
    actual = _sha_evidencia(raiz, str(registro.get("archivo", "")))
    return actual is None or actual == sha


def archivos_en_investigacion(raiz_atlas: str | Path | None) -> frozenset[str]:
    """`archivo` de cada documento con cuarentena ACTIVA y vigente."""
    if raiz_atlas is None:
        return frozenset()
    raiz = Path(raiz_atlas)
    if not ruta_registro(raiz).is_file():
        return frozenset()
    return frozenset(
        str(r.get("archivo", "")) for r in leer_registro(raiz)["registros"]
        if isinstance(r, dict) and r.get("archivo") and _vigente(raiz, r)
    )


def excluir_decisiones_en_investigacion(
    decisiones: Iterable[Mapping[str, object]], archivos: frozenset[str],
) -> list[dict]:
    decisiones = [dict(d) for d in decisiones]
    if not archivos:
        return decisiones
    return [
        d for d in decisiones
        if str((d.get("documento") or {}).get("archivo", "")) not in archivos
    ]


def _fila_documento(raiz: Path, archivo: str) -> dict[str, str] | None:
    dataset = _actual(raiz) / "analisis_completo_guias.csv"
    try:
        with dataset.open("r", newline="", encoding="utf-8-sig") as flujo:
            for fila in csv.DictReader(flujo, delimiter=";"):
                if str(fila.get("archivo", "")) == archivo:
                    return dict(fila)
    except (OSError, UnicodeDecodeError):
        return None
    return None


def _publicar_bandeja(raiz: Path, decisiones: list[dict], reloj) -> dict:
    from atlas_core.decisiones_pendientes import NOMBRE_ARTEFACTO, _generar_artefacto_sin_lock

    actual = _actual(raiz)
    return _generar_artefacto_sin_lock(
        ruta_dataset=actual / "analisis_completo_guias.csv", carpeta_catalogos=raiz / "catalogos_privados",
        decisiones=decisiones, ruta_salida=actual / NOMBRE_ARTEFACTO, reloj=reloj,
    )


def _bandeja(raiz: Path) -> list[dict]:
    from atlas_core.decisiones_pendientes import NOMBRE_ARTEFACTO

    try:
        contenido = json.loads((_actual(raiz) / NOMBRE_ARTEFACTO).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [d for d in contenido.get("decisiones", []) if isinstance(d, dict)]


def poner_en_investigacion(
    *, raiz_atlas: str | Path, archivo: str, actor: str, motivo: str,
    referencia_investigacion: str, reloj=lambda: datetime.now(timezone.utc),
) -> dict[str, object]:
    """Activa la cuarentena del documento `archivo`. Idempotente: si ya hay
    una ACTIVA vigente, no cambia nada. Retiene (en el registro) sus
    decisiones pendientes y las retira de la bandeja activa. Nunca escribe
    el ledger, el dataset ni catálogos."""
    from atlas_core.decisiones_pendientes import NOMBRE_LOCK_DECISIONES_PENDIENTES

    raiz = Path(raiz_atlas)
    archivo = str(archivo or "").strip()
    if not archivo or not str(actor or "").strip() or not str(motivo or "").strip():
        return {"ok": False, "motivo": "ARCHIVO_ACTOR_Y_MOTIVO_OBLIGATORIOS"}
    fila = _fila_documento(raiz, archivo)
    if fila is None:
        return {"ok": False, "motivo": "DOCUMENTO_NO_ENCONTRADO_EN_DATASET", "archivo": archivo}
    sha = _sha_evidencia(raiz, archivo)
    with bloqueo_sesion(_actual(raiz), NOMBRE_LOCK_DECISIONES_PENDIENTES):
        contenido = leer_registro(raiz)
        vigentes = [r for r in contenido["registros"] if r.get("archivo") == archivo and _vigente(raiz, r)]
        if vigentes:
            return {"ok": True, "idempotente": True, "cuarentena_id": vigentes[0]["cuarentena_id"],
                    "archivo": archivo, "decisiones_retenidas": [
                        d.get("decision_id") for d in vigentes[0].get("decisiones_retenidas", [])]}
        bandeja = _bandeja(raiz)
        retenidas = [
            d for d in bandeja
            if str((d.get("documento") or {}).get("archivo", "")) == archivo and d.get("estado") == "PENDIENTE"
        ]
        registro = {
            "cuarentena_id": str(uuid.uuid4()),
            "estado": ESTADO_ACTIVA,
            "archivo": archivo,
            "sha256_evidencia": sha,
            "numero_guia": str(fila.get("numero_guia", "")),
            "numero_transporte": str(fila.get("numero_transporte", "")),
            "actor": str(actor).strip(),
            "motivo": str(motivo).strip(),
            "referencia_investigacion": str(referencia_investigacion or "").strip(),
            "activada_en": reloj().astimezone(timezone.utc).isoformat(),
            "decisiones_retenidas": retenidas,
            "levantada_en": None, "levantada_por": None, "motivo_levantamiento": None,
        }
        contenido["registros"].append(registro)
        escribir_json_atomico(ruta_registro(raiz), contenido)
        # El escritor de la bandeja ya excluye el documento: reescribirla
        # con la bandeja vigente retira sus decisiones sin tocar ninguna otra.
        _publicar_bandeja(raiz, bandeja, reloj)
    return {"ok": True, "idempotente": False, "cuarentena_id": registro["cuarentena_id"],
            "archivo": archivo, "sha256_evidencia": sha,
            "decisiones_retenidas": [d.get("decision_id") for d in retenidas]}


def levantar_investigacion(
    *, raiz_atlas: str | Path, archivo: str, actor: str, motivo: str,
    reloj=lambda: datetime.now(timezone.utc),
) -> dict[str, object]:
    """Levanta la cuarentena ACTIVA de `archivo` (queda LEVANTADA, nunca se
    borra) y devuelve sus decisiones retenidas a la evaluación normal:
    `regenerar_decisiones_persistidas` decide, con la evidencia vigente,
    cuáles siguen siendo una pregunta real. Idempotente."""
    from atlas_core.decisiones_pendientes import NOMBRE_LOCK_DECISIONES_PENDIENTES, regenerar_decisiones_persistidas

    raiz = Path(raiz_atlas)
    archivo = str(archivo or "").strip()
    if not archivo or not str(actor or "").strip() or not str(motivo or "").strip():
        return {"ok": False, "motivo": "ARCHIVO_ACTOR_Y_MOTIVO_OBLIGATORIOS"}
    with bloqueo_sesion(_actual(raiz), NOMBRE_LOCK_DECISIONES_PENDIENTES):
        contenido = leer_registro(raiz)
        activas = [r for r in contenido["registros"] if r.get("archivo") == archivo and r.get("estado") == ESTADO_ACTIVA]
        if not activas:
            return {"ok": True, "idempotente": True, "archivo": archivo, "decisiones_reevaluadas": []}
        instante = reloj().astimezone(timezone.utc).isoformat()
        retenidas: list[dict] = []
        for registro in activas:
            registro.update(estado=ESTADO_LEVANTADA, levantada_en=instante,
                            levantada_por=str(actor).strip(), motivo_levantamiento=str(motivo).strip())
            retenidas.extend(registro.get("decisiones_retenidas", []))
        escribir_json_atomico(ruta_registro(raiz), contenido)
        actual = _actual(raiz)
        vigentes = regenerar_decisiones_persistidas(
            decisiones=[*_bandeja(raiz), *retenidas], carpeta_catalogos=raiz / "catalogos_privados",
            ruta_dataset=actual / "analisis_completo_guias.csv",
        )
        bandeja = _publicar_bandeja(raiz, vigentes, reloj)
    devueltas = {str(d.get("decision_id")) for d in bandeja["decisiones"]
                 if str((d.get("documento") or {}).get("archivo", "")) == archivo}
    return {"ok": True, "idempotente": False, "archivo": archivo,
            "decisiones_reevaluadas": sorted(devueltas)}


def decision_en_investigacion(raiz_atlas: str | Path, decision_id: str) -> dict | None:
    """Registro ACTIVO que retiene `decision_id`, si lo hay."""
    raiz = Path(raiz_atlas)
    if not ruta_registro(raiz).is_file():
        return None
    for registro in leer_registro(raiz)["registros"]:
        if registro.get("estado") != ESTADO_ACTIVA:
            continue
        if any(str(d.get("decision_id")) == str(decision_id) for d in registro.get("decisiones_retenidas", [])):
            return registro if _vigente(raiz, registro) else None
    return None
