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


def test_registrar_obra_corregida_conserva_ocr_como_alias_sin_duplicar_entidad(tmp_path):
    raiz,catalogos,_,cliente,decision=_entorno(tmp_path)
    resultado=aplicar_decision_obra(
        raiz_atlas=raiz, decision_id=decision["decision_id"], accion="REGISTRAR",
        nombre_obra_manual="OBRA CANONICA LIMITADA",
    )
    catalogo=CatalogoObrasDestinos(
        ruta=catalogos/"obras_destinos.json", ruta_clientes=catalogos/"clientes.json",
        ruta_destinos=catalogos/"destinos_maestros.json",
    )
    obras=catalogo.listar_obras()
    assert resultado["ok"] and len(obras) == 1
    assert obras[0].nombre_canonico == "OBRA CANONICA LIMITADA"
    assert obras[0].aliases_documentales == ("OBRA NUEVA",)
    nuevas=detectar_decisiones_documento(
        archivo="alias.png", datos={"número de guía":"101", "cliente":cliente.razon_social,
        "RUT del cliente":"50.234.350-5", "obra destino":"OBRA NUEVA"}, carpeta_catalogos=catalogos,
    )
    assert not any(d["tipo"] == "OBRA_DESCONOCIDA" for d in nuevas)


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


def test_fallo_posterior_revierte_catalogo_pero_nunca_el_artefacto(tmp_path,monkeypatch):
    """Fase 2 -- Regla absoluta: `obras_destinos.json` (escritura DIRECTA
    de esta decisión) sí se revierte, bajo su propio lock, verificado
    contra el checkpoint. `decisiones_pendientes.json` NUNCA se revierte
    por bytes -- ya está protegido por su propio lock desde Fase 1 y
    nunca queda a medio escribir (atómico); no hace falta ni es correcto
    restaurarlo."""
    raiz,catalogos,actual,_,decision=_entorno(tmp_path)
    ruta_obras = catalogos/"obras_destinos.json"; antes_obras = ruta_obras.read_bytes()
    monkeypatch.setattr(modulo,"generar_artefacto",lambda **k: (_ for _ in ()).throw(OSError("fallo sintético")))
    with pytest.raises(OSError): aplicar_decision_obra(raiz_atlas=raiz,decision_id=decision["decision_id"],accion="REGISTRAR")
    assert ruta_obras.read_bytes()==antes_obras and not (actual/"decisiones_aplicadas.json").exists()


def test_f_rollback_de_catalogo_concurrente_no_borra_actualizacion_ajena_posterior(tmp_path, monkeypatch):
    """Fase 2, criterio F: si `aplicar_decision_obra` falla DESPUÉS de
    escribir un catálogo (`obras_destinos.json`) y, en el ínterin, OTRA
    operación real escribió ESE MISMO catálogo, el revert se abstiene --
    nunca borra esa actualización ajena posterior."""
    raiz, catalogos, actual, cliente, decision = _entorno(tmp_path)
    ruta_obras = catalogos / "obras_destinos.json"

    def generar_artefacto_que_simula_otra_escritura_y_falla(**kwargs):
        # Simula: otra operación real registra OTRA obra en el MISMO
        # catálogo, justo en este instante (después de que esta decisión
        # ya escribió su propia obra, antes de que el fallo se dispare).
        CatalogoObrasDestinos(
            ruta=ruta_obras, ruta_clientes=catalogos / "clientes.json", ruta_destinos=catalogos / "destinos_maestros.json",
        ).registrar_observacion(
            cliente_id=cliente.cliente_id, nombre_obra="OBRA DE OTRO PROCESO",
            evidencia=Evidencia(
                tipo=TipoEvidencia.GUIA.value, identificador_fuente="999", referencia_hash="c" * 64,
                campos_observados={"obra": "OBRA DE OTRO PROCESO"}, fecha="2026-01-01T00:00:00+00:00",
                actor_proceso="OTRO_PROCESO", resultado=ResultadoEvidencia.SOPORTA.value,
            ),
        )
        raise OSError("fallo sintético")

    monkeypatch.setattr(modulo, "generar_artefacto", generar_artefacto_que_simula_otra_escritura_y_falla)
    with pytest.raises(OSError):
        aplicar_decision_obra(raiz_atlas=raiz, decision_id=decision["decision_id"], accion="REGISTRAR")

    obras = CatalogoObrasDestinos(
        ruta=ruta_obras, ruta_clientes=catalogos / "clientes.json", ruta_destinos=catalogos / "destinos_maestros.json",
    ).listar_obras()
    nombres = {o.nombre_canonico for o in obras}
    # La obra de "otro proceso" sobrevive intacta -- el revert nunca la pisó.
    assert "OBRA DE OTRO PROCESO" in nombres


