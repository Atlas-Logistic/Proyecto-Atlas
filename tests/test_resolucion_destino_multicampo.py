from __future__ import annotations

from copy import deepcopy

import pytest

from atlas_core.inteligencia.contrato_multicampo import EstadoResolucion
from atlas_core.inteligencia.resolucion_destino import (
    auditar_catalogo_destinos,
    resolver_destino_ubicacion,
)
from atlas_core.inteligencia.snapshot_catalogo_destinos import (
    crear_snapshot_catalogo_destinos,
)


def _cliente(cliente_id, nombre):
    return {
        "cliente_id": cliente_id,
        "razon_social": nombre,
        "nombre_comercial": "",
        "rut": "",
        "aliases": [],
    }


def _destino(
    destino_id,
    cliente_id,
    nombre,
    direccion,
    comuna="RENCA",
    region="RM",
    *,
    aliases=(),
    calidad="CONFIRMADO",
    activo=True,
):
    return {
        "destino_id": destino_id,
        "cliente_id": cliente_id,
        "nombre_destino": nombre,
        "direccion": direccion,
        "comuna": comuna,
        "region": region,
        "pais": "CHILE",
        "aliases": list(aliases),
        "estado_calidad": calidad,
        "estado_vigencia": "ACTIVO" if activo else "INACTIVO",
    }


def _planta(planta_id, nombre, direccion, comuna):
    return {
        "planta_id": planta_id,
        "nombre": nombre,
        "direccion": direccion,
        "comuna": comuna,
        "region": "REGIÓN METROPOLITANA",
        "estado_calidad": "CONFIRMADA",
        "estado_vigencia": "ACTIVA",
    }


def _catalogos(*destinos):
    return (
        {"destinos": list(destinos)},
        {
            "clientes": [
                _cliente("c1", "CLIENTE UNO SA"),
                _cliente("c2", "CLIENTE DOS SA"),
            ]
        },
        {
            "plantas": [
                _planta("p-colina", "AZA COLINA", "AV. FREI 18500", "COLINA"),
                _planta("p-renca", "AZA RENCA", "LA UNIÓN 3070", "RENCA"),
            ]
        },
    )


def _resolver(*destinos, **kwargs):
    d, c, p = _catalogos(*destinos)
    return resolver_destino_ubicacion(
        catalogo_destinos=d,
        catalogo_clientes=c,
        catalogo_plantas=p,
        **kwargs,
    )


def test_destino_exacto_activo_confirma_y_conserva_original():
    original = "  Bodega Central "
    resultado = _resolver(
        _destino("d1", "c1", "BODEGA CENTRAL", "CALLE UNO 123, RENCA"),
        obra_destino=original,
    )
    assert resultado.estado is EstadoResolucion.CONFIRMADO
    assert resultado.destino_original == original
    assert resultado.destino_canonico == "BODEGA CENTRAL"
    assert resultado.id_destino_canonico == "d1"


def test_alias_exacto_unico_confirma():
    resultado = _resolver(
        _destino(
            "d1", "c1", "BODEGA CENTRAL", "CALLE UNO 123, RENCA",
            aliases=("CENTRAL NORTE",),
        ),
        obra_destino="central norte",
    )
    assert resultado.estado is EstadoResolucion.CONFIRMADO
    assert resultado.via_decision == "ALIAS_EXACTO_UNICO"


def test_nombre_fuzzy_con_direccion_exacta_confirma():
    resultado = _resolver(
        _destino("d1", "c1", "BODEGA CENTRAL", "CALLE UNO 123, RENCA"),
        obra_destino="BODEGA CENTRA1",
        direccion="CALLE UNO 123",
    )
    assert resultado.estado is EstadoResolucion.CONFIRMADO
    assert resultado.via_decision == "FUZZY_MAS_DIRECCION"


def test_direccion_parcial_unica_solo_propone():
    resultado = _resolver(
        _destino("d1", "c1", "CENTRO LOGISTICO", "CAMINO NORTE 123, RENCA"),
        direccion="CAMINO NORTE",
    )
    assert resultado.estado is EstadoResolucion.PROPUESTO
    assert resultado.requiere_revision


def test_cliente_con_multiples_destinos_no_se_copia_como_destino():
    resultado = _resolver(
        _destino("d1", "c1", "OBRA NORTE", "CALLE UNO 123, RENCA"),
        _destino("d2", "c1", "OBRA SUR", "CALLE DOS 456, RENCA"),
        id_cliente_canonico="c1",
    )
    assert resultado.estado is EstadoResolucion.NO_RESUELTO
    assert resultado.destino_canonico is None


def test_dos_nombres_parecidos_fuzzy_se_abstienen():
    resultado = _resolver(
        _destino("d1", "c1", "CENTRO LOGISTICO NORTE", "UNO 123, RENCA"),
        _destino("d2", "c1", "CENTRO LOGISTICO SUR", "DOS 456, RENCA"),
        obra_destino="CENTRO LOGISTICO",
    )
    assert resultado.estado is not EstadoResolucion.CONFIRMADO


