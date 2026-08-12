"""Bloque ESTADOS S2: separar CALIDAD DEL DATO (¿requiere revisión, y por
qué?) de TRAZABILIDAD DEL MÉTODO (¿cómo se obtuvo el valor final?).

Un método técnico (geometría, fuzzy, homologación, consenso focal) nunca
fuerza revisión humana por sí solo -- solo la fuerza una incertidumbre
real: dato ausente, ambigüedad real, conflicto, o una recuperación SIN una
segunda señal independiente que la corrobore. Ver
`atlas_core/procesamiento_masivo.py` (`MotivoRevisionDocumento`,
`MetodoObtencionDocumento`) y la auditoría real en `estado_revision_eval/`
(bloques ESTADOS S1/S2) que motivó este bloque.

Los 8 casos de esta suite son los "casos reales obligatorios" pedidos
explícitamente por la especificación de ESTADOS S2 (Fase H).
"""
import json
from unittest.mock import Mock

from atlas_core import procesamiento_masivo
from atlas_core.gestor_viajes import MotivoRevision, agrupar_viajes
from atlas_core.ocr import BloqueOCR
from atlas_core.procesamiento_masivo import procesar_archivo


def _escribir_catalogo(tmp_path, nombre, contenido):
    carpeta = tmp_path / "catalogos"
    carpeta.mkdir(exist_ok=True)
    (carpeta / nombre).write_text(json.dumps(contenido), encoding="utf-8")
    return carpeta


def _datos_base(**overrides):
    datos = {
        "número de guía": "463309",
        "número de transporte": "0000123456",
        "cliente": "ACEROS SUR",
        "obra destino": "PLANTA CENTRAL",
        "chofer": "RODRIGO NAHUELÑIR",
        "RUT del cliente": "11.111.111-1",
        "patente del tracto": "AB1234",
        "patente del carro": "CD5678",
    }
    datos.update(overrides)
    return datos


# --- 1: recuperación geométrica correcta y corroborada (cliente + RUT válido) ---

def test_1_recuperacion_geometrica_de_cliente_corroborada_por_rut_no_fuerza_revision(
    tmp_path, monkeypatch
):
    ruta = tmp_path / "guia.jpg"
    etiqueta = BloqueOCR("SEÑOR(ES)", ((10, 10), (90, 10), (90, 30), (10, 30)), 0.9)
    cliente = BloqueOCR("ACEROS SUR", ((150, 10), (240, 10), (240, 30), (150, 30)), 0.9)
    monkeypatch.setattr(procesamiento_masivo, "leer_texto_imagen", Mock(return_value=["HORMIGON 10MM"]))
    monkeypatch.setattr(procesamiento_masivo, "leer_bloques_imagen", Mock(return_value=[cliente, etiqueta]))
    monkeypatch.setattr(
        procesamiento_masivo, "extraer_datos",
        Mock(return_value=_datos_base(cliente="No encontrado")),
    )

    resultado = procesar_archivo(ruta)

    assert resultado["cliente"] == "ACEROS SUR"
    assert resultado["indicador_revision"] == "OK"
    assert "GEOMETRICO" in resultado["metodos_recuperacion_documento"]
    assert "CLIENTE_SIN_CORROBORAR" not in resultado["motivos_revision_documento"]


# --- 2: SD6486 -> SB6486 mediante catálogo único (homologación corroborada) ---

def test_2_homologacion_patente_candidato_unico_no_fuerza_revision(tmp_path, monkeypatch):
    ruta = tmp_path / "guia.jpg"
    carpeta_catalogos = _escribir_catalogo(
        tmp_path, "vehiculos.json", {"SB6486": {"tipo": "TRACTO"}, "JF4288": {"tipo": "CARRO"}}
    )
    monkeypatch.setattr(procesamiento_masivo, "leer_texto_imagen", Mock(return_value=["HORMIGON 10MM"]))
    monkeypatch.setattr(procesamiento_masivo, "leer_bloques_imagen", Mock(return_value=[]))
    monkeypatch.setattr(
        procesamiento_masivo, "extraer_datos",
        Mock(return_value=_datos_base(**{"patente del tracto": "SD6486", "patente del carro": "JF4288"})),
    )

    resultado = procesar_archivo(ruta, carpeta_catalogos=carpeta_catalogos)

    assert resultado["patente_tracto"] == "SB6486"
    assert resultado["indicador_revision"] == "OK"
    assert "HOMOLOGADO" in resultado["metodos_recuperacion_documento"]
    assert "PATENTE_SIN_HOMOLOGAR" not in resultado["motivos_revision_documento"]
    assert "PATENTE_AMBIGUA" not in resultado["motivos_revision_documento"]


