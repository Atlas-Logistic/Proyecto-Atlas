"""Incidencias Documentales -- registro auditable de errores atribuibles
al CONTENIDO HUMANO/DOCUMENTAL de una guía (no a la calidad de la imagen
ni a una lectura OCR ambigua). Capacidad transversal: aplica a cualquier
campo documental (cliente, patente, obra, dirección, comuna, chofer,
transportista, fecha/hora, etc.) -- una taxonomía extensible, no cerrada
ni exhaustiva.

Distinción obligatoria y estructuralmente protegida por tests
(`tests/test_incidencias_documentales.py`):

- Incidencia Documental: el documento, leído CORRECTAMENTE por OCR, dice
  algo objetivamente distinto de la realidad operacional (p.ej. el
  mandante escribió el nombre de otra empresa, o una patente que no le
  corresponde a ese vehículo). El error es del CONTENIDO, no de la
  lectura.
- Problema de lectura / calidad documental: la imagen está borrosa,
  manchada, arrugada, mal iluminada, cortada, o el OCR confundió
  caracteres (6/8, D/E, etc.) o no detectó texto. Esto NUNCA se registra
  como Incidencia Documental -- Atlas puede advertirlo y usar otras
  fuentes para recuperar el dato, pero la pestaña de Incidencias
  Documentales es sólo para errores humanos reales del contenido."""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Iterable

from atlas_core.almacenamiento_portable import bloqueo_sesion, escribir_json_atomico

VERSION_FORMATO = 1


class ErrorIncidenciasDocumentales(ValueError):
    """Error base de este almacén."""


class EstadoIncidencia(str, Enum):
    DETECTADA = "DETECTADA"
    CONFIRMADA = "CONFIRMADA"
    DESCARTADA = "DESCARTADA"


# Taxonomía inicial, deliberadamente pequeña y extensible -- nunca
# exhaustiva. `tipo_incidencia` acepta cualquier string; estos son sólo
# los códigos ya conocidos para los campos documentales típicos.
TIPO_PATENTE_DOCUMENTAL_INCORRECTA = "PATENTE_DOCUMENTAL_INCORRECTA"
TIPO_IDENTIDAD_CLIENTE_INCONSISTENTE = "IDENTIDAD_CLIENTE_INCONSISTENTE"
TIPO_RUT_NO_CORRESPONDE_A_RAZON_SOCIAL = "RUT_NO_CORRESPONDE_A_RAZON_SOCIAL"
TIPO_DIRECCION_NO_CORRESPONDE_A_ENTIDAD = "DIRECCION_NO_CORRESPONDE_A_ENTIDAD"
TIPO_OBRA_DOCUMENTAL_INCONSISTENTE = "OBRA_DOCUMENTAL_INCONSISTENTE"
TIPO_COMUNA_DOCUMENTAL_INCORRECTA = "COMUNA_DOCUMENTAL_INCORRECTA"
TIPO_TRANSPORTISTA_DOCUMENTAL_INCORRECTO = "TRANSPORTISTA_DOCUMENTAL_INCORRECTO"
TIPO_HORA_DOCUMENTAL_INCONSISTENTE = "HORA_DOCUMENTAL_INCONSISTENTE"
# Bloque R5 I -- omisión, no contradicción: la guía nunca imprimió el
# número de transporte (la etiqueta "NRO...TRANSPORTE" no aparece en el
# texto OCR, y el documento no está degradado en general -- ver
# `atlas_core.procesamiento_masivo._documento_degradado` /
# `MotivoRevisionDocumento.TRANSPORTE_AUSENTE_SIN_ETIQUETA`). `registrar()`
# exige `valor_documental` != `valor_canonico`, ambos no vacíos -- para una
# ausencia (no hay dos valores que contrastar) se usan los sentinelas fijos
# de abajo, que documentan la ausencia sin fingir un valor documental que
# nunca existió.
TIPO_TRANSPORTE_AUSENTE_DOCUMENTAL = "TRANSPORTE_AUSENTE_DOCUMENTAL"
VALOR_DOCUMENTAL_CAMPO_AUSENTE = "(campo ausente en el documento)"
VALOR_CANONICO_CAMPO_REQUERIDO = "número de transporte requerido, no impreso en la guía"
# Bloque FIX RUT DOCUMENTAL -- el RUT SÍ está impreso en la guía, pero no
# pasa validación estructural (dígito verificador incorrecto, o cuerpo
# implausible como dígitos repetidos -- ver
# `atlas_core.validadores._cuerpo_implausible`; caso real: guía de
# WLADIMIR AGUILAR con "55.555.555-5"). Distinto de
# TIPO_RUT_NO_CORRESPONDE_A_RAZON_SOCIAL (ese es un RUT bien formado que
# le pertenece a otra entidad); acá el RUT en sí es documentalmente
# inválido. Cuando no existe un RUT canónico confiable para sustituirlo
# se usa el sentinela de abajo -- nunca se inventa un valor.
TIPO_RUT_DOCUMENTAL_INVALIDO = "RUT_DOCUMENTAL_INVALIDO"
VALOR_CANONICO_RUT_NO_CONFIRMADO = "RUT canónico no confirmado -- requiere revisión humana"

# Lo que NUNCA es una incidencia documental -- código explícito para que
# el resto del código (y los tests) puedan afirmarlo positivamente, en
# vez de razonar por ausencia.
MOTIVO_PROBLEMA_LECTURA = "PROBLEMA_DE_LECTURA"
MOTIVO_CALIDAD_DOCUMENTAL_O_IMAGEN = "CALIDAD_DOCUMENTAL_O_IMAGEN"
MOTIVOS_NUNCA_INCIDENCIA = (MOTIVO_PROBLEMA_LECTURA, MOTIVO_CALIDAD_DOCUMENTAL_O_IMAGEN)


