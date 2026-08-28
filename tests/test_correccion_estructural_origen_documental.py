"""Bloque CORRECCIÓN ESTRUCTURAL DE ORIGEN DOCUMENTAL AZA.

Causa raíz real (472647/472648, transporte 0000355231): "CASA MATRIZ
PLANTA RENCA..." es el domicilio legal/societario del emisor (impreso
IDÉNTICO en cada guía de esa empresa, terminología SII estándar), nunca
la planta física real de despacho. Javier confirma que el membrete/
encabezado corporativo NUNCA debe tratarse como evidencia de origen,
bajo ningún contexto -- ni siquiera cuando coincide con una planta real
del catálogo, ni cuando no hay ninguna otra evidencia disponible.

Ver también `tests/test_rutas_origen_documental.py` (Casos A/B/C: el
membrete/sucursales nunca resuelven; un campo explícito sí). Este
archivo cubre D/E/F/G/I: la generación de decisión ORIGEN_NO_CONFIRMADO
sin candidato falso, el filtrado de candidatos INCOMPATIBLE, la
revalidación de datos legacy, la preservación de evidencia fuerte
previa, y la idempotencia."""
from __future__ import annotations

import csv

from atlas_core.catalogo_plantas import CatalogoPlantas, EstadoCalidad
from atlas_core.decisiones_pendientes import (
    crear_decision, detectar_decision_origen_no_confirmado, regenerar_decisiones_persistidas,
)
from atlas_core.procesamiento_masivo import COLUMNAS
from atlas_core.revalidacion_documental import revalidar_origen_encabezado_no_confiable_sin_ocr


def _plantas(carpeta):
    repo = CatalogoPlantas(carpeta / "plantas.json")
    renca = repo.crear(
        nombre="AZA RENCA", pais="CHILE", fuente="TEST",
        estado_calidad=EstadoCalidad.CONFIRMADA, categorias_permitidas=("ANGULOS",),
    )
    colina = repo.crear(
        nombre="AZA COLINA", pais="CHILE", fuente="TEST",
        estado_calidad=EstadoCalidad.CONFIRMADA, categorias_permitidas=("BARRAS", "ROLLOS"),
    )
    return repo.listar(), renca, colina


def _fila(**overrides):
    fila = {c: "" for c in COLUMNAS}
    fila.update({
        "archivo": "472648.jpeg", "estado_procesamiento": "OK", "numero_guia": "472648",
        "numero_transporte": "0000355231", "fecha": "26-08-2026", "tipo_carga": "BARRAS",
    })
    fila.update(overrides)
    return fila


def _escribir_csv(ruta, filas):
    with ruta.open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader()
        escritor.writerows(filas)


def _leer(ruta):
    return list(csv.DictReader(ruta.open(encoding="utf-8-sig"), delimiter=";"))


# ============================================================
# E. Candidato INCOMPATIBLE nunca aparece como "planta sugerida"
#    (caso real 472648)
# ============================================================


def test_candidato_incompatible_no_aparece_como_sugerido(tmp_path):
    plantas, renca, _colina = _plantas(tmp_path)
    fila = _fila(
        estado_ruta="ORIGEN_NO_DETERMINADO",
        motivo_ruta="CONTRADICCION_OPERACIONAL_ORIGEN[DOCUMENTO=AZA_RENCA:INCOMPATIBLE]",
    )
    decision = detectar_decision_origen_no_confirmado(archivo="472648.jpeg", fila=fila, plantas=plantas)
    assert decision is not None
    assert decision["tipo"] == "ORIGEN_NO_CONFIRMADO"
    # La planta ya descartada por la regla NUNCA figura como candidato --
    # ni como "el único candidato" (que dispararía "Confirmar planta
    # sugerida" en Desktop).
    assert decision["candidatos"] == []
    ids_candidatos = {c.get("planta_id") for c in decision["candidatos"]}
    assert renca.planta_id not in ids_candidatos


def test_candidato_compatible_si_se_ofrece_junto_a_uno_incompatible(tmp_path):
    """Control -- si el motivo trae DOS plantas (Mobile compatible +
    Documento incompatible), sólo la compatible se ofrece como
    candidato; la incompatible se descarta igual."""
    plantas, renca, colina = _plantas(tmp_path)
    fila = _fila(
        estado_ruta="ORIGEN_NO_DETERMINADO",
        motivo_ruta=(
            "CONTRADICCION_OPERACIONAL_ORIGEN[MOBILE=AZA_COLINA:INCOMPATIBLE|"
            "DOCUMENTO=AZA_RENCA:INCOMPATIBLE]"
        ),
    )
    decision = detectar_decision_origen_no_confirmado(archivo="472648.jpeg", fila=fila, plantas=plantas)
    assert decision is not None
    assert decision["candidatos"] == []


