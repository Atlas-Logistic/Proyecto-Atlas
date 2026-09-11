"""CAPABILITY SUITE DE ORIGEN -- suite determinista e independiente del
dataset vivo que protege, en un solo lugar, TODAS las capacidades de
resolución de origen ya ganadas por Atlas (inspirada en problemas
reales -- 472037/472477/464730/464981/464367 -- pero con fixtures
congelados, nunca datos vivos de G:\\).

Precedencia de evidencia que esta suite protege (derivada del código,
ver informe del cierre):
1. Origen ya persistido -- nunca se reinvestiga (L).
2. Documento hermano del MISMO transporte ya resuelto -- es
   literalmente el mismo viaje físico, la evidencia más fuerte posible
   (G).
3. Detención GPS real fuera de toda geocerca / conflicto GPS con
   evidencia física real -- nunca se pisa con una inferencia más débil
   (F, I).
4. Regla documental determinística (categoría de carga -> única planta
   compatible, declarada en catálogo) -- se evalúa SIEMPRE que hay
   categoría; gana salvo que contradiga a TODOS los candidatos que un
   conflicto GPS real ya nombró (A, B, D, E, J).
5. Patrón de vecinos temporales del mismo vehículo (evidencia física,
   pero inferida de OTROS viajes, con ventana de días) -- sólo si la
   regla documental no resolvió.
6. Historial de convergencia ABSOLUTA del mismo cliente (evidencia de
   negocio, sin ventana temporal) -- última vía automática, sólo si
   nada de lo anterior resolvió (J).
7. Ambigüedad real persistente -- `ORIGEN_NO_CONFIRMADO`, nunca se
   inventa una planta (K, M)."""
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
        "cliente": "CLIENTE EJEMPLO SA", "obra_destino": "OBRA CLIENTE EJEMPLO",
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


def _entorno(tmp_path, filas_o_funcion):
    """`filas_o_funcion` es una lista de filas YA armada, o un callable
    `(planta_colina, planta_renca) -> list[fila]` para cuando las filas
    necesitan referenciar el `planta_id` real de alguna planta (los
    catálogos se crean ANTES de construir las filas en ese caso)."""
    raiz = tmp_path / "Atlas"
    catalogos = raiz / "catalogos_privados"
    actual = raiz / "operacion" / "actual"
    (raiz / "reportes").mkdir(parents=True)
    actual.mkdir(parents=True)
    _catalogos_base(catalogos)
    planta_colina, planta_renca = _plantas(catalogos)
    filas = filas_o_funcion(planta_colina, planta_renca) if callable(filas_o_funcion) else filas_o_funcion
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


def _sin_decision_origen(actual, numero_guia):
    return not any(
        (d.get("documento") or {}).get("numero_guia") == numero_guia and d.get("tipo") == "ORIGEN_NO_CONFIRMADO"
        for d in _pendientes(actual) if d.get("estado") == "PENDIENTE"
    )


_EMPATE_0_0 = "CONFLICTO_REAL_EN_VENTANA(AZA_COLINA:score=0.0,solape=0.0%;AZA_RENCA:score=0.0,solape=0.0%)"
_CONFLICTO_REAL = "CONFLICTO_REAL_EN_VENTANA(AZA_COLINA:score=0.3681,solape=22.4%;AZA_RENCA:score=0.3096,solape=1.1%)"


# ============================================================
# A. cliente + barras/hormigón -> COLINA
# ============================================================

def test_a_barras_hormigon_resuelve_colina(tmp_path):
    raiz, catalogos, actual, dataset, colina, renca = _entorno(tmp_path, [_fila_csv(
        numero_guia="1", numero_transporte="T1", patente_tracto="AA1111",
        tipo_carga="BARRAS", descripcion_material="B HORMIGON 12MM 12M A630-420H (N)",
    )])
    _revalidar(raiz)
    assert _fila_por_guia(dataset, "1")["planta_origen_id"] == colina.planta_id


# ============================================================
# B. cliente + familia exclusiva Renca -> RENCA
# ============================================================

def test_b_angulos_resuelve_renca(tmp_path):
    raiz, catalogos, actual, dataset, colina, renca = _entorno(tmp_path, [_fila_csv(
        numero_guia="1", numero_transporte="T1", patente_tracto="AA1111",
        tipo_carga="ANGULOS", descripcion_material="ANGULO 25X25X3MM",
    )])
    _revalidar(raiz)
    assert _fila_por_guia(dataset, "1")["planta_origen_id"] == renca.planta_id


