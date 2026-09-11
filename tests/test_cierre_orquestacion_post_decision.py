"""Bloque CIERRE DE ORQUESTACIÓN -- caso real 472477 (transporte
0000354870): aplicar una decisión humana de destino (DESTINO_NO_RESUELTO
/ REGISTRAR_DIRECCION) dejaba de disparar la batería completa de
revalidación (`revalidar_y_regenerar_reporte`) -- sólo regeneraba el
reporte con los datos tal cual quedaron, así que evidencia recién
desbloqueada (origen, ruta, decisiones de OTRAS guías) nunca tenía
oportunidad de resolverse en la MISMA operación; había que cerrar y
reabrir Desktop (o correr un script aparte) para que una segunda
reconciliación la alcanzara.

Este módulo prueba, con un solo escenario real reutilizado por los 5
tests (regla 8 A-E del cierre):
A) aplicar REGISTRAR_DIRECCION dispara la batería completa, no sólo el
   reporte;
B) evidencia nueva que permite resolución automática (origen por
   convergencia de vecinos GPS del mismo vehículo) termina sin ninguna
   decisión humana de origen;
C) una ambigüedad real de OTRA guía, distinta y no relacionada, sigue
   generando su propia decisión pendiente -- la batería nunca "resuelve
   en silencio" lo que sigue siendo genuinamente ambiguo;
D) reejecutar `revalidar_y_regenerar_reporte` sin evidencia nueva es
   idempotente -- no cambia nada ya persistido;
E) un viaje ajeno al transporte de la decisión (patente, obra, cliente y
   motivo totalmente distintos) queda exactamente igual, byte a byte."""
from __future__ import annotations

import csv
import json

from atlas_core.aplicacion_decisiones import aplicar_decision_obra
from atlas_core.catalogo_plantas import CatalogoPlantas, EstadoCalidad
from atlas_core.decisiones_pendientes import (
    detectar_decision_destino_contaminado_documental, generar_artefacto,
)
from atlas_core.procesamiento_masivo import COLUMNAS
from atlas_core.revalidacion_documental import revalidar_y_regenerar_reporte
from atlas_core.rutas.modelos import CandidatoGeocodificacion, Coordenadas, EstadoRuta, ResultadoGeocodificacion, ResultadoRuta
from atlas_core.rutas.proveedor import ProveedorRutasSimulado

COORD_AZA_COLINA = Coordenadas(-70.665977, -33.137558)
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


def _pendientes(actual):
    return json.loads((actual / "decisiones_pendientes.json").read_text(encoding="utf-8"))["decisiones"]


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


