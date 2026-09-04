"""Bloque ENTREGAS E1: DESPACHAR A como fuente autoritativa de la ruta.

Regla de negocio (Javier, prevalece sobre D2/D3/D3.1): la ruta debe ser
PLANTA ORIGEN -> DESPACHAR A, nunca PLANTA ORIGEN -> dirección del
cliente/sitio registrado. Ante ambigüedad de geocodificación, abstención
(REVISAR) -- nunca se elige el candidato más cercano a una planta AZA.
"""
from datetime import datetime, timezone

import pytest

from atlas_core.catalogo_plantas import CatalogoPlantas, EstadoCalidad
from atlas_core.rutas.destino_entrega import (
    ESTADO_REVISAR,
    ESTADO_RESUELTO,
    ESTADO_SIN_DATO,
    _comuna_documental_inequivoca,
    _comunas_explicitas,
    calcular_ruta_entrega_para_viaje,
    resolver_comuna_territorial_conocida,
    resolver_destino_entrega,
)
from atlas_core.rutas.modelos import (
    CandidatoGeocodificacion,
    Coordenadas,
    EstadoRuta,
    ResultadoGeocodificacion,
    ResultadoRuta,
)
from atlas_core.rutas.proveedor import ProveedorRutasSimulado

COORD_AZA_RENCA = Coordenadas(-70.685226, -33.401595)
COORD_MEJILLONES = Coordenadas(-70.4500, -23.0985)  # real, Región de Antofagasta

TEXTOS_ENCABEZADO_RENCA = "GUIA DESPACHO PLANTA ORIGEN RENCA ACEROS AZA S A CASA MATRIZ PLANTA RENCA LA UNION 3070 RENCA SANTIAGO CHILE"


@pytest.fixture
def planta_renca(tmp_path):
    plantas_repo = CatalogoPlantas(tmp_path / "plantas.json")
    planta = plantas_repo.crear(
        nombre="AZA RENCA", pais="CHILE", fuente="PRUEBA",
        direccion="LA UNION 3070", comuna="RENCA", region="RM",
        latitud=COORD_AZA_RENCA.latitud, longitud=COORD_AZA_RENCA.longitud,
        estado_calidad=EstadoCalidad.CONFIRMADA,
    )
    return plantas_repo.listar(), planta


# --- resolver_destino_entrega: niveles básicos ---

def test_sin_despachar_a_es_sin_dato():
    proveedor = ProveedorRutasSimulado()
    resultado = resolver_destino_entrega("", proveedor)
    assert resultado.estado == ESTADO_SIN_DATO
    assert proveedor.llamadas_geocodificacion == 0


def test_candidato_unico_con_confianza_suficiente_resuelve():
    consulta = "AV. ALMTE. LATORRE 843, MEJILLONES, Chile"
    proveedor = ProveedorRutasSimulado(geocodificaciones={
        consulta: ResultadoGeocodificacion(
            EstadoRuta.REQUIERE_REVISION,
            (CandidatoGeocodificacion(COORD_MEJILLONES, "Av. Almte. Latorre 843, Mejillones", 0.8),),
            "REQUIERE_CONFIRMACION_HUMANA",
        )
    })
    resultado = resolver_destino_entrega("AV. ALMTE. LATORRE 843, MEJILLONES", proveedor)
    assert resultado.estado == ESTADO_RESUELTO
    assert resultado.coordenadas == COORD_MEJILLONES
    assert resultado.confianza == 0.8
    assert resultado.despachar_a_crudo == "AV. ALMTE. LATORRE 843, MEJILLONES"


def test_candidato_unico_con_confianza_insuficiente_revisa():
    consulta = "CALLE AMBIGUA 100, Chile"
    proveedor = ProveedorRutasSimulado(geocodificaciones={
        consulta: ResultadoGeocodificacion(
            EstadoRuta.REQUIERE_REVISION,
            (CandidatoGeocodificacion(Coordenadas(-70.0, -33.0), "Calle Ambigua 100", 0.2),),
            "REQUIERE_CONFIRMACION_HUMANA",
        )
    })
    resultado = resolver_destino_entrega("CALLE AMBIGUA 100", proveedor)
    assert resultado.estado == ESTADO_REVISAR
    assert resultado.motivo == "CONFIANZA_INSUFICIENTE"


