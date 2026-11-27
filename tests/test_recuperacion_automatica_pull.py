"""P0.4: el ciclo normal del PULL recupera solo los turnos interrumpidos.

Se usa ``ejecutar_pull_con_escritor`` real con la Cloud simulada de
test_estado_confirmado; la recepción de envíos y los pasos de licencias se
sustituyen por dobles (la pasada escribe un envío nuevo, como haría Mobile).
El equipo original se elimina: todo sale de Cloud.
"""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import sincronizar_mobile_cloud as smc
from atlas_core import escritor_operativo as eo
from atlas_core import estado_confirmado as ec
from tests.test_estado_confirmado import CATALOGO, CloudFalsa, Equipo, sha
from tests.test_recuperacion_turno_remoto import DATASET, dataset, huella


class RecuperacionAutomaticaPull(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)
        self.cloud = CloudFalsa()
        self.casa = Equipo(self.base, "casa", self.cloud)
        self.oficina = Equipo(self.base, "oficina", self.cloud)
        self._parches = [patch("atlas_core.escritor_operativo._json", side_effect=self.cloud.json),
                         patch.object(ec.ClienteEstado, "_crudo", lambda c, h, **kw: self.cloud.crudo(c, h, **kw))]
        for nombre in ("sincronizar_licencias_cloud", "extraer_licencias_pendientes", "identificar_patentes_documentos",
                       "extraer_vencimientos_vehiculos", "publicar_asignaciones_cloud", "ejecutar_en_ciclo_pull"):
            if hasattr(smc, nombre):
                self._parches.append(patch.object(smc, nombre, return_value={}))
        for p in self._parches:
            p.start()
        with self.casa.lease() as lease:
            self.assertTrue(lease.adquirir(), lease.motivo)
            self.casa.escribir(DATASET, dataset("g1", "g2"))
            self.casa.escribir(CATALOGO, "cat-1")
        for rel in (DATASET, CATALOGO):
            self.oficina.escribir(rel, self.casa.leer(rel))

    def tearDown(self):
        for p in self._parches:
            p.stop()
        ec._activas.clear()
        self._tmp.cleanup()

    # ------------------------------------------------------------ apoyo
    def fabrica(self, equipo: Equipo):
        def crear(**_kw):
            lease = eo.LeaseEscritorOperativo(base_url="https://cloud.test", token_motor="t", escritor_id=equipo.id,
                                              heartbeat_segundos=0, margen_relevo_segundos=0,
                                              ruta_relevo=equipo.local / "relevo.json")
            lease.vincular_raiz = lambda raiz: setattr(lease, "custodia", ec.CustodiaEstado(
                raiz, ec.ClienteEstado("https://cloud.test", "t", 5), carpeta_local=equipo.local))
            return lease
        return crear

    def pull(self, equipo: Equipo, envio: str) -> dict:
        """Una pasada del PULL: recibe un envío Mobile (escritura propia)."""
        def recibir(**_kw):
            equipo.escribir(f"operacion/mobile/envios/{envio}/envio.json", json.dumps({"envio_id": envio}))
            return {"encontrados": 1, "confirmados": [envio]}

        with patch.object(smc, "sincronizar_envios_cloud", side_effect=recibir):
            return smc.ejecutar_pull_con_escritor(
                base_url="https://cloud.test", token_motor="t", consumidor=equipo.id,
                repositorio=SimpleNamespace(raiz_atlas=equipo.raiz), timeout=5, procesar=False,
                dataset=equipo.archivo(DATASET), carpeta_catalogos=None, fabrica_escritor=self.fabrica(equipo))

    def casa_se_pierde(self, escrituras: dict[str, str], *, directas: dict[str, str] | None = None) -> str:
        self.cloud.avanzar(3)
        lease = self.casa.lease()
        self.assertTrue(lease.adquirir(), lease.motivo)
        for rel, texto in escrituras.items():
            self.casa.escribir(rel, texto)
        for rel, texto in (directas or {}).items():
            with open(self.casa.archivo(rel), "a", encoding="utf-8") as archivo:
                archivo.write(texto)
        diario = ec.ruta_diario("pc-casa", lease.epoca)
        lease.custodia.detener()
        lease._soltar_turno()
        shutil.rmtree(self.casa.raiz.parent)
        self.cloud.avanzar(11)
        return diario

    def vigentes(self) -> dict:
        return {r: s for r, (s, _v) in self.cloud._vigentes().items()}

    # ------------------------------------------------------------ casos
    def test_pull_recupera_el_turno_perdido_y_sigue(self):
        escrito = {DATASET: dataset("g1", "g2", "g3"), CATALOGO: "cat-2"}
        diario = self.casa_se_pierde(escrito)
        r = self.pull(self.oficina, "env-oficina-1")
        self.assertNotEqual(r.get("escritor_operativo"), "NO_ADQUIRIDO")
        rec = r["recuperacion_turnos"]
        self.assertEqual([x["diario"] for x in rec["recuperados"]], [diario])
        self.assertEqual(rec["recuperados"][0]["documentos_recuperados"], ["g3"])
        self.assertEqual(rec["en_revision"], [])
        vig = self.vigentes()
        for rel, texto in escrito.items():
            self.assertEqual(vig[rel], huella(texto))
        self.assertIsNone(vig[diario])
        self.assertIsNotNone(vig["operacion/mobile/envios/env-oficina-1/envio.json"])  # la pasada continuó

    def test_segundo_ciclo_no_repite_ni_duplica(self):
        diario = self.casa_se_pierde({DATASET: dataset("g1", "g2", "g3")})
        self.pull(self.oficina, "env-1")
        self.cloud.avanzar(3)
        version = self.cloud.marca["version"]
        r = self.pull(self.oficina, "env-2")
        self.assertEqual(r["recuperacion_turnos"], {"recuperados": [], "en_revision": [], "omitidos": 0})
        self.assertEqual(self.oficina.leer(DATASET).count("g3;"), 1)
        self.assertIsNone(self.vigentes()[diario])
        self.assertGreater(self.cloud.marca["version"], version)  # sólo por el envío nuevo

    def test_incompatible_queda_en_revision_sin_bloquear_la_pasada(self):
        diario = self.casa_se_pierde({}, directas={DATASET: "g9;9\n"})  # sin contenido custodiado
        r = self.pull(self.oficina, "env-1")
        rec = r["recuperacion_turnos"]
        self.assertEqual(rec["recuperados"], [])
        self.assertEqual([(e["diario"], e["permanente"]) for e in rec["en_revision"]], [(diario, True)])
        self.assertEqual(rec["en_revision"][0]["bloqueos"][0]["codigo"], "CONTENIDO_NO_CUSTODIADO")
        self.assertIsNotNone(self.vigentes()["operacion/mobile/envios/env-1/envio.json"])
        self.assertIsNotNone(self.vigentes()[diario])  # se conserva para revisión
        self.assertNotIn("g9", self.oficina.leer(DATASET))
        # El ciclo siguiente no lo reevalúa: lo informa y sigue.
        self.cloud.avanzar(3)
        with patch.object(ec.CustodiaEstado, "recuperar_turno", side_effect=AssertionError("no debía reevaluarse")):
            r = self.pull(self.oficina, "env-2")
        self.assertEqual(r["recuperacion_turnos"]["omitidos"], 1)
        self.assertIsNotNone(self.vigentes()["operacion/mobile/envios/env-2/envio.json"])

    def test_compatibles_e_incompatibles_en_el_mismo_ciclo(self):
        perdido = self.casa_se_pierde({CATALOGO: "cat-2"})
        tercero = Equipo(self.base, "tercero", self.cloud)
        for rel in (DATASET, CATALOGO):
            tercero.escribir(rel, {DATASET: dataset("g1", "g2"), CATALOGO: "cat-1"}[rel])
        lease = tercero.lease()
        self.assertTrue(lease.adquirir(), lease.motivo)  # tercero: CATALOGO cambia sobre la misma base
        tercero.escribir(CATALOGO, "cat-tercero")
        tercero.escribir(DATASET, dataset("g1", "g2", "g5"))
        posterior = ec.ruta_diario("pc-tercero", lease.epoca)
        lease.custodia.detener()
        lease._soltar_turno()
        self.cloud.avanzar(11)
        r = self.pull(self.oficina, "env-1")
        rec = r["recuperacion_turnos"]
        # El más antiguo (CASA) se aplica; el de TERCERO pisaría CATALOGO ya cambiado: revisión.
        self.assertEqual([x["diario"] for x in rec["recuperados"]], [perdido])
        self.assertEqual([e["diario"] for e in rec["en_revision"]], [posterior])
        self.assertEqual(rec["en_revision"][0]["bloqueos"][0], {"codigo": "VERSION_POSTERIOR", "rutas": [CATALOGO]})
        self.assertEqual(self.vigentes()[CATALOGO], huella("cat-2"))
        self.assertEqual(self.vigentes()[DATASET], huella(dataset("g1", "g2")))

    def test_lease_perdido_detiene_la_recuperacion_sin_romper(self):
        self.casa_se_pierde({CATALOGO: "cat-2"})
        lease = self.oficina.lease()
        self.assertTrue(lease.adquirir(), lease.motivo)
        self.cloud.avanzar(5)  # vence antes de recuperar
        r = lease.custodia.recuperar_automaticamente(lease)
        self.assertEqual(r["recuperados"], [])
        self.assertEqual(self.vigentes()[CATALOGO], huella("cat-1"))
        lease.cerrar()


if __name__ == "__main__":
    unittest.main()
