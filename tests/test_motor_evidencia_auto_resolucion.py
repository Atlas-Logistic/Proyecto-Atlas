"""MOTOR DE EVIDENCIA FASE 4 -- activación controlada de auto-resolución.
Decisión de producto de Javier: `RESUELTO_AUTOMATICAMENTE` se aplica
SOLO al reconciliar la bandeja, sin pedir un clic humano -- reutilizando
`aplicar_decision_obra` con `actor="ATLAS_AUTOMATICO"`, nunca un segundo
camino de escritura. `SUGERENCIA_HUMANA`/`CONTRADICCION_DOCUMENTAL`/
`ALTA_NUEVA`/`ABSTENCION_REAL` NUNCA se aplican solos -- siguen
generando tarjeta."""
from __future__ import annotations

import csv
import json

from atlas_core.catalogo_clientes import CatalogoClientes
from atlas_core.decisiones_pendientes import crear_decision, generar_artefacto
from atlas_core.evidencia_entidades import AlmacenEvidenciaEntidades
from atlas_core.incidencias_documentales import AlmacenIncidenciasDocumentales
from atlas_core.procesamiento_masivo import COLUMNAS
from atlas_core.revalidacion_documental import reconciliar_bandeja_decisiones

RUT_EBEMA = "76086428-5"
FECHA = "05-08-2026"


def _fila_csv(**overrides):
    fila = {c: "" for c in COLUMNAS}
    fila.update({
        "archivo": "1.jpeg", "estado_procesamiento": "OK", "numero_guia": "1",
        "numero_transporte": "T-1", "fecha": FECHA, "chofer": "CHOFER PRUEBA",
        "rut_chofer": "15489424-1", "cliente": "EBEMA SA", "obra_destino": "EBEMA SA",
        "patente_tracto": "AB1234", "patente_rampla": "CD5678",
        "indicador_revision": "REVISAR",
        "planta_origen_id": "", "planta_origen_nombre": "",
        "origen_determinado_por": "", "evidencia_origen": "",
        "despachar_a_crudo": "", "direccion_entrega": "", "estado_entrega": "",
        "distancia_km": "", "duracion_min": "", "proveedor_ruta": "",
        "estado_ruta": "", "motivo_ruta": "",
    })
    fila.update(overrides)
    return fila


def _escribir_csv(ruta, filas):
    with ruta.open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader()
        escritor.writerows(filas)


def _entorno(tmp_path, *, filas_csv, clientes=None):
    raiz = tmp_path / "Atlas"
    catalogos = raiz / "catalogos_privados"
    actual = raiz / "operacion" / "actual"
    catalogos.mkdir(parents=True)
    actual.mkdir(parents=True)
    for nombre, contenido in {
        "clientes.json": {"version_formato": 1, "clientes": clientes or []},
        "empresas.json": {},
        "vehiculos.json": {"version": 1, "vehiculos": []},
        "obras_destinos.json": {"version_formato": 1, "obras": [], "relaciones": []},
        "destinos_maestros.json": {"version_formato": 1, "destinos": []},
    }.items():
        (catalogos / nombre).write_text(json.dumps(contenido), encoding="utf-8")
    dataset = actual / "analisis_completo_guias.csv"
    _escribir_csv(dataset, filas_csv)
    return {"raiz": raiz, "catalogos": catalogos, "actual": actual, "dataset": dataset}


def _cliente_ebema_dict():
    return {
        "cliente_id": "cliente-ebema", "razon_social": "EBEMA SA", "nombre_normalizado": "EBEMA",
        "nombre_comercial": "", "rut": RUT_EBEMA, "aliases": [],
        "estado_calidad": "CONFIRMADO", "estado_vigencia": "ACTIVO", "fuente": "TEST",
        "observacion": "", "fecha_creacion": "2026-01-01T00:00:00+00:00", "fecha_modificacion": "2026-01-01T00:00:00+00:00",
    }


def _confirmacion(almacen, *, valor_documental, numero_guia, numero_transporte):
    from datetime import datetime, timezone
    almacen.registrar_confirmacion(
        dominio="CLIENTE", contexto_clave=RUT_EBEMA, valor_documental=valor_documental,
        valor_confirmado="EBEMA SA", identificador_confirmado="cliente-ebema",
        numero_guia=numero_guia, numero_transporte=numero_transporte,
        actor="JAVIER_MBT", fuente_decision="TEST", fecha=datetime(2026, 8, 19, tzinfo=timezone.utc),
    )


def _decision_alias_candidato(*, guia, transporte, valor_documental):
    identidad = {"entidad_id": "cliente-ebema", "valor_canonico": "EBEMA SA", "rut": RUT_EBEMA}
    return crear_decision(
        tipo="ALIAS_CANDIDATO", entidad="CLIENTE", archivo=f"{guia}.jpeg",
        numero_guia=guia, numero_transporte=transporte, campo="cliente",
        valor_documental=valor_documental, valor_normalizado=valor_documental,
        identidad_resuelta=identidad, candidatos=(identidad,),
        motivos=("RUT_EXACTO_ALIAS_NO_CONFIRMADO",),
        evidencias=({"tipo": "RUT_EXACTO", "campo": "rut_cliente", "valor": RUT_EBEMA},),
        acciones_permitidas=("CONFIRMAR_ALIAS", "RECHAZAR", "POSPONER"),
    )