# ============================================================
# D. Sin evidencia confiable -> ORIGEN_NO_CONFIRMADO sin candidato falso
# ============================================================


def test_origen_encabezado_no_confiable_genera_decision_neutral_sin_candidato(tmp_path):
    plantas, _renca, _colina = _plantas(tmp_path)
    fila = _fila(estado_ruta="ORIGEN_NO_DETERMINADO", motivo_ruta="ENCABEZADO_GUIA_NO_CONFIABLE")
    decision = detectar_decision_origen_no_confirmado(archivo="472648.jpeg", fila=fila, plantas=plantas)
    assert decision is not None
    assert decision["tipo"] == "ORIGEN_NO_CONFIRMADO"
    assert decision["candidatos"] == []
    assert decision["motivos"] == ["ENCABEZADO_GUIA_NO_CONFIABLE"]


def test_sin_ninguna_senal_de_origen_no_genera_decision_vacia():
    """Control -- sin motivo de contradicción ni de encabezado no
    confiable (p. ej. sin ningún motivo_ruta reconocido), no se genera
    una pregunta totalmente vacía -- misma filosofía ya vigente."""
    fila = {"estado_ruta": "ORIGEN_NO_DETERMINADO", "planta_origen_id": "", "motivo_ruta": "SIN_HISTORICO"}
    assert detectar_decision_origen_no_confirmado(archivo="1.jpeg", fila=fila, plantas=[]) is None


# ============================================================
# F. Dato legacy ENCABEZADO_GUIA se invalida correctamente
#    (caso real 464991/472073/472223/472339/472647)
# ============================================================


def test_revalida_origen_legacy_encabezado_guia(tmp_path):
    fila = _fila(
        numero_guia="472647", planta_origen_id="planta-renca-id", planta_origen_nombre="AZA RENCA",
        origen_determinado_por="DOCUMENTO", evidencia_origen="ENCABEZADO_GUIA",
        distancia_km="14.73", duracion_min="21.3", proveedor_ruta="openrouteservice",
        estado_ruta="RUTA_CALCULADA",
    )
    dataset = tmp_path / "dataset.csv"
    _escribir_csv(dataset, [fila])
    resultado = revalidar_origen_encabezado_no_confiable_sin_ocr(ruta_dataset=dataset)
    assert resultado["guias_actualizadas"] == ["472647"]

    fila_final = _leer(dataset)[0]
    assert fila_final["planta_origen_id"] == ""
    assert fila_final["planta_origen_nombre"] == ""
    assert fila_final["origen_determinado_por"] == ""
    assert fila_final["evidencia_origen"] == ""
    assert fila_final["distancia_km"] == ""
    assert fila_final["duracion_min"] == ""
    assert fila_final["proveedor_ruta"] == ""
    assert fila_final["estado_ruta"] == "ORIGEN_NO_DETERMINADO"
    assert fila_final["motivo_ruta"] == "ENCABEZADO_GUIA_NO_CONFIABLE"


def test_revalidacion_legacy_no_toca_otros_campos(tmp_path):
    fila = _fila(
        numero_guia="472647", cliente="SALOMON SACK SA", obra_destino="SALOMON SACK SA LA CHIMBA",
        rut_cliente="76.111.111-6", chofer="CARLOS FARIAS", patente_tracto="TVKT21",
        planta_origen_id="planta-renca-id", planta_origen_nombre="AZA RENCA",
        origen_determinado_por="DOCUMENTO", evidencia_origen="ENCABEZADO_GUIA",
    )
    dataset = tmp_path / "dataset.csv"
    _escribir_csv(dataset, [fila])
    revalidar_origen_encabezado_no_confiable_sin_ocr(ruta_dataset=dataset)
    fila_final = _leer(dataset)[0]
    assert fila_final["cliente"] == "SALOMON SACK SA"
    assert fila_final["obra_destino"] == "SALOMON SACK SA LA CHIMBA"
    assert fila_final["rut_cliente"] == "76.111.111-6"
    assert fila_final["chofer"] == "CARLOS FARIAS"
    assert fila_final["patente_tracto"] == "TVKT21"


