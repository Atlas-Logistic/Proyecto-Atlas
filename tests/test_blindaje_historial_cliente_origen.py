"""Blindaje explícito de `revalidar_origen_por_historial_de_cliente_sin_ocr`
(capability suite de origen, cierre 2929203): la inferencia por
historial de cliente sólo es válida evidencia fuerte cuando (1) existen
>= 2 observaciones confiables, (2) todas convergen en la misma planta y
(3) no hay evidencia ACTUAL más fuerte que la contradiga -- nunca debe
convertirse en una regla permanente que ignore lo que ESTE documento
trae. Ejercita el entrypoint real (`revalidar_y_regenerar_reporte`),
no la función aislada, para demostrar el flujo completo."""
from __future__ import annotations

import csv
import json

from atlas_core.catalogo_plantas import CatalogoPlantas, EstadoCalidad
from atlas_core.decisiones_pendientes import generar_artefacto
from atlas_core.procesamiento_masivo import COLUMNAS
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
        "cliente": "PRODALAM SA", "obra_destino": "OBRA CLIENTE EJEMPLO",
        "despachar_a_crudo": "CALLE DE UN CLIENTE 500",
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


def _pendientes(actual):
    return json.loads((actual / "decisiones_pendientes.json").read_text(encoding="utf-8"))["decisiones"]


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


def _revalidar(raiz, nombre="reporte"):
    return revalidar_y_regenerar_reporte(
        raiz_atlas=raiz, nombre_carpeta_reporte=nombre, proveedor_rutas=ProveedorRutasSimulado(),
    )


def _historial_colina(n, prefijo="H"):
    return [_fila_csv(
        numero_guia=f"{prefijo}{i}", numero_transporte=f"T{prefijo}{i}", patente_tracto="ZZ0000",
        tipo_carga="BARRAS", descripcion_material="B HORMIGON 12MM 12M A630-420H (N)",
    ) for i in range(n)]


_EMPATE_0_0 = "CONFLICTO_REAL_EN_VENTANA(AZA_COLINA:score=0.0,solape=0.0%;AZA_RENCA:score=0.0,solape=0.0%)"


# ============================================================
# A. 13/13 COLINA, sin evidencia contradictoria -> COLINA
# ============================================================

def test_a_trece_de_trece_colina_sin_contradiccion_resuelve_colina(tmp_path):
    filas = _historial_colina(13)
    filas.append(_fila_csv(
        numero_guia="TARGET", numero_transporte="TTARGET", patente_tracto="VP8521",
        tipo_carga="NO DETERMINADO", motivo_origen_gps=_EMPATE_0_0, origen_gps="ORIGEN_GPS_CONFLICTO",
    ))
    raiz, catalogos, actual, dataset, colina, renca = _entorno(tmp_path, filas)
    _revalidar(raiz)
    fila = _fila_por_guia(dataset, "TARGET")
    assert fila["planta_origen_id"] == colina.planta_id
    assert fila["origen_determinado_por"] == "HISTORIAL_CLIENTE"


# ============================================================
# B. 12 COLINA + 1 RENCA -> historial se abstiene (desacuerdo real)
# ============================================================

def test_b_historial_en_desacuerdo_se_abstiene(tmp_path):
    filas = _historial_colina(12)
    filas.append(_fila_csv(
        numero_guia="DISCREPANTE", numero_transporte="TDISCREPANTE", patente_tracto="YY0000",
        tipo_carga="ANGULOS", descripcion_material="ANGULO 25X25X3MM",
    ))
    filas.append(_fila_csv(
        numero_guia="TARGET", numero_transporte="TTARGET", patente_tracto="VP8521",
        tipo_carga="NO DETERMINADO", motivo_origen_gps=_EMPATE_0_0, origen_gps="ORIGEN_GPS_CONFLICTO",
    ))
    raiz, catalogos, actual, dataset, colina, renca = _entorno(tmp_path, filas)
    _revalidar(raiz)
    fila = _fila_por_guia(dataset, "TARGET")
    assert fila["planta_origen_id"] == ""
    decision = next(
        d for d in _pendientes(actual)
        if (d.get("documento") or {}).get("numero_guia") == "TARGET" and d.get("estado") == "PENDIENTE"
    )
    assert decision["tipo"] == "ORIGEN_NO_CONFIRMADO"


# ============================================================
# C. historial COLINA + material documental determinístico RENCA ->
#    gana la evidencia documental ACTUAL (categoría corre antes)
# ============================================================

