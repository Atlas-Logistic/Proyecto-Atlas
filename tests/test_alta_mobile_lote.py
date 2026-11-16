from __future__ import annotations
import json
import sqlite3
from types import SimpleNamespace
import pytest
import alta_mobile_lote as lote
import alta_chofer_mobile as alta
from atlas_core.mobile import hash_password
from test_alta_chofer_mobile import raiz as raiz_base, EscritorFalso
from atlas_core.exclusion_local import TurnoEscritura

@pytest.fixture
def raiz(raiz_base):
    ruta = raiz_base / 'catalogos_privados' / 'usuarios_mobile.json'
    with TurnoEscritura(raiz_base):
        datos = json.loads(ruta.read_text(encoding='utf-8'))
        del datos['usuarios']['jose.lazcano']
        ruta.write_text(json.dumps(datos), encoding='utf-8')
    return raiz_base

PASSWORD = 'synthetic-secret-98'
CUENTA = ('nuevo.test', '10833150K', 'JOSE LAZCANO', 'Jose Lazcano')

class Cloud:
    EMPRESA = 'empresa-prueba-javier'
    D1 = 'synthetic'
    def __init__(self):
        self.db = sqlite3.connect(':memory:')
        self.db.execute('CREATE TABLE mobile_usuarios_cloud (usuario_id TEXT PRIMARY KEY, empresa_id TEXT, chofer_id TEXT, nombre_usuario TEXT UNIQUE, nombre_chofer TEXT, password_hash TEXT, activo INTEGER, creado_en TEXT)')
        self.db.row_factory = sqlite3.Row
        self.publicaciones = 0
    def sql_texto(self, s): return "'" + s.replace("'", "''") + "'"
    def hash_cloud(self, p): return hash_password(p)
    def sentencia_upsert(self, **k):
        q = self.sql_texto
        return ('INSERT INTO mobile_usuarios_cloud (usuario_id, empresa_id, chofer_id, nombre_usuario, nombre_chofer, password_hash, activo, creado_en) VALUES (' +
                ','.join(q(x) for x in ('id', k['empresa_id'], k['chofer_id'], k['usuario'], k['nombre_chofer'], k['password_hash'])) + ",1,'now') ON CONFLICT(nombre_usuario) DO UPDATE SET activo=1;")
    def cuenta_local(self, path, user): return json.loads(path.read_text(encoding='utf-8'))['usuarios'][user]
    def wrangler(self, *args):
        sql = args[-1]
        try:
            cursor = self.db.execute(sql)
            rows = [dict(x) for x in cursor.fetchall()] if cursor.description else []
            changes = cursor.rowcount if cursor.rowcount >= 0 else 0
            if sql.startswith('INSERT'): self.publicaciones += changes
            return SimpleNamespace(returncode=0, stdout=json.dumps([{'success': True, 'results': rows, 'meta': {'changes': changes}}]))
        except sqlite3.Error:
            return SimpleNamespace(returncode=1, stdout='')

def ejecutar_real(raiz, **kwargs):
    return alta.ejecutar(raiz, fabrica_escritor=lambda r: EscritorFalso(r), **kwargs)

def test_flujo_completo_mantiene_catalogo_y_usa_clave_una_vez(raiz):
    c = Cloud()
    antes = (raiz / 'catalogos_privados' / 'choferes.json').read_bytes()
    recibidas = []
    resultado = lote.procesar(raiz, c, CUENTA, PASSWORD, ejecutar=ejecutar_real,
                              ingreso=lambda u, p, r: (recibidas.append((u, p, r)) or True, 200, 'identidad verificada'))
    assert resultado.startswith('HABILITADO')
    assert recibidas == [('nuevo.test', PASSWORD, '10833150K')]
    assert (raiz / 'catalogos_privados' / 'choferes.json').read_bytes() == antes
    assert c.publicaciones == 1
    assert PASSWORD not in resultado

def test_duplicado_d1_impide_alta_local(raiz):
    c = Cloud()
    c.db.execute("INSERT INTO mobile_usuarios_cloud VALUES ('otro', 'empresa', '10833150K', 'otro', '', 'hash', 1, 'now')")
    antes = (raiz / 'catalogos_privados' / 'usuarios_mobile.json').read_bytes()
    assert 'duplicado' in lote.procesar(raiz, c, CUENTA, PASSWORD, ejecutar=ejecutar_real)
    assert (raiz / 'catalogos_privados' / 'usuarios_mobile.json').read_bytes() == antes

