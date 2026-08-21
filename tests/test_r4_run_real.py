import csv
import json
from pathlib import Path

from atlas_core.catalogo_vehiculos import resolver_patente
from atlas_core.procesamiento_masivo import (
    COLUMNAS,
    _corroborar_destino_historico_repetido,
    _corroborar_documentos_relacionados,
    _ejecutar_ia_shadow,
    extraer_descripcion_material,
    extraer_fecha,
    extraer_peso_kg_etiquetado,
)
from atlas_core.atlas_ia.contratos import RESULTADO_HIPOTESIS_ABSTENCION
from atlas_core.atlas_ia.orquestador import OrquestadorAtlasIA
from atlas_core.atlas_ia.proveedor import ProveedorModeloIASimulado, RespuestaSimulada


def test_material_multilinea_estructural_no_termina_ausente():
    textos = [
        "ANGULO 25X25X3MM 6M A270ES (N)",
        "REDONDO LISO 16MM 6M SAE 1020 (N)",
        "PLANA 32X3MM 6M A270ES (N)",
    ]
    assert extraer_descripcion_material(textos) == " | ".join(textos)


def test_material_corrige_confusiones_solo_en_contexto_estructural():
    assert extraer_descripcion_material([
        "D HORMIGON 10MM 6M A630-420H (N)", "3 HORMIGON BMM 6M A630-420H (I)",
    ]) == "B HORMIGON 10MM 6M A630-420H (N) | B HORMIGON 8MM 6M A630-420H (I)"


def test_fecha_emision_con_anio_implausible_cede_ante_doble_consenso_operacional():
    assert extraer_fecha([
        "FECHA DE EMISION 18-08-2024",
        "FECHA SALIDA 18-08-2026",
        "FECHA LLEGADA 18-08-2026",
    ]) == "18-08-2026"


def test_peso_se_recupera_solo_desde_etiqueta_estructural():
    assert extraer_peso_kg_etiquetado(["VALOR TOTAL 9.842.461", "PESO KG.", ": 9.231,00"]) == "9231"
    assert extraer_peso_kg_etiquetado(["ESOKG.", ":9.231,00"]) == "9231"
    assert extraer_peso_kg_etiquetado(["TOTAL 9.231,00"]) == "No encontrado"


def test_patente_ocr_dos_por_be_se_reconcilia_solo_con_candidato_unico():
    catalogo = {"JB8529": {"tipo": "CARRO"}}
    resultado = resolver_patente(catalogo, "J28529", tipo_esperado="CARRO")
    assert (resultado.estado, resultado.valor_resultado) == ("CORRECCION_OCR_SEGURA", "JB8529")


def _fila(**cambios):
    fila = {columna: "" for columna in COLUMNAS}
    fila.update({
        "estado_procesamiento": "OK", "fecha": "18-08-2026",
        "chofer": "PERSONA EJEMPLO", "patente_tracto": "AB1234",
        "obra_destino": "OBRA NORTE", "indicador_revision": "REVISAR",
    })
    fila.update(cambios)
    return fila


def test_documento_relacionado_corroborra_con_senales_fuertes_sin_contaminar_otro_viaje(tmp_path):
    ruta = tmp_path / "datos.csv"
    filas = [
        _fila(archivo="a.jpg", numero_transporte="T1", rut_chofer="12.345.678-5"),
        _fila(archivo="b.jpg", numero_transporte="T2", rut_chofer="No encontrado",
              motivos_revision_documento="CHOFER_SIN_CORROBORAR | OBRA_DESTINO_SIN_CORROBORAR"),
        _fila(archivo="c.jpg", numero_transporte="T3", chofer="OTRA PERSONA", rut_chofer="9.999.999-9"),
    ]
    with ruta.open("w", encoding="utf-8-sig", newline="") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader(); escritor.writerows(filas)
    assert _corroborar_documentos_relacionados(ruta, {"b.jpg"}) == 1
    with ruta.open(encoding="utf-8-sig", newline="") as archivo:
        salida = {f["archivo"]: f for f in csv.DictReader(archivo, delimiter=";")}
    assert salida["b.jpg"]["rut_chofer"] == "12.345.678-5"
    assert "CHOFER_SIN_CORROBORAR" not in salida["b.jpg"]["motivos_revision_documento"]
    assert salida["b.jpg"]["estado_documental"] == "REQUIERE_REVISION"
    evidencia = json.loads(salida["b.jpg"]["evidencia_documentos_relacionados"])
    assert evidencia["archivo_fuente"] == "a.jpg"
    assert salida["c.jpg"]["rut_chofer"] == "9.999.999-9"


def test_historico_repetido_exactamente_corroborado_y_observacion_aislada_no(tmp_path):
    ruta = tmp_path / "destinos_maestros.json"
    ruta.write_text(json.dumps({"destinos": [
        {"destino_id": "d1", "cliente_id": "c1", "nombre_destino": "CALLE UNO 123",
         "estado_vigencia": "ACTIVO", "observacion": "3 viajes en el periodo"},
        {"destino_id": "d2", "cliente_id": "c1", "nombre_destino": "CALLE DOS 456",
         "estado_vigencia": "ACTIVO", "observacion": "1 viaje en el periodo"},
    ]}), encoding="utf-8")
    assert _corroborar_destino_historico_repetido(
        tmp_path, cliente_id="c1", textos=["DESPACHAR A CALLE UNO 123"]
    )["destino_id"] == "d1"
    assert _corroborar_destino_historico_repetido(
        tmp_path, cliente_id="c1", textos=["DESPACHAR A CALLE DOS 456"]
    ) is None


def test_ia_entra_despues_del_motor_y_puede_abstenerse_sin_escribir_dato(tmp_path):
    ruta = tmp_path / "datos.csv"
    filas = [
        _fila(archivo="fuente.jpg", obra_destino="OBRA NORTE", indicador_revision="OK"),
        _fila(archivo="objetivo.jpg", obra_destino="No encontrado",
              motivos_revision_documento="OBRA_DESTINO_SIN_CORROBORAR"),
    ]
    with ruta.open("w", encoding="utf-8-sig", newline="") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader(); escritor.writerows(filas)
    proveedor = ProveedorModeloIASimulado(respuestas_por_valor_documental={
        "No encontrado": RespuestaSimulada(resultado=RESULTADO_HIPOTESIS_ABSTENCION),
    })
    resumen = _ejecutar_ia_shadow(
        ruta, {"objetivo.jpg"}, OrquestadorAtlasIA(proveedor=proveedor)
    )
    with ruta.open(encoding="utf-8-sig", newline="") as archivo:
        salida = {f["archivo"]: f for f in csv.DictReader(archivo, delimiter=";")}
    assert resumen["llamadas"] == 1 and resumen["C"] == 1
    assert salida["objetivo.jpg"]["obra_destino"] == "No encontrado"
    assert json.loads(salida["objetivo.jpg"]["resultado_atlas_ia_json"])[0]["estado"] == "ABSTENCION_IA"
