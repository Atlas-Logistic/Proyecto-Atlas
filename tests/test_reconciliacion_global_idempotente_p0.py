"""Bloque P0 INGESTA FOCAL -- ELIMINAR RECONCILIACIÓN DUPLICADA. Causa
raíz medida (perfilado real, guía 474197): dos reconciliaciones GLOBALES
completas corrieron 75s aparte para la misma ingesta, con conteos de
salida IDÉNTICOS (234/202/1/31) -- prueba de que la segunda no tenía
nada nuevo que hacer. El origen (Desktop llamando `cargarAutomatico`
justo después de una ingesta ya reconciliada focal) se corrige en el
repo Desktop (ver `test/eliminar_reconciliacion_duplicada_ingesta.test.js`
en Atlas-Viajes-Desktop-Restaurado). Este archivo prueba la protección
de respaldo, del lado Motor: `reconciliar_estado_derivado` no repite la
batería pesada cuando una corrida GLOBAL reciente, con la MISMA huella
byte a byte (dataset + pendientes técnicos + decisiones aplicadas +
versión de reglas/capacidades), ya demostró el mismo resultado.

Todo el entorno es scratch (`tmp_path`), proveedor 100% simulado (nunca
red real) -- reutiliza el fixture ya auditado de `test_ingesta_focal_p0.py`."""
from __future__ import annotations

import csv
from datetime import timedelta

from atlas_core.reconciliacion_estado_derivado import reconciliar_estado_derivado
from tests.test_ingesta_focal_p0 import RELOJ, _entorno_focal, _fila_backlog, _fila_nueva


def _reloj_mas(segundos):
    return lambda: RELOJ() + timedelta(seconds=segundos)


def test_e1_segunda_reconciliacion_global_identica_no_repite_bateria_pesada(tmp_path):
    filas_backlog = [_fila_backlog(f"OLD{i:03d}", None) for i in range(1, 4)]
    filas_nuevas = [_fila_nueva("NEW001", None)]
    ent = _entorno_focal(tmp_path, filas_backlog=filas_backlog, filas_nuevas=filas_nuevas)

    proveedor = None
    from atlas_core.rutas.proveedor import ProveedorRutasSimulado
    proveedor = ProveedorRutasSimulado()

    primera = reconciliar_estado_derivado(
        raiz_atlas=ent["raiz"], reloj=RELOJ, proveedor_rutas=proveedor, proveedor_rutas_fallback=proveedor,
        guias_objetivo=None,
    )
    assert primera["reconciliado"] is True
    llamadas_tras_primera = proveedor.llamadas_geocodificacion + proveedor.llamadas_ruta
    assert llamadas_tras_primera > 0  # la primera SÍ hizo trabajo real (backlog + nueva)

    # Segunda llamada, 10s después (misma ventana de idempotencia, nada
    # cambió en disco entre medio) -- exactamente el escenario medido en
    # 474197 (~75s aparte, ambas dentro de la ventana de 300s).
    segunda = reconciliar_estado_derivado(
        raiz_atlas=ent["raiz"], reloj=_reloj_mas(10), proveedor_rutas=proveedor, proveedor_rutas_fallback=proveedor,
        guias_objetivo=None,
    )
    assert segunda["reconciliado"] is False
    # En este fixture (cooldown de 24h, un solo intento real ya
    # consumido), el corte YA EXISTENTE (`VERSION_VIGENTE_SIN_REINTENTO_
    # PENDIENTE`) también puede disparar primero -- cuál de los dos
    # motivos de "no hay nada que hacer" es un detalle de implementación;
    # lo que importa (y se prueba también de forma aislada más abajo, ver
    # `test_e1b_*`) es el resultado observable: cero llamadas nuevas.
    assert segunda["motivo"] in (
        "IDEMPOTENTE_RECONCILIACION_GLOBAL_RECIENTE_SIN_CAMBIOS",
        "VERSION_VIGENTE_SIN_REINTENTO_PENDIENTE",
    )
    # Cero llamadas NUEVAS al proveedor -- la batería pesada no se repitió.
    assert proveedor.llamadas_geocodificacion + proveedor.llamadas_ruta == llamadas_tras_primera


