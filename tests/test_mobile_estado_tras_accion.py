"""Convergencia focal del envío Mobile al cerrar una acción operacional --
caso real 482559 (envío bd67b564, 2026-10-20): la corrección de patentes
dejó la fila y el viaje OK, pero el envío siguió REQUIERE_REVISION hasta
que llegara OTRO envío (único disparador del barrido Mobile). Fixtures
sintéticas; nunca G:."""
from __future__ import annotations

import csv
import hashlib
import uuid

from atlas_core import mobile
from atlas_core.acciones_operacionales import CapaAccionesOperacionales
from atlas_core.mobile import RepositorioEnviosMobile
from tests.test_acciones_operacionales import entorno  # noqa: F401 -- fixture

TRANSPORTE = "0000900001"


def _sin_ocr(monkeypatch):
    def prohibido(*_a, **_k):
        raise AssertionError("la convergencia Mobile nunca corre OCR")
    monkeypatch.setattr(mobile, "crear_proveedor_ocr", prohibido)


def _envio(repo: RepositorioEnviosMobile, guia: str) -> str:
    envio_id = str(uuid.uuid4())
    repo.recibir(envio_id=envio_id, imagen=b"foto", mime="image/jpeg",
                 metadata={"chofer_id": "123456785", "tipo_novedad": "", "guia_firmada_correo": False,
                           "planta_origen_informada": "AZA_COLINA"})
    registro = repo.cargar(envio_id)
    registro["foto_original"] = "original.jpg"
    registro["datos_ocr"] = {"numero_guia": guia, "numero_transporte": TRANSPORTE, "indicador_revision": "REVISAR"}
    registro["resultado_asociacion"] = {
        "estado": "ASOCIADO_AUTOMATICAMENTE", "numero_transporte": TRANSPORTE, "numero_guia": guia,
        "candidatos": [TRANSPORTE], "motivo": "Coincidencia exacta determinista de guía/transporte.",
        "documento_ya_existe": False,
    }
    registro["estado"] = "REQUIERE_REVISION"
    repo.guardar(envio_id, registro)
    return envio_id


def _preparar(entorno, *, motivos_a: str):  # noqa: F811
    """500001 = envío A (tracto leído mal, como 482559); 500002 = envío B,
    otra guía cuyo envío también está en revisión y nunca debe tocarse."""
    repo = RepositorioEnviosMobile(entorno["raiz"])
    a, b = _envio(repo, "500001"), _envio(repo, "500002")
    ruta = entorno["dataset"]
    with ruta.open(encoding="utf-8-sig", newline="") as flujo:
        lector = csv.DictReader(flujo, delimiter=";")
        columnas, filas = lector.fieldnames, list(lector)
    for fila in filas:
        if fila["numero_guia"] == "500001":
            fila.update({"archivo": f"mobile/{a}/original.jpg", "patente_tracto": "JF9575",
                         "motivos_revision_documento": motivos_a, "indicador_revision": "REVISAR",
                         "estado_documental": "REQUIERE_REVISION", "estado_operacional": "REQUIERE_REVISION"})
        else:
            fila.update({"archivo": f"mobile/{b}/original.jpg", "indicador_revision": "REVISAR",
                         "motivos_revision_documento": "OBRA_DESTINO_SIN_CORROBORAR"})
    with ruta.open("w", encoding="utf-8-sig", newline="") as flujo:
        escritor = csv.DictWriter(flujo, fieldnames=columnas, delimiter=";")
        escritor.writeheader()
        escritor.writerows(filas)
    return repo, a, b


def _corregir(capa, campo, valor):
    p = capa.previsualizar("DOCUMENTO_CORREGIR_CAMPO", {"numero_guia": "500001", "campo": campo, "valor": valor},
                           actor="CLAUDE_CODE_OPERADOR_OFICINA")
    assert p["estado"] == "PREVIEW", p
    r = capa.ejecutar(p["token"], actor="CLAUDE_CODE_OPERADOR_OFICINA", confirmado_por="JAVIER_MBT")
    assert r["estado"] == "APLICADA", r
    return r


def _fila(entorno, guia):  # noqa: F811
    with entorno["dataset"].open(encoding="utf-8-sig", newline="") as flujo:
        return next(f for f in csv.DictReader(flujo, delimiter=";") if f["numero_guia"] == guia)


def _sha_envio(repo, envio_id):
    return hashlib.sha256((repo.raiz / envio_id / "envio.json").read_bytes()).hexdigest()


def test_correccion_que_deja_la_fila_ok_converge_solo_su_envio(entorno, monkeypatch):  # noqa: F811
    _sin_ocr(monkeypatch)
    repo, a, b = _preparar(entorno, motivos_a="PATENTE_SIN_HOMOLOGAR")
    sha_b = _sha_envio(repo, b)

    r = _corregir(CapaAccionesOperacionales(entorno["raiz"]), "patente_tracto", "KN5439")

    assert _fila(entorno, "500001")["indicador_revision"] == "OK"
    registro = repo.cargar(a)
    assert registro["estado"] == "ASOCIADO"
    assert registro["resultado_asociacion"]["estado"] == "ASOCIADO_AUTOMATICAMENTE"  # nunca se reinventa
    traza = registro["convergencias_estado"][-1]
    assert traza["origen"] == "ACCION_OPERACIONAL" and traza["accion"] == "DOCUMENTO_CORREGIR_CAMPO"
    assert traza["token"] == r["token"] and traza["confirmado_por"] == "JAVIER_MBT"
    assert (traza["estado_anterior"], traza["estado_nuevo"]) == ("REQUIERE_REVISION", "ASOCIADO")
    assert r["revalidacion"]["mobile"]["envios"] == [a]
    assert r["revalidacion"]["mobile"]["actualizados"] == [a]
    assert _sha_envio(repo, b) == sha_b  # el envío de otra guía queda byte a byte


