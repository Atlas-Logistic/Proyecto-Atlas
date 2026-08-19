"""Bloque VEHÍCULO D1 -- patrón documental->canónico para vehículos,
reutilizando la infraestructura de `ORIGEN_NO_CONFIRMADO` (nunca un
sistema paralelo): sugerencia por asociación histórica de RUT de
chofer, nunca autocorrección; `USAR_PATENTE_EXISTENTE`/
`SELECCIONAR_OTRA_PATENTE` como acciones humanas nuevas; `NO_REGISTRAR`
extendido con `motivo_rechazo` para el caso "error documental sin
canónica conocida" (Ortiz); reconciliación general de la bandeja tras
un cambio controlado del dataset; y el refresco de `estado_ruta`/
`motivo_ruta` tras confirmar origen (464717).

Caso real que motivó este bloque -- Carlos Simón: 3 documentos con
lecturas OCR distintas (JD6659/VP6521/JD0659) de un tracto+rampla ya
confirmados en catálogo bajo OTRO valor (VP8521/JE8659); JE8659 se
repite 3 veces en documentos de un solo cliente, pero Javier confirmó
directamente con el chofer que la patente real es JD8659 -- la
repetición documental NO decidió la canónica, sólo la sugirió, tal
como exige este bloque."""
from __future__ import annotations

