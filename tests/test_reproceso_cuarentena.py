import csv, json
from pathlib import Path

import pytest

from atlas_core.procesamiento_masivo import COLUMNAS
from atlas_core.reproceso_cuarentena import DocumentoSeleccionado, generar_candidato, promover_candidato


def _fila(archivo, transporte="0000000100"):
    r={c:"" for c in COLUMNAS}
    r.update(archivo=archivo,numero_guia="No encontrado",numero_transporte=transporte,
             cliente="CLIENTE REAL SA",rut_cliente="93.772.000-9",chofer="CHOFER REAL",
             rut_chofer="12.345.678-5",obra_destino="OBRA REAL",despachar_a_crudo="CALLE 10",
             estado_ruta="",estado_entrega="NO_INTENTADO")
    return r

def _raiz(tmp_path, filas):
    raiz=tmp_path/"atlas"; (raiz/"operacion/actual").mkdir(parents=True); (raiz/"catalogos_privados").mkdir()
    with (raiz/"operacion/actual/analisis_completo_guias.csv").open("w",newline="",encoding="utf-8-sig") as f:
        w=csv.DictWriter(f,fieldnames=COLUMNAS,delimiter=";");w.writeheader();w.writerows(filas)
    (raiz/"operacion/actual/decisiones_pendientes.json").write_text(json.dumps({"decisiones":[]}),encoding="utf-8")
    lote=raiz/"operacion/entradas/lote";lote.mkdir(parents=True)
    for f in filas:(lote/f["archivo"]).write_bytes(b"original-"+f["archivo"].encode())
    return raiz

def _extraido(guia, transporte, *, rut_cliente="93.772.000-9", destino="AVENIDA REAL 123"):
    return {"numero_guia":guia,"numero_transporte":transporte,"cliente":"CLIENTE REAL SA",
            "rut_cliente":rut_cliente,"chofer":"CHOFER REAL","rut_chofer":"12.345.678-5",
            "obra_destino":"OBRA REAL","despachar_a_crudo":destino,"direccion_entrega":"",
            "estado_ruta":"","estado_entrega":"NO_INTENTADO"}

def _sha(p):
    import hashlib
    return hashlib.sha256(p.read_bytes()).hexdigest()

def test_sha_incorrecto_aborta_sin_workspace(tmp_path):
    raiz=_raiz(tmp_path,[_fila("a.jpg")])
    with pytest.raises(ValueError,match="SHA_INCORRECTO"):
        generar_candidato(raiz_atlas=raiz,workspace=tmp_path/"q",documentos=[DocumentoSeleccionado("a.jpg","0"*64)],cardinalidad_esperada=1)
    assert not (tmp_path/"q").exists()

def test_cardinalidad_aborta_antes_de_escribir(tmp_path):
    raiz=_raiz(tmp_path,[_fila("a.jpg")])
    with pytest.raises(ValueError,match="CARDINALIDAD"):
        generar_candidato(raiz_atlas=raiz,workspace=tmp_path/"q",documentos=[DocumentoSeleccionado("a.jpg","x")],cardinalidad_esperada=2)
    assert not (tmp_path/"q").exists()

def test_dos_documentos_mismo_transporte_siguen_distintos_y_no_tocan_produccion(tmp_path,monkeypatch):
    filas=[_fila("a.jpg"),_fila("b.jpg")];raiz=_raiz(tmp_path,filas);dataset=raiz/"operacion/actual/analisis_completo_guias.csv";antes=dataset.read_bytes()
    valores=iter([_extraido("100001","0000000100"),_extraido("100002","0000000100")])
    monkeypatch.setattr("atlas_core.reproceso_cuarentena.procesar_archivo",lambda *a,**k:next(valores))
    q=tmp_path/"q";m=generar_candidato(raiz_atlas=raiz,workspace=q,documentos=[DocumentoSeleccionado("a.jpg",_sha(raiz/"operacion/entradas/lote/a.jpg")),DocumentoSeleccionado("b.jpg",_sha(raiz/"operacion/entradas/lote/b.jpg"))],cardinalidad_esperada=2,transporte_esperado="0000000100",proveedor_ocr=object())
    assert m["estado"]=="APTO_PARA_PROMOCION";assert dataset.read_bytes()==antes
    assert [d["fila_candidata"]["numero_guia"] for d in m["documentos"]]==["100001","100002"]
    assert (q/"catalogos").is_dir() and m["aislamiento"]["b1"]=="NO_EJECUTADO"

