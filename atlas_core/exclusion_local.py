"""Exclusión local de escritores del Motor (Etapa 1, condición C1).

Un único turno de escritura por raíz operacional, por equipo y por perfil de
Windows, sostenido por un bloqueo de rango de bytes (``msvcrt.locking``) sobre
``%LOCALAPPDATA%\\Atlas\\cache\\exclusion_local\\turno_<sha256(raíz)>.lock``:

- Se toma ANTES de pedir el lease Cloud y se suelta DESPUÉS de liberarlo
  (incluida la confirmación de custodia). Lo toman ``LeaseEscritorOperativo`` y
  ``EscritorEquipoUnico``, así que PULL, sesión Desktop, B1, mantenimiento y
  migración lo heredan sin cambios propios.
- El bloqueo pertenece a un HANDLE del proceso, no a un hilo: no hay hilo
  propietario que pueda morir y cualquier hilo puede soltarlo. Sólo se pierde
  si este módulo cierra el handle o si el proceso termina. El handle no es
  heredable: los procesos hijos no conservan el bloqueo.
- Un único dueño por proceso y raíz, SIN reentrancia: mientras una instancia
  posee el turno, otra del mismo proceso recibe ``False``. La misma semántica
  que el lease Cloud, que tampoco es reentrante.
- Orden: físico primero, lógico después; lógico se retira primero, físico se
  libera en ``finally``. Por eso ``posee_turno`` y ``vigente`` verdaderos
  implican siempre el bloqueo concedido por el kernel.
- Todas las esperas son acotadas. Un fallo del mecanismo es ``ErrorTurno``,
  nunca turno obtenido.
- Abandono: el archivo guarda los datos del dueño mientras lo posee y se vacía
  al soltar. Si al adquirir no está vacío, el dueño anterior terminó sin soltar
  (``abandonado``); la recuperación de operaciones queda para otra etapa.

Límites declarados: una interrupción asíncrona DENTRO del propio bloque de
limpieza puede saltarse el cierre explícito (lo lógico sigue sin indicar
posesión y el handle se cierra al liberarse su última referencia o al terminar
el proceso); dos usuarios de Windows distintos no se excluyen (el archivo es
por perfil); Windows puede demorar la liberación tras la terminación abrupta
de un proceso; un proceso vivo y colgado retiene el turno.

Guardia (audit hook, se instala al importar ``atlas_core``): en una raíz
protegida, una escritura de un proceso que no posee el turno se rechaza
(``ATLAS_EXCLUSION_LOCAL=exigir``, por defecto), sólo se anota (``observar``)
o se ignora (``desactivada``; ``observar`` y ``desactivada`` NO protegen).
Raíces protegidas: ``ATLAS_EXCLUSION_RAICES`` explícitas, más
``ATLAS_DATA_DIR`` y la raíz de la política de operación
(``desktop_operacion.json``) cuando son compartidas (Drive, UNC, unidad
distinta de C:). Una raíz local de desarrollo o de pruebas no se protege.

Cobertura REAL de la guardia (ver docs/EXCLUSION_LOCAL_ESCRITORES.md y
tests/test_exclusion_local_fallos.py): intercepta por RUTA TEXTUAL los eventos
de auditoría listados en ``_EVENTOS``. NO cubre: escrituras por un descriptor
abierto antes (con turno o antes de importar atlas_core), llamadas nativas
(ctypes/Win32), alias de ruta (junction, enlace, ``\\\\?\\``, 8.3, unidad
mapeada frente a UNC), eventos no listados (p. ej. sqlite3), procesos hijos ni
procesos ajenos al Motor, ni escritores de otro computador (eso sigue a cargo
del lease Cloud y de la custodia). La exclusión entre escritores del Motor la
da el turno que toman los escritores; la guardia es una defensa adicional.
"""
from __future__ import annotations

import errno
import hashlib
import json
import logging
import math
import os
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

try:
    import msvcrt
except ImportError:  # el turno sólo existe en Windows; fuera de él, falla cerrado
    msvcrt = None

MODOS = ("exigir", "observar", "desactivada")
CODIGO_OCUPADO = "ESCRITOR_LOCAL_OCUPADO"

