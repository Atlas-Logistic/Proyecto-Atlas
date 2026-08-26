"""Bloque DESTINOS E1 -- FIX DE AUTONOMÍA DE DESTINO: una dirección
urbana numerada no debe quedar en `SIN_ACCESO_VIAL`/`REVISAR` sin agotar
el pipeline determinista ya existente (ORS -> Nominatim de respaldo ->
corroboración territorial).

Caso real que motivó este bloque -- guía 472339, "HELSINSKI 5810 LA
REINA SANTIAGO": el proveedor principal (ORS) sólo resolvió dos
centroides genéricos de comuna ("La Reina, RM, Chile", misma localidad,
misma confianza, >1 km entre sí) -- correctamente tratados como "el
mismo lugar real" (Bloque E2E R1.1, caso Coronel/Biobío) y aceptados
como RESUELTO, pero el punto elegido resultó no ruteable (`SIN_ACCESO_
VIAL`). El reintento con el respaldo estructurado (Nominatim) SÍ
encontró la calle ("Helsinski"), pero SIN el número de casa en su
etiqueta -- `_candidato_unico_con_numero_de_calle` exigía SIEMPRE un
calce de número, así que un único candidato de calle real, sin ningún
rival, se descartaba igual que si no hubiera encontrado nada.

Causa raíz: el respaldo estructurado no tenía un segundo nivel de
aceptación para "único candidato total, sin número en la etiqueta" --
sólo "único candidato CON número". Corregido en
`atlas_core.rutas.destino_entrega._candidato_unico_con_numero_de_calle`;
sigue exigiendo exactamente la misma corroboración territorial que ya
exigía cualquier candidato de este respaldo (nunca "único total" solo).

Los tests de este archivo usan direcciones y comunas sintéticas (nunca
"Helsinski"/"La Reina" literalmente, salvo el test end-to-end que
reproduce la estructura exacta del caso real 472339 con valores
sintéticos) para probar la regla GENERAL."""
from __future__ import annotations

