"""Bloque CIERRE PRECEDENCIA ORIGEN (casos reales 472037/472477) --
`revalidar_origen_por_categoria_sin_candidato_sin_ocr` trataba CUALQUIER
GPS `CONFLICTO_REAL_EN_VENTANA` con solape > 0% en algún candidato como
"evidencia física real, nunca se pisa" -- pero un conflicto, POR
DEFINICIÓN, es la propia telemetría diciendo que no pudo decidir entre
sus candidatos; nunca es un origen ya confirmado. Cuando una regla
documental determinística (categoría de carga -> ÚNICA planta
compatible, ya declarada en el catálogo) resuelve a UNA de esas mismas
plantas que el GPS ya venía considerando, esa regla CORROBORA la
ambigüedad -- nunca la contradice -- así que debe poder cerrarla antes
de escalar a un humano. Sólo sigue existiendo una contradicción real
(y por tanto abstención) cuando la categoría apunta a una planta que el
GPS ni siquiera consideró.

Causa raíz: esta precedencia YA EXISTÍA antes de los commits recientes
de cierre de orquestación (045dec9/deed083/15050a9) -- 472037 tenía
`tipo_carga=BARRAS` desde su ingestión original, meses antes de esta
sesión. Lo que esos commits cambiaron fue hacer VISIBLE el resultado
(antes, el origen simplemente quedaba `INCOMPLETO_TECNICO` sin ninguna
tarjeta ni acción posible; ahora `ORIGEN_NO_CONFIRMADO` se publica
correctamente cuando corresponde) -- exponiendo, de paso, esta
precedencia incorrecta que ya vivía en el código. Este cierre corrige
esa precedencia; no es un problema introducido por esos tres commits.

Precedencia final de evidencia para el origen de UN documento:
1. Origen ya persistido (`planta_origen_id`) -- nunca se reinvestiga.
2. Detención GPS real fuera de toda geocerca -- evidencia física
   directa, nunca se pisa.
3. Regla documental determinística (categoría de carga -> única planta
   compatible del catálogo) -- SIEMPRE se evalúa; si resuelve, se
   acepta salvo que contradiga a TODOS los candidatos que un conflicto
   GPS real ya nombró.
4. Patrón de vecinos temporales del mismo vehículo (evidencia más
   débil, inferida de OTROS viajes) -- sólo si la regla documental de
   arriba no pudo resolver.
5. Ambigüedad real persistente (sin regla documental ni vecinos que
   resuelvan) -- decisión humana `ORIGEN_NO_CONFIRMADO`, nunca se
   inventa una planta."""
from __future__ import annotations

import csv
import json

