"""B1 -- corrección segura del CHOFER OPERACIONAL de una guía (lenguaje
natural y tarjeta de Revisión). Sólo fixtures sintéticas: nunca G: ni datos
productivos. Cubre corrección normal, RUT impreso contradictorio, chofer
inexistente/inactivo, guías hermanas, revalidación/relectura posterior,
persistencia tras reinicio y asignaciones de vehículos intactas."""
from __future__ import annotations

import csv
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from atlas_core.acciones_operacionales import CapaAccionesOperacionales
from atlas_core.b1_operador import (
    ACCION_CHOFER_OPERACIONAL, OperadorB1, es_confirmacion, es_confirmacion_discrepancia, interpretar_determinista,
)
from atlas_core.chofer_operacional import (
    TIPO_LEDGER_CHOFER_OPERACIONAL, choferes_operacionales_por_ledger, retirar_decisiones_chofer_operacional,
)
from atlas_core.decisiones_pendientes import crear_decision, generar_artefacto
from atlas_core.procesamiento_masivo import COLUMNAS
from atlas_core.reporte_viajes import generar_reporte_viajes
from atlas_core.revalidacion_documental import (
    reconciliar_bandeja_decisiones, revalidar_chofer_sin_corroborar_por_catalogo_sin_ocr,
)
from tests.test_acciones_operacionales import RUT_ACTIVO, _fila, entorno  # noqa: F401 -- fixture compartida


def _rut(cuerpo: int) -> str:
    suma, factor = 0, 2
    for digito in reversed(str(cuerpo)):
        suma += int(digito) * factor
        factor = 2 if factor == 7 else factor + 1
    dv = 11 - suma % 11
    return f"{cuerpo}-{'0' if dv == 11 else 'K' if dv == 10 else dv}"


RUT_PEDRO = _rut(15333444)
RUT_CARLOS = _rut(16555666)
CANON_PEDRO = "15.333.444-7"  # formato canónico del catálogo
TRANSPORTE = "0000600001"
GUIA, HERMANA, DISCREPANTE = "600001", "600002", "600003"
INSTRUCCION = f"El chofer de la guía {GUIA} es PEDRO MUNOZ"


def _filas(entorno):
    with entorno["dataset"].open(encoding="utf-8-sig", newline="") as archivo:
        return {f["archivo"]: f for f in csv.DictReader(archivo, delimiter=";")}


def _escribir(entorno, filas):
    with entorno["dataset"].open("w", encoding="utf-8-sig", newline="") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader()
        escritor.writerows(filas)


def _sha(ruta: Path) -> str:
    return hashlib.sha256(ruta.read_bytes()).hexdigest()


def _bandeja(entorno):
    return json.loads((entorno["actual"] / "decisiones_pendientes.json").read_text(encoding="utf-8"))["decisiones"]


def _ledger(entorno):
    return json.loads((entorno["actual"] / "decisiones_aplicadas.json").read_text(encoding="utf-8"))["aplicaciones"]


def _tarjeta_chofer(guia, nombre, rut_impreso, tipo="CHOFER_CANDIDATO"):
    return crear_decision(
        tipo=tipo, entidad="CHOFER", archivo=f"{guia}.jpeg", numero_guia=guia, numero_transporte=TRANSPORTE,
        campo="chofer", valor_documental=nombre, valor_normalizado=nombre, identidad_resuelta=None,
        candidatos=[{"nombre": "PEDRO MUNOZ", "rut": RUT_PEDRO}] if tipo == "CHOFER_CANDIDATO" else (),
        motivos=("CHOFER_SIN_CORROBORAR_REQUIERE_CONFIRMACION",),
        evidencias=({"tipo": "RUT_DOCUMENTAL", "valor": rut_impreso},),
        acciones_permitidas=("CONFIRMAR", "NO_CONFIRMAR", "POSPONER"))


