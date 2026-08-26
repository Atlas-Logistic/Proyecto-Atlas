"""Bloque VEHÍCULO E2 -- FIX DE AUTONOMÍA: una patente OCR con un error
menor no debe escalar a Javier si Atlas ya puede identificar la
canónica sin ambigüedad, cruzando confirmación humana o corroboración
documental independiente del chofer con similitud OCR calibrada.

Caso real que motivó este bloque -- guía 472339, Cristopher Retamal
(RUT 17576134-9): OCR leyó "BPHF67"; el chofer tiene dos transportes
independientes previos con "BPHR67" ya confirmada/activa en catálogo;
F/R es una confusión OCR calibrada (agregada a
`atlas_core.catalogo_vehiculos._CONFUSIONES_OCR` con evidencia real de
este caso). Antes de este bloque, `NIVEL_DOCUMENTAL_INDEPENDIENTE`
nunca alcanzaba `RESUELTO_AUTOMATICAMENTE` por sí solo -- sólo
`CONFIRMACION_HUMANA` lo hacía -- así que esta patente quedaba siempre
en `SUGERENCIA_HUMANA`, generando una tarjeta para Javier aunque no
hubiera ningún candidato competidor.

Los tests de este archivo usan patentes y confusiones OCR sintéticas
(nunca "BPHF67"/"BPHR67" ni el chofer real) para probar la regla
GENERAL, más un test end-to-end que reproduce la estructura exacta del
caso real 472339 con valores sintéticos."""
from __future__ import annotations

import csv
import json
from datetime import datetime, timezone

from atlas_core.catalogo_vehiculos import TipoVehiculo, cargar_catalogo_vehiculos, confirmar_vehiculo
from atlas_core.decisiones_pendientes import (
    crear_decision,
    evaluar_evidencia_patente,
    generar_artefacto,
)
from atlas_core.procesamiento_masivo import COLUMNAS, MotivoRevisionDocumento
from atlas_core.revalidacion_documental import (
    reconciliar_bandeja_decisiones,
    revalidar_patente_sin_homologar_sin_ocr,
)

RUT_CHOFER = "15489424-1"
FECHA = "05-08-2026"