# ============================================================
# C. GPS concluyente compatible con regla documental -> nada que hacer
# ============================================================

def test_c_gps_ya_confirmado_compatible_con_categoria_no_se_toca(tmp_path):
    raiz, catalogos, actual, dataset, colina, renca = _entorno(tmp_path, lambda colina, renca: [_fila_csv(
        numero_guia="1", numero_transporte="T1", patente_tracto="AA1111",
        tipo_carga="BARRAS", descripcion_material="B HORMIGON 12MM 12M A630-420H (N)",
        planta_origen_id=colina.planta_id, planta_origen_nombre="AZA COLINA",
        origen_determinado_por="TELEMETRIA_GPS", evidencia_origen="ORIGINAL",
        estado_ruta="RUTA_CALCULADA", distancia_km="10", duracion_min="15",
    )])
    resultado = _revalidar(raiz)
    fila = _fila_por_guia(dataset, "1")
    assert fila["planta_origen_id"] == colina.planta_id
    assert fila["origen_determinado_por"] == "TELEMETRIA_GPS"
    assert fila["evidencia_origen"] == "ORIGINAL"


# ============================================================
# D. GPS conflictivo real + regla documental determinística -> resuelve
# ============================================================

def test_d_gps_conflictivo_real_con_regla_documental_resuelve(tmp_path):
    """Caso real 472037."""
    raiz, catalogos, actual, dataset, colina, renca = _entorno(tmp_path, [_fila_csv(
        numero_guia="1", numero_transporte="T1", patente_tracto="AA1111",
        tipo_carga="BARRAS", descripcion_material="B HORMIGON 12MM 12M A630-420H (N)",
        motivo_origen_gps=_CONFLICTO_REAL, origen_gps="ORIGEN_GPS_CONFLICTO",
        estado_ruta="ORIGEN_NO_DETERMINADO", motivo_ruta="ORIGEN_GPS_CONFLICTO",
    )])
    _revalidar(raiz)
    fila = _fila_por_guia(dataset, "1")
    assert fila["planta_origen_id"] == colina.planta_id
    assert fila["origen_determinado_por"] == "CATEGORIA_DESTINO_EXTERNO"
    assert _sin_decision_origen(actual, "1")


# ============================================================
# E. GPS 0/0 + regla documental determinística -> resuelve
# ============================================================

def test_e_gps_empate_en_cero_con_regla_documental_resuelve(tmp_path):
    raiz, catalogos, actual, dataset, colina, renca = _entorno(tmp_path, [_fila_csv(
        numero_guia="1", numero_transporte="T1", patente_tracto="AA1111",
        tipo_carga="BARRAS", descripcion_material="B HORMIGON 12MM 12M A630-420H (N)",
        motivo_origen_gps=_EMPATE_0_0, origen_gps="ORIGEN_GPS_CONFLICTO",
    )])
    _revalidar(raiz)
    fila = _fila_por_guia(dataset, "1")
    assert fila["planta_origen_id"] == colina.planta_id
    assert _sin_decision_origen(actual, "1")


# ============================================================
# F. evidencia física directa contradice regla débil -> no pisar GPS real
# ============================================================

def test_f_deteccion_real_fuera_de_geocerca_nunca_se_pisa_por_historial(tmp_path):
    """Aunque el historial de este cliente converja de forma absoluta en
    AZA COLINA, una detención GPS real fuera de toda geocerca (evidencia
    física DIRECTA de ESTE documento) nunca se pisa con una inferencia
    de negocio -- se abstiene, la ambigüedad queda para un humano con
    ambas fuentes disponibles."""
    filas = [_fila_csv(
        numero_guia=str(n), numero_transporte=f"T{n}", patente_tracto="AA1111",
        cliente="CLIENTE HISTORIAL SA", tipo_carga="NO DETERMINADO",
        planta_origen_id="COLINA_ID_PLACEHOLDER", planta_origen_nombre="AZA COLINA",
        origen_determinado_por="TELEMETRIA_GPS",
    ) for n in range(1, 3)]
    filas.append(_fila_csv(
        numero_guia="TARGET", numero_transporte="TTARGET", patente_tracto="BB2222",
        cliente="CLIENTE HISTORIAL SA", tipo_carga="NO DETERMINADO",
        motivo_origen_gps="DETENCION_REAL_FUERA_DE_TODA_GEOCERCA(duracion=25min)",
        latitud_estadia_gps="-33.40", longitud_estadia_gps="-70.68",
        duracion_estadia_gps_min="25",
    ))
    raiz, catalogos, actual, dataset, colina, renca = _entorno(tmp_path, filas)
    # Corrige el placeholder de los vecinos por el id real de la planta.
    filas_reales = _leer_csv(dataset)
    for f in filas_reales:
        if f["planta_origen_id"] == "COLINA_ID_PLACEHOLDER":
            f["planta_origen_id"] = colina.planta_id
    _escribir_csv(dataset, filas_reales)

    _revalidar(raiz)
    fila = _fila_por_guia(dataset, "TARGET")
    assert fila["planta_origen_id"] == ""


