import logging
from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock

from atlas_core import procesamiento_masivo
from atlas_core.inteligencia.contrato_multicampo import EstadoResolucion
from atlas_core.inteligencia.resolucion_destino import resolver_destino_ubicacion
from atlas_core.politica_activacion_multicampo import (
    EstadoOperacional,
    REGISTRO_ACTIVACION_MULTICAMPO_FASE1,
)


CLIENTES = {"clientes": [{
    "cliente_id": "cliente-1",
    "razon_social": "CLIENTE DEMO SPA",
    "nombre_comercial": "",
    "rut": "",
    "aliases": [],
    "estado_calidad": "CONFIRMADO",
    "estado_vigencia": "ACTIVO",
}]}
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
PLANTAS = {"plantas": []}


def _argumentos_destino():
    return {
        "obra_destino": "BODEGA CENTRAL",
        "catalogo_destinos": DESTINOS,
        "catalogo_clientes": CLIENTES,
        "catalogo_plantas": PLANTAS,
        "id_cliente_canonico": "cliente-1",
        "cliente_canonico": "CLIENTE DEMO SPA",
        "contexto": {"fuente": "prueba"},
    }


def test_composicion_destino_conserva_el_resultado_directo():
    argumentos = _argumentos_destino()
    directo = resolver_destino_ubicacion(**argumentos)

    agregado = procesamiento_masivo._orquestar_destino_sombra(**argumentos)

    assert agregado.orden_ejecucion == ("destino",)
    assert agregado.resultados["destino"] == directo
    assert agregado.resumenes["destino"].estado is EstadoResolucion.CONFIRMADO
    assert agregado.completo is True
    assert agregado.modo == "SOMBRA"


def test_fallo_del_resolver_destino_queda_aislado(monkeypatch):
    def falla(**_kwargs):
        raise RuntimeError("detalle que no debe propagarse")

    monkeypatch.setattr(procesamiento_masivo, "resolver_destino_ubicacion", falla)

    agregado = procesamiento_masivo._orquestar_destino_sombra(
        **_argumentos_destino()
    )

    assert agregado.resultados == {}
    assert agregado.fallos["destino"].tipo_error == "RuntimeError"
    assert "detalle que no debe propagarse" not in repr(agregado.fallos)
    assert agregado.completo is False
    assert agregado.requiere_revision is True


def test_flujo_principal_ejecuta_destino_controlado_sin_autorizacion(
    tmp_path, monkeypatch, caplog
):
    datos = {
        "número de guía": "463309",
        "número de transporte": "0000123456",
        "cliente": "CLIENTE DEMO SPA",
        "obra destino": "BODEGA CENTRAL",
        "chofer": "CHOFER DEMO",
    }
    monkeypatch.setattr(
        procesamiento_masivo, "leer_texto_imagen", Mock(return_value=[])
    )
    monkeypatch.setattr(
        procesamiento_masivo, "extraer_datos", Mock(return_value=datos)
    )

    def cargar(ruta):
        return {
            "clientes.json": CLIENTES,
            "destinos.json": DESTINOS,
            "plantas.json": PLANTAS,
            "choferes.json": {},
        }.get(Path(ruta).name, {})

    monkeypatch.setattr(procesamiento_masivo, "cargar_catalogo_json", cargar)
    monkeypatch.setattr("atlas_core.catalogos.cargar_catalogo_json", cargar)

    with caplog.at_level(logging.INFO):
        salida = procesamiento_masivo.procesar_archivo(tmp_path / "guia.jpg")

    assert salida["obra_destino"] == "BODEGA CENTRAL"
    assert "orquestador-destino-sombra-v1 estado=CONFIRMADO" in caplog.text
    assert "estado_operacional=PRODUCTIVO_CONTROLADO publicar=False" in caplog.text


def test_publicacion_controlada_y_rollback_de_destino_aislan_otros_campos(
    tmp_path, monkeypatch, caplog
):
    datos = {
        "nÃºmero de guÃ­a": "463309",
        "nÃºmero de transporte": "0000123456",
        "cliente": "CLIENTE DEMO SPA",
        "obra destino": "BODEGA OCR",
        "chofer": "CHOFER DEMO",
    }
    destinos_con_alias = deepcopy(DESTINOS)
    destinos_con_alias["destinos"][0]["aliases"] = ["BODEGA OCR"]
    monkeypatch.setattr(
        procesamiento_masivo, "leer_texto_imagen", Mock(return_value=[])
    )
    monkeypatch.setattr(
        procesamiento_masivo,
        "extraer_datos",
        lambda _textos: dict(datos),
    )

    def cargar(ruta):
        return {
            "clientes.json": CLIENTES,
            "destinos.json": destinos_con_alias,
            "plantas.json": PLANTAS,
            "choferes.json": {},
        }.get(Path(ruta).name, {})

    monkeypatch.setattr(procesamiento_masivo, "cargar_catalogo_json", cargar)
    monkeypatch.setattr("atlas_core.catalogos.cargar_catalogo_json", cargar)

    sin_autorizacion = procesamiento_masivo.procesar_archivo(
        tmp_path / "sin-autorizacion.jpg"
    )
    with caplog.at_level(logging.INFO):
        autorizado = procesamiento_masivo.procesar_archivo(
            tmp_path / "autorizado.jpg",
            campos_controlados_autorizados={"destino"},
        )
    registro_rollback = dict(REGISTRO_ACTIVACION_MULTICAMPO_FASE1)
    registro_rollback["destino"] = EstadoOperacional.SOMBRA
    rollback = procesamiento_masivo.procesar_archivo(
        tmp_path / "rollback.jpg",
        registro_activacion=registro_rollback,
        campos_controlados_autorizados={"destino"},
    )

    assert sin_autorizacion["obra_destino"] == "BODEGA OCR"
    assert autorizado["obra_destino"] == "BODEGA CENTRAL"
    assert rollback["obra_destino"] == "BODEGA OCR"
    for campo in ("chofer", "cliente", "descripcion_material", "tipo_carga"):
        assert autorizado[campo] == sin_autorizacion[campo] == rollback[campo]
    assert "publicar=True motivo=publicacion-controlada-autorizada" in caplog.text


def test_fallo_de_destino_no_interrumpe_el_flujo_principal(
    tmp_path, monkeypatch, caplog
):
    datos = {
        "número de guía": "463309",
        "número de transporte": "0000123456",
        "cliente": "CLIENTE DEMO SPA",
        "obra destino": "DESTINO OCR",
        "chofer": "CHOFER DEMO",
    }
    monkeypatch.setattr(
        procesamiento_masivo, "leer_texto_imagen", Mock(return_value=[])
    )
    monkeypatch.setattr(
        procesamiento_masivo, "extraer_datos", Mock(return_value=datos)
    )
    monkeypatch.setattr(
        procesamiento_masivo, "cargar_catalogo_json", Mock(return_value={})
    )
    monkeypatch.setattr(
        "atlas_core.catalogos.cargar_catalogo_json", Mock(return_value={})
    )
    monkeypatch.setattr(
        procesamiento_masivo,
        "resolver_destino_ubicacion",
        Mock(side_effect=RuntimeError("fallo controlado")),
    )

    with caplog.at_level(logging.WARNING):
        salida = procesamiento_masivo.procesar_archivo(tmp_path / "guia.jpg")

    assert salida["obra_destino"] == "DESTINO OCR"
    assert "orquestador-destino-sombra-v1 fallo=RuntimeError" in caplog.text
