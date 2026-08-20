"""Bloque ATLAS IA A1 -- shadow harness (`atlas_core.atlas_ia.shadow`).

Cubre T8 (sin efectos laterales), T9 (adaptador real contra
`evaluar_evidencia_patente`) y T10 (caso Ortiz como benchmark
ESTRUCTURAL, nunca cognitivo -- ver docstring de `test_t10_...` más
abajo). Mismo patrón de fixtures que
`tests/test_motor_evidencia_vehiculos.py` -- no se reinventa."""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from atlas_core.atlas_ia.adaptadores import contexto_desde_resultado_evaluar_evidencia_patente
from atlas_core.atlas_ia.contratos import RESULTADO_HIPOTESIS_PROPUESTA
from atlas_core.atlas_ia.proveedor import ProveedorModeloIASimulado, RespuestaSimulada
from atlas_core.atlas_ia.shadow import ejecutar_caso_shadow, ejecutar_shadow
from atlas_core.catalogo_vehiculos import TipoVehiculo, cargar_catalogo_vehiculos, confirmar_vehiculo
from atlas_core.decisiones_pendientes import (
    RESULTADO_SUGERENCIA_HUMANA,
    evaluar_evidencia_patente,
)
from atlas_core.procesamiento_masivo import COLUMNAS

RUT_ORTIZ = "18626166-6"
FECHA = "05-08-2026"


def _fila(**overrides):
    fila = {c: "" for c in COLUMNAS}
    fila.update({
        "archivo": "1.jpeg", "estado_procesamiento": "OK", "numero_guia": "1",
        "numero_transporte": "T-1", "fecha": FECHA, "chofer": "CHOFER PRUEBA",
        "rut_chofer": RUT_ORTIZ, "patente_tracto": "AB1234", "patente_rampla": "CD5678",
    })
    fila.update(overrides)
    return fila


def _catalogo(tmp_path):
    ruta = tmp_path / "vehiculos.json"
    ruta.write_text(json.dumps({"version": 1, "vehiculos": []}), encoding="utf-8")
    return ruta


def _confirmar(ruta, patente, tipo, *, rut_chofer_asociado=""):
    return confirmar_vehiculo(
        ruta, patente=patente, tipo=tipo, actor="JAVIER_MBT",
        fuente_decision="TEST", fecha=datetime.now(timezone.utc),
        rut_chofer_asociado=rut_chofer_asociado,
    )


def _resultado_y_contexto_ortiz(tmp_path):
    """Reproduce exactamente el fixture real de
    `test_ortiz_xf3662_nunca_se_autocorrige_a_xf3629`
    (`tests/test_motor_evidencia_vehiculos.py`): guía 464036, patente
    tracto documental XF3662, candidato circunstancial XF3629 (mismo RUT,
    otro transporte, SIN confirmación humana). Produce SUGERENCIA_HUMANA,
    nunca RESUELTO_AUTOMATICAMENTE."""
    ruta = _catalogo(tmp_path)
    _confirmar(ruta, "XF3629", TipoVehiculo.CAMION_RIGIDO)  # sin rut_chofer_asociado
    vehiculos = cargar_catalogo_vehiculos(ruta).homologables()
    filas = [
        _fila(numero_guia="1", numero_transporte="T-1", patente_tracto="XF3662"),
        _fila(numero_guia="2", numero_transporte="T-2", patente_tracto="XF3629"),
    ]
    resultado = evaluar_evidencia_patente(
        campo="patente_tracto", valor_documental="XF3662", rut_chofer=RUT_ORTIZ,
        tipo_esperado=None, numero_transporte_actual="T-1", filas=filas, vehiculos=vehiculos,
    )
    contexto = contexto_desde_resultado_evaluar_evidencia_patente(
        campo="patente_tracto", valor_documental="XF3662", rut_chofer=RUT_ORTIZ,
        numero_guia="1", numero_transporte="T-1", resultado_evidencia=resultado,
    )
    return resultado, contexto


# ---------------------------------------------------------------------
# T9 -- adaptador real
# ---------------------------------------------------------------------


def test_t9_adaptador_convierte_resultado_real_a_contexto(tmp_path):
    resultado, contexto = _resultado_y_contexto_ortiz(tmp_path)
    assert resultado["resultado"] == RESULTADO_SUGERENCIA_HUMANA  # el Motor determinista, sin tocar

    assert contexto.campo == "patente_tracto"
    assert contexto.valor_documental == "XF3662"
    assert contexto.rut_chofer == RUT_ORTIZ
    assert contexto.resultado_motor == RESULTADO_SUGERENCIA_HUMANA
    assert contexto.explicacion_motor == resultado["explicacion"]
    assert "XF3629" in contexto.valores_evidencia()
    # nada se oculta: la cantidad de evidencias del contexto coincide con
    # la cantidad de candidatos que el Motor determinista reunió.
    assert len(contexto.evidencias) == len(resultado["candidatos"])
    assert contexto.evidencias[0].referencias_fuente == (
        "guia=2;transporte=T-2;relacion=TRANSPORTE_INDEPENDIENTE",
    )
    # el candidato es circunstancial (sin confirmación humana) -- nunca se
    # reclasifica aquí como DECISION_HUMANA.
    assert all(not e.es_decision_humana for e in contexto.evidencias)


# ---------------------------------------------------------------------
# T10 -- caso Ortiz como benchmark ESTRUCTURAL
# ---------------------------------------------------------------------


