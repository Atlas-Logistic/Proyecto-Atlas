"""Bloque C1 -- CONTROL GENERAL DE CREDIBILIDAD ANTES DE PUBLICAR DATOS.

Regresiones pedidas explícitamente por el bloque:
1. material normal -> pasa.
2. material contaminado por otras secciones -> dudoso/no publicable.
3. campo dudoso con evidencia relacionada suficiente -> puede escalar B1.
4. B1 insuficiente -> abstención limpia (nunca resuelve una ambigüedad
   sin evidencia suficiente).
5. campo determinista confiable -> B1 no se invoca.
6. valor sospechoso nunca se sustituye por uno inventado.
7. Mobile y Desktop/lote tienen la misma conducta.

Casos reales (472623/472624) usados sólo como evidencia -- ningún
umbral ni vocabulario del propio código de producción (`atlas_core.
credibilidad_campos`) referencia una guía, empresa o cliente concretos."""
from __future__ import annotations

from unittest.mock import Mock

from atlas_core import procesamiento_masivo
from atlas_core.atlas_ia.contratos import (
    ContextoRazonamiento, HipotesisIA, RESULTADO_HIPOTESIS_ABSTENCION,
    RESULTADO_HIPOTESIS_PROPUESTA, calcular_hipotesis_id,
)
from atlas_core.atlas_ia.orquestador import ABSTENCION_IA, OrquestadorAtlasIA
from atlas_core.atlas_ia.registro_problemas import detectar_problemas_elegibles
from atlas_core.procesamiento_masivo import MotivoRevisionDocumento, procesar_archivo

_MATERIAL_CONTAMINADO_472624 = (
    "Codigo Cliente 0001004274 FECHA DE EMISION 26-08-2026 SODIMAC SA "
    "SENOR(ES) 96.792.430-K RUT VIA AL X MENOR MAI C GIRO AV PDIE "
    "EDUARDO FREI 3092 DIRECCION COMUNA RENCA CIUDAD SANTIAGO "
    "Operacion constituye Venta INDICADOR TRASLADO TRANSPORTE "
    "TRANSPORTES MBI SPA EMPRESA DESCRIPCION CANTIDAD Codigo "
    "HORMIGON 8MM 12M A630-420H (N) 3.025/110002847 B Coladas: 2617677302"
)


def _datos_base(**overrides):
    datos = {
        "número de guía": "900001",
        "número de transporte": "0000900001",
        "cliente": "COMERCIAL PRUEBA SPA",
        "obra destino": "OBRA DE PRUEBA CENTRAL",
        "chofer": "CHOFER DE PRUEBA",
        "RUT del cliente": "11.111.111-1",
        "RUT del chofer": "11.111.111-1",
        "patente del tracto": "AB1234",
        "patente del carro": "CD5678",
    }
    datos.update(overrides)
    return datos


def _preparar_mocks(monkeypatch, datos, descripcion_material=""):
    monkeypatch.setattr(procesamiento_masivo, "leer_texto_imagen", Mock(return_value=["FECHA DE EMISION 11-08-2026"]))
    monkeypatch.setattr(procesamiento_masivo, "leer_bloques_imagen", Mock(return_value=[]))
    monkeypatch.setattr(procesamiento_masivo, "extraer_datos", Mock(return_value=datos))
    monkeypatch.setattr(
        procesamiento_masivo, "extraer_descripcion_material", Mock(return_value=descripcion_material),
    )


# ============================================================
# 1/2. Pipeline completo (`procesar_archivo`): material normal pasa,
#      material contaminado queda marcado -- nunca publicado limpio.
# ============================================================


def test_material_normal_pasa_limpio_por_el_pipeline_completo(tmp_path, monkeypatch):
    _preparar_mocks(monkeypatch, _datos_base(), descripcion_material="HORMIGON 8MM 12M A630-420H (N)")

    resultado = procesar_archivo(tmp_path / "guia.jpg")

    assert resultado["descripcion_material"] == "HORMIGON 8MM 12M A630-420H (N)"
    assert "MATERIAL_POSIBLEMENTE_CONTAMINADO" not in resultado["motivos_revision_documento"]
    assert resultado["indicador_revision"] == "OK"


