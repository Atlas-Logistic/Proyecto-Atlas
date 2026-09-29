"""Cliente del lease global de escritor operativo de Atlas Mobile Cloud.

La identidad vive en almacenamiento local del PC, nunca en la raíz Atlas ni
en Google Drive. Si Cloud no responde o el lease está ocupado, el llamador
queda en modo seguro: no inicia escrituras operacionales.
"""
from __future__ import annotations

import json
import os
import threading
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Callable


LEASE_HEARTBEAT_SEGUNDOS = 30.0
MARGEN_RELEVO_SEGUNDOS = 30.0


class ErrorEscritorOperativo(RuntimeError):
    pass


def _url(base_url: str, ruta: str) -> str:
    url = base_url.rstrip("/") + ruta
    if not url.startswith("https://"):
        raise ErrorEscritorOperativo("Escritor operativo requiere HTTPS saliente")
    return url


def _json(base_url: str, ruta: str, token: str, *, method: str = "GET", body: dict | None = None, timeout: float) -> dict:
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(_url(base_url, ruta), method=method, data=data, headers={
        "Authorization": f"Bearer {token}", "Content-Type": "application/json",
        "User-Agent": "Atlas-Escritor-Operativo/1.0",
    })
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read())
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as error:
        raise ErrorEscritorOperativo(f"Cloud escritor {method} {ruta}: {error}") from error


def ruta_identidad_escritor() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".local")
    return base / "Atlas" / "escritor_operativo_id.txt"


def identidad_escritor(*, ruta: Path | None = None) -> str:
    """Identidad estable por instalación, con override explícito para soporte."""
    override = os.environ.get("ATLAS_ESCRITOR_ID", "").strip()
    if override:
        return override
    ruta = ruta or ruta_identidad_escritor()
    try:
        existente = ruta.read_text(encoding="utf-8").strip()
        if existente:
            return existente
    except OSError:
        pass
    ruta.parent.mkdir(parents=True, exist_ok=True)
    nueva = f"pc-{uuid.uuid4()}"
    try:
        with ruta.open("x", encoding="utf-8") as archivo:
            archivo.write(nueva)
        return nueva
    except FileExistsError:
        return ruta.read_text(encoding="utf-8").strip()


class LeaseEscritorOperativo:
    """Lease global cooperativo; el contexto libera sólo al cerrar el PULL."""

    def __init__(
        self, *, base_url: str, token_motor: str, escritor_id: str | None = None,
        timeout: float = 30.0, heartbeat_segundos: float = LEASE_HEARTBEAT_SEGUNDOS,
        margen_relevo_segundos: float = MARGEN_RELEVO_SEGUNDOS,
        dormir: Callable[[float], None] | None = None,
    ) -> None:
        self.base_url = base_url
        self.token_motor = token_motor
        self.escritor_id = escritor_id or identidad_escritor()
        self.timeout = timeout
        self.heartbeat_segundos = heartbeat_segundos
        self.margen_relevo_segundos = margen_relevo_segundos
        self._dormir = dormir or (lambda segundos: self._detener.wait(segundos))
        self.lease_token = ""
        self.epoca = 0
        self._detener = threading.Event()
        self._perdido = threading.Event()
        self._hilo: threading.Thread | None = None

    @property
    def vigente(self) -> bool:
        return bool(self.lease_token) and not self._perdido.is_set()

    def consultar(self) -> dict:
        return _json(self.base_url, "/api/motor/escritor/estado", self.token_motor, timeout=self.timeout)

    def adquirir(self) -> bool:
        try:
            previo = self.consultar()
            respuesta = _json(
                self.base_url, "/api/motor/escritor/adquirir", self.token_motor,
                method="POST", body={"escritor_id": self.escritor_id}, timeout=self.timeout,
            )
        except ErrorEscritorOperativo:
            return False
        token = str(respuesta.get("lease_token") or "")
        if respuesta.get("estado") != "ADQUIRIDO" or not token:
            return False
        self.lease_token = token
        self.epoca = int(respuesta.get("epoca") or 0)
        self._iniciar_heartbeat()
        # epoca previa > 0 significa que ya hubo un titular. Este cliente no
        # distingue vencimiento de liberación voluntaria: aplica el margen en
        # ambos casos, conservador y sin depender de Drive.
        if int(previo.get("epoca") or 0) > 0 and self.margen_relevo_segundos > 0:
            self._dormir(self.margen_relevo_segundos)
        if not self.vigente:
            self.cerrar()
            return False
        return True

    def renovar(self) -> bool:
        if not self.vigente:
            return False
        try:
            respuesta = _json(
                self.base_url, "/api/motor/escritor/renovar", self.token_motor,
                method="POST", body={"lease_token": self.lease_token}, timeout=self.timeout,
            )
            if respuesta.get("estado") != "RENOVADO":
                raise ErrorEscritorOperativo("renovación global inválida")
            return True
        except ErrorEscritorOperativo:
            self._perdido.set()
            return False

    def _iniciar_heartbeat(self) -> None:
        if self.heartbeat_segundos <= 0:
            return

        def latir() -> None:
            while not self._detener.wait(self.heartbeat_segundos):
                if not self.renovar():
                    return

        self._hilo = threading.Thread(target=latir, name="atlas-escritor-operativo", daemon=True)
        self._hilo.start()

    def cerrar(self) -> None:
        self._detener.set()
        if self._hilo is not None:
            self._hilo.join(timeout=self.timeout + 1)
        if self.lease_token:
            try:
                _json(
                    self.base_url, "/api/motor/escritor/liberar", self.token_motor,
                    method="POST", body={"lease_token": self.lease_token}, timeout=self.timeout,
                )
            except ErrorEscritorOperativo:
                pass
        self.lease_token = ""

    def __enter__(self) -> "LeaseEscritorOperativo":
        return self

    def __exit__(self, _tipo, _valor, _traza) -> None:
        self.cerrar()
