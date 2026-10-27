from types import SimpleNamespace

import pytest
import atlas_core.revalidacion_documental as modulo
from atlas_core.catalogo_plantas import CatalogoPlantas, EstadoCalidad
from atlas_core.rutas.modelos import Coordenadas, EstadoRuta, ResultadoRuta
from atlas_core.rutas.proveedor import ProveedorRutasSimulado
from tests.test_final_core_v1 import _escribir_csv, _fila_csv, _leer_csv


@pytest.mark.parametrize('texto', [
    'PANAMERICANA NORTE 22650 SANTIAGO LAMPA RUTCHOFER',
    'PANAMERICANA 22650 rut chofer: 123',
    'PANAMERICANA 22650 OBRADESTINO TEST',
    'PANAMERICANA 22650 CODDESTINATARIO 42',
    'PANAMERICANA 22650 HORA SALIDA 12:00',
    'PANAMERICANA 22650 RETIRA JUAN',
])
def test_detecta_etiqueta_residual(texto):
    assert modulo._destino_con_etiqueta_residual_convergencia(texto)


@pytest.mark.parametrize('texto', [
    'PANAMERICANA NORTE 22650 SANTIAGO LAMPA',
    'AVENIDA LOS TRANSPORTISTAS 123 RENCA',
    'CALLE EL RETIRO 345 SANTIAGO',
    'AVENIDA CIUDAD DE CALERA 123',
    'CALLE RUTCHOFERIA 123',
    'LA ESTERA 525 COLINA',
])
def test_direcciones_legitimas_no_se_bloquean(texto):
    assert not modulo._destino_con_etiqueta_residual_convergencia(texto)


def test_483223_no_hereda_convergencia_de_direcciones_limpias(tmp_path, monkeypatch):
    carpeta = tmp_path / 'catalogos'
    carpeta.mkdir()
    planta = CatalogoPlantas(carpeta / 'plantas.json').crear(
        nombre='AZA COLINA', pais='CHILE', fuente='TEST', direccion='TEST', comuna='COLINA',
        region='RM', latitud=-33.294752, longitud=-70.730387, estado_calidad=EstadoCalidad.CONFIRMADA)
    limpia = 'PANAMERICANA NORTE 22650 SANTIAGO LAMPA'
    contaminada = limpia + ' RUTCHOFER'
    dataset = tmp_path / 'dataset.csv'
    _escribir_csv(dataset, [_fila_csv(archivo=f'{i}.jpeg', numero_guia=num,
        fecha=f'{18+i:02d}-08-2026', planta_origen_id=planta.planta_id, despachar_a_crudo=direccion)
        for i, (num, direccion) in enumerate([('483223', contaminada), ('1', limpia), ('2', limpia)])])
    antes = {f['numero_guia']: f for f in _leer_csv(dataset)}
    pendientes = tmp_path / 'pendientes.json'
    pendientes.write_text('[{"guia":"483223","estado":"PENDIENTE"}]', encoding='utf-8')
    original = pendientes.read_bytes()
    monkeypatch.setattr(modulo, 'enriquecer_documento_con_telemetria', lambda **kwargs:
        SimpleNamespace(punto_gps_destino=Coordenadas(-70.65, -33.35)))
    servicio = SimpleNamespace(proveedor=SimpleNamespace(nombre='test'),
        repositorio=SimpleNamespace(buscar_viajes=lambda *args: (object(),)))
    proveedor = ProveedorRutasSimulado(resultado_ruta=ResultadoRuta(EstadoRuta.RUTA_CALCULADA, 8, 12, 'TEST'))
    resultado = modulo.revalidar_ruta_por_convergencia_gps_historica_sin_ocr(
        ruta_dataset=dataset, carpeta_catalogos=carpeta, proveedor_rutas=proveedor, servicio_telemetria=servicio)
    despues = {f['numero_guia']: f for f in _leer_csv(dataset)}
    assert set(resultado['guias_actualizadas']) == {'1', '2'}
    assert despues['483223'] == antes['483223']
    assert all(despues[g]['estado_ruta'] == 'RUTA_CALCULADA' for g in ('1', '2'))
    assert pendientes.read_bytes() == original


def test_solo_contaminadas_no_rutea_ni_aprende(tmp_path, monkeypatch):
    # Aunque hubiera dos observaciones convergentes, no se usan para confirmar el destino.
    carpeta = tmp_path / 'catalogos'
    carpeta.mkdir()
    planta = CatalogoPlantas(carpeta / 'plantas.json').crear(nombre='AZA', pais='CHILE', fuente='TEST',
        direccion='TEST', comuna='COLINA', region='RM', latitud=-33.29, longitud=-70.73,
        estado_calidad=EstadoCalidad.CONFIRMADA)
    dataset = tmp_path / 'dataset.csv'
    _escribir_csv(dataset, [_fila_csv(archivo=f'{i}.jpeg', numero_guia=str(i), fecha=f'{18+i:02d}-08-2026',
        planta_origen_id=planta.planta_id, despachar_a_crudo='PANAMERICANA 22650 RUTCHOFER') for i in range(2)])
    antes = dataset.read_bytes()
    servicio = SimpleNamespace(proveedor=SimpleNamespace(nombre='test'),
        repositorio=SimpleNamespace(buscar_viajes=lambda *args: (object(),)))
    proveedor = ProveedorRutasSimulado(resultado_ruta=ResultadoRuta(EstadoRuta.RUTA_CALCULADA, 8, 12, 'TEST'))
    resultado = modulo.revalidar_ruta_por_convergencia_gps_historica_sin_ocr(
        ruta_dataset=dataset, carpeta_catalogos=carpeta, proveedor_rutas=proveedor, servicio_telemetria=servicio)
    assert resultado == {'guias_actualizadas': [], 'destinos_aprendidos': []}
    assert dataset.read_bytes() == antes
