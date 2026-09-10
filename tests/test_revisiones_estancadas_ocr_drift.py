"""Bloque REVISIONES ESTANCADAS -- una tarjeta de Revisión de Atlas que un
humano YA respondió para una guía concreta seguía viva porque una
reextracción posterior varió el texto documental y
`regenerar_decisiones_persistidas` sólo empataba la resolución previa por
clave EXACTA (`decision_id` -- que depende de `valor_documental` -- o
coincidencia LITERAL de calle).

Casos reales:
  * 472037 -- `CLIENTE_CANDIDATO`: el humano confirmó "COMERCIAL A Y B
    LTDA"; una pasada posterior leyó "CONERCIAL A Y B LTDA" (una letra) y
    se regeneró la tarjeta con otro `decision_id`.
  * 472008 / 472227 -- `DESTINO_SIN_CONFIRMAR`: la relación
    obra<->destino ya estaba CONFIRMADA (nivel CONFIRMACION_HUMANA) con
    evidencia que cita esa guía, pero el `destino_documental` de la
    tarjeta quedó como un texto OCR distinto ("Jefe de Adquisiciones
    ...", "0114B" vs "O1148").

Las dos supresiones nuevas son keyed por `(numero_guia, entidad)` y
tolerantes al drift; conservan la tarjeta si hay contradicción real
(cliente distinto en la fila) o si la fila sigue sucia.
"""
from __future__ import annotations

import csv
import json

import pytest

from atlas_core.catalogo_clientes import CatalogoClientes, EstadoCalidadCliente
from atlas_core.catalogo_destinos import CatalogoDestinos, EstadoCalidadDestino
from atlas_core.catalogo_obras_destinos import (
    CatalogoObrasDestinos, Evidencia, ResultadoEvidencia, TipoEvidencia,
)
from atlas_core.decisiones_pendientes import (
    _clientes_confirmados_por_humano_por_guia,
    _obras_con_relacion_confirmada_por_humano_por_guia,
    crear_decision,
    regenerar_decisiones_persistidas,
)
from atlas_core.fuente_catalogos import ARCHIVOS_REQUERIDOS
from atlas_core.procesamiento_masivo import COLUMNAS


# --------------------------------------------------------------------------
# Fixtures mínimas
# --------------------------------------------------------------------------


def _catalogos_base(carpeta):
    contenidos = {
        "choferes.json": {},
        "clientes.json": {"version_formato": 1, "clientes": []},
        "empresas.json": {},
        "destinos_maestros.json": {"version_formato": 1, "destinos": []},
        "vehiculos.json": {},
        "plantas.json": {"plantas": []},
        "rutas.json": {"rutas": []},
    }
    for nombre in ARCHIVOS_REQUERIDOS:
        (carpeta / nombre).write_text(json.dumps(contenidos[nombre]), encoding="utf-8")
    (carpeta / "obras_destinos.json").write_text(
        json.dumps({"version_formato": 1, "obras": [], "relaciones": []}), encoding="utf-8",
    )


def _fila(**overrides):
    fila = {c: "" for c in COLUMNAS}
    fila.update({
        "archivo": "472037.jpeg", "estado_procesamiento": "OK",
        "numero_guia": "472037", "numero_transporte": "0000354034", "fecha": "21-08-2026",
        "indicador_revision": "OK", "estado_documental": "OK", "estado_operacional": "OK",
        "estado_ruta": "RUTA_CALCULADA", "motivo_ruta": "",
        "cliente": "", "rut_cliente": "No encontrado", "obra_destino": "",
    })
    fila.update(overrides)
    return fila


def _dataset(actual, filas):
    ruta = actual / "analisis_completo_guias.csv"
    with ruta.open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNAS, delimiter=";")
        w.writeheader()
        w.writerows(filas)
    return ruta


def _ledger(actual, aplicaciones):
    (actual / "decisiones_aplicadas.json").write_text(
        json.dumps({"schema_version": 1, "aplicaciones": aplicaciones}), encoding="utf-8",
    )


