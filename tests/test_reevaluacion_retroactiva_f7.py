"""Bloque REEVALUACIÓN RETROACTIVA UNIVERSAL -- una mejora declarada
(subir la `version` de un dominio en `REGISTRO_CAPACIDADES`) debe poder
propagarse automáticamente a los viajes que sigan pendientes de ESE
dominio, reutilizando los revalidadores existentes, sin OCR masivo, sin
inventar soluciones y de forma idempotente.
"""
from __future__ import annotations

import dataclasses

import pytest

from atlas_core import capacidades_reevaluacion as cap


def _bump(dominio, delta=1):
    """Devuelve un REGISTRO_CAPACIDADES con la versión de `dominio` subida."""
    reg = dict(cap.REGISTRO_CAPACIDADES)
    reg[dominio] = dataclasses.replace(reg[dominio], version=reg[dominio].version + delta)
    return reg


def _dec(decision_id, tipo, guia):
    return {"decision_id": decision_id, "tipo": tipo, "documento": {"numero_guia": guia}}


def _tec(guia, motivo):
    return {"numero_guia": guia, "motivo_actual": motivo}


# ==========================================================================
# 1-2. Una mejora de CLIENTE / VEHICULO reevalúa SÓLO su dominio
# ==========================================================================


def test_1_mejora_cliente_solo_avanza_cliente(monkeypatch):
    monkeypatch.setattr(cap, "REGISTRO_CAPACIDADES", _bump(cap.DOMINIO_CLIENTE))
    persistidas = cap.versiones_actuales()  # todo "al día" salvo el bump
    persistidas[cap.DOMINIO_CLIENTE] -= 1
    avanzadas = cap.capacidades_avanzadas(persistidas)
    assert set(avanzadas) == {cap.DOMINIO_CLIENTE}
    assert avanzadas[cap.DOMINIO_CLIENTE][1] == cap.REGISTRO_CAPACIDADES[cap.DOMINIO_CLIENTE].version


def test_2_mejora_vehiculo_solo_avanza_vehiculo(monkeypatch):
    monkeypatch.setattr(cap, "REGISTRO_CAPACIDADES", _bump(cap.DOMINIO_VEHICULO))
    persistidas = cap.versiones_actuales()
    persistidas[cap.DOMINIO_VEHICULO] -= 1
    assert set(cap.capacidades_avanzadas(persistidas)) == {cap.DOMINIO_VEHICULO}


# ==========================================================================
# 3. Una mejora de GEOGRAFIA selecciona los pendientes geográficos
#    (sin resolverlos: eso lo deciden los revalidadores con evidencia real)
# ==========================================================================


def test_3_geografia_mapea_pendientes_tecnicos_geo():
    for motivo in (
        "GEOCODIFICACION_DIRECCION_NO_ENCONTRADA", "COORDENADA_NO_CONFIRMADA(5)",
        "GEOCODIFICACION_NUMERO_INCOMPATIBLE: 15 != 1545", "CONFIANZA_INSUFICIENTE",
        "MULTIPLES_UBICACIONES_DISPERSAS(3)",
    ):
        assert cap.DOMINIO_GEOGRAFIA in cap.dominios_de_motivo_tecnico(motivo)
    # un motivo ajeno no cae en GEOGRAFIA
    assert cap.dominios_de_motivo_tecnico("CONTRADICCION_OPERACIONAL_ORIGEN") == frozenset({cap.DOMINIO_ORIGEN})


