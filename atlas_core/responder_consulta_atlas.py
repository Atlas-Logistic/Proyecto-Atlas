"""Consultas Atlas V1 -- orquestador de un extremo a otro (Bloque 22):

    pregunta -> interpretador -> ConsultaAtlas -> validador ->
    ejecutor determinístico -> ResultadoConsultaAtlas -> presentación.

Punto de entrada único que Desktop invoca (vía el CLI de
`atlas_core.cli_consulta_atlas`) -- nunca acopla la presentación
directamente al CSV ni duplica el cálculo del Motor (Bloque 22: "no
acoplar renderer directamente a CSV con lógica duplicada")."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from atlas_core.consultas_atlas import (
    DOMINIO_INCIDENCIAS_DOCUMENTALES,
    DOMINIO_VIAJES,
    METRICA_COUNT_DISTINCT_CHOFER,
    METRICA_COUNT_GUIAS,
    METRICA_COUNT_INCIDENCIAS,
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
    ejecutar_consulta_incidencias_documentales,
    validar_consulta,
)
from atlas_core.incidencias_documentales import AlmacenIncidenciasDocumentales
from atlas_core.interpretador_consultas import (
    CatalogosConsulta,
    construir_catalogos_consulta,
    interpretar_consulta_determinista,
    validar_compatibilidad_semantica,
)
from atlas_core.proveedor_interpretacion_consultas import ProveedorInterpretacionConsulta

# Bloque B1 V2 (Bloque 16 del ticket) -- observabilidad SÓLO en logs
# internos de depuración, nunca en la UI principal ni en el JSON que
# recibe Desktop. Nunca registra la credencial ni el prompt completo de
# B1 -- sólo la decisión (intención propuesta, incompatibilidades,
# si escaló a B1).
_registro = logging.getLogger(__name__)

ESTADO_OK = "OK"
ESTADO_AMBIGUA = "AMBIGUA"
ESTADO_SIN_RESULTADOS = "SIN_RESULTADOS"
ESTADO_NO_INTERPRETABLE = "NO_INTERPRETABLE"
ESTADO_CONSULTA_INVALIDA = "CONSULTA_INVALIDA"
# Bloque B1 V2.1 (regresión "3 -> 0 incidencias sin cambio real de
# datos") -- distingue "la fuente de incidencias nunca se indicó" (el
# llamador -- Desktop -- no pasó `ruta_incidencias`, casi siempre una
# raíz Atlas sin resolver o un proceso Desktop desactualizado) de
# "el repositorio real está vacío" (`ruta_incidencias` sí se indicó,
# el archivo simplemente no existe todavía -- eso SÍ es cero real,
# mismo criterio que ya usa `src/incidencias_documentales.js`).
# Nunca responder "0" con la misma confianza en ambos casos.
ESTADO_FUENTE_NO_DISPONIBLE = "FUENTE_NO_DISPONIBLE"


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


def _nota_cobertura_km(resultado: ResultadoConsultaAtlas) -> str | None:
    """Bloque 10 -- si sólo ALGUNOS de los viajes que cumplen el filtro
    tienen distancia calculada, decirlo brevemente en vez de sumar en
    silencio sólo sobre los que sí la tienen (Bloque 12: "responder con
    los datos disponibles y anotar la cobertura si es relevante")."""
    total = resultado.total_coincidencias
    if total <= 1:
        return None
    con_distancia = sum(
        1 for v in resultado.viajes_soporte
        if str(v.get("distancia_km", "")).strip() not in ("", "0", "0.0")
    )
    if con_distancia and con_distancia != total:
        return f"Disponible en {con_distancia} de {total} viaje{'s' if total != 1 else ''}."
    return None


def _formatear_respuesta_incidencias(resultado: ResultadoConsultaAtlas) -> str:
    """Bloque 4.A/12 -- dominio INCIDENCIAS_DOCUMENTALES: cuenta
    registros, tal como el repositorio canónico los entrega (nunca
    infiere contando viajes REVISAR)."""
    n = resultado.resultado
    texto = f"Hay {n} incidencia{'s' if n != 1 else ''} documental{'es' if n != 1 else ''} registrada{'s' if n != 1 else ''}."
    if resultado.advertencias:
        texto += f" {resultado.advertencias[0]}"
    return texto


def _formatear_respuesta(resultado: ResultadoConsultaAtlas) -> str:
    """Bloque 11 -- respuesta breve y operacional, nunca un párrafo de
    razonamiento B1. Bloque 13 -- cero resultados nunca es un error."""
    consulta = resultado.consulta_interpretada
    if consulta.dominio == DOMINIO_INCIDENCIAS_DOCUMENTALES:
        return _formatear_respuesta_incidencias(resultado)

    contexto = _filtros_legibles(consulta)
    sufijo_contexto = f" ({contexto})" if contexto else ""

    if consulta.metrica == METRICA_COUNT_DISTINCT_CHOFER:
        n = resultado.resultado
        if n == 0:
            return f"No encontré choferes con viajes que cumplan esos criterios{sufijo_contexto}."
        return f"{n} chofer{'es' if n != 1 else ''}{sufijo_contexto}."

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
        # Bloque 10 -- `distancia_km` es la distancia RUTEADA (ORS
        # driving-hgv, ver `reporte_viajes.py`), nunca un GPS real de
        # recorrido (eso no existe todavía -- Ruta GPS V1 no implementada).
        # Se nombra explícitamente "km calculados", nunca "km recorridos
        # reales".
        texto = f"{_formatear_numero(total)} km calculados{sufijo_contexto}."
        cobertura = _nota_cobertura_km(resultado)
        return f"{texto} {cobertura}" if cobertura else texto
    if consulta.metrica == METRICA_SUM_TIEMPO:
        return f"{_formatear_numero(total)} minutos{sufijo_contexto}."
    return f"{_formatear_numero(total)} {resultado.unidades}{sufijo_contexto}."


def _formatear_numero(valor: object) -> str:
    if isinstance(valor, int):
        return str(valor)
    return f"{float(valor):.2f}".rstrip("0").rstrip(".")


def _cargar_incidencias(ruta_incidencias: str | Path | None) -> list[dict[str, object]]:
    """Read-only (Bloque 18/9): usa el repositorio canónico, nunca una
    lectura paralela del JSON. Un archivo ausente no es un error --
    significa "todavía no hay ninguna Incidencia Documental registrada"
    (mismo criterio ya usado por `src/incidencias_documentales.js`)."""
    if ruta_incidencias is None or not Path(ruta_incidencias).is_file():
        return []
    return [i.a_dict() for i in AlmacenIncidenciasDocumentales(ruta_incidencias).listar()]


def responder_consulta_atlas(
    pregunta: str, *, ruta_viajes: str | Path, ruta_incidencias: str | Path | None = None,
    proveedor_interpretacion: ProveedorInterpretacionConsulta | None = None,
) -> RespuestaConsultaAtlas:
    """Punto de entrada único de Consultas Atlas V1. Read-only (Bloque
    18): nunca escribe nada, sólo lee `viajes.csv` y (dominio
    INCIDENCIAS_DOCUMENTALES) el repositorio canónico de incidencias.

    Pipeline (Bloque 7 del ticket):
        determinístico -> [validador semántico] -> B1 (sólo si hace
        falta) -> [validador semántico] -> validador estructural ->
        ejecutor determinístico -> presentación.
    Toda cifra sigue saliendo siempre del ejecutor -- B1 nunca produce
    una respuesta numérica final, sólo una `ConsultaAtlas`."""
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

    # Bloque 6/7 -- "estructuralmente válida" no basta: si el
    # determinístico propuso algo semánticamente incompatible con la
    # pregunta (Bloque 2: KM+COUNT_VIAJES, CHOFERES+COUNT_VIAJES,
    # INCIDENCIAS+dominio VIAJES, PESO+COUNT_VIAJES), se descarta esa
    # propuesta y se cede a B1 en vez de responder con un número que no
    # corresponde -- este es EXACTAMENTE el criterio que antes hacía que
    # B1 nunca interviniera.
    motivo_incompatibilidad: str | None = None
    if consulta is not None:
        motivo_incompatibilidad = validar_compatibilidad_semantica(pregunta, consulta)
        if motivo_incompatibilidad is not None:
            _registro.debug(
                "Consulta determinística descartada por incompatibilidad semántica: %s (métrica=%s dominio=%s)",
                motivo_incompatibilidad, consulta.metrica, consulta.dominio,
            )
            consulta = None
        else:
            _registro.debug(
                "Consulta determinística aceptada sin B1: métrica=%s dominio=%s", consulta.metrica, consulta.dominio,
            )

    if consulta is None:
        sin_coincidencia = next((a for a in avisos if a.startswith("SIN_COINCIDENCIA:")), None)
        if proveedor_interpretacion is not None:
            _registro.debug("Escalando a B1 (proveedor=%s)", getattr(proveedor_interpretacion, "nombre", "?"))
            consulta = proveedor_interpretacion.interpretar(pregunta, catalogos)
            if consulta is not None:
                motivo_b1 = validar_compatibilidad_semantica(pregunta, consulta)
                if motivo_b1 is not None:
                    _registro.debug("Consulta de B1 también incompatible: %s", motivo_b1)
                    consulta = None
                else:
                    _registro.debug("Consulta de B1 validada: métrica=%s dominio=%s", consulta.metrica, consulta.dominio)
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

    if consulta.dominio == DOMINIO_INCIDENCIAS_DOCUMENTALES:
        if ruta_incidencias is None:
            # Bloque B1 V2.1 -- nunca afirmar "0 incidencias" con la
            # misma confianza que un repositorio real y vacío: el
            # llamador ni siquiera indicó dónde está el repositorio
            # (Desktop sin raíz Atlas resuelta, o un proceso
            # desactualizado que todavía no pasa `--incidencias`).
            _registro.debug("Dominio INCIDENCIAS_DOCUMENTALES sin ruta_incidencias -- fuente no disponible")
            return RespuestaConsultaAtlas(
                estado=ESTADO_FUENTE_NO_DISPONIBLE,
                texto_respuesta=(
                    "No pude verificar las incidencias documentales -- no se indicó dónde está el "
                    "repositorio en este entorno. Esto no significa que no existan."
                ),
            )
        incidencias = _cargar_incidencias(ruta_incidencias)
        resultado = ejecutar_consulta_incidencias_documentales(consulta, incidencias)
    else:
        resultado = ejecutar_consulta_atlas(consulta, viajes)
    texto = _formatear_respuesta(resultado)
    estado = ESTADO_SIN_RESULTADOS if resultado.total_coincidencias == 0 else ESTADO_OK
    _registro.debug("Consulta ejecutada: métrica=%s dominio=%s resultado=%r", consulta.metrica, consulta.dominio, resultado.resultado)
    return RespuestaConsultaAtlas(estado=estado, texto_respuesta=texto, resultado=resultado)
