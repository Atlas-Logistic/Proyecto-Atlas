"""Relectura con evidencia mejor: una foto nueva con el mismo `archivo` de
una guía ya ingresada se reextrae y, si identifica el mismo documento sin
perder información, reemplaza la extracción vigente en su lugar. Datos
sintéticos (caso real que lo motivó: 474699, foto degradada + foto mejor
arrastradas a Desktop en dos lotes distintos)."""
from __future__ import annotations

import csv
import json

import pytest

from atlas_core import procesamiento_masivo
from atlas_core.evidencia_documental import leer_registro_relecturas, resolver_ruta_evidencia
from atlas_core.gestor_viajes import agrupar_viajes
from atlas_core.procesamiento_masivo import (
    COLUMNAS, descartar_decisiones_de_relecturas_promovidas, procesar_carpeta,
)

ARCHIVO = "474001.jpeg"
GUIA, TRANSPORTE = "474001", "0000399001"

EXTRACCIONES = {
    b"foto-degradada": {
        "numero_guia": GUIA, "numero_transporte": TRANSPORTE, "fecha": "16-09-2028",
        "chofer": "LUIS VARAS", "cliente": "BALOMON BACH EA", "obra_destino": "SALCMIHE KACH",
        "despachar_a_crudo": "CAMINO LS PINDS NNA", "tipo_carga": "BARRAS", "peso_kg": "26733",
        "motivos_revision_documento": "CLIENTE_SIN_CORROBORAR | OBRA_DESTINO_SIN_CORROBORAR",
    },
    b"foto-mejor": {
        "numero_guia": GUIA, "numero_transporte": TRANSPORTE, "fecha": "26-09-2026",
        "chofer": "LUIS VARAS", "cliente": "SALOMON SACK SA", "obra_destino": "SALOMON SACK SA SAN BERNARDO",
        "despachar_a_crudo": "CAMINO LOS PINOS 3396 SANTIAGO SAN BERNARDO", "tipo_carga": "BARRAS",
        "peso_kg": "26733", "motivos_revision_documento": "",
    },
    b"foto-peor": {
        "numero_guia": GUIA, "numero_transporte": TRANSPORTE, "fecha": "No encontrado",
        "chofer": "LUIS VARAS", "cliente": "SALOMON SACK SA", "obra_destino": "SALOMON SACK SA",
        "despachar_a_crudo": "CAMINO LOS PINOS", "tipo_carga": "BARRAS", "peso_kg": "26733",
    },
    b"foto-degradada-global": {
        "numero_guia": GUIA, "numero_transporte": TRANSPORTE, "fecha": "26-09-2026",
        "chofer": "LUIS VARAS", "cliente": "SALOMON SACK SA", "obra_destino": "SALOMON SACK SA",
        "despachar_a_crudo": "CAMINO LOS PINOS", "tipo_carga": "BARRAS", "peso_kg": "26733",
        "motivos_revision_documento": "DOCUMENTO_DEGRADADO",
    },
    b"foto-sin-guia": {
        "numero_guia": "No encontrado", "numero_transporte": TRANSPORTE, "fecha": "26-09-2026",
        "chofer": "LUIS VARAS", "cliente": "SALOMON SACK SA", "tipo_carga": "BARRAS",
    },
    b"foto-otra-guia": {
        "numero_guia": "474002", "numero_transporte": TRANSPORTE, "fecha": "26-09-2026",
        "chofer": "LUIS VARAS", "cliente": "SALOMON SACK SA", "tipo_carga": "BARRAS",
    },
}


def _procesador(ruta):
    contenido = ruta.read_bytes()
    if contenido == b"foto-que-rompe":
        raise RuntimeError("OCR caído")
    return dict(EXTRACCIONES[contenido])


def _fila_vigente():
    fila = {c: "" for c in COLUMNAS}
    fila.update(EXTRACCIONES[b"foto-degradada"])
    fila.update(archivo=ARCHIVO, estado_procesamiento="OK", fecha_ingesta_utc="2026-09-28T12:03:33+00:00")
    return fila


def _hermana():
    fila = {c: "" for c in COLUMNAS}
    fila.update(
        archivo="ajena.jpeg", estado_procesamiento="OK", numero_guia="470000",
        numero_transporte="0000388888", tipo_carga="ROLLOS", cliente="OTRO CLIENTE",
    )
    return fila


def _leer(ruta):
    with ruta.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f, delimiter=";"))


