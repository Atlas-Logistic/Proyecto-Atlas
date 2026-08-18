import csv
import json
import sys
from datetime import date
from unittest.mock import Mock

import pytest

import analizar_guias_masivo
from atlas_core import procesamiento_masivo
from atlas_core.ocr import BloqueOCR
from atlas_core.procesamiento_masivo import (
    COLUMNAS,
    descubrir_archivos,
    extraer_descripcion_material,
    extraer_fecha,
    procesar_archivo,
    procesar_carpeta,
)


def _crear_archivo(ruta):
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_bytes(b"simulado")


def test_procesar_archivo_integra_asociacion_geometrica_y_mantiene_revision(
    tmp_path, monkeypatch
):
    ruta = tmp_path / "nombre_sin_datos.jpg"
    etiqueta = BloqueOCR("SEÑOR(ES)", ((10, 10), (90, 10), (90, 30), (10, 30)), 0.9)
    cliente = BloqueOCR("ACEROS SUR", ((150, 10), (240, 10), (240, 30), (150, 30)), 0.9)
    destino_etiqueta = BloqueOCR("OBRA DESTINO", ((10, 50), (115, 50), (115, 70), (10, 70)), 0.9)
    destino = BloqueOCR("PLANTA CENTRAL", ((170, 50), (280, 50), (280, 70), (170, 70)), 0.9)
    monkeypatch.setattr(procesamiento_masivo, "leer_texto_imagen", Mock(return_value=[]))
    monkeypatch.setattr(
        procesamiento_masivo,
        "leer_bloques_imagen",
        Mock(return_value=[destino, cliente, destino_etiqueta, etiqueta]),
    )
    monkeypatch.setattr(
        procesamiento_masivo,
        "extraer_datos",
        Mock(return_value={"número de guía": "123456", "cliente": "No encontrado", "obra destino": "No encontrado"}),
    )

    resultado = procesar_archivo(ruta)

    assert resultado["cliente"] == "ACEROS SUR"
    assert resultado["obra_destino"] == "PLANTA CENTRAL"
    assert resultado["indicador_revision"] == "REVISAR"


def test_procesar_archivo_no_reemplaza_valores_lineales_correctos(tmp_path, monkeypatch):
    ruta = tmp_path / "guia.jpg"
    datos = {
        "número de guía": "123456",
        "número de transporte": "0000123456",
        "cliente": "CLIENTE LINEAL",
        "obra destino": "DESTINO LINEAL",
        "chofer": "MARIO SOTO",
        "RUT del cliente": "11.111.111-1",
        "RUT del chofer": "11.111.111-1",
        "patente del tracto": "AB1234",
        "patente del carro": "CD5678",
    }
    leer_bloques = Mock()
    focal = Mock()
    monkeypatch.setattr(
        procesamiento_masivo,
        "leer_texto_imagen",
        Mock(return_value=["FECHA DE EMISIÓN 23-06-2025"]),
    )
    monkeypatch.setattr(procesamiento_masivo, "leer_bloques_imagen", leer_bloques)
    monkeypatch.setattr(procesamiento_masivo, "_leer_transporte_focal", focal)
    monkeypatch.setattr(procesamiento_masivo, "extraer_datos", Mock(return_value=datos))

    resultado = procesar_archivo(ruta)

    assert resultado["cliente"] == "CLIENTE LINEAL"
    assert resultado["obra_destino"] == "DESTINO LINEAL"
    assert resultado["numero_transporte"] == "0000123456"
    leer_bloques.assert_not_called()
    focal.assert_not_called()


def test_procesar_archivo_integra_transporte_corregido_y_reutiliza_bloques(
    tmp_path, monkeypatch
):
    ruta = tmp_path / "sin_numero_en_nombre.jpg"
    bloques = [
        BloqueOCR("NRO TRANSPORTE", ((10, 10), (130, 10), (130, 30), (10, 30)), 0.9),
        BloqueOCR("00do348808", ((180, 10), (280, 10), (280, 30), (180, 30)), 0.8),
    ]
    leer_bloques = Mock(return_value=bloques)
    focal = Mock(
        return_value={
            "recorte": (170, 5, 290, 35),
            "lecturas": [
                {"variante": "original", "texto": "0000348808"},
                {"variante": "grises", "texto": "0000348808"},
            ],
        }
    )
    monkeypatch.setattr(procesamiento_masivo, "leer_texto_imagen", Mock(return_value=[]))
    monkeypatch.setattr(procesamiento_masivo, "leer_bloques_imagen", leer_bloques)
    monkeypatch.setattr(procesamiento_masivo, "_leer_transporte_focal", focal)
    monkeypatch.setattr(
        procesamiento_masivo,
        "extraer_datos",
        Mock(
            return_value={
                "número de guía": "123456",
                "número de transporte": "No encontrado",
                "cliente": "CLIENTE LINEAL",
                "obra destino": "DESTINO LINEAL",
            }
        ),
    )

    resultado = procesar_archivo(ruta)

    assert resultado["numero_transporte"] == "0000348808"
    assert resultado["indicador_revision"] == "REVISAR"
    leer_bloques.assert_called_once_with(ruta, lector=None)
    focal.assert_called_once()


def test_procesar_archivo_patentes_geometricas_recuperan_tracto_y_carro_desde_bloques_paddle(
    tmp_path, monkeypatch
):
    """P1: reproduce la guía real con RODRIGO NAHUELÑIR (tracto SB6486 leído
    por Paddle como SD6486, rampla JF4288), pero con las etiquetas repartidas
    en bloques separados como entrega PaddleOCR (no la frase contigua "RETIRA
    PATENTE FECHA LLEGADA" del formato lineal histórico)."""
    ruta = tmp_path / "guia.jpg"
    bloques = [
        BloqueOCR("RETIRA", ((10, 10), (70, 10), (70, 30), (10, 30)), 0.9),
        BloqueOCR("PATENTE", ((10, 40), (80, 40), (80, 60), (10, 60)), 0.9),
        BloqueOCR(":SD6486 CARRO:JF4288", ((10, 70), (230, 70), (230, 90), (10, 90)), 0.85),
        BloqueOCR("FECHA LLEGADA", ((10, 100), (130, 100), (130, 120), (10, 120)), 0.9),
    ]
    monkeypatch.setattr(procesamiento_masivo, "leer_texto_imagen", Mock(return_value=[]))
    monkeypatch.setattr(procesamiento_masivo, "leer_bloques_imagen", Mock(return_value=bloques))
    monkeypatch.setattr(
        procesamiento_masivo,
        "extraer_datos",
        Mock(
            return_value={
                "número de guía": "123456", "número de transporte": "0000123456",
                "cliente": "A", "obra destino": "B", "chofer": "C",
                "patente del tracto": "No encontrado", "patente del carro": "No encontrado",
            }
        ),
    )

    resultado = procesar_archivo(ruta)

    assert resultado["patente_tracto"] == "SD6486"
    assert resultado["patente_rampla"] == "JF4288"
    assert resultado["indicador_revision"] == "REVISAR"


# --- P2: homologación conservadora de patentes contra catálogo de vehículos ---

CATALOGO_VEHICULOS_REAL_464511 = {
    "SB6486": {"tipo": "TRACTO"},
    "JF4288": {"tipo": "CARRO"},
}


def _escribir_catalogo_vehiculos(tmp_path, contenido):
    carpeta = tmp_path / "catalogos"
    carpeta.mkdir(exist_ok=True)
    (carpeta / "vehiculos.json").write_text(json.dumps(contenido), encoding="utf-8")
    return carpeta


def test_procesar_archivo_homologa_sd6486_a_sb6486_y_conserva_jf4288(tmp_path, monkeypatch):
    """P2 end-to-end: la guía real 464511 ya trae SD6486/JF4288 (P1 resuelto);
    con el catálogo real, el tracto se homologa a SB6486 y la rampla exacta
    JF4288 no se modifica. Resto de campos sin cambios."""
    ruta = tmp_path / "guia.jpg"
    carpeta_catalogos = _escribir_catalogo_vehiculos(tmp_path, CATALOGO_VEHICULOS_REAL_464511)
    monkeypatch.setattr(
        procesamiento_masivo, "leer_texto_imagen", Mock(return_value=["HORMIGON 10MM"])
    )
    monkeypatch.setattr(procesamiento_masivo, "leer_bloques_imagen", Mock(return_value=[]))
    monkeypatch.setattr(
        procesamiento_masivo,
        "extraer_datos",
        Mock(
            return_value=_datos_lineales_completos(
                **{
                    "número de guía": "464511", "número de transporte": "0000352449",
                    "cliente": "ARMACERO MATCO SA", "obra destino": "ARMACERO MATCO SA",
                    "chofer": "RODRIGO NAHUELÑIR",
                    "patente del tracto": "SD6486", "patente del carro": "JF4288",
                }
            )
        ),
    )

    resultado = procesar_archivo(ruta, carpeta_catalogos=carpeta_catalogos)

    assert resultado["patente_tracto"] == "SB6486"
    assert resultado["patente_rampla"] == "JF4288"
    assert resultado["numero_guia"] == "464511"
    assert resultado["numero_transporte"] == "0000352449"
    assert resultado["cliente"] == "ARMACERO MATCO SA"
    assert resultado["chofer"] == "RODRIGO NAHUELÑIR"
    # Bloque ESTADOS S2: CORRECCION_OCR_SEGURA es una homologación
    # corroborada por catálogo (candidato único, determinista) -- ya no
    # fuerza revisión solo por haber pasado por geometría/homologación.
    assert resultado["indicador_revision"] == "OK"
    assert "HOMOLOGADO" in resultado["metodos_recuperacion_documento"]
    assert resultado["motivos_revision_documento"] == ""


def test_procesar_archivo_homologacion_ambigua_mantiene_ocr_y_marca_revisar(
    tmp_path, monkeypatch
):
    ruta = tmp_path / "guia.jpg"
    carpeta_catalogos = _escribir_catalogo_vehiculos(
        tmp_path,
        {"AD1234": {"tipo": "TRACTO"}, "A81234": {"tipo": "TRACTO"}},
    )
    monkeypatch.setattr(
        procesamiento_masivo, "leer_texto_imagen", Mock(return_value=["HORMIGON 10MM"])
    )
    monkeypatch.setattr(procesamiento_masivo, "leer_bloques_imagen", Mock(return_value=[]))
    monkeypatch.setattr(
        procesamiento_masivo,
        "extraer_datos",
        Mock(
            return_value=_datos_lineales_completos(
                **{"patente del tracto": "AB1234", "patente del carro": "No encontrado"}
            )
        ),
    )

    resultado = procesar_archivo(ruta, carpeta_catalogos=carpeta_catalogos)

    assert resultado["patente_tracto"] == "AB1234"
    assert resultado["indicador_revision"] == "REVISAR"


