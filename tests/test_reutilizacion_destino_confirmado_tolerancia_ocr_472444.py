"""Bloque REUTILIZACIÓN DE DESTINO CONFIRMADO CON TOLERANCIA OCR -- caso
real 472444 (obra "EMPRESA CONST SIGRO", cliente PRODALAM SA): la
dirección "AVDA IRARRAZAVAL 5497 SANTIAGO NUNOA" ya está CONFIRMADA dos
veces por Javier (guías 464550, 472227 -- dos representaciones de texto
ligeramente distintas de la MISMA dirección real, exactamente el mismo
patrón ya documentado para AUSIN SAN BERNARDO/472593). La guía 472444
imprime la misma dirección con un único carácter OCR mal leído
("IRABRAZAVAL" por "IRARRAZAVAL", R/B visualmente parecidas). Antes de
este bloque, el resolver estricto se abstenía (dos relaciones
confirmadas = evidencia redundante, no ambigüedad real -- ver Bloque
REGENERACIÓN B1) y el fallback de reutilización exigía coincidencia
LITERAL de la calle dentro del texto documental -- un solo carácter
distinto bastaba para tratar una dirección ya conocida como si fuera
nueva y generar una revisión humana redundante para corregir un typo de
OCR.

Causa raíz: `direccion_confirmada_coincide` (antes, un simple `in` de
Python) no toleraba ninguna sustitución de caracteres. La corrección es
GENERAL (bounded, por longitud, nunca "fuzzy" abierto) -- ningún test de
este archivo hardcodea "Irarrázaval"/"Ñuñoa" como caso especial excepto
la regresión exacta al final; el mecanismo se prueba primero con
nombres de calle genéricos."""
from __future__ import annotations

import json

from atlas_core.catalogo_clientes import CatalogoClientes, EstadoCalidadCliente
from atlas_core.catalogo_destinos import CatalogoDestinos, EstadoCalidadDestino, direccion_confirmada_coincide
from atlas_core.catalogo_obras_destinos import CatalogoObrasDestinos, Evidencia, ResultadoEvidencia, TipoEvidencia
from atlas_core.decisiones_pendientes import _decisiones_obra_para_cliente
from atlas_core.procesamiento_masivo import COLUMNAS  # noqa: F401  (import paridad con el resto de la suite)


def _catalogos_base(carpeta):
    for nombre, contenido in {
        "clientes.json": {"version_formato": 1, "clientes": []}, "empresas.json": {},
        "vehiculos.json": {"version": 1, "vehiculos": []},
        "obras_destinos.json": {"version_formato": 1, "obras": [], "relaciones": []},
        "destinos_maestros.json": {"version_formato": 1, "destinos": []},
    }.items():
        (carpeta / nombre).write_text(json.dumps(contenido), encoding="utf-8")


def _confirmar_destino_para_obra(catalogo_obras, catalogos, *, cliente_id, obra, texto_destino, guia):
    resultado_obs = catalogo_obras.registrar_observacion(
        cliente_id=cliente_id, nombre_obra=obra,
        destino_id=CatalogoDestinos(
            catalogos / "destinos_maestros.json", ruta_clientes=catalogos / "clientes.json",
        ).crear(
            cliente_id="", nombre_destino=texto_destino, direccion=texto_destino,
            pais="CHILE", fuente="TEST", estado_calidad=EstadoCalidadDestino.CONFIRMADO,
        ).destino_id,
        evidencia=Evidencia(
            tipo=TipoEvidencia.GUIA.value, identificador_fuente=guia, referencia_hash="b" * 64,
            campos_observados={"obra": obra, "destino": texto_destino},
            fecha="2026-01-01T00:00:00+00:00", actor_proceso="TEST", resultado=ResultadoEvidencia.SOPORTA.value,
        ),
    )
    relacion = resultado_obs.relacion
    if relacion.estado == "PENDIENTE":
        catalogo_obras.confirmar_relacion(relacion.relacion_id, actor="TEST", identificador_fuente="test")


def _preparar_obra_con_dos_confirmaciones(tmp_path, *, cliente_razon_social, rut, obra, destino_a, destino_b):
    """Dos relaciones CONFIRMADAS para la MISMA obra -- el resolver
    estricto (exige exactamente una) se abstiene por evidencia
    redundante, exactamente como en el caso real (464550/472227), y el
    fallback de reutilización (`direccion_confirmada_coincide`) es quien
    debe decidir."""
    catalogos = tmp_path / "catalogos_privados"
    catalogos.mkdir(parents=True)
    _catalogos_base(catalogos)
    cliente = CatalogoClientes(catalogos / "clientes.json").crear(
        razon_social=cliente_razon_social, rut=rut, fuente="TEST",
        estado_calidad=EstadoCalidadCliente.CONFIRMADO,
    )
    catalogo_obras = CatalogoObrasDestinos(
        ruta=catalogos / "obras_destinos.json", ruta_clientes=catalogos / "clientes.json",
        ruta_destinos=catalogos / "destinos_maestros.json",
    )
    _confirmar_destino_para_obra(
        catalogo_obras, catalogos, cliente_id=cliente.cliente_id, obra=obra,
        texto_destino=destino_a, guia="1",
    )
    _confirmar_destino_para_obra(
        catalogo_obras, catalogos, cliente_id=cliente.cliente_id, obra=obra,
        texto_destino=destino_b, guia="2",
    )
    return catalogos, cliente


