"""Motor de Evidencia -- Obras. Mismo patrón genérico
(`atlas_core.motor_evidencia`), aplicado al caso real que lo motivó: la
guía 464493 trae "EMPRESA CONST SIGRO SA" y Atlas ya tiene confirmada,
para el mismo cliente, la obra "EMPRESA CONST SIGRO" -- misma entidad,
sólo con un sufijo societario de más.

Deliberadamente NO se modifica `normalizar_nombre_obra`
(`atlas_core.catalogo_obras_destinos`): esa función decide identidad
EXACTA para deduplicar el catálogo real, ya validada en producción --
ensancharla para ignorar sufijos societarios arriesgaría fusionar en
silencio dos obras que de verdad son entidades legales distintas (p.ej.
"Constructora ABC SA" y "Constructora ABC SPA" podrían no ser la misma
empresa). En cambio, este módulo agrega una función NUEVA y calibrada,
`coincide_salvo_sufijo_societario`, que sólo SUGIERE la posible
coincidencia -- nunca decide identidad por sí sola. Mismo principio ya
usado para vehículos (`_diferencia_ocr_segura` sugiere, nunca autocorrige)."""
from __future__ import annotations

from atlas_core.catalogo_obras_destinos import Obra, normalizar_nombre_obra
from atlas_core.motor_evidencia import (
    NIVEL_DOCUMENTAL_DEBIL, NIVEL_EXTERNO_CORPORATIVO, NIVEL_EXTERNO_DIRECTORIO, NIVEL_EXTERNO_OFICIAL,
    RESULTADO_ALTA_NUEVA, RESULTADO_CONTRADICCION_DOCUMENTAL, RESULTADO_SUGERENCIA_HUMANA,
    CandidatoEvidencia, ResultadoEvidencia, elegir_mejor_candidato, hay_empate_en_el_tope,
)
from atlas_core.verificacion_externa import TIPO_FUENTE_CORPORATIVO, TIPO_FUENTE_DIRECTORIO, TIPO_FUENTE_OFICIAL, EvidenciaExterna

# Sufijos societarios chilenos habituales -- lista pequeña y explícita,
# nunca "cualquier última palabra". Un único sufijo removido de CADA lado
# como máximo (nunca en cascada).
_SUFIJOS_SOCIETARIOS = ("SA", "LTDA", "SPA", "EIRL", "LIMITADA")

_NIVEL_POR_TIPO_FUENTE_EXTERNA = {
    TIPO_FUENTE_OFICIAL: NIVEL_EXTERNO_OFICIAL,
    TIPO_FUENTE_CORPORATIVO: NIVEL_EXTERNO_CORPORATIVO,
    TIPO_FUENTE_DIRECTORIO: NIVEL_EXTERNO_DIRECTORIO,
}


def _sin_sufijo_societario(tokens: tuple[str, ...]) -> tuple[str, ...]:
    if tokens and tokens[-1] in _SUFIJOS_SOCIETARIOS:
        return tokens[:-1]
    return tokens


def coincide_salvo_sufijo_societario(nombre_a: str, nombre_b: str) -> bool:
    """True si dos nombres, ya normalizados por `normalizar_nombre_obra`,
    son IDÉNTICOS una vez que se retira -- como mucho -- un sufijo
    societario final de cada lado, y los textos originales normalizados
    NO eran ya idénticos (ese caso ni siquiera necesita esta función)."""
    tokens_a = tuple(normalizar_nombre_obra(nombre_a).split())
    tokens_b = tuple(normalizar_nombre_obra(nombre_b).split())
    if not tokens_a or not tokens_b or tokens_a == tokens_b:
        return False
    return _sin_sufijo_societario(tokens_a) == _sin_sufijo_societario(tokens_b)


