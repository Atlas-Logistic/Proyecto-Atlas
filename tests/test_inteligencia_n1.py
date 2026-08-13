"""Bloque INTELIGENCIA N1: normalización semántica controlada de
territorios y entidades.

Principio del bloque: un valor OCR no es la verdad, pero tampoco se
adivina -- VALOR OCR != VALOR NORMALIZADO != VALOR CANÓNICO CORROBORADO.
Cada paso queda trazable (motivo/método) y nunca se sustituye sin
evidencia suficiente (candidato único, con margen).

Ningún test aquí depende de una guía real específica -- reproduce los
patrones estructurales encontrados en la tanda (Fase A) con datos
sintéticos, salvo cuando se documenta explícitamente lo contrario.
"""
from __future__ import annotations

import json
from unittest.mock import Mock

import pytest

from atlas_core import procesamiento_masivo
from atlas_core.catalogos import (
    registrar_alias_seguro,
    resolver_nombre_empresa_difuso,
)
from atlas_core.normalizacion_semantica import (
    normalizar_nombre_societario,
    normalizar_token_societario,
)
from atlas_core.procesamiento_masivo import procesar_archivo
from atlas_core.territorio_chile import (
    ESTADO_COMUNA_AMBIGUA,
    ESTADO_COMUNA_EXACTA,
    ESTADO_COMUNA_NORMALIZADA_SEGURA,
    ESTADO_COMUNA_NO_RECONOCIDA,
    normalizar_comuna,
    normalizar_direccion_con_comunas,
)


def _datos_lineales_completos(**overrides):
    datos = {
        "número de guía": "123456",
        "número de transporte": "0000123456",
        "cliente": "A",
        "obra destino": "B",
        "chofer": "C",
        "RUT del cliente": "11.111.111-1",
        "RUT del chofer": "11.111.111-1",
        "patente del tracto": "AB1234",
        "patente del carro": "CD5678",
    }
    datos.update(overrides)
    return datos


def _preparar_mocks(monkeypatch, datos, texto_lineal="FECHA DE EMISION 11-08-2026"):
    monkeypatch.setattr(procesamiento_masivo, "leer_texto_imagen", Mock(return_value=[texto_lineal]))
    monkeypatch.setattr(procesamiento_masivo, "leer_bloques_imagen", Mock(return_value=[]))
    monkeypatch.setattr(procesamiento_masivo, "extraer_datos", Mock(return_value=datos))


def _escribir_catalogo(tmp_path, nombre_archivo, contenido):
    carpeta = tmp_path / "catalogos"
    carpeta.mkdir(exist_ok=True)
    (carpeta / nombre_archivo).write_text(json.dumps(contenido, ensure_ascii=False), encoding="utf-8")
    return carpeta


# --- 1: comuna exacta ---


def test_comuna_exacta_se_reconoce_sin_tocarla():
    resultado = normalizar_comuna("Providencia")
    assert resultado.estado == ESTADO_COMUNA_EXACTA
    assert resultado.comuna == "Providencia"
    assert resultado.region == "Metropolitana"


# --- 2: comuna typo único seguro ---


def test_comuna_typo_unico_se_normaliza_de_forma_segura():
    resultado = normalizar_comuna("CAUQUBNES")
    assert resultado.estado == ESTADO_COMUNA_NORMALIZADA_SEGURA
    assert resultado.comuna == "Cauquenes"
    assert resultado.region == "Maule"

    resultado2 = normalizar_comuna("CADQUENES")
    assert resultado2.estado == ESTADO_COMUNA_NORMALIZADA_SEGURA
    assert resultado2.comuna == "Cauquenes"


# --- 3: comuna ambigua ---


