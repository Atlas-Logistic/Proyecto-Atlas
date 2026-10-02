"""Soporte SEMÁNTICO de una respuesta de Consultas Atlas (sólo presentación).

Caso real (Desktop, 2026-10-02): "cuantos choferes tenemos confirmados en
atlas" respondía "19 choferes." y "Ver soporte" mostraba 355 filas de
viajes (fecha, guía, cliente, material, km...): no era la evidencia de la
cifra. El soporte debe mostrar las entidades que componen la respuesta:

- conteo/listado de choferes -> los choferes contados;
- conteo/listado de clientes, obras, patentes, destinos... -> esos valores;
- conteo de guías -> las guías;
- listado/conteo de viajes -> los viajes;
- agregados (kg, km, tiempo, agrupaciones) -> sólo los viajes que aportan
  al cálculo, con la columna del valor sumado.

Nunca recalcula la respuesta ni inventa filas: deriva todo de las filas ya
devueltas por el ejecutor (`viajes_soporte`) con los mismos helpers de
`consultas_atlas`. Nunca expone identificadores internos ni datos técnicos.
Devuelve None cuando no hay un soporte semántico mejor que el actual
(Desktop conserva entonces su presentación de siempre)."""
from __future__ import annotations

from collections import Counter
from typing import Mapping, Sequence

from atlas_core.consultas_atlas import (
    _CHOFERES_AUSENTES, _COLUMNA_RELACION, _COLUMNAS_MULTIVALOR, DOMINIO_ASOCIACIONES_PATENTE_CHOFER,
    DOMINIO_VIAJES, METRICA_COUNT_DISTINCT_CHOFER, METRICA_COUNT_DISTINCT_RELACION, METRICA_COUNT_GUIAS,
    METRICA_COUNT_PATENTES_SIN_CHOFER, METRICA_COUNT_VIAJES, METRICA_LIST_DISTINCT_CHOFER,
    METRICA_LIST_RELACION, METRICA_LISTAR_VIAJES, METRICA_SUM_KM, METRICA_SUM_PESO, METRICA_SUM_TIEMPO,
    ResultadoConsultaAtlas, _claves_agrupacion, _guias_coincidentes, _valor_metrica, _valores_multivalor,
    normalizar_texto_atlas,
)

# Entidad (singular/plural) y encabezado por relación -- siempre lenguaje humano.
_ENTIDAD_RELACION = {
    "chofer": ("CHOFERES", "Chofer", "chofer", "choferes"),
    "cliente": ("CLIENTES", "Cliente", "cliente", "clientes"),
    "obra": ("OBRAS", "Obra", "obra", "obras"),
    "destino": ("DESTINOS", "Destino", "destino", "destinos"),
    "comuna": ("COMUNAS", "Comuna", "comuna", "comunas"),
    "material": ("MATERIALES", "Material", "material", "materiales"),
    "tipo_carga": ("TIPOS_CARGA", "Tipo de carga", "tipo de carga", "tipos de carga"),
    "guia": ("GUIAS", "Guía", "guía", "guías"),
    "patente_tracto": ("PATENTES", "Patente", "patente", "patentes"),
    "patente_rampla": ("PATENTES", "Patente", "patente", "patentes"),
    "vehiculo": ("PATENTES", "Patente", "patente", "patentes"),
    "transporte": ("TRANSPORTES", "Transporte", "transporte", "transportes"),
}
_COLUMNA_VALOR_AGREGADO = {
    METRICA_SUM_PESO: ("peso_total_viaje_kg", "Kg"),
    METRICA_SUM_KM: ("distancia_km", "Km calculados"),
    METRICA_SUM_TIEMPO: ("duracion_min", "Minutos"),
}


def _texto(valor: object) -> str:
    return str(valor if valor is not None else "").strip()


def _soporte(tipo: str, columnas: Sequence[str], filas: Sequence[Sequence[object]], *, resumen: str) -> dict:
    return {
        "tipo": tipo, "resumen": resumen, "columnas": list(columnas),
        "filas": [[_texto(c) for c in fila] for fila in filas],
    }


def _plural(n: int, singular: str, plural: str) -> str:
    return f"{n} {singular if n == 1 else plural}"


def _entidades_con_viajes(
    viajes: Sequence[Mapping[str, str]], extraer, *, excluir: frozenset[str] = frozenset(),
) -> list[tuple[str, int]]:
    """Valores distintos (por identidad normalizada, mostrando la grafía
    más frecuente) con la cantidad de viajes en que aparecen."""
    grafias: dict[str, Counter] = {}
    viajes_por_clave: Counter = Counter()
    for viaje in viajes:
        claves_viaje: set[str] = set()
        for valor in extraer(viaje):
            texto = _texto(valor)
            clave = normalizar_texto_atlas(texto)
            if not texto or clave in excluir:
                continue
            grafias.setdefault(clave, Counter())[texto] += 1
            claves_viaje.add(clave)
        viajes_por_clave.update(claves_viaje)
    filas = [(grafias[c].most_common(1)[0][0], viajes_por_clave[c]) for c in grafias]
    return sorted(filas, key=lambda f: (-f[1], f[0]))


