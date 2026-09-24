"""Bloque P0 OBSERVABILIDAD RECONCILIACIÓN FOCAL. Caso real medido (guía
474196): la reconciliación focal tomó ~60s sin que ningún log dijera en
qué sub-etapa -- `reconciliar_estado_derivado` ya calculaba `tiempos_ms`
internamente (bloque `_marca_etapa`), pero se descartaba. Estos tests
prueban que esa información YA EXISTENTE ahora se persiste (alcance
FOCAL/GLOBAL + guías objetivo + tiempos), fuera de `raiz_atlas`/G:\\
(vía `ATLAS_DIAGNOSTICO_DIR`, el mismo mecanismo de override que
`atlas_core.paddle_runtime`), y que un fallo del propio diagnóstico
(ruta no escribible) nunca impide ni altera una reconciliación real --
sin ejecutar red ni tocar G, todo en `tmp_path`."""
from __future__ import annotations

import json

from atlas_core.reconciliacion_estado_derivado import reconciliar_estado_derivado
from atlas_core.rutas.proveedor import ProveedorRutasSimulado
from tests.test_ingesta_focal_p0 import RELOJ, _entorno_focal, _fila_backlog, _fila_nueva


def _ultima_linea(ruta_log):
    lineas = ruta_log.read_text(encoding="utf-8").strip().splitlines()
    return json.loads(lineas[-1])


def test_focal_registra_sus_tiempos_y_alcance(tmp_path, monkeypatch):
    ruta_diagnostico = tmp_path / "diagnostico"
    monkeypatch.setenv("ATLAS_DIAGNOSTICO_DIR", str(ruta_diagnostico))

    filas_backlog = [_fila_backlog(f"OLD{i:03d}", None) for i in range(1, 4)]
    filas_nuevas = [_fila_nueva("NEW001", None)]
    ent = _entorno_focal(tmp_path, filas_backlog=filas_backlog, filas_nuevas=filas_nuevas)
    proveedor = ProveedorRutasSimulado()

    resultado = reconciliar_estado_derivado(
        raiz_atlas=ent["raiz"], reloj=RELOJ, proveedor_rutas=proveedor, proveedor_rutas_fallback=proveedor,
        guias_objetivo={"NEW001"},
    )
    assert resultado["reconciliado"] is True

    ruta_log = ruta_diagnostico / "reconciliacion_tiempos.jsonl"
    assert ruta_log.is_file()
    entrada = _ultima_linea(ruta_log)
    assert entrada["alcance"] == "FOCAL"
    assert entrada["guias_objetivo"] == ["NEW001"]
    assert entrada["reconciliado"] is True
    # `tiempos_ms` es EXACTAMENTE lo que la función ya calculaba y
    # devolvía -- no una medición nueva -- por eso debe coincidir con lo
    # que trae `resultado` mismo.
    assert entrada["tiempos_ms"] == resultado["tiempos_ms"]
    assert entrada["duracion_bateria_completa_ms"] == resultado["duracion_bateria_completa_ms"]
    assert isinstance(entrada["tiempos_ms"], dict) and len(entrada["tiempos_ms"]) > 0
    # El diagnóstico vive fuera de raiz_atlas -- nunca dentro de G/la
    # operación real que este test simula.
    assert not str(ruta_log).startswith(str(ent["raiz"]))


def test_global_registra_sus_tiempos(tmp_path, monkeypatch):
    ruta_diagnostico = tmp_path / "diagnostico"
    monkeypatch.setenv("ATLAS_DIAGNOSTICO_DIR", str(ruta_diagnostico))

    filas_backlog = [_fila_backlog(f"OLD{i:03d}", None) for i in range(1, 3)]
    filas_nuevas = [_fila_nueva("NEW001", None)]
    ent = _entorno_focal(tmp_path, filas_backlog=filas_backlog, filas_nuevas=filas_nuevas)
    proveedor = ProveedorRutasSimulado()

    resultado = reconciliar_estado_derivado(
        raiz_atlas=ent["raiz"], reloj=RELOJ, proveedor_rutas=proveedor, proveedor_rutas_fallback=proveedor,
        guias_objetivo=None,
    )
    assert resultado["reconciliado"] is True

    entrada = _ultima_linea(ruta_diagnostico / "reconciliacion_tiempos.jsonl")
    assert entrada["alcance"] == "GLOBAL"
    assert entrada["guias_objetivo"] is None
    assert entrada["tiempos_ms"] == resultado["tiempos_ms"]


def test_fallo_del_diagnostico_nunca_afecta_la_reconciliacion(tmp_path, monkeypatch):
    # Fuerza que la ruta de diagnóstico sea imposible de crear: un
    # ARCHIVO ya ocupa el lugar donde el diagnóstico necesitaría un
    # directorio -- `mkdir(parents=True)` falla adentro del bloque
    # `try/except` del propio helper.
    obstaculo = tmp_path / "diagnostico_bloqueado"
    obstaculo.write_text("no soy un directorio", encoding="utf-8")
    monkeypatch.setenv("ATLAS_DIAGNOSTICO_DIR", str(obstaculo / "sub"))

    filas_backlog = [_fila_backlog(f"OLD{i:03d}", None) for i in range(1, 3)]
    filas_nuevas = [_fila_nueva("NEW001", None)]
    ent = _entorno_focal(tmp_path, filas_backlog=filas_backlog, filas_nuevas=filas_nuevas)
    proveedor = ProveedorRutasSimulado()

    # No debe lanzar -- la reconciliación real se completa exactamente
    # igual que sin diagnóstico.
    resultado = reconciliar_estado_derivado(
        raiz_atlas=ent["raiz"], reloj=RELOJ, proveedor_rutas=proveedor, proveedor_rutas_fallback=proveedor,
        guias_objetivo={"NEW001"},
    )
    assert resultado["reconciliado"] is True
    assert isinstance(resultado["tiempos_ms"], dict) and len(resultado["tiempos_ms"]) > 0
    # El "archivo" que ocupaba el lugar del directorio de diagnóstico
    # sigue intacto -- el fallo se contuvo, nunca se propagó ni corrompió
    # nada fuera del propio intento de log.
    assert obstaculo.read_text(encoding="utf-8") == "no soy un directorio"
