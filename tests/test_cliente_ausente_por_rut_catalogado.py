"""Regresiones: cliente ausente resuelto por RUT maestro antes de B1."""

from __future__ import annotations

import json
from unittest.mock import Mock

import atlas_core.procesamiento_masivo as procesamiento
from atlas_core.atlas_ia.orquestador import ABSTENCION_IA, CLASIFICACION_C, ResultadoOrquestacion
from atlas_core.catalogo_clientes import CatalogoClientes, EstadoCalidadCliente
from atlas_core.procesamiento_masivo import (
    _completar_cliente_ausente_por_rut_catalogado,
    escalar_resultado_ia_en_memoria,
    procesar_archivo,
)

RUT = "50.234.350-5"


def _catalogo(tmp_path):
    carpeta = tmp_path / "catalogos"
    carpeta.mkdir()
    cliente = CatalogoClientes(carpeta / "clientes.json").crear(
        razon_social="CLIENTE CANONICO SA", rut=RUT, fuente="TEST",
        estado_calidad=EstadoCalidadCliente.CONFIRMADO,
    )
    return carpeta, cliente


def _procesar(tmp_path, carpeta, monkeypatch, *, rut):
    datos = {
        "número de guía": "900001", "número de transporte": "0000900000",
        "cliente": "No encontrado", "obra destino": "OBRA PRUEBA",
        "chofer": "JUAN PEREZ", "RUT del cliente": rut,
        "RUT del chofer": RUT, "patente del tracto": "AB1234",
        "patente del carro": "CD5678",
    }
    monkeypatch.setattr(procesamiento, "leer_texto_imagen", Mock(return_value=["DESPACHAR A CALLE UNO 100"]))
    monkeypatch.setattr(procesamiento, "leer_bloques_imagen", Mock(return_value=[]))
    monkeypatch.setattr(procesamiento, "extraer_datos", Mock(return_value=datos))
    return procesar_archivo(tmp_path / "guia.jpg", carpeta_catalogos=carpeta, proveedor_rutas=object())


def test_cliente_ausente_rut_catalogado_unico_completa_canonico(tmp_path, monkeypatch):
    carpeta, cliente = _catalogo(tmp_path)
    salida = _procesar(tmp_path, carpeta, monkeypatch, rut=RUT)

    assert salida["cliente"] == cliente.razon_social
    assert "CATALOGO_RUT_CLIENTE" in salida["metodos_recuperacion_documento"]
    assert "CLIENTE_AUSENTE" not in salida["motivos_revision_documento"]


def test_rut_desconocido_mantiene_cliente_ausente(tmp_path, monkeypatch):
    carpeta, _ = _catalogo(tmp_path)
    salida = _procesar(tmp_path, carpeta, monkeypatch, rut="76.111.111-6")

    assert salida["cliente"] == "No encontrado"
    assert "CLIENTE_AUSENTE" in salida["motivos_revision_documento"]
    assert "CATALOGO_RUT_CLIENTE" not in salida["metodos_recuperacion_documento"]


def test_rut_invalido_o_ambiguo_no_resuelve(tmp_path):
    carpeta, _ = _catalogo(tmp_path)
    invalido = {"cliente": "No encontrado", "RUT del cliente": "50.234.350-4"}
    assert _completar_cliente_ausente_por_rut_catalogado(invalido, carpeta) is False

    ruta = carpeta / "clientes.json"
    contenido = json.loads(ruta.read_text(encoding="utf-8"))
    duplicado = dict(contenido["clientes"][0])
    duplicado["cliente_id"] = "cliente-duplicado"
    duplicado["razon_social"] = "OTRO CLIENTE CANONICO SA"
    duplicado["nombre_normalizado"] = "OTRO CLIENTE CANONICO"
    contenido["clientes"].append(duplicado)
    ruta.write_text(json.dumps(contenido), encoding="utf-8")
    ambiguo = {"cliente": "No encontrado", "RUT del cliente": RUT}
    assert _completar_cliente_ausente_por_rut_catalogado(ambiguo, carpeta) is False
    assert ambiguo["cliente"] == "No encontrado"


class _OrquestadorContador:
    def __init__(self):
        self.campos = []

    def resolver(self, contexto):
        self.campos.append(contexto.campo)
        return ResultadoOrquestacion(ABSTENCION_IA, CLASIFICACION_C, contexto, rondas=1)


def test_b1_no_recibe_cliente_si_rut_catalogado_ya_lo_resolvio(tmp_path):
    carpeta, cliente = _catalogo(tmp_path)
    orquestador = _OrquestadorContador()
    salida, _ = escalar_resultado_ia_en_memoria(
        {
            "archivo": "mobile/envio/original.jpg", "numero_guia": "900001",
            "numero_transporte": "0000900000", "cliente": "No encontrado",
            "rut_cliente": RUT, "motivos_revision_documento": "CLIENTE_AUSENTE",
            "indicador_revision": "REVISAR", "estado_documental": "REQUIERE_REVISION",
        },
        [], orquestador_ia=orquestador, carpeta_catalogos=carpeta,
    )

    assert salida["cliente"] == cliente.razon_social
    assert "CLIENTE_AUSENTE" not in salida["motivos_revision_documento"]
    assert "CATALOGO_RUT_CLIENTE" in salida["metodos_recuperacion_documento"]
    assert "cliente" not in orquestador.campos
