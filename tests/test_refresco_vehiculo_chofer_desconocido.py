"""Bloque REFRESCO ESTRUCTURAL VEHICULO/CHOFER DESCONOCIDO -- casos
reales del lote 20260916_151401, después de que REPROCESAMIENTO_
REPARADOR corrigiera el dataset:

- 473325: `VEHICULO_DESCONOCIDO` sobre `patente_tracto="2PAR67"`
  (basura OCR), el dataset ya trae `patente_tracto="BPHR67"` (reparado).
- 473326: `CHOFER_DESCONOCIDO` sobre `chofer="CRISIOPHER RSTAVAR BPHR
  NETOS"` (basura OCR), el dataset ya trae `chofer="CRISTOPHER
  RETAMAL"` (reparado).

Ninguna de las dos tarjetas puede sobrevivir con la evidencia vieja: la
pregunta original ("¿qué patente/chofer es este valor documental?") ya
no corresponde al documento vigente. `regenerar_decisiones_persistidas`
(con `ruta_dataset`) debe descartarlas -- una tarjeta fresca, si el
campo reparado TODAVÍA la necesita, se publica en la próxima detección
real (fuera del alcance de este test, que ejercita sólo la
retirada)."""
from __future__ import annotations

import csv

from atlas_core.decisiones_pendientes import crear_decision, regenerar_decisiones_persistidas
from atlas_core.procesamiento_masivo import COLUMNAS


def _catalogos_vacios(tmp_path):
    import json
    carpeta = tmp_path / "catalogos"
    carpeta.mkdir()
    for nombre, contenido in {
        "clientes.json": {"version_formato": 1, "clientes": []},
        "obras_destinos.json": {"version_formato": 1, "obras": [], "relaciones": []},
        "destinos_maestros.json": {"version_formato": 1, "destinos": []},
        "vehiculos.json": {"version": 1, "vehiculos": []},
        "plantas.json": {"version_formato": 1, "plantas": []},
    }.items():
        (carpeta / nombre).write_text(json.dumps(contenido), encoding="utf-8")
    return carpeta


def _fila(**overrides):
    fila = {c: "" for c in COLUMNAS}
    fila.update({
        "archivo": "473325.jpeg", "estado_procesamiento": "OK", "numero_guia": "473325",
        "numero_transporte": "0000357133", "fecha": "04-09-2026",
        "chofer": "CRISTOPHER RETAMAL", "rut_chofer": "17576134-9",
        "cliente": "PRODALAM SA", "obra_destino": "EMPRESA CONST SIGRO SA",
        "patente_tracto": "BPHR67", "patente_rampla": "No encontrado",
        "motivos_revision_documento": "", "indicador_revision": "OK",
        "estado_documental": "OK", "estado_ruta": "",
    })
    fila.update(overrides)
    return fila


def _escribir_csv(ruta, filas):
    with ruta.open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader()
        escritor.writerows(filas)


def _decision_vehiculo_desconocido(*, archivo, numero_guia, valor_documental):
    return crear_decision(
        tipo="VEHICULO_DESCONOCIDO", entidad="VEHICULO", archivo=archivo,
        numero_guia=numero_guia, numero_transporte="No encontrado", campo="patente_tracto",
        valor_documental=valor_documental, valor_normalizado=valor_documental,
        identidad_resuelta=None, candidatos=[], motivos=["SIN_VEHICULO_CONFIRMADO_COMPATIBLE"],
        evidencias=[{"tipo": "OCR_DOCUMENTAL", "campo": "patente_tracto", "valor": valor_documental}],
        acciones_permitidas=["REGISTRAR", "NO_REGISTRAR", "POSPONER"],
        tipo_resolucion="REQUIERE_CONFIRMACION_HUMANA", tipo_vehiculo_propuesto=None,
    )


def _decision_chofer_desconocido(*, archivo, numero_guia, valor_documental):
    return crear_decision(
        tipo="CHOFER_DESCONOCIDO", entidad="CHOFER", archivo=archivo,
        numero_guia=numero_guia, numero_transporte="No encontrado", campo="chofer",
        valor_documental=valor_documental, valor_normalizado=valor_documental,
        identidad_resuelta=None, candidatos=[], motivos=["SIN_CHOFER_CONFIRMADO_COMPATIBLE"],
        evidencias=[{"tipo": "OCR_DOCUMENTAL", "campo": "chofer", "valor": valor_documental}],
        acciones_permitidas=["REGISTRAR", "NO_REGISTRAR", "POSPONER"],
    )


