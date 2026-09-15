"""Bloque CORRECCIÓN HUMANA TRANSVERSAL -- caso real 460486: una decisión
DESTINO_NO_RESUELTO con propuesta B1 confirmable (`contexto.b1_propuesta`)
sólo dejaba corregir la comuna/localidad -- si la propuesta de Atlas era
incorrecta (guía 460486: "10833150-K FECHA", un RUT+etiqueta administrativa,
nunca una dirección real), Javier no tenía forma de indicar la dirección
correcta sin editar el dataset a mano.

El backend (`aplicar_decision_obra`/REGISTRAR_DIRECCION) ya soportaba
recibir cualquier `direccion_manual` -- el defecto era exclusivamente que
Desktop (`decisiones_pendientes_ui.js`) nunca exponía un campo editable en
ese camino, dejando la propuesta pre-cargada en una variable sin `<input>`
asociado. Este bloque agrega:
  - trazabilidad explícita del valor anterior (`valor_documental_anterior`/
    `b1_propuesta_anterior`) en el ledger de esta misma aplicación (antes
    sólo se guardaba el valor NUEVO);
  - las pruebas Motor equivalentes al fix de UI (que se prueba aparte en
    Desktop, `decisiones_pendientes.test.js`).

Nunca reabre la investigación de 460486 (causa raíz del cliente/obra ya
cerrada en un bloque previo) -- sólo prueba el mecanismo GENERAL de
corrección con datos con la misma forma."""
from __future__ import annotations

import csv
import json

from atlas_core.aplicacion_decisiones import aplicar_decision_obra
from atlas_core.catalogo_clientes import normalizar_nombre_cliente
from atlas_core.catalogo_obras_destinos import CatalogoObrasDestinos
from atlas_core.catalogo_plantas import CatalogoPlantas, EstadoCalidad
from atlas_core.decisiones_pendientes import crear_decision, generar_artefacto
from atlas_core.procesamiento_masivo import COLUMNAS
from atlas_core.rutas.modelos import (
    CandidatoGeocodificacion, Coordenadas, EstadoRuta, ResultadoGeocodificacion, ResultadoRuta,
)
from atlas_core.rutas.proveedor import ProveedorRutasSimulado

COORD_PLANTA = Coordenadas(-70.665977, -33.137558)
FECHA = "31-07-2026"


