from __future__ import annotations

import unittest
from unittest.mock import patch

from sincronizar_mobile_cloud import ejecutar_pull_con_escritor


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
        self.assertTrue(pull.call_args.kwargs["puede_continuar"]())
        self.assertTrue(escritor.cerrado)

    def test_lease_ocupado_no_ejecuta_pull_ni_reclama_envios(self):
        escritor = EscritorFalso(adquirido=False)
        with patch("sincronizar_mobile_cloud.sincronizar_envios_cloud") as pull:
            resultado = ejecutar_pull_con_escritor(**self._argumentos(), fabrica_escritor=lambda **_kwargs: escritor)
        self.assertEqual(resultado["escritor_operativo"], "NO_ADQUIRIDO")
        pull.assert_not_called()
        self.assertTrue(escritor.cerrado)
