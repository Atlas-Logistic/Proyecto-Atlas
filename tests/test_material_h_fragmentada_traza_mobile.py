"""P0 guía 484553 (envío Mobile leído como "8484553", 11-11-2026).

RapidOCR leyó la partida "B HORMIGON 8MM 12M A630-420H (N)" como
"B1IORMIGON 8MM12MA630-4201(N)": la H partida en dos trazos. El extractor
sólo toleraba deformaciones de igual longitud y el material legible quedó
MATERIAL_AUSENTE. Además Mobile no persistía la traza OCR, así que ninguna
mejora posterior del extractor podía reaplicarse sin OCR nuevo.
"""
from __future__ import annotations

import csv
import json
import uuid
from pathlib import Path

import pytest

from atlas_core import mobile
from atlas_core.mobile import RepositorioEnviosMobile, procesar_envio_mobile
from atlas_core.procesamiento_masivo import COLUMNAS, extraer_descripcion_material
from atlas_core.trazabilidad_ocr import ruta_traza_ocr

# Lectura RapidOCR real del documento (sólo la tabla de productos y su pie;
# sin datos personales del chofer).
LINEAS_REALES_484553 = [
    "GUIA DEDESPACHO", "ELECTRONICA", "N8484553", "FECHA DE EMISION", "11-11-2026",
    "Nro.TRANSPORTE", "0000369979",
    "UNIDAD", "PRECIO", "VALOR", "CANTIDAD", "CODIGO", "DESCRIPCION", "KG", "972,00", "26.737.776",
    "27.508110002847",
    "B1IORMIGON 8MM12MA630-4201(N)",
    "Colada81 2618048602,2618076602,2618076702,26180768",
    "02", "DESPACHO", "FOMANA", "1NOV2026", "EBEMAS.A",
    "Tara:13.470,000 PesoBruto:40.978,000",
    "FECHA", "MOTIVO", "TIPODEDOCUMENTO", "FOLIO",
    "VALORTOTAL:26.737.776", "C5-12.00", "PESOKG.", "27.508,00",
]
# Relectura focal real de la región DESCRIPCION del mismo documento.
LINEAS_FOCALES_484553 = [
    ["D 1IORMIGON 8MM 12M AG30-420I (N)", "Co1ada71 2618048602.2618076602,2618076702,26", "02"],
    ["B 1IORMIGON 8MM 12M AG30-420II (N)", "Co1ada81 2618048602.2618076602,2618076702,26", "02"],
]


def test_lectura_real_484553_recupera_la_partida_tal_como_la_leyo_el_ocr():
    assert extraer_descripcion_material(LINEAS_REALES_484553) == "B HORMIGON 8MM12MA630-4201(N)"


@pytest.mark.parametrize(("lineas", "esperado"), [
    (LINEAS_FOCALES_484553[0], "B HORMIGON 8MM 12M AG30-420I (N)"),
    (LINEAS_FOCALES_484553[1], "B HORMIGON 8MM 12M AG30-420II (N)"),
    (["1IORMIGON 12MM 6M A630-420H (N)"], "HORMIGON 12MM 6M A630-420H (N)"),
    (["3 lIORMIGON 22 MM 6M A630-420H"], "B HORMIGON 22 MM 6M A630-420H"),
    (["B|IORMIGON 10MM 12M A630-420H (N)"], "B HORMIGON 10MM 12M A630-420H (N)"),
])
def test_h_partida_con_diametro_se_reconoce(lineas, esperado):
    assert extraer_descripcion_material(lineas) == esperado


@pytest.mark.parametrize("linea", [
    # Sin diámetro inmediatamente después: no hay contexto de producto.
    "B1IORMIGON",
    "B1IORMIGON A630-420H (N)",
    "TRANSPORTE 1IORMIGON",
    "1IORMIGON COLINA 8",
    # Otra letra delante de los trazos: no es la designación de barra.
    "X1IORMIGON 8MM 12M",
    "TRANSPORTES1IORMIGON 8MM",
    # Un solo trazo o tres: no es la H partida de esta regla.
    "B1ORMIGON 8MM 12M",
    "B11IORMIGON 8MM 12M",
    # Trazos separados de ORMIGON o palabra más larga.
    "B 1I ORMIGON 8MM 12M",
    "B1IORMIGONES 8MM 12M",
    # MM seguido de letra no es un diámetro.
    "B1IORMIGON 8MMX",
])
def test_sin_contexto_suficiente_no_se_inventa_material(linea):
    assert extraer_descripcion_material([linea]) == ""


