"""Bloque CIERRE DUPLICADO DESTINO_NO_RESUELTO -- caso real 473444: dos
tarjetas `DESTINO_NO_RESUELTO` simultáneas para el mismo archivo, mismo
motivo (`GEOCODIFICACION_DIRECCION_NO_ENCONTRADA`, la geocodificación
todavía falla incluso con el texto corregido -- R19 nunca ve un cambio
de motivo), pero `valor_documental` distinto ("VaRGAS BUSTOS 899 SAn
MIGUEL..." vs "VARGAS BUSTOS 899 SAN MIGUEL..."). Tests puramente
sintéticos, nunca tocan G:."""
from __future__ import annotations

import csv
import json

from atlas_core.decisiones_pendientes import (
    crear_decision,
    detectar_decision_destino_no_resuelto,
    regenerar_decisiones_persistidas,
)
from atlas_core.procesamiento_masivo import COLUMNAS

VALOR_VIEJO = "VaRGAS BUSTOS 899 SAn MIGUEL SAN MIGUEL"
VALOR_NUEVO = "VARGAS BUSTOS 899 SAN MIGUEL SAN MIGUEL"


def _catalogos_vacios(tmp_path):
    carpeta = tmp_path / "catalogos"
    carpeta.mkdir()
    for nombre, contenido in {
        "clientes.json": {"version_formato": 1, "clientes": []},
        "obras_destinos.json": {"version_formato": 1, "obras": [], "relaciones": []},
        "destinos_maestros.json": {"version_formato": 1, "destinos": []},
        "vehiculos.json": {"version": 1, "vehiculos": []},
        "plantas.json": {"version_formato": 1, "plantas": []},
    }.items():
        (carpeta / nombre).write_text(json.dumps(contenido), encoding="utf-8")
    return carpeta


def _fila(*, archivo="473444.jpeg", numero_guia="473444", despachar_a_crudo=VALOR_NUEVO, **overrides):
    fila = {c: "" for c in COLUMNAS}
    fila.update({
        "archivo": archivo, "numero_guia": numero_guia, "numero_transporte": "0000357478",
        "despachar_a_crudo": despachar_a_crudo, "planta_origen_id": "PLANTA1",
        "motivo_ruta": "GEOCODIFICACION_DIRECCION_NO_ENCONTRADA", "estado_ruta": "REQUIERE_REVISION",
        "motivos_revision_documento": "", "indicador_revision": "OK", "estado_documental": "OK",
    })
    fila.update(overrides)
    return fila


def _escribir_csv(ruta, filas):
    with ruta.open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader()
        escritor.writerows(filas)


def _decision_destino_real(*, carpeta, fila):
    """Construye la decisión EXACTAMENTE como la produce el detector
    real (`detectar_decision_destino_no_resuelto`) -- nunca a mano,
    para que `contexto`/`evidencias` tengan la forma real."""
    decision = detectar_decision_destino_no_resuelto(
        archivo=str(fila["archivo"]), fila=fila, carpeta_catalogos=carpeta,
    )
    assert decision is not None
    return decision


def _decision_destino_con_valor(*, carpeta, fila, valor_documental):
    """Misma forma que el detector real, pero con un `valor_documental`
    explícito -- simula la tarjeta VIEJA que el detector habría
    producido cuando el dataset todavía traía ese texto."""
    base = _decision_destino_real(carpeta=carpeta, fila=fila)
    return crear_decision(
        tipo=base["tipo"], entidad=base["entidad"], archivo=base["documento"]["archivo"],
        numero_guia=base["documento"]["numero_guia"], numero_transporte=base["documento"]["numero_transporte"],
        campo=base["campo"], valor_documental=valor_documental, valor_normalizado=base["valor_normalizado"],
        identidad_resuelta=base["identidad_resuelta"], candidatos=base["candidatos"], motivos=base["motivos"],
        evidencias=[{**e, "despachar_a_crudo": valor_documental} if "despachar_a_crudo" in e else e for e in base["evidencias"]],
        acciones_permitidas=base["acciones_permitidas"], contexto=base["contexto"],
    )


def test_473444_retira_la_tarjeta_vieja_y_conserva_la_vigente(tmp_path):
    carpeta = _catalogos_vacios(tmp_path)
    dataset = tmp_path / "analisis_completo_guias.csv"
    fila_vigente = _fila(despachar_a_crudo=VALOR_NUEVO)
    _escribir_csv(dataset, [fila_vigente])

    vieja = _decision_destino_con_valor(carpeta=carpeta, fila=fila_vigente, valor_documental=VALOR_VIEJO)
    vigente = _decision_destino_real(carpeta=carpeta, fila=fila_vigente)

    restantes = regenerar_decisiones_persistidas(
        decisiones=[vieja, vigente], carpeta_catalogos=carpeta, ruta_dataset=dataset,
    )
    ids = {d["decision_id"] for d in restantes}
    assert vieja["decision_id"] not in ids
    assert vigente["decision_id"] in ids
    assert len(restantes) == 1


