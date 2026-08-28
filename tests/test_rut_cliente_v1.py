"""Bloque RUT CLIENTE V1 -- extracción + corroboración documental del
RUT del cliente/destinatario, y reducción de revisiones innecesarias.

Causa raíz real (guía 472593, envío 36e7aa53-214e-48b0-a96c-14989b60e9aa,
PRODALAM SA -- envío real preservado en G:\\Mi unidad\\Atlas, NUNCA
modificado por este bloque): el RUT del cliente estaba impreso, legible
y en la posición correcta (SEÑOR(ES)/R.U.T.), pero EasyOCR partió el
número en tres cajas separadas ("93"/"772"/"000-9") -- el extractor
geométrico sólo evaluaba cada caja por separado, así que nunca validaba
ninguna como RUT completo. Además, aunque `datos["RUT del cliente"]` SÍ
se calculaba y usaba internamente para corroboración, nunca se exponía
como su propia columna en la salida estructurada (`datos_ocr`/CSV) --
se perdía antes de persistir.

Esta suite cubre los 10 casos del bloque (Sección 16), sin depender de
ningún cliente/formato hardcodeado salvo el propio caso real 472593
(regresión, Sección 2/10)."""
from __future__ import annotations

import json
from unittest.mock import Mock

from atlas_core import procesamiento_masivo
from atlas_core.extractor import _extraer_rut_cliente_geometrico
from atlas_core.ocr import BloqueOCR
from atlas_core.procesamiento_masivo import COLUMNAS, procesar_archivo
from atlas_core.validadores import validar_rut_chileno


def _bloque(texto, x, y, ancho=None, alto=44, conf=0.9):
    ancho = ancho if ancho is not None else max(30, len(texto) * 8)
    return BloqueOCR(
        texto=texto,
        bounding_box=((x, y), (x + ancho, y), (x + ancho, y + alto), (x, y + alto)),
        confianza=conf,
    )


def _datos_lineales_completos(**overrides):
    datos = {
        "número de guía": "123456",
        "número de transporte": "0000123456",
        # Bloque C1: placeholders con contenido real de nombre -- un
        # valor de una sola letra ("A"/"B") ya no es un fixture neutro,
        # es indistinguible de un fragmento truncado real (ver
        # `atlas_core.credibilidad_campos`); ningún test de este archivo
        # depende del valor literal.
        "cliente": "CLIENTE DE PRUEBA SPA",
        "obra destino": "OBRA DE PRUEBA CENTRAL",
        "chofer": "CHOFER DE PRUEBA",
        "RUT del chofer": "11.111.111-1",
        "patente del tracto": "AB1234",
        "patente del carro": "CD5678",
    }
    datos.update(overrides)
    return datos


def _preparar_mocks(monkeypatch, datos, texto_lineal="FECHA DE EMISION 11-08-2026", bloques=None):
    monkeypatch.setattr(procesamiento_masivo, "leer_texto_imagen", Mock(return_value=[texto_lineal]))
    monkeypatch.setattr(procesamiento_masivo, "leer_bloques_imagen", Mock(return_value=bloques or []))
    monkeypatch.setattr(procesamiento_masivo, "extraer_datos", Mock(return_value=datos))


def _escribir_catalogo(tmp_path, nombre_archivo, contenido):
    carpeta = tmp_path / "catalogos"
    carpeta.mkdir(exist_ok=True)
    (carpeta / nombre_archivo).write_text(json.dumps(contenido, ensure_ascii=False), encoding="utf-8")
    return carpeta


# ============================================================
# 0. rut_cliente es su propia columna, backward-compatible (Sección 12)
# ============================================================


def test_rut_cliente_es_su_propia_columna_al_final_backward_compatible():
    assert COLUMNAS[-1] == "rut_cliente"
    assert "rut_chofer" in COLUMNAS  # el campo hermano ya existente no se mueve/renombra


# ============================================================
# 1. RUT cliente visible + nombre coincidente -> corroboración automática
# ============================================================