# ============================================================
# 1 -- direccion_confirmada_coincide: unidad pura, reglas generales
# ============================================================


def test_coincidencia_literal_se_mantiene_igual_que_antes():
    assert direccion_confirmada_coincide("CALLE GENERICA 100", "CALLE GENERICA 100 SANTIAGO") is True


def test_sin_coincidencia_alguna_nunca_acepta():
    assert direccion_confirmada_coincide("CALLE GENERICA 100", "OTRA CALLE 999 SANTIAGO") is False


def test_un_solo_caracter_distinto_en_direccion_larga_se_tolera():
    """Fragmento largo (>25 caracteres): un solo carácter sustituido
    (error OCR de una letra) se tolera."""
    confirmada = "AVENIDA PROVIDENCIA 1234 SANTIAGO PROVIDENCIA"
    documental_con_ocr = "AVENIDA PROVIOENCIA 1234 SANTIAGO PROVIDENCIA"  # D->O
    assert direccion_confirmada_coincide(confirmada, documental_con_ocr) is True


def test_separacion_ocr_espuria_con_numero_ancla_se_tolera():
    """La tolerancia conserva el ancla numérica y sólo absorbe una
    separación espuria de OCR; no habilita una búsqueda difusa general."""
    assert direccion_confirmada_coincide(
        "AVENIDA CENTRAL 151",
        "AVENIDA CENT RAL 151 SANTIAGO",
    ) is True


def test_fragmento_corto_exige_coincidencia_exacta_sin_tolerancia():
    """Por debajo del umbral mínimo (10 caracteres) -- p. ej. un número
    de calle o una palabra corta ambigua -- nunca hay tolerancia: un
    solo carácter distinto sigue rechazando, para no arriesgar confundir
    dos calles reales distintas."""
    assert direccion_confirmada_coincide("CALLE UNO", "CALLE DOS SANTIAGO") is False


def test_demasiadas_diferencias_para_la_longitud_no_se_tolera():
    """Dos calles realmente distintas, de longitud similar, con muchas
    diferencias -- nunca se confunden aunque el fragmento sea largo."""
    confirmada = "AVENIDA PROVIDENCIA 1234 SANTIAGO PROVIDENCIA"
    otra_calle_real = "CAMINO LAS PALMERAS 9876 SANTIAGO LAS CONDES"
    assert direccion_confirmada_coincide(confirmada, otra_calle_real) is False


def test_valor_vacio_nunca_revienta():
    assert direccion_confirmada_coincide("", "CUALQUIER TEXTO") is False


# ============================================================
# 2 -- Detección (`_decisiones_obra_para_cliente`): la tarjeta
# DESTINO_SIN_CONFIRMAR no se genera cuando la dirección documental es
# una variante OCR menor de un destino YA confirmado para la obra. Dos
# confirmaciones (evidencia redundante, mismo patrón real 464550/472227)
# para que el resolver estricto se abstenga y el fallback tolerante
# sea quien realmente decide -- con una sola confirmación, el resolver
# estricto ya suprime la tarjeta por sí solo (R3.4) y el test no
# ejercitaría el mecanismo nuevo.
# ============================================================


def test_variante_ocr_menor_de_destino_ya_confirmado_no_genera_tarjeta(tmp_path):
    """Fixture genérica -- nunca 'Irarrázaval'/'Ñuñoa': una calle larga
    con un único carácter OCR distinto, ya confirmada (dos veces, con
    variantes de texto) para la obra, no debe generar una revisión
    humana redundante."""
    catalogos, cliente = _preparar_obra_con_dos_confirmaciones(
        tmp_path, cliente_razon_social="CLIENTE GENERICO SA", rut="76.111.111-6",
        obra="OBRA GENERICA",
        destino_a="AVENIDA PROVIDENCIA 1234 SANTIAGO PROVIDENCIA",
        destino_b="Avenida Providencia 1234, Providencia",  # misma dirección real, otra forma de texto
    )
    decisiones = _decisiones_obra_para_cliente(
        carpeta=catalogos, cliente_id=cliente.cliente_id, cliente_razon_social=cliente.razon_social,
        cliente_aliases=(), obra_texto="OBRA GENERICA",
        despachar_a_documental="AVENIDA PROVIOENCIA 1234 SANTIAGO PROVIDENCIA",  # D->O, error OCR de una letra
        comunes={"archivo": "3.jpeg", "numero_guia": "3", "numero_transporte": "T3"},
    )
    assert decisiones == []