def test_decision_unica_nunca_se_toca_aunque_no_coincida_con_la_fila(tmp_path):
    """Regresión real: una versión anterior de este fix comparaba
    `valor_documental` contra el `despachar_a_crudo` vigente para
    CUALQUIER `DESTINO_NO_RESUELTO`, no sólo duplicados -- rompía
    fixtures sintéticas (de otros bloques) que nunca poblaban ese campo.
    Con una sola decisión (nada que desambiguar), debe sobrevivir
    siempre, incluso si su valor ya no coincide con la fila."""
    carpeta = _catalogos_vacios(tmp_path)
    dataset = tmp_path / "analisis_completo_guias.csv"
    fila_vigente = _fila(despachar_a_crudo=VALOR_NUEVO)
    _escribir_csv(dataset, [fila_vigente])

    unica = _decision_destino_con_valor(carpeta=carpeta, fila=fila_vigente, valor_documental=VALOR_VIEJO)
    restantes = regenerar_decisiones_persistidas(
        decisiones=[unica], carpeta_catalogos=carpeta, ruta_dataset=dataset,
    )
    assert len(restantes) == 1
    assert restantes[0]["decision_id"] == unica["decision_id"]


def test_si_ninguna_coincide_se_retiran_todas(tmp_path):
    """El destino cambió una TERCERA vez -- ninguna de las dos tarjetas
    viejas representa ya la pregunta vigente; ambas se retiran. El
    destino TODAVÍA necesita resolución (mismo motivo de ruta sigue
    vigente), así que el mecanismo de detección ya existente (ajeno a
    este fix) genera una fresca correcta en la MISMA pasada -- nunca
    queda la guía sin ninguna tarjeta."""
    carpeta = _catalogos_vacios(tmp_path)
    dataset = tmp_path / "analisis_completo_guias.csv"
    fila_vigente = _fila(despachar_a_crudo="UNA DIRECCION COMPLETAMENTE DISTINTA")
    _escribir_csv(dataset, [fila_vigente])

    vieja = _decision_destino_con_valor(carpeta=carpeta, fila=fila_vigente, valor_documental=VALOR_VIEJO)
    otra_vieja = _decision_destino_con_valor(carpeta=carpeta, fila=fila_vigente, valor_documental=VALOR_NUEVO)
    restantes = regenerar_decisiones_persistidas(
        decisiones=[vieja, otra_vieja], carpeta_catalogos=carpeta, ruta_dataset=dataset,
    )
    ids = {d["decision_id"] for d in restantes}
    assert vieja["decision_id"] not in ids
    assert otra_vieja["decision_id"] not in ids
    assert len(restantes) == 1  # la fresca, con el valor realmente vigente
    assert restantes[0]["valor_documental"] == "UNA DIRECCION COMPLETAMENTE DISTINTA"


def test_archivo_ambiguo_nunca_se_toca(tmp_path):
    """Dos filas con el mismo `archivo` (colisión) -- `filas_por_archivo`
    ya excluye esa clave por completo; el grupo duplicado de decisiones
    de ESTE bloque queda intacto, nunca se adivina cuál fila es la
    correcta (la detección de candidatas frescas, ajena a este fix, es
    por `numero_guia` y puede seguir agregando una tarjeta más para la
    segunda guía -- eso no es lo que este test verifica)."""
    carpeta = _catalogos_vacios(tmp_path)
    dataset = tmp_path / "analisis_completo_guias.csv"
    fila_vigente = _fila(despachar_a_crudo=VALOR_NUEVO)
    _escribir_csv(dataset, [
        fila_vigente,
        _fila(numero_guia="999", despachar_a_crudo="OTRA COSA"),  # mismo archivo "473444.jpeg" por defecto
    ])
    vieja = _decision_destino_con_valor(carpeta=carpeta, fila=fila_vigente, valor_documental=VALOR_VIEJO)
    vigente = _decision_destino_real(carpeta=carpeta, fila=fila_vigente)
    restantes = regenerar_decisiones_persistidas(
        decisiones=[vieja, vigente], carpeta_catalogos=carpeta, ruta_dataset=dataset,
    )
    ids = {d["decision_id"] for d in restantes}
    assert vieja["decision_id"] in ids  # archivo ambiguo -- este bloque nunca la retira
    assert vigente["decision_id"] in ids


def test_decisiones_de_otros_archivos_no_se_mezclan(tmp_path):
    carpeta = _catalogos_vacios(tmp_path)
    dataset = tmp_path / "analisis_completo_guias.csv"
    fila_473444 = _fila(despachar_a_crudo=VALOR_NUEVO)
    fila_999 = _fila(archivo="999.jpeg", numero_guia="999", despachar_a_crudo="DIRECCION DE OTRA GUIA")
    _escribir_csv(dataset, [fila_473444, fila_999])

    vieja_473444 = _decision_destino_con_valor(carpeta=carpeta, fila=fila_473444, valor_documental=VALOR_VIEJO)
    vigente_473444 = _decision_destino_real(carpeta=carpeta, fila=fila_473444)
    unica_999 = _decision_destino_real(carpeta=carpeta, fila=fila_999)

    restantes = regenerar_decisiones_persistidas(
        decisiones=[vieja_473444, vigente_473444, unica_999], carpeta_catalogos=carpeta, ruta_dataset=dataset,
    )
    ids = {d["decision_id"] for d in restantes}
    assert vieja_473444["decision_id"] not in ids
    assert vigente_473444["decision_id"] in ids
    assert unica_999["decision_id"] in ids  # única de su archivo -- nunca se toca
