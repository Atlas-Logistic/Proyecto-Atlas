"""Proceso auxiliar REAL para tests/test_exclusion_local.py (no es una prueba).

Uso: python ayudante_exclusion_local.py <modo> <raiz> <control> [args...]

- ``control`` es una carpeta FUERA de la raíz protegida: el auxiliar escribe ahí
  sus señales (``<nombre>.json``) y espera órdenes (archivo ``soltar``).
- La raíz se protege con ATLAS_EXCLUSION_RAICES (la fija la prueba).
"""
from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from atlas_core import exclusion_local as el  # noqa: E402  (instala la guardia)


def senal(control: Path, nombre: str, **datos) -> None:
    temporal = control / f".{nombre}.{os.getpid()}.tmp"
    temporal.write_text(json.dumps({"pid": os.getpid(), **datos}), encoding="utf-8")
    os.replace(temporal, control / f"{nombre}.json")


def esperar_orden(control: Path, nombre: str, limite: float = 60.0) -> None:
    fin = time.monotonic() + limite
    while not (control / nombre).exists():
        if time.monotonic() > fin:
            raise SystemExit(f"sin orden {nombre}")
        time.sleep(0.02)


class CloudFalsa:
    """Cloud que siempre concede: aísla la exclusión LOCAL del arbitraje Cloud."""

    def __init__(self) -> None:
        self.llamadas = 0

    def __call__(self, _base, ruta, _token, *, method="GET", body=None, timeout=0):
        self.llamadas += 1
        if ruta.endswith("/estado"):
            return {"epoca": 0, "vigente": False}
        if ruta.endswith("/adquirir"):
            return {"estado": "ADQUIRIDO", "lease_token": f"t-{os.getpid()}-{self.llamadas}", "epoca": 1}
        if ruta.endswith("/renovar"):
            return {"estado": "RENOVADO"}
        if ruta.endswith("/liberar"):
            return {"estado": "LIBERADO"}
        raise AssertionError(ruta)


def lease(raiz: str, cloud: CloudFalsa):
    from atlas_core import escritor_operativo as eo
    eo._json = cloud
    os.environ["ATLAS_DATA_DIR"] = raiz
    return eo.LeaseEscritorOperativo(base_url="https://cloud.falsa", token_motor="x", escritor_id="pc-prueba",
                                     heartbeat_segundos=0, margen_relevo_segundos=0,
                                     ruta_relevo=Path(os.environ["LOCALAPPDATA"]) / "relevo.json")


