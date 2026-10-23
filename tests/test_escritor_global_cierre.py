"""Cierre del escritor global: la acción TRANSPORTE_REVALIDAR (Desktop/B1)
corre bajo el mismo lease que el PULL, y una reconciliación que quedó sin
hacer tras reescribir el dataset es recuperable sin duplicar ni perder
filas. Sintético: Cloud es el doble de `test_revalidacion_transporte_escritor`."""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest

import revalidar_transporte as cli
from atlas_core import reprocesamiento_reparador as m
from atlas_core.acciones_operacionales import CapaAccionesOperacionales
from atlas_core.escritor_operativo import LeaseEscritorOperativo, lease_desde_entorno
from atlas_core.revalidacion_documental import _escribir_filas_completas, _leer_filas
from tests.lectura_ocr_reparador import con_lectura
from tests.test_revalidacion_transporte_escritor import (
    TRANSPORTE, CloudEscritor, Fabrica, _dataset, _pesos, _pull, _raiz,
)


@pytest.fixture(autouse=True)
def sin_ocr_real(monkeypatch):
    monkeypatch.setattr(m, "crear_proveedor_ocr", lambda *a, **kw: object())


@pytest.fixture
def cloud():
    api = CloudEscritor()
    with patch("atlas_core.escritor_operativo._json", side_effect=api):
        yield api


@pytest.fixture
def reconciliaciones(monkeypatch):
    llamadas = []
    monkeypatch.setattr(m, "revalidar_y_regenerar_reporte", lambda **kw: llamadas.append(kw) or {"ok": True})
    return llamadas


def _marca(raiz):
    return raiz / "operacion" / "actual" / m.NOMBRE_MARCA_RECONCILIACION_PENDIENTE


def _perder_tras_escribir(raiz, monkeypatch):
    """Corrida que reescribe el dataset y pierde el lease antes de reconciliar."""
    monkeypatch.setattr(m, "procesar_archivo", con_lectura(lambda *a, **kw: {"peso_kg": "9307"}))
    vigencia = iter([True, True, True, False])  # doc1, doc2, escritura, reconciliación
    return m.revalidar_documentos_por_transporte(
        raiz_atlas=raiz, numero_transporte=TRANSPORTE, dry_run=False, proveedor=object(),
        puede_escribir=lambda: next(vigencia),
    )


# --- reconciliación recuperable ---

def test_perdida_tras_escribir_deja_marca_durable(tmp_path, reconciliaciones, monkeypatch):
    raiz = _raiz(tmp_path)

    resultado = _perder_tras_escribir(raiz, monkeypatch)

    assert resultado["dataset_escrito"] is True and resultado["reconciliacion_pendiente"] is True
    assert reconciliaciones == []
    assert json.loads(_marca(raiz).read_text(encoding="utf-8"))["transportes"] == [TRANSPORTE]
    assert _pesos(raiz) == ["9307", "9307"]


def test_recuperacion_sin_ocr_reconcilia_una_vez_sin_tocar_filas(tmp_path, cloud, reconciliaciones, monkeypatch):
    raiz = _raiz(tmp_path)
    _perder_tras_escribir(raiz, monkeypatch)
    filas_antes = _leer_filas(_dataset(raiz))
    monkeypatch.setattr(m, "procesar_archivo", con_lectura(lambda *a, **kw: pytest.fail("la recuperación no hace OCR")))

    resultado = cli.ejecutar_reconciliacion_pendiente_con_escritor(
        base_url="https://cloud.test", token_motor="t", raiz_atlas=raiz, fabrica_escritor=Fabrica(),
    )

    assert resultado["escritor_operativo"] == "ADQUIRIDO"
    assert resultado["transportes"] == [TRANSPORTE] and resultado["reconciliacion_pendiente"] is False
    assert len(reconciliaciones) == 1
    assert not _marca(raiz).exists()
    assert _leer_filas(_dataset(raiz)) == filas_antes  # ni duplica ni pierde filas
    assert cloud.token == ""
    # Segunda pasada: nada pendiente, no reconcilia otra vez.
    otra = cli.ejecutar_reconciliacion_pendiente_con_escritor(
        base_url="https://cloud.test", token_motor="t", raiz_atlas=raiz, fabrica_escritor=Fabrica(),
    )
    assert otra["reconciliacion_pendiente"] is False and len(reconciliaciones) == 1


