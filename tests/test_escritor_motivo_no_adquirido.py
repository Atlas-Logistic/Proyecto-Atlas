"""Motivo explícito cuando el escritor Cloud no se adquiere sin titular ajeno.

Caso real 16/11/2026 08:12-08:56 en CASA: el Wi-Fi cayó, el PULL quedó en
NO_ADQUIRIDO con motivo vacío y sin rastro del error. Estas pruebas fijan el
motivo y la advertencia, y que el comportamiento seguro no cambia: no se
adquiere, `ocupado` sigue en False, no se reintenta distinto y la salida es 1.
"""
from __future__ import annotations

import io
import json
import logging
import os
import socket
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

from atlas_core import escritor_operativo as eo
from atlas_core.escritor_operativo import LeaseEscritorOperativo

TOKEN_MOTOR = "token-motor-secreto-no-debe-aparecer"
LEASE_SECRETO = "lease-secreto-no-debe-aparecer"


def _lease(**extra) -> LeaseEscritorOperativo:
    return LeaseEscritorOperativo(
        base_url="https://cloud.test", token_motor=TOKEN_MOTOR, escritor_id="casa-1",
        heartbeat_segundos=0, **extra,
    )


def _respuesta(cuerpo: bytes):
    return io.BytesIO(cuerpo)


class ApiRegistrada:
    """`_json` simulado: registra rutas y delega cada una en una función."""

    def __init__(self, **por_ruta):
        self.por_ruta = por_ruta
        self.rutas: list[str] = []

    def __call__(self, _base, ruta, _token, *, method="GET", body=None, timeout=0):
        self.rutas.append(ruta)
        return self.por_ruta[ruta.rsplit("/", 1)[-1]](body)


class MotivoErrorCloudTests(unittest.TestCase):
    def _adquirir_con_urlopen(self, efecto):
        lease = _lease()
        with self.assertLogs("atlas_core.escritor_operativo", level=logging.WARNING) as registros, \
                patch("urllib.request.urlopen", side_effect=efecto) as urlopen:
            self.assertFalse(lease.adquirir())
        return lease, "\n".join(registros.output), urlopen

    def test_sin_red_motivo_cloud_no_disponible_con_advertencia_sin_credenciales(self):
        lease, texto, urlopen = self._adquirir_con_urlopen(
            urllib.error.URLError(socket.gaierror(11001, "getaddrinfo failed")))
        self.assertEqual(lease.motivo, "CLOUD_NO_DISPONIBLE")
        self.assertFalse(lease.ocupado)
        self.assertFalse(lease.vigente)
        self.assertEqual(lease.lease_token, "")
        # Igual que antes: falla en la consulta previa, no llega a /adquirir.
        self.assertEqual(urlopen.call_count, 1)
        self.assertIn("CLOUD_NO_DISPONIBLE", texto)
        self.assertIn("getaddrinfo failed", texto)
        self.assertIn("/api/motor/escritor/estado", texto)
        self.assertNotIn(TOKEN_MOTOR, texto)
        self.assertNotIn("Bearer", texto)

    def test_tiempo_agotado_y_conexion_rechazada_son_cloud_no_disponible(self):
        for efecto in (TimeoutError("timed out"), ConnectionRefusedError(10061, "refused")):
            with self.subTest(efecto=type(efecto).__name__):
                lease, texto, _ = self._adquirir_con_urlopen(efecto)
                self.assertEqual(lease.motivo, "CLOUD_NO_DISPONIBLE")
                self.assertFalse(lease.ocupado)
                self.assertNotIn(TOKEN_MOTOR, texto)

    def test_http_distinto_de_409_es_respuesta_invalida(self):
        for codigo in (401, 403, 500, 503):
            def abrir(request, timeout=0, codigo=codigo):
                if request.full_url.endswith("/estado"):
                    return _respuesta(b'{"vigente": false, "epoca": 3}')
                raise urllib.error.HTTPError(request.full_url, codigo, "x", {}, _respuesta(b"{}"))
            with self.subTest(codigo=codigo):
                lease, texto, _ = self._adquirir_con_urlopen(abrir)
                self.assertEqual(lease.motivo, "RESPUESTA_CLOUD_INVALIDA")
                self.assertFalse(lease.ocupado)
                self.assertIn(f"HTTP Error {codigo}", texto)
                self.assertNotIn(TOKEN_MOTOR, texto)

    def test_json_roto_es_respuesta_invalida(self):
        lease, texto, _ = self._adquirir_con_urlopen(lambda request, timeout=0: _respuesta(b"<html>"))
        self.assertEqual(lease.motivo, "RESPUESTA_CLOUD_INVALIDA")
        self.assertFalse(lease.ocupado)
        self.assertNotIn(TOKEN_MOTOR, texto)

    def test_https_obligatorio_sigue_rechazando_sin_conectar(self):
        lease = LeaseEscritorOperativo(base_url="http://cloud.test", token_motor=TOKEN_MOTOR,
                                       escritor_id="casa-1", heartbeat_segundos=0)
        with self.assertLogs("atlas_core.escritor_operativo", level=logging.WARNING), \
                patch("urllib.request.urlopen") as urlopen:
            self.assertFalse(lease.adquirir())
        urlopen.assert_not_called()
        self.assertEqual(lease.motivo, "CLOUD_NO_DISPONIBLE")


