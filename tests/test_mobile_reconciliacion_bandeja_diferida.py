"""P0 BLOQUEO MOBILE (08-10-2026, envío real 35f58c4e).

`reconciliar_bandeja_decisiones` (pasada GLOBAL: bandeja completa +
escaneo de `reportes/*/viajes.csv`) corría DENTRO del cierre de cada envío
Mobile; sobre G: en streaming tardó horas y retuvo el envio.json, el
reporte, la confirmación Cloud y toda la cola PULL.

Contrato verificado aquí: en el consumidor Cloud el envío se cierra y se
confirma SIN esperar esa pasada; la pasada queda PENDIENTE de forma
persistida y corre UNA vez al final del ciclo; sólo se marca COMPLETADA si
realmente corrió; un fallo la deja PENDIENTE para el ciclo siguiente; la
bandeja final es la misma que con el comportamiento previo."""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from atlas_core import mobile
from atlas_core.catalogo_plantas import CatalogoPlantas, EstadoCalidad
from atlas_core.cloud_mobile_sync_cliente import sincronizar_envios_cloud
from atlas_core.mobile import RepositorioEnviosMobile, procesar_envio_mobile, reconciliar_bandeja_diferida_mobile
from atlas_core.procesamiento_masivo import COLUMNAS

ENVIO = "35f58c4e-0000-4000-8000-000000000001"
BYTES = b"jpeg-reconciliacion-diferida"
SHA = hashlib.sha256(BYTES).hexdigest()
METADATA = {"chofer_id": "c1", "planta_origen_informada": "AZA_COLINA"}

OCR_CON_DECISION = {
    "numero_guia": "700001", "numero_transporte": "0000700000",
    "indicador_revision": "REVISAR", "tipo_carga": "NO DETERMINADO",
    "estado_ruta": "ORIGEN_NO_DETERMINADO",
    "motivo_ruta": "CONTRADICCION_OPERACIONAL_ORIGEN[MOBILE=AZA_COLINA:INCOMPATIBLE]",
    "planta_origen_id": "", "planta_origen_nombre": "",
}


