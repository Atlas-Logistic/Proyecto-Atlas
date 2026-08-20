"""Herramientas read-only de evidencia disponibles para Atlas IA B1."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, Mapping

from atlas_core.atlas_ia.contratos import ContextoRazonamiento, EvidenciaIA


ConsultaEvidencia = Callable[[ContextoRazonamiento], tuple[EvidenciaIA, ...]]


@dataclass(frozen=True)
class HerramientaEvidencia:
    nombre: str
    descripcion: str
    consultar: ConsultaEvidencia


def herramienta_documentos_relacionados(
    filas: Iterable[Mapping[str, object]],
) -> HerramientaEvidencia:
    """Expone otras guías del mismo transporte como evidencia, sin decidir."""
    filas_copia = tuple(dict(fila) for fila in filas)

    def consultar(contexto: ContextoRazonamiento) -> tuple[EvidenciaIA, ...]:
        evidencias: list[EvidenciaIA] = []
        for fila in filas_copia:
            guia = str(fila.get("numero_guia", "")).strip()
            transporte = str(fila.get("numero_transporte", "")).strip()
            if not transporte or transporte != contexto.numero_transporte or guia == contexto.numero_guia:
                continue
            valor = str(fila.get(contexto.campo, "")).strip()
            if not valor or valor in ("No encontrado", "NO ENCONTRADO"):
                continue
            evidencias.append(EvidenciaIA(
                identificador=f"documento:{guia}:{contexto.campo}",
                campo=contexto.campo, valor=valor, tipo_fuente="DOCUMENTAL",
                nivel="DOCUMENTAL_DEBIL", a_favor=("MISMO_TRANSPORTE",),
                independencia=0,
                procedencia="atlas_core.atlas_ia.herramientas.documentos_relacionados",
                referencias_fuente=(f"guia={guia};transporte={transporte};relacion=MISMO_TRANSPORTE",),
            ))
        return tuple(evidencias)

    return HerramientaEvidencia(
        nombre="DOCUMENTOS_RELACIONADOS",
        descripcion="Busca valores del mismo campo en otras guías del mismo transporte.",
        consultar=consultar,
    )
