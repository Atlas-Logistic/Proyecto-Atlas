"""Caso real 0000368939 (05/11/2026, chofer JOSÉ LAZCANO, guías 484139 y
484140, SODIMAC S.A. RENCA BOD 209, Camino Lo Ruiz 3099): una sola entrega
física que Atlas partía en dos porque una guía trae el RUT del cliente y la
otra no (OCR "No encontrado"). Datos con la misma forma que los reales.

También: viajes con varios destinos legítimos siguen separados -- compartir
transporte, cliente o comuna nunca basta para agrupar."""

from atlas_core.destino_operacional import TIPO, proyectar_destino
from atlas_core.gestor_viajes import agrupar_viajes

RUTA_CONFIRMADA = {"distancia_km": "15.9161", "duracion_min": "14.431666666666667",
                   "proveedor_ruta": "openrouteservice", "estado_ruta": "RUTA_CALCULADA"}


def _fila(guia, **cambios):
    fila = {"archivo": f"{guia}.jpeg", "numero_guia": guia, "numero_transporte": "0000368939",
            "fecha": "05-11-2026", "chofer": "JOSE LAZCANO", "rut_chofer": "10833150-K",
            "cliente": "SODIMAC SA", "rut_cliente": "96.792.430-K", "obra_destino": "SODIMAC SA RENCA BOD 209",
            "cod_destinatario": "0002001254", "patente_tracto": "ND6443", "patente_rampla": "JB6878",
            "planta_origen_nombre": "AZA COLINA", "hora_entrada_aza": "10:09", "hora_salida_aza": "11:41"}
    fila.update(cambios)
    return fila


def _484139(**cambios):
    """Guía con RUT de cliente, dirección resuelta y ruta calculada."""
    return _fila("484139", **{**dict(
        peso_kg="16017", descripcion_material="B HORMIGON 10MM 12M A630-420H (N)", tipo_carga="BARRAS",
        despachar_a_crudo="CAMINO LO RUIZ 3099 SANTIAGO RENCA", direccion_entrega="CAMINO LO RUIZ 3099 SANTIAGO RENCA",
        localidad_entrega="Renca", region_entrega="Metropolitana", estado_entrega="RESUELTO", codigo_pais="CL",
        codigo_unidad="13128", codigo_contexto="13", **RUTA_CONFIRMADA), **cambios})


def _484140_documental(**cambios):
    """Guía Mobile: RUT de cliente no leído, "RU1" por "RUIZ", sin ruta."""
    return _fila("484140", **{**dict(
        archivo="mobile/f30cfc02/original.jpg", rut_cliente="No encontrado", peso_kg="9081",
        descripcion_material="", tipo_carga="NO DETERMINADO", despachar_a_crudo="CAMINO LO RU1 3099 SANTIAGO RENCA",
        estado_entrega="NO_INTENTADO", estado_ruta="REQUIERE_REVISION",
        motivo_ruta="DESTINO_CONTRADICE_CATALOGO_CONFIRMADO"), **cambios})


def _484140_confirmada(**cambios):
    """Destino confirmado por un humano (B1) y proyectado desde el ledger."""
    fila = _484140_documental(**cambios)
    ledger = {"aplicaciones": [{
        "tipo": TIPO, "documento": {"archivo": fila["archivo"], "numero_guia": "484140"},
        "destino_operacional": {"direccion": "CAMINO LO RUIZ 3099", "comuna": "RENCA"},
        "ruta_operacional": dict(RUTA_CONFIRMADA, comuna="RENCA")}]}
    proyectada = proyectar_destino(fila, ledger)
    assert proyectada != fila
    proyectada["_evidencia_documental_original"] = dict(fila)
    return proyectada


def _viaje(*filas):
    viajes, sin_transporte = agrupar_viajes(list(filas))
    assert len(viajes) == 1 and not sin_transporte
    return viajes[0]


# --- Caso real -------------------------------------------------------------------

