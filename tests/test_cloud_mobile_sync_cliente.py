from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from atlas_core.cloud_mobile_sync_cliente import sincronizar_envios_cloud
from atlas_core.mobile import ErrorEnvioMobile


BYTES = b"jpeg-cloud-prueba"
SHA = hashlib.sha256(BYTES).hexdigest()


class Repo:
    def __init__(self, falla=False): self.registros, self.falla = [], falla
    def recibir(self, **kwargs):
        if self.falla: raise ErrorEnvioMobile("disco local falló")
        self.registros.append(kwargs)
        return {}, True


def lease(**extra):
    salida = {"envio_id": "envio-1", "documento_id": "doc_envio-1", "empresa_id": "empresa-prueba-javier", "chofer_id": "chofer-1", "observacion": "observación Cloud", "imagen_mime": "image/jpeg", "imagen_bytes": len(BYTES), "imagen_sha256": SHA, "descarga_url": "https://cloud.test/api/motor/documentos/doc_envio-1?token=x", "lease_token": "lease-1", "planta_origen_informada": "AZA_COLINA", "tipo_novedad": "", "guia_firmada_correo": False, "capturado_en": "", "lote_id": ""}
    salida.update(extra)
    return salida


class CloudMobileSyncTests(unittest.TestCase):
    def ejecutar(self, repo, datos_lease=None, descarga=BYTES):
        confirmaciones = []
        def falso_json(base, ruta, token, **kwargs):
            if ruta.endswith("pendientes"): return {"envios": [{"envio_id": "envio-1"}]}
            if ruta.endswith("/lease"): return datos_lease or lease()
            if ruta.endswith("/confirmar"):
                confirmaciones.append(kwargs["body"])
                return {"estado": "COMPLETADO"}
            raise AssertionError(ruta)
        with patch("atlas_core.cloud_mobile_sync_cliente._json", side_effect=falso_json), patch("atlas_core.cloud_mobile_sync_cliente._descargar", return_value=descarga):
            resultado = sincronizar_envios_cloud(base_url="https://cloud.test", token_motor="independiente", consumidor="motor-prueba", repositorio=repo, timeout=1)
        return resultado, confirmaciones

    def test_pendiente_lease_descarga_persistencia_confirmacion_y_observacion(self):
        repo = Repo()
        resultado, confirmaciones = self.ejecutar(repo)
        self.assertEqual(resultado["confirmados"], ["envio-1"])
        self.assertEqual(confirmaciones, [{"lease_token": "lease-1"}])
        self.assertEqual(repo.registros[0]["metadata"]["observacion"], "observación Cloud")
        self.assertEqual(repo.registros[0]["metadata"]["empresa_id"], "empresa-prueba-javier")

    def test_sha_o_tamano_incorrecto_no_confirman(self):
        repo = Repo()
        resultado, confirmaciones = self.ejecutar(repo, descarga=b"corrupto")
        self.assertEqual(confirmaciones, [])
        self.assertIn("envio-1", resultado["fallidos"])
        resultado, confirmaciones = self.ejecutar(Repo(), datos_lease=lease(imagen_bytes=len(BYTES) + 1))
        self.assertEqual(confirmaciones, [])
        self.assertIn("envio-1", resultado["fallidos"])

    def test_fallo_local_no_confirma_y_reintento_es_seguro(self):
        resultado, confirmaciones = self.ejecutar(Repo(falla=True))
        self.assertEqual(confirmaciones, [])
        self.assertIn("envio-1", resultado["fallidos"])
        resultado, confirmaciones = self.ejecutar(Repo())
        self.assertEqual(resultado["confirmados"], ["envio-1"])
        self.assertEqual(len(confirmaciones), 1)

    def test_exige_https(self):
        with self.assertRaisesRegex(Exception, "HTTPS"):
            sincronizar_envios_cloud(base_url="http://no-seguro", token_motor="x", consumidor="motor", repositorio=Repo())
