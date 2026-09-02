"""Bloque REPROCESO PERSISTIDO IDEMPOTENTE (causa raíz real 472624):
`procesar_envio_mobile` es deliberadamente APPEND-ONLY -- si el
identificador ya existe en el dataset, nunca vuelve a escribir la fila
(eso es justamente lo que evita duplicar). Pero eso también significaba
que, hasta este bloque, un fix real de extracción/OCR (Motor corregido)
nunca podía llegar a la fila YA PERSISTIDA de un documento -- quedaba
mostrando el estado viejo para siempre.

`reprocesar_envio_mobile_persistido` es el modo COMPLEMENTARIO explícito
de reemplazo: identifica la fila EXCLUSIVAMENTE por el identificador
persistente del documento (`archivo`), reutiliza el MISMO pipeline
OCR/extracción/asociación que `procesar_envio_mobile` (nunca un segundo
camino), y sustituye esa fila en el lugar vía el mismo reescritor
atómico completo (`_escribir_filas_completas`) que ya usan las
revalidaciones `_sin_ocr`. Nunca conoce ninguna guía/cliente concretos
-- opera sobre cualquier `envio_id` ya persistido."""
from __future__ import annotations

import csv
import json
import threading
import uuid
from pathlib import Path

import pytest

from atlas_core.almacenamiento_portable import SesionOcupadaError, leer_estado_operacion
from atlas_core.decisiones_pendientes import generar_artefacto
from atlas_core.mobile import (
    ESTADO_DERIVADOS_PENDIENTES,
    FASE_DATASET_REEMPLAZADO,
    FASE_DERIVADOS_REGENERADOS,
    FASE_PREPARADO,
    FASE_PROCESADO_EN_MEMORIA,
    ErrorEnvioMobile,
    RepositorioEnviosMobile,
    procesar_envio_mobile,
    reprocesar_envio_mobile_persistido,
)
from atlas_core.procesamiento_masivo import COLUMNAS
from atlas_core.revalidacion_documental import revalidar_y_regenerar_reporte


def _dataset_vacio(ruta: Path) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with ruta.open("w", newline="", encoding="utf-8-sig") as archivo:
        csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";").writeheader()


def _dataset_con_filas(ruta: Path, filas: list[dict[str, str]]) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    completas = [{columna: fila.get(columna, "") for columna in COLUMNAS} for fila in filas]
    with ruta.open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader()
        escritor.writerows(completas)


def _leer_filas_dataset(ruta: Path) -> list[dict[str, str]]:
    with ruta.open(encoding="utf-8-sig", newline="") as archivo:
        return list(csv.DictReader(archivo, delimiter=";"))


def _catalogos_minimos(ruta: Path) -> Path:
    ruta.mkdir(parents=True, exist_ok=True)
    contenidos = {
        "clientes.json": {"version_formato": 1, "clientes": []},
        "obras_destinos.json": {"version_formato": 1, "obras": [], "relaciones": []},
        "destinos_maestros.json": {"version_formato": 1, "destinos": []},
        "vehiculos.json": {"version": 1, "vehiculos": []},
        "plantas.json": {"version_formato": 1, "plantas": []},
        "telemetria_cache.json": {},
        "evidencia_entidades.json": {},
        "verificacion_externa_cache.json": {},
    }
    for nombre, contenido in contenidos.items():
        (ruta / nombre).write_text(json.dumps(contenido), encoding="utf-8")
    return ruta


def _recibir(tmp_path: Path) -> tuple[RepositorioEnviosMobile, str]:
    repo = RepositorioEnviosMobile(tmp_path)
    envio_id = str(uuid.uuid4())
    repo.recibir(
        envio_id=envio_id, imagen=b"foto", mime="image/jpeg",
        metadata={"chofer_id": "c1", "tipo_novedad": "", "guia_firmada_correo": False, "planta_origen_informada": "AZA_COLINA"},
    )
    return repo, envio_id


def _fila_vieja(identificador: str, **overrides) -> dict[str, str]:
    fila = {columna: "" for columna in COLUMNAS}
    fila.update(
        archivo=identificador, numero_guia="900001", numero_transporte="0000900000",
        cliente="No encontrado", rut_cliente="No encontrado", estado_procesamiento="OK",
    )
    fila.update(overrides)
    return fila


# ---- 1. reemplaza exactamente una fila existente ----


def test_reemplaza_exactamente_una_fila_existente(tmp_path: Path, monkeypatch) -> None:
    import atlas_core.mobile as mobile

    repo, envio_id = _recibir(tmp_path)
    dataset = tmp_path / "operacion/actual/analisis_completo_guias.csv"
    identificador = f"mobile/{envio_id}/original.jpg"
    _dataset_con_filas(dataset, [_fila_vieja(identificador)])

    monkeypatch.setattr(mobile, "crear_proveedor_ocr", lambda: object())
    monkeypatch.setattr(
        mobile, "procesar_archivo",
        lambda ruta, **kw: {"numero_guia": "900001", "numero_transporte": "0000900000", "cliente": "SODIMAC SA", "rut_cliente": "96.792.430-K"},
    )

    resultado = reprocesar_envio_mobile_persistido(repo, envio_id, dataset=dataset)
    assert resultado["estado"] != "ERROR", resultado.get("error")

    filas = _leer_filas_dataset(dataset)
    assert len(filas) == 1
    assert filas[0]["archivo"] == identificador
    assert filas[0]["cliente"] == "SODIMAC SA"
    assert filas[0]["rut_cliente"] == "96.792.430-K"


# ---- 2. no aumenta el conteo total de filas, ni toca otros documentos ----


def test_no_aumenta_conteo_y_no_toca_otras_filas(tmp_path: Path, monkeypatch) -> None:
    import atlas_core.mobile as mobile

    repo, envio_id = _recibir(tmp_path)
    dataset = tmp_path / "operacion/actual/analisis_completo_guias.csv"
    identificador = f"mobile/{envio_id}/original.jpg"
    otra_fila_1 = _fila_vieja("mobile/otro-envio-1/original.jpg", numero_guia="100001", numero_transporte="0000100001", cliente="OTRO CLIENTE SA")
    otra_fila_2 = _fila_vieja("mobile/otro-envio-2/original.jpg", numero_guia="100002", numero_transporte="0000100002", cliente="TERCER CLIENTE SA")
    _dataset_con_filas(dataset, [otra_fila_1, _fila_vieja(identificador), otra_fila_2])

    monkeypatch.setattr(mobile, "crear_proveedor_ocr", lambda: object())
    monkeypatch.setattr(
        mobile, "procesar_archivo",
        lambda ruta, **kw: {"numero_guia": "900001", "numero_transporte": "0000900000", "cliente": "SODIMAC SA"},
    )

    reprocesar_envio_mobile_persistido(repo, envio_id, dataset=dataset)

    filas = _leer_filas_dataset(dataset)
    assert len(filas) == 3
    filas_por_archivo = {f["archivo"]: f for f in filas}
    assert filas_por_archivo["mobile/otro-envio-1/original.jpg"]["cliente"] == "OTRO CLIENTE SA"
    assert filas_por_archivo["mobile/otro-envio-2/original.jpg"]["cliente"] == "TERCER CLIENTE SA"
    assert filas_por_archivo[identificador]["cliente"] == "SODIMAC SA"


# ---- 3. idempotencia: segunda ejecución con el mismo resultado no cambia nada más ----


def test_segunda_ejecucion_idempotente_no_cambia_el_dataset_de_nuevo(tmp_path: Path, monkeypatch) -> None:
    import atlas_core.mobile as mobile

    repo, envio_id = _recibir(tmp_path)
    dataset = tmp_path / "operacion/actual/analisis_completo_guias.csv"
    identificador = f"mobile/{envio_id}/original.jpg"
    _dataset_con_filas(dataset, [_fila_vieja(identificador)])

    monkeypatch.setattr(mobile, "crear_proveedor_ocr", lambda: object())
    monkeypatch.setattr(
        mobile, "procesar_archivo",
        lambda ruta, **kw: {"numero_guia": "900001", "numero_transporte": "0000900000", "cliente": "SODIMAC SA", "rut_cliente": "96.792.430-K"},
    )

    reprocesar_envio_mobile_persistido(repo, envio_id, dataset=dataset)
    contenido_tras_primera = dataset.read_bytes()

    reprocesar_envio_mobile_persistido(repo, envio_id, dataset=dataset)
    contenido_tras_segunda = dataset.read_bytes()

    assert contenido_tras_segunda == contenido_tras_primera, "misma entrada -- el dataset debe quedar byte a byte idéntico"
    assert len(_leer_filas_dataset(dataset)) == 1


# ---- 4. falta de fila -> nunca hace append ----


def test_fila_ausente_se_abstiene_y_nunca_hace_append(tmp_path: Path, monkeypatch) -> None:
    import atlas_core.mobile as mobile

    repo, envio_id = _recibir(tmp_path)
    dataset = tmp_path / "operacion/actual/analisis_completo_guias.csv"
    otra_fila = _fila_vieja("mobile/otro-envio/original.jpg", numero_guia="100001", numero_transporte="0000100001")
    _dataset_con_filas(dataset, [otra_fila])
    contenido_antes = dataset.read_bytes()

    monkeypatch.setattr(mobile, "crear_proveedor_ocr", lambda: object())
    monkeypatch.setattr(
        mobile, "procesar_archivo",
        lambda ruta, **kw: {"numero_guia": "900001", "numero_transporte": "0000900000"},
    )

    with pytest.raises(ErrorEnvioMobile, match="No existe ninguna fila"):
        reprocesar_envio_mobile_persistido(repo, envio_id, dataset=dataset)

    assert dataset.read_bytes() == contenido_antes, "sin la fila del documento, el dataset no debe tocarse -- nunca un append silencioso"
    registro = repo.cargar(envio_id)
    assert registro["estado"] == "RECIBIDO", "la abstención es previa a cualquier intento -- nunca marca PROCESANDO/ERROR"


# ---- 5. identificador duplicado -> aborta, nunca decide cuál ----


def test_identificador_duplicado_aborta_y_no_toca_el_dataset(tmp_path: Path, monkeypatch) -> None:
    import atlas_core.mobile as mobile

    repo, envio_id = _recibir(tmp_path)
    dataset = tmp_path / "operacion/actual/analisis_completo_guias.csv"
    identificador = f"mobile/{envio_id}/original.jpg"
    _dataset_con_filas(dataset, [
        _fila_vieja(identificador, cliente="PRIMERA COPIA SA"),
        _fila_vieja(identificador, cliente="SEGUNDA COPIA SA"),
    ])
    contenido_antes = dataset.read_bytes()

    monkeypatch.setattr(mobile, "crear_proveedor_ocr", lambda: object())
    monkeypatch.setattr(
        mobile, "procesar_archivo",
        lambda ruta, **kw: {"numero_guia": "900001", "numero_transporte": "0000900000"},
    )

    with pytest.raises(ErrorEnvioMobile, match="Existen 2 filas"):
        reprocesar_envio_mobile_persistido(repo, envio_id, dataset=dataset)

    assert dataset.read_bytes() == contenido_antes, "ante una anomalía preexistente (duplicado), nunca se decide ni se escribe nada"


# ---- 6. derivados (decisiones/asociación/reporte/estado_operación) se regeneran ----


