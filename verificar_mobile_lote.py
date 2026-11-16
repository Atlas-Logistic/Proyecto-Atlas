"""Compara credenciales Mobile local y D1 en memoria, sin escribir en D1.

No realiza login: el servicio puede crear una sesion en D1 al autenticar.
"""
import getpass
import json
import os
import subprocess
import sys
import warnings
from pathlib import Path

import alta_mobile_lote as lote
from atlas_core.mobile import verificar_password


def consultar_sensible(cloud, sql):
    # La respuesta contiene un hash: solo en memoria y sin bitacora de Wrangler.
    entorno = {**os.environ, 'WRANGLER_WRITE_LOGS': 'false'}
    resultado = subprocess.run(['node', cloud.wrangler_js(), 'd1', 'execute', cloud.D1,
                                '--remote', '--json', '--command', sql], cwd=cloud.RAIZ_CLOUD,
                               env=entorno, capture_output=True, text=True, encoding='utf-8', errors='replace')
    if resultado.returncode:
        raise RuntimeError('D1 no disponible')
    try:
        datos = json.loads(resultado.stdout)
        if not datos or not all(x.get('success') for x in datos):
            raise ValueError()
        return datos[0]['results']
    except (ValueError, KeyError, TypeError):
        raise RuntimeError('Respuesta D1 no verificable') from None


def verificar(raiz, cloud, cuenta, password, *, consulta=consultar_sensible):
    usuario, rut, _, _ = cuenta
    u = cloud.sql_texto(usuario)
    filas = consulta(cloud, 'SELECT nombre_usuario, chofer_id, empresa_id, activo, password_hash '
                     f'FROM mobile_usuarios_cloud WHERE lower(nombre_usuario)=lower({u})')
    if len(filas) != 1:
        return 'PENDIENTE: cuenta D1 ausente o ambigua'
    remota = filas[0]
    if (remota.get('nombre_usuario') != usuario or remota.get('chofer_id') != rut or
            remota.get('empresa_id') != cloud.EMPRESA or remota.get('activo') != 1):
        return 'PENDIENTE: identidad D1 no coincide o inactiva'
    local = cloud.cuenta_local(raiz / 'catalogos_privados' / 'usuarios_mobile.json', usuario)
    if local.get('chofer_id') != rut:
        return 'PENDIENTE: identidad local no coincide'
    if not verificar_password(password, str(local.get('password_hash', ''))):
        return 'PENDIENTE: credencial local no coincide'
    if not verificar_password(password, str(remota.get('password_hash', ''))):
        return 'PENDIENTE: credencial D1 no coincide'
    return 'CREDENCIAL LOCAL Y D1 COINCIDE; acceso real no comprobado'


def main():
    if not sys.stdin.isatty() or not sys.stderr.isatty():
        raise SystemExit('Se requiere consola interactiva con entrada oculta.')
    warnings.simplefilter('error', getpass.GetPassWarning)
    config = Path(os.environ['LOCALAPPDATA']) / 'Atlas' / 'desktop_operacion.json'
    raiz = Path(json.loads(config.read_text(encoding='utf-8-sig'))['raiz'])
    cloud = lote.cargar_cloud()
    print('Comparacion local y D1: solo lectura; no realiza inicio de sesion.')
    for cuenta in lote.CUENTAS:
        usuario = cuenta[0]
        try:
            password = getpass.getpass(f'Contraseña de {usuario} (entrada oculta): ')
            try:
                print(f'{usuario}: {verificar(raiz, cloud, cuenta, password)}', flush=True)
            finally:
                password = None
        except (EOFError, KeyboardInterrupt):
            print(f'\n{usuario}: PENDIENTE: entrada cancelada', flush=True)
        except Exception as e:
            print(f'{usuario}: PENDIENTE: verificacion no disponible ({type(e).__name__})', flush=True)
    print('Las coincidencias no confirman el inicio de sesion real.')


if __name__ == '__main__':
    main()
