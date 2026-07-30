from __future__ import annotations

from atlas_core.inteligencia.contrato_multicampo import EstadoResolucion
from atlas_core.inteligencia.politica_confianza_vehiculo import (
    POLITICA_CONFIANZA_VEHICULO_V1,
    PoliticaConfianzaVehiculo,
    ViaDecisionVehiculo,
)
from atlas_core.inteligencia.resolucion_vehiculo import (
    auditar_catalogo_vehiculos,
    resolver_vehiculo_patente,
)


def _registro(patente, tipo, **extras):
    return {
        "vehiculo_id": extras.pop("vehiculo_id", f"id-{patente}"),
        "patente": patente,
        "tipo": tipo,
        "aliases": extras.pop("aliases", []),
        "estado_vigencia": extras.pop("estado_vigencia", "ACTIVO"),
        "estado_calidad": extras.pop("estado_calidad", "CONFIRMADO"),
        **extras,
    }


def test_correccion_visual_no_confirma_aunque_politica_valga_uno():
    valores = dict(POLITICA_CONFIANZA_VEHICULO_V1.valores)
    valores[ViaDecisionVehiculo.CORRECCION_VISUAL_UNICA] = 1.0
    politica = PoliticaConfianzaVehiculo("prueba", valores)
    resultado = resolver_vehiculo_patente(
        patente_tracto="8KYX63",
        catalogo={"vehiculos": [_registro("BKYX63", "TRACTO")]},
        politica_confianza=politica,
    )
    assert resultado.estado is EstadoResolucion.PROPUESTO
    assert resultado.confianza == 1.0


def test_patente_parecida_pero_exacta_de_otro_vehiculo_no_se_corrige():
    catalogo = {
        "vehiculos": [
            _registro("BKYX63", "TRACTO"),
            _registro("BKYX83", "TRACTO"),
        ]
    }
    resultado = resolver_vehiculo_patente(
        patente_tracto="BKYX83", catalogo=catalogo
    )
    assert resultado.estado is EstadoResolucion.CONFIRMADO
    assert resultado.patente_tracto_canonica == "BKYX83"


def test_calidad_baja_de_patente_exacta_exige_revision():
    resultado = resolver_vehiculo_patente(
        patente_tracto="BKYX63",
        calidades={"patente_tracto": 0.4},
        catalogo={"vehiculos": [_registro("BKYX63", "TRACTO")]},
    )
    assert resultado.estado is EstadoResolucion.REQUIERE_REVISION
    assert resultado.via_decision == "EVIDENCIA_BAJA"


def test_tipo_no_confirmado_del_catalogo_exige_revision():
    resultado = resolver_vehiculo_patente(
        patente_tracto="BKYX63",
        catalogo={
            "vehiculos": [
                _registro(
                    "BKYX63", "TRACTO", estado_calidad="PENDIENTE"
                )
            ]
        },
    )
    assert resultado.estado is EstadoResolucion.REQUIERE_REVISION


def test_catalogo_real_conocido_no_se_hardcodea():
    catalogo = {
        "BKYX63": {"tipo": "TRACTO"},
        "BPHR67": {"tipo": "TRACTO"},
    }
    for patente, rol in (
        ("WC1343", "RAMPLA"),
        ("WT7724", "RAMPLA"),
        ("KN5439", "RAMPLA"),
        ("XF3629", "CAMION_CAJITA"),
    ):
        resultado = resolver_vehiculo_patente(
            patente=patente, tipo_vehiculo=rol, catalogo=catalogo
        )
        assert resultado.estado is EstadoResolucion.NO_RESUELTO
        assert resultado.entidad is None


def test_bphr67_cajita_con_catalogo_tracto_es_contradiccion():
    resultado = resolver_vehiculo_patente(
        patente="BPHR67",
        tipo_vehiculo="CAMION_CAJITA",
        catalogo={"BPHR67": {"tipo": "TRACTO"}},
    )
    assert resultado.estado is EstadoResolucion.REQUIERE_REVISION
    assert resultado.contradicciones
    assert resultado.tipo_vehiculo_canonico == "TRACTO"


