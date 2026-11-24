"""Destinos confirmados reconocidos pese a numeraciones con varias letras OCR (casos reales 492111, 484655,
482101 y 484007), sin tarjetas DESTINO_SIN_CONFIRMAR redundantes. Misma regla de siempre: la numeración
OCR sólo equivale al número EXACTO de la calle confirmada y con la comuna confirmada en el texto."""
from __future__ import annotations

from types import SimpleNamespace as NS

import pytest

from atlas_core import decisiones_pendientes as dp
from atlas_core.catalogo_destinos import direccion_confirmada_coincide


@pytest.mark.parametrize("calle,texto,comuna", [
    ("VISTA CLARA 2351", "VISTA CLARA 23SI CERRILLOS", "CERRILLOS"),       # 492111: S->5 dentro, I->1 al final
    ("SANTA ISABEL 585", "SANTA ISABEL 58S SANTIAGO LAMPA", "LAMPA"),      # 484655/482101: S->5 al final
    ("CAMINO LO RUIZ 2901", "CAMINO LO RUIZ 29Q1 SANTIAGO RENCA", "RENCA"),  # 484007: Q->0
    ("CAMINO LO RUIZ 2901", "CAMINO LO RUIZ 290I SANTIAGO RENCA", "RENCA"),  # 482771: regla previa intacta
])
def test_numeracion_ocr_equivale_al_numero_confirmado(calle, texto, comuna):
    assert direccion_confirmada_coincide(calle, texto, comuna_confirmada=comuna)


@pytest.mark.parametrize("calle,texto,comuna", [
    ("VISTA CLARA 2351", "VISTA CLARA 23SI CERRILLOS", ""),               # sin comuna que la respalde
    ("VISTA CLARA 2351", "VISTA CLARA 23SI MAIPU", "CERRILLOS"),          # otra comuna
    ("SANTA ISABEL 585", "SANTA ISABEL 58S SANTIAGO COLINA", "LAMPA"),
    ("VISTA CLARA 2351", "VISTA CLARA 2SSI CERRILLOS", "CERRILLOS"),      # no equivale exactamente
    ("CAMINO LO RUIZ 2901", "CAMINO LO RUIZ 29Q2 SANTIAGO RENCA", "RENCA"),
    ("SANTA ISABEL 128", "SANTA ISABEL 12B LAMPA", "LAMPA"),              # B final es numeración real
    ("SANTA ISABEL 585", "SANTA ISABEL SBS SANTIAGO LAMPA", "LAMPA"),     # sin ningún dígito
    ("SANTA ISABEL 585", "SANTA ISABEL 586 LAMPA", "LAMPA"),              # otro número real
    ("PDTE. RIESCO 5903", "PDTE. RIESCO 6903", "LAS CONDES"),             # 464653
])
def test_numeraciones_no_equivalentes_nunca_coinciden(calle, texto, comuna):
    if comuna:
        assert not direccion_confirmada_coincide(calle, texto, comuna_confirmada=comuna)
    else:
        assert not direccion_confirmada_coincide(calle, texto)


@pytest.fixture
def catalogo(monkeypatch):
    obra = NS(obra_id="obra-1", cliente_id="cliente-1", nombre_canonico="TORRES OCARANZA LTDA",
              aliases_documentales=(), estado="CONFIRMADA", estado_vigencia="ACTIVO")
    destinos = [NS(destino_id="d-1", direccion="VISTA CLARA 2351, CERRILLOS, REGION METROPOLITANA, CHILE", comuna="CERRILLOS")]
    monkeypatch.setattr(dp, "CatalogoObrasDestinos", lambda *a, **k: NS(
        listar_obras=lambda: [obra], resolver_obra_destino_confirmada=lambda **k: None,
        listar_destinos_confirmados_para_obra=lambda **k: destinos))
    return destinos


def _tarjetas(destino_documental):
    return dp._decisiones_obra_para_cliente(
        carpeta=__import__("pathlib").Path("catalogos"), cliente_id="cliente-1", cliente_razon_social="TORRES OCARANZA LTDA",
        cliente_aliases=(), obra_texto="TORRES OCARANZA LTDA", despachar_a_documental=destino_documental,
        comunes={"archivo": "g.jpg", "numero_guia": "492111", "numero_transporte": "No encontrado"})


@pytest.mark.parametrize("texto", ["VISTA CLARA 23SI CERRILLOS", "VISTA CLARA 2351 CERRILLOS"])
def test_destino_confirmado_de_la_obra_no_genera_tarjeta(catalogo, texto):
    assert _tarjetas(texto) == []


@pytest.mark.parametrize("texto", ["VISTA CLARA 23SI MAIPU", "VISTA CLARA 2SSI CERRILLOS", "VISTA CLARA 2551 CERRILLOS"])
def test_destino_no_inequivoco_sigue_preguntando(catalogo, texto):
    (tarjeta,) = _tarjetas(texto)
    assert tarjeta["tipo"] == "DESTINO_SIN_CONFIRMAR" and tarjeta["valor_documental"] == texto
