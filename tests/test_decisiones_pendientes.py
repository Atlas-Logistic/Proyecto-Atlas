import hashlib
import json
from datetime import datetime, timezone

from atlas_core.almacenamiento_portable import escribir_estado_operacion
from atlas_core.decisiones_pendientes import crear_decision, detectar_decisiones_documento, generar_artefacto, regenerar_decisiones_persistidas
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
    assert d["acciones_permitidas"]==["REGISTRAR","NO_REGISTRAR","POSPONER"]  # R3.2: simplificado
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
    assert next(x for x in ds if x["tipo"]=="OBRA_DESCONOCIDA")["acciones_permitidas"]==["REGISTRAR","NO_REGISTRAR","POSPONER"]  # R3.2: simplificado


def test_obra_desconocida_transporta_cliente_reconocido_separado_de_la_obra(tmp_path):
    carpeta=_catalogos(tmp_path); cliente=_cliente_confirmado(carpeta,nombre="CLIENTE CANONICO SA")
    ds=detectar_decisiones_documento(
        archivo="100.png",
        datos=_datos_cliente(nombre="CLIENTE CANONICO SA",obra="OBRA NUEVA"),
        carpeta_catalogos=carpeta,
    )
    d=next(x for x in ds if x["tipo"]=="OBRA_DESCONOCIDA")
    assert d["contexto"]=={"cliente_id":cliente.cliente_id,"cliente_canonico":"CLIENTE CANONICO SA","destino_documental":""}
    assert d["valor_documental"]=="OBRA NUEVA"
    assert d["valor_documental"]!=d["contexto"]["cliente_canonico"]
    assert d["identidad_resuelta"] is None  # la obra en sí sigue sin resolverse


def test_decision_id_no_cambia_al_agregar_contexto(tmp_path):
    sin_contexto=_decision()
    con_contexto=_decision(contexto={"cliente_id":"x","cliente_canonico":"CLIENTE X"})
    assert sin_contexto["decision_id"]==con_contexto["decision_id"]


def test_generar_artefacto_acepta_decision_sin_clave_contexto_para_compatibilidad(tmp_path):
    carpeta=_catalogos(tmp_path); dataset=tmp_path/"datos.csv"; dataset.write_bytes(b"x\n")
    vieja=_decision()  # como un artefacto R3.1 anterior a este cambio
    del vieja["contexto"]
    antes={p.name:p.read_bytes() for p in carpeta.iterdir()}
    artefacto=generar_artefacto(ruta_dataset=dataset,carpeta_catalogos=carpeta,decisiones=[vieja])
    assert len(artefacto["decisiones"])==1
    assert "contexto" not in artefacto["decisiones"][0]
    assert antes=={p.name:p.read_bytes() for p in carpeta.iterdir()}


def test_obra_existente_sin_relacion_confirmada_y_caso_confirmado(tmp_path):
    carpeta=_catalogos(tmp_path); cliente=_cliente_confirmado(carpeta)
    obras=CatalogoObrasDestinos(carpeta/"obras_destinos.json",ruta_clientes=carpeta/"clientes.json",ruta_destinos=carpeta/"destinos_maestros.json")
    obras.registrar_observacion(cliente_id=cliente.cliente_id,nombre_obra="OBRA UNO",evidencia=_evidencia())
    datos=_datos_cliente(nombre="CLIENTE CANONICO SA",obra="OBRA UNO")
    ds=detectar_decisiones_documento(archivo="100.png",datos=datos,carpeta_catalogos=carpeta)
    assert [x["tipo"] for x in ds if x["entidad"] in {"OBRA","RELACION_OBRA_DESTINO"}]==["DESTINO_SIN_CONFIRMAR"]
    assert next(x for x in ds if x["tipo"]=="DESTINO_SIN_CONFIRMAR")["acciones_permitidas"]==["CONFIRMAR","NO_CONFIRMAR","POSPONER"]
    destino=CatalogoDestinos(carpeta/"destinos_maestros.json",ruta_clientes=carpeta/"clientes.json").crear(cliente_id=cliente.cliente_id,nombre_destino="DESTINO UNO",pais="CHILE",fuente="PRUEBA",estado_calidad=EstadoCalidadDestino.CONFIRMADO)
    pendiente=obras.registrar_observacion(cliente_id=cliente.cliente_id,nombre_obra="OBRA UNO",destino_id=destino.destino_id,evidencia=Evidencia(**{**_evidencia().a_dict(),"identificador_fuente":"guia-101"})).relacion
    obras.confirmar_relacion(pendiente.relacion_id,actor="test")
    ds=detectar_decisiones_documento(archivo="100.png",datos=datos,carpeta_catalogos=carpeta)
    assert not any(x["tipo"] in {"OBRA_DESCONOCIDA","DESTINO_SIN_CONFIRMAR"} for x in ds)


