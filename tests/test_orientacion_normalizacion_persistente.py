"""P0 ORIENTACIÓN DOCUMENTAL PERSISTENTE -- el mismo documento sintético en
0°, 90° horario, 90° antihorario y 180° llega al OCR con la MISMA
orientación, el original queda intacto byte a byte, la versión normalizada
queda persistida con registro auditable y reprocesar no vuelve a girar.

El OCR es simulado pero se comporta como PaddleOCR real con
`use_textline_orientation=False` (calibrado con una guía sintética): un
documento girado 90° horario se lee bien pero con líneas VERTICALES; 90°
antihorario da líneas verticales ilegibles; 180° da líneas horizontales
ilegibles. El simulador identifica la orientación real COMPARANDO PÍXELES
contra el documento de referencia -- nunca por nombre de archivo. Ningún
dato real: documento inventado."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFont, ImageOps

from atlas_core import procesamiento_masivo as pm
from atlas_core.evidencia_documental import resolver_ruta_evidencia
from atlas_core.ocr import BloqueOCR
from atlas_core.orientacion_documental import (
    ABSTENCION_AMBIGUA, CORREGIDA, SIN_ROTACION, SIN_TEXTO, YA_NORMALIZADA,
    directorio_orientacion_para_raiz, leer_registro, marca_normalizada, normalizar_orientacion,
    ruta_operacional, sha256_archivo,
)
from tests.fixtures_pdf_sinteticos import PaginaSintetica, construir_pdf

LINEAS = [
    "EMPRESA DEMO ACEROS S.A.",
    "GUIA DE DESPACHO ELECTRONICA",
    "N 000123",
    "SEÑOR(ES): CONSTRUCTORA EJEMPLO LTDA",
    "R.U.T.: 76.123.456-0",
    "DESPACHAR A: AVENIDA PRINCIPAL 1234, CONCEPCION",
    "FECHA EMISION: 12-08-2026",
    "OBRA DESTINO: EDIFICIO CENTRAL",
    "EMPRESA TRANSPORTE: TRANSPORTES PRUEBA",
    "CHOFER: JUAN PEREZ RUT CHOFER: 12.345.678-5",
    "DESCRIPCION: BARRAS HORMIGON 12MM 1500 KG",
    "Nro. TRANSPORTE 0000123456",
]
ANCHO, ALTO, PASO, MARGEN = 900, 1200, 80, 60

# Giro que TIENE el documento (grados antihorario, PIL `rotate`) -> giro
# antihorario que Atlas debe aplicarle para dejarlo derecho.
VARIANTES = {
    "0": (0, 0),
    "90_horario": (270, 90),
    "90_antihorario": (90, 270),
    "180": (180, 180),
}


def _documento() -> Image.Image:
    imagen = Image.new("RGB", (ANCHO, ALTO), "white")
    dibujo = ImageDraw.Draw(imagen)
    fuente = ImageFont.load_default(size=26)
    for indice, linea in enumerate(LINEAS):
        dibujo.text((MARGEN, MARGEN + indice * PASO), linea, fill="black", font=fuente)
    # Marca asimétrica: evita que dos rotaciones se parezcan en píxeles.
    dibujo.rectangle((ANCHO - 200, ALTO - 120, ANCHO - 60, ALTO - 60), fill="black")
    return imagen


def _huella(imagen: Image.Image) -> list[int]:
    return list(ImageOps.grayscale(imagen).resize((24, 32) if imagen.width < imagen.height else (32, 24)).tobytes())


class OCRSimulado:
    """Contrato ProveedorOCR. Registra con qué orientación REAL (medida en
    píxeles) llegó cada lectura de texto/bloques/focal."""

    def __init__(self, referencia: Image.Image) -> None:
        self.huellas = {k: _huella(referencia.rotate(k, expand=True)) for k in (0, 90, 180, 270)}
        self.vistas: dict[str, list[int]] = {"texto": [], "bloques": [], "focal": []}

    def giro_real(self, ruta) -> int:
        with Image.open(ruta) as imagen:
            huella = _huella(ImageOps.exif_transpose(imagen).convert("RGB"))
        distancias = {
            k: sum(abs(a - b) for a, b in zip(h, huella))
            for k, h in self.huellas.items() if len(h) == len(huella)
        }
        return min(distancias, key=distancias.get)

    def _bloques(self, giro: int) -> list[BloqueOCR]:
        bloques = []
        for indice, linea in enumerate(LINEAS):
            x1, y1 = MARGEN, MARGEN + indice * PASO
            x2, y2 = x1 + 16 * len(linea), y1 + 30
            legible = giro in (0, 270)
            texto = linea if legible else linea[::-1].replace("A", "V").replace("E", "Ǝ")
            if giro in (0, 180):
                caja = ((x1, y1), (x2, y1), (x2, y2), (x1, y2))
            else:  # vertical: ancho y alto intercambiados
                caja = ((y1, x1), (y2, x1), (y2, x2), (y1, x2))
            bloques.append(BloqueOCR(texto=texto, bounding_box=caja, confianza=0.99 if legible else 0.7))
        return bloques

    def leer_bloques(self, ruta):
        giro = self.giro_real(ruta)
        self.vistas["bloques"].append(giro)
        return self._bloques(giro)

    def leer_texto(self, ruta):
        giro = self.giro_real(ruta)
        self.vistas["texto"].append(giro)
        return [b.texto for b in self._bloques(giro)]

    def leer_focal(self, ruta, caja, allowlist=""):
        self.vistas["focal"].append(self.giro_real(ruta))
        return {"recorte": list(caja), "lecturas": []}


def _sha(ruta: Path) -> str:
    return hashlib.sha256(ruta.read_bytes()).hexdigest()


@pytest.fixture
def referencia() -> Image.Image:
    return _documento()


def _variante(tmp_path: Path, referencia: Image.Image, nombre: str, formato: str = "JPEG") -> Path:
    giro, _ = VARIANTES[nombre]
    carpeta = tmp_path / "entradas"
    carpeta.mkdir(exist_ok=True)
    ruta = carpeta / f"guia_{nombre}.{'jpg' if formato == 'JPEG' else 'png'}"
    referencia.rotate(giro, expand=True).save(ruta, format=formato, quality=92)
    return ruta


def _raiz(tmp_path: Path) -> tuple[Path, Path]:
    raiz = tmp_path / "atlas"
    catalogos = raiz / "catalogos"
    catalogos.mkdir(parents=True, exist_ok=True)
    return raiz, catalogos


# ------------------------------------------------------- normalización pura

@pytest.mark.parametrize("nombre", list(VARIANTES))
def test_cuatro_orientaciones_quedan_derechas_y_persistidas(tmp_path, referencia, nombre) -> None:
    ruta = _variante(tmp_path, referencia, nombre)
    sha_original = _sha(ruta)
    ocr = OCRSimulado(referencia)
    directorio = tmp_path / "evidencia_orientada"
    resultado = normalizar_orientacion(ruta, ocr.leer_bloques, directorio_persistencia=directorio, referencia=f"lote/{ruta.name}")
    _, correccion = VARIANTES[nombre]

    assert resultado.angulo_correccion == correccion
    assert ocr.giro_real(resultado.ruta_ocr) == 0, "la ruta que usará el OCR está derecha"
    assert _sha(ruta) == sha_original, "el original queda intacto byte a byte"

    registro = leer_registro(directorio, sha_original)
    assert registro["referencias"] == [f"lote/{ruta.name}"]
    assert registro["nombre_original"] == ruta.name
    assert registro["rotacion_aplicada_grados_antihorario"] == correccion
    assert registro["orientacion_detectada_grados_horario"] == correccion
    assert registro["metodo"] == "GEOMETRIA_OCR" and registro["criterio"]
    assert "original" in registro["evidencia"]
    pngs = list(directorio.glob("*.png"))
    if correccion == 0:
        assert registro["resultado"] == SIN_ROTACION
        assert resultado.ruta_ocr == ruta, "0°: sin transformación ni recompresión"
        assert registro["version_normalizada"] is None and pngs == []
        assert ocr.vistas["bloques"] == [0], "0°: una sola lectura, sin candidatos"
    else:
        assert registro["resultado"] == CORREGIDA
        assert resultado.ruta_ocr.parent == directorio and pngs == [resultado.ruta_ocr]
        assert registro["version_normalizada"] == {"archivo": resultado.ruta_ocr.name, "sha256": _sha(resultado.ruta_ocr)}
        assert marca_normalizada(resultado.ruta_ocr)["sha256_original"] == sha_original
        assert resultado.bloques is not None, "los bloques de la versión elegida se reutilizan"
        with Image.open(resultado.ruta_ocr) as normalizada:
            assert normalizada.size == (ANCHO, ALTO)


def test_versiones_normalizadas_son_equivalentes_en_pixeles(tmp_path, referencia) -> None:
    """Transposición exacta: desde PNG, la versión normalizada es idéntica
    píxel a píxel al documento derecho."""
    derecho = referencia.tobytes()
    for nombre in ("90_horario", "90_antihorario", "180"):
        ruta = _variante(tmp_path, referencia, nombre, formato="PNG")
        resultado = normalizar_orientacion(
            ruta, OCRSimulado(referencia).leer_bloques, directorio_persistencia=tmp_path / "persistida",
        )
        with Image.open(resultado.ruta_ocr) as normalizada:
            assert normalizada.convert("RGB").tobytes() == derecho, nombre


def test_reprocesar_no_vuelve_a_girar_ni_acumula_copias(tmp_path, referencia) -> None:
    ruta = _variante(tmp_path, referencia, "90_horario")
    directorio = tmp_path / "evidencia_orientada"
    primero = normalizar_orientacion(ruta, OCRSimulado(referencia).leer_bloques, directorio_persistencia=directorio)
    archivos = sorted(p.name for p in directorio.iterdir())
    registro = leer_registro(directorio, sha256_archivo(ruta))

    ocr = OCRSimulado(referencia)
    segundo = normalizar_orientacion(ruta, ocr.leer_bloques, directorio_persistencia=directorio)
    assert ocr.vistas["bloques"] == [], "reutiliza el registro: sin lecturas de detección"
    assert segundo.ruta_ocr == primero.ruta_ocr and segundo.angulo_correccion == 90
    assert segundo.diagnostico["reutilizado"] is True
    assert sorted(p.name for p in directorio.iterdir()) == archivos
    assert leer_registro(directorio, sha256_archivo(ruta)) == registro

    # La propia versión normalizada, reingresada por cualquier vía, no se gira.
    ocr_normalizada = OCRSimulado(referencia)
    tercero = normalizar_orientacion(primero.ruta_ocr, ocr_normalizada.leer_bloques, directorio_persistencia=directorio)
    assert tercero.angulo_correccion == 0 and tercero.ruta_ocr == primero.ruta_ocr
    assert tercero.diagnostico["resultado"] == YA_NORMALIZADA
    assert ocr_normalizada.vistas["bloques"] == []
    assert sorted(p.name for p in directorio.iterdir()) == archivos


def test_version_normalizada_borrada_se_regenera_y_alterada_se_abstiene(tmp_path, referencia) -> None:
    ruta = _variante(tmp_path, referencia, "180")
    directorio = tmp_path / "evidencia_orientada"
    primero = normalizar_orientacion(ruta, OCRSimulado(referencia).leer_bloques, directorio_persistencia=directorio)
    sha_normalizada = _sha(primero.ruta_ocr)
    primero.ruta_ocr.unlink()
    regenerada = normalizar_orientacion(ruta, OCRSimulado(referencia).leer_bloques, directorio_persistencia=directorio)
    assert regenerada.ruta_ocr == primero.ruta_ocr and _sha(regenerada.ruta_ocr) == sha_normalizada

    regenerada.ruta_ocr.write_bytes(b"alterada")
    alterada = normalizar_orientacion(ruta, OCRSimulado(referencia).leer_bloques, directorio_persistencia=directorio)
    assert alterada.ruta_ocr == ruta and alterada.angulo_correccion == 0
    assert alterada.diagnostico["resultado"] == "NORMALIZADA_CORRUPTA"
    assert regenerada.ruta_ocr.read_bytes() == b"alterada", "nunca reescribe un derivado alterado"


def test_orientacion_ambigua_se_abstiene_sin_girar(tmp_path, referencia) -> None:
    """Dos rotaciones igual de legibles (ninguna evidencia para elegir)."""
    ruta = _variante(tmp_path, referencia, "90_horario")
    ocr = OCRSimulado(referencia)

    def lector(ruta_imagen):
        # La original se lee vertical; CUALQUIER rotación candidata, legible.
        return ocr._bloques(270 if ocr.giro_real(ruta_imagen) == 270 else 0)

    directorio = tmp_path / "evidencia_orientada"
    resultado = normalizar_orientacion(ruta, lector, directorio_persistencia=directorio)
    assert resultado.angulo_correccion == 0 and resultado.ruta_ocr == ruta
    registro = leer_registro(directorio, sha256_archivo(ruta))
    assert registro["resultado"] == ABSTENCION_AMBIGUA
    assert registro["orientacion_detectada_grados_horario"] is None
    assert registro["version_normalizada"] is None and list(directorio.glob("*.png")) == []


def test_imagen_sin_texto_se_abstiene(tmp_path) -> None:
    ruta = tmp_path / "foto.jpg"
    Image.new("RGB", (300, 200), "gray").save(ruta)
    directorio = tmp_path / "evidencia_orientada"
    lecturas = []
    resultado = normalizar_orientacion(ruta, lambda r: lecturas.append(r) or [], directorio_persistencia=directorio)
    assert resultado.ruta_ocr == ruta and resultado.angulo_correccion == 0 and len(lecturas) == 1
    assert leer_registro(directorio, sha256_archivo(ruta))["resultado"] == SIN_TEXTO


# ------------------------------------------------ pipeline: procesar_archivo

_CAMPOS_VOLATILES = {"archivo", "metricas_procesamiento_json", "fecha_ingesta_utc"}


def test_procesar_archivo_cuatro_orientaciones_extraen_lo_mismo(tmp_path, referencia) -> None:
    raiz, catalogos = _raiz(tmp_path)
    resultados = {}
    for nombre, (_, correccion) in VARIANTES.items():
        ruta = _variante(tmp_path, referencia, nombre)
        sha_original = _sha(ruta)
        ocr = OCRSimulado(referencia)
        salida = dict(pm.procesar_archivo(ruta, proveedor=ocr, carpeta_catalogos=catalogos, proveedor_rutas=object()))
        assert set(ocr.vistas["texto"]) == {0}, f"{nombre}: el OCR de texto leyó la versión derecha"
        assert set(ocr.vistas["focal"]) <= {0}, f"{nombre}: lecturas focales sobre la versión derecha"
        assert _sha(ruta) == sha_original
        metricas = json.loads(salida["metricas_procesamiento_json"])["orientacion_documental"]
        assert metricas["angulo_correccion"] == correccion
        resultados[nombre] = {k: v for k, v in salida.items() if k not in _CAMPOS_VOLATILES}

    base = resultados["0"]
    assert base["numero_guia"] not in ("", "No encontrado"), "la extracción de referencia no es vacía"
    for nombre, campos in resultados.items():
        assert campos == base, f"{nombre}: extracción distinta a la del documento derecho"

    directorio = directorio_orientacion_para_raiz(raiz)
    assert len(list(directorio.glob("*.json"))) == 4 and len(list(directorio.glob("*.png"))) == 3


def test_procesar_archivo_reprocesado_reutiliza_la_version_normalizada(tmp_path, referencia) -> None:
    _, catalogos = _raiz(tmp_path)
    ruta = _variante(tmp_path, referencia, "90_antihorario")
    pm.procesar_archivo(ruta, proveedor=OCRSimulado(referencia), carpeta_catalogos=catalogos, proveedor_rutas=object())
    ocr = OCRSimulado(referencia)
    salida = pm.procesar_archivo(ruta, proveedor=ocr, carpeta_catalogos=catalogos, proveedor_rutas=object())
    metricas = json.loads(salida["metricas_procesamiento_json"])["orientacion_documental"]
    assert metricas["reutilizado"] is True and metricas["angulo_correccion"] == 270
    assert set(ocr.vistas["bloques"]) == {0}, "sin lecturas de candidatos: sólo la versión ya derecha"


def test_ruta_operacional_prefiere_la_normalizada_y_cae_al_original(tmp_path, referencia) -> None:
    raiz, catalogos = _raiz(tmp_path)
    girada = _variante(tmp_path, referencia, "180")
    derecha = _variante(tmp_path, referencia, "0")
    for ruta in (girada, derecha):
        pm.procesar_archivo(ruta, proveedor=OCRSimulado(referencia), carpeta_catalogos=catalogos, proveedor_rutas=object())
    operacional = ruta_operacional(raiz, girada)
    assert operacional != girada and OCRSimulado(referencia).giro_real(operacional) == 0
    assert ruta_operacional(raiz, derecha) == derecha


# -------------------------------------------------- PDF basado en imagen

def _jpeg(imagen: Image.Image) -> bytes:
    import io

    salida = io.BytesIO()
    imagen.save(salida, format="JPEG", quality=92)
    return salida.getvalue()


def test_pdf_de_imagenes_normaliza_por_pagina_y_preserva_el_original(tmp_path, referencia, monkeypatch) -> None:
    """PDF armado desde fotos (tipo iLovePDF): página 1 con la foto girada
    90° horario (sin /Rotate, la página misma es apaisada), página 2
    derecha. Sin texto embebido -> ambas van a OCR."""
    monkeypatch.setenv("ATLAS_IA_B1_OPERACIONAL", "0")
    for clave in ("GROQ_API_KEY", "OPENROUTESERVICE_API_KEY"):
        monkeypatch.delenv(clave, raising=False)
    raiz, catalogos = _raiz(tmp_path)
    entrada = tmp_path / "entrada"
    entrada.mkdir()
    pdf = entrada / "guias_escaneadas.pdf"
    pdf.write_bytes(construir_pdf([
        PaginaSintetica(imagen_jpeg=_jpeg(referencia.rotate(270, expand=True)), ancho=ALTO * 0.75, alto=ANCHO * 0.75),
        PaginaSintetica(imagen_jpeg=_jpeg(referencia), ancho=ANCHO * 0.75, alto=ALTO * 0.75),
    ]))
    sha_pdf = _sha(pdf)
    salida_csv = raiz / "operacion" / "actual" / "analisis_completo_guias.csv"
    salida_csv.parent.mkdir(parents=True)
    vistas: list[OCRSimulado] = []

    def procesador(ruta):
        ocr = OCRSimulado(referencia)
        vistas.append(ocr)
        return pm.procesar_archivo(ruta, proveedor=ocr, carpeta_catalogos=catalogos, proveedor_rutas=object())

    pm.procesar_carpeta(entrada, salida_csv, procesador=procesador, cada=1)
    assert _sha(pdf) == sha_pdf, "el PDF original queda intacto"
    assert len(vistas) == 2
    assert all(set(ocr.vistas["texto"]) == {0} for ocr in vistas), "ambas páginas llegan derechas al OCR"

    # La página derivada (PNG técnico del manifiesto) tampoco se toca; la
    # evidencia operacional de la página 1 es su versión normalizada.
    pagina1 = resolver_ruta_evidencia(raiz, "guias_escaneadas.pdf::pagina=0001")
    pagina2 = resolver_ruta_evidencia(raiz, "guias_escaneadas.pdf::pagina=0002")
    assert pagina1.ubicacion == "DERIVADA_PDF" and pagina2.ubicacion == "DERIVADA_PDF"
    directorio = directorio_orientacion_para_raiz(raiz)
    registro1 = leer_registro(directorio, sha256_archivo(pagina1.ruta))
    registro2 = leer_registro(directorio, sha256_archivo(pagina2.ruta))
    assert registro1["resultado"] == CORREGIDA and registro1["rotacion_aplicada_grados_antihorario"] == 90
    assert registro2["resultado"] == SIN_ROTACION
    assert OCRSimulado(referencia).giro_real(ruta_operacional(raiz, pagina1.ruta)) == 0
    assert ruta_operacional(raiz, pagina2.ruta) == pagina2.ruta


# ------------------------------------------------ OCR real (opt-in, manual)

@pytest.mark.skipif(os.environ.get("ATLAS_PRUEBA_OCR_REAL") != "1", reason="OCR real: ATLAS_PRUEBA_OCR_REAL=1")
def test_ocr_real_paddle_cuatro_orientaciones(tmp_path) -> None:
    """Misma prueba con PaddleOCR real sobre una guía sintética con fuente
    TrueType (no corre en CI: requiere el runtime de PaddleOCR)."""
    from atlas_core.ocr_provider import crear_proveedor_ocr

    fuente = ImageFont.truetype("arial.ttf", 30)
    documento = Image.new("RGB", (1240, 1600), "white")
    dibujo = ImageDraw.Draw(documento)
    for indice, linea in enumerate(LINEAS):
        dibujo.text((70, 60 + indice * 110), linea, fill="black", font=fuente)
    proveedor = crear_proveedor_ocr()
    _, catalogos = _raiz(tmp_path)
    textos = {}
    for nombre, (giro, correccion) in VARIANTES.items():
        ruta = tmp_path / f"real_{nombre}.jpg"
        documento.rotate(giro, expand=True).save(ruta, quality=92)
        salida = pm.procesar_archivo(ruta, proveedor=proveedor, carpeta_catalogos=catalogos, proveedor_rutas=object())
        metricas = json.loads(salida["metricas_procesamiento_json"])["orientacion_documental"]
        assert metricas["angulo_correccion"] == correccion, (nombre, metricas)
        textos[nombre] = tuple(salida[c] for c in ("numero_guia", "rut_cliente", "fecha", "cliente", "despachar_a_crudo"))
    assert len(set(textos.values())) == 1, textos
    guia, rut, fecha, _cliente, destino = textos["0"]  # cliente: catálogo vacío en la prueba
    assert all(v not in ("", "No encontrado") for v in (guia, rut, fecha, destino)), textos
