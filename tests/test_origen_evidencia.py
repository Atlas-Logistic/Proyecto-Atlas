"""Bloque ORIGEN OPERACIONAL V2 -- fusión de evidencia MOBILE/DOCUMENTO
cruzada con reglas de compatibilidad planta<->categoría configurables.
Fixtures sintéticas propias, universales (nunca acopladas a MBT/AZA
salvo en los nombres de ejemplo, que son datos, no lógica)."""
from __future__ import annotations

from datetime import datetime, timezone

from atlas_core.catalogo_plantas import Planta
from atlas_core.rutas.origen_evidencia import (
    COMPATIBLE,
    FUENTE_DOCUMENTO,
    FUENTE_MOBILE,
    INCOMPATIBLE,
    MOTIVO_CONTRADICCION_OPERACIONAL,
    SIN_REGLA,
    evaluar_compatibilidad_planta_categoria,
    fusionar_evidencia_origen,
)

_AHORA = datetime.now(timezone.utc).isoformat()


def _planta(nombre: str, categorias: tuple[str, ...] = (), planta_id: str | None = None) -> Planta:
    return Planta(
        planta_id=planta_id or nombre.replace(" ", "_"), nombre=nombre,
        nombre_normalizado=nombre.upper(), direccion="", comuna="", region="", pais="CL",
        latitud=None, longitud=None, estado_calidad="CONFIRMADA", estado_vigencia="ACTIVA",
        fuente="TEST", observacion="", fecha_creacion=_AHORA, fecha_modificacion=_AHORA,
        categorias_permitidas=categorias,
    )


COLINA = _planta("AZA COLINA", ("BARRAS", "ROLLOS"))
RENCA = _planta("AZA RENCA", ("ANGULOS",))
SIN_REGLAS = _planta("PLANTA SIN REGLAS")


# --- Bloque 3/6 -- evaluación de compatibilidad, degradación segura ---

def test_compatibilidad_sin_planta_es_sin_regla():
    assert evaluar_compatibilidad_planta_categoria(None, "BARRAS") == SIN_REGLA


def test_compatibilidad_sin_categorias_configuradas_es_sin_regla():
    assert evaluar_compatibilidad_planta_categoria(SIN_REGLAS, "BARRAS") == SIN_REGLA


def test_compatibilidad_sin_categoria_informada_es_sin_regla():
    assert evaluar_compatibilidad_planta_categoria(COLINA, None) == SIN_REGLA
    assert evaluar_compatibilidad_planta_categoria(COLINA, "") == SIN_REGLA


def test_compatibilidad_categoria_permitida():
    assert evaluar_compatibilidad_planta_categoria(COLINA, "BARRAS") == COMPATIBLE
    assert evaluar_compatibilidad_planta_categoria(COLINA, "barras") == COMPATIBLE  # nunca sensible a mayúsculas


def test_compatibilidad_categoria_no_permitida():
    assert evaluar_compatibilidad_planta_categoria(COLINA, "ANGULOS") == INCOMPATIBLE
    assert evaluar_compatibilidad_planta_categoria(RENCA, "BARRAS") == INCOMPATIBLE


# --- Bloque M2-A -- causa raíz real (472624, Mobile): "NO DETERMINADO"
# (el centinela real que persiste `atlas_core.clasificador_material`
# cuando el OCR no logró determinar el material) NUNCA es una categoría
# real -- ausencia de evidencia != evidencia de incompatibilidad. ---

def test_compatibilidad_categoria_no_determinada_es_sin_regla_no_incompatible():
    """Caso real 472624: OCR no determinó material -- ninguna planta
    puede quedar marcada INCOMPATIBLE sólo por eso."""
    assert evaluar_compatibilidad_planta_categoria(COLINA, "NO DETERMINADO") == SIN_REGLA
    assert evaluar_compatibilidad_planta_categoria(RENCA, "NO DETERMINADO") == SIN_REGLA
    assert evaluar_compatibilidad_planta_categoria(COLINA, "no determinado") == SIN_REGLA  # sin distinguir mayúsculas


