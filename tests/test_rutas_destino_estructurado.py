"""Bloque DESTINOS D2: resolución estructurada de destino canónico.

Prioriza identificadores del propio documento (código destinatario,
dirección + comuna, alias acotado al cliente) sobre el emparejamiento
textual débil de `obra_destino`, y contrasta el destino resuelto contra
DESPACHAR A antes de enrutar -- ver `atlas_core/rutas/destino_estructurado.py`.
"""
from datetime import datetime, timezone

import pytest

from atlas_core.catalogo_clientes import CatalogoClientes
from atlas_core.catalogo_destinos import CatalogoDestinos, EstadoCalidadDestino
from atlas_core.catalogo_plantas import CatalogoPlantas, EstadoCalidad
from atlas_core.rutas.destino_estructurado import (
    IdentificadoresDestinoDocumento,
    evaluar_concordancia_despacho,
    extraer_identificadores_destino,
    resolver_destino_canonico_estructurado,
)
from atlas_core.rutas.enriquecimiento_viaje import calcular_ruta_para_viaje
from atlas_core.rutas.modelos import Coordenadas, EstadoRuta, ResultadoRuta
from atlas_core.rutas.proveedor import ProveedorRutasSimulado
from atlas_core.rutas.repositorio import RepositorioRutas
from atlas_core.rutas.servicio import ServicioRutas

INSTANTE_SALIDA = datetime(2026, 8, 11, 12, 0, tzinfo=timezone.utc)
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
    ebema = clientes_repo.crear(razon_social="EBEMA SA", fuente="PRUEBA", rut="83585400-0")
    armacero = clientes_repo.crear(razon_social="ARMACERO MATCO SA", fuente="PRUEBA")

    destinos_repo = CatalogoDestinos(ruta_destinos, ruta_clientes=ruta_clientes)
    # EBEMA: dos destinos reales -- uno con código destinatario, otro sin él.
    destino_galvarino = destinos_repo.crear(
        cliente_id=ebema.cliente_id, nombre_destino="GALVARINO 8501",
        codigo_destino="0002013046",
        pais="CHILE", fuente="PRUEBA", direccion="GALVARINO 8501", comuna="QUILICURA", region="RM",
        latitud=-33.370934, longitud=-70.716168,
        estado_calidad=EstadoCalidadDestino.CONFIRMADO,
    )
    destino_cerro_blanco = destinos_repo.crear(
        cliente_id=ebema.cliente_id, nombre_destino="CERRO BLANCO 3670",
        pais="CHILE", fuente="PRUEBA", direccion="CERRO BLANCO 3670", comuna="TILTIL", region="RM",
        latitud=-33.089419, longitud=-70.702515,
        estado_calidad=EstadoCalidadDestino.PENDIENTE,
    )
    # ARMACERO: destino PENDIENTE con alias explícito.
    destino_armacero = destinos_repo.crear(
        cliente_id=armacero.cliente_id, nombre_destino="SANTA ISABEL 585",
        pais="CHILE", fuente="PRUEBA", direccion="SANTA ISABEL 585", comuna="LAMPA", region="RM",
        latitud=-33.310665, longitud=-70.737609,
        estado_calidad=EstadoCalidadDestino.PENDIENTE,
        aliases=["ARMACERO MATCO SA"],
    )

    return {
        "plantas": plantas_repo.listar(),
        "planta_renca": planta_renca,
        "catalogo_destinos": destinos_repo,
        "catalogo_clientes": clientes_repo,
        "ebema": ebema, "armacero": armacero,
        "destino_galvarino": destino_galvarino,
        "destino_cerro_blanco": destino_cerro_blanco,
        "destino_armacero": destino_armacero,
    }


def _servicio(tmp_path, resultado_ruta=None):
    proveedor = ProveedorRutasSimulado(
        resultado_ruta=resultado_ruta
        or ResultadoRuta(EstadoRuta.RUTA_CALCULADA, 16.683, 24.53, "SINTETICO")
    )
    return ServicioRutas(proveedor, RepositorioRutas(tmp_path / "cache_rutas.json"))


