"""Bloque ESTADOS S2.2: cubrir enriquecer_datos_con_catalogos() dentro del
modelo de calidad/trazabilidad de ESTADOS S2.

Hallazgo real que motiva este bloque (guía 383295, ver
estado_revision_eval/s2_1/): `enriquecer_datos_con_catalogos()` (mecanismo
preexistente, anterior a S1/S2) puede reemplazar cliente/chofer/obra
destino contra los catálogos maestros SIN dejar ningún rastro de método
ni de motivo de revisión -- un documento con "OBRA DESTINO" en blanco en
la propia guía terminaba "OK" con un nombre inventado desde el código
"COD DESTINATARIO". Este bloque agrega el método CATALOGO y, para
cliente/chofer (corroborados por RUT exacto), lo deja informativo; para
obra destino (sin una señal de corroboración equivalente al RUT),
cualquier cambio de catálogo sigue pidiendo revisión, sin excepción.
"""
import json
from unittest.mock import Mock

from atlas_core import procesamiento_masivo
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


# --- 1: cliente vacío + RUT exacto en catálogo -> confirmado, método CATALOGO ---

def test_1_cliente_por_rut_exacto_catalogo_no_fuerza_revision(tmp_path, monkeypatch):
    ruta = tmp_path / "guia.jpg"
    carpeta_catalogos = _escribir_catalogo(
        tmp_path, "empresas.json", {"111111111": {"nombre": "ACEROS SUR SPA"}}
    )
    monkeypatch.setattr(procesamiento_masivo, "leer_texto_imagen", Mock(return_value=["HORMIGON 10MM"]))
    monkeypatch.setattr(procesamiento_masivo, "leer_bloques_imagen", Mock(return_value=[]))
    monkeypatch.setattr(
        procesamiento_masivo, "extraer_datos",
        Mock(return_value=_datos_base(cliente="ACEROS SUR")),
    )

    resultado = procesar_archivo(ruta, carpeta_catalogos=carpeta_catalogos)

    assert resultado["cliente"] == "ACEROS SUR SPA"
    assert resultado["indicador_revision"] == "OK"
    assert "CATALOGO" in resultado["metodos_recuperacion_documento"]
    assert "CLIENTE_SIN_CORROBORAR" not in resultado["motivos_revision_documento"]


# --- 2: cliente sin RUT que calce en catálogo -> catálogo no lo toca ---

def test_2_cliente_sin_coincidencia_de_rut_en_catalogo_no_cambia(tmp_path, monkeypatch):
    ruta = tmp_path / "guia.jpg"
    carpeta_catalogos = _escribir_catalogo(
        tmp_path, "empresas.json", {"222222222": {"nombre": "OTRA EMPRESA SPA"}}
    )
    monkeypatch.setattr(procesamiento_masivo, "leer_texto_imagen", Mock(return_value=["HORMIGON 10MM"]))
    monkeypatch.setattr(procesamiento_masivo, "leer_bloques_imagen", Mock(return_value=[]))
    monkeypatch.setattr(
        procesamiento_masivo, "extraer_datos",
        Mock(return_value=_datos_base(cliente="ACEROS SUR", **{"RUT del cliente": "11.111.111-1"})),
    )

    resultado = procesar_archivo(ruta, carpeta_catalogos=carpeta_catalogos)

    assert resultado["cliente"] == "ACEROS SUR"
    assert "CATALOGO" not in resultado["metodos_recuperacion_documento"]


# --- 3: chofer por RUT exacto en catálogo -> confirmado, método CATALOGO ---

def test_3_chofer_por_rut_exacto_catalogo_no_fuerza_revision(tmp_path, monkeypatch):
    ruta = tmp_path / "guia.jpg"
    carpeta_catalogos = _escribir_catalogo(
        tmp_path, "choferes.json", {"111111111": {"nombre": "RODRIGO NAHUELÑIR MUÑOZ", "activo": True}}
    )
    monkeypatch.setattr(procesamiento_masivo, "leer_texto_imagen", Mock(return_value=["HORMIGON 10MM"]))
    monkeypatch.setattr(procesamiento_masivo, "leer_bloques_imagen", Mock(return_value=[]))
    monkeypatch.setattr(
        procesamiento_masivo, "extraer_datos",
        Mock(return_value=_datos_base(chofer="RODRIGO NAHUELÑIR", **{"RUT del chofer": "11.111.111-1"})),
    )

    resultado = procesar_archivo(ruta, carpeta_catalogos=carpeta_catalogos)

    assert resultado["chofer"] == "RODRIGO NAHUELÑIR MUÑOZ"
    assert resultado["indicador_revision"] == "OK"
    assert "CATALOGO" in resultado["metodos_recuperacion_documento"]
    assert "CHOFER_SIN_CORROBORAR" not in resultado["motivos_revision_documento"]