def test_e1b_helper_idempotencia_compara_huella_byte_a_byte(tmp_path):
    """Prueba unitaria y directa de `_reconciliacion_global_reciente_
    identica` -- el helper que SÍ dispara el nuevo motivo
    `IDEMPOTENTE_RECONCILIACION_GLOBAL_RECIENTE_SIN_CAMBIOS` incluso
    cuando `por_reintentar` no está vacío (el caso real medido en
    474197: backlog cooldown-eligible que, sin este corte, dispara la
    batería completa igual aunque el resultado vaya a ser idéntico)."""
    import json
    from datetime import datetime, timezone

    from atlas_core.reconciliacion_estado_derivado import (
        VERSION_ESTADO_DERIVADO, _reconciliacion_global_reciente_identica,
    )

    filas_backlog = [_fila_backlog(f"OLD{i:03d}", None) for i in range(1, 3)]
    filas_nuevas = [_fila_nueva("NEW001", None)]
    ent = _entorno_focal(tmp_path, filas_backlog=filas_backlog, filas_nuevas=filas_nuevas)

    instante = RELOJ()
    huella = {
        "dataset_sha256": "abc123",
        "pendientes_tecnicos_sha256": "def456",
        "decisiones_aplicadas_sha256": "AUSENTE",
        "version_estado_derivado": 24,
        "versiones_capacidades": {},
    }
    respaldo = ent["raiz"] / "respaldos" / f"reconciliacion_estado_derivado_v{VERSION_ESTADO_DERIVADO}_20260921_163315_000000"
    respaldo.mkdir(parents=True)
    (respaldo / "manifest.json").write_text(json.dumps({
        "version_origen": 24, "version_destino": 24,
        "creado_en": instante.isoformat(), "alcance": "GLOBAL", "huella_idempotencia": huella,
    }), encoding="utf-8")

    # 1) Huella idéntica, dentro de la ventana -> devuelve el respaldo.
    encontrado = _reconciliacion_global_reciente_identica(
        raiz=ent["raiz"], instante=instante + timedelta(seconds=75), huella_idempotencia_actual=dict(huella),
    )
    assert encontrado == respaldo.name

    # 2) Huella distinta (algo cambió de verdad) -> no dispara.
    huella_distinta = {**huella, "dataset_sha256": "OTRO_HASH"}
    assert _reconciliacion_global_reciente_identica(
        raiz=ent["raiz"], instante=instante + timedelta(seconds=75), huella_idempotencia_actual=huella_distinta,
    ) is None

    # 3) Fuera de la ventana (10 minutos después) -> no dispara aunque la
    #    huella coincida -- nunca se convierte en un caché de largo plazo.
    assert _reconciliacion_global_reciente_identica(
        raiz=ent["raiz"], instante=instante + timedelta(minutes=10), huella_idempotencia_actual=dict(huella),
    ) is None


