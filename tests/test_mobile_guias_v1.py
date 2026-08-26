"""Bloque GUÍAS MÓVILES V1 -- Mobile entra al MISMO Motor que Desktop.

Foco: `procesar_envio_mobile` debe persistir la guía en el dataset real
(no sólo en el JSON del envío), reusando `procesar_archivo`/COLUMNAS
-- nunca un Core paralelo -- y debe distinguir captura ilegible de
Incidencia Documental, y nunca duplicar un documento ya representado.
"""
from __future__ import annotations

import csv
import json
import threading
import time
import urllib.request
import uuid
from pathlib import Path

from atlas_core.mobile import AutenticadorMobile, RepositorioEnviosMobile, hash_password, procesar_envio_mobile
from atlas_core.procesamiento_masivo import COLUMNAS
from servidor_mobile import crear_servidor


def _dataset_vacio(ruta: Path) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with ruta.open("w", newline="", encoding="utf-8-sig") as archivo:
        csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";").writeheader()


def _dataset_con_fila(ruta: Path, fila: dict[str, str]) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    completa = {columna: fila.get(columna, "") for columna in COLUMNAS}
    with ruta.open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader()
        escritor.writerow(completa)


def _recibir(tmp_path: Path) -> tuple[RepositorioEnviosMobile, str]:
    repo = RepositorioEnviosMobile(tmp_path)
    envio_id = str(uuid.uuid4())
    repo.recibir(
        envio_id=envio_id, imagen=b"foto", mime="image/jpeg",
        metadata={"chofer_id": "c1", "tipo_novedad": "", "guia_firmada_correo": False, "planta_origen_informada": "AZA_COLINA"},
    )
    return repo, envio_id


def test_guia_nueva_se_persiste_en_el_dataset_real_y_aparece_como_fila(tmp_path: Path) -> None:
    repo, envio_id = _recibir(tmp_path)
    dataset = tmp_path / "operacion/actual/analisis_completo_guias.csv"
    _dataset_vacio(dataset)
    registro = procesar_envio_mobile(
        repo, envio_id, dataset=dataset,
        procesador=lambda ruta: {
            "numero_guia": "555111", "numero_transporte": "0000999888",
            "chofer": "PEREZ JUAN", "indicador_revision": "OK",
        },
    )
    assert registro["estado"] == "ASOCIADO"
    assert registro["archivo_dataset"] == f"mobile/{envio_id}/original.jpg"
    with dataset.open(encoding="utf-8-sig", newline="") as archivo:
        filas = list(csv.DictReader(archivo, delimiter=";"))
    assert len(filas) == 1
    assert filas[0]["numero_guia"] == "555111"
    assert filas[0]["archivo"] == f"mobile/{envio_id}/original.jpg"


def test_misma_guia_ya_presente_no_duplica_la_fila(tmp_path: Path) -> None:
    repo, envio_id = _recibir(tmp_path)
    dataset = tmp_path / "operacion/actual/analisis_completo_guias.csv"
    _dataset_con_fila(dataset, {
        "archivo": "desktop/460807.jpeg", "numero_guia": "460807",
        "numero_transporte": "0000351135", "estado_procesamiento": "OK",
    })
    registro = procesar_envio_mobile(
        repo, envio_id, dataset=dataset,
        procesador=lambda ruta: {"numero_guia": "460807", "numero_transporte": "0000351135"},
    )
    assert registro["estado"] == "ASOCIADO"
    assert registro["archivo_dataset"] == ""  # no se escribió fila nueva
    with dataset.open(encoding="utf-8-sig", newline="") as archivo:
        filas = list(csv.DictReader(archivo, delimiter=";"))
    assert len(filas) == 1  # sigue habiendo una sola fila para esta guía


def test_reprocesar_el_mismo_envio_no_duplica_la_fila(tmp_path: Path) -> None:
    repo, envio_id = _recibir(tmp_path)
    dataset = tmp_path / "operacion/actual/analisis_completo_guias.csv"
    _dataset_vacio(dataset)
    procesador = lambda ruta: {"numero_guia": "555111", "numero_transporte": "0000999888"}
    procesar_envio_mobile(repo, envio_id, dataset=dataset, procesador=procesador)
    procesar_envio_mobile(repo, envio_id, dataset=dataset, procesador=procesador)
    with dataset.open(encoding="utf-8-sig", newline="") as archivo:
        filas = list(csv.DictReader(archivo, delimiter=";"))
    assert len(filas) == 1


