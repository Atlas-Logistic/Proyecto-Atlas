from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from atlas_core.escritor_operativo import ErrorEscritorOperativo, LeaseEscritorOperativo, identidad_escritor


class ApiEscritor:
    def __init__(self, *, ocupado: bool = False, epoca_previa: int = 0):
        self.ocupado = ocupado
        self.epoca = epoca_previa
        self.token = ""
        self.llamadas: list[tuple[str, dict | None]] = []
        self.trabajo_terminado = False

    def __call__(self, _base, ruta, _token, *, method="GET", body=None, timeout=0):
        self.llamadas.append((ruta, body))
        if ruta.endswith("/estado"):
            return {"vigente": bool(self.token), "epoca": self.epoca}
        if ruta.endswith("/adquirir"):
            if self.ocupado:
                raise ErrorEscritorOperativo("ocupado")
            self.epoca += 1
            self.token = f"token-{self.epoca}"
            return {"estado": "ADQUIRIDO", "lease_token": self.token, "epoca": self.epoca}
        if ruta.endswith("/renovar"):
            if body["lease_token"] != self.token:
                raise ErrorEscritorOperativo("token inválido")
            return {"estado": "RENOVADO", "epoca": self.epoca}
        if ruta.endswith("/liberar"):
            if body["lease_token"] != self.token:
                raise ErrorEscritorOperativo("token inválido")
            assert self.trabajo_terminado, "no se libera antes de terminar el trabajo"
            self.token = ""
            return {"estado": "LIBERADO"}
        raise AssertionError(ruta)


class EscritorOperativoTests(unittest.TestCase):
    def test_identidad_es_estable_y_local(self):
        with tempfile.TemporaryDirectory() as temporal:
            ruta = Path(temporal) / "escritor.txt"
            self.assertEqual(identidad_escritor(ruta=ruta), identidad_escritor(ruta=ruta))
            self.assertTrue(ruta.is_file())

    def test_obtiene_renueva_y_libera_solo_despues_del_trabajo(self):
        api = ApiEscritor()
        with patch("atlas_core.escritor_operativo._json", side_effect=api):
            lease = LeaseEscritorOperativo(base_url="https://cloud.test", token_motor="t", escritor_id="casa-1", heartbeat_segundos=0)
            self.assertTrue(lease.adquirir())
            self.assertTrue(lease.renovar())
            api.trabajo_terminado = True
            lease.cerrar()
        rutas = [ruta for ruta, _ in api.llamadas]
        self.assertEqual(rutas, ["/api/motor/escritor/estado", "/api/motor/escritor/adquirir", "/api/motor/escritor/renovar", "/api/motor/escritor/liberar"])

    def test_lease_ocupado_no_permite_pull(self):
        api = ApiEscritor(ocupado=True)
        with patch("atlas_core.escritor_operativo._json", side_effect=api):
            lease = LeaseEscritorOperativo(base_url="https://cloud.test", token_motor="t", escritor_id="oficina-1", heartbeat_segundos=0)
            self.assertFalse(lease.adquirir())
            self.assertFalse(lease.vigente)
        self.assertEqual([ruta for ruta, _ in api.llamadas], ["/api/motor/escritor/estado", "/api/motor/escritor/adquirir"])

    def test_ocupado_solo_ante_409_de_adquirir(self):
        import io, urllib.error
        from atlas_core import escritor_operativo as eo
        def http(codigo):
            def abrir(request, timeout=0):
                if request.full_url.endswith("/estado"):
                    return io.BytesIO(b'{"vigente": true, "epoca": 3}')
                raise urllib.error.HTTPError(request.full_url, codigo, "x", {}, io.BytesIO(b"{}"))
            return abrir
        lease = LeaseEscritorOperativo(base_url="https://cloud.test", token_motor="t", escritor_id="casa-1", heartbeat_segundos=0)
        with patch("urllib.request.urlopen", side_effect=http(409)):
            self.assertFalse(lease.adquirir())
            self.assertTrue(lease.ocupado)
            with self.assertRaises(eo.EscritorOcupado):
                eo._json("https://cloud.test", "/api/motor/escritor/adquirir", "t", method="POST", body={}, timeout=1)
            with self.assertRaises(ErrorEscritorOperativo) as renovar:
                eo._json("https://cloud.test", "/api/motor/escritor/renovar", "t", method="POST", body={}, timeout=1)
            self.assertNotIsInstance(renovar.exception, eo.EscritorOcupado)
        for codigo in (401, 503):
            with patch("urllib.request.urlopen", side_effect=http(codigo)):
                self.assertFalse(lease.adquirir())
                self.assertFalse(lease.ocupado)
        self.assertFalse(lease.vigente)

    def test_relevo_con_epoca_previa_respeta_margen(self):
        api = ApiEscritor(epoca_previa=1)
        esperas: list[float] = []
        with patch("atlas_core.escritor_operativo._json", side_effect=api):
            lease = LeaseEscritorOperativo(
                base_url="https://cloud.test", token_motor="t", escritor_id="oficina-1",
                heartbeat_segundos=0, margen_relevo_segundos=30, dormir=esperas.append,
            )
            self.assertTrue(lease.adquirir())
            api.trabajo_terminado = True
            lease.cerrar()
        self.assertEqual(esperas, [30])

    def test_heartbeat_renueva_mientras_el_pull_sigue_activo(self):
        api = ApiEscritor()
        with patch("atlas_core.escritor_operativo._json", side_effect=api):
            lease = LeaseEscritorOperativo(
                base_url="https://cloud.test", token_motor="t", escritor_id="casa-1",
                heartbeat_segundos=0.01,
            )
            self.assertTrue(lease.adquirir())
            time.sleep(0.04)
            api.trabajo_terminado = True
            lease.cerrar()
        renovaciones = [ruta for ruta, _ in api.llamadas if ruta.endswith("/renovar")]
        self.assertGreaterEqual(len(renovaciones), 2)


