import csv
import sys
from pathlib import Path
from datetime import date
from unittest.mock import Mock

import pytest

import analizar_guias_masivo
from atlas_core import procesamiento_masivo
from atlas_core.ocr import BloqueOCR
from atlas_core.politica_activacion_multicampo import (
    EstadoOperacional,
    REGISTRO_ACTIVACION_MULTICAMPO_FASE1,
)
from atlas_core.procesamiento_masivo import (
    COLUMNAS,
    COLUMNAS_PUBLICACION,
    _corregir_codigo_destinatario_por_catalogo,
    _resolver_origen_documental,
    _rut_cliente_requiere_relectura,
    descubrir_archivos,
    extraer_descripcion_material,
    extraer_fecha,
    procesar_archivo,
    procesar_carpeta,
)


def test_origen_documental_exige_consenso_y_planta_unica():
    catalogo = {
        "plantas": [
            {
                "nombre": "AZA RENCA",
                "estado_calidad": "CONFIRMADA",
                "estado_vigencia": "ACTIVA",
            },
            {
                "nombre": "AZA COLINA",
                "estado_calidad": "CONFIRMADA",
                "estado_vigencia": "ACTIVA",
            },
        ]
    }
    lecturas = [
        "ACEROS AZA CASA MATRIZ PLANTA RENCA",
        "ACEROS AZA CASA MATRIZ PLANTA RENECA",
        "texto ilegible",
    ]

    assert _resolver_origen_documental(lecturas, catalogo) == "AZA RENCA"


def test_origen_documental_abstiene_sin_dos_lecturas_coincidentes():
    catalogo = {
        "plantas": [{
            "nombre": "AZA RENCA",
            "estado_calidad": "CONFIRMADA",
            "estado_vigencia": "ACTIVA",
        }]
    }

    assert _resolver_origen_documental(
        ["ACEROS AZA PLANTA RENCA", "texto ilegible"], catalogo
    ) is None


def test_origen_documental_ignora_sucursales_confirmadas_como_plantas():
    """Reproduce con datos reales el catálogo privado vigente (AZA RENCA +
    AZA COLINA, ambas CONFIRMADA/ACTIVA) y el encabezado real de una guía:
    sin el corte en "SUCURSAL", el token COLINA impreso en el directorio de
    sucursales produce una segunda coincidencia y anula el voto para RENCA.
    """
    catalogo = {
        "plantas": [
            {
                "nombre": "AZA RENCA",
                "estado_calidad": "CONFIRMADA",
                "estado_vigencia": "ACTIVA",
            },
            {
                "nombre": "AZA COLINA",
                "estado_calidad": "CONFIRMADA",
                "estado_vigencia": "ACTIVA",
            },
        ]
    }
    lectura_real = (
        "ACEROS AZA S A AZA GIRO: FUNDICION LAMINACION EXPORTACION CASA "
        "MATRIZ PLANTA RENCA LA UNION 3070 RENCA SANTIAGO CHILE COD POSTAL "
        "746 45 22 FONO (56)2267 79100 www aza cl Sucursal Antofagasta "
        "Calle Hector Gomez Cobo 21.000 sector Nudo Uribe Cuidad Antofagasta "
        "Sucursal Temuco Calle Milano 03625 Barrio Industrial Ciudad Temuco "
        "Fono 45 2252 103 Sucursal Talcahuano Jaime Repullo 1014 Ciudad "
        "Talcahuano Sucursal Colina Panamericana Norte KM 18 Colina Santiago "
        "Fono (56) 226779501"
    )

    assert _resolver_origen_documental([lectura_real] * 3, catalogo) == "AZA RENCA"


def test_origen_documental_sin_encabezado_de_sucursales_no_cambia():
    """Sin la palabra "SUCURSAL" el comportamiento es idéntico al previo."""
    catalogo = {
        "plantas": [{
            "nombre": "AZA RENCA",
            "estado_calidad": "CONFIRMADA",
            "estado_vigencia": "ACTIVA",
        }]
    }

    assert _resolver_origen_documental(
        ["ACEROS AZA CASA MATRIZ PLANTA RENCA"] * 2, catalogo
    ) == "AZA RENCA"


@pytest.mark.parametrize(
    ("rut", "esperado"),
    [
        ("93.772.000", True),
        ("93.772.000-1", True),
        ("93.772.000-9", False),
        ("No encontrado", False),
        ("", False),
    ],
)
def test_rut_cliente_requiere_relectura_solo_si_hay_evidencia_invalida(
    rut, esperado
):
    assert _rut_cliente_requiere_relectura(rut) is esperado


def test_rut_cliente_ausente_se_relee_solo_con_cliente_observado():
    assert _rut_cliente_requiere_relectura(
        "No encontrado", "COMERCIAL", etiqueta_rut_observada=True
    ) is True
    assert _rut_cliente_requiere_relectura("", "No encontrado") is False
    assert _rut_cliente_requiere_relectura("", "COMERCIAL") is False


def _catalogo_destinos_con_codigo(
    codigo, estado_calidad="CONFIRMADO", estado_vigencia="ACTIVO"
):
    return {
        "destinos": [
            {
                "codigo_destino": codigo,
                "estado_calidad": estado_calidad,
                "estado_vigencia": estado_vigencia,
            }
        ]
    }


def test_corregir_codigo_destinatario_conserva_coincidencia_exacta():
    catalogo = _catalogo_destinos_con_codigo("0001004443")
    assert (
        _corregir_codigo_destinatario_por_catalogo("0001004443", catalogo)
        == "0001004443"
    )


def test_corregir_codigo_destinatario_tolera_un_solo_digito():
    """Caso real (guía 464345): código real del catálogo maestro
    "0001004443"; código reconstruido por OCR "0001001443" (un solo
    dígito distinto, posición 6). Reutiliza la misma técnica ya probada
    en el proyecto para patentes (`_distancia_patente_ocr` en
    `extractor.py`): distancia de caracteres sobre una cadena de longitud
    fija, exigiendo coincidencia única."""
    catalogo = _catalogo_destinos_con_codigo("0001004443")
    assert (
        _corregir_codigo_destinatario_por_catalogo("0001001443", catalogo)
        == "0001004443"
    )


def test_corregir_codigo_destinatario_abstiene_con_dos_diferencias():
    catalogo = _catalogo_destinos_con_codigo("0001004443")
    assert (
        _corregir_codigo_destinatario_por_catalogo("0001009943", catalogo)
        == "0001009943"
    )


def test_corregir_codigo_destinatario_abstiene_con_longitud_distinta():
    catalogo = _catalogo_destinos_con_codigo("0001004443")
    assert (
        _corregir_codigo_destinatario_por_catalogo("000100444", catalogo)
        == "000100444"
    )


