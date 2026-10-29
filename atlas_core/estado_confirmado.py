"""Custodia del estado operacional confirmado en Cloud (protocolo 2 del lease).

Drive replica archivo por archivo y sin garantía de orden ni de plazo: tras un
relevo de escritor, la copia local puede estar atrasada, a medias, o recibir
más tarde archivos viejos que otro equipo no alcanzó a subir antes de
apagarse. El lease Cloud ya impide escritores simultáneos; esta custodia le
agrega la marca del último estado confirmado:

- Al cerrar su turno, el titular publica en Cloud la huella SHA-256 de cada
  archivo operacional que modificó y sube su contenido (R2, direccionado por
  huella). La confirmación es atómica y exige lease vigente y versión base.
- Al adquirir, y antes de cualquier escritura, el titular alinea su copia
  local con la marca: lo que difiere se restaura desde Cloud. Un contenido
  local nunca confirmado se copia antes a cuarentena local (no se pierde).
  Si no se logra la coincidencia exacta, el lease se libera sin escribir.
- Las escrituras se registran con un audit hook de Python (todas las
  escrituras del Motor ocurren en proceso) y en un diario local, para que un
  apagado inesperado se confirme al volver si nadie confirmó entre medio.

`reportes/`, `respaldos/` y `backups/` quedan fuera: cada escritura crea una
carpeta con marca de tiempo única, nunca reemplaza contenido previo.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import sys
import threading
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

PROTOCOLO = 2
EXCLUIDOS_PRIMER_NIVEL = frozenset({
    "reportes", "respaldos", "backups", "_respaldos_desarrollo", "historico_pre_infra_s2", "investigacion",
})
# Línea base de la activación: archivos mutables que la operación reescribe.
SEMILLA_CARPETAS = ("operacion/actual", "operacion/procesamiento", "catalogos_privados", "fichas_digitales")
SEMILLA_ENVIOS = "operacion/mobile/envios"
LOTE_CONFIRMACION = 200
LOTE_CONSULTA = 500

log = logging.getLogger(__name__)


class EstadoNoVerificado(RuntimeError):
    """La copia local no coincide con la marca de Cloud: no se escribe."""


def ruta_local() -> Path:
    # Dentro de LOCALAPPDATA/Atlas/cache: única carpeta local que la sesión
    # Desktop autoriza a escribir además de la raíz y los temporales.
    base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".local")
    return base / "Atlas" / "cache" / "estado_confirmado"


def rastreable(rel: str) -> bool:
    partes = rel.split("/")
    if not partes or partes[0] in EXCLUIDOS_PRIMER_NIVEL:
        return False
    nombre = partes[-1]
    bajo = nombre.lower()
    return not (nombre.startswith(".atlas_lock_") or bajo.endswith(".tmp") or nombre.startswith("~$")
                or bajo == "desktop.ini" or ".atlas_restaurar." in nombre)


def sha256_archivo(ruta: Path) -> str:
    h = hashlib.sha256()
    with open(ruta, "rb") as archivo:
        for bloque in iter(lambda: archivo.read(1024 * 1024), b""):
            h.update(bloque)
    return h.hexdigest()


def _leer_json(ruta: Path, defecto):
    try:
        return json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return defecto


def _escribir_json(ruta: Path, datos) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    temporal = ruta.with_name(f"{ruta.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    temporal.write_text(json.dumps(datos, ensure_ascii=False), encoding="utf-8")
    os.replace(temporal, ruta)


class ClienteEstado:
    """Endpoints /api/motor/estado/* del Worker, mismo token que el lease."""

    def __init__(self, base_url: str, token_motor: str, timeout: float) -> None:
        self.base_url = base_url
        self.token_motor = token_motor
        self.timeout = timeout

    def _json(self, ruta, *, method="GET", body=None):
        from atlas_core.escritor_operativo import _json
        return _json(self.base_url, ruta, self.token_motor, method=method, body=body, timeout=self.timeout)

    def manifiesto(self) -> dict:
        return self._json("/api/motor/estado/manifiesto")

    def conocidos(self, consultas: list[list[str]]) -> list[bool]:
        salida: list[bool] = []
        for i in range(0, len(consultas), LOTE_CONSULTA):
            salida += self._json("/api/motor/estado/conocidos", method="POST", body={"consultas": consultas[i:i + LOTE_CONSULTA]})["conocidos"]
        return salida

    def faltantes(self, huellas: list[str]) -> list[str]:
        salida: list[str] = []
        for i in range(0, len(huellas), LOTE_CONSULTA):
            salida += self._json("/api/motor/estado/faltantes", method="POST", body={"sha256": huellas[i:i + LOTE_CONSULTA]})["faltantes"]
        return salida

    def _crudo(self, sha: str, *, method: str, data: bytes | None = None, lease_token: str = "") -> bytes:
        from atlas_core.escritor_operativo import ErrorEscritorOperativo, _url
        headers = {"Authorization": f"Bearer {self.token_motor}", "User-Agent": "Atlas-Estado-Confirmado/1.0",
                   "Content-Type": "application/octet-stream"}
        if lease_token:
            headers["X-Atlas-Lease"] = lease_token
        request = urllib.request.Request(_url(self.base_url, f"/api/motor/estado/objetos/{sha}"), method=method, data=data, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=max(self.timeout, 120.0)) as response:
                return response.read()
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise ErrorEscritorOperativo(f"Cloud estado {method} objeto {sha[:12]}: {error}") from error

    def subir(self, sha: str, datos: bytes, lease_token: str) -> None:
        self._crudo(sha, method="PUT", data=datos, lease_token=lease_token)

    def descargar(self, sha: str) -> bytes:
        return self._crudo(sha, method="GET")

    def confirmar(self, lease_token: str, version_base: int, archivos: list[list]) -> int:
        respuesta = self._json("/api/motor/estado/confirmar", method="POST",
                               body={"lease_token": lease_token, "version_base": version_base, "archivos": archivos})
        if respuesta.get("estado") != "CONFIRMADO":
            raise EstadoNoVerificado("confirmación de estado rechazada")
        return int(respuesta["version"])


_activas: list["CustodiaEstado"] = []
_local = threading.local()


def _dir_fd(valor):
    # Windows informa -1 cuando no hay dir_fd; sólo un descriptor real impide
    # conocer la ruta absoluta.
    return valor if isinstance(valor, int) and valor >= 0 else None


def _auditar(evento, args):
    if not _activas or getattr(_local, "dentro", False):
        return
    if evento == "open":
        ruta, modo, flags = args
        if not ((modo and any(c in modo for c in "wax+")) or
                (flags and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND))):
            return
        destinos, dir_fd = [ruta], None
    elif evento == "os.rename":
        destinos, dir_fd = list(args[:2]), _dir_fd(args[2]) if _dir_fd(args[2]) is not None else _dir_fd(args[3])
    elif evento in {"os.remove", "os.truncate"}:
        destinos, dir_fd = [args[0]], _dir_fd(args[1]) if len(args) > 1 and evento == "os.remove" else None
    elif evento == "os.rmdir":
        destinos, dir_fd = [], _dir_fd(args[1]) if len(args) > 1 else None
        for custodia in tuple(_activas):
            if dir_fd is not None or custodia.contiene(args[0]):
                custodia.borrado_sin_ruta = True
        return
    else:
        return
    _local.dentro = True
    try:
        for custodia in tuple(_activas):
            if dir_fd is not None:
                custodia.borrado_sin_ruta = True
                continue
            for destino in destinos:
                if destino is not None and not isinstance(destino, int):
                    custodia.registrar(destino)
    finally:
        _local.dentro = False


sys.addaudithook(_auditar)


class CustodiaEstado:
    def __init__(self, raiz, cliente: ClienteEstado, *, carpeta_local: Path | None = None) -> None:
        self.raiz = Path(os.path.abspath(raiz))
        self._raiz_norm = os.path.normcase(str(self.raiz)).rstrip("\\/") + os.sep
        self.cliente = cliente
        self.local = carpeta_local or ruta_local()
        self.version = 0
        self.manifiesto: dict[str, str | None] = {}
        self.modificadas: set[str] = set()
        self.borrado_sin_ruta = False
        self.resumen: dict = {}
        self._lease = None
        self._cerrojo = threading.Lock()

    # --------------------------------------------------------------- rutas
    @property
    def _ruta_huellas(self): return self.local / "huellas.json"
    @property
    def _ruta_manifiesto(self): return self.local / "manifiesto.json"
    @property
    def _ruta_pendiente(self): return self.local / "pendiente.json"

    def contiene(self, ruta) -> bool:
        return os.path.normcase(os.path.abspath(os.fsdecode(ruta))).startswith(self._raiz_norm)

    def _rel(self, ruta) -> str | None:
        absoluta = os.path.abspath(os.fsdecode(ruta))
        if not os.path.normcase(absoluta).startswith(self._raiz_norm):
            return None
        return os.path.relpath(absoluta, self.raiz).replace(os.sep, "/")

    def _abs(self, rel: str) -> Path:
        return self.raiz.joinpath(*rel.split("/"))

    # ------------------------------------------------------------- huellas
    def _huellas_locales(self, rels) -> dict[str, str | None]:
        cache = _leer_json(self._ruta_huellas, {})
        salida = {}
        for rel in rels:
            ruta = self._abs(rel)
            try:
                st = ruta.stat()
            except OSError:
                salida[rel] = None
                continue
            if not ruta.is_file():
                salida[rel] = None
                continue
            previo = cache.get(rel)
            if previo and previo[0] == st.st_size and previo[1] == st.st_mtime_ns:
                salida[rel] = previo[2]
                continue
            sha = sha256_archivo(ruta)
            cache[rel] = [st.st_size, st.st_mtime_ns, sha]
            salida[rel] = sha
        _escribir_json(self._ruta_huellas, cache)
        return salida

    def _cargar_manifiesto(self, version: int) -> dict[str, str | None]:
        cache = _leer_json(self._ruta_manifiesto, {})
        if cache.get("version") == version and isinstance(cache.get("archivos"), dict):
            return cache["archivos"]
        datos = self.cliente.manifiesto()
        if int(datos.get("version", -1)) != version:
            raise EstadoNoVerificado("manifiesto Cloud cambió durante la alineación")
        archivos = {ruta: sha for ruta, sha, _v in datos.get("archivos", [])}
        _escribir_json(self._ruta_manifiesto, {"version": version, "archivos": archivos})
        return archivos

    # ---------------------------------------------------------- alineación
    def alinear(self, lease) -> dict:
        """Antes de escribir: copia local == marca Cloud, o EstadoNoVerificado."""
        self.version = int(lease.marca.get("version") or 0)
        self.manifiesto = dict(self._cargar_manifiesto(self.version))
        resumen = {"version": self.version, "restaurados": [], "borrados": [], "cuarentena": [], "pendiente_confirmado": 0}
        self._recuperar_pendiente(lease, resumen)
        locales = self._huellas_locales(self.manifiesto)
        distintos = {rel: sha for rel, sha in locales.items() if sha != self.manifiesto[rel]}
        if distintos:
            consultas = [[rel, sha] for rel, sha in distintos.items() if sha]
            conocidos = dict(zip((c[0] for c in consultas), self.cliente.conocidos(consultas))) if consultas else {}
            destino_cuarentena = self.local / "cuarentena" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            for rel, sha_local in sorted(distintos.items()):
                if sha_local and not conocidos.get(rel):
                    # Contenido nunca confirmado (escritura fuera de protocolo o
                    # turno caído y superado): se conserva fuera de Drive.
                    copia = destino_cuarentena.joinpath(*rel.split("/"))
                    copia.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(self._abs(rel), copia)
                    resumen["cuarentena"].append(rel)
                esperado = self.manifiesto[rel]
                if esperado is None:
                    self._abs(rel).unlink(missing_ok=True)
                    resumen["borrados"].append(rel)
                else:
                    self._restaurar(rel, esperado)
                    resumen["restaurados"].append(rel)
            if resumen["cuarentena"]:
                log.warning("Estado confirmado: %d archivo(s) local(es) nunca confirmados en cuarentena %s", len(resumen["cuarentena"]), destino_cuarentena)
            locales = self._huellas_locales(self.manifiesto)
            residuo = [rel for rel, sha in locales.items() if sha != self.manifiesto[rel]]
            if residuo:
                raise EstadoNoVerificado(f"copia local no coincide con la marca Cloud v{self.version}: {residuo[:5]}")
        self.resumen = resumen
        return resumen

    def _restaurar(self, rel: str, sha: str) -> None:
        datos = self.cliente.descargar(sha)
        if hashlib.sha256(datos).hexdigest() != sha:
            raise EstadoNoVerificado(f"contenido Cloud de {rel} no coincide con su huella")
        destino = self._abs(rel)
        destino.parent.mkdir(parents=True, exist_ok=True)
        temporal = destino.with_name(f".{destino.name}.atlas_restaurar.{os.getpid()}.tmp")
        temporal.write_bytes(datos)
        os.replace(temporal, destino)

    def _recuperar_pendiente(self, lease, resumen: dict) -> None:
        pendiente = _leer_json(self._ruta_pendiente, None)
        if not isinstance(pendiente, dict):
            return
        rutas = [r for r in pendiente.get("rutas", []) if isinstance(r, str) and rastreable(r)]
        if (pendiente.get("escritor_id") == lease.escritor_id and pendiente.get("version_base") == self.version
                and pendiente.get("raiz") == str(self.raiz) and rutas):
            # Turno anterior de este mismo equipo caído antes de confirmar y
            # nadie confirmó después: esas escrituras son el estado más nuevo.
            resumen["pendiente_confirmado"] = len(self._confirmar_rutas(lease, rutas))
        # Con la marca ya superada, la alineación pone esos archivos en
        # cuarentena (contenido nunca confirmado) y restaura la versión vigente.
        self._ruta_pendiente.unlink(missing_ok=True)

    # ------------------------------------------------------------ registro
    def iniciar(self, lease) -> None:
        self._lease = lease
        self.modificadas = set()
        self.borrado_sin_ruta = False
        _activas.append(self)

    def detener(self) -> None:
        if self in _activas:
            _activas.remove(self)
        self._lease = None

    def registrar(self, ruta) -> None:
        rel = self._rel(ruta)
        if rel is None or rel in self.modificadas or not rastreable(rel):
            return
        with self._cerrojo:
            self.modificadas.add(rel)
            lease = self._lease
            # Diario local antes de que la escritura ocurra: si el equipo se
            # apaga a mitad, el próximo turno sabe qué confirmar o aislar.
            _escribir_json(self._ruta_pendiente, {
                "escritor_id": getattr(lease, "escritor_id", ""), "version_base": self.version,
                "raiz": str(self.raiz), "rutas": sorted(self.modificadas),
            })

    # --------------------------------------------------------- confirmación
    def confirmar(self, lease) -> dict:
        rutas = set(self.modificadas)
        if self.borrado_sin_ruta:
            rutas |= {rel for rel, sha in self.manifiesto.items() if sha is not None and not self._abs(rel).exists()}
        confirmadas = self._confirmar_rutas(lease, sorted(rutas)) if rutas else []
        self._ruta_pendiente.unlink(missing_ok=True)
        self.modificadas = set()
        return {"version": self.version, "confirmados": len(confirmadas)}

    def _confirmar_rutas(self, lease, rutas) -> list[list]:
        rutas = [r for r in rutas if rastreable(r)]
        locales = self._huellas_locales(rutas)
        cambios = [[rel, sha] for rel, sha in sorted(locales.items()) if self.manifiesto.get(rel, "ausente") != sha]
        # Una ruta nueva que ya no existe (temporal efímero) no aporta estado.
        cambios = [c for c in cambios if c[1] is not None or c[0] in self.manifiesto]
        if not cambios:
            return []
        huellas = sorted({sha for _rel, sha in cambios if sha})
        for sha in self.cliente.faltantes(huellas) if huellas else []:
            rel = next(r for r, s in cambios if s == sha)
            datos = self._abs(rel).read_bytes()
            if hashlib.sha256(datos).hexdigest() != sha:
                raise EstadoNoVerificado(f"{rel} cambió durante la confirmación")
            self.cliente.subir(sha, datos, lease.lease_token)
        for i in range(0, len(cambios), LOTE_CONFIRMACION):
            lote = cambios[i:i + LOTE_CONFIRMACION]
            self.version = self.cliente.confirmar(lease.lease_token, self.version, lote)
            for rel, sha in lote:
                self.manifiesto[rel] = sha
            _escribir_json(self._ruta_manifiesto, {"version": self.version, "archivos": self.manifiesto})
        return cambios

    # -------------------------------------------------------------- semilla
    def rutas_semilla(self) -> list[str]:
        rels = []
        for carpeta in SEMILLA_CARPETAS:
            base = self._abs(carpeta)
            if base.is_dir():
                rels += [self._rel(p) for p in base.rglob("*") if p.is_file()]
        envios = self._abs(SEMILLA_ENVIOS)
        if envios.is_dir():
            rels += [self._rel(p) for p in envios.glob("*/envio.json") if p.is_file()]
        return sorted(r for r in rels if r and rastreable(r))

    def sembrar(self, lease) -> dict:
        """Activación: publica la línea base desde el equipo con el estado vigente."""
        return {"version": None, "confirmados": len(self._confirmar_rutas(lease, self.rutas_semilla())), "version_final": self.version}


