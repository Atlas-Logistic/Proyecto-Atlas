"""Consultas Atlas V1 -- pregunta natural sobre la operación real,
respondida con cifras que salen SIEMPRE del dataset ya persistido
(`viajes.csv`, el mismo reporte que ya consume Desktop), nunca de un
LLM. Separación estricta (Bloque 1 del ticket):

    INTERPRETACIÓN (natural language -> `ConsultaAtlas`, determinística
    cuando es posible, B1 sólo cuando hace falta -- ver
    `interpretador_consultas.py`)
    vs
    CÁLCULO (`ejecutar_consulta_atlas`, siempre este módulo, siempre
    determinístico, nunca el LLM).

Read-only: este módulo nunca escribe nada -- ni al dataset, ni a
catálogos, ni a `decisiones_pendientes.json`. Sólo lee `viajes.csv` y
devuelve un `ResultadoConsultaAtlas`."""

from __future__ import annotations

import csv
import unicodedata
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Mapping, Sequence

SEPARADOR_MULTIVALOR = " | "

# --- Bloque 3: métricas V1 -- exactamente las que el dataset real puede
# calcular sin inventar ningún dato. ---
METRICA_COUNT_VIAJES = "COUNT_VIAJES"
METRICA_COUNT_GUIAS = "COUNT_GUIAS"
METRICA_SUM_PESO = "SUM_PESO"
METRICA_SUM_KM = "SUM_KM"
METRICA_SUM_TIEMPO = "SUM_TIEMPO"
METRICA_LISTAR_VIAJES = "LISTAR_VIAJES"
METRICAS_SOPORTADAS = frozenset({
    METRICA_COUNT_VIAJES, METRICA_COUNT_GUIAS, METRICA_SUM_PESO,
    METRICA_SUM_KM, METRICA_SUM_TIEMPO, METRICA_LISTAR_VIAJES,
})
_UNIDADES_POR_METRICA = {
    METRICA_COUNT_VIAJES: "viajes", METRICA_COUNT_GUIAS: "guías",
    METRICA_SUM_PESO: "kg", METRICA_SUM_KM: "km", METRICA_SUM_TIEMPO: "min",
    METRICA_LISTAR_VIAJES: "viajes",
}

# --- Bloque 2: filtros V1 -- sólo campos que `viajes.csv` realmente
# trae (ver `reporte_viajes.py`). Cada filtro mapea a UNA columna real
# del reporte -- nunca un campo inventado. ---
_CAMPO_A_COLUMNA = {
    "chofer": "choferes", "cliente": "clientes", "obra": "obras_destino",
    "destino": "direccion_entrega", "comuna": "localidad_entrega",
    "material": "materiales", "tipo_carga": "tipos_carga",
    "patente_tracto": "patentes_tracto", "patente_rampla": "patentes_rampla",
    "estado": "estado", "numero_guia": "numeros_guia",
    "numero_transporte": "numero_transporte",
}
# Columnas cuyo valor real puede traer varios elementos separados por
# `SEPARADOR_MULTIVALOR` (ver `reporte_viajes.py` -- consolidación de
# viaje). `numero_transporte`/`estado` son siempre un único valor.
_COLUMNAS_MULTIVALOR = frozenset({
    "choferes", "clientes", "obras_destino", "materiales", "tipos_carga",
    "patentes_tracto", "patentes_rampla", "numeros_guia",
})
# Filtros cuyo valor se compara por SUBCADENA (texto libre, sin
# catálogo finito de valores posibles -- Bloque 7: "material" es
# descripción libre, nunca una enumeración cerrada como tipo_carga).
_FILTROS_SUBCADENA = frozenset({"material", "destino"})
FILTROS_SOPORTADOS = frozenset(_CAMPO_A_COLUMNA) | frozenset({
    "periodo", "fecha_desde", "fecha_hasta",
})

# --- Bloque 4: agrupaciones V1. ---
AGRUPACIONES_SOPORTADAS = frozenset({
    "chofer", "cliente", "obra", "destino", "comuna", "material",
    "tipo_carga", "dia", "semana", "mes",
})

# --- Bloque 5: períodos V1 -- resueltos de forma determinística, nunca
# por el LLM (Bloque 5 del ticket: "no dejar que B1 invente fechas"). ---
PERIODO_HOY = "HOY"
PERIODO_AYER = "AYER"
PERIODO_ESTA_SEMANA = "ESTA_SEMANA"
PERIODO_SEMANA_PASADA = "SEMANA_PASADA"
PERIODO_ESTE_MES = "ESTE_MES"
PERIODO_MES_PASADO = "MES_PASADO"
PERIODOS_SOPORTADOS = frozenset({
    PERIODO_HOY, PERIODO_AYER, PERIODO_ESTA_SEMANA, PERIODO_SEMANA_PASADA,
    PERIODO_ESTE_MES, PERIODO_MES_PASADO,
})


