"""Bloque R21 -- REFRESCO ESTRUCTURAL DE DECISIONES VIVAS: caso real
472640 (DSI UNDERGROUND CHILE SPA). Una tarjeta `DESTINO_NO_RESUELTO`
originada en `motivos_revision_documento` (DESTINO_CONTAMINADO_POR_
OTRA_SECCION, `detectar_decision_destino_contaminado_documental` --
distinta del camino `motivo_ruta` que ya cubre Bloque RESOLUCIÓN R19,
ver `test_resolucion_r19.py`) seguía mostrando `valor_documental` y
`cliente_canonico` viejos en Revisión de Atlas después de que una
reextracción corrigiera `despachar_a_crudo`/`cliente` en el dataset.

Generaliza R19 (que sólo comparaba `motivo_ruta`) a los DOS orígenes de
`DESTINO_NO_RESUELTO` por igual, comparando el propio `valor_documental`
persistido en la decisión contra el `despachar_a_crudo` VIGENTE de la
fila. `valor_documental` participa del hash de `decision_id` (ver
`_decision_id`) -- por eso, cuando cambia, la tarjeta vieja se DESCARTA y
una fresca la reemplaza con un `decision_id` nuevo (nunca se fuerza a
conservar un ID que ya no representaría la evidencia real). Cuando en
cambio sólo cambian campos de `contexto` (`cliente_canonico`/
`obra_canonica`, que NO participan del hash), la tarjeta se refresca EN
EL MISMO LUGAR conservando su `decision_id` -- exactamente el
comportamiento pedido: "conservar decision_id si corresponde, refrescar
su contexto documental vigente"."""
from __future__ import annotations

import csv

from atlas_core.decisiones_pendientes import (
    crear_decision, detectar_decision_destino_contaminado_documental,
    detectar_decision_destino_no_resuelto, regenerar_decisiones_persistidas,
)
from atlas_core.procesamiento_masivo import COLUMNAS

CAMPO = "despachar_a_crudo"
VALOR_VIEJO = "LAS VIOLETAS"
VALOR_NUEVO = "LAS VIOLETAS 55 SECTOR LA ESPERANZA PADRE HU"


def _catalogos_vacios(tmp_path):
    import json as _json
    carpeta = tmp_path / "catalogos"
    carpeta.mkdir()
    for nombre, contenido in {
        "clientes.json": {"version_formato": 1, "clientes": []},
        "obras_destinos.json": {"version_formato": 1, "obras": [], "relaciones": []},
        "destinos_maestros.json": {"version_formato": 1, "destinos": []},
        "vehiculos.json": {"version": 1, "vehiculos": []},
        "plantas.json": {"version_formato": 1, "plantas": []},
    }.items():
        (carpeta / nombre).write_text(_json.dumps(contenido), encoding="utf-8")
    return carpeta


def _fila_472640(**overrides):
    fila = {c: "" for c in COLUMNAS}
    fila.update({
        "archivo": "mobile/472640/original.jpg", "estado_procesamiento": "OK",
        "numero_guia": "472640", "numero_transporte": "0000355509", "fecha": "26-08-2026",
        "cliente": "DSI UNDERGROUND CHILE SPA", "rut_cliente": "76.083.093-3",
        "obra_destino": "DSI UNDERGROUND CHILE SPA",
        "despachar_a_crudo": VALOR_NUEVO,
        "motivos_revision_documento": "DESTINO_CONTAMINADO_POR_OTRA_SECCION",
        "indicador_revision": "REVISAR", "estado_documental": "REQUIERE_REVISION",
        "estado_ruta": "", "motivo_ruta": "",
    })
    fila.update(overrides)
    return fila


def _escribir_csv(ruta, filas):
    with ruta.open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader()
        escritor.writerows(filas)


