"""Regresiones: CLIENTE_AUSENTE con el cliente legible en una cabecera
SEÑOR(ES) truncada por el borde de la foto (caso real 475042)."""

from __future__ import annotations

import json
from unittest.mock import Mock

import pytest

import atlas_core.procesamiento_masivo as procesamiento
from atlas_core.catalogo_clientes import CatalogoClientes, EstadoCalidadCliente
from atlas_core.codigo_cliente_destinatario import CatalogoCodigosCliente
from atlas_core.extractor import (
    _es_fragmento_etiqueta_codigo_cliente,
    _es_fragmento_etiqueta_senor,
    _extraer_identidad_cliente_cabecera_truncada,
)
from atlas_core.ocr import BloqueOCR
from atlas_core.procesamiento_masivo import (
    _completar_cliente_ausente_por_cabecera_documental,
    procesar_archivo,
)

RUT_EASY = "76.568.660-1"
RUT_OTRO = "50.234.350-5"


def _bloque(texto, x1, y1, x2, y2, confianza=0.9):
    return BloqueOCR(texto=texto, bounding_box=((x1, y1), (x2, y1), (x2, y2), (x1, y2)), confianza=confianza)


def _bloques_475042(*, rut=("76.568", "660-1"), extra_rut=()):
    """Geometría real de la lectura EasyOCR de 475042 (zona cabecera)."""
    bloques = [
        _bloque("dlgo Cliente", 0, 1009, 179, 1052),
        _bloque("0001001422", 238, 1016, 414, 1048),
        _bloque("CHA DE EMISIÓN", 0, 1072, 237, 1112),
        _bloque("30-09-2026", 435, 1082, 611, 1114),
        _bloque("ORDEN DE COMPRA", 1025, 1072, 1315, 1112),
        _bloque("6701619671", 1426, 1076, 1595, 1108),
        _bloque("VOR(ES)", 0, 1108, 123, 1157),
        _bloque("EASY REIAIL", 435, 1123, 627, 1155),
        _bloque("SA", 638, 1123, 677, 1155),
        _bloque("SOLICITANTE", 1025, 1112, 1221, 1149),
        _bloque("EBCO $.A", 1426, 1116, 1577, 1148),
        _bloque("TELEFONO", 1024, 1149, 1188, 1191),
        _bloque("992041493", 1426, 1154, 1580, 1186),
        _bloque("{0", 0, 1194, 36, 1227),
        _bloque("VIA", 435, 1201, 495, 1233),
        _bloque("X MENOR ARI", 554, 1201, 745, 1233),
        _bloque("OBRA DESTINO", 1025, 1190, 1249, 1228),
        _bloque("IECCION", 0, 1229, 125, 1273),
        _bloque("AV KENNEDY 9001", 438, 1238, 695, 1270),
    ]
    if rut:
        x = 435
        for fragmento in rut:
            ancho = 18 * len(fragmento)
            bloques.append(_bloque(fragmento, x, 1160, x + ancho, 1192))
            x += ancho + 12
    for fragmento, x1 in extra_rut:
        bloques.append(_bloque(fragmento, x1, 1160, x1 + 18 * len(fragmento), 1192))
    return bloques


def _catalogo(tmp_path, *clientes):
    carpeta = tmp_path / "catalogos"
    carpeta.mkdir(exist_ok=True)
    catalogo = CatalogoClientes(carpeta / "clientes.json")
    creados = [
        catalogo.crear(
            razon_social=razon, rut=rut, fuente="TEST",
            estado_calidad=estado or EstadoCalidadCliente.CONFIRMADO,
        )
        for razon, rut, estado in clientes
    ]
    return carpeta, creados


def _easy(tmp_path, *otros):
    return _catalogo(tmp_path, ("EASY RETAIL SA", RUT_EASY, None), *otros)


def _procesar(tmp_path, carpeta, monkeypatch, bloques, **extra):
    datos = {
        "número de guía": "475042", "número de transporte": "0000361447",
        "cliente": "No encontrado", "obra destino": "EBCO S.A",
        "chofer": "CRISTOPHER RETAMAL", "RUT del cliente": "No encontrado",
        "RUT del chofer": "17.576.134-9", "patente del tracto": "BPHR67",
        "patente del carro": "No encontrado",
        **extra,
    }
    monkeypatch.setattr(procesamiento, "leer_texto_imagen", Mock(return_value=["DESPACHAR A LOS MAITENES SUR 9800"]))
    monkeypatch.setattr(procesamiento, "leer_bloques_imagen", Mock(return_value=bloques))
    monkeypatch.setattr(procesamiento, "extraer_datos", Mock(return_value=datos))
    return procesar_archivo(tmp_path / "guia.jpg", carpeta_catalogos=carpeta, proveedor_rutas=object())


# --- Extracción documental -------------------------------------------------