class ErrorConsultaAtlas(ValueError):
    """Consulta inválida -- métrica/filtro/agrupación/período inexistente,
    o fecha con formato inválido. Nunca se ejecuta una consulta que no
    pasó esta validación (Bloque 20: "validador rechaza")."""


@dataclass(frozen=True)
class ConsultaAtlas:
    """Contrato mínimo y extensible (Bloque 2). `filtros` ya trae
    valores CANÓNICOS resueltos (nunca texto parcial del usuario sin
    resolver -- eso es trabajo del interpretador, no del ejecutor)."""

    metrica: str
    filtros: Mapping[str, str] = field(default_factory=dict)
    agrupacion: str | None = None
    orden: str = "DESC"
    limite: int | None = None


@dataclass(frozen=True)
class ResultadoConsultaAtlas:
    """Salida estructurada (Bloque 8). `resultado` es un número cuando
    no hay `agrupacion` y la métrica no es `LISTAR_VIAJES`; una lista de
    `{"grupo": ..., "valor": ...}` cuando hay `agrupacion`; o la lista
    de viajes soporte tal cual cuando la métrica es `LISTAR_VIAJES`.
    `viajes_soporte` SIEMPRE trae las filas reales que sustentan la
    respuesta (Bloque 9: trazabilidad) -- nunca sólo un número."""

    consulta_interpretada: ConsultaAtlas
    resultado: object
    unidades: str
    total_coincidencias: int
    viajes_soporte: tuple[Mapping[str, str], ...]
    advertencias: tuple[str, ...] = ()


def validar_consulta(consulta: ConsultaAtlas) -> None:
    """Bloque 20 -- rechaza cualquier métrica/filtro/agrupación/período
    que el dataset real no soporte. Se llama SIEMPRE antes de ejecutar,
    tanto si la consulta la armó el interpretador determinístico como
    si la armó B1."""
    if consulta.metrica not in METRICAS_SOPORTADAS:
        raise ErrorConsultaAtlas(f"Métrica no soportada: {consulta.metrica!r}")
    for campo in consulta.filtros:
        if campo not in FILTROS_SOPORTADOS:
            raise ErrorConsultaAtlas(f"Filtro no soportado: {campo!r}")
    if consulta.agrupacion is not None and consulta.agrupacion not in AGRUPACIONES_SOPORTADAS:
        raise ErrorConsultaAtlas(f"Agrupación no soportada: {consulta.agrupacion!r}")
    periodo = consulta.filtros.get("periodo")
    if periodo is not None and periodo not in PERIODOS_SOPORTADOS:
        raise ErrorConsultaAtlas(f"Período no soportado: {periodo!r}")
    if consulta.orden not in ("ASC", "DESC"):
        raise ErrorConsultaAtlas(f"Orden no soportado: {consulta.orden!r}")
    for clave in ("fecha_desde", "fecha_hasta"):
        valor = consulta.filtros.get(clave)
        if valor is not None and _parsear_fecha_iso(valor) is None:
            raise ErrorConsultaAtlas(f"{clave} inválida: {valor!r}")


def resolver_periodo(nombre: str, *, hoy: date) -> tuple[date, date]:
    """Bloque 5 -- resolución determinística de período, siempre
    después de interpretar la intención (nunca antes: el LLM nunca ve
    ni produce una fecha concreta, sólo el NOMBRE del período)."""
    if nombre == PERIODO_HOY:
        return hoy, hoy
    if nombre == PERIODO_AYER:
        ayer = hoy - timedelta(days=1)
        return ayer, ayer
    if nombre == PERIODO_ESTA_SEMANA:
        inicio = hoy - timedelta(days=hoy.weekday())
        return inicio, hoy
    if nombre == PERIODO_SEMANA_PASADA:
        inicio_esta = hoy - timedelta(days=hoy.weekday())
        inicio_pasada = inicio_esta - timedelta(days=7)
        fin_pasada = inicio_esta - timedelta(days=1)
        return inicio_pasada, fin_pasada
    if nombre == PERIODO_ESTE_MES:
        return hoy.replace(day=1), hoy
    if nombre == PERIODO_MES_PASADO:
        fin_mes_pasado = hoy.replace(day=1) - timedelta(days=1)
        return fin_mes_pasado.replace(day=1), fin_mes_pasado
    raise ErrorConsultaAtlas(f"Período no soportado: {nombre!r}")