def test_foto_ilegible_es_problema_de_captura_no_incidencia_documental(tmp_path: Path) -> None:
    repo, envio_id = _recibir(tmp_path)
    dataset = tmp_path / "operacion/actual/analisis_completo_guias.csv"
    _dataset_vacio(dataset)
    registro = procesar_envio_mobile(
        repo, envio_id, dataset=dataset,
        procesador=lambda ruta: {"numero_guia": "No encontrado", "numero_transporte": "No encontrado"},
    )
    assert registro["estado"] == "REQUIERE_REVISION"
    assert registro["problema_captura"] is True
    assert registro["archivo_dataset"] == ""
    with dataset.open(encoding="utf-8-sig", newline="") as archivo:
        filas = list(csv.DictReader(archivo, delimiter=";"))
    assert len(filas) == 0  # nunca se escribe una fila en blanco como incidencia


def test_indicador_revision_del_core_manda_a_revision_igual_que_desktop(tmp_path: Path) -> None:
    repo, envio_id = _recibir(tmp_path)
    dataset = tmp_path / "operacion/actual/analisis_completo_guias.csv"
    _dataset_vacio(dataset)
    registro = procesar_envio_mobile(
        repo, envio_id, dataset=dataset,
        procesador=lambda ruta: {
            "numero_guia": "555111", "numero_transporte": "0000999888",
            "indicador_revision": "REVISAR",
        },
    )
    assert registro["estado"] == "REQUIERE_REVISION"
    assert registro["problema_captura"] is False
    # La fila igual queda persistida (misma Incidencia Documental que ya
    # usa Desktop) -- Mobile no la esconde, sólo no la asocia sola.
    assert registro["archivo_dataset"] != ""


def test_dataset_de_esquema_reducido_nunca_recibe_una_escritura_con_esquema_completo(tmp_path: Path) -> None:
    repo, envio_id = _recibir(tmp_path)
    dataset = tmp_path / "operacion/actual/analisis_completo_guias.csv"
    dataset.parent.mkdir(parents=True)
    dataset.write_text("numero_guia;numero_transporte\n464265;0000351135\n", encoding="utf-8-sig")
    registro = procesar_envio_mobile(
        repo, envio_id, dataset=dataset,
        procesador=lambda ruta: {"numero_guia": "999000", "numero_transporte": "0000111222"},
    )
    assert registro["archivo_dataset"] == ""
    contenido = dataset.read_text(encoding="utf-8-sig")
    assert contenido.count("\n") == 2  # encabezado + 1 fila original, sin agregados


def test_envio_id_con_traversal_o_caracteres_no_seguros_se_rechaza(tmp_path: Path) -> None:
    from atlas_core.mobile import ErrorEnvioMobile

    repo = RepositorioEnviosMobile(tmp_path)
    for envio_id_malicioso in ("../../etc/passwd", "..\\..\\windows", "a/b", "corto"):
        try:
            repo.recibir(
                envio_id=envio_id_malicioso, imagen=b"foto", mime="image/jpeg",
                metadata={"tipo_novedad": "", "guia_firmada_correo": False, "planta_origen_informada": "AZA_COLINA"},
            )
            assert False, f"debió rechazar {envio_id_malicioso!r}"
        except ErrorEnvioMobile:
            pass
    assert not (tmp_path / "operacion" / "mobile" / "envios").exists() or \
        len(list((tmp_path / "operacion" / "mobile" / "envios").iterdir())) == 0


def _multipart(campos: dict[str, str], imagen: bytes, mime: str = "image/jpeg") -> tuple[bytes, str]:
    boundary = "atlas-e2e-boundary"
    partes = []
    for nombre, valor in campos.items():
        partes.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{nombre}\"\r\n\r\n{valor}\r\n".encode())
    partes.append(
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"imagen\"; filename=\"foto.jpg\"\r\nContent-Type: {mime}\r\n\r\n".encode()
        + imagen + b"\r\n"
    )
    partes.append(f"--{boundary}--\r\n".encode())
    return b"".join(partes), f"multipart/form-data; boundary={boundary}"


