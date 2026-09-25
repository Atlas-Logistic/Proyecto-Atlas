"""Bloque ORIENTACIÓN DOCUMENTAL -- caso real 480603/480604 (0000360179):
fotos giradas 90° sin EXIF rompían el emparejado geométrico etiqueta->valor.
Pruebas con OCR simulado: la decisión usa sólo la geometría/confianza que
el propio OCR devuelve, nunca EXIF ni el nombre del archivo."""
from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

from atlas_core import procesamiento_masivo as pm
from atlas_core.ocr import BloqueOCR
from atlas_core.orientacion_documental import medir_orientacion, normalizar_orientacion

ETIQUETAS = [
    "GUIA DE DESPACHO ELECTRONICA", "SEÑOR(ES)", "R.U.T.", "DESPACHAR A", "FECHA DE EMISION",
    "RUT CHOFER", "EMPRESA TRANSPORTE", "OBRA DESTINO", "Nro. TRANSPORTE", "CODIGO CLIENTE",
]


def _bloque(texto, vertical, confianza=0.99, y=0.0):
    ancho, alto = (20.0, 200.0) if vertical else (200.0, 20.0)
    return BloqueOCR(texto=texto, bounding_box=((0.0, y), (ancho, y), (ancho, y + alto), (0.0, y + alto)), confianza=confianza)


def _legibles(vertical):
    return [_bloque(t, vertical, y=i * 30.0) for i, t in enumerate(ETIQUETAS)]


def _basura(vertical):
    return [_bloque(t, vertical, confianza=0.7, y=i * 30.0) for i, t in enumerate(
        ["OIVHDSEd", "VNOISIWE", "XOHOLNL", "WOPPINS", "ZIDWNEJ", "ONSODAL", "LNEIIO", "VLVNIS", "ADNNOL", "OTSEG"])]


def _imagen(tmp_path: Path, nombre="guia.jpeg") -> Path:
    ruta = tmp_path / nombre
    Image.new("RGB", (160, 120), "white").save(ruta)
    return ruta


class LectorFalso:
    """OCR simulado: responde según el ángulo codificado en el nombre de la
    copia girada (`<stem>.orientada_<angulo>.png`)."""

    def __init__(self, por_angulo):
        self.por_angulo = por_angulo
        self.lecturas: list[str] = []

    def __call__(self, ruta):
        self.lecturas.append(Path(ruta).name)
        nombre = Path(ruta).name
        angulo = int(nombre.split(".orientada_")[1].split(".")[0]) if ".orientada_" in nombre else 0
        return self.por_angulo[angulo]


def test_medir_orientacion_distingue_texto_vertical_y_horizontal() -> None:
    assert medir_orientacion(_legibles(vertical=True)).fraccion_vertical == 1.0
    horizontal = medir_orientacion(_legibles(vertical=False))
    assert horizontal.fraccion_vertical == 0.0 and horizontal.anclas >= 8


def test_documento_derecho_no_se_gira_ni_relee(tmp_path) -> None:
    ruta = _imagen(tmp_path)
    lector = LectorFalso({0: _legibles(vertical=False)})
    resultado = normalizar_orientacion(ruta, lector)
    assert resultado.angulo_correccion == 0 and resultado.ruta_ocr == ruta
    assert lector.lecturas == ["guia.jpeg"], "una sola lectura, sin candidatos"
    assert resultado.bloques is not None and resultado.diagnostico == {}


def test_foto_girada_90_elige_la_rotacion_legible_y_la_imagen_girada_existe(tmp_path) -> None:
    ruta = _imagen(tmp_path)
    lector = LectorFalso({0: _legibles(vertical=True), 90: _legibles(vertical=False), 270: _basura(vertical=False)})
    resultado = normalizar_orientacion(ruta, lector)
    try:
        assert resultado.angulo_correccion == 90
        assert resultado.ruta_ocr.exists() and resultado.ruta_ocr != ruta
        assert Image.open(resultado.ruta_ocr).size == (120, 160), "girada 90° con expand"
        assert resultado.diagnostico["resultado"] == "CORREGIDA"
    finally:
        resultado.limpiar()
    assert not resultado.ruta_ocr.exists(), "la copia temporal se limpia"


