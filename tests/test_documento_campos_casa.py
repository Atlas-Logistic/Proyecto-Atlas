"""Aceptacion CASA: correcciones nuevas sobre datos sinteticos aislados."""
import csv

import pytest

from test_acciones_operacionales import entorno, _bandeja
from test_bandeja_alcance_focal_p0 import preparar
from atlas_core.acciones_operacionales import CapaAccionesOperacionales
from atlas_core.decisiones_pendientes import generar_artefacto
from atlas_core.reprocesamiento_reparador import (
    CAMPOS_DOCUMENTALES_CONTROLADOS,
    reparar_documento_focal_con_valores_conocidos,
)


@pytest.mark.parametrize("existentes", [False, True])
@pytest.mark.parametrize("campo,valor", [
    ("fecha", "22-10-2026"),
    ("peso_kg", "28500"),
    ("hora_entrada_aza", "07:45"),
    ("hora_salida_aza", "08:35"),
    ("descripcion_material", "GRAVA 3/4"),
])
def test_campos_nuevos_preservan_otras_guias_y_protegen_valor(entorno, existentes, campo, valor):
    latentes = preparar(entorno)
    generar_artefacto(ruta_dataset=entorno["dataset"], carpeta_catalogos=entorno["cat"],
                      decisiones=latentes if existentes else [])
    antes = list(csv.DictReader(entorno["dataset"].open(encoding="utf-8-sig"), delimiter=";"))
    tarjetas = _bandeja(entorno)["decisiones"]
    catalogos = {p.name: p.read_bytes() for p in entorno["cat"].glob("*.json")}
    capa = CapaAccionesOperacionales(entorno["raiz"])
    preview = capa.previsualizar("DOCUMENTO_CORREGIR_CAMPO", {
        "numero_guia": "482673", "campo": campo, "valor": valor,
    }, actor="TEST")
    assert preview["estado"] == "PREVIEW", preview
    assert capa.ejecutar(preview["token"], actor="TEST")["codigo"] == "CONFIRMACION_REQUERIDA"
    assert list(csv.DictReader(entorno["dataset"].open(encoding="utf-8-sig"), delimiter=";")) == antes
    resultado = capa.ejecutar(preview["token"], actor="TEST", confirmado_por="TEST")
    assert resultado["estado"] == "APLICADA", resultado
    despues = list(csv.DictReader(entorno["dataset"].open(encoding="utf-8-sig"), delimiter=";"))
    assert despues[1:] == antes[1:]
    assert despues[0][campo] == valor
    assert _bandeja(entorno)["decisiones"] == tarjetas
    assert {p.name: p.read_bytes() for p in entorno["cat"].glob("*.json")} == catalogos
    assert (entorno["raiz"] / resultado["respaldo"]).is_dir()
    assert capa.auditoria()[-1]["resultado"] == "APLICADA"
    assert resultado["revalidacion"]["guias"] is not None
    assert resultado["revalidacion"]["reporte"] is not None
    intento = reparar_documento_focal_con_valores_conocidos(
        raiz_atlas=entorno["raiz"], archivo="482673.jpeg", valores={campo: valor},
        dry_run=True, numero_guia="482673",
        campos_adicionales_permitidos=frozenset(CAMPOS_DOCUMENTALES_CONTROLADOS),
    )
    assert intento["campos_bloqueados_por_ledger"] == [campo]