def test_corregir_codigo_destinatario_abstiene_ante_ambiguedad():
    """Si dos códigos activos y confirmados del catálogo quedan igual de
    cerca (distancia 1) del código leído, no se adivina entre ellos —
    mismo criterio conservador de unicidad ya usado para patentes."""
    catalogo = {
        "destinos": [
            {"codigo_destino": "1111111112", "estado_calidad": "CONFIRMADO", "estado_vigencia": "ACTIVO"},
            {"codigo_destino": "2111111111", "estado_calidad": "CONFIRMADO", "estado_vigencia": "ACTIVO"},
        ]
    }
    assert (
        _corregir_codigo_destinatario_por_catalogo("1111111111", catalogo)
        == "1111111111"
    )


def test_corregir_codigo_destinatario_ignora_destino_inactivo_o_no_confirmado():
    catalogo = _catalogo_destinos_con_codigo(
        "0001004443", estado_calidad="PENDIENTE"
    )
    assert (
        _corregir_codigo_destinatario_por_catalogo("0001001443", catalogo)
        == "0001001443"
    )
    catalogo_inactivo = _catalogo_destinos_con_codigo(
        "0001004443", estado_vigencia="INACTIVO"
    )
    assert (
        _corregir_codigo_destinatario_por_catalogo("0001001443", catalogo_inactivo)
        == "0001001443"
    )


def test_corregir_codigo_destinatario_sin_catalogo_no_falla():
    assert _corregir_codigo_destinatario_por_catalogo("0001001443", None) == "0001001443"
    assert _corregir_codigo_destinatario_por_catalogo("", {"destinos": []}) == ""
    assert _corregir_codigo_destinatario_por_catalogo(None, {"destinos": []}) == ""


def _crear_archivo(ruta):
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_bytes(b"simulado")


def _dv(base: str) -> str:
    suma = 0
    factor = 2
    for digito in reversed(base):
        suma += int(digito) * factor
        factor = factor + 1 if factor < 7 else 2
    resto = 11 - suma % 11
    return "0" if resto == 11 else "K" if resto == 10 else str(resto)


def _rut(numero: int) -> str:
    base = f"{numero:08d}"
    return f"{base}-{_dv(base)}"


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
    }
    leer_bloques = Mock()
    focal = Mock()
    monkeypatch.setattr(procesamiento_masivo, "leer_texto_imagen", Mock(return_value=[]))
    monkeypatch.setattr(procesamiento_masivo, "leer_bloques_imagen", leer_bloques)
    monkeypatch.setattr(procesamiento_masivo, "_leer_transporte_focal", focal)
    monkeypatch.setattr(procesamiento_masivo, "extraer_datos", Mock(return_value=datos))

    resultado = procesar_archivo(ruta)

    assert resultado["cliente"] == "CLIENTE LINEAL"
    assert resultado["obra_destino"] == "DESTINO LINEAL"
    assert resultado["numero_transporte"] == "0000123456"
    leer_bloques.assert_not_called()
    focal.assert_not_called()


def test_procesar_archivo_relee_solo_rut_cliente_incompleto(tmp_path, monkeypatch):
    ruta = tmp_path / "guia.jpg"
    bloques = [
        BloqueOCR("SEÑOR(ES)", ((10, 10), (90, 10), (90, 30), (10, 30)), 0.9),
        BloqueOCR("RUT", ((10, 40), (50, 40), (50, 60), (10, 60)), 0.9),
    ]
    datos = {
        "número de guía": "123456",
        "número de transporte": "0000123456",
        "cliente": "PRODALAM SA",
        "RUT del cliente": "93.772.000",
        "obra destino": "DESTINO LINEAL",
        "chofer": "MARIO SOTO",
    }
    focal = Mock(return_value={
        "valor": "93772000-9",
        "motivo": "consenso-modulo-11",
        "lecturas": [],
    })
    resolver_cliente = Mock(wraps=procesamiento_masivo.resolver_cliente_rut)
    monkeypatch.setattr(procesamiento_masivo, "leer_texto_imagen", Mock(return_value=[]))
    monkeypatch.setattr(procesamiento_masivo, "leer_bloques_imagen", Mock(return_value=bloques))
    monkeypatch.setattr(procesamiento_masivo, "extraer_datos", Mock(return_value=datos))
    monkeypatch.setattr(procesamiento_masivo, "_leer_rut_cliente_focal", focal)
    monkeypatch.setattr(procesamiento_masivo, "resolver_cliente_rut", resolver_cliente)
    monkeypatch.setattr(procesamiento_masivo, "cargar_catalogo_json", Mock(return_value={}))
    monkeypatch.setattr("atlas_core.catalogos.cargar_catalogo_json", Mock(return_value={}))

    procesar_archivo(ruta)

    focal.assert_called_once_with(ruta, bloques, lector=None)
    assert resolver_cliente.call_args.args[1] == "93772000-9"


def test_procesar_archivo_abstiene_y_conserva_rut_cliente_ante_conflicto(
    tmp_path, monkeypatch
):
    ruta = tmp_path / "guia.jpg"
    datos = {
        "número de guía": "123456",
        "número de transporte": "0000123456",
        "cliente": "PRODALAM SA",
        "RUT del cliente": "93.772.000",
        "obra destino": "DESTINO LINEAL",
        "chofer": "MARIO SOTO",
    }
    resolver_cliente = Mock(wraps=procesamiento_masivo.resolver_cliente_rut)
    monkeypatch.setattr(procesamiento_masivo, "leer_texto_imagen", Mock(return_value=[]))
    monkeypatch.setattr(procesamiento_masivo, "leer_bloques_imagen", Mock(return_value=[]))
    monkeypatch.setattr(procesamiento_masivo, "extraer_datos", Mock(return_value=datos))
    monkeypatch.setattr(
        procesamiento_masivo,
        "_leer_rut_cliente_focal",
        Mock(return_value={"valor": None, "motivo": "conflicto-ruts-validos"}),
    )
    monkeypatch.setattr(procesamiento_masivo, "resolver_cliente_rut", resolver_cliente)
    monkeypatch.setattr(procesamiento_masivo, "cargar_catalogo_json", Mock(return_value={}))
    monkeypatch.setattr("atlas_core.catalogos.cargar_catalogo_json", Mock(return_value={}))

    procesar_archivo(ruta)

    assert resolver_cliente.call_args.args[1] == "93.772.000"


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


def test_procesar_archivo_abstiene_con_evidencia_focal_baja_confianza(tmp_path, monkeypatch):
    ruta = tmp_path / "guia.jpg"
    bloques = [
        BloqueOCR("NRO TRANSPORTE", ((10, 10), (130, 10), (130, 30), (10, 30)), 0.9),
        BloqueOCR("00do348808", ((180, 10), (280, 10), (280, 30), (180, 30)), 0.8),
    ]
    monkeypatch.setattr(procesamiento_masivo, "leer_texto_imagen", Mock(return_value=[]))
    monkeypatch.setattr(procesamiento_masivo, "leer_bloques_imagen", Mock(return_value=bloques))
    monkeypatch.setattr(
        procesamiento_masivo,
        "_leer_transporte_focal",
        Mock(
            return_value={
                "lecturas": [
                    {"variante": "original", "texto": "0000348808", "confianza": 0.05},
                    {"variante": "grises", "texto": "000o348808", "confianza": 0.06},
                ]
            }
        ),
    )
    monkeypatch.setattr(
        procesamiento_masivo,
        "extraer_datos",
        Mock(return_value={"número de guía": "123456", "número de transporte": "No encontrado", "cliente": "A", "obra destino": "B"}),
    )

    resultado = procesar_archivo(ruta)

    assert resultado["numero_transporte"] == "No encontrado"
    assert resultado["indicador_revision"] == "REVISAR"


