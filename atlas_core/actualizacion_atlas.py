"""Actualización automática de Motor y Desktop entre equipos (P0.5).

Una VERSIÓN es un descriptor publicado en la custodia Cloud de la empresa
(``.atlas_custodia/version/vigente.json``, confirmado bajo lease como el
diario de recuperación) que fija:

- el Motor: rama y commit, que debe estar publicado en ``origin`` (mismo
  criterio que ``scripts/actualizar_equipo_relevo.ps1``);
- Desktop (opcional): un paquete zip con ``app.asar`` y
  ``app.asar.unpacked``, subido a R2 y verificado por SHA-256;
- ``nivel_custodia_minimo``: un Motor con ``NIVEL_CUSTODIA`` menor no alinea
  ni escribe (``MotorIncompatible``) hasta actualizarse.

Al iniciar Atlas, ``actualizar`` compara lo instalado con la versión vigente
y, si difiere: verifica todo antes de tocar nada, toma el turno local de la
raíz (el PULL no corre en paralelo), escribe un diario de actualización,
respalda Desktop (``app.asar.antes-<version>``), aplica Motor (``git reset
--keep``) y Desktop, y comprueba la salud de la nueva versión en un proceso
nuevo. Ante cualquier falla vuelve a la versión anterior. Si el proceso se
corta a mitad, el siguiente arranque encuentra el diario, revierte y
reintenta. Una versión que falla ``MAX_INTENTOS`` veces no se reintenta
hasta que se publique otra.
"""
from __future__ import annotations

import hashlib
import io
import json
import logging
import os
import shutil
import struct
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

# Nivel de compatibilidad de custodia que implementa ESTE Motor. Se sube
# cuando un cambio hace inseguro que escriba un Motor anterior.
NIVEL_CUSTODIA = 1
RUTA_DESCRIPTOR = ".atlas_custodia/version/vigente.json"
TIPO_DESCRIPTOR = "ATLAS_VERSION"
MAX_INTENTOS = 2
ASAR, DESEMPAQUETADO = "app.asar", "app.asar.unpacked"
# SÓLO PRUEBAS: simula un corte de energía al terminar la fase indicada.
VARIABLE_CORTE = "ATLAS_PRUEBA_CORTE_ACTUALIZACION"

log = logging.getLogger(__name__)


class ErrorActualizacion(RuntimeError):
    pass


def _sha(datos: bytes) -> str:
    return hashlib.sha256(datos).hexdigest()