def test_procesar_archivo_sin_carpeta_catalogos_no_homologa_patente(tmp_path, monkeypatch):
    """Sin carpeta_catalogos, P2 no se ejecuta: el valor OCR de P1 se
    conserva tal cual, sin inventar ni intentar homologar."""
    ruta = tmp_path / "guia.jpg"
    monkeypatch.setattr(procesamiento_masivo, "leer_texto_imagen", Mock(return_value=[]))
    monkeypatch.setattr(procesamiento_masivo, "leer_bloques_imagen", Mock(return_value=[]))
    monkeypatch.setattr(
        procesamiento_masivo,
        "extraer_datos",
        Mock(
            return_value=_datos_lineales_completos(
                **{"patente del tracto": "SD6486", "patente del carro": "JF4288"}
            )
        ),
    )

    resultado = procesar_archivo(ruta)

    assert resultado["patente_tracto"] == "SD6486"
    assert resultado["patente_rampla"] == "JF4288"


def test_procesar_archivo_p1_geometrico_y_p2_homologacion_encadenados(tmp_path, monkeypatch):
    """No regresión de P1: la recuperación geométrica (bloques Paddle
    fragmentados) y la homologación de catálogo (P2) operan en secuencia
    sobre la misma guía sin interferir entre sí."""
    ruta = tmp_path / "guia.jpg"
    carpeta_catalogos = _escribir_catalogo_vehiculos(tmp_path, CATALOGO_VEHICULOS_REAL_464511)
    bloques = [
        BloqueOCR("RETIRA", ((10, 10), (70, 10), (70, 30), (10, 30)), 0.9),
        BloqueOCR("PATENTE", ((10, 40), (80, 40), (80, 60), (10, 60)), 0.9),
        BloqueOCR(":SD6486 CARRO:JF4288", ((10, 70), (230, 70), (230, 90), (10, 90)), 0.85),
        BloqueOCR("FECHA LLEGADA", ((10, 100), (130, 100), (130, 120), (10, 120)), 0.9),
    ]
    monkeypatch.setattr(
        procesamiento_masivo, "leer_texto_imagen", Mock(return_value=["HORMIGON 10MM"])
    )
    monkeypatch.setattr(procesamiento_masivo, "leer_bloques_imagen", Mock(return_value=bloques))
    monkeypatch.setattr(
        procesamiento_masivo,
        "extraer_datos",
        Mock(
            return_value={
                "número de guía": "464511", "número de transporte": "0000352449",
                "cliente": "ARMACERO MATCO SA", "obra destino": "ARMACERO MATCO SA",
                "chofer": "RODRIGO NAHUELÑIR",
                "patente del tracto": "No encontrado", "patente del carro": "No encontrado",
            }
        ),
    )

    resultado = procesar_archivo(ruta, carpeta_catalogos=carpeta_catalogos)

    assert resultado["patente_tracto"] == "SB6486"
    assert resultado["patente_rampla"] == "JF4288"
    # Bloque ESTADOS S2: ambas patentes terminan homologadas contra
    # catálogo (corroboradas) -- la recuperación geométrica previa (P1) no
    # deja un motivo pendiente una vez que P2 la corrobora.
    assert resultado["indicador_revision"] == "OK"
    assert "GEOMETRICO" in resultado["metodos_recuperacion_documento"]
    assert "HOMOLOGADO" in resultado["metodos_recuperacion_documento"]
    assert resultado["motivos_revision_documento"] == ""


def test_procesar_archivo_consenso_focal_corrige_global_sin_mapa_seis_a_ocho(
    tmp_path, monkeypatch
):
    ruta = tmp_path / "guia.jpg"
    bloques = [
        BloqueOCR("NRO TRANSPORTE", ((10, 10), (130, 10), (130, 30), (10, 30)), 0.9),
        BloqueOCR("00do348608", ((180, 10), (280, 10), (280, 30), (180, 30)), 0.3),
    ]
    monkeypatch.setattr(procesamiento_masivo, "leer_texto_imagen", Mock(return_value=[]))
    monkeypatch.setattr(procesamiento_masivo, "leer_bloques_imagen", Mock(return_value=bloques))
    monkeypatch.setattr(
        procesamiento_masivo, "extraer_datos",
        Mock(return_value={"número de guía": "123456", "número de transporte": "No encontrado", "cliente": "A", "obra destino": "B"}),
    )
    monkeypatch.setattr(
        procesamiento_masivo, "_leer_transporte_focal",
        Mock(return_value={"lecturas": [
            {"variante": "original", "texto": "oo 0000348808"},
            {"variante": "grises", "texto": "oo 00do348808"},
            {"variante": "ampliada_2x", "texto": "000o348608"},
        ]}),
    )

    resultado = procesar_archivo(ruta)

    assert resultado["numero_transporte"] == "0000348808"
    assert resultado["indicador_revision"] == "REVISAR"


def test_procesar_archivo_sin_etiqueta_no_ejecuta_ocr_focal(tmp_path, monkeypatch):
    ruta = tmp_path / "guia.jpg"
    focal = Mock()
    monkeypatch.setattr(procesamiento_masivo, "leer_texto_imagen", Mock(return_value=[]))
    monkeypatch.setattr(procesamiento_masivo, "leer_bloques_imagen", Mock(return_value=[]))
    monkeypatch.setattr(procesamiento_masivo, "_leer_transporte_focal", focal)
    monkeypatch.setattr(
        procesamiento_masivo, "extraer_datos",
        Mock(return_value={"número de guía": "123456", "número de transporte": "No encontrado", "cliente": "A", "obra destino": "B"}),
    )

    assert procesar_archivo(ruta)["numero_transporte"] == "No encontrado"
    focal.assert_not_called()


def test_procesar_archivo_excepcion_ocr_focal_se_abstiene(tmp_path, monkeypatch):
    ruta = tmp_path / "guia.jpg"
    bloques = [
        BloqueOCR("NRO TRANSPORTE", ((10, 10), (130, 10), (130, 30), (10, 30)), 0.9),
        BloqueOCR("000o348808", ((180, 10), (280, 10), (280, 30), (180, 30)), 0.8),
    ]
    monkeypatch.setattr(procesamiento_masivo, "leer_texto_imagen", Mock(return_value=[]))
    monkeypatch.setattr(procesamiento_masivo, "leer_bloques_imagen", Mock(return_value=bloques))
    monkeypatch.setattr(
        procesamiento_masivo, "_leer_transporte_focal", Mock(side_effect=RuntimeError("fallo focal"))
    )
    monkeypatch.setattr(
        procesamiento_masivo, "extraer_datos",
        Mock(return_value={"número de guía": "123456", "número de transporte": "No encontrado", "cliente": "A", "obra destino": "B"}),
    )

    resultado = procesar_archivo(ruta)

    assert resultado["numero_transporte"] == "No encontrado"


def test_procesar_archivo_preserva_chofer_lineal_limpio(tmp_path, monkeypatch):
    ruta = tmp_path / "guia.jpg"
    bloques = Mock()
    monkeypatch.setattr(
        procesamiento_masivo,
        "leer_texto_imagen",
        Mock(return_value=["FECHA DE EMISIÓN 23-06-2025"]),
    )
    monkeypatch.setattr(procesamiento_masivo, "leer_bloques_imagen", bloques)
    monkeypatch.setattr(
        procesamiento_masivo, "extraer_datos",
        Mock(return_value={
            "número de guía": "123456", "número de transporte": "0000123456",
            "cliente": "A", "obra destino": "B", "chofer": "MARIO SOTO",
            "RUT del cliente": "11.111.111-1", "RUT del chofer": "11.111.111-1",
            "patente del tracto": "AB1234", "patente del carro": "CD5678",
        }),
    )

    assert procesar_archivo(ruta)["chofer"] == "MARIO SOTO"
    bloques.assert_not_called()


def test_procesar_archivo_reemplaza_chofer_contaminado_y_mantiene_revision(tmp_path, monkeypatch):
    ruta = tmp_path / "archivo_sin_nombre_personal.jpg"
    bloques = [
        BloqueOCR("RETIRA", ((10, 10), (70, 10), (70, 30), (10, 30)), 0.9),
        BloqueOCR("NOMBRE APELLIDO", ((120, 10), (250, 10), (250, 30), (120, 30)), 0.8),
        BloqueOCR("PATENTE", ((10, 40), (80, 40), (80, 60), (10, 60)), 0.9),
    ]
    monkeypatch.setattr(procesamiento_masivo, "leer_texto_imagen", Mock(return_value=[]))
    monkeypatch.setattr(procesamiento_masivo, "leer_bloques_imagen", Mock(return_value=bloques))
    monkeypatch.setattr(
        procesamiento_masivo, "extraer_datos",
        Mock(return_value={"número de guía": "123456", "número de transporte": "0000123456", "cliente": "A", "obra destino": "B", "chofer": "TOTAL EXENTO NOMBRE APELLIDO"}),
    )

    resultado = procesar_archivo(ruta)

    assert resultado["chofer"] == "NOMBRE APELLIDO"
    assert resultado["indicador_revision"] == "REVISAR"


def test_procesar_archivo_contaminado_sin_candidato_conserva_valor_anterior(tmp_path, monkeypatch):
    ruta = tmp_path / "guia.jpg"
    monkeypatch.setattr(procesamiento_masivo, "leer_texto_imagen", Mock(return_value=[]))
    monkeypatch.setattr(procesamiento_masivo, "leer_bloques_imagen", Mock(return_value=[]))
    monkeypatch.setattr(
        procesamiento_masivo, "extraer_datos",
        Mock(return_value={"número de guía": "123456", "número de transporte": "0000123456", "cliente": "A", "obra destino": "B", "chofer": "TOTAL EXENTO JUAN PEREZ"}),
    )

    assert procesar_archivo(ruta)["chofer"] == "TOTAL EXENTO JUAN PEREZ"


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


