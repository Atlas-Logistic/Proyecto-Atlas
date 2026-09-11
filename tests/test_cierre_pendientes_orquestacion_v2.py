"""Bloque CIERRE DE ORQUESTACIÓN V2 -- defectos reales expuestos por la
validación del cierre anterior (045dec9), sobre los casos reales 472037
(origen), 464746 (destino) y 472477 (convergencia origen+material).

CASO A (472037) -- `revalidar_origen_por_vecinos_temporales_gps_sin_ocr`
podía fijar `planta_origen_id` usando el patrón de OTROS viajes del
mismo vehículo aunque la fila objetivo YA tuviera, en su propia ventana
documental, un conflicto GPS real entre dos plantas (evidencia más
fuerte, aunque ambigua) -- `detectar_decision_origen_no_confirmado`
nunca llegaba a publicar `ORIGEN_NO_CONFIRMADO` porque veía el origen
"ya resuelto". Dos piezas: una guarda preventiva (nunca vuelve a
ocurrir) y `revalidar_origen_vecinos_gps_contra_evidencia_propia_real_
sin_ocr` (corrige lo ya persistido).

CASO B (464746) -- trazado completo: `regenerar_decisiones_persistidas`
SÍ descarta el candidato fresco, pero se confirma (con datos reales)
que es la vía `guias_destino_conocido_ruta_pendiente` -- una relación
obra<->destino YA CONFIRMADA a nivel humano, citando esa misma guía,
cuyo destino coincide LITERALMENTE con el documental -- funcionando
exactamente como está diseñada ("decisión ya contestada realmente").
No es un defecto: estos tests prueban ambos lados de esa misma regla
(cuándo debe sobrevivir, cuándo debe suprimirse), sin tocar el
mecanismo.

CASO C (472477) -- tras aplicar una decisión de destino, si la guía
sigue con `MATERIAL_AUSENTE` y su imagen sigue disponible, el reproceso
focal ya existente se encadena automáticamente; si recupera una
categoría antes desconocida, la resolución de origen por categoría (que
ahora también opera sobre `estado_ruta` vacío, no sólo `ORIGEN_NO_
DETERMINADO`) obtiene, en la misma operación, lo que le faltaba para
dejar de abstenerse."""
from __future__ import annotations

import csv
import json

from PIL import Image

from atlas_core.aplicacion_decisiones import aplicar_decision_obra
from atlas_core.catalogo_clientes import CatalogoClientes, EstadoCalidadCliente
from atlas_core.catalogo_obras_destinos import CatalogoObrasDestinos, Evidencia, ResultadoEvidencia, TipoEvidencia
from atlas_core.catalogo_plantas import CatalogoPlantas, EstadoCalidad
from atlas_core.decisiones_pendientes import (
    detectar_decision_destino_contaminado_documental,
    generar_artefacto, regenerar_decisiones_persistidas,
)
from atlas_core.procesamiento_masivo import COLUMNAS
from atlas_core.revalidacion_documental import (
    revalidar_origen_por_vecinos_temporales_gps_sin_ocr,
    revalidar_origen_vecinos_gps_contra_evidencia_propia_real_sin_ocr,
    revalidar_y_regenerar_reporte,
)
from atlas_core.rutas.modelos import CandidatoGeocodificacion, Coordenadas, EstadoRuta, ResultadoGeocodificacion, ResultadoRuta
from atlas_core.rutas.proveedor import ProveedorRutasSimulado

COORD_AZA_COLINA = Coordenadas(-70.665977, -33.137558)
COORD_AZA_RENCA = Coordenadas(-70.685226, -33.401595)
DIRECCION_CONFIRMADA = "AV. LIBERTADOR 4500"


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


def _plantas(catalogos, *, categorias_colina=("BARRAS",), categorias_renca=()):
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


def _motivo_conflicto_real(planta_colina, planta_renca, *, solape_colina=22.4, solape_renca=1.1):
    return (
        f"CONFLICTO_REAL_EN_VENTANA(AZA_COLINA:score=0.3681,solape={solape_colina}%;"
        f"AZA_RENCA:score=0.3096,solape={solape_renca}%)"
    )


