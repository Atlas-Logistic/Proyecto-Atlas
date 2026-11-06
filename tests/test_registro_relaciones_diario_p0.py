"""Diario incremental del registro de relaciones: el ciclo normal no reescribe
el registro completo; agrega la unión nueva al segmento del día.

Cubre idempotencia, reinicio (cortes durante la escritura y la
consolidación), recuperación entre equipos (Drive atrasado, copias en
conflicto, segmento ilegible), equivalencia con la escritura directa vigente
y lo que la custodia Cloud real sube en cada turno.
"""
from __future__ import annotations

import copy
import csv
import hashlib
import json
import os
import random
import shutil

import pytest

import atlas_core.registro_relaciones_operacionales as registro
from atlas_core import estado_confirmado as ec


def _rel(guia, patente="AA1111", rut="11111111-1", transporte="T1"):
    return {"numero_guia": str(guia), "numero_transporte": transporte, "rut_chofer": rut,
            "patente_tracto": patente, "patente_rampla": ""}


def _reporte(raiz, nombre, evidencias):
    carpeta = raiz / "reportes" / nombre
    carpeta.mkdir(parents=True)
    with (carpeta / "viajes.csv").open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["numero_transporte", "evidencias_documentos"], delimiter=";")
        w.writeheader()
        w.writerow({"numero_transporte": "1", "evidencias_documentos": json.dumps(evidencias)})


def _dataset(raiz, relaciones):
    ruta = raiz / "operacion" / "actual" / "analisis_completo_guias.csv"
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with ruta.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(registro.CAMPOS), delimiter=";")
        w.writeheader()
        w.writerows(relaciones)
    return ruta


def _migrada(raiz, cantidad=3):
    """Raíz con la migración completa: el ciclo normal ya incorpora el dataset."""
    for i in range(cantidad):
        _reporte(raiz, f"r{i}", [_rel(f"H{i}")])
    assert registro.migrar_reportes_historicos(raiz, aplicar=True)["estado"] == registro.ESTADO_COMPLETA


def _almacen(raiz):
    """Bytes de todo lo que compone el registro vigente (base + diario)."""
    archivos = [registro.ruta_registro(raiz), *sorted(registro.ruta_diario(raiz).glob("*"))]
    return {a.name: a.read_bytes() for a in archivos if a.is_file()}


def _normal(contenido):
    """Forma comparable: sin orden de listas ni marcas de tiempo."""
    salida = {}
    for empresa_id, empresa in contenido["empresas"].items():
        relaciones = {}
        for e in empresa["relaciones"]:
            relaciones[e["clave"]] = {
                "relacion": e["relacion"],
                "fuentes": sorted(registro._identidad_fuente(f) for f in e["fuentes"]),
                "conflictos": sorted(json.dumps(c, sort_keys=True) for c in e["conflictos"]),
                "confirmaciones": sorted(json.dumps(c, sort_keys=True) for c in e["confirmaciones_humanas"]),
            }
        salida[empresa_id] = {"relaciones": relaciones, "migracion": {
            k: v for k, v in (empresa.get("migracion") or {}).items() if not k.endswith("_en")
        }}
    return salida


def _reloj(monkeypatch, dia):
    monkeypatch.setattr(registro, "_ahora", lambda: f"{dia}T12:00:00+00:00")


# --- Ciclo normal ----------------------------------------------------------------