def test_procesar_archivo_fecha_global_valida_no_dispara_focal(tmp_path, monkeypatch):
    ruta = tmp_path / "guia.jpg"
    leer_bloques = Mock()
    fecha_geometrica = Mock()
    fecha_focal = Mock()
    monkeypatch.setattr(
        procesamiento_masivo,
        "leer_texto_imagen",
        Mock(return_value=["FECHA DE EMISIÓN 23-06-2025"]),
    )
    monkeypatch.setattr(procesamiento_masivo, "leer_bloques_imagen", leer_bloques)
    monkeypatch.setattr(procesamiento_masivo, "_extraer_fecha_geometrico", fecha_geometrica)
    monkeypatch.setattr(procesamiento_masivo, "_leer_fecha_focal", fecha_focal)
    monkeypatch.setattr(
        procesamiento_masivo, "extraer_datos", Mock(return_value=_datos_lineales_completos())
    )

    resultado = procesar_archivo(ruta)

    assert resultado["fecha"] == "23-06-2025"
    leer_bloques.assert_not_called()
    fecha_geometrica.assert_not_called()
    fecha_focal.assert_not_called()


def test_procesar_archivo_fecha_focal_recupera_con_consenso_de_dos_variantes(
    tmp_path, monkeypatch
):
    ruta = tmp_path / "guia.jpg"
    bloques = [
        BloqueOCR("FECHA DE EMISION", ((10, 10), (160, 10), (160, 28), (10, 28)), 0.9),
        BloqueOCR("RUIDO 2025", ((180, 10), (280, 10), (280, 28), (180, 28)), 0.3),
    ]
    monkeypatch.setattr(
        procesamiento_masivo, "leer_texto_imagen", Mock(return_value=["sin fecha reconocible"])
    )
    monkeypatch.setattr(procesamiento_masivo, "leer_bloques_imagen", Mock(return_value=bloques))
    monkeypatch.setattr(
        procesamiento_masivo, "extraer_datos", Mock(return_value=_datos_lineales_completos())
    )
    monkeypatch.setattr(
        procesamiento_masivo,
        "_leer_fecha_focal",
        Mock(
            return_value={
                "lecturas": [
                    {"variante": "original", "texto": "FECHA DE EMISION 23-06-2025", "confianza": 0.95},
                    {"variante": "grises", "texto": "FECHA DE EMISION 23-06-2025", "confianza": 0.90},
                    {"variante": "ampliada_2x", "texto": "", "confianza": None},
                    {"variante": "ampliada_2x_contraste", "texto": "", "confianza": None},
                ]
            }
        ),
    )

    resultado = procesar_archivo(ruta)

    assert resultado["fecha"] == "23-06-2025"
    # Bloque ESTADOS S2: el consenso focal de fecha exige >=2 lecturas
    # concordantes con confianza suficiente -- corroborado por diseño, ya
    # no fuerza revisión por sí solo (la descripción de material ausente,
    # `MATERIAL_AUSENTE`, tampoco: es informativa, no bloqueante).
    assert resultado["indicador_revision"] == "OK"
    assert "FOCAL" in resultado["metodos_recuperacion_documento"]


def test_procesar_archivo_fecha_focal_abstiene_si_un_voto_coincidente_tiene_confianza_baja(
    tmp_path, monkeypatch
):
    """Reproduce el caso real IMG-20250930-WA0046.jpg (F2.2): 3 variantes
    coinciden en la misma fecha (incorrecta en el caso real), pero una de
    ellas tiene confianza por debajo del umbral -> se descarta el consenso
    completo y se abstiene, en vez de aceptar un consenso débil."""
    ruta = tmp_path / "guia.jpg"
    bloques = [
        BloqueOCR("FECHA DE EMISION", ((10, 10), (160, 10), (160, 28), (10, 28)), 0.9),
        BloqueOCR("RUIDO 2025", ((180, 10), (280, 10), (280, 28), (180, 28)), 0.3),
    ]
    monkeypatch.setattr(
        procesamiento_masivo, "leer_texto_imagen", Mock(return_value=["sin fecha reconocible"])
    )
    monkeypatch.setattr(procesamiento_masivo, "leer_bloques_imagen", Mock(return_value=bloques))
    monkeypatch.setattr(
        procesamiento_masivo, "extraer_datos", Mock(return_value=_datos_lineales_completos())
    )
    monkeypatch.setattr(
        procesamiento_masivo,
        "_leer_fecha_focal",
        Mock(
            return_value={
                "lecturas": [
                    {"variante": "original", "texto": "FECHA DE EMISION 10-09-2025", "confianza": 0.82},
                    {"variante": "grises", "texto": "FECHA DE EMISION 10-09-2025", "confianza": 0.82},
                    {"variante": "ampliada_2x", "texto": "FECHA DE EMISION 10-09-2025", "confianza": 0.47},
                    {"variante": "ampliada_2x_contraste", "texto": "", "confianza": 0.99},
                ]
            }
        ),
    )

    resultado = procesar_archivo(ruta)

    assert resultado["fecha"] == "No encontrado"
    # Bloque ESTADOS S2: la fecha ausente nunca formó parte de los campos
    # clave que fuerzan revisión (ni antes ni después de este bloque); el
    # único motivo de REVISAR en este escenario era la descripción de
    # material ausente, ahora informativa/no bloqueante.
    assert resultado["indicador_revision"] == "OK"


def test_procesar_archivo_fecha_focal_acepta_confianza_exactamente_en_el_umbral(
    tmp_path, monkeypatch
):
    ruta = tmp_path / "guia.jpg"
    bloques = [
        BloqueOCR("FECHA DE EMISION", ((10, 10), (160, 10), (160, 28), (10, 28)), 0.9),
        BloqueOCR("RUIDO 2025", ((180, 10), (280, 10), (280, 28), (180, 28)), 0.3),
    ]
    monkeypatch.setattr(
        procesamiento_masivo, "leer_texto_imagen", Mock(return_value=["sin fecha reconocible"])
    )
    monkeypatch.setattr(procesamiento_masivo, "leer_bloques_imagen", Mock(return_value=bloques))
    monkeypatch.setattr(
        procesamiento_masivo, "extraer_datos", Mock(return_value=_datos_lineales_completos())
    )
    monkeypatch.setattr(
        procesamiento_masivo,
        "_leer_fecha_focal",
        Mock(
            return_value={
                "lecturas": [
                    {"variante": "original", "texto": "FECHA DE EMISION 30-09-2025", "confianza": 0.70},
                    {"variante": "grises", "texto": "", "confianza": None},
                    {"variante": "ampliada_2x", "texto": "FECHA DE EMISION 30-09-2025", "confianza": 0.70},
                    {"variante": "ampliada_2x_contraste", "texto": "", "confianza": None},
                ]
            }
        ),
    )

    resultado = procesar_archivo(ruta)

    assert resultado["fecha"] == "30-09-2025"
    assert resultado["indicador_revision"] == "OK"
    assert "FOCAL" in resultado["metodos_recuperacion_documento"]


def test_procesar_archivo_fecha_focal_variantes_discordantes_no_convergen(
    tmp_path, monkeypatch
):
    ruta = tmp_path / "guia.jpg"
    bloques = [
        BloqueOCR("FECHA DE EMISION", ((10, 10), (160, 10), (160, 28), (10, 28)), 0.9),
        BloqueOCR("RUIDO 2025", ((180, 10), (280, 10), (280, 28), (180, 28)), 0.3),
    ]
    monkeypatch.setattr(
        procesamiento_masivo, "leer_texto_imagen", Mock(return_value=["sin fecha reconocible"])
    )
    monkeypatch.setattr(procesamiento_masivo, "leer_bloques_imagen", Mock(return_value=bloques))
    monkeypatch.setattr(
        procesamiento_masivo, "extraer_datos", Mock(return_value=_datos_lineales_completos())
    )
    monkeypatch.setattr(
        procesamiento_masivo,
        "_leer_fecha_focal",
        Mock(
            return_value={
                "lecturas": [
                    {"variante": "original", "texto": "FECHA DE EMISION 23-06-2025"},
                    {"variante": "grises", "texto": "FECHA DE EMISION 24-06-2025"},
                    {"variante": "ampliada_2x", "texto": "FECHA DE EMISION 25-06-2025"},
                    {"variante": "ampliada_2x_contraste", "texto": ""},
                ]
            }
        ),
    )

    resultado = procesar_archivo(ruta)

    assert resultado["fecha"] == "No encontrado"
    assert resultado["indicador_revision"] == "OK"


def test_procesar_archivo_fecha_focal_descarta_anio_absurdo_por_plausibilidad(
    tmp_path, monkeypatch
):
    ruta = tmp_path / "guia.jpg"
    bloques = [
        BloqueOCR("FECHA DE EMISION", ((10, 10), (160, 10), (160, 28), (10, 28)), 0.9),
        BloqueOCR("RUIDO 2025", ((180, 10), (280, 10), (280, 28), (180, 28)), 0.3),
    ]
    monkeypatch.setattr(
        procesamiento_masivo, "leer_texto_imagen", Mock(return_value=["sin fecha reconocible"])
    )
    monkeypatch.setattr(procesamiento_masivo, "leer_bloques_imagen", Mock(return_value=bloques))
    monkeypatch.setattr(
        procesamiento_masivo, "extraer_datos", Mock(return_value=_datos_lineales_completos())
    )
    monkeypatch.setattr(
        procesamiento_masivo,
        "_leer_fecha_focal",
        Mock(
            return_value={
                "lecturas": [
                    {"variante": "original", "texto": "FECHA DE EMISION 23-06-7025"},
                    {"variante": "grises", "texto": "FECHA DE EMISION 23-06-7025"},
                    {"variante": "ampliada_2x", "texto": ""},
                    {"variante": "ampliada_2x_contraste", "texto": ""},
                ]
            }
        ),
    )

    resultado = procesar_archivo(ruta)

    assert resultado["fecha"] == "No encontrado"


def test_procesar_archivo_fecha_focal_sin_caja_geometrica_se_abstiene(tmp_path, monkeypatch):
    ruta = tmp_path / "guia.jpg"
    bloques = [BloqueOCR("FECHA DE EMISION", ((10, 10), (160, 10), (160, 28), (10, 28)), 0.9)]
    fecha_focal = Mock()
    monkeypatch.setattr(
        procesamiento_masivo, "leer_texto_imagen", Mock(return_value=["sin fecha reconocible"])
    )
    monkeypatch.setattr(procesamiento_masivo, "leer_bloques_imagen", Mock(return_value=bloques))
    monkeypatch.setattr(procesamiento_masivo, "_leer_fecha_focal", fecha_focal)
    monkeypatch.setattr(
        procesamiento_masivo, "extraer_datos", Mock(return_value=_datos_lineales_completos())
    )

    resultado = procesar_archivo(ruta)

    assert resultado["fecha"] == "No encontrado"
    fecha_focal.assert_not_called()


