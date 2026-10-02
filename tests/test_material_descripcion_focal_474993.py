"""Relectura focal de la región DESCRIPCION -- regresión real 474993.

Guía 474993 (envío Mobile 762cb967, transporte 0000361291): la imagen
original conservada muestra "B HORMIGON 8MM 12M A630-420H (N)" bajo
DESCRIPCION, pero el OCR general (y su relectura completa) nunca detectó esa
línea: el detector la funde con el borde de la tabla. Sólo cuando el
material sigue ausente tras el flujo normal, Atlas localiza la celda por la
estructura del documento (encabezado DESCRIPCION, vecinos CODIGO/UNIDAD, pie
de tabla), relee esa región con el mismo proveedor de la ingesta y reutiliza
`extraer_descripcion_material`. Acepta sólo si todas las lecturas (dos
anclajes de borde x dos variantes) coinciden; si no, se abstiene.

Los bloques estructurales son los reales de 474993 (sólo encabezados, la
línea "Coladas" y pies de tabla). El OCR real no se ejecuta en la suite.
"""
from __future__ import annotations

import csv
import json

import pytest
from PIL import Image

from atlas_core.ocr import BloqueOCR
from atlas_core.procesamiento_masivo import COLUMNAS
from atlas_core.revalidacion_documental import (
    METODO_RELECTURA_FOCAL_DESCRIPCION,
    _localizar_region_descripcion_material,
    reprocesar_material_focal_desde_imagen_original,
)

GUIA = "474993"
ENVIO = "762cb967-78af-412e-833a-b0d5ab1c5e7f"
ARCHIVO = f"mobile/{ENVIO}/original.jpg"
MATERIAL = "B HORMIGON 8MM 12M A630-420H (N)"
COLADAS = "Coladas: 2617955002"
TAMANO_IMAGEN = (3024, 4032)  # marco orientado (EXIF aplicado) de la foto real


def _b(texto, x1, y1, x2, y2):
    return BloqueOCR(texto, ((x1, y1), (x2, y1), (x2, y2), (x1, y2)), 0.99)


def _bloques_474993():
    return [
        _b("CANTIDAD", 149, 1292, 380, 1346), _b("CODIGO", 565, 1315, 743, 1371),
        _b("VALOR", 2649, 1340, 2801, 1385), _b("UNIDAD", 2186, 1359, 2346, 1397),
        _b("PRECIO", 2392, 1349, 2554, 1391), _b("DESCRIPCION", 1399, 1379, 1672, 1421),
        _b(COLADAS, 907, 1469, 1352, 1537), _b("TIPO DE DOCUMENTO", 257, 2392, 734, 2438),
        _b("PESO KG.", 98, 2582, 325, 2633), _b("DESPACHAR A", 91, 2664, 429, 2716),
    ]


class _Proveedor:
    """Proveedor de la ingesta: lectura completa sin la línea de producto;
    las lecturas de recortes (archivos temporales) responden `focal`."""

    def __init__(self, focal=None, *, bloques=None, completo=("DESCRIPCION", COLADAS)):
        self.focal = focal or (lambda variante, ancho: [MATERIAL, COLADAS])
        self.bloques = _bloques_474993() if bloques is None else bloques
        self.completo = list(completo)
        self.recortes = []
        self.lecturas_completas = 0

    def leer_texto(self, ruta):
        ruta = str(ruta)
        if ruta.endswith("original.jpg") or ruta.endswith(".jpeg"):
            self.lecturas_completas += 1
            return list(self.completo)
        with Image.open(ruta) as recorte:
            self.recortes.append(recorte.size)
            ancho = recorte.size[0]
        return list(self.focal(ruta.rsplit("\\", 1)[-1].rsplit("/", 1)[-1], ancho))

    def leer_bloques(self, ruta):
        return list(self.bloques)


def _fila(**overrides):
    fila = {c: "" for c in COLUMNAS}
    fila.update(
        archivo=ARCHIVO, numero_guia=GUIA, numero_transporte="0000361291", cliente="PRODALAM SA",
        descripcion_material="", tipo_carga="NO DETERMINADO", motivos_revision_documento="MATERIAL_AUSENTE",
        indicador_revision="OK", estado_documental="OK", estado_operacional="OK",
        estado_ruta="RUTA_CALCULADA", metodos_recuperacion_documento="CATALOGO_OBRA_DESTINO",
    )
    fila.update(overrides)
    return fila