def test_h_partida_despues_del_pie_de_tabla_no_cuenta():
    lineas = ["DESCRIPCION", "Tara:1.000 PesoBruto:2.000", "VALORTOTAL:1.000", "B1IORMIGON 8MM 12M A630-420H"]
    assert extraer_descripcion_material(lineas) == ""


def test_lecturas_ya_correctas_no_cambian():
    linea = "BHORMIGON 8MM 12M A630-420H (N)"
    assert extraer_descripcion_material([linea]) == "B HORMIGON 8MM 12M A630-420H (N)"


@pytest.mark.parametrize("linea", [
    # 483407 y 488100: fallos de OTRA forma (diámetro "18M" de una sola M;
    # CHATARRA pegada a la palabra siguiente). Fuera del alcance de esta
    # regla: siguen ausentes y no se tocan aquí.
    "3HORMIGON18M12M A630-420H (N)",
    "CHATARRACPESADAPARA PROCESAR",
])
def test_otras_deformaciones_quedan_fuera_de_esta_regla(linea):
    assert extraer_descripcion_material([linea]) == ""


# --- Traza OCR Mobile -------------------------------------------------------

class _ProveedorReal484553:
    """Doble del OCR: entrega la lectura real; sin geometría."""

    def leer_texto(self, _ruta):
        return list(LINEAS_REALES_484553)

    def leer_bloques(self, _ruta):
        return []

    def leer_focal(self, _ruta, _caja, allowlist=""):
        return {}


def _preparar(tmp_path: Path):
    repo = RepositorioEnviosMobile(tmp_path / "operacion" / "mobile" / "envios")
    envio_id = str(uuid.uuid4())
    repo.recibir(
        envio_id=envio_id, imagen=b"foto-original-484553", mime="image/jpeg",
        metadata={"chofer_id": "c1", "tipo_novedad": "", "guia_firmada_correo": False,
                  "planta_origen_informada": "AZA_COLINA"},
    )
    dataset = tmp_path / "operacion" / "actual" / "analisis_completo_guias.csv"
    dataset.parent.mkdir(parents=True)
    with dataset.open("w", newline="", encoding="utf-8-sig") as archivo:
        csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";").writeheader()
    return repo, envio_id, dataset


def _filas(dataset: Path) -> list[dict[str, str]]:
    with dataset.open(encoding="utf-8-sig", newline="") as archivo:
        return list(csv.DictReader(archivo, delimiter=";"))


def test_envio_mobile_persiste_traza_ocr_en_operacion_trazas_ocr(tmp_path):
    repo, envio_id, dataset = _preparar(tmp_path)
    foto = repo.cargar(envio_id)["foto_original"]
    identificador = f"mobile/{envio_id}/{foto}"

    procesar_envio_mobile(repo, envio_id, dataset=dataset, proveedor_ocr=_ProveedorReal484553())

    directorio = tmp_path / "operacion" / "trazas_ocr"
    ruta = ruta_traza_ocr(directorio, identificador)
    assert ruta.is_file()
    # Una sola traza, nombrada por el identificador lógico (todas las fotos
    # Mobile se llaman igual): dos envíos nunca comparten archivo.
    assert [p.name for p in directorio.glob("*.json")] == [ruta.name]
    assert ruta_traza_ocr(directorio, f"mobile/{uuid.uuid4()}/{foto}") != ruta
    texto = ruta.read_text(encoding="utf-8")
    traza = json.loads(texto)
    assert traza["imagen"]["referencia"] == identificador
    assert traza["ocr"]["lineas"] == LINEAS_REALES_484553
    # Sin rutas locales ni bytes de la imagen; la foto no se duplica.
    assert str(tmp_path) not in texto and str(tmp_path).replace("\\", "/") not in texto
    assert "foto-original-484553" not in texto
    assert not [p for p in tmp_path.rglob("*") if p.is_file() and p.name == foto and "envios" not in p.parts]
    fila = next(f for f in _filas(dataset) if f["archivo"] == identificador)
    assert fila["descripcion_material"] == "B HORMIGON 8MM12MA630-4201(N)"