def test_foto_girada_270_elige_la_otra_rotacion(tmp_path) -> None:
    ruta = _imagen(tmp_path)
    lector = LectorFalso({0: _legibles(vertical=True), 90: _basura(vertical=False), 270: _legibles(vertical=False)})
    resultado = normalizar_orientacion(ruta, lector)
    assert resultado.angulo_correccion == 270
    resultado.limpiar()


def test_foto_invertida_180_se_corrige_solo_si_mejora_con_claridad(tmp_path) -> None:
    ruta = _imagen(tmp_path)
    corregida = normalizar_orientacion(ruta, LectorFalso({0: _basura(vertical=False), 180: _legibles(vertical=False)}))
    assert corregida.angulo_correccion == 180
    corregida.limpiar()
    # Foto simplemente mala (180° tampoco se lee): se conserva la original.
    sin_mejora = normalizar_orientacion(ruta, LectorFalso({0: _basura(vertical=False), 180: _basura(vertical=False)}))
    assert sin_mejora.angulo_correccion == 0 and sin_mejora.ruta_ocr == ruta
    assert sin_mejora.diagnostico["resultado"] == "SIN_CANDIDATO_CLARO"


def test_empate_entre_90_y_270_se_abstiene(tmp_path) -> None:
    ruta = _imagen(tmp_path)
    lector = LectorFalso({0: _legibles(vertical=True), 90: _legibles(vertical=False), 270: _legibles(vertical=False)})
    resultado = normalizar_orientacion(ruta, lector)
    assert resultado.angulo_correccion == 0 and resultado.ruta_ocr == ruta


def test_archivo_que_no_es_imagen_no_se_lee_ni_se_gira(tmp_path) -> None:
    ruta = tmp_path / "guia.pdf"
    ruta.write_bytes(b"%PDF-1.4 no es una imagen")
    lector = LectorFalso({})
    resultado = normalizar_orientacion(ruta, lector)
    assert resultado.angulo_correccion == 0 and resultado.bloques is None and lector.lecturas == []


# ---------------------------------------------------------------- integración

class ProveedorFalso:
    def __init__(self, por_angulo):
        self.lector = LectorFalso(por_angulo)
        self.rutas_texto: list[str] = []
        self.rutas_focal: list[str] = []

    def leer_bloques(self, ruta):
        return self.lector(ruta)

    def leer_texto(self, ruta):
        self.rutas_texto.append(Path(ruta).name)
        return [b.texto for b in self.lector.por_angulo[0 if ".orientada_" not in Path(ruta).name else 90]]

    def leer_focal(self, ruta, caja, allowlist):
        self.rutas_focal.append(Path(ruta).name)
        return {"recorte": list(caja), "lecturas": []}


def test_procesar_archivo_lee_texto_y_bloques_de_la_imagen_girada(tmp_path) -> None:
    ruta = _imagen(tmp_path, "480604.jpeg")
    proveedor = ProveedorFalso({0: _legibles(vertical=True), 90: _legibles(vertical=False), 270: _basura(vertical=False)})
    resultado = pm.procesar_archivo(ruta, proveedor=proveedor)
    assert proveedor.rutas_texto == ["480604.orientada_90.png"]
    assert all(r == "480604.orientada_90.png" for r in proveedor.rutas_focal)
    lecturas_bloques = proveedor.lector.lecturas
    assert lecturas_bloques[:3] == ["480604.jpeg", "480604.orientada_90.png", "480604.orientada_270.png"]
    assert lecturas_bloques[3:] == [], "los bloques ya leídos de la imagen elegida se reutilizan"
    orientacion = json.loads(resultado["metricas_procesamiento_json"])["orientacion_documental"]
    assert orientacion["angulo_correccion"] == 90 and orientacion["metodo"] == "GEOMETRIA_OCR"


def test_procesar_archivo_documento_derecho_conserva_comportamiento(tmp_path) -> None:
    ruta = _imagen(tmp_path, "473316.jpeg")
    proveedor = ProveedorFalso({0: _legibles(vertical=False)})
    resultado = pm.procesar_archivo(ruta, proveedor=proveedor)
    assert proveedor.rutas_texto == ["473316.jpeg"]
    assert all(r == "473316.jpeg" for r in proveedor.rutas_focal)
    assert proveedor.lector.lecturas == ["473316.jpeg"], "una sola lectura de bloques, reutilizada"
    assert "orientacion_documental" not in json.loads(resultado["metricas_procesamiento_json"])
