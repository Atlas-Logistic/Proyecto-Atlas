"""Regresión explícita -- ACEPTACIÓN INDEBIDA DE DESTINO RECHAZADO POR
EVIDENCIA (Codex 472623 / 472624).

472623 y 472624 comparten el transporte 0000355433 (SODIMAC SA). B1 de
472623 dejó evidencia explícita sobre `despachar_a_crudo`:
`VALOR_NO_RESPALDADO_POR_EVIDENCIA` / "SAN LUIS 1201 QUILICURA no aparece
en la evidencia del caso" (`BLOQUEADO_POR_VALIDACION`,
`aplicado_operacionalmente=false`). Pese a eso ambas quedaron
`RUTA_CALCULADA` con ese destino y luego actuaron como historial.

`revalidar_destino_rechazado_por_evidencia_b1_sin_ocr` invalida el
destino/ruta derivados de un valor rechazado, con alcance por transporte,
y deja la fila explícitamente sin resolver.
"""
from __future__ import annotations

import csv
import json

from atlas_core.procesamiento_masivo import COLUMNAS
from atlas_core.revalidacion_documental import (
    revalidar_destino_rechazado_por_evidencia_b1_sin_ocr,
)

SAN_LUIS = "SAN LUIS 1201 QUILICURA"
_CONTAMINADO = "DESTINO_CONTAMINADO_POR_OTRA_SECCION"


def _traza_destino(*, estado="BLOQUEADO_POR_VALIDACION", aceptada=False,
                   motivo_rechazo="VALOR_NO_RESPALDADO_POR_EVIDENCIA",
                   evidencia_en_contra=(), aplicado=False, valor=SAN_LUIS):
    return {
        "campo": "despachar_a_crudo", "dominio": "DESTINO",
        "problema": _CONTAMINADO, "estado": estado,
        "aplicado_operacionalmente": aplicado,
        "contexto_final": {
            "valor_documental": valor,
            "identidad_operacional": {"direccion_entrega": valor, "obra_destino": "No encontrado"},
        },
        "hipotesis": {
            "campo": "despachar_a_crudo", "resultado": "PROPUESTA",
            "valor_propuesto": valor, "valor_observado": valor,
            "evidencia_en_contra": list(evidencia_en_contra),
        },
        "validacion": {"aceptada": aceptada, "motivo_rechazo": motivo_rechazo,
                       "detalle": f'"{valor}" no aparece en la evidencia del caso.'},
    }


def _fila(numero_guia, transporte, *, trazas=None, direccion=SAN_LUIS, despachar=SAN_LUIS,
          estado_ruta="RUTA_CALCULADA", metodos="GEOMETRICO", motivos="",
          indicador="OK", estado_op="OK"):
    fila = {c: "" for c in COLUMNAS}
    fila.update(
        archivo=f"{numero_guia}.jpeg", numero_guia=numero_guia, numero_transporte=transporte,
        cliente="SODIMAC SA", obra_destino="No encontrado",
        despachar_a_crudo=despachar, direccion_entrega=direccion,
        localidad_entrega="Quilicura" if direccion else "", region_entrega="Metropolitana" if direccion else "",
        distancia_km="16.37" if estado_ruta == "RUTA_CALCULADA" else "",
        duracion_min="22.4" if estado_ruta == "RUTA_CALCULADA" else "",
        proveedor_ruta="openrouteservice" if estado_ruta == "RUTA_CALCULADA" else "",
        estado_ruta=estado_ruta, estado_entrega="RESUELTO" if estado_ruta == "RUTA_CALCULADA" else "NO_INTENTADO",
        motivos_revision_documento=motivos, indicador_revision=indicador,
        estado_documental="OK" if indicador == "OK" else "REQUIERE_REVISION", estado_operacional=estado_op,
        metodos_recuperacion_documento=metodos,
        resultado_atlas_ia_json=json.dumps(trazas or [], ensure_ascii=False),
    )
    return fila


def _escribir(ruta, filas, *, ledger=None):
    with ruta.open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNAS, delimiter=";")
        w.writeheader()
        w.writerows(filas)
    (ruta.parent / "decisiones_aplicadas.json").write_text(
        json.dumps({"schema_version": 1, "aplicaciones": ledger or []}), encoding="utf-8",
    )


