"""Bloque MOBILE -> DESKTOP (fix real, caso real 472623/472624): ni
`procesar_envio_mobile` ni `revalidar_asociacion_mobile_sin_ocr`
regeneraban el reporte/`estado_operacion.json` que Desktop realmente
lee -- la fila del documento ya quedaba bien escrita en el dataset,
pero Desktop seguía mostrando un reporte viejo hasta que algún proceso
externo, sin relación con la subida Mobile, volviera a reconciliar.

`servidor_mobile._procesar_y_revalidar` ahora cierra ese hueco llamando
al reconciliador general ya existente (`revalidar_y_regenerar_reporte`)
al terminar cada envío -- nunca un segundo reconciliador paralelo,
nunca bloquea el 202 (corre en el mismo worker de 1 hilo en segundo
plano de siempre)."""
from __future__ import annotations

import csv
import json
import uuid
from pathlib import Path

from atlas_core.almacenamiento_portable import escribir_estado_operacion, leer_estado_operacion
from atlas_core.decisiones_pendientes import generar_artefacto
from atlas_core.mobile import RepositorioEnviosMobile
from atlas_core.procesamiento_masivo import COLUMNAS, _escribir_filas
from atlas_core.reporte_viajes import _sha256_archivo, generar_reporte_viajes
from atlas_core.revalidacion_documental import revalidar_y_regenerar_reporte
from servidor_mobile import _procesar_y_revalidar, _regenerar_reporte_tras_envio_mobile


def _dataset_vacio(ruta: Path) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with ruta.open("w", newline="", encoding="utf-8-sig") as archivo:
        csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";").writeheader()


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


def _recibir(repo: RepositorioEnviosMobile) -> str:
    envio_id = str(uuid.uuid4())
    repo.recibir(
        envio_id=envio_id, imagen=b"foto", mime="image/jpeg",
        metadata={"chofer_id": "c1", "tipo_novedad": "", "guia_firmada_correo": False, "planta_origen_informada": "AZA_COLINA"},
    )
    return envio_id


def _escribir_fila_procesada(dataset: Path, catalogos: Path, *, envio_id: str, numero_guia: str, numero_transporte: str) -> str:
    """Simula lo que YA hace `procesar_envio_mobile` (escribir la fila
    real en el dataset Y publicar/actualizar `decisiones_pendientes.json`
    -- ver ese mismo bloque en atlas_core/mobile.py) -- estos tests
    prueban específicamente la reconciliación de reporte que corre
    DESPUÉS, no el OCR/asociación en sí (eso ya está cubierto en
    test_mobile_guias_v1.py).

    Mismo motivo que el caso real (472624/472623): `DESTINO_CONTAMINADO_
    POR_OTRA_SECCION` -- sin ESTE tipo de contenido "accionable",
    `revalidar_y_regenerar_reporte` no tiene ninguna decisión nueva que
    publicar ni nada que corregir, y correctamente NO regenera nada (es
    idempotente por diseño, ver Requisito 4) -- una fila ya perfecta no
    demostraría la reconciliación real."""
    identificador = f"mobile/{envio_id}/original.jpg"
    fila = {columna: "" for columna in COLUMNAS}
    fila.update(
        archivo=identificador, numero_guia=numero_guia, numero_transporte=numero_transporte,
        estado_procesamiento="OK", indicador_revision="REVISAR", estado_documental="REQUIERE_REVISION",
        estado_operacional="REQUIERE_REVISION", motivos_revision_documento="DESTINO_CONTAMINADO_POR_OTRA_SECCION",
    )
    _escribir_filas(dataset, [fila])
    # `revalidar_y_regenerar_reporte` sólo descubre/publica decisiones
    # NUEVAS si `decisiones_pendientes.json` ya existe -- en producción
    # ya existe siempre porque `procesar_envio_mobile` lo crea/actualiza
    # como parte de SU PROPIO procesamiento (misma llamada, ver ese
    # archivo); acá se replica ese mismo paso para no depender de la
    # OCR real.
    generar_artefacto(
        ruta_dataset=dataset, carpeta_catalogos=catalogos, decisiones=[],
        ruta_salida=dataset.parent / "decisiones_pendientes.json",
    )
    return identificador


