"""Documentos de la rampla desde Mobile (rol declarado TRACTO/RAMPLA).

Motor publica tracto y rampla confirmados por separado, y clasifica los
documentos nuevos con rol declarado por la patente que Cloud resolvió, sólo
si sigue siendo hoy la asignación CONFIRMADA de ese rol. Lo recibido sin rol
(Mobile anterior) conserva la regla de siempre y nada antiguo se reclasifica.
Sólo datos sintéticos en tmp_path.
"""
from __future__ import annotations

import json

import pytest

from atlas_core import cloud_asignaciones_vehiculo as publicacion
from atlas_core.fichas_vehiculos import PENDIENTES
from tests.test_fichas_vehiculos_mobile import (  # noqa: F401 -- `raiz` es fixture
    COMBO, CONFLICTO, INACTIVO, JPEG, SOLO, CloudFalso, _asignar, _datos, _doc_cloud, _registrar, _sincronizar,
    _vehiculo, raiz,
)
from atlas_core.catalogo_vehiculos import TipoVehiculo
from tests.test_motor_evidencia_vehiculos import _confirmar

TRACTO, RAMPLA = "TG8925", "JF9575"  # de COMBO (tracto + carro confirmados)


def _pendientes(raiz):
    return _datos(raiz).get(PENDIENTES, [])


# ---- Publicación Motor -> Cloud ----

def test_publica_tracto_y_rampla_confirmados_por_rol(raiz):
    por_rol = publicacion.asignaciones_publicables_por_rol(raiz)
    assert por_rol["tracto"] == [{"chofer_id": COMBO, "patente": TRACTO}, {"chofer_id": SOLO, "patente": "CC5678"}]
    assert por_rol["rampla"] == [{"chofer_id": COMBO, "patente": RAMPLA}]
    # Compatibilidad: la lista de siempre sigue siendo sólo la de tractos.
    assert publicacion.asignaciones_publicables(raiz) == por_rol["tracto"]


def test_rampla_en_conflicto_o_de_chofer_inactivo_no_se_publica(raiz):
    ruta = raiz / "catalogos_privados" / "vehiculos.json"
    for patente in ("KK1111", "KK2222", "KK3333"):
        _confirmar(ruta, patente, TipoVehiculo.CARRO)
    _asignar(ruta, "KK1111", CONFLICTO, 1)
    _asignar(ruta, "KK2222", CONFLICTO, 2)   # dos carros vigentes: conflicto
    _asignar(ruta, "KK3333", INACTIVO, 1)
    assert publicacion.asignaciones_publicables_por_rol(raiz)["rampla"] == [{"chofer_id": COMBO, "patente": RAMPLA}]


def test_publicar_envia_tractos_y_ramplas_en_un_solo_conjunto(raiz, monkeypatch):
    llamadas = []
    monkeypatch.setattr(publicacion, "_json", lambda base, ruta, token, **kw: llamadas.append(kw["body"]) or {"asignaciones": 2, "ramplas": 1, "cambios": 3})
    r = publicacion.publicar_asignaciones_cloud(base_url="https://cloud.local", token_motor="t", raiz=raiz, timeout=5, puede_continuar=lambda: True)
    assert r == {"publicadas": 2, "ramplas_publicadas": 1, "cambios": 3}
    assert llamadas == [{"asignaciones": [{"chofer_id": COMBO, "patente": TRACTO}, {"chofer_id": SOLO, "patente": "CC5678"}],
                         "ramplas": [{"chofer_id": COMBO, "patente": RAMPLA}]}]


def test_publicar_no_modifica_catalogos(raiz, monkeypatch):
    carpeta = raiz / "catalogos_privados"
    antes = {n: (carpeta / n).read_bytes() for n in ("vehiculos.json", "choferes.json")}
    monkeypatch.setattr(publicacion, "_json", lambda *a, **kw: {})
    publicacion.publicar_asignaciones_cloud(base_url="https://cloud.local", token_motor="t", raiz=raiz, timeout=5, puede_continuar=lambda: True)
    assert {n: (carpeta / n).read_bytes() for n in antes} == antes


# ---- Clasificación por rol declarado ----