def _leer(ruta):
    with ruta.open(newline="", encoding="utf-8-sig") as fh:
        return {f["numero_guia"]: f for f in csv.DictReader(fh, delimiter=";")}


# ============================================================
# 1. Invalidación por rechazo explícito de B1
# ============================================================


def test_destino_rechazado_por_b1_no_puede_quedar_ruta_calculada(tmp_path):
    ruta = tmp_path / "guias.csv"
    _escribir(ruta, [_fila("472623", "0000355433", trazas=[_traza_destino()])])
    res = revalidar_destino_rechazado_por_evidencia_b1_sin_ocr(ruta_dataset=ruta)
    assert res["guias_actualizadas"] == ["472623"]
    f = _leer(ruta)["472623"]
    assert f["estado_ruta"] == "REQUIERE_REVISION"
    assert f["motivo_ruta"] == "DESTINO_RECHAZADO_POR_EVIDENCIA_B1"
    assert f["direccion_entrega"] == "" and f["despachar_a_crudo"] == ""
    assert f["distancia_km"] == "" and f["duracion_min"] == "" and f["proveedor_ruta"] == ""
    assert f["estado_entrega"] == "NO_INTENTADO"
    assert _CONTAMINADO in f["motivos_revision_documento"]
    assert f["indicador_revision"] == "REVISAR"
    assert f["estado_operacional"] == "REQUIERE_REVISION"


def test_preserva_evidencia_documental_original_en_la_traza_b1(tmp_path):
    ruta = tmp_path / "guias.csv"
    _escribir(ruta, [_fila("472623", "0000355433", trazas=[_traza_destino()])])
    revalidar_destino_rechazado_por_evidencia_b1_sin_ocr(ruta_dataset=ruta)
    f = _leer(ruta)["472623"]
    # criterio 5: el texto crudo sobrevive para auditar (en la traza)
    assert SAN_LUIS in f["resultado_atlas_ia_json"]


def test_rechazo_por_evidencia_en_contra_tambien_invalida(tmp_path):
    ruta = tmp_path / "guias.csv"
    _escribir(ruta, [_fila("472623", "0000355433", trazas=[_traza_destino(
        estado="RESPONDIO", motivo_rechazo="", evidencia_en_contra=["la evidencia del caso no menciona esa dirección"],
    )])])
    res = revalidar_destino_rechazado_por_evidencia_b1_sin_ocr(ruta_dataset=ruta)
    assert res["guias_actualizadas"] == ["472623"]


# ============================================================
# 2. Alcance por transporte -- dos guías del mismo transporte
# ============================================================


def test_guia_hermana_del_mismo_transporte_tambien_se_invalida(tmp_path):
    ruta = tmp_path / "guias.csv"
    _escribir(ruta, [
        _fila("472623", "0000355433", trazas=[_traza_destino()]),
        # 472624: NO tiene traza de destino propia, pero mismo transporte
        # y mismo valor operacional -> no puede validarse por su hermana.
        _fila("472624", "0000355433", trazas=[]),
    ])
    res = revalidar_destino_rechazado_por_evidencia_b1_sin_ocr(ruta_dataset=ruta)
    assert set(res["guias_actualizadas"]) == {"472623", "472624"}
    for g in ("472623", "472624"):
        assert _leer(ruta)[g]["estado_ruta"] == "REQUIERE_REVISION"
        assert _leer(ruta)[g]["despachar_a_crudo"] == ""


def test_otro_transporte_con_el_mismo_valor_pero_sin_rechazo_no_se_toca(tmp_path):
    ruta = tmp_path / "guias.csv"
    _escribir(ruta, [
        _fila("472623", "0000355433", trazas=[_traza_destino()]),
        # transporte distinto, misma dirección, sin rechazo B1 -> intacta
        _fila("500001", "0000999999", trazas=[]),
    ])
    res = revalidar_destino_rechazado_por_evidencia_b1_sin_ocr(ruta_dataset=ruta)
    assert res["guias_actualizadas"] == ["472623"]
    otra = _leer(ruta)["500001"]
    assert otra["estado_ruta"] == "RUTA_CALCULADA"
    assert otra["direccion_entrega"] == SAN_LUIS


# ============================================================
# 3. Abstención ante evidencia superior
# ============================================================


