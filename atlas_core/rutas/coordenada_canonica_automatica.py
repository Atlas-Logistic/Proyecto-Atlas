"""Promoción conservadora de una coordenada canónica desde geocodificación.

Este módulo no consulta proveedores ni escribe catálogos por sí solo.  Separa
la evidencia devuelta por el geocodificador de la decisión de persistirla:
una coordenada nueva sólo puede promoverse cuando el destino documental ya
está confirmado y un único candidato específico pasa todas las guardas.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable

from atlas_core.catalogo_destinos import CatalogoDestinos, Destino, EstadoCalidadDestino, EstadoVigenciaDestino
from atlas_core.rutas.destino_entrega import motivo_incoherencia_destino_documental
from atlas_core.rutas.modelos import CandidatoGeocodificacion, EstadoRuta, ResultadoGeocodificacion
from atlas_core.territorio_chile import ESTADO_COMUNA_EXACTA, normalizar_comuna


class DecisionCoordenadaCanonica(str, Enum):
    AUTORESOLVIBLE_CON_NUEVA_POLITICA = "AUTORESOLVIBLE_CON_NUEVA_POLITICA"
    REQUIERE_CONFIRMACION = "REQUIERE_CONFIRMACION"
    SIGUE_REQUIRIENDO_MEJORA = "SIGUE_REQUIRIENDO_MEJORA"


@dataclass(frozen=True)
class PreviewConfirmacionGeografica:
    """Contrato mínimo para Review/B1; no presupone UI ni muta estado."""

    destino_id: str
    destino: str
    candidato_geografico: str
    direccion_normalizada: str
    comuna: str
    region: str
    precision: str
    fuente: str
    longitud: float | None
    latitud: float | None
    viajes_afectados: int
    # Si hay más de uno, Review debe mostrar opciones, no tratar el primero
    # como una propuesta implícita.
    candidatos: tuple[CandidatoGeocodificacion, ...] = ()
    acciones: tuple[str, str, str] = (
        "CONFIRMAR_UBICACION", "RECHAZAR_CANDIDATO", "DECIDIR_DESPUES",
    )


@dataclass(frozen=True)
class EvaluacionCoordenadaCanonica:
    decision: DecisionCoordenadaCanonica
    motivo: str
    candidato: CandidatoGeocodificacion | None
    preview: PreviewConfirmacionGeografica | None


def promover_evaluacion_automatica(
    catalogo: CatalogoDestinos, evaluacion: EvaluacionCoordenadaCanonica, *,
    proveedor: str, referencia: str,
) -> Destino:
    """Único adaptador de escritura; rechaza toda evaluación no inequívoca."""
    if (
        evaluacion.decision != DecisionCoordenadaCanonica.AUTORESOLVIBLE_CON_NUEVA_POLITICA
        or evaluacion.candidato is None
    ):
        raise ValueError("la evidencia no autoriza promoción automática")
    punto = evaluacion.candidato.coordenadas
    return catalogo.promover_coordenada_canonica_evidencia_fuerte(
        evaluacion.preview.destino_id if evaluacion.preview else "",
        latitud=punto.latitud, longitud=punto.longitud,
        proveedor=proveedor, referencia=referencia,
    )


def _destino_confirmado(destino: Destino) -> bool:
    return (
        destino.estado_calidad == EstadoCalidadDestino.CONFIRMADO.value
        and destino.estado_vigencia == EstadoVigenciaDestino.ACTIVO.value
    )


def _preview(
    destino: Destino, candidato: CandidatoGeocodificacion | None, *,
    fuente: str, viajes_afectados: int, candidatos: tuple[CandidatoGeocodificacion, ...] = (),
) -> PreviewConfirmacionGeografica:
    return PreviewConfirmacionGeografica(
        destino_id=destino.destino_id,
        destino=destino.direccion or destino.nombre_destino,
        candidato_geografico=candidato.etiqueta if candidato else "",
        direccion_normalizada=candidato.etiqueta if candidato else "",
        comuna=candidato.localidad if candidato else "",
        region=candidato.region if candidato else "",
        precision=("DIRECCION_ESPECIFICA" if candidato and candidato.etiqueta else "SIN_CANDIDATO"),
        fuente=fuente,
        longitud=candidato.coordenadas.longitud if candidato else None,
        latitud=candidato.coordenadas.latitud if candidato else None,
        viajes_afectados=viajes_afectados,
        candidatos=candidatos,
    )


def evaluar_coordenada_canonica_automatica(
    *,
    destino: Destino,
    resultado: ResultadoGeocodificacion,
    fuente: str,
    guias_afectadas: Iterable[str] = (),
    confianza_minima: float = 0.5,
) -> EvaluacionCoordenadaCanonica:
    """Clasifica candidatos sin rebajar las guardas de routing.

    La promoción requiere exactamente un candidato, confianza explícita y
    suficiente, y que su etiqueta aporte calle/número coherentes con el
    documento canónico. Una respuesta de comuna/centroide, una contradicción
    o cualquier pluralidad de candidatos se abstiene.
    """
    guias = tuple(dict.fromkeys(str(g).strip() for g in guias_afectadas if str(g).strip()))
    candidatos = resultado.candidatos
    if not _destino_confirmado(destino):
        return EvaluacionCoordenadaCanonica(
            DecisionCoordenadaCanonica.SIGUE_REQUIRIENDO_MEJORA,
            "DESTINO_NO_CONFIRMADO_NO_ES_AUTORIDAD_CANONICA", None, None,
        )
    if not candidatos:
        return EvaluacionCoordenadaCanonica(
            DecisionCoordenadaCanonica.SIGUE_REQUIRIENDO_MEJORA,
            f"SIN_CANDIDATO_UTIL:{resultado.estado.value}", None,
            _preview(destino, None, fuente=fuente, viajes_afectados=len(guias)),
        )
    if len(candidatos) != 1:
        return EvaluacionCoordenadaCanonica(
            DecisionCoordenadaCanonica.REQUIERE_CONFIRMACION,
            f"MULTIPLES_CANDIDATOS({len(candidatos)})", None,
            _preview(destino, None, fuente=fuente, viajes_afectados=len(guias), candidatos=candidatos),
        )
    candidato = candidatos[0]
    if resultado.estado not in (EstadoRuta.REQUIERE_REVISION, EstadoRuta.RESULTADO_AMBIGUO):
        return EvaluacionCoordenadaCanonica(
            DecisionCoordenadaCanonica.SIGUE_REQUIRIENDO_MEJORA,
            f"RESULTADO_NO_UTIL:{resultado.estado.value}", candidato,
            _preview(destino, candidato, fuente=fuente, viajes_afectados=len(guias)),
        )
    if candidato.confianza is None or candidato.confianza < confianza_minima:
        return EvaluacionCoordenadaCanonica(
            DecisionCoordenadaCanonica.REQUIERE_CONFIRMACION,
            "CONFIANZA_INSUFICIENTE", candidato,
            _preview(destino, candidato, fuente=fuente, viajes_afectados=len(guias)),
        )
    incoherencia = motivo_incoherencia_destino_documental(
        despachar_a_crudo=destino.direccion,
        etiqueta_geocodificada=candidato.etiqueta,
        localidad=candidato.localidad,
        region=candidato.region,
    )
    if incoherencia:
        return EvaluacionCoordenadaCanonica(
            DecisionCoordenadaCanonica.REQUIERE_CONFIRMACION,
            incoherencia, candidato,
            _preview(destino, candidato, fuente=fuente, viajes_afectados=len(guias)),
        )
    # El destino ya confirmado puede aportar comuna canónica como evidencia
    # adicional, pero sólo para CONTRADECIR un candidato: nunca completa una
    # comuna ausente ni elige entre alternativas. Ambas deben normalizar de
    # forma exacta en el catálogo territorial cerrado.
    comuna_destino = normalizar_comuna(destino.comuna) if destino.comuna else None
    comuna_candidato = normalizar_comuna(candidato.localidad) if candidato.localidad else None
    if (
        comuna_destino and comuna_candidato
        and comuna_destino.estado == ESTADO_COMUNA_EXACTA
        and comuna_candidato.estado == ESTADO_COMUNA_EXACTA
        and comuna_destino.comuna != comuna_candidato.comuna
    ):
        return EvaluacionCoordenadaCanonica(
            DecisionCoordenadaCanonica.REQUIERE_CONFIRMACION,
            f"GEOCODIFICACION_CONTRADICE_COMUNA_CANONICA: {comuna_destino.comuna} != {comuna_candidato.comuna}",
            candidato, _preview(destino, candidato, fuente=fuente, viajes_afectados=len(guias)),
        )
    return EvaluacionCoordenadaCanonica(
        DecisionCoordenadaCanonica.AUTORESOLVIBLE_CON_NUEVA_POLITICA,
        "CANDIDATO_UNICO_ESPECIFICO_COHERENTE", candidato,
        _preview(destino, candidato, fuente=fuente, viajes_afectados=len(guias)),
    )
