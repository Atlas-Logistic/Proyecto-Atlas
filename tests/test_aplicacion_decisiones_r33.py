import csv
import json
import os
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone

import pytest

import atlas_core.aplicacion_decisiones as modulo
from atlas_core.aplicacion_decisiones import DecisionObsoletaError, aplicar_decision_obra
from atlas_core.catalogo_clientes import CatalogoClientes, EstadoCalidadCliente
from atlas_core.catalogo_obras_destinos import CatalogoObrasDestinos, Evidencia, ResultadoEvidencia, TipoEvidencia
from atlas_core.decisiones_pendientes import crear_decision, detectar_decisiones_documento, generar_artefacto
from atlas_core.procesamiento_masivo import COLUMNAS


def _entorno(tmp_path):
    raiz=tmp_path/"Atlas"; catalogos=raiz/"catalogos_privados"; actual=raiz/"operacion"/"actual"; catalogos.mkdir(parents=True); actual.mkdir(parents=True)
    for nombre,contenido in {"clientes.json":{"version_formato":1,"clientes":[]},"empresas.json":{},"vehiculos.json":{},"obras_destinos.json":{"version_formato":1,"obras":[],"relaciones":[]},"destinos_maestros.json":{"version_formato":1,"destinos":[]}}.items():(catalogos/nombre).write_text(json.dumps(contenido),encoding="utf-8")
    cliente=CatalogoClientes(catalogos/"clientes.json").crear(razon_social="CLIENTE CANONICO SA",rut="50.234.350-5",fuente="TEST",estado_calidad=EstadoCalidadCliente.CONFIRMADO)
    dataset=actual/"analisis_completo_guias.csv"
    # Bloque R10: fila con esquema completo (COLUMNAS) -- ya no una fila
    # mínima de 2 columnas, porque REGISTRAR ahora dispara
    # `revalidar_y_regenerar_reporte` (fix de la revisión huérfana, caso
    # real 472163), que sí lee y valida el esquema del dataset completo.
    fila={c:"" for c in COLUMNAS}
    fila.update({"archivo":"100.png","estado_procesamiento":"OK","numero_guia":"100","numero_transporte":"T1",
                 "fecha":"01-08-2026","cliente":"CLIENTE CANONICO SA","obra_destino":"OBRA NUEVA",
                 "indicador_revision":"REVISAR","motivos_revision_documento":"OBRA_DESTINO_SIN_CORROBORAR"})
    with dataset.open("w",newline="",encoding="utf-8-sig") as archivo:
        escritor=csv.DictWriter(archivo,fieldnames=COLUMNAS,delimiter=";"); escritor.writeheader(); escritor.writerow(fila)
    decision=crear_decision(tipo="OBRA_DESCONOCIDA",entidad="OBRA",archivo="100.png",numero_guia="100",numero_transporte="T1",campo="obra_destino",valor_documental="OBRA NUEVA",valor_normalizado="OBRA NUEVA",identidad_resuelta=None,candidatos=(),motivos=("OBRA_NO_EXISTE_PARA_CLIENTE",),evidencias=({"tipo":"CLIENTE_RESUELTO","entidad_id":cliente.cliente_id},),acciones_permitidas=("REGISTRAR","NO_REGISTRAR","POSPONER"),contexto={"cliente_id":cliente.cliente_id,"cliente_canonico":cliente.razon_social})
    generar_artefacto(ruta_dataset=dataset,carpeta_catalogos=catalogos,decisiones=[decision],ruta_salida=actual/"decisiones_pendientes.json")
    return raiz,catalogos,actual,cliente,decision


def _pendientes(actual): return json.loads((actual/"decisiones_pendientes.json").read_text(encoding="utf-8"))["decisiones"]


def test_registrar_crea_obra_auditada_desaparece_y_se_reconoce_sin_ocr(tmp_path):
    raiz,catalogos,actual,cliente,decision=_entorno(tmp_path)
    resultado=aplicar_decision_obra(raiz_atlas=raiz,decision_id=decision["decision_id"],accion="REGISTRAR")
    obras=CatalogoObrasDestinos(ruta=catalogos/"obras_destinos.json",ruta_clientes=catalogos/"clientes.json",ruta_destinos=catalogos/"destinos_maestros.json").listar_obras()
    assert resultado["ok"] and len(obras)==1 and obras[0].cliente_id==cliente.cliente_id and obras[0].nombre_canonico=="OBRA NUEVA"
    assert _pendientes(actual)==[]
    nuevas=detectar_decisiones_documento(archivo="otra.png",datos={"número de guía":"101","cliente":"CLIENTE CANONICO SA","RUT del cliente":"50.234.350-5","obra destino":"OBRA NUEVA"},carpeta_catalogos=catalogos)
    assert not any(d["tipo"]=="OBRA_DESCONOCIDA" for d in nuevas)