def test_derivados_decisiones_asociacion_reporte_y_estado_operacion_se_regeneran(tmp_path: Path, monkeypatch) -> None:
    """Reproduce, en miniatura, el caso real 472624: fila vieja con
    cliente/RUT sin resolver y un motivo accionable; reproceso con Motor
    corregido debe dejar la fila limpia -- y componer el reproceso con el
    reconciliador general ya existente (`revalidar_y_regenerar_reporte`,
    exactamente el mismo mecanismo canónico que usa `servidor_mobile.
    _procesar_y_revalidar` -- nunca duplicado dentro de este bloque) debe
    reflejar esa corrección en reporte/estado_operación."""
    import atlas_core.mobile as mobile

    repo, envio_id = _recibir(tmp_path)
    catalogos = _catalogos_minimos(tmp_path / "catalogos_privados")
    dataset = tmp_path / "operacion/actual/analisis_completo_guias.csv"
    identificador = f"mobile/{envio_id}/original.jpg"
    _dataset_con_filas(dataset, [_fila_vieja(
        identificador, indicador_revision="REVISAR", estado_documental="REQUIERE_REVISION",
        motivos_revision_documento="DESTINO_CONTAMINADO_POR_OTRA_SECCION",
    )])
    # Semilla de decisiones_pendientes.json, igual que en producción
    # (procesar_envio_mobile ya lo crea/actualiza como parte de su propio
    # procesamiento) -- necesario para que revalidar_y_regenerar_reporte
    # tenga una bandeja que republicar en la corrida de referencia.
    generar_artefacto(
        ruta_dataset=dataset, carpeta_catalogos=catalogos, decisiones=[],
        ruta_salida=dataset.parent / "decisiones_pendientes.json",
    )

    # Corrida de referencia: establece el reporte/estado_operación
    # vigente ANTES del reproceso -- mismo patrón que el resto del
    # bloque REVISIÓN DE ATLAS para probar que una corrida posterior
    # detecta el cambio real.
    resultado_referencia = revalidar_y_regenerar_reporte(raiz_atlas=tmp_path, nombre_carpeta_reporte="reporte_referencia")
    assert resultado_referencia["reporte_regenerado"] is True

    monkeypatch.setattr(mobile, "crear_proveedor_ocr", lambda: object())
    monkeypatch.setattr(
        mobile, "procesar_archivo",
        lambda ruta, **kw: {"numero_guia": "900001", "numero_transporte": "0000900000", "cliente": "SODIMAC SA", "rut_cliente": "96.792.430-K"},
    )

    resultado = reprocesar_envio_mobile_persistido(repo, envio_id, dataset=dataset, carpeta_catalogos=catalogos)
    assert resultado["estado"] != "ERROR", resultado.get("error")

    # 1) decisiones/asociación -- ya regenerados por el propio reproceso
    #    (mismo mecanismo canónico que procesar_envio_mobile).
    assert (dataset.parent / "decisiones_pendientes.json").is_file()
    assert resultado["resultado_asociacion"]["numero_guia"] == "900001"

    # 2) reporte/estado_operación -- se componen aparte, con el MISMO
    #    reconciliador general ya existente.
    resultado_tras_reproceso = revalidar_y_regenerar_reporte(raiz_atlas=tmp_path, nombre_carpeta_reporte="reporte_tras_reproceso")
    assert resultado_tras_reproceso["reporte_regenerado"] is True, resultado_tras_reproceso

    estado = leer_estado_operacion(raiz=tmp_path)
    assert estado is not None
    viajes_csv = (tmp_path / estado["reporte_vigente"] / "viajes.csv").read_text(encoding="utf-8-sig")
    assert "900001" in viajes_csv
    assert "SODIMAC SA" in viajes_csv


# ============================================================
# 7. Un reproceso fallido NUNCA degrada un envío previamente válido
#    (Hallazgo Codex -- fases explícitas, preservación de estado,
#    concurrencia)
# ============================================================


def test_fallo_ocr_antes_de_escribir_preserva_dataset_y_estado_previo_del_envio(tmp_path: Path, monkeypatch) -> None:
    """Sección 1: un envío que YA tenía un procesamiento válido anterior
    (estado/datos_ocr/asociación reales) nunca debe quedar degradado a
    ERROR sólo porque un INTENTO de reproceso falló en el OCR -- se
    restaura tal cual estaba, y el fallo queda diagnosticable aparte."""
    import atlas_core.mobile as mobile

    repo, envio_id = _recibir(tmp_path)
    dataset = tmp_path / "operacion/actual/analisis_completo_guias.csv"
    identificador = f"mobile/{envio_id}/original.jpg"
    fila_vieja = _fila_vieja(identificador, cliente="SODIMAC SA")
    _dataset_con_filas(dataset, [fila_vieja])

    # Estado previo REAL (no un envío recién recibido): simula un
    # procesamiento anterior exitoso que un reproceso fallido NUNCA debe
    # degradar.
    registro_previo = repo.cargar(envio_id)
    registro_previo.update({
        "estado": "ASOCIADO",
        "datos_ocr": {"numero_guia": "900001", "cliente": "SODIMAC SA", "rut_cliente": "96.792.430-K"},
        "resultado_asociacion": {"estado": "ASOCIADO_AUTOMATICAMENTE", "numero_transporte": "0000900000", "numero_guia": "900001"},
        "atlas_ia": {"llamadas": 0},
        "archivo_dataset": identificador,
        "error": "",
    })
    repo.guardar(envio_id, registro_previo)
    dataset_antes = dataset.read_bytes()

    monkeypatch.setattr(mobile, "crear_proveedor_ocr", lambda: object())

    def procesar_archivo_roto(ruta, **kw):
        raise RuntimeError("OCR caído (simulado)")

    monkeypatch.setattr(mobile, "procesar_archivo", procesar_archivo_roto)

    resultado = reprocesar_envio_mobile_persistido(repo, envio_id, dataset=dataset)

    # El dataset nunca se tocó.
    assert dataset.read_bytes() == dataset_antes
    # El envío quedó EXACTAMENTE como antes -- nunca "ERROR" genérico,
    # nunca pierde los datos válidos del procesamiento anterior.
    assert resultado["estado"] == "ASOCIADO"
    assert resultado["datos_ocr"] == registro_previo["datos_ocr"]
    assert resultado["resultado_asociacion"] == registro_previo["resultado_asociacion"]
    assert resultado["error"] == ""
    # El fallo del INTENTO de reproceso queda diagnosticable aparte.
    diagnostico = resultado["reproceso_persistido"]
    assert diagnostico["fase"] == FASE_PROCESADO_EN_MEMORIA
    assert diagnostico["estado"] == "FALLIDO"
    assert "OCR caído" in diagnostico["error"]


def test_fallo_derivados_tras_reemplazar_preserva_datos_nuevos_y_marca_estado_parcial(tmp_path: Path, monkeypatch) -> None:
    """Sección 2: si la fila YA fue sustituida y luego falla regenerar
    decisiones/artefacto, el reemplazo NUNCA se revierte -- el envío
    queda con estado parcial explícito (`ESTADO_DERIVADOS_PENDIENTES`),
    nunca un fallo total, y con los datos NUEVOS (no los viejos)."""
    import atlas_core.mobile as mobile

    repo, envio_id = _recibir(tmp_path)
    catalogos = _catalogos_minimos(tmp_path / "catalogos_privados")
    dataset = tmp_path / "operacion/actual/analisis_completo_guias.csv"
    identificador = f"mobile/{envio_id}/original.jpg"
    _dataset_con_filas(dataset, [_fila_vieja(identificador)])

    monkeypatch.setattr(mobile, "crear_proveedor_ocr", lambda: object())
    monkeypatch.setattr(
        mobile, "procesar_archivo",
        lambda ruta, **kw: {"numero_guia": "900001", "numero_transporte": "0000900000", "cliente": "SODIMAC SA", "rut_cliente": "96.792.430-K"},
    )

    # Checkpoint DURABLE en disco: en el momento en que se intenta
    # regenerar el artefacto, el dataset YA debe estar reemplazado y el
    # diagnóstico ya debe reflejar la fase DATASET_REEMPLAZADO -- si el
    # proceso se interrumpiera justo acá, esto es lo que quedaría en
    # disco (Sección 3: diagnóstico recuperable entre fases).
    estado_capturado: dict[str, object] = {}

    def generar_artefacto_roto(*args, **kwargs):
        estado_capturado.update(repo.cargar(envio_id))
        estado_capturado["_filas_dataset"] = _leer_filas_dataset(dataset)
        raise RuntimeError("catálogo de decisiones corrupto (simulado)")

    # Ronda 8 (consistencia operacional): la publicación real ahora corre
    # vía `_generar_artefacto_sin_lock` bajo el lock de decisiones -- es
    # esa función la que hay que interceptar.
    monkeypatch.setattr(mobile, "_generar_artefacto_sin_lock", generar_artefacto_roto)

    resultado = reprocesar_envio_mobile_persistido(repo, envio_id, dataset=dataset, carpeta_catalogos=catalogos)

    # Checkpoint intermedio: el dataset ya estaba reemplazado ANTES de
    # que el fallo ocurriera.
    assert estado_capturado["_filas_dataset"][0]["cliente"] == "SODIMAC SA"
    assert estado_capturado["reproceso_persistido"]["fase"] == FASE_DATASET_REEMPLAZADO

    # El dataset queda con los datos NUEVOS -- nunca se revierte.
    filas = _leer_filas_dataset(dataset)
    assert len(filas) == 1
    assert filas[0]["cliente"] == "SODIMAC SA"
    assert filas[0]["rut_cliente"] == "96.792.430-K"

    # El envío NUNCA queda en fallo total -- estado parcial explícito,
    # con los datos nuevos (no restaurados a los viejos).
    assert resultado["estado"] == ESTADO_DERIVADOS_PENDIENTES
    assert resultado["estado"] != "ERROR"
    assert resultado["datos_ocr"]["cliente"] == "SODIMAC SA"
    diagnostico = resultado["reproceso_persistido"]
    assert diagnostico["fase"] == FASE_DERIVADOS_REGENERADOS
    assert diagnostico["estado"] == "FALLIDO"
    assert "catálogo de decisiones corrupto" in diagnostico["error"]


