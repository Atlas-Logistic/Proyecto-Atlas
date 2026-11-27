"""P0.1: diario de recuperación persistido en Cloud antes de escribir.

El diario de cada turno (empresa, escritor, época del lease, versión base y
rutas) debe quedar en Cloud antes de que cambie cualquier dato operacional y
sobrevivir a la pérdida definitiva del equipo que lo inició: otro equipo de la
misma empresa lo lee íntegro, verificado por huella. Usa la misma Cloud
simulada que tests/test_estado_confirmado.py (semántica del Worker).
"""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from atlas_core import escritor_operativo as eo
from atlas_core import estado_confirmado as ec
from tests.test_estado_confirmado import CATALOGO, DATASET, CloudFalsa, Equipo, sha


class DiarioRecuperacionRemoto(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)
        self.cloud = CloudFalsa()
        self.casa = Equipo(self.base, "casa", self.cloud)
        self.oficina = Equipo(self.base, "oficina", self.cloud)
        self._parches = [patch("atlas_core.escritor_operativo._json", side_effect=self.cloud.json),
                         patch.object(ec.ClienteEstado, "_crudo", lambda c, h, **kw: self.cloud.crudo(c, h, **kw))]
        for p in self._parches:
            p.start()

    def tearDown(self):
        for p in self._parches:
            p.stop()
        ec._activas.clear()
        self._tmp.cleanup()

    def turno(self, equipo: Equipo, escrituras: dict[str, str]):
        with equipo.lease() as lease:
            self.assertTrue(lease.adquirir(), lease.motivo)
            for rel, texto in escrituras.items():
                equipo.escribir(rel, texto)
        return lease

    def cliente(self) -> ec.ClienteEstado:
        return ec.ClienteEstado("https://cloud.test", "t", 5)

    def perder_equipo(self, lease, equipo: Equipo) -> None:
        """Apagado sin cerrar y pérdida definitiva: ni raíz ni LOCALAPPDATA."""
        lease.custodia.detener()
        lease._soltar_turno()  # el proceso muere: el kernel libera el bloqueo local
        shutil.rmtree(equipo.raiz.parent)

    # ------------------------------------------------------------ antes
    def test_diario_queda_en_cloud_antes_de_que_cambie_el_archivo(self):
        self.turno(self.casa, {DATASET: "v1"})
        vistos = []
        original = self.cloud.crudo

        def crudo(cliente, huella, **kw):
            if kw.get("method") == "PUT":
                vistos.append(self.casa.leer(DATASET))
            return original(cliente, huella, **kw)

        self.cloud.avanzar(3)
        with self.casa.lease() as lease, patch.object(self.cloud, "crudo", side_effect=crudo):
            self.assertTrue(lease.adquirir(), lease.motivo)
            with open(self.casa.archivo(DATASET), "w", encoding="utf-8") as archivo:
                # Al abrir para escribir, el diario ya está confirmado en Cloud.
                rel = ec.ruta_diario("pc-casa", lease.epoca)
                self.assertIsNotNone(self.cloud._vigentes()[rel][0])
                archivo.write("v2")
        self.assertEqual(vistos[0], "v1")
        self.assertEqual(self.cloud._vigentes()[DATASET][0], sha(b"v2"))

    def test_sin_diario_remoto_la_escritura_se_aborta(self):
        self.turno(self.casa, {DATASET: "v1"})
        self.cloud.avanzar(3)
        version = self.cloud.marca["version"]
        lease = self.casa.lease()
        self.assertTrue(lease.adquirir(), lease.motivo)
        with patch.object(self.cloud, "crudo", side_effect=eo.ErrorEscritorOperativo("Cloud caído")):
            with self.assertRaises(ec.DiarioNoPersistido):
                with open(self.casa.archivo(DATASET), "w", encoding="utf-8") as archivo:
                    archivo.write("v2")
        self.assertEqual(self.casa.leer(DATASET), "v1")
        self.assertEqual(lease.custodia.modificadas, set())
        lease.cerrar()
        self.assertEqual(self.cloud.marca["version"], version)

    def test_lease_perdido_aborta_la_escritura(self):
        self.turno(self.casa, {DATASET: "v1"})
        self.cloud.avanzar(3)
        lease = self.casa.lease()
        self.assertTrue(lease.adquirir(), lease.motivo)
        self.cloud.avanzar(5)  # el lease vence sin heartbeat
        with self.assertRaises(ec.DiarioNoPersistido):
            self.casa.escribir(DATASET, "v2")
        self.assertEqual(self.casa.leer(DATASET), "v1")
        lease.cerrar()

    # --------------------------------------------------- contenido y cierre
    def test_diario_ligado_a_empresa_version_base_y_turno(self):
        self.turno(self.casa, {DATASET: "v1"})
        base = self.cloud.marca["version"]
        self.cloud.avanzar(3)
        lease = self.casa.lease()
        self.assertTrue(lease.adquirir(), lease.motivo)
        self.casa.escribir(DATASET, "v2")
        self.casa.escribir(CATALOGO, "cat-1")
        leidos = ec.leer_diarios_remotos(self.cliente(), empresa_id="mbt")
        self.assertEqual(len(leidos["diarios"]), 1)
        entrada = leidos["diarios"][0]
        diario = entrada["diario"]
        self.assertTrue(entrada["vigente"])
        self.assertEqual(entrada["ruta"], ec.ruta_diario("pc-casa", lease.epoca))
        self.assertEqual(diario["empresa_id"], "mbt")
        self.assertEqual(diario["escritor_id"], "pc-casa")
        self.assertEqual(diario["epoca"], lease.epoca)
        self.assertEqual(diario["version_base"], base)
        self.assertEqual(diario["lease_sha256"], sha(lease.lease_token.encode()))
        self.assertEqual(diario["rutas"], sorted([DATASET, CATALOGO]))
        self.assertEqual(diario["huellas_base"], {DATASET: sha(b"v1"), CATALOGO: None})
        lease.cerrar()
        self.assertEqual(ec.leer_diarios_remotos(self.cliente())["diarios"], [])
        self.assertFalse((self.casa.local / "pendiente.json").exists())

    def test_cierre_del_diario_va_en_el_ultimo_lote_de_datos(self):
        lease = self.casa.lease()
        self.assertTrue(lease.adquirir(), lease.motivo)
        self.casa.escribir(DATASET, "v1")
        self.casa.escribir(CATALOGO, "cat-1")
        rel = ec.ruta_diario("pc-casa", lease.epoca)
        original = self.cloud.json
        lotes = []

        def json_(base, ruta, token, **kw):
            if ruta.endswith("/estado/confirmar"):
                lotes.append([par[0] for par in kw["body"]["archivos"]])
                if len(lotes) == 2:
                    raise eo.ErrorEscritorOperativo("corte entre lotes")
            return original(base, ruta, token, **kw)

        with patch.object(ec, "LOTE_CONFIRMACION", 1), patch("atlas_core.escritor_operativo._json", side_effect=json_):
            lease.cerrar()
        self.assertEqual(lotes, [[CATALOGO], [DATASET, rel]])
        # Corte a mitad del cierre: el diario sigue abierto e íntegro.
        self.assertIsNotNone(self.cloud._vigentes()[rel][0])
        self.assertEqual(ec.leer_diarios_remotos(self.cliente())["diarios"][0]["diario"]["rutas"], sorted([DATASET, CATALOGO]))

    # ---------------------------------------------- pérdida del equipo
    def test_diario_sobrevive_a_la_perdida_definitiva_del_equipo(self):
        self.turno(self.casa, {DATASET: "v1", CATALOGO: "cat-1"})
        base = self.cloud.marca["version"]
        self.cloud.avanzar(3)
        lease = self.casa.lease()
        self.assertTrue(lease.adquirir(), lease.motivo)
        epoca = lease.epoca
        self.casa.escribir(DATASET, "v2")
        rel = ec.ruta_diario("pc-casa", epoca)
        publicado = self.cloud.objetos[self.cloud._vigentes()[rel][0]]
        self.perder_equipo(lease, self.casa)
        self.assertFalse(self.casa.raiz.exists())

        # Otro equipo, horas después: lee el diario íntegro desde Cloud.
        self.cloud.avanzar(240)
        self.oficina.escribir(DATASET, "v1")
        self.oficina.escribir(CATALOGO, "cat-1")
        leidos = ec.leer_diarios_remotos(self.cliente(), empresa_id="mbt")["diarios"]
        self.assertEqual(len(leidos), 1)
        self.assertTrue(leidos[0]["vigente"])
        self.assertEqual(ec.serializar_diario(leidos[0]["diario"]), publicado)
        self.assertEqual(leidos[0]["diario"]["version_base"], base)
        self.assertEqual(leidos[0]["diario"]["epoca"], epoca)
        self.assertEqual(leidos[0]["diario"]["rutas"], [DATASET])

        # Su turno no restaura el diario a la raíz, no lo anula ni lo adopta.
        with self.oficina.lease() as otro:
            self.assertTrue(otro.adquirir(), otro.motivo)
            self.assertEqual(otro.custodia.resumen["diarios_abiertos"], [rel])
            self.assertEqual(otro.custodia.resumen["restaurados"], [])
            self.oficina.escribir(CATALOGO, "cat-2")
        self.assertFalse((self.oficina.raiz / ".atlas_custodia").exists())
        despues = ec.leer_diarios_remotos(self.cliente(), empresa_id="mbt")["diarios"]
        self.assertEqual([d["ruta"] for d in despues], [rel])
        self.assertEqual(ec.serializar_diario(despues[0]["diario"]), publicado)
        self.assertFalse(despues[0]["vigente"])  # alguien confirmó después
        verificacion = ec.verificar_sin_escribir(self.oficina.raiz, self.cliente(), carpeta_local=self.oficina.local)
        self.assertEqual(verificacion["distintos"], 0)
        self.assertEqual(verificacion["diarios_abiertos"], [rel])

    def test_mismo_equipo_recupera_su_turno_y_cierra_su_diario(self):
        self.turno(self.casa, {DATASET: "v1"})
        self.cloud.avanzar(3)
        lease = self.casa.lease()
        self.assertTrue(lease.adquirir(), lease.motivo)
        rel = ec.ruta_diario("pc-casa", lease.epoca)
        self.casa.escribir(DATASET, "v2")
        lease.custodia.detener()  # apagado sin confirmar; LOCALAPPDATA intacto
        lease._soltar_turno()  # el proceso muere: el kernel libera el bloqueo local
        self.cloud.avanzar(3)
        with self.casa.lease() as vuelta:
            self.assertTrue(vuelta.adquirir(), vuelta.motivo)
            self.assertEqual(vuelta.custodia.resumen["pendiente_confirmado"], 1)
            self.assertEqual(vuelta.custodia.resumen["diarios_abiertos"], [])
        self.assertEqual(self.cloud._vigentes()[DATASET][0], sha(b"v2"))
        self.assertIsNone(self.cloud._vigentes()[rel][0])

    # -------------------------------------------------------- integridad
    def test_diario_alterado_o_de_otra_empresa_no_se_acepta(self):
        lease = self.casa.lease()
        self.assertTrue(lease.adquirir(), lease.motivo)
        self.casa.escribir(DATASET, "v1")
        rel = ec.ruta_diario("pc-casa", lease.epoca)
        huella = self.cloud._vigentes()[rel][0]
        with self.assertRaises(ec.EstadoNoVerificado):
            ec.leer_diarios_remotos(self.cliente(), empresa_id="andes-prueba")
        original = self.cloud.objetos[huella]
        self.cloud.objetos[huella] = original.replace(b'"epoca"', b'"epoca" ')
        with self.assertRaises(ec.EstadoNoVerificado):
            ec.leer_diarios_remotos(self.cliente())
        otro = json.loads(original)
        otro["epoca"] += 1
        datos = ec.serializar_diario(otro)
        with self.assertRaises(ec.EstadoNoVerificado):
            ec.interpretar_diario(rel, datos, sha(datos))  # no corresponde a su turno
        self.cloud.objetos[huella] = original
        lease.cerrar()


if __name__ == "__main__":
    unittest.main()
