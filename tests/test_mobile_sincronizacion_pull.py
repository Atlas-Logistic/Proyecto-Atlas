"""Bloque MOBILE SINCRONIZACIÓN PULL V1 -- receptor central 24/7 <->
Atlas local.

Pruebas focales, enteramente en `tmp_path` (nunca G:\\ real, ver
consigna del bloque): un servidor HTTP real (`servidor_mobile.crear_
servidor`) hace de RECEPTOR CENTRAL sobre una carpeta `tmp_path` propia;
`atlas_core.mobile_sync_cliente.sincronizar_envios_pendientes` hace de
consumidor PULL de Atlas LOCAL sobre una carpeta `tmp_path` DISTINTA --
dos raíces separadas, exactamente como en producción (VM del receptor
central vs. G:\\ de Javier), nunca la misma carpeta para las dos puntas.

Nunca se usa `AutenticadorMobile` (login de chofer) en estas pruebas --
los envíos se siembran en el central llamando directamente a
`RepositorioEnviosMobile.recibir()` (el mismo camino real que usa
`POST /api/mobile/envios`, sin necesidad de levantar el multipart HTTP
del chofer, que ya cubren test_mobile_m1.py/test_mobile_envio_real.py).
Lo que este archivo ejercita es la conversación NUEVA: receptor central
-> consumidor PULL -> Motor local.
"""
from __future__ import annotations

import hashlib
import json
import threading

import pytest

from atlas_core.almacenamiento_portable import bloqueo_sesion
from atlas_core.mobile import AutenticadorMobile, AutenticadorSincronizacionMobile, RepositorioEnviosMobile, hash_password
from atlas_core.mobile_sync_cliente import ErrorSincronizacionMobile, sincronizar_envios_pendientes
from servidor_mobile import crear_servidor

TOKEN_SYNC = "secreto-de-sincronizacion-de-prueba-123456789"


def _auth_chofer() -> AutenticadorMobile:
    # Nunca se usa en estas pruebas (no hay login de chofer) -- `crear_
    # servidor` lo exige igual, sólo para no romper su firma.
    return AutenticadorMobile(
        {"javier": {"chofer_id": "chofer-1", "password_hash": hash_password("secreto")}},
        "secreto-de-prueba-mobile-sync-123456",
    )


@pytest.fixture()
def receptor_central(tmp_path):
    """Levanta un servidor HTTP real sobre `tmp_path/central` -- el
    RECEPTOR 24/7 en miniatura. `procesar=False`: el central nunca
    procesa nada por sí mismo (esa responsabilidad es exclusiva del
    consumidor PULL / Motor local, ver Sección ARQUITECTURA del bloque)."""
    raiz_central = tmp_path / "central"
    servidor = crear_servidor(
        "127.0.0.1", 0, raiz=raiz_central, autenticador=_auth_chofer(),
        autenticador_sync=AutenticadorSincronizacionMobile(TOKEN_SYNC),
        procesar=False,
    )
    hilo = threading.Thread(target=servidor.serve_forever, daemon=True)
    hilo.start()
    try:
        yield servidor, RepositorioEnviosMobile(raiz_central)
    finally:
        servidor.shutdown()
        servidor.server_close()


def _base_url(servidor) -> str:
    return f"http://127.0.0.1:{servidor.server_port}"


def _sembrar_envio_central(repo_central: RepositorioEnviosMobile, *, envio_id: str, imagen: bytes = b"contenido-jpeg-de-prueba") -> dict:
    registro, nuevo = repo_central.recibir(
        envio_id=envio_id, imagen=imagen, mime="image/jpeg",
        metadata={
            "chofer_id": "chofer-1", "usuario": "javier", "capturado_en": "2026-09-22T18:00:00Z",
            "tipo_novedad": "TIENE_ESTADIA", "guia_firmada_correo": True,
            "planta_origen_informada": "AZA_COLINA", "lote_id": "",
        },
    )
    assert nuevo
    return registro


