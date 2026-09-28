"""Caso real 474823 -- UnicodeEncodeError '\\udc8d' al aplicar decisiones
múltiples. Causa: el lote llegaba por stdin decodificado como cp1252 +
surrogateescape ("COMPAÑÍA" -> "COMPAÃ\\u2018Ã\\udc8d"). Regresiones de la
corrección general: lectura UTF-8 estricta del lote, escrituras UTF-8 que
sólo sanean lo inválido (con trazabilidad) sin dejar temporales, y un lote
que ante un error inesperado no queda en estado parcial incoherente.
Datos sintéticos; nunca G:."""
from __future__ import annotations

import csv
import json
import logging
import os
import subprocess
import sys
from pathlib import Path

from atlas_core.almacenamiento_portable import escribir_json_atomico
from atlas_core.aplicacion_multiple import aplicar_decisiones_multiples
from atlas_core.catalogo_obras_destinos import CatalogoObrasDestinos
from atlas_core.decisiones_pendientes import generar_artefacto
from atlas_core.procesamiento_masivo import COLUMNAS
from atlas_core.revalidacion_documental import _escribir_filas_completas, _leer_filas
from tests.test_aplicacion_multiple import _contador_reconciliacion, _decision_obra, _entorno

NOMBRE_CONFIRMADO = "CONSTRUCTORA YUBINI ARAYA Y COMPAÑÍA LIMITADA"
OBRA_DOCUMENTAL = "CONSTRUCTORA YUBINI ARAYA Y"
RAIZ_MOTOR = Path(__file__).resolve().parent.parent


def _fila(guia, **extra):
    fila = {c: "" for c in COLUMNAS}
    fila.update({"archivo": f"{guia}.png", "estado_procesamiento": "OK", "numero_guia": guia,
                 "numero_transporte": f"T{guia}", "fecha": "28-09-2026", "cliente": "CLIENTE CANONICO SA",
                 "indicador_revision": "REVISAR", "motivos_revision_documento": "OBRA_DESTINO_SIN_CORROBORAR"})
    fila.update(extra)
    return fila


def _escribir_dataset(ruta, filas):
    with ruta.open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader()
        escritor.writerows(filas)


def _temporales(carpeta):
    return [p.name for p in Path(carpeta).glob(".*.tmp")]


# ------------------------------------------------------------- entrada del lote


def test_lote_por_stdin_utf8_llega_intacto_aunque_la_consola_sea_cp1252():
    """Mismo modo que Desktop: bytes UTF-8 por tubería, sin PYTHONUTF8 ni
    PYTHONIOENCODING (en Windows stdin sería cp1252 + surrogateescape)."""
    entorno = {k: v for k, v in os.environ.items() if k not in {"PYTHONIOENCODING", "PYTHONUTF8"}}
    lote = json.dumps([{"decision_id": "x", "accion": "REGISTRAR", "nombre_obra_manual": NOMBRE_CONFIRMADO}],
                      ensure_ascii=False).encode("utf-8")
    salida = subprocess.run(
        [sys.executable, "-c", "import aplicar_decisiones_multiples as m; "
                               "print(ascii(m.leer_solicitudes()[0]['nombre_obra_manual']))"],
        input=lote, capture_output=True, cwd=RAIZ_MOTOR, env=entorno, check=True,
    )
    assert salida.stdout.decode("ascii").strip() == ascii(NOMBRE_CONFIRMADO)


def test_lote_no_utf8_se_rechaza_con_json_sin_aplicar_nada(tmp_path):
    entorno = {k: v for k, v in os.environ.items() if k not in {"PYTHONIOENCODING", "PYTHONUTF8"}}
    salida = subprocess.run(
        [sys.executable, "aplicar_decisiones_multiples.py", "--raiz-atlas", str(tmp_path)],
        input='[{"nombre_obra_manual": "COMPAÑÍA"}]'.encode("cp1252"),
        capture_output=True, cwd=RAIZ_MOTOR, env=entorno, check=True,
    )
    resultado = json.loads(salida.stdout.decode("ascii"))
    assert resultado["total_aplicadas"] == 0
    assert "UTF-8" in resultado["reconciliacion_motivo"]


