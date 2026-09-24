"""Bloque P0 -- CÓDIGO CLIENTE + DESTINATARIO OPERACIONAL. Tests
focales, puramente sintéticos (nunca tocan G:). Casos de referencia
reales usados como fixtures: AGF, PRODALAM, TORRES, ACEROS COX."""
from __future__ import annotations

from datetime import datetime, timezone

from atlas_core.catalogo_clientes import Cliente, normalizar_nombre_cliente
from atlas_core.codigo_cliente_destinatario import (
    RESULTADO_ABSTENCION,
    RESULTADO_SIN_EVIDENCIA,
    RESULTADO_SUGERENCIA_HUMANA,
    CatalogoCodigosCliente,
    enriquecer_decisiones_cliente_por_codigo,
    enriquecer_decisiones_obra_por_destinatario,
    evidencia_destinatario_compatible_con_obra,
    resolver_identidad_cliente_reforzada,
)
from atlas_core.extractor import extraer_datos


def _cliente(cliente_id, razon_social, rut=""):
    return Cliente(
        cliente_id=cliente_id, razon_social=razon_social,
        nombre_normalizado=normalizar_nombre_cliente(razon_social), nombre_comercial="",
        rut=rut, aliases=(), estado_calidad="CONFIRMADO", estado_vigencia="ACTIVO",
        fuente="TEST", observacion="", fecha_creacion="2026-01-01T00:00:00+00:00",
        fecha_modificacion="2026-01-01T00:00:00+00:00",
    )


def _fila(**overrides):
    fila = {
        "archivo": "1.jpeg", "numero_guia": "1", "cliente": "", "obra_destino": "",
        "codigo_cliente": "No encontrado", "cod_destinatario": "No encontrado",
        "rut_cliente": "No encontrado",
    }
    fila.update(overrides)
    return fila


# --- 1. AGF: comprador=obra, códigos DIFERENTES -> se mantienen separados ---

def test_agf_codigo_cliente_y_cod_destinatario_se_mantienen_separados():
    textos = [
        "SENOR(ES) AGF ACEROS DE CHILE SPA RUT 77410131-4",
        "Codigo Cliente 0001006226",
        "OBRA DESTINO AGF ACEROS DE CHILE SPA COD DESTINATARIO 000200473",
    ]
    datos = extraer_datos(textos)
    assert datos["código cliente"] == "0001006226"
    assert datos["cod destinatario"] == "000200473"
    # Nunca el mismo valor aunque el comprador y la obra coincidan de nombre.
    assert datos["código cliente"] != datos["cod destinatario"]


def test_agf_dos_filas_mismo_codigo_cliente_distinto_cod_destinatario():
    fila_hurtado = _fila(
        cliente="AGF ACEROS DE CHILE SPA", codigo_cliente="0001006226",
        cod_destinatario="000200231", obra_destino="CONSTRUCTORA IGNACIO HURTADO",
    )
    fila_agf = _fila(
        cliente="AGF ACEROS DE CHILE SPA", codigo_cliente="0001006226",
        cod_destinatario="000200473", obra_destino="AGF ACEROS DE CHILE SPA",
    )
    historicas = [fila_hurtado, fila_agf]
    assert evidencia_destinatario_compatible_con_obra(
        cliente_comprador="AGF ACEROS DE CHILE SPA", cod_destinatario="000200231",
        obra_candidata="CONSTRUCTORA IGNACIO HURTADO", filas_historicas=historicas,
    )
    assert evidencia_destinatario_compatible_con_obra(
        cliente_comprador="AGF ACEROS DE CHILE SPA", cod_destinatario="000200473",
        obra_candidata="AGF ACEROS DE CHILE SPA", filas_historicas=historicas,
    )
    # Cruzado: el destinatario de Hurtado NUNCA corrobora la obra AGF.
    assert not evidencia_destinatario_compatible_con_obra(
        cliente_comprador="AGF ACEROS DE CHILE SPA", cod_destinatario="000200231",
        obra_candidata="AGF ACEROS DE CHILE SPA", filas_historicas=historicas,
    )


# --- 2. TORRES: códigos IGUALES -> campos semánticamente separados ---

