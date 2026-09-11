"""Bloque CIERRE DE ESTADOS NO TERMINALES (caso real 472477) -- ningún
viaje puede quedar indefinidamente en `REQUIERE_REPROCESAMIENTO` si ya
no existe ninguna operación técnica concreta pendiente: `detectar_
decision_origen_no_confirmado` sólo operaba sobre `estado_ruta==
"ORIGEN_NO_DETERMINADO"`, nunca sobre vacío -- un documento cuyo destino
se resolvió recién (`REGISTRAR_DIRECCION`) nunca llegó a intentar ruta
mientras el destino faltaba, así que `estado_ruta` queda en blanco para
siempre. Tras agotar vecinos GPS, categoría, destino confirmado y
reproceso focal de material (472477: ninguno aporta evidencia nueva),
el conflicto GPS real (dos plantas conocidas, `CONFLICTO_REAL_EN_
VENTANA`) quedaba invisible -- ni acción técnica pendiente NI pregunta
humana.

Contrato final de estados:
- REQUIERE_REPROCESAMIENTO: todavía existe una acción técnica concreta
  pendiente que puede aportar evidencia nueva (p. ej. reproceso focal de
  material con imagen disponible, o un vecino GPS que aún no convergió).
- AMBIGÜEDAD_REAL: las acciones técnicas razonables ya se agotaron --
  corresponde escalar a una decisión humana (`ORIGEN_NO_CONFIRMADO` con
  las alternativas conocidas, nunca inventando una planta)."""
from __future__ import annotations

import csv
import json

from atlas_core.aplicacion_decisiones import aplicar_decision_obra
from atlas_core.catalogo_plantas import CatalogoPlantas, EstadoCalidad
from atlas_core.decisiones_pendientes import generar_artefacto, regenerar_decisiones_persistidas
from atlas_core.procesamiento_masivo import COLUMNAS
from atlas_core.revalidacion_documental import (
    detectar_decisiones_origen_sin_ocr,
    revalidar_origen_por_categoria_sin_candidato_sin_ocr,
    revalidar_origen_por_vecinos_temporales_gps_sin_ocr,
    revalidar_y_regenerar_reporte,
)
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


def _plantas(catalogos, *, categorias_colina=(), categorias_renca=()):
    planta_colina = CatalogoPlantas(catalogos / "plantas.json").crear(
        nombre="AZA COLINA", pais="CHILE", fuente="TEST",
        direccion="RUTA 5", comuna="COLINA", region="RM",
        latitud=COORD_AZA_COLINA.latitud, longitud=COORD_AZA_COLINA.longitud,
        estado_calidad=EstadoCalidad.CONFIRMADA, categorias_permitidas=categorias_colina,
    )
    planta_renca = CatalogoPlantas(catalogos / "plantas.json").crear(
        nombre="AZA RENCA", pais="CHILE", fuente="TEST",
        direccion="LA UNION 3070", comuna="RENCA", region="RM",
        latitud=COORD_AZA_RENCA.latitud, longitud=COORD_AZA_RENCA.longitud,
        estado_calidad=EstadoCalidad.CONFIRMADA, categorias_permitidas=categorias_renca,
    )
    return planta_colina, planta_renca


def _pendientes(actual):
    return json.loads((actual / "decisiones_pendientes.json").read_text(encoding="utf-8"))["decisiones"]


_MOTIVO_EMPATE_SIN_EVIDENCIA = (
    "CONFLICTO_REAL_EN_VENTANA(AZA_COLINA:score=0.0,solape=0.0%;AZA_RENCA:score=0.0,solape=0.0%)"
)


# =====================================================================
# 1. Acción técnica disponible -> permanece técnico, no pregunta todavía
# =====================================================================