def test_comuna_ambigua_con_empate_construido_se_abstiene():
    """Empate explícito y determinista: dos comunas reales inventadas a
    la misma distancia de un token corrupto -- nunca se elige por orden."""
    from atlas_core import territorio_chile

    original_indice = dict(territorio_chile._INDICE_COMUNAS)
    original_nombres = territorio_chile._NOMBRES_SIMPLES_COMUNAS
    try:
        # Nombres sintéticos de 8 caracteres para que la similitud de un
        # candidato a 1 posición de distancia quede sobre el umbral
        # (2*7/16 = 0.875 >= 0.87) -- con nombres más cortos la similitud
        # cae bajo el umbral antes de poder probar la ambigüedad real.
        territorio_chile._INDICE_COMUNAS["ZOTAMPUR"] = ("Zotampur", "Región X")
        territorio_chile._INDICE_COMUNAS["ZUTAMPUR"] = ("Zutampur", "Región Y")
        territorio_chile._NOMBRES_SIMPLES_COMUNAS = tuple(territorio_chile._INDICE_COMUNAS.keys())
        resultado = territorio_chile.normalizar_comuna("ZYTAMPUR")  # 1 posición de distancia de ambas
        assert resultado.estado == ESTADO_COMUNA_AMBIGUA
    finally:
        territorio_chile._INDICE_COMUNAS.clear()
        territorio_chile._INDICE_COMUNAS.update(original_indice)
        territorio_chile._NOMBRES_SIMPLES_COMUNAS = original_nombres


# --- 4: margen entre candidatos ---


def test_no_reconocida_sin_similitud_suficiente():
    resultado = normalizar_comuna("METROPOLITANA")
    assert resultado.estado == ESTADO_COMUNA_NO_RECONOCIDA


def test_token_corto_nunca_se_normaliza_por_fuzzy():
    resultado = normalizar_comuna("LO")  # < LONGITUD_MINIMA_COMUNA_DIFUSA
    assert resultado.estado == ESTADO_COMUNA_NO_RECONOCIDA


# --- 5: contexto región/comuna dentro de una dirección completa ---


def test_direccion_completa_dedup_comuna_repetida_corrupta():
    """Caso real (guías 464698/464699): el documento repite la comuna en
    dos campos (COMUNA + CIUDAD); el OCR corrompe uno de los dos. El
    token corrupto se descarta (no se duplica), el legible se conserva,
    y la calle/número quedan intactos."""
    resultado = normalizar_direccion_con_comunas("CATEDRAL 759 CADQUENES CAUQUENES")
    assert resultado == "CATEDRAL 759 CAUQUENES"


def test_direccion_sin_comuna_corrupta_no_se_toca():
    texto = "AVDA IRARRAZAVAL 5497 SANTIAGO NUNOA"
    assert normalizar_direccion_con_comunas(texto) == texto


# --- 6: sufijo societario válido (ya correcto, no se toca) ---


def test_sufijo_societario_valido_no_se_modifica():
    assert normalizar_token_societario("SA") is None
    assert normalizar_token_societario("LTDA") is None
    assert normalizar_nombre_societario("ARMACERO MATCO SA").cambio is False


# --- 7: sufijo OCR corrupto se normaliza de forma general ---


def test_sufijo_ocr_corrupto_se_normaliza():
    assert normalizar_token_societario("LIMITAD") == "LIMITADA"
    assert normalizar_token_societario("CONETRUCTORA") == "CONSTRUCTORA"
    assert normalizar_token_societario("LIDA") == "LTDA"

    resultado = normalizar_nombre_societario("SOC CONETRUCTORA OCL LIMITAD")
    assert resultado.valor_normalizado == "SOC CONSTRUCTORA OCL LIMITADA"
    assert resultado.valor_ocr == "SOC CONETRUCTORA OCL LIMITAD"  # Fase G: OCR original trazable


def test_palabra_real_corta_no_se_confunde_con_forma_abreviada():
    """Bug real encontrado y corregido en este mismo bloque: una
    tolerancia de edición ingenua dejaba "SAN" (real, común en topónimos
    chilenos) a distancia 1 de "SA" y lo corrompía. Las formas cortas
    (SA/SPA/LTDA/EIRL) solo aceptan sustitución en la MISMA longitud."""
    assert normalizar_token_societario("SAN") is None
    assert normalizar_nombre_societario("SALOMON SACK SA SAN BERNARDO").valor_normalizado == (
        "SALOMON SACK SA SAN BERNARDO"
    )


# --- 8: RUT exacto -> entidad canónica ---


