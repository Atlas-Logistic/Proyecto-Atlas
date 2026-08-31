"""Bloque P1, Parte B -- RESOLUCIÓN REACTIVA DE DEPENDENCIAS cuando una
decisión humana se confirma.

Auditoría (Fase 1, punto 6): el mecanismo GENERAL ya existía antes de
P1 -- `aplicar_decision_obra` dispara `revalidar_ruta_sin_destino_
calculado_sin_ocr` inline para DESTINO_NO_RESUELTO/REGISTRAR_DIRECCION,
y termina SIEMPRE regenerando el reporte oficial (`revalidar_y_
regenerar_reporte`/`generar_reporte_viajes` + `escribir_estado_
operacion`) para CUALQUIER decisión que cierre (comentario "Bloque R10"
en `aplicacion_decisiones.py`: "cubre obra/cliente/destino/vehículo/
alias hoy y cualquier tipo de decisión nuevo mañana, sin volver a tocar
esta lista"). P1 no reconstruye esto -- lo demuestra end-to-end, tal
como pide el bloque, usando el proveedor de rutas inyectable/fake ya
existente (`ProveedorRutasSimulado`)."""
from __future__ import annotations

import csv
import json

from atlas_core.aplicacion_decisiones import aplicar_decision_obra
from atlas_core.catalogo_plantas import CatalogoPlantas, EstadoCalidad
from atlas_core.decisiones_pendientes import (
    crear_decision, detectar_decision_destino_no_resuelto, generar_artefacto,
)
from atlas_core.procesamiento_masivo import COLUMNAS
from atlas_core.rutas.modelos import (
    CandidatoGeocodificacion, Coordenadas, EstadoRuta, ResultadoGeocodificacion, ResultadoRuta,
)
from atlas_core.rutas.proveedor import ProveedorRutasSimulado

COORD_AZA_COLINA = Coordenadas(-70.665977, -33.137558)
FECHA = "26-08-2026"