@pytest.fixture
def con_choferes(entorno):
    """Transporte 0000600001 con tres guías:
    - 600001: nombre impreso ilegible, sin RUT, CHOFER_SIN_CORROBORAR + tarjeta.
    - 600002 (hermana): LUIS REYES corroborado; nunca debe cambiar.
    - 600003: nombre ilegible con el RUT impreso de LUIS REYES (discrepancia
      si se propone a PEDRO MUNOZ) + tarjeta."""
    catalogo = json.loads((entorno["cat"] / "choferes.json").read_text(encoding="utf-8"))
    catalogo[RUT_PEDRO.replace("-", "")] = {"nombre": "PEDRO MUNOZ", "rut": RUT_PEDRO, "aliases": [], "activo": True}
    catalogo[RUT_CARLOS.replace("-", "")] = {"nombre": "CARLOS DIAZ", "rut": RUT_CARLOS, "aliases": [], "activo": True}
    (entorno["cat"] / "choferes.json").write_text(json.dumps(catalogo), encoding="utf-8")
    revisar = {"motivos_revision_documento": "CHOFER_SIN_CORROBORAR", "indicador_revision": "REVISAR",
               "estado_documental": "REQUIERE_REVISION", "estado_operacional": "REQUIERE_REVISION"}
    filas = list(_filas(entorno).values()) + [
        _fila(GUIA, numero_transporte=TRANSPORTE, chofer="PDRO MUNO", rut_chofer="No encontrado",
              patente_rampla="JK2501", peso_kg="28000", **revisar),
        _fila(HERMANA, numero_transporte=TRANSPORTE, patente_rampla="JK2501", peso_kg="1000"),
        _fila(DISCREPANTE, numero_transporte=TRANSPORTE, chofer="PEDR MNZ", rut_chofer=RUT_ACTIVO,
              patente_rampla="JK2501", peso_kg="1000", **revisar),
    ]
    _escribir(entorno, filas)
    tarjeta = _tarjeta_chofer(GUIA, "PDRO MUNO", "No encontrado")
    tarjeta_discrepante = _tarjeta_chofer(DISCREPANTE, "PEDR MNZ", RUT_ACTIVO)
    generar_artefacto(ruta_dataset=entorno["dataset"], carpeta_catalogos=entorno["cat"],
                      decisiones=[entorno["decision"], tarjeta, tarjeta_discrepante])
    entorno.update(tarjeta=tarjeta["decision_id"], tarjeta_discrepante=tarjeta_discrepante["decision_id"])
    return entorno


def _estado_documental(fila):
    return {k: v for k, v in fila.items()
            if k not in {"motivos_revision_documento", "indicador_revision", "estado_documental", "estado_operacional"}}


# ------------------------------------------------------------ interpretación


@pytest.mark.parametrize("texto", [
    INSTRUCCION,
    f"el chofer de la guia {GUIA} es Pedro Munoz",
    f"El chofer correcto de la guía N° {GUIA} es PEDRO MUNOZ.",
    f"Chofer de la guía {GUIA}: PEDRO MUNOZ",
    f"En la guía {GUIA} el chofer es PEDRO MUNOZ",
    f"en la guia {GUIA}, el conductor correcto es PEDRO MUNOZ",
    f"Corrige el chofer de la guía {GUIA} a PEDRO MUNOZ",
    f"cambia el chofer de la guia {GUIA} por el chofer PEDRO MUNOZ",
])
def test_frases_de_chofer_operacional(texto):
    intencion = interpretar_determinista(texto)
    assert intencion.accion == ACCION_CHOFER_OPERACIONAL
    assert intencion.parametros["numero_guia"] == GUIA
    assert intencion.menciones == {"chofer": "PEDRO MUNOZ"}


def test_chofer_por_rut_se_acepta_como_mencion():
    intencion = interpretar_determinista(f"El chofer de la guía {GUIA} es {RUT_PEDRO}")
    assert intencion.accion == ACCION_CHOFER_OPERACIONAL and intencion.menciones == {"chofer": RUT_PEDRO}


@pytest.mark.parametrize("texto", [f"¿El chofer de la guía {GUIA} es PEDRO MUNOZ?",
                                   f"¿Quién es el chofer de la guía {GUIA}?"])
