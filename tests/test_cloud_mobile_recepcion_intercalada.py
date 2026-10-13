"""PULL Cloud con recepción intercalada: un OCR lento no retiene la
recepción del resto y el contrato de confirmación queda intacto.

Worker simulado con la semántica de D1 (`listarMotor`, lease con token y
vencimiento, renovar, confirmar sólo con token vigente), repositorio REAL
en una raíz temporal y OCR simulado. Nunca G:, Worker real ni OCR real."""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pytest

from atlas_core import cloud_mobile_sync_cliente as cloud
from atlas_core.cloud_mobile_sync_cliente import ErrorSincronizacionCloudMobile
from atlas_core.mobile import RepositorioEnviosMobile

LEASE_SEGUNDOS = 300


class WorkerSimulado:
    def __init__(self) -> None:
        self.ahora = 0.0
        self.envios: dict[str, dict] = {}
        self.eventos: list[str] = []
        self.fallas_pendientes = 0
        self.fallas_confirmar: set[str] = set()
        self.max_en_lease = 0
        self.leases_por_envio: dict[str, int] = {}
        self.confirmaciones: list[tuple[str, str]] = []
        self.listado_extra: list[str] = []

    def agregar(self, envio_id: str) -> None:
        self.envios[envio_id] = {"estado": "PENDIENTE", "token": None, "expira": 0.0, "bytes": f"img-{envio_id}".encode()}

    def _disponible(self, envio: dict) -> bool:
        return envio["estado"] == "PENDIENTE" or (envio["estado"] == "EN_LEASE" and envio["expira"] <= self.ahora)

    def _vigente(self, envio: dict, token: str) -> bool:
        return envio["estado"] == "EN_LEASE" and envio["token"] == token and envio["expira"] > self.ahora

    def en_lease(self) -> int:
        return sum(1 for e in self.envios.values() if e["estado"] == "EN_LEASE" and e["expira"] > self.ahora)

    def json(self, _base, ruta, _token, *, method="GET", body=None, timeout=None):
        if ruta.endswith("/pendientes"):
            if self.fallas_pendientes:
                self.fallas_pendientes -= 1
                raise ErrorSincronizacionCloudMobile("Cloud Motor GET pendientes: timed out")
            listado = [i for i, e in self.envios.items() if self._disponible(e)] + self.listado_extra
            return {"envios": [{"envio_id": i} for i in listado]}
        envio_id, accion = re.fullmatch(r"/api/motor/envios/([^/]+)/(lease|lease/renovar|confirmar)", ruta).groups()
        envio = self.envios[envio_id]
        if accion == "lease":
            if not self._disponible(envio):
                raise ErrorSincronizacionCloudMobile("409 LEASE_NO_DISPONIBLE")
            self.leases_por_envio[envio_id] = self.leases_por_envio.get(envio_id, 0) + 1
            token = f"tok-{envio_id}-{self.leases_por_envio[envio_id]}"
            envio.update(estado="EN_LEASE", token=token, expira=self.ahora + LEASE_SEGUNDOS)
            self.max_en_lease = max(self.max_en_lease, self.en_lease())
            self.eventos.append(f"lease:{envio_id}")
            contenido = envio["bytes"]
            return {
                "envio_id": envio_id, "documento_id": f"doc_{envio_id}", "empresa_id": "empresa-prueba",
                "chofer_id": "chofer-1", "observacion": "", "imagen_mime": "image/jpeg",
                "imagen_bytes": len(contenido), "imagen_sha256": hashlib.sha256(contenido).hexdigest(),
                "descarga_url": f"https://cloud.test/doc/{envio_id}?t={token}", "lease_token": token,
                "planta_origen_informada": "AZA_COLINA", "tipo_novedad": "", "guia_firmada_correo": False,
                "capturado_en": "", "lote_id": "",
            }
        token = body["lease_token"]
        if accion == "lease/renovar":
            if not self._vigente(envio, token):
                raise ErrorSincronizacionCloudMobile("409 LEASE_NO_VIGENTE")
            envio["expira"] = self.ahora + LEASE_SEGUNDOS
            return {"estado": "EN_LEASE"}
        if envio_id in self.fallas_confirmar:
            self.fallas_confirmar.discard(envio_id)
            raise ErrorSincronizacionCloudMobile("Cloud Motor POST confirmar: connection reset")
        if not self._vigente(envio, token):
            raise ErrorSincronizacionCloudMobile("409 LEASE_NO_VIGENTE")
        envio.update(estado="COMPLETADO", token=None)
        self.confirmaciones.append((envio_id, token))
        self.eventos.append(f"confirmado:{envio_id}")
        return {"estado": "COMPLETADO"}

    def descargar(self, url, *, esperado_bytes, timeout):
        envio_id, token = re.fullmatch(r"https://cloud\.test/doc/([^?]+)\?t=(.+)", url).groups()
        envio = self.envios[envio_id]
        if not self._vigente(envio, token):
            raise ErrorSincronizacionCloudMobile("409 LEASE_NO_VIGENTE")
        return envio["bytes"]