def test_procesar_archivo_recupera_origen_girando_la_imagen(tmp_path, monkeypatch):
    """Reproduce el caso real 464108: la foto no confirma origen a 0 grados
    pero sí lo hace tras girarla, y el reintento se detiene en el primer
    giro exitoso sin agotar 180/270."""
    ruta = tmp_path / "guia.jpg"
    datos = {
        "número de guía": "123456",
        "número de transporte": "0000123456",
        "cliente": "PRODALAM SA",
        "obra destino": "DESTINO LINEAL",
        "chofer": "MARIO SOTO",
    }
    catalogo_plantas = {
        "plantas": [{
            "nombre": "AZA RENCA",
            "estado_calidad": "CONFIRMADA",
            "estado_vigencia": "ACTIVA",
        }]
    }

    def cargar_catalogo(ruta_catalogo, *args, **kwargs):
        if Path(ruta_catalogo).name == "plantas.json":
            return catalogo_plantas
        return {}

    def origen_focal(ruta_imagen, lector=None, grados_adicionales=0):
        if grados_adicionales == 90:
            return ["ACEROS AZA CASA MATRIZ PLANTA RENCA"] * 2
        return ["texto irreconocible"] * 3

    origen_focal_mock = Mock(side_effect=origen_focal)
    monkeypatch.setattr(procesamiento_masivo, "leer_texto_imagen", Mock(return_value=[]))
    monkeypatch.setattr(procesamiento_masivo, "leer_bloques_imagen", Mock(return_value=[]))
    monkeypatch.setattr(procesamiento_masivo, "extraer_datos", Mock(return_value=datos))
    monkeypatch.setattr(procesamiento_masivo, "cargar_catalogo_json", Mock(side_effect=cargar_catalogo))
    monkeypatch.setattr("atlas_core.catalogos.cargar_catalogo_json", Mock(return_value={}))
    monkeypatch.setattr(procesamiento_masivo, "leer_encabezado_origen_focal", origen_focal_mock)

    resultado = procesar_archivo(ruta)

    assert resultado["origen"] == "AZA RENCA"
    grados_llamados = [
        llamada.kwargs["grados_adicionales"] for llamada in origen_focal_mock.call_args_list
    ]
    assert grados_llamados == [0, 90]


def test_procesar_archivo_orquestador_destino_usa_catalogo_maestro(
    tmp_path, monkeypatch
):
    """Reproduce la causa raíz real: el resolver de destino debe leer
    destinos_maestros.json (catálogo rico y vigente), nunca destinos.json
    (catálogo legado código->nombre, sin relación con el esquema esperado).
    Verificado con datos reales: el mismo destino resuelve NO_RESUELTO con
    destinos.json y CONFIRMADO con destinos_maestros.json."""
    ruta = tmp_path / "guia.jpg"
    datos = {
        "número de guía": "123456",
        "número de transporte": "0000123456",
        "cliente": "CLIENTE DEMO SPA",
        "obra destino": "BODEGA CENTRAL",
        "direccion": "CALLE UNO 123",
        "comuna": "RENCA",
        "chofer": "MARIO SOTO",
    }
    destinos_maestros = {
        "destinos": [{
            "destino_id": "destino-1",
            "cliente_id": "",
            "nombre_destino": "BODEGA CENTRAL",
            "direccion": "CALLE UNO 123",
            "comuna": "RENCA",
            "region": "RM",
            "pais": "CHILE",
            "aliases": [],
            "estado_calidad": "CONFIRMADO",
            "estado_vigencia": "ACTIVO",
        }]
    }
    # Catálogo legado real: esquema código->nombre, sin la clave "destinos".
    # Si el resolver llegara a leer este archivo, la solicitud queda vacía.
    destinos_legado = {"0000000000": {"nombre": "OTRA COSA", "rut_empresa": "1"}}
    rutas_solicitadas: list[str] = []

    def cargar_catalogo(ruta_catalogo, *args, **kwargs):
        nombre = Path(ruta_catalogo).name
        rutas_solicitadas.append(nombre)
        if nombre == "destinos_maestros.json":
            return destinos_maestros
        if nombre == "destinos.json":
            return destinos_legado
        return {}

    monkeypatch.setattr(procesamiento_masivo, "leer_texto_imagen", Mock(return_value=[]))
    monkeypatch.setattr(procesamiento_masivo, "leer_bloques_imagen", Mock(return_value=[]))
    monkeypatch.setattr(procesamiento_masivo, "extraer_datos", Mock(return_value=datos))
    monkeypatch.setattr(
        procesamiento_masivo, "cargar_catalogo_json", Mock(side_effect=cargar_catalogo)
    )
    monkeypatch.setattr("atlas_core.catalogos.cargar_catalogo_json", Mock(return_value={}))

    resultado = procesar_archivo(
        ruta, campos_controlados_autorizados=frozenset({"destino"})
    )

    assert resultado["obra_destino"] == "BODEGA CENTRAL"
    assert "destinos_maestros.json" in rutas_solicitadas


def test_procesar_archivo_direccion_ausente_no_genera_contradiccion_destino(
    tmp_path, monkeypatch
):
    """Sin dirección/comuna extraídas, el resolver no debe fabricar una
    contradicción de dirección; el destino simplemente no se confirma."""
    ruta = tmp_path / "guia.jpg"
    datos = {
        "número de guía": "123456",
        "número de transporte": "0000123456",
        "cliente": "CLIENTE DEMO SPA",
        "obra destino": "BODEGA CENTRAL",
        "chofer": "MARIO SOTO",
    }
    destinos_maestros = {
        "destinos": [{
            "destino_id": "destino-1",
            "cliente_id": "",
            "nombre_destino": "BODEGA CENTRAL",
            "direccion": "CALLE UNO 123",
            "comuna": "RENCA",
            "region": "RM",
            "pais": "CHILE",
            "aliases": [],
            "estado_calidad": "CONFIRMADO",
            "estado_vigencia": "ACTIVO",
        }]
    }

    def cargar_catalogo(ruta_catalogo, *args, **kwargs):
        if Path(ruta_catalogo).name == "destinos_maestros.json":
            return destinos_maestros
        return {}

    monkeypatch.setattr(procesamiento_masivo, "leer_texto_imagen", Mock(return_value=[]))
    monkeypatch.setattr(procesamiento_masivo, "leer_bloques_imagen", Mock(return_value=[]))
    monkeypatch.setattr(procesamiento_masivo, "extraer_datos", Mock(return_value=datos))
    monkeypatch.setattr(
        procesamiento_masivo, "cargar_catalogo_json", Mock(side_effect=cargar_catalogo)
    )
    monkeypatch.setattr("atlas_core.catalogos.cargar_catalogo_json", Mock(return_value={}))

    resultado = procesar_archivo(
        ruta, campos_controlados_autorizados=frozenset({"destino"})
    )

    # Nombre exacto y único basta para confirmar aunque falte la dirección.
    assert resultado["obra_destino"] == "BODEGA CENTRAL"


