"""Validadores deterministas POST-proveedor -- la barrera anti-alucinación
de Atlas IA, Bloque A1.

Se ejecutan SIEMPRE después de que un `ProveedorModeloIA` devuelve una
`HipotesisIA`, antes de que se use para cualquier fin (incluido shadow,
que sólo la registra). Ninguno de estos validadores usa IA -- son
deterministas y reutilizan, donde ya existen, las mismas funciones que
usa el Motor productivo (nunca duplican una regla de formato de patente
que ya vive en `atlas_core.extractor`).

Principio central (V2): Atlas IA no puede convertir conocimiento
paramétrico del modelo en un hecho operacional -- un valor propuesto que
no aparezca en la evidencia recuperada para este caso exacto se rechaza,
sin importar cuánta "confianza" declare el proveedor."""

from __future__ import annotations

from atlas_core.atlas_ia.contratos import (
    ContextoRazonamiento,
    HipotesisIA,
    MOTIVO_CONTRADICE_EVIDENCIA_SUPERIOR,
    MOTIVO_ESTRUCTURA_INVALIDA,
    MOTIVO_FORMATO_INVALIDO,
    MOTIVO_VALOR_NO_RESPALDADO,
    RESULTADO_HIPOTESIS_PROPUESTA,
    ResultadoValidacionHipotesis,
)
from atlas_core.extractor import _patente_valida
from atlas_core.catalogo_clientes import normalizar_rut_cliente
from atlas_core.validadores import EstadoValidacion, validar_fecha


def validar_hipotesis_multicampo(
    hipotesis: HipotesisIA, contexto: ContextoRazonamiento,
) -> ResultadoValidacionHipotesis:
    """Barrera universal y reglas específicas sólo cuando ya existen."""
    if hipotesis.campo != contexto.campo or hipotesis.valor_observado != contexto.valor_documental:
        return ResultadoValidacionHipotesis(
            aceptada=False, motivo_rechazo=MOTIVO_ESTRUCTURA_INVALIDA,
            detalle="La hipótesis no corresponde al contexto recibido.",
        )
    if hipotesis.resultado != RESULTADO_HIPOTESIS_PROPUESTA:
        return ResultadoValidacionHipotesis(aceptada=True)
    if hipotesis.valor_propuesto not in contexto.valores_evidencia():
        return ResultadoValidacionHipotesis(
            aceptada=False, motivo_rechazo=MOTIVO_VALOR_NO_RESPALDADO,
            detalle=f'"{hipotesis.valor_propuesto}" no aparece en la evidencia del caso.',
        )
    for evidencia in contexto.evidencias:
        if evidencia.es_decision_humana and evidencia.valor != hipotesis.valor_propuesto:
            return ResultadoValidacionHipotesis(
                aceptada=False, motivo_rechazo=MOTIVO_CONTRADICE_EVIDENCIA_SUPERIOR,
                detalle=f'La propuesta contradice la decisión humana "{evidencia.valor}".',
            )

    campo = contexto.campo.lower()
    if campo in ("patente_tracto", "patente_rampla") and not _patente_valida(hipotesis.valor_propuesto):
        return ResultadoValidacionHipotesis(
            aceptada=False, motivo_rechazo=MOTIVO_FORMATO_INVALIDO,
            detalle="La propuesta no tiene formato de patente válido.",
        )
    if campo in ("rut_chofer", "rut_cliente"):
        try:
            normalizar_rut_cliente(hipotesis.valor_propuesto)
        except ValueError:
            return ResultadoValidacionHipotesis(
                aceptada=False, motivo_rechazo=MOTIVO_FORMATO_INVALIDO,
                detalle="La propuesta no tiene un RUT chileno válido.",
            )
    if campo == "fecha":
        valor_fecha = hipotesis.valor_propuesto.replace("-", "/")
        if validar_fecha(valor_fecha, formato_esperado="DD/MM/YYYY").estado != EstadoValidacion.VALIDO:
            return ResultadoValidacionHipotesis(
                aceptada=False, motivo_rechazo=MOTIVO_FORMATO_INVALIDO,
                detalle="La propuesta no tiene una fecha DD-MM-YYYY válida.",
            )
    return ResultadoValidacionHipotesis(aceptada=True)


def validar_hipotesis_vehiculo(
    hipotesis: HipotesisIA, contexto: ContextoRazonamiento,
) -> ResultadoValidacionHipotesis:
    """V1-V4 para el vertical vehículos/patentes (único vertical de A1).

    Una hipótesis con resultado distinto de `PROPUESTA` (ABSTENCION o
    REQUIERE_HERRAMIENTA) siempre se acepta estructuralmente -- no hay
    ningún valor que validar contra evidencia cuando el proveedor no
    propuso nada. Rechazar una abstención sería convertir una abstención
    correcta en un error, exactamente lo que el bloque A1 prohíbe."""
    # V4 -- estructura: la hipótesis debe corresponder a este contexto,
    # nunca a otro campo/valor documental distinto.
    if hipotesis.campo != contexto.campo or hipotesis.valor_observado != contexto.valor_documental:
        return ResultadoValidacionHipotesis(
            aceptada=False, motivo_rechazo=MOTIVO_ESTRUCTURA_INVALIDA,
            detalle="La hipótesis no corresponde al campo/valor documental de este contexto.",
        )

    if hipotesis.resultado != RESULTADO_HIPOTESIS_PROPUESTA:
        return ResultadoValidacionHipotesis(aceptada=True)

    # V1 -- formato: misma regla que ya usa el resto del Motor, nunca duplicada.
    if not _patente_valida(hipotesis.valor_propuesto):
        return ResultadoValidacionHipotesis(
            aceptada=False, motivo_rechazo=MOTIVO_FORMATO_INVALIDO,
            detalle=f'"{hipotesis.valor_propuesto}" no tiene formato de patente válido.',
        )

    # V2 -- el valor propuesto debe existir en la evidencia recuperada
    # para este caso exacto; nunca inventado por el proveedor.
    if hipotesis.valor_propuesto not in contexto.valores_evidencia():
        return ResultadoValidacionHipotesis(
            aceptada=False, motivo_rechazo=MOTIVO_VALOR_NO_RESPALDADO,
            detalle=(
                f'"{hipotesis.valor_propuesto}" no aparece en ninguna evidencia/candidato '
                "recuperado para este caso -- Atlas IA no puede convertir conocimiento "
                "paramétrico del modelo en un hecho operacional."
            ),
        )

    # V3 -- ninguna decisión humana previa, ya presente en la evidencia,
    # puede quedar contradicha por la propuesta.
    for evidencia in contexto.evidencias:
        if evidencia.es_decision_humana and evidencia.valor != hipotesis.valor_propuesto:
            return ResultadoValidacionHipotesis(
                aceptada=False, motivo_rechazo=MOTIVO_CONTRADICE_EVIDENCIA_SUPERIOR,
                detalle=(
                    f'Existe una decisión humana previa ("{evidencia.valor}") que contradice '
                    f'la propuesta ("{hipotesis.valor_propuesto}").'
                ),
            )

    return ResultadoValidacionHipotesis(aceptada=True)
