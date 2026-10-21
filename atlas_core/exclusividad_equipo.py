"""Escritor de equipo único explícito; no sustituye un lease multi-PC.

Mutex Global de Windows mantenido por el kernel (liberación tras caída),
política ligada al equipo y raíz exactos, y PULL local prohibido.
"""
from __future__ import annotations
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import threading

def ruta_politica():
    return Path(os.environ['LOCALAPPDATA'])/'Atlas'/'desktop_operacion.json'

def identidad_equipo():
    import winreg
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\Microsoft\Cryptography',0,winreg.KEY_READ|winreg.KEY_WOW64_64KEY) as key:
        return winreg.QueryValueEx(key,'MachineGuid')[0]

def politica_equipo_unico(raiz):
    if os.name != 'nt': return None
    # El proceso normal obtiene esta ruta de la misma configuración del launcher;
    # el override permite aislar pruebas sin tocar la política productiva.
    ruta=Path(os.environ.get('ATLAS_OPERACION_CONFIG') or ruta_politica())
    try: c=json.loads(ruta.read_text(encoding='utf-8-sig'))
    except FileNotFoundError: return None
    if c.get('modo_escritor') != 'equipo_unico': return None
    if Path(c.get('raiz','')).resolve() != Path(raiz).resolve(): return None
    if not c.get('autorizada') or not c.get('habilitada'):
        raise PermissionError('Modo de equipo único sin autorización operacional.')
    if c.get('equipo','').casefold() != socket.gethostname().casefold() or c.get('machine_guid') != identidad_equipo():
        raise PermissionError('Política de escritor ligada a otro equipo; no se escribe.')
    return c

def comprobar_pull_detenido():
    comando = r'''$ErrorActionPreference='Stop'
$patron='(?i)sincronizar_mobile(?:_cloud)?\.py|servidor_mobile\.py'
$tareas=@(Get-ScheduledTask | Where-Object { ($_.TaskName -match '(?i)atlas.*pull|pull.*atlas' -or (($_.Actions.Arguments -join ' ') -match '(?i)pull_cloud|sincronizar_mobile')) -and $_.State -ne 'Disabled' } | Select-Object -ExpandProperty TaskName)
$procesos=@(Get-CimInstance Win32_Process | Where-Object { $_.Name -match '(?i)^python(?:w)?\.exe$' -and $_.CommandLine -match $patron } | Select-Object -ExpandProperty ProcessId)
@{tareas=$tareas;procesos=$procesos} | ConvertTo-Json -Compress'''
    powershell=Path(os.environ['SystemRoot'])/'System32'/'WindowsPowerShell'/'v1.0'/'powershell.exe'
    r=subprocess.run([str(powershell),'-NoProfile','-NonInteractive','-Command',comando],capture_output=True,text=True,encoding='utf-8',timeout=20,creationflags=subprocess.CREATE_NO_WINDOW)
    if r.returncode: raise PermissionError('No se pudo verificar PULL local; operación bloqueada.')
    datos=json.loads(r.stdout.lstrip('\ufeff'))
    if datos['tareas'] or datos['procesos']:
        raise PermissionError('PULL habilitado o en ejecución; modo manual de equipo único bloqueado.')
    return datos

class EscritorEquipoUnico:
    def __init__(self,raiz,*,verificar=comprobar_pull_detenido):
        self.raiz=Path(raiz).resolve()
        self.verificar=verificar
        self.handle=None
        self._perdido=threading.Event()
        self._detener=threading.Event()
        self._hilo=None
        self._k=ctypes.WinDLL('kernel32',use_last_error=True)
        self._k.CreateMutexW.argtypes=[ctypes.c_void_p,wintypes.BOOL,wintypes.LPCWSTR]
        self._k.CreateMutexW.restype=wintypes.HANDLE
        self._k.WaitForSingleObject.argtypes=[wintypes.HANDLE,wintypes.DWORD]
        self._k.WaitForSingleObject.restype=wintypes.DWORD
        self._k.ReleaseMutex.argtypes=[wintypes.HANDLE]
        self._k.CloseHandle.argtypes=[wintypes.HANDLE]
    @property
    def vigente(self): return self.handle is not None and not self._perdido.is_set()
    def adquirir(self):
        nombre='Global\\AtlasDesktopWriter-'+hashlib.sha256(str(self.raiz).casefold().encode()).hexdigest()
        h=self._k.CreateMutexW(None,False,nombre)
        if not h: raise PermissionError('No se pudo acceder al mutex del escritor de Windows.')
        if self._k.WaitForSingleObject(h,0) not in (0,0x80):
            self._k.CloseHandle(h)
            return False
        self.handle=h
        try: self.verificar()
        except Exception:
            self.cerrar(); raise
        def vigilar():
            while not self._detener.wait(3):
                try: self.verificar()
                except Exception:
                    self._perdido.set(); return
        self._hilo=threading.Thread(target=vigilar,name='atlas-equipo-unico',daemon=True)
        self._hilo.start()
        return True
    def renovar(self): return self.vigente
    def recuperar_bloqueos_huerfanos(self):
        """Sólo bajo mutex: recupera locks del mismo PC cuyo PID ya terminó.

        Un PID vivo, inaccesible, reutilizado o de otro host nunca se elimina.
        """
        if not self.vigente: raise PermissionError('Recuperación sin exclusividad.')
        k=self._k
        k.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
        k.OpenProcess.restype=wintypes.HANDLE
        k.GetExitCodeProcess.argtypes=[wintypes.HANDLE,ctypes.POINTER(wintypes.DWORD)]
        recuperados=[]
        for ruta in (self.raiz/'operacion'/'actual').glob('.atlas_lock_*'):
            original=ruta.read_bytes()
            try: info=json.loads(original)
            except (ValueError,UnicodeError): continue
            if str(info.get('host','')).casefold()!=socket.gethostname().casefold(): continue
            pid=info.get('pid')
            if not isinstance(pid,int) or pid<=0: continue
            h=k.OpenProcess(0x1000,False,pid)
            if h:
                codigo=wintypes.DWORD()
                try: muerto=bool(k.GetExitCodeProcess(h,ctypes.byref(codigo))) and codigo.value!=259
                finally: k.CloseHandle(h)
            else: muerto=ctypes.get_last_error()==87
            if muerto and ruta.read_bytes()==original:
                ruta.unlink(); recuperados.append(ruta.name)
        return recuperados
    def cerrar(self):
        self._detener.set()
        if self._hilo: self._hilo.join(timeout=22)
        if self.handle:
            self._k.ReleaseMutex(self.handle); self._k.CloseHandle(self.handle); self.handle=None
    def __enter__(self): return self
    def __exit__(self,*args): self.cerrar()
