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
        resultado_bruto = r.resultado
        if isinstance(resultado_bruto, tuple):
            # LISTAR_VIAJES: la propia lista de viajes es el "resultado".
            resultado_serializado = [_viaje_recortado(dict(v)) for v in resultado_bruto]
        else:
            resultado_serializado = resultado_bruto
        salida["resultado"] = {
            "consulta_interpretada": {
                "metrica": consulta.metrica, "filtros": dict(consulta.filtros),
                "agrupacion": consulta.agrupacion, "orden": consulta.orden, "limite": consulta.limite,
            },
            "resultado": resultado_serializado,
            "unidades": r.unidades,
            "total_coincidencias": r.total_coincidencias,
            "viajes_soporte": [_viaje_recortado(dict(v)) for v in r.viajes_soporte],
            "advertencias": list(r.advertencias),
        }
    return salida


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Consultas Atlas V1 -- responde una pregunta operacional.")
    parser.add_argument("pregunta")
    parser.add_argument("--viajes", required=True, help="Ruta a viajes.csv del reporte vigente.")
    args = parser.parse_args(argv)

    try:
        respuesta = responder_consulta_atlas(
            args.pregunta, ruta_viajes=args.viajes,
            proveedor_interpretacion=_proveedor_interpretacion_opcional(),
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