def test_direccion_realmente_nueva_sigue_generando_tarjeta_pese_a_obra_ya_conocida(tmp_path):
    """Control -- la obra tiene dos destinos confirmados REALMENTE
    distintos entre sí; una tercera dirección, también realmente
    distinta de ambos (no una variante OCR menor de ninguno), sigue
    siendo una pregunta legítima."""
    catalogos, cliente = _preparar_obra_con_dos_confirmaciones(
        tmp_path, cliente_razon_social="CLIENTE GENERICO SA", rut="76.111.111-6",
        obra="OBRA GENERICA", destino_a="CALLE UNO 100 SANTIAGO", destino_b="CALLE DOS 200 SANTIAGO",
    )
    decisiones = _decisiones_obra_para_cliente(
        carpeta=catalogos, cliente_id=cliente.cliente_id, cliente_razon_social=cliente.razon_social,
        cliente_aliases=(), obra_texto="OBRA GENERICA",
        despachar_a_documental="AVENIDA TRES 300 SANTIAGO",
        comunes={"archivo": "3.jpeg", "numero_guia": "3", "numero_transporte": "T3"},
    )
    assert len(decisiones) == 1
    assert decisiones[0]["tipo"] == "DESTINO_SIN_CONFIRMAR"


def test_direccion_corta_con_error_ocr_de_una_letra_sigue_generando_tarjeta(tmp_path):
    """Control -- fragmento corto (por debajo del umbral de tolerancia):
    incluso un error OCR de una sola letra sigue generando la tarjeta,
    nunca se arriesga a confundir dos calles cortas distintas."""
    catalogos, cliente = _preparar_obra_con_dos_confirmaciones(
        tmp_path, cliente_razon_social="CLIENTE GENERICO SA", rut="76.111.111-6",
        obra="OBRA GENERICA", destino_a="CALLE UNO", destino_b="CALLE TRES",
    )
    decisiones = _decisiones_obra_para_cliente(
        carpeta=catalogos, cliente_id=cliente.cliente_id, cliente_razon_social=cliente.razon_social,
        cliente_aliases=(), obra_texto="OBRA GENERICA", despachar_a_documental="CALLE DOS",
        comunes={"archivo": "3.jpeg", "numero_guia": "3", "numero_transporte": "T3"},
    )
    assert len(decisiones) == 1


def test_obra_confirmada_sin_destino_documental_no_genera_revision(tmp_path):
    """Sin dirección documental no hay relación obra↔destino que decidir."""
    catalogos, cliente = _preparar_obra_con_dos_confirmaciones(
        tmp_path, cliente_razon_social="CLIENTE GENERICO SA", rut="76.111.111-6",
        obra="OBRA GENERICA", destino_a="CALLE UNO 100 SANTIAGO", destino_b="CALLE DOS 200 SANTIAGO",
    )
    decisiones = _decisiones_obra_para_cliente(
        carpeta=catalogos, cliente_id=cliente.cliente_id, cliente_razon_social=cliente.razon_social,
        cliente_aliases=(), obra_texto="OBRA GENERICA", despachar_a_documental="",
        comunes={"archivo": "4.jpeg", "numero_guia": "4", "numero_transporte": "T4"},
    )
    assert decisiones == []


# ============================================================
# 3 -- regresión exacta del caso real 472444 (además de la cobertura
# general de arriba): obra "EMPRESA CONST SIGRO", cliente PRODALAM SA,
# destino ya confirmado dos veces con dos formas de texto de "AVDA
# IRARRAZAVAL 5497 SANTIAGO NUNOA"; guía 472444 imprime "AVDA
# IRABRAZAVAL 5497 SANTIAGO NUNOA" (R->B, error OCR de una sola letra).
# ============================================================


def test_regresion_472444_variante_ocr_de_irarrazaval_no_genera_tarjeta(tmp_path):
    catalogos, cliente = _preparar_obra_con_dos_confirmaciones(
        tmp_path, cliente_razon_social="PRODALAM SA", rut="93.772.000-9",
        obra="EMPRESA CONST SIGRO",
        destino_a="AVDA IRARRAZAVAL 5497 SANTIAGO NUNOA",
        destino_b="Av. Irarrazaval 5497 Ñuñoa",
    )
    decisiones = _decisiones_obra_para_cliente(
        carpeta=catalogos, cliente_id=cliente.cliente_id, cliente_razon_social=cliente.razon_social,
        cliente_aliases=(), obra_texto="EMPRESA CONST SIGRO",
        despachar_a_documental="AVDA IRABRAZAVAL 5497 SANTIAGO NUNOA",
        comunes={"archivo": "472444.jpeg", "numero_guia": "472444", "numero_transporte": "0000355145"},
    )
    assert decisiones == []