@dataclass(frozen=True)
class IncidenciaDocumental:
    incidencia_id: str
    contexto: str  # p.ej. razón social/cliente_id del contexto operacional
    numero_guia: str
    numero_transporte: str
    campo: str
    valor_documental: str
    valor_canonico: str
    tipo_incidencia: str
    evidencia: tuple[str, ...]
    fecha_deteccion: str
    estado: str
    fuente_resolucion: str
    actor: str  # "" si la detección fue automática, sin intervención humana puntual
    decision_id: str  # "" si no hay una decisión de bandeja asociada

    def a_dict(self) -> dict[str, object]:
        datos = asdict(self)
        datos["evidencia"] = list(self.evidencia)
        return datos

    @classmethod
    def desde_dict(cls, datos: dict[str, object]) -> "IncidenciaDocumental":
        campos = set(cls.__dataclass_fields__)
        faltantes = campos - set(datos)
        if faltantes:
            raise ErrorIncidenciasDocumentales(f"incidencia incompleta, faltan: {sorted(faltantes)}")
        valores = dict(datos)
        valores["evidencia"] = tuple(valores.get("evidencia") or ())
        return cls(**{campo: valores[campo] if campo == "evidencia" else str(valores[campo]) for campo in campos})


def _id_incidencia(*, numero_guia: str, campo: str, valor_documental: str, valor_canonico: str) -> str:
    base = "|".join([numero_guia, campo, valor_documental, valor_canonico])
    return hashlib.sha256(base.encode("utf-8")).hexdigest()


class AlmacenIncidenciasDocumentales:
    """Persistencia atómica -- mismo patrón que
    `atlas_core.evidencia_entidades.AlmacenEvidenciaEntidades`."""

    def __init__(self, ruta: str | Path) -> None:
        self.ruta = Path(ruta)

    def listar(self, *, estado: str | None = None) -> list[IncidenciaDocumental]:
        incidencias = self._leer()
        if estado is not None:
            incidencias = [i for i in incidencias if i.estado == estado]
        return incidencias

    def registrar(
        self, *, contexto: str, numero_guia: str, numero_transporte: str, campo: str,
        valor_documental: str, valor_canonico: str, tipo_incidencia: str,
        evidencia: Iterable[str], fecha: datetime, estado: EstadoIncidencia | str = EstadoIncidencia.DETECTADA,
        fuente_resolucion: str = "", actor: str = "", decision_id: str = "",
    ) -> IncidenciaDocumental:
        if tipo_incidencia.strip() in MOTIVOS_NUNCA_INCIDENCIA:
            raise ErrorIncidenciasDocumentales(
                f"{tipo_incidencia!r} es un problema de lectura/calidad documental, "
                "nunca una Incidencia Documental -- ver docstring del módulo"
            )
        if not valor_documental.strip():
            raise ErrorIncidenciasDocumentales("valor_documental obligatorio")
        if not valor_canonico.strip():
            raise ErrorIncidenciasDocumentales("valor_canonico obligatorio")
        if valor_documental.strip() == valor_canonico.strip():
            raise ErrorIncidenciasDocumentales(
                "valor_documental y valor_canonico son iguales -- no hay incidencia que registrar"
            )
        if fecha.tzinfo is None:
            raise ErrorIncidenciasDocumentales("fecha debe incluir zona horaria")
        incidencia = IncidenciaDocumental(
            incidencia_id=_id_incidencia(
                numero_guia=numero_guia, campo=campo,
                valor_documental=valor_documental, valor_canonico=valor_canonico,
            ),
            contexto=contexto.strip(), numero_guia=str(numero_guia), numero_transporte=str(numero_transporte),
            campo=campo.strip(), valor_documental=valor_documental.strip(), valor_canonico=valor_canonico.strip(),
            tipo_incidencia=tipo_incidencia.strip(), evidencia=tuple(evidencia),
            fecha_deteccion=fecha.astimezone(timezone.utc).isoformat(),
            estado=EstadoIncidencia(estado).value, fuente_resolucion=fuente_resolucion.strip(),
            actor=actor.strip(), decision_id=decision_id.strip(),
        )
        with bloqueo_sesion(self.ruta.parent, "incidencias_documentales"):
            incidencias = self._leer()
            existente = next((i for i in incidencias if i.incidencia_id == incidencia.incidencia_id), None)
            if existente is None:
                incidencias.append(incidencia)
                self._escribir(incidencias)
                return incidencia
            return existente  # idempotente: la misma incidencia no se duplica

    def _leer(self) -> list[IncidenciaDocumental]:
        if not self.ruta.exists():
            return []
        try:
            with self.ruta.open("r", encoding="utf-8") as archivo:
                contenido = json.load(archivo)
        except (OSError, json.JSONDecodeError) as error:
            raise ErrorIncidenciasDocumentales(f"no se pudo leer el almacén: {error}") from error
        if not isinstance(contenido, dict) or contenido.get("version_formato") != VERSION_FORMATO:
            raise ErrorIncidenciasDocumentales("versión de formato incompatible")
        registros = contenido.get("incidencias")
        if not isinstance(registros, list):
            raise ErrorIncidenciasDocumentales("incidencias debe ser una lista")
        return [IncidenciaDocumental.desde_dict(r) for r in registros]

    def _escribir(self, incidencias: Iterable[IncidenciaDocumental]) -> None:
        contenido = {
            "version_formato": VERSION_FORMATO,
            "incidencias": [i.a_dict() for i in incidencias],
        }
        escribir_json_atomico(self.ruta, contenido)
