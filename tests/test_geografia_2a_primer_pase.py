"""Bloque GEOGRAFÍA 2A -- PRIMER PASE AUTÓNOMO.

El primer pase productivo (`resolver_entrega_documento` /
`calcular_ruta_entrega_para_viaje` / `resolver_destino_entrega`) ahora
puede usar el geocodificador de RESPALDO gratuito (Nominatim/OSM) y los
destinos ya CONFIRMADOS -- exactamente las mismas capacidades que la
revalidación posterior ya aprovechaba. Todo candidato del respaldo pasa
por los mismos gates (Chile/región, comuna documental/humana, número,
confianza/corroboración) -- nunca se acepta algo sólo porque el respaldo
lo encontró.

Además: la comparación de número de casa colapsa ceros a la izquierda
("0100" == "100", "0015" == "15") pero mantiene "15" != "1545".
"""
from __future__ import annotations

from atlas_core.rutas.destino_entrega import (
    _numero_direccion_incompatible,
    resolver_destino_entrega,
    resolver_destino_entrega_validado,
)
from atlas_core.rutas.modelos import (
    CandidatoGeocodificacion,
    Coordenadas,
    EstadoRuta,
    ResultadoGeocodificacion,
)
from atlas_core.rutas.proveedor import ProveedorRutasSimulado


def _principal_sin_candidatos(consulta):
    return ProveedorRutasSimulado(geocodificaciones={
        consulta: ResultadoGeocodificacion(
            EstadoRuta.DIRECCION_NO_ENCONTRADA, (), "SIN_CANDIDATOS"
        ),
    })


def _principal_un_candidato(consulta, candidato):
    return ProveedorRutasSimulado(geocodificaciones={
        consulta: ResultadoGeocodificacion(
            EstadoRuta.REQUIERE_REVISION, (candidato,), "REQUIERE_CONFIRMACION_HUMANA"
        ),
    })


def _fallback(consulta, candidatos):
    return ProveedorRutasSimulado(geocodificaciones={
        consulta: ResultadoGeocodificacion(
            EstadoRuta.RESULTADO_AMBIGUO, candidatos, "MULTIPLES_CANDIDATOS"
        ),
    })


# ============================================================
# 4. NÚMEROS CON CEROS INICIALES
# ============================================================


def test_numero_ceros_a_la_izquierda_0100_igual_100_compatible():
    assert _numero_direccion_incompatible(
        "SAN DAMIAN 0100 VITACURA", "San Damián 100, Vitacura, RM, Chile"
    ) is False


def test_numero_ceros_a_la_izquierda_0015_igual_15_compatible():
    # Antes del bloque 2A: abs(len("0015") - len("15")) == 2 -> se
    # marcaba incompatible por error (comparación de LARGO de string).
    assert _numero_direccion_incompatible(
        "URUGUAY 0015 LA CISTERNA", "Uruguay 15, La Cisterna, RM, Chile"
    ) is False


def test_numero_15_distinto_de_1545_sigue_incompatible():
    assert _numero_direccion_incompatible(
        "URUGUAY 15", "Uruguay 1545, La Cisterna, RM, Chile"
    ) is True


def test_numero_83_distinto_de_otro_real_sigue_incompatible():
    assert _numero_direccion_incompatible(
        "PUERTA DEL SOL 83", "Puerta del Sol 8351, Las Condes, RM, Chile"
    ) is True


def test_numero_alfanumerico_no_se_colapsa_todavia():
    # "0114B" / "O1148" -- equivalencias alfanuméricas FUERA de este bloque.
    # `_numero_calle` sólo extrae el primer token de dígitos puros, así que
    # la comparación aquí no debe "resolver" el ruido OCR.
    assert _numero_direccion_incompatible(
        "INTERIOR NUEVA 0114B SAN BERNARDO", "Interior Nueva 1148, San Bernardo"
    ) is False  # "0114" vs "1148": distintos, pero mismo largo -> no es el gate


# ============================================================
# 1 + 2. PRIMER PASE CON FALLBACK -- 0 candidatos no es callejón sin salida
# ============================================================


