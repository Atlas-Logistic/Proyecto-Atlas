"""Material descartado con OCR utilizable (22 guías "sin material",
02-10-2026). Líneas OCR reales de las trazas de esas guías:
productos fuera del vocabulario (SAFEROCK/CHATARRA/HEXAGONO), HORMIGON
leído con dígitos (HORMIG0N) y lecturas muy deformadas en las que sólo la
familia es sostenible (nunca se reconstruyen diámetro/largo/calidad)."""
import csv
import json

import pytest

from atlas_core.procesamiento_masivo import COLUMNAS, extraer_descripcion_material
from atlas_core.revalidacion_documental import recuperar_material_ausente_desde_traza_ocr_sin_ocr
from atlas_core.trazabilidad_ocr import persistir_traza_ocr

ILEGIBLE = "(DETALLE ILEGIBLE EN OCR)"


@pytest.mark.parametrize("lineas, esperado", [
    # 460486 / 477043: productos reales fuera del vocabulario, OCR limpio.
    (["DESCRIPCION", "SAFEROCK 25MM 12M A420", "Coladas:2617651803,2617652202"], "SAFEROCK 25MM 12M A420"),
    (["DESCRIPCION", "CHATARRA C PESADA PARA PROCESAR", "KG"], "CHATARRA C PESADA PARA PROCESAR"),
    # 473263 / 474708: sólo el dígito de la palabra de familia se lee como letra.
    (["0 HORMIG0N 16MM 12M A630-420H (N)", "Coladas: 2617881103"], "0 HORMIGON 16MM 12M A630-420H (N)"),
    (["à HORMIG0N 10MM 12M A630-420m (N)"], "à HORMIGON 10MM 12M A630-420m (N)"),
])
def test_lecturas_fieles_conservan_la_linea_ocr(lineas, esperado):
    assert extraer_descripcion_material(lineas) == esperado


@pytest.mark.parametrize("linea, familia", [
    ("B HOMMI0ON 10NM 12M A630-420H (N)", "HORMIGON"),          # 475040
    ("MOPMIGON 28MH 12M A630-à708 (N)", "HORMIGON"),            # 474988
    ("HORKIGON Ak Coladas : 1630-4204 2617892102", "HORMIGON"),  # 473424
    ("B HORM190H 12994 644 A630-4298 (99)", "HORMIGON"),         # 472710
    ("HORKIGOK ZzMM 7X: R630 12041 Coladas: 2617818102", "HORMIGON"),  # 473326
    ("EORYIGOX 124 12k R630 4205 50,8085 261705802", "HORMIGON"),      # 473412
    ("HEKAGONO 1 1/R** 1,6H SAE 1045 (N)", "HEXAGONO"),          # 480715
    ("REXAGONO 1** 1, GM SAE 1045 (N)", "HEXAGONO"),             # 480715
])
def test_lectura_deformada_registra_solo_la_familia(linea, familia):
    resultado = extraer_descripcion_material([linea])
    assert resultado == f"{familia} {ILEGIBLE}"
    # Nunca se reconstruyen atributos que el OCR no sostiene.
    assert "MM" not in resultado and "A630" not in resultado and "SAE" not in resultado


def test_dos_lecturas_deformadas_del_mismo_documento_no_duplican_familia():
    lineas = ["HEKAGONO 1 1/R** 1,6H SAE 1045 (N)", "REXAGONO 1** 1, GM SAE 1045 (N)"]
    assert extraer_descripcion_material(lineas) == f"HEXAGONO {ILEGIBLE}"


@pytest.mark.parametrize("lineas", [
    # Palabra parecida sin contexto siderúrgico en la línea: no es evidencia.
    ["HORKIGOK SAN BERNARDO"],
    # Contexto siderúrgico pero sin palabra de familia reconocible (473481, grupo B).
    ["ALN 60 AA 1006 (N)", "Coladan: 2617837702,2617837802"],
    # Sello operacional con término de material: sigue descartado.
    ["C6 10.08 12PM/BARRAS CYD"],
])
def test_sin_evidencia_suficiente_no_inventa_material(lineas):
    assert extraer_descripcion_material(lineas) == ""


