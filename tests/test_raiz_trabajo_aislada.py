"""P0.3.1: las escrituras de un turno quedan en la raíz de trabajo local
(fuera de Drive); la raíz publicada (Drive) recibe sólo lo que Cloud
confirmó. Así un turno interrumpido nunca llega a otro escritor ni lo
bloquea. Cloud simulada con la semántica del Worker.
"""
from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from atlas_core import estado_confirmado as ec
from atlas_core import escritor_operativo as eo
from tests.test_estado_confirmado import CATALOGO, CloudFalsa, Equipo, sha

DATASET = ec.RUTA_DATASET
REPORTE = "reportes/20261127T120000/viajes.csv"


def huella(texto: str) -> str:
    return sha(texto.replace("\n", os.linesep).encode())


def drive_sincroniza(origen: Path, destino: Path) -> None:
    """Google Drive replica la raíz publicada entre equipos (otro proceso)."""
    shutil.copytree(origen, destino, dirs_exist_ok=True)


class EquipoAislado(Equipo):
    """Raíz de trabajo local (``raiz``) + su copia de la raíz publicada."""

    def __init__(self, base: Path, nombre: str, cloud: CloudFalsa):
        super().__init__(base, nombre, cloud)
        self.publicada = base / nombre / "Drive" / "Atlas"
        self.publicada.mkdir(parents=True)
        self.config = {"raiz_trabajo": str(self.raiz), "raiz_publicada": str(self.publicada)}

    def lease(self, *, protocolo2: bool = True, raiz: Path | None = None) -> eo.LeaseEscritorOperativo:
        lease = eo.LeaseEscritorOperativo(base_url="https://cloud.test", token_motor="t", escritor_id=self.id,
                                          heartbeat_segundos=0, margen_relevo_segundos=0,
                                          ruta_relevo=self.local / "relevo.json")
        with patch.object(ec, "configuracion_publicacion", return_value=self.config):
            lease.custodia = ec.CustodiaEstado(raiz or self.raiz, ec.ClienteEstado("https://cloud.test", "t", 5),
                                               carpeta_local=self.local)
        return lease

    def publicado(self, rel: str) -> str | None:
        ruta = self.publicada.joinpath(*rel.split("/"))
        return ruta.read_text(encoding="utf-8") if ruta.is_file() else None


