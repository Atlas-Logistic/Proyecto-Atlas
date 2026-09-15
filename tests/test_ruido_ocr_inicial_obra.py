"""Bloque RUIDO OCR INICIAL (caso investigado 472516): un dígito de 1-2
cifras que el OCR antepone por error a un nombre de obra ("1
CONSTRUCTORA X SPA") no debe impedir reconciliar con una obra ya
confirmada del mismo cliente -- pero SOLO si, tras retirar el ruido, el
texto coincide EXACTO (no aproximado) con una única obra confirmada.
Generaliza el patrón "OCR-noise-vs-known-entity" ya usado en
`resolver_obra_por_variacion_ortografica_menor` /
`resolver_obra_por_prefijo_documental_confirmado`; no está hardcodeado
a 472516 (de hecho, 472516 NO resuelve con esta función: ver el test de
control abajo, que reproduce por qué)."""
from __future__ import annotations

from atlas_core.catalogo_obras_destinos import Obra, normalizar_nombre_obra
from atlas_core.motor_evidencia_obras import resolver_obra_por_ruido_ocr_inicial


def _obra(nombre, aliases=(), obra_id=None):
    return Obra(
        obra_id=obra_id or f"obra-{nombre}", cliente_id="cliente-1", nombre_canonico=nombre,
        nombre_normalizado=normalizar_nombre_obra(nombre), aliases_documentales=tuple(aliases),
        estado="CONFIRMADA", estado_vigencia="ACTIVO", evidencias=(),
        fecha_creacion="2026-01-01T00:00:00+00:00", fecha_modificacion="2026-01-01T00:00:00+00:00",
    )


def test_dos_digitos_de_ruido_se_descartan_con_match_exacto():
    obras = (_obra("EMPRESA CONST SIGRO"),)
    resultado = resolver_obra_por_ruido_ocr_inicial(
        nombre_documental="12 EMPRESA CONST SIGRO", obras_confirmadas_mismo_cliente=obras,
    )
    assert resultado is not None and resultado.nombre_canonico == "EMPRESA CONST SIGRO"


def test_un_digito_de_ruido_se_descarta_con_match_exacto():
    obras = (_obra("EBCO S.A."),)
    resultado = resolver_obra_por_ruido_ocr_inicial(
        nombre_documental="1 EBCO S.A.", obras_confirmadas_mismo_cliente=obras,
    )
    assert resultado is not None and resultado.nombre_canonico == "EBCO S.A."


def test_coincide_por_alias_documental():
    obras = (_obra("CONSTRUCTORA DON PEDRO LTDA", aliases=("CONST DON PEDRO",)),)
    resultado = resolver_obra_por_ruido_ocr_inicial(
        nombre_documental="3 CONST DON PEDRO", obras_confirmadas_mismo_cliente=obras,
    )
    assert resultado is not None and resultado.nombre_canonico == "CONSTRUCTORA DON PEDRO LTDA"


def test_sin_digito_inicial_no_aplica():
    """Control -- si no hay ruido numérico inicial que retirar, esta
    función se abstiene (no es su rol reconciliar variaciones sin
    ruido; para eso existe resolver_obra_por_variacion_ortografica_menor)."""
    obras = (_obra("EMPRESA CONST SIGRO"),)
    resultado = resolver_obra_por_ruido_ocr_inicial(
        nombre_documental="EMPRESA CONST SIGRO", obras_confirmadas_mismo_cliente=obras,
    )
    assert resultado is None


def test_match_ambiguo_entre_dos_obras_se_abstiene():
    obras = (_obra("SIGRO A", obra_id="o1"), _obra("SIGRO A", obra_id="o2"))
    # dos obras con el mismo nombre canónico normalizado -> ambigüedad real
    resultado = resolver_obra_por_ruido_ocr_inicial(
        nombre_documental="1 SIGRO A", obras_confirmadas_mismo_cliente=obras,
    )
    assert resultado is None


def test_texto_que_no_coincide_con_ninguna_obra_se_abstiene():
    obras = (_obra("EMPRESA CONST SIGRO"), _obra("EBCO S.A."))
    resultado = resolver_obra_por_ruido_ocr_inicial(
        nombre_documental="9 OTRA OBRA TOTALMENTE DISTINTA", obras_confirmadas_mismo_cliente=obras,
    )
    assert resultado is None


def test_caso_472516_no_resuelve_porque_no_es_match_exacto():
    """Control de fidelidad al caso real: el catálogo real de PRODALAM SA
    confirma 'CONSTRUCTORA LO BLANCO SPA', no 'CONSTRUCTORA LO LANCO
    SPA' como se asumía. Tras retirar el ruido ('1 '), el texto
    resultante ('CONSTRUCTORA LO LANCO SPA') NO es un match exacto
    contra 'CONSTRUCTORA LO BLANCO SPA' (difieren en más que el ruido
    retirado), así que esta función se abstiene correctamente -- no
    fuerza una reconciliación cuando la coincidencia no es exacta."""
    obras = (_obra("CONSTRUCTORA LO BLANCO SPA"),)
    resultado = resolver_obra_por_ruido_ocr_inicial(
        nombre_documental="1 CONSTRUCTORA LO LANCO SPA", obras_confirmadas_mismo_cliente=obras,
    )
    assert resultado is None