def test_nombre_y_direccion_contradictorios():
    resultado = _resolver(
        _destino("d1", "c1", "OBRA NORTE", "CALLE UNO 123, RENCA"),
        _destino("d2", "c1", "OBRA SUR", "CALLE DOS 456, RENCA"),
        obra_destino="OBRA NORTE",
        direccion="CALLE DOS 456",
    )
    assert resultado.estado is EstadoResolucion.REQUIERE_REVISION
    assert any(
        c.campos_enfrentados == ("obra_destino", "direccion")
        for c in resultado.contradicciones
    )


def test_comuna_y_region_correctas_salen_canonicas():
    resultado = _resolver(
        _destino("d1", "c1", "BODEGA CENTRAL", "CALLE UNO 123, RENCA"),
        obra_destino="BODEGA CENTRAL",
        comuna="RENCA",
        region="Región Metropolitana",
    )
    assert resultado.estado is EstadoResolucion.CONFIRMADO
    assert resultado.comuna_canonica == "RENCA"
    assert resultado.region_canonica == "REGIÓN METROPOLITANA"


def test_comuna_incompatible_exige_revision():
    resultado = _resolver(
        _destino("d1", "c1", "BODEGA CENTRAL", "CALLE UNO 123, RENCA"),
        obra_destino="BODEGA CENTRAL",
        comuna="QUILICURA",
        region="RM",
    )
    assert resultado.estado is EstadoResolucion.REQUIERE_REVISION


def test_region_ausente_no_impide_usar_region_del_catalogo():
    resultado = _resolver(
        _destino("d1", "c1", "BODEGA CENTRAL", "CALLE UNO 123, RENCA"),
        obra_destino="BODEGA CENTRAL",
    )
    assert resultado.estado is EstadoResolucion.CONFIRMADO
    assert resultado.region_original == ""
    assert resultado.region_canonica == "REGIÓN METROPOLITANA"


def test_destino_inexistente_no_inventa():
    resultado = _resolver(
        _destino("d1", "c1", "BODEGA CENTRAL", "CALLE UNO 123, RENCA"),
        obra_destino="NO EXISTE",
    )
    assert resultado.estado is EstadoResolucion.NO_RESUELTO
    assert resultado.entidad is None


def test_ocr_vacio_no_resuelto():
    resultado = _resolver()
    assert resultado.estado is EstadoResolucion.NO_RESUELTO
    assert resultado.requiere_revision


def test_destino_inactivo_requiere_revision():
    resultado = _resolver(
        _destino(
            "d1", "c1", "BODEGA CENTRAL", "CALLE UNO 123, RENCA",
            activo=False,
        ),
        obra_destino="BODEGA CENTRAL",
    )
    assert resultado.estado is EstadoResolucion.REQUIERE_REVISION
    assert resultado.via_decision == "INACTIVO"


def test_duplicado_catalogo_es_auditable_y_revisable():
    destinos = {
        "destinos": [
            _destino("d1", "c1", "BODEGA", "CALLE UNO 123, RENCA"),
            _destino("d2", "c1", "BODEGA", "CALLE UNO 123, RENCA"),
        ]
    }
    clientes = {"clientes": [_cliente("c1", "CLIENTE UNO SA")]}
    plantas = {"plantas": []}
    assert any(
        h.codigo == "DESTINO_DUPLICADO"
        for h in auditar_catalogo_destinos(destinos, clientes, plantas)
    )
    resultado = resolver_destino_ubicacion(
        obra_destino="BODEGA",
        direccion="CALLE UNO 123",
        catalogo_destinos=destinos,
        catalogo_clientes=clientes,
        catalogo_plantas=plantas,
    )
    assert resultado.estado is EstadoResolucion.REQUIERE_REVISION


@pytest.mark.parametrize(
    "direccion", ["Av. Central 123", "AV CENTRAL 123.", "avenida central 123"]
)
def test_direccion_puntuacion_y_abreviaturas(direccion):
    resultado = _resolver(
        _destino("d1", "c1", "CENTRO", "AVENIDA CENTRAL 123, RENCA"),
        direccion=direccion,
    )
    assert resultado.estado is EstadoResolucion.CONFIRMADO


def test_calle_con_error_ocr_mas_nombre_exacto_confirma():
    resultado = _resolver(
        _destino("d1", "c1", "CENTRO NORTE", "CAMINO CENTRAL 123, RENCA"),
        obra_destino="CENTRO NORTE",
        direccion="CAMINO CENTRA1 123",
    )
    assert resultado.estado is EstadoResolucion.CONFIRMADO


