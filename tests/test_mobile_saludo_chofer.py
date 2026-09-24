"""El login Mobile expone el nombre CANÓNICO del chofer (`choferes.json`,
clave = `chofer_id`) para el saludo de la app. Sólo presentación: el token
y la autenticación no cambian. Catálogo sintético en `tmp_path`."""
from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from types import SimpleNamespace

import pytest

import servidor_mobile
from atlas_core.mobile import AutenticadorMobile, hash_password


def _servidor(tmp_path, monkeypatch, *, catalogo: dict | None):
    carpeta = None
    if catalogo is not None:
        carpeta = tmp_path / "catalogos"
        carpeta.mkdir()
        (carpeta / "choferes.json").write_text(json.dumps(catalogo, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(servidor_mobile, "validar_fuente_catalogos", lambda *a, **k: SimpleNamespace(ruta=carpeta))
    autenticador = AutenticadorMobile(
        {
            "andres.prueba": {"chofer_id": "111111111", "password_hash": hash_password("secreto-1")},
            "cuenta-prueba": {"chofer_id": "CUENTA_PRUEBA", "password_hash": hash_password("secreto-2")},
        },
        "secreto-de-prueba-saludo-123456789",
    )
    srv = servidor_mobile.crear_servidor("127.0.0.1", 0, raiz=tmp_path, autenticador=autenticador, procesar=False)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def _login(srv, usuario, password):
    solicitud = urllib.request.Request(
        f"http://127.0.0.1:{srv.server_port}/api/mobile/login",
        data=json.dumps({"usuario": usuario, "password": password}).encode(),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.urlopen(solicitud) as respuesta:
            return respuesta.status, json.load(respuesta)
    except urllib.error.HTTPError as error:
        return error.code, json.load(error)


@pytest.fixture()
def cerrar():
    servidores = []
    yield servidores.append
    for srv in servidores:
        srv.shutdown(); srv.server_close(); srv.ejecutor.shutdown(wait=True)


def test_login_incluye_nombre_canonico_del_chofer(tmp_path, monkeypatch, cerrar) -> None:
    srv = _servidor(tmp_path, monkeypatch, catalogo={"111111111": {"nombre": "ANDRES PRUEBA ÑUÑEZ", "activo": True}})
    cerrar(srv)
    codigo, cuerpo = _login(srv, "andres.prueba", "secreto-1")
    assert codigo == 200
    assert cuerpo["nombre_chofer"] == "ANDRES PRUEBA ÑUÑEZ"
    assert cuerpo["chofer_id"] == "111111111" and cuerpo["token"]


def test_cuenta_sin_chofer_canonico_devuelve_nombre_vacio(tmp_path, monkeypatch, cerrar) -> None:
    srv = _servidor(tmp_path, monkeypatch, catalogo={"111111111": {"nombre": "ANDRES PRUEBA"}})
    cerrar(srv)
    codigo, cuerpo = _login(srv, "cuenta-prueba", "secreto-2")
    assert codigo == 200 and cuerpo["nombre_chofer"] == "" and cuerpo["token"]


def test_sin_catalogo_configurado_el_login_sigue_funcionando(tmp_path, monkeypatch, cerrar) -> None:
    srv = _servidor(tmp_path, monkeypatch, catalogo=None)
    cerrar(srv)
    codigo, cuerpo = _login(srv, "andres.prueba", "secreto-1")
    assert codigo == 200 and cuerpo["nombre_chofer"] == ""


def test_credenciales_invalidas_no_exponen_nombre(tmp_path, monkeypatch, cerrar) -> None:
    srv = _servidor(tmp_path, monkeypatch, catalogo={"111111111": {"nombre": "ANDRES PRUEBA"}})
    cerrar(srv)
    codigo, cuerpo = _login(srv, "andres.prueba", "incorrecta")
    assert codigo == 401 and cuerpo == {"error": "credenciales_invalidas"}
