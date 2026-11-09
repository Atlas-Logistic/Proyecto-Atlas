"""Custodia por contenido y bloqueos de escritura, con la guarda real de empresa."""
from __future__ import annotations

import json

from tests.test_aislamiento_empresas import mundo  # noqa: F401
from tests.test_multiempresa_integracion import NORTE, _proceso

DETECTA = """
    from atlas_core import estado_confirmado as ec
    raiz = RAIZ
    rel = "catalogos_privados/igual.json"
    archivo = raiz / rel
    instante = 1_780_000_000_000_000_000
    def escribir(texto):
        archivo.write_text(texto, encoding="utf-8")
        os.utime(archivo, ns=(instante, instante))
    custodia = ec.CustodiaEstado(raiz, ec.ClienteEstado("https://x", "t", 1))
    escribir('{"v": "AAAA"}')
    antes, datos = custodia._huellas_locales([rel])[rel], os.stat(archivo)
    escribir('{"v": "BBBB"}')
    despues, nuevos = custodia._huellas_locales([rel])[rel], os.stat(archivo)
    assert (datos.st_size, datos.st_mtime_ns) == (nuevos.st_size, nuevos.st_mtime_ns)
    assert antes and despues and antes != despues
"""


def test_detecta_cambio_de_igual_tamano_y_fecha_en_otra_empresa(mundo):  # noqa: F811
    _proceso(mundo, NORTE, DETECTA.replace("RAIZ", "a") + """
    vetado(lambda: ec.sha256_archivo(b / "catalogos_privados" / "empresa_identidad.json"))
    vetado(lambda: ec.sha256_archivo(mbt / "catalogos_privados" / "choferes.json"))
    """)


def test_detecta_cambio_de_igual_tamano_y_fecha_en_mbt(mundo):  # noqa: F811
    _proceso(mundo, None, DETECTA.replace("RAIZ", "mbt"))


def test_escritor_de_fichas_respeta_el_bloqueo_de_su_empresa(mundo):  # noqa: F811
    _m, a, _b = mundo
    catalogo = {"123456785": {"nombre": "ANA", "rut": "12345678-5", "aliases": [], "activo": True}}
    (a.raiz / "catalogos_privados" / "choferes.json").write_text(json.dumps(catalogo), encoding="utf-8")
    _proceso(mundo, NORTE, """
    from atlas_core import fichas_choferes as fc
    with ap.bloqueo_sesion(a / "operacion" / "actual", "fichas_choferes_" + fc.EMPRESA_ACTUAL):
        try:
            fc.inicializar_almacen(a, empresa=fc.EMPRESA_ACTUAL, actor="PRUEBA")
        except Exception as error:
            assert "Bloqueo activo" in str(error), error
        else:
            raise SystemExit("NO BLOQUEADO")
    assert fc.inicializar_almacen(a, empresa=fc.EMPRESA_ACTUAL, actor="PRUEBA")
    """)