class Entorno:
    def __init__(self, raiz: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.worker = WorkerSimulado()
        self.repo = RepositorioEnviosMobile(raiz)
        self.ocr: list[str] = []
        self.durante_ocr: dict[str, callable] = {}
        self.persistidos_en_ocr: dict[str, list[str]] = {}
        recibir_original = self.repo.recibir

        def recibir(**kwargs):
            salida = recibir_original(**kwargs)
            self.worker.eventos.append(f"persistido:{kwargs['envio_id']}")
            return salida

        self.repo.recibir = recibir  # type: ignore[method-assign]
        monkeypatch.setattr(cloud, "_json", self.worker.json)
        monkeypatch.setattr(cloud, "_descargar", self.worker.descargar)
        monkeypatch.setattr(cloud, "_procesar_envio_cloud", self._procesar)

    def _procesar(self, repositorio, envio_id, **_kwargs):
        registro = repositorio.cargar(envio_id)
        if registro["estado"] == "ERROR":
            return {"completado": False, "error": "ERROR funcional persistido"}
        if registro["estado"] in ("RECIBIDO", "PROCESANDO"):
            self.ocr.append(envio_id)
            self.worker.eventos.append(f"ocr:{envio_id}")
            registro["estado"] = "PROCESANDO"
            repositorio.guardar(envio_id, registro)
            accion = self.durante_ocr.get(envio_id)
            if accion is not None:
                accion()
            registro["estado"] = "ASOCIADO"
            repositorio.guardar(envio_id, registro)
        return {"completado": True}

    def pull(self, *, procesar: bool = True, puede_continuar=None, max_leases_en_cola: int = 20) -> dict:
        return cloud.sincronizar_envios_cloud(
            base_url="https://cloud.test", token_motor="t", consumidor="motor-prueba", repositorio=self.repo,
            timeout=1, procesar=procesar, dataset=None, carpeta_catalogos=None,
            lease_heartbeat_segundos=0, puede_continuar=puede_continuar, max_leases_en_cola=max_leases_en_cola,
        )

    def estado_local(self, envio_id: str) -> str:
        return self.repo.cargar(envio_id)["estado"]

    def checkpoint(self, envio_id: str) -> str:
        return (self.repo.cargar(envio_id).get("cloud_procesamiento") or {}).get("estado", "")


A, B, C, D, E = (f"envio-{letra}-0001" for letra in "abcde")


@pytest.fixture
def entorno(tmp_path, monkeypatch):
    return Entorno(tmp_path, monkeypatch)


def test_ocr_lento_no_retiene_la_recepcion_del_resto(entorno):
    entorno.worker.agregar(A)
    entorno.worker.agregar(B)
    entorno.durante_ocr[A] = lambda: entorno.worker.agregar(C)  # llega mientras A está en OCR

    resultado = entorno.pull()

    assert entorno.worker.eventos == [
        f"lease:{A}", f"persistido:{A}", f"lease:{B}", f"persistido:{B}",
        f"ocr:{A}", f"confirmado:{A}",
        f"lease:{C}", f"persistido:{C}",  # recibido ANTES del siguiente OCR
        f"ocr:{B}", f"confirmado:{B}",
        f"ocr:{C}", f"confirmado:{C}",
    ]
    assert resultado["confirmados"] == [A, B, C]
    assert resultado["encontrados"] == 3
    assert resultado["fallidos"] == {}


def test_multiples_leases_vivos_se_confirman_cada_uno_con_su_token(entorno):
    for envio_id in (A, B, C):
        entorno.worker.agregar(envio_id)

    resultado = entorno.pull()

    assert entorno.worker.max_en_lease == 3
    assert entorno.worker.confirmaciones == [(A, f"tok-{A}-1"), (B, f"tok-{B}-1"), (C, f"tok-{C}-1")]
    assert resultado["confirmados"] == [A, B, C]
    assert all(entorno.checkpoint(e) == "RECONCILIADO" for e in (A, B, C))


def test_cola_limitada_deja_el_resto_pendiente_en_cloud_y_lo_toma_despues(entorno):
    for envio_id in (A, B, C, D, E):
        entorno.worker.agregar(envio_id)

    resultado = entorno.pull(max_leases_en_cola=2)

    assert entorno.worker.max_en_lease == 2
    assert resultado["confirmados"] == [A, B, C, D, E]
    assert entorno.worker.eventos[:5] == [f"lease:{A}", f"persistido:{A}", f"lease:{B}", f"persistido:{B}", f"ocr:{A}"]


def test_tope_por_defecto_es_20_leases(entorno):
    ids = [f"envio-{n:04d}-tope" for n in range(25)]
    for envio_id in ids:
        entorno.worker.agregar(envio_id)

    resultado = entorno.pull(max_leases_en_cola=cloud.MAX_LEASES_EN_COLA)

    assert cloud.MAX_LEASES_EN_COLA == 20
    assert entorno.worker.max_en_lease == 20
    assert resultado["confirmados"] == ids


def test_red_intermitente_en_recepcion_intercalada_no_corta_el_procesamiento(entorno):
    entorno.worker.agregar(A)
    entorno.worker.agregar(B)

    def cae_la_red():
        entorno.worker.agregar(C)
        entorno.worker.fallas_pendientes = 1  # la ronda intercalada siguiente falla

    entorno.durante_ocr[A] = cae_la_red
    resultado = entorno.pull()

    assert resultado["errores_recepcion"] == ["Cloud Motor GET pendientes: timed out"]
    # B (ya en cola) se procesó y confirmó; C entró en la ronda siguiente.
    assert resultado["confirmados"] == [A, B, C]


def test_primera_recepcion_sin_red_corta_la_corrida_como_antes(entorno):
    entorno.worker.agregar(A)
    entorno.worker.fallas_pendientes = 1
    with pytest.raises(ErrorSincronizacionCloudMobile):
        entorno.pull()
    assert entorno.worker.eventos == []


def test_confirmacion_perdida_por_red_se_recupera_sin_reprocesar(entorno):
    entorno.worker.agregar(A)
    entorno.worker.fallas_confirmar.add(A)

    primera = entorno.pull()
    assert primera["confirmados"] == []
    assert A in primera["fallidos"]
    assert entorno.checkpoint(A) == "RECONCILIADO"

    entorno.worker.ahora += LEASE_SEGUNDOS + 1  # el lease vence; Cloud lo vuelve a ofrecer
    segunda = entorno.pull()

    assert segunda["confirmados"] == [A]
    assert entorno.ocr == [A]  # nunca un segundo OCR
    assert entorno.worker.confirmaciones == [(A, f"tok-{A}-2")]


def test_lease_perdido_en_cola_no_confirma_ni_usa_token_vencido(entorno):
    entorno.worker.agregar(A)
    entorno.worker.agregar(B)

    def vence_lease_de_b():
        entorno.worker.ahora += LEASE_SEGUNDOS + 1  # OCR de A más largo que el lease de B

    entorno.durante_ocr[A] = vence_lease_de_b
    resultado = entorno.pull()

    # A se renueva justo antes de confirmar (renovar exige vigencia: A también
    # venció) -> ninguno se confirma con un token vencido.
    assert entorno.worker.confirmaciones == []
    assert resultado["fallidos"] == {A: "lease Cloud perdido antes de confirmar", B: "lease Cloud perdido antes de confirmar"}
    # Cloud los vuelve a listar en la ronda intercalada, pero en la misma
    # corrida nunca se pide un segundo lease del mismo envío.
    assert entorno.worker.leases_por_envio == {A: 1, B: 1}
    assert entorno.estado_local(A) == entorno.estado_local(B) == "ASOCIADO"

    segunda = entorno.pull()
    assert segunda["confirmados"] == [A, B]
    assert entorno.ocr == [A, B]


def test_caida_a_mitad_de_ocr_libera_la_cola_y_la_corrida_siguiente_recupera(entorno):
    entorno.worker.agregar(A)
    entorno.worker.agregar(B)

    def caida():
        raise RuntimeError("proceso terminado a mitad de OCR")

    entorno.durante_ocr[A] = caida
    with pytest.raises(RuntimeError):
        entorno.pull()
    assert entorno.worker.confirmaciones == []
    assert entorno.estado_local(A) == "PROCESANDO"
    assert entorno.estado_local(B) == "RECIBIDO"

    del entorno.durante_ocr[A]
    entorno.worker.ahora += LEASE_SEGUNDOS + 1
    resultado = entorno.pull()

    assert resultado["confirmados"] == [A, B]
    assert entorno.worker.leases_por_envio == {A: 2, B: 2}
    # Re-descarga idempotente: `recibir` no duplica el envío local.
    assert sorted(p.name for p in entorno.repo.raiz.iterdir()) == sorted([A, B])


def test_caida_tras_aterrizar_sin_cloud_disponible_se_recupera_localmente(entorno):
    entorno.worker.agregar(A)
    entorno.pull(procesar=False)  # aterriza, no confirma (equivale a caer antes del OCR)
    assert entorno.estado_local(A) == "RECIBIDO"

    # Cloud aún no lo reofrece (lease vigente): el barrido local lo procesa
    # igual, sin confirmar con un lease que esta corrida no tiene.
    resultado = entorno.pull()
    assert resultado["procesados"] == [A]
    assert resultado["confirmados"] == []
    assert entorno.estado_local(A) == "ASOCIADO"

    entorno.worker.ahora += LEASE_SEGUNDOS + 1
    resultado = entorno.pull()
    assert resultado["confirmados"] == [A]
    assert entorno.ocr == [A]


def test_barrido_local_tambien_intercala_recepcion(entorno):
    entorno.worker.agregar(A)
    entorno.worker.agregar(B)
    entorno.pull(procesar=False)
    entorno.worker.ahora += 1  # leases de A y B siguen vigentes en Cloud
    entorno.durante_ocr[A] = lambda: entorno.worker.agregar(C)

    resultado = entorno.pull()

    eventos = entorno.worker.eventos
    assert eventos.index(f"persistido:{C}") < eventos.index(f"ocr:{B}")
    assert resultado["confirmados"] == [C]
    assert set(resultado["procesados"]) == {A, B, C}


def test_duplicados_en_el_listado_no_piden_dos_leases(entorno):
    entorno.worker.agregar(A)
    entorno.worker.listado_extra = [A, A]

    resultado = entorno.pull()

    assert entorno.worker.leases_por_envio == {A: 1}
    assert resultado["encontrados"] == 1
    assert resultado["confirmados"] == [A]


def test_error_funcional_en_cola_no_se_confirma_y_no_bloquea_al_resto(entorno):
    entorno.worker.agregar(A)
    entorno.worker.agregar(B)
    entorno.pull(procesar=False)
    registro = entorno.repo.cargar(A)
    registro["estado"] = "ERROR"
    entorno.repo.guardar(A, registro)
    entorno.worker.ahora += LEASE_SEGUNDOS + 1

    resultado = entorno.pull()

    assert resultado["confirmados"] == [B]
    assert A in resultado["errores_procesamiento"]
    assert [envio for envio, _ in entorno.worker.confirmaciones] == [B]
    assert entorno.worker.envios[A]["estado"] == "EN_LEASE"  # sigue reintentable en Cloud


def test_perdida_de_escritor_con_cola_no_procesa_ni_confirma_el_resto(entorno):
    entorno.worker.agregar(A)
    entorno.worker.agregar(B)
    activo = {"valor": True}

    def pierde_escritor():
        activo["valor"] = False

    entorno.durante_ocr[A] = pierde_escritor
    resultado = entorno.pull(puede_continuar=lambda: activo["valor"])

    assert resultado["detenido_por_escritor"] is True
    assert entorno.worker.confirmaciones == []
    assert entorno.ocr == [A]
    assert entorno.estado_local(B) == "RECIBIDO"


def test_sin_procesar_aterriza_todo_sin_ocr_ni_confirmar(entorno):
    for envio_id in (A, B, C):
        entorno.worker.agregar(envio_id)

    resultado = entorno.pull(procesar=False, max_leases_en_cola=1)  # el tope no aplica sin procesar

    assert resultado["persistidos"] == [A, B, C]
    assert resultado["confirmados"] == []
    assert entorno.ocr == []
    assert [e for e in entorno.worker.eventos if e.startswith("confirmado")] == []
    assert all(entorno.checkpoint(e) == "ATERRIZADO" for e in (A, B, C))
