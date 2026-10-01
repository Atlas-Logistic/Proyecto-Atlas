"""Resolución común de credenciales de proveedores externos.

Un proceso hijo (p. ej. el Python que Electron lanza para B1) puede no
heredar las variables de usuario de Windows. Por eso: primero el entorno
del proceso; en Windows, fallback de sólo lectura a HKCU\\Environment.
Nunca persiste ni registra el valor."""
from __future__ import annotations

import os


def _leer_entorno_usuario_windows(nombre: str) -> str:
    if os.name != "nt":
        return ""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as clave:
            valor, _ = winreg.QueryValueEx(clave, nombre)
        return str(valor or "").strip()
    except (FileNotFoundError, OSError):
        return ""


def resolver_credencial(nombre: str, api_key: str | None = None) -> str:
    """Resuelve la credencial `nombre` del proceso o del perfil Windows, sin persistirla."""
    if api_key is not None:
        return api_key.strip()
    valor = os.getenv(nombre, "").strip()
    if valor:
        return valor
    return _leer_entorno_usuario_windows(nombre)


def resolver_openrouter_api_key(api_key: str | None = None) -> str:
    return resolver_credencial("OPENROUTER_API_KEY", api_key)