# =====================================================================
# CASO A -- conflicto real de origen entre dos plantas
# =====================================================================

def test_a1_conflicto_real_entre_dos_plantas_no_se_pisa_por_patron_de_vecinos(tmp_path):
    """Test 1 (regla 8): conflicto real entre dos plantas -> ORIGEN_NO_
    CONFIRMADO. Guarda PREVENTIVA: aunque existan vecinos GPS-confirmados
    del mismo vehículo convergiendo en una sola planta, esa evidencia más
    débil nunca debe pisar el conflicto real y propio del documento."""
    catalogos = tmp_path / "catalogos"
    planta_colina, planta_renca = _plantas(catalogos)
    dataset = tmp_path / "dataset.csv"
    motivo = _motivo_conflicto_real(planta_colina, planta_renca)
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
            origen_determinado_por="", motivo_origen_gps=motivo, origen_gps="ORIGEN_GPS_CONFLICTO",
            estado_ruta="ORIGEN_NO_DETERMINADO", motivo_ruta="ORIGEN_GPS_CONFLICTO",
        ),
    ])
    resultado = revalidar_origen_por_vecinos_temporales_gps_sin_ocr(ruta_dataset=dataset)
    assert resultado["guias_actualizadas"] == []
    fila_target = _fila_por_guia(dataset, "TARGET")
    assert fila_target["planta_origen_id"] == ""


def test_a1b_conflicto_real_publica_origen_no_confirmado_end_to_end(tmp_path):
    """Mismo escenario que A1, pero end-to-end: `revalidar_y_regenerar_
    reporte` sobre la raíz completa debe terminar publicando la tarjeta
    `ORIGEN_NO_CONFIRMADO` -- nunca una planta forzada."""
    raiz = tmp_path / "Atlas"
    catalogos = raiz / "catalogos_privados"
    actual = raiz / "operacion" / "actual"
    (raiz / "reportes").mkdir(parents=True)
    actual.mkdir(parents=True)
    _catalogos_base(catalogos)
    planta_colina, planta_renca = _plantas(catalogos)
    dataset = actual / "analisis_completo_guias.csv"
    motivo = _motivo_conflicto_real(planta_colina, planta_renca)
    _escribir_csv(dataset, [
        _fila_csv(
            numero_guia="VECINO1", numero_transporte="TV1", fecha="17-08-2026",
            patente_tracto="AL1879", planta_origen_id=planta_colina.planta_id,
            planta_origen_nombre="AZA COLINA", origen_determinado_por="TELEMETRIA_GPS",
            estado_ruta="RUTA_CALCULADA", distancia_km="10", duracion_min="15",
        ),
        _fila_csv(
            numero_guia="VECINO2", numero_transporte="TV2", fecha="18-08-2026",
            patente_tracto="AL1879", planta_origen_id=planta_colina.planta_id,
            planta_origen_nombre="AZA COLINA", origen_determinado_por="TELEMETRIA_GPS",
            estado_ruta="RUTA_CALCULADA", distancia_km="11", duracion_min="16",
        ),
        _fila_csv(
            numero_guia="TARGET", numero_transporte="TTARGET", fecha="19-08-2026",
            patente_tracto="AL1879", planta_origen_id="", planta_origen_nombre="",
            origen_determinado_por="", motivo_origen_gps=motivo, origen_gps="ORIGEN_GPS_CONFLICTO",
            estado_ruta="ORIGEN_NO_DETERMINADO", motivo_ruta="ORIGEN_GPS_CONFLICTO",
        ),
    ])
    # `revalidar_y_regenerar_reporte` sólo republica decisiones si YA
    # existe una bandeja en disco (aunque sea vacía) -- mismo requisito
    # que Desktop/`aplicar_decision_obra` ya satisfacen siempre.
    generar_artefacto(
        ruta_dataset=dataset, carpeta_catalogos=catalogos, decisiones=[],
        ruta_salida=actual / "decisiones_pendientes.json",
    )
    resultado = revalidar_y_regenerar_reporte(raiz_atlas=raiz, nombre_carpeta_reporte="reporte_caso_a")

    fila_target = _fila_por_guia(dataset, "TARGET")
    # No forzar una planta: sigue sin origen.
    assert fila_target["planta_origen_id"] == ""

    pendientes = _pendientes(actual)
    decision_target = next(
        (
            d for d in pendientes
            if (d.get("documento") or {}).get("numero_guia") == "TARGET" and d.get("estado") == "PENDIENTE"
        ),
        None,
    )
    assert decision_target is not None, "debía publicarse ORIGEN_NO_CONFIRMADO para TARGET"
    assert decision_target["tipo"] == "ORIGEN_NO_CONFIRMADO"
    nombres_candidatos = {c["planta_nombre"] for c in decision_target.get("candidatos", [])}
    assert nombres_candidatos == {"AZA COLINA", "AZA RENCA"}


