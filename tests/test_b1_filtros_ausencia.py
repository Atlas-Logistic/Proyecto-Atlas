"""B1 nunca ignora una condición de ausencia. Caso real: «a cuantos viajes
les falta material» (con variaciones de escritura) respondía el total de
viajes del reporte. `viajes.csv` sintético propio: cada viaje carece de
un solo campo, así la cifra esperada identifica el filtro aplicado."""
from __future__ import annotations

import csv

import pytest

from atlas_core.consultas_atlas import ConsultaAtlas
from atlas_core.interpretador_consultas import validar_compatibilidad_semantica
from atlas_core.responder_consulta_atlas import (
    ESTADO_NO_INTERPRETABLE, ESTADO_OK, responder_consulta_atlas,
)

COLUMNAS = ("viaje_id", "numero_transporte", "fecha", "estado", "numeros_guia", "clientes", "obras_destino",
            "choferes", "patentes_tracto", "materiales", "tipos_carga", "peso_total_viaje_kg",
            "direccion_entrega", "localidad_entrega")
COMPLETO = {"fecha": "30-09-2026", "estado": "CONFIRMADO", "clientes": "CLIENTE A", "obras_destino": "OBRA A",
            "choferes": "PATRICK ORTIZ", "patentes_tracto": "XF3629", "materiales": "BARRA 12MM",
            "tipos_carga": "BARRAS", "peso_total_viaje_kg": "1000", "direccion_entrega": "AV. CARRASCAL 5060",
            "localidad_entrega": "Quinta Normal"}
# campo vacío -> cuántos viajes lo tienen vacío
FALTANTES = {"materiales": 3, "choferes": 2, "clientes": 1, "peso_total_viaje_kg": 1, "fecha": 1,
             "direccion_entrega": 2}
COMPLETOS = 2


@pytest.fixture
def ruta(tmp_path):
    filas, n = [], 0
    for columna, cantidad in FALTANTES.items():
        for _ in range(cantidad):
            n += 1
            filas.append({**COMPLETO, "viaje_id": f"v{n}", "numero_transporte": f"T{n}",
                          "numeros_guia": str(100 + n), columna: "NO DETERMINADO" if n % 2 else ""})
    for _ in range(COMPLETOS):
        n += 1
        filas.append({**COMPLETO, "viaje_id": f"v{n}", "numero_transporte": f"T{n}", "numeros_guia": str(100 + n)})
    destino = tmp_path / "viajes.csv"
    with destino.open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader()
        escritor.writerows(filas)
    return destino


TOTAL = sum(FALTANTES.values()) + COMPLETOS


def _responder(pregunta, ruta, **kwargs):
    return responder_consulta_atlas(pregunta, ruta_viajes=ruta, **kwargs)


@pytest.mark.parametrize("pregunta, campo, esperado", [
    ("a cuantos viajes les falta material", "material", 3),
    ("¿A cuántos viajes les falta el material?", "material", 3),
    ("a cuantos viajes les fata material", "material", 3),
    ("cuantos viajes sin materal", "material", 3),
    ("cuantos viajes no tienen material", "material", 3),
    ("cuantos viajes no tiene materiales", "material", 3),
    ("cuantos viajes con material faltante", "material", 3),
    ("cuantos viajes tienen faltante de material", "material", 3),
    ("cuantos viajes con material pendiente de identificar", "material", 3),
    ("cuantos viajes falta identificar el material", "material", 3),
    ("cuantos viajes con material desconocido", "material", 3),
    ("a cuantos viajes les falta el chofer", "chofer", 2),
    ("cuantos viajes les falta el chofr", "chofer", 2),
    ("cuantos viajes no tienen conductor", "chofer", 2),
    ("cuantos viajes con chofer faltante", "chofer", 2),
    ("cuantos viajes sin cliente", "cliente", 1),
    ("a cuantos viajes les falta el clinte", "cliente", 1),
    ("cuantos viajes no tienen peso", "peso", 1),
    ("cuantos viajes con peso pendiente de identificar", "peso", 1),
    ("cuantos viajes sin fecha", "fecha", 1),
    ("a cuantos viajes les falta la fecha", "fecha", 1),
    ("cuantos viajes les falta la direccion", "destino", 2),
    ("cuantos viajes sin direccion de entrega", "destino", 2),
])
def test_ausencia_aplica_el_filtro_pedido(ruta, pregunta, campo, esperado):
    respuesta = _responder(pregunta, ruta)
    assert respuesta.estado == ESTADO_OK, respuesta.texto_respuesta
    assert respuesta.resultado.consulta_interpretada.filtros == {"ausente": campo}
    assert respuesta.resultado.resultado == esperado
    assert respuesta.resultado.resultado != TOTAL


def test_varias_ausencias_se_combinan(ruta):
    respuesta = _responder("cuantos viajes sin peso ni fecha", ruta)
    assert respuesta.resultado.consulta_interpretada.filtros == {"ausente": "peso,fecha"}
    assert respuesta.resultado.resultado == 0


def test_consulta_sin_filtros_da_el_total(ruta):
    respuesta = _responder("cuantos viajes hay", ruta)
    assert respuesta.estado == ESTADO_OK
    assert respuesta.resultado.consulta_interpretada.filtros == {}
    assert respuesta.resultado.resultado == TOTAL


@pytest.mark.parametrize("pregunta", [
    "cuantos viajes les falta el color",
    "cuantos viajes no tienen sello",
    "cuantos viajes sin material y sin color",
])
def test_condicion_desconocida_informa_la_limitacion(ruta, pregunta):
    class ProveedorQueDescarta:
        nombre = "prueba"

        def interpretar(self, pregunta, catalogos):
            raise AssertionError("una condición no aplicable no se delega al proveedor")

    respuesta = _responder(pregunta, ruta, proveedor_interpretacion=ProveedorQueDescarta())
    assert respuesta.estado == ESTADO_NO_INTERPRETABLE
    assert respuesta.resultado is None
    assert "No pude aplicar la condición" in respuesta.texto_respuesta
    assert "material" in respuesta.texto_respuesta and str(TOTAL) not in respuesta.texto_respuesta


def test_consulta_que_omite_la_ausencia_pedida_es_incompatible():
    sin_filtro = ConsultaAtlas(metrica="COUNT_VIAJES", filtros={})
    assert validar_compatibilidad_semantica("cuantos viajes les falta material", sin_filtro) is not None
    con_filtro = ConsultaAtlas(metrica="COUNT_VIAJES", filtros={"ausente": "material"})
    assert validar_compatibilidad_semantica("cuantos viajes les falta material", con_filtro) is None


def test_proveedor_que_descarta_la_ausencia_no_produce_el_total(ruta):
    class ProveedorSinFiltro:
        nombre = "prueba"

        def interpretar(self, pregunta, catalogos):
            return ConsultaAtlas(metrica="COUNT_VIAJES", filtros={})

    # «Zeta» no es una entidad conocida: el determinístico cede al proveedor.
    respuesta = _responder("cuantos viajes de Zeta sin material", ruta, proveedor_interpretacion=ProveedorSinFiltro())
    assert respuesta.estado != ESTADO_OK
    assert respuesta.resultado is None


@pytest.mark.parametrize("pregunta", ["cuantos viajes salieron a Salta", "cuantos viajes pasaron por el peaje"])
def test_correccion_no_toca_palabras_fuera_de_la_ausencia(ruta, pregunta):
    respuesta = _responder(pregunta, ruta)
    assert respuesta.resultado is None or "ausente" not in respuesta.resultado.consulta_interpretada.filtros
