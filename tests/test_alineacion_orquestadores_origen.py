"""Bloque CIERRE MAPA DE CAPACIDADES DE ORIGEN -- prueba explícita del
PRINCIPIO de alineación: "un viaje no debe obtener distinto origen
únicamente por la puerta de entrada". Ejercita los DOS entrypoints
reales de producción -- `revalidar_y_regenerar_reporte` (decisión
humana aplicada / envío Mobile) y `reconciliar_estado_derivado` (carga
automática de Desktop) -- sobre el MISMO dataset congelado, y confirma
que ambos llegan al mismo origen resuelto para los mismos casos reales
(472037: categoría; 472477: historial de cliente)."""
from __future__ import annotations

import csv
import json

from atlas_core.catalogo_plantas import CatalogoPlantas, EstadoCalidad
from atlas_core.decisiones_pendientes import generar_artefacto
from atlas_core.procesamiento_masivo import COLUMNAS
from atlas_core.reconciliacion_estado_derivado import reconciliar_estado_derivado
from atlas_core.revalidacion_documental import revalidar_y_regenerar_reporte
from atlas_core.rutas.modelos import Coordenadas
from atlas_core.rutas.proveedor import ProveedorRutasSimulado

COORD_AZA_COLINA = Coordenadas(-70.665977, -33.137558)
COORD_AZA_RENCA = Coordenadas(-70.685226, -33.401595)


def _fila_csv(**overrides):
    fila = {c: "" for c in COLUMNAS}
    fila.update({
        "archivo": "9999999.jpeg", "estado_procesamiento": "OK",
        "chofer": "CHOFER TEST", "indicador_revision": "OK",
        "estado_documental": "OK", "estado_operacional": "REQUIERE_REVISION",
        "fecha": "19-08-2026",
    })
    fila.update(overrides)
    return fila


def _escribir_csv(ruta, filas):
    with ruta.open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader()
        escritor.writerows(filas)


def _leer_csv(ruta):
    with ruta.open("r", newline="", encoding="utf-8-sig") as archivo:
        return list(csv.DictReader(archivo, delimiter=";"))


def _fila_por_guia(ruta, numero_guia):
    return next(f for f in _leer_csv(ruta) if f["numero_guia"] == numero_guia)


def _catalogos_base(catalogos):
    catalogos.mkdir(parents=True, exist_ok=True)
    for nombre, contenido in {
        "clientes.json": {"version_formato": 1, "clientes": []}, "empresas.json": {}, "vehiculos.json": {},
        "obras_destinos.json": {"version_formato": 1, "obras": [], "relaciones": []},
        "destinos_maestros.json": {"version_formato": 1, "destinos": []},
    }.items():
        (catalogos / nombre).write_text(json.dumps(contenido), encoding="utf-8")


def _plantas(catalogos):
    planta_colina = CatalogoPlantas(catalogos / "plantas.json").crear(
        nombre="AZA COLINA", pais="CHILE", fuente="TEST",
        direccion="RUTA 5", comuna="COLINA", region="RM",
        latitud=COORD_AZA_COLINA.latitud, longitud=COORD_AZA_COLINA.longitud,
        estado_calidad=EstadoCalidad.CONFIRMADA, categorias_permitidas=["BARRAS", "ROLLOS"],
    )
    planta_renca = CatalogoPlantas(catalogos / "plantas.json").crear(
        nombre="AZA RENCA", pais="CHILE", fuente="TEST",
        direccion="LA UNION 3070", comuna="RENCA", region="RM",
        latitud=COORD_AZA_RENCA.latitud, longitud=COORD_AZA_RENCA.longitud,
        estado_calidad=EstadoCalidad.CONFIRMADA, categorias_permitidas=["ANGULOS"],
    )
    return planta_colina, planta_renca


def _entorno(tmp_path, filas):
    raiz = tmp_path / "Atlas"
    catalogos = raiz / "catalogos_privados"
    actual = raiz / "operacion" / "actual"
    (raiz / "reportes").mkdir(parents=True)
    actual.mkdir(parents=True)
    _catalogos_base(catalogos)
    planta_colina, planta_renca = _plantas(catalogos)
    dataset = actual / "analisis_completo_guias.csv"
    _escribir_csv(dataset, filas)
    generar_artefacto(
        ruta_dataset=dataset, carpeta_catalogos=catalogos, decisiones=[],
        ruta_salida=actual / "decisiones_pendientes.json",
    )
    return raiz, catalogos, actual, dataset, planta_colina, planta_renca