@pytest.fixture
def atlas(tmp_path):
    raiz = tmp_path / "Atlas"
    dataset = raiz / "operacion" / "actual" / "analisis_completo_guias.csv"
    dataset.parent.mkdir(parents=True)
    with dataset.open("w", encoding="utf-8-sig", newline="") as f:
        escritor = csv.DictWriter(f, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader()
        escritor.writerows([_hermana(), _fila_vigente()])
    lote_original = raiz / "operacion" / "entradas" / "20260928_090333"
    lote_original.mkdir(parents=True)
    (lote_original / ARCHIVO).write_bytes(b"foto-degradada")
    return raiz, dataset


def _arrastrar(raiz, dataset, lote, contenido, **kwargs):
    carpeta = raiz / "operacion" / "entradas" / lote
    carpeta.mkdir(parents=True, exist_ok=True)
    (carpeta / ARCHIVO).write_bytes(contenido)
    return procesar_carpeta(carpeta, dataset, procesador=_procesador, orquestador_ia=object(), **kwargs)


def test_foto_mejor_reextrae_y_reemplaza_la_extraccion_en_su_lugar(atlas):
    raiz, dataset = atlas
    antes = _leer(dataset)
    viajes_antes, _ = agrupar_viajes(antes)

    resumen = _arrastrar(raiz, dataset, "20260928_120938", b"foto-mejor")

    filas = _leer(dataset)
    assert [f["archivo"] for f in filas] == ["ajena.jpeg", ARCHIVO]  # misma posición, sin fila nueva
    assert filas[0] == antes[0]  # otra guía intacta
    fila = filas[1]
    assert fila["fecha"] == "26-09-2026"
    assert fila["cliente"] == "SALOMON SACK SA"
    assert fila["obra_destino"] == "SALOMON SACK SA SAN BERNARDO"
    assert fila["despachar_a_crudo"] == "CAMINO LOS PINOS 3396 SANTIAGO SAN BERNARDO"
    assert fila["motivos_revision_documento"] == ""
    assert fila["fecha_ingesta_utc"] == "2026-09-28T12:03:33+00:00"
    viajes_despues, _ = agrupar_viajes(filas)
    assert len(viajes_despues) == len(viajes_antes)  # ningún viaje duplicado

    assert resumen["procesados"] == 1 and resumen["omitidos"] == 0
    assert resumen["archivos_procesados_ahora"] == [ARCHIVO]  # entra a la reconciliación focal
    [relectura] = resumen["relecturas"]
    assert relectura["resultado"] == "PROMOVIDA" and relectura["motivo"] == ""
    assert relectura["cambios"]["fecha"] == ["16-09-2028", "26-09-2026"]
    assert "chofer" not in relectura["cambios"]

    # Trazabilidad: ambas evidencias siguen en disco; la vigente es la nueva.
    documento = leer_registro_relecturas(raiz)["documentos"][ARCHIVO]
    assert documento["vigente"]["lote"] == "20260928_120938"
    assert documento["historial"][0]["anterior"]["lote"] == "20260928_090333"
    assert (raiz / "operacion" / "entradas" / "20260928_090333" / ARCHIVO).read_bytes() == b"foto-degradada"
    assert resolver_ruta_evidencia(raiz, ARCHIVO).ruta.read_bytes() == b"foto-mejor"


def test_relectura_es_idempotente(atlas):
    raiz, dataset = atlas
    _arrastrar(raiz, dataset, "20260928_120938", b"foto-mejor")
    tras_primera = dataset.read_bytes()
    registro = json.loads((raiz / "operacion" / "relecturas_documentales.json").read_text(encoding="utf-8"))

    # Mismo lote reprocesado y la misma foto arrastrada otra vez.
    carpeta = raiz / "operacion" / "entradas" / "20260928_120938"
    repetido = procesar_carpeta(carpeta, dataset, procesador=_procesador, orquestador_ia=object())
    otra_vez = _arrastrar(raiz, dataset, "20260928_130000", b"foto-mejor")

    for resumen in (repetido, otra_vez):
        assert resumen["relecturas"] == [] and resumen["omitidos"] == 1 and resumen["procesados"] == 0
    assert dataset.read_bytes() == tras_primera
    assert json.loads((raiz / "operacion" / "relecturas_documentales.json").read_text(encoding="utf-8")) == registro


def test_misma_foto_original_en_otro_lote_se_omite_como_siempre(atlas):
    raiz, dataset = atlas
    antes = dataset.read_bytes()
    resumen = _arrastrar(raiz, dataset, "20260928_120938", b"foto-degradada")
    assert resumen["relecturas"] == [] and resumen["omitidos"] == 1
    assert dataset.read_bytes() == antes
    assert not (raiz / "operacion" / "relecturas_documentales.json").exists()


@pytest.mark.parametrize("contenido, motivo", [
    (b"foto-peor", "EVIDENCIA_PEOR:CAMPOS_PERDIDOS=fecha"),
    (b"foto-degradada-global", "EVIDENCIA_PEOR:DOCUMENTO_DEGRADADO"),
    (b"foto-sin-guia", "NO_IDENTIFICABLE"),
    (b"foto-otra-guia", "IDENTIDAD_DISTINTA"),
    (b"foto-que-rompe", "EXTRACCION_FALLIDA:RuntimeError"),
])
def test_evidencia_peor_o_no_identificable_no_reemplaza_y_queda_registrada(atlas, contenido, motivo):
    raiz, dataset = atlas
    antes = dataset.read_bytes()

    resumen = _arrastrar(raiz, dataset, "20260928_120938", contenido)

    assert dataset.read_bytes() == antes  # sin reemplazo ni fila de error
    assert resumen["archivos_procesados_ahora"] == [] and resumen["decisiones_pendientes"] == []
    [relectura] = resumen["relecturas"]
    assert relectura["resultado"] == "RECHAZADA" and relectura["motivo"] == motivo
    documento = leer_registro_relecturas(raiz)["documentos"][ARCHIVO]
    assert documento["vigente"] is None and documento["historial"][0]["motivo"] == motivo
    # La evidencia vigente sigue siendo la original; la rechazada queda guardada.
    assert resolver_ruta_evidencia(raiz, ARCHIVO).ruta.read_bytes() == b"foto-degradada"
    assert (raiz / "operacion" / "entradas" / "20260928_120938" / ARCHIVO).read_bytes() == contenido
    # Volver a arrastrar la misma foto rechazada no la reevalúa.
    assert _arrastrar(raiz, dataset, "20260928_130000", contenido)["relecturas"] == []


def test_campo_con_decision_humana_conserva_su_valor(atlas):
    raiz, dataset = atlas
    (dataset.parent / "decisiones_aplicadas.json").write_text(json.dumps({"aplicaciones": [{
        "documento": {"archivo": ARCHIVO, "numero_guia": GUIA}, "campo": "obra_destino",
    }]}), encoding="utf-8")

    _arrastrar(raiz, dataset, "20260928_120938", b"foto-mejor")

    fila = _leer(dataset)[1]
    assert fila["obra_destino"] == "SALCMIHE KACH"  # el ledger gana
    assert fila["fecha"] == "26-09-2026"


def test_fuera_de_la_operacion_real_se_conserva_la_omision(tmp_path):
    dataset = tmp_path / "resultado.csv"
    with dataset.open("w", encoding="utf-8-sig", newline="") as f:
        escritor = csv.DictWriter(f, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader()
        escritor.writerow(_fila_vigente())
    lote = tmp_path / "lote"
    lote.mkdir()
    (lote / ARCHIVO).write_bytes(b"foto-mejor")
    antes = dataset.read_bytes()

    resumen = procesar_carpeta(lote, dataset, procesador=_procesador, orquestador_ia=object())

    assert resumen["omitidos"] == 1 and resumen["relecturas"] == []
    assert dataset.read_bytes() == antes


def test_decisiones_de_la_extraccion_reemplazada_se_reconcilian(atlas, monkeypatch):
    raiz, dataset = atlas

    def procesar_falso(ruta, **kwargs):
        kwargs["recolector_decisiones"]([{
            "decision_id": "nueva", "documento": {"archivo": ARCHIVO}, "valor_documental": "SALOMON SACK SA",
        }])
        return dict(EXTRACCIONES[ruta.read_bytes()])

    monkeypatch.setattr(procesamiento_masivo, "procesar_archivo", procesar_falso)
    carpeta = raiz / "operacion" / "entradas" / "20260928_120938"
    carpeta.mkdir(parents=True)
    (carpeta / ARCHIVO).write_bytes(b"foto-mejor")
    resumen = procesar_carpeta(
        carpeta, dataset, lector_ocr=object(), carpeta_catalogos=raiz / "catalogos_privados",
        proveedor_rutas=object(), orquestador_ia=object(),
    )

    assert [d["decision_id"] for d in resumen["decisiones_pendientes"]] == ["nueva"]
    previas = [
        {"decision_id": "vieja", "documento": {"archivo": ARCHIVO}, "valor_documental": "CAMINO LS PINDS NNA"},
        {"decision_id": "ajena", "documento": {"archivo": "ajena.jpeg"}},
    ]
    vigentes = descartar_decisiones_de_relecturas_promovidas(previas, resumen["relecturas"])
    assert [d["decision_id"] for d in vigentes] == ["ajena"]
    # Una relectura rechazada no retira nada.
    rechazada = [{**resumen["relecturas"][0], "resultado": "RECHAZADA"}]
    assert descartar_decisiones_de_relecturas_promovidas(previas, rechazada) == previas
