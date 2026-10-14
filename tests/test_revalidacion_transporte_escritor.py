"""Exclusión entre escritores: `revalidar_transporte.py --ejecutar` y el
PULL Cloud comparten el MISMO lease global de escritor. Sintético: el
Cloud es un doble con la semántica del Worker (`adquirir` sólo gana si no
hay lease vigente, aunque lo pida el mismo `escritor_id`), nunca toca G:."""
from __future__ import annotations

import os
import time
from unittest.mock import patch

import pytest

import revalidar_transporte as cli
from atlas_core import reprocesamiento_reparador as m
from atlas_core.almacenamiento_portable import SesionOcupadaError
from atlas_core.escritor_operativo import ErrorEscritorOperativo, LeaseEscritorOperativo
from atlas_core.procesamiento_masivo import COLUMNAS
from atlas_core.revalidacion_documental import _escribir_filas_completas, _leer_filas
from sincronizar_mobile_cloud import ejecutar_pull_con_escritor

TRANSPORTE = "0000359510"


class CloudEscritor:
    """Un único lease por empresa, como `escritores_operativos` en D1."""

    def __init__(self):
        self.token = ""
        self.epoca = 0
        self.adquisiciones: list[str] = []
        self.liberaciones = 0

    def __call__(self, _base, ruta, _token, *, method="GET", body=None, timeout=0):
        if ruta.endswith("/estado"):
            return {"vigente": bool(self.token), "epoca": self.epoca}
        if ruta.endswith("/adquirir"):
            if self.token:
                raise ErrorEscritorOperativo("HTTP 409 ESCRITOR_OCUPADO")
            self.epoca += 1
            self.token = f"lease-{self.epoca}"
            self.adquisiciones.append(body["escritor_id"])
            return {"estado": "ADQUIRIDO", "lease_token": self.token, "epoca": self.epoca}
        if ruta.endswith("/renovar"):
            if not self.token or body["lease_token"] != self.token:
                raise ErrorEscritorOperativo("HTTP 409 LEASE_PERDIDO")
            return {"estado": "RENOVADO", "epoca": self.epoca}
        if ruta.endswith("/liberar"):
            if not self.token or body["lease_token"] != self.token:
                raise ErrorEscritorOperativo("HTTP 409 LEASE_PERDIDO")
            self.token = ""
            self.liberaciones += 1
            return {"estado": "LIBERADO"}
        raise AssertionError(ruta)

    def vencer(self):
        """El lease vence en Cloud (heartbeat caído): otro puede tomarlo."""
        self.token = ""


@pytest.fixture(autouse=True)
def sin_ocr_real(monkeypatch):
    monkeypatch.setattr(m, "crear_proveedor_ocr", lambda *a, **kw: object())


@pytest.fixture
def cloud():
    api = CloudEscritor()
    with patch("atlas_core.escritor_operativo._json", side_effect=api):
        yield api


class Fabrica:
    """Lease real, misma identidad de PC para PULL y revalidación."""

    def __init__(self):
        self.instancias: list[LeaseEscritorOperativo] = []

    def __call__(self, **kwargs):
        lease = LeaseEscritorOperativo(
            **kwargs, escritor_id="pc-oficina", heartbeat_segundos=0, margen_relevo_segundos=0,
        )
        self.instancias.append(lease)
        return lease


def _raiz(tmp_path):
    raiz = tmp_path / "atlas"
    (raiz / "operacion" / "actual").mkdir(parents=True)
    (raiz / "operacion" / "entradas" / "LOTE1").mkdir(parents=True)
    (raiz / "catalogos_privados").mkdir(parents=True)
    filas = []
    for archivo, guia in (("474285.jpg", "474285"), ("474286.jpg", "474286")):
        (raiz / "operacion" / "entradas" / "LOTE1" / archivo).write_bytes(b"fake-image-bytes")
        fila = {columna: "" for columna in COLUMNAS}
        fila.update({
            "archivo": archivo, "numero_guia": guia, "numero_transporte": TRANSPORTE,
            "estado_procesamiento": "OK", "indicador_revision": "OK", "estado_documental": "OK",
            "estado_operacional": "OK", "peso_kg": "19307",
        })
        filas.append(fila)
    _escribir_filas_completas(_dataset(raiz), filas)
    (raiz / "operacion" / "actual" / "decisiones_aplicadas.json").write_text('{"aplicaciones": []}', encoding="utf-8")
    return raiz