def test_3b_geografia_no_resuelve_artificialmente(monkeypatch):
    monkeypatch.setattr(cap, "REGISTRO_CAPACIDADES", _bump(cap.DOMINIO_GEOGRAFIA))
    tecnicos = [_tec("464395", "GEOCODIFICACION_DIRECCION_NO_ENCONTRADA"),
               _tec("464740", "COORDENADA_NO_CONFIRMADA(5)")]
    r = cap.resumen_reevaluacion(
        avanzadas={cap.DOMINIO_GEOGRAFIA: (1, 2)},
        decisiones_antes=[], decisiones_despues=[],
        tecnicos_antes=tecnicos, tecnicos_despues=list(tecnicos),  # sin cambio
        duracion_ms=1,
    )
    d = r["por_dominio"][cap.DOMINIO_GEOGRAFIA]
    assert d["pendientes_tecnicos_en_alcance_antes"] == 2
    assert d["pendientes_tecnicos_en_alcance_despues"] == 2
    assert d["pendientes_tecnicos_retirados"] == 0
    assert r["pendientes_tecnicos_retirados_total"] == 0


# ==========================================================================
# 4. Un viaje OK/CONFIRMADO (sin decisión ni pendiente técnico) no se toca
# ==========================================================================


def test_4_viaje_confirmado_no_entra_en_ningun_alcance():
    r = cap.resumen_reevaluacion(
        avanzadas={cap.DOMINIO_CLIENTE: (1, 2), cap.DOMINIO_OBRA: (1, 2)},
        decisiones_antes=[], decisiones_despues=[],
        tecnicos_antes=[], tecnicos_despues=[],
        duracion_ms=1,
    )
    assert r["viajes_pendientes_evaluados"] == 0
    assert r["decisiones_retiradas_total"] == 0
    for info in r["por_dominio"].values():
        assert info["decisiones_en_alcance_antes"] == 0


# ==========================================================================
# 5. Mejora irrelevante -> no dispara reevaluación
# ==========================================================================


def test_5_sin_avance_no_hay_reevaluacion():
    assert cap.capacidades_avanzadas(cap.versiones_actuales()) == {}


def test_5b_manifiesto_sin_estampar_difiere_a_la_migracion():
    # Un manifiesto que nunca estampó `versiones_capacidades` NO dispara el
    # trigger por sí solo (lo hace la migración de RULESET_VERSION, que
    # además deja el primer estampado).
    assert cap.capacidades_avanzadas(None) == {}
    assert cap.capacidades_avanzadas({}) == {}


# ==========================================================================
# 6. Una decisión resuelta desaparece canónicamente y se atribuye
# ==========================================================================


def test_6_decision_resuelta_se_cuenta_y_atribuye():
    antes = [_dec("d1", "CLIENTE_CANDIDATO", "472477"), _dec("d2", "VEHICULO_DESCONOCIDO", "472477")]
    despues = [_dec("d2", "VEHICULO_DESCONOCIDO", "472477")]  # d1 (cliente) resuelta
    r = cap.resumen_reevaluacion(
        avanzadas={cap.DOMINIO_CLIENTE: (1, 2), cap.DOMINIO_VEHICULO: (1, 2)},
        decisiones_antes=antes, decisiones_despues=despues,
        tecnicos_antes=[], tecnicos_despues=[], duracion_ms=1,
    )
    assert r["decisiones_retiradas_total"] == 1
    assert r["por_dominio"][cap.DOMINIO_CLIENTE]["decisiones_retiradas"] == 1
    assert r["por_dominio"][cap.DOMINIO_CLIENTE]["decisiones_retiradas_guias"] == ["472477"]
    assert r["por_dominio"][cap.DOMINIO_VEHICULO]["decisiones_retiradas"] == 0


# ==========================================================================
# 7. Una decisión aún ambigua permanece
# ==========================================================================


def test_7_decision_ambigua_permanece():
    antes = [_dec("d2", "VEHICULO_DESCONOCIDO", "472477")]
    r = cap.resumen_reevaluacion(
        avanzadas={cap.DOMINIO_VEHICULO: (1, 2)},
        decisiones_antes=antes, decisiones_despues=list(antes),  # sin cambio
        tecnicos_antes=[], tecnicos_despues=[], duracion_ms=1,
    )
    d = r["por_dominio"][cap.DOMINIO_VEHICULO]
    assert d["decisiones_en_alcance_despues"] == 1
    assert d["decisiones_retiradas"] == 0
    assert r["sin_cambio"] == 1


