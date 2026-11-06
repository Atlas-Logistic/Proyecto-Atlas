"""Cierre P0 del diario incremental y la publicación rotativa.

1. Migración en dos fases: la lectura de reportes (horas en Drive) ocurre
   SIN escritor; el escritor se toma sólo para una escritura atómica. PULL
   no se detiene durante la lectura.
2. Recuperación desde la custodia Cloud en un equipo AISLADO, sin carpeta
   ``reportes/``: el consumidor operacional obtiene las mismas relaciones.
3. Consolidación: los segmentos borrados se propagan como borrado (``None``).
4. Rotación: reduce las carpetas permanentes sin perder evidencia, ni
   siquiera si el turno que capturó cae y otro equipo releva.
5. Reversión: ``--desactivar`` y modo ``snapshots``.
"""
from __future__ import annotations

import json
import shutil

import pytest

import atlas_core.registro_relaciones_operacionales as registro
from atlas_core import estado_confirmado as ec
from atlas_core import publicacion_reportes as pub
from atlas_core import revalidacion_documental as rd
from atlas_core.almacenamiento_portable import escribir_estado_operacion
from tests.test_registro_relaciones_diario_p0 import _Lease, _Nube, _dataset, _normal, _rel, _reloj, _reporte


@pytest.fixture(autouse=True)
def _aislado(tmp_path, monkeypatch):
    monkeypatch.setenv("ATLAS_CACHE_DIR", str(tmp_path / "cache-local"))
    pub._CAPTURADAS_EN_PROCESO.clear()
    yield
    pub._CAPTURADAS_EN_PROCESO.clear()


def _arbol(raiz):
    return {p.relative_to(raiz).as_posix(): p.read_bytes() for p in raiz.rglob("*") if p.is_file()}


def _historicos(raiz, cantidad=6):
    for i in range(cantidad):
        _reporte(raiz, f"reporte_mobile_2026110{i}", [_rel(f"H{i}-{j}", rut=f"{i}{j}-1") for j in range(3)])
    # Discrepancia documental: misma guía/transporte/RUT con otra patente.
    _reporte(raiz, "reporte_mobile_20261109", [_rel("H0-0", rut="00-1", patente="ZZ9999")])


def _claves(relaciones):
    return {registro._clave(r) for r in relaciones}


class _Contador:
    def __init__(self, monkeypatch, falla_en=None):
        self.lecturas, self.falla_en = 0, falla_en
        original = registro._leer_reporte

        def leer(ruta):
            self.lecturas += 1
            if self.falla_en is not None and self.lecturas == self.falla_en:
                raise KeyboardInterrupt("corte simulado")
            return original(ruta)

        monkeypatch.setattr(registro, "_leer_reporte", leer)


# --- 1. Migración en dos fases ------------------------------------------------------

def test_preparar_no_escribe_la_raiz_y_es_reanudable_tras_un_corte(tmp_path, monkeypatch):
    raiz = tmp_path / "Atlas"
    _historicos(raiz)
    antes = _arbol(raiz)
    contador = _Contador(monkeypatch, falla_en=4)
    with pytest.raises(KeyboardInterrupt):
        registro.preparar_migracion(raiz, lote=2)
    assert _arbol(raiz) == antes  # ni registro ni nada bajo la raíz Atlas
    contador.falla_en, contador.lecturas = None, 0
    preparado = registro.preparar_migracion(raiz, lote=2)
    assert contador.lecturas == 7 - 2  # los 2 del lote confirmado no se releen
    assert preparado["ilegibles"] == [] and _arbol(raiz) == antes
    assert registro.ruta_plan_migracion(raiz).is_file()
    assert not str(registro.ruta_plan_migracion(raiz)).startswith(str(raiz))