TEXTOS_ENCABEZADO_RENCA = "GUIA DESPACHO PLANTA ORIGEN RENCA ACEROS AZA S A CASA MATRIZ PLANTA RENCA LA UNION 3070 RENCA SANTIAGO CHILE"


# --- 1: cliente + código destinatario exacto ---

def test_resuelve_por_codigo_destinatario_exacto(entorno):
    textos = [TEXTOS_ENCABEZADO_RENCA, "COD DESTINATARIO :0002013046"]
    destino, motivo = resolver_destino_canonico_estructurado(
        cliente_texto="EBEMA SA", obra_destino_texto="ALGO QUE NO COINCIDE",
        textos_documento=textos,
        catalogo_destinos=entorno["catalogo_destinos"],
        catalogo_clientes=entorno["catalogo_clientes"],
    )
    assert motivo == "RESUELTO_CODIGO_DESTINATARIO"
    assert destino.destino_id == entorno["destino_galvarino"].destino_id


# --- 2: código destinatario desconocido -> no bloquea, cae al siguiente nivel ---

def test_codigo_destinatario_desconocido_cae_a_siguiente_nivel(entorno):
    textos = [TEXTOS_ENCABEZADO_RENCA, "COD DESTINATARIO :9999999999 DIRECCION : CERRO BLANCO 3670 COMUNA TILTIL"]
    destino, motivo = resolver_destino_canonico_estructurado(
        cliente_texto="EBEMA SA", obra_destino_texto="NO ENCONTRADO",
        textos_documento=textos,
        catalogo_destinos=entorno["catalogo_destinos"],
        catalogo_clientes=entorno["catalogo_clientes"],
    )
    assert motivo == "RESUELTO_DIRECCION_COMUNA"
    assert destino.destino_id == entorno["destino_cerro_blanco"].destino_id


# --- 3: mismo cliente con múltiples destinos -> no elige por fuzzy arbitrario ---

def test_obra_destino_no_coincide_con_ningun_destino_del_cliente_abstiene(entorno):
    destino, motivo = resolver_destino_canonico_estructurado(
        cliente_texto="EBEMA SA", obra_destino_texto="SUPERMERCADO SEÑOR DE LOS MI",
        textos_documento=["GUIA DE DESPACHO SEÑOR(ES) EBEMA SA"],
        catalogo_destinos=entorno["catalogo_destinos"],
        catalogo_clientes=entorno["catalogo_clientes"],
    )
    assert destino is None
    assert motivo == "DESTINO_NO_HOMOLOGADO"


# --- 4: dirección (+ comuna) exacta normalizada ---

def test_resuelve_por_direccion_y_comuna_exacta(entorno):
    textos = [TEXTOS_ENCABEZADO_RENCA, "DIRECCION : GALVARINO 8501 COMUNA QUILICURA"]
    destino, motivo = resolver_destino_canonico_estructurado(
        cliente_texto="EBEMA SA", obra_destino_texto="NO ENCONTRADO",
        textos_documento=textos,
        catalogo_destinos=entorno["catalogo_destinos"],
        catalogo_clientes=entorno["catalogo_clientes"],
    )
    assert motivo == "RESUELTO_DIRECCION_COMUNA"
    assert destino.destino_id == entorno["destino_galvarino"].destino_id


# --- 5: alias explícito acotado al cliente ---

def test_resuelve_por_alias_explicito_acotado_a_cliente(entorno):
    destino, motivo = resolver_destino_canonico_estructurado(
        cliente_texto="ARMACERO MATCO SA", obra_destino_texto="ARMACERO MATCO SA",
        textos_documento=["GUIA DE DESPACHO SEÑOR(ES) ARMACERO MATCO SA"],
        catalogo_destinos=entorno["catalogo_destinos"],
        catalogo_clientes=entorno["catalogo_clientes"],
    )
    assert motivo == "RESUELTO_ALIAS_CLIENTE"
    assert destino.destino_id == entorno["destino_armacero"].destino_id