def _decision_cliente_candidato(*, numero_guia, valor_documental, cliente_id, valor_canonico, rut=""):
    return crear_decision(
        tipo="CLIENTE_CANDIDATO", entidad="CLIENTE", archivo=f"{numero_guia}.jpeg",
        numero_guia=numero_guia, numero_transporte="0000354034", campo="cliente",
        valor_documental=valor_documental, valor_normalizado=valor_documental,
        identidad_resuelta={"entidad_id": cliente_id, "valor_canonico": valor_canonico, "rut": rut},
        candidatos=({"entidad_id": cliente_id, "valor_canonico": valor_canonico, "rut": rut},),
        motivos=("NOMBRE_SIN_RUT_CORROBORABLE",),
        evidencias=({"tipo": "NOMBRE_COINCIDENCIA_SEGURA", "campo": "cliente", "valor": valor_documental},),
        acciones_permitidas=("CONFIRMAR", "NO_CONFIRMAR", "POSPONER"),
    )


def _decision_destino_sin_confirmar(*, numero_guia, obra_id, obra_canonica, cliente_id, destino_documental):
    return crear_decision(
        tipo="DESTINO_SIN_CONFIRMAR", entidad="RELACION_OBRA_DESTINO", archivo=f"{numero_guia}.jpeg",
        numero_guia=numero_guia, numero_transporte="0000354349", campo="destino_entrega",
        valor_documental=destino_documental, valor_normalizado=destino_documental,
        identidad_resuelta={"entidad_id": obra_id, "valor_canonico": obra_canonica},
        candidatos=(), motivos=("OBRA_SIN_RELACION_CONFIRMADA_UNICA",),
        evidencias=({"tipo": "OBRA_IDENTIFICADA", "entidad_id": obra_id},),
        acciones_permitidas=("CONFIRMAR", "NO_CONFIRMAR", "POSPONER"),
        contexto={
            "cliente_id": cliente_id, "obra_id": obra_id, "obra_canonica": obra_canonica,
            "destino_documental": destino_documental,
        },
    )


def _obra_con_dos_relaciones_confirmadas(catalogos, *, cliente_id, nombre_obra, guias):
    """Registra `nombre_obra` con una relación CONFIRMADA por cada guía de
    `guias` (evidencia GUIA que la cita) -- deja a la obra con DOS
    relaciones confirmadas, igual que el caso real, para que el resolver
    de unicidad ya existente se abstenga y sea la regla nueva la que
    decide."""
    destinos = CatalogoDestinos(catalogos / "destinos_maestros.json", ruta_clientes=catalogos / "clientes.json")
    obras = CatalogoObrasDestinos(
        ruta=catalogos / "obras_destinos.json", ruta_clientes=catalogos / "clientes.json",
        ruta_destinos=catalogos / "destinos_maestros.json",
    )
    obra_id = None
    for i, guia in enumerate(guias):
        destino = destinos.crear(
            cliente_id="", nombre_destino=f"CALLE REAL {i} 100", direccion=f"CALLE REAL {i} 100, SANTIAGO",
            pais="CHILE", fuente="TEST", estado_calidad=EstadoCalidadDestino.CONFIRMADO,
        )
        obs = obras.registrar_observacion(
            cliente_id=cliente_id, nombre_obra=nombre_obra, destino_id=destino.destino_id,
            evidencia=Evidencia(
                tipo=TipoEvidencia.GUIA.value, identificador_fuente=guia, referencia_hash="a" * 64,
                campos_observados={"obra": nombre_obra, "numero_guia": guia},
                fecha="2026-08-20T00:00:00+00:00", actor_proceso="TEST",
                resultado=ResultadoEvidencia.SOPORTA.value,
            ),
        )
        obras.confirmar_relacion(obs.relacion.relacion_id, actor="JAVIER_DESKTOP", identificador_fuente=guia)
        obra_id = obs.obra.obra_id
    return obra_id


