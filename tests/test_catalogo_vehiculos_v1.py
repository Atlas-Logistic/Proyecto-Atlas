import json
from contextlib import contextmanager
from datetime import datetime, timezone

import pytest

import atlas_core.catalogo_vehiculos as modulo
from atlas_core.catalogo_vehiculos import (
    CatalogoVehiculosAusenteError,
    CatalogoVehiculosCorruptoError,
    ErrorCatalogoVehiculos,
    EvidenciaVehiculo,
    VehiculoDuplicadoError,
    VersionCatalogoVehiculosDesconocidaError,
    cargar_catalogo_vehiculos,
    confirmar_vehiculo,
    migrar_v0_a_v1,
    resolver_patente,
    ruta_catalogo_vehiculos,
)


FECHA = "2026-01-02T03:04:05+00:00"


def evidencia(*, alias="", acompanante=""):
    campos = {"patente": "AB1234"}
    if alias:
        campos["alias"] = alias
    if acompanante:
        campos["patente_acompanante"] = acompanante
    return {
        "tipo": "GUIA",
        "identificador_fuente": "documento-sintetico",
        "referencia_hash": "abc123",
        "campos_observados": campos,
        "fecha": FECHA,
        "actor_proceso": "TEST",
        "resultado": "SOPORTA",
    }


def vehiculo(
    patente="AB1234", *, tipo="TRACTO", calidad="CONFIRMADO",
    vigencia="ACTIVO", aliases=None, evidencias=None,
):
    es_confirmado = calidad == "CONFIRMADO"
    return {
        "vehiculo_id": f"id-{patente}",
        "patente_canonica": patente,
        "tipo": tipo,
        "estado_calidad": calidad,
        "estado_vigencia": vigencia,
        "aliases": aliases or [],
        "evidencias": evidencias or [],
        "procedencia": "CONFIRMACION_HUMANA",
        "confirmado_por": "PERSONA TEST" if es_confirmado else "",
        "fecha_confirmacion": FECHA if es_confirmado else "",
        "observaciones": "",
        "fecha_creacion": FECHA,
        "fecha_modificacion": FECHA,
    }


def catalogo_v1(*registros):
    return {"version": 1, "vehiculos": list(registros)}


def test_lectura_v0_y_paridad_de_homologacion(tmp_path):
    ruta = tmp_path / "vehiculos.json"
    ruta.write_text(json.dumps({"AB1234": {"tipo": "TRACTO"}}), encoding="utf-8")
    cargado = cargar_catalogo_vehiculos(ruta)
    assert cargado.formato == "V0"
    assert resolver_patente(ruta, "ab 1234", tipo_esperado="CARRO").estado == "COINCIDENCIA_EXACTA"
    assert ruta.read_text(encoding="utf-8") == json.dumps({"AB1234": {"tipo": "TRACTO"}})


def test_lectura_v1_confirmado_activo_homologa():
    cargado = cargar_catalogo_vehiculos(catalogo_v1(vehiculo()))
    assert cargado.formato == "V1"
    assert resolver_patente(catalogo_v1(vehiculo()), "AB1234", tipo_esperado="TRACTO").estado == "COINCIDENCIA_EXACTA"


@pytest.mark.parametrize("calidad", ["OBSERVADO", "CANDIDATO", "RECHAZADO"])
def test_v1_no_confirmado_no_homologa(calidad):
    resultado = resolver_patente(catalogo_v1(vehiculo(calidad=calidad)), "AB1234")
    assert resultado.estado == "CATALOGO_VACIO"


def test_v1_inactivo_no_homologa():
    assert resolver_patente(catalogo_v1(vehiculo(vigencia="INACTIVO")), "AB1234").estado == "CATALOGO_VACIO"


def test_ausente_corrupto_y_version_desconocida_se_distinguen(tmp_path):
    with pytest.raises(CatalogoVehiculosAusenteError):
        cargar_catalogo_vehiculos(tmp_path / "ausente.json")
    ruta = tmp_path / "vehiculos.json"
    ruta.write_text("{", encoding="utf-8")
    with pytest.raises(CatalogoVehiculosCorruptoError):
        cargar_catalogo_vehiculos(ruta)
    with pytest.raises(VersionCatalogoVehiculosDesconocidaError):
        cargar_catalogo_vehiculos({"version": 2, "vehiculos": []})