def test_e2_dataset_invalidado_recalcula_de_verdad(tmp_path):
    """Si algo SÍ cambió (una guía nueva se agrega al dataset), la
    protección de idempotencia no debe enmascararlo -- la huella ya no
    coincide y la batería vuelve a correr."""
    filas_backlog = [_fila_backlog(f"OLD{i:03d}", None) for i in range(1, 3)]
    filas_nuevas = [_fila_nueva("NEW001", None)]
    ent = _entorno_focal(tmp_path, filas_backlog=filas_backlog, filas_nuevas=filas_nuevas)

    from atlas_core.rutas.proveedor import ProveedorRutasSimulado
    proveedor = ProveedorRutasSimulado()

    primera = reconciliar_estado_derivado(
        raiz_atlas=ent["raiz"], reloj=RELOJ, proveedor_rutas=proveedor, proveedor_rutas_fallback=proveedor,
        guias_objetivo=None,
    )
    assert primera["reconciliado"] is True
    llamadas_tras_primera = proveedor.llamadas_geocodificacion + proveedor.llamadas_ruta

    # Invalida el dataset: agrega una guía nueva directamente al CSV
    # (simula una ingesta real entre medio) -- dataset_sha256 cambia.
    from atlas_core.procesamiento_masivo import COLUMNAS
    filas_actuales = list(csv.DictReader(ent["dataset"].open(encoding="utf-8-sig", newline=""), delimiter=";"))
    nueva_fila = _fila_nueva("NEW002", ent["planta_id"])
    filas_actuales.append(nueva_fila)
    with ent["dataset"].open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNAS, delimiter=";")
        w.writeheader()
        w.writerows(filas_actuales)

    segunda = reconciliar_estado_derivado(
        raiz_atlas=ent["raiz"], reloj=_reloj_mas(10), proveedor_rutas=proveedor, proveedor_rutas_fallback=proveedor,
        guias_objetivo=None,
    )
    assert segunda["reconciliado"] is True
    assert segunda.get("motivo") != "IDEMPOTENTE_RECONCILIACION_GLOBAL_RECIENTE_SIN_CAMBIOS"
    # Se hicieron llamadas NUEVAS -- la guía agregada (y el backlog, en
    # alcance global) sí se procesaron de verdad.
    assert proveedor.llamadas_geocodificacion + proveedor.llamadas_ruta > llamadas_tras_primera


def test_e3_una_corrida_focal_nunca_enmascara_el_barrido_global_que_sigue(tmp_path):
    """La protección de idempotencia SOLO compara GLOBAL-contra-GLOBAL
    (ver `alcance` en el manifiesto). Una reconciliación FOCAL reciente
    (misma huella de dataset/pendientes/decisiones) NO debe hacer que una
    reconciliación GLOBAL posterior se salte el backlog -- son alcances
    distintos, "mismos insumos" no implica "mismo resultado" entre
    ellos."""
    filas_backlog = [_fila_backlog(f"OLD{i:03d}", None) for i in range(1, 4)]
    filas_nuevas = [_fila_nueva("NEW001", None)]
    ent = _entorno_focal(tmp_path, filas_backlog=filas_backlog, filas_nuevas=filas_nuevas)

    from atlas_core.rutas.proveedor import ProveedorRutasSimulado
    proveedor = ProveedorRutasSimulado()

    focal = reconciliar_estado_derivado(
        raiz_atlas=ent["raiz"], reloj=RELOJ, proveedor_rutas=proveedor, proveedor_rutas_fallback=proveedor,
        guias_objetivo={"NEW001"},
    )
    assert focal["reconciliado"] is True
    llamadas_tras_focal = proveedor.llamadas_geocodificacion + proveedor.llamadas_ruta
    assert llamadas_tras_focal == 1  # sólo NEW001, backlog intacto (P0 previo)

    # 10s después, alguien pide una reconciliación GLOBAL explícita
    # (mantenimiento) -- el backlog de 3 guías AÚN no fue tocado y debe
    # recorrerse de verdad, sin que la corrida focal previa lo enmascare.
    global_ = reconciliar_estado_derivado(
        raiz_atlas=ent["raiz"], reloj=_reloj_mas(10), proveedor_rutas=proveedor, proveedor_rutas_fallback=proveedor,
        guias_objetivo=None,
    )
    assert global_["reconciliado"] is True
    assert global_.get("motivo") != "IDEMPOTENTE_RECONCILIACION_GLOBAL_RECIENTE_SIN_CAMBIOS"
    assert proveedor.llamadas_geocodificacion + proveedor.llamadas_ruta > llamadas_tras_focal