@pytest.mark.parametrize("tipo", ["PERMISO_CIRCULACION", "REVISION_TECNICA"])
def test_documento_de_rampla_con_rol_va_a_la_ficha_de_la_rampla(raiz, tipo):
    r = _registrar(raiz, "dfm_r1", chofer=COMBO, tipo=tipo, patente=RAMPLA, rol_cloud="RAMPLA")
    assert (r["patente"], r["motivo"], r["duplicado"]) == (RAMPLA, "", False)
    doc = _vehiculo(raiz, RAMPLA)["documentos"][0]
    assert doc["tipo"] == tipo
    assert doc["asociacion"]["rol"] == "RAMPLA" and doc["asociacion"]["metodo"] == "ASIGNACION_CONFIRMADA"
    assert doc["procedencia"] == {"chofer_id": COMBO, "patente_cloud": RAMPLA, "recibido_en": "2026-11-02T13:00:00Z", "rol_cloud": "RAMPLA"}
    assert _vehiculo(raiz, TRACTO) is None, "nunca se asigna al tracto"
    assert _pendientes(raiz) == []


def test_documento_del_tracto_con_rol_va_al_tracto_aunque_haya_rampla(raiz):
    r = _registrar(raiz, "dfm_t1", chofer=COMBO, tipo="SOAP", patente=TRACTO, rol_cloud="TRACTO")
    assert (r["patente"], r["motivo"]) == (TRACTO, "")
    assert _vehiculo(raiz, TRACTO)["documentos"][0]["asociacion"]["rol"] == "TRACTO"


def test_sin_rol_mobile_anterior_conserva_la_regla_de_siempre(raiz):
    # Tracto + carro sin rol declarado: sigue siendo ambiguo.
    r = _registrar(raiz, "dfm_v1", chofer=COMBO, tipo="PERMISO_CIRCULACION", patente=TRACTO)
    assert (r["patente"], r["motivo"]) == (None, "TRACTO_Y_CARRO")
    assert "rol_cloud" not in _pendientes(raiz)[0]["procedencia"]
    # Sólo tracto sin rol: asociado al tracto, igual que antes (rol TRACTO en la asociación).
    s = _registrar(raiz, "dfm_v2", tipo="SOAP", patente="CC5678")
    assert s["patente"] == "CC5678"
    assert _vehiculo(raiz, "CC5678")["documentos"][0]["asociacion"]["rol"] == "TRACTO"


@pytest.mark.parametrize("chofer,patente,rol,tipo,motivo", [
    (COMBO, TRACTO, "RAMPLA", "PERMISO_CIRCULACION", "ASIGNACION_DISTINTA"),       # patente de otro rol
    (COMBO, "ZZ9999", "RAMPLA", "PERMISO_CIRCULACION", "ASIGNACION_DISTINTA"),     # rampla cambió tras el envío
    (SOLO, "CC5678", "RAMPLA", "REVISION_TECNICA", "SIN_ASIGNACION_CONFIRMADA"),   # sin rampla confirmada
    (COMBO, RAMPLA, "RAMPLA", "SOAP", "TIPO_NO_CORRESPONDE_A_RAMPLA"),
    (COMBO, RAMPLA, "CAMION", "PERMISO_CIRCULACION", "ROL_DESCONOCIDO"),
])
def test_rol_que_no_coincide_con_la_asignacion_confirmada_queda_por_clasificar(raiz, chofer, patente, rol, tipo, motivo):
    r = _registrar(raiz, "dfm_x", chofer=chofer, tipo=tipo, patente=patente, rol_cloud=rol)
    assert (r["patente"], r["motivo"]) == (None, motivo)
    assert [v["patente"] for v in _datos(raiz)["vehiculos"]] == []
    pendiente = _pendientes(raiz)[0]
    assert pendiente["clasificacion"]["motivo"] == motivo and pendiente["procedencia"]["rol_cloud"] == rol


def test_documentos_antiguos_ambiguos_no_se_reclasifican(raiz):
    antiguo = _registrar(raiz, "dfm_viejo", chofer=COMBO, tipo="PERMISO_CIRCULACION", patente=TRACTO)
    assert antiguo["motivo"] == "TRACTO_Y_CARRO"
    pendiente_antes = json.dumps(_pendientes(raiz), sort_keys=True)
    # El mismo origen reaparece (reintento) ahora con rol: idempotente, sin mover nada.
    otra_vez = _registrar(raiz, "dfm_viejo", chofer=COMBO, tipo="PERMISO_CIRCULACION", patente=TRACTO, rol_cloud="TRACTO")
    assert otra_vez["idempotente"] and otra_vez["patente"] is None
    # Un documento nuevo con rol se clasifica; el antiguo sigue igual, por clasificar.
    nuevo = _registrar(raiz, "dfm_nuevo", chofer=COMBO, tipo="PERMISO_CIRCULACION", patente=RAMPLA, rol_cloud="RAMPLA")
    assert nuevo["patente"] == RAMPLA
    assert json.dumps(_pendientes(raiz), sort_keys=True) == pendiente_antes


