"""Continuidad CASA / OFICINA con la custodia REAL (estado_confirmado.CustodiaEstado, protocolo 2).

Dos raíces locales sintéticas (las copias Drive de CASA y OFICINA), dos carpetas
locales de custodia y un cliente Cloud en memoria con la semántica del Worker
(versión, historial (ruta, sha), objetos por SHA y confirmación con versión base).
Los equipos nunca están encendidos a la vez: los turnos son secuenciales.
No toca G:, Cloud, CASA ni OFICINA. Ver docs/CONTINUIDAD_CASA_OFICINA.md.
"""
from __future__ import annotations

import contextlib
import hashlib
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from atlas_core.estado_confirmado import CustodiaEstado, EstadoNoVerificado

DATASET = "operacion/actual/analisis_completo_guias.csv"
LEDGER = "operacion/actual/decisiones_aplicadas.json"
EVIDENCIA = "operacion/entradas/lote-2/Guia 900002.jpg"
CABECERA = "archivo;numero_guia\n"


class NubeMemoria:
    """Semántica del Worker 61c2872 para la custodia: marca, historial y objetos por empresa."""

    def __init__(self):
        self.version = 0
        self.archivos: dict[str, str | None] = {}
        self.historial: set[tuple[str, str]] = set()
        self.objetos: dict[str, bytes] = {}
        self.confirmaciones = 0
        self.fallar_en: int | None = None      # n-ésima llamada a confirmar que falla (corte)
        self.disponible = True

    def _exigir(self):
        if not self.disponible:
            raise OSError("Cloud no disponible")

    def manifiesto(self):
        self._exigir()
        return {"version": self.version, "archivos": [[r, h, 1] for r, h in self.archivos.items()]}

    def conocidos(self, consultas):
        self._exigir()
        return [(r, h) in self.historial for r, h in consultas]

    def faltantes(self, huellas):
        self._exigir()
        return [h for h in huellas if h not in self.objetos]

    def subir(self, sha, datos, lease_token):
        self._exigir()
        assert hashlib.sha256(datos).hexdigest() == sha
        self.objetos[sha] = bytes(datos)

    def descargar(self, sha):
        self._exigir()
        return self.objetos[sha]

    def confirmar(self, lease_token, version_base, archivos):
        self._exigir()
        self.confirmaciones += 1
        if self.fallar_en is not None and self.confirmaciones == self.fallar_en:
            raise OSError("corte durante la confirmación")
        assert version_base == self.version
        for ruta, sha in archivos:
            self.archivos[ruta] = sha
            if sha:
                self.historial.add((ruta, sha))
        self.version += 1
        return self.version


class Equipo:
    def __init__(self, nombre: str, base: Path):
        self.nombre = nombre
        self.raiz = base / nombre / "Atlas"
        self.raiz.mkdir(parents=True)
        self.local = base / nombre / "custodia_local"

    @contextlib.contextmanager
    def turno(self, nube: NubeMemoria, *, confirmar=True):
        """Turno de escritor: alinear (al adquirir), escribir, confirmar (al cerrar), como LeaseEscritorOperativo."""
        custodia = CustodiaEstado(self.raiz, nube, carpeta_local=self.local)
        lease = SimpleNamespace(escritor_id=self.nombre, lease_token=f"lease-{self.nombre}", marca={"version": nube.version})
        custodia.resumen_alineacion = custodia.alinear(lease)
        custodia.iniciar(lease)
        try:
            yield custodia
            if confirmar:
                try:
                    custodia.confirmar(lease)       # LeaseEscritorOperativo._cerrar_custodia: el fallo sólo se registra
                except OSError as error:
                    custodia.error_confirmacion = error
        finally:
            custodia.detener()

    def escribir(self, rel: str, texto: str | bytes):
        ruta = self.raiz / rel
        ruta.parent.mkdir(parents=True, exist_ok=True)
        (ruta.write_bytes if isinstance(texto, bytes) else lambda t: ruta.write_text(t, encoding="utf-8"))(texto)

    def leer(self, rel: str) -> bytes | None:
        ruta = self.raiz / rel
        return ruta.read_bytes() if ruta.is_file() else None

    def cuarentena(self) -> list[Path]:
        return sorted(p for p in (self.local / "cuarentena").rglob("*") if p.is_file()) if (self.local / "cuarentena").exists() else []


