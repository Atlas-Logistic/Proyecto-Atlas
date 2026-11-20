from atlas_core.destino_operacional import TIPO, proyectar_destino
from atlas_core.gestor_viajes import agrupar_viajes
from atlas_core.territorio_chile import normalizar_comuna, ESTADO_COMUNA_NORMALIZADA_SEGURA
import pytest


def _filas(direccion="SAN LUIS 1201 OUILICURA", cliente="CLIENTE EJEMPLO SPA"):
    base = {"numero_transporte": "0000364898", "chofer": "Rodrigo Nahuelñir",
            "cliente": cliente, "obra_destino": "CLIENTE EJEMPLO SPA"}
    documental = {**base, "archivo": "482492.jpeg", "numero_guia": "482492",
                  "despachar_a_crudo": direccion}
    original = {**base, "archivo": "482493.jpeg", "numero_guia": "482493",
                "despachar_a_crudo": "SAN LUIS 1201 QUILICURA"}
    ledger = {"aplicaciones": [{"tipo": TIPO,
        "documento": {"archivo": original["archivo"], "numero_guia": "482493"},
        "destino_operacional": {"direccion": "SAN LUIS 1201", "comuna": "QUILICURA"},
        "ruta_operacional": {}}]}
    confirmado = proyectar_destino(original, ledger)
    confirmado["_evidencia_documental_original"] = dict(original)
    return documental, confirmado


def _entregas(*filas):
    viajes, _ = agrupar_viajes(list(filas))
    assert len(viajes) == 1
    return viajes[0].entregas


@pytest.mark.parametrize("comuna", ["OUILICURA", "QUTLICURA"])
def test_simulacion_guias_con_comuna_ocr_segura(comuna):
    assert normalizar_comuna(comuna).estado == ESTADO_COMUNA_NORMALIZADA_SEGURA
    filas = _filas(f"SAN LUIS 1201 {comuna}")
    entregas = _entregas(*filas)
    assert len(entregas) == 1
    assert entregas[0]["numeros_guia"] == ["482492", "482493"]
    assert filas[0]["despachar_a_crudo"] == f"SAN LUIS 1201 {comuna}"


@pytest.mark.parametrize("direccion", [
    "SAN LUIS 1201 RENCA", "SAN LUIS 1202 OUILICURA",
    "OTRA CALLE 1201 OUILICURA", "SAN LUIS 1201 ZYTAMPUR",
    "SAN LUIS 1201 LOCAL 4 OUILICURA", "SAN LUIS 1201 RENCA OUILICURA",
])
def test_destinos_distintos_o_sufijos_inseguros_no_se_unen(direccion):
    assert len(_entregas(*_filas(direccion))) == 2


def test_cliente_distinto_no_se_une():
    documental, confirmado = _filas()
    documental["cliente"] = "OTRO CLIENTE SPA"
    assert len(_entregas(documental, confirmado)) == 2


def test_normalizacion_ambigua_se_rechaza(monkeypatch):
    from atlas_core import entregas
    from atlas_core.territorio_chile import ResultadoNormalizacionComuna
    monkeypatch.setattr(entregas, "normalizar_comuna", lambda texto:
        ResultadoNormalizacionComuna("AMBIGUA", texto, "Quilicura"))
    assert len(_entregas(*_filas())) == 2


def test_numero_recortado_no_se_admite_con_comuna_normalizada():
    assert len(_entregas(*_filas("SAN LUIS 201 OUILICURA"))) == 2