def test_dos_fases_equivale_a_la_migracion_directa(tmp_path):
    directa, dos_fases = tmp_path / "directa" / "Atlas", tmp_path / "dos" / "Atlas"
    _historicos(directa)
    shutil.copytree(directa, dos_fases)
    registro.migrar_reportes_historicos(directa, aplicar=True)
    registro.preparar_migracion(dos_fases)
    aplicado = registro.aplicar_migracion_preparada(dos_fases)
    assert aplicado["estado"] == registro.ESTADO_COMPLETA
    assert _normal(registro.contenido_vigente(dos_fases)) == _normal(registro.contenido_vigente(directa))
    assert not registro.ruta_plan_migracion(dos_fases).exists()
    # Repetir: nada nuevo que leer ni escribir.
    base = registro.ruta_registro(dos_fases).read_bytes()
    assert registro.preparar_migracion(dos_fases)["leidos"] == 0
    registro.aplicar_migracion_preparada(dos_fases)
    assert registro.ruta_registro(dos_fases).read_bytes() == base


def test_escrituras_entre_fases_se_conservan(tmp_path, monkeypatch):
    """Un turno de PULL durante la lectura (captura rotativa en el diario) no
    se pierde: la fase 2 une sobre el registro vigente de ese momento."""
    raiz = tmp_path / "Atlas"
    _historicos(raiz)
    registro.preparar_migracion(raiz)
    _reloj(monkeypatch, "2026-11-06")
    registro.incorporar_relaciones(raiz, [_rel("PULL-1", rut="99-9")], procedencia={"tipo": registro.TIPO_PUBLICADO})
    registro.aplicar_migracion_preparada(raiz)
    claves = _claves(registro.leer_relaciones(raiz))
    assert registro._clave(_rel("PULL-1", rut="99-9")) in claves and len(claves) == 6 * 3 + 1 + 1


def test_aplicar_sin_plan_completo_no_escribe(tmp_path):
    raiz = tmp_path / "Atlas"
    _historicos(raiz)
    with pytest.raises(registro.MigracionNoPreparada):
        registro.aplicar_migracion_preparada(raiz)
    assert not registro.ruta_registro(raiz).exists()


def test_marcar_verificada_rechequea_el_registro_alineado(tmp_path):
    """Si entre la lectura y la marca la custodia restauró un registro al que
    le falta una relación leída, no se marca verificada."""
    raiz = tmp_path / "Atlas"
    _historicos(raiz)
    registro.migrar_reportes_historicos(raiz, aplicar=True)
    lectura, exigidas = registro.leer_verificacion(raiz)
    assert lectura["ok"]
    contenido = json.loads(registro.ruta_registro(raiz).read_text(encoding="utf-8"))
    contenido["empresas"]["oficina"]["relaciones"].pop()
    registro.ruta_registro(raiz).write_text(json.dumps(contenido), encoding="utf-8")
    antes = registro.ruta_registro(raiz).read_bytes()
    marcado = registro.marcar_verificada(raiz, lectura, exigidas)
    assert marcado["ok"] is False and marcado["estado"] == registro.ESTADO_COMPLETA
    assert registro.ruta_registro(raiz).read_bytes() == antes


class _Escritor:
    def __init__(self, libre=True):
        self.libre, self.vigente, self.adquisiciones = libre, False, 0

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        self.vigente = False

    def adquirir(self):
        self.adquisiciones += 1
        self.vigente = self.libre
        return self.libre


def test_cli_escritor_ocupado_conserva_la_lectura_y_reintenta_sin_releer(tmp_path, monkeypatch, capsys):
    import migrar_relaciones_operacionales as cli
    raiz = tmp_path / "Atlas"
    _historicos(raiz)
    contador = _Contador(monkeypatch)
    assert cli.main(["--raiz", str(raiz), "--aplicar"], fabrica_escritor=lambda _r: _Escritor(libre=False)) == 2
    assert contador.lecturas == 7 and not registro.ruta_registro(raiz).exists()
    contador.lecturas = 0
    escritor = _Escritor()
    capsys.readouterr()
    assert cli.main(["--raiz", str(raiz), "--aplicar"], fabrica_escritor=lambda _r: escritor) == 0
    assert contador.lecturas == 0  # reanuda desde el plan local
    assert json.loads(capsys.readouterr().out)["estado"] == registro.ESTADO_COMPLETA
    # Verificación sin nada que marcar (ya verificada) no toma el escritor.
    assert cli.main(["--raiz", str(raiz), "--verificar"], fabrica_escritor=lambda _r: escritor) == 0
    assert escritor.adquisiciones == 2
    assert cli.main(["--raiz", str(raiz), "--verificar"], fabrica_escritor=lambda _r: escritor) == 0
    assert escritor.adquisiciones == 2


