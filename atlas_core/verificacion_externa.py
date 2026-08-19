"""Verificación externa de entidades -- interfaz general (Protocol) para
consultar fuentes fuera de Atlas (registros públicos, sitios corporativos,
directorios empresariales) y corroborar identidad de clientes/obras. Nunca
LLM, nunca IA generativa: la fuente devuelve datos estructurados, Atlas los
combina con el resto de la evidencia usando `atlas_core.motor_evidencia`.

Este módulo define el CONTRATO, no una integración acoplada a un buscador
concreto (nunca "si Google" / "si Bing"): cualquier proveedor real
(API de un registro oficial, un servicio de búsqueda, un directorio con
API propia) implementa `ProveedorVerificacionEntidades` y listo.

Estado real de este bloque (ver `docs/BITACORA_TECNICA_CRONOLOGICA.md` para
el detalle): el entorno de desarrollo SÍ tiene salida de red (HTTP directo
funciona), pero el código de producción NO tiene hoy ningún proveedor de
búsqueda configurado (sin API key/servicio de registro empresarial
contratado) -- por eso `ProveedorVerificacionFijo` (fixtures/caché, sin red)
es el único proveedor que corre en la suite y en producción por ahora. Las
2 evidencias reales usadas en el caso SIGRO de este bloque se obtuvieron
con las herramientas de búsqueda del propio agente (fuera del proceso
Python) y se guardaron como fixture real -- nunca inventadas -- para poder
auditarlas y para dejar el contrato ya probado contra un caso genuino.
Falta, para producción real y autónoma: contratar/configurar un proveedor
de búsqueda o de registro empresarial oficial (p.ej. una API del SII o un
directorio con API), inyectarlo detrás de esta misma interfaz."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

# Jerarquía de fuentes externas, de mayor a menor confianza -- ver
# `atlas_core.motor_evidencia` para cómo se combinan con el resto de los
# niveles de evidencia (nunca "más fuentes débiles" le gana a una fuente
# oficial).
TIPO_FUENTE_OFICIAL = "OFICIAL"  # registro público (p.ej. SII, registro de empresas)
TIPO_FUENTE_CORPORATIVO = "CORPORATIVO"  # sitio web propio de la entidad
TIPO_FUENTE_DIRECTORIO = "DIRECTORIO"  # directorio empresarial de alta confianza
TIPO_FUENTE_AUXILIAR = "AUXILIAR"  # cualquier otra fuente -- nunca decide sola

TIPOS_FUENTE_VALIDOS = (
    TIPO_FUENTE_OFICIAL, TIPO_FUENTE_CORPORATIVO, TIPO_FUENTE_DIRECTORIO, TIPO_FUENTE_AUXILIAR,
)


@dataclass(frozen=True)
class EvidenciaExterna:
    """Un resultado estructurado de una fuente externa -- siempre
    trazable: de dónde vino, cuándo se consultó y qué corrobora
    exactamente. Nunca se almacena contenido web masivo, sólo los campos
    ya extraídos que importan para la identidad de la entidad."""

    fuente: str  # nombre/dominio de la fuente, p.ej. "web.sigro.cl"
    tipo_fuente: str
    url: str
    fecha_consulta: str  # ISO 8601 con zona horaria
    razon_social: str = ""
    rut: str = ""
    direccion: str = ""
    comuna: str = ""
    campos_corroborados: tuple[str, ...] = ()
    contradicciones: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.tipo_fuente not in TIPOS_FUENTE_VALIDOS:
            raise ValueError(f"tipo_fuente no soportado: {self.tipo_fuente!r}")

    def a_dict(self) -> dict[str, object]:
        return {
            "fuente": self.fuente, "tipo_fuente": self.tipo_fuente, "url": self.url,
            "fecha_consulta": self.fecha_consulta, "razon_social": self.razon_social,
            "rut": self.rut, "direccion": self.direccion, "comuna": self.comuna,
            "campos_corroborados": list(self.campos_corroborados),
            "contradicciones": list(self.contradicciones),
        }

    @classmethod
    def desde_dict(cls, datos: dict[str, object]) -> "EvidenciaExterna":
        return cls(
            fuente=str(datos.get("fuente", "")), tipo_fuente=str(datos.get("tipo_fuente", "")),
            url=str(datos.get("url", "")), fecha_consulta=str(datos.get("fecha_consulta", "")),
            razon_social=str(datos.get("razon_social", "")), rut=str(datos.get("rut", "")),
            direccion=str(datos.get("direccion", "")), comuna=str(datos.get("comuna", "")),
            campos_corroborados=tuple(datos.get("campos_corroborados") or ()),
            contradicciones=tuple(datos.get("contradicciones") or ()),
        )


class ProveedorVerificacionEntidades(Protocol):
    """Contrato que debe cumplir cualquier proveedor real de verificación
    externa. `consultar` NUNCA debe lanzar por falta de resultados -- una
    búsqueda sin hallazgos devuelve una tupla vacía, nunca `None` ni
    excepción (la ausencia de evidencia externa es, en sí misma, un dato:
    ver CASO del "Supermercado Señor de los Milagros" en la bitácora
    técnica, donde la ausencia de corroboración fue justamente la señal
    relevante)."""

    def consultar(self, *, razon_social: str, rut: str = "", direccion: str = "") -> tuple[EvidenciaExterna, ...]:
        ...


class ProveedorVerificacionFijo:
    """Proveedor determinista basado en resultados ya capturados (fixtures
    de test, o evidencia real guardada de una consulta puntual del
    agente) -- nunca hace red. Es el único proveedor que corre hoy en
    producción y en la suite; ver docstring del módulo."""

    def __init__(self, resultados: dict[str, tuple[EvidenciaExterna, ...]]) -> None:
        # Clave: razón social documental normalizada por el llamador (no
        # se normaliza aquí -- este proveedor es deliberadamente ciego a
        # reglas de negocio, sólo devuelve lo que ya tiene guardado).
        self._resultados = dict(resultados)

    def consultar(self, *, razon_social: str, rut: str = "", direccion: str = "") -> tuple[EvidenciaExterna, ...]:
        return self._resultados.get(razon_social, ())


@dataclass
class CacheVerificacionExterna:
    """Caché simple en memoria (persistible como dict JSON) para evitar
    reconsultar una entidad ya corroborada externamente. Ver FASE 12 de
    este bloque: una entidad ya confirmada internamente no debería volver
    a golpear una fuente externa salvo evidencia nueva/contradicción."""

    entradas: dict[str, dict[str, object]] = field(default_factory=dict)

    def obtener(self, clave: str) -> tuple[EvidenciaExterna, ...] | None:
        entrada = self.entradas.get(clave)
        if entrada is None:
            return None
        return tuple(EvidenciaExterna.desde_dict(d) for d in entrada.get("evidencias", []))

    def guardar(self, clave: str, evidencias: tuple[EvidenciaExterna, ...], *, fecha: str) -> None:
        self.entradas[clave] = {
            "fecha_guardado": fecha,
            "evidencias": [e.a_dict() for e in evidencias],
        }

    def a_dict(self) -> dict[str, object]:
        return {"version": 1, "entradas": self.entradas}

    @classmethod
    def desde_dict(cls, datos: dict[str, object]) -> "CacheVerificacionExterna":
        return cls(entradas=dict(datos.get("entradas") or {}))