def test_seguro_de_carga_con_rol_se_rechaza_sin_escribir(raiz):
    antes = _datos(raiz)["revision"]
    with pytest.raises(ValueError, match="sin rol"):
        _registrar(raiz, "seg-r", chofer=COMBO, tipo="SEGURO_CARGA", patente="", rol_cloud="RAMPLA")
    assert _datos(raiz)["revision"] == antes
    # Sin rol: el comportamiento de siempre.
    assert _registrar(raiz, "seg-ok", chofer=COMBO, tipo="SEGURO_CARGA", patente="")["motivo"] == "SEGURO_SIN_VEHICULO_ACREDITADO"


def test_mismo_archivo_en_tracto_y_rampla_quedan_en_su_vehiculo_sin_cruzarse(raiz):
    # Cloud ya impide los mismos bytes para ambos; si llegaran, Motor no los funde entre vehículos.
    contenido = JPEG("un-permiso")
    t = _registrar(raiz, "dfm_t", chofer=COMBO, tipo="PERMISO_CIRCULACION", patente=TRACTO, rol_cloud="TRACTO", contenido=contenido)
    r = _registrar(raiz, "dfm_r", chofer=COMBO, tipo="PERMISO_CIRCULACION", patente=RAMPLA, rol_cloud="RAMPLA", contenido=contenido)
    assert (t["patente"], r["patente"]) == (TRACTO, RAMPLA)
    assert [d["origen_documento_id"] for d in _vehiculo(raiz, TRACTO)["documentos"]] == ["dfm_t"]
    assert [d["origen_documento_id"] for d in _vehiculo(raiz, RAMPLA)["documentos"]] == ["dfm_r"]


def test_clasificar_no_modifica_catalogos(raiz):
    carpeta = raiz / "catalogos_privados"
    antes = {n: (carpeta / n).read_bytes() for n in ("vehiculos.json", "choferes.json")}
    _registrar(raiz, "dfm_r", chofer=COMBO, tipo="REVISION_TECNICA", patente=RAMPLA, rol_cloud="RAMPLA")
    assert {n: (carpeta / n).read_bytes() for n in antes} == antes


# ---- PULL: el rol llega en el documento de Cloud ----

def test_pull_usa_el_rol_de_cloud_y_sin_rol_conserva_la_regla(raiz):
    cloud = CloudFalso([
        {**_doc_cloud("dfm_pc_rampla", "PERMISO_CIRCULACION", COMBO, RAMPLA, JPEG("pc-rampla")), "rol": "RAMPLA"},
        {**_doc_cloud("dfm_rt_rampla", "REVISION_TECNICA", COMBO, RAMPLA, JPEG("rt-rampla")), "rol": "RAMPLA"},
        {**_doc_cloud("dfm_soap_tracto", "SOAP", COMBO, TRACTO, JPEG("soap-tracto")), "rol": "TRACTO"},
        _doc_cloud("dfm_legado", "PERMISO_CIRCULACION", COMBO, TRACTO, JPEG("pc-legado")),  # Cloud/Mobile anterior
    ])
    resumen = _sincronizar(raiz, cloud)
    assert not resumen["errores"] and not resumen["sin_vincular"]
    assert [c[1] for c in cloud.confirmados] == ["RECIBIDO_PENDIENTE_REVISION"] * 4
    assert [(v["documento_id"], v["patente"], v["motivo"]) for v in resumen["vehiculos"]] == [
        ("dfm_pc_rampla", RAMPLA, ""), ("dfm_rt_rampla", RAMPLA, ""), ("dfm_soap_tracto", TRACTO, ""),
        ("dfm_legado", None, "TRACTO_Y_CARRO")]
    assert sorted(d["tipo"] for d in _vehiculo(raiz, RAMPLA)["documentos"]) == ["PERMISO_CIRCULACION", "REVISION_TECNICA"]
    assert [d["tipo"] for d in _vehiculo(raiz, TRACTO)["documentos"]] == ["SOAP"]
    revision = _datos(raiz)["revision"]
    _sincronizar(raiz, cloud)
    assert _datos(raiz)["revision"] == revision, "un segundo ciclo no duplica"