# --- R3.4: contrato enriquecido de DESTINO_SIN_CONFIRMAR ---

def test_destino_sin_confirmar_transporta_cliente_obra_y_destino_documental(tmp_path):
    carpeta=_catalogos(tmp_path); cliente=_cliente_confirmado(carpeta,nombre="CONSTRUMART SA")
    obras=CatalogoObrasDestinos(carpeta/"obras_destinos.json",ruta_clientes=carpeta/"clientes.json",ruta_destinos=carpeta/"destinos_maestros.json")
    obra=obras.registrar_observacion(cliente_id=cliente.cliente_id,nombre_obra="CONSTRUCTORA INMOBILIARIA E",evidencia=_evidencia()).obra
    datos=_datos_cliente(nombre="CONSTRUMART SA",obra="CONSTRUCTORA INMOBILIARIA E")
    ds=detectar_decisiones_documento(
        archivo="464715.png",datos=datos,carpeta_catalogos=carpeta,
        despachar_a_documental="AV. VICUNA MACKENNA 3451 SAN JOAQUIN",
    )
    d=next(x for x in ds if x["tipo"]=="DESTINO_SIN_CONFIRMAR")
    assert d["campo"]=="destino_entrega"
    assert d["valor_documental"]=="AV. VICUNA MACKENNA 3451 SAN JOAQUIN"
    assert d["identidad_resuelta"]=={"entidad_id":obra.obra_id,"valor_canonico":"CONSTRUCTORA INMOBILIARIA E"}
    assert d["contexto"]=={
        "cliente_id":cliente.cliente_id,"cliente_canonico":"CONSTRUMART SA",
        "obra_id":obra.obra_id,"obra_canonica":"CONSTRUCTORA INMOBILIARIA E",
        "destino_documental":"AV. VICUNA MACKENNA 3451 SAN JOAQUIN",
    }
    assert d["acciones_permitidas"]==["CONFIRMAR","NO_CONFIRMAR","POSPONER"]
    # nunca se confunde destino con obra en el campo de valor
    assert d["valor_documental"]!=d["contexto"]["obra_canonica"]


def test_destino_sin_confirmar_sin_despachar_a_no_rompe_y_usa_obra_como_respaldo(tmp_path):
    """Compatibilidad: un llamador que todavía no pasa despachar_a_documental
    (parámetro opcional) sigue generando una decisión válida."""
    carpeta=_catalogos(tmp_path); cliente=_cliente_confirmado(carpeta)
    obras=CatalogoObrasDestinos(carpeta/"obras_destinos.json",ruta_clientes=carpeta/"clientes.json",ruta_destinos=carpeta/"destinos_maestros.json")
    obras.registrar_observacion(cliente_id=cliente.cliente_id,nombre_obra="OBRA UNO",evidencia=_evidencia())
    ds=detectar_decisiones_documento(archivo="100.png",datos=_datos_cliente(nombre="CLIENTE CANONICO SA",obra="OBRA UNO"),carpeta_catalogos=carpeta)
    d=next(x for x in ds if x["tipo"]=="DESTINO_SIN_CONFIRMAR")
    assert d["valor_documental"]=="OBRA UNO"  # respaldo, sin destino documental disponible


