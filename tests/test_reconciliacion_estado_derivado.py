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


def test_fallo_no_publica_version_pero_nunca_revierte_cambios_del_dataset_ya_aplicados(tmp_path, monkeypatch):
    """Fase 2 -- Regla absoluta: el dataset NUNCA se restaura por
    snapshot completo. El cambio que dejó `revalidar_motivo_destino_ya_
    confirmado_sin_ocr` (una revalidación canónica, ya atómica) se
    conserva intacto aunque la generación del reporte falle después --
    sólo la publicación de una nueva versión/estado_operación se
    aborta."""
    dataset, _ = _entorno(tmp_path)

    def limpiar(**kwargs):
        dataset.write_text("alterado", encoding="utf-8")
        return {"guias_actualizadas": ["1"]}

    monkeypatch.setattr(modulo, "revalidar_motivo_destino_ya_confirmado_sin_ocr", limpiar)
    monkeypatch.setattr(modulo, "generar_reporte_viajes", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("fallo")))

    import pytest
    with pytest.raises(RuntimeError, match="fallo"):
        modulo.reconciliar_estado_derivado(raiz_atlas=tmp_path, reloj=RELOJ)
    assert dataset.read_text(encoding="utf-8") == "alterado"
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


def test_a_reconciliacion_vs_otro_escritor_real_concurrente_no_pierde_cambio_ajeno(tmp_path, monkeypatch):
    """Fase 2, criterio A: `reconciliar_estado_derivado` (fase de
    migración, que llama a una revalidación REAL,
    `revalidar_motivo_destino_ya_confirmado_sin_ocr`) contra OTRO
    escritor REAL del dataset (`revalidar_tipo_carga_sin_ocr`, no un
    doble simulado) -- ninguno pisa al otro; el cambio del otro escritor
    nunca desaparece."""
    import threading

    import pytest

    import atlas_core.clasificador_material as clasificador_material
    import atlas_core.revalidacion_documental as revalidacion_documental
    from atlas_core.almacenamiento_portable import SesionOcupadaError

    actual = tmp_path / "operacion" / "actual"
    actual.mkdir(parents=True)
    dataset = actual / "analisis_completo_guias.csv"
    fila = {c: "" for c in COLUMNAS}
    fila.update(archivo="g.jpeg", numero_guia="1", numero_transporte="T1", tipo_carga="", descripcion_material="ROLLOS DE ACERO")
    with dataset.open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader()
        escritor.writerows([fila])

    class _FakeTipoCarga:
        def __init__(self, value: str) -> None:
            self.value = value

    monkeypatch.setattr(
        clasificador_material, "clasificar_material",
        lambda d: _FakeTipoCarga("ROLLOS" if "ROLLOS" in str(d or "").upper() else "NO DETERMINADO"),
    )

    escribir_original = revalidacion_documental._escribir_filas_completas
    dentro_del_lock = threading.Event()
    puede_continuar = threading.Event()

    def escribir_con_pausa(ruta, filas):
        dentro_del_lock.set()
        puede_continuar.wait(timeout=5)
        escribir_original(ruta, filas)

    monkeypatch.setattr(revalidacion_documental, "_escribir_filas_completas", escribir_con_pausa)

    resultado_otro: dict[str, object] = {}

    def correr_otro():
        resultado_otro["valor"] = revalidacion_documental.revalidar_tipo_carga_sin_ocr(ruta_dataset=dataset)

    hilo_otro = threading.Thread(target=correr_otro)
    hilo_otro.start()
    assert dentro_del_lock.wait(timeout=5), "el otro escritor real nunca llegó a tomar el lock del dataset"

    # `version_previa` es 0 (ningún `estado_operacion.json` previo) --
    # `migracion=True` dispara la revalidación REAL, que intenta MIENTRAS
    # el otro escritor real todavía tiene el lock tomado.
    with pytest.raises(SesionOcupadaError):
        modulo.reconciliar_estado_derivado(raiz_atlas=tmp_path, reloj=RELOJ)

    puede_continuar.set()
    hilo_otro.join(timeout=5)
    assert resultado_otro["valor"]["guias_actualizadas"] == ["1"]

    # Reintento -- converge, y la actualización del otro escritor sigue
    # ahí, intacta. Reloj distinto del primer intento -- el real nunca
    # repite timestamp entre dos llamadas, a diferencia de `RELOJ` fijo.
    reloj_reintento = lambda: datetime(2026, 8, 31, 18, 0, 1, tzinfo=timezone.utc)
    resultado_reintento = modulo.reconciliar_estado_derivado(raiz_atlas=tmp_path, reloj=reloj_reintento)
    assert resultado_reintento["reconciliado"] is True

    with dataset.open(encoding="utf-8-sig", newline="") as archivo:
        filas_finales = list(csv.DictReader(archivo, delimiter=";"))
    assert filas_finales[0]["tipo_carga"] == "ROLLOS"