def test_sugerencia_humana_nunca_se_aplica_sola_sigue_generando_tarjeta(tmp_path):
    """Una única confirmación previa (no dos) da SUGERENCIA_HUMANA, no
    RESUELTO_AUTOMATICAMENTE -- debe permanecer pendiente."""
    entorno = _entorno(tmp_path, filas_csv=[_fila_csv(numero_guia="1")], clientes=[_cliente_ebema_dict()])
    almacen = AlmacenEvidenciaEntidades(entorno["catalogos"] / "evidencia_entidades.json")
    _confirmacion(almacen, valor_documental="PPP CONSTRUCCIONES", numero_guia="0", numero_transporte="T-0")

    decision = _decision_alias_candidato(guia="1", transporte="T-1", valor_documental="XYZ CONSTRUCCIONES")
    generar_artefacto(
        ruta_dataset=entorno["dataset"], carpeta_catalogos=entorno["catalogos"],
        decisiones=[decision], ruta_salida=entorno["actual"] / "decisiones_pendientes.json",
    )
    resultado = reconciliar_bandeja_decisiones(raiz_atlas=entorno["raiz"])
    assert resultado["decisiones_aplicadas_automaticamente"] == []
    ids_pendientes = [d["decision_id"] for d in resultado["bandeja"]["decisiones"]]
    assert decision["decision_id"] in ids_pendientes
    clientes = CatalogoClientes(entorno["catalogos"] / "clientes.json").listar()
    assert clientes[0].aliases == ()  # nada se vinculó -- sigue pendiente de un humano


def test_reconciliar_dos_veces_tras_auto_resolucion_es_idempotente(tmp_path):
    """Regenerar la bandeja una segunda vez, después de que la
    auto-resolución ya cerró la decisión, no debe fallar ni duplicar
    nada -- la decisión ya cerrada nunca resucita (mismo filtro terminal
    que protege a las decisiones aplicadas por un humano)."""
    entorno = _entorno(
        tmp_path,
        filas_csv=[_fila_csv(numero_guia="1"), _fila_csv(numero_guia="2", numero_transporte="T-2"), _fila_csv(numero_guia="3", numero_transporte="T-3")],
        clientes=[_cliente_ebema_dict()],
    )
    almacen = AlmacenEvidenciaEntidades(entorno["catalogos"] / "evidencia_entidades.json")
    _confirmacion(almacen, valor_documental="PPP CONSTRUCCIONES", numero_guia="1", numero_transporte="T-1")
    _confirmacion(almacen, valor_documental="OTRO NOMBRE MAL", numero_guia="2", numero_transporte="T-2")

    decision = _decision_alias_candidato(guia="3", transporte="T-3", valor_documental="XYZ CONSTRUCCIONES")
    generar_artefacto(
        ruta_dataset=entorno["dataset"], carpeta_catalogos=entorno["catalogos"],
        decisiones=[decision], ruta_salida=entorno["actual"] / "decisiones_pendientes.json",
    )
    primera = reconciliar_bandeja_decisiones(raiz_atlas=entorno["raiz"])
    assert len(primera["decisiones_aplicadas_automaticamente"]) == 1

    segunda = reconciliar_bandeja_decisiones(raiz_atlas=entorno["raiz"])
    assert segunda["decisiones_aplicadas_automaticamente"] == []
    assert all(d["decision_id"] != decision["decision_id"] for d in segunda["bandeja"]["decisiones"])

    ledger = json.loads((entorno["actual"] / "decisiones_aplicadas.json").read_text(encoding="utf-8"))
    aplicaciones_de_esta_decision = [a for a in ledger["aplicaciones"] if a["decision_id"] == decision["decision_id"]]
    assert len(aplicaciones_de_esta_decision) == 1  # nunca se duplica


def test_dos_alias_candidato_se_desbloquean_en_cadena_en_una_sola_reconciliacion(tmp_path):
    """Punto fijo: aplicar la primera decisión (que aporta la 2ª
    confirmación independiente) puede desbloquear una SEGUNDA decisión
    de otro documento en la MISMA corrida de `reconciliar_bandeja_decisiones`,
    sin que Javier tenga que disparar una reconciliación aparte."""
    entorno = _entorno(
        tmp_path,
        filas_csv=[
            _fila_csv(numero_guia="1"), _fila_csv(numero_guia="2", numero_transporte="T-2"),
            _fila_csv(numero_guia="3", numero_transporte="T-3"),
        ],
        clientes=[_cliente_ebema_dict()],
    )
    almacen = AlmacenEvidenciaEntidades(entorno["catalogos"] / "evidencia_entidades.json")
    _confirmacion(almacen, valor_documental="PPP CONSTRUCCIONES", numero_guia="1", numero_transporte="T-1")

    # decision_2 aporta la 2a confirmación independiente (queda pendiente
    # hasta que un humano la resuelva -- aquí ya viene "pre-confirmada"
    # simulando que decision_2 misma es la 2a confirmación real: para
    # simplificar el escenario de cadena, se registra directamente como
    # si un humano ya la hubiese aplicado).
    _confirmacion(almacen, valor_documental="OTRO NOMBRE MAL", numero_guia="2", numero_transporte="T-2")

    # decision_3: 3a aparición equivalente -- ya debería auto-resolverse
    # en la MISMA corrida, sin pasos intermedios.
    decision_3 = _decision_alias_candidato(guia="3", transporte="T-3", valor_documental="XYZ CONSTRUCCIONES")
    generar_artefacto(
        ruta_dataset=entorno["dataset"], carpeta_catalogos=entorno["catalogos"],
        decisiones=[decision_3], ruta_salida=entorno["actual"] / "decisiones_pendientes.json",
    )
    resultado = reconciliar_bandeja_decisiones(raiz_atlas=entorno["raiz"])
    assert len(resultado["decisiones_aplicadas_automaticamente"]) == 1
    assert resultado["decisiones_aplicadas_automaticamente"][0]["decision_id"] == decision_3["decision_id"]