# ============================================================
# Bloque HOMOLOGACIÓN OBRA -> OPERACIÓN -- caso real 0000359449/474381:
# Javier confirmó "LINSAS MONTAJES Y SERVICIOS" (OCR) == "LINEAS MONTAJES
# Y SERVICIOS HENAO SPA" (canónico); el catálogo quedaba correcto
# (nombre_canonico + alias_documental), pero la ficha del viaje seguía
# mostrando el texto documental porque nada reescribía `obra_destino` en
# el dataset -- ni al aplicar la decisión, ni al revalidar después. Estas
# pruebas usan la misma fixture `_entorno` (OCR "OBRA NUEVA" -> canónico
# "OBRA CANONICA LIMITADA") -- nunca los números reales del caso, nunca
# hardcodeados -- para que el mismo criterio valga para cualquier
# decisión de obra equivalente.
# ============================================================

def test_registrar_con_correccion_actualiza_la_fila_del_documento_al_canonico(tmp_path):
    """Items 1/2/4 del bloque: OCR trae una obra incorrecta, el humano
    confirma la obra canónica real, y la FICHA (el campo `obra_destino`
    del dataset que lee `gestor_viajes`/`entregas`/reportes) debe mostrar
    el canónico de inmediato -- sin esperar ninguna revalidación
    posterior, sin depender de que la fila tuviera un motivo bloqueante."""
    raiz, catalogos, actual, cliente, decision = _entorno(tmp_path)
    resultado = aplicar_decision_obra(
        raiz_atlas=raiz, decision_id=decision["decision_id"], accion="REGISTRAR",
        nombre_obra_manual="OBRA CANONICA LIMITADA",
    )
    assert resultado["ok"]

    dataset = actual / "analisis_completo_guias.csv"
    with dataset.open(encoding="utf-8-sig", newline="") as archivo:
        fila = next(csv.DictReader(archivo, delimiter=";"))
    assert fila["obra_destino"] == "OBRA CANONICA LIMITADA"


def test_registrar_con_correccion_conserva_el_valor_documental_para_trazabilidad(tmp_path):
    """Item 3: el OCR original NUNCA se pierde -- sigue disponible como
    alias en el catálogo (ya cubierto por
    test_registrar_obra_corregida_conserva_ocr_como_alias_sin_duplicar_
    entidad) y, aparte, como `valor_documental` auditable en el ledger de
    decisiones aplicadas -- la trazabilidad documental es independiente
    de qué se reescribe como operacional."""
    raiz, catalogos, actual, cliente, decision = _entorno(tmp_path)
    aplicar_decision_obra(
        raiz_atlas=raiz, decision_id=decision["decision_id"], accion="REGISTRAR",
        nombre_obra_manual="OBRA CANONICA LIMITADA",
    )
    ledger = json.loads((actual / "decisiones_aplicadas.json").read_text(encoding="utf-8"))
    assert ledger["aplicaciones"][0]["valor_documental"] == "OBRA NUEVA"


