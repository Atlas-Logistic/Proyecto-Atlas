from __future__ import annotations

import hashlib
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from atlas_core.cloud_mobile_sync_cliente import ErrorSincronizacionCloudMobile, sincronizar_envios_cloud
from atlas_core.mobile import ErrorEnvioMobile


BYTES = b"jpeg-cloud-prueba"
SHA = hashlib.sha256(BYTES).hexdigest()


class Repo:
    def __init__(self, falla=False): self.registros, self.falla, self.por_id = [], falla, {}
    def recibir(self, **kwargs):
        if self.falla: raise ErrorEnvioMobile("disco local falló")
        self.registros.append(kwargs)
        self.por_id.setdefault(kwargs["envio_id"], {"envio_id": kwargs["envio_id"], "estado": "RECIBIDO"})
        return self.por_id[kwargs["envio_id"]], True
    def cargar(self, envio_id): return dict(self.por_id[envio_id])
    def guardar(self, envio_id, registro): self.por_id[envio_id] = dict(registro)
    def historial(self): return list(self.por_id.values())


def lease(**extra):
    salida = {"envio_id": "envio-1", "documento_id": "doc_envio-1", "empresa_id": "empresa-prueba-javier", "chofer_id": "chofer-1", "observacion": "observación Cloud", "imagen_mime": "image/jpeg", "imagen_bytes": len(BYTES), "imagen_sha256": SHA, "descarga_url": "https://cloud.test/api/motor/documentos/doc_envio-1?token=x", "lease_token": "lease-1", "planta_origen_informada": "AZA_COLINA", "tipo_novedad": "", "guia_firmada_correo": False, "capturado_en": "", "lote_id": ""}
    salida.update(extra)
    return salida


class CloudMobileSyncTests(unittest.TestCase):
    def ejecutar(self, repo, datos_lease=None, descarga=BYTES, procesar=False, resultado_procesamiento=None, renovar_falla=False):
        confirmaciones = []
        def falso_json(base, ruta, token, **kwargs):
            if ruta.endswith("pendientes"): return {"envios": [{"envio_id": "envio-1"}]}
            if ruta.endswith("/renovar"):
                if renovar_falla: raise ErrorSincronizacionCloudMobile("lease vencido")
                return {"estado": "EN_LEASE"}
            if ruta.endswith("/lease"): return datos_lease or lease()
            if ruta.endswith("/confirmar"):
                confirmaciones.append(kwargs["body"])
                return {"estado": "COMPLETADO"}
            raise AssertionError(ruta)
        with patch("atlas_core.cloud_mobile_sync_cliente._json", side_effect=falso_json), patch("atlas_core.cloud_mobile_sync_cliente._descargar", return_value=descarga), patch("atlas_core.cloud_mobile_sync_cliente._procesar_envio_cloud", return_value=resultado_procesamiento or {"completado": True}):
            resultado = sincronizar_envios_cloud(base_url="https://cloud.test", token_motor="independiente", consumidor="motor-prueba", repositorio=repo, timeout=1, procesar=procesar)
        return resultado, confirmaciones

    def test_pendiente_se_confirma_solo_tras_exito_operacional(self):
        repo = Repo()
        resultado, confirmaciones = self.ejecutar(repo, procesar=True)
        self.assertEqual(resultado["confirmados"], ["envio-1"])
        self.assertEqual(confirmaciones, [{"lease_token": "lease-1"}])
        self.assertEqual(repo.registros[0]["metadata"]["observacion"], "observación Cloud")
        self.assertEqual(repo.registros[0]["metadata"]["empresa_id"], "empresa-prueba-javier")
        self.assertEqual(repo.cargar("envio-1")["cloud_procesamiento"]["estado"], "RECONCILIADO")

    def test_sin_procesar_aterriza_pero_no_confirma(self):
        resultado, confirmaciones = self.ejecutar(Repo())
        self.assertEqual(resultado["persistidos"], ["envio-1"])
        self.assertEqual(confirmaciones, [])

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
        resultado, confirmaciones = self.ejecutar(Repo(), procesar=True)
        self.assertEqual(resultado["confirmados"], ["envio-1"])
        self.assertEqual(len(confirmaciones), 1)

    def test_exige_https(self):
        with self.assertRaisesRegex(Exception, "HTTPS"):
            sincronizar_envios_cloud(base_url="http://no-seguro", token_motor="x", consumidor="motor", repositorio=Repo())

    def test_reconciliacion_incompleta_no_confirma(self):
        resultado, confirmaciones = self.ejecutar(
            Repo(), procesar=True, resultado_procesamiento={"completado": False, "error": "reconciliación operacional no terminada"},
        )
        self.assertEqual(confirmaciones, [])
        self.assertIn("envio-1", resultado["errores_procesamiento"])

    def test_lease_perdido_no_confirma(self):
        resultado, confirmaciones = self.ejecutar(Repo(), procesar=True, renovar_falla=True)
        self.assertEqual(confirmaciones, [])
        self.assertIn("envio-1", resultado["fallidos"])

    def test_escritor_no_vigente_no_reclama_ni_escribe(self):
        with patch("atlas_core.cloud_mobile_sync_cliente._json", side_effect=AssertionError("no debe consultar ni reclamar Cloud")):
            resultado = sincronizar_envios_cloud(
                base_url="https://cloud.test", token_motor="t", consumidor="motor", repositorio=Repo(),
                procesar=True, puede_continuar=lambda: False,
            )
        self.assertTrue(resultado["detenido_por_escritor"])
        self.assertEqual(resultado["leaseados"], [])
        self.assertEqual(resultado["persistidos"], [])

    def test_perdida_de_escritor_durante_procesamiento_no_confirma(self):
        activo = {"valor": True}
        confirmaciones = []
        def falso_json(_base, ruta, _token, **_kwargs):
            if ruta.endswith("pendientes"): return {"envios": [{"envio_id": "envio-1"}]}
            if ruta.endswith("/lease"): return lease()
            if ruta.endswith("/renovar"): return {"estado": "EN_LEASE"}
            if ruta.endswith("/confirmar"):
                confirmaciones.append(ruta); return {"estado": "COMPLETADO"}
            raise AssertionError(ruta)
        def procesamiento(*_args, **_kwargs):
            activo["valor"] = False
            return {"completado": True}
        with patch("atlas_core.cloud_mobile_sync_cliente._json", side_effect=falso_json), \
             patch("atlas_core.cloud_mobile_sync_cliente._descargar", return_value=BYTES), \
             patch("atlas_core.cloud_mobile_sync_cliente._procesar_envio_cloud", side_effect=procesamiento):
            resultado = sincronizar_envios_cloud(
                base_url="https://cloud.test", token_motor="t", consumidor="motor", repositorio=Repo(),
                procesar=True, puede_continuar=lambda: activo["valor"],
            )
        self.assertEqual(confirmaciones, [])
        self.assertTrue(resultado["detenido_por_escritor"])

    def test_renueva_lease_durante_procesamiento_largo(self):
        renovaciones = []
        def falso_json(_base, ruta, _token, **_kwargs):
            if ruta.endswith("pendientes"): return {"envios": [{"envio_id": "envio-1"}]}
            if ruta.endswith("/lease"): return lease()
            if ruta.endswith("/renovar"):
                renovaciones.append(ruta); return {"estado": "EN_LEASE"}
            if ruta.endswith("/confirmar"): return {"estado": "COMPLETADO"}
            raise AssertionError(ruta)
        with patch("atlas_core.cloud_mobile_sync_cliente._json", side_effect=falso_json), \
             patch("atlas_core.cloud_mobile_sync_cliente._descargar", return_value=BYTES), \
             patch("atlas_core.cloud_mobile_sync_cliente._procesar_envio_cloud", side_effect=lambda *_a, **_k: (time.sleep(0.04) or {"completado": True})):
            resultado = sincronizar_envios_cloud(
                base_url="https://cloud.test", token_motor="t", consumidor="motor", repositorio=Repo(),
                procesar=True, lease_heartbeat_segundos=0.01,
            )
        self.assertEqual(resultado["confirmados"], ["envio-1"])
        self.assertGreaterEqual(len(renovaciones), 2)