def test_0_candidatos_consulta_fallback_y_resuelve_si_corrobora():
    """CARMEN MENA 529 / SAN MIGUEL: el principal devuelve 0 candidatos
    (DIRECCION_NO_ENCONTRADA). El respaldo encuentra un único candidato con
    el número exacto y la comuna que el propio texto menciona -> RESUELTO,
    sin intervención humana."""
    consulta = "CARMEN MENA 529 SAN MIGUEL, Chile"
    principal = _principal_sin_candidatos(consulta)
    fallback = _fallback(consulta, (
        CandidatoGeocodificacion(
            Coordenadas(-70.652, -33.497), "Carmen Mena 529", 0.9,
            "San Miguel", "Metropolitana",
        ),
    ))
    r = resolver_destino_entrega(
        "CARMEN MENA 529 SAN MIGUEL", principal,
        proveedor_geocodificacion_fallback=fallback,
    )
    assert r.estado == "RESUELTO"
    assert r.coordenadas == Coordenadas(-70.652, -33.497)
    assert r.localidad == "San Miguel"


def test_0_candidatos_fallback_sin_corroboracion_conserva_abstencion():
    """Mismo escenario, pero el candidato del respaldo no tiene ninguna
    comuna que el texto o un destino confirmado corroboren -> se conserva
    EXACTAMENTE la abstención anterior, con su motivo técnico específico.
    Nunca se inventan coordenadas ni ruta."""
    consulta = "CARMEN MENA 529 SAN MIGUEL, Chile"
    principal = _principal_sin_candidatos(consulta)
    fallback = _fallback(consulta, (
        CandidatoGeocodificacion(
            Coordenadas(-70.9, -33.9), "Carmen Mena 529", 0.9, "", "",
        ),
    ))
    r = resolver_destino_entrega(
        "CARMEN MENA 529 SAN MIGUEL", principal,
        proveedor_geocodificacion_fallback=fallback,
    )
    assert r.estado == "REVISAR"
    assert r.motivo == "GEOCODIFICACION_DIRECCION_NO_ENCONTRADA"
    assert r.coordenadas is None


def test_0_candidatos_sin_fallback_comportamiento_identico():
    """Caso E -- sin proveedor de respaldo disponible: comportamiento
    idéntico a antes del bloque (REVISAR con el motivo técnico), sin
    crash, sin aceptación más laxa."""
    consulta = "CARMEN MENA 529 SAN MIGUEL, Chile"
    principal = _principal_sin_candidatos(consulta)
    r = resolver_destino_entrega("CARMEN MENA 529 SAN MIGUEL", principal)
    assert r.estado == "REVISAR"
    assert r.motivo == "GEOCODIFICACION_DIRECCION_NO_ENCONTRADA"
    assert r.coordenadas is None


def test_fallback_no_se_consulta_si_principal_ya_resolvio():
    """El respaldo es "sólo si A falla": si el principal devuelve un
    candidato bueno, el respaldo nunca se toca."""
    consulta = "AV FORESTAL 1014 CORONEL, Chile"
    principal = _principal_un_candidato(consulta, CandidatoGeocodificacion(
        Coordenadas(-73.13, -37.03), "Av. Forestal 1014, Coronel, Biobío", 0.9,
        "Coronel", "Biobío",
    ))
    fallback = _fallback(consulta, (
        CandidatoGeocodificacion(Coordenadas(0.0, 0.0), "BASURA", 0.9, "X", "Y"),
    ))
    r = resolver_destino_entrega(
        "AV FORESTAL 1014 CORONEL", principal,
        proveedor_geocodificacion_fallback=fallback,
    )
    assert r.estado == "RESUELTO"
    assert r.localidad == "Coronel"
    assert fallback.llamadas_geocodificacion == 0


# ============================================================
# A. URUGUAY 15 / LA CISTERNA -- regresión obligatoria
# ============================================================


def test_uruguay_15_candidato_1545_sigue_rechazado():
    consulta = "URUGUAY 15, Chile"
    principal = _principal_un_candidato(consulta, CandidatoGeocodificacion(
        Coordenadas(-72.59, -38.73), "Uruguay 1545, Temuco, Araucanía, Chile", 1.0,
        "Temuco", "Araucanía",
    ))
    r = resolver_destino_entrega_validado("URUGUAY 15", principal)
    assert r.estado == "REVISAR"
    assert "GEOCODIFICACION_NUMERO_INCOMPATIBLE" in r.motivo
    assert r.etiqueta_geocodificada == ""


