"""Capa canónica de ACCIONES OPERACIONALES para agentes (B1) y operadores.

Un agente nunca edita CSV/JSON/catálogos: pide una acción TIPADA, recibe un
PREVIEW estructurado y sólo una confirmación externa -- que cita el token de
ESE preview -- la ejecuta. El ejecutor usa exclusivamente los parámetros
guardados con el preview (nunca los que el llamador reenvíe), por lo que es
imposible confirmar una propuesta y ejecutar otra.

    acción tipada -> preview (token) -> confirmación -> ejecutar -> reconciliar
    -> revalidar afectados -> auditar -> resultado

Esta capa NO interpreta lenguaje natural ni decide nada: cada acción delega
la escritura en el servicio canónico ya existente del dominio (catálogo de
choferes/vehículos/obras/destinos, reparador focal, `aplicar_decision_obra`).
Lo que agrega es el contrato común: validación estricta de parámetros,
huella del estado base de la entidad afectada (PREVIEW_OBSOLETO si cambió),
bloqueo, respaldo focal con restauración ante fallo, reconciliación de la
bandeja, revalidación focal, idempotencia y auditoría append-only.

Nada es específico de una empresa: las entidades se identifican por los
identificadores de los catálogos (RUT/clave de chofer, patente, obra_id,
destino_id, decision_id, número de guía) y el registro de acciones es
extensible (`ACCIONES`).
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import re
import shutil
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Iterable, Mapping

from atlas_core.almacenamiento_portable import (
    SesionOcupadaError, bloqueo_sesion, escribir_json_atomico,
)

SCHEMA_VERSION = 1
NOMBRE_REGISTRO = "acciones_operacionales.json"
NOMBRE_LOCK = "acciones_operacionales"
TTL_PREVIEW = timedelta(minutes=30)
# Tipo con que una corrección documental del operador queda en el ledger
# de decisiones: el replay OCR/reparador la respeta (`_hay_decision_
# humana_para_campo`), y ningún lector del ledger la confunde con una
# decisión de Revisión (todos filtran por tipo/acción).
TIPO_LEDGER_CORRECCION = "CORRECCION_DOCUMENTAL_OPERADOR"

# --------------------------------------------------------------- riesgo

LECTURA = "LECTURA"
OPERACIONAL_REVERSIBLE = "OPERACIONAL_REVERSIBLE"
SENSIBLE = "SENSIBLE"
DESTRUCTIVA = "DESTRUCTIVA"

ORIGEN_HUMANO = "HUMANO"
ORIGEN_B1 = "B1"
ORIGEN_SISTEMA = "SISTEMA"
ORIGENES = frozenset({ORIGEN_HUMANO, ORIGEN_B1, ORIGEN_SISTEMA})

POLITICA_AUTONOMIA = {
    LECTURA: "AUTOMATICA",
    OPERACIONAL_REVERSIBLE: "CONFIRMACION_HUMANA",
    SENSIBLE: "FUERA_DE_AUTONOMIA_B1",
    DESTRUCTIVA: "PROHIBIDA",
}

# --------------------------------------------------------------- errores


class ErrorAccionOperacional(ValueError):
    def __init__(self, codigo: str, mensaje: str):
        super().__init__(mensaje)
        self.codigo = codigo


def _rechazo(error: ErrorAccionOperacional, **extra) -> dict[str, object]:
    return {"estado": "RECHAZADA", "codigo": error.codigo, "mensaje": str(error), **extra}


# --------------------------------------------------------------- parámetros

_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")


@dataclass(frozen=True)
class Parametro:
    tipo: str  # texto | id | rut | patente | bool | enum | numero | lista_texto | guia | transporte | archivo_documento | fecha
    obligatorio: bool = False
    opciones: tuple[str, ...] = ()
    max_largo: int = 300


def _validar_valor(nombre: str, spec: Parametro, valor: object) -> object:
    def invalido(motivo: str) -> ErrorAccionOperacional:
        return ErrorAccionOperacional("PARAMETRO_INVALIDO", f"{nombre}: {motivo}")

    if spec.tipo == "bool":
        if not isinstance(valor, bool):
            raise invalido("debe ser booleano")
        return valor
    if spec.tipo == "numero":
        if isinstance(valor, bool) or not isinstance(valor, (int, float)) or not math.isfinite(valor):
            raise invalido("debe ser numérico")
        return float(valor)
    if spec.tipo == "lista_texto":
        if not isinstance(valor, list) or len(valor) > 10:
            raise invalido("debe ser una lista de a lo más 10 textos")
        return [_validar_valor(nombre, Parametro("texto", max_largo=spec.max_largo), v) for v in valor]
    if not isinstance(valor, str):
        raise invalido("debe ser texto")
    texto = " ".join(valor.split()) if spec.tipo == "texto" else valor.strip()
    if not texto:
        raise invalido("vacío")
    if len(texto) > spec.max_largo or _CONTROL.search(valor):
        raise invalido("largo o caracteres no permitidos")
    if spec.tipo == "enum":
        texto = texto.upper()
        if texto not in spec.opciones:
            raise invalido(f"debe ser uno de {', '.join(spec.opciones)}")
    elif spec.tipo == "id":
        if not _ID.fullmatch(texto):
            raise invalido("identificador con formato inválido")
    elif spec.tipo == "rut":
        if not re.fullmatch(r"[0-9.]{1,12}-?[0-9Kk]", texto):
            raise invalido("RUT con formato inválido")
    elif spec.tipo == "patente":
        texto = re.sub(r"[\s-]", "", texto).upper()
        if not re.fullmatch(r"(?=.*[A-Z])(?=.*\d)[A-Z0-9]{5,8}", texto):
            raise invalido("patente con formato inválido")
    elif spec.tipo == "guia":
        if not re.fullmatch(r"\d{3,12}", texto):
            raise invalido("número de guía inválido")
    elif spec.tipo == "fecha":
        try:
            date.fromisoformat(texto)
        except ValueError:
            raise invalido("fecha inválida (AAAA-MM-DD)") from None
    elif spec.tipo == "transporte":
        if not re.fullmatch(r"\d{4,15}", texto):
            raise invalido("número de transporte inválido")
    elif spec.tipo == "archivo_documento":
        # Sólo una CLAVE de búsqueda contra el dataset (nunca se abre como
        # ruta): se rechaza cualquier forma de salto o ruta absoluta.
        if ".." in texto or texto.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:", texto):
            raise invalido("referencia de documento no permitida")
    return texto


def _validar_parametros(esquema: Mapping[str, Parametro], parametros: object) -> dict[str, object]:
    if parametros is None:
        parametros = {}
    if not isinstance(parametros, Mapping):
        raise ErrorAccionOperacional("PARAMETRO_INVALIDO", "los parámetros deben ser un objeto")
    extra = sorted(str(k) for k in parametros if k not in esquema)
    if extra:
        raise ErrorAccionOperacional(
            "PARAMETRO_NO_PERMITIDO", f"parámetros no admitidos por la acción: {', '.join(extra)}",
        )
    limpios: dict[str, object] = {}
    for nombre, spec in esquema.items():
        if nombre not in parametros or parametros[nombre] is None:
            if spec.obligatorio:
                raise ErrorAccionOperacional("PARAMETRO_FALTANTE", f"falta el parámetro {nombre}")
            continue
        limpios[nombre] = _validar_valor(nombre, spec, parametros[nombre])
    return limpios


# --------------------------------------------------------------- utilidades


def _huella(valor: object) -> str:
    serializado = json.dumps(valor, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(serializado.encode("utf-8")).hexdigest()


def _leer_json(ruta: Path, defecto):
    try:
        return json.loads(ruta.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return defecto
    except (OSError, json.JSONDecodeError) as error:
        raise ErrorAccionOperacional("ESTADO_ILEGIBLE", f"no se pudo leer {ruta.name}") from error


class _Contexto:
    def __init__(self, raiz: Path, reloj, proveedor_rutas, proveedor_rutas_fallback):
        self.raiz = raiz
        self.actual = raiz / "operacion" / "actual"
        self.catalogos = raiz / "catalogos_privados"
        self.reloj = reloj
        self.proveedor_rutas = proveedor_rutas
        self.proveedor_rutas_fallback = proveedor_rutas_fallback
        self.token = ""
        self.confirmado_por = ""
        # Únicos archivos que esta capa puede respaldar/restaurar -- rutas
        # fijas de la raíz, nunca derivadas de parámetros.
        self.archivos = {
            "choferes": self.catalogos / "choferes.json",
            "vehiculos": self.catalogos / "vehiculos.json",
            "clientes": self.catalogos / "clientes.json",
            "obras_destinos": self.catalogos / "obras_destinos.json",
            "destinos_maestros": self.catalogos / "destinos_maestros.json",
            "dataset": self.actual / "analisis_completo_guias.csv",
            "bandeja": self.actual / "decisiones_pendientes.json",
            "ledger_decisiones": self.actual / "decisiones_aplicadas.json",
            "agrupaciones_viaje": self.actual / "agrupaciones_viaje.json",
        }

    def filas(self) -> list[dict[str, str]]:
        ruta = self.archivos["dataset"]
        if not ruta.is_file():
            return []
        with ruta.open("r", newline="", encoding="utf-8-sig") as archivo:
            return list(csv.DictReader(archivo, delimiter=";"))

    def decisiones(self) -> list[dict[str, object]]:
        contenido = _leer_json(self.archivos["bandeja"], {})
        clave = "decisiones" if isinstance(contenido.get("decisiones"), list) else "decisions"
        return [d for d in contenido.get(clave) or [] if isinstance(d, dict)]

    def choferes(self) -> dict[str, dict]:
        contenido = _leer_json(self.archivos["choferes"], {})
        return contenido if isinstance(contenido, dict) else {}

    def catalogo_obras(self):
        from atlas_core.catalogo_obras_destinos import CatalogoObrasDestinos
        return CatalogoObrasDestinos(
            ruta=self.archivos["obras_destinos"], ruta_clientes=self.archivos["clientes"],
            ruta_destinos=self.archivos["destinos_maestros"],
        )

    def catalogo_destinos(self):
        from atlas_core.catalogo_destinos import CatalogoDestinos
        return CatalogoDestinos(self.archivos["destinos_maestros"], ruta_clientes=self.archivos["clientes"])


@dataclass
class Plan:
    entidad: dict[str, object]
    valor_actual: object
    valor_propuesto: object
    estado_base: object
    sin_cambios: bool = False
    afectados: dict[str, object] = field(default_factory=dict)
    consecuencias: list[str] = field(default_factory=list)
    revalidaciones: list[str] = field(default_factory=list)
    archivos: tuple[str, ...] = ()
    datos: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class DefinicionAccion:
    nombre: str
    riesgo: str
    descripcion: str
    parametros: Mapping[str, Parametro]
    planificar: Callable[[_Contexto, dict], Plan] | None = None
    aplicar: Callable[[_Contexto, dict, Plan, str], dict] | None = None
    consultar: Callable[[_Contexto, dict], object] | None = None


def _afectados_por_guias(ctx: _Contexto, guias: set[str], *, limite: int = 50) -> dict[str, object]:
    guias = {g for g in guias if g}
    decisiones = [
        {"decision_id": d.get("decision_id"), "tipo": d.get("tipo"),
         "numero_guia": (d.get("documento") or {}).get("numero_guia")}
        for d in ctx.decisiones() if str((d.get("documento") or {}).get("numero_guia", "")) in guias
    ]
    return {"guias": sorted(guias)[:limite], "total_guias": len(guias),
            "decisiones_pendientes": decisiones[:limite], "total_decisiones": len(decisiones)}


# =============================================================== CHOFERES


def _resolver_chofer(choferes: Mapping[str, dict], referencia: str) -> str:
    from atlas_core.catalogos import normalizar_rut
    if referencia in choferes and isinstance(choferes[referencia], dict):
        return referencia
    buscado = normalizar_rut(referencia)
    coincidencias = [
        clave for clave, registro in choferes.items()
        if isinstance(registro, dict) and buscado
        and buscado in {normalizar_rut(clave), normalizar_rut(str(registro.get("rut", "")))}
    ]
    if len(coincidencias) == 1:
        return coincidencias[0]
    if coincidencias:
        raise ErrorAccionOperacional("ENTIDAD_AMBIGUA", "el RUT identifica a más de un chofer")
    raise ErrorAccionOperacional("ENTIDAD_NO_ENCONTRADA", "chofer inexistente en el catálogo")


def _vista_chofer(clave: str, registro: Mapping[str, object]) -> dict[str, object]:
    from atlas_core.catalogos import rut_canonico_de_registro_chofer
    return {"chofer_id": clave, "nombre": str(registro.get("nombre", "")),
            "rut": rut_canonico_de_registro_chofer(clave, registro) or "",
            "activo": registro.get("activo", True) is True,
            "aliases": list(registro.get("aliases") or [])}


def _guias_de_chofer(ctx: _Contexto, clave: str, registro: Mapping[str, object]) -> set[str]:
    from atlas_core.catalogos import normalizar_rut
    ruts = {normalizar_rut(clave), normalizar_rut(str(registro.get("rut", "")))} - {""}
    return {str(f.get("numero_guia", "")).strip() for f in ctx.filas()
            if normalizar_rut(str(f.get("rut_chofer", ""))) in ruts}


def _fecha_documental(valor: object) -> date | None:
    try:
        return datetime.strptime(str(valor or "").strip(), "%d-%m-%Y").date()
    except ValueError:
        return None


def choferes_catalogo_con_viajes(
    choferes: Mapping[str, object], filas: Iterable[Mapping[str, str]], *,
    desde: date | None = None, hasta: date | None = None,
) -> dict[str, str]:
    """Choferes del CATÁLOGO que aparecen al menos una vez en el dataset
    operacional (o dentro de [desde, hasta]): {clave: "RUT" | "NOMBRE"}.

    Cruce sólo para estadística -- nunca crea ni confirma identidad, nunca
    escribe. Primero el RUT canónico; el nombre/alias normalizado sólo para
    choferes SIN RUT canónico y sólo si ese nombre identifica a UN único
    chofer del catálogo."""
    from atlas_core.catalogos import _normalizar_nombre_chofer, normalizar_rut, rut_canonico_de_registro_chofer

    claves_por_rut: dict[str, set[str]] = {}
    claves_por_nombre: dict[str, set[str]] = {}
    sin_rut: set[str] = set()
    for clave, registro in choferes.items():
        if not isinstance(registro, dict):
            continue
        rut = rut_canonico_de_registro_chofer(clave, registro)
        if rut:
            claves_por_rut.setdefault(normalizar_rut(rut), set()).add(clave)
        else:
            sin_rut.add(clave)
        for nombre in (registro.get("nombre"), *(registro.get("aliases") or ())):
            normalizado = _normalizar_nombre_chofer(str(nombre or ""))
            if normalizado:
                claves_por_nombre.setdefault(normalizado, set()).add(clave)

    encontrados: dict[str, str] = {}
    for fila in filas:
        if desde is not None or hasta is not None:
            fecha = _fecha_documental(fila.get("fecha"))
            if fecha is None or (desde and fecha < desde) or (hasta and fecha > hasta):
                continue
        por_rut = claves_por_rut.get(normalizar_rut(str(fila.get("rut_chofer", ""))), set())
        if len(por_rut) == 1:
            encontrados.setdefault(next(iter(por_rut)), "RUT")
            continue
        if por_rut:
            continue  # RUT compartido por varios registros: nunca se elige
        por_nombre = claves_por_nombre.get(_normalizar_nombre_chofer(str(fila.get("chofer", ""))), set())
        if len(por_nombre) == 1 and next(iter(por_nombre)) in sin_rut:
            encontrados.setdefault(next(iter(por_nombre)), "NOMBRE")
    return encontrados


def _consultar_choferes(ctx: _Contexto, p: dict) -> object:
    """Catálogo de choferes (registrados/activos/inactivos) cruzado con su
    actividad en el dataset vigente (con/sin viajes, opcionalmente en un
    período). Nunca cuenta choferes que no están en el catálogo."""
    filtro = p.get("estado", "TODOS")
    viajes = p.get("viajes", "TODOS")
    desde = date.fromisoformat(p["fecha_desde"]) if p.get("fecha_desde") else None
    hasta = date.fromisoformat(p["fecha_hasta"]) if p.get("fecha_hasta") else None
    choferes = ctx.choferes()
    con_viajes = choferes_catalogo_con_viajes(choferes, ctx.filas(), desde=desde, hasta=hasta)
    todas = [{**_vista_chofer(k, r), "con_viajes": k in con_viajes}
             for k, r in sorted(choferes.items()) if isinstance(r, dict)]
    vistas = todas
    if filtro != "TODOS":
        vistas = [v for v in vistas if v["activo"] is (filtro == "ACTIVO")]
    if viajes != "TODOS":
        vistas = [v for v in vistas if v["con_viajes"] is (viajes == "CON")]
    activos = sum(v["activo"] for v in todas)
    con = sum(v["con_viajes"] for v in todas)
    return {
        "choferes": vistas, "total": len(vistas), "estado": filtro, "viajes": viajes,
        "periodo": ({"desde": p.get("fecha_desde", ""), "hasta": p.get("fecha_hasta", "")}
                    if desde or hasta else None),
        "resumen": {"registrados": len(todas), "activos": activos, "inactivos": len(todas) - activos,
                    "con_viajes": con, "sin_viajes": len(todas) - con},
    }


def _plan_chofer_estado(ctx: _Contexto, p: dict) -> Plan:
    choferes = ctx.choferes()
    clave = _resolver_chofer(choferes, str(p["chofer"]))
    registro = choferes[clave]
    actual = registro.get("activo", True) is True
    nuevo = bool(p["activo"])
    guias = _guias_de_chofer(ctx, clave, registro)
    consecuencias = (
        ["Los resolutores de identidad sólo consideran choferes activos: guías nuevas con este chofer"
         " quedarán sin corroborar hasta reactivarlo.", "El historial documental y los viajes existentes no se modifican."]
        if not nuevo else
        ["El chofer vuelve a ser elegible para resolver identidad en guías nuevas y en la bandeja."]
    )
    return Plan(
        entidad={"tipo": "CHOFER", "id": clave, "nombre": registro.get("nombre", "")},
        valor_actual={"activo": actual}, valor_propuesto={"activo": nuevo},
        estado_base={"chofer": registro}, sin_cambios=actual == nuevo,
        afectados=_afectados_por_guias(ctx, guias), consecuencias=consecuencias,
        revalidaciones=["RECONCILIAR_BANDEJA"], archivos=("choferes", "bandeja"),
        datos={"clave": clave},
    )


def _aplicar_chofer_estado(ctx: _Contexto, p: dict, plan: Plan, actor: str) -> dict:
    from atlas_core.catalogos import cambiar_estado_chofer
    registro = cambiar_estado_chofer(ctx.archivos["choferes"], str(plan.datos["clave"]), bool(p["activo"]))
    return {"despues": {"activo": registro.get("activo")}, "reconciliar": True}


def _plan_chofer_alias(ctx: _Contexto, p: dict) -> Plan:
    from atlas_core.catalogos import _normalizar_nombre_entidad
    choferes = ctx.choferes()
    clave = _resolver_chofer(choferes, str(p["chofer"]))
    registro = choferes[clave]
    alias = str(p["alias"])
    buscado = _normalizar_nombre_entidad(alias)
    propio = {_normalizar_nombre_entidad(str(v)) for v in (registro.get("nombre", ""), *(registro.get("aliases") or []))}
    for otra, otro in choferes.items():
        if otra != clave and isinstance(otro, dict) and buscado in {
            _normalizar_nombre_entidad(str(v)) for v in (otro.get("nombre", ""), *(otro.get("aliases") or []))
        }:
            raise ErrorAccionOperacional("CONFLICTO", "el alias ya identifica a otro chofer")
    return Plan(
        entidad={"tipo": "CHOFER", "id": clave, "nombre": registro.get("nombre", "")},
        valor_actual={"aliases": list(registro.get("aliases") or [])},
        valor_propuesto={"alias_agregado": alias}, estado_base={"chofer": registro},
        sin_cambios=buscado in propio,
        afectados=_afectados_por_guias(ctx, _guias_de_chofer(ctx, clave, registro)),
        consecuencias=["El alias pasa a resolver a este chofer en guías futuras y en la bandeja."],
        revalidaciones=["RECONCILIAR_BANDEJA"], archivos=("choferes", "bandeja"), datos={"clave": clave},
    )


def _aplicar_chofer_alias(ctx: _Contexto, p: dict, plan: Plan, actor: str) -> dict:
    from atlas_core.catalogos import registrar_alias_seguro
    with bloqueo_sesion(ctx.catalogos, "choferes"):
        if not registrar_alias_seguro(ctx.archivos["choferes"], str(plan.datos["clave"]), str(p["alias"])):
            raise ErrorAccionOperacional("CONFLICTO", "el catálogo rechazó el alias")
    return {"despues": {"aliases": list(ctx.choferes()[str(plan.datos["clave"])].get("aliases") or [])},
            "reconciliar": True}


def _plan_chofer_vehiculo(ctx: _Contexto, p: dict) -> Plan:
    from atlas_core.catalogo_vehiculos import cargar_catalogo_vehiculos
    from atlas_core.catalogos import normalizar_rut, rut_canonico_de_registro_chofer
    from atlas_core.operaciones_conversacionales import _plan_impacto_focal
    choferes = ctx.choferes()
    clave = _resolver_chofer(choferes, str(p["chofer"]))
    registro = choferes[clave]
    if registro.get("activo", True) is not True:
        raise ErrorAccionOperacional("PRECONDICION_FALLIDA", "el chofer está inactivo")
    rut = rut_canonico_de_registro_chofer(clave, registro)
    if not rut:
        raise ErrorAccionOperacional("PRECONDICION_FALLIDA", "el chofer no tiene RUT canónico")
    rut_normalizado = normalizar_rut(rut)
    patente = str(p["patente"])
    try:
        catalogo = cargar_catalogo_vehiculos(ctx.archivos["vehiculos"])
    except Exception as error:  # noqa: BLE001 -- ausente/corrupto: no hay vehículo que asociar
        raise ErrorAccionOperacional("ESTADO_ILEGIBLE", "catálogo de vehículos no disponible") from error
    vehiculo = next((v for v in catalogo.vehiculos if v.patente_canonica == patente), None)
    if vehiculo is None or vehiculo.estado_calidad != "CONFIRMADO" or vehiculo.estado_vigencia != "ACTIVO":
        raise ErrorAccionOperacional(
            "PRECONDICION_FALLIDA", "la patente no existe como vehículo CONFIRMADO y ACTIVO; esta acción no crea vehículos",
        )
    tipo = {"TRACTO": "TRACTO", "CARRO": "RAMPLA"}.get(vehiculo.tipo)
    if tipo is None:
        raise ErrorAccionOperacional("PRECONDICION_FALLIDA", f"tipo de vehículo {vehiculo.tipo} no asociable")
    # Normalizado: asociaciones previas pudieron guardar el RUT con formato
    # ("18091588-5"); compararlas crudas duplicaría la misma relación.
    ruts_asociados = sorted({normalizar_rut(str(e.campos_observados.get("rut_chofer_asociado", "")))
                             for e in vehiculo.evidencias} - {""})
    impacto = _plan_impacto_focal(raiz=ctx.raiz, rut_chofer=rut_normalizado, tipo_humano=tipo,
                                  patente=patente, aplicar=False)
    return Plan(
        entidad={"tipo": "CHOFER_VEHICULO", "id": f"{clave}:{patente}", "chofer": registro.get("nombre", "")},
        valor_actual={"ruts_asociados_a_patente": ruts_asociados},
        valor_propuesto={"rut_chofer": rut_normalizado, "patente": patente, "tipo": tipo},
        estado_base={"chofer": registro, "vehiculo": vehiculo.vehiculo_id, "ruts": ruts_asociados},
        sin_cambios=rut_normalizado in ruts_asociados,
        afectados={"decisiones_vehiculo_retirables": impacto.get("decisiones_retiradas", 0),
                   "decisiones_revisadas": impacto.get("decisiones", [])},
        consecuencias=["Evidencia CONFIRMACION_HUMANA append-only en el vehículo; no modifica patentes documentales."],
        revalidaciones=["RETIRO_FOCAL_VEHICULO_DESCONOCIDO", "RECONCILIAR_BANDEJA"],
        archivos=("vehiculos", "bandeja"), datos={"rut": rut_normalizado, "tipo": tipo},
    )


def _aplicar_chofer_vehiculo(ctx: _Contexto, p: dict, plan: Plan, actor: str) -> dict:
    from atlas_core.catalogo_vehiculos import asociar_chofer_a_vehiculo_confirmado
    from atlas_core.operaciones_conversacionales import _plan_impacto_focal
    asociar_chofer_a_vehiculo_confirmado(
        ctx.archivos["vehiculos"], patente=str(p["patente"]), actor=actor,
        fuente_decision=f"ACCION_OPERACIONAL:{ctx.token}", fecha=ctx.reloj(),
        rut_chofer_asociado=str(plan.datos["rut"]), observaciones=str(p.get("referencia", "")),
    )
    impacto = _plan_impacto_focal(raiz=ctx.raiz, rut_chofer=str(plan.datos["rut"]),
                                  tipo_humano=str(plan.datos["tipo"]), patente=str(p["patente"]), aplicar=True)
    return {"despues": plan.valor_propuesto, "revalidacion_focal": impacto, "reconciliar": True}


# =============================================================== OBRAS / DESTINOS


def _evidencia_operador(ctx: _Contexto, actor: str, campos: Mapping[str, str]):
    from atlas_core.catalogo_obras_destinos import Evidencia, ResultadoEvidencia, TipoEvidencia
    return Evidencia(
        tipo=TipoEvidencia.CATALOGO.value, identificador_fuente=f"ACCION_OPERACIONAL:{ctx.token}",
        referencia_hash="", campos_observados={k: str(v) for k, v in campos.items()},
        fecha=ctx.reloj().astimezone(timezone.utc).isoformat(), actor_proceso=actor,
        resultado=ResultadoEvidencia.SOPORTA.value,
    )


def _guias_por_obra(ctx: _Contexto, claves: set[str]) -> set[str]:
    from atlas_core.catalogo_obras_destinos import normalizar_nombre_obra
    return {str(f.get("numero_guia", "")).strip() for f in ctx.filas()
            if normalizar_nombre_obra(str(f.get("obra_destino", ""))) in claves}


def _obra(ctx: _Contexto, obra_id: str):
    obra = next((o for o in ctx.catalogo_obras().listar_obras() if o.obra_id == obra_id), None)
    if obra is None:
        raise ErrorAccionOperacional("ENTIDAD_NO_ENCONTRADA", "obra inexistente")
    return obra


def _consultar_obras(ctx: _Contexto, p: dict) -> object:
    from atlas_core.catalogo_obras_destinos import normalizar_nombre_obra
    catalogo = ctx.catalogo_obras()
    clave = normalizar_nombre_obra(str(p.get("nombre", "")))
    relaciones = catalogo.listar_relaciones()
    obras = [o for o in catalogo.listar_obras()
             if not clave or clave in {normalizar_nombre_obra(x) for x in (o.nombre_canonico, *o.aliases_documentales)}]
    return {"obras": [
        {"obra_id": o.obra_id, "nombre": o.nombre_canonico, "aliases": list(o.aliases_documentales),
         "estado": o.estado, "vigencia": o.estado_vigencia,
         "relaciones": [{"destino_id": r.destino_id, "estado": r.estado} for r in relaciones if r.obra_id == o.obra_id]}
        for o in obras[:200]], "total": len(obras)}


def _plan_obra_registrar(ctx: _Contexto, p: dict) -> Plan:
    from atlas_core.catalogo_clientes import CatalogoClientes
    from atlas_core.catalogo_obras_destinos import normalizar_nombre_obra
    try:
        cliente = CatalogoClientes(ctx.archivos["clientes"]).obtener(str(p["cliente_id"]))
    except Exception as error:  # noqa: BLE001
        raise ErrorAccionOperacional("ENTIDAD_NO_ENCONTRADA", "cliente inexistente") from error
    if cliente.estado_vigencia != "ACTIVO":
        raise ErrorAccionOperacional("PRECONDICION_FALLIDA", "cliente inactivo")
    nombre = str(p["nombre_obra"])
    clave = normalizar_nombre_obra(nombre)
    if not clave:
        raise ErrorAccionOperacional("PARAMETRO_INVALIDO", "nombre_obra sin contenido normalizable")
    compatibles = [o for o in ctx.catalogo_obras().listar_obras() if o.estado_vigencia == "ACTIVO"
                   and clave in {normalizar_nombre_obra(x) for x in (o.nombre_canonico, *o.aliases_documentales)}]
    if len(compatibles) > 1:
        raise ErrorAccionOperacional("ENTIDAD_AMBIGUA", "el nombre coincide con más de una obra activa")
    existente = compatibles[0] if compatibles else None
    return Plan(
        entidad={"tipo": "OBRA", "id": existente.obra_id if existente else "", "nombre": nombre},
        valor_actual=({"obra_id": existente.obra_id, "estado": existente.estado} if existente else None),
        valor_propuesto={"nombre_obra": nombre, "cliente": cliente.razon_social, "estado": "OBSERVADA"},
        estado_base={"coincidentes": [o.a_dict() for o in compatibles]},
        sin_cambios=existente is not None,
        afectados=_afectados_por_guias(ctx, _guias_por_obra(ctx, {clave})),
        consecuencias=["Registra la obra como identidad global OBSERVADA (no confirma destino)."],
        revalidaciones=["REVALIDACION_REACTIVA_OBRA", "RECONCILIAR_BANDEJA"],
        archivos=("obras_destinos", "bandeja"), datos={"cliente_id": cliente.cliente_id},
    )


def _aplicar_obra_registrar(ctx: _Contexto, p: dict, plan: Plan, actor: str) -> dict:
    from atlas_core.revalidacion_reactiva_tecnica import revalidar_tras_cambio_catalogo
    resultado = ctx.catalogo_obras().registrar_observacion(
        cliente_id=str(plan.datos["cliente_id"]), nombre_obra=str(p["nombre_obra"]),
        alias_documental=str(p.get("alias_documental", "")),
        evidencia=_evidencia_operador(ctx, actor, {"nombre_obra": str(p["nombre_obra"]),
                                                   "referencia": str(p.get("referencia", ""))}),
    )
    reactiva = revalidar_tras_cambio_catalogo(ctx.archivos["obras_destinos"], obra_id=resultado.obra.obra_id)
    return {"despues": {"obra_id": resultado.obra.obra_id, "estado": resultado.obra.estado},
            "revalidacion_focal": reactiva, "reconciliar": True}


def _plan_obra_corregir(ctx: _Contexto, p: dict) -> Plan:
    from atlas_core.catalogo_obras_destinos import normalizar_nombre_obra
    obra = _obra(ctx, str(p["obra_id"]))
    if obra.estado_vigencia != "ACTIVO":
        raise ErrorAccionOperacional("PRECONDICION_FALLIDA", "obra inactiva")
    nombre = str(p["nombre_canonico"])
    aliases = list(p.get("aliases") or [])
    claves_actuales = {normalizar_nombre_obra(x) for x in (obra.nombre_canonico, *obra.aliases_documentales)}
    propuestas = {normalizar_nombre_obra(x) for x in (nombre, *aliases)}
    for otra in ctx.catalogo_obras().listar_obras():
        if otra.obra_id != obra.obra_id and otra.estado_vigencia == "ACTIVO" and propuestas & {
            normalizar_nombre_obra(x) for x in (otra.nombre_canonico, *otra.aliases_documentales)
        }:
            raise ErrorAccionOperacional("CONFLICTO", "la identidad propuesta colisiona con otra obra activa")
    sin_cambios = nombre == obra.nombre_canonico and propuestas <= claves_actuales
    return Plan(
        entidad={"tipo": "OBRA", "id": obra.obra_id, "nombre": obra.nombre_canonico},
        valor_actual={"nombre_canonico": obra.nombre_canonico, "aliases": list(obra.aliases_documentales)},
        valor_propuesto={"nombre_canonico": nombre, "aliases_agregados": aliases},
        estado_base={"obra": obra.a_dict()}, sin_cambios=sin_cambios,
        afectados=_afectados_por_guias(ctx, _guias_por_obra(ctx, claves_actuales | propuestas)),
        consecuencias=["Cambia el nombre canónico; el nombre anterior queda como alias si se incluye en aliases "
                       "o si el nuevo canónico era un alias de esta obra (ese alias deja de serlo).",
                       "No altera estado, relaciones ni cliente de la obra."],
        revalidaciones=["REVALIDACION_REACTIVA_OBRA", "RECONCILIAR_BANDEJA"],
        archivos=("obras_destinos", "bandeja"),
    )


def _aplicar_obra_corregir(ctx: _Contexto, p: dict, plan: Plan, actor: str) -> dict:
    from atlas_core.revalidacion_reactiva_tecnica import revalidar_tras_cambio_catalogo
    obra = ctx.catalogo_obras().actualizar_identidad_obra(
        str(p["obra_id"]), nombre_canonico=str(p["nombre_canonico"]), aliases_documentales=list(p.get("aliases") or []),
        evidencia=_evidencia_operador(ctx, actor, {"nombre_canonico": str(p["nombre_canonico"]),
                                                   "referencia": str(p.get("referencia", ""))}),
    )
    reactiva = revalidar_tras_cambio_catalogo(ctx.archivos["obras_destinos"], obra_id=obra.obra_id)
    return {"despues": {"nombre_canonico": obra.nombre_canonico, "aliases": list(obra.aliases_documentales)},
            "revalidacion_focal": reactiva, "reconciliar": True}


def _plan_destino_registrar(ctx: _Contexto, p: dict) -> Plan:
    from atlas_core.catalogo_destinos import EstadoBusquedaDestino
    if ("latitud" in p) != ("longitud" in p):
        raise ErrorAccionOperacional("PARAMETRO_INVALIDO", "latitud y longitud van juntas")
    resuelto = ctx.catalogo_destinos().resolver_direccion_global(
        str(p["direccion"]), comuna=str(p.get("comuna", "")), region=str(p.get("region", "")))
    if resuelto.estado == EstadoBusquedaDestino.AMBIGUA:
        raise ErrorAccionOperacional("ENTIDAD_AMBIGUA", "la dirección coincide con más de un destino activo")
    existente = resuelto.destino
    sin_cambios = existente is not None and existente.estado_calidad == "CONFIRMADO" and (
        "latitud" not in p or existente.latitud is not None)
    return Plan(
        entidad={"tipo": "DESTINO", "id": existente.destino_id if existente else "", "direccion": p["direccion"]},
        valor_actual=(existente.a_dict() if existente else None),
        valor_propuesto={k: p[k] for k in ("direccion", "comuna", "region", "latitud", "longitud") if k in p}
        | {"estado_calidad": "CONFIRMADO"},
        estado_base={"destino": existente.a_dict() if existente else None}, sin_cambios=sin_cambios,
        consecuencias=[("Promueve el destino existente a CONFIRMADO (nunca degrada ni sobrescribe coordenadas)."
                        if existente else "Crea un destino global CONFIRMADO por el operador.")],
        revalidaciones=["REVALIDACION_REACTIVA_DESTINO", "RECONCILIAR_BANDEJA"],
        archivos=("destinos_maestros", "bandeja"),
    )


def _aplicar_destino_registrar(ctx: _Contexto, p: dict, plan: Plan, actor: str) -> dict:
    from atlas_core.catalogo_destinos import EstadoCalidadDestino
    from atlas_core.revalidacion_reactiva_tecnica import revalidar_tras_cambio_catalogo
    destino = ctx.catalogo_destinos().crear_o_reutilizar_global(
        nombre_destino=str(p.get("nombre_destino") or p["direccion"]), direccion=str(p["direccion"]),
        comuna=str(p.get("comuna", "")), region=str(p.get("region", "")),
        fuente=f"ACCION_OPERACIONAL:{actor}", latitud=p.get("latitud"), longitud=p.get("longitud"),
        estado_calidad=EstadoCalidadDestino.CONFIRMADO,
    )
    reactiva = revalidar_tras_cambio_catalogo(ctx.archivos["destinos_maestros"], destino=destino)
    return {"despues": {"destino_id": destino.destino_id, "estado_calidad": destino.estado_calidad},
            "revalidacion_focal": reactiva, "reconciliar": True}


# Chile continental + insular cercano: una coordenada fuera (p. ej. signos
# invertidos) nunca es un punto de entrega de esta operación.
_LATITUD_CHILE, _LONGITUD_CHILE = (-56.0, -17.0), (-76.0, -66.0)


def _plan_destino_coordenada(ctx: _Contexto, p: dict) -> Plan:
    """Coordenada canónica confirmada por humano para un destino EXISTENTE.
    Deja el destino CONFIRMADO con fuente COORDENADA_CANONICA_CONFIRMADA:
    desde ahí `_destino_con_coordenada_canonica_para` la reutiliza para todo
    DESPACHAR A que coincida exactamente con su dirección o alias."""
    from atlas_core.catalogo_destinos import ErrorCatalogoDestinos
    from atlas_core.rutas.destino_entrega import (
        FUENTE_COORDENADA_CANONICA_CONFIRMADA, plan_impacto_coordenada_canonica,
    )
    latitud, longitud = float(p["latitud"]), float(p["longitud"])
    if not (_LATITUD_CHILE[0] <= latitud <= _LATITUD_CHILE[1] and _LONGITUD_CHILE[0] <= longitud <= _LONGITUD_CHILE[1]):
        raise ErrorAccionOperacional("PARAMETRO_INVALIDO", "la coordenada no está en Chile (revise signos y orden)")
    try:
        destino = ctx.catalogo_destinos().obtener(str(p["destino_id"]))
    except ErrorCatalogoDestinos as error:
        raise ErrorAccionOperacional("ENTIDAD_NO_ENCONTRADA", "destino inexistente") from error
    if destino.estado_vigencia != "ACTIVO":
        raise ErrorAccionOperacional("PRECONDICION_FALLIDA", "el destino no está activo")
    if not str(destino.direccion or "").strip():
        raise ErrorAccionOperacional("PRECONDICION_FALLIDA", "el destino no tiene dirección con qué coincidir")
    guias = list(plan_impacto_coordenada_canonica(destino=destino, filas=ctx.filas()).guias)
    sin_cambios = (destino.estado_calidad == "CONFIRMADO" and destino.fuente == FUENTE_COORDENADA_CANONICA_CONFIRMADA
                   and destino.latitud == latitud and destino.longitud == longitud)
    consecuencias = [
        f"Toda guía cuyo DESPACHAR A sea exactamente {destino.direccion!r} (o un alias del destino) "
        "se ruteará a este punto, sin geocodificar.",
        f"Se recalcula ahora la ruta de {len(guias)} guía(s)" + (f": {', '.join(guias)}." if guias else "."),
    ]
    if destino.latitud is not None and not sin_cambios:
        consecuencias.insert(0, f"Reemplaza la coordenada actual ({destino.latitud}, {destino.longitud}).")
    if destino.estado_calidad != "CONFIRMADO":
        consecuencias.append(f"El destino pasa de {destino.estado_calidad} a CONFIRMADO.")
    return Plan(
        entidad={"tipo": "DESTINO", "id": destino.destino_id, "direccion": destino.direccion},
        valor_actual={"latitud": destino.latitud, "longitud": destino.longitud,
                      "estado_calidad": destino.estado_calidad, "fuente": destino.fuente},
        valor_propuesto={"latitud": latitud, "longitud": longitud, "estado_calidad": "CONFIRMADO",
                         "fuente": FUENTE_COORDENADA_CANONICA_CONFIRMADA},
        estado_base={"destino": destino.a_dict(), "guias": guias}, sin_cambios=sin_cambios,
        afectados=_afectados_por_guias(ctx, set(guias)), consecuencias=consecuencias,
        revalidaciones=["MANTENIMIENTO_FOCAL_GUIAS", "RECONCILIAR_BANDEJA", "REGENERAR_REPORTE_VIAJES"],
        archivos=("destinos_maestros", "bandeja"), datos={"guias": guias},
    )


def _aplicar_destino_coordenada(ctx: _Contexto, p: dict, plan: Plan, actor: str) -> dict:
    from atlas_core.catalogo_destinos import EstadoCalidadDestino
    catalogo = ctx.catalogo_destinos()
    destino_id = str(p["destino_id"])
    # Con el lock de decisión tomado, la revalidación reactiva del catálogo
    # se aparta (DECISION_EN_CURSO): la revalidación focal la hace esta
    # acción UNA vez, con el destino ya completo (CONFIRMADO + coordenada).
    with bloqueo_sesion(ctx.actual, "aplicar_decision_obra"):
        if plan.valor_actual["estado_calidad"] != EstadoCalidadDestino.CONFIRMADO.value:
            catalogo.editar(destino_id, estado_calidad=EstadoCalidadDestino.CONFIRMADO.value,
                            modificacion_manual=True)
        destino = catalogo.confirmar_coordenada_canonica(
            destino_id, latitud=float(p["latitud"]), longitud=float(p["longitud"]),
            actor=f"{actor}/{ctx.confirmado_por}",
            referencia=f"ACCION_OPERACIONAL:{ctx.token}" + (f" {p['referencia']}" if p.get("referencia") else ""),
        )
    return {"despues": {"latitud": destino.latitud, "longitud": destino.longitud,
                        "estado_calidad": destino.estado_calidad, "fuente": destino.fuente},
            "reconciliar": True, "guias_revalidar": list(plan.datos["guias"]), "regenerar_reporte": True,
            "servicio": "CatalogoDestinos.confirmar_coordenada_canonica"}


MOTIVO_COORDENADA_NO_CONFIRMADA = "COORDENADA_NO_CONFIRMADA"


def _filas_de_guias_para_destino(ctx: _Contexto, destino, guias: list[str]) -> list[dict[str, str]]:
    """Exactamente una fila por guía, y su DESPACHAR A debe ser la dirección
    del destino; si no, ninguna (nunca se elige entre varias filas)."""
    from atlas_core.revalidacion_documental import _direcciones_documentales_compatibles
    filas = ctx.filas()
    elegidas = []
    for guia in guias:
        candidatas = [f for f in filas if str(f.get("numero_guia", "")) == guia
                      and _direcciones_documentales_compatibles(destino.direccion, f.get("despachar_a_crudo", ""))]
        if len(candidatas) != 1:
            raise ErrorAccionOperacional(
                "PRECONDICION_FALLIDA",
                f"la guía {guia} no tiene exactamente un documento con la dirección {destino.direccion!r}")
        elegidas.append(candidatas[0])
    return elegidas


def _plan_destino_retirar_coordenada(ctx: _Contexto, p: dict) -> Plan:
    """Retira una coordenada NO verificada de un destino CONFIRMADO (identidad
    humana intacta) y deja pendiente la ruta de sus guías: nunca asigna otra
    coordenada ni recalcula a un punto aproximado."""
    from atlas_core.catalogo_destinos import ErrorCatalogoDestinos
    try:
        destino = ctx.catalogo_destinos().obtener(str(p["destino_id"]))
    except ErrorCatalogoDestinos as error:
        raise ErrorAccionOperacional("ENTIDAD_NO_ENCONTRADA", "destino inexistente") from error
    if destino.estado_vigencia != "ACTIVO" or destino.estado_calidad != "CONFIRMADO":
        raise ErrorAccionOperacional("PRECONDICION_FALLIDA", "el destino no está CONFIRMADO y activo")
    guias = [str(g) for g in p["guias"]]
    filas = _filas_de_guias_para_destino(ctx, destino, guias)
    comuna = str(p.get("comuna") or "").strip().upper()
    sin_cambios = (destino.latitud is None and destino.longitud is None
                   and (not comuna or destino.comuna == comuna)
                   and all(f.get("estado_ruta") != "RUTA_CALCULADA" for f in filas))
    return Plan(
        entidad={"tipo": "DESTINO", "id": destino.destino_id, "direccion": destino.direccion, "guias": guias},
        valor_actual={"latitud": destino.latitud, "longitud": destino.longitud, "comuna": destino.comuna,
                      "rutas": {f["numero_guia"]: [f.get("estado_ruta"), f.get("distancia_km")] for f in filas}},
        valor_propuesto={"latitud": None, "longitud": None, "comuna": comuna or destino.comuna,
                         "rutas": {f["numero_guia"]: ["REQUIERE_REVISION", MOTIVO_COORDENADA_NO_CONFIRMADA]
                                   for f in filas}},
        estado_base={"destino": destino.a_dict(), "filas": filas}, sin_cambios=sin_cambios,
        afectados=_afectados_por_guias(ctx, set(guias)),
        consecuencias=[
            "Se retira la coordenada no verificada del destino; su identidad (dirección confirmada) no cambia.",
            "No se asigna ninguna coordenada nueva: la ruta de las guías queda pendiente hasta una ubicación válida.",
            "No se reabre la revisión de destino: la dirección ya está confirmada.",
        ],
        revalidaciones=["MANTENIMIENTO_FOCAL_GUIAS", "RECONCILIAR_BANDEJA", "REGENERAR_REPORTE_VIAJES"],
        archivos=("destinos_maestros", "dataset", "bandeja"),
        datos={"guias": guias, "archivos": [f["archivo"] for f in filas], "comuna": comuna},
    )


def _aplicar_destino_retirar_coordenada(ctx: _Contexto, p: dict, plan: Plan, actor: str) -> dict:
    from atlas_core.revalidacion_documental import invalidar_derivados_ruta
    destino_id = str(p["destino_id"])
    nota = (f"COORDENADA_RETIRADA_NO_VERIFICADA ({plan.valor_actual['latitud']}, {plan.valor_actual['longitud']}) "
            f"ACCION_OPERACIONAL:{ctx.token} {actor}/{ctx.confirmado_por}"
            + (f" {p['referencia']}" if p.get("referencia") else ""))[:500]
    with bloqueo_sesion(ctx.actual, "aplicar_decision_obra"):
        catalogo = ctx.catalogo_destinos()
        previa = str(catalogo.obtener(destino_id).observacion or "").strip()
        destino = catalogo.editar(
            destino_id, modificacion_manual=True, limpiar_coordenadas=True,
            comuna=plan.datos["comuna"] or None, observacion=(f"{previa} | {nota}" if previa else nota),
        )
        with bloqueo_sesion(ctx.actual, "revalidacion_dataset"):
            from atlas_core.revalidacion_documental import _escribir_filas_completas, _leer_filas
            filas = _leer_filas(ctx.archivos["dataset"])
            archivos = set(plan.datos["archivos"])
            for fila in filas:
                if fila.get("archivo") in archivos:
                    fila.update(invalidar_derivados_ruta())
                    fila["estado_ruta"] = "REQUIERE_REVISION"
                    fila["motivo_ruta"] = MOTIVO_COORDENADA_NO_CONFIRMADA
                    fila["direccion_entrega"] = ""
                    fila["localidad_entrega"] = destino.comuna
            _escribir_filas_completas(ctx.archivos["dataset"], filas)
    return {"despues": {"latitud": destino.latitud, "longitud": destino.longitud, "comuna": destino.comuna,
                        "guias_pendientes": list(plan.datos["guias"])},
            "reconciliar": True, "guias_revalidar": list(plan.datos["guias"]), "regenerar_reporte": True,
            "servicio": "CatalogoDestinos.editar(limpiar_coordenadas=True)"}


def _plan_obra_destino(ctx: _Contexto, p: dict) -> Plan:
    from atlas_core.catalogo_obras_destinos import normalizar_nombre_obra
    obra = _obra(ctx, str(p["obra_id"]))
    if obra.estado_vigencia != "ACTIVO" or obra.estado in {"RECHAZADA", "INACTIVA"}:
        raise ErrorAccionOperacional("PRECONDICION_FALLIDA", "una obra rechazada o inactiva no puede vincularse")
    try:
        destino = ctx.catalogo_destinos().obtener(str(p["destino_id"]))
    except Exception as error:  # noqa: BLE001
        raise ErrorAccionOperacional("ENTIDAD_NO_ENCONTRADA", "destino inexistente") from error
    if destino.estado_vigencia != "ACTIVO":
        raise ErrorAccionOperacional("PRECONDICION_FALLIDA", "destino inactivo")
    relaciones = [r for r in ctx.catalogo_obras().listar_relaciones() if r.obra_id == obra.obra_id]
    propia = [r for r in relaciones if r.destino_id == destino.destino_id]
    terminal = [r for r in propia if r.estado in {"RECHAZADA", "INACTIVA"}]
    if terminal and not any(r.estado in {"PENDIENTE", "CONFIRMADA"} for r in propia):
        raise ErrorAccionOperacional(
            "PRECONDICION_FALLIDA", "la relación fue rechazada/inactivada antes; esta acción no la reactiva",
        )
    otras_confirmadas = [r.destino_id for r in relaciones if r.estado == "CONFIRMADA" and r.destino_id != destino.destino_id]
    consecuencias = ["Relación obra↔destino CONFIRMADA por humano: las guías de esta obra podrán rutear a ese destino."]
    if otras_confirmadas:
        consecuencias.append(
            f"La obra ya tiene {len(otras_confirmadas)} otro(s) destino(s) confirmado(s): la resolución única se abstendrá.")
    claves = {normalizar_nombre_obra(x) for x in (obra.nombre_canonico, *obra.aliases_documentales)}
    return Plan(
        entidad={"tipo": "RELACION_OBRA_DESTINO", "id": f"{obra.obra_id}:{destino.destino_id}",
                 "obra": obra.nombre_canonico, "destino": destino.direccion or destino.nombre_destino},
        valor_actual={"relaciones": [{"destino_id": r.destino_id, "estado": r.estado} for r in relaciones]},
        valor_propuesto={"destino_id": destino.destino_id, "estado": "CONFIRMADA"},
        estado_base={"obra": obra.a_dict(), "relaciones": [r.a_dict() for r in relaciones],
                     "destino_vigencia": destino.estado_vigencia},
        sin_cambios=any(r.estado == "CONFIRMADA" for r in propia),
        afectados=_afectados_por_guias(ctx, _guias_por_obra(ctx, claves)), consecuencias=consecuencias,
        revalidaciones=["REVALIDACION_REACTIVA_OBRA", "RECONCILIAR_BANDEJA"],
        archivos=("obras_destinos", "bandeja"),
        datos={"pendiente": next((r.relacion_id for r in propia if r.estado == "PENDIENTE"), ""),
               "cliente_id": obra.cliente_id},
    )


def _aplicar_obra_destino(ctx: _Contexto, p: dict, plan: Plan, actor: str) -> dict:
    catalogo = ctx.catalogo_obras()
    relacion_id = str(plan.datos.get("pendiente") or "")
    if not relacion_id:
        observacion = catalogo.registrar_observacion(
            cliente_id=str(p.get("cliente_id") or plan.datos.get("cliente_id") or ""),
            nombre_obra=_obra(ctx, str(p["obra_id"])).nombre_canonico, destino_id=str(p["destino_id"]),
            evidencia=_evidencia_operador(ctx, actor, {"destino_id": str(p["destino_id"]),
                                                       "referencia": str(p.get("referencia", ""))}),
        )
        if observacion.relacion is None or observacion.obra.obra_id != str(p["obra_id"]):
            raise ErrorAccionOperacional("PRECONDICION_FALLIDA", "el catálogo no pudo crear la relación")
        relacion_id = observacion.relacion.relacion_id
    # `confirmar_relacion` ya dispara la revalidación reactiva focal.
    relacion = catalogo.confirmar_relacion(
        relacion_id, actor=actor, fuente_confirmacion="ACCION_OPERACIONAL",
        observaciones=str(p.get("observaciones", "")), identificador_fuente=f"ACCION_OPERACIONAL:{ctx.token}",
    )
    return {"despues": {"relacion_id": relacion.relacion_id, "estado": relacion.estado}, "reconciliar": True}


# =============================================================== DOCUMENTO


def _campos_documentales() -> tuple[str, ...]:
    from atlas_core.reprocesamiento_reparador import CAMPOS_FOCALES_CONOCIDOS
    return tuple(sorted(CAMPOS_FOCALES_CONOCIDOS))


def _fila_documento(ctx: _Contexto, guia: str, archivo: str) -> dict[str, str]:
    filas = [f for f in ctx.filas() if str(f.get("numero_guia", "")).strip() == guia
             and (not archivo or str(f.get("archivo", "")) == archivo)]
    if not filas:
        raise ErrorAccionOperacional("ENTIDAD_NO_ENCONTRADA", "documento inexistente en el dataset")
    if len(filas) > 1:
        raise ErrorAccionOperacional("ENTIDAD_AMBIGUA", "la guía tiene varios documentos; indique 'archivo'")
    return filas[0]


def _decision_obsoleta_por_campo(decision: Mapping[str, object], archivo: str, campo: str, valor: str,
                                 transporte_anterior: str = "") -> bool:
    documento = decision.get("documento") or {}
    if str(documento.get("archivo", "")) != archivo:
        return False
    if str(decision.get("campo", "")) == campo and str(decision.get("valor_documental", "")).strip() != valor:
        return True
    # Corrección de transporte: una tarjeta del mismo archivo que sigue
    # identificando el documento por el transporte anterior depende de él
    # (la independencia de evidencia se cuenta por transporte).
    return bool(transporte_anterior) and str(documento.get("numero_transporte", "")).strip() == transporte_anterior


def _transporte(fila: Mapping[str, str]) -> str:
    return str(fila.get("numero_transporte", "")).strip()


def _precondiciones_cambio_transporte(ctx: _Contexto, fila: Mapping[str, str], nuevo: str) -> dict[str, object]:
    """Bloqueos de `numero_transporte` que el reparador no puede ver
    (eventos y agrupaciones viven fuera del dataset) y las filas de los dos
    viajes involucrados, que el preview muestra."""
    from atlas_core.agrupacion_viajes import agrupaciones_activas
    anterior = _transporte(fila)
    # Misma protección para ambos extremos: sacar la guía de un viaje con
    # eventos/agrupación o meterla en uno los alteraría en silencio.
    for transporte in (t for t in (anterior, nuevo) if t):
        eventos = [e for e in _leer_json(ctx.actual / "eventos_operacionales.json", {}).get("eventos") or []
                   if isinstance(e, dict) and e.get("estado", "ACTIVO") == "ACTIVO"
                   and str(e.get("numero_transporte", "")).strip() == transporte]
        if eventos:
            raise ErrorAccionOperacional(
                "PRECONDICION_FALLIDA",
                f"el transporte {transporte} tiene {len(eventos)} evento(s) operacional(es) activo(s); "
                "resuélvalos primero",
            )
        agrupaciones = [a for a in agrupaciones_activas(ctx.actual)
                        if transporte in {str(t).strip() for t in a.get("transportes") or []}]
        if agrupaciones:
            raise ErrorAccionOperacional(
                "PRECONDICION_FALLIDA",
                f"el transporte {transporte} participa en una agrupación de viaje activa "
                f"({agrupaciones[0].get('agrupacion_id', '')}); desagrúpelo primero",
            )
    filas = ctx.filas()
    archivo = str(fila.get("archivo", ""))
    origen = [f for f in filas if anterior and _transporte(f) == anterior and str(f.get("archivo", "")) != archivo]
    destino = [f for f in filas if _transporte(f) == nuevo and str(f.get("archivo", "")) != archivo]
    return {"origen": origen, "destino": destino}


def _plan_documento_campo(ctx: _Contexto, p: dict) -> Plan:
    from atlas_core.investigacion_documental import archivos_en_investigacion
    from atlas_core.reprocesamiento_reparador import reparar_documento_focal_con_valores_conocidos
    fila = _fila_documento(ctx, str(p["numero_guia"]), str(p.get("archivo", "")))
    archivo = str(fila.get("archivo", ""))
    if archivo in archivos_en_investigacion(ctx.raiz):
        raise ErrorAccionOperacional("PRECONDICION_FALLIDA", "el documento está en investigación (cuarentena)")
    campo, valor = str(p["campo"]).lower(), str(p["valor"])
    actual = str(fila.get(campo, "")).strip()
    if actual == valor:
        sin_cambios = True
    else:
        # El propio reparador focal valida el valor y el guardián del ledger
        # (dry-run: nunca escribe).
        try:
            simulacion = reparar_documento_focal_con_valores_conocidos(
                raiz_atlas=ctx.raiz, archivo=archivo, valores={campo: valor}, dry_run=True,
                reconciliar=False, tipos_ledger_superables=frozenset({TIPO_LEDGER_CORRECCION}),
                superar_resoluciones_automaticas=True,
                numero_guia=str(fila.get("numero_guia", "")),
            )
        except ValueError as error:
            # La fila del documento no es única o no es de la guía: nunca se elige otra.
            raise ErrorAccionOperacional("PRECONDICION_FALLIDA", str(error)) from error
        if simulacion["campos_bloqueados_por_ledger"]:
            raise ErrorAccionOperacional(
                "CAMPO_FIJADO_POR_DECISION_HUMANA",
                "una decisión de Revisión ya fijó este campo; corríjalo desde esa decisión",
            )
        if simulacion.get("duplicados_guia_transporte"):
            raise ErrorAccionOperacional(
                "PRECONDICION_FALLIDA",
                f"ya existe la guía {fila.get('numero_guia', '')} con transporte {valor} "
                f"({', '.join(simulacion['duplicados_guia_transporte'])})",
            )
        if not simulacion["cambios"]:
            raise ErrorAccionOperacional("PARAMETRO_INVALIDO", f"valor no válido para {campo}")
        sin_cambios = False
    if campo == "numero_transporte":
        return _plan_documento_transporte(ctx, p, fila, sin_cambios=sin_cambios)
    obsoletas = [d for d in ctx.decisiones() if _decision_obsoleta_por_campo(d, archivo, campo, valor)]
    return Plan(
        entidad={"tipo": "DOCUMENTO", "id": archivo, "numero_guia": fila.get("numero_guia", ""),
                 "numero_transporte": fila.get("numero_transporte", ""), "campo": campo},
        valor_actual={campo: actual}, valor_propuesto={campo: valor},
        estado_base={"fila": fila}, sin_cambios=sin_cambios,
        afectados={"guias": [fila.get("numero_guia", "")], "numero_transporte": fila.get("numero_transporte", ""),
                   "decisiones_obsoletas": [{"decision_id": d.get("decision_id"), "tipo": d.get("tipo"),
                                             "valor_documental": d.get("valor_documental")} for d in obsoletas]},
        consecuencias=["El valor queda protegido en el ledger: un reproceso/OCR no lo revierte.",
                       "Se retiran las decisiones que preguntaban por el valor anterior y se recalcula la bandeja."],
        revalidaciones=["RETIRO_DECISIONES_OBSOLETAS", "RECONCILIAR_BANDEJA", "MANTENIMIENTO_FOCAL_GUIA",
                        "REGENERAR_REPORTE_VIAJES"],
        archivos=("dataset", "bandeja", "ledger_decisiones"),
        datos={"archivo": archivo, "guia": str(fila.get("numero_guia", "")),
               "transporte": str(fila.get("numero_transporte", ""))},
    )


def _plan_documento_transporte(ctx: _Contexto, p: dict, fila: dict[str, str], *, sin_cambios: bool) -> Plan:
    archivo, guia = str(fila.get("archivo", "")), str(fila.get("numero_guia", ""))
    anterior, nuevo = _transporte(fila), str(p["valor"])
    viajes = ({"origen": [], "destino": []} if sin_cambios
              else _precondiciones_cambio_transporte(ctx, fila, nuevo))
    guias_origen = sorted({str(f.get("numero_guia", "")) for f in viajes["origen"]} - {""})
    guias_destino = sorted({str(f.get("numero_guia", "")) for f in viajes["destino"]} - {""})
    obsoletas = [] if sin_cambios else [
        d for d in ctx.decisiones()
        if _decision_obsoleta_por_campo(d, archivo, "numero_transporte", nuevo, anterior)
    ]
    return Plan(
        entidad={"tipo": "DOCUMENTO", "id": archivo, "numero_guia": guia, "numero_transporte": anterior,
                 "campo": "numero_transporte"},
        valor_actual={"numero_transporte": anterior}, valor_propuesto={"numero_transporte": nuevo},
        # Filas de ambos viajes: si otra guía entra o sale de cualquiera de
        # los dos entre el preview y la confirmación, el preview queda obsoleto.
        estado_base={"fila": fila, "viaje_origen": viajes["origen"], "viaje_destino": viajes["destino"]},
        sin_cambios=sin_cambios,
        afectados={
            "guias": [guia], "archivo": archivo, "numero_transporte": anterior,
            "transporte_anterior": anterior, "transporte_nuevo": nuevo,
            "viaje_origen": {"numero_transporte": anterior, "guias_restantes": guias_origen},
            "viaje_destino": {"numero_transporte": nuevo, "guias_existentes": guias_destino,
                              "guias_resultantes": sorted({*guias_destino, guia})},
            "guias_revalidar": sorted({guia, *guias_destino}),
            "decisiones_obsoletas": [{"decision_id": d.get("decision_id"), "tipo": d.get("tipo"),
                                      "valor_documental": d.get("valor_documental")} for d in obsoletas],
        },
        consecuencias=[
            f"La guía {guia} ({archivo}) pasa del transporte {anterior or '(vacío)'} al {nuevo}; "
            "ningún otro campo del documento cambia.",
            (f"El viaje {anterior} queda con {len(guias_origen)} guía(s)" if anterior else "Sin viaje de origen")
            + f"; el viaje {nuevo} queda con {len(guias_destino) + 1} guía(s).",
            "El valor queda protegido en el ledger: un reproceso/OCR no lo revierte.",
            "Se retiran las tarjetas del documento que dependen del transporte anterior y se recalcula la bandeja.",
        ],
        revalidaciones=["RETIRO_DECISIONES_OBSOLETAS", "RECONCILIAR_BANDEJA", "MANTENIMIENTO_FOCAL_GUIAS",
                        "REGENERAR_REPORTE_VIAJES"],
        archivos=("dataset", "bandeja", "ledger_decisiones"),
        datos={"archivo": archivo, "guia": guia, "transporte": anterior, "guias_destino": guias_destino},
    )


def _aplicar_documento_campo(ctx: _Contexto, p: dict, plan: Plan, actor: str) -> dict:
    from atlas_core.reprocesamiento_reparador import reparar_documento_focal_con_valores_conocidos
    campo, valor, archivo = str(p["campo"]).lower(), str(p["valor"]), str(plan.datos["archivo"])
    resultado = reparar_documento_focal_con_valores_conocidos(
        raiz_atlas=ctx.raiz, archivo=archivo, valores={campo: valor}, dry_run=False,
        reconciliar=False, tipos_ledger_superables=frozenset({TIPO_LEDGER_CORRECCION}),
                superar_resoluciones_automaticas=True,
        numero_guia=str(plan.datos["guia"]),
    )
    if not resultado["cambios"]:
        raise ErrorAccionOperacional("PRECONDICION_FALLIDA", "el reparador no aplicó el cambio")
    if (str(resultado.get("archivo")) != archivo
            or str(resultado.get("numero_guia")) != str(plan.datos["guia"])):
        # Defensa: el documento modificado debe ser exactamente el del plan.
        raise ErrorAccionOperacional("PRECONDICION_FALLIDA", "el documento modificado no es el del preview")
    antes = str(resultado["cambios"][0]["antes"])
    with bloqueo_sesion(ctx.actual, "aplicar_decision_obra"):
        ledger = _leer_json(ctx.archivos["ledger_decisiones"], {"schema_version": 1, "aplicaciones": []})
        ledger.setdefault("aplicaciones", []).append({
            "decision_id": f"ACCION_OPERACIONAL:{ctx.token}", "tipo": TIPO_LEDGER_CORRECCION,
            "accion": "CORREGIR_CAMPO", "actor": actor, "fecha": ctx.reloj().astimezone(timezone.utc).isoformat(),
            "documento": {"archivo": archivo, "numero_guia": plan.datos["guia"],
                          "numero_transporte": plan.datos["transporte"]},
            "campo": campo, "valor_documental": antes, "valor_corregido": valor,
            "referencia": str(p.get("referencia", "")),
        })
        escribir_json_atomico(ctx.archivos["ledger_decisiones"], ledger)
    if campo == "numero_transporte":
        return {"despues": {campo: valor}, "reconciliar": True,
                "retirar_obsoletas": (archivo, campo, valor, str(plan.datos["transporte"])),
                "guias_revalidar": [plan.datos["guia"], *plan.datos["guias_destino"]], "regenerar_reporte": True}
    return {"despues": {campo: valor}, "reconciliar": True, "retirar_obsoletas": (archivo, campo, valor),
            "guias_revalidar": [plan.datos["guia"]], "regenerar_reporte": True}


def _retirar_obsoletas_por_campo(ctx: _Contexto, archivo: str, campo: str, valor: str,
                                 transporte_anterior: str = "") -> list[str]:
    """Red de seguridad DESPUÉS de la reconciliación canónica (que ya retira
    y recalcula los tipos que conoce): ninguna tarjeta puede seguir
    preguntando por el valor anterior de un campo que el operador corrigió.
    Sólo quita entradas -- los hashes publicados de la bandeja siguen válidos."""
    from atlas_core.decisiones_pendientes import NOMBRE_LOCK_DECISIONES_PENDIENTES
    if not ctx.archivos["bandeja"].is_file():
        return []
    retiradas: list[str] = []
    with bloqueo_sesion(ctx.actual, NOMBRE_LOCK_DECISIONES_PENDIENTES):
        contenido = _leer_json(ctx.archivos["bandeja"], {})
        clave = "decisiones" if isinstance(contenido.get("decisiones"), list) else "decisions"
        vigentes = []
        for decision in contenido.get(clave) or []:
            if isinstance(decision, dict) and _decision_obsoleta_por_campo(
                    decision, archivo, campo, valor, transporte_anterior):
                retiradas.append(str(decision.get("decision_id", "")))
            else:
                vigentes.append(decision)
        if retiradas:
            contenido[clave] = vigentes
            escribir_json_atomico(ctx.archivos["bandeja"], contenido)
    return retiradas


def _plan_documento_obra(ctx: _Contexto, p: dict) -> Plan:
    """Obra de una guía = una obra YA EXISTENTE del catálogo (por obra_id).
    Se escribe su nombre canónico por la misma vía que DOCUMENTO_CORREGIR_CAMPO;
    el catálogo no se toca (ni obra nueva ni alias desde el texto anterior)."""
    obra = _obra(ctx, str(p["obra_id"]))
    if obra.estado_vigencia != "ACTIVO" or obra.estado in {"RECHAZADA", "INACTIVA"}:
        raise ErrorAccionOperacional("PRECONDICION_FALLIDA", "la obra está rechazada o inactiva")
    base = _plan_documento_campo(ctx, {"numero_guia": p["numero_guia"], "campo": "obra_destino",
                                       "valor": obra.nombre_canonico, "archivo": p.get("archivo", "")})
    base.entidad["obra_id"] = obra.obra_id
    base.valor_propuesto = {"obra_destino": obra.nombre_canonico, "obra_id": obra.obra_id}
    base.estado_base = {"documento": base.estado_base, "obra": obra.a_dict()}
    base.consecuencias = [
        f"Reutiliza la obra existente {obra.nombre_canonico!r} (obra_id {obra.obra_id}); "
        "no crea obra nueva ni registra el valor anterior como alias.",
        *base.consecuencias,
        "Revalidación focal sólo de esta guía y su viaje.",
    ]
    return base


def _aplicar_documento_obra(ctx: _Contexto, p: dict, plan: Plan, actor: str) -> dict:
    salida = _aplicar_documento_campo(ctx, {"campo": "obra_destino", "valor": plan.valor_propuesto["obra_destino"],
                                            "referencia": p.get("referencia", "")}, plan, actor)
    salida["despues"] = dict(plan.valor_propuesto)
    return salida


# =============================================================== DECISIONES


_ACCIONES_DECISION = (
    "REGISTRAR", "NO_REGISTRAR", "CONFIRMAR", "NO_CONFIRMAR", "CONFIRMAR_PLANTA", "SELECCIONAR_OTRA_PLANTA",
    "NO_PUEDO_DETERMINAR", "USAR_PATENTE_EXISTENTE", "SELECCIONAR_OTRA_PATENTE", "CONFIRMAR_ALIAS", "RECHAZAR",
    "REGISTRAR_DIRECCION", "REGISTRAR_CLIENTE_MANUAL",
)
_EXTRAS_DECISION = (
    "tipo_vehiculo", "planta_id_elegida", "patente_elegida", "motivo_rechazo", "direccion_manual", "comuna_manual",
    "razon_social_manual", "rut_manual", "nombre_obra_manual", "cliente_correccion_manual", "rut_chofer_elegido",
)


def _consultar_decisiones(ctx: _Contexto, p: dict) -> object:
    guia = str(p.get("numero_guia", ""))
    decisiones = [d for d in ctx.decisiones()
                  if not guia or str((d.get("documento") or {}).get("numero_guia", "")) == guia]
    return {"decisiones": [
        {"decision_id": d.get("decision_id"), "tipo": d.get("tipo"), "campo": d.get("campo"),
         "valor_documental": d.get("valor_documental"), "documento": d.get("documento"),
         "acciones_permitidas": d.get("acciones_permitidas")} for d in decisiones[:200]],
        "total": len(decisiones)}


def _plan_decision(ctx: _Contexto, p: dict) -> Plan:
    decision_id = str(p["decision_id"])
    ledger = _leer_json(ctx.archivos["ledger_decisiones"], {})
    aplicada = next((a for a in ledger.get("aplicaciones", []) or [] if a.get("decision_id") == decision_id), None)
    decision = next((d for d in ctx.decisiones() if d.get("decision_id") == decision_id), None)
    if aplicada is None and decision is None:
        raise ErrorAccionOperacional("ENTIDAD_NO_ENCONTRADA", "la decisión no está pendiente")
    accion = str(p["accion_decision"])
    if decision is not None and aplicada is None and accion not in (decision.get("acciones_permitidas") or []):
        raise ErrorAccionOperacional("PARAMETRO_INVALIDO", "la acción no está permitida para esta decisión")
    base = decision or {}
    return Plan(
        entidad={"tipo": "DECISION", "id": decision_id, "tipo_decision": base.get("tipo") or (aplicada or {}).get("tipo"),
                 "documento": base.get("documento") or (aplicada or {}).get("documento")},
        valor_actual={"estado": "APLICADA" if aplicada else "PENDIENTE", "valor_documental": base.get("valor_documental"),
                      "candidatos": base.get("candidatos")},
        valor_propuesto={"accion": accion, **{k: p[k] for k in _EXTRAS_DECISION if k in p}},
        estado_base={"decision": decision, "aplicada": bool(aplicada)}, sin_cambios=aplicada is not None,
        afectados={"guias": [str((base.get("documento") or {}).get("numero_guia", ""))]},
        consecuencias=["Se aplica por `aplicar_decision_obra` (misma vía que Revisión de Atlas), con su propio"
                       " respaldo transaccional y plan de impacto."],
        revalidaciones=["PLAN_DE_IMPACTO_APLICAR_DECISION"],
        archivos=("choferes", "vehiculos", "clientes", "obras_destinos", "destinos_maestros",
                  "dataset", "bandeja", "ledger_decisiones"),
    )


def _aplicar_decision(ctx: _Contexto, p: dict, plan: Plan, actor: str) -> dict:
    from atlas_core.aplicacion_decisiones import ErrorAplicacionDecision, aplicar_decision_obra
    argumentos = dict(raiz_atlas=ctx.raiz, decision_id=str(p["decision_id"]), accion=str(p["accion_decision"]),
                      actor=actor, proveedor_rutas=ctx.proveedor_rutas,
                      proveedor_rutas_fallback=ctx.proveedor_rutas_fallback,
                      **{k: p[k] for k in _EXTRAS_DECISION if k in p})
    try:
        resultado = aplicar_decision_obra(**argumentos)
    except ErrorAplicacionDecision as error:
        raise ErrorAccionOperacional("SERVICIO_RECHAZO", str(error)) from error
    return {"despues": {"estado": "APLICADA", "accion": p["accion_decision"]}, "servicio": resultado}


# =============================================================== VIAJE FÍSICO


def _plan_viaje_agrupar(ctx: _Contexto, p: dict) -> Plan:
    from atlas_core.agrupacion_viajes import agrupaciones_activas, evaluar_agrupacion, identificador_agrupacion
    guias = [str(g) for g in p["guias"]]
    if not 2 <= len(set(guias)) <= 10 or any(not re.fullmatch(r"\d{3,12}", g) for g in guias):
        raise ErrorAccionOperacional("PARAMETRO_INVALIDO", "guias: entre 2 y 10 números de guía distintos")
    filas = ctx.filas()
    agrupaciones = agrupaciones_activas(ctx.actual)
    eventos = _leer_json(ctx.actual / "eventos_operacionales.json", {}).get("eventos") or []
    evaluacion = evaluar_agrupacion(guias=guias, filas=filas, agrupaciones=agrupaciones, eventos=eventos)
    if evaluacion.motivo_rechazo:
        raise ErrorAccionOperacional("PRECONDICION_FALLIDA", evaluacion.motivo_rechazo)
    transportes = evaluacion.transportes
    todas_las_guias = sorted({d["numero_guia"] for docs in evaluacion.documentos.values() for d in docs})
    relevantes = [a for a in agrupaciones if set(a.get("transportes") or []) & set(transportes)]
    pendientes = {str((d.get("documento") or {}).get("numero_guia", "")).strip() for d in ctx.decisiones()
                  if d.get("estado", "PENDIENTE") == "PENDIENTE"}
    resultado = _simular_viaje_agrupado(filas, transportes, pendientes) if not evaluacion.ya_agrupadas else {}
    return Plan(
        entidad={"tipo": "VIAJE_FISICO", "id": identificador_agrupacion(transportes), "transportes": transportes,
                 "guias": evaluacion.guias},
        valor_actual={"viajes": [{"numero_transporte": t, "guias": [d["numero_guia"] for d in docs],
                                  "planta_horas": sorted({f"{d['planta_origen_nombre']} {d['hora_entrada_aza']}-"
                                                          f"{d['hora_salida_aza']}".strip() for d in docs})}
                                 for t, docs in evaluacion.documentos.items()]},
        valor_propuesto={"viaje_unico": {"numero_transporte_principal": evaluacion.principal,
                                         "transportes_aza": transportes, "guias": todas_las_guias,
                                         **resultado}},
        estado_base={"filas": [f for f in filas if str(f.get("numero_transporte", "")).strip() in set(transportes)],
                     "agrupaciones": relevantes},
        sin_cambios=evaluacion.ya_agrupadas,
        afectados=_afectados_por_guias(ctx, set(todas_las_guias)),
        consecuencias=[
            f"{len(transportes)} transportes AZA pasan a ser UN viaje Atlas (principal {evaluacion.principal}); "
            "cada guía conserva su número de transporte y sus datos documentales.",
            "Cada guía conserva su transporte, planta, material y peso; cada entrega conserva su destino y su "
            "propia ruta (nunca la del transporte principal). Ver cargas y entregas resultantes.",
        ],
        revalidaciones=["REGENERAR_REPORTE_VIAJES", "RECONCILIAR_BANDEJA", "MANTENIMIENTO_FOCAL_GUIAS"],
        archivos=("agrupaciones_viaje", "bandeja"),
        datos={"transportes": transportes, "guias": todas_las_guias},
    )


def _simular_viaje_agrupado(filas: list[dict[str, str]], transportes: list[str], pendientes: set[str]) -> dict:
    """Resultado EXACTO que publicará el reporte tras agrupar: el mismo
    `agrupar_viajes` sobre las filas involucradas, en memoria (no escribe)."""
    from atlas_core.gestor_viajes import agrupar_viajes
    involucradas = [f for f in filas if str(f.get("numero_transporte", "")).strip() in set(transportes)]
    viajes, _ = agrupar_viajes(involucradas, guias_revision_humana=pendientes - {""},
                               agrupaciones_transporte={t: transportes[0] for t in transportes})
    if len(viajes) != 1:
        raise ErrorAccionOperacional("PRECONDICION_FALLIDA", "la simulación no produjo un único viaje")
    viaje = viajes[0]
    cargas = []
    for transporte in transportes:
        docs = [d for d in viaje.documentos if d.evidencia.get("numero_transporte", "").strip() == transporte]
        cargas.append({
            "numero_transporte": transporte,
            "plantas": sorted({d.planta_origen_nombre for d in docs if d.planta_origen_nombre}),
            "horas_planta": sorted({f"{d.hora_entrada_aza}-{d.hora_salida_aza}" for d in docs
                                    if d.hora_entrada_aza or d.hora_salida_aza}),
            "guias": [{"numero_guia": d.numero_guia, "peso_kg": d.peso_kg,
                       "material": d.descripcion_material} for d in docs],
        })
    entregas = [{"guias": list(e.get("numeros_guia") or []), "destino": e.get("destino_operacional", ""),
                 "localidad": e.get("localidad_entrega", ""), "distancia_km": e.get("distancia_km", ""),
                 "estado_ruta": e.get("estado_ruta", "")} for e in viaje.entregas]
    return {"cargas": cargas, "entregas": entregas, "peso_total_kg": viaje.peso_total_viaje_kg,
            "estado_resultante": viaje.estado.value, "motivos_revision": [m.value for m in viaje.motivos_revision]}


def _aplicar_viaje_agrupar(ctx: _Contexto, p: dict, plan: Plan, actor: str) -> dict:
    from atlas_core.agrupacion_viajes import registrar_agrupacion
    agrupacion, _creada = registrar_agrupacion(
        ctx.actual, transportes=plan.datos["transportes"], guias=plan.datos["guias"], actor=actor,
        confirmado_por=ctx.confirmado_por or actor, fuente=f"ACCION_OPERACIONAL:{ctx.token}", referencia=str(p.get("referencia", "")),
        reloj=ctx.reloj,
    )
    return {"despues": {"agrupacion_id": agrupacion["agrupacion_id"], "transportes_aza": agrupacion["transportes"],
                        "numero_transporte_principal": agrupacion["transporte_principal"]},
            "reconciliar": True, "guias_revalidar": list(plan.datos["guias"]), "regenerar_reporte": True}


# =============================================================== TRANSPORTE (sensible)


def _plan_transporte(ctx: _Contexto, p: dict) -> Plan:
    transporte = str(p["numero_transporte"])
    filas = [f for f in ctx.filas() if str(f.get("numero_transporte", "")).strip() == transporte]
    if not filas:
        raise ErrorAccionOperacional("ENTIDAD_NO_ENCONTRADA", "transporte sin documentos persistidos")
    return Plan(
        entidad={"tipo": "TRANSPORTE", "id": transporte},
        valor_actual={"documentos": [f.get("archivo", "") for f in filas]},
        valor_propuesto={"reextraccion": "OCR sobre la evidencia original de cada documento"},
        estado_base={"filas": filas},
        afectados=_afectados_por_guias(ctx, {str(f.get("numero_guia", "")) for f in filas}),
        consecuencias=["Re-extrae con OCR y puede cambiar campos documentales (el ledger humano siempre gana).",
                       "Dispara la reconciliación canónica global `revalidar_y_regenerar_reporte`."],
        revalidaciones=["REVALIDAR_Y_REGENERAR_REPORTE"],
        archivos=("dataset", "bandeja"),
    )


def _aplicar_transporte(ctx: _Contexto, p: dict, plan: Plan, actor: str) -> dict:
    from atlas_core.reprocesamiento_reparador import revalidar_documentos_por_transporte
    resultado = revalidar_documentos_por_transporte(
        raiz_atlas=ctx.raiz, numero_transporte=str(p["numero_transporte"]), dry_run=False)
    return {"despues": {"reextraido": True}, "servicio": resultado}


# =============================================================== registro

_P = Parametro
_REF = _P("texto", max_largo=500)

ACCIONES: dict[str, DefinicionAccion] = {d.nombre: d for d in (
    DefinicionAccion("CHOFER_CONSULTAR", LECTURA,
                     "Choferes del catálogo: registrados, activos/inactivos y con/sin viajes (opcionalmente en un período).",
                     {"estado": _P("enum", opciones=("ACTIVO", "INACTIVO", "TODOS")),
                      "viajes": _P("enum", opciones=("CON", "SIN", "TODOS")),
                      "fecha_desde": _P("fecha"), "fecha_hasta": _P("fecha")}, consultar=_consultar_choferes),
    DefinicionAccion("OBRA_CONSULTAR", LECTURA, "Lista obras (opcionalmente por nombre) con sus relaciones.",
                     {"nombre": _P("texto")}, consultar=_consultar_obras),
    DefinicionAccion("DECISION_CONSULTAR", LECTURA, "Lista decisiones pendientes (opcionalmente por guía).",
                     {"numero_guia": _P("guia")}, consultar=_consultar_decisiones),
    DefinicionAccion("CHOFER_CAMBIAR_ESTADO", OPERACIONAL_REVERSIBLE, "Activa o inactiva un chofer (nunca lo borra).",
                     {"chofer": _P("id", True), "activo": _P("bool", True), "referencia": _REF},
                     _plan_chofer_estado, _aplicar_chofer_estado),
    DefinicionAccion("CHOFER_AGREGAR_ALIAS", OPERACIONAL_REVERSIBLE, "Agrega un alias nominal a un chofer.",
                     {"chofer": _P("id", True), "alias": _P("texto", True, max_largo=120), "referencia": _REF},
                     _plan_chofer_alias, _aplicar_chofer_alias),
    DefinicionAccion("CHOFER_ASIGNAR_VEHICULO", OPERACIONAL_REVERSIBLE,
                     "Asocia un chofer a un vehículo CONFIRMADO y ACTIVO (evidencia append-only).",
                     {"chofer": _P("id", True), "patente": _P("patente", True), "referencia": _REF},
                     _plan_chofer_vehiculo, _aplicar_chofer_vehiculo),
    DefinicionAccion("OBRA_REGISTRAR", OPERACIONAL_REVERSIBLE, "Registra una obra nueva (identidad global OBSERVADA).",
                     {"cliente_id": _P("id", True), "nombre_obra": _P("texto", True, max_largo=200),
                      "alias_documental": _P("texto", max_largo=200), "referencia": _REF},
                     _plan_obra_registrar, _aplicar_obra_registrar),
    DefinicionAccion("OBRA_CORREGIR", OPERACIONAL_REVERSIBLE, "Corrige nombre canónico / agrega aliases de una obra.",
                     {"obra_id": _P("id", True), "nombre_canonico": _P("texto", True, max_largo=200),
                      "aliases": _P("lista_texto", max_largo=200), "referencia": _REF},
                     _plan_obra_corregir, _aplicar_obra_corregir),
    DefinicionAccion("DESTINO_REGISTRAR", OPERACIONAL_REVERSIBLE, "Registra (o reutiliza y confirma) un destino global.",
                     {"direccion": _P("texto", True), "comuna": _P("texto", max_largo=80),
                      "region": _P("texto", max_largo=80), "nombre_destino": _P("texto"),
                      "latitud": _P("numero"), "longitud": _P("numero"), "referencia": _REF},
                     _plan_destino_registrar, _aplicar_destino_registrar),
    DefinicionAccion("DESTINO_CONFIRMAR_COORDENADA", OPERACIONAL_REVERSIBLE,
                     "Confirma (humano) la coordenada canónica de un destino EXISTENTE y lo deja CONFIRMADO.",
                     {"destino_id": _P("id", True), "latitud": _P("numero", True), "longitud": _P("numero", True),
                      "referencia": _REF},
                     _plan_destino_coordenada, _aplicar_destino_coordenada),
    DefinicionAccion("DESTINO_RETIRAR_COORDENADA_NO_VERIFICADA", OPERACIONAL_REVERSIBLE,
                     "Retira una coordenada no verificada de un destino CONFIRMADO y deja pendiente la ruta "
                     "de sus guías (nunca asigna otra coordenada).",
                     {"destino_id": _P("id", True), "guias": _P("lista_texto", True, max_largo=12),
                      "comuna": _P("texto", max_largo=80), "referencia": _REF},
                     _plan_destino_retirar_coordenada, _aplicar_destino_retirar_coordenada),
    DefinicionAccion("OBRA_VINCULAR_DESTINO", OPERACIONAL_REVERSIBLE, "Confirma la relación obra↔destino.",
                     {"obra_id": _P("id", True), "destino_id": _P("id", True), "cliente_id": _P("id"),
                      "observaciones": _P("texto"), "referencia": _REF},
                     _plan_obra_destino, _aplicar_obra_destino),
    DefinicionAccion("DOCUMENTO_CORREGIR_CAMPO", OPERACIONAL_REVERSIBLE,
                     "Corrige un campo documental autorizado de una guía y reconcilia lo afectado.",
                     {"numero_guia": _P("guia", True), "campo": _P("enum", True, opciones=()),
                      "valor": _P("texto", True, max_largo=200), "archivo": _P("archivo_documento", max_largo=260),
                      "referencia": _REF},
                     _plan_documento_campo, _aplicar_documento_campo),
    DefinicionAccion("DOCUMENTO_ASIGNAR_OBRA", OPERACIONAL_REVERSIBLE,
                     "Asigna a una guía una obra EXISTENTE del catálogo (sin crear obra ni alias).",
                     {"numero_guia": _P("guia", True), "obra_id": _P("id", True),
                      "archivo": _P("archivo_documento", max_largo=260), "referencia": _REF},
                     _plan_documento_obra, _aplicar_documento_obra),
    DefinicionAccion("DECISION_APLICAR", OPERACIONAL_REVERSIBLE, "Aplica una decisión pendiente de Revisión.",
                     {"decision_id": _P("id", True), "accion_decision": _P("enum", True, opciones=_ACCIONES_DECISION),
                      **{k: _P("texto", max_largo=200) for k in _EXTRAS_DECISION}},
                     _plan_decision, _aplicar_decision),
    DefinicionAccion("VIAJE_AGRUPAR_GUIAS", OPERACIONAL_REVERSIBLE,
                     "Declara que 2+ guías (y sus transportes AZA completos) son un mismo viaje físico.",
                     {"guias": _P("lista_texto", True, max_largo=12), "referencia": _REF},
                     _plan_viaje_agrupar, _aplicar_viaje_agrupar),
    DefinicionAccion("TRANSPORTE_REVALIDAR", SENSIBLE, "Re-extrae con OCR los documentos de un transporte.",
                     {"numero_transporte": _P("transporte", True), "referencia": _REF},
                     _plan_transporte, _aplicar_transporte),
    # Declaradas sólo para que su rechazo sea explícito y auditable.
    DefinicionAccion("ENTIDAD_ELIMINAR", DESTRUCTIVA, "Eliminar entidades de catálogo: prohibido.", {}),
    DefinicionAccion("EVIDENCIA_ELIMINAR", DESTRUCTIVA, "Eliminar evidencia original: prohibido.", {}),
    DefinicionAccion("HISTORIAL_ELIMINAR", DESTRUCTIVA, "Eliminar historial/auditoría: prohibido.", {}),
)}


def _esquema(definicion: DefinicionAccion) -> Mapping[str, Parametro]:
    if definicion.nombre == "DOCUMENTO_CORREGIR_CAMPO":
        esquema = dict(definicion.parametros)
        esquema["campo"] = Parametro("enum", True, opciones=tuple(c.upper() for c in _campos_documentales()))
        return esquema
    return definicion.parametros


def catalogo_acciones() -> list[dict[str, object]]:
    """Contrato público: qué acciones existen, su riesgo y sus parámetros."""
    return [{
        "accion": d.nombre, "riesgo": d.riesgo, "autonomia_b1": POLITICA_AUTONOMIA[d.riesgo],
        "descripcion": d.descripcion,
        "parametros": {n: {"tipo": s.tipo, "obligatorio": s.obligatorio,
                           **({"opciones": list(s.opciones)} if s.opciones else {})}
                       for n, s in _esquema(d).items()},
    } for d in ACCIONES.values()]


# =============================================================== fachada


class CapaAccionesOperacionales:
    """Única puerta de escritura operacional para agentes."""

    def __init__(self, raiz_atlas: str | Path, *, reloj=lambda: datetime.now(timezone.utc),
                 proveedor_rutas=None, proveedor_rutas_fallback=None, ttl_preview: timedelta = TTL_PREVIEW):
        self.raiz = Path(raiz_atlas)
        self._reloj = reloj
        self._ttl = ttl_preview
        self._ctx = _Contexto(self.raiz, reloj, proveedor_rutas, proveedor_rutas_fallback)
        self._ruta_registro = self._ctx.actual / NOMBRE_REGISTRO

    # ------------------------------------------------------------ registro

    def _leer_registro(self) -> dict:
        registro = _leer_json(self._ruta_registro, None)
        if registro is None:
            return {"schema_version": SCHEMA_VERSION, "previews": {}, "auditoria": []}
        if registro.get("schema_version") != SCHEMA_VERSION:
            raise ErrorAccionOperacional("ESTADO_ILEGIBLE", "registro de acciones con versión desconocida")
        return registro

    def _guardar_registro(self, registro: dict) -> None:
        ahora = self._reloj()
        registro["previews"] = {
            t: v for t, v in registro.get("previews", {}).items()
            if v.get("estado") == "PREVIEW" and datetime.fromisoformat(v["expira_en"]) > ahora
        }
        escribir_json_atomico(self._ruta_registro, registro)

    def auditoria(self) -> list[dict]:
        return list(self._leer_registro().get("auditoria", []))

    # ------------------------------------------------------------ preview

    @staticmethod
    def _definicion(accion: object) -> DefinicionAccion:
        definicion = ACCIONES.get(str(accion or "").strip().upper()) if isinstance(accion, str) else None
        if definicion is None:
            raise ErrorAccionOperacional("ACCION_INVALIDA", "acción no reconocida por la capa canónica")
        if definicion.riesgo == DESTRUCTIVA:
            raise ErrorAccionOperacional("ACCION_PROHIBIDA", "acción destructiva fuera del alcance de esta capa")
        return definicion

    def _planificar(self, definicion: DefinicionAccion, parametros: dict) -> Plan:
        try:
            return definicion.planificar(self._ctx, parametros)
        except ErrorAccionOperacional:
            raise
        except (ValueError, OSError) as error:
            raise ErrorAccionOperacional("PRECONDICION_FALLIDA", str(error)) from error

    def _construir_preview(self, definicion: DefinicionAccion, parametros: dict, plan: Plan, *,
                           actor: str, origen: str, referencia: str) -> dict:
        ahora = self._reloj()
        huella_base = _huella(plan.estado_base)
        return {
            "estado": "SIN_CAMBIOS" if plan.sin_cambios else "PREVIEW",
            "token": uuid.uuid4().hex,
            "accion": definicion.nombre, "riesgo": definicion.riesgo,
            "autonomia_b1": POLITICA_AUTONOMIA[definicion.riesgo],
            "entidad": plan.entidad, "valor_actual": plan.valor_actual, "valor_propuesto": plan.valor_propuesto,
            "afectados": plan.afectados, "consecuencias": plan.consecuencias,
            "revalidaciones": plan.revalidaciones,
            "requiere_confirmacion": not plan.sin_cambios,
            "parametros": parametros, "huella_base": huella_base,
            # Misma entidad resuelta + mismo valor propuesto = misma acción,
            # sin importar cómo se escribió el identificador (RUT con o sin
            # formato, patente con guion, etc.).
            "idempotency_key": _huella({"accion": definicion.nombre, "tipo": plan.entidad.get("tipo"),
                                        "id": plan.entidad.get("id"), "propuesto": plan.valor_propuesto}),
            "solicitado_por": actor, "origen": origen, "referencia": referencia,
            "creado_en": ahora.isoformat(), "expira_en": (ahora + self._ttl).isoformat(),
        }

    def previsualizar(self, accion: object, parametros: object = None, *, actor: str,
                      origen: str = ORIGEN_HUMANO, referencia: str = "") -> dict:
        """Nunca escribe datos operacionales: sólo registra el preview."""
        try:
            definicion = self._definicion(accion)
            limpios = _validar_parametros(_esquema(definicion), parametros)
            actor = self._validar_actor(actor, origen)
            if definicion.riesgo == LECTURA:
                return {"estado": "RESULTADO", "accion": definicion.nombre, "riesgo": LECTURA,
                        "requiere_confirmacion": False, "resultado": definicion.consultar(self._ctx, limpios)}
            plan = self._planificar(definicion, limpios)
            preview = self._construir_preview(definicion, limpios, plan, actor=actor, origen=origen,
                                              referencia=str(referencia or "")[:500])
            if plan.sin_cambios:
                # Nada que confirmar: sin token ejecutable, sin escritura.
                anterior = next((a for a in reversed(self.auditoria())
                                 if a.get("idempotency_key") == preview["idempotency_key"]
                                 and a.get("resultado") == "APLICADA"), None)
                preview.update(token=None, idempotente=True,
                               auditoria_previa=anterior.get("auditoria_id") if anterior else None)
            else:
                with bloqueo_sesion(self._ctx.actual, NOMBRE_LOCK):
                    registro = self._leer_registro()
                    registro.setdefault("previews", {})[preview["token"]] = preview
                    self._guardar_registro(registro)
            return preview
        except ErrorAccionOperacional as error:
            return _rechazo(error, accion=str(accion))
        except SesionOcupadaError as error:
            return _rechazo(ErrorAccionOperacional("SESION_OCUPADA", str(error)), accion=str(accion))

    consultar = previsualizar

    @staticmethod
    def _validar_actor(actor: object, origen: str) -> str:
        if origen not in ORIGENES:
            raise ErrorAccionOperacional("PARAMETRO_INVALIDO", "origen desconocido")
        texto = str(actor or "").strip()
        if not _ID.fullmatch(texto):
            raise ErrorAccionOperacional("PARAMETRO_INVALIDO", "actor obligatorio (identificador simple)")
        return texto

    # ------------------------------------------------------------ ejecutar

    def ejecutar(self, token: str, *, actor: str, confirmado_por: str = "", origen: str = ORIGEN_HUMANO,
                 autorizacion_sensible: bool = False, accion_esperada: str | None = None) -> dict:
        """Ejecuta EXACTAMENTE el preview identificado por `token`."""
        try:
            actor = self._validar_actor(actor, origen)
            with bloqueo_sesion(self._ctx.actual, NOMBRE_LOCK):
                return self._ejecutar_bloqueado(str(token or ""), actor=actor, confirmado_por=confirmado_por,
                                                origen=origen, autorizacion_sensible=autorizacion_sensible,
                                                accion_esperada=accion_esperada)
        except ErrorAccionOperacional as error:
            return _rechazo(error, token=str(token))
        except SesionOcupadaError as error:
            return _rechazo(ErrorAccionOperacional("SESION_OCUPADA", str(error)), token=str(token))

    def _ejecutar_bloqueado(self, token: str, *, actor: str, confirmado_por: str, origen: str,
                            autorizacion_sensible: bool, accion_esperada: str | None) -> dict:
        registro = self._leer_registro()
        previa = next((a for a in registro.get("auditoria", []) if a.get("token") == token), None)
        if previa is not None:
            # Reintento del MISMO token: nunca vuelve a escribir.
            return {**previa["resultado_publico"], "idempotente": True}
        preview = registro.get("previews", {}).get(token)
        if preview is None:
            raise ErrorAccionOperacional("TOKEN_DESCONOCIDO", "no existe un preview vigente con ese token")
        if accion_esperada is not None and str(accion_esperada).upper() != preview["accion"]:
            raise ErrorAccionOperacional("TOKEN_NO_CORRESPONDE", "el token pertenece a otra acción")
        if datetime.fromisoformat(preview["expira_en"]) <= self._reloj():
            raise ErrorAccionOperacional("PREVIEW_EXPIRADO", "el preview expiró; solicite uno nuevo")
        definicion = self._definicion(preview["accion"])
        confirmado = str(confirmado_por or "").strip()
        if definicion.riesgo in (OPERACIONAL_REVERSIBLE, SENSIBLE) and not _ID.fullmatch(confirmado):
            raise ErrorAccionOperacional("CONFIRMACION_REQUERIDA", "falta la confirmación humana explícita")
        if definicion.riesgo == SENSIBLE and (origen != ORIGEN_HUMANO or not autorizacion_sensible):
            raise ErrorAccionOperacional(
                "FUERA_DE_AUTONOMIA", "acción SENSIBLE: sólo un humano con autorización explícita puede ejecutarla",
            )
        parametros = dict(preview["parametros"])
        plan = self._planificar(definicion, parametros)
        if _huella(plan.estado_base) != preview["huella_base"]:
            nuevo = self._construir_preview(definicion, parametros, plan, actor=preview["solicitado_por"],
                                            origen=preview["origen"], referencia=preview.get("referencia", ""))
            registro["previews"][token]["estado"] = "OBSOLETO"
            if not plan.sin_cambios:
                registro["previews"][nuevo["token"]] = nuevo
            self._guardar_registro(registro)
            return {"estado": "PREVIEW_OBSOLETO", "token": token, "accion": definicion.nombre,
                    "mensaje": "la entidad cambió desde el preview; no se ejecutó nada", "preview_nuevo": nuevo}
        if plan.sin_cambios:
            registro["previews"][token]["estado"] = "SIN_CAMBIOS"
            self._guardar_registro(registro)
            anterior = next((a for a in reversed(registro.get("auditoria", []))
                             if a.get("idempotency_key") == preview["idempotency_key"]), None)
            return {"estado": "SIN_CAMBIOS", "token": token, "accion": definicion.nombre, "idempotente": True,
                    "auditoria_previa": anterior.get("auditoria_id") if anterior else None}

        self._ctx.token = token
        self._ctx.confirmado_por = confirmado
        respaldo = self._respaldar(plan.archivos, token)
        instante = self._reloj().astimezone(timezone.utc).isoformat()
        try:
            salida = definicion.aplicar(self._ctx, parametros, plan, actor)
        except Exception as error:  # noqa: BLE001 -- se restaura y se audita cualquier fallo del servicio
            self._restaurar(respaldo)
            codigo = error.codigo if isinstance(error, ErrorAccionOperacional) else "ERROR_SERVICIO"
            publico = {"estado": "FALLIDA", "token": token, "accion": definicion.nombre, "codigo": codigo,
                       "mensaje": f"{type(error).__name__}: {error}", "respaldo_restaurado": True}
            self._auditar(registro, preview, actor=actor, confirmado_por=confirmado, origen=origen,
                          instante=instante, despues=None, resultado="FALLIDA", publico=publico,
                          respaldo=respaldo)
            return publico
        ids_antes = self._ids_decisiones_documento(plan)
        reconciliacion = self._reconciliar() if salida.get("reconciliar") else None
        red_seguridad = (_retirar_obsoletas_por_campo(self._ctx, *salida["retirar_obsoletas"])
                         if salida.get("retirar_obsoletas") else [])
        ids_despues = self._ids_decisiones_documento(plan)
        revalidacion = {
            "focal": salida.get("revalidacion_focal"),
            "guias": self._revalidar_guias(set(salida.get("guias_revalidar") or ())),
            "reporte": self._regenerar_reporte() if salida.get("regenerar_reporte") else None,
        }
        publico = {
            "estado": "APLICADA", "token": token, "accion": definicion.nombre, "riesgo": definicion.riesgo,
            "entidad": plan.entidad, "antes": plan.valor_actual, "despues": salida.get("despues"),
            "decisiones_retiradas": sorted(ids_antes - ids_despues),
            "decisiones_nuevas": sorted(ids_despues - ids_antes),
            "retiradas_por_red_de_seguridad": red_seguridad,
            "reconciliacion": reconciliacion, "revalidacion": revalidacion,
            "servicio": salida.get("servicio"), "respaldo": respaldo.get("carpeta"), "idempotente": False,
        }
        publico["auditoria_id"] = self._auditar(
            registro, preview, actor=actor, confirmado_por=confirmado, origen=origen, instante=instante,
            despues=salida.get("despues"), resultado="APLICADA", publico=publico, respaldo=respaldo,
        )
        return publico

    # ------------------------------------------------------------ pasos comunes

    def _ids_decisiones_documento(self, plan: Plan) -> set[str]:
        guias = {str(g) for g in (plan.afectados.get("guias") or []) if g}
        if not guias:
            return set()
        try:
            decisiones = self._ctx.decisiones()
        except ErrorAccionOperacional:
            return set()
        return {str(d.get("decision_id", "")) for d in decisiones
                if str((d.get("documento") or {}).get("numero_guia", "")) in guias}

    def _respaldar(self, claves: tuple[str, ...], token: str) -> dict:
        carpeta = (self.raiz / "respaldos" / "acciones_operacionales"
                   / f"{self._reloj().strftime('%Y%m%d_%H%M%S')}_{token[:12]}")
        copias: dict[str, str | None] = {}
        for clave in claves:
            origen = self._ctx.archivos[clave]
            if origen.is_file():
                carpeta.mkdir(parents=True, exist_ok=True)
                shutil.copy2(origen, carpeta / origen.name)
                copias[clave] = origen.name
            else:
                copias[clave] = None
        return {"carpeta": str(carpeta.relative_to(self.raiz)) if carpeta.exists() else None, "copias": copias,
                "ruta": carpeta}

    def _restaurar(self, respaldo: dict) -> None:
        for clave, nombre in respaldo["copias"].items():
            destino = self._ctx.archivos[clave]
            if nombre is None:
                destino.unlink(missing_ok=True)
            else:
                shutil.copy2(respaldo["ruta"] / nombre, destino)

    def _reconciliar(self) -> dict | None:
        """Republica la bandeja con hashes frescos y retira decisiones que el
        nuevo estado vuelve obsoletas -- `reconciliar_bandeja_decisiones` es
        la vía canónica (sin OCR, sin tocar el CSV documental)."""
        if not (self._ctx.archivos["bandeja"].is_file() and self._ctx.archivos["dataset"].is_file()):
            return {"ejecutado": False, "motivo": "SIN_BANDEJA_O_DATASET"}
        from atlas_core.revalidacion_documental import reconciliar_bandeja_decisiones
        try:
            resultado = reconciliar_bandeja_decisiones(raiz_atlas=self.raiz, reloj=self._reloj)
        except Exception as error:  # noqa: BLE001 -- la escritura ya ocurrió; la tarea periódica lo retoma
            return {"ejecutado": False, "motivo": "ERROR_RECONCILIACION", "error": f"{type(error).__name__}: {error}"}
        return {"ejecutado": True, **{k: v for k, v in (resultado or {}).items()
                                      if isinstance(v, (int, float, str, bool)) or v is None}}

    def _revalidar_guias(self, guias: set[str]) -> dict | None:
        guias = {g for g in guias if g}
        if not guias:
            return None
        from atlas_core.mantenimiento_pendientes_tecnicos import mantener_pendientes_tecnicos
        try:
            resultado = mantener_pendientes_tecnicos(
                raiz_atlas=self.raiz, reloj=self._reloj, solo_cambios=True, guias_forzadas=guias,
                proveedor_rutas=self._ctx.proveedor_rutas, proveedor_rutas_fallback=self._ctx.proveedor_rutas_fallback,
            )
        except Exception as error:  # noqa: BLE001
            return {"ejecutado": False, "motivo": "ERROR_REVALIDACION", "error": f"{type(error).__name__}: {error}"}
        return {"ejecutado": bool(resultado.get("ejecutado")), "motivo": resultado.get("motivo"),
                "resueltas": resultado.get("resueltas", []), "pendientes": resultado.get("pendientes", [])}

    def _regenerar_reporte(self) -> dict:
        """Vista derivada de viajes tras un cambio del dataset (mismo patrón
        que el mantenimiento focal): sin OCR ni red."""
        from atlas_core.almacenamiento_portable import escribir_estado_operacion
        from atlas_core.reporte_viajes import _sha256_archivo, generar_reporte_viajes
        actual, dataset = self._ctx.actual, self._ctx.archivos["dataset"]
        instante = self._reloj()
        reporte = self.raiz / "reportes" / f"accion_operacional_{instante.strftime('%Y%m%d_%H%M%S_%f')}"
        try:
            huella = _sha256_archivo(dataset)
            generar_reporte_viajes(dataset, reporte, carpeta_catalogos=self._ctx.catalogos,
                                   ruta_ledger=self._ctx.archivos["ledger_decisiones"], reloj=lambda: instante)
            escribir_estado_operacion(
                reporte_vigente=reporte, dataset_operacional=dataset,
                decisiones_pendientes=self._ctx.archivos["bandeja"] if self._ctx.archivos["bandeja"].is_file() else None,
                raiz=self.raiz, reloj=lambda: instante, origen="ACCION_OPERACIONAL", dataset_sha256=huella,
            )
        except Exception as error:  # noqa: BLE001
            shutil.rmtree(reporte, ignore_errors=True)
            return {"regenerado": False, "error": f"{type(error).__name__}: {error}"}
        return {"regenerado": True, "reporte": str(reporte.relative_to(self.raiz))}

    def _auditar(self, registro: dict, preview: dict, *, actor: str, confirmado_por: str, origen: str,
                 instante: str, despues: object, resultado: str, publico: dict, respaldo: dict) -> str:
        auditoria_id = uuid.uuid4().hex
        registro.setdefault("auditoria", []).append({
            "auditoria_id": auditoria_id, "token": preview["token"], "idempotency_key": preview["idempotency_key"],
            "accion": preview["accion"], "riesgo": preview["riesgo"], "entidad": preview["entidad"],
            "actor": actor, "origen": origen, "confirmado_por": confirmado_por,
            "solicitado_por": preview["solicitado_por"], "referencia": preview.get("referencia", ""),
            "parametros": preview["parametros"], "antes": preview["valor_actual"], "despues": despues,
            "timestamp": instante, "resultado": resultado, "respaldo": respaldo.get("carpeta"),
            "resultado_publico": {**publico, "auditoria_id": auditoria_id},
        })
        registro["previews"][preview["token"]]["estado"] = "EJECUTADO" if resultado == "APLICADA" else resultado
        self._guardar_registro(registro)
        return auditoria_id
