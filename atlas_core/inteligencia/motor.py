"""Resolución reproducible por evidencias estructuradas."""

from __future__ import annotations

import unicodedata
from collections import defaultdict
from typing import Iterable, Mapping

from atlas_core.inteligencia.modelos import (
    Contradiccion,
    EstadoPropuesta,
    Evidencia,
    NivelConfianza,
    Propuesta,
    TipoFuente,
)
from atlas_core.inteligencia.politicas import PoliticaResolucion, obtener_politica


def normalizar(valor: object) -> str:
    texto = " ".join(str(valor or "").strip().upper().split())
    descompuesto = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in descompuesto if not unicodedata.combining(c))


def _identidad(evidencia: Evidencia) -> tuple[object, ...]:
    return (
        evidencia.valor_normalizado,
        evidencia.tipo_fuente,
        evidencia.fuente,
        evidencia.documento_origen,
        evidencia.referencia,
    )


class MotorResolucion:
    def resolver(
        self,
        campo: str,
        valor_original: str,
        evidencias: Iterable[Evidencia],
        politica: PoliticaResolucion | None = None,
        contexto: Mapping[str, object] | None = None,
    ) -> Propuesta:
        regla = politica or obtener_politica(campo)
        contexto = dict(contexto or {})
        unicas: dict[tuple[object, ...], Evidencia] = {}
        descartadas = 0
        for evidencia in evidencias:
            if evidencia.campo_objetivo != campo:
                descartadas += 1
                continue
            clave = _identidad(evidencia)
            if clave not in unicas or evidencia.confianza_fuente > unicas[clave].confianza_fuente:
                unicas[clave] = evidencia
        grupos: dict[str, list[Evidencia]] = defaultdict(list)
        for evidencia in unicas.values():
            valor = evidencia.valor_normalizado or normalizar(evidencia.valor_observado)
            if valor:
                grupos[valor].append(evidencia)
        if not grupos:
            return self._crear(
                campo, valor_original, valor_original,
                EstadoPropuesta.SIN_EVIDENCIA_SUFICIENTE, NivelConfianza.NULA,
                (), (), (), ("No existe evidencia utilizable.",),
                "REVISAR", {"evidencias_unicas": 0, "contexto": contexto},
            )

        puntajes = {
            valor: sum(
                regla.pesos_fuente[e.tipo_fuente] * e.confianza_fuente
                for e in grupo
            )
            for valor, grupo in grupos.items()
        }
        orden = sorted(puntajes, key=lambda v: (-puntajes[v], v))
        ganador = orden[0]
        segundo = puntajes[orden[1]] if len(orden) > 1 else 0.0
        favorables = tuple(grupos[ganador])
        contrarias = tuple(
            evidencia
            for valor in orden[1:]
            for evidencia in grupos[valor]
        )
        contradicciones: tuple[Contradiccion, ...] = ()
        if segundo >= regla.umbral_contradiccion:
            contradicciones = (
                Contradiccion(
                    campo,
                    tuple(orden),
                    tuple(unicas.values()),
                    "ALTA",
                    "Existen valores competidores con apoyo independiente.",
                    True,
                ),
            )

        puntaje = puntajes[ganador]
        margen = puntaje - segundo
        valido = regla.validador(ganador)
        solo_modelo = all(e.tipo_fuente == TipoFuente.MODELO_IA for e in favorables)
        inferencia_prohibida = any(
            e.detalles.get("relacion") in regla.inferencias_prohibidas
            for e in favorables
        )
        if contradicciones or inferencia_prohibida:
            estado, confianza, accion = (
                EstadoPropuesta.REVISAR, NivelConfianza.BAJA, "REVISAR"
            )
        elif not valido or solo_modelo:
            estado, confianza, accion = (
                EstadoPropuesta.SIN_EVIDENCIA_SUFICIENTE,
                NivelConfianza.BAJA,
                "REVISAR",
            )
        elif puntaje >= regla.umbral_confirmacion and margen >= regla.margen_minimo:
            estado, confianza, accion = (
                EstadoPropuesta.CONFIRMADO, NivelConfianza.ALTA, "ACEPTAR_PROPUESTA"
            )
        elif puntaje >= regla.umbral_propuesta and margen >= regla.margen_minimo:
            estado, confianza, accion = (
                EstadoPropuesta.PROPUESTO, NivelConfianza.MEDIA, "REVISAR_PROPUESTA"
            )
        else:
            estado, confianza, accion = (
                EstadoPropuesta.REVISAR, NivelConfianza.BAJA, "REVISAR"
            )
        propuesto = ganador if estado in {
            EstadoPropuesta.CONFIRMADO, EstadoPropuesta.PROPUESTO
        } else valor_original
        if estado == EstadoPropuesta.CONFIRMADO and normalizar(valor_original) == ganador:
            estado, propuesto, accion = EstadoPropuesta.SIN_CAMBIO, valor_original, "CONSERVAR"
        explicacion = (
            f"Campo: {campo}.",
            f"Original conservado: {valor_original or '[VACÍO]'}.",
            f"Valor con mayor apoyo: {ganador}.",
            f"Evidencias favorables independientes: {len(favorables)}.",
            f"Evidencias contrarias: {len(contrarias)}.",
            f"Decisión: {estado.value}.",
        )
        return self._crear(
            campo, valor_original, propuesto, estado, confianza,
            favorables, contrarias, contradicciones, explicacion, accion,
            {
                "puntajes": tuple((v, round(puntajes[v], 6)) for v in orden),
                "margen": round(margen, 6),
                "evidencias_unicas": len(unicas),
                "evidencias_descartadas": descartadas,
                "politica": regla.campo,
                "contexto": contexto,
            },
        )

    @staticmethod
    def _crear(
        campo, original, propuesto, estado, confianza, favorables, contrarias,
        contradicciones, explicacion, accion, trazabilidad
    ) -> Propuesta:
        return Propuesta(
            campo, original, propuesto, estado, confianza, tuple(favorables),
            tuple(contrarias), tuple(contradicciones), tuple(explicacion),
            accion, trazabilidad,
        )