# --- 4: chofer sin RUT que calce en catálogo -> catálogo no lo toca ---

def test_4_chofer_sin_coincidencia_de_rut_en_catalogo_no_cambia(tmp_path, monkeypatch):
    ruta = tmp_path / "guia.jpg"
    carpeta_catalogos = _escribir_catalogo(
        tmp_path, "choferes.json", {"222222222": {"nombre": "OTRO CHOFER", "activo": True}}
    )
    monkeypatch.setattr(procesamiento_masivo, "leer_texto_imagen", Mock(return_value=["HORMIGON 10MM"]))
    monkeypatch.setattr(procesamiento_masivo, "leer_bloques_imagen", Mock(return_value=[]))
    monkeypatch.setattr(
        procesamiento_masivo, "extraer_datos",
        Mock(return_value=_datos_base(**{"RUT del chofer": "11.111.111-1"})),
    )

    resultado = procesar_archivo(ruta, carpeta_catalogos=carpeta_catalogos)

    assert resultado["chofer"] == "RODRIGO NAHUELÑIR"
    assert "CATALOGO" not in resultado["metodos_recuperacion_documento"]


# --- 5: obra_destino vacío + catálogo sugiere obra vía COD DESTINATARIO ---
#          -> REVISAR, nunca OK silencioso (caso real 383295) ---

def test_5_obra_destino_vacio_completado_por_catalogo_fuerza_revision(tmp_path, monkeypatch):
    ruta = tmp_path / "guia.jpg"
    carpeta_catalogos = _escribir_catalogo(
        tmp_path, "destinos.json", {"0002012245": {"nombre": "EMPRESA CONST SIGRO", "rut_empresa": "93772000"}}
    )
    monkeypatch.setattr(
        procesamiento_masivo, "leer_texto_imagen",
        Mock(return_value=["HORMIGON 10MM", "COD DESTINATARIO : 0002012245"]),
    )
    monkeypatch.setattr(procesamiento_masivo, "leer_bloques_imagen", Mock(return_value=[]))
    monkeypatch.setattr(
        procesamiento_masivo, "extraer_datos",
        Mock(return_value=_datos_base(**{"obra destino": "No encontrado"})),
    )

    resultado = procesar_archivo(ruta, carpeta_catalogos=carpeta_catalogos)

    assert resultado["obra_destino"] == "EMPRESA CONST SIGRO"
    # Caso 383295: nunca OK silencioso solo porque el catálogo sugirió un
    # valor plausible -- el campo documental estaba vacío.
    assert resultado["indicador_revision"] == "REVISAR"
    assert "OBRA_DESTINO_SIN_CORROBORAR" in resultado["motivos_revision_documento"]
    assert "CATALOGO" in resultado["metodos_recuperacion_documento"]


# --- 6: obra_destino documental + catálogo coincide -> sin cambio, sin motivo nuevo ---

def test_6_obra_destino_documental_coincide_con_catalogo_no_agrega_motivo(tmp_path, monkeypatch):
    ruta = tmp_path / "guia.jpg"
    carpeta_catalogos = _escribir_catalogo(
        tmp_path, "destinos.json", {"0002012245": {"nombre": "EMPRESA CONST SIGRO", "rut_empresa": "93772000"}}
    )
    monkeypatch.setattr(
        procesamiento_masivo, "leer_texto_imagen",
        Mock(return_value=["HORMIGON 10MM", "COD DESTINATARIO : 0002012245"]),
    )
    monkeypatch.setattr(procesamiento_masivo, "leer_bloques_imagen", Mock(return_value=[]))
    monkeypatch.setattr(
        procesamiento_masivo, "extraer_datos",
        Mock(return_value=_datos_base(**{"obra destino": "EMPRESA CONST SIGRO"})),
    )

    resultado = procesar_archivo(ruta, carpeta_catalogos=carpeta_catalogos)

    assert resultado["obra_destino"] == "EMPRESA CONST SIGRO"
    assert resultado["indicador_revision"] == "OK"
    assert "OBRA_DESTINO_SIN_CORROBORAR" not in resultado["motivos_revision_documento"]


# --- 7: obra_destino documental + catálogo contradice -> REVISAR (conservador) ---