def test_preguntas_sobre_el_chofer_nunca_son_correcciones(texto):
    intencion = interpretar_determinista(texto)
    assert intencion is None or intencion.accion != ACCION_CHOFER_OPERACIONAL


def test_confirmacion_administrativa_es_especifica():
    assert es_confirmacion_discrepancia("Confirmo la discrepancia de RUT")
    assert es_confirmacion_discrepancia("confirmo discrepancia del rut.")
    assert not es_confirmacion_discrepancia("sí")
    assert not es_confirmacion("confirmo la discrepancia de RUT")


# ------------------------------------------------------------ corrección normal


def test_preview_muestra_actual_propuesto_rut_y_guia_sin_escribir(con_choferes):
    antes = {p.name: _sha(p) for p in con_choferes["actual"].iterdir() if p.is_file()}
    r = OperadorB1(con_choferes["raiz"]).atender("conv-chofer", INSTRUCCION)
    assert r["estado"] == "PREVIEW_PENDIENTE", r
    assert "confirmacion_requerida" not in r and r["mensaje"].endswith("¿Confirmas? (sí / no)")
    preview = r["preview"]
    assert preview["accion"] == ACCION_CHOFER_OPERACIONAL and "token" not in preview
    assert preview["entidad"]["numero_guia"] == GUIA and preview["entidad"]["id"] == f"{GUIA}.jpeg"
    assert preview["valor_actual"]["chofer"] == "PDRO MUNO" and preview["valor_actual"]["rut_documental"] == "No encontrado"
    assert preview["valor_propuesto"] == {"chofer": "PEDRO MUNOZ", "rut_chofer": CANON_PEDRO,
                                          "discrepancia_rut": False, "discrepancia_confirmada": False}
    assert preview["afectados"]["guias"] == [GUIA]
    assert preview["afectados"]["guias_hermanas_sin_cambios"] == [HERMANA, DISCREPANTE]
    assert f"guía {GUIA}" in r["mensaje"] and "PEDRO MUNOZ" in r["mensaje"] and CANON_PEDRO in r["mensaje"]
    despues = {p.name: _sha(p) for p in con_choferes["actual"].iterdir() if p.is_file()}
    assert {k: v for k, v in antes.items() if k != "acciones_operacionales.json"} == {
        k: v for k, v in despues.items() if k in antes and k != "acciones_operacionales.json"}


def test_confirmacion_fija_solo_identidad_operacional_con_auditoria(con_choferes):
    filas_antes = _filas(con_choferes)
    catalogos_antes = {p.name: _sha(p) for p in con_choferes["cat"].iterdir()}
    b1 = OperadorB1(con_choferes["raiz"], usuario="JAVIER")
    assert b1.atender("conv-chofer", INSTRUCCION)["estado"] == "PREVIEW_PENDIENTE"
    r = b1.atender("conv-chofer", "sí")
    assert r["estado"] == "EJECUTADA", r
    assert r["resultado"]["persistencia_verificada"] is True
    assert "PEDRO MUNOZ" in r["mensaje"] and "RUT impreso" in r["mensaje"]

    filas = _filas(con_choferes)
    objetivo = filas[f"{GUIA}.jpeg"]
    # Lo documental (nombre y RUT impresos) intacto; sólo se retira el motivo de identidad.
    assert _estado_documental(objetivo) == _estado_documental(filas_antes[f"{GUIA}.jpeg"])
    assert objetivo["chofer"] == "PDRO MUNO" and objetivo["rut_chofer"] == "No encontrado"
    assert "CHOFER_SIN_CORROBORAR" not in objetivo["motivos_revision_documento"]
    assert objetivo["indicador_revision"] == "OK"
    # Ninguna otra guía cambia (incluida la discrepante del mismo transporte).
    assert {k: v for k, v in filas.items() if k != f"{GUIA}.jpeg"} == {
        k: v for k, v in filas_antes.items() if k != f"{GUIA}.jpeg"}
    # Catálogos (choferes, vehículos/asignaciones) intactos.
    assert {p.name: _sha(p) for p in con_choferes["cat"].iterdir()} == catalogos_antes

    entrada = [a for a in _ledger(con_choferes) if a["tipo"] == TIPO_LEDGER_CHOFER_OPERACIONAL]
    assert len(entrada) == 1
    assert entrada[0]["chofer_operacional"] == {"nombre": "PEDRO MUNOZ", "rut": CANON_PEDRO}
    assert entrada[0]["chofer_documental"] == "PDRO MUNO" and entrada[0]["rut_documental"] == "No encontrado"
    assert entrada[0]["confirmado_por"] == "JAVIER" and entrada[0]["documento"]["numero_guia"] == GUIA
    auditoria = CapaAccionesOperacionales(con_choferes["raiz"]).auditoria()[-1]
    assert auditoria["accion"] == ACCION_CHOFER_OPERACIONAL and auditoria["resultado"] == "APLICADA"
    assert auditoria["confirmado_por"] == "JAVIER" and auditoria["respaldo"]

    # Tarjeta de esa guía retirada; la de la guía discrepante y la ajena siguen.
    ids = {d["decision_id"] for d in _bandeja(con_choferes)}
    assert con_choferes["tarjeta"] not in ids
    assert {con_choferes["tarjeta_discrepante"], con_choferes["decision"]["decision_id"]} <= ids
    assert con_choferes["tarjeta"] in r["resultado"]["decisiones_retiradas"]


