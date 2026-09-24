"""Bloque MOBILE OBSERVACIÓN DEL CHOFER V1 -- texto libre OPCIONAL que el
chofer escribe para el ENVÍO completo (misma observación en cada foto de
la tanda, junto a su `lote_id`). Viaja explícito en el contrato Mobile
(campo multipart `observacion`), se valida en Core
(`normalizar_observacion_mobile`, nunca sólo en el cliente) y queda
persistido en `envio.json` -- sobrevive al procesamiento, al reproceso y
a la consulta posterior. Nunca se interpreta: se conserva lo escrito."""
from __future__ import annotations

import csv
import json
import threading
import unicodedata
import urllib.error
import urllib.request
import uuid
from pathlib import Path

import pytest

from atlas_core.mobile import (
    MAX_OBSERVACION_CARACTERES, AutenticadorMobile, ErrorEnvioMobile, RepositorioEnviosMobile,
    hash_password, normalizar_observacion_mobile, procesar_envio_mobile, reprocesar_envio_mobile_persistido,
)
from atlas_core.procesamiento_masivo import COLUMNAS
from servidor_mobile import crear_servidor


def _auth() -> AutenticadorMobile:
    return AutenticadorMobile(
        {"javier": {"chofer_id": "chofer-1", "password_hash": hash_password("secreto")}},
        "secreto-de-prueba-observacion-123456",
    )


def _multipart(campos: dict[str, str], imagen: bytes) -> tuple[bytes, str]:
    boundary = "atlas-test-boundary"
    partes = [
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"{nombre}\"\r\n\r\n".encode() + valor.encode("utf-8") + b"\r\n"
        for nombre, valor in campos.items()
    ]
    partes.append(
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"imagen\"; filename=\"foto.jpg\"\r\nContent-Type: image/jpeg\r\n\r\n".encode()
        + imagen + b"\r\n"
    )
    partes.append(f"--{boundary}--\r\n".encode())
    return b"".join(partes), f"multipart/form-data; boundary={boundary}"


def _campos(envio_id: str, **extra: str) -> dict[str, str]:
    return {
        "envio_id": envio_id, "schema_version": "1", "capturado_en": "2026-09-23T12:00:00Z",
        "tipo_novedad": "", "guia_firmada_correo": "false", "planta_origen_informada": "AZA_COLINA", **extra,
    }