def test_1_con_accion_tecnica_disponible_no_pregunta_todavia(tmp_path):
    """Vecinos GPS del mismo vehículo SÍ convergen -- todavía existe una
    acción técnica concreta (el propio patrón de vecinos) capaz de
    resolver el origen solo. Mientras esa vía no se agote, no debe
    generarse ninguna pregunta humana."""
    raiz = tmp_path / "Atlas"
    catalogos = raiz / "catalogos_privados"
    actual = raiz / "operacion" / "actual"
    actual.mkdir(parents=True)
    _catalogos_base(catalogos)
    planta_colina, _ = _plantas(catalogos)
    dataset = actual / "analisis_completo_guias.csv"
    _escribir_csv(dataset, [
        _fila_csv(
            numero_guia="VECINO1", numero_transporte="TV1", fecha="17-08-2026",
            patente_tracto="AL1879", planta_origen_id=planta_colina.planta_id,
            planta_origen_nombre="AZA COLINA", origen_determinado_por="TELEMETRIA_GPS",
        ),
        _fila_csv(
            numero_guia="VECINO2", numero_transporte="TV2", fecha="18-08-2026",
            patente_tracto="AL1879", planta_origen_id=planta_colina.planta_id,
            planta_origen_nombre="AZA COLINA", origen_determinado_por="TELEMETRIA_GPS",
        ),
        _fila_csv(
            numero_guia="TARGET", numero_transporte="TTARGET", fecha="19-08-2026",
            patente_tracto="AL1879", planta_origen_id="", planta_origen_nombre="",
            origen_determinado_por="", motivo_origen_gps="SIN_EVIDENCIA_GPS",
            estado_ruta="", motivo_ruta="",
        ),
    ])
    # ANTES de que la vía técnica corra: sin evidencia propia real y sin
    # origen todavía -- tampoco hay nada fundado que preguntar (SIN_
    # EVIDENCIA_GPS no ofrece candidato razonable).
    candidatas_antes = detectar_decisiones_origen_sin_ocr(raiz_atlas=raiz)
    assert candidatas_antes == []

    resultado = revalidar_origen_por_vecinos_temporales_gps_sin_ocr(ruta_dataset=dataset)
    assert resultado["guias_actualizadas"] == ["TARGET"]
    assert _fila_por_guia(dataset, "TARGET")["planta_origen_id"] == planta_colina.planta_id

    # DESPUÉS: el origen ya se resolvió solo -- sigue sin pregunta humana.
    candidatas_despues = detectar_decisiones_origen_sin_ocr(raiz_atlas=raiz)
    assert candidatas_despues == []


# =====================================================================
# 2. Acciones agotadas + ambigüedad real -> decisión humana
# =====================================================================

def _entorno_472477(tmp_path):
    raiz = tmp_path / "Atlas"
    catalogos = raiz / "catalogos_privados"
    actual = raiz / "operacion" / "actual"
    (raiz / "reportes").mkdir(parents=True)
    actual.mkdir(parents=True)
    _catalogos_base(catalogos)
    planta_colina, planta_renca = _plantas(catalogos)
    dataset = actual / "analisis_completo_guias.csv"
    _escribir_csv(dataset, [
        _fila_csv(
            numero_guia="TARGET", numero_transporte="TTARGET", fecha="24-08-2026",
            patente_tracto="VP8521", planta_origen_id="", planta_origen_nombre="",
            origen_determinado_por="", motivo_origen_gps=_MOTIVO_EMPATE_SIN_EVIDENCIA,
            origen_gps="ORIGEN_GPS_CONFLICTO",
            estado_ruta="", motivo_ruta="",
            despachar_a_crudo="PASAJE ISRAEL 1303", direccion_entrega="PASAJE ISRAEL 1303",
            localidad_entrega="CHILLAN",
            tipo_carga="NO DETERMINADO", descripcion_material="",
        ),
    ])
    return raiz, catalogos, actual, dataset, planta_colina, planta_renca


def test_2_agotadas_las_vias_automaticas_genera_decision_humana(tmp_path):
    """Caso real 472477: sin vecinos GPS, sin categoría determinable
    (material sigue ausente), destino ya resuelto -- el único origen que
    queda es un conflicto GPS real entre dos plantas conocidas, sin
    evidencia positiva para ninguna. Contrato (A): las alternativas se
    acotan a plantas conocidas -> `ORIGEN_NO_CONFIRMADO` con esas dos,
    nunca una planta forzada."""
    raiz, catalogos, actual, dataset, planta_colina, planta_renca = _entorno_472477(tmp_path)
    generar_artefacto(
        ruta_dataset=dataset, carpeta_catalogos=catalogos, decisiones=[],
        ruta_salida=actual / "decisiones_pendientes.json",
    )
    resultado = revalidar_y_regenerar_reporte(raiz_atlas=raiz, nombre_carpeta_reporte="reporte_472477", proveedor_rutas=ProveedorRutasSimulado())

    # Ninguna vía automática resolvió -- Atlas no fuerza ninguna planta.
    assert _fila_por_guia(dataset, "TARGET")["planta_origen_id"] == ""

    pendientes = _pendientes(actual)
    decision = next(
        (
            d for d in pendientes
            if (d.get("documento") or {}).get("numero_guia") == "TARGET" and d.get("estado") == "PENDIENTE"
        ),
        None,
    )
    assert decision is not None, "472477 debía escalar a ORIGEN_NO_CONFIRMADO tras agotar evidencia"
    assert decision["tipo"] == "ORIGEN_NO_CONFIRMADO"
    nombres = {c["planta_nombre"] for c in decision["candidatos"]}
    assert nombres == {"AZA COLINA", "AZA RENCA"}


# =====================================================================
# 3. Evidencia automática posterior resuelve -> no preguntar
# =====================================================================

