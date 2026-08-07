from __future__ import annotations

from copy import deepcopy

import pytest

from atlas_core.inteligencia.contrato_multicampo import (
    CalidadObservacion,
    EstadoResolucion,
)
from atlas_core.inteligencia.resolucion_cliente import (
    auditar_catalogo_clientes,
    normalizar_nombre_cliente_multicampo,
    resolver_cliente_rut,
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


def _registro(
    cliente_id: str,
    razon_social: str,
    rut: str,
    *,
    aliases=(),
    nombre_comercial="",
    estado_calidad="CONFIRMADO",
    estado_vigencia="ACTIVO",
):
    return {
        "cliente_id": cliente_id,
        "razon_social": razon_social,
        "nombre_comercial": nombre_comercial,
        "rut": rut,
        "aliases": list(aliases),
        "estado_calidad": estado_calidad,
        "estado_vigencia": estado_vigencia,
    }


@pytest.fixture
def catalogo():
    return {
        "version_formato": 1,
        "clientes": [
            _registro(
                "cliente-demo-norte",
                "ACEROS DEMO DEL NORTE SpA",
                _rut(101),
                aliases=("ADN DEMO",),
                nombre_comercial="ACEROS NORTE DEMO",
            ),
            _registro(
                "cliente-demo-sur",
                "TRANSPORTES DEMO DEL SUR LTDA.",
                _rut(202),
                aliases=("TDS DEMO",),
            ),
            _registro(
                "cliente-demo-pena",
                "COMERCIAL PEÑA EIRL",
                _rut(303),
            ),
        ],
    }


def test_nombre_y_rut_exactos_mismo_cliente_confirman(catalogo):
    resultado = resolver_cliente_rut(
        "ACEROS DEMO DEL NORTE SPA", _rut(101), catalogo
    )
    assert resultado.estado is EstadoResolucion.CONFIRMADO
    assert resultado.identificador_canonico == "cliente:cliente-demo-norte"
    assert resultado.valor_canonico == "ACEROS DEMO DEL NORTE SpA"
    assert resultado.cliente_original == "ACEROS DEMO DEL NORTE SPA"
    assert resultado.rut_cliente_original == _rut(101)
    assert resultado.cliente_canonico == "ACEROS DEMO DEL NORTE SpA"
    assert resultado.rut_cliente_canonico == _rut(101)
    assert resultado.id_cliente_canonico == "cliente:cliente-demo-norte"
    assert resultado.requiere_revision is False
    assert resultado.confianza == 1.0


def test_nombre_fuzzy_y_rut_valido_mismo_cliente_confirman(catalogo):
    resultado = resolver_cliente_rut(
        "ACER0S DEMO DEL NORTE", _rut(101), catalogo
    )
    assert resultado.estado is EstadoResolucion.CONFIRMADO
    assert resultado.via_decision == "FUZZY_MAS_RUT"
    assert any(e.tipo == "NOMBRE_FUZZY" for e in resultado.evidencias)


def test_rut_exacto_y_prefijo_ocr_unico_publican_nombre_completo():
    rut = "786349109"
    catalogo = {"version_formato": 1, "clientes": [
        _registro("comercial-ayb", "COMERCIAL A Y B LTDA", rut),
        _registro("aceros-cox", "ACEROS COX COMERCIAL SA", _rut(404)),
    ]}
    resultado = resolver_cliente_rut("COMERCIAL", rut, catalogo)
    assert resultado.estado is EstadoResolucion.CONFIRMADO
    assert resultado.valor_canonico == "COMERCIAL A Y B LTDA"
    assert any(
        e.tipo == "NOMBRE_OCR_PREFIJO_UNICO_MAS_RUT_EXACTO"
        for e in resultado.evidencias
    )


def test_prefijo_ocr_ambiguo_no_confirma_aunque_el_rut_sea_valido():
    rut = _rut(405)
    catalogo = {"version_formato": 1, "clientes": [
        _registro("comercial-uno", "COMERCIAL UNO LTDA", rut),
        _registro("comercial-dos", "COMERCIAL DOS LTDA", _rut(406)),
    ]}
    resultado = resolver_cliente_rut("COMERCIAL", rut, catalogo)
    assert resultado.estado is EstadoResolucion.REQUIERE_REVISION
    assert resultado.valor_canonico is None


def test_nombre_fuerte_sin_rut_confirma(catalogo):
    resultado = resolver_cliente_rut("ADN DEMO", "", catalogo)
    assert resultado.estado is EstadoResolucion.CONFIRMADO
    assert resultado.identificador_canonico == "cliente:cliente-demo-norte"


def test_contexto_compatible_refuerza_evidencia_sin_sustituir_decision(catalogo):
    resultado = resolver_cliente_rut(
        "ADN DEMO",
        "",
        catalogo,
        {"destino": "ACEROS DEMO DEL NORTE", "material": "BARRAS"},
    )
    assert resultado.estado is EstadoResolucion.CONFIRMADO
    assert any(e.tipo == "CONTEXTO_COMPATIBLE" for e in resultado.evidencias)


def test_rut_fuerte_sin_nombre_confirma(catalogo):
    resultado = resolver_cliente_rut("", _rut(202), catalogo)
    assert resultado.estado is EstadoResolucion.CONFIRMADO
    assert resultado.identificador_canonico == "cliente:cliente-demo-sur"


def test_rut_exacto_unico_confirma_aunque_el_nombre_no_corrobore(catalogo):
    # Auditoría "Resolver de Cliente — Separación entre Identificación y
    # Corroboración" (caso real 464345): un RUT chileno válido, único,
    # activo y con calidad de catálogo confirmada basta por sí solo para
    # fijar la identidad, aunque el nombre OCR no alcance el umbral de
    # identificación fuzzy (UMBRAL_FUZZY_CLIENTE) usado cuando NO hay RUT —
    # mientras el nombre no señale, con evidencia fuerte propia, a OTRO
    # cliente del catálogo (eso sigue siendo una contradicción genuina, ver
    # test_nombre_y_rut_de_clientes_distintos_contradiccion). Antes de esta
    # corrección, la ausencia de corroboración del nombre se trataba como si
    # fuera una contradicción y bloqueaba la confirmación.
    resultado = resolver_cliente_rut(
        "XYZQW ILEGIBLE TOTALMENTE DISTINTO", _rut(101), catalogo
    )
    assert resultado.estado is EstadoResolucion.CONFIRMADO
    assert resultado.identificador_canonico == "cliente:cliente-demo-norte"
    assert resultado.via_decision == "RUT_EXACTO_UNICO"
    assert resultado.requiere_revision_humana is False


def test_nombre_y_rut_de_clientes_distintos_contradiccion(catalogo):
    resultado = resolver_cliente_rut("ADN DEMO", _rut(202), catalogo)
    assert resultado.estado is EstadoResolucion.REQUIERE_REVISION
    assert resultado.requiere_revision_humana
    assert resultado.confianza == 0.0
    contradiccion = resultado.contradicciones[0]
    assert contradiccion.campos_enfrentados == ("cliente", "rut_cliente")
    assert {e.observado.campo for e in contradiccion.evidencias_enfrentadas} == {
        "cliente", "rut_cliente"
    }
    assert len(contradiccion.entidades_involucradas) == 2


def test_rut_invalido_modulo_11_no_confirma(catalogo):
    valido = _rut(101)
    invalido = valido[:-1] + ("1" if valido[-1] != "1" else "2")
    resultado = resolver_cliente_rut("ADN DEMO", invalido, catalogo)
    assert resultado.estado is EstadoResolucion.REQUIERE_REVISION
    assert resultado.observaciones[1].calidad is CalidadObservacion.INVALIDA
    assert any(e.tipo == "RUT_INVALIDO" for e in resultado.evidencias)


def test_nombre_ambiguo_entre_dos_clientes_requiere_revision():
    catalogo = {
        "clientes": [
            _registro("uno", "EMPRESA DEMO UNO SA", _rut(1), aliases=("GRUPO DEMO",)),
            _registro("dos", "EMPRESA DEMO DOS SPA", _rut(2), aliases=("GRUPO DEMO",)),
        ]
    }
    resultado = resolver_cliente_rut("GRUPO DEMO", "", catalogo)
    assert resultado.estado is EstadoResolucion.REQUIERE_REVISION
    assert resultado.entidad is None


def test_cliente_inexistente_se_abstiene(catalogo):
    resultado = resolver_cliente_rut("CLIENTE COMPLETAMENTE AJENO", "", catalogo)
    assert resultado.estado is EstadoResolucion.NO_RESUELTO
    assert resultado.entidad is None
    assert resultado.requiere_revision_humana


@pytest.mark.parametrize(("nombre", "rut"), [("", ""), (None, None)])
def test_ocr_vacio_se_abstiene(catalogo, nombre, rut):
    resultado = resolver_cliente_rut(nombre, rut, catalogo)
    assert resultado.estado is EstadoResolucion.NO_RESUELTO
    assert resultado.requiere_revision_humana


@pytest.mark.parametrize(
    "variante",
    [
        "ACEROS DEMO DEL NORTE SA",
        "ACEROS DEMO DEL NORTE S.A.",
        "ACEROS DEMO DEL NORTE SpA",
        "ACEROS DEMO DEL NORTE SPA",
        "ACEROS DEMO DEL NORTE LTDA",
        "ACEROS DEMO DEL NORTE EIRL",
        "ACEROS DEMO DEL NORTE SOCIEDAD ANONIMA",
        "ACEROS DEMO DEL NORTE SOCIEDAD POR ACCIONES",
    ],
)
def test_sufijos_societarios_equivalentes(variante):
    assert normalizar_nombre_cliente_multicampo(variante) == (
        "ACEROS DEMO DEL NORTE"
    )


def test_acentos_puntuacion_espacios_mayusculas_y_nfd(catalogo):
    resultado = resolver_cliente_rut(
        "  comercial,  pen\u0303a   e.i.r.l. ", "", catalogo
    )
    assert resultado.estado is EstadoResolucion.CONFIRMADO
    assert resultado.identificador_canonico == "cliente:cliente-demo-pena"
    assert normalizar_nombre_cliente_multicampo("PEÑA") != (
        normalizar_nombre_cliente_multicampo("PENA")
    )


def test_no_acepta_subcadena_corta_peligrosa():
    catalogo = {
        "clientes": [
            _registro("uno", "ACERO DEMO SA", _rut(1)),
            _registro("dos", "ACERO DEMO ESPECIAL SPA", _rut(2)),
        ]
    }
    resultado = resolver_cliente_rut("ACERO", "", catalogo)
    assert resultado.estado is EstadoResolucion.NO_RESUELTO
    assert resultado.entidad is None


def test_cliente_no_se_mezcla_con_obra_o_destino(catalogo):
    resultado = resolver_cliente_rut(
        "OBRA DEMO CENTRAL",
        "",
        catalogo,
        {"destino": "ACEROS DEMO DEL NORTE", "comuna": "DEMO"},
    )
    assert resultado.estado is EstadoResolucion.NO_RESUELTO
    assert resultado.entidad is None
    assert resultado.contexto["destino"] == "ACEROS DEMO DEL NORTE"
    assert all("destino" not in evidencia.tipo.lower() for evidencia in resultado.evidencias)


def test_destino_no_fuerza_cliente_ante_nombre_ambiguo():
    catalogo = {
        "clientes": [
            _registro("uno", "CLIENTE DEMO UNO SA", _rut(1), aliases=("DEMO COMUN",)),
            _registro("dos", "CLIENTE DEMO DOS SA", _rut(2), aliases=("DEMO COMUN",)),
        ]
    }
    resultado = resolver_cliente_rut(
        "DEMO COMUN", "", catalogo, {"destino": "CLIENTE DEMO UNO"}
    )
    assert resultado.estado is EstadoResolucion.REQUIERE_REVISION
    assert resultado.entidad is None


def test_ocr_original_permanece_intacto(catalogo):
    original = "  Acéros Demo del Norte, S.p.A. "
    rut_original = f"{_rut(101)[:-1]}-{_rut(101)[-1]}"
    resultado = resolver_cliente_rut(original, rut_original, catalogo)
    assert resultado.valores_ocr_originales["cliente"] == (original,)
    assert resultado.valores_ocr_originales["rut_cliente"] == (rut_original,)


def test_fuzzy_sin_rut_solo_propone(catalogo):
    resultado = resolver_cliente_rut("ACER0S DEMO DEL NORTE", "", catalogo)
    assert resultado.estado is EstadoResolucion.PROPUESTO
    assert resultado.requiere_revision_humana
    assert resultado.identificador_canonico == "cliente:cliente-demo-norte"


def test_fuzzy_sin_rut_de_alta_confianza_confirma_sin_rut(catalogo):
    # Falta solo la última letra ("NORT" en vez de "NORTE"): similitud 0.976
    # contra el catálogo, muy por encima del umbral de solo-propuesta (0.88)
    # y del nuevo umbral de confirmación (0.97). Decisión de producto: el RUT
    # de cliente casi nunca viene legible en guías reales, así que un fuzzy de
    # esta confianza debe confirmar sin exigir RUT.
    resultado = resolver_cliente_rut("ACEROS DEMO DEL NORT", "", catalogo)
    assert resultado.estado is EstadoResolucion.CONFIRMADO
    assert resultado.via_decision == "FUZZY_ALTA_CONFIANZA"
    assert resultado.identificador_canonico == "cliente:cliente-demo-norte"
    assert resultado.requiere_revision_humana is False


def test_catalogo_no_muta_y_propuesta_no_aprende(catalogo):
    original = deepcopy(catalogo)
    uno = resolver_cliente_rut("ACER0S DEMO DEL NORTE", "", catalogo)
    dos = resolver_cliente_rut("ACER0S DEMO DEL NORTE", "", catalogo)
    assert uno == dos
    assert catalogo == original
    assert all(
        "ACER0S DEMO DEL NORTE" not in registro["aliases"]
        for registro in catalogo["clientes"]
    )


def test_auditoria_detecta_rut_y_alias_duplicados():
    rut = _rut(1)
    catalogo = {
        "clientes": [
            _registro("uno", "DEMO UNO SA", rut, aliases=("ALIAS COMUN",)),
            _registro("dos", "DEMO DOS SPA", rut, aliases=("ALIAS COMUN",)),
        ]
    }
    tipos = {hallazgo.tipo for hallazgo in auditar_catalogo_clientes(catalogo)}
    assert {"RUT_DUPLICADO", "ALIAS_COMPARTIDO"} <= tipos
    assert resolver_cliente_rut("", rut, catalogo).estado is (
        EstadoResolucion.REQUIERE_REVISION
    )


def test_codigo_destinatario_sin_nombre_ni_rut_confirma_cliente(catalogo):
    # Caso real guía 464110: cliente y RUT vienen ilegibles en el documento,
    # pero el Código Destinatario ya identificó, a través de un destino
    # confirmado y único, el cliente_id vinculado en el catálogo maestro.
    resultado = resolver_cliente_rut(
        "", "", catalogo,
        id_cliente_por_destino_codigo="cliente-demo-sur",
    )
    assert resultado.estado is EstadoResolucion.CONFIRMADO
    assert resultado.identificador_canonico == "cliente:cliente-demo-sur"
    assert resultado.valor_canonico == "TRANSPORTES DEMO DEL SUR LTDA."
    assert resultado.via_decision == "CLIENTE_ID_POR_DESTINO_CODIGO"
    assert any(
        e.tipo == "CLIENTE_ID_POR_DESTINO_CODIGO" for e in resultado.evidencias
    )
    assert not resultado.requiere_revision_humana


def test_codigo_destinatario_inexistente_en_catalogo_se_abstiene(catalogo):
    resultado = resolver_cliente_rut(
        "", "", catalogo,
        id_cliente_por_destino_codigo="cliente-que-no-existe",
    )
    assert resultado.estado is EstadoResolucion.NO_RESUELTO
    assert resultado.entidad is None


def test_codigo_destinatario_ausente_no_cambia_comportamiento_previo(catalogo):
    # Caso real guía 464260: no hay destino confirmado por código para esta
    # guía, así que la evidencia cruzada nunca llega; debe abstenerse igual
    # que sin el mecanismo nuevo.
    resultado = resolver_cliente_rut("", "", catalogo)
    assert resultado.estado is EstadoResolucion.NO_RESUELTO
    assert resultado.entidad is None


def test_codigo_destinatario_en_conflicto_con_rut_exige_revision(catalogo):
    resultado = resolver_cliente_rut(
        "", _rut(101), catalogo,
        id_cliente_por_destino_codigo="cliente-demo-sur",
    )
    assert resultado.estado is EstadoResolucion.REQUIERE_REVISION
    assert resultado.requiere_revision_humana
    contradiccion = next(
        c for c in resultado.contradicciones
        if c.campos_enfrentados == ("cliente", "cliente_id_por_destino_codigo")
    )
    assert len(contradiccion.entidades_involucradas) == 2


def test_codigo_destinatario_en_conflicto_con_nombre_exige_revision(catalogo):
    resultado = resolver_cliente_rut(
        "ADN DEMO", "", catalogo,
        id_cliente_por_destino_codigo="cliente-demo-sur",
    )
    assert resultado.estado is EstadoResolucion.REQUIERE_REVISION
    assert any(
        c.campos_enfrentados == ("cliente", "cliente_id_por_destino_codigo")
        for c in resultado.contradicciones
    )


def test_rut_exacto_tiene_prioridad_sobre_codigo_destinatario_compatible(catalogo):
    resultado = resolver_cliente_rut(
        "", _rut(202), catalogo,
        id_cliente_por_destino_codigo="cliente-demo-sur",
    )
    assert resultado.estado is EstadoResolucion.CONFIRMADO
    assert resultado.identificador_canonico == "cliente:cliente-demo-sur"
    assert resultado.via_decision == "RUT_EXACTO_UNICO"


def test_codigo_destinatario_de_cliente_no_confirmado_exige_revision():
    catalogo = {
        "clientes": [
            _registro(
                "pendiente", "CLIENTE SIN CONFIRMAR SPA", _rut(9),
                estado_calidad="PENDIENTE",
            ),
        ]
    }
    resultado = resolver_cliente_rut(
        "", "", catalogo, id_cliente_por_destino_codigo="pendiente",
    )
    assert resultado.estado is EstadoResolucion.REQUIERE_REVISION
    assert resultado.via_decision == "CALIDAD_NO_CONFIRMADA"
