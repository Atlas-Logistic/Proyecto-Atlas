"""Regresiones P0: el OCR de Mobile pertenece al trabajador, no a la guía."""
from __future__ import annotations

import hashlib
import json
import threading
import urllib.request
import uuid
from pathlib import Path

from atlas_core import cloud_mobile_sync_cliente as cloud
from atlas_core import mobile
import servidor_mobile


class _Proveedor:
    def __init__(self):
        self.cierres = 0

    def cerrar(self):
        self.cierres += 1


def test_punto_de_entrada_mobile_reutiliza_el_proveedor_inyectado(monkeypatch, tmp_path: Path):
    proveedor = _Proveedor()
    recibidos = []

    def procesar(_repositorio, envio_id, **kwargs):
        recibidos.append((envio_id, kwargs["proveedor_ocr"]))
        return {"estado": "ASOCIADO"}

    monkeypatch.setattr(mobile, "procesar_envio_mobile", procesar)
    monkeypatch.setattr(mobile, "_revalidar_asociacion_diagnosticable", lambda *_a, **_k: None)
    monkeypatch.setattr(mobile, "_regenerar_reporte_tras_envio_mobile", lambda *_a, **_k: True)
    monkeypatch.setattr(mobile, "_converger_envios_tras_reporte", lambda *_a, **_k: True)
    monkeypatch.setattr(mobile, "_sincronizar_contrato_v2", lambda *_a, **_k: None)

    class Repo:
        def cargar(self, _envio_id):
            return {"estado": "RECIBIDO"}

    repo = Repo()
    salida_1 = mobile.procesar_y_revalidar_envio_mobile(repo, "uno", dataset=tmp_path / "datos.csv", carpeta_catalogos=None, proveedor_ocr=proveedor)
    salida_2 = mobile.procesar_y_revalidar_envio_mobile(repo, "dos", dataset=tmp_path / "datos.csv", carpeta_catalogos=None, proveedor_ocr=proveedor)

    assert salida_1 == salida_2 == {"procesamiento_ok": True, "reconciliacion_ok": True}
    assert recibidos == [("uno", proveedor), ("dos", proveedor)]


def test_punto_de_entrada_mobile_no_pasa_proveedor_none_a_sustituto_previo(monkeypatch, tmp_path: Path):
    recibidos = []

    def procesar_previo(_repositorio, envio_id, *, dataset=None, carpeta_catalogos=None):
        recibidos.append((envio_id, dataset, carpeta_catalogos))
        return {"estado": "ASOCIADO"}

    monkeypatch.setattr(mobile, "procesar_envio_mobile", procesar_previo)
    monkeypatch.setattr(mobile, "_revalidar_asociacion_diagnosticable", lambda *_a, **_k: None)
    monkeypatch.setattr(mobile, "_regenerar_reporte_tras_envio_mobile", lambda *_a, **_k: True)
    monkeypatch.setattr(mobile, "_converger_envios_tras_reporte", lambda *_a, **_k: True)
    monkeypatch.setattr(mobile, "_sincronizar_contrato_v2", lambda *_a, **_k: None)

    class Repo:
        def cargar(self, _envio_id):
            return {"estado": "RECIBIDO"}

    repo = Repo()
    salida = mobile.procesar_y_revalidar_envio_mobile(
        repo, "uno", dataset=tmp_path / "datos.csv", carpeta_catalogos=None,
    )

    assert salida == {"procesamiento_ok": True, "reconciliacion_ok": True}
    assert recibidos == [("uno", tmp_path / "datos.csv", None)]


def test_barrido_cloud_pasa_la_misma_instancia_a_envios_consecutivos(monkeypatch):
    proveedor = _Proveedor()
    usados = []

    class Repo:
        def historial(self):
            return [{"envio_id": "uno", "estado": "RECIBIDO"}, {"envio_id": "dos", "estado": "PROCESANDO"}]

    def procesar(_repo, envio_id, **kwargs):
        usados.append((envio_id, kwargs["proveedor_ocr"]))
        return {"completado": True}

    monkeypatch.setattr(cloud, "_procesar_envio_cloud", procesar)

    resultado = cloud.procesar_envios_recibidos(Repo(), dataset=None, carpeta_catalogos=None, proveedor_ocr=proveedor)

    assert resultado["procesados"] == ["uno", "dos"]
    assert usados == [("uno", proveedor), ("dos", proveedor)]


