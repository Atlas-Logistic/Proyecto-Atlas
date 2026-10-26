"""B1 -- corrección de PESO de una guía en lenguaje natural ("En la guía
482816 el peso correcto es 12.450 kg"). Sólo fixtures sintéticas: nunca G:
ni datos productivos. Cubre interpretación, preview, confirmación explícita,
escritura acotada a peso + motivos de peso, ledger humano, auditoría,
tarjetas y persistencia frente a OCR/relectura."""
from __future__ import annotations

import csv
import hashlib
import json

import pytest

from atlas_core.b1_operador import ErrorContratoInterpretacion, OperadorB1, interpretar_determinista
from atlas_core.decisiones_pendientes import crear_decision, generar_artefacto
from atlas_core.procesamiento_masivo import COLUMNAS, _promover_relectura
from tests.test_acciones_operacionales import _fila, entorno  # noqa: F401 -- fixture compartida

GUIA = "482816"
ARCHIVO = f"{GUIA}.jpeg"
INSTRUCCION = "En la guía 482816 el peso correcto es 12.450 kg"
# Campos que una corrección de peso nunca puede tocar.
INTOCABLES = ("descripcion_material", "chofer", "rut_chofer", "patente_tracto", "patente_rampla", "cliente",
              "rut_cliente", "obra_destino", "despachar_a_crudo", "direccion_entrega", "distancia_km",
              "duracion_min", "estado_ruta", "proveedor_ruta", "numero_transporte", "numero_guia", "fecha")


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
    return json.loads((entorno["actual"] / "decisiones_pendientes.json").read_text(encoding="utf-8"))["decisiones"]


def _ledger(entorno):
    return json.loads((entorno["actual"] / "decisiones_aplicadas.json").read_text(encoding="utf-8"))["aplicaciones"]


def _decision(tipo, campo, valor, motivos, acciones, entidad="PESO"):
    return crear_decision(
        tipo=tipo, entidad=entidad, archivo=ARCHIVO, numero_guia=GUIA, numero_transporte="0000900001",
        campo=campo, valor_documental=valor, valor_normalizado=valor, identidad_resuelta=None, candidatos=(),
        motivos=motivos, evidencias=(), acciones_permitidas=acciones)


@pytest.fixture
def con_guia(entorno):
    """482816 con peso atípico y una revisión crítica ajena al peso; en la
    bandeja: una tarjeta de peso y otra de obra de la MISMA guía."""
    filas = _filas(entorno)
    filas.append(_fila(
        GUIA, peso_kg="1245", descripcion_material="ROLLO HORMIGON 10MM", patente_rampla="JB6878",
        rut_cliente="76.111.111-6", fecha="20-10-2026", distancia_km="31.2", duracion_min="44",
        motivos_revision_documento="CLIENTE_AUSENTE | PESO_CORREGIDO_POR_BAJA_CONFIANZA_OCR | PESO_OPERACIONALMENTE_ATIPICO",
        indicador_revision="REVISAR", estado_documental="REQUIERE_REVISION", estado_operacional="REQUIERE_REVISION"))
    _escribir(entorno, filas)
    peso = _decision("PESO_VIAJE_IMPLAUSIBLE", "peso_kg", "1245", ("PESO_TOTAL_VIAJE_IMPLAUSIBLE",),
                     ("CONFIRMAR", "CORREGIR_PESO", "POSPONER"))
    obra = _decision("OBRA_DESCONOCIDA", "obra_destino", "OBRA VIEJA", ("OBRA_NO_EXISTE_PARA_CLIENTE",),
                     ("REGISTRAR", "NO_REGISTRAR", "POSPONER"), entidad="OBRA")
    generar_artefacto(ruta_dataset=entorno["dataset"], carpeta_catalogos=entorno["cat"],
                      decisiones=[entorno["decision"], peso, obra])
    entorno.update(peso=peso["decision_id"], obra=obra["decision_id"])
    return entorno