# Byte lejano: el bloqueo no ocupa contenido ni hace crecer el archivo, así que
# los bytes iniciales quedan libres para los datos del dueño.
DESPLAZAMIENTO_BLOQUEO = 2 ** 30
INTERVALO_REINTENTO_SEGUNDOS = 0.02
INTERVALO_TRANSICION_SEGUNDOS = 0.002
# Más allá de la espera pedida, plazo para las transiciones de este proceso.
MARGEN_TRANSICION_SEGUNDOS = 15.0
_MAXIMO_LECTURA_DUENO = 4096

log = logging.getLogger(__name__)


class TurnoOcupado(RuntimeError):
    """Otro proceso de este equipo tiene el turno de escritura de la raíz."""

    codigo = CODIGO_OCUPADO


class EscrituraSinTurno(PermissionError):
    """Escritura en una raíz protegida sin poseer el turno local."""


class ErrorTurno(OSError):
    """Fallo del mecanismo de turno. Nunca equivale a turno obtenido."""


# ------------------------------------------------------------------- rutas

def normalizar_raiz(raiz) -> str:
    """Misma clave en el archivo de turno, el registro del proceso y la guardia."""
    return os.path.normcase(os.path.abspath(os.fsdecode(raiz))).rstrip("\\/")


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


def ruta_turno(raiz) -> Path:
    clave = hashlib.sha256(normalizar_raiz(raiz).encode("utf-8")).hexdigest()
    return ruta_registro_abandonos().with_name(f"turno_{clave}.lock")


# ------------------------------------------------------- bloqueo del archivo

def _punto(_nombre: str) -> None:
    """Sin efecto: permite a las pruebas interrumpir cada paso crítico."""


def _abrir_o_crear(ruta, banderas: int) -> int:
    return os.open(ruta, banderas | os.O_CREAT, 0o600)


def _abrir_archivo_turno(raiz_norm: str):
    ruta = ruta_turno(raiz_norm)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    # "r+b" y no "a+b": los datos del dueño se SOBRESCRIBEN, sin dejar el
    # archivo vacío entre medio (perdería la señal de abandono del anterior).
    # FileIO sin búfer y no heredable.
    return open(ruta, "r+b", buffering=0, opener=_abrir_o_crear)


def _intentar_bloqueo(archivo, fin: float) -> bool:
    """Intentos no bloqueantes hasta ``fin``. True si el kernel concedió el byte."""
    while True:
        archivo.seek(DESPLAZAMIENTO_BLOQUEO)
        try:
            msvcrt.locking(archivo.fileno(), msvcrt.LK_NBLCK, 1)
            return True
        except OSError as error:
            if error.errno not in (errno.EACCES, errno.EDEADLOCK):
                raise
        restante = fin - time.monotonic()
        if restante <= 0:
            return False
        time.sleep(min(INTERVALO_REINTENTO_SEGUNDOS, restante))


def _leer_dueno_previo(archivo) -> dict | None:
    """Datos del dueño anterior; None si soltó limpio (archivo vacío)."""
    archivo.seek(0)
    contenido = archivo.read(_MAXIMO_LECTURA_DUENO)
    if not contenido:
        return None
    try:
        datos = json.loads(contenido.decode("utf-8"))
        return datos if isinstance(datos, dict) else {"ilegible": True}
    except ValueError:
        return {"ilegible": True}


def _escribir_dueno(archivo, raiz_norm: str) -> None:
    datos = json.dumps({"pid": os.getpid(), "raiz": raiz_norm, "inicio": datetime.now(timezone.utc).isoformat(),
                        "proceso": " ".join(sys.argv[:2])[:300]}, ensure_ascii=False).encode("utf-8")
    archivo.seek(0)
    if archivo.write(datos) != len(datos):
        raise OSError(errno.EIO, "escritura incompleta del archivo de turno")
    archivo.truncate(len(datos))
    os.fsync(archivo.fileno())


