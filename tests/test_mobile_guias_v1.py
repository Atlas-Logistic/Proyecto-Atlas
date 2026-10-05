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
from datetime import datetime, timezone
from pathlib import Path

from atlas_core.catalogo_vehiculos import (
    TipoVehiculo, asociar_chofer_a_vehiculo_confirmado, confirmar_vehiculo,
)
from atlas_core.decisiones_pendientes import crear_decision
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


def test_mobile_usa_el_selector_normal_de_proveedor_ocr(tmp_path: Path, monkeypatch) -> None:
    import atlas_core.mobile as mobile

    repo, envio_id = _recibir(tmp_path)
    proveedor_configurado = object()
    observado = {}

    monkeypatch.setattr(mobile, "crear_proveedor_ocr", lambda: proveedor_configurado)

    def procesar(ruta, **kwargs):
        observado.update(kwargs)
        return {"numero_guia": "555111", "numero_transporte": "0000999888"}

    monkeypatch.setattr(mobile, "procesar_archivo", procesar)
    procesar_envio_mobile(repo, envio_id)

    assert observado["proveedor"] is proveedor_configurado
    assert "lector_ocr" not in observado


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


def test_mobile_regenera_decision_humana_desde_motivo_bloqueante(tmp_path: Path) -> None:
    """Un motivo humano Mobile no puede quedar sin tarjeta accionable."""
    repo, envio_id = _recibir(tmp_path)
    dataset = tmp_path / "operacion/actual/analisis_completo_guias.csv"
    _dataset_vacio(dataset)
    catalogos = tmp_path / "catalogos"
    catalogos.mkdir()
    (catalogos / "clientes.json").write_text('{"version_formato": 1, "clientes": []}', encoding="utf-8")
    (catalogos / "plantas.json").write_text('{"version_formato": 1, "plantas": []}', encoding="utf-8")

    registro = procesar_envio_mobile(
        repo, envio_id, dataset=dataset, carpeta_catalogos=catalogos,
        procesador=lambda ruta: {
            "numero_guia": "472640", "numero_transporte": "0000355471",
            "cliente": "No encontrado", "obra_destino": "OBRA EJEMPLO",
            "motivos_revision_documento": "CLIENTE_AUSENTE",
            "indicador_revision": "REVISAR", "estado_operacional": "REQUIERE_REVISION",
        },
    )

    artefacto = json.loads((dataset.parent / "decisiones_pendientes.json").read_text(encoding="utf-8"))
    decisiones_guia = [d for d in artefacto["decisiones"] if d["documento"]["numero_guia"] == "472640"]
    assert registro["estado"] == "REQUIERE_REVISION"
    assert [d["tipo"] for d in decisiones_guia] == ["CLIENTE_AUSENTE"]
    from atlas_core.gestor_viajes import EstadoViaje, agrupar_viajes
    with dataset.open(encoding="utf-8-sig", newline="") as archivo:
        viajes, _ = agrupar_viajes(list(csv.DictReader(archivo, delimiter=";")))
    assert viajes[0].estado == EstadoViaje.REQUIERE_REVISION
    assert viajes[0].estado != EstadoViaje.INCOMPLETO_TECNICO


def _catalogos_para_patente_mobile(carpeta: Path) -> None:
    carpeta.mkdir()
    for nombre, contenido in {
        "clientes.json": {"version_formato": 1, "clientes": []},
        "empresas.json": {},
        "vehiculos.json": {"version": 1, "vehiculos": []},
        "obras_destinos.json": {"version_formato": 1, "obras": [], "relaciones": []},
        "destinos_maestros.json": {"version_formato": 1, "destinos": []},
        "plantas.json": {"version_formato": 1, "plantas": []},
    }.items():
        (carpeta / nombre).write_text(json.dumps(contenido), encoding="utf-8")


def _asignar_tracto(catalogos: Path, patente: str, rut: str) -> None:
    fecha = datetime(2026, 10, 5, tzinfo=timezone.utc)
    ruta = catalogos / "vehiculos.json"
    confirmar_vehiculo(
        ruta, patente=patente, tipo=TipoVehiculo.TRACTO.value,
        actor="TEST", fuente_decision="TEST", fecha=fecha,
    )
    asociar_chofer_a_vehiculo_confirmado(
        ruta, patente=patente, actor="TEST", fuente_decision="TEST",
        fecha=fecha, rut_chofer_asociado=rut,
    )


