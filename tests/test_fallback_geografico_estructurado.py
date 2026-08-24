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
from atlas_core.catalogo_plantas import CatalogoPlantas, EstadoCalidad
from atlas_core.rutas.destino_entrega import (
    _numeros_de_calle,
    calcular_ruta_con_planta_conocida,
    resolver_destino_con_fallback_estructurado,
    resolver_destino_entrega,
)
from atlas_core.rutas.modelos import (
    CandidatoGeocodificacion, Coordenadas, EstadoRuta,
    ResultadoGeocodificacion, ResultadoRuta,
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


# ============================================================
# Bloque CATCH-UP LOGÍSTICO -- el fallback también se intenta cuando el
# principal deja UN ÚNICO candidato de confianza insuficiente (nunca
# sólo en el camino ambiguo) y cuando la ruta queda SIN_ACCESO_VIAL.
# ============================================================


def test_caso_real_472044_candidato_unico_insuficiente_usa_fallback():
    """Caso real 472044 (PUERTA DEL SOL 83): el principal NUNCA queda
    ambiguo -- resuelve un único candidato degradado a nivel país
    ("Chile", confianza 0.1). Antes, esto terminaba directo en
    `CONFIANZA_INSUFICIENTE` sin intentar el respaldo. Con corroboración
    disponible (comuna confirmada), el respaldo debe intentarse igual
    que en el camino ambiguo -- "sólo si A falla" cubre cualquier forma
    de que A falle."""
    consulta = "PUERTA DEL SOL 83, Chile"
    principal = ProveedorRutasSimulado(geocodificaciones={
        consulta: ResultadoGeocodificacion(
            EstadoRuta.REQUIERE_REVISION,
            (CandidatoGeocodificacion(Coordenadas(-72.27, -38.17), "Chile", 0.1),),
            "REQUIERE_CONFIRMACION_HUMANA",
        )
    })
    fallback = _proveedor_fallback(
        (CandidatoGeocodificacion(Coordenadas(-70.57, -33.41), "Puerta del Sol 83", 0.9, "Las Condes", "Metropolitana"),),
        consulta="PUERTA DEL SOL 83, Chile",
    )
    destino = _destino_confirmado("PUERTA DEL SOL 83", comuna="Las Condes")
    resultado = resolver_destino_entrega(
        "PUERTA DEL SOL 83", principal,
        destinos_confirmados=(destino,), proveedor_geocodificacion_fallback=fallback,
    )
    assert resultado.estado == "RESUELTO"
    assert resultado.coordenadas == Coordenadas(-70.57, -33.41)
    assert resultado.localidad == "Las Condes"


def test_candidato_unico_insuficiente_sin_corroboracion_conserva_motivo():
    """Control -- mismo escenario, pero sin nada que corrobore al
    respaldo: se conserva `CONFIANZA_INSUFICIENTE`, nunca inventa."""
    consulta = "PUERTA DEL SOL 83, Chile"
    principal = ProveedorRutasSimulado(geocodificaciones={
        consulta: ResultadoGeocodificacion(
            EstadoRuta.REQUIERE_REVISION,
            (CandidatoGeocodificacion(Coordenadas(-72.27, -38.17), "Chile", 0.1),),
            "REQUIERE_CONFIRMACION_HUMANA",
        )
    })
    fallback = _proveedor_fallback(
        (CandidatoGeocodificacion(Coordenadas(-70.57, -33.41), "Puerta del Sol 83", 0.9, "Las Condes", "Metropolitana"),),
        consulta="PUERTA DEL SOL 83, Chile",
    )
    resultado = resolver_destino_entrega(
        "PUERTA DEL SOL 83", principal, proveedor_geocodificacion_fallback=fallback,
    )
    assert resultado.estado == "REVISAR"
    assert resultado.motivo == "CONFIANZA_INSUFICIENTE"


def test_caso_real_472073_sin_acceso_vial_usa_fallback_con_destino_confirmado(tmp_path):
    """Caso real 472073 (PDTE. RIESCO 5903 LAS CONDES): el destino ya
    CONFIRMADO trae comuna propia ("Las Condes") pero SIN coordenadas
    (Bloque CONFIRMACIÓN D2) -- el reintento clásico de SIN_ACCESO_VIAL
    exige coordenadas YA presentes en el destino confirmado y nunca
    podía usarlo. Con el fallback estructurado corroborado por esa misma
    comuna, se reintenta el ruteo desde el punto que SÍ resuelve."""
    plantas = CatalogoPlantas(tmp_path / "plantas.json")
    planta = plantas.crear(
        nombre="AZA RENCA", pais="CHILE", fuente="TEST",
        direccion="LA UNION 3070", comuna="RENCA", region="RM",
        latitud=-33.401595, longitud=-70.685226, estado_calidad=EstadoCalidad.CONFIRMADA,
    )
    centroide = Coordenadas(-70.57, -33.40)
    punto_fallback = Coordenadas(-70.55, -33.42)  # a ~2.7 km del centroide -- evidencia nueva real
    consulta = "PDTE. RIESCO 5903 LAS CONDES, Chile"

    class _ProveedorSinAccesoEnCentroide:
        nombre = "simulado_sin_acceso"
        version = "1"

        def geocodificar(self, direccion):
            return ResultadoGeocodificacion(
                EstadoRuta.REQUIERE_REVISION,
                (CandidatoGeocodificacion(centroide, "Las Condes, RM, Chile", 0.6, "Las Condes", "Metropolitana"),),
                "REQUIERE_CONFIRMACION_HUMANA",
            )

        def calcular_ruta(self, origen, destino, perfil):
            if (round(destino.longitud, 4), round(destino.latitud, 4)) == (round(punto_fallback.longitud, 4), round(punto_fallback.latitud, 4)):
                return ResultadoRuta(EstadoRuta.RUTA_CALCULADA, 18.0, 25.0, "SINTETICO")
            return ResultadoRuta(EstadoRuta.SIN_ACCESO_VIAL, motivo="SIN_ACCESO_VIAL")

    fallback = _proveedor_fallback(
        (CandidatoGeocodificacion(punto_fallback, "Avenida Manquehue 5903", 0.9, "Las Condes", "Metropolitana"),),
        consulta=consulta,
    )
    destino = _destino_confirmado("PDTE. RIESCO 5903", comuna="Las Condes")
    resultado = calcular_ruta_con_planta_conocida(
        planta=planta, despachar_a_crudo="PDTE. RIESCO 5903 LAS CONDES",
        proveedor_rutas=_ProveedorSinAccesoEnCentroide(),
        destinos_confirmados=(destino,), proveedor_geocodificacion_fallback=fallback,
    )
    assert resultado.estado_ruta == "RUTA_CALCULADA"
    assert resultado.distancia_km == "18.0"
    assert resultado.metodo_confirmacion_destino == "FALLBACK_ESTRUCTURADO_SIN_ACCESO_VIAL"


def test_sin_acceso_vial_sin_corroboracion_conserva_motivo(tmp_path):
    """Control -- sin comuna confirmada que corrobore, `SIN_ACCESO_VIAL`
    se conserva -- nunca inventa un snap vial."""
    plantas = CatalogoPlantas(tmp_path / "plantas.json")
    planta = plantas.crear(
        nombre="AZA RENCA", pais="CHILE", fuente="TEST",
        direccion="LA UNION 3070", comuna="RENCA", region="RM",
        latitud=-33.401595, longitud=-70.685226, estado_calidad=EstadoCalidad.CONFIRMADA,
    )
    centroide = Coordenadas(-70.57, -33.40)
    consulta = "PDTE. RIESCO 5903 LAS CONDES, Chile"

    class _ProveedorSinAcceso:
        nombre = "simulado_sin_acceso"
        version = "1"

        def geocodificar(self, direccion):
            return ResultadoGeocodificacion(
                EstadoRuta.REQUIERE_REVISION,
                (CandidatoGeocodificacion(centroide, "Las Condes, RM, Chile", 0.6, "Las Condes", "Metropolitana"),),
                "REQUIERE_CONFIRMACION_HUMANA",
            )

        def calcular_ruta(self, origen, destino, perfil):
            return ResultadoRuta(EstadoRuta.SIN_ACCESO_VIAL, motivo="SIN_ACCESO_VIAL")

    fallback = _proveedor_fallback(
        (CandidatoGeocodificacion(Coordenadas(-70.5694134, -33.4025444), "Avenida Manquehue 5903", 0.9, "Las Condes", "Metropolitana"),),
        consulta=consulta,
    )
    resultado = calcular_ruta_con_planta_conocida(
        planta=planta, despachar_a_crudo="PDTE. RIESCO 5903 LAS CONDES",
        proveedor_rutas=_ProveedorSinAcceso(), proveedor_geocodificacion_fallback=fallback,
    )
    assert resultado.estado_ruta == "SIN_ACCESO_VIAL"


# ============================================================
# Bloque CATCH-UP LOGÍSTICO -- generalización de detección de número de
# calle: un patrón OCR real (símbolo de numeral "Nº"/"N°" perdido/
# confundido con una letra pegada al número, caso real 460807/472008
# "INTERIOR NUEVA O1148 SAN BERNARDO") también cuenta como número.
# ============================================================


def test_numero_con_prefijo_ocr_se_detecta():
    assert _numeros_de_calle("INTERIOR NUEVA O1148 SAN BERNARDO") == {"1148"}


def test_numero_con_prefijo_ocr_coincide_con_candidato_sin_prefijo():
    """El destino confirmado hereda el MISMO texto glueado que quedó
    persistido al confirmarse (caso real 460807/472008: `direccion_final`
    es literalmente lo que Javier/la evidencia externa confirmó, con el
    mismo artefacto OCR) -- `_destino_confirmado_coincide_texto` compara
    literal, así que el candidato del respaldo (sin el prefijo, como lo
    devuelve un geocodificador estructurado real) debe seguir corroborando
    vía el número ya normalizado, no vía el texto crudo con el prefijo."""
    candidatos = (
        CandidatoGeocodificacion(Coordenadas(-70.7, -33.6), "Interior Nueva 1148", 0.9, "San Bernardo", "Metropolitana"),
    )
    destino = _destino_confirmado("INTERIOR NUEVA O1148 SAN BERNARDO", comuna="San Bernardo")
    r = resolver_destino_con_fallback_estructurado(
        "INTERIOR NUEVA O1148 SAN BERNARDO",
        proveedor_fallback=_proveedor_fallback(candidatos, consulta="INTERIOR NUEVA O1148 SAN BERNARDO, Chile"),
        destinos_confirmados=(destino,),
    )
    assert r.resuelto is True
    assert r.candidato.localidad == "San Bernardo"


def test_numero_normal_sin_prefijo_no_se_duplica():
    """Control -- un texto con número normal (sin prefijo OCR) sigue
    detectándose exactamente igual que antes -- la generalización no
    cambia el caso ya cubierto."""
    assert _numeros_de_calle("PUERTA DEL SOL 83") == {"83"}