def test_reejecucion_tras_derivados_pendientes_completa_de_forma_idempotente(tmp_path: Path, monkeypatch) -> None:
    """Sección 3: una reejecución posterior, con el catálogo/derivados ya
    reparados, completa la fase que faltaba -- sin volver a tocar el
    dataset (misma fila, mismo contenido) y sin duplicar nada."""
    import atlas_core.mobile as mobile

    repo, envio_id = _recibir(tmp_path)
    catalogos = _catalogos_minimos(tmp_path / "catalogos_privados")
    dataset = tmp_path / "operacion/actual/analisis_completo_guias.csv"
    identificador = f"mobile/{envio_id}/original.jpg"
    _dataset_con_filas(dataset, [_fila_vieja(identificador)])

    monkeypatch.setattr(mobile, "crear_proveedor_ocr", lambda: object())
    monkeypatch.setattr(
        mobile, "procesar_archivo",
        lambda ruta, **kw: {"numero_guia": "900001", "numero_transporte": "0000900000", "cliente": "SODIMAC SA", "rut_cliente": "96.792.430-K"},
    )
    monkeypatch.setattr(mobile, "_generar_artefacto_sin_lock", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("roto (simulado)")))

    primer_resultado = reprocesar_envio_mobile_persistido(repo, envio_id, dataset=dataset, carpeta_catalogos=catalogos)
    assert primer_resultado["estado"] == ESTADO_DERIVADOS_PENDIENTES
    dataset_tras_primera = dataset.read_bytes()

    # El catálogo/derivados ya "se repararon" -- se restaura el
    # comportamiento real de generar_artefacto.
    monkeypatch.undo()
    monkeypatch.setattr(mobile, "crear_proveedor_ocr", lambda: object())
    monkeypatch.setattr(
        mobile, "procesar_archivo",
        lambda ruta, **kw: {"numero_guia": "900001", "numero_transporte": "0000900000", "cliente": "SODIMAC SA", "rut_cliente": "96.792.430-K"},
    )

    segundo_resultado = reprocesar_envio_mobile_persistido(repo, envio_id, dataset=dataset, carpeta_catalogos=catalogos)

    assert segundo_resultado["estado"] != ESTADO_DERIVADOS_PENDIENTES
    assert segundo_resultado["estado"] != "ERROR"
    assert segundo_resultado["reproceso_persistido"]["fase"] == "COMPLETADO"
    # El dataset queda IDÉNTICO -- la reejecución no duplicó ni volvió a
    # cambiar la fila (mismos datos de entrada).
    assert dataset.read_bytes() == dataset_tras_primera
    assert len(_leer_filas_dataset(dataset)) == 1
    assert (dataset.parent / "decisiones_pendientes.json").is_file()


def test_interrupcion_simulada_entre_fases_deja_diagnostico_recuperable_en_disco(tmp_path: Path, monkeypatch) -> None:
    """Sección 3: si el proceso se interrumpiera justo cuando arranca
    OCR/B1 (fase PROCESADO_EN_MEMORIA), el diagnóstico YA en disco debe
    mostrar que se llegó a PREPARADO -- suficiente para saber, sin
    adivinar, que el dataset todavía no se tocó y que es seguro
    reintentar desde cero."""
    import atlas_core.mobile as mobile

    repo, envio_id = _recibir(tmp_path)
    dataset = tmp_path / "operacion/actual/analisis_completo_guias.csv"
    identificador = f"mobile/{envio_id}/original.jpg"
    _dataset_con_filas(dataset, [_fila_vieja(identificador)])

    diagnostico_durante_la_interrupcion: dict[str, object] = {}

    def procesar_archivo_interrumpido(ruta, **kw):
        diagnostico_durante_la_interrupcion.update(repo.cargar(envio_id))
        raise RuntimeError("interrupción simulada durante OCR")

    monkeypatch.setattr(mobile, "crear_proveedor_ocr", lambda: object())
    monkeypatch.setattr(mobile, "procesar_archivo", procesar_archivo_interrumpido)

    reprocesar_envio_mobile_persistido(repo, envio_id, dataset=dataset)

    # Checkpoint EN DISCO capturado durante la propia interrupción --
    # ya reflejaba PREPARADO en progreso, nunca información ausente.
    assert diagnostico_durante_la_interrupcion["reproceso_persistido"]["fase"] == FASE_PREPARADO
    assert diagnostico_durante_la_interrupcion["reproceso_persistido"]["estado"] == "EN_PROGRESO"
    assert diagnostico_durante_la_interrupcion["estado"] == "PROCESANDO"

    # Diagnóstico final -- avanzó y quedó recuperable: se sabe
    # exactamente hasta dónde llegó (PROCESADO_EN_MEMORIA, fallido).
    registro_final = repo.cargar(envio_id)
    assert registro_final["reproceso_persistido"]["fase"] == FASE_PROCESADO_EN_MEMORIA
    assert registro_final["reproceso_persistido"]["estado"] == "FALLIDO"


def test_dos_reprocesos_concurrentes_no_pierden_filas_ni_actualizaciones(tmp_path: Path, monkeypatch) -> None:
    """Sección 4: dos reprocesos concurrentes sobre el MISMO dataset
    (documentos distintos) nunca se pisan -- uno escribe bajo lock,
    el otro se entera de la contención con un error explícito (nunca
    pierde su actualización en silencio) y, reintentado después, se
    aplica igual. Al final ambas filas quedan correctas, sin perder
    ninguna."""
    import atlas_core.revalidacion_documental as revalidacion_documental
    import atlas_core.mobile as mobile

    repo = RepositorioEnviosMobile(tmp_path)
    envio_id_1 = str(uuid.uuid4())
    envio_id_2 = str(uuid.uuid4())
    for envio_id in (envio_id_1, envio_id_2):
        repo.recibir(
            envio_id=envio_id, imagen=b"foto", mime="image/jpeg",
            metadata={"chofer_id": "c1", "tipo_novedad": "", "guia_firmada_correo": False, "planta_origen_informada": "AZA_COLINA"},
        )
    dataset = tmp_path / "operacion/actual/analisis_completo_guias.csv"
    identificador_1 = f"mobile/{envio_id_1}/original.jpg"
    identificador_2 = f"mobile/{envio_id_2}/original.jpg"
    _dataset_con_filas(dataset, [
        _fila_vieja(identificador_1, numero_guia="900001", numero_transporte="0000900001"),
        _fila_vieja(identificador_2, numero_guia="900002", numero_transporte="0000900002"),
    ])

    monkeypatch.setattr(mobile, "crear_proveedor_ocr", lambda: object())
    monkeypatch.setattr(
        mobile, "procesar_archivo",
        lambda ruta, **kw: {"numero_guia": "900001", "numero_transporte": "0000900001", "cliente": "PRIMER CLIENTE SA"},
    )

    # El hilo 1 queda DENTRO del lock (justo antes de escribir) hasta
    # que el test se lo permita -- garantiza que el hilo 2 intente
    # mientras el lock sigue tomado.
    hilo1_dentro_del_lock = threading.Event()
    hilo1_puede_escribir = threading.Event()
    escribir_original = revalidacion_documental._escribir_filas_completas

    def escribir_con_pausa(ruta, filas):
        hilo1_dentro_del_lock.set()
        hilo1_puede_escribir.wait(timeout=5)
        escribir_original(ruta, filas)

    monkeypatch.setattr(revalidacion_documental, "_escribir_filas_completas", escribir_con_pausa)

    resultado_hilo1: dict[str, object] = {}

    def correr_hilo1():
        resultado_hilo1["valor"] = reprocesar_envio_mobile_persistido(repo, envio_id_1, dataset=dataset)

    hilo1 = threading.Thread(target=correr_hilo1)
    hilo1.start()
    assert hilo1_dentro_del_lock.wait(timeout=5), "el hilo 1 nunca llegó a tomar el lock"

    # El hilo 2 intenta MIENTRAS el hilo 1 todavía tiene el lock -- debe
    # enterarse con un error explícito, nunca pisar/perder en silencio.
    monkeypatch.setattr(
        mobile, "procesar_archivo",
        lambda ruta, **kw: {"numero_guia": "900002", "numero_transporte": "0000900002", "cliente": "SEGUNDO CLIENTE SA"},
    )
    resultado_hilo2_primer_intento = reprocesar_envio_mobile_persistido(repo, envio_id_2, dataset=dataset)
    assert resultado_hilo2_primer_intento["reproceso_persistido"]["fase"] == FASE_DATASET_REEMPLAZADO
    assert resultado_hilo2_primer_intento["reproceso_persistido"]["estado"] == "FALLIDO"
    assert "SesionOcupadaError" in resultado_hilo2_primer_intento["reproceso_persistido"]["error"]

    # Se libera el hilo 1 y se reintenta el hilo 2 (mismo patrón que
    # cualquier caller real ante contención: reintentar después).
    hilo1_puede_escribir.set()
    hilo1.join(timeout=5)
    assert resultado_hilo1["valor"]["reproceso_persistido"]["fase"] == "COMPLETADO"

    resultado_hilo2_reintento = reprocesar_envio_mobile_persistido(repo, envio_id_2, dataset=dataset)
    assert resultado_hilo2_reintento["reproceso_persistido"]["fase"] == "COMPLETADO"

    # Ninguna fila se perdió ni se pisó -- ambas quedaron con sus datos
    # nuevos respectivos.
    filas = _leer_filas_dataset(dataset)
    assert len(filas) == 2
    filas_por_archivo = {f["archivo"]: f for f in filas}
    assert filas_por_archivo[identificador_1]["cliente"] == "PRIMER CLIENTE SA"
    assert filas_por_archivo[identificador_2]["cliente"] == "SEGUNDO CLIENTE SA"


# ============================================================
# 8. Journal separado (Hallazgo Codex, ronda 5) -- ventana entre el
#    reemplazo del dataset y el checkpoint de `envio.json`, y lock
#    COMÚN por recurso con otros escritores reales.
# ============================================================


def test_fallo_guardar_envio_json_tras_reemplazo_conserva_journal_y_no_restaura_datos_viejos(tmp_path: Path, monkeypatch) -> None:
    """Hallazgo #1/#2: si el dataset YA se reemplazó y el guardado
    SIGUIENTE de `envio.json` falla, el fallo nunca se trata como "antes
    del reemplazo" -- nunca se restaura `estado_previo` encima de los
    datos nuevos, y la evidencia completa sobrevive en el journal aunque
    `envio.json` se haya quedado en el checkpoint anterior."""
    import atlas_core.mobile as mobile

    repo, envio_id = _recibir(tmp_path)
    dataset = tmp_path / "operacion/actual/analisis_completo_guias.csv"
    identificador = f"mobile/{envio_id}/original.jpg"
    _dataset_con_filas(dataset, [_fila_vieja(identificador)])

    monkeypatch.setattr(mobile, "crear_proveedor_ocr", lambda: object())
    monkeypatch.setattr(
        mobile, "procesar_archivo",
        lambda ruta, **kw: {"numero_guia": "900001", "numero_transporte": "0000900000", "cliente": "SODIMAC SA", "rut_cliente": "96.792.430-K"},
    )

    guardar_original = repo.guardar

    def guardar_roto(envio_id_arg, registro):
        diagnostico = registro.get("reproceso_persistido") or {}
        if diagnostico.get("fase") == mobile.FASE_DATASET_REEMPLAZADO and diagnostico.get("estado") == "EN_PROGRESO":
            raise OSError("disco lleno (simulado) justo después del reemplazo")
        guardar_original(envio_id_arg, registro)

    monkeypatch.setattr(repo, "guardar", guardar_roto)

    with pytest.raises(ErrorEnvioMobile, match="journal"):
        reprocesar_envio_mobile_persistido(repo, envio_id, dataset=dataset)

    # El dataset YA quedó reemplazado -- este fallo nunca lo revierte.
    filas = _leer_filas_dataset(dataset)
    assert filas[0]["cliente"] == "SODIMAC SA"
    assert filas[0]["rut_cliente"] == "96.792.430-K"

    # `envio.json` se quedó en el checkpoint ANTERIOR al que falló --
    # nunca "ERROR" genérico, nunca los datos viejos restaurados encima.
    registro_en_disco = repo.cargar(envio_id)
    assert registro_en_disco["reproceso_persistido"]["fase"] == FASE_PROCESADO_EN_MEMORIA
    assert registro_en_disco["estado"] == "PROCESANDO"

    # El journal SÍ conserva la evidencia completa -- sobrevive aunque
    # `envio.json` no se haya podido actualizar.
    journal = json.loads((dataset.parent / mobile.NOMBRE_JOURNAL_REPROCESO_PERSISTIDO).read_text(encoding="utf-8"))
    entrada = journal[identificador]
    assert entrada["datos_ocr"]["cliente"] == "SODIMAC SA"
    assert entrada["fila_hash"] == mobile._hash_fila(filas[0])


