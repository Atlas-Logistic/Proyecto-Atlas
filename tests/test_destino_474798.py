"""Regresión del intercalado OCR y la evidencia histórica de la guía 474798."""

import csv
import json

from atlas_core.atlas_ia.registro_problemas import recopilar_evidencia_destino
from atlas_core.decisiones_pendientes import (
    detectar_decision_destino_contaminado_documental, regenerar_decisiones_persistidas,
)
from atlas_core.ocr import BloqueOCR
from atlas_core.procesamiento_masivo import COLUMNAS, _revalidar_contaminacion_destino_final
from atlas_core.rutas.destino_entrega import resolver_entrega_documento
from atlas_core.rutas.destino_estructurado import extraer_identificadores_destino


def _bloque(texto, x, y, ancho):
    return BloqueOCR(
        texto=texto,
        bounding_box=((x, y), (x + ancho, y), (x + ancho, y + 18), (x, y + 18)),
        confianza=0.95,
    )


def _bloques_entrega(direccion):
    return [
        _bloque("DESPACHAR A", 55, 1093, 123),
        _bloque(f": {direccion}", 234, 1092, 450),
        _bloque("RETIRA", 730, 1083, 66),
        _bloque("PATENTE", 728, 1103, 88),
        _bloque(": BDFG50", 827, 1103, 85),
        _bloque("RUT CHOFER", 54, 1113, 113),
        _bloque(":18098153-5", 234, 1113, 105),
    ]


def test_474798_recupera_despachar_a_del_original_y_no_usa_direccion_cliente():
    destino = "AV. CAM. LOS TRAPENSES LO BARNECHEA LO BARNE"
    # Orden lineal observado en la relectura del original: el valor de
    # DESPACHAR A aparece antes de su etiqueta y tras ella vienen patente/RUT.
    textos = [
        "DIRECCION", ": VTA AL X MENOR ART F", ": AV KENNEDY 9001",
        "COMUNA", "LAS CONDES", "OBRA DESTINO", ": EMPRESA CONSTRUCTORA BRAVO E",
        f": {destino}", "PATENTE", "DESPACHAR A", ": BDFG50",
        ":18098153-5", "FECHA", "RUT CHOFER",
    ]
    assert extraer_identificadores_destino(textos).despachar_a == "BDFG50 :18098153-5 FECHA"
    resultado = resolver_entrega_documento(textos, [], None, bloques=_bloques_entrega(destino))
    assert resultado["despachar_a_crudo"] == destino
    assert "BDFG50" not in resultado["despachar_a_crudo"]
    assert "AV KENNEDY 9001" not in resultado["despachar_a_crudo"]
    assert "0100" not in resultado["despachar_a_crudo"]


def test_valor_lineal_con_patente_rut_o_etiqueta_activa_geometria():
    destino = "CALLE EJEMPLO 321 PROVIDENCIA"
    for contaminado in ("ABCD12 :12345678-5 FECHA", "RUT CHOFER :12345678-5", "PATENTE : ABCD12"):
        resultado = resolver_entrega_documento(
            ["DESPACHAR A", f": {contaminado}"], [], None,
            bloques=_bloques_entrega(destino),
        )
        assert resultado["despachar_a_crudo"] == destino


def test_historial_de_otra_empresa_no_respalda_destino_de_474798():
    actual = {
        "archivo": "mobile/actual/original.jpg", "numero_transporte": "0000360715",
        "cliente": "EASY RETAIL SA", "obra_destino": "EMPRESA CONSTRUCTORA BRAVO E",
        "despachar_a_crudo": "AV. CAM. LOS TRAPENSES LO BARNECHEA LO BARNE",
        "metodos_recuperacion_documento": "GEOMETRICO",
    }
    historicas = [
        {"archivo": nombre, "cliente": "PRODALAM SA", "obra_destino": actual["obra_destino"],
         "estado_ruta": "RUTA_CALCULADA", "direccion_entrega": "SAN DAMIAN 0100"}
        for nombre in ("464870.jpeg", "mobile/474548/original.jpg")
    ]
    evidencias = recopilar_evidencia_destino(actual, [actual, *historicas])
    assert [e.valor for e in evidencias] == [actual["despachar_a_crudo"]]
    assert evidencias[0].tipo_fuente == "DOCUMENTAL"


