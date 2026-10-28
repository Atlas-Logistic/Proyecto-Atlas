"""Caso real 0000366871 (guías 483490/483491): una sola entrega física con
variantes OCR del mismo DESPACHAR A y destino confirmado por B1 en una de
las guías. Datos sintéticos con la misma forma."""

from atlas_core.destino_operacional import TIPO, proyectar_destino
from atlas_core.gestor_viajes import agrupar_viajes

RUTA_CONFIRMADA = {"distancia_km": "8.5231", "duracion_min": "14.44", "proveedor_ruta": "SINTETICO",
                   "estado_ruta": "RUTA_CALCULADA", "comuna": "LAMPA"}


def _fila(guia, **cambios):
    fila = {"archivo": f"{guia}.jpeg", "numero_guia": guia, "numero_transporte": "0000366871",
            "fecha": "28-10-2026", "chofer": "CHOFER EJEMPLO", "rut_chofer": "11.111.111-1",
            "cliente": "CLIENTE EJEMPLO SPA", "rut_cliente": "76.000.000-0",
            "obra_destino": "CLIENTE EJEMPLO SPA", "patente_tracto": "AB1234", "patente_rampla": "CD5678",
            "descripcion_material": f"ROLLO {guia}", "tipo_carga": "ROLLOS", "peso_kg": "1000",
            "hora_entrada_aza": "07:11", "hora_salida_aza": "10:25"}
    fila.update(cambios)
    return fila


def _documental():
    """483490: firma sobre el "22" y residuo de la etiqueta "DESPACHAR A"."""
    return _fila("483490", obra_destino="CLIENTE EJEMPLO SPA", peso_kg="21828",
                 despachar_a_crudo="APANAMERICANA NORTE 650 SANTIAGO LAMPA",
                 direccion_entrega="APANAMERICANA NORTE 650 SANTIAGO LAMPA", localidad_entrega="Lampa",
                 region_entrega="Metropolitana", estado_entrega="RESUELTO", distancia_km="8.5231",
                 duracion_min="14.44", proveedor_ruta="SINTETICO", estado_ruta="RUTA_CALCULADA",
                 codigo_pais="CL", codigo_unidad="13302", codigo_contexto="13")


def _confirmada(direccion="PANAMERICANA NORTE 22650", comuna="LAMPA", ruta=None, **cambios):
    """483491: OCR sin ruta; destino confirmado por B1 y proyectado desde el ledger."""
    fila = _fila("483491", obra_destino="CLIENTF EJEMPLO SPA", peso_kg="6170",
                 despachar_a_crudo="RUTCHOFER PANAMERICANA NORTE 22650 SANTIAGO LAMPA",
                 estado_entrega="REVISAR", estado_ruta="REQUIERE_REVISION",
                 motivo_ruta="MULTIPLES_UBICACIONES_DISPERSAS(2)", **cambios)
    ledger = {"aplicaciones": [{"tipo": TIPO, "documento": {"archivo": fila["archivo"], "numero_guia": "483491"},
                                "destino_operacional": {"direccion": direccion, "comuna": comuna},
                                "ruta_operacional": dict(RUTA_CONFIRMADA if ruta is None else ruta, comuna=comuna)}]}
    proyectada = proyectar_destino(fila, ledger)
    proyectada["_evidencia_documental_original"] = dict(fila)
    return proyectada


def _viaje(*filas):
    viajes, _ = agrupar_viajes(list(filas))
    assert len(viajes) == 1
    return viajes[0]


def test_variantes_ocr_con_destino_confirmado_son_una_sola_entrega():
    documental, confirmada = _documental(), _confirmada()
    viaje = _viaje(documental, confirmada)
    assert len(viaje.entregas) == 1, viaje.entregas
    entrega = viaje.entregas[0]
    assert entrega["numeros_guia"] == ["483490", "483491"]
    assert entrega["destino_operacional"] == "PANAMERICANA NORTE 22650"
    assert entrega["localidad_entrega"] == "LAMPA"
    assert (entrega["distancia_km"], entrega["estado_ruta"]) == ("8.5231", "RUTA_CALCULADA")
    assert (viaje.direccion_entrega, viaje.localidad_entrega) == ("PANAMERICANA NORTE 22650", "LAMPA")
    assert (viaje.distancia_km, viaje.duracion_min) == ("8.5231", "14.44")
    # Pesos, materiales y evidencia documental intactos.
    assert viaje.peso_total_viaje_kg == "27998"
    operacionales = {d["numero_guia"]: d for d in viaje.documentos_operacionales}
    assert operacionales["483490"]["descripcion_material"] == "ROLLO 483490"
    assert operacionales["483491"]["peso_kg"] == "6170"
    evidencias = {e["numero_guia"]: e for e in viaje.a_dict()["evidencias_documentos"]}
    assert evidencias["483490"]["despachar_a_crudo"] == "APANAMERICANA NORTE 650 SANTIAGO LAMPA"
    assert evidencias["483491"]["despachar_a_crudo"] == "RUTCHOFER PANAMERICANA NORTE 22650 SANTIAGO LAMPA"
    assert "PANAMERICANA" not in evidencias["483491"].get("direccion_entrega", "")


