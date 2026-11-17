"""Protocolo de instalaci?n: transacci?n de pausa con recuperaci?n verificable.

El adaptador debe proporcionar journal durable, guardia independiente e
interlock de escritores. Este m?dulo no habilita por s? solo una instalaci?n.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import PureWindowsPath
from typing import Protocol, Sequence


@dataclass(frozen=True)
class Proceso:
    pid: int
    padre: int
    argumentos: tuple[str, ...]


def procesos_del_motor(procesos: Sequence[Proceso], directorio_motor: str) -> set[int]:
    """Identifica scripts del checkout instalado y sus hijos, no otros Python.

    Una invocaci?n sin ruta identificable no demuestra que sea ajena; el
    adaptador debe cerrar el acceso de Desktop y tomar el interlock, adem?s
    de esta comprobaci?n, antes de cambiar c?digo.
    """
    raiz = str(PureWindowsPath(directorio_motor)).casefold().rstrip("\\")
    raices = set()
    for proceso in procesos:
        for argumento in proceso.argumentos[1:]:
            texto = str(PureWindowsPath(argumento.strip('"'))).casefold()
            if texto.startswith(raiz + "\\") and texto.endswith((".py", ".ps1", ".exe")):
                raices.add(proceso.pid)
                break
    relacionados = set(raices)
    while True:
        nuevos = {p.pid for p in procesos if p.padre in relacionados} - relacionados
        if not nuevos:
            return relacionados
        relacionados |= nuevos


class Adaptador(Protocol):
    def preparar(self) -> None: ...
    def tareas_activas(self) -> Sequence[str]: ...
    def registrar_recuperacion(self, tareas: Sequence[str]) -> None: ...
    def armar_guardia(self, tareas: Sequence[str]) -> None: ...
    def comprobar_guardia(self) -> bool: ...
    def pausar(self, tarea: str) -> None: ...
    def esperar_ciclos(self) -> None: ...
    def adquirir_interlock(self) -> None: ...
    def comprobar_exclusividad(self) -> None: ...
    def instalar(self) -> None: ...
    def comprobar_motor_recuperable(self) -> None: ...
    def liberar_interlock(self) -> None: ...
    def reactivar(self, tarea: str) -> None: ...
    def activa(self, tarea: str) -> bool: ...
    def verificar_continuidad(self, tareas: Sequence[str]) -> None: ...
    def cerrar_recuperacion(self) -> None: ...


class RecuperacionIncompleta(RuntimeError):
    pass


def instalar_con_recuperacion(adaptador: Adaptador) -> None:
    """Ejecuta la instalaci?n s?lo con guardia e interlock ya comprobables.

    El journal contiene todas las tareas inicialmente activas ANTES de la
    primera pausa, incluso si pausar cambia el estado y luego lanza error.
    La guardia se conserva hasta comprobar reactivaci?n y continuidad.
    """
    adaptador.preparar()  # incluye respaldo, compatibilidad y acceso de Desktop
    tareas = tuple(adaptador.tareas_activas())
    if not tareas or len(set(tareas)) != len(tareas):
        raise RuntimeError("Inventario de tareas incompleto o ambiguo")
    adaptador.registrar_recuperacion(tareas)
    adaptador.armar_guardia(tareas)
    if not adaptador.comprobar_guardia():
        raise RuntimeError("Guardia de recuperaci?n no disponible; instalaci?n bloqueada")
    error = None
    bloqueado = False
    try:
        for tarea in tareas:
            adaptador.pausar(tarea)
        adaptador.esperar_ciclos()  # ning?n ciclo ni hijo productivo a medio ejecutar
        adaptador.adquirir_interlock()
        bloqueado = True
        adaptador.comprobar_exclusividad()  # revalidaci?n despu?s del interlock
        adaptador.instalar()
    except BaseException as exc:
        error = exc
    fallos = []
    if bloqueado:
        try:
            adaptador.comprobar_motor_recuperable()
        except BaseException as exc:
            # No arranca PULL contra c?digo parcialmente instalado. El journal
            # y la guardia quedan activos para una recuperaci?n segura.
            raise RecuperacionIncompleta("Motor no verificable; recuperaci?n bloqueada") from exc
    if bloqueado:
        try:
            adaptador.liberar_interlock()
        except BaseException as exc:
            fallos.append(exc)
    for tarea in tareas:
        try:
            adaptador.reactivar(tarea)
            if not adaptador.activa(tarea):
                raise RuntimeError(f"Tarea no reactivada: {tarea}")
        except BaseException as exc:
            fallos.append(exc)
    if not fallos:
        try:
            adaptador.verificar_continuidad(tareas)
            adaptador.cerrar_recuperacion()
        except BaseException as exc:
            fallos.append(exc)
    if fallos:
        raise RecuperacionIncompleta("PULL no recuperado o no verificado; guardia y journal permanecen") from fallos[0]
    if error:
        raise error
