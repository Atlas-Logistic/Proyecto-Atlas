from __future__ import annotations

from copy import deepcopy

import pytest

from atlas_core.inteligencia.contrato_multicampo import (
    Disponibilidad,
    EstadoResolucion,
)
from atlas_core.inteligencia.resolucion_vehiculo import (
    auditar_catalogo_vehiculos,
    resolver_vehiculo_patente,
)
from atlas_core.inteligencia.snapshot_catalogo_vehiculos import (
    crear_snapshot_catalogo_vehiculos,
)


def _vehiculo(
    patente,
    tipo="TRACTO",
    *,
    vehiculo_id=None,
    activo=True,
    calidad="CONFIRMADO",
    aliases=(),
    nombre="",
):
    return {
        "vehiculo_id": vehiculo_id or f"id-{patente}",
        "patente": patente,
        "tipo": tipo,
        "aliases": list(aliases),
        "nombre": nombre,
        "estado_vigencia": "ACTIVO" if activo else "INACTIVO",
        "estado_calidad": calidad,
    }


def _catalogo(*registros):
    return {"vehiculos": list(registros)}


def test_patente_exacta_activa_confirma_y_conserva_ocr():
    catalogo = _catalogo(_vehiculo("BKYX63"))
    original = "  bkyx-63 "
    resultado = resolver_vehiculo_patente(
        patente_tracto=original, catalogo=catalogo
    )
    assert resultado.estado is EstadoResolucion.CONFIRMADO
    assert resultado.patente_tracto_original == original
    assert resultado.patente_tracto_canonica == "BKYX63"
    assert resultado.id_vehiculo_canonico == "id-BKYX63"
    assert resultado.rol_patente == "TRACTO"


def test_patente_exacta_inactiva_requiere_revision():
    resultado = resolver_vehiculo_patente(
        patente="BKYX63",
        tipo_vehiculo="TRACTO",
        catalogo=_catalogo(_vehiculo("BKYX63", activo=False)),
    )
    assert resultado.estado is EstadoResolucion.REQUIERE_REVISION
    assert resultado.via_decision == "INACTIVO"


def test_patente_valida_inexistente_no_inventa():
    resultado = resolver_vehiculo_patente(
        patente="ZZZZ99", catalogo=_catalogo(_vehiculo("BKYX63"))
    )
    assert resultado.estado is EstadoResolucion.NO_RESUELTO
    assert resultado.entidad is None
    assert resultado.patente_original == "ZZZZ99"


def test_ocr_vacio_no_resuelto():
    resultado = resolver_vehiculo_patente(catalogo=_catalogo())
    assert resultado.estado is EstadoResolucion.NO_RESUELTO
    assert resultado.requiere_revision


@pytest.mark.parametrize(
    ("ocr", "canonico"),
    [
        ("8KYX63", "BKYX63"),
        ("BKYXO3", "BKYX03"),
        ("BKYX6I", "BKYX61"),
        ("BKS563", "BK5563"),
        ("BKZ263", "BK2263"),
        ("BKG663", "BK6663"),
        ("BKYT63", "BKYI63"),
    ],
)
def test_correccion_visual_unica_solo_propone(ocr, canonico):
    resultado = resolver_vehiculo_patente(
        patente_tracto=ocr,
        catalogo=_catalogo(_vehiculo(canonico)),
    )
    assert resultado.estado is EstadoResolucion.PROPUESTO
    assert resultado.patente_tracto_original == ocr
    assert resultado.patente_tracto_canonica == canonico
    assert resultado.requiere_revision
    assert any(
        e.tipo == "CORRECCION_VISUAL_UN_CARACTER"
        for e in resultado.evidencias
    )


def test_dos_candidatos_visuales_se_abstiene():
    resultado = resolver_vehiculo_patente(
        patente_tracto="8KYX63",
        catalogo=_catalogo(
            _vehiculo("BKYX63"),
            _vehiculo("BKYX63", vehiculo_id="otro"),
        ),
    )
    assert resultado.estado is EstadoResolucion.REQUIERE_REVISION
    assert resultado.entidad is None
    assert resultado.via_decision == "DUPLICADO"


