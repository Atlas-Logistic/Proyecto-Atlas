"""Caso real 482209 (Mobile, mié 14-10): recibida el 14-10 pero procesada el
16-10 por un OCR colgado; el filtro Hoy de Desktop la contaba en la jornada
del 16-10. La recepción real del documento se guarda aparte de
`fecha_ingesta_utc` (procesamiento), dentro de `metricas_procesamiento_json`.
"""
from __future__ import annotations

import csv
import json
import uuid

from atlas_core import procesamiento_masivo as pm
from atlas_core.mobile import RepositorioEnviosMobile, procesar_envio_mobile
from atlas_core.procesamiento_masivo import (
    COLUMNAS, anotar_fecha_recepcion, fecha_recepcion_de, procesar_carpeta,
)


def _leer(ruta):
    with ruta.open(encoding="utf-8-sig", newline="") as archivo:
        return list(csv.DictReader(archivo, delimiter=";"))


def _escribir(ruta, filas):
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with ruta.open("w", encoding="utf-8-sig", newline="") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader(); escritor.writerows(filas)


def test_anotar_conserva_metricas_no_pisa_y_normaliza_a_utc():
    datos = {"metricas_procesamiento_json": json.dumps({"ocr_seg": 1.5}), "fecha_ingesta_utc": "X"}
    anotar_fecha_recepcion(datos, "2026-10-14T14:41:31-03:00")
    assert json.loads(datos["metricas_procesamiento_json"]) == {
        "ocr_seg": 1.5, "fecha_recepcion_utc": "2026-10-14T17:41:31+00:00"}
    anotar_fecha_recepcion(datos, "2026-10-16T13:48:02Z")  # nunca pisa la primera
    assert fecha_recepcion_de(datos) == "2026-10-14T17:41:31+00:00"
    assert datos["fecha_ingesta_utc"] == "X"


def test_anotar_ignora_valores_ilegibles_o_sin_zona():
    for valor in (None, "", "ayer", "2026-10-14T17:41:31"):
        datos = {"metricas_procesamiento_json": "{}"}
        anotar_fecha_recepcion(datos, valor)
        assert fecha_recepcion_de(datos) == "", valor
    assert fecha_recepcion_de({"metricas_procesamiento_json": "no-json"}) == ""
    assert fecha_recepcion_de({}) == ""  # documentos antiguos: sin recepción


def test_desktop_usa_el_ingreso_del_lote_y_no_marca_reingestas(tmp_path):
    entrada, salida = tmp_path / "lote", tmp_path / "operacion" / "actual.csv"
    previa = {c: "" for c in COLUMNAS}
    previa.update(archivo="previa.jpg", numero_guia="482179", numero_transporte="0000363997", estado_procesamiento="OK")
    _escribir(salida, [previa])
    entrada.mkdir(parents=True)
    (entrada / "482247.jpeg").write_bytes(b"nueva")
    (entrada / "482179.jpeg").write_bytes(b"reenvio")
    identidades = {"482247.jpeg": ("482247", "0000364199"), "482179.jpeg": ("482179", "0000363997")}

    procesado = "2026-10-16T15:12:12+00:00"  # procesar_archivo estampa su propio instante
    resumen = procesar_carpeta(entrada, salida, procesador=lambda ruta: {
        "numero_guia": identidades[ruta.name][0], "numero_transporte": identidades[ruta.name][1],
        "fecha_ingesta_utc": procesado})

    manifiesto = json.loads((salida.parent / "manifiestos_ingesta" / "lote.json").read_text(encoding="utf-8"))
    ingreso = {s["nombre_archivo"]: s["ingresado_en_utc"] for s in manifiesto["seleccion"]}
    filas = {f["archivo"]: f for f in _leer(salida)}
    assert resumen["reingestas_omitidas"] == 1 and set(filas) == {"previa.jpg", "482247.jpeg"}
    assert fecha_recepcion_de(filas["482247.jpeg"]) == ingreso["482247.jpeg"]
    assert filas["482247.jpeg"]["fecha_ingesta_utc"] == procesado  # el procesamiento queda aparte
    assert fecha_recepcion_de(filas["previa.jpg"]) == ""  # la fila existente no se toca


def test_relectura_conserva_la_recepcion_original(tmp_path):
    salida = tmp_path / "actual.csv"
    vigente = {c: "" for c in COLUMNAS}
    vigente.update(archivo="482179.jpeg", numero_guia="482179", fecha_ingesta_utc="2026-10-14T21:22:09+00:00",
                   metricas_procesamiento_json=json.dumps({"fecha_recepcion_utc": "2026-10-14T21:21:42+00:00"}))
    _escribir(salida, [vigente])
    nueva = {**vigente, "fecha_ingesta_utc": "2026-10-16T15:12:00+00:00",
             "metricas_procesamiento_json": json.dumps({"ocr_seg": 3})}

    pm._promover_relectura(salida, archivo="482179.jpeg", fila_nueva=nueva)

    fila = _leer(salida)[0]
    assert fecha_recepcion_de(fila) == "2026-10-14T21:21:42+00:00"
    assert fila["fecha_ingesta_utc"] == "2026-10-14T21:22:09+00:00"


def test_mobile_procesado_tarde_conserva_la_recepcion_del_envio(tmp_path):
    raiz = tmp_path / "atlas"
    dataset = raiz / "operacion" / "actual" / "analisis_completo_guias.csv"
    previa = {c: "" for c in COLUMNAS}
    previa.update(archivo="previo.jpg", numero_guia="482000", numero_transporte="0000364082")
    _escribir(dataset, [previa])
    repo = RepositorioEnviosMobile(raiz)
    envio_id = str(uuid.uuid4())
    repo.recibir(envio_id=envio_id, imagen=b"foto", mime="image/jpeg",
                 metadata={"chofer_id": "10833150K", "usuario": "lazcano", "planta_origen_informada": "AZA_COLINA"})
    registro = repo.cargar(envio_id)
    registro["recibido_en"] = "2026-10-14T17:41:31.447445+00:00"  # recibido dos días antes de procesarse
    repo.guardar(envio_id, registro)

    procesar_envio_mobile(repo, envio_id, dataset=dataset,
                          procesador=lambda ruta: {"numero_guia": "482209", "numero_transporte": "0000364082",
                                                   "fecha_ingesta_utc": "2026-10-16T13:48:02+00:00"})

    fila = next(f for f in _leer(dataset) if f["numero_guia"] == "482209")
    assert fecha_recepcion_de(fila) == "2026-10-14T17:41:31.447445+00:00"
    assert fila["fecha_ingesta_utc"] == "2026-10-16T13:48:02+00:00"  # procesamiento, sin cambios