def test_reejecucion_tras_fallo_de_guardado_de_envio_json_reanuda_desde_journal_sin_repetir_ocr(tmp_path: Path, monkeypatch) -> None:
    """Hallazgo #1/#3: una vez reparado lo que hacía fallar el guardado
    de `envio.json`, una reejecución del MISMO reproceso completa desde
    el journal -- sin volver a llamar OCR (el dataset ya tiene la fila
    correcta; repetir OCR sería trabajo perdido y una ventana más para
    volver a fallar)."""
    import atlas_core.mobile as mobile

    repo, envio_id = _recibir(tmp_path)
    dataset = tmp_path / "operacion/actual/analisis_completo_guias.csv"
    identificador = f"mobile/{envio_id}/original.jpg"
    _dataset_con_filas(dataset, [_fila_vieja(identificador)])

    monkeypatch.setattr(mobile, "crear_proveedor_ocr", lambda: object())
    llamadas_ocr = {"n": 0}

    def procesar_archivo_contador(ruta, **kw):
        llamadas_ocr["n"] += 1
        return {"numero_guia": "900001", "numero_transporte": "0000900000", "cliente": "SODIMAC SA", "rut_cliente": "96.792.430-K"}

    monkeypatch.setattr(mobile, "procesar_archivo", procesar_archivo_contador)

    guardar_original = repo.guardar

    def guardar_roto_una_vez(envio_id_arg, registro):
        diagnostico = registro.get("reproceso_persistido") or {}
        if diagnostico.get("fase") == mobile.FASE_DATASET_REEMPLAZADO and diagnostico.get("estado") == "EN_PROGRESO":
            raise OSError("disco lleno (simulado)")
        guardar_original(envio_id_arg, registro)

    monkeypatch.setattr(repo, "guardar", guardar_roto_una_vez)
    with pytest.raises(ErrorEnvioMobile):
        reprocesar_envio_mobile_persistido(repo, envio_id, dataset=dataset)
    assert llamadas_ocr["n"] == 1

    # Se "repara" lo que hacía fallar el guardado.
    monkeypatch.setattr(repo, "guardar", guardar_original)

    resultado = reprocesar_envio_mobile_persistido(repo, envio_id, dataset=dataset)

    assert llamadas_ocr["n"] == 1, "no debía repetir OCR -- debía reanudar desde el journal"
    assert resultado["estado"] != "ERROR"
    assert resultado["reproceso_persistido"]["fase"] == "COMPLETADO"
    assert resultado["datos_ocr"]["cliente"] == "SODIMAC SA"

    filas = _leer_filas_dataset(dataset)
    assert len(filas) == 1
    assert filas[0]["cliente"] == "SODIMAC SA"

    # Éxito total -- el journal ya se limpió para este identificador.
    journal = json.loads((dataset.parent / mobile.NOMBRE_JOURNAL_REPROCESO_PERSISTIDO).read_text(encoding="utf-8"))
    assert identificador not in journal


def test_interrupcion_total_justo_tras_reemplazo_se_recupera_via_journal_sin_repetir_ocr(tmp_path: Path, monkeypatch) -> None:
    """Hallazgo #1, escenario más extremo: el proceso murió literalmente
    justo después de reemplazar la fila del dataset y escribir el
    journal -- ni siquiera hubo una excepción que capturar, `envio.json`
    se quedó mostrando el estado previo a que el reproceso empezara. Una
    reejecución debe detectar, por la huella de la fila YA en el
    dataset, que hay un journal pendiente que coincide, y completar
    desde ahí sin volver a invocar OCR."""
    import atlas_core.mobile as mobile

    repo, envio_id = _recibir(tmp_path)
    catalogos = _catalogos_minimos(tmp_path / "catalogos_privados")
    dataset = tmp_path / "operacion/actual/analisis_completo_guias.csv"
    identificador = f"mobile/{envio_id}/original.jpg"

    fila_ya_reemplazada = _fila_vieja(
        identificador, cliente="SODIMAC SA", rut_cliente="96.792.430-K",
        numero_guia="900001", numero_transporte="0000900000",
    )
    _dataset_con_filas(dataset, [fila_ya_reemplazada])
    fila_en_disco = _leer_filas_dataset(dataset)[0]

    mobile._escribir_entrada_journal_reproceso(dataset, identificador, {
        "envio_id": envio_id,
        "reemplazado_en": "2026-09-02T00:00:00+00:00",
        "fila_hash": mobile._hash_fila(fila_en_disco),
        "datos_ocr": {
            "numero_guia": "900001", "numero_transporte": "0000900000",
            "cliente": "SODIMAC SA", "rut_cliente": "96.792.430-K", "archivo": identificador,
        },
        "resultado_asociacion": {"estado": "ASOCIADO_AUTOMATICAMENTE", "numero_transporte": "0000900000", "numero_guia": "900001"},
        "atlas_ia": {"llamadas": 0},
        "problema_captura": False,
        "decisiones_nuevas": [],
    })
    # `envio.json` nunca llegó a actualizarse -- como si el proceso
    # hubiera muerto antes de cualquier checkpoint del reproceso.
    assert repo.cargar(envio_id)["estado"] == "RECIBIDO"

    def ocr_no_debe_llamarse(*args, **kwargs):
        raise AssertionError("OCR no debía volver a ejecutarse -- debía reanudar desde el journal")

    monkeypatch.setattr(mobile, "crear_proveedor_ocr", ocr_no_debe_llamarse)
    monkeypatch.setattr(mobile, "procesar_archivo", ocr_no_debe_llamarse)

    resultado = reprocesar_envio_mobile_persistido(repo, envio_id, dataset=dataset, carpeta_catalogos=catalogos)

    assert resultado["estado"] != "ERROR"
    assert resultado["reproceso_persistido"]["fase"] == "COMPLETADO"
    assert resultado["datos_ocr"]["cliente"] == "SODIMAC SA"

    filas = _leer_filas_dataset(dataset)
    assert len(filas) == 1
    assert filas[0]["cliente"] == "SODIMAC SA"

    journal = mobile._leer_journal_reproceso(dataset)
    assert identificador not in journal


def test_decisiones_nuevas_no_se_duplican_al_reanudar_desde_journal_tras_fallo_de_guardado(tmp_path: Path, monkeypatch) -> None:
    """Hallazgo #3: `decisiones_nuevas` (incluida `ORIGEN_NO_CONFIRMADO`)
    se calcula ANTES del reemplazo y queda journalizada -- una
    reejecución que reanuda desde el journal la reutiliza tal cual, sin
    volver a calcularla y sin duplicarla en la bandeja persistida."""
    import atlas_core.decisiones_pendientes as decisiones_pendientes
    import atlas_core.mobile as mobile

    repo, envio_id = _recibir(tmp_path)
    catalogos = _catalogos_minimos(tmp_path / "catalogos_privados")
    dataset = tmp_path / "operacion/actual/analisis_completo_guias.csv"
    identificador = f"mobile/{envio_id}/original.jpg"
    _dataset_con_filas(dataset, [_fila_vieja(identificador)])

    monkeypatch.setattr(mobile, "crear_proveedor_ocr", lambda: object())
    llamadas_ocr = {"n": 0}

    def procesar_archivo_contador(ruta, **kw):
        llamadas_ocr["n"] += 1
        return {"numero_guia": "900001", "numero_transporte": "0000900000", "cliente": "SODIMAC SA", "rut_cliente": "96.792.430-K"}

    monkeypatch.setattr(mobile, "procesar_archivo", procesar_archivo_contador)

    def detector_forzado(*, archivo, fila, plantas):
        return {
            "decision_id": f"origen::{archivo}", "tipo": "ORIGEN_NO_CONFIRMADO", "entidad": "ORIGEN",
            "archivo": archivo, "documento": {"numero_guia": "900001", "archivo": archivo},
        }

    monkeypatch.setattr(decisiones_pendientes, "detectar_decision_origen_no_confirmado", detector_forzado)

    guardar_original = repo.guardar

    def guardar_roto_una_vez(envio_id_arg, registro):
        diagnostico = registro.get("reproceso_persistido") or {}
        if diagnostico.get("fase") == mobile.FASE_DATASET_REEMPLAZADO and diagnostico.get("estado") == "EN_PROGRESO":
            raise OSError("disco lleno (simulado)")
        guardar_original(envio_id_arg, registro)

    monkeypatch.setattr(repo, "guardar", guardar_roto_una_vez)

    with pytest.raises(ErrorEnvioMobile):
        reprocesar_envio_mobile_persistido(repo, envio_id, dataset=dataset, carpeta_catalogos=catalogos)
    assert llamadas_ocr["n"] == 1

    monkeypatch.setattr(repo, "guardar", guardar_original)
    resultado = reprocesar_envio_mobile_persistido(repo, envio_id, dataset=dataset, carpeta_catalogos=catalogos)

    assert llamadas_ocr["n"] == 1, "no debía repetir OCR -- debía reanudar desde el journal"
    assert resultado["reproceso_persistido"]["fase"] == "COMPLETADO"

    pendientes = json.loads((dataset.parent / "decisiones_pendientes.json").read_text(encoding="utf-8"))
    ids = [d.get("decision_id") for d in pendientes.get("decisiones", [])]
    assert ids.count(f"origen::{identificador}") == 1, f"decisión duplicada o ausente: {ids}"


