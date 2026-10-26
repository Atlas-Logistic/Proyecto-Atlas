from __future__ import annotations

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