def _serializar(datos: dict) -> bytes:
    return json.dumps(datos, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("ascii")


def _ahora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ----------------------------------------------------------- descriptor
def validar_descriptor(d: dict) -> dict:
    if not isinstance(d, dict) or d.get("tipo") != TIPO_DESCRIPTOR or d.get("formato") != 1:
        raise ErrorActualizacion("descriptor de versión desconocido")
    motor, desktop = d.get("motor"), d.get("desktop")
    if not (isinstance(d.get("version"), str) and d["version"] and isinstance(d.get("nivel_custodia_minimo"), int)
            and isinstance(motor, dict) and isinstance(motor.get("rama"), str) and motor["rama"]
            and isinstance(motor.get("commit"), str) and len(motor["commit"]) == 40):
        raise ErrorActualizacion("descriptor de versión incompleto")
    if desktop is not None and not (isinstance(desktop, dict) and isinstance(desktop.get("paquete_sha256"), str)
                                    and len(desktop["paquete_sha256"]) == 64):
        raise ErrorActualizacion("descriptor de Desktop inválido")
    return d


def leer_descriptor(manifiesto: dict, descargar) -> dict | None:
    sha = manifiesto.get(RUTA_DESCRIPTOR)
    if not sha:
        return None
    datos = descargar(sha)
    if _sha(datos) != sha:
        raise ErrorActualizacion("descriptor de versión no coincide con su huella")
    return validar_descriptor(json.loads(datos.decode("ascii")))


def exigir_compatibilidad(manifiesto: dict, descargar) -> None:
    """En la alineación: un Motor bajo el nivel publicado no escribe."""
    from atlas_core.estado_confirmado import MotorIncompatible
    try:
        descriptor = leer_descriptor(manifiesto, descargar)
    except ErrorActualizacion as error:
        raise MotorIncompatible(f"versión publicada no verificable: {error}") from error
    if descriptor and descriptor["nivel_custodia_minimo"] > NIVEL_CUSTODIA:
        raise MotorIncompatible(
            f"Motor con nivel de custodia {NIVEL_CUSTODIA}; la versión {descriptor['version']} exige "
            f"{descriptor['nivel_custodia_minimo']}: actualizar antes de escribir")


# -------------------------------------------------------------- Desktop
def verificar_asar(ruta: Path) -> int:
    """Cabecera de un archivo asar (pickle de Chromium + JSON con "files")."""
    with open(ruta, "rb") as archivo:
        cabecera = archivo.read(16)
        if len(cabecera) < 16:
            raise ErrorActualizacion(f"{ruta.name}: asar truncado")
        uno, _pickle, payload, largo = struct.unpack("<4I", cabecera)
        if uno != 4 or not 0 < largo <= payload:
            raise ErrorActualizacion(f"{ruta.name}: cabecera asar inválida")
        try:
            indice = json.loads(archivo.read(largo).decode("utf-8"))
        except (UnicodeError, ValueError) as error:
            raise ErrorActualizacion(f"{ruta.name}: índice asar ilegible") from error
    if not isinstance(indice, dict) or not isinstance(indice.get("files"), dict):
        raise ErrorActualizacion(f"{ruta.name}: índice asar sin archivos")

    def contar(nodo: dict) -> int:
        return sum(contar(v["files"]) if isinstance(v, dict) and "files" in v else 1 for v in nodo.values())
    return contar(indice["files"])


def empaquetar_desktop(recursos: Path) -> bytes:
    """Paquete reproducible de Desktop: app.asar + app.asar.unpacked."""
    recursos = Path(recursos)
    verificar_asar(recursos / ASAR)
    salida = io.BytesIO()
    with zipfile.ZipFile(salida, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        miembros = [recursos / ASAR]
        if (recursos / DESEMPAQUETADO).is_dir():
            miembros += sorted(p for p in (recursos / DESEMPAQUETADO).rglob("*") if p.is_file())
        for ruta in miembros:
            info = zipfile.ZipInfo(ruta.relative_to(recursos).as_posix(), date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, ruta.read_bytes())
    return salida.getvalue()


def _extraer_paquete(datos: bytes, destino: Path) -> None:
    with zipfile.ZipFile(io.BytesIO(datos)) as zf:
        nombres = zf.namelist()
        if ASAR not in nombres:
            raise ErrorActualizacion("paquete Desktop sin app.asar")
        for nombre in nombres:
            partes = nombre.split("/")
            if (nombre.startswith("/") or ":" in nombre or ".." in partes
                    or not (nombre == ASAR or partes[0] == DESEMPAQUETADO)):
                raise ErrorActualizacion(f"paquete Desktop con ruta no permitida: {nombre}")
        zf.extractall(destino)
    verificar_asar(destino / ASAR)


# ----------------------------------------------------------------- git
def _git(motor: Path, *args: str, comprobar: bool = True) -> subprocess.CompletedProcess:
    r = subprocess.run(["git", "-C", str(motor), *args], capture_output=True, text=True, encoding="utf-8", errors="replace")
    if comprobar and r.returncode != 0:
        raise ErrorActualizacion(f"git {' '.join(args)}: {(r.stderr or r.stdout).strip()[-400:]}")
    return r


def commit_actual(motor: Path) -> str:
    return _git(motor, "rev-parse", "HEAD").stdout.strip()


def verificar_commit_publicado(motor: Path, rama: str, commit: str) -> None:
    """Mismo criterio que actualizar_equipo_relevo.ps1: el commit existe en origin/<rama>."""
    _git(motor, "fetch", "--quiet", "origin", rama)
    remoto = _git(motor, "rev-parse", "FETCH_HEAD").stdout.strip()
    if _git(motor, "cat-file", "-e", f"{commit}^{{commit}}", comprobar=False).returncode != 0:
        raise ErrorActualizacion(f"commit {commit[:12]} inexistente")
    if _git(motor, "merge-base", "--is-ancestor", commit, remoto, comprobar=False).returncode != 0:
        raise ErrorActualizacion(f"{commit[:12]} no está publicado en origin/{rama}")


# -------------------------------------------------------- publicación
def publicar_version(lease, *, version: str, rama: str, commit: str, motor: Path,
                     paquete_desktop: bytes | None, nivel_minimo: int) -> dict:
    """Bajo lease vigente y custodia alineada: sube el paquete Desktop y
    confirma el descriptor en la marca. No baja el nivel ya publicado."""
    custodia = lease.custodia
    from atlas_core.estado_confirmado import _activas, _escribir_json
    if custodia is None or custodia not in _activas or not lease.vigente:
        raise ErrorActualizacion("publicar una versión exige lease vigente y custodia alineada")
    if nivel_minimo > NIVEL_CUSTODIA:
        raise ErrorActualizacion(f"este Motor (nivel {NIVEL_CUSTODIA}) no puede exigir nivel {nivel_minimo}")
    verificar_commit_publicado(Path(motor), rama, commit)
    previo = leer_descriptor(custodia.manifiesto, custodia.cliente.descargar)
    if previo and nivel_minimo < previo["nivel_custodia_minimo"]:
        raise ErrorActualizacion(f"no se baja el nivel de custodia publicado ({previo['nivel_custodia_minimo']})")
    if previo and previo["version"] == version:
        raise ErrorActualizacion(f"la versión {version} ya está publicada")
    objetos = {}
    desktop = None
    if paquete_desktop is not None:
        with __import__("tempfile").TemporaryDirectory() as tmp:
            _extraer_paquete(paquete_desktop, Path(tmp))  # se publica sólo lo que se puede instalar
        desktop = {"paquete_sha256": _sha(paquete_desktop), "bytes": len(paquete_desktop)}
        objetos[desktop["paquete_sha256"]] = paquete_desktop
    descriptor = validar_descriptor({
        "tipo": TIPO_DESCRIPTOR, "formato": 1, "version": version, "nivel_custodia_minimo": nivel_minimo,
        "motor": {"rama": rama, "commit": commit}, "desktop": desktop,
        "publicado_por": lease.escritor_id, "publicado_en": _ahora(),
    })
    datos = _serializar(descriptor)
    sha = _sha(datos)
    objetos[sha] = datos
    for huella in custodia.cliente.faltantes(sorted(objetos)):
        custodia.cliente.subir(huella, objetos[huella], lease.lease_token)
    custodia.version = custodia.cliente.confirmar(lease.lease_token, custodia.version, [[RUTA_DESCRIPTOR, sha]])
    custodia.manifiesto[RUTA_DESCRIPTOR] = sha
    _escribir_json(custodia._ruta_manifiesto, {"version": custodia.version, "archivos": custodia.manifiesto})
    return {"publicada": version, "sha256": sha, "version_marca": custodia.version, "descriptor": descriptor}


# --------------------------------------------------------- actualizador
class Actualizador:
    def __init__(self, *, motor: Path, recursos: Path | None, estado: Path, cliente, python: str | None = None,
                 raiz: Path | None = None, proceso_desktop: str = "Atlas Viajes.exe",
                 desktop_exe: Path | None = None, espera_arranque: float = 90.0) -> None:
        # P0.6: con el ejecutable, la salud de Desktop incluye abrirlo de verdad.
        self.desktop_exe = Path(desktop_exe) if desktop_exe else None
        self.espera_arranque = espera_arranque
        self.motor = Path(motor)
        self.recursos = Path(recursos) if recursos else None
        self.estado = Path(estado)
        self.cliente = cliente
        self.python = python or sys.executable
        self.raiz = Path(raiz) if raiz else None
        self.proceso_desktop = proceso_desktop

    # rutas de estado (LOCALAPPDATA)
    @property
    def _diario(self): return self.estado / "actualizacion_en_curso.json"
    @property
    def _instalado(self): return self.estado / "version_instalada.json"
    @property
    def _fallidas(self): return self.estado / "versiones_fallidas.json"

    def _leer(self, ruta: Path, defecto):
        try:
            return json.loads(ruta.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return defecto

    def _escribir(self, ruta: Path, datos) -> None:
        ruta.parent.mkdir(parents=True, exist_ok=True)
        temporal = ruta.with_name(f"{ruta.name}.{os.getpid()}.tmp")
        temporal.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporal, ruta)

    def _corte(self, fase: str) -> None:
        if os.environ.get(VARIABLE_CORTE) == fase:
            os._exit(9)

    # ---------------------------------------------------------------
    def actualizar(self) -> dict:
        resultado: dict = {"motor_antes": commit_actual(self.motor)}
        if self._diario.exists():
            resultado["recuperacion"] = self._recuperar_interrumpida()
        try:
            manifiesto = {r: s for r, s, _v in self.cliente.manifiesto().get("archivos", [])}
            descriptor = leer_descriptor(manifiesto, self.cliente.descargar)
        except Exception as error:  # noqa: BLE001 - sin Cloud se arranca con lo instalado
            return {**resultado, "estado": "SIN_VERIFICAR", "detalle": str(error)}
        if descriptor is None:
            return {**resultado, "estado": "SIN_VERSION_PUBLICADA"}
        clave = self._clave(descriptor, manifiesto)
        resultado["version"] = descriptor["version"]
        if self._al_dia(descriptor):
            return {**resultado, "estado": "AL_DIA"}
        fallidas = self._leer(self._fallidas, {})
        if fallidas.get(clave, {}).get("intentos", 0) >= MAX_INTENTOS:
            return {**resultado, "estado": "VERSION_FALLIDA_OMITIDA", "detalle": fallidas[clave]}
        return {**resultado, **self._aplicar(descriptor, clave)}

    def _clave(self, descriptor: dict, manifiesto: dict) -> str:
        return manifiesto.get(RUTA_DESCRIPTOR) or _sha(_serializar(descriptor))

    def _al_dia(self, descriptor: dict) -> bool:
        if commit_actual(self.motor) != descriptor["motor"]["commit"]:
            return False
        if descriptor["desktop"] is None or self.recursos is None:
            return True
        instalado = self._leer(self._instalado, {})
        return (instalado.get("desktop_paquete_sha256") == descriptor["desktop"]["paquete_sha256"]
                and (self.recursos / ASAR).is_file()
                and _sha((self.recursos / ASAR).read_bytes()) == instalado.get("desktop_asar_sha256"))

    def _desktop_en_uso(self) -> bool:
        if os.name != "nt" or not self.proceso_desktop:
            return False
        r = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {self.proceso_desktop}", "/NH"], capture_output=True,
                           text=True, encoding="utf-8", errors="replace")
        return self.proceso_desktop.lower() in (r.stdout or "").lower()

    def _aplicar(self, descriptor: dict, clave: str) -> dict:
        objetivo = descriptor["motor"]["commit"]
        usa_desktop = descriptor["desktop"] is not None and self.recursos is not None
        # 1. Todo se verifica antes de tocar nada.
        try:
            if _git(self.motor, "status", "--porcelain", "--untracked-files=no").stdout.strip():
                raise ErrorActualizacion("el Motor instalado tiene cambios sin commit")
            if usa_desktop and self._desktop_en_uso():
                raise ErrorActualizacion("Desktop está abierto; se actualiza en el próximo inicio")
            verificar_commit_publicado(self.motor, descriptor["motor"]["rama"], objetivo)
            staging = None
            if usa_desktop:
                paquete = self.cliente.descargar(descriptor["desktop"]["paquete_sha256"])
                if _sha(paquete) != descriptor["desktop"]["paquete_sha256"]:
                    raise ErrorActualizacion("paquete Desktop no coincide con su huella")
                staging = self.recursos / f".atlas_actualizar_{descriptor['desktop']['paquete_sha256'][:16]}"
                shutil.rmtree(staging, ignore_errors=True)
                _extraer_paquete(paquete, staging)
        except Exception as error:  # noqa: BLE001
            return {"estado": "NO_APLICADA", "detalle": str(error)}
        # 2. Turno local: el PULL de este equipo no corre en paralelo.
        turno = None
        if self.raiz is not None:
            from atlas_core.exclusion_local import TurnoEscritura
            turno = TurnoEscritura(self.raiz, espera_segundos=30)
            if not turno.adquirir():
                if staging is not None:
                    shutil.rmtree(staging, ignore_errors=True)
                return {"estado": "NO_APLICADA", "detalle": "turno local ocupado (PULL en curso)"}
        try:
            antes = {"motor": commit_actual(self.motor), "desktop": None}
            if usa_desktop:
                sufijo = f"antes-{descriptor['version']}".replace("/", "_").replace("\\", "_")
                respaldo = {"asar": str(self.recursos / f"{ASAR}.{sufijo}"),
                            "desempaquetado": str(self.recursos / f"{DESEMPAQUETADO}.{sufijo}"),
                            "asar_sha256": _sha((self.recursos / ASAR).read_bytes()),
                            "habia_desempaquetado": (self.recursos / DESEMPAQUETADO).is_dir()}
                antes["desktop"] = respaldo
            diario = {"objetivo": descriptor, "clave": clave, "antes": antes, "fase": "inicio",
                      "respaldo_completo": False, "inicio": _ahora()}
            self._escribir(self._diario, diario)
            if usa_desktop:
                # Respaldo atómico (mismo criterio que la instalación manual:
                # app.asar.antes-*); sólo uno completo se usa al revertir.
                temporal = Path(respaldo["asar"] + ".tmp")
                shutil.copy2(self.recursos / ASAR, temporal)
                os.replace(temporal, respaldo["asar"])
                if respaldo["habia_desempaquetado"]:
                    temporal = Path(respaldo["desempaquetado"] + ".tmp")
                    shutil.rmtree(temporal, ignore_errors=True)
                    shutil.copytree(self.recursos / DESEMPAQUETADO, temporal)
                    shutil.rmtree(respaldo["desempaquetado"], ignore_errors=True)
                    os.replace(temporal, respaldo["desempaquetado"])
                diario["respaldo_completo"] = True
                self._escribir(self._diario, diario)
            self._corte("respaldo")
            try:
                _git(self.motor, "reset", "--keep", objetivo)
                self._fase(diario, "motor")
                self._corte("motor")
                if usa_desktop:
                    os.replace(staging / ASAR, self.recursos / ASAR)
                    if (staging / DESEMPAQUETADO).is_dir():
                        shutil.rmtree(self.recursos / DESEMPAQUETADO, ignore_errors=True)
                        os.replace(staging / DESEMPAQUETADO, self.recursos / DESEMPAQUETADO)
                    self._fase(diario, "desktop")
                    self._corte("desktop")
                salud = self._salud(descriptor)
            except Exception as error:  # noqa: BLE001 - cualquier falla: versión anterior
                revertida = self._revertir(diario)
                self._registrar_falla(clave, descriptor["version"], str(error))
                return {"estado": "REVERTIDA", "detalle": str(error), "reversion": revertida}
            self._escribir(self._instalado, {
                "version": descriptor["version"], "motor_commit": objetivo,
                "desktop_paquete_sha256": (descriptor["desktop"] or {}).get("paquete_sha256"),
                "desktop_asar_sha256": _sha((self.recursos / ASAR).read_bytes()) if usa_desktop else None,
                "instalado_en": _ahora()})
            fallidas = self._leer(self._fallidas, {})
            fallidas.pop(clave, None)
            self._escribir(self._fallidas, fallidas)
            self._diario.unlink(missing_ok=True)
            return {"estado": "ACTUALIZADA", "motor_despues": objetivo, "salud": salud}
        finally:
            if staging is not None:
                shutil.rmtree(staging, ignore_errors=True)
            if turno is not None:
                turno.soltar()

    def _fase(self, diario: dict, fase: str) -> None:
        diario["fase"] = fase
        self._escribir(self._diario, diario)

    def _salud(self, descriptor: dict) -> dict:
        """En un proceso NUEVO con el Motor instalado: importa la custodia y
        los puntos de entrada y exige el nivel publicado. Desktop: asar sano."""
        codigo = ("import json, atlas_core.estado_confirmado, atlas_core.escritor_operativo, "
                  "atlas_core.actualizacion_atlas as a, sincronizar_mobile_cloud, desktop_operacion_cli; "
                  "print(json.dumps({'nivel': a.NIVEL_CUSTODIA}))")
        entorno = {**os.environ, "PYTHONPATH": str(self.motor), "PYTHONDONTWRITEBYTECODE": "1"}
        entorno.pop(VARIABLE_CORTE, None)
        r = subprocess.run([self.python, "-B", "-c", codigo], cwd=self.motor, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", env=entorno, timeout=300)
        if r.returncode != 0:
            raise ErrorActualizacion(f"Motor nuevo no arranca: {(r.stderr or r.stdout).strip()[-600:]}")
        nivel = json.loads(r.stdout.strip().splitlines()[-1])["nivel"]
        if nivel < descriptor["nivel_custodia_minimo"]:
            raise ErrorActualizacion(f"Motor nuevo con nivel {nivel} bajo el exigido {descriptor['nivel_custodia_minimo']}")
        salud = {"motor_nivel": nivel}
        if descriptor["desktop"] is not None and self.recursos is not None:
            salud["desktop_entradas_asar"] = verificar_asar(self.recursos / ASAR)
            if self.desktop_exe is not None:
                salud["desktop_arranque"] = self._arranque_desktop()
        return salud

    def _arranque_desktop(self) -> dict:
        """Arranque REAL de Electron con el asar instalado, aislado: sin
        datos (raíz vacía), sin credenciales, sin autorización de escritura
        y con carpeta de usuario temporal. Exige que cargue la ventana
        principal (protocolo de depuración local) y luego lo cierra."""
        import re
        import socket
        import tempfile
        import time
        import urllib.request
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            puerto = s.getsockname()[1]
        inicio = time.monotonic()
        with tempfile.TemporaryDirectory(prefix="atlas-arranque-", ignore_cleanup_errors=True) as tmp:
            base = Path(tmp)
            (base / "raiz").mkdir()
            (base / "config.json").write_text("{}", encoding="utf-8")
            entorno = {k: v for k, v in os.environ.items() if not re.match(r"(?i)(ATLAS_|OPENROUTER|CLOUD_)", k)}
            entorno.pop("ELECTRON_RUN_AS_NODE", None)
            entorno.update(ATLAS_USER_DATA_PATH=str(base / "userdata"), ATLAS_DATA_DIR=str(base / "raiz"),
                           ATLAS_CONFIG_PATH=str(base / "config.json"),
                           ATLAS_OPERACION_CONFIG=str(base / "sin_operacion.json"))
            proceso = subprocess.Popen([str(self.desktop_exe), f"--remote-debugging-port={puerto}"], env=entorno,
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                while time.monotonic() - inicio < self.espera_arranque:
                    if proceso.poll() is not None:
                        raise ErrorActualizacion(f"Desktop nuevo terminó al arrancar (código {proceso.returncode})")
                    try:
                        with urllib.request.urlopen(f"http://127.0.0.1:{puerto}/json/list", timeout=2) as r:
                            objetivos = json.loads(r.read())
                    except (OSError, ValueError):
                        objetivos = []
                    paginas = [o for o in objetivos if o.get("type") == "page" and ".html" in o.get("url", "")
                               and not o.get("url", "").startswith("devtools")]
                    if paginas:
                        time.sleep(2)  # no basta con abrir: debe seguir vivo
                        if proceso.poll() is not None:
                            raise ErrorActualizacion("Desktop nuevo se cerró tras abrir la ventana")
                        return {"pagina": paginas[0]["url"].rsplit("/", 1)[-1], "titulo": paginas[0].get("title", ""),
                                "segundos": round(time.monotonic() - inicio, 1)}
                    time.sleep(0.5)
                raise ErrorActualizacion(f"Desktop nuevo no abrió su ventana en {self.espera_arranque:.0f} s")
            finally:
                subprocess.run(["taskkill", "/T", "/F", "/PID", str(proceso.pid)], capture_output=True)
                try:
                    proceso.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    pass

    def _revertir(self, diario: dict) -> dict:
        antes = diario["antes"]
        _git(self.motor, "reset", "--keep", antes["motor"])
        respaldo = antes.get("desktop")
        if respaldo and self.recursos is not None and diario.get("respaldo_completo"):
            # Sólo con un respaldo completo; si el asar actual ya es el
            # original (corte antes de reemplazarlo) no se toca.
            actual = self.recursos / ASAR
            if not actual.is_file() or _sha(actual.read_bytes()) != respaldo["asar_sha256"]:
                temporal = self.recursos / f"{ASAR}.atlas_revertir.tmp"
                shutil.copy2(respaldo["asar"], temporal)
                if _sha(temporal.read_bytes()) != respaldo["asar_sha256"]:
                    raise ErrorActualizacion("respaldo de app.asar no coincide con el original")
                os.replace(temporal, actual)
            if respaldo.get("habia_desempaquetado") and Path(respaldo["desempaquetado"]).is_dir():
                shutil.rmtree(self.recursos / DESEMPAQUETADO, ignore_errors=True)
                shutil.copytree(respaldo["desempaquetado"], self.recursos / DESEMPAQUETADO)
        self._diario.unlink(missing_ok=True)
        return {"motor": commit_actual(self.motor),
                "desktop_asar_sha256": _sha((self.recursos / ASAR).read_bytes()) if self.recursos and (self.recursos / ASAR).is_file() else None}

    def _registrar_falla(self, clave: str, version: str, detalle: str) -> None:
        fallidas = self._leer(self._fallidas, {})
        previa = fallidas.get(clave, {})
        fallidas[clave] = {"version": version, "intentos": int(previa.get("intentos", 0)) + 1,
                           "ultimo_error": detalle[-800:], "fecha": _ahora()}
        self._escribir(self._fallidas, fallidas)
        log.warning("Versión %s revertida (intento %s): %s", version, fallidas[clave]["intentos"], detalle)

    def _recuperar_interrumpida(self) -> dict:
        """Arranque tras un corte a mitad: se vuelve a la versión anterior
        (siempre completa y respaldada) y el intento cuenta como fallido."""
        diario = self._leer(self._diario, None)
        if not isinstance(diario, dict) or "antes" not in diario:
            self._diario.unlink(missing_ok=True)
            return {"estado": "DIARIO_ILEGIBLE_DESCARTADO"}
        revertida = self._revertir(diario)
        objetivo = diario.get("objetivo") or {}
        self._registrar_falla(diario.get("clave", ""), objetivo.get("version", "?"),
                              f"actualización interrumpida en fase {diario.get('fase')}")
        return {"estado": "REVERTIDA_TRAS_CORTE", "fase": diario.get("fase"), "reversion": revertida}
