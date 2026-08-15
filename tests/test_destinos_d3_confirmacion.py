"""Bloque DESTINOS D3: confirmación humana asistida de destinos frecuentes.

D3 no introduce un nuevo mecanismo de resolución -- reutiliza intacto el de
D2 (`atlas_core/rutas/destino_estructurado.py`) sobre datos de catálogo ya
confirmados por evidencia real. Estas pruebas verifican: (a) que la
región/comuna es una dimensión real de la identidad de un destino y nunca
se ignora; (b) que el mecanismo de confirmación (`CatalogoDestinos.editar`)
nunca toca dirección/comuna/región/código/coordenadas al confirmar; (c) que
el gate de calidad y el gate de concordancia de despacho siguen protegiendo
cada viaje individualmente, confirmado o no; (d) no regresión de D2.
"""
from datetime import datetime, timezone

import pytest

from atlas_core.catalogo_clientes import CatalogoClientes
from atlas_core.catalogo_destinos import (
    CatalogoDestinos,
    CatalogoDestinosCorruptoError,
    EstadoBusquedaDestino,
    EstadoCalidadDestino,
)
from atlas_core.catalogo_plantas import CatalogoPlantas, EstadoCalidad
from atlas_core.rutas.destino_estructurado import (
    evaluar_concordancia_despacho,
    extraer_identificadores_destino,
    resolver_destino_canonico_estructurado,
)
from atlas_core.rutas.enriquecimiento_viaje import calcular_ruta_para_viaje
from atlas_core.rutas.modelos import Coordenadas, EstadoRuta, ResultadoRuta
from atlas_core.rutas.proveedor import ProveedorRutasSimulado
from atlas_core.rutas.repositorio import RepositorioRutas
from atlas_core.rutas.servicio import ServicioRutas

COORD_AZA_RENCA = Coordenadas(-70.685226, -33.401595)


@pytest.fixture
def entorno(tmp_path):
    ruta_plantas = tmp_path / "plantas.json"
    ruta_clientes = tmp_path / "clientes.json"
    ruta_destinos = tmp_path / "destinos_maestros.json"

    plantas_repo = CatalogoPlantas(ruta_plantas)
    planta_renca = plantas_repo.crear(
        nombre="AZA RENCA", pais="CHILE", fuente="PRUEBA",
        direccion="LA UNION 3070", comuna="RENCA", region="RM",
        latitud=COORD_AZA_RENCA.latitud, longitud=COORD_AZA_RENCA.longitud,
        estado_calidad=EstadoCalidad.CONFIRMADA,
    )

    clientes_repo = CatalogoClientes(ruta_clientes)
    armacero = clientes_repo.crear(razon_social="ARMACERO MATCO SA", fuente="PRUEBA")
    otro_cliente = clientes_repo.crear(razon_social="OTRO CLIENTE REGIONAL SPA", fuente="PRUEBA")

    destinos_repo = CatalogoDestinos(ruta_destinos, ruta_clientes=ruta_clientes)
    # Caso real D3: ARMACERO MATCO SA / SANTA ISABEL 585 -- destino
    # confirmado en este bloque con evidencia real (2 guías independientes,
    # 464511 + fila 429061 del ground truth).
    destino_armacero = destinos_repo.crear(
        cliente_id=armacero.cliente_id, nombre_destino="SANTA ISABEL 585",
        codigo_destino="CL14",
        pais="CHILE", fuente="MIGRACION_EXCEL_ESTUDIO_DISTANCIAS_2026Q2",
        direccion="SANTA ISABEL 585", comuna="LAMPA", region="RM",
        latitud=-33.310665, longitud=-70.737609,
        estado_calidad=EstadoCalidadDestino.PENDIENTE,
        observacion="Clave destino original: ARMACERO MATCO SA|RM|LAMPA|SANTA ISABEL 585. 94 viajes.",
    )
    # Mismo nombre de calle ("SANTA ISABEL 585"), cliente distinto, comuna
    # y región distintas -- caso sintético para la prueba 2 (nunca debe
    # colisionar con el destino de ARMACERO).
    destinos_repo.crear(
        cliente_id=otro_cliente.cliente_id, nombre_destino="SANTA ISABEL 585",
        pais="CHILE", fuente="PRUEBA",
        direccion="SANTA ISABEL 585", comuna="TEMUCO", region="ARAUCANIA",
        latitud=-38.7359, longitud=-72.5904,
        estado_calidad=EstadoCalidadDestino.CONFIRMADO,
    )
    # Destino con coordenada fuera de rango RM -- mismo patrón real
    # detectado en el catálogo activo (registros "SAN MIGUEL").
    destino_fuera_de_rango = destinos_repo.crear(
        cliente_id=armacero.cliente_id, nombre_destino="CARMEN MENA 529",
        pais="CHILE", fuente="PRUEBA", direccion="CARMEN MENA 529", comuna="SAN MIGUEL", region="RM",
        latitud=-30.8143, longitud=-70.6034,
        estado_calidad=EstadoCalidadDestino.CONFIRMADO,
    )

    return {
        "plantas": plantas_repo.listar(), "planta_renca": planta_renca,
        "catalogo_destinos": destinos_repo, "catalogo_clientes": clientes_repo,
        "ruta_destinos": ruta_destinos,
        "armacero": armacero, "destino_armacero": destino_armacero,
        "destino_fuera_de_rango": destino_fuera_de_rango,
    }