def _dataset(raiz):
    return raiz / "operacion" / "actual" / "analisis_completo_guias.csv"


def _lock(raiz):
    return raiz / "operacion" / "actual" / ".atlas_lock_revalidacion_dataset"


def _pesos(raiz):
    return [f["peso_kg"] for f in _leer_filas(_dataset(raiz))]


def _revalidar(raiz, fabrica):
    return cli.ejecutar_revalidacion_con_escritor(
        base_url="https://cloud.test", token_motor="t", raiz_atlas=raiz,
        numero_transporte=TRANSPORTE, fabrica_escritor=fabrica,
    )


def _pull(fabrica, sincronizar):
    with patch("sincronizar_mobile_cloud.sincronizar_envios_cloud", side_effect=sincronizar) as pull:
        resultado = ejecutar_pull_con_escritor(
            base_url="https://cloud.test", token_motor="t", consumidor="pc-oficina",
            repositorio=object(), timeout=1, procesar=True, dataset=None, carpeta_catalogos=None,
            fabrica_escritor=fabrica,
        )
    return resultado, pull


@pytest.fixture
def reconciliaciones(monkeypatch):
    llamadas = []
    monkeypatch.setattr(m, "revalidar_y_regenerar_reporte", lambda **kw: llamadas.append(kw) or {"ok": True})
    return llamadas


# --- competencia PULL <-> revalidación ---

def test_pull_activo_impide_revalidacion_sin_ocr_ni_escritura(tmp_path, cloud, reconciliaciones, monkeypatch):
    raiz = _raiz(tmp_path)
    fabrica = Fabrica()
    ocr = []
    monkeypatch.setattr(m, "procesar_archivo", lambda *a, **kw: ocr.append(a) or {"peso_kg": "9307"})
    vistos = {}

    def pull_que_dura(**kwargs):
        # Mientras el PULL escribe, el operador lanza la revalidación.
        vistos["revalidacion"] = _revalidar(raiz, fabrica)
        assert kwargs["puede_continuar"]()  # el PULL conserva su lease
        return {"confirmados": []}

    resultado_pull, pull = _pull(fabrica, pull_que_dura)

    assert resultado_pull == {"confirmados": []}
    assert vistos["revalidacion"] == {"escritor_operativo": "NO_ADQUIRIDO", "numero_transporte": TRANSPORTE}
    assert ocr == [] and reconciliaciones == []
    assert _pesos(raiz) == ["19307", "19307"]
    assert not _lock(raiz).exists()
    assert cloud.adquisiciones == ["pc-oficina"]  # mismo PC, sin reentrada
    assert cloud.token == "" and cloud.liberaciones == 1


def test_revalidacion_activa_impide_pull_y_lo_libera_al_terminar(tmp_path, cloud, reconciliaciones, monkeypatch):
    raiz = _raiz(tmp_path)
    fabrica = Fabrica()
    pulls_durante = []

    def ocr_lento(*_a, **_kw):
        pulls_durante.append(_pull(fabrica, lambda **_k: {"confirmados": ["x"]}))
        return {"peso_kg": "9307"}

    monkeypatch.setattr(m, "procesar_archivo", ocr_lento)

    resultado = _revalidar(raiz, fabrica)

    assert resultado["escritor_operativo"] == "ADQUIRIDO"
    assert resultado["campos_cambiados_total"] == 2 and resultado["reconciliacion_pendiente"] is False
    assert len(reconciliaciones) == 1
    assert _pesos(raiz) == ["9307", "9307"]
    for resultado_pull, pull in pulls_durante:
        assert resultado_pull["escritor_operativo"] == "NO_ADQUIRIDO"
        pull.assert_not_called()
    # Liberado el lease, el siguiente ciclo del PULL entra normalmente.
    assert cloud.token == ""
    resultado_pull, pull = _pull(fabrica, lambda **_k: {"confirmados": []})
    assert resultado_pull == {"confirmados": []} and pull.call_count == 1