def test_t10_caso_ortiz_hipotesis_estructuralmente_valida(tmp_path):
    """IMPORTANTE (ver AJUSTE 3 del bloque A1): esto NO demuestra que
    "Atlas IA acertó Ortiz". El proveedor simulado está configurado a mano
    para proponer XF3629 -- no razonó nada. Lo único que este test prueba
    es que, CUANDO un futuro modelo real llegue a esa misma conclusión, la
    arquitectura ya construida (adaptador -> contexto -> proveedor ->
    validador -> ResultadoShadow) puede recibirla, validarla contra
    evidencia real y auditarla correctamente -- sin inventar nada y sin
    aplicar nada a la operación."""
    _, contexto = _resultado_y_contexto_ortiz(tmp_path)
    proveedor = ProveedorModeloIASimulado(respuestas_por_valor_documental={
        "XF3662": RespuestaSimulada(
            resultado=RESULTADO_HIPOTESIS_PROPUESTA, valor_propuesto="XF3629",
            evidencia_usada=("veh:XF3629",),
            explicacion="Configurado a mano para este test -- no es un acierto de razonamiento.",
        ),
    })
    resultado_shadow = ejecutar_caso_shadow(
        caso_id="464036", contexto=contexto, proveedor=proveedor, ground_truth_humano="XF3629",
    )
    assert resultado_shadow.hipotesis.valor_propuesto == "XF3629"
    assert resultado_shadow.validacion.aceptada is True
    assert resultado_shadow.resultado_motor == RESULTADO_SUGERENCIA_HUMANA
    assert resultado_shadow.ground_truth_humano == "XF3629"


# ---------------------------------------------------------------------
# T8 -- sin efectos laterales
# ---------------------------------------------------------------------


def test_t8_shadow_sin_persistir_no_escribe_nada(tmp_path):
    ruta_catalogo, contexto = None, None
    _, contexto = _resultado_y_contexto_ortiz(tmp_path)
    contenido_catalogo_antes = (tmp_path / "vehiculos.json").read_bytes()
    archivos_antes = sorted(p.name for p in tmp_path.iterdir())

    proveedor = ProveedorModeloIASimulado(respuestas_por_valor_documental={
        "XF3662": RespuestaSimulada(resultado=RESULTADO_HIPOTESIS_PROPUESTA, valor_propuesto="XF3629"),
    })
    resultados = ejecutar_shadow(
        casos=[("464036", contexto, "XF3629")], proveedor=proveedor,
    )  # persistir=False por defecto -- ni siquiera se menciona ruta_salida

    assert len(resultados) == 1
    # cero archivos nuevos, cero modificados -- el catálogo de fixture es
    # el único artefacto en tmp_path y sigue byte a byte igual.
    assert (tmp_path / "vehiculos.json").read_bytes() == contenido_catalogo_antes
    assert sorted(p.name for p in tmp_path.iterdir()) == archivos_antes


def test_t8_shadow_persistir_sin_ruta_es_error(tmp_path):
    _, contexto = _resultado_y_contexto_ortiz(tmp_path)
    proveedor = ProveedorModeloIASimulado(respuestas_por_valor_documental={})
    with pytest.raises(ValueError, match="ruta_salida"):
        ejecutar_shadow(casos=[("464036", contexto, "")], proveedor=proveedor, persistir=True)


def test_t8_shadow_persistir_escribe_solo_en_la_ruta_indicada(tmp_path):
    _, contexto = _resultado_y_contexto_ortiz(tmp_path)
    proveedor = ProveedorModeloIASimulado(respuestas_por_valor_documental={
        "XF3662": RespuestaSimulada(resultado=RESULTADO_HIPOTESIS_PROPUESTA, valor_propuesto="XF3629"),
    })
    ruta_salida = tmp_path / "salida_explicita" / "resultado_shadow.json"
    resultados = ejecutar_shadow(
        casos=[("464036", contexto, "XF3629")], proveedor=proveedor,
        persistir=True, ruta_salida=ruta_salida,
    )
    assert ruta_salida.is_file()
    contenido = json.loads(ruta_salida.read_text(encoding="utf-8"))
    assert contenido[0]["caso_id"] == "464036"
    assert contenido[0]["hipotesis"]["valor_propuesto"] == "XF3629"
    assert len(resultados) == 1
    # nada se escribió fuera de la ruta explícita -- el catálogo sigue intacto.
    assert (tmp_path / "vehiculos.json").is_file()


def test_t8_shadow_nunca_importa_mecanismos_de_autodeteccion_de_drive():
    """Verificación estática mínima: el módulo no importa el mecanismo de
    autodetección de la raíz portable de Atlas (`almacenamiento_portable`)
    ni lee variables de entorno -- toda ruta de escritura llega siempre
    como parámetro explícito (`ruta_salida`)."""
    import ast

    import atlas_core.atlas_ia.shadow as modulo_shadow
    with open(modulo_shadow.__file__, encoding="utf-8") as f:
        arbol = ast.parse(f.read())

    modulos_importados = {
        nodo.module for nodo in ast.walk(arbol) if isinstance(nodo, ast.ImportFrom)
    } | {
        alias.name for nodo in ast.walk(arbol) if isinstance(nodo, ast.Import) for alias in nodo.names
    }
    assert "atlas_core.almacenamiento_portable" not in modulos_importados
    assert "os" not in modulos_importados

    llamadas_a_environ = [
        nodo for nodo in ast.walk(arbol)
        if isinstance(nodo, ast.Attribute) and nodo.attr == "environ"
    ]
    assert not llamadas_a_environ