def test_ciclo_normal_no_reescribe_el_base_y_solo_crece_el_segmento_del_dia(tmp_path, monkeypatch):
    raiz = tmp_path / "Atlas"
    _migrada(raiz)
    base = registro.ruta_registro(raiz).read_bytes()
    _reloj(monkeypatch, "2026-11-06")
    resumen = registro.incorporar_dataset(raiz, _dataset(raiz, [_rel("N1"), _rel("H0")]))
    assert resumen == {"relaciones_agregadas": 1, "fuentes_agregadas": 2, "total": 4}
    assert registro.ruta_registro(raiz).read_bytes() == base  # el base no se reescribe
    assert [p.name for p in registro.ruta_diario(raiz).iterdir()] == ["20261106.json"]
    segmento = json.loads((registro.ruta_diario(raiz) / "20261106.json").read_text(encoding="utf-8"))
    # Sólo la unión nueva: H0 ya existía como migrada, pero el dataset es una fuente nueva.
    assert {r["numero_guia"] for r in segmento["entradas"][0]["relaciones"]} == {"N1", "H0"}
    assert {r["numero_guia"] for r in registro.leer_relaciones(raiz)} == {"H0", "H1", "H2", "N1"}
    # Al día siguiente, otro segmento; el anterior queda intacto.
    anterior = (registro.ruta_diario(raiz) / "20261106.json").read_bytes()
    _reloj(monkeypatch, "2026-11-07")
    registro.incorporar_dataset(raiz, _dataset(raiz, [_rel("N1"), _rel("N2")]))
    assert (registro.ruta_diario(raiz) / "20261106.json").read_bytes() == anterior
    assert sorted(p.name for p in registro.ruta_diario(raiz).iterdir()) == ["20261106.json", "20261107.json"]


def test_consumidor_activo_lee_el_diario_sin_abrir_reportes(tmp_path, monkeypatch):
    from atlas_core import revalidacion_documental as rd
    raiz = tmp_path / "Atlas"
    _migrada(raiz)
    assert registro.verificar_migracion(raiz)["ok"]
    registro.activar_registro(raiz)
    registro.incorporar_dataset(raiz, _dataset(raiz, [_rel("N1")]))
    monkeypatch.setattr(rd, "_leer_relaciones_historicas_reportadas",
                        lambda *_: (_ for _ in ()).throw(AssertionError("lee históricos")))
    monkeypatch.setattr(registro, "_leer_reporte", lambda *_: (_ for _ in ()).throw(AssertionError("abre reportes")))
    guias = {r["numero_guia"] for r in rd._relaciones_historicas_operacionales(raiz)}
    assert guias == {"H0", "H1", "H2", "N1"}


# --- Idempotencia ----------------------------------------------------------------

def test_repetir_no_escribe_y_reproducir_dos_veces_no_cambia_nada(tmp_path, monkeypatch):
    raiz = tmp_path / "Atlas"
    _migrada(raiz)
    dataset = _dataset(raiz, [_rel("N1"), _rel("N2", "BB2222")])
    registro.incorporar_dataset(raiz, dataset)
    antes = _almacen(raiz)
    vigente = _normal(registro.contenido_vigente(raiz))
    monkeypatch.setattr(registro, "escribir_json_atomico",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("escribe sin cambio")))
    for _ in range(3):
        assert registro.incorporar_dataset(raiz, dataset)["fuentes_agregadas"] == 0
    assert _almacen(raiz) == antes
    # Un segmento duplicado (copia de Drive) se reproduce sin efecto.
    (segmento,) = registro.ruta_diario(raiz).glob("*.json")
    shutil.copy2(segmento, segmento.with_name(segmento.stem + " (1).json"))
    assert _normal(registro.contenido_vigente(raiz)) == vigente


