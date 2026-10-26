"""B1 en las tarjetas de Revisión de Atlas: lo escrito en una tarjeta llega
como "@revision:<decision_id> <instrucción>" y se resuelve contra la tarjeta
vigente con las MISMAS acciones de B1 (preview, confirmación, auditoría).
Sólo fixtures sintéticas: nunca G: ni datos productivos."""
from __future__ import annotations

import csv
import hashlib
import json

import pytest

from atlas_core.b1_operador import Intencion, OperadorB1, ajustar_a_revision, instruccion_en_revision
from atlas_core.decisiones_pendientes import crear_decision, generar_artefacto
from atlas_core.procesamiento_masivo import COLUMNAS
from tests.test_acciones_operacionales import _fila, entorno  # noqa: F401 -- fixture compartida

GUIA = "482816"
ARCHIVO = "mobile/8323e2e1/original.jpg"


def _filas(entorno):
    with entorno["dataset"].open(encoding="utf-8-sig", newline="") as archivo:
        return list(csv.DictReader(archivo, delimiter=";"))


def _escribir(entorno, filas):
    with entorno["dataset"].open("w", encoding="utf-8-sig", newline="") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader()
        escritor.writerows(filas)


def _sha(ruta):
    return hashlib.sha256(ruta.read_bytes()).hexdigest()


def _bandeja(entorno):
    return {d["decision_id"] for d in json.loads(
        (entorno["actual"] / "decisiones_pendientes.json").read_text(encoding="utf-8"))["decisiones"]}


def _decision(tipo, campo, valor, acciones, entidad, archivo=ARCHIVO):
    return crear_decision(
        tipo=tipo, entidad=entidad, archivo=archivo, numero_guia=GUIA, numero_transporte="0000365506",
        campo=campo, valor_documental=valor, valor_normalizado=valor, identidad_resuelta=None, candidatos=(),
        motivos=("PRUEBA",), evidencias=(), acciones_permitidas=acciones)


@pytest.fixture
def tarjetas(entorno):
    """482816 con tres tarjetas a la vez (peso, rampla, chofer) más la tarjeta
    de obra de otra guía que trae el fixture compartido."""
    filas = _filas(entorno)
    filas.append(_fila(GUIA, archivo=ARCHIVO, numero_transporte="0000365506", peso_kg="1245",
                       patente_rampla="JC4173", descripcion_material="ROLLO HORMIGON 10MM",
                       chofer="LUIS VARAS", rut_chofer=""))
    _escribir(entorno, filas)
    peso = _decision("PESO_VIAJE_IMPLAUSIBLE", "peso_kg", "1245", ("CONFIRMAR", "CORREGIR_PESO", "POSPONER"), "PESO")
    rampla = _decision("VEHICULO_DESCONOCIDO", "patente_rampla", "JC4173", ("REGISTRAR", "NO_REGISTRAR", "POSPONER"),
                       "VEHICULO")
    chofer = _decision("CHOFER_CANDIDATO", "chofer", "LUIS VARAS", ("CONFIRMAR", "NO_CONFIRMAR", "POSPONER"), "CHOFER")
    generar_artefacto(ruta_dataset=entorno["dataset"], carpeta_catalogos=entorno["cat"],
                      decisiones=[entorno["decision"], peso, rampla, chofer])
    entorno.update(peso=peso["decision_id"], rampla=rampla["decision_id"], chofer=chofer["decision_id"],
                   obra=entorno["decision"]["decision_id"])
    assert {entorno["peso"], entorno["rampla"], entorno["chofer"], entorno["obra"]} <= _bandeja(entorno)
    return entorno


def _en(decision_id, texto):
    return f"@revision:{decision_id} {texto}"


# ------------------------------------------------------------ reescritura contextual

PESO = {"decision_id": "p", "tipo": "PESO_VIAJE_IMPLAUSIBLE", "campo": "peso_kg",
        "documento": {"numero_guia": GUIA, "archivo": ARCHIVO}}


