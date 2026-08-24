"""Bloque B1 OBSERVADOR + FALLBACK GEOGRÁFICO -- "Vía C": un geocodificador
de RESPALDO estructurado se consulta SÓLO cuando el principal deja una
ambigüedad sin resolver y ni Vía A (catálogo confirmado) ni Vía B (GPS)
pueden desambiguar. Se acepta el candidato del respaldo SÓLO si es el
ÚNICO con número de calle coincidente Y un destino ya CONFIRMADO trae
comuna propia territorialmente compatible -- nunca un candidato solitario
sin corroboración (caso real 472037: Nominatim encuentra "Pasaje Vicuña
Mackenna 655" en Maipú, pero sin comuna confirmada que lo corrobore --
Atlas se abstiene en vez de adivinar)."""
from __future__ import annotations

from datetime import datetime, timezone

from atlas_core.catalogo_destinos import Destino
from atlas_core.rutas.destino_entrega import (
    resolver_destino_con_fallback_estructurado,
    resolver_destino_entrega,
)
from atlas_core.rutas.modelos import (
    CandidatoGeocodificacion, Coordenadas, EstadoRuta, ResultadoGeocodificacion,
)
from atlas_core.rutas.proveedor import ProveedorRutasSimulado

FECHA = datetime(2026, 1, 1, tzinfo=timezone.utc).isoformat()


def _candidato(lat, lon, etiqueta="Candidato", confianza=0.9, localidad="", region=""):
    return CandidatoGeocodificacion(Coordenadas(lon, lat), etiqueta, confianza, localidad, region)


def _destino_confirmado(direccion, *, comuna="", estado_calidad="CONFIRMADO", estado_vigencia="ACTIVO"):
    return Destino(
        destino_id="d-1", cliente_id="", nombre_destino=direccion,
        nombre_normalizado=direccion.upper(), codigo_destino="",
        direccion=direccion, comuna=comuna, region="", pais="CHILE",
        latitud=None, longitud=None, aliases=(), estado_calidad=estado_calidad,
        estado_vigencia=estado_vigencia, fuente="TEST", observacion="",
        fecha_creacion=FECHA, fecha_modificacion=FECHA,
    )


def _proveedor_fallback(candidatos, *, consulta="VICUÑA MACKENNA 655, Chile"):
    return ProveedorRutasSimulado(geocodificaciones={
        consulta: ResultadoGeocodificacion(EstadoRuta.RESULTADO_AMBIGUO, candidatos, "MULTIPLES_CANDIDATOS"),
    })


# ============================================================
# resolver_destino_con_fallback_estructurado -- unidad
# ============================================================


def test_caso_real_472037_sin_comuna_confirmada_ni_evidencia_b1_se_abstiene():
    """Control -- sin comuna confirmada NI evidencia B1 que mencione
    "Santiago": nada que corrobore, Atlas se abstiene (nunca adivina)."""
    candidatos = (
        _candidato(-33.52, -70.75, "Pasaje Vicuña Mackenna 655", localidad="Maipú", region="Metropolitana"),
        _candidato(-33.05, -71.62, "Vicuña Mackenna", confianza=0.2, localidad="Valparaíso", region="Valparaíso"),
    )
    destino = _destino_confirmado("VICUÑA MACKENNA 655", comuna="")
    r = resolver_destino_con_fallback_estructurado(
        "VICUÑA MACKENNA 655", proveedor_fallback=_proveedor_fallback(candidatos),
        destinos_confirmados=(destino,),
    )
    assert r.resuelto is False
    assert r.identidad_confirmada is True
    assert "FALLBACK_SIN_CORROBORACION_TERRITORIAL" in r.motivo


def test_caso_real_472037_evidencia_b1_menciona_santiago_corrobora_maipu():
    """Bloque VALIDACIÓN TERRITORIAL T2 -- caso real 472037 exacto: el
    destino confirmado no tiene comuna propia, pero la evidencia YA
    PERSISTIDA de B1 (nunca una llamada nueva) menciona "Santiago" como
    ciudad/área metropolitana -- territorialmente compatible con Maipú
    (misma región RM, criterio ya calibrado). "Santiago" y "Maipú" NO
    son automáticamente incompatibles -- Atlas compara niveles
    territoriales equivalentes, nunca exige coincidencia literal."""
    candidatos = (
        _candidato(-33.52, -70.75, "Pasaje Vicuña Mackenna 655", localidad="Maipú", region="Metropolitana"),
        _candidato(-33.05, -71.62, "Vicuña Mackenna", confianza=0.2, localidad="Valparaíso", region="Valparaíso"),
    )
    destino = _destino_confirmado("VICUÑA MACKENNA 655", comuna="")
    evidencia_b1 = (
        'Los dos registros externos consultados confirman que la dirección Vicuña Mackenna 655 '
        'existe y está asociada al proyecto "Vicuña Mackenna 655" en Santiago.'
    )
    r = resolver_destino_con_fallback_estructurado(
        "VICUÑA MACKENNA 655", proveedor_fallback=_proveedor_fallback(candidatos),
        destinos_confirmados=(destino,), contexto_evidencia_b1=evidencia_b1,
    )
    assert r.resuelto is True
    assert r.candidato.localidad == "Maipú"
    assert r.motivo == "FALLBACK_ESTRUCTURADO_CORROBORADO"