def _entorno(tmp_path):
    """Caso real 0000354870/472477, con nombres sintéticos: un vehículo
    (patente `AL1879`) con DOS viajes vecinos recientes ya confirmados por
    TELEMETRIA_GPS en AZA COLINA (`VECINO1`/`VECINO2`) y un tercer
    documento del MISMO vehículo (`TARGET`) cuyo origen todavía no se
    determinó -- exactamente la ambigüedad de origen que 472477 tenía
    (`ORIGEN_GPS_CONFLICTO`, empate sin evidencia real) -- bloqueado,
    además, por un destino documental contaminado (`DESTINO_CONTAMINADO_
    POR_OTRA_SECCION`, mismo detector real que publicó la tarjeta de
    472477). Una guía totalmente ajena (`AMBIG1`, otro cliente/obra/
    patente) tiene un motivo de destino genuinamente sin salida
    (`GEOCODIFICACION_DEMASIADO_GENERICA`) y ninguna decisión publicada
    todavía. Otra guía ajena (`AJENO1`) ya está CONFIRMADA, sin relación
    alguna con nada de lo anterior."""
    raiz = tmp_path / "Atlas"
    catalogos = raiz / "catalogos_privados"
    actual = raiz / "operacion" / "actual"
    (raiz / "reportes").mkdir(parents=True)
    catalogos.mkdir(parents=True)
    actual.mkdir(parents=True)
    for nombre, contenido in {
        "clientes.json": {"version_formato": 1, "clientes": []}, "empresas.json": {}, "vehiculos.json": {},
        "obras_destinos.json": {"version_formato": 1, "obras": [], "relaciones": []},
        "destinos_maestros.json": {"version_formato": 1, "destinos": []},
    }.items():
        (catalogos / nombre).write_text(json.dumps(contenido), encoding="utf-8")

    planta_colina = CatalogoPlantas(catalogos / "plantas.json").crear(
        nombre="AZA COLINA", pais="CHILE", fuente="TEST",
        direccion="RUTA 5", comuna="COLINA", region="RM",
        latitud=COORD_AZA_COLINA.latitud, longitud=COORD_AZA_COLINA.longitud,
        estado_calidad=EstadoCalidad.CONFIRMADA,
    )

    dataset = actual / "analisis_completo_guias.csv"
    filas = [
        _fila_csv(
            numero_guia="VECINO1", numero_transporte="TVECINO1", fecha="17-08-2026",
            cliente="PRODALAM SA", obra_destino="CONSTRUCTORA DON PEDRO LTDA",
            patente_tracto="AL1879", despachar_a_crudo="CAMINO A COLINA 200",
            planta_origen_id=planta_colina.planta_id, planta_origen_nombre="AZA COLINA",
            origen_determinado_por="TELEMETRIA_GPS",
            estado_ruta="RUTA_CALCULADA", distancia_km="10.0", duracion_min="15.0",
        ),
        _fila_csv(
            numero_guia="VECINO2", numero_transporte="TVECINO2", fecha="18-08-2026",
            cliente="PRODALAM SA", obra_destino="CONSTRUCTORA DON PEDRO LTDA",
            patente_tracto="AL1879", despachar_a_crudo="CAMINO A COLINA 250",
            planta_origen_id=planta_colina.planta_id, planta_origen_nombre="AZA COLINA",
            origen_determinado_por="TELEMETRIA_GPS",
            estado_ruta="RUTA_CALCULADA", distancia_km="11.0", duracion_min="16.0",
        ),
        _fila_csv(
            numero_guia="TARGET", numero_transporte="TTARGET", fecha="19-08-2026",
            cliente="PRODALAM SA", obra_destino="CONSTRUCTORA DON PEDRO LTDA",
            patente_tracto="AL1879", despachar_a_crudo="",
            planta_origen_id="", planta_origen_nombre="", origen_determinado_por="",
            estado_ruta="", motivo_ruta="",
            motivos_revision_documento="DESTINO_CONTAMINADO_POR_OTRA_SECCION",
            indicador_revision="REVISAR", estado_documental="REQUIERE_REVISION",
        ),
        _fila_csv(
            numero_guia="AMBIG1", numero_transporte="TAMBIG1", fecha="19-08-2026",
            cliente="OTRO CLIENTE SPA", obra_destino="OTRA OBRA CUALQUIERA",
            patente_tracto="ZZ0000", despachar_a_crudo="CHILE",
            planta_origen_id=planta_colina.planta_id, planta_origen_nombre="AZA COLINA",
            origen_determinado_por="TELEMETRIA_GPS",
            estado_ruta="REQUIERE_REVISION", motivo_ruta="GEOCODIFICACION_DEMASIADO_GENERICA",
        ),
        _fila_csv(
            numero_guia="AJENO1", numero_transporte="TAJENO1", fecha="19-08-2026",
            cliente="CLIENTE TOTALMENTE AJENO SA", obra_destino="OBRA AJENA",
            patente_tracto="XY1234", despachar_a_crudo="AV. SIEMPRE VIVA 742",
            planta_origen_id=planta_colina.planta_id, planta_origen_nombre="AZA COLINA",
            origen_determinado_por="TELEMETRIA_GPS",
            estado_ruta="RUTA_CALCULADA", distancia_km="5.0", duracion_min="9.0",
            indicador_revision="OK", estado_documental="OK", estado_operacional="OK",
        ),
    ]
    _escribir_csv(dataset, filas)

    fila_target = next(f for f in filas if f["numero_guia"] == "TARGET")
    decision = detectar_decision_destino_contaminado_documental(
        archivo="9999999.jpeg", fila=fila_target, carpeta_catalogos=catalogos,
    )
    assert decision is not None
    generar_artefacto(
        ruta_dataset=dataset, carpeta_catalogos=catalogos, decisiones=[decision],
        ruta_salida=actual / "decisiones_pendientes.json",
    )
    return raiz, catalogos, actual, dataset, decision, planta_colina