def _reporte_vigente_viajes_csv(tmp_path: Path) -> str:
    estado = leer_estado_operacion(raiz=tmp_path)
    assert estado is not None, "estado_operacion.json debe existir tras la reconciliación"
    ruta_viajes = tmp_path / estado["reporte_vigente"] / "viajes.csv"
    assert ruta_viajes.is_file(), f"el reporte vigente debe tener viajes.csv: {ruta_viajes}"
    return ruta_viajes.read_text(encoding="utf-8-sig")


# ---- 1. envío procesado -> dataset actualizado -> reporte/estado_operacion actualizado ----

def test_regenerar_reporte_tras_envio_mobile_actualiza_estado_operacion_y_viajes(tmp_path: Path) -> None:
    catalogos = _catalogos_minimos(tmp_path / "catalogos_privados")
    dataset = tmp_path / "operacion/actual/analisis_completo_guias.csv"
    _dataset_vacio(dataset)
    repo = RepositorioEnviosMobile(tmp_path)
    envio_id = _recibir(repo)
    _escribir_fila_procesada(dataset, catalogos, envio_id=envio_id, numero_guia="472624", numero_transporte="0000355433")

    assert not (tmp_path / "operacion" / "estado_operacion.json").exists()

    _regenerar_reporte_tras_envio_mobile(repo, envio_id)

    registro = repo.cargar(envio_id)
    diagnostico = registro["reconciliacion_reporte"]
    assert diagnostico["estado"] == "OK", diagnostico
    assert diagnostico["reporte_regenerado"] is True

    contenido_viajes = _reporte_vigente_viajes_csv(tmp_path)
    assert "0000355433" in contenido_viajes, "el transporte del envío recién procesado debe aparecer en el reporte"


def test_procesar_y_revalidar_real_encadena_ocr_asociacion_y_reconciliacion(tmp_path: Path, monkeypatch) -> None:
    """Ejercita `_procesar_y_revalidar` de verdad (el punto de entrada
    real que usa `do_POST` en segundo plano) -- sólo se reemplaza el
    paso de OCR (mismo patrón ya usado en
    test_mobile_guias_v1.py::test_mobile_usa_el_selector_normal_de_
    proveedor_ocr) para no depender de una imagen real; el resto de la
    cadena (asociación + reconciliación de reporte) es el código real,
    sin mocks."""
    import servidor_mobile as sm

    catalogos = _catalogos_minimos(tmp_path / "catalogos_privados")
    dataset = tmp_path / "operacion/actual/analisis_completo_guias.csv"
    _dataset_vacio(dataset)
    repo = RepositorioEnviosMobile(tmp_path)
    envio_id = _recibir(repo)

    def procesar_envio_mobile_falso(repositorio, envio_id_arg, *, dataset=None, carpeta_catalogos=None):
        _escribir_fila_procesada(dataset, catalogos, envio_id=envio_id_arg, numero_guia="472624", numero_transporte="0000355433")
        registro = repositorio.cargar(envio_id_arg)
        registro.update(
            estado="ASOCIADO", archivo_dataset=f"mobile/{envio_id_arg}/original.jpg",
            resultado_asociacion={"estado": "SIN_ASOCIACION", "numero_transporte": "", "numero_guia": "472624", "candidatos": [], "motivo": "", "documento_ya_existe": False},
            error="",
        )
        repositorio.guardar(envio_id_arg, registro)
        return registro

    monkeypatch.setattr(sm, "procesar_envio_mobile", procesar_envio_mobile_falso)

    sm._procesar_y_revalidar(repo, envio_id, dataset=dataset, carpeta_catalogos=catalogos)

    registro = repo.cargar(envio_id)
    assert registro["archivo_dataset"] != "", "la fila del documento debe seguir escribiéndose (paso ya existente, sin cambios)"
    assert registro["reconciliacion_reporte"]["estado"] == "OK"
    contenido_viajes = _reporte_vigente_viajes_csv(tmp_path)
    assert "0000355433" in contenido_viajes


# ---- 2. dos envíos secuenciales -> ambos visibles en el estado derivado ----

