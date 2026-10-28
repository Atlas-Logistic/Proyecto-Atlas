"""Expediente digital de choferes y vehículos -- etapa 1 (base persistente).

Registro append-only de documentos (licencia de conducir, revisión técnica,
SOAP, permiso de circulación) asociados a identidades EXISTENTES de los
catálogos `choferes.json` / `vehiculos.json`: nunca crea ni copia una
identidad, sólo la referencia (clave del chofer, `vehiculo_id`).

Almacén por empresa, junto al de fichas (`fichas_digitales/<EMPRESA>/
expediente_documentos.json`), con la misma validación de empresa que
`fichas_choferes.ruta_almacen`: la separación multiempresa queda preparada
sin interfaz todavía. Registrar un documento del mismo tipo para la misma
identidad marca el anterior como reemplazado; nada se borra.

El estado de vencimiento es SIEMPRE derivado (`estado_expediente`), nunca se
persiste. Las licencias ya registradas en las fichas de choferes
(`fichas_documentales.json`) se incluyen en la vista sólo como lectura.
Fuera de alcance: carga de archivos, interfaz, alertas y Mobile.
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import date, datetime, timezone
from pathlib import Path, PureWindowsPath
from typing import Callable

from atlas_core.almacenamiento_portable import bloqueo_sesion, escribir_json_atomico

VERSION = 1
NOMBRE_ALMACEN = "expediente_documentos.json"
CHOFER, VEHICULO = "CHOFER", "VEHICULO"
TIPOS_POR_ENTIDAD = {
    CHOFER: frozenset({"LICENCIA_CONDUCIR"}),
    VEHICULO: frozenset({"REVISION_TECNICA", "SOAP", "PERMISO_CIRCULACION"}),
}
DIAS_POR_VENCER = 30
VENCIDO, POR_VENCER, VIGENTE, SIN_VENCIMIENTO = "VENCIDO", "POR_VENCER", "VIGENTE", "SIN_VENCIMIENTO"


class ErrorExpedienteDigital(ValueError):
    pass


def ruta_almacen_expediente(raiz: str | Path, empresa: str) -> Path:
    from atlas_core.fichas_choferes import ruta_almacen
    try:
        return ruta_almacen(raiz, empresa).with_name(NOMBRE_ALMACEN)
    except ValueError as error:
        raise ErrorExpedienteDigital(str(error)) from error


def _vacio(empresa: str) -> dict:
    return {"version": VERSION, "empresa": empresa, "revision": 0, "documentos": []}


def leer_expediente(raiz: str | Path, *, empresa: str) -> dict:
    """Lectura pura: un almacén ausente es un expediente vacío (no se crea)."""
    ruta = ruta_almacen_expediente(raiz, empresa)
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return _vacio(empresa)
    except (OSError, ValueError) as error:
        raise ErrorExpedienteDigital(f"expediente ilegible: {error}") from error
    if not isinstance(datos, dict) or datos.get("version") != VERSION or datos.get("empresa") != empresa \
            or not isinstance(datos.get("documentos"), list):
        raise ErrorExpedienteDigital("versión o empresa del expediente incompatible")
    return datos


# ------------------------------------------------------------------ identidad


def _referencia_chofer(catalogos: Path, referencia: str) -> str:
    from atlas_core.catalogos import cargar_catalogo_json, normalizar_rut
    choferes = cargar_catalogo_json(catalogos / "choferes.json")
    if referencia in choferes:
        return referencia
    buscado = normalizar_rut(referencia)
    claves = [k for k, r in choferes.items() if isinstance(r, dict) and buscado
              and buscado in {normalizar_rut(k), normalizar_rut(str(r.get("rut", "")))}]
    if len(claves) != 1:
        raise ErrorExpedienteDigital("el chofer no existe (o no es único) en el catálogo")
    return claves[0]


def _referencia_vehiculo(catalogos: Path, referencia: str) -> str:
    from atlas_core.catalogo_vehiculos import cargar_catalogo_vehiculos, normalizar_patente_vehiculo
    vehiculos = cargar_catalogo_vehiculos(catalogos / "vehiculos.json").vehiculos
    patente = normalizar_patente_vehiculo(referencia)
    coincidentes = [v for v in vehiculos if v.vehiculo_id == referencia or v.patente_canonica == patente]
    if len(coincidentes) != 1:
        raise ErrorExpedienteDigital("el vehículo no existe (o no es único) en el catálogo")
    return coincidentes[0].vehiculo_id


def _fecha(valor: object) -> str:
    texto = str(valor or "").strip()
    try:
        return date.fromisoformat(texto).isoformat() if re.fullmatch(r"\d{4}-\d{2}-\d{2}", texto) else _invalida()
    except ValueError:
        return _invalida()


def _invalida() -> str:
    raise ErrorExpedienteDigital("la fecha de vencimiento debe ser AAAA-MM-DD")


def _archivo(valor: object) -> str:
    """Referencia relativa dentro del almacén de la empresa (`archivos/...`);
    esta etapa no copia ni abre archivos."""
    texto = str(valor or "").strip().replace("\\", "/")
    if not texto:
        return ""
    partes = PureWindowsPath(texto)
    if partes.is_absolute() or partes.drive or ".." in partes.parts or partes.parts[0] != "archivos":
        raise ErrorExpedienteDigital("la referencia al archivo debe estar dentro de archivos/ de la empresa")
    return texto


# ------------------------------------------------------------------ escritura


def registrar_documento(
    raiz: str | Path, *, empresa: str, entidad: str, referencia: str, tipo: str,
    fecha_vencimiento: str, archivo: str = "", sha256: str = "", actor: str,
    carpeta_catalogos: str | Path | None = None, reloj: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
) -> dict:
    """Agrega un documento vigente; el anterior del mismo tipo e identidad
    queda `reemplazado_por` el nuevo. Nunca toca los catálogos."""
    entidad, tipo = str(entidad).upper(), str(tipo).upper()
    if tipo not in TIPOS_POR_ENTIDAD.get(entidad, ()):
        raise ErrorExpedienteDigital(f"tipo {tipo!r} no admitido para {entidad!r}")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}", str(actor or "")):
        raise ErrorExpedienteDigital("actor obligatorio")
    if sha256 and not re.fullmatch(r"[0-9a-f]{64}", sha256):
        raise ErrorExpedienteDigital("sha256 inválido")
    catalogos = Path(carpeta_catalogos) if carpeta_catalogos else Path(raiz) / "catalogos_privados"
    clave = (_referencia_chofer if entidad == CHOFER else _referencia_vehiculo)(catalogos, str(referencia).strip())
    ruta = ruta_almacen_expediente(raiz, empresa)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with bloqueo_sesion(ruta.parent, "expediente_documentos"):
        datos = leer_expediente(raiz, empresa=empresa)
        instante = reloj().astimezone(timezone.utc).isoformat()
        documento = {
            "documento_id": str(uuid.uuid4()), "entidad": entidad, "referencia_catalogo": clave, "tipo": tipo,
            "fecha_vencimiento": _fecha(fecha_vencimiento), "archivo": _archivo(archivo), "sha256": sha256,
            "registrado_en": instante, "actor": actor, "reemplazado_por": "",
        }
        for previo in datos["documentos"]:
            if (previo["entidad"], previo["referencia_catalogo"], previo["tipo"]) == (entidad, clave, tipo) \
                    and not previo.get("reemplazado_por"):
                previo["reemplazado_por"] = documento["documento_id"]
        datos["documentos"].append(documento)
        datos["revision"] = int(datos.get("revision", 0)) + 1
        escribir_json_atomico(ruta, datos)
    return documento


# ------------------------------------------------------------------ vista derivada


def estado_vencimiento(fecha_vencimiento: str, *, hoy: date, dias_por_vencer: int = DIAS_POR_VENCER) -> str:
    if not fecha_vencimiento:
        return SIN_VENCIMIENTO
    restantes = (date.fromisoformat(fecha_vencimiento) - hoy).days
    return VENCIDO if restantes < 0 else POR_VENCER if restantes <= dias_por_vencer else VIGENTE


def _licencias_de_fichas(raiz: str | Path, empresa: str) -> list[dict]:
    """Licencias ya registradas en las fichas de choferes (sólo lectura)."""
    from atlas_core.fichas_choferes import leer_almacen
    try:
        fichas = leer_almacen(raiz, empresa=empresa)
    except (OSError, ValueError):
        return []
    documentos = []
    for ficha in (fichas or {}).get("choferes", []) if (fichas or {}).get("version") == 2 else []:
        for doc in ficha.get("documentos", []):
            if doc.get("tipo") == "LICENCIA_CONDUCIR" and not doc.get("reemplazado_por") and ficha.get(
                    "referencias_catalogo"):
                documentos.append({
                    "documento_id": doc["documento_id"], "entidad": CHOFER,
                    "referencia_catalogo": ficha["referencias_catalogo"][0], "tipo": "LICENCIA_CONDUCIR",
                    "fecha_vencimiento": str(doc.get("vencimiento", "")), "archivo": str(doc.get("archivo", "")),
                    "sha256": str(doc.get("sha256", "")), "fuente": "FICHA_CHOFER",
                })
    return documentos


def estado_expediente(raiz: str | Path, *, empresa: str, hoy: date | None = None,
                      dias_por_vencer: int = DIAS_POR_VENCER) -> list[dict]:
    """Documentos vigentes (no reemplazados) con su estado de vencimiento
    derivado a la fecha `hoy`. Incluye las licencias de las fichas de
    choferes que el expediente no registró. Nunca escribe."""
    hoy = hoy or date.today()
    propios = [{**d, "fuente": "EXPEDIENTE"} for d in leer_expediente(raiz, empresa=empresa)["documentos"]
               if not d.get("reemplazado_por")]
    cubiertos = {(d["entidad"], d["referencia_catalogo"], d["tipo"]) for d in propios}
    externos = [d for d in _licencias_de_fichas(raiz, empresa)
                if (d["entidad"], d["referencia_catalogo"], d["tipo"]) not in cubiertos]
    vista = []
    for d in propios + externos:
        estado = estado_vencimiento(d["fecha_vencimiento"], hoy=hoy, dias_por_vencer=dias_por_vencer)
        dias = (date.fromisoformat(d["fecha_vencimiento"]) - hoy).days if d["fecha_vencimiento"] else None
        vista.append({**d, "estado_vencimiento": estado, "dias_para_vencer": dias})
    return sorted(vista, key=lambda d: (d["dias_para_vencer"] is None, d["dias_para_vencer"] or 0))


def documentos_por_atender(raiz: str | Path, *, empresa: str, hoy: date | None = None,
                           dias_por_vencer: int = DIAS_POR_VENCER) -> list[dict]:
    """Vencidos y próximos a vencer (base para alertas de una etapa futura)."""
    return [d for d in estado_expediente(raiz, empresa=empresa, hoy=hoy, dias_por_vencer=dias_por_vencer)
            if d["estado_vencimiento"] in (VENCIDO, POR_VENCER)]
