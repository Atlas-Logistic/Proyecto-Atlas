import hashlib
import json
from datetime import datetime, timezone

from atlas_core.almacenamiento_portable import escribir_estado_operacion
from atlas_core.decisiones_pendientes import crear_decision, detectar_decisiones_documento, generar_artefacto
from atlas_core.catalogo_clientes import CatalogoClientes, EstadoCalidadCliente
from atlas_core.catalogo_destinos import CatalogoDestinos, EstadoCalidadDestino
from atlas_core.catalogo_obras_destinos import CatalogoObrasDestinos, Evidencia, TipoEvidencia


def _catalogos(tmp_path):
    carpeta = tmp_path / "catalogos"; carpeta.mkdir()
    for nombre, contenido in {
        "clientes.json": {"version_formato": 1, "clientes": []},
        "empresas.json": {},
        "vehiculos.json": {},
        "obras_destinos.json": {"version_formato": 1, "obras": [], "relaciones": []},
        "destinos_maestros.json": {"version_formato": 1, "destinos": []},
    }.items(): (carpeta / nombre).write_text(json.dumps(contenido), encoding="utf-8")
    return carpeta


def _decision(**cambios):
    datos=dict(tipo="VEHICULO_DESCONOCIDO", entidad="VEHICULO", archivo="g.png", numero_guia="1", numero_transporte="2", campo="patente_tracto", valor_documental="AB1234", valor_normalizado="AB1234", identidad_resuelta=None, candidatos=(), motivos=("SIN_CANDIDATO",), evidencias=({"tipo":"OCR_DOCUMENTAL"},), acciones_permitidas=("POSPONER",))
    datos.update(cambios); return crear_decision(**datos)


def _cliente_confirmado(carpeta, nombre="CLIENTE CANONICO SA", rut="50.234.350-5"):
    return CatalogoClientes(carpeta/"clientes.json").crear(
        razon_social=nombre, rut=rut, fuente="PRUEBA",
        estado_calidad=EstadoCalidadCliente.CONFIRMADO,
    )


def _datos_cliente(nombre="NOMBRE DOCUMENTAL SPA", rut="50.234.350-5", obra=""):
    return {"número de guía":"100", "cliente":nombre, "RUT del cliente":rut, "obra destino":obra}


def _evidencia():
    return Evidencia(tipo=TipoEvidencia.GUIA.value, identificador_fuente="guia-100", referencia_hash="a"*64, campos_observados={"obra":"OBRA UNO"}, fecha="2026-01-01T00:00:00+00:00", actor_proceso="test", resultado="SOPORTA")


def test_patente_desconocida_lineal_genera_decision(tmp_path):
    decisiones=detectar_decisiones_documento(archivo="g.png", datos={"número de guía":"1","patente del tracto":"AB1234"}, carpeta_catalogos=_catalogos(tmp_path))
    assert [(d["tipo"],d["valor_documental"]) for d in decisiones] == [("VEHICULO_DESCONOCIDO","AB1234")]


def test_decision_id_es_determinista_y_cambia_con_documento_o_campo():
    assert _decision()["decision_id"] == _decision()["decision_id"]
    assert _decision()["decision_id"] != _decision(numero_guia="9")["decision_id"]
    assert _decision()["decision_id"] != _decision(campo="patente_rampla")["decision_id"]


def test_texto_documental_permanece_separado_de_identidad_canonica():
    d=_decision(valor_documental="CONSTR EJEMPLO", identidad_resuelta={"valor_canonico":"CONSTRUCTORA EJEMPLO LIMITADA"})
    assert d["valor_documental"] != d["identidad_resuelta"]["valor_canonico"]


def test_artefacto_vacio_hashes_atomico_y_catalogos_byte_identicos(tmp_path):
    carpeta=_catalogos(tmp_path); dataset=tmp_path/"datos.csv"; dataset.write_bytes(b"a,b\n")
    antes={p.name:p.read_bytes() for p in carpeta.iterdir()}
    salida=tmp_path/"decisiones_pendientes.json"
    artefacto=generar_artefacto(ruta_dataset=dataset, carpeta_catalogos=carpeta, decisiones=[], ruta_salida=salida, reloj=lambda:datetime(2026,1,1,tzinfo=timezone.utc))
    assert artefacto["schema_version"]==1 and artefacto["decisiones"]==[]
    assert artefacto["dataset_sha256"]==hashlib.sha256(b"a,b\n").hexdigest().upper()
    assert all(clave in artefacto["catalogos_sha256"] for clave in ("clientes","vehiculos","obras_destinos","destinos_maestros"))
    assert antes=={p.name:p.read_bytes() for p in carpeta.iterdir()}
    assert json.loads(salida.read_text(encoding="utf-8"))["decisiones"]==[]


