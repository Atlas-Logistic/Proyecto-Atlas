from types import MappingProxyType

import pytest

from atlas_core.inteligencia import (
    EstadoResolucion,
    OrquestadorMulticampoSombra,
    ResumenResolucionSombra,
    SolicitudResolucionSombra,
    orquestar_multicampo_sombra,
    resolver_chofer_rut,
    resolver_cliente_rut,
    resolver_guia_transporte_fecha,
    resolver_material_tipo_carga,
    resolver_destino_ubicacion,
    resolver_vehiculo_patente,
)


CLIENTES = {"clientes": [{
    "cliente_id": "cliente-1",
    "razon_social": "CLIENTE DEMO SPA",
    "nombre_comercial": "",
    "rut": "760864285",
    "aliases": [],
    "estado_calidad": "CONFIRMADO",
    "estado_vigencia": "ACTIVO",
}]}
CHOFERES = {"760864285": {
    "nombre": "CHOFER DEMO",
    "aliases": [],
    "activo": True,
    "estado_calidad": "CONFIRMADO",
}}


def test_compone_resolvers_reales_sin_cambiar_sus_resultados():
    solicitud_cliente = SolicitudResolucionSombra(
        "cliente", resolver_cliente_rut,
        ("CLIENTE DEMO SPA", "76.086.428-5", CLIENTES),
    )
    solicitud_chofer = SolicitudResolucionSombra(
        "chofer", resolver_chofer_rut,
        ("CHOFER DEMO", "76.086.428-5", CHOFERES),
    )
    directo_cliente = resolver_cliente_rut(*solicitud_cliente.argumentos)
    directo_chofer = resolver_chofer_rut(*solicitud_chofer.argumentos)

    resultado = orquestar_multicampo_sombra(
        (solicitud_cliente, solicitud_chofer)
    )

    assert resultado.resultados["cliente"] == directo_cliente
    assert resultado.resultados["chofer"] == directo_chofer
    assert resultado.resumenes["cliente"].estado is EstadoResolucion.CONFIRMADO
    assert resultado.resumenes["chofer"].estado is EstadoResolucion.CONFIRMADO
    assert resultado.completo is True
    assert resultado.requiere_revision is False


def test_adapta_contratos_especializados_documento_y_material():
    resultado = orquestar_multicampo_sombra((
        SolicitudResolucionSombra(
            "documento", resolver_guia_transporte_fecha,
            opciones={"numero_guia": "123456"},
        ),
        SolicitudResolucionSombra(
            "material", resolver_material_tipo_carga,
            opciones={"descripcion_material_ocr": "BARRAS"},
        ),
    ))

    assert resultado.resumenes["documento"].estado is EstadoResolucion.PROPUESTO
    assert resultado.resumenes["material"].estado is EstadoResolucion.PROPUESTO
    assert resultado.requiere_revision is True


def test_compone_todos_los_resolvers_estandar_sin_conocer_sus_firmas():
    resultado = orquestar_multicampo_sombra((
        SolicitudResolucionSombra(
            "chofer", resolver_chofer_rut, ("", "", {}),
        ),
        SolicitudResolucionSombra(
            "cliente", resolver_cliente_rut,
            ("", "", {"clientes": []}),
        ),
        SolicitudResolucionSombra(
            "vehiculo", resolver_vehiculo_patente,
        ),
        SolicitudResolucionSombra(
            "destino", resolver_destino_ubicacion,
        ),
        SolicitudResolucionSombra(
            "documento", resolver_guia_transporte_fecha,
        ),
        SolicitudResolucionSombra(
            "material", resolver_material_tipo_carga,
        ),
    ))
    assert tuple(resultado.resultados) == (
        "chofer", "cliente", "vehiculo", "destino", "documento", "material"
    )
    assert resultado.completo is True


def test_adaptador_explicito_permite_contratos_externos_sin_duplicar_reglas():
    resultado_externo = object()

    def resumir(campo, resultado):
        assert resultado is resultado_externo
        return ResumenResolucionSombra(
            campo, EstadoResolucion.PROPUESTO, 0.5, True, 0
        )

    resultado = orquestar_multicampo_sombra((
        SolicitudResolucionSombra(
            "ruta", lambda: resultado_externo, resumidor=resumir
        ),
    ))
    assert resultado.resultados["ruta"] is resultado_externo
    assert resultado.resumenes["ruta"].estado is EstadoResolucion.PROPUESTO


def test_fallo_de_un_resolver_no_impide_los_demas():
    def falla():
        raise RuntimeError("detalle potencialmente sensible")

    resultado = orquestar_multicampo_sombra((
        SolicitudResolucionSombra("fallido", falla),
        SolicitudResolucionSombra(
            "documento", resolver_guia_transporte_fecha,
            opciones={"numero_guia": "123456"},
        ),
    ))

    assert resultado.fallos["fallido"].tipo_error == "RuntimeError"
    assert "detalle potencialmente sensible" not in repr(resultado.fallos)
    assert "documento" in resultado.resultados
    assert resultado.completo is False
    assert resultado.requiere_revision is True


def test_resultado_y_solicitud_son_inmutables():
    opciones = {"numero_guia": "123456"}
    solicitud = SolicitudResolucionSombra(
        "documento", resolver_guia_transporte_fecha, opciones=opciones
    )
    opciones["numero_guia"] = "654321"
    resultado = orquestar_multicampo_sombra((solicitud,))

    assert solicitud.opciones["numero_guia"] == "123456"
    with pytest.raises(TypeError):
        solicitud.opciones["numero_guia"] = "otro"
    with pytest.raises(TypeError):
        resultado.resultados["otro"] = object()


def test_orden_es_determinista_y_no_reordena_solicitudes():
    campos = ("zeta", "alfa")
    solicitudes = tuple(
        SolicitudResolucionSombra(
            campo, resolver_guia_transporte_fecha,
            opciones={"numero_guia": "123456"},
        )
        for campo in campos
    )
    resultado = OrquestadorMulticampoSombra().ejecutar(solicitudes)
    assert resultado.orden_ejecucion == campos
    assert tuple(resultado.resultados) == campos


def test_rechaza_campos_duplicados_antes_de_ejecutar():
    llamadas = []

    def resolver():
        llamadas.append(True)

    solicitudes = (
        SolicitudResolucionSombra("cliente", resolver),
        SolicitudResolucionSombra("cliente", resolver),
    )
    with pytest.raises(ValueError, match="una sola vez"):
        orquestar_multicampo_sombra(solicitudes)
    assert llamadas == []


def test_rechaza_resultado_que_no_cumple_contrato_multicampo():
    resultado = orquestar_multicampo_sombra((
        SolicitudResolucionSombra("invalido", lambda: object()),
    ))
    assert resultado.fallos["invalido"].tipo_error == "TypeError"
    assert resultado.resultados == MappingProxyType({})


@pytest.mark.parametrize("campo", ["", "  "])
def test_rechaza_nombre_de_campo_vacio(campo):
    with pytest.raises(ValueError):
        SolicitudResolucionSombra(campo, lambda: None)


def test_no_acepta_modo_productivo_en_fase_uno():
    resultado = orquestar_multicampo_sombra(())
    with pytest.raises(ValueError, match="solo admite modo SOMBRA"):
        type(resultado)(
            resultados={}, resumenes={}, fallos={}, orden_ejecucion=(),
            modo="PRODUCTIVO",
        )