def test_tracto_correcto_sin_rampla_no_inventa_rampla():
    resultado = resolver_vehiculo_patente(
        patente_tracto="BKYX63",
        catalogo=_catalogo(_vehiculo("BKYX63")),
    )
    assert resultado.estado is EstadoResolucion.CONFIRMADO
    assert resultado.patente_rampla_canonica is None
    assert resultado.contexto["rampla_disponibilidad"] == "AUSENTE"


def test_tracto_y_rampla_correctos_confirman_par():
    resultado = resolver_vehiculo_patente(
        patente_tracto="BKYX63",
        patente_rampla="WC1343",
        catalogo=_catalogo(
            _vehiculo("BKYX63"),
            _vehiculo("WC1343", "RAMPLA"),
        ),
    )
    assert resultado.estado is EstadoResolucion.CONFIRMADO
    assert resultado.patente_tracto_canonica == "BKYX63"
    assert resultado.patente_rampla_canonica == "WC1343"
    assert resultado.via_decision == "PAR_TRACTO_RAMPLA_EXACTO"


def test_tracto_y_rampla_intercambiados_materializan_contradiccion():
    resultado = resolver_vehiculo_patente(
        patente_tracto="WC1343",
        patente_rampla="BKYX63",
        catalogo=_catalogo(
            _vehiculo("BKYX63"),
            _vehiculo("WC1343", "RAMPLA"),
        ),
    )
    assert resultado.estado is EstadoResolucion.REQUIERE_REVISION
    assert resultado.via_decision == "TRACTO_RAMPLA_INTERCAMBIADOS"
    assert any(
        c.campos_enfrentados == ("patente_tracto", "patente_rampla")
        for c in resultado.contradicciones
    )


def test_camion_cajita_sin_rampla_marca_no_aplica():
    resultado = resolver_vehiculo_patente(
        patente="XF3629",
        tipo_vehiculo="camión cajita",
        catalogo=_catalogo(_vehiculo("XF3629", "CAMION_CAJITA")),
    )
    assert resultado.estado is EstadoResolucion.CONFIRMADO
    assert resultado.patente_rampla_canonica == "NO_APLICA"
    assert resultado.contexto["rampla_disponibilidad"] == "NO_APLICA"


def test_camion_cajita_con_falsa_rampla_exige_revision():
    resultado = resolver_vehiculo_patente(
        patente="XF3629",
        patente_rampla="WC1343",
        tipo_vehiculo="camión cajita",
        catalogo=_catalogo(
            _vehiculo("XF3629", "CAMION_CAJITA"),
            _vehiculo("WC1343", "RAMPLA"),
        ),
    )
    assert resultado.estado is EstadoResolucion.REQUIERE_REVISION
    assert any(
        c.campos_enfrentados == ("tipo_vehiculo", "patente_rampla")
        for c in resultado.contradicciones
    )


def test_guia_antigua_sin_rampla_no_fuerza_no_aplica():
    resultado = resolver_vehiculo_patente(
        patente_tracto="BKYX63",
        contexto={"guia_antigua": True},
        catalogo=_catalogo(_vehiculo("BKYX63")),
    )
    assert resultado.patente_rampla_canonica is None
    assert resultado.contexto["rampla_disponibilidad"] == "AUSENTE"


@pytest.mark.parametrize("patente", ["BK-YX.63", " bk yx 63 ", "bkyx63"])
def test_puntuacion_espacios_y_minusculas_solo_normalizan_comparacion(patente):
    resultado = resolver_vehiculo_patente(
        patente=patente,
        tipo_vehiculo="TRACTO",
        catalogo=_catalogo(_vehiculo("BKYX63")),
    )
    assert resultado.estado is EstadoResolucion.CONFIRMADO
    assert resultado.patente_original == patente


@pytest.mark.parametrize("patente", ["WC1343", "BKYX63"])
def test_formatos_chilenos_antiguo_y_nuevo(patente):
    tipo = "RAMPLA" if patente == "WC1343" else "TRACTO"
    resultado = resolver_vehiculo_patente(
        patente=patente,
        tipo_vehiculo=tipo,
        catalogo=_catalogo(_vehiculo(patente, tipo)),
    )
    assert resultado.estado is EstadoResolucion.CONFIRMADO