def test_numero_calle_incorrecto_es_contradiccion():
    resultado = _resolver(
        _destino("d1", "c1", "CENTRO NORTE", "CAMINO CENTRAL 123, RENCA"),
        obra_destino="CENTRO NORTE",
        direccion="CAMINO CENTRAL 124",
    )
    assert resultado.estado is EstadoResolucion.REQUIERE_REVISION
    assert any("número" in c.razon for c in resultado.contradicciones)


def test_alias_ambiguo_se_abstiene():
    resultado = _resolver(
        _destino(
            "d1", "c1", "CENTRO NORTE", "UNO 123, RENCA",
            aliases=("CENTRAL",),
        ),
        _destino(
            "d2", "c1", "CENTRO SUR", "DOS 456, RENCA",
            aliases=("CENTRAL",),
        ),
        obra_destino="CENTRAL",
    )
    assert resultado.estado is EstadoResolucion.REQUIERE_REVISION
    assert resultado.entidad is None


@pytest.mark.parametrize("generica", ["OBRA", "PLANTA", "BODEGA", "SUCURSAL"])
def test_palabra_generica_no_resuelve(generica):
    resultado = _resolver(
        _destino("d1", "c1", f"{generica} NORTE", "UNO 123, RENCA"),
        obra_destino=generica,
    )
    assert resultado.estado is EstadoResolucion.NO_RESUELTO


def test_cliente_correcto_con_destino_de_otro_cliente_contradice():
    resultado = _resolver(
        _destino("d2", "c2", "OBRA SUR", "DOS 456, RENCA"),
        obra_destino="OBRA SUR",
        id_cliente_canonico="c1",
    )
    assert resultado.estado is EstadoResolucion.REQUIERE_REVISION
    assert any(
        c.campos_enfrentados == ("cliente", "obra_destino")
        for c in resultado.contradicciones
    )


@pytest.mark.parametrize(
    ("planta", "esperada"),
    [("AZA COLINA", "AZA COLINA"), ("aza renca", "AZA RENCA")],
)
def test_planta_explicita_resuelve_sin_origen_por_defecto(planta, esperada):
    resultado = _resolver(
        _destino("d1", "c1", "CENTRO", "UNO 123, RENCA"),
        obra_destino="CENTRO",
        planta_salida=planta,
    )
    assert resultado.estado is EstadoResolucion.CONFIRMADO
    assert resultado.planta_salida_canonica == esperada


def test_planta_ausente_permanece_no_resuelta():
    resultado = _resolver(
        _destino("d1", "c1", "CENTRO", "UNO 123, RENCA"),
        obra_destino="CENTRO",
    )
    assert resultado.estado is EstadoResolucion.CONFIRMADO
    assert resultado.planta_salida_canonica is None


def test_planta_ocr_y_documental_contradictorias():
    resultado = _resolver(
        _destino("d1", "c1", "CENTRO", "UNO 123, RENCA"),
        obra_destino="CENTRO",
        planta_salida="AZA COLINA",
        planta_documental="AZA RENCA",
    )
    assert resultado.estado is EstadoResolucion.REQUIERE_REVISION
    assert resultado.planta_salida_canonica is None


def test_rutas_distancias_no_fuerzan_planta():
    resultado = _resolver(
        _destino("d1", "c1", "CENTRO", "UNO 123, RENCA"),
        obra_destino="CENTRO",
        contexto={
            "ruta": "AZA COLINA->DESTINO",
            "kilometros": 1,
            "planta_mas_cercana": "AZA COLINA",
        },
    )
    assert resultado.planta_salida_canonica is None


def test_no_modifica_catalogos_y_snapshot_es_inmutable():
    d, c, p = _catalogos(
        _destino("d1", "c1", "CENTRO", "UNO 123, RENCA")
    )
    originales = deepcopy((d, c, p))
    snapshot = crear_snapshot_catalogo_destinos(d, c, p)
    uno = resolver_destino_ubicacion(
        obra_destino="CENTRO", catalogo_destinos=snapshot
    )
    assert (d, c, p) == originales
    d["destinos"][0]["nombre_destino"] = "CAMBIADO"
    dos = resolver_destino_ubicacion(
        obra_destino="CENTRO", catalogo_destinos=snapshot
    )
    assert uno == dos


def test_cliente_y_destino_se_mantienen_separados():
    resultado = _resolver(
        _destino("d1", "c1", "OBRA NORTE", "UNO 123, RENCA"),
        cliente_canonico="CLIENTE UNO SA",
    )
    assert resultado.estado is EstadoResolucion.NO_RESUELTO
    assert resultado.destino_canonico is None


def test_evidencia_insuficiente_abstencion_segura():
    resultado = _resolver(
        _destino("d1", "c1", "CENTRO NORTE", "UNO 123, RENCA"),
        comuna="RENCA",
        region="RM",
    )
    assert resultado.estado is EstadoResolucion.NO_RESUELTO
    assert resultado.entidad is None
