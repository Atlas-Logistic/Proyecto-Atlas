"""Evaluación ciega, reproducible y exclusivamente sintética de destinos."""

from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from atlas_core.inteligencia import (
    Evidencia,
    SolicitudVerificacionDestino,
    TipoFuente,
    VerificadorDestinosOpenRouteService,
    convertir_a_evidencia,
    resolver_destino_con_verificacion,
)
from atlas_core.inteligencia.motor import normalizar
from atlas_core.inteligencia.verificacion_destinos import RespuestaHTTPDestino


FECHA = datetime(2026, 7, 28, 20, 0, tzinfo=timezone.utc)
CLASES = (
    ("VERIFICABLE_EXACTA", 12),
    ("VERIFICABLE_APROXIMADA", 12),
    ("CONTRADICCION_COMUNA", 11),
    ("CONTRADICCION_REGION", 9),
    ("AMBIGUA", 8),
    ("SIN_RESULTADOS", 6),
    ("DATOS_INSUFICIENTES", 6),
)
ESPECIALES = frozenset({2, 7, 14, 19, 28, 37, 46, 58})


def sha256(ruta: Path) -> str:
    return hashlib.sha256(ruta.read_bytes()).hexdigest()


def construir_casos() -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    muestra, gt = [], []
    numero = 0
    for clase, cantidad in CLASES:
        for indice in range(1, cantidad + 1):
            numero += 1
            especial = numero in ESPECIALES
            direccion = (
                f"Pasaje Ñandú Sintético Nº {numero:03d}, Torre Á"
                if especial
                else f"Calle Sintética {numero:03d}"
            )
            comuna = f"COMUNA SINTETICA {numero % 5 + 1}"
            region = f"REGION SINTETICA {numero % 3 + 1}"
            feature = _feature(direccion, comuna, region, numero)
            autorizado = True
            if clase == "VERIFICABLE_APROXIMADA":
                feature["properties"]["label"] = (
                    f"AVENIDA APROXIMADA {numero:03d}, {comuna}, {region}"
                )
            elif clase == "CONTRADICCION_COMUNA":
                feature["properties"]["locality"] = "COMUNA CONTRARIA"
            elif clase == "CONTRADICCION_REGION":
                feature["properties"]["region"] = "REGION CONTRARIA"
            respuesta = {"features": [feature]}
            resultado_esperado = {
                "VERIFICABLE_EXACTA": "VERIFICADA",
                "VERIFICABLE_APROXIMADA": "COINCIDENCIA_PARCIAL",
                "CONTRADICCION_COMUNA": "CONTRADICCION_COMUNA",
                "CONTRADICCION_REGION": "CONTRADICCION_REGION",
                "AMBIGUA": "REVISAR",
                "SIN_RESULTADOS": "SIN_RESULTADOS",
                "DATOS_INSUFICIENTES": "DATOS_INSUFICIENTES",
            }[clase]
            if clase == "AMBIGUA":
                respuesta = {"features": [feature, _feature(
                    f"Alternativa Sintética {numero}", comuna, region, numero + 100
                )]}
            elif clase == "SIN_RESULTADOS":
                respuesta = {"features": []}
            elif clase == "DATOS_INSUFICIENTES":
                autorizado = False
            id_caso = f"DEST-{numero:03d}"
            muestra.append(
                {
                    "id_caso": id_caso,
                    "direccion_entrada": direccion,
                    "comuna_esperada": comuna,
                    "region_esperada": region,
                    "pais": "PAIS SINTETICO",
                    "autorizado": autorizado,
                    "caso_especial": especial,
                    "respuesta_simulada": respuesta,
                }
            )
            requiere_revision = clase != "VERIFICABLE_EXACTA"
            gt.append(
                {
                    "id_caso": id_caso,
                    "direccion_entrada": direccion,
                    "comuna_esperada": comuna,
                    "region_esperada": region,
                    "clase_gt": clase,
                    "resultado_esperado": resultado_esperado,
                    "requiere_revision_esperado": requiere_revision,
                    "coordenadas_aceptables": clase == "VERIFICABLE_EXACTA",
                    "motivo_gt": _motivo_gt(clase),
                }
            )
    return muestra, gt


def _feature(direccion, comuna, region, semilla):
    return {
        "geometry": {
            "coordinates": [
                round(-20.0 - semilla / 1000, 6),
                round(-10.0 - semilla / 1000, 6),
            ]
        },
        "properties": {
            "label": f"{direccion}, {comuna}, {region}",
            "locality": comuna,
            "region": region,
            "country": "PAIS SINTETICO",
            "confidence": 0.92,
        },
    }