def test_siguiente_revalidacion_completa_la_pendiente_en_una_sola_pasada(tmp_path, reconciliaciones, monkeypatch):
    raiz = _raiz(tmp_path)
    _perder_tras_escribir(raiz, monkeypatch)

    # Las filas ya están corregidas: esta corrida no tiene cambios propios.
    resultado = m.revalidar_documentos_por_transporte(
        raiz_atlas=raiz, numero_transporte=TRANSPORTE, dry_run=False, proveedor=object(),
        puede_escribir=lambda: True,
    )

    assert resultado["campos_cambiados_total"] == 0 and resultado["dataset_escrito"] is False
    assert resultado["reconciliaciones_pendientes_previas"] == [TRANSPORTE]
    assert len(reconciliaciones) == 1 and resultado["reconciliacion_pendiente"] is False
    assert not _marca(raiz).exists()
    assert len(_leer_filas(_dataset(raiz))) == 2


def test_corte_entre_marca_y_dataset_es_recuperable(tmp_path, reconciliaciones, monkeypatch):
    raiz = _raiz(tmp_path)
    monkeypatch.setattr(m, "procesar_archivo", con_lectura(lambda *a, **kw: {"peso_kg": "9307"}))

    def corte(_dataset, _filas):
        raise OSError("corte de energía")

    monkeypatch.setattr(m, "_escribir_filas_completas", corte)
    with pytest.raises(OSError):
        m.revalidar_documentos_por_transporte(
            raiz_atlas=raiz, numero_transporte=TRANSPORTE, dry_run=False, proveedor=object(),
            puede_escribir=lambda: True,
        )

    assert _marca(raiz).exists() and _pesos(raiz) == ["19307", "19307"]
    assert not (raiz / "operacion" / "actual" / ".atlas_lock_revalidacion_dataset").exists()
    resultado = m.completar_reconciliacion_pendiente(raiz_atlas=raiz, puede_escribir=lambda: True)
    assert resultado["reconciliacion_pendiente"] is False and len(reconciliaciones) == 1
    assert _pesos(raiz) == ["19307", "19307"]


def test_reconciliacion_que_falla_conserva_la_marca(tmp_path, monkeypatch):
    raiz = _raiz(tmp_path)
    monkeypatch.setattr(m, "procesar_archivo", con_lectura(lambda *a, **kw: {"peso_kg": "9307"}))

    def rota(**_kw):
        raise RuntimeError("reporte roto")

    monkeypatch.setattr(m, "revalidar_y_regenerar_reporte", rota)
    with pytest.raises(RuntimeError):
        m.revalidar_documentos_por_transporte(
            raiz_atlas=raiz, numero_transporte=TRANSPORTE, dry_run=False, proveedor=object(),
            puede_escribir=lambda: True,
        )

    assert _marca(raiz).exists()
    assert m.leer_reconciliacion_pendiente(raiz) == [TRANSPORTE]


def test_recuperacion_sin_escritor_no_reconcilia(tmp_path, reconciliaciones, monkeypatch):
    raiz = _raiz(tmp_path)
    _perder_tras_escribir(raiz, monkeypatch)

    resultado = m.completar_reconciliacion_pendiente(raiz_atlas=raiz, puede_escribir=lambda: False)

    assert resultado["escritor_operativo_perdido"] is True and resultado["reconciliacion_pendiente"] is True
    assert reconciliaciones == [] and _marca(raiz).exists()


def test_dry_run_informa_la_pendiente_sin_resolverla(tmp_path, reconciliaciones, monkeypatch):
    raiz = _raiz(tmp_path)
    _perder_tras_escribir(raiz, monkeypatch)

    resultado = m.revalidar_documentos_por_transporte(
        raiz_atlas=raiz, numero_transporte=TRANSPORTE, dry_run=True, proveedor=object(),
    )

    assert resultado["reconciliaciones_pendientes_previas"] == [TRANSPORTE]
    assert resultado["reconciliacion_pendiente"] is True
    assert reconciliaciones == [] and _marca(raiz).exists()


