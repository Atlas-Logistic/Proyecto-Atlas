import json

from tests.test_b1_adicionales_operacion import raiz, operador, eventos  # noqa: F401
from atlas_core.registro_eventos_operacionales import registrar_evento


def test_mixto_ambiguedad_no_bloquea_y_confirmacion_se_revalida(raiz):
    registrar_evento(raiz=raiz, tipo_evento="OBSERVACION_OPERACIONAL", numero_transporte="0000365998",
                     nota="ADICIONAL DE 15 MIL POR GUIA", origen="TEST")
    b = operador(raiz)
    orden = "Agrega un adicional de $15.000 por carga a las guías 483082, 483043 y 999999"
    previo = json.dumps(eventos(raiz), sort_keys=True)
    r = b.atender("c", orden)
    assert r["estado"] == "PREVIEW_PENDIENTE"
    assert json.dumps(eventos(raiz), sort_keys=True) == previo
    assert b.atender("c", "si")["estado"] == "EJECUTADA"
    por = {e["numero_transporte"]: e["nota"] for e in eventos(raiz)}
    assert por["0000365998"] == "ADICIONAL DE 15 MIL POR GUIA"
    assert "POR CARGA" in por["0000366043"]


def test_todas_faltantes_se_informan(raiz):
    r = operador(raiz).atender("c", "Agrega un adicional de $15.000 a las guías 999998 y 999999")
    assert r["estado"] == "SIN_CAMBIOS"
    assert [f[0] for f in r["tablas"][0]["filas"]] == ["999998", "999999"]
    assert all("No existe" in f[2] for f in r["tablas"][0]["filas"])