def test_registrar_es_idempotente(tmp_path):
    raiz,catalogos,_,_,decision=_entorno(tmp_path)
    aplicar_decision_obra(raiz_atlas=raiz,decision_id=decision["decision_id"],accion="REGISTRAR")
    segunda=aplicar_decision_obra(raiz_atlas=raiz,decision_id=decision["decision_id"],accion="REGISTRAR")
    assert segunda["idempotente"] is True
    assert len(CatalogoObrasDestinos(ruta=catalogos/"obras_destinos.json",ruta_clientes=catalogos/"clientes.json",ruta_destinos=catalogos/"destinos_maestros.json").listar_obras())==1


def test_no_registrar_no_crea_obra_y_suprime_misma_evidencia(tmp_path):
    raiz,catalogos,actual,_,decision=_entorno(tmp_path)
    resultado=aplicar_decision_obra(raiz_atlas=raiz,decision_id=decision["decision_id"],accion="NO_REGISTRAR")
    assert resultado["ok"] and CatalogoObrasDestinos(ruta=catalogos/"obras_destinos.json",ruta_clientes=catalogos/"clientes.json",ruta_destinos=catalogos/"destinos_maestros.json").listar_obras()==[]
    ledger=json.loads((actual/"decisiones_aplicadas.json").read_text(encoding="utf-8")); assert ledger["aplicaciones"][0]["accion"]=="NO_REGISTRAR"
    generar_artefacto(ruta_dataset=actual/"analisis_completo_guias.csv",carpeta_catalogos=catalogos,decisiones=[decision],ruta_salida=actual/"decisiones_pendientes.json")
    assert _pendientes(actual)==[]


def test_posponer_no_escribe_y_conserva_pendiente(tmp_path):
    raiz,catalogos,actual,_,decision=_entorno(tmp_path); antes={p:p.read_bytes() for p in [catalogos/"obras_destinos.json",actual/"decisiones_pendientes.json"]}
    resultado=aplicar_decision_obra(raiz_atlas=raiz,decision_id=decision["decision_id"],accion="POSPONER")
    assert resultado["accion"]=="POSPONER" and not (actual/"decisiones_aplicadas.json").exists() and len(_pendientes(actual))==1
    assert antes=={p:p.read_bytes() for p in antes}


def test_estado_obsoleto_se_abstiene_sin_escribir(tmp_path):
    raiz,catalogos,actual,_,decision=_entorno(tmp_path); (actual/"analisis_completo_guias.csv").write_text("cambio",encoding="utf-8"); antes=(catalogos/"obras_destinos.json").read_bytes()
    with pytest.raises(DecisionObsoletaError): aplicar_decision_obra(raiz_atlas=raiz,decision_id=decision["decision_id"],accion="REGISTRAR")
    assert (catalogos/"obras_destinos.json").read_bytes()==antes


def test_cli_entrega_mensaje_de_obsolescencia_unicode_correcto_a_desktop(tmp_path):
    raiz,catalogos,actual,_,decision=_entorno(tmp_path)
    (actual/"analisis_completo_guias.csv").write_text("cambio externo",encoding="utf-8")
    script=Path(__file__).resolve().parents[1]/"aplicar_decision_pendiente.py"
    entorno={**os.environ,"PYTHONIOENCODING":"cp1252"}
    proceso=subprocess.run(
        [sys.executable,str(script),"--raiz-atlas",str(raiz),"--decision-id",decision["decision_id"],"--accion","REGISTRAR"],
        cwd=script.parent,env=entorno,capture_output=True,check=True,
    )
    # El transporte es ASCII JSON aun si Windows fuerza cp1252; JSON.parse
    # reconstruye el texto Unicode correcto para la UI.
    respuesta=json.loads(proceso.stdout.decode("ascii"))
    assert respuesta=={"ok":False,"error":"La decisión quedó obsoleta porque cambió el dataset."}


def _decision_obra(archivo,numero_guia,cliente,obra):
    return crear_decision(tipo="OBRA_DESCONOCIDA",entidad="OBRA",archivo=archivo,numero_guia=numero_guia,numero_transporte="T1",campo="obra_destino",valor_documental=obra,valor_normalizado=obra,identidad_resuelta=None,candidatos=(),motivos=("OBRA_NO_EXISTE_PARA_CLIENTE",),evidencias=({"tipo":"CLIENTE_RESUELTO","entidad_id":cliente.cliente_id},),acciones_permitidas=("REGISTRAR","NO_REGISTRAR","POSPONER"),contexto={"cliente_id":cliente.cliente_id,"cliente_canonico":cliente.razon_social})


# --- R3.3.1: obra global -- caso Construmart -> X / Easy -> X ---