def test_lecturas_ya_aceptadas_no_cambian():
    lineas = ["B HORMIGON 12MM 12M A630-420H (N)", "B BORHIGON 22MM 12M A630-420H (N)"]
    assert extraer_descripcion_material(lineas) == " | ".join(lineas)


# --------------------------------------------------- reproceso histórico sin OCR

def _fila(**cambios):
    fila = {campo: "" for campo in COLUMNAS}
    fila.update({
        "archivo": "lote/a.jpeg", "numero_guia": "1", "numero_transporte": "0000000001",
        "cliente": "CLIENTE A", "descripcion_material": "", "tipo_carga": "NO DETERMINADO",
        "motivos_revision_documento": "MATERIAL_AUSENTE", "estado_ruta": "RUTA_CALCULADA",
        "metricas_procesamiento_json": "{}",
    })
    fila.update(cambios)
    return fila


def _raiz(tmp_path, filas, trazas):
    actual = tmp_path / "operacion" / "actual"
    actual.mkdir(parents=True)
    ruta = actual / "analisis_completo_guias.csv"
    with ruta.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNAS, delimiter=";")
        w.writeheader()
        w.writerows(filas)
    for archivo, lineas in trazas.items():
        persistir_traza_ocr(directorio=tmp_path / "operacion" / "trazas_ocr", referencia_imagen=archivo,
                            textos=lineas, bloques=[])
    return ruta


def _leer(ruta):
    with ruta.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f, delimiter=";"))


def test_reproceso_desde_traza_recupera_material_sin_tocar_otros_campos(tmp_path):
    ruta = _raiz(tmp_path, [_fila()], {"lote/a.jpeg": ["0 HORMIG0N 16MM 12M A630-420H (N)", "Coladas: 1"]})
    resultado = recuperar_material_ausente_desde_traza_ocr_sin_ocr(raiz_atlas=tmp_path)
    fila = _leer(ruta)[0]
    assert resultado["guias_actualizadas"] == ["1"]
    assert fila["descripcion_material"] == "0 HORMIGON 16MM 12M A630-420H (N)"
    assert fila["tipo_carga"] == "BARRAS"
    assert "MATERIAL_AUSENTE" not in fila["motivos_revision_documento"]
    assert fila["cliente"] == "CLIENTE A" and fila["numero_transporte"] == "0000000001"
    traza = json.loads(fila["metricas_procesamiento_json"])["recuperacion_p0"]["material_traza"]
    assert traza["resultado"] == "RECUPERADO"
    # Idempotente: un segundo ciclo no vuelve a revisar la fila.
    assert recuperar_material_ausente_desde_traza_ocr_sin_ocr(raiz_atlas=tmp_path)["revisadas"] == 0


def test_reproceso_respeta_decision_humana_y_material_existente(tmp_path):
    ruta = _raiz(tmp_path, [
        _fila(),
        _fila(archivo="lote/b.jpeg", numero_guia="2", descripcion_material="BARRA LISA"),
    ], {
        "lote/a.jpeg": ["SAFEROCK 25MM 12M A420"],
        "lote/b.jpeg": ["SAFEROCK 25MM 12M A420"],
    })
    (tmp_path / "operacion" / "actual" / "decisiones_aplicadas.json").write_text(json.dumps({"aplicaciones": [{
        "campo": "descripcion_material", "documento": {"archivo": "lote/a.jpeg", "numero_guia": "1"},
    }]}), encoding="utf-8")
    resultado = recuperar_material_ausente_desde_traza_ocr_sin_ocr(raiz_atlas=tmp_path)
    uno, dos = _leer(ruta)
    assert resultado["guias_actualizadas"] == []
    assert uno["descripcion_material"] == "" and "MATERIAL_AUSENTE" in uno["motivos_revision_documento"]
    assert dos["descripcion_material"] == "BARRA LISA"


def test_reproceso_sin_evidencia_conserva_ausencia(tmp_path):
    ruta = _raiz(tmp_path, [_fila()], {"lote/a.jpeg": ["ALN 60 AA 1006 (N)"]})
    resultado = recuperar_material_ausente_desde_traza_ocr_sin_ocr(raiz_atlas=tmp_path)
    fila = _leer(ruta)[0]
    assert resultado["guias_actualizadas"] == []
    assert fila["descripcion_material"] == "" and fila["motivos_revision_documento"] == "MATERIAL_AUSENTE"
    assert json.loads(fila["metricas_procesamiento_json"])["recuperacion_p0"]["material_traza"]["resultado"] == "ABSTENCION"