def test_viaje_y_entrega_muestran_la_obra_canonica_tras_aplicar_la_decision(tmp_path):
    """Items 4/5: la ficha del VIAJE y de la ENTREGA (las superficies
    operacionales reales que arma `gestor_viajes.agrupar_viajes`/
    `Viaje.entregas`) deben mostrar la obra canónica, nunca el texto
    documental -- integración end-to-end, no sólo la fila cruda."""
    from atlas_core.gestor_viajes import agrupar_viajes

    raiz, catalogos, actual, cliente, decision = _entorno(tmp_path)
    aplicar_decision_obra(
        raiz_atlas=raiz, decision_id=decision["decision_id"], accion="REGISTRAR",
        nombre_obra_manual="OBRA CANONICA LIMITADA",
    )
    dataset = actual / "analisis_completo_guias.csv"
    with dataset.open(encoding="utf-8-sig", newline="") as archivo:
        fila = next(csv.DictReader(archivo, delimiter=";"))
    # `_entorno` usa "T1" como transporte (válido para el contrato de
    # decisiones, que nunca exige transporte numérico) -- `agrupar_viajes`
    # sí lo exige (`transporte_valido`); se sustituye por uno numérico
    # sintético sólo para poder ejercer la agrupación real, sin tocar
    # ningún otro campo ya persistido por la decisión.
    fila["numero_transporte"] = "0000900001"

    viajes, pendientes = agrupar_viajes([fila])
    assert not pendientes
    assert len(viajes) == 1
    viaje = viajes[0]
    assert viaje.obras_destino == ["OBRA CANONICA LIMITADA"]
    assert len(viaje.entregas) == 1
    assert viaje.entregas[0]["obras_destino"] == ["OBRA CANONICA LIMITADA"]


def test_revalidar_de_nuevo_no_revierte_al_valor_documental(tmp_path):
    """Item 6: un "reload"/nueva revalidación posterior (Javier refresca
    Desktop, o corre la reconciliación de nuevo) nunca debe reintroducir
    el texto OCR ya corregido -- ni dejarlo como estaba, ni volver a
    escribirlo por error."""
    from atlas_core.revalidacion_documental import revalidar_obra_destino_sin_ocr

    raiz, catalogos, actual, cliente, decision = _entorno(tmp_path)
    aplicar_decision_obra(
        raiz_atlas=raiz, decision_id=decision["decision_id"], accion="REGISTRAR",
        nombre_obra_manual="OBRA CANONICA LIMITADA",
    )
    dataset = actual / "analisis_completo_guias.csv"

    revalidar_obra_destino_sin_ocr(ruta_dataset=dataset, carpeta_catalogos=catalogos)
    revalidar_obra_destino_sin_ocr(ruta_dataset=dataset, carpeta_catalogos=catalogos)

    with dataset.open(encoding="utf-8-sig", newline="") as archivo:
        fila = next(csv.DictReader(archivo, delimiter=";"))
    assert fila["obra_destino"] == "OBRA CANONICA LIMITADA"


def test_siguiente_aparicion_con_el_mismo_ocr_no_vuelve_a_preguntar(tmp_path):
    """Item 7: una vez homologado (alias único y fuerte -- una confirmación
    humana explícita), un documento FUTURO con el mismo texto OCR no debe
    generar una nueva tarjeta OBRA_DESCONOCIDA -- el aprendizaje ya
    existente (`detectar_decisiones_documento`, reconocimiento por alias)
    ya cubre esto; esta prueba sólo lo verifica explícitamente para el
    mismo escenario del bug real, con una guía y archivo distintos."""
    raiz, catalogos, actual, cliente, decision = _entorno(tmp_path)
    aplicar_decision_obra(
        raiz_atlas=raiz, decision_id=decision["decision_id"], accion="REGISTRAR",
        nombre_obra_manual="OBRA CANONICA LIMITADA",
    )
    from atlas_core.decisiones_pendientes import detectar_decisiones_documento

    nuevas = detectar_decisiones_documento(
        archivo="otra_guia_futura.png",
        datos={
            "número de guía": "555", "cliente": cliente.razon_social,
            "RUT del cliente": "50.234.350-5", "obra destino": "OBRA NUEVA",
        },
        carpeta_catalogos=catalogos,
    )
    assert not any(d["tipo"] == "OBRA_DESCONOCIDA" for d in nuevas)