def _decision_vieja(*, valor_documental=VALOR_VIEJO, cliente_canonico="No encontrado"):
    return crear_decision(
        tipo="DESTINO_NO_RESUELTO", entidad="DESTINO", archivo="mobile/472640/original.jpg",
        numero_guia="472640", numero_transporte="0000355509", campo=CAMPO,
        valor_documental=valor_documental, valor_normalizado="", identidad_resuelta=None,
        candidatos=(), motivos=["DESTINO_CONTAMINADO_POR_OTRA_SECCION"],
        evidencias=[{
            "tipo": "DESTINO_DOCUMENTAL_CONTAMINADO",
            "motivos": ["DESTINO_CONTAMINADO_POR_OTRA_SECCION"],
            "despachar_a_crudo": valor_documental,
            "estado_ruta": "",
        }],
        acciones_permitidas=("REGISTRAR_DIRECCION", "NO_PUEDO_DETERMINAR", "POSPONER"),
        contexto={"obra_canonica": "DSI UNDERGROUMD CHIL2", "cliente_canonico": cliente_canonico},
    )


def test_valor_documental_desactualizado_descarta_la_tarjeta_vieja_y_publica_una_fresca(tmp_path):
    """Caso real 472640: `valor_documental="LAS VIOLETAS"` ya no coincide
    con el `despachar_a_crudo` vigente -- la tarjeta vieja se descarta (su
    ID ya no representaría la evidencia real) y aparece una fresca con
    `valor_documental`/`cliente_canonico` al día y un `decision_id`
    DISTINTO."""
    carpeta = _catalogos_vacios(tmp_path)
    dataset = tmp_path / "dataset.csv"
    _escribir_csv(dataset, [_fila_472640()])
    vieja = _decision_vieja()

    restantes = regenerar_decisiones_persistidas(
        decisiones=[vieja], carpeta_catalogos=carpeta, ruta_dataset=dataset,
    )

    ids = {d["decision_id"] for d in restantes}
    assert vieja["decision_id"] not in ids
    assert len(restantes) == 1
    fresca = restantes[0]
    assert fresca["valor_documental"] == VALOR_NUEVO
    assert fresca["contexto"]["cliente_canonico"] == "DSI UNDERGROUND CHILE SPA"
    assert fresca["tipo"] == "DESTINO_NO_RESUELTO"


def test_problema_resuelto_no_deja_tarjeta_fantasma(tmp_path):
    """Si además el motivo documental ya no está vigente (destino
    corregido, ya no contaminado), la tarjeta vieja se descarta y NO se
    genera ninguna de reemplazo -- mismo criterio ya probado por R19
    (`test_decision_destino_con_motivo_obsoleto_se_descarta`), ahora
    también para el camino documental."""
    carpeta = _catalogos_vacios(tmp_path)
    dataset = tmp_path / "dataset.csv"
    _escribir_csv(dataset, [_fila_472640(motivos_revision_documento="")])
    vieja = _decision_vieja()

    restantes = regenerar_decisiones_persistidas(
        decisiones=[vieja], carpeta_catalogos=carpeta, ruta_dataset=dataset,
    )
    assert restantes == []


def test_solo_contexto_desactualizado_conserva_decision_id(tmp_path):
    """`valor_documental` YA coincide con la fila (nunca cambió) pero
    `cliente_canonico` quedó viejo en el contexto -- la tarjeta se
    refresca EN EL MISMO LUGAR (mismo `decision_id`, `cliente_canonico`
    puesto al día), porque `contexto` no participa del hash."""
    carpeta = _catalogos_vacios(tmp_path)
    dataset = tmp_path / "dataset.csv"
    _escribir_csv(dataset, [_fila_472640()])
    vieja = _decision_vieja(valor_documental=VALOR_NUEVO, cliente_canonico="No encontrado")

    restantes = regenerar_decisiones_persistidas(
        decisiones=[vieja], carpeta_catalogos=carpeta, ruta_dataset=dataset,
    )

    assert len(restantes) == 1
    refrescada = restantes[0]
    assert refrescada["decision_id"] == vieja["decision_id"]
    assert refrescada["valor_documental"] == VALOR_NUEVO
    assert refrescada["contexto"]["cliente_canonico"] == "DSI UNDERGROUND CHILE SPA"
    assert refrescada["contexto"]["obra_canonica"] == "DSI UNDERGROUND CHILE SPA"