def test_equivalente_a_la_escritura_directa_vigente(tmp_path, monkeypatch):
    """Secuencia aleatoria de dataset, reportes publicados y empresas, con
    relaciones discrepantes: el diario sin consolidar, el diario consolidado
    al final y la escritura directa en el base (consolidar tras cada
    operación, como el registro monolítico anterior) dan el mismo registro."""
    azar = random.Random(20261106)
    operaciones = []
    for paso in range(60):
        empresa = azar.choice(["oficina", "oficina", "b"])
        tipo = azar.choice([registro.TIPO_DATASET, registro.TIPO_PUBLICADO, "otra"])
        relaciones = [_rel(azar.randint(1, 25), azar.choice(["AA1111", "BB2222", "CC3333"])) for _ in range(azar.randint(0, 5))]
        operaciones.append((f"2026-11-{1 + paso // 20:02d}", empresa, relaciones, {"tipo": tipo, "sha256": str(paso)}))

    def ejecutar(raiz, *, consolidar_cada_vez):
        for dia, empresa, relaciones, procedencia in operaciones:
            _reloj(monkeypatch, dia)
            registro.incorporar_relaciones(raiz, relaciones, empresa_id=empresa, procedencia=procedencia)
            if consolidar_cada_vez:
                registro.consolidar_diario(raiz, hasta="99999999")
        return registro.contenido_vigente(raiz)

    diario = ejecutar(tmp_path / "diario", consolidar_cada_vez=False)
    directo = ejecutar(tmp_path / "directo", consolidar_cada_vez=True)
    assert not list(registro.ruta_diario(tmp_path / "directo").glob("*"))
    assert _normal(diario) == _normal(directo)
    assert any(e["conflictos"] for e in diario["empresas"]["oficina"]["relaciones"])
    registro.consolidar_diario(tmp_path / "diario", hasta="99999999")
    assert _normal(registro.contenido_vigente(tmp_path / "diario")) == _normal(directo)


# --- Reinicio --------------------------------------------------------------------

def test_corte_al_escribir_el_segmento_no_pierde_lo_confirmado(tmp_path, monkeypatch):
    raiz = tmp_path / "Atlas"
    _migrada(raiz)
    registro.incorporar_dataset(raiz, _dataset(raiz, [_rel("N1")]))
    antes = _almacen(raiz)
    real = os.replace

    def corte(origen, destino, *a, **k):
        if str(destino).endswith(".json") and registro.CARPETA_DIARIO in str(destino):
            raise OSError("equipo apagado")
        return real(origen, destino, *a, **k)

    monkeypatch.setattr(os, "replace", corte)
    with pytest.raises(OSError):
        registro.incorporar_dataset(raiz, _dataset(raiz, [_rel("N1"), _rel("N2")]))
    monkeypatch.setattr(os, "replace", real)
    assert _almacen(raiz) == antes  # el segmento anterior queda íntegro, sin temporales visibles
    assert {r["numero_guia"] for r in registro.leer_relaciones(raiz)} == {"H0", "H1", "H2", "N1"}
    registro.incorporar_dataset(raiz, _dataset(raiz, [_rel("N1"), _rel("N2")]))  # reintento
    assert {r["numero_guia"] for r in registro.leer_relaciones(raiz)} == {"H0", "H1", "H2", "N1", "N2"}


def test_corte_entre_base_consolidado_y_borrado_se_reanuda_sin_duplicar(tmp_path, monkeypatch):
    raiz = tmp_path / "Atlas"
    _migrada(raiz)
    for dia, guia in (("2026-11-04", "N1"), ("2026-11-05", "N2")):
        _reloj(monkeypatch, dia)
        registro.incorporar_dataset(raiz, _dataset(raiz, [_rel(guia)]))
    vigente = _normal(registro.contenido_vigente(raiz))
    real = type(registro.ruta_registro(raiz)).unlink

    def corte(self, *a, **k):
        if registro.CARPETA_DIARIO in str(self):
            raise OSError("equipo apagado")
        return real(self, *a, **k)

    monkeypatch.setattr(type(registro.ruta_registro(raiz)), "unlink", corte)
    with pytest.raises(OSError):
        registro.consolidar_diario(raiz, hasta="20261106")
    monkeypatch.setattr(type(registro.ruta_registro(raiz)), "unlink", real)
    # Base ya consolidado + segmentos aún presentes: mismo registro, sin duplicados.
    assert len(list(registro.ruta_diario(raiz).glob("*.json"))) == 2
    assert _normal(registro.contenido_vigente(raiz)) == vigente
    reanudada = registro.consolidar_diario(raiz, hasta="20261106")
    assert reanudada["consolidados"] == ["20261104.json", "20261105.json"]
    assert _normal(registro.contenido_vigente(raiz)) == vigente
    assert not list(registro.ruta_diario(raiz).glob("*.json"))