def test_dos_envios_secuenciales_del_mismo_transporte_terminan_ambos_visibles(tmp_path: Path) -> None:
    catalogos = _catalogos_minimos(tmp_path / "catalogos_privados")
    dataset = tmp_path / "operacion/actual/analisis_completo_guias.csv"
    _dataset_vacio(dataset)
    repo = RepositorioEnviosMobile(tmp_path)

    envio_1 = _recibir(repo)
    _escribir_fila_procesada(dataset, catalogos, envio_id=envio_1, numero_guia="472624", numero_transporte="0000355433")
    _regenerar_reporte_tras_envio_mobile(repo, envio_1)

    envio_2 = _recibir(repo)
    _escribir_fila_procesada(dataset, catalogos, envio_id=envio_2, numero_guia="472623", numero_transporte="0000355433")
    _regenerar_reporte_tras_envio_mobile(repo, envio_2)

    assert repo.cargar(envio_1)["reconciliacion_reporte"]["estado"] == "OK"
    assert repo.cargar(envio_2)["reconciliacion_reporte"]["estado"] == "OK"

    with dataset.open(encoding="utf-8-sig", newline="") as archivo:
        filas = list(csv.DictReader(archivo, delimiter=";"))
    assert {f["numero_guia"] for f in filas} == {"472624", "472623"}, "ambas filas deben seguir en el dataset, sin duplicar ni perder ninguna"

    contenido_viajes = _reporte_vigente_viajes_csv(tmp_path)
    assert contenido_viajes.count("0000355433") >= 1, "el reporte final (tras el segundo envío) debe reflejar el transporte compartido"
    # Hallazgo Codex #3 -- no basta con el transporte compartido: el
    # reporte FINAL (el que queda vigente tras el segundo envío) debe
    # mostrar EXPLÍCITAMENTE las dos guías, no sólo una de ellas
    # "arrastrada" por casualidad desde el primer reporte.
    assert "472624" in contenido_viajes, "la guía del primer envío debe seguir presente en el reporte final"
    assert "472623" in contenido_viajes, "la guía del segundo envío debe estar presente en el reporte final"


# ---- 3. segunda regeneración sin cambios es idempotente ----

def test_segunda_reconciliacion_sin_cambios_es_idempotente_no_regenera_de_nuevo(tmp_path: Path) -> None:
    catalogos = _catalogos_minimos(tmp_path / "catalogos_privados")
    dataset = tmp_path / "operacion/actual/analisis_completo_guias.csv"
    _dataset_vacio(dataset)
    repo = RepositorioEnviosMobile(tmp_path)
    envio_id = _recibir(repo)
    _escribir_fila_procesada(dataset, catalogos, envio_id=envio_id, numero_guia="472624", numero_transporte="0000355433")

    _regenerar_reporte_tras_envio_mobile(repo, envio_id)
    primer_intento = repo.cargar(envio_id)["reconciliacion_reporte"]
    assert primer_intento["estado"] == "OK"
    assert primer_intento["reporte_regenerado"] is True
    reporte_vigente_1 = leer_estado_operacion(raiz=tmp_path)["reporte_vigente"]

    # Nada cambió en el dataset ni en las decisiones -- una segunda
    # pasada, sobre el MISMO envío, nunca debe generar una carpeta de
    # reporte nueva otra vez.
    _regenerar_reporte_tras_envio_mobile(repo, envio_id)
    segundo_intento = repo.cargar(envio_id)["reconciliacion_reporte"]
    assert segundo_intento["estado"] == "OK"
    assert segundo_intento["reporte_regenerado"] is False, "sin cambios reales, la segunda pasada debe ser un no-op -- idempotente"

    reporte_vigente_2 = leer_estado_operacion(raiz=tmp_path)["reporte_vigente"]
    assert reporte_vigente_2 == reporte_vigente_1, "el reporte vigente no debe cambiar de carpeta si no hubo nada que regenerar"


# ---- 4. un envío nuevo "limpio" (sin guías corregidas, sin cambio de bandeja) igual debe aparecer ----

