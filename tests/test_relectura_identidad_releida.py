"""Reingesta de una captura MEJOR del mismo documento cuya lectura anterior
tenía la identidad mal leída (caso real que lo motivó: guía con número de
transporte leído 3->8/6->8 en una foto mala). La captura nueva corrige la
identidad sólo con evidencia OCR fuerte, completa campos ausentes, conserva
estructurados válidos que no volvió a leer, no duplica el documento y deja
trazabilidad. Datos sintéticos."""
from __future__ import annotations

import csv
import json

import pytest

from atlas_core.evidencia_documental import (
    leer_registro_relecturas, registrar_relectura, resolver_ruta_evidencia,
)
from atlas_core.gestor_viajes import agrupar_viajes
from atlas_core.procesamiento_masivo import COLUMNAS, procesar_carpeta
from atlas_core.trazabilidad_ocr import ruta_traza_ocr

ARCHIVO, GUIA = "500096.jpeg", "500096"
MALO, BUENO = "0000381570", "0000361570"
LOTE_ORIGINAL = "20261001_122605"

VIGENTE = {
    "numero_guia": GUIA, "numero_transporte": MALO, "fecha": "01-10-2025", "chofer": "No encontrado",
    "cliente": "No encontrado", "rut_cliente": "No encontrado", "obra_destino": "AMN HACO",
    "despachar_a_crudo": "PUT CHOFER E BANZA ISABZL", "patente_tracto": "AL1871", "peso_kg": "24471",
    "tipo_carga": "BARRAS", "indicador_revision": "REVISAR",
    "motivos_revision_documento": "PATENTE_SIN_HOMOLOGAR | OBRA_DESTINO_SIN_CORROBORAR | CHOFER_AUSENTE | "
                                  "CLIENTE_AUSENTE | MATERIAL_AUSENTE",
}
MEJOR = {
    "numero_guia": GUIA, "numero_transporte": BUENO, "fecha": "01-10-2026", "chofer": "RENE GARCIA",
    "rut_chofer": "9.708.225-1", "cliente": "ARMACERO MATCO SA", "rut_cliente": "78.170.790-2",
    "obra_destino": "ARMACERO MATCO SA", "despachar_a_crudo": "", "patente_tracto": "AL1879",
    "descripcion_material": "B HORMIGON 16MM", "peso_kg": "No encontrado", "tipo_carga": "BARRAS",
    "indicador_revision": "OK", "motivos_revision_documento": "",
}
PEOR = {**VIGENTE, "peso_kg": "No encontrado",
        "motivos_revision_documento": VIGENTE["motivos_revision_documento"] + " | DOCUMENTO_DEGRADADO"}
EXTRACCIONES = {b"mejor": (MEJOR, 0.9996), b"mejor-baja-confianza": (MEJOR, 0.91),
                b"otro-transporte": ({**MEJOR, "numero_transporte": "0000372570"}, 0.9996),
                b"peor": (PEOR, 0.95)}


def _escribir_traza(directorio, valor, confianza):
    ruta = ruta_traza_ocr(directorio, ARCHIVO)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps({"schema_version": 1, "imagen": {"referencia": ARCHIVO},
                                "ocr": {"lineas": [{"texto": valor, "confianza": confianza}], "bloques": []},
                                "identificadores_extraidos": {}}), encoding="utf-8")


def _hermana():
    fila = {c: "" for c in COLUMNAS}
    fila.update(archivo="ajena.jpeg", estado_procesamiento="OK", numero_guia="470000",
                numero_transporte="0000388888", tipo_carga="ROLLOS", cliente="OTRO CLIENTE")
    return fila


def _leer(ruta):
    with ruta.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f, delimiter=";"))