# ------------------------------------------------------------ interpretación


@pytest.mark.parametrize("texto", [
    INSTRUCCION,
    "en la guia 482816, el peso es 12450",
    "El peso de la guía 482816 es 12.450 kilos",
    "El peso correcto de la guía N° 482816 es de 12.450 kg.",
    "Peso de la guía 482816: 12450 kg",
    "Corrige el peso de la guía 482816 a 12.450 kg",
    "cambia el peso de la guia 482816 por 12450 kilogramos",
    "La guía 482816 pesa 12.450 kg",
    "La guía 482816 tiene un peso de 12.450 kg",
])
def test_frases_de_peso_se_interpretan_en_kilos_enteros(texto):
    intencion = interpretar_determinista(texto)
    assert intencion.accion == "DOCUMENTO_CORREGIR_CAMPO"
    assert intencion.parametros == {"numero_guia": GUIA, "campo": "peso_kg", "valor": "12450", "referencia": texto}


@pytest.mark.parametrize("valor", ["12,450", "12.45", "12,5 toneladas", "12.450,5 kg", "12 450", "0", "0 kg",
                                   "150.000 kg", "doce mil", "-12450", "12.450 t", "012450"])
def test_peso_ambiguo_o_invalido_se_rechaza_sin_inventar(valor):
    with pytest.raises(ErrorContratoInterpretacion, match="kilos enteros"):
        interpretar_determinista(f"En la guía 482816 el peso correcto es {valor}")


@pytest.mark.parametrize("texto", ["¿Cuál es el peso de la guía 482816?", "¿El peso de la guía 482816 es 12.450?",
                                   "peso de la guía 482816"])
def test_preguntas_sobre_el_peso_nunca_son_correcciones(texto):
    intencion = interpretar_determinista(texto)
    assert intencion is None or intencion.accion != "DOCUMENTO_CORREGIR_CAMPO"


# ------------------------------------------------------------ flujo completo


def test_preview_muestra_guia_pesos_y_documento_sin_escribir(con_guia):
    antes = {p: _sha(p) for p in con_guia["actual"].iterdir() if p.is_file()}
    r = OperadorB1(con_guia["raiz"]).atender("conv-peso", INSTRUCCION)
    assert r["estado"] == "PREVIEW_PENDIENTE", r
    assert "guía 482816" in r["mensaje"] and "transporte 0000900001" in r["mensaje"]
    assert "peso actual 1.245 kg" in r["mensaje"] and "peso propuesto 12.450 kg" in r["mensaje"]
    assert r["mensaje"].endswith("¿Confirmas? (sí / no)")
    preview = r["preview"]
    # Identifica el documento exacto: Desktop abre su fotografía original con él.
    assert preview["entidad"]["tipo"] == "DOCUMENTO" and preview["entidad"]["id"] == ARCHIVO
    assert preview["valor_actual"] == {"peso_kg": "1245"} and preview["valor_propuesto"] == {"peso_kg": "12450"}
    assert "token" not in preview
    despues = {p: _sha(p) for p in con_guia["actual"].iterdir() if p.is_file() and p.name in {q.name for q in antes}}
    datos = {p for p in antes if p.name != "b1_operador_conversaciones.json"}
    assert {p: antes[p] for p in datos} == {p: despues[p] for p in datos}


