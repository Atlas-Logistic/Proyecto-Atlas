import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock

import pytest

from atlas_core import procesamiento_masivo
from atlas_core.catalogo_clientes import CatalogoClientes
from atlas_core.catalogo_destinos import CatalogoDestinos
from atlas_core.catalogo_obras_destinos import (
    CatalogoObrasDestinos,
    Evidencia,
    ResultadoEvidencia,
    TipoEvidencia,
)
from atlas_core.ocr import BloqueOCR
from atlas_core.extractor import _extraer_rut_cliente_geometrico
from atlas_core.procesamiento_masivo import (
    _corroborar_obra_destino_confirmada,
    procesar_archivo,
)


class Reloj:
    def __init__(self):
        self.actual = datetime(2026, 1, 1, tzinfo=timezone.utc)

    def __call__(self):
        valor = self.actual
        self.actual += timedelta(seconds=1)
        return valor


class Ids:
    def __init__(self):
        self.n = 0

    def __call__(self):
        self.n += 1
        return f"id-{self.n}"


def evidencia(identificador="guia-1", resultado="SOPORTA"):
    return Evidencia(
        tipo=TipoEvidencia.GUIA.value,
        identificador_fuente=identificador,
        referencia_hash="a" * 64,
        campos_observados={"obra": "OBRA NORTE"},
        fecha="2026-01-01T00:00:00+00:00",
        actor_proceso="test",
        resultado=resultado,
    )


def crear_entorno(tmp_path: Path, *, confirmar=True, contradice_obra=False):
    carpeta = tmp_path / "catalogos"
    clientes = carpeta / "clientes.json"
    destinos = carpeta / "destinos_maestros.json"
    reloj = Reloj()
    ids = Ids()
    cliente = CatalogoClientes(clientes, reloj=reloj, generador_id=ids).crear(
        razon_social="CLIENTE SINTETICO SA",
        rut="50.234.350-5",
        fuente="PRUEBA",
    )
    destino = CatalogoDestinos(
        destinos, ruta_clientes=clientes, reloj=reloj, generador_id=ids
    ).crear(
        cliente_id=cliente.cliente_id,
        nombre_destino="DESTINO NORTE",
        direccion="CALLE 123",
        pais="CHILE",
        fuente="PRUEBA",
    )
    catalogo = CatalogoObrasDestinos(
        carpeta / "obras_destinos.json",
        ruta_clientes=clientes,
        ruta_destinos=destinos,
        reloj=reloj,
        generador_id=ids,
    )
    resultado = catalogo.registrar_observacion(
        cliente_id=cliente.cliente_id,
        nombre_obra="OBRA NORTE",
        destino_id=destino.destino_id,
        evidencia=evidencia(resultado="CONTRADICE" if contradice_obra else "SOPORTA"),
    )
    catalogo.registrar_observacion(
        cliente_id=cliente.cliente_id,
        nombre_obra="OBRA NORTE",
        destino_id=destino.destino_id,
        evidencia=evidencia("guia-2"),
    )
    if confirmar:
        catalogo.confirmar_relacion(resultado.relacion.relacion_id, actor="HUMANO")
    return carpeta, catalogo, cliente, destino, resultado.relacion.relacion_id


def resolver(carpeta, **cambios):
    argumentos = {
        "cliente_texto": "CLIENTE SINTETICO SA",
        "rut_cliente": "50.234.350-5",
        "obra_documental": "OBRA NORTE",
        "identidad_cliente_corroborada": True,
    }
    argumentos.update(cambios)
    return _corroborar_obra_destino_confirmada(carpeta, **argumentos)


def test_confirmada_corrobora_por_rut_exacto(tmp_path):
    carpeta, _, _, destino, _ = crear_entorno(tmp_path)
    assert resolver(carpeta).destino.destino_id == destino.destino_id


def test_rut_cliente_geometrico_tolera_coma_ocr_con_dv_valido():
    bloques = [
        BloqueOCR("SEÑOR(ES)", ((155, 476), (237, 476), (237, 494), (155, 494)), 0.95),
        BloqueOCR("R.U.T.", ((156, 495), (201, 495), (201, 513), (156, 513)), 0.99),
        BloqueOCR(":50.234,350-5", ((377, 497), (487, 497), (487, 511), (377, 511)), 0.91),
    ]
    assert _extraer_rut_cliente_geometrico(bloques) == {"valor": "50.234.350-5"}


def test_rut_cliente_geometrico_no_acepta_coma_si_dv_es_invalido():
    bloques = [
        BloqueOCR("SEÑOR(ES)", ((155, 476), (237, 476), (237, 494), (155, 494)), 0.95),
        BloqueOCR("R.U.T.", ((156, 495), (201, 495), (201, 513), (156, 513)), 0.99),
        BloqueOCR(":50.234,350-4", ((377, 497), (487, 497), (487, 511), (377, 511)), 0.91),
    ]
    assert _extraer_rut_cliente_geometrico(bloques) == {}


def test_obra_candidata_y_relacion_pendiente_no_corroboran(tmp_path):
    carpeta, _, _, _, _ = crear_entorno(tmp_path, confirmar=False)
    assert resolver(carpeta) is None


@pytest.mark.parametrize("estado", ["RECHAZADA", "INACTIVA"])
def test_relacion_terminal_no_corroborra(tmp_path, estado):
    carpeta, catalogo, _, _, relacion_id = crear_entorno(tmp_path, confirmar=False)
    if estado == "RECHAZADA":
        catalogo.rechazar_relacion(relacion_id, actor="HUMANO")
    else:
        datos = json.loads(catalogo.ruta.read_text(encoding="utf-8"))
        datos["relaciones"][0]["estado"] = "INACTIVA"
        catalogo.ruta.write_text(json.dumps(datos), encoding="utf-8")
    assert resolver(carpeta) is None