class Entorno:
    def __init__(self, raiz: Path, monkeypatch: pytest.MonkeyPatch, ocr: dict[str, str], *, reconciliador_real: bool = False):
        monkeypatch.setenv("ATLAS_IA_B1_OPERACIONAL", "0")
        monkeypatch.setenv("ATLAS_CACHE_DIR", str(raiz / "_cache"))
        self.raiz = raiz
        self.dataset = raiz / "operacion" / "actual" / "analisis_completo_guias.csv"
        self.dataset.parent.mkdir(parents=True)
        with self.dataset.open("w", newline="", encoding="utf-8-sig") as archivo:
            csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";").writeheader()
        self.catalogos = raiz / "catalogos"
        CatalogoPlantas(self.catalogos / "plantas.json").crear(
            nombre="AZA COLINA", pais="CHILE", fuente="TEST", estado_calidad=EstadoCalidad.CONFIRMADA,
            categorias_permitidas=("BARRAS",),
        )
        self.repo = RepositorioEnviosMobile(raiz)
        self.eventos: list[str] = []  # orden observable: confirmación Cloud vs reconciliación global
        self.reconciliaciones: list[dict[str, object]] = []
        self.publicadas: list[tuple[str, str]] = []  # decisiones que el envío publicó al procesarse
        self.falla_reconciliacion = False

        def ocr_simulado(ruta, **_kwargs):
            return dict(ocr)

        def reconciliador(*, raiz_atlas, **_kwargs):
            self.eventos.append("reconciliacion")
            existe = (self.repo.raiz / ENVIO / "envio.json").is_file()
            self.reconciliaciones.append({
                "raiz": Path(raiz_atlas), "estado_envio": self.repo.cargar(ENVIO)["estado"] if existe else None,
            })
            if self.falla_reconciliacion:
                raise RuntimeError("G: no responde")
            return {"decisiones_aplicadas_automaticamente": []}

        publicar_original = mobile._generar_artefacto_sin_lock

        def publicar_espia(**kwargs):
            self.publicadas.extend((d["tipo"], d.get("documento", {}).get("numero_guia", "")) for d in kwargs["decisiones"])
            return publicar_original(**kwargs)

        monkeypatch.setattr(mobile, "procesar_archivo", ocr_simulado)
        monkeypatch.setattr(mobile, "crear_proveedor_ocr", lambda: object())
        monkeypatch.setattr(mobile, "_generar_artefacto_sin_lock", publicar_espia)
        if not reconciliador_real:
            monkeypatch.setattr("atlas_core.revalidacion_documental.reconciliar_bandeja_decisiones", reconciliador)

    def pull(self, *, pendientes: bool = True) -> dict:
        def falso_json(base, ruta, token, **kwargs):
            if ruta.endswith("pendientes"):
                return {"envios": [{"envio_id": ENVIO}] if pendientes else []}
            if ruta.endswith("/renovar"):
                return {"estado": "EN_LEASE"}
            if ruta.endswith("/lease"):
                return {
                    "envio_id": ENVIO, "documento_id": f"doc_{ENVIO}", "empresa_id": "empresa-prueba",
                    "chofer_id": "chofer-1", "observacion": "", "imagen_mime": "image/jpeg",
                    "imagen_bytes": len(BYTES), "imagen_sha256": SHA,
                    "descarga_url": "https://cloud.test/doc", "lease_token": "lease-1",
                    "planta_origen_informada": "AZA_COLINA", "tipo_novedad": "",
                    "guia_firmada_correo": False, "capturado_en": "", "lote_id": "",
                }
            if ruta.endswith("/confirmar"):
                self.eventos.append("confirmacion")
                return {"estado": "COMPLETADO"}
            raise AssertionError(ruta)

        with patch("atlas_core.cloud_mobile_sync_cliente._json", side_effect=falso_json), \
                patch("atlas_core.cloud_mobile_sync_cliente._descargar", return_value=BYTES):
            return sincronizar_envios_cloud(
                base_url="https://cloud.test", token_motor="t", consumidor="motor-prueba",
                repositorio=self.repo, timeout=1, procesar=True,
                dataset=self.dataset, carpeta_catalogos=self.catalogos,
            )

    def filas_envio(self) -> list[dict[str, str]]:
        with self.dataset.open(encoding="utf-8-sig", newline="") as archivo:
            return [f for f in csv.DictReader(archivo, delimiter=";") if ENVIO in f.get("archivo", "")]

    def solicitud(self) -> dict:
        return self.repo.cargar(ENVIO).get("reconciliacion_bandeja") or {}

    def bandeja(self) -> list[tuple[str, str, str]]:
        ruta = self.dataset.parent / "decisiones_pendientes.json"
        if not ruta.is_file():
            return []
        return sorted(
            (d["tipo"], d.get("documento", {}).get("numero_guia", ""), d.get("decision_id", ""))
            for d in json.loads(ruta.read_text(encoding="utf-8"))["decisiones"]
        )


def _con_planta_del_entorno(entorno: Entorno, ocr: dict[str, str]) -> None:
    if "planta_origen_nombre" in ocr and ocr.get("origen_determinado_por"):
        ocr["planta_origen_id"] = CatalogoPlantas(entorno.catalogos / "plantas.json").listar()[0].planta_id


def _bandeja_final_sin_diferir(raiz: Path, monkeypatch: pytest.MonkeyPatch, ocr: dict[str, str]) -> list[tuple[str, str, str]]:
    """Mismo pull con el comportamiento previo (reconciliación dentro del cierre)."""
    from atlas_core import cloud_mobile_sync_cliente
    original = cloud_mobile_sync_cliente.procesar_y_revalidar_envio_mobile
    with monkeypatch.context() as m:
        m.setattr(
            cloud_mobile_sync_cliente, "procesar_y_revalidar_envio_mobile",
            lambda *a, diferir_reconciliacion_bandeja=False, **k: original(*a, **k),
        )
        referencia = Entorno(raiz, m, ocr)
        _con_planta_del_entorno(referencia, ocr)
        referencia.pull()
        assert referencia.eventos == ["reconciliacion", "confirmacion"]  # orden previo
        return referencia.bandeja()


