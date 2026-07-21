"""V1F: experimento aislado de número de guía con OCR espacial almacenado."""
from __future__ import annotations
import csv, hashlib, json, os, re, tempfile, unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

VERSION="V1F-1.0"
REGLA_VERSION="numero-guia-contextual-conservador-v1"
SALIDAS=("detalle_experimento.csv","metricas_experimento.json","resumen_experimento.md","manifest_experimento.json")
COLUMNAS=("nombre_archivo","cohorte","estado_gt","numero_guia_gt","numero_guia_atlas_v1b","clasificacion_v1b","anclas_detectadas","ancla_seleccionada","tipo_ancla","bloques_contexto","candidatos_detectados","candidatos_descartados","candidato_experimental","decision_emitida","resultado_experimental","distancia_horizontal","distancia_vertical","alineacion","confianza_ancla","confianza_candidato","competidores_detectados","puntuacion_desglosada","motivo_decision","regla_version","fuente_bloques","hash_fuente_bloques","ocr_ejecutado")
COMPETIDORES={"SAP":r"\bSAP\b","TRANSPORTE":r"TRANSPORTE","ORDEN_COMPRA":r"ORDEN\s+DE\s+COMPRA|\bOC\b","PEDIDO":r"PEDIDO","CLIENTE":r"CLIENTE","DESTINATARIO":r"DESTINATARIO","RUT":r"\bRUT\b","FECHA":r"FECHA|\b\d{1,2}[-/]\d{1,2}[-/]\d{4}\b","PESO_CANTIDAD":r"PESO|CANTIDAD"}

def sha256(path):
 h=hashlib.sha256()
 with Path(path).open("rb") as f:
  for b in iter(lambda:f.read(1048576),b""):h.update(b)
 return h.hexdigest().upper()
def _base(v):return PurePosixPath(str(v).replace("\\","/")).name
def normalizar(t):
 s=''.join(c for c in unicodedata.normalize("NFD",str(t).upper()) if unicodedata.category(c)!="Mn")
 return ' '.join(re.sub(r"[^A-Z0-9]+"," ",s).split())
def _csv(path):
 with Path(path).open(encoding="utf-8-sig",newline="") as f:return list(csv.DictReader(f,delimiter=";"))
def _div(a,b):return None if not b else a/b

def bloque(f):
 x1,y1,x2,y2=map(float,(f["x_min"],f["y_min"],f["x_max"],f["y_max"]));return {"orden":int(f["indice_bloque"]),"texto":f["texto"],"normalizado":normalizar(f["texto"]),"confianza":float(f["confianza"]),"bbox":[x1,y1,x2,y2],"centro_x":(x1+x2)/2,"centro_y":(y1+y2)/2,"ancho":x2-x1,"alto":y2-y1}
def _union(bs):return [min(b["bbox"][0] for b in bs),min(b["bbox"][1] for b in bs),max(b["bbox"][2] for b in bs),max(b["bbox"][3] for b in bs)]
def _centro(bb):return ((bb[0]+bb[2])/2,(bb[1]+bb[3])/2)
def _dist(a,b):
 ax,ay=_centro(a);bx,by=_centro(b);return abs(ax-bx),abs(ay-by)
def _alineacion(a,b):
 dx,dy=_dist(a,b);ha=max(a[3]-a[1],b[3]-b[1],1);wa=max(a[2]-a[0],b[2]-b[0],1)
 if dy<=ha*.8:return "MISMA_FILA"
 if dx<=wa*.8:return "MISMA_COLUMNA"
 return "PROXIMO"

