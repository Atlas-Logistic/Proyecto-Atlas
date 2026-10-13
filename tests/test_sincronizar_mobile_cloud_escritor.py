from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from sincronizar_mobile_cloud import ejecutar_pull_con_escritor, main


class EscritorFalso:
    def __init__(self, *, adquirido: bool):
        self.adquirido = adquirido
        self.vigente = adquirido
        self.cerrado = False

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.cerrado = True

    def adquirir(self):
        return self.adquirido


class PullConEscritorTests(unittest.TestCase):
    def _argumentos(self):
        return {
            "base_url": "https://cloud.test", "token_motor": "t", "consumidor": "pc-prueba",
            "repositorio": object(), "timeout": 1, "procesar": True, "dataset": None,
            "carpeta_catalogos": None,
        }

    def test_lease_obtenido_permite_pull_y_libera_al_terminar(self):
        escritor = EscritorFalso(adquirido=True)
        with patch("sincronizar_mobile_cloud.sincronizar_envios_cloud", return_value={"confirmados": []}) as pull:
            resultado = ejecutar_pull_con_escritor(**self._argumentos(), fabrica_escritor=lambda **_kwargs: escritor)
        self.assertEqual(resultado, {"confirmados": []})
        self.assertEqual(pull.call_count, 1)

    def test_preferencia_ocr_se_propaga_al_pull(self):
        escritor = EscritorFalso(adquirido=True)
        with patch("sincronizar_mobile_cloud.sincronizar_envios_cloud", return_value={"confirmados": []}) as pull:
            ejecutar_pull_con_escritor(
                **self._argumentos(), proveedor_ocr_preferido="easyocr",
                fabrica_escritor=lambda **_kwargs: escritor,
            )
        self.assertEqual(pull.call_args.kwargs["proveedor_ocr_preferido"], "easyocr")
        self.assertTrue(pull.call_args.kwargs["puede_continuar"]())
        self.assertTrue(escritor.cerrado)

    def test_lease_ocupado_no_ejecuta_pull_ni_reclama_envios(self):
        escritor = EscritorFalso(adquirido=False)
        with patch("sincronizar_mobile_cloud.sincronizar_envios_cloud") as pull:
            resultado = ejecutar_pull_con_escritor(**self._argumentos(), fabrica_escritor=lambda **_kwargs: escritor)
        self.assertEqual(resultado["escritor_operativo"], "NO_ADQUIRIDO")
        pull.assert_not_called()
        self.assertTrue(escritor.cerrado)

    def test_proveedor_invalido_falla_antes_de_iniciar_el_pull(self):
        entorno = {"ATLAS_CLOUD_MOTOR_TOKEN": "token-prueba", "ATLAS_OCR_PROVIDER": "otro"}
        with (
            patch.dict(os.environ, entorno, clear=False),
            patch("sys.argv", ["sincronizar_mobile_cloud.py"]),
            patch("sincronizar_mobile_cloud.ejecutar_pull_con_escritor") as pull,
        ):
            with self.assertRaises(SystemExit) as salida:
                main()
        self.assertEqual(salida.exception.code, 2)
        pull.assert_not_called()