def _viaje_reporte(raiz, salida):
    generar_reporte_viajes(raiz / "operacion" / "actual" / "analisis_completo_guias.csv", salida,
                           carpeta_catalogos=raiz / "catalogos_privados")
    with (salida / "viajes.csv").open(encoding="utf-8-sig", newline="") as archivo:
        return next(v for v in csv.DictReader(archivo, delimiter=";") if v["numero_transporte"] == TRANSPORTE)


def test_reporte_usa_chofer_operacional_y_conserva_evidencia_impresa(con_choferes, tmp_path):
    b1 = OperadorB1(con_choferes["raiz"], usuario="JAVIER")
    b1.atender("conv-chofer", INSTRUCCION)
    assert b1.atender("conv-chofer", "sí")["estado"] == "EJECUTADA"
    viaje = _viaje_reporte(con_choferes["raiz"], tmp_path / "reporte")
    assert "PEDRO MUNOZ" in viaje["choferes"] and CANON_PEDRO in viaje["ruts_chofer"]
    evidencia = {e["numero_guia"]: e for e in json.loads(viaje["evidencias_documentos"])}
    assert evidencia[GUIA]["chofer"] == "PDRO MUNO" and evidencia[GUIA]["rut_chofer"] == "No encontrado"
    # La hermana conserva su chofer: el conflicto queda visible, no se resuelve en silencio.
    assert "LUIS REYES" in viaje["choferes"] and evidencia[HERMANA]["chofer"] == "LUIS REYES"
    # Patentes (asignaciones tracto/rampla) sin cambios en el valor operacional.
    assert viaje["patentes_tracto"] == "KN5439" and viaje["patentes_rampla"] == "JK2501"


# ------------------------------------------------------------ RUT contradictorio


def test_rut_impreso_contradictorio_exige_confirmacion_administrativa(con_choferes):
    b1 = OperadorB1(con_choferes["raiz"], usuario="JAVIER")
    r = b1.atender("conv-disc", f"El chofer de la guía {DISCREPANTE} es PEDRO MUNOZ")
    assert r["estado"] == "PREVIEW_PENDIENTE" and r["confirmacion_requerida"] == "DISCREPANCIA_RUT", r
    assert r["preview"]["valor_propuesto"]["discrepancia_rut"] is True
    assert "DISCREPANCIA" in r["mensaje"] and RUT_ACTIVO in r["mensaje"] and "LUIS REYES" in r["mensaje"]
    assert "confirmo la discrepancia de RUT" in r["mensaje"]
    ledger_antes = _sha(con_choferes["actual"] / "decisiones_aplicadas.json")

    # Un "sí" normal NO aplica una discrepancia.
    no = b1.atender("conv-disc", "sí")
    assert no["estado"] == "PREVIEW_PENDIENTE" and no["confirmacion_requerida"] == "DISCREPANCIA_RUT"
    assert "No apliqué nada" in no["mensaje"]
    assert _sha(con_choferes["actual"] / "decisiones_aplicadas.json") == ledger_antes

    si = b1.atender("conv-disc", "Confirmo la discrepancia de RUT")
    assert si["estado"] == "EJECUTADA", si
    fila = _filas(con_choferes)[f"{DISCREPANTE}.jpeg"]
    assert fila["rut_chofer"] == RUT_ACTIVO and fila["chofer"] == "PEDR MNZ"  # RUT impreso intacto
    entrada = [a for a in _ledger(con_choferes) if a["tipo"] == TIPO_LEDGER_CHOFER_OPERACIONAL][-1]
    assert entrada["discrepancia_rut"] is True and entrada["discrepancia_confirmada"] is True
    assert entrada["rut_documental"] == RUT_ACTIVO