# --- Caso real 472593 -- Mobile COLINA + BARRAS + encabezado societario RENCA ---

def test_caso_real_472593_mobile_colina_no_es_sobrescrito_por_encabezado_renca():
    r = fusionar_evidencia_origen(planta_mobile=COLINA, planta_documento=RENCA, categoria="BARRAS")
    assert r.contradiccion is False
    assert r.planta is COLINA
    assert r.fuente == FUENTE_MOBILE
    assert r.compatibilidad_mobile == COMPATIBLE
    assert r.compatibilidad_documento == INCOMPATIBLE


# --- Contradicción real: una sola fuente (Mobile) viola la regla, sin
# corroboración -- nunca se corrige sola ni se acepta a ciegas ---

def test_mobile_renca_barras_regla_incompatible_es_contradiccion():
    r = fusionar_evidencia_origen(planta_mobile=RENCA, planta_documento=None, categoria="BARRAS")
    assert r.contradiccion is True
    assert r.planta is None
    assert r.motivo.startswith(MOTIVO_CONTRADICCION_OPERACIONAL)
    assert "MOBILE=AZA_RENCA:INCOMPATIBLE" in r.motivo


def test_mobile_colina_angulos_regla_incompatible_es_contradiccion():
    r = fusionar_evidencia_origen(planta_mobile=COLINA, planta_documento=None, categoria="ANGULOS")
    assert r.contradiccion is True


def test_mobile_colina_material_no_determinado_resuelve_directo_caso_real_472624():
    """Bloque M2-A/B -- causa raíz real 472624: Mobile informó AZA_COLINA,
    el OCR no logró determinar el material (`tipo_carga="NO DETERMINADO"`)
    -- Atlas producía `CONTRADICCION_OPERACIONAL_ORIGEN[MOBILE=AZA_COLINA:
    INCOMPATIBLE]` y dejaba el origen sin determinar. Evidencia directa
    (Mobile) suficiente y sin contradicción real -- debe resolver y
    terminar, nunca exigir que el material esté determinado para aceptar
    Mobile."""
    r = fusionar_evidencia_origen(planta_mobile=COLINA, planta_documento=None, categoria="NO DETERMINADO")
    assert r.contradiccion is False
    assert r.planta is COLINA
    assert r.fuente == FUENTE_MOBILE
    assert r.compatibilidad_mobile == SIN_REGLA


def test_mobile_renca_angulos_es_consistente():
    r = fusionar_evidencia_origen(planta_mobile=RENCA, planta_documento=None, categoria="ANGULOS")
    assert r.contradiccion is False
    assert r.planta is RENCA


def test_mobile_colina_rollos_es_consistente():
    r = fusionar_evidencia_origen(planta_mobile=COLINA, planta_documento=None, categoria="ROLLOS")
    assert r.contradiccion is False
    assert r.planta is COLINA


# --- Ausencia de reglas configuradas -- degradación segura ---

def test_sin_reglas_configuradas_mobile_gana_sin_bloquear():
    r = fusionar_evidencia_origen(planta_mobile=SIN_REGLAS, planta_documento=None, categoria="BARRAS")
    assert r.contradiccion is False
    assert r.planta is SIN_REGLAS


def test_sin_reglas_configuradas_documento_gana_sin_bloquear():
    r = fusionar_evidencia_origen(planta_mobile=None, planta_documento=SIN_REGLAS, categoria="BARRAS")
    assert r.contradiccion is False
    assert r.planta is SIN_REGLAS
    assert r.fuente == FUENTE_DOCUMENTO


def test_sin_ninguna_evidencia_sin_origen_sin_contradiccion():
    r = fusionar_evidencia_origen(planta_mobile=None, planta_documento=None, categoria="BARRAS")
    assert r.planta is None
    assert r.contradiccion is False


# --- Encabezado societario nunca se trata automáticamente como origen
# físico cuando contradice la regla y no hay corroboración ---