def test_envio_limpio_nuevo_sin_cambios_de_guia_ni_bandeja_igual_aparece_en_el_reporte(tmp_path: Path) -> None:
    """Hallazgo Codex #1: antes de este fix, `revalidar_y_regenerar_
    reporte` sólo regeneraba el reporte si alguna revalidación puntual
    corregía una guía YA EXISTENTE o si la bandeja de decisiones cambiaba
    efectivamente -- un envío Mobile nuevo y VÁLIDO cuya fila queda
    "limpia" (nada que corregir, ninguna decisión nueva) no disparaba
    ninguna de las dos condiciones y quedaba invisible en Desktop pese a
    estar correctamente persistido. La sola incorporación efectiva de la
    fila nueva al dataset (detectada comparando el sha256 del dataset
    contra el grabado en el `reporte_vigente` anterior) debe bastar."""
    catalogos = _catalogos_minimos(tmp_path / "catalogos_privados")
    dataset = tmp_path / "operacion/actual/analisis_completo_guias.csv"
    _dataset_vacio(dataset)
    repo = RepositorioEnviosMobile(tmp_path)

    # Primer envío: "accionable" (mismo patrón que el resto de los tests)
    # para que ya exista un reporte/estado_operacion vigente ANTES del
    # caso que este test realmente ejercita.
    envio_1 = _recibir(repo)
    _escribir_fila_procesada(dataset, catalogos, envio_id=envio_1, numero_guia="472624", numero_transporte="0000355433")
    _regenerar_reporte_tras_envio_mobile(repo, envio_1)
    assert repo.cargar(envio_1)["reconciliacion_reporte"]["reporte_regenerado"] is True

    # Segundo envío: fila LIMPIA -- ninguna revalidación puntual tiene
    # nada que corregir ahí, y al no ser "accionable" no agrega ninguna
    # decisión nueva a la bandeja (bandeja_cambio_efectivo=False). Es
    # EXACTAMENTE el caso que Codex identificó como hueco.
    envio_2 = _recibir(repo)
    identificador = f"mobile/{envio_2}/original.jpg"
    fila_limpia = {columna: "" for columna in COLUMNAS}
    fila_limpia.update(
        archivo=identificador, numero_guia="472999", numero_transporte="0000399999",
        estado_procesamiento="OK", indicador_revision="OK", estado_documental="OK",
        estado_operacional="OK",
    )
    _escribir_filas(dataset, [fila_limpia])

    _regenerar_reporte_tras_envio_mobile(repo, envio_2)

    diagnostico_2 = repo.cargar(envio_2)["reconciliacion_reporte"]
    assert diagnostico_2["estado"] == "OK", diagnostico_2
    assert diagnostico_2["reporte_regenerado"] is True, (
        "una fila nueva y limpia, sin guías corregidas ni cambio de bandeja, "
        "igual debe disparar la regeneración del reporte (hallazgo Codex #1)"
    )
    contenido_viajes = _reporte_vigente_viajes_csv(tmp_path)
    assert "472999" in contenido_viajes, "la guía del envío nuevo, aunque 'limpia', debe aparecer en el reporte vigente"


# ---- compatibilidad con estado histórico real (dataset_sha256 binario, sin la huella nueva) ----

