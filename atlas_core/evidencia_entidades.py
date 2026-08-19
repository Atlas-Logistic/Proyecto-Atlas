"""Evidencia extendida de entidades (clientes/obras) -- confirmaciones
humanas de identidad y evidencia externa corroborada, en un almacén
NUEVO y ADITIVO (`catalogos_privados/evidencia_entidades.json`), separado
de `clientes.json`/`obras_destinos.json`.

Por qué un archivo nuevo y no extender `Cliente`/`Obra`: ambos dataclasses
validan el conjunto EXACTO de campos (`set(datos) != campos` en
`Cliente.desde_dict`, patrón equivalente en obras) -- agregar un campo ahí
exigiría una migración real de esos catálogos en producción. En cambio,
`vehiculos.json` ya tiene un punto de extensión libre
(`campos_observados: dict`), por eso el motor de vehículos no necesitó un
archivo nuevo. Este módulo replica esa misma idea (aditivo, sin migración)
pero como almacén independiente, ya que clientes/obras no tienen ese punto
de extensión hoy.

Concepto central -- CONFIRMACIONES_INDEPENDIENTES: cuando un humano
confirma la misma relación (valor_documental -> valor_confirmado, para el
mismo contexto de identidad) en transportes DISTINTOS, cada confirmación
cuenta. Nunca se cuenta dos veces la misma confirmación ni dos documentos
del mismo transporte -- exactamente el mismo principio "repetición no
equivale a independencia" ya validado en producción para vehículos
(`atlas_core.decisiones_pendientes._transportes_por_patente_de_chofer`)."""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from atlas_core.almacenamiento_portable import bloqueo_sesion, escribir_json_atomico

VERSION_FORMATO = 1

# Umbral de confirmaciones independientes para que Atlas deje de volver a
# preguntar lo mismo (ver docstring del módulo y FASE de "aprendizaje
# operacional" de este bloque). Vive aquí, como una única constante
# nombrada -- nunca repetido como un número mágico dentro de la lógica.
UMBRAL_CONFIRMACIONES_PARA_CONOCIMIENTO_FUERTE = 2


class ErrorEvidenciaEntidades(ValueError):
    """Error base de este almacén."""


@dataclass(frozen=True)
class ConfirmacionIdentidad:
    """Una confirmación humana puntual de que, en el contexto dado (p.ej.
    un RUT documental concreto), el valor documental leído corresponde al
    valor canónico confirmado. `contexto_clave` es deliberadamente
    genérico (nunca "RUT de cliente" hardcodeado) para poder reutilizarse
    con otros dominios (obras, destinos) más adelante."""

    confirmacion_id: str
    dominio: str  # "CLIENTE" | "OBRA" | ... -- extensible, nunca cerrado
    contexto_clave: str
    valor_documental: str
    valor_confirmado: str
    identificador_confirmado: str  # cliente_id/obra_id si ya existe, o "" si es alta nueva
    numero_guia: str
    numero_transporte: str
    actor: str
    fecha: str
    fuente_decision: str

    def a_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def desde_dict(cls, datos: dict[str, object]) -> "ConfirmacionIdentidad":
        campos = set(cls.__dataclass_fields__)
        faltantes = campos - set(datos)
        if faltantes:
            raise ErrorEvidenciaEntidades(f"confirmación incompleta, faltan: {sorted(faltantes)}")
        return cls(**{campo: str(datos[campo]) for campo in campos})


def _id_confirmacion(*, dominio: str, contexto_clave: str, valor_documental: str, numero_guia: str, numero_transporte: str) -> str:
    base = "|".join([dominio, contexto_clave, valor_documental, numero_guia, numero_transporte])
    return hashlib.sha256(base.encode("utf-8")).hexdigest()


