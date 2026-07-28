from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime, timezone
from importlib import reload

import pytest

import atlas_core.inteligencia as inteligencia
from atlas_core.inteligencia import (
    CorreccionHumana,
    EstadoCorreccion,
    EstadoPropuesta,
    Evidencia,
    MotorResolucion,
    NivelConfianza,
    PoliticaResolucion,
    ProveedorExternoSimulado,
    ProveedorModeloSimulado,
    RepositorioCorreccionesMemoria,
    RespuestaProveedor,
    TipoFuente,
    normalizar,
    obtener_politica,
    preparar_envio,
)
from atlas_core.procesamiento_masivo import COLUMNAS
from atlas_core.rutas import CalculadorRutas
from atlas_core.gestor_viajes import agrupar_viajes
from demostrar_motor_inteligente import construir_demostracion


AHORA = datetime(2026, 7, 28, 18, 30, tzinfo=timezone.utc)


def ev(
    valor,
    tipo=TipoFuente.OCR,
    confianza=1.0,
    *,
    campo="chofer",
    fuente=None,
    referencia="ref",
    detalles=None,
):
    return Evidencia(
        campo,
        valor,
        normalizar(valor),
        fuente or tipo.value,
        tipo,
        confianza,
        AHORA,
        "DOC-SINTETICO",
        referencia,
        detalles or {},
        campo in {"chofer", "rut_chofer", "destino"},
    )


def resolver(evidencias, original="ORIGINAL", campo="chofer", politica=None):
    return MotorResolucion().resolver(campo, original, evidencias, politica)


def test_confirmacion_por_evidencia_fuerte():
    regla = PoliticaResolucion("chofer", umbral_confirmacion=0.8)
    assert resolver([ev("ANA", TipoFuente.CORRECCION_HUMANA)], politica=regla).estado == EstadoPropuesta.CONFIRMADO


def test_confirmacion_por_evidencias_independientes():
    propuesta = resolver([
        ev("CARLOS FIEBIG", TipoFuente.CATALOGO, .95),
        ev("CARLOS FIEBIG", TipoFuente.RELACION_CAMPO, 1, fuente="rut"),
    ])
    assert propuesta.estado == EstadoPropuesta.CONFIRMADO


def test_evidencia_duplicada_no_cuenta_dos_veces():
    repetida = ev("ANA", confianza=.8)
    propuesta = resolver([repetida, repetida])
    assert propuesta.trazabilidad["evidencias_unicas"] == 1
    assert propuesta.estado == EstadoPropuesta.REVISAR


def test_dos_valores_con_igual_apoyo_revisar():
    assert resolver([ev("ANA"), ev("BEA", fuente="ocr-2")]).estado == EstadoPropuesta.REVISAR


def test_contradiccion_fuerte_queda_estructurada():
    propuesta = resolver([
        ev("ANA", TipoFuente.CATALOGO, 1),
        ev("BEA", TipoFuente.REGLA_DETERMINISTA, 1),
    ])
    assert propuesta.contradicciones[0].requiere_revision


def test_evidencia_insuficiente():
    assert resolver([]).estado == EstadoPropuesta.SIN_EVIDENCIA_SUFICIENTE


def test_valor_original_preservado():
    propuesta = resolver([ev("OTRO", confianza=.1)], original="OCR ORIGINAL")
    assert propuesta.valor_original == "OCR ORIGINAL"
    assert propuesta.valor_propuesto == "OCR ORIGINAL"


def test_trazabilidad_completa_e_inmutable():
    propuesta = resolver([ev("ANA")])
    assert {"puntajes", "margen", "politica"} <= propuesta.trazabilidad.keys()
    with pytest.raises(TypeError):
        propuesta.trazabilidad["x"] = 1


def test_explicacion_determinista():
    evidencias = [ev("ANA", TipoFuente.CATALOGO), ev("ANA", TipoFuente.RELACION_CAMPO, fuente="rut")]
    assert resolver(evidencias).explicacion == resolver(evidencias).explicacion