def test_envio_con_decision_se_cierra_y_confirma_antes_de_la_reconciliacion_global(tmp_path, monkeypatch):
    esperado = _bandeja_final_sin_diferir(tmp_path / "previo", monkeypatch, OCR_CON_DECISION)
    entorno = Entorno(tmp_path / "diferido", monkeypatch, OCR_CON_DECISION)

    resultado = entorno.pull()

    assert resultado["confirmados"] == [ENVIO]
    registro = entorno.repo.cargar(ENVIO)
    assert registro["estado"] not in ("RECIBIDO", "PROCESANDO")
    assert registro["cloud_procesamiento"]["estado"] == "RECONCILIADO"
    # El envío publicó su decisión pendiente al procesarse, y la bandeja
    # final es exactamente la del comportamiento previo.
    assert ("ORIGEN_NO_CONFIRMADO", "700001") in entorno.publicadas
    assert entorno.bandeja() == esperado
    # La pasada global corrió UNA vez, después de confirmar, con el envío ya cerrado.
    assert entorno.eventos == ["confirmacion", "reconciliacion"]
    assert entorno.reconciliaciones[0]["raiz"] == entorno.raiz
    assert entorno.reconciliaciones[0]["estado_envio"] == registro["estado"]
    solicitud = entorno.solicitud()
    assert solicitud["estado"] == "COMPLETADA"
    assert solicitud["intentos"] == 1
    assert resultado["reconciliacion_bandeja"]["completados"] == [ENVIO]


def test_envio_sin_decisiones_tambien_se_cierra_sin_esperar(tmp_path, monkeypatch):
    ocr = {
        "numero_guia": "700002", "numero_transporte": "0000700002",
        "indicador_revision": "OK", "tipo_carga": "BARRAS",
        "estado_ruta": "RUTA_CALCULADA", "motivo_ruta": "",
        "planta_origen_id": "", "planta_origen_nombre": "AZA COLINA",
        "origen_determinado_por": "MOBILE",
    }
    esperado = _bandeja_final_sin_diferir(tmp_path / "previo", monkeypatch, ocr)
    entorno = Entorno(tmp_path / "diferido", monkeypatch, ocr)
    _con_planta_del_entorno(entorno, ocr)

    resultado = entorno.pull()

    assert resultado["confirmados"] == [ENVIO]
    assert entorno.publicadas == []
    assert entorno.bandeja() == esperado
    assert entorno.eventos == ["confirmacion", "reconciliacion"]
    assert entorno.solicitud()["estado"] == "COMPLETADA"
    assert len(entorno.filas_envio()) == 1


def test_reintento_del_mismo_envio_no_duplica_y_vuelve_a_reconciliar(tmp_path, monkeypatch):
    entorno = Entorno(tmp_path, monkeypatch, OCR_CON_DECISION)
    entorno.pull()
    bandeja_tras_primer_cierre = entorno.bandeja()
    # Interrupción real (PID 16016): quedó PROCESANDO tras escribir dataset y bandeja.
    registro = entorno.repo.cargar(ENVIO)
    registro["estado"] = "PROCESANDO"
    registro["cloud_procesamiento"]["estado"] = "ATERRIZADO"
    entorno.repo.guardar(ENVIO, registro)

    resultado = entorno.pull()  # Cloud lo vuelve a ofrecer: lease vencido, sin confirmar

    assert resultado["confirmados"] == [ENVIO]
    assert len(entorno.filas_envio()) == 1
    assert entorno.bandeja() == bandeja_tras_primer_cierre
    assert entorno.solicitud()["estado"] == "COMPLETADA"
    assert entorno.solicitud()["intentos"] == 2
    assert entorno.eventos.count("reconciliacion") == 2

    # Idempotente: sin nada nuevo ni pendiente, la pasada global no vuelve a correr.
    entorno.pull(pendientes=False)
    assert entorno.eventos.count("reconciliacion") == 2