@pytest.mark.parametrize(
    "registros, mensaje",
    [
        ([vehiculo(), vehiculo()], "patente"),
        ([vehiculo("AB1234", aliases=["CD5678"], evidencias=[evidencia(alias="CD5678")]),
          vehiculo("EF9012", tipo="CARRO", aliases=["CD5678"], evidencias=[evidencia(alias="CD5678")])], "alias"),
        ([vehiculo("AB1234", aliases=["CD5678"], evidencias=[evidencia(alias="CD5678")]),
          vehiculo("CD5678", tipo="CARRO")], "alias"),
    ],
)
def test_rechaza_patente_alias_duplicado_o_colision(registros, mensaje):
    with pytest.raises(VehiculoDuplicadoError, match=mensaje):
        cargar_catalogo_vehiculos(catalogo_v1(*registros))


def test_alias_requiere_evidencia_explicita():
    with pytest.raises(CatalogoVehiculosCorruptoError, match="evidencia"):
        cargar_catalogo_vehiculos(catalogo_v1(vehiculo(aliases=["CD5678"])))


@pytest.mark.parametrize(
    "cambio",
    [{"tipo": "BUS"}, {"estado_calidad": "DUDOSO"}, {"estado_vigencia": "VIGENTE"}],
)
def test_rechaza_tipo_o_estado_invalido(cambio):
    registro = {**vehiculo(), **cambio}
    with pytest.raises(CatalogoVehiculosCorruptoError):
        cargar_catalogo_vehiculos(catalogo_v1(registro))


def test_alias_v1_y_ocr_conservador_se_resuelven_sin_fuzzy():
    con_alias = vehiculo(aliases=["AD1234"], evidencias=[evidencia(alias="AD1234")])
    assert resolver_patente(catalogo_v1(con_alias), "AD1234").estado == "ALIAS"
    assert resolver_patente(catalogo_v1(vehiculo()), "AD1234").estado == "CORRECCION_OCR_SEGURA"
    assert resolver_patente(catalogo_v1(vehiculo()), "AX9999").estado == "SIN_CANDIDATO"


def test_migracion_v0_v1_sin_perdida_ni_confirmacion_humana():
    v0 = {"AB1234": {"tipo": "TRACTO"}, "CD5678": {"tipo": "CARRO"}}
    resultado = migrar_v0_a_v1(v0, fecha=datetime(2026, 1, 2, tzinfo=timezone.utc), referencia_hash="sha")
    cargado = cargar_catalogo_vehiculos(resultado)
    assert {(v.patente_canonica, v.tipo) for v in cargado.vehiculos} == {("AB1234", "TRACTO"), ("CD5678", "CARRO")}
    assert all(v.procedencia == "CATALOGO_LEGACY" for v in cargado.vehiculos)
    assert all(v.confirmado_por == "" and v.fecha_confirmacion == "" for v in cargado.vehiculos)
    assert resolver_patente(resultado, "AB1234").estado == "COINCIDENCIA_EXACTA"


def test_confirmacion_humana_exige_actor_y_fuente_de_decision(tmp_path):
    ruta = tmp_path / "vehiculos.json"
    ruta.write_text(json.dumps(catalogo_v1()), encoding="utf-8")
    with pytest.raises(ErrorCatalogoVehiculos, match="actor"):
        confirmar_vehiculo(ruta, patente="AB1234", tipo="TRACTO", actor="", fuente_decision="ACTA", fecha=datetime.now(timezone.utc))
    with pytest.raises(ErrorCatalogoVehiculos, match="fuente_decision"):
        confirmar_vehiculo(ruta, patente="AB1234", tipo="TRACTO", actor="PERSONA", fuente_decision="", fecha=datetime.now(timezone.utc))