def test_a2_origen_ya_persistido_erroneamente_por_vecinos_se_revierte(tmp_path):
    """Caso real 472037: un origen que YA quedó fijado por el patrón de
    vecinos (de una corrida anterior a esta guarda) se revierte cuando
    la propia fila tiene un conflicto GPS real -- `estado_ruta`/`motivo_
    ruta` no se tocan si ya describían correctamente la ambigüedad."""
    dataset = tmp_path / "dataset.csv"
    motivo = _motivo_conflicto_real(None, None)
    _escribir_csv(dataset, [
        _fila_csv(
            numero_guia="472037", numero_transporte="T472037",
            patente_tracto="BPHR67", planta_origen_id="planta-colina-id",
            planta_origen_nombre="AZA COLINA", origen_determinado_por="PATRON_VEHICULO_GPS_VECINOS",
            evidencia_origen="vecinos_gps_confirmados=3", motivo_origen_gps=motivo,
            origen_gps="ORIGEN_GPS_CONFLICTO",
            estado_ruta="ORIGEN_NO_DETERMINADO", motivo_ruta="ORIGEN_GPS_CONFLICTO",
        ),
    ])
    resultado = revalidar_origen_vecinos_gps_contra_evidencia_propia_real_sin_ocr(ruta_dataset=dataset)
    assert resultado["guias_actualizadas"] == ["472037"]
    fila = _fila_por_guia(dataset, "472037")
    assert fila["planta_origen_id"] == ""
    assert fila["planta_origen_nombre"] == ""
    assert fila["origen_determinado_por"] == ""
    assert fila["evidencia_origen"] == ""
    # La ambigüedad de origen ya estaba correctamente descrita -- se conserva.
    assert fila["estado_ruta"] == "ORIGEN_NO_DETERMINADO"
    assert fila["motivo_ruta"] == "ORIGEN_GPS_CONFLICTO"


def test_a3_sin_evidencia_propia_real_el_patron_de_vecinos_sigue_funcionando(tmp_path):
    """Regresión negativa: la guarda nueva nunca bloquea el caso ORIGINAL
    que esta función existe para resolver (464981) -- sin evidencia
    propia real (motivo genérico, p. ej. `SIN_EVIDENCIA_GPS`), el patrón
    de vecinos sigue resolviendo igual que siempre."""
    catalogos = tmp_path / "catalogos"
    planta_colina, _ = _plantas(catalogos)
    dataset = tmp_path / "dataset.csv"
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
            origen_determinado_por="", motivo_origen_gps="SIN_EVIDENCIA_GPS", origen_gps="ORIGEN_GPS_NO_DETERMINADO",
        ),
    ])
    resultado = revalidar_origen_por_vecinos_temporales_gps_sin_ocr(ruta_dataset=dataset)
    assert resultado["guias_actualizadas"] == ["TARGET"]
    fila_target = _fila_por_guia(dataset, "TARGET")
    assert fila_target["planta_origen_id"] == planta_colina.planta_id


# =====================================================================
# CASO B -- 464746: candidato fresco vs. decisión ya contestada
# =====================================================================