def test_torres_codigos_iguales_nunca_se_fusionan():
    textos = [
        "SENOR(ES) TORRES OCARANZA LTDA RUT 76083093-3",
        "Codigo Cliente 0001004443",
        "OBRA DESTINO TORRES OCARANZA LTDA COD DESTINATARIO 0001004443",
    ]
    datos = extraer_datos(textos)
    # Los VALORES pueden coincidir (caso real) pero viven en campos
    # documentales distintos -- nunca un solo campo fusionado.
    assert datos["código cliente"] == "0001004443"
    assert datos["cod destinatario"] == "0001004443"
    # Dos claves documentales DISTINTAS, cada una con su propio valor --
    # nunca un solo campo fusionado, aunque el valor coincida.
    assert {"código cliente", "cod destinatario"} <= set(datos.keys())


def test_torres_codigo_cliente_no_se_usa_como_cod_destinatario():
    """Que el VALOR coincida (0001004443) nunca implica que la evidencia
    de destinatario se derive del código de cliente -- son fuentes
    documentales independientes, cada una con su propia columna."""
    historicas = [_fila(
        cliente="TORRES OCARANZA LTDA", codigo_cliente="0001004443",
        cod_destinatario="0001004443", obra_destino="TORRES OCARANZA LTDA",
    )]
    # Evidencia real: coincide EXACTAMENTE con cod_destinatario histórico.
    assert evidencia_destinatario_compatible_con_obra(
        cliente_comprador="TORRES OCARANZA LTDA", cod_destinatario="0001004443",
        obra_candidata="TORRES OCARANZA LTDA", filas_historicas=historicas,
    )
    # Un cod_destinatario DISTINTO nunca se corrobora sólo porque coincide
    # con el código_cliente conocido de ese comprador.
    assert not evidencia_destinatario_compatible_con_obra(
        cliente_comprador="TORRES OCARANZA LTDA", cod_destinatario="0009999999",
        obra_candidata="TORRES OCARANZA LTDA", filas_historicas=historicas,
    )


# --- 3. PRODALAM: varios COD DESTINATARIO -> un solo cliente comprador ---

def test_prodalam_varios_destinatarios_un_solo_comprador():
    historicas = [
        _fila(cliente="PRODALAM SA", codigo_cliente="0001003518",
              cod_destinatario="0002012245", obra_destino="EMPRESA CONST SIGRO"),
        _fila(cliente="PRODALAM SA", codigo_cliente="0001003518",
              cod_destinatario="0002012124", obra_destino="EBCO"),
    ]
    assert evidencia_destinatario_compatible_con_obra(
        cliente_comprador="PRODALAM SA", cod_destinatario="0002012245",
        obra_candidata="EMPRESA CONST SIGRO", filas_historicas=historicas,
    )
    assert evidencia_destinatario_compatible_con_obra(
        cliente_comprador="PRODALAM SA", cod_destinatario="0002012124",
        obra_candidata="EBCO", filas_historicas=historicas,
    )
    # Nunca se confunde un destinatario con la obra del OTRO.
    assert not evidencia_destinatario_compatible_con_obra(
        cliente_comprador="PRODALAM SA", cod_destinatario="0002012245",
        obra_candidata="EBCO", filas_historicas=historicas,
    )


# --- 4/5. Prioridad de identidad cliente ---

def test_codigo_cliente_conocido_con_rut_y_nombre_compatibles_refuerza():
    agf = _cliente("cliente-agf", "AGF ACEROS DE CHILE SPA", rut="77410131-4")
    catalogo_codigos = _catalogo_codigos_con(tmp_codigo="0001006226", cliente_id="cliente-agf")
    identidad = resolver_identidad_cliente_reforzada(
        rut_documental="77410131-4", nombre_documental="AGF ACEROS DE CHILE SPA",
        codigo_cliente="0001006226", clientes=[agf], catalogo_codigos=catalogo_codigos,
    )
    assert identidad.resultado == RESULTADO_SUGERENCIA_HUMANA
    assert identidad.cliente_id == "cliente-agf"