def _fila_csv(**overrides):
    fila = {c: "" for c in COLUMNAS}
    fila.update({
        "archivo": "460486.jpeg", "estado_procesamiento": "OK", "numero_guia": "460486",
        "numero_transporte": "0000350638", "fecha": FECHA, "chofer": "JOSE LAZCANO",
        "cliente": "PRODALAM SA", "obra_destino": "PRODALAM SA RENCA",
        "patente_tracto": "AL1879", "indicador_revision": "REVISAR",
        "planta_origen_id": "planta-renca", "planta_origen_nombre": "AZA RENCA",
        "origen_determinado_por": "TELEMETRIA_GPS", "evidencia_origen": "ORIGEN_GPS_CONFIRMADO",
        "despachar_a_crudo": "", "direccion_entrega": "", "estado_entrega": "NO_INTENTADO",
        "distancia_km": "", "duracion_min": "", "proveedor_ruta": "",
        "estado_ruta": "", "motivo_ruta": "",
        "motivos_revision_documento": "DESTINO_CONTAMINADO_POR_OTRA_SECCION",
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


def _entorno(tmp_path, *, filas_csv, clientes=None, obras=None):
    raiz = tmp_path / "Atlas"
    catalogos = raiz / "catalogos_privados"
    actual = raiz / "operacion" / "actual"
    catalogos.mkdir(parents=True)
    actual.mkdir(parents=True)
    for nombre, contenido in {
        "clientes.json": {"version_formato": 1, "clientes": clientes or []},
        "empresas.json": {},
        "vehiculos.json": {"version": 1, "vehiculos": []},
        "obras_destinos.json": {"version_formato": 1, "obras": obras or [], "relaciones": []},
        "destinos_maestros.json": {"version_formato": 1, "destinos": []},
    }.items():
        (catalogos / nombre).write_text(json.dumps(contenido), encoding="utf-8")
    plantas = CatalogoPlantas(catalogos / "plantas.json")
    planta_renca = plantas.crear(
        nombre="AZA RENCA", pais="CHILE", fuente="TEST",
        direccion="LA UNION 3070", comuna="RENCA", region="RM",
        latitud=COORD_PLANTA.latitud, longitud=COORD_PLANTA.longitud,
        estado_calidad=EstadoCalidad.CONFIRMADA,
    )
    for fila in filas_csv:
        if fila.get("planta_origen_id") == "planta-renca":
            fila["planta_origen_id"] = planta_renca.planta_id
    dataset = actual / "analisis_completo_guias.csv"
    _escribir_csv(dataset, filas_csv)
    return {"raiz": raiz, "catalogos": catalogos, "actual": actual, "dataset": dataset}


def _cliente_dict():
    return {
        "cliente_id": "cliente-prodalam", "razon_social": "PRODALAM SA",
        "nombre_normalizado": normalizar_nombre_cliente("PRODALAM SA"), "nombre_comercial": "", "rut": "93772000-9",
        "aliases": [], "estado_calidad": "CONFIRMADO", "estado_vigencia": "ACTIVO", "fuente": "TEST",
        "observacion": "", "fecha_creacion": "2026-01-01T00:00:00+00:00", "fecha_modificacion": "2026-01-01T00:00:00+00:00",
    }


def _obra_dict():
    return {
        "obra_id": "obra-prodalam-renca", "cliente_id": "cliente-prodalam",
        "nombre_canonico": "PRODALAM SA RENCA", "nombre_normalizado": "PRODALAM SA RENCA",
        "aliases_documentales": [], "estado": "OBSERVADA", "estado_vigencia": "ACTIVO", "evidencias": [],
        "fecha_creacion": "2026-01-01T00:00:00+00:00", "fecha_modificacion": "2026-01-01T00:00:00+00:00",
    }


def _decision_con_hallazgo(*, b1_propuesta="10833150-K FECHA"):
    """Misma forma real que la tarjeta de 460486: DESTINO_NO_RESUELTO con
    `despachar_a_crudo` vacío/contaminado y una propuesta B1 confirmable
    que, en el caso real, resultó ser basura (RUT+etiqueta, nunca una
    dirección)."""
    return crear_decision(
        tipo="DESTINO_NO_RESUELTO", entidad="DESTINO", archivo="460486.jpeg",
        numero_guia="460486", numero_transporte="0000350638", campo="despachar_a_crudo",
        valor_documental="", valor_normalizado="", identidad_resuelta=None,
        candidatos=(), motivos=("DESTINO_CONTAMINADO_POR_OTRA_SECCION",),
        evidencias=({
            "tipo": "DESTINO_DOCUMENTAL_CONTAMINADO",
            "motivos": ["DESTINO_CONTAMINADO_POR_OTRA_SECCION"],
            "despachar_a_crudo": "", "estado_ruta": "",
        },),
        acciones_permitidas=("REGISTRAR_DIRECCION", "NO_PUEDO_DETERMINAR", "POSPONER"),
        contexto={
            "obra_canonica": "PRODALAM SA RENCA", "cliente_canonico": "PRODALAM SA",
            "planta_origen_id": "planta-renca",
            "b1_resumen_hallazgo": "Observación documental indica que despachar_a_crudo tiene ese valor literal.",
            "b1_propuesta": b1_propuesta, "b1_evidencia_resumida": "", "b1_fuentes_resumidas": [],
            "b1_motivo_no_autoaplicable": "La evidencia es fuerte, pero Atlas nunca aplica un destino nuevo sin confirmación humana.",
            "b1_pregunta_humana": "¿Confirma que este es el destino correcto?",
        },
    )


def _publicar(entorno, decision):
    generar_artefacto(
        ruta_dataset=entorno["dataset"], carpeta_catalogos=entorno["catalogos"],
        decisiones=[decision], ruta_salida=entorno["actual"] / "decisiones_pendientes.json",
    )


def _proveedor_direccion_valida(direccion):
    # `resolver_destino_entrega_validado` puede ampliar la consulta con la
    # comuna conocida (manual, o inferida sin ambigüedad del propio nombre
    # de obra "PRODALAM SA RENCA") antes de geocodificar -- se registra el
    # resultado bajo AMBAS formas posibles de la consulta para que el
    # stub responda sin depender de cuál de las dos rutas la resolvió.
    candidato = CandidatoGeocodificacion(
        Coordenadas(-70.671, -33.401), direccion + ", Renca, RM, Chile", 1.0,
        "Renca", "Metropolitana",
    )
    resultado = ResultadoGeocodificacion(EstadoRuta.REQUIERE_REVISION, (candidato,), "")
    return ProveedorRutasSimulado(
        geocodificaciones={
            f"{direccion}, Chile": resultado,
            f"{direccion} Renca, Chile": resultado,
            f"{direccion} RENCA, Chile": resultado,
        },
        resultado_ruta=ResultadoRuta(EstadoRuta.RUTA_CALCULADA, 3.1, 9.4, "SINTETICO"),
    )


# ============================================================
# 1. Destino propuesto CORRECTO -> confirmar sigue funcionando
# ============================================================


def test_confirmar_propuesta_correcta_sin_editar_sigue_aplicando_igual_que_antes(tmp_path):
    entorno = _entorno(
        tmp_path, filas_csv=[_fila_csv()], clientes=[_cliente_dict()], obras=[_obra_dict()],
    )
    direccion_correcta = "ALBERTO PEPPER 1610"
    decision = _decision_con_hallazgo(b1_propuesta=direccion_correcta)
    _publicar(entorno, decision)

    # Javier no edita nada -- Desktop sigue enviando la propuesta tal cual
    # como `direccion_manual` (mismo contrato de siempre).
    resultado = aplicar_decision_obra(
        raiz_atlas=entorno["raiz"], decision_id=decision["decision_id"],
        accion="REGISTRAR_DIRECCION", direccion_manual=direccion_correcta,
        comuna_manual="RENCA", proveedor_rutas=_proveedor_direccion_valida(direccion_correcta),
    )
    assert resultado["ok"] is True
    assert resultado["ruta_resuelta"] is True

    fila = _leer_csv(entorno["dataset"])[0]
    assert fila["despachar_a_crudo"] == direccion_correcta
    assert fila["estado_ruta"] == "RUTA_CALCULADA"

    bandeja = json.loads((entorno["actual"] / "decisiones_pendientes.json").read_text(encoding="utf-8"))
    assert bandeja["decisiones"] == []


# ============================================================
# 2. Destino propuesto INCORRECTO -> dirección+comuna corregidas persisten
# ============================================================


def test_corregir_propuesta_incorrecta_persiste_la_correccion_no_la_propuesta(tmp_path):
    entorno = _entorno(
        tmp_path, filas_csv=[_fila_csv()], clientes=[_cliente_dict()], obras=[_obra_dict()],
    )
    propuesta_basura = "10833150-K FECHA"
    decision = _decision_con_hallazgo(b1_propuesta=propuesta_basura)
    _publicar(entorno, decision)

    direccion_real = "ALBERTO PEPPER 1610"
    resultado = aplicar_decision_obra(
        raiz_atlas=entorno["raiz"], decision_id=decision["decision_id"],
        accion="REGISTRAR_DIRECCION", direccion_manual=direccion_real,
        comuna_manual="RENCA", proveedor_rutas=_proveedor_direccion_valida(direccion_real),
    )
    assert resultado["ok"] is True

    fila = _leer_csv(entorno["dataset"])[0]
    # La corrección -- nunca la propuesta descartada -- es lo que queda
    # como valor canónico operacional.
    assert fila["despachar_a_crudo"] == direccion_real
    assert propuesta_basura not in fila["despachar_a_crudo"]
    assert fila["localidad_entrega"] == "RENCA"


# ============================================================
# 3. La corrección dispara routing/reconciliación (km/tiempo recalculados)
# ============================================================


def test_correccion_dispara_recalculo_de_ruta_km_y_tiempo(tmp_path):
    entorno = _entorno(
        tmp_path, filas_csv=[_fila_csv()], clientes=[_cliente_dict()], obras=[_obra_dict()],
    )
    decision = _decision_con_hallazgo()
    _publicar(entorno, decision)

    direccion_real = "ALBERTO PEPPER 1610"
    resultado = aplicar_decision_obra(
        raiz_atlas=entorno["raiz"], decision_id=decision["decision_id"],
        accion="REGISTRAR_DIRECCION", direccion_manual=direccion_real,
        comuna_manual="RENCA", proveedor_rutas=_proveedor_direccion_valida(direccion_real),
    )
    assert resultado["ok"] is True
    assert resultado["ruta_resuelta"] is True

    fila = _leer_csv(entorno["dataset"])[0]
    assert fila["distancia_km"] == "3.1"
    assert fila["duracion_min"] == "9.4"
    assert fila["estado_ruta"] == "RUTA_CALCULADA"

    catalogo_obras = CatalogoObrasDestinos(
        ruta=entorno["catalogos"] / "obras_destinos.json",
        ruta_clientes=entorno["catalogos"] / "clientes.json",
        ruta_destinos=entorno["catalogos"] / "destinos_maestros.json",
    )
    assert catalogo_obras.resolver_obra_destino_confirmada_global(
        nombre_obra="PRODALAM SA RENCA"
    ) is not None


# ============================================================
# 4. El valor anterior (propuesta/OCR) queda trazable
# ============================================================


def test_valor_anterior_queda_trazable_en_el_ledger(tmp_path):
    entorno = _entorno(
        tmp_path, filas_csv=[_fila_csv()], clientes=[_cliente_dict()], obras=[_obra_dict()],
    )
    propuesta_basura = "10833150-K FECHA"
    decision = _decision_con_hallazgo(b1_propuesta=propuesta_basura)
    _publicar(entorno, decision)

    direccion_real = "ALBERTO PEPPER 1610"
    resultado = aplicar_decision_obra(
        raiz_atlas=entorno["raiz"], decision_id=decision["decision_id"],
        accion="REGISTRAR_DIRECCION", direccion_manual=direccion_real,
        comuna_manual="RENCA", proveedor_rutas=_proveedor_direccion_valida(direccion_real),
    )
    assert resultado["ok"] is True

    ledger = json.loads((entorno["actual"] / "decisiones_aplicadas.json").read_text(encoding="utf-8"))
    aplicacion = next(a for a in ledger["aplicaciones"] if a["decision_id"] == decision["decision_id"])
    assert aplicacion["direccion_manual"] == direccion_real
    assert aplicacion["b1_propuesta_anterior"] == propuesta_basura


# ============================================================
# 5. 460486 se resuelve íntegramente desde el flujo humano normal
# ============================================================


def test_460486_se_resuelve_integramente_via_aplicar_decision_obra_sin_tocar_dataset_a_mano(tmp_path):
    """Misma forma que la tarjeta real de 460486 (obra/cliente ya
    resueltos, destino con propuesta B1 basura) -- se resuelve por completo
    llamando SÓLO la función oficial que Desktop invoca al aplicar una
    decisión (la misma que ejecuta `aplicar_decision_pendiente.py`), nunca
    editando el CSV/JSON directamente."""
    entorno = _entorno(
        tmp_path, filas_csv=[_fila_csv()], clientes=[_cliente_dict()], obras=[_obra_dict()],
    )
    decision = _decision_con_hallazgo(b1_propuesta="10833150-K FECHA")
    _publicar(entorno, decision)

    resultado = aplicar_decision_obra(
        raiz_atlas=entorno["raiz"], decision_id=decision["decision_id"],
        accion="REGISTRAR_DIRECCION", direccion_manual="ALBERTO PEPPER 1610",
        comuna_manual="RENCA", proveedor_rutas=_proveedor_direccion_valida("ALBERTO PEPPER 1610"),
    )
    assert resultado["ok"] is True
    assert resultado["ruta_resuelta"] is True

    fila = _leer_csv(entorno["dataset"])[0]
    assert fila["cliente"] == "PRODALAM SA"
    assert fila["obra_destino"] == "PRODALAM SA RENCA"
    assert fila["despachar_a_crudo"] == "ALBERTO PEPPER 1610"
    assert fila["estado_ruta"] == "RUTA_CALCULADA"

    bandeja = json.loads((entorno["actual"] / "decisiones_pendientes.json").read_text(encoding="utf-8"))
    assert bandeja["decisiones"] == [], "la tarjeta debe retirarse automáticamente al quedar resuelta"


# ============================================================
# 6. No regresión: confirmar sin propuesta B1 (camino histórico) intacto
# ============================================================


def test_no_regresion_registrar_direccion_manual_sin_propuesta_b1(tmp_path):
    entorno = _entorno(
        tmp_path, filas_csv=[_fila_csv()], clientes=[_cliente_dict()], obras=[_obra_dict()],
    )
    decision = crear_decision(
        tipo="DESTINO_NO_RESUELTO", entidad="DESTINO", archivo="460486.jpeg",
        numero_guia="460486", numero_transporte="0000350638", campo="despachar_a_crudo",
        valor_documental="", valor_normalizado="", identidad_resuelta=None,
        candidatos=(), motivos=("DESTINO_SIN_DATO",),
        evidencias=({"tipo": "DESTINO_SIN_DATO"},),
        acciones_permitidas=("REGISTRAR_DIRECCION", "NO_PUEDO_DETERMINAR", "POSPONER"),
        contexto={"obra_canonica": "PRODALAM SA RENCA", "cliente_canonico": "PRODALAM SA"},
    )
    _publicar(entorno, decision)

    direccion = "ALBERTO PEPPER 1610"
    resultado = aplicar_decision_obra(
        raiz_atlas=entorno["raiz"], decision_id=decision["decision_id"],
        accion="REGISTRAR_DIRECCION", direccion_manual=direccion,
        proveedor_rutas=_proveedor_direccion_valida(direccion),
    )
    assert resultado["ok"] is True
    assert resultado["ruta_resuelta"] is True
    fila = _leer_csv(entorno["dataset"])[0]
    assert fila["despachar_a_crudo"] == direccion