# ------------------------------------------------------------- escrituras UTF-8


def test_csv_con_surrogate_de_ocr_se_escribe_saneado_y_conserva_texto_valido(tmp_path, caplog):
    ruta = tmp_path / "analisis_completo_guias.csv"
    filas = [
        _fila("474823", obra_destino=NOMBRE_CONFIRMADO, chofer="OSCAR QUEZADA"),
        _fila("474824", obra_destino="OBRA LEÍDA CON RUIDO \udc8d FINAL", chofer="ÑANCUCHEO"),
    ]
    with caplog.at_level(logging.WARNING, logger="atlas_core.texto_unicode"):
        _escribir_filas_completas(ruta, filas)
    releidas = {f["numero_guia"]: f for f in _leer_filas(ruta)}
    assert releidas["474823"]["obra_destino"] == NOMBRE_CONFIRMADO
    assert releidas["474824"]["obra_destino"] == "OBRA LEÍDA CON RUIDO � FINAL"
    assert releidas["474824"]["chofer"] == "ÑANCUCHEO"
    assert any("guia=474824" in r.getMessage() and "columna=obra_destino" in r.getMessage() for r in caplog.records)
    assert _temporales(tmp_path) == []


def test_fallo_no_oserror_durante_escritura_csv_no_deja_temporal(tmp_path, monkeypatch):
    ruta = tmp_path / "analisis_completo_guias.csv"
    _escribir_dataset(ruta, [_fila("1")])
    antes = ruta.read_bytes()

    def falla(self, filas):
        raise RuntimeError("fallo simulado a mitad de escritura")

    monkeypatch.setattr(csv.DictWriter, "writerows", falla)
    try:
        _escribir_filas_completas(ruta, [_fila("1", obra_destino="X")])
    except RuntimeError:
        pass
    assert ruta.read_bytes() == antes
    assert _temporales(tmp_path) == []


def test_json_atomico_con_surrogate_se_sanea_y_conserva_texto_valido(tmp_path, caplog):
    ruta = tmp_path / "catalogo.json"
    with caplog.at_level(logging.WARNING, logger="atlas_core.texto_unicode"):
        escribir_json_atomico(ruta, {"obra": NOMBRE_CONFIRMADO, "ruido": "A\udc8dB"})
    contenido = json.loads(ruta.read_text(encoding="utf-8"))
    assert contenido == {"obra": NOMBRE_CONFIRMADO, "ruido": "A�B"}
    assert caplog.records and _temporales(tmp_path) == []


# ------------------------------------------------------------- aplicación múltiple


def _entorno_474823(tmp_path, guias=("474823",)):
    raiz, catalogos, actual, cliente = _entorno(tmp_path)
    dataset = actual / "analisis_completo_guias.csv"
    _escribir_dataset(dataset, [_fila(g, obra_destino=f"{OBRA_DOCUMENTAL} {i}" if i else OBRA_DOCUMENTAL)
                                for i, g in enumerate(guias)])
    decisiones = [_decision_obra(f"{g}.png", g, cliente, f"{OBRA_DOCUMENTAL} {i}" if i else OBRA_DOCUMENTAL)
                  for i, g in enumerate(guias)]
    generar_artefacto(ruta_dataset=dataset, carpeta_catalogos=catalogos, decisiones=decisiones,
                      ruta_salida=actual / "decisiones_pendientes.json")
    return raiz, catalogos, actual, decisiones


def _obras(catalogos):
    return CatalogoObrasDestinos(ruta=catalogos / "obras_destinos.json", ruta_clientes=catalogos / "clientes.json",
                                 ruta_destinos=catalogos / "destinos_maestros.json").listar_obras()