# --- 6: ambigüedad -> abstención ---
#
# El propio CatalogoDestinos impide -- ya en la escritura -- que un mismo
# cliente tenga dos destinos con el mismo código, la misma dirección o el
# mismo nombre/alias (ver `_validar_duplicado`), así que la ambigüedad
# dentro de un cliente ya resuelto es estructuralmente imposible por ese
# camino. La ambigüedad real y alcanzable es entre CLIENTES DISTINTOS que
# comparten el mismo nombre de destino -- cuando el cliente del documento
# no se resuelve, el nivel D (global, histórico) puede toparse con ella.

def test_obra_destino_ambigua_entre_clientes_distintos_abstiene(entorno):
    otro_cliente = entorno["catalogo_clientes"].crear(
        razon_social="OTRO CLIENTE SPA", fuente="PRUEBA"
    )
    entorno["catalogo_destinos"].crear(
        cliente_id=otro_cliente.cliente_id, nombre_destino="GALVARINO 8501",
        pais="CHILE", fuente="PRUEBA", direccion="OTRA DIRECCION 1", comuna="OTRA COMUNA", region="RM",
        estado_calidad=EstadoCalidadDestino.CONFIRMADO,
    )
    destino, motivo = resolver_destino_canonico_estructurado(
        cliente_texto="CLIENTE QUE NO EXISTE EN EL CATALOGO",
        obra_destino_texto="GALVARINO 8501",
        textos_documento=["GUIA SIN ENCABEZADO RECONOCIBLE"],
        catalogo_destinos=entorno["catalogo_destinos"],
        catalogo_clientes=entorno["catalogo_clientes"],
    )
    assert destino is None
    assert motivo == "DESTINO_AMBIGUO"


# --- 7: cliente no resuelto -> cae al comportamiento histórico (nivel D) ---

def test_cliente_no_resuelto_cae_a_resolver_historico_global(entorno):
    destino, motivo = resolver_destino_canonico_estructurado(
        cliente_texto="CLIENTE INEXISTENTE SPA",
        obra_destino_texto="GALVARINO 8501",
        textos_documento=["DIRECCION : GALVARINO 8501 COMUNA QUILICURA"],
        catalogo_destinos=entorno["catalogo_destinos"],
        catalogo_clientes=entorno["catalogo_clientes"],
    )
    assert motivo == ""
    assert destino.destino_id == entorno["destino_galvarino"].destino_id


# --- RUT contradictorio: el nombre coincide pero el RUT del documento no --

def test_rut_contradictorio_no_acota_por_cliente(entorno):
    destino, motivo = resolver_destino_canonico_estructurado(
        cliente_texto="EBEMA SA", rut_cliente_texto="11111111-1",
        obra_destino_texto="NO ENCONTRADO",
        textos_documento=[TEXTOS_ENCABEZADO_RENCA, "COD DESTINATARIO :0002013046"],
        catalogo_destinos=entorno["catalogo_destinos"],
        catalogo_clientes=entorno["catalogo_clientes"],
    )
    # Sin acotar por cliente, el código no se busca en ningún destino
    # global (nivel D exige nombre/alias, no código) -- abstención segura.
    assert destino is None
    assert motivo == "OBRA_DESTINO_NO_INFORMADA"


# --- 8: ruta calculada solo con destino canónico confirmado y concordante ---

def test_calcula_ruta_real_con_destino_confirmado_y_despacho_concordante(entorno, tmp_path):
    servicio = _servicio(tmp_path)
    textos = [
        TEXTOS_ENCABEZADO_RENCA,
        "COD DESTINATARIO :0002013046 DIRECCION GALVARINO 8501 COMUNA QUILICURA",
        "DESPACHAR A : GALVARINO 8501 QUILICURA",
    ]
    resultado = calcular_ruta_para_viaje(
        obra_destino_texto="NO ENCONTRADO", patente=None, instante_salida=None,
        catalogo_destinos=entorno["catalogo_destinos"], plantas=entorno["plantas"],
        proveedor_posicion=None, servicio_rutas=servicio, textos_documento=textos,
        cliente_texto="EBEMA SA", catalogo_clientes=entorno["catalogo_clientes"],
    )
    assert resultado.estado_ruta == EstadoRuta.RUTA_CALCULADA.value
    assert resultado.destino_id == entorno["destino_galvarino"].destino_id
    assert resultado.distancia_km == "16.683"