# --- R3.2: simplificación operacional ---

def test_cliente_igual_obra_no_genera_obra_desconocida(tmp_path):
    """Regla de Javier: si Atlas ya conoce la entidad, no pregunta. Cuando el
    valor documental de "obra" es, normalizado, el mismo nombre (o alias) del
    cliente ya reconocido, no hay ninguna obra nueva que registrar."""
    carpeta=_catalogos(tmp_path); _cliente_confirmado(carpeta,nombre="AGF ACEROS DE CHILE SPA")
    ds=detectar_decisiones_documento(archivo="100.png",datos=_datos_cliente(nombre="AGF ACEROS DE CHILE SPA",obra="AGF ACEROS DE CHILE SPA"),carpeta_catalogos=carpeta)
    assert not any(x["tipo"] in {"OBRA_DESCONOCIDA","DESTINO_SIN_CONFIRMAR"} for x in ds)


def test_obra_realmente_desconocida_conserva_solo_registrar_no_registrar(tmp_path):
    carpeta=_catalogos(tmp_path); _cliente_confirmado(carpeta,nombre="CONSTRUMART SA")
    ds=detectar_decisiones_documento(archivo="100.png",datos=_datos_cliente(nombre="CONSTRUMART SA",obra="CONSTRUCTORA INMOBILIARIA E"),carpeta_catalogos=carpeta)
    d=next(x for x in ds if x["tipo"]=="OBRA_DESCONOCIDA")
    assert d["acciones_permitidas"]==["REGISTRAR","NO_REGISTRAR","POSPONER"]
    assert d["motivos"]==["OBRA_NO_EXISTE_PARA_CLIENTE"]


def test_obra_global_reconocida_por_otro_cliente_no_genera_obra_desconocida(tmp_path):
    """R3.3.1: una obra ya observada para el CLIENTE A se reconoce igual
    cuando el CLIENTE B trae la misma obra -- no hay dos identidades, no se
    pregunta de nuevo por la obra (sólo, en este caso, por el destino, que
    es una decisión distinta: DESTINO_SIN_CONFIRMAR)."""
    carpeta=_catalogos(tmp_path)
    cliente_a=_cliente_confirmado(carpeta,nombre="CLIENTE A SPA",rut="50.234.350-5")
    cliente_b=_cliente_confirmado(carpeta,nombre="CLIENTE B SPA",rut="76.123.987-2")
    obras=CatalogoObrasDestinos(carpeta/"obras_destinos.json",ruta_clientes=carpeta/"clientes.json",ruta_destinos=carpeta/"destinos_maestros.json")
    resultado=obras.registrar_observacion(cliente_id=cliente_a.cliente_id,nombre_obra="CONSTRUCTORA X",evidencia=_evidencia())
    ds=detectar_decisiones_documento(archivo="100.png",datos=_datos_cliente(nombre="CLIENTE B SPA",rut="76.123.987-2",obra="CONSTRUCTORA X"),carpeta_catalogos=carpeta)
    assert not any(x["tipo"]=="OBRA_DESCONOCIDA" for x in ds)
    d=next(x for x in ds if x["tipo"]=="DESTINO_SIN_CONFIRMAR")
    assert d["identidad_resuelta"]["entidad_id"]==resultado.obra.obra_id  # misma obra_id, no una segunda


def test_patente_desconocida_conserva_solo_registrar_no_registrar(tmp_path):
    ds=detectar_decisiones_documento(archivo="g.png",datos={"número de guía":"1","patente del tracto":"AB1234"},carpeta_catalogos=_catalogos(tmp_path))
    d=next(x for x in ds if x["tipo"]=="VEHICULO_DESCONOCIDO")
    assert d["acciones_permitidas"]==["REGISTRAR","NO_REGISTRAR","POSPONER"]