def test_sin_cambios_es_completamente_idempotente(tmp_path):
    """Corrida repetida sobre una tarjeta ya al día: ni el `decision_id`
    ni ningún otro campo cambia entre pasadas -- condición explícita de
    idempotencia pedida para este bloque."""
    carpeta = _catalogos_vacios(tmp_path)
    dataset = tmp_path / "dataset.csv"
    _escribir_csv(dataset, [_fila_472640()])
    vieja = _decision_vieja(valor_documental=VALOR_NUEVO, cliente_canonico="DSI UNDERGROUND CHILE SPA")

    primera = regenerar_decisiones_persistidas(
        decisiones=[vieja], carpeta_catalogos=carpeta, ruta_dataset=dataset,
    )
    segunda = regenerar_decisiones_persistidas(
        decisiones=primera, carpeta_catalogos=carpeta, ruta_dataset=dataset,
    )
    assert primera == segunda


def test_reemplazo_por_valor_desactualizado_es_idempotente_en_pasadas_sucesivas(tmp_path):
    """La MISMA situación real de 472640 (tarjeta vieja + fila ya
    corregida): la primera pasada reemplaza la tarjeta; una segunda
    pasada sobre el resultado de la primera ya no vuelve a cambiar nada
    (la tarjeta fresca ya coincide con la fila) -- nunca genera un
    tercer `decision_id` en bucle."""
    carpeta = _catalogos_vacios(tmp_path)
    dataset = tmp_path / "dataset.csv"
    _escribir_csv(dataset, [_fila_472640()])
    vieja = _decision_vieja()

    primera = regenerar_decisiones_persistidas(
        decisiones=[vieja], carpeta_catalogos=carpeta, ruta_dataset=dataset,
    )
    segunda = regenerar_decisiones_persistidas(
        decisiones=primera, carpeta_catalogos=carpeta, ruta_dataset=dataset,
    )
    assert primera == segunda
    assert len(segunda) == 1
    assert segunda[0]["valor_documental"] == VALOR_NUEVO


def test_decision_motivo_ruta_no_se_ve_afectada_por_el_nuevo_chequeo(tmp_path):
    """Una decisión `DESTINO_NO_RESUELTO` originada por `motivo_ruta`
    (`detectar_decision_destino_no_resuelto`, no la documental) cuyo
    `valor_documental` SÍ sigue coincidiendo con la fila debe sobrevivir
    intacta -- el nuevo chequeo de R21 nunca descarta una tarjeta vigente
    sólo por existir, sólo por divergencia real de valor."""
    from atlas_core.catalogo_plantas import CatalogoPlantas, EstadoCalidad

    carpeta = _catalogos_vacios(tmp_path)
    planta = CatalogoPlantas(carpeta / "plantas.json").crear(
        nombre="AZA COLINA", pais="CHILE", fuente="TEST",
        direccion="RUTA 5", comuna="COLINA", region="RM",
        latitud=-70.669, longitud=-33.201, estado_calidad=EstadoCalidad.CONFIRMADA,
    )
    dataset = tmp_path / "dataset.csv"
    fila = _fila_472640(
        despachar_a_crudo="VICUÑA MACKENNA 655", motivos_revision_documento="",
        planta_origen_id=planta.planta_id, planta_origen_nombre=planta.nombre,
        estado_ruta="REQUIERE_REVISION", motivo_ruta="MULTIPLES_UBICACIONES_DISPERSAS(5)",
    )
    _escribir_csv(dataset, [fila])
    decision = detectar_decision_destino_no_resuelto(archivo="mobile/472640/original.jpg", fila=fila)
    assert decision is not None

    restantes = regenerar_decisiones_persistidas(
        decisiones=[decision], carpeta_catalogos=carpeta, ruta_dataset=dataset,
    )
    assert len(restantes) == 1
    assert restantes[0]["decision_id"] == decision["decision_id"]


def test_detector_documental_produce_valor_documental_ya_alineado_con_la_fila(tmp_path):
    """Control focal: el propio detector (fuente de verdad, sin pasar por
    `regenerar_decisiones_persistidas`) ya fija `valor_documental` desde
    `despachar_a_crudo` -- confirma que el chequeo de R21 compara contra
    el campo correcto."""
    fila = _fila_472640()
    decision = detectar_decision_destino_contaminado_documental(
        archivo="mobile/472640/original.jpg", fila=fila,
    )
    assert decision is not None
    assert decision["campo"] == CAMPO
    assert decision["valor_documental"] == VALOR_NUEVO