# --- pérdida de lease ---

def test_lease_perdido_durante_ocr_no_escribe_ni_reconcilia(tmp_path, cloud, reconciliaciones, monkeypatch):
    raiz = _raiz(tmp_path)
    fabrica = Fabrica()
    ocr = []

    def ocr_y_vence(*a, **_kw):
        ocr.append(a)
        cloud.vencer()
        assert not fabrica.instancias[-1].renovar()  # el heartbeat detecta la pérdida
        return {"peso_kg": "9307"}

    monkeypatch.setattr(m, "procesar_archivo", ocr_y_vence)

    resultado = _revalidar(raiz, fabrica)

    assert resultado["escritor_operativo"] == "PERDIDO"
    assert resultado["escritor_operativo_perdido"] is True
    assert resultado["dataset_escrito"] is False and resultado["reconciliacion_pendiente"] is False
    assert len(ocr) == 1  # el segundo documento ya no se procesa
    assert reconciliaciones == []
    assert _pesos(raiz) == ["19307", "19307"]
    assert not _lock(raiz).exists()


def test_lease_perdido_tras_escribir_dataset_deja_reconciliacion_pendiente(tmp_path, cloud, monkeypatch):
    raiz = _raiz(tmp_path)
    monkeypatch.setattr(m, "procesar_archivo", lambda *a, **kw: {"peso_kg": "9307"})
    reconciliaciones = []
    monkeypatch.setattr(m, "revalidar_y_regenerar_reporte", lambda **kw: reconciliaciones.append(kw))
    vigencia = iter([True, True, True, False])  # doc1, doc2, escritura, reconciliación

    resultado = m.revalidar_documentos_por_transporte(
        raiz_atlas=raiz, numero_transporte=TRANSPORTE, dry_run=False, proveedor=object(),
        puede_escribir=lambda: next(vigencia),
    )

    assert resultado["dataset_escrito"] is True
    assert resultado["reconciliacion_pendiente"] is True
    assert resultado["escritor_operativo_perdido"] is True
    assert reconciliaciones == []
    assert _pesos(raiz) == ["9307", "9307"]


def test_guarda_no_se_consulta_en_dry_run(tmp_path, monkeypatch):
    raiz = _raiz(tmp_path)
    monkeypatch.setattr(m, "procesar_archivo", lambda *a, **kw: {"peso_kg": "9307"})

    def guarda():
        raise AssertionError("dry-run no consulta el escritor")

    resultado = m.revalidar_documentos_por_transporte(
        raiz_atlas=raiz, numero_transporte=TRANSPORTE, dry_run=True, proveedor=object(), puede_escribir=guarda,
    )

    assert resultado["campos_cambiados_total"] == 2 and resultado["escritor_operativo_perdido"] is False
    assert _pesos(raiz) == ["19307", "19307"]


# --- liberación de locks y recuperación ---

def test_falla_en_reconciliacion_libera_lease_y_lock(tmp_path, cloud, monkeypatch):
    raiz = _raiz(tmp_path)
    monkeypatch.setattr(m, "procesar_archivo", lambda *a, **kw: {"peso_kg": "9307"})

    def reconciliacion_rota(**_kw):
        raise RuntimeError("reporte roto")

    monkeypatch.setattr(m, "revalidar_y_regenerar_reporte", reconciliacion_rota)

    with pytest.raises(RuntimeError, match="reporte roto"):
        _revalidar(raiz, Fabrica())

    assert cloud.token == "" and cloud.liberaciones == 1
    assert not _lock(raiz).exists()
    # Se puede volver a tomar de inmediato (no queda bloqueado).
    _resultado, pull = _pull(Fabrica(), lambda **_k: {"confirmados": []})
    assert pull.call_count == 1