def verificar_sin_escribir(raiz, cliente: ClienteEstado, *, carpeta_local: Path | None = None) -> dict:
    """Sólo lectura: cuántos archivos locales difieren de la marca vigente."""
    custodia = CustodiaEstado(raiz, cliente, carpeta_local=carpeta_local)
    datos = cliente.manifiesto()
    manifiesto = {ruta: sha for ruta, sha, _v in datos.get("archivos", [])}
    locales = custodia._huellas_locales(manifiesto)
    distintos = sorted(rel for rel, sha in locales.items() if sha != manifiesto[rel])
    return {"version": datos.get("version"), "protocolo_minimo": datos.get("protocolo_minimo"),
            "archivos": len(manifiesto), "distintos": len(distintos), "ejemplos": distintos[:10]}


def main(argv=None) -> int:
    import argparse
    from atlas_core.escritor_operativo import lease_desde_entorno
    parser = argparse.ArgumentParser(description="Estado operacional confirmado en Cloud (protocolo 2).")
    parser.add_argument("--raiz-atlas", required=True)
    accion = parser.add_mutually_exclusive_group(required=True)
    accion.add_argument("--sembrar", action="store_true", help="Activación: publica la línea base bajo lease (sólo el equipo con el estado vigente)")
    accion.add_argument("--verificar", action="store_true", help="Sólo lectura: compara la copia local con la marca vigente")
    args = parser.parse_args(argv)
    lease = lease_desde_entorno(raiz=args.raiz_atlas)
    if lease is None:
        parser.error("Falta ATLAS_CLOUD_MOTOR_TOKEN")
    if args.verificar:
        print(json.dumps(verificar_sin_escribir(args.raiz_atlas, lease.custodia.cliente), ensure_ascii=False))
        return 0
    with lease:
        if not lease.adquirir():
            print(json.dumps({"sembrado": False, "motivo": lease.motivo or "ESCRITOR_OCUPADO"}))
            return 1
        resultado = lease.custodia.sembrar(lease)
    print(json.dumps({"sembrado": True, **resultado}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    # Ejecutado con -m: delegar al módulo importado, el mismo que usa el lease
    # (un segundo audit hook y una segunda lista de custodias no registran nada).
    from atlas_core.estado_confirmado import main as _main
    raise SystemExit(_main())
