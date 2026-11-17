"""Reconciliación focal sin el paso compartido de coordenadas del catálogo.

Caso real 484907: la reconciliación limitada a una guía también ejecutaba
`revalidar_destinos_confirmados_sin_coordenadas_sin_ocr`, que recorre TODO
el catálogo y completaba coordenadas de destinos ajenos. El parámetro
opt-in `omitir_coordenadas_catalogo` lo omite; por defecto nada cambia.
"""
from __future__ import annotations

import csv
import json

import pytest

import atlas_core.reconciliacion_estado_derivado as R
from atlas_core.catalogo_destinos import CatalogoDestinos
from atlas_core.procesamiento_masivo import COLUMNAS
from tests.test_reconciliacion_global_r13 import _catalogos_base, _fila, _proveedor_direccion_ambigua


def _raiz(tmp_path):
    raiz = tmp_path / "Atlas"
    catalogos = raiz / "catalogos_privados"; actual = raiz / "operacion" / "actual"
    (raiz / "reportes").mkdir(parents=True); catalogos.mkdir(parents=True); actual.mkdir(parents=True)
    _catalogos_base(catalogos)
    CatalogoDestinos(catalogos / "destinos_maestros.json", ruta_clientes=catalogos / "clientes.json").crear(
        cliente_id="", nombre_destino="CALLE AJENA 100", pais="CHILE", fuente="TEST",
        direccion="CALLE AJENA 100", comuna="LA CISTERNA", estado_calidad="CONFIRMADO",
    )
    with (actual / "analisis_completo_guias.csv").open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader(); escritor.writerow(_fila(archivo="1.jpeg", numero_guia="1"))
    return raiz


@pytest.mark.parametrize("omitir,esperado", [(True, 0), (False, 1)])
def test_paso_de_coordenadas_se_omite_solo_si_se_pide(tmp_path, monkeypatch, omitir, esperado):
    raiz = _raiz(tmp_path)
    llamadas = []
    original = R.revalidar_destinos_confirmados_sin_coordenadas_sin_ocr

    def espia(**kwargs):
        llamadas.append(kwargs)
        return original(**kwargs)

    monkeypatch.setattr(R, "revalidar_destinos_confirmados_sin_coordenadas_sin_ocr", espia)
    kwargs = {"omitir_coordenadas_catalogo": True} if omitir else {}
    resultado = R.reconciliar_estado_derivado(
        raiz_atlas=raiz, guias_objetivo={"1"},
        proveedor_rutas=_proveedor_direccion_ambigua("x"), **kwargs,
    )
    assert resultado["reconciliado"] is True
    assert len(llamadas) == esperado


def test_omitir_deja_el_catalogo_identico(tmp_path):
    raiz = _raiz(tmp_path)
    catalogo = raiz / "catalogos_privados" / "destinos_maestros.json"
    antes = catalogo.read_bytes()
    R.reconciliar_estado_derivado(
        raiz_atlas=raiz, guias_objetivo={"1"},
        proveedor_rutas=_proveedor_direccion_ambigua("x"), omitir_coordenadas_catalogo=True,
    )
    assert catalogo.read_bytes() == antes
    assert json.loads(antes)["destinos"][0]["latitud"] is None