# ---- Bloque M1: proveedor OCR (numero_guia robusto, focal generalizado, guarda documental) ----

class _ProveedorFalso:
    """Proveedor OCR mínimo para tests, cumple el contrato ProveedorOCR."""

    def __init__(self, texto=None, bloques=None, focal=None):
        self._texto = texto or []
        self._bloques = bloques or []
        self._focal = focal or {"lecturas": []}
        self.llamadas_focal = []

    def leer_texto(self, ruta):
        return self._texto

    def leer_bloques(self, ruta):
        return self._bloques

    def leer_focal(self, ruta, caja, allowlist):
        self.llamadas_focal.append((ruta, caja, allowlist))
        return self._focal


def test_procesar_archivo_numero_guia_recupera_con_etiqueta_fragmentada_via_proveedor(
    tmp_path, monkeypatch
):
    """Reproduce el caso real de PaddleOCR: "GUIA"/"DESPACHO"/"ELECTRONICA"
    llegan en bloques separados con una línea ajena en medio (dirección),
    y el número está más abajo junto a un marcador "N°". decidir_bloques_ocr
    ya resuelve esto — este test confirma que queda conectado vía proveedor."""
    ruta = tmp_path / "guia.jpg"
    bloques = [
        BloqueOCR("GUIA", ((10, 10), (50, 10), (50, 28), (10, 28)), 0.9),
        BloqueOCR("DESPACHO", ((55, 10), (135, 10), (135, 28), (55, 28)), 0.9),
        BloqueOCR("ELECTRONICA", ((140, 10), (230, 10), (230, 28), (140, 28)), 0.9),
        BloqueOCR("LA UNION 3070 RENCA SANTIAGO", ((10, 40), (270, 40), (270, 58), (10, 58)), 0.9),
        BloqueOCR("N°", ((10, 70), (35, 70), (35, 88), (10, 88)), 0.9),
        BloqueOCR("384674", ((40, 70), (105, 70), (105, 88), (40, 88)), 0.9),
    ]
    proveedor = _ProveedorFalso(texto=["sin fecha reconocible"], bloques=bloques)
    monkeypatch.setattr(
        procesamiento_masivo,
        "extraer_datos",
        Mock(return_value=_datos_lineales_completos(**{"número de guía": "No encontrado"})),
    )

    resultado = procesar_archivo(ruta, proveedor=proveedor)

    assert resultado["numero_guia"] == "384674"


def test_procesar_archivo_numero_guia_sin_contexto_suficiente_se_abstiene(tmp_path, monkeypatch):
    ruta = tmp_path / "guia.jpg"
    bloques = [
        BloqueOCR("GUIA", ((10, 10), (50, 10), (50, 28), (10, 28)), 0.9),
        BloqueOCR("DESPACHO", ((55, 10), (135, 10), (135, 28), (55, 28)), 0.9),
        BloqueOCR("ELECTRONICA", ((140, 10), (230, 10), (230, 28), (140, 28)), 0.9),
        BloqueOCR("384674", ((10, 200), (75, 200), (75, 218), (10, 218)), 0.9),  # sin marcador N° cerca
    ]
    proveedor = _ProveedorFalso(texto=["sin fecha reconocible"], bloques=bloques)
    monkeypatch.setattr(
        procesamiento_masivo,
        "extraer_datos",
        Mock(return_value=_datos_lineales_completos(**{"número de guía": "No encontrado"})),
    )

    resultado = procesar_archivo(ruta, proveedor=proveedor)

    assert resultado["numero_guia"] == "No encontrado"


def test_procesar_archivo_fecha_focal_via_proveedor(tmp_path, monkeypatch):
    ruta = tmp_path / "guia.jpg"
    bloques = [
        BloqueOCR("FECHA DE EMISION", ((10, 10), (160, 10), (160, 28), (10, 28)), 0.9),
        BloqueOCR("RUIDO 2025", ((180, 10), (280, 10), (280, 28), (180, 28)), 0.3),
    ]
    proveedor = _ProveedorFalso(
        texto=["sin fecha reconocible"],
        bloques=bloques,
        focal={
            "lecturas": [
                {"variante": "original", "texto": "FECHA DE EMISION 23-06-2025", "confianza": 0.95},
                {"variante": "grises", "texto": "FECHA DE EMISION 23-06-2025", "confianza": 0.90},
            ]
        },
    )
    monkeypatch.setattr(
        procesamiento_masivo, "extraer_datos", Mock(return_value=_datos_lineales_completos())
    )

    resultado = procesar_archivo(ruta, proveedor=proveedor)

    assert resultado["fecha"] == "23-06-2025"
    assert len(proveedor.llamadas_focal) == 1


def test_procesar_archivo_transporte_focal_via_proveedor(tmp_path, monkeypatch):
    ruta = tmp_path / "guia.jpg"
    bloques = [
        BloqueOCR("NRO TRANSPORTE", ((10, 10), (130, 10), (130, 30), (10, 30)), 0.9),
        BloqueOCR("00do348608", ((180, 10), (280, 10), (280, 30), (180, 30)), 0.3),
    ]
    proveedor = _ProveedorFalso(
        texto=["sin fecha reconocible"],
        bloques=bloques,
        focal={
            "lecturas": [
                {"variante": "original", "texto": "oo 0000348808", "confianza": 0.9},
                {"variante": "grises", "texto": "oo 00do348808", "confianza": 0.9},
                {"variante": "ampliada_2x", "texto": "000o348608", "confianza": 0.9},
            ]
        },
    )
    monkeypatch.setattr(
        procesamiento_masivo,
        "extraer_datos",
        Mock(
            return_value={
                "número de guía": "123456", "número de transporte": "No encontrado",
                "cliente": "A", "obra destino": "B", "chofer": "C",
            }
        ),
    )

    resultado = procesar_archivo(ruta, proveedor=proveedor)

    assert resultado["numero_transporte"] == "0000348808"
    assert len(proveedor.llamadas_focal) == 1


def test_documento_degradado_activa_con_multiples_campos_faltantes():
    datos = {
        "número de guía": "No encontrado", "número de transporte": "0000123456",
        "cliente": "No encontrado", "obra destino": "No encontrado",
        "chofer": "JUAN PEREZ", "patente del tracto": "No encontrado",
        "patente del carro": "No encontrado",
    }
    assert procesamiento_masivo._documento_degradado(datos, "HORMIGON 10MM") is True


def test_documento_degradado_no_se_activa_con_pocos_campos_faltantes():
    datos = {
        "número de guía": "123456", "número de transporte": "0000123456",
        "cliente": "ACEROS SUR", "obra destino": "No encontrado",
        "chofer": "JUAN PEREZ", "patente del tracto": "ABCD12",
        "patente del carro": "No encontrado",
    }
    assert procesamiento_masivo._documento_degradado(datos, "HORMIGON 10MM") is False


def test_procesar_archivo_documento_degradado_queda_revisar(tmp_path, monkeypatch):
    ruta = tmp_path / "guia.jpg"
    monkeypatch.setattr(
        procesamiento_masivo, "leer_texto_imagen", Mock(return_value=["FECHA DE EMISIÓN 23-06-2025"])
    )
    monkeypatch.setattr(procesamiento_masivo, "leer_bloques_imagen", Mock(return_value=[]))
    monkeypatch.setattr(
        procesamiento_masivo,
        "extraer_datos",
        Mock(
            return_value={
                "número de guía": "No encontrado", "número de transporte": "0000123456",
                "cliente": "No encontrado", "obra destino": "No encontrado",
                "chofer": "JUAN PEREZ", "patente del tracto": "No encontrado",
                "patente del carro": "No encontrado",
            }
        ),
    )

    resultado = procesar_archivo(ruta)

    assert resultado["indicador_revision"] == "REVISAR"


def test_procesar_archivo_sin_proveedor_usa_easyocr_directo_como_antes(tmp_path, monkeypatch):
    """No degradar comportamiento existente: sin `proveedor`, la ruta sigue
    siendo exactamente la de EasyOCR directo, sin tocar bloques si no hace falta."""
    ruta = tmp_path / "guia.jpg"
    leer_texto = Mock(return_value=["FECHA DE EMISIÓN 23-06-2025"])
    leer_bloques = Mock()
    monkeypatch.setattr(procesamiento_masivo, "leer_texto_imagen", leer_texto)
    monkeypatch.setattr(procesamiento_masivo, "leer_bloques_imagen", leer_bloques)
    monkeypatch.setattr(
        procesamiento_masivo, "extraer_datos", Mock(return_value=_datos_lineales_completos())
    )

    resultado = procesar_archivo(ruta)

    assert resultado["fecha"] == "23-06-2025"
    leer_texto.assert_called_once_with(ruta, lector=None)
    leer_bloques.assert_not_called()


def _preparar_procesamiento_fuzzy(monkeypatch, datos, catalogo, bloques=None):
    monkeypatch.setattr(
        procesamiento_masivo, "leer_texto_imagen", Mock(return_value=[])
    )
    monkeypatch.setattr(
        procesamiento_masivo, "extraer_datos", Mock(return_value=datos)
    )
    monkeypatch.setattr(
        procesamiento_masivo,
        "cargar_catalogo_json",
        Mock(return_value=catalogo),
    )
    if bloques is not None:
        monkeypatch.setattr(
            procesamiento_masivo,
            "leer_bloques_imagen",
            Mock(return_value=bloques),
        )


def test_fuzzy_se_aplica_al_chofer_de_ocr_directo_sin_cambiar_otros_campos(
    tmp_path, monkeypatch
):
    datos = {
        "número de guía": "463309",
        "número de transporte": "0000123456",
        "cliente": "CLIENTE ORIGINAL",
        "obra destino": "DESTINO ORIGINAL",
        "chofer": "ENRIQUE RANOS",
        "RUT del chofer": "No encontrado",
        "patente del tracto": "ABCD12",
        "patente del carro": "EFGH34",
    }
    _preparar_procesamiento_fuzzy(
        monkeypatch,
        datos,
        {"1": {"nombre": "ENRIQUE RAMOS", "activo": True}},
    )

    resultado = procesar_archivo(tmp_path / "guia.jpg")

    assert resultado["chofer"] == "ENRIQUE RAMOS"
    assert resultado["numero_guia"] == "463309"
    assert resultado["numero_transporte"] == "0000123456"
    assert resultado["cliente"] == "CLIENTE ORIGINAL"
    assert resultado["obra_destino"] == "DESTINO ORIGINAL"
    assert resultado["patente_tracto"] == "ABCD12"
    assert resultado["patente_rampla"] == "EFGH34"