def test_uruguay_15_candidato_temuco_sigue_rechazado_por_comuna_humana():
    consulta = "URUGUAY 15, Chile"
    principal = _principal_un_candidato(consulta, CandidatoGeocodificacion(
        Coordenadas(-72.59, -38.73), "Uruguay 15, Temuco, Araucanía, Chile", 1.0,
        "Temuco", "Araucanía",
    ))
    r = resolver_destino_entrega_validado(
        "URUGUAY 15", principal, comuna_confirmada_humano="LA CISTERNA",
    )
    assert r.estado == "REVISAR"
    assert "GEOCODIFICACION_CONTRADICE_COMUNA_DOCUMENTAL" in r.motivo
    assert r.etiqueta_geocodificada == ""


# ============================================================
# B. SAN DAMIAN 0100 / VITACURA -- camino feliz sigue RESUELTO
# ============================================================


def test_san_damian_0100_camino_feliz_resuelto():
    consulta = "SAN DAMIAN 0100 VITACURA, Chile"
    principal = _principal_un_candidato(consulta, CandidatoGeocodificacion(
        Coordenadas(-70.55, -33.38), "San Damián 100, Vitacura, RM, Chile", 0.9,
        "Vitacura", "Metropolitana",
    ))
    r = resolver_destino_entrega_validado("SAN DAMIAN 0100 VITACURA", principal)
    assert r.estado == "RESUELTO"
    assert r.motivo == ""
    assert r.coordenadas == Coordenadas(-70.55, -33.38)
    assert r.localidad == "Vitacura"


# ============================================================
# C. PUERTA DEL SOL 83 / LAS CONDES -- centroide -> fallback obligatorio
# ============================================================


def test_puerta_del_sol_83_centroide_consulta_fallback_y_resuelve():
    """El principal sólo devuelve el centroide de la comuna (baja
    confianza, sin número). El respaldo, corroborado por un destino ya
    CONFIRMADO con comuna propia, aporta calle+número -> RESUELTO."""
    from atlas_core.catalogo_destinos import Destino

    consulta = "PUERTA DEL SOL 83 LAS CONDES, Chile"
    principal = _principal_un_candidato(consulta, CandidatoGeocodificacion(
        Coordenadas(-70.53, -33.40), "Las Condes, RM, Chile", 0.2,
        "Las Condes", "Metropolitana",
    ))
    fallback = ProveedorRutasSimulado(geocodificaciones={
        "PUERTA DEL SOL 83 LAS CONDES, Chile": ResultadoGeocodificacion(
            EstadoRuta.RESULTADO_AMBIGUO,
            (CandidatoGeocodificacion(
                Coordenadas(-70.5074, -33.4128), "Puerta del Sol 83", 0.9,
                "Las Condes", "Metropolitana",
            ),),
            "MULTIPLES_CANDIDATOS",
        ),
    })
    destino = Destino(
        destino_id="d-1", cliente_id="", nombre_destino="PUERTA DEL SOL 83",
        nombre_normalizado="PUERTA DEL SOL 83", codigo_destino="",
        direccion="PUERTA DEL SOL 83", comuna="Las Condes", region="", pais="CHILE",
        latitud=None, longitud=None, aliases=(), estado_calidad="CONFIRMADO",
        estado_vigencia="ACTIVO", fuente="TEST", observacion="",
        fecha_creacion="2026-01-01T00:00:00+00:00",
        fecha_modificacion="2026-01-01T00:00:00+00:00",
    )
    r = resolver_destino_entrega_validado(
        "PUERTA DEL SOL 83 LAS CONDES", principal,
        proveedor_geocodificacion_fallback=fallback,
        destinos_confirmados=(destino,),
    )
    assert r.estado == "RESUELTO"
    assert r.coordenadas == Coordenadas(-70.5074, -33.4128)
    assert r.localidad == "Las Condes"


def test_puerta_del_sol_83_centroide_sin_corroboracion_abstiene():
    """Sin destino confirmado ni evidencia que corrobore, el candidato del
    respaldo (un único número, sin comuna en el texto) NO alcanza para
    resolver -> abstención (CONFIANZA_INSUFICIENTE), nunca ruta al
    centroide como si fuera el destino exacto."""
    consulta = "PUERTA DEL SOL 83, Chile"
    principal = _principal_un_candidato(consulta, CandidatoGeocodificacion(
        Coordenadas(-70.53, -33.40), "Chile", 0.1, "", "",
    ))
    fallback = ProveedorRutasSimulado(geocodificaciones={
        "PUERTA DEL SOL 83, Chile": ResultadoGeocodificacion(
            EstadoRuta.RESULTADO_AMBIGUO,
            (CandidatoGeocodificacion(
                Coordenadas(-70.5074, -33.4128), "Puerta del Sol 83", 0.9, "Las Condes", "Metropolitana",
            ),),
            "MULTIPLES_CANDIDATOS",
        ),
    })
    r = resolver_destino_entrega_validado(
        "PUERTA DEL SOL 83", principal,
        proveedor_geocodificacion_fallback=fallback,
    )
    assert r.estado == "REVISAR"
    assert r.motivo == "CONFIANZA_INSUFICIENTE"


