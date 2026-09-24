"""P0: promoción automática sólo con evidencia geográfica fuerte."""

from dataclasses import replace
from datetime import datetime, timezone

import pytest

from atlas_core.catalogo_clientes import CatalogoClientes
from atlas_core.catalogo_destinos import CatalogoDestinos, Destino, EstadoCalidadDestino, EstadoVigenciaDestino, normalizar_nombre_destino
from atlas_core.rutas.coordenada_canonica_automatica import (
    DecisionCoordenadaCanonica,
    evaluar_coordenada_canonica_automatica,
    promover_evaluacion_automatica,
)
from atlas_core.rutas.modelos import CandidatoGeocodificacion, Coordenadas, EstadoRuta, ResultadoGeocodificacion


def _destino(*, estado="CONFIRMADO", direccion="AVENIDA EJEMPLO 123, LAMPA"):
    ahora = datetime(2026, 9, 21, tzinfo=timezone.utc).isoformat()
    return Destino(
        destino_id="d-1", cliente_id="", nombre_destino="OBRA PRUEBA",
        nombre_normalizado=normalizar_nombre_destino("OBRA PRUEBA"), codigo_destino="",
        direccion=direccion, comuna="LAMPA", region="RM", pais="CHILE",
        latitud=None, longitud=None, aliases=(), estado_calidad=estado,
        estado_vigencia=EstadoVigenciaDestino.ACTIVO.value, fuente="PRUEBA", observacion="",
        fecha_creacion=ahora, fecha_modificacion=ahora,
    )


def _resultado(*candidatos):
    return ResultadoGeocodificacion(EstadoRuta.REQUIERE_REVISION, tuple(candidatos))


def _candidato(etiqueta="Avenida Ejemplo 123", localidad="Lampa", confianza=0.8):
    return CandidatoGeocodificacion(Coordenadas(-70.8, -33.3), etiqueta, confianza, localidad, "Metropolitana")


def test_candidato_fuerte_unico_es_autoresoluble_y_lleva_preview():
    evaluacion = evaluar_coordenada_canonica_automatica(
        destino=_destino(), resultado=_resultado(_candidato()), fuente="openrouteservice",
        guias_afectadas=("1", "2", "2"),
    )

    assert evaluacion.decision == DecisionCoordenadaCanonica.AUTORESOLVIBLE_CON_NUEVA_POLITICA
    assert evaluacion.preview.viajes_afectados == 2
    assert evaluacion.preview.acciones == ("CONFIRMAR_UBICACION", "RECHAZAR_CANDIDATO", "DECIDIR_DESPUES")


@pytest.mark.parametrize("candidatos,motivo", [
    ((_candidato("Lampa, RM, Chile"),), "GEOCODIFICACION_DEMASIADO_GENERICA"),
    ((_candidato(), _candidato("Avenida Ejemplo 123 bis")), "MULTIPLES_CANDIDATOS(2)"),
    ((_candidato("Avenida Ejemplo 999"),), "GEOCODIFICACION_NUMERO_INCOMPATIBLE"),
    ((_candidato(localidad="Temuco"),), "GEOCODIFICACION_CONTRADICE_COMUNA_CANONICA"),
])
def test_evidencia_debil_o_contradictoria_nunca_se_promueve(candidatos, motivo):
    evaluacion = evaluar_coordenada_canonica_automatica(
        destino=_destino(), resultado=_resultado(*candidatos), fuente="ors",
    )
    assert evaluacion.decision == DecisionCoordenadaCanonica.REQUIERE_CONFIRMACION
    assert motivo in evaluacion.motivo


def test_destino_no_confirmado_no_adquiere_autoridad():
    evaluacion = evaluar_coordenada_canonica_automatica(
        destino=_destino(estado=EstadoCalidadDestino.PENDIENTE.value),
        resultado=_resultado(_candidato()), fuente="ors",
    )
    assert evaluacion.decision == DecisionCoordenadaCanonica.SIGUE_REQUIRIENDO_MEJORA
    assert evaluacion.preview is None


def test_promocion_rechaza_evaluacion_no_autorizada(tmp_path):
    cliente = CatalogoClientes(tmp_path / "clientes.json").crear(razon_social="Cliente", fuente="PRUEBA")
    catalogo = CatalogoDestinos(tmp_path / "destinos.json", ruta_clientes=tmp_path / "clientes.json")
    destino = catalogo.crear(cliente_id=cliente.cliente_id, nombre_destino="Obra", direccion="Avenida Ejemplo 123, Lampa", pais="CHILE", fuente="PRUEBA")
    catalogo.editar(destino.destino_id, estado_calidad="CONFIRMADO", modificacion_manual=True)
    evaluacion = evaluar_coordenada_canonica_automatica(
        destino=_destino(direccion=destino.direccion),
        resultado=_resultado(_candidato("Lampa, RM, Chile")), fuente="ors",
    )
    with pytest.raises(ValueError, match="no autoriza"):
        promover_evaluacion_automatica(catalogo, evaluacion, proveedor="ors", referencia="test")


def test_promocion_autorizada_deja_fuente_auditable(tmp_path):
    clientes = tmp_path / "clientes.json"
    cliente = CatalogoClientes(clientes).crear(razon_social="Cliente", fuente="PRUEBA")
    catalogo = CatalogoDestinos(tmp_path / "destinos.json", ruta_clientes=clientes)
    creado = catalogo.crear(
        cliente_id=cliente.cliente_id, nombre_destino="Obra", pais="CHILE",
        direccion="Avenida Ejemplo 123, Lampa", comuna="Lampa", fuente="PRUEBA",
    )
    confirmado = catalogo.editar(creado.destino_id, estado_calidad="CONFIRMADO", modificacion_manual=True)
    evaluacion = evaluar_coordenada_canonica_automatica(
        destino=replace(_destino(), destino_id=confirmado.destino_id, direccion=confirmado.direccion),
        resultado=_resultado(_candidato()), fuente="ors",
    )
    promovido = promover_evaluacion_automatica(catalogo, evaluacion, proveedor="ors", referencia="prueba")
    assert promovido.fuente == "COORDENADA_CANONICA_EVIDENCIA_FUERTE"
    assert "proveedor=ors" in promovido.observacion