def _multipart(envio_id: str) -> tuple[bytes, str]:
    boundary = "atlas-ocr-reuse"
    campos = {
        "envio_id": envio_id, "capturado_en": "2026-10-08T12:00:00Z",
        "planta_origen_informada": "AZA_COLINA",
    }
    partes = [
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"{nombre}\"\r\n\r\n{valor}\r\n".encode()
        for nombre, valor in campos.items()
    ]
    partes.extend((
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"imagen\"; filename=\"guia.jpg\"\r\nContent-Type: image/jpeg\r\n\r\n".encode(),
        b"jpeg-simulada\r\n",
        f"--{boundary}--\r\n".encode(),
    ))
    return b"".join(partes), f"multipart/form-data; boundary={boundary}"


def test_servidor_http_reutiliza_proveedor_y_lo_cierra_una_vez(monkeypatch, tmp_path: Path):
    proveedor = _Proveedor()
    usados = []
    monkeypatch.setattr(servidor_mobile, "crear_proveedor_ocr", lambda: proveedor)
    monkeypatch.setattr(
        servidor_mobile,
        "procesar_y_revalidar_envio_mobile",
        lambda _repo, envio_id, **kwargs: usados.append((envio_id, kwargs["proveedor_ocr"])),
    )
    autenticador = mobile.AutenticadorMobile(
        {"operador": {"chofer_id": "chofer-1", "password_hash": mobile.hash_password("secreto")}},
        "secreto-prueba-ocr-mobile",
    )
    servidor = servidor_mobile.crear_servidor("127.0.0.1", 0, raiz=tmp_path, autenticador=autenticador)
    hilo = threading.Thread(target=servidor.serve_forever, daemon=True)
    hilo.start()
    try:
        login = urllib.request.Request(
            f"http://127.0.0.1:{servidor.server_port}/api/mobile/login",
            data=json.dumps({"usuario": "operador", "password": "secreto"}).encode(),
            headers={"Content-Type": "application/json"}, method="POST",
        )
        token = json.load(urllib.request.urlopen(login))["token"]
        for _ in range(2):
            cuerpo, tipo = _multipart(str(uuid.uuid4()))
            solicitud = urllib.request.Request(
                f"http://127.0.0.1:{servidor.server_port}/api/mobile/envios", data=cuerpo,
                headers={"Content-Type": tipo, "Authorization": f"Bearer {token}"}, method="POST",
            )
            assert json.load(urllib.request.urlopen(solicitud))["resultado"] == "ACEPTADO"
        servidor.ejecutor.shutdown(wait=True)  # type: ignore[attr-defined]
        assert len(usados) == 2
        assert usados[0][1] is usados[1][1] is proveedor
    finally:
        servidor.shutdown()
        servidor.server_close()
    assert proveedor.cierres == 1


def test_cloud_simulado_no_crea_proveedor_ocr(monkeypatch):
    creado = []
    imagen = b"jpeg-cloud"

    class Repo:
        def __init__(self):
            self.registro = {"envio_id": "uno", "estado": "RECIBIDO"}

        def recibir(self, **_kwargs):
            return self.registro, True

        def cargar(self, _envio_id):
            return self.registro

        def guardar(self, _envio_id, registro):
            self.registro = dict(registro)

        def historial(self):
            return [self.registro]

    def json_cloud(_base, ruta, _token, **_kwargs):
        if ruta.endswith("pendientes"):
            return {"envios": [{"envio_id": "uno"}]}
        if ruta.endswith("/lease"):
            return {
                "lease_token": "lease", "imagen_mime": "image/jpeg", "imagen_bytes": len(imagen),
                "imagen_sha256": hashlib.sha256(imagen).hexdigest(), "descarga_url": "https://cloud/uno",
                "empresa_id": "empresa", "documento_id": "doc", "chofer_id": "chofer",
            }
        if ruta.endswith("/renovar"):
            return {"estado": "EN_LEASE"}
        if ruta.endswith("/confirmar"):
            return {"estado": "COMPLETADO"}
        raise AssertionError(ruta)

    monkeypatch.setattr(cloud, "crear_proveedor_ocr", lambda: creado.append(True))
    monkeypatch.setattr(cloud, "_json", json_cloud)
    monkeypatch.setattr(cloud, "_descargar", lambda *_a, **_k: imagen)
    monkeypatch.setattr(cloud, "_marcar_aterrizado_cloud", lambda *_a, **_k: None)
    monkeypatch.setattr(cloud, "_procesar_envio_cloud", lambda *_a, **_k: {"completado": True})

    resultado = cloud.sincronizar_envios_cloud(
        base_url="https://cloud", token_motor="token", consumidor="motor", repositorio=Repo(), procesar=True,
    )

    assert resultado["confirmados"] == ["uno"]
    assert creado == []