def test_concurrencia_reproceso_vs_otro_escritor_real_del_dataset_no_pierde_actualizaciones(tmp_path: Path, monkeypatch) -> None:
    """Hallazgo #4 (bloqueante): el lock COMÚN del dataset
    (`NOMBRE_LOCK_DATASET_OPERACIONAL`) protege frente a CUALQUIER
    escritor real del mismo `analisis_completo_guias.csv`, no sólo entre
    dos reprocesos -- acá el otro escritor es `revalidar_tipo_carga_
    sin_ocr`, una revalidación `_sin_ocr` REAL y preexistente de
    `revalidacion_documental.py` (nunca un doble simulado). Mientras
    tiene el lock tomado, un reproceso concurrente sobre OTRA fila se
    entera de la contención con un error explícito -- ninguna de las dos
    actualizaciones se pierde."""
    import atlas_core.clasificador_material as clasificador_material
    import atlas_core.mobile as mobile
    import atlas_core.revalidacion_documental as revalidacion_documental

    repo, envio_id = _recibir(tmp_path)
    dataset = tmp_path / "operacion/actual/analisis_completo_guias.csv"
    identificador = f"mobile/{envio_id}/original.jpg"
    otra_fila = _fila_vieja(
        "mobile/otro-envio/original.jpg", numero_guia="100001", numero_transporte="0000100001",
        tipo_carga="", descripcion_material="ROLLOS DE ACERO",
    )
    # La fila del propio reproceso queda con un `tipo_carga` que YA
    # coincide con lo que el clasificador (mockeado abajo) produciría --
    # así el otro escritor real sólo tiene algo que actualizar en LA
    # OTRA fila, nunca en la del reproceso.
    _dataset_con_filas(dataset, [otra_fila, _fila_vieja(identificador, tipo_carga="NO DETERMINADO")])

    class _FakeTipoCarga:
        def __init__(self, value: str) -> None:
            self.value = value

    def _clasificar_material_falso(descripcion: str) -> _FakeTipoCarga:
        texto = str(descripcion or "").upper()
        return _FakeTipoCarga("ROLLOS" if "ROLLOS" in texto else "NO DETERMINADO")

    monkeypatch.setattr(clasificador_material, "clasificar_material", _clasificar_material_falso)

    escribir_original = revalidacion_documental._escribir_filas_completas
    otro_escritor_dentro_del_lock = threading.Event()
    otro_escritor_puede_escribir = threading.Event()

    def escribir_con_pausa(ruta, filas):
        otro_escritor_dentro_del_lock.set()
        otro_escritor_puede_escribir.wait(timeout=5)
        escribir_original(ruta, filas)

    monkeypatch.setattr(revalidacion_documental, "_escribir_filas_completas", escribir_con_pausa)

    resultado_otro_escritor: dict[str, object] = {}

    def correr_otro_escritor():
        resultado_otro_escritor["valor"] = revalidacion_documental.revalidar_tipo_carga_sin_ocr(ruta_dataset=dataset)

    hilo_otro_escritor = threading.Thread(target=correr_otro_escritor)
    hilo_otro_escritor.start()
    assert otro_escritor_dentro_del_lock.wait(timeout=5), "el otro escritor real nunca llegó a tomar el lock"

    monkeypatch.setattr(mobile, "crear_proveedor_ocr", lambda: object())
    monkeypatch.setattr(
        mobile, "procesar_archivo",
        lambda ruta, **kw: {"numero_guia": "900001", "numero_transporte": "0000900000", "cliente": "SODIMAC SA"},
    )

    # El reproceso intenta MIENTRAS el otro escritor real todavía tiene
    # el lock -- debe enterarse con un error explícito, nunca pisar ni
    # perder en silencio la escritura ajena.
    resultado_reproceso = reprocesar_envio_mobile_persistido(repo, envio_id, dataset=dataset)
    assert resultado_reproceso["reproceso_persistido"]["fase"] == FASE_DATASET_REEMPLAZADO
    assert resultado_reproceso["reproceso_persistido"]["estado"] == "FALLIDO"
    assert "SesionOcupadaError" in resultado_reproceso["reproceso_persistido"]["error"]

    otro_escritor_puede_escribir.set()
    hilo_otro_escritor.join(timeout=5)
    assert resultado_otro_escritor["valor"]["guias_actualizadas"] == ["100001"]

    # Reintento del reproceso, ya sin contención -- converge igual que
    # cualquier caller real ante un lock ocupado.
    resultado_reintento = reprocesar_envio_mobile_persistido(repo, envio_id, dataset=dataset)
    assert resultado_reintento["reproceso_persistido"]["fase"] == "COMPLETADO"

    filas = _leer_filas_dataset(dataset)
    assert len(filas) == 2
    filas_por_archivo = {f["archivo"]: f for f in filas}
    # La actualización del OTRO escritor real nunca se perdió.
    assert filas_por_archivo["mobile/otro-envio/original.jpg"]["tipo_carga"] == "ROLLOS"
    # Y el reproceso, reintentado, también aplicó la suya -- ninguna de
    # las dos escrituras se pisó ni se perdió.
    assert filas_por_archivo[identificador]["cliente"] == "SODIMAC SA"


# ============================================================
# 9. Microcorrección (Codex, ronda 6) -- Problema A: nunca tratar como
#    "fallo antes del reemplazo" una situación donde el dataset ya pudo
#    cambiar; Problema B: nunca borrar el journal antes de que COMPLETADO
#    quede durable; Problema C: lock común TAMBIÉN en aplicar_decision_obra.
# ============================================================


def test_dataset_reemplazado_con_fallo_al_escribir_journal_no_restaura_estado_previo(tmp_path: Path, monkeypatch) -> None:
    """Problema A: si por cualquier motivo el dataset queda reemplazado
    mientras la escritura del journal falla (el orden journal-antes-que-
    dataset reduce esta ventana, pero la semántica de recuperación no
    puede depender ciegamente de él -- se fuerza la peor combinación
    posible acá para probar la RED DE SEGURIDAD, no el camino feliz), el
    `except` debe reconocerlo por EVIDENCIA (huella del dataset) y nunca
    tratarlo como "antes del reemplazo": nunca restaura `estado_previo`
    encima de los datos nuevos."""
    import atlas_core.mobile as mobile

    repo, envio_id = _recibir(tmp_path)
    dataset = tmp_path / "operacion/actual/analisis_completo_guias.csv"
    identificador = f"mobile/{envio_id}/original.jpg"
    _dataset_con_filas(dataset, [_fila_vieja(identificador, cliente="CLIENTE VIEJO SA")])

    # Estado previo REAL (un procesamiento anterior exitoso) -- si el
    # fallo se tratara mal, se vería restaurado tal cual encima de los
    # datos nuevos.
    registro_previo = repo.cargar(envio_id)
    registro_previo.update({
        "estado": "ASOCIADO",
        "datos_ocr": {"numero_guia": "900001", "cliente": "CLIENTE VIEJO SA"},
        "resultado_asociacion": {"estado": "ASOCIADO_AUTOMATICAMENTE", "numero_transporte": "0000900000", "numero_guia": "900001"},
        "atlas_ia": {"llamadas": 0}, "archivo_dataset": identificador, "error": "",
    })
    repo.guardar(envio_id, registro_previo)

    monkeypatch.setattr(mobile, "crear_proveedor_ocr", lambda: object())
    monkeypatch.setattr(
        mobile, "procesar_archivo",
        lambda ruta, **kw: {"numero_guia": "900001", "numero_transporte": "0000900000", "cliente": "SODIMAC SA", "rut_cliente": "96.792.430-K"},
    )

    def journal_falla_tras_dejar_el_dataset_ya_reemplazado(dataset_arg, identificador_arg, entrada):
        if entrada is not None:
            # Simula la PEOR ventana posible: el dataset queda con la
            # fila nueva (misma construcción que el código real) ANTES
            # de que este intento de journal termine de fallar.
            datos_ocr = entrada["datos_ocr"]
            fila = {columna: str(datos_ocr.get(columna, "")) for columna in COLUMNAS}
            fila.update(
                archivo=identificador_arg,
                estado_procesamiento=str(datos_ocr.get("estado_procesamiento") or "OK"), error="",
            )
            filas_actuales = _leer_filas_dataset(dataset_arg)
            for indice, existente in enumerate(filas_actuales):
                if existente.get("archivo") == identificador_arg:
                    filas_actuales[indice] = fila
            _dataset_con_filas(dataset_arg, filas_actuales)
        raise OSError("disco lleno (simulado) escribiendo el journal")

    # Ronda 7: la escritura de la entrada NUEVA (dentro de la fase
    # DATASET_REEMPLAZADO) corre vía la variante `_sin_lock` -- ya está
    # dentro del lock común, así que es esa función la que hay que
    # interceptar acá (el wrapper protegido `_escribir_entrada_journal_
    # reproceso` es para los OTROS 3 callers, que no sostienen el lock).
    monkeypatch.setattr(
        mobile, "_escribir_entrada_journal_reproceso_sin_lock", journal_falla_tras_dejar_el_dataset_ya_reemplazado,
    )

    with pytest.raises(ErrorEnvioMobile, match="journal"):
        reprocesar_envio_mobile_persistido(repo, envio_id, dataset=dataset)

    # El dataset quedó con los datos NUEVOS -- nunca se revierte.
    filas = _leer_filas_dataset(dataset)
    assert filas[0]["cliente"] == "SODIMAC SA"

    # El envío en disco NUNCA vuelve a mostrar el estado previo encima de
    # los datos nuevos.
    registro_en_disco = repo.cargar(envio_id)
    assert registro_en_disco["datos_ocr"]["cliente"] == "SODIMAC SA"
    assert registro_en_disco["estado"] != "ASOCIADO"
    assert registro_en_disco["reproceso_persistido"]["fase"] == FASE_DATASET_REEMPLAZADO
    assert registro_en_disco["reproceso_persistido"]["estado"] == "FALLIDO_JOURNAL"
    assert "journal" in registro_en_disco["reproceso_persistido"]["error"]


def test_fallo_guardando_completado_antes_de_borrar_journal_conserva_journal_y_deja_derivados_ya_regenerados(tmp_path: Path, monkeypatch) -> None:
    """Problema B: si el guardado final de COMPLETADO falla, el journal
    NUNCA se borra antes -- sigue vigente para que una reejecución no
    repita OCR ni duplique nada, aunque los derivados (decisiones_
    pendientes.json) ya se hayan regenerado correctamente en disco."""
    import atlas_core.mobile as mobile

    repo, envio_id = _recibir(tmp_path)
    catalogos = _catalogos_minimos(tmp_path / "catalogos_privados")
    dataset = tmp_path / "operacion/actual/analisis_completo_guias.csv"
    identificador = f"mobile/{envio_id}/original.jpg"
    _dataset_con_filas(dataset, [_fila_vieja(identificador)])

    monkeypatch.setattr(mobile, "crear_proveedor_ocr", lambda: object())
    llamadas_ocr = {"n": 0}

    def procesar_archivo_contador(ruta, **kw):
        llamadas_ocr["n"] += 1
        return {"numero_guia": "900001", "numero_transporte": "0000900000", "cliente": "SODIMAC SA", "rut_cliente": "96.792.430-K"}

    monkeypatch.setattr(mobile, "procesar_archivo", procesar_archivo_contador)

    guardar_original = repo.guardar

    def guardar_roto_en_completado(envio_id_arg, registro):
        diagnostico = registro.get("reproceso_persistido") or {}
        if diagnostico.get("fase") == mobile.FASE_COMPLETADO and diagnostico.get("estado") == "COMPLETADO":
            raise OSError("disco lleno (simulado) justo en el checkpoint final")
        guardar_original(envio_id_arg, registro)

    monkeypatch.setattr(repo, "guardar", guardar_roto_en_completado)

    with pytest.raises(ErrorEnvioMobile, match="journal"):
        reprocesar_envio_mobile_persistido(repo, envio_id, dataset=dataset, carpeta_catalogos=catalogos)
    assert llamadas_ocr["n"] == 1

    # Los derivados YA se regeneraron en disco -- eso no se revierte.
    assert (dataset.parent / "decisiones_pendientes.json").is_file()

    # El journal NO se borró -- sigue vigente para una reejecución.
    journal = json.loads((dataset.parent / mobile.NOMBRE_JOURNAL_REPROCESO_PERSISTIDO).read_text(encoding="utf-8"))
    assert identificador in journal

    # `envio.json` mismo no alcanzó a reflejar COMPLETADO.
    registro_en_disco = repo.cargar(envio_id)
    assert not (
        registro_en_disco["reproceso_persistido"]["fase"] == mobile.FASE_COMPLETADO
        and registro_en_disco["reproceso_persistido"]["estado"] == "COMPLETADO"
    )

    # Reentrada: se "repara" el guardado -- reanuda SIN repetir OCR.
    monkeypatch.setattr(repo, "guardar", guardar_original)
    resultado = reprocesar_envio_mobile_persistido(repo, envio_id, dataset=dataset, carpeta_catalogos=catalogos)

    assert llamadas_ocr["n"] == 1, "no debía repetir OCR -- debía reanudar desde el journal"
    assert resultado["reproceso_persistido"]["fase"] == "COMPLETADO"
    assert resultado["reproceso_persistido"]["estado"] == "COMPLETADO"

    # El journal ya se limpió -- éxito total.
    journal_final = json.loads((dataset.parent / mobile.NOMBRE_JOURNAL_REPROCESO_PERSISTIDO).read_text(encoding="utf-8"))
    assert identificador not in journal_final