def test_capa_rechaza_discrepancia_sin_confirmacion_y_restaura(con_choferes):
    capa = CapaAccionesOperacionales(con_choferes["raiz"])
    ledger_antes = _sha(con_choferes["actual"] / "decisiones_aplicadas.json")
    dataset_antes = _sha(con_choferes["dataset"])
    preview = capa.previsualizar(ACCION_CHOFER_OPERACIONAL, {"numero_guia": DISCREPANTE, "chofer": RUT_PEDRO},
                                 actor="B1", origen="B1")
    assert preview["estado"] == "PREVIEW" and preview["valor_propuesto"]["discrepancia_rut"] is True
    r = capa.ejecutar(preview["token"], actor="B1", origen="B1", confirmado_por="JAVIER")
    assert r["estado"] == "FALLIDA" and r["codigo"] == "DISCREPANCIA_RUT_SIN_CONFIRMAR"
    assert _sha(con_choferes["actual"] / "decisiones_aplicadas.json") == ledger_antes
    assert _sha(con_choferes["dataset"]) == dataset_antes


def test_sin_confirmacion_humana_no_se_ejecuta(con_choferes):
    capa = CapaAccionesOperacionales(con_choferes["raiz"])
    preview = capa.previsualizar(ACCION_CHOFER_OPERACIONAL, {"numero_guia": GUIA, "chofer": RUT_PEDRO},
                                 actor="B1", origen="B1")
    r = capa.ejecutar(preview["token"], actor="B1", origen="B1", confirmado_por="")
    assert r["estado"] == "RECHAZADA" and r["codigo"] == "CONFIRMACION_REQUERIDA"
    assert not [a for a in _ledger(con_choferes) if a["tipo"] == TIPO_LEDGER_CHOFER_OPERACIONAL]


# ------------------------------------------------------------ chofer inexistente / inactivo / guía


@pytest.mark.parametrize("texto", [f"El chofer de la guía {GUIA} es ZACARIAS INEXISTENTE",
                                   f"El chofer de la guía {GUIA} es {_rut(9876543)}",
                                   f"El chofer de la guía {GUIA} es ANA SOTO"])
def test_chofer_inexistente_o_inactivo_no_corrige_nada(con_choferes, texto):
    antes = {p.name: _sha(p) for p in con_choferes["actual"].iterdir() if p.is_file()}
    b1 = OperadorB1(con_choferes["raiz"], usuario="JAVIER")
    r = b1.atender("conv-x", texto)
    assert r["estado"] == "ACLARACION_REQUERIDA", r
    assert b1.atender("conv-x", "sí")["estado"] == "SIN_PREVIEW_PENDIENTE"
    despues = {p.name: _sha(p) for p in con_choferes["actual"].iterdir() if p.is_file() and p.name in antes}
    assert {k: antes[k] for k in despues if k != "b1_operador_conversaciones.json"} == {
        k: v for k, v in despues.items() if k != "b1_operador_conversaciones.json"}


def test_guia_inexistente_se_rechaza(con_choferes):
    r = OperadorB1(con_choferes["raiz"]).atender("conv-x", "El chofer de la guía 699999 es PEDRO MUNOZ")
    assert r["estado"] == "RECHAZADA" and "No encontré la guía 699999" in r["mensaje"]


