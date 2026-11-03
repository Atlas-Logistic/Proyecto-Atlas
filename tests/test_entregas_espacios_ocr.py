"""Caso real 0000368092 (SALOMÓN PIZARRO, guías 483891..483894): 483891,
483892 y 483894 imprimen "CAMINO A MELIPILLA 10800 SANTIAGO MAIPU", pero el
OCR de 483891 omitió un espacio ("CAMINOA MELIPILLA"); 483893 imprime 10338.
Sólo el nombre de la calle tolera espacios insertados/omitidos: número
exacto, comuna compatible y sin contradicción de cliente u obra. Valores
almacenados reales del dataset."""

from atlas_core.destino_operacional import TIPO, proyectar_destino
from atlas_core.entregas import _calles_equivalentes
from atlas_core.gestor_viajes import agrupar_viajes

RUTA_10800 = {"distancia_km": "34.8807", "duracion_min": "48.82333333333334", "proveedor_ruta": "openrouteservice",
              "estado_ruta": "RUTA_CALCULADA"}


def _fila(guia, **cambios):
    fila = {"archivo": f"mobile/{guia}/original.jpg", "numero_guia": guia, "numero_transporte": "0000368092",
            "fecha": "02-11-2026", "chofer": "SALOMÓN PIZARRO", "rut_chofer": "18091588-5",
            "cliente": "AMERICAN SCREW CHILE SPA", "rut_cliente": "91.410.000-3",
            "obra_destino": "AMERICAN SCREW CHILE SPA", "patente_tracto": "TG8925", "patente_rampla": "JF9575",
            "descripcion_material": f"MATERIAL {guia}", "tipo_carga": "BARRAS", "peso_kg": "1000",
            "hora_entrada_aza": "13:43", "hora_salida_aza": "15:19", "estado_entrega": "RESUELTO",
            "proveedor_ruta": "openrouteservice", "estado_ruta": "RUTA_CALCULADA"}
    fila.update(cambios)
    return fila


def _catalogo(guia, peso, direccion="CAMINO A MELIPILLA 10800 SANTIAGO MAIPU", **cambios):
    """483892/483894: resueltas contra el destino maestro, sin código territorial."""
    return _fila(guia, **{"peso_kg": peso, "despachar_a_crudo": direccion, "direccion_entrega": direccion,
                          "localidad_entrega": "MAIPU", "region_entrega": "RM", "distancia_km": "34.8807",
                          "duracion_min": "48.82333333333334", **cambios})


def _483891(**cambios):
    direccion = "CAMINOA MELIPILLA 10800 SANTIAGO MAIPU"
    return _fila("483891", peso_kg="16010", despachar_a_crudo=direccion, direccion_entrega=direccion,
                 localidad_entrega="Maipú", region_entrega="Metropolitana", distancia_km="34.8694",
                 duracion_min="47.61", codigo_pais="CL", codigo_unidad="13119", codigo_contexto="13", **cambios)


def _483893():
    return _fila("483893", peso_kg="1552", despachar_a_crudo="CAMINO A MELIPILLA 10338",
                 direccion_entrega="CAMINO A MELIPILLA 10338, Maipú [INE]", localidad_entrega="Maipú",
                 region_entrega="Metropolitana", estado_entrega="", distancia_km="34.2066",
                 duracion_min="47.876666666666665", codigo_pais="CL", codigo_unidad="13119", codigo_contexto="13")


def _entregas(*filas):
    viajes, _ = agrupar_viajes(list(filas))
    assert len(viajes) == 1
    return viajes[0].entregas


def _guias(entregas):
    return sorted(tuple(e["numeros_guia"]) for e in entregas)


