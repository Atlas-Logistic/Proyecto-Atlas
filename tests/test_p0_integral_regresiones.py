"""P0.6: regresiones del P0 encontradas en la validación integral.

R1. Con la raíz de trabajo local (P0.3.1) en C:, ``compartida`` la trataba
    como privada: las escrituras de Desktop iban sin lease ni custodia. Y
    Desktop, que muestra la raíz publicada, la entrega al Motor: el Motor
    debe operar sobre la de trabajo.
R2. La raíz publicada real (G:) está protegida por la guardia del turno
    local: publicar sin poseer su turno fallaba siempre.
R3. La salud de una versión de Desktop debe arrancar Electron de verdad.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from atlas_core import desktop_operacion as do
from atlas_core import estado_confirmado as ec
from atlas_core import exclusion_local as el
from atlas_core import raiz_publicada as rp
from tests.test_raiz_trabajo_aislada import DATASET, EquipoAislado, drive_sincroniza
from tests.test_estado_confirmado import CloudFalsa


class RaizPublicadaEnProcesos(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        self.trabajo, self.publicada = base / "Local" / "Atlas", base / "Drive" / "Atlas"
        self.trabajo.mkdir(parents=True)
        self.publicada.mkdir(parents=True)
        self.cfg = base / "raiz_publicada.json"
        self.cfg.write_text(json.dumps({"raiz_trabajo": str(self.trabajo), "raiz_publicada": str(self.publicada)}),
                            encoding="utf-8")
        self._p = patch.object(rp, "ruta_configuracion", return_value=self.cfg)
        self._p.start()

    def tearDown(self):
        self._p.stop()
        self._tmp.cleanup()

    def test_proceso_que_recibe_la_publicada_opera_en_la_de_trabajo(self):
        argv = ["b1_operador_cli.py", "--raiz-atlas", str(self.publicada), "--texto", "x",
                f"--otra={self.publicada}", str(self.publicada / "sub")]
        with patch.object(sys, "argv", list(argv)), patch.dict(os.environ, {"ATLAS_DATA_DIR": str(self.publicada)}):
            self.assertTrue(rp.redirigir_proceso())
            self.assertEqual(sys.argv[2], str(self.trabajo))
            self.assertEqual(sys.argv[5], f"--otra={self.trabajo}")
            self.assertEqual(sys.argv[6], str(self.publicada / "sub"))  # sólo la raíz exacta
            self.assertEqual(os.environ["ATLAS_DATA_DIR"], str(self.trabajo))
        self.assertEqual(rp.operativa(self.publicada), self.trabajo)
        self.assertEqual(rp.operativa(str(self.publicada)), str(self.trabajo))
        self.assertEqual(rp.operativa(Path("C:/otra")), Path("C:/otra"))

    def test_variables_del_lanzador_del_pull_tambien_se_redirigen(self):
        # pull_pc_nuevo.ps1 exporta ATLAS_DATA_DIR y ATLAS_CATALOGOS_DIR sobre la raíz configurada (Drive).
        (self.trabajo / "catalogos_privados").mkdir()
        entorno = {"ATLAS_DATA_DIR": str(self.publicada), "ATLAS_CATALOGOS_DIR": str(self.publicada / "catalogos_privados"),
                   "ATLAS_EXCLUSION_RAICES": str(self.publicada), "ATLAS_OTRA": r"C:\otra\ruta", "OTRA_VARIABLE": str(self.publicada)}
        with patch.object(sys, "argv", ["sincronizar_mobile_cloud.py"]), patch.dict(os.environ, entorno):
            self.assertTrue(rp.redirigir_proceso())
            self.assertEqual(os.environ["ATLAS_DATA_DIR"], str(self.trabajo))
            self.assertEqual(Path(os.environ["ATLAS_CATALOGOS_DIR"]), self.trabajo / "catalogos_privados")
            self.assertEqual(os.environ["ATLAS_EXCLUSION_RAICES"], str(self.publicada))  # la guardia sigue en Drive
            self.assertEqual(os.environ["ATLAS_OTRA"], r"C:\otra\ruta")
            self.assertEqual(os.environ["OTRA_VARIABLE"], str(self.publicada))
            from atlas_core.fuente_catalogos import resolver_fuente_catalogos
            self.assertEqual(Path(resolver_fuente_catalogos(None)).resolve(),
                             (self.trabajo / "catalogos_privados").resolve())

    def test_valores_relativos_no_se_resuelven_contra_la_carpeta_actual(self):
        # Defecto real (CASA, 27/11): con la carpeta actual dentro de G:, el token
        # ATLAS_CLOUD_MOTOR_TOKEN "parecía" una ruta bajo la raíz publicada.
        anterior = os.getcwd()
        os.chdir(self.publicada)
        try:
            entorno = {"ATLAS_CLOUD_MOTOR_TOKEN": "token-sin-barras", "ATLAS_OTRO": "operacion"}
            with patch.object(sys, "argv", ["x", ".", "operacion", "--texto=."]), patch.dict(os.environ, entorno):
                self.assertFalse(rp.redirigir_proceso())
                self.assertEqual(os.environ["ATLAS_CLOUD_MOTOR_TOKEN"], "token-sin-barras")
                self.assertEqual(os.environ["ATLAS_OTRO"], "operacion")
                self.assertEqual(sys.argv, ["x", ".", "operacion", "--texto=."])
        finally:
            os.chdir(anterior)

    def test_sin_configuracion_nada_cambia(self):
        self.cfg.unlink()
        with patch.object(sys, "argv", ["x", str(self.publicada)]):
            self.assertFalse(rp.redirigir_proceso())
        self.assertFalse(do.compartida(self.trabajo))

    def test_la_raiz_de_trabajo_se_escribe_con_lease_y_turno(self):
        self.assertTrue(do.compartida(self.trabajo))
        self.assertTrue(el.compartida(self.trabajo))
        self.assertFalse(do.compartida(Path(self._tmp.name) / "otra"))

    def test_desktop_operacion_recibe_la_publicada_y_responde_con_ella(self):
        visto = {}

        def ejecutar(solicitud):
            visto.update(solicitud)
            return {"ok": True, "carpetaReportes": str(self.trabajo / "reportes" / "r1")}

        with patch.object(do, "_ejecutar", side_effect=ejecutar):
            r = do.ejecutar({"raiz": str(self.publicada), "accion": "script",
                             "argumentos": ["b1_operador_cli.py", "--raiz-atlas", str(self.publicada)]})
        self.assertEqual(Path(visto["raiz"]), self.trabajo.resolve())
        self.assertEqual(visto["argumentos"][2], str(self.trabajo))
        self.assertEqual(Path(r["carpetaReportes"]), self.publicada.resolve() / "reportes" / "r1")


class PublicacionEnRaizProtegida(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.cloud = CloudFalsa()
        self.casa = EquipoAislado(Path(self._tmp.name), "casa", self.cloud)
        self._parches = [patch("atlas_core.escritor_operativo._json", side_effect=self.cloud.json),
                         patch.object(ec.ClienteEstado, "_crudo", lambda c, h, **kw: self.cloud.crudo(c, h, **kw)),
                         # Como G: en producción: la guardia exige turno en la raíz publicada.
                         patch.dict(os.environ, {"ATLAS_EXCLUSION_RAICES": str(self.casa.publicada),
                                                 "ATLAS_EXCLUSION_LOCAL": "exigir"})]
        for p in self._parches:
            p.start()

    def tearDown(self):
        for p in self._parches:
            p.stop()
        ec._activas.clear()
        self._tmp.cleanup()

    def test_la_publicacion_toma_el_turno_de_la_raiz_publicada(self):
        with self.assertRaises(el.EscrituraSinTurno):
            (self.casa.publicada / "intruso.txt").write_text("x", encoding="utf-8")  # sin turno: vetado
        with self.casa.lease() as lease:
            self.assertTrue(lease.adquirir(), lease.motivo)
            self.casa.escribir(DATASET, "archivo;g\ng1;1\n")
        self.assertEqual(self.casa.publicado(DATASET), "archivo;g\ng1;1\n")
        self.assertFalse((self.casa.local / "publicacion_pendiente.json").exists())


class ArranqueRealDeDesktop(unittest.TestCase):
    def test_ejecutable_que_no_abre_ventana_falla_la_salud(self):
        from atlas_core.actualizacion_atlas import Actualizador, ErrorActualizacion
        a = Actualizador(motor=Path("."), recursos=None, estado=Path(tempfile.gettempdir()), cliente=None,
                         desktop_exe=Path(sys.executable), espera_arranque=20)
        with self.assertRaises(ErrorActualizacion):  # python rechaza --remote-debugging-port y termina
            a._arranque_desktop()


if __name__ == "__main__":
    unittest.main()
