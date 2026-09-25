"""Reproceso documental aislado y promoción focal recuperable."""
from __future__ import annotations
import csv, hashlib, json, os, shutil, subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping
from atlas_core.almacenamiento_portable import bloqueo_sesion, escribir_json_atomico
from atlas_core.evidencia_documental import resolver_ruta_evidencia
from atlas_core.procesamiento_masivo import COLUMNAS, procesar_archivo
from atlas_core.rutas.modelos import EstadoRuta, ResultadoGeocodificacion, ResultadoRuta
from atlas_core.validadores import validar_rut_chileno
from atlas_core.modelos import EstadoValidacion
from atlas_core.credibilidad_campos import evaluar_credibilidad_direccion, evaluar_credibilidad_entidad_nombre

NOMBRE_MANIFIESTO="manifiesto_candidato.json"; NOMBRE_JOURNAL="journal_promocion.json"
@dataclass(frozen=True)
class DocumentoSeleccionado: archivo:str; sha256:str
class ProveedorRutasSinRed:
    nombre="cuarentena_sin_red"; version="1"
    def __init__(self): self.llamadas=0
    def geocodificar(self,direccion): self.llamadas+=1; return ResultadoGeocodificacion(EstadoRuta.PROVEEDOR_NO_DISPONIBLE,(),"CUARENTENA_SIN_RED")
    def geocodificar_estructurado(self,direccion,contexto): return self.geocodificar(direccion)
    def calcular_ruta(self,origen,destino,perfil): self.llamadas+=1; return ResultadoRuta(EstadoRuta.PROVEEDOR_NO_DISPONIBLE,motivo="CUARENTENA_SIN_RED")
def _sha(p:Path)->str:
    h=hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda:f.read(1048576),b""): h.update(b)
    return h.hexdigest()
def _leer(p:Path):
    with p.open("r",newline="",encoding="utf-8-sig") as f:return list(csv.DictReader(f,delimiter=";"))
def _escribir(p:Path,filas):
    with p.open("w",newline="",encoding="utf-8-sig") as f:
        w=csv.DictWriter(f,fieldnames=COLUMNAS,delimiter=";",extrasaction="ignore");w.writeheader();w.writerows(filas);f.flush();os.fsync(f.fileno())
def _commit():
    try:return subprocess.check_output(["git","rev-parse","HEAD"],text=True,stderr=subprocess.DEVNULL).strip()
    except Exception:return "DESCONOCIDO"
def _catalogos(origen:Path,destino:Path):
    hashes={};destino.mkdir(parents=True,exist_ok=True)
    for p in origen.rglob("*"):
        if p.is_file():
            rel=p.relative_to(origen);q=destino/rel;q.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,q);hashes[str(rel).replace("\\","/")]=_sha(p)
    return hashes
def _candidata(actual,extraido):
    salida=dict(actual)
    for c in COLUMNAS:
        if c in extraido: salida[c]=str(extraido[c] if extraido[c] is not None else "")
    salida["archivo"]=actual["archivo"];return salida
def _ruta_valida(f):
    if f.get("estado_ruta")!=EstadoRuta.RUTA_CALCULADA.value:return True,"SIN_RUTA_CALCULADA"
    campos=("planta_origen_id","destino_id","longitud_entrega","latitud_entrega","proveedor_ruta","distancia_km","duracion_min")
    faltan=[c for c in campos if not str(f.get(c,"")).strip()]
    try: positivo=float(f.get("distancia_km",0))>0 and float(f.get("duracion_min",0))>0
    except (ValueError,TypeError):positivo=False
    return (not faltan and positivo, "RUTA_TRAZABLE" if not faltan and positivo else "RUTA_CALCULADA_SIN_ENDPOINT_TRAZABLE:"+",".join(faltan or ["DISTANCIA_O_DURACION"]))