def cargar_viajes(ruta_csv: str | Path) -> list[dict[str, str]]:
    """Lee el reporte oficial `viajes.csv` (el mismo que Desktop ya
    consume) -- ninguna otra fuente. Read-only, sin caché propia (el
    dataset ya es pequeño; recalcular siempre evita servir un resultado
    obsoleto tras una revalidación)."""
    with Path(ruta_csv).open("r", newline="", encoding="utf-8-sig") as archivo:
        return list(csv.DictReader(archivo, delimiter=";"))


def _valores_multivalor(viaje: Mapping[str, str], columna: str) -> tuple[str, ...]:
    crudo = str(viaje.get(columna, "")).strip()
    if not crudo:
        return ()
    return tuple(v.strip() for v in crudo.split(SEPARADOR_MULTIVALOR) if v.strip())


def normalizar_texto_atlas(texto: str) -> str:
    """Misma normalización ya usada en todo Atlas (mayúsculas, sin
    acentos, espacios colapsados) -- nunca una tercera variante."""
    mayuscula = " ".join(str(texto or "").strip().upper().split())
    sin_acentos = unicodedata.normalize("NFKD", mayuscula)
    return "".join(c for c in sin_acentos if not unicodedata.combining(c))


def _parsear_fecha_dataset(texto: str) -> date | None:
    """`viajes.csv.fecha` viene DD-MM-YYYY (mismo formato documental
    que usa el resto de Motor)."""
    try:
        return datetime.strptime(str(texto or "").strip(), "%d-%m-%Y").date()
    except ValueError:
        return None


def _parsear_fecha_iso(texto: str) -> date | None:
    try:
        return date.fromisoformat(str(texto or "").strip())
    except ValueError:
        return None


def _num(texto: str) -> float:
    try:
        return float(str(texto or "").strip())
    except ValueError:
        return 0.0


def _rango_fecha_de_consulta(consulta: ConsultaAtlas) -> tuple[date, date] | None:
    periodo = consulta.filtros.get("periodo")
    if periodo is not None:
        return resolver_periodo(periodo, hoy=date.today())
    desde = consulta.filtros.get("fecha_desde")
    hasta = consulta.filtros.get("fecha_hasta")
    if desde is None and hasta is None:
        return None
    fecha_desde = _parsear_fecha_iso(desde) if desde is not None else date.min
    fecha_hasta = _parsear_fecha_iso(hasta) if hasta is not None else date.max
    return fecha_desde, fecha_hasta


def _fila_coincide(
    viaje: Mapping[str, str], consulta: ConsultaAtlas, rango_fecha: tuple[date, date] | None,
) -> bool:
    if rango_fecha is not None:
        fecha = _parsear_fecha_dataset(viaje.get("fecha", ""))
        if fecha is None or not (rango_fecha[0] <= fecha <= rango_fecha[1]):
            return False
    for campo, valor in consulta.filtros.items():
        if campo in ("periodo", "fecha_desde", "fecha_hasta"):
            continue
        columna = _CAMPO_A_COLUMNA[campo]
        valor_normalizado = normalizar_texto_atlas(valor)
        if columna in _COLUMNAS_MULTIVALOR:
            valores = _valores_multivalor(viaje, columna)
        else:
            valores = (str(viaje.get(columna, "")).strip(),)
        if campo in _FILTROS_SUBCADENA:
            if not any(valor_normalizado in normalizar_texto_atlas(v) for v in valores):
                return False
        else:
            if not any(normalizar_texto_atlas(v) == valor_normalizado for v in valores):
                return False
    return True


def _valor_metrica(viaje: Mapping[str, str], metrica: str) -> float:
    if metrica == METRICA_COUNT_VIAJES:
        return 1.0
    if metrica == METRICA_COUNT_GUIAS:
        return float(len(_valores_multivalor(viaje, "numeros_guia")) or (1 if str(viaje.get("numeros_guia", "")).strip() else 0))
    if metrica == METRICA_SUM_PESO:
        return _num(viaje.get("peso_total_viaje_kg"))
    if metrica == METRICA_SUM_KM:
        return _num(viaje.get("distancia_km"))
    if metrica == METRICA_SUM_TIEMPO:
        return _num(viaje.get("duracion_min"))
    return 0.0