def test_procesar_archivo_destino_por_codigo_no_se_pierde_si_sombra_no_confirma(
    tmp_path, monkeypatch
):
    """Reproduce un caso real (464110): el código destinatario ya vinculó el
    maestro confirmado antes de que corra el orquestador en sombra. Si el
    texto libre de "OBRA DESTINO" no coincide por nombre ni dirección, el
    resolver en sombra no confirma nada nuevo — pero eso NO debe pisar el
    valor ya enriquecido por código destinatario con el OCR crudo anterior,
    aun con "destino" autorizado en PRODUCTIVO_CONTROLADO."""
    ruta = tmp_path / "guia.jpg"
    datos = {
        "número de guía": "123456",
        "número de transporte": "0000123456",
        "cliente": "CLIENTE DEMO SPA",
        # Texto libre real de "OBRA DESTINO": el nombre del cliente, no una
        # dirección ni el nombre del destino maestro.
        "obra destino": "CLIENTE DEMO SPA",
        "chofer": "MARIO SOTO",
    }
    destinos_maestros = {
        "destinos": [{
            "destino_id": "destino-1",
            "cliente_id": "",
            "nombre_destino": "BODEGA CENTRAL",
            "codigo_destino": "0001004443",
            "direccion": "CALLE UNO 123",
            "comuna": "RENCA",
            "region": "RM",
            "pais": "CHILE",
            "aliases": [],
            "estado_calidad": "CONFIRMADO",
            "estado_vigencia": "ACTIVO",
        }]
    }

    def cargar_catalogo(ruta_catalogo, *args, **kwargs):
        if Path(ruta_catalogo).name == "destinos_maestros.json":
            return destinos_maestros
        return {}

    def enriquecer(datos_originales, textos, carpeta, *, campos_estructurados=None):
        # Simula el enriquecimiento por código destinatario: reemplaza el
        # texto libre por el nombre del maestro confirmado ANTES de que el
        # orquestador en sombra reciba destino_original.
        enriquecido = dict(datos_originales)
        enriquecido["obra destino"] = "BODEGA CENTRAL"
        return enriquecido

    monkeypatch.setattr(procesamiento_masivo, "leer_texto_imagen", Mock(return_value=[]))
    monkeypatch.setattr(procesamiento_masivo, "leer_bloques_imagen", Mock(return_value=[]))
    monkeypatch.setattr(procesamiento_masivo, "extraer_datos", Mock(return_value=datos))
    monkeypatch.setattr(
        procesamiento_masivo, "cargar_catalogo_json", Mock(side_effect=cargar_catalogo)
    )
    monkeypatch.setattr(
        procesamiento_masivo, "enriquecer_datos_con_catalogos", enriquecer
    )

    resultado = procesar_archivo(
        ruta, campos_controlados_autorizados=frozenset({"destino"})
    )

    # El nombre libre ("CLIENTE DEMO SPA") no coincide con "BODEGA CENTRAL"
    # por nombre ni dirección, así que el resolver en sombra no confirma
    # nada nuevo — pero el valor ya vinculado por código destinatario debe
    # conservarse intacto, no revertir al OCR original.
    assert resultado["obra_destino"] == "BODEGA CENTRAL"


def test_procesar_archivo_resuelve_cliente_por_codigo_destinatario_del_destino(
    tmp_path, monkeypatch
):
    """Reproduce el caso real 464110: cliente y RUT no llegan legibles desde
    el OCR, pero el Código Destinatario ya identifica, a través de un
    destino confirmado y único, el cliente_id vinculado en el catálogo
    maestro. Mecanismo general: Código Destinatario -> destino -> cliente_id
    -> Cliente, sin nombre ni RUT legibles en el documento."""
    ruta = tmp_path / "guia.jpg"
    datos = {
        "número de guía": "123456",
        "número de transporte": "0000123456",
        "cliente": "No encontrado",
        "RUT del cliente": "No encontrado",
        "obra destino": "No encontrado",
        "chofer": "MARIO SOTO",
    }
    bloques = [
        BloqueOCR("COD DESTINATARIO", ((20, 20), (155, 20), (155, 38), (20, 38)), 0.9),
        BloqueOCR("0001004443", ((170, 20), (260, 20), (260, 38), (170, 38)), 0.9),
    ]
    destinos_maestros = {
        "destinos": [{
            "destino_id": "destino-1",
            "cliente_id": "cliente-1",
            "nombre_destino": "VISTA CLARA 2351",
            "codigo_destino": "0001004443",
            "direccion": "VISTA CLARA 2351, CERRILLOS",
            "comuna": "CERRILLOS",
            "region": "RM",
            "pais": "CHILE",
            "aliases": [],
            "estado_calidad": "CONFIRMADO",
            "estado_vigencia": "ACTIVO",
        }]
    }
    clientes = {
        "clientes": [{
            "cliente_id": "cliente-1",
            "razon_social": "TORRES OCARANZA LTDA",
            "nombre_comercial": "",
            "rut": "50234350-5",
            "aliases": [],
            "estado_calidad": "CONFIRMADO",
            "estado_vigencia": "ACTIVO",
        }]
    }

    def cargar_catalogo(ruta_catalogo, *args, **kwargs):
        nombre = Path(ruta_catalogo).name
        if nombre == "destinos_maestros.json":
            return destinos_maestros
        if nombre == "clientes.json":
            return clientes
        return {}

    monkeypatch.setattr(procesamiento_masivo, "leer_texto_imagen", Mock(return_value=[]))
    monkeypatch.setattr(procesamiento_masivo, "leer_bloques_imagen", Mock(return_value=bloques))
    monkeypatch.setattr(procesamiento_masivo, "extraer_datos", Mock(return_value=datos))
    monkeypatch.setattr(
        procesamiento_masivo, "cargar_catalogo_json", Mock(side_effect=cargar_catalogo)
    )
    monkeypatch.setattr("atlas_core.catalogos.cargar_catalogo_json", Mock(return_value={}))

    resultado = procesar_archivo(
        ruta, campos_controlados_autorizados=frozenset({"destino"})
    )

    assert resultado["cliente"] == "TORRES OCARANZA LTDA"
    assert resultado["obra_destino"] == "VISTA CLARA 2351"