def test_marca_ilegible_cuenta_como_pendiente(tmp_path, reconciliaciones):
    raiz = _raiz(tmp_path)
    _marca(raiz).write_text("{corrupta", encoding="utf-8")

    assert m.leer_reconciliacion_pendiente(raiz) == ["MARCA_ILEGIBLE"]
    m.completar_reconciliacion_pendiente(raiz_atlas=raiz, puede_escribir=lambda: True)
    assert len(reconciliaciones) == 1 and not _marca(raiz).exists()


def test_cli_reconciliar_pendiente_respeta_al_pull(tmp_path, cloud, reconciliaciones, monkeypatch, capsys):
    raiz = _raiz(tmp_path)
    _perder_tras_escribir(raiz, monkeypatch)
    cloud.token = "lease-del-pull"
    monkeypatch.setenv("ATLAS_CLOUD_MOTOR_TOKEN", "t")
    monkeypatch.setattr("sys.argv", ["revalidar_transporte.py", "--raiz-atlas", str(raiz),
                                     "--reconciliar-pendiente", "--ejecutar"])

    with pytest.raises(SystemExit) as salida:
        cli.main()

    assert salida.value.code == 3
    assert '"escritor_operativo": "NO_ADQUIRIDO"' in capsys.readouterr().out
    assert reconciliaciones == [] and _marca(raiz).exists()
    assert cloud.token == "lease-del-pull"


@pytest.mark.parametrize("argumentos", [
    [],  # ni transporte ni recuperación
    ["--numero-transporte", TRANSPORTE, "--reconciliar-pendiente", "--ejecutar"],
    ["--reconciliar-pendiente"],  # sin --ejecutar
])
def test_cli_valida_modo(tmp_path, monkeypatch, argumentos):
    monkeypatch.setattr("sys.argv", ["revalidar_transporte.py", "--raiz-atlas", str(tmp_path), *argumentos])
    with pytest.raises(SystemExit) as salida:
        cli.main()
    assert salida.value.code == 2


# --- acción TRANSPORTE_REVALIDAR (Desktop / B1) ---

def _capa(raiz, fabrica):
    return CapaAccionesOperacionales(raiz, fabrica_escritor=fabrica)


def _preview(capa):
    preview = capa.previsualizar("TRANSPORTE_REVALIDAR", {"numero_transporte": TRANSPORTE}, actor="JAVIER")
    assert preview["estado"] == "PREVIEW", preview
    return preview["token"]


def _ejecutar(capa, token):
    return capa.ejecutar(token, actor="JAVIER", confirmado_por="JAVIER", autorizacion_sensible=True)


def _fabrica_accion():
    instancias = []

    def fabrica():
        lease = LeaseEscritorOperativo(
            base_url="https://cloud.test", token_motor="t", escritor_id="pc-oficina",
            heartbeat_segundos=0, margen_relevo_segundos=0,
        )
        instancias.append(lease)
        return lease

    fabrica.instancias = instancias
    return fabrica


def _respaldos(raiz):
    carpeta = raiz / "respaldos" / "acciones_operacionales"
    return list(carpeta.iterdir()) if carpeta.exists() else []


def test_accion_con_pull_activo_no_respalda_ni_escribe_y_el_token_sigue_valido(
        tmp_path, cloud, reconciliaciones, monkeypatch):
    raiz = _raiz(tmp_path)
    monkeypatch.setattr(m, "procesar_archivo", con_lectura(lambda *a, **kw: {"peso_kg": "9307"}))
    capa = _capa(raiz, _fabrica_accion())
    token = _preview(capa)
    cloud.token = "lease-del-pull"

    rechazo = _ejecutar(capa, token)

    assert rechazo["estado"] == "RECHAZADA" and rechazo["codigo"] == "ESCRITOR_OCUPADO"
    assert _respaldos(raiz) == [] and _pesos(raiz) == ["19307", "19307"] and capa.auditoria() == []
    assert cloud.token == "lease-del-pull"
    # Terminado el PULL, el MISMO token se ejecuta.
    cloud.token = ""
    aplicada = _ejecutar(capa, token)
    assert aplicada["estado"] == "APLICADA", aplicada
    assert _pesos(raiz) == ["9307", "9307"] and len(reconciliaciones) == 1
    assert cloud.token == "" and cloud.liberaciones == 1


