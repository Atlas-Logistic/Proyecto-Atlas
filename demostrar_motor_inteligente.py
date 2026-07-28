"""Demostración exclusivamente sintética del motor inteligente Atlas."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from atlas_core.inteligencia import (
    Evidencia,
    MotorResolucion,
    TipoFuente,
    normalizar,
)


INSTANTE = datetime(2026, 7, 28, 18, 30, tzinfo=timezone.utc)


def evidencia(valor: str, tipo: TipoFuente, fuente: str, confianza: float):
    return Evidencia(
        "chofer", valor, normalizar(valor), fuente, tipo, confianza, INSTANTE,
        documento_origen="GUIA-SINTETICA-001",
        referencia=f"REF-{tipo.value}",
        detalles={"caso": "demostracion_sintetica"},
        contiene_datos_sensibles=True,
    )


def construir_demostracion() -> dict[str, object]:
    propuesta = MotorResolucion().resolver(
        "chofer",
        "CARLOS FIEBRI",
        (
            evidencia("CARLOS FIEBRI", TipoFuente.OCR, "ocr_simulado", 0.86),
            evidencia("CARLOS FIEBIG", TipoFuente.CATALOGO, "catalogo_sintetico", 0.95),
            evidencia("CARLOS FIEBIG", TipoFuente.RELACION_CAMPO, "rut_sintetico", 1.0),
            evidencia("CARLOS FIEBIG", TipoFuente.VERIFICACION_EXTERNA, "externo_simulado", 0.8),
        ),
    )
    return {
        "campo": propuesta.campo,
        "original": propuesta.valor_original,
        "propuesto": propuesta.valor_propuesto,
        "estado": propuesta.estado.value,
        "confianza": propuesta.confianza.value,
        "evidencias_favorables": len(propuesta.evidencias_favorables),
        "evidencias_contrarias": len(propuesta.evidencias_contrarias),
        "contradicciones": [c.motivo for c in propuesta.contradicciones],
        "explicacion": list(propuesta.explicacion),
        "accion": propuesta.accion_recomendada,
    }


def main() -> None:
    print(json.dumps(construir_demostracion(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
