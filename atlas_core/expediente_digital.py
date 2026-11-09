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
    "SEGURO_CARGA": {"entidad": VEHICULO, "nombre": "Seguro de carga", "obligatorio": False},
}
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


# ------------------------------------------------------------------ escritura de documentos


def registrar_documento(
    raiz: str | Path, *, empresa: str, entidad: str, referencia: str, tipo: str, actor: str,
    fecha_vencimiento: str = "", fecha_emision: str = "", archivo: str = "", sha256: str = "",
    contenido: bytes | None = None, mime_type: str = "",
    carpeta_catalogos: str | Path | None = None, reloj: _Reloj = _ahora_utc,
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
            emision, vencimiento = _fechas(fecha_emision, fecha_vencimiento, definicion["requiere_vencimiento"],
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
            reemplazados = []
            for previo in datos["documentos"]:
                if previo["expediente_id"] == expediente["expediente_id"] and previo["tipo"] == tipo \
                        and previo["estado"] == ACTIVO:
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


def _documento_de_ficha(doc: dict, entidad: str, referencias: list[str], fuente: str) -> dict:
    vencimiento = str(doc.get("vencimiento") or "")
    return {
        "documento_id": doc["documento_id"], "entidad": entidad, "referencia_catalogo": referencias[-1],
        "referencias": referencias, "tipo": doc["tipo"], "fecha_emision": "", "fecha_vencimiento": vencimiento,
        "estado": ACTIVO, "archivo": str(doc.get("archivo", "")), "sha256": str(doc.get("sha256", "")),
        "fuente": fuente, "pendiente_revision": not vencimiento,
        "confirmado_por_humano": bool(vencimiento) and doc.get("estado_revision") != _ESTADO_OCR_AUTOMATICO,
    }


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
        documentos += [_documento_de_ficha(doc, VEHICULO, [patentes.get(patente, patente)], "FICHA_VEHICULO")
                       for doc in ficha.get("documentos", []) if doc.get("tipo") and not doc.get("reemplazado_por")]
    resultado, mejores = [], {}
    for doc in documentos:
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
    datos = leer_expediente(raiz, empresa=empresa)
    referencias = {e["expediente_id"]: e["referencias"] for e in datos["expedientes"]}
    propios = [{**d, "fuente": "EXPEDIENTE", "pendiente_revision": False, "confirmado_por_humano": True,
                "referencias": referencias[d["expediente_id"]]}
               for d in datos["documentos"] if d["estado"] == ACTIVO]
    claves = lambda d: [(d["entidad"], r, d["tipo"]) for r in d["referencias"]]  # noqa: E731
    registrados = {k: d["fecha_vencimiento"] for d in propios for k in claves(d)}
    fichas = _documentos_de_fichas(raiz, empresa, _carpeta(raiz, carpeta_catalogos))
    # Una renovación llegada después por la ficha no queda oculta tras el registro antiguo.
    mas_recientes = [d for d in fichas if not d["pendiente_revision"]
                     and _dias_para_vencer(d["fecha_vencimiento"], date.min) is not None
                     and any(k in registrados and d["fecha_vencimiento"] > registrados[k] for k in claves(d))]
    superados = {k for d in mas_recientes for k in claves(d)}
    propios = [d for d in propios if not superados & set(claves(d))]
    externos = [d for d in fichas if d in mas_recientes or not any(k in registrados for k in claves(d))]
    vista = []
    for d in propios + externos:
        estado = PENDIENTE_REVISION if d["pendiente_revision"] else estado_vencimiento(
            d["fecha_vencimiento"], hoy=hoy, dias_por_vencer=dias_por_vencer)
        vista.append({**d, "estado_vencimiento": estado, "dias_para_vencer": _dias_para_vencer(d["fecha_vencimiento"], hoy)})
    return sorted(vista, key=lambda d: (d["dias_para_vencer"] is None, d["dias_para_vencer"] or 0))


def _ausentes(tipos: dict, entidad: str, documentos: list[dict]) -> list[dict]:
    presentes = {d["tipo"] for d in documentos if d["estado_vencimiento"] != PENDIENTE_REVISION}
    pendientes = {d["tipo"] for d in documentos if d["estado_vencimiento"] == PENDIENTE_REVISION}
    return [{"tipo": t, "nombre": c["nombre"], "pendiente_revision": t in pendientes} for t, c in tipos.items()
            if c["entidad"] == entidad and c["obligatorio"] and c["activo"] and t not in presentes]


def consultar_expediente(raiz: str | Path, *, empresa: str, entidad: str, referencia: str, hoy: date | None = None,
                         dias_por_vencer: int = DIAS_POR_VENCER, carpeta_catalogos: str | Path | None = None) -> dict:
    """Expediente de una identidad: vigencia, ausentes, histórico y
    trazabilidad. Lectura pura: si aún no existe, informa `existe: False`."""
    entidad = str(entidad).upper()
    clave, equivalentes, _ = _identidad(raiz, empresa, entidad, referencia, carpeta_catalogos)
    datos = leer_expediente(raiz, empresa=empresa)
    expediente = _buscar_expediente(datos, entidad, equivalentes)
    conocidas = set(equivalentes) | set(expediente["referencias"] if expediente else ())
    documentos = [d for d in estado_expediente(raiz, empresa=empresa, hoy=hoy, dias_por_vencer=dias_por_vencer,
                                               carpeta_catalogos=carpeta_catalogos)
                  if d["entidad"] == entidad and conocidas & set(d["referencias"])]
    expediente_id = expediente["expediente_id"] if expediente else ""
    return {
        "empresa": empresa, "entidad": entidad, "referencia_catalogo": clave, "existe": expediente is not None,
        "expediente_id": expediente_id, "documentos": documentos,
        "ausentes": _ausentes(tipos_documento(datos), entidad, documentos),
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
        resultado += [{"entidad": entidad, "referencia_catalogo": clave, **a} for a in _ausentes(tipos, entidad, propios)]
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
        "fuente": d["fuente"],
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