def test_codigo_cliente_conocido_con_rut_contradictorio_se_abstiene():
    agf = _cliente("cliente-agf", "AGF ACEROS DE CHILE SPA", rut="77410131-4")
    catalogo_codigos = _catalogo_codigos_con(tmp_codigo="0001006226", cliente_id="cliente-agf")
    identidad = resolver_identidad_cliente_reforzada(
        # RUT documental de ESTA guía pertenece a otra entidad conocida.
        rut_documental="96596450-9", nombre_documental="AGF ACEROS DE CHILE SPA",
        codigo_cliente="0001006226", clientes=[agf], catalogo_codigos=catalogo_codigos,
    )
    assert identidad.resultado == RESULTADO_ABSTENCION
    assert identidad.cliente_id is None  # nunca reemplaza la identidad


def test_rut_documental_siempre_gana_sobre_codigo():
    agf = _cliente("cliente-agf", "AGF ACEROS DE CHILE SPA", rut="77410131-4")
    otro = _cliente("cliente-otro", "OTRA EMPRESA SPA", rut="96596450-9")
    catalogo_codigos = _catalogo_codigos_con(tmp_codigo="0001006226", cliente_id="cliente-agf")
    identidad = resolver_identidad_cliente_reforzada(
        rut_documental="96596450-9", nombre_documental="OTRA EMPRESA SPA",
        codigo_cliente="0001006226", clientes=[agf, otro], catalogo_codigos=catalogo_codigos,
    )
    assert identidad.resultado == RESULTADO_SUGERENCIA_HUMANA
    assert identidad.cliente_id == "cliente-otro"
    assert identidad.via == "RUT"


# --- 6. COD DESTINATARIO conocido + cliente resuelto + obra compatible -> refuerza obra ---

def test_enriquecer_obra_desconocida_por_destinatario_refuerza():
    decision = {
        "tipo": "OBRA_DESCONOCIDA", "documento": {"archivo": "473999.jpeg", "numero_guia": "473999"},
        "valor_documental": "EMPRESA CONST SIGRO",
        "contexto": {"cliente_canonico": "PRODALAM SA"},
    }
    filas = [
        _fila(archivo="473999.jpeg", cliente="PRODALAM SA", cod_destinatario="0002012245",
              obra_destino="EMPRESA CONST SIGRO"),
        _fila(archivo="otro.jpeg", cliente="PRODALAM SA", codigo_cliente="0001003518",
              cod_destinatario="0002012245", obra_destino="EMPRESA CONST SIGRO"),
    ]
    resultado = enriquecer_decisiones_obra_por_destinatario(decisiones=[decision], filas=filas)
    evaluacion = resultado[0]["evaluacion_evidencia_destinatario"]
    assert evaluacion["resultado"] == RESULTADO_SUGERENCIA_HUMANA


def test_enriquecer_obra_desconocida_sin_historial_no_refuerza():
    decision = {
        "tipo": "OBRA_DESCONOCIDA", "documento": {"archivo": "1.jpeg", "numero_guia": "1"},
        "valor_documental": "OBRA NUNCA VISTA", "contexto": {"cliente_canonico": "PRODALAM SA"},
    }
    resultado = enriquecer_decisiones_obra_por_destinatario(decisiones=[decision], filas=[])
    evaluacion = resultado[0]["evaluacion_evidencia_destinatario"]
    assert evaluacion["resultado"] == RESULTADO_SIN_EVIDENCIA


# --- 7. COD DESTINATARIO nunca fija DESPACHAR_A por sí solo ---