def _procesador_con_tarjeta_patente(monkeypatch, *, guia: str, transporte: str, patente_ocr: str, rut: str) -> None:
    import atlas_core.mobile as mobile

    def procesar(_imagen, **kwargs):
        kwargs["recolector_decisiones"]([
            crear_decision(
                tipo="VEHICULO_DESCONOCIDO", entidad="VEHICULO", archivo="original.jpg",
                numero_guia=guia, numero_transporte=transporte, campo="patente_tracto",
                valor_documental=patente_ocr, valor_normalizado=patente_ocr,
                identidad_resuelta=None, candidatos=(),
                motivos=("SIN_VEHICULO_CONFIRMADO_COMPATIBLE",),
                evidencias=({"tipo": "OCR_DOCUMENTAL", "campo": "patente_tracto", "valor": patente_ocr},),
                acciones_permitidas=("REGISTRAR", "NO_REGISTRAR", "POSPONER"),
                tipo_resolucion="INEQUIVOCO", tipo_vehiculo_propuesto="TRACTO",
            )
        ])
        return {
            "numero_guia": guia, "numero_transporte": transporte, "chofer": "SALOMON PIZARRO",
            "rut_chofer": rut, "patente_tracto": patente_ocr, "patente_rampla": "JF9575",
            "indicador_revision": "REVISAR", "estado_procesamiento": "OK",
        }

    monkeypatch.setattr(mobile, "crear_proveedor_ocr", lambda: object())
    monkeypatch.setattr(mobile, "procesar_archivo", procesar)


def test_mobile_auto_resuelve_patente_ocr_con_asignacion_humana_unica(tmp_path: Path, monkeypatch) -> None:
    """Regresión 475252: Mobile debe ejecutar la misma pasada final que Desktop."""
    rut = "18.091.588-5"
    repo, envio_id = _recibir(tmp_path / "operacion/mobile/envios")
    dataset = tmp_path / "operacion/actual/analisis_completo_guias.csv"
    _dataset_vacio(dataset)
    catalogos = tmp_path / "catalogos_privados"
    _catalogos_para_patente_mobile(catalogos)
    _asignar_tracto(catalogos, "TG8925", rut)
    _procesador_con_tarjeta_patente(
        monkeypatch, guia="475252", transporte="0000362011", patente_ocr="1G8925", rut=rut,
    )

    procesar_envio_mobile(repo, envio_id, dataset=dataset, carpeta_catalogos=catalogos)

    pendientes = json.loads((dataset.parent / "decisiones_pendientes.json").read_text(encoding="utf-8"))
    assert not any(d["tipo"] == "VEHICULO_DESCONOCIDO" for d in pendientes["decisiones"])
    ledger = json.loads((dataset.parent / "decisiones_aplicadas.json").read_text(encoding="utf-8"))
    aplicada = next(a for a in ledger["aplicaciones"] if a["documento"]["numero_guia"] == "475252")
    assert aplicada["accion"] == "USAR_PATENTE_EXISTENTE"
    assert aplicada["patente_canonica"] == "TG8925"


def test_mobile_mantiene_revision_si_asignacion_del_chofer_es_ambigua(tmp_path: Path, monkeypatch) -> None:
    rut = "18.091.588-5"
    repo, envio_id = _recibir(tmp_path / "operacion/mobile/envios")
    dataset = tmp_path / "operacion/actual/analisis_completo_guias.csv"
    _dataset_vacio(dataset)
    catalogos = tmp_path / "catalogos_privados"
    _catalogos_para_patente_mobile(catalogos)
    _asignar_tracto(catalogos, "TG8925", rut)
    _asignar_tracto(catalogos, "AB1234", rut)
    _procesador_con_tarjeta_patente(
        monkeypatch, guia="475253", transporte="0000362012", patente_ocr="1G8925", rut=rut,
    )

    procesar_envio_mobile(repo, envio_id, dataset=dataset, carpeta_catalogos=catalogos)

    pendientes = json.loads((dataset.parent / "decisiones_pendientes.json").read_text(encoding="utf-8"))
    tarjeta = next(d for d in pendientes["decisiones"] if d["tipo"] == "VEHICULO_DESCONOCIDO")
    assert {c["patente"] for c in tarjeta["candidatos"]} == {"TG8925", "AB1234"}
    assert tarjeta["evaluacion_evidencia"]["resultado"] != "RESUELTO_AUTOMATICAMENTE"


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
        # La selección normal puede arrancar el worker PaddleOCR por primera
        # vez; el contrato sigue siendo asíncrono, pero ese arranque es más
        # costoso que el fallback EasyOCR histórico de esta prueba.
        for _ in range(300):
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