def test_rut_cliente_visible_y_nombre_coincidente_corrobora_automaticamente(tmp_path, monkeypatch):
    carpeta_catalogos = _escribir_catalogo(tmp_path, "empresas.json", {"937720009": {"nombre": "PRODALAM SA"}})
    _preparar_mocks(
        monkeypatch,
        _datos_lineales_completos(cliente="PRODALAM SA", **{"RUT del cliente": "93.772.000-9"}),
    )

    decisiones = []
    resultado = procesar_archivo(
        tmp_path / "guia.jpg", carpeta_catalogos=carpeta_catalogos, recolector_decisiones=decisiones.extend,
    )

    assert resultado["cliente"] == "PRODALAM SA"
    assert resultado["rut_cliente"] == "93.772.000-9"
    assert "CLIENTE_SIN_CORROBORAR" not in resultado["motivos_revision_documento"]
    assert "RUT_CLIENTE_CONTRADICE_CATALOGO" not in resultado["motivos_revision_documento"]
    # Nunca pide confirmación humana sólo por redundancia burocrática
    # (Sección 5): con RUT exacto corroborado, el documento no requiere
    # revisión por este motivo.
    assert resultado["indicador_revision"] == "OK"


# ============================================================
# 2. RUT válido + nombre variante/alias confirmado -> identidad canónica
# ============================================================


def test_rut_valido_con_variante_de_nombre_resuelve_identidad_canonica(tmp_path, monkeypatch):
    """Corolario necesario: un RUT exacto sigue corrigiendo un nombre
    documental con variante/typo (mismo mecanismo YA existente, ver
    `test_cliente_corroborado_via_rut_propone_alias_sin_escribir_catalogo`
    en test_inteligencia_n1.py) -- la nueva columna rut_cliente no debe
    romper ese camino."""
    carpeta_catalogos = _escribir_catalogo(tmp_path, "empresas.json", {"123456785": {"nombre": "EBEMA SA"}})
    _preparar_mocks(
        monkeypatch,
        _datos_lineales_completos(cliente="EDMA SA", **{"RUT del cliente": "12.345.678-5"}),
    )

    resultado = procesar_archivo(tmp_path / "guia.jpg", carpeta_catalogos=carpeta_catalogos)

    assert resultado["cliente"] == "EBEMA SA"
    assert resultado["rut_cliente"] == "12.345.678-5"
    assert "RUT_CLIENTE_CONTRADICE_CATALOGO" not in resultado["motivos_revision_documento"]


# ============================================================
# 3. RUT cliente inválido -> no corregir silenciosamente
# ============================================================


def test_rut_cliente_invalido_nunca_se_usa_ni_se_corrige_en_silencio(tmp_path, monkeypatch):
    """Caso real WLADIMIR AGUILAR, versión cliente: el dígito verificador
    calza matemáticamente pero el cuerpo es implausible (dígitos
    repetidos) -- Incidencia Documental, nunca un dato operacional ni una
    corrección silenciosa."""
    assert validar_rut_chileno("55.555.555-5").estado.value == "INVALIDO"
    _preparar_mocks(
        monkeypatch,
        _datos_lineales_completos(
            cliente="EMPRESA REAL SA",
            **{"RUT del cliente": "No encontrado", "RUT del cliente (documento, invalido)": "55.555.555-5"},
        ),
    )

    resultado = procesar_archivo(tmp_path / "guia.jpg")

    assert resultado["rut_cliente"] == "No encontrado"  # nunca se usa el valor inválido como dato operacional
    assert "RUT_CLIENTE_INVALIDO" in resultado["motivos_revision_documento"]
    # No bloqueante (Incidencia Documental, mismo criterio que
    # RUT_CHOFER_INVALIDO -- ver MOTIVOS_NO_BLOQUEANTES): la identidad
    # del cliente YA está establecida por nombre, el problema es
    # específicamente el RUT documental -- nunca entra a la cola de
    # Revisión de Atlas (Sección 11 del bloque).
    assert resultado["indicador_revision"] == "OK"


# ============================================================
# 4. RUT cliente contradice catálogo -> conflicto real
# ============================================================


def test_rut_cliente_valido_que_resuelve_a_otra_empresa_es_conflicto_real(tmp_path, monkeypatch):
    """Sección 5 del bloque: nombre documental original resuelve
    confiablemente a una empresa, pero el RUT (también válido) resuelve
    a OTRA empresa distinta en el catálogo -- se marca como conflicto
    real, nunca se acepta la coincidencia de RUT a ciegas."""
    carpeta_catalogos = _escribir_catalogo(tmp_path, "empresas.json", {
        "835854000": {"nombre": "LOGISTICA DEL SUR LTDA"},
        "760830933": {"nombre": "TRANSPORTES DEL NORTE SA"},
    })
    _preparar_mocks(
        monkeypatch,
        _datos_lineales_completos(cliente="LOGISTICA DEL SUR LTDA", **{"RUT del cliente": "76.083.093-3"}),
    )

    resultado = procesar_archivo(tmp_path / "guia.jpg", carpeta_catalogos=carpeta_catalogos)

    assert "RUT_CLIENTE_CONTRADICE_CATALOGO" in resultado["motivos_revision_documento"]
    assert resultado["indicador_revision"] == "REVISAR"  # bloqueante -- requiere revisión humana
    assert resultado["rut_cliente"] == "76.083.093-3"  # el valor documental se conserva, nunca se descarta