def _soltar_archivo(archivo, *, bloqueado: bool, vaciar: bool) -> None:
    """Libera lo físico. El cierre del handle es incondicional."""
    if archivo.closed:
        return
    try:
        if vaciar:
            _punto("durante_vaciado")
            try:
                archivo.truncate(0)
            except OSError as error:  # sólo cuesta un falso positivo de abandono
                log.warning("No se pudo vaciar el archivo de turno: %s", error)
    finally:
        try:
            if bloqueado:
                _punto("durante_desbloqueo")
                archivo.seek(DESPLAZAMIENTO_BLOQUEO)
                msvcrt.locking(archivo.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError as error:
            log.warning("Fallo al desbloquear el archivo de turno: %s", error)
            raise ErrorTurno(f"No se pudo desbloquear el archivo de turno: {error}") from error
        finally:
            archivo.close()


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


# --------------------------------------------------------------- propietario

@dataclass(eq=False)
class _PropietarioRaiz:
    archivo: object
    dueno: "TurnoEscritura"


# Sólo protege los diccionarios (lo consulta la guardia): se toma por
# instantes, nunca durante una espera ni una E/S.
_registro = threading.RLock()
_propietarios: dict[str, _PropietarioRaiz] = {}
_transiciones: dict[str, "_TransicionRaiz"] = {}


class _TransicionRaiz:
    """Serializa adquirir y soltar de una raíz dentro del proceso. La posee un
    testigo por llamada, no un ``Lock`` tomado con plazo: tras un ``acquire``
    exitoso cabe una interrupción antes del ``try`` y el ``Lock`` quedaría
    tomado para siempre. El testigo se fija DENTRO del ``try`` y se borra con
    una asignación sin llamadas."""

    def __init__(self) -> None:
        self.dueno = None


def _transicion(raiz_norm: str) -> _TransicionRaiz:
    with _registro:
        return _transiciones.setdefault(raiz_norm, _TransicionRaiz())


def _tomar_transicion(transicion: _TransicionRaiz, testigo: object, limite: float) -> bool:
    while True:
        with _registro:
            if transicion.dueno is None:
                transicion.dueno = testigo
                return True
        if time.monotonic() >= limite:
            return False
        time.sleep(INTERVALO_TRANSICION_SEGUNDOS)


class TurnoEscritura:
    """Turno local de escritura sobre ``raiz``. Uso:

    ``with TurnoEscritura(raiz): ...`` (lanza ``TurnoOcupado``), o
    ``adquirir()`` -> bool y ``soltar()`` (idempotente).

    ``adquirir`` devuelve False si otro proceso u otra instancia lo tiene y
    lanza ``ErrorTurno`` si el mecanismo falla. Una instancia aporta como
    máximo una posesión: volver a pedirlo siendo dueña devuelve True sin
    efecto y un único ``soltar`` lo libera.

    Toda espera tiene un plazo finito. La transición de la raíz serializa
    adquirir y soltar, también entre hilos de una misma instancia.
    """

    def __init__(self, raiz, *, espera_segundos: float = 0.0) -> None:
        self.raiz_norm = normalizar_raiz(raiz)
        espera = float(espera_segundos)
        if not math.isfinite(espera) or espera < 0:
            raise ValueError("espera_segundos debe ser finita y no negativa")
        self.espera_segundos = espera
        self.abandonado = False
        self.error = ""

    @property
    def vigente(self) -> bool:
        with _registro:
            propietario = _propietarios.get(self.raiz_norm)
            return propietario is not None and propietario.dueno is self and not propietario.archivo.closed

    def adquirir(self) -> bool:
        fin = time.monotonic() + self.espera_segundos
        transicion = _transicion(self.raiz_norm)
        testigo = object()
        try:
            if not _tomar_transicion(transicion, testigo, fin + MARGEN_TRANSICION_SEGUNDOS):
                self.error = "otra transición del turno en este proceso no terminó en plazo"
                return False
            if self.vigente:
                return True
            try:
                return self._tomar(fin)
            except BaseException:
                # Una interrupción justo al volver no deja una posesión que el
                # llamador desconoce.
                self._liberar(vaciar=not self.abandonado)
                raise
        finally:
            if transicion.dueno is testigo:  # sin llamadas: no cabe otra interrupción
                transicion.dueno = None

    def _tomar(self, fin: float) -> bool:
        with _registro:
            propietario = _propietarios.get(self.raiz_norm)
            if propietario is not None and propietario.archivo.closed:
                del _propietarios[self.raiz_norm]  # handle ya cerrado: nada físico que respetar
                propietario = None
        if propietario is not None:
            self.error = "otra instancia de este proceso posee el turno"
            return False
        if msvcrt is None:
            raise ErrorTurno("El turno de escritura sólo está disponible en Windows.")
        try:
            archivo = _abrir_archivo_turno(self.raiz_norm)
        except OSError as error:
            raise ErrorTurno(f"Archivo de turno no disponible: {error}") from error
        bloqueado = escrito = registrado = conservar = False
        previo = None
        try:
            _punto("tras_abrir")
            bloqueado = _intentar_bloqueo(archivo, fin)
            if not bloqueado:
                return False
            _punto("tras_bloquear")
            previo = _leer_dueno_previo(archivo)
            _punto("tras_leer_previo")
            if previo is not None:
                log.warning("Turno de escritura abandonado por un proceso terminado (%s); requiere verificación.",
                            self.raiz_norm)
                _anotar_abandono(self.raiz_norm, previo, "ARCHIVO_TURNO")
            _escribir_dueno(archivo, self.raiz_norm)
            escrito = True
            _punto("tras_escribir_pid")
            _punto("antes_registrar")
            self.error = ""
            self.abandonado = previo is not None
            with _registro:  # último paso: desde aquí el proceso posee el turno
                _propietarios[self.raiz_norm] = _PropietarioRaiz(archivo, self)
                registrado = True
            _punto("tras_registrar")
            conservar = True
            return True
        except OSError as error:
            raise ErrorTurno(f"Bloqueo de turno no disponible: {error}") from error
        finally:
            if not conservar:
                if registrado:
                    with _registro:
                        _propietarios.pop(self.raiz_norm, None)
                # Una señal de abandono recibida no se borra: el siguiente la verá.
                try:
                    _soltar_archivo(archivo, bloqueado=bloqueado, vaciar=escrito and previo is None)
                except OSError as error:
                    log.warning("Fallo al deshacer la adquisición del turno: %s", error)

    def soltar(self) -> None:
        transicion = _transicion(self.raiz_norm)
        testigo = object()
        try:
            limite = time.monotonic() + self.espera_segundos + MARGEN_TRANSICION_SEGUNDOS
            if not _tomar_transicion(transicion, testigo, limite):
                raise ErrorTurno(f"No se pudo soltar el turno de {self.raiz_norm}: transición bloqueada")
            self._liberar(vaciar=True)
        finally:
            if transicion.dueno is testigo:
                transicion.dueno = None

    def _liberar(self, *, vaciar: bool) -> None:
        """Dentro de la transición: lo lógico primero, lo físico en ``finally``."""
        retirado = None
        try:
            with _registro:
                propietario = _propietarios.get(self.raiz_norm)
                if propietario is None or propietario.dueno is not self:
                    return
                del _propietarios[self.raiz_norm]
                retirado = propietario
            _punto("tras_retirar_registro")
        finally:
            if retirado is not None:
                _soltar_archivo(retirado.archivo, bloqueado=True, vaciar=vaciar)

    def __enter__(self) -> "TurnoEscritura":
        try:
            obtenido = self.adquirir()
        except BaseException:
            self.soltar()  # una interrupción al volver no deja posesión sin __exit__
            raise
        if not obtenido:
            raise TurnoOcupado(f"Otro proceso Atlas de este equipo está escribiendo en {self.raiz_norm}.")
        return self

    def __exit__(self, *_args) -> None:
        self.soltar()


def posee_turno(ruta) -> bool:
    """True si este proceso posee el turno de una raíz que contiene ``ruta``."""
    ruta_norm = os.path.normcase(os.path.abspath(os.fsdecode(ruta)))
    with _registro:
        return any(not propietario.archivo.closed and _dentro(ruta_norm, raiz)
                   for raiz, propietario in _propietarios.items())


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
    if evento in {"os.rename", "os.link", "os.symlink", "shutil.move"}:
        return list(args[:2])
    if evento in {"shutil.copyfile", "shutil.copytree", "shutil.copymode", "shutil.copystat", "_winapi.CopyFile2"}:
        # En Windows (3.12+) copy2 y el respaldo de move copian con CopyFile2
        # nativo, sin evento `open`: el destino viene en estos eventos.
        return [args[1]]
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
                      "os.truncate", "os.chmod", "os.utime", "shutil.rmtree", "shutil.move", "shutil.copyfile",
                      "shutil.copytree", "shutil.copymode", "shutil.copystat", "_winapi.CopyFile2"})
_instalada = False


def instalar_guardia() -> None:
    """Idempotente: un único audit hook por intérprete (no se puede quitar)."""
    global _instalada
    if _instalada:
        return
    sys.addaudithook(_guardia)
    _instalada = True
