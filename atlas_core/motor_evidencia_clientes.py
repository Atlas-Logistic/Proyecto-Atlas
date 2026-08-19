"""Motor de Evidencia -- Clientes. Reutiliza el patrón genérico de
`atlas_core.motor_evidencia` (mismo que ya valida en producción para
vehículos) aplicado a la identidad de clientes: OBSERVACIÓN (nombre/RUT/
dirección documental) -> CANDIDATOS (clientes internos, confirmaciones
humanas acumuladas, evidencia externa) -> EVIDENCIAS/CONTRADICCIONES ->
RESULTADO -> EXPLICACIÓN.

No sustituye el flujo determinista ya existente y validado
(`_identidad_cliente_por_rut` + `ALIAS_CANDIDATO`, en
`atlas_core.decisiones_pendientes`): ese paso -- RUT exacto contra
catálogo `CONFIRMADO`/`ACTIVO` -- sigue siendo la primera y más fuerte
señal, igual que `resolver_patente` lo es para vehículos. Este módulo
añade la pieza que faltaba:

1. Distinguir RUT_DOCUMENTAL (texto crudo tal cual llegó) de RUT_OCR
   (con `_AUSENTES` filtrados) de RUT_VALIDADO (pasa el dígito
   verificador chileno) de RUT_CANONICO (coincide con un cliente interno
   ya `CONFIRMADO`/`ACTIVO`) -- un RUT documental inválido NUNCA se trata
   como si fuera verdad.
2. CONFIRMACIONES_INDEPENDIENTES: cuando el mismo RUT ya fue confirmado
   por un humano, en transportes distintos, como la misma entidad
   canónica dos o más veces (`UMBRAL_CONFIRMACIONES_PARA_CONOCIMIENTO_FUERTE`
   en `atlas_core.evidencia_entidades`), esa relación se eleva a
   conocimiento operacional fuerte -- una tercera aparición equivalente
   puede resolverse automáticamente, sin volver a preguntar, registrando
   además una Incidencia Documental (el documento seguía trayendo un
   valor distinto del real).
3. Evidencia externa (opcional, inyectada por el llamador -- este módulo
   nunca hace red por sí mismo, ver `atlas_core.verificacion_externa`)."""
from __future__ import annotations

from typing import Iterable

from atlas_core.catalogo_clientes import (
    Cliente, EstadoCalidadCliente, EstadoVigenciaCliente, normalizar_nombre_cliente, normalizar_rut_cliente,
)
from atlas_core.evidencia_entidades import (
    UMBRAL_CONFIRMACIONES_PARA_CONOCIMIENTO_FUERTE, ConfirmacionIdentidad, transportes_independientes,
)
from atlas_core.motor_evidencia import (
    NIVEL_CONFIRMACION_HUMANA, NIVEL_DOCUMENTAL_DEBIL, NIVEL_DOCUMENTAL_INDEPENDIENTE,
    NIVEL_EXTERNO_CORPORATIVO, NIVEL_EXTERNO_DIRECTORIO, NIVEL_EXTERNO_OFICIAL,
    RESULTADO_ABSTENCION_REAL, RESULTADO_ALTA_NUEVA, RESULTADO_CONTRADICCION_DOCUMENTAL,
    RESULTADO_RESUELTO_AUTOMATICAMENTE, RESULTADO_SUGERENCIA_HUMANA,
    CandidatoEvidencia, ResultadoEvidencia, elegir_mejor_candidato, hay_empate_en_el_tope,
)
from atlas_core.verificacion_externa import TIPO_FUENTE_CORPORATIVO, TIPO_FUENTE_DIRECTORIO, TIPO_FUENTE_OFICIAL, EvidenciaExterna

# Estados del RUT documental -- ver punto 1 del docstring del módulo.
RUT_AUSENTE = "RUT_AUSENTE"
RUT_INVALIDO = "RUT_INVALIDO"
RUT_VALIDADO = "RUT_VALIDADO"
RUT_CANONICO = "RUT_CANONICO"

_NIVEL_POR_TIPO_FUENTE_EXTERNA = {
    TIPO_FUENTE_OFICIAL: NIVEL_EXTERNO_OFICIAL,
    TIPO_FUENTE_CORPORATIVO: NIVEL_EXTERNO_CORPORATIVO,
    TIPO_FUENTE_DIRECTORIO: NIVEL_EXTERNO_DIRECTORIO,
}


