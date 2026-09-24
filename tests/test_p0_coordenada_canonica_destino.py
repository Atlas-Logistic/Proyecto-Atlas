"""P0 Geografia: coordenada canónica confirmada, sin acceso a G."""

from datetime import datetime, timezone

from atlas_core.catalogo_destinos import (
    CatalogoDestinos,
    Destino,
    EstadoCalidadDestino,
    EstadoVigenciaDestino,
    normalizar_nombre_destino,
)
from atlas_core.catalogo_clientes import CatalogoClientes
from atlas_core.catalogo_plantas import CatalogoPlantas, EstadoCalidad
from atlas_core.rutas.destino_entrega import (
    FUENTE_COORDENADA_CANONICA_CONFIRMADA,
    calcular_ruta_entrega_para_viaje,
    plan_impacto_coordenada_canonica,
    revalidar_coordenada_canonica_focal,
)
from atlas_core.rutas.modelos import Coordenadas, EstadoRuta
from atlas_core.rutas.proveedor import ProveedorRutasSimulado


NOVICIADO = "CAM. EL NOVICIADO LAMPA LAMPA"
GUIAS_NOVICIADO = ("464746", "473149", "473324", "474064")
TEXTO_RENCA = "GUIA DESPACHO PLANTA ORIGEN RENCA ACEROS AZA S A"


def _destino(*, direccion=NOVICIADO, estado="CONFIRMADO", latitud=-33.25,
              longitud=-70.88, fuente=FUENTE_COORDENADA_CANONICA_CONFIRMADA):
    ahora = datetime(2026, 9, 17, tzinfo=timezone.utc).isoformat()
    return Destino(
        destino_id="destino-noviciado", cliente_id="cliente-mena",
        nombre_destino="OBRA NOVICIADO",
        nombre_normalizado=normalizar_nombre_destino("OBRA NOVICIADO"),
        codigo_destino="", direccion=direccion, comuna="LAMPA", region="RM",
        pais="CHILE", latitud=latitud, longitud=longitud, aliases=(),
        estado_calidad=estado, estado_vigencia=EstadoVigenciaDestino.ACTIVO.value,
        fuente=fuente, observacion="COORDENADA_CANONICA_CONFIRMADA actor=prueba",
        fecha_creacion=ahora, fecha_modificacion=ahora,
    )


def _plantas(tmp_path):
    catalogo = CatalogoPlantas(tmp_path / "plantas.json")
    catalogo.crear(
        nombre="AZA RENCA", pais="CHILE", fuente="PRUEBA",
        direccion="LA UNION 3070", comuna="RENCA", region="RM",
        latitud=-33.401595, longitud=-70.685226,
        estado_calidad=EstadoCalidad.CONFIRMADA,
    )
    return catalogo.listar()


def _ruta(tmp_path, proveedor, destino, texto=NOVICIADO):
    return calcular_ruta_entrega_para_viaje(
        despachar_a_crudo=texto, patente=None, instante_salida=None,
        plantas=_plantas(tmp_path), proveedor_posicion=None,
        proveedor_rutas=proveedor, textos_documento=[TEXTO_RENCA],
        destinos_confirmados=[destino],
    )


def test_noviciado_canonico_reutiliza_una_coordenada_en_cuatro_guias(tmp_path):
    """Caso de aceptación: 4 guías, 0 geocodificaciones independientes."""
    destino = _destino()
    proveedor = ProveedorRutasSimulado()

    resultados = [_ruta(tmp_path / guia, proveedor, destino) for guia in GUIAS_NOVICIADO]

    assert [r.estado_ruta for r in resultados] == [EstadoRuta.RUTA_CALCULADA.value] * 4
    assert {(r.longitud_entrega, r.latitud_entrega) for r in resultados} == {("-70.88", "-33.25")}
    assert {r.metodo_confirmacion_destino for r in resultados} == {"COORDENADA_CANONICA_CATALOGO"}
    assert proveedor.llamadas_geocodificacion == 0
    assert proveedor.llamadas_ruta == 4


def test_plan_impacto_y_revalidacion_solo_tocan_guias_exactas():
    destino = _destino()
    filas = [
        {"numero_guia": guia, "despachar_a_crudo": NOVICIADO}
        for guia in GUIAS_NOVICIADO
    ] + [
        {"numero_guia": "NO-TOCAR", "despachar_a_crudo": NOVICIADO + " 2"},
    ]
    vistas = []

    plan, resultados = revalidar_coordenada_canonica_focal(
        destino=destino, filas=filas,
        revalidador=lambda fila: vistas.append(fila["numero_guia"]) or fila["numero_guia"],
    )

    assert plan == plan_impacto_coordenada_canonica(destino=destino, filas=filas)
    assert plan.guias == GUIAS_NOVICIADO
    assert vistas == list(GUIAS_NOVICIADO)
    assert resultados == GUIAS_NOVICIADO


def test_similar_pendiente_o_invalido_siguen_el_flujo_existente(tmp_path):
    proveedor = ProveedorRutasSimulado()
    # Misma familia textual, pero no coincidencia exacta: debe consultar geocoder.
    _ruta(tmp_path / "similar", proveedor, _destino(), NOVICIADO + " 2")
    assert proveedor.llamadas_geocodificacion == 1

    # Un destino pendiente, aunque contenga coordenadas, no gana autoridad.
    _ruta(tmp_path / "pendiente", proveedor, _destino(estado=EstadoCalidadDestino.PENDIENTE.value))
    assert proveedor.llamadas_geocodificacion == 2

    # Objeto inválido legado: el guard defensivo lo rechaza y conserva el flujo actual.
    _ruta(tmp_path / "invalido", proveedor, _destino(latitud=999.0))
    assert proveedor.llamadas_geocodificacion == 3

    _ruta(tmp_path / "ausente", proveedor, _destino(latitud=None, longitud=None))
    assert proveedor.llamadas_geocodificacion == 4


def test_confirmacion_persiste_procedencia_en_catalogo_temporal(tmp_path):
    ruta_clientes = tmp_path / "clientes.json"
    cliente = CatalogoClientes(ruta_clientes).crear(
        razon_social="CLIENTE PRUEBA", fuente="PRUEBA"
    )
    catalogo = CatalogoDestinos(tmp_path / "destinos.json", ruta_clientes=ruta_clientes)
    destino = catalogo.crear(
        cliente_id=cliente.cliente_id, nombre_destino="OBRA NOVICIADO",
        direccion=NOVICIADO, comuna="LAMPA", region="RM", pais="CHILE",
        fuente="PRUEBA",
    )
    catalogo.editar(
        destino.destino_id, estado_calidad=EstadoCalidadDestino.CONFIRMADO.value,
        modificacion_manual=True,
    )

    confirmado = catalogo.confirmar_coordenada_canonica(
        destino.destino_id, latitud=-33.25, longitud=-70.88,
        actor="javier", referencia="prueba-sintetica",
    )

    assert confirmado.fuente == FUENTE_COORDENADA_CANONICA_CONFIRMADA
    assert "actor=javier" in confirmado.observacion
    assert catalogo.obtener(destino.destino_id) == confirmado