def _fila_csv(**overrides):
    fila = {c: "" for c in COLUMNAS}
    fila.update({
        "archivo": "1.jpeg", "estado_procesamiento": "OK", "numero_guia": "1",
        "numero_transporte": "T-1", "fecha": FECHA, "chofer": "CHOFER PRUEBA",
        "rut_chofer": RUT_CHOFER, "cliente": "CLIENTE PRUEBA", "obra_destino": "OBRA PRUEBA",
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
    dataset = actual / "analisis_completo_guias.csv"
    _escribir_csv(dataset, filas_csv)
    return {"raiz": raiz, "catalogos": catalogos, "actual": actual, "dataset": dataset}


def _confirmar(catalogos, patente, tipo):
    return confirmar_vehiculo(
        catalogos / "vehiculos.json", patente=patente, tipo=tipo,
        actor="JAVIER_MBT", fuente_decision="PREVIA", fecha=datetime.now(timezone.utc),
    )


def _decision_vehiculo(*, guia, campo, valor_documental, transporte="T-3"):
    return crear_decision(
        tipo="VEHICULO_DESCONOCIDO", entidad="VEHICULO", archivo=f"{guia}.jpeg",
        numero_guia=guia, numero_transporte=transporte, campo=campo,
        valor_documental=valor_documental, valor_normalizado=valor_documental,
        identidad_resuelta=None, candidatos=(),
        motivos=("SIN_VEHICULO_CONFIRMADO_COMPATIBLE",),
        evidencias=({"tipo": "OCR_DOCUMENTAL", "campo": campo, "valor": valor_documental},),
        acciones_permitidas=("REGISTRAR", "NO_REGISTRAR", "POSPONER"),
        tipo_resolucion="REQUIERE_CONFIRMACION_HUMANA", tipo_vehiculo_propuesto=None,
    )


# ============================================================
# A -- 1 error OCR + único candidato compatible -> auto-resuelve
# ============================================================


def test_a_ocr_unico_candidato_con_historico_independiente_resuelve_automaticamente(tmp_path):
    """"AD1234" (confirmada/activa) tiene dos transportes independientes
    del mismo chofer; el documento actual trae "AB1234" -- B/D es una
    confusión OCR ya calibrada. Único candidato, sin competidores:
    RESUELTO_AUTOMATICAMENTE, aunque nunca hubo una confirmación humana
    asociada a ESTE RUT."""
    entorno = _entorno(tmp_path, filas_csv=[
        _fila_csv(numero_guia="1", patente_tracto="AD1234"),
        _fila_csv(numero_guia="2", patente_tracto="AD1234", numero_transporte="T-2"),
    ])
    _confirmar(entorno["catalogos"], "AD1234", TipoVehiculo.TRACTO)
    vehiculos = cargar_catalogo_vehiculos(entorno["catalogos"] / "vehiculos.json").homologables()
    filas = _leer_csv(entorno["dataset"])

    resultado = evaluar_evidencia_patente(
        campo="patente_tracto", valor_documental="AB1234", rut_chofer=RUT_CHOFER,
        tipo_esperado="TRACTO", numero_transporte_actual="T-3", filas=filas, vehiculos=vehiculos,
    )
    assert resultado["resultado"] == "RESUELTO_AUTOMATICAMENTE"
    assert len(resultado["candidatos"]) == 1
    assert resultado["candidatos"][0]["patente"] == "AD1234"
    assert "SIMILITUD_OCR_CALIBRADA" in resultado["candidatos"][0]["evidencias"]


# ============================================================
# B -- 2 candidatos cercanos -> NO auto-resuelve
# ============================================================


def test_b_dos_candidatos_independientes_empatados_no_auto_resuelve(tmp_path):
    """El mismo chofer corrobora, independientemente, DOS patentes
    distintas -- Atlas nunca elige entre ellas sola."""
    entorno = _entorno(tmp_path, filas_csv=[
        _fila_csv(numero_guia="1", patente_tracto="AD1234"),
        _fila_csv(numero_guia="2", patente_tracto="AD1234", numero_transporte="T-2"),
        _fila_csv(numero_guia="3", patente_tracto="AE1234", numero_transporte="T-4"),
        _fila_csv(numero_guia="4", patente_tracto="AE1234", numero_transporte="T-5"),
    ])
    _confirmar(entorno["catalogos"], "AD1234", TipoVehiculo.TRACTO)
    _confirmar(entorno["catalogos"], "AE1234", TipoVehiculo.TRACTO)
    vehiculos = cargar_catalogo_vehiculos(entorno["catalogos"] / "vehiculos.json").homologables()
    filas = _leer_csv(entorno["dataset"])

    resultado = evaluar_evidencia_patente(
        campo="patente_tracto", valor_documental="AB1234", rut_chofer=RUT_CHOFER,
        tipo_esperado="TRACTO", numero_transporte_actual="T-6", filas=filas, vehiculos=vehiculos,
    )
    assert resultado["resultado"] == "SUGERENCIA_HUMANA"
    assert len(resultado["candidatos"]) == 2


# ============================================================
# C -- chofer cambió vehículo -> no forzar histórico viejo
# ============================================================


def test_c_chofer_cambio_de_vehiculo_no_fuerza_historico_viejo_sin_similitud_ocr(tmp_path):
    """El único histórico del chofer ("AD1234") no se parece en nada a
    lo que el OCR leyó hoy ("ZZ9999") -- el chofer pudo simplemente
    haber cambiado de camión. Sigue apareciendo como candidata débil
    (mismo comportamiento ya existente), pero SIN similitud OCR nunca
    se aplica sola."""
    entorno = _entorno(tmp_path, filas_csv=[
        _fila_csv(numero_guia="1", patente_tracto="AD1234"),
        _fila_csv(numero_guia="2", patente_tracto="AD1234", numero_transporte="T-2"),
    ])
    _confirmar(entorno["catalogos"], "AD1234", TipoVehiculo.TRACTO)
    vehiculos = cargar_catalogo_vehiculos(entorno["catalogos"] / "vehiculos.json").homologables()
    filas = _leer_csv(entorno["dataset"])

    resultado = evaluar_evidencia_patente(
        campo="patente_tracto", valor_documental="ZZ9999", rut_chofer=RUT_CHOFER,
        tipo_esperado="TRACTO", numero_transporte_actual="T-3", filas=filas, vehiculos=vehiculos,
    )
    assert resultado["resultado"] == "SUGERENCIA_HUMANA"
    assert len(resultado["candidatos"]) == 1
    assert "SIMILITUD_OCR_CALIBRADA" not in resultado["candidatos"][0]["evidencias"]


# ============================================================
# D -- patente realmente nueva -> sigue generando revisión
# ============================================================


def test_d_patente_nueva_sin_ningun_candidato_sigue_en_revision(tmp_path):
    entorno = _entorno(tmp_path, filas_csv=[_fila_csv(numero_guia="1", patente_tracto="ZZ9999")])
    vehiculos = ()
    filas = _leer_csv(entorno["dataset"])

    resultado = evaluar_evidencia_patente(
        campo="patente_tracto", valor_documental="ZZ9999", rut_chofer=RUT_CHOFER,
        tipo_esperado="TRACTO", numero_transporte_actual="T-1", filas=filas, vehiculos=vehiculos,
    )
    assert resultado["resultado"] == "ABSTENCION"
    assert resultado["candidatos"] == []


# ============================================================
# E -- resolución automática nunca contamina el catálogo global
# ============================================================


def test_e_resolucion_automatica_no_escribe_alias_ni_registra_vehiculo_nuevo(tmp_path):
    """La resolución automática vincula documento->canónica en el
    ledger (evidencia por documento) -- nunca agrega "AB1234" como
    alias de "AD1234" ni modifica el catálogo de vehículos."""
    entorno = _entorno(tmp_path, filas_csv=[
        _fila_csv(numero_guia="1", patente_tracto="AD1234"),
        _fila_csv(numero_guia="2", patente_tracto="AD1234", numero_transporte="T-2"),
        _fila_csv(numero_guia="3", patente_tracto="AB1234", numero_transporte="T-3"),
    ])
    _confirmar(entorno["catalogos"], "AD1234", TipoVehiculo.TRACTO)
    ruta_vehiculos = entorno["catalogos"] / "vehiculos.json"
    antes = ruta_vehiculos.read_bytes()

    decision = _decision_vehiculo(guia="3", campo="patente_tracto", valor_documental="AB1234")
    generar_artefacto(
        ruta_dataset=entorno["dataset"], carpeta_catalogos=entorno["catalogos"],
        decisiones=[decision], ruta_salida=entorno["actual"] / "decisiones_pendientes.json",
    )
    resultado = reconciliar_bandeja_decisiones(raiz_atlas=entorno["raiz"])
    assert len(resultado["decisiones_aplicadas_automaticamente"]) == 1

    assert ruta_vehiculos.read_bytes() == antes  # catálogo global intacto
    catalogo_tras = cargar_catalogo_vehiculos(ruta_vehiculos).homologables()
    assert [v.aliases for v in catalogo_tras if v.patente_canonica == "AD1234"] == [()]


# ============================================================
# End-to-end -- reproduce la estructura exacta del caso real 472339
# ============================================================


def test_e2e_472339_la_decision_desaparece_y_el_motivo_se_limpia(tmp_path):
    """Reproduce el caso real (valores sintéticos): chofer con dos
    transportes independientes previos usando la canónica confirmada;
    el documento del viaje actual trae un error OCR de un solo
    carácter, calibrado. Al reconciliar la bandeja, la decisión
    VEHICULO_DESCONOCIDO se aplica sola y desaparece; al revalidar
    PATENTE_SIN_HOMOLOGAR sin OCR, el motivo se limpia de esa fila (el
    valor documental del CSV nunca se reescribe -- sigue siendo
    evidencia del error real de OCR)."""
    entorno = _entorno(tmp_path, filas_csv=[
        _fila_csv(numero_guia="472037", patente_tracto="AD1234", numero_transporte="T-1"),
        _fila_csv(numero_guia="472227", patente_tracto="AD1234", numero_transporte="T-2"),
        _fila_csv(
            numero_guia="472339", patente_tracto="AB1234", patente_rampla="",
            numero_transporte="T-3",
            motivos_revision_documento=MotivoRevisionDocumento.PATENTE_SIN_HOMOLOGAR.value,
        ),
    ])
    _confirmar(entorno["catalogos"], "AD1234", TipoVehiculo.TRACTO)

    decision = _decision_vehiculo(
        guia="472339", campo="patente_tracto", valor_documental="AB1234", transporte="T-3",
    )
    generar_artefacto(
        ruta_dataset=entorno["dataset"], carpeta_catalogos=entorno["catalogos"],
        decisiones=[decision], ruta_salida=entorno["actual"] / "decisiones_pendientes.json",
    )

    resultado = reconciliar_bandeja_decisiones(raiz_atlas=entorno["raiz"])
    assert len(resultado["decisiones_aplicadas_automaticamente"]) == 1
    ids_pendientes = [d["decision_id"] for d in resultado["bandeja"]["decisiones"]]
    assert decision["decision_id"] not in ids_pendientes  # la decisión desaparece, nadie la ve

    ledger = json.loads((entorno["actual"] / "decisiones_aplicadas.json").read_text(encoding="utf-8"))
    aplicacion = ledger["aplicaciones"][0]
    assert aplicacion["tipo"] == "VEHICULO_DESCONOCIDO"
    assert aplicacion["accion"] == "USAR_PATENTE_EXISTENTE"
    assert aplicacion["valor_documental"] == "AB1234"  # evidencia documental preservada
    assert aplicacion["patente_canonica"] == "AD1234"

    # `aplicar_decision_obra` ya revalida PATENTE_SIN_HOMOLOGAR como parte
    # de su propia aplicación (mecanismo ya existente, ver
    # `revalidar_patente_sin_homologar_sin_ocr`) -- el motivo queda
    # limpio de inmediato, sin un paso aparte.
    filas_tras = {f["numero_guia"]: f for f in _leer_csv(entorno["dataset"])}
    assert filas_tras["472339"]["motivos_revision_documento"] == ""
    assert filas_tras["472339"]["patente_tracto"] == "AB1234"  # valor documental, nunca reescrito

    # Idempotente: una revalidación manual aparte ya no encuentra nada
    # pendiente que corregir.
    revalidacion = revalidar_patente_sin_homologar_sin_ocr(
        ruta_dataset=entorno["dataset"], carpeta_catalogos=entorno["catalogos"],
        ruta_ledger=entorno["actual"] / "decisiones_aplicadas.json",
    )
    assert revalidacion["guias_actualizadas"] == []