def test_rut_cliente_ambiguo_en_nombre_no_catalogado_no_dispara_falso_conflicto(tmp_path, monkeypatch):
    """Si el nombre documental no resuelve con confianza a NINGUNA
    empresa concreta (catálogo vacío/nombre no catalogado), no hay una
    segunda lectura confiable con la que contradecir al RUT -- se sigue
    confiando en el RUT, nunca se inventa un conflicto por descarte."""
    carpeta_catalogos = _escribir_catalogo(tmp_path, "empresas.json", {"937720009": {"nombre": "PRODALAM SA"}})
    _preparar_mocks(
        monkeypatch,
        _datos_lineales_completos(cliente="EMPRESA COMPLETAMENTE DESCONOCIDA SPA", **{"RUT del cliente": "93.772.000-9"}),
    )

    resultado = procesar_archivo(tmp_path / "guia.jpg", carpeta_catalogos=carpeta_catalogos)

    assert "RUT_CLIENTE_CONTRADICE_CATALOGO" not in resultado["motivos_revision_documento"]
    assert resultado["cliente"] == "PRODALAM SA"  # el RUT exacto corrige el nombre, como siempre


# ============================================================
# 5. RUT emisor + cliente + chofer en el mismo documento -> roles correctos
# ============================================================


def test_rut_emisor_cliente_y_chofer_conservan_roles_correctos_sin_confundirse(tmp_path, monkeypatch):
    """Sección 9 del bloque: un RUT de EMISOR arriba del documento (fuera
    de la zona SEÑOR(ES)/cliente) nunca debe confundirse con el RUT del
    cliente -- cada uno resuelve a su propio campo. Mismo patrón que el
    caso real 472593: `cliente` ya viene leído por la vía lineal (no
    hace falta geometría para el NOMBRE), sólo el RUT se recupera por
    geometría."""
    bloques = [
        # Encabezado societario (emisor) -- lejos, sin relación con SEÑOR(ES).
        _bloque("GIRO: FUNDICION", 593, 517),
        _bloque("R.U.T.: 92.176.000-0", 2024, 492),
        # Zona cliente (SEÑOR(ES)/R.U.T.), fragmentado como en 472593.
        _bloque("SEÑOR(ES)", 192, 1133),
        _bloque("CLIENTE GENERICO", 828, 1143, 300),
        _bloque("R.U.T.", 195, 1190, 116),
        _bloque("11", 834, 1194, 54),
        _bloque("222", 901, 1190, 75),
        _bloque("333-9", 989, 1190, 122),
    ]
    assert validar_rut_chileno("11.222.333-9").estado.value == "VALIDO"

    _preparar_mocks(
        monkeypatch,
        _datos_lineales_completos(
            cliente="CLIENTE GENERICO", chofer="JUAN PEREZ",
            **{"RUT del chofer": "10190440-7", "RUT del cliente": "No encontrado"},
        ),
        texto_lineal="RUT CHOFER :10190440-7",
        bloques=bloques,
    )

    resultado = procesar_archivo(tmp_path / "guia.jpg")

    assert resultado["cliente"] == "CLIENTE GENERICO"
    assert resultado["rut_cliente"] == "11.222.333-9"  # nunca "92.176.000-0" (el del emisor)
    assert resultado["rut_chofer"] == "10190440-7"


# ============================================================
# 6. Sin RUT cliente -> degradación segura
# ============================================================


def test_sin_rut_cliente_extraible_degrada_seguro_sin_inventar_nada(tmp_path, monkeypatch):
    _preparar_mocks(
        monkeypatch,
        _datos_lineales_completos(cliente="EMPRESA SIN RUT VISIBLE SA", **{"RUT del cliente": "No encontrado"}),
        bloques=[],
    )

    resultado = procesar_archivo(tmp_path / "guia.jpg")

    assert resultado["rut_cliente"] == "No encontrado"
    assert resultado["cliente"] == "EMPRESA SIN RUT VISIBLE SA"  # el nombre documental se conserva igual