# ============================================================
# G. mismo transporte / documentos vecinos
# ============================================================

def test_g_documento_hermano_del_mismo_transporte_ya_resuelto(tmp_path):
    """Caso real 0000354651 (472276/472277): dos guías del MISMO
    transporte son, físicamente, el mismo viaje -- si una ya resolvió
    origen (por cualquier vía confiable) y la otra no trae ninguna
    evidencia propia, comparte el mismo origen."""
    raiz, catalogos, actual, dataset, colina, renca = _entorno(tmp_path, [
        _fila_csv(
            numero_guia="1", numero_transporte="T-COMPARTIDO", patente_tracto="AA1111",
            tipo_carga="BARRAS", descripcion_material="B HORMIGON 12MM 12M A630-420H (N)",
        ),
        _fila_csv(
            numero_guia="2", numero_transporte="T-COMPARTIDO", patente_tracto="AA1111",
            tipo_carga="NO DETERMINADO", descripcion_material="",
        ),
    ])
    _revalidar(raiz)
    fila_1 = _fila_por_guia(dataset, "1")
    fila_2 = _fila_por_guia(dataset, "2")
    assert fila_1["planta_origen_id"] == colina.planta_id
    assert fila_2["planta_origen_id"] == colina.planta_id
    assert fila_2["origen_determinado_por"] == "DOCUMENTO_HERMANO_MISMO_TRANSPORTE"


# ============================================================
# H. correlatividad de números de guía
# ============================================================

def test_h_correlatividad_de_guias_nunca_se_usa_como_evidencia_de_origen(tmp_path):
    """Dos guías numéricamente correlativas (471000/471001) de un MISMO
    cliente/transporte distinto no deben resolverse por "cercanía de
    número" -- Atlas no tiene ninguna regla de origen basada en
    correlatividad de folios (el número de guía es un correlativo del
    emisor, sin relación con qué planta despachó); la correlatividad
    numérica NUNCA debe fabricar una convergencia que no existe.
    Confirma que la ausencia de esa "capacidad" es intencional: sin
    categoría, sin historial de cliente suficiente y sin hermano de
    transporte, la guía correlativa por sí sola no resuelve nada."""
    raiz, catalogos, actual, dataset, colina, renca = _entorno(tmp_path, [
        _fila_csv(
            numero_guia="471000", numero_transporte="T-A", patente_tracto="AA1111",
            cliente="CLIENTE UNICO SA", tipo_carga="BARRAS",
            descripcion_material="B HORMIGON 12MM 12M A630-420H (N)",
        ),
        _fila_csv(
            numero_guia="471001", numero_transporte="T-B", patente_tracto="ZZ9999",
            cliente="OTRO CLIENTE DISTINTO SA", tipo_carga="NO DETERMINADO",
        ),
    ])
    _revalidar(raiz)
    assert _fila_por_guia(dataset, "471000")["planta_origen_id"] == colina.planta_id
    # La correlatividad del folio (471001 sigue a 471000) es irrelevante:
    # cliente y transporte distintos -- sigue, honestamente, sin origen.
    assert _fila_por_guia(dataset, "471001")["planta_origen_id"] == ""


# ============================================================
# I. evidencia propia prevalece sobre inferencia indirecta
# ============================================================