def test_estado_operacion_apunta_artefacto_sin_romper_lectores_antiguos(tmp_path):
    reporte=tmp_path/"reportes"/"actual"; reporte.mkdir(parents=True)
    decisiones=tmp_path/"operacion"/"actual"/"decisiones_pendientes.json"; decisiones.parent.mkdir(parents=True); decisiones.write_text("{}")
    ruta=escribir_estado_operacion(reporte_vigente=reporte, decisiones_pendientes=decisiones, raiz=tmp_path)
    assert json.loads(ruta.read_text(encoding="utf-8"))["decisiones_pendientes"]=="operacion/actual/decisiones_pendientes.json"


def test_cliente_desconocido_con_rut_valido_preserva_texto_evidencia_y_catalogos(tmp_path):
    carpeta=_catalogos(tmp_path); antes={p.name:p.read_bytes() for p in carpeta.iterdir()}
    ds=detectar_decisiones_documento(archivo="100.png",datos=_datos_cliente(),carpeta_catalogos=carpeta)
    d=next(x for x in ds if x["tipo"]=="CLIENTE_DESCONOCIDO")
    assert d["valor_documental"]=="NOMBRE DOCUMENTAL SPA"
    assert d["evidencias"]==[{"tipo":"RUT_VALIDO","campo":"rut_cliente","valor":"50.234.350-5"}]
    assert d["acciones_permitidas"]==["CONFIRMAR_NUEVO","ASOCIAR_EXISTENTE","POSPONER"]
    assert antes=={p.name:p.read_bytes() for p in carpeta.iterdir()}


def test_alias_cliente_maestro_por_rut_es_read_only(tmp_path):
    carpeta=_catalogos(tmp_path); cliente=_cliente_confirmado(carpeta); antes=(carpeta/"clientes.json").read_bytes()
    ds=detectar_decisiones_documento(archivo="100.png",datos=_datos_cliente(),carpeta_catalogos=carpeta,cliente_documental_original="NOMBRE DOCUMENTAL SPA")
    d=next(x for x in ds if x["tipo"]=="ALIAS_CANDIDATO")
    assert d["identidad_resuelta"]["entidad_id"]==cliente.cliente_id and d["valor_documental"]=="NOMBRE DOCUMENTAL SPA"
    assert d["acciones_permitidas"]==["CONFIRMAR_ALIAS","RECHAZAR","POSPONER"]
    assert (carpeta/"clientes.json").read_bytes()==antes


def test_alias_empresa_legacy_por_rut_no_registra_alias(tmp_path, monkeypatch):
    carpeta=_catalogos(tmp_path); (carpeta/"empresas.json").write_text(json.dumps({"50.234.350-5":{"nombre":"EMPRESA CANONICA SA"}}),encoding="utf-8"); antes=(carpeta/"empresas.json").read_bytes()
    import atlas_core.catalogos as catalogos
    monkeypatch.setattr(catalogos,"registrar_alias_seguro",lambda *a,**k: (_ for _ in ()).throw(AssertionError("no debe ejecutarse")))
    ds=detectar_decisiones_documento(archivo="100.png",datos=_datos_cliente(),carpeta_catalogos=carpeta,cliente_documental_original="NOMBRE DOCUMENTAL SPA")
    d=next(x for x in ds if x["tipo"]=="ALIAS_CANDIDATO")
    assert d["identidad_resuelta"]["valor_canonico"]=="EMPRESA CANONICA SA"
    assert (carpeta/"empresas.json").read_bytes()==antes