def _entorno_destino_generico(tmp_path, *, con_relacion_confirmada, direccion_confirmada_coincide=True):
    raiz = tmp_path / "Atlas"
    catalogos = raiz / "catalogos_privados"
    actual = raiz / "operacion" / "actual"
    (raiz / "reportes").mkdir(parents=True)
    actual.mkdir(parents=True)
    _catalogos_base(catalogos)
    cliente = CatalogoClientes(catalogos / "clientes.json").crear(
        razon_social="EASY RETAIL SA", rut="76.111.111-6", fuente="TEST",
        estado_calidad=EstadoCalidadCliente.CONFIRMADO,
    )
    obra_texto = "EMPRESA CONSTRUCTORA MENA Y CIA"
    destino_texto = "CAM. EL NOVICIADO LAMPA LAMPA"
    if con_relacion_confirmada:
        obras = CatalogoObrasDestinos(
            ruta=catalogos / "obras_destinos.json", ruta_clientes=catalogos / "clientes.json",
            ruta_destinos=catalogos / "destinos_maestros.json",
        )
        # Registrar la obra + destino CONFIRMADO citando esta misma guía.
        from atlas_core.catalogo_destinos import CatalogoDestinos, EstadoCalidadDestino
        destino = CatalogoDestinos(catalogos / "destinos_maestros.json", ruta_clientes=catalogos / "clientes.json").crear_o_reutilizar_global(
            nombre_destino=destino_texto if direccion_confirmada_coincide else "OTRA DIRECCION DISTINTA 999",
            direccion=destino_texto if direccion_confirmada_coincide else "OTRA DIRECCION DISTINTA 999",
            comuna="LAMPA", region="Metropolitana", fuente="TEST",
            estado_calidad=EstadoCalidadDestino.CONFIRMADO,
        )
        resultado_obs = obras.registrar_observacion(
            cliente_id=cliente.cliente_id, nombre_obra=obra_texto, destino_id=destino.destino_id,
            evidencia=Evidencia(
                tipo=TipoEvidencia.GUIA.value, identificador_fuente="464746", referencia_hash="b" * 64,
                campos_observados={"obra": obra_texto, "destino": destino_texto}, fecha="2026-01-01T00:00:00+00:00",
                actor_proceso="TEST", resultado=ResultadoEvidencia.SOPORTA.value,
            ),
        )
        if resultado_obs.relacion is not None and resultado_obs.relacion.estado == "PENDIENTE":
            obras.confirmar_relacion(resultado_obs.relacion.relacion_id, actor="TEST", identificador_fuente="b" * 64)

    fila = _fila_csv(
        archivo="464746.jpeg", numero_guia="464746", numero_transporte="T464746",
        cliente="EASY RETAIL SA", obra_destino=obra_texto,
        despachar_a_crudo=destino_texto, planta_origen_id="planta-colina",
        planta_origen_nombre="AZA COLINA", origen_determinado_por="TELEMETRIA_GPS",
        estado_ruta="REQUIERE_REVISION", motivo_ruta="GEOCODIFICACION_DEMASIADO_GENERICA",
    )
    dataset = actual / "analisis_completo_guias.csv"
    _escribir_csv(dataset, [fila])
    return raiz, catalogos, actual, dataset


def test_b1_candidato_fresco_sobrevive_sin_relacion_confirmada(tmp_path):
    """Test 3 (regla 8): sin una relación obra<->destino ya CONFIRMADA
    citando esta guía, el candidato fresco DESTINO_NO_RESUELTO debe
    sobrevivir a `regenerar_decisiones_persistidas` -- nunca desaparece
    por una falsa terminalidad."""
    from atlas_core.revalidacion_documental import detectar_decisiones_destino_no_resuelto_sin_ocr

    raiz, catalogos, actual, dataset = _entorno_destino_generico(tmp_path, con_relacion_confirmada=False)
    candidatas = detectar_decisiones_destino_no_resuelto_sin_ocr(raiz_atlas=raiz)
    assert len(candidatas) == 1
    restantes = regenerar_decisiones_persistidas(
        decisiones=candidatas, carpeta_catalogos=catalogos, ruta_dataset=dataset,
    )
    assert [r["decision_id"] for r in restantes] == [candidatas[0]["decision_id"]]