def test_i_conflicto_gps_propio_prevalece_sobre_hermano_de_transporte(tmp_path):
    """Si ESTE documento trae su propio conflicto GPS real (evidencia
    directa), un documento hermano del mismo transporte ya resuelto
    (inferencia indirecta -- "el hermano sí tuvo GPS limpio") no debe
    pisarlo en silencio; la contradicción real entre dos documentos del
    mismo transporte es, en sí misma, motivo suficiente para preguntar,
    no para promediar."""
    raiz, catalogos, actual, dataset, colina, renca = _entorno(tmp_path, [
        _fila_csv(
            numero_guia="1", numero_transporte="T-COMPARTIDO", patente_tracto="AA1111",
            tipo_carga="BARRAS", descripcion_material="B HORMIGON 12MM 12M A630-420H (N)",
        ),
        _fila_csv(
            numero_guia="2", numero_transporte="T-COMPARTIDO", patente_tracto="AA1111",
            tipo_carga="NO DETERMINADO",
            motivo_origen_gps=_CONFLICTO_REAL, origen_gps="ORIGEN_GPS_CONFLICTO",
        ),
    ])
    _revalidar(raiz)
    fila_2 = _fila_por_guia(dataset, "2")
    # AZA COLINA sigue siendo el candidato del conflicto con más solape
    # -- pero la fuente debe seguir siendo la evidencia propia (o la
    # categoría, que aquí no aplica), nunca "porque el hermano ya lo
    # tenía" pisando un conflicto real y propio.
    assert fila_2["origen_determinado_por"] != "DOCUMENTO_HERMANO_MISMO_TRANSPORTE"


# ============================================================
# J. material desconocido pero otras evidencias suficientes -> resolver
# ============================================================

def test_j_material_desconocido_con_historial_de_cliente_unanime_resuelve(tmp_path):
    """Caso real 472477: sin categoría determinable, el historial
    COMPLETO de ese cliente (13+ despachos previos, todos AZA COLINA,
    ninguno en desacuerdo) es evidencia suficiente para resolver sin
    preguntar."""
    filas = [_fila_csv(
        numero_guia=str(n), numero_transporte=f"T{n}", patente_tracto="ZZ0000",
        cliente="PRODALAM SA", tipo_carga="BARRAS",
        descripcion_material="B HORMIGON 12MM 12M A630-420H (N)",
    ) for n in range(1, 3)]
    filas.append(_fila_csv(
        numero_guia="TARGET", numero_transporte="TTARGET", patente_tracto="VP8521",
        cliente="PRODALAM SA", tipo_carga="NO DETERMINADO", descripcion_material="",
        motivo_origen_gps=_EMPATE_0_0, origen_gps="ORIGEN_GPS_CONFLICTO",
        despachar_a_crudo="PASAJE ISRAEL 1303",
    ))
    raiz, catalogos, actual, dataset, colina, renca = _entorno(tmp_path, filas)
    _revalidar(raiz)
    fila = _fila_por_guia(dataset, "TARGET")
    assert fila["planta_origen_id"] == colina.planta_id
    assert fila["origen_determinado_por"] == "HISTORIAL_CLIENTE"
    assert _sin_decision_origen(actual, "TARGET")


# ============================================================
# K. material desconocido y resto insuficiente -> humano
# ============================================================

def test_k_material_desconocido_sin_evidencia_suficiente_escala_a_humano(tmp_path):
    raiz, catalogos, actual, dataset, colina, renca = _entorno(tmp_path, [_fila_csv(
        numero_guia="TARGET", numero_transporte="TTARGET", patente_tracto="VP8521",
        cliente="CLIENTE NUEVO SIN HISTORIAL SA", tipo_carga="NO DETERMINADO",
        motivo_origen_gps=_EMPATE_0_0, origen_gps="ORIGEN_GPS_CONFLICTO",
    )])
    _revalidar(raiz)
    fila = _fila_por_guia(dataset, "TARGET")
    assert fila["planta_origen_id"] == ""
    decision = next(
        d for d in _pendientes(actual)
        if (d.get("documento") or {}).get("numero_guia") == "TARGET" and d.get("estado") == "PENDIENTE"
    )
    assert decision["tipo"] == "ORIGEN_NO_CONFIRMADO"
    assert {c["planta_nombre"] for c in decision["candidatos"]} == {"AZA COLINA", "AZA RENCA"}


# ============================================================
# L. origen ya confirmado no se reinvestiga
# ============================================================

def test_l_origen_ya_confirmado_no_se_reinvestiga(tmp_path):
    raiz, catalogos, actual, dataset, colina, renca = _entorno(tmp_path, lambda colina, renca: [_fila_csv(
        numero_guia="1", numero_transporte="T1", patente_tracto="AA1111",
        tipo_carga="ANGULOS", descripcion_material="ANGULO 25X25X3MM",
        planta_origen_id=colina.planta_id, planta_origen_nombre="AZA COLINA",
        origen_determinado_por="CONFIRMACION_HUMANA", evidencia_origen="DECISION_HUMANA:x",
    )])
    _revalidar(raiz)
    fila = _fila_por_guia(dataset, "1")
    # A pesar de que la categoría (ANGULOS) apuntaría a RENCA, un origen
    # ya persistido -- sea cual sea su fuente -- nunca se reinvestiga.
    assert fila["planta_origen_id"] == colina.planta_id
    assert fila["origen_determinado_por"] == "CONFIRMACION_HUMANA"


