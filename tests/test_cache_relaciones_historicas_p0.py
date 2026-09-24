"""Bloque P0 ELIMINAR ESCANEO HISTÓRICO REPETITIVO. Causa raíz medida
(reconciliación real, guías 474211/474252): `_leer_relaciones_historicas_
reportadas` recorría CADA `viajes.csv` bajo `reportes/` (518 archivos,
396 MB medidos) en CADA llamada -- ~30.26s, el 51.5% del total de la
batería -- incluso con la bandeja de decisiones completamente VACÍA
(resultado sin usar). Estos tests prueban, en `tmp_path` (nunca G, nunca
red, nunca B1):

  A) bandeja vacía -> la función ni se llama;
  B) primera corrida con una decisión VEHICULO_DESCONOCIDO -> construye
     el histórico correctamente desde los reportes existentes;
  C) segunda corrida sin cambios -> no vuelve a parsear ningún archivo;
  D) aparece un reporte nuevo -> sólo se parsea ESE, el resto viene del
     cache;
  E) cache ausente/corrupto -> reconstruye correctamente (mismo
     resultado que sin cache);
  F) el resultado funcional (relaciones históricas) es idéntico con y
     sin cache."""
from __future__ import annotations

import csv
import json
from datetime import datetime, timezone

import pytest

from atlas_core.catalogo_clientes import CatalogoClientes
from atlas_core.catalogo_vehiculos import TipoVehiculo, confirmar_vehiculo
from atlas_core.decisiones_pendientes import crear_decision, generar_artefacto
from atlas_core.procesamiento_masivo import COLUMNAS
from atlas_core.revalidacion_documental import (
    _leer_relaciones_historicas_reportadas,
    _leer_relaciones_historicas_reportadas_sin_cache,
    _ruta_cache_relaciones_historicas,
    reconciliar_bandeja_decisiones,
)


def _fila(**ov):
    fila = {c: "" for c in COLUMNAS}
    fila.update({
        "archivo": "g1.jpeg", "estado_procesamiento": "OK", "numero_guia": "900001",
        "numero_transporte": "T-1", "indicador_revision": "REVISAR",
        "estado_documental": "REQUIERE_REVISION",
    })
    fila.update(ov)
    return fila


def _entorno(tmp_path):
    raiz = tmp_path / "Atlas"
    cat = raiz / "catalogos_privados"
    cat.mkdir(parents=True)
    actual = raiz / "operacion" / "actual"
    actual.mkdir(parents=True)
    for nombre in ("empresas.json", "choferes.json", "rutas.json"):
        (cat / nombre).write_text("{}", encoding="utf-8")
    (cat / "vehiculos.json").write_text(json.dumps({"version": 1, "vehiculos": []}), encoding="utf-8")
    CatalogoClientes(cat / "clientes.json")
    return raiz, cat, actual


def _escribir_reporte(raiz, nombre_carpeta, *, evidencias_por_viaje):
    """Crea `reportes/<nombre_carpeta>/viajes.csv` con una fila por cada
    entrada de `evidencias_por_viaje` (lista de listas de dicts -- una
    lista de `evidencias_documentos` por viaje), igual al esquema real
    que `_relaciones_de_un_reporte` lee."""
    carpeta = raiz / "reportes" / nombre_carpeta
    carpeta.mkdir(parents=True)
    ruta = carpeta / "viajes.csv"
    with ruta.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["numero_transporte", "evidencias_documentos"], delimiter=";")
        w.writeheader()
        for i, evidencias in enumerate(evidencias_por_viaje):
            w.writerow({
                "numero_transporte": f"T-{nombre_carpeta}-{i}",
                "evidencias_documentos": json.dumps(evidencias, ensure_ascii=False),
            })
    return ruta


def _decision_vehiculo(tmp_path_cat, *, rut="15489424-1"):
    # Mismo patrón ya probado en
    # test_reconciliacion_convergencia_historica_f5.py::
    # test_reconciliar_bandeja_autoaplica_vehiculo_con_ganadora_unica_de_nivel
    # -- un único candidato con evidencia de más alto nivel (CONFIRMACION_
    # HUMANA) alcanza RESUELTO_AUTOMATICAMENTE y se auto-aplica.
    confirmar_vehiculo(
        tmp_path_cat / "vehiculos.json", patente="JD8659", tipo=TipoVehiculo.CARRO,
        actor="JAVIER", fuente_decision="T", fecha=datetime.now(timezone.utc),
        rut_chofer_asociado=rut,
    )
    return crear_decision(
        tipo="VEHICULO_DESCONOCIDO", entidad="VEHICULO", archivo="g1.jpeg",
        numero_guia="900001", numero_transporte="T-1", campo="patente_rampla",
        valor_documental="JD8629", valor_normalizado="JD8629", identidad_resuelta=None,
        candidatos=({"patente": "JD8659", "nivel": "CONFIRMACION_HUMANA"},),
        motivos=("SIN_VEHICULO_CONFIRMADO_COMPATIBLE",), evidencias=(),
        acciones_permitidas=("REGISTRAR", "NO_REGISTRAR", "POSPONER"),
        tipo_resolucion="REQUIERE_CONFIRMACION_HUMANA", tipo_vehiculo_propuesto="CARRO",
    )