def _fila_csv(**overrides):
    fila = {c: "" for c in COLUMNAS}
    fila.update({
        "archivo": "900001.jpeg", "estado_procesamiento": "OK", "numero_guia": "900001",
        "numero_transporte": "0000900001", "fecha": FECHA, "chofer": "CHOFER DE PRUEBA",
        "cliente": "COMERCIAL PRUEBA SPA", "obra_destino": "OBRA DE PRUEBA CENTRAL",
        "patente_tracto": "AB1234", "indicador_revision": "OK",
        "planta_origen_id": "planta-colina", "planta_origen_nombre": "AZA COLINA",
        "origen_determinado_por": "CONFIRMACION_HUMANA", "evidencia_origen": "DECISION_HUMANA:x",
        "despachar_a_crudo": "", "direccion_entrega": "", "estado_entrega": "SIN_DATO",
        "distancia_km": "", "duracion_min": "", "proveedor_ruta": "",
        "estado_ruta": "REQUIERE_REVISION", "motivo_ruta": "DESTINO_SIN_DATO",
        "motivos_revision_documento": "",
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


def _entorno(tmp_path, *, filas_csv):
    raiz = tmp_path / "Atlas"
    catalogos = raiz / "catalogos_privados"
    actual = raiz / "operacion" / "actual"
    catalogos.mkdir(parents=True)
    actual.mkdir(parents=True)
    for nombre, contenido in {
        "clientes.json": {"version_formato": 1, "clientes": []},
        "empresas.json": {},
        "vehiculos.json": {"version": 1, "vehiculos": []},
        "obras_destinos.json": {"version_formato": 1, "obras": [], "relaciones": []},
        "destinos_maestros.json": {"version_formato": 1, "destinos": []},
    }.items():
        (catalogos / nombre).write_text(json.dumps(contenido), encoding="utf-8")
    planta_colina = CatalogoPlantas(catalogos / "plantas.json").crear(
        nombre="AZA COLINA", pais="CHILE", fuente="TEST",
        direccion="AV EJEMPLO 1", comuna="COLINA", region="RM",
        latitud=COORD_AZA_COLINA.latitud, longitud=COORD_AZA_COLINA.longitud,
        estado_calidad=EstadoCalidad.CONFIRMADA,
    )
    # El sentinela "planta-colina" en las filas dadas se reescribe con el
    # id REAL recién generado (mismo criterio ya usado en
    # test_destino_no_resuelto_r6.py) -- sin esto, `planta_origen_id` no
    # resuelve contra el catálogo real y el resto de la cadena (incluida
    # la consulta de geocodificación) nunca llega a ejecutarse.
    for fila in filas_csv:
        if fila.get("planta_origen_id") == "planta-colina":
            fila["planta_origen_id"] = planta_colina.planta_id
    dataset = actual / "analisis_completo_guias.csv"
    _escribir_csv(dataset, filas_csv)
    return {"raiz": raiz, "catalogos": catalogos, "actual": actual, "dataset": dataset}


def _proveedor_direccion_valida(direccion):
    consulta = f"{direccion}, Chile"
    return ProveedorRutasSimulado(
        geocodificaciones={
            consulta: ResultadoGeocodificacion(
                EstadoRuta.REQUIERE_REVISION,
                (CandidatoGeocodificacion(
                    Coordenadas(-70.634933, -33.436723), direccion + ", Santiago, RM, Chile", 1.0,
                    "Santiago", "Metropolitana",
                ),),
                "",
            )
        },
        resultado_ruta=ResultadoRuta(EstadoRuta.RUTA_CALCULADA, 25.4, 38.2, "SINTETICO"),
    )


def test_destino_confirmado_recalcula_km_tiempo_viaje_y_retira_la_revision_sin_comando_manual(tmp_path):
    """Caso crítico DESTINO -> KM, extremo a extremo, sin ejecutar NADA
    manual entre "usuario confirma destino" y "KM/tiempo/viaje al día":

    1. documento con destino no confirmado (DESTINO_SIN_DATO) -- ya en
       el fixture inicial;
    2. KM/tiempo pendientes -- confirmado abajo, antes de aplicar nada;
    3. usuario confirma destino (`aplicar_decision_obra(REGISTRAR_
       DIRECCION)`) -- LA ÚNICA llamada de esta prueba;
    4. sin ningún comando adicional: destino queda operativo, routing
       se calcula, KM aparece, tiempo aparece, el reporte de viajes se
       regenera con esos valores, y la decisión desaparece de la
       bandeja -- todo verificado abajo, todo producto de esa única
       llamada."""
    fila_pendiente = _fila_csv()
    otra_decision_no_relacionada = crear_decision(
        tipo="CLIENTE_AUSENTE", entidad="CLIENTE",
        archivo="900002.jpeg", numero_guia="900002", numero_transporte="0000900002",
        campo="cliente", valor_documental="", valor_normalizado="",
        identidad_resuelta=None, candidatos=[], evidencias=[],
        motivos=["CLIENTE_AUSENTE"], acciones_permitidas=["REGISTRAR_CLIENTE_MANUAL", "NO_PUEDO_DETERMINAR", "POSPONER"],
    )
    entorno = _entorno(tmp_path, filas_csv=[fila_pendiente])

    # 1/2: destino no confirmado -> KM/tiempo pendientes (verificado ANTES
    # de tocar nada).
    fila_antes = _leer_csv(entorno["dataset"])[0]
    assert fila_antes["estado_ruta"] == "REQUIERE_REVISION"
    assert fila_antes["distancia_km"] == ""
    assert fila_antes["duracion_min"] == ""

    decision = detectar_decision_destino_no_resuelto(archivo="900001.jpeg", fila=fila_pendiente)
    assert decision is not None
    generar_artefacto(
        ruta_dataset=entorno["dataset"], carpeta_catalogos=entorno["catalogos"],
        decisiones=[decision, otra_decision_no_relacionada],
        ruta_salida=entorno["actual"] / "decisiones_pendientes.json",
    )
    bandeja_antes = json.loads((entorno["actual"] / "decisiones_pendientes.json").read_text(encoding="utf-8"))
    assert {d["decision_id"] for d in bandeja_antes["decisiones"]} == {
        decision["decision_id"], otra_decision_no_relacionada["decision_id"],
    }

    # 3: EL USUARIO CONFIRMA EL DESTINO -- única acción manual de la prueba.
    direccion = "AVENIDA APOQUINDO 1234"
    resultado = aplicar_decision_obra(
        raiz_atlas=entorno["raiz"], decision_id=decision["decision_id"],
        accion="REGISTRAR_DIRECCION", direccion_manual=direccion,
        proveedor_rutas=_proveedor_direccion_valida(direccion),
    )
    assert resultado["ok"] is True

    # 4a: destino operativo + routing calculado + KM + tiempo -- sin OCR,
    # sin ningún otro comando.
    fila_despues = _leer_csv(entorno["dataset"])[0]
    assert fila_despues["despachar_a_crudo"] == direccion
    assert fila_despues["estado_ruta"] == "RUTA_CALCULADA"
    assert fila_despues["distancia_km"] == "25.4"
    assert fila_despues["duracion_min"] == "38.2"

    # 4b: el reporte oficial de VIAJES ya quedó regenerado con esos
    # valores -- Desktop puede mostrarlo de inmediato, sin revalidación
    # manual adicional.
    from pathlib import Path

    estado_operacion = json.loads((entorno["actual"] / "estado_operacion.json").read_text(encoding="utf-8"))
    ruta_reporte = Path(estado_operacion["reporte_vigente"])
    if not ruta_reporte.is_absolute():
        ruta_reporte = entorno["raiz"] / ruta_reporte
    viajes = _leer_csv(ruta_reporte / "viajes.csv")
    viaje = next(v for v in viajes if v["numero_transporte"] == "0000900001")
    assert viaje["distancia_km"] == "25.4"
    assert viaje["duracion_min"] == "38.2"
    assert viaje["estado_ruta"] == "RUTA_CALCULADA"
    assert viaje["motivo_ruta"] == ""  # el motivo de bloqueo ya no aparece.
    assert viaje["estado"] == "CONFIRMADO"  # el viaje nunca estuvo bloqueado por otra causa.

    # 8: la decisión ya resuelta desaparece de la bandeja.
    bandeja_despues = json.loads((entorno["actual"] / "decisiones_pendientes.json").read_text(encoding="utf-8"))
    ids_restantes = {d["decision_id"] for d in bandeja_despues["decisiones"]}
    assert decision["decision_id"] not in ids_restantes

    # 9: la OTRA decisión pendiente (sin relación con ésta) permanece intacta.
    assert otra_decision_no_relacionada["decision_id"] in ids_restantes
    otra_tras = next(d for d in bandeja_despues["decisiones"] if d["decision_id"] == otra_decision_no_relacionada["decision_id"])
    assert otra_tras["estado"] == "PENDIENTE"
    assert otra_tras["campo"] == "cliente"
