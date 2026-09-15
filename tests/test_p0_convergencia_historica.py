import csv
import json

from atlas_core.ocr import BloqueOCR
from atlas_core.procesamiento_masivo import COLUMNAS
from atlas_core.revalidacion_documental import (
    recuperar_material_ausente_focal_controlado,
    recuperar_pendientes_desde_replay_traza_ocr_sin_ocr,
    revalidar_tipo_carga_sin_ocr,
)
from atlas_core.trazabilidad_ocr import persistir_traza_ocr


def _fila(**cambios):
    fila = {campo: "" for campo in COLUMNAS}
    fila.update({
        "archivo": "lote/a.jpeg", "numero_guia": "", "numero_transporte": "0000000001",
        "cliente": "", "obra_destino": "", "despachar_a_crudo": "",
        "descripcion_material": "", "tipo_carga": "", "metricas_procesamiento_json": "{}",
    })
    fila.update(cambios)
    return fila


def _dataset(raiz, filas):
    actual = raiz / "operacion" / "actual"
    actual.mkdir(parents=True)
    ruta = actual / "analisis_completo_guias.csv"
    with ruta.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNAS, delimiter=";")
        w.writeheader(); w.writerows(filas)
    return ruta


def _bloque(texto, x, y, ancho=90, alto=20):
    return BloqueOCR(texto, ((x, y), (x + ancho, y), (x + ancho, y + alto), (x, y + alto)), .95)


def _leer(ruta):
    with ruta.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f, delimiter=";"))


def test_tipo_carga_historico_se_resincroniza_y_valido_no_degrada(tmp_path):
    ruta = _dataset(tmp_path, [
        _fila(numero_guia="1", descripcion_material="ANGULO 25X25X3MM", tipo_carga="NO DETERMINADO"),
        _fila(numero_guia="2", descripcion_material="ANGULO 25X25X3MM", tipo_carga="ANGULOS"),
    ])
    resultado = revalidar_tipo_carga_sin_ocr(ruta_dataset=ruta)
    filas = _leer(ruta)
    assert resultado["guias_actualizadas"] == ["1"]
    assert filas[0]["tipo_carga"] == "ANGULOS"
    assert filas[1]["tipo_carga"] == "ANGULOS"


def test_replay_productivo_recupera_ausencias_y_no_repite(tmp_path):
    ruta = _dataset(tmp_path, [_fila()])
    trazas = tmp_path / "operacion" / "trazas_ocr"
    bloques = [
        _bloque("GUIA DE DESPACHO", 570, 272), _bloque("N? 464453", 622, 334),
        _bloque("SEÑOR(ES)", 114, 348), _bloque("AGF ACEROS", 260, 375),
        _bloque("DE", 356, 381), _bloque("CHILE", 384, 381), _bloque("SPA", 436, 385),
        _bloque("OBRA DESTINO", 648, 438), _bloque("CONSTRUCTORA", 829, 436),
        _bloque("IGNACIO", 947, 439), _bloque("HURTADO", 1017, 439),
    ]
    persistir_traza_ocr(directorio=trazas, referencia_imagen="lote/a.jpeg", textos=[b.texto for b in bloques], bloques=bloques)
    primero = recuperar_pendientes_desde_replay_traza_ocr_sin_ocr(raiz_atlas=tmp_path)
    fila = _leer(ruta)[0]
    assert primero["guias_actualizadas"] == ["464453"]
    assert fila["numero_guia"] == "464453"
    assert fila["cliente"] == "AGF ACEROS DE CHILE SPA"
    assert fila["obra_destino"] == "CONSTRUCTORA IGNACIO HURTADO"
    assert json.loads(fila["metricas_procesamiento_json"])["recuperacion_p0"]["replay"]["resultado"] == "APLICADO"
    assert recuperar_pendientes_desde_replay_traza_ocr_sin_ocr(raiz_atlas=tmp_path)["revisadas"] == 0


def test_replay_se_abstiene_y_decision_humana_tiene_precedencia(tmp_path):
    ruta = _dataset(tmp_path, [_fila(numero_guia="99")])
    trazas = tmp_path / "operacion" / "trazas_ocr"
    # Sólo contiene guía; no hay evidencia geométrica para cliente/obra/destino.
    persistir_traza_ocr(directorio=trazas, referencia_imagen="lote/a.jpeg", textos=["GUIA DE DESPACHO"], bloques=[_bloque("GUIA DE DESPACHO", 570, 272)])
    actual = tmp_path / "operacion" / "actual"
    (actual / "decisiones_aplicadas.json").write_text(json.dumps({"aplicaciones": [{
        "campo": "cliente", "documento": {"archivo": "lote/a.jpeg", "numero_guia": "99"},
    }]}), encoding="utf-8")
    resultado = recuperar_pendientes_desde_replay_traza_ocr_sin_ocr(raiz_atlas=tmp_path)
    fila = _leer(ruta)[0]
    assert resultado["abstenciones"] == 1
    assert fila["cliente"] == ""
    assert json.loads(fila["metricas_procesamiento_json"])["recuperacion_p0"]["replay"]["resultado"] == "ABSTENCION"


def test_material_focal_controlado_no_sobrescribe_y_no_repite(tmp_path, monkeypatch):
    ruta = _dataset(tmp_path, [
        _fila(numero_guia="1", descripcion_material="No encontrado", motivos_revision_documento="MATERIAL_AUSENTE"),
        _fila(numero_guia="2", descripcion_material="BARRA LISA", tipo_carga="BARRAS", motivos_revision_documento="MATERIAL_AUSENTE"),
    ])
    entrada = tmp_path / "operacion" / "entradas" / "lote"
    entrada.mkdir(parents=True)
    (entrada / "lote").mkdir()
    (entrada / "lote" / "a.jpeg").write_bytes(b"imagen")
    llamadas = []

    def focal(*, raiz_atlas, numero_guia):
        llamadas.append(numero_guia)
        filas = _leer(ruta)
        fila = next(f for f in filas if f["numero_guia"] == numero_guia)
        fila["descripcion_material"] = "ANGULO 25X25X3MM"
        fila["tipo_carga"] = "NO DETERMINADO"
        with ruta.open("w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=COLUMNAS, delimiter=";"); w.writeheader(); w.writerows(filas)
        return {"aplicado": True}

    monkeypatch.setattr("atlas_core.revalidacion_documental.reprocesar_material_focal_desde_imagen_original", focal)
    primero = recuperar_material_ausente_focal_controlado(raiz_atlas=tmp_path)
    fila_uno, fila_dos = _leer(ruta)
    assert llamadas == ["1"]
    assert primero["recuperados"] == ["1"]
    assert fila_uno["tipo_carga"] == "ANGULOS"
    assert fila_dos["descripcion_material"] == "BARRA LISA"
    assert recuperar_material_ausente_focal_controlado(raiz_atlas=tmp_path)["intentados"] == 0
