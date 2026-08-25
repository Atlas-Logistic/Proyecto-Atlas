"""Consultas Atlas V1 -- orquestador de un extremo a otro (Bloque 22):

    pregunta -> interpretador -> ConsultaAtlas -> validador ->
    ejecutor determinístico -> ResultadoConsultaAtlas -> presentación.

Punto de entrada único que Desktop invoca (vía el CLI de
`atlas_core.cli_consulta_atlas`) -- nunca acopla la presentación
directamente al CSV ni duplica el cálculo del Motor (Bloque 22: "no
acoplar renderer directamente a CSV con lógica duplicada")."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from atlas_core.consultas_atlas import (
    METRICA_COUNT_GUIAS,
    METRICA_COUNT_VIAJES,
    METRICA_LISTAR_VIAJES,
    METRICA_SUM_KM,
    METRICA_SUM_PESO,
    METRICA_SUM_TIEMPO,
    ConsultaAtlas,
    ErrorConsultaAtlas,
    ResultadoConsultaAtlas,
    cargar_viajes,
    ejecutar_consulta_atlas,
    validar_consulta,
)
from atlas_core.interpretador_consultas import (
    CatalogosConsulta,
    construir_catalogos_consulta,
    interpretar_consulta_determinista,
)
from atlas_core.proveedor_interpretacion_consultas import ProveedorInterpretacionConsulta

ESTADO_OK = "OK"
ESTADO_AMBIGUA = "AMBIGUA"
ESTADO_SIN_RESULTADOS = "SIN_RESULTADOS"
ESTADO_NO_INTERPRETABLE = "NO_INTERPRETABLE"
ESTADO_CONSULTA_INVALIDA = "CONSULTA_INVALIDA"


@dataclass(frozen=True)
class RespuestaConsultaAtlas:
    """Lo que Desktop necesita para presentar la respuesta (Bloque 11):
    `texto_respuesta` breve y operacional, nunca un párrafo de
    razonamiento; `resultado` trae siempre las filas soporte reales
    cuando `estado == OK` (Bloque 9: trazabilidad); `opciones_aclaracion`
    sólo se llena cuando `estado == AMBIGUA` (Bloque 14)."""

    estado: str
    texto_respuesta: str
    resultado: ResultadoConsultaAtlas | None = None
    opciones_aclaracion: tuple[str, ...] = ()


_NOMBRE_FILTRO_LEGIBLE = {
    "chofer": "chofer", "cliente": "cliente", "obra": "obra", "destino": "destino",
    "comuna": "comuna", "material": "material", "tipo_carga": "tipo de carga",
    "patente_tracto": "patente tracto", "patente_rampla": "patente rampla",
    "estado": "estado", "numero_guia": "guía", "numero_transporte": "transporte",
    "periodo": "período",
}
_NOMBRE_PERIODO_LEGIBLE = {
    "HOY": "hoy", "AYER": "ayer", "ESTA_SEMANA": "esta semana",
    "SEMANA_PASADA": "la semana pasada", "ESTE_MES": "este mes", "MES_PASADO": "el mes pasado",
}
_NOMBRE_AGRUPACION_LEGIBLE = {
    "chofer": "chofer", "cliente": "cliente", "obra": "obra", "destino": "destino",
    "comuna": "comuna", "material": "material", "tipo_carga": "tipo de carga",
    "dia": "día", "semana": "semana", "mes": "mes",
}


def _filtros_legibles(consulta: ConsultaAtlas) -> str:
    partes = []
    for campo, valor in consulta.filtros.items():
        if campo == "periodo":
            partes.append(_NOMBRE_PERIODO_LEGIBLE.get(valor, valor))
            continue
        etiqueta = _NOMBRE_FILTRO_LEGIBLE.get(campo, campo)
        partes.append(f"{etiqueta} {valor}")
    return ", ".join(partes)


def _formatear_respuesta(resultado: ResultadoConsultaAtlas) -> str:
    """Bloque 11 -- respuesta breve y operacional, nunca un párrafo de
    razonamiento B1. Bloque 13 -- cero resultados nunca es un error."""
    consulta = resultado.consulta_interpretada
    contexto = _filtros_legibles(consulta)
    sufijo_contexto = f" ({contexto})" if contexto else ""

    if consulta.metrica == METRICA_LISTAR_VIAJES:
        n = resultado.total_coincidencias
        if n == 0:
            return f"No encontré viajes que cumplan esos criterios{sufijo_contexto}."
        return f"Encontré {n} viaje{'s' if n != 1 else ''}{sufijo_contexto}."

    if consulta.agrupacion is not None:
        filas = resultado.resultado
        if not filas:
            return f"No encontré datos para agrupar por {_NOMBRE_AGRUPACION_LEGIBLE.get(consulta.agrupacion, consulta.agrupacion)}{sufijo_contexto}."
        top = filas[0]
        if consulta.metrica == METRICA_SUM_PESO:
            valor_top = f"{_formatear_numero(top['valor'] / 1000.0)} toneladas"
        else:
            valor_top = f"{_formatear_numero(top['valor'])} {resultado.unidades}"
        return (
            f"Resultados por {_NOMBRE_AGRUPACION_LEGIBLE.get(consulta.agrupacion, consulta.agrupacion)}"
            f"{sufijo_contexto} -- el primero: {top['grupo']} con {valor_top}."
        )

    total = resultado.resultado
    if consulta.metrica == METRICA_COUNT_VIAJES:
        if total == 0:
            return f"No encontré viajes que cumplan esos criterios{sufijo_contexto}."
        return f"{total} viaje{'s' if total != 1 else ''}{sufijo_contexto}."
    if consulta.metrica == METRICA_COUNT_GUIAS:
        return f"{int(total)} guía{'s' if total != 1 else ''}{sufijo_contexto}."
    if consulta.metrica == METRICA_SUM_PESO:
        toneladas = total / 1000.0
        return f"{_formatear_numero(toneladas)} toneladas ({_formatear_numero(total)} kg){sufijo_contexto}."
    if consulta.metrica == METRICA_SUM_KM:
        return f"{_formatear_numero(total)} km{sufijo_contexto}."
    if consulta.metrica == METRICA_SUM_TIEMPO:
        return f"{_formatear_numero(total)} minutos{sufijo_contexto}."
    return f"{_formatear_numero(total)} {resultado.unidades}{sufijo_contexto}."


def _formatear_numero(valor: object) -> str:
    if isinstance(valor, int):
        return str(valor)
    return f"{float(valor):.2f}".rstrip("0").rstrip(".")


def responder_consulta_atlas(
    pregunta: str, *, ruta_viajes: str | Path,
    proveedor_interpretacion: ProveedorInterpretacionConsulta | None = None,
) -> RespuestaConsultaAtlas:
    """Punto de entrada único de Consultas Atlas V1. Read-only (Bloque
    18): nunca escribe nada, sólo lee `viajes.csv`."""
    viajes = cargar_viajes(ruta_viajes)
    catalogos = construir_catalogos_consulta(viajes)

    consulta, avisos = interpretar_consulta_determinista(pregunta, catalogos=catalogos)

    ambiguos = [a for a in avisos if a.startswith("AMBIGUO:")]
    if ambiguos:
        campo, candidatos_texto = ambiguos[0].split(":", 2)[1:]
        candidatos = tuple(candidatos_texto.split(" | "))
        etiqueta = _NOMBRE_FILTRO_LEGIBLE.get(campo, campo)
        return RespuestaConsultaAtlas(
            estado=ESTADO_AMBIGUA,
            texto_respuesta=(
                f"Encontré más de un/a {etiqueta} que coincide con tu pregunta: "
                f"{', '.join(candidatos)}. ¿Cuál quieres consultar?"
            ),
            opciones_aclaracion=candidatos,
        )

    if consulta is None:
        sin_coincidencia = next((a for a in avisos if a.startswith("SIN_COINCIDENCIA:")), None)
        if proveedor_interpretacion is not None:
            consulta = proveedor_interpretacion.interpretar(pregunta, catalogos)
        if consulta is None:
            if sin_coincidencia is not None:
                nombres = sin_coincidencia.split(":", 1)[1]
                return RespuestaConsultaAtlas(
                    estado=ESTADO_NO_INTERPRETABLE,
                    texto_respuesta=f"No encontré a «{nombres}» entre los choferes, clientes u obras de la operación actual.",
                )
            return RespuestaConsultaAtlas(
                estado=ESTADO_NO_INTERPRETABLE,
                texto_respuesta="No pude interpretar esa pregunta como una consulta operacional de Atlas.",
            )

    try:
        validar_consulta(consulta)
    except ErrorConsultaAtlas as error:
        return RespuestaConsultaAtlas(estado=ESTADO_CONSULTA_INVALIDA, texto_respuesta=str(error))

    resultado = ejecutar_consulta_atlas(consulta, viajes)
    texto = _formatear_respuesta(resultado)
    estado = ESTADO_SIN_RESULTADOS if resultado.total_coincidencias == 0 else ESTADO_OK
    return RespuestaConsultaAtlas(estado=estado, texto_respuesta=texto, resultado=resultado)