# ---------------------------------------------------------------- Mobile 24/7
# Runner cloud + procesamiento: repositorio REAL en tmp, dataset aislado y
# OCR simulado (nunca G:\ ni OCR real).
import csv  # noqa: E402

from atlas_core import mobile  # noqa: E402
from atlas_core.almacenamiento_portable import SesionOcupadaError  # noqa: E402
from atlas_core.mobile import RepositorioEnviosMobile  # noqa: E402
from atlas_core.procesamiento_masivo import COLUMNAS  # noqa: E402

ENVIO_REAL = "8f0f3c1e-9b1a-4c55-9d9e-24b7c0a1e001"


class CloudMobileRunnerProcesamientoTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.raiz = Path(self.tmp.name)
        self.dataset = self.raiz / "operacion" / "actual" / "analisis_completo_guias.csv"
        self.dataset.parent.mkdir(parents=True)
        with self.dataset.open("w", newline="", encoding="utf-8-sig") as archivo:
            escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
            escritor.writeheader()
            escritor.writerow({**{c: "" for c in COLUMNAS}, "archivo": "previo.jpg", "numero_guia": "700001", "numero_transporte": "0000800001"})
        self.repo = RepositorioEnviosMobile(self.raiz)
        self.ocr = []
        def ocr_simulado(ruta, **_kwargs):
            self.ocr.append(Path(ruta).parent.name)
            return {"numero_guia": "900001", "numero_transporte": "0000800001"}
        self.parches = [patch.object(mobile, "procesar_archivo", ocr_simulado), patch.object(mobile, "crear_proveedor_ocr", lambda: object())]
        for p in self.parches: p.start()

    def tearDown(self):
        for p in self.parches: p.stop()
        self.tmp.cleanup()

    def pull(self, *, pendientes=True, procesar=True):
        confirmaciones = []
        def falso_json(base, ruta, token, **kwargs):
            if ruta.endswith("pendientes"): return {"envios": [{"envio_id": ENVIO_REAL}] if pendientes else []}
            if ruta.endswith("/renovar"): return {"estado": "EN_LEASE"}
            if ruta.endswith("/lease"): return lease(envio_id=ENVIO_REAL, documento_id=f"doc_{ENVIO_REAL}", tipo_novedad="DOBLE_VUELTA")
            if ruta.endswith("/confirmar"):
                confirmaciones.append(ruta); return {"estado": "COMPLETADO"}
            raise AssertionError(ruta)
        with patch("atlas_core.cloud_mobile_sync_cliente._json", side_effect=falso_json), patch("atlas_core.cloud_mobile_sync_cliente._descargar", return_value=BYTES):
            resultado = sincronizar_envios_cloud(base_url="https://cloud.test", token_motor="t", consumidor="motor-prueba", repositorio=self.repo,
                                                 timeout=1, procesar=procesar, dataset=self.dataset, carpeta_catalogos=None)
        return resultado, confirmaciones

    def filas(self):
        with self.dataset.open(encoding="utf-8-sig", newline="") as archivo:
            return list(csv.DictReader(archivo, delimiter=";"))

    def test_envio_cloud_se_procesa_con_el_mismo_flujo_que_lan(self):
        resultado, confirmaciones = self.pull()
        self.assertEqual(resultado["confirmados"], [ENVIO_REAL])
        self.assertEqual(resultado["procesados"], [ENVIO_REAL])
        self.assertEqual(self.ocr, [ENVIO_REAL])
        self.assertEqual(self.repo.cargar(ENVIO_REAL)["estado"], "ASOCIADO")
        self.assertEqual(len(self.filas()), 2)

    def test_idempotente_reenvio_de_cloud_no_duplica_ni_reprocesa(self):
        self.pull()
        resultado, confirmaciones = self.pull()  # Cloud lo vuelve a listar (p. ej. confirmación perdida)
        self.assertEqual(resultado["confirmados"], [ENVIO_REAL])
        self.assertEqual(resultado["procesados"], [])
        self.assertEqual(self.ocr, [ENVIO_REAL])
        self.assertEqual(len(self.filas()), 2)

    def test_corrida_interrumpida_se_retoma_en_la_siguiente(self):
        self.pull(procesar=False)  # aterrizó sin confirmar; Cloud podrá ofrecerlo al vencer el lease
        self.assertEqual(self.repo.cargar(ENVIO_REAL)["estado"], "RECIBIDO")
        resultado, confirmaciones = self.pull(pendientes=False)
        self.assertEqual(confirmaciones, [])
        self.assertEqual(resultado["procesados"], [ENVIO_REAL])
        self.assertEqual(self.repo.cargar(ENVIO_REAL)["estado"], "ASOCIADO")

    def test_envio_tomado_por_otro_consumidor_se_omite(self):
        with patch("atlas_core.cloud_mobile_sync_cliente.procesar_y_revalidar_envio_mobile", side_effect=SesionOcupadaError("ocupado")):
            resultado, _ = self.pull()
        self.assertEqual(resultado["omitidos_por_bloqueo"], [ENVIO_REAL])
        self.assertEqual(self.repo.cargar(ENVIO_REAL)["estado"], "RECIBIDO")

    def test_procesando_interrumpido_reintenta_sin_duplicar_dataset(self):
        self.pull()
        self.assertEqual(len(self.filas()), 2)
        registro = self.repo.cargar(ENVIO_REAL)
        registro["estado"] = "PROCESANDO"
        registro["cloud_procesamiento"]["estado"] = "ATERRIZADO"
        self.repo.guardar(ENVIO_REAL, registro)
        resultado, _ = self.pull(pendientes=False)
        self.assertEqual(resultado["procesados"], [ENVIO_REAL])
        self.assertEqual(self.repo.cargar(ENVIO_REAL)["estado"], "ASOCIADO")
        self.assertEqual(len(self.filas()), 2)

    def test_error_funcional_no_se_reprocesa_ni_confirma(self):
        self.pull(procesar=False)
        registro = self.repo.cargar(ENVIO_REAL)
        registro["estado"] = "ERROR"
        self.repo.guardar(ENVIO_REAL, registro)
        resultado, confirmaciones = self.pull()
        self.assertEqual(confirmaciones, [])
        self.assertEqual(self.ocr, [])
        self.assertIn(ENVIO_REAL, resultado["errores_procesamiento"])

    def test_sin_procesar_por_defecto_no_confirma(self):
        with patch("atlas_core.cloud_mobile_sync_cliente._json", side_effect=lambda b, r, t, **k: {"envios": []}):
            resultado = sincronizar_envios_cloud(base_url="https://cloud.test", token_motor="t", consumidor="m", repositorio=self.repo)
        self.assertEqual(resultado["procesados"], [])
