"""SOAP, revisión técnica y permiso de circulación desde Mobile -> ficha del vehículo.

Sólo datos sintéticos en tmp_path; Cloud se simula parcheando `_json` y
`_descargar` del consumidor. Asignaciones con la misma regla de la ficha
(`asignaciones_de_chofer`) sobre un catálogo de vehículos sintético.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from atlas_core import cloud_fichas_documentos as consumidor
from atlas_core import fichas_vehiculos as modulo
from atlas_core.catalogo_vehiculos import TipoVehiculo, asociar_chofer_a_vehiculo_confirmado
from atlas_core.fichas_choferes import inicializar_almacen, leer_almacen, ruta_almacen
from atlas_core.fichas_vehiculos import PENDIENTES, registrar_documento_vehiculo_mobile
from tests.test_motor_evidencia_vehiculos import _catalogo, _confirmar

SOLO, COMBO, CONFLICTO, INACTIVO = "97082251", "180915885", "10833150K", "78143109"
sha = lambda b: hashlib.sha256(b).hexdigest()
JPEG = lambda texto: b"\xff\xd8\xff\xe0" + texto.encode()
PDF = b"%PDF-1.4 permiso ficticio"


def _asignar(ruta, patente, rut, dia):
    asociar_chofer_a_vehiculo_confirmado(ruta, patente=patente, actor="JAVIER", fuente_decision="TEST",
                                         rut_chofer_asociado=rut, fecha=datetime(2026, 10, dia, tzinfo=timezone.utc))


@pytest.fixture
def raiz(tmp_path):
    carpeta = tmp_path / "catalogos_privados"; carpeta.mkdir()
    ruta = _catalogo(carpeta)
    for patente, tipo in (("CC5678", TipoVehiculo.TRACTO), ("TG8925", TipoVehiculo.TRACTO), ("JF9575", TipoVehiculo.CARRO),
                          ("ND6443", TipoVehiculo.TRACTO), ("BB1234", TipoVehiculo.TRACTO), ("DD9012", TipoVehiculo.TRACTO)):
        _confirmar(ruta, patente, tipo)
    _asignar(ruta, "CC5678", SOLO, 1)        # sólo un tracto: inequívoco
    _asignar(ruta, "TG8925", COMBO, 1)       # tracto + carro: ambiguo
    _asignar(ruta, "JF9575", COMBO, 1)
    _asignar(ruta, "ND6443", CONFLICTO, 1)   # dos tractos vigentes: conflicto
    _asignar(ruta, "BB1234", CONFLICTO, 2)
    _asignar(ruta, "DD9012", INACTIVO, 1)
    (carpeta / "choferes.json").write_text(json.dumps({
        SOLO: {"nombre": "SOLO SINTETICO", "activo": True}, COMBO: {"nombre": "COMBO SINTETICO", "activo": True},
        CONFLICTO: {"nombre": "CONFLICTO SINTETICO", "activo": True},
        INACTIVO: {"nombre": "INACTIVO SINTETICO", "activo": False},
    }), encoding="utf-8")
    (tmp_path / "operacion" / "actual").mkdir(parents=True)
    inicializar_almacen(tmp_path, empresa="MBT", actor="TEST")
    return tmp_path


def _registrar(raiz, origen="dfv_1", *, chofer=SOLO, tipo="SOAP", patente="CC5678", contenido=None, mime="image/jpeg",
               comprobar=lambda: None, **cambios):
    contenido = JPEG(f"{tipo}-{origen}") if contenido is None else contenido
    argumentos = dict(empresa="MBT", origen_documento_id=origen, chofer_id=chofer, tipo=tipo, patente_cloud=patente,
                      recibido_en="2026-11-02T13:00:00Z", contenido=contenido, mime_type=mime, sha256=sha(contenido),
                      comprobar=comprobar, actor=f"MOBILE:{chofer}")
    argumentos.update(cambios)
    return registrar_documento_vehiculo_mobile(raiz, **argumentos)


def _datos(raiz):
    return leer_almacen(raiz, empresa="MBT")


def _vehiculo(raiz, patente):
    return next((v for v in _datos(raiz)["vehiculos"] if v["patente"] == patente), None)


def _archivo(raiz, relativo):
    return (ruta_almacen(raiz, "MBT").parent / relativo).read_bytes()


# ---------------------------------------------------------------- asociación inequívoca


@pytest.mark.parametrize("tipo,contenido,mime", [
    ("SOAP", JPEG("soap"), "image/jpeg"), ("REVISION_TECNICA", JPEG("rt"), "image/jpeg"),
    ("PERMISO_CIRCULACION", PDF, "application/pdf"),
])
def test_cada_tipo_se_asocia_al_tracto_unico_confirmado_sin_vencimiento_ni_revision(raiz, tipo, contenido, mime):
    r = _registrar(raiz, tipo=tipo, contenido=contenido, mime=mime)
    assert r["patente"] == "CC5678" and not r["motivo"] and not r["duplicado"]
    [doc] = _vehiculo(raiz, "CC5678")["documentos"]
    assert doc["tipo"] == tipo and doc["estado_revision"] == "PENDIENTE_EXTRACCION"
    assert "vencimiento" not in doc and "confirmacion_humana" not in doc
    assert doc["sha256"] == sha(contenido) and _archivo(raiz, doc["archivo"]) == contenido
    assert doc["archivo"].startswith("archivos/vehiculos/CC5678/")
    assert doc["origen"] == "MOBILE" and doc["origen_documento_id"] == "dfv_1"
    assert doc["procedencia"] == {"chofer_id": SOLO, "patente_cloud": "CC5678", "recibido_en": "2026-11-02T13:00:00Z"}
    assert doc["asociacion"]["metodo"] == "ASIGNACION_CONFIRMADA" and doc["asociacion"]["chofer_id"] == SOLO
    evento = _vehiculo(raiz, "CC5678")["historial"][-1]
    assert evento["accion"] == "DOCUMENTO_VEHICULO_RECIBIDO_MOBILE" and evento["sha256"] == sha(contenido)
    manifiestos = [json.loads(p.read_text(encoding="utf-8")) for p in (raiz / "respaldos" / "fichas_choferes").glob("*/manifest.json")]
    assert any(m["operacion"] == "DOCUMENTO_VEHICULO_RECIBIDO_MOBILE" and m["patente"] == "CC5678" for m in manifiestos)


def test_documentos_quedan_en_el_vehiculo_aunque_cambie_el_chofer(raiz):
    _registrar(raiz, "dfv_1", tipo="SOAP")
    ruta = raiz / "catalogos_privados" / "vehiculos.json"
    # El tracto pasa a otro chofer: el documento anterior sigue en el vehículo.
    _asignar(ruta, "CC5678", COMBO, 5)
    vehiculo = _vehiculo(raiz, "CC5678")
    assert [d["origen_documento_id"] for d in vehiculo["documentos"]] == ["dfv_1"]
    assert len(_datos(raiz)["vehiculos"]) == 1


# ---------------------------------------------------------------- abstención


@pytest.mark.parametrize("chofer,patente,motivo,candidatos", [
    (COMBO, "TG8925", "TRACTO_Y_CARRO", ["JF9575", "TG8925"]),
    (CONFLICTO, "ND6443", "SIN_ASIGNACION_CONFIRMADA", ["BB1234", "ND6443"]),
    (SOLO, "TG8925", "ASIGNACION_DISTINTA", ["CC5678"]),
    (INACTIVO, "DD9012", "CHOFER_NO_VIGENTE", []),
    ("PENDIENTE00000009", "CC5678", "CHOFER_NO_VIGENTE", []),
    (SOLO, "", "SIN_PATENTE_CLOUD", []),
])
def test_sin_vehiculo_inequivoco_queda_pendiente_de_clasificacion_sin_patente(raiz, chofer, patente, motivo, candidatos):
    contenido = JPEG(f"ambiguo-{motivo}")
    r = _registrar(raiz, chofer=chofer, patente=patente, tipo="REVISION_TECNICA", contenido=contenido)
    assert (r["patente"], r["motivo"]) == (None, motivo)
    datos = _datos(raiz)
    assert datos["vehiculos"] == []  # ninguna patente inventada
    [doc] = datos[PENDIENTES]
    assert doc["clasificacion"] == {"estado": "PENDIENTE_CLASIFICACION", "motivo": motivo,
                                    "patente_cloud": patente, "candidatos": candidatos}
    assert doc["estado_revision"] == "PENDIENTE_EXTRACCION" and "asociacion" not in doc
    assert doc["archivo"].startswith("archivos/vehiculos/sin_clasificar/") and _archivo(raiz, doc["archivo"]) == contenido
    assert doc["historial"][-1]["motivo"] == motivo


# ---------------------------------------------------------------- idempotencia y duplicados


def test_mismo_documento_cloud_es_idempotente(raiz):
    primero = _registrar(raiz, "dfv_1")
    revision = _datos(raiz)["revision"]
    segundo = _registrar(raiz, "dfv_1")
    assert segundo["idempotente"] and segundo["documento_id"] == primero["documento_id"]
    assert _datos(raiz)["revision"] == revision


def test_mismo_archivo_desde_otro_envio_no_duplica(raiz):
    contenido = JPEG("soap-repetido")
    primero = _registrar(raiz, "dfv_1", contenido=contenido)
    segundo = _registrar(raiz, "dfv_2", contenido=contenido)
    assert segundo["duplicado"] and segundo["documento_id"] == primero["documento_id"]
    [doc] = _vehiculo(raiz, "CC5678")["documentos"]
    assert doc["origenes_adicionales"] == ["dfv_2"] and doc["procedencias_adicionales"][0]["chofer_id"] == SOLO
    assert len(list((ruta_almacen(raiz, "MBT").parent / "archivos" / "vehiculos" / "CC5678").iterdir())) == 1
    assert _vehiculo(raiz, "CC5678")["historial"][-1]["accion"] == "DOCUMENTO_VEHICULO_REPETIDO"
    assert _registrar(raiz, "dfv_2", contenido=contenido)["idempotente"]
    # Otro tipo con los mismos bytes sí es otro documento.
    assert not _registrar(raiz, "dfv_3", contenido=contenido, tipo="PERMISO_CIRCULACION")["duplicado"]


# ---------------------------------------------------------------- rechazos y persistencia


@pytest.mark.parametrize("cambios,motivo", [
    ({"sha256": "0" * 64}, "huella"),
    ({"mime_type": "image/png"}, "no corresponde"),
    ({"tipo": "TIPO_DESCONOCIDO"}, "no admitido"),
    ({"tipo": "LICENCIA_CONDUCIR"}, "no admitido"),
    ({"chofer_id": ""}, "sin chofer"),
])
def test_rechazos_no_escriben_nada(raiz, cambios, motivo):
    antes = ruta_almacen(raiz, "MBT").read_bytes()
    with pytest.raises(ValueError, match=motivo):
        _registrar(raiz, **cambios)
    assert ruta_almacen(raiz, "MBT").read_bytes() == antes
    assert not (ruta_almacen(raiz, "MBT").parent / "archivos" / "vehiculos").exists() or \
        not any(p.is_file() for p in (ruta_almacen(raiz, "MBT").parent / "archivos" / "vehiculos").rglob("*"))


def test_fallo_al_persistir_borra_el_original_escrito_y_no_publica(raiz, monkeypatch):
    antes = ruta_almacen(raiz, "MBT").read_bytes()
    real = modulo.escribir_json_atomico

    def falla(ruta, datos):
        if Path(ruta).name == "fichas_documentales.json":
            raise OSError("disco lleno")
        return real(ruta, datos)

    monkeypatch.setattr(modulo, "escribir_json_atomico", falla)
    with pytest.raises(OSError):
        _registrar(raiz)
    assert ruta_almacen(raiz, "MBT").read_bytes() == antes
    assert not any(p.is_file() for p in (ruta_almacen(raiz, "MBT").parent / "archivos" / "vehiculos").rglob("*"))


def test_lease_perdido_no_publica(raiz):
    antes = ruta_almacen(raiz, "MBT").read_bytes()
    llamadas = []

    def perdido():
        llamadas.append(1)
        if len(llamadas) > 1:
            raise PermissionError("lease perdido")

    with pytest.raises(PermissionError):
        _registrar(raiz, comprobar=perdido)
    assert ruta_almacen(raiz, "MBT").read_bytes() == antes
    assert not any(p.is_file() for p in (ruta_almacen(raiz, "MBT").parent / "archivos" / "vehiculos").rglob("*"))


def test_catalogo_de_vehiculos_ilegible_no_clasifica_ni_publica(raiz):
    (raiz / "catalogos_privados" / "vehiculos.json").write_text("{", encoding="utf-8")
    antes = ruta_almacen(raiz, "MBT").read_bytes()
    with pytest.raises(ValueError):
        _registrar(raiz)
    assert ruta_almacen(raiz, "MBT").read_bytes() == antes


# ---------------------------------------------------------------- PULL (Cloud simulado)


class CloudFalso:
    def __init__(self, documentos):
        self.documentos, self.confirmados, self.rutas = documentos, [], []

    def json(self, base_url, ruta, token, *, method="GET", body=None, timeout):
        self.rutas.append((ruta, body))
        if ruta.split("?")[0].endswith("/pendientes"):
            return {"documentos": [{k: d[k] for k in ("documento_id", "titular", "tipo")} for d in self.documentos]}
        documento_id = ruta.split("/")[-2]
        doc = next(d for d in self.documentos if d["documento_id"] == documento_id)
        if ruta.endswith("/lease"):
            return {**{k: v for k, v in doc.items() if k not in ("contenido", "sha_cloud")}, "formato": "UNICA",
                    "sha256": doc.get("sha_cloud", sha(doc["contenido"])),
                    "lease_token": f"lt-{documento_id}", "descarga_url": f"https://cloud.test/{documento_id}"}
        if ruta.endswith("/confirmar"):
            self.confirmados.append((documento_id, body["resultado"]))
            assert body["lease_token"] == f"lt-{documento_id}"
            return {"estado": "COMPLETADO"}
        raise AssertionError(ruta)

    def descargar(self, url, *, esperado_bytes, timeout):
        doc = next(d for d in self.documentos if url.endswith(d["documento_id"]))
        assert esperado_bytes == len(doc["contenido"])
        return doc["contenido"]


def _doc_cloud(documento_id, tipo, chofer, patente, contenido, titular="VEHICULO"):
    return {"documento_id": documento_id, "titular": titular, "tipo": tipo, "chofer_id": chofer, "patente": patente,
            "mime_type": "image/jpeg", "bytes": len(contenido), "recibido_en": "2026-11-02T13:00:00Z",
            "contenido": contenido}


def _sincronizar(raiz, cloud):
    with patch.object(consumidor, "_json", cloud.json), patch.object(consumidor, "_descargar", cloud.descargar):
        return consumidor.sincronizar_licencias_cloud(base_url="https://cloud.test", token_motor="t", consumidor="JAVO",
                                                      raiz=raiz, timeout=1, puede_continuar=lambda: True)


def test_pull_recibe_los_tres_tipos_y_licencias_con_su_resultado_propio(raiz):
    licencia = JPEG("licencia")
    cloud = CloudFalso([
        _doc_cloud("dfv_soap", "SOAP", SOLO, "CC5678", JPEG("soap")),
        _doc_cloud("dfv_rt", "REVISION_TECNICA", COMBO, "TG8925", JPEG("rt")),
        _doc_cloud("dfv_pc", "PERMISO_CIRCULACION", SOLO, "CC5678", JPEG("pc")),
        {**_doc_cloud("dfm_lic", "LICENCIA_CONDUCIR", SOLO, "", licencia, titular="CHOFER"), "sha256": sha(licencia)},
    ])
    resumen = _sincronizar(raiz, cloud)
    assert not resumen["errores"] and not resumen["sin_vincular"]
    assert cloud.confirmados == [("dfv_soap", "RECIBIDO_PENDIENTE_REVISION"), ("dfv_rt", "RECIBIDO_PENDIENTE_REVISION"),
                                 ("dfv_pc", "RECIBIDO_PENDIENTE_REVISION"), ("dfm_lic", "PENDIENTE_EXTRACCION")]
    assert [(v["documento_id"], v["patente"], v["motivo"]) for v in resumen["vehiculos"]] == [
        ("dfv_soap", "CC5678", ""), ("dfv_rt", None, "TRACTO_Y_CARRO"), ("dfv_pc", "CC5678", "")]
    assert [i["documento_id"] for i in resumen["incorporados"]] == ["dfm_lic"]
    assert cloud.rutas[0][0].endswith("&tipos=SOAP,REVISION_TECNICA,PERMISO_CIRCULACION,SEGURO_CARGA")
    assert sorted(d["tipo"] for d in _vehiculo(raiz, "CC5678")["documentos"]) == ["PERMISO_CIRCULACION", "SOAP"]
    # Un segundo ciclo con lo mismo no duplica nada.
    revision = _datos(raiz)["revision"]
    _sincronizar(raiz, cloud)
    assert _datos(raiz)["revision"] == revision


def test_pull_con_sha_incorrecto_no_escribe_ni_confirma(raiz):
    cloud = CloudFalso([{**_doc_cloud("dfv_soap", "SOAP", SOLO, "CC5678", JPEG("soap")), "sha_cloud": "0" * 64}])
    antes = ruta_almacen(raiz, "MBT").read_bytes()
    resumen = _sincronizar(raiz, cloud)
    assert resumen["errores"] and cloud.confirmados == []
    assert ruta_almacen(raiz, "MBT").read_bytes() == antes


def test_pull_con_fallo_de_persistencia_no_confirma_y_sigue_con_los_demas(raiz, monkeypatch):
    real = modulo.escribir_json_atomico
    fallar = {"dfv_1"}

    def falla(ruta, datos):
        if Path(ruta).name == "fichas_documentales.json" and any(
                d.get("origen_documento_id") in fallar for v in datos.get("vehiculos", []) for d in v["documentos"]):
            raise OSError("Drive no disponible")
        return real(ruta, datos)

    monkeypatch.setattr(modulo, "escribir_json_atomico", falla)
    cloud = CloudFalso([_doc_cloud("dfv_1", "SOAP", SOLO, "CC5678", JPEG("a")),
                        _doc_cloud("dfv_2", "PERMISO_CIRCULACION", SOLO, "CC5678", JPEG("b"))])
    resumen = _sincronizar(raiz, cloud)
    assert [s["documento_id"] for s in resumen["sin_vincular"]] == ["dfv_1"]
    assert cloud.confirmados == [("dfv_2", "RECIBIDO_PENDIENTE_REVISION")]
    assert [d["origen_documento_id"] for d in _vehiculo(raiz, "CC5678")["documentos"]] == ["dfv_2"]


def test_pull_no_toma_tipos_no_admitidos(raiz):
    cloud = CloudFalso([_doc_cloud("dfv_seguro", "TIPO_DESCONOCIDO", SOLO, "CC5678", JPEG("seguro"))])
    resumen = _sincronizar(raiz, cloud)
    assert resumen["vehiculos"] == [] and cloud.confirmados == []
    assert all(not r.endswith("/lease") for r, _ in cloud.rutas)


def test_seguro_cloud_se_recibe_sin_patente_y_sin_activar_ocr(raiz):
    from atlas_core.identificacion_patentes import _por_identificar
    contenido = JPEG("seguro carga")
    cloud = CloudFalso([_doc_cloud("seguro_1", "SEGURO_CARGA", SOLO, "", contenido)])
    resumen = _sincronizar(raiz, cloud)
    assert not resumen["errores"] and not resumen["sin_vincular"]
    assert cloud.confirmados == [("seguro_1", "RECIBIDO_PENDIENTE_REVISION")]
    assert resumen["vehiculos"][0]["patente"] is None
    doc = _datos(raiz)[PENDIENTES][0]
    assert doc["tipo"] == "SEGURO_CARGA" and doc["procedencia"]["chofer_id"] == SOLO
    assert doc["clasificacion"]["motivo"] == "SEGURO_SIN_VEHICULO_ACREDITADO"
    assert "asociacion" not in doc and not _por_identificar(doc)
    assert _archivo(raiz, doc["archivo"]) == contenido and doc["sha256"] == sha(contenido)
    assert _datos(raiz)["vehiculos"] == []
    revision = _datos(raiz)["revision"]
    _sincronizar(raiz, cloud)
    assert _datos(raiz)["revision"] == revision


def test_seguro_deduplica_por_remitente_y_no_acepta_patente(raiz):
    original = JPEG("mismo seguro")
    primero = _registrar(raiz, "seg-1", tipo="SEGURO_CARGA", patente="", contenido=original)
    repetido = _registrar(raiz, "seg-2", tipo="SEGURO_CARGA", patente="", contenido=original)
    otro = _registrar(raiz, "seg-3", chofer=COMBO, tipo="SEGURO_CARGA", patente="", contenido=original)
    assert repetido["duplicado"] and repetido["documento_id"] == primero["documento_id"]
    assert otro["documento_id"] != primero["documento_id"]
    with pytest.raises(ValueError, match="sin patente"):
        _registrar(raiz, "seg-4", tipo="SEGURO_CARGA", patente="CC5678")
    with pytest.raises(ValueError, match="otro remitente"):
        _registrar(raiz, "seg-1", chofer=COMBO, tipo="SEGURO_CARGA", patente="", contenido=original)


def test_seguro_lease_perdido_no_persiste_ni_confirma(raiz):
    antes = ruta_almacen(raiz, "MBT").read_bytes()
    cloud = CloudFalso([_doc_cloud("seguro_1", "SEGURO_CARGA", SOLO, "", JPEG("seguro"))])
    with patch.object(consumidor, "_json", cloud.json), patch.object(consumidor, "_descargar", cloud.descargar):
        resultado = consumidor.sincronizar_licencias_cloud(base_url="https://cloud.test", token_motor="t", consumidor="JAVO",
                                                          raiz=raiz, timeout=1, puede_continuar=lambda: False)
    assert resultado["detenido_por_escritor"] and cloud.confirmados == []
    assert ruta_almacen(raiz, "MBT").read_bytes() == antes


def test_seguro_aislado_por_empresa(raiz):
    inicializar_almacen(raiz, empresa="OTRA", actor="TEST")
    contenido = JPEG("seguro")
    _registrar(raiz, "seg-empresa", tipo="SEGURO_CARGA", patente="", contenido=contenido)
    assert leer_almacen(raiz, empresa="OTRA").get(PENDIENTES, []) == []
    _registrar(raiz, "seg-empresa", tipo="SEGURO_CARGA", patente="", contenido=contenido, empresa="OTRA")
    assert len(_datos(raiz)[PENDIENTES]) == 1
    assert len(leer_almacen(raiz, empresa="OTRA")[PENDIENTES]) == 1


def test_seguro_hash_incorrecto_no_persiste_ni_confirma(raiz):
    antes = ruta_almacen(raiz, "MBT").read_bytes()
    cloud = CloudFalso([{**_doc_cloud("seguro_1", "SEGURO_CARGA", SOLO, "", JPEG("seguro")),
                         "sha_cloud": "0" * 64}])
    resultado = _sincronizar(raiz, cloud)
    assert resultado["errores"] and not cloud.confirmados
    assert ruta_almacen(raiz, "MBT").read_bytes() == antes