@pytest.mark.parametrize("texto", ["el peso correcto es 12.450 kg", "12.450 kg", "es 12450", "Peso: 12.450 kg",
                                   "corrígelo a 12.450 kg", "cambia el peso por 12.450 kilos", "debe ser 12.450 kg"])
def test_frases_de_tarjeta_se_reescriben_a_la_frase_canonica(texto):
    canonica = instruccion_en_revision(PESO, texto)
    assert canonica is not None and canonica.startswith(f"En la guía {GUIA} el peso correcto es ")


@pytest.mark.parametrize("texto", ["el cliente es OTRO SA", "hola", "no sé", "la rampla es JC4173", "revisar después"])
def test_otro_dato_o_texto_libre_no_se_toma_como_correccion(texto):
    assert instruccion_en_revision(PESO, texto) is None


def test_destino_usa_la_revision_exacta_de_la_tarjeta():
    tarjeta = {"decision_id": "d2", "tipo": "DESTINO_NO_RESUELTO", "campo": "despachar_a_crudo",
               "acciones_permitidas": ["REGISTRAR_DIRECCION", "NO_PUEDO_DETERMINAR", "POSPONER"],
               "documento": {"numero_guia": GUIA, "archivo": ARCHIVO}}
    from atlas_core.b1_operador import interpretar_determinista
    canonica = instruccion_en_revision(tarjeta, "el destino es AV EJEMPLO 123, COMUNA DE MAIPU")
    intencion = interpretar_determinista(canonica)
    assert intencion.accion == "DECISION_APLICAR"
    assert ajustar_a_revision(intencion, tarjeta, "x") == ""
    # Aunque la guía tenga otra revisión de destino, se usa la de ESTA tarjeta.
    assert intencion.parametros["decision_id"] == "d2" and "guia_destino" not in intencion.menciones


def test_accion_ajena_a_la_tarjeta_se_rechaza():
    mensaje = ajustar_a_revision(Intencion("CHOFER_CAMBIAR_ESTADO", {"activo": False}, {"chofer": "X"}), PESO, "x")
    assert "no corrige" in mensaje or "No entendí" in mensaje


# ------------------------------------------------------------ flujo completo


def test_correccion_desde_tarjeta_cierra_solo_su_decision(tarjetas):
    b1 = OperadorB1(tarjetas["raiz"], usuario="JAVIER_DESKTOP")
    conv = f"revision-{tarjetas['peso']}"
    preview = b1.atender(conv, _en(tarjetas["peso"], "el peso correcto es 12.450 kg"))
    assert preview["estado"] == "PREVIEW_PENDIENTE", preview
    assert "peso actual 1.245 kg, peso propuesto 12.450 kg" in preview["mensaje"]
    assert preview["preview"]["entidad"]["id"] == ARCHIVO  # fotografía original de esta guía
    assert "@revision" not in json.dumps(preview, ensure_ascii=False)
    assert tarjetas["peso"] not in preview["mensaje"]

    resultado = b1.atender(conv, _en(tarjetas["peso"], "sí"))
    assert resultado["estado"] == "EJECUTADA", resultado
    fila = next(f for f in _filas(tarjetas) if f["numero_guia"] == GUIA)
    assert (fila["peso_kg"], fila["patente_rampla"], fila["chofer"]) == ("12450", "JC4173", "LUIS VARAS")
    vigentes = _bandeja(tarjetas)
    assert tarjetas["peso"] not in vigentes
    assert {tarjetas["rampla"], tarjetas["chofer"], tarjetas["obra"]} <= vigentes
    ledger = json.loads((tarjetas["actual"] / "decisiones_aplicadas.json").read_text(encoding="utf-8"))["aplicaciones"]
    correccion = [a for a in ledger if a.get("campo") == "peso_kg"]
    assert len(correccion) == 1 and correccion[0]["confirmado_por"] == "JAVIER_DESKTOP"
    assert correccion[0]["referencia"] == f"Revisión de Atlas, guía {GUIA}: el peso correcto es 12.450 kg"
    assert correccion[0]["documento"]["archivo"] == ARCHIVO