def test_fallo_borrando_journal_despues_de_completado_es_inocuo_y_reentrada_solo_limpia(tmp_path: Path, monkeypatch) -> None:
    """Problema B: si sólo la limpieza del journal (best-effort) falla
    DESPUÉS de que COMPLETADO ya quedó durablemente persistido, es
    inocuo -- una reejecución reconoce que ya está completado (misma
    huella de fila) y sólo reintenta la limpieza, sin reprocesar
    absolutamente nada (ni OCR, ni dataset, ni derivados)."""
    import atlas_core.mobile as mobile

    repo, envio_id = _recibir(tmp_path)
    dataset = tmp_path / "operacion/actual/analisis_completo_guias.csv"
    identificador = f"mobile/{envio_id}/original.jpg"
    _dataset_con_filas(dataset, [_fila_vieja(identificador)])

    monkeypatch.setattr(mobile, "crear_proveedor_ocr", lambda: object())
    llamadas_ocr = {"n": 0}

    def procesar_archivo_contador(ruta, **kw):
        llamadas_ocr["n"] += 1
        return {"numero_guia": "900001", "numero_transporte": "0000900000", "cliente": "SODIMAC SA", "rut_cliente": "96.792.430-K"}

    monkeypatch.setattr(mobile, "procesar_archivo", procesar_archivo_contador)

    limpieza_original = mobile._escribir_entrada_journal_reproceso

    def limpieza_rota_solo_al_borrar(dataset_arg, identificador_arg, entrada):
        if entrada is None:
            raise OSError("disco lleno (simulado) borrando el journal")
        limpieza_original(dataset_arg, identificador_arg, entrada)

    monkeypatch.setattr(mobile, "_escribir_entrada_journal_reproceso", limpieza_rota_solo_al_borrar)

    # No debe propagar ningún error -- la limpieza es best-effort.
    resultado = reprocesar_envio_mobile_persistido(repo, envio_id, dataset=dataset)
    assert resultado["reproceso_persistido"]["fase"] == "COMPLETADO"
    assert llamadas_ocr["n"] == 1

    # El journal quedó huérfano (limpieza fallida) -- inocuo.
    journal = json.loads((dataset.parent / mobile.NOMBRE_JOURNAL_REPROCESO_PERSISTIDO).read_text(encoding="utf-8"))
    assert identificador in journal

    # Reentrada: reconoce que ya está COMPLETADO (misma huella) --
    # reintenta ÚNICAMENTE la limpieza, sin repetir OCR ni ninguna otra
    # fase.
    monkeypatch.setattr(mobile, "_escribir_entrada_journal_reproceso", limpieza_original)
    resultado_reentrada = reprocesar_envio_mobile_persistido(repo, envio_id, dataset=dataset)

    assert llamadas_ocr["n"] == 1, "la reentrada no debía reprocesar nada -- sólo limpiar el journal"
    assert resultado_reentrada == repo.cargar(envio_id)
    journal_final = json.loads((dataset.parent / mobile.NOMBRE_JOURNAL_REPROCESO_PERSISTIDO).read_text(encoding="utf-8"))
    assert identificador not in journal_final


def test_concurrencia_reproceso_persistido_vs_aplicar_decision_obra_real_no_pierde_actualizaciones(tmp_path: Path, monkeypatch) -> None:
    """Hallazgo #4 (Codex, ronda 6 -- bloqueante): `aplicar_decision_obra`
    ahora TAMBIÉN adquiere el lock común ("revalidacion_dataset")
    alrededor de sus escrituras directas -- un reproceso persistido y una
    aplicación de decisión REAL y concurrentes sobre filas DISTINTAS del
    MISMO dataset nunca se pisan: ambas actualizaciones sobreviven."""
    import atlas_core.revalidacion_documental as revalidacion_documental
    from atlas_core.aplicacion_decisiones import aplicar_decision_obra
    from atlas_core.decisiones_pendientes import detectar_decision_cliente_ausente, generar_artefacto
    import atlas_core.mobile as mobile

    raiz = tmp_path / "Atlas"
    catalogos = raiz / "catalogos_privados"
    actual = raiz / "operacion" / "actual"
    catalogos.mkdir(parents=True)
    actual.mkdir(parents=True)
    for nombre, contenido in {
        "clientes.json": {"version_formato": 1, "clientes": []},
        "empresas.json": {},
        "vehiculos.json": {"version": 1, "vehiculos": []},
        "obras_destinos.json": {"version_formato": 1, "obras": [], "relaciones": []},
        "destinos_maestros.json": {"version_formato": 1, "destinos": []},
        "plantas.json": {"version_formato": 1, "plantas": []},
    }.items():
        (catalogos / nombre).write_text(json.dumps(contenido), encoding="utf-8")

    repo = RepositorioEnviosMobile(raiz)
    envio_id = str(uuid.uuid4())
    repo.recibir(
        envio_id=envio_id, imagen=b"foto", mime="image/jpeg",
        metadata={"chofer_id": "c1", "tipo_novedad": "", "guia_firmada_correo": False, "planta_origen_informada": "AZA_COLINA"},
    )
    identificador = f"mobile/{envio_id}/original.jpg"

    dataset = actual / "analisis_completo_guias.csv"
    fila_cliente_ausente = {c: "" for c in COLUMNAS}
    fila_cliente_ausente.update({
        "archivo": "472238.jpeg", "estado_procesamiento": "OK", "numero_guia": "472238",
        "numero_transporte": "0000354443", "fecha": "20-08-2026", "chofer": "WLADIMIR AGUILAR",
        "cliente": "No encontrado", "obra_destino": "VISTA CLARA 2351 CERRILLOS",
        "indicador_revision": "REVISAR", "motivos_revision_documento": "CLIENTE_AUSENTE",
        "planta_origen_id": "planta-colina", "planta_origen_nombre": "AZA COLINA",
    })
    _dataset_con_filas(dataset, [fila_cliente_ausente, _fila_vieja(identificador)])

    decision = detectar_decision_cliente_ausente(archivo="472238.jpeg", fila=fila_cliente_ausente)
    assert decision is not None
    generar_artefacto(
        ruta_dataset=dataset, carpeta_catalogos=catalogos, decisiones=[decision],
        ruta_salida=actual / "decisiones_pendientes.json",
    )

    monkeypatch.setattr(mobile, "crear_proveedor_ocr", lambda: object())
    monkeypatch.setattr(
        mobile, "procesar_archivo",
        lambda ruta, **kw: {"numero_guia": "900001", "numero_transporte": "0000900000", "cliente": "SODIMAC SA"},
    )

    escribir_original = revalidacion_documental._escribir_filas_completas
    primera_escritura_dentro_del_lock = threading.Event()
    primera_escritura_puede_continuar = threading.Event()
    ya_pauso_una_vez = threading.Event()

    def escribir_con_pausa_una_sola_vez(ruta, filas):
        if not ya_pauso_una_vez.is_set():
            ya_pauso_una_vez.set()
            primera_escritura_dentro_del_lock.set()
            primera_escritura_puede_continuar.wait(timeout=5)
        escribir_original(ruta, filas)

    monkeypatch.setattr(revalidacion_documental, "_escribir_filas_completas", escribir_con_pausa_una_sola_vez)

    resultado_decision: dict[str, object] = {}

    def correr_aplicar_decision():
        resultado_decision["valor"] = aplicar_decision_obra(
            raiz_atlas=raiz, decision_id=decision["decision_id"],
            accion="REGISTRAR_CLIENTE_MANUAL", razon_social_manual="COMERCIAL NUEVA SPA",
            rut_manual="76086428-5",
        )

    hilo_decision = threading.Thread(target=correr_aplicar_decision)
    hilo_decision.start()
    assert primera_escritura_dentro_del_lock.wait(timeout=5), "aplicar_decision_obra nunca llegó a tomar el lock común del dataset"

    # El reproceso intenta MIENTRAS aplicar_decision_obra todavía tiene
    # el lock común tomado -- debe enterarse con un error explícito,
    # nunca pisar ni perder en silencio la escritura ajena.
    resultado_reproceso_primer_intento = reprocesar_envio_mobile_persistido(repo, envio_id, dataset=dataset)
    assert resultado_reproceso_primer_intento["reproceso_persistido"]["fase"] == FASE_DATASET_REEMPLAZADO
    assert resultado_reproceso_primer_intento["reproceso_persistido"]["estado"] == "FALLIDO"
    assert "SesionOcupadaError" in resultado_reproceso_primer_intento["reproceso_persistido"]["error"]

    primera_escritura_puede_continuar.set()
    hilo_decision.join(timeout=10)
    assert resultado_decision["valor"]["ok"] is True

    # Reintento del reproceso, ya sin contención.
    resultado_reproceso_reintento = reprocesar_envio_mobile_persistido(repo, envio_id, dataset=dataset)
    assert resultado_reproceso_reintento["reproceso_persistido"]["fase"] == "COMPLETADO"

    # Ninguna de las dos actualizaciones se perdió ni se pisó.
    filas = _leer_filas_dataset(dataset)
    assert len(filas) == 2
    filas_por_archivo = {f["archivo"]: f for f in filas}
    assert filas_por_archivo["472238.jpeg"]["cliente"] == "COMERCIAL NUEVA SPA"
    assert filas_por_archivo[identificador]["cliente"] == "SODIMAC SA"


# ============================================================
# 10. Microfix (Codex, ronda 7 -- bloqueante): las 4 mutaciones del
#     journal (`.reproceso_persistido_journal.json`) comparten el MISMO
#     lock común del dataset -- ninguna corre sin protección.
# ============================================================


