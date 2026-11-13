"""Alta interactiva de cuentas Mobile de choferes existentes (MBT).

Una entrada oculta por cuenta; credencial solo en memoria. No modifica choferes.
El escritor oficial espera por PULL sin detenerlo; si no lo obtiene, se omite la cuenta.
"""
from __future__ import annotations
import getpass
import importlib.util
import json
import os
import sys
import urllib.request
import warnings
from pathlib import Path

import alta_chofer_mobile as alta
from atlas_core.mobile import verificar_password

CLOUD = Path(r'C:\Atlas\Atlas-Mobile-Cloud')
URL = 'https://mobile.dttacgroup.cl/api/mobile/login'
CUENTAS = (
    ('carlo.simon', '154894241', 'CARLOS SIMON', 'Carlo Simon'),
    ('pedro.vasquez', '131820534', 'PEDRO VASQUEZ', 'Pedro Vasquez'),
    ('carlos.nancucheo', '159258882', 'CARLOS ÑANCUCHEO', 'Carlos Ñancucheo'),
    ('ivan.roa', '101904407', 'IVAN ROA', 'Ivan Roa'),
    ('carlos.farias', '98966625', 'CARLOS FARIAS', 'Carlos Farias'),
)


def cargar_cloud():
    spec = importlib.util.spec_from_file_location('atlas_migracion', CLOUD / 'scripts' / 'migrar_usuario_mobile_cloud.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def consultar(cloud, sql):
    r = cloud.wrangler('d1', 'execute', cloud.D1, '--remote', '--json', '--command', sql)
    if r.returncode:
        raise RuntimeError('D1 no disponible')
    try:
        data = json.loads(r.stdout)
        if not data or not all(x.get('success') for x in data):
            raise ValueError()
        return data[0]['results']
    except (ValueError, KeyError, TypeError):
        raise RuntimeError('Respuesta D1 no verificable') from None


def coincidencias(cloud, usuario, rut):
    u, r = cloud.sql_texto(usuario), cloud.sql_texto(rut.upper())
    return consultar(cloud, 'SELECT nombre_usuario, chofer_id, empresa_id, nombre_chofer, activo FROM mobile_usuarios_cloud '
                     f"WHERE lower(nombre_usuario)=lower({u}) OR upper(replace(replace(chofer_id,'.',''),'-',''))={r}")


def publicar(cloud, usuario, rut, nombre, password):
    # Reutiliza generacion y formato oficial. INSERT condicional evita UPSERT o
    # reemplazo si aparece una cuenta entre consulta y publicacion.
    sql = cloud.sentencia_upsert(usuario=usuario, chofer_id=rut, nombre_chofer=nombre,
                                 password_hash=cloud.hash_cloud(password), empresa_id=cloud.EMPRESA)
    prefijo = sql.split(' ON CONFLICT', 1)[0]
    values = prefijo.split(' VALUES ', 1)
    if len(values) != 2:
        raise RuntimeError('Contrato de publicacion inesperado')
    u, r = cloud.sql_texto(usuario), cloud.sql_texto(rut.upper())
    select = values[1].strip()[1:-1]
    insercion = values[0] + ' SELECT ' + select + (' WHERE NOT EXISTS (SELECT 1 FROM mobile_usuarios_cloud '
                 f"WHERE lower(nombre_usuario)=lower({u}) OR upper(replace(replace(chofer_id,'.',''),'-',''))={r});")
    respuesta = cloud.wrangler('d1', 'execute', cloud.D1, '--remote', '--json', '--command', insercion)
    if respuesta.returncode:
        raise RuntimeError('Publicacion D1 no confirmada')
    try:
        resultado = json.loads(respuesta.stdout)
        if not resultado[0]['success'] or resultado[0]['meta']['changes'] != 1:
            raise RuntimeError('D1 no inserto la cuenta; comprobar duplicados')
    except (ValueError, KeyError, IndexError, TypeError):
        raise RuntimeError('Publicacion D1 no verificable') from None


def login(usuario, password, rut):
    body = json.dumps({'usuario': usuario, 'password': password}).encode('utf-8')
    req = urllib.request.Request(URL, data=body, method='POST', headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            datos = json.loads(response.read())
            return response.status == 200 and bool(datos.get('token')) and datos.get('chofer_id') == rut
    except Exception:
        return False


def procesar(raiz, cloud, cuenta, password, *, ejecutar=alta.ejecutar, ingreso=login):
    usuario, rut, nombre_catalogo, nombre_mobile = cuenta
    estado = 'alta local no confirmada'
    try:
        if coincidencias(cloud, usuario, rut):
            return 'PENDIENTE: duplicado en D1; sin escritura'
        # El verificador oficial comprueba formato, duplicados y nombre de catalogo.
        ejecutar(raiz, usuario=usuario, rut=rut, nombre=nombre_catalogo, existente=True,
                 pedir=lambda _: password)
        estado = 'alta local aplicada; D1 no confirmado'
        local = cloud.cuenta_local(raiz / 'catalogos_privados' / 'usuarios_mobile.json', usuario)
        if local.get('chofer_id') != rut or not verificar_password(password, local.get('password_hash', '')):
            return 'PENDIENTE: alta local no verificable; D1 sin publicar'
        publicar(cloud, usuario, rut, nombre_mobile, password)
        estado = 'publicada en D1; verificacion incompleta'
        filas = coincidencias(cloud, usuario, rut)
        if len(filas) != 1 or filas[0] != {'nombre_usuario': usuario, 'chofer_id': rut,
                                            'empresa_id': cloud.EMPRESA, 'nombre_chofer': nombre_mobile, 'activo': 1}:
            return 'PENDIENTE: cuenta local y publicacion realizadas; D1 no verificable'
        if not ingreso(usuario, password, rut):
            return 'PENDIENTE: local y D1 verificadas; ingreso Mobile fallido'
        return 'HABILITADO: local, D1 e ingreso Mobile verificados'
    except Exception as e:
        # No imprimir excepciones externas que pudieran contener datos sensibles.
        codigo = e.codigo if isinstance(e, alta.ErrorAlta) else type(e).__name__
        return f'PENDIENTE: {estado} ({codigo})'


def main():
    config = Path(os.environ['LOCALAPPDATA']) / 'Atlas' / 'desktop_operacion.json'
    cfg = json.loads(config.read_text(encoding='utf-8-sig'))
    raiz = Path(cfg['raiz'])
    os.environ['ATLAS_OPERACION_CONFIG'] = str(config)
    os.environ['ATLAS_DATA_DIR'] = str(raiz)
    os.environ['ATLAS_CATALOGOS_DIR'] = str(raiz / 'catalogos_privados')
    cloud = cargar_cloud()
    if not sys.stdin.isatty() or not sys.stderr.isatty():
        raise SystemExit('Se requiere consola interactiva con entrada oculta; no se escribio nada.')
    warnings.simplefilter('error', getpass.GetPassWarning)
    print('Alta de cinco cuentas existentes. Una entrada oculta por cuenta; PULL permanece activo.')
    for cuenta in CUENTAS:
        usuario, rut, nombre, _ = cuenta
        try:
            alta.ejecutar(raiz, usuario=usuario, rut=rut, nombre=nombre, existente=True, solo_validar=True)
            if coincidencias(cloud, usuario, rut):
                print(f'{usuario}: PENDIENTE: duplicado D1; sin escritura', flush=True)
                continue
            password = getpass.getpass(f'Contraseña inicial de {usuario} (entrada oculta): ')
            try:
                print(f'{usuario}: {procesar(raiz, cloud, cuenta, password)}', flush=True)
            finally:
                password = None
        except (KeyboardInterrupt, EOFError):
            print(f'\n{usuario}: PENDIENTE: entrada cancelada; continuando', flush=True)
        except Exception as e:
            codigo = e.codigo if isinstance(e, alta.ErrorAlta) else type(e).__name__
            print(f'{usuario}: PENDIENTE: validacion previa ({codigo})', flush=True)
    print('Terminado. Una cuenta pendiente requiere revision individual antes de reintentar.')


if __name__ == '__main__':
    main()