def test_3_evidencia_automatica_posterior_resuelve_sin_preguntar(tmp_path):
    """Mismo escenario, pero la categoría del material SÍ se conoce
    (llegó por otra vía -- p. ej. reproceso focal) y resuelve de forma
    única -- nunca debe generarse la pregunta de origen."""
    raiz, catalogos, actual, dataset, planta_colina, planta_renca = _entorno_472477(tmp_path)
    # AZA COLINA es la única compatible con BARRAS -- la categoría, una
    # vez conocida, resuelve por sí sola.
    CatalogoPlantas(catalogos / "plantas.json").editar(
        planta_colina.planta_id, categorias_permitidas=["BARRAS"], modificacion_manual=True,
    )
    filas = _leer_csv(dataset)
    for fila in filas:
        if fila["numero_guia"] == "TARGET":
            fila["tipo_carga"] = "BARRAS"
            fila["descripcion_material"] = "B HORMIGON 25MM 12M A630-420H (N)"
    _escribir_csv(dataset, filas)
    generar_artefacto(
        ruta_dataset=dataset, carpeta_catalogos=catalogos, decisiones=[],
        ruta_salida=actual / "decisiones_pendientes.json",
    )
    resultado = revalidar_y_regenerar_reporte(raiz_atlas=raiz, nombre_carpeta_reporte="reporte_472477_resuelto", proveedor_rutas=ProveedorRutasSimulado())

    fila_final = _fila_por_guia(dataset, "TARGET")
    assert fila_final["planta_origen_id"] == planta_colina.planta_id

    pendientes = _pendientes(actual)
    # Sin candidato de origen: la categoría, ya conocida, resolvió sola.
    # (El destino de esta fila sintética no geocodifica contra el
    # proveedor real por defecto -- irrelevante para lo que este test
    # verifica, que es específicamente la pregunta de ORIGEN.)
    assert not any(
        (d.get("documento") or {}).get("numero_guia") == "TARGET"
        and d.get("estado") == "PENDIENTE" and d.get("tipo") == "ORIGEN_NO_CONFIRMADO"
        for d in pendientes
    )


# =====================================================================
# 4. Decisión respondida -> no reaparece
# =====================================================================

def test_4_decision_respondida_no_reaparece(tmp_path):
    raiz, catalogos, actual, dataset, planta_colina, planta_renca = _entorno_472477(tmp_path)
    generar_artefacto(
        ruta_dataset=dataset, carpeta_catalogos=catalogos, decisiones=[],
        ruta_salida=actual / "decisiones_pendientes.json",
    )
    revalidar_y_regenerar_reporte(raiz_atlas=raiz, nombre_carpeta_reporte="reporte_472477_previo", proveedor_rutas=ProveedorRutasSimulado())
    decision = next(
        d for d in _pendientes(actual)
        if (d.get("documento") or {}).get("numero_guia") == "TARGET" and d.get("estado") == "PENDIENTE"
    )

    resultado = aplicar_decision_obra(
        raiz_atlas=raiz, decision_id=decision["decision_id"], accion="SELECCIONAR_OTRA_PLANTA",
        planta_id_elegida=planta_colina.planta_id,
    )
    assert resultado["ok"] is True
    assert _fila_por_guia(dataset, "TARGET")["planta_origen_id"] != ""

    # Aunque el motivo_origen_gps original (el mismo empate) siga
    # persistido en la fila, la decisión ya respondida nunca reaparece.
    pendientes_despues = _pendientes(actual)
    assert not any(
        (d.get("documento") or {}).get("numero_guia") == "TARGET" and d.get("estado") == "PENDIENTE"
        for d in pendientes_despues
    )


# =====================================================================
# 5. Idempotencia
# =====================================================================

def test_5_idempotencia(tmp_path):
    raiz, catalogos, actual, dataset, planta_colina, planta_renca = _entorno_472477(tmp_path)
    generar_artefacto(
        ruta_dataset=dataset, carpeta_catalogos=catalogos, decisiones=[],
        ruta_salida=actual / "decisiones_pendientes.json",
    )
    revalidar_y_regenerar_reporte(raiz_atlas=raiz, nombre_carpeta_reporte="reporte_472477_primera", proveedor_rutas=ProveedorRutasSimulado())
    dataset_antes = dataset.read_bytes()
    decisiones_antes = _pendientes(actual)

    resultado_segunda = revalidar_y_regenerar_reporte(raiz_atlas=raiz, nombre_carpeta_reporte="reporte_472477_segunda", proveedor_rutas=ProveedorRutasSimulado())
    assert resultado_segunda["guias_actualizadas"] == []
    assert resultado_segunda["bandeja_cambio_efectivo"] is False
    assert dataset.read_bytes() == dataset_antes
    assert _pendientes(actual) == decisiones_antes
    assert not (raiz / "reportes" / "reporte_472477_segunda").exists()