# ============================================================
# M. no generar ORIGEN_NO_CONFIRMADO antes de agotar capacidades
# ============================================================

def test_m_no_genera_origen_no_confirmado_si_alguna_capacidad_puede_resolver(tmp_path):
    """Combina TODAS las vías automáticas disponibles en un solo dataset
    -- ninguna guía resoluble por alguna vía debe terminar con una
    tarjeta `ORIGEN_NO_CONFIRMADO`."""
    filas = [
        _fila_csv(  # A: categoría BARRAS
            numero_guia="1", numero_transporte="T1", patente_tracto="AA1111",
            tipo_carga="BARRAS", descripcion_material="B HORMIGON 12MM 12M A630-420H (N)",
        ),
        _fila_csv(  # G: hermano de transporte
            numero_guia="2", numero_transporte="T1", patente_tracto="AA1111",
            tipo_carga="NO DETERMINADO",
        ),
    ]
    filas += [
        _fila_csv(  # historial de cliente
            numero_guia=str(n), numero_transporte=f"TH{n}", patente_tracto="ZZ0000",
            cliente="PRODALAM SA", tipo_carga="BARRAS",
            descripcion_material="B HORMIGON 12MM 12M A630-420H (N)",
        ) for n in range(3, 5)
    ]
    filas.append(_fila_csv(  # J: resuelto por historial
        numero_guia="TARGET", numero_transporte="TTARGET", patente_tracto="VP8521",
        cliente="PRODALAM SA", tipo_carga="NO DETERMINADO",
        motivo_origen_gps=_EMPATE_0_0, origen_gps="ORIGEN_GPS_CONFLICTO",
    ))
    raiz, catalogos, actual, dataset, colina, renca = _entorno(tmp_path, filas)
    _revalidar(raiz)
    for guia in ("1", "2", "TARGET"):
        assert _fila_por_guia(dataset, guia)["planta_origen_id"] != "", guia
        assert _sin_decision_origen(actual, guia), guia


# ============================================================
# N. idempotencia
# ============================================================

def test_n_idempotencia(tmp_path):
    raiz, catalogos, actual, dataset, colina, renca = _entorno(tmp_path, [_fila_csv(
        numero_guia="1", numero_transporte="T1", patente_tracto="AA1111",
        tipo_carga="BARRAS", descripcion_material="B HORMIGON 12MM 12M A630-420H (N)",
    )])
    _revalidar(raiz, "reporte_n1")
    dataset_antes = dataset.read_bytes()
    decisiones_antes = _pendientes(actual)

    resultado_2 = _revalidar(raiz, "reporte_n2")
    assert resultado_2["guias_actualizadas"] == []
    assert resultado_2["bandeja_cambio_efectivo"] is False
    assert dataset.read_bytes() == dataset_antes
    assert _pendientes(actual) == decisiones_antes


# ============================================================
# O. viaje ajeno intacto
# ============================================================

def test_o_viaje_ajeno_intacto(tmp_path):
    raiz, catalogos, actual, dataset, colina, renca = _entorno(tmp_path, lambda colina, renca: [
        _fila_csv(
            numero_guia="TARGET", numero_transporte="TTARGET", patente_tracto="VP8521",
            tipo_carga="BARRAS", descripcion_material="B HORMIGON 12MM 12M A630-420H (N)",
        ),
        _fila_csv(
            numero_guia="AJENO", numero_transporte="TAJENO", patente_tracto="ZZ9999",
            cliente="CLIENTE TOTALMENTE AJENO SA", tipo_carga="ANGULOS",
            descripcion_material="ANGULO 25X25X3MM",
            planta_origen_id=renca.planta_id, planta_origen_nombre="AZA RENCA",
            origen_determinado_por="TELEMETRIA_GPS",
            estado_ruta="RUTA_CALCULADA", distancia_km="5.0", duracion_min="8.0",
            indicador_revision="OK", estado_documental="OK", estado_operacional="OK",
        ),
    ])
    fila_ajeno_antes = _fila_por_guia(dataset, "AJENO")
    _revalidar(raiz)
    assert _fila_por_guia(dataset, "AJENO") == fila_ajeno_antes
