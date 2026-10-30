"""Contrato de faltantes por guía en las consultas de ausencia: guía y campo
afectado, operación B1 compatible y referencia al documento original, sin
alterar los conteos. `viajes.csv` y raíz Atlas sintéticos."""
from __future__ import annotations

import csv
import json

import pytest

from atlas_core.b1_operador import interpretar_determinista
from atlas_core.cli_consulta_atlas import _respuesta_a_dict
from atlas_core.faltantes_guia import _OPERACIONES
from atlas_core.responder_consulta_atlas import ESTADO_OK, responder_consulta_atlas

COLUMNAS = ("viaje_id", "numero_transporte", "fecha", "estado", "numeros_guia", "clientes", "obras_destino",
            "choferes", "patentes_tracto", "materiales", "tipos_carga", "peso_total_viaje_kg",
            "direccion_entrega", "localidad_entrega", "documentos_operacionales", "evidencias_documentos")


def _doc(guia, archivo, material="BARRA 12MM", fecha="30-09-2026"):
    return {"numero_guia": guia, "archivo": archivo, "descripcion_material": material, "peso_kg": "1000",
            "cliente": "CLIENTE A", "obra_destino": "OBRA A", "fecha": fecha}


def _viaje(vid, docs, *, detalle=True, **overrides):
    fila = {c: "" for c in COLUMNAS}
    fila.update({
        "viaje_id": vid, "numero_transporte": f"00000{vid[1:]:0>5}", "fecha": "30-09-2026", "estado": "CONFIRMADO",
        "numeros_guia": " | ".join(d["numero_guia"] for d in docs), "clientes": "CLIENTE A",
        "obras_destino": "OBRA A", "choferes": "PATRICK ORTIZ", "patentes_tracto": "XF3629",
        "materiales": " | ".join(d["descripcion_material"] for d in docs if d["descripcion_material"]),
        "tipos_carga": "BARRAS", "peso_total_viaje_kg": "1000", "direccion_entrega": "AV. CARRASCAL 5060",
        "localidad_entrega": "Quinta Normal",
    })
    if detalle:
        fila["documentos_operacionales"] = json.dumps(docs)
        fila["evidencias_documentos"] = json.dumps(docs)
    fila.update(overrides)
    return fila


@pytest.fixture
def entorno(tmp_path):
    raiz = tmp_path / "Atlas"
    lote = raiz / "operacion" / "entradas" / "lote1"
    lote.mkdir(parents=True)
    for nombre in ("100.jpg", "200.jpg", "201.jpg", "500.jpg", "700.jpg"):
        (lote / nombre).write_bytes(b"imagen")
    filas = [
        # Una guía sin material, original disponible.
        _viaje("v1", [_doc("100", "100.jpg", material="")]),
        # Dos guías, sólo la 201 sin material.
        _viaje("v2", [_doc("200", "200.jpg"), _doc("201", "201.jpg", material="NO DETERMINADO")]),
        # Dos guías sin detalle por documento: no se sabe cuál.
        _viaje("v3", [_doc("300", ""), _doc("301", "")], detalle=False, materiales=""),
        # Original no disponible.
        _viaje("v4", [_doc("400", "400.jpg", material="")]),
        # Guía sin número identificable.
        _viaje("v5", [_doc("No encontrado", "500.jpg", material="")], numeros_guia=""),
        # Fecha ausente en la guía (sin operación B1).
        _viaje("v6", [_doc("600", "600.jpg", fecha="")], fecha=""),
        # Folio repetido en dos documentos del reporte.
        _viaje("v7", [_doc("700", "700.jpg", material="")]),
        _viaje("v8", [_doc("700", "700b.jpg")]),
        # Completo.
        _viaje("v9", [_doc("900", "900.jpg")]),
    ]
    ruta = tmp_path / "viajes.csv"
    with ruta.open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader()
        escritor.writerows(filas)
    return ruta, raiz


def _faltantes(pregunta, entorno, *, con_raiz=True):
    ruta, raiz = entorno
    respuesta = responder_consulta_atlas(pregunta, ruta_viajes=ruta, raiz_atlas=raiz if con_raiz else None)
    assert respuesta.estado == ESTADO_OK, respuesta.texto_respuesta
    return respuesta, {(i["viaje_id"], i["numero_guia"]): i for i in respuesta.resultado.faltantes}


def _operacion(item, accion):
    return next(o for o in item["operaciones"] if o["accion"] == accion)


def test_conteo_y_viajes_no_cambian(entorno):
    respuesta, items = _faltantes("muéstrame los viajes sin material", entorno)
    viajes = {v["viaje_id"] for v in respuesta.resultado.viajes_soporte}
    assert viajes == {"v1", "v2", "v3", "v4", "v5", "v7"}
    assert respuesta.resultado.total_coincidencias == 6
    assert {i["viaje_id"] for i in items.values()} == viajes
    conteo, _ = _faltantes("cuantos viajes sin material", entorno)
    assert conteo.resultado.resultado == 6


