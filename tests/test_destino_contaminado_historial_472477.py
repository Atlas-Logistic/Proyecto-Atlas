"""Regresión explícita -- CONTAMINACIÓN DE DESTINO POR HISTORIAL (Codex).

Caso testigo: guía 472477 / transporte 0000354870 (PRODALAM SA).
Documento real: "PASAJE ISRAEL 1303 CHILLAN CHILLAN".
Atlas lo contaminó con "SAN LUIS 1201 QUILICURA" tomado de 472623/472624
(SODIMAC SA, transporte 0000355433) porque
`_resolver_destinos_contaminados_por_historial`:
  1. usaba `obra_destino="No encontrado"` como clave de agrupación válida;
  2. no exigía el mismo cliente;
  3. contaba dos guías del MISMO transporte como dos pruebas;
  4. sobrescribía `despachar_a_crudo` (evidencia documental).

Este archivo fija las cuatro correcciones y la reversión automática.
"""
from __future__ import annotations

import csv

from atlas_core.procesamiento_masivo import (
    COLUMNAS,
    _resolver_destinos_contaminados_por_historial,
    _revertir_promociones_historial_contaminado,
)

_CONTAMINADO = "DESTINO_CONTAMINADO_POR_OTRA_SECCION"


def _fila(**over):
    fila = {c: "" for c in COLUMNAS}
    fila.update(estado_procesamiento="OK")
    fila.update(over)
    return fila


def _escribir(ruta, filas):
    with ruta.open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNAS, delimiter=";")
        w.writeheader()
        w.writerows(filas)


def _leer(ruta):
    with ruta.open(newline="", encoding="utf-8-sig") as fh:
        return {f["numero_guia"]: f for f in csv.DictReader(fh, delimiter=";")}


def _hermanas_san_luis(**over):
    """472623 / 472624 -- MISMO transporte 0000355433, cliente SODIMAC,
    obra 'No encontrado', ruta ya calculada a SAN LUIS 1201 QUILICURA."""
    base = dict(
        cliente="SODIMAC SA", obra_destino="No encontrado",
        despachar_a_crudo="SAN LUIS 1201 QUILICURA",
        direccion_entrega="SAN LUIS 1201 QUILICURA",
        localidad_entrega="Quilicura", region_entrega="Metropolitana",
        estado_ruta="RUTA_CALCULADA", estado_entrega="RESUELTO",
        distancia_km="16.3682", duracion_min="22.43", proveedor_ruta="openrouteservice",
        planta_origen_id="22429e82", indicador_revision="OK",
        estado_documental="OK", estado_operacional="OK",
    )
    base.update(over)
    return [
        _fila(archivo="472624.jpeg", numero_guia="472624", numero_transporte="0000355433", **base),
        _fila(archivo="472623.jpeg", numero_guia="472623", numero_transporte="0000355433", **base),
    ]


def _fila_472477(**over):
    base = dict(
        archivo="472477.jpeg", numero_guia="472477", numero_transporte="0000354870",
        cliente="PRODALAM SA", obra_destino="No encontrado",
        despachar_a_crudo="SAN LUIS 1201 QUILICURA",  # ya contaminado
        motivos_revision_documento="MATERIAL_AUSENTE",
        estado_ruta="REQUIERE_REVISION", estado_operacional="REQUIERE_REVISION",
        indicador_revision="OK",
    )
    base.update(over)
    return _fila(**base)


# ============================================================
# 1. El resolver NUNCA promueve el caso 472477
# ============================================================


def test_472477_obra_placeholder_no_habilita_promocion(tmp_path):
    ruta = tmp_path / "guias.csv"
    _escribir(ruta, [
        _fila_472477(motivos_revision_documento=f"MATERIAL_AUSENTE | {_CONTAMINADO}",
                     despachar_a_crudo="1303 PASAJE ISRAEL"),
        *_hermanas_san_luis(),
    ])
    assert _resolver_destinos_contaminados_por_historial(ruta, {"472477.jpeg"}) == 0
    fila = _leer(ruta)["472477"]
    assert _CONTAMINADO in fila["motivos_revision_documento"]
    assert fila["direccion_entrega"] == ""
    assert "SAN LUIS 1201 QUILICURA" not in fila["despachar_a_crudo"]