def test_solo_documento_incompatible_es_contradiccion_no_aceptacion_ciega():
    r = fusionar_evidencia_origen(planta_mobile=None, planta_documento=RENCA, categoria="BARRAS")
    assert r.contradiccion is True
    assert r.planta is None


def test_solo_documento_compatible_sigue_funcionando_igual_que_hoy():
    """Compatibilidad hacia atrás: documentos históricos sin Mobile,
    cuya planta documental SÍ es compatible con la categoría (o sin
    regla configurada), siguen resolviendo exactamente igual que antes
    de este bloque."""
    r = fusionar_evidencia_origen(planta_mobile=None, planta_documento=COLINA, categoria="BARRAS")
    assert r.contradiccion is False
    assert r.planta is COLINA
    assert r.fuente == FUENTE_DOCUMENTO
    assert r.evidencia == "ENCABEZADO_GUIA"


# --- Ambas coinciden: consistente ---

def test_mobile_y_documento_coinciden_en_la_misma_planta():
    r = fusionar_evidencia_origen(planta_mobile=COLINA, planta_documento=COLINA, categoria="BARRAS")
    assert r.contradiccion is False
    assert r.planta is COLINA
    assert r.fuente == FUENTE_MOBILE


# --- Ambas discrepan y NINGUNA regla desempata (ambas compatibles, o
# ambas incompatibles, o sin regla) -- contradicción real ---

def test_discrepancia_sin_regla_que_desempate_es_contradiccion():
    otra_planta_sin_reglas = _planta("PLANTA OTRA")
    r = fusionar_evidencia_origen(planta_mobile=SIN_REGLAS, planta_documento=otra_planta_sin_reglas, categoria="BARRAS")
    assert r.contradiccion is True


def test_mobile_incompatible_documento_compatible_no_se_acepta_el_documento_a_ciegas():
    """Aunque el documento resulte "compatible" con la regla, el
    encabezado societario sigue siendo estructuralmente poco confiable
    -- nunca se usa para CORREGIR una discrepancia con Mobile, sólo
    para reforzar cuando Mobile ya es compatible (Sección
    CONTRADICCIONES del ticket: no autocorregir sólo por la regla)."""
    r = fusionar_evidencia_origen(planta_mobile=RENCA, planta_documento=COLINA, categoria="BARRAS")
    assert r.contradiccion is True
    assert r.planta is None


# --- Bloque GENERALIZACIÓN del ticket -- PRUEBA ARQUITECTÓNICA: otro
# rubro (alimentos), CERO código específico nuevo. Si esto pasa, el
# motor de evidencia de origen es universal de verdad, no MBT/AZA con
# otro nombre encima. ---

PLANTA_NORTE = _planta("PLANTA NORTE", ("REFRIGERADOS",))
PLANTA_SUR = _planta("PLANTA SUR", ("SECOS",))


def test_otro_rubro_alimentos_refrigerados_planta_norte_es_compatible():
    r = fusionar_evidencia_origen(planta_mobile=PLANTA_NORTE, planta_documento=None, categoria="REFRIGERADOS")
    assert r.contradiccion is False
    assert r.planta is PLANTA_NORTE


def test_otro_rubro_alimentos_refrigerados_planta_sur_es_contradiccion():
    r = fusionar_evidencia_origen(planta_mobile=PLANTA_SUR, planta_documento=None, categoria="REFRIGERADOS")
    assert r.contradiccion is True
    assert r.planta is None