def test_rut_exacto_corrobora_cliente_end_to_end(tmp_path, monkeypatch):
    carpeta_catalogos = _escribir_catalogo(
        tmp_path, "empresas.json", {"111111111": {"nombre": "ACEROS PRUEBA SA"}}
    )
    _preparar_mocks(
        monkeypatch,
        _datos_lineales_completos(
            cliente="ACEROS PRUEBA SA", **{"RUT del cliente": "11.111.111-1"}
        ),
    )

    resultado = procesar_archivo(tmp_path / "guia.jpg", carpeta_catalogos=carpeta_catalogos)

    assert resultado["cliente"] == "ACEROS PRUEBA SA"
    assert "CLIENTE_SIN_CORROBORAR" not in resultado["motivos_revision_documento"]
    assert "CLIENTE_NUEVA_ENTIDAD_NO_CATALOGADA" not in resultado["motivos_revision_documento"]


# --- 9: fuzzy único fuerte ---


def test_fuzzy_unico_fuerte_corrobora_cliente():
    catalogo = {"11111111": {"nombre": "EBEMA SA"}}
    resultado = resolver_nombre_empresa_difuso(catalogo, "KBEMA SA")
    assert resultado.estado == "COINCIDENCIA_SEGURA"
    assert resultado.valor_resultado == "EBEMA SA"


def test_dos_campos_independientes_corroboraan_misma_empresa(tmp_path, monkeypatch):
    carpeta_catalogos = _escribir_catalogo(
        tmp_path, "empresas.json", {"781707902": {"nombre": "ARMACERO MATCO SA"}}
    )
    _preparar_mocks(
        monkeypatch,
        _datos_lineales_completos(
            cliente="ARMACERO MICO",
            **{"obra destino": "ARMACERO MATCO", "RUT del cliente": "No encontrado"},
        ),
    )

    resultado = procesar_archivo(tmp_path / "guia.jpg", carpeta_catalogos=carpeta_catalogos)

    assert resultado["cliente"] == "ARMACERO MATCO SA"
    assert "FUZZY" in resultado["metodos_recuperacion_documento"]
    assert "OBRA_DESTINO_SIN_CORROBORAR" not in resultado["motivos_revision_documento"]


def test_nombre_exacto_unico_de_chofer_completa_rut_desde_catalogo(tmp_path, monkeypatch):
    carpeta_catalogos = _escribir_catalogo(
        tmp_path,
        "choferes.json",
        {"154542973": {"nombre": "RODRIGO NAHUELÑIR", "activo": True, "aliases": []}},
    )
    _preparar_mocks(
        monkeypatch,
        _datos_lineales_completos(
            chofer="RODRIGO NAHUELÑIR", **{"RUT del chofer": "No encontrado"}
        ),
    )

    resultado = procesar_archivo(tmp_path / "guia.jpg", carpeta_catalogos=carpeta_catalogos)

    assert resultado["chofer"] == "RODRIGO NAHUELÑIR"
    assert resultado["rut_chofer"] == "15.454.297-3"
    assert "CATALOGO" in resultado["metodos_recuperacion_documento"]


def test_nombre_exacto_con_rut_catalogo_invalido_no_publica_ni_corrobora(
    tmp_path, monkeypatch
):
    carpeta_catalogos = _escribir_catalogo(
        tmp_path,
        "choferes.json",
        {"154542974": {"nombre": "PERSONA LEGIBLE", "activo": True, "aliases": []}},
    )
    _preparar_mocks(
        monkeypatch,
        _datos_lineales_completos(
            chofer="No encontrado", **{"RUT del chofer": "No encontrado"}
        ),
    )
    monkeypatch.setattr(
        procesamiento_masivo,
        "_extraer_chofer_geometrico",
        Mock(return_value={"valor": "PERSONA LEGIBLE"}),
    )

    resultado = procesar_archivo(tmp_path / "guia.jpg", carpeta_catalogos=carpeta_catalogos)

    assert resultado["rut_chofer"] == "No encontrado"
    assert "CATALOGO" not in resultado["metodos_recuperacion_documento"]
    assert "CHOFER_SIN_CORROBORAR" in resultado["motivos_revision_documento"]
    assert resultado["indicador_revision"] == "REVISAR"