def detectar_anclas(bs):
 piezas=[]
 for b in bs:
  n=b["normalizado"];tipos=set()
  if re.search(r"\bGUIA\b",n):tipos.add("GUIA")
  if "DESPACHO" in n:tipos.add("DESPACHO")
  if "ELECTRONICA" in n:tipos.add("ELECTRONICA")
  if tipos:piezas.append((b,tipos))
 anclas=[]
 # Una ancla completa puede estar en un bloque o fragmentada en bloques próximos.
 for b,t in piezas:
  if "GUIA" in t and ("DESPACHO" in t or "ELECTRONICA" in t):anclas.append({"tipo":"ANCLA_GUIA_COMPLETA","bloques":[b],"componentes":sorted(t)})
 for gb,gt in piezas:
  if "GUIA" not in gt:continue
  vecinos=[];componentes=set(gt)
  for b,t in piezas:
   if b is gb:continue
   dx,dy=_dist(gb["bbox"],b["bbox"])
   if dx<=350 and dy<=120:vecinos.append(b);componentes|=t
  if "DESPACHO" in componentes and "ELECTRONICA" in componentes:
   usados=[gb]+vecinos;anclas.append({"tipo":"ANCLA_GUIA_FRAGMENTADA","bloques":usados,"componentes":sorted(componentes)})
 unicos={}
 for a in anclas:
  ids=tuple(sorted(b["orden"] for b in a["bloques"]));a["bbox"]=_union(a["bloques"]);a["confianza"]=min(b["confianza"] for b in a["bloques"]);a["texto"]=" | ".join(b["texto"] for b in a["bloques"]);unicos[(a["tipo"],ids)]=a
 return list(unicos.values())

def detectar_marcadores(bs):
 out=[]
 for b in bs:
  raw=str(b["texto"]).upper();n=b["normalizado"]
  # NP, NRO, NUMERO o N/N°/Nº/N? como token; nunca son ancla por sí solos.
  if re.search(r"(?:^|\s)(NP|NRO|NUMERO|N\s*[°º?]?)(?=\s|\d|$)",raw) or re.fullmatch(r"N|NP|NRO|NUMERO",n):out.append(b)
 return out
def detectar_candidatos(bs):
 out=[];rech=[]
 for b in bs:
  nums=re.findall(r"(?<![A-Za-z0-9])\d+(?![A-Za-z0-9])",str(b["texto"]))
  for v in nums:
   item={"valor":v,"bloque":b,"origen":"TOKEN_BLOQUE"}
   if 5<=len(v)<=8:out.append(item)
   elif len(v)>=4:rech.append({**item,"motivo":"LONGITUD_INVALIDA"})
 return out,rech
def detectar_competidores(bs):
 out=[]
 for b in bs:
  for tipo,pat in COMPETIDORES.items():
   if re.search(pat,b["normalizado"]):out.append({"tipo":tipo,"bloque":b})
 return out
def _asociado_competidor(c,comp):
 cb=c["bloque"]["bbox"];bb=comp["bloque"]["bbox"];dx,dy=_dist(cb,bb);al=_alineacion(bb,cb)
 # Debe seguir o quedar a la derecha/debajo de la etiqueta competidora.
 posterior=c["bloque"]["orden"]>=comp["bloque"]["orden"] or cb[0]>=bb[2] or cb[1]>=bb[3]
 return posterior and ((al=="MISMA_FILA" and dx<=240) or (al=="MISMA_COLUMNA" and dy<=100))

def decidir(bs,atlas):
 anclas=detectar_anclas(bs);marcadores=detectar_marcadores(bs);cands,rech=detectar_candidatos(bs);comps=detectar_competidores(bs);evaluados=[]
 for c in cands:
  mejores=[]
  for a in anclas:
   for m in marcadores:
    da=_dist(a["bbox"],m["bbox"]);dc=_dist(m["bbox"],c["bloque"]["bbox"]);am=_alineacion(a["bbox"],m["bbox"]);mc=_alineacion(m["bbox"],c["bloque"]["bbox"])
    # Cadena compacta y explicable; marcador y candidato pueden compartir bloque.
    enlace_ancla=(da[0]<=380 and da[1]<=150)
    enlace_candidato=(m["orden"]==c["bloque"]["orden"] or (dc[0]<=160 and dc[1]<=80 and mc in {"MISMA_FILA","MISMA_COLUMNA"}))
    if enlace_ancla and enlace_candidato:mejores.append((da[0]+da[1]+dc[0]+dc[1],a,m,am,mc,da,dc))
  if not mejores:rech.append({**c,"motivo":"SIN_CADENA_GUIA_MARCADOR"});continue
  best=min(mejores,key=lambda x:(x[0],x[1]["bbox"],x[2]["orden"]));compet=[x for x in comps if _asociado_competidor(c,x)]
  if compet:rech.append({**c,"motivo":"ASOCIADO_COMPETIDOR","competidores":[x["tipo"] for x in compet]});continue
  _,a,m,am,mc,da,dc=best;evaluados.append({"candidato":c,"ancla":a,"marcador":m,"alineacion":mc,"distancia_ancla_marcador":da,"distancia_marcador_candidato":dc,"competidores":[]})
 # Preservación obligatoria: nunca override de Atlas presente.
 if re.fullmatch(r"\d{5,8}",str(atlas).strip()):return {"valor":str(atlas).strip(),"emitida":True,"motivo":"Valor Atlas presente; conservación obligatoria sin override","anclas":anclas,"candidatos":cands,"descartados":rech,"competidores":comps,"seleccion":None,"diagnosticos":evaluados}
 valores={e["candidato"]["valor"] for e in evaluados}
 if len(valores)!=1:return {"valor":"ABSTENERSE","emitida":False,"motivo":"Sin candidato contextual único y seguro","anclas":anclas,"candidatos":cands,"descartados":rech,"competidores":comps,"seleccion":None,"diagnosticos":evaluados}
 valor=next(iter(valores));sel=min((e for e in evaluados if e["candidato"]["valor"]==valor),key=lambda e:sum(e["distancia_ancla_marcador"])+sum(e["distancia_marcador_candidato"]))
 return {"valor":valor,"emitida":True,"motivo":"Cadena única: evidencia de guía -> marcador -> candidato","anclas":anclas,"candidatos":cands,"descartados":rech,"competidores":comps,"seleccion":sel,"diagnosticos":evaluados}