def test_473325_vehiculo_desconocido_basado_en_patente_obsoleta_se_retira(tmp_path):
    catalogos = _catalogos_vacios(tmp_path)
    dataset = tmp_path / "analisis_completo_guias.csv"
    _escribir_csv(dataset, [_fila(patente_tracto="BPHR67")])  # ya reparado

    decision_vieja = _decision_vehiculo_desconocido(
        archivo="473325.jpeg", numero_guia="473325", valor_documental="2PAR67",  # evidencia obsoleta
    )
    restantes = regenerar_decisiones_persistidas(
        decisiones=[decision_vieja], carpeta_catalogos=catalogos, ruta_dataset=dataset,
    )
    assert decision_vieja["decision_id"] not in {d["decision_id"] for d in restantes}


def test_473326_chofer_desconocido_basado_en_texto_obsoleto_se_retira(tmp_path):
    catalogos = _catalogos_vacios(tmp_path)
    dataset = tmp_path / "analisis_completo_guias.csv"
    _escribir_csv(dataset, [_fila(
        archivo="473326.jpeg", numero_guia="473326", chofer="CRISTOPHER RETAMAL",
    )])  # ya reparado

    decision_vieja = _decision_chofer_desconocido(
        archivo="473326.jpeg", numero_guia="473326",
        valor_documental="CRISIOPHER RSTAVAR BPHR NETOS",  # evidencia obsoleta
    )
    restantes = regenerar_decisiones_persistidas(
        decisiones=[decision_vieja], carpeta_catalogos=catalogos, ruta_dataset=dataset,
    )
    assert decision_vieja["decision_id"] not in {d["decision_id"] for d in restantes}


def test_decision_legitima_vigente_sobrevive(tmp_path):
    """Una VEHICULO_DESCONOCIDO cuya evidencia SIGUE coincidiendo con el
    dataset vigente (nada la reparó, la pregunta sigue siendo real) debe
    conservarse -- el fix no puede volverse una purga general."""
    catalogos = _catalogos_vacios(tmp_path)
    dataset = tmp_path / "analisis_completo_guias.csv"
    _escribir_csv(dataset, [_fila(archivo="473999.jpeg", numero_guia="473999", patente_tracto="ZZ1234")])

    decision_vigente = _decision_vehiculo_desconocido(
        archivo="473999.jpeg", numero_guia="473999", valor_documental="ZZ1234",  # coincide con el dataset
    )
    restantes = regenerar_decisiones_persistidas(
        decisiones=[decision_vigente], carpeta_catalogos=catalogos, ruta_dataset=dataset,
    )
    assert decision_vigente["decision_id"] in {d["decision_id"] for d in restantes}


def test_decision_ya_resuelta_en_ledger_no_resurge(tmp_path):
    """`ids_resueltos` (ledger humano ya aplicado) sigue excluyendo
    decisiones terminales exactamente igual con este fix -- el refresco
    estructural nuevo no interfiere con ese filtro ya existente."""
    catalogos = _catalogos_vacios(tmp_path)
    dataset = tmp_path / "analisis_completo_guias.csv"
    _escribir_csv(dataset, [_fila(archivo="473999.jpeg", numero_guia="473999", patente_tracto="ZZ1234")])

    decision_ya_resuelta = _decision_vehiculo_desconocido(
        archivo="473999.jpeg", numero_guia="473999", valor_documental="ZZ1234",
    )
    restantes = regenerar_decisiones_persistidas(
        decisiones=[decision_ya_resuelta], carpeta_catalogos=catalogos, ruta_dataset=dataset,
        ids_resueltos=[decision_ya_resuelta["decision_id"]],
    )
    assert restantes == []


def test_decisiones_de_otras_guias_no_relacionadas_no_se_tocan(tmp_path):
    """Retirar la tarjeta obsoleta de una guía nunca debe afectar una
    decisión legítima de OTRA guía no relacionada."""
    catalogos = _catalogos_vacios(tmp_path)
    dataset = tmp_path / "analisis_completo_guias.csv"
    _escribir_csv(dataset, [
        _fila(archivo="473325.jpeg", numero_guia="473325", patente_tracto="BPHR67"),
        _fila(archivo="473999.jpeg", numero_guia="473999", patente_tracto="ZZ1234"),
    ])

    obsoleta = _decision_vehiculo_desconocido(
        archivo="473325.jpeg", numero_guia="473325", valor_documental="2PAR67",
    )
    vigente = _decision_vehiculo_desconocido(
        archivo="473999.jpeg", numero_guia="473999", valor_documental="ZZ1234",
    )
    restantes = regenerar_decisiones_persistidas(
        decisiones=[obsoleta, vigente], carpeta_catalogos=catalogos, ruta_dataset=dataset,
    )
    ids = {d["decision_id"] for d in restantes}
    assert obsoleta["decision_id"] not in ids
    assert vigente["decision_id"] in ids