def test_corroboracion_cruzada_se_abstiene_si_obra_apunta_a_otra_empresa(tmp_path, monkeypatch):
    carpeta_catalogos = _escribir_catalogo(
        tmp_path,
        "empresas.json",
        {
            "781707902": {"nombre": "ARMACERO MATCO SA"},
            "909700000": {"nombre": "SALOMON SACK SA"},
        },
    )
    _preparar_mocks(
        monkeypatch,
        _datos_lineales_completos(
            cliente="ARMACERO MICO",
            **{"obra destino": "SALOMON SACK SA", "RUT del cliente": "No encontrado"},
        ),
    )

    resultado = procesar_archivo(tmp_path / "guia.jpg", carpeta_catalogos=carpeta_catalogos)

    assert resultado["cliente"] == "ARMACERO MICO"


# --- 10: fuzzy ambiguo -> revisión ---


def test_fuzzy_ambiguo_entre_dos_empresas_similares_se_abstiene():
    catalogo = {
        "11111111": {"nombre": "COMERCIAL ANDINA SPA"},
        "22222222": {"nombre": "COMERCIAL ANDINO SPA"},
    }
    resultado = resolver_nombre_empresa_difuso(catalogo, "COMERCIAL ANDIN SPA")
    assert resultado.estado == "AMBIGUO"


# --- 11: conservar OCR original (trazabilidad) ---


def test_normalizacion_conserva_ocr_original_en_el_resultado():
    resultado = normalizar_nombre_societario("I SOC CONETRUCTORA OCL LIMITAD")
    assert resultado.valor_ocr == "I SOC CONETRUCTORA OCL LIMITAD"
    assert resultado.valor_normalizado == "SOC CONSTRUCTORA OCL LIMITADA"
    assert resultado.cambio is True


# --- 12: alias seguro se aprende ---


def test_alias_seguro_se_registra_y_se_reutiliza(tmp_path):
    ruta = tmp_path / "empresas.json"
    ruta.write_text(json.dumps({"11111111": {"nombre": "EBEMA SA"}}), encoding="utf-8")

    aprendido = registrar_alias_seguro(ruta, "11111111", "EDMA SA")
    assert aprendido is True

    catalogo_actualizado = json.loads(ruta.read_text(encoding="utf-8"))
    assert "EDMA SA" in catalogo_actualizado["11111111"]["aliases"]

    # Segunda vez: ya está registrado, no reescribe ni duplica.
    assert registrar_alias_seguro(ruta, "11111111", "EDMA SA") is False
    catalogo_final = json.loads(ruta.read_text(encoding="utf-8"))
    assert catalogo_final["11111111"]["aliases"].count("EDMA SA") == 1


# --- 13: alias ambiguo no se aprende ---


def test_alias_que_pertenece_a_otro_registro_no_se_aprende(tmp_path):
    ruta = tmp_path / "empresas.json"
    ruta.write_text(
        json.dumps({
            "11111111": {"nombre": "EBEMA SA"},
            "22222222": {"nombre": "EDMA SA"},  # ya existe como nombre CANONICO de otro
        }),
        encoding="utf-8",
    )
    assert registrar_alias_seguro(ruta, "11111111", "EDMA SA") is False
    catalogo = json.loads(ruta.read_text(encoding="utf-8"))
    assert "aliases" not in catalogo["11111111"] or "EDMA SA" not in catalogo["11111111"].get("aliases", [])


# --- 14: cliente corroborado end-to-end (RUT + alias aprendido) ---


def test_cliente_corroborado_via_rut_aprende_alias_para_la_proxima(tmp_path, monkeypatch):
    carpeta_catalogos = _escribir_catalogo(tmp_path, "empresas.json", {"111111111": {"nombre": "EBEMA SA"}})
    _preparar_mocks(
        monkeypatch,
        _datos_lineales_completos(cliente="EDMA SA", **{"RUT del cliente": "11.111.111-1"}),
    )

    resultado = procesar_archivo(tmp_path / "guia.jpg", carpeta_catalogos=carpeta_catalogos)

    assert resultado["cliente"] == "EBEMA SA"
    assert "FUZZY" not in resultado["metodos_recuperacion_documento"]  # corroboró por RUT, no por fuzzy
    catalogo_final = json.loads((carpeta_catalogos / "empresas.json").read_text(encoding="utf-8"))
    assert "EDMA SA" in catalogo_final["111111111"].get("aliases", [])