class AlmacenEvidenciaEntidades:
    """Persistencia atómica del almacén de confirmaciones -- mismo patrón
    de bloqueo/escritura ya usado por `catalogo_vehiculos.confirmar_vehiculo`."""

    def __init__(self, ruta: str | Path) -> None:
        self.ruta = Path(ruta)

    def listar(self) -> list[ConfirmacionIdentidad]:
        return self._leer()

    def registrar_confirmacion(
        self, *, dominio: str, contexto_clave: str, valor_documental: str, valor_confirmado: str,
        identificador_confirmado: str = "", numero_guia: str, numero_transporte: str,
        actor: str, fuente_decision: str, fecha: datetime,
    ) -> ConfirmacionIdentidad:
        if not actor.strip():
            raise ErrorEvidenciaEntidades("actor obligatorio")
        if not contexto_clave.strip():
            raise ErrorEvidenciaEntidades("contexto_clave obligatorio")
        if fecha.tzinfo is None:
            raise ErrorEvidenciaEntidades("fecha debe incluir zona horaria")
        confirmacion = ConfirmacionIdentidad(
            confirmacion_id=_id_confirmacion(
                dominio=dominio, contexto_clave=contexto_clave, valor_documental=valor_documental,
                numero_guia=numero_guia, numero_transporte=numero_transporte,
            ),
            dominio=dominio, contexto_clave=contexto_clave.strip(),
            valor_documental=valor_documental.strip(), valor_confirmado=valor_confirmado.strip(),
            identificador_confirmado=identificador_confirmado.strip(),
            numero_guia=str(numero_guia), numero_transporte=str(numero_transporte),
            actor=actor.strip(), fecha=fecha.astimezone(timezone.utc).isoformat(),
            fuente_decision=fuente_decision.strip(),
        )
        with bloqueo_sesion(self.ruta.parent, "evidencia_entidades"):
            confirmaciones = self._leer()
            # Idempotente: la misma confirmación (mismo id determinista)
            # no se duplica -- registrar dos veces la misma cosa nunca
            # debe contar como dos confirmaciones independientes.
            if not any(c.confirmacion_id == confirmacion.confirmacion_id for c in confirmaciones):
                confirmaciones.append(confirmacion)
                self._escribir(confirmaciones)
        return confirmacion

    def confirmaciones_para(self, *, dominio: str, contexto_clave: str, valor_confirmado: str = "") -> list[ConfirmacionIdentidad]:
        resultado = [
            c for c in self._leer()
            if c.dominio == dominio and c.contexto_clave == contexto_clave
        ]
        if valor_confirmado:
            resultado = [c for c in resultado if c.valor_confirmado == valor_confirmado]
        return resultado

    def _leer(self) -> list[ConfirmacionIdentidad]:
        if not self.ruta.exists():
            return []
        try:
            with self.ruta.open("r", encoding="utf-8") as archivo:
                contenido = json.load(archivo)
        except (OSError, json.JSONDecodeError) as error:
            raise ErrorEvidenciaEntidades(f"no se pudo leer el almacén: {error}") from error
        if not isinstance(contenido, dict) or contenido.get("version_formato") != VERSION_FORMATO:
            raise ErrorEvidenciaEntidades("versión de formato incompatible")
        registros = contenido.get("confirmaciones")
        if not isinstance(registros, list):
            raise ErrorEvidenciaEntidades("confirmaciones debe ser una lista")
        return [ConfirmacionIdentidad.desde_dict(r) for r in registros]

    def _escribir(self, confirmaciones: Iterable[ConfirmacionIdentidad]) -> None:
        contenido = {
            "version_formato": VERSION_FORMATO,
            "confirmaciones": [c.a_dict() for c in confirmaciones],
        }
        escribir_json_atomico(self.ruta, contenido)


def transportes_independientes(confirmaciones: Iterable[ConfirmacionIdentidad]) -> int:
    """Cuenta transportes DISTINTOS entre las confirmaciones dadas --
    nunca documentos. Mismo principio que en vehículos: 3 confirmaciones
    del mismo transporte cuentan como 1, no como 3."""
    return len({c.numero_transporte for c in confirmaciones if c.numero_transporte})