# --- 2-3. Custodia Cloud: recuperación aislada y consolidación ---------------------------

class _Equipo:
    """Una raíz con su custodia contra la misma nube (CASA, OFICINA, aislado)."""

    def __init__(self, raiz, nube, local):
        self.raiz, self.nube = raiz, nube
        self.custodia = ec.CustodiaEstado(raiz, nube, carpeta_local=local)

    def alinear(self):
        return self.custodia.alinear(_Lease(self.nube))

    def turno(self, operacion, *, confirmar=True):
        lease = _Lease(self.nube)
        self.custodia.alinear(lease)
        self.custodia.iniciar(lease)
        try:
            resultado = operacion()
            if confirmar:
                self.custodia.confirmar(lease)
            return resultado
        finally:
            self.custodia.detener()


def _casa_migrada(tmp_path, monkeypatch, nube):
    raiz = tmp_path / "casa" / "Atlas"
    _historicos(raiz)
    _dataset(raiz, [_rel("H1-1", rut="11-1"), _rel("DS-0", rut="70-1")])  # H1-1 ya histórica
    casa = _Equipo(raiz, nube, tmp_path / "custodia-casa")
    casa.turno(lambda: casa.custodia._confirmar_rutas(_Lease(nube), casa.custodia.rutas_semilla()), confirmar=False)
    registro.preparar_migracion(raiz)  # sin turno: PULL sigue
    casa.turno(lambda: registro.aplicar_migracion_preparada(raiz))
    lectura, exigidas = registro.leer_verificacion(raiz)
    casa.turno(lambda: registro.marcar_verificada(raiz, lectura, exigidas))
    casa.turno(lambda: registro.activar_registro(raiz))
    for dia, guias in (("2026-11-06", ("N1", "N2")), ("2026-11-07", ("N3",))):
        _reloj(monkeypatch, dia)
        for guia in guias:
            casa.turno(lambda g=guia: registro.incorporar_dataset(raiz, _dataset(raiz, [_rel(g, rut=f"{g}-K")])))
    return casa


def test_equipo_aislado_sin_reportes_recupera_las_relaciones_desde_cloud(tmp_path, monkeypatch):
    nube = _Nube()
    casa = _casa_migrada(tmp_path, monkeypatch, nube)
    esperado = _claves(rd._relaciones_historicas_operacionales(casa.raiz))
    historicas = _claves(rd._leer_relaciones_historicas_reportadas(casa.raiz))
    assert historicas <= esperado and len(esperado) == len(historicas) + 4 - 1  # + DS-0, N1, N2, N3 - H1-1 (ya histórica)

    aislado = _Equipo(tmp_path / "aislado" / "Atlas", nube, tmp_path / "custodia-aislado")
    restaurados = aislado.alinear()["restaurados"]
    assert "catalogos_privados/registro_relaciones_operacionales.json" in restaurados
    assert {r for r in restaurados if "registro_relaciones_diario/" in r} == {
        "catalogos_privados/registro_relaciones_diario/20261106.json",
        "catalogos_privados/registro_relaciones_diario/20261107.json",
    }
    assert not (aislado.raiz / "reportes").exists()  # sin carpetas históricas
    assert registro.estado_registro(aislado.raiz)["activo"] is True
    assert _claves(rd._relaciones_historicas_operacionales(aislado.raiz)) == esperado
    assert _normal(registro.contenido_vigente(aislado.raiz)) == _normal(registro.contenido_vigente(casa.raiz))