class RelevoConfirmadoTests(unittest.TestCase):
    """El margen sólo se omite si este PC liberó la época inmediata anterior."""

    def setUp(self):
        self._temporal = tempfile.TemporaryDirectory()
        self.ruta = Path(self._temporal.name) / "relevo.json"
        self.api = ApiEscritor()
        self.api.trabajo_terminado = True
        self.esperas: list[float] = []
        self._parche = patch("atlas_core.escritor_operativo._json", side_effect=self.api)
        self._parche.start()

    def tearDown(self):
        self._parche.stop()
        self._temporal.cleanup()

    def lease(self, escritor_id="casa-1"):
        return LeaseEscritorOperativo(
            base_url="https://cloud.test", token_motor="t", escritor_id=escritor_id,
            heartbeat_segundos=0, margen_relevo_segundos=30, dormir=self.esperas.append,
            ruta_relevo=self.ruta,
        )

    def ciclo(self, escritor_id="casa-1"):
        lease = self.lease(escritor_id)
        self.assertTrue(lease.adquirir())
        lease.cerrar()
        return lease

    def test_relevo_inmediato_tras_liberacion_confirmada_del_mismo_pc(self):
        self.ciclo()  # época 1: sin titular previo, sin margen
        self.ciclo()  # época 2: relevo de la 1 liberada por este PC
        self.ciclo()
        self.assertEqual(self.esperas, [])
        self.assertEqual(json.loads(self.ruta.read_text(encoding="utf-8")), {"escritor_id": "casa-1", "epoca": 3})

    def test_vencimiento_sin_liberar_conserva_margen(self):
        self.ciclo()
        caido = self.lease()
        self.assertTrue(caido.adquirir())  # época 2: el proceso cae sin liberar
        self.api.token = ""  # Cloud la da por vencida
        self.ciclo()
        self.assertEqual(self.esperas, [30])

    def test_lease_perdido_no_deja_constancia(self):
        self.ciclo()
        perdido = self.lease()
        self.assertTrue(perdido.adquirir())
        perdido._perdido.set()
        perdido.cerrar()
        self.ciclo()
        self.assertEqual(self.esperas, [30])

    def test_otro_pc_entre_medio_conserva_margen(self):
        self.ciclo("casa-1")
        self.ciclo("oficina-1")  # registro local de casa-1 no prueba nada de oficina
        self.esperas.clear()
        self.ciclo("casa-1")
        self.assertEqual(self.esperas, [30])

    def test_salto_de_epoca_por_concurrencia_conserva_margen(self):
        self.ciclo()
        self.api.epoca += 1  # otro titular tomó y soltó una época sin que este PC lo viera
        self.ciclo()
        self.assertEqual(self.esperas, [30])

    def test_error_de_red_al_liberar_conserva_margen(self):
        self.ciclo()
        lease = self.lease()
        self.assertTrue(lease.adquirir())
        original = self.api.__call__
        def falla_liberar(base, ruta, token, **kw):
            if ruta.endswith("/liberar"):
                self.api.token = ""
                raise ErrorEscritorOperativo("red")
            return original(base, ruta, token, **kw)
        self._parche.stop()
        with patch("atlas_core.escritor_operativo._json", side_effect=falla_liberar):
            lease.cerrar()
        self._parche.start()
        self.ciclo()
        self.assertEqual(self.esperas, [30])

    def test_estado_desconocido_o_registro_corrupto_conserva_margen(self):
        self.ciclo()
        self.ruta.write_text("{corrupto", encoding="utf-8")
        self.ciclo()
        self.assertEqual(self.esperas, [30])
        original = self.api.__call__
        def sin_vigente(base, ruta, token, **kw):
            respuesta = original(base, ruta, token, **kw)
            return {"epoca": respuesta["epoca"]} if ruta.endswith("/estado") else respuesta
        self._parche.stop()
        with patch("atlas_core.escritor_operativo._json", side_effect=sin_vigente):
            self.ciclo()
        self._parche.start()
        self.assertEqual(self.esperas, [30, 30])