def test_consolidacion_respeta_el_segmento_en_uso_y_las_confirmaciones(tmp_path, monkeypatch):
    raiz = tmp_path / "Atlas"
    _migrada(raiz)
    base = registro.ruta_registro(raiz)
    contenido = json.loads(base.read_text(encoding="utf-8"))
    confirmacion = {"por": "operador", "decision_id": "d-1"}
    contenido["empresas"]["oficina"]["relaciones"][0]["confirmaciones_humanas"] = [confirmacion]
    base.write_text(json.dumps(contenido), encoding="utf-8")
    for dia, guia in (("2026-11-05", "N1"), ("2026-11-06", "N2")):
        _reloj(monkeypatch, dia)
        registro.incorporar_dataset(raiz, _dataset(raiz, [_rel(guia), _rel("H0")]))
    vigente = _normal(registro.contenido_vigente(raiz))
    resultado = registro.consolidar_diario(raiz)  # hoy (reloj) = 2026-11-06
    assert resultado["consolidados"] == ["20261105.json"]
    assert [p.name for p in registro.ruta_diario(raiz).glob("*.json")] == ["20261106.json"]
    assert _normal(registro.contenido_vigente(raiz)) == vigente
    entrada = next(e for e in registro.contenido_vigente(raiz)["empresas"]["oficina"]["relaciones"]
                   if e["relacion"]["numero_guia"] == "H0")
    assert entrada["confirmaciones_humanas"] == [confirmacion]
    assert registro.estado_registro(raiz)["estado_migracion"] == registro.ESTADO_COMPLETA


# --- Recuperación e integridad -----------------------------------------------------

def test_segmento_ilegible_bloquea_sin_sobrescribir_y_el_consumidor_vuelve_a_historicos(tmp_path, monkeypatch):
    from atlas_core import publicacion_reportes as pub
    raiz = tmp_path / "Atlas"
    _migrada(raiz)
    assert registro.verificar_migracion(raiz)["ok"]
    registro.activar_registro(raiz)
    pub.configurar(raiz, modo=pub.MODO_ROTATIVO)
    roto = registro.ruta_diario(raiz) / "20261106.json"
    roto.parent.mkdir(parents=True)
    roto.write_bytes(b'{"version": 1, "tipo": "diario_registro_relaciones", "entradas": [')
    antes = _almacen(raiz)
    assert registro.relaciones_si_activo(raiz) is None           # el consumidor usa el lector histórico
    assert registro.estado_registro(raiz)["codigo"] == "REGISTRO_ILEGIBLE"
    assert pub.modo_efectivo(raiz) == pub.MODO_SNAPSHOTS          # sin captura posible, vuelve a snapshots
    with pytest.raises(registro.RegistroIlegible):
        registro.incorporar_relaciones(raiz, [_rel("N9")], procedencia={"tipo": "x"})
    with pytest.raises(registro.RegistroIlegible):
        registro.consolidar_diario(raiz, hasta="99999999")
    with pytest.raises(registro.RegistroIlegible):
        registro.desactivar_registro(raiz)
    assert _almacen(raiz) == antes
    roto.write_text(json.dumps({"version": 2, "tipo": registro.TIPO_SEGMENTO, "entradas": []}), encoding="utf-8")
    assert registro.estado_registro(raiz)["codigo"] == "REGISTRO_INCOMPATIBLE"