def test_fuzzy_se_aplica_al_chofer_del_fallback_geometrico_y_corrobora_sin_revision(
    tmp_path, monkeypatch
):
    datos = {
        "número de guía": "463309",
        "número de transporte": "0000123456",
        "cliente": "CLIENTE ORIGINAL",
        "obra destino": "DESTINO ORIGINAL",
        "chofer": "No encontrado",
    }
    bloques = [
        BloqueOCR("RETIRA", ((10, 10), (70, 10), (70, 30), (10, 30)), 0.9),
        BloqueOCR(
            "ENRIQUE RANOS", ((120, 10), (250, 10), (250, 30), (120, 30)), 0.8
        ),
        BloqueOCR("PATENTE", ((10, 40), (80, 40), (80, 60), (10, 60)), 0.9),
    ]
    _preparar_procesamiento_fuzzy(
        monkeypatch,
        datos,
        {"1": {"nombre": "ENRIQUE RAMOS", "activo": True}},
        bloques,
    )

    resultado = procesar_archivo(tmp_path / "guia.jpg")

    assert resultado["chofer"] == "ENRIQUE RAMOS"
    # Bloque ESTADOS S2: el chofer llegó por geometría (nombre ausente en
    # extracción lineal), pero el fuzzy-match "COINCIDENCIA_SEGURA" contra
    # catálogo lo corrobora -- ya no fuerza revisión solo por el método.
    assert resultado["indicador_revision"] == "OK"
    assert "GEOMETRICO" in resultado["metodos_recuperacion_documento"]
    assert "FUZZY" in resultado["metodos_recuperacion_documento"]
    assert "CHOFER_SIN_CORROBORAR" not in resultado["motivos_revision_documento"]


def test_fuzzy_sin_coincidencia_conserva_nombre_y_revision_actual(
    tmp_path, monkeypatch
):
    datos = {
        "número de guía": "463309",
        "número de transporte": "0000123456",
        "cliente": "CLIENTE ORIGINAL",
        "obra destino": "DESTINO ORIGINAL",
        "chofer": "NOMBRE ORIGINAL",
    }
    _preparar_procesamiento_fuzzy(
        monkeypatch,
        datos,
        {"1": {"nombre": "PERSONA DIFERENTE", "activo": True}},
    )

    resultado = procesar_archivo(tmp_path / "guia.jpg")

    assert resultado["chofer"] == "NOMBRE ORIGINAL"
    # Bloque ESTADOS S2: el chofer vino de extracción lineal limpia (nunca
    # ausente/contaminado) -- que el fuzzy no encuentre coincidencia no
    # invalida un dato que nunca necesitó rescate.
    assert resultado["indicador_revision"] == "OK"


def test_fuzzy_no_modifica_rut_y_respeta_match_exacto_existente(
    tmp_path, monkeypatch
):
    datos = {
        "número de guía": "463309",
        "número de transporte": "0000123456",
        "cliente": "CLIENTE ORIGINAL",
        "obra destino": "DESTINO ORIGINAL",
        "chofer": "ENRIQUE RANOS",
        "RUT del chofer": "11.111.111-1",
    }
    catalogo = {
        "111111111": {"nombre": "OTRO NOMBRE", "activo": True},
        "222222222": {"nombre": "ENRIQUE RAMOS", "activo": True},
    }
    _preparar_procesamiento_fuzzy(monkeypatch, datos, catalogo)

    resultado = procesar_archivo(tmp_path / "guia.jpg")

    assert resultado["chofer"] == "ENRIQUE RANOS"
    assert resultado["rut_chofer"] == "11.111.111-1"
    assert set(resultado) == {
        "numero_guia",
        "numero_transporte",
        "fecha",
        "chofer",
        "rut_chofer",
        "cliente",
        "obra_destino",
        "patente_tracto",
        "patente_rampla",
        "descripcion_material",
        "tipo_carga",
        "indicador_revision",
        "motivos_revision_documento",
        "metodos_recuperacion_documento",
        "peso_kg",
        "hora_entrada_aza",
        "hora_salida_aza",
        "permanencia_minutos",
        "despachar_a_crudo",
        "direccion_entrega",
        "localidad_entrega",
        "region_entrega",
        "estado_entrega",
        "planta_origen_id",
        "planta_origen_nombre",
        "origen_determinado_por",
        "evidencia_origen",
        "distancia_km",
        "duracion_min",
        "proveedor_ruta",
        "estado_ruta",
        "motivo_ruta",
        "proveedor_telemetria",
        "estado_telemetria",
        "origen_gps",
        "planta_gps_id",
        "planta_gps_nombre",
        "hora_entrada_gps",
        "hora_salida_gps",
        "distancia_gps_km",
        "evidencia_telemetria",
        "motivo_origen_gps",
        "latitud_estadia_gps",
        "longitud_estadia_gps",
        "duracion_estadia_gps_min",
    }


def test_descubre_extensiones_permitidas_en_subcarpetas_y_ordena(tmp_path):
    for nombre in ("z.TIFF", "sub/b.jpeg", "sub/a.PNG", "foto.webp", "x.tif"):
        _crear_archivo(tmp_path / nombre)
    _crear_archivo(tmp_path / "sub/ignorar.pdf")
    _crear_archivo(tmp_path / "texto.txt")

    encontrados = [ruta.relative_to(tmp_path).as_posix() for ruta in descubrir_archivos(tmp_path)]

    assert encontrados == ["foto.webp", "sub/a.PNG", "sub/b.jpeg", "x.tif", "z.TIFF"]


def test_continua_si_un_archivo_falla_y_escribe_csv_excel(tmp_path):
    _crear_archivo(tmp_path / "guias/a.jpg")
    _crear_archivo(tmp_path / "guias/b.jpg")
    salida = tmp_path / "salida/nueva/resultado.csv"

    def procesador(ruta):
        if ruta.name == "a.jpg":
            raise RuntimeError("OCR falló")
        return {"numero_guia": "123", "tipo_carga": "BARRAS", "cliente": "ACEROS ÑUBLE"}

    resumen = procesar_carpeta(tmp_path / "guias", salida, procesador=procesador, cada=1)

    assert resumen["encontrados"] == 2
    assert resumen["procesados"] == 2
    assert resumen["omitidos"] == 0
    assert resumen["errores"] == 1
    assert resumen["barras"] == 1
    assert resumen["no_determinados"] == 1
    assert salida.read_bytes().startswith(b"\xef\xbb\xbf")
    with salida.open(encoding="utf-8-sig", newline="") as archivo:
        lector = csv.DictReader(archivo, delimiter=";")
        filas = list(lector)
    assert lector.fieldnames == COLUMNAS
    assert filas[0]["estado_procesamiento"] == "ERROR"
    assert "RuntimeError: OCR falló" == filas[0]["error"]
    assert filas[1]["cliente"] == "ACEROS ÑUBLE"


def test_omite_archivo_ya_procesado(tmp_path):
    carpeta = tmp_path / "guias"
    _crear_archivo(carpeta / "a.jpg")
    salida = tmp_path / "resultado.csv"
    llamadas = []

    def procesador(ruta):
        llamadas.append(ruta)
        return {"numero_guia": "1"}

    procesar_carpeta(carpeta, salida, procesador=procesador)
    resumen = procesar_carpeta(carpeta, salida, procesador=procesador)

    assert len(llamadas) == 1
    assert resumen["omitidos"] == 1
    assert len(salida.read_text(encoding="utf-8-sig").splitlines()) == 2


def test_reprocesar_rechaza_csv_con_datos_y_conserva_sus_bytes(tmp_path):
    carpeta = tmp_path / "guias"
    _crear_archivo(carpeta / "a.jpg")
    salida = tmp_path / "resultado.csv"
    procesador = Mock(return_value={"numero_guia": "1"})
    procesar_carpeta(carpeta, salida, procesador=procesador)
    contenido_original = salida.read_bytes()
    procesador.reset_mock()

    with pytest.raises(FileExistsError, match="ruta de salida nueva o inexistente"):
        procesar_carpeta(carpeta, salida, procesador=procesador, reprocesar=True)

    assert salida.read_bytes() == contenido_original
    procesador.assert_not_called()


def test_reprocesar_permite_ruta_nueva(tmp_path):
    carpeta = tmp_path / "guias"
    _crear_archivo(carpeta / "a.jpg")
    salida = tmp_path / "resultado_nuevo.csv"

    resumen = procesar_carpeta(
        carpeta,
        salida,
        procesador=lambda ruta: {"numero_guia": "1"},
        reprocesar=True,
    )

    assert resumen["procesados"] == 1
    assert len(salida.read_text(encoding="utf-8-sig").splitlines()) == 2


def test_acepta_csv_existente_vacio(tmp_path):
    carpeta = tmp_path / "guias"
    _crear_archivo(carpeta / "a.jpg")
    salida = tmp_path / "resultado.csv"
    salida.touch()

    procesar_carpeta(carpeta, salida, procesador=lambda ruta: {"numero_guia": "1"})

    with salida.open(encoding="utf-8-sig", newline="") as archivo:
        lector = csv.DictReader(archivo, delimiter=";")
        filas = list(lector)
    assert lector.fieldnames == COLUMNAS
    assert len(filas) == 1


def test_acepta_encabezado_exacto_para_reanudar(tmp_path):
    carpeta = tmp_path / "guias"
    _crear_archivo(carpeta / "a.jpg")
    salida = tmp_path / "resultado.csv"
    with salida.open("w", encoding="utf-8-sig", newline="") as archivo:
        csv.writer(archivo, delimiter=";").writerow(COLUMNAS)

    resumen = procesar_carpeta(
        carpeta, salida, procesador=lambda ruta: {"numero_guia": "1"}
    )

    assert resumen["procesados"] == 1


@pytest.mark.parametrize(
    "encabezado",
    [
        COLUMNAS[:-1],
        COLUMNAS + ["columna_extra"],
        [*COLUMNAS[:-1], COLUMNAS[-2]],
    ],
)
def test_rechaza_encabezado_incompatible_sin_modificarlo(tmp_path, encabezado):
    carpeta = tmp_path / "guias"
    _crear_archivo(carpeta / "a.jpg")
    salida = tmp_path / "resultado.csv"
    with salida.open("w", encoding="utf-8-sig", newline="") as archivo:
        csv.writer(archivo, delimiter=";").writerow(encabezado)
    contenido_original = salida.read_bytes()
    procesador = Mock()

    with pytest.raises(ValueError, match="esquema incompatible"):
        procesar_carpeta(carpeta, salida, procesador=procesador)

    assert salida.read_bytes() == contenido_original
    procesador.assert_not_called()