# --- Bloque REGISTRO_DIRECCION CONTEXTO (caso real 472640) ---


def test_comuna_territorial_conocida_eleva_un_candidato_de_baja_confianza():
    """Sin comuna, el mismo candidato real (472640: "LAS VIOLETAS 55")
    queda con confianza insuficiente -- exactamente el bug real. Con una
    comuna YA confiable de otra fuente (nunca del propio texto, que sigue
    sin mencionarla), la consulta se amplía y el mismo proveedor la
    resuelve."""
    direccion = "LAS VIOLETAS 55"
    proveedor = ProveedorRutasSimulado(geocodificaciones={
        f"{direccion} Padre Hurtado, Chile": ResultadoGeocodificacion(
            EstadoRuta.REQUIERE_REVISION,
            (CandidatoGeocodificacion(
                Coordenadas(-70.76, -33.58), direccion + ", Padre Hurtado, RM, Chile", 0.9,
                "Padre Hurtado", "Metropolitana",
            ),),
            "",
        ),
    })
    sin_comuna = resolver_destino_entrega(direccion, proveedor)
    assert sin_comuna.estado == ESTADO_REVISAR
    assert sin_comuna.motivo == "CONFIANZA_INSUFICIENTE"

    con_comuna = resolver_destino_entrega(
        direccion, proveedor, comuna_territorial_conocida="Padre Hurtado",
    )
    assert con_comuna.estado == ESTADO_RESUELTO
    assert con_comuna.localidad == "Padre Hurtado"
    # El texto documental persistido (`despachar_a_crudo`) sigue siendo
    # EXACTAMENTE lo que el humano escribió -- la comuna sólo amplió la
    # consulta al geocodificador, nunca se incrusta en el resultado.
    assert con_comuna.despachar_a_crudo == direccion


def test_comuna_territorial_conocida_nunca_contradice_comuna_documental_propia():
    """Si `despachar_a_crudo` YA menciona una comuna propia inequívoca,
    `comuna_territorial_conocida` nunca la sobrescribe ni se agrega --
    sólo completa evidencia AUSENTE, jamás contradice evidencia ya
    presente en el documento."""
    direccion = "AV SIEMPREVIVA 123 QUILICURA"
    consulta_original = f"{direccion}, Chile"
    proveedor = ProveedorRutasSimulado(geocodificaciones={
        consulta_original: ResultadoGeocodificacion(
            EstadoRuta.REQUIERE_REVISION,
            (CandidatoGeocodificacion(
                Coordenadas(-70.73, -33.36), direccion + ", Quilicura, RM, Chile", 0.9,
                "Quilicura", "Metropolitana",
            ),),
            "",
        ),
    })
    resultado = resolver_destino_entrega(
        direccion, proveedor, comuna_territorial_conocida="Padre Hurtado",
    )
    assert resultado.estado == ESTADO_RESUELTO
    assert resultado.localidad == "Quilicura"
    assert proveedor.llamadas_geocodificacion == 1