def test_patente_conocida_no_genera_decision(tmp_path):
    carpeta=_catalogos(tmp_path)
    (carpeta/"vehiculos.json").write_text(json.dumps({"version":1,"vehiculos":[{
        "vehiculo_id":"id-1","patente_canonica":"AB1234","tipo":"TRACTO",
        "estado_calidad":"CONFIRMADO","estado_vigencia":"ACTIVO","aliases":[],
        "evidencias":[],"procedencia":"CONFIRMACION_HUMANA","confirmado_por":"test",
        "fecha_confirmacion":"2026-01-01T00:00:00+00:00","observaciones":"",
        "fecha_creacion":"2026-01-01T00:00:00+00:00","fecha_modificacion":"2026-01-01T00:00:00+00:00",
    }]}),encoding="utf-8")
    ds=detectar_decisiones_documento(archivo="g.png",datos={"número de guía":"1","patente del tracto":"AB1234"},carpeta_catalogos=carpeta)
    assert not any(x["tipo"]=="VEHICULO_DESCONOCIDO" for x in ds)


def _vehiculo_v1(patente, tipo, vehiculo_id="id-1"):
    return {
        "vehiculo_id": vehiculo_id, "patente_canonica": patente, "tipo": tipo,
        "estado_calidad": "CONFIRMADO", "estado_vigencia": "ACTIVO", "aliases": [],
        "evidencias": [], "procedencia": "CONFIRMACION_HUMANA", "confirmado_por": "test",
        "fecha_confirmacion": "2026-01-01T00:00:00+00:00", "observaciones": "",
        "fecha_creacion": "2026-01-01T00:00:00+00:00", "fecha_modificacion": "2026-01-01T00:00:00+00:00",
    }


def test_patente_tracto_camion_rigido_conocida_sin_rampla_no_genera_decision(tmp_path):
    """R4: caso real -- una patente_tracto AISLADA (sin rampla documental,
    camión rígido) ya CONFIRMADA/ACTIVA en el catálogo como CAMION_RIGIDO no
    debe generar VEHICULO_DESCONOCIDO -- mismo criterio de compatibilidad ya
    aplicado en `procesamiento_masivo.procesar_archivo` (P2) y en
    `revalidar_patente_sin_homologar_sin_ocr`. Antes de este fix, esta
    función seguía filtrando patente_tracto por TRACTO exclusivo y volvía a
    pedir "registrar" una patente que Atlas ya conoce -- contradiciendo al
    dataset/reporte, que ya la trata como homologada."""
    carpeta = _catalogos(tmp_path)
    (carpeta / "vehiculos.json").write_text(
        json.dumps({"version": 1, "vehiculos": [_vehiculo_v1("XF3629", "CAMION_RIGIDO")]}),
        encoding="utf-8",
    )
    ds = detectar_decisiones_documento(
        archivo="g.png", datos={"número de guía": "1", "patente del tracto": "XF3629"},
        carpeta_catalogos=carpeta,
    )
    assert not any(x["tipo"] == "VEHICULO_DESCONOCIDO" for x in ds)


def test_patente_tracto_camion_rigido_conocida_con_rampla_documental_si_genera_decision(tmp_path):
    """Control -- la compatibilidad TRACTO/CAMION_RIGIDO es SOLO para el
    tracto AISLADO. Si el documento SÍ trae una rampla documental válida (es
    un tracto+rampla articulado), una patente_tracto que en catálogo es
    CAMION_RIGIDO sigue sin ser candidata: el rol documental exige TRACTO
    exclusivo, así que la decisión debe seguir generándose."""
    carpeta = _catalogos(tmp_path)
    (carpeta / "vehiculos.json").write_text(
        json.dumps({"version": 1, "vehiculos": [_vehiculo_v1("XF3629", "CAMION_RIGIDO")]}),
        encoding="utf-8",
    )
    ds = detectar_decisiones_documento(
        archivo="g.png",
        datos={"número de guía": "1", "patente del tracto": "XF3629", "patente del carro": "AB1234"},
        carpeta_catalogos=carpeta,
    )
    assert any(x["tipo"] == "VEHICULO_DESCONOCIDO" and x["campo"] == "patente_tracto" for x in ds)


