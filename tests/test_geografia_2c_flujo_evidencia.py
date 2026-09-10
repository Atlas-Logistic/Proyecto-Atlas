"""GEOGRAFÍA 2C -- la base local PARTICIPA COMO EVIDENCIA en el flujo de
destino (Vía C) antes de declarar un fallo agotado, y la capacidad
GEOGRAFIA avanza para que los pendientes técnicos existentes se
reevalúen.

Contrato de seguridad: la base local sólo AÑADE una corroboración; nunca
resuelve por sí sola, nunca aporta coordenadas, nunca acepta un número
distinto. Sin base provisionada, el comportamiento es byte-idéntico a
2A/2B.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from atlas_core.capacidades_reevaluacion import (
    DOMINIO_GEOGRAFIA,
    REGISTRO_CAPACIDADES,
    capacidades_avanzadas,
    dominios_de_motivo_tecnico,
    versiones_actuales,
)
from atlas_core.geografia.base_local import BaseGeograficaLocalSQLite
from atlas_core.rutas.destino_entrega import (
    VIA_BASE_LOCAL,
    resolver_destino_con_fallback_estructurado,
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

FECHA = datetime(2026, 1, 1, tzinfo=timezone.utc).isoformat()


def _candidato(lat, lon, etiqueta, *, localidad="", region="Metropolitana", confianza=0.9):
    return CandidatoGeocodificacion(
        Coordenadas(lon, lat), etiqueta, confianza, localidad, region
    )


def _fallback(candidatos, consulta="VICUÑA MACKENNA 655, Chile"):
    return ProveedorRutasSimulado(geocodificaciones={
        consulta: ResultadoGeocodificacion(
            EstadoRuta.RESULTADO_AMBIGUO, candidatos, "MULTIPLES_CANDIDATOS"
        ),
    })


def _base(tmp_path, filas=()):
    b = BaseGeograficaLocalSQLite(tmp_path / "base.sqlite")
    if filas:
        b.importar_filas(filas)
    return b


# ============================================================
# 1. La base local corrobora un candidato del respaldo que ninguna otra
#    vía podía corroborar
# ============================================================


def test_base_local_corrobora_candidato_sin_otra_evidencia(tmp_path):
    """Caso tipo 472037: el respaldo encuentra "Vicuña Mackenna 655" en
    Maipú, pero no hay destino confirmado, ni evidencia B1, ni el texto
    nombra la comuna. Antes: FALLBACK_SIN_CORROBORACION_TERRITORIAL. Con
    la base local que conoce esa dirección exacta en Maipú -> corrobora."""
    candidatos = (_candidato(-33.52, -70.75, "Vicuña Mackenna 655", localidad="Maipú"),)
    base = _base(tmp_path, [
        {"comuna": "Maipú", "calle": "Vicuña Mackenna", "numero": "655", "fuente": "SEMILLA"},
    ])
    r = resolver_destino_con_fallback_estructurado(
        "VICUÑA MACKENNA 655", proveedor_fallback=_fallback(candidatos),
        base_geografica_local=base,
    )
    assert r.resuelto is True
    assert r.candidato.localidad == "Maipú"
    assert r.motivo == "FALLBACK_ESTRUCTURADO_CORROBORADO_POR_BASE_LOCAL"
    assert VIA_BASE_LOCAL in r.vias


def test_sin_base_local_mismo_caso_sigue_abstiniendose(tmp_path):
    """Control -- sin base local: comportamiento 2A/2B intacto."""
    candidatos = (_candidato(-33.52, -70.75, "Vicuña Mackenna 655", localidad="Maipú"),)
    r = resolver_destino_con_fallback_estructurado(
        "VICUÑA MACKENNA 655", proveedor_fallback=_fallback(candidatos),
    )
    assert r.resuelto is False
    assert "FALLBACK_SIN_CORROBORACION_TERRITORIAL" in r.motivo


def test_base_local_no_provisionada_es_noop(tmp_path):
    """Con la base local declarada pero SIN datos (sin PBF todavía) el
    resultado es idéntico a no pasarla -- no-op estricto."""
    candidatos = (_candidato(-33.52, -70.75, "Vicuña Mackenna 655", localidad="Maipú"),)
    base = _base(tmp_path)  # archivo inexistente
    r = resolver_destino_con_fallback_estructurado(
        "VICUÑA MACKENNA 655", proveedor_fallback=_fallback(candidatos),
        base_geografica_local=base,
    )
    assert r.resuelto is False
    assert "FALLBACK_SIN_CORROBORACION_TERRITORIAL" in r.motivo


# ============================================================
# 2. La base local NUNCA corrobora un número distinto ni otra comuna
# ============================================================


def test_base_local_no_corrobora_si_el_numero_difiere(tmp_path):
    candidatos = (_candidato(-33.52, -70.75, "Vicuña Mackenna 655", localidad="Maipú"),)
    base = _base(tmp_path, [
        {"comuna": "Maipú", "calle": "Vicuña Mackenna", "numero": "1545", "fuente": "SEMILLA"},
    ])
    r = resolver_destino_con_fallback_estructurado(
        "VICUÑA MACKENNA 655", proveedor_fallback=_fallback(candidatos),
        base_geografica_local=base,
    )
    assert r.resuelto is False
    assert "FALLBACK_SIN_CORROBORACION_TERRITORIAL" in r.motivo


def test_base_local_no_corrobora_candidato_en_otra_comuna_pero_ine_resuelve_sola(tmp_path):
    """GEOGRAFÍA 3 -- el candidato del respaldo dice Providencia y no
    corrobora contra la base consultada CON esa comuna; pero la base
    territorial INE conoce esa calle+número como ÚNICA en toda la RM
    (Maipú) -> resuelve por sí misma con su coordenada real, ignorando la
    comuna equivocada del respaldo. Nunca inventa: si estuviera en dos
    comunas, abstención (ver test siguiente)."""
    candidatos = (_candidato(-33.43, -70.61, "Vicuña Mackenna 655", localidad="Providencia"),)
    base = _base(tmp_path, [
        {"comuna": "Maipú", "calle": "Vicuña Mackenna", "numero": "655",
         "ref_externa": "gid=1", "lon": -70.75, "lat": -33.52},
    ])
    r = resolver_destino_con_fallback_estructurado(
        "VICUÑA MACKENNA 655", proveedor_fallback=_fallback(candidatos),
        base_geografica_local=base,
    )
    assert r.resuelto is True
    assert r.motivo == "DIRECCION_EXACTA_BASE_LOCAL_INE"
    assert r.candidato.localidad == "Maipú"
    assert (r.candidato.coordenadas.longitud, r.candidato.coordenadas.latitud) == (-70.75, -33.52)


def test_base_local_se_abstiene_si_la_calle_numero_esta_en_dos_comunas(tmp_path):
    """GEOGRAFÍA 3 -- misma calle+número en DOS comunas -> INE devuelve
    MULTIPLE -> nunca elige; el respaldo tampoco corrobora -> abstención
    intacta."""
    candidatos = (_candidato(-33.43, -70.61, "Vicuña Mackenna 655", localidad="Providencia"),)
    base = _base(tmp_path, [
        {"comuna": "Maipú", "calle": "Vicuña Mackenna", "numero": "655",
         "ref_externa": "gid=1", "lon": -70.75, "lat": -33.52},
        {"comuna": "La Florida", "calle": "Vicuña Mackenna", "numero": "655",
         "ref_externa": "gid=2", "lon": -70.58, "lat": -33.53},
    ])
    r = resolver_destino_con_fallback_estructurado(
        "VICUÑA MACKENNA 655", proveedor_fallback=_fallback(candidatos),
        base_geografica_local=base,
    )
    assert r.resuelto is False
    assert "FALLBACK_SIN_CORROBORACION_TERRITORIAL" in r.motivo


def test_base_local_calle_conocida_sin_el_numero_no_corrobora_si_hay_numero_en_doc(tmp_path):
    candidatos = (_candidato(-33.52, -70.75, "Vicuña Mackenna 655", localidad="Maipú"),)
    base = _base(tmp_path, [
        {"comuna": "Maipú", "calle": "Vicuña Mackenna", "numero": "", "fuente": "SEMILLA"},
    ])
    r = resolver_destino_con_fallback_estructurado(
        "VICUÑA MACKENNA 655", proveedor_fallback=_fallback(candidatos),
        base_geografica_local=base,
    )
    assert r.resuelto is False


# ============================================================
# 3. Integración a través de resolver_destino_entrega (ambiguo)
# ============================================================


def test_resolver_destino_entrega_usa_base_local_para_desambiguar(tmp_path):
    consulta = "VICUÑA MACKENNA 655, Chile"
    principal = ProveedorRutasSimulado(geocodificaciones={
        consulta: ResultadoGeocodificacion(
            EstadoRuta.RESULTADO_AMBIGUO,
            (
                _candidato(-33.52, -70.75, "Vicuña Mackenna 655", localidad="Maipú"),
                _candidato(-36.60, -72.10, "Vicuña Mackenna 655", localidad="Chillán", region="Ñuble"),
            ),
            "MULTIPLES_CANDIDATOS",
        ),
    })
    fallback = _fallback((_candidato(-33.52, -70.75, "Vicuña Mackenna 655", localidad="Maipú"),))
    base = _base(tmp_path, [
        {"comuna": "Maipú", "calle": "Vicuña Mackenna", "numero": "655", "fuente": "SEMILLA"},
    ])
    r = resolver_destino_entrega(
        "VICUÑA MACKENNA 655", principal,
        proveedor_geocodificacion_fallback=fallback,
        base_geografica_local=base,
    )
    assert r.estado == "RESUELTO"
    assert r.localidad == "Maipú"
    assert r.coordenadas == Coordenadas(-70.75, -33.52)


def test_resolver_destino_entrega_sin_base_local_default_none_no_cambia_nada(tmp_path):
    consulta = "VICUÑA MACKENNA 655, Chile"
    principal = ProveedorRutasSimulado(geocodificaciones={
        consulta: ResultadoGeocodificacion(
            EstadoRuta.RESULTADO_AMBIGUO,
            (
                _candidato(-33.52, -70.75, "Vicuña Mackenna 655", localidad="Maipú"),
                _candidato(-36.60, -72.10, "Vicuña Mackenna 655", localidad="Chillán", region="Ñuble"),
            ),
            "MULTIPLES_CANDIDATOS",
        ),
    })
    fallback = _fallback((_candidato(-33.52, -70.75, "Vicuña Mackenna 655", localidad="Maipú"),))
    r = resolver_destino_entrega(
        "VICUÑA MACKENNA 655", principal,
        proveedor_geocodificacion_fallback=fallback,
    )
    assert r.estado == "REVISAR"


# ============================================================
# 3bis. GEOGRAFÍA 3 -- INE rescata un destino que el geocodificador dejó
#       INCOHERENTE con la dirección documental (número / calle / comuna)
# ============================================================


def _principal_confiado(consulta, candidato):
    return ProveedorRutasSimulado(geocodificaciones={
        consulta: ResultadoGeocodificacion(
            EstadoRuta.REQUIERE_REVISION, (candidato,), "OK",
        ),
    })


def test_ine_rescata_destino_con_numero_incompatible_del_geocodificador(tmp_path):
    """El proveedor resuelve, confiado, "VICUÑA MACKENNA 1545" para un
    documento que dice 655 -> la guarda de número lo rechaza; la base INE
    tiene el 655 real -> se acepta ESE, no un pendiente técnico."""
    consulta = "VICUÑA MACKENNA 655, Chile"
    malo = _candidato(-33.49, -70.62, "Vicuña Mackenna 1545, Maipú", localidad="Maipú")
    base = _base(tmp_path, [
        {"comuna": "Maipú", "calle": "Vicuña Mackenna", "numero": "655",
         "ref_externa": "gid=1", "lon": -70.75, "lat": -33.52},
    ])
    r = resolver_destino_entrega_validado(
        "VICUÑA MACKENNA 655", _principal_confiado(consulta, malo),
        base_geografica_local=base,
    )
    assert r.estado == "RESUELTO"
    assert r.coordenadas == Coordenadas(-70.75, -33.52)   # coordenada REAL de INE
    assert r.localidad == "Maipú"
    assert r.metodo_confirmacion == "BASE_LOCAL_INE"


def test_sin_ine_el_numero_incompatible_sigue_siendo_rechazo(tmp_path):
    consulta = "VICUÑA MACKENNA 655, Chile"
    malo = _candidato(-33.49, -70.62, "Vicuña Mackenna 1545, Maipú", localidad="Maipú")
    r = resolver_destino_entrega_validado(
        "VICUÑA MACKENNA 655", _principal_confiado(consulta, malo),
        base_geografica_local=None,
    )
    assert r.estado == "REVISAR"
    assert r.motivo.startswith("GEOCODIFICACION_NUMERO_INCOMPATIBLE")


def test_ine_no_rescata_si_tambien_contradice_la_comuna_documental(tmp_path):
    """La base INE resolvería la calle+número en Maipú, pero el documento
    dice CERRILLOS de forma inequívoca -> el candidato INE pasa por las
    MISMAS guardas y también se rechaza: gana el rechazo original."""
    consulta = "VICUÑA MACKENNA 655 CERRILLOS, Chile"
    malo = _candidato(-33.49, -70.62, "Vicuña Mackenna 1545, Maipú", localidad="Maipú")
    base = _base(tmp_path, [
        {"comuna": "Maipú", "calle": "Vicuña Mackenna", "numero": "655",
         "ref_externa": "gid=1", "lon": -70.75, "lat": -33.52},
    ])
    r = resolver_destino_entrega_validado(
        "VICUÑA MACKENNA 655 CERRILLOS", _principal_confiado(consulta, malo),
        base_geografica_local=base,
    )
    assert r.estado == "REVISAR"


# ============================================================
# 4. La capacidad GEOGRAFIA avanzó -> los pendientes técnicos se reevalúan
# ============================================================


def test_capacidad_geografia_avanzo_a_2_o_mas():
    assert REGISTRO_CAPACIDADES[DOMINIO_GEOGRAFIA].version >= 2


def test_manifiesto_en_geografia_v1_dispara_reevaluacion():
    persistidas = versiones_actuales()
    persistidas[DOMINIO_GEOGRAFIA] = 1
    avanzadas = capacidades_avanzadas(persistidas)
    assert DOMINIO_GEOGRAFIA in avanzadas
    assert avanzadas[DOMINIO_GEOGRAFIA][1] == REGISTRO_CAPACIDADES[DOMINIO_GEOGRAFIA].version


def test_pendientes_geo_siguen_mapeando_a_geografia():
    for motivo in (
        "GEOCODIFICACION_DIRECCION_NO_ENCONTRADA", "COORDENADA_NO_CONFIRMADA(5)",
        "CONFIANZA_INSUFICIENTE", "MULTIPLES_UBICACIONES_DISPERSAS(3)",
    ):
        assert DOMINIO_GEOGRAFIA in dominios_de_motivo_tecnico(motivo)