# --- 15: obra destino corroborada (mecanismo existente, código destinatario) ---


def test_obra_destino_se_normaliza_y_conserva_corroboracion_conservadora(tmp_path, monkeypatch):
    """La normalización societaria (Fase E) limpia el texto de OBRA
    DESTINO aunque no exista corroboración de catálogo -- el motivo de
    revisión de obra destino se mantiene deliberadamente conservador
    (Fase H/L: no maquillar un estado que sigue sin corroboración real
    e independiente del documento)."""
    carpeta_catalogos = _escribir_catalogo(tmp_path, "destinos.json", {})
    _escribir_catalogo(tmp_path, "empresas.json", {})
    _preparar_mocks(
        monkeypatch,
        _datos_lineales_completos(**{"obra destino": "SOC CONETRUCTORA OCL LIMITAD"}),
    )

    resultado = procesar_archivo(tmp_path / "guia.jpg", carpeta_catalogos=carpeta_catalogos)

    assert resultado["obra_destino"] == "SOC CONSTRUCTORA OCL LIMITADA"
    assert "NORMALIZADO" in resultado["metodos_recuperacion_documento"]


# --- 16: chofer corroborado (RUT con dígito verificador K) ---


def test_chofer_corroborado_con_rut_terminado_en_k(tmp_path, monkeypatch):
    """Bug real corregido en este bloque: `buscar_rut_chofer` truncaba el
    RUT justo antes de un dígito verificador K, así que nunca calzaba
    contra el catálogo aunque el chofer sí estuviera cargado ahí."""
    carpeta_catalogos = _escribir_catalogo(
        tmp_path, "choferes.json", {"10833150K": {"nombre": "JOSE LAZCANO", "activo": True}}
    )
    monkeypatch.setattr(
        procesamiento_masivo, "leer_texto_imagen",
        Mock(return_value=[
            "FECHA DE EMISION 11-08-2026",
            "RETIRA JOSE LAZCANO",
            "RUT CHOFER :10.833.150-K",
        ]),
    )
    monkeypatch.setattr(procesamiento_masivo, "leer_bloques_imagen", Mock(return_value=[]))
    monkeypatch.setattr(
        procesamiento_masivo, "extraer_datos",
        Mock(return_value=_datos_lineales_completos(chofer="JOSE LAZCANO", **{"RUT del chofer": "10833150-K"})),
    )

    resultado = procesar_archivo(tmp_path / "guia.jpg", carpeta_catalogos=carpeta_catalogos)

    assert "CHOFER_SIN_CORROBORAR" not in resultado["motivos_revision_documento"]


# --- 17: desbloqueo de geocodificación por normalización de comuna ---


def test_normalizacion_de_comuna_desbloquea_geocodificacion():
    """La consulta real enviada al geocodificador ya no contiene el token
    corrupto -- reproduce el desbloqueo real (464698/464699)."""
    from atlas_core.rutas.modelos import CandidatoGeocodificacion, Coordenadas, EstadoRuta, ResultadoGeocodificacion
    from atlas_core.rutas.destino_entrega import resolver_destino_entrega
    from atlas_core.rutas.proveedor import ProveedorRutasSimulado

    texto = "CATEDRAL 759 CADQUENES CAUQUENES"
    consulta_limpia = "CATEDRAL 759 CAUQUENES, Chile"
    candidato = CandidatoGeocodificacion(
        Coordenadas(-72.31, -35.97), "Catedral, Cauquenes, Chile", 0.8, "Cauquenes", "Maule",
    )
    proveedor = ProveedorRutasSimulado(geocodificaciones={
        consulta_limpia: ResultadoGeocodificacion(EstadoRuta.REQUIERE_REVISION, (candidato,), "")
    })

    resultado = resolver_destino_entrega(texto, proveedor)

    assert resultado.estado == "RESUELTO"
    assert resultado.despachar_a_crudo == texto  # el crudo documental nunca se pierde


# --- 18: no regresión -- ver `python -m pytest -q` (suite completa) ---