def test_evidencia_b1_menciona_comuna_fuera_de_rm_no_corrobora():
    """Control -- "Santiago" en la evidencia B1 sólo corrobora comunas de
    la MISMA región (RM); un candidato en otra región sigue bloqueado
    -- nunca "cualquier mención de Santiago basta"."""
    candidatos = (
        _candidato(-36.6, -72.1, "Vicuña Mackenna 655", localidad="Chillán", region="Ñuble"),
    )
    destino = _destino_confirmado("VICUÑA MACKENNA 655", comuna="")
    evidencia_b1 = 'La dirección está asociada al proyecto en Santiago.'
    r = resolver_destino_con_fallback_estructurado(
        "VICUÑA MACKENNA 655", proveedor_fallback=_proveedor_fallback(candidatos),
        destinos_confirmados=(destino,), contexto_evidencia_b1=evidencia_b1,
    )
    assert r.resuelto is False


def test_evidencia_b1_sin_mencion_de_santiago_no_corrobora():
    """Control -- evidencia B1 real pero que NUNCA menciona "Santiago"
    (ni ninguna comuna): no hay nada que corroborar, se abstiene igual
    que sin evidencia."""
    candidatos = (
        _candidato(-33.52, -70.75, "Pasaje Vicuña Mackenna 655", localidad="Maipú", region="Metropolitana"),
    )
    destino = _destino_confirmado("VICUÑA MACKENNA 655", comuna="")
    evidencia_b1 = "Se encontró una referencia al proyecto asociado a Fundamenta."
    r = resolver_destino_con_fallback_estructurado(
        "VICUÑA MACKENNA 655", proveedor_fallback=_proveedor_fallback(candidatos),
        destinos_confirmados=(destino,), contexto_evidencia_b1=evidencia_b1,
    )
    assert r.resuelto is False


def test_mencion_de_santiago_dentro_de_otra_palabra_no_cuenta():
    """Nunca un `in` ingenuo sobre el string crudo -- "Santiago" debe
    aparecer como palabra completa, no como substring de otra palabra
    (evita falsos positivos)."""
    candidatos = (
        _candidato(-33.52, -70.75, "Pasaje Vicuña Mackenna 655", localidad="Maipú", region="Metropolitana"),
    )
    destino = _destino_confirmado("VICUÑA MACKENNA 655", comuna="")
    evidencia_b1 = "El chofer se llama Santiagocarlos Pérez."  # nunca "Santiago" como palabra
    r = resolver_destino_con_fallback_estructurado(
        "VICUÑA MACKENNA 655", proveedor_fallback=_proveedor_fallback(candidatos),
        destinos_confirmados=(destino,), contexto_evidencia_b1=evidencia_b1,
    )
    assert r.resuelto is False


def test_comuna_confirmada_compatible_resuelve():
    """Control positivo -- si el destino CONFIRMADO SÍ trae una comuna
    propia y es territorialmente compatible con el candidato único, Vía
    C resuelve."""
    candidatos = (
        _candidato(-33.52, -70.75, "Pasaje Vicuña Mackenna 655", localidad="Maipú", region="Metropolitana"),
        _candidato(-33.05, -71.62, "Vicuña Mackenna", confianza=0.2, localidad="Valparaíso", region="Valparaíso"),
    )
    destino = _destino_confirmado("VICUÑA MACKENNA 655", comuna="Maipú")
    r = resolver_destino_con_fallback_estructurado(
        "VICUÑA MACKENNA 655", proveedor_fallback=_proveedor_fallback(candidatos),
        destinos_confirmados=(destino,),
    )
    assert r.resuelto is True
    assert r.candidato.localidad == "Maipú"
    assert r.motivo == "FALLBACK_ESTRUCTURADO_CORROBORADO"


def test_comuna_confirmada_incompatible_se_abstiene():
    """Control negativo -- comuna confirmada REAL pero de otra región:
    contradicción real, nunca se acepta el candidato."""
    candidatos = (
        _candidato(-33.52, -70.75, "Pasaje Vicuña Mackenna 655", localidad="Maipú", region="Metropolitana"),
    )
    destino = _destino_confirmado("VICUÑA MACKENNA 655", comuna="Concepción")
    r = resolver_destino_con_fallback_estructurado(
        "VICUÑA MACKENNA 655", proveedor_fallback=_proveedor_fallback(candidatos),
        destinos_confirmados=(destino,),
    )
    assert r.resuelto is False


