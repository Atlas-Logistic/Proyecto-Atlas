import hashlib
from pathlib import Path
from unittest.mock import patch

import pytest

from atlas_core.mobile import RepositorioEnviosMobile, ErrorEnvioMobile
from atlas_core.guardia_pull import proteger_escrituras
from atlas_core import estado_confirmado as ec, escritor_operativo as eo
from test_estado_confirmado import CloudFalsa, Equipo

FOTO = b"fotografia sintetica original"
ENVIO = "envio-sintetico-123"
META = {"empresa_id": "e", "documento_id": "d", "chofer_id": "c", "capturado_en": "2026-11-19", "planta_origen_informada": "AZA_COLINA"}


def recibir(repo, foto=FOTO, mime="image/jpeg"):
    return repo.recibir(envio_id=ENVIO, imagen=foto, mime=mime, metadata=META)


def test_recibir_completo_reintento_sin_modificar_estado_ni_archivos(tmp_path):
    repo = RepositorioEnviosMobile(tmp_path)
    registro, creado = recibir(repo)
    assert creado
    registro["estado"] = "ASOCIADO"
    registro["confirmacion_humana"] = "conservada"
    repo.guardar(ENVIO, registro)
    ruta = repo.raiz / ENVIO / "original.jpg"
    json_antes = (ruta.parent / "envio.json").read_bytes()
    stat = ruta.stat().st_mtime_ns
    repetido, creado = recibir(repo)
    assert not creado and repetido == registro
    assert ruta.read_bytes() == FOTO and ruta.stat().st_mtime_ns == stat
    assert (ruta.parent / "envio.json").read_bytes() == json_antes


@pytest.mark.parametrize("corrupta", [False, True])
def test_repara_foto_sin_cambiar_json_y_repeticion_es_idempotente(tmp_path, corrupta):
    repo = RepositorioEnviosMobile(tmp_path)
    recibir(repo)
    ruta = repo.raiz / ENVIO / "original.jpg"
    registro = repo.cargar(ENVIO)
    registro.update(estado="ERROR", error="foto ausente")
    repo.guardar(ENVIO, registro)
    antes = (ruta.parent / "envio.json").read_bytes()
    if corrupta: ruta.write_bytes(b"alterada")
    else: ruta.unlink()
    assert recibir(repo) == (registro, False)
    assert ruta.read_bytes() == FOTO
    assert (ruta.parent / "envio.json").read_bytes() == antes
    assert recibir(repo) == (registro, False)


def test_rechaza_imagen_de_otro_documento_y_metadata_invalida(tmp_path):
    repo = RepositorioEnviosMobile(tmp_path)
    recibir(repo)
    ruta = repo.raiz / ENVIO / "original.jpg"
    ruta.unlink()
    with pytest.raises(ErrorEnvioMobile, match="identidad"):
        recibir(repo, b"imagen distinta")
    assert not ruta.exists() and repo.cargar(ENVIO)["estado"] == "RECIBIDO"


def test_corte_antes_de_replace_no_publica_foto_parcial_y_reintenta(tmp_path, monkeypatch):
    repo = RepositorioEnviosMobile(tmp_path)
    recibir(repo)
    ruta = repo.raiz / ENVIO / "original.jpg"
    ruta.unlink()
    import atlas_core.mobile as mobile
    reemplazar = mobile.os.replace
    def corte(origen, destino):
        if Path(destino) == ruta:
            raise OSError("corte sintetico")
        return reemplazar(origen, destino)
    monkeypatch.setattr(mobile.os, "replace", corte)
    with pytest.raises(OSError, match="corte sintetico"):
        recibir(repo)
    assert not ruta.exists() and repo.cargar(ENVIO)["estado"] == "RECIBIDO"
    monkeypatch.setattr(mobile.os, "replace", reemplazar)
    recibir(repo)
    assert ruta.read_bytes() == FOTO


def test_custodia_v2_confirma_reparacion_y_siguiente_alineacion_la_conserva(tmp_path, monkeypatch):
    cloud = CloudFalsa(protocolo_minimo=2)
    equipo = Equipo(tmp_path, "casa", cloud)
    repo = RepositorioEnviosMobile(equipo.raiz)
    recibir(repo)
    ruta = repo.raiz / ENVIO / "original.jpg"
    ruta.unlink()
    monkeypatch.setattr(eo, "_json", cloud.json)
    monkeypatch.setattr(ec.ClienteEstado, "_crudo", lambda c, h, **kw: cloud.crudo(c, h, **kw))
    with equipo.lease() as lease:
        assert lease.adquirir()
        with proteger_escrituras(equipo.raiz, lambda: lease.vigente):
            recibir(repo)
        confirmacion = lease.custodia.confirmar(lease)
        assert confirmacion["confirmados"] == 1
    rel = f"operacion/mobile/envios/{ENVIO}/original.jpg"
    assert cloud._vigentes()[rel][0] == hashlib.sha256(FOTO).hexdigest()
    ruta.write_bytes(b"copia antigua")
    with equipo.lease() as siguiente:
        assert siguiente.adquirir()
        assert ruta.read_bytes() == FOTO


def test_guardia_rechaza_reparacion_sin_lease(tmp_path):
    repo = RepositorioEnviosMobile(tmp_path)
    recibir(repo)
    ruta = repo.raiz / ENVIO / "original.jpg"
    ruta.unlink()
    with pytest.raises(PermissionError):
        with proteger_escrituras(tmp_path, lambda: False):
            recibir(repo)
    assert not ruta.exists()


