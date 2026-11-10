from datetime import date

import pytest

from atlas_core.expediente_digital import consultar_expediente
from atlas_core.extraccion_vencimientos_vehiculos import extraer_vencimientos_vehiculos
from atlas_core.identificacion_patentes import identificar_patentes_documentos
from tests.test_fichas_vehiculos_mobile import (
    CloudFalso, JPEG, SOLO, _doc_cloud, _sincronizar, _vehiculo, raiz,  # noqa: F401
)
from tests.test_identificacion_patentes import OCRFalso

RC, ROBO = "POLIZA_RESPONSABILIDAD_CIVIL", "POLIZA_ROBO"


def extraer(raiz, textos):
    identificar_patentes_documentos(raiz, comprobar=lambda: None, fabrica_ocr=lambda: OCRFalso(textos))
    extraer_vencimientos_vehiculos(raiz, comprobar=lambda: None, fabrica_ocr=lambda: OCRFalso(textos))


def ver(raiz):
    return consultar_expediente(raiz, empresa="MBT", entidad="VEHICULO", referencia="CC5678", hoy=date(2026, 11, 9))


@pytest.mark.parametrize("cobertura", ["RESPONSABILIDAD CIVIL", "RESPONSABILIDAD CIVIL Y ROBO"])
@pytest.mark.parametrize("vinculo", [True, False])
@pytest.mark.parametrize("tipo_nuevo", [RC, ROBO])
def test_cloud_motor_expediente_reemplazo_explicito_o_independiente(raiz, cobertura, vinculo, tipo_nuevo):
    viejo, nuevo = JPEG("poliza-vieja"), JPEG("poliza-nueva")
    doc1 = _doc_cloud("origen_viejo", RC, SOLO, "CC5678", viejo)
    doc2 = _doc_cloud("origen_nuevo", tipo_nuevo, SOLO, "CC5678", nuevo)
    if vinculo:
        doc2["reemplaza_documento_id"] = "origen_viejo"
    textos = {viejo: ["POLIZA", "PATENTE CC5678", "VENCE: 30/09/2027", "COBERTURAS: RESPONSABILIDAD CIVIL Y ROBO"],
              nuevo: ["POLIZA", "PATENTE CC5678", "VENCE: 30/09/2028", "COBERTURAS: " + cobertura]}
    assert not _sincronizar(raiz, CloudFalso([doc1]))["errores"]
    extraer(raiz, textos)
    assert not _sincronizar(raiz, CloudFalso([doc2]))["errores"]
    # La recepción sola no retira el documento anterior.
    assert not _vehiculo(raiz, "CC5678")["documentos"][0].get("reemplazado_por")
    extraer(raiz, textos)
    docs = _vehiculo(raiz, "CC5678")["documentos"]
    # Se reemplaza sólo con cobertura completa: por vínculo explícito, o sin él si el tipo leído
    # coincide con el informado (único anterior, vencimiento posterior). Si no, ambos quedan.
    reemplaza = cobertura == "RESPONSABILIDAD CIVIL Y ROBO" and (vinculo or tipo_nuevo == RC)
    assert len(docs) == 2 and docs[0].get("reemplazado_por", "") == (docs[1]["documento_id"] if reemplaza else "")
    assert bool(docs[1].get("posible_reemplazo")) == (not reemplaza)
    assert bool(docs[1].get("vencimiento")) == reemplaza  # el pendiente no tiene vencimiento operativo
    activos = ver(raiz)["documentos"]
    assert len(activos) == (1 if reemplaza else 2)
    faltantes = {a["tipo"] for a in ver(raiz)["ausentes"]}
    assert ROBO not in faltantes and RC not in faltantes  # ninguna cobertura se retira sin evidencia
    assert all((raiz / "fichas_digitales" / "MBT" / d["archivo"]).is_file() for d in docs)
    # Un reintento de Cloud no duplica ni reaplica.
    _sincronizar(raiz, CloudFalso([doc2]))
    assert len(_vehiculo(raiz, "CC5678")["documentos"]) == 2


@pytest.mark.parametrize("origen,cobertura", [("inexistente", "RESPONSABILIDAD CIVIL"),
                                               ("origen_viejo", "RESPONSABILIDAD CIVIL Y ROBO EXCLUIDO")])
def test_vinculo_no_resuelto_o_cobertura_ambigua_no_retira_anterior(raiz, origen, cobertura):
    viejo, nuevo = JPEG("v"), JPEG("n")
    doc1 = _doc_cloud("origen_viejo", RC, SOLO, "CC5678", viejo)
    doc2 = {**_doc_cloud("origen_nuevo", RC, SOLO, "CC5678", nuevo), "reemplaza_documento_id": origen}
    textos = {viejo: ["POLIZA", "PATENTE CC5678", "VENCE: 30/09/2027", "COBERTURA: RESPONSABILIDAD CIVIL"],
              nuevo: ["POLIZA", "PATENTE CC5678", "VENCE: 30/09/2028", "COBERTURA: " + cobertura]}
    _sincronizar(raiz, CloudFalso([doc1])); extraer(raiz, textos)
    _sincronizar(raiz, CloudFalso([doc2])); extraer(raiz, textos)
    assert not _vehiculo(raiz, "CC5678")["documentos"][0].get("reemplazado_por")
    assert len(ver(raiz)["documentos"]) == 2


def test_mismo_original_en_ambos_tipos_no_se_duplica(raiz):
    contenido = JPEG("archivo-unico")
    documentos = [_doc_cloud("origen_rc", RC, SOLO, "CC5678", contenido),
                  _doc_cloud("origen_robo", ROBO, SOLO, "CC5678", contenido)]
    resumen = _sincronizar(raiz, CloudFalso(documentos))
    assert not resumen["errores"] and resumen["vehiculos"][1]["duplicado"]
    docs = _vehiculo(raiz, "CC5678")["documentos"]
    assert len(docs) == 1 and docs[0]["origenes_adicionales"] == ["origen_robo"]