class RespuestaInesperadaTests(unittest.TestCase):
    def _adquirir(self, respuesta_adquirir: dict):
        api = ApiRegistrada(estado=lambda _b: {"vigente": False, "epoca": 0},
                            adquirir=lambda _b: respuesta_adquirir)
        lease = _lease()
        with self.assertLogs("atlas_core.escritor_operativo", level=logging.WARNING) as registros, \
                patch("atlas_core.escritor_operativo._json", side_effect=api):
            self.assertFalse(lease.adquirir())
        return lease, "\n".join(registros.output), api

    def test_estado_distinto_de_adquirido_no_expone_el_lease(self):
        lease, texto, api = self._adquirir({"estado": "RARO", "lease_token": LEASE_SECRETO, "epoca": 9})
        self.assertEqual(lease.motivo, "RESPUESTA_CLOUD_INVALIDA")
        self.assertIn("'RARO'", texto)
        self.assertIn("presente", texto)
        self.assertNotIn(LEASE_SECRETO, texto)
        self.assertNotIn(TOKEN_MOTOR, texto)
        # Comportamiento previo intacto: no toma el token, no libera, no late.
        self.assertEqual(lease.lease_token, "")
        self.assertFalse(lease.vigente)
        self.assertFalse(lease.ocupado)
        self.assertEqual(api.rutas, ["/api/motor/escritor/estado", "/api/motor/escritor/adquirir"])

    def test_adquirido_sin_token_es_respuesta_invalida(self):
        lease, texto, _ = self._adquirir({"estado": "ADQUIRIDO", "epoca": 9})
        self.assertEqual(lease.motivo, "RESPUESTA_CLOUD_INVALIDA")
        self.assertIn("ausente", texto)
        self.assertFalse(lease.vigente)


class PerdidaEnRelevoTests(unittest.TestCase):
    def test_lease_perdido_durante_el_margen_libera_y_registra_motivo(self):
        token = {"valor": ""}

        def adquirir(_b):
            token["valor"] = LEASE_SECRETO
            return {"estado": "ADQUIRIDO", "lease_token": LEASE_SECRETO, "epoca": 8}

        def liberar(body):
            self.assertEqual(body["lease_token"], LEASE_SECRETO)
            token["valor"] = ""
            return {"estado": "LIBERADO"}

        api = ApiRegistrada(estado=lambda _b: {"vigente": False, "epoca": 7}, adquirir=adquirir, liberar=liberar)
        esperas: list[float] = []
        with tempfile.TemporaryDirectory() as temporal:
            ruta_relevo = Path(temporal) / "relevo.json"
            lease = _lease(margen_relevo_segundos=30, ruta_relevo=ruta_relevo)

            def dormir(segundos):
                esperas.append(segundos)
                lease._perdido.set()  # el heartbeat no pudo renovar durante la espera

            lease._dormir = dormir
            with self.assertLogs("atlas_core.escritor_operativo", level=logging.WARNING) as registros, \
                    patch("atlas_core.escritor_operativo._json", side_effect=api):
                self.assertFalse(lease.adquirir())
            texto = "\n".join(registros.output)
            self.assertFalse(ruta_relevo.exists(), "un lease perdido no deja constancia de relevo")
        self.assertEqual(esperas, [30])
        self.assertEqual(lease.motivo, "LEASE_PERDIDO_EN_RELEVO")
        self.assertIn("época 8", texto)
        self.assertNotIn(LEASE_SECRETO, texto)
        self.assertFalse(lease.ocupado)
        self.assertFalse(lease.vigente)
        self.assertEqual(lease.lease_token, "")
        # Igual que antes: se intenta liberar el lease tomado.
        self.assertEqual(api.rutas, ["/api/motor/escritor/estado", "/api/motor/escritor/adquirir",
                                     "/api/motor/escritor/liberar"])