def test_a_dict_expone_ambas_fuentes_y_compatibilidad_para_b1():
    """Bloque "B1/ATLAS IA" del ticket: B1 debe poder recibir origen
    informado, evidencia documental, categoría y compatibilidades ya
    evaluadas -- nunca AZA/COLINA/RENCA/BARRAS como claves, sólo como
    VALORES de este contexto."""
    r = fusionar_evidencia_origen(planta_mobile=COLINA, planta_documento=RENCA, categoria="BARRAS")
    datos = r.a_dict()
    assert datos["mobile"]["planta_nombre"] == "AZA COLINA"
    assert datos["mobile"]["compatibilidad"] == COMPATIBLE
    assert datos["documento"]["planta_nombre"] == "AZA RENCA"
    assert datos["documento"]["compatibilidad"] == INCOMPATIBLE
    assert datos["resultado"]["planta_nombre"] == "AZA COLINA"
    assert datos["categoria"] == "BARRAS"
    assert datos["contradiccion"] is False


def test_a_dict_en_contradiccion_no_pierde_evidencia_de_ninguna_fuente():
    r = fusionar_evidencia_origen(planta_mobile=RENCA, planta_documento=None, categoria="BARRAS")
    datos = r.a_dict()
    assert datos["contradiccion"] is True
    assert datos["mobile"]["planta_nombre"] == "AZA RENCA"
    assert datos["mobile"]["compatibilidad"] == INCOMPATIBLE
    assert datos["documento"] == {"compatibilidad": SIN_REGLA}


def test_otro_rubro_alimentos_encabezado_no_fisico_no_sobrescribe_mobile():
    """Réplica exacta del caso real 472593, con un rubro y nombres de
    planta completamente distintos -- misma mecánica, mismo resultado:
    Mobile compatible gana sobre un documento incompatible con la
    regla."""
    r = fusionar_evidencia_origen(planta_mobile=PLANTA_NORTE, planta_documento=PLANTA_SUR, categoria="REFRIGERADOS")
    assert r.contradiccion is False
    assert r.planta is PLANTA_NORTE
    assert r.fuente == FUENTE_MOBILE


# ============================================================
# Bloque R2.3 (adición) -- resolución de origen por eliminación de
# categoría cuando la planta documental resulta incompatible. Universal
# por diseño (misma filosofía del módulo): fixtures propias, nombres
# arbitrarios -- la "regla AZA" real vive en categorias_permitidas del
# catálogo (dato), nunca en este código.
# ============================================================

from atlas_core.rutas.origen_evidencia import resolver_planta_alternativa_por_categoria


def _planta_con_direccion(nombre, categorias, direccion):
    base = _planta(nombre, categorias)
    from dataclasses import replace
    return replace(base, direccion=direccion)


NORTE_CON_DIRECCION = _planta_con_direccion("PLANTA NORTE AVENA", ("BARRAS", "ROLLOS"), "CALLE NORTE 100, COMUNA X")
SUR_SOLO_ANGULOS = _planta("PLANTA SUR AVENA", ("ANGULOS",))


def test_resuelve_por_eliminacion_cuando_hay_exactamente_una_alternativa_compatible():
    resultado = resolver_planta_alternativa_por_categoria(
        planta_documental=SUR_SOLO_ANGULOS, categoria="BARRAS",
        plantas=[NORTE_CON_DIRECCION, SUR_SOLO_ANGULOS],
        destino_texto="CALLE DE UN CLIENTE CUALQUIERA 500",
    )
    assert resultado is NORTE_CON_DIRECCION


def test_no_resuelve_si_la_planta_documental_es_compatible():
    """Nada que resolver por este camino: la incompatibilidad es el
    disparador, no un requisito arbitrario."""
    resultado = resolver_planta_alternativa_por_categoria(
        planta_documental=NORTE_CON_DIRECCION, categoria="BARRAS",
        plantas=[NORTE_CON_DIRECCION, SUR_SOLO_ANGULOS],
        destino_texto="CUALQUIER DESTINO",
    )
    assert resultado is None


def test_no_resuelve_si_hay_mas_de_una_alternativa_compatible():
    otra_compatible = _planta("PLANTA ESTE AVENA", ("BARRAS",))
    resultado = resolver_planta_alternativa_por_categoria(
        planta_documental=SUR_SOLO_ANGULOS, categoria="BARRAS",
        plantas=[NORTE_CON_DIRECCION, otra_compatible, SUR_SOLO_ANGULOS],
        destino_texto="CUALQUIER DESTINO",
    )
    assert resultado is None