def test_rechaza_separador_incorrecto_sin_modificarlo(tmp_path):
    carpeta = tmp_path / "guias"
    _crear_archivo(carpeta / "a.jpg")
    salida = tmp_path / "resultado.csv"
    salida.write_text(",".join(COLUMNAS) + "\n", encoding="utf-8-sig")
    contenido_original = salida.read_bytes()

    with pytest.raises(ValueError, match="separado por ';'"):
        procesar_carpeta(carpeta, salida, procesador=Mock())

    assert salida.read_bytes() == contenido_original


def test_keyboard_interrupt_guarda_pendientes_y_se_propaga(tmp_path):
    carpeta = tmp_path / "guias"
    for nombre in ("a.jpg", "b.jpg", "c.jpg"):
        _crear_archivo(carpeta / nombre)
    salida = tmp_path / "resultado.csv"

    def interrumpir_en_tercero(ruta):
        if ruta.name == "c.jpg":
            raise KeyboardInterrupt
        return {"numero_guia": ruta.stem, "tipo_carga": "BARRAS"}

    with pytest.raises(KeyboardInterrupt):
        procesar_carpeta(
            carpeta, salida, procesador=interrumpir_en_tercero, cada=10
        )

    with salida.open(encoding="utf-8-sig", newline="") as archivo:
        filas = list(csv.DictReader(archivo, delimiter=";"))
    assert [fila["archivo"] for fila in filas] == ["a.jpg", "b.jpg"]

    procesados_al_reanudar = []

    def completar(ruta):
        procesados_al_reanudar.append(ruta.name)
        return {"numero_guia": ruta.stem, "tipo_carga": "BARRAS"}

    resumen = procesar_carpeta(carpeta, salida, procesador=completar)

    assert procesados_al_reanudar == ["c.jpg"]
    assert resumen["omitidos"] == 2


def test_extrae_descripcion_y_clasifica_barras_rollos_y_mixto():
    casos = [
        (["B HORMIGÓN 16 MM 12 M"], "BARRAS"),
        (["ROLLO HORMIGÓN 10 MM"], "ROLLOS"),
        (["BARRAS PARA HORMIGÓN", "BOBINA"], "MIXTO"),
    ]
    from atlas_core.clasificador_material import clasificar_material

    for textos, esperado in casos:
        descripcion = extraer_descripcion_material(textos)
        assert clasificar_material(descripcion).value == esperado


def test_no_inventa_material_sin_evidencia():
    assert extraer_descripcion_material(["ACERO 16 MM", "TOTAL 100"]) == ""


def test_extrae_material_tolerando_confusion_ocr_h_por_b_y_m_por_h():
    # Reproducción real guía 464265: OCR leyó "HORMIGON" como "BORHIGON"
    # (H->B y M->H simultáneos) y la línea se perdía por completo antes del
    # fix -- no distancia de edición abierta, sólo los 3 pares ya
    # confirmados en `_CONFUSIONES_OCR_MATERIAL`.
    texto = "9.221 110002948 BORHIGON 22MM 12M A630-420H (N)"
    assert extraer_descripcion_material([texto]) == texto


def test_extrae_material_tolerando_confusion_ocr_r_por_m():
    # Reproducción real guía 464264, segunda línea de material: OCR leyó
    # "HORMIGON" como "HOMMIGON" (R->M) -- se perdía en silencio junto a la
    # primera línea (que sí calzaba exacto), quedando descripcion_material
    # incompleta.
    texto = "B HOMMIGON 12MM 12M A630-420N (N)"
    assert extraer_descripcion_material([texto]) == texto


def test_no_tolera_mas_de_dos_diferencias_ni_pares_no_vetados():
    # Palabras de igual longitud a "HORMIGON" (8) pero con diferencias fuera
    # de la tabla vetada, o con más de 2 diferencias, nunca deben colarse --
    # prueba negativa explícita de que la tolerancia no es fuzzy abierto.
    assert extraer_descripcion_material(["ZORZIGON 16 MM"]) == ""  # 2 diferencias, ningún par vetado
    assert extraer_descripcion_material(["BOMBIGON 16 MM"]) == ""  # 3 diferencias con HORMIGON


def test_tolerancia_ocr_material_no_afecta_otros_terminos_ni_texto_ajeno():
    # La tolerancia sólo aplica a HORMIGON (única palabra con evidencia real
    # de confusión); BARRAS/ROLLOS/ALAMBRON/BOBINAS siguen exigiendo
    # coincidencia exacta, y el texto conservado nunca se reescribe.
    assert extraer_descripcion_material(["PRODUCTO HORMIGSN 16 MM"]) == ""
    assert extraer_descripcion_material(["ACERO ESTRUCTURAL 16MM"]) == ""


def test_fecha_descarta_primera_imposible_y_usa_segunda_valida():
    textos = ["FECHAS 31-02-2026 y 28-02-2026"]

    assert extraer_fecha(textos) == "28-02-2026"


def test_fecha_descarta_emision_imposible_y_usa_salida_valida():
    textos = [
        "FECHA DE EMISIÓN 76-17-2124",
        "FECHA SALIDA 06-07-2026",
    ]

    assert extraer_fecha(textos) == "06-07-2026"


def test_fecha_emision_valida_gana_sobre_salida_valida():
    textos = [
        "FECHA SALIDA 03-07-2026",
        "texto intermedio " * 10,
        "FECHA DE EMISIÓN 02-07-2026",
    ]

    assert extraer_fecha(textos) == "02-07-2026"


def test_fecha_recopila_varias_coincidencias_del_mismo_bloque():
    textos = ["31-04-2026 15-06-2026 16-06-2026"]

    assert extraer_fecha(textos) == "15-06-2026"


def test_fecha_recopila_coincidencias_distribuidas_en_bloques():
    textos = ["31-02-2026", "30-02-2026", "01-03-2026"]

    assert extraer_fecha(textos) == "01-03-2026"


def test_fecha_solo_con_candidatos_imposibles_no_se_encuentra():
    textos = ["31-02-2026", "00/12/2026", "2026-13-01"]

    assert extraer_fecha(textos) == "No encontrado"


def test_fecha_bisiesta_valida():
    assert extraer_fecha(["FECHA DE EMISIÓN 29-02-2024"]) == "29-02-2024"


def test_fecha_dia_imposible_se_descarta():
    assert extraer_fecha(["FECHA 31-04-2026"]) == "No encontrado"


def test_fecha_mes_imposible_se_descarta():
    assert extraer_fecha(["FECHA 15-13-2026"]) == "No encontrado"


@pytest.mark.parametrize("valor", ["14/07/2026", "14-07-2026"])
def test_fecha_acepta_separadores_y_conserva_valor_original(valor):
    assert extraer_fecha([f"FECHA DE EMISIÓN {valor}"]) == valor


@pytest.mark.parametrize("valor", ["2026-07-14", "2026/07/14"])
def test_fecha_acepta_formato_iso_y_conserva_valor_original(valor):
    assert extraer_fecha([f"FECHA DE EMISIÓN {valor}"]) == valor


def test_fecha_reconoce_etiqueta_con_mayusculas_acentos_y_saltos():
    textos = ["fEcHa", "de", "EmIsIóN", "29/02/2024"]

    assert extraer_fecha(textos) == "29/02/2024"


FECHA_DESDE_LOTE = date(2025, 1, 1)
FECHA_HASTA_LOTE = date(2026, 7, 31)


def test_fecha_sin_rango_descarta_anio_operacionalmente_absurdo():
    """Sin fecha_desde/fecha_hasta explícitos, igual rige la guarda de
    plausibilidad temporal por defecto: un año como 7025 no puede ser un
    documento real de Atlas, sin importar que el calendario lo acepte."""
    assert extraer_fecha(["FECHA DE EMISIÓN 01-07-7025"]) == "No encontrado"


def test_fecha_sin_rango_acepta_anio_normal_de_la_muestra():
    """Una fecha típica de la muestra real (2025-2026) se mantiene válida
    sin necesidad de pasar fecha_desde/fecha_hasta."""
    assert extraer_fecha(["FECHA DE EMISIÓN 13-07-2026"]) == "13-07-2026"


def test_fecha_sin_rango_limite_inferior_plausible_es_aceptado():
    anio = procesamiento_masivo.ANIO_MINIMO_PLAUSIBLE
    assert extraer_fecha([f"FECHA DE EMISIÓN 01-01-{anio}"]) == f"01-01-{anio}"


def test_fecha_sin_rango_limite_superior_plausible_es_aceptado():
    anio = procesamiento_masivo.ANIO_MAXIMO_PLAUSIBLE
    assert extraer_fecha([f"FECHA DE EMISIÓN 31-12-{anio}"]) == f"31-12-{anio}"


@pytest.mark.parametrize(
    "anio",
    [
        procesamiento_masivo.ANIO_MINIMO_PLAUSIBLE - 1,
        procesamiento_masivo.ANIO_MAXIMO_PLAUSIBLE + 1,
    ],
)
def test_fecha_sin_rango_anio_fuera_del_rango_plausible_se_descarta(anio):
    assert extraer_fecha([f"FECHA DE EMISIÓN 01-01-{anio}"]) == "No encontrado"


def test_fecha_con_rango_explicito_mas_amplio_que_el_default_prevalece():
    """Un fecha_desde/fecha_hasta explícito manda por completo sobre la
    guarda de plausibilidad por defecto, incluso si es más amplio que ella."""
    resultado = extraer_fecha(
        ["FECHA DE EMISIÓN 01-01-2040"],
        date(1990, 1, 1),
        date(2099, 12, 31),
    )
    assert resultado == "01-01-2040"


def test_fecha_con_rango_explicito_mas_estrecho_que_el_default_prevalece():
    """Un rango explícito también puede ser más estrecho que el default y
    sigue mandando sobre él (comportamiento de rango explícito sin cambios)."""
    resultado = extraer_fecha(
        ["FECHA DE EMISIÓN 01-01-2020"],
        FECHA_DESDE_LOTE,
        FECHA_HASTA_LOTE,
    )
    assert resultado == "No encontrado"


def test_fecha_sin_rango_candidato_absurdo_y_plausible_elige_el_plausible():
    textos = ["FECHA SALIDA 01-07-7025 FECHA DE EMISIÓN 13-07-2026"]
    assert extraer_fecha(textos) == "13-07-2026"