def test_no_invalida_si_b1_acepto_el_destino(tmp_path):
    ruta = tmp_path / "guias.csv"
    _escribir(ruta, [_fila("472623", "0000355433", trazas=[
        _traza_destino(estado="RESUELTO_POR_IA", aceptada=True, motivo_rechazo="", aplicado=True),
    ])])
    res = revalidar_destino_rechazado_por_evidencia_b1_sin_ocr(ruta_dataset=ruta)
    assert res["guias_actualizadas"] == []
    assert _leer(ruta)["472623"]["estado_ruta"] == "RUTA_CALCULADA"


def test_no_invalida_si_hay_registrar_direccion_humano_en_el_ledger(tmp_path):
    ruta = tmp_path / "guias.csv"
    _escribir(ruta, [_fila("472623", "0000355433", trazas=[_traza_destino()])], ledger=[{
        "tipo": "DESTINO_NO_RESUELTO", "accion": "REGISTRAR_DIRECCION",
        "documento": {"numero_guia": "472623"}, "direccion_manual": SAN_LUIS,
    }])
    res = revalidar_destino_rechazado_por_evidencia_b1_sin_ocr(ruta_dataset=ruta)
    assert res["guias_actualizadas"] == []
    assert _leer(ruta)["472623"]["estado_ruta"] == "RUTA_CALCULADA"


def test_no_invalida_si_el_destino_vino_de_catalogo_confirmado(tmp_path):
    ruta = tmp_path / "guias.csv"
    _escribir(ruta, [_fila("472623", "0000355433", trazas=[_traza_destino()],
                           metodos="CATALOGO_OBRA_DESTINO | GEOMETRICO")])
    res = revalidar_destino_rechazado_por_evidencia_b1_sin_ocr(ruta_dataset=ruta)
    assert res["guias_actualizadas"] == []


# ============================================================
# 4. Idempotencia y no-daño colateral
# ============================================================


def test_idempotente(tmp_path):
    ruta = tmp_path / "guias.csv"
    _escribir(ruta, [
        _fila("472623", "0000355433", trazas=[_traza_destino()]),
        _fila("472624", "0000355433", trazas=[]),
    ])
    assert len(revalidar_destino_rechazado_por_evidencia_b1_sin_ocr(ruta_dataset=ruta)["guias_actualizadas"]) == 2
    assert revalidar_destino_rechazado_por_evidencia_b1_sin_ocr(ruta_dataset=ruta)["guias_actualizadas"] == []


def test_fila_sin_destino_operacional_no_se_toca_472477(tmp_path):
    """Una fila ya sin `despachar_a_crudo`/`direccion_entrega` (p. ej.
    472477 tras su propia limpieza) no vuelve a tocarse aunque comparta
    universo con un transporte rechazado."""
    ruta = tmp_path / "guias.csv"
    filas = [
        _fila("472623", "0000355433", trazas=[_traza_destino()]),
        _fila("472477", "0000354870", trazas=[], direccion="", despachar="",
              estado_ruta="REQUIERE_REVISION", motivos="MATERIAL_AUSENTE | " + _CONTAMINADO,
              indicador="REVISAR", estado_op="REQUIERE_REVISION"),
    ]
    _escribir(ruta, filas)
    res = revalidar_destino_rechazado_por_evidencia_b1_sin_ocr(ruta_dataset=ruta)
    assert res["guias_actualizadas"] == ["472623"]
    f477 = _leer(ruta)["472477"]
    assert f477["motivos_revision_documento"] == "MATERIAL_AUSENTE | " + _CONTAMINADO
    assert f477["despachar_a_crudo"] == "" and f477["direccion_entrega"] == ""


def test_sin_ninguna_traza_de_rechazo_no_cambia_nada(tmp_path):
    ruta = tmp_path / "guias.csv"
    _escribir(ruta, [_fila("500002", "0000555555", trazas=[
        {"campo": "patente_tracto", "dominio": "PATENTE", "estado": "RESUELTO_POR_IA",
         "aplicado_operacionalmente": False, "validacion": {"aceptada": True}},
    ])])
    res = revalidar_destino_rechazado_por_evidencia_b1_sin_ocr(ruta_dataset=ruta)
    assert res["guias_actualizadas"] == []