def test_cancelar_desde_la_tarjeta_no_escribe(tarjetas):
    sha = _sha(tarjetas["dataset"]), _sha(tarjetas["actual"] / "decisiones_pendientes.json")
    b1 = OperadorB1(tarjetas["raiz"])
    conv = f"revision-{tarjetas['peso']}"
    assert b1.atender(conv, _en(tarjetas["peso"], "12.450 kg"))["estado"] == "PREVIEW_PENDIENTE"
    assert b1.atender(conv, _en(tarjetas["peso"], "no"))["estado"] == "CANCELADA"
    assert b1.atender(conv, _en(tarjetas["peso"], "sí"))["estado"] == "SIN_PREVIEW_PENDIENTE"
    assert (_sha(tarjetas["dataset"]), _sha(tarjetas["actual"] / "decisiones_pendientes.json")) == sha


@pytest.mark.parametrize(("texto", "esperado"), [
    ("el cliente es OTRO SA", "No entendí la corrección de el peso"),
    ("En la guía 500001 el peso correcto es 12.450 kg", "la instrucción menciona la guía 500001"),
    ("corrige la rampla de la guía 482816 a JC4178", "No entendí la corrección de el peso"),
    ("hola", "por ejemplo: «el peso correcto es 12.450 kg»"),
])
def test_instrucciones_ambiguas_o_ajenas_piden_aclaracion_sin_escribir(tarjetas, texto, esperado):
    sha = _sha(tarjetas["dataset"])
    b1 = OperadorB1(tarjetas["raiz"])
    r = b1.atender(f"revision-{tarjetas['peso']}", _en(tarjetas["peso"], texto))
    assert r["estado"] == "ACLARACION_REQUERIDA", r
    assert esperado in r["mensaje"] and "No se corrigió nada" in r["mensaje"]
    assert b1.atender(f"revision-{tarjetas['peso']}", _en(tarjetas["peso"], "sí"))["estado"] == "SIN_PREVIEW_PENDIENTE"
    assert _sha(tarjetas["dataset"]) == sha


def test_peso_invalido_desde_la_tarjeta_se_rechaza(tarjetas):
    r = OperadorB1(tarjetas["raiz"]).atender("revision-x", _en(tarjetas["peso"], "12,45"))
    assert r["estado"] == "RECHAZADA" and "kilos enteros" in r["mensaje"]


def test_tarjeta_sin_correccion_soportada_lo_explica(tarjetas):
    r = OperadorB1(tarjetas["raiz"]).atender("revision-c", _en(tarjetas["chofer"], "el chofer es JUAN PEREZ"))
    assert r["estado"] == "ACLARACION_REQUERIDA"
    assert r["mensaje"].startswith(f"Desde esta tarjeta B1 todavía no corrige el chofer de la guía {GUIA}")


def test_rampla_desde_su_tarjeta_cambia_solo_la_rampla(tarjetas):
    b1 = OperadorB1(tarjetas["raiz"])
    conv = f"revision-{tarjetas['rampla']}"
    preview = b1.atender(conv, _en(tarjetas["rampla"], "la patente correcta es JC4178"))
    assert preview["estado"] == "PREVIEW_PENDIENTE", preview
    assert b1.atender(conv, _en(tarjetas["rampla"], "sí"))["estado"] == "EJECUTADA"
    fila = next(f for f in _filas(tarjetas) if f["numero_guia"] == GUIA)
    assert (fila["patente_rampla"], fila["peso_kg"]) == ("JC4178", "1245")
    vigentes = _bandeja(tarjetas)
    assert tarjetas["rampla"] not in vigentes
    assert {tarjetas["peso"], tarjetas["chofer"], tarjetas["obra"]} <= vigentes