def test_variante_realmente_desconocida_no_se_auto_homologa(tmp_path):
    """Item 8: un texto documental que NO coincide con ninguna obra/alias
    conocido es ambigüedad real -- `revalidar_obra_destino_sin_ocr` debe
    abstenerse (nunca inventar una homologación): ni reescribe
    `obra_destino`, ni retira el motivo bloqueante."""
    from atlas_core.revalidacion_documental import revalidar_obra_destino_sin_ocr

    raiz, catalogos, actual, cliente, decision = _entorno(tmp_path)
    # Ninguna decisión se aplica -- el catálogo de obras queda vacío
    # (ninguna obra CONFIRMADA con la que "OBRA COMPLETAMENTE DESCONOCIDA"
    # pudiera coincidir, ni por nombre ni por alias).
    dataset = actual / "analisis_completo_guias.csv"
    with dataset.open(encoding="utf-8-sig", newline="") as archivo:
        filas = list(csv.DictReader(archivo, delimiter=";"))
    filas[0]["obra_destino"] = "OBRA COMPLETAMENTE DESCONOCIDA"
    with dataset.open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=filas[0].keys(), delimiter=";")
        escritor.writeheader()
        escritor.writerows(filas)

    resultado = revalidar_obra_destino_sin_ocr(ruta_dataset=dataset, carpeta_catalogos=catalogos)
    assert resultado["guias_actualizadas"] == []

    with dataset.open(encoding="utf-8-sig", newline="") as archivo:
        fila = next(csv.DictReader(archivo, delimiter=";"))
    assert fila["obra_destino"] == "OBRA COMPLETAMENTE DESCONOCIDA"
    assert "OBRA_DESTINO_SIN_CORROBORAR" in fila["motivos_revision_documento"]


def test_catchup_revalida_fila_stale_de_una_decision_ya_aplicada_antes_del_fix(tmp_path):
    """Caso real 0000359449/474381: decisiones aplicadas ANTES de este fix
    (o antes de que este mecanismo existiera) dejaron el catálogo
    correcto, pero la fila del dataset con el texto documental para
    siempre -- ninguna revalidación normal la toca porque no tiene ningún
    motivo bloqueante. `revalidar_obra_destino_por_decision_aplicada_sin_
    ocr` es el mecanismo de catch-up genérico (nunca hardcodeado a
    ninguna guía/transporte -- recorre TODO el ledger) para corregir
    retroactivamente esas filas."""
    from atlas_core.revalidacion_documental import revalidar_obra_destino_por_decision_aplicada_sin_ocr

    raiz, catalogos, actual, cliente, decision = _entorno(tmp_path)
    aplicar_decision_obra(
        raiz_atlas=raiz, decision_id=decision["decision_id"], accion="REGISTRAR",
        nombre_obra_manual="OBRA CANONICA LIMITADA",
    )
    dataset = actual / "analisis_completo_guias.csv"

    # Simula el estado "pre-fix" real encontrado en G:\: la fila quedó con
    # el texto documental y SIN motivo bloqueante, aunque el catálogo/
    # ledger ya reflejen la corrección humana.
    with dataset.open(encoding="utf-8-sig", newline="") as archivo:
        filas = list(csv.DictReader(archivo, delimiter=";"))
    filas[0]["obra_destino"] = "OBRA NUEVA"
    filas[0]["motivos_revision_documento"] = ""
    with dataset.open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=filas[0].keys(), delimiter=";")
        escritor.writeheader()
        escritor.writerows(filas)

    resultado = revalidar_obra_destino_por_decision_aplicada_sin_ocr(
        ruta_dataset=dataset, ruta_ledger=actual / "decisiones_aplicadas.json", carpeta_catalogos=catalogos,
    )
    assert resultado["guias_actualizadas"] == ["100"]

    with dataset.open(encoding="utf-8-sig", newline="") as archivo:
        fila = next(csv.DictReader(archivo, delimiter=";"))
    assert fila["obra_destino"] == "OBRA CANONICA LIMITADA"