def test_confirmacion_escribe_solo_peso_y_motivos_de_peso_con_ledger_y_auditoria(con_guia):
    original = next(f for f in _filas(con_guia) if f["numero_guia"] == GUIA)
    otras = [f for f in _filas(con_guia) if f["numero_guia"] != GUIA]
    b1 = OperadorB1(con_guia["raiz"], usuario="JAVIER")
    assert b1.atender("conv-peso", INSTRUCCION)["estado"] == "PREVIEW_PENDIENTE"
    r = b1.atender("conv-peso", "sí")
    assert r["estado"] == "EJECUTADA", r
    assert r["mensaje"].startswith("Listo: la guía 482816 quedó con peso 12.450 kg (antes 1.245 kg).")

    fila = next(f for f in _filas(con_guia) if f["numero_guia"] == GUIA)
    assert fila["peso_kg"] == "12450"
    for campo in INTOCABLES:
        assert fila[campo] == original[campo], campo
    # Sólo se retiran los motivos del peso anterior; la revisión crítica ajena sigue.
    assert fila["motivos_revision_documento"] == "CLIENTE_AUSENTE"
    assert fila["indicador_revision"] == "REVISAR" and fila["estado_documental"] == "REQUIERE_REVISION"
    assert [f for f in _filas(con_guia) if f["numero_guia"] != GUIA] == otras

    ledger = [a for a in _ledger(con_guia) if a.get("campo") == "peso_kg"]
    assert len(ledger) == 1
    assert ledger[0]["tipo"] == "CORRECCION_DOCUMENTAL_OPERADOR" and ledger[0]["confirmado_por"] == "JAVIER"
    assert ledger[0]["documento"]["archivo"] == ARCHIVO
    assert (ledger[0]["valor_documental"], ledger[0]["valor_corregido"]) == ("1245", "12450")
    assert ledger[0]["referencia"] == INSTRUCCION

    auditoria = json.loads((con_guia["actual"] / "acciones_operacionales.json").read_text(encoding="utf-8"))
    aplicada = [a for a in json.dumps(auditoria, ensure_ascii=False).split("DOCUMENTO_CORREGIR_CAMPO")]
    assert len(aplicada) > 1 and '"confirmado_por": "JAVIER"' in json.dumps(auditoria, ensure_ascii=False)


def test_tarjeta_de_peso_se_retira_y_las_demas_decisiones_siguen(con_guia):
    b1 = OperadorB1(con_guia["raiz"])
    b1.atender("conv-peso", INSTRUCCION)
    r = b1.atender("conv-peso", "sí")
    assert r["estado"] == "EJECUTADA", r
    vigentes = {d["decision_id"] for d in _bandeja(con_guia)}
    assert con_guia["peso"] not in vigentes
    assert con_guia["peso"] in r["resultado"]["decisiones_retiradas"]
    assert {con_guia["obra"], con_guia["decision"]["decision_id"]} <= vigentes


def test_sin_confirmacion_no_se_escribe_nada(con_guia):
    sha = _sha(con_guia["dataset"]), _sha(con_guia["actual"] / "decisiones_aplicadas.json")
    b1 = OperadorB1(con_guia["raiz"])
    b1.atender("conv-peso", INSTRUCCION)
    assert b1.atender("conv-peso", "no")["estado"] == "CANCELADA"
    assert b1.atender("conv-peso", "sí")["estado"] == "SIN_PREVIEW_PENDIENTE"
    assert (_sha(con_guia["dataset"]), _sha(con_guia["actual"] / "decisiones_aplicadas.json")) == sha


def test_peso_nuevo_atipico_conserva_su_advertencia(con_guia):
    b1 = OperadorB1(con_guia["raiz"])
    b1.atender("conv-peso", "En la guía 482816 el peso correcto es 120 kg")
    assert b1.atender("conv-peso", "sí")["estado"] == "EJECUTADA"
    fila = next(f for f in _filas(con_guia) if f["numero_guia"] == GUIA)
    assert fila["peso_kg"] == "120"
    assert fila["motivos_revision_documento"] == "CLIENTE_AUSENTE | PESO_OPERACIONALMENTE_ATIPICO"