def test_material_contaminado_por_otras_secciones_queda_marcado_no_publicable_limpio(tmp_path, monkeypatch):
    """Caso real 472624: el campo MATERIAL trae, de hecho, el bloque
    completo cliente/fecha/RUT/dirección/transportista de la guía."""
    _preparar_mocks(monkeypatch, _datos_base(), descripcion_material=_MATERIAL_CONTAMINADO_472624)

    resultado = procesar_archivo(tmp_path / "guia.jpg")

    # 6. El valor documental NUNCA se reemplaza -- se conserva íntegro.
    assert resultado["descripcion_material"] == _MATERIAL_CONTAMINADO_472624
    # 2. Pero SÍ queda marcado -- nunca "OK" silencioso con basura adentro.
    assert MotivoRevisionDocumento.MATERIAL_POSIBLEMENTE_CONTAMINADO.value in resultado["motivos_revision_documento"]
    assert resultado["indicador_revision"] == "REVISAR"
    assert resultado["estado_documental"] == "REQUIERE_REVISION"


def test_obra_destino_etiqueta_generica_y_destino_fragmento_truncado_quedan_marcados(tmp_path, monkeypatch):
    """Caso real 472624: obra_destino = "TRANSPORTES" (etiqueta
    documental genérica, nunca una obra), despachar_a truncado a "SAN".
    despachar_a se lee desde el texto OCR (`extraer_identificadores_
    destino`), no desde `datos` -- se simula vía `leer_texto_imagen`."""
    monkeypatch.setattr(
        procesamiento_masivo, "leer_texto_imagen",
        Mock(return_value=["FECHA DE EMISION 11-08-2026", "DESPACHAR A SAN"]),
    )
    monkeypatch.setattr(procesamiento_masivo, "leer_bloques_imagen", Mock(return_value=[]))
    monkeypatch.setattr(
        procesamiento_masivo, "extraer_datos", Mock(return_value=_datos_base(**{"obra destino": "TRANSPORTES"})),
    )
    monkeypatch.setattr(
        procesamiento_masivo, "extraer_descripcion_material",
        Mock(return_value="HORMIGON 8MM 12M A630-420H (N)"),
    )

    resultado = procesar_archivo(tmp_path / "guia.jpg")

    assert resultado["obra_destino"] == "TRANSPORTES"  # nunca se reemplaza
    assert MotivoRevisionDocumento.OBRA_DESTINO_POSIBLEMENTE_INVALIDA.value in resultado["motivos_revision_documento"]
    assert resultado["indicador_revision"] == "REVISAR"


# ============================================================
# 5. Campo determinista confiable -> B1 no se invoca (la puerta común
#    ni siquiera detecta el problema).
# ============================================================


def test_material_confiable_nunca_es_elegible_para_b1():
    fila = {
        "numero_guia": "1", "numero_transporte": "1",
        "motivos_revision_documento": "", "motivo_ruta": "", "motivo_origen_gps": "",
        "descripcion_material": "HORMIGON 8MM",
    }
    encontrados = detectar_problemas_elegibles(fila)
    assert not any(codigo == "MATERIAL_POSIBLEMENTE_CONTAMINADO" for _, codigo in encontrados)


# ============================================================
# 3. Campo dudoso con evidencia relacionada suficiente -> puede
#    escalar a B1 con esa evidencia realmente adjunta.
# ============================================================


def test_material_contaminado_con_documento_hermano_limpio_escala_con_evidencia_real():
    fila = {
        "numero_guia": "472624", "numero_transporte": "0000355433",
        "motivos_revision_documento": "MATERIAL_POSIBLEMENTE_CONTAMINADO",
        "motivo_ruta": "", "motivo_origen_gps": "",
        "descripcion_material": _MATERIAL_CONTAMINADO_472624,
    }
    hermano = {
        "numero_guia": "472623", "numero_transporte": "0000355433",
        "descripcion_material": "HORMIGON 1OMM 12M A630-42OH (N)",
    }
    encontrados = detectar_problemas_elegibles(fila)
    tipo_material = next(tipo for tipo, codigo in encontrados if codigo == "MATERIAL_POSIBLEMENTE_CONTAMINADO")
    assert tipo_material.dominio == "MATERIAL"
    assert "DOCUMENTOS_RELACIONADOS" in tipo_material.herramientas

    evidencias = tipo_material.recopilar_evidencia(fila, [hermano], carpeta_catalogos=None)
    assert len(evidencias) == 1
    assert evidencias[0].valor == "HORMIGON 1OMM 12M A630-42OH (N)"