def test_procesar_archivo_codigo_destinatario_sin_coincidencia_conserva_abstencion(
    tmp_path, monkeypatch
):
    """Caso real 464260: existe Código Destinatario pero no coincide con
    ningún destino confirmado del catálogo; cliente debe permanecer en
    abstención, igual que sin el mecanismo nuevo."""
    ruta = tmp_path / "guia.jpg"
    datos = {
        "número de guía": "123456",
        "número de transporte": "0000123456",
        "cliente": "No encontrado",
        "RUT del cliente": "No encontrado",
        "obra destino": "No encontrado",
        "chofer": "MARIO SOTO",
    }
    bloques = [
        BloqueOCR("COD DESTINATARIO", ((20, 20), (155, 20), (155, 38), (20, 38)), 0.9),
        BloqueOCR("00D2N032BD", ((170, 20), (260, 20), (260, 38), (170, 38)), 0.9),
    ]
    destinos_maestros = {
        "destinos": [{
            "destino_id": "destino-1",
            "cliente_id": "cliente-1",
            "nombre_destino": "VISTA CLARA 2351",
            "codigo_destino": "0001004443",
            "direccion": "VISTA CLARA 2351, CERRILLOS",
            "comuna": "CERRILLOS",
            "region": "RM",
            "pais": "CHILE",
            "aliases": [],
            "estado_calidad": "CONFIRMADO",
            "estado_vigencia": "ACTIVO",
        }]
    }

    def cargar_catalogo(ruta_catalogo, *args, **kwargs):
        nombre = Path(ruta_catalogo).name
        if nombre == "destinos_maestros.json":
            return destinos_maestros
        return {}

    monkeypatch.setattr(procesamiento_masivo, "leer_texto_imagen", Mock(return_value=[]))
    monkeypatch.setattr(procesamiento_masivo, "leer_bloques_imagen", Mock(return_value=bloques))
    monkeypatch.setattr(procesamiento_masivo, "extraer_datos", Mock(return_value=datos))
    monkeypatch.setattr(
        procesamiento_masivo, "cargar_catalogo_json", Mock(side_effect=cargar_catalogo)
    )
    monkeypatch.setattr("atlas_core.catalogos.cargar_catalogo_json", Mock(return_value={}))

    resultado = procesar_archivo(ruta)

    assert resultado["cliente"] == "No encontrado"


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
    monkeypatch.setattr(procesamiento_masivo, "leer_texto_imagen", Mock(return_value=[]))
    monkeypatch.setattr(procesamiento_masivo, "leer_bloques_imagen", bloques)
    monkeypatch.setattr(
        procesamiento_masivo, "extraer_datos",
        Mock(return_value={"número de guía": "123456", "número de transporte": "0000123456", "cliente": "A", "obra destino": "B", "chofer": "MARIO SOTO"}),
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


def test_procesar_archivo_reemplaza_cliente_y_destino_contaminados_con_geometria(
    tmp_path, monkeypatch
):
    """Reproduce el patrón real de la guía 464260: el extractor lineal arrastra
    la etiqueta de la columna vecina ("SOLICITANTE ..." / "DIRECCION ...") al
    fusionar columnas del párrafo OCR. La contaminación debe habilitar el
    reemplazo geométrico aunque el valor lineal no esté vacío, igual que ya
    ocurre con el chofer.
    """
    ruta = tmp_path / "guia.jpg"
    etiqueta_cliente = BloqueOCR("SEÑOR(ES)", ((10, 10), (90, 10), (90, 30), (10, 30)), 0.9)
    cliente = BloqueOCR("ACEROS SUR", ((150, 10), (240, 10), (240, 30), (150, 30)), 0.9)
    etiqueta_destino = BloqueOCR("OBRA DESTINO", ((10, 50), (115, 50), (115, 70), (10, 70)), 0.9)
    destino = BloqueOCR("PLANTA CENTRAL", ((170, 50), (280, 50), (280, 70), (170, 70)), 0.9)
    monkeypatch.setattr(procesamiento_masivo, "leer_texto_imagen", Mock(return_value=[]))
    monkeypatch.setattr(
        procesamiento_masivo,
        "leer_bloques_imagen",
        Mock(return_value=[destino, cliente, etiqueta_destino, etiqueta_cliente]),
    )
    monkeypatch.setattr(
        procesamiento_masivo,
        "extraer_datos",
        Mock(return_value={
            "número de guía": "123456",
            "número de transporte": "0000123456",
            "cliente": "SOLICITANTE SALCMON SACX SAX SRUOKON SACK",
            "obra destino": "DIRECCION PAES1D EDO FAEL MOYTALVA 9770",
            "chofer": "MARIO SOTO",
        }),
    )

    resultado = procesar_archivo(ruta)

    assert resultado["cliente"] == "ACEROS SUR"
    assert resultado["obra_destino"] == "PLANTA CENTRAL"
    assert resultado["indicador_revision"] == "REVISAR"


def test_procesar_archivo_cliente_y_destino_contaminados_sin_candidato_conservan_valor(
    tmp_path, monkeypatch
):
    ruta = tmp_path / "guia.jpg"
    monkeypatch.setattr(procesamiento_masivo, "leer_texto_imagen", Mock(return_value=[]))
    monkeypatch.setattr(procesamiento_masivo, "leer_bloques_imagen", Mock(return_value=[]))
    monkeypatch.setattr(
        procesamiento_masivo,
        "extraer_datos",
        Mock(return_value={
            "número de guía": "123456",
            "número de transporte": "0000123456",
            "cliente": "SOLICITANTE SALCMON SACX SAX SRUOKON SACK",
            "obra destino": "DIRECCION PAES1D EDO FAEL MOYTALVA 9770",
            "chofer": "MARIO SOTO",
        }),
    )

    resultado = procesar_archivo(ruta)

    assert resultado["cliente"] == "SOLICITANTE SALCMON SACX SAX SRUOKON SACK"
    assert resultado["obra_destino"] == "DIRECCION PAES1D EDO FAEL MOYTALVA 9770"


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


def _preparar_procesamiento_clientes(
    monkeypatch,
    datos,
    *,
    catalogo_clientes,
    catalogo_choferes,
    bloques=None,
):
    monkeypatch.setattr(
        procesamiento_masivo, "leer_texto_imagen", Mock(return_value=[])
    )
    monkeypatch.setattr(
        procesamiento_masivo, "extraer_datos", Mock(return_value=datos)
    )

    def _cargar_catalogo(ruta):
        nombre = Path(ruta).name
        if nombre == "clientes.json":
            return catalogo_clientes
        if nombre == "choferes.json":
            return catalogo_choferes
        return {}

    cargador = Mock(side_effect=_cargar_catalogo)
    monkeypatch.setattr(procesamiento_masivo, "cargar_catalogo_json", cargador)
    monkeypatch.setattr("atlas_core.catalogos.cargar_catalogo_json", cargador)
    if bloques is not None:
        monkeypatch.setattr(
            procesamiento_masivo,
            "leer_bloques_imagen",
            Mock(return_value=bloques),
        )


def test_resolucion_de_cliente_confirma_con_motor_multicampo_y_conserva_ocr_en_contradiccion(
    tmp_path, monkeypatch
):
    datos = {
        "número de guía": "463309",
        "número de transporte": "0000123456",
        "cliente": "CLIENTE OCR",
        "obra destino": "DESTINO ORIGINAL",
        "chofer": "MARIO SOTO",
        "RUT del cliente": "11.111.111-1",
    }
    catalogo = {
        "version_formato": 1,
        "clientes": [
            {
                "cliente_id": "cliente-demo",
                "razon_social": "EMPRESA CATALOGO",
                "nombre_comercial": "",
                "rut": "111111111",
                "aliases": [],
                "estado_calidad": "CONFIRMADO",
                "estado_vigencia": "ACTIVO",
            }
        ],
    }
    _preparar_procesamiento_fuzzy(monkeypatch, datos, catalogo)

    resultado = procesar_archivo(tmp_path / "guia.jpg")

    assert resultado["cliente"] == "CLIENTE OCR"
    assert resultado["indicador_revision"] == "REVISAR"


def test_resolucion_de_cliente_propuesto_marca_revision_en_flujo_principal(
    tmp_path, monkeypatch
):
    datos = {
        "número de guía": "463309",
        "número de transporte": "0000123456",
        "cliente": "ACER0S DEMO DEL NORTE",
        "obra destino": "DESTINO ORIGINAL",
        "chofer": "MARIO SOT0",
        "RUT del chofer": "11.111.111-1",
        "patente del tracto": "ABCD12",
        "patente del carro": "EFGH34",
    }
    catalogo_clientes = {
        "version_formato": 1,
        "clientes": [
            {
                "cliente_id": "cliente-demo-norte",
                "razon_social": "ACEROS DEMO DEL NORTE SpA",
                "nombre_comercial": "ACEROS NORTE DEMO",
                "rut": _rut(101),
                "aliases": ["ADN DEMO"],
                "estado_calidad": "CONFIRMADO",
                "estado_vigencia": "ACTIVO",
            }
        ],
    }
    catalogo_choferes = {
        "111111111": {"nombre": "MARIO SOTO", "activo": True}
    }
    _preparar_procesamiento_clientes(
        monkeypatch,
        datos,
        catalogo_clientes=catalogo_clientes,
        catalogo_choferes=catalogo_choferes,
    )

    resultado = procesar_archivo(tmp_path / "guia.jpg")

    assert resultado["cliente"] == "ACER0S DEMO DEL NORTE"
    assert resultado["chofer"] == "MARIO SOTO"
    assert resultado["indicador_revision"] == "REVISAR"


def test_resolucion_de_cliente_no_resuelto_marca_revision_en_flujo_principal(
    tmp_path, monkeypatch
):
    datos = {
        "número de guía": "463309",
        "número de transporte": "0000123456",
        "cliente": "CLIENTE COMPLETAMENTE AJENO",
        "obra destino": "DESTINO ORIGINAL",
        "chofer": "MARIO SOT0",
        "RUT del chofer": "11.111.111-1",
        "patente del tracto": "ABCD12",
        "patente del carro": "EFGH34",
    }
    catalogo_clientes = {
        "version_formato": 1,
        "clientes": [
            {
                "cliente_id": "cliente-demo-norte",
                "razon_social": "ACEROS DEMO DEL NORTE SpA",
                "nombre_comercial": "ACEROS NORTE DEMO",
                "rut": _rut(101),
                "aliases": ["ADN DEMO"],
                "estado_calidad": "CONFIRMADO",
                "estado_vigencia": "ACTIVO",
            }
        ],
    }
    catalogo_choferes = {
        "111111111": {"nombre": "MARIO SOTO", "activo": True}
    }
    _preparar_procesamiento_clientes(
        monkeypatch,
        datos,
        catalogo_clientes=catalogo_clientes,
        catalogo_choferes=catalogo_choferes,
    )

    resultado = procesar_archivo(tmp_path / "guia.jpg")

    assert resultado["cliente"] == "CLIENTE COMPLETAMENTE AJENO"
    assert resultado["chofer"] == "MARIO SOTO"
    assert resultado["indicador_revision"] == "REVISAR"


def test_resolucion_de_cliente_alias_ambiguo_marca_revision_en_flujo_principal(
    tmp_path, monkeypatch
):
    datos = {
        "número de guía": "463309",
        "número de transporte": "0000123456",
        "cliente": "GRUPO DEMO",
        "obra destino": "DESTINO ORIGINAL",
        "chofer": "MARIO SOT0",
        "RUT del chofer": "11.111.111-1",
        "patente del tracto": "ABCD12",
        "patente del carro": "EFGH34",
    }
    catalogo_clientes = {
        "version_formato": 1,
        "clientes": [
            {
                "cliente_id": "uno",
                "razon_social": "EMPRESA DEMO UNO SA",
                "nombre_comercial": "",
                "rut": _rut(101),
                "aliases": ["GRUPO DEMO"],
                "estado_calidad": "CONFIRMADO",
                "estado_vigencia": "ACTIVO",
            },
            {
                "cliente_id": "dos",
                "razon_social": "EMPRESA DEMO DOS SPA",
                "nombre_comercial": "",
                "rut": _rut(202),
                "aliases": ["GRUPO DEMO"],
                "estado_calidad": "CONFIRMADO",
                "estado_vigencia": "ACTIVO",
            },
        ],
    }
    catalogo_choferes = {
        "111111111": {"nombre": "MARIO SOTO", "activo": True}
    }
    _preparar_procesamiento_clientes(
        monkeypatch,
        datos,
        catalogo_clientes=catalogo_clientes,
        catalogo_choferes=catalogo_choferes,
    )

    resultado = procesar_archivo(tmp_path / "guia.jpg")

    assert resultado["cliente"] == "GRUPO DEMO"
    assert resultado["chofer"] == "MARIO SOTO"
    assert resultado["indicador_revision"] == "REVISAR"


def test_resolucion_de_cliente_rut_contradictorio_marca_revision_en_flujo_principal(
    tmp_path, monkeypatch
):
    datos = {
        "número de guía": "463309",
        "número de transporte": "0000123456",
        "cliente": "ADN DEMO",
        "obra destino": "DESTINO ORIGINAL",
        "chofer": "MARIO SOT0",
        "RUT del cliente": _rut(202),
        "RUT del chofer": "11.111.111-1",
        "patente del tracto": "ABCD12",
        "patente del carro": "EFGH34",
    }
    catalogo_clientes = {
        "version_formato": 1,
        "clientes": [
            {
                "cliente_id": "cliente-demo-norte",
                "razon_social": "ACEROS DEMO DEL NORTE SpA",
                "nombre_comercial": "ACEROS NORTE DEMO",
                "rut": _rut(101),
                "aliases": ["ADN DEMO"],
                "estado_calidad": "CONFIRMADO",
                "estado_vigencia": "ACTIVO",
            },
            {
                "cliente_id": "cliente-demo-sur",
                "razon_social": "TRANSPORTES DEMO DEL SUR LTDA.",
                "nombre_comercial": "",
                "rut": _rut(202),
                "aliases": ["TDS DEMO"],
                "estado_calidad": "CONFIRMADO",
                "estado_vigencia": "ACTIVO",
            },
        ],
    }
    catalogo_choferes = {
        "111111111": {"nombre": "MARIO SOTO", "activo": True}
    }
    _preparar_procesamiento_clientes(
        monkeypatch,
        datos,
        catalogo_clientes=catalogo_clientes,
        catalogo_choferes=catalogo_choferes,
    )

    resultado = procesar_archivo(tmp_path / "guia.jpg")

    assert resultado["cliente"] == "ADN DEMO"
    assert resultado["chofer"] == "MARIO SOTO"
    assert resultado["indicador_revision"] == "REVISAR"


def test_resolucion_de_cliente_alias_unico_confirma_contrato_definitivo_de_catalogo(
    tmp_path, monkeypatch
):
    datos = {
        "número de guía": "463309",
        "número de transporte": "0000123456",
        "cliente": "ADN DEMO",
        "obra destino": "DESTINO ORIGINAL",
        "chofer": "MARIO SOT0",
        "RUT del chofer": "11.111.111-1",
        "patente del tracto": "ABCD12",
        "patente del carro": "EFGH34",
    }
    catalogo_clientes = {
        "version_formato": 1,
        "clientes": [
            {
                "cliente_id": "cliente-demo-norte",
                "razon_social": "ACEROS DEMO DEL NORTE SpA",
                "nombre_comercial": "ACEROS NORTE DEMO",
                "rut": _rut(101),
                "aliases": ["ADN DEMO"],
                "estado_calidad": "CONFIRMADO",
                "estado_vigencia": "ACTIVO",
            }
        ],
    }
    catalogo_choferes = {
        "111111111": {"nombre": "MARIO SOTO", "activo": True}
    }
    _preparar_procesamiento_clientes(
        monkeypatch,
        datos,
        catalogo_clientes=catalogo_clientes,
        catalogo_choferes=catalogo_choferes,
    )

    resultado = procesar_archivo(tmp_path / "guia.jpg")

    assert resultado["cliente"] == "ACEROS DEMO DEL NORTE SpA"
    assert resultado["chofer"] == "MARIO SOTO"
    assert resultado["indicador_revision"] == "OK"


def test_chofer_ocr_ya_coincide_con_canonico_no_fuerza_revision(
    tmp_path, monkeypatch
):
    # Reproduce el defecto ya documentado el 2026-08-01 y confirmado en el
    # diagnóstico de la validación E2E (12/12 REVISAR): el OCR del chofer ya
    # coincide textualmente con el nombre canónico confirmado por RUT (el
    # caso de éxito, sin necesidad de corrección) y aun así el documento
    # quedaba forzado a REVISAR. Con el fix, si el chofer y el cliente
    # confirman limpio, el documento debe quedar OK.
    datos = {
        "número de guía": "463309",
        "número de transporte": "0000123456",
        "cliente": "ADN DEMO",
        "obra destino": "DESTINO ORIGINAL",
        "chofer": "MARIO SOTO",
        "RUT del chofer": "11.111.111-1",
        "patente del tracto": "ABCD12",
        "patente del carro": "EFGH34",
    }
    catalogo_clientes = {
        "version_formato": 1,
        "clientes": [
            {
                "cliente_id": "cliente-demo-norte",
                "razon_social": "ACEROS DEMO DEL NORTE SpA",
                "nombre_comercial": "ACEROS NORTE DEMO",
                "rut": _rut(101),
                "aliases": ["ADN DEMO"],
                "estado_calidad": "CONFIRMADO",
                "estado_vigencia": "ACTIVO",
            }
        ],
    }
    catalogo_choferes = {
        "111111111": {"nombre": "MARIO SOTO", "activo": True}
    }
    _preparar_procesamiento_clientes(
        monkeypatch,
        datos,
        catalogo_clientes=catalogo_clientes,
        catalogo_choferes=catalogo_choferes,
    )

    resultado = procesar_archivo(tmp_path / "guia.jpg")

    assert resultado["chofer"] == "MARIO SOTO"
    assert resultado["cliente"] == "ACEROS DEMO DEL NORTE SpA"
    assert resultado["indicador_revision"] == "OK"


def test_resolucion_de_chofer_confirma_por_rut_en_flujo_principal(
    tmp_path, monkeypatch
):
    datos = {
        "número de guía": "463309",
        "número de transporte": "0000123456",
        "cliente": "CLIENTE ORIGINAL",
        "obra destino": "DESTINO ORIGINAL",
        "chofer": "NOMBRE OCR",
        "RUT del chofer": "11.111.111-1",
        "patente del tracto": "ABCD12",
        "patente del carro": "EFGH34",
    }
    catalogo = {
        "111111111": {"nombre": "ENRIQUE RAMOS", "activo": True},
    }
    _preparar_procesamiento_fuzzy(monkeypatch, datos, catalogo)

    resultado = procesar_archivo(tmp_path / "guia.jpg")

    assert resultado["chofer"] == "ENRIQUE RAMOS"
    assert resultado["numero_guia"] == "463309"
    assert resultado["numero_transporte"] == "0000123456"
    assert resultado["cliente"] == "CLIENTE ORIGINAL"
    assert resultado["obra_destino"] == "DESTINO ORIGINAL"
    assert resultado["patente_tracto"] == "ABCD12"
    assert resultado["patente_rampla"] == "EFGH34"
    assert resultado["indicador_revision"] == "REVISAR"


def test_procesar_archivo_464089_recupera_chofer_ausente_geometricamente(
    tmp_path, monkeypatch
):
    ruta = tmp_path / "464089.jpeg"
    bloques = [
        BloqueOCR("RETIRA", ((10, 10), (70, 10), (70, 30), (10, 30)), 0.98),
        BloqueOCR(
            "LEANDRO TOLEDO",
            ((120, 10), (250, 10), (250, 30), (120, 30)),
            0.97,
        ),
        BloqueOCR("PATENTE", ((10, 40), (80, 40), (80, 60), (10, 60)), 0.99),
    ]
    monkeypatch.setattr(
        procesamiento_masivo, "leer_texto_imagen", Mock(return_value=[])
    )
    monkeypatch.setattr(
        procesamiento_masivo, "leer_bloques_imagen", Mock(return_value=bloques)
    )
    monkeypatch.setattr(
        procesamiento_masivo, "extraer_datos",
        Mock(
            return_value={
                "número de guía": "464089",
                "número de transporte": "0000350880",
                "cliente": "A",
                "obra destino": "B",
                "chofer": "No encontrado",
            }
        ),
    )

    resultado = procesar_archivo(ruta)

    assert resultado["chofer"] == "LEANDRO TOLEDO"
    assert resultado["indicador_revision"] == "REVISAR"


def test_rollback_de_chofer_por_configuracion_conserva_valor_ocr(
    tmp_path, monkeypatch
):
    datos = {
        "nÃºmero de guÃ­a": "463309",
        "nÃºmero de transporte": "0000123456",
        "cliente": "CLIENTE ORIGINAL",
        "obra destino": "DESTINO ORIGINAL",
        "chofer": "NOMBRE OCR",
        "RUT del chofer": "11.111.111-1",
        "patente del tracto": "ABCD12",
        "patente del carro": "EFGH34",
    }
    _preparar_procesamiento_fuzzy(
        monkeypatch,
        datos,
        {"111111111": {"nombre": "ENRIQUE RAMOS", "activo": True}},
    )
    registro_rollback = dict(REGISTRO_ACTIVACION_MULTICAMPO_FASE1)
    registro_rollback["chofer"] = EstadoOperacional.SOMBRA

    resultado = procesar_archivo(
        tmp_path / "guia.jpg",
        registro_activacion=registro_rollback,
    )

    assert resultado["chofer"] == "NOMBRE OCR"
    assert resultado["cliente"] == "CLIENTE ORIGINAL"


def test_resolucion_de_chofer_conserva_recuperacion_geometrica_y_marca_revision(
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

    assert resultado["chofer"] == "ENRIQUE RANOS"
    assert resultado["indicador_revision"] == "REVISAR"


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
    assert resultado["indicador_revision"] == "REVISAR"


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
            "peso",
            "cantidad",
            "origen",
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
    assert lector.fieldnames == COLUMNAS_PUBLICACION
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
    assert lector.fieldnames == COLUMNAS_PUBLICACION
    assert len(filas) == 1


def test_migra_csv_atlas_15_columnas_sin_perder_filas(tmp_path):
    carpeta = tmp_path / "guias"
    _crear_archivo(carpeta / "nueva.jpg")
    salida = tmp_path / "resultado.csv"
    with salida.open("w", encoding="utf-8-sig", newline="") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader()
        escritor.writerow({"archivo": "anterior.jpg", "numero_guia": "100"})

    resumen = procesar_carpeta(
        carpeta,
        salida,
        procesador=lambda ruta: {
            "numero_guia": "200", "peso": "10", "cantidad": "2", "origen": "AZA RENCA"
        },
    )

    with salida.open(encoding="utf-8-sig", newline="") as archivo:
        lector = csv.DictReader(archivo, delimiter=";")
        filas = list(lector)
    assert lector.fieldnames == COLUMNAS_PUBLICACION
    assert filas[0]["numero_guia"] == "100"
    assert filas[0]["peso"] == filas[0]["cantidad"] == filas[0]["origen"] == ""
    assert filas[1]["numero_guia"] == "200"
    assert filas[1]["origen"] == "AZA RENCA"
    assert resumen["procesados"] == 1


def test_acepta_encabezado_exacto_para_reanudar(tmp_path):
    carpeta = tmp_path / "guias"
    _crear_archivo(carpeta / "a.jpg")
    salida = tmp_path / "resultado.csv"
    with salida.open("w", encoding="utf-8-sig", newline="") as archivo:
        csv.writer(archivo, delimiter=";").writerow(COLUMNAS_PUBLICACION)

    resumen = procesar_carpeta(
        carpeta, salida, procesador=lambda ruta: {"numero_guia": "1"}
    )

    assert resumen["procesados"] == 1


@pytest.mark.parametrize(
    "encabezado",
    [
        COLUMNAS[1:],
        COLUMNAS_PUBLICACION + ["columna_extra"],
        [*COLUMNAS_PUBLICACION[:-1], COLUMNAS_PUBLICACION[-2]],
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


def test_fecha_sin_rango_conserva_comportamiento_de_etapa_uno():
    assert extraer_fecha(["FECHA DE EMISIÓN 01-07-7025"]) == "01-07-7025"


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


def test_procesar_archivo_sin_rango_conserva_compatibilidad(tmp_path, monkeypatch):
    ruta = tmp_path / "guia.jpg"
    monkeypatch.setattr(
        procesamiento_masivo,
        "leer_texto_imagen",
        Mock(return_value=["FECHA DE EMISIÓN 01-07-7025"]),
    )
    monkeypatch.setattr(procesamiento_masivo, "extraer_datos", lambda textos: {})

    resultado = procesar_archivo(ruta)

    assert resultado["fecha"] == "01-07-7025"


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


def test_crea_lector_una_vez_y_lo_reutiliza(tmp_path, monkeypatch):
    carpeta = tmp_path / "guias"
    for nombre in ("a.jpg", "b.jpg", "c.jpg"):
        _crear_archivo(carpeta / nombre)
    lector = object()
    crear_lector = Mock(return_value=lector)
    lectores_recibidos = []
    monkeypatch.setattr(procesamiento_masivo, "crear_lector_ocr", crear_lector)

    def procesar(ruta, lector_ocr=None):
        lectores_recibidos.append(lector_ocr)
        return {"tipo_carga": "NO DETERMINADO"}

    monkeypatch.setattr(procesamiento_masivo, "procesar_archivo", procesar)
    procesar_carpeta(carpeta, tmp_path / "resultado.csv")

    crear_lector.assert_called_once_with()
    assert lectores_recibidos == [lector, lector, lector]


def test_lector_inyectado_no_crea_otro(tmp_path, monkeypatch):
    carpeta = tmp_path / "guias"
    _crear_archivo(carpeta / "a.jpg")
    lector = object()
    crear_lector = Mock()
    procesar = Mock(return_value={"tipo_carga": "BARRAS"})
    monkeypatch.setattr(procesamiento_masivo, "crear_lector_ocr", crear_lector)
    monkeypatch.setattr(procesamiento_masivo, "procesar_archivo", procesar)

    procesar_carpeta(carpeta, tmp_path / "resultado.csv", lector_ocr=lector)

    crear_lector.assert_not_called()
    procesar.assert_called_once_with(next(carpeta.iterdir()), lector_ocr=lector)


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
        sys, "argv", ["analizar_guias_masivo.py", str(tmp_path), "--sin-catalogos"]
    )

    analizar_guias_masivo.main()

    assert procesar.call_args.kwargs["fecha_desde"] is None
    assert procesar.call_args.kwargs["fecha_hasta"] is None


def test_cli_sin_autorizar_no_habilita_campos_controlados(monkeypatch, tmp_path):
    procesar = Mock(return_value=_resumen_cli())
    monkeypatch.setattr(analizar_guias_masivo, "procesar_carpeta", procesar)
    monkeypatch.setattr(
        sys, "argv", ["analizar_guias_masivo.py", str(tmp_path), "--sin-catalogos"]
    )

    analizar_guias_masivo.main()

    assert procesar.call_args.kwargs["campos_controlados_autorizados"] == frozenset()


def test_cli_autoriza_campos_controlados_explicitamente(monkeypatch, tmp_path):
    procesar = Mock(return_value=_resumen_cli())
    monkeypatch.setattr(analizar_guias_masivo, "procesar_carpeta", procesar)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "analizar_guias_masivo.py",
            str(tmp_path),
            "--sin-catalogos",
            "--autorizar-campos-controlados",
            "destino, material",
        ],
    )

    analizar_guias_masivo.main()

    assert procesar.call_args.kwargs["campos_controlados_autorizados"] == frozenset(
        {"destino", "material"}
    )