def _semantica(f):
    e=[]
    for c in ("cliente","obra_destino"):
        r=evaluar_credibilidad_entidad_nombre(f.get(c,""))
        if not r.confiable():e.append(f"{c}:ETIQUETA_O_ENTIDAD_NO_CREDIBLE:{r.motivo}")
    r=evaluar_credibilidad_direccion(f.get("despachar_a_crudo",""))
    if not r.confiable():e.append(f"despachar_a_crudo:ETIQUETA_O_DIRECCION_NO_CREDIBLE:{r.motivo}")
    rc,rh=str(f.get("rut_cliente","")).strip(),str(f.get("rut_chofer","")).strip()
    if rc and validar_rut_chileno(rc).estado!=EstadoValidacion.VALIDO:e.append("rut_cliente:FORMATO_INVALIDO")
    if rc and rc==rh:e.append("rut_cliente:COINCIDE_CON_RUT_CHOFER")
    return e
def _validar(docs,transporte,cardinalidad):
    errores=[];ids=set()
    if len(docs)!=cardinalidad:errores.append("CARDINALIDAD_CANDIDATOS_INCORRECTA")
    for d in docs:
        f=d["fila_candidata"];g,t=str(f.get("numero_guia","")).strip(),str(f.get("numero_transporte","")).strip()
        if not g or g=="No encontrado":errores.append(f"{d['archivo']}:GUIA_AUSENTE")
        if transporte and t!=transporte:errores.append(f"{d['archivo']}:TRANSPORTE_INESPERADO")
        if (g,t) in ids:errores.append(f"{d['archivo']}:IDENTIDAD_DOCUMENTAL_DUPLICADA")
        ids.add((g,t));errores += [f"{d['archivo']}:{x}" for x in _semantica(f)]
        ok,m=_ruta_valida(f)
        if not ok:
            for c in ("distancia_km","duracion_min","proveedor_ruta","estado_ruta","motivo_ruta"):f[c]=""
            d["advertencias"].append(m)
    return errores
def _actualizar_proyeccion_focal(*,raiz:Path,filas,transporte:str,respaldo:Path):
    """Reemplaza sólo la fila de un transporte en el reporte vigente, si existe.

    No regenera el informe ni recorre rutas; la agrupación usa exclusivamente
    las filas ya preparadas de ese transporte.
    """
    reporte=raiz/"reportes/actual/viajes.csv"
    if not reporte.is_file():return False
    from atlas_core.gestor_viajes import agrupar_viajes
    from atlas_core.reporte_viajes import COLUMNAS_VIAJES, _fila_viaje
    grupo=[f for f in filas if str(f.get("numero_transporte","")).strip()==transporte]
    viajes,_=agrupar_viajes(grupo,guias_revision_humana=())
    if len(viajes)!=1:return False
    with reporte.open("r",newline="",encoding="utf-8-sig") as f: anteriores=list(csv.DictReader(f,delimiter=";"))
    shutil.copy2(reporte,respaldo/reporte.name)
    nueva=_fila_viaje(viajes[0])
    finales=[nueva if str(r.get("numero_transporte","")).strip()==transporte else r for r in anteriores]
    if not any(str(r.get("numero_transporte","")).strip()==transporte for r in anteriores):return False
    tmp=reporte.with_suffix(".cuarentena.tmp")
    with tmp.open("w",newline="",encoding="utf-8-sig") as f:
        w=csv.DictWriter(f,fieldnames=COLUMNAS_VIAJES,delimiter=";",extrasaction="ignore");w.writeheader();w.writerows(finales);f.flush();os.fsync(f.fileno())
    os.replace(tmp,reporte);return True