def test_resolver_comuna_territorial_conocida_usa_destino_confirmado_de_la_obra(tmp_path):
    """Escribe los 3 catálogos directamente en su forma persistida (mismo
    esquema que `Destino`/`Obra`/`RelacionObraDestino.a_dict()`) -- evita
    acoplar esta prueba a la API interna de escritura de cada catálogo,
    que ya tiene su propia cobertura dedicada. Cubre lo mismo que el
    escenario real (ver `test_registro_direccion_contexto_territorial.
    test_comuna_de_destino_confirmado_previo_se_reutiliza_sin_preguntar`,
    a través del flujo real de `aplicar_decision_obra`), aislado a sólo
    `resolver_comuna_territorial_conocida`."""
    import json as json_mod

    fecha = "2026-01-01T00:00:00+00:00"
    (tmp_path / "clientes.json").write_text(
        json_mod.dumps({"version_formato": 1, "clientes": []}), encoding="utf-8",
    )
    (tmp_path / "destinos_maestros.json").write_text(json_mod.dumps({
        "version_formato": 1,
        "destinos": [{
            "destino_id": "destino-1", "cliente_id": "", "nombre_destino": "CAMINO LA ESTRELLA 100",
            "nombre_normalizado": "CAMINO LA ESTRELLA 100", "codigo_destino": "",
            "direccion": "CAMINO LA ESTRELLA 100", "comuna": "Padre Hurtado", "region": "Metropolitana",
            "pais": "CHILE", "latitud": -33.58, "longitud": -70.76, "aliases": [],
            "estado_calidad": "CONFIRMADO", "estado_vigencia": "ACTIVO", "fuente": "TEST",
            "observacion": "", "fecha_creacion": fecha, "fecha_modificacion": fecha,
        }],
    }), encoding="utf-8")
    (tmp_path / "obras_destinos.json").write_text(json_mod.dumps({
        "version_formato": 1,
        "obras": [{
            "obra_id": "obra-1", "cliente_id": "", "nombre_canonico": "DSI UNDERGROUND CHILE SPA",
            "nombre_normalizado": "DSI UNDERGROUND CHILE SPA", "aliases_documentales": [],
            "estado": "CONFIRMADA", "estado_vigencia": "ACTIVO",
            "evidencias": [{
                "tipo": "CONFIRMACION_HUMANA", "identificador_fuente": "472037", "referencia_hash": "x",
                "campos_observados": {}, "fecha": fecha, "actor_proceso": "TEST", "resultado": "SOPORTA",
            }],
            "fecha_creacion": fecha, "fecha_modificacion": fecha,
        }],
        "relaciones": [{
            "relacion_id": "relacion-1", "obra_id": "obra-1", "destino_id": "destino-1",
            "estado": "CONFIRMADA",
            "evidencias": [{
                "tipo": "CONFIRMACION_HUMANA", "identificador_fuente": "472037", "referencia_hash": "x",
                "campos_observados": {}, "fecha": fecha, "actor_proceso": "TEST", "resultado": "SOPORTA",
            }],
            "fuente_confirmacion": "TEST",
            "confirmado_por": "TEST", "fecha_confirmacion": fecha, "observaciones": "",
            "fecha_creacion": fecha, "fecha_modificacion": fecha,
        }],
    }), encoding="utf-8")

    comuna = resolver_comuna_territorial_conocida(
        obra_canonica="DSI UNDERGROUND CHILE SPA",
        catalogo_obras_ruta=tmp_path / "obras_destinos.json",
        catalogo_clientes_ruta=tmp_path / "clientes.json",
        catalogo_destinos_ruta=tmp_path / "destinos_maestros.json",
    )
    assert comuna == "Padre Hurtado"


def test_resolver_comuna_territorial_conocida_usa_nombre_de_obra_sin_destino_previo(tmp_path):
    for nombre, contenido in {
        "clientes.json": {"version_formato": 1, "clientes": []},
        "obras_destinos.json": {"version_formato": 1, "obras": [], "relaciones": []},
        "destinos_maestros.json": {"version_formato": 1, "destinos": []},
    }.items():
        (tmp_path / nombre).write_text(__import__("json").dumps(contenido), encoding="utf-8")
    comuna = resolver_comuna_territorial_conocida(
        obra_canonica="CONSTRUCTORA EJEMPLO PADRE HURTADO",
        catalogo_obras_ruta=tmp_path / "obras_destinos.json",
        catalogo_clientes_ruta=tmp_path / "clientes.json",
        catalogo_destinos_ruta=tmp_path / "destinos_maestros.json",
    )
    assert comuna == "Padre Hurtado"


def test_resolver_comuna_territorial_conocida_vacia_sin_ninguna_fuente_confiable(tmp_path):
    for nombre, contenido in {
        "clientes.json": {"version_formato": 1, "clientes": []},
        "obras_destinos.json": {"version_formato": 1, "obras": [], "relaciones": []},
        "destinos_maestros.json": {"version_formato": 1, "destinos": []},
    }.items():
        (tmp_path / nombre).write_text(__import__("json").dumps(contenido), encoding="utf-8")
    comuna = resolver_comuna_territorial_conocida(
        obra_canonica="DSI UNDERGROUND CHILE SPA",
        catalogo_obras_ruta=tmp_path / "obras_destinos.json",
        catalogo_clientes_ruta=tmp_path / "clientes.json",
        catalogo_destinos_ruta=tmp_path / "destinos_maestros.json",
    )
    assert comuna == ""