def test_consolidacion_propaga_borrados_y_no_cambia_las_relaciones(tmp_path, monkeypatch):
    nube = _Nube()
    casa = _casa_migrada(tmp_path, monkeypatch, nube)
    oficina = _Equipo(tmp_path / "oficina" / "Atlas", nube, tmp_path / "custodia-oficina")
    oficina.alinear()  # copia con los segmentos previos a consolidar
    esperado = _normal(registro.contenido_vigente(casa.raiz))
    resultado = casa.turno(lambda: registro.consolidar_diario(casa.raiz, hasta="99999999"))
    assert resultado["consolidados"] == ["20261106.json", "20261107.json"]
    segmentos = {r: s for r, s in nube.archivos.items() if "registro_relaciones_diario/" in r}
    assert segmentos and all(s is None for s in segmentos.values())  # borrado confirmado
    borrados = oficina.alinear()["borrados"]
    assert sorted(borrados) == sorted(segmentos)
    assert not list(registro.ruta_diario(oficina.raiz).glob("*.json"))
    assert _normal(registro.contenido_vigente(oficina.raiz)) == esperado == _normal(registro.contenido_vigente(casa.raiz))


def test_desactivar_vuelve_a_historicos_donde_existen(tmp_path, monkeypatch):
    nube = _Nube()
    casa = _casa_migrada(tmp_path, monkeypatch, nube)
    historicas = rd._leer_relaciones_historicas_reportadas(casa.raiz)
    casa.turno(lambda: registro.desactivar_registro(casa.raiz))
    assert registro.relaciones_si_activo(casa.raiz) is None
    assert _claves(rd._relaciones_historicas_operacionales(casa.raiz)) == _claves(historicas)
    assert (casa.raiz / "reportes").is_dir() and len(list((casa.raiz / "reportes").iterdir())) == 7
    casa.turno(lambda: registro.activar_registro(casa.raiz))
    assert registro.relaciones_si_activo(casa.raiz) is not None


# --- 4. Rotación ---------------------------------------------------------------------

def _publicar(raiz, nombre, relaciones):
    carpeta = pub.ruta_reporte_automatico(raiz, nombre)
    temporal = raiz / "_tmp_publicar"
    _reporte(temporal, nombre, relaciones)
    carpeta.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(temporal / "reportes" / nombre), str(carpeta))
    shutil.rmtree(temporal)
    escribir_estado_operacion(reporte_vigente=carpeta, raiz=raiz)
    return carpeta


def test_rotacion_reduce_carpetas_sin_perder_evidencia_ni_otros_archivos(tmp_path, monkeypatch):
    nube = _Nube()
    casa = _casa_migrada(tmp_path, monkeypatch, nube)
    raiz = casa.raiz
    (raiz / "operacion" / "mobile" / "envios" / "e1").mkdir(parents=True)
    (raiz / "operacion" / "mobile" / "envios" / "e1" / "original.jpg").write_bytes(b"foto")
    (raiz / "operacion" / "actual" / "acciones_operacionales.json").write_text('{"auditoria": [1]}', encoding="utf-8")
    casa.turno(lambda: pub.configurar(raiz, modo=pub.MODO_ROTATIVO, conservar=2))
    historicos = {p: p.read_bytes() for p in (raiz / "reportes").glob("reporte_*/*")}
    publicadas = []
    for ciclo in range(8):  # 8 ciclos de PULL = 8 procesos
        pub._CAPTURADAS_EN_PROCESO.clear()
        relaciones = [_rel(f"P{ciclo}", rut=f"{ciclo}-P")]
        publicadas += relaciones
        protegidos = {k: v for k, v in _arbol(raiz).items() if not k.startswith("reportes/")
                      and not k.startswith("catalogos_privados/registro_relaciones")
                      and k != "operacion/actual/estado_operacion.json"}
        casa.turno(lambda c=ciclo, r=relaciones: _publicar(raiz, f"reporte_mobile_r{c}", r))
        despues = {k: v for k, v in _arbol(raiz).items() if k in protegidos}
        assert despues == protegidos  # originales, auditoría y confirmaciones intactos
    vivos = sorted(p.name for p in pub.raiz_vigentes(raiz).iterdir() if p.is_dir())
    assert len(vivos) <= 3  # conservar=2 + la del último proceso aún sin confirmar
    assert {p: p.read_bytes() for p in historicos} == historicos
    assert len([p for p in (raiz / "reportes").iterdir() if p.name != "vigentes"]) == 7  # ninguna permanente nueva
    aislado = _Equipo(tmp_path / "aislado" / "Atlas", nube, tmp_path / "custodia-aislado")
    aislado.alinear()
    assert _claves(publicadas) <= _claves(rd._relaciones_historicas_operacionales(aislado.raiz))