def test_b2_decision_realmente_respondida_no_reaparece(tmp_path):
    """Test 4 (regla 8): con la relación obra<->destino CONFIRMADA a
    nivel humano citando esta guía Y coincidiendo literalmente con el
    texto documental, el candidato fresco se descarta -- Atlas no vuelve
    a preguntar una identidad de destino que un humano ya confirmó,
    aunque el problema técnico de ruta siga vivo."""
    from atlas_core.revalidacion_documental import detectar_decisiones_destino_no_resuelto_sin_ocr

    raiz, catalogos, actual, dataset = _entorno_destino_generico(tmp_path, con_relacion_confirmada=True)
    candidatas = detectar_decisiones_destino_no_resuelto_sin_ocr(raiz_atlas=raiz)
    assert len(candidatas) == 1
    restantes = regenerar_decisiones_persistidas(
        decisiones=candidatas, carpeta_catalogos=catalogos, ruta_dataset=dataset,
    )
    assert restantes == []
    # El problema técnico de ruta sigue vivo en el dataset -- nunca se oculta.
    fila = _fila_por_guia(dataset, "464746")
    assert fila["motivo_ruta"] == "GEOCODIFICACION_DEMASIADO_GENERICA"


def test_b3_relacion_confirmada_con_direccion_distinta_no_suprime(tmp_path):
    """Regresión negativa de B2: si la relación CONFIRMADA cita otra
    dirección (no coincide literalmente con `despachar_a_crudo`), la
    tarjeta debe sobrevivir -- la identidad de ESTE texto documental
    concreto sigue sin respuesta."""
    from atlas_core.revalidacion_documental import detectar_decisiones_destino_no_resuelto_sin_ocr

    raiz, catalogos, actual, dataset = _entorno_destino_generico(
        tmp_path, con_relacion_confirmada=True, direccion_confirmada_coincide=False,
    )
    candidatas = detectar_decisiones_destino_no_resuelto_sin_ocr(raiz_atlas=raiz)
    assert len(candidatas) == 1
    restantes = regenerar_decisiones_persistidas(
        decisiones=candidatas, carpeta_catalogos=catalogos, ruta_dataset=dataset,
    )
    assert len(restantes) == 1


# =====================================================================
# CASO C -- 472477: material focal encadenado + convergencia de origen
# =====================================================================

def _entorno_convergencia(tmp_path, *, con_imagen=True):
    raiz = tmp_path / "Atlas"
    catalogos = raiz / "catalogos_privados"
    actual = raiz / "operacion" / "actual"
    entradas = raiz / "operacion" / "entradas" / "20260909_111301"
    (raiz / "reportes").mkdir(parents=True)
    actual.mkdir(parents=True)
    entradas.mkdir(parents=True)
    _catalogos_base(catalogos)
    planta_colina, planta_renca = _plantas(catalogos, categorias_colina=("BARRAS",), categorias_renca=())

    dataset = actual / "analisis_completo_guias.csv"
    fila_target = _fila_csv(
        archivo="TARGET.jpeg", numero_guia="TARGET", numero_transporte="TTARGET", fecha="24-08-2026",
        cliente="PRODALAM SA", obra_destino="CONSTRUCTORA DON PEDRO LTDA",
        patente_tracto="VP8521", despachar_a_crudo="",
        planta_origen_id="", planta_origen_nombre="", origen_determinado_por="",
        estado_ruta="", motivo_ruta="",
        descripcion_material="", tipo_carga="NO DETERMINADO",
        motivos_revision_documento="DESTINO_CONTAMINADO_POR_OTRA_SECCION | MATERIAL_AUSENTE",
        indicador_revision="REVISAR", estado_documental="REQUIERE_REVISION",
        motivo_origen_gps="CONFLICTO_REAL_EN_VENTANA(AZA_COLINA:score=0.0,solape=0.0%;AZA_RENCA:score=0.0,solape=0.0%)",
        origen_gps="ORIGEN_GPS_CONFLICTO",
    )
    _escribir_csv(dataset, [fila_target])
    if con_imagen:
        Image.new("RGB", (4, 4), color="white").save(entradas / "TARGET.jpeg")

    decision = detectar_decision_destino_contaminado_documental(
        archivo="TARGET.jpeg", fila=fila_target, carpeta_catalogos=catalogos,
    )
    assert decision is not None
    generar_artefacto(
        ruta_dataset=dataset, carpeta_catalogos=catalogos, decisiones=[decision],
        ruta_salida=actual / "decisiones_pendientes.json",
    )
    return raiz, catalogos, actual, dataset, decision, planta_colina