def test_no_resuelve_si_ninguna_alternativa_es_compatible():
    otra_incompatible = _planta("PLANTA ESTE AVENA", ("ANGULOS",))
    resultado = resolver_planta_alternativa_por_categoria(
        planta_documental=SUR_SOLO_ANGULOS, categoria="BARRAS",
        plantas=[otra_incompatible, SUR_SOLO_ANGULOS],
        destino_texto="CUALQUIER DESTINO",
    )
    assert resultado is None


def test_no_resuelve_si_el_destino_es_la_propia_planta_alternativa_direccion():
    """Caso real (traslado interno): BARRAS con destino la DIRECCIÓN real
    de la planta candidata -- eso es evidencia de un movimiento interno
    HACIA esa planta, nunca de un despacho a cliente DESDE ella."""
    resultado = resolver_planta_alternativa_por_categoria(
        planta_documental=SUR_SOLO_ANGULOS, categoria="BARRAS",
        plantas=[NORTE_CON_DIRECCION, SUR_SOLO_ANGULOS],
        destino_texto="CALLE NORTE 100, COMUNA X",
    )
    assert resultado is None


def test_no_resuelve_si_el_destino_nombra_la_propia_planta_alternativa():
    resultado = resolver_planta_alternativa_por_categoria(
        planta_documental=SUR_SOLO_ANGULOS, categoria="BARRAS",
        plantas=[NORTE_CON_DIRECCION, SUR_SOLO_ANGULOS],
        destino_texto="PLANTA NORTE AVENA",
    )
    assert resultado is None


def test_planta_alternativa_no_vigente_no_cuenta():
    from dataclasses import replace
    inactiva = replace(NORTE_CON_DIRECCION, estado_vigencia="INACTIVA")
    resultado = resolver_planta_alternativa_por_categoria(
        planta_documental=SUR_SOLO_ANGULOS, categoria="BARRAS",
        plantas=[inactiva, SUR_SOLO_ANGULOS],
        destino_texto="CUALQUIER DESTINO",
    )
    assert resultado is None


def test_caso_real_rollos_cliente_externo_aza_resuelve_colina():
    resultado = resolver_planta_alternativa_por_categoria(
        planta_documental=RENCA, categoria="ROLLOS", plantas=[COLINA, RENCA],
        destino_texto="CAMINO A MELIPILLA 10800 SANTIAGO MAIPU",
    )
    assert resultado is COLINA


def test_caso_real_barras_cliente_externo_aza_resuelve_colina():
    resultado = resolver_planta_alternativa_por_categoria(
        planta_documental=RENCA, categoria="BARRAS", plantas=[COLINA, RENCA],
        destino_texto="AV. ALMTE. LATORRE 843 MEJILLONES MEJILLONES",
    )
    assert resultado is COLINA


# ============================================================
# Bloque ORIGEN V3 -- CONVERGENCIA DE EVIDENCIA ANTES DE PREGUNTAR:
# `resolver_planta_unica_por_categoria` -- a diferencia de la función de
# arriba, NUNCA exige una planta documental que "eliminar"; resuelve por
# categoría sola cuando exactamente una planta vigente la despacha.
# Casos reales del lote 2: 464730/464631/464529.
# ============================================================

from atlas_core.rutas.origen_evidencia import (
    conflicto_gps_tiene_evidencia_real,
    resolver_planta_unica_por_categoria,
)


def test_resuelve_sin_ningun_candidato_previo_cuando_hay_una_sola_planta_compatible():
    resultado = resolver_planta_unica_por_categoria(
        categoria="BARRAS", plantas=[COLINA, RENCA],
        destino_texto="CAMINO A MELIPILLA 10800 SANTIAGO MAIPU",
    )
    assert resultado is COLINA


