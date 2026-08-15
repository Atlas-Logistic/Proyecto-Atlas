"""Catálogo privado y portable de obras documentales y destinos físicos.

``destino_id`` referencia ``destinos_maestros.json`` y sigue perteneciendo a
un cliente. Una ``Obra`` es, en cambio, una identidad GLOBAL (R3.3.1): su
``cliente_id`` ya NO es propietario ni filtro de resolución -- se conserva
únicamente como procedencia histórica informativa (qué cliente la observó
primero), y puede quedar vacío. La unicidad de nombre/alias normalizado de
una obra ACTIVA es global, no por cliente: dos clientes distintos que
mencionan la misma obra deben resolver a la MISMA fila ``Obra``, y esa
aparición conjunta se conserva sólo como evidencia operacional del
documento, no como una relación de pertenencia. Las observaciones
automáticas nunca confirman obras ni relaciones.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Callable, Iterable, Mapping
from uuid import uuid4

from atlas_core.almacenamiento_portable import (
    bloqueo_sesion,
    escribir_json_atomico,
    ruta_catalogos_privados,
)
from atlas_core.catalogo_clientes import CatalogoClientes
from atlas_core.catalogo_destinos import CatalogoDestinos


VERSION_FORMATO = 1
NOMBRE_ARCHIVO = "obras_destinos.json"


class ErrorCatalogoObrasDestinos(ValueError):
    """Error controlado del catálogo relacional."""


class CatalogoObrasDestinosCorruptoError(ErrorCatalogoObrasDestinos):
    """El archivo existe, pero viola el esquema o su integridad."""


class ObraNoEncontradaError(ErrorCatalogoObrasDestinos):
    pass


class RelacionNoEncontradaError(ErrorCatalogoObrasDestinos):
    pass


class EstadoObra(str, Enum):
    OBSERVADA = "OBSERVADA"
    CANDIDATA = "CANDIDATA"
    CONFIRMADA = "CONFIRMADA"
    RECHAZADA = "RECHAZADA"
    INACTIVA = "INACTIVA"


class EstadoRelacion(str, Enum):
    PENDIENTE = "PENDIENTE"
    CONFIRMADA = "CONFIRMADA"
    RECHAZADA = "RECHAZADA"
    INACTIVA = "INACTIVA"


class EstadoVigencia(str, Enum):
    ACTIVO = "ACTIVO"
    INACTIVO = "INACTIVO"


class TipoEvidencia(str, Enum):
    GUIA = "GUIA"
    RUT = "RUT"
    CODIGO_DESTINATARIO = "CODIGO_DESTINATARIO"
    CATALOGO = "CATALOGO"
    CONFIRMACION_HUMANA = "CONFIRMACION_HUMANA"
    FUENTE_EXTERNA = "FUENTE_EXTERNA"


class ResultadoEvidencia(str, Enum):
    SOPORTA = "SOPORTA"
    CONTRADICE = "CONTRADICE"
    NEUTRAL = "NEUTRAL"


def _ahora_utc() -> datetime:
    return datetime.now(timezone.utc)


def normalizar_nombre_obra(nombre: str) -> str:
    texto = unicodedata.normalize("NFKD", str(nombre or "").strip())
    texto = "".join(c for c in texto if not unicodedata.combining(c)).upper()
    texto = re.sub(
        r"(?<![A-Z0-9])(?:[A-Z]\.){2,}",
        lambda coincidencia: coincidencia.group(0).replace(".", ""),
        texto,
    )
    return " ".join(re.findall(r"[A-Z0-9]+", texto))


def _obligatorio(valor: object, campo: str) -> str:
    limpio = str(valor or "").strip()
    if not limpio:
        raise ErrorCatalogoObrasDestinos(f"{campo} es obligatorio")
    return limpio


def _fecha_iso(valor: str, campo: str) -> None:
    try:
        fecha = datetime.fromisoformat(valor)
    except (TypeError, ValueError) as error:
        raise ErrorCatalogoObrasDestinos(
            f"{campo} debe ser una fecha ISO válida"
        ) from error
    if fecha.tzinfo is None:
        raise ErrorCatalogoObrasDestinos(f"{campo} debe incluir zona horaria")


@dataclass(frozen=True)
class Evidencia:
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
    def desde_dict(cls, datos: object) -> "Evidencia":
        if not isinstance(datos, dict) or set(datos) != set(cls.__dataclass_fields__):
            raise CatalogoObrasDestinosCorruptoError("campos de evidencia incompatibles")
        if not isinstance(datos.get("campos_observados"), dict):
            raise CatalogoObrasDestinosCorruptoError("campos_observados debe ser objeto")
        try:
            evidencia = cls(**datos)
            _validar_evidencia(evidencia)
        except (TypeError, ErrorCatalogoObrasDestinos) as error:
            raise CatalogoObrasDestinosCorruptoError(str(error)) from error
        return evidencia


@dataclass(frozen=True)
class Obra:
    obra_id: str
    cliente_id: str
    nombre_canonico: str
    nombre_normalizado: str
    aliases_documentales: tuple[str, ...]
    estado: str
    estado_vigencia: str
    evidencias: tuple[Evidencia, ...]
    fecha_creacion: str
    fecha_modificacion: str

    def a_dict(self) -> dict[str, object]:
        datos = asdict(self)
        datos["aliases_documentales"] = list(self.aliases_documentales)
        datos["evidencias"] = [e.a_dict() for e in self.evidencias]
        return datos

    @classmethod
    def desde_dict(cls, datos: object) -> "Obra":
        if not isinstance(datos, dict) or set(datos) != set(cls.__dataclass_fields__):
            raise CatalogoObrasDestinosCorruptoError("campos de obra incompatibles")
        if not isinstance(datos.get("aliases_documentales"), list) or not isinstance(
            datos.get("evidencias"), list
        ):
            raise CatalogoObrasDestinosCorruptoError("listas de obra incompatibles")
        try:
            obra = cls(
                **{
                    **datos,
                    "aliases_documentales": tuple(datos["aliases_documentales"]),
                    "evidencias": tuple(
                        Evidencia.desde_dict(e) for e in datos["evidencias"]
                    ),
                }
            )
            _validar_obra(obra)
        except (TypeError, ErrorCatalogoObrasDestinos) as error:
            raise CatalogoObrasDestinosCorruptoError(str(error)) from error
        return obra


@dataclass(frozen=True)
class RelacionObraDestino:
    relacion_id: str
    obra_id: str
    destino_id: str
    estado: str
    evidencias: tuple[Evidencia, ...]
    fuente_confirmacion: str
    confirmado_por: str
    fecha_confirmacion: str
    observaciones: str
    fecha_creacion: str
    fecha_modificacion: str

    def a_dict(self) -> dict[str, object]:
        datos = asdict(self)
        datos["evidencias"] = [e.a_dict() for e in self.evidencias]
        return datos

    @classmethod
    def desde_dict(cls, datos: object) -> "RelacionObraDestino":
        if not isinstance(datos, dict) or set(datos) != set(cls.__dataclass_fields__):
            raise CatalogoObrasDestinosCorruptoError("campos de relación incompatibles")
        if not isinstance(datos.get("evidencias"), list):
            raise CatalogoObrasDestinosCorruptoError("evidencias de relación debe ser lista")
        try:
            relacion = cls(
                **{
                    **datos,
                    "evidencias": tuple(
                        Evidencia.desde_dict(e) for e in datos["evidencias"]
                    ),
                }
            )
            _validar_relacion(relacion)
        except (TypeError, ErrorCatalogoObrasDestinos) as error:
            raise CatalogoObrasDestinosCorruptoError(str(error)) from error
        return relacion


@dataclass(frozen=True)
class ResultadoObservacion:
    obra: Obra
    relacion: RelacionObraDestino | None


@dataclass(frozen=True)
class ResolucionObraDestino:
    obra: Obra
    relacion: RelacionObraDestino
    destino: object


def _validar_evidencia(evidencia: Evidencia) -> None:
    try:
        TipoEvidencia(evidencia.tipo)
        ResultadoEvidencia(evidencia.resultado)
    except ValueError as error:
        raise ErrorCatalogoObrasDestinos("tipo o resultado de evidencia inválido") from error
    _obligatorio(evidencia.identificador_fuente, "identificador_fuente")
    _obligatorio(evidencia.actor_proceso, "actor_proceso")
    _fecha_iso(evidencia.fecha, "fecha")
    if any(not isinstance(k, str) or not isinstance(v, str) for k, v in evidencia.campos_observados.items()):
        raise ErrorCatalogoObrasDestinos("campos_observados debe contener texto")


def _validar_obra(obra: Obra) -> None:
    _obligatorio(obra.obra_id, "obra_id")
    # R3.3.1: cliente_id deja de ser obligatorio -- una obra es una
    # identidad global; cliente_id, cuando está presente, es sólo
    # procedencia histórica informativa (qué cliente la observó primero),
    # nunca una condición de existencia ni de resolución.
    if not isinstance(obra.cliente_id, str):
        raise ErrorCatalogoObrasDestinos("cliente_id debe ser texto")
    nombre = _obligatorio(obra.nombre_canonico, "nombre_canonico")
    if obra.nombre_normalizado != normalizar_nombre_obra(nombre):
        raise ErrorCatalogoObrasDestinos("nombre_normalizado no corresponde")
    try:
        estado = EstadoObra(obra.estado)
        vigencia = EstadoVigencia(obra.estado_vigencia)
    except ValueError as error:
        raise ErrorCatalogoObrasDestinos("estado de obra inválido") from error
    if (estado == EstadoObra.INACTIVA) != (vigencia == EstadoVigencia.INACTIVO):
        raise ErrorCatalogoObrasDestinos("estado y vigencia de obra son incoherentes")
    claves = [normalizar_nombre_obra(a) for a in obra.aliases_documentales]
    if any(not clave for clave in claves) or len(claves) != len(set(claves)):
        raise ErrorCatalogoObrasDestinos("aliases de obra inválidos o duplicados")
    if obra.nombre_normalizado in claves:
        raise ErrorCatalogoObrasDestinos("alias duplica nombre canónico")
    for evidencia in obra.evidencias:
        _validar_evidencia(evidencia)
    if obra.estado == EstadoObra.CONFIRMADA.value and not any(
        evidencia.tipo == TipoEvidencia.CONFIRMACION_HUMANA.value
        and evidencia.resultado == ResultadoEvidencia.SOPORTA.value
        for evidencia in obra.evidencias
    ):
        raise ErrorCatalogoObrasDestinos(
            "obra confirmada sin evidencia humana de soporte"
        )
    _fecha_iso(obra.fecha_creacion, "fecha_creacion")
    _fecha_iso(obra.fecha_modificacion, "fecha_modificacion")


def _validar_relacion(relacion: RelacionObraDestino) -> None:
    _obligatorio(relacion.relacion_id, "relacion_id")
    _obligatorio(relacion.obra_id, "obra_id")
    _obligatorio(relacion.destino_id, "destino_id")
    try:
        estado = EstadoRelacion(relacion.estado)
    except ValueError as error:
        raise ErrorCatalogoObrasDestinos("estado de relación inválido") from error
    for evidencia in relacion.evidencias:
        _validar_evidencia(evidencia)
    if estado == EstadoRelacion.CONFIRMADA:
        _obligatorio(relacion.fuente_confirmacion, "fuente_confirmacion")
        _obligatorio(relacion.confirmado_por, "confirmado_por")
        _fecha_iso(relacion.fecha_confirmacion, "fecha_confirmacion")
        if not any(
            e.tipo == TipoEvidencia.CONFIRMACION_HUMANA.value
            and e.resultado == ResultadoEvidencia.SOPORTA.value
            for e in relacion.evidencias
        ):
            raise ErrorCatalogoObrasDestinos("confirmación sin evidencia humana")
    elif any((relacion.fuente_confirmacion, relacion.confirmado_por, relacion.fecha_confirmacion)):
        raise ErrorCatalogoObrasDestinos("relación no confirmada contiene metadatos de confirmación")
    _fecha_iso(relacion.fecha_creacion, "fecha_creacion")
    _fecha_iso(relacion.fecha_modificacion, "fecha_modificacion")


class CatalogoObrasDestinos:
    def __init__(
        self,
        ruta: str | Path | None = None,
        *,
        ruta_clientes: str | Path | None = None,
        ruta_destinos: str | Path | None = None,
        raiz: Path | None = None,
        reloj: Callable[[], datetime] = _ahora_utc,
        generador_id: Callable[[], object] = uuid4,
    ) -> None:
        carpeta = ruta_catalogos_privados(raiz=raiz)
        self.ruta = Path(ruta) if ruta is not None else carpeta / NOMBRE_ARCHIVO
        self.ruta_clientes = Path(ruta_clientes) if ruta_clientes is not None else carpeta / "clientes.json"
        self.ruta_destinos = Path(ruta_destinos) if ruta_destinos is not None else carpeta / "destinos_maestros.json"
        self._reloj = reloj
        self._generador_id = generador_id

    def inicializar_vacio(self) -> Path:
        """Crea el catálogo V1 vacío una sola vez, sin sobrescribir datos."""
        with bloqueo_sesion(self.ruta.parent, "obras_destinos"):
            if self.ruta.exists():
                raise ErrorCatalogoObrasDestinos(
                    "el catálogo ya existe; no se sobrescribe"
                )
            self._escribir([], [])
        return self.ruta

    def listar_obras(self) -> list[Obra]:
        return list(self._leer()[0])

    def listar_relaciones(self) -> list[RelacionObraDestino]:
        return list(self._leer()[1])

    def actualizar_identidad_obra(
        self,
        obra_id: str,
        *,
        nombre_canonico: str,
        aliases_documentales: Iterable[str] = (),
        evidencia: Evidencia,
    ) -> Obra:
        """Actualiza una identidad auditada sin alterar su pertenencia ni estado."""
        _validar_evidencia(evidencia)
        if evidencia.tipo == TipoEvidencia.CONFIRMACION_HUMANA.value:
            raise ErrorCatalogoObrasDestinos(
                "la identidad canónica requiere evidencia no decisional"
            )
        nombre = _obligatorio(nombre_canonico, "nombre_canonico")
        aliases_nuevos = tuple(
            _obligatorio(alias, "alias_documental") for alias in aliases_documentales
        )
        with bloqueo_sesion(self.ruta.parent, "obras_destinos"):
            obras, relaciones = self._leer()
            obra = self._obra(obras, obra_id)
            if obra.estado_vigencia != EstadoVigencia.ACTIVO.value:
                raise ErrorCatalogoObrasDestinos(
                    "no se puede actualizar la identidad de una obra inactiva"
                )
            clave_canonica = normalizar_nombre_obra(nombre)
            aliases = list(obra.aliases_documentales)
            claves = {normalizar_nombre_obra(alias) for alias in aliases}
            for alias in aliases_nuevos:
                clave = normalizar_nombre_obra(alias)
                if clave != clave_canonica and clave not in claves:
                    aliases.append(alias)
                    claves.add(clave)
            claves_propuestas = {clave_canonica, *claves}
            # R3.3.1: colisión GLOBAL -- una obra es una identidad única en
            # todo Atlas, no sólo frente a las demás obras del mismo cliente.
            for otra in obras:
                if (
                    otra.obra_id != obra.obra_id
                    and otra.estado_vigencia == EstadoVigencia.ACTIVO.value
                    and claves_propuestas.intersection(self._claves_obra(otra))
                ):
                    raise ErrorCatalogoObrasDestinos(
                        "la identidad propuesta colisiona con otra obra activa"
                    )
            instante = self._instante_iso()
            actualizada = replace(
                obra,
                nombre_canonico=nombre,
                nombre_normalizado=clave_canonica,
                aliases_documentales=tuple(aliases),
                evidencias=self._agregar_evidencia(obra.evidencias, evidencia),
                fecha_modificacion=instante,
            )
            _validar_obra(actualizada)
            obras[obras.index(obra)] = actualizada
            self._validar_catalogo(obras, relaciones)
            self._escribir(obras, relaciones)
            return actualizada

    def registrar_observacion(
        self,
        *,
        cliente_id: str,
        nombre_obra: str,
        evidencia: Evidencia,
        destino_id: str | None = None,
        alias_documental: str = "",
    ) -> ResultadoObservacion:
        """Registra evidencia sin confirmar implícitamente ninguna entidad.

        R3.3.1: la obra se busca/crea GLOBALMENTE por nombre normalizado,
        sin filtrar por `cliente_id` -- una obra ya observada para CUALQUIER
        cliente se reutiliza tal cual para éste. `cliente_id` sigue siendo
        obligatorio como identidad del cliente que hace esta observación
        (queda como evidencia operacional del documento), pero deja de ser
        una condición de pertenencia de la obra.
        """
        _validar_evidencia(evidencia)
        if evidencia.tipo == TipoEvidencia.CONFIRMACION_HUMANA.value:
            raise ErrorCatalogoObrasDestinos(
                "use confirmar_relacion para una confirmación humana"
            )
        with bloqueo_sesion(self.ruta.parent, "obras_destinos"):
            obras, relaciones = self._leer()
            cliente = self._cliente_activo(cliente_id)
            clave = normalizar_nombre_obra(_obligatorio(nombre_obra, "nombre_obra"))
            compatibles = [
                o for o in obras
                if o.estado_vigencia == EstadoVigencia.ACTIVO.value
                and clave in self._claves_obra(o)
            ]
            if len(compatibles) > 1:
                # Ambigüedad global: el catálogo se abstiene en vez de
                # adivinar cuál de las obras activas es la correcta.
                raise ErrorCatalogoObrasDestinos("obra observada ambigua")
            instante = self._instante_iso()
            if compatibles:
                obra = compatibles[0]
                evidencias = self._agregar_evidencia(obra.evidencias, evidencia)
                aliases = obra.aliases_documentales
                alias = str(alias_documental or "").strip()
                if alias and normalizar_nombre_obra(alias) not in self._claves_obra(obra):
                    aliases = (*aliases, alias)
                estado = obra.estado
                if estado == EstadoObra.OBSERVADA.value and len(evidencias) >= 2:
                    estado = EstadoObra.CANDIDATA.value
                obra_nueva = replace(
                    obra,
                    aliases_documentales=aliases,
                    estado=estado,
                    evidencias=evidencias,
                    fecha_modificacion=instante,
                )
                obras[obras.index(obra)] = obra_nueva
                obra = obra_nueva
            else:
                # cliente_id queda registrado como procedencia informativa
                # (primer observador) -- no vuelve a usarse para filtrar
                # búsquedas futuras de esta obra.
                obra = Obra(
                    obra_id=str(self._generador_id()),
                    cliente_id=cliente.cliente_id,
                    nombre_canonico=str(nombre_obra).strip(),
                    nombre_normalizado=clave,
                    aliases_documentales=(),
                    estado=EstadoObra.OBSERVADA.value,
                    estado_vigencia=EstadoVigencia.ACTIVO.value,
                    evidencias=(evidencia,),
                    fecha_creacion=instante,
                    fecha_modificacion=instante,
                )
                _validar_obra(obra)
                obras.append(obra)

            relacion = None
            if destino_id not in (None, ""):
                # R3.3.1: ya no se exige que destino.cliente_id coincida con
                # el (ex) "cliente de la obra" -- la obra es global, así que
                # esa coherencia dejó de tener sentido. El destino_id sigue
                # validándose como existente y activo en `_destino_activo`.
                destino = self._destino_activo(str(destino_id))
                coincidentes = [
                    r for r in relaciones
                    if r.obra_id == obra.obra_id
                    and r.destino_id == destino.destino_id
                ]
                existentes = [
                    r for r in coincidentes
                    if r.estado not in {
                        EstadoRelacion.RECHAZADA.value,
                        EstadoRelacion.INACTIVA.value,
                    }
                ]
                if len(existentes) > 1:
                    raise ErrorCatalogoObrasDestinos("relación activa duplicada")
                if existentes:
                    relacion = existentes[0]
                    relacion_nueva = replace(
                        relacion,
                        evidencias=self._agregar_evidencia(relacion.evidencias, evidencia),
                        fecha_modificacion=instante,
                    )
                    relaciones[relaciones.index(relacion)] = relacion_nueva
                    relacion = relacion_nueva
                elif coincidentes:
                    # Una observación posterior nunca revoca una decisión
                    # humana ni reactiva una relación inactiva. Se conserva
                    # el estado terminal y se agrega evidencia a su historial.
                    if len(coincidentes) != 1:
                        raise ErrorCatalogoObrasDestinos(
                            "historial terminal ambiguo para obra y destino"
                        )
                    relacion = coincidentes[0]
                    relacion_nueva = replace(
                        relacion,
                        evidencias=self._agregar_evidencia(
                            relacion.evidencias, evidencia
                        ),
                        fecha_modificacion=instante,
                    )
                    relaciones[relaciones.index(relacion)] = relacion_nueva
                    relacion = relacion_nueva
                else:
                    relacion = RelacionObraDestino(
                        relacion_id=str(self._generador_id()),
                        obra_id=obra.obra_id,
                        destino_id=destino.destino_id,
                        estado=EstadoRelacion.PENDIENTE.value,
                        evidencias=(evidencia,),
                        fuente_confirmacion="",
                        confirmado_por="",
                        fecha_confirmacion="",
                        observaciones="",
                        fecha_creacion=instante,
                        fecha_modificacion=instante,
                    )
                    relaciones.append(relacion)
            self._validar_catalogo(obras, relaciones)
            self._escribir(obras, relaciones)
            return ResultadoObservacion(obra, relacion)

    def confirmar_relacion(
        self,
        relacion_id: str,
        *,
        actor: str,
        fuente_confirmacion: str = "CONFIRMACION_HUMANA",
        observaciones: str = "",
        identificador_fuente: str | None = None,
    ) -> RelacionObraDestino:
        actor = _obligatorio(actor, "actor")
        fuente = _obligatorio(fuente_confirmacion, "fuente_confirmacion")
        with bloqueo_sesion(self.ruta.parent, "obras_destinos"):
            obras, relaciones = self._leer()
            relacion = self._relacion(relaciones, relacion_id)
            if relacion.estado != EstadoRelacion.PENDIENTE.value:
                raise ErrorCatalogoObrasDestinos(
                    "sólo una relación PENDIENTE puede confirmarse"
                )
            obra = self._obra(obras, relacion.obra_id)
            if obra.estado not in {
                EstadoObra.OBSERVADA.value,
                EstadoObra.CANDIDATA.value,
                EstadoObra.CONFIRMADA.value,
            } or obra.estado_vigencia != EstadoVigencia.ACTIVO.value:
                raise ErrorCatalogoObrasDestinos(
                    "una obra rechazada o inactiva no puede confirmarse"
                )
            self._cliente_activo(obra.cliente_id)
            self._destino_activo(relacion.destino_id)
            instante = self._instante_iso()
            evidencia = Evidencia(
                tipo=TipoEvidencia.CONFIRMACION_HUMANA.value,
                identificador_fuente=identificador_fuente or relacion.relacion_id,
                referencia_hash="",
                campos_observados={"decision": "CONFIRMADA"},
                fecha=instante,
                actor_proceso=actor,
                resultado=ResultadoEvidencia.SOPORTA.value,
            )
            obra_nueva = replace(
                obra,
                estado=EstadoObra.CONFIRMADA.value,
                evidencias=self._agregar_evidencia(obra.evidencias, evidencia),
                fecha_modificacion=instante,
            )
            obras[obras.index(obra)] = obra_nueva
            nueva = replace(
                relacion,
                estado=EstadoRelacion.CONFIRMADA.value,
                evidencias=self._agregar_evidencia(relacion.evidencias, evidencia),
                fuente_confirmacion=fuente,
                confirmado_por=actor,
                fecha_confirmacion=instante,
                observaciones=str(observaciones or "").strip(),
                fecha_modificacion=instante,
            )
            relaciones[relaciones.index(relacion)] = nueva
            self._validar_catalogo(obras, relaciones)
            self._escribir(obras, relaciones)
            return nueva

    def rechazar_relacion(self, relacion_id: str, *, actor: str, observaciones: str = "") -> RelacionObraDestino:
        return self._decidir_no_confirmada(
            relacion_id, EstadoRelacion.RECHAZADA, actor, observaciones
        )

    def mantener_pendiente(self, relacion_id: str, *, actor: str, observaciones: str = "") -> RelacionObraDestino:
        return self._decidir_no_confirmada(
            relacion_id, EstadoRelacion.PENDIENTE, actor, observaciones
        )

    def resolver_obra_destino_confirmada(
        self, *, cliente_id: str, nombre_obra: str
    ) -> ResolucionObraDestino | None:
        """R3.3.1: la obra se busca GLOBALMENTE por nombre normalizado, sin
        filtrar por `cliente_id` -- una obra confirmada para cualquier
        cliente se reconoce igual para éste. `cliente_id` se sigue
        validando (debe ser un cliente real y activo) porque el llamador
        siempre lo tiene disponible como contexto del documento, pero ya no
        participa en la búsqueda de la obra."""
        obras, relaciones = self._leer()
        self._cliente_activo(cliente_id)  # valida el contexto; no filtra la obra
        clave = normalizar_nombre_obra(nombre_obra)
        candidatas = [
            o for o in obras
            if o.estado == EstadoObra.CONFIRMADA.value
            and o.estado_vigencia == EstadoVigencia.ACTIVO.value
            and clave in self._claves_obra(o)
        ]
        if len(candidatas) != 1:
            return None
        obra = candidatas[0]
        confirmadas = [
            r for r in relaciones
            if r.obra_id == obra.obra_id
            and r.estado == EstadoRelacion.CONFIRMADA.value
            and not any(e.resultado == ResultadoEvidencia.CONTRADICE.value for e in r.evidencias)
        ]
        if any(
            evidencia.resultado == ResultadoEvidencia.CONTRADICE.value
            for evidencia in obra.evidencias
        ):
            return None
        if len(confirmadas) != 1:
            return None
        relacion = confirmadas[0]
        try:
            destino = self._destino_activo(relacion.destino_id)
        except ErrorCatalogoObrasDestinos:
            return None
        return ResolucionObraDestino(obra, relacion, destino)

    def migrar_a_identidad_global(self) -> dict[str, object]:
        """R3.3.1: recertifica el catálogo bajo el modelo de obra global.

        No transforma ningún dato -- `cliente_id` se conserva tal cual en
        cada obra, como procedencia histórica informativa; sólo deja de
        interpretarse como propietario. Es, en esencia, una lectura +
        validación (con la nueva regla de unicidad GLOBAL) + reescritura
        atómica bajo el mismo candado de sesión que usa el resto del
        catálogo -- sirve como checkpoint verificado de que el archivo es
        100% compatible con el código nuevo.

        Se ABSTIENE de escribir (y reporta `migrado: False`) si detecta
        cualquier colisión de nombre/alias normalizado entre obras activas
        de clientes distintos -- una migración no destructiva nunca fusiona
        identidades ambiguas por su cuenta.
        """
        with bloqueo_sesion(self.ruta.parent, "obras_destinos"):
            obras, relaciones = self._leer()
            colisiones = self._colisiones_globales(obras)
            reporte: dict[str, object] = {
                "total_obras": len(obras),
                "total_relaciones": len(relaciones),
                "obra_ids": sorted(o.obra_id for o in obras),
                "colisiones_detectadas": len(colisiones),
                "colisiones": colisiones,
            }
            if colisiones:
                reporte["migrado"] = False
                return reporte
            self._validar_catalogo(obras, relaciones)
            self._escribir(obras, relaciones)
            reporte["migrado"] = True
            return reporte

    def _decidir_no_confirmada(
        self,
        relacion_id: str,
        estado: EstadoRelacion,
        actor: str,
        observaciones: str,
    ) -> RelacionObraDestino:
        actor = _obligatorio(actor, "actor")
        with bloqueo_sesion(self.ruta.parent, "obras_destinos"):
            obras, relaciones = self._leer()
            relacion = self._relacion(relaciones, relacion_id)
            if relacion.estado != EstadoRelacion.PENDIENTE.value:
                raise ErrorCatalogoObrasDestinos(
                    "sólo una relación PENDIENTE admite esta decisión"
                )
            instante = self._instante_iso()
            evidencia = Evidencia(
                tipo=TipoEvidencia.CONFIRMACION_HUMANA.value,
                identificador_fuente=relacion.relacion_id,
                referencia_hash="",
                campos_observados={"decision": estado.value},
                fecha=instante,
                actor_proceso=actor,
                resultado=(
                    ResultadoEvidencia.CONTRADICE.value
                    if estado == EstadoRelacion.RECHAZADA
                    else ResultadoEvidencia.NEUTRAL.value
                ),
            )
            nueva = replace(
                relacion,
                estado=estado.value,
                evidencias=self._agregar_evidencia(relacion.evidencias, evidencia),
                fuente_confirmacion="",
                confirmado_por="",
                fecha_confirmacion="",
                observaciones=str(observaciones or "").strip(),
                fecha_modificacion=instante,
            )
            relaciones[relaciones.index(relacion)] = nueva
            self._validar_catalogo(obras, relaciones)
            self._escribir(obras, relaciones)
            return nueva

    def _leer(self) -> tuple[list[Obra], list[RelacionObraDestino]]:
        if not self.ruta.exists():
            return [], []
        try:
            contenido = json.loads(self.ruta.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise CatalogoObrasDestinosCorruptoError(
                f"No se pudo leer el catálogo: {error}"
            ) from error
        if not isinstance(contenido, dict) or set(contenido) != {
            "version_formato", "obras", "relaciones"
        }:
            raise CatalogoObrasDestinosCorruptoError("raíz de catálogo incompatible")
        if contenido.get("version_formato") != VERSION_FORMATO:
            raise CatalogoObrasDestinosCorruptoError("versión de formato desconocida")
        if not isinstance(contenido.get("obras"), list) or not isinstance(
            contenido.get("relaciones"), list
        ):
            raise CatalogoObrasDestinosCorruptoError("obras y relaciones deben ser listas")
        obras = [Obra.desde_dict(o) for o in contenido["obras"]]
        relaciones = [RelacionObraDestino.desde_dict(r) for r in contenido["relaciones"]]
        self._validar_catalogo(obras, relaciones, corrupto=True)
        return obras, relaciones

    def _validar_catalogo(
        self,
        obras: Iterable[Obra],
        relaciones: Iterable[RelacionObraDestino],
        *,
        corrupto: bool = False,
    ) -> None:
        try:
            obras = list(obras)
            relaciones = list(relaciones)
            if len({o.obra_id for o in obras}) != len(obras):
                raise ErrorCatalogoObrasDestinos("IDs de obra duplicados")
            if len({r.relacion_id for r in relaciones}) != len(relaciones):
                raise ErrorCatalogoObrasDestinos("IDs de relación duplicados")
            clientes = {c.cliente_id for c in CatalogoClientes(self.ruta_clientes).listar()}
            destinos = {d.destino_id for d in CatalogoDestinos(
                self.ruta_destinos, ruta_clientes=self.ruta_clientes
            ).listar()}
            ids_obras = {o.obra_id for o in obras}
            for obra in obras:
                _validar_obra(obra)
                # cliente_id es opcional (R3.3.1); si está presente, debe
                # seguir siendo un cliente real -- pero su ausencia ya no es
                # un error, porque la obra no depende de él para existir.
                if obra.cliente_id and obra.cliente_id not in clientes:
                    raise ErrorCatalogoObrasDestinos("obra referencia cliente inexistente")
            activas: set[tuple[str, str]] = set()
            for relacion in relaciones:
                _validar_relacion(relacion)
                if relacion.obra_id not in ids_obras:
                    raise ErrorCatalogoObrasDestinos("relación referencia obra inexistente")
                if relacion.destino_id not in destinos:
                    raise ErrorCatalogoObrasDestinos("relación referencia destino inexistente")
                # R3.3.1: la obra ya no "pertenece" a un cliente, así que la
                # validez de la relación obra<->destino ya no depende de qué
                # cliente compró el material -- sólo de que ambos existan y
                # estén activos (ya verificado arriba). El destino conserva
                # su propio cliente_id (es un lugar físico registrado para
                # ese cliente); eso es independiente de la identidad global
                # de la obra.
                if relacion.estado not in {
                    EstadoRelacion.RECHAZADA.value, EstadoRelacion.INACTIVA.value
                }:
                    clave = (relacion.obra_id, relacion.destino_id)
                    if clave in activas:
                        raise ErrorCatalogoObrasDestinos("relación activa duplicada")
                    activas.add(clave)
        except ErrorCatalogoObrasDestinos as error:
            if corrupto:
                raise CatalogoObrasDestinosCorruptoError(str(error)) from error
            raise

    def _escribir(self, obras: Iterable[Obra], relaciones: Iterable[RelacionObraDestino]) -> None:
        escribir_json_atomico(
            self.ruta,
            {
                "version_formato": VERSION_FORMATO,
                "obras": [o.a_dict() for o in obras],
                "relaciones": [r.a_dict() for r in relaciones],
            },
        )

    def _cliente_activo(self, cliente_id: str):
        try:
            cliente = CatalogoClientes(self.ruta_clientes).obtener(cliente_id)
        except Exception as error:
            raise ErrorCatalogoObrasDestinos("cliente_id inexistente") from error
        if cliente.estado_vigencia != "ACTIVO":
            raise ErrorCatalogoObrasDestinos("cliente_id inactivo")
        return cliente

    def _destino_activo(self, destino_id: str):
        try:
            destino = CatalogoDestinos(
                self.ruta_destinos, ruta_clientes=self.ruta_clientes
            ).obtener(destino_id)
        except Exception as error:
            raise ErrorCatalogoObrasDestinos("destino_id inexistente") from error
        if destino.estado_vigencia != "ACTIVO":
            raise ErrorCatalogoObrasDestinos("destino_id inactivo")
        return destino

    @staticmethod
    def _claves_obra(obra: Obra) -> set[str]:
        return {
            normalizar_nombre_obra(x)
            for x in (obra.nombre_canonico, *obra.aliases_documentales)
        }

    @classmethod
    def _colisiones_globales(cls, obras: Iterable[Obra]) -> dict[str, list[str]]:
        """R3.3.1: detecta (sin lanzar) nombres/alias normalizados que
        coinciden entre DOS O MÁS obras activas -- comparación exacta
        normalizada, sin fuzzy. No se usa para bloquear lecturas normales
        (el catálogo real de hoy no tiene ninguna), sólo como preflight de
        `migrar_a_identidad_global` -- una migración no destructiva nunca
        fusiona automáticamente una ambigüedad así detectada."""
        por_clave: dict[str, set[str]] = {}
        for obra in obras:
            if obra.estado_vigencia != EstadoVigencia.ACTIVO.value:
                continue
            for clave in cls._claves_obra(obra):
                por_clave.setdefault(clave, set()).add(obra.obra_id)
        return {
            clave: sorted(ids) for clave, ids in por_clave.items() if len(ids) > 1
        }

    @staticmethod
    def _agregar_evidencia(
        existentes: tuple[Evidencia, ...], nueva: Evidencia
    ) -> tuple[Evidencia, ...]:
        return existentes if nueva in existentes else (*existentes, nueva)

    @staticmethod
    def _obra(obras: Iterable[Obra], obra_id: str) -> Obra:
        for obra in obras:
            if obra.obra_id == str(obra_id).strip():
                return obra
        raise ObraNoEncontradaError("obra inexistente")

    @staticmethod
    def _relacion(
        relaciones: Iterable[RelacionObraDestino], relacion_id: str
    ) -> RelacionObraDestino:
        for relacion in relaciones:
            if relacion.relacion_id == str(relacion_id).strip():
                return relacion
        raise RelacionNoEncontradaError("relación inexistente")

    def _instante_iso(self) -> str:
        instante = self._reloj()
        if instante.tzinfo is None:
            instante = instante.replace(tzinfo=timezone.utc)
        return instante.astimezone(timezone.utc).isoformat()