def test_fecha_dentro_del_rango_es_aceptada():
    resultado = extraer_fecha(
        ["FECHA DE EMISIÓN 14-07-2026"], FECHA_DESDE_LOTE, FECHA_HASTA_LOTE
    )

    assert resultado == "14-07-2026"


def test_fecha_igual_al_limite_inferior_es_aceptada():
    resultado = extraer_fecha(
        ["FECHA DE EMISIÓN 01-01-2025"], FECHA_DESDE_LOTE, FECHA_HASTA_LOTE
    )

    assert resultado == "01-01-2025"


def test_fecha_igual_al_limite_superior_es_aceptada():
    resultado = extraer_fecha(
        ["FECHA DE EMISIÓN 31-07-2026"], FECHA_DESDE_LOTE, FECHA_HASTA_LOTE
    )

    assert resultado == "31-07-2026"


def test_fecha_anterior_al_rango_es_descartada():
    resultado = extraer_fecha(
        ["FECHA DE EMISIÓN 31-12-2024"], FECHA_DESDE_LOTE, FECHA_HASTA_LOTE
    )

    assert resultado == "No encontrado"


def test_fecha_posterior_al_rango_es_descartada():
    resultado = extraer_fecha(
        ["FECHA DE EMISIÓN 01-08-2026"], FECHA_DESDE_LOTE, FECHA_HASTA_LOTE
    )

    assert resultado == "No encontrado"


def test_fecha_continua_tras_candidato_fuera_de_rango():
    resultado = extraer_fecha(
        ["01-07-7025 y 15-06-2026"], FECHA_DESDE_LOTE, FECHA_HASTA_LOTE
    )

    assert resultado == "15-06-2026"


def test_fecha_emision_fuera_de_rango_y_salida_dentro_de_rango():
    resultado = extraer_fecha(
        ["FECHA DE EMISIÓN 01-07-7025", "FECHA SALIDA 15-06-2026"],
        FECHA_DESDE_LOTE,
        FECHA_HASTA_LOTE,
    )

    assert resultado == "15-06-2026"


def test_fecha_todos_los_candidatos_fuera_de_rango_no_se_encuentra():
    resultado = extraer_fecha(
        ["31-12-2024", "01-07-7025", "01-08-2026"],
        FECHA_DESDE_LOTE,
        FECHA_HASTA_LOTE,
    )

    assert resultado == "No encontrado"


@pytest.mark.parametrize("valor", ["01-07-1024", "28-06-7025", "15-06-7029"])
def test_fecha_descarta_anios_anomalos_con_rango_del_lote(valor):
    resultado = extraer_fecha([valor], FECHA_DESDE_LOTE, FECHA_HASTA_LOTE)

    assert resultado == "No encontrado"


@pytest.mark.parametrize("valor", ["14/07/2026", "14-07-2026"])
def test_fecha_con_rango_conserva_valor_original_y_separador(valor):
    resultado = extraer_fecha([valor], FECHA_DESDE_LOTE, FECHA_HASTA_LOTE)

    assert resultado == valor


def test_fecha_con_rango_conserva_prioridad_de_contexto():
    textos = [
        "FECHA SALIDA 03-07-2026",
        "texto intermedio " * 10,
        "FECHA DE EMISIÓN 02-07-2026",
    ]

    resultado = extraer_fecha(textos, FECHA_DESDE_LOTE, FECHA_HASTA_LOTE)

    assert resultado == "02-07-2026"


def test_procesar_archivo_integra_fecha_con_ocr_simulado(tmp_path, monkeypatch):
    ruta = tmp_path / "guia.jpg"
    lector = object()
    leer = Mock(
        return_value=[
            "FECHA DE EMISIÓN 31-02-2026",
            "FECHA SALIDA 28-02-2026",
        ]
    )
    monkeypatch.setattr(procesamiento_masivo, "leer_texto_imagen", leer)
    monkeypatch.setattr(procesamiento_masivo, "extraer_datos", lambda textos: {})

    resultado = procesar_archivo(ruta, lector_ocr=lector)

    assert resultado["fecha"] == "28-02-2026"
    leer.assert_called_once_with(ruta, lector=lector)


def test_procesar_archivo_integra_rango_de_fecha(tmp_path, monkeypatch):
    ruta = tmp_path / "guia.jpg"
    monkeypatch.setattr(
        procesamiento_masivo,
        "leer_texto_imagen",
        Mock(return_value=["FECHA DE EMISIÓN 01-07-7025", "15-06-2026"]),
    )
    monkeypatch.setattr(procesamiento_masivo, "extraer_datos", lambda textos: {})

    resultado = procesar_archivo(
        ruta, fecha_desde=FECHA_DESDE_LOTE, fecha_hasta=FECHA_HASTA_LOTE
    )

    assert resultado["fecha"] == "15-06-2026"


def test_procesar_archivo_sin_rango_descarta_anio_operacionalmente_absurdo(
    tmp_path, monkeypatch
):
    ruta = tmp_path / "guia.jpg"
    monkeypatch.setattr(
        procesamiento_masivo,
        "leer_texto_imagen",
        Mock(return_value=["FECHA DE EMISIÓN 01-07-7025"]),
    )
    monkeypatch.setattr(procesamiento_masivo, "extraer_datos", lambda textos: {})

    resultado = procesar_archivo(ruta)

    assert resultado["fecha"] == "No encontrado"


@pytest.mark.parametrize(
    ("valor_ocr", "esperado"),
    [
        ("23-062025", "23-06-2025"),
        ("23/062025", "23/06/2025"),
        ("09-07 2025", "09-07-2025"),
        ("09/07 2025", "09/07/2025"),
    ],
)
def test_fecha_normaliza_separador_en_contexto(valor_ocr, esperado):
    assert extraer_fecha([f"FECHA DE EMISION {valor_ocr}"]) == esperado


def test_fecha_normaliza_caracter_inesperado_en_contexto():
    assert extraer_fecha(["FECHA DE EMISION 17207-2025"]) == "17-07-2025"


@pytest.mark.parametrize("valor", ["23-062025", "09-07 2025", "17207-2025"])
def test_fecha_no_normaliza_sin_etiqueta(valor):
    assert extraer_fecha([f"TEXTO GLOBAL {valor}"]) == "No encontrado"


@pytest.mark.parametrize(
    "textos",
    [
        ["fEcHa", "de", "EmIsiÃ³N", "23-062025"],
        ["fecha emisiÃ³n 23-062025"],
        ["FECHA\nSALIDA\n09-07 2025"],
        ["fecha llegada 17207-2025"],
    ],
)
def test_fecha_normalizada_reconoce_variantes_de_etiqueta(textos):
    assert extraer_fecha(textos) != "No encontrado"


def test_normalizaciones_rechaza_dos_interpretaciones_para_el_mismo_tramo():
    base = {
        "valor_original": "17207-2025",
        "posicion": 10,
        "fin": 20,
    }
    propuestas = [
        {**base, "valor_normalizado": "17-07-2025"},
        {**base, "valor_normalizado": "12-07-2025"},
    ]

    assert procesamiento_masivo._normalizaciones_fecha_unicas(propuestas) == []


@pytest.mark.parametrize(
    "texto",
    [
        "FECHA DE EMISION 00-01-2026",
        "FECHA DE EMISION 25-00-2026",
        "FECHA DE EMISION 70-09-2025",
        "FECHA DE EMISION 01-07-1024",
        "FECHA DE EMISION 28-06-7025",
        "FECHA DE EMISION 15-06-7029",
        "FECHA DE EMISION 11a2025",
        "FECHA DE EMISION 23 e 202 $",
        "FECHA DE EMISION 26~0e n",
    ],
)
def test_fecha_normalizada_no_corrige_patrones_no_autorizados(texto):
    assert (
        extraer_fecha(texto.splitlines(), FECHA_DESDE_LOTE, FECHA_HASTA_LOTE)
        == "No encontrado"
    )


def test_fecha_normalizada_aplica_solo_una_modificacion():
    assert extraer_fecha(["FECHA DE EMISION 23062025"]) == "No encontrado"


def test_fecha_normalizada_valida_bisiesto():
    assert extraer_fecha(["FECHA DE EMISION 29-022024"]) == "29-02-2024"
    assert extraer_fecha(["FECHA DE EMISION 29-022025"]) == "No encontrado"


def test_fecha_normalizada_aplica_rango_y_continua_busqueda():
    resultado = extraer_fecha(
        ["FECHA DE EMISION 31-122024", "FECHA SALIDA 15-062026"],
        FECHA_DESDE_LOTE,
        FECHA_HASTA_LOTE,
    )

    assert resultado == "15-06-2026"


def test_fecha_normalizada_conserva_prioridad_de_contexto():
    textos = ["FECHA SALIDA 03-072026", "FECHA DE EMISION 02-072026"]

    assert extraer_fecha(textos) == "02-07-2026"


def test_fecha_estricta_valida_tiene_prioridad_sobre_normalizada():
    textos = ["FECHA DE EMISION 02-072026", "TOTAL 03-07-2026"]

    assert extraer_fecha(textos) == "03-07-2026"


def test_fecha_estricta_conserva_valor_original_sin_cambios():
    assert extraer_fecha(["FECHA DE EMISION 14/07/2026"]) == "14/07/2026"


def test_procesar_archivo_integra_fecha_normalizada(tmp_path, monkeypatch):
    ruta = tmp_path / "guia.jpg"
    monkeypatch.setattr(
        procesamiento_masivo,
        "leer_texto_imagen",
        Mock(return_value=["FECHA DE EMISION 23-062025"]),
    )
    monkeypatch.setattr(procesamiento_masivo, "extraer_datos", lambda textos: {})

    resultado = procesar_archivo(ruta)

    assert resultado["fecha"] == "23-06-2025"


def test_fecha_normalizada_sin_rango_conserva_compatibilidad():
    assert extraer_fecha(["FECHA DE EMISION 23-062025"]) == "23-06-2025"


def test_procesar_carpeta_crea_proveedor_una_vez_y_lo_reutiliza(tmp_path, monkeypatch):
    """M2: por defecto (sin lector_ocr ni proveedor explícitos), procesar_carpeta
    construye UN proveedor OCR vía crear_proveedor_ocr() para todo el lote —
    no uno por imagen — y se lo pasa a procesar_archivo."""
    carpeta = tmp_path / "guias"
    for nombre in ("a.jpg", "b.jpg", "c.jpg"):
        _crear_archivo(carpeta / nombre)
    proveedor_falso = object()
    crear_proveedor = Mock(return_value=proveedor_falso)
    proveedores_recibidos = []
    monkeypatch.setattr(procesamiento_masivo, "crear_proveedor_ocr", crear_proveedor)

    def procesar(ruta, proveedor=None):
        proveedores_recibidos.append(proveedor)
        return {"tipo_carga": "NO DETERMINADO"}

    monkeypatch.setattr(procesamiento_masivo, "procesar_archivo", procesar)
    procesar_carpeta(carpeta, tmp_path / "resultado.csv")

    crear_proveedor.assert_called_once_with()
    assert proveedores_recibidos == [proveedor_falso, proveedor_falso, proveedor_falso]


