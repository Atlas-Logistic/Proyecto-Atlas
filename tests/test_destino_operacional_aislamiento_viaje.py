from atlas_core.gestor_viajes import agrupar_viajes


def test_destino_confirmado_no_adopta_ruta_de_hermana_con_mismo_codigo_territorial():
    base = {"numero_transporte": "0000352376", "fecha": "2026-10-28", "cliente": "CLIENTE EJEMPLO SA",
            "obra_destino": "OBRA EJEMPLO", "chofer": "JUAN PEREZ", "patente_tracto": "AB1234",
            "codigo_pais": "CL", "codigo_unidad": "88", "codigo_contexto": "123",
            "despachar_a_crudo": "CALLE ANTIGUA 100", "direccion_entrega": "CALLE ANTIGUA 100",
            "localidad_entrega": "RENCA", "distancia_km": "17", "duracion_min": "30",
            "proveedor_ruta": "SINTETICO", "estado_ruta": "RUTA_CALCULADA"}
    primera = {**base, "archivo": "482379.jpg", "numero_guia": "482379"}
    hermana = {**base, "archivo": "483298.jpg", "numero_guia": "483298"}
    # Misma proyecci?n sint?tica del ensayo previo, sin conectar B1.
    proyectada = {**primera, "direccion_entrega": "AVENIDA NUEVA 999",
                  "localidad_entrega": "MAIPU", "distancia_km": "", "duracion_min": "",
                  "proveedor_ruta": "", "estado_ruta": "", "latitud_entrega": "", "longitud_entrega": ""}
    assert proyectada["distancia_km"] == ""
    viajes, _ = agrupar_viajes([proyectada, hermana])
    assert len(viajes) == 1
    entregas = viajes[0].entregas
    assert len(entregas) == 2, f"entregas incorrectamente fusionadas: {entregas!r}"
    assert viajes[0].distancia_km == viajes[0].duracion_min == viajes[0].estado_ruta == ""


    por_guia = {tuple(e["numeros_guia"]): e for e in entregas}
    corregida = por_guia[("482379",)]
    assert corregida["destino_operacional"] == "AVENIDA NUEVA 999"
    assert corregida["distancia_km"] == corregida["duracion_min"] == ""
    assert por_guia[("483298",)]["distancia_km"] == "17"


def test_codigo_territorial_no_oculta_numero_ni_comuna_distintos():
    base = {"numero_transporte": "0000352376", "cliente": "CLIENTE EJEMPLO SA",
            "obra_destino": "OBRA EJEMPLO", "codigo_pais": "CL", "codigo_unidad": "88",
            "codigo_contexto": "123", "direccion_entrega": "CALLE EJEMPLO 123",
            "localidad_entrega": "RENCA"}
    for cambios in ({"direccion_entrega": "CALLE EJEMPLO 124"}, {"localidad_entrega": "MAIPU"}):
        a = {**base, "archivo": "a.jpg", "numero_guia": "482379"}
        b = {**base, **cambios, "archivo": "b.jpg", "numero_guia": "483251"}
        viajes, _ = agrupar_viajes([a, b])
        assert len(viajes[0].entregas) == 2


def test_codigo_territorial_y_direccion_equivalente_conservan_agrupacion():
    base = {"numero_transporte": "0000352376", "cliente": "CLIENTE EJEMPLO SA",
            "obra_destino": "OBRA EJEMPLO", "codigo_pais": "CL", "codigo_unidad": "88",
            "codigo_contexto": "123", "direccion_entrega": "CALLE EJEMPLO 123", "localidad_entrega": "RENCA"}
    a = {**base, "archivo": "a.jpg", "numero_guia": "482379"}
    b = {**base, "archivo": "b.jpg", "numero_guia": "483298"}
    viajes, _ = agrupar_viajes([a, b])
    assert len(viajes[0].entregas) == 1


def test_viaje_mismo_destino_conserva_ruta_compartida():
    base = {"numero_transporte": "0000352376", "cliente": "CLIENTE EJEMPLO SA",
            "obra_destino": "OBRA EJEMPLO", "direccion_entrega": "CALLE EJEMPLO 123",
            "localidad_entrega": "RENCA", "estado_ruta": "RUTA_CALCULADA",
            "distancia_km": "17", "duracion_min": "30", "proveedor_ruta": "SINTETICO"}
    a = {**base, "archivo": "a.jpg", "numero_guia": "482379"}
    b = {**base, "archivo": "b.jpg", "numero_guia": "483298"}
    viajes, _ = agrupar_viajes([a, b])
    assert len(viajes[0].entregas) == 1
    assert viajes[0].distancia_km == "17"
    assert viajes[0].estado_ruta == "RUTA_CALCULADA"


def test_viaje_multidestino_no_consolida_dos_rutas_individuales():
    base = {"numero_transporte": "0000352376", "cliente": "CLIENTE EJEMPLO SA",
            "obra_destino": "OBRA EJEMPLO", "estado_ruta": "RUTA_CALCULADA",
            "distancia_km": "17", "duracion_min": "30", "proveedor_ruta": "SINTETICO"}
    a = {**base, "archivo": "a.jpg", "numero_guia": "482379",
         "direccion_entrega": "CALLE EJEMPLO 123", "localidad_entrega": "RENCA"}
    b = {**base, "archivo": "b.jpg", "numero_guia": "483251",
         "direccion_entrega": "AVENIDA NUEVA 999", "localidad_entrega": "MAIPU"}
    viajes, _ = agrupar_viajes([a, b])
    assert len(viajes[0].entregas) == 2
    assert all(e["distancia_km"] == "17" for e in viajes[0].entregas)
    assert viajes[0].distancia_km == viajes[0].duracion_min == viajes[0].estado_ruta == ""