def test_defensas_rechazan_rut_chofer_y_etiqueta_administrativa(tmp_path,monkeypatch):
    raiz=_raiz(tmp_path,[_fila("a.jpg")]);p=raiz/"operacion/entradas/lote/a.jpg"
    monkeypatch.setattr("atlas_core.reproceso_cuarentena.procesar_archivo",lambda *a,**k:_extraido("100001","0000000100",rut_cliente="12.345.678-5",destino="DOCUMENTO"))
    m=generar_candidato(raiz_atlas=raiz,workspace=tmp_path/"q",documentos=[DocumentoSeleccionado("a.jpg",_sha(p))],cardinalidad_esperada=1,proveedor_ocr=object())
    assert m["estado"]=="NO_APTO_PARA_PROMOCION"
    assert any("COINCIDE_CON_RUT_CHOFER" in x for x in m["validaciones"])
    assert any("DIRECCION_NO_CREDIBLE" in x for x in m["validaciones"])

def test_ruta_residual_sin_endpoint_no_pasa_y_promocion_es_focal(tmp_path,monkeypatch):
    filas=[_fila("a.jpg"),_fila("otro.jpg","0000000200")];raiz=_raiz(tmp_path,filas)
    p=raiz/"operacion/entradas/lote/a.jpg";x=_extraido("100001","0000000100");x.update(estado_ruta="RUTA_CALCULADA",distancia_km="12",duracion_min="20",proveedor_ruta="ors")
    monkeypatch.setattr("atlas_core.reproceso_cuarentena.procesar_archivo",lambda *a,**k:x)
    q=tmp_path/"q";m=generar_candidato(raiz_atlas=raiz,workspace=q,documentos=[DocumentoSeleccionado("a.jpg",_sha(p))],cardinalidad_esperada=1,proveedor_ocr=object())
    assert m["estado"]=="APTO_PARA_PROMOCION" and m["documentos"][0]["fila_candidata"]["estado_ruta"]==""
    promover_candidato(raiz_atlas=raiz,workspace=q)
    with (raiz/"operacion/actual/analisis_completo_guias.csv").open(encoding="utf-8-sig",newline="") as f: rows=list(csv.DictReader(f,delimiter=";"))
    assert rows[0]["numero_guia"]=="100001" and rows[1]==filas[1]
    assert json.loads((q/"journal_promocion.json").read_text())["estado"]=="COMMIT"

def test_promocion_rollback_si_falla_decisiones(tmp_path,monkeypatch):
    raiz=_raiz(tmp_path,[_fila("a.jpg")]);p=raiz/"operacion/entradas/lote/a.jpg";dataset=raiz/"operacion/actual/analisis_completo_guias.csv";antes=dataset.read_bytes()
    monkeypatch.setattr("atlas_core.reproceso_cuarentena.procesar_archivo",lambda *a,**k:_extraido("100001","0000000100"))
    q=tmp_path/"q";generar_candidato(raiz_atlas=raiz,workspace=q,documentos=[DocumentoSeleccionado("a.jpg",_sha(p))],cardinalidad_esperada=1,proveedor_ocr=object())
    real=__import__("atlas_core.reproceso_cuarentena",fromlist=["escribir_json_atomico"]).escribir_json_atomico
    def falla(ruta, valor):
        if Path(ruta).name=="decisiones_pendientes.json": raise OSError("falla simulada")
        return real(ruta,valor)
    monkeypatch.setattr("atlas_core.reproceso_cuarentena.escribir_json_atomico",falla)
    with pytest.raises(OSError): promover_candidato(raiz_atlas=raiz,workspace=q)
    assert dataset.read_bytes()==antes
    assert json.loads((q/"journal_promocion.json").read_text())["estado"]=="ROLLBACK"

def test_candidato_no_levanta_cuarentena(tmp_path,monkeypatch):
    raiz=_raiz(tmp_path,[_fila("a.jpg")]);p=raiz/"operacion/entradas/lote/a.jpg"
    registro={"schema_version":1,"registros":[{"estado":"ACTIVA","archivo":"a.jpg","sha256_evidencia":_sha(p)}]}
    investigacion=raiz/"operacion/actual/documentos_en_investigacion.json";investigacion.write_text(json.dumps(registro),encoding="utf-8");antes=investigacion.read_bytes()
    monkeypatch.setattr("atlas_core.reproceso_cuarentena.procesar_archivo",lambda *a,**k:_extraido("100001","0000000100"))
    generar_candidato(raiz_atlas=raiz,workspace=tmp_path/"q",documentos=[DocumentoSeleccionado("a.jpg",_sha(p))],cardinalidad_esperada=1,proveedor_ocr=object())
    assert investigacion.read_bytes()==antes