def test_7_obra_destino_documental_contradicho_por_catalogo_fuerza_revision(tmp_path, monkeypatch):
    ruta = tmp_path / "guia.jpg"
    carpeta_catalogos = _escribir_catalogo(
        tmp_path, "destinos.json", {"0002012245": {"nombre": "EMPRESA CONST SIGRO", "rut_empresa": "93772000"}}
    )
    monkeypatch.setattr(
        procesamiento_masivo, "leer_texto_imagen",
        Mock(return_value=["HORMIGON 10MM", "COD DESTINATARIO : 0002012245"]),
    )
    monkeypatch.setattr(procesamiento_masivo, "leer_bloques_imagen", Mock(return_value=[]))
    monkeypatch.setattr(
        procesamiento_masivo, "extraer_datos",
        Mock(return_value=_datos_base(**{"obra destino": "CONSTRUCTORA SIGRO SA"})),
    )

    resultado = procesar_archivo(ruta, carpeta_catalogos=carpeta_catalogos)

    assert resultado["obra_destino"] == "EMPRESA CONST SIGRO"
    assert resultado["indicador_revision"] == "REVISAR"
    assert "OBRA_DESTINO_SIN_CORROBORAR" in resultado["motivos_revision_documento"]


# --- 8: patente exacta en catálogo (vía enriquecimiento) -> confirmada ---

def test_8_patente_exacta_en_catalogo_no_fuerza_revision(tmp_path, monkeypatch):
    ruta = tmp_path / "guia.jpg"
    carpeta_catalogos = _escribir_catalogo(tmp_path, "vehiculos.json", {"AB1234": {"tipo": "TRACTO"}})
    monkeypatch.setattr(procesamiento_masivo, "leer_texto_imagen", Mock(return_value=["HORMIGON 10MM"]))
    monkeypatch.setattr(procesamiento_masivo, "leer_bloques_imagen", Mock(return_value=[]))
    monkeypatch.setattr(
        procesamiento_masivo, "extraer_datos",
        Mock(return_value=_datos_base(**{"patente del tracto": "AB1234"})),
    )

    resultado = procesar_archivo(ruta, carpeta_catalogos=carpeta_catalogos)

    assert resultado["patente_tracto"] == "AB1234"
    assert resultado["indicador_revision"] == "OK"
    assert "PATENTE_SIN_HOMOLOGAR" not in resultado["motivos_revision_documento"]
    assert "PATENTE_AMBIGUA" not in resultado["motivos_revision_documento"]


# --- 9: patente con corrección OCR segura (ya cubierto por P2, no regresión) ---

def test_9_patente_correccion_ocr_segura_sigue_sin_forzar_revision(tmp_path, monkeypatch):
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


# --- 10: patente ambigua (ya cubierto por P2, no regresión) ---

def test_10_patente_ambigua_sigue_forzando_revision(tmp_path, monkeypatch):
    ruta = tmp_path / "guia.jpg"
    carpeta_catalogos = _escribir_catalogo(
        tmp_path, "vehiculos.json", {"AD1234": {"tipo": "TRACTO"}, "A81234": {"tipo": "TRACTO"}},
    )
    monkeypatch.setattr(procesamiento_masivo, "leer_texto_imagen", Mock(return_value=["HORMIGON 10MM"]))
    monkeypatch.setattr(procesamiento_masivo, "leer_bloques_imagen", Mock(return_value=[]))
    monkeypatch.setattr(
        procesamiento_masivo, "extraer_datos",
        Mock(return_value=_datos_base(**{"patente del tracto": "AB1234", "patente del carro": "No encontrado"})),
    )

    resultado = procesar_archivo(ruta, carpeta_catalogos=carpeta_catalogos)

    assert resultado["patente_tracto"] == "AB1234"
    assert resultado["indicador_revision"] == "REVISAR"
    assert "PATENTE_AMBIGUA" in resultado["motivos_revision_documento"]


# --- 11: trazabilidad CATALOGO persistida en la columna de métodos ---

def test_11_metodo_catalogo_persistido_en_columna(tmp_path, monkeypatch):
    ruta = tmp_path / "guia.jpg"
    carpeta_catalogos = _escribir_catalogo(
        tmp_path, "empresas.json", {"111111111": {"nombre": "ACEROS SUR SPA"}}
    )
    monkeypatch.setattr(procesamiento_masivo, "leer_texto_imagen", Mock(return_value=["HORMIGON 10MM"]))
    monkeypatch.setattr(procesamiento_masivo, "leer_bloques_imagen", Mock(return_value=[]))
    monkeypatch.setattr(
        procesamiento_masivo, "extraer_datos",
        Mock(return_value=_datos_base(cliente="ACEROS SUR")),
    )

    resultado = procesar_archivo(ruta, carpeta_catalogos=carpeta_catalogos)
    assert "CATALOGO" in resultado["metodos_recuperacion_documento"].split(" | ")


# --- 12: motivo de revisión explícito para el caso de destino sin corroborar ---