def test_multiples_candidatos_nunca_elige_el_mas_cercano_a_aza():
    # Un candidato está a metros de AZA Renca, el otro a cientos de km --
    # el resolver NUNCA debe preferir el cercano; debe abstenerse.
    consulta = "SANTA ISABEL 585, Chile"
    cercano_a_aza = CandidatoGeocodificacion(
        Coordenadas(-70.686, -33.402), "Santa Isabel 585, Renca", 0.9
    )
    lejano = CandidatoGeocodificacion(
        Coordenadas(-72.59, -38.74), "Santa Isabel 585, Temuco", 0.85
    )
    proveedor = ProveedorRutasSimulado(geocodificaciones={
        consulta: ResultadoGeocodificacion(
            EstadoRuta.RESULTADO_AMBIGUO, (cercano_a_aza, lejano), "MULTIPLES_CANDIDATOS"
        )
    })
    resultado = resolver_destino_entrega("SANTA ISABEL 585", proveedor)
    assert resultado.estado == ESTADO_REVISAR
    assert resultado.coordenadas is None  # no elige ninguno de los dos
    assert "MULTIPLES_UBICACIONES_DISPERSAS" in resultado.motivo


def test_candidatos_dispersos_pero_cercanos_no_son_ambiguedad_real():
    # Caso real (Bloque E1): "AV. ALMTE. LATORRE 843, MEJILLONES" devolvió
    # 5 candidatos, todos confianza 1.0, todos en la misma cuadra de la
    # misma calle en Mejillones (Pelias no calzó el número exacto) --
    # eso NO es la ambigüedad de calles homónimas que hay que evitar.
    consulta = "AV. ALMTE. LATORRE 843 MEJILLONES, Chile"
    candidatos = (
        CandidatoGeocodificacion(Coordenadas(-70.445403, -23.100131), "898 Av. Latorre, Mejillones", 1.0),
        CandidatoGeocodificacion(Coordenadas(-70.447422, -23.100201), "792 Av. Latorre, Mejillones", 1.0),
        CandidatoGeocodificacion(Coordenadas(-70.446343, -23.100161), "866 Av. Latorre, Mejillones", 1.0),
        CandidatoGeocodificacion(Coordenadas(-70.448719, -23.100073), "637 Av. Latorre, Mejillones", 1.0),
        CandidatoGeocodificacion(Coordenadas(-70.448993, -23.100072), "611 Av. Latorre, Mejillones", 1.0),
    )
    proveedor = ProveedorRutasSimulado(geocodificaciones={
        consulta: ResultadoGeocodificacion(EstadoRuta.RESULTADO_AMBIGUO, candidatos, "MULTIPLES_CANDIDATOS")
    })
    resultado = resolver_destino_entrega("AV. ALMTE. LATORRE 843 MEJILLONES", proveedor)
    assert resultado.estado == ESTADO_RESUELTO
    assert resultado.coordenadas == candidatos[0].coordenadas
    assert resultado.confianza == 1.0


def test_fallo_de_geocodificacion_preserva_texto_crudo_y_explica():
    proveedor = ProveedorRutasSimulado(geocodificaciones={
        "DIRECCION INEXISTENTE, Chile": ResultadoGeocodificacion(
            EstadoRuta.DIRECCION_NO_ENCONTRADA, motivo="SIN_CANDIDATOS"
        )
    })
    resultado = resolver_destino_entrega("DIRECCION INEXISTENTE", proveedor)
    assert resultado.estado == ESTADO_REVISAR
    assert resultado.despachar_a_crudo == "DIRECCION INEXISTENTE"
    assert "DIRECCION_NO_ENCONTRADA" in resultado.motivo


# --- calcular_ruta_entrega_para_viaje: orquestación end-to-end ---

