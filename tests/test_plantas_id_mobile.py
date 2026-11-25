from atlas_core.catalogo_plantas import CatalogoPlantas
from atlas_core.rutas.origen_evidencia import resolver_planta_por_codigo_mobile


def test_origen_mobile_por_id_en_catalogo_de_cada_empresa(tmp_path):
    mbt = CatalogoPlantas(tmp_path / 'mbt.json', generador_id=lambda: 'mbt-id')
    andes = CatalogoPlantas(tmp_path / 'andes.json', generador_id=lambda: 'andes-id')
    a = mbt.crear(nombre='AZA COLINA', pais='Chile', fuente='prueba', estado_calidad='CONFIRMADA')
    b = andes.crear(nombre='Puerto Norte', pais='Chile', fuente='prueba', estado_calidad='CONFIRMADA',
                     direccion='Ruta 5', comuna='Lampa', latitud=-33.2, longitud=-70.8)
    assert resolver_planta_por_codigo_mobile('AZA_COLINA', mbt.listar()) == a
    assert resolver_planta_por_codigo_mobile('andes-id', andes.listar()) == b
    assert resolver_planta_por_codigo_mobile('andes-id', mbt.listar()) is None
    assert resolver_planta_por_codigo_mobile('mbt-id', andes.listar()) is None
    andes.desactivar('andes-id', modificacion_manual=True)
    assert resolver_planta_por_codigo_mobile('andes-id', andes.listar()) is None