def _entorno(tmp_path, filas=None):
    raiz = tmp_path / "Atlas"
    actual = raiz / "operacion" / "actual"
    envio = raiz / "operacion" / "mobile" / "envios" / ENVIO
    actual.mkdir(parents=True)
    envio.mkdir(parents=True)
    with (actual / "analisis_completo_guias.csv").open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNAS, delimiter=";")
        w.writeheader()
        w.writerows(filas or [_fila()])
    Image.new("RGB", TAMANO_IMAGEN, color="white").save(envio / "original.jpg")
    return raiz


def _leer(raiz):
    with (raiz / "operacion" / "actual" / "analisis_completo_guias.csv").open(newline="", encoding="utf-8-sig") as fh:
        return {f["numero_guia"]: f for f in csv.DictReader(fh, delimiter=";")}


def _trazas_focales(raiz):
    return sorted((raiz / "operacion" / "trazas_ocr" / "focal_material").glob("*.json"))


def _reprocesar(raiz, proveedor):
    return reprocesar_material_focal_desde_imagen_original(raiz_atlas=raiz, numero_guia=GUIA, proveedor_ocr=proveedor)


# --- 1. localización por estructura (bloques reales de 474993) ---

def test_region_descripcion_se_deriva_de_encabezados_y_pie_reales():
    bloques = _bloques_474993()
    assert _localizar_region_descripcion_material(bloques, avance_izquierdo=0.15) == pytest.approx((841.4, 1421.0, 1929.0, 1621.0))
    assert _localizar_region_descripcion_material(bloques, avance_izquierdo=0.05) == pytest.approx((775.8, 1421.0, 1929.0, 1621.0))


@pytest.mark.parametrize("quitar,agregar", [
    ({"DESCRIPCION"}, []),                                           # sin encabezado
    ({"UNIDAD", "PRECIO", "VALOR"}, []),                             # sin vecino derecho
    ({"CODIGO", "CANTIDAD"}, []),                                    # sin vecino izquierdo
    ({"TIPO DE DOCUMENTO", "PESO KG.", "DESPACHAR A"}, []),          # sin pie de tabla
    (set(), [_b("DESCRIPCION", 1399, 2000, 1672, 2042)]),            # dos DESCRIPCION
])
def test_estructura_incompleta_o_ambigua_no_localiza_region(quitar, agregar):
    bloques = [b for b in _bloques_474993() if b.texto not in quitar] + agregar
    assert _localizar_region_descripcion_material(bloques) is None


# --- 2. regresión real 474993 ---

def test_474993_recupera_material_desde_descripcion_con_trazabilidad(tmp_path):
    raiz = _entorno(tmp_path)
    proveedor = _Proveedor()

    resultado = _reprocesar(raiz, proveedor)

    assert resultado["aplicado"] is True
    assert resultado["descripcion_material"] == MATERIAL
    assert resultado["metodo"] == METODO_RELECTURA_FOCAL_DESCRIPCION
    fila = _leer(raiz)[GUIA]
    assert fila["descripcion_material"] == MATERIAL
    assert fila["tipo_carga"] != "NO DETERMINADO"
    assert "MATERIAL_AUSENTE" not in fila["motivos_revision_documento"]
    assert fila["metodos_recuperacion_documento"] == f"CATALOGO_OBRA_DESTINO | {METODO_RELECTURA_FOCAL_DESCRIPCION}"
    # Recortes exactos de la celda (sin margen que reintroduzca el encabezado):
    # 2 anclajes de borde x 2 variantes, alto = 1621 - 1421.
    assert sorted(proveedor.recortes) == [(1088, 200), (1088, 200), (1154, 200), (1154, 200)]
    # Trazabilidad aditiva: la lectura focal queda aparte, con sus 4 lecturas.
    (traza,) = _trazas_focales(raiz)
    contenido = json.loads(traza.read_text(encoding="utf-8"))
    assert traza.name.startswith(f"{GUIA}.")
    assert contenido["archivo"] == ARCHIVO
    assert contenido["material_consensuado"] == MATERIAL
    assert len(contenido["lecturas"]) == 4
    assert all(l["lineas"] == [MATERIAL, COLADAS] for l in contenido["lecturas"])
    # La traza vigente sigue siendo la lectura completa del documento (sin la línea).
    vigentes = [p for p in (raiz / "operacion" / "trazas_ocr").glob("*.json")]
    assert vigentes and all(MATERIAL not in p.read_text(encoding="utf-8") for p in vigentes)