def test_aplicacion_multiple_con_nombre_confirmado_con_n_y_tilde_queda_intacto(tmp_path, monkeypatch):
    raiz, catalogos, actual, decisiones = _entorno_474823(tmp_path)
    _contador_reconciliacion(monkeypatch)
    resultado = aplicar_decisiones_multiples(raiz_atlas=raiz, solicitudes=[{
        "decision_id": decisiones[0]["decision_id"], "accion": "REGISTRAR", "nombre_obra_manual": NOMBRE_CONFIRMADO,
    }])
    assert resultado.total_aplicadas == 1, resultado.a_dict()
    fila = {f["numero_guia"]: f for f in _leer_filas(actual / "analisis_completo_guias.csv")}["474823"]
    assert fila["obra_destino"] == NOMBRE_CONFIRMADO
    assert [o.nombre_canonico for o in _obras(catalogos)] == [NOMBRE_CONFIRMADO]
    assert _temporales(actual) == []


def test_error_inesperado_a_mitad_del_lote_no_deja_estado_parcial_incoherente(tmp_path, monkeypatch):
    """Réplica del 474823: 1ra aplicada, 2da falla con UnicodeEncodeError
    (no de dominio). Antes abortaba el lote sin informar ni cerrar; ahora la
    2da se revierte y queda pendiente, la 3ra NO se procesa (lote detenido),
    y el cierre agregado corre para la que sí se aplicó."""
    raiz, catalogos, actual, decisiones = _entorno_474823(tmp_path, guias=("474823", "474824", "474825"))
    llamadas = _contador_reconciliacion(monkeypatch)
    import atlas_core.aplicacion_multiple as modulo
    real = modulo.aplicar_decision_obra
    fallida = decisiones[1]["decision_id"]

    def aplicar(*, decision_id, **kwargs):
        if decision_id == fallida:
            raise UnicodeEncodeError("utf-8", "\udc8d", 0, 1, "surrogates not allowed")
        return real(decision_id=decision_id, **kwargs)

    monkeypatch.setattr(modulo, "aplicar_decision_obra", aplicar)
    resultado = aplicar_decisiones_multiples(raiz_atlas=raiz, solicitudes=[
        {"decision_id": d["decision_id"], "accion": "REGISTRAR"} for d in decisiones])

    por_id = {r.decision_id: r for r in resultado.resultados}
    assert por_id[decisiones[0]["decision_id"]].aplicada is True
    assert por_id[fallida].aplicada is False and "UnicodeEncodeError" in por_id[fallida].motivo
    assert por_id[decisiones[2]["decision_id"]].aplicada is False
    assert "No procesada" in por_id[decisiones[2]["decision_id"]].motivo
    assert resultado.total_aplicadas == 1 and len(llamadas) == 1 and resultado.reconciliacion_ejecutada
    ledger = json.loads((actual / "decisiones_aplicadas.json").read_text(encoding="utf-8"))["aplicaciones"]
    assert [a["decision_id"] for a in ledger] == [decisiones[0]["decision_id"]]
    pendientes = {d["decision_id"] for d in
                  json.loads((actual / "decisiones_pendientes.json").read_text(encoding="utf-8"))["decisiones"]}
    assert {fallida, decisiones[2]["decision_id"]} <= pendientes
    assert _temporales(actual) == []


def test_surrogate_en_texto_humano_ya_no_rompe_la_aplicacion(tmp_path, monkeypatch, caplog):
    raiz, catalogos, actual, decisiones = _entorno_474823(tmp_path)
    _contador_reconciliacion(monkeypatch)
    corrupto = "CONSTRUCTORA YUBINI ARAYA Y COMPAÃ‘Ã\udc8dA LIMITADA"  # tal como llegó en 474823
    with caplog.at_level(logging.WARNING, logger="atlas_core.texto_unicode"):
        resultado = aplicar_decisiones_multiples(raiz_atlas=raiz, solicitudes=[{
            "decision_id": decisiones[0]["decision_id"], "accion": "REGISTRAR", "nombre_obra_manual": corrupto,
        }])
    assert resultado.total_aplicadas == 1
    fila = {f["numero_guia"]: f for f in _leer_filas(actual / "analisis_completo_guias.csv")}["474823"]
    assert "\udc8d" not in fila["obra_destino"] and "�" in fila["obra_destino"]
    assert any("474823" in r.getMessage() for r in caplog.records), "el saneamiento deja trazabilidad"
    assert _temporales(actual) == []