@pytest.fixture()
def servidor(tmp_path: Path):
    srv = crear_servidor("127.0.0.1", 0, raiz=tmp_path, autenticador=_auth(), procesar=False)
    hilo = threading.Thread(target=srv.serve_forever, daemon=True)
    hilo.start()
    login = urllib.request.Request(
        f"http://127.0.0.1:{srv.server_port}/api/mobile/login",
        data=json.dumps({"usuario": "javier", "password": "secreto"}).encode(),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    srv.token_prueba = json.load(urllib.request.urlopen(login))["token"]  # type: ignore[attr-defined]
    try:
        yield srv
    finally:
        srv.shutdown(); srv.server_close(); srv.ejecutor.shutdown(wait=True)


def _subir(srv, cuerpo: bytes, tipo: str) -> tuple[int, dict]:
    solicitud = urllib.request.Request(
        f"http://127.0.0.1:{srv.server_port}/api/mobile/envios", data=cuerpo,
        headers={"Content-Type": tipo, "Authorization": f"Bearer {srv.token_prueba}"}, method="POST",
    )
    try:
        with urllib.request.urlopen(solicitud) as respuesta:
            return respuesta.status, json.load(respuesta)
    except urllib.error.HTTPError as error:
        return error.code, json.load(error)


def _subir_campos(srv, campos: dict[str, str]) -> tuple[int, dict]:
    return _subir(srv, *_multipart(campos, b"contenido-jpeg-simulado"))


# ============================================================
# Contrato HTTP real (servidor_mobile.py)
# ============================================================

def test_envio_sin_observacion_cliente_anterior_sigue_funcionando(servidor) -> None:
    envio_id = str(uuid.uuid4())
    codigo, cuerpo = _subir_campos(servidor, _campos(envio_id))
    assert codigo == 202 and cuerpo["resultado"] == "ACEPTADO"
    registro = servidor.repositorio.cargar(envio_id)
    assert registro["observacion"] == ""
    assert registro["planta_origen_informada"] == "AZA_COLINA"


def test_envio_con_observacion_corta_queda_persistido(servidor) -> None:
    envio_id = str(uuid.uuid4())
    codigo, _ = _subir_campos(servidor, _campos(envio_id, observacion="Cliente no quiso recibir"))
    assert codigo == 202
    assert servidor.repositorio.cargar(envio_id)["observacion"] == "Cliente no quiso recibir"


def test_tildes_enie_numeros_puntuacion_y_saltos_crlf(servidor) -> None:
    envio_id = str(uuid.uuid4())
    texto = "Guía firmada con observación: Sr. Muñoz, 2ª vuelta (15:30) ¿ok?\r\nFoto adicional corresponde al rechazo"
    codigo, _ = _subir_campos(servidor, _campos(envio_id, observacion=unicodedata.normalize("NFD", texto)))
    assert codigo == 202
    guardado = servidor.repositorio.cargar(envio_id)["observacion"]
    assert guardado == unicodedata.normalize("NFC", texto).replace("\r\n", "\n")
    # Persistido como UTF-8 legible en disco (auditable), no escapado.
    crudo = (servidor.repositorio.raiz / envio_id / "envio.json").read_text(encoding="utf-8")
    assert "Muñoz" in crudo or "Mu\\u00f1oz" in crudo
    assert json.loads(crudo)["observacion"] == guardado


def test_observacion_en_el_limite_se_acepta(servidor) -> None:
    envio_id = str(uuid.uuid4())
    texto = "ñ" * MAX_OBSERVACION_CARACTERES  # 500 caracteres, 1000 bytes UTF-8.
    codigo, _ = _subir_campos(servidor, _campos(envio_id, observacion=texto))
    assert codigo == 202
    assert servidor.repositorio.cargar(envio_id)["observacion"] == texto


def test_observacion_sobre_el_limite_se_rechaza_y_no_persiste_nada(servidor) -> None:
    envio_id = str(uuid.uuid4())
    codigo, cuerpo = _subir_campos(servidor, _campos(envio_id, observacion="a" * (MAX_OBSERVACION_CARACTERES + 1)))
    assert codigo == 400
    assert "observacion" in cuerpo["error"]
    assert not (servidor.repositorio.raiz / envio_id).exists()


def test_observacion_con_bytes_no_utf8_responde_400(servidor) -> None:
    envio_id = str(uuid.uuid4())
    cuerpo, tipo = _multipart(_campos(envio_id), b"contenido-jpeg-simulado")
    cuerpo = cuerpo.replace(
        b"--atlas-test-boundary\r\nContent-Disposition: form-data; name=\"imagen\"",
        b"--atlas-test-boundary\r\nContent-Disposition: form-data; name=\"observacion\"\r\n\r\n\xff\xfe\r\n"
        b"--atlas-test-boundary\r\nContent-Disposition: form-data; name=\"imagen\"",
    )
    codigo, respuesta = _subir(servidor, cuerpo, tipo)
    assert codigo == 400 and "UTF-8" in respuesta["error"]


def test_varias_fotos_de_una_tanda_llevan_una_sola_observacion(servidor) -> None:
    lote_id = str(uuid.uuid4())
    ids = [str(uuid.uuid4()) for _ in range(3)]
    for envio_id in ids:
        codigo, _ = _subir_campos(servidor, _campos(envio_id, lote_id=lote_id, observacion="Segunda vuelta"))
        assert codigo == 202
    registros = [servidor.repositorio.cargar(i) for i in ids]
    assert {r["observacion"] for r in registros} == {"Segunda vuelta"}
    assert {r["lote_id"] for r in registros} == {lote_id}


def test_reintento_idempotente_conserva_la_observacion_original(servidor) -> None:
    envio_id = str(uuid.uuid4())
    _subir_campos(servidor, _campos(envio_id, observacion="Esperando descarga"))
    codigo, cuerpo = _subir_campos(servidor, _campos(envio_id, observacion="Esperando descarga"))
    assert codigo == 202 and cuerpo["duplicado"] is True
    assert servidor.repositorio.cargar(envio_id)["observacion"] == "Esperando descarga"


# ============================================================
# Core -- validación, procesamiento, reproceso, consulta
# ============================================================

@pytest.mark.parametrize("valor, esperado", [
    (None, ""), ("", ""), ("   \n ", ""), ("  hola  ", "hola"), ("a\r\nb\rc", "a\nb\nc"), ("a\tb", "a\tb"),
])
def test_normalizacion(valor, esperado) -> None:
    assert normalizar_observacion_mobile(valor) == esperado


@pytest.mark.parametrize("valor", ["hola\x00mundo", "x\x1b[31m", "a" * 501, "🚚" * 501, 123])
def test_rechazos(valor) -> None:
    with pytest.raises(ErrorEnvioMobile):
        normalizar_observacion_mobile(valor)


def test_limite_cuenta_caracteres_unicode_no_bytes() -> None:
    assert normalizar_observacion_mobile("🚚" * 500) == "🚚" * 500


def _recibir(repo: RepositorioEnviosMobile, observacion: str | None) -> str:
    envio_id = str(uuid.uuid4())
    metadata = {"chofer_id": "c1", "tipo_novedad": "", "guia_firmada_correo": False, "planta_origen_informada": "AZA_COLINA"}
    if observacion is not None:
        metadata["observacion"] = observacion
    repo.recibir(envio_id=envio_id, imagen=b"foto", mime="image/jpeg", metadata=metadata)
    return envio_id


def test_observacion_sobrevive_al_procesamiento_del_motor(tmp_path: Path) -> None:
    repo = RepositorioEnviosMobile(tmp_path)
    envio_id = _recibir(repo, "Guía firmada con observación")
    dataset = tmp_path / "operacion/actual/analisis_completo_guias.csv"
    dataset.parent.mkdir(parents=True)
    dataset.write_text("numero_guia;numero_transporte\n464265;0000351135\n", encoding="utf-8-sig")
    registro = procesar_envio_mobile(
        repo, envio_id, dataset=dataset,
        procesador=lambda ruta: {"numero_guia": "464265", "numero_transporte": "0000351135"},
    )
    assert registro["estado"] == "ASOCIADO"
    assert registro["observacion"] == "Guía firmada con observación"
    assert repo.cargar(envio_id)["observacion"] == "Guía firmada con observación"


def test_observacion_sobrevive_al_reproceso_persistido(tmp_path: Path, monkeypatch) -> None:
    import atlas_core.mobile as mobile

    repo = RepositorioEnviosMobile(tmp_path)
    envio_id = _recibir(repo, "Foto adicional corresponde al rechazo")
    dataset = tmp_path / "operacion/actual/analisis_completo_guias.csv"
    dataset.parent.mkdir(parents=True)
    fila = {columna: "" for columna in COLUMNAS}
    fila.update(archivo=f"mobile/{envio_id}/original.jpg", numero_guia="900001", numero_transporte="0000900000",
                cliente="No encontrado", rut_cliente="No encontrado", estado_procesamiento="OK")
    with dataset.open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader(); escritor.writerow(fila)
    monkeypatch.setattr(mobile, "crear_proveedor_ocr", lambda: object())
    monkeypatch.setattr(mobile, "procesar_archivo", lambda ruta, **kw: {"numero_guia": "900001", "numero_transporte": "0000900000"})

    resultado = reprocesar_envio_mobile_persistido(repo, envio_id, dataset=dataset)
    assert resultado["estado"] != "ERROR", resultado.get("error")
    assert repo.cargar(envio_id)["observacion"] == "Foto adicional corresponde al rechazo"


def test_consulta_posterior_historial_expone_observacion_y_tolera_envio_antiguo(tmp_path: Path) -> None:
    repo = RepositorioEnviosMobile(tmp_path)
    nuevo = _recibir(repo, "Esperando descarga")
    # Envío antiguo ya persistido ANTES de este bloque: sin clave `observacion`.
    antiguo = _recibir(repo, None)
    registro_antiguo = repo.cargar(antiguo)
    registro_antiguo.pop("observacion")
    repo.guardar(antiguo, registro_antiguo)

    por_id = {r["envio_id"]: r for r in repo.historial()}
    assert por_id[nuevo]["observacion"] == "Esperando descarga"
    assert "observacion" not in por_id[antiguo]
    assert por_id[antiguo].get("observacion", "") == ""


def test_recibir_sin_campo_observacion_guarda_vacio(tmp_path: Path) -> None:
    repo = RepositorioEnviosMobile(tmp_path)
    assert repo.cargar(_recibir(repo, None))["observacion"] == ""
