"""Migración única y auditable de destinos V1 a identidad física global."""
from __future__ import annotations
import hashlib
import json
import shutil
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from atlas_core.almacenamiento_portable import bloqueo_sesion, escribir_json_atomico
from atlas_core.catalogo_destinos import EstadoCalidadDestino, EstadoVigenciaDestino, clave_fisica_destino


def _sha(ruta: Path) -> str: return hashlib.sha256(ruta.read_bytes()).hexdigest().upper()


def auditar_destinos_globales(ruta_destinos: str | Path) -> dict[str, object]:
    ruta=Path(ruta_destinos); datos=json.loads(ruta.read_text(encoding="utf-8")); destinos=datos["destinos"]
    grupos=defaultdict(list)
    for d in destinos:
        if str(d.get("direccion","")).strip(): grupos[clave_fisica_destino(d["direccion"],d.get("comuna",""),d.get("region",""))].append(d)
    duplicados={k:v for k,v in grupos.items() if len(v)>1}
    return {"total":len(destinos),"ids_unicos":len({d["destino_id"] for d in destinos}),"con_coordenadas":sum(d.get("latitud") is not None and d.get("longitud") is not None for d in destinos),"sin_coordenadas":sum(d.get("latitud") is None and d.get("longitud") is None for d in destinos),"duplicados":duplicados}


def _rango(destino: dict, relacionados: set[str]) -> tuple[int,int,int,str]:
    return (destino.get("estado_vigencia")==EstadoVigenciaDestino.ACTIVO.value,destino.get("estado_calidad")==EstadoCalidadDestino.CONFIRMADO.value,destino.get("destino_id") in relacionados,str(destino.get("destino_id")))


def migrar_destinos_globales(*, ruta_destinos: str | Path, ruta_obras_destinos: str | Path, carpeta_respaldos: str | Path, reloj=lambda:datetime.now(timezone.utc)) -> dict[str, object]:
    ruta=Path(ruta_destinos); obras=Path(ruta_obras_destinos); respaldos=Path(carpeta_respaldos); antes_sha=_sha(ruta)
    auditoria=auditar_destinos_globales(ruta); datos=json.loads(ruta.read_text(encoding="utf-8")); relaciones=json.loads(obras.read_text(encoding="utf-8")).get("relaciones",[]) if obras.is_file() else []
    por_id={d["destino_id"]:d for d in datos["destinos"]}
    relacionados={r.get("destino_id") for r in relaciones if r.get("estado")=="CONFIRMADA"}
    marca=reloj().astimezone(timezone.utc).strftime("%Y%m%d_%H%M%S"); respaldo=respaldos/f"R3_4_1_DESTINOS_GLOBALES_{marca}"; respaldo.mkdir(parents=True,exist_ok=False)
    shutil.copy2(ruta,respaldo/ruta.name); escribir_json_atomico(respaldo/"manifest.json",{"origen":str(ruta),"sha256":antes_sha,"fecha":reloj().astimezone(timezone.utc).isoformat(),"total":auditoria["total"]})
    fusiones=[]
    with bloqueo_sesion(ruta.parent,"destinos_globales"):
        for clave,grupo_auditado in auditoria["duplicados"].items():
            # La auditoria carga su propia copia JSON; migrar sobre los objetos
            # que se serializaran evita informar cambios que no se persistan.
            grupo=[por_id[d["destino_id"]] for d in grupo_auditado]
            canonico=max(grupo,key=lambda d:_rango(d,relacionados)); retirados=[]
            for duplicado in grupo:
                if duplicado["destino_id"]==canonico["destino_id"]: continue
                previo=duplicado.get("estado_vigencia"); duplicado["estado_vigencia"]="INACTIVO"
                nota=f"MIGRACION_DESTINO_GLOBAL: identidad canónica {canonico['destino_id']}; vigencia previa {previo}; ID histórico preservado."
                duplicado["observacion"]=(str(duplicado.get("observacion","")).rstrip()+" | "+nota).strip(" |")
                retirados.append(duplicado["destino_id"])
            fusiones.append({"clave":list(clave),"destino_id_canonico":canonico["destino_id"],"ids_historicos":retirados})
        escribir_json_atomico(ruta,datos)
    return {"antes_sha256":antes_sha,"despues_sha256":_sha(ruta),"respaldo":str(respaldo),"total_antes":auditoria["total"],"total_despues":len(datos["destinos"]),"ids_preservados":auditoria["ids_unicos"]==len({d["destino_id"] for d in datos["destinos"]}),"fusiones":fusiones}
