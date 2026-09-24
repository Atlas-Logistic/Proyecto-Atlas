"""Bloque O3 -- defensa de plausibilidad del PESO TOTAL DEL VIAJE.

Caso real que lo motiva: viaje 0000359510 (chofer SALOMÓN PIZARRO, guías
474285/474286/474287) mostraba peso_total_viaje_kg=47.779 (dos documentos
con +10.000 kg espurios por un dígito OCR de baja confianza, ver Bloque O2
en atlas_core.extractor). Esta defensa NUNCA corrige el peso -- sólo
señala la contradicción para revisión humana cuando persiste después de
que Bloque O2 ya tuvo su oportunidad de resolverla con evidencia.
"""

from atlas_core.gestor_viajes import EstadoViaje, MotivoRevision, agrupar_viajes


def _fila(**cambios):
    fila = {
        "archivo": f"{cambios.get('numero_guia', '000101')}.jpg",
        "numero_guia": "000101",
        "numero_transporte": "0000359510",
        "fecha": "21-09-2026",
        "chofer": "SALOMÓN PIZARRO",
        "rut_chofer": "18.091.588-5",
        "cliente": "ARMACERO MATCO SA",
        "obra_destino": "ARMACERO MATCO SA",
        "patente_tracto": "TG8925",
        "patente_rampla": "JF9575",
        "descripcion_material": "BARRAS",
        "tipo_carga": "BARRAS",
        "peso_kg": "9000",
        "hora_entrada_aza": "13:54",
        "hora_salida_aza": "16:35",
        "despachar_a_crudo": "SANTA ISABEL 585 SANTIAGO LAMPA",
        "direccion_entrega": "SANTA ISABEL 585 SANTIAGO LAMPA",
        "localidad_entrega": "Lampa",
        "region_entrega": "Región Metropolitana",
        "estado_entrega": "RESUELTO",
        "distancia_km": "6.5",
        "duracion_min": "10.8",
        "proveedor_ruta": "openrouteservice",
        "estado_ruta": "RUTA_CALCULADA",
        "motivo_ruta": "",
    }
    fila.update(cambios)
    fila.setdefault("archivo", f"{fila['numero_guia']}.jpg")
    return fila


def test_peso_total_viaje_implausible_fuerza_revision():
    # Caso real reproducido con los pesos ERRÓNEOS documentados por
    # Javier (19.307 + 9.535 + 18.937 = 47.779 kg, > 30 t).
    filas = [
        _fila(numero_guia="474285", peso_kg="19307"),
        _fila(numero_guia="474286", peso_kg="9535"),
        _fila(numero_guia="474287", peso_kg="18937"),
    ]
    viajes, _ = agrupar_viajes(filas)
    assert len(viajes) == 1
    assert viajes[0].peso_total_viaje_kg == "47779"
    assert MotivoRevision.PESO_TOTAL_VIAJE_IMPLAUSIBLE in viajes[0].motivos_revision
    assert viajes[0].estado == EstadoViaje.REQUIERE_REVISION


def test_peso_total_viaje_correcto_no_dispara_nada():
    # Mismo viaje con los pesos CORRECTOS (9.307 + 9.535 + 8.937 =
    # 27.779 kg, dentro del rango operacional real 27-30 t) -- no debe
    # generar ningún motivo de revisión ni pendiente técnico artificial.
    filas = [
        _fila(numero_guia="474285", peso_kg="9307"),
        _fila(numero_guia="474286", peso_kg="9535"),
        _fila(numero_guia="474287", peso_kg="8937"),
    ]
    viajes, _ = agrupar_viajes(filas)
    assert len(viajes) == 1
    assert viajes[0].peso_total_viaje_kg == "27779"
    assert MotivoRevision.PESO_TOTAL_VIAJE_IMPLAUSIBLE not in viajes[0].motivos_revision
    assert viajes[0].estado == EstadoViaje.CONFIRMADO


def test_peso_justo_en_el_techo_operacional_no_dispara():
    # 30.000 kg exactos: no debe generar falso positivo sobre el techo
    # mismo del rango que confirmó Javier (27-30 t).
    filas = [
        _fila(numero_guia="1", peso_kg="15000"),
        _fila(numero_guia="2", peso_kg="15000"),
    ]
    viajes, _ = agrupar_viajes(filas)
    assert MotivoRevision.PESO_TOTAL_VIAJE_IMPLAUSIBLE not in viajes[0].motivos_revision


def test_un_kg_sobre_el_techo_si_dispara():
    filas = [
        _fila(numero_guia="1", peso_kg="15000"),
        _fila(numero_guia="2", peso_kg="15001"),
    ]
    viajes, _ = agrupar_viajes(filas)
    assert MotivoRevision.PESO_TOTAL_VIAJE_IMPLAUSIBLE in viajes[0].motivos_revision


def test_suma_parcial_sin_peso_en_todos_los_documentos_nunca_se_evalua():
    # Un documento sin peso válido no permite demostrar que la suma esté
    # completa -- igual criterio que `Viaje.peso_total_viaje_kg` (queda
    # vacío); esta defensa tampoco debe opinar sobre una suma parcial.
    filas = [
        _fila(numero_guia="1", peso_kg="25000"),
        _fila(numero_guia="2", peso_kg="No encontrado"),
    ]
    viajes, _ = agrupar_viajes(filas)
    assert viajes[0].peso_total_viaje_kg == ""
    assert MotivoRevision.PESO_TOTAL_VIAJE_IMPLAUSIBLE not in viajes[0].motivos_revision


def test_no_regresion_viaje_normal_de_una_sola_guia():
    filas = [_fila(numero_guia="1", peso_kg="9500")]
    viajes, _ = agrupar_viajes(filas)
    assert viajes[0].estado == EstadoViaje.CONFIRMADO
    assert MotivoRevision.PESO_TOTAL_VIAJE_IMPLAUSIBLE not in viajes[0].motivos_revision
