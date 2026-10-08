"""P0 CACHÉ HISTÓRICO (casa, 08-10). Causa raíz medida en G: real: 22 de
los 25 `reportes/*/viajes.csv` nuevos traían un campo > 131072 caracteres.
`_relaciones_de_un_reporte` sólo capturaba OSError/UnicodeDecodeError, así
que en un proceso con el límite por defecto de ``csv`` el `csv.Error`
abortaba `_leer_relaciones_historicas_reportadas` ANTES de escribir el
cache -> el cache nunca avanzaba (o nunca existía) y cada envío Mobile
volvía a recorrer todo `reportes/`. Además el cache se escribía con
`write_text` (no atómico): un lector concurrente podía verlo vacío.

Estos tests prueban, en `tmp_path` (nunca G, nunca red, nunca OCR):
campos grandes sin depender del orden de importación, carpeta ilegible
(no registrada, reintentada, sin perder el resto), cache ausente /
corrupto, carpeta cambiada / desaparecida / cambiando durante la lectura,
escritura atómica y actualización incremental de varios envíos."""
from __future__ import annotations

import csv
import json
import shutil

import atlas_core.revalidacion_documental as rd
from atlas_core.revalidacion_documental import (
    _leer_relaciones_historicas_reportadas,
    _leer_relaciones_historicas_reportadas_sin_cache,
    _ruta_cache_relaciones_historicas,
)


def _raiz(tmp_path, monkeypatch):
    monkeypatch.setenv("ATLAS_CACHE_DIR", str(tmp_path / "cache"))
    raiz = tmp_path / "Atlas"
    (raiz / "reportes").mkdir(parents=True)
    return raiz


def _escribir_reporte(raiz, nombre, relaciones):
    carpeta = raiz / "reportes" / nombre
    carpeta.mkdir(parents=True)
    ruta = carpeta / "viajes.csv"
    with ruta.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["numero_transporte", "evidencias_documentos"], delimiter=";")
        w.writeheader()
        w.writerow({"numero_transporte": f"T-{nombre}", "evidencias_documentos": json.dumps(relaciones)})
    return ruta


def _relacion(guia):
    return {"numero_guia": guia, "numero_transporte": f"t{guia}", "rut_chofer": "15489424-1",
            "patente_tracto": "AB1234", "patente_rampla": ""}


def _relacion_grande(guia):
    # `evidencias_documentos` real: JSON con texto OCR largo por documento.
    return {**_relacion(guia), "texto_ocr": "X" * 200_000}


def _guias(relaciones):
    return {f["numero_guia"] for f in relaciones}


def _cache(raiz):
    return json.loads(_ruta_cache_relaciones_historicas(raiz).read_text(encoding="utf-8"))


def _contar_lecturas(monkeypatch, lector=None):
    original = lector or rd._leer_reporte_historico
    llamadas: list[str] = []

    def _contador(ruta):
        llamadas.append(ruta.parent.name)
        return original(ruta)

    monkeypatch.setattr(rd, "_leer_reporte_historico", _contador)
    return llamadas


def test_campo_mayor_al_limite_por_defecto_se_lee_sin_depender_de_importaciones(tmp_path, monkeypatch):
    raiz = _raiz(tmp_path, monkeypatch)
    _escribir_reporte(raiz, "reporte0", [_relacion("g0")])
    _escribir_reporte(raiz, "reporte_grande", [_relacion_grande("ggrande")])
    anterior = csv.field_size_limit()
    # Proceso donde nadie subió el límite (o alguien lo volvió a bajar
    # después de importar `mobile`/`procesamiento_masivo`).
    csv.field_size_limit(131072)
    try:
        con_cache = _leer_relaciones_historicas_reportadas(raiz)
        csv.field_size_limit(131072)
        sin_cache = _leer_relaciones_historicas_reportadas_sin_cache(raiz)
    finally:
        csv.field_size_limit(anterior)
    assert _guias(con_cache) == _guias(sin_cache) == {"g0", "ggrande"}
    assert set(_cache(raiz)["carpetas"]) == {"reporte0", "reporte_grande"}