class MotivosExistentesIntactosTests(unittest.TestCase):
    def _http_409(self, codigo_cloud: str):
        def abrir(request, timeout=0):
            if request.full_url.endswith("/estado"):
                return _respuesta(b'{"vigente": true, "epoca": 3}')
            cuerpo = json.dumps({"error": codigo_cloud}).encode()
            raise urllib.error.HTTPError(request.full_url, 409, "x", {}, _respuesta(cuerpo))
        return abrir

    def test_409_conserva_motivos_y_ocupado(self):
        casos = {"ESCRITOR_OCUPADO": ("ESCRITOR_OCUPADO", True),
                 "ESCRITOR_PRIORIDAD": ("PRIORIDAD_OTRO_EQUIPO", False)}
        for codigo_cloud, (motivo, ocupado) in casos.items():
            with self.subTest(codigo=codigo_cloud), patch("urllib.request.urlopen", side_effect=self._http_409(codigo_cloud)):
                lease = _lease()
                self.assertFalse(lease.adquirir())
                self.assertEqual(lease.motivo, motivo)
                self.assertEqual(lease.ocupado, ocupado)

    def test_adquisicion_correcta_deja_motivo_vacio_tras_un_fallo_previo(self):
        lease = _lease()
        with self.assertLogs("atlas_core.escritor_operativo", level=logging.WARNING), \
                patch("urllib.request.urlopen", side_effect=urllib.error.URLError("sin red")):
            self.assertFalse(lease.adquirir())
        self.assertEqual(lease.motivo, "CLOUD_NO_DISPONIBLE")
        api = ApiRegistrada(
            estado=lambda _b: {"vigente": False, "epoca": 0},
            adquirir=lambda _b: {"estado": "ADQUIRIDO", "lease_token": "tok", "epoca": 1},
            liberar=lambda _b: {"estado": "LIBERADO"},
        )
        with tempfile.TemporaryDirectory() as temporal, patch("atlas_core.escritor_operativo._json", side_effect=api):
            lease.ruta_relevo = Path(temporal) / "relevo.json"
            self.assertTrue(lease.adquirir())
            self.assertEqual(lease.motivo, "")
            self.assertTrue(lease.vigente)
            lease.cerrar()


class PullConMotivoTests(unittest.TestCase):
    """El PULL publica el motivo nuevo y conserva la salida 1."""

    def _argumentos(self):
        return {
            "base_url": "https://cloud.test", "token_motor": TOKEN_MOTOR, "consumidor": "pc-prueba",
            "repositorio": object(), "timeout": 1, "procesar": True, "dataset": None,
            "carpeta_catalogos": None,
        }

    def test_pull_sin_red_informa_cloud_no_disponible_sin_reclamar_envios(self):
        from sincronizar_mobile_cloud import ejecutar_pull_con_escritor
        with self.assertLogs("atlas_core.escritor_operativo", level=logging.WARNING), \
                patch("urllib.request.urlopen", side_effect=urllib.error.URLError("sin red")), \
                patch("sincronizar_mobile_cloud.sincronizar_envios_cloud") as pull:
            resultado = ejecutar_pull_con_escritor(
                **self._argumentos(),
                fabrica_escritor=lambda **kw: LeaseEscritorOperativo(escritor_id="casa-1", heartbeat_segundos=0, **kw),
            )
        pull.assert_not_called()
        self.assertEqual(resultado, {"escritor_operativo": "NO_ADQUIRIDO", "motivo": "CLOUD_NO_DISPONIBLE",
                                     "encontrados": 0, "confirmados": []})

    def test_main_conserva_salida_1_con_motivos_nuevos(self):
        import sincronizar_mobile_cloud as cli
        for motivo in ("CLOUD_NO_DISPONIBLE", "RESPUESTA_CLOUD_INVALIDA", "LEASE_PERDIDO_EN_RELEVO"):
            resultado = {"escritor_operativo": "NO_ADQUIRIDO", "motivo": motivo, "encontrados": 0, "confirmados": []}
            with self.subTest(motivo=motivo), tempfile.TemporaryDirectory() as raiz, \
                    patch.dict(os.environ, {"ATLAS_CLOUD_MOTOR_TOKEN": TOKEN_MOTOR}, clear=False), \
                    patch("sys.argv", ["sincronizar_mobile_cloud.py", "--raiz-atlas", raiz]), \
                    patch("atlas_core.exclusividad_equipo.politica_equipo_unico", return_value=None), \
                    patch("atlas_core.aislamiento_empresas.exigir_raiz_de_proceso"), \
                    patch("sincronizar_mobile_cloud.resolver_preferencia_ocr_desde_entorno", return_value="rapidocr"), \
                    patch("sincronizar_mobile_cloud.leer_estado_operacion", return_value={}), \
                    patch("sincronizar_mobile_cloud.validar_fuente_catalogos", side_effect=cli.ErrorFuenteCatalogos("x")), \
                    patch("sincronizar_mobile_cloud.RepositorioEnviosMobile"), \
                    patch("sincronizar_mobile_cloud.ejecutar_pull_con_escritor", return_value=resultado), \
                    patch("sys.stdout", new_callable=io.StringIO):
                with self.assertRaises(SystemExit) as salida:
                    cli.main()
                self.assertEqual(salida.exception.code, 1)


if __name__ == "__main__":
    unittest.main()