def test_publicacion_no_reemplaza_si_aparece_duplicado():
    c = Cloud()
    c.db.execute("INSERT INTO mobile_usuarios_cloud VALUES ('otro', 'empresa', '10833150K', 'otro', '', 'hash', 1, 'now')")
    with pytest.raises(RuntimeError): lote.publicar(c, CUENTA[0], CUENTA[1], CUENTA[3], PASSWORD)
    assert c.db.execute('SELECT count(*) FROM mobile_usuarios_cloud').fetchone()[0] == 1

def test_login_fallido_informa_estado_individual(raiz):
    c = Cloud()
    resultado = lote.procesar(raiz, c, CUENTA, PASSWORD, ejecutar=ejecutar_real, ingreso=lambda *_: (False, 401, 'CREDENCIALES_INVALIDAS'))
    assert resultado.startswith('PENDIENTE: local y D1 verificadas')
    assert 'HTTP 401, CREDENCIALES_INVALIDAS' in resultado
    assert PASSWORD not in resultado

def test_escritor_no_disponible_no_publica(raiz):
    c = Cloud()
    def sin_escritor(*args, **kwargs): raise alta.ErrorAlta('ESCRITOR_OCUPADO', 'ocupado')
    resultado = lote.procesar(raiz, c, CUENTA, PASSWORD, ejecutar=sin_escritor)
    assert 'ESCRITOR_OCUPADO' in resultado
    assert c.publicaciones == 0



def test_lanzador_captura_una_vez_por_cuenta_y_continua(monkeypatch, tmp_path, capsys):
    local = tmp_path / 'Atlas'
    local.mkdir()
    (local / 'desktop_operacion.json').write_text(json.dumps({'raiz': str(tmp_path)}), encoding='utf-8')
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path))
    monkeypatch.setattr(lote.sys.stdin, 'isatty', lambda: True)
    monkeypatch.setattr(lote.sys.stderr, 'isatty', lambda: True)
    monkeypatch.setattr(lote, 'cargar_cloud', lambda: object())
    monkeypatch.setattr(lote.alta, 'ejecutar', lambda *a, **kw: None)
    monkeypatch.setattr(lote, 'coincidencias', lambda *a: [])
    capturas = []
    monkeypatch.setattr(lote.getpass, 'getpass', lambda prompt: capturas.append(prompt) or PASSWORD)
    monkeypatch.setattr(lote, 'procesar', lambda r, c, cuenta, p: 'PENDIENTE: ensayo' if cuenta == lote.CUENTAS[1] else 'HABILITADO: ensayo')
    lote.main()
    salida = capsys.readouterr().out
    assert len(capturas) == 5
    assert salida.count('HABILITADO') == 4 and salida.count('PENDIENTE') == 1
    assert PASSWORD not in salida

def test_login_envia_agente_oficial_y_verifica_identidad(monkeypatch):
    from io import BytesIO
    class Respuesta:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self): return json.dumps({'token': 'secreto-sintetico', 'chofer_id': CUENTA[1]}).encode()
    def abrir(req, timeout):
        assert req.get_header('User-agent') == 'Atlas-Migracion-Usuarios/1.0'
        return Respuesta()
    monkeypatch.setattr(lote.urllib.request, 'urlopen', abrir)
    resultado = lote.login(CUENTA[0], PASSWORD, CUENTA[1])
    assert resultado == (True, 200, 'identidad verificada')
    assert 'secreto-sintetico' not in str(resultado)
    assert lote.login(CUENTA[0], PASSWORD, 'otro-rut')[0] is False

@pytest.mark.parametrize('status,body,detalle', [
    (403, b'error code: 1010', 'error code: 1010'),
    (401, b'{"error":"CREDENCIALES_INVALIDAS"}', 'CREDENCIALES_INVALIDAS'),
    (500, b'{"error":"secreto sensible", "token":"abc"}', 'respuesta no reconocida'),
])
def test_login_informa_http_sin_revelar_cuerpo(monkeypatch, status, body, detalle):
    from io import BytesIO
    def abrir(req, timeout):
        raise lote.urllib.error.HTTPError(req.full_url, status, 'fallo', {}, BytesIO(body))
    monkeypatch.setattr(lote.urllib.request, 'urlopen', abrir)
    assert lote.login(CUENTA[0], PASSWORD, CUENTA[1]) == (False, status, detalle)
