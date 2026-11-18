from datetime import datetime, timezone
from unittest.mock import Mock

import pytest

from atlas_core import procesamiento_masivo as pm
from atlas_core.perfiles_documentales import FormatoDocumentalDesconocido, PERFIL_AZA


def test_aza_reenvia_todo_el_contexto_y_resultado_sin_modificar(monkeypatch, tmp_path):
    resultado = {"numero_guia": "123456", "motivos_revision_documento": "MOTIVO", "evidencia": "original"}
    legado = Mock(return_value=resultado)
    monkeypatch.setattr(pm, "_procesar_archivo_aza", legado)
    reloj = lambda: datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert pm.procesar_archivo(tmp_path / "a.jpg", reloj=reloj) is resultado
    assert legado.call_args.kwargs["reloj"] is reloj
    assert pm.procesar_archivo(tmp_path / "a.jpg", perfil_documental=PERFIL_AZA) is resultado
    assert legado.call_count == 2


def test_perfil_alternativo_aislado_preserva_evidencia_y_contexto(monkeypatch, tmp_path):
    monkeypatch.setattr(pm, "_procesar_archivo_aza", Mock(side_effect=AssertionError("AZA invocado")))
    testigo = object()
    resultado = {"numero_guia": "EXT-1", "evidencia": "lectura literal", "motivos_revision_documento": "REVISAR"}
    class Alternativo:
        def procesar(self, **contexto):
            assert contexto["recolector_decisiones"] is testigo
            assert contexto["referencia_imagen_traza"] == "a.pdf::pagina=0001"
            return resultado
    assert pm.procesar_archivo(tmp_path / "a.jpg", recolector_decisiones=testigo,
        referencia_imagen_traza="a.pdf::pagina=0001", perfil_documental=Alternativo()) is resultado


@pytest.mark.parametrize("perfil", [None, "desconocido", object()])
def test_formato_desconocido_se_abstiene_antes_de_ocr_o_aza(monkeypatch, tmp_path, perfil):
    monkeypatch.setattr(pm, "_procesar_archivo_aza", Mock(side_effect=AssertionError("AZA invocado")))
    monkeypatch.setattr(pm, "leer_texto_imagen", Mock(side_effect=AssertionError("OCR invocado")))
    with pytest.raises(FormatoDocumentalDesconocido, match="requiere revisión"):
        pm.procesar_archivo(tmp_path / "a.jpg", perfil_documental=perfil)


def test_perfil_no_puede_devolver_salida_no_documental(tmp_path):
    class Malo:
        def procesar(self, **contexto):
            return None
    with pytest.raises(TypeError):
        pm.procesar_archivo(tmp_path / "a.jpg", perfil_documental=Malo())


def test_pipeline_aza_completo_igual_al_camino_heredado(monkeypatch, tmp_path):
    # OCR simulado: ejercita el extractor y las recuperaciones posteriores.
    textos = ["GUIA DE DESPACHO ELECTRONICA N 900001", "FECHA DE EMISION 11-08-2026",
              "TRANSPORTE 0000900001", "PESO KG", "1000"]
    monkeypatch.setattr(pm, "leer_texto_imagen", Mock(return_value=textos))
    monkeypatch.setattr(pm, "leer_bloques_imagen", Mock(return_value=[]))
    monkeypatch.setattr(pm.time, "perf_counter", lambda: 1.0)
    reloj = lambda: datetime(2026, 1, 1, tzinfo=timezone.utc)
    legado = pm._procesar_archivo_aza(tmp_path / "a.jpg", reloj=reloj)
    actual = pm.procesar_archivo(tmp_path / "a.jpg", reloj=reloj)
    assert actual == legado
    assert actual["peso_kg"] == "1000"