_COLUMNA_AGRUPACION = {
    "chofer": "choferes", "cliente": "clientes", "obra": "obras_destino",
    "destino": "direccion_entrega", "comuna": "localidad_entrega",
    "material": "materiales", "tipo_carga": "tipos_carga",
}


def _claves_agrupacion(viaje: Mapping[str, str], agrupacion: str) -> tuple[str, ...]:
    if agrupacion == "dia":
        fecha = _parsear_fecha_dataset(viaje.get("fecha", ""))
        return (fecha.isoformat(),) if fecha else ()
    if agrupacion == "semana":
        fecha = _parsear_fecha_dataset(viaje.get("fecha", ""))
        if fecha is None:
            return ()
        inicio_semana = fecha - timedelta(days=fecha.weekday())
        return (f"Semana del {inicio_semana.isoformat()}",)
    if agrupacion == "mes":
        fecha = _parsear_fecha_dataset(viaje.get("fecha", ""))
        return (fecha.strftime("%Y-%m"),) if fecha else ()
    columna = _COLUMNA_AGRUPACION[agrupacion]
    if columna in _COLUMNAS_MULTIVALOR:
        return _valores_multivalor(viaje, columna)
    valor = str(viaje.get(columna, "")).strip()
    return (valor,) if valor else ()


def ejecutar_consulta_atlas(
    consulta: ConsultaAtlas, viajes: Sequence[Mapping[str, str]],
) -> ResultadoConsultaAtlas:
    """Bloque 8 -- ejecutor determinístico. Única autoridad de cálculo
    de Atlas: filtra, agrupa, suma/cuenta, ordena y devuelve las filas
    soporte reales -- nunca un número que no pueda inspeccionarse
    (Bloque 9). Nunca escribe nada (Bloque 18: read-only)."""
    validar_consulta(consulta)
    rango_fecha = _rango_fecha_de_consulta(consulta)
    coincidencias = [v for v in viajes if _fila_coincide(v, consulta, rango_fecha)]
    unidades = _UNIDADES_POR_METRICA[consulta.metrica]

    if consulta.metrica == METRICA_LISTAR_VIAJES:
        filas = list(coincidencias)
        filas.sort(key=lambda v: _parsear_fecha_dataset(v.get("fecha", "")) or date.min, reverse=(consulta.orden == "DESC"))
        if consulta.limite is not None:
            filas = filas[: consulta.limite]
        return ResultadoConsultaAtlas(
            consulta_interpretada=consulta, resultado=tuple(filas), unidades=unidades,
            total_coincidencias=len(coincidencias), viajes_soporte=tuple(filas),
        )

    if consulta.agrupacion is None:
        total = sum(_valor_metrica(v, consulta.metrica) for v in coincidencias)
        if consulta.metrica == METRICA_COUNT_VIAJES:
            total = int(total)
        return ResultadoConsultaAtlas(
            consulta_interpretada=consulta, resultado=total, unidades=unidades,
            total_coincidencias=len(coincidencias), viajes_soporte=tuple(coincidencias),
        )

    acumulado: dict[str, float] = {}
    filas_por_grupo: dict[str, list[Mapping[str, str]]] = {}
    for viaje in coincidencias:
        claves = _claves_agrupacion(viaje, consulta.agrupacion)
        for clave in claves:
            acumulado[clave] = acumulado.get(clave, 0.0) + _valor_metrica(viaje, consulta.metrica)
            filas_por_grupo.setdefault(clave, []).append(viaje)

    filas_resultado = [
        {"grupo": clave, "valor": (int(valor) if consulta.metrica == METRICA_COUNT_VIAJES else valor)}
        for clave, valor in acumulado.items()
    ]
    filas_resultado.sort(key=lambda f: f["valor"], reverse=(consulta.orden == "DESC"))
    if consulta.limite is not None:
        filas_resultado = filas_resultado[: consulta.limite]
    grupos_incluidos = {f["grupo"] for f in filas_resultado}
    soporte: list[Mapping[str, str]] = []
    vistos: set[int] = set()
    for grupo in grupos_incluidos:
        for viaje in filas_por_grupo.get(grupo, ()):
            if id(viaje) not in vistos:
                vistos.add(id(viaje))
                soporte.append(viaje)

    return ResultadoConsultaAtlas(
        consulta_interpretada=consulta, resultado=tuple(filas_resultado), unidades=unidades,
        total_coincidencias=len(coincidencias), viajes_soporte=tuple(soporte),
    )