# --- 3/4: "IVAN ROA" antes/después de alta en catálogo ---

def test_3_chofer_geometrico_sin_catalogo_es_revision_legitima(tmp_path, monkeypatch):
    ruta = tmp_path / "guia.jpg"
    bloques = [
        BloqueOCR("RETIRA", ((10, 10), (70, 10), (70, 30), (10, 30)), 0.9),
        BloqueOCR("IVAN ROA", ((120, 10), (250, 10), (250, 30), (120, 30)), 0.8),
    ]
    carpeta_catalogos = _escribir_catalogo(tmp_path, "choferes.json", {})
    monkeypatch.setattr(procesamiento_masivo, "leer_texto_imagen", Mock(return_value=["HORMIGON 10MM"]))
    monkeypatch.setattr(procesamiento_masivo, "leer_bloques_imagen", Mock(return_value=bloques))
    monkeypatch.setattr(
        procesamiento_masivo, "extraer_datos",
        Mock(return_value=_datos_base(chofer="No encontrado")),
    )

    resultado = procesar_archivo(ruta, carpeta_catalogos=carpeta_catalogos)

    assert resultado["chofer"] == "IVAN ROA"
    assert resultado["indicador_revision"] == "REVISAR"
    assert "CHOFER_SIN_CORROBORAR" in resultado["motivos_revision_documento"]


def test_4_chofer_geometrico_con_catalogo_exacto_ya_no_fuerza_revision(tmp_path, monkeypatch):
    ruta = tmp_path / "guia.jpg"
    bloques = [
        BloqueOCR("RETIRA", ((10, 10), (70, 10), (70, 30), (10, 30)), 0.9),
        BloqueOCR("IVAN ROA", ((120, 10), (250, 10), (250, 30), (120, 30)), 0.8),
    ]
    carpeta_catalogos = _escribir_catalogo(
        tmp_path, "choferes.json", {"111111111": {"nombre": "IVAN ROA", "activo": True}}
    )
    monkeypatch.setattr(procesamiento_masivo, "leer_texto_imagen", Mock(return_value=["HORMIGON 10MM"]))
    monkeypatch.setattr(procesamiento_masivo, "leer_bloques_imagen", Mock(return_value=bloques))
    monkeypatch.setattr(
        procesamiento_masivo, "extraer_datos",
        Mock(return_value=_datos_base(chofer="No encontrado", **{"RUT del chofer": "11.111.111-1"})),
    )

    resultado = procesar_archivo(ruta, carpeta_catalogos=carpeta_catalogos)

    assert resultado["chofer"] == "IVAN ROA"
    # Bloque ESTADOS S2: el chofer sigue habiendo llegado por geometría --
    # eso NO cambia -- pero ahora el RUT lo corrobora contra catálogo, y
    # ya no fuerza revisión solo por el método original (geométrico).
    assert resultado["indicador_revision"] == "OK"
    assert "GEOMETRICO" in resultado["metodos_recuperacion_documento"]
    assert "CHOFER_SIN_CORROBORAR" not in resultado["motivos_revision_documento"]


# --- 5: cliente ausente real -> revisión ---

def test_5_cliente_ausente_real_fuerza_revision(tmp_path, monkeypatch):
    ruta = tmp_path / "guia.jpg"
    monkeypatch.setattr(procesamiento_masivo, "leer_texto_imagen", Mock(return_value=["HORMIGON 10MM"]))
    monkeypatch.setattr(procesamiento_masivo, "leer_bloques_imagen", Mock(return_value=[]))
    monkeypatch.setattr(
        procesamiento_masivo, "extraer_datos",
        Mock(return_value=_datos_base(cliente="No encontrado")),
    )

    resultado = procesar_archivo(ruta)

    assert resultado["cliente"] == "No encontrado"
    assert resultado["indicador_revision"] == "REVISAR"
    assert "CLIENTE_AUSENTE" in resultado["motivos_revision_documento"]