def test_lector_inyectado_no_crea_proveedor(tmp_path, monkeypatch):
    carpeta = tmp_path / "guias"
    _crear_archivo(carpeta / "a.jpg")
    lector = object()
    crear_proveedor = Mock()
    procesar = Mock(return_value={"tipo_carga": "BARRAS"})
    monkeypatch.setattr(procesamiento_masivo, "crear_proveedor_ocr", crear_proveedor)
    monkeypatch.setattr(procesamiento_masivo, "procesar_archivo", procesar)

    procesar_carpeta(carpeta, tmp_path / "resultado.csv", lector_ocr=lector)

    crear_proveedor.assert_not_called()
    procesar.assert_called_once_with(next(carpeta.iterdir()), lector_ocr=lector)


def test_proveedor_inyectado_se_reutiliza_sin_crear_otro(tmp_path, monkeypatch):
    carpeta = tmp_path / "guias"
    for nombre in ("a.jpg", "b.jpg"):
        _crear_archivo(carpeta / nombre)
    proveedor_dado = object()
    crear_proveedor = Mock()
    proveedores_recibidos = []
    monkeypatch.setattr(procesamiento_masivo, "crear_proveedor_ocr", crear_proveedor)

    def procesar(ruta, proveedor=None):
        proveedores_recibidos.append(proveedor)
        return {"tipo_carga": "NO DETERMINADO"}

    monkeypatch.setattr(procesamiento_masivo, "procesar_archivo", procesar)
    procesar_carpeta(carpeta, tmp_path / "resultado.csv", proveedor=proveedor_dado)

    crear_proveedor.assert_not_called()
    assert proveedores_recibidos == [proveedor_dado, proveedor_dado]


def test_resumen_cuenta_tipos_y_tiempos(tmp_path):
    carpeta = tmp_path / "guias"
    tipos = {
        "a.jpg": "BARRAS",
        "b.jpg": "ROLLOS",
        "c.jpg": "MIXTO",
        "d.jpg": "NO DETERMINADO",
    }
    for nombre in tipos:
        _crear_archivo(carpeta / nombre)

    resumen = procesar_carpeta(
        carpeta,
        tmp_path / "resultado.csv",
        procesador=lambda ruta: {"tipo_carga": tipos[ruta.name]},
    )

    assert resumen["barras"] == 1
    assert resumen["rollos"] == 1
    assert resumen["mixtos"] == 1
    assert resumen["no_determinados"] == 1
    assert resumen["tiempo_total_segundos"] >= 0
    assert resumen["promedio_segundos_archivo"] >= 0


def _preparar_procesamiento_mock(tmp_path, monkeypatch):
    carpeta = tmp_path / "guias"
    _crear_archivo(carpeta / "a.jpg")
    lector = object()
    procesar = Mock(return_value={"tipo_carga": "NO DETERMINADO"})
    monkeypatch.setattr(procesamiento_masivo, "procesar_archivo", procesar)
    return carpeta, lector, procesar


def test_procesar_carpeta_sin_rango_mantiene_llamada_compatible(
    tmp_path, monkeypatch
):
    carpeta, lector, procesar = _preparar_procesamiento_mock(tmp_path, monkeypatch)

    procesar_carpeta(carpeta, tmp_path / "salida.csv", lector_ocr=lector)

    procesar.assert_called_once_with(next(carpeta.iterdir()), lector_ocr=lector)


@pytest.mark.parametrize(
    ("fecha_desde", "fecha_hasta"),
    [
        (FECHA_DESDE_LOTE, FECHA_HASTA_LOTE),
        (FECHA_DESDE_LOTE, None),
        (None, FECHA_HASTA_LOTE),
    ],
)
def test_procesar_carpeta_pasa_limites_a_procesar_archivo(
    tmp_path, monkeypatch, fecha_desde, fecha_hasta
):
    carpeta, lector, procesar = _preparar_procesamiento_mock(tmp_path, monkeypatch)

    procesar_carpeta(
        carpeta,
        tmp_path / "salida.csv",
        lector_ocr=lector,
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
    )

    procesar.assert_called_once_with(
        next(carpeta.iterdir()),
        lector_ocr=lector,
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
    )


def test_procesar_carpeta_rango_invertido_falla_antes_de_tocar_salida(
    tmp_path, monkeypatch
):
    carpeta, _, procesar = _preparar_procesamiento_mock(tmp_path, monkeypatch)
    salida = tmp_path / "salida.csv"

    with pytest.raises(ValueError, match="fecha_desde no puede"):
        procesar_carpeta(
            carpeta,
            salida,
            fecha_desde=FECHA_HASTA_LOTE,
            fecha_hasta=FECHA_DESDE_LOTE,
        )

    assert not salida.exists()
    procesar.assert_not_called()


def test_reanudacion_con_rango_omite_filas_ya_guardadas(tmp_path, monkeypatch):
    carpeta, lector, procesar = _preparar_procesamiento_mock(tmp_path, monkeypatch)
    salida = tmp_path / "salida.csv"

    procesar_carpeta(
        carpeta,
        salida,
        lector_ocr=lector,
        fecha_desde=FECHA_DESDE_LOTE,
    )
    resumen = procesar_carpeta(
        carpeta,
        salida,
        lector_ocr=lector,
        fecha_desde=FECHA_DESDE_LOTE,
    )

    assert procesar.call_count == 1
    assert resumen["omitidos"] == 1


def _resumen_cli():
    return {
        "encontrados": 0,
        "procesados": 0,
        "omitidos": 0,
        "errores": 0,
        "barras": 0,
        "rollos": 0,
        "mixtos": 0,
        "no_determinados": 0,
        "tiempo_total_segundos": 0.0,
        "promedio_segundos_archivo": 0.0,
    }


def test_cli_acepta_fechas_validas(monkeypatch, tmp_path):
    procesar = Mock(return_value=_resumen_cli())
    monkeypatch.setattr(analizar_guias_masivo, "procesar_carpeta", procesar)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "analizar_guias_masivo.py",
            str(tmp_path),
            "--fecha-desde",
            "2025-01-01",
            "--fecha-hasta",
            "2026-07-31",
            "--sin-catalogos",
        ],
    )

    analizar_guias_masivo.main()

    assert procesar.call_args.kwargs["fecha_desde"] == FECHA_DESDE_LOTE
    assert procesar.call_args.kwargs["fecha_hasta"] == FECHA_HASTA_LOTE


@pytest.mark.parametrize(
    ("opcion", "valor", "mensaje"),
    [
        ("--fecha-desde", "01-01-2025", "YYYY-MM-DD"),
        ("--fecha-hasta", "2025-02-30", "inexistente"),
    ],
)
def test_cli_rechaza_fecha_invalida(
    monkeypatch, tmp_path, capsys, opcion, valor, mensaje
):
    procesar = Mock()
    monkeypatch.setattr(analizar_guias_masivo, "procesar_carpeta", procesar)
    monkeypatch.setattr(
        sys, "argv", ["analizar_guias_masivo.py", str(tmp_path), opcion, valor]
    )

    with pytest.raises(SystemExit) as salida:
        analizar_guias_masivo.main()

    assert salida.value.code == 2
    assert mensaje in capsys.readouterr().err
    procesar.assert_not_called()


def test_cli_rechaza_rango_invertido_antes_de_procesar(
    monkeypatch, tmp_path, capsys
):
    procesar = Mock()
    monkeypatch.setattr(analizar_guias_masivo, "procesar_carpeta", procesar)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "analizar_guias_masivo.py",
            str(tmp_path),
            "--fecha-desde",
            "2026-07-31",
            "--fecha-hasta",
            "2025-01-01",
        ],
    )

    with pytest.raises(SystemExit) as salida:
        analizar_guias_masivo.main()

    assert salida.value.code == 2
    assert "no puede ser posterior" in capsys.readouterr().err
    procesar.assert_not_called()


def test_cli_sin_fechas_mantiene_compatibilidad(monkeypatch, tmp_path):
    procesar = Mock(return_value=_resumen_cli())
    monkeypatch.setattr(analizar_guias_masivo, "procesar_carpeta", procesar)
    monkeypatch.setattr(
        sys,
        "argv",
        ["analizar_guias_masivo.py", str(tmp_path), "--sin-catalogos"],
    )

    analizar_guias_masivo.main()

    assert procesar.call_args.kwargs["fecha_desde"] is None
    assert procesar.call_args.kwargs["fecha_hasta"] is None


def test_columnas_csv_incluyen_peso_y_horarios_operacionales_o1():
    """Bloque O1: `peso_kg`/`hora_entrada_aza`/`hora_salida_aza`/
    `permanencia_minutos` llegan hasta el esquema de `analisis_completo_guias.csv`
    -- antes de este bloque se calculaban internamente pero nunca salían
    de `extraer_datos()`. No se afirma que sean las últimas 6 columnas del
    CSV (bloques posteriores, p. ej. E2E R1, agregan las suyas después) --
    solo que aparecen, en orden, inmediatamente después de `indicador_revision`."""
    indice = COLUMNAS.index("indicador_revision") + 1
    assert COLUMNAS[indice:indice + 6] == [
        "peso_kg", "hora_entrada_aza", "hora_salida_aza", "permanencia_minutos",
        "motivos_revision_documento", "metodos_recuperacion_documento",
    ]


def test_columnas_csv_incluyen_motivos_y_metodos_estados_s2():
    """Bloque ESTADOS S2: `motivos_revision_documento` (calidad del dato,
    explícito) y `metodos_recuperacion_documento` (trazabilidad del método)
    llegan al esquema del CSV masivo -- backward-compatible,
    `indicador_revision` conserva su semántica REVISAR/OK de siempre. No se
    afirma que sean las últimas 2 columnas (bloques posteriores agregan las
    suyas después)."""
    indice = COLUMNAS.index("permanencia_minutos") + 1
    assert COLUMNAS[indice:indice + 2] == ["motivos_revision_documento", "metodos_recuperacion_documento"]