def test_472477_distinto_cliente_no_promueve_aunque_la_obra_fuera_real(tmp_path):
    ruta = tmp_path / "guias.csv"
    comun = dict(
        obra_destino="EMPRESA CONST SIGRO", despachar_a_crudo="SAN LUIS 1201 QUILICURA",
        direccion_entrega="SAN LUIS 1201 QUILICURA", localidad_entrega="Quilicura",
        estado_ruta="RUTA_CALCULADA", distancia_km="16", duracion_min="22", planta_origen_id="p1",
    )
    _escribir(ruta, [
        _fila_472477(obra_destino="EMPRESA CONST SIGRO",
                     motivos_revision_documento=_CONTAMINADO,
                     despachar_a_crudo="RUT 93.772.000-9"),
        # hermanas con DOS transportes distintos -> aísla el gate de cliente
        _fila(archivo="h1.jpeg", numero_guia="900001", numero_transporte="0000900001",
              cliente="SODIMAC SA", **comun),
        _fila(archivo="h2.jpeg", numero_guia="900002", numero_transporte="0000900002",
              cliente="SODIMAC SA", **comun),
    ])
    assert _resolver_destinos_contaminados_por_historial(ruta, {"472477.jpeg"}) == 0
    fila = _leer(ruta)["472477"]
    assert fila["direccion_entrega"] == ""
    assert fila["despachar_a_crudo"] == "RUT 93.772.000-9"  # intacto (no se tocó)


def test_dos_guias_del_mismo_transporte_no_son_dos_pruebas(tmp_path):
    ruta = tmp_path / "guias.csv"
    _escribir(ruta, [
        _fila_472477(cliente="SODIMAC SA", obra_destino="BODEGA CENTRAL SPA",
                     motivos_revision_documento=_CONTAMINADO, despachar_a_crudo="14-08-2026 RECEPCION"),
        *_hermanas_san_luis(obra_destino="BODEGA CENTRAL SPA"),  # ambas transporte 0000355433
    ])
    assert _resolver_destinos_contaminados_por_historial(ruta, {"472477.jpeg"}) == 0
    assert _leer(ruta)["472477"]["direccion_entrega"] == ""


# ============================================================
# 2. Promoción válida -- sólo el campo operacional, nunca el documental
# ============================================================


def test_promocion_valida_no_toca_despachar_a_crudo(tmp_path):
    ruta = tmp_path / "guias.csv"
    _escribir(ruta, [
        _fila_472477(cliente="ACME SA", obra_destino="OBRA ACME NORTE",
                     motivos_revision_documento=_CONTAMINADO,
                     despachar_a_crudo="FECHA LLEGADA 24-08-2026 GUIA"),  # fragmento no creíble
        _fila(archivo="h1.jpeg", numero_guia="900001", numero_transporte="0000900001",
              cliente="ACME SA", obra_destino="OBRA ACME NORTE",
              despachar_a_crudo="CAMINO REAL 4500 LAMPA", direccion_entrega="CAMINO REAL 4500 LAMPA",
              estado_ruta="RUTA_CALCULADA", distancia_km="12", duracion_min="18", planta_origen_id="p1"),
        _fila(archivo="h2.jpeg", numero_guia="900002", numero_transporte="0000900002",
              cliente="ACME SA", obra_destino="OBRA ACME NORTE",
              despachar_a_crudo="CAMINO REAL 4500 LAMPA", direccion_entrega="CAMINO REAL 4500 LAMPA",
              estado_ruta="RUTA_CALCULADA", distancia_km="12", duracion_min="18", planta_origen_id="p1"),
    ])
    assert _resolver_destinos_contaminados_por_historial(ruta, {"472477.jpeg"}) == 1
    fila = _leer(ruta)["472477"]
    assert fila["direccion_entrega"] == "CAMINO REAL 4500 LAMPA"
    # Codex criterio 1: la propuesta histórica NUNCA entra a despachar_a_crudo
    assert fila["despachar_a_crudo"] != "CAMINO REAL 4500 LAMPA"
    assert fila["despachar_a_crudo"] == ""  # el fragmento contaminado se vacía
    assert _CONTAMINADO not in fila["motivos_revision_documento"]


