"""B1 de catálogo de obras: sólo preview, confirmación y servicios canónicos.

Todos los casos usan el entorno temporal; nunca el directorio G ni catálogos
productivos.
"""
from __future__ import annotations

import hashlib

from atlas_core.b1_operador import OperadorB1, interpretar_determinista
from tests.test_acciones_operacionales import entorno  # noqa: F401 -- fixture temporal
from tests.test_b1_operador_obra import b1  # noqa: F401 -- fixture temporal


def _huella(ruta):
    return hashlib.sha256(ruta.read_bytes()).hexdigest()


def _estado(entorno):
    return (_huella(entorno["cat"] / "obras_destinos.json"),
            _huella(entorno["actual"] / "decisiones_pendientes.json"))


def test_interpreta_correccion_y_registro_de_catalogo():
    correccion = interpretar_determinista("corrige la obra Obra Vieja SA, Renca a Edificio Norte")
    assert correccion.accion == "OBRA_CORREGIR"
    assert correccion.menciones == {"obra": "OBRA VIEJA SA, RENCA"}
    assert correccion.parametros == {"nombre_canonico": "EDIFICIO NORTE"}
    registro = interpretar_determinista("registra la obra Torre Norte para el cliente Cliente Uno SA")
    assert registro.accion == "OBRA_REGISTRAR"
    assert registro.parametros == {"nombre_obra": "TORRE NORTE"}
    assert registro.menciones == {"cliente": "CLIENTE UNO SA"}


def test_corrige_obra_existente_con_preview_confirmacion_auditoria_y_sin_ids(entorno, b1):  # noqa: F811
    antes = _estado(entorno)
    respuesta = b1.atender("catalogo", "corrige la obra Obra Vieja SA, Renca a Edificio Norte")
    assert respuesta["estado"] == "PREVIEW_PENDIENTE"
    assert respuesta["preview"] == {
        "entidad": {"tipo": "obra"},
        "valor_actual": {"nombre": "OBRA VIEJA SA, RENCA"},
        "valor_propuesto": {"nombre": "EDIFICIO NORTE"},
        "revalidacion": "focal del catálogo de obras y conciliación de bandeja",
    }
    assert "Obra actual: OBRA VIEJA SA, RENCA" in respuesta["mensaje"]
    assert "Cambio propuesto: EDIFICIO NORTE" in respuesta["mensaje"]
    assert "obra_id" not in repr(respuesta) and "cliente_id" not in repr(respuesta)
    assert _estado(entorno) == antes

    aplicada = b1.atender("catalogo", "sí")
    assert aplicada["estado"] == "EJECUTADA"
    assert aplicada["resultado"]["obra"] == {"nombre": "EDIFICIO NORTE"}
    auditoria = b1.capa.auditoria()
    assert len(auditoria) == 1 and auditoria[0]["accion"] == "OBRA_CORREGIR"
    assert auditoria[0]["despues"]["nombre_canonico"] == "EDIFICIO NORTE"
    assert "OBRA VIEJA SA, RENCA" in auditoria[0]["despues"]["aliases"]


def test_registra_obra_inexistente_solo_con_datos_explicitos_y_repetir_no_duplica(entorno, b1):  # noqa: F811
    antes = _estado(entorno)
    falta_cliente = b1.atender("crear", "registra la obra Torre Nueva")
    assert falta_cliente["estado"] == "ACLARACION_REQUERIDA"
    assert _estado(entorno) == antes

    respuesta = b1.atender("crear", "registra la obra Torre Nueva para el cliente Cliente Uno SA")
    assert respuesta["estado"] == "PREVIEW_PENDIENTE"
    assert respuesta["preview"]["valor_actual"] == {"nombre": "no existe"}
    assert respuesta["preview"]["valor_propuesto"] == {"nombre": "TORRE NUEVA", "cliente": "CLIENTE UNO SA"}
    assert "Obra propuesta a crear: TORRE NUEVA" in respuesta["mensaje"]
    assert _estado(entorno) == antes

    assert b1.atender("crear", "confirmo")["estado"] == "EJECUTADA"
    assert len(b1.capa.auditoria()) == 1
    despues = _estado(entorno)
    assert b1.atender("crear", "sí")["estado"] == "SIN_PREVIEW_PENDIENTE"
    assert b1.atender("crear", "registra la obra Torre Nueva para el cliente Cliente Uno SA")["estado"] == "SIN_CAMBIOS"
    assert _estado(entorno) == despues and len(b1.capa.auditoria()) == 1


def test_ambiguedad_y_cancelacion_no_escriben(entorno, b1):  # noqa: F811
    antes = _estado(entorno)
    ambigua = b1.atender("ambigua", "corrige la obra Obra Vieja a Edificio Norte")
    assert ambigua["estado"] == "ACLARACION_REQUERIDA"
    assert {c["nombre"] for c in ambigua["candidatos"]} == {"OBRA VIEJA SA, RENCA", "OBRA VIEJA SA, COLINA"}
    assert "obra_id" not in repr(ambigua)
    assert b1.pendiente("ambigua") is None and _estado(entorno) == antes

    preview = b1.atender("cancelar", "registra la obra Torre Cancelada para el cliente Cliente Uno SA")
    assert preview["estado"] == "PREVIEW_PENDIENTE"
    assert b1.atender("cancelar", "no")["estado"] == "CANCELADA"
    assert b1.pendiente("cancelar") is None and _estado(entorno) == antes
