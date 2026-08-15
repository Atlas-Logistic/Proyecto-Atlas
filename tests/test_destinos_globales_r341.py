import json
from pathlib import Path
from atlas_core.catalogo_clientes import CatalogoClientes,EstadoCalidadCliente
from atlas_core.catalogo_destinos import CatalogoDestinos,EstadoCalidadDestino,EstadoBusquedaDestino
from atlas_core.migracion_destinos_globales import migrar_destinos_globales

def _cliente(ruta,nombre,rut): return CatalogoClientes(ruta).crear(razon_social=nombre,rut=rut,fuente="TEST",estado_calidad=EstadoCalidadCliente.CONFIRMADO)
def _entorno(tmp_path):
 c=tmp_path/"clientes.json"; a=_cliente(c,"CONSTRUMART SA","50.234.350-5"); b=_cliente(c,"EASY SA","76.083.093-3"); d=tmp_path/"destinos.json"; return c,a,b,CatalogoDestinos(d,ruta_clientes=c),d

def test_destino_global_se_reutiliza_entre_clientes(tmp_path):
 c,a,b,repo,_=_entorno(tmp_path); uno=repo.crear(cliente_id=a.cliente_id,nombre_destino="OBRA X",direccion="AV. VICUÑA MACKENNA 3451",comuna="SAN JOAQUIN",region="RM",pais="CHILE",fuente="TEST")
 dos=repo.crear_o_reutilizar_global(nombre_destino="OTRO NOMBRE",direccion="AV VICUNA MACKENNA 3451",comuna="SAN JOAQUIN",region="RM",fuente="TEST")
 assert uno.destino_id==dos.destino_id and len(repo.listar())==1
 assert repo.buscar("OBRA X",cliente_id=b.cliente_id).destino.destino_id==uno.destino_id

def test_colisiones_conservadoras(tmp_path):
 _,a,_,repo,_=_entorno(tmp_path); primero=repo.crear(cliente_id=a.cliente_id,nombre_destino="A",direccion="CALLE 123",comuna="NORTE",region="RM",pais="CHILE",fuente="TEST")
 distinto_comuna=repo.crear(cliente_id="",nombre_destino="B",direccion="CALLE 123",comuna="SUR",region="RM",pais="CHILE",fuente="TEST")
 distinto_numero=repo.crear(cliente_id="",nombre_destino="C",direccion="CALLE 132",comuna="NORTE",region="RM",pais="CHILE",fuente="TEST")
 assert len({primero.destino_id,distinto_comuna.destino_id,distinto_numero.destino_id})==3

def test_direccion_incompleta_se_abstiene(tmp_path):
 _,_,_,repo,_=_entorno(tmp_path)
 import pytest
 with pytest.raises(ValueError): repo.resolver_direccion_global("")

def test_migracion_preserva_ids_coordenadas_y_retira_duplicado(tmp_path):
 c,a,b,repo,ruta=_entorno(tmp_path); uno=repo.crear(cliente_id=a.cliente_id,nombre_destino="A",direccion="CALLE 123",comuna="NORTE",region="RM",pais="CHILE",fuente="TEST",latitud=-33.1,longitud=-70.1,estado_calidad=EstadoCalidadDestino.CONFIRMADO)
 # Simula V1 permitido antes del cambio global.
 datos=json.loads(ruta.read_text()); duplicado={**datos["destinos"][0],"destino_id":"destino-historico","cliente_id":b.cliente_id,"estado_calidad":"PENDIENTE"};datos["destinos"].append(duplicado);ruta.write_text(json.dumps(datos),encoding="utf-8")
 obras=tmp_path/"obras.json";obras.write_text(json.dumps({"version_formato":1,"obras":[],"relaciones":[]}),encoding="utf-8")
 resultado=migrar_destinos_globales(ruta_destinos=ruta,ruta_obras_destinos=obras,carpeta_respaldos=tmp_path/"respaldos")
 finales=json.loads(ruta.read_text())["destinos"]
 assert resultado["total_antes"]==resultado["total_despues"]==2 and resultado["ids_preservados"]
 assert {d["destino_id"] for d in finales}=={uno.destino_id,"destino-historico"}
 assert next(d for d in finales if d["destino_id"]==uno.destino_id)["latitud"]==-33.1
 assert sum(d["estado_vigencia"]=="ACTIVO" for d in finales)==1
 assert (Path(resultado["respaldo"])/"destinos.json").is_file()