def test_dos_candidatos_con_el_mismo_numero_no_es_unico():
    """Dos calles homónimas distintas, cada una con el número 655 --
    nunca se elige una al azar."""
    candidatos = (
        _candidato(-33.52, -70.75, "Pasaje Vicuña Mackenna 655", localidad="Maipú", region="Metropolitana"),
        _candidato(-33.40, -70.60, "Vicuña Mackenna 655", localidad="Providencia", region="Metropolitana"),
    )
    destino = _destino_confirmado("VICUÑA MACKENNA 655", comuna="Maipú")
    r = resolver_destino_con_fallback_estructurado(
        "VICUÑA MACKENNA 655", proveedor_fallback=_proveedor_fallback(candidatos),
        destinos_confirmados=(destino,),
    )
    assert r.resuelto is False
    assert "FALLBACK_SIN_CANDIDATO_UNICO" in r.motivo


def test_sin_numero_en_el_texto_documental_se_abstiene():
    """Nunca gasta una consulta de red cuando el texto documental no
    tiene ningún número de calle -- se abstiene antes de consultar el
    respaldo (Bloque J: "no gastar si no hace falta")."""
    destino = _destino_confirmado("CAMINO SIN NUMERO", comuna="Maipú")
    llamadas = []
    fallback_nunca_llamado = _proveedor_fallback((), consulta="x")
    fallback_nunca_llamado.geocodificar = lambda d: llamadas.append(d)
    r = resolver_destino_con_fallback_estructurado(
        "CAMINO SIN NUMERO", proveedor_fallback=fallback_nunca_llamado,
        destinos_confirmados=(destino,),
    )
    assert r.resuelto is False
    assert r.motivo == "SIN_NUMERO_DE_CALLE_EN_TEXTO_DOCUMENTAL"
    assert llamadas == []


def test_sin_texto_documental_se_abstiene():
    r = resolver_destino_con_fallback_estructurado(
        "", proveedor_fallback=_proveedor_fallback((), consulta="x"),
    )
    assert r.resuelto is False
    assert r.motivo == "SIN_TEXTO_DOCUMENTAL"


# ============================================================
# resolver_destino_entrega -- integración ("sólo si A falla")
# ============================================================


def test_resolver_destino_entrega_no_llama_al_fallback_si_el_principal_resuelve():
    """Nunca se consulta el respaldo cuando el proveedor principal ya
    resolvió sin ambigüedad -- "sólo si A falla" (Bloque J)."""
    consulta = "AV. ALMTE. LATORRE 843, MEJILLONES, Chile"
    principal = ProveedorRutasSimulado(geocodificaciones={
        consulta: ResultadoGeocodificacion(
            EstadoRuta.REQUIERE_REVISION,
            (CandidatoGeocodificacion(Coordenadas(-70.45, -23.10), "Av. Almte. Latorre 843, Mejillones", 0.8),),
            "REQUIERE_CONFIRMACION_HUMANA",
        )
    })
    llamadas_fallback = []
    fallback = ProveedorRutasSimulado(geocodificaciones={})
    fallback.geocodificar = lambda d: (llamadas_fallback.append(d) or ResultadoGeocodificacion(EstadoRuta.DIRECCION_NO_ENCONTRADA))
    resultado = resolver_destino_entrega(
        "AV. ALMTE. LATORRE 843, MEJILLONES", principal,
        proveedor_geocodificacion_fallback=fallback,
    )
    assert resultado.estado == "RESUELTO"
    assert llamadas_fallback == []


def test_resolver_destino_entrega_usa_el_fallback_cuando_hay_corroboracion():
    """E2E de la Vía C dentro de `resolver_destino_entrega`: ambiguo en
    el principal, sin catálogo/GPS, pero el respaldo SÍ corrobora contra
    un destino confirmado con comuna propia -- resuelve punto + persiste
    localidad/región, nunca inventa km/tiempo (eso lo hace el routing,
    aparte)."""
    consulta = "VICUÑA MACKENNA 655, Chile"
    principal = ProveedorRutasSimulado(geocodificaciones={
        consulta: ResultadoGeocodificacion(
            EstadoRuta.RESULTADO_AMBIGUO,
            (
                CandidatoGeocodificacion(Coordenadas(-70.60, -33.45), "Vicuña Mackenna, Providencia", 0.6, "Providencia", "Metropolitana"),
                CandidatoGeocodificacion(Coordenadas(-72.6, -38.7), "Vicuña Mackenna, Temuco", 0.6, "Temuco", "La Araucanía"),
            ),
            "MULTIPLES_CANDIDATOS",
        )
    })
    fallback_candidatos = (
        CandidatoGeocodificacion(Coordenadas(-70.75, -33.52), "Pasaje Vicuña Mackenna 655", 0.9, "Maipú", "Metropolitana"),
        CandidatoGeocodificacion(Coordenadas(-71.62, -33.05), "Vicuña Mackenna", 0.2, "Valparaíso", "Valparaíso"),
    )
    fallback = _proveedor_fallback(fallback_candidatos)
    destino = _destino_confirmado("VICUÑA MACKENNA 655", comuna="Maipú")
    resultado = resolver_destino_entrega(
        "VICUÑA MACKENNA 655", principal,
        destinos_confirmados=(destino,), proveedor_geocodificacion_fallback=fallback,
    )
    assert resultado.estado == "RESUELTO"
    assert resultado.coordenadas == Coordenadas(-70.75, -33.52)
    assert resultado.localidad == "Maipú"
    assert resultado.metodo_confirmacion == "FALLBACK_ESTRUCTURADO_CORROBORADO"


