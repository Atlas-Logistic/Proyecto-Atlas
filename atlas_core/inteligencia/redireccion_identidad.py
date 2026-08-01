"""Contrato append-only para migrar IDs sin destruir referencias históricas."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class TipoRedireccionIdentidad(str, Enum):
    MIGRADA = "MIGRADA"
    REDIRIGIDA = "REDIRIGIDA"


@dataclass(frozen=True)
class EventoRedireccionIdentidad:
    evento_id: str
    id_anterior: str
    id_canonico_nuevo: str
    tipo: TipoRedireccionIdentidad
    fecha: datetime
    motivo: str
    decision_humana_id: str
    revierte_evento_id: str = ""

    def __post_init__(self) -> None:
        if not all((
            self.evento_id.strip(), self.id_anterior.strip(),
            self.id_canonico_nuevo.strip(), self.motivo.strip(),
            self.decision_humana_id.strip(),
        )):
            raise ValueError("el evento de redirección tiene campos obligatorios vacíos")
        if self.id_anterior == self.id_canonico_nuevo:
            raise ValueError("una identidad no puede redirigirse a sí misma")
        if self.fecha.tzinfo is None:
            raise ValueError("la fecha debe incluir zona horaria")


@dataclass(frozen=True)
class HistorialRedireccionesIdentidad:
    eventos: tuple[EventoRedireccionIdentidad, ...] = ()

    def agregar(
        self, evento: EventoRedireccionIdentidad
    ) -> "HistorialRedireccionesIdentidad":
        if any(item.evento_id == evento.evento_id for item in self.eventos):
            raise ValueError("evento_id duplicado")
        if evento.revierte_evento_id and not any(
            item.evento_id == evento.revierte_evento_id for item in self.eventos
        ):
            raise ValueError("el evento a revertir no existe")
        candidato = HistorialRedireccionesIdentidad(self.eventos + (evento,))
        candidato._mapa_activo()
        return candidato

    def _mapa_activo(self) -> dict[str, str]:
        revertidos = {
            evento.revierte_evento_id
            for evento in self.eventos if evento.revierte_evento_id
        }
        mapa: dict[str, str] = {}
        for evento in self.eventos:
            if evento.evento_id in revertidos:
                continue
            if evento.id_anterior in mapa:
                raise ValueError("existe más de una redirección activa para el mismo ID")
            mapa[evento.id_anterior] = evento.id_canonico_nuevo
        for origen in sorted(mapa):
            vistos: set[str] = set()
            actual = origen
            while actual in mapa:
                if actual in vistos:
                    raise ValueError("ciclo de redirecciones detectado")
                vistos.add(actual)
                actual = mapa[actual]
        return mapa

    def resolver(self, identidad: str) -> str:
        mapa = self._mapa_activo()
        actual = identidad
        while actual in mapa:
            actual = mapa[actual]
        return actual