def test_contradiccion_en_obra_no_corroborra(tmp_path):
    carpeta, _, _, _, _ = crear_entorno(tmp_path, contradice_obra=True)
    assert resolver(carpeta) is None


def test_contradiccion_en_relacion_no_corroborra(tmp_path):
    carpeta, catalogo, _, _, _ = crear_entorno(tmp_path)
    datos = json.loads(catalogo.ruta.read_text(encoding="utf-8"))
    contradice = evidencia("guia-contradice", "CONTRADICE").a_dict()
    datos["relaciones"][0]["evidencias"].append(contradice)
    catalogo.ruta.write_text(json.dumps(datos), encoding="utf-8")
    assert resolver(carpeta) is None


def test_cliente_distinto_obra_ausente_y_nombre_no_corroborado_abstienen(tmp_path):
    carpeta, _, _, _, _ = crear_entorno(tmp_path)
    assert resolver(carpeta, rut_cliente="90.970.000-0") is None
    assert resolver(carpeta, obra_documental="No encontrado") is None
    assert resolver(
        carpeta, rut_cliente="", cliente_texto="CLIENTE SINTETICX",
        identidad_cliente_corroborada=False,
    ) is None


def test_obra_ambigua_abstiene(tmp_path):
    carpeta, catalogo, cliente, destino, _ = crear_entorno(tmp_path)
    datos = json.loads(catalogo.ruta.read_text(encoding="utf-8"))
    duplicada = dict(datos["obras"][0])
    duplicada["obra_id"] = "obra-ambigua"
    duplicada["nombre_canonico"] = "OTRA OBRA"
    duplicada["nombre_normalizado"] = "OTRA OBRA"
    duplicada["aliases_documentales"] = ["OBRA NORTE"]
    datos["obras"].append(duplicada)
    catalogo.ruta.write_text(json.dumps(datos), encoding="utf-8")
    assert resolver(carpeta) is None


@pytest.mark.parametrize("contenido", [None, "{corrupto"])
def test_catalogo_ausente_o_corrupto_abstiene(tmp_path, contenido):
    carpeta, _, _, _, _ = crear_entorno(tmp_path)
    ruta = carpeta / "obras_destinos.json"
    ruta.unlink()
    if contenido is not None:
        ruta.write_text(contenido, encoding="utf-8")
    assert resolver(carpeta) is None


def test_procesamiento_corroborra_sin_escribir_catalogos(tmp_path, monkeypatch):
    carpeta, _, _, _, _ = crear_entorno(tmp_path)
    antes = {p.name: p.read_bytes() for p in carpeta.glob("*.json")}
    base = {
        "número de guía": "1", "número de transporte": "0000123456",
        "cliente": "CLIENTE SINTETICO SA", "obra destino": "No encontrado",
        "chofer": "CHOFER PRUEBA", "RUT del cliente": "50.234.350-5",
        "RUT del chofer": "50.234.350-5", "patente del tracto": "AB1234",
        "patente del carro": "CD5678",
    }
    etiqueta = BloqueOCR("OBRA DESTINO", ((10, 50), (115, 50), (115, 70), (10, 70)), 0.9)
    obra = BloqueOCR("OBRA NORTE", ((170, 50), (280, 50), (280, 70), (170, 70)), 0.9)
    monkeypatch.setattr(procesamiento_masivo, "leer_texto_imagen", Mock(return_value=["HORMIGON 10MM"]))
    monkeypatch.setattr(procesamiento_masivo, "leer_bloques_imagen", Mock(return_value=[obra, etiqueta]))
    monkeypatch.setattr(procesamiento_masivo, "extraer_datos", Mock(return_value=base))
    resultado = procesar_archivo(
        tmp_path / "guia.jpg", carpeta_catalogos=carpeta, proveedor_rutas=object()
    )
    assert resultado["obra_destino"] == "OBRA NORTE"
    assert "OBRA_DESTINO_SIN_CORROBORAR" not in resultado["motivos_revision_documento"]
    assert "CATALOGO_OBRA_DESTINO" in resultado["metodos_recuperacion_documento"]
    assert {p.name: p.read_bytes() for p in carpeta.glob("*.json")} == antes
    assert len(CatalogoObrasDestinos(
        carpeta / "obras_destinos.json",
        ruta_clientes=carpeta / "clientes.json",
        ruta_destinos=carpeta / "destinos_maestros.json",
    ).listar_relaciones()) == 1


def test_normalizacion_documental_permitida_puede_ser_corroborada(tmp_path, monkeypatch):
    carpeta, _, _, _, _ = crear_entorno(tmp_path)
    base = {
        "número de guía": "1", "número de transporte": "0000123456",
        "cliente": "CLIENTE SINTETICO SA", "obra destino": "I OBRA NORTE",
        "chofer": "CHOFER PRUEBA", "RUT del cliente": "50.234.350-5",
        "RUT del chofer": "50.234.350-5", "patente del tracto": "AB1234",
        "patente del carro": "CD5678",
    }
    monkeypatch.setattr(procesamiento_masivo, "leer_texto_imagen", Mock(return_value=["HORMIGON 10MM"]))
    monkeypatch.setattr(procesamiento_masivo, "leer_bloques_imagen", Mock(return_value=[]))
    monkeypatch.setattr(procesamiento_masivo, "extraer_datos", Mock(return_value=base))
    resultado = procesar_archivo(
        tmp_path / "guia.jpg", carpeta_catalogos=carpeta, proveedor_rutas=object()
    )
    assert resultado["obra_destino"] == "OBRA NORTE"
    assert "OBRA_DESTINO_SIN_CORROBORAR" not in resultado["motivos_revision_documento"]