def test_viaje_con_una_guia(entorno):
    _, items = _faltantes("muéstrame los viajes sin material", entorno)
    item = items[("v1", "100")]
    assert item["nivel"] == "GUIA" and item["campo"] == "material"
    assert item["campo_documental"] == "descripcion_material" and item["valor_actual"] == ""
    assert item["referencia_documental"]["disponible"] is True
    assert item["referencia_documental"]["estado"] == "ACTIVA_DESKTOP"
    corregir = _operacion(item, "DOCUMENTO_CORREGIR_CAMPO")
    assert corregir["habilitada"] and corregir["requiere_valor"]
    assert corregir["parametros"] == {"numero_guia": "100", "campo": "descripcion_material", "archivo": "100.jpg"}
    assert corregir["instruccion"] == "El material de la guía 100 es {valor}"
    assert _operacion(item, "DOCUMENTO_RECUPERAR_MATERIAL")["habilitada"]
    assert item["correccion_habilitada"] and item["limitacion"] is None


def test_varias_guias_solo_una_afectada(entorno):
    _, items = _faltantes("muéstrame los viajes sin material", entorno)
    assert ("v2", "201") in items and ("v2", "200") not in items
    assert items[("v2", "201")]["valor_actual"] == "NO DETERMINADO"


def test_varias_guias_sin_evidencia_suficiente(entorno):
    _, items = _faltantes("muéstrame los viajes sin material", entorno)
    item = items[("v3", None)]
    assert item["nivel"] == "VIAJE" and item["operaciones"] == []
    assert not item["correccion_habilitada"]
    assert "no se puede identificar" in item["limitacion"]


def test_documento_original_no_disponible(entorno):
    _, items = _faltantes("muéstrame los viajes sin material", entorno)
    item = items[("v4", "400")]
    assert item["referencia_documental"]["disponible"] is False
    assert item["referencia_documental"]["estado"] == "NO_ENCONTRADA"
    # El valor humano no necesita el original; la relectura OCR sí.
    assert _operacion(item, "DOCUMENTO_CORREGIR_CAMPO")["habilitada"]
    recuperar = _operacion(item, "DOCUMENTO_RECUPERAR_MATERIAL")
    assert not recuperar["habilitada"] and recuperar["instruccion"] is None and recuperar["motivo"]


def test_sin_raiz_la_referencia_no_se_verifica(entorno):
    _, items = _faltantes("muéstrame los viajes sin material", entorno, con_raiz=False)
    item = items[("v1", "100")]
    assert item["referencia_documental"]["estado"] == "NO_VERIFICADA"
    assert item["referencia_documental"]["disponible"] is None
    assert not _operacion(item, "DOCUMENTO_RECUPERAR_MATERIAL")["habilitada"]


@pytest.mark.parametrize("viaje, guia, motivo", [("v5", "No encontrado", "identificable"), ("v7", "700", "aparece en 2")])
def test_guia_no_identificable_deshabilita_la_correccion(entorno, viaje, guia, motivo):
    _, items = _faltantes("muéstrame los viajes sin material", entorno)
    item = items[(viaje, guia)]
    assert not item["correccion_habilitada"] and motivo in item["limitacion"]
    assert all(not o["habilitada"] and o["instruccion"] is None for o in item["operaciones"])


def test_campo_sin_operacion(entorno):
    _, items = _faltantes("muéstrame los viajes sin fecha", entorno)
    item = items[("v6", "600")]
    assert item["nivel"] == "GUIA" and item["campo_documental"] == "fecha"
    assert item["operaciones"] == [] and not item["correccion_habilitada"]
    assert "No existe una operación" in item["limitacion"]
    assert item["referencia_documental"]["estado"] == "NO_ENCONTRADA"


def test_dato_presente_en_guias_y_ausente_en_el_viaje(entorno):
    ruta, raiz = entorno
    filas = list(csv.DictReader(ruta.open(encoding="utf-8-sig"), delimiter=";"))
    filas[1]["choferes"] = ""  # v2: ambas guías traen chofer en su fila documental
    for f in filas[1:2]:
        evidencias = json.loads(f["evidencias_documentos"])
        for e in evidencias:
            e["chofer"] = "PATRICK ORTIZ"
        f["evidencias_documentos"] = json.dumps(evidencias)
    with ruta.open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader()
        escritor.writerows(filas)
    _, items = _faltantes("muéstrame los viajes sin chofer", entorno)
    item = items[("v2", None)]
    assert item["nivel"] == "VIAJE" and not item["correccion_habilitada"]
    assert "consolidado del viaje" in item["limitacion"]


def test_contrato_cli_solo_con_filtro_de_ausencia(entorno):
    ruta, raiz = entorno
    con = _respuesta_a_dict(responder_consulta_atlas("muéstrame los viajes sin material", ruta_viajes=ruta,
                                                     raiz_atlas=raiz))
    assert con["resultado"]["faltantes"]["version"] == 1
    assert len(con["resultado"]["faltantes"]["items"]) == 6
    json.dumps(con)  # serializable tal cual
    sin = _respuesta_a_dict(responder_consulta_atlas("cuantos viajes hay", ruta_viajes=ruta, raiz_atlas=raiz))
    assert "faltantes" not in sin["resultado"]
    assert sin["resultado"]["resultado"] == 9


@pytest.mark.parametrize("campo, definicion", [(c, d) for c, ds in _OPERACIONES.items() for d in ds])
def test_instrucciones_son_las_que_b1_ya_interpreta(campo, definicion):
    valor = "12450" if campo == "peso" else "VALOR DE PRUEBA"
    texto = definicion["instruccion"].replace("{guia}", "482553").replace("{valor}", valor)
    intencion = interpretar_determinista(texto)
    assert intencion is not None and intencion.accion == definicion["accion"], texto
    assert intencion.parametros["numero_guia"] == "482553"
    if "campo" in definicion:
        assert intencion.parametros["campo"] == definicion["campo"]