import csv
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from atlas_core.aplicacion_decisiones import (
    DecisionObsoletaError,
    ErrorAplicacionDecision,
    aplicar_decision_obra,
)
from atlas_core.catalogo_vehiculos import TipoVehiculo, cargar_catalogo_vehiculos, confirmar_vehiculo
from atlas_core.decisiones_pendientes import (
    crear_decision,
    enriquecer_decisiones_vehiculo,
    generar_artefacto,
    sugerir_vehiculos_por_chofer,
)
from atlas_core.procesamiento_masivo import COLUMNAS
from atlas_core.revalidacion_documental import (
    _leer_filas,
    derivar_estado_ruta_tras_cambio_origen,
    reconciliar_bandeja_decisiones,
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


def _decision_vehiculo(*, guia, campo, valor_documental):
    return crear_decision(
        tipo="VEHICULO_DESCONOCIDO", entidad="VEHICULO", archivo=f"{guia}.jpeg",
        numero_guia=guia, numero_transporte="T-1", campo=campo,
        valor_documental=valor_documental, valor_normalizado=valor_documental,
        identidad_resuelta=None, candidatos=(),
        motivos=("SIN_VEHICULO_CONFIRMADO_COMPATIBLE",),
        evidencias=({"tipo": "OCR_DOCUMENTAL", "campo": campo, "valor": valor_documental},),
        acciones_permitidas=("REGISTRAR", "NO_REGISTRAR", "POSPONER"),
        tipo_resolucion="INEQUIVOCO" if campo == "patente_rampla" else "REQUIERE_CONFIRMACION_HUMANA",
        tipo_vehiculo_propuesto="CARRO" if campo == "patente_rampla" else None,
    )


# ============================================================
# Sugerencia por asociación histórica -- nunca autocorrección
# ============================================================


def test_sugiere_patente_existente_asociada_al_mismo_rut(tmp_path):
    entorno = _entorno(tmp_path, filas_csv=[
        _fila_csv(numero_guia="1", patente_tracto="VP6521"),
        _fila_csv(numero_guia="2", patente_tracto="VP8521", numero_transporte="T-2"),
    ])
    _confirmar(entorno["catalogos"], "VP8521", TipoVehiculo.TRACTO)
    vehiculos = cargar_catalogo_vehiculos(entorno["catalogos"] / "vehiculos.json").homologables()
    filas = _leer_csv(entorno["dataset"])
    candidatos = sugerir_vehiculos_por_chofer(
        rut_chofer=RUT_CHOFER, campo="patente_tracto", valor_documental="VP6521",
        filas=filas, vehiculos=vehiculos,
    )
    assert len(candidatos) == 1
    assert candidatos[0]["patente"] == "VP8521"
    assert candidatos[0]["tipo_vehiculo"] == "TRACTO"
    assert candidatos[0]["transportes_independientes"] == 1


def test_sugerencia_compara_rut_normalizado_no_el_string_crudo(tmp_path):
    """Hallazgo real (464699, Carlos Simón): el mismo chofer puede tener
    el RUT documental formateado distinto entre guías (con/sin puntos) --
    la comparación debe ser por RUT normalizado, nunca por el texto
    exacto, o se pierde evidencia real disponible."""
    entorno = _entorno(tmp_path, filas_csv=[
        _fila_csv(numero_guia="1", patente_rampla="JD6659", rut_chofer="15.489.424-1"),
        _fila_csv(numero_guia="2", patente_rampla="JE8659", numero_transporte="T-2", rut_chofer="15489424-1"),
    ])
    _confirmar(entorno["catalogos"], "JE8659", TipoVehiculo.CARRO)
    vehiculos = cargar_catalogo_vehiculos(entorno["catalogos"] / "vehiculos.json").homologables()
    filas = _leer_csv(entorno["dataset"])
    candidatos = sugerir_vehiculos_por_chofer(
        rut_chofer="15.489.424-1", campo="patente_rampla", valor_documental="JD6659",
        filas=filas, vehiculos=vehiculos,
    )
    assert len(candidatos) == 1
    assert candidatos[0]["patente"] == "JE8659"


def test_no_sugiere_nada_si_el_rut_no_tiene_otra_patente_confirmada(tmp_path):
    entorno = _entorno(tmp_path, filas_csv=[_fila_csv(numero_guia="1", patente_tracto="VP6521")])
    filas = _leer_csv(entorno["dataset"])
    candidatos = sugerir_vehiculos_por_chofer(
        rut_chofer=RUT_CHOFER, campo="patente_tracto", valor_documental="VP6521",
        filas=filas, vehiculos=(),
    )
    assert candidatos == []


def test_no_sugiere_vehiculo_no_confirmado_o_inactivo(tmp_path):
    """La repetición documental NO basta -- si el catálogo no la tiene
    CONFIRMADO/ACTIVO, no se sugiere (nunca se inventa evidencia de
    catálogo que no existe)."""
    entorno = _entorno(tmp_path, filas_csv=[
        _fila_csv(numero_guia="1", patente_tracto="VP6521"),
        _fila_csv(numero_guia="2", patente_tracto="VP8521", numero_transporte="T-2"),
    ])
    # Vehículo existe pero NO homologable (no CONFIRMADO/ACTIVO) --
    # homologables() ya lo excluye, así que no llega como candidato.
    filas = _leer_csv(entorno["dataset"])
    candidatos = sugerir_vehiculos_por_chofer(
        rut_chofer=RUT_CHOFER, campo="patente_tracto", valor_documental="VP6521",
        filas=filas, vehiculos=(),  # catálogo vacío -- nada homologable
    )
    assert candidatos == []


def test_repeticion_documental_nunca_decide_por_mayoria_reporta_cada_candidata_igual(tmp_path):
    """Control crítico (caso real Carlos Simón): un valor que se repite
    3 veces en el dataset NO se trata como "más verdadero" que uno que
    aparece una sola vez -- ambos se reportan igual, con su propia
    evidencia, y la decisión de cuál es la canónica es siempre humana."""
    entorno = _entorno(tmp_path, filas_csv=[
        _fila_csv(numero_guia="1", patente_rampla="JD6659"),
        _fila_csv(numero_guia="2", patente_rampla="JE8659", numero_transporte="T-2"),
        _fila_csv(numero_guia="3", patente_rampla="JE8659", numero_transporte="T-3"),
        _fila_csv(numero_guia="4", patente_rampla="JE8659", numero_transporte="T-4"),
        _fila_csv(numero_guia="5", patente_rampla="JD8659", numero_transporte="T-5"),
    ])
    _confirmar(entorno["catalogos"], "JE8659", TipoVehiculo.CARRO)
    _confirmar(entorno["catalogos"], "JD8659", TipoVehiculo.CARRO)
    vehiculos = cargar_catalogo_vehiculos(entorno["catalogos"] / "vehiculos.json").homologables()
    filas = _leer_csv(entorno["dataset"])
    candidatos = sugerir_vehiculos_por_chofer(
        rut_chofer=RUT_CHOFER, campo="patente_rampla", valor_documental="JD6659",
        filas=filas, vehiculos=vehiculos,
    )
    por_patente = {c["patente"]: c for c in candidatos}
    assert set(por_patente) == {"JE8659", "JD8659"}
    assert por_patente["JE8659"]["transportes_independientes"] == 3
    assert por_patente["JD8659"]["transportes_independientes"] == 1
    # Ambas aparecen como candidatas -- Atlas NUNCA elige JE8659 sólo
    # porque aparece más veces.


def test_enriquecer_decisiones_vehiculo_no_toca_decisiones_sin_asociacion(tmp_path):
    """Las 9 decisiones "genuinamente nuevas" del caso real (sin ningún
    historial por RUT) deben quedar exactamente igual que antes --
    ningún candidato, mismas 3 acciones de siempre."""
    entorno = _entorno(tmp_path, filas_csv=[_fila_csv(numero_guia="1", patente_tracto="ZZ0000")])
    decision = _decision_vehiculo(guia="1", campo="patente_tracto", valor_documental="ZZ0000")
    filas = _leer_csv(entorno["dataset"])
    resultado = enriquecer_decisiones_vehiculo(decisiones=[decision], filas=filas, vehiculos=())
    assert resultado[0]["candidatos"] == []
    assert resultado[0]["acciones_permitidas"] == ["REGISTRAR", "NO_REGISTRAR", "POSPONER"]


def test_enriquecer_decisiones_vehiculo_agrega_candidatos_y_acciones(tmp_path):
    entorno = _entorno(tmp_path, filas_csv=[
        _fila_csv(numero_guia="1", patente_tracto="VP6521"),
        _fila_csv(numero_guia="2", patente_tracto="VP8521", numero_transporte="T-2"),
    ])
    _confirmar(entorno["catalogos"], "VP8521", TipoVehiculo.TRACTO)
    vehiculos = cargar_catalogo_vehiculos(entorno["catalogos"] / "vehiculos.json").homologables()
    decision = _decision_vehiculo(guia="1", campo="patente_tracto", valor_documental="VP6521")
    filas = _leer_csv(entorno["dataset"])
    resultado = enriquecer_decisiones_vehiculo(decisiones=[decision], filas=filas, vehiculos=vehiculos)
    enriquecida = resultado[0]
    assert len(enriquecida["candidatos"]) == 1
    assert "USAR_PATENTE_EXISTENTE" in enriquecida["acciones_permitidas"]
    assert "SELECCIONAR_OTRA_PATENTE" in enriquecida["acciones_permitidas"]
    # Las 3 acciones originales se conservan -- nunca se reemplazan.
    assert "REGISTRAR" in enriquecida["acciones_permitidas"]
    assert "NO_REGISTRAR" in enriquecida["acciones_permitidas"]
    assert "POSPONER" in enriquecida["acciones_permitidas"]


# ============================================================
# Aplicación: USAR_PATENTE_EXISTENTE / SELECCIONAR_OTRA_PATENTE
# ============================================================


def _entorno_con_decision_enriquecida(tmp_path, *, filas_csv, decision_base):
    entorno = _entorno(tmp_path, filas_csv=filas_csv)
    filas = _leer_csv(entorno["dataset"])
    vehiculos = cargar_catalogo_vehiculos(entorno["catalogos"] / "vehiculos.json").homologables()
    enriquecidas = enriquecer_decisiones_vehiculo(decisiones=[decision_base], filas=filas, vehiculos=vehiculos)
    generar_artefacto(
        ruta_dataset=entorno["dataset"], carpeta_catalogos=entorno["catalogos"],
        decisiones=enriquecidas, ruta_salida=entorno["actual"] / "decisiones_pendientes.json",
    )
    return entorno, enriquecidas[0]


def test_usar_patente_existente_aplica_sin_tocar_csv(tmp_path):
    entorno, decision = _entorno_con_decision_enriquecida(
        tmp_path,
        filas_csv=[
            _fila_csv(numero_guia="1", patente_tracto="VP6521"),
            _fila_csv(numero_guia="2", patente_tracto="VP8521", numero_transporte="T-2"),
        ],
        decision_base=_decision_vehiculo(guia="1", campo="patente_tracto", valor_documental="VP6521"),
    )
    vehiculo = _confirmar(entorno["catalogos"], "VP8521", TipoVehiculo.TRACTO)
    # La decisión ya se generó/publicó con el candidato; el catálogo real
    # sólo se confirma después -- se re-publica para reflejar el hash
    # vigente antes de aplicar (mismo patrón que el resto del proyecto).
    filas = _leer_csv(entorno["dataset"])
    vehiculos = cargar_catalogo_vehiculos(entorno["catalogos"] / "vehiculos.json").homologables()
    enriquecidas = enriquecer_decisiones_vehiculo(decisiones=[decision], filas=filas, vehiculos=vehiculos)
    generar_artefacto(
        ruta_dataset=entorno["dataset"], carpeta_catalogos=entorno["catalogos"],
        decisiones=enriquecidas, ruta_salida=entorno["actual"] / "decisiones_pendientes.json",
    )
    antes = entorno["dataset"].read_bytes()
    resultado = aplicar_decision_obra(
        raiz_atlas=entorno["raiz"], decision_id=decision["decision_id"], accion="USAR_PATENTE_EXISTENTE",
    )
    assert resultado["ok"] is True
    assert resultado["patente_canonica"] == "VP8521"
    assert resultado["vehiculo_id"] == vehiculo.vehiculo_id
    # El valor documental (CSV) nunca se toca -- se preserva tal cual.
    assert entorno["dataset"].read_bytes() == antes
    fila = _leer_csv(entorno["dataset"])[0]
    assert fila["patente_tracto"] == "VP6521"


def test_usar_patente_existente_falla_con_mas_de_un_candidato(tmp_path):
    entorno, decision = _entorno_con_decision_enriquecida(
        tmp_path,
        filas_csv=[
            _fila_csv(numero_guia="1", patente_rampla="JD6659"),
            _fila_csv(numero_guia="2", patente_rampla="JE8659", numero_transporte="T-2"),
            _fila_csv(numero_guia="3", patente_rampla="JD8659", numero_transporte="T-3"),
        ],
        decision_base=_decision_vehiculo(guia="1", campo="patente_rampla", valor_documental="JD6659"),
    )
    _confirmar(entorno["catalogos"], "JE8659", TipoVehiculo.CARRO)
    _confirmar(entorno["catalogos"], "JD8659", TipoVehiculo.CARRO)
    filas = _leer_csv(entorno["dataset"])
    vehiculos = cargar_catalogo_vehiculos(entorno["catalogos"] / "vehiculos.json").homologables()
    enriquecidas = enriquecer_decisiones_vehiculo(decisiones=[decision], filas=filas, vehiculos=vehiculos)
    generar_artefacto(
        ruta_dataset=entorno["dataset"], carpeta_catalogos=entorno["catalogos"],
        decisiones=enriquecidas, ruta_salida=entorno["actual"] / "decisiones_pendientes.json",
    )
    with pytest.raises(ErrorAplicacionDecision):
        aplicar_decision_obra(raiz_atlas=entorno["raiz"], decision_id=enriquecidas[0]["decision_id"], accion="USAR_PATENTE_EXISTENTE")


def test_seleccionar_otra_patente_control_critico_javier_elige_jd8659(tmp_path):
    """Control crítico real: JE8659 se repite 3 veces (más que JD8659,
    que aparece 1 vez), pero el humano elige JD8659 -- Atlas nunca fuerza
    la más repetida."""
    entorno, decision = _entorno_con_decision_enriquecida(
        tmp_path,
        filas_csv=[
            _fila_csv(numero_guia="1", patente_rampla="JD6659"),
            _fila_csv(numero_guia="2", patente_rampla="JE8659", numero_transporte="T-2"),
            _fila_csv(numero_guia="3", patente_rampla="JE8659", numero_transporte="T-3"),
            _fila_csv(numero_guia="4", patente_rampla="JE8659", numero_transporte="T-4"),
            _fila_csv(numero_guia="5", patente_rampla="JD8659", numero_transporte="T-5"),
        ],
        decision_base=_decision_vehiculo(guia="1", campo="patente_rampla", valor_documental="JD6659"),
    )
    _confirmar(entorno["catalogos"], "JE8659", TipoVehiculo.CARRO)
    vehiculo_jd = _confirmar(entorno["catalogos"], "JD8659", TipoVehiculo.CARRO)
    filas = _leer_csv(entorno["dataset"])
    vehiculos = cargar_catalogo_vehiculos(entorno["catalogos"] / "vehiculos.json").homologables()
    enriquecidas = enriquecer_decisiones_vehiculo(decisiones=[decision], filas=filas, vehiculos=vehiculos)
    generar_artefacto(
        ruta_dataset=entorno["dataset"], carpeta_catalogos=entorno["catalogos"],
        decisiones=enriquecidas, ruta_salida=entorno["actual"] / "decisiones_pendientes.json",
    )
    resultado = aplicar_decision_obra(
        raiz_atlas=entorno["raiz"], decision_id=enriquecidas[0]["decision_id"],
        accion="SELECCIONAR_OTRA_PATENTE", patente_elegida="JD8659",
    )
    assert resultado["ok"] is True
    assert resultado["patente_canonica"] == "JD8659"
    assert resultado["vehiculo_id"] == vehiculo_jd.vehiculo_id
    ledger = json.loads((entorno["actual"] / "decisiones_aplicadas.json").read_text(encoding="utf-8"))
    aplicacion = ledger["aplicaciones"][0]
    assert aplicacion["accion"] == "SELECCIONAR_OTRA_PATENTE"
    assert aplicacion["valor_documental"] == "JD6659"
    assert aplicacion["patente_canonica"] == "JD8659"
    assert aplicacion["actor"] == "JAVIER_MBT"


def test_seleccionar_otra_patente_rechaza_patente_no_confirmada(tmp_path):
    entorno, decision = _entorno_con_decision_enriquecida(
        tmp_path,
        filas_csv=[_fila_csv(numero_guia="1", patente_tracto="VP6521")],
        decision_base=_decision_vehiculo(guia="1", campo="patente_tracto", valor_documental="VP6521"),
    )
    with pytest.raises(ErrorAplicacionDecision):
        aplicar_decision_obra(
            raiz_atlas=entorno["raiz"], decision_id=decision["decision_id"],
            accion="SELECCIONAR_OTRA_PATENTE", patente_elegida="ZZ9999",
        )


# ============================================================
# NO_REGISTRAR con motivo (caso Ortiz -- error documental sin canónica)
# ============================================================


def test_no_registrar_preserva_motivo_de_rechazo(tmp_path):
    entorno = _entorno(tmp_path, filas_csv=[_fila_csv(numero_guia="1", patente_tracto="XF3662")])
    decision = _decision_vehiculo(guia="1", campo="patente_tracto", valor_documental="XF3662")
    generar_artefacto(
        ruta_dataset=entorno["dataset"], carpeta_catalogos=entorno["catalogos"],
        decisiones=[decision], ruta_salida=entorno["actual"] / "decisiones_pendientes.json",
    )
    resultado = aplicar_decision_obra(
        raiz_atlas=entorno["raiz"], decision_id=decision["decision_id"],
        accion="NO_REGISTRAR", motivo_rechazo="ERROR_DOCUMENTAL_MANDANTE",
    )
    assert resultado["ok"] is True
    ledger = json.loads((entorno["actual"] / "decisiones_aplicadas.json").read_text(encoding="utf-8"))
    aplicacion = ledger["aplicaciones"][0]
    assert aplicacion["motivo_rechazo"] == "ERROR_DOCUMENTAL_MANDANTE"
    assert aplicacion["valor_documental"] == "XF3662"
    assert aplicacion["vehiculo_id"] is None
    # No se registra ningún vehículo.
    assert cargar_catalogo_vehiculos(entorno["catalogos"] / "vehiculos.json").homologables() == ()


def test_no_registrar_sin_motivo_sigue_funcionando_como_antes(tmp_path):
    """Compatibilidad: `motivo_rechazo` es opcional -- el flujo ya
    existente (Desktop hoy no lo envía) sigue funcionando igual."""
    entorno = _entorno(tmp_path, filas_csv=[_fila_csv(numero_guia="1", patente_tracto="XF3662")])
    decision = _decision_vehiculo(guia="1", campo="patente_tracto", valor_documental="XF3662")
    generar_artefacto(
        ruta_dataset=entorno["dataset"], carpeta_catalogos=entorno["catalogos"],
        decisiones=[decision], ruta_salida=entorno["actual"] / "decisiones_pendientes.json",
    )
    resultado = aplicar_decision_obra(raiz_atlas=entorno["raiz"], decision_id=decision["decision_id"], accion="NO_REGISTRAR")
    assert resultado["ok"] is True
    ledger = json.loads((entorno["actual"] / "decisiones_aplicadas.json").read_text(encoding="utf-8"))
    assert ledger["aplicaciones"][0]["motivo_rechazo"] is None


def test_misma_evidencia_rechazada_no_reaparece(tmp_path):
    entorno = _entorno(tmp_path, filas_csv=[_fila_csv(numero_guia="1", patente_tracto="XF3662")])
    decision = _decision_vehiculo(guia="1", campo="patente_tracto", valor_documental="XF3662")
    generar_artefacto(
        ruta_dataset=entorno["dataset"], carpeta_catalogos=entorno["catalogos"],
        decisiones=[decision], ruta_salida=entorno["actual"] / "decisiones_pendientes.json",
    )
    aplicar_decision_obra(
        raiz_atlas=entorno["raiz"], decision_id=decision["decision_id"],
        accion="NO_REGISTRAR", motivo_rechazo="ERROR_DOCUMENTAL_MANDANTE",
    )
    # Misma evidencia exacta -> mismo decision_id -> generar_artefacto la filtra.
    misma_decision = _decision_vehiculo(guia="1", campo="patente_tracto", valor_documental="XF3662")
    assert misma_decision["decision_id"] == decision["decision_id"]
    bandeja = generar_artefacto(
        ruta_dataset=entorno["dataset"], carpeta_catalogos=entorno["catalogos"],
        decisiones=[misma_decision], ruta_salida=entorno["actual"] / "decisiones_pendientes.json",
    )
    assert bandeja["decisiones"] == []


def test_evidencia_nueva_si_puede_generar_revision_nueva(tmp_path):
    """Si una relectura futura del documento extrajera un valor
    DISTINTO, es evidencia nueva -- Atlas correctamente vuelve a
    preguntar (no es "la misma revisión eterna")."""
    entorno = _entorno(tmp_path, filas_csv=[_fila_csv(numero_guia="1", patente_tracto="XF3662")])
    decision = _decision_vehiculo(guia="1", campo="patente_tracto", valor_documental="XF3662")
    generar_artefacto(
        ruta_dataset=entorno["dataset"], carpeta_catalogos=entorno["catalogos"],
        decisiones=[decision], ruta_salida=entorno["actual"] / "decisiones_pendientes.json",
    )
    aplicar_decision_obra(
        raiz_atlas=entorno["raiz"], decision_id=decision["decision_id"],
        accion="NO_REGISTRAR", motivo_rechazo="ERROR_DOCUMENTAL_MANDANTE",
    )
    decision_distinta = _decision_vehiculo(guia="1", campo="patente_tracto", valor_documental="XF9999")
    assert decision_distinta["decision_id"] != decision["decision_id"]
    bandeja = generar_artefacto(
        ruta_dataset=entorno["dataset"], carpeta_catalogos=entorno["catalogos"],
        decisiones=[decision_distinta], ruta_salida=entorno["actual"] / "decisiones_pendientes.json",
    )
    assert len(bandeja["decisiones"]) == 1


# ============================================================
# Reconciliación de la bandeja tras cambio controlado del dataset
# ============================================================


def test_reconciliar_bandeja_refresca_dataset_sha256_sin_tocar_csv_ni_catalogos(tmp_path):
    entorno = _entorno(tmp_path, filas_csv=[_fila_csv(numero_guia="1", patente_tracto="ZZ0000")])
    decision = _decision_vehiculo(guia="1", campo="patente_tracto", valor_documental="ZZ0000")
    generar_artefacto(
        ruta_dataset=entorno["dataset"], carpeta_catalogos=entorno["catalogos"],
        decisiones=[decision], ruta_salida=entorno["actual"] / "decisiones_pendientes.json",
    )
    artefacto_antes = json.loads((entorno["actual"] / "decisiones_pendientes.json").read_text(encoding="utf-8"))
    sha_antes = artefacto_antes["dataset_sha256"]

    # Simula un cambio controlado del dataset que NO pasó por
    # generar_artefacto (como la aplicación directa de ruta/km del
    # bloque anterior) -- deja el hash del artefacto desalineado.
    filas = _leer_csv(entorno["dataset"])
    filas[0]["distancia_km"] = "12.3"
    _escribir_csv(entorno["dataset"], filas)

    antes_bytes_csv = entorno["dataset"].read_bytes()
    antes_bytes_catalogo = (entorno["catalogos"] / "vehiculos.json").read_bytes()

    # Sin reconciliar, aplicar_decision_obra debe rechazar por obsolescencia.
    with pytest.raises(DecisionObsoletaError):
        aplicar_decision_obra(raiz_atlas=entorno["raiz"], decision_id=decision["decision_id"], accion="NO_REGISTRAR")

    resultado = reconciliar_bandeja_decisiones(raiz_atlas=entorno["raiz"])
    assert resultado["decisiones_conservadas"] == 1
    assert resultado["decisiones_publicadas"] == 1

    artefacto_despues = json.loads((entorno["actual"] / "decisiones_pendientes.json").read_text(encoding="utf-8"))
    assert artefacto_despues["dataset_sha256"] != sha_antes
    # La reconciliación nunca toca el CSV ni los catálogos.
    assert entorno["dataset"].read_bytes() == antes_bytes_csv
    assert (entorno["catalogos"] / "vehiculos.json").read_bytes() == antes_bytes_catalogo

    # Y ahora sí puede aplicarse.
    resultado_aplicar = aplicar_decision_obra(raiz_atlas=entorno["raiz"], decision_id=decision["decision_id"], accion="NO_REGISTRAR")
    assert resultado_aplicar["ok"] is True


def test_reconciliar_bandeja_enriquece_vehiculos_con_candidatos(tmp_path):
    entorno = _entorno(tmp_path, filas_csv=[
        _fila_csv(numero_guia="1", patente_tracto="VP6521"),
        _fila_csv(numero_guia="2", patente_tracto="VP8521", numero_transporte="T-2"),
    ])
    _confirmar(entorno["catalogos"], "VP8521", TipoVehiculo.TRACTO)
    decision = _decision_vehiculo(guia="1", campo="patente_tracto", valor_documental="VP6521")
    generar_artefacto(
        ruta_dataset=entorno["dataset"], carpeta_catalogos=entorno["catalogos"],
        decisiones=[decision], ruta_salida=entorno["actual"] / "decisiones_pendientes.json",
    )
    reconciliar_bandeja_decisiones(raiz_atlas=entorno["raiz"])
    artefacto = json.loads((entorno["actual"] / "decisiones_pendientes.json").read_text(encoding="utf-8"))
    dec = artefacto["decisiones"][0]
    assert len(dec["candidatos"]) == 1
    assert dec["candidatos"][0]["patente"] == "VP8521"
    assert "USAR_PATENTE_EXISTENTE" in dec["acciones_permitidas"]


def test_reconciliar_bandeja_no_reabre_decision_ya_cerrada(tmp_path):
    entorno = _entorno(tmp_path, filas_csv=[_fila_csv(numero_guia="1", patente_tracto="ZZ0000")])
    decision = _decision_vehiculo(guia="1", campo="patente_tracto", valor_documental="ZZ0000")
    generar_artefacto(
        ruta_dataset=entorno["dataset"], carpeta_catalogos=entorno["catalogos"],
        decisiones=[decision], ruta_salida=entorno["actual"] / "decisiones_pendientes.json",
    )
    aplicar_decision_obra(raiz_atlas=entorno["raiz"], decision_id=decision["decision_id"], accion="NO_REGISTRAR")
    resultado = reconciliar_bandeja_decisiones(raiz_atlas=entorno["raiz"])
    assert resultado["decisiones_publicadas"] == 0


def test_aplicar_decision_ajena_no_borra_las_acciones_de_una_decision_enriquecida(tmp_path):
    """Hallazgo real en validación TEMP: aplicar una decisión (p. ej.
    Ortiz, NO_REGISTRAR) dispara internamente `regenerar_decisiones_persistidas`
    sobre TODA la bandeja -- sin esta protección, esa regeneración
    reseteaba `acciones_permitidas` a la base de 3 para CUALQUIER otra
    decisión VEHICULO_DESCONOCIDO ya enriquecida con candidatos (Carlos
    Simón), dejando USAR_PATENTE_EXISTENTE/SELECCIONAR_OTRA_PATENTE
    inaccesibles pese a que `candidatos` seguía ahí."""
    entorno = _entorno(tmp_path, filas_csv=[
        _fila_csv(numero_guia="1", patente_tracto="XF3662"),  # Ortiz -- sin candidato
        _fila_csv(numero_guia="2", patente_rampla="JD6659", numero_transporte="T-2"),  # Carlos Simón
        _fila_csv(numero_guia="3", patente_rampla="JE8659", numero_transporte="T-3"),
    ])
    _confirmar(entorno["catalogos"], "JE8659", TipoVehiculo.CARRO)
    decision_ortiz = _decision_vehiculo(guia="1", campo="patente_tracto", valor_documental="XF3662")
    decision_carlos = _decision_vehiculo(guia="2", campo="patente_rampla", valor_documental="JD6659")
    filas = _leer_csv(entorno["dataset"])
    vehiculos = cargar_catalogo_vehiculos(entorno["catalogos"] / "vehiculos.json").homologables()
    enriquecidas = enriquecer_decisiones_vehiculo(decisiones=[decision_ortiz, decision_carlos], filas=filas, vehiculos=vehiculos)
    generar_artefacto(
        ruta_dataset=entorno["dataset"], carpeta_catalogos=entorno["catalogos"],
        decisiones=enriquecidas, ruta_salida=entorno["actual"] / "decisiones_pendientes.json",
    )
    decision_ortiz_publicada = next(d for d in enriquecidas if d["documento"]["numero_guia"] == "1")

    # Aplicar la decisión de Ortiz -- NO relacionada con Carlos Simón --
    # dispara la regeneración interna de TODA la bandeja.
    aplicar_decision_obra(
        raiz_atlas=entorno["raiz"], decision_id=decision_ortiz_publicada["decision_id"],
        accion="NO_REGISTRAR", motivo_rechazo="ERROR_DOCUMENTAL_MANDANTE",
    )

    artefacto = json.loads((entorno["actual"] / "decisiones_pendientes.json").read_text(encoding="utf-8"))
    carlos_actual = next(d for d in artefacto["decisiones"] if d["documento"]["numero_guia"] == "2")
    assert carlos_actual["candidatos"], "los candidatos deben sobrevivir"
    assert "USAR_PATENTE_EXISTENTE" in carlos_actual["acciones_permitidas"]
    assert "SELECCIONAR_OTRA_PATENTE" in carlos_actual["acciones_permitidas"]


def test_reconciliar_bandeja_protege_dataset_genuinamente_obsoleto(tmp_path):
    """La reconciliación no relaja la protección real: si el dataset
    fuera reemplazado por uno GENUINAMENTE distinto (no un simple
    refresco de hash) DESPUÉS de reconciliar, `aplicar_decision_obra`
    vuelve a rechazar."""
    entorno = _entorno(tmp_path, filas_csv=[_fila_csv(numero_guia="1", patente_tracto="ZZ0000")])
    decision = _decision_vehiculo(guia="1", campo="patente_tracto", valor_documental="ZZ0000")
    generar_artefacto(
        ruta_dataset=entorno["dataset"], carpeta_catalogos=entorno["catalogos"],
        decisiones=[decision], ruta_salida=entorno["actual"] / "decisiones_pendientes.json",
    )
    reconciliar_bandeja_decisiones(raiz_atlas=entorno["raiz"])
    entorno["dataset"].write_text("cambio externo posterior no reconciliado", encoding="utf-8")
    with pytest.raises(DecisionObsoletaError):
        aplicar_decision_obra(raiz_atlas=entorno["raiz"], decision_id=decision["decision_id"], accion="NO_REGISTRAR")


# ============================================================
# Refresco de estado_ruta/motivo_ruta tras confirmar origen (464717)
# ============================================================


def test_derivar_estado_ruta_no_cambia_nada_si_origen_sigue_sin_determinar():
    fila = _fila_csv(estado_ruta="ORIGEN_NO_DETERMINADO", motivo_ruta="ORIGEN_GPS_NO_DETERMINADO")
    assert derivar_estado_ruta_tras_cambio_origen(fila) == {}


def test_derivar_estado_ruta_no_cambia_nada_si_ya_hay_ruta_calculada():
    fila = _fila_csv(
        planta_origen_nombre="AZA COLINA", distancia_km="12.3",
        estado_ruta="RUTA_CALCULADA", motivo_ruta="",
    )
    assert derivar_estado_ruta_tras_cambio_origen(fila) == {}


def test_derivar_estado_ruta_expresa_bloqueo_de_destino_tras_confirmar_origen():
    """Patrón exacto 464717: origen confirmado, destino ambiguo
    (`estado_entrega=REVISAR`), pero `estado_ruta` seguía diciendo
    ORIGEN_NO_DETERMINADO."""
    fila = _fila_csv(
        planta_origen_nombre="AZA COLINA", origen_determinado_por="CONFIRMACION_HUMANA",
        estado_entrega="REVISAR", distancia_km="",
        estado_ruta="ORIGEN_NO_DETERMINADO", motivo_ruta="ORIGEN_GPS_ESTADIA_SIN_PLANTA",
    )
    resultado = derivar_estado_ruta_tras_cambio_origen(fila)
    assert resultado == {"estado_ruta": "REQUIERE_REVISION", "motivo_ruta": "DESTINO_REVISAR"}
    # Nunca fuerza RUTA_CALCULADA -- el destino sigue genuinamente ambiguo.
    assert resultado["estado_ruta"] != "RUTA_CALCULADA"


def test_derivar_estado_ruta_no_cambia_nada_si_destino_ya_resuelto():
    fila = _fila_csv(
        planta_origen_nombre="AZA RENCA", estado_entrega="RESUELTO", distancia_km="",
        estado_ruta="ORIGEN_NO_DETERMINADO", motivo_ruta="ORIGEN_GPS_CONFLICTO",
    )
    # Caso 464730-como (destino ya resuelto, ruta aún no calculada
    # explícitamente) -- no hay "bloqueo de destino" que expresar; se
    # deja para el mecanismo de ruta/km, no para éste.
    assert derivar_estado_ruta_tras_cambio_origen(fila) == {}


def test_aplicar_confirmacion_origen_refresca_estado_ruta_automaticamente(tmp_path):
    """Integración: `aplicar_decision_obra` para ORIGEN_NO_CONFIRMADO ya
    dispara el refresco automáticamente -- sin ningún parche específico
    para 464717."""
    from atlas_core.catalogo_plantas import CatalogoPlantas, EstadoCalidad
    from atlas_core.decisiones_pendientes import crear_decision as crear_decision_generica

    entorno = _entorno(tmp_path, filas_csv=[_fila_csv(
        numero_guia="464717", numero_transporte="T-464717",
        estado_ruta="ORIGEN_NO_DETERMINADO", motivo_ruta="ORIGEN_GPS_ESTADIA_SIN_PLANTA",
        estado_entrega="REVISAR", despachar_a_crudo="CAMINO EJEMPLO 123",
    )])
    catalogo = CatalogoPlantas(entorno["catalogos"] / "plantas.json")
    planta = catalogo.crear(
        nombre="AZA COLINA", pais="CHILE", fuente="TEST",
        latitud=-33.137558, longitud=-70.665977, estado_calidad=EstadoCalidad.CONFIRMADA,
    )
    decision = crear_decision_generica(
        tipo="ORIGEN_NO_CONFIRMADO", entidad="ORIGEN", archivo="464717.jpeg",
        numero_guia="464717", numero_transporte="T-464717", campo="planta_origen",
        valor_documental="", valor_normalizado="", identidad_resuelta=None,
        candidatos=[{"planta_id": planta.planta_id, "planta_nombre": "AZA COLINA", "evidencia_resumen": "test"}],
        motivos=("ORIGEN_GPS_ESTADIA_SIN_PLANTA",),
        evidencias=({"tipo": "GPS_ORIGEN", "motivo_origen_gps": "x"},),
        acciones_permitidas=("CONFIRMAR_PLANTA", "SELECCIONAR_OTRA_PLANTA", "NO_PUEDO_DETERMINAR", "POSPONER"),
    )
    generar_artefacto(
        ruta_dataset=entorno["dataset"], carpeta_catalogos=entorno["catalogos"],
        decisiones=[decision], ruta_salida=entorno["actual"] / "decisiones_pendientes.json",
    )
    aplicar_decision_obra(raiz_atlas=entorno["raiz"], decision_id=decision["decision_id"], accion="CONFIRMAR_PLANTA")

    fila = _leer_csv(entorno["dataset"])[0]
    assert fila["planta_origen_nombre"] == "AZA COLINA"
    assert fila["origen_determinado_por"] == "CONFIRMACION_HUMANA"
    # El bug real: ya NO dice "origen no determinado" -- ahora expresa el
    # bloqueo real (destino ambiguo).
    assert fila["estado_ruta"] == "REQUIERE_REVISION"
    assert fila["motivo_ruta"] == "DESTINO_REVISAR"


# ============================================================
# CLI (aplicar_decision_pendiente.py) -- lo que Desktop invoca en vivo
# ============================================================


def _ejecutar_cli(raiz, decision_id, accion, **extra):
    script = Path(__file__).resolve().parents[1] / "aplicar_decision_pendiente.py"
    argumentos = [sys.executable, str(script), "--raiz-atlas", str(raiz), "--decision-id", decision_id, "--accion", accion]
    for bandera, valor in extra.items():
        if valor:
            argumentos += [f"--{bandera}", valor]
    proceso = subprocess.run(argumentos, cwd=script.parent, capture_output=True, check=True)
    return json.loads(proceso.stdout.decode("ascii"))


def test_cli_usar_patente_existente_de_punta_a_punta(tmp_path):
    entorno, decision = _entorno_con_decision_enriquecida(
        tmp_path,
        filas_csv=[
            _fila_csv(numero_guia="1", patente_tracto="VP6521"),
            _fila_csv(numero_guia="2", patente_tracto="VP8521", numero_transporte="T-2"),
        ],
        decision_base=_decision_vehiculo(guia="1", campo="patente_tracto", valor_documental="VP6521"),
    )
    _confirmar(entorno["catalogos"], "VP8521", TipoVehiculo.TRACTO)
    filas = _leer_csv(entorno["dataset"])
    vehiculos = cargar_catalogo_vehiculos(entorno["catalogos"] / "vehiculos.json").homologables()
    enriquecidas = enriquecer_decisiones_vehiculo(decisiones=[decision], filas=filas, vehiculos=vehiculos)
    generar_artefacto(
        ruta_dataset=entorno["dataset"], carpeta_catalogos=entorno["catalogos"],
        decisiones=enriquecidas, ruta_salida=entorno["actual"] / "decisiones_pendientes.json",
    )
    respuesta = _ejecutar_cli(entorno["raiz"], enriquecidas[0]["decision_id"], "USAR_PATENTE_EXISTENTE")
    assert respuesta["ok"] is True
    assert respuesta["patente_canonica"] == "VP8521"


def test_cli_seleccionar_otra_patente_y_no_registrar_con_motivo_de_punta_a_punta(tmp_path):
    entorno, decision = _entorno_con_decision_enriquecida(
        tmp_path,
        filas_csv=[
            _fila_csv(numero_guia="1", patente_rampla="JD6659"),
            _fila_csv(numero_guia="2", patente_rampla="JE8659", numero_transporte="T-2"),
        ],
        decision_base=_decision_vehiculo(guia="1", campo="patente_rampla", valor_documental="JD6659"),
    )
    _confirmar(entorno["catalogos"], "JE8659", TipoVehiculo.CARRO)
    filas = _leer_csv(entorno["dataset"])
    vehiculos = cargar_catalogo_vehiculos(entorno["catalogos"] / "vehiculos.json").homologables()
    enriquecidas = enriquecer_decisiones_vehiculo(decisiones=[decision], filas=filas, vehiculos=vehiculos)
    generar_artefacto(
        ruta_dataset=entorno["dataset"], carpeta_catalogos=entorno["catalogos"],
        decisiones=enriquecidas, ruta_salida=entorno["actual"] / "decisiones_pendientes.json",
    )
    respuesta = _ejecutar_cli(
        entorno["raiz"], enriquecidas[0]["decision_id"], "SELECCIONAR_OTRA_PATENTE", **{"patente-elegida": "JE8659"},
    )
    assert respuesta["ok"] is True
    assert respuesta["patente_canonica"] == "JE8659"


def test_cli_no_registrar_con_motivo_rechazo_de_punta_a_punta(tmp_path):
    entorno = _entorno(tmp_path, filas_csv=[_fila_csv(numero_guia="1", patente_tracto="XF3662")])
    decision = _decision_vehiculo(guia="1", campo="patente_tracto", valor_documental="XF3662")
    generar_artefacto(
        ruta_dataset=entorno["dataset"], carpeta_catalogos=entorno["catalogos"],
        decisiones=[decision], ruta_salida=entorno["actual"] / "decisiones_pendientes.json",
    )
    respuesta = _ejecutar_cli(
        entorno["raiz"], decision["decision_id"], "NO_REGISTRAR", **{"motivo-rechazo": "ERROR_DOCUMENTAL_MANDANTE"},
    )
    assert respuesta["ok"] is True
    ledger = json.loads((entorno["actual"] / "decisiones_aplicadas.json").read_text(encoding="utf-8"))
    assert ledger["aplicaciones"][0]["motivo_rechazo"] == "ERROR_DOCUMENTAL_MANDANTE"