def decidir_bloques_ocr(bloques_ocr, atlas="No encontrado"):
 """Aplica la regla congelada a bloques OCR productivos, sin releer la imagen."""
 convertidos=[]
 for indice,item in enumerate(bloques_ocr):
  xs=[float(p[0]) for p in item.bounding_box];ys=[float(p[1]) for p in item.bounding_box]
  convertidos.append(bloque({"indice_bloque":indice,"texto":str(item.texto),"confianza":float(item.confianza),"x_min":min(xs),"y_min":min(ys),"x_max":max(xs),"y_max":max(ys)}))
 return decidir(convertidos,atlas)

def _simple_b(b):return {k:b[k] for k in ("orden","texto","normalizado","confianza","bbox","centro_x","centro_y","ancho","alto")}
def _simple_a(a):return {"tipo":a["tipo"],"texto":a["texto"],"componentes":a["componentes"],"bbox":a["bbox"],"confianza":a["confianza"],"ordenes":[b["orden"] for b in a["bloques"]]}
def _simple_c(c):return {"valor":c["valor"],"origen":c["origen"],"bloque":_simple_b(c["bloque"])}
def _simple_r(r):
 d={"valor":r["valor"],"motivo":r["motivo"],"bloque":_simple_b(r["bloque"])}
 if "competidores" in r:d["competidores"]=r["competidores"]
 return d
def _metricas(filas):
 med=[f for f in filas if f["estado_gt"]=="MEDIBLE_CON_VALOR"];emit=[f for f in med if f["decision_emitida"]=="SI"];ok=sum(f["resultado_experimental"] in {"CONSERVADO_CORRECTO","RECUPERADO"} for f in med)
 return {"casos":len(filas),"casos_medibles":len(med),"aciertos_conservados":sum(f["resultado_experimental"]=="CONSERVADO_CORRECTO" for f in med),"controles_candidato_diferente":sum(f["cohorte"]=="CONTROL_ACIERTO" and json.loads(f["candidatos_detectados"] or "[]") and any(x["valor"]!=f["numero_guia_atlas_v1b"] for x in json.loads(f["candidatos_detectados"])) for f in med),"objetivos_confirmados":sum(f["cohorte"]=="OBJETIVO_CONFIRMADO" for f in med),"objetivos_recuperados":sum(f["cohorte"]=="OBJETIVO_CONFIRMADO" and f["resultado_experimental"]=="RECUPERADO" for f in med),"control_abstencion":sum(f["cohorte"]=="CONTROL_ABSTENCION" for f in med),"falsos_positivos":sum(f["resultado_experimental"]=="CANDIDATO_INCORRECTO" for f in med),"candidatos_incorrectos":sum(f["resultado_experimental"]=="CANDIDATO_INCORRECTO" for f in med),"abstenciones":sum(f["decision_emitida"]=="NO" for f in med),"aciertos_totales":ok,"exactitud_end_to_end":_div(ok,len(med)),"exactitud_condicionada":_div(ok,len(emit)),"matriz_v1b_v1f":dict(Counter(f"{f['clasificacion_v1b']}->{f['resultado_experimental']}" for f in med))}