def test_accion_sin_token_cloud_no_ejecuta(tmp_path, monkeypatch):
    raiz = _raiz(tmp_path)
    monkeypatch.setattr(m, "procesar_archivo", con_lectura(lambda *a, **kw: pytest.fail("sin escritor no hay OCR")))
    capa = CapaAccionesOperacionales(raiz)  # fábrica por defecto: lee el entorno (conftest quita el token)

    rechazo = _ejecutar(capa, _preview(capa))

    assert rechazo["codigo"] == "ESCRITOR_NO_DISPONIBLE"
    assert _respaldos(raiz) == [] and _pesos(raiz) == ["19307", "19307"]


def test_accion_activa_bloquea_al_pull(tmp_path, cloud, reconciliaciones, monkeypatch):
    raiz = _raiz(tmp_path)
    pulls = []

    def ocr(*_a, **_kw):
        pulls.append(_pull(Fabrica(), lambda **_k: {"confirmados": ["x"]}))
        return {"peso_kg": "9307"}

    monkeypatch.setattr(m, "procesar_archivo", con_lectura(ocr))
    capa = _capa(raiz, _fabrica_accion())

    assert _ejecutar(capa, _preview(capa))["estado"] == "APLICADA"
    assert pulls and all(r["escritor_operativo"] == "NO_ADQUIRIDO" and not p.called for r, p in pulls)
    assert cloud.token == ""


def test_accion_con_lease_perdido_no_restaura_encima_del_pull(tmp_path, cloud, reconciliaciones, monkeypatch):
    raiz = _raiz(tmp_path)
    fabrica = _fabrica_accion()

    def ocr_y_relevo(*_a, **_kw):
        # El lease vence, otro escritor lo toma y agrega una fila.
        cloud.vencer()
        assert not fabrica.instancias[-1].renovar()
        filas = _leer_filas(_dataset(raiz))
        nueva = dict(filas[0], archivo="PULL.jpg", numero_guia="999999", numero_transporte="0000999999")
        _escribir_filas_completas(_dataset(raiz), [*filas, nueva])
        return {"peso_kg": "9307"}

    monkeypatch.setattr(m, "procesar_archivo", con_lectura(ocr_y_relevo))
    capa = _capa(raiz, fabrica)

    resultado = _ejecutar(capa, _preview(capa))

    assert resultado["estado"] == "FALLIDA" and resultado["codigo"] == "ESCRITOR_PERDIDO"
    assert resultado["respaldo_restaurado"] is False
    archivos = [f["archivo"] for f in _leer_filas(_dataset(raiz))]
    assert "PULL.jpg" in archivos  # la fila del otro escritor sobrevive
    assert _pesos(raiz)[:2] == ["19307", "19307"] and reconciliaciones == []


def test_accion_con_error_y_lease_vigente_restaura_y_libera(tmp_path, cloud, monkeypatch):
    raiz = _raiz(tmp_path)
    monkeypatch.setattr(m, "procesar_archivo", con_lectura(lambda *a, **kw: {"peso_kg": "9307"}))

    def rota(**_kw):
        raise RuntimeError("reporte roto")

    monkeypatch.setattr(m, "revalidar_y_regenerar_reporte", rota)
    capa = _capa(raiz, _fabrica_accion())

    resultado = _ejecutar(capa, _preview(capa))

    assert resultado["estado"] == "FALLIDA" and resultado["respaldo_restaurado"] is True
    assert _pesos(raiz) == ["19307", "19307"]
    assert _marca(raiz).exists()  # restaurado, pero la reconciliación sigue pendiente (inocua)
    assert cloud.token == "" and cloud.liberaciones == 1
    assert not (raiz / "operacion" / "actual" / ".atlas_lock_acciones_operacionales").exists()


def test_lease_desde_entorno(monkeypatch):
    monkeypatch.delenv("ATLAS_CLOUD_MOTOR_TOKEN", raising=False)
    assert lease_desde_entorno() is None
    monkeypatch.setenv("ATLAS_CLOUD_MOTOR_TOKEN", "t")
    monkeypatch.delenv("ATLAS_CLOUD_MOBILE_URL", raising=False)
    monkeypatch.setenv("ATLAS_ESCRITOR_ID", "pc-prueba")  # no lee ni crea la identidad real
    lease = lease_desde_entorno(timeout=5)
    assert lease.base_url.startswith("https://") and lease.token_motor == "t" and not lease.vigente