def evaluar_evidencia_obra(
    *, nombre_documental: str, obras_confirmadas_mismo_cliente: tuple[Obra, ...] = (),
    evidencia_externa: tuple[EvidenciaExterna, ...] = (),
) -> ResultadoEvidencia:
    """Se invoca DESPUÉS de que la coincidencia exacta
    (`normalizar_nombre_obra`, ya usada por `regenerar_decisiones_persistidas`)
    falló -- nunca la reemplaza. Busca coincidencias por sufijo societario
    contra obras ya confirmadas del mismo cliente, y considera evidencia
    externa si se le entrega."""
    documental = str(nombre_documental or "").strip()
    if not documental:
        return ResultadoEvidencia(resultado=RESULTADO_SUGERENCIA_HUMANA, explicacion="Sin nombre documental que evaluar.")

    candidatos: list[CandidatoEvidencia] = []
    for obra in obras_confirmadas_mismo_cliente:
        if coincide_salvo_sufijo_societario(documental, obra.nombre_canonico):
            candidatos.append(CandidatoEvidencia(
                identificador=obra.obra_id, valor_canonico=obra.nombre_canonico,
                nivel=NIVEL_DOCUMENTAL_DEBIL, evidencias=("COINCIDE_SALVO_SUFIJO_SOCIETARIO",),
                conflictos=("TEXTO_DOCUMENTAL_DIFIERE",),
                razon_legible=(
                    f'Atlas considera "{obra.nombre_canonico}" porque ya está confirmada para este mismo '
                    f'cliente y coincide con "{documental}" salvo un sufijo societario (p.ej. "SA", "LTDA").'
                ),
            ))

    for evidencia in evidencia_externa:
        nivel = _NIVEL_POR_TIPO_FUENTE_EXTERNA.get(evidencia.tipo_fuente, NIVEL_DOCUMENTAL_DEBIL)
        candidatos.append(CandidatoEvidencia(
            identificador=evidencia.rut or evidencia.razon_social, valor_canonico=evidencia.razon_social,
            nivel=nivel, evidencias=("EVIDENCIA_EXTERNA:" + evidencia.tipo_fuente,),
            conflictos=tuple(evidencia.contradicciones),
            razon_legible=(
                f'Atlas encontró "{evidencia.razon_social}" en una fuente externa '
                f"({evidencia.tipo_fuente.lower()}: {evidencia.fuente}) que corrobora "
                f"{', '.join(evidencia.campos_corroborados) or 'esta identidad'} -- pero una dirección o "
                "sitio web corporativo por sí solo no demuestra que exista una obra operacional en curso."
            ),
        ))

    if not candidatos:
        return ResultadoEvidencia(
            resultado=RESULTADO_ALTA_NUEVA,
            explicacion=f'"{documental}" no coincide con ninguna obra conocida del cliente ni con evidencia externa en contra.',
        )

    if hay_empate_en_el_tope(tuple(candidatos)):
        return ResultadoEvidencia(
            resultado=RESULTADO_SUGERENCIA_HUMANA, candidatos=tuple(candidatos),
            explicacion="Hay más de una candidata igualmente respaldada -- Atlas no elige arbitrariamente entre ellas.",
        )

    mejor = elegir_mejor_candidato(tuple(candidatos))
    assert mejor is not None
    # Ninguna fuente disponible para obras alcanza hoy el nivel de
    # confirmación humana estructural -- el resultado más fuerte posible
    # es CONTRADICCION_DOCUMENTAL (sugerir con fuerza, nunca resolver
    # solo) cuando la fuente es de alta confianza; el resto queda como
    # sugerencia. Nunca RESUELTO_AUTOMATICAMENTE sin una confirmación
    # humana real -- ver la misma decisión de producto tomada para
    # VP6521->VP8521 en el bloque anterior.
    if mejor.nivel in (NIVEL_EXTERNO_OFICIAL, NIVEL_EXTERNO_CORPORATIVO):
        return ResultadoEvidencia(
            resultado=RESULTADO_CONTRADICCION_DOCUMENTAL, candidatos=tuple(candidatos), explicacion=mejor.razon_legible,
        )
    return ResultadoEvidencia(
        resultado=RESULTADO_SUGERENCIA_HUMANA, candidatos=tuple(candidatos), explicacion=mejor.razon_legible,
    )