def test_c_regla_documental_actual_gana_al_historial_de_cliente(tmp_path):
    filas = _historial_colina(13)
    filas.append(_fila_csv(
        numero_guia="TARGET", numero_transporte="TTARGET", patente_tracto="VP8521",
        tipo_carga="ANGULOS", descripcion_material="ANGULO 25X25X3MM",
        motivo_origen_gps=_EMPATE_0_0, origen_gps="ORIGEN_GPS_CONFLICTO",
    ))
    raiz, catalogos, actual, dataset, colina, renca = _entorno(tmp_path, filas)
    _revalidar(raiz)
    fila = _fila_por_guia(dataset, "TARGET")
    # ESTE documento trae ÁNGULOS -- evidencia documental propia y
    # actual -- nunca el historial (que apuntaría a COLINA por las
    # otras 13 guías, todas de una categoría distinta).
    assert fila["planta_origen_id"] == renca.planta_id
    assert fila["origen_determinado_por"] == "CATEGORIA_DESTINO_EXTERNO"


# ============================================================
# D. historial COLINA + GPS propio físico concluyente RENCA ->
#    gana la evidencia física ACTUAL
# ============================================================

def test_d_evidencia_gps_propia_real_gana_al_historial_de_cliente(tmp_path):
    """Aunque las 13 guías históricas de este cliente sean COLINA, un
    conflicto GPS real y propio de ESTE documento (evidencia física
    directa) nunca se pisa con el historial -- se abstiene, deja la
    ambigüedad para un humano con ambas fuentes disponibles."""
    filas = _historial_colina(13)
    filas.append(_fila_csv(
        numero_guia="TARGET", numero_transporte="TTARGET", patente_tracto="VP8521",
        tipo_carga="NO DETERMINADO",
        motivo_origen_gps="CONFLICTO_REAL_EN_VENTANA(AZA_COLINA:score=0.05,solape=0.5%;AZA_RENCA:score=0.4,solape=38.0%)",
        origen_gps="ORIGEN_GPS_CONFLICTO",
    ))
    raiz, catalogos, actual, dataset, colina, renca = _entorno(tmp_path, filas)
    _revalidar(raiz)
    fila = _fila_por_guia(dataset, "TARGET")
    assert fila["planta_origen_id"] == ""
    assert fila["origen_determinado_por"] != "HISTORIAL_CLIENTE"


# ============================================================
# E. histórico insuficiente (< 2 observaciones) -> abstiene
# ============================================================

def test_e_historial_insuficiente_se_abstiene(tmp_path):
    filas = _historial_colina(1)
    filas.append(_fila_csv(
        numero_guia="TARGET", numero_transporte="TTARGET", patente_tracto="VP8521",
        tipo_carga="NO DETERMINADO", motivo_origen_gps=_EMPATE_0_0, origen_gps="ORIGEN_GPS_CONFLICTO",
    ))
    raiz, catalogos, actual, dataset, colina, renca = _entorno(tmp_path, filas)
    _revalidar(raiz)
    fila = _fila_por_guia(dataset, "TARGET")
    assert fila["planta_origen_id"] == ""
    assert fila["origen_determinado_por"] != "HISTORIAL_CLIENTE"


# ============================================================
# F. el historial no se convierte en una regla permanente de planta
# ============================================================

def test_f_historial_nunca_reinvestiga_un_origen_ya_confirmado_distinto(tmp_path):
    """13 guías históricas del cliente son COLINA, pero ESTA guía ya
    tiene su origen confirmado en RENCA (por cualquier vía, incluida una
    decisión humana) -- el historial nunca la reinvestiga ni la
    "corrige" hacia el patrón mayoritario. El cliente no es una regla
    permanente de planta: cada documento conserva su propia evidencia."""
    filas = _historial_colina(13)
    filas.append(_fila_csv(
        numero_guia="TARGET", numero_transporte="TTARGET", patente_tracto="VP8521",
        tipo_carga="NO DETERMINADO",
    ))
    raiz, catalogos, actual, dataset, colina, renca = _entorno(tmp_path, filas)
    # Fija el origen de TARGET a RENCA por una vía ya confirmada (p. ej.
    # una decisión humana) ANTES de correr la batería.
    filas_reales = _leer_csv(dataset)
    for f in filas_reales:
        if f["numero_guia"] == "TARGET":
            f["planta_origen_id"] = renca.planta_id
            f["planta_origen_nombre"] = "AZA RENCA"
            f["origen_determinado_por"] = "CONFIRMACION_HUMANA"
            f["evidencia_origen"] = "DECISION_HUMANA:x"
    _escribir_csv(dataset, filas_reales)

    _revalidar(raiz)
    fila = _fila_por_guia(dataset, "TARGET")
    assert fila["planta_origen_id"] == renca.planta_id
    assert fila["origen_determinado_por"] == "CONFIRMACION_HUMANA"
