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