def test_sin_dataset_mobile_no_escribe_traza(tmp_path):
    assert mobile._argumentos_traza_ocr_mobile(None, "mobile/x/original.jpg") == {}


def test_reproceso_persistido_tambien_conserva_traza(tmp_path, monkeypatch):
    repo, envio_id, dataset = _preparar(tmp_path)
    vistos = []

    def procesar(ruta, **kwargs):
        vistos.append(kwargs)
        raise RuntimeError("detener tras capturar argumentos")

    procesar_envio_mobile(repo, envio_id, dataset=dataset, proveedor_ocr=_ProveedorReal484553())
    monkeypatch.setattr(mobile, "crear_proveedor_ocr", lambda: _ProveedorReal484553())
    monkeypatch.setattr(mobile, "procesar_archivo", procesar)
    filas_antes = _filas(dataset)
    try:
        mobile.reprocesar_envio_mobile_persistido(repo, envio_id, dataset=dataset)
    except Exception:
        pass  # el reproceso restaura el envío ante un fallo: sólo importan los argumentos
    assert _filas(dataset) == filas_antes
    foto = repo.cargar(envio_id)["foto_original"]
    assert vistos and vistos[0]["directorio_trazas_ocr"] == tmp_path / "operacion" / "trazas_ocr"
    assert vistos[0]["referencia_imagen_traza"] == f"mobile/{envio_id}/{foto}"


def test_traza_mobile_permite_reextraer_material_sin_ocr(tmp_path):
    """Fila MATERIAL_AUSENTE con traza Mobile persistida: el recuperador por
    traza (sin OCR) completa sólo material, tipo de carga y el motivo."""
    from atlas_core.revalidacion_documental import recuperar_material_ausente_desde_traza_ocr_sin_ocr
    from atlas_core.trazabilidad_ocr import persistir_traza_ocr

    identificador = f"mobile/{uuid.uuid4()}/original.jpg"
    dataset = tmp_path / "operacion" / "actual" / "analisis_completo_guias.csv"
    dataset.parent.mkdir(parents=True)
    fila = {c: "" for c in COLUMNAS}
    fila.update(
        archivo=identificador, numero_guia="8484553", numero_transporte="0000369979", fecha="11-11-2026",
        hora_entrada_aza="No encontrado", tipo_carga="NO DETERMINADO", estado_ruta="ORIGEN_NO_DETERMINADO",
        motivo_ruta="CONTRADICCION_OPERACIONAL_ORIGEN", motivos_revision_documento="MATERIAL_AUSENTE",
        indicador_revision="OK", estado_documental="OK", estado_operacional="REQUIERE_REVISION",
    )
    otra = dict(fila, archivo="otra.jpeg", numero_guia="111111")
    with dataset.open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader()
        escritor.writerows([fila, otra])
    persistir_traza_ocr(
        directorio=tmp_path / "operacion" / "trazas_ocr", referencia_imagen=identificador,
        textos=LINEAS_REALES_484553, bloques=None,
    )
    antes = {f["archivo"]: f for f in _filas(dataset)}

    resultado = recuperar_material_ausente_desde_traza_ocr_sin_ocr(raiz_atlas=tmp_path)

    despues = {f["archivo"]: f for f in _filas(dataset)}
    assert resultado["guias_actualizadas"] == ["8484553"]
    assert despues["otra.jpeg"] == antes["otra.jpeg"]
    cambios = {k for k in COLUMNAS if despues[identificador][k] != antes[identificador][k]}
    assert despues[identificador]["descripcion_material"] == "B HORMIGON 8MM12MA630-4201(N)"
    assert despues[identificador]["tipo_carga"] == "BARRAS"
    assert despues[identificador]["motivos_revision_documento"] == ""
    # Folio, fecha, horas, ruta y estado operacional intactos.
    assert cambios <= {
        "descripcion_material", "tipo_carga", "motivos_revision_documento",
        "indicador_revision", "estado_documental", "metricas_procesamiento_json",
    }
