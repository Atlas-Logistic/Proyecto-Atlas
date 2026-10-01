"""Regresiones focales de propuestas B1 para obra y dirección operacional."""
from atlas_core.atlas_ia.candidatos_externos import (
    CandidatoExterno,
    evaluar_candidatos,
    evaluar_nombre_obra,
)
from atlas_core.atlas_ia.investigacion_revision import preview_operacional


def _obra(url, nombre="EMPRESA CONSTRUCTORA BRAVO E IZQUIERDO LIMITADA"):
    return CandidatoExterno(
        nombre=nombre, url=url, verificacion="VERIFICADA",
        anclajes_verificados=("ENTIDAD", "NOMBRE_COMPLETO"),
    )


def _direccion(url, *, numero="73"):
    return CandidatoExterno(
        nombre="OBRA NOVICIADO", direccion="CAMINO EL NOVICIADO", numero=numero,
        comuna="LAMPA", url=url, verificacion="VERIFICADA",
        anclajes_verificados=("DIRECCION", "NUMERO", "COMUNA", "ENTIDAD"),
    )


def _eval_direccion(*candidatos, direccion="CAM. EL NOVICIADO LAMPA LAMPA"):
    return evaluar_candidatos(
        candidatos=list(candidatos), obra="OBRA NOVICIADO", cliente="", rut_cliente="",
        direccion_documental=direccion, localidad="LAMPA",
    )


def test_nombre_truncado_propone_nombre_operacional_completo_sin_prueba_juridica():
    resultado = evaluar_nombre_obra(
        candidatos=[_obra("https://uno.cl/obra"), _obra("https://dos.cl/obra")],
        obra_documental="EMPRESA CONSTRUCTORA BRAVO E",
    )
    assert resultado["estado"] == "PROPUESTA_RESOLUBLE"
    assert resultado["propuesta"]["nombre_candidato"] == "EMPRESA CONSTRUCTORA BRAVO E IZQUIERDO LIMITADA"


def test_direccion_incompleta_propone_numero_solo_cuando_dos_fuentes_lo_publican():
    resultado = _eval_direccion(_direccion("https://uno.cl/a"), _direccion("https://dos.cl/b"))
    assert resultado["estado"] == "PROPUESTA_RESOLUBLE"
    assert resultado["propuesta"]["direccion"] == "CAMINO EL NOVICIADO 73, LAMPA"
    assert resultado["numero_documental"] == ""


def test_evidencia_insuficiente_o_numeros_contradictorios_se_abstiene():
    assert _eval_direccion(_direccion("https://uno.cl/a"))["estado"] == "ABSTENCION"
    resultado = _eval_direccion(
        _direccion("https://uno.cl/a"), _direccion("https://dos.cl/b"),
        direccion="CAM. EL NOVICIADO 72 LAMPA",
    )
    assert resultado["estado"] == "ABSTENCION"
    assert resultado["candidatos_evaluados"][0]["comparaciones"]["NUMERO"] == "CONTRADICE"


def test_dos_nombres_o_dos_direcciones_plausibles_piden_aclaracion():
    obras = evaluar_nombre_obra(
        candidatos=[
            _obra("https://uno.cl/a", "EMPRESA CONSTRUCTORA BRAVO E IZQUIERDO LIMITADA"),
            _obra("https://dos.cl/a", "EMPRESA CONSTRUCTORA BRAVO E IZQUIERDO LIMITADA"),
            _obra("https://tres.cl/b", "EMPRESA CONSTRUCTORA BRAVO E SPA"),
            _obra("https://cuatro.cl/b", "EMPRESA CONSTRUCTORA BRAVO E SPA"),
        ], obra_documental="EMPRESA CONSTRUCTORA BRAVO E",
    )
    destinos = _eval_direccion(
        _direccion("https://uno.cl/a", numero="73"), _direccion("https://dos.cl/a", numero="73"),
        _direccion("https://tres.cl/b", numero="75"), _direccion("https://cuatro.cl/b", numero="75"),
    )
    assert obras["estado"] == destinos["estado"] == "ABSTENCION"


def test_preview_humano_es_minimo_y_exige_confirmacion_por_via_controlada():
    preview = preview_operacional({
        "CAMPO": "obra_destino", "PROPUESTA": "EMPRESA CONSTRUCTORA BRAVO E IZQUIERDO LIMITADA",
        "HECHOS_DOCUMENTALES": {"valor_extraido": "EMPRESA CONSTRUCTORA BRAVO E"},
        "EVALUACION_CANDIDATOS_EXTERNOS": {"razon": "Dos fuentes independientes convergen"},
    })
    assert set(preview) == {"valor_actual", "valor_propuesto", "evidencia_relevante", "consecuencia_operacional"}
    assert "confirmación" in preview["consecuencia_operacional"]