def clasificar_rut_documental(rut_documental: str, *, clientes_confirmados_por_rut: dict[str, Cliente]) -> tuple[str, str]:
    """Devuelve `(estado, rut_normalizado)`. `rut_normalizado` es "" si el
    RUT está ausente o no pasa el dígito verificador -- nunca se propaga
    un RUT inválido como si fuera un identificador real."""
    crudo = str(rut_documental or "").strip()
    if not crudo:
        return RUT_AUSENTE, ""
    try:
        normalizado = normalizar_rut_cliente(crudo)
    except ValueError:
        return RUT_INVALIDO, ""
    if normalizado in clientes_confirmados_por_rut:
        return RUT_CANONICO, normalizado
    return RUT_VALIDADO, normalizado


def _candidato_desde_externa(evidencia: EvidenciaExterna, *, conflictos: tuple[str, ...], razon: str) -> CandidatoEvidencia:
    nivel = _NIVEL_POR_TIPO_FUENTE_EXTERNA.get(evidencia.tipo_fuente, NIVEL_DOCUMENTAL_DEBIL)
    return CandidatoEvidencia(
        identificador=evidencia.rut or evidencia.razon_social, valor_canonico=evidencia.razon_social,
        nivel=nivel, evidencias=("EVIDENCIA_EXTERNA:" + evidencia.tipo_fuente,), conflictos=conflictos,
        razon_legible=razon, metadatos={"fuente": evidencia.fuente, "url": evidencia.url, "rut": evidencia.rut},
    )


