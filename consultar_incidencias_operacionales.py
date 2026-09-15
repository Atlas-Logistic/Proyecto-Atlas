"""CLI estrecho usado por Atlas Desktop para preguntas conversacionales
sobre incidencias operacionales ("Pregúntale a Atlas") -- V1.2, última
milla sobre atlas_core.gestion_incidencias_conversacional.responder_
consulta_incidencias_conversacional (V1.1, ya aprobado, sin cambios).

SOLO LECTURA. Adapta la salida de esa función (que trae un `origen`
propio para distinguir sus 3 caminos: delegado al motor genérico,
"no revisados", o "estado de gestión") al MISMO contrato JSON que
`atlas_core.cli_consulta_atlas` ya produce para `consultar_atlas.py` --
así Desktop reutiliza el renderer de "Pregúntale a Atlas" YA EXISTENTE
sin ninguna vista nueva (ver `renderResultadoConsulta` en
atlas_viajes.html), en vez de duplicar presentación."""
from __future__ import annotations

import argparse
import json
import sys

from atlas_core.cli_consulta_atlas import _respuesta_a_dict
from atlas_core.consultas_atlas import (
    DOMINIO_EVENTOS,
    DOMINIO_VIAJES,
    METRICA_COUNT_EVENTOS,
    METRICA_LIST_VIAJES,
    ConsultaAtlas,
    ResultadoConsultaAtlas,
)
from atlas_core.gestion_incidencias_conversacional import responder_consulta_incidencias_conversacional
from atlas_core.responder_consulta_atlas import RespuestaConsultaAtlas


def _aplanar_evento(evento: dict) -> dict:
    """Mismo aplanado ya usado por `responder_consulta_atlas._cargar_
    eventos` (chofer/cliente/obra al nivel superior, no sólo en
    `snapshot`) -- para que la tabla de soporte ya existente (que lee
    esos campos planos) los muestre igual que para cualquier otra
    consulta de eventos."""
    plano = dict(evento)
    snapshot = plano.get("snapshot") if isinstance(plano.get("snapshot"), dict) else {}
    plano.setdefault("chofer", str(snapshot.get("chofer", "")).strip())
    plano.setdefault("cliente", str(snapshot.get("cliente", "")).strip())
    plano.setdefault("obra", str(snapshot.get("obra", "")).strip())
    plano.setdefault("fecha", plano.get("fecha_operacional", ""))
    return plano


def _a_respuesta_estandar(datos: dict) -> RespuestaConsultaAtlas:
    origen = datos.get("origen")
    if origen == "DELEGADO_RESPONDER_CONSULTA_ATLAS":
        # Ya es exactamente lo que produce responder_consulta_atlas --
        # se reempaqueta tal cual, sin tocar nada.
        return RespuestaConsultaAtlas(
            estado=datos["estado"], texto_respuesta=datos["texto_respuesta"],
            resultado=datos.get("resultado"),
            opciones_aclaracion=tuple(datos.get("opciones_aclaracion") or ()),
        )
    if origen == "INCIDENCIAS_NO_REVISADAS":
        viajes = tuple(datos.get("viajes") or ())
        consulta = ConsultaAtlas(metrica=METRICA_LIST_VIAJES, dominio=DOMINIO_VIAJES, filtros={})
        resultado = ResultadoConsultaAtlas(
            consulta_interpretada=consulta, resultado=viajes, unidades="viajes",
            total_coincidencias=len(viajes), viajes_soporte=viajes,
        )
        return RespuestaConsultaAtlas(
            estado=datos["estado"], texto_respuesta=datos["texto_respuesta"], resultado=resultado,
            opciones_aclaracion=tuple(datos.get("opciones_aclaracion") or ()),
        )
    if origen == "INCIDENCIAS_GESTION":
        incidencias = tuple(_aplanar_evento(e) for e in (datos.get("incidencias") or ()))
        consulta = ConsultaAtlas(metrica=METRICA_COUNT_EVENTOS, dominio=DOMINIO_EVENTOS, filtros={})
        resultado = ResultadoConsultaAtlas(
            consulta_interpretada=consulta, resultado=len(incidencias), unidades="incidencias",
            total_coincidencias=len(incidencias), viajes_soporte=incidencias,
        )
        return RespuestaConsultaAtlas(estado=datos["estado"], texto_respuesta=datos["texto_respuesta"], resultado=resultado)
    # Estado sin `origen` reconocido (p. ej. AMBIGUA detectada antes de
    # resolver la rama) -- se muestra el texto/aclaración igual, nunca
    # una tabla de soporte inventada.
    return RespuestaConsultaAtlas(
        estado=datos.get("estado", "CONSULTA_INVALIDA"), texto_respuesta=datos.get("texto_respuesta", ""),
        opciones_aclaracion=tuple(datos.get("opciones_aclaracion") or ()),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("texto")
    parser.add_argument("--raiz-atlas", required=True)
    parser.add_argument("--viajes", required=True, help="Ruta a viajes.csv del reporte vigente.")
    args = parser.parse_args(argv)

    try:
        crudo = responder_consulta_incidencias_conversacional(
            args.texto, raiz=args.raiz_atlas, ruta_viajes=args.viajes,
        )
        respuesta = _a_respuesta_estandar(crudo)
    except Exception as error:
        print(json.dumps({
            "estado": "ERROR", "texto_respuesta": f"No se pudo consultar incidencias: {error}",
            "opciones_aclaracion": [], "resultado": None,
        }, ensure_ascii=True))
        return 1

    print(json.dumps(_respuesta_a_dict(respuesta), ensure_ascii=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