@pytest.fixture
def atlas(tmp_path):
    raiz = tmp_path / "Atlas"
    dataset = raiz / "operacion" / "actual" / "analisis_completo_guias.csv"
    dataset.parent.mkdir(parents=True)
    vigente = {c: "" for c in COLUMNAS}
    vigente.update(VIGENTE, archivo=ARCHIVO, estado_procesamiento="OK", fecha_ingesta_utc="2026-10-01T15:26:34+00:00")
    with dataset.open("w", encoding="utf-8-sig", newline="") as f:
        escritor = csv.DictWriter(f, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader()
        escritor.writerows([_hermana(), vigente])
    (raiz / "operacion" / "entradas" / LOTE_ORIGINAL).mkdir(parents=True)
    (raiz / "operacion" / "entradas" / LOTE_ORIGINAL / ARCHIVO).write_bytes(b"foto-mala")
    _escribir_traza(raiz / "operacion" / "trazas_ocr", MALO, 0.903)
    return raiz, dataset


def _arrastrar(raiz, lote, contenido):
    carpeta = raiz / "operacion" / "entradas" / lote
    carpeta.mkdir(parents=True, exist_ok=True)
    (carpeta / ARCHIVO).write_bytes(contenido)
    extraccion, confianza = EXTRACCIONES[contenido]

    def procesador(ruta):
        # La traza OCR de la relectura (escrita aparte hasta saber si se promueve).
        _escribir_traza(raiz / "operacion" / "trazas_ocr" / "_relecturas" / lote,
                        extraccion["numero_transporte"], confianza)
        return dict(extraccion)
    return procesar_carpeta(carpeta, raiz / "operacion" / "actual" / "analisis_completo_guias.csv",
                            procesador=procesador, orquestador_ia=object())


def _registro(raiz):
    return leer_registro_relecturas(raiz)["documentos"][ARCHIVO]


def test_captura_mejor_corrige_identidad_completa_campos_y_no_duplica(atlas):
    raiz, dataset = atlas
    antes = _leer(dataset)
    viajes_antes, _ = agrupar_viajes(antes)
    _arrastrar(raiz, "20261001_150314", b"mejor")
    filas = _leer(dataset)
    assert [f["archivo"] for f in filas] == ["ajena.jpeg", ARCHIVO]  # sin documento duplicado
    assert filas[0] == antes[0]
    fila = filas[1]
    assert fila["numero_transporte"] == BUENO  # identidad mal leída corregida por evidencia fuerte
    assert (fila["fecha"], fila["cliente"], fila["rut_cliente"], fila["chofer"]) == (
        "01-10-2026", "ARMACERO MATCO SA", "78.170.790-2", "RENE GARCIA")  # campos ausentes completados
    assert fila["peso_kg"] == "24471"  # estructurado válido no releído: se conserva, no se degrada
    assert fila["despachar_a_crudo"] == ""  # texto ilegible de la foto mala no se arrastra
    assert fila["motivos_revision_documento"] == "" and fila["indicador_revision"] == "OK"
    assert fila["fecha_ingesta_utc"] == "2026-10-01T15:26:34+00:00"
    viajes, _ = agrupar_viajes(filas)
    assert len(viajes) == len(viajes_antes)
    ultima = _registro(raiz)["historial"][-1]
    assert ultima["resultado"] == "PROMOVIDA" and ultima["reglas"] == 2
    assert ultima["conservados_de_evidencia_anterior"] == {"peso_kg": "24471"}
    assert ultima["confianza_transporte"] == {"anterior": 0.903, "nueva": 0.9996}
    assert ultima["cambios"]["numero_transporte"] == [MALO, BUENO]
    # ambas evidencias se conservan; la nueva queda vigente
    assert (raiz / "operacion/entradas" / LOTE_ORIGINAL / ARCHIVO).read_bytes() == b"foto-mala"
    assert resolver_ruta_evidencia(raiz, ARCHIVO).ruta.parent.name == "20261001_150314"
    trazas = sorted(p.name for p in (raiz / "operacion/trazas_ocr").glob("*.json"))
    assert len(trazas) == 2 and any("--anterior-" in n for n in trazas)


@pytest.mark.parametrize("contenido, motivo", [
    (b"otro-transporte", "IDENTIDAD_DISTINTA"),      # dígitos no confundibles: conflicto real
    (b"mejor-baja-confianza", "IDENTIDAD_DISTINTA"),  # confundible pero sin evidencia OCR fuerte
    (b"peor", "EVIDENCIA_PEOR"),                     # lectura peor no degrada lo bueno
])
def test_conflicto_o_evidencia_peor_mantiene_la_extraccion_y_su_revision(atlas, contenido, motivo):
    raiz, dataset = atlas
    antes = _leer(dataset)
    _arrastrar(raiz, "20261001_150314", contenido)
    assert _leer(dataset) == antes  # nada cambia: sigue en Revisión con su extracción
    ultima = _registro(raiz)["historial"][-1]
    assert ultima["resultado"] == "RECHAZADA" and ultima["motivo"].startswith(motivo)


def test_rechazo_con_reglas_anteriores_se_reevalua_al_reingresar(atlas):
    raiz, dataset = atlas
    # El mismo contenido ya fue rechazado con las reglas anteriores (sin "reglas").
    import hashlib
    registrar_relectura(raiz, archivo=ARCHIVO, lote="20261001_150314", sha256=hashlib.sha256(b"mejor").hexdigest(),
                        resultado="RECHAZADA", motivo="IDENTIDAD_DISTINTA",
                        anterior={"lote": LOTE_ORIGINAL, "sha256": hashlib.sha256(b"foto-mala").hexdigest()})
    _arrastrar(raiz, "20261001_155401", b"mejor")
    assert _leer(dataset)[1]["numero_transporte"] == BUENO
    assert _registro(raiz)["historial"][-1]["resultado"] == "PROMOVIDA"
    # Ya evaluado con las reglas vigentes: reingresarlo otra vez no reprocesa.
    total = len(_registro(raiz)["historial"])
    _arrastrar(raiz, "20261001_160000", b"mejor")
    assert len(_registro(raiz)["historial"]) == total