def test_limpieza_de_journal_concurrente_con_escritura_de_otro_identificador_nunca_pierde_la_entrada_ajena(tmp_path: Path, monkeypatch) -> None:
    """El race exacto que reportó Codex: reproceso A lee el journal para
    borrar su propia entrada, reproceso B agrega/actualiza la SUYA
    mientras tanto, A escribe de vuelta su copia (ya obsoleta) -- sin
    lock, la entrada de B desaparecería en silencio. Con el lock común,
    B se entera con un error explícito mientras A tiene el lock, y su
    entrada sobrevive intacta al reintentar."""
    import atlas_core.mobile as mobile

    dataset = tmp_path / "operacion/actual/analisis_completo_guias.csv"
    dataset.parent.mkdir(parents=True, exist_ok=True)
    identificador_a = "mobile/envio-a/original.jpg"
    identificador_b = "mobile/envio-b/original.jpg"

    # A ya tiene una entrada -- se va a limpiar (delete, `entrada=None`).
    mobile._escribir_entrada_journal_reproceso(dataset, identificador_a, {"envio_id": "a", "fila_hash": "hash-a"})

    escribir_original = mobile._escribir_entrada_journal_reproceso_sin_lock
    dentro_del_lock = threading.Event()
    puede_continuar = threading.Event()

    def escribir_con_pausa(dataset_arg, identificador_arg, entrada):
        if identificador_arg == identificador_a and entrada is None:
            dentro_del_lock.set()
            puede_continuar.wait(timeout=5)
        escribir_original(dataset_arg, identificador_arg, entrada)

    monkeypatch.setattr(mobile, "_escribir_entrada_journal_reproceso_sin_lock", escribir_con_pausa)

    hilo_a = threading.Thread(
        target=lambda: mobile._escribir_entrada_journal_reproceso(dataset, identificador_a, None),
    )
    hilo_a.start()
    assert dentro_del_lock.wait(timeout=5), "A nunca llegó a tomar el lock común del journal"

    # B intenta escribir SU PROPIA entrada MIENTRAS A todavía tiene el
    # lock tomado -- debe enterarse con un error explícito, nunca perder
    # su actualización en silencio.
    with pytest.raises(SesionOcupadaError):
        mobile._escribir_entrada_journal_reproceso(dataset, identificador_b, {"envio_id": "b", "fila_hash": "hash-b"})

    puede_continuar.set()
    hilo_a.join(timeout=5)

    # Reintento de B, ya sin contención -- converge igual que cualquier
    # caller real ante un lock ocupado.
    mobile._escribir_entrada_journal_reproceso(dataset, identificador_b, {"envio_id": "b", "fila_hash": "hash-b"})

    journal_final = mobile._leer_journal_reproceso(dataset)
    assert identificador_a not in journal_final  # A se limpió correctamente
    assert identificador_b in journal_final  # B nunca se perdió ni se pisó
    assert journal_final[identificador_b]["envio_id"] == "b"


def test_dos_limpiezas_de_journal_concurrentes_de_identificadores_distintos_no_se_pisan(tmp_path: Path, monkeypatch) -> None:
    """Dos limpiezas (delete) concurrentes de identificadores DISTINTOS
    tampoco se pisan -- misma protección, sin importar si la mutación es
    crear/actualizar o eliminar."""
    import atlas_core.mobile as mobile

    dataset = tmp_path / "operacion/actual/analisis_completo_guias.csv"
    dataset.parent.mkdir(parents=True, exist_ok=True)
    identificador_a = "mobile/envio-a/original.jpg"
    identificador_b = "mobile/envio-b/original.jpg"

    mobile._escribir_entrada_journal_reproceso(dataset, identificador_a, {"envio_id": "a", "fila_hash": "hash-a"})
    mobile._escribir_entrada_journal_reproceso(dataset, identificador_b, {"envio_id": "b", "fila_hash": "hash-b"})

    escribir_original = mobile._escribir_entrada_journal_reproceso_sin_lock
    dentro_del_lock = threading.Event()
    puede_continuar = threading.Event()

    def escribir_con_pausa(dataset_arg, identificador_arg, entrada):
        if identificador_arg == identificador_a:
            dentro_del_lock.set()
            puede_continuar.wait(timeout=5)
        escribir_original(dataset_arg, identificador_arg, entrada)

    monkeypatch.setattr(mobile, "_escribir_entrada_journal_reproceso_sin_lock", escribir_con_pausa)

    hilo_a = threading.Thread(
        target=lambda: mobile._escribir_entrada_journal_reproceso(dataset, identificador_a, None),
    )
    hilo_a.start()
    assert dentro_del_lock.wait(timeout=5), "A nunca llegó a tomar el lock común del journal"

    with pytest.raises(SesionOcupadaError):
        mobile._escribir_entrada_journal_reproceso(dataset, identificador_b, None)

    puede_continuar.set()
    hilo_a.join(timeout=5)

    # Reintento de B, ya sin contención.
    mobile._escribir_entrada_journal_reproceso(dataset, identificador_b, None)

    journal_final = mobile._leer_journal_reproceso(dataset)
    assert identificador_a not in journal_final
    assert identificador_b not in journal_final


# ============================================================
# 11. IMPLEMENTACIÓN INTEGRAL, Fase 1 -- lock POR ENVÍO
#     (`mobile_<envio_id>`): dos operaciones sobre el MISMO envío nunca
#     se pisan; envíos distintos corren en paralelo sin contención.
# ============================================================


def test_mobile_normal_vs_reproceso_mismo_envio_contencion_explicita_sin_perdida(tmp_path: Path, monkeypatch) -> None:
    """#1 (Fase 1): `procesar_envio_mobile` y `reprocesar_envio_mobile_
    persistido` sobre el MISMO envío nunca se pisan -- mientras uno tiene
    el lock por envío tomado, el otro se entera con `SesionOcupadaError`
    ANTES de tocar nada; reintentado después, converge sin pérdida."""
    import atlas_core.mobile as mobile

    repo, envio_id = _recibir(tmp_path)
    dataset = tmp_path / "operacion/actual/analisis_completo_guias.csv"
    identificador = f"mobile/{envio_id}/original.jpg"
    _dataset_con_filas(dataset, [_fila_vieja(identificador, cliente="CLIENTE VIEJO SA")])

    monkeypatch.setattr(mobile, "crear_proveedor_ocr", lambda: object())

    dentro_del_lock = threading.Event()
    puede_continuar = threading.Event()

    def procesar_archivo_pausado(ruta, **kw):
        dentro_del_lock.set()
        puede_continuar.wait(timeout=5)
        return {"numero_guia": "900001", "numero_transporte": "0000900000", "cliente": "SODIMAC SA"}

    monkeypatch.setattr(mobile, "procesar_archivo", procesar_archivo_pausado)

    hilo_mobile = threading.Thread(
        target=lambda: mobile.procesar_envio_mobile(repo, envio_id, dataset=dataset),
    )
    hilo_mobile.start()
    assert dentro_del_lock.wait(timeout=5), "procesar_envio_mobile nunca llegó a tomar el lock por envío"

    # El reproceso intenta MIENTRAS Mobile normal todavía tiene el lock
    # de ESTE envío tomado -- debe enterarse con un error explícito,
    # nunca pisar ni perder en silencio la operación en curso.
    with pytest.raises(SesionOcupadaError):
        mobile.reprocesar_envio_mobile_persistido(repo, envio_id, dataset=dataset)

    puede_continuar.set()
    hilo_mobile.join(timeout=5)

    registro_tras_mobile = repo.cargar(envio_id)
    assert registro_tras_mobile["estado"] != "ERROR"

    # Reintento del reproceso, ya sin contención -- converge igual que
    # cualquier caller real ante un lock ocupado.
    monkeypatch.setattr(
        mobile, "procesar_archivo",
        lambda ruta, **kw: {"numero_guia": "900001", "numero_transporte": "0000900000", "cliente": "SODIMAC REPROCESADO SA"},
    )
    resultado_reproceso = mobile.reprocesar_envio_mobile_persistido(repo, envio_id, dataset=dataset)
    assert resultado_reproceso["reproceso_persistido"]["fase"] == "COMPLETADO"

    filas = _leer_filas_dataset(dataset)
    assert len(filas) == 1
    assert filas[0]["cliente"] == "SODIMAC REPROCESADO SA"


def test_reproceso_de_envios_distintos_progresan_sin_lock_global_innecesario(tmp_path: Path, monkeypatch) -> None:
    """#3 (Fase 1): dos reprocesos de envíos DISTINTOS corren en paralelo
    sin ninguna contención entre sí -- el lock es por `envio_id`, nunca
    global."""
    import atlas_core.mobile as mobile

    repo = RepositorioEnviosMobile(tmp_path)
    envio_id_1 = str(uuid.uuid4())
    envio_id_2 = str(uuid.uuid4())
    for envio_id in (envio_id_1, envio_id_2):
        repo.recibir(
            envio_id=envio_id, imagen=b"foto", mime="image/jpeg",
            metadata={"chofer_id": "c1", "tipo_novedad": "", "guia_firmada_correo": False, "planta_origen_informada": "AZA_COLINA"},
        )
    dataset = tmp_path / "operacion/actual/analisis_completo_guias.csv"
    identificador_1 = f"mobile/{envio_id_1}/original.jpg"
    identificador_2 = f"mobile/{envio_id_2}/original.jpg"
    _dataset_con_filas(dataset, [
        _fila_vieja(identificador_1, numero_guia="900001", numero_transporte="0000900001"),
        _fila_vieja(identificador_2, numero_guia="900002", numero_transporte="0000900002"),
    ])

    monkeypatch.setattr(mobile, "crear_proveedor_ocr", lambda: object())

    dentro_del_lock_1 = threading.Event()
    puede_continuar_1 = threading.Event()

    def procesar_archivo_pausado_1(ruta, **kw):
        dentro_del_lock_1.set()
        puede_continuar_1.wait(timeout=5)
        return {"numero_guia": "900001", "numero_transporte": "0000900001", "cliente": "PRIMER CLIENTE SA"}

    monkeypatch.setattr(mobile, "procesar_archivo", procesar_archivo_pausado_1)

    hilo_1 = threading.Thread(
        target=lambda: mobile.reprocesar_envio_mobile_persistido(repo, envio_id_1, dataset=dataset),
    )
    hilo_1.start()
    assert dentro_del_lock_1.wait(timeout=5), "el reproceso 1 nunca llegó a tomar su lock por envío"

    # El envío 2 es COMPLETAMENTE distinto -- debe completar sin ninguna
    # contención, aunque el envío 1 todavía esté "en vuelo" con SU propio
    # lock tomado.
    monkeypatch.setattr(
        mobile, "procesar_archivo",
        lambda ruta, **kw: {"numero_guia": "900002", "numero_transporte": "0000900002", "cliente": "SEGUNDO CLIENTE SA"},
    )
    resultado_2 = mobile.reprocesar_envio_mobile_persistido(repo, envio_id_2, dataset=dataset)
    assert resultado_2["reproceso_persistido"]["fase"] == "COMPLETADO"

    puede_continuar_1.set()
    hilo_1.join(timeout=5)

    filas = _leer_filas_dataset(dataset)
    assert len(filas) == 2
    filas_por_archivo = {f["archivo"]: f for f in filas}
    assert filas_por_archivo[identificador_1]["cliente"] == "PRIMER CLIENTE SA"
    assert filas_por_archivo[identificador_2]["cliente"] == "SEGUNDO CLIENTE SA"