def test_calcula_ruta_real_planta_a_despachar_a(planta_renca):
    plantas, _ = planta_renca
    consulta = "AV. ALMTE. LATORRE 843, MEJILLONES, Chile"
    proveedor = ProveedorRutasSimulado(
        geocodificaciones={
            consulta: ResultadoGeocodificacion(
                EstadoRuta.REQUIERE_REVISION,
                (CandidatoGeocodificacion(COORD_MEJILLONES, "Av. Almte. Latorre 843, Mejillones", 0.8),),
                "REQUIERE_CONFIRMACION_HUMANA",
            )
        },
        resultado_ruta=ResultadoRuta(EstadoRuta.RUTA_CALCULADA, 1387.4, 960.2, "SINTETICO"),
    )
    resultado = calcular_ruta_entrega_para_viaje(
        despachar_a_crudo="AV. ALMTE. LATORRE 843, MEJILLONES",
        patente=None, instante_salida=None, plantas=plantas,
        proveedor_posicion=None, proveedor_rutas=proveedor,
        textos_documento=[TEXTOS_ENCABEZADO_RENCA],
    )
    assert resultado.estado_ruta == EstadoRuta.RUTA_CALCULADA.value
    assert resultado.planta_origen_nombre == "AZA RENCA"
    assert resultado.despachar_a_crudo == "AV. ALMTE. LATORRE 843, MEJILLONES"
    assert resultado.distancia_km == "1387.4"
    assert proveedor.llamadas_ruta == 1


def test_origen_no_determinado_nunca_geocodifica(planta_renca):
    plantas, _ = planta_renca
    proveedor = ProveedorRutasSimulado()
    resultado = calcular_ruta_entrega_para_viaje(
        despachar_a_crudo="AV. ALMTE. LATORRE 843, MEJILLONES",
        patente=None, instante_salida=None, plantas=plantas,
        proveedor_posicion=None, proveedor_rutas=proveedor,
        textos_documento=["GUIA SIN ENCABEZADO RECONOCIBLE"],
    )
    assert resultado.estado_ruta == EstadoRuta.ORIGEN_NO_DETERMINADO.value
    assert proveedor.llamadas_geocodificacion == 0
    assert proveedor.llamadas_ruta == 0


def test_entrega_ambigua_nunca_calcula_ruta(planta_renca):
    plantas, _ = planta_renca
    consulta = "SANTA ISABEL 585, Chile"
    proveedor = ProveedorRutasSimulado(geocodificaciones={
        consulta: ResultadoGeocodificacion(
            EstadoRuta.RESULTADO_AMBIGUO,
            (
                CandidatoGeocodificacion(Coordenadas(-70.686, -33.402), "Santa Isabel 585, Renca", 0.9),
                CandidatoGeocodificacion(Coordenadas(-72.59, -38.74), "Santa Isabel 585, Temuco", 0.85),
            ),
            "MULTIPLES_CANDIDATOS",
        )
    })
    resultado = calcular_ruta_entrega_para_viaje(
        despachar_a_crudo="SANTA ISABEL 585",
        patente=None, instante_salida=None, plantas=plantas,
        proveedor_posicion=None, proveedor_rutas=proveedor,
        textos_documento=[TEXTOS_ENCABEZADO_RENCA],
    )
    assert resultado.estado_ruta == EstadoRuta.REQUIERE_REVISION.value
    assert "MULTIPLES_UBICACIONES_DISPERSAS" in resultado.motivo_ruta
    assert proveedor.llamadas_ruta == 0


def test_destino_rechazado_por_confianza_no_expone_etiqueta_ni_localidad(planta_renca):
    """Bloque F (R4.10), caso real 472008: un candidato a confianza
    insuficiente (0.1, "Chile" sin localidad/región) no debe exponer su
    etiqueta como si fuera el destino operacional resuelto -- coordenadas/
    confianza sí se conservan (evidencia técnica), pero
    direccion_entrega_geocodificada/localidad/región quedan vacías."""
    plantas, _ = planta_renca
    consulta = "DIRECCION ILEGIBLE 999, Chile"
    proveedor = ProveedorRutasSimulado(geocodificaciones={
        consulta: ResultadoGeocodificacion(
            EstadoRuta.REQUIERE_REVISION,
            (CandidatoGeocodificacion(Coordenadas(-72.27, -38.17), "Chile", 0.1, localidad="", region=""),),
            "REQUIERE_CONFIRMACION_HUMANA",
        )
    })
    resultado = calcular_ruta_entrega_para_viaje(
        despachar_a_crudo="DIRECCION ILEGIBLE 999",
        patente=None, instante_salida=None, plantas=plantas,
        proveedor_posicion=None, proveedor_rutas=proveedor,
        textos_documento=[TEXTOS_ENCABEZADO_RENCA],
    )
    assert resultado.estado_ruta == EstadoRuta.REQUIERE_REVISION.value
    assert resultado.motivo_ruta == "CONFIANZA_INSUFICIENTE"
    assert resultado.direccion_entrega_geocodificada == ""
    assert resultado.localidad_entrega == ""
    assert resultado.region_entrega == ""
    # Evidencia técnica de auditoría -- se conserva.
    assert resultado.confianza_geocodificacion == "0.1"
    assert resultado.longitud_entrega and resultado.latitud_entrega


