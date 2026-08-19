"""Motor de Evidencia -- Obras. Caso real que motivó este módulo: guía
464493, "EMPRESA CONST SIGRO SA" vs la obra ya confirmada "EMPRESA CONST
SIGRO" para el mismo cliente (PRODALAM SA) -- ver auditoría previa,
commit `fb8ba95`. Usa la evidencia externa REAL capturada del caso SIGRO
(`tests/fixtures_verificacion_externa.py`)."""
from __future__ import annotations

from atlas_core.catalogo_obras_destinos import Obra
from atlas_core.motor_evidencia import RESULTADO_ALTA_NUEVA, RESULTADO_CONTRADICCION_DOCUMENTAL, RESULTADO_SUGERENCIA_HUMANA
from atlas_core.motor_evidencia_obras import coincide_salvo_sufijo_societario, evaluar_evidencia_obra
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