def test_error_persistido_descarga_repara_pero_no_procesa_ni_confirma(tmp_path, monkeypatch):
    import atlas_core.cloud_mobile_sync_cliente as sync
    repo = RepositorioEnviosMobile(tmp_path)
    registro, _ = recibir(repo)
    registro.update(estado="ERROR", error="original.jpg ausente")
    repo.guardar(ENVIO, registro)
    ruta = repo.raiz / ENVIO / "original.jpg"
    ruta.unlink()
    antes = (ruta.parent / "envio.json").read_bytes()
    llamadas = []
    sha = hashlib.sha256(FOTO).hexdigest()
    def json_cloud(base, ruta_api, token, **kwargs):
        llamadas.append(ruta_api)
        if ruta_api.endswith("pendientes"):
            return {"envios": [{"envio_id": ENVIO, "imagen_sha256": sha}]}
        if ruta_api.endswith("/lease"):
            return {"envio_id": ENVIO, "lease_token": "lease", "empresa_id": "empresa-prueba-javier", "documento_id": "d", "chofer_id": "c", "imagen_mime": "image/jpeg", "imagen_bytes": len(FOTO), "imagen_sha256": sha, "descarga_url": "https://cloud.test/imagen", "planta_origen_informada": "AZA_COLINA"}
        if ruta_api.endswith("/renovar"): return {"estado": "EN_LEASE"}
        raise AssertionError(ruta_api)
    monkeypatch.setattr(sync, "_json", json_cloud)
    monkeypatch.setattr(sync, "_descargar", lambda *a, **k: FOTO)
    monkeypatch.setattr(sync, "_procesar_envio_cloud", lambda *a, **k: pytest.fail("no debe procesar"))
    resultado = sync.sincronizar_envios_cloud(base_url="https://cloud.test", token_motor="t", consumidor="motor", repositorio=repo, procesar=True, lease_heartbeat_segundos=0)
    assert ruta.read_bytes() == FOTO
    assert (ruta.parent / "envio.json").read_bytes() == antes
    assert ENVIO in resultado["omitidos_error_persistido"]
    assert not any(r.endswith("/confirmar") for r in llamadas)
    llamadas.clear()
    sync.sincronizar_envios_cloud(base_url="https://cloud.test", token_motor="t", consumidor="motor", repositorio=repo, procesar=True, lease_heartbeat_segundos=0)
    assert not any(r.endswith("/lease") for r in llamadas)


@pytest.mark.parametrize("mime", ["image/png", "image/webp"])
def test_recepcion_otros_formatos_permitidos_siguen_idempotentes(tmp_path, mime):
    repo = RepositorioEnviosMobile(tmp_path)
    registro, _ = recibir(repo, mime=mime)
    ruta = repo.raiz / ENVIO / registro["foto_original"]
    ruta.unlink()
    assert recibir(repo, mime=mime)[1] is False
    assert ruta.read_bytes() == FOTO


def test_error_con_foto_reparada_permite_recuperacion_explicita_sin_duplicar(tmp_path, monkeypatch):
    import csv
    import atlas_core.mobile as mobile
    from test_mobile_recuperacion_error_pre_persistencia import _envio_error
    repo, envio_id, dataset = _envio_error(tmp_path)
    ruta = repo.raiz / envio_id / "original.jpg"
    foto = ruta.read_bytes()
    registro = repo.cargar(envio_id)
    ruta.unlink()
    repo.recibir(envio_id=envio_id, imagen=foto, mime="image/jpeg", metadata=registro)
    assert repo.cargar(envio_id)["estado"] == "ERROR"
    monkeypatch.setattr(mobile, "crear_proveedor_ocr", lambda: object())
    monkeypatch.setattr(mobile, "procesar_archivo", lambda *a, **kw: {"numero_guia": "900001", "numero_transporte": "0000900000", "cliente": "CLIENTE"})
    resultado = mobile.recuperar_envio_mobile_error_pre_persistencia(repo, envio_id, dataset=dataset, puede_escribir=lambda: True)
    assert resultado["recuperacion_error_pre_persistencia"]["estado"] == "COMPLETADA"
    with dataset.open(encoding="utf-8-sig", newline="") as archivo:
        filas = list(csv.DictReader(archivo, delimiter=";"))
    assert sum(f["archivo"] == f"mobile/{envio_id}/original.jpg" for f in filas) == 1
    with pytest.raises(ErrorEnvioMobile):
        mobile.recuperar_envio_mobile_error_pre_persistencia(repo, envio_id, dataset=dataset, puede_escribir=lambda: True)


def test_foto_incompleta_no_salta_lock_de_procesamiento(tmp_path):
    from atlas_core.almacenamiento_portable import bloqueo_sesion, SesionOcupadaError
    repo = RepositorioEnviosMobile(tmp_path)
    recibir(repo)
    ruta = repo.raiz / ENVIO / "original.jpg"
    ruta.unlink()
    with bloqueo_sesion(repo.raiz, f"mobile_{ENVIO}"):
        with pytest.raises(SesionOcupadaError):
            recibir(repo)
    assert not ruta.exists()
    recibir(repo)
    assert ruta.read_bytes() == FOTO
