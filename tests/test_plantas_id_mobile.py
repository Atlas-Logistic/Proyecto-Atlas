from atlas_core.catalogo_plantas import CatalogoPlantas
from atlas_core.rutas.origen_evidencia import resolver_planta_por_codigo_mobile
from atlas_core.mobile import validar_planta_origen_mobile, ErrorEnvioMobile


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
    # Desactivada despues de capturar: el ID sigue siendo inequivoco y la guia
    # conserva su origen (Cloud ya rechaza capturas posteriores a la baja).
    assert resolver_planta_por_codigo_mobile('andes-id', andes.listar()).planta_id == 'andes-id'


def test_recepcion_mobile_acepta_solo_catalogo_de_andes(tmp_path):
    raiz = tmp_path / 'Atlas_empresas' / 'transportes-andes'
    catalogo = CatalogoPlantas(raiz / 'catalogos_privados' / 'plantas.json', generador_id=lambda: 'andes-norte')
    catalogo.crear(nombre='Terminal Norte', pais='Chile', fuente='prueba', estado_calidad='CONFIRMADA')
    assert validar_planta_origen_mobile('andes-norte', raiz_atlas=raiz) == 'andes-norte'
    try:
        validar_planta_origen_mobile('AZA_COLINA', raiz_atlas=raiz)
    except ErrorEnvioMobile:
        pass
    else:
        raise AssertionError('una planta MBT no puede entrar en Andes')
