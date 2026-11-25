"""Recuperación incremental en otra empresa: su estado local (marca de la
pasada PULL y respaldos del dataset) queda en la carpeta local de ESA empresa,
nunca en la de MBT. Antes, un proceso de otra empresa chocaba con la guarda
(ErrorAislamiento) y el PULL omitía la recuperación en silencio. Para MBT las
rutas siguen siendo exactamente las de siempre."""
from __future__ import annotations

import os
from pathlib import Path

from tests.test_multiempresa_integracion import NORTE, _proceso
from tests.test_aislamiento_empresas import mundo  # noqa: F401


def test_otra_empresa_usa_su_carpeta_local_y_la_pasada_pull_corre(mundo):  # noqa: F811
    _mbt, a, _b = mundo
    salida = _proceso(mundo, NORTE, """
        from atlas_core import recuperacion_incremental as ri
        propia = ae.base_local()
        assert propia == local / "Atlas" / "empresas" / "transportes-norte", propia
        for ruta in (ri._marca_pull_local(), ri._directorio_respaldo_local()):
            assert str(ruta).startswith(str(propia)), ruta
        # La pasada real del ciclo PULL: lee y escribe la marca sin ErrorAislamiento.
        resultado = ri.ejecutar_en_ciclo_pull(raiz_atlas=a, comprobar=lambda: None, fabrica_ocr=lambda: None)
        assert ri._marca_pull_local().is_file()
        # La carpeta local de MBT sigue vetada para esta empresa.
        vetado(lambda: (local / "Atlas" / "cache" / "recuperacion_incremental_ultima_pasada.json").read_text())
        print("OK", type(resultado).__name__)
    """)
    assert "OK dict" in salida
    assert not (Path(os.environ["LOCALAPPDATA"]) / "Atlas" / "cache" / "recuperacion_incremental_ultima_pasada.json").exists()


def test_mbt_conserva_las_rutas_de_siempre(mundo):  # noqa: F811
    _proceso(mundo, None, """
        import tempfile
        from atlas_core import recuperacion_incremental as ri
        base = Path(os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()) / "Atlas"
        assert ri._marca_pull_local() == base / "cache" / "recuperacion_incremental_ultima_pasada.json"
        assert ri._directorio_respaldo_local() == base / "respaldos" / "recuperacion_incremental"
    """)