def test_12_motivo_explicito_obra_destino_sin_corroborar(tmp_path, monkeypatch):
    ruta = tmp_path / "guia.jpg"
    carpeta_catalogos = _escribir_catalogo(
        tmp_path, "destinos.json", {"0002012245": {"nombre": "EMPRESA CONST SIGRO"}}
    )
    monkeypatch.setattr(
        procesamiento_masivo, "leer_texto_imagen",
        Mock(return_value=["HORMIGON 10MM", "COD DESTINATARIO : 0002012245"]),
    )
    monkeypatch.setattr(procesamiento_masivo, "leer_bloques_imagen", Mock(return_value=[]))
    monkeypatch.setattr(
        procesamiento_masivo, "extraer_datos",
        Mock(return_value=_datos_base(**{"obra destino": "No encontrado"})),
    )

    resultado = procesar_archivo(ruta, carpeta_catalogos=carpeta_catalogos)
    assert resultado["motivos_revision_documento"].split(" | ") == ["OBRA_DESTINO_SIN_CORROBORAR"]


# --- 13: combinación GEOMETRICO + CATALOGO sobre el mismo campo, sin duplicar motivo ---

def test_13_combinacion_geometrico_y_catalogo_en_obra_destino_no_duplica_motivo(
    tmp_path, monkeypatch
):
    ruta = tmp_path / "guia.jpg"
    bloques = [
        BloqueOCR("OBRA DESTINO", ((10, 50), (115, 50), (115, 70), (10, 70)), 0.9),
        BloqueOCR("PLANTA VIEJA", ((170, 50), (280, 50), (280, 70), (170, 70)), 0.9),
    ]
    carpeta_catalogos = _escribir_catalogo(
        tmp_path, "destinos.json", {"0002012245": {"nombre": "EMPRESA CONST SIGRO"}}
    )
    monkeypatch.setattr(
        procesamiento_masivo, "leer_texto_imagen",
        Mock(return_value=["HORMIGON 10MM", "COD DESTINATARIO : 0002012245"]),
    )
    monkeypatch.setattr(procesamiento_masivo, "leer_bloques_imagen", Mock(return_value=bloques))
    monkeypatch.setattr(
        procesamiento_masivo, "extraer_datos",
        Mock(return_value=_datos_base(**{"obra destino": "No encontrado"})),
    )

    resultado = procesar_archivo(ruta, carpeta_catalogos=carpeta_catalogos)

    # El catálogo tiene la última palabra sobre el valor final (corre
    # después de la geometría), pero ambos métodos quedan trazados.
    assert resultado["obra_destino"] == "EMPRESA CONST SIGRO"
    assert "GEOMETRICO" in resultado["metodos_recuperacion_documento"]
    assert "CATALOGO" in resultado["metodos_recuperacion_documento"]
    assert resultado["motivos_revision_documento"].count("OBRA_DESTINO_SIN_CORROBORAR") == 1


# --- 15: regresión real -- guía 383295 ---

def test_15_regresion_real_guia_383295_obra_destino_en_blanco_no_relaja_silenciosamente(
    tmp_path, monkeypatch
):
    """Caso real (ver estado_revision_eval/s2_1/): la guía 383295 tiene el
    campo OBRA DESTINO en blanco en el documento físico, pero el código
    COD DESTINATARIO impreso resuelve, vía catálogo, a un nombre de
    empresa -- y el documento terminaba "OK" sin ningún motivo de
    revisión. No se hardcodea el número de guía; se reproduce el patrón
    estructural real (campo vacío + resolución exclusiva por catálogo)
    con datos sintéticos equivalentes a los del caso real."""
    ruta = tmp_path / "guia.jpg"
    carpeta_catalogos = _escribir_catalogo(
        tmp_path, "destinos.json", {"0002012245": {"nombre": "EMPRESA CONST SIGRO", "rut_empresa": "93772000"}}
    )
    monkeypatch.setattr(
        procesamiento_masivo, "leer_texto_imagen",
        Mock(return_value=[
            "SEÑOR(ES) : SALOMON SACK SA",
            "OBRA DESTINO :",
            "COD DESTINATARIO : 0002012245",
        ]),
    )
    monkeypatch.setattr(procesamiento_masivo, "leer_bloques_imagen", Mock(return_value=[]))
    monkeypatch.setattr(
        procesamiento_masivo, "extraer_datos",
        Mock(return_value=_datos_base(cliente="SALOMON SACK SA", **{"obra destino": "No encontrado"})),
    )

    resultado = procesar_archivo(ruta, carpeta_catalogos=carpeta_catalogos)

    assert resultado["obra_destino"] == "EMPRESA CONST SIGRO"
    assert resultado["indicador_revision"] == "REVISAR"
    assert "OBRA_DESTINO_SIN_CORROBORAR" in resultado["motivos_revision_documento"]