def test_e2e_http_real_con_procesamiento_automatico_y_reintento_sin_duplicar(tmp_path: Path) -> None:
    # Sección 16 (E2E real obligatorio, casos C/F): sube por HTTP real
    # (mismo servidor que usa la app Mobile), deja que el procesamiento
    # automático en segundo plano corra solo (Sección 12 -- nadie aprieta
    # "procesar" a mano), y confirma que reenviar el MISMO envio_id (igual
    # que hace `sync-core.js` en un reintento de red) nunca crea un
    # segundo envío ni un segundo archivo.
    dataset = tmp_path / "operacion/actual/analisis_completo_guias.csv"
    _dataset_vacio(dataset)
    autenticador = AutenticadorMobile(
        {"carlos": {"chofer_id": "chofer-1", "password_hash": hash_password("secreto")}},
        "secreto-de-prueba-e2e-mobile-123456",
    )
    servidor = crear_servidor("127.0.0.1", 0, raiz=tmp_path, autenticador=autenticador, procesar=True)
    hilo = threading.Thread(target=servidor.serve_forever, daemon=True)
    hilo.start()
    try:
        login = urllib.request.Request(
            f"http://127.0.0.1:{servidor.server_port}/api/mobile/login",
            data=json.dumps({"usuario": "carlos", "password": "secreto"}).encode(),
            headers={"Content-Type": "application/json"}, method="POST",
        )
        token = json.load(urllib.request.urlopen(login))["token"]
        envio_id = str(uuid.uuid4())
        cuerpo, tipo = _multipart({"envio_id": envio_id, "schema_version": "1", "capturado_en": "2026-08-25T12:00:00Z", "planta_origen_informada": "AZA_COLINA"}, b"no-es-una-imagen-real")
        solicitud = lambda: urllib.request.Request(
            f"http://127.0.0.1:{servidor.server_port}/api/mobile/envios",
            data=cuerpo, headers={"Content-Type": tipo, "Authorization": f"Bearer {token}"}, method="POST",
        )
        primera = json.load(urllib.request.urlopen(solicitud()))
        assert primera["resultado"] == "ACEPTADO" and not primera["duplicado"]
        # El procesamiento automático corre en segundo plano (executor de
        # 1 worker) -- se espera a que termine sin que nadie lo dispare a mano.
        registro = None
        for _ in range(50):
            registro = servidor.repositorio.cargar(envio_id)  # type: ignore[attr-defined]
            if registro["estado"] != "PROCESANDO" and registro["estado"] != "RECIBIDO":
                break
            time.sleep(0.1)
        assert registro is not None and registro["estado"] in ("ERROR", "REQUIERE_REVISION", "ASOCIADO")

        segunda = json.load(urllib.request.urlopen(solicitud()))
        assert segunda["duplicado"]
        carpeta_envios = tmp_path / "operacion" / "mobile" / "envios"
        assert len(list(carpeta_envios.iterdir())) == 1  # nunca un segundo envío por el mismo envio_id
    finally:
        servidor.shutdown(); servidor.server_close()


def test_decisiones_pendientes_previas_de_desktop_no_se_pierden_al_procesar_mobile(tmp_path: Path) -> None:
    repo, envio_id = _recibir(tmp_path)
    dataset = tmp_path / "operacion/actual/analisis_completo_guias.csv"
    _dataset_vacio(dataset)
    catalogos = tmp_path / "catalogos_privados"
    catalogos.mkdir()
    artefacto = dataset.parent / "decisiones_pendientes.json"
    artefacto.write_text(json.dumps({
        "decisiones": [{"decision_id": "desktop-previa-1", "tipo": "PLANTA_AMBIGUA"}],
    }), encoding="utf-8")

    def _procesador(ruta: Path) -> dict:
        return {"numero_guia": "555111", "numero_transporte": "0000999888"}

    procesar_envio_mobile(
        repo, envio_id, dataset=dataset, carpeta_catalogos=catalogos, procesador=_procesador,
    )
    publicado = json.loads(artefacto.read_text(encoding="utf-8"))
    ids = {d.get("decision_id") for d in publicado["decisiones"]}
    assert "desktop-previa-1" in ids  # nunca se pisa lo pendiente de Desktop