def _proveedor_ruta_confiable():
    consulta = f"{DIRECCION_CONFIRMADA}, Chile"
    return ProveedorRutasSimulado(
        geocodificaciones={
            consulta: ResultadoGeocodificacion(
                EstadoRuta.REQUIERE_REVISION,
                (CandidatoGeocodificacion(
                    Coordenadas(-70.64, -33.42), DIRECCION_CONFIRMADA + ", Santiago, RM, Chile", 0.95,
                    "Santiago", "Metropolitana",
                ),),
                "",
            ),
        },
        resultado_ruta=ResultadoRuta(EstadoRuta.RUTA_CALCULADA, 12.3, 18.4, "SINTETICO"),
    )


def test_c1_material_ausente_con_imagen_dispara_reproceso_focal_y_desbloquea_origen(tmp_path, monkeypatch):
    """Tests 6 (regla 8) + convergencia: MATERIAL_AUSENTE con imagen
    disponible dispara el reproceso focal ya existente dentro del flujo
    normal de `aplicar_decision_obra`; la categoría recuperada (BARRAS,
    única compatible con AZA COLINA) resuelve el origen -- que antes
    quedaba bloqueado por el empate GPS 0.0%/0.0% -- en la MISMA
    operación."""
    raiz, catalogos, actual, dataset, decision, planta_colina = _entorno_convergencia(tmp_path)
    monkeypatch.setattr(
        "atlas_core.ocr.leer_texto_imagen",
        lambda ruta, lector=None: ["B HORMIGON 25MM 12M A630-420H (N)"],
    )
    resultado = aplicar_decision_obra(
        raiz_atlas=raiz, decision_id=decision["decision_id"], accion="REGISTRAR_DIRECCION",
        direccion_manual=DIRECCION_CONFIRMADA, comuna_manual="Santiago", proveedor_rutas=_proveedor_ruta_confiable(),
    )
    assert resultado["ok"] is True
    assert resultado["material_focal"]["aplicado"] is True
    assert "revalidacion_tras_material" in resultado

    fila = _fila_por_guia(dataset, "TARGET")
    assert fila["descripcion_material"] == "B HORMIGON 25MM 12M A630-420H (N)"
    assert fila["tipo_carga"] == "BARRAS"
    assert "MATERIAL_AUSENTE" not in fila["motivos_revision_documento"]
    # La categoría recién recuperada resolvió el origen por eliminación
    # de alternativas (único candidato compatible) -- nunca inventado.
    assert fila["planta_origen_id"] == planta_colina.planta_id
    assert fila["estado_ruta"] == "RUTA_CALCULADA"


def test_c2_material_irrecuperable_conserva_abstencion(tmp_path, monkeypatch):
    """Test 7 (regla 8): si el OCR focal no logra recuperar ningún
    material reconocible, `MATERIAL_AUSENTE` se conserva intacto -- nunca
    se inventa una categoría ni se fuerza un origen."""
    raiz, catalogos, actual, dataset, decision, planta_colina = _entorno_convergencia(tmp_path)
    monkeypatch.setattr(
        "atlas_core.ocr.leer_texto_imagen",
        lambda ruta, lector=None: ["TEXTO SIN NINGUN MATERIAL RECONOCIBLE"],
    )
    resultado = aplicar_decision_obra(
        raiz_atlas=raiz, decision_id=decision["decision_id"], accion="REGISTRAR_DIRECCION",
        direccion_manual=DIRECCION_CONFIRMADA, comuna_manual="Santiago", proveedor_rutas=_proveedor_ruta_confiable(),
    )
    assert resultado["ok"] is True
    assert resultado["material_focal"]["aplicado"] is False
    assert "revalidacion_tras_material" not in resultado

    fila = _fila_por_guia(dataset, "TARGET")
    assert fila["descripcion_material"] == ""
    assert "MATERIAL_AUSENTE" in fila["motivos_revision_documento"]
    # Sin categoría conocida, el origen sigue, honestamente, sin resolver.
    assert fila["planta_origen_id"] == ""