# ============================================================
# 4. B1 insuficiente -> abstención limpia (nunca resuelve una
#    ambigüedad B/3 sin evidencia suficiente) -- mismo criterio general
#    ya probado en U1/M3, reconstruido aquí para el dominio MATERIAL.
# ============================================================


class _ProveedorSeAbstieneSinEvidencia:
    def razonar(self, contexto: ContextoRazonamiento) -> HipotesisIA:
        return HipotesisIA(
            hipotesis_id=calcular_hipotesis_id(contexto, ""), campo=contexto.campo,
            valor_observado=contexto.valor_documental, valor_propuesto="",
            resultado=RESULTADO_HIPOTESIS_ABSTENCION,
            explicacion="Sin documento hermano ni evidencia suficiente para corroborar.",
        )


def test_material_contaminado_sin_evidencia_relacionada_b1_se_abstiene_limpio():
    contexto = ContextoRazonamiento(
        campo="descripcion_material", valor_documental=_MATERIAL_CONTAMINADO_472624,
        rut_chofer="", numero_guia="472624", numero_transporte="0000355433",
        evidencias=(), resultado_motor="REQUIERE_REVISION",
        herramientas_disponibles=("DOCUMENTOS_RELACIONADOS",),
    )
    resultado = OrquestadorAtlasIA(proveedor=_ProveedorSeAbstieneSinEvidencia(), herramientas={}).resolver(contexto)
    assert resultado.estado == ABSTENCION_IA
    assert resultado.hipotesis.valor_propuesto == ""


def test_material_contaminado_b1_nunca_puede_proponer_un_valor_inventado():
    """6 (a nivel B1): incluso si el proveedor "alucinara" un valor de
    material limpio no respaldado por ninguna evidencia real, el
    validador universal (misma barrera anti-alucinación de siempre) lo
    rechaza -- B1 nunca puede limpiar un dato sólo porque parece raro."""
    from atlas_core.atlas_ia.validadores import validar_hipotesis_multicampo
    from atlas_core.atlas_ia.contratos import MOTIVO_VALOR_NO_RESPALDADO

    contexto = ContextoRazonamiento(
        campo="descripcion_material", valor_documental=_MATERIAL_CONTAMINADO_472624,
        rut_chofer="", numero_guia="472624", numero_transporte="0000355433",
        evidencias=(), resultado_motor="REQUIERE_REVISION",
    )
    hipotesis_inventada = HipotesisIA(
        hipotesis_id=calcular_hipotesis_id(contexto, "HORMIGON GENERICO"), campo="descripcion_material",
        valor_observado=_MATERIAL_CONTAMINADO_472624, valor_propuesto="HORMIGON GENERICO",
        resultado=RESULTADO_HIPOTESIS_PROPUESTA,
    )
    resultado = validar_hipotesis_multicampo(hipotesis_inventada, contexto)
    assert resultado.aceptada is False
    assert resultado.motivo_rechazo == MOTIVO_VALOR_NO_RESPALDADO


# ============================================================
# 7. Mobile y Desktop/lote tienen la misma conducta -- prueba
#    estructural (mismo criterio de U1): ambos caminos delegan en el
#    MISMO `procesar_archivo`, nunca una copia paralela de esta capa.
# ============================================================


def test_mobile_y_desktop_ejecutan_la_misma_capa_de_credibilidad():
    import inspect

    fuente_mobile = inspect.getsource(__import__("atlas_core.mobile", fromlist=["procesar_envio_mobile"]).procesar_envio_mobile)
    fuente_lote = inspect.getsource(procesamiento_masivo.procesar_carpeta)
    assert "procesar_archivo(" in fuente_mobile
    assert "procesar_archivo(" in fuente_lote