def generar_candidato(*,raiz_atlas,workspace,documentos:Iterable[DocumentoSeleccionado],cardinalidad_esperada:int,transporte_esperado:str|None=None,proveedor_ocr=None):
    raiz,ws=Path(raiz_atlas),Path(workspace);seleccion=list(documentos)
    if not seleccion or len(seleccion)!=cardinalidad_esperada:raise ValueError("CARDINALIDAD_ESPERADA_INCORRECTA")
    if len({s.archivo for s in seleccion}) != len(seleccion):raise ValueError("ARCHIVO_SELECCIONADO_DUPLICADO")
    if ws.exists():raise ValueError("WORKSPACE_CUARENTENA_YA_EXISTE")
    filas=_leer(raiz/"operacion/actual/analisis_completo_guias.csv");por={f.get("archivo",""):f for f in filas}
    # Preflight completo antes de crear el workspace: una discrepancia de
    # identidad no deja siquiera un artefacto parcial de cuarentena.
    for s in seleccion:
        actual=por.get(s.archivo)
        if actual is None:raise ValueError(f"FILA_NO_ENCONTRADA:{s.archivo}")
        if transporte_esperado and actual.get("numero_transporte","").strip()!=transporte_esperado:raise ValueError(f"TRANSPORTE_ACTUAL_INESPERADO:{s.archivo}")
        e=resolver_ruta_evidencia(raiz,s.archivo)
        if e.ruta is None:raise ValueError(f"ORIGINAL_NO_ENCONTRADO:{s.archivo}")
        if _sha(e.ruta)!=s.sha256:raise ValueError(f"SHA_INCORRECTO:{s.archivo}")
    ws.mkdir(parents=True)
    hashes=_catalogos(raiz/"catalogos_privados",ws/"catalogos");docs=[]
    for s in seleccion:
        actual=por.get(s.archivo)
        if actual is None:raise ValueError(f"FILA_NO_ENCONTRADA:{s.archivo}")
        if transporte_esperado and actual.get("numero_transporte","").strip()!=transporte_esperado:raise ValueError(f"TRANSPORTE_ACTUAL_INESPERADO:{s.archivo}")
        e=resolver_ruta_evidencia(raiz,s.archivo)
        if e.ruta is None:raise ValueError(f"ORIGINAL_NO_ENCONTRADO:{s.archivo}")
        if _sha(e.ruta)!=s.sha256:raise ValueError(f"SHA_INCORRECTO:{s.archivo}")
        copia=ws/"originales"/Path(s.archivo).name;copia.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(e.ruta,copia)
        sin_red=ProveedorRutasSinRed();extraido=procesar_archivo(copia,proveedor=proveedor_ocr,carpeta_catalogos=ws/"catalogos",proveedor_rutas=sin_red,proveedor_geocodificacion_fallback=sin_red,directorio_trazas_ocr=ws/"trazas_ocr",directorio_orientacion=ws/"orientacion",referencia_imagen_traza=s.archivo)
        candidata=_candidata(actual,extraido);docs.append({"archivo":s.archivo,"sha256_esperado":s.sha256,"sha256_observado":_sha(e.ruta),"fila_actual":actual,"fila_candidata":candidata,"diff":{k:{"antes":actual.get(k,""),"despues":candidata.get(k,"")} for k in COLUMNAS if actual.get(k,"")!=candidata.get(k,"")},"advertencias":[],"llamadas_red_bloqueadas":sin_red.llamadas})
    errores=_validar(docs,transporte_esperado,cardinalidad_esperada)
    m={"schema_version":1,"estado":"APTO_PARA_PROMOCION" if not errores else "NO_APTO_PARA_PROMOCION","creado_en":datetime.now(timezone.utc).isoformat(),"commit_motor":_commit(),"transporte_esperado":transporte_esperado or "","cardinalidad_esperada":cardinalidad_esperada,"catalogos_sha256":hashes,"documentos":docs,"validaciones":errores,"aislamiento":{"red":"BLOQUEADA","b1":"NO_EJECUTADO","dataset":"NO_MODIFICADO","catalogos_productivos":"SOLO_LECTURA","caches_productivas":"NO_MODIFICADAS"}}
    escribir_json_atomico(ws/NOMBRE_MANIFIESTO,m);return m