def test_turno_caido_y_relevo_no_pierden_la_evidencia_de_una_publicacion_podable(tmp_path, monkeypatch):
    """CASA publica y captura, pero su turno cae antes de confirmar; OFICINA
    releva (la alineación restaura el segmento confirmado, sin esa captura).
    La publicación no se poda: se recaptura en el turno vigente."""
    nube = _Nube()
    casa = _casa_migrada(tmp_path, monkeypatch, nube)
    raiz = casa.raiz
    casa.turno(lambda: pub.configurar(raiz, modo=pub.MODO_ROTATIVO, conservar=2))
    perdida = _rel("CAIDA", rut="77-7")
    casa.turno(lambda: _publicar(raiz, "reporte_mobile_caido", [perdida]), confirmar=False)  # cae sin confirmar
    assert registro._clave(perdida) in _claves(registro.leer_relaciones(raiz))
    # Relevo: OFICINA (misma raíz vía Drive) alinea con Cloud -> cuarentena + restauración.
    oficina = _Equipo(raiz, nube, tmp_path / "custodia-oficina")
    oficina.custodia._ruta_pendiente.unlink(missing_ok=True)
    resumen = oficina.alinear()
    assert resumen["cuarentena"] and registro._clave(perdida) not in _claves(registro.leer_relaciones(raiz))
    for ciclo in range(3):  # procesos posteriores de OFICINA
        pub._CAPTURADAS_EN_PROCESO.clear()
        oficina.turno(lambda c=ciclo: _publicar(raiz, f"reporte_mobile_of{c}", [_rel(f"OF{c}", rut=f"{c}-O")]))
    assert registro._clave(perdida) in _claves(registro.relaciones_si_activo(raiz))  # recapturada y confirmada
    aislado = _Equipo(tmp_path / "aislado" / "Atlas", nube, tmp_path / "custodia-aislado")
    aislado.alinear()
    assert registro._clave(perdida) in _claves(rd._relaciones_historicas_operacionales(aislado.raiz))


def test_volver_a_snapshots_es_inmediato_y_conserva_lo_rotativo(tmp_path, monkeypatch):
    nube = _Nube()
    casa = _casa_migrada(tmp_path, monkeypatch, nube)
    raiz = casa.raiz
    casa.turno(lambda: pub.configurar(raiz, modo=pub.MODO_ROTATIVO, conservar=2))
    casa.turno(lambda: _publicar(raiz, "reporte_mobile_rot", [_rel("R1", rut="1-R")]))
    casa.turno(lambda: pub.configurar(raiz, modo=pub.MODO_SNAPSHOTS))
    salida = casa.turno(lambda: _publicar(raiz, "reporte_mobile_snap", [_rel("S1", rut="1-S")]))
    assert salida.parent == raiz / "reportes"
    assert (pub.raiz_vigentes(raiz) / "reporte_mobile_rot" / "viajes.csv").is_file()