# --- 9: destino PENDIENTE -> el gate de calidad bloquea, no calcula ruta ---

def test_no_calcula_ruta_con_destino_pendiente(entorno, tmp_path):
    servicio = _servicio(tmp_path)
    textos = [TEXTOS_ENCABEZADO_RENCA, "DESPACHAR A : SANTA ISABEL 585 LAMPA"]
    resultado = calcular_ruta_para_viaje(
        obra_destino_texto="ARMACERO MATCO SA", patente=None, instante_salida=None,
        catalogo_destinos=entorno["catalogo_destinos"], plantas=entorno["plantas"],
        proveedor_posicion=None, servicio_rutas=servicio, textos_documento=textos,
        cliente_texto="ARMACERO MATCO SA", catalogo_clientes=entorno["catalogo_clientes"],
    )
    assert resultado.estado_ruta == EstadoRuta.REQUIERE_REVISION.value
    assert resultado.motivo_ruta == "DESTINO_NO_CONFIRMADO"


# --- 10: DESPACHAR A divergente del destino canónico bloquea el enrutado ---

def test_despacho_divergente_bloquea_ruta_aunque_destino_resuelva(entorno, tmp_path):
    servicio = _servicio(tmp_path)
    textos = [
        TEXTOS_ENCABEZADO_RENCA,
        "COD DESTINATARIO :0002013046 DIRECCION GALVARINO 8501 COMUNA QUILICURA",
        "DESPACHAR A : AV ALMTE LATORRE 843 MEJILLONES MEJILLONES",
    ]
    resultado = calcular_ruta_para_viaje(
        obra_destino_texto="NO ENCONTRADO", patente=None, instante_salida=None,
        catalogo_destinos=entorno["catalogo_destinos"], plantas=entorno["plantas"],
        proveedor_posicion=None, servicio_rutas=servicio, textos_documento=textos,
        cliente_texto="EBEMA SA", catalogo_clientes=entorno["catalogo_clientes"],
    )
    assert resultado.estado_ruta == EstadoRuta.REQUIERE_REVISION.value
    assert resultado.motivo_ruta == "DESPACHO_DIVERGENTE_DEL_DESTINO_CANONICO"
    assert resultado.destino_id == entorno["destino_galvarino"].destino_id
    assert resultado.distancia_km == ""
    assert servicio.proveedor.llamadas_ruta == 0


# --- extracción de identificadores: orden de etiquetas variable en el documento ---

def test_extrae_identificadores_con_orden_de_etiquetas_distinto():
    # Orden real observado en guía 464170: DIRECCION antes de COD DESTINATARIO.
    textos_a = ["DIRECCION : GALVARINO 8501 COD DESTINATARIO :0002013046 COMUNA QUILICURA"]
    resultado_a = extraer_identificadores_destino(textos_a)
    assert resultado_a.direccion == "GALVARINO 8501"
    assert resultado_a.codigo_destinatario == "0002013046"
    assert resultado_a.comuna == "QUILICURA"

    # Orden real observado en guía 464511: COD DESTINATARIO antes de DIRECCION.
    textos_b = ["COD DESTINATARIO : CL14 DIRECCION : SANTA ISABEL 585 HORA ENTRADA :09:29:00 COMUNA : LAMPA"]
    resultado_b = extraer_identificadores_destino(textos_b)
    assert resultado_b.direccion == "SANTA ISABEL 585"
    assert resultado_b.codigo_destinatario == "CL14"
    assert resultado_b.comuna == "LAMPA"


def test_extrae_despachar_a_hasta_la_siguiente_etiqueta():
    textos = ["DESPACHAR A : VISTA CLARA 2351 CERRILLOS RETIRA RODRIGO NAHUELNIR"]
    resultado = extraer_identificadores_destino(textos)
    assert resultado.despachar_a == "VISTA CLARA 2351 CERRILLOS"


# --- concordancia: sin DESPACHAR A en el documento, se considera concordante ---

def test_sin_despachar_a_se_considera_concordante(entorno):
    concordante, motivo = evaluar_concordancia_despacho(
        entorno["destino_galvarino"], IdentificadoresDestinoDocumento()
    )
    assert concordante
    assert motivo == ""