# ==========================================================================
# A -- bandeja vacía: la función histórica ni se llama
# ==========================================================================


def test_a_bandeja_vacia_no_ejecuta_escaneo_historico(tmp_path, monkeypatch):
    raiz, cat, actual = _entorno(tmp_path)
    # Reporte real en disco -- si la función se llamara, esto le daría
    # trabajo real que hacer.
    _escribir_reporte(raiz, "reporte1", evidencias_por_viaje=[
        [{"numero_guia": "1", "numero_transporte": "T-1", "rut_chofer": "15489424-1",
          "patente_tracto": "AB1234", "patente_rampla": ""}],
    ])
    _csv_ruta = actual / "analisis_completo_guias.csv"
    with _csv_ruta.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNAS, delimiter=";", extrasaction="ignore")
        w.writeheader()
    generar_artefacto(
        ruta_dataset=_csv_ruta, carpeta_catalogos=cat,
        decisiones=[], ruta_salida=actual / "decisiones_pendientes.json",
        reloj=lambda: datetime.now(timezone.utc),
    )

    def _fallar_si_se_llama(_raiz):
        raise AssertionError("con la bandeja vacía, _leer_relaciones_historicas_reportadas no debe llamarse")

    monkeypatch.setattr(
        "atlas_core.revalidacion_documental._leer_relaciones_historicas_reportadas", _fallar_si_se_llama,
    )
    r = reconciliar_bandeja_decisiones(raiz_atlas=raiz)
    assert r["decisiones_publicadas"] == 0


# ==========================================================================
# B -- primera corrida con decisión VEHICULO_DESCONOCIDO: construye bien
# ==========================================================================


def test_b_primera_corrida_construye_historico_correctamente(tmp_path, monkeypatch):
    raiz, cat, actual = _entorno(tmp_path)
    monkeypatch.setenv("ATLAS_CACHE_DIR", str(tmp_path / "cache"))
    _escribir_reporte(raiz, "reporte1", evidencias_por_viaje=[
        [{"numero_guia": "472477", "numero_transporte": "0000354870", "rut_chofer": "15489424-1",
          "patente_tracto": "", "patente_rampla": "JD8659"}],
    ])
    relaciones = _leer_relaciones_historicas_reportadas(raiz)
    assert len(relaciones) == 1
    assert relaciones[0]["numero_guia"] == "472477"
    assert relaciones[0]["patente_rampla"] == "JD8659"
    assert _ruta_cache_relaciones_historicas(raiz).is_file()


# ==========================================================================
# C -- segunda corrida sin cambios: no vuelve a parsear los archivos
# ==========================================================================


def test_c_segunda_corrida_sin_cambios_no_reparsea(tmp_path, monkeypatch):
    raiz, cat, actual = _entorno(tmp_path)
    monkeypatch.setenv("ATLAS_CACHE_DIR", str(tmp_path / "cache"))
    for i in range(5):
        _escribir_reporte(raiz, f"reporte{i}", evidencias_por_viaje=[
            [{"numero_guia": f"g{i}", "numero_transporte": f"t{i}", "rut_chofer": "15489424-1",
              "patente_tracto": "AB1234", "patente_rampla": ""}],
        ])
    primera = _leer_relaciones_historicas_reportadas(raiz)
    assert len(primera) == 5

    llamadas = []
    original = None
    import atlas_core.revalidacion_documental as rd
    original = rd._relaciones_de_un_reporte

    def _contador(ruta):
        llamadas.append(ruta)
        return original(ruta)

    monkeypatch.setattr(rd, "_relaciones_de_un_reporte", _contador)
    segunda = _leer_relaciones_historicas_reportadas(raiz)
    assert llamadas == []  # cero archivos reparseados
    assert {tuple(sorted(f.items())) for f in segunda} == {tuple(sorted(f.items())) for f in primera}


# ==========================================================================
# D -- aparece un reporte nuevo: sólo se parsea ESE
# ==========================================================================


def test_d_reporte_nuevo_solo_incorpora_la_evidencia_nueva(tmp_path, monkeypatch):
    raiz, cat, actual = _entorno(tmp_path)
    monkeypatch.setenv("ATLAS_CACHE_DIR", str(tmp_path / "cache"))
    for i in range(3):
        _escribir_reporte(raiz, f"reporte{i}", evidencias_por_viaje=[
            [{"numero_guia": f"g{i}", "numero_transporte": f"t{i}", "rut_chofer": "15489424-1",
              "patente_tracto": "AB1234", "patente_rampla": ""}],
        ])
    primera = _leer_relaciones_historicas_reportadas(raiz)
    assert len(primera) == 3

    # Nuevo reporte -- nunca visto antes.
    _escribir_reporte(raiz, "reporte_nuevo", evidencias_por_viaje=[
        [{"numero_guia": "gnuevo", "numero_transporte": "tnuevo", "rut_chofer": "99999999-9",
          "patente_tracto": "ZZ9999", "patente_rampla": ""}],
    ])

    import atlas_core.revalidacion_documental as rd
    original = rd._relaciones_de_un_reporte
    llamadas = []

    def _contador(ruta):
        llamadas.append(ruta.parent.name)
        return original(ruta)

    monkeypatch.setattr(rd, "_relaciones_de_un_reporte", _contador)
    segunda = _leer_relaciones_historicas_reportadas(raiz)
    assert llamadas == ["reporte_nuevo"]  # SÓLO el nuevo se reparseó
    assert len(segunda) == 4  # 3 anteriores + 1 nueva -- nada se perdió
    guias = {f["numero_guia"] for f in segunda}
    assert guias == {"g0", "g1", "g2", "gnuevo"}