# ----------------------------------- relectura focal de imagen (grupo B)

def _raiz_con_imagen(tmp_path, filas):
    from PIL import Image

    ruta = _raiz(tmp_path, filas, {})
    entradas = tmp_path / "operacion" / "entradas" / "20261002_120000" / "lote"
    entradas.mkdir(parents=True)
    Image.new("RGB", (4, 4), color="white").save(entradas / "a.jpeg")
    return ruta


class _ProveedorIngesta:
    def __init__(self, lineas):
        self.lineas, self.llamadas = lineas, 0

    def leer_texto(self, ruta):
        self.llamadas += 1
        return list(self.lineas)


def test_relectura_focal_usa_ocr_de_ingesta_y_archiva_traza_previa(tmp_path, monkeypatch):
    from atlas_core.revalidacion_documental import reprocesar_material_focal_desde_imagen_original
    from atlas_core.trazabilidad_ocr import ruta_traza_ocr

    ruta = _raiz_con_imagen(tmp_path, [_fila()])
    trazas = tmp_path / "operacion" / "trazas_ocr"
    persistir_traza_ocr(directorio=trazas, referencia_imagen="lote/a.jpeg", textos=["ALN 60 AA 1006 (N)"], bloques=[])
    proveedor = _ProveedorIngesta(["DESCRIPCION", "3 HORMIG0N 25MM 7M A630-420B (N)", "Coladas: 2617667002"])
    monkeypatch.setattr("atlas_core.ocr_provider.crear_proveedor_ocr", lambda *a, **k: proveedor)
    monkeypatch.setattr("atlas_core.ocr.leer_texto_imagen", lambda *a, **k: pytest.fail("no debe usar EasyOCR"))

    resultado = reprocesar_material_focal_desde_imagen_original(raiz_atlas=tmp_path, numero_guia="1")
    assert resultado["aplicado"] is True
    assert _leer(ruta)[0]["descripcion_material"] == "B HORMIGON 25MM 7M A630-420B (N)"
    vigente = json.loads(ruta_traza_ocr(trazas, "lote/a.jpeg").read_text(encoding="utf-8"))
    assert "3 HORMIG0N 25MM 7M A630-420B (N)" in vigente["ocr"]["lineas"]
    archivadas = list((trazas / "historico").glob("*.json"))
    assert len(archivadas) == 1
    assert json.loads(archivadas[0].read_text(encoding="utf-8"))["ocr"]["lineas"] == ["ALN 60 AA 1006 (N)"]


def test_reintento_focal_una_vez_por_avance_de_capacidad(tmp_path, monkeypatch):
    from atlas_core.capacidades_reevaluacion import versiones_actuales
    from atlas_core.revalidacion_documental import recuperar_material_ausente_focal_controlado

    previa = {"recuperacion_p0": {"material_focal": {"version": 1, "resultado": "MATERIAL_NO_RECUPERABLE_TRAS_REPROCESO"}}}
    ruta = _raiz_con_imagen(tmp_path, [_fila(metricas_procesamiento_json=json.dumps(previa))])
    proveedor = _ProveedorIngesta(["GUIA DE DESPACHO"])  # la imagen sigue sin línea de producto
    monkeypatch.setattr("atlas_core.ocr_provider.crear_proveedor_ocr", lambda *a, **k: proveedor)

    primero = recuperar_material_ausente_focal_controlado(raiz_atlas=tmp_path)
    segundo = recuperar_material_ausente_focal_controlado(raiz_atlas=tmp_path)
    assert (primero["intentados"], segundo["intentados"], proveedor.llamadas) == (1, 0, 1)
    nota = json.loads(_leer(ruta)[0]["metricas_procesamiento_json"])["recuperacion_p0"]["material_focal"]
    assert nota["capacidad_material"] == versiones_actuales()["MATERIAL"]
    assert _leer(ruta)[0]["descripcion_material"] == ""