def _motivo_gt(clase):
    return {
        "VERIFICABLE_EXACTA": "Dirección, comuna y región coinciden.",
        "VERIFICABLE_APROXIMADA": "La geografía coincide, pero la dirección es aproximada.",
        "CONTRADICCION_COMUNA": "La comuna externa contradice la esperada.",
        "CONTRADICCION_REGION": "La región externa contradice la esperada.",
        "AMBIGUA": "Existen varios candidatos y se requiere abstención.",
        "SIN_RESULTADOS": "El proveedor no devuelve candidatos.",
        "DATOS_INSUFICIENTES": "La consulta no está autorizada.",
    }[clase]


def escribir_csv(ruta: Path, filas: list[dict[str, object]]) -> None:
    with ruta.open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=list(filas[0]))
        escritor.writeheader()
        escritor.writerows(filas)


def ejecutar_predicciones(
    muestra: list[dict[str, object]], ruta: Path
) -> list[dict[str, object]]:
    predicciones = []
    for caso in muestra:
        cuerpo = json.dumps(caso["respuesta_simulada"]).encode("utf-8")
        proveedor = VerificadorDestinosOpenRouteService(
            api_key="CREDENCIAL_SINTETICA_NO_REAL",
            transporte=lambda *_args, cuerpo=cuerpo: RespuestaHTTPDestino(200, cuerpo),
            reloj=lambda: FECHA,
            monotono=lambda: 100.0,
            usar_cache=False,
            limite_consultas=1,
        )
        solicitud = SolicitudVerificacionDestino(
            direccion_original=str(caso["direccion_entrada"]),
            comuna_esperada=str(caso["comuna_esperada"]),
            region_esperada=str(caso["region_esperada"]),
            pais=str(caso["pais"]),
            identificador_interno=str(caso["id_caso"]),
            autorizacion_externa=bool(caso["autorizado"]),
            campos_autorizados=frozenset(
                {"direccion_original", "comuna_esperada", "region_esperada", "pais"}
            ),
        )
        resultado = proveedor.verificar(solicitud)
        interna = (
            Evidencia(
                "destino",
                str(caso["direccion_entrada"]),
                normalizar(caso["direccion_entrada"]),
                "catalogo_sintetico",
                TipoFuente.CATALOGO,
                1.0,
                FECHA,
                referencia=f"CAT-{caso['id_caso']}",
            ),
            Evidencia(
                "destino",
                str(caso["direccion_entrada"]),
                normalizar(caso["direccion_entrada"]),
                "regla_sintetica",
                TipoFuente.REGLA_DETERMINISTA,
                1.0,
                FECHA,
                referencia=f"REGLA-{caso['id_caso']}",
            ),
        )
        propuesta = resolver_destino_con_verificacion(
            str(caso["direccion_entrada"]), interna, resultado
        )
        externa = convertir_a_evidencia(resultado)
        predicciones.append(
            {
                "id_caso": caso["id_caso"],
                "estado_predicho": resultado.estado.value,
                "valor_propuesto": propuesta.valor_propuesto,
                "comuna_predicha": resultado.comuna_encontrada,
                "region_predicha": resultado.region_encontrada,
                "acepta_coordenadas": resultado.estado.value == "VERIFICADA",
                "requiere_revision": propuesta.estado.value == "REVISAR",
                "confianza": propuesta.confianza.value,
                "contradicciones": json.dumps(
                    [c.motivo for c in propuesta.contradicciones],
                    ensure_ascii=False,
                ),
                "explicacion": json.dumps(
                    propuesta.explicacion, ensure_ascii=False
                ),
                "evidencias_utilizadas": json.dumps(
                    {
                        "internas": len(interna),
                        "externa": externa is not None,
                        "estado_externo": resultado.estado.value,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                "valor_original_conservado": propuesta.valor_original
                == caso["direccion_entrada"],
            }
        )
    escribir_csv(ruta, predicciones)
    return predicciones


def comparar(
    gt: list[dict[str, object]], predicciones: list[dict[str, object]]
) -> list[dict[str, object]]:
    por_id = {p["id_caso"]: p for p in predicciones}
    filas = []
    for esperado in gt:
        pred = por_id.get(esperado["id_caso"])
        clasificacion = clasificar(esperado, pred)
        filas.append(
            {
                "id_caso": esperado["id_caso"],
                "clase_gt": esperado["clase_gt"],
                "resultado_esperado": esperado["resultado_esperado"],
                "estado_predicho": pred["estado_predicho"] if pred else "",
                "clasificacion": clasificacion,
                "gravedad": "ALTA" if clasificacion == "FALSO_POSITIVO" else (
                    "MEDIA" if clasificacion in {
                        "FALSO_NEGATIVO", "ERROR_CLASIFICACION", "ERROR_TECNICO"
                    } else "NINGUNA"
                ),
                "valor_original_conservado": bool(
                    pred and pred["valor_original_conservado"]
                ),
                "trazabilidad_completa": bool(
                    pred
                    and pred["explicacion"]
                    and pred["evidencias_utilizadas"]
                ),
            }
        )
    return filas


def clasificar(gt, pred):
    if pred is None:
        return "ERROR_TECNICO"
    confirma = (
        pred["estado_predicho"] == "VERIFICADA"
        and pred["acepta_coordenadas"]
        and not pred["requiere_revision"]
    )
    if gt["requiere_revision_esperado"] and confirma:
        return "FALSO_POSITIVO"
    if not gt["requiere_revision_esperado"] and not confirma:
        return "FALSO_NEGATIVO"
    if gt["clase_gt"] == "VERIFICABLE_EXACTA" and confirma:
        return "ACIERTO_CONFIRMACION"
    if gt["clase_gt"] in {"CONTRADICCION_COMUNA", "CONTRADICCION_REGION"}:
        return (
            "ACIERTO_CONTRADICCION"
            if pred["estado_predicho"] == gt["resultado_esperado"]
            else "ERROR_CLASIFICACION"
        )
    if gt["requiere_revision_esperado"]:
        return (
            "ACIERTO_ABSTENCION"
            if pred["estado_predicho"] == gt["resultado_esperado"]
            else "ERROR_CLASIFICACION"
        )
    return "ERROR_CLASIFICACION"


def calcular_metricas(comparacion, predicciones):
    total = len(comparacion)
    conteo = Counter(f["clasificacion"] for f in comparacion)
    confirmaciones = sum(
        p["estado_predicho"] == "VERIFICADA" for p in predicciones
    )
    exactos = sum(f["clase_gt"] == "VERIFICABLE_EXACTA" for f in comparacion)
    abstenciones = sum(p["requiere_revision"] for p in predicciones)
    return {
        "casos": total,
        "aciertos": sum(
            cantidad
            for clase, cantidad in conteo.items()
            if clase.startswith("ACIERTO_")
        ),
        "exactitud_global": [sum(
            v for k, v in conteo.items() if k.startswith("ACIERTO_")
        ), total],
        "precision_confirmaciones": [
            conteo["ACIERTO_CONFIRMACION"], confirmaciones
        ],
        "cobertura_confirmaciones": [
            conteo["ACIERTO_CONFIRMACION"], exactos
        ],
        "tasa_abstencion": [abstenciones, total],
        "falsos_positivos": [conteo["FALSO_POSITIVO"], total],
        "falsos_negativos": [conteo["FALSO_NEGATIVO"], exactos],
        "contradiccion_comuna": [
            sum(
                f["clasificacion"] == "ACIERTO_CONTRADICCION"
                and f["clase_gt"] == "CONTRADICCION_COMUNA"
                for f in comparacion
            ),
            sum(f["clase_gt"] == "CONTRADICCION_COMUNA" for f in comparacion),
        ],
        "contradiccion_region": [
            sum(
                f["clasificacion"] == "ACIERTO_CONTRADICCION"
                and f["clase_gt"] == "CONTRADICCION_REGION"
                for f in comparacion
            ),
            sum(f["clase_gt"] == "CONTRADICCION_REGION" for f in comparacion),
        ],
        "ambiguedad": [
            sum(
                f["clasificacion"] == "ACIERTO_ABSTENCION"
                and f["clase_gt"] == "AMBIGUA"
                for f in comparacion
            ),
            sum(f["clase_gt"] == "AMBIGUA" for f in comparacion),
        ],
        "originales_conservados": [
            sum(f["valor_original_conservado"] for f in comparacion), total
        ],
        "trazabilidad_completa": [
            sum(f["trazabilidad_completa"] for f in comparacion), total
        ],
    }


def diagnosticar(comparacion, gt, predicciones):
    gt_id = {x["id_caso"]: x for x in gt}
    pred_id = {x["id_caso"]: x for x in predicciones}
    errores = []
    for fila in comparacion:
        if fila["clasificacion"].startswith("ACIERTO_"):
            continue
        esperado, pred = gt_id[fila["id_caso"]], pred_id.get(fila["id_caso"], {})
        errores.append(
            {
                "id_caso": fila["id_caso"],
                "clasificacion": fila["clasificacion"],
                "evidencia_disponible": pred.get("evidencias_utilizadas", ""),
                "decision_tomada": pred.get("estado_predicho", ""),
                "decision_esperada": esperado["resultado_esperado"],
                "causa_probable": "Clasificación conservadora o respuesta inesperada.",
                "gravedad": fila["gravedad"],
                "politica_involucrada": "destino",
                "propuesta_correccion": "Revisar en un bloque posterior; no ajustar esta corrida.",
            }
        )
    return errores


def ejecutar(carpeta: str | Path) -> dict[str, object]:
    salida = Path(carpeta)
    salida.mkdir(parents=True, exist_ok=False)
    muestra, gt = construir_casos()
    (salida / "manifest_muestra.json").write_text(
        json.dumps(
            {
                "version": "1",
                "sintetica": True,
                "cantidad": len(muestra),
                "distribucion": dict(Counter(x["clase_gt"] for x in gt)),
                "casos_especiales": sum(x["caso_especial"] for x in muestra),
                "red_permitida": False,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ) + "\n",
        encoding="utf-8",
    )
    (salida / "muestra_proveedor_simulado.json").write_text(
        json.dumps(muestra, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    ruta_gt = salida / "ground_truth_congelado.csv"
    escribir_csv(ruta_gt, gt)
    hash_gt = sha256(ruta_gt)
    (salida / "hash_ground_truth.txt").write_text(hash_gt + "\n", encoding="ascii")

    ruta_pred = salida / "predicciones_congeladas.csv"
    predicciones = ejecutar_predicciones(muestra, ruta_pred)
    hash_pred = sha256(ruta_pred)
    (salida / "hash_predicciones.txt").write_text(hash_pred + "\n", encoding="ascii")
    ruta_repeticion = salida / "predicciones_repeticion.csv"
    predicciones_2 = ejecutar_predicciones(muestra, ruta_repeticion)
    hash_repeticion = sha256(ruta_repeticion)

    comparacion = comparar(gt, predicciones)
    escribir_csv(salida / "comparacion.csv", comparacion)
    metricas = calcular_metricas(comparacion, predicciones)
    metricas["determinismo"] = {
        "archivos_identicos": ruta_pred.read_bytes() == ruta_repeticion.read_bytes(),
        "hash_primera": hash_pred,
        "hash_segunda": hash_repeticion,
        "metricas_identicas": metricas == calcular_metricas(
            comparar(gt, predicciones_2), predicciones_2
        ),
    }
    (salida / "metricas.json").write_text(
        json.dumps(metricas, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    diagnostico = diagnosticar(comparacion, gt, predicciones)
    escribir_csv(
        salida / "diagnostico.csv",
        diagnostico or [{
            "id_caso": "", "clasificacion": "SIN_ERRORES",
            "evidencia_disponible": "", "decision_tomada": "",
            "decision_esperada": "", "causa_probable": "",
            "gravedad": "NINGUNA", "politica_involucrada": "destino",
            "propuesta_correccion": "Ninguna",
        }],
    )
    recomendacion = recomendar(metricas)
    (salida / "README.md").write_text(
        _readme(hash_gt, hash_pred, metricas, recomendacion),
        encoding="utf-8",
    )
    (salida / "hashes.json").write_text(
        json.dumps(
            {
                ruta.name: sha256(ruta)
                for ruta in sorted(salida.iterdir())
                if ruta.is_file() and ruta.name != "hashes.json"
            },
            indent=2,
            sort_keys=True,
        ) + "\n",
        encoding="utf-8",
    )
    return {
        "hash_gt": hash_gt,
        "hash_pred": hash_pred,
        "hash_repeticion": hash_repeticion,
        "metricas": metricas,
        "recomendacion": recomendacion,
    }


def recomendar(metricas):
    cumple = (
        metricas["falsos_positivos"][0] == 0
        and metricas["contradiccion_region"][0] == metricas["contradiccion_region"][1]
        and metricas["ambiguedad"][0] == metricas["ambiguedad"][1]
        and metricas["originales_conservados"][0] == metricas["originales_conservados"][1]
        and metricas["trazabilidad_completa"][0] == metricas["trazabilidad_completa"][1]
        and metricas["determinismo"]["archivos_identicos"]
    )
    return (
        "APTO PARA PILOTO REAL CONTROLADO"
        if cumple
        else "REQUIERE AJUSTES ANTES DEL PILOTO"
    )


def _readme(hash_gt, hash_pred, metricas, recomendacion):
    return f"""# Validación ciega sintética de destinos

Reproducir desde una carpeta inexistente:

`python validacion_ciega_destinos.py RUTA_SALIDA`

- Ground Truth congelado antes de predicciones: `{hash_gt}`
- Predicciones congeladas: `{hash_pred}`
- Casos: {metricas['casos']}
- Recomendación: **{recomendacion}**

La evaluación usa sólo respuestas simuladas deterministas. No usa internet,
credenciales, catálogos, direcciones, coordenadas ni datos operacionales reales.
Las políticas productivas no se modifican.
"""


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("salida", type=Path)
    argumentos = parser.parse_args()
    print(json.dumps(ejecutar(argumentos.salida), ensure_ascii=False, indent=2))