@pytest.mark.parametrize("texto", ["SENOR(ES)", "ENOR(ES)", "NOR(ES)", "VOR(ES)", "OR(ES)", "SENORES"])
def test_fragmentos_validos_de_senor(texto):
    assert _es_fragmento_etiqueta_senor(texto)


@pytest.mark.parametrize("texto", ["SENOR DE LOS MILAGROS", "VR(ES)", "COMUNA", "R(ES)", "ORDEN"])
def test_no_confunde_otros_textos_con_senor(texto):
    assert not _es_fragmento_etiqueta_senor(texto)


@pytest.mark.parametrize("texto,esperado", [
    ("CODIGO CLIENTE", True), ("DLGO CLIENTE", True), ("DIGO CLIENTE", True),
    ("COD CLIENTE", True), ("CLIENTE", False), ("NUEVO CLIENTE", False),
])
def test_fragmento_codigo_cliente(texto, esperado):
    assert _es_fragmento_etiqueta_codigo_cliente(texto) is esperado


def test_extrae_cabecera_truncada_475042():
    identidad = _extraer_identidad_cliente_cabecera_truncada(_bloques_475042())
    assert identidad == {
        "cliente": "EASY REIAIL SA", "rut": RUT_EASY,
        "codigo_cliente": "0001001422", "rut_ambiguo": False,
    }


def test_dos_rut_validos_en_la_fila_es_ambiguo():
    # Un segundo RUT válido alineado con la columna de valores, en la misma
    # fila y contiguo: no hay un candidato único.
    bloques = _bloques_475042(rut=("76.568.660-1", "50.234.350-5"))
    identidad = _extraer_identidad_cliente_cabecera_truncada(bloques)
    assert identidad["rut"] == ""
    assert identidad["rut_ambiguo"] is True


# --- Resolución contra catálogo -------------------------------------------

def test_regresion_475042_resuelve_cliente_confirmado(tmp_path, monkeypatch):
    carpeta, (easy,) = _easy(tmp_path)
    antes = (carpeta / "clientes.json").read_text(encoding="utf-8")

    salida = _procesar(tmp_path, carpeta, monkeypatch, _bloques_475042())

    assert salida["cliente"] == "EASY RETAIL SA"
    assert salida["rut_cliente"] == RUT_EASY
    assert salida["codigo_cliente"] == "0001001422"
    assert "CLIENTE_AUSENTE" not in salida["motivos_revision_documento"]
    metodos = salida["metodos_recuperacion_documento"]
    assert "CATALOGO_RUT_CLIENTE" in metodos and "GEOMETRICO" in metodos
    auditoria = json.loads(salida["metricas_procesamiento_json"])["recuperacion_cliente_documental"]
    assert auditoria["cliente_id"] == easy.cliente_id
    assert auditoria["via"] == "RUT"
    assert auditoria["nombre_documental"] == "EASY REIAIL SA"
    # Nunca crea ni modifica clientes.
    assert (carpeta / "clientes.json").read_text(encoding="utf-8") == antes


def test_rut_no_catalogado_conserva_cliente_ausente(tmp_path, monkeypatch):
    carpeta, _ = _catalogo(tmp_path, ("OTRO CLIENTE SA", RUT_OTRO, None))
    antes = (carpeta / "clientes.json").read_text(encoding="utf-8")

    salida = _procesar(tmp_path, carpeta, monkeypatch, _bloques_475042())

    assert salida["cliente"] == "No encontrado"
    assert "CLIENTE_AUSENTE" in salida["motivos_revision_documento"]
    assert (carpeta / "clientes.json").read_text(encoding="utf-8") == antes


def test_rut_ambiguo_conserva_cliente_ausente(tmp_path, monkeypatch):
    carpeta, _ = _easy(tmp_path, ("OTRO CLIENTE SA", RUT_OTRO, None))
    salida = _procesar(
        tmp_path, carpeta, monkeypatch, _bloques_475042(rut=("76.568.660-1", "50.234.350-5")),
    )
    assert salida["cliente"] == "No encontrado"
    assert "CLIENTE_AUSENTE" in salida["motivos_revision_documento"]


def test_cliente_no_confirmado_no_resuelve(tmp_path):
    carpeta, _ = _catalogo(tmp_path, ("EASY RETAIL SA", RUT_EASY, EstadoCalidadCliente.PENDIENTE))
    datos = {"cliente": "No encontrado"}
    identidad = {"cliente": "EASY RETAIL SA", "rut": RUT_EASY, "codigo_cliente": ""}
    assert _completar_cliente_ausente_por_cabecera_documental(datos, identidad, carpeta) is None
    assert datos["cliente"] == "No encontrado"


