"""Resolución común de credenciales de proveedores externos.

Un proceso hijo (p. ej. el Python que Electron lanza para B1) puede no
heredar las variables de usuario de Windows. Por eso: primero el entorno
del proceso; en Windows, fallback de sólo lectura a HKCU\\Environment.
Nunca registra el valor en logs ni salidas.

Secretos = locales por usuario/PC (nunca Git ni Drive/G:). Se registran
una vez por PC con `registrar_credencial.py`; ver docs/CREDENCIALES_LOCALES.md."""
from __future__ import annotations

import os

# Únicas credenciales que `registrar_credencial.py` acepta escribir.
CREDENCIALES_PERMITIDAS = ("TAVILY_API_KEY", "OPENROUTER_API_KEY", "GROQ_API_KEY")


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


def resolver_tavily_api_key(api_key: str | None = None) -> str:
    return resolver_credencial("TAVILY_API_KEY", api_key)


def _escribir_entorno_usuario_windows(nombre: str, valor: str) -> None:
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_SET_VALUE) as clave:
        winreg.SetValueEx(clave, nombre, 0, winreg.REG_SZ, valor)


def _notificar_cambio_entorno_windows() -> None:
    """WM_SETTINGCHANGE "Environment": los procesos abiertos después (Explorer, Desktop) ven el cambio."""
    import ctypes
    from ctypes import wintypes
    resultado = wintypes.DWORD()
    ctypes.windll.user32.SendMessageTimeoutW(
        0xFFFF, 0x001A, 0, "Environment", 0x0002, 5000, ctypes.byref(resultado))  # HWND_BROADCAST, WM_SETTINGCHANGE, SMTO_ABORTIFHUNG


def registrar_credencial_usuario(nombre: str, valor: str) -> None:
    """Guarda `nombre` en HKCU\\Environment del usuario actual. Nunca incluye el valor en errores."""
    if nombre not in CREDENCIALES_PERMITIDAS:
        raise ValueError(f"Credencial no permitida: {nombre}")
    valor = str(valor or "").strip()
    if not valor:
        raise ValueError("El valor de la credencial está vacío.")
    if any(c.isspace() or not c.isprintable() for c in valor):
        raise ValueError("El valor de la credencial contiene espacios o caracteres de control.")
    if os.name != "nt":
        raise OSError("El registro de credenciales sólo está disponible en Windows.")
    _escribir_entorno_usuario_windows(nombre, valor)
    _notificar_cambio_entorno_windows()
