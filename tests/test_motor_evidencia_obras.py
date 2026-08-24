"""Motor de Evidencia -- Obras. Caso real que motivó este módulo: guía
464493, "EMPRESA CONST SIGRO SA" vs la obra ya confirmada "EMPRESA CONST
SIGRO" para el mismo cliente (PRODALAM SA) -- ver auditoría previa,
commit `fb8ba95`. Usa la evidencia externa REAL capturada del caso SIGRO
(`tests/fixtures_verificacion_externa.py`)."""
from __future__ import annotations

from atlas_core.catalogo_obras_destinos import Obra
from atlas_core.motor_evidencia import RESULTADO_ALTA_NUEVA, RESULTADO_CONTRADICCION_DOCUMENTAL, RESULTADO_SUGERENCIA_HUMANA
from atlas_core.motor_evidencia_obras import (
    coincide_salvo_sufijo_societario,
    coincide_salvo_variacion_ortografica_menor,
    evaluar_evidencia_obra,
    resolver_obra_por_variacion_ortografica_menor,
)
from tests.fixtures_verificacion_externa import EVIDENCIA_SIGRO_CORPORATIVA, EVIDENCIA_SIGRO_DIRECTORIO


def _obra_sigro() -> Obra:
    return Obra(
        obra_id="obra-sigro", cliente_id="cliente-prodalam", nombre_canonico="EMPRESA CONST SIGRO",
        nombre_normalizado="EMPRESA CONST SIGRO", aliases_documentales=(), estado="CONFIRMADA",
        estado_vigencia="ACTIVO", evidencias=(),
        fecha_creacion="2026-01-01T00:00:00+00:00", fecha_modificacion="2026-01-01T00:00:00+00:00",
    )


# ============================================================
# coincide_salvo_sufijo_societario -- calibrada, nunca decide identidad sola
# ============================================================


def test_coincide_salvo_sufijo_sigro_sa_vs_sigro():
    assert coincide_salvo_sufijo_societario("EMPRESA CONST SIGRO SA", "EMPRESA CONST SIGRO") is True


def test_no_coincide_si_ya_son_identicos():
    """No debería siquiera necesitar esta función -- el match exacto ya lo
    resuelve; se define False para evitar candidatos redundantes."""
    assert coincide_salvo_sufijo_societario("EMPRESA CONST SIGRO", "EMPRESA CONST SIGRO") is False


def test_no_coincide_si_difieren_en_algo_mas_que_el_sufijo():
    assert coincide_salvo_sufijo_societario("CONSTRUCTORA ABC SA", "CONSTRUCTORA XYZ SA") is False


def test_no_fusiona_dos_formas_societarias_distintas_con_nombre_base_distinto():
    """Nunca asume que remover el sufijo de AMBOS lados basta si los
    nombres base no coinciden -- protege contra fusionar entidades
    legalmente distintas."""
    assert coincide_salvo_sufijo_societario("CONSTRUCTORA DELTA SPA", "CONSTRUCTORA OMEGA LTDA") is False


# ============================================================
# SIGRO -- caso real completo
# ============================================================


def test_sigro_coincidencia_interna_por_sufijo_es_sugerencia_no_forzada():
    resultado = evaluar_evidencia_obra(
        nombre_documental="EMPRESA CONST SIGRO SA", obras_confirmadas_mismo_cliente=(_obra_sigro(),),
    )
    assert resultado.resultado == RESULTADO_SUGERENCIA_HUMANA
    assert resultado.candidatos[0].valor_canonico == "EMPRESA CONST SIGRO"
    assert "TEXTO_DOCUMENTAL_DIFIERE" in resultado.candidatos[0].conflictos


def test_sigro_con_solo_directorio_real_sigue_siendo_sugerencia_no_forzada():
    """Un directorio empresarial (Mercantil.com, evidencia REAL capturada
    el 2026-08-19) es una fuente de alta confianza, pero no la más alta
    -- sólo refuerza la sugerencia, no la convierte en contradicción
    demostrada por sí sola."""
    resultado = evaluar_evidencia_obra(
        nombre_documental="EMPRESA CONST SIGRO SA", obras_confirmadas_mismo_cliente=(_obra_sigro(),),
        evidencia_externa=(EVIDENCIA_SIGRO_DIRECTORIO,),
    )
    assert resultado.resultado == RESULTADO_SUGERENCIA_HUMANA
    assert any(c.valor_canonico == "Empresa Constructora Sigro S.A." for c in resultado.candidatos)
    # La coincidencia interna por sufijo sigue siendo visible, nunca oculta.
    assert any(c.valor_canonico == "EMPRESA CONST SIGRO" for c in resultado.candidatos)