def test_guia_con_dos_documentos_usa_el_documento_de_la_tarjeta(tarjetas):
    filas = _filas(tarjetas)
    filas.append(_fila(GUIA, archivo="mobile/otro/original.jpg", numero_transporte="0000365506", peso_kg="9000"))
    _escribir(tarjetas, filas)
    b1 = OperadorB1(tarjetas["raiz"])
    # Sin tarjeta, la guía es ambigua...
    assert b1.atender("libre", "En la guía 482816 el peso correcto es 12.450 kg")["codigo"] == "ENTIDAD_AMBIGUA"
    # ...desde la tarjeta, el documento es el de la tarjeta.
    conv = f"revision-{tarjetas['peso']}"
    assert b1.atender(conv, _en(tarjetas["peso"], "12.450 kg"))["estado"] == "PREVIEW_PENDIENTE"
    assert b1.atender(conv, _en(tarjetas["peso"], "sí"))["estado"] == "EJECUTADA"
    pesos = {f["archivo"]: f["peso_kg"] for f in _filas(tarjetas) if f["numero_guia"] == GUIA}
    assert pesos == {ARCHIVO: "12450", "mobile/otro/original.jpg": "9000"}


def test_tarjeta_ya_resuelta_no_admite_correcciones(tarjetas):
    r = OperadorB1(tarjetas["raiz"]).atender("revision-z", _en("f" * 64, "12.450 kg"))
    assert r["estado"] == "RECHAZADA" and r["codigo"] == "REVISION_NO_PENDIENTE"


def test_permisos_solo_consulta_y_derivacion(tarjetas):
    b1 = OperadorB1(tarjetas["raiz"])
    texto = _en(tarjetas["peso"], "12.450 kg")
    assert b1.consultar(texto)["estado"] == "RECHAZADA"
    assert b1.consultar(texto, derivar_operacionales=True)["estado"] == "REQUIERE_OPERADOR"
    assert b1.consultar(_en(tarjetas["peso"], "sí"), derivar_operacionales=True)["estado"] == "REQUIERE_OPERADOR"


def test_correccion_desde_tarjeta_persiste_frente_a_ocr(tarjetas):
    b1 = OperadorB1(tarjetas["raiz"])
    conv = f"revision-{tarjetas['peso']}"
    b1.atender(conv, _en(tarjetas["peso"], "12.450 kg"))
    assert b1.atender(conv, _en(tarjetas["peso"], "sí"))["estado"] == "EJECUTADA"
    from atlas_core.reprocesamiento_reparador import (
        CAMPOS_DOCUMENTALES_CONTROLADOS, reparar_documento_focal_con_valores_conocidos,
    )
    intento = reparar_documento_focal_con_valores_conocidos(
        raiz_atlas=tarjetas["raiz"], archivo=ARCHIVO, valores={"peso_kg": "1245"}, dry_run=False,
        numero_guia=GUIA, campos_adicionales_permitidos=frozenset(CAMPOS_DOCUMENTALES_CONTROLADOS))
    assert intento["campos_bloqueados_por_ledger"] == ["peso_kg"]
    assert next(f for f in _filas(tarjetas) if f["numero_guia"] == GUIA)["peso_kg"] == "12450"