def test_obra_desconocida_no_se_confunde_con_destino(tmp_path):
    carpeta=_catalogos(tmp_path); _cliente_confirmado(carpeta)
    ds=detectar_decisiones_documento(archivo="100.png",datos=_datos_cliente(nombre="CLIENTE CANONICO SA",obra="OBRA NUEVA"),carpeta_catalogos=carpeta)
    assert [x["tipo"] for x in ds if x["entidad"] in {"OBRA","RELACION_OBRA_DESTINO"}]==["OBRA_DESCONOCIDA"]
    assert next(x for x in ds if x["tipo"]=="OBRA_DESCONOCIDA")["acciones_permitidas"]==["REGISTRAR_OBSERVACION","ASOCIAR_EXISTENTE","POSPONER"]


def test_obra_existente_sin_relacion_confirmada_y_caso_confirmado(tmp_path):
    carpeta=_catalogos(tmp_path); cliente=_cliente_confirmado(carpeta)
    obras=CatalogoObrasDestinos(carpeta/"obras_destinos.json",ruta_clientes=carpeta/"clientes.json",ruta_destinos=carpeta/"destinos_maestros.json")
    obras.registrar_observacion(cliente_id=cliente.cliente_id,nombre_obra="OBRA UNO",evidencia=_evidencia())
    datos=_datos_cliente(nombre="CLIENTE CANONICO SA",obra="OBRA UNO")
    ds=detectar_decisiones_documento(archivo="100.png",datos=datos,carpeta_catalogos=carpeta)
    assert [x["tipo"] for x in ds if x["entidad"] in {"OBRA","RELACION_OBRA_DESTINO"}]==["DESTINO_SIN_CONFIRMAR"]
    assert next(x for x in ds if x["tipo"]=="DESTINO_SIN_CONFIRMAR")["acciones_permitidas"]==["CONFIRMAR_RELACION","RECHAZAR","POSPONER"]
    destino=CatalogoDestinos(carpeta/"destinos_maestros.json",ruta_clientes=carpeta/"clientes.json").crear(cliente_id=cliente.cliente_id,nombre_destino="DESTINO UNO",pais="CHILE",fuente="PRUEBA",estado_calidad=EstadoCalidadDestino.CONFIRMADO)
    pendiente=obras.registrar_observacion(cliente_id=cliente.cliente_id,nombre_obra="OBRA UNO",destino_id=destino.destino_id,evidencia=Evidencia(**{**_evidencia().a_dict(),"identificador_fuente":"guia-101"})).relacion
    obras.confirmar_relacion(pendiente.relacion_id,actor="test")
    ds=detectar_decisiones_documento(archivo="100.png",datos=datos,carpeta_catalogos=carpeta)
    assert not any(x["tipo"] in {"OBRA_DESCONOCIDA","DESTINO_SIN_CONFIRMAR"} for x in ds)


def test_artefacto_deduplica_y_controla_cuatro_decisiones(tmp_path):
    carpeta=_catalogos(tmp_path); dataset=tmp_path/"datos.csv"; dataset.write_text("19 OK;0 REVISAR\n",encoding="utf-8")
    alias=[_decision(tipo="ALIAS_CANDIDATO",entidad="CLIENTE",campo="cliente",numero_guia=str(g),valor_documental=v,evidencias=({"tipo":"RUT_EXACTO"},),acciones_permitidas=("CONFIRMAR_ALIAS","RECHAZAR","POSPONER")) for g,v in ((464529,"TORRES OCARANEA LTDA"),(464698,"EDMA SA"),(464699,"KBEMA SA"))]
    destino=_decision(tipo="DESTINO_SIN_CONFIRMAR",entidad="RELACION_OBRA_DESTINO",campo="obra_destino",numero_guia="464550",valor_documental="EMPRESA CONST SIGRO",evidencias=({"tipo":"OBRA_IDENTIFICADA"},),acciones_permitidas=("CONFIRMAR_RELACION","RECHAZAR","POSPONER"))
    artefacto=generar_artefacto(ruta_dataset=dataset,carpeta_catalogos=carpeta,decisiones=[alias[0],alias[0],*alias[1:],destino])
    assert artefacto["schema_version"]==1 and len(artefacto["decisiones"])==4
    assert [x["tipo"] for x in artefacto["decisiones"]].count("ALIAS_CANDIDATO")==3
    assert [x["tipo"] for x in artefacto["decisiones"]].count("DESTINO_SIN_CONFIRMAR")==1