def test_catchup_nunca_pisa_una_fila_que_ya_cambio_por_otra_via(tmp_path):
    """Seguridad del catch-up: si la fila ya no muestra el texto
    documental exacto que originó la decisión (otra corrección real
    posterior), nunca se pisa -- ni con el canónico ni con ningún otro
    valor."""
    from atlas_core.revalidacion_documental import revalidar_obra_destino_por_decision_aplicada_sin_ocr

    raiz, catalogos, actual, cliente, decision = _entorno(tmp_path)
    aplicar_decision_obra(
        raiz_atlas=raiz, decision_id=decision["decision_id"], accion="REGISTRAR",
        nombre_obra_manual="OBRA CANONICA LIMITADA",
    )
    dataset = actual / "analisis_completo_guias.csv"
    with dataset.open(encoding="utf-8-sig", newline="") as archivo:
        filas = list(csv.DictReader(archivo, delimiter=";"))
    filas[0]["obra_destino"] = "OTRO VALOR CUALQUIERA YA CORREGIDO"
    with dataset.open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=filas[0].keys(), delimiter=";")
        escritor.writeheader()
        escritor.writerows(filas)

    resultado = revalidar_obra_destino_por_decision_aplicada_sin_ocr(
        ruta_dataset=dataset, ruta_ledger=actual / "decisiones_aplicadas.json", carpeta_catalogos=catalogos,
    )
    assert resultado["guias_actualizadas"] == []
    with dataset.open(encoding="utf-8-sig", newline="") as archivo:
        fila = next(csv.DictReader(archivo, delimiter=";"))
    assert fila["obra_destino"] == "OTRO VALOR CUALQUIERA YA CORREGIDO"


def test_catchup_numeros_transporte_acota_el_alcance(tmp_path):
    """El filtro `numeros_transporte` (mismo criterio de alcance que
    `revalidar_documentos_por_transporte`) deja fuera cualquier fila de un
    transporte no incluido, aunque el ledger sí tenga una decisión
    terminal aplicable -- permite revalidar UN transporte real sin tocar
    el resto del catch-up general."""
    from atlas_core.revalidacion_documental import revalidar_obra_destino_por_decision_aplicada_sin_ocr

    raiz, catalogos, actual, cliente, decision = _entorno(tmp_path)
    aplicar_decision_obra(
        raiz_atlas=raiz, decision_id=decision["decision_id"], accion="REGISTRAR",
        nombre_obra_manual="OBRA CANONICA LIMITADA",
    )
    dataset = actual / "analisis_completo_guias.csv"
    with dataset.open(encoding="utf-8-sig", newline="") as archivo:
        filas = list(csv.DictReader(archivo, delimiter=";"))
    filas[0]["obra_destino"] = "OBRA NUEVA"
    filas[0]["motivos_revision_documento"] = ""
    with dataset.open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=filas[0].keys(), delimiter=";")
        escritor.writeheader()
        escritor.writerows(filas)

    # "T1" es el transporte real de la fixture -- pedir uno DISTINTO
    # deja la fila fuera de alcance, aunque el ledger sí resolviera.
    resultado_fuera_de_alcance = revalidar_obra_destino_por_decision_aplicada_sin_ocr(
        ruta_dataset=dataset, ruta_ledger=actual / "decisiones_aplicadas.json", carpeta_catalogos=catalogos,
        numeros_transporte={"OTRO_TRANSPORTE_CUALQUIERA"},
    )
    assert resultado_fuera_de_alcance["guias_actualizadas"] == []
    with dataset.open(encoding="utf-8-sig", newline="") as archivo:
        fila = next(csv.DictReader(archivo, delimiter=";"))
    assert fila["obra_destino"] == "OBRA NUEVA"  # sin tocar

    resultado_en_alcance = revalidar_obra_destino_por_decision_aplicada_sin_ocr(
        ruta_dataset=dataset, ruta_ledger=actual / "decisiones_aplicadas.json", carpeta_catalogos=catalogos,
        numeros_transporte={"T1"},
    )
    assert resultado_en_alcance["guias_actualizadas"] == ["100"]