def test_carpeta_ilegible_no_se_registra_conserva_el_resto_y_se_reintenta(tmp_path, monkeypatch):
    raiz = _raiz(tmp_path, monkeypatch)
    for i in range(3):
        _escribir_reporte(raiz, f"reporte{i}", [_relacion(f"g{i}")])
    _escribir_reporte(raiz, "reporte_roto", [_relacion("groto")])
    original = rd._leer_reporte_historico
    roto = {"activo": True}

    def _lector(ruta):
        if ruta.parent.name == "reporte_roto" and roto["activo"]:
            return None  # ilegible (OSError / csv.Error / UnicodeDecodeError)
        return original(ruta)

    monkeypatch.setattr(rd, "_leer_reporte_historico", _lector)
    primera = _leer_relaciones_historicas_reportadas(raiz)
    assert _guias(primera) == {"g0", "g1", "g2"}  # evidencia válida conservada
    assert set(_cache(raiz)["carpetas"]) == {"reporte0", "reporte1", "reporte2"}  # la rota NO

    # Siguiente llamada: sólo se reintenta la pendiente; ya legible, se incorpora.
    roto["activo"] = False
    llamadas = _contar_lecturas(monkeypatch, _lector)
    segunda = _leer_relaciones_historicas_reportadas(raiz)
    assert llamadas == ["reporte_roto"]
    assert _guias(segunda) == {"g0", "g1", "g2", "groto"}
    assert "reporte_roto" in _cache(raiz)["carpetas"]


def test_carpeta_ilegible_real_no_aborta_la_llamada(tmp_path, monkeypatch):
    raiz = _raiz(tmp_path, monkeypatch)
    _escribir_reporte(raiz, "reporte0", [_relacion("g0")])
    roto = raiz / "reportes" / "reporte_binario"
    roto.mkdir()
    (roto / "viajes.csv").write_bytes(b"\xff\xfe\x00\x81 no es utf-8 \x00")
    assert rd._leer_reporte_historico(roto / "viajes.csv") is None
    assert _guias(_leer_relaciones_historicas_reportadas(raiz)) == {"g0"}
    assert set(_cache(raiz)["carpetas"]) == {"reporte0"}


def test_cache_ausente_con_reporte_grande_queda_escrito_y_la_siguiente_no_reparsea(tmp_path, monkeypatch):
    raiz = _raiz(tmp_path, monkeypatch)
    for i in range(3):
        _escribir_reporte(raiz, f"reporte{i}", [_relacion(f"g{i}")])
    _escribir_reporte(raiz, "reporte_grande", [_relacion_grande("ggrande")])
    assert not _ruta_cache_relaciones_historicas(raiz).exists()
    primera = _leer_relaciones_historicas_reportadas(raiz)
    assert _ruta_cache_relaciones_historicas(raiz).is_file()

    llamadas = _contar_lecturas(monkeypatch)
    segunda = _leer_relaciones_historicas_reportadas(raiz)
    assert llamadas == []
    assert _guias(segunda) == _guias(primera) == {"g0", "g1", "g2", "ggrande"}


def test_cache_corrupto_vacio_o_mal_formado_reconstruye_igual_que_sin_cache(tmp_path, monkeypatch):
    raiz = _raiz(tmp_path, monkeypatch)
    _escribir_reporte(raiz, "reporte0", [_relacion("g0")])
    _escribir_reporte(raiz, "reporte_grande", [_relacion_grande("ggrande")])
    esperado = _guias(_leer_relaciones_historicas_reportadas_sin_cache(raiz))
    ruta_cache = _ruta_cache_relaciones_historicas(raiz)
    ruta_cache.parent.mkdir(parents=True, exist_ok=True)
    for contenido in ("", "{ no json ][", json.dumps({"carpetas": [], "relaciones": {}})):
        ruta_cache.write_text(contenido, encoding="utf-8")
        assert _guias(_leer_relaciones_historicas_reportadas(raiz)) == esperado
        assert set(_cache(raiz)["carpetas"]) == {"reporte0", "reporte_grande"}