def _servicio(tmp_path, resultado_ruta=None):
    proveedor = ProveedorRutasSimulado(
        resultado_ruta=resultado_ruta
        or ResultadoRuta(EstadoRuta.RUTA_CALCULADA, 12.969, 19.71, "SINTETICO")
    )
    return ServicioRutas(proveedor, RepositorioRutas(tmp_path / "cache_rutas.json"))


TEXTOS_ENCABEZADO_RENCA = "ACEROS AZA S A CASA MATRIZ PLANTA RENCA LA UNION 3070 RENCA SANTIAGO CHILE"


# --- 1: destino RM válido, resuelto y con comuna+región coherentes ---

def test_destino_rm_valido_por_comuna_y_region(entorno):
    destino, motivo = resolver_destino_canonico_estructurado(
        cliente_texto="ARMACERO MATCO SA", obra_destino_texto="ARMACERO MATCO SA",
        textos_documento=[TEXTOS_ENCABEZADO_RENCA, "COD DESTINATARIO :CL14 DIRECCION SANTA ISABEL 585 COMUNA LAMPA"],
        catalogo_destinos=entorno["catalogo_destinos"],
        catalogo_clientes=entorno["catalogo_clientes"],
    )
    assert destino.destino_id == entorno["destino_armacero"].destino_id
    assert destino.comuna == "LAMPA"
    assert destino.region == "RM"


# --- 2: mismo nombre de calle en comuna/región distinta no colisiona ---

def test_mismo_nombre_de_calle_en_region_distinta_no_colisiona(entorno):
    # Cliente no resuelto -> nivel D global (por nombre, sin acotar por
    # cliente): dos destinos de CLIENTES distintos comparten el mismo
    # nombre de calle -- debe abstenerse, nunca elegir uno al azar.
    destino, motivo = resolver_destino_canonico_estructurado(
        cliente_texto="CLIENTE QUE NO EXISTE",
        obra_destino_texto="SANTA ISABEL 585",
        textos_documento=["GUIA SIN ENCABEZADO RECONOCIBLE"],
        catalogo_destinos=entorno["catalogo_destinos"],
        catalogo_clientes=entorno["catalogo_clientes"],
    )
    assert destino is None
    assert motivo == "DESTINO_AMBIGUO"

    # El cliente tampoco debe actuar como propietario/desambiguador del lugar:
    # sin comuna/región documental, la identidad física sigue siendo ambigua.
    destino_acotado, motivo_acotado = resolver_destino_canonico_estructurado(
        cliente_texto="ARMACERO MATCO SA", obra_destino_texto="SANTA ISABEL 585",
        textos_documento=["GUIA SIN ENCABEZADO RECONOCIBLE"],
        catalogo_destinos=entorno["catalogo_destinos"],
        catalogo_clientes=entorno["catalogo_clientes"],
    )
    assert destino_acotado is None
    assert motivo_acotado == "DESTINO_AMBIGUO"


# --- 3: coordenadas fuera del rango geográfico plausible -> rechazo ---