def test_promocion_se_abstiene_si_contradice_calle_numero_o_ciudad_documental(tmp_path):
    ruta = tmp_path / "guias.csv"
    _escribir(ruta, [
        _fila_472477(cliente="ACME SA", obra_destino="OBRA ACME NORTE",
                     motivos_revision_documento=_CONTAMINADO,
                     # documental CLARO y distinto: calle, número y ciudad
                     despachar_a_crudo="PASAJE ISRAEL 1303 CHILLAN CHILLAN"),
        _fila(archivo="h1.jpeg", numero_guia="900001", numero_transporte="0000900001",
              cliente="ACME SA", obra_destino="OBRA ACME NORTE",
              despachar_a_crudo="SAN LUIS 1201 QUILICURA", direccion_entrega="SAN LUIS 1201 QUILICURA",
              localidad_entrega="Quilicura", estado_ruta="RUTA_CALCULADA",
              distancia_km="12", duracion_min="18", planta_origen_id="p1"),
        _fila(archivo="h2.jpeg", numero_guia="900002", numero_transporte="0000900002",
              cliente="ACME SA", obra_destino="OBRA ACME NORTE",
              despachar_a_crudo="SAN LUIS 1201 QUILICURA", direccion_entrega="SAN LUIS 1201 QUILICURA",
              localidad_entrega="Quilicura", estado_ruta="RUTA_CALCULADA",
              distancia_km="12", duracion_min="18", planta_origen_id="p1"),
    ])
    assert _resolver_destinos_contaminados_por_historial(ruta, {"472477.jpeg"}) == 0
    fila = _leer(ruta)["472477"]
    assert fila["despachar_a_crudo"] == "PASAJE ISRAEL 1303 CHILLAN CHILLAN"  # intacto
    assert fila["direccion_entrega"] == ""


# ============================================================
# 3. Reversión automática de una contaminación YA aplicada
# ============================================================


def test_reversion_deshace_la_contaminacion_ya_persistida_de_472477(tmp_path):
    ruta = tmp_path / "guias.csv"
    _escribir(ruta, [
        # 472477 tal como quedó en producción: despachar inyectado, SIN
        # motivo (la regla vieja ya lo removió), sin ruta.
        _fila_472477(despachar_a_crudo="SAN LUIS 1201 QUILICURA",
                     motivos_revision_documento="MATERIAL_AUSENTE",
                     direccion_entrega="", indicador_revision="OK"),
        *_hermanas_san_luis(),
    ])
    assert _revertir_promociones_historial_contaminado(ruta) == 1
    fila = _leer(ruta)["472477"]
    assert fila["despachar_a_crudo"] == ""                      # inyección deshecha
    assert _CONTAMINADO in fila["motivos_revision_documento"]   # re-marcado
    assert fila["indicador_revision"] == "REVISAR"
    assert fila["estado_operacional"] == "REQUIERE_REVISION"
    # idempotente
    assert _revertir_promociones_historial_contaminado(ruta) == 0


def test_reversion_no_toca_una_convergencia_legitima(tmp_path):
    """Mismo cliente, obra real, DOS transportes distintos, ruta OK ->
    NO es la contaminación de Codex; la reversión no la altera."""
    ruta = tmp_path / "guias.csv"
    filas = [
        _fila(archivo="a.jpeg", numero_guia="800001", numero_transporte="0000800001",
              cliente="ARMACERO MATCO SA", obra_destino="ARMACERO MATCO SA",
              despachar_a_crudo="SANTA ISABEL 585 SANTIAGO LAMPA",
              direccion_entrega="SANTA ISABEL 585 SANTIAGO LAMPA",
              estado_ruta="RUTA_CALCULADA", estado_entrega="RESUELTO",
              distancia_km="30", duracion_min="40", planta_origen_id="p1",
              indicador_revision="OK", estado_documental="OK", estado_operacional="OK"),
        _fila(archivo="b.jpeg", numero_guia="800002", numero_transporte="0000800002",
              cliente="ARMACERO MATCO SA", obra_destino="ARMACERO MATCO SA",
              despachar_a_crudo="SANTA ISABEL 585 SANTIAGO LAMPA",
              direccion_entrega="SANTA ISABEL 585 SANTIAGO LAMPA",
              estado_ruta="RUTA_CALCULADA", estado_entrega="RESUELTO",
              distancia_km="30", duracion_min="40", planta_origen_id="p1",
              indicador_revision="OK", estado_documental="OK", estado_operacional="OK"),
    ]
    _escribir(ruta, filas)
    assert _revertir_promociones_historial_contaminado(ruta) == 0
    for g in ("800001", "800002"):
        assert _leer(ruta)[g]["despachar_a_crudo"] == "SANTA ISABEL 585 SANTIAGO LAMPA"