class RaizTrabajoAislada(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        self.cloud = CloudFalsa()
        self.casa = EquipoAislado(base, "casa", self.cloud)
        self.oficina = EquipoAislado(base, "oficina", self.cloud)
        self._parches = [patch("atlas_core.escritor_operativo._json", side_effect=self.cloud.json),
                         patch.object(ec.ClienteEstado, "_crudo", lambda c, h, **kw: self.cloud.crudo(c, h, **kw))]
        for p in self._parches:
            p.start()
        # Base confirmada por CASA, publicada y replicada por Drive a OFICINA,
        # que prepara desde ahí su propia raíz de trabajo.
        self.turno(self.casa, {DATASET: "archivo;g\ng1;1\n", CATALOGO: "cat-1"})
        drive_sincroniza(self.casa.publicada, self.oficina.publicada)
        shutil.rmtree(self.oficina.raiz)
        shutil.copytree(self.oficina.publicada, self.oficina.raiz)

    def tearDown(self):
        for p in self._parches:
            p.stop()
        ec._activas.clear()
        self._tmp.cleanup()

    def turno(self, equipo: EquipoAislado, escrituras: dict[str, str]):
        with equipo.lease() as lease:
            self.assertTrue(lease.adquirir(), lease.motivo)
            for rel, texto in escrituras.items():
                equipo.escribir(rel, texto)
        return lease

    def cae(self, equipo: EquipoAislado, escrituras: dict[str, str]) -> None:
        self.cloud.avanzar(11)
        lease = equipo.lease()
        self.assertTrue(lease.adquirir(), lease.motivo)
        for rel, texto in escrituras.items():
            equipo.escribir(rel, texto)
        lease.custodia.detener()
        lease._soltar_turno()

    # ------------------------------------------------------------------
    def test_lo_confirmado_se_publica_con_sus_reportes(self):
        self.assertEqual(self.casa.publicado(DATASET), "archivo;g\ng1;1\n")
        self.cloud.avanzar(3)
        self.turno(self.casa, {DATASET: "archivo;g\ng1;1\ng2;2\n", REPORTE: "viajes"})
        self.assertEqual(self.casa.publicado(DATASET), "archivo;g\ng1;1\ng2;2\n")
        self.assertEqual(self.casa.publicado(REPORTE), "viajes")
        self.assertEqual(huella(self.casa.publicado(DATASET)), self.cloud._vigentes()[DATASET][0])

    def test_turno_sin_confirmar_no_llega_a_la_raiz_publicada(self):
        self.cae(self.casa, {DATASET: "archivo;g\ng1;1\ng9;9\n", CATALOGO: "cat-9", REPORTE: "parcial"})
        self.assertIn("g9", self.casa.leer(DATASET))  # sólo en la raíz de trabajo
        self.assertEqual(self.casa.publicado(DATASET), "archivo;g\ng1;1\n")
        self.assertEqual(self.casa.publicado(CATALOGO), "cat-1")
        self.assertIsNone(self.casa.publicado(REPORTE))

    def test_segundo_escritor_continua_sin_contaminacion_ni_bloqueo(self):
        self.cae(self.casa, {DATASET: "archivo;g\ng1;1\ng9;9\n", REPORTE: "parcial"})
        drive_sincroniza(self.casa.publicada, self.oficina.publicada)  # Drive a mitad de la caída
        self.cloud.avanzar(11)
        with self.oficina.lease() as lease:
            self.assertTrue(lease.adquirir(), lease.motivo)  # sin ESTADO_NO_VERIFICADO
            self.assertNotIn("g9", self.oficina.leer(DATASET))
            self.oficina.escribir(DATASET, self.oficina.leer(DATASET) + "g2;2\n")
        drive_sincroniza(self.oficina.publicada, self.casa.publicada)
        for equipo in (self.casa, self.oficina):
            self.assertEqual(equipo.publicado(DATASET), "archivo;g\ng1;1\ng2;2\n")
            self.assertIsNone(equipo.publicado(REPORTE))
        # CASA vuelve: su turno superado se aísla y su raíz queda como Cloud.
        self.cloud.avanzar(11)
        with self.casa.lease() as vuelta:
            self.assertTrue(vuelta.adquirir(), vuelta.motivo)
        self.assertEqual(self.casa.leer(DATASET), "archivo;g\ng1;1\ng2;2\n")

    def test_turno_propio_superado_sin_contenido_custodiado_no_bloquea_al_volver(self):
        self.cloud.avanzar(11)
        lease = self.casa.lease()
        self.assertTrue(lease.adquirir(), lease.motivo)
        with open(self.casa.archivo(DATASET), "a", encoding="utf-8") as archivo:  # directa, sin punto de control
            archivo.write("g9;9\n")
        lease.custodia.detener()
        lease._soltar_turno()
        self.cloud.avanzar(11)
        with self.oficina.lease() as otro:
            self.assertTrue(otro.adquirir(), otro.motivo)
            self.oficina.escribir(CATALOGO, "cat-oficina")
        self.cloud.avanzar(11)
        with self.casa.lease() as vuelta:
            self.assertTrue(vuelta.adquirir(), vuelta.motivo)
            self.assertIn(DATASET, vuelta.custodia.resumen["cuarentena"])
        self.assertNotIn("g9", self.casa.leer(DATASET))
        copias = list((self.casa.local / "cuarentena").rglob("analisis_completo_guias.csv"))
        self.assertTrue(any("g9" in c.read_text(encoding="utf-8") for c in copias))  # no se pierde

    def test_sin_raiz_aislada_se_mantiene_la_proteccion_del_dataset(self):
        normal = Equipo(Path(self._tmp.name), "normal", self.cloud)
        for rel in (DATASET, CATALOGO):
            normal.archivo(rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(self.casa.archivo(rel), normal.archivo(rel))
        self.cloud.avanzar(11)
        lease = normal.lease()
        self.assertTrue(lease.adquirir(), lease.motivo)
        with open(normal.archivo(DATASET), "a", encoding="utf-8") as archivo:
            archivo.write("g9;9\n")
        lease.custodia.detener()
        lease._soltar_turno()
        self.cloud.avanzar(11)
        self.turno(self.oficina, {CATALOGO: "cat-oficina"})
        self.cloud.avanzar(11)
        vuelta = normal.lease()
        self.assertFalse(vuelta.adquirir())
        self.assertEqual(vuelta.motivo, "ESTADO_NO_VERIFICADO")

    def test_la_raiz_publicada_no_se_usa_para_escribir(self):
        self.cloud.avanzar(3)
        lease = self.casa.lease(raiz=self.casa.publicada)
        self.assertFalse(lease.adquirir())
        self.assertEqual(lease.motivo, "ESTADO_NO_VERIFICADO")
        self.assertEqual(self.casa.publicado(CATALOGO), "cat-1")

    def test_publicacion_fallida_se_reintenta_en_el_siguiente_turno(self):
        self.cloud.avanzar(3)
        with patch.object(ec.CustodiaEstado, "_escribir_publicada", side_effect=OSError("Drive desmontado")):
            self.turno(self.casa, {CATALOGO: "cat-2"})
        self.assertEqual(self.cloud._vigentes()[CATALOGO][0], huella("cat-2"))  # Cloud confirmó igual
        self.assertEqual(self.casa.publicado(CATALOGO), "cat-1")
        self.cloud.avanzar(3)
        with self.casa.lease() as lease:
            self.assertTrue(lease.adquirir(), lease.motivo)
            self.assertEqual(lease.custodia.resumen["publicacion_reintentada"], 1)
        self.assertEqual(self.casa.publicado(CATALOGO), "cat-2")

    def test_trae_reportes_de_turnos_confirmados_en_otro_equipo(self):
        self.cloud.avanzar(3)
        self.turno(self.casa, {REPORTE: "viajes-casa"})
        drive_sincroniza(self.casa.publicada, self.oficina.publicada)
        self.cloud.avanzar(11)
        with self.oficina.lease() as lease:
            self.assertTrue(lease.adquirir(), lease.motivo)
            self.assertEqual(lease.custodia.resumen["traidos_de_publicada"], 1)
        self.assertEqual(self.oficina.leer(REPORTE), "viajes-casa")

    def test_preparar_raiz_trabajo(self):
        base = Path(self._tmp.name) / "nuevo"
        publicada, trabajo = base / "Drive" / "Atlas", base / "Local" / "Atlas"
        shutil.copytree(self.casa.publicada, publicada)
        with patch.object(ec, "ruta_configuracion_publicacion", return_value=base / "cfg" / "raiz_publicada.json"):
            r = ec.preparar_raiz_trabajo(publicada, trabajo)
            self.assertTrue(r["copiada"])
            self.assertEqual(ec.configuracion_publicacion(), {"raiz_trabajo": str(trabajo), "raiz_publicada": str(publicada)})
            with self.assertRaises(ec.EstadoNoVerificado):
                ec.preparar_raiz_trabajo(publicada, publicada / "dentro")
        self.assertEqual((trabajo / "catalogos_privados" / "vehiculos.json").read_text(encoding="utf-8"), "cat-1")


if __name__ == "__main__":
    unittest.main()
