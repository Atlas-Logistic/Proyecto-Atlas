"""Bloque FIX RUT DOCUMENTAL -- un RUT documental (chofer/cliente) que no
pasa validación estructural nunca se acepta silenciosamente como dato
operacional. Distingue error documental real (dígito verificador calza,
cuerpo implausible -- p. ej. dígitos repetidos) de duda de OCR (dígito
verificador no calza, comúnmente un solo carácter mal leído): sólo el
primero registra Incidencia Documental automática. Caso real que motivó
este bloque: guía de WLADIMIR AGUILAR con "55.555.555-5" impreso.

Cubre: el validador compartido (`atlas_core.validadores`), el extractor
(`atlas_core.extractor.extraer_datos`), la clasificación en
`atlas_core.procesamiento_masivo.procesar_archivo` (Sección 10, casos
A-E) y la reconciliación/catch-up de documentos ya persistidos
(`atlas_core.revalidacion_documental`), mismo patrón que
`tests/test_transporte_ausente_clasificacion_r5.py`."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import Mock

from atlas_core import procesamiento_masivo
from atlas_core.extractor import extraer_datos
from atlas_core.incidencias_documentales import (
    TIPO_RUT_DOCUMENTAL_INVALIDO,
    VALOR_CANONICO_RUT_NO_CONFIRMADO,
    AlmacenIncidenciasDocumentales,
)
from atlas_core.procesamiento_masivo import COLUMNAS, procesar_archivo
from atlas_core.revalidacion_documental import (
    detectar_incidencias_rut_chofer_invalido_sin_ocr,
    reconciliar_incidencias_rut_chofer_documental,
)
from atlas_core.validadores import (
    EstadoValidacion,
    rut_documentalmente_confirmado_invalido,
    validar_rut_chileno,
)

# ============================================================
# 1. Validador compartido -- plausibilidad
# ============================================================


def test_rut_valido_normal_pasa():
    resultado = validar_rut_chileno("12.345.678-5")
    assert resultado.estado == EstadoValidacion.VALIDO
    assert resultado.valor == "12.345.678-5"


def test_rut_con_cuerpo_de_digito_repetido_es_invalido_aunque_el_digito_verificador_calce():
    """Caso real WLADIMIR AGUILAR: "55.555.555-5" -- el dígito verificador
    SÍ calza matemáticamente (módulo 11 no distingue esto de un RUT real)
    pero el cuerpo es evidentemente ficticio."""
    resultado = validar_rut_chileno("55.555.555-5")
    assert resultado.estado == EstadoValidacion.INVALIDO


def test_rut_con_digito_verificador_incorrecto_sigue_invalido():
    resultado = validar_rut_chileno("12.345.678-9")
    assert resultado.estado == EstadoValidacion.INVALIDO


def test_confirmado_invalido_solo_para_cuerpo_implausible_con_digito_verificador_correcto():
    assert rut_documentalmente_confirmado_invalido("55.555.555-5") is True
    assert rut_documentalmente_confirmado_invalido("11111111-1") is True


def test_confirmado_invalido_es_falso_para_duda_de_ocr_digito_verificador_no_calza():
    # "12.345.678-5" es válido; "-9" no calza -- posible dígito mal leído.
    assert rut_documentalmente_confirmado_invalido("12.345.678-9") is False


def test_confirmado_invalido_es_falso_para_rut_valido_normal():
    assert rut_documentalmente_confirmado_invalido("12.345.678-5") is False


# ============================================================
# 2. Extractor -- nunca acepta un RUT inválido como operacional,
#    pero conserva el valor documental como evidencia
# ============================================================


def test_extractor_rut_chofer_implausible_no_se_acepta_pero_queda_como_evidencia():
    textos = [
        "SEÑOR(ES) : CLIENTE X",
        "RUT ChoFER 55.555.555-5 FECHA SALIDA 20-08-2026",
    ]
    datos = extraer_datos(textos)
    assert datos.get("RUT del chofer", "No encontrado") == "No encontrado"
    assert datos["RUT del chofer (documento, invalido)"] == "55555555-5"


def test_extractor_rut_chofer_valido_se_acepta_normalmente():
    textos = [
        "SEÑOR(ES) : CLIENTE X",
        "RUT ChoFER 12345678-5 FECHA SALIDA 20-08-2026",
    ]
    datos = extraer_datos(textos)
    assert datos["RUT del chofer"] == "12345678-5"
    assert "RUT del chofer (documento, invalido)" not in datos


# ============================================================
# 3. Pipeline (procesar_archivo) -- Sección 10, casos A-E
# ============================================================


def _mocks(monkeypatch, datos_extraidos):
    monkeypatch.setattr(procesamiento_masivo, "leer_texto_imagen", Mock(return_value=["texto"]))
    monkeypatch.setattr(procesamiento_masivo, "leer_bloques_imagen", Mock(return_value=[]))
    monkeypatch.setattr(procesamiento_masivo, "extraer_datos", Mock(return_value=datos_extraidos))


def _datos_base(**overrides):
    datos = {
        "número de guía": "900001",
        "número de transporte": "0000900001",
        "cliente": "CLIENTE X",
        "obra destino": "CLIENTE X",
        "chofer": "PEDRO PRUEBA",
        "RUT del cliente": "12.345.678-5",
        "patente del tracto": "AB1234",
        "patente del carro": "CD5678",
    }
    datos.update(overrides)
    return datos


def _escribir_catalogo(tmp_path, nombre, contenido):
    carpeta = tmp_path / "catalogos"
    carpeta.mkdir(exist_ok=True)
    (carpeta / nombre).write_text(json.dumps(contenido), encoding="utf-8")
    return carpeta


def test_a_rut_chofer_valido_no_genera_incidencia_ni_motivo(tmp_path, monkeypatch):
    _mocks(monkeypatch, _datos_base(**{"RUT del chofer": "12.345.678-5"}))
    resultado = procesar_archivo(tmp_path / "guia.jpg")
    assert "RUT_CHOFER_INVALIDO" not in resultado["motivos_revision_documento"]


def test_b_rut_chofer_invalido_confirmado_con_canonico_en_catalogo_se_usa_y_genera_incidencia(
    tmp_path, monkeypatch
):
    carpeta_catalogos = _escribir_catalogo(
        tmp_path, "choferes.json",
        {"123456785": {"nombre": "PEDRO PRUEBA", "activo": True}},
    )
    _mocks(monkeypatch, _datos_base(**{
        "RUT del chofer": "No encontrado",
        "RUT del chofer (documento, invalido)": "55555555-5",
    }))
    resultado = procesar_archivo(tmp_path / "guia.jpg", carpeta_catalogos=carpeta_catalogos)

    assert "RUT_CHOFER_INVALIDO" in resultado["motivos_revision_documento"]
    # RUT canónico del catálogo (existente, ya corroborado por nombre) se
    # usa operacionalmente -- el valor documental inválido nunca contamina
    # el dato operacional.
    assert resultado["rut_chofer"] == "12.345.678-5"
    # No bloqueante -- se resuelve vía Incidencia Documental, no Revisión
    # de Atlas.
    assert resultado["indicador_revision"] == "OK"


def test_c_rut_chofer_invalido_pero_duda_de_ocr_no_genera_incidencia_automatica(tmp_path, monkeypatch):
    _mocks(monkeypatch, _datos_base(**{
        "RUT del chofer": "No encontrado",
        "RUT del chofer (documento, invalido)": "12345678-9",  # dígito verificador no calza
    }))
    resultado = procesar_archivo(tmp_path / "guia.jpg")
    assert "RUT_CHOFER_INVALIDO" not in resultado["motivos_revision_documento"]


def test_d_rut_chofer_invalido_confirmado_sin_canonico_disponible_nunca_inventa(tmp_path, monkeypatch):
    _mocks(monkeypatch, _datos_base(**{
        "RUT del chofer": "No encontrado",
        "RUT del chofer (documento, invalido)": "55555555-5",
    }))
    resultado = procesar_archivo(tmp_path / "guia.jpg")  # sin catálogo de choferes

    assert "RUT_CHOFER_INVALIDO" in resultado["motivos_revision_documento"]
    assert resultado["rut_chofer"] in {"", "No encontrado"}


def test_e_rut_documental_invalido_nunca_escribe_alias_en_catalogo(tmp_path, monkeypatch):
    carpeta_catalogos = _escribir_catalogo(
        tmp_path, "choferes.json",
        {"123456785": {"nombre": "PEDRO PRUEBA", "activo": True}},
    )
    ruta_choferes = carpeta_catalogos / "choferes.json"
    antes = ruta_choferes.read_bytes()
    _mocks(monkeypatch, _datos_base(**{
        "RUT del chofer": "No encontrado",
        "RUT del chofer (documento, invalido)": "55555555-5",
    }))
    procesar_archivo(tmp_path / "guia.jpg", carpeta_catalogos=carpeta_catalogos)
    assert ruta_choferes.read_bytes() == antes


# ============================================================
# 4. Reconciliación / catch-up de documentos ya persistidos
# ============================================================


def _entorno(tmp_path, *, filas, choferes=None):
    import csv

    raiz = tmp_path / "Atlas"
    actual = raiz / "operacion" / "actual"
    actual.mkdir(parents=True)
    (raiz / "catalogos_privados").mkdir(parents=True)
    dataset = actual / "analisis_completo_guias.csv"
    with dataset.open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader()
        escritor.writerows(filas)
    (raiz / "catalogos_privados" / "choferes.json").write_text(
        json.dumps(choferes or {}), encoding="utf-8",
    )
    return raiz


def _fila(**overrides):
    fila = {c: "" for c in COLUMNAS}
    fila.update({
        "archivo": "1.jpeg", "estado_procesamiento": "OK", "numero_guia": "1",
        "numero_transporte": "0000000001", "cliente": "CLIENTE X",
        "chofer": "WLADIMIR AGUILAR", "rut_chofer": "55.555.555-5",
        "motivos_revision_documento": "", "indicador_revision": "OK",
    })
    fila.update(overrides)
    return fila


def test_detecta_solo_filas_con_rut_confirmado_invalido_y_chofer_identificado(tmp_path):
    filas = [
        _fila(numero_guia="1", rut_chofer="55.555.555-5"),  # confirmado inválido
        _fila(numero_guia="2", rut_chofer="12.345.678-9"),  # duda de OCR -- no calza
        _fila(numero_guia="3", rut_chofer="12.345.678-5"),  # válido
        _fila(numero_guia="4", rut_chofer="55.555.555-5", chofer="No encontrado"),  # sin identidad
    ]
    raiz = _entorno(tmp_path, filas=filas)
    candidatas = detectar_incidencias_rut_chofer_invalido_sin_ocr(raiz_atlas=raiz)
    assert [c["numero_guia"] for c in candidatas] == ["1"]


def test_reconciliar_usa_historico_del_dataset_como_canonico_y_corrige_el_dataset(tmp_path):
    """Caso real WLADIMIR AGUILAR: dos documentos hermanos (472230/472239)
    comparten el mismo RUT documental inválido; otros dos documentos,
    de viajes distintos, comparten un RUT válido y consistente -- ese es
    el histórico usado como canónico."""
    filas = [
        _fila(numero_guia="472230", rut_chofer="55.555.555-5", numero_transporte="0000354443"),
        _fila(numero_guia="472239", rut_chofer="55.555.555-5", numero_transporte="0000354443"),
        _fila(numero_guia="460807", rut_chofer="26.646.499-1", numero_transporte="0000353928"),
        _fila(numero_guia="472008", rut_chofer="26.646.499-1", numero_transporte="0000353932"),
    ]
    raiz = _entorno(tmp_path, filas=filas)
    reloj = lambda: datetime(2026, 8, 25, tzinfo=timezone.utc)

    resultado = reconciliar_incidencias_rut_chofer_documental(raiz_atlas=raiz, reloj=reloj)
    assert resultado["candidatas"] == 2
    assert sorted(resultado["rut_corregido_en_dataset"]) == ["472230", "472239"]

    import csv
    with (raiz / "operacion" / "actual" / "analisis_completo_guias.csv").open(
        "r", newline="", encoding="utf-8-sig"
    ) as archivo:
        filas_tras = {f["numero_guia"]: f for f in csv.DictReader(archivo, delimiter=";")}
    assert filas_tras["472230"]["rut_chofer"] == "26.646.499-1"
    assert filas_tras["472239"]["rut_chofer"] == "26.646.499-1"

    incidencias = AlmacenIncidenciasDocumentales(
        raiz / "catalogos_privados" / "incidencias_documentales.json"
    ).listar()
    assert len(incidencias) == 2
    for incidencia in incidencias:
        assert incidencia.tipo_incidencia == TIPO_RUT_DOCUMENTAL_INVALIDO
        assert incidencia.valor_documental == "55.555.555-5"
        assert incidencia.valor_canonico == "26.646.499-1"
        assert incidencia.actor == ""

    # Idempotente
    segundo = reconciliar_incidencias_rut_chofer_documental(raiz_atlas=raiz, reloj=reloj)
    assert segundo["candidatas"] == 0  # ya no quedan filas con RUT inválido


def test_reconciliar_sin_canonico_disponible_nunca_inventa_y_deja_el_dataset_intacto(tmp_path):
    filas = [_fila(numero_guia="1", chofer="CHOFER SOLITARIO", rut_chofer="55.555.555-5")]
    raiz = _entorno(tmp_path, filas=filas)
    reloj = lambda: datetime(2026, 8, 25, tzinfo=timezone.utc)

    resultado = reconciliar_incidencias_rut_chofer_documental(raiz_atlas=raiz, reloj=reloj)
    assert resultado["candidatas"] == 1
    assert resultado["rut_corregido_en_dataset"] == []

    import csv
    with (raiz / "operacion" / "actual" / "analisis_completo_guias.csv").open(
        "r", newline="", encoding="utf-8-sig"
    ) as archivo:
        fila_tras = next(csv.DictReader(archivo, delimiter=";"))
    assert fila_tras["rut_chofer"] == "55.555.555-5"  # dataset intacto, nunca se inventa

    incidencia = AlmacenIncidenciasDocumentales(
        raiz / "catalogos_privados" / "incidencias_documentales.json"
    ).listar()[0]
    assert incidencia.valor_canonico == VALOR_CANONICO_RUT_NO_CONFIRMADO


def test_reconciliar_usa_catalogo_confirmado_como_canonico(tmp_path):
    filas = [_fila(numero_guia="1", chofer="ANA CATALOGADA", rut_chofer="55.555.555-5")]
    raiz = _entorno(
        tmp_path, filas=filas,
        choferes={"123456785": {"nombre": "ANA CATALOGADA", "activo": True}},
    )
    resultado = reconciliar_incidencias_rut_chofer_documental(raiz_atlas=raiz)
    assert resultado["rut_corregido_en_dataset"] == ["1"]

    incidencia = AlmacenIncidenciasDocumentales(
        raiz / "catalogos_privados" / "incidencias_documentales.json"
    ).listar()[0]
    assert incidencia.valor_canonico == "12.345.678-5"


def test_reconciliar_no_usa_placeholder_pendiente_del_catalogo_como_canonico(tmp_path):
    filas = [_fila(numero_guia="1", chofer="WLADIMIR AGUILAR", rut_chofer="55.555.555-5")]
    raiz = _entorno(
        tmp_path, filas=filas,
        choferes={"PENDIENTE00000006": {"nombre": "WLADIMIR AGUILAR", "activo": True}},
    )
    resultado = reconciliar_incidencias_rut_chofer_documental(raiz_atlas=raiz)
    assert resultado["rut_corregido_en_dataset"] == []