# ============================================================
# resolver_entrega_documento -- acepta y propaga los nuevos parámetros
# ============================================================


def test_resolver_entrega_documento_propaga_fallback_y_destinos_confirmados(tmp_path):
    from atlas_core.catalogo_plantas import CatalogoPlantas, EstadoCalidad
    from atlas_core.rutas.destino_entrega import resolver_entrega_documento

    catalogo = CatalogoPlantas(tmp_path / "plantas.json")
    catalogo.crear(
        nombre="AZA RENCA", pais="CHILE", fuente="PRUEBA",
        direccion="LA UNION 3070", comuna="RENCA", region="RM",
        latitud=-33.401595, longitud=-70.685226,
        estado_calidad=EstadoCalidad.CONFIRMADA,
    )
    textos = [
        "GUIA DESPACHO PLANTA ORIGEN RENCA ACEROS AZA S A CASA MATRIZ PLANTA RENCA LA UNION 3070 RENCA SANTIAGO CHILE",
        "SEÑOR(ES) : CLIENTE DEMO SA",
        "OBRA DESTINO : OBRA DEMO",
        "DESPACHAR A : CARMEN MENA 529 SAN MIGUEL",
    ]
    consulta = "CARMEN MENA 529 SAN MIGUEL, Chile"
    principal = ProveedorRutasSimulado(
        geocodificaciones={
            consulta: ResultadoGeocodificacion(
                EstadoRuta.DIRECCION_NO_ENCONTRADA, (), "SIN_CANDIDATOS"
            ),
        },
        resultado_ruta=__import__(
            "atlas_core.rutas.modelos", fromlist=["ResultadoRuta"]
        ).ResultadoRuta(EstadoRuta.RUTA_CALCULADA, 8.0, 15.0, "SINTETICO"),
    )
    fallback = _fallback(consulta, (
        CandidatoGeocodificacion(
            Coordenadas(-70.652, -33.497), "Carmen Mena 529", 0.9, "San Miguel", "Metropolitana",
        ),
    ))
    resultado = resolver_entrega_documento(
        textos, catalogo.listar(), principal,
        destinos_confirmados=[],
        proveedor_geocodificacion_fallback=fallback,
    )
    # El fallback SÍ se consultó (el principal dio 0 candidatos) y el
    # candidato corroborado por el propio texto se aceptó -> ruta calculada.
    assert fallback.llamadas_geocodificacion >= 1
    assert resultado["estado_ruta"] == EstadoRuta.RUTA_CALCULADA.value
    assert resultado["localidad_entrega"] == "San Miguel"


def test_resolver_entrega_documento_sin_nuevos_parametros_sigue_funcionando(tmp_path):
    """Compatibilidad: llamadores que no pasan los nuevos parámetros
    (default) obtienen exactamente el comportamiento anterior."""
    from atlas_core.catalogo_plantas import CatalogoPlantas, EstadoCalidad
    from atlas_core.rutas.destino_entrega import resolver_entrega_documento

    catalogo = CatalogoPlantas(tmp_path / "plantas.json")
    catalogo.crear(
        nombre="AZA RENCA", pais="CHILE", fuente="PRUEBA",
        direccion="LA UNION 3070", comuna="RENCA", region="RM",
        latitud=-33.401595, longitud=-70.685226,
        estado_calidad=EstadoCalidad.CONFIRMADA,
    )
    textos = [
        "GUIA DESPACHO PLANTA ORIGEN RENCA ACEROS AZA S A CASA MATRIZ PLANTA RENCA LA UNION 3070 RENCA SANTIAGO CHILE",
        "OBRA DESTINO : OBRA DEMO",
        "DESPACHAR A : CARMEN MENA 529 SAN MIGUEL",
    ]
    principal = _principal_sin_candidatos("CARMEN MENA 529 SAN MIGUEL, Chile")
    resultado = resolver_entrega_documento(textos, catalogo.listar(), principal)
    assert resultado["estado_ruta"] == EstadoRuta.REQUIERE_REVISION.value
    assert "DIRECCION_NO_ENCONTRADA" in resultado["motivo_ruta"]
