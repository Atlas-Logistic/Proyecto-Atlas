"""Reintento de ruta sin evidencia nueva conserva la resolución territorial.

Caso real 482995 (envío Mobile ae70a62b): la homologación automática de su
rampla (JF9557 -> JF9575) revalida la guía; sin credencial de geocodificación
el reintento de ruta falla con GEOCODIFICACION_SIN_CREDENCIAL y vaciaba
GALVARINO 8501 QUILICURA, comuna, región y códigos territoriales ya resueltos.
Un rechazo basado en evidencia sigue reemplazándolos (suites de rutas existentes).
"""
from __future__ import annotations

from atlas_core.revalidacion_documental import revalidar_ruta_sin_destino_calculado_sin_ocr
from atlas_core.rutas.modelos import EstadoRuta, ResultadoGeocodificacion
from atlas_core.rutas.proveedor import ProveedorRutasSimulado
from tests.test_ciclo_pendientes_tecnicos_simulado import Operacion, _escribir_csv, _fila, _leer_csv

TERRITORIO = {
    "direccion_entrega": "GALVARINO 8501 QUILICURA", "localidad_entrega": "Quilicura",
    "region_entrega": "Metropolitana", "codigo_pais": "CL", "codigo_unidad": "13125", "codigo_contexto": "13",
}


class _SinCredencial(ProveedorRutasSimulado):
    def geocodificar(self, direccion):
        self.llamadas_geocodificacion += 1
        return ResultadoGeocodificacion(EstadoRuta.SIN_CREDENCIAL, (), "SIN_CREDENCIAL")


def _revalidar(tmp_path, proveedor, **extra):
    op = Operacion(tmp_path)
    fila = _fila("482995", "SIN_CREDENCIAL", op.planta_id, despachar_a_crudo="GALVARINO 8501 QUILICURA",
                 estado_ruta="SIN_CREDENCIAL", estado_entrega="RESUELTO", **{**TERRITORIO, **extra})
    _escribir_csv(op.dataset, [fila, _fila("500002", "", op.planta_id)])
    resultado = revalidar_ruta_sin_destino_calculado_sin_ocr(
        ruta_dataset=op.dataset, carpeta_catalogos=op.catalogos, proveedor_rutas=proveedor,
        proveedor_rutas_fallback=proveedor, guias_objetivo={"482995"},
    )
    return resultado, _leer_csv(op.dataset)


def test_482995_reintento_sin_credencial_conserva_direccion_y_codigos(tmp_path):
    proveedor = _SinCredencial()
    _, filas = _revalidar(tmp_path, proveedor)
    fila = filas["482995"]
    assert proveedor.llamadas_geocodificacion >= 1  # el reintento sí ocurrió
    assert {c: fila[c] for c in TERRITORIO} == TERRITORIO
    assert fila["motivo_ruta"].endswith("SIN_CREDENCIAL")  # la etiqueta dice la verdad vigente


def test_482995_no_toca_otras_guias(tmp_path):
    _, filas = _revalidar(tmp_path, _SinCredencial())
    assert filas["500002"]["direccion_entrega"] == ""
    assert filas["500002"]["motivo_ruta"] == ""