# ============================================================
# G. Evidencia fuerte previa (GPS/Mobile/confirmación humana) no se degrada
# ============================================================


def test_origen_gps_nunca_se_revalida(tmp_path):
    fila = _fila(
        numero_guia="900001", planta_origen_id="planta-x", planta_origen_nombre="AZA RENCA",
        origen_determinado_por="TELEMETRIA_GPS", evidencia_origen="GEOCERCA_PLANTA",
    )
    dataset = tmp_path / "dataset.csv"
    _escribir_csv(dataset, [fila])
    resultado = revalidar_origen_encabezado_no_confiable_sin_ocr(ruta_dataset=dataset)
    assert resultado["guias_actualizadas"] == []
    assert _leer(dataset)[0]["planta_origen_nombre"] == "AZA RENCA"


def test_origen_mobile_nunca_se_revalida(tmp_path):
    fila = _fila(
        numero_guia="900002", planta_origen_id="planta-x", planta_origen_nombre="AZA COLINA",
        origen_determinado_por="MOBILE", evidencia_origen="MOBILE_COMPATIBLE_DOCUMENTO_CONTRADICE_REGLA",
    )
    dataset = tmp_path / "dataset.csv"
    _escribir_csv(dataset, [fila])
    resultado = revalidar_origen_encabezado_no_confiable_sin_ocr(ruta_dataset=dataset)
    assert resultado["guias_actualizadas"] == []
    assert _leer(dataset)[0]["planta_origen_nombre"] == "AZA COLINA"


def test_origen_confirmacion_humana_nunca_se_revalida(tmp_path):
    fila = _fila(
        numero_guia="900003", planta_origen_id="planta-x", planta_origen_nombre="AZA RENCA",
        origen_determinado_por="CONFIRMACION_HUMANA", evidencia_origen="CONFIRMACION_HUMANA_JAVIER",
    )
    dataset = tmp_path / "dataset.csv"
    _escribir_csv(dataset, [fila])
    resultado = revalidar_origen_encabezado_no_confiable_sin_ocr(ruta_dataset=dataset)
    assert resultado["guias_actualizadas"] == []
    assert _leer(dataset)[0]["planta_origen_nombre"] == "AZA RENCA"


def test_origen_documento_con_evidencia_distinta_de_encabezado_no_se_toca(tmp_path):
    """Control -- sólo la firma EXACTA `DOCUMENTO`+`ENCABEZADO_GUIA` se
    revierte; otra combinación (aunque también sea `DOCUMENTO`) se
    conserva."""
    fila = _fila(
        numero_guia="900004", planta_origen_id="planta-x", planta_origen_nombre="AZA RENCA",
        origen_determinado_por="DOCUMENTO", evidencia_origen="OTRA_EVIDENCIA_DOCUMENTAL",
    )
    dataset = tmp_path / "dataset.csv"
    _escribir_csv(dataset, [fila])
    resultado = revalidar_origen_encabezado_no_confiable_sin_ocr(ruta_dataset=dataset)
    assert resultado["guias_actualizadas"] == []


# ============================================================
# I. Idempotencia
# ============================================================


def test_revalidacion_legacy_es_idempotente(tmp_path):
    fila = _fila(
        numero_guia="472647", planta_origen_id="planta-renca-id", planta_origen_nombre="AZA RENCA",
        origen_determinado_por="DOCUMENTO", evidencia_origen="ENCABEZADO_GUIA",
    )
    dataset = tmp_path / "dataset.csv"
    _escribir_csv(dataset, [fila])
    primera = revalidar_origen_encabezado_no_confiable_sin_ocr(ruta_dataset=dataset)
    assert primera["guias_actualizadas"] == ["472647"]
    segunda = revalidar_origen_encabezado_no_confiable_sin_ocr(ruta_dataset=dataset)
    assert segunda["guias_actualizadas"] == []  # ya no vuelve a tocarla -- la firma ya cambió


# ============================================================
# Fixture universal -- otro rubro, nada relacionado con AZA/acero/RENCA
# ============================================================


# ============================================================
# G. Reconciliación de una decisión ORIGEN_NO_CONFIRMADO YA PUBLICADA
#    (caso real 472648): `motivo_ruta` no cambió de texto -- lo que
#    cambió fue la política de `detectar_decision_origen_no_confirmado`
#    sobre cómo interpretarlo. `regenerar_decisiones_persistidas` debe
#    volver a ejecutar el propio detector contra la fila vigente, nunca
#    conservar candidatos ya descartados por la regla.
# ============================================================


