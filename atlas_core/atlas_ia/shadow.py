"""Shadow harness de Atlas IA -- Bloque A1.

Orquestador de sólo lectura: recibe casos ya construidos (nunca los
descubre por su cuenta), llama al proveedor inyectado, valida la
hipótesis resultante y produce un `ResultadoShadow` por caso. Nunca abre
Drive, nunca conoce `ATLAS_DATA_DIR` ni `operacion/actual`, nunca aplica
ninguna decisión ni escribe ningún catálogo/ledger/reporte.

Por defecto `persistir=False`: el resultado completo vive en memoria. Si
se pide persistir, `ruta_salida` es obligatoria y explícita -- nunca
autodetectada; pedir persistir sin ruta es un error de uso, no un
fallback silencioso a ninguna ubicación por defecto."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from atlas_core.atlas_ia.contratos import ContextoRazonamiento, ResultadoShadow
from atlas_core.atlas_ia.proveedor import ProveedorModeloIA
from atlas_core.atlas_ia.validadores import validar_hipotesis_vehiculo


def ejecutar_caso_shadow(
    *, caso_id: str, contexto: ContextoRazonamiento, proveedor: ProveedorModeloIA,
    ground_truth_humano: str = "",
) -> ResultadoShadow:
    """Ejecuta UN caso de punta a punta: proveedor -> validador ->
    `ResultadoShadow`. Nunca aplica nada, nunca escribe nada -- devuelve
    el resultado completo en memoria."""
    hipotesis = proveedor.razonar(contexto)
    validacion = validar_hipotesis_vehiculo(hipotesis, contexto)
    return ResultadoShadow(
        caso_id=caso_id, contexto=contexto, hipotesis=hipotesis, validacion=validacion,
        resultado_motor=contexto.resultado_motor, ground_truth_humano=ground_truth_humano,
    )


def ejecutar_shadow(
    *,
    casos: Iterable[tuple[str, ContextoRazonamiento, str]],
    proveedor: ProveedorModeloIA,
    persistir: bool = False,
    ruta_salida: str | Path | None = None,
) -> list[ResultadoShadow]:
    """Ejecuta una tanda de casos. `casos` es un iterable de
    `(caso_id, contexto, ground_truth_humano)` -- construido siempre
    fuera de este módulo (fixtures/tests/adaptadores); este harness nunca
    lee Drive ni ninguna ruta global para descubrir casos por su cuenta.

    `persistir=False` (por defecto): no escribe nada, devuelve la lista
    completa en memoria -- comportamiento estándar para tests y para
    cualquier corrida de auditoría offline.

    `persistir=True` exige `ruta_salida` explícita. Nunca se autodetecta
    vía `ATLAS_DATA_DIR`/Drive/`operacion/actual`/junto al ledger -- si se
    pide persistir sin ruta, se lanza un error de uso en vez de escribir
    en cualquier ubicación por defecto."""
    resultados = [
        ejecutar_caso_shadow(
            caso_id=caso_id, contexto=contexto, proveedor=proveedor, ground_truth_humano=ground_truth,
        )
        for caso_id, contexto, ground_truth in casos
    ]
    if persistir:
        if ruta_salida is None:
            raise ValueError("persistir=True exige ruta_salida explícita.")
        ruta = Path(ruta_salida)
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_text(
            json.dumps([r.a_dict() for r in resultados], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return resultados