def main() -> int:
    modo, raiz, control = sys.argv[1], sys.argv[2], Path(sys.argv[3])
    extra = sys.argv[4:]
    if modo == "tomar":  # toma el turno, avisa y lo sostiene hasta la orden
        espera = float(extra[0]) if extra else 0.0
        inicio = time.monotonic()
        turno = el.TurnoEscritura(raiz, espera_segundos=espera)
        ok = turno.adquirir()
        senal(control, "tomar", ok=ok, abandonado=turno.abandonado, espera=time.monotonic() - inicio)
        if not ok:
            return 3
        esperar_orden(control, "soltar")
        turno.soltar()
        senal(control, "soltado")
        return 0
    if modo == "cruzado":  # sostiene <raiz> y, a la orden, pide <otra> con espera acotada
        otra, espera = extra[0], float(extra[1])
        primero = el.TurnoEscritura(raiz)
        assert primero.adquirir()
        senal(control, "cruzado_tomado", ok=True)
        esperar_orden(control, "pedir")
        inicio = time.monotonic()
        segundo = el.TurnoEscritura(otra, espera_segundos=espera)
        ok = segundo.adquirir()
        senal(control, "cruzado", ok=ok, duracion=time.monotonic() - inicio)
        segundo.soltar()
        primero.soltar()
        return 0
    if modo == "tomar_y_morir":  # sostiene el turno y termina SIN soltarlo
        turno = el.TurnoEscritura(raiz)
        assert turno.adquirir()
        senal(control, "tomar", ok=True, abandonado=turno.abandonado)
        if extra and extra[0] == "exit":
            esperar_orden(control, "morir")
            os._exit(7)  # salida abrupta: sin finally ni atexit
        time.sleep(600)  # la prueba lo termina con TerminateProcess
        return 0
    if modo == "pausar_en":  # se detiene en un punto crítico para que la prueba lo mate
        punto = extra[0]

        def pausar(nombre: str) -> None:
            if nombre == punto:
                senal(control, "en_punto", punto=nombre)
                time.sleep(600)

        el._punto = pausar
        turno = el.TurnoEscritura(raiz)
        assert turno.adquirir()
        turno.soltar()
        return 0
    if modo == "tomar_con_hijo":  # sostiene el turno con un hijo de larga vida
        inherit = bool(extra and extra[0] == "heredar")
        turno = el.TurnoEscritura(raiz)
        assert turno.adquirir()
        archivo_pid = control / "hijo.pid"
        codigo = f"import os,time,pathlib;pathlib.Path(r'{archivo_pid}').write_text(str(os.getpid()));time.sleep(120)"
        subprocess.Popen([sys.executable, "-I", "-c", codigo], close_fds=not inherit,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        fin = time.monotonic() + 30
        while not archivo_pid.exists() and time.monotonic() < fin:
            time.sleep(0.02)
        senal(control, "tomar", ok=True, hijo=int(archivo_pid.read_text()))
        time.sleep(600)
        return 0
    if modo == "intervalos":  # alterna turnos y registra cuándo creyó poseerlo (QPC)
        duracion = float(extra[0])
        kernel = ctypes.WinDLL("kernel32")

        def qpc() -> int:
            valor = ctypes.c_longlong()
            kernel.QueryPerformanceCounter(ctypes.byref(valor))
            return valor.value

        marca = Path(raiz) / "exclusion.marca"
        intervalos, colisiones = [], 0
        fin = time.monotonic() + duracion
        while time.monotonic() < fin:
            turno = el.TurnoEscritura(raiz)
            if not turno.adquirir():
                continue
            inicio = qpc()
            assert el.posee_turno(raiz) and turno.vigente
            try:
                with open(marca, "x", encoding="utf-8"):
                    pass
                os.remove(marca)
            except FileExistsError:
                colisiones += 1
            termino = qpc()
            intervalos.append([inicio, termino])
            turno.soltar()
        senal(control, "intervalos", intervalos=intervalos, colisiones=colisiones)
        return 0
    if modo == "excepcion":  # una excepción dentro del turno lo libera
        try:
            with el.TurnoEscritura(raiz):
                senal(control, "tomar", ok=True)
                raise KeyboardInterrupt
        except KeyboardInterrupt:
            pass
        senal(control, "soltado")
        return 0
    if modo == "escribir":  # escribe en la raíz sin turno (o con, si se pide)
        con_turno = bool(extra and extra[0] == "con_turno")
        turno = el.TurnoEscritura(raiz) if con_turno else None
        if turno is not None and not turno.adquirir():
            senal(control, "escribir", ok=False, error="OCUPADO")
            return 3
        try:
            (Path(raiz) / f"escrito_{os.getpid()}.txt").write_text("x", encoding="utf-8")
            senal(control, "escribir", ok=True)
        except el.EscrituraSinTurno as error:
            senal(control, "escribir", ok=False, error=type(error).__name__)
        finally:
            if turno is not None:
                turno.soltar()
        return 0
    if modo == "lease_sostener":  # lease (Cloud falsa) + escritura, sostiene hasta la orden
        cloud = CloudFalsa()
        escritor = lease(raiz, cloud)
        ok = escritor.adquirir()
        if ok:
            (Path(raiz) / "dataset.csv").write_text("version_A", encoding="utf-8")
        senal(control, "lease", ok=ok, motivo=escritor.motivo, ocupado=escritor.ocupado, llamadas=cloud.llamadas)
        if ok:
            esperar_orden(control, "soltar")
            (Path(raiz) / "dataset.csv").write_text("version_A_tardia", encoding="utf-8")
            escritor.cerrar()
            senal(control, "soltado", turno_libre=escritor.turno is None)
        return 0
    if modo == "lease_intentar":  # un intento: no debe escribir si no obtiene el turno
        cloud = CloudFalsa()
        escritor = lease(raiz, cloud)
        ok = escritor.adquirir()
        escrito = False
        if ok:
            (Path(raiz) / "dataset.csv").write_text("version_B", encoding="utf-8")
            escrito = True
        sin_turno = "NO_PROBADO"
        if not ok:  # el escritor rechazado intenta escribir igual: la guardia lo detiene
            try:
                (Path(raiz) / "intento_sin_turno.txt").write_text("x", encoding="utf-8")
                sin_turno = "ESCRITO"
            except el.EscrituraSinTurno:
                sin_turno = "RECHAZADO"
        escritor.cerrar()
        senal(control, "intento", ok=ok, motivo=escritor.motivo, ocupado=escritor.ocupado,
              llamadas_cloud=cloud.llamadas, escrito=escrito, sin_turno=sin_turno)
        return 0
    if modo == "ciclos":  # ciclos tipo PULL/Desktop concurrentes con espera acotada
        from atlas_core import desktop_operacion as do
        nombre, ciclos = extra[0], int(extra[1])
        do.ESPERA_ESCRITOR_OCUPADO_SEGUNDOS = 60
        do.INTERVALO_ESCRITOR_OCUPADO_SEGUNDOS = 0.01
        cloud = CloudFalsa()
        hechos, esperas = 0, []
        for i in range(ciclos):
            escritor = lease(raiz, cloud)
            inicio = time.monotonic()
            if not do._adquirir_con_espera(escritor):
                senal(control, f"ciclos_{nombre}", ok=False, hechos=hechos, motivo=escritor.motivo)
                return 4
            esperas.append(time.monotonic() - inicio)
            try:
                # Sección crítica: un marcador exclusivo; dos dueños a la vez => colisión.
                marcador = Path(raiz) / "seccion_critica.marca"
                with open(marcador, "x", encoding="utf-8") as archivo:
                    archivo.write(f"{nombre}:{i}")
                time.sleep(0.01)
                (Path(raiz) / f"ciclo_{nombre}.txt").write_text(str(i), encoding="utf-8")
                marcador.unlink()
                hechos += 1
            finally:
                escritor.cerrar()
        senal(control, f"ciclos_{nombre}", ok=True, hechos=hechos, espera_max=max(esperas))
        return 0
    if modo == "equipo_unico":  # el modo de equipo único comparte el turno
        from atlas_core.exclusividad_equipo import EscritorEquipoUnico
        escritor = EscritorEquipoUnico(raiz, verificar=lambda: None)
        ok = escritor.adquirir()
        senal(control, "equipo_unico", ok=ok)
        if ok:
            esperar_orden(control, "soltar")
            escritor.cerrar()
            senal(control, "soltado")
        return 0
    raise SystemExit(f"modo desconocido {modo}")


if __name__ == "__main__":
    raise SystemExit(main())