def test_comuna_documental_inequivoca_encuentra_una_comuna_repetida():
    """Caso real 460807: "SAN BERNARDO" aparece dos veces (misma comuna) --
    una sola comuna DISTINTA, evidencia inequívoca."""
    texto = "INTERIOR NUEVA O1148 SAN BERNARDO SAN BERNAR"
    assert _comunas_explicitas(texto) == ("San Bernardo",)
    assert _comuna_documental_inequivoca(texto) == "San Bernardo"


def test_comuna_documental_inequivoca_ya_no_confunde_calle_con_comuna():
    """Bloque TERRITORIAL T1 -- caso real 472002: "Galvarino" es aquí el
    nombre de la CALLE (antes del número), nunca una comuna documental --
    aunque también exista una comuna real con ese nombre en otra región,
    su posición ANTES del número la excluye por construcción (formato
    chileno convencional CALLE NÚMERO COMUNA). "Quilicura" (después del
    número) es la única comuna real candidata -- ya no hay ambigüedad
    que forzara la abstención de antes; se resuelve directo."""
    texto = "GALVARINO 8501 QUILICURA"
    comunas = _comunas_explicitas(texto)
    assert comunas == ("Quilicura",)
    assert _comuna_documental_inequivoca(texto) == "Quilicura"


def test_comuna_documental_inequivoca_vacia_sin_ninguna_comuna_reconocida():
    assert _comuna_documental_inequivoca("DIRECCION SIN NINGUNA COMUNA VALIDA 123") == ""


def test_caso_real_464170_apunta_a_mejillones_no_a_galvarino(planta_renca):
    """Caso real que motivó la regla de negocio: cliente EBEMA SA,
    DIRECCION=GALVARINO 8501/QUILICURA, pero DESPACHAR A=AV. ALMTE.
    LATORRE 843, MEJILLONES. La ruta debe terminar en Mejillones --
    Galvarino 8501 no debe usarse como destino de esta ruta."""
    plantas, _ = planta_renca
    despachar_a_real = "AV. ALMTE. LATORRE 843 MEJILLONES MEJILLONES"
    consulta = f"{despachar_a_real}, Chile"
    proveedor = ProveedorRutasSimulado(
        geocodificaciones={
            consulta: ResultadoGeocodificacion(
                EstadoRuta.REQUIERE_REVISION,
                (CandidatoGeocodificacion(COORD_MEJILLONES, "Av. Almte. Latorre 843, Mejillones", 0.75),),
                "REQUIERE_CONFIRMACION_HUMANA",
            )
        },
        resultado_ruta=ResultadoRuta(EstadoRuta.RUTA_CALCULADA, 1387.4, 960.2, "SINTETICO"),
    )
    resultado = calcular_ruta_entrega_para_viaje(
        despachar_a_crudo=despachar_a_real,
        patente=None, instante_salida=None, plantas=plantas,
        proveedor_posicion=None, proveedor_rutas=proveedor,
        textos_documento=[
            TEXTOS_ENCABEZADO_RENCA,
            "SEÑOR(ES) : EBEMA SA DIRECCION : GALVARINO 8501 COMUNA QUILICURA",
        ],
    )
    assert resultado.estado_ruta == EstadoRuta.RUTA_CALCULADA.value
    assert resultado.latitud_entrega == str(COORD_MEJILLONES.latitud)
    assert resultado.longitud_entrega == str(COORD_MEJILLONES.longitud)
    # Nunca las coordenadas de Galvarino 8501 (Quilicura, RM).
    assert resultado.latitud_entrega != "-33.370934"