def test_tipo_desconocido_en_catalogo_es_auditable_y_no_confirma():
    catalogo = {"ZZZZ99": {"tipo": "SIN_CLASIFICAR"}}
    assert any(
        h.codigo == "ROL_DESCONOCIDO"
        for h in auditar_catalogo_vehiculos(catalogo)
    )
    resultado = resolver_vehiculo_patente(
        patente="ZZZZ99", catalogo=catalogo
    )
    assert resultado.estado is EstadoResolucion.REQUIERE_REVISION


def test_contexto_y_originales_quedan_congelados():
    contexto = {"documento": {"campos": ["chofer", "cliente"]}}
    resultado = resolver_vehiculo_patente(
        patente_tracto="BKYX63",
        catalogo={"BKYX63": {"tipo": "TRACTO"}},
        contexto=contexto,
    )
    contexto["documento"]["campos"].append("destino")
    assert resultado.contexto["documento"]["campos"] == ("chofer", "cliente")
    assert resultado.valores_ocr_originales["patente_tracto"] == ("BKYX63",)


def test_cajita_solo_es_no_aplica_con_evidencia_explicita_compatible():
    sin_tipo = resolver_vehiculo_patente(
        patente="XF3629",
        catalogo={"XF3629": {"tipo": "CAMION_CAJITA"}},
    )
    assert sin_tipo.patente_rampla_canonica is None
    assert sin_tipo.contexto["rampla_disponibilidad"] == "AUSENTE"

    con_tipo = resolver_vehiculo_patente(
        patente="XF3629",
        tipo_vehiculo="CAJITA",
        catalogo={"XF3629": {"tipo": "CAMION_CAJITA"}},
    )
    assert con_tipo.patente_rampla_canonica == "NO_APLICA"


def test_no_hay_autoaprendizaje_tras_propuesta_visual():
    catalogo = {"BKYX63": {"tipo": "TRACTO"}}
    uno = resolver_vehiculo_patente(
        patente_tracto="8KYX63", catalogo=catalogo
    )
    dos = resolver_vehiculo_patente(
        patente_tracto="8KYX63", catalogo=catalogo
    )
    assert uno == dos
    assert list(catalogo) == ["BKYX63"]


def test_patente_exacta_de_uno_y_alias_historico_de_otro_es_ambigua():
    catalogo = {
        "vehiculos": [
            _registro("BKYX63", "TRACTO", vehiculo_id="exacto"),
            _registro(
                "DD2494", "TRACTO", vehiculo_id="alias",
                aliases=["BKYX63"],
            ),
        ]
    }
    assert any(
        h.codigo == "ALIAS_PATENTE_AMBIGUO"
        for h in auditar_catalogo_vehiculos(catalogo)
    )
    resultado = resolver_vehiculo_patente(
        patente_tracto="BKYX63", catalogo=catalogo
    )
    assert resultado.estado is EstadoResolucion.REQUIERE_REVISION
    assert resultado.entidad is None


def test_alias_de_nombre_sin_patente_solo_propone():
    registro = _registro("BKYX63", "TRACTO", nombre="TRACTO AZUL")
    registro["aliases_nombre"] = ["AZUL"]
    resultado = resolver_vehiculo_patente(
        vehiculo="AZUL", catalogo={"vehiculos": [registro]}
    )
    assert resultado.estado is EstadoResolucion.PROPUESTO


def test_patente_invalida_aunque_figure_en_catalogo_no_confirma():
    catalogo = {"B8YX63": {"tipo": "TRACTO"}}
    resultado = resolver_vehiculo_patente(
        patente_tracto="B8YX63", catalogo=catalogo
    )
    assert resultado.estado is EstadoResolucion.REQUIERE_REVISION
    assert any(
        h.codigo == "PATENTE_INVALIDA"
        for h in auditar_catalogo_vehiculos(catalogo)
    )