from atlas_core.catalogo_plantas import CatalogoPlantas, EstadoCalidad
from atlas_core.decisiones_pendientes import generar_artefacto
from atlas_core.procesamiento_masivo import COLUMNAS
from atlas_core.revalidacion_documental import (
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
        "cliente": "CLIENTE EJEMPLO SA", "obra_destino": "OBRA CLIENTE EJEMPLO",
        "despachar_a_crudo": "CALLE DE UN CLIENTE 500",
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


def _entorno(tmp_path, **overrides_fila):
    raiz = tmp_path / "Atlas"
    catalogos = raiz / "catalogos_privados"
    actual = raiz / "operacion" / "actual"
    (raiz / "reportes").mkdir(parents=True)
    actual.mkdir(parents=True)
    _catalogos_base(catalogos)
    planta_colina, planta_renca = _plantas(catalogos)
    dataset = actual / "analisis_completo_guias.csv"
    fila = _fila_csv(numero_guia="TARGET", numero_transporte="TTARGET", patente_tracto="VP8521")
    fila.update(overrides_fila)
    _escribir_csv(dataset, [fila])
    generar_artefacto(
        ruta_dataset=dataset, carpeta_catalogos=catalogos, decisiones=[],
        ruta_salida=actual / "decisiones_pendientes.json",
    )
    return raiz, catalogos, actual, dataset, planta_colina, planta_renca


def _revalidar(raiz, nombre):
    return revalidar_y_regenerar_reporte(
        raiz_atlas=raiz, nombre_carpeta_reporte=nombre, proveedor_rutas=ProveedorRutasSimulado(),
    )


_EMPATE_0_0 = "CONFLICTO_REAL_EN_VENTANA(AZA_COLINA:score=0.0,solape=0.0%;AZA_RENCA:score=0.0,solape=0.0%)"
_CONFLICTO_REAL = "CONFLICTO_REAL_EN_VENTANA(AZA_COLINA:score=0.3681,solape=22.4%;AZA_RENCA:score=0.3096,solape=1.1%)"


# =====================================================================
# 1. Cliente + barras de hormigón + GPS 0/0 -> COLINA automático
# =====================================================================

def test_1_barras_hormigon_con_gps_0_0_resuelve_colina_automatico(tmp_path):
    raiz, catalogos, actual, dataset, planta_colina, planta_renca = _entorno(
        tmp_path, tipo_carga="BARRAS", descripcion_material="B HORMIGON 12MM 12M A630-420H (N)",
        motivo_origen_gps=_EMPATE_0_0, origen_gps="ORIGEN_GPS_CONFLICTO",
        estado_ruta="", motivo_ruta="",
    )
    _revalidar(raiz, "reporte_1")

    fila = _fila_por_guia(dataset, "TARGET")
    assert fila["planta_origen_id"] == planta_colina.planta_id
    assert fila["origen_determinado_por"] == "CATEGORIA_DESTINO_EXTERNO"
    assert not any(
        (d.get("documento") or {}).get("numero_guia") == "TARGET" and d.get("tipo") == "ORIGEN_NO_CONFIRMADO"
        for d in _pendientes(actual)
    )


# =====================================================================
# 2. Cliente + barras hormigón + GPS conflictivo real -> regla
#    operacional se evalúa ANTES de escalar a humano
# =====================================================================

def test_2_barras_hormigon_con_gps_conflictivo_real_resuelve_antes_de_preguntar(tmp_path):
    """Caso real 472037: AZA_COLINA con 22.4% de solape (evidencia real,
    no un empate en cero) sigue siendo un CONFLICTO -- nunca un origen
    confirmado. La categoría, ya conocida, corrobora exactamente al
    candidato con más evidencia de los dos."""
    raiz, catalogos, actual, dataset, planta_colina, planta_renca = _entorno(
        tmp_path, tipo_carga="BARRAS", descripcion_material="B HORMIGON 12MM 12M A630-420H (N)",
        motivo_origen_gps=_CONFLICTO_REAL, origen_gps="ORIGEN_GPS_CONFLICTO",
        estado_ruta="ORIGEN_NO_DETERMINADO", motivo_ruta="ORIGEN_GPS_CONFLICTO",
    )
    _revalidar(raiz, "reporte_2")

    fila = _fila_por_guia(dataset, "TARGET")
    assert fila["planta_origen_id"] == planta_colina.planta_id
    assert fila["origen_determinado_por"] == "CATEGORIA_DESTINO_EXTERNO"
    assert not any(
        (d.get("documento") or {}).get("numero_guia") == "TARGET" and d.get("tipo") == "ORIGEN_NO_CONFIRMADO"
        for d in _pendientes(actual)
    )


# =====================================================================
# 3. Cliente + ángulos -> RENCA
# =====================================================================

def test_3_angulos_resuelve_renca(tmp_path):
    raiz, catalogos, actual, dataset, planta_colina, planta_renca = _entorno(
        tmp_path, tipo_carga="ANGULOS", descripcion_material="ANGULO 25X25X3MM",
        motivo_origen_gps=_CONFLICTO_REAL, origen_gps="ORIGEN_GPS_CONFLICTO",
        estado_ruta="ORIGEN_NO_DETERMINADO", motivo_ruta="ORIGEN_GPS_CONFLICTO",
    )
    _revalidar(raiz, "reporte_3")

    fila = _fila_por_guia(dataset, "TARGET")
    assert fila["planta_origen_id"] == planta_renca.planta_id
    assert fila["origen_determinado_por"] == "CATEGORIA_DESTINO_EXTERNO"


# =====================================================================
# 4. Material realmente desconocido + GPS ambiguo -> humano
# =====================================================================

def test_4_material_desconocido_con_gps_ambiguo_escala_a_humano(tmp_path):
    """Caso real 472477: sin categoría determinable, la regla documental
    no tiene nada que evaluar -- la ambigüedad GPS, ya agotadas las
    demás vías, sí debe convertirse en `ORIGEN_NO_CONFIRMADO`."""
    raiz, catalogos, actual, dataset, planta_colina, planta_renca = _entorno(
        tmp_path, tipo_carga="NO DETERMINADO", descripcion_material="",
        motivo_origen_gps=_EMPATE_0_0, origen_gps="ORIGEN_GPS_CONFLICTO",
        estado_ruta="", motivo_ruta="",
    )
    _revalidar(raiz, "reporte_4")

    fila = _fila_por_guia(dataset, "TARGET")
    assert fila["planta_origen_id"] == ""
    decision = next(
        (
            d for d in _pendientes(actual)
            if (d.get("documento") or {}).get("numero_guia") == "TARGET" and d.get("estado") == "PENDIENTE"
        ),
        None,
    )
    assert decision is not None
    assert decision["tipo"] == "ORIGEN_NO_CONFIRMADO"
    assert {c["planta_nombre"] for c in decision["candidatos"]} == {"AZA COLINA", "AZA RENCA"}


# =====================================================================
# 5. La regla documental no puede ser reemplazada por una inferencia débil
# =====================================================================

def test_5_regla_documental_no_es_reemplazada_por_patron_de_vecinos_debil(tmp_path):
    """Si dos vecinos GPS-confirmados del MISMO vehículo convergieran en
    AZA RENCA (un patrón inferido, más débil) pero el material de ESTE
    documento es BARRAS (regla documental, más fuerte, sólo compatible
    con AZA COLINA), la regla documental debe ganar -- nunca depender de
    qué revalidador corrió primero."""
    raiz, catalogos, actual, dataset, planta_colina, planta_renca = _entorno(
        tmp_path, tipo_carga="BARRAS", descripcion_material="B HORMIGON 12MM 12M A630-420H (N)",
        motivo_origen_gps="SIN_EVIDENCIA_GPS", origen_gps="ORIGEN_GPS_NO_DETERMINADO",
        estado_ruta="", motivo_ruta="", fecha="19-08-2026",
    )
    filas = _leer_csv(dataset)
    filas.append(_fila_csv(
        numero_guia="VECINO1", numero_transporte="TV1", fecha="17-08-2026",
        patente_tracto="VP8521", planta_origen_id=planta_renca.planta_id,
        planta_origen_nombre="AZA RENCA", origen_determinado_por="TELEMETRIA_GPS",
    ))
    filas.append(_fila_csv(
        numero_guia="VECINO2", numero_transporte="TV2", fecha="18-08-2026",
        patente_tracto="VP8521", planta_origen_id=planta_renca.planta_id,
        planta_origen_nombre="AZA RENCA", origen_determinado_por="TELEMETRIA_GPS",
    ))
    _escribir_csv(dataset, filas)

    _revalidar(raiz, "reporte_5")

    fila = _fila_por_guia(dataset, "TARGET")
    assert fila["planta_origen_id"] == planta_colina.planta_id
    assert fila["origen_determinado_por"] == "CATEGORIA_DESTINO_EXTERNO"


def test_5b_sin_regla_documental_el_patron_de_vecinos_sigue_funcionando(tmp_path):
    """Regresión negativa -- si la categoría NO puede resolver (material
    desconocido), el patrón de vecinos conserva su función original."""
    raiz, catalogos, actual, dataset, planta_colina, planta_renca = _entorno(
        tmp_path, tipo_carga="NO DETERMINADO", descripcion_material="",
        motivo_origen_gps="SIN_EVIDENCIA_GPS", origen_gps="ORIGEN_GPS_NO_DETERMINADO",
        estado_ruta="", motivo_ruta="", fecha="19-08-2026",
    )
    filas = _leer_csv(dataset)
    filas.append(_fila_csv(
        numero_guia="VECINO1", numero_transporte="TV1", fecha="17-08-2026",
        patente_tracto="VP8521", planta_origen_id=planta_renca.planta_id,
        planta_origen_nombre="AZA RENCA", origen_determinado_por="TELEMETRIA_GPS",
    ))
    filas.append(_fila_csv(
        numero_guia="VECINO2", numero_transporte="TV2", fecha="18-08-2026",
        patente_tracto="VP8521", planta_origen_id=planta_renca.planta_id,
        planta_origen_nombre="AZA RENCA", origen_determinado_por="TELEMETRIA_GPS",
    ))
    _escribir_csv(dataset, filas)

    resultado = revalidar_origen_por_vecinos_temporales_gps_sin_ocr(ruta_dataset=dataset)
    assert "TARGET" in resultado["guias_actualizadas"]
    assert _fila_por_guia(dataset, "TARGET")["planta_origen_id"] == planta_renca.planta_id


# =====================================================================
# 6. No reaparecen revisiones espurias
# =====================================================================

def test_6_no_reaparecen_revisiones_espurias_tras_resolver_por_categoria(tmp_path):
    raiz, catalogos, actual, dataset, planta_colina, planta_renca = _entorno(
        tmp_path, tipo_carga="BARRAS", descripcion_material="B HORMIGON 12MM 12M A630-420H (N)",
        motivo_origen_gps=_CONFLICTO_REAL, origen_gps="ORIGEN_GPS_CONFLICTO",
        estado_ruta="ORIGEN_NO_DETERMINADO", motivo_ruta="ORIGEN_GPS_CONFLICTO",
    )
    _revalidar(raiz, "reporte_6a")
    assert _fila_por_guia(dataset, "TARGET")["planta_origen_id"] == planta_colina.planta_id
    assert not any(
        (d.get("documento") or {}).get("numero_guia") == "TARGET"
        for d in _pendientes(actual) if d.get("estado") == "PENDIENTE"
    )

    dataset_antes = dataset.read_bytes()
    resultado_2 = _revalidar(raiz, "reporte_6b")
    assert resultado_2["guias_actualizadas"] == []
    assert resultado_2["bandeja_cambio_efectivo"] is False
    assert dataset.read_bytes() == dataset_antes
    assert not any(
        (d.get("documento") or {}).get("numero_guia") == "TARGET"
        for d in _pendientes(actual) if d.get("estado") == "PENDIENTE"
    )