def test_coordenadas_fuera_de_rango_geografico_rechaza(entorno):
    destino, motivo = resolver_destino_canonico_estructurado(
        cliente_texto="ARMACERO MATCO SA", obra_destino_texto="CARMEN MENA 529",
        textos_documento=["GUIA SIN ENCABEZADO RECONOCIBLE"],
        catalogo_destinos=entorno["catalogo_destinos"],
        catalogo_clientes=entorno["catalogo_clientes"],
    )
    assert destino is None
    assert motivo == "DESTINO_COORDENADAS_FUERA_DE_RANGO"


# --- 4: código destinatario concordante resuelve (caso real ARMACERO/CL14) ---

def test_codigo_destinatario_concordante_resuelve(entorno):
    textos = [TEXTOS_ENCABEZADO_RENCA, "COD DESTINATARIO :CL14"]
    destino, motivo = resolver_destino_canonico_estructurado(
        cliente_texto="ARMACERO MATCO SA", obra_destino_texto="NO ENCONTRADO",
        textos_documento=textos,
        catalogo_destinos=entorno["catalogo_destinos"],
        catalogo_clientes=entorno["catalogo_clientes"],
    )
    assert motivo == "RESUELTO_CODIGO_DESTINATARIO"
    assert destino.destino_id == entorno["destino_armacero"].destino_id


# --- 5: DESPACHAR A divergente -> no confirma/calcula la ruta ---

def test_despachar_a_divergente_no_calcula_ruta_aunque_este_confirmado(entorno, tmp_path):
    entorno["catalogo_destinos"].editar(
        entorno["destino_armacero"].destino_id,
        modificacion_manual=True, estado_calidad=EstadoCalidadDestino.CONFIRMADO,
    )
    servicio = _servicio(tmp_path)
    textos = [
        TEXTOS_ENCABEZADO_RENCA,
        "COD DESTINATARIO :CL14 DIRECCION SANTA ISABEL 585 COMUNA LAMPA",
        "DESPACHAR A : AV ALMTE LATORRE 843 MEJILLONES MEJILLONES",
    ]
    resultado = calcular_ruta_para_viaje(
        obra_destino_texto="NO ENCONTRADO", patente=None, instante_salida=None,
        catalogo_destinos=entorno["catalogo_destinos"], plantas=entorno["plantas"],
        proveedor_posicion=None, servicio_rutas=servicio, textos_documento=textos,
        cliente_texto="ARMACERO MATCO SA", catalogo_clientes=entorno["catalogo_clientes"],
    )
    assert resultado.estado_ruta == EstadoRuta.REQUIERE_REVISION.value
    assert resultado.motivo_ruta == "DESPACHO_DIVERGENTE_DEL_DESTINO_CANONICO"
    assert servicio.proveedor.llamadas_ruta == 0


# --- 6: destino PENDIENTE no enruta (gate de calidad, sin cambios) ---

def test_destino_pendiente_no_enruta(entorno, tmp_path):
    servicio = _servicio(tmp_path)
    textos = [
        TEXTOS_ENCABEZADO_RENCA,
        "COD DESTINATARIO :CL14 DIRECCION SANTA ISABEL 585 COMUNA LAMPA",
        "DESPACHAR A : SANTA ISABEL 585 LAMPA",
    ]
    resultado = calcular_ruta_para_viaje(
        obra_destino_texto="NO ENCONTRADO", patente=None, instante_salida=None,
        catalogo_destinos=entorno["catalogo_destinos"], plantas=entorno["plantas"],
        proveedor_posicion=None, servicio_rutas=servicio, textos_documento=textos,
        cliente_texto="ARMACERO MATCO SA", catalogo_clientes=entorno["catalogo_clientes"],
    )
    assert entorno["destino_armacero"].estado_calidad == "PENDIENTE"
    assert resultado.estado_ruta == EstadoRuta.REQUIERE_REVISION.value
    assert resultado.motivo_ruta == "DESTINO_NO_CONFIRMADO"


# --- 7: destino CONFIRMADO y concordante sí enruta (caso real D3) ---

