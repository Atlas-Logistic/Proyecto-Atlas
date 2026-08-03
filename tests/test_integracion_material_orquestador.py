import logging
from pathlib import Path
from unittest.mock import Mock

from atlas_core import procesamiento_masivo
from atlas_core.inteligencia.contrato_multicampo import EstadoResolucion
from atlas_core.inteligencia.resolucion_material import resolver_material_tipo_carga


MATERIALES = {"materiales": [{
    "material_id": "material-1",
    "descripcion_oficial": "B HORMIGON 16 MM 12 M",
    "familia_material": "ACERO",
    "tipo_carga": "BARRAS",
    "aliases": [],
    "abreviaciones": [],
    "estado_calidad": "CONFIRMADO",
    "estado_vigencia": "ACTIVO",
}]}


def _argumentos_material():
    return {
        "descripcion_material_ocr": "B HORMIGON 16 MM 12 M",
        "tipo_carga_ocr": "BARRAS",
        "catalogo_materiales": MATERIALES,
        "contexto": {"fuente": "prueba"},
    }


def test_composicion_material_conserva_el_resultado_directo():
    argumentos = _argumentos_material()
    directo = resolver_material_tipo_carga(**argumentos)

    agregado = procesamiento_masivo._orquestar_material_sombra(**argumentos)

    assert agregado.orden_ejecucion == ("material",)
    assert agregado.resultados["material"] == directo
    assert agregado.resumenes["material"].estado is EstadoResolucion.CONFIRMADO
    assert agregado.completo is True
    assert agregado.modo == "SOMBRA"


def test_fallo_del_resolver_material_queda_aislado(monkeypatch):
    def falla(**_kwargs):
        raise RuntimeError("detalle que no debe propagarse")

    monkeypatch.setattr(procesamiento_masivo, "resolver_material_tipo_carga", falla)

    agregado = procesamiento_masivo._orquestar_material_sombra(
        **_argumentos_material()
    )

    assert agregado.resultados == {}
    assert agregado.fallos["material"].tipo_error == "RuntimeError"
    assert "detalle que no debe propagarse" not in repr(agregado.fallos)
    assert agregado.completo is False
    assert agregado.requiere_revision is True


def test_flujo_principal_ejecuta_material_en_sombra_sin_publicarlo(
    tmp_path, monkeypatch, caplog
):
    datos = {
        "número de guía": "463309",
        "número de transporte": "0000123456",
        "cliente": "CLIENTE DEMO",
        "obra destino": "DESTINO DEMO",
        "chofer": "CHOFER DEMO",
    }
    monkeypatch.setattr(
        procesamiento_masivo,
        "leer_texto_imagen",
        Mock(return_value=["B HORMIGÓN 16 MM 12 M"]),
    )
    monkeypatch.setattr(
        procesamiento_masivo, "extraer_datos", Mock(return_value=datos)
    )

    def cargar(ruta):
        return MATERIALES if Path(ruta).name == "materiales.json" else {}

    monkeypatch.setattr(procesamiento_masivo, "cargar_catalogo_json", cargar)
    monkeypatch.setattr("atlas_core.catalogos.cargar_catalogo_json", cargar)

    with caplog.at_level(logging.INFO):
        salida = procesamiento_masivo.procesar_archivo(tmp_path / "guia.jpg")

    assert salida["descripcion_material"] == "B HORMIGÓN 16 MM 12 M"
    assert salida["tipo_carga"] == "BARRAS"
    assert "orquestador-material-sombra-v1 estado=CONFIRMADO" in caplog.text


def test_fallo_de_material_no_interrumpe_el_flujo_principal(
    tmp_path, monkeypatch, caplog
):
    datos = {
        "número de guía": "463309",
        "número de transporte": "0000123456",
        "cliente": "CLIENTE DEMO",
        "obra destino": "DESTINO DEMO",
        "chofer": "CHOFER DEMO",
    }
    monkeypatch.setattr(
        procesamiento_masivo,
        "leer_texto_imagen",
        Mock(return_value=["ROLLO HORMIGÓN 10 MM"]),
    )
    monkeypatch.setattr(
        procesamiento_masivo, "extraer_datos", Mock(return_value=datos)
    )
    monkeypatch.setattr(
        procesamiento_masivo, "cargar_catalogo_json", Mock(return_value={})
    )
    monkeypatch.setattr(
        "atlas_core.catalogos.cargar_catalogo_json", Mock(return_value={})
    )
    monkeypatch.setattr(
        procesamiento_masivo,
        "resolver_material_tipo_carga",
        Mock(side_effect=RuntimeError("fallo controlado")),
    )

    with caplog.at_level(logging.WARNING):
        salida = procesamiento_masivo.procesar_archivo(tmp_path / "guia.jpg")

    assert salida["descripcion_material"] == "ROLLO HORMIGÓN 10 MM"
    assert salida["tipo_carga"] == "ROLLOS"
    assert "orquestador-material-sombra-v1 fallo=RuntimeError" in caplog.text