def test_fallo_de_reconciliacion_global_no_bloquea_el_envio_y_queda_pendiente(tmp_path, monkeypatch):
    entorno = Entorno(tmp_path, monkeypatch, OCR_CON_DECISION)
    entorno.falla_reconciliacion = True

    resultado = entorno.pull()

    # El envío se cerró y Cloud recibió su confirmación igual.
    assert resultado["confirmados"] == [ENVIO]
    assert entorno.repo.cargar(ENVIO)["estado"] not in ("RECIBIDO", "PROCESANDO")
    # Nunca se declara reconciliado lo que no corrió.
    solicitud = entorno.solicitud()
    assert solicitud["estado"] == "PENDIENTE"
    assert solicitud["intentos"] == 1
    assert "G: no responde" in solicitud["ultimo_error"]
    assert resultado["reconciliacion_bandeja"]["ejecutada"] is False
    assert resultado["reconciliacion_bandeja"]["completados"] == []

    # Ciclo siguiente (sin envíos nuevos): retoma la pendiente y la completa.
    entorno.falla_reconciliacion = False
    resultado = entorno.pull(pendientes=False)
    solicitud = entorno.solicitud()
    assert solicitud["estado"] == "COMPLETADA"
    assert solicitud["intentos"] == 2
    assert "ultimo_error" not in solicitud
    assert resultado["reconciliacion_bandeja"]["completados"] == [ENVIO]
    assert len(entorno.filas_envio()) == 1


def test_reconciliador_real_sobre_datos_temporales_completa_la_solicitud(tmp_path, monkeypatch):
    entorno = Entorno(tmp_path, monkeypatch, OCR_CON_DECISION, reconciliador_real=True)

    resultado = entorno.pull()

    assert resultado["confirmados"] == [ENVIO]
    assert resultado["reconciliacion_bandeja"]["error"] is None
    assert entorno.solicitud()["estado"] == "COMPLETADA"
    assert len(entorno.filas_envio()) == 1


def test_solicitud_renovada_durante_la_pasada_sigue_pendiente(tmp_path, monkeypatch):
    entorno = Entorno(tmp_path, monkeypatch, OCR_CON_DECISION)
    entorno.repo.recibir(envio_id=ENVIO, imagen=BYTES, mime="image/jpeg", metadata=METADATA)
    registro = entorno.repo.cargar(ENVIO)
    registro["reconciliacion_bandeja"] = mobile._solicitud_reconciliacion_bandeja(registro)
    entorno.repo.guardar(ENVIO, registro)

    def reconciliador_con_reproceso_concurrente(*, raiz_atlas):
        # Un reproceso del mismo envío renueva la solicitud mientras corre la pasada.
        actual = entorno.repo.cargar(ENVIO)
        actual["reconciliacion_bandeja"] = mobile._solicitud_reconciliacion_bandeja(actual)
        entorno.repo.guardar(ENVIO, actual)

    resultado = reconciliar_bandeja_diferida_mobile(
        entorno.repo, raiz_atlas=tmp_path, reconciliador=reconciliador_con_reproceso_concurrente,
    )

    assert resultado["completados"] == []
    assert entorno.solicitud()["estado"] == "PENDIENTE"


def test_flujo_lan_por_defecto_conserva_la_reconciliacion_sincronica(tmp_path, monkeypatch):
    entorno = Entorno(tmp_path, monkeypatch, OCR_CON_DECISION)
    entorno.repo.recibir(envio_id=ENVIO, imagen=BYTES, mime="image/jpeg", metadata=METADATA)

    registro = procesar_envio_mobile(
        entorno.repo, ENVIO, dataset=entorno.dataset, carpeta_catalogos=entorno.catalogos,
    )

    assert entorno.eventos == ["reconciliacion"]
    assert entorno.reconciliaciones[0]["estado_envio"] == "PROCESANDO"  # dentro del cierre, como hoy
    assert "reconciliacion_bandeja" not in registro