def _repo_local(tmp_path) -> RepositorioEnviosMobile:
    return RepositorioEnviosMobile(tmp_path / "local_javier")


# ---- 1/2/3: el receptor tiene un envío pendiente; Atlas lo obtiene con
# metadata/chofer/envio_id intactos ----

def test_atlas_obtiene_el_pendiente_con_metadata_intacta(tmp_path, receptor_central):
    servidor, repo_central = receptor_central
    envio_id = "e2e-sync-00000001"
    _sembrar_envio_central(repo_central, envio_id=envio_id)
    repo_local = _repo_local(tmp_path)

    resultado = sincronizar_envios_pendientes(
        base_url=_base_url(servidor), token=TOKEN_SYNC, repositorio=repo_local,
        procesar=False, consumidor="pc-javier-test",
    )

    assert resultado["encontrados"] == 1
    assert resultado["nuevos_sincronizados"] == [envio_id]
    assert resultado["confirmados"] == [envio_id]

    local = repo_local.cargar(envio_id)
    central = repo_central.cargar(envio_id)
    for campo in ("envio_id", "chofer_id", "usuario", "capturado_en", "tipo_novedad", "guia_firmada_correo", "planta_origen_informada"):
        assert local[campo] == central[campo], campo


# Bloque MOBILE OBSERVACIÓN DEL CHOFER V1 -- la observación del chofer
# llega intacta al Atlas local tras el pull (y un envío sin ella, vacía).
def test_observacion_del_chofer_sobrevive_la_sincronizacion(tmp_path, receptor_central):
    servidor, repo_central = receptor_central
    texto = "Guía firmada con observación: Sr. Muñoz\nSegunda vuelta"
    repo_central.recibir(
        envio_id="e2e-sync-obs-0001", imagen=b"contenido-jpeg-de-prueba", mime="image/jpeg",
        metadata={"chofer_id": "chofer-1", "usuario": "javier", "tipo_novedad": "",
                  "planta_origen_informada": "AZA_COLINA", "observacion": texto},
    )
    _sembrar_envio_central(repo_central, envio_id="e2e-sync-obs-0002")
    repo_local = _repo_local(tmp_path)

    sincronizar_envios_pendientes(
        base_url=_base_url(servidor), token=TOKEN_SYNC, repositorio=repo_local,
        procesar=False, consumidor="pc-javier-test",
    )

    assert repo_local.cargar("e2e-sync-obs-0001")["observacion"] == texto
    assert repo_local.cargar("e2e-sync-obs-0002")["observacion"] == ""


# ---- 4: el archivo aterrizado localmente es byte-identical / hash-identical ----

def test_archivo_local_es_byte_identico_y_hash_identico(tmp_path, receptor_central):
    servidor, repo_central = receptor_central
    envio_id = "e2e-sync-00000002"
    imagen_original = b"bytes-reales-de-una-foto-simulada" * 100
    _sembrar_envio_central(repo_central, envio_id=envio_id, imagen=imagen_original)
    repo_local = _repo_local(tmp_path)

    sincronizar_envios_pendientes(base_url=_base_url(servidor), token=TOKEN_SYNC, repositorio=repo_local, procesar=False)

    registro_local = repo_local.cargar(envio_id)
    ruta_imagen_local = repo_local.raiz / envio_id / registro_local["foto_original"]
    contenido_local = ruta_imagen_local.read_bytes()
    assert contenido_local == imagen_original
    assert hashlib.sha256(contenido_local).hexdigest() == registro_local["imagen_sha256"]
    assert registro_local["imagen_sha256"] == repo_central.cargar(envio_id)["imagen_sha256"]


# ---- 5: segundo pull no duplica ----