def test_mobile_normal_append_vs_reemplazo_completo_concurrente_ninguna_fila_desaparece(tmp_path: Path, monkeypatch) -> None:
    """#4 (Fase 1): el append de `procesar_envio_mobile` corre ahora bajo
    el lock físico común del dataset -- mientras un reemplazo completo
    REAL (`revalidar_tipo_carga_sin_ocr`, no un doble simulado) lo tiene
    tomado, el append se entera con un error explícito (nunca escribe a
    ciegas); reintentado después, ninguna fila -- ni la del reemplazo, ni
    la de Mobile -- desaparece."""
    import atlas_core.revalidacion_documental as revalidacion_documental
    import atlas_core.mobile as mobile

    repo, envio_id = _recibir(tmp_path)
    dataset = tmp_path / "operacion/actual/analisis_completo_guias.csv"
    identificador = f"mobile/{envio_id}/original.jpg"
    otra_fila = _fila_vieja(
        "mobile/otro-envio/original.jpg", numero_guia="100001", numero_transporte="0000100001",
        tipo_carga="", descripcion_material="ROLLOS DE ACERO",
    )
    _dataset_con_filas(dataset, [otra_fila])

    import atlas_core.clasificador_material as clasificador_material

    class _FakeTipoCarga:
        def __init__(self, value: str) -> None:
            self.value = value

    def _clasificar_material_falso(descripcion: str) -> _FakeTipoCarga:
        return _FakeTipoCarga("ROLLOS" if "ROLLOS" in str(descripcion or "").upper() else "NO DETERMINADO")

    monkeypatch.setattr(clasificador_material, "clasificar_material", _clasificar_material_falso)

    escribir_original = revalidacion_documental._escribir_filas_completas
    dentro_del_lock = threading.Event()
    puede_continuar = threading.Event()

    def escribir_con_pausa(ruta, filas):
        dentro_del_lock.set()
        puede_continuar.wait(timeout=5)
        escribir_original(ruta, filas)

    monkeypatch.setattr(revalidacion_documental, "_escribir_filas_completas", escribir_con_pausa)

    resultado_revalidacion: dict[str, object] = {}

    def correr_revalidacion():
        resultado_revalidacion["valor"] = revalidacion_documental.revalidar_tipo_carga_sin_ocr(ruta_dataset=dataset)

    hilo_revalidacion = threading.Thread(target=correr_revalidacion)
    hilo_revalidacion.start()
    assert dentro_del_lock.wait(timeout=5), "la revalidación real nunca llegó a tomar el lock del dataset"

    monkeypatch.setattr(mobile, "crear_proveedor_ocr", lambda: object())
    monkeypatch.setattr(
        mobile, "procesar_archivo",
        lambda ruta, **kw: {"numero_guia": "900001", "numero_transporte": "0000900000", "cliente": "SODIMAC SA"},
    )

    # Mobile intenta MIENTRAS la revalidación real todavía tiene el lock
    # del dataset tomado -- el append se entera con un error explícito
    # (nunca escribe a ciegas ni pierde el chequeo de duplicado).
    resultado_mobile = mobile.procesar_envio_mobile(repo, envio_id, dataset=dataset)
    assert resultado_mobile["estado"] == "ERROR"
    assert "SesionOcupadaError" in resultado_mobile["error"]
    assert resultado_mobile.get("archivo_dataset", "") == ""

    puede_continuar.set()
    hilo_revalidacion.join(timeout=5)
    assert resultado_revalidacion["valor"]["guias_actualizadas"] == ["100001"]

    # Reintento de Mobile, ya sin contención.
    resultado_reintento = mobile.procesar_envio_mobile(repo, envio_id, dataset=dataset)
    assert resultado_reintento["estado"] != "ERROR"
    assert resultado_reintento["archivo_dataset"] == identificador

    filas = _leer_filas_dataset(dataset)
    assert len(filas) == 2
    filas_por_archivo = {f["archivo"]: f for f in filas}
    # La actualización de la revalidación real nunca se perdió.
    assert filas_por_archivo["mobile/otro-envio/original.jpg"]["tipo_carga"] == "ROLLOS"
    # Y Mobile, reintentado, sí agregó su propia fila -- ninguna de las
    # dos escrituras se pisó ni se perdió.
    assert filas_por_archivo[identificador]["cliente"] == "SODIMAC SA"


# ============================================================
# 12. IMPLEMENTACIÓN INTEGRAL, Fase 2 -- publicación VERSIONADA de
#     reporte + estado_operación: criterios C/D/E.
# ============================================================


def test_c_d_e_generacion_de_reporte_mientras_dataset_cambia_no_publica_version_vieja_y_converge_despues(tmp_path, monkeypatch) -> None:
    """C: si el dataset cambia MIENTRAS `revalidar_y_regenerar_reporte`
    genera el reporte, ese reporte NUNCA se publica como vigente (ni la
    carpeta queda huérfana, ni `estado_operacion.json` se toca).
    D: la siguiente corrida (natural, idempotente) converge y publica el
    reporte de la versión NUEVA.
    E: `estado_operacion.json` nunca declara una huella de dataset que no
    corresponda EXACTAMENTE al `reporte_vigente` que señala."""
    import atlas_core.revalidacion_documental as revalidacion_documental
    from atlas_core.almacenamiento_portable import leer_estado_operacion

    catalogos = _catalogos_minimos(tmp_path / "catalogos_privados")
    dataset = tmp_path / "operacion/actual/analisis_completo_guias.csv"
    # `motivos_revision_documento` con un motivo real -- necesario para
    # que `revalidar_y_regenerar_reporte` detecte algo que regenerar y
    # llegue hasta `generar_reporte_viajes` (mismo patrón que el resto
    # de este archivo, ver `DESTINO_CONTAMINADO_POR_OTRA_SECCION`).
    _dataset_con_filas(dataset, [_fila_vieja(
        "mobile/g/original.jpg", cliente="CLIENTE ORIGINAL SA",
        indicador_revision="REVISAR", estado_documental="REQUIERE_REVISION",
        motivos_revision_documento="DESTINO_CONTAMINADO_POR_OTRA_SECCION",
    )])
    # Semilla de decisiones_pendientes.json -- necesario para que
    # `revalidar_y_regenerar_reporte` detecte cambio de firma de bandeja
    # y llegue hasta `generar_reporte_viajes` (mismo patrón que
    # `test_derivados_decisiones_asociacion_reporte_y_estado_operacion_se_regeneran`).
    generar_artefacto(
        ruta_dataset=dataset, carpeta_catalogos=catalogos, decisiones=[],
        ruta_salida=dataset.parent / "decisiones_pendientes.json",
    )

    generar_original = revalidacion_documental.generar_reporte_viajes

    def generar_con_cambio_concurrente(dataset_arg, salida, **kwargs):
        # Simula: OTRO proceso real (una decisión, una revalidación)
        # cambia el dataset justo MIENTRAS este reporte se genera.
        filas = _leer_filas_dataset(dataset_arg)
        filas[0]["cliente"] = "CLIENTE CAMBIADO POR OTRO PROCESO"
        _dataset_con_filas(dataset_arg, filas)
        return generar_original(dataset_arg, salida, **kwargs)

    monkeypatch.setattr(revalidacion_documental, "generar_reporte_viajes", generar_con_cambio_concurrente)

    resultado_1 = revalidacion_documental.revalidar_y_regenerar_reporte(
        raiz_atlas=tmp_path, nombre_carpeta_reporte="reporte_1",
    )
    # C -- nunca se publica como vigente.
    assert resultado_1["reporte_regenerado"] is False
    assert resultado_1.get("motivo") == "DATASET_AVANZO_DURANTE_GENERACION_REPORTE"
    assert not (tmp_path / "reportes" / "reporte_1").exists()
    assert leer_estado_operacion(raiz=tmp_path) is None

    # D -- la siguiente corrida (ya sin el cambio concurrente en curso)
    # converge y publica el reporte de la versión YA estable.
    monkeypatch.setattr(revalidacion_documental, "generar_reporte_viajes", generar_original)
    resultado_2 = revalidacion_documental.revalidar_y_regenerar_reporte(
        raiz_atlas=tmp_path, nombre_carpeta_reporte="reporte_2",
    )
    assert resultado_2["reporte_regenerado"] is True

    # E -- estado_operación apunta EXACTAMENTE al dataset que produjo ESE
    # reporte -- nunca una huella nueva sobre un reporte viejo, ni
    # viceversa.
    estado = leer_estado_operacion(raiz=tmp_path)
    assert estado is not None
    huella_real = revalidacion_documental._sha256_archivo(dataset)
    assert estado["dataset_sha256"] == huella_real
    assert estado["reporte_vigente"] == "reportes/reporte_2"
    viajes_csv = (tmp_path / estado["reporte_vigente"] / "viajes.csv").read_text(encoding="utf-8-sig")
    assert "CLIENTE CAMBIADO POR OTRO PROCESO" in viajes_csv


def test_g_reproceso_interrumpido_con_lock_huerfano_y_journal_a_medio_camino_converge_en_reentrada(tmp_path: Path, monkeypatch) -> None:
    """Fase 2, criterio G: simula el crash más severo -- el proceso murió
    sosteniendo el lock por envío (que queda huérfano en disco) justo
    después de reemplazar el dataset y journalizar, antes del checkpoint
    de `envio.json`. Una reejecución debe: reconocer el lock huérfano
    como expirado (nunca bloquear para siempre) Y reanudar desde el
    journal sin repetir OCR -- converge sin duplicar ni perder nada."""
    import os
    import time

    import atlas_core.mobile as mobile

    repo, envio_id = _recibir(tmp_path)
    catalogos = _catalogos_minimos(tmp_path / "catalogos_privados")
    dataset = tmp_path / "operacion/actual/analisis_completo_guias.csv"
    identificador = f"mobile/{envio_id}/original.jpg"

    fila_ya_reemplazada = _fila_vieja(
        identificador, cliente="SODIMAC SA", rut_cliente="96.792.430-K",
        numero_guia="900001", numero_transporte="0000900000",
    )
    _dataset_con_filas(dataset, [fila_ya_reemplazada])
    fila_en_disco = _leer_filas_dataset(dataset)[0]
    mobile._escribir_entrada_journal_reproceso(dataset, identificador, {
        "envio_id": envio_id, "reemplazado_en": "2026-09-02T00:00:00+00:00",
        "fila_hash": mobile._hash_fila(fila_en_disco),
        "datos_ocr": {
            "numero_guia": "900001", "numero_transporte": "0000900000",
            "cliente": "SODIMAC SA", "rut_cliente": "96.792.430-K", "archivo": identificador,
        },
        "resultado_asociacion": {"estado": "ASOCIADO_AUTOMATICAMENTE", "numero_transporte": "0000900000", "numero_guia": "900001"},
        "atlas_ia": {"llamadas": 0}, "problema_captura": False, "decisiones_nuevas": [],
    })

    # El proceso "murió" sosteniendo el lock por envío -- se simula
    # creando el archivo de lock a mano, con una marca de tiempo más
    # vieja que la expiración configurada.
    ruta_lock = repo.raiz / f".atlas_lock_mobile_{envio_id}"
    ruta_lock.write_text('{"pid": 0, "host": "crash-simulado"}', encoding="utf-8")
    vieja = time.time() - mobile.TIEMPO_EXPIRACION_LOCK_ENVIO_SEGUNDOS - 60
    os.utime(ruta_lock, (vieja, vieja))

    def ocr_no_debe_llamarse(*args, **kwargs):
        raise AssertionError("OCR no debía volver a ejecutarse -- debía reanudar desde el journal")

    monkeypatch.setattr(mobile, "crear_proveedor_ocr", ocr_no_debe_llamarse)
    monkeypatch.setattr(mobile, "procesar_archivo", ocr_no_debe_llamarse)

    resultado = mobile.reprocesar_envio_mobile_persistido(repo, envio_id, dataset=dataset, carpeta_catalogos=catalogos)

    assert resultado["estado"] != "ERROR"
    assert resultado["reproceso_persistido"]["fase"] == "COMPLETADO"
    # El lock huérfano se reemplazó y se liberó correctamente -- nunca
    # bloqueó para siempre.
    assert not ruta_lock.exists()
    # El journal ya se limpió -- éxito total, sin duplicar ni perder nada.
    journal = mobile._leer_journal_reproceso(dataset)
    assert identificador not in journal
    filas = _leer_filas_dataset(dataset)
    assert len(filas) == 1
    assert filas[0]["cliente"] == "SODIMAC SA"