def test_confirmacion_humana_agrega_evidencia_y_es_atomica_bajo_bloqueo(tmp_path, monkeypatch):
    ruta = tmp_path / "vehiculos.json"
    ruta.write_text(json.dumps(catalogo_v1()), encoding="utf-8")
    llamadas = []

    @contextmanager
    def bloqueo(directorio, nombre):
        llamadas.append(("lock", directorio, nombre))
        yield

    escritura_real = modulo.escribir_json_atomico
    def escritura(ruta_destino, contenido):
        llamadas.append(("atomico", ruta_destino))
        escritura_real(ruta_destino, contenido)

    monkeypatch.setattr(modulo, "bloqueo_sesion", bloqueo)
    monkeypatch.setattr(modulo, "escribir_json_atomico", escritura)
    creado = confirmar_vehiculo(
        ruta, patente="AB1234", tipo="TRACTO", actor="PERSONA TEST",
        fuente_decision="ACTA TEST", referencia_hash="hash-acta",
        observaciones="confirmado visualmente",
        fecha=datetime(2026, 1, 2, tzinfo=timezone.utc),
    )
    assert creado.confirmado_por == "PERSONA TEST"
    assert creado.evidencias[0].tipo == "CONFIRMACION_HUMANA"
    assert creado.evidencias[0].resultado == "SOPORTA"
    assert creado.evidencias[0].identificador_fuente == "ACTA TEST"
    assert creado.evidencias[0].campos_observados["observacion"] == "confirmado visualmente"
    assert [llamada[0] for llamada in llamadas] == ["lock", "atomico"]
    assert "pareja" not in ruta.read_text(encoding="utf-8").lower()


def test_dos_patentes_similares_coexisten_sin_alias_implicito():
    contenido = catalogo_v1(vehiculo("AB1234"), vehiculo("AB1235", tipo="CARRO"))
    cargado = cargar_catalogo_vehiculos(contenido)
    assert {v.patente_canonica for v in cargado.vehiculos} == {"AB1234", "AB1235"}
    assert all(not v.aliases for v in cargado.vehiculos)


def test_ruta_catalogo_respeta_atlas_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("ATLAS_DATA_DIR", str(tmp_path))
    assert ruta_catalogo_vehiculos() == tmp_path / "catalogos_privados" / "vehiculos.json"


def _guardar_v1(tmp_path, *registros):
    ruta = tmp_path / "vehiculos.json"
    ruta.write_text(json.dumps(catalogo_v1(*registros)), encoding="utf-8")
    return ruta


def _confirmar(ruta, *, patente="AB1234", tipo="TRACTO"):
    return confirmar_vehiculo(
        ruta,
        patente=patente,
        tipo=tipo,
        actor="PERSONA AUDITORA",
        fuente_decision="ACTA SINTETICA",
        referencia_hash="hash-decision",
        observaciones="decisión humana de prueba",
        fecha=datetime(2026, 2, 3, 4, 5, tzinfo=timezone.utc),
    )


@pytest.mark.parametrize("estado", ["OBSERVADO", "CANDIDATO"])
def test_observado_y_candidato_pueden_confirmarse_humanamente(tmp_path, estado):
    ruta = _guardar_v1(tmp_path, vehiculo(calidad=estado))
    confirmado = _confirmar(ruta)
    assert confirmado.estado_calidad == "CONFIRMADO"
    assert confirmado.confirmado_por == "PERSONA AUDITORA"
    assert confirmado.evidencias[-1].tipo == "CONFIRMACION_HUMANA"


def test_rechazado_no_puede_confirmarse_y_archivo_permanece_intacto(tmp_path):
    ruta = _guardar_v1(tmp_path, vehiculo(calidad="RECHAZADO"))
    antes = ruta.read_bytes()
    with pytest.raises(ErrorCatalogoVehiculos, match="rechazado"):
        _confirmar(ruta)
    assert ruta.read_bytes() == antes


def test_inactivo_no_puede_confirmarse_y_archivo_permanece_intacto(tmp_path):
    ruta = _guardar_v1(tmp_path, vehiculo(calidad="CANDIDATO", vigencia="INACTIVO"))
    antes = ruta.read_bytes()
    with pytest.raises(ErrorCatalogoVehiculos, match="inactivo"):
        _confirmar(ruta)
    assert ruta.read_bytes() == antes