# --- 3. negativos: lectura ambigua o insuficiente se abstiene ---

def _sin_cambios(raiz):
    fila = _leer(raiz)[GUIA]
    assert fila["descripcion_material"] == ""
    assert fila["motivos_revision_documento"] == "MATERIAL_AUSENTE"
    assert fila["metodos_recuperacion_documento"] == "CATALOGO_OBRA_DESTINO"


@pytest.mark.parametrize("focal", [
    # Un anclaje amputa la primera letra (casos reales 473550/474576).
    lambda variante, ancho: ["HORMIGON 8MM 12M A630-420H (N)", COLADAS] if ancho == 1088 else [MATERIAL, COLADAS],
    # Una variante no ve la línea (fragilidad real del detector).
    lambda variante, ancho: [COLADAS] if "grises" in variante else [MATERIAL, COLADAS],
    # Dos lecturas distintas del diámetro.
    lambda variante, ancho: ["B HORMIGON 10MM 12M A630-420H (N)", COLADAS] if "grises" in variante else [MATERIAL, COLADAS],
    # Sólo se lee la línea de coladas.
    lambda variante, ancho: [COLADAS],
    # Nada legible.
    lambda variante, ancho: [],
])
def test_lectura_focal_ambigua_o_insuficiente_se_abstiene(tmp_path, focal):
    raiz = _entorno(tmp_path)
    resultado = _reprocesar(raiz, _Proveedor(focal))
    assert resultado["aplicado"] is False
    assert resultado["motivo"] == "MATERIAL_NO_RECUPERABLE_TRAS_REPROCESO"
    assert resultado["detalle_focal"] == "LECTURA_FOCAL_SIN_CONSENSO"
    _sin_cambios(raiz)
    (traza,) = _trazas_focales(raiz)
    assert json.loads(traza.read_text(encoding="utf-8"))["resultado"] == "ABSTENCION"


def test_estructura_incompleta_nunca_relee_recortes(tmp_path):
    raiz = _entorno(tmp_path)
    proveedor = _Proveedor(bloques=[b for b in _bloques_474993() if b.texto != "DESCRIPCION"])
    resultado = _reprocesar(raiz, proveedor)
    assert resultado["detalle_focal"] == "ESTRUCTURA_DESCRIPCION_INCOMPLETA"
    assert proveedor.recortes == []
    _sin_cambios(raiz)


def test_error_de_la_lectura_focal_no_altera_la_fila(tmp_path):
    raiz = _entorno(tmp_path)

    def falla(variante, ancho):
        raise RuntimeError("worker OCR caído")

    resultado = _reprocesar(raiz, _Proveedor(falla))
    assert resultado["aplicado"] is False
    assert resultado["detalle_focal"].startswith("ERROR_RELECTURA_FOCAL")
    _sin_cambios(raiz)


# --- 4. sólo cuando el flujo normal no resolvió ---

def test_material_ya_presente_no_ejecuta_ningun_ocr(tmp_path):
    raiz = _entorno(tmp_path, [_fila(descripcion_material="ALAMBRON 5,5MM SAE 1005 (I)", motivos_revision_documento="")])
    proveedor = _Proveedor()
    resultado = _reprocesar(raiz, proveedor)
    assert resultado["motivo"] == "MATERIAL_YA_PRESENTE"
    assert proveedor.lecturas_completas == 0 and proveedor.recortes == []
    assert _leer(raiz)[GUIA]["descripcion_material"] == "ALAMBRON 5,5MM SAE 1005 (I)"


def test_flujo_normal_que_recupera_no_dispara_relectura_focal(tmp_path):
    raiz = _entorno(tmp_path)
    proveedor = _Proveedor(completo=("DESCRIPCION", "B HORMIGON 12MM 12M A630-420H (N)", COLADAS))
    resultado = _reprocesar(raiz, proveedor)
    assert resultado["descripcion_material"] == "B HORMIGON 12MM 12M A630-420H (N)"
    assert "metodo" not in resultado
    assert proveedor.recortes == []
    assert _trazas_focales(raiz) == []
    assert _leer(raiz)[GUIA]["metodos_recuperacion_documento"] == "CATALOGO_OBRA_DESTINO"
