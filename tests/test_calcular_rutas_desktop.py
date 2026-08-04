from atlas_core.rutas import CalculadorRutas, EstadoRuta, ProveedorRutasSimulado
from calcular_rutas_desktop import calcular_fila, _indice_destinos, _indice_plantas
from atlas_core.catalogo_plantas import Planta
from atlas_core.catalogo_destinos import Destino


BASE = {
    "fuente": "PRUEBA", "observacion": "", "fecha_creacion": "2026-08-04T00:00:00+00:00",
    "fecha_modificacion": "2026-08-04T00:00:00+00:00",
}


def _planta(**cambios):
    datos = dict(planta_id="P1", nombre="AZA RENCA", nombre_normalizado="AZA RENCA",
                 direccion="Calle 1", comuna="Renca", region="RM", pais="Chile",
                 latitud=-33.4, longitud=-70.7, estado_calidad="CONFIRMADA",
                 estado_vigencia="ACTIVA", **BASE)
    return Planta(**{**datos, **cambios})


def _destino(**cambios):
    datos = dict(destino_id="D1", cliente_id="C1", nombre_destino="OBRA NORTE",
                 nombre_normalizado="OBRA NORTE", codigo_destino="", direccion="Calle 2",
                 comuna="Colina", region="RM", pais="Chile", latitud=-33.2,
                 longitud=-70.6, aliases=("NORTE",), estado_calidad="CONFIRMADO",
                 estado_vigencia="ACTIVO", **BASE)
    return Destino(**{**datos, **cambios})


def _calcular(fila, *, planta=None, destino=None, proveedor=None):
    return calcular_fila(
        {"viaje_id": "V1", "origenes": "AZA RENCA", "obras_destino": "OBRA NORTE", **fila},
        plantas=_indice_plantas([planta or _planta()]),
        destinos=_indice_destinos([destino or _destino()]),
        calculador=CalculadorRutas(proveedor or ProveedorRutasSimulado()),
    )


def test_calcula_kilometros_y_tiempo_con_entidades_confirmadas():
    resultado = _calcular({})
    assert resultado == {
        "viaje_id": "V1", "estado": "CALCULADO", "distancia_km": 12.5,
        "tiempo_estimado": "24 min", "proveedor": "simulado", "motivo": "ruta calculada",
    }


def test_alias_de_destino_reutiliza_identidad_canonica():
    resultado = _calcular({"obras_destino": "NORTE"})
    assert resultado["estado"] == "CALCULADO"


def test_informa_direccion_y_coordenadas_faltantes_sin_llamar_proveedor():
    proveedor = ProveedorRutasSimulado()
    sin_direccion = _calcular({}, destino=_destino(direccion=""), proveedor=proveedor)
    sin_coordenadas = _calcular({}, planta=_planta(latitud=None, longitud=None), proveedor=proveedor)
    assert sin_direccion["motivo"] == "destino sin dirección completa"
    assert sin_coordenadas["motivo"] == "coordenadas de origen inexistentes"
    assert proveedor.llamadas_ruta == 0


def test_informa_origen_ambiguo_y_destino_no_confirmado():
    assert _calcular({"origenes": "AZA RENCA | AZA COLINA"})["motivo"] == "origen ambiguo"
    assert _calcular({"obras_destino": "DESCONOCIDO"})["motivo"] == "destino no confirmado en catálogo"


def test_proveedor_no_disponible_no_publica_metricas():
    proveedor = ProveedorRutasSimulado()
    proveedor.resultado_ruta = proveedor.resultado_ruta.__class__(
        EstadoRuta.SIN_CONEXION, motivo="SIN_CONEXION"
    )
    resultado = _calcular({}, proveedor=proveedor)
    assert resultado["estado"] == "NO_DISPONIBLE"
    assert resultado["distancia_km"] is None
    assert resultado["motivo"] == "proveedor no disponible"