def test_c3_sin_imagen_disponible_nunca_intenta_ocr(tmp_path):
    """El reproceso focal se abstiene solo si la imagen ya no existe --
    nunca lanza un error ni bloquea el resto de la convergencia."""
    raiz, catalogos, actual, dataset, decision, planta_colina = _entorno_convergencia(tmp_path, con_imagen=False)
    resultado = aplicar_decision_obra(
        raiz_atlas=raiz, decision_id=decision["decision_id"], accion="REGISTRAR_DIRECCION",
        direccion_manual=DIRECCION_CONFIRMADA, comuna_manual="Santiago", proveedor_rutas=_proveedor_ruta_confiable(),
    )
    assert resultado["ok"] is True
    assert resultado["material_focal"]["aplicado"] is False
    fila = _fila_por_guia(dataset, "TARGET")
    assert "MATERIAL_AUSENTE" in fila["motivos_revision_documento"]


def test_c4_idempotencia_tras_convergencia(tmp_path, monkeypatch):
    """Test 8 (regla 8): reejecutar la batería después de la
    convergencia (material + origen) no cambia nada -- ni vuelve a
    intentar el OCR focal (el motivo ya no está vigente)."""
    raiz, catalogos, actual, dataset, decision, planta_colina = _entorno_convergencia(tmp_path)
    monkeypatch.setattr(
        "atlas_core.ocr.leer_texto_imagen",
        lambda ruta, lector=None: ["B HORMIGON 25MM 12M A630-420H (N)"],
    )
    aplicar_decision_obra(
        raiz_atlas=raiz, decision_id=decision["decision_id"], accion="REGISTRAR_DIRECCION",
        direccion_manual=DIRECCION_CONFIRMADA, comuna_manual="Santiago", proveedor_rutas=_proveedor_ruta_confiable(),
    )
    dataset_antes = dataset.read_bytes()

    def _falla_si_se_llama(ruta, lector=None):
        raise AssertionError("no debía reintentar OCR -- el motivo ya no está vigente")

    monkeypatch.setattr("atlas_core.ocr.leer_texto_imagen", _falla_si_se_llama)
    resultado_segunda_pasada = revalidar_y_regenerar_reporte(
        raiz_atlas=raiz, nombre_carpeta_reporte="reporte_convergencia_idempotencia",
    )
    assert resultado_segunda_pasada["guias_actualizadas"] == []
    assert resultado_segunda_pasada["bandeja_cambio_efectivo"] is False
    assert dataset.read_bytes() == dataset_antes


def test_c5_viaje_ajeno_intacto_tras_convergencia(tmp_path, monkeypatch):
    """Test 9 (regla 8): un viaje sin relación alguna con TARGET queda
    exactamente igual, byte a byte, tras toda la convergencia."""
    raiz, catalogos, actual, dataset, decision, planta_colina = _entorno_convergencia(tmp_path)
    filas = _leer_csv(dataset)
    filas.append(_fila_csv(
        archivo="AJENO.jpeg", numero_guia="AJENO", numero_transporte="TAJENO",
        cliente="CLIENTE AJENO SA", obra_destino="OBRA AJENA",
        patente_tracto="ZZ9999", despachar_a_crudo="OTRA DIRECCION 1",
        planta_origen_id=planta_colina.planta_id, planta_origen_nombre="AZA COLINA",
        origen_determinado_por="TELEMETRIA_GPS",
        estado_ruta="RUTA_CALCULADA", distancia_km="7.0", duracion_min="10.0",
        indicador_revision="OK", estado_documental="OK", estado_operacional="OK",
    ))
    _escribir_csv(dataset, filas)
    fila_ajeno_antes = _fila_por_guia(dataset, "AJENO")

    monkeypatch.setattr(
        "atlas_core.ocr.leer_texto_imagen",
        lambda ruta, lector=None: ["B HORMIGON 25MM 12M A630-420H (N)"],
    )
    aplicar_decision_obra(
        raiz_atlas=raiz, decision_id=decision["decision_id"], accion="REGISTRAR_DIRECCION",
        direccion_manual=DIRECCION_CONFIRMADA, comuna_manual="Santiago", proveedor_rutas=_proveedor_ruta_confiable(),
    )

    assert _fila_por_guia(dataset, "AJENO") == fila_ajeno_antes