def test_segundo_pull_no_duplica(tmp_path, receptor_central):
    servidor, repo_central = receptor_central
    envio_id = "e2e-sync-00000003"
    _sembrar_envio_central(repo_central, envio_id=envio_id)
    repo_local = _repo_local(tmp_path)

    primero = sincronizar_envios_pendientes(base_url=_base_url(servidor), token=TOKEN_SYNC, repositorio=repo_local, procesar=False)
    assert primero["nuevos_sincronizados"] == [envio_id]

    segundo = sincronizar_envios_pendientes(base_url=_base_url(servidor), token=TOKEN_SYNC, repositorio=repo_local, procesar=False)
    assert segundo["nuevos_sincronizados"] == []
    # Ya confirmado en el primer pull -> el central ya no debe listarlo.
    assert segundo["encontrados"] == 0

    assert len(list(repo_local.raiz.glob("*/envio.json"))) == 1


# ---- 6: caída durante la descarga (bytes corruptos/incompletos) no deja
# un envío local válido -- se descarta por hash, se reintenta después ----

def test_descarga_corrupta_no_deja_envio_local_parcial(tmp_path, receptor_central, monkeypatch):
    servidor, repo_central = receptor_central
    envio_id = "e2e-sync-00000004"
    _sembrar_envio_central(repo_central, envio_id=envio_id)
    repo_local = _repo_local(tmp_path)

    import atlas_core.mobile_sync_cliente as cliente_mod

    def descarga_corrupta(base_url, token, envio_id_arg, *, timeout):
        return b"bytes-truncados-o-corruptos-que-no-coinciden-con-el-hash"

    monkeypatch.setattr(cliente_mod, "_descargar_imagen", descarga_corrupta)

    resultado = sincronizar_envios_pendientes(base_url=_base_url(servidor), token=TOKEN_SYNC, repositorio=repo_local, procesar=False)

    assert resultado["fallidos_hash"] == [envio_id]
    assert resultado["nuevos_sincronizados"] == []
    assert not (repo_local.raiz / envio_id).exists(), "una descarga corrupta nunca debe dejar ni siquiera la carpeta del envío"
    # Nunca se confirma algo que no se aterrizó -- el central lo sigue
    # listando como pendiente.
    assert repo_central.cargar(envio_id).get("sincronizacion", {}).get("estado") != "SINCRONIZADO_LOCAL"


# ---- 7: tras la caída, un nuevo pull (sin el fallo simulado) recupera el envío ----

def test_reintento_tras_descarga_corrupta_recupera_el_envio(tmp_path, receptor_central, monkeypatch):
    servidor, repo_central = receptor_central
    envio_id = "e2e-sync-00000005"
    imagen_original = b"contenido-real-de-la-foto"
    _sembrar_envio_central(repo_central, envio_id=envio_id, imagen=imagen_original)
    repo_local = _repo_local(tmp_path)

    import atlas_core.mobile_sync_cliente as cliente_mod
    original = cliente_mod._descargar_imagen
    monkeypatch.setattr(cliente_mod, "_descargar_imagen", lambda *a, **k: b"corrupto")
    fallido = sincronizar_envios_pendientes(base_url=_base_url(servidor), token=TOKEN_SYNC, repositorio=repo_local, procesar=False)
    assert fallido["fallidos_hash"] == [envio_id]

    monkeypatch.setattr(cliente_mod, "_descargar_imagen", original)
    recuperado = sincronizar_envios_pendientes(base_url=_base_url(servidor), token=TOKEN_SYNC, repositorio=repo_local, procesar=False)

    assert recuperado["nuevos_sincronizados"] == [envio_id]
    registro_local = repo_local.cargar(envio_id)
    ruta_imagen_local = repo_local.raiz / envio_id / registro_local["foto_original"]
    assert ruta_imagen_local.read_bytes() == imagen_original


# ---- 8: un envío ya existente LOCALMENTE (llegó por LAN directo) no se
# vuelve a descargar ni duplica -- sólo se confirma al central ----