def drive(origen: Equipo, destino: Equipo, *, solo=None):
    """Réplica Drive (posiblemente parcial) de origen a destino."""
    for ruta in origen.raiz.rglob("*"):
        rel = ruta.relative_to(origen.raiz).as_posix()
        if ruta.is_file() and (solo is None or rel in solo):
            copia = destino.raiz / rel
            copia.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ruta, copia)


@pytest.fixture
def mundo(tmp_path):
    nube = NubeMemoria()
    casa, oficina = Equipo("CASA", tmp_path), Equipo("OFICINA", tmp_path)
    with casa.turno(nube):
        casa.escribir(DATASET, CABECERA + "Guia 900001.jpg;900001\n")
        casa.escribir(LEDGER, '{"aplicaciones": []}')
    assert nube.version == 1
    drive(casa, oficina)
    return SimpleNamespace(nube=nube, casa=casa, oficina=oficina)


# 1, 2, 6, 9 ----------------------------------------------------------------
def test_apagado_normal_y_drive_atrasado_continua_desde_cloud(mundo):
    with mundo.casa.turno(mundo.nube):
        mundo.casa.escribir(DATASET, CABECERA + "Guia 900001.jpg;900001\nGuia 900002.jpg;900002\n")
        mundo.casa.escribir(LEDGER, '{"aplicaciones": [{"token": "t1", "actor": "HUMANO"}]}')
        mundo.casa.escribir(EVIDENCIA, b"foto-900002")       # ingreso Desktop: escritura gobernada
    # CASA se apaga; Drive no alcanzó a subir nada.
    with mundo.oficina.turno(mundo.nube) as c:
        assert sorted(c.resumen_alineacion["restaurados"]) == sorted([DATASET, LEDGER, EVIDENCIA])
    for rel in (DATASET, LEDGER, EVIDENCIA):
        assert mundo.oficina.leer(rel) == mundo.casa.leer(rel)


# 3, 4, 5: confirmación que no llegó a Cloud antes de apagar --------------------
def test_trabajo_no_confirmado_se_revierte_en_el_otro_equipo(mundo):
    mundo.nube.fallar_en = mundo.nube.confirmaciones + 1     # corte justo al cerrar el turno
    with mundo.casa.turno(mundo.nube) as c:
        mundo.casa.escribir(LEDGER, '{"aplicaciones": [{"token": "t1", "actor": "HUMANO"}]}')
    assert isinstance(c.error_confirmacion, OSError) and mundo.nube.version == 1
    drive(mundo.casa, mundo.oficina)                          # Drive sí subió el archivo
    with mundo.oficina.turno(mundo.nube) as o:
        resumen = o.resumen_alineacion
    # Sin error ni aviso: la decisión de CASA queda sólo en la cuarentena local de OFICINA.
    assert resumen["cuarentena"] == [LEDGER] and resumen["restaurados"] == [LEDGER]
    assert mundo.oficina.leer(LEDGER) == b'{"aplicaciones": []}'
    assert any(p.read_bytes().startswith(b'{"aplicaciones": [{"token": "t1"') for p in mundo.oficina.cuarentena())


def test_trabajo_no_confirmado_con_documentos_nuevos_bloquea_al_otro_equipo(mundo):
    mundo.nube.fallar_en = mundo.nube.confirmaciones + 1
    with mundo.casa.turno(mundo.nube):
        mundo.casa.escribir(DATASET, CABECERA + "Guia 900001.jpg;900001\nGuia 900002.jpg;900002\n")
    drive(mundo.casa, mundo.oficina)
    with pytest.raises(EstadoNoVerificado, match="eliminaria documentos locales"):
        with mundo.oficina.turno(mundo.nube):
            pass
    assert mundo.nube.version == 1        # OFICINA no escribe hasta que alguien recupere


def test_reinicio_en_el_mismo_equipo_confirma_el_diario(mundo):
    mundo.nube.fallar_en = mundo.nube.confirmaciones + 1
    with mundo.casa.turno(mundo.nube):
        mundo.casa.escribir(LEDGER, '{"aplicaciones": [{"token": "t1", "actor": "HUMANO"}]}')
    with mundo.casa.turno(mundo.nube) as c:                   # CASA vuelve a encenderse
        assert c.resumen_alineacion["pendiente_confirmado"] == 1
    assert mundo.nube.archivos[LEDGER] == hashlib.sha256(mundo.casa.leer(LEDGER)).hexdigest()


