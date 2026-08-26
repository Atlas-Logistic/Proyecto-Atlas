"""Consultas Atlas V1 -- CLI invocado por Desktop (IPC `atlas:consultar-
atlas`, mismo patrón ya usado para `analizar_guias_masivo.py`/
`generar_reporte_viajes.py`: Desktop hace `spawn('py', ['-3', '-u',
...])` y lee la salida estándar). Imprime UN solo objeto JSON a stdout
-- nunca progreso línea por línea (esta consulta es instantánea, no
necesita barra de progreso).

Read-only (Bloque 18): sólo lee `viajes.csv`. B1 (Bloque 10/21) se
conecta SOLO si hay `ANTHROPIC_API_KEY` en el entorno -- sin ella, el
camino determinístico sigue funcionando igual; si además falla, la
respuesta es "no interpretable", nunca un error de proceso."""

from __future__ import annotations

import argparse
import json
import os
import sys

from atlas_core.consultas_atlas import DOMINIO_INCIDENCIAS_DOCUMENTALES, DOMINIO_VIAJES, METRICA_LIST_RELACION
from atlas_core.responder_consulta_atlas import RespuestaConsultaAtlas, responder_consulta_atlas


def _proveedor_interpretacion_opcional():
    if not os.getenv("ANTHROPIC_API_KEY", "").strip():
        return None
    from atlas_core.proveedor_interpretacion_consultas import ProveedorInterpretacionConsultaAnthropic
    return ProveedorInterpretacionConsultaAnthropic()


# Bloque 16 -- Desktop sólo necesita presentar el viaje, nunca la
# evidencia interna completa (JSON de métricas/atlas_ia, un documento
# por columna repetida) -- se recorta a las columnas que la tabla de
# soporte realmente muestra. Nunca se inventa una columna nueva: todas
# ya existen en `viajes.csv` (ver `reporte_viajes.py`).
_COLUMNAS_SOPORTE_DESKTOP = (
    "numero_transporte", "fecha", "numeros_guia", "clientes", "obras_destino",
    "choferes", "patentes_tracto", "materiales", "tipos_carga",
    "peso_total_viaje_kg", "distancia_km", "duracion_min",
    "direccion_entrega", "localidad_entrega", "estado_ruta", "estado",
)


def _viaje_recortado(viaje: dict) -> dict:
    return {columna: viaje.get(columna, "") for columna in _COLUMNAS_SOPORTE_DESKTOP}


def _respuesta_a_dict(respuesta: RespuestaConsultaAtlas) -> dict:
    salida: dict[str, object] = {
        "estado": respuesta.estado,
        "texto_respuesta": respuesta.texto_respuesta,
        "opciones_aclaracion": list(respuesta.opciones_aclaracion),
        "resultado": None,
    }
    if respuesta.resultado is not None:
        r = respuesta.resultado
        consulta = r.consulta_interpretada
        # Bloque B1 V2/UNIVERSAL V1 -- las filas de SOPORTE (`viajes_
        # soporte`) son siempre del dominio real de la consulta: viajes
        # para VIAJES, incidencias para INCIDENCIAS_DOCUMENTALES, eventos
        # para EVENTOS -- recortarlas con las columnas de un viaje fuera
        # del dominio VIAJES sólo produciría columnas vacías. Se pasan
        # tal cual fuera de VIAJES (nunca un secreto/prompt -- ver
        # `IncidenciaDocumental`/`eventos_operacionales`).
        recorte = _viaje_recortado if consulta.dominio == DOMINIO_VIAJES else (lambda v: dict(v))
        resultado_bruto = r.resultado
        if consulta.metrica == METRICA_LIST_RELACION:
            # LIST_RELACION: el "resultado" es una lista de VALORES
            # (strings), no de filas -- nunca pasa por un recorte de
            # columnas de viaje/incidencia (Bug real encontrado en este
            # bloque: el recorte de abajo, pensado sólo para
            # LISTAR_VIAJES, se aplicaba también a agrupaciones y hubiera
            # aplicado a listas de strings, vaciando el resultado).
            resultado_serializado = list(resultado_bruto)
        elif isinstance(resultado_bruto, tuple) and consulta.agrupacion is not None:
            # Agrupación (Bug real encontrado en este bloque): son filas
            # `{"grupo":..., "valor":...}`, NUNCA viajes/incidencias --
            # `_viaje_recortado` las vaciaba en silencio (todas las
            # columnas quedaban "") porque ninguna coincide con
            # "grupo"/"valor". Se pasan tal cual, ya son pequeñas.
            resultado_serializado = [dict(f) for f in resultado_bruto]
        elif isinstance(resultado_bruto, tuple):
            # LISTAR_VIAJES (o el listado de soporte de otro dominio): la
            # propia lista de filas es el "resultado".
            resultado_serializado = [recorte(dict(v)) for v in resultado_bruto]
        else:
            resultado_serializado = resultado_bruto
        salida["resultado"] = {
            "consulta_interpretada": {
                "metrica": consulta.metrica, "dominio": consulta.dominio, "filtros": dict(consulta.filtros),
                "agrupacion": consulta.agrupacion, "orden": consulta.orden, "limite": consulta.limite,
            },
            "resultado": resultado_serializado,
            "unidades": r.unidades,
            "total_coincidencias": r.total_coincidencias,
            "viajes_soporte": [recorte(dict(v)) for v in r.viajes_soporte],
            "advertencias": list(r.advertencias),
        }
    return salida


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Consultas Atlas V1 -- responde una pregunta operacional.")
    parser.add_argument("pregunta")
    parser.add_argument("--viajes", required=True, help="Ruta a viajes.csv del reporte vigente.")
    # Bloque B1 V2 -- dominio INCIDENCIAS_DOCUMENTALES (Bloque 4.A/9 del
    # ticket). Opcional: sin ella, ese dominio simplemente responde "0
    # incidencias" (mismo criterio ya usado por
    # `src/incidencias_documentales.js` -- archivo ausente no es error).
    parser.add_argument("--incidencias", default=None, help="Ruta a catalogos_privados/incidencias_documentales.json.")
    # Bloque UNIVERSAL V1 -- dominio EVENTOS (Bloque 9/13 del ticket).
    # Opcional: sin ella, ese dominio responde "no pude verificar" en
    # vez de "0" (Bloque 14, mismo criterio que INCIDENCIAS_DOCUMENTALES).
    parser.add_argument("--raiz-atlas", default=None, help="Raíz de datos Atlas (para operacion/mobile/envios).")
    args = parser.parse_args(argv)

    try:
        respuesta = responder_consulta_atlas(
            args.pregunta, ruta_viajes=args.viajes, ruta_incidencias=args.incidencias,
            raiz_atlas=args.raiz_atlas, proveedor_interpretacion=_proveedor_interpretacion_opcional(),
        )
    except Exception as error:  # nunca deja el proceso sin salida JSON parseable
        # Salida ASCII JSON: evita que la consola Windows recodifique los
        # mensajes UTF-8 antes de que Desktop haga JSON.parse (mismo
        # criterio ya establecido en aplicar_decision_pendiente.py).
        print(json.dumps({
            "estado": "ERROR", "texto_respuesta": f"No se pudo consultar Atlas: {error}",
            "opciones_aclaracion": [], "resultado": None,
        }, ensure_ascii=True))
        return 1

    print(json.dumps(_respuesta_a_dict(respuesta), ensure_ascii=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