def _fila_viaje(viaje: Mapping[str, str], *extra: str) -> list[str]:
    return [
        _texto(viaje.get("fecha")), _texto(viaje.get("numero_transporte")),
        _texto(viaje.get("numeros_guia")), _texto(viaje.get("choferes")), _texto(viaje.get("clientes")), *extra,
    ]


_COLUMNAS_VIAJE = ["Fecha", "Transporte", "Guías", "Chofer", "Cliente"]


def soporte_semantico(resultado: ResultadoConsultaAtlas) -> dict | None:
    consulta = resultado.consulta_interpretada
    viajes = list(resultado.viajes_soporte)
    metrica = consulta.metrica

    if consulta.dominio == DOMINIO_ASOCIACIONES_PATENTE_CHOFER and metrica == METRICA_COUNT_PATENTES_SIN_CHOFER:
        filas = [[r.get("patente"), r.get("transportes_soporte"), r.get("guias_soporte")] for r in viajes]
        return _soporte("PATENTES", ["Patente", "Transportes", "Guías"], filas,
                        resumen=_plural(len(filas), "patente sin chofer asociado", "patentes sin chofer asociado"))
    if consulta.dominio != DOMINIO_VIAJES:
        return None  # incidencias/eventos ya tienen su propia vista semántica en Desktop

    if metrica in (METRICA_COUNT_DISTINCT_CHOFER, METRICA_LIST_DISTINCT_CHOFER):
        entidades = _entidades_con_viajes(
            viajes, lambda v: _valores_multivalor(v, "choferes"), excluir=_CHOFERES_AUSENTES,
        )
        return _soporte("CHOFERES", ["Chofer", "Viajes"], entidades,
                        resumen=_plural(len(entidades), "chofer", "choferes"))

    if metrica in (METRICA_LIST_RELACION, METRICA_COUNT_DISTINCT_RELACION) and consulta.relacion:
        tipo, encabezado, singular, plural = _ENTIDAD_RELACION.get(
            consulta.relacion, ("VALORES", "Valor", "valor", "valores"),
        )
        if consulta.relacion == "guia":
            filas = [
                [guia, _texto(v.get("numero_transporte")), _texto(v.get("fecha"))]
                for v in viajes for guia in _guias_coincidentes(v, consulta)
            ]
            filas = sorted({tuple(f) for f in filas}, key=lambda f: f[0])
            return _soporte("GUIAS", ["Guía", "Transporte", "Fecha"], filas,
                            resumen=_plural(len(filas), "guía", "guías"))
        if consulta.relacion == "vehiculo":
            extraer = lambda v: (*_valores_multivalor(v, "patentes_tracto"), *_valores_multivalor(v, "patentes_rampla"))  # noqa: E731
        else:
            columna = _COLUMNA_RELACION[consulta.relacion]
            extraer = (
                (lambda v, c=columna: _valores_multivalor(v, c)) if columna in _COLUMNAS_MULTIVALOR
                else (lambda v, c=columna: (_texto(v.get(c)),))
            )
        entidades = _entidades_con_viajes(viajes, extraer, excluir=frozenset({"", "NO ENCONTRADO"}))
        return _soporte(tipo, [encabezado, "Viajes"], entidades, resumen=_plural(len(entidades), singular, plural))

    if metrica == METRICA_COUNT_GUIAS and consulta.agrupacion is None:
        filas = sorted({
            (guia, _texto(v.get("numero_transporte")), _texto(v.get("fecha")))
            for v in viajes for guia in _guias_coincidentes(v, consulta) if _texto(guia)
        }, key=lambda f: f[0])
        return _soporte("GUIAS", ["Guía", "Transporte", "Fecha"], filas, resumen=_plural(len(filas), "guía", "guías"))

    if metrica in _COLUMNA_VALOR_AGREGADO:
        _, encabezado = _COLUMNA_VALOR_AGREGADO[metrica]
        usados = [(v, _valor_metrica(v, metrica, consulta)) for v in viajes]
        usados = [(v, valor) for v, valor in usados if valor]
        filas = [_fila_viaje(v, f"{valor:g}") for v, valor in usados]
        return _soporte("VIAJES", [*_COLUMNAS_VIAJE, encabezado], filas,
                        resumen=_plural(len(filas), "viaje usado en el cálculo", "viajes usados en el cálculo"))

    if metrica in (METRICA_COUNT_VIAJES, METRICA_LISTAR_VIAJES) or consulta.agrupacion:
        columnas = list(_COLUMNAS_VIAJE)
        if consulta.agrupacion and consulta.agrupacion not in ("chofer", "cliente"):
            columnas.append(consulta.agrupacion.replace("_", " ").capitalize())
            filas = [_fila_viaje(v, " | ".join(_claves_agrupacion(v, consulta.agrupacion))) for v in viajes]
        else:
            filas = [_fila_viaje(v) for v in viajes]
        return _soporte("VIAJES", columnas, filas, resumen=_plural(len(filas), "viaje", "viajes"))
    return None