def test_ratificacion_legacy_conserva_origen_e_historial_y_agrega_decision_humana(tmp_path):
    migrado = migrar_v0_a_v1(
        {"AB1234": {"tipo": "TRACTO"}},
        fecha=datetime(2026, 1, 1, tzinfo=timezone.utc),
        referencia_hash="hash-v0",
    )
    ruta = tmp_path / "vehiculos.json"
    ruta.write_text(json.dumps(migrado), encoding="utf-8")
    ratificado = _confirmar(ruta)
    assert ratificado.procedencia == "CATALOGO_LEGACY"
    assert ratificado.confirmado_por == "PERSONA AUDITORA"
    assert ratificado.fecha_confirmacion
    assert [e.tipo for e in ratificado.evidencias] == [
        "MIGRACION_LEGACY",
        "CONFIRMACION_HUMANA",
    ]


def test_ratificacion_legacy_con_tipo_distinto_rechaza_sin_escribir(tmp_path):
    migrado = migrar_v0_a_v1(
        {"AB1234": {"tipo": "TRACTO"}},
        fecha=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    ruta = tmp_path / "vehiculos.json"
    ruta.write_text(json.dumps(migrado), encoding="utf-8")
    antes = ruta.read_bytes()
    with pytest.raises(ErrorCatalogoVehiculos, match="tipo contradice"):
        _confirmar(ruta, tipo="CARRO")
    assert ruta.read_bytes() == antes


def test_confirmado_humanamente_no_admite_reconfirmacion_ni_duplica_evidencia(tmp_path):
    ruta = _guardar_v1(tmp_path)
    primero = _confirmar(ruta)
    antes = ruta.read_bytes()
    with pytest.raises(VehiculoDuplicadoError, match="confirmación humana"):
        _confirmar(ruta)
    assert ruta.read_bytes() == antes
    assert len(primero.evidencias) == 1


def test_api_no_admite_evidencia_arbitraria_guiada_por_ocr(tmp_path):
    ruta = _guardar_v1(tmp_path)
    evidencia_ocr = EvidenciaVehiculo.desde_dict(evidencia())
    with pytest.raises(TypeError, match="evidencia"):
        confirmar_vehiculo(
            ruta,
            patente="AB1234",
            tipo="TRACTO",
            actor="PROCESO_OCR",
            fuente_decision="GUIA",
            fecha=datetime.now(timezone.utc),
            evidencia=evidencia_ocr,
        )
    assert cargar_catalogo_vehiculos(ruta).vehiculos == ()


def test_contradiccion_de_tipo_en_candidato_conserva_archivo_byte_a_byte(tmp_path):
    ruta = _guardar_v1(tmp_path, vehiculo(calidad="CANDIDATO"))
    antes = ruta.read_bytes()
    with pytest.raises(ErrorCatalogoVehiculos, match="tipo contradice"):
        _confirmar(ruta, tipo="CARRO")
    assert ruta.read_bytes() == antes


def test_migracion_v0_preserva_alias_y_registra_evidencia_sin_autoria_humana():
    migrado = migrar_v0_a_v1(
        {"AB1234": {"tipo": "TRACTO", "alias": ["AD1234"]}},
        fecha=datetime(2026, 1, 1, tzinfo=timezone.utc),
        referencia_hash="hash-v0",
    )
    registro = cargar_catalogo_vehiculos(migrado).vehiculos[0]
    assert registro.aliases == ("AD1234",)
    assert [e.tipo for e in registro.evidencias] == [
        "MIGRACION_LEGACY",
        "MIGRACION_LEGACY",
    ]
    assert registro.confirmado_por == ""
    assert registro.fecha_confirmacion == ""
    assert resolver_patente(migrado, "AD1234").estado == "ALIAS"


@pytest.mark.parametrize(
    "v0_corrupto",
    [
        {"AB1234": {"tipo": "TRACTO"}, "CD5678": {}},
        {"AB1234": {"tipo": "TRACTO"}, "CD5678": {"tipo": "BUS"}},
    ],
)
def test_v0_parcialmente_corrupto_invalida_catalogo_completo(v0_corrupto):
    with pytest.raises(CatalogoVehiculosCorruptoError):
        cargar_catalogo_vehiculos(v0_corrupto)
    with pytest.raises(CatalogoVehiculosCorruptoError):
        resolver_patente(v0_corrupto, "AB1234")
