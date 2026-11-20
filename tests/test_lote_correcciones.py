from dataclasses import replace
import copy
import pytest
from atlas_core.lote_correcciones import (DestinoOperacional, InstantaneaLote,
    ReferenciaDocumento, SolicitudLote, previsualizar_lote)


def datos(n=2):
    filas = tuple({"numero_guia": str(482000+i), "archivo": f"{i}.jpg", "numero_transporte": "0000364898", "fecha": "18-10-2026", "despachar_a_crudo": "SAN LUIS 1201 QUILICURA"} for i in range(n))
    refs = tuple(ReferenciaDocumento(f["numero_guia"]) for f in filas)
    return SolicitudLote("op-1", "mbt", "FECHA_EMISION", "19-10-2026", refs), InstantaneaLote("mbt", filas, (), (), frozenset())


@pytest.mark.parametrize("n", [2, 10, 100])
def test_lotes_completos(n):
    s, i = datos(n); r = previsualizar_lote(s, i)
    assert r["estado"] == "PREVIEW" and r["resumen"]["total"] == n
    assert len(r["documentos"]) == n and r["resumen"]["CAMBIARIA"] == n
    assert r["autoriza_escritura"] is False and "token" not in r


def test_duplicados_y_referencias_contradictorias():
    s, i = datos(); a = s.documentos[0]
    for refs, motivo in [((a,a), "GUIA_DUPLICADA"), ((a,replace(a, archivo="x")), "REFERENCIAS_CONTRADICTORIAS")]:
        r = previsualizar_lote(replace(s, documentos=refs), i)
        assert r["estado"] == "NO_APLICABLE"
        assert all(motivo in x["motivos"] for x in r["documentos"])


def test_ambigua_ausente_y_otra_empresa():
    s, i = datos()
    ambigua = replace(i, filas=i.filas + ({**i.filas[0], "archivo": "otra.jpg"},))
    assert "DOCUMENTO_AMBIGUO" in next(x for x in previsualizar_lote(s, ambigua)["documentos"] if x["numero_guia"] == "482000")["motivos"]
    for ref, motivo in [(ReferenciaDocumento("999999"), "DOCUMENTO_NO_ENCONTRADO"),
                        (replace(s.documentos[0], empresa_id="otra"), "EMPRESA_DISTINTA")]:
        r=previsualizar_lote(replace(s, documentos=(ref,)), i)
        assert motivo in r["documentos"][0]["motivos"] and r["estado"] == "NO_APLICABLE"
    with pytest.raises(ValueError): previsualizar_lote(s, replace(i, empresa_id="otra"))


def test_protegida_y_cuarentena():
    s, i = datos(); doc = {"archivo": "0.jpg", "numero_guia": "482000"}
    ledger = ({"documento": doc, "campo": "fecha", "actor": "OPERADOR", "tipo": "REVISION"},)
    r = previsualizar_lote(s, replace(i, aplicaciones=ledger, archivos_en_investigacion=frozenset({"0.jpg"})))
    assert r["estado"] == "NO_APLICABLE"
    assert {"CAMPO_PROTEGIDO", "EN_INVESTIGACION"} <= set(next(x for x in r["documentos"] if x["numero_guia"] == "482000")["motivos"])


@pytest.mark.parametrize("valor", ["2026-10-19", "31-02-2026", "19-10-2201"])
def test_fecha_invalida(valor):
    s,i=datos(); r=previsualizar_lote(replace(s, valor=valor), i)
    assert r["estado"] == "NO_APLICABLE" and all("VALOR_INVALIDO" in x["motivos"] for x in r["documentos"])


