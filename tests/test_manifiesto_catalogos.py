import json

from scripts.generar_manifiesto_catalogos import crear_manifiesto, metricas_choferes
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
    assert primero["esquema"] == "atlas-catalogos-manifiesto-v2"


def test_contrato_separa_alias_canonicos_normalizacion_e_inactivos():
    metricas = metricas_choferes({
        "1": {
            "nombre": "CHOFER SINTÉTICO UNO", "activo": True,
            "aliases": ["CHOFER SINTETICO  UNO", "LECTURA DEMO", "LECTURA DEMO"],
        },
        "2": {"nombre": "CHOFER DOS", "activo": True, "aliases": []},
        "3": {
            "nombre": "CHOFER TRES", "activo": False,
            "aliases": ["ALIAS INACTIVO", "  "],
        },
        "PENDIENTE-1": {"nombre": "CHOFER CUATRO", "activo": True},
    })

    assert metricas["choferes_total"] == 4
    assert metricas["nombres_canonicos"] == 4
    assert metricas["aliases_explicitos_total"] == 4
    assert metricas["aliases_explicitos_unicos_literal"] == 3
    assert metricas["aliases_explicitos_unicos_normalizados"] == 3
    assert metricas["aliases_explicitos_colisiones_normalizadas"] == 1
    assert metricas["aliases_normalizados_que_coinciden_con_canonico_activo"] == 1
    assert metricas["aliases_explicitos_inactivos"] == 1
    assert metricas["aliases_explicitos_vacios"] == 1
    assert metricas["registros_sin_alias_explicitos"] == 2
    assert metricas["variantes_normalizadas_generadas"] == 2
    assert metricas["variantes_fuzzy_activas_total"] == 6
    assert metricas["variantes_fuzzy_activas_unicas_normalizadas"] == 4
    assert metricas["aliases_utilizables_fuzzy_unicos_normalizados"] == 1
    assert metricas["identidades_chofer_pendientes"] == 1


def test_catalogo_vacio_tiene_metricas_cero():
    assert all(valor == 0 for valor in metricas_choferes({}).values())