def test_ruta_de_la_hermana_documental_nunca_reemplaza_la_confirmada():
    documental = {**_documental(), "distancia_km": "31.9", "duracion_min": "40"}
    viaje = _viaje(documental, _confirmada())
    assert len(viaje.entregas) == 1
    assert viaje.entregas[0]["distancia_km"] == "8.5231"
    assert (viaje.distancia_km, viaje.duracion_min) == ("8.5231", "14.44")


def test_confirmada_sin_ruta_no_hereda_km_de_la_hermana():
    viaje = _viaje(_documental(), _confirmada(ruta={"estado_ruta": "RUTA_CALCULADA", "comuna": "OTRA"}))
    assert len(viaje.entregas) == 1
    assert viaje.entregas[0]["distancia_km"] == viaje.entregas[0]["duracion_min"] == ""
    assert viaje.distancia_km == viaje.duracion_min == ""
    assert viaje.direccion_entrega == "PANAMERICANA NORTE 22650"


def test_destinos_realmente_distintos_siguen_separados():
    variantes = [
        {"direccion_entrega": "APANAMERICANA NORTE 1200 SANTIAGO LAMPA",
         "despachar_a_crudo": "APANAMERICANA NORTE 1200 SANTIAGO LAMPA"},
        {"direccion_entrega": "APANAMERICANA NORTE 50 SANTIAGO LAMPA",
         "despachar_a_crudo": "APANAMERICANA NORTE 50 SANTIAGO LAMPA"},
        {"direccion_entrega": "CAMINO LO ECHEVERS 650 SANTIAGO LAMPA",
         "despachar_a_crudo": "CAMINO LO ECHEVERS 650 SANTIAGO LAMPA"},
        {"direccion_entrega": "PANAMERICANA NORTE 22650 SANTIAGO QUILICURA",
         "despachar_a_crudo": "PANAMERICANA NORTE 22650 SANTIAGO QUILICURA",
         "localidad_entrega": "Quilicura", "codigo_unidad": "13125"},
        {"direccion_entrega": "PANAMERICANA NORTE 22650 LOCAL 4 LAMPA",
         "despachar_a_crudo": "PANAMERICANA NORTE 22650 LOCAL 4 LAMPA"},
        {"rut_cliente": "77.000.000-0"},
        {"obra_destino": "CLIENTE EJEMPLO SPA 2"},
    ]
    for cambios in variantes:
        viaje = _viaje({**_documental(), **cambios}, _confirmada())
        assert len(viaje.entregas) == 2, cambios
        por_guia = {tuple(e["numeros_guia"]): e for e in viaje.entregas}
        assert por_guia[("483491",)]["destino_operacional"] == "PANAMERICANA NORTE 22650"
        assert viaje.distancia_km == viaje.duracion_min == ""


def test_transporte_y_codigo_territorial_solos_no_fusionan():
    documental = {**_documental(), "direccion_entrega": "", "despachar_a_crudo": "",
                  "localidad_entrega": "Lampa"}
    viaje = _viaje(documental, _confirmada())
    assert len(viaje.entregas) == 2


def test_dos_confirmaciones_distintas_prevalecen_sobre_la_inferencia():
    otra = _confirmada()
    segunda = _documental()
    ledger = {"aplicaciones": [{"tipo": TIPO, "documento": {"archivo": "483490.jpeg", "numero_guia": "483490"},
                                "destino_operacional": {"direccion": "PANAMERICANA NORTE 650", "comuna": "LAMPA"},
                                "ruta_operacional": dict(RUTA_CONFIRMADA, distancia_km="20")}]}
    segunda = {**proyectar_destino(segunda, ledger), "_evidencia_documental_original": dict(segunda)}
    viaje = _viaje(segunda, otra)
    assert len(viaje.entregas) == 2
    destinos = {e["destino_operacional"]: e["distancia_km"] for e in viaje.entregas}
    assert destinos == {"PANAMERICANA NORTE 650": "20", "PANAMERICANA NORTE 22650": "8.5231"}


def test_sin_confirmacion_humana_no_se_relaja_la_comparacion():
    documental = _documental()
    otra = _fila("483491", despachar_a_crudo="RUTCHOFER PANAMERICANA NORTE 22650 SANTIAGO LAMPA",
                 direccion_entrega="PANAMERICANA NORTE 22650 SANTIAGO LAMPA", localidad_entrega="Lampa",
                 codigo_pais="CL", codigo_unidad="13302", codigo_contexto="13")
    assert len(_viaje(documental, otra).entregas) == 2


def test_obra_con_digito_distinto_no_es_error_ocr():
    a = _fila("1", obra_destino="EDIFICIO TORRE NORTE 1", direccion_entrega="CALLE EJEMPLO 123",
              localidad_entrega="RENCA")
    b = _fila("2", obra_destino="EDIFICIO TORRE NORTE 2", direccion_entrega="CALLE EJEMPLO 123",
              localidad_entrega="RENCA")
    assert len(_viaje(a, b).entregas) == 2
    c = {**b, "obra_destino": "EDIFICIO TORRE NORTF 1"}
    assert len(_viaje(a, c).entregas) == 1
