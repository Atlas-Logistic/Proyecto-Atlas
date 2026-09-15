"""PERFIL FOCAL DE LATENCIA -- métricas de duración por etapa.

Caso real: "Actualizando operación" tardaba ~70s en Desktop sin que
ningún log dijera dónde. Estos tests verifican que
`reconciliar_estado_derivado` expone `tiempos_ms`/`duracion_bateria_
completa_ms` (instrumentación pura, `time.perf_counter`, nunca decide
nada) y que `reevaluacion_retroactiva.duracion_ms` ya NO se atribuye por
error el costo de toda la batería (bug de medición corregido -- antes
medía desde antes de la batería, ahora sólo mide su propia comparación
antes/después)."""
import json
import time
from datetime import datetime, timezone

from atlas_core.almacenamiento_portable import escribir_estado_operacion
from atlas_core import reconciliacion_estado_derivado as modulo

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


def _stub_bateria(monkeypatch, dataset, *, demora_motivo_s: float = 0.0):
    def limpiar(**kwargs):
        if demora_motivo_s:
            time.sleep(demora_motivo_s)
        contenido = dataset.read_text(encoding="utf-8").replace("REQUIERE_REVISION", "OK")
        dataset.write_text(contenido, encoding="utf-8")
        return {"guias_actualizadas": ["1"]}

    def reportar(_dataset, salida, **kwargs):
        salida.mkdir(parents=True)
        (salida / "viajes.csv").write_text("estado\nINCOMPLETO_TECNICO\n", encoding="utf-8")
        return {"totales": {"viajes": 1, "viajes_incompletos_tecnicos": 1}}

    monkeypatch.setattr(modulo, "revalidar_motivo_destino_ya_confirmado_sin_ocr", limpiar)
    monkeypatch.setattr(modulo, "revalidar_material_estampado_persistido_sin_ocr", lambda **k: {"guias_actualizadas": []})
    monkeypatch.setattr(modulo, "revalidar_destino_contra_comuna_documental_sin_ocr", lambda **k: {"guias_actualizadas": []})
    monkeypatch.setattr(modulo, "revalidar_obra_destino_sin_ocr", lambda **k: {"guias_actualizadas": []})
    monkeypatch.setattr(modulo, "reconciliar_decisiones_destino_no_resuelto", lambda **k: {"decisiones_candidatas": 0, "decisiones_publicadas": 0, "bandeja": {"decisiones": []}})
    monkeypatch.setattr(modulo, "revalidar_origen_encabezado_no_confiable_sin_ocr", lambda **k: {"guias_actualizadas": []})
    monkeypatch.setattr(modulo, "revalidar_origen_por_categoria_sin_candidato_sin_ocr", lambda **k: {"guias_actualizadas": []})
    monkeypatch.setattr(modulo, "revalidar_ruta_con_destino_confirmado_en_catalogo_sin_ocr", lambda **k: {"guias_actualizadas": [], "guias_contradiccion": []})
    monkeypatch.setattr(modulo, "reconciliar_incidencias_rut_chofer_documental", lambda **k: {"candidatas": 0, "incidencias_registradas": [], "rut_corregido_en_dataset": []})
    monkeypatch.setattr(modulo, "revalidar_indicadores_documentales_sin_ocr", lambda **k: {"guias_actualizadas": []})
    monkeypatch.setattr(modulo, "revalidar_asociacion_mobile_sin_ocr", lambda *a, **k: {"revisados": 0, "actualizados": []})
    monkeypatch.setattr(modulo, "reconciliar_bandeja_decisiones", lambda **k: {"decisiones_aplicadas_automaticamente": []})
    monkeypatch.setattr(modulo, "generar_reporte_viajes", reportar)


def test_tiempos_ms_expone_desglose_por_etapa(tmp_path, monkeypatch):
    dataset, _ = _entorno(tmp_path)
    _stub_bateria(monkeypatch, dataset)

    resultado = modulo.reconciliar_estado_derivado(raiz_atlas=tmp_path, reloj=RELOJ)

    assert resultado["reconciliado"] is True
    assert "tiempos_ms" in resultado
    assert "duracion_bateria_completa_ms" in resultado
    # Cada etapa mide un tramo real (nunca negativo); el total de la
    # batería es al menos tan grande como la suma de tramos medidos
    # (puede haber overhead de I/O propio entre marcas).
    for nombre, ms in resultado["tiempos_ms"].items():
        assert ms >= 0, f"{nombre} no puede ser negativo"
    assert resultado["duracion_bateria_completa_ms"] >= sum(resultado["tiempos_ms"].values()) - 1
    # Etapas nombradas que el perfilado focal identificó como las más
    # costosas en producción deben estar presentes para que una futura
    # regresión sea visible por nombre, no sólo por el total.
    for etapa_esperada in (
        "limpieza_motivos_destino_obra_material_fecha",
        "destino_ruta_y_geocoding",
        "bandeja_decisiones_evidencia",
        "segunda_pasada_universal_sin_ocr",
        "destino_no_resuelto",
    ):
        assert etapa_esperada in resultado["tiempos_ms"]


def test_reevaluacion_retroactiva_ya_no_se_atribuye_el_costo_de_la_bateria(tmp_path, monkeypatch):
    """Bug de medición corregido: antes, `reevaluacion_retroactiva.
    duracion_ms` medía desde ANTES de correr toda la batería de
    revalidadores hasta después de `reconciliar_decisiones_destino_no_
    resuelto` -- un run real con 9 viajes y CERO capacidades avanzadas
    reportaba ~33s bajo esa etiqueta, escondiendo que el costo real
    estaba en la batería, no en la comparación retroactiva. Se
    verifica inyectando una demora artificial y deliberada en UNA
    revalidación de la batería (`revalidar_motivo_destino_ya_
    confirmado_sin_ocr`) y confirmando que esa demora aparece en
    `tiempos_ms`/`duracion_bateria_completa_ms`, NUNCA en
    `reevaluacion_retroactiva.duracion_ms` (que debe seguir siendo
    minúsculo -- sólo compara dos snapshots ya en memoria)."""
    dataset, _ = _entorno(tmp_path)
    DEMORA_S = 0.25
    _stub_bateria(monkeypatch, dataset, demora_motivo_s=DEMORA_S)

    resultado = modulo.reconciliar_estado_derivado(raiz_atlas=tmp_path, reloj=RELOJ)

    duracion_reeval_ms = resultado["reevaluacion_retroactiva"]["duracion_ms"]
    assert duracion_reeval_ms < (DEMORA_S * 1000) / 2, (
        "la demora artificial de la batería se filtró a la métrica de "
        "reevaluación retroactiva -- el bug de atribución volvió"
    )
    assert resultado["duracion_bateria_completa_ms"] >= DEMORA_S * 1000