def test_destino_confirmado_y_concordante_calcula_ruta_real(entorno, tmp_path):
    entorno["catalogo_destinos"].editar(
        entorno["destino_armacero"].destino_id,
        modificacion_manual=True, estado_calidad=EstadoCalidadDestino.CONFIRMADO,
    )
    servicio = _servicio(tmp_path)
    textos = [
        TEXTOS_ENCABEZADO_RENCA,
        "COD DESTINATARIO :CL14 DIRECCION SANTA ISABEL 585 COMUNA LAMPA",
        "DESPACHAR A : SANTA ISABEL 585 SANTIAGO LAMPA",
    ]
    resultado = calcular_ruta_para_viaje(
        obra_destino_texto="NO ENCONTRADO", patente=None, instante_salida=None,
        catalogo_destinos=entorno["catalogo_destinos"], plantas=entorno["plantas"],
        proveedor_posicion=None, servicio_rutas=servicio, textos_documento=textos,
        cliente_texto="ARMACERO MATCO SA", catalogo_clientes=entorno["catalogo_clientes"],
    )
    assert resultado.estado_ruta == EstadoRuta.RUTA_CALCULADA.value
    assert resultado.destino_id == entorno["destino_armacero"].destino_id
    assert resultado.distancia_km == "12.969"


# --- 8: confirmar preserva dirección/comuna/región/código/coordenadas ---

def test_confirmar_destino_preserva_datos_geograficos(entorno):
    antes = entorno["destino_armacero"]
    despues = entorno["catalogo_destinos"].editar(
        antes.destino_id, modificacion_manual=True,
        estado_calidad=EstadoCalidadDestino.CONFIRMADO,
        fuente="CONFIRMACION_DESTINOS_D3_2026-08-11+EVIDENCIA_MULTIPLE_INDEPENDIENTE",
        observacion=antes.observacion + " | CONFIRMACION_D3: prueba.",
    )
    assert despues.estado_calidad == "CONFIRMADO"
    assert despues.direccion == antes.direccion
    assert despues.comuna == antes.comuna
    assert despues.region == antes.region
    assert despues.codigo_destino == antes.codigo_destino
    assert despues.latitud == antes.latitud
    assert despues.longitud == antes.longitud
    assert despues.nombre_destino == antes.nombre_destino


# --- 9: el catálogo sigue siendo válido tras la confirmación ---

def test_catalogo_sigue_siendo_valido_tras_confirmar(entorno):
    entorno["catalogo_destinos"].editar(
        entorno["destino_armacero"].destino_id,
        modificacion_manual=True, estado_calidad=EstadoCalidadDestino.CONFIRMADO,
    )
    recargado = CatalogoDestinos(
        entorno["ruta_destinos"], ruta_clientes=entorno["ruta_destinos"].parent / "clientes.json"
    )
    try:
        destinos = recargado.listar()
    except CatalogoDestinosCorruptoError:
        pytest.fail("El catálogo quedó corrupto tras la confirmación")
    assert len(destinos) == 3
    confirmado = recargado.obtener(entorno["destino_armacero"].destino_id)
    assert confirmado.estado_calidad == "CONFIRMADO"


# --- 10: no regresión -- resolución sin cliente/catálogo de clientes sigue igual (D2) ---

def test_no_regresion_resolucion_global_sin_cliente(entorno):
    from atlas_core.rutas.enriquecimiento_viaje import resolver_destino_canonico

    destino, motivo = resolver_destino_canonico("SANTA ISABEL 585", entorno["catalogo_destinos"])
    # Ambiguo a nivel global -- dos destinos (ARMACERO y el cliente
    # regional sintético) comparten el mismo nombre de calle; el
    # comportamiento histórico de D1/D2 se preserva sin cambios.
    assert destino is None
    assert motivo == "DESTINO_AMBIGUO"


def test_extraccion_identificadores_sin_cambios_respecto_a_d2():
    resultado = extraer_identificadores_destino(
        ["DIRECCION : SANTA ISABEL 585 COMUNA LAMPA COD DESTINATARIO :CL14"]
    )
    assert resultado.direccion == "SANTA ISABEL 585"
    assert resultado.comuna == "LAMPA"
    assert resultado.codigo_destinatario == "CL14"


def test_concordancia_despacho_sin_cambios_respecto_a_d2(entorno):
    concordante, motivo = evaluar_concordancia_despacho(
        entorno["destino_armacero"],
        extraer_identificadores_destino(["DESPACHAR A : SANTA ISABEL 585 LAMPA"]),
    )
    assert concordante
    assert motivo == ""
