"""Regresión explícita -- BRECHA DE CITACIÓN DE EVIDENCIA PROPIA (Codex
472623 / 472624).

472623 (SODIMAC SA, transporte 0000355433) trae, en su propia traza B1:
`valor_documental_observado` == `identidad_operacional.direccion_entrega`
== `valor_propuesto` == `valor_observado` == "SAN LUIS 1201 QUILICURA",
sin `evidencia_en_contra`, confianza declarada 0.93 -- B1 propuso aceptar
ese valor citando ÚNICAMENTE evidencia del propio documento. El validador
lo bloqueó por `VALOR_NO_RESPALDADO_POR_EVIDENCIA` sólo porque
`contexto_final.evidencias` llegó vacío (brecha de empaquetado, no de
contenido) -- `revalidar_destino_rechazado_por_evidencia_b1_sin_ocr` (la
función HERMANA) ya invalidó correctamente el destino de la fila,
dejándola `despachar_a_crudo=""` con `DESTINO_CONTAMINADO_POR_OTRA_
SECCION`.

`revalidar_destino_propio_respaldado_por_b1_sin_ocr` reconoce ESTE perfil
exacto (evidencia propia, sin contradicción, alta confianza) y restaura
`despachar_a_crudo` al mismo texto ya observado -- nunca relaja la regla
para evidencia que cita OTRO documento/catálogo/historial (eso sigue
siendo terreno exclusivo de la función hermana, y de 472477)."""
from __future__ import annotations

import csv
import json

from atlas_core.procesamiento_masivo import COLUMNAS
from atlas_core.revalidacion_documental import (
    revalidar_destino_propio_respaldado_por_b1_sin_ocr,
)

SAN_LUIS = "SAN LUIS 1201 QUILICURA"
_CONTAMINADO = "DESTINO_CONTAMINADO_POR_OTRA_SECCION"


def _traza_propia(
    *, valor=SAN_LUIS, evidencia_usada=("valor_documental_observado", "identidad_operacional.direccion_entrega"),
    confianza=0.93, evidencia_en_contra=(),
):
    return {
        "campo": "despachar_a_crudo", "dominio": "DESTINO",
        "problema": _CONTAMINADO, "estado": "BLOQUEADO_POR_VALIDACION",
        "aplicado_operacionalmente": False,
        "contexto_final": {
            "valor_documental": valor,
            "identidad_operacional": {"direccion_entrega": valor, "obra_destino": "No encontrado"},
        },
        "hipotesis": {
            "campo": "despachar_a_crudo", "resultado": "PROPUESTA",
            "valor_propuesto": valor, "valor_observado": valor,
            "evidencia_usada": list(evidencia_usada),
            "evidencia_en_contra": list(evidencia_en_contra),
            "metadata": {"confianza_declarada": confianza},
        },
        "validacion": {
            "aceptada": False, "motivo_rechazo": "VALOR_NO_RESPALDADO_POR_EVIDENCIA",
            "detalle": f'"{valor}" no aparece en la evidencia del caso.',
        },
    }


def _fila(numero_guia, transporte, *, trazas=None, despachar="", motivos=_CONTAMINADO,
          indicador="REVISAR", estado_op="REQUIERE_REVISION", estado_ruta="REQUIERE_REVISION",
          motivo_ruta="DESTINO_RECHAZADO_POR_EVIDENCIA_B1"):
    fila = {c: "" for c in COLUMNAS}
    fila.update(
        archivo=f"{numero_guia}.jpeg", numero_guia=numero_guia, numero_transporte=transporte,
        cliente="SODIMAC SA", obra_destino="No encontrado",
        despachar_a_crudo=despachar, direccion_entrega="",
        estado_ruta=estado_ruta, motivo_ruta=motivo_ruta, estado_entrega="NO_INTENTADO",
        motivos_revision_documento=motivos, indicador_revision=indicador,
        estado_documental="OK" if indicador == "OK" else "REQUIERE_REVISION", estado_operacional=estado_op,
        resultado_atlas_ia_json=json.dumps(trazas or [], ensure_ascii=False),
    )
    return fila


def _escribir(ruta, filas):
    with ruta.open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNAS, delimiter=";")
        w.writeheader()
        w.writerows(filas)


def _leer(ruta):
    with ruta.open(newline="", encoding="utf-8-sig") as fh:
        return {f["numero_guia"]: f for f in csv.DictReader(fh, delimiter=";")}


# ============================================================
# 1. Restauración por evidencia propia sin contradicción
# ============================================================


def test_restaura_destino_con_evidencia_propia_sin_contradiccion(tmp_path):
    ruta = tmp_path / "guias.csv"
    _escribir(ruta, [_fila("472623", "0000355433", trazas=[_traza_propia()])])
    res = revalidar_destino_propio_respaldado_por_b1_sin_ocr(ruta_dataset=ruta)
    assert res["guias_actualizadas"] == ["472623"]
    f = _leer(ruta)["472623"]
    assert f["despachar_a_crudo"] == SAN_LUIS
    assert _CONTAMINADO not in f["motivos_revision_documento"]
    # Nunca calcula ruta aquí -- sin red -- sólo deja la fila lista para
    # que la geocodificación real de la operación normal la recalcule.
    assert f["estado_ruta"] == ""
    assert f["motivo_ruta"] == ""
    assert f["direccion_entrega"] == ""


