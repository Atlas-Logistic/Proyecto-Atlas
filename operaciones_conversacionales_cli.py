import argparse, json
from atlas_core.operaciones_conversacionales import proponer_asociacion_chofer_vehiculo, confirmar_asociacion_chofer_vehiculo
p=argparse.ArgumentParser(); p.add_argument("modo", choices=("proponer","confirmar")); p.add_argument("--raiz-atlas", required=True); p.add_argument("--texto"); p.add_argument("--propuesta"); p.add_argument("--actor", default="JAVIER_DESKTOP"); a=p.parse_args()
r = proponer_asociacion_chofer_vehiculo(raiz_atlas=a.raiz_atlas, texto=a.texto or "", actor=a.actor) if a.modo=="proponer" else confirmar_asociacion_chofer_vehiculo(raiz_atlas=a.raiz_atlas, propuesta=json.loads(a.propuesta), actor=a.actor)
print(json.dumps({"ok": True, **r}, ensure_ascii=True))