def test_destino_valida_sin_ruta_y_exige_comuna():
    s,i=datos(); s=replace(s,campo="DESTINO_OPERACIONAL",valor=DestinoOperacional("SAN LUIS 1201", "QUILICURA"))
    r=previsualizar_lote(s,i)
    assert r["estado"] == "PREVIEW"
    assert r["documentos"][0]["dependencias"]["ruta_y_coordenadas"] == "PENDIENTE_EVALUACION"
    assert r["documentos"][0]["dependencias"]["destino_documental"] == "SAN LUIS 1201 QUILICURA"
    assert previsualizar_lote(replace(s,valor=DestinoOperacional("SAN LUIS 1201", "")),i)["estado"] == "NO_APLICABLE"


def test_sin_cambios_y_huella():
    s,i=datos(); base=previsualizar_lote(s,i)
    invertida=previsualizar_lote(replace(s, documentos=tuple(reversed(s.documentos))), replace(i,filas=tuple(reversed(i.filas))))
    assert base["huella_plan"] == invertida["huella_plan"]
    cambiado=replace(i, filas=({**i.filas[0], "cliente": "CAMBIO"}, *i.filas[1:]))
    assert base["huella_plan"] != previsualizar_lote(s,cambiado)["huella_plan"]
    assert previsualizar_lote(replace(s,valor="18-10-2026"),i)["estado"] == "SIN_CAMBIOS"


def test_puro_sin_escrituras_ni_mutaciones(monkeypatch):
    s,i=datos(); anterior=copy.deepcopy((s,i))
    import builtins
    def prohibido(*a, **k): raise AssertionError("E/S no permitida")
    monkeypatch.setattr(builtins, "open", prohibido)
    monkeypatch.setattr("pathlib.Path.open", prohibido)
    previsualizar_lote(s,i)
    assert (s,i) == anterior


def test_destino_igual_sin_confirmacion_no_es_sin_cambios():
    s,i=datos(1); fila={**i.filas[0], "direccion_entrega": "SAN LUIS 1201", "localidad_entrega": "QUILICURA"}
    s=replace(s,campo="DESTINO_OPERACIONAL",valor=DestinoOperacional("SAN LUIS 1201", "Quilicura"))
    r=previsualizar_lote(s,replace(i,filas=(fila,)))
    assert r["documentos"][0]["resultado"] == "CAMBIARIA"
    assert not r["documentos"][0]["dependencias"]["destino_operacional_confirmado"]
    entrada={"tipo":"DESTINO_OPERACIONAL_DOCUMENTO", "documento":{"archivo":"0.jpg","numero_guia":"482000"},
             "destino_operacional":{"direccion":"SAN LUIS 1201","comuna":"QUILICURA"}, "conservar_estado_operacional":True}
    assert previsualizar_lote(s,replace(i,filas=(fila,),aplicaciones=(entrada,)))["estado"] == "SIN_CAMBIOS"


def test_estado_esperado_y_protecciones_cambian_huella():
    s,i=datos(); base=previsualizar_lote(s,i)
    d=next(x for x in base["documentos"] if x["numero_guia"] == "482000")
    r=replace(s.documentos[0],estado_esperado=d["huella_estado"])
    assert previsualizar_lote(replace(s,documentos=(r,)),i)["estado"] == "PREVIEW"
    assert previsualizar_lote(replace(s,documentos=(replace(r,estado_esperado="obsoleto"),)),i)["estado"] == "NO_APLICABLE"
    assert base["huella_plan"] != previsualizar_lote(s,replace(i,archivos_en_investigacion=frozenset({"0.jpg"})))["huella_plan"]


def test_empresa_en_fila_se_rechaza():
    s,i=datos(1); i=replace(i,filas=({**i.filas[0],"empresa_id":"otra"},))
    assert "EMPRESA_DISTINTA" in previsualizar_lote(s,i)["documentos"][0]["motivos"]


def test_archivo_reutilizado_por_otra_guia_es_ambiguo():
    s,i=datos(1); otra={**i.filas[0], "numero_guia":"499999"}
    r=previsualizar_lote(s,replace(i,filas=(*i.filas,otra)))
    assert "DOCUMENTO_AMBIGUO" in r["documentos"][0]["motivos"]
