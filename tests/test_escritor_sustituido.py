"""P0.3: un escritor cuyo lease venció o fue sustituido no modifica datos
compartidos, aunque localmente se crea vigente (sin heartbeat). La
protección está en cada escritura (servidor + contenido del destino) y en la
confirmación, no en una comprobación previa. Cloud simulada con la semántica
del Worker (tests/test_estado_confirmado.py).
"""
from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from atlas_core import estado_confirmado as ec
from tests.test_estado_confirmado import CATALOGO, CloudFalsa, Equipo, sha

DATASET = ec.RUTA_DATASET


def drive_escribe(ruta: Path, texto: str) -> None:
    """Google Drive (DriveFS) es otro proceso: la custodia no lo observa."""
    activas = list(ec._activas)
    ec._activas.clear()
    try:
        ruta.write_text(texto, encoding="utf-8")
    finally:
        ec._activas.extend(activas)


def huella(texto: str) -> str:
    return sha(texto.replace("\n", os.linesep).encode())


class EscritorSustituido(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        self.cloud = CloudFalsa()
        self.casa = Equipo(base, "casa", self.cloud)
        self.oficina = Equipo(base, "oficina", self.cloud)
        self._parches = [patch("atlas_core.escritor_operativo._json", side_effect=self.cloud.json),
                         patch.object(ec.ClienteEstado, "_crudo", lambda c, h, **kw: self.cloud.crudo(c, h, **kw))]
        for p in self._parches:
            p.start()
        with self.casa.lease() as lease:
            self.assertTrue(lease.adquirir(), lease.motivo)
            self.casa.escribir(DATASET, "archivo;g\ng1;1\n")
            self.casa.escribir(CATALOGO, "cat-1")
        for rel in (DATASET, CATALOGO):  # Drive replica la base a OFICINA
            self.oficina.archivo(rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(self.casa.archivo(rel), self.oficina.archivo(rel))

    def tearDown(self):
        for p in self._parches:
            p.stop()
        ec._activas.clear()
        self._tmp.cleanup()

    def vigentes(self) -> dict:
        return {r: s for r, (s, _v) in self.cloud._vigentes().items()}

    def abrir_turno(self, equipo: Equipo):
        lease = equipo.lease()  # heartbeat_segundos=0: el estado local no se entera de nada
        self.assertTrue(lease.adquirir(), lease.motivo)
        return lease

    # ------------------------------------------- lease vencido, local "vigente"
    def test_lease_vencido_rechaza_incluso_reescrituras_sin_cambios(self):
        self.cloud.avanzar(3)
        lease = self.abrir_turno(self.casa)
        self.casa.escribir(CATALOGO, "cat-2")
        self.cloud.avanzar(5)  # vence en Cloud; nadie lo sabe localmente
        self.assertTrue(lease.vigente)
        with self.assertRaises(ec.EscritorSustituido):
            self.casa.escribir(CATALOGO, "cat-2")  # mismo contenido: sin publicación del diario
        with self.assertRaises(ec.EscritorSustituido):
            self.casa.escribir(DATASET, "archivo;g\ng1;1\ng9;9\n")
        self.assertEqual(self.casa.leer(DATASET), "archivo;g\ng1;1\n")
        self.assertFalse(lease.vigente)  # el rechazo del servidor queda registrado
        lease.cerrar()
        self.assertEqual(self.vigentes()[CATALOGO], huella("cat-1"))

    def test_escritura_directa_tras_vencer_se_rechaza(self):
        self.cloud.avanzar(3)
        lease = self.abrir_turno(self.casa)
        with open(self.casa.archivo(DATASET), "a", encoding="utf-8") as archivo:
            archivo.write("g2;2\n")
        self.cloud.avanzar(5)
        with self.assertRaises(ec.EscritorSustituido):
            with open(self.casa.archivo(DATASET), "a", encoding="utf-8") as archivo:
                archivo.write("g3;3\n")
        self.assertNotIn("g3", self.casa.leer(DATASET))
        lease.cerrar()

    # --------------------------------------------- sustituido por otro equipo
    def test_escritor_anterior_no_sobrescribe_al_nuevo(self):
        self.cloud.avanzar(3)
        viejo = self.abrir_turno(self.casa)
        self.casa.escribir(CATALOGO, "cat-casa")
        self.cloud.avanzar(11)  # el lease de CASA vence; OFICINA lo toma
        with self.oficina.lease() as nuevo:
            self.assertTrue(nuevo.adquirir(), nuevo.motivo)
            self.oficina.escribir(DATASET, "archivo;g\ng1;1\ng2;2\n")
            self.oficina.escribir(CATALOGO, "cat-oficina")
        oficina = self.vigentes()
        self.assertTrue(viejo.vigente)  # CASA aún se cree vigente
        for rel, texto in ((CATALOGO, "cat-casa-2"), (DATASET, "archivo;g\ng1;1\ng9;9\n")):
            with self.assertRaises(ec.EstadoNoVerificado):
                self.casa.escribir(rel, texto)
        viejo.cerrar()  # su confirmación también la rechaza Cloud
        self.assertEqual(self.vigentes(), oficina)
        self.assertEqual(oficina[CATALOGO], huella("cat-oficina"))

    def test_expiracion_durante_una_escritura_directa(self):
        self.cloud.avanzar(3)
        viejo = self.abrir_turno(self.casa)
        archivo = open(self.casa.archivo(DATASET), "a", encoding="utf-8")  # comprobación vigente
        archivo.write("g7;7\n")
        self.cloud.avanzar(11)
        with self.oficina.lease() as nuevo:
            self.assertTrue(nuevo.adquirir(), nuevo.motivo)
            self.oficina.escribir(DATASET, "archivo;g\ng1;1\ng2;2\n")
        archivo.close()  # los bytes llegan al disco de CASA: inevitable y local
        self.assertFalse(ec.punto_de_control_tras_escritura(self.casa.archivo(DATASET)))
        with self.assertRaises(ec.DiarioNoPersistido):
            ec.punto_de_control(self.casa.archivo(DATASET))
        viejo.cerrar()
        self.assertEqual(self.vigentes()[DATASET], huella("archivo;g\ng1;1\ng2;2\n"))

    # ------------------------------------------- contenido ajeno en el destino
    def test_contenido_ajeno_traido_por_drive_no_se_pisa_ni_se_adopta(self):
        self.cloud.avanzar(11)
        with self.oficina.lease() as lease:
            self.assertTrue(lease.adquirir(), lease.motivo)
            self.oficina.escribir(CATALOGO, "cat-oficina")
            # Drive trae la versión del escritor anterior a mitad del turno.
            drive_escribe(self.oficina.archivo(CATALOGO), "cat-casa-viejo")
            with self.assertRaises(ec.ContenidoAjeno):
                self.oficina.escribir(CATALOGO, "cat-casa-viejo + oficina")
            self.assertEqual(self.oficina.leer(CATALOGO), "cat-casa-viejo")
        self.assertEqual(self.vigentes()[CATALOGO], huella("cat-oficina"))
        self.assertEqual(lease.custodia.ajenos_descartados, [CATALOGO])
        self.cloud.avanzar(3)
        with self.oficina.lease() as vuelta:
            self.assertTrue(vuelta.adquirir(), vuelta.motivo)
            self.assertEqual(vuelta.custodia.resumen["cuarentena"], [CATALOGO])
        self.assertEqual(self.oficina.leer(CATALOGO), "cat-oficina")

    def test_ruta_no_tocada_cambiada_por_drive_no_se_escribe(self):
        self.cloud.avanzar(11)
        with self.oficina.lease() as lease:
            self.assertTrue(lease.adquirir(), lease.motivo)
            drive_escribe(self.oficina.archivo(DATASET), "archivo;g\ng1;1\ng8;8\n")
            with self.assertRaises(ec.ContenidoAjeno):
                with open(self.oficina.archivo(DATASET), "a", encoding="utf-8") as archivo:
                    archivo.write("g2;2\n")
        self.assertEqual(self.vigentes()[DATASET], huella("archivo;g\ng1;1\n"))

    def test_mismo_equipo_al_volver_confirma_lo_que_escribio_no_lo_que_hay(self):
        self.cloud.avanzar(3)
        lease = self.abrir_turno(self.casa)
        self.casa.escribir(CATALOGO, "cat-2")
        lease.custodia.detener()
        lease._soltar_turno()  # corte de luz
        drive_escribe(self.casa.archivo(CATALOGO), "ajeno")  # Drive, después
        self.cloud.avanzar(3)
        with self.casa.lease() as vuelta:
            self.assertTrue(vuelta.adquirir(), vuelta.motivo)
            self.assertEqual(vuelta.custodia.resumen["pendiente_confirmado"], 1)
        self.assertEqual(self.vigentes()[CATALOGO], huella("cat-2"))
        self.assertEqual(self.casa.leer(CATALOGO), "cat-2")


if __name__ == "__main__":
    unittest.main()