# --------------------------------------------------------------------------
# CLIENTE_CANDIDATO
# --------------------------------------------------------------------------


def test_cliente_candidato_se_retira_con_confirmacion_humana_pese_a_drift_ocr(tmp_path):
    catalogos = tmp_path / "catalogos"; catalogos.mkdir(); _catalogos_base(catalogos)
    actual = tmp_path / "actual"; actual.mkdir()
    cliente = CatalogoClientes(catalogos / "clientes.json").crear(
        razon_social="COMERCIAL A Y B LTDA", rut="78634910-9", fuente="TEST",
        estado_calidad=EstadoCalidadCliente.CONFIRMADO,
    )
    _ledger(actual, [{
        "tipo": "CLIENTE_CANDIDATO", "accion": "CONFIRMAR", "actor": "JAVIER_DESKTOP",
        "documento": {"numero_guia": "472037"}, "cliente_id": cliente.cliente_id,
        "valor_documental": "COMERCIAL A Y B LTDA", "valor_canonico": "COMERCIAL A Y B LTDA",
    }])
    dataset = _dataset(actual, [_fila(cliente="COMERCIAL A Y B LTDA")])
    decision = _decision_cliente_candidato(
        numero_guia="472037", valor_documental="CONERCIAL A Y B LTDA",  # drift OCR
        cliente_id=cliente.cliente_id, valor_canonico="COMERCIAL A Y B LTDA", rut="78634910-9",
    )
    salida = regenerar_decisiones_persistidas(
        decisiones=[decision], carpeta_catalogos=catalogos, ruta_dataset=dataset,
    )
    assert salida == []


def test_cliente_candidato_se_conserva_si_la_fila_resuelve_a_otro_cliente(tmp_path):
    catalogos = tmp_path / "catalogos"; catalogos.mkdir(); _catalogos_base(catalogos)
    actual = tmp_path / "actual"; actual.mkdir()
    cliente = CatalogoClientes(catalogos / "clientes.json").crear(
        razon_social="COMERCIAL A Y B LTDA", rut="78634910-9", fuente="TEST",
        estado_calidad=EstadoCalidadCliente.CONFIRMADO,
    )
    _ledger(actual, [{
        "tipo": "CLIENTE_CANDIDATO", "accion": "CONFIRMAR", "actor": "JAVIER_DESKTOP",
        "documento": {"numero_guia": "472037"}, "cliente_id": cliente.cliente_id,
    }])
    dataset = _dataset(actual, [_fila(cliente="OTRA EMPRESA TOTALMENTE DISTINTA SA")])
    decision = _decision_cliente_candidato(
        numero_guia="472037", valor_documental="CONERCIAL A Y B LTDA",
        cliente_id=cliente.cliente_id, valor_canonico="COMERCIAL A Y B LTDA",
    )
    salida = regenerar_decisiones_persistidas(
        decisiones=[decision], carpeta_catalogos=catalogos, ruta_dataset=dataset,
    )
    assert [d["decision_id"] for d in salida] == [decision["decision_id"]]


def test_cliente_candidato_se_conserva_sin_confirmacion_humana_en_ledger(tmp_path):
    catalogos = tmp_path / "catalogos"; catalogos.mkdir(); _catalogos_base(catalogos)
    actual = tmp_path / "actual"; actual.mkdir()
    cliente = CatalogoClientes(catalogos / "clientes.json").crear(
        razon_social="COMERCIAL A Y B LTDA", rut="78634910-9", fuente="TEST",
        estado_calidad=EstadoCalidadCliente.CONFIRMADO,
    )
    _ledger(actual, [])  # nadie confirmó nada
    dataset = _dataset(actual, [_fila(cliente="COMERCIAL A Y B LTDA")])
    decision = _decision_cliente_candidato(
        numero_guia="472037", valor_documental="CONERCIAL A Y B LTDA",
        cliente_id=cliente.cliente_id, valor_canonico="COMERCIAL A Y B LTDA",
    )
    salida = regenerar_decisiones_persistidas(
        decisiones=[decision], carpeta_catalogos=catalogos, ruta_dataset=dataset,
    )
    assert [d["decision_id"] for d in salida] == [decision["decision_id"]]