from atlas_core.catalogo_destinos import Destino
from atlas_core.rutas.destino_entrega import (
    calcular_ruta_con_planta_conocida,
    resolver_destino_con_fallback_estructurado,
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


def _candidato(lat, lon, etiqueta="Candidato", confianza=0.9, localidad="", region=""):
    return CandidatoGeocodificacion(Coordenadas(lon, lat), etiqueta, confianza, localidad, region)


def _proveedor_fallback(candidatos, *, consulta):
    return ProveedorRutasSimulado(geocodificaciones={
        consulta: ResultadoGeocodificacion(EstadoRuta.RESULTADO_AMBIGUO, candidatos, "MULTIPLES_CANDIDATOS"),
    })


# ============================================================
# A -- dirección urbana normal -> camino rápido (principal resuelve solo)
# ============================================================


def test_a_dirreccion_urbana_normal_resuelve_con_el_principal_sin_fallback(tmp_path):
    consulta = "AV. LAS ROSAS 1200 NUNOA, Chile"
    principal = ProveedorRutasSimulado(geocodificaciones={
        consulta: ResultadoGeocodificacion(
            EstadoRuta.REQUIERE_REVISION,
            (_candidato(-33.45, -70.60, "Av. Las Rosas 1200, Ñuñoa", 0.9, "Ñuñoa", "Metropolitana"),),
            "REQUIERE_CONFIRMACION_HUMANA",
        )
    })
    llamadas_fallback = []
    fallback = ProveedorRutasSimulado(geocodificaciones={})
    fallback.geocodificar = lambda d: (llamadas_fallback.append(d) or ResultadoGeocodificacion(EstadoRuta.DIRECCION_NO_ENCONTRADA))
    resultado = resolver_destino_entrega(
        "AV. LAS ROSAS 1200 NUNOA", principal, proveedor_geocodificacion_fallback=fallback,
    )
    assert resultado.estado == "RESUELTO"
    assert llamadas_fallback == []  # nunca gasta el respaldo si el principal ya resolvió


# ============================================================
# B -- typo/calle sin número en el respaldo + único candidato -> resuelve
# ============================================================


def test_b_unico_candidato_de_respaldo_sin_numero_en_la_etiqueta_resuelve_con_corroboracion():
    """Reproduce la causa real: el respaldo ubica la CALLE pero no trae
    el número en su etiqueta -- antes se descartaba igual que "ningún
    candidato"; ahora, siendo el ÚNICO total y con corroboración
    territorial (la comuna aparece en el propio texto documental),
    resuelve."""
    texto = "PASAJE VENTISCA 5810 NUNOA SANTIAGO"
    candidato_sin_numero = _candidato(-33.45, -70.57, "Ventisca", 0.2, "Ñuñoa", "Metropolitana")
    fallback = _proveedor_fallback((candidato_sin_numero,), consulta=f"{texto}, Chile")
    r = resolver_destino_con_fallback_estructurado(texto, proveedor_fallback=fallback)
    assert r.resuelto is True
    assert r.candidato == candidato_sin_numero
    assert r.motivo == "FALLBACK_ESTRUCTURADO_CORROBORADO"


def test_b_sin_corroboracion_territorial_el_candidato_solitario_sin_numero_no_basta():
    """Control -- mismo escenario, pero la comuna del candidato NUNCA
    aparece en el texto documental ni hay destino confirmado/evidencia
    B1: "único total" por sí solo sigue sin ser evidencia inequívoca."""
    texto = "PASAJE VENTISCA 5810"
    candidato_sin_numero = _candidato(-33.45, -70.57, "Ventisca", 0.2, "Comuna Lejana", "Metropolitana")
    fallback = _proveedor_fallback((candidato_sin_numero,), consulta=f"{texto}, Chile")
    r = resolver_destino_con_fallback_estructurado(texto, proveedor_fallback=fallback)
    assert r.resuelto is False
    assert "FALLBACK_SIN_CORROBORACION_TERRITORIAL" in r.motivo


def test_b_candidato_solitario_sin_localidad_tampoco_basta():
    """Un candidato sin NINGÚN dato de localidad no es evidencia -- no se
    puede corroborar territorialmente algo vacío."""
    texto = "PASAJE VENTISCA 5810"
    candidato_vacio = _candidato(-33.45, -70.57, "Ventisca", 0.2, "", "")
    fallback = _proveedor_fallback((candidato_vacio,), consulta=f"{texto}, Chile")
    r = resolver_destino_con_fallback_estructurado(texto, proveedor_fallback=fallback)
    assert r.resuelto is False
    assert r.motivo == "FALLBACK_SIN_CANDIDATO_UNICO"


# ============================================================
# C -- dos candidatos plausibles -> nunca adivina
# ============================================================


def test_c_dos_candidatos_de_respaldo_sin_numero_ninguno_es_unico_no_adivina():
    """Dos candidatos, ninguno con número en la etiqueta -- "único total"
    ya no aplica (hay dos) y ninguno calza por número: se abstiene,
    igual que la ambigüedad real de calles homónimas."""
    texto = "PASAJE VENTISCA 5810 NUNOA"
    a = _candidato(-33.45, -70.57, "Ventisca", 0.3, "Ñuñoa", "Metropolitana")
    b = _candidato(-33.10, -70.90, "Ventisca", 0.3, "Providencia", "Metropolitana")
    fallback = _proveedor_fallback((a, b), consulta=f"{texto}, Chile")
    r = resolver_destino_con_fallback_estructurado(texto, proveedor_fallback=fallback)
    assert r.resuelto is False
    assert r.candidato is None


# ============================================================
# D -- punto dentro de predio + acceso vial verificable -> routing
# (reproduce la estructura completa del caso real 472339)
# ============================================================


def test_d_e2e_472339_centroide_sin_acceso_vial_pero_respaldo_encuentra_calle_ruteable(tmp_path):
    """Reproduce, con valores sintéticos, la estructura exacta del caso
    real: el principal resuelve DOS centroides genéricos de la misma
    comuna (mismo criterio ya calibrado, Coronel/Biobío) -- el punto
    elegido no tiene acceso vial; el respaldo ubica la calle real (sin
    número en su etiqueta) corroborada por la comuna mencionada en el
    propio texto documental -- el reintento de ruteo sobre ESE punto sí
    calcula ruta."""
    from atlas_core.catalogo_plantas import CatalogoPlantas, EstadoCalidad

    plantas = CatalogoPlantas(tmp_path / "plantas.json")
    planta = plantas.crear(
        nombre="PLANTA DEMO", pais="CHILE", fuente="TEST",
        direccion="CAMINO DEMO 1", comuna="RENCA", region="RM",
        latitud=-33.40, longitud=-70.68, estado_calidad=EstadoCalidad.CONFIRMADA,
    )
    texto = "PASAJE VENTISCA 5810 NUNOA SANTIAGO"
    consulta = f"{texto}, Chile"
    centroide_a = Coordenadas(-70.516, -33.4596)
    centroide_b = Coordenadas(-70.5357, -33.4485)  # >1km del anterior, misma comuna declarada
    punto_calle_real = Coordenadas(-70.5705, -33.4565)  # el que SÍ tiene acceso vial

    class _ProveedorPrincipalCentroideSinAcceso:
        nombre = "principal_simulado"
        version = "1"

        def geocodificar(self, direccion):
            return ResultadoGeocodificacion(
                EstadoRuta.RESULTADO_AMBIGUO,
                (
                    _candidato(centroide_a.latitud, centroide_a.longitud, "Ñuñoa, RM, Chile", 0.6, "Ñuñoa", "Metropolitana"),
                    _candidato(centroide_b.latitud, centroide_b.longitud, "Ñuñoa, RM, Chile", 0.6, "Ñuñoa", "Metropolitana"),
                ),
                "MULTIPLES_CANDIDATOS",
            )

        def calcular_ruta(self, origen, destino, perfil):
            if (round(destino.longitud, 4), round(destino.latitud, 4)) == (round(punto_calle_real.longitud, 4), round(punto_calle_real.latitud, 4)):
                return ResultadoRuta(EstadoRuta.RUTA_CALCULADA, 12.3, 20.0, "SINTETICO")
            return ResultadoRuta(EstadoRuta.SIN_ACCESO_VIAL, motivo="SIN_ACCESO_VIAL")

    fallback = _proveedor_fallback(
        (_candidato(punto_calle_real.latitud, punto_calle_real.longitud, "Ventisca", 0.2, "Ñuñoa", "Metropolitana"),),
        consulta=consulta,
    )
    resultado = calcular_ruta_con_planta_conocida(
        planta=planta, despachar_a_crudo=texto,
        proveedor_rutas=_ProveedorPrincipalCentroideSinAcceso(),
        proveedor_geocodificacion_fallback=fallback,
    )
    assert resultado.estado_ruta == "RUTA_CALCULADA"
    assert resultado.distancia_km == "12.3"
    assert resultado.metodo_confirmacion_destino == "FALLBACK_ESTRUCTURADO_SIN_ACCESO_VIAL"


# ============================================================
# E -- dirección realmente irresoluble -> causa final explícita
# ============================================================


def test_e_direccion_irresoluble_sin_ningun_candidato_conserva_causa_explicita(tmp_path):
    """Ni el principal ni el respaldo encuentran nada usable -- la
    ambigüedad/ausencia se conserva con un motivo explícito, nunca un
    `SIN_ACCESO_VIAL` genérico sin explicación agotada."""
    from atlas_core.catalogo_plantas import CatalogoPlantas, EstadoCalidad

    plantas = CatalogoPlantas(tmp_path / "plantas.json")
    planta = plantas.crear(
        nombre="PLANTA DEMO", pais="CHILE", fuente="TEST",
        direccion="CAMINO DEMO 1", comuna="RENCA", region="RM",
        latitud=-33.40, longitud=-70.68, estado_calidad=EstadoCalidad.CONFIRMADA,
    )
    texto = "CALLE INEXISTENTE 999 NINGUNA COMUNA"

    class _ProveedorSinNada:
        nombre = "principal_simulado"
        version = "1"

        def geocodificar(self, direccion):
            return ResultadoGeocodificacion(EstadoRuta.DIRECCION_NO_ENCONTRADA, (), "SIN_RESULTADOS")

        def calcular_ruta(self, origen, destino, perfil):
            return ResultadoRuta(EstadoRuta.SIN_ACCESO_VIAL, motivo="SIN_ACCESO_VIAL")

    fallback = ProveedorRutasSimulado(geocodificaciones={})
    fallback.geocodificar = lambda d: ResultadoGeocodificacion(EstadoRuta.DIRECCION_NO_ENCONTRADA)

    resultado = calcular_ruta_con_planta_conocida(
        planta=planta, despachar_a_crudo=texto,
        proveedor_rutas=_ProveedorSinNada(), proveedor_geocodificacion_fallback=fallback,
    )
    assert resultado.estado_ruta == "REQUIERE_REVISION"
    assert resultado.motivo_ruta  # causa explícita, nunca vacía
    assert resultado.motivo_ruta != "SIN_ACCESO_VIAL"