def test_cloud_no_crea_ocr_para_envio_ya_procesado(monkeypatch):
    creado = []
    llamadas = []

    class Repo:
        def cargar(self, _envio_id):
            return {"estado": "ASOCIADO"}

    # Sin `proveedor_ocr` en la firma: si el consumidor lo pasara para un
    # envío ya procesado, esta llamada fallaría. El consumidor PULL siempre
    # difiere la reconciliación global (P0 BLOQUEO MOBILE, 5371e42).
    def revalidar_previo(_repositorio, envio_id, *, dataset=None, carpeta_catalogos=None,
                         diferir_reconciliacion_bandeja=False):
        llamadas.append((envio_id, dataset, carpeta_catalogos, diferir_reconciliacion_bandeja))
        return {"procesamiento_ok": True, "reconciliacion_ok": True}

    monkeypatch.setattr(cloud, "crear_proveedor_ocr", lambda: creado.append(True))
    monkeypatch.setattr(cloud, "procesar_y_revalidar_envio_mobile", revalidar_previo)

    salida = cloud._procesar_envio_cloud(
        Repo(), "ya-procesado", dataset=None, carpeta_catalogos=None,
        obtener_proveedor_ocr=cloud.crear_proveedor_ocr,
    )

    assert salida == {"completado": True}
    assert llamadas == [("ya-procesado", None, None, True)]
    assert creado == []


def test_cloud_cierra_proveedor_si_ocurre_excepcion_inesperada(monkeypatch):
    proveedor = _Proveedor()
    imagen = b"jpeg-cloud"

    class Repo:
        def __init__(self):
            self.registro = {"envio_id": "uno", "estado": "RECIBIDO"}

        def recibir(self, **_kwargs):
            return self.registro, True

        def cargar(self, _envio_id):
            return self.registro

        def guardar(self, _envio_id, registro):
            self.registro = dict(registro)

        def historial(self):
            return [self.registro]

    def json_cloud(_base, ruta, _token, **_kwargs):
        if ruta.endswith("pendientes"):
            return {"envios": [{"envio_id": "uno"}]}
        if ruta.endswith("/lease"):
            return {
                "lease_token": "lease", "imagen_mime": "image/jpeg", "imagen_bytes": len(imagen),
                "imagen_sha256": hashlib.sha256(imagen).hexdigest(), "descarga_url": "https://cloud/uno",
                "empresa_id": "empresa", "documento_id": "doc", "chofer_id": "chofer",
            }
        raise AssertionError(ruta)

    monkeypatch.setattr(cloud, "crear_proveedor_ocr", lambda: proveedor)
    monkeypatch.setattr(cloud, "_json", json_cloud)
    monkeypatch.setattr(cloud, "_descargar", lambda *_a, **_k: imagen)
    monkeypatch.setattr(cloud, "_marcar_aterrizado_cloud", lambda *_a, **_k: None)
    usados = []

    def procesamiento_simulado(*_args, **kwargs):
        obtener = kwargs["obtener_proveedor_ocr"]
        usados.extend((obtener(), obtener()))
        raise RuntimeError("inesperado")

    monkeypatch.setattr(cloud, "_procesar_envio_cloud", procesamiento_simulado)

    try:
        cloud.sincronizar_envios_cloud(
            base_url="https://cloud", token_motor="token", consumidor="motor", repositorio=Repo(), procesar=True,
        )
        assert False, "la excepción inesperada debe propagarse"
    except RuntimeError as as_error:
        assert str(as_error) == "inesperado"
    assert usados == [proveedor, proveedor]
    assert proveedor.cierres == 1
