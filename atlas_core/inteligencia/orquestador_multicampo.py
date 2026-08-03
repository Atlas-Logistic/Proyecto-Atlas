"""Orquestación reutilizable y aislada del Motor Multicampo en modo sombra."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Callable, Iterable, Mapping

from atlas_core.inteligencia.contrato_multicampo import EstadoResolucion


ResolverMulticampo = Callable[..., object]


@dataclass(frozen=True)
class SolicitudResolucionSombra:
    """Invocación ya preparada de un resolver existente.

    El orquestador no conoce catálogos, políticas ni firmas particulares:
    cada solicitud conserva esa responsabilidad en el resolver de origen.
    """

    campo: str
    resolver: ResolverMulticampo
    argumentos: tuple[object, ...] = ()
    opciones: Mapping[str, object] = field(default_factory=dict)
    resumidor: Callable[[str, object], "ResumenResolucionSombra"] | None = None

    def __post_init__(self) -> None:
        campo = str(self.campo).strip()
        if not campo:
            raise ValueError("campo de resolución vacío")
        if not callable(self.resolver):
            raise TypeError("resolver debe ser invocable")
        if self.resumidor is not None and not callable(self.resumidor):
            raise TypeError("resumidor debe ser invocable")
        object.__setattr__(self, "campo", campo)
        object.__setattr__(self, "argumentos", tuple(self.argumentos))
        object.__setattr__(
            self, "opciones", MappingProxyType(dict(self.opciones))
        )


@dataclass(frozen=True)
class ResumenResolucionSombra:
    campo: str
    estado: EstadoResolucion
    confianza: float
    requiere_revision: bool
    cantidad_contradicciones: int

    def __post_init__(self) -> None:
        if not 0.0 <= self.confianza <= 1.0:
            raise ValueError("confianza fuera de rango")


@dataclass(frozen=True)
class FalloResolucionSombra:
    campo: str
    tipo_error: str


@dataclass(frozen=True)
class ResultadoOrquestacionSombra:
    """Resultados crudos más una vista común, sin proyectar a producción."""

    resultados: Mapping[str, object]
    resumenes: Mapping[str, ResumenResolucionSombra]
    fallos: Mapping[str, FalloResolucionSombra]
    orden_ejecucion: tuple[str, ...]
    modo: str = "SOMBRA"
    version: str = "orquestador-multicampo-fase1"

    def __post_init__(self) -> None:
        if self.modo != "SOMBRA":
            raise ValueError("la fase 1 solo admite modo SOMBRA")
        object.__setattr__(
            self, "resultados", MappingProxyType(dict(self.resultados))
        )
        object.__setattr__(
            self, "resumenes", MappingProxyType(dict(self.resumenes))
        )
        object.__setattr__(self, "fallos", MappingProxyType(dict(self.fallos)))
        object.__setattr__(self, "orden_ejecucion", tuple(self.orden_ejecucion))

    @property
    def completo(self) -> bool:
        return not self.fallos

    @property
    def requiere_revision(self) -> bool:
        return bool(self.fallos) or any(
            resumen.requiere_revision for resumen in self.resumenes.values()
        )


class OrquestadorMulticampoSombra:
    """Ejecuta resolvers independientes sin decidir ni publicar valores."""

    version = "orquestador-multicampo-fase1"

    def ejecutar(
        self, solicitudes: Iterable[SolicitudResolucionSombra]
    ) -> ResultadoOrquestacionSombra:
        preparadas = tuple(solicitudes)
        nombres = tuple(solicitud.campo for solicitud in preparadas)
        if len(set(nombres)) != len(nombres):
            raise ValueError("cada campo puede aparecer una sola vez")

        resultados: dict[str, object] = {}
        resumenes: dict[str, ResumenResolucionSombra] = {}
        fallos: dict[str, FalloResolucionSombra] = {}
        for solicitud in preparadas:
            try:
                resultado = solicitud.resolver(
                    *solicitud.argumentos, **solicitud.opciones
                )
                resumen = (solicitud.resumidor or _resumir)(
                    solicitud.campo, resultado
                )
                if not isinstance(resumen, ResumenResolucionSombra):
                    raise TypeError(
                        "resumidor debe devolver ResumenResolucionSombra"
                    )
                if resumen.campo != solicitud.campo:
                    raise ValueError(
                        "el campo del resumen no coincide con la solicitud"
                    )
            except Exception as error:  # Aislamiento obligatorio del modo sombra.
                fallos[solicitud.campo] = FalloResolucionSombra(
                    solicitud.campo, type(error).__name__
                )
                continue
            resultados[solicitud.campo] = resultado
            resumenes[solicitud.campo] = resumen

        return ResultadoOrquestacionSombra(
            resultados=resultados,
            resumenes=resumenes,
            fallos=fallos,
            orden_ejecucion=nombres,
            version=self.version,
        )


def orquestar_multicampo_sombra(
    solicitudes: Iterable[SolicitudResolucionSombra],
) -> ResultadoOrquestacionSombra:
    """Fachada funcional de la fase 1."""
    return OrquestadorMulticampoSombra().ejecutar(solicitudes)


def _resumir(campo: str, resultado: object) -> ResumenResolucionSombra:
    estado = getattr(resultado, "estado", None)
    if estado is None:
        estado = getattr(resultado, "estado_resolucion", None)
    if not isinstance(estado, EstadoResolucion):
        raise TypeError("el resolver no devolvió un estado multicampo válido")

    confianza = float(getattr(resultado, "confianza"))
    requiere_revision = getattr(resultado, "requiere_revision_humana", None)
    if requiere_revision is None:
        requiere_revision = getattr(resultado, "requiere_revision", None)
    if not isinstance(requiere_revision, bool):
        raise TypeError("el resolver no devolvió el indicador de revisión")

    contradicciones = getattr(resultado, "contradicciones", ())
    try:
        cantidad_contradicciones = len(contradicciones)
    except TypeError as error:
        raise TypeError("contradicciones debe ser una colección") from error
    return ResumenResolucionSombra(
        campo=campo,
        estado=estado,
        confianza=confianza,
        requiere_revision=requiere_revision,
        cantidad_contradicciones=cantidad_contradicciones,
    )
