import json

from scripts.generar_manifiesto_catalogos import crear_manifiesto
from atlas_core.fuente_catalogos import ARCHIVOS_REQUERIDOS


def _fuente_valida(tmp_path):
    contenidos = {
        "choferes.json": {"1": {"nombre": "CHOFER SINTETICO", "activo": True}},
        "clientes.json": {"clientes": []}, "empresas.json": {},
        "destinos_maestros.json": {"destinos": []}, "vehiculos.json": {},
        "plantas.json": {"plantas": []}, "rutas.json": {"rutas": []},
    }
    for nombre in ARCHIVOS_REQUERIDOS:
        (tmp_path / nombre).write_text(json.dumps(contenidos[nombre]), encoding="utf-8")


def test_manifiesto_es_determinista_y_no_incluye_registros(tmp_path):
    _fuente_valida(tmp_path)
    primero = crear_manifiesto(tmp_path)
    segundo = crear_manifiesto(tmp_path)
    assert primero == segundo
    serializado = json.dumps(primero, sort_keys=True)
    assert "CHOFER SINTETICO" not in serializado
    assert primero["conflictos"]["texto_ocr_promovido"] == 0