def test_confianza_configurable():
    baja = PoliticaResolucion("chofer", umbral_confirmacion=5, umbral_propuesta=4)
    assert resolver([ev("ANA")], politica=baja).confianza == NivelConfianza.BAJA


@pytest.mark.parametrize(
    "campo",
    [
        "chofer", "rut_chofer", "cliente", "destino", "patente_tracto",
        "patente_rampla", "fecha", "numero_transporte", "numero_guia",
        "planta_origen", "comuna", "region",
    ],
)
def test_existen_politicas_separadas(campo):
    assert obtener_politica(campo).campo == campo


@pytest.mark.parametrize(
    ("campo", "relacion"),
    [
        ("cliente", "destino"),
        ("destino", "cliente"),
        ("chofer", "patente_tracto"),
        ("patente_tracto", "chofer"),
        ("planta_origen", "cercania"),
    ],
)
def test_inferencias_prohibidas_no_se_aplican(campo, relacion):
    evidencia = ev(
        "VALOR INFERIDO", TipoFuente.RELACION_CAMPO,
        campo=campo, detalles={"relacion": relacion},
    )
    assert resolver([evidencia], campo=campo).estado == EstadoPropuesta.REVISAR


def test_transporte_alfanumerico_no_se_inventa():
    propuesta = resolver(
        [ev("12A3", TipoFuente.HISTORICO, campo="numero_transporte")],
        original="12A3", campo="numero_transporte",
    )
    assert propuesta.valor_propuesto == "12A3"
    assert propuesta.estado != EstadoPropuesta.CONFIRMADO


def test_fecha_ambigua_con_incompatible_revisar():
    propuesta = resolver([
        ev("01/02/2026", TipoFuente.OCR, campo="fecha"),
        ev("02/01/2026", TipoFuente.CATALOGO, campo="fecha"),
    ], campo="fecha")
    assert propuesta.estado == EstadoPropuesta.REVISAR


def test_chofer_sintetico_confirmado_por_rut_y_catalogo():
    propuesta = resolver([
        ev("CARLOS FIEBRI", TipoFuente.OCR, .85),
        ev("CARLOS FIEBIG", TipoFuente.CATALOGO, .95),
        ev("CARLOS FIEBIG", TipoFuente.RELACION_CAMPO, 1, fuente="rut"),
    ], original="CARLOS FIEBRI")
    assert propuesta.valor_propuesto == "CARLOS FIEBIG"
    assert propuesta.estado == EstadoPropuesta.CONFIRMADO


def test_chofer_ambiguo_sin_rut_revisar():
    assert resolver([
        ev("CARLOS UNO", TipoFuente.CATALOGO, .8),
        ev("CARLOS DOS", TipoFuente.CATALOGO, .8, fuente="catalogo-2"),
    ]).estado == EstadoPropuesta.REVISAR


def test_contradiccion_externa_cliente_destino_revisar():
    propuesta = resolver([
        ev("COMUNA A", TipoFuente.HISTORICO, campo="destino"),
        ev("COMUNA B", TipoFuente.VERIFICACION_EXTERNA, campo="destino"),
    ], campo="destino")
    assert propuesta.estado == EstadoPropuesta.REVISAR


@pytest.mark.parametrize(
    "estado,esperadas",
    [
        (EstadoCorreccion.PENDIENTE, 0),
        (EstadoCorreccion.APROBADA, 1),
        (EstadoCorreccion.RECHAZADA, 0),
        (EstadoCorreccion.INACTIVA, 0),
    ],
)
def test_aprendizaje_controlado_por_estado(estado, esperadas):
    repo = RepositorioCorreccionesMemoria()
    correccion = CorreccionHumana(
        "chofer", "A", "B", ev("B", TipoFuente.CORRECCION_HUMANA),
        "ACTOR-SINTETICO", AHORA, 1, estado, "2026",
    )
    repo.registrar(correccion)
    assert len(repo.aprobadas("chofer", "A")) == esperadas