def _aplicar_decision(raiz, decision):
    return aplicar_decision_obra(
        raiz_atlas=raiz, decision_id=decision["decision_id"], accion="REGISTRAR_DIRECCION",
        direccion_manual=DIRECCION_CONFIRMADA, proveedor_rutas=_proveedor_ruta_confiable(),
    )


# ---------------------------------------------------------------------
# A) REGISTRAR_DIRECCION dispara la batería completa, no sólo el reporte.
# ---------------------------------------------------------------------

def test_a_registrar_direccion_dispara_bateria_completa_no_solo_reporte(tmp_path):
    raiz, catalogos, actual, dataset, decision, planta_colina = _entorno(tmp_path)
    resultado = _aplicar_decision(raiz, decision)
    assert resultado["ok"] is True

    revalidacion = resultado["revalidacion"]
    # Antes del cierre, esta rama sólo llamaba a `generar_reporte_viajes`
    # (resultado_extra["reporte_regenerado"], sin ninguna clave de
    # revalidación) -- ahora debe traer las claves de la batería completa
    # de `revalidar_y_regenerar_reporte`, prueba de que corrió de verdad.
    for clave in (
        "origen_vecinos_temporales_gps", "origen_categoria_sin_candidato",
        "ruta", "indicadores_documentales", "bandeja_republicada",
    ):
        assert clave in revalidacion, f"falta clave de batería completa: {clave}"


# ---------------------------------------------------------------------
# B) evidencia nueva que permite resolución automática (origen por
#    convergencia de vecinos GPS) termina sin decisión humana.
# ---------------------------------------------------------------------

def test_b_origen_se_resuelve_solo_por_vecinos_gps_sin_pedir_decision_humana(tmp_path):
    raiz, catalogos, actual, dataset, decision, planta_colina = _entorno(tmp_path)
    _aplicar_decision(raiz, decision)

    fila_target = _fila_por_guia(dataset, "TARGET")
    # El origen de TARGET nunca tuvo su propia evidencia GPS -- sólo se
    # resuelve porque el MISMO vehículo (AL1879) tiene dos vecinos
    # recientes ya confirmados por telemetría, convergiendo en AZA
    # COLINA -- exactamente el mecanismo que, antes de este cierre, nunca
    # llegaba a ejecutarse en la misma operación que la decisión.
    assert fila_target["planta_origen_id"] == planta_colina.planta_id
    assert fila_target["origen_determinado_por"] == "PATRON_VEHICULO_GPS_VECINOS"
    # Con origen y destino ya resueltos, la ruta también queda calculada
    # en la misma pasada -- nunca hace falta una segunda reconciliación.
    assert fila_target["estado_ruta"] == "RUTA_CALCULADA"

    pendientes = _pendientes(actual)
    # Ninguna decisión ORIGEN_NO_CONFIRMADO se generó para TARGET: la
    # ambigüedad de origen se cerró sola, nunca llegó a convertirse en
    # una pregunta humana.
    assert not any(
        d.get("tipo") == "ORIGEN_NO_CONFIRMADO"
        and (d.get("documento") or {}).get("numero_guia") == "TARGET"
        for d in pendientes
    )
    # Tampoco queda una DESTINO_NO_RESUELTO pendiente para TARGET -- la
    # decisión aplicada ya la resolvió.
    assert not any(
        (d.get("documento") or {}).get("numero_guia") == "TARGET" and d.get("estado") == "PENDIENTE"
        for d in pendientes
    )