def test_patente_tracto_realmente_desconocida_sigue_generando_decision(tmp_path):
    """Control -- una patente_tracto aislada que NO existe en ningún
    catálogo (ni como TRACTO ni como CAMION_RIGIDO) debe seguir generando su
    VEHICULO_DESCONOCIDO normal; el fix de compatibilidad nunca se convierte
    en una abstención general."""
    carpeta = _catalogos(tmp_path)
    (carpeta / "vehiculos.json").write_text(
        json.dumps({"version": 1, "vehiculos": [_vehiculo_v1("ZZ9999", "CAMION_RIGIDO", "id-otro")]}),
        encoding="utf-8",
    )
    ds = detectar_decisiones_documento(
        archivo="g.png", datos={"número de guía": "1", "patente del tracto": "XF3629"},
        carpeta_catalogos=carpeta,
    )
    assert [(d["tipo"], d["valor_documental"]) for d in ds] == [("VEHICULO_DESCONOCIDO", "XF3629")]


def test_patente_rampla_camion_rigido_conocida_no_se_acepta_como_carro(tmp_path):
    """Control -- la compatibilidad TRACTO/CAMION_RIGIDO es exclusiva del
    campo patente_tracto; patente_rampla nunca acepta CAMION_RIGIDO (ni
    TRACTO) como candidata."""
    carpeta = _catalogos(tmp_path)
    (carpeta / "vehiculos.json").write_text(
        json.dumps({"version": 1, "vehiculos": [_vehiculo_v1("XF3629", "CAMION_RIGIDO")]}),
        encoding="utf-8",
    )
    ds = detectar_decisiones_documento(
        archivo="g.png", datos={"número de guía": "1", "patente del carro": "XF3629"},
        carpeta_catalogos=carpeta,
    )
    assert any(x["tipo"] == "VEHICULO_DESCONOCIDO" and x["campo"] == "patente_rampla" for x in ds)


def test_cliente_desconocido_conserva_solo_registrar_no_registrar(tmp_path):
    ds=detectar_decisiones_documento(archivo="100.png",datos=_datos_cliente(),carpeta_catalogos=_catalogos(tmp_path))
    d=next(x for x in ds if x["tipo"]=="CLIENTE_DESCONOCIDO")
    assert d["acciones_permitidas"]==["REGISTRAR","NO_REGISTRAR","POSPONER"]


def test_chofer_y_vehiculo_conocidos_combinacion_nueva_no_genera_decision(tmp_path):
    """Documenta la regla de producto: un chofer y un vehículo, ambos
    conocidos, apareciendo juntos por primera vez en una guía no debe pedir
    confirmar una relación permanente. Hoy el detector no modela ninguna
    relación chofer<->vehículo (ni permanente ni por viaje), así que esto ya
    se cumple de forma trivial -- se deja como test de contrato explícito
    para que una futura implementación de esa relación no rompa la regla."""
    carpeta=_catalogos(tmp_path)
    datos=dict(_datos_cliente(),**{"chofer":"CUALQUIERA","patente del tracto":"AB1234"})
    ds=detectar_decisiones_documento(archivo="100.png",datos=datos,carpeta_catalogos=carpeta)
    assert not any("CHOFER" in x["tipo"] or x["entidad"]=="CHOFER" for x in ds)


