"""Expediente digital de choferes y vehículos -- base funcional reutilizable.

Cada chofer o vehículo de los catálogos tiene como máximo un expediente por
empresa, con `expediente_id` propio. El expediente sólo guarda referencias de
identidad (clave del chofer, `vehiculo_id`), nunca nombre, RUT ni patente: un
cambio de datos descriptivos no crea otro expediente. Un cambio de clave de
chofer se reconoce por el vínculo explícito de su ficha
(`referencias_catalogo`), jamás por parecido.

Almacén por empresa, junto al de fichas (`fichas_digitales/<EMPRESA>/
expediente_documentos.json`). Nada se borra: un documento nuevo del mismo tipo
marca el anterior REEMPLAZADO, una corrección deja antes/después en `historial`
y anular sólo cambia el estado. El original es inmutable: la corrección de un
documento nunca cambia su archivo ni su huella, y los originales recibidos se
guardan con nombre único bajo `archivos/expediente/`, sin sobrescribir.

El estado de vencimiento es SIEMPRE derivado, nunca se persiste. Los documentos
de las fichas de choferes y vehículos (`fichas_documentales.json`) entran en la
vista sólo como lectura; uno pendiente de extracción nunca cuenta como vigente
ni satisface un documento obligatorio.

`carpeta_catalogos` es por omisión `<raiz>/catalogos_privados`: el modelo de
Atlas es una raíz por empresa. Dos empresas en una misma raíz deben indicar
cada una su carpeta de catálogos.

`preparar_alertas_vencimiento` sólo calcula candidatas: no notifica ni escribe.
Fuera de alcance: interfaz, envío de notificaciones y Mobile.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import uuid
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path, PureWindowsPath
from typing import Callable, Iterator

from atlas_core.almacenamiento_portable import bloqueo_sesion, escribir_json_atomico

VERSION = 2
NOMBRE_ALMACEN = "expediente_documentos.json"
CHOFER, VEHICULO = "CHOFER", "VEHICULO"
TIPOS_BASE = {
    "LICENCIA_CONDUCIR": {"entidad": CHOFER, "nombre": "Licencia de conducir", "obligatorio": True},
    "REVISION_TECNICA": {"entidad": VEHICULO, "nombre": "Revisión técnica", "obligatorio": True},
    "SOAP": {"entidad": VEHICULO, "nombre": "SOAP", "obligatorio": True},
    "PERMISO_CIRCULACION": {"entidad": VEHICULO, "nombre": "Permiso de circulación", "obligatorio": True},
    "CERTIFICADO_EMISION_GASES": {"entidad": VEHICULO, "nombre": "Certificado de emisión de gases o contaminantes", "obligatorio": True},
    "POLIZA_RESPONSABILIDAD_CIVIL": {"entidad": VEHICULO, "nombre": "Póliza de responsabilidad civil", "obligatorio": True},
    "POLIZA_ROBO": {"entidad": VEHICULO, "nombre": "Póliza de seguro contra robos", "obligatorio": False},
    "SEGURO_CARGA": {"entidad": VEHICULO, "nombre": "Seguro de carga", "obligatorio": False},
}
TIPOS_POLIZA = frozenset({"POLIZA_RESPONSABILIDAD_CIVIL", "POLIZA_ROBO"})
DIAS_POR_VENCER = 30
VENCIDO, POR_VENCER, VIGENTE, SIN_VENCIMIENTO = "VENCIDO", "POR_VENCER", "VIGENTE", "SIN_VENCIMIENTO"
PENDIENTE_REVISION, FECHA_INVALIDA = "PENDIENTE_REVISION", "FECHA_INVALIDA"
ESTADOS_VENCIMIENTO = (VENCIDO, POR_VENCER, VIGENTE, SIN_VENCIMIENTO, PENDIENTE_REVISION, FECHA_INVALIDA)
ACTIVO, REEMPLAZADO, ANULADO = "ACTIVO", "REEMPLAZADO", "ANULADO"
INTEGRO, ARCHIVO_AUSENTE, ALTERADO, SIN_HUELLA, SIN_ARCHIVO, FUERA_DE_EMPRESA = (
    "INTEGRO", "AUSENTE", "ALTERADO", "SIN_HUELLA", "SIN_ARCHIVO", "FUERA_DE_EMPRESA")
_ESPACIO_UUID = uuid.UUID("0f4c5a52-6a0e-5c37-9d5e-3a1f5b7c2e11")
_ESTADO_OCR_AUTOMATICO = "VENCIMIENTO_OCR_AUTOMATICO"
_Reloj = Callable[[], datetime]


def _ahora_utc() -> datetime:
    return datetime.now(timezone.utc)


class ErrorExpedienteDigital(ValueError):
    pass


def empresa_del_proceso() -> str:
    """Código de almacén de la empresa activa: el identificador multiempresa va
    en minúsculas y `fichas_digitales/<EMPRESA>` sólo admite mayúsculas."""
    from atlas_core.fichas_choferes import EMPRESA_ACTUAL
    return EMPRESA_ACTUAL.upper()


def ruta_almacen_expediente(raiz: str | Path, empresa: str) -> Path:
    from atlas_core.fichas_choferes import ruta_almacen
    try:
        return ruta_almacen(raiz, empresa).with_name(NOMBRE_ALMACEN)
    except ValueError as error:
        raise ErrorExpedienteDigital(str(error)) from error


def _vacio(empresa: str) -> dict:
    return {"version": VERSION, "empresa": empresa, "revision": 0, "expedientes": [], "documentos": [],
            "tipos_documento": {}, "historial": []}


def _desde_v1(datos: dict) -> dict:
    """Almacén v1 (sin expedientes) leído como v2; se persiste al escribir."""
    empresa, expedientes = datos["empresa"], {}
    for documento in datos["documentos"]:
        clave = (documento["entidad"], documento["referencia_catalogo"])
        expediente_id = str(uuid.uuid5(_ESPACIO_UUID, f"{empresa}:{clave[0]}:{clave[1]}"))
        expedientes.setdefault(clave, {
            "expediente_id": expediente_id, "entidad": clave[0], "referencias": [clave[1]], "ficha_id": "",
            "creado_en": documento["registrado_en"], "creado_por": documento["actor"]})
        documento.update(expediente_id=expediente_id, fecha_emision="",
                         estado=REEMPLAZADO if documento.get("reemplazado_por") else ACTIVO)
    return {**_vacio(empresa), "revision": datos.get("revision", 0), "expedientes": list(expedientes.values()),
            "documentos": datos["documentos"]}


def leer_expediente(raiz: str | Path, *, empresa: str) -> dict:
    """Lectura pura: un almacén ausente es un expediente vacío (no se crea)."""
    ruta = ruta_almacen_expediente(raiz, empresa)
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return _vacio(empresa)
    except (OSError, ValueError) as error:
        raise ErrorExpedienteDigital(f"expediente ilegible: {error}") from error
    if not isinstance(datos, dict) or datos.get("version") not in (1, VERSION) or datos.get("empresa") != empresa \
            or not isinstance(datos.get("documentos"), list):
        raise ErrorExpedienteDigital("versión o empresa del expediente incompatible")
    if datos["version"] == 1:
        return _desde_v1(datos)
    if not isinstance(datos.get("expedientes"), list) or not isinstance(datos.get("historial"), list) \
            or not isinstance(datos.get("tipos_documento"), dict):
        raise ErrorExpedienteDigital("versión o empresa del expediente incompatible")
    return datos


@contextmanager
def _mutacion(raiz: str | Path, empresa: str) -> Iterator[dict]:
    """Lee, deja modificar y publica bajo bloqueo. Sin eventos nuevos no escribe;
    una excepción deja el almacén intacto."""
    ruta = ruta_almacen_expediente(raiz, empresa)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with bloqueo_sesion(ruta.parent, "expediente_documentos"):
        datos = leer_expediente(raiz, empresa=empresa)
        eventos = len(datos["historial"])
        yield datos
        if len(datos["historial"]) > eventos:
            datos["revision"] = int(datos.get("revision", 0)) + 1
            escribir_json_atomico(ruta, datos)


def _instante(reloj: _Reloj) -> str:
    return reloj().astimezone(timezone.utc).isoformat()


def _evento(datos: dict, operacion: str, actor: str, instante: str, **detalle: object) -> None:
    datos["historial"].append({"evento_id": str(uuid.uuid4()), "revision": int(datos.get("revision", 0)) + 1,
                               "operacion": operacion, "actor": actor, "en": instante, **detalle})


def _actor(actor: object) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}", str(actor or "")):
        raise ErrorExpedienteDigital("actor obligatorio")
    return str(actor)


def _motivo(motivo: object) -> str:
    texto = str(motivo or "").strip()
    if not texto or len(texto) > 500:
        raise ErrorExpedienteDigital("motivo obligatorio (hasta 500 caracteres)")
    return texto


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
    try:
        vehiculos = cargar_catalogo_vehiculos(catalogos / "vehiculos.json").vehiculos
        patente = normalizar_patente_vehiculo(referencia)
    except ValueError as error:
        raise ErrorExpedienteDigital(f"el vehículo no existe (o el catálogo es ilegible): {error}") from error
    coincidentes = [v for v in vehiculos if v.vehiculo_id == referencia or v.patente_canonica == patente
                    or patente in v.aliases]
    if len(coincidentes) != 1:
        raise ErrorExpedienteDigital("el vehículo no existe (o no es único) en el catálogo")
    return coincidentes[0].vehiculo_id


def _carpeta(raiz: str | Path, carpeta_catalogos: str | Path | None) -> Path:
    return Path(carpeta_catalogos) if carpeta_catalogos else Path(raiz) / "catalogos_privados"


def _leer_fichas(raiz: str | Path, empresa: str) -> dict | None:
    from atlas_core.fichas_choferes import leer_almacen
    try:
        return leer_almacen(raiz, empresa=empresa)
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise ErrorExpedienteDigital(f"fichas ilegibles: {error}") from error


def _identidad(raiz: str | Path, empresa: str, entidad: str, referencia: object,
               carpeta_catalogos: str | Path | None) -> tuple[str, list[str], str]:
    """(clave vigente, claves equivalentes, ficha_id) de una identidad de catálogo."""
    catalogos, texto = _carpeta(raiz, carpeta_catalogos), str(referencia or "").strip()
    if entidad == VEHICULO:
        clave = _referencia_vehiculo(catalogos, texto)
        return clave, [clave], ""
    if entidad != CHOFER:
        raise ErrorExpedienteDigital(f"entidad {entidad!r} no admitida")
    from atlas_core.fichas_choferes import fichas_por_referencia
    clave = _referencia_chofer(catalogos, texto)
    ficha = fichas_por_referencia(_leer_fichas(raiz, empresa)).get(clave)
    return (clave, list(ficha["referencias_catalogo"]), ficha["ficha_id"]) if ficha else (clave, [clave], "")


def _buscar_expediente(datos: dict, entidad: str, equivalentes: list[str]) -> dict | None:
    hallados = [e for e in datos["expedientes"] if e["entidad"] == entidad and set(e["referencias"]) & set(equivalentes)]
    if len(hallados) > 1:
        raise ErrorExpedienteDigital("la identidad corresponde a más de un expediente; revisar vínculos")
    return hallados[0] if hallados else None


def _asegurar_expediente(datos: dict, entidad: str, clave: str, equivalentes: list[str], ficha_id: str,
                         actor: str, instante: str) -> tuple[dict, bool]:
    expediente = _buscar_expediente(datos, entidad, equivalentes)
    if expediente is None:
        expediente = {"expediente_id": str(uuid.uuid4()), "entidad": entidad, "referencias": [clave],
                      "ficha_id": ficha_id, "creado_en": instante, "creado_por": actor}
        datos["expedientes"].append(expediente)
        _evento(datos, "EXPEDIENTE_CREADO", actor, instante, expediente_id=expediente["expediente_id"],
                referencia_catalogo=clave)
        return expediente, True
    if clave not in expediente["referencias"]:
        expediente["referencias"].append(clave)
        _evento(datos, "EXPEDIENTE_REFERENCIA_VINCULADA", actor, instante, expediente_id=expediente["expediente_id"],
                referencia_catalogo=clave)
    return expediente, False


def crear_expediente(raiz: str | Path, *, empresa: str, entidad: str, referencia: str, actor: str,
                     carpeta_catalogos: str | Path | None = None, reloj: _Reloj = _ahora_utc) -> dict:
    """Crea el expediente de una identidad de catálogo; si existe, lo devuelve."""
    entidad, actor = str(entidad).upper(), _actor(actor)
    ruta_almacen_expediente(raiz, empresa)
    clave, equivalentes, ficha_id = _identidad(raiz, empresa, entidad, referencia, carpeta_catalogos)
    with _mutacion(raiz, empresa) as datos:
        expediente, creado = _asegurar_expediente(datos, entidad, clave, equivalentes, ficha_id, actor, _instante(reloj))
        return {**expediente, "creado": creado}


# ------------------------------------------------------------------ tipos configurables


def tipos_documento(datos: dict) -> dict:
    """Catálogo de tipos de la empresa: base + configurados."""
    base = {t: {"tipo": t, "requiere_vencimiento": True, "activo": True, "configurable": False, **c}
            for t, c in TIPOS_BASE.items()}
    return {**base, **{t: {"tipo": t, "configurable": True, **c} for t, c in datos["tipos_documento"].items()}}


def configurar_tipo_documento(
    raiz: str | Path, *, empresa: str, entidad: str, tipo: str, nombre: str, actor: str,
    requiere_vencimiento: bool = True, obligatorio: bool = False, activo: bool = True, reloj: _Reloj = _ahora_utc,
) -> dict:
    """Crea o ajusta un tipo propio de la empresa. Los tipos base no se
    redefinen y la entidad de un tipo no cambia; desactivar conserva lo
    registrado y sólo impide documentos nuevos."""
    entidad, tipo, actor = str(entidad).upper(), str(tipo).strip().upper(), _actor(actor)
    nombre = str(nombre or "").strip()
    if entidad not in (CHOFER, VEHICULO):
        raise ErrorExpedienteDigital(f"entidad {entidad!r} no admitida")
    if not re.fullmatch(r"[A-Z][A-Z0-9_]{1,47}", tipo) or tipo in TIPOS_BASE:
        raise ErrorExpedienteDigital(f"tipo {tipo!r} no configurable")
    if not nombre or len(nombre) > 80:
        raise ErrorExpedienteDigital("nombre de tipo obligatorio (hasta 80 caracteres)")
    nuevo = {"entidad": entidad, "nombre": nombre, "requiere_vencimiento": bool(requiere_vencimiento),
             "obligatorio": bool(obligatorio), "activo": bool(activo)}
    with _mutacion(raiz, empresa) as datos:
        anterior = datos["tipos_documento"].get(tipo)
        if anterior and anterior["entidad"] != entidad:
            raise ErrorExpedienteDigital("la entidad de un tipo configurado no cambia")
        if anterior != nuevo:
            datos["tipos_documento"][tipo] = nuevo
            _evento(datos, "TIPO_CONFIGURADO", actor, _instante(reloj), tipo=tipo, antes=anterior, despues=nuevo)
    return {"tipo": tipo, "configurable": True, **nuevo}


# ------------------------------------------------------------------ validación de documentos


def _fecha(valor: object, campo: str = "vencimiento") -> str:
    texto = str(valor or "").strip()
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", texto):
            return date.fromisoformat(texto).isoformat()
    except ValueError:
        pass
    raise ErrorExpedienteDigital(f"la fecha de {campo} debe ser AAAA-MM-DD")


def _fechas(emision: object, vencimiento: object, requiere_vencimiento: bool, hoy: date) -> tuple[str, str]:
    fecha_emision = _fecha(emision, "emisión") if str(emision or "").strip() else ""
    fecha_vencimiento = _fecha(vencimiento) if requiere_vencimiento or str(vencimiento or "").strip() else ""
    if fecha_emision and fecha_emision > hoy.isoformat():
        raise ErrorExpedienteDigital("la fecha de emisión no puede ser futura")
    if fecha_emision and fecha_vencimiento and fecha_emision > fecha_vencimiento:
        raise ErrorExpedienteDigital("la fecha de emisión es posterior al vencimiento")
    return fecha_emision, fecha_vencimiento


def _archivo(valor: object) -> str:
    """Referencia relativa dentro del almacén de la empresa (`archivos/...`)."""
    texto = str(valor or "").strip().replace("\\", "/")
    if not texto:
        return ""
    partes = PureWindowsPath(texto)
    if partes.is_absolute() or partes.drive or ".." in partes.parts or partes.parts[0] != "archivos" \
            or len(partes.parts) < 2:
        raise ErrorExpedienteDigital("la referencia al archivo debe estar dentro de archivos/ de la empresa")
    return texto


def _guardar_original(carpeta_empresa: Path, expediente_id: str, documento_id: str, extension: str,
                      contenido: bytes) -> tuple[str, Path]:
    """Creación exclusiva con nombre único: un original nunca se sobrescribe."""
    relativo = Path("archivos") / "expediente" / expediente_id / (documento_id + extension)
    destino = carpeta_empresa / relativo
    destino.parent.mkdir(parents=True, exist_ok=True)
    if not destino.parent.resolve().is_relative_to(carpeta_empresa.resolve()):
        raise ErrorExpedienteDigital("la carpeta de originales apunta fuera de la empresa")
    temporal = destino.with_name(".tmp-" + uuid.uuid4().hex)  # corto: rutas largas en Windows
    try:
        with temporal.open("xb") as salida:
            salida.write(contenido)
        os.rename(temporal, destino)  # en Windows falla si el destino existe
    except OSError:
        temporal.unlink(missing_ok=True)
        raise
    return relativo.as_posix(), destino


def _buscar_documento(datos: dict, documento_id: object) -> dict:
    for documento in datos["documentos"]:
        if documento["documento_id"] == documento_id:
            return documento
    raise ErrorExpedienteDigital("el documento no existe en esta empresa")


def _coberturas_extraidas(extraccion: dict) -> list[str]:
    campo = (extraccion.get("campos") or {}).get("coberturas") or {}
    valores = campo.get("valor")
    if campo.get("estado") != "EXTRAIDO" or campo.get("motivo") or not campo.get("evidencia") \
            or not isinstance(valores, list) or not valores or any(not isinstance(v, str) or v not in TIPOS_POLIZA for v in valores):
        return []
    return sorted(set(valores))


def _revision_vigente(documento: dict) -> dict:
    """Revisión humana hecha sobre este mismo original (nunca se hereda a otro archivo)."""
    revision = documento.get("revision_humana") or {}
    return revision if revision.get("sha256") and revision.get("sha256") == documento.get("sha256") else {}


def _coberturas_documento(documento: dict) -> list[str]:
    """Coberturas acreditadas: las leídas con evidencia, también tras la revisión humana
    (que sólo puede confirmar las leídas, nunca agregar)."""
    revision = _revision_vigente(documento)
    if revision:
        return list(revision.get("coberturas") or [])
    return _coberturas_extraidas(documento.get("extraccion_automatica") or {})


def _anteriores_operativos(datos: dict, actual: dict, hoy: date) -> list[dict]:
    """Documentos operativos del mismo vehículo frente a los que decide `renovacion_documental`."""
    return [{"documento_id": d["documento_id"], "tipo": d["tipo"], "vencimiento": d["fecha_vencimiento"],
             "coberturas": _coberturas_documento(d), "origenes": [d["documento_id"]]}
            for d in datos["documentos"]
            if d is not actual and d["expediente_id"] == actual["expediente_id"] and d["estado"] == ACTIVO
            and (not d.get("pendiente_revision") or d.get("transicion_programada"))
            and _dias_para_vencer(d.get("fecha_vencimiento") or "", hoy) is not None]


# ------------------------------------------------------------------ escritura de documentos


def registrar_documento(
    raiz: str | Path, *, empresa: str, entidad: str, referencia: str, tipo: str, actor: str,
    fecha_vencimiento: str = "", fecha_emision: str = "", archivo: str = "", sha256: str = "",
    contenido: bytes | None = None, mime_type: str = "",
    carpeta_catalogos: str | Path | None = None, reloj: _Reloj = _ahora_utc, pendiente_ocr: bool = False,
) -> dict:
    """Agrega un documento activo al expediente (creándolo si hace falta); el
    activo anterior del mismo tipo queda REEMPLAZADO. `contenido` custodia el
    original bajo la empresa; `archivo` referencia uno que ya está en ella."""
    entidad, tipo, actor = str(entidad).upper(), str(tipo).upper(), _actor(actor)
    if sha256 and not re.fullmatch(r"[0-9a-f]{64}", sha256):
        raise ErrorExpedienteDigital("sha256 inválido")
    if contenido is not None and archivo:
        raise ErrorExpedienteDigital("indique contenido o referencia al archivo, no ambos")
    ruta = ruta_almacen_expediente(raiz, empresa)
    escrito: Path | None = None
    try:
        with _mutacion(raiz, empresa) as datos:
            definicion = tipos_documento(datos).get(tipo)
            if not definicion or definicion["entidad"] != entidad or not definicion["activo"]:
                raise ErrorExpedienteDigital(f"tipo {tipo!r} no admitido para {entidad!r}")
            clave, equivalentes, ficha_id = _identidad(raiz, empresa, entidad, referencia, carpeta_catalogos)
            emision, vencimiento = _fechas(fecha_emision, fecha_vencimiento, definicion["requiere_vencimiento"] and not pendiente_ocr,
                                           reloj().astimezone(timezone.utc).date())
            referencia_archivo = _archivo(archivo)
            original = None
            if contenido is not None:
                from atlas_core.fichas_choferes import _original_valido
                try:
                    original = _original_valido(contenido, mime_type, sha256 or hashlib.sha256(contenido).hexdigest())
                except ValueError as error:
                    raise ErrorExpedienteDigital(str(error)) from error
            instante = _instante(reloj)
            expediente, _ = _asegurar_expediente(datos, entidad, clave, equivalentes, ficha_id, actor, instante)
            documento_id = str(uuid.uuid4())
            if original:
                referencia_archivo, escrito = _guardar_original(ruta.parent, expediente["expediente_id"], documento_id,
                                                                original["extension"], original["contenido"])
                sha256 = original["sha256"]
            documento = {
                "documento_id": documento_id, "expediente_id": expediente["expediente_id"], "entidad": entidad,
                "referencia_catalogo": clave, "tipo": tipo, "fecha_emision": emision, "fecha_vencimiento": vencimiento,
                "estado": ACTIVO, "archivo": referencia_archivo, "sha256": sha256, "registrado_en": instante,
                "actor": actor, "reemplazado_por": "",
            }
            if pendiente_ocr:
                documento["pendiente_revision"] = True
                documento["confirmado_por_humano"] = False
            reemplazados = []
            for previo in datos["documentos"]:
                if previo["expediente_id"] == expediente["expediente_id"] and previo["tipo"] == tipo \
                        and previo["estado"] == ACTIVO and not pendiente_ocr:
                    previo.update(estado=REEMPLAZADO, reemplazado_por=documento_id)
                    reemplazados.append(previo["documento_id"])
            datos["documentos"].append(documento)
            _evento(datos, "DOCUMENTO_REGISTRADO", actor, instante, expediente_id=expediente["expediente_id"],
                    documento_id=documento_id, tipo=tipo, reemplaza=reemplazados, sha256=sha256)
    except Exception:
        if escrito is not None:  # el almacén no llegó a referenciarlo
            escrito.unlink(missing_ok=True)
        raise
    return documento


def registrar_documento_vehiculo_desktop(
    raiz: str | Path, *, empresa: str, referencia: str, tipo: str, contenido: bytes, mime_type: str,
    fabrica_ocr, fecha_emision_informada: str = "", fecha_vencimiento_informada: str = "",
    reloj: _Reloj = _ahora_utc,
) -> dict:
    """Custodia primero, lee el mismo original y publica sólo una asociación inequívoca."""
    from atlas_core.catalogo_vehiculos import cargar_catalogo_vehiculos
    from atlas_core.extraccion_vencimientos_vehiculos import extraer_vencimiento
    from atlas_core.fichas_vehiculos import TIPOS_VEHICULO
    from atlas_core.identificacion_patentes import identificar_patente
    from atlas_core.lectura_documento_vehiculo import leer_texto_documento, extraer_campos_adicionales, identificar_tipo_documental, TIPO_PENDIENTE

    if tipo not in TIPOS_VEHICULO:
        raise ErrorExpedienteDigital("tipo vehicular sin procesamiento OCR")
    documento = registrar_documento(raiz, empresa=empresa, entidad=VEHICULO, referencia=referencia, tipo=tipo,
                                    actor="DESKTOP", contenido=contenido, mime_type=mime_type,
                                    pendiente_ocr=True, reloj=reloj)
    ruta = ruta_almacen_expediente(raiz, empresa).parent / documento["archivo"]
    proveedor = None
    lectura = {"estado": "PENDIENTE_REVISION", "motivo": "ERROR_OCR", "campos": {
        nombre: {"valor": None, "estado": PENDIENTE_REVISION, "motivo": "ERROR_OCR", "evidencia": []}
        for nombre in ("tipo_documental", "patente", "emision", "vencimiento", "aseguradora", "numero_poliza", "coberturas")}}
    try:
        if hashlib.sha256(ruta.read_bytes()).hexdigest() != documento["sha256"]:
            raise ValueError("Original alterado")
        proveedor = fabrica_ocr()
        lineas = leer_texto_documento(ruta, lambda: proveedor,
                                     directorio_temporal=ruta_almacen_expediente(raiz, empresa).parent)
        if lineas is None:
            lectura["motivo"] = "PDF_ILEGIBLE"
            for campo in lectura["campos"].values():
                campo["motivo"] = "PDF_ILEGIBLE"
        else:
            catalogo = cargar_catalogo_vehiculos(Path(raiz) / "catalogos_privados" / "vehiculos.json")
            patente = identificar_patente(lineas, catalogo)
            tipo_ocr = identificar_tipo_documental(lineas)
            vencimiento = (extraer_vencimiento(tipo_ocr["valor"], lineas) if tipo_ocr["valor"] else
                           {"valor": None, "estado": PENDIENTE_REVISION, "motivo": "TIPO_PENDIENTE", "evidencia": []})
            campos = {"tipo_documental": tipo_ocr, "vencimiento": vencimiento, **extraer_campos_adicionales(lineas)}
            campos["patente"] = {"valor": patente["patente"], "estado": "EXTRAIDO" if patente["patente"] else PENDIENTE_REVISION,
                                 "motivo": patente["motivo"], "evidencia": patente["evidencia"]}
            lectura = {"estado": "COMPLETA", "motivo": "", "campos": campos}
    except Exception:  # conserva el original y deja constancia para un reintento posterior
        pass
    finally:
        cerrar = getattr(proveedor, "cerrar", None)
        if callable(cerrar):
            try:
                cerrar()
            except Exception:
                pass

    with _mutacion(raiz, empresa) as datos:
        actual = _buscar_documento(datos, documento["documento_id"])
        if actual["estado"] != ACTIVO or actual.get("sha256") != documento["sha256"]:
            raise ErrorExpedienteDigital("El documento cambió durante la lectura")
        if not ruta.resolve().is_relative_to(ruta_almacen_expediente(raiz, empresa).parent.resolve()) or \
                hashlib.sha256(ruta.read_bytes()).hexdigest() != documento["sha256"]:
            raise ErrorExpedienteDigital("El original cambió durante la lectura")
        campos = lectura["campos"]
        tipo_detectado = (campos.get("tipo_documental") or {}).get("valor")
        actual["tipo_informado"] = tipo
        actual["tipo"] = tipo_detectado or TIPO_PENDIENTE
        p = (campos.get("patente") or {}).get("valor")
        if p and _referencia_vehiculo(_carpeta(raiz, None), p) != actual["referencia_catalogo"]:
            campos["patente"].update(valor=None, observado=p, estado=PENDIENTE_REVISION, motivo="PATENTE_DISTINTA")
            p = None
        vencimiento = (campos.get("vencimiento") or {}).get("valor") or ""
        emision = (campos.get("emision") or {}).get("valor") or ""
        try:
            if emision:
                _fechas(emision, vencimiento, False, reloj().astimezone(timezone.utc).date())
        except ErrorExpedienteDigital:
            campos["emision"].update(valor=None, estado=PENDIENTE_REVISION, motivo="FECHA_INCONSISTENTE")
            emision = ""
        actual["extraccion_automatica"] = {**lectura, "procedencia": "AUTOMATICA_OCR",
                                          "sha256": documento["sha256"], "fecha": _instante(reloj)}
        actual["datos_informados"] = {"fecha_emision": fecha_emision_informada,
                                      "fecha_vencimiento": fecha_vencimiento_informada}
        actual["fecha_emision"] = emision
        actual["fecha_vencimiento"] = vencimiento
        hoy = reloj().astimezone(timezone.utc).date()
        _aplicar_transiciones(datos, hoy, reloj)  # las programadas que ya comenzaron se materializan primero
        coberturas = _coberturas_extraidas(lectura) if tipo_detectado in TIPOS_POLIZA else []
        decision = None
        if tipo_detectado and p and vencimiento and (tipo_detectado not in TIPOS_POLIZA or coberturas):
            from atlas_core.renovacion_documental import decidir_renovacion, inicio_acreditado
            anteriores = _anteriores_operativos(datos, actual, hoy)
            # Misma regla que la activación Mobile; Desktop no ofrece vínculo explícito.
            decision = decidir_renovacion({"tipo": tipo_detectado, "tipo_informado": tipo, "vencimiento": vencimiento,
                                           "inicio": inicio_acreditado(campos.get("vencimiento")),
                                           "estado_inicio": (campos.get("vencimiento") or {}).get("inicio_vigencia"),
                                           "coberturas": coberturas, "reemplaza": ""}, anteriores, hoy)
        reemplazados = []
        if decision and decision["accion"] in ("ACTIVAR", "REEMPLAZAR"):
            actual["pendiente_revision"] = False
            for previo in datos["documentos"]:
                if previo["documento_id"] in decision["documentos"]:
                    previo.update(estado=REEMPLAZADO, reemplazado_por=actual["documento_id"])
                    reemplazados.append(previo["documento_id"])
        elif decision and decision["accion"] == "PROGRAMAR":
            actual["transicion_programada"] = {"fecha": decision["fecha"], "reemplaza": decision["documentos"],
                                               "motivo": decision["motivo"], "registrado": _instante(reloj)}
        elif decision:  # PENDIENTE: se conservan ambos; nunca se activa solo
            actual["posible_reemplazo"] = {"documentos": decision["documentos"], "motivo": decision["motivo"],
                                           "registrado": _instante(reloj)}
        _evento(datos, "DOCUMENTO_EXTRACCION_OCR", "MOTOR_OCR", _instante(reloj),
                expediente_id=actual["expediente_id"], documento_id=actual["documento_id"],
                reemplaza=reemplazados, pendiente_revision=actual["pendiente_revision"],
                renovacion=decision["accion"] if decision else "", motivo=decision["motivo"] if decision else "",
                anteriores=decision["documentos"] if decision else [])
        return dict(actual)


def _aplicar_transiciones(datos: dict, hoy: date, reloj: _Reloj | None = None) -> None:
    """Materializa los reemplazos programados cuya vigencia ya comenzó. Con `reloj` deja
    constancia en el historial (escritura); sin él sólo ajusta una copia para consultar."""
    activos = {d["documento_id"]: d for d in datos["documentos"] if d["estado"] == ACTIVO}
    for nuevo in list(activos.values()):
        programada = nuevo.get("transicion_programada") or {}
        fecha = _fecha_iso(programada.get("fecha"))
        if not fecha or fecha > hoy or not nuevo.get("pendiente_revision") or nuevo.get("posible_reemplazo"):
            continue
        retirados = []
        for documento_id in programada.get("reemplaza") or []:
            previo = activos.get(documento_id)
            if previo is not None and previo["estado"] == ACTIVO:
                previo.update(estado=REEMPLAZADO, reemplazado_por=nuevo["documento_id"])
                retirados.append(documento_id)
        nuevo["pendiente_revision"] = False
        nuevo["transicion_aplicada"] = {**programada, "aplicada": hoy.isoformat()}
        nuevo.pop("transicion_programada")
        if reloj is not None:
            _evento(datos, "DOCUMENTO_REEMPLAZO_PROGRAMADO_APLICADO", "MOTOR", _instante(reloj),
                    expediente_id=nuevo["expediente_id"], documento_id=nuevo["documento_id"], reemplaza=retirados)


def _fecha_iso(valor) -> date | None:
    try:
        return date.fromisoformat(str(valor or ""))
    except ValueError:
        return None


def _leer_a_fecha(raiz: str | Path, empresa: str, hoy: date) -> dict:
    """Expediente tal como rige `hoy` (con reemplazos programados ya cumplidos). Sólo lee."""
    datos = copy.deepcopy(leer_expediente(raiz, empresa=empresa))
    _aplicar_transiciones(datos, hoy)
    return datos


def _documento_activo(datos: dict, documento_id: object) -> dict:
    documento = _buscar_documento(datos, documento_id)
    if documento["estado"] != ACTIVO:
        raise ErrorExpedienteDigital(f"el documento está {documento['estado']}; sólo se modifica uno activo")
    return documento


def actualizar_documento(
    raiz: str | Path, *, empresa: str, documento_id: str, actor: str, motivo: str,
    fecha_emision: str | None = None, fecha_vencimiento: str | None = None, reloj: _Reloj = _ahora_utc,
) -> dict:
    """Corrige las fechas de un documento activo. `None` conserva el valor. El
    archivo y su huella no cambian: otro original es otro documento."""
    actor, motivo = _actor(actor), _motivo(motivo)
    with _mutacion(raiz, empresa) as datos:
        documento = _documento_activo(datos, documento_id)
        emision, vencimiento = _fechas(
            documento["fecha_emision"] if fecha_emision is None else fecha_emision,
            documento["fecha_vencimiento"] if fecha_vencimiento is None else fecha_vencimiento,
            tipos_documento(datos).get(documento["tipo"], {}).get("requiere_vencimiento", True),
            reloj().astimezone(timezone.utc).date())
        cambios = {campo: {"antes": documento[campo], "despues": valor}
                   for campo, valor in (("fecha_emision", emision), ("fecha_vencimiento", vencimiento))
                   if documento[campo] != valor}
        if cambios:
            documento.update({campo: c["despues"] for campo, c in cambios.items()})
            _evento(datos, "DOCUMENTO_ACTUALIZADO", actor, _instante(reloj), expediente_id=documento["expediente_id"],
                    documento_id=documento["documento_id"], cambios=cambios, motivo=motivo)
        return dict(documento)


def anular_documento(raiz: str | Path, *, empresa: str, documento_id: str, actor: str, motivo: str,
                     reloj: _Reloj = _ahora_utc) -> dict:
    """Deja el documento fuera de la vigencia sin borrar registro ni original.
    No reactiva el reemplazado antes: su ausencia queda a la vista."""
    actor, motivo = _actor(actor), _motivo(motivo)
    with _mutacion(raiz, empresa) as datos:
        documento = _documento_activo(datos, documento_id)
        documento["estado"] = ANULADO
        _evento(datos, "DOCUMENTO_ANULADO", actor, _instante(reloj), expediente_id=documento["expediente_id"],
                documento_id=documento["documento_id"], cambios={"estado": {"antes": ACTIVO, "despues": ANULADO}},
                motivo=motivo)
        return dict(documento)


# ------------------------------------------------------------------ revisión humana de pendientes vehiculares
#
# Una persona revisa en Desktop un documento vehicular del expediente que el OCR
# dejó pendiente: completa lo que no se pudo leer y lo confirma o lo rechaza.
# Nunca contradice lo leído con evidencia del mismo original (tipo, patente,
# fechas, inicio de vigencia, coberturas): si la lectura es errónea, se rechaza y
# se adjunta un original legible. La consecuencia la decide SIEMPRE
# `renovacion_documental.decidir_renovacion` con los mismos anteriores que el
# alta; sólo se confirma si activa, reemplaza o programa. Ambigüedades de la regla
# (vencimiento no posterior, coberturas reducidas, etc.) siguen pendientes.

CONFIRMAR, RECHAZAR, BLOQUEADO = "CONFIRMAR", "RECHAZAR", "BLOQUEADO"
_CAMPOS_REVISION = ("tipo", "patente", "fecha_emision", "fecha_vencimiento", "inicio_vigencia")
_CONFIRMABLES = ("ACTIVAR", "REEMPLAZAR", "PROGRAMAR")
# Aceptación simple (contrato 2): emisión y vencimiento los puede corregir la persona aunque el OCR los
# haya leído (queda la procedencia de cada fecha); tipo, patente e inicio leídos siguen sin poder
# contradecirse. Completar a mano tipo, patente, inicio o el documento reemplazado exige, sin revisor
# declarado, la confirmación explícita de que esos datos aparecen en el original.
CONTRATO_ACEPTACION = 2
_CAMPOS_FECHA_REVISION = ("fecha_emision", "fecha_vencimiento")
_CAMPOS_CONFIRMACION_ORIGINAL = ("tipo", "patente", "inicio_vigencia", "reemplaza")
PERSONA_DECLARADA, PERSONA_NO_DECLARADA = "DECLARADA", "NO_DECLARADA"


def _equipo_canal() -> dict | None:
    """Equipo que acepta: la identidad del escritor operativo de esta instalación (la misma que registra
    el lease de Cloud, por eso verificable) si ya existe. Nunca la crea; un override de entorno queda
    marcado como no verificable."""
    override = os.environ.get("ATLAS_ESCRITOR_ID", "").strip()
    if override:
        return {"id": override[:80], "fuente": "OVERRIDE_ENTORNO", "verificable": False}
    try:
        from atlas_core.escritor_operativo import ruta_identidad_escritor
        valor = ruta_identidad_escritor().read_text(encoding="utf-8").strip()
    except (OSError, ImportError, ValueError):
        return None
    if re.fullmatch(r"pc-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", valor):
        return {"id": valor, "fuente": "ESCRITOR_OPERATIVO", "verificable": True}
    return None


def _autoria(autor: object, revisor_no_declarado: bool, actor: str) -> dict:
    """Quién decide. Con nombre: el de siempre. Sin nombre (sólo canal Desktop y pedido explícitamente):
    persona no declarada, canal y equipo; nunca se inventa una identidad humana."""
    texto = " ".join(str(autor or "").split())
    if revisor_no_declarado is True:
        if texto:
            raise ErrorExpedienteDigital("indique un revisor o declare que no se informa, no ambos")
        if actor != "DESKTOP":
            raise ErrorExpedienteDigital("sólo el canal Desktop puede aceptar sin revisor declarado")
        return {"autor": None, "persona": PERSONA_NO_DECLARADA, "canal": actor, "equipo": _equipo_canal()}
    return {"autor": _autor(autor), "persona": PERSONA_DECLARADA, "canal": actor}


def _auditoria_autoria(autoria: dict) -> dict:
    """Campos de auditoría que se agregan a la decisión (el `autor` ya va aparte)."""
    salida = {"persona": autoria["persona"], "canal": autoria["canal"]}
    if autoria["persona"] == PERSONA_NO_DECLARADA:
        salida["equipo"] = autoria.get("equipo")
    return salida


def _marcar_fechas_humanas(documento: dict, fechas: dict, autoria: dict, instante: str) -> None:
    """Fechas escritas por la persona al aceptar: mismo registro que la corrección manual (`fechas_confirmadas`),
    así nunca figuran como lectura automática. Las que vienen del OCR no se marcan."""
    confirmadas = dict(documento.get("fechas_confirmadas") or {})
    for campo, f in fechas.items():
        if f["origen"] == "HUMANO":
            confirmadas[campo] = {"valor": f["valor"], "autor": autoria["autor"], "actor": autoria["canal"], "fecha": instante,
                                  "sha256": documento.get("sha256", ""), "en": "ACEPTACION", **_auditoria_autoria(autoria)}
    if confirmadas:
        documento["fechas_confirmadas"] = confirmadas


def _datos_completados(propuesta: dict | None, leido: dict) -> list[str]:
    """Datos que la persona indica y que el OCR no leyó (tipo, patente, inicio) o la elección del reemplazado."""
    propuesta = propuesta or {}
    completados = [c for c in ("tipo", "patente", "inicio_vigencia")
                   if " ".join(str(propuesta.get(c) or "").split()) and not leido.get(c)]
    if str(propuesta.get("reemplaza") or "").strip():
        completados.append("reemplaza")
    return completados


def _exigir_confirmacion_original(autoria: dict, completados: list[str], confirmo_original: bool) -> None:
    if autoria["persona"] == PERSONA_NO_DECLARADA and completados and confirmo_original is not True:
        nombres = {"tipo": "tipo", "patente": "patente", "inicio_vigencia": "inicio de vigencia", "reemplaza": "documento reemplazado"}
        raise ErrorExpedienteDigital("confirme que estos datos aparecen en el original: "
                                     + ", ".join(nombres[c] for c in completados))


def _procedencia_fechas(leido: dict, propuesta: dict | None, valores: dict) -> dict:
    """Por cada fecha: lo leído por OCR, lo aceptado y de dónde viene (OCR o la persona)."""
    propuesta = propuesta or {}
    salida = {}
    for campo in _CAMPOS_FECHA_REVISION:
        propio = " ".join(str(propuesta.get(campo) or "").split())
        ocr = leido.get(campo) or ""
        humano = bool(propio) and propio != ocr
        salida[campo] = {"ocr": ocr, "valor": valores.get(campo, ""), "origen": "HUMANO" if humano else ("OCR" if ocr else "")}
    return salida


def _autor(autor: object) -> str:
    texto = " ".join(str(autor or "").split())
    if not texto or len(texto) > 80 or re.search(r"[\x00-\x1f\x7f]", texto):
        raise ErrorExpedienteDigital("indique quién revisó el documento (hasta 80 caracteres)")
    return texto


def _revisable(documento: dict) -> bool:
    from atlas_core.fichas_vehiculos import TIPOS_VEHICULO
    return (documento["estado"] == ACTIVO and documento["entidad"] == VEHICULO
            and bool(documento.get("pendiente_revision")) and not documento.get("transicion_programada")
            and documento["tipo"] in (*TIPOS_VEHICULO, "DOCUMENTO_VEHICULO_PENDIENTE"))


def _campo_leido(campo: dict | None) -> bool:
    campo = campo or {}
    return campo.get("estado") == "EXTRAIDO" and bool(campo.get("valor")) and not campo.get("motivo")


def _lectura(documento: dict) -> dict:
    """Lo leído con evidencia del mismo original y por qué falta lo demás (códigos)."""
    from atlas_core.renovacion_documental import inicio_acreditado
    extraccion = documento.get("extraccion_automatica") or {}
    valida = bool(extraccion) and extraccion.get("sha256") == documento.get("sha256")
    campos = (extraccion.get("campos") or {}) if valida else {}
    tipo, patente, emision, vencimiento = (campos.get(c) or {} for c in ("tipo_documental", "patente", "emision", "vencimiento"))
    inicio = vencimiento.get("inicio_vigencia") or {}
    leido = {
        "tipo": tipo.get("valor") if _campo_leido(tipo) else None,
        "patente": patente.get("valor") if _campo_leido(patente) else None,
        "fecha_emision": emision.get("valor") if _campo_leido(emision) else None,
        "fecha_vencimiento": vencimiento.get("valor") if _campo_leido(vencimiento) else None,
        "inicio_vigencia": inicio_acreditado(vencimiento) or None,
        "coberturas": _coberturas_extraidas(extraccion) if valida else [],
    }
    otro_vehiculo = patente.get("motivo") == "PATENTE_DISTINTA"
    motivos = []
    if not valida or extraccion.get("estado") != "COMPLETA":
        motivos.append("LECTURA_FALLIDA")
    else:
        posible = (documento.get("posible_reemplazo") or {}).get("motivo")
        if not leido["tipo"]:
            motivos.append("TIPO_NO_IDENTIFICADO")
        elif documento.get("tipo_informado") not in (None, leido["tipo"]) and posible != "TIPO_LEIDO_CON_VIGENTE":
            motivos.append("TIPO_DISTINTO_DEL_INFORMADO")
        if otro_vehiculo:
            motivos.append("PATENTE_DE_OTRO_VEHICULO")
        elif not leido["patente"]:
            motivos.append("PATENTE_NO_LEIDA")
        if not leido["fecha_vencimiento"]:
            motivos.append("VENCIMIENTO_NO_LEIDO")
        if emision.get("motivo") == "FECHA_INCONSISTENTE":
            motivos.append("EMISION_INCONSISTENTE")
        if inicio.get("motivo") not in (None, "", "NO_ENCONTRADO"):
            motivos.append("INICIO_AMBIGUO")
        if leido["tipo"] in TIPOS_POLIZA and not leido["coberturas"]:
            motivos.append("COBERTURAS_NO_LEIDAS")
    if (documento.get("posible_reemplazo") or {}).get("motivo"):
        motivos.append(documento["posible_reemplazo"]["motivo"])
    observados = [v for v in inicio.get("observados") or [] if _fecha_iso(v)]
    return {"leido": leido, "motivos": list(dict.fromkeys(motivos)), "otro_vehiculo": otro_vehiculo,
            "estado_inicio": inicio or None, "inicios_observados": sorted(set(observados))}


def _vehiculo_de(raiz: str | Path, carpeta_catalogos, patente: str) -> str:
    try:
        return _referencia_vehiculo(_carpeta(raiz, carpeta_catalogos), patente)
    except ErrorExpedienteDigital:
        return ""


def _evaluar_revision(raiz: str | Path, datos: dict, documento: dict, propuesta: dict | None, hoy: date,
                      carpeta_catalogos=None, anteriores=None) -> dict:
    """Consecuencia de confirmar con `propuesta`: la de `decidir_renovacion`, o BLOQUEADO si
    los datos no permiten aplicarla (falta, contradice la lectura o es de otro vehículo)."""
    from atlas_core.fichas_vehiculos import TIPOS_VEHICULO
    from atlas_core.renovacion_documental import decidir_renovacion
    lectura, propuesta = _lectura(documento), propuesta or {}
    leido = lectura["leido"]

    def bloqueo(motivo: str, campo: str = "", detalle: str = "") -> dict:
        return {"accion": BLOQUEADO, "motivo": motivo, "campo": campo, "detalle": detalle, "documentos": [],
                "fecha": "", "valores": {}}

    valores = {}
    for campo in _CAMPOS_REVISION:
        propio = " ".join(str(propuesta.get(campo) or "").split())
        if campo in ("tipo", "patente"):
            propio = propio.upper()
        # Emisión y vencimiento: la persona puede corregir lo leído (queda su procedencia); lo demás leído no.
        if leido[campo] and propio and propio != leido[campo] and campo not in ("patente", *_CAMPOS_FECHA_REVISION):
            return bloqueo("CONTRADICE_LECTURA", campo)
        valores[campo] = propio or leido[campo] or ""
    if lectura["otro_vehiculo"]:
        return bloqueo("PATENTE_DE_OTRO_VEHICULO", "patente")
    if not valores["tipo"]:
        return bloqueo("TIPO_FALTANTE", "tipo")
    if valores["tipo"] not in TIPOS_VEHICULO:
        return bloqueo("TIPO_NO_ADMITIDO", "tipo")
    if not valores["patente"]:
        return bloqueo("PATENTE_FALTANTE", "patente")
    expediente = next(e for e in datos["expedientes"] if e["expediente_id"] == documento["expediente_id"])
    vehiculo = _vehiculo_de(raiz, carpeta_catalogos, valores["patente"])
    if leido["patente"] and vehiculo != _vehiculo_de(raiz, carpeta_catalogos, leido["patente"]):
        return bloqueo("CONTRADICE_LECTURA", "patente")
    if not vehiculo or vehiculo not in expediente["referencias"]:
        return bloqueo("PATENTE_NO_CORRESPONDE", "patente")
    if not valores["fecha_vencimiento"]:
        return bloqueo("VENCIMIENTO_FALTANTE", "fecha_vencimiento")
    try:
        emision, vencimiento = _fechas(valores["fecha_emision"], valores["fecha_vencimiento"], True, hoy)
        inicio = _fecha(valores["inicio_vigencia"], "inicio de vigencia") if valores["inicio_vigencia"] else ""
    except ErrorExpedienteDigital as error:
        return bloqueo("FECHAS_NO_VALIDAS", "", str(error))
    inicio_humano = bool(inicio) and not leido["inicio_vigencia"]
    if inicio_humano and lectura["inicios_observados"] and inicio not in lectura["inicios_observados"]:
        # Ante varias fechas de inicio en el original, la persona elige una de ellas; no inventa otra.
        return bloqueo("INICIO_NO_OBSERVADO", "inicio_vigencia")
    coberturas = leido["coberturas"] if valores["tipo"] in TIPOS_POLIZA else []
    if valores["tipo"] in TIPOS_POLIZA and not coberturas:
        return bloqueo("COBERTURAS_SIN_EVIDENCIA", "coberturas")
    reemplaza = str(propuesta.get("reemplaza") or "").strip()
    # El tipo confirmado por la persona resuelve la duda entre informado y leído; todo lo demás
    # (vínculo, cobertura, vencimiento posterior, vigencia futura) lo decide la regla única.
    decision = decidir_renovacion({
        "tipo": valores["tipo"], "tipo_informado": valores["tipo"], "vencimiento": vencimiento, "inicio": inicio,
        "estado_inicio": None if inicio_humano else lectura["estado_inicio"], "coberturas": coberturas,
        "reemplaza": reemplaza}, _anteriores_operativos(datos, documento, hoy) if anteriores is None else anteriores, hoy)
    valores.update(fecha_emision=emision, fecha_vencimiento=vencimiento, inicio_vigencia=inicio, coberturas=coberturas,
                   reemplaza=reemplaza)
    return {**decision, "campo": "", "detalle": "", "valores": valores}


def _clave_consecuencia(evaluacion: dict) -> str:
    """Huella de lo que se mostró en la vista previa: confirmar exige que no haya cambiado."""
    contenido = {c: evaluacion[c] for c in ("accion", "motivo", "documentos", "fecha", "valores")}
    return hashlib.sha256(json.dumps(contenido, sort_keys=True).encode()).hexdigest()[:32]


def _pendiente_de_vehiculo(raiz: str | Path, empresa: str, datos: dict, referencia: object, documento_id: object,
                           carpeta_catalogos=None) -> dict:
    _, equivalentes, _ = _identidad(raiz, empresa, VEHICULO, referencia, carpeta_catalogos)
    expediente = _buscar_expediente(datos, VEHICULO, equivalentes)
    documento = _buscar_documento(datos, documento_id)
    if expediente is None or documento["expediente_id"] != expediente["expediente_id"]:
        raise ErrorExpedienteDigital("el documento no pertenece a este vehículo")
    if not _revisable(documento):
        raise ErrorExpedienteDigital("el documento ya no está pendiente de revisión")
    return documento


def _resumen_documento(documento: dict) -> dict:
    return {"documento_id": documento["documento_id"], "tipo": documento["tipo"],
            "fecha_emision": documento.get("fecha_emision", ""), "fecha_vencimiento": documento.get("fecha_vencimiento", ""),
            "coberturas": _coberturas_documento(documento), "archivo": documento.get("archivo", ""),
            "registrado_en": documento.get("registrado_en", "")}


def _revision_desktop_contexto(raiz, empresa, datos, documento, propuesta, hoy, carpeta_catalogos=None):
    """Evalúa una revisión frente a ambos almacenes sin escribirlos."""
    from atlas_core.identificacion_patentes import _ubicaciones
    fichas = _leer_fichas(raiz, empresa)
    anteriores = _anteriores_operativos(datos, documento, hoy)
    expediente = next(e for e in datos['expedientes'] if e['expediente_id'] == documento['expediente_id'])
    fichas_anteriores = []
    for patente, d in _ubicaciones(fichas or {}):
        if not patente or d.get('reemplazado_por') or d.get('rechazo') or not d.get('vencimiento'):
            continue
        if _vehiculo_de(raiz, carpeta_catalogos, patente) not in expediente['referencias']:
            continue
        if _dias_para_vencer(d['vencimiento'], hoy) is None:
            continue
        rev = d.get('revision_humana') or {}
        cobertura = rev.get('coberturas') if rev.get('sha256') == d.get('sha256') else _coberturas_extraidas(d.get('extraccion_automatica') or {})
        anteriores.append({'documento_id': d['documento_id'], 'tipo': d['tipo'], 'vencimiento': d['vencimiento'],
                           'coberturas': cobertura or [], 'origenes': [d['documento_id'], d.get('origen_documento_id'), *d.get('origenes_adicionales', [])]})
        fichas_anteriores.append(d)
    evaluacion = _evaluar_revision(raiz, datos, documento, propuesta, hoy, carpeta_catalogos, anteriores)
    if evaluacion['accion'] in ('REEMPLAZAR', 'PROGRAMAR') and set(evaluacion['documentos']) & {d['documento_id'] for d in fichas_anteriores}:
        evaluacion.update(accion='PENDIENTE', motivo='RENOVACION_ENTRE_ALMACENES')
    catalogo = _carpeta(raiz, carpeta_catalogos) / 'vehiculos.json'
    carpeta = ruta_almacen_expediente(raiz, empresa).parent.resolve()
    ruta = (carpeta / str(documento.get('archivo') or '')).resolve()
    original = hashlib.sha256(ruta.read_bytes()).hexdigest() if ruta.is_relative_to(carpeta) and ruta.is_file() else ''
    clave = hashlib.sha256(json.dumps({'fichas': fichas, 'expedientes': datos['expedientes'],
                                     'documentos': datos['documentos'], 'evaluacion': evaluacion,
                                     'catalogo': hashlib.sha256(catalogo.read_bytes()).hexdigest(), 'original': original},
                                    sort_keys=True, ensure_ascii=True).encode()).hexdigest()[:32]
    return evaluacion, anteriores, fichas_anteriores, clave


def revisar_documento_pendiente(raiz: str | Path, *, empresa: str, referencia: str, documento_id: str,
                                propuesta: dict | None = None, reloj: _Reloj = _ahora_utc,
                                carpeta_catalogos: str | Path | None = None) -> dict:
    """Vista previa de la revisión (sólo lee): lo leído, los motivos de la duda, los
    anteriores del vehículo y la consecuencia exacta que tendría confirmar."""
    from atlas_core.identificacion_patentes import _ubicaciones
    fichas = _leer_fichas(raiz, empresa)
    if fichas and any(d.get('documento_id') == documento_id and d.get('origen') == 'MOBILE'
                      for _, d in _ubicaciones(fichas)):
        from atlas_core.revision_vehiculo_mobile import revisar
        return revisar(raiz, empresa=empresa, referencia=referencia, documento_id=documento_id,
                       propuesta=propuesta, reloj=reloj, carpeta_catalogos=carpeta_catalogos)
    from atlas_core.fichas_vehiculos import TIPOS_VEHICULO
    hoy = reloj().astimezone(timezone.utc).date()
    datos = _leer_a_fecha(raiz, empresa, hoy)
    documento = _pendiente_de_vehiculo(raiz, empresa, datos, referencia, documento_id, carpeta_catalogos)
    lectura = _lectura(documento)
    evaluacion, anteriores, fichas_anteriores, clave = _revision_desktop_contexto(raiz, empresa, datos, documento, propuesta, hoy, carpeta_catalogos)
    from atlas_core.renovacion_documental import tipos_acreditados
    # Sólo los anteriores que acreditan lo mismo que el tipo en revisión (y los que nombra la decisión).
    tipo_revisado = str((propuesta or {}).get("tipo") or "").upper() or lectura["leido"]["tipo"] or documento.get("tipo_informado") or ""
    acredita = tipos_acreditados({"tipo": tipo_revisado, "coberturas": lectura["leido"]["coberturas"]})
    operativos = {a["documento_id"] for a in anteriores
                  if acredita & tipos_acreditados(a) or a["documento_id"] in evaluacion["documentos"]}
    nombres = tipos_documento(datos)
    return {
        "empresa": empresa,
        "documento": {**_resumen_documento(documento), "tipo_informado": documento.get("tipo_informado", ""),
                      "datos_informados": documento.get("datos_informados") or {}, "sha256": documento.get("sha256", "")},
        "leido": lectura["leido"], "motivos": lectura["motivos"], "inicios_observados": lectura["inicios_observados"],
        **_vista_aceptacion(lectura),
        "tipos": [{"tipo": t, "nombre": nombres[t]["nombre"]} for t in TIPOS_VEHICULO],
        "anteriores": ([_resumen_documento(d) for d in datos["documentos"] if d["documento_id"] in operativos] +
                       [{"documento_id": d['documento_id'], "tipo": d['tipo'], "fecha_emision": "", "fecha_vencimiento": d['vencimiento'],
                         "coberturas": _coberturas_extraidas(d.get('extraccion_automatica') or {}), "archivo": d.get('archivo', ''),
                         "registrado_en": d.get('recibido_en', '')} for d in fichas_anteriores if d['documento_id'] in operativos]),
        "consecuencia": {**{c: evaluacion[c] for c in ("accion", "motivo", "campo", "detalle", "documentos", "fecha")},
                         "clave": clave},
        "puede_confirmar": evaluacion["accion"] in _CONFIRMABLES,
    }


def _vista_aceptacion(lectura: dict, *, otro_vehiculo: bool | None = None) -> dict:
    """Parte de la vista previa que usa la aceptación simple: qué se puede escribir, qué fechas precargar
    (sólo lo leído con evidencia) y qué datos completados exigen confirmar el original."""
    otro = lectura["otro_vehiculo"] if otro_vehiculo is None else otro_vehiculo
    return {
        "editables": [c for c in _CAMPOS_REVISION if c in _CAMPOS_FECHA_REVISION
                      or (not lectura["leido"][c] and not (c == "patente" and otro))],
        "contrato_aceptacion": CONTRATO_ACEPTACION,
        "precarga": {c: lectura["leido"][c] or "" for c in _CAMPOS_FECHA_REVISION},
        "confirmacion_original": [c for c in _CAMPOS_CONFIRMACION_ORIGINAL if c == "reemplaza" or not lectura["leido"][c]],
    }


def resolver_documento_pendiente(
    raiz: str | Path, *, empresa: str, referencia: str, documento_id: str, sha256: str, decision: str, autor: str = "",
    confirmacion_humana: bool, motivo: str = "", propuesta: dict | None = None, clave_consecuencia: str = "",
    actor: str = "DESKTOP", reloj: _Reloj = _ahora_utc, carpeta_catalogos: str | Path | None = None,
    revisor_no_declarado: bool = False, confirmo_original: bool = False,
) -> dict:
    """Confirma o rechaza un pendiente vehicular revisado por una persona. Confirmar
    recalcula bajo bloqueo la misma consecuencia de la vista previa y sólo la aplica si
    coincide y la regla la permite. Rechazar lo deja anulado con su original e historial.
    `revisor_no_declarado`: Desktop decide sin nombre (queda persona no declarada, canal y equipo);
    entonces completar tipo, patente, inicio o reemplazado exige `confirmo_original`."""
    from atlas_core.identificacion_patentes import _ubicaciones
    fichas = _leer_fichas(raiz, empresa)
    if fichas and any(d.get('documento_id') == documento_id and d.get('origen') == 'MOBILE'
                      for _, d in _ubicaciones(fichas)):
        from atlas_core.revision_vehiculo_mobile import resolver
        return resolver(raiz, empresa=empresa, referencia=referencia, documento_id=documento_id, sha256=sha256,
                        decision=str(decision or '').upper(), autor=autor, confirmacion_humana=confirmacion_humana,
                        motivo=motivo, propuesta=propuesta, clave_consecuencia=clave_consecuencia, actor=actor,
                        reloj=reloj, carpeta_catalogos=carpeta_catalogos, revisor_no_declarado=revisor_no_declarado,
                        confirmo_original=confirmo_original)
    actor, decision = _actor(actor), str(decision or "").upper()
    autoria = _autoria(autor, revisor_no_declarado, actor)
    autor = autoria["autor"]
    if confirmacion_humana is not True:
        raise ErrorExpedienteDigital("falta la confirmación de que una persona revisó el original")
    if decision not in (CONFIRMAR, RECHAZAR):
        raise ErrorExpedienteDigital("decisión no admitida")
    motivo = _motivo(motivo) if decision == RECHAZAR else ""
    carpeta = ruta_almacen_expediente(raiz, empresa).parent
    # Misma secuencia que la revisión Mobile; adquisición sin espera.
    # _mutacion publica el expediente antes de liberar catálogo y fichas.
    with bloqueo_sesion(Path(raiz) / 'operacion' / 'actual', 'fichas_choferes_' + empresa), \
         bloqueo_sesion(_carpeta(raiz, carpeta_catalogos), 'catalogo_vehiculos'), \
         _mutacion(raiz, empresa) as datos:
        hoy = reloj().astimezone(timezone.utc).date()
        _aplicar_transiciones(datos, hoy, reloj)
        documento = _pendiente_de_vehiculo(raiz, empresa, datos, referencia, documento_id, carpeta_catalogos)
        if not sha256 or documento.get("sha256") != sha256:
            raise ErrorExpedienteDigital("el documento cambió desde que se abrió; vuelva a revisarlo")
        instante = _instante(reloj)
        if decision == RECHAZAR:
            documento["estado"] = ANULADO
            documento["rechazo"] = {"autor": autor, "motivo": motivo, "en": instante, "actor": actor,
                                    "motivos_revisados": _lectura(documento)["motivos"], **_auditoria_autoria(autoria)}
            _evento(datos, "DOCUMENTO_RECHAZADO_EN_REVISION", actor, instante, expediente_id=documento["expediente_id"],
                    documento_id=documento["documento_id"], autor=autor, motivo=motivo,
                    cambios={"estado": {"antes": ACTIVO, "despues": ANULADO}}, **_auditoria_autoria(autoria))
            return dict(documento)
        ruta = carpeta / str(documento.get("archivo") or "")
        if not documento.get("archivo") or not ruta.resolve().is_relative_to(carpeta.resolve()) or not ruta.is_file() \
                or hashlib.sha256(ruta.read_bytes()).hexdigest() != documento["sha256"]:
            raise ErrorExpedienteDigital("el original no está íntegro; no se puede confirmar")
        lectura = _lectura(documento)
        completados = _datos_completados(propuesta, lectura["leido"])
        _exigir_confirmacion_original(autoria, completados, confirmo_original)
        evaluacion, _, _, clave = _revision_desktop_contexto(raiz, empresa, datos, documento, propuesta, hoy, carpeta_catalogos)
        if not clave_consecuencia or clave != clave_consecuencia:
            raise ErrorExpedienteDigital("la consecuencia cambió desde la vista previa; vuelva a revisarla")
        accion = evaluacion["accion"]
        if accion not in _CONFIRMABLES:
            raise ErrorExpedienteDigital("este documento no puede confirmarse: queda pendiente por seguridad")
        v = evaluacion["valores"]
        motivos = lectura["motivos"]
        fechas = _procedencia_fechas(lectura["leido"], propuesta, v)
        correccion_ocr = {c: {"antes": f["ocr"], "despues": f["valor"]} for c, f in fechas.items() if f["origen"] == "HUMANO" and f["ocr"]}
        cambios = {c: {"antes": documento.get(c, ""), "despues": v[c]}
                   for c in ("tipo", "fecha_emision", "fecha_vencimiento") if documento.get(c, "") != v[c]}
        documento.update({c: v[c] for c in ("tipo", "fecha_emision", "fecha_vencimiento")}, confirmado_por_humano=True)
        resuelto = documento.pop("posible_reemplazo", None)
        _marcar_fechas_humanas(documento, fechas, autoria, instante)
        documento["revision_humana"] = {
            "autor": autor, "en": instante, "actor": actor, "sha256": documento["sha256"], "decision": accion,
            "motivo_regla": evaluacion["motivo"], "patente": v["patente"], "inicio_vigencia": v["inicio_vigencia"],
            "coberturas": v["coberturas"], "cambios": cambios, "motivos_revisados": motivos,
            "posible_reemplazo_resuelto": resuelto, "reemplaza": evaluacion["documentos"],
            "fechas": fechas, "correccion_ocr": correccion_ocr, "datos_completados": completados,
            "confirmo_original": bool(completados) and confirmo_original is True, **_auditoria_autoria(autoria)}
        reemplazados = []
        if accion == "PROGRAMAR":
            documento["transicion_programada"] = {"fecha": evaluacion["fecha"], "reemplaza": evaluacion["documentos"],
                                                  "motivo": evaluacion["motivo"], "registrado": instante}
        else:
            documento["pendiente_revision"] = False
            for previo in datos["documentos"]:
                if previo["documento_id"] in evaluacion["documentos"] and previo["estado"] == ACTIVO:
                    previo.update(estado=REEMPLAZADO, reemplazado_por=documento["documento_id"])
                    reemplazados.append(previo["documento_id"])
        _evento(datos, "DOCUMENTO_REVISION_CONFIRMADA", actor, instante, expediente_id=documento["expediente_id"],
                documento_id=documento["documento_id"], tipo=documento["tipo"], autor=autor, cambios=cambios,
                renovacion=accion, motivo_regla=evaluacion["motivo"], reemplaza=reemplazados,
                programado_desde=evaluacion["fecha"] if accion == "PROGRAMAR" else "",
                anteriores=evaluacion["documentos"], fechas=fechas, correccion_ocr=correccion_ocr,
                datos_completados=completados, **_auditoria_autoria(autoria))
        return dict(documento)


# ------------------------------------------------------------------ vista derivada


def estado_vencimiento(fecha_vencimiento: str, *, hoy: date, dias_por_vencer: int = DIAS_POR_VENCER) -> str:
    if not fecha_vencimiento:
        return SIN_VENCIMIENTO
    dias = _dias_para_vencer(fecha_vencimiento, hoy)
    if dias is None:
        return FECHA_INVALIDA
    return VENCIDO if dias < 0 else POR_VENCER if dias <= dias_por_vencer else VIGENTE


def _dias_para_vencer(fecha_vencimiento: str, hoy: date) -> int | None:
    try:
        return (date.fromisoformat(fecha_vencimiento) - hoy).days
    except (TypeError, ValueError):
        return None


def _indice_patentes(catalogos: Path) -> dict[str, str]:
    from atlas_core.catalogo_vehiculos import cargar_catalogo_vehiculos
    try:
        vehiculos = cargar_catalogo_vehiculos(catalogos / "vehiculos.json").vehiculos
    except ValueError:
        return {}
    return {p: v.vehiculo_id for v in vehiculos for p in (v.patente_canonica, *v.aliases)}


def _ultima_correccion_fechas(doc: dict) -> dict:
    """Resumen de la última corrección manual de fechas (autor, fecha y campos), o {}."""
    correcciones = doc.get("correcciones_fechas") or []
    ultima = correcciones[-1] if correcciones and isinstance(correcciones[-1], dict) else {}
    if not ultima:
        return {}
    return {"autor": ultima.get("autor", ""), "fecha": ultima.get("fecha", ""),
            "campos": sorted(ultima.get("cambios") or {}), "cantidad": len(correcciones)}


def _vencimiento_corregido(documento: dict) -> bool:
    """El vencimiento registrado es el que confirmó una persona sobre este mismo original."""
    registro = (documento.get("fechas_confirmadas") or {}).get("fecha_vencimiento") or {}
    return bool(registro.get("valor")) and registro.get("valor") == documento.get("fecha_vencimiento") \
        and registro.get("sha256") == documento.get("sha256")


def _documento_de_ficha(doc: dict, entidad: str, referencias: list[str], fuente: str, patente_ficha: str = "") -> dict:
    vencimiento = str(doc.get("vencimiento") or "")
    vista = {
        "documento_id": doc["documento_id"], "entidad": entidad, "referencia_catalogo": referencias[-1],
        "referencias": referencias, "tipo": doc["tipo"], "fecha_emision": str(doc.get("emision") or ""),
        "fecha_vencimiento": vencimiento,
        "estado": ACTIVO, "archivo": str(doc.get("archivo", "")), "sha256": str(doc.get("sha256", "")),
        "fuente": fuente, "pendiente_revision": not vencimiento,
        "confirmado_por_humano": bool(vencimiento) and doc.get("estado_revision") != _ESTADO_OCR_AUTOMATICO,
    }
    if doc.get("fechas_confirmadas"):
        vista["fechas_confirmadas"] = doc["fechas_confirmadas"]
    if _ultima_correccion_fechas(doc):
        vista["correccion_fechas"] = _ultima_correccion_fechas(doc)
    if doc.get("tipo") in TIPOS_POLIZA or doc.get("tipo") == "DOCUMENTO_VEHICULO_PENDIENTE":
        vista.update(extraccion_automatica=doc.get("extraccion_automatica"),
                     identificacion_patente=doc.get("identificacion_patente"), asociacion=doc.get("asociacion"),
                     vencimiento_registro=doc.get("vencimiento_registro"), patente_ficha=patente_ficha,
                     tipo_informado=doc.get("tipo_informado"), revision_humana=doc.get("revision_humana"))
    for clave in ("tipo_informado", "posible_reemplazo", "transicion_programada"):
        if doc.get(clave):
            vista[clave] = doc[clave]
    return vista


def _vista_coberturas(documento: dict) -> dict:
    """Una sola entrada documental, con requisitos derivados del OCR de su original."""
    if documento.get("tipo") == "DOCUMENTO_VEHICULO_PENDIENTE" and documento.get("tipo_informado") in TIPOS_POLIZA:
        return {**documento, "tipos_cubiertos": [], "pendiente_revision": True}
    if documento.get("tipo") not in TIPOS_POLIZA:
        return documento
    extraccion = documento.get("extraccion_automatica") or {}
    campos = extraccion.get("campos") or {}
    huella = documento.get("sha256")
    if _revision_vigente(documento).get("coberturas"):
        # Confirmada por una persona sobre este original, con coberturas leídas con evidencia.
        return {**documento, "tipos_cubiertos": _coberturas_documento(documento),
                "pendiente_revision": bool(documento.get("pendiente_revision"))}
    if documento.get("fuente") == "EXPEDIENTE":
        patente = campos.get("patente") or {}
        vinculado = bool(huella and extraccion.get("sha256") == huella and patente.get("estado") == "EXTRAIDO"
                         and patente.get("valor") and patente.get("evidencia") and not patente.get("motivo"))
    else:
        ident = documento.get("identificacion_patente") or {}
        asociacion = documento.get("asociacion") or {}
        registro = documento.get("vencimiento_registro") or {}
        archivos = extraccion.get("archivos") or []
        vinculado = bool(huella and ident.get("estado") == "ASOCIADA" and ident.get("evidencia")
                         and asociacion.get("metodo") == "PATENTE_DOCUMENTAL"
                         and ident.get("patente") == asociacion.get("patente") == documento.get("patente_ficha")
                         and registro.get("procedencia") == "OCR_AUTOMATICO" and registro.get("sha256") == huella
                         and len(archivos) == 1 and archivos[0].get("sha256") == huella
                         and archivos[0].get("archivo") == documento.get("archivo"))
    vencimiento = campos.get("vencimiento") or {}
    leido = (vencimiento.get("estado") == "EXTRAIDO" and vencimiento.get("valor") == documento.get("fecha_vencimiento")
             and vencimiento.get("evidencia") and not vencimiento.get("motivo"))
    # Un vencimiento corregido por una persona sobre el mismo original no cambia las coberturas leídas.
    confiable = (vinculado and extraccion.get("procedencia") == "AUTOMATICA_OCR"
                 and (leido or _vencimiento_corregido(documento)))
    coberturas = _coberturas_extraidas(extraccion) if confiable else []
    return {**documento, "tipos_cubiertos": coberturas,
            "pendiente_revision": bool(documento.get("pendiente_revision") or not coberturas)}


def _documentos_de_fichas(raiz: str | Path, empresa: str, catalogos: Path) -> list[dict]:
    """Documentos de las fichas (sólo lectura). De cada identidad y tipo queda
    el de vencimiento válido más lejano, como en Desktop, y aparte los
    pendientes y los de fecha inválida."""
    fichas = _leer_fichas(raiz, empresa)
    if not fichas or fichas.get("version") != 2:
        return []
    documentos = [_documento_de_ficha(doc, CHOFER, ficha["referencias_catalogo"], "FICHA_CHOFER")
                  for ficha in fichas.get("choferes", []) for doc in ficha.get("documentos", [])
                  if doc.get("tipo") == "LICENCIA_CONDUCIR" and not doc.get("reemplazado_por")]
    patentes = _indice_patentes(catalogos) if fichas.get("vehiculos") else {}
    for ficha in fichas.get("vehiculos", []):
        patente = str(ficha.get("patente", ""))
        documentos += [_documento_de_ficha(doc, VEHICULO, [patentes.get(patente, patente)], "FICHA_VEHICULO", patente)
                       for doc in ficha.get("documentos", []) if doc.get("tipo") and not doc.get("reemplazado_por")
                       and not doc.get("rechazo")]
    documentos = [_vista_coberturas(d) for d in documentos]
    resultado, mejores = [], {}
    for doc in documentos:
        if doc["tipo"] in TIPOS_POLIZA:
            resultado.append(doc)
            continue
        if doc["pendiente_revision"] or _dias_para_vencer(doc["fecha_vencimiento"], date.min) is None:
            resultado.append(doc)
            continue
        clave = (doc["entidad"], doc["referencias"][0], doc["tipo"])
        if clave not in mejores or doc["fecha_vencimiento"] > mejores[clave]["fecha_vencimiento"]:
            mejores[clave] = doc
    return resultado + list(mejores.values())


def estado_expediente(raiz: str | Path, *, empresa: str, hoy: date | None = None,
                      dias_por_vencer: int = DIAS_POR_VENCER, carpeta_catalogos: str | Path | None = None) -> list[dict]:
    """Documentos activos con su estado de vencimiento derivado a la fecha
    `hoy`. Incluye los de las fichas que el expediente no registró. Nunca
    escribe. Una ficha ilegible es un error, no una ausencia de documentos."""
    hoy = hoy or date.today()
    datos = _leer_a_fecha(raiz, empresa, hoy)
    referencias = {e["expediente_id"]: e["referencias"] for e in datos["expedientes"]}
    propios = [_vista_coberturas({**d, "fuente": "EXPEDIENTE", "pendiente_revision": d.get("pendiente_revision", False),
                "confirmado_por_humano": d.get("confirmado_por_humano", True),
                "referencias": referencias[d["expediente_id"]],
                **({"correccion_fechas": _ultima_correccion_fechas(d)} if _ultima_correccion_fechas(d) else {})})
               for d in datos["documentos"] if d["estado"] == ACTIVO]
    claves = lambda d: [(d["entidad"], r, d["tipo"]) for r in d["referencias"]]  # noqa: E731
    registrados = {k: d["fecha_vencimiento"] for d in propios
                   if not d["pendiente_revision"] and d["tipo"] not in TIPOS_POLIZA for k in claves(d)}
    fichas = _documentos_de_fichas(raiz, empresa, _carpeta(raiz, carpeta_catalogos))
    # Una renovación llegada después por la ficha no queda oculta tras el registro antiguo.
    mas_recientes = [d for d in fichas if d["tipo"] not in TIPOS_POLIZA and not d["pendiente_revision"]
                     and _dias_para_vencer(d["fecha_vencimiento"], date.min) is not None
                     and any(k in registrados and d["fecha_vencimiento"] > registrados[k] for k in claves(d))]
    superados = {k for d in mas_recientes for k in claves(d)}
    propios = [d for d in propios if d["tipo"] in TIPOS_POLIZA or d["pendiente_revision"] or not superados & set(claves(d))]
    externos = [d for d in fichas if d["tipo"] in TIPOS_POLIZA or d in mas_recientes or not any(k in registrados for k in claves(d))]
    vista = []
    for d in propios + externos:
        estado = PENDIENTE_REVISION if d["pendiente_revision"] else estado_vencimiento(
            d["fecha_vencimiento"], hoy=hoy, dias_por_vencer=dias_por_vencer)
        vista.append({**d, "estado_vencimiento": estado, "dias_para_vencer": _dias_para_vencer(d["fecha_vencimiento"], hoy)})
    return sorted(vista, key=lambda d: (d["dias_para_vencer"] is None, d["dias_para_vencer"] or 0))


def _ausentes(tipos: dict, entidad: str, documentos: list[dict], *, requeridos: set[str] | None = None) -> list[dict]:
    presentes, pendientes = set(), set()
    for d in documentos:
        if d["tipo"] in TIPOS_POLIZA or (d["tipo"] == "DOCUMENTO_VEHICULO_PENDIENTE" and d.get("tipo_informado") in TIPOS_POLIZA):
            if d["estado_vencimiento"] == PENDIENTE_REVISION:
                pendientes.update(TIPOS_POLIZA)
            elif d["estado_vencimiento"] not in (VENCIDO, FECHA_INVALIDA, SIN_VENCIMIENTO):
                presentes.update(d.get("tipos_cubiertos", []))
        elif d["tipo"] == "DOCUMENTO_VEHICULO_PENDIENTE":
            # Sin evidencia de tipo no acredita nada: el requisito informado queda recibido y pendiente.
            pendientes.add(d.get("tipo_informado") or d["tipo"])
        elif d["estado_vencimiento"] == PENDIENTE_REVISION:
            pendientes.add(d["tipo"])
        else:
            presentes.add(d["tipo"])
    return [{"tipo": t, "nombre": c["nombre"], "pendiente_revision": t in pendientes} for t, c in tipos.items()
            if c["entidad"] == entidad and c["activo"] and (c["obligatorio"] if requeridos is None else t in requeridos) and t not in presentes]


# Requisitos de operación MBT; no son afirmaciones sobre obligaciones legales.
_REQUISITOS_VEHICULO_MBT = frozenset({"SOAP", "POLIZA_RESPONSABILIDAD_CIVIL", "SEGURO_CARGA",
    "REVISION_TECNICA", "PERMISO_CIRCULACION", "CERTIFICADO_EMISION_GASES"})
_REQUISITOS_CHOFER_MBT = ("LICENCIA_CONDUCIR", "SOAP", "POLIZA_RESPONSABILIDAD_CIVIL", "SEGURO_CARGA",
    "REVISION_TECNICA", "PERMISO_CIRCULACION", "CERTIFICADO_EMISION_GASES")


def _tipo_vehiculo_requisitos(catalogos: Path, clave: str) -> str | None:
    from atlas_core.catalogo_vehiculos import cargar_catalogo_vehiculos
    catalogo = cargar_catalogo_vehiculos(catalogos / "vehiculos.json")
    v = next((v for v in catalogo.vehiculos if v.vehiculo_id == clave), None)
    if not v or v.estado_calidad != "CONFIRMADO" or v.estado_vigencia != "ACTIVO":
        return None
    if any(e.resultado == "CONTRADICE" and e.campos_observados.get("tipo")
           and e.campos_observados["tipo"] != v.tipo for e in v.evidencias):
        return None
    return v.tipo if v.tipo in ("TRACTO", "CARRO", "CAMION_RIGIDO") else None


# Lo que NO se exige a cada tipo (única fuente para la vista del vehículo, la del chofer y los ausentes).
# Coberturas: la responsabilidad civil corresponde al tracto y el seguro de carga a la rampla; el camión
# rígido lleva ambas. Una póliza sólo acredita al vehículo al que está asociada (sin coberturas compartidas).
_NO_EXIGIDOS_POR_TIPO = {
    "TRACTO": frozenset({"SEGURO_CARGA"}),
    "CARRO": frozenset({"SOAP", "CERTIFICADO_EMISION_GASES", "POLIZA_RESPONSABILIDAD_CIVIL"}),
    "CAMION_RIGIDO": frozenset(),
}


def _requeridos_vehiculo(tipos: dict, empresa: str, tipo: str | None) -> set[str]:
    # Tipo incierto: no se calcula ningún requisito (ni se marcan faltantes).
    if tipo is None:
        return set()
    requeridos = {t for t, c in tipos.items() if c["entidad"] == VEHICULO and c["activo"] and c["obligatorio"]}
    if empresa.upper() == "MBT":
        requeridos |= {t for t in _REQUISITOS_VEHICULO_MBT if tipos[t]["activo"]}
    return requeridos - _NO_EXIGIDOS_POR_TIPO.get(tipo, frozenset())


def _requisitos_chofer(empresa, clave, documentos, documentos_chofer, tipos, catalogos):
    from atlas_core.catalogo_vehiculos import cargar_catalogo_vehiculos
    from atlas_core.catalogos import cargar_catalogo_json, rut_canonico_de_registro_chofer
    from atlas_core.fichas_choferes import asignaciones_de_chofer
    registros = cargar_catalogo_json(catalogos / "choferes.json")
    rut = rut_canonico_de_registro_chofer(clave, registros.get(clave))
    try:
        catalogo = cargar_catalogo_vehiculos(catalogos / "vehiculos.json")
        vehiculos_catalogo = catalogo.homologables()
        vehiculos = {v.patente_canonica: v for v in catalogo.vehiculos}
    except (OSError, ValueError):
        vehiculos_catalogo, vehiculos = (), {}
    asignaciones = asignaciones_de_chofer(rut, vehiculos_catalogo)
    detalles = []
    for rol, asignacion in asignaciones.items():
        if asignacion["estado"] != "CONFIRMADO":
            continue
        v = vehiculos[asignacion["patente"]]
        tipo = _tipo_vehiculo_requisitos(catalogos, v.vehiculo_id)
        requeridos = _requeridos_vehiculo(tipos, empresa, tipo)
        propios = [d for d in documentos if d["entidad"] == VEHICULO and v.vehiculo_id in d["referencias"]]
        faltantes = {a["tipo"]: a for a in _ausentes(tipos, VEHICULO, propios, requeridos=requeridos)}
        detalles.append((rol, v, tipo, requeridos, faltantes))
    licencia = _ausentes(tipos, CHOFER, documentos_chofer)
    resultado = []
    for t in _REQUISITOS_CHOFER_MBT:
        if t == "LICENCIA_CONDUCIR":
            falta = next((a for a in licencia if a["tipo"] == t), None)
            estado = "PENDIENTE_REVISION" if falta and falta["pendiente_revision"] else "FALTANTE" if falta else "PRESENTE"
            resultado.append({"tipo": t, "nombre": tipos[t]["nombre"], "ambito": "CHOFER", "estado": estado, "vehiculos": []})
            continue
        items = []
        for rol, v, tipo, requeridos, faltantes in detalles:
            falta = faltantes.get(t)
            estado = ("TIPO_INCIERTO" if tipo is None else "NO_APLICA" if t not in requeridos else
                      "PENDIENTE_REVISION" if falta and falta["pendiente_revision"] else "FALTANTE" if falta else "PRESENTE")
            items.append({"referencia_catalogo": v.vehiculo_id, "patente": v.patente_canonica,
                          "tipo_vehiculo": tipo, "rol": rol, "estado": estado})
        resultado.append({"tipo": t, "nombre": tipos[t]["nombre"],
                          "ambito": "COBERTURA" if t in ("POLIZA_RESPONSABILIDAD_CIVIL", "SEGURO_CARGA") else "VEHICULO",
                          "estado": "SIN_ASIGNACION" if not items else "POR_VEHICULO", "vehiculos": items})
    return resultado, asignaciones


def consultar_expediente(raiz: str | Path, *, empresa: str, entidad: str, referencia: str, hoy: date | None = None,
                         dias_por_vencer: int = DIAS_POR_VENCER, carpeta_catalogos: str | Path | None = None) -> dict:
    """Expediente de una identidad: vigencia, ausentes, histórico y
    trazabilidad. Lectura pura: si aún no existe, informa `existe: False`."""
    entidad = str(entidad).upper()
    clave, equivalentes, _ = _identidad(raiz, empresa, entidad, referencia, carpeta_catalogos)
    hoy = hoy or date.today()
    datos = _leer_a_fecha(raiz, empresa, hoy)
    expediente = _buscar_expediente(datos, entidad, equivalentes)
    conocidas = set(equivalentes) | set(expediente["referencias"] if expediente else ())
    todos = estado_expediente(raiz, empresa=empresa, hoy=hoy, dias_por_vencer=dias_por_vencer,
                              carpeta_catalogos=carpeta_catalogos)
    documentos = [d for d in todos if d["entidad"] == entidad and conocidas & set(d["referencias"])]
    expediente_id = expediente["expediente_id"] if expediente else ""
    tipos = tipos_documento(datos)
    catalogos = _carpeta(raiz, carpeta_catalogos)
    tipo_vehiculo = _tipo_vehiculo_requisitos(catalogos, clave) if entidad == VEHICULO else None
    requeridos = _requeridos_vehiculo(tipos, empresa, tipo_vehiculo) if entidad == VEHICULO else None
    adicionales = {}
    if entidad == VEHICULO:
        adicionales = {"tipo_vehiculo": tipo_vehiculo, "tipo_vehiculo_estado": "CONFIRMADO" if tipo_vehiculo else "INCIERTO",
                       "requisitos_aplicables": sorted(requeridos)}
    elif empresa.upper() == "MBT":
        requisitos, asignaciones = _requisitos_chofer(empresa, clave, todos, documentos, tipos, catalogos)
        adicionales = {"requisitos_documentales": requisitos, "asignaciones_requisitos": asignaciones}
    return {
        **adicionales,
        "empresa": empresa, "entidad": entidad, "referencia_catalogo": clave, "existe": expediente is not None,
        "expediente_id": expediente_id, "documentos": documentos,
        "ausentes": _ausentes(tipos, entidad, documentos, requeridos=requeridos),
        "historico": [d for d in datos["documentos"] if d["expediente_id"] == expediente_id and d["estado"] != ACTIVO],
        "trazabilidad": [e for e in datos["historial"] if expediente_id and e.get("expediente_id") == expediente_id],
    }


def consultar_vencimientos(raiz: str | Path, *, empresa: str, hoy: date | None = None,
                           dias_por_vencer: int = DIAS_POR_VENCER, entidad: str | None = None,
                           carpeta_catalogos: str | Path | None = None) -> dict[str, list[dict]]:
    """Documentos activos agrupados por estado de vencimiento."""
    grupos: dict[str, list[dict]] = {estado: [] for estado in ESTADOS_VENCIMIENTO}
    for documento in estado_expediente(raiz, empresa=empresa, hoy=hoy, dias_por_vencer=dias_por_vencer,
                                       carpeta_catalogos=carpeta_catalogos):
        if entidad is None or documento["entidad"] == str(entidad).upper():
            grupos[documento["estado_vencimiento"]].append(documento)
    return grupos


def _identidades_activas(catalogos: Path) -> list[tuple[str, str]]:
    from atlas_core.catalogo_vehiculos import cargar_catalogo_vehiculos
    from atlas_core.catalogos import cargar_catalogo_json
    choferes = cargar_catalogo_json(catalogos / "choferes.json")
    try:
        vehiculos = cargar_catalogo_vehiculos(catalogos / "vehiculos.json").vehiculos
    except ValueError as error:
        raise ErrorExpedienteDigital(f"catálogo de vehículos no disponible: {error}") from error
    if not choferes:  # `cargar_catalogo_json` devuelve {} si falta o no se puede leer
        raise ErrorExpedienteDigital("catálogo de choferes no disponible")
    return [(CHOFER, k) for k, r in choferes.items() if isinstance(r, dict) and r.get("activo", True)] + [
        (VEHICULO, v.vehiculo_id) for v in vehiculos if v.estado_vigencia == "ACTIVO"]


def documentos_ausentes(raiz: str | Path, *, empresa: str, carpeta_catalogos: str | Path | None = None) -> list[dict]:
    """Obligatorios sin documento utilizable, por cada identidad activa."""
    from atlas_core.fichas_choferes import fichas_por_referencia
    datos = leer_expediente(raiz, empresa=empresa)
    tipos, ficha_de = tipos_documento(datos), fichas_por_referencia(_leer_fichas(raiz, empresa))
    vista = estado_expediente(raiz, empresa=empresa, carpeta_catalogos=carpeta_catalogos)
    resultado = []
    for entidad, clave in _identidades_activas(_carpeta(raiz, carpeta_catalogos)):
        conocidas = set(ficha_de.get(clave, {}).get("referencias_catalogo", [clave])) if entidad == CHOFER else {clave}
        propios = [d for d in vista if d["entidad"] == entidad and conocidas & set(d["referencias"])]
        requeridos = (_requeridos_vehiculo(tipos, empresa, _tipo_vehiculo_requisitos(_carpeta(raiz, carpeta_catalogos), clave))
                      if entidad == VEHICULO else None)
        resultado += [{"entidad": entidad, "referencia_catalogo": clave, **a}
                      for a in _ausentes(tipos, entidad, propios, requeridos=requeridos)]
    return resultado


def documentos_por_atender(raiz: str | Path, *, empresa: str, hoy: date | None = None,
                           dias_por_vencer: int = DIAS_POR_VENCER,
                           carpeta_catalogos: str | Path | None = None) -> list[dict]:
    """Vencidos, próximos a vencer y con fecha ilegible."""
    return [d for d in estado_expediente(raiz, empresa=empresa, hoy=hoy, dias_por_vencer=dias_por_vencer,
                                         carpeta_catalogos=carpeta_catalogos)
            if d["estado_vencimiento"] in (VENCIDO, POR_VENCER, FECHA_INVALIDA)]


def preparar_alertas_vencimiento(raiz: str | Path, *, empresa: str, hoy: date | None = None,
                                 dias_por_vencer: int = DIAS_POR_VENCER,
                                 carpeta_catalogos: str | Path | None = None) -> list[dict]:
    """Candidatas a alerta, sin enviar ni persistir nada. `alerta_id` es estable
    por empresa, documento, fecha y nivel, para no repetir un aviso futuro."""
    return [{
        "alerta_id": str(uuid.uuid5(_ESPACIO_UUID, ":".join(
            (empresa, d["documento_id"], d["fecha_vencimiento"], d["estado_vencimiento"])))),
        "empresa": empresa, "nivel": d["estado_vencimiento"], "documento_id": d["documento_id"],
        "entidad": d["entidad"], "referencia_catalogo": d["referencia_catalogo"], "tipo": d["tipo"],
        "fecha_vencimiento": d["fecha_vencimiento"], "dias_para_vencer": d["dias_para_vencer"],
        "fuente": d["fuente"], **({"tipos_cubiertos": d["tipos_cubiertos"]} if "tipos_cubiertos" in d else {}),
    } for d in documentos_por_atender(raiz, empresa=empresa, hoy=hoy, dias_por_vencer=dias_por_vencer,
                                      carpeta_catalogos=carpeta_catalogos)]


def vista_expediente_desktop(raiz: str | Path, *, empresa: str, entidad: str, referencia: str,
                             hoy: date | None = None) -> dict:
    """Lo que muestra la ficha en Desktop. La licencia no se ofrece para registrar:
    su fuente única sigue siendo la ficha del chofer."""
    consulta = consultar_expediente(raiz, empresa=empresa, entidad=entidad, referencia=referencia, hoy=hoy)
    tipos = tipos_documento(leer_expediente(raiz, empresa=empresa))
    ids = {d["documento_id"] for d in consulta["documentos"]}
    return {
        **consulta,
        "alertas": [a for a in preparar_alertas_vencimiento(raiz, empresa=empresa, hoy=hoy) if a["documento_id"] in ids],
        "tipos_registrables": [
            {"tipo": t, "nombre": c["nombre"], "requiere_vencimiento": c["requiere_vencimiento"]}
            for t, c in tipos.items()
            if c["entidad"] == consulta["entidad"] and c["activo"] and t != "LICENCIA_CONDUCIR"],
    }


def verificar_originales(raiz: str | Path, *, empresa: str) -> list[dict]:
    """Comprueba contra su huella los originales de todos los documentos del
    expediente, también reemplazados y anulados. Sólo lee."""
    carpeta = ruta_almacen_expediente(raiz, empresa).parent
    resultado = []
    for documento in leer_expediente(raiz, empresa=empresa)["documentos"]:
        archivo, huella = documento.get("archivo", ""), documento.get("sha256", "")
        ruta = carpeta / archivo
        if not archivo:
            estado = SIN_ARCHIVO
        elif not ruta.resolve().is_relative_to(carpeta.resolve()):
            estado = FUERA_DE_EMPRESA
        elif not ruta.is_file():
            estado = ARCHIVO_AUSENTE
        elif not huella:
            estado = SIN_HUELLA
        else:
            estado = INTEGRO if hashlib.sha256(ruta.read_bytes()).hexdigest() == huella else ALTERADO
        resultado.append({"documento_id": documento["documento_id"], "archivo": archivo, "estado": estado})
    return resultado
