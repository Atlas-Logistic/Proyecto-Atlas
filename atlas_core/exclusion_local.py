"""Exclusión local de escritores del Motor (Etapa 1, condición C1).

Un único turno de escritura por raíz operacional y por equipo, sostenido por
un mutex con nombre de Windows (``Global\\AtlasEscritorTurno-<sha>``):

- Se toma ANTES de pedir el lease Cloud y se suelta DESPUÉS de liberarlo
  (incluida la confirmación de custodia): cubre toda la sección crítica, no
  sólo la adquisición. Lo toman ``LeaseEscritorOperativo`` y
  ``EscritorEquipoUnico``, así que PULL, sesión Desktop, B1, mantenimiento y
  migración lo heredan sin cambios propios.
- El mutex lo posee un hilo dedicado del proceso: el turno es del PROCESO
  (cualquier hilo puede escribir) y se libera desde cualquier hilo. Si el
  proceso termina sin soltarlo, el kernel lo abandona y el siguiente lo
  recibe con ``WAIT_ABANDONED``: nunca queda bloqueado por una interrupción.
  El abandono se informa (``abandonado``) y se anota en la caché local; la
  recuperación de operaciones queda para una etapa posterior.
- Reentrante dentro del proceso: un segundo turno de la misma raíz en el mismo
  proceso no espera (el árbitro dentro del proceso sigue siendo Cloud).

Guardia (audit hook, se instala al importar ``atlas_core``): en una raíz
protegida, toda escritura de un proceso que no posee el turno se rechaza
(``ATLAS_EXCLUSION_LOCAL=exigir``, por defecto), sólo se anota (``observar``)
o se ignora (``desactivada``). Raíces protegidas: ``ATLAS_EXCLUSION_RAICES``
explícitas, más ``ATLAS_DATA_DIR`` y la raíz de la política de operación
(``desktop_operacion.json``) cuando son compartidas (Drive, UNC, unidad
distinta de C:). Una raíz local de desarrollo o de pruebas no se protege.

Límites (no se asumen): sólo excluye procesos Python del Motor de este equipo
que importan ``atlas_core``. No protege contra Google Drive, personas, otros
programas ni escritores de otro computador; eso sigue a cargo del lease Cloud
y de la custodia.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

PREFIJO_MUTEX = "Global\\AtlasEscritorTurno-"
MODOS = ("exigir", "observar", "desactivada")
CODIGO_OCUPADO = "ESCRITOR_LOCAL_OCUPADO"

_WAIT_OBJECT_0 = 0x0
_WAIT_ABANDONED = 0x80
_WAIT_TIMEOUT = 0x102
_INFINITO = 0xFFFFFFFF

log = logging.getLogger(__name__)


class TurnoOcupado(RuntimeError):
    """Otro proceso de este equipo tiene el turno de escritura de la raíz."""

    codigo = CODIGO_OCUPADO


class EscrituraSinTurno(PermissionError):
    """Escritura en una raíz protegida sin poseer el turno local."""


# ------------------------------------------------------------------- rutas

def normalizar_raiz(raiz) -> str:
    """Misma clave en el nombre del mutex, el registro del proceso y la guardia."""
    return os.path.normcase(os.path.abspath(os.fsdecode(raiz))).rstrip("\\/")


def nombre_mutex(raiz) -> str:
    return PREFIJO_MUTEX + hashlib.sha256(normalizar_raiz(raiz).encode("utf-8")).hexdigest()[:40]


def compartida(raiz) -> bool:
    """Mismo criterio que ``desktop_operacion.compartida`` (sin importarlo)."""
    texto = str(raiz).replace("/", "\\").lower()
    return (texto.startswith("\\\\") or (len(texto) > 1 and texto[1] == ":" and texto[0] != "c")
            or "onedrive" in texto or "google drive" in texto)


def _dentro(ruta_norm: str, raiz_norm: str) -> bool:
    return ruta_norm == raiz_norm or ruta_norm.startswith(raiz_norm + os.sep)


def ruta_registro_abandonos() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".local")
    return base / "Atlas" / "cache" / "exclusion_local" / "abandonos.jsonl"


def ruta_registro_observaciones() -> Path:
    return ruta_registro_abandonos().with_name("observaciones.jsonl")


# --------------------------------------------------------- mutex de Windows

def _kernel32():
    import ctypes
    from ctypes import wintypes
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    k.CreateMutexW.restype = wintypes.HANDLE
    k.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    k.WaitForSingleObject.restype = wintypes.DWORD
    k.ReleaseMutex.argtypes = [wintypes.HANDLE]
    k.ReleaseMutex.restype = wintypes.BOOL
    k.CloseHandle.argtypes = [wintypes.HANDLE]
    k.CloseHandle.restype = wintypes.BOOL
    return k


class _Poseedor(threading.Thread):
    """Hilo dueño del mutex: lo toma, avisa y lo sostiene hasta ``soltar``."""

    def __init__(self, nombre: str, espera_ms: int) -> None:
        super().__init__(name="atlas-turno-escritura", daemon=True)
        self.nombre = nombre
        self.espera_ms = espera_ms
        self.resultado = ""  # ADQUIRIDO | ABANDONADO | OCUPADO | ERROR
        self.error = ""
        self._listo = threading.Event()
        self._soltar = threading.Event()

    def run(self) -> None:
        k = _kernel32()
        handle = k.CreateMutexW(None, False, self.nombre)
        if not handle:
            import ctypes
            self.resultado, self.error = "ERROR", f"CreateMutexW: {ctypes.get_last_error()}"
            self._listo.set()
            return
        try:
            espera = k.WaitForSingleObject(handle, self.espera_ms)
            if espera not in (_WAIT_OBJECT_0, _WAIT_ABANDONED):
                self.resultado = "OCUPADO" if espera == _WAIT_TIMEOUT else "ERROR"
                if self.resultado == "ERROR":
                    import ctypes
                    self.error = f"WaitForSingleObject={espera:#x} error={ctypes.get_last_error()}"
                self._listo.set()
                return
            self.resultado = "ABANDONADO" if espera == _WAIT_ABANDONED else "ADQUIRIDO"
            self._listo.set()
            self._soltar.wait()
            k.ReleaseMutex(handle)
        finally:
            k.CloseHandle(handle)

    def esperar_resultado(self) -> str:
        self._listo.wait()
        return self.resultado

    def soltar(self) -> None:
        self._soltar.set()
        self.join(timeout=10)


class _TurnoProceso:
    """Turno compartido por todos los hilos y objetos del proceso para una raíz."""

    def __init__(self, raiz_norm: str, poseedor: _Poseedor | None) -> None:
        self.raiz_norm = raiz_norm
        self.poseedor = poseedor
        self.referencias = 0


_cerrojo = threading.RLock()          # registro del proceso (lo consulta la guardia)
_cerrojo_adquisicion = threading.Lock()  # una adquisición a la vez dentro del proceso
_turnos: dict[str, _TurnoProceso] = {}


def ruta_marcador(raiz_norm: str) -> Path:
    """Marcador local de turno en curso. Sólo lo escribe/borra quien posee el
    mutex: si al adquirir existe, el dueño anterior terminó sin soltar. Es la
    señal fiable de abandono: si nadie más tenía abierto el mutex, Windows lo
    destruye al morir el dueño y el siguiente no recibe WAIT_ABANDONED."""
    return ruta_registro_abandonos().with_name(f"turno_{nombre_mutex(raiz_norm)[len(PREFIJO_MUTEX):]}.json")


def _leer_marcador(ruta: Path) -> dict | None:
    try:
        with open(ruta, encoding="utf-8") as archivo:
            datos = json.load(archivo)
        return datos if isinstance(datos, dict) else {"ilegible": True}
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        return {"ilegible": True}


def _escribir_marcador(ruta: Path, raiz_norm: str) -> None:
    try:
        ruta.parent.mkdir(parents=True, exist_ok=True)
        temporal = ruta.with_name(f"{ruta.name}.{os.getpid()}.tmp")
        with open(temporal, "w", encoding="utf-8") as archivo:
            json.dump({"pid": os.getpid(), "raiz": raiz_norm, "inicio": datetime.now(timezone.utc).isoformat(),
                       "proceso": " ".join(sys.argv[:2])[:300]}, archivo, ensure_ascii=False)
        os.replace(temporal, ruta)
    except OSError as error:  # sin marcador sólo se pierde la señal de abandono, nunca la exclusión
        log.warning("No se pudo registrar el turno local en curso: %s", error)


def _anotar_abandono(raiz_norm: str, anterior: dict | None, origen: str) -> None:
    ruta = ruta_registro_abandonos()
    try:
        ruta.parent.mkdir(parents=True, exist_ok=True)
        with open(ruta, "a", encoding="utf-8") as archivo:
            archivo.write(json.dumps({"fecha": datetime.now(timezone.utc).isoformat(), "raiz": raiz_norm,
                                      "pid": os.getpid(), "origen": origen, "anterior": anterior},
                                     ensure_ascii=False) + "\n")
    except OSError:
        pass


class TurnoEscritura:
    """Turno local de escritura sobre ``raiz``. Uso:

    ``with TurnoEscritura(raiz): ...`` (lanza ``TurnoOcupado``), o
    ``adquirir()`` -> bool y ``soltar()`` (idempotente).
    """

    def __init__(self, raiz, *, espera_segundos: float = 0.0) -> None:
        self.raiz_norm = normalizar_raiz(raiz)
        self.espera_segundos = max(0.0, float(espera_segundos))
        self.abandonado = False
        self.error = ""
        self._tomado = False

    @property
    def vigente(self) -> bool:
        return self._tomado

    def adquirir(self) -> bool:
        if self._tomado:
            return True
        with _cerrojo_adquisicion:
            with _cerrojo:
                turno = _turnos.get(self.raiz_norm)
                if turno is not None:  # reentrante: el proceso ya lo posee
                    turno.referencias += 1
                    self._tomado = True
                    return True
            poseedor = None
            resultado = "ADQUIRIDO"
            if os.name == "nt":
                espera_ms = _INFINITO if self.espera_segundos == float("inf") else int(self.espera_segundos * 1000)
                poseedor = _Poseedor(nombre_mutex(self.raiz_norm), espera_ms)
                poseedor.start()
                resultado = poseedor.esperar_resultado()
                if resultado not in ("ADQUIRIDO", "ABANDONADO"):
                    self.error = poseedor.error
                    if resultado == "ERROR":
                        raise OSError(f"Mutex de turno de escritura no disponible: {poseedor.error}")
                    return False
            # Con el mutex en mano: el marcador del dueño anterior sólo puede
            # existir si terminó sin soltar (Windows no siempre informa
            # WAIT_ABANDONED: el objeto se destruye si nadie más lo tenía abierto).
            marcador = ruta_marcador(self.raiz_norm)
            anterior = _leer_marcador(marcador)
            if resultado == "ABANDONADO" or anterior is not None:
                self.abandonado = True
                log.warning("Turno de escritura abandonado por un proceso terminado (%s); requiere verificación.",
                            self.raiz_norm)
                _anotar_abandono(self.raiz_norm, anterior, "WAIT_ABANDONED" if resultado == "ABANDONADO" else "MARCADOR")
            _escribir_marcador(marcador, self.raiz_norm)
            with _cerrojo:
                turno = _TurnoProceso(self.raiz_norm, poseedor)
                turno.referencias = 1
                _turnos[self.raiz_norm] = turno
        self._tomado = True
        return True

    def soltar(self) -> None:
        if not self._tomado:
            return
        self._tomado = False
        with _cerrojo:
            turno = _turnos.get(self.raiz_norm)
            if turno is None:
                return
            turno.referencias -= 1
            if turno.referencias > 0:
                return
            del _turnos[self.raiz_norm]
        # Primero el marcador (aún con el mutex), después el mutex: un corte
        # entre ambos se ve como turno limpio, y ya no quedaba escritura.
        try:
            ruta_marcador(self.raiz_norm).unlink(missing_ok=True)
        except OSError as error:
            log.warning("No se pudo borrar el marcador del turno local: %s", error)
        if turno.poseedor is not None:
            turno.poseedor.soltar()

    def __enter__(self) -> "TurnoEscritura":
        if not self.adquirir():
            raise TurnoOcupado(f"Otro proceso Atlas de este equipo está escribiendo en {self.raiz_norm}.")
        return self

    def __exit__(self, *_args) -> None:
        self.soltar()


def posee_turno(ruta) -> bool:
    """True si este proceso posee el turno de una raíz que contiene ``ruta``."""
    ruta_norm = os.path.normcase(os.path.abspath(os.fsdecode(ruta)))
    with _cerrojo:
        return any(_dentro(ruta_norm, raiz) for raiz in _turnos)


# ----------------------------------------------------------------- guardia

def modo_guardia() -> str:
    modo = os.environ.get("ATLAS_EXCLUSION_LOCAL", "exigir").strip().lower() or "exigir"
    return modo if modo in MODOS else "exigir"


_cache_raices: tuple[tuple, tuple[str, ...]] | None = None


def _raiz_politica() -> str:
    ruta = os.environ.get("ATLAS_OPERACION_CONFIG") or (
        str(Path(os.environ["LOCALAPPDATA"]) / "Atlas" / "desktop_operacion.json") if os.environ.get("LOCALAPPDATA") else "")
    if not ruta:
        return ""
    try:
        with open(ruta, encoding="utf-8-sig") as archivo:  # lectura: no la ve la guardia
            return str(json.load(archivo).get("raiz") or "")
    except (OSError, ValueError, AttributeError):
        return ""


def raices_protegidas() -> tuple[str, ...]:
    """Raíces donde se exige el turno. Cacheado por valores de entorno."""
    global _cache_raices
    clave = (os.environ.get("ATLAS_EXCLUSION_RAICES", ""), os.environ.get("ATLAS_DATA_DIR", ""),
             os.environ.get("ATLAS_OPERACION_CONFIG", ""), os.environ.get("LOCALAPPDATA", ""))
    if _cache_raices is not None and _cache_raices[0] == clave:
        return _cache_raices[1]
    raices: list[str] = [r for r in clave[0].split(os.pathsep) if r.strip()]
    for candidata in (clave[1], _raiz_politica()):
        if candidata and compartida(candidata):
            raices.append(candidata)
    normalizadas = tuple(sorted({normalizar_raiz(r) for r in raices}))
    _cache_raices = (clave, normalizadas)
    return normalizadas


_local = threading.local()
_observadas: set[str] = set()


def _anotar_observacion(ruta_norm: str, evento: str) -> None:
    if ruta_norm in _observadas:
        return
    _observadas.add(ruta_norm)
    try:
        destino = ruta_registro_observaciones()
        destino.parent.mkdir(parents=True, exist_ok=True)
        with open(destino, "a", encoding="utf-8") as archivo:
            archivo.write(json.dumps({"fecha": datetime.now(timezone.utc).isoformat(), "pid": os.getpid(),
                                      "evento": evento, "ruta": ruta_norm,
                                      "proceso": " ".join(sys.argv[:2])[:300]}, ensure_ascii=False) + "\n")
    except OSError:
        pass


def _destinos(evento: str, args) -> list:
    if evento == "open":
        ruta, modo, flags = args
        if not ((modo and any(c in modo for c in "wax+")) or
                (flags and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND))):
            return []
        return [ruta]
    if evento in {"os.rename", "os.link", "os.symlink"}:
        return list(args[:2])
    if evento in {"os.remove", "os.rmdir", "os.mkdir", "os.truncate", "os.chmod", "os.utime", "shutil.rmtree"}:
        return [args[0]]
    return []


def _guardia(evento: str, args) -> None:
    if evento not in _EVENTOS or getattr(_local, "dentro", False):
        return
    destinos = _destinos(evento, args)
    if not destinos:
        return
    modo = modo_guardia()
    if modo == "desactivada":
        return
    _local.dentro = True
    try:
        raices = raices_protegidas()
        if not raices:
            return
        for destino in destinos:
            if destino is None or isinstance(destino, int):
                continue
            ruta_norm = os.path.normcase(os.path.abspath(os.fsdecode(destino)))
            raiz = next((r for r in raices if _dentro(ruta_norm, r)), None)
            if raiz is None or posee_turno(ruta_norm):
                continue
            if modo == "observar":
                _anotar_observacion(ruta_norm, evento)
                continue
            raise EscrituraSinTurno(
                f"Escritura sin turno local en raíz operacional protegida ({evento}): {ruta_norm}. "
                "Sólo un escritor del Motor con turno (PULL, sesión Desktop, B1, mantenimiento) puede escribir.")
    finally:
        _local.dentro = False


_EVENTOS = frozenset({"open", "os.rename", "os.link", "os.symlink", "os.remove", "os.rmdir", "os.mkdir",
                      "os.truncate", "os.chmod", "os.utime", "shutil.rmtree"})
_instalada = False


def instalar_guardia() -> None:
    """Idempotente: un único audit hook por intérprete (no se puede quitar)."""
    global _instalada
    if _instalada:
        return
    sys.addaudithook(_guardia)
    _instalada = True