def test_duplicado_catalogo_requiere_revision():
    catalogo = _catalogo(
        _vehiculo("BKYX63", vehiculo_id="uno"),
        _vehiculo("BKYX63", vehiculo_id="dos"),
    )
    assert any(
        h.codigo == "PATENTE_DUPLICADA"
        for h in auditar_catalogo_vehiculos(catalogo)
    )
    resultado = resolver_vehiculo_patente(
        patente_tracto="BKYX63", catalogo=catalogo
    )
    assert resultado.estado is EstadoResolucion.REQUIERE_REVISION
    assert resultado.entidad is None


def test_rol_contradictorio_exige_revision():
    resultado = resolver_vehiculo_patente(
        patente_tracto="WC1343",
        catalogo=_catalogo(_vehiculo("WC1343", "RAMPLA")),
    )
    assert resultado.estado is EstadoResolucion.REQUIERE_REVISION
    assert resultado.contradicciones


def test_wc1343_alias_historico_nc1343_es_trazable():
    resultado = resolver_vehiculo_patente(
        patente_rampla="NC1343",
        catalogo=_catalogo(
            _vehiculo("WC1343", "RAMPLA", aliases=("NC1343",))
        ),
    )
    assert resultado.estado is EstadoResolucion.CONFIRMADO
    assert resultado.patente_rampla_original == "NC1343"
    assert resultado.patente_rampla_canonica == "WC1343"
    assert any(
        e.tipo == "ALIAS_PATENTE_HISTORICO" for e in resultado.evidencias
    )


def test_nombre_o_alias_sin_patente_solo_propone():
    resultado = resolver_vehiculo_patente(
        vehiculo="TRACTO AZUL",
        catalogo=_catalogo(
            _vehiculo("BKYX63", nombre="TRACTO AZUL")
        ),
    )
    assert resultado.estado is EstadoResolucion.PROPUESTO
    assert resultado.requiere_revision


def test_evidencia_parcial_insuficiente_no_resuelve():
    resultado = resolver_vehiculo_patente(
        patente="BKYX", catalogo=_catalogo(_vehiculo("BKYX63"))
    )
    assert resultado.estado is EstadoResolucion.NO_RESUELTO
    assert resultado.observaciones[2].disponibilidad is Disponibilidad.PARCIAL


def test_contexto_ajeno_no_fuerza_identidad():
    resultado = resolver_vehiculo_patente(
        patente="ZZZZ99",
        catalogo=_catalogo(_vehiculo("BKYX63")),
        contexto={
            "chofer": "CONDUCTOR BKYX63",
            "cliente": "CLIENTE BKYX63",
            "destino": "DESTINO BKYX63",
        },
    )
    assert resultado.estado is EstadoResolucion.NO_RESUELTO
    assert resultado.entidad is None


def test_snapshot_inmutable_determinista_y_catalogo_no_muta():
    catalogo = _catalogo(_vehiculo("BKYX63"))
    original = deepcopy(catalogo)
    snapshot = crear_snapshot_catalogo_vehiculos(catalogo)
    uno = resolver_vehiculo_patente(patente_tracto="BKYX63", catalogo=snapshot)
    assert catalogo == original
    catalogo["vehiculos"][0]["patente"] = "ZZZZ99"
    dos = resolver_vehiculo_patente(patente_tracto="BKYX63", catalogo=snapshot)
    assert uno == dos
    assert original != catalogo


def test_orden_del_catalogo_no_cambia_resultado():
    registros = [
        _vehiculo("BKYX63"),
        _vehiculo("WC1343", "RAMPLA"),
    ]
    directo = resolver_vehiculo_patente(
        patente_tracto="BKYX63",
        patente_rampla="WC1343",
        catalogo=_catalogo(*registros),
    )
    invertido = resolver_vehiculo_patente(
        patente_tracto="BKYX63",
        patente_rampla="WC1343",
        catalogo=_catalogo(*reversed(registros)),
    )
    assert directo == invertido