def test_lock_de_revalidacion_vigente_aborta_y_libera_el_lease(tmp_path, cloud, reconciliaciones, monkeypatch):
    raiz = _raiz(tmp_path)
    _lock(raiz).write_text('{"pid": 1}', encoding="utf-8")  # otra aplicación de decisión en curso
    monkeypatch.setattr(m, "procesar_archivo", lambda *a, **kw: {"peso_kg": "9307"})

    with pytest.raises(SesionOcupadaError):
        _revalidar(raiz, Fabrica())

    assert cloud.token == "" and cloud.liberaciones == 1
    assert _lock(raiz).exists()  # el lock ajeno no se toca
    assert _pesos(raiz) == ["19307", "19307"] and reconciliaciones == []


def test_lock_huerfano_tras_interrupcion_se_recupera_bajo_lease(tmp_path, cloud, reconciliaciones, monkeypatch):
    raiz = _raiz(tmp_path)
    _lock(raiz).write_text('{"pid": 1}', encoding="utf-8")
    viejo = time.time() - 7 * 3600  # > 6 h: proceso anterior murió sin liberar
    os.utime(_lock(raiz), (viejo, viejo))
    monkeypatch.setattr(m, "procesar_archivo", lambda *a, **kw: {"peso_kg": "9307"})

    resultado = _revalidar(raiz, Fabrica())

    assert resultado["escritor_operativo"] == "ADQUIRIDO"
    assert _pesos(raiz) == ["9307", "9307"]
    assert not _lock(raiz).exists()
    assert cloud.token == ""


# --- CLI ---

def test_cli_dry_run_no_pide_token_ni_lease(tmp_path, cloud, monkeypatch, capsys):
    raiz = _raiz(tmp_path)
    monkeypatch.setattr(m, "procesar_archivo", lambda *a, **kw: {"peso_kg": "9307"})
    monkeypatch.delenv("ATLAS_CLOUD_MOTOR_TOKEN", raising=False)
    monkeypatch.setattr("sys.argv", ["revalidar_transporte.py", "--raiz-atlas", str(raiz), "--numero-transporte", TRANSPORTE])

    cli.main()

    assert '"dry_run": true' in capsys.readouterr().out
    assert cloud.adquisiciones == []
    assert _pesos(raiz) == ["19307", "19307"]


def test_cli_ejecutar_sin_token_falla_antes_de_tocar_datos(tmp_path, monkeypatch):
    raiz = _raiz(tmp_path)
    monkeypatch.delenv("ATLAS_CLOUD_MOTOR_TOKEN", raising=False)
    monkeypatch.setattr("sys.argv", ["revalidar_transporte.py", "--raiz-atlas", str(raiz),
                                     "--numero-transporte", TRANSPORTE, "--ejecutar"])
    monkeypatch.setattr(cli, "revalidar_documentos_por_transporte", lambda **kw: pytest.fail("no debe revalidar"))

    with pytest.raises(SystemExit) as salida:
        cli.main()

    assert salida.value.code == 2


def test_cli_ejecutar_con_escritor_ocupado_sale_con_codigo_3(tmp_path, cloud, monkeypatch, capsys):
    raiz = _raiz(tmp_path)
    cloud.token = "lease-del-pull"
    monkeypatch.setenv("ATLAS_CLOUD_MOTOR_TOKEN", "t")
    monkeypatch.setattr("sys.argv", ["revalidar_transporte.py", "--raiz-atlas", str(raiz),
                                     "--numero-transporte", TRANSPORTE, "--ejecutar"])
    monkeypatch.setattr(cli, "revalidar_documentos_por_transporte", lambda **kw: pytest.fail("no debe revalidar"))

    with pytest.raises(SystemExit) as salida:
        cli.main()

    assert salida.value.code == 3
    assert '"escritor_operativo": "NO_ADQUIRIDO"' in capsys.readouterr().out
    assert cloud.token == "lease-del-pull"  # el lease ajeno no se libera