def test_estado_historico_real_con_dataset_sha256_binario_no_dispara_falsa_migracion(tmp_path: Path) -> None:
    """Hallazgo Codex (2da ronda): `dataset_sha256` sigue siendo,
    exactamente igual que siempre, el hash BINARIO de los bytes crudos
    del dataset -- el mismo que ya escriben/leen `estado_operacion` y
    `reconciliar_estado_derivado`. Este test parte de un manifiesto
    "histórico" construido exactamente así (sin la huella semántica
    nueva, `huella_filas_dataset`, que ese código legacy nunca conoció) y
    demuestra: (1) sin cambio real de filas, correr el código nuevo
    contra ese estado NO regenera nada sólo por la migración de formato;
    (2) una fila nueva REAL sigue disparando la regeneración igual que
    siempre, incluso viniendo de un estado legacy."""
    catalogos = _catalogos_minimos(tmp_path / "catalogos_privados")
    dataset = tmp_path / "operacion/actual/analisis_completo_guias.csv"
    _dataset_vacio(dataset)
    repo = RepositorioEnviosMobile(tmp_path)

    # Fila LIMPIA (sin motivo de revisión) -- nada que ninguna
    # revalidación puntual necesite corregir, para aislar esta prueba de
    # la lógica ya cubierta por separado (fila "accionable").
    envio_1 = _recibir(repo)
    fila_1 = {columna: "" for columna in COLUMNAS}
    fila_1.update(
        archivo=f"mobile/{envio_1}/original.jpg", numero_guia="472624", numero_transporte="0000355433",
        estado_procesamiento="OK", indicador_revision="OK", estado_documental="OK", estado_operacional="OK",
    )
    _escribir_filas(dataset, [fila_1])

    # Manifiesto histórico: publicado por FUERA de `revalidar_y_
    # regenerar_reporte` (mismo patrón que ya usa `reconciliar_estado_
    # derivado` hoy) -- `dataset_sha256` real y binario, SIN
    # `huella_filas_dataset` (esa clave no existía antes de este fix).
    reporte_legacy = tmp_path / "reportes" / "reporte_legacy_historico"
    generar_reporte_viajes(
        dataset, reporte_legacy, carpeta_catalogos=catalogos,
        ruta_ledger=tmp_path / "operacion/actual/decisiones_aplicadas.json",
    )
    escribir_estado_operacion(
        reporte_vigente=reporte_legacy, dataset_operacional=dataset,
        dataset_sha256=_sha256_archivo(dataset), origen="RECONCILIACION_ESTADO_DERIVADO", raiz=tmp_path,
    )
    estado_legacy = leer_estado_operacion(raiz=tmp_path)
    assert estado_legacy is not None and estado_legacy.get("dataset_sha256")
    assert "huella_filas_dataset" not in estado_legacy, "el manifiesto legacy no debe traer la huella nueva"

    # (1) Sin cambio real de filas -- nunca debe regenerar sólo por
    # migrar a este código.
    resultado_sin_cambios = revalidar_y_regenerar_reporte(
        raiz_atlas=tmp_path, nombre_carpeta_reporte="no_deberia_existir",
    )
    assert resultado_sin_cambios["reporte_regenerado"] is False, resultado_sin_cambios
    assert not (tmp_path / "reportes" / "no_deberia_existir").exists()

    # (2) Fila nueva real -- sí debe regenerar, aun viniendo de un estado
    # legacy sin huella_filas_dataset.
    envio_2 = _recibir(repo)
    fila_2 = {columna: "" for columna in COLUMNAS}
    fila_2.update(
        archivo=f"mobile/{envio_2}/original.jpg", numero_guia="472623", numero_transporte="0000355433",
        estado_procesamiento="OK", indicador_revision="OK", estado_documental="OK", estado_operacional="OK",
    )
    _escribir_filas(dataset, [fila_2])

    resultado_con_cambio = revalidar_y_regenerar_reporte(
        raiz_atlas=tmp_path, nombre_carpeta_reporte="reporte_tras_fila_nueva_real",
    )
    assert resultado_con_cambio["reporte_regenerado"] is True, resultado_con_cambio
    ruta_viajes = tmp_path / "reportes" / "reporte_tras_fila_nueva_real" / "viajes.csv"
    assert ruta_viajes.is_file()
    assert "472623" in ruta_viajes.read_text(encoding="utf-8-sig")


# ---- un fallo en la revalidación de asociación no debe cortar la reconciliación del reporte ----