def test_tarjeta_antigua_original_jpg_se_publica_con_su_documento_y_b1_la_usa(tarjetas):
    vieja = _decision("PESO_VIAJE_IMPLAUSIBLE", "peso_kg", "1245", ("CONFIRMAR", "CORREGIR_PESO", "POSPONER"), "PESO",
                      archivo="original.jpg")
    generar_artefacto(ruta_dataset=tarjetas["dataset"], carpeta_catalogos=tarjetas["cat"], decisiones=[vieja])
    bandeja = json.loads((tarjetas["actual"] / "decisiones_pendientes.json").read_text(encoding="utf-8"))["decisiones"]
    publicada = next(d for d in bandeja if d["tipo"] == "PESO_VIAJE_IMPLAUSIBLE")
    assert publicada["documento"]["archivo"] == ARCHIVO and publicada["decision_id"] != vieja["decision_id"]
    b1 = OperadorB1(tarjetas["raiz"])
    assert b1.atender("revision-vieja", _en(vieja["decision_id"], "12.450 kg"))["codigo"] == "REVISION_NO_PENDIENTE"
    preview = b1.atender("revision-nueva", _en(publicada["decision_id"], "12.450 kg"))
    assert preview["estado"] == "PREVIEW_PENDIENTE", preview
    assert preview["preview"]["entidad"]["id"] == ARCHIVO


def test_tarjeta_de_documento_sin_numero_de_guia_lo_explica():
    tarjeta = {**PESO, "documento": {"numero_guia": "No encontrado", "archivo": "473316.jpeg"}}
    from atlas_core.b1_operador import aclaracion_revision
    assert instruccion_en_revision(tarjeta, "12.450 kg") is None
    assert aclaracion_revision(tarjeta).startswith("Esta tarjeta es de un documento sin número de guía")


@pytest.mark.parametrize("texto", ["En la guía 482816 el peso es 12.450 kg", "en la guia 482816, 12.450 kg",
                                   "El peso de la guía 482816 es 12.450 kg"])
def test_nombrar_la_guia_de_la_tarjeta_tambien_funciona(texto):
    canonica = instruccion_en_revision(PESO, texto)
    assert canonica is not None
    from atlas_core.b1_operador import interpretar_determinista
    assert interpretar_determinista(canonica).parametros["valor"] == "12450"


def test_otra_guia_se_nombra_explicitamente(tarjetas):
    r = OperadorB1(tarjetas["raiz"]).atender("revision-o", _en(tarjetas["rampla"], "En la guía 482740 la patente es AB1234"))
    assert r["estado"] == "ACLARACION_REQUERIDA" and "la instrucción menciona la guía 482740" in r["mensaje"]


def test_guia_propia_con_frase_que_b1_lee_como_otra_orden_se_reinterpreta():
    tracto = {"decision_id": "t", "tipo": "VEHICULO_DESCONOCIDO", "campo": "patente_tracto",
              "documento": {"numero_guia": "482740", "archivo": "482740.jpeg"}}
    assert instruccion_en_revision(tracto, "En la guía 482740 la patente correcta es JC4173") == \
        "Corrige el tracto de la guía 482740 a JC4173"


@pytest.mark.parametrize(("campo", "tipo", "texto", "accion"), [
    ("obra_destino", "OBRA_DESCONOCIDA", "la obra es EDIFICIO CENTRAL", "DOCUMENTO_ASIGNAR_OBRA"),
    ("cliente", "CLIENTE_DESCONOCIDO", "el cliente es CONSTRUCTORA EJEMPLO SPA", "DOCUMENTO_CORREGIR_CAMPO"),
    ("patente_tracto", "VEHICULO_DESCONOCIDO", "corrígela a AB1234", "DOCUMENTO_CORREGIR_CAMPO"),
])
def test_cada_campo_soportado_llega_a_su_accion_existente(campo, tipo, texto, accion):
    from atlas_core.b1_operador import interpretar_determinista
    tarjeta = {"decision_id": "x", "tipo": tipo, "campo": campo, "documento": {"numero_guia": GUIA, "archivo": ARCHIVO}}
    intencion = interpretar_determinista(instruccion_en_revision(tarjeta, texto))
    assert intencion.accion == accion
    assert ajustar_a_revision(intencion, tarjeta, texto, {ARCHIVO}) == ""
    assert intencion.parametros["archivo"] == ARCHIVO and intencion.parametros["referencia"].startswith("Revisión de Atlas")