def test_recuperacion_entre_equipos_drive_atrasado_y_copias_en_conflicto(tmp_path, monkeypatch):
    casa, oficina = tmp_path / "casa" / "Atlas", tmp_path / "oficina" / "Atlas"
    _migrada(casa)
    shutil.copytree(casa, oficina)                       # ambos parten del mismo base
    _reloj(monkeypatch, "2026-11-06")
    registro.incorporar_relaciones(casa, [_rel("C1")], procedencia={"tipo": registro.TIPO_DATASET, "dataset": "d"})
    # OFICINA aún no recibió el segmento: no ve C1, pero tampoco nada corrupto.
    assert "C1" not in {r["numero_guia"] for r in registro.leer_relaciones(oficina)}
    # Fuera de protocolo, OFICINA también anotó el mismo día (p. ej. sin lease).
    registro.incorporar_relaciones(oficina, [_rel("O1")], procedencia={"tipo": registro.TIPO_DATASET, "dataset": "d"})
    # Drive entrega el de CASA como copia en conflicto: la unión conserva ambos.
    shutil.copy2(registro.ruta_diario(casa) / "20261106.json", registro.ruta_diario(oficina) / "20261106 (1).json")
    guias = {r["numero_guia"] for r in registro.leer_relaciones(oficina)}
    assert {"C1", "O1", "H0", "H1", "H2"} <= guias
    # La consolidación incorpora también la copia en conflicto y retira ambas.
    registro.consolidar_diario(oficina, hasta="99999999")
    assert not list(registro.ruta_diario(oficina).glob("*.json"))
    assert {r["numero_guia"] for r in registro.leer_relaciones(oficina)} == guias


def test_diario_no_altera_la_firma_de_catalogos_como_en_modo_snapshots(tmp_path):
    from atlas_core.frescura_reconciliacion import _sha256_catalogos
    raiz = tmp_path / "Atlas"
    _migrada(raiz)
    antes = _sha256_catalogos(raiz / "catalogos_privados")
    registro.incorporar_dataset(raiz, _dataset(raiz, [_rel("N1")]))
    assert _sha256_catalogos(raiz / "catalogos_privados") == antes


# --- Custodia Cloud real: qué sube cada turno ---------------------------------------

class _Nube:
    """Misma semántica que el Worker para la custodia: objetos por huella,
    manifiesto versionado. Cuenta lo que se sube a R2."""

    def __init__(self):
        self.version, self.archivos, self.objetos, self.historial = 0, {}, {}, set()
        self.subidas, self.bytes_subidos = 0, 0

    def manifiesto(self):
        return {"version": self.version, "archivos": [[r, s, self.version] for r, s in self.archivos.items()]}

    def conocidos(self, consultas):
        return [(r, s) in self.historial for r, s in consultas]

    def faltantes(self, huellas):
        return [h for h in huellas if h not in self.objetos]

    def subir(self, sha, datos, _token):
        assert hashlib.sha256(datos).hexdigest() == sha
        self.objetos[sha] = datos
        self.subidas += 1
        self.bytes_subidos += len(datos)

    def descargar(self, sha):
        return self.objetos[sha]

    def confirmar(self, _token, base, archivos):
        assert base == self.version
        for rel, sha in archivos:
            self.archivos[rel] = sha
            self.historial.add((rel, sha))
        self.version += 1
        return self.version


class _Lease:
    lease_token, escritor_id = "t", "CASA"

    def __init__(self, nube):
        self.marca = {"version": nube.version}


def _turnos(raiz, tmp_path, monkeypatch, *, monolitico, dias, por_dia):
    """Cada publicación = un turno de PULL con custodia real (audit hook)."""
    nube = _Nube()
    custodia = ec.CustodiaEstado(raiz, nube, carpeta_local=tmp_path / f"custodia-{monolitico}")
    lease = _Lease(nube)
    custodia.alinear(lease)
    custodia.iniciar(lease)
    custodia._confirmar_rutas(lease, custodia.rutas_semilla())  # línea base (registro migrado)
    custodia.detener()
    linea_base = nube.bytes_subidos
    nube.subidas = nube.bytes_subidos = 0
    guia = 0
    for dia in range(dias):
        for _ in range(por_dia):
            _reloj(monkeypatch, f"2026-12-{dia + 1:02d}")
            lease = _Lease(nube)
            custodia.alinear(lease)
            custodia.iniciar(lease)
            try:
                guia += 1
                registro.incorporar_relaciones(raiz, [_rel(f"D{guia}", rut=f"{guia}-K")],
                                               procedencia={"tipo": registro.TIPO_PUBLICADO})
                if monolitico:  # el registro anterior: el archivo completo cambia en cada turno
                    registro.consolidar_diario(raiz, hasta="99999999")
                custodia.confirmar(lease)
            finally:
                custodia.detener()
    return nube, linea_base


