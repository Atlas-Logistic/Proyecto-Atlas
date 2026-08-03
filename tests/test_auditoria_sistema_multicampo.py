from types import MappingProxyType

import pytest

from atlas_core.inteligencia import (
    EstadoResolucion,
    SolicitudResolucionSombra,
    orquestar_multicampo_sombra,
    resolver_chofer_rut,
    resolver_cliente_rut,
    resolver_destino_ubicacion,
    resolver_material_tipo_carga,
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
DESTINOS = {"destinos": [{
    "destino_id": "destino-1",
    "cliente_id": "cliente-1",
    "nombre_destino": "BODEGA CENTRAL",
    "direccion": "CALLE UNO 123",
    "comuna": "RENCA",
    "region": "RM",
    "pais": "CHILE",
    "aliases": [],
    "estado_calidad": "CONFIRMADO",
    "estado_vigencia": "ACTIVO",
}]}
MATERIALES = {"materiales": [{
    "material_id": "material-1",
    "descripcion_oficial": "B HORMIGON 16 MM 12 M",
    "familia_material": "ACERO",
    "tipo_carga": "BARRAS",
    "aliases": [],
    "abreviaciones": [],
    "estado_calidad": "CONFIRMADO",
    "estado_vigencia": "ACTIVO",
}]}


def _solicitudes():
    return (
        SolicitudResolucionSombra(
            "chofer",
            resolver_chofer_rut,
            ("CHOFER DEMO", "76.086.428-5", CHOFERES),
        ),
        SolicitudResolucionSombra(
            "cliente",
            resolver_cliente_rut,
            ("CLIENTE DEMO SPA", "76.086.428-5", CLIENTES),
        ),
        SolicitudResolucionSombra(
            "destino",
            resolver_destino_ubicacion,
            opciones={
                "obra_destino": "BODEGA CENTRAL",
                "catalogo_destinos": DESTINOS,
                "catalogo_clientes": CLIENTES,
                "catalogo_plantas": {"plantas": []},
                "id_cliente_canonico": "cliente-1",
            },
        ),
        SolicitudResolucionSombra(
            "material",
            resolver_material_tipo_carga,
            opciones={
                "descripcion_material_ocr": "B HORMIGON 16 MM 12 M",
                "tipo_carga_ocr": "BARRAS",
                "catalogo_materiales": MATERIALES,
            },
        ),
    )


def test_los_cuatro_resolvers_componen_sin_cambiar_resultados():
    solicitudes = _solicitudes()
    directos = {
        solicitud.campo: solicitud.resolver(
            *solicitud.argumentos, **solicitud.opciones
        )
        for solicitud in solicitudes
    }

    agregado = orquestar_multicampo_sombra(solicitudes)

    assert agregado.orden_ejecucion == (
        "chofer", "cliente", "destino", "material"
    )
    assert agregado.resultados == directos
    assert all(
        resumen.estado is EstadoResolucion.CONFIRMADO
        for resumen in agregado.resumenes.values()
    )
    assert agregado.completo is True
    assert agregado.requiere_revision is False
    assert agregado.modo == "SOMBRA"


def test_un_fallo_no_contamina_los_otros_campos():
    def falla():
        raise RuntimeError("detalle sensible")

    solicitudes = list(_solicitudes())
    solicitudes[2] = SolicitudResolucionSombra("destino", falla)

    agregado = orquestar_multicampo_sombra(solicitudes)

    assert tuple(agregado.resultados) == ("chofer", "cliente", "material")
    assert agregado.fallos["destino"].tipo_error == "RuntimeError"
    assert "detalle sensible" not in repr(agregado.fallos)
    assert agregado.completo is False
    assert agregado.requiere_revision is True


def test_agregado_integral_es_inmutable():
    agregado = orquestar_multicampo_sombra(_solicitudes())

    assert isinstance(agregado.resultados, MappingProxyType)
    assert isinstance(agregado.resumenes, MappingProxyType)
    assert isinstance(agregado.fallos, MappingProxyType)
    with pytest.raises(TypeError):
        agregado.resultados["otro"] = object()