# ==========================================================================
# 8. INCOMPLETO_TECNICO puede volver a evaluarse ante una nueva regla
# ==========================================================================


def test_8_nueva_regla_geografia_habilita_reevaluacion_de_tecnicos(monkeypatch):
    monkeypatch.setattr(cap, "REGISTRO_CAPACIDADES", _bump(cap.DOMINIO_GEOGRAFIA))
    persistidas = cap.versiones_actuales()
    persistidas[cap.DOMINIO_GEOGRAFIA] -= 1
    avanzadas = cap.capacidades_avanzadas(persistidas)
    assert cap.DOMINIO_GEOGRAFIA in avanzadas  # el trigger entrará y re-barrerá técnicos


# ==========================================================================
# 9. Idempotencia
# ==========================================================================


def test_9_idempotente():
    v = cap.versiones_actuales()
    assert cap.capacidades_avanzadas(v) == {}
    # y tras un avance + estampado, vuelve a quedar en cero
    v2 = dict(v)
    v2[cap.DOMINIO_CLIENTE] -= 1
    assert set(cap.capacidades_avanzadas(v2)) == {cap.DOMINIO_CLIENTE}
    v2[cap.DOMINIO_CLIENTE] = cap.REGISTRO_CAPACIDADES[cap.DOMINIO_CLIENTE].version
    assert cap.capacidades_avanzadas(v2) == {}


# ==========================================================================
# 10. Ninguna pérdida de decisiones humanas / ledger
# ==========================================================================


def test_10_una_decision_que_sigue_presente_nunca_se_marca_retirada():
    antes = [_dec("d1", "CLIENTE_CANDIDATO", "472037"), _dec("d2", "OBRA_DESCONOCIDA", "472414")]
    despues = list(antes)  # ninguna se retira (evidencia insuficiente)
    r = cap.resumen_reevaluacion(
        avanzadas={cap.DOMINIO_CLIENTE: (1, 2), cap.DOMINIO_OBRA: (1, 2)},
        decisiones_antes=antes, decisiones_despues=despues,
        tecnicos_antes=[], tecnicos_despues=[], duracion_ms=1,
    )
    assert r["decisiones_retiradas_total"] == 0
    assert r["por_dominio"][cap.DOMINIO_CLIENTE]["decisiones_retiradas"] == 0
    assert r["por_dominio"][cap.DOMINIO_OBRA]["decisiones_retiradas"] == 0


def test_10b_decision_de_dominio_no_avanzado_no_se_atribuye():
    # d1 es DESTINO (no avanzó); desaparece por otra vía -> se cuenta en el
    # total pero NO se atribuye a CLIENTE (el único dominio avanzado).
    antes = [_dec("d1", "DESTINO_SIN_CONFIRMAR", "472008"), _dec("d2", "CLIENTE_CANDIDATO", "9")]
    despues = [_dec("d2", "CLIENTE_CANDIDATO", "9")]
    r = cap.resumen_reevaluacion(
        avanzadas={cap.DOMINIO_CLIENTE: (1, 2)},
        decisiones_antes=antes, decisiones_despues=despues,
        tecnicos_antes=[], tecnicos_despues=[], duracion_ms=1,
    )
    assert r["decisiones_retiradas_total"] == 1
    assert r["por_dominio"][cap.DOMINIO_CLIENTE]["decisiones_retiradas"] == 0


# ==========================================================================
# Contrato del registro
# ==========================================================================


def test_registro_cubre_los_dominios_declarados():
    esperados = {
        "CLIENTE", "CHOFER", "VEHICULO", "OBRA", "DESTINO", "GEOGRAFIA",
        "ORIGEN", "MATERIAL", "HORARIOS", "ROUTING", "EXTRACCION", "B1", "CATALOGOS",
    }
    assert set(cap.REGISTRO_CAPACIDADES) == esperados
    for dominio, c in cap.REGISTRO_CAPACIDADES.items():
        assert c.dominio == dominio
        assert c.version >= 1
        assert c.descripcion