def test_sigro_con_sitio_corporativo_real_es_contradiccion_documental():
    """El sitio corporativo oficial (web.sigro.cl, evidencia REAL) es una
    fuente de mayor confianza -- corrobora con fuerza, aunque sigue sin
    resolver solo (nunca sin confirmación humana estructural)."""
    resultado = evaluar_evidencia_obra(
        nombre_documental="EMPRESA CONST SIGRO SA", obras_confirmadas_mismo_cliente=(_obra_sigro(),),
        evidencia_externa=(EVIDENCIA_SIGRO_CORPORATIVA,),
    )
    assert resultado.resultado == RESULTADO_CONTRADICCION_DOCUMENTAL
    assert any(c.valor_canonico == "SIGRO S.A." for c in resultado.candidatos)


def test_sin_ninguna_coincidencia_es_alta_nueva():
    resultado = evaluar_evidencia_obra(nombre_documental="OBRA GENUINAMENTE NUEVA XYZ", obras_confirmadas_mismo_cliente=())
    assert resultado.resultado == RESULTADO_ALTA_NUEVA


def test_evidencia_externa_corrobora_direccion_y_comuna_visible_en_el_candidato():
    """La evidencia externa real de SIGRO trae dirección/comuna
    corroboradas -- deben quedar visibles en el candidato (nunca sólo la
    razón social), auditable por Javier."""
    resultado = evaluar_evidencia_obra(
        nombre_documental="EMPRESA CONST SIGRO SA", obras_confirmadas_mismo_cliente=(),
        evidencia_externa=(EVIDENCIA_SIGRO_CORPORATIVA,),
    )
    candidato = resultado.candidatos[0]
    assert candidato.metadatos.get("fuente") == "web.sigro.cl"
    assert "EVIDENCIA_EXTERNA" in candidato.evidencias[0]
    assert candidato.metadatos.get("direccion") == "Narciso Goycolea 4040 Piso 1"
    assert candidato.metadatos.get("comuna") == "Vitacura"
    assert EVIDENCIA_SIGRO_CORPORATIVA.direccion == "Narciso Goycolea 4040 Piso 1"
    assert EVIDENCIA_SIGRO_CORPORATIVA.comuna == "Vitacura"


def test_direccion_web_sola_no_demuestra_obra_operacional():
    """Evidencia corporativa (el sitio propio de SIGRO) corrobora la
    EMPRESA, no que exista una obra/proyecto operacional en curso -- el
    resultado sigue siendo, como mucho, una contradicción a confirmar,
    nunca RESUELTO_AUTOMATICAMENTE."""
    resultado = evaluar_evidencia_obra(
        nombre_documental="EMPRESA CONST SIGRO SA", obras_confirmadas_mismo_cliente=(),
        evidencia_externa=(EVIDENCIA_SIGRO_DIRECTORIO,),
    )
    assert resultado.resultado != "RESUELTO_AUTOMATICAMENTE"


# ============================================================
# Bloque FIX DE ACEPTACION -- caso real 460861: "SALOMON SACK SA SAN
# BERNGARDO" (OCR) vs la obra ya CONFIRMADA "SALOMON SACK SA SAN
# BERNARDO" -- variación ortográfica/OCR MÍNIMA de un solo token.
# ============================================================


def _obra_salomon_sack() -> Obra:
    return Obra(
        obra_id="obra-salomon-sack", cliente_id="cliente-salomon-sack",
        nombre_canonico="SALOMON SACK SA SAN BERNARDO",
        nombre_normalizado="SALOMON SACK SA SAN BERNARDO", aliases_documentales=(),
        estado="CONFIRMADA", estado_vigencia="ACTIVO", evidencias=(),
        fecha_creacion="2026-01-01T00:00:00+00:00", fecha_modificacion="2026-01-01T00:00:00+00:00",
    )


def test_coincide_salvo_variacion_ortografica_caso_real_460861():
    assert coincide_salvo_variacion_ortografica_menor(
        "SALOMON SACK SA SAN BERNGARDO", "SALOMON SACK SA SAN BERNARDO",
    ) is True


def test_no_coincide_variacion_ortografica_si_ya_son_identicos():
    assert coincide_salvo_variacion_ortografica_menor(
        "SALOMON SACK SA SAN BERNARDO", "SALOMON SACK SA SAN BERNARDO",
    ) is False


def test_no_coincide_variacion_ortografica_con_numero_de_tokens_distinto():
    """Nunca compensa una palabra de más/de menos -- ese es el dominio de
    `coincide_salvo_sufijo_societario`, no de este chequeo."""
    assert coincide_salvo_variacion_ortografica_menor(
        "EMPRESA CONST SIGRO SA", "EMPRESA CONST SIGRO",
    ) is False


