import csv
import sys
from datetime import date
from unittest.mock import Mock

import pytest

import analizar_guias_masivo
from atlas_core import procesamiento_masivo
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
    monkeypatch.setattr(sys, "argv", ["analizar_guias_masivo.py", str(tmp_path)])

    analizar_guias_masivo.main()

    assert procesar.call_args.kwargs["fecha_desde"] is None
    assert procesar.call_args.kwargs["fecha_hasta"] is None
