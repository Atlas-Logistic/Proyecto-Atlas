from atlas_core.atlas_ia import investigacion_revision
from atlas_core.b1_operador import ACCION_INVESTIGAR_REVISION, OperadorB1, interpretar_determinista


def test_intencion_investiga_obra_de_guia():
    resultado = interpretar_determinista("Investiga la obra de la guía 474993")
    assert resultado.accion == ACCION_INVESTIGAR_REVISION
    assert resultado.parametros == {"numero_guia": "474993", "campos": ("obra_destino",)}


def test_intencion_investiga_direccion_de_guia():
    resultado = interpretar_determinista("Busca la dirección completa de la guía 474993")
    assert resultado.accion == ACCION_INVESTIGAR_REVISION
    assert resultado.parametros == {"numero_guia": "474993", "campos": ("despachar_a_crudo",)}


def test_intencion_investiga_obra_y_direccion_de_guia():
    resultado = interpretar_determinista(
        "Investiga la guía 474993 y dime cuál es el nombre completo de la obra y cuál es la dirección completa del destino")
    assert resultado.accion == ACCION_INVESTIGAR_REVISION
    assert resultado.parametros == {"numero_guia": "474993", "campos": ("obra_destino", "despachar_a_crudo")}


def test_investigacion_es_informativa_y_no_crea_preview(tmp_path, monkeypatch):
    (tmp_path / "operacion" / "actual").mkdir(parents=True)
    llamadas = []

    def investigar(numero_guia, **kwargs):
        llamadas.append((numero_guia, kwargs))
        return {"expedientes": [{
            "CAMPO": "obra_destino",
            "HECHOS_DOCUMENTALES": {"valor_extraido": "OBRA PARCIAL"},
            "PROPUESTA": "OBRA COMPLETA LIMITADA",
            "EVALUACION_CANDIDATOS_EXTERNOS": {"razon": "Dos fuentes independientes convergen."},
            "PREVIEW_OPERACIONAL": {
                "valor_actual": "OBRA PARCIAL", "valor_propuesto": "OBRA COMPLETA LIMITADA",
                "evidencia_relevante": "Dos fuentes independientes convergen.",
                "consecuencia_operacional": "La asociación sólo cambiaría tras confirmación humana.",
            },
        }]}

    monkeypatch.setattr(investigacion_revision, "investigar_revision", investigar)
    operador = OperadorB1(tmp_path)
    respuesta = operador.atender("chat-1", "Investiga la obra de la guía 474993")

    assert respuesta["estado"] == "RESULTADO_INVESTIGACION"
    assert respuesta["propuestas"]["obra"]["valor_propuesto"] == "OBRA COMPLETA LIMITADA"
    assert "Confirmas" not in respuesta["mensaje"]
    assert operador.pendiente("chat-1") is None
    assert llamadas == [("474993", {"raiz_atlas": tmp_path, "campos_solicitados": ("obra_destino",),
                                     "permitir_ocr_nuevo": False})]


def test_pregunta_normal_por_obra_sigue_siendo_informativa_y_no_accion():
    assert interpretar_determinista("¿Cuál es la obra de la guía 474993?") is None