def test_generar_artefacto_no_modifica_catalogos_con_decisiones_r32(tmp_path):
    carpeta=_catalogos(tmp_path); _cliente_confirmado(carpeta,nombre="CONSTRUMART SA")
    dataset=tmp_path/"datos.csv"; dataset.write_bytes(b"a,b\n")
    antes={p.name:p.read_bytes() for p in carpeta.iterdir()}
    ds=detectar_decisiones_documento(archivo="100.png",datos=_datos_cliente(nombre="CONSTRUMART SA",obra="OBRA X"),carpeta_catalogos=carpeta)
    generar_artefacto(ruta_dataset=dataset,carpeta_catalogos=carpeta,decisiones=ds,ruta_salida=tmp_path/"decisiones_pendientes.json")
    assert antes=={p.name:p.read_bytes() for p in carpeta.iterdir()}


# --- R3.2.1: regeneración read-only de decisiones ya persistidas (sin OCR) ---

def _decision_obra_r31(carpeta, cliente, obra_texto, numero_guia="1"):
    """Simula una OBRA_DESCONOCIDA tal como la habría dejado un artefacto
    generado ANTES de R3.2: acciones_permitidas viejas, pero ya con
    `contexto` (R3.1.3)."""
    return crear_decision(
        tipo="OBRA_DESCONOCIDA", entidad="OBRA", archivo=f"{numero_guia}.png",
        numero_guia=numero_guia, numero_transporte="1", campo="obra_destino",
        valor_documental=obra_texto, valor_normalizado=obra_texto,
        identidad_resuelta=None, candidatos=(), motivos=("OBRA_NO_EXISTE_PARA_CLIENTE",),
        evidencias=({"tipo":"CLIENTE_RESUELTO","entidad_id":cliente.cliente_id},),
        acciones_permitidas=("REGISTRAR_OBSERVACION","ASOCIAR_EXISTENTE","POSPONER"),
        contexto={"cliente_id":cliente.cliente_id,"cliente_canonico":cliente.razon_social},
    )


def test_regenerar_descarta_cliente_igual_obra_de_un_artefacto_r31(tmp_path):
    carpeta=_catalogos(tmp_path); cliente=_cliente_confirmado(carpeta,nombre="AGF ACEROS DE CHILE SPA")
    vieja=_decision_obra_r31(carpeta,cliente,"AGF ACEROS DE CHILE SPA")
    regeneradas=regenerar_decisiones_persistidas(decisiones=[vieja],carpeta_catalogos=carpeta)
    assert regeneradas==[]


def test_regenerar_conserva_obra_realmente_desconocida_y_normaliza_acciones(tmp_path):
    carpeta=_catalogos(tmp_path); cliente=_cliente_confirmado(carpeta,nombre="CONSTRUMART SA")
    vieja=_decision_obra_r31(carpeta,cliente,"CONSTRUCTORA INMOBILIARIA E",numero_guia="464715")
    regeneradas=regenerar_decisiones_persistidas(decisiones=[vieja],carpeta_catalogos=carpeta)
    assert len(regeneradas)==1
    d=regeneradas[0]
    assert d["tipo"]=="OBRA_DESCONOCIDA"
    assert d["valor_documental"]=="CONSTRUCTORA INMOBILIARIA E"
    assert d["acciones_permitidas"]==["REGISTRAR","NO_REGISTRAR","POSPONER"]
    assert d["decision_id"]==vieja["decision_id"]  # misma decisión semántica: mismo id


def test_regenerar_conserva_patente_desconocida_y_normaliza_acciones(tmp_path):
    carpeta=_catalogos(tmp_path)
    vieja=_decision(tipo="VEHICULO_DESCONOCIDO",entidad="VEHICULO",campo="patente_tracto",
                     valor_documental="KN5439",motivos=("SIN_VEHICULO_CONFIRMADO_COMPATIBLE",),
                     evidencias=({"tipo":"OCR_DOCUMENTAL","campo":"patente_tracto","valor":"KN5439"},),
                     acciones_permitidas=("CONFIRMAR_NUEVO","ASOCIAR_EXISTENTE","POSPONER"))
    regeneradas=regenerar_decisiones_persistidas(decisiones=[vieja],carpeta_catalogos=carpeta)
    assert len(regeneradas)==1
    d=regeneradas[0]
    assert d["valor_documental"]=="KN5439"
    assert d["acciones_permitidas"]==["REGISTRAR","NO_REGISTRAR","POSPONER"]
    assert d["decision_id"]==vieja["decision_id"]