# ------------------------------------------------------------ hermanas, revalidación, reinicio


def test_guias_hermanas_no_se_modifican_ni_revalidan(con_choferes):
    b1 = OperadorB1(con_choferes["raiz"], usuario="JAVIER")
    b1.atender("conv-chofer", INSTRUCCION)
    r = b1.atender("conv-chofer", "sí")
    assert r["resultado"]["revalidacion"]["guias"] is None
    assert r["resultado"]["revalidacion"]["reporte"]["regenerado"] is True
    filas = _filas(con_choferes)
    assert filas[f"{HERMANA}.jpeg"]["chofer"] == "LUIS REYES"
    assert filas[f"{DISCREPANTE}.jpeg"]["motivos_revision_documento"] == "CHOFER_SIN_CORROBORAR"
    assert choferes_operacionales_por_ledger(con_choferes["actual"] / "decisiones_aplicadas.json").keys() == {
        f"{GUIA}.jpeg"}


def test_relectura_ocr_y_revalidacion_posterior_no_revierten_la_correccion(con_choferes, tmp_path):
    b1 = OperadorB1(con_choferes["raiz"], usuario="JAVIER")
    b1.atender("conv-chofer", INSTRUCCION)
    assert b1.atender("conv-chofer", "sí")["estado"] == "EJECUTADA"
    # Una relectura OCR reescribe la fila con otra lectura y vuelve a marcar el
    # motivo; la tarjeta regenerada reaparece en la bandeja.
    filas = _filas(con_choferes)
    filas[f"{GUIA}.jpeg"].update(chofer="P MUNOZ X", rut_chofer=_rut(22333444),
                                 motivos_revision_documento="CHOFER_SIN_CORROBORAR", indicador_revision="REVISAR",
                                 estado_documental="REQUIERE_REVISION", estado_operacional="REQUIERE_REVISION")
    _escribir(con_choferes, list(filas.values()))
    reaparecida = _tarjeta_chofer(GUIA, "P MUNOZ X", _rut(22333444), tipo="CHOFER_DESCONOCIDO")
    generar_artefacto(ruta_dataset=con_choferes["dataset"], carpeta_catalogos=con_choferes["cat"],
                      decisiones=[*_bandeja(con_choferes), reaparecida])

    revalidar_chofer_sin_corroborar_por_catalogo_sin_ocr(raiz_atlas=con_choferes["raiz"])
    reconciliar_bandeja_decisiones(raiz_atlas=con_choferes["raiz"])

    fila = _filas(con_choferes)[f"{GUIA}.jpeg"]
    assert fila["chofer"] == "P MUNOZ X" and fila["rut_chofer"] == _rut(22333444)  # lectura nueva intacta
    assert "CHOFER_SIN_CORROBORAR" not in fila["motivos_revision_documento"]
    # Ninguna tarjeta de chofer de la guía corregida sobrevive (la de 600003
    # sigue su propia reconciliación global, ajena a esta corrección).
    assert not [d for d in _bandeja(con_choferes)
                if d["documento"]["numero_guia"] == GUIA and d["tipo"].startswith("CHOFER_")]
    viaje = _viaje_reporte(con_choferes["raiz"], tmp_path / "reporte")
    assert "PEDRO MUNOZ" in viaje["choferes"] and CANON_PEDRO in viaje["ruts_chofer"]
    # La guía discrepante nunca recibe la corrección de su hermana.
    assert f"{DISCREPANTE}.jpeg" not in choferes_operacionales_por_ledger(
        con_choferes["actual"] / "decisiones_aplicadas.json")