def test_construmart_registra_x_y_easy_la_reconoce_sin_ocr_ni_segunda_obra(tmp_path):
    raiz,catalogos,actual,construmart,decision=_entorno(tmp_path)
    easy=CatalogoClientes(catalogos/"clientes.json").crear(razon_social="EASY RETAIL SA",rut="76.123.987-2",fuente="TEST",estado_calidad=EstadoCalidadCliente.CONFIRMADO)
    # crear a Easy cambió clientes.json -- se regenera el artefacto para que
    # catalogos_sha256 refleje el estado vigente antes de aplicar la decisión.
    generar_artefacto(ruta_dataset=actual/"analisis_completo_guias.csv",carpeta_catalogos=catalogos,decisiones=[decision],ruta_salida=actual/"decisiones_pendientes.json")

    resultado=aplicar_decision_obra(raiz_atlas=raiz,decision_id=decision["decision_id"],accion="REGISTRAR")
    assert resultado["ok"]
    obras=CatalogoObrasDestinos(ruta=catalogos/"obras_destinos.json",ruta_clientes=catalogos/"clientes.json",ruta_destinos=catalogos/"destinos_maestros.json").listar_obras()
    assert len(obras)==1
    obra_id_construmart=resultado["obra_id"]

    # Guía B: EASY trae la MISMA obra -- sin OCR, sólo lectura del catálogo ya migrado/actualizado.
    nuevas=detectar_decisiones_documento(archivo="200.png",datos={"número de guía":"200","cliente":"EASY RETAIL SA","RUT del cliente":"76.123.987-2","obra destino":"OBRA NUEVA"},carpeta_catalogos=catalogos)
    assert not any(d["tipo"]=="OBRA_DESCONOCIDA" for d in nuevas)  # 0 OBRA_DESCONOCIDA

    # Si Easy también "registra" (observa) la misma obra, se reutiliza -- no se duplica.
    evidencia_easy=Evidencia(tipo=TipoEvidencia.GUIA.value,identificador_fuente="200",referencia_hash="b"*64,campos_observados={"obra":"OBRA NUEVA","cliente_id_observado":easy.cliente_id},fecha="2026-01-01T00:00:00+00:00",actor_proceso="TEST",resultado=ResultadoEvidencia.SOPORTA.value)
    resultado_easy=CatalogoObrasDestinos(ruta=catalogos/"obras_destinos.json",ruta_clientes=catalogos/"clientes.json",ruta_destinos=catalogos/"destinos_maestros.json").registrar_observacion(cliente_id=easy.cliente_id,nombre_obra="OBRA NUEVA",evidencia=evidencia_easy)
    assert resultado_easy.obra.obra_id==obra_id_construmart  # misma obra_id, no una segunda
    obras_final=CatalogoObrasDestinos(ruta=catalogos/"obras_destinos.json",ruta_clientes=catalogos/"clientes.json",ruta_destinos=catalogos/"destinos_maestros.json").listar_obras()
    assert len(obras_final)==1
    fuentes=[e.identificador_fuente for e in obras_final[0].evidencias]
    assert "100" in fuentes and "200" in fuentes  # evidencia operacional de ambos clientes conservada


def test_mismo_cliente_repite_obra_reutiliza_la_misma_obra(tmp_path):
    raiz,catalogos,actual,cliente,decision=_entorno(tmp_path)
    aplicar_decision_obra(raiz_atlas=raiz,decision_id=decision["decision_id"],accion="REGISTRAR")
    otra_decision=_decision_obra("101.png","101",cliente,"OBRA NUEVA")
    generar_artefacto(ruta_dataset=actual/"analisis_completo_guias.csv",carpeta_catalogos=catalogos,decisiones=[otra_decision],ruta_salida=actual/"decisiones_pendientes.json")
    resultado=aplicar_decision_obra(raiz_atlas=raiz,decision_id=otra_decision["decision_id"],accion="REGISTRAR")
    assert resultado["ok"]
    obras=CatalogoObrasDestinos(ruta=catalogos/"obras_destinos.json",ruta_clientes=catalogos/"clientes.json",ruta_destinos=catalogos/"destinos_maestros.json").listar_obras()
    assert len(obras)==1  # no se duplica para el mismo cliente tampoco


def test_fallo_posterior_revierte_catalogo_ledger_y_artefacto(tmp_path,monkeypatch):
    raiz,catalogos,actual,_,decision=_entorno(tmp_path); rutas=[catalogos/"obras_destinos.json",actual/"decisiones_pendientes.json"]; antes={p:p.read_bytes() for p in rutas}
    monkeypatch.setattr(modulo,"generar_artefacto",lambda **k: (_ for _ in ()).throw(OSError("fallo sintético")))
    with pytest.raises(OSError): aplicar_decision_obra(raiz_atlas=raiz,decision_id=decision["decision_id"],accion="REGISTRAR")
    assert antes=={p:p.read_bytes() for p in rutas} and not (actual/"decisiones_aplicadas.json").exists()