def promover_candidato(*,raiz_atlas,workspace):
    raiz,ws=Path(raiz_atlas),Path(workspace);m=json.loads((ws/NOMBRE_MANIFIESTO).read_text(encoding="utf-8"))
    if m.get("estado")!="APTO_PARA_PROMOCION":raise ValueError("PAQUETE_NO_APTO")
    sel={d["archivo"]:d for d in m.get("documentos",[])};actual=raiz/"operacion/actual";dataset=actual/"analisis_completo_guias.csv";decisiones=actual/"decisiones_pendientes.json"
    with bloqueo_sesion(actual,"promocion_reproceso_cuarentena"):
        hashes_actuales={}
        for p in (raiz/"catalogos_privados").rglob("*"):
            if p.is_file():hashes_actuales[str(p.relative_to(raiz/"catalogos_privados")).replace("\\","/")]=_sha(p)
        if hashes_actuales != m.get("catalogos_sha256",{}):raise ValueError("CATALOGOS_CAMBIARON_ANTES_DE_PROMOCION")
        filas=_leer(dataset);encontradas=[f for f in filas if f.get("archivo") in sel]
        if len(encontradas)!=len(sel):raise ValueError("FILAS_SELECCIONADAS_NO_COINCIDEN")
        for f in encontradas:
            e=resolver_ruta_evidencia(raiz,f["archivo"])
            if e.ruta is None or _sha(e.ruta)!=sel[f["archivo"]]["sha256_observado"]:raise ValueError("SHA_CAMBIO_ANTES_DE_PROMOCION")
        identidades_no_seleccionadas={(str(f.get("numero_guia","")).strip(),str(f.get("numero_transporte","")).strip()) for f in filas if f.get("archivo") not in sel}
        identidades_candidatas={(str(d["fila_candidata"].get("numero_guia","")).strip(),str(d["fila_candidata"].get("numero_transporte","")).strip()) for d in sel.values()}
        if identidades_no_seleccionadas & identidades_candidatas:raise ValueError("DUPLICACION_IDENTIDAD_DOCUMENTAL")
        b=ws/"backup_promocion";b.mkdir(exist_ok=True);shutil.copy2(dataset,b/dataset.name)
        if decisiones.exists():shutil.copy2(decisiones,b/decisiones.name)
        j={"estado":"PREPARADO","archivos":sorted(sel),"creado_en":datetime.now(timezone.utc).isoformat()};escribir_json_atomico(ws/NOMBRE_JOURNAL,j)
        try:
            nuevas=[dict(sel[f["archivo"]]["fila_candidata"]) if f.get("archivo") in sel else f for f in filas];tmp=dataset.with_suffix(".cuarentena.tmp");_escribir(tmp,nuevas);os.replace(tmp,dataset)
            if decisiones.exists():
                x=json.loads(decisiones.read_text(encoding="utf-8"));x["decisiones"]=[d for d in x.get("decisiones",[]) if str((d.get("documento") or {}).get("archivo","")) not in sel];escribir_json_atomico(decisiones,x)
            transporte=str(next(iter(sel.values()))["fila_candidata"].get("numero_transporte","")).strip()
            proyeccion=_actualizar_proyeccion_focal(raiz=raiz,filas=nuevas,transporte=transporte,respaldo=b)
            j["estado"]="COMMIT";j["proyeccion_actualizada"]=proyeccion;escribir_json_atomico(ws/NOMBRE_JOURNAL,j);return {"estado":"COMMIT","archivos":sorted(sel),"proyeccion_actualizada":proyeccion}
        except Exception:
            shutil.copy2(b/dataset.name,dataset)
            if (b/decisiones.name).exists():shutil.copy2(b/decisiones.name,decisiones)
            reporte=raiz/"reportes/actual/viajes.csv"
            if (b/reporte.name).exists():shutil.copy2(b/reporte.name,reporte)
            j["estado"]="ROLLBACK";escribir_json_atomico(ws/NOMBRE_JOURNAL,j);raise