def test_guia_ambigua_o_inexistente_se_rechaza(con_guia):
    filas = _filas(con_guia)
    filas.append(_fila(GUIA, archivo="mobile/otro/original.jpg", peso_kg="9000"))
    _escribir(con_guia, filas)
    sha = _sha(con_guia["dataset"])
    b1 = OperadorB1(con_guia["raiz"])
    ambigua = b1.atender("conv-peso", INSTRUCCION)
    assert ambigua["estado"] == "RECHAZADA" and ambigua["codigo"] == "ENTIDAD_AMBIGUA"
    assert "más de un documento" in ambigua["mensaje"] and "archivo" not in ambigua["mensaje"]
    inexistente = b1.atender("conv-peso", "En la guía 999999 el peso correcto es 12.450 kg")
    assert inexistente["estado"] == "RECHAZADA" and "No encontré la guía 999999" in inexistente["mensaje"]
    assert b1.atender("conv-peso", "sí")["estado"] == "SIN_PREVIEW_PENDIENTE"
    assert _sha(con_guia["dataset"]) == sha


def test_peso_invalido_responde_sin_preview(con_guia):
    r = OperadorB1(con_guia["raiz"]).atender("conv-peso", "En la guía 482816 el peso correcto es 12,45")
    assert r["estado"] == "RECHAZADA" and "kilos enteros" in r["mensaje"]


# ------------------------------------------------------------ persistencia


def test_correccion_persiste_frente_a_ocr_relectura_y_nueva_correccion(con_guia):
    b1 = OperadorB1(con_guia["raiz"])
    b1.atender("conv-peso", INSTRUCCION)
    assert b1.atender("conv-peso", "sí")["estado"] == "EJECUTADA"

    # Reparador/OCR (mismo guardián que reprocesos y revalidaciones).
    from atlas_core.reprocesamiento_reparador import (
        CAMPOS_DOCUMENTALES_CONTROLADOS, reparar_documento_focal_con_valores_conocidos,
    )
    intento = reparar_documento_focal_con_valores_conocidos(
        raiz_atlas=con_guia["raiz"], archivo=ARCHIVO, valores={"peso_kg": "1245"}, dry_run=False,
        numero_guia=GUIA, campos_adicionales_permitidos=frozenset(CAMPOS_DOCUMENTALES_CONTROLADOS))
    assert intento["campos_bloqueados_por_ledger"] == ["peso_kg"] and not intento["cambios"]

    # Relectura de una foto mejor: reemplaza la fila, pero el peso humano se conserva.
    fila = next(f for f in _filas(con_guia) if f["numero_guia"] == GUIA)
    nueva = {**fila, "peso_kg": "1245", "descripcion_material": "ROLLO HORMIGON 10MM"}
    _promover_relectura(con_guia["dataset"], archivo=ARCHIVO, fila_nueva=nueva)
    assert next(f for f in _filas(con_guia) if f["numero_guia"] == GUIA)["peso_kg"] == "12450"

    # Una segunda corrección humana sí puede reemplazar a la primera (queda auditada).
    b1.atender("conv-peso", "Corrige el peso de la guía 482816 a 12.540 kg")
    assert b1.atender("conv-peso", "sí")["estado"] == "EJECUTADA"
    assert next(f for f in _filas(con_guia) if f["numero_guia"] == GUIA)["peso_kg"] == "12540"
    assert [a["valor_corregido"] for a in _ledger(con_guia) if a.get("campo") == "peso_kg"] == ["12450", "12540"]


def test_reporte_regenerado_muestra_el_peso_corregido(con_guia):
    b1 = OperadorB1(con_guia["raiz"])
    b1.atender("conv-peso", INSTRUCCION)
    r = b1.atender("conv-peso", "sí")
    reporte = (r["resultado"].get("revalidacion") or {}).get("reporte") or {}
    assert reporte.get("regenerado"), reporte
    viajes = list((con_guia["raiz"]).rglob("viajes.csv"))
    assert viajes, "no se generó viajes.csv"
    ultimo = max(viajes, key=lambda p: p.stat().st_mtime)
    contenido = ultimo.read_text(encoding="utf-8-sig")
    assert "12450" in contenido and "1245;" not in contenido