def test_resolver_destino_entrega_sin_corroboracion_conserva_motivo_correcto():
    """Control -- sin comuna confirmada NI evidencia B1: el respaldo
    encuentra un candidato, pero nada lo corrobora -- Atlas se abstiene
    con el motivo correcto (identidad confirmada, sólo falta el punto),
    nunca inventa."""
    consulta = "VICUÑA MACKENNA 655, Chile"
    principal = ProveedorRutasSimulado(geocodificaciones={
        consulta: ResultadoGeocodificacion(
            EstadoRuta.RESULTADO_AMBIGUO,
            (
                CandidatoGeocodificacion(Coordenadas(-70.60, -33.45), "Vicuña Mackenna, Providencia", 0.6, "Providencia", "Metropolitana"),
                CandidatoGeocodificacion(Coordenadas(-72.6, -38.7), "Vicuña Mackenna, Temuco", 0.6, "Temuco", "La Araucanía"),
            ),
            "MULTIPLES_CANDIDATOS",
        )
    })
    fallback_candidatos = (
        CandidatoGeocodificacion(Coordenadas(-70.75, -33.52), "Pasaje Vicuña Mackenna 655", 0.9, "Maipú", "Metropolitana"),
    )
    fallback = _proveedor_fallback(fallback_candidatos)
    destino = _destino_confirmado("VICUÑA MACKENNA 655", comuna="")  # sin comuna registrada
    resultado = resolver_destino_entrega(
        "VICUÑA MACKENNA 655", principal,
        destinos_confirmados=(destino,), proveedor_geocodificacion_fallback=fallback,
    )
    assert resultado.estado == "REVISAR"
    assert resultado.coordenadas is None  # nunca inventa un punto
    assert resultado.motivo == "COORDENADA_NO_CONFIRMADA(2)"


def test_resolver_destino_entrega_caso_real_472037_con_evidencia_b1_resuelve():
    """Caso real 472037 exacto, dentro de `resolver_destino_entrega`
    completo: destino confirmado SIN comuna propia, pero con la
    evidencia B1 YA PERSISTIDA (nunca una llamada nueva) que menciona
    "Santiago" -- ahora SÍ corrobora al candidato único del respaldo
    (Maipú, misma región RM) y resuelve el punto."""
    consulta = "VICUÑA MACKENNA 655, Chile"
    principal = ProveedorRutasSimulado(geocodificaciones={
        consulta: ResultadoGeocodificacion(
            EstadoRuta.RESULTADO_AMBIGUO,
            (
                CandidatoGeocodificacion(Coordenadas(-70.60, -33.45), "Vicuña Mackenna, Providencia", 0.6, "Providencia", "Metropolitana"),
                CandidatoGeocodificacion(Coordenadas(-72.6, -38.7), "Vicuña Mackenna, Temuco", 0.6, "Temuco", "La Araucanía"),
            ),
            "MULTIPLES_CANDIDATOS",
        )
    })
    fallback_candidatos = (
        CandidatoGeocodificacion(Coordenadas(-70.75, -33.52), "Pasaje Vicuña Mackenna 655", 0.9, "Maipú", "Metropolitana"),
    )
    fallback = _proveedor_fallback(fallback_candidatos)
    destino = _destino_confirmado("VICUÑA MACKENNA 655", comuna="")  # sin comuna registrada
    evidencia_b1 = 'La dirección Vicuña Mackenna 655 está asociada al proyecto en Santiago.'
    resultado = resolver_destino_entrega(
        "VICUÑA MACKENNA 655", principal,
        destinos_confirmados=(destino,), proveedor_geocodificacion_fallback=fallback,
        contexto_evidencia_b1=evidencia_b1,
    )
    assert resultado.estado == "RESUELTO"
    assert resultado.coordenadas == Coordenadas(-70.75, -33.52)
    assert resultado.localidad == "Maipú"
    assert resultado.motivo == ""
