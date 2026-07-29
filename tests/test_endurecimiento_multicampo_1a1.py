from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from atlas_core.inteligencia.contrato_multicampo import (
    Disponibilidad,
    EstadoResolucion,
    ResultadoResolucion,
    ValorObservado,
    descongelar,
)
from atlas_core.inteligencia.politica_confianza_chofer import (
    POLITICA_CONFIANZA_CHOFER_V1_1,
    PoliticaConfianzaChofer,
    ViaDecisionChofer,
)
from atlas_core.inteligencia.redireccion_identidad import (
    EventoRedireccionIdentidad,
    HistorialRedireccionesIdentidad,
    TipoRedireccionIdentidad,
)
from atlas_core.inteligencia.resolucion_chofer import (
    normalizar_nombre_identidad,
    resolver_chofer_rut,
)
from atlas_core.inteligencia.snapshot_catalogo_choferes import (
    crear_snapshot_catalogo_choferes,
)


def _dv(base: str) -> str:
    suma = 0
    factor = 2
    for digito in reversed(base):
        suma += int(digito) * factor
        factor = factor + 1 if factor < 7 else 2
    resto = 11 - suma % 11
    return "0" if resto == 11 else "K" if resto == 10 else str(resto)


def _rut(numero: int) -> str:
    base = f"{numero:08d}"
    return base + _dv(base)


@pytest.fixture
def catalogo():
    return {
        _rut(101): {
            "nombre": "PERSONA DEMO PEÑA",
            "activo": True,
            "aliases": ["ALIAS DEMO PEÑA"],
        },
        _rut(202): {
            "nombre": "PERSONA DEMO DOS",
            "activo": True,
            "aliases": ["ALIAS DEMO DOS"],
        },
        _rut(1202): {
            "nombre": "PERSONA DEMO TRES",
            "activo": True,
        },
    }


@pytest.mark.parametrize(
    ("nombre", "rut"),
    [
        ("", ""),
        (None, None),
        ("TEXTO SIN EVIDENCIA", ""),
        ("", "RUT-INVALIDO-X"),
    ],
)
def test_no_resuelto_obligatorio_siempre_requiere_revision(catalogo, nombre, rut):
    resultado = resolver_chofer_rut(nombre, rut, catalogo)
    assert resultado.estado is EstadoResolucion.NO_RESUELTO
    assert resultado.requiere_revision_humana is True


def test_campo_opcional_explicitamente_puede_cerrar_no_resuelto(catalogo):
    resultado = resolver_chofer_rut("", "", catalogo, campo_obligatorio=False)
    assert resultado.estado is EstadoResolucion.NO_RESUELTO
    assert resultado.requiere_revision_humana is False


@pytest.mark.parametrize("nombre", ["ALIAS DEMO PEÑA", "PERSONA DEMO PEÑA"])
def test_parcial_incompatible_conserva_ambos_lados(catalogo, nombre):
    parcial = _rut(202)[-5:]
    resultado = resolver_chofer_rut(nombre, parcial, catalogo)
    assert resultado.estado is EstadoResolucion.REQUIERE_REVISION
    contradiccion = resultado.contradicciones[0]
    assert len(contradiccion.entidades_involucradas) == 2
    assert [e.observado.campo for e in contradiccion.evidencias_enfrentadas] == [
        "nombre_chofer", "rut_chofer"
    ]
    evidencia_rut = contradiccion.evidencias_enfrentadas[1]
    assert evidencia_rut.observado.valor_original == parcial
    assert evidencia_rut.candidato
    assert evidencia_rut.apoya is False


def test_parcial_compatible_conserva_apoyo(catalogo):
    parcial = _rut(101)[-5:]
    resultado = resolver_chofer_rut("ALIAS DEMO PEÑA", parcial, catalogo)
    assert resultado.estado is EstadoResolucion.CONFIRMADO
    evidencia = next(e for e in resultado.evidencias if e.observado.campo == "rut_chofer")
    assert evidencia.apoya is True
    assert not resultado.contradicciones


def test_parcial_ambiguo_identifica_todos_los_candidatos():
    rut = _rut(202)
    base, dv = rut[:-1], rut[-1]
    formateado = f"{base[:2]}.{base[2:5]}.{base[5:]}-{dv}"
    catalogo = {
        rut: {"nombre": "PERSONA DEMO A", "activo": True},
        formateado: {"nombre": "PERSONA DEMO B", "activo": True},
        "PENDIENTE-DEMO": {
            "nombre": "PERSONA DEMO C", "activo": True,
            "aliases": ["ALIAS CENTRAL"],
        },
    }
    resultado = resolver_chofer_rut("ALIAS CENTRAL", rut[-5:], catalogo)
    assert resultado.estado is EstadoResolucion.REQUIERE_REVISION
    contradiccion = resultado.contradicciones[0]
    assert len(contradiccion.entidades_involucradas) >= 2
    assert tuple(e.observado.campo for e in contradiccion.evidencias_enfrentadas)[0] == "nombre_chofer"