def test_destino_no_resuelto_solo_recibe_contexto_nunca_despachar_a():
    decision = {
        "tipo": "DESTINO_NO_RESUELTO", "campo": "despachar_a_crudo",
        "documento": {"archivo": "473444.jpeg", "numero_guia": "473444"},
        "valor_documental": "VARGAS BUSTOS 899 SAN MIGUEL",
        "acciones_permitidas": ["REGISTRAR_DIRECCION", "NO_PUEDO_DETERMINAR", "POSPONER"],
    }
    filas = [_fila(archivo="473444.jpeg", cod_destinatario="0002099999", codigo_cliente="0001099999")]
    resultado = enriquecer_decisiones_obra_por_destinatario(decisiones=[decision], filas=filas)
    enriquecida = resultado[0]
    # Nunca toca el campo/valor/acciones de la pregunta de destino.
    assert enriquecida["campo"] == "despachar_a_crudo"
    assert enriquecida["valor_documental"] == "VARGAS BUSTOS 899 SAN MIGUEL"
    assert enriquecida["acciones_permitidas"] == ["REGISTRAR_DIRECCION", "NO_PUEDO_DETERMINAR", "POSPONER"]
    assert "despachar_a_crudo" not in enriquecida.get("contexto", {})
    # Sólo agrega contexto puramente informativo.
    assert enriquecida["contexto"]["cod_destinatario_documental"] == "0002099999"
    assert enriquecida["contexto"]["codigo_cliente_documental"] == "0001099999"


# --- 8. Guía sin códigos -> comportamiento previo intacto ---

def test_guia_sin_codigos_no_cambia_nada():
    decision_cliente = {
        "tipo": "CLIENTE_AUSENTE", "entidad": "CLIENTE",
        "documento": {"archivo": "1.jpeg", "numero_guia": "1"}, "valor_documental": "",
    }
    fila = _fila()  # codigo_cliente/cod_destinatario = "No encontrado" (default)
    catalogo_codigos = CatalogoCodigosCliente("/ruta/inexistente/codigos_cliente.json")
    resultado = enriquecer_decisiones_cliente_por_codigo(
        decisiones=[decision_cliente], filas=[fila], clientes=[], catalogo_codigos=catalogo_codigos,
    )
    evaluacion = resultado[0]["evaluacion_evidencia_codigo"]
    assert evaluacion["resultado"] == RESULTADO_SIN_EVIDENCIA
    assert evaluacion["cliente_id"] is None

    decision_obra = {
        "tipo": "OBRA_DESCONOCIDA", "documento": {"archivo": "1.jpeg", "numero_guia": "1"},
        "valor_documental": "CUALQUIER OBRA", "contexto": {"cliente_canonico": "CUALQUIER CLIENTE"},
    }
    resultado_obra = enriquecer_decisiones_obra_por_destinatario(decisiones=[decision_obra], filas=[fila])
    assert resultado_obra[0]["evaluacion_evidencia_destinatario"]["resultado"] == RESULTADO_SIN_EVIDENCIA

    decision_destino = {
        "tipo": "DESTINO_NO_RESUELTO", "campo": "despachar_a_crudo",
        "documento": {"archivo": "1.jpeg", "numero_guia": "1"}, "valor_documental": "ALGUNA DIRECCION",
    }
    resultado_destino = enriquecer_decisiones_obra_por_destinatario(decisiones=[decision_destino], filas=[fila])
    # Sin códigos documentales: nunca se agrega/crea `contexto`.
    assert "contexto" not in resultado_destino[0]


def _catalogo_codigos_con(*, tmp_codigo, cliente_id):
    import tempfile
    from pathlib import Path

    ruta = Path(tempfile.mkdtemp()) / "codigos_cliente.json"
    catalogo = CatalogoCodigosCliente(ruta)
    catalogo.confirmar(
        codigo=tmp_codigo, cliente_id=cliente_id, actor="JAVIER_DESKTOP", fuente="CLIENTE_CANDIDATO_CONFIRMAR",
        reloj=lambda: datetime(2026, 9, 17, tzinfo=timezone.utc),
    )
    return catalogo


def test_catalogo_codigos_cliente_confirmar_y_buscar_roundtrip(tmp_path):
    catalogo = CatalogoCodigosCliente(tmp_path / "codigos_cliente.json")
    assert catalogo.buscar("0001006226") is None  # nada aprendido todavía
    catalogo.confirmar(
        codigo="0001006226", cliente_id="cliente-agf", actor="JAVIER_DESKTOP",
        fuente="CLIENTE_CANDIDATO_CONFIRMAR",
    )
    assert catalogo.buscar("0001006226") == "cliente-agf"
    # Tolerante a espacios/mayúsculas del OCR, mismo criterio de normalización.
    assert catalogo.buscar(" 0001006226 ") == "cliente-agf"