def test_caso_real_dos_entregas_mientras_483893_siga_en_10338():
    entregas = _entregas(_catalogo("483892", "6236"), _483891(), _483893(), _catalogo("483894", "3180"))
    assert _guias(entregas) == [("483891", "483892", "483894"), ("483893",)]
    principal = next(e for e in entregas if "483891" in e["numeros_guia"])
    # La mayoría confiable fija el destino mostrado; el documental de 483891 no se toca.
    assert principal["destino_operacional"] == "CAMINO A MELIPILLA 10800 SANTIAGO MAIPU"
    assert principal["distancia_km"] == "34.8807"


def test_destinos_documentales_almacenados_no_cambian():
    fila = _483891()
    copia = dict(fila)
    _entregas(_catalogo("483892", "6236"), fila)
    assert fila == copia


def test_rectificacion_posterior_de_483893_a_10800_consolida_una_entrega():
    rectificada = _483893()
    ledger = {"aplicaciones": [{"tipo": TIPO, "documento": {"archivo": rectificada["archivo"], "numero_guia": "483893"},
                                "destino_operacional": {"direccion": "CAMINO A MELIPILLA 10800", "comuna": "MAIPU"},
                                "ruta_operacional": dict(RUTA_10800, comuna="MAIPU")}]}
    proyectada = proyectar_destino(rectificada, ledger)
    proyectada["_evidencia_documental_original"] = dict(rectificada)
    entregas = _entregas(_catalogo("483892", "6236"), _483891(), proyectada, _catalogo("483894", "3180"))
    assert _guias(entregas) == [("483891", "483892", "483893", "483894")]


def test_calle_solo_tolera_espacios_insertados_u_omitidos():
    assert _calles_equivalentes("CAMINOA MELIPILLA", "CAMINO A MELIPILLA")
    assert _calles_equivalentes("CAMINO A MELI PILLA", "CAMINO A MELIPILLA")
    assert not _calles_equivalentes("CAMINOA LA ESTRELLA", "CAMINO A MELIPILLA")
    assert not _calles_equivalentes("CAMINO A MELIPILLA", "CAMINO AMELIPILLAS")


def test_numero_distinto_no_se_fusiona_aunque_la_calle_solo_difiera_en_espacios():
    entregas = _entregas(_catalogo("1", "10", "CAMINO A MELIPILLA 10800 SANTIAGO MAIPU"),
                         _catalogo("2", "10", "CAMINOA MELIPILLA 10338 SANTIAGO MAIPU"))
    assert len(entregas) == 2


def test_espacio_dentro_del_numero_no_se_tolera():
    entregas = _entregas(_catalogo("1", "10", "CAMINO A MELIPILLA 10800 SANTIAGO MAIPU"),
                         _catalogo("2", "10", "CAMINOA MELIPILLA 108 00 SANTIAGO MAIPU"))
    assert len(entregas) == 2


def test_comuna_distinta_no_se_fusiona():
    entregas = _entregas(_catalogo("1", "10", "CAMINO A MELIPILLA 10800 SANTIAGO MAIPU"),
                         _catalogo("2", "10", "CAMINOA MELIPILLA 10800 SANTIAGO PUDAHUEL", localidad_entrega="PUDAHUEL"))
    assert len(entregas) == 2


def test_cliente_incompatible_no_se_fusiona():
    entregas = _entregas(_catalogo("1", "10"), _483891(rut_cliente="76.000.000-0", cliente="OTRO CLIENTE SPA"))
    assert len(entregas) == 2


def test_obra_incompatible_no_se_fusiona():
    entregas = _entregas(_catalogo("1", "10"), _483891(obra_destino="OBRA TORRE 2"))
    assert len(entregas) == 2


def test_calle_realmente_distinta_con_mismo_numero_transporte_y_cliente_no_se_fusiona():
    entregas = _entregas(_catalogo("1", "10", "CAMINO A MELIPILLA 10800 SANTIAGO MAIPU"),
                         _catalogo("2", "10", "CAMINOA LA ESTRELLA 10800 SANTIAGO MAIPU"))
    assert len(entregas) == 2