def test_no_relaja_la_regla_si_cita_evidencia_de_otro_documento(tmp_path):
    """472477: sin traza propia de destino (o citando algo fuera del
    documento) -- nunca se restaura a ciegas."""
    ruta = tmp_path / "guias.csv"
    traza = _traza_propia(evidencia_usada=("historial_destino_otra_guia",))
    _escribir(ruta, [_fila("472477", "0000354870", trazas=[traza])])
    res = revalidar_destino_propio_respaldado_por_b1_sin_ocr(ruta_dataset=ruta)
    assert res["guias_actualizadas"] == []
    assert _leer(ruta)["472477"]["despachar_a_crudo"] == ""


def test_no_relaja_la_regla_si_hay_evidencia_en_contra(tmp_path):
    ruta = tmp_path / "guias.csv"
    traza = _traza_propia(evidencia_en_contra=["la evidencia del caso no menciona esa dirección"])
    _escribir(ruta, [_fila("472623", "0000355433", trazas=[traza])])
    res = revalidar_destino_propio_respaldado_por_b1_sin_ocr(ruta_dataset=ruta)
    assert res["guias_actualizadas"] == []


def test_no_relaja_la_regla_si_confianza_es_baja(tmp_path):
    ruta = tmp_path / "guias.csv"
    traza = _traza_propia(confianza=0.4)
    _escribir(ruta, [_fila("472623", "0000355433", trazas=[traza])])
    res = revalidar_destino_propio_respaldado_por_b1_sin_ocr(ruta_dataset=ruta)
    assert res["guias_actualizadas"] == []


def test_no_relaja_la_regla_si_las_cuatro_fuentes_propias_divergen(tmp_path):
    """valor_propuesto distinto de identidad_operacional.direccion_entrega
    -- nunca "casi coinciden", exige coincidencia exacta."""
    ruta = tmp_path / "guias.csv"
    traza = _traza_propia()
    traza["hipotesis"]["valor_propuesto"] = "SAN LUIS 1201 RENCA"
    _escribir(ruta, [_fila("472623", "0000355433", trazas=[traza])])
    res = revalidar_destino_propio_respaldado_por_b1_sin_ocr(ruta_dataset=ruta)
    assert res["guias_actualizadas"] == []


def test_no_toca_una_fila_que_ya_tiene_despachar_a_crudo(tmp_path):
    ruta = tmp_path / "guias.csv"
    _escribir(ruta, [_fila("472623", "0000355433", trazas=[_traza_propia()], despachar=SAN_LUIS)])
    res = revalidar_destino_propio_respaldado_por_b1_sin_ocr(ruta_dataset=ruta)
    assert res["guias_actualizadas"] == []


# ============================================================
# 2. Documento hermano del mismo transporte/parada (472624)
# ============================================================


def test_hermano_del_mismo_transporte_reutiliza_el_mismo_texto(tmp_path):
    ruta = tmp_path / "guias.csv"
    _escribir(ruta, [
        _fila("472623", "0000355433", trazas=[_traza_propia()]),
        # 472624: sin traza propia de destino, mismo transporte/parada.
        _fila("472624", "0000355433", trazas=[]),
    ])
    res = revalidar_destino_propio_respaldado_por_b1_sin_ocr(ruta_dataset=ruta)
    assert set(res["guias_actualizadas"]) == {"472623", "472624"}
    f624 = _leer(ruta)["472624"]
    assert f624["despachar_a_crudo"] == SAN_LUIS
    assert _CONTAMINADO not in f624["motivos_revision_documento"]


def test_hermano_de_otro_transporte_no_se_toca(tmp_path):
    ruta = tmp_path / "guias.csv"
    _escribir(ruta, [
        _fila("472623", "0000355433", trazas=[_traza_propia()]),
        _fila("472477", "0000354870", trazas=[]),
    ])
    res = revalidar_destino_propio_respaldado_por_b1_sin_ocr(ruta_dataset=ruta)
    assert res["guias_actualizadas"] == ["472623"]
    assert _leer(ruta)["472477"]["despachar_a_crudo"] == ""
    assert _CONTAMINADO in _leer(ruta)["472477"]["motivos_revision_documento"]


# ============================================================
# 3. Idempotencia
# ============================================================


def test_idempotente(tmp_path):
    ruta = tmp_path / "guias.csv"
    _escribir(ruta, [
        _fila("472623", "0000355433", trazas=[_traza_propia()]),
        _fila("472624", "0000355433", trazas=[]),
    ])
    assert len(revalidar_destino_propio_respaldado_por_b1_sin_ocr(ruta_dataset=ruta)["guias_actualizadas"]) == 2
    assert revalidar_destino_propio_respaldado_por_b1_sin_ocr(ruta_dataset=ruta)["guias_actualizadas"] == []