# --------------------------------------------------------------------------
# DESTINO_SIN_CONFIRMAR
# --------------------------------------------------------------------------


def test_destino_sin_confirmar_se_retira_con_relacion_confirmada_que_cita_la_guia(tmp_path):
    catalogos = tmp_path / "catalogos"; catalogos.mkdir(); _catalogos_base(catalogos)
    actual = tmp_path / "actual"; actual.mkdir()
    cliente = CatalogoClientes(catalogos / "clientes.json").crear(
        razon_social="PRODALAM SA", rut="93772000-9", fuente="TEST",
        estado_calidad=EstadoCalidadCliente.CONFIRMADO,
    )
    obra_id = _obra_con_dos_relaciones_confirmadas(
        catalogos, cliente_id=cliente.cliente_id, nombre_obra="EMPRESA CONST SIGRO",
        guias=["464550", "472227"],
    )
    _ledger(actual, [])
    dataset = _dataset(actual, [_fila(
        numero_guia="472227", archivo="472227.jpeg", cliente="PRODALAM SA",
        obra_destino="EMPRESA CONST SIGRO", direccion_entrega="AVDA IRARRAZAVAL 5497 SANTIAGO NUNOA",
        indicador_revision="OK", estado_operacional="OK", estado_ruta="RUTA_CALCULADA",
    )])
    decision = _decision_destino_sin_confirmar(
        numero_guia="472227", obra_id=obra_id, obra_canonica="EMPRESA CONST SIGRO",
        cliente_id=cliente.cliente_id,
        destino_documental="Jefe de Adquisiciones astructora Sigro S.A",  # basura OCR
    )
    salida = regenerar_decisiones_persistidas(
        decisiones=[decision], carpeta_catalogos=catalogos, ruta_dataset=dataset,
    )
    assert salida == []


def test_destino_sin_confirmar_se_conserva_si_la_fila_no_esta_limpia(tmp_path):
    catalogos = tmp_path / "catalogos"; catalogos.mkdir(); _catalogos_base(catalogos)
    actual = tmp_path / "actual"; actual.mkdir()
    cliente = CatalogoClientes(catalogos / "clientes.json").crear(
        razon_social="PRODALAM SA", rut="93772000-9", fuente="TEST",
        estado_calidad=EstadoCalidadCliente.CONFIRMADO,
    )
    obra_id = _obra_con_dos_relaciones_confirmadas(
        catalogos, cliente_id=cliente.cliente_id, nombre_obra="EMPRESA CONST SIGRO",
        guias=["464550", "472227"],
    )
    _ledger(actual, [])
    dataset = _dataset(actual, [_fila(
        numero_guia="472227", archivo="472227.jpeg", cliente="PRODALAM SA",
        obra_destino="EMPRESA CONST SIGRO",
        indicador_revision="REVISAR", estado_operacional="REQUIERE_REVISION", estado_ruta="RUTA_CALCULADA",
    )])
    decision = _decision_destino_sin_confirmar(
        numero_guia="472227", obra_id=obra_id, obra_canonica="EMPRESA CONST SIGRO",
        cliente_id=cliente.cliente_id, destino_documental="Jefe de Adquisiciones astructora Sigro S.A",
    )
    salida = regenerar_decisiones_persistidas(
        decisiones=[decision], carpeta_catalogos=catalogos, ruta_dataset=dataset,
    )
    assert [d["decision_id"] for d in salida] == [decision["decision_id"]]