def _decision_origen_stale(*, planta_id):
    """Reproduce EXACTAMENTE la forma de una decisión ORIGEN_NO_CONFIRMADO
    publicada por el código ANTERIOR a este bloque (candidato incompatible
    todavía ofrecido como sugerencia) -- caso real 472648."""
    return crear_decision(
        tipo="ORIGEN_NO_CONFIRMADO", entidad="ORIGEN", archivo="472648.jpeg",
        numero_guia="472648", numero_transporte="0000355231",
        campo="planta_origen", valor_documental="", valor_normalizado="",
        identidad_resuelta=None,
        candidatos=[{
            "planta_id": planta_id, "planta_nombre": "AZA RENCA",
            "evidencia_resumen": "fuente=documento, compatibilidad con la regla configurada=incompatible",
        }],
        motivos=["CONTRADICCION_OPERACIONAL_ORIGEN"],
        evidencias=[{
            "tipo": "CONTRADICCION_OPERACIONAL_ORIGEN",
            "motivo_ruta": "CONTRADICCION_OPERACIONAL_ORIGEN[DOCUMENTO=AZA_RENCA:INCOMPATIBLE]",
            "tipo_carga": "BARRAS",
        }],
        acciones_permitidas=["CONFIRMAR_PLANTA", "SELECCIONAR_OTRA_PLANTA", "NO_PUEDO_DETERMINAR", "POSPONER"],
    )


def test_regenerar_decisiones_persistidas_retira_candidato_incompatible_ya_publicado(tmp_path):
    plantas, renca, _colina = _plantas(tmp_path)
    decision_vieja = _decision_origen_stale(planta_id=renca.planta_id)
    fila = _fila(
        estado_ruta="ORIGEN_NO_DETERMINADO",
        motivo_ruta="CONTRADICCION_OPERACIONAL_ORIGEN[DOCUMENTO=AZA_RENCA:INCOMPATIBLE]",
    )
    dataset = tmp_path / "dataset.csv"
    _escribir_csv(dataset, [fila])
    resultado = regenerar_decisiones_persistidas(
        decisiones=[decision_vieja], carpeta_catalogos=tmp_path, ruta_dataset=dataset,
    )
    assert len(resultado) == 1
    # La tarjeta se conserva (sigue habiendo una señal real que investigar
    # -- 472648 no queda huérfana), pero SIN el candidato ya descartado.
    assert resultado[0]["candidatos"] == []
    assert resultado[0]["tipo"] == "ORIGEN_NO_CONFIRMADO"


def test_regenerar_decisiones_persistidas_retira_tarjeta_completa_si_origen_ya_se_resolvio(tmp_path):
    """Control -- si para cuando se regenera la fila YA tiene un origen
    determinado (p. ej. Javier ya lo confirmó por otra vía), la pregunta
    completa se retira -- nunca queda una tarjeta huérfana."""
    plantas, renca, _colina = _plantas(tmp_path)
    decision_vieja = _decision_origen_stale(planta_id=renca.planta_id)
    fila = _fila(
        estado_ruta="RUTA_CALCULADA", planta_origen_id=renca.planta_id, planta_origen_nombre="AZA RENCA",
        motivo_ruta="",
    )
    dataset = tmp_path / "dataset.csv"
    _escribir_csv(dataset, [fila])
    resultado = regenerar_decisiones_persistidas(
        decisiones=[decision_vieja], carpeta_catalogos=tmp_path, ruta_dataset=dataset,
    )
    assert resultado == []


def test_fixture_universal_revalidacion_legacy_otro_rubro(tmp_path):
    fila = _fila(
        numero_guia="900005", cliente="DISTRIBUIDORA GENERICA SPA",
        planta_origen_id="sucursal-x", planta_origen_nombre="SUCURSAL NORTE",
        origen_determinado_por="DOCUMENTO", evidencia_origen="ENCABEZADO_GUIA",
    )
    dataset = tmp_path / "dataset.csv"
    _escribir_csv(dataset, [fila])
    resultado = revalidar_origen_encabezado_no_confiable_sin_ocr(ruta_dataset=dataset)
    assert resultado["guias_actualizadas"] == ["900005"]
    fila_final = _leer(dataset)[0]
    assert fila_final["planta_origen_nombre"] == ""
    assert fila_final["estado_ruta"] == "ORIGEN_NO_DETERMINADO"