def test_persistencia_tras_reinicio(con_choferes, tmp_path):
    b1 = OperadorB1(con_choferes["raiz"], usuario="JAVIER")
    b1.atender("conv-chofer", INSTRUCCION)
    assert b1.atender("conv-chofer", "sí")["estado"] == "EJECUTADA"
    # Proceso nuevo: sólo el disco (ledger + dataset) sostiene la corrección.
    salida = tmp_path / "reporte_reinicio"
    codigo = (
        "import csv,json,sys;from pathlib import Path;"
        "from atlas_core.reporte_viajes import generar_reporte_viajes;"
        "r=Path(sys.argv[1]);s=Path(sys.argv[2]);"
        "generar_reporte_viajes(r/'operacion'/'actual'/'analisis_completo_guias.csv',s,carpeta_catalogos=r/'catalogos_privados');"
        "v=[x for x in csv.DictReader((s/'viajes.csv').open(encoding='utf-8-sig'),delimiter=';') if x['numero_transporte']==sys.argv[3]][0];"
        "print(json.dumps({'choferes':v['choferes'],'ruts':v['ruts_chofer']}))"
    )
    salida_proceso = subprocess.run([sys.executable, "-c", codigo, str(con_choferes["raiz"]), str(salida), TRANSPORTE],
                                    capture_output=True, text=True, check=True, cwd=Path(__file__).resolve().parents[1])
    viaje = json.loads(salida_proceso.stdout.strip().splitlines()[-1])
    assert "PEDRO MUNOZ" in viaje["choferes"] and CANON_PEDRO in viaje["ruts"]
    # Un operador nuevo ve la corrección vigente: repetirla no tiene nada que confirmar.
    otra = OperadorB1(con_choferes["raiz"], usuario="JAVIER").atender("conv-nueva", INSTRUCCION)
    assert otra["estado"] == "SIN_CAMBIOS", otra
    # Cambiar a otro chofer muestra como actual el operacional vigente.
    cambio = OperadorB1(con_choferes["raiz"]).atender("conv-nueva", f"El chofer de la guía {GUIA} es CARLOS DIAZ")
    assert cambio["preview"]["valor_actual"]["chofer"] == "PEDRO MUNOZ"
    assert cambio["preview"]["valor_actual"]["fuente"] == "CORRECCION_OPERACIONAL"


# ------------------------------------------------------------ tarjeta de Revisión


@pytest.mark.parametrize("escrito", ["el chofer es PEDRO MUNOZ", "PEDRO MUNOZ", RUT_PEDRO,
                                     "corrige a PEDRO MUNOZ", f"El chofer de la guía {GUIA} es PEDRO MUNOZ"])
def test_tarjeta_de_chofer_corrige_con_b1(con_choferes, escrito):
    b1 = OperadorB1(con_choferes["raiz"], usuario="JAVIER")
    r = b1.atender("revision-x", f"@revision:{con_choferes['tarjeta']} {escrito}")
    assert r["estado"] == "PREVIEW_PENDIENTE", r
    assert r["preview"]["entidad"]["numero_guia"] == GUIA
    assert r["preview"]["parametros"]["archivo"] == f"{GUIA}.jpeg"
    hecho = b1.atender("revision-x", "sí")
    assert hecho["estado"] == "EJECUTADA", hecho
    assert con_choferes["tarjeta"] not in {d["decision_id"] for d in _bandeja(con_choferes)}


def test_tarjeta_rechaza_orden_de_otra_guia(con_choferes):
    r = OperadorB1(con_choferes["raiz"]).atender(
        "revision-x", f"@revision:{con_choferes['tarjeta']} El chofer de la guía {HERMANA} es PEDRO MUNOZ")
    assert r["estado"] == "ACLARACION_REQUERIDA" and f"guía {GUIA}" in r["mensaje"]


# ------------------------------------------------------------ robustez del índice


def test_ledger_corrupto_o_ausente_no_inventa_correcciones(tmp_path):
    assert choferes_operacionales_por_ledger(tmp_path / "no_existe.json") == {}
    corrupto = tmp_path / "ledger.json"
    corrupto.write_text("{no es json", encoding="utf-8")
    assert choferes_operacionales_por_ledger(corrupto) == {}
    decisiones = [{"tipo": "CHOFER_CANDIDATO", "documento": {"archivo": "a.jpeg"}}]
    assert retirar_decisiones_chofer_operacional(decisiones, ruta_ledger=corrupto) == decisiones