def test_correccion_puede_desactivarse():
    repo = RepositorioCorreccionesMemoria()
    correccion = CorreccionHumana(
        "chofer", "A", "B", ev("B"), "actor", AHORA, 2,
        EstadoCorreccion.APROBADA, "2026",
    )
    repo.registrar(correccion)
    repo.desactivar(correccion)
    assert repo.aprobadas("chofer", "A") == ()


def test_proveedores_simulados_son_deterministas():
    respuesta = RespuestaProveedor((ev("ANA"),))
    modelo = ProveedorModeloSimulado(respuesta)
    externo = ProveedorExternoSimulado(respuesta)
    assert modelo.analizar({"x": 1}) == modelo.analizar({"x": 1})
    assert externo.verificar({"x": 1}) == externo.verificar({"x": 1})


@pytest.mark.parametrize("metodo", ["analizar", "verificar"])
def test_error_y_timeout_de_proveedor_no_forman_parte_del_motor(metodo):
    class Falla:
        def analizar(self, _):
            raise TimeoutError("secreto-no-expuesto")
        verificar = analizar
    with pytest.raises(TimeoutError):
        getattr(Falla(), metodo)({})
    assert resolver([ev("ANA")]).campo == "chofer"


def test_datos_sensibles_redactados_y_original_local_conservado():
    original = {"rut": "12.345.678-5", "comuna": "SINTETICA"}
    envio = preparar_envio(original, {"rut", "comuna"})
    assert envio.datos["rut"] == "[REDACTADO]"
    assert original["rut"] == "12.345.678-5"


def test_imagen_completa_y_secretos_bloqueados():
    envio = preparar_envio(
        {"imagen_completa": b"bytes", "api_key": "SECRETO", "comuna": "A"},
        {"imagen_completa", "api_key", "comuna"},
    )
    assert envio.datos == {"comuna": "A"}
    assert set(envio.campos_bloqueados) == {"api_key", "imagen_completa"}
    assert "SECRETO" not in repr(envio)


def test_proveedor_recibe_solo_datos_autorizados():
    envio = preparar_envio({"rut": "1-9", "region": "X", "imagen": b"x"}, {"rut", "region"})
    proveedor = ProveedorModeloSimulado()
    proveedor.analizar(envio.datos)
    assert proveedor.solicitudes == [{"region": "X", "rut": "[REDACTADO]"}]


def test_modelo_ia_sin_otra_evidencia_no_se_acepta():
    assert resolver([ev("ANA", TipoFuente.MODELO_IA)]).estado == EstadoPropuesta.SIN_EVIDENCIA_SUFICIENTE


def test_modelo_no_puede_mutar_valor_directamente():
    propuesta = resolver([ev("OTRO", TipoFuente.MODELO_IA)], original="ORIGINAL")
    assert propuesta.valor_propuesto == "ORIGINAL"


def test_modelos_inmutables():
    evidencia = ev("ANA")
    with pytest.raises(FrozenInstanceError):
        evidencia.valor_observado = "CAMBIO"


def test_importacion_sin_io(monkeypatch):
    llamadas = []
    monkeypatch.setattr("builtins.open", lambda *_a, **_k: llamadas.append(1))
    reload(inteligencia)
    assert llamadas == []


def test_funciona_sin_internet(monkeypatch):
    monkeypatch.setattr("socket.create_connection", lambda *_a, **_k: pytest.fail("red"))
    assert resolver([ev("ANA")]).campo == "chofer"


def test_quince_campos_oficiales_no_cambian():
    antes = tuple(COLUMNAS)
    resolver([ev("ANA")])
    assert tuple(COLUMNAS) == antes
    assert len(COLUMNAS) == 15


def test_compatibilidad_de_importacion_con_viajes_y_rutas():
    assert callable(agrupar_viajes)
    assert CalculadorRutas.__name__ == "CalculadorRutas"
    assert MotorResolucion.__name__ == "MotorResolucion"


def test_demostracion_sintetica_completa():
    salida = construir_demostracion()
    assert salida["estado"] == "CONFIRMADO"
    assert salida["propuesto"] == "CARLOS FIEBIG"
    assert salida["confianza"] == "ALTA"