# ---------------------------------------------------------------------
# C) una ambigüedad real (de otra guía, no relacionada) sigue generando
#    su propia decisión pendiente.
# ---------------------------------------------------------------------

def test_c_ambiguedad_real_de_otra_guia_regenera_su_propia_decision(tmp_path):
    raiz, catalogos, actual, dataset, decision, planta_colina = _entorno(tmp_path)
    # Antes de aplicar nada: AMBIG1 no tiene ninguna decisión publicada
    # todavía (sólo se publicó la de TARGET, ver `_entorno`).
    pendientes_antes = _pendientes(actual)
    assert not any((d.get("documento") or {}).get("numero_guia") == "AMBIG1" for d in pendientes_antes)

    _aplicar_decision(raiz, decision)

    pendientes_despues = _pendientes(actual)
    decision_ambig = next(
        (
            d for d in pendientes_despues
            if (d.get("documento") or {}).get("numero_guia") == "AMBIG1" and d.get("estado") == "PENDIENTE"
        ),
        None,
    )
    # La batería completa (`detectar_decisiones_destino_no_resuelto_sin_ocr`,
    # dentro de `revalidar_y_regenerar_reporte`) descubre esta ambigüedad
    # real -- totalmente ajena a la decisión que se acaba de aplicar -- y
    # publica su propia tarjeta. Nunca se "resuelve en silencio" lo que
    # sigue siendo, honestamente, una pregunta para un humano.
    assert decision_ambig is not None, "AMBIG1 debería tener una decisión DESTINO_NO_RESUELTO pendiente"
    assert decision_ambig["tipo"] == "DESTINO_NO_RESUELTO"
    # Su propio destino nunca se tocó -- Atlas nunca "arregla" direcciones.
    assert _fila_por_guia(dataset, "AMBIG1")["motivo_ruta"] == "GEOCODIFICACION_DEMASIADO_GENERICA"


# ---------------------------------------------------------------------
# D) reejecutar el flujo sin evidencia nueva es idempotente.
# ---------------------------------------------------------------------

def test_d_reejecutar_sin_evidencia_nueva_es_idempotente(tmp_path):
    raiz, catalogos, actual, dataset, decision, planta_colina = _entorno(tmp_path)
    _aplicar_decision(raiz, decision)

    dataset_antes = dataset.read_bytes()
    decisiones_antes = _pendientes(actual)

    resultado_segunda_pasada = revalidar_y_regenerar_reporte(
        raiz_atlas=raiz, nombre_carpeta_reporte="reporte_segunda_pasada_idempotencia",
    )
    assert resultado_segunda_pasada["guias_actualizadas"] == []
    assert resultado_segunda_pasada["bandeja_cambio_efectivo"] is False
    assert resultado_segunda_pasada["reporte_regenerado"] is False

    assert dataset.read_bytes() == dataset_antes
    # Contenido semántico idéntico -- se ignora `generado_en` (metadato
    # volátil del artefacto, siempre se re-estampa) y se compara por
    # `decision_id`, nunca por el JSON crudo completo.
    assert _pendientes(actual) == decisiones_antes
    assert not (raiz / "reportes" / "reporte_segunda_pasada_idempotencia").exists()


# ---------------------------------------------------------------------
# E) un viaje ajeno al transporte de la decisión queda intacto.
# ---------------------------------------------------------------------

def test_e_viaje_ajeno_no_se_altera(tmp_path):
    raiz, catalogos, actual, dataset, decision, planta_colina = _entorno(tmp_path)
    fila_ajeno_antes = _fila_por_guia(dataset, "AJENO1")

    _aplicar_decision(raiz, decision)

    fila_ajeno_despues = _fila_por_guia(dataset, "AJENO1")
    assert fila_ajeno_despues == fila_ajeno_antes
