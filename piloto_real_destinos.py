"""Piloto real controlado y reversible de verificación de destinos."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from atlas_core.inteligencia import (
    Evidencia,
    SolicitudVerificacionDestino,
    TipoFuente,
    VerificadorDestinosOpenRouteService,
    convertir_a_evidencia,
    resolver_destino_con_verificacion,
)
from atlas_core.inteligencia.motor import normalizar
from atlas_core.inteligencia.verificacion_destinos import (
    RespuestaHTTPDestino,
    _transporte_urllib,
)


SALIDA_PREDETERMINADA = (
    Path("validaciones") / "piloto_real_destinos_2026-07-28"
)
FECHA_GT = "2026-07-28"
CAMPOS_AUTORIZADOS = (
    "direccion_original",
    "comuna_esperada",
    "region_esperada",
    "pais",
)

CASOS = (
    {
        "id_caso": "REAL-001",
        "destino_id": "51b4cd04-0c4c-41f1-9fd2-3da535148c24",
        "direccion": "SANTA ISABEL 585",
        "comuna": "LAMPA",
        "region": "REGIÓN METROPOLITANA",
        "fuente": "CONFIRMACION_JAVIER_2026-07-27",
        "observaciones": "Bodega compartida con entregas habituales.",
    },
    {
        "id_caso": "REAL-002",
        "destino_id": "7ca60aef-ae2e-4149-b2e5-408ff5e6da95",
        "direccion": "LAS VIOLETAS 55 SECTOR LAS ESPERANZA",
        "comuna": "PADRE HURTADO",
        "region": "REGIÓN METROPOLITANA",
        "fuente": "PLUS_CODE_Y_CONFIRMACION_JAVIER_2026-07-27",
        "latitud_aprobada": -33.5563125,
        "longitud_aprobada": -70.8608125,
        "observaciones": "Único caso con coordenadas humanas aprobadas.",
    },
    {
        "id_caso": "REAL-003",
        "destino_id": "aefa98d8-62b5-4538-b8d2-4e16f6ac5b15",
        "direccion": "CALLE INTERIOR 700, FUNDO LA MONTAÑA",
        "comuna": "LAMPA",
        "region": "REGIÓN METROPOLITANA",
        "fuente": "CONFIRMACION_JAVIER_2026-07-27",
        "observaciones": "Dirección principal distinguida de Santa Isabel 585.",
    },
    {
        "id_caso": "REAL-004",
        "destino_id": "34b754bc-4d2f-4f3f-85e5-98d907106262",
        "direccion": "VISTA CLARA 2351",
        "comuna": "CERRILLOS",
        "region": "REGIÓN METROPOLITANA",
        "fuente": "EXCEL_38_REGISTROS_Y_CONFIRMACION_JAVIER_2026-07-28",
        "observaciones": "2401 es incorrecto; cualquier numeración distinta exige REVISAR.",
    },
    {
        "id_caso": "REAL-005",
        "destino_id": "32d67fec-2b5d-4daf-8205-b78719bc4ab7",
        "direccion": "GALVARINO 8501",
        "comuna": "QUILICURA",
        "region": "REGIÓN METROPOLITANA",
        "fuente": "EXCEL_HISTORICO_34_REGISTROS",
        "observaciones": "",
    },
    {
        "id_caso": "REAL-006",
        "destino_id": "7df58eec-eff3-4a6a-bdfa-34509ee8d2a2",
        "direccion": "CAMINO LO RUIZ 2901",
        "comuna": "RENCA",
        "region": "REGIÓN METROPOLITANA",
        "fuente": "EXCEL_HISTORICO_20_REGISTROS",
        "observaciones": "",
    },
    {
        "id_caso": "REAL-007",
        "destino_id": "73b2f2a2-12a4-4a56-b9a4-3932adf8025c",
        "direccion": "PANAMERICANA NORTE 22650",
        "comuna": "LAMPA",
        "region": "REGIÓN METROPOLITANA",
        "fuente": "EXCEL_HISTORICO_23_REGISTROS",
        "observaciones": "",
    },
    {
        "id_caso": "REAL-008",
        "destino_id": "b1332634-4904-4a1e-a0c2-f73e44beec6e",
        "direccion": "AV CORDILLERA 482",
        "comuna": "QUILICURA",
        "region": "REGIÓN METROPOLITANA",
        "fuente": "EXCEL_HISTORICO_4_REGISTROS",
        "observaciones": "",
    },
    {
        "id_caso": "REAL-009",
        "destino_id": "c64c55e3-2fd2-445f-ab0f-6546531034f3",
        "direccion": "CAMINO LOS PINOS 3394",
        "comuna": "SAN BERNARDO",
        "region": "REGIÓN METROPOLITANA",
        "fuente": "EXCEL_HISTORICO_2_REGISTROS",
        "observaciones": "3396 existe como destino separado y no sustituye 3394.",
    },
    {
        "id_caso": "REAL-010",
        "destino_id": "f2cef3d4-c1a5-48e8-8713-067222aaada6",
        "direccion": "RUTA 5 KM 40 S/N",
        "comuna": "PAINE",
        "region": "REGIÓN METROPOLITANA",
        "fuente": "EXCEL_HISTORICO_1_REGISTRO",
        "observaciones": "",
    },
    {
        "id_caso": "REAL-011",
        "destino_id": "aa4e2bcb-c580-4e90-85ca-bd475514caed",
        "direccion": "LA UNION 3070",
        "comuna": "RENCA",
        "region": "REGIÓN METROPOLITANA",
        "fuente": "EXCEL_HISTORICO_MOVIMIENTO_INTERNO_AZA",
        "observaciones": "",
    },
    {
        "id_caso": "REAL-012",
        "destino_id": "09011c4c-15c6-425a-a825-ede7313b9e78",
        "direccion": "LAUTARO 9202",
        "comuna": "QUILICURA",
        "region": "REGIÓN METROPOLITANA",
        "fuente": "EXCEL_HISTORICO_3_REGISTROS",
        "observaciones": "",
    },
)

RESULTADOS_BASE = {
    "REAL-001": ("CONTRADICCION_REGION", "ACIERTO_ABSTENCION"),
    "REAL-002": ("REVISAR", "ACIERTO_ABSTENCION"),
    "REAL-003": ("REVISAR", "ACIERTO_ABSTENCION"),
    "REAL-004": ("CONTRADICCION_REGION", "ACIERTO_ABSTENCION"),
    "REAL-005": ("REVISAR", "ACIERTO_ABSTENCION"),
    "REAL-006": ("CONTRADICCION_REGION", "ACIERTO_ABSTENCION"),
    "REAL-007": ("REVISAR", "ACIERTO_ABSTENCION"),
    "REAL-008": ("REVISAR", "ACIERTO_ABSTENCION"),
    "REAL-009": ("REVISAR", "ACIERTO_ABSTENCION"),
    "REAL-010": ("REVISAR", "ACIERTO_ABSTENCION"),
    "REAL-011": ("CONTRADICCION_REGION", "FALSO_NEGATIVO"),
    "REAL-012": ("REVISAR", "ACIERTO_ABSTENCION"),
}


def sha256(ruta: Path) -> str:
    return hashlib.sha256(ruta.read_bytes()).hexdigest()


def escribir_json(ruta: Path, valor: Any) -> None:
    ruta.write_text(
        json.dumps(valor, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def escribir_csv(ruta: Path, filas: list[dict[str, Any]]) -> None:
    with ruta.open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=list(filas[0]))
        escritor.writeheader()
        escritor.writerows(filas)


def preparar(salida: Path = SALIDA_PREDETERMINADA) -> dict[str, str]:
    salida.mkdir(parents=True, exist_ok=True)
    manifiesto = {
        "fecha": FECHA_GT,
        "rama": "piloto-real-controlado-destinos",
        "commit_base": "7beb9c6a8569d1af207300fff8dd84e81a2cd9c2",
        "cantidad_casos": len(CASOS),
        "orden_casos": [caso["id_caso"] for caso in CASOS],
        "destino_ids": [caso["destino_id"] for caso in CASOS],
        "campos_enviados": list(CAMPOS_AUTORIZADOS),
        "campos_excluidos": [
            "cliente", "rut", "chofer", "patente", "guia", "transporte", "imagen"
        ],
        "maximo_consultas_unicas": 12,
        "modifica_catalogos": False,
        "aceptacion_automatica_coordenadas": False,
    }
    gt = []
    for caso in CASOS:
        gt.append({
            "id_caso": caso["id_caso"],
            "identificador_interno": caso["destino_id"],
            "direccion_confirmada": caso["direccion"],
            "comuna_confirmada": caso["comuna"],
            "region_confirmada": caso["region"],
            "pais": "CHILE",
            "estado_confirmacion": "CONFIRMADO_DOCUMENTAL",
            "latitud_aprobada": caso.get("latitud_aprobada", ""),
            "longitud_aprobada": caso.get("longitud_aprobada", ""),
            "fuente_humana_documental": caso["fuente"],
            "resultado_esperado": "CONSERVAR_ORIGINAL_Y_EVALUAR_EVIDENCIA",
            "debe_confirmar": False,
            "debe_revisar": True,
            "observaciones": caso["observaciones"],
        })
    ruta_manifest = salida / "manifiesto_definitivo.json"
    ruta_gt = salida / "ground_truth_congelado.csv"
    escribir_json(ruta_manifest, manifiesto)
    escribir_csv(ruta_gt, gt)
    hashes = {
        "manifiesto_definitivo.json": sha256(ruta_manifest),
        "ground_truth_congelado.csv": sha256(ruta_gt),
    }
    escribir_json(salida / "hashes_preconsulta.json", hashes)
    return hashes


class CapturaTransporte:
    def __init__(self) -> None:
        self.respuestas: list[dict[str, Any]] = []

    def __call__(self, solicitud, timeout: float) -> RespuestaHTTPDestino:
        respuesta = _transporte_urllib(solicitud, timeout)
        try:
            cuerpo = json.loads(respuesta.cuerpo.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            cuerpo = {"respuesta_no_json_sha256": hashlib.sha256(respuesta.cuerpo).hexdigest()}
        self.respuestas.append({
            "orden": len(self.respuestas) + 1,
            "codigo_http": respuesta.estado,
            "cuerpo": cuerpo,
        })
        return respuesta


def _solicitud(caso: dict[str, Any]) -> SolicitudVerificacionDestino:
    return SolicitudVerificacionDestino(
        direccion_original=caso["direccion"],
        comuna_esperada=caso["comuna"],
        region_esperada=caso["region"],
        pais="CHILE",
        identificador_interno=caso["destino_id"],
        autorizacion_externa=True,
        campos_autorizados=frozenset(CAMPOS_AUTORIZADOS),
        contiene_datos_sensibles=False,
    )


def _internas(caso: dict[str, Any]) -> tuple[Evidencia, ...]:
    ahora = datetime(2026, 7, 28, tzinfo=timezone.utc)
    return (
        Evidencia(
            "destino", caso["direccion"], normalizar(caso["direccion"]),
            "ground_truth_humano", TipoFuente.CATALOGO, 1.0, ahora,
            referencia=f"GT-{caso['id_caso']}",
        ),
        Evidencia(
            "destino", caso["direccion"], normalizar(caso["direccion"]),
            "documento_historico", TipoFuente.REGLA_DETERMINISTA, 1.0, ahora,
            referencia=f"DOC-{caso['id_caso']}",
        ),
    )


def _fila_resultado(caso, resultado, propuesta, desde_cache):
    externa = convertir_a_evidencia(resultado)
    estado = resultado.estado.value
    tokens_direccion_gt = set(re.findall(r"[A-ZÁÉÍÓÚÑ0-9]+", normalizar(caso["direccion"])))
    tokens_direccion_devuelta = set(re.findall(
        r"[A-ZÁÉÍÓÚÑ0-9]+", normalizar(resultado.direccion_devuelta)
    ))
    direccion_exacta_humana = bool(tokens_direccion_gt) and (
        tokens_direccion_gt <= tokens_direccion_devuelta
    )
    comuna_compatible_humana = (
        not resultado.comuna_encontrada
        or normalizar(caso["comuna"]) == normalizar(resultado.comuna_encontrada)
    )
    region_compatible_humana = _region_compatible_humana(
        caso["region"], resultado.region_encontrada
    )
    if estado == "VERIFICADA":
        clasificacion = "ACIERTO_CONFIRMACION"
    elif estado == "CONTRADICCION_REGION" and region_compatible_humana:
        clasificacion = (
            "FALSO_NEGATIVO"
            if direccion_exacta_humana and comuna_compatible_humana
            else "ACIERTO_ABSTENCION"
        )
    elif estado in {"CONTRADICCION_COMUNA", "CONTRADICCION_REGION"}:
        clasificacion = "ACIERTO_CONTRADICCION"
    elif estado in {
        "COINCIDENCIA_PARCIAL", "REVISAR", "SIN_RESULTADOS",
        "DATOS_INSUFICIENTES",
    }:
        clasificacion = "ACIERTO_ABSTENCION"
    elif estado in {"ERROR_PROVEEDOR", "CUOTA_AGOTADA"}:
        clasificacion = "ERROR_PROVEEDOR"
    elif estado == "TIMEOUT":
        clasificacion = "ERROR_TECNICO"
    else:
        clasificacion = "ERROR_CLASIFICACION"
    if caso["id_caso"] == "REAL-004" and "2401" in normalizar(
        resultado.direccion_devuelta
    ):
        clasificacion = "FALSO_POSITIVO" if estado == "VERIFICADA" else "ACIERTO_CONTRADICCION"
    coordenadas = (
        "ACEPTADAS_EVIDENCIA_SUFFICIENTE"
        if estado == "VERIFICADA"
        else "RECHAZADAS_PENDIENTE_CONFIRMACION"
    )
    if resultado.latitud is None or resultado.longitud is None:
        coordenadas = "NO_PROPUESTAS"
    if "latitud_aprobada" in caso and resultado.latitud is not None:
        distancia_simple = abs(resultado.latitud - caso["latitud_aprobada"]) + abs(
            resultado.longitud - caso["longitud_aprobada"]
        )
        coordenadas = (
            "ACEPTADAS_EVIDENCIA_SUFFICIENTE"
            if estado == "VERIFICADA" and distancia_simple <= 0.001
            else "RECHAZADAS_INCOMPATIBLES_O_NO_VERIFICADAS"
        )
    return {
        "id_caso": caso["id_caso"],
        "destino_id": caso["destino_id"],
        "direccion_gt": caso["direccion"],
        "consulta_minimizada": resultado.consulta_minimizada,
        "estado_externo": estado,
        "tipo_coincidencia": resultado.tipo_coincidencia,
        "direccion_devuelta": resultado.direccion_devuelta,
        "comuna_devuelta": resultado.comuna_encontrada,
        "region_devuelta": resultado.region_encontrada,
        "latitud": resultado.latitud if resultado.latitud is not None else "",
        "longitud": resultado.longitud if resultado.longitud is not None else "",
        "coordenadas": coordenadas,
        "clasificacion": clasificacion,
        "valor_original_conservado": propuesta.valor_original == caso["direccion"],
        "valor_propuesto": propuesta.valor_propuesto,
        "estado_motor": propuesta.estado.value,
        "confianza_motor": propuesta.confianza.value,
        "requiere_revision": resultado.requiere_revision,
        "region_compatible_humana": region_compatible_humana,
        "calle_coincide": resultado.detalle_comparacion.get(
            "calle_coincide", False
        ),
        "numero_coincide": resultado.detalle_comparacion.get(
            "numero_coincide", False
        ),
        "comuna_coincide": resultado.detalle_comparacion.get(
            "comuna_coincide", False
        ),
        "region_coincide": resultado.detalle_comparacion.get(
            "region_coincide", False
        ),
        "explicacion_geografica": json.dumps(
            resultado.detalle_comparacion.get("explicacion", ()),
            ensure_ascii=False,
        ),
        "trazabilidad": externa is not None or bool(resultado.identificador_consulta),
        "identificador_consulta": resultado.identificador_consulta,
        "desde_cache": desde_cache,
        "duracion_ms": resultado.duracion_ms,
        "error": resultado.error,
    }


def _region_compatible_humana(esperada: str, encontrada: str) -> bool:
    if not encontrada:
        return False
    def reducir(valor):
        tokens = normalizar(valor).split()
        return " ".join(t for t in tokens if t not in {"REGION", "DE"})
    return reducir(esperada) == reducir(encontrada)


def _evaluar(proveedor, desde_cache: bool) -> list[dict[str, Any]]:
    filas = []
    for caso in CASOS:
        resultado = proveedor.verificar(_solicitud(caso))
        propuesta = resolver_destino_con_verificacion(
            caso["direccion"], _internas(caso), resultado
        )
        filas.append(_fila_resultado(caso, resultado, propuesta, desde_cache))
    return filas


def _metricas(filas, consultas_reales):
    total = len(filas)
    conteo = Counter(f["clasificacion"] for f in filas)
    confirmaciones = sum(f["estado_externo"] == "VERIFICADA" for f in filas)
    abstenciones = sum(bool(f["requiere_revision"]) for f in filas)
    coords_aceptadas = sum(
        f["coordenadas"] == "ACEPTADAS_EVIDENCIA_SUFFICIENTE" for f in filas
    )
    coords_rechazadas = sum(f["coordenadas"].startswith("RECHAZADAS") for f in filas)
    comuna = sum(
        normalizar(f["comuna_devuelta"]) == normalizar(CASOS[i]["comuna"])
        for i, f in enumerate(filas)
        if f["comuna_devuelta"]
    )
    comuna_den = sum(bool(f["comuna_devuelta"]) for f in filas)
    region = sum(bool(f["region_compatible_humana"]) for f in filas if f["region_devuelta"])
    region_den = sum(bool(f["region_devuelta"]) for f in filas)
    return {
        "casos": total,
        "precision_confirmaciones": [conteo["ACIERTO_CONFIRMACION"], confirmaciones],
        "cobertura_confirmaciones": [conteo["ACIERTO_CONFIRMACION"], total],
        "tasa_abstencion": [abstenciones, total],
        "falsos_positivos": [conteo["FALSO_POSITIVO"], total],
        "falsos_negativos": [conteo["FALSO_NEGATIVO"], total],
        "coincidencia_comuna": [comuna, comuna_den],
        "coincidencia_region": [region, region_den],
        "coordenadas_aceptadas": [coords_aceptadas, total],
        "coordenadas_rechazadas": [coords_rechazadas, total],
        "originales_conservados": [
            sum(bool(f["valor_original_conservado"]) for f in filas), total
        ],
        "trazabilidad_completa": [sum(bool(f["trazabilidad"]) for f in filas), total],
        "clasificaciones": dict(sorted(conteo.items())),
        "tiempo_medio_consulta_ms": round(
            sum(float(f["duracion_ms"]) for f in filas) / total, 3
        ),
        "consumo_cuota": [consultas_reales, 12],
    }


def _canon(filas):
    omitir = {"desde_cache", "duracion_ms"}
    return [{k: v for k, v in fila.items() if k not in omitir} for fila in filas]


def _escribir_antes_despues(salida, filas, metricas):
    antes_despues = [{
        "id_caso": f["id_caso"],
        "estado_antes": RESULTADOS_BASE[f["id_caso"]][0],
        "estado_despues": f["estado_externo"],
        "clasificacion_antes": RESULTADOS_BASE[f["id_caso"]][1],
        "clasificacion_despues": f["clasificacion"],
        "tipo_coincidencia_despues": f["tipo_coincidencia"],
        "calle_coincide": f["calle_coincide"],
        "numero_coincide": f["numero_coincide"],
        "comuna_coincide": f["comuna_coincide"],
        "region_coincide": f["region_coincide"],
        "coordenadas_despues": f["coordenadas"],
        "requiere_revision_despues": f["requiere_revision"],
    } for f in filas]
    escribir_csv(salida / "comparacion_antes_despues.csv", antes_despues)
    escribir_json(salida / "metricas_antes_despues.json", {
        "antes": {
            "confirmaciones": [0, 12], "abstenciones": [12, 12],
            "falsos_positivos": [0, 12], "falsos_negativos": [1, 12],
            "coordenadas_aceptadas": [0, 12],
        },
        "despues": {
            "confirmaciones": metricas["cobertura_confirmaciones"],
            "abstenciones": metricas["tasa_abstencion"],
            "falsos_positivos": metricas["falsos_positivos"],
            "falsos_negativos": metricas["falsos_negativos"],
            "coordenadas_aceptadas": metricas["coordenadas_aceptadas"],
        },
    })


def ejecutar(salida: Path = SALIDA_PREDETERMINADA) -> dict[str, Any]:
    hashes_previos = json.loads(
        (salida / "hashes_preconsulta.json").read_text(encoding="utf-8")
    )
    for nombre, esperado in hashes_previos.items():
        if sha256(salida / nombre) != esperado:
            raise RuntimeError(f"Artefacto preconsulta alterado: {nombre}")
    captura = CapturaTransporte()
    proveedor = VerificadorDestinosOpenRouteService(
        api_key=os.getenv("OPENROUTESERVICE_API_KEY", ""),
        timeout=12.0,
        limite_consultas=12,
        transporte=captura,
        usar_cache=True,
    )
    primera = _evaluar(proveedor, False)
    escribir_json(salida / "respuestas_ors_congeladas.json", captura.respuestas)
    escribir_csv(salida / "resultados_primera_ejecucion.csv", primera)
    consultas_antes_cache = proveedor.consultas_realizadas
    repeticion = _evaluar(proveedor, True)
    escribir_csv(salida / "resultados_desde_cache.csv", repeticion)
    metricas = _metricas(primera, consultas_antes_cache)
    metricas["determinismo"] = {
        "consultas_nuevas_en_repeticion": proveedor.consultas_realizadas
        - consultas_antes_cache,
        "resultados_semanticos_identicos": _canon(primera) == _canon(repeticion),
        "casos_desde_cache": sum(bool(f["desde_cache"]) for f in repeticion),
    }
    escribir_json(salida / "metricas.json", metricas)
    comparacion = [
        {
            "id_caso": f["id_caso"],
            "direccion_gt": f["direccion_gt"],
            "estado_externo": f["estado_externo"],
            "clasificacion": f["clasificacion"],
            "coordenadas": f["coordenadas"],
            "original_conservado": f["valor_original_conservado"],
            "requiere_revision": f["requiere_revision"],
        }
        for f in primera
    ]
    escribir_csv(salida / "comparacion.csv", comparacion)
    _escribir_antes_despues(salida, primera, metricas)
    recomendacion = recomendar(metricas)
    (salida / "recomendacion.txt").write_text(
        recomendacion + "\n", encoding="utf-8"
    )
    hashes = {
        p.name: sha256(p)
        for p in sorted(salida.iterdir())
        if p.is_file() and p.name != "hashes_finales.json"
    }
    escribir_json(salida / "hashes_finales.json", hashes)
    return {"metricas": metricas, "recomendacion": recomendacion, "hashes": hashes}


class TransporteCongelado:
    def __init__(self, respuestas: list[dict[str, Any]]) -> None:
        self._respuestas = list(respuestas)
        self._indice = 0

    def __call__(self, _solicitud, _timeout: float) -> RespuestaHTTPDestino:
        if self._indice >= len(self._respuestas):
            raise AssertionError("Se intentó exceder las respuestas congeladas")
        item = self._respuestas[self._indice]
        self._indice += 1
        return RespuestaHTTPDestino(
            int(item["codigo_http"]),
            json.dumps(item["cuerpo"], ensure_ascii=False).encode("utf-8"),
        )


def reproducir_desde_congelado(
    salida: Path = SALIDA_PREDETERMINADA,
) -> dict[str, Any]:
    respuestas = json.loads(
        (salida / "respuestas_ors_congeladas.json").read_text(encoding="utf-8")
    )
    proveedor = VerificadorDestinosOpenRouteService(
        api_key="CREDENCIAL_DE_REPRODUCCION_NO_REAL",
        timeout=12.0,
        limite_consultas=12,
        transporte=TransporteCongelado(respuestas),
        usar_cache=True,
    )
    primera = _evaluar(proveedor, False)
    escribir_csv(salida / "resultados_primera_ejecucion.csv", primera)
    antes = proveedor.consultas_realizadas
    repeticion = _evaluar(proveedor, True)
    escribir_csv(salida / "resultados_desde_cache.csv", repeticion)
    metricas = _metricas(primera, len(respuestas))
    auditoria_externa = json.loads(
        (salida / "ejecucion_externa.json").read_text(encoding="utf-8")
    )
    metricas["tiempo_medio_reproduccion_ms"] = metricas["tiempo_medio_consulta_ms"]
    metricas["tiempo_medio_consulta_ms"] = auditoria_externa[
        "tiempo_medio_consulta_real_ms"
    ]
    metricas["determinismo"] = {
        "consultas_nuevas_en_repeticion": proveedor.consultas_realizadas - antes,
        "resultados_semanticos_identicos": _canon(primera) == _canon(repeticion),
        "casos_desde_cache": sum(bool(f["desde_cache"]) for f in repeticion),
    }
    escribir_json(salida / "metricas.json", metricas)
    comparacion = [{
        "id_caso": f["id_caso"],
        "direccion_gt": f["direccion_gt"],
        "estado_externo": f["estado_externo"],
        "clasificacion": f["clasificacion"],
        "coordenadas": f["coordenadas"],
        "original_conservado": f["valor_original_conservado"],
        "requiere_revision": f["requiere_revision"],
    } for f in primera]
    escribir_csv(salida / "comparacion.csv", comparacion)
    _escribir_antes_despues(salida, primera, metricas)
    recomendacion = recomendar(metricas)
    (salida / "recomendacion.txt").write_text(recomendacion + "\n", encoding="utf-8")
    hashes = {
        p.name: sha256(p)
        for p in sorted(salida.iterdir())
        if p.is_file() and p.name != "hashes_finales.json"
    }
    escribir_json(salida / "hashes_finales.json", hashes)
    return {"metricas": metricas, "recomendacion": recomendacion, "hashes": hashes}


def recomendar(metricas):
    criticos = (
        metricas["falsos_positivos"][0] == 0
        and metricas["originales_conservados"][0] == metricas["casos"]
        and metricas["trazabilidad_completa"][0] == metricas["casos"]
        and metricas["determinismo"]["resultados_semanticos_identicos"]
        and metricas["determinismo"]["consultas_nuevas_en_repeticion"] == 0
    )
    return (
        "APTO PARA INTEGRACIÓN OPCIONAL EN MODO REVISIÓN"
        if criticos
        else "REQUIERE AJUSTES ANTES DE USAR DESTINOS REALES"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("fase", choices=("preparar", "ejecutar", "reproducir"))
    parser.add_argument("--salida", type=Path, default=SALIDA_PREDETERMINADA)
    args = parser.parse_args()
    if args.fase == "preparar":
        resultado = preparar(args.salida)
    elif args.fase == "ejecutar":
        resultado = ejecutar(args.salida)
    else:
        resultado = reproducir_desde_congelado(args.salida)
    print(json.dumps(resultado, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
