"""Regresiones P0: el OCR de Mobile pertenece al trabajador, no a la guía."""
from __future__ import annotations

from pathlib import Path

from atlas_core import cloud_mobile_sync_cliente as cloud
from atlas_core import mobile


class _Proveedor:
    pass


def test_punto_de_entrada_mobile_reutiliza_el_proveedor_inyectado(monkeypatch, tmp_path: Path):
    proveedor = _Proveedor()
    recibidos = []

    def procesar(_repositorio, envio_id, **kwargs):
        recibidos.append((envio_id, kwargs["proveedor_ocr"]))
        return {"estado": "ASOCIADO"}

    monkeypatch.setattr(mobile, "procesar_envio_mobile", procesar)
    monkeypatch.setattr(mobile, "_revalidar_asociacion_diagnosticable", lambda *_a, **_k: None)
    monkeypatch.setattr(mobile, "_regenerar_reporte_tras_envio_mobile", lambda *_a, **_k: True)
    monkeypatch.setattr(mobile, "_converger_envios_tras_reporte", lambda *_a, **_k: True)
    monkeypatch.setattr(mobile, "_sincronizar_contrato_v2", lambda *_a, **_k: None)

    class Repo:
        def cargar(self, _envio_id):
            return {"estado": "RECIBIDO"}

    repo = Repo()
    salida_1 = mobile.procesar_y_revalidar_envio_mobile(repo, "uno", dataset=tmp_path / "datos.csv", carpeta_catalogos=None, proveedor_ocr=proveedor)
    salida_2 = mobile.procesar_y_revalidar_envio_mobile(repo, "dos", dataset=tmp_path / "datos.csv", carpeta_catalogos=None, proveedor_ocr=proveedor)

    assert salida_1 == salida_2 == {"procesamiento_ok": True, "reconciliacion_ok": True}
    assert recibidos == [("uno", proveedor), ("dos", proveedor)]


def test_barrido_cloud_pasa_la_misma_instancia_a_envios_consecutivos(monkeypatch):
    proveedor = _Proveedor()
    usados = []

    class Repo:
        def historial(self):
            return [{"envio_id": "uno", "estado": "RECIBIDO"}, {"envio_id": "dos", "estado": "PROCESANDO"}]

    def procesar(_repo, envio_id, **kwargs):
        usados.append((envio_id, kwargs["proveedor_ocr"]))
        return {"completado": True}

    monkeypatch.setattr(cloud, "_procesar_envio_cloud", procesar)

    resultado = cloud.procesar_envios_recibidos(Repo(), dataset=None, carpeta_catalogos=None, proveedor_ocr=proveedor)

    assert resultado["procesados"] == ["uno", "dos"]
    assert usados == [("uno", proveedor), ("dos", proveedor)]