# ============================================================
# 7. Dos RUT candidatos plausibles -> no asignar a ciegas
# ============================================================


def test_dos_candidatos_de_rut_igualmente_plausibles_se_abstiene():
    """Un candidato fragmentado válido (mecanismo nuevo, Sección 7/10)
    compitiendo con OTRO candidato de bloque único también válido en la
    misma zona -- ambigüedad real, nunca se elige uno a ciegas."""
    bloques = [
        _bloque("SEÑOR(ES)", 192, 1133),
        _bloque("CLIENTE GENERICO", 828, 1143, 300),
        _bloque("R.U.T.", 195, 1190, 116),
        _bloque("11", 834, 1190, 54),
        _bloque("222", 901, 1190, 75),
        _bloque("333-9", 989, 1190, 122),
        # Candidato competidor, mismo renglón/zona, RUT distinto también válido.
        _bloque(":76.083.093-3", 1300, 1190, 180),
    ]
    assert _extraer_rut_cliente_geometrico(bloques) == {}


# ============================================================
# 8. Variación geométrica/etiqueta -> extracción robusta
# ============================================================


def test_etiqueta_rut_con_ruido_ocr_minusculas_sigue_reconociendose():
    """Caso real 472593: el OCR leyó la etiqueta como 'RUt' (no 'R.U.T.'
    ni 'RUT') -- debe seguir reconociéndose como la etiqueta de RUT."""
    bloques = [
        _bloque("SEÑOR(ES)", 192, 1133),
        _bloque("CLIENTE GENERICO", 828, 1143, 300),
        _bloque("RUt", 195, 1190, 116, conf=0.4),  # confianza baja, formato ruidoso
        _bloque("11", 834, 1194, 54),
        _bloque("222", 901, 1190, 75),
        _bloque("333-9", 989, 1190, 122),
    ]
    assert _extraer_rut_cliente_geometrico(bloques) == {"valor": "11.222.333-9"}


def test_fragmentos_de_rut_con_pequenas_variaciones_de_gap_siguen_uniendose():
    """No depende de una posición fija (Sección 7) -- variaciones
    pequeñas y realistas de separación horizontal entre fragmentos."""
    for gap in (5, 13, 30):
        bloques = [
            _bloque("SEÑOR(ES)", 192, 1133),
            _bloque("CLIENTE GENERICO", 828, 1143, 300),
            _bloque("R.U.T.", 195, 1190, 116),
            _bloque("11", 834, 1190, 54),
            _bloque("222", 888 + gap, 1190, 75),
            _bloque("333-9", 888 + gap + 75 + gap, 1190, 122),
        ]
        assert _extraer_rut_cliente_geometrico(bloques) == {"valor": "11.222.333-9"}, f"gap={gap}"


# ============================================================
# 9. Fixture de otro formato/empresa -- misma lógica, sin hardcodear
# ============================================================


def test_otro_formato_empresa_generica_misma_logica_sin_hardcodear():
    """Ejemplo del bloque: EMPRESA EJEMPLO LTDA / RUT 12.345.678-5, en un
    único bloque (formato distinto de 472593, sin fragmentación) --
    demuestra que el extractor es genérico, no exclusivo de AZA/PRODALAM."""
    assert validar_rut_chileno("12.345.678-5").estado.value == "VALIDO"
    bloques = [
        _bloque("SEÑOR(ES)", 46, 550, 72, 40),
        _bloque(": EMPRESA EJEMPLO LTDA", 217, 550, 220, 40),
        _bloque("R.U.T.", 47, 590, 40, 40),
        _bloque(":12.345.678-5", 216, 590, 140, 40),
    ]
    assert _extraer_rut_cliente_geometrico(bloques) == {"valor": "12.345.678-5"}


def test_otro_formato_empresa_generica_end_to_end_reduce_revision_innecesaria(tmp_path, monkeypatch):
    """Mismo fixture, ahora de punta a punta: cliente ausente de la
    lectura lineal (recuperado por geometría) + RUT geométrico válido ->
    corroborado, sin pedir revisión sólo por falta de RUT."""
    bloques = [
        _bloque("SEÑOR(ES)", 20, 20, 80),
        _bloque("EMPRESA EJEMPLO LTDA", 180, 20, 220),
        _bloque("R.U.T.", 21, 60, 60),
        _bloque(":12.345.678-5", 190, 60, 140),
    ]
    _preparar_mocks(
        monkeypatch,
        _datos_lineales_completos(cliente="No encontrado", **{"RUT del cliente": "No encontrado"}),
        bloques=bloques,
    )

    resultado = procesar_archivo(tmp_path / "guia.jpg")

    assert resultado["cliente"] == "EMPRESA EJEMPLO LTDA"
    assert resultado["rut_cliente"] == "12.345.678-5"
    assert "CLIENTE_SIN_CORROBORAR" not in resultado["motivos_revision_documento"]