# --- 6: conflicto multiguía de patente -> revisión (nivel viaje) ---

def test_6_conflicto_multiguia_patente_tracto_fuerza_revision_del_viaje():
    filas = [
        {"archivo": "a.jpg", "numero_transporte": "0000351135", "patente_tracto": "AB1234", "indicador_revision": "OK"},
        {"archivo": "b.jpg", "numero_transporte": "0000351135", "patente_tracto": "CD5678", "indicador_revision": "OK"},
    ]
    viajes, _ = agrupar_viajes(filas)

    assert len(viajes) == 1
    assert MotivoRevision.CONFLICTO_PATENTE_TRACTO in viajes[0].motivos_revision
    from atlas_core.gestor_viajes import EstadoViaje
    assert viajes[0].estado == EstadoViaje.REQUIERE_REVISION


# --- 7: abstención segura de peso/hora -> no fuerza revisión del documento ---

def test_7_peso_y_hora_ausentes_no_fuerzan_revision_del_documento(tmp_path, monkeypatch):
    ruta = tmp_path / "guia.jpg"
    monkeypatch.setattr(procesamiento_masivo, "leer_texto_imagen", Mock(return_value=["HORMIGON 10MM"]))
    monkeypatch.setattr(procesamiento_masivo, "leer_bloques_imagen", Mock(return_value=[]))
    monkeypatch.setattr(
        procesamiento_masivo, "extraer_datos",
        Mock(return_value=_datos_base(peso="No encontrado")),
    )

    resultado = procesar_archivo(ruta)

    assert resultado["peso_kg"] == "No encontrado"
    assert resultado["hora_entrada_aza"] == "No encontrado"
    assert resultado["hora_salida_aza"] == "No encontrado"
    # Mismo criterio ya establecido en Bloque O1: la ausencia de peso/horas
    # nunca participa en `motivos_revision_documento` ni en
    # `indicador_revision` -- no hay ningún motivo PESO_AUSENTE/HORA_AUSENTE.
    assert resultado["indicador_revision"] == "OK"
    assert "PESO" not in resultado["motivos_revision_documento"]
    assert "HORA" not in resultado["motivos_revision_documento"]


# --- 8: destino de entrega recuperado por geometría, sin corroboración -> revisión ---

def test_8_obra_destino_geometrico_sin_senal_de_corroboracion_fuerza_revision(
    tmp_path, monkeypatch
):
    ruta = tmp_path / "guia.jpg"
    etiqueta = BloqueOCR("OBRA DESTINO", ((10, 50), (115, 50), (115, 70), (10, 70)), 0.9)
    destino = BloqueOCR("PLANTA CENTRAL", ((170, 50), (280, 50), (280, 70), (170, 70)), 0.9)
    monkeypatch.setattr(procesamiento_masivo, "leer_texto_imagen", Mock(return_value=["HORMIGON 10MM"]))
    monkeypatch.setattr(procesamiento_masivo, "leer_bloques_imagen", Mock(return_value=[destino, etiqueta]))
    monkeypatch.setattr(
        procesamiento_masivo, "extraer_datos",
        Mock(return_value=_datos_base(**{"obra destino": "No encontrado"})),
    )

    resultado = procesar_archivo(ruta)

    assert resultado["obra_destino"] == "PLANTA CENTRAL"
    # Deliberadamente conservador: a diferencia de cliente (que sí tiene
    # una señal de corroboración independiente -- RUT), obra_destino no
    # tiene hoy un equivalente -- se mantiene pidiendo revisión hasta que
    # exista una, para no relajar sin evidencia (ver Fase C/D del bloque
    # ESTADOS S2).
    assert resultado["indicador_revision"] == "REVISAR"
    assert "OBRA_DESTINO_SIN_CORROBORAR" in resultado["motivos_revision_documento"]