def test_caso_real_destino_confirmado_y_hermana_con_rut_son_una_entrega():
    viaje = _viaje(_484140_confirmada(), _484139())
    assert len(viaje.entregas) == 1, viaje.entregas
    entrega = viaje.entregas[0]
    assert entrega["numeros_guia"] == ["484139", "484140"]
    assert entrega["clientes"] == ["SODIMAC SA"]
    assert entrega["obras_destino"] == ["SODIMAC SA RENCA BOD 209"]
    # Destino y ruta: los que confirmó el humano, sin recalcular nada.
    assert entrega["destino_operacional"] == "CAMINO LO RUIZ 3099"
    assert entrega["localidad_entrega"] == "RENCA"
    assert (entrega["distancia_km"], entrega["estado_ruta"]) == ("15.9161", "RUTA_CALCULADA")
    assert (viaje.direccion_entrega, viaje.localidad_entrega) == ("CAMINO LO RUIZ 3099", "RENCA")
    assert viaje.distancia_km == "15.9161"
    # Guías, pesos, materiales, transporte y evidencia documental intactos.
    assert viaje.numero_transporte == "0000368939"
    assert viaje.peso_total_viaje_kg == "25098"
    operacionales = {d["numero_guia"]: d for d in viaje.documentos_operacionales}
    assert operacionales["484139"]["peso_kg"] == "16017"
    assert operacionales["484140"]["peso_kg"] == "9081"
    assert operacionales["484139"]["descripcion_material"] == "B HORMIGON 10MM 12M A630-420H (N)"
    evidencias = {e["numero_guia"]: e for e in viaje.a_dict()["evidencias_documentos"]}
    assert evidencias["484140"]["despachar_a_crudo"] == "CAMINO LO RU1 3099 SANTIAGO RENCA"
    assert evidencias["484140"]["rut_cliente"] == "No encontrado"
    assert evidencias["484140"].get("direccion_entrega", "") == ""
    assert evidencias["484139"]["rut_cliente"] == "96.792.430-K"


def test_orden_de_las_guias_no_cambia_el_resultado():
    a = _viaje(_484140_confirmada(), _484139()).entregas
    b = _viaje(_484139(), _484140_confirmada()).entregas
    assert a == b and len(a) == 1


def test_sin_confirmacion_rut_ausente_en_una_guia_no_divide_la_entrega():
    sin_rut = _484140_documental(despachar_a_crudo="CAMINO LO RUIZ 3099 SANTIAGO RENCA",
                                 direccion_entrega="CAMINO LO RUIZ 3099 SANTIAGO RENCA",
                                 localidad_entrega="Renca", **RUTA_CONFIRMADA, motivo_ruta="")
    viaje = _viaje(sin_rut, _484139())
    assert len(viaje.entregas) == 1
    assert viaje.entregas[0]["numeros_guia"] == ["484139", "484140"]


# --- Destinos legítimamente distintos siguen separados ------------------------------

def test_mismo_transporte_cliente_y_comuna_con_otra_direccion_son_dos_entregas():
    otra = _fila("484141", despachar_a_crudo="CAMINO LO BOZA 120 SANTIAGO RENCA",
                 direccion_entrega="CAMINO LO BOZA 120 SANTIAGO RENCA", localidad_entrega="Renca",
                 codigo_pais="CL", codigo_unidad="13128", codigo_contexto="13", peso_kg="5000")
    viaje = _viaje(_484139(), otra)
    assert sorted(e["numeros_guia"][0] for e in viaje.entregas) == ["484139", "484141"]


def test_mismo_numero_de_calle_en_otra_comuna_son_dos_entregas():
    otra = _fila("484142", rut_cliente="No encontrado",
                 despachar_a_crudo="CAMINO LO RUIZ 3099 SANTIAGO QUILICURA",
                 direccion_entrega="CAMINO LO RUIZ 3099 SANTIAGO QUILICURA", localidad_entrega="Quilicura")
    assert len(_viaje(_484139(), otra).entregas) == 2


def test_rut_de_cliente_distinto_con_mismo_nombre_son_dos_entregas():
    otra = _484139(archivo="484143.jpeg", numero_guia="484143", rut_cliente="77.111.222-3")
    assert len(_viaje(_484139(), otra).entregas) == 2


def test_rut_ausente_y_otro_cliente_en_el_mismo_destino_son_dos_entregas():
    otra = _484139(archivo="484144.jpeg", numero_guia="484144", rut_cliente="No encontrado",
                   cliente="CONSTRUCTORA EJEMPLO SPA", obra_destino="CONSTRUCTORA EJEMPLO SPA")
    assert len(_viaje(_484139(), otra).entregas) == 2


def test_confirmada_no_reune_hermana_de_otro_cliente_ni_sin_cliente_comparable():
    otro_cliente = _484139(rut_cliente="No encontrado", cliente="CONSTRUCTORA EJEMPLO SPA",
                           obra_destino="SODIMAC SA RENCA BOD 209")
    assert len(_viaje(_484140_confirmada(), otro_cliente).entregas) == 2
    # Sin RUT ni nombre en la hermana no hay evidencia positiva: no se reúne.
    sin_cliente = _484139(rut_cliente="No encontrado", cliente="No encontrado")
    assert len(_viaje(_484140_confirmada(cliente="No encontrado"), sin_cliente).entregas) == 2


def test_confirmada_no_reune_hermana_con_otro_numero_de_calle():
    otra = _484139(despachar_a_crudo="CAMINO LO RUIZ 2901 SANTIAGO RENCA",
                   direccion_entrega="CAMINO LO RUIZ 2901 SANTIAGO RENCA")
    assert len(_viaje(_484140_confirmada(), otra).entregas) == 2
