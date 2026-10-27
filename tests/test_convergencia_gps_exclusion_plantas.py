from types import SimpleNamespace

import atlas_core.revalidacion_documental as revalidacion
from atlas_core.catalogo_plantas import CatalogoPlantas, EstadoCalidad
from atlas_core.rutas.modelos import Coordenadas, EstadoRuta, ResultadoRuta
from atlas_core.rutas.proveedor import ProveedorRutasSimulado
from tests.test_final_core_v1 import _escribir_csv, _fila_csv, _leer_csv


class ProveedorRegistrado(ProveedorRutasSimulado):
    def __init__(self):
        super().__init__(resultado_ruta=ResultadoRuta(EstadoRuta.RUTA_CALCULADA, 8.0, 12.0, "TEST"))
        self.destinos = []

    def calcular_ruta(self, origen, destino, perfil):
        self.destinos.append(destino)
        return super().calcular_ruta(origen, destino, perfil)


def ejecutar(tmp_path, monkeypatch, puntos):
    carpeta = tmp_path / 'catalogos'
    carpeta.mkdir()
    catalogo = CatalogoPlantas(carpeta / 'plantas.json')
    origen = catalogo.crear(nombre='AZA ORIGEN', pais='CHILE', fuente='TEST', direccion='TEST',
        comuna='TEST', region='RM', latitud=-33.4, longitud=-70.8, estado_calidad=EstadoCalidad.CONFIRMADA)
    catalogo.crear(nombre='AZA COLINA', pais='CHILE', fuente='TEST', direccion='TEST',
        comuna='TEST', region='RM', latitud=-33.137558, longitud=-70.665977,
        estado_calidad=EstadoCalidad.CONFIRMADA, tipo_geocerca='POLIGONAL',
        vertices=[(-33.296, -70.732), (-33.296, -70.728), (-33.293, -70.728), (-33.293, -70.732)])
    dataset = tmp_path / 'dataset.csv'
    filas = [_fila_csv(archivo=f'{i}.jpeg', numero_guia='483223' if i == 0 else str(i),
        fecha=f'{18+i:02d}-08-2026', planta_origen_id=origen.planta_id,
        despachar_a_crudo='PANAMERICANA NORTE 22650 SANTIAGO LAMPA') for i in range(len(puntos))]
    _escribir_csv(dataset, filas)
    pendientes = tmp_path / 'pendientes.json'
    pendientes.write_text('[{"guia":"483223","estado":"PENDIENTE"}]', encoding='utf-8')
    antes = pendientes.read_bytes()
    secuencia = iter(puntos)
    monkeypatch.setattr(revalidacion, 'enriquecer_documento_con_telemetria',
        lambda **kwargs: SimpleNamespace(punto_gps_destino=next(secuencia)))
    servicio = SimpleNamespace(proveedor=SimpleNamespace(nombre='test'),
        repositorio=SimpleNamespace(buscar_viajes=lambda *args: (object(),)))
    proveedor = ProveedorRegistrado()
    resultado = revalidacion.revalidar_ruta_por_convergencia_gps_historica_sin_ocr(
        ruta_dataset=dataset, carpeta_catalogos=carpeta, proveedor_rutas=proveedor, servicio_telemetria=servicio)
    assert pendientes.read_bytes() == antes
    return resultado, proveedor, _leer_csv(dataset)


def test_483223_puntos_en_otra_planta_se_abstiene(tmp_path, monkeypatch):
    planta = Coordenadas(-70.72930, -33.29467)
    resultado, proveedor, filas = ejecutar(tmp_path, monkeypatch, [planta, planta])
    assert resultado == {'guias_actualizadas': [], 'destinos_aprendidos': []}
    assert proveedor.destinos == []
    assert all(f['estado_ruta'] != 'RUTA_CALCULADA' and not f['direccion_entrega'] for f in filas)


def test_excluye_planta_y_converge_en_entregas_validas(tmp_path, monkeypatch):
    planta = Coordenadas(-70.72930, -33.29467)
    entrega = Coordenadas(-70.70, -33.35)
    resultado, proveedor, filas = ejecutar(tmp_path, monkeypatch, [planta, entrega, entrega])
    assert len(resultado['guias_actualizadas']) == 3
    assert proveedor.destinos == [entrega] * 3
    assert all(f['estado_ruta'] == 'RUTA_CALCULADA' for f in filas)


def test_una_sola_entrega_fuera_no_basta(tmp_path, monkeypatch):
    resultado, proveedor, _ = ejecutar(tmp_path, monkeypatch,
        [Coordenadas(-70.72930, -33.29467), Coordenadas(-70.70, -33.35)])
    assert resultado['guias_actualizadas'] == []
    assert proveedor.destinos == []