def test_no_coincide_variacion_ortografica_con_dos_tokens_distintos():
    """Dos o más tokens distintos ya no es una variación menor -- Atlas
    se abstiene en vez de adivinar."""
    assert coincide_salvo_variacion_ortografica_menor(
        "CONSTRUCTORA DELTA NORTE", "CONSTRUCTORA OMEGA SUR",
    ) is False


def test_no_coincide_variacion_ortografica_token_corto():
    """Piso de seguridad: un token corto con distancia de edición 1 es
    demasiado inespecífico (p.ej. "SAL"/"SAN", 3 letras) para
    autorresolver -- nunca una coincidencia por azar entre palabras
    cortas."""
    assert coincide_salvo_variacion_ortografica_menor(
        "OBRA CENTRO SAL", "OBRA CENTRO SAN",
    ) is False


def test_no_coincide_variacion_ortografica_distancia_mayor_a_uno():
    assert coincide_salvo_variacion_ortografica_menor(
        "SALOMON SACK SA SAN BERNGARDOX", "SALOMON SACK SA SAN BERNARDO",
    ) is False


# --- REGRESIONES (Sección 6 del bloque) --------------------------------


def test_regresion_a_typo_ocr_pequeno_con_unico_candidato_autorresuelve():
    obra = _obra_salomon_sack()
    resuelto = resolver_obra_por_variacion_ortografica_menor(
        nombre_documental="SALOMON SACK SA SAN BERNGARDO",
        obras_confirmadas_mismo_cliente=(obra,),
    )
    assert resuelto is obra


def test_regresion_b_dos_entidades_realmente_similares_no_autorresuelve():
    """Caso genuinamente ambiguo: el texto documental está a distancia de
    edición 1 de DOS obras reales distintas del mismo cliente -- ninguna
    es claramente superior, así que Atlas se abstiene (Bloque SEGURIDAD:
    "si hay dos candidatos plausibles -> B1/humano") en vez de elegir
    arbitrariamente."""
    obra_bernardo = _obra_salomon_sack()  # "...SAN BERNARDO"
    obra_bernardq = Obra(
        obra_id="obra-bernardq", cliente_id="cliente-salomon-sack",
        nombre_canonico="SALOMON SACK SA SAN BERNARDQ",
        nombre_normalizado="SALOMON SACK SA SAN BERNARDQ", aliases_documentales=(),
        estado="CONFIRMADA", estado_vigencia="ACTIVO", evidencias=(),
        fecha_creacion="2026-01-01T00:00:00+00:00", fecha_modificacion="2026-01-01T00:00:00+00:00",
    )
    resuelto = resolver_obra_por_variacion_ortografica_menor(
        nombre_documental="SALOMON SACK SA SAN BERNARDX",
        obras_confirmadas_mismo_cliente=(obra_bernardo, obra_bernardq),
    )
    assert resuelto is None


def test_regresion_c_entidad_realmente_nueva_no_autorresuelve():
    obra = _obra_salomon_sack()
    resuelto = resolver_obra_por_variacion_ortografica_menor(
        nombre_documental="CONSTRUCTORA TOTALMENTE DISTINTA LTDA",
        obras_confirmadas_mismo_cliente=(obra,),
    )
    assert resuelto is None


def test_regresion_d_aprendizaje_previo_reutiliza_alias_por_coincidencia_exacta():
    """El "aprendizaje" (alias persistido) se prueba aquí a nivel de la
    función de resolución: una vez que el texto documental exacto ya es
    un alias de la obra, la variación ortográfica ni siquiera hace falta
    -- el alias por sí solo ya la identifica como candidata."""
    obra = _obra_salomon_sack()
    obra_con_alias = Obra(**{**obra.__dict__, "aliases_documentales": ("SALOMON SACK SA SAN BERNGARDO",)})
    # Una variación NUEVA, distinta de la ya aprendida, contra la MISMA
    # obra -- el alias aprendido no bloquea que otras variaciones sigan
    # resolviendo por el mecanismo de variación ortográfica.
    resuelto = resolver_obra_por_variacion_ortografica_menor(
        nombre_documental="SALOMON SACK SA SAN BERNARFO",
        obras_confirmadas_mismo_cliente=(obra_con_alias,),
    )
    assert resuelto is obra_con_alias


def test_sin_candidatos_no_autorresuelve():
    assert resolver_obra_por_variacion_ortografica_menor(
        nombre_documental="SALOMON SACK SA SAN BERNGARDO",
        obras_confirmadas_mismo_cliente=(),
    ) is None
