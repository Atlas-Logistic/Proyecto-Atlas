"""Regresion del aislamiento: ninguna ruta predeterminada usa el perfil real."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


def test_perfil_temporal_tambien_aisla_hijos_python(tmp_path):
    local = Path(os.environ['LOCALAPPDATA'])
    home = Path.home()
    assert local.is_relative_to(home)
    assert Path(os.environ['ATLAS_OPERACION_CONFIG']).is_relative_to(local)
    assert not Path(os.environ['ATLAS_OPERACION_CONFIG']).exists()  # No se copia autorizacion real.
    codigo = "import os,pathlib,json; print(json.dumps({'local':os.environ['LOCALAPPDATA'],'home':str(pathlib.Path.home())}))"
    hijo = json.loads(subprocess.check_output([sys.executable, '-I', '-c', codigo], text=True))
    assert hijo == {'local': str(local), 'home': str(home)}


def test_pytest_aisla_coleccion_fallbacks_y_bloquea_mutaciones_absolutas(tmp_path):
    repo = Path(__file__).resolve().parents[1]
    suite = tmp_path / 'suite'
    suite.mkdir()
    shutil.copyfile(repo / 'tests' / 'conftest.py', suite / 'conftest.py')
    # Simula la carpeta real con un archivo ESCRIBIBLE; nunca intenta modificar
    # la autorizacion del operador. El hijo debe proteger este perfil heredado.
    perfil = tmp_path / 'usuario_real_simulado'
    local = perfil / 'AppData' / 'Local'
    real = local / 'Atlas'
    real.mkdir(parents=True)
    politica = real / 'desktop_operacion.json'
    politica.write_text('{"autorizada": true, "sentinela": "conservar"}', encoding='utf8')
    antes = (hashlib.sha256(politica.read_bytes()).hexdigest(), politica.stat().st_mtime_ns)
    (suite / 'test_perfil.py').write_text(r''' 
import json, os, shutil, subprocess, sys
from pathlib import Path
import pytest
# Esto corre DURANTE COLECCION, antes de cualquier fixture.
real = Path(os.environ['ATLAS_REAL_SIMULADO'])
local_coleccion = Path(os.environ['LOCALAPPDATA'])
assert not local_coleccion.is_relative_to(real.parent)
for nombre in ['ATLAS_CACHE_DIR','ATLAS_DIAGNOSTICO_DIR','ATLAS_OPERACION_CONFIG','ATLAS_PADDLE_RUNTIME','ATLAS_PULL_LOG_DIR']:
    assert Path(os.environ[nombre]).is_relative_to(local_coleccion)
marca = local_coleccion / 'Atlas' / 'coleccion.txt'
marca.parent.mkdir(parents=True)
marca.write_text('solo temporal')

def test_fallbacks_sin_overrides(tmp_path, monkeypatch):
    from atlas_core.desktop_operacion import sesion
    from atlas_core.exclusividad_equipo import ruta_politica, politica_equipo_unico
    from atlas_core.escritor_operativo import ruta_identidad_escritor, identidad_escritor
    from atlas_core.paddle_runtime import ruta_runtime_paddle
    from atlas_core.registro_ciclo_pull import directorio_ciclos
    from atlas_core.reconciliacion_estado_derivado import _ruta_log_diagnostico_reconciliacion
    from atlas_core.revalidacion_documental import _ruta_cache_relaciones_historicas
    for nombre in ['ATLAS_CACHE_DIR','ATLAS_DIAGNOSTICO_DIR','ATLAS_OPERACION_CONFIG','ATLAS_PADDLE_RUNTIME','ATLAS_PULL_LOG_DIR','ATLAS_ESCRITOR_ID']:
        monkeypatch.delenv(nombre, raising=False)
    local = Path(os.environ['LOCALAPPDATA'])
    assert local != local_coleccion  # Un perfil nuevo por test.
    assert politica_equipo_unico(tmp_path) is None
    rutas = [ruta_politica(), ruta_identidad_escritor(), ruta_runtime_paddle(),
             directorio_ciclos(), _ruta_log_diagnostico_reconciliacion(),
             _ruta_cache_relaciones_historicas(tmp_path)]
    assert all(p.is_relative_to(local) for p in rutas)
    with sesion(tmp_path):
        assert (local / 'Atlas' / 'cache').is_dir()  # Ignora ATLAS_CACHE_DIR.
    assert identidad_escritor().startswith('pc-')
    for p in rutas:
        p.parent.mkdir(parents=True, exist_ok=True)
    # Fallbacks que ignoran/eliminan tambien LOCALAPPDATA.
    monkeypatch.delenv('LOCALAPPDATA')
    home = Path.home()
    for p in [ruta_identidad_escritor(), ruta_runtime_paddle(), directorio_ciclos(),
              _ruta_log_diagnostico_reconciliacion(), _ruta_cache_relaciones_historicas(tmp_path)]:
        assert p.is_relative_to(home)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text('solo prueba', encoding='utf8')
    child = subprocess.check_output([sys.executable, '-I', '-c',
        'from pathlib import Path; print(Path.home())'], text=True).strip()
    assert Path(child) == home

def test_rutas_absolutas_no_pueden_tocar_configuracion_heredada():
    politica = real / 'desktop_operacion.json'
    for accion in [lambda: politica.write_text('borrada'), lambda: politica.unlink(),
                   lambda: politica.rename(real / 'otra.json'),
                   lambda: shutil.rmtree(real), lambda: real.rename(real.parent / 'movida'),
                   lambda: os.chmod(politica, 0o600), lambda: os.utime(politica, None),
                   lambda: os.open(politica, os.O_WRONLY | os.O_TRUNC)]:
        with pytest.raises(PermissionError, match='configuracion real de Atlas protegida'):
            accion()
    assert 'conservar' in politica.read_text(encoding='utf8')
''', encoding='utf8')
    env = os.environ.copy()
    env.update(LOCALAPPDATA=str(local), APPDATA=str(perfil / 'AppData' / 'Roaming'),
               USERPROFILE=str(perfil), HOME=str(perfil), HOMEDRIVE=perfil.drive,
               HOMEPATH=str(perfil)[len(perfil.drive):], ATLAS_REAL_SIMULADO=str(real),
               PYTHONPATH=str(repo))
    # Overrides heredados incorrectos tampoco deben escapar del aislamiento.
    for nombre in ['ATLAS_CACHE_DIR', 'ATLAS_DIAGNOSTICO_DIR', 'ATLAS_OPERACION_CONFIG',
                   'ATLAS_PADDLE_RUNTIME', 'ATLAS_PULL_LOG_DIR']:
        env[nombre] = str(politica if nombre == 'ATLAS_OPERACION_CONFIG' else real)
    p = subprocess.run([sys.executable, '-m', 'pytest', '-q', '--confcutdir=' + str(suite), str(suite)],
                       cwd=repo, env=env, text=True, capture_output=True, timeout=60)
    assert p.returncode == 0, p.stdout + p.stderr
    assert '2 passed' in p.stdout
    assert (hashlib.sha256(politica.read_bytes()).hexdigest(), politica.stat().st_mtime_ns) == antes
    assert list(real.iterdir()) == [politica]