def test_destino_sin_confirmar_se_conserva_si_la_relacion_confirmada_no_cita_esta_guia(tmp_path):
    catalogos = tmp_path / "catalogos"; catalogos.mkdir(); _catalogos_base(catalogos)
    actual = tmp_path / "actual"; actual.mkdir()
    cliente = CatalogoClientes(catalogos / "clientes.json").crear(
        razon_social="PRODALAM SA", rut="93772000-9", fuente="TEST",
        estado_calidad=EstadoCalidadCliente.CONFIRMADO,
    )
    obra_id = _obra_con_dos_relaciones_confirmadas(
        catalogos, cliente_id=cliente.cliente_id, nombre_obra="EMPRESA CONST SIGRO",
        guias=["464550", "460001"],  # NO cita 472227
    )
    _ledger(actual, [])
    dataset = _dataset(actual, [_fila(
        numero_guia="472227", archivo="472227.jpeg", cliente="PRODALAM SA",
        obra_destino="EMPRESA CONST SIGRO",
        indicador_revision="OK", estado_operacional="OK", estado_ruta="RUTA_CALCULADA",
    )])
    decision = _decision_destino_sin_confirmar(
        numero_guia="472227", obra_id=obra_id, obra_canonica="EMPRESA CONST SIGRO",
        cliente_id=cliente.cliente_id, destino_documental="Jefe de Adquisiciones astructora Sigro S.A",
    )
    salida = regenerar_decisiones_persistidas(
        decisiones=[decision], carpeta_catalogos=catalogos, ruta_dataset=dataset,
    )
    assert [d["decision_id"] for d in salida] == [decision["decision_id"]]


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def test_helper_clientes_confirmados_por_guia_lee_todas_las_formas(tmp_path):
    ruta = tmp_path / "decisiones_aplicadas.json"
    ruta.write_text(json.dumps({"aplicaciones": [
        {"tipo": "CLIENTE_CANDIDATO", "accion": "CONFIRMAR",
         "documento": {"numero_guia": "1"}, "cliente_id": "c1"},
        {"tipo": "CLIENTE_AUSENTE", "accion": "REGISTRAR_CLIENTE_MANUAL",
         "documento": {"numero_guia": "2"}, "cliente_id": "c2"},
        {"tipo": "CLIENTE_CANDIDATO", "accion": "NO_CONFIRMAR",
         "documento": {"numero_guia": "3"}, "cliente_id": "c3"},   # no cuenta
        {"tipo": "OBRA_DESCONOCIDA", "accion": "REGISTRAR",
         "documento": {"numero_guia": "4"}, "obra_id": "o4"},       # no cuenta
    ]}), encoding="utf-8")
    assert _clientes_confirmados_por_humano_por_guia(ruta) == {"1": {"c1"}, "2": {"c2"}}


def test_helper_clientes_confirmados_por_guia_tolera_ledger_ausente(tmp_path):
    assert _clientes_confirmados_por_humano_por_guia(tmp_path / "no_existe.json") == {}


def test_helper_obras_relacion_confirmada_none_no_rompe():
    assert _obras_con_relacion_confirmada_por_humano_por_guia(None) == {}


def test_helper_obras_relacion_confirmada_mapea_guia_a_obra(tmp_path):
    catalogos = tmp_path / "catalogos"; catalogos.mkdir(); _catalogos_base(catalogos)
    cliente = CatalogoClientes(catalogos / "clientes.json").crear(
        razon_social="PRODALAM SA", rut="93772000-9", fuente="TEST",
        estado_calidad=EstadoCalidadCliente.CONFIRMADO,
    )
    obra_id = _obra_con_dos_relaciones_confirmadas(
        catalogos, cliente_id=cliente.cliente_id, nombre_obra="EMPRESA CONST SIGRO",
        guias=["464550", "472227"],
    )
    catalogo = CatalogoObrasDestinos(
        ruta=catalogos / "obras_destinos.json", ruta_clientes=catalogos / "clientes.json",
        ruta_destinos=catalogos / "destinos_maestros.json",
    )
    mapa = _obras_con_relacion_confirmada_por_humano_por_guia(catalogo)
    assert mapa.get("464550") == {obra_id}
    assert mapa.get("472227") == {obra_id}