def test_carpeta_cambiada_o_desaparecida_no_sirve_evidencia_obsoleta(tmp_path, monkeypatch):
    raiz = _raiz(tmp_path, monkeypatch)
    for i in range(3):
        _escribir_reporte(raiz, f"reporte{i}", [_relacion(f"g{i}")])
    assert _guias(_leer_relaciones_historicas_reportadas(raiz)) == {"g0", "g1", "g2"}

    shutil.rmtree(raiz / "reportes" / "reporte1")
    _escribir_reporte(raiz, "reporte1", [_relacion("g1b"), _relacion("g1c")])  # huella distinta
    assert _guias(_leer_relaciones_historicas_reportadas(raiz)) == {"g0", "g1b", "g1c", "g2"}

    shutil.rmtree(raiz / "reportes" / "reporte2")
    assert _guias(_leer_relaciones_historicas_reportadas(raiz)) == {"g0", "g1b", "g1c"}


def test_huella_que_cambia_durante_la_lectura_no_se_registra(tmp_path, monkeypatch):
    raiz = _raiz(tmp_path, monkeypatch)
    _escribir_reporte(raiz, "reporte0", [_relacion("g0")])
    _escribir_reporte(raiz, "reporte_escribiendose", [_relacion("gw")])
    original = rd._leer_reporte_historico

    def _lector_que_ve_crecer(ruta):
        filas = original(ruta)
        if ruta.parent.name == "reporte_escribiendose":
            with ruta.open("a", encoding="utf-8") as f:
                f.write("T-extra;[]\n")  # el escritor sigue agregando
        return filas

    monkeypatch.setattr(rd, "_leer_reporte_historico", _lector_que_ve_crecer)
    assert _guias(_leer_relaciones_historicas_reportadas(raiz)) == {"g0", "gw"}  # vale para esta llamada
    cache = _cache(raiz)
    assert set(cache["carpetas"]) == {"reporte0"}  # pero no queda congelada a medias
    assert _guias(cache["relaciones"]) == {"g0"}  # ni su evidencia entra al cache


def test_escritura_atomica_no_deja_temporales_ni_cache_parcial(tmp_path, monkeypatch):
    raiz = _raiz(tmp_path, monkeypatch)
    _escribir_reporte(raiz, "reporte0", [_relacion("g0")])
    _leer_relaciones_historicas_reportadas(raiz)
    ruta_cache = _ruta_cache_relaciones_historicas(raiz)
    previo = ruta_cache.read_text(encoding="utf-8")
    assert [p.name for p in ruta_cache.parent.iterdir()] == [ruta_cache.name]

    _escribir_reporte(raiz, "reporte1", [_relacion("g1")])

    def _replace_falla(_origen, _destino):
        raise PermissionError("bloqueado por otro proceso")

    monkeypatch.setattr(rd.os, "replace", _replace_falla)
    assert _guias(_leer_relaciones_historicas_reportadas(raiz)) == {"g0", "g1"}
    assert ruta_cache.read_text(encoding="utf-8") == previo  # cache anterior intacto
    assert [p.name for p in ruta_cache.parent.iterdir()] == [ruta_cache.name]  # sin temporales


def test_varios_envios_seguidos_solo_parsean_lo_nuevo(tmp_path, monkeypatch):
    raiz = _raiz(tmp_path, monkeypatch)
    for i in range(5):
        _escribir_reporte(raiz, f"reporte_hist{i}", [_relacion(f"h{i}")])
    _leer_relaciones_historicas_reportadas(raiz)

    llamadas = _contar_lecturas(monkeypatch)
    for n in range(3):
        nombre = f"reporte_mobile_{n}"
        _escribir_reporte(raiz, nombre, [_relacion_grande(f"m{n}") if n % 2 == 0 else _relacion(f"m{n}")])
        llamadas.clear()
        resultado = _leer_relaciones_historicas_reportadas(raiz)
        assert llamadas == [nombre]
        assert _guias(resultado) == {f"h{i}" for i in range(5)} | {f"m{k}" for k in range(n + 1)}