def test_parcial_ambiguo_sin_nombre_requiere_revision():
    rut = _rut(202)
    base, dv = rut[:-1], rut[-1]
    catalogo = {
        rut: {"nombre": "PERSONA DEMO A", "activo": True},
        f"{base[:2]}.{base[2:5]}.{base[5:]}-{dv}": {
            "nombre": "PERSONA DEMO B", "activo": True
        },
    }
    resultado = resolver_chofer_rut("", rut[-5:], catalogo)
    assert resultado.estado is EstadoResolucion.REQUIERE_REVISION
    assert resultado.requiere_revision_humana
    assert resultado.via_decision == ViaDecisionChofer.DUPLICADO.value


def test_enie_unicode_completa_y_acentos():
    assert normalizar_nombre_identidad("PEÑA") == normalizar_nombre_identidad("PEN\u0303A")
    assert normalizar_nombre_identidad("peña") == normalizar_nombre_identidad("PEÑA")
    assert normalizar_nombre_identidad("PEÑA") != normalizar_nombre_identidad("PENA")
    assert normalizar_nombre_identidad("  José   PEÑA  ") == "JOSE PEÑA"


def test_alias_unicode_mixto_resuelve_misma_identidad(catalogo):
    resultado = resolver_chofer_rut("ALIAS DEMO PEN\u0303A", "", catalogo)
    assert resultado.estado is EstadoResolucion.CONFIRMADO
    assert resultado.identificador_canonico == f"chofer:{_rut(101)}"


def test_contexto_se_copia_y_congela_recursivamente(catalogo):
    original = {
        "anidado": {"lista": [1, {"valor": "A"}]},
        "set": {"B", "A"},
    }
    resultado = resolver_chofer_rut("", "", catalogo, original)
    original["anidado"]["lista"][1]["valor"] = "CAMBIO"
    original["set"].add("C")
    assert descongelar(resultado.contexto) == {
        "anidado": {"lista": [1, {"valor": "A"}]},
        "set": ["A", "B"],
    }
    with pytest.raises(TypeError):
        resultado.contexto["nuevo"] = "X"
    with pytest.raises(TypeError):
        resultado.contexto["anidado"]["nuevo"] = "X"
    assert json.dumps(
        descongelar(resultado.contexto), ensure_ascii=False, sort_keys=True
    ) == json.dumps(
        descongelar(resultado.contexto), ensure_ascii=False, sort_keys=True
    )


def test_snapshot_es_inmutable_estable_y_hash_determinista(catalogo):
    invertido = dict(reversed(list(catalogo.items())))
    uno = crear_snapshot_catalogo_choferes(catalogo)
    dos = crear_snapshot_catalogo_choferes(invertido)
    assert uno.sha256 == dos.sha256
    assert uno.version == dos.version
    assert uno.cantidad_registros == len(catalogo)
    catalogo[_rut(101)]["nombre"] = "MUTADO"
    catalogo["NUEVA"] = {"nombre": "NUEVA", "activo": True}
    assert uno.registros[_rut(101)]["nombre"] == "PERSONA DEMO PEÑA"
    assert "NUEVA" not in uno.registros
    with pytest.raises(TypeError):
        uno.registros[_rut(101)]["nombre"] = "OTRO"


def test_fecha_snapshot_no_cambia_hash_semantico(catalogo):
    uno = crear_snapshot_catalogo_choferes(
        catalogo, fecha_creacion=datetime(2026, 7, 29, 10, tzinfo=timezone.utc)
    )
    dos = crear_snapshot_catalogo_choferes(
        catalogo, fecha_creacion=datetime(2026, 7, 29, 11, tzinfo=timezone.utc)
    )
    assert uno.sha256 == dos.sha256
    assert uno.fecha_creacion != dos.fecha_creacion


def test_snapshot_detecta_claves_invalidas(catalogo):
    catalogo["CLAVE NO VALIDA"] = {"nombre": "DEMO", "activo": True}
    snapshot = crear_snapshot_catalogo_choferes(catalogo)
    assert snapshot.claves_invalidas == ("CLAVE NO VALIDA",)