def evaluar_evidencia_cliente(
    *, razon_social_documental: str, rut_documental: str, numero_guia: str, numero_transporte: str,
    clientes: Iterable[Cliente], confirmaciones: Iterable[ConfirmacionIdentidad] = (),
    evidencia_externa: tuple[EvidenciaExterna, ...] = (),
) -> ResultadoEvidencia:
    """Motor de evidencia completo para la identidad de un cliente. Se
    invoca DESPUÉS de que el paso determinista existente
    (`_identidad_cliente_por_rut`) ya falló en encontrar una coincidencia
    exacta y sin contradicción -- nunca lo reemplaza."""
    documental = str(razon_social_documental or "").strip()
    clientes_lista = list(clientes)
    confirmadas_activas = [
        c for c in clientes_lista
        if c.estado_calidad == EstadoCalidadCliente.CONFIRMADO.value
        and c.estado_vigencia == EstadoVigenciaCliente.ACTIVO.value
    ]
    clientes_confirmados_por_rut = {c.rut: c for c in confirmadas_activas if c.rut}

    estado_rut, rut_normalizado = clasificar_rut_documental(rut_documental, clientes_confirmados_por_rut=clientes_confirmados_por_rut)

    if not documental and estado_rut in (RUT_AUSENTE, RUT_INVALIDO):
        return ResultadoEvidencia(
            resultado=RESULTADO_ABSTENCION_REAL,
            explicacion="No puedo determinarlo con seguridad: no hay razón social documental ni un RUT válido para investigar.",
        )

    candidatos: list[CandidatoEvidencia] = []

    # 1) RUT canónico -- el cliente ya existe, CONFIRMADO/ACTIVO. Sin
    #    contradicción de texto, esto ya es certeza total (nivel tope).
    #    CON contradicción, sigue siendo un match estructural fuerte
    #    (nivel DOCUMENTAL_INDEPENDIENTE -> CONTRADICCION_DOCUMENTAL, ver
    #    CASO B), salvo que YA existan >=2 confirmaciones humanas
    #    independientes de esta relación puntual (RUT documental distinto
    #    -> este cliente), en cuyo caso sube a certeza total (CASO C).
    cliente_por_rut = clientes_confirmados_por_rut.get(rut_normalizado) if estado_rut == RUT_CANONICO else None
    if cliente_por_rut is not None:
        claves_confirmadas = {
            normalizar_nombre_cliente(cliente_por_rut.razon_social),
            *(normalizar_nombre_cliente(alias) for alias in cliente_por_rut.aliases),
        }
        coincide_texto = bool(documental) and normalizar_nombre_cliente(documental) in claves_confirmadas
        conflictos = () if coincide_texto or not documental else ("TEXTO_DOCUMENTAL_DIFIERE",)
        if not conflictos:
            nivel, evidencias, extra = NIVEL_CONFIRMACION_HUMANA, ("RUT_CANONICO_COINCIDE",), ""
        else:
            confirmaciones_de_esta_relacion = [
                c for c in confirmaciones
                if c.dominio == "CLIENTE" and c.contexto_clave == rut_normalizado
                and normalizar_nombre_cliente(c.valor_confirmado) == normalizar_nombre_cliente(cliente_por_rut.razon_social)
            ]
            independientes = transportes_independientes(confirmaciones_de_esta_relacion)
            if independientes >= UMBRAL_CONFIRMACIONES_PARA_CONOCIMIENTO_FUERTE:
                nivel = NIVEL_CONFIRMACION_HUMANA
                evidencias = ("RUT_CANONICO_COINCIDE", f"CONFIRMACIONES_INDEPENDIENTES({independientes})")
                extra = f" Además, un humano ya confirmó esta misma relación en {independientes} transportes independientes."
            else:
                nivel, evidencias, extra = NIVEL_DOCUMENTAL_INDEPENDIENTE, ("RUT_CANONICO_COINCIDE",), ""
        candidatos.append(CandidatoEvidencia(
            identificador=cliente_por_rut.cliente_id, valor_canonico=cliente_por_rut.razon_social,
            nivel=nivel, evidencias=evidencias, conflictos=conflictos, metadatos={"rut": cliente_por_rut.rut},
            razon_legible=(
                f'Atlas considera "{cliente_por_rut.razon_social}" porque el RUT documental coincide '
                f"exactamente con un cliente ya confirmado."
                + (f' La guía dice "{documental}", un texto distinto.' if conflictos else "") + extra
            ),
        ))

    # 2) Confirmaciones humanas independientes acumuladas para este RUT,
    #    cuando el cliente todavía NO está formalmente en el catálogo
    #    (p.ej. Javier ya confirmó la relación operacionalmente varias
    #    veces, pero el alta formal del cliente sigue pendiente).
    if rut_normalizado and cliente_por_rut is None:
        confirmaciones_del_rut = [c for c in confirmaciones if c.dominio == "CLIENTE" and c.contexto_clave == rut_normalizado]
        if confirmaciones_del_rut:
            por_valor: dict[str, list[ConfirmacionIdentidad]] = {}
            for confirmacion in confirmaciones_del_rut:
                por_valor.setdefault(confirmacion.valor_confirmado, []).append(confirmacion)
            for valor_confirmado, lista in por_valor.items():
                independientes = transportes_independientes(lista)
                if independientes >= UMBRAL_CONFIRMACIONES_PARA_CONOCIMIENTO_FUERTE:
                    identificador = lista[0].identificador_confirmado or valor_confirmado
                    coincide_texto = bool(documental) and normalizar_nombre_cliente(documental) == normalizar_nombre_cliente(valor_confirmado)
                    conflictos = () if coincide_texto or not documental else ("TEXTO_DOCUMENTAL_DIFIERE",)
                    candidatos.append(CandidatoEvidencia(
                        identificador=identificador, valor_canonico=valor_confirmado,
                        nivel=NIVEL_CONFIRMACION_HUMANA,
                        evidencias=(f"CONFIRMACIONES_INDEPENDIENTES({independientes})",), conflictos=conflictos,
                        razon_legible=(
                            f'Atlas considera "{valor_confirmado}" porque un humano ya confirmó, en '
                            f"{independientes} transportes independientes, que este RUT corresponde a esa entidad."
                            + (f' La guía de hoy dice "{documental}", un valor distinto.' if conflictos else "")
                        ),
                        metadatos={"transportes_independientes": independientes, "guias": tuple(c.numero_guia for c in lista)},
                    ))
                elif independientes == 1 and documental and normalizar_nombre_cliente(documental) != normalizar_nombre_cliente(lista[0].valor_confirmado):
                    # Una sola confirmación previa: todavía más débil que
                    # un match estructural (RUT canónico) -- sigue siendo
                    # sólo una sugerencia, no "conocimiento fuerte" ni
                    # contradicción demostrada.
                    candidatos.append(CandidatoEvidencia(
                        identificador=lista[0].identificador_confirmado or valor_confirmado,
                        valor_canonico=valor_confirmado, nivel=NIVEL_DOCUMENTAL_DEBIL,
                        evidencias=("CONFIRMACION_HUMANA_PREVIA_UNICA",), conflictos=("TEXTO_DOCUMENTAL_DIFIERE",),
                        razon_legible=(
                            f'Atlas considera "{valor_confirmado}" porque un humano ya confirmó una vez, para '
                            f"este RUT, que corresponde a esa entidad. La guía de hoy dice \"{documental}\", "
                            "un valor distinto -- todavía falta una segunda confirmación independiente."
                        ),
                        metadatos={"transportes_independientes": 1},
                    ))

    # 3) Evidencia externa (inyectada, nunca red desde aquí).
    for evidencia in evidencia_externa:
        coincide_texto = (
            bool(documental) and bool(evidencia.razon_social)
            and normalizar_nombre_cliente(documental) == normalizar_nombre_cliente(evidencia.razon_social)
        )
        texto_difiere = (
            () if coincide_texto or not documental or not evidencia.razon_social
            else ("TEXTO_DOCUMENTAL_DIFIERE",)
        )
        conflictos_externos = tuple(evidencia.contradicciones) + texto_difiere
        candidatos.append(_candidato_desde_externa(
            evidencia, conflictos=conflictos_externos,
            razon=(
                f'Atlas considera "{evidencia.razon_social}" porque una fuente externa '
                f"({evidencia.tipo_fuente.lower()}: {evidencia.fuente}) corrobora "
                f"{', '.join(evidencia.campos_corroborados) or 'esta identidad'}."
                + (f" Contradicciones detectadas: {', '.join(conflictos_externos)}." if conflictos_externos else "")
            ),
        ))

    if not candidatos:
        if estado_rut == RUT_INVALIDO:
            return ResultadoEvidencia(
                resultado=RESULTADO_ABSTENCION_REAL,
                explicacion=f'No puedo determinarlo con seguridad: el RUT documental "{rut_documental}" no es válido y no hay ninguna otra evidencia.',
            )
        # Sin candidato rival y sin evidencia en contra -- entidad
        # genuinamente nueva y plausible.
        return ResultadoEvidencia(
            resultado=RESULTADO_ALTA_NUEVA,
            explicacion=f'"{documental}" no coincide con ningún cliente conocido; no hay evidencia que lo contradiga.',
        )

    if hay_empate_en_el_tope(tuple(candidatos)):
        return ResultadoEvidencia(
            resultado=RESULTADO_SUGERENCIA_HUMANA, candidatos=tuple(candidatos),
            explicacion="Hay más de una candidata igualmente respaldada -- Atlas no elige arbitrariamente entre ellas.",
        )

    mejor = elegir_mejor_candidato(tuple(candidatos))
    assert mejor is not None
    if not mejor.conflictos:
        # El texto documental ya coincide (o no hay texto que comparar):
        # no hay contradicción que resolver.
        return ResultadoEvidencia(
            resultado=RESULTADO_RESUELTO_AUTOMATICAMENTE, candidatos=tuple(candidatos), explicacion=mejor.razon_legible,
        )
    if mejor.nivel == NIVEL_CONFIRMACION_HUMANA:
        return ResultadoEvidencia(
            resultado=RESULTADO_RESUELTO_AUTOMATICAMENTE, candidatos=tuple(candidatos), explicacion=mejor.razon_legible,
        )
    if mejor.nivel in (NIVEL_EXTERNO_OFICIAL, NIVEL_EXTERNO_CORPORATIVO, NIVEL_DOCUMENTAL_INDEPENDIENTE):
        return ResultadoEvidencia(
            resultado=RESULTADO_CONTRADICCION_DOCUMENTAL, candidatos=tuple(candidatos), explicacion=mejor.razon_legible,
        )
    return ResultadoEvidencia(
        resultado=RESULTADO_SUGERENCIA_HUMANA, candidatos=tuple(candidatos), explicacion=mejor.razon_legible,
    )