def test_envio_ya_existente_localmente_no_duplica_y_se_confirma(tmp_path, receptor_central):
    servidor, repo_central = receptor_central
    envio_id = "e2e-sync-00000006"
    _sembrar_envio_central(repo_central, envio_id=envio_id)
    repo_local = _repo_local(tmp_path)
    # Simula que este envío YA llegó por LAN directo (mismo envio_id --
    # el chofer reintentó su subida y esta vez sí conectó con el PC de
    # Javier, además de haber quedado antes en el receptor central).
    _sembrar_envio_central(repo_local, envio_id=envio_id)

    resultado = sincronizar_envios_pendientes(base_url=_base_url(servidor), token=TOKEN_SYNC, repositorio=repo_local, procesar=False)

    assert resultado["nuevos_sincronizados"] == []
    assert resultado["ya_existian_localmente"] == [envio_id]
    assert resultado["confirmados"] == [envio_id]
    assert len(list(repo_local.raiz.glob("*/envio.json"))) == 1


# ---- 9: Motor apagado no afecta lo almacenado centralmente ----

def test_motor_apagado_no_afecta_almacenamiento_central(receptor_central):
    """Nunca se ejecuta ningún consumidor en esta prueba -- equivale a
    "el PC de Javier está apagado": el envío sigue disponible, intacto y
    listable en el receptor central sin que nada del lado Motor haya
    corrido."""
    servidor, repo_central = receptor_central
    envio_id = "e2e-sync-00000007"
    registro = _sembrar_envio_central(repo_central, envio_id=envio_id)

    assert registro["estado"] == "RECIBIDO"
    pendientes = repo_central.listar_pendientes_sincronizacion()
    assert [p["envio_id"] for p in pendientes] == [envio_id]
    # La imagen sigue en disco, intacta, sin ningún consumidor local.
    assert (repo_central.raiz / envio_id / registro["foto_original"]).is_file()


# ---- 10: varios envíos se recuperan correctamente en una sola pasada ----

def test_varios_envios_se_recuperan_en_una_pasada(tmp_path, receptor_central):
    servidor, repo_central = receptor_central
    ids = [f"e2e-sync-multi-{i:08d}" for i in range(1, 6)]
    for envio_id in ids:
        _sembrar_envio_central(repo_central, envio_id=envio_id, imagen=f"foto-{envio_id}".encode() * 50)
    repo_local = _repo_local(tmp_path)

    resultado = sincronizar_envios_pendientes(base_url=_base_url(servidor), token=TOKEN_SYNC, repositorio=repo_local, procesar=False)

    assert resultado["encontrados"] == 5
    assert sorted(resultado["nuevos_sincronizados"]) == sorted(ids)
    for envio_id in ids:
        local = repo_local.cargar(envio_id)
        central = repo_central.cargar(envio_id)
        assert local["imagen_sha256"] == central["imagen_sha256"]


# ---- 11: un error de OCR/procesamiento posterior NUNCA transforma una
# recepción/sincronización ya exitosa en un fallo de subida ----

def test_error_de_procesamiento_no_transforma_recepcion_en_fallo(tmp_path, receptor_central, monkeypatch):
    servidor, repo_central = receptor_central
    envio_id = "e2e-sync-00000008"
    _sembrar_envio_central(repo_central, envio_id=envio_id)
    repo_local = _repo_local(tmp_path)

    import atlas_core.mobile as mobile_mod

    def procesar_roto(repositorio, envio_id_arg, *, dataset=None, carpeta_catalogos=None):
        raise RuntimeError("OCR simulado roto")

    monkeypatch.setattr(mobile_mod, "procesar_envio_mobile", procesar_roto)

    resultado = sincronizar_envios_pendientes(
        base_url=_base_url(servidor), token=TOKEN_SYNC, repositorio=repo_local,
        dataset=None, carpeta_catalogos=None, procesar=True,
    )

    # La RECEPCIÓN/sincronización fue exitosa -- eso es lo que el chofer
    # ya vio confirmado en el 202 original, mucho antes de que exista
    # este consumidor.
    assert resultado["nuevos_sincronizados"] == [envio_id]
    assert resultado["confirmados"] == [envio_id]
    assert (repo_local.raiz / envio_id / "envio.json").is_file()
    # El fallo de procesamiento queda reflejado APARTE, nunca deshace lo
    # anterior.
    assert envio_id in resultado["errores_procesamiento"]
    assert "OCR simulado roto" in resultado["errores_procesamiento"][envio_id]