def test_correccion_que_deja_revisiones_reales_no_marca_ok(entorno, monkeypatch):  # noqa: F811
    _sin_ocr(monkeypatch)
    repo, a, _ = _preparar(entorno, motivos_a="PATENTE_SIN_HOMOLOGAR")

    r = _corregir(CapaAccionesOperacionales(entorno["raiz"]), "obra_destino", "OBRA NUEVA SA")

    assert _fila(entorno, "500001")["indicador_revision"] == "REVISAR"  # la patente sigue sin homologar
    registro = repo.cargar(a)
    assert registro["estado"] == "REQUIERE_REVISION"
    assert "convergencias_estado" not in registro
    assert r["revalidacion"]["mobile"]["actualizados"] == []


def test_fallo_de_convergencia_mobile_no_deshace_la_accion(entorno, monkeypatch):  # noqa: F811
    _sin_ocr(monkeypatch)
    repo, a, _ = _preparar(entorno, motivos_a="PATENTE_SIN_HOMOLOGAR")

    def falla(*_a, **_k):
        raise OSError("disco")
    monkeypatch.setattr(mobile, "converger_envios_mobile_de_guias", falla)

    r = _corregir(CapaAccionesOperacionales(entorno["raiz"]), "patente_tracto", "KN5439")

    assert _fila(entorno, "500001")["patente_tracto"] == "KN5439"
    assert r["revalidacion"]["mobile"] == {"estado": "ERROR", "error": "OSError: disco"}
    assert repo.cargar(a)["estado"] == "REQUIERE_REVISION"


def _marcar_fila_ok(entorno, guia):  # noqa: F811
    """Estado real de 482559 tras la corrección de las 11:08: fila OK, envío no."""
    ruta = entorno["dataset"]
    with ruta.open(encoding="utf-8-sig", newline="") as flujo:
        lector = csv.DictReader(flujo, delimiter=";")
        columnas, filas = lector.fieldnames, list(lector)
    for fila in filas:
        if fila["numero_guia"] == guia:
            fila.update({"motivos_revision_documento": "", "indicador_revision": "OK",
                         "estado_documental": "OK", "estado_operacional": "OK", "patente_tracto": "KN5439"})
    with ruta.open("w", encoding="utf-8-sig", newline="") as flujo:
        escritor = csv.DictWriter(flujo, fieldnames=columnas, delimiter=";")
        escritor.writeheader()
        escritor.writerows(filas)


def test_accion_recalcular_estado_mobile_converge_envio_ya_desfasado(entorno, monkeypatch):  # noqa: F811
    _sin_ocr(monkeypatch)
    repo, a, b = _preparar(entorno, motivos_a="PATENTE_SIN_HOMOLOGAR")
    _marcar_fila_ok(entorno, "500001")
    sha_a, sha_b = _sha_envio(repo, a), _sha_envio(repo, b)
    capa = CapaAccionesOperacionales(entorno["raiz"])

    p = capa.previsualizar("MOBILE_RECALCULAR_ESTADO", {"numero_guia": "500001"}, actor="CLAUDE_CODE_OPERADOR_OFICINA")
    assert p["estado"] == "PREVIEW", p
    assert p["valor_actual"] == {"estados": {a: "REQUIERE_REVISION"}}
    assert p["valor_propuesto"] == {"estados": {a: "ASOCIADO"}}
    assert _sha_envio(repo, a) == sha_a  # el preview no escribe

    r = capa.ejecutar(p["token"], actor="CLAUDE_CODE_OPERADOR_OFICINA", confirmado_por="JAVIER_MBT")
    assert r["estado"] == "APLICADA", r
    assert r["despues"] == {"estados": {a: "ASOCIADO"}, "actualizados": [a]}
    traza = repo.cargar(a)["convergencias_estado"]
    assert len(traza) == 1 and traza[0]["accion"] == "MOBILE_RECALCULAR_ESTADO" and traza[0]["token"] == p["token"]
    assert _sha_envio(repo, b) == sha_b
    assert capa.auditoria()[-1]["accion"] == "MOBILE_RECALCULAR_ESTADO"

    otra = capa.previsualizar("MOBILE_RECALCULAR_ESTADO", {"numero_guia": "500001"}, actor="CLAUDE_CODE_OPERADOR_OFICINA")
    assert otra["estado"] == "SIN_CAMBIOS", otra


def test_accion_recalcular_estado_mobile_respeta_revision_real(entorno, monkeypatch):  # noqa: F811
    _sin_ocr(monkeypatch)
    repo, a, _ = _preparar(entorno, motivos_a="PATENTE_SIN_HOMOLOGAR")
    p = CapaAccionesOperacionales(entorno["raiz"]).previsualizar(
        "MOBILE_RECALCULAR_ESTADO", {"numero_guia": "500001"}, actor="CLAUDE_CODE_OPERADOR_OFICINA")
    assert p["estado"] == "SIN_CAMBIOS", p
    assert repo.cargar(a)["estado"] == "REQUIERE_REVISION"


def test_documento_no_mobile_no_toca_envios(entorno, monkeypatch):  # noqa: F811
    _sin_ocr(monkeypatch)
    r = _corregir(CapaAccionesOperacionales(entorno["raiz"]), "obra_destino", "OBRA NUEVA SA")
    assert r["revalidacion"]["mobile"] == {"envios": [], "revisados": 0, "actualizados": [], "estados": {}}
