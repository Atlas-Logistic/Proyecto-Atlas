import json
from pathlib import Path
import pytest
import verificar_mobile_lote as check
from atlas_core.mobile import hash_password
from test_alta_mobile_lote import Cloud, CUENTA, PASSWORD, raiz, raiz_base, ejecutar_real


def preparar(raiz):
    cloud = Cloud()
    ejecutar_real(raiz, usuario=CUENTA[0], rut=CUENTA[1], nombre=CUENTA[2], existente=True, pedir=lambda _: PASSWORD)
    cloud.db.execute('INSERT INTO mobile_usuarios_cloud VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                     ('id', cloud.EMPRESA, CUENTA[1], CUENTA[0], CUENTA[3], cloud.hash_cloud(PASSWORD), 1, 'now'))
    return cloud


def test_compara_dos_hashes_sin_escrituras_ni_login(raiz):
    cloud = preparar(raiz)
    antes_db = cloud.db.total_changes
    path = raiz / 'catalogos_privados' / 'usuarios_mobile.json'
    antes = path.read_bytes()
    salida = check.verificar(raiz, cloud, CUENTA, PASSWORD, consulta=check.lote.consultar)
    assert salida == 'CREDENCIAL LOCAL Y D1 COINCIDE; acceso real no comprobado'
    assert cloud.db.total_changes == antes_db and path.read_bytes() == antes
    assert PASSWORD not in salida


def test_clave_incorrecta_y_usuario_inactivo(raiz):
    cloud = preparar(raiz)
    assert 'local no coincide' in check.verificar(raiz, cloud, CUENTA, 'no-es-la-clave', consulta=check.lote.consultar)
    cloud.db.execute('UPDATE mobile_usuarios_cloud SET activo=0')
    assert 'inactiva' in check.verificar(raiz, cloud, CUENTA, PASSWORD, consulta=check.lote.consultar)


def test_credencial_d1_distinta_no_confirma_acceso(raiz):
    cloud = preparar(raiz)
    cloud.db.execute('UPDATE mobile_usuarios_cloud SET password_hash=?', (cloud.hash_cloud('otra-clave-sintetica'),))
    assert 'D1 no coincide' in check.verificar(raiz, cloud, CUENTA, PASSWORD, consulta=check.lote.consultar)


def test_consulta_sensible_no_registra_respuesta(monkeypatch):
    from types import SimpleNamespace
    cloud = SimpleNamespace(wrangler_js=lambda: 'wrangler.js', D1='prueba', RAIZ_CLOUD='.')
    def run(args, **kwargs):
        assert kwargs['env']['WRANGLER_WRITE_LOGS'] == 'false'
        assert kwargs['capture_output'] is True
        return SimpleNamespace(returncode=0, stdout=json.dumps([{'success': True, 'results': [{'password_hash': 'hash-sintetico'}]}]))
    monkeypatch.setattr(check.subprocess, 'run', run)
    assert check.consultar_sensible(cloud, 'SELECT') == [{'password_hash': 'hash-sintetico'}]


def test_una_captura_por_usuario_sin_exponer(monkeypatch, tmp_path, capsys):
    local = tmp_path / 'Atlas'
    local.mkdir()
    (local / 'desktop_operacion.json').write_text(json.dumps({'raiz': str(tmp_path)}), encoding='utf-8')
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path))
    monkeypatch.setattr(check.sys.stdin, 'isatty', lambda: True)
    monkeypatch.setattr(check.sys.stderr, 'isatty', lambda: True)
    monkeypatch.setattr(check.lote, 'cargar_cloud', lambda: object())
    llamadas = []
    monkeypatch.setattr(check.getpass, 'getpass', lambda prompt: llamadas.append(prompt) or PASSWORD)
    monkeypatch.setattr(check, 'verificar', lambda *args: 'CREDENCIAL COINCIDE; acceso real no comprobado')
    check.main()
    salida = capsys.readouterr().out
    assert len(llamadas) == 5 and salida.count('CREDENCIAL COINCIDE') == 5
    assert PASSWORD not in salida
