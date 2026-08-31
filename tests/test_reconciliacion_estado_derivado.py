import json
import csv
from datetime import datetime, timezone

from atlas_core.almacenamiento_portable import escribir_estado_operacion, leer_estado_operacion
from atlas_core import reconciliacion_estado_derivado as modulo
from atlas_core.procesamiento_masivo import COLUMNAS


RELOJ = lambda: datetime(2026, 8, 31, 18, 0, tzinfo=timezone.utc)


def _entorno(tmp_path):
    actual = tmp_path / "operacion" / "actual"
    actual.mkdir(parents=True)
    dataset = actual / "analisis_completo_guias.csv"
    dataset.write_text("numero_guia;estado_operacional\n1;REQUIERE_REVISION\n", encoding="utf-8")
    decisiones = actual / "decisiones_pendientes.json"
    decisiones.write_text(json.dumps({"decisiones": [{"decision_id": "d1"}]}), encoding="utf-8")
    reporte = tmp_path / "reportes" / "anterior"
    reporte.mkdir(parents=True)
    escribir_estado_operacion(
        reporte_vigente=reporte, dataset_operacional=dataset,
        decisiones_pendientes=decisiones, raiz=tmp_path, reloj=RELOJ,
    )
    return dataset, decisiones


def test_estado_pre_r2_se_reconcilia_una_vez_sin_ocr_y_con_respaldo(tmp_path, monkeypatch):
    dataset, decisiones = _entorno(tmp_path)
    bytes_decisiones = decisiones.read_bytes()
    llamadas = {"limpieza": 0, "reporte": 0}

    def limpiar(**kwargs):
        llamadas["limpieza"] += 1
        contenido = dataset.read_text(encoding="utf-8").replace("REQUIERE_REVISION", "OK")
        dataset.write_text(contenido, encoding="utf-8")
        return {"guias_actualizadas": ["1"]}

    def reportar(_dataset, salida, **kwargs):
        llamadas["reporte"] += 1
        salida.mkdir(parents=True)
        (salida / "viajes.csv").write_text("estado\nINCOMPLETO_TECNICO\n", encoding="utf-8")
        return {"totales": {"viajes": 1, "viajes_incompletos_tecnicos": 1}}

    monkeypatch.setattr(modulo, "revalidar_motivo_destino_ya_confirmado_sin_ocr", limpiar)
    monkeypatch.setattr(modulo, "generar_reporte_viajes", reportar)

    primero = modulo.reconciliar_estado_derivado(raiz_atlas=tmp_path, reloj=RELOJ)
    segundo = modulo.reconciliar_estado_derivado(raiz_atlas=tmp_path, reloj=RELOJ)

    assert primero["reconciliado"] is True
    assert primero["ocr_ejecutado"] is False
    assert primero["guias_actualizadas"] == ["1"]
    assert segundo == {"reconciliado": False, "motivo": "VERSION_VIGENTE_SIN_REINTENTO_PENDIENTE", "version": 2, "pendientes_tecnicos": 0}
    assert llamadas == {"limpieza": 1, "reporte": 1}
    assert decisiones.read_bytes() == bytes_decisiones
    assert (next((tmp_path / "respaldos").iterdir()) / dataset.name).is_file()
    assert leer_estado_operacion(raiz=tmp_path)["version_estado_derivado"] == 2


def test_fallo_no_publica_version_y_restaura_dataset(tmp_path, monkeypatch):
    dataset, _ = _entorno(tmp_path)
    original = dataset.read_bytes()

    def limpiar(**kwargs):
        dataset.write_text("alterado", encoding="utf-8")
        return {"guias_actualizadas": ["1"]}

    monkeypatch.setattr(modulo, "revalidar_motivo_destino_ya_confirmado_sin_ocr", limpiar)
    monkeypatch.setattr(modulo, "generar_reporte_viajes", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("fallo")))

    import pytest
    with pytest.raises(RuntimeError, match="fallo"):
        modulo.reconciliar_estado_derivado(raiz_atlas=tmp_path, reloj=RELOJ)
    assert dataset.read_bytes() == original
    assert "version_estado_derivado" not in leer_estado_operacion(raiz=tmp_path)


def test_pendiente_tecnico_se_recupera_en_siguiente_oportunidad_sin_decision_humana(tmp_path, monkeypatch):
    actual = tmp_path / "operacion" / "actual"; actual.mkdir(parents=True)
    dataset = actual / "analisis_completo_guias.csv"
    fila = {c: "" for c in COLUMNAS}
    fila.update({
        "archivo": "guia.jpeg", "numero_guia": "99", "numero_transporte": "T99",
        "indicador_revision": "OK", "estado_operacional": "REQUIERE_REVISION",
        "planta_origen_id": "p1", "despachar_a_crudo": "CALLE 123",
        "estado_ruta": "REQUIERE_REVISION", "motivo_ruta": "MULTIPLES_UBICACIONES_DISPERSAS(5)",
        "cliente": "CLIENTE", "obra_destino": "OBRA",
    })
    with dataset.open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader(); escritor.writerow(fila)
    decisiones = actual / "decisiones_pendientes.json"
    decisiones.write_text('{"decisiones": []}', encoding="utf-8")
    (tmp_path / "catalogos_privados").mkdir()
    reporte_anterior = tmp_path / "reportes" / "anterior"; reporte_anterior.mkdir(parents=True)
    escribir_estado_operacion(reporte_vigente=reporte_anterior, dataset_operacional=dataset, decisiones_pendientes=decisiones, raiz=tmp_path, reloj=RELOJ)

    monkeypatch.setattr(modulo, "revalidar_motivo_destino_ya_confirmado_sin_ocr", lambda **k: {"guias_actualizadas": []})
    def recuperar(**kwargs):
        assert kwargs["guias_objetivo"] == {"99"}
        filas = modulo._leer_filas(dataset)
        filas[0].update({"estado_ruta": "RUTA_CALCULADA", "motivo_ruta": "", "distancia_km": "12", "duracion_min": "20", "estado_operacional": "OK"})
        with dataset.open("w", newline="", encoding="utf-8-sig") as archivo:
            escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
            escritor.writeheader(); escritor.writerows(filas)
        return {"guias_actualizadas": ["99"]}
    monkeypatch.setattr(modulo, "revalidar_ruta_sin_destino_calculado_sin_ocr", recuperar)
    def reportar(_dataset, salida, **kwargs):
        salida.mkdir(parents=True); (salida / "viajes.csv").write_text("estado\nCONFIRMADO\n", encoding="utf-8")
        return {"totales": {"viajes": 1, "viajes_confirmados": 1}}
    monkeypatch.setattr(modulo, "generar_reporte_viajes", reportar)

    resultado = modulo.reconciliar_estado_derivado(raiz_atlas=tmp_path, reloj=RELOJ)
    repetido = modulo.reconciliar_estado_derivado(raiz_atlas=tmp_path, reloj=RELOJ)
    assert resultado["guias_recuperadas"] == ["99"]
    assert resultado["pendientes_tecnicos"] == 0
    assert json.loads((actual / "pendientes_tecnicos.json").read_text())["pendientes"] == []
    assert json.loads(decisiones.read_text())["decisiones"] == []
    assert repetido["reconciliado"] is False