def test_fallo_revalidando_asociacion_no_impide_la_reconciliacion_del_reporte(tmp_path: Path, monkeypatch) -> None:
    """Hallazgo Codex #2: antes de este fix, si `revalidar_asociacion_
    mobile_sin_ocr` lanzaba una excepción, el código secuencial de
    `_procesar_y_revalidar` se cortaba ahí mismo y `_regenerar_reporte_
    tras_envio_mobile` (el paso siguiente) nunca llegaba a correr -- el
    documento ya podía estar correctamente persistido (ese paso sólo
    revalida, nunca reescribe la fila) y aun así quedaba invisible en
    Desktop. Ahora la reconciliación del reporte corre siempre, y el
    fallo queda diagnosticable en un campo aparte sin tocar estado/error
    del envío ni duplicar nada."""
    import servidor_mobile as sm

    catalogos = _catalogos_minimos(tmp_path / "catalogos_privados")
    dataset = tmp_path / "operacion/actual/analisis_completo_guias.csv"
    _dataset_vacio(dataset)
    repo = RepositorioEnviosMobile(tmp_path)
    envio_id = _recibir(repo)

    def procesar_envio_mobile_falso(repositorio, envio_id_arg, *, dataset=None, carpeta_catalogos=None):
        _escribir_fila_procesada(dataset, catalogos, envio_id=envio_id_arg, numero_guia="472624", numero_transporte="0000355433")
        registro = repositorio.cargar(envio_id_arg)
        registro.update(estado="ASOCIADO", archivo_dataset=f"mobile/{envio_id_arg}/original.jpg", error="")
        repositorio.guardar(envio_id_arg, registro)
        return registro

    def revalidar_asociacion_rota(repositorio, *, dataset):
        raise RuntimeError("catálogo ilegible (simulado)")

    monkeypatch.setattr(sm, "procesar_envio_mobile", procesar_envio_mobile_falso)
    monkeypatch.setattr(sm, "revalidar_asociacion_mobile_sin_ocr", revalidar_asociacion_rota)

    sm._procesar_y_revalidar(repo, envio_id, dataset=dataset, carpeta_catalogos=catalogos)

    registro = repo.cargar(envio_id)
    # El fallo de la revalidación de asociación queda diagnosticable aparte...
    assert registro["revalidacion_asociacion_post_ocr"]["estado"] == "ERROR"
    assert "catálogo ilegible" in registro["revalidacion_asociacion_post_ocr"]["error"]
    # ...nunca toca el resultado de procesar el documento...
    assert registro["estado"] == "ASOCIADO"
    assert registro["error"] == ""
    # ...y, sobre todo, la reconciliación del reporte SÍ corrió después.
    assert registro["reconciliacion_reporte"]["estado"] == "OK"
    contenido_viajes = _reporte_vigente_viajes_csv(tmp_path)
    assert "472624" in contenido_viajes, "el documento ya persistido debe aparecer en el reporte pese al fallo de asociación"


# ---- 5. un fallo reconciliando nunca borra/duplica el envío, y queda diagnosticable ----

def test_fallo_reconciliando_queda_diagnosticable_y_nunca_toca_el_envio_ya_procesado(tmp_path: Path, monkeypatch) -> None:
    import servidor_mobile as sm

    catalogos = _catalogos_minimos(tmp_path / "catalogos_privados")
    dataset = tmp_path / "operacion/actual/analisis_completo_guias.csv"
    _dataset_vacio(dataset)
    repo = RepositorioEnviosMobile(tmp_path)
    envio_id = _recibir(repo)
    _escribir_fila_procesada(dataset, catalogos, envio_id=envio_id, numero_guia="472624", numero_transporte="0000355433")
    # Simula un catálogo corrupto/ilegible -- causa real y plausible de
    # que `revalidar_y_regenerar_reporte` falle a mitad de camino.
    registro_antes = repo.cargar(envio_id)

    def reconciliador_roto(*, raiz_atlas, nombre_carpeta_reporte, **kwargs):
        raise RuntimeError("catálogo corrupto (simulado)")

    monkeypatch.setattr(sm, "revalidar_y_regenerar_reporte", reconciliador_roto)

    sm._regenerar_reporte_tras_envio_mobile(repo, envio_id)

    registro_despues = repo.cargar(envio_id)
    assert registro_despues["reconciliacion_reporte"]["estado"] == "ERROR"
    assert "catálogo corrupto" in registro_despues["reconciliacion_reporte"]["error"]
    # El resultado de PROCESAR el documento (independiente de reconciliar
    # el reporte) queda intacto -- nunca se pisa con el error de reporte.
    assert registro_despues["estado"] == registro_antes["estado"]
    assert registro_despues.get("archivo_dataset") == registro_antes.get("archivo_dataset")
    assert registro_despues["error"] == registro_antes["error"] == ""
    with dataset.open(encoding="utf-8-sig", newline="") as archivo:
        filas = list(csv.DictReader(archivo, delimiter=";"))
    assert len(filas) == 1  # la fila ya escrita sigue estando, sin duplicar
