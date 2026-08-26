"""Catálogo portable de vehículos con compatibilidad de lectura V0/V1.

V0 es el mapa histórico ``patente -> {tipo}`` y permanece read-only. V1
incorpora evidencia y estados auditables; sólo CONFIRMADO+ACTIVO participa en
la homologación. Las observaciones OCR nunca escriben ni confirman vehículos.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Mapping
from uuid import NAMESPACE_URL, uuid5

from atlas_core.almacenamiento_portable import (
    bloqueo_sesion,
    escribir_json_atomico,
    ruta_catalogos_privados,
)


VERSION_FORMATO = 1
NOMBRE_ARCHIVO = "vehiculos.json"


def ruta_catalogo_vehiculos(*, raiz: Path | None = None) -> Path:
    return ruta_catalogos_privados(raiz=raiz) / NOMBRE_ARCHIVO


class ErrorCatalogoVehiculos(ValueError):
    pass


class CatalogoVehiculosAusenteError(ErrorCatalogoVehiculos):
    pass


class CatalogoVehiculosCorruptoError(ErrorCatalogoVehiculos):
    pass


class VersionCatalogoVehiculosDesconocidaError(ErrorCatalogoVehiculos):
    pass


class VehiculoDuplicadoError(ErrorCatalogoVehiculos):
    pass


class TipoVehiculo(str, Enum):
    TRACTO = "TRACTO"
    CARRO = "CARRO"
    # R3.2: preparación de contrato -- adición aditiva y compatible (un
    # nuevo miembro de enum no invalida catálogos V0/V1 existentes, que sólo
    # usan TRACTO/CARRO). Registrar un vehículo con este tipo no está
    # habilitado todavía en ningún flujo: falta que el pipeline de
    # extracción tenga un campo documental para una patente única de camión
    # rígido (hoy sólo existen "patente_tracto"/"patente_rampla", pensados
    # para un tracto+rampla articulado). Ver auditoría R3.2 para el detalle.
    CAMION_RIGIDO = "CAMION_RIGIDO"


class EstadoCalidadVehiculo(str, Enum):
    OBSERVADO = "OBSERVADO"
    CANDIDATO = "CANDIDATO"
    CONFIRMADO = "CONFIRMADO"
    RECHAZADO = "RECHAZADO"


class EstadoVigenciaVehiculo(str, Enum):
    ACTIVO = "ACTIVO"
    INACTIVO = "INACTIVO"


def normalizar_patente_vehiculo(valor: str) -> str:
    return "".join(str(valor or "").split()).upper()


def _validar_patente(valor: str) -> str:
    patente = normalizar_patente_vehiculo(valor)
    if not re.fullmatch(r"(?=.*[A-Z])(?=.*\d)[A-Z0-9]{6}", patente):
        raise ErrorCatalogoVehiculos("patente inválida")
    return patente


def _fecha_iso_con_zona(valor: str, campo: str, *, permitir_vacia: bool = False) -> None:
    if permitir_vacia and not valor:
        return
    try:
        fecha = datetime.fromisoformat(valor)
    except (TypeError, ValueError) as error:
        raise ErrorCatalogoVehiculos(f"{campo} debe ser una fecha ISO válida") from error
    if fecha.tzinfo is None:
        raise ErrorCatalogoVehiculos(f"{campo} debe incluir zona horaria")


@dataclass(frozen=True)
class EvidenciaVehiculo:
    tipo: str
    identificador_fuente: str
    referencia_hash: str
    campos_observados: dict[str, str]
    fecha: str
    actor_proceso: str
    resultado: str

    def a_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def desde_dict(cls, datos: object) -> "EvidenciaVehiculo":
        if not isinstance(datos, dict) or set(datos) != set(cls.__dataclass_fields__):
            raise CatalogoVehiculosCorruptoError("campos de evidencia incompatibles")
        if not isinstance(datos.get("campos_observados"), dict):
            raise CatalogoVehiculosCorruptoError("campos_observados debe ser objeto")
        evidencia = cls(**datos)
        if evidencia.resultado not in {"SOPORTA", "CONTRADICE", "NEUTRAL"}:
            raise CatalogoVehiculosCorruptoError("resultado de evidencia inválido")
        if not evidencia.tipo.strip() or not evidencia.identificador_fuente.strip():
            raise CatalogoVehiculosCorruptoError("fuente de evidencia obligatoria")
        if not evidencia.actor_proceso.strip():
            raise CatalogoVehiculosCorruptoError("actor_proceso obligatorio")
        if any(not isinstance(k, str) or not isinstance(v, str) for k, v in evidencia.campos_observados.items()):
            raise CatalogoVehiculosCorruptoError("campos_observados debe contener texto")
        _fecha_iso_con_zona(evidencia.fecha, "fecha")
        return evidencia


@dataclass(frozen=True)
class Vehiculo:
    vehiculo_id: str
    patente_canonica: str
    tipo: str
    estado_calidad: str
    estado_vigencia: str
    aliases: tuple[str, ...]
    evidencias: tuple[EvidenciaVehiculo, ...]
    procedencia: str
    confirmado_por: str
    fecha_confirmacion: str
    observaciones: str
    fecha_creacion: str
    fecha_modificacion: str

    def a_dict(self) -> dict[str, object]:
        datos = asdict(self)
        datos["aliases"] = list(self.aliases)
        datos["evidencias"] = [e.a_dict() for e in self.evidencias]
        return datos

    @classmethod
    def desde_dict(cls, datos: object) -> "Vehiculo":
        if not isinstance(datos, dict) or set(datos) != set(cls.__dataclass_fields__):
            raise CatalogoVehiculosCorruptoError("campos de vehículo incompatibles")
        if not isinstance(datos.get("aliases"), list) or not isinstance(datos.get("evidencias"), list):
            raise CatalogoVehiculosCorruptoError("aliases/evidencias deben ser listas")
        try:
            vehiculo = cls(**{
                **datos,
                "aliases": tuple(datos["aliases"]),
                "evidencias": tuple(EvidenciaVehiculo.desde_dict(e) for e in datos["evidencias"]),
            })
            _validar_vehiculo(vehiculo)
        except (TypeError, ValueError) as error:
            if isinstance(error, CatalogoVehiculosCorruptoError):
                raise
            raise CatalogoVehiculosCorruptoError(str(error)) from error
        return vehiculo


def _validar_vehiculo(vehiculo: Vehiculo) -> None:
    if not vehiculo.vehiculo_id.strip() or not vehiculo.procedencia.strip():
        raise ErrorCatalogoVehiculos("identidad y procedencia obligatorias")
    if _validar_patente(vehiculo.patente_canonica) != vehiculo.patente_canonica:
        raise ErrorCatalogoVehiculos("patente_canonica no está normalizada")
    TipoVehiculo(vehiculo.tipo)
    EstadoCalidadVehiculo(vehiculo.estado_calidad)
    EstadoVigenciaVehiculo(vehiculo.estado_vigencia)
    aliases = tuple(_validar_patente(a) for a in vehiculo.aliases)
    if len(aliases) != len(set(aliases)) or vehiculo.patente_canonica in aliases:
        raise ErrorCatalogoVehiculos("aliases duplicados o iguales a la patente")
    for alias in aliases:
        if not any(
            e.resultado == "SOPORTA"
            and normalizar_patente_vehiculo(e.campos_observados.get("alias", "")) == alias
            for e in vehiculo.evidencias
        ):
            raise ErrorCatalogoVehiculos("cada alias requiere evidencia explícita")
    _fecha_iso_con_zona(vehiculo.fecha_creacion, "fecha_creacion")
    _fecha_iso_con_zona(vehiculo.fecha_modificacion, "fecha_modificacion")
    _fecha_iso_con_zona(vehiculo.fecha_confirmacion, "fecha_confirmacion", permitir_vacia=True)
    if vehiculo.estado_calidad == EstadoCalidadVehiculo.CONFIRMADO.value:
        es_legacy = vehiculo.procedencia == "CATALOGO_LEGACY"
        if es_legacy and not any(
            e.tipo == "MIGRACION_LEGACY" for e in vehiculo.evidencias
        ):
            raise ErrorCatalogoVehiculos(
                "un confirmado legacy requiere evidencia de migración"
            )
        if not es_legacy and (not vehiculo.confirmado_por.strip() or not vehiculo.fecha_confirmacion):
            raise ErrorCatalogoVehiculos("confirmación requiere actor y fecha")


@dataclass(frozen=True)
class CatalogoVehiculosCargado:
    formato: str
    vehiculos: tuple[Vehiculo, ...]

    def homologables(self) -> tuple[Vehiculo, ...]:
        if self.formato == "V0":
            return self.vehiculos
        return tuple(
            v for v in self.vehiculos
            if v.estado_calidad == "CONFIRMADO" and v.estado_vigencia == "ACTIVO"
        )


def _vehiculo_legacy(patente: str, registro: object) -> Vehiculo:
    if not isinstance(registro, dict) or set(registro) - {"tipo", "alias"}:
        raise CatalogoVehiculosCorruptoError("registro V0 inválido")
    canonica = _validar_patente(patente)
    try:
        tipo = TipoVehiculo(str(registro.get("tipo", ""))).value
    except ValueError as error:
        raise CatalogoVehiculosCorruptoError("tipo V0 inválido") from error
    aliases_crudos = registro.get("alias", [])
    if not isinstance(aliases_crudos, list):
        raise CatalogoVehiculosCorruptoError("alias V0 inválido")
    # V0 carece de evidencia; se conserva sólo para compatibilidad de lectura.
    return Vehiculo(
        vehiculo_id=f"legacy:{canonica}", patente_canonica=canonica, tipo=tipo,
        estado_calidad="CONFIRMADO", estado_vigencia="ACTIVO",
        aliases=tuple(normalizar_patente_vehiculo(a) for a in aliases_crudos), evidencias=(),
        procedencia="CATALOGO_LEGACY", confirmado_por="", fecha_confirmacion="",
        observaciones="", fecha_creacion="1970-01-01T00:00:00+00:00",
        fecha_modificacion="1970-01-01T00:00:00+00:00",
    )


def cargar_catalogo_vehiculos(fuente: str | Path | Mapping[str, object]) -> CatalogoVehiculosCargado:
    if isinstance(fuente, Mapping):
        contenido: object = dict(fuente)
    else:
        ruta = Path(fuente)
        if not ruta.is_file():
            raise CatalogoVehiculosAusenteError(f"catálogo ausente: {ruta}")
        try:
            contenido = json.loads(ruta.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise CatalogoVehiculosCorruptoError(f"JSON inválido: {ruta}") from error
    if not isinstance(contenido, dict):
        raise CatalogoVehiculosCorruptoError("la raíz debe ser un objeto")
    if "version" in contenido or "vehiculos" in contenido:
        if contenido.get("version") != VERSION_FORMATO:
            raise VersionCatalogoVehiculosDesconocidaError(str(contenido.get("version")))
        if set(contenido) != {"version", "vehiculos"} or not isinstance(contenido["vehiculos"], list):
            raise CatalogoVehiculosCorruptoError("esquema V1 inválido")
        vehiculos = tuple(Vehiculo.desde_dict(v) for v in contenido["vehiculos"])
        formato = "V1"
    else:
        vehiculos = tuple(_vehiculo_legacy(str(p), r) for p, r in contenido.items())
        formato = "V0"
    _validar_unicidad(vehiculos)
    return CatalogoVehiculosCargado(formato, vehiculos)


def _validar_unicidad(vehiculos: tuple[Vehiculo, ...]) -> None:
    patentes = [v.patente_canonica for v in vehiculos]
    ids = [v.vehiculo_id for v in vehiculos]
    aliases = [a for v in vehiculos for a in v.aliases]
    if len(patentes) != len(set(patentes)) or len(ids) != len(set(ids)):
        raise VehiculoDuplicadoError("patente o vehiculo_id duplicado")
    if len(aliases) != len(set(aliases)):
        raise VehiculoDuplicadoError("alias duplicado")
    if set(aliases) & set(patentes):
        raise VehiculoDuplicadoError("alias colisiona con patente canónica")


_CONFUSIONES_OCR = tuple(map(frozenset, (
    {"B", "D"}, {"0", "O"}, {"1", "I"}, {"5", "S"}, {"8", "B"}, {"8", "E"}, {"2", "B"}, {"K", "R"},
    # Bloque R11 -- caso real 472247 (Rodrigo Nahuelñir): OCR leyó "JE4288"
    # para patente_rampla; la patente real, confirmada por Javier, es
    # "JF4288" -- E/F es una confusión de trazo real y documentada (no una
    # tabla ampliada a ciegas), igual que las demás de este set.
    {"E", "F"},
    # Bloque VEHÍCULO E2 -- caso real 472339 (Cristopher Retamal): OCR
    # leyó "BPHF67" para patente_tracto; la patente real, con dos
    # transportes independientes previos que la corroboran, es "BPHR67"
    # -- F/R es una confusión de trazo real y documentada en este
    # documento (no una tabla ampliada a ciegas), igual que las demás.
    {"F", "R"},
)))


@dataclass(frozen=True)
class ResultadoResolucionPatente:
    estado: str
    valor_original: str
    valor_resultado: str
    candidatos_ambiguos: tuple[str, ...] = ()


def _diferencia_ocr_segura(a: str, b: str) -> bool:
    diferencias = [(x, y) for x, y in zip(a, b) if x != y]
    return len(a) == len(b) and len(diferencias) == 1 and frozenset(diferencias[0]) in _CONFUSIONES_OCR


def resolver_patente(fuente: str | Path | Mapping[str, object], patente_observada: str, *, tipo_esperado: str | None = None) -> ResultadoResolucionPatente:
    original = str(patente_observada or "").strip()
    if not original or original == "No encontrado":
        return ResultadoResolucionPatente("VACIO", original, original)
    observado = normalizar_patente_vehiculo(original)
    try:
        catalogo = cargar_catalogo_vehiculos(fuente)
    except CatalogoVehiculosAusenteError:
        return ResultadoResolucionPatente("CATALOGO_VACIO", original, original)
    vehiculos = catalogo.homologables()
    if not vehiculos:
        return ResultadoResolucionPatente("CATALOGO_VACIO", original, original)
    tipo = str(tipo_esperado or "").strip().upper()
    # V0 preserva exactamente el contrato histórico: el tipo sólo filtraba la
    # corrección OCR. V1 sí aplica el tipo esperado a toda resolución.
    elegibles = vehiculos if catalogo.formato == "V0" else tuple(
        v for v in vehiculos if not tipo or v.tipo == tipo
    )
    exactos = {v.patente_canonica for v in elegibles if v.patente_canonica == observado}
    if len(exactos) == 1:
        return ResultadoResolucionPatente("COINCIDENCIA_EXACTA", original, next(iter(exactos)))
    por_alias = {v.patente_canonica for v in elegibles if observado in v.aliases}
    if len(por_alias) == 1:
        return ResultadoResolucionPatente("ALIAS", original, next(iter(por_alias)))
    if len(por_alias) > 1:
        return ResultadoResolucionPatente("AMBIGUO", original, original, tuple(sorted(por_alias)))
    if not re.fullmatch(r"(?=.*[A-Z])(?=.*\d)[A-Z0-9]{6}", observado):
        return ResultadoResolucionPatente("SIN_CANDIDATO", original, original)
    candidatos_ocr = tuple(
        v for v in vehiculos
        if (not tipo or v.tipo == tipo) and _diferencia_ocr_segura(observado, v.patente_canonica)
    )
    candidatos = {v.patente_canonica for v in candidatos_ocr}
    if len(candidatos) == 1:
        return ResultadoResolucionPatente("CORRECCION_OCR_SEGURA", original, next(iter(candidatos)))
    if len(candidatos) > 1:
        return ResultadoResolucionPatente("AMBIGUO", original, original, tuple(sorted(candidatos)))
    return ResultadoResolucionPatente("SIN_CANDIDATO", original, original)


def migrar_v0_a_v1(contenido_v0: Mapping[str, object], *, fecha: datetime, referencia_hash: str = "") -> dict[str, object]:
    if fecha.tzinfo is None:
        raise ErrorCatalogoVehiculos("fecha debe incluir zona horaria")
    cargado = cargar_catalogo_vehiculos(contenido_v0)
    if cargado.formato != "V0":
        raise ErrorCatalogoVehiculos("se esperaba formato V0")
    instante = fecha.astimezone(timezone.utc).isoformat()
    salida: list[dict[str, object]] = []
    for legado in cargado.vehiculos:
        evidencia = EvidenciaVehiculo(
            tipo="MIGRACION_LEGACY", identificador_fuente=NOMBRE_ARCHIVO,
            referencia_hash=referencia_hash, campos_observados={"patente": legado.patente_canonica, "tipo": legado.tipo},
            fecha=instante, actor_proceso="PROCESO_MIGRACION", resultado="SOPORTA",
        )
        evidencias_alias = tuple(
            EvidenciaVehiculo(
                tipo="MIGRACION_LEGACY", identificador_fuente=NOMBRE_ARCHIVO,
                referencia_hash=referencia_hash, campos_observados={"alias": alias},
                fecha=instante, actor_proceso="PROCESO_MIGRACION", resultado="SOPORTA",
            )
            for alias in legado.aliases
        )
        vehiculo = Vehiculo(
            vehiculo_id=str(uuid5(NAMESPACE_URL, f"atlas:vehiculo:{legado.patente_canonica}")),
            patente_canonica=legado.patente_canonica, tipo=legado.tipo,
            estado_calidad="CONFIRMADO", estado_vigencia="ACTIVO", aliases=legado.aliases,
            evidencias=(evidencia, *evidencias_alias), procedencia="CATALOGO_LEGACY",
            confirmado_por="", fecha_confirmacion="",
            observaciones="Confianza operacional heredada; no representa confirmación humana histórica.",
            fecha_creacion=instante, fecha_modificacion=instante,
        )
        salida.append(vehiculo.a_dict())
    resultado = {"version": VERSION_FORMATO, "vehiculos": salida}
    cargar_catalogo_vehiculos(resultado)
    return resultado


def confirmar_vehiculo(
    ruta: str | Path | None = None, *, patente: str, tipo: TipoVehiculo | str, actor: str,
    fuente_decision: str, fecha: datetime, referencia_hash: str = "",
    observaciones: str = "", rut_chofer_asociado: str = "",
) -> Vehiculo:
    if not actor.strip():
        raise ErrorCatalogoVehiculos("actor obligatorio")
    if not fuente_decision.strip():
        raise ErrorCatalogoVehiculos("fuente_decision obligatoria")
    if fecha.tzinfo is None:
        raise ErrorCatalogoVehiculos("fecha debe incluir zona horaria")
    canonica = _validar_patente(patente)
    try:
        tipo_valido = TipoVehiculo(tipo).value
    except ValueError as error:
        raise ErrorCatalogoVehiculos("tipo inválido") from error
    instante = fecha.astimezone(timezone.utc).isoformat()
    # Bloque VEHÍCULO E1 -- campo opcional y aditivo (no rompe ningún
    # llamador existente, que sigue sin pasarlo): cuando una confirmación
    # humana se origina específicamente para un chofer/RUT determinado
    # (p. ej. el chofer mismo confirmó su patente a Javier), se registra
    # aquí para que el motor de evidencia pueda reconocerla como
    # CONFIRMACION_HUMANA_ASOCIADA en decisiones futuras de ESE mismo
    # RUT -- nunca se infiere, sólo se persiste lo que el llamador ya
    # sabía con certeza al confirmar.
    campos_observados: dict[str, object] = {
        "patente": canonica,
        "tipo": tipo_valido,
        "observacion": observaciones.strip(),
    }
    if rut_chofer_asociado.strip():
        campos_observados["rut_chofer_asociado"] = rut_chofer_asociado.strip()
    evidencia = EvidenciaVehiculo(
        tipo="CONFIRMACION_HUMANA",
        identificador_fuente=fuente_decision.strip(),
        referencia_hash=str(referencia_hash or "").strip(),
        campos_observados=campos_observados,
        fecha=instante,
        actor_proceso=actor.strip(),
        resultado="SOPORTA",
    )
    EvidenciaVehiculo.desde_dict(evidencia.a_dict())
    ruta = Path(ruta) if ruta is not None else ruta_catalogo_vehiculos()
    with bloqueo_sesion(ruta.parent, "catalogo_vehiculos"):
        cargado = cargar_catalogo_vehiculos(ruta)
        if cargado.formato != "V1":
            raise ErrorCatalogoVehiculos("la confirmación sólo escribe catálogos V1")
        existente = next((v for v in cargado.vehiculos if v.patente_canonica == canonica), None)
        if existente is not None and existente.tipo != tipo_valido:
            raise ErrorCatalogoVehiculos("el tipo contradice el registro existente")
        if existente is not None and existente.estado_vigencia == "INACTIVO":
            raise ErrorCatalogoVehiculos("un vehículo inactivo requiere reactivación explícita")
        if existente is not None and existente.estado_calidad == "RECHAZADO":
            raise ErrorCatalogoVehiculos("un vehículo rechazado no puede confirmarse")
        ratificacion_legacy = (
            existente is not None
            and existente.estado_calidad == "CONFIRMADO"
            and existente.procedencia == "CATALOGO_LEGACY"
            and not existente.confirmado_por
            and not existente.fecha_confirmacion
        )
        if existente is not None and existente.estado_calidad == "CONFIRMADO" and not ratificacion_legacy:
            raise VehiculoDuplicadoError("el vehículo ya tiene confirmación humana")
        vehiculo = Vehiculo(
            vehiculo_id=(existente.vehiculo_id if existente else str(uuid5(NAMESPACE_URL, f"atlas:vehiculo:{canonica}"))),
            patente_canonica=canonica, tipo=tipo_valido,
            estado_calidad="CONFIRMADO", estado_vigencia="ACTIVO",
            aliases=(existente.aliases if existente else ()),
            evidencias=(*(existente.evidencias if existente else ()), evidencia),
            procedencia=(existente.procedencia if existente else "CONFIRMACION_HUMANA"),
            confirmado_por=actor.strip(), fecha_confirmacion=instante,
            observaciones=observaciones.strip(),
            fecha_creacion=(existente.fecha_creacion if existente else instante),
            fecha_modificacion=instante,
        )
        _validar_vehiculo(vehiculo)
        contenido = {
            "version": VERSION_FORMATO,
            "vehiculos": [
                *(v.a_dict() for v in cargado.vehiculos if v.patente_canonica != canonica),
                vehiculo.a_dict(),
            ],
        }
        cargar_catalogo_vehiculos(contenido)
        escribir_json_atomico(ruta, contenido)
        return vehiculo