def test_rut_duplicado_en_catalogo_es_ambiguo(tmp_path):
    carpeta, _ = _easy(tmp_path)
    ruta = carpeta / "clientes.json"
    contenido = json.loads(ruta.read_text(encoding="utf-8"))
    duplicado = dict(contenido["clientes"][0])
    duplicado.update(cliente_id="cliente-duplicado", razon_social="EASY DUPLICADO SA",
                     nombre_normalizado="EASY DUPLICADO")
    contenido["clientes"].append(duplicado)
    ruta.write_text(json.dumps(contenido), encoding="utf-8")
    datos = {"cliente": "No encontrado"}
    identidad = {"cliente": "EASY REIAIL SA", "rut": RUT_EASY, "codigo_cliente": ""}
    assert _completar_cliente_ausente_por_cabecera_documental(datos, identidad, carpeta) is None


def test_nombre_exacto_de_otro_cliente_contradice_rut(tmp_path):
    carpeta, _ = _easy(tmp_path, ("OTRO CLIENTE SA", RUT_OTRO, None))
    datos = {"cliente": "No encontrado"}
    identidad = {"cliente": "OTRO CLIENTE SA", "rut": RUT_EASY, "codigo_cliente": ""}
    assert _completar_cliente_ausente_por_cabecera_documental(datos, identidad, carpeta) is None
    assert datos["cliente"] == "No encontrado"


def test_nombre_legible_sin_tokens_comunes_contradice_rut(tmp_path):
    carpeta, _ = _easy(tmp_path)
    datos = {"cliente": "No encontrado"}
    identidad = {"cliente": "CONSTRUCTORA PEHUEN LTDA", "rut": RUT_EASY, "codigo_cliente": ""}
    assert _completar_cliente_ausente_por_cabecera_documental(datos, identidad, carpeta) is None


def test_rut_primario_distinto_contradice_cabecera(tmp_path):
    carpeta, _ = _easy(tmp_path, ("OTRO CLIENTE SA", RUT_OTRO, None))
    datos = {"cliente": "No encontrado", "RUT del cliente": RUT_OTRO}
    identidad = {"cliente": "EASY REIAIL SA", "rut": RUT_EASY, "codigo_cliente": ""}
    assert _completar_cliente_ausente_por_cabecera_documental(datos, identidad, carpeta) is None
    assert datos["cliente"] == "No encontrado"


def test_nombre_exacto_solo_no_decide(tmp_path):
    carpeta, _ = _easy(tmp_path)
    datos = {"cliente": "No encontrado"}
    identidad = {"cliente": "EASY RETAIL SA", "rut": "", "codigo_cliente": ""}
    assert _completar_cliente_ausente_por_cabecera_documental(datos, identidad, carpeta) is None


def test_codigo_confirmado_mas_nombre_exacto_resuelve(tmp_path):
    carpeta, (easy,) = _easy(tmp_path)
    CatalogoCodigosCliente(carpeta / "codigos_cliente.json").confirmar(
        codigo="0001001422", cliente_id=easy.cliente_id, actor="TEST", fuente="TEST",
    )
    datos = {"cliente": "No encontrado"}
    identidad = {"cliente": "EASY RETAIL SA", "rut": "", "codigo_cliente": "0001001422"}
    evidencia = _completar_cliente_ausente_por_cabecera_documental(datos, identidad, carpeta)
    assert evidencia is not None and evidencia["via"] == "CODIGO_CLIENTE"
    assert datos["cliente"] == "EASY RETAIL SA"
    assert datos["código cliente"] == "0001001422"


def test_codigo_confirmado_con_nombre_no_exacto_no_resuelve(tmp_path):
    carpeta, (easy,) = _easy(tmp_path)
    CatalogoCodigosCliente(carpeta / "codigos_cliente.json").confirmar(
        codigo="0001001422", cliente_id=easy.cliente_id, actor="TEST", fuente="TEST",
    )
    datos = {"cliente": "No encontrado"}
    identidad = {"cliente": "EASY REIAIL SA", "rut": "", "codigo_cliente": "0001001422"}
    assert _completar_cliente_ausente_por_cabecera_documental(datos, identidad, carpeta) is None


def test_codigo_de_otro_cliente_contradice_rut(tmp_path):
    carpeta, (easy, otro) = _easy(tmp_path, ("OTRO CLIENTE SA", RUT_OTRO, None))
    CatalogoCodigosCliente(carpeta / "codigos_cliente.json").confirmar(
        codigo="0001001422", cliente_id=otro.cliente_id, actor="TEST", fuente="TEST",
    )
    datos = {"cliente": "No encontrado"}
    identidad = {"cliente": "EASY REIAIL SA", "rut": RUT_EASY, "codigo_cliente": "0001001422"}
    assert _completar_cliente_ausente_por_cabecera_documental(datos, identidad, carpeta) is None


def test_cliente_ya_presente_no_se_toca(tmp_path):
    carpeta, _ = _easy(tmp_path)
    datos = {"cliente": "CLIENTE DOCUMENTAL SA"}
    identidad = {"cliente": "EASY REIAIL SA", "rut": RUT_EASY, "codigo_cliente": ""}
    assert _completar_cliente_ausente_por_cabecera_documental(datos, identidad, carpeta) is None
    assert datos["cliente"] == "CLIENTE DOCUMENTAL SA"