def test_caso_real_464730_barras_conflicto_gps_en_cero_resuelve_colina():
    resultado = resolver_planta_unica_por_categoria(
        categoria="BARRAS", plantas=[COLINA, RENCA],
        destino_texto="CAMINO A MELIPILLA 10B00 SANTIAGO MAIPU",
    )
    assert resultado is COLINA


def test_caso_real_464631_rollos_resuelve_colina():
    resultado = resolver_planta_unica_por_categoria(
        categoria="ROLLOS", plantas=[COLINA, RENCA], destino_texto="SANTA ISABEL 585 SANTIAGO LAMPA",
    )
    assert resultado is COLINA


def test_caso_real_464529_rollos_resuelve_colina():
    resultado = resolver_planta_unica_por_categoria(
        categoria="ROLLOS", plantas=[COLINA, RENCA], destino_texto="VISTA CLARA 2351 CERRILLOS",
    )
    assert resultado is COLINA


def test_categoria_sin_regla_nunca_cuenta_como_evidencia():
    """SIN_REGLA (categoría no determinada, o ninguna planta con
    `categorias_permitidas` configuradas) nunca decide -- nunca se
    inventa origen cuando en verdad no hay evidencia real (464367/464265:
    material NO_DETERMINADO)."""
    resultado = resolver_planta_unica_por_categoria(
        categoria="NO DETERMINADO", plantas=[COLINA, RENCA], destino_texto="CUALQUIER DESTINO",
    )
    assert resultado is None


def test_dos_plantas_compatibles_es_ambiguedad_real_nunca_elige():
    otra_compatible = _planta("PLANTA ESTE", ("BARRAS",))
    resultado = resolver_planta_unica_por_categoria(
        categoria="BARRAS", plantas=[COLINA, otra_compatible, RENCA], destino_texto="CUALQUIER DESTINO",
    )
    assert resultado is None


def test_traslado_interno_hacia_la_unica_planta_no_resuelve():
    resultado = resolver_planta_unica_por_categoria(
        categoria="ROLLOS", plantas=[COLINA, RENCA], destino_texto="AZA COLINA",
    )
    assert resultado is None


def test_ninguna_planta_compatible_no_resuelve():
    resultado = resolver_planta_unica_por_categoria(
        categoria="ANGULOS", plantas=[COLINA], destino_texto="CUALQUIER DESTINO",
    )
    assert resultado is None


# --- `conflicto_gps_tiene_evidencia_real` -- distingue un conflicto GPS
# con evidencia física real de uno donde todo el "solape" mide 0%. ---


def test_conflicto_real_con_todo_solape_en_cero_no_es_evidencia_real():
    """Caso real 464730 -- ningún candidato tocó realmente la ventana de
    forma medible; el empate en cero no es evidencia real."""
    assert conflicto_gps_tiene_evidencia_real(
        "CONFLICTO_REAL_EN_VENTANA(AZA_COLINA:score=0.0026,solape=0.0%;AZA_RENCA:score=0.0,solape=0.0%)"
    ) is False


def test_conflicto_real_con_algun_solape_positivo_es_evidencia_real():
    assert conflicto_gps_tiene_evidencia_real(
        "CONFLICTO_REAL_EN_VENTANA(AZA_COLINA:score=0.8,solape=45.2%;AZA_RENCA:score=0.1,solape=0.0%)"
    ) is True


def test_motivo_que_no_es_conflicto_nunca_cuenta_como_evidencia_real():
    assert conflicto_gps_tiene_evidencia_real("EVIDENCIA_GEOCERCA_SIN_SOLAPE_SUFICIENTE(X:solape=0.0%,score=0.0)") is False
    assert conflicto_gps_tiene_evidencia_real("SIN_EVIDENCIA_GPS") is False
    assert conflicto_gps_tiene_evidencia_real("") is False


def test_conflicto_real_sin_solape_parseable_se_trata_como_evidencia_real_por_cautela():
    assert conflicto_gps_tiene_evidencia_real("CONFLICTO_REAL_EN_VENTANA(FORMATO_INESPERADO)") is True