def _historial_colina(cliente, n):
    return [_fila_csv(
        numero_guia=f"H{i}", numero_transporte=f"TH{i}", patente_tracto="ZZ0000",
        cliente=cliente, obra_destino="OBRA CUALQUIERA",
        tipo_carga="BARRAS", descripcion_material="B HORMIGON 12MM 12M A630-420H (N)",
    ) for i in range(13)]


_EMPATE_0_0 = "CONFLICTO_REAL_EN_VENTANA(AZA_COLINA:score=0.0,solape=0.0%;AZA_RENCA:score=0.0,solape=0.0%)"
_CONFLICTO_REAL = "CONFLICTO_REAL_EN_VENTANA(AZA_COLINA:score=0.3681,solape=22.4%;AZA_RENCA:score=0.3096,solape=1.1%)"


def _filas_caso(cliente):
    filas = _historial_colina(cliente, 13)
    filas.append(_fila_csv(  # estilo 472037: categoría conocida + GPS conflictivo real
        numero_guia="CATEGORIA", numero_transporte="TCATEGORIA", patente_tracto="AA1111",
        cliente="OTRO CLIENTE SA", obra_destino="OBRA OTRO CLIENTE",
        tipo_carga="BARRAS", descripcion_material="B HORMIGON 12MM 12M A630-420H (N)",
        motivo_origen_gps=_CONFLICTO_REAL, origen_gps="ORIGEN_GPS_CONFLICTO",
        estado_ruta="ORIGEN_NO_DETERMINADO", motivo_ruta="ORIGEN_GPS_CONFLICTO",
    ))
    filas.append(_fila_csv(  # estilo 472477: material desconocido + historial de cliente
        numero_guia="HISTORIAL", numero_transporte="THISTORIAL", patente_tracto="VP8521",
        cliente=cliente, obra_destino="OBRA NUEVA",
        tipo_carga="NO DETERMINADO", motivo_origen_gps=_EMPATE_0_0, origen_gps="ORIGEN_GPS_CONFLICTO",
        despachar_a_crudo="PASAJE ISRAEL 1303",
    ))
    return filas


def test_ambos_entrypoints_resuelven_el_mismo_origen(tmp_path):
    cliente = "PRODALAM SA"
    raiz_a = tmp_path / "via_decision"
    raiz_a.mkdir()
    raiz_a, catalogos_a, actual_a, dataset_a, colina_a, renca_a = _entorno(raiz_a, _filas_caso(cliente))
    revalidar_y_regenerar_reporte(
        raiz_atlas=raiz_a, nombre_carpeta_reporte="reporte_via_decision",
        proveedor_rutas=ProveedorRutasSimulado(),
    )

    raiz_b = tmp_path / "via_desktop"
    raiz_b.mkdir()
    raiz_b, catalogos_b, actual_b, dataset_b, colina_b, renca_b = _entorno(raiz_b, _filas_caso(cliente))
    resultado_desktop = reconciliar_estado_derivado(
        raiz_atlas=raiz_b, proveedor_rutas=ProveedorRutasSimulado(),
    )
    assert resultado_desktop["reconciliado"] is True

    fila_categoria_a = _fila_por_guia(dataset_a, "CATEGORIA")
    fila_categoria_b = _fila_por_guia(dataset_b, "CATEGORIA")
    assert fila_categoria_a["planta_origen_nombre"] == fila_categoria_b["planta_origen_nombre"] == "AZA COLINA"

    fila_historial_a = _fila_por_guia(dataset_a, "HISTORIAL")
    fila_historial_b = _fila_por_guia(dataset_b, "HISTORIAL")
    assert fila_historial_a["planta_origen_nombre"] == fila_historial_b["planta_origen_nombre"] == "AZA COLINA"
    assert fila_historial_a["origen_determinado_por"] == fila_historial_b["origen_determinado_por"] == "HISTORIAL_CLIENTE"