# ============================================================
# 10. Regresión real 472593 (fixture fiel, NUNCA la foto real)
# ============================================================


def test_regresion_472593_geometria_real_recupera_rut_prodalam():
    """Fixture fiel a la geometría REAL leída por EasyOCR sobre
    G:\\Mi unidad\\Atlas\\operacion\\mobile\\envios\\36e7aa53-214e-48b0-
    a96c-14989b60e9aa\\original.jpg (coordenadas/textos reales,
    confirmados por diagnóstico de sólo lectura -- el archivo real NUNCA
    se modifica ni se confirma). El RUT del cliente (93.772.000-9,
    PRODALAM SA) estaba partido en tres cajas por EasyOCR -- exactamente
    el bug que corrige este bloque."""
    bloques = [
        _bloque("SE\u00d1OR(ES)", 192, 1133, 700 - 192, 1177 - 1133, conf=0.995),
        _bloque("PRODALAM", 828, 1143, 1020 - 828, 1187 - 1143, conf=0.699),
        _bloque("SA", 1033, 1143, 1080 - 1033, 1187 - 1143, conf=1.0),
        _bloque("RUt", 195, 1190, 311 - 195, 1234 - 1190, conf=0.392),
        _bloque("93", 834, 1194, 888 - 834, 1231 - 1194, conf=1.0),
        _bloque("772", 901, 1190, 976 - 901, 1231 - 1190, conf=1.0),
        _bloque("000-9", 989, 1190, 1111 - 989, 1231 - 1190, conf=0.834),
        _bloque("GIRO", 192, 1241, 400 - 192, 1285 - 1241, conf=0.983),
        _bloque("TELEFONO", 1621, 1186, 1837 - 1621, 1235 - 1186, conf=0.987),
        # Encabezado societario del emisor (AZA), en otra zona -- nunca
        # debe confundirse con el RUT cliente.
        _bloque("GIRO: FUNDICI\u00d3N", 593, 517, conf=0.814),
        _bloque("R.U.T.: 92.176.000-0", 2024, 492, conf=0.754),
    ]
    assert _extraer_rut_cliente_geometrico(bloques) == {"valor": "93.772.000-9"}


def test_regresion_472593_end_to_end_ya_no_pide_revision_por_falta_de_rut(tmp_path, monkeypatch):
    """De punta a punta, con el `cliente` ya presente (como en el envío
    real -- lo lineal SÍ leyó "PRODALAM SA") y el RUT recuperado por
    geometría: el documento sigue requiriendo revisión por
    OBRA_DESTINO_SIN_CORROBORAR (motivo real, independiente, no se toca
    -- Sección 13: "no limpiar motivos no relacionados"), pero YA NO por
    falta de RUT del cliente."""
    bloques = [
        _bloque("SE\u00d1OR(ES)", 192, 1133, 700 - 192, 1177 - 1133),
        _bloque("PRODALAM", 828, 1143, 1020 - 828, 1187 - 1143),
        _bloque("SA", 1033, 1143, 1080 - 1033, 1187 - 1143),
        _bloque("RUt", 195, 1190, 311 - 195, 1234 - 1190),
        _bloque("93", 834, 1194, 888 - 834, 1231 - 1194),
        _bloque("772", 901, 1190, 976 - 901, 1231 - 1190),
        _bloque("000-9", 989, 1190, 1111 - 989, 1231 - 1190),
    ]
    _preparar_mocks(
        monkeypatch,
        _datos_lineales_completos(
            cliente="PRODALAM SA", obra_destino="No encontrado",
            **{"RUT del cliente": "No encontrado", "indicador_revision": "REVISAR"},
        ),
        bloques=bloques,
    )

    resultado = procesar_archivo(tmp_path / "guia.jpg")

    assert resultado["rut_cliente"] == "93.772.000-9"
    assert "CLIENTE_SIN_CORROBORAR" not in resultado["motivos_revision_documento"]