# ==========================================================================
# E -- cache ausente/corrupto: reconstruye correctamente
# ==========================================================================


def test_e_cache_corrupto_reconstruye_correctamente(tmp_path, monkeypatch):
    raiz, cat, actual = _entorno(tmp_path)
    monkeypatch.setenv("ATLAS_CACHE_DIR", str(tmp_path / "cache"))
    for i in range(3):
        _escribir_reporte(raiz, f"reporte{i}", evidencias_por_viaje=[
            [{"numero_guia": f"g{i}", "numero_transporte": f"t{i}", "rut_chofer": "15489424-1",
              "patente_tracto": "AB1234", "patente_rampla": ""}],
        ])
    esperado = _leer_relaciones_historicas_reportadas(raiz)

    ruta_cache = _ruta_cache_relaciones_historicas(raiz)
    assert ruta_cache.is_file()
    ruta_cache.write_text("{ esto no es json valido ][", encoding="utf-8")

    resultado = _leer_relaciones_historicas_reportadas(raiz)
    assert {tuple(sorted(f.items())) for f in resultado} == {tuple(sorted(f.items())) for f in esperado}

    # Cache ausente por completo -- también reconstruye.
    ruta_cache.unlink()
    resultado2 = _leer_relaciones_historicas_reportadas(raiz)
    assert {tuple(sorted(f.items())) for f in resultado2} == {tuple(sorted(f.items())) for f in esperado}


# ==========================================================================
# F -- resultado funcional idéntico con y sin cache
# ==========================================================================


def test_f_resultado_identico_con_y_sin_cache(tmp_path, monkeypatch):
    raiz, cat, actual = _entorno(tmp_path)
    monkeypatch.setenv("ATLAS_CACHE_DIR", str(tmp_path / "cache"))
    for i in range(4):
        _escribir_reporte(raiz, f"reporte{i}", evidencias_por_viaje=[
            [{"numero_guia": f"g{i}", "numero_transporte": f"t{i}", "rut_chofer": "15489424-1",
              "patente_tracto": "AB1234", "patente_rampla": ""}],
        ])
    con_cache = _leer_relaciones_historicas_reportadas(raiz)
    sin_cache = _leer_relaciones_historicas_reportadas_sin_cache(raiz)
    assert {tuple(sorted(f.items())) for f in con_cache} == {tuple(sorted(f.items())) for f in sin_cache}


def test_f2_reconciliar_bandeja_mismo_resultado_con_decision_vehiculo(tmp_path, monkeypatch):
    """Extremo a extremo: `reconciliar_bandeja_decisiones` con una
    decisión VEHICULO_DESCONOCIDO produce el mismo enriquecimiento con el
    cache activo que el comportamiento histórico (mismo criterio que
    `test_reconciliar_bandeja_autoaplica_vehiculo_con_ganadora_unica_de_nivel`,
    ver test_reconciliacion_convergencia_historica_f5.py)."""
    raiz, cat, actual = _entorno(tmp_path)
    monkeypatch.setenv("ATLAS_CACHE_DIR", str(tmp_path / "cache"))
    _escribir_reporte(raiz, "reporte1", evidencias_por_viaje=[
        [{"numero_guia": "472477", "numero_transporte": "0000354870", "rut_chofer": "15489424-1",
          "patente_tracto": "", "patente_rampla": "JD8659"}],
    ])
    decision = _decision_vehiculo(cat)
    filas = [_fila(rut_chofer="15489424-1", chofer="CARLOS SIMON", patente_rampla="JD8629")]
    _csv_ruta = actual / "analisis_completo_guias.csv"
    with _csv_ruta.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNAS, delimiter=";", extrasaction="ignore")
        w.writeheader(); w.writerows(filas)
    generar_artefacto(
        ruta_dataset=_csv_ruta, carpeta_catalogos=cat, decisiones=[decision],
        ruta_salida=actual / "decisiones_pendientes.json",
        reloj=lambda: datetime.now(timezone.utc),
    )

    r = reconciliar_bandeja_decisiones(raiz_atlas=raiz)
    aplicadas = r["decisiones_aplicadas_automaticamente"]
    assert len(aplicadas) == 1
    assert aplicadas[0]["resultado"]["ok"] is True
    tipos = {d["tipo"] for d in r["bandeja"]["decisiones"]}
    assert "VEHICULO_DESCONOCIDO" not in tipos  # candidato único -> resuelta
