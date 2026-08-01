from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace

import pytest

from atlas_core.rutas.modelos import Coordenadas, EstadoRuta
from atlas_core.rutas.proveedor import ProveedorRutasSimulado
from atlas_core.rutas.repositorio import RepositorioRutas
from atlas_core.rutas.servicio import ServicioRutas
from gestionar_catalogos import main


def planta(**cambios):
    datos = dict(planta_id="PLANTA-DEMO", direccion="AVENIDA FICTICIA 100",
                 comuna="COMUNA DEMO", region="REGION DEMO", pais="PAIS DEMO",
                 estado_calidad="CONFIRMADA", estado_vigencia="ACTIVA")
    datos.update(cambios); return SimpleNamespace(**datos)


def destino(**cambios):
    datos = dict(destino_id="DESTINO-DEMO", direccion="AVENIDA FICTICIA 200",
                 comuna="COMUNA DEMO", region="REGION DEMO", pais="PAIS DEMO",
                 estado_calidad="CONFIRMADO", estado_vigencia="ACTIVO")
    datos.update(cambios); return SimpleNamespace(**datos)


def servicio(tmp_path):
    proveedor = ProveedorRutasSimulado()
    return ServicioRutas(proveedor, RepositorioRutas(tmp_path / "rutas.json")), proveedor


def test_preparar_geocodifica_sin_persistir(tmp_path):
    srv, proveedor = servicio(tmp_path)
    resultado = srv.preparar(planta(), destino(), "driving-car")
    assert resultado.estado == EstadoRuta.REQUIERE_REVISION
    assert proveedor.llamadas_geocodificacion == 2
    assert not srv.repositorio.ruta.exists()


def test_confirmacion_calcula_y_persiste_resultado_positivo(tmp_path):
    srv, proveedor = servicio(tmp_path)
    resultado = srv.confirmar_y_calcular(
        planta(), destino(), "driving-car", Coordenadas(-20, -10),
        Coordenadas(-20.1, -10.1), confirmacion_explicita=True,
    )
    assert resultado.estado == EstadoRuta.RUTA_CALCULADA
    assert resultado.ruta.distancia_km > 0
    assert resultado.ruta.duracion_estimada_min > 0
    assert proveedor.llamadas_ruta == 1


def test_segunda_ejecucion_usa_cache_sin_proveedor(tmp_path):
    srv, proveedor = servicio(tmp_path)
    coords = (Coordenadas(-20, -10), Coordenadas(-20.1, -10.1))
    srv.confirmar_y_calcular(planta(), destino(), "driving-car", *coords, confirmacion_explicita=True)
    llamadas = proveedor.llamadas_ruta
    resultado = srv.preparar(planta(), destino(), "driving-car")
    assert resultado.estado == EstadoRuta.RESULTADO_DESDE_CACHE
    assert proveedor.llamadas_ruta == llamadas
    assert proveedor.llamadas_geocodificacion == 0


def test_cambio_de_direccion_invalida_cache(tmp_path):
    srv, proveedor = servicio(tmp_path)
    srv.confirmar_y_calcular(planta(), destino(), "driving-car", Coordenadas(-20, -10), Coordenadas(-20.1, -10.1), confirmacion_explicita=True)
    resultado = srv.preparar(planta(), destino(direccion="CALLE FICTICIA 300"), "driving-car")
    assert resultado.estado == EstadoRuta.REQUIERE_REVISION
    assert proveedor.llamadas_geocodificacion == 2


@pytest.mark.parametrize(("p", "d", "motivo"), [
    (planta(estado_calidad="PENDIENTE"), destino(), "PLANTA_NO_CONFIRMADA"),
    (planta(), destino(estado_calidad="REQUIERE_REVISION"), "DESTINO_NO_CONFIRMADO"),
    (planta(estado_vigencia="INACTIVA"), destino(), "PLANTA_INACTIVA"),
    (planta(), destino(estado_vigencia="INACTIVO"), "DESTINO_INACTIVO"),
    (planta(direccion=""), destino(), "PLANTA_DIRECCION_INCOMPLETA"),
])
def test_rechaza_entidades_no_elegibles(tmp_path, p, d, motivo):
    srv, proveedor = servicio(tmp_path)
    resultado = srv.preparar(p, d, "driving-car")
    assert resultado.motivo == motivo
    assert proveedor.llamadas_geocodificacion == 0


def test_fallo_proveedor_no_persiste(tmp_path):
    proveedor = ProveedorRutasSimulado()
    proveedor.resultado_ruta = proveedor.resultado_ruta.__class__(EstadoRuta.SIN_CONEXION)
    srv = ServicioRutas(proveedor, RepositorioRutas(tmp_path / "rutas.json"))
    resultado = srv.confirmar_y_calcular(planta(), destino(), "driving-car", Coordenadas(-20, -10), Coordenadas(-20.1, -10.1), confirmacion_explicita=True)
    assert resultado.estado == EstadoRuta.SIN_CONEXION
    assert not srv.repositorio.ruta.exists()


def test_servicio_no_modifica_entidades_ni_guarda_clave(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENROUTESERVICE_API_KEY", "SECRETO_DE_PRUEBA")
    p, d = planta(), destino()
    antes = (deepcopy(vars(p)), deepcopy(vars(d)))
    srv, _ = servicio(tmp_path)
    srv.confirmar_y_calcular(p, d, "driving-car", Coordenadas(-20, -10), Coordenadas(-20.1, -10.1), confirmacion_explicita=True)
    assert (vars(p), vars(d)) == antes
    assert "SECRETO_DE_PRUEBA" not in srv.repositorio.ruta.read_text(encoding="utf-8")


def test_cli_anteriores_siguen_disponibles(tmp_path):
    plantas = tmp_path / "plantas.json"
    clientes = tmp_path / "clientes.json"
    assert main(["--archivo", str(plantas), "listar"]) == 0
    assert main(["clientes", "--archivo", str(clientes), "listar"]) == 0


def test_cli_rutas_vacia_no_crea_archivo(tmp_path):
    rutas = tmp_path / "rutas.json"
    assert main(["rutas", "--archivo", str(rutas), "listar"]) == 0
    assert not rutas.exists()