# ---- 12: dos consumidores no producen doble procesamiento (mecanismo
# mínimo del piloto: lock por envío ya existente, reutilizado tal cual) ----

def test_dos_consumidores_no_procesan_el_mismo_envio_dos_veces(tmp_path, receptor_central):
    servidor, repo_central = receptor_central
    envio_id = "e2e-sync-00000009"
    _sembrar_envio_central(repo_central, envio_id=envio_id)
    repo_local = _repo_local(tmp_path)

    # Primer pull: sólo aterriza (no procesa todavía) -- deja el envío
    # local en RECIBIDO, listo para que "dos consumidores" compitan por
    # procesarlo.
    aterrizado = sincronizar_envios_pendientes(base_url=_base_url(servidor), token=TOKEN_SYNC, repositorio=repo_local, procesar=False)
    assert aterrizado["nuevos_sincronizados"] == [envio_id]
    assert repo_local.cargar(envio_id)["estado"] == "RECIBIDO"

    # Simula un "segundo consumidor" (el otro PC de Javier, o una segunda
    # corrida de este mismo script) que ya sostiene el lock de ESTE
    # envío exacto mientras el primero intenta procesar.
    with bloqueo_sesion(repo_local.raiz, f"mobile_{envio_id}"):
        resultado = sincronizar_envios_pendientes(
            base_url=_base_url(servidor), token=TOKEN_SYNC, repositorio=repo_local,
            dataset=None, carpeta_catalogos=None, procesar=True,
        )

    assert resultado["procesados"] == []
    assert resultado["omitidos_por_bloqueo"] == [envio_id]
    # Sigue en RECIBIDO -- nadie alcanzó a tocarlo mientras el lock
    # estaba tomado; el próximo ciclo puede reintentarlo sin riesgo de
    # duplicar el procesamiento.
    assert repo_local.cargar(envio_id)["estado"] == "RECIBIDO"


# ---- extra: receptor central inalcanzable -- error claro, nunca un
# resultado silenciosamente vacío que aparente "nada pendiente" ----

def test_receptor_inalcanzable_lanza_error_claro(tmp_path):
    repo_local = _repo_local(tmp_path)
    with pytest.raises(ErrorSincronizacionMobile):
        sincronizar_envios_pendientes(
            base_url="http://127.0.0.1:1", token=TOKEN_SYNC, repositorio=repo_local, procesar=False, timeout=2.0,
        )


# ---- extra: sin token de sincronización configurado en el receptor
# (`autenticador_sync=None`, mismo default que antes de este bloque), las
# rutas /sync/* quedan simplemente inalcanzables (401 -- nunca 500, nunca
# ejecutan nada) -- el modo LAN histórico (login/envíos de chofer, en un
# código completamente aparte) queda intacto (ver también
# test_mobile_m1.py/test_mobile_envio_real.py, que ya cubren ese modo sin
# `autenticador_sync`) ----

def test_receptor_sin_token_de_sync_configurado_nunca_ejecuta_la_sincronizacion(tmp_path):
    raiz_central = tmp_path / "central_sin_sync"
    servidor = crear_servidor("127.0.0.1", 0, raiz=raiz_central, autenticador=_auth_chofer(), procesar=False)
    hilo = threading.Thread(target=servidor.serve_forever, daemon=True)
    hilo.start()
    try:
        repo_local = _repo_local(tmp_path)
        with pytest.raises(ErrorSincronizacionMobile):
            sincronizar_envios_pendientes(
                base_url=_base_url(servidor), token=TOKEN_SYNC, repositorio=repo_local, procesar=False,
            )
    finally:
        servidor.shutdown()
        servidor.server_close()