def test_resolver_usa_snapshot_aunque_original_cambie(catalogo):
    snapshot = crear_snapshot_catalogo_choferes(catalogo)
    antes = resolver_chofer_rut("ALIAS DEMO PEÑA", "", snapshot)
    catalogo[_rut(101)]["aliases"].clear()
    despues = resolver_chofer_rut("ALIAS DEMO PEÑA", "", snapshot)
    assert antes == despues
    assert antes.version_catalogo == snapshot.version


def test_politica_visible_y_estado_independiente_del_numero(catalogo):
    valores = dict(POLITICA_CONFIANZA_CHOFER_V1_1.valores)
    valores[ViaDecisionChofer.FUZZY_UNICO] = 1.0
    politica = PoliticaConfianzaChofer("prueba-no-confirma", valores)
    resultado = resolver_chofer_rut(
        "PERSONA DEMO PENA", "", catalogo, politica_confianza=politica
    )
    assert resultado.estado is EstadoResolucion.PROPUESTO
    assert resultado.version_politica == "prueba-no-confirma"
    assert resultado.via_decision == ViaDecisionChofer.FUZZY_UNICO.value


def test_vias_forzadas_por_estado(catalogo):
    inactivo = dict(catalogo)
    inactivo[_rut(101)] = {**catalogo[_rut(101)], "activo": False}
    assert resolver_chofer_rut(
        "ALIAS DEMO PEÑA", "", inactivo
    ).via_decision == ViaDecisionChofer.INACTIVO.value
    assert resolver_chofer_rut(
        "ALIAS DEMO PEÑA", _rut(202), catalogo
    ).via_decision == ViaDecisionChofer.CONTRADICCION.value


def test_observaciones_repetidas_no_se_pierden():
    observaciones = (
        ValorObservado("campo", "PRIMERO", "PRIMERO", "OCR", Disponibilidad.DISPONIBLE),
        ValorObservado("campo", "SEGUNDO", "SEGUNDO", "OCR_2", Disponibilidad.DISPONIBLE),
    )
    resultado = ResultadoResolucion(
        "demo", observaciones, None, EstadoResolucion.NO_RESUELTO, 0.0,
        (), (), (), True,
    )
    assert resultado.valores_ocr_originales["campo"] == ("PRIMERO", "SEGUNDO")
    assert resultado.ultimos_valores_ocr_originales["campo"] == "SEGUNDO"


def _evento(
    evento_id: str,
    anterior: str,
    nuevo: str,
    *,
    revierte: str = "",
) -> EventoRedireccionIdentidad:
    return EventoRedireccionIdentidad(
        evento_id, anterior, nuevo,
        TipoRedireccionIdentidad.REDIRIGIDA if revierte else TipoRedireccionIdentidad.MIGRADA,
        datetime(2026, 7, 29, tzinfo=timezone.utc),
        "Decisión sintética confirmada", f"decision-{evento_id}", revierte,
    )


def test_redireccion_transitiva_conserva_historia():
    historial = HistorialRedireccionesIdentidad()
    historial = historial.agregar(_evento("e1", "chofer:PENDIENTE-DEMO", "chofer:RUT-DEMO"))
    historial = historial.agregar(_evento("e2", "chofer:RUT-DEMO", "chofer:RUT-NUEVO"))
    assert historial.resolver("chofer:PENDIENTE-DEMO") == "chofer:RUT-NUEVO"
    assert len(historial.eventos) == 2


def test_redireccion_se_revierte_con_nuevo_evento():
    historial = HistorialRedireccionesIdentidad().agregar(
        _evento("e1", "chofer:PENDIENTE-DEMO", "chofer:RUT-DEMO")
    )
    revertido = historial.agregar(
        _evento("e2", "chofer:RUT-DEMO", "chofer:PENDIENTE-DEMO", revierte="e1")
    )
    assert len(revertido.eventos) == 2
    assert revertido.resolver("chofer:RUT-DEMO") == "chofer:PENDIENTE-DEMO"


def test_ciclo_redirecciones_se_rechaza():
    historial = HistorialRedireccionesIdentidad().agregar(_evento("e1", "A", "B"))
    with pytest.raises(ValueError, match="ciclo"):
        historial.agregar(_evento("e2", "B", "A"))


def test_salida_independiente_del_orden_y_ocr_intacto(catalogo):
    invertido = dict(reversed(list(catalogo.items())))
    uno = resolver_chofer_rut("  ALIAS DEMO PEN\u0303A ", "", catalogo)
    dos = resolver_chofer_rut("  ALIAS DEMO PEN\u0303A ", "", invertido)
    assert uno == dos
    assert uno.valores_ocr_originales["nombre_chofer"] == (
        "  ALIAS DEMO PEN\u0303A ",
    )
    assert uno.estado is EstadoResolucion.CONFIRMADO