def test_diario_del_equipo_apagado_se_descarta_si_el_otro_confirmo_despues(mundo):
    mundo.nube.fallar_en = mundo.nube.confirmaciones + 1
    with mundo.casa.turno(mundo.nube):
        mundo.casa.escribir(LEDGER, '{"aplicaciones": [{"token": "t1", "actor": "HUMANO"}]}')
    with mundo.oficina.turno(mundo.nube):                     # OFICINA trabaja (Drive no trajo nada)
        mundo.oficina.escribir("operacion/actual/agrupaciones_viaje.json", '{"agrupaciones": []}')
    with mundo.casa.turno(mundo.nube) as c:                   # CASA vuelve después
        assert c.resumen_alineacion["pendiente_confirmado"] == 0
        assert LEDGER in c.resumen_alineacion["cuarentena"]
    assert mundo.casa.leer(LEDGER) == b'{"aplicaciones": []}'   # la decisión de CASA quedó fuera


# 5: confirmación por lotes interrumpida ----------------------------------------
def test_confirmacion_por_lotes_interrumpida_queda_como_mezcla_aceptada(mundo):
    rutas = [f"operacion/actual/parte_{n:03d}.json" for n in range(51)]
    with mundo.casa.turno(mundo.nube):                        # estado previo confirmado: versión "a"
        for rel in rutas:
            mundo.casa.escribir(rel, '{"version": "a"}')
    drive(mundo.casa, mundo.oficina)
    base = mundo.nube.version
    mundo.nube.fallar_en = mundo.nube.confirmaciones + 2     # cae el segundo lote (LOTE_CONFIRMACION = 50)
    with mundo.casa.turno(mundo.nube) as c:                   # una operación lógica cambia los 51 a "b"
        for rel in rutas:
            mundo.casa.escribir(rel, '{"version": "b"}')
    assert isinstance(c.error_confirmacion, OSError) and mundo.nube.version == base + 1
    drive(mundo.casa, mundo.oficina)                          # Drive trajo los 51 en "b"
    with mundo.oficina.turno(mundo.nube) as o:                # OFICINA alinea sin error...
        assert o.resumen_alineacion["cuarentena"] == [rutas[-1]]
    versiones = [mundo.oficina.leer(r) for r in rutas]
    # ...y queda una mezcla aceptada como estado confirmado: 50 en "b" y 1 revertido a "a".
    assert versiones.count(b'{"version": "b"}') == 50 and versiones[-1] == b'{"version": "a"}'
    with mundo.casa.turno(mundo.nube) as c2:                  # CASA, al volver, también descarta su diario:
        assert c2.resumen_alineacion["pendiente_confirmado"] == 0   # la versión base quedó superada por su propio lote
    assert mundo.casa.leer(rutas[-1]) == b'{"version": "a"}'


# 8: archivo faltante o corrupto ------------------------------------------------
def test_archivo_local_corrupto_o_faltante_se_restaura(mundo):
    mundo.oficina.escribir(LEDGER, b"\x00\x00corrupto")
    (mundo.oficina.raiz / DATASET).unlink()
    with mundo.oficina.turno(mundo.nube) as o:
        assert sorted(o.resumen_alineacion["restaurados"]) == sorted([DATASET, LEDGER])
    assert mundo.oficina.leer(LEDGER) == mundo.casa.leer(LEDGER)


def test_objeto_cloud_corrupto_bloquea(mundo):
    sha = mundo.nube.archivos[LEDGER]
    mundo.nube.objetos[sha] = b"otro contenido"
    mundo.oficina.escribir(LEDGER, b"distinto")
    with pytest.raises(EstadoNoVerificado, match="no coincide con su huella"):
        with mundo.oficina.turno(mundo.nube):
            pass


# 7: Cloud inaccesible ------------------------------------------------------------
def test_cloud_inaccesible_no_permite_escribir(mundo):
    mundo.nube.disponible = False
    with pytest.raises(OSError):
        with mundo.oficina.turno(mundo.nube):
            mundo.oficina.escribir(LEDGER, "no debe ocurrir")
    assert mundo.oficina.leer(LEDGER) == mundo.casa.leer(LEDGER)