def test_custodia_sube_solo_el_segmento_no_el_registro_completo(tmp_path, monkeypatch, capsys):
    resultados = {}
    for monolitico in (True, False):
        raiz = tmp_path / ("monolitico" if monolitico else "diario") / "Atlas"
        for i in range(40):
            _reporte(raiz, f"r{i:03d}", [_rel(f"H{i}-{j}", rut=f"{i}{j}-1") for j in range(50)])
        registro.migrar_reportes_historicos(raiz, aplicar=True, lote=50)
        resultados[monolitico] = _turnos(raiz, tmp_path, monkeypatch, monolitico=monolitico, dias=3, por_dia=5)
        assert len(registro.leer_relaciones(raiz)) == 40 * 50 + 15
    (mono, base_mono), (diario, base_diario) = resultados[True], resultados[False]
    with capsys.disabled():
        print(f"\n[MEDICION custodia] registro 2000 relaciones (base {base_mono} B), 15 turnos en 3 días: "
              f"monolitico subidas={mono.subidas} bytes={mono.bytes_subidos} | "
              f"diario subidas={diario.subidas} bytes={diario.bytes_subidos}")
    assert abs(base_mono - base_diario) < base_mono * 0.02  # mismo registro migrado (sólo cambian marcas de tiempo)
    assert mono.bytes_subidos >= 15 * base_mono                 # el archivo completo en cada turno
    assert diario.bytes_subidos * 50 < mono.bytes_subidos        # sólo el segmento del día
    assert set(diario.archivos) == {
        "catalogos_privados/registro_relaciones_operacionales.json",
        *(f"catalogos_privados/registro_relaciones_diario/202612{d:02d}.json" for d in (1, 2, 3)),
    }


def test_otro_equipo_recupera_el_diario_desde_la_custodia(tmp_path, monkeypatch):
    """OFICINA con Drive atrasado: la alineación restaura los segmentos
    confirmados y el registro vigente coincide con el de CASA."""
    casa = tmp_path / "casa" / "Atlas"
    _migrada(casa)
    oficina = tmp_path / "oficina" / "Atlas"
    shutil.copytree(casa, oficina)
    nube, _ = _turnos(casa, tmp_path, monkeypatch, monolitico=False, dias=2, por_dia=2)
    custodia = ec.CustodiaEstado(oficina, nube, carpeta_local=tmp_path / "custodia-oficina")
    resumen = custodia.alinear(_Lease(nube))
    assert sorted(resumen["restaurados"]) == [
        "catalogos_privados/registro_relaciones_diario/20261201.json",
        "catalogos_privados/registro_relaciones_diario/20261202.json",
    ]
    assert _normal(registro.contenido_vigente(oficina)) == _normal(registro.contenido_vigente(casa))


# --- CLI -----------------------------------------------------------------------------

def test_cli_consolidar_solo_con_escritor(tmp_path, monkeypatch, capsys):
    import migrar_relaciones_operacionales as cli
    raiz = tmp_path / "Atlas"
    _migrada(raiz)
    _reloj(monkeypatch, "2026-11-05")
    registro.incorporar_dataset(raiz, _dataset(raiz, [_rel("N1")]))
    antes = _almacen(raiz)
    assert cli.main(["--raiz", str(raiz), "--consolidar"], fabrica_escritor=lambda _r: None) == 2
    assert _almacen(raiz) == antes
    capsys.readouterr()
    assert cli.main(["--raiz", str(raiz), "--consolidar", "--hasta", "20261106", "--sin-escritor"]) == 0
    assert json.loads(capsys.readouterr().out)["consolidados"] == ["20261105.json"]
    assert cli.main(["--raiz", str(raiz), "--estado"]) == 0
    estado = json.loads(capsys.readouterr().out)
    assert estado["diario"]["segmentos"] == 0 and estado["relaciones"] == 4