def test_historial_de_misma_obra_y_cliente_sigue_disponible():
    actual = {"archivo": "actual.jpeg", "cliente": "CLIENTE SA", "obra_destino": "OBRA UNO"}
    historica = {"archivo": "anterior.jpeg", "cliente": "CLIENTE SA", "obra_destino": "OBRA UNO",
                 "estado_ruta": "RUTA_CALCULADA", "direccion_entrega": "CALLE EJEMPLO 321"}
    evidencias = recopilar_evidencia_destino(actual, [actual, historica])
    assert [(e.valor, e.nivel) for e in evidencias] == [("CALLE EJEMPLO 321", "OBRA_RELACIONADA")]


def test_contaminacion_temprana_se_retira_solo_si_geometria_la_reemplaza():
    motivo = "DESTINO_CONTAMINADO_POR_OTRA_SECCION"
    contaminado = "BDFG50 :18098153-5 FECHA"
    destino = "AV. CAM. LOS TRAPENSES LO BARNECHEA LO BARNE"
    motivos = [motivo]
    _revalidar_contaminacion_destino_final(
        motivos, {"despachar_a_crudo": destino, "direccion_entrega": ""},
        destino_lineal=contaminado,
    )
    assert motivos == []  # la geocodificación aún puede quedar pendiente
    motivos = [motivo]
    _revalidar_contaminacion_destino_final(
        motivos, {"despachar_a_crudo": contaminado, "direccion_entrega": ""},
        destino_lineal=contaminado,
    )
    assert motivos == [motivo]


def test_tarjeta_mixta_obsoleta_no_conserva_destino_leido_anterior(tmp_path):
    catalogos = tmp_path / "catalogos_privados"
    catalogos.mkdir()
    for nombre, contenido in (
        ("clientes.json", {"version_formato": 1, "clientes": []}),
        ("obras_destinos.json", {"version_formato": 1, "obras": [], "relaciones": []}),
        ("destinos_maestros.json", {"version_formato": 1, "destinos": []}),
    ):
        (catalogos / nombre).write_text(json.dumps(contenido), encoding="utf-8")
    archivo = "mobile/actual/original.jpg"
    fila = {columna: "" for columna in COLUMNAS}
    fila.update(archivo=archivo, numero_guia="474798", numero_transporte="0000360715",
                cliente="EASY RETAIL SA", obra_destino="EMPRESA CONSTRUCTORA BRAVO E",
                despachar_a_crudo="AV. CAM. LOS TRAPENSES LO BARNECHEA LO BARNE",
                estado_ruta="REQUIERE_REVISION", motivo_ruta="GEOCODIFICACION_DEMASIADO_GENERICA")
    dataset = tmp_path / "operacion" / "actual" / "analisis_completo_guias.csv"
    dataset.parent.mkdir(parents=True)
    with dataset.open("w", encoding="utf-8-sig", newline="") as flujo:
        escritor = csv.DictWriter(flujo, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader()
        escritor.writerow(fila)
    anterior = dict(fila, despachar_a_crudo="BDFG50 :18098153-5 FECHA",
                    motivos_revision_documento="DESTINO_CONTAMINADO_POR_OTRA_SECCION")
    decision = detectar_decision_destino_contaminado_documental(archivo=archivo, fila=anterior)
    decision["motivos"].append("DESTINO_CONTRADICE_CATALOGO_CONFIRMADO")
    vigentes = regenerar_decisiones_persistidas(
        decisiones=[decision], carpeta_catalogos=catalogos, ruta_dataset=dataset,
    )
    assert all(d.get("valor_documental") != anterior["despachar_a_crudo"] for d in vigentes)