def test_regenerar_no_modifica_catalogos(tmp_path):
    carpeta=_catalogos(tmp_path); cliente=_cliente_confirmado(carpeta,nombre="CONSTRUMART SA")
    vieja=_decision_obra_r31(carpeta,cliente,"CONSTRUCTORA INMOBILIARIA E")
    antes={p.name:p.read_bytes() for p in carpeta.iterdir()}
    regenerar_decisiones_persistidas(decisiones=[vieja],carpeta_catalogos=carpeta)
    assert antes=={p.name:p.read_bytes() for p in carpeta.iterdir()}


def test_regenerar_conserva_obra_sin_contexto_por_falta_de_base_para_decidir(tmp_path):
    """Un artefacto anterior a R3.1.3 no trae `contexto`; sin esa identidad
    de apoyo no hay base para decidir cliente==obra, así que se conserva sin
    filtrar en vez de asumir algo que el artefacto no dice."""
    carpeta=_catalogos(tmp_path)
    vieja=_decision(tipo="OBRA_DESCONOCIDA",entidad="OBRA",campo="obra_destino",
                     valor_documental="OBRA X",motivos=("OBRA_NO_EXISTE_PARA_CLIENTE",),
                     evidencias=({"tipo":"CLIENTE_RESUELTO","entidad_id":"x"},),
                     acciones_permitidas=("REGISTRAR_OBSERVACION","ASOCIAR_EXISTENTE","POSPONER"))
    del vieja["contexto"]
    regeneradas=regenerar_decisiones_persistidas(decisiones=[vieja],carpeta_catalogos=carpeta)
    assert len(regeneradas)==1
    assert regeneradas[0]["acciones_permitidas"]==["REGISTRAR","NO_REGISTRAR","POSPONER"]


def test_artefacto_deduplica_y_controla_cuatro_decisiones(tmp_path):
    carpeta=_catalogos(tmp_path); dataset=tmp_path/"datos.csv"; dataset.write_text("19 OK;0 REVISAR\n",encoding="utf-8")
    alias=[_decision(tipo="ALIAS_CANDIDATO",entidad="CLIENTE",campo="cliente",numero_guia=str(g),valor_documental=v,evidencias=({"tipo":"RUT_EXACTO"},),acciones_permitidas=("CONFIRMAR_ALIAS","RECHAZAR","POSPONER")) for g,v in ((464529,"TORRES OCARANEA LTDA"),(464698,"EDMA SA"),(464699,"KBEMA SA"))]
    destino=_decision(tipo="DESTINO_SIN_CONFIRMAR",entidad="RELACION_OBRA_DESTINO",campo="obra_destino",numero_guia="464550",valor_documental="EMPRESA CONST SIGRO",evidencias=({"tipo":"OBRA_IDENTIFICADA"},),acciones_permitidas=("CONFIRMAR_RELACION","RECHAZAR","POSPONER"))
    artefacto=generar_artefacto(ruta_dataset=dataset,carpeta_catalogos=carpeta,decisiones=[alias[0],alias[0],*alias[1:],destino])
    assert artefacto["schema_version"]==1 and len(artefacto["decisiones"])==4
    assert [x["tipo"] for x in artefacto["decisiones"]].count("ALIAS_CANDIDATO")==3
    assert [x["tipo"] for x in artefacto["decisiones"]].count("DESTINO_SIN_CONFIRMAR")==1
