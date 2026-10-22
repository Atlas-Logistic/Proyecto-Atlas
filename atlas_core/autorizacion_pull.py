"""Autorizacion local revocable; independiente del lease temporal de Cloud."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path


def identidad_equipo():
    import winreg
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\Microsoft\Cryptography',
                        access=winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
        return str(winreg.QueryValueEx(key, 'MachineGuid')[0]).lower()


def validar_autorizacion(ruta, config, *, ahora=None, equipo=None):
    """Falla cerrado ante ausencia, revocacion, equipo ajeno o modo desconocido."""
    a = json.loads(Path(ruta).read_text(encoding='utf-8-sig'))
    c = json.loads(Path(config).read_text(encoding='utf-8-sig'))
    if (c.get('modo_escritor') != 'lease_cloud' or c.get('autorizada') is not True
            or c.get('habilitada') is not True):
        raise ValueError('Configuracion PULL no autorizada para lease_cloud.')
    if a.get('autor') != 'Javier' or a.get('exclusividad_verificada') is not True:
        raise ValueError('Autorizacion PULL invalida.')
    modo = a.get('modo', 'temporal')
    if modo == 'persistente':
        if (a.get('schema_version') != 1 or a.get('habilitada') is not True
                or a.get('revocada') is not False or a.get('vence_utc') is not None):
            raise ValueError('Autorizacion persistente revocada o invalida.')
        actual = (equipo if equipo is not None else identidad_equipo()).lower()
        if not actual or a.get('machine_guid', '').lower() != actual or c.get('machine_guid', '').lower() != actual:
            raise ValueError('Autorizacion persistente pertenece a otro equipo.')
    elif modo == 'temporal':
        if a.get('revocada') is True or a.get('habilitada') is False:
            raise ValueError('Autorizacion temporal revocada.')
        vence = datetime.fromisoformat(a['vence_utc'].replace('Z', '+00:00'))
        if vence.tzinfo is None or vence <= (ahora or datetime.now(timezone.utc)):
            raise ValueError('Autorizacion PULL vencida.')
    else:
        raise ValueError('Modo de autorizacion PULL desconocido.')
    return True


def autorizacion_vigente(ruta, config):
    try:
        return validar_autorizacion(ruta, config)
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return False


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--autorizacion', required=True)
    parser.add_argument('--config', required=True)
    args = parser.parse_args()
    if not autorizacion_vigente(args.autorizacion, args.config):
        parser.exit(1, 'Autorizacion PULL ausente, invalida, revocada o vencida.\n')