def ejecutar(bloques_path,gt_path,detalle_v1b_path,atlas_path,salida,*,sobrescribir=False,fecha=None,antes_publicar=None):
 entradas={"bloques":Path(bloques_path),"ground_truth":Path(gt_path),"detalle_v1b":Path(detalle_v1b_path),"atlas":Path(atlas_path)};hs={k:sha256(v) for k,v in entradas.items()};br=_csv(bloques_path);gt=_csv(gt_path);dv=_csv(detalle_v1b_path)
 por=defaultdict(list)
 for r in br:por[_base(r["nombre_archivo"])].append(r)
 nombres=sorted(por,key=str.casefold)
 if len(nombres)!=30 or any(not por[n] for n in nombres):raise ValueError("V1F requiere bloques para 30 imágenes únicas")
 gi={(r["nombre_archivo"],r["campo"]):r for r in gt};di={r["nombre_archivo"]:r for r in dv if r["campo"]=="numero_guia"}
 if set(nombres)!=set(di) or any((n,"numero_guia") not in gi for n in nombres):raise ValueError("Los basenames de las entradas no coinciden")
 filas=[]
 for n in nombres:
  bs=[bloque(x) for x in sorted(por[n],key=lambda x:int(x["indice_bloque"]))];g=gi[(n,"numero_guia")];d=di[n];atlas=d["valor_atlas_original"].strip();cl="ACIERTO" if d["clasificacion"]=="ACIERTO_EXACTO" else d["clasificacion"] if d["clasificacion"]=="FALSO_NEGATIVO" else "EXCLUIDO"
  if g["estado_gt"]!="MEDIBLE_CON_VALOR":coh="EXCLUIDO"
  elif cl=="ACIERTO":coh="CONTROL_ACIERTO"
  elif g["valor_gt"] in " ".join(x["texto"] for x in bs) or normalizar(g["valor_gt"]) in normalizar(" ".join(x["texto"] for x in bs)):coh="OBJETIVO_CONFIRMADO"
  else:coh="CONTROL_ABSTENCION"
  r=decidir(bs,atlas);v=r["valor"]
  if coh=="EXCLUIDO":res="EXCLUIDO"
  elif cl=="ACIERTO":res="CONSERVADO_CORRECTO" if v==g["valor_gt"] else "CANDIDATO_INCORRECTO"
  elif v=="ABSTENERSE":res="SIGUE_AUSENTE"
  elif v==g["valor_gt"]:res="RECUPERADO"
  else:res="CANDIDATO_INCORRECTO"
  s=r["seleccion"];anclas=[_simple_a(x) for x in r["anclas"]];cands=[_simple_c(x) for x in r["candidatos"]];desc=[_simple_r(x) for x in r["descartados"]];comps=[{"tipo":x["tipo"],"bloque":_simple_b(x["bloque"])} for x in r["competidores"]]
  filas.append({"nombre_archivo":n,"cohorte":coh,"estado_gt":g["estado_gt"],"numero_guia_gt":g["valor_gt"],"numero_guia_atlas_v1b":atlas,"clasificacion_v1b":cl,"anclas_detectadas":json.dumps(anclas,ensure_ascii=False),"ancla_seleccionada":"" if not s else json.dumps(_simple_a(s["ancla"]),ensure_ascii=False),"tipo_ancla":"" if not s else s["ancla"]["tipo"],"bloques_contexto":"" if not s else json.dumps([_simple_b(x) for x in [*s["ancla"]["bloques"],s["marcador"],s["candidato"]["bloque"]]],ensure_ascii=False),"candidatos_detectados":json.dumps(cands,ensure_ascii=False),"candidatos_descartados":json.dumps(desc,ensure_ascii=False),"candidato_experimental":v,"decision_emitida":"SI" if r["emitida"] else "NO","resultado_experimental":res,"distancia_horizontal":"" if not s else s["distancia_marcador_candidato"][0],"distancia_vertical":"" if not s else s["distancia_marcador_candidato"][1],"alineacion":"" if not s else s["alineacion"],"confianza_ancla":"" if not s else s["ancla"]["confianza"],"confianza_candidato":"" if not s else s["candidato"]["bloque"]["confianza"],"competidores_detectados":json.dumps(comps,ensure_ascii=False),"puntuacion_desglosada":"" if not s else json.dumps({"distancia_ancla_marcador":s["distancia_ancla_marcador"],"distancia_marcador_candidato":s["distancia_marcador_candidato"],"regla":"umbrales categóricos; no suma decisoria"}),"motivo_decision":r["motivo"],"regla_version":REGLA_VERSION,"fuente_bloques":str(bloques_path),"hash_fuente_bloques":hs["bloques"],"ocr_ejecutado":"NO"})
 grupos={"CONTROL_ACIERTO":[f for f in filas if f["cohorte"]=="CONTROL_ACIERTO"],"OBJETIVO_CONFIRMADO":[f for f in filas if f["cohorte"]=="OBJETIVO_CONFIRMADO"],"CONTROL_ABSTENCION":[f for f in filas if f["cohorte"]=="CONTROL_ABSTENCION"],"TOTAL":filas};mets={k:_metricas(v) for k,v in grupos.items()};tot=mets["TOTAL"]
 conclusion="PROMETEDOR PARA SEGUNDA FASE" if tot["aciertos_conservados"]==24 and tot["objetivos_recuperados"]>=1 and tot["falsos_positivos"]==0 else "ABANDONAR"
 resultado={"version":VERSION,"regla_version":REGLA_VERSION,"linea_base_v1b":{"medibles":27,"aciertos_exactos":24,"errores_valor":0,"falsos_negativos":3,"excluidos":3},"metricas":mets,"conclusion":conclusion}
 salida=Path(salida);existentes=[salida/x for x in SALIDAS if (salida/x).exists()]
 if existentes and not sobrescribir:raise FileExistsError("Ya existen resultados V1F")
 salida.mkdir(parents=True,exist_ok=True);now=fecha or datetime.now(timezone.utc).astimezone()
 with tempfile.TemporaryDirectory(prefix=".v1f-",dir=salida) as td:
  t=Path(td)
  with (t/SALIDAS[0]).open("w",encoding="utf-8-sig",newline="") as f:w=csv.DictWriter(f,fieldnames=COLUMNAS,delimiter=";");w.writeheader();w.writerows(filas)
  (t/SALIDAS[1]).write_text(json.dumps(resultado,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
  (t/SALIDAS[2]).write_text(f"# Experimento Número de Guía Contextual V1F\n\nResultado no productivo. OCR ejecutado: no.\n\n- Conclusión: **{conclusion}**.\n- Aciertos conservados: {tot['aciertos_conservados']}/24.\n- Objetivos recuperados: {tot['objetivos_recuperados']}/2.\n- Falsos positivos: {tot['falsos_positivos']}.\n- Aciertos totales: {tot['aciertos_totales']}/27.\n",encoding="utf-8")
  out={n:sha256(t/n) for n in SALIDAS[:3]};man={"version":VERSION,"regla_version":REGLA_VERSION,"fecha_hora":now.isoformat(timespec="seconds"),"universo":{"imagenes":30,"medibles":27,"excluidos":3},"cohortes":dict(Counter(f["cohorte"] for f in filas)),"entradas":{k:{"ruta":str(v),"sha256":hs[k]} for k,v in entradas.items()},"metricas_v1b":resultado["linea_base_v1b"],"metricas_v1f":mets,"aciertos_conservados":tot["aciertos_conservados"],"recuperaciones":tot["objetivos_recuperados"],"abstenciones":tot["abstenciones"],"falsos_positivos":tot["falsos_positivos"],"conclusion":conclusion,"salidas":{n:{"sha256":h} for n,h in out.items()},"ocr_ejecutado":False,"extractor_productivo_modificado":False,"comparador_modificado":False,"ground_truth_modificado":False,"resultado_no_productivo":True};(t/SALIDAS[3]).write_text(json.dumps(man,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
  if antes_publicar:antes_publicar()
  if {k:sha256(v) for k,v in entradas.items()}!=hs:raise RuntimeError("Una entrada cambió durante V1F")
  for n in SALIDAS:os.replace(t/n,salida/n)
 return man
