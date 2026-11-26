"""Plantas configurables por empresa: Motor publica a Cloud las plantas de su
empresa y recibe de Mobile el `planta_id` elegido. Transportes Andes
ficticia frente a MBT, que conserva AZA_COLINA/AZA_RENCA sin publicar nada.
Catálogos sintéticos; nada toca Cloud real."""
from __future__ import annotations

from pathlib import Path

import pytest

from atlas_core import cloud_plantas_mobile as modulo
from atlas_core.catalogo_plantas import CatalogoPlantas
from atlas_core.cloud_mobile_sync_cliente import ErrorSincronizacionCloudMobile
from atlas_core.mobile import ErrorEnvioMobile, RepositorioEnviosMobile, validar_planta_origen_mobile

NORTE, LAMPA, PENDIENTE, BAJA = (f"a1b2c3d4-0000-4000-8000-00000000000{i}" for i in range(1, 5))


def _andes(tmp_path: Path) -> Path:
    raiz = tmp_path / "Atlas_empresas" / "transportes-andes"
    ids = iter([NORTE, LAMPA, PENDIENTE, BAJA])
    catalogo = CatalogoPlantas(raiz / "catalogos_privados" / "plantas.json", generador_id=lambda: next(ids))
    catalogo.crear(nombre="Puerto Norte", pais="Chile", fuente="prueba", estado_calidad="CONFIRMADA")
    catalogo.crear(nombre="Bodega Lampa", pais="Chile", fuente="prueba", estado_calidad="CONFIRMADA")
    catalogo.crear(nombre="Patio en evaluación", pais="Chile", fuente="prueba")  # PENDIENTE
    catalogo.crear(nombre="Antigua Quilicura", pais="Chile", fuente="prueba", estado_calidad="CONFIRMADA")
    catalogo.desactivar(BAJA, modificacion_manual=True)
    return raiz


def _mbt(tmp_path: Path) -> Path:
    raiz = tmp_path / "mbt"
    catalogo = CatalogoPlantas(raiz / "catalogos_privados" / "plantas.json", generador_id=lambda: "mbt-colina-id")
    catalogo.crear(nombre="AZA COLINA", pais="Chile", fuente="prueba", estado_calidad="CONFIRMADA")
    return raiz


# ---- Recepción (receptor Motor) ----

def test_mbt_conserva_codigos_legados_y_no_acepta_plantas_de_andes(tmp_path):
    raiz = _mbt(tmp_path)
    for codigo in ("AZA_COLINA", "AZA_RENCA"):
        assert validar_planta_origen_mobile(codigo, raiz_atlas=raiz) == codigo
    with pytest.raises(ErrorEnvioMobile):
        validar_planta_origen_mobile(NORTE, raiz_atlas=raiz)


def test_andes_acepta_solo_plantas_confirmadas_de_su_catalogo(tmp_path):
    raiz = _andes(tmp_path)
    assert validar_planta_origen_mobile(NORTE, raiz_atlas=raiz) == NORTE
    # Desactivada después de capturar (cola offline): se recibe igual.
    assert validar_planta_origen_mobile(BAJA, raiz_atlas=raiz) == BAJA
    for invalido in (PENDIENTE, "AZA_COLINA", "AZA_RENCA", "mbt-colina-id", ""):
        with pytest.raises(ErrorEnvioMobile):
            validar_planta_origen_mobile(invalido, raiz_atlas=raiz)


def test_recepcion_completa_de_andes_persiste_su_planta(tmp_path):
    raiz = _andes(tmp_path)
    registro, nuevo = RepositorioEnviosMobile(raiz).recibir(
        envio_id="guia-andes-000001", imagen=b"foto", mime="image/jpeg",
        metadata={"chofer_id": "chofer-1", "tipo_novedad": "", "planta_origen_informada": LAMPA},
    )
    assert nuevo is True and registro["planta_origen_informada"] == LAMPA
    with pytest.raises(ErrorEnvioMobile):
        RepositorioEnviosMobile(raiz).recibir(
            envio_id="guia-andes-000002", imagen=b"foto", mime="image/jpeg",
            metadata={"chofer_id": "chofer-1", "tipo_novedad": "", "planta_origen_informada": "AZA_COLINA"},
        )


# ---- Publicación Motor -> Cloud ----

def test_publicables_solo_confirmadas_y_activas_por_nombre(tmp_path):
    assert modulo.plantas_publicables(_andes(tmp_path)) == [
        {"planta_id": LAMPA, "nombre": "Bodega Lampa"}, {"planta_id": NORTE, "nombre": "Puerto Norte"},
    ]


def test_publica_lista_completa_bajo_lease(tmp_path, monkeypatch):
    llamadas = []
    monkeypatch.setattr(modulo, "_json", lambda base, ruta, token, **kw: llamadas.append((ruta, kw)) or {"plantas": 2, "cambios": 2})
    raiz = _andes(tmp_path)
    r = modulo.publicar_plantas_cloud(base_url="https://cloud.local", token_motor="t", raiz=raiz, timeout=5, puede_continuar=lambda: True)
    assert r == {"publicadas": 2, "cambios": 2}
    assert llamadas == [("/api/motor/plantas", {"method": "POST", "timeout": 5, "body": {"plantas": [
        {"planta_id": LAMPA, "nombre": "Bodega Lampa"}, {"planta_id": NORTE, "nombre": "Puerto Norte"}]}})]
    llamadas.clear()
    r = modulo.publicar_plantas_cloud(base_url="https://cloud.local", token_motor="t", raiz=raiz, timeout=5, puede_continuar=lambda: False)
    assert r["detenido_por_escritor"] is True and llamadas == []


def test_mbt_nunca_publica(tmp_path, monkeypatch):
    llamadas = []
    monkeypatch.setattr(modulo, "_json", lambda *a, **kw: llamadas.append(a) or {})
    r = modulo.publicar_plantas_cloud(base_url="https://cloud.local", token_motor="t", raiz=_mbt(tmp_path), timeout=5, puede_continuar=lambda: True)
    assert r["publicadas"] is None and "omitido" in r and llamadas == []


@pytest.mark.parametrize("dano", ["ausente", "roto", "nombre_largo"])
def test_catalogo_no_publicable_no_envia_nada(tmp_path, monkeypatch, dano):
    llamadas = []
    monkeypatch.setattr(modulo, "_json", lambda *a, **kw: llamadas.append(a) or {})
    raiz = _andes(tmp_path)
    ruta = raiz / "catalogos_privados" / "plantas.json"
    if dano == "ausente":
        ruta.unlink()
    elif dano == "roto":
        ruta.write_text("{roto", encoding="utf-8")
    else:
        CatalogoPlantas(ruta, generador_id=lambda: "larga").crear(nombre="X" * 90, pais="Chile", fuente="prueba", estado_calidad="CONFIRMADA")
    r = modulo.publicar_plantas_cloud(base_url="https://cloud.local", token_motor="t", raiz=raiz, timeout=5, puede_continuar=lambda: True)
    assert r["publicadas"] is None and r["error"] and llamadas == []


def test_cloud_anterior_sin_ruta_no_corta(tmp_path, monkeypatch):
    def falla(*a, **kw):
        raise ErrorSincronizacionCloudMobile("Cloud Motor POST /api/motor/plantas: HTTP Error 404")
    monkeypatch.setattr(modulo, "_json", falla)
    r = modulo.publicar_plantas_cloud(base_url="https://cloud.local", token_motor="t", raiz=_andes(tmp_path), timeout=5, puede_continuar=lambda: True)
    assert r["publicadas"] is None and "404" in r["error"]
