"""B1 -- corrección de la FECHA DE EMISIÓN de una guía en lenguaje natural
(«La fecha de emisión de la guía 482492 es 19-10-2026»). Sólo fixtures
sintéticas: nunca G: ni datos productivos. Reutiliza DOCUMENTO_CORREGIR_CAMPO
(campo `fecha`): interpretación, normalización DD-MM-AAAA, vista previa sin
escritura, confirmación explícita, ledger humano, auditoría, respaldo,
protección frente a OCR y dependencias de la fecha (viaje, agrupación,
asignación de vehículos, tarjetas y reporte)."""
from __future__ import annotations

import csv
import hashlib
import json
from datetime import date

import pytest

from atlas_core.b1_operador import (
    ErrorContratoInterpretacion, OperadorB1, _fecha_emision_declarada, interpretar_determinista,
)
from atlas_core.decisiones_pendientes import crear_decision, generar_artefacto
from atlas_core.procesamiento_masivo import COLUMNAS, _promover_relectura
from tests.test_acciones_operacionales import RUT_ACTIVO, _fila, _vehiculo, entorno  # noqa: F401 -- fixture compartida

GUIA = "482492"
OTRA = "482493"
ARCHIVO = f"{GUIA}.jpeg"
TRANSPORTE = "0000900001"
FRASES = (
    "La fecha de emisión de la guía 482492 es 19-10-2026",
    "Corrige la fecha de la guía 482492 al 19 de octubre de 2026",
    "La guía 482492 fue emitida el 19/10/2026",
)
INSTRUCCION = FRASES[0]
# Campos que una corrección de fecha nunca puede tocar.
INTOCABLES = ("descripcion_material", "peso_kg", "chofer", "rut_chofer", "patente_tracto", "patente_rampla",
              "cliente", "rut_cliente", "obra_destino", "despachar_a_crudo", "direccion_entrega", "numero_transporte",
              "numero_guia", "archivo", "hora_entrada_aza", "hora_salida_aza", "metricas_procesamiento_json")


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


def _ledger(entorno):
    return json.loads((entorno["actual"] / "decisiones_aplicadas.json").read_text(encoding="utf-8"))["aplicaciones"]


def _bandeja(entorno):
    return json.loads((entorno["actual"] / "decisiones_pendientes.json").read_text(encoding="utf-8"))["decisiones"]


def _fila_guia(entorno, guia=GUIA):
    return next(f for f in _filas(entorno) if f["numero_guia"] == guia)


# Registro del propio canal: guarda la vista previa pendiente (token), nunca datos.
_REGISTROS_DE_SESION = {"b1_operador_conversaciones.json", "acciones_operacionales.json"}


def _huellas(entorno):
    """Todos los datos de la raíz (dataset, bandeja, ledger, catálogos,
    original, reportes) salvo los registros de sesión del canal."""
    return {p: _sha(p) for p in entorno["raiz"].rglob("*")
            if p.is_file() and p.name not in _REGISTROS_DE_SESION and ".lock" not in p.name}


def _sin_aplicaciones(entorno):
    ruta = entorno["actual"] / "acciones_operacionales.json"
    texto = ruta.read_text(encoding="utf-8") if ruta.is_file() else ""
    return "APLICADA" not in texto and not any(a.get("campo") == "fecha" for a in _ledger(entorno))


@pytest.fixture
def con_guia(entorno):
    """482492 con fecha mal leída (18-10-2026), sola en su transporte, con
    un original documental en disco y una tarjeta ajena a la fecha."""
    filas = [f for f in _filas(entorno) if f["numero_guia"] not in {"500001", "500002"}]
    filas.append(_fila(GUIA, fecha="18-10-2026", peso_kg="28000", descripcion_material="ROLLO 10MM",
                       patente_rampla="JB6878", rut_cliente="76.111.111-6", distancia_km="31.2", duracion_min="44",
                       metricas_procesamiento_json='{"ms": 10}'))
    filas.append(_fila("500002", numero_transporte="0000900002", fecha="10-10-2026"))
    _escribir(entorno, filas)
    original = entorno["raiz"] / ARCHIVO
    original.write_bytes(b"\xff\xd8 original sintetico \xff\xd9")
    obra = crear_decision(
        tipo="OBRA_DESCONOCIDA", entidad="OBRA", archivo=ARCHIVO, numero_guia=GUIA, numero_transporte=TRANSPORTE,
        campo="obra_destino", valor_documental="OBRA VIEJA", valor_normalizado="OBRA VIEJA", identidad_resuelta=None,
        candidatos=(), motivos=("OBRA_NO_EXISTE_PARA_CLIENTE",), evidencias=(),
        acciones_permitidas=("REGISTRAR", "NO_REGISTRAR", "POSPONER"))
    generar_artefacto(ruta_dataset=entorno["dataset"], carpeta_catalogos=entorno["cat"], decisiones=[obra])
    entorno.update(obra=obra["decision_id"], original=original)
    return entorno


# ------------------------------------------------------------ interpretación


@pytest.mark.parametrize("texto", FRASES)
def test_tres_frases_se_reconocen_y_normalizan(texto):
    intencion = interpretar_determinista(texto)
    assert intencion.accion == "DOCUMENTO_CORREGIR_CAMPO"
    assert intencion.parametros == {"numero_guia": GUIA, "campo": "fecha", "valor": "19-10-2026", "referencia": texto}


@pytest.mark.parametrize("texto", [
    "la fecha de la guia 482492 es 19.10.2026",
    "En la guía 482492 la fecha correcta es 2026-10-19",
    "Cambia la fecha de emisión de la guía N° 482492 a el 19 de octubre del 2026",
    "La guía 482492 se emitió el domingo 19 de octubre de 2026",
    "Fecha de la guía 482492: 19-10-2026",
    "La fecha de emisión de la guía 482492 es el 19 de Octubre de 2026.",
])
def test_variantes_inequivocas_se_normalizan(texto):
    intencion = interpretar_determinista(texto)
    assert (intencion.accion, intencion.parametros["campo"], intencion.parametros["valor"]) == (
        "DOCUMENTO_CORREGIR_CAMPO", "fecha", "19-10-2026")


@pytest.mark.parametrize("valor", ["31-02-2026", "32-10-2026", "19-13-2026", "00-10-2026", "29-02-2025",
                                   "31 de septiembre de 2026", "19 de octubbre de 2026", "19-10-1999",
                                   "31-12-2099", "mañana", "diecinueve de octubre de 2026"])
def test_fechas_invalidas_se_rechazan(valor):
    with pytest.raises(ErrorContratoInterpretacion, match="No se corrigió nada"):
        interpretar_determinista(f"La fecha de emisión de la guía 482492 es {valor}")


@pytest.mark.parametrize("valor", ["19-10-26", "19/10/26", "19 de octubre", "19-10", "19/10", "octubre de 2026",
                                   "19-10/2026", "ayer", "hoy", "19-10-2026 o 20-10-2026"])
def test_fechas_ambiguas_se_rechazan(valor):
    with pytest.raises(ErrorContratoInterpretacion, match="No se corrigió nada"):
        interpretar_determinista(f"La fecha de emisión de la guía 482492 es {valor}")


def test_falta_de_anio_se_explica_como_ambiguedad():
    with pytest.raises(ErrorContratoInterpretacion, match="ambigua: falta el año"):
        interpretar_determinista("La guía 482492 fue emitida el 19/10")


def test_fecha_futura_se_rechaza_respecto_de_hoy():
    assert _fecha_emision_declarada("19-10-2026", hoy=date(2026, 11, 20)) == "19-10-2026"
    with pytest.raises(ErrorContratoInterpretacion, match="posterior a hoy"):
        _fecha_emision_declarada("21-11-2026", hoy=date(2026, 11, 20))


@pytest.mark.parametrize("texto", [
    "La fecha de las guías 482492 y 482493 es 19-10-2026",
    "La fecha de emisión de la guía 482492 y la guía 482493 es 19-10-2026",
    "La guía 482492 y la 482493 fueron emitidas el 19/10/2026",
    "Corrige la fecha de las guías 482492, 482493 al 19 de octubre de 2026",
    "La fecha de la guía 482492 es 19-10-2026 y la de la guía 482493 es 18-10-2026",
])
def test_frase_con_varias_guias_no_se_reduce_a_una(texto):
    with pytest.raises(ErrorContratoInterpretacion, match="más de una guía"):
        interpretar_determinista(texto)


@pytest.mark.parametrize("texto", ["¿Cuál es la fecha de la guía 482492?",
                                   "¿La fecha de la guía 482492 es 19-10-2026?",
                                   "muestra la fecha de las guías 482492 y 482493"])
def test_preguntas_nunca_son_correcciones(texto):
    intencion = interpretar_determinista(texto)
    assert intencion is None or intencion.accion != "DOCUMENTO_CORREGIR_CAMPO"


def test_otras_frases_documentales_no_cambian():
    peso = interpretar_determinista("En la guía 482816 el peso correcto es 12.450 kg")
    assert peso.parametros["campo"] == "peso_kg"
    material = interpretar_determinista("El material de la guía 482816 es ROLLO 10MM")
    assert material.parametros["campo"] == "descripcion_material"


# ------------------------------------------------------------ vista previa


@pytest.mark.parametrize("texto", FRASES)
def test_vista_previa_muestra_guia_y_fechas_sin_escribir(con_guia, texto):
    antes = _huellas(con_guia)
    r = OperadorB1(con_guia["raiz"]).atender("conv-fecha", texto)
    assert r["estado"] == "PREVIEW_PENDIENTE", r
    assert "guía 482492" in r["mensaje"] and f"transporte {TRANSPORTE}" in r["mensaje"]
    assert "fecha anterior 18-10-2026 (18 de octubre de 2026)" in r["mensaje"]
    assert "fecha propuesta 19-10-2026 (19 de octubre de 2026)" in r["mensaje"]
    assert "documento original y su lectura OCR no se modifican" in r["mensaje"]
    assert r["mensaje"].endswith("¿Confirmas? (sí / no)")
    preview = r["preview"]
    assert preview["entidad"]["tipo"] == "DOCUMENTO" and preview["entidad"]["id"] == ARCHIVO
    assert preview["valor_actual"] == {"fecha": "18-10-2026"} and preview["valor_propuesto"] == {"fecha": "19-10-2026"}
    assert "token" not in preview
    assert _huellas(con_guia) == antes and _sin_aplicaciones(con_guia)


def test_guia_inexistente_se_rechaza(con_guia):
    antes = _huellas(con_guia)
    b1 = OperadorB1(con_guia["raiz"])
    r = b1.atender("conv-fecha", "La fecha de emisión de la guía 999999 es 19-10-2026")
    assert r["estado"] == "RECHAZADA" and r["codigo"] == "ENTIDAD_NO_ENCONTRADA"
    assert "No encontré la guía 999999" in r["mensaje"]
    assert b1.atender("conv-fecha", "sí")["estado"] == "SIN_PREVIEW_PENDIENTE"
    assert _huellas(con_guia) == antes


def test_guia_ambigua_se_rechaza(con_guia):
    filas = _filas(con_guia)
    filas.append(_fila(GUIA, archivo="mobile/otro/original.jpg", fecha="17-10-2026"))
    _escribir(con_guia, filas)
    sha = _sha(con_guia["dataset"])
    r = OperadorB1(con_guia["raiz"]).atender("conv-fecha", INSTRUCCION)
    assert r["estado"] == "RECHAZADA" and r["codigo"] == "ENTIDAD_AMBIGUA" and "más de un documento" in r["mensaje"]
    assert _sha(con_guia["dataset"]) == sha


def test_fecha_invalida_o_ambigua_responde_sin_preview(con_guia):
    sha = _sha(con_guia["dataset"])
    b1 = OperadorB1(con_guia["raiz"])
    for texto in ("La fecha de emisión de la guía 482492 es 31-02-2026",
                  "La fecha de emisión de la guía 482492 es 19/10/26",
                  "La fecha de las guías 482492 y 482493 es 19-10-2026"):
        r = b1.atender("conv-fecha", texto)
        assert r["estado"] == "RECHAZADA" and "No se corrigió nada" in r["mensaje"], r
        assert b1.atender("conv-fecha", "sí")["estado"] == "SIN_PREVIEW_PENDIENTE"
    assert _sha(con_guia["dataset"]) == sha


def test_misma_fecha_no_pide_confirmacion(con_guia):
    sha = _sha(con_guia["dataset"])
    r = OperadorB1(con_guia["raiz"]).atender("conv-fecha", "La fecha de emisión de la guía 482492 es 18-10-2026")
    assert r["estado"] != "PREVIEW_PENDIENTE" and r["estado"] != "EJECUTADA", r
    assert _sha(con_guia["dataset"]) == sha


def test_confirmar_fecha_antigua_registra_confirmacion_y_retira_alerta(con_guia):
    from atlas_core.alertas_fecha import alerta_fecha
    from atlas_core.revalidacion_documental import reconciliar_bandeja_decisiones
    filas = _filas(con_guia)
    for fila in filas:
        if fila['numero_guia'] == GUIA:
            fila['fecha'] = '18-10-2020'
            fila['metricas_procesamiento_json'] = json.dumps({'fecha_recepcion_utc': '2026-10-18T12:00:00Z'})
    _escribir(con_guia, filas)
    fila_antes = _fila_guia(con_guia)
    assert alerta_fecha(fila_antes, _ledger(con_guia))
    reconciliar_bandeja_decisiones(raiz_atlas=con_guia['raiz'], guias_objetivo={GUIA})
    assert sum(d.get('tipo') == 'FECHA_SOSPECHOSA' for d in _bandeja(con_guia)) == 1
    b1 = OperadorB1(con_guia['raiz'], usuario='JAVIER')
    tarjeta = next(d for d in _bandeja(con_guia) if d['tipo'] == 'FECHA_SOSPECHOSA')
    previo = b1.atender('fecha-antigua', f"@revision:{tarjeta['decision_id']} la fecha es 18-10-2020")
    assert previo['estado'] == 'PREVIEW_PENDIENTE', previo
    confirmado = b1.atender('fecha-antigua', 'si')
    assert confirmado['estado'] == 'EJECUTADA', confirmado
    assert _fila_guia(con_guia)['fecha'] == '18-10-2020'
    assert alerta_fecha(_fila_guia(con_guia), _ledger(con_guia)) is None
    assert not any(d.get('tipo') == 'FECHA_SOSPECHOSA' for d in _bandeja(con_guia))


def test_corregir_fecha_alertada_conserva_ocr_y_no_reabre_tarjeta(con_guia):
    from atlas_core.revalidacion_documental import reconciliar_bandeja_decisiones
    filas = _filas(con_guia)
    for fila in filas:
        if fila['numero_guia'] == GUIA:
            fila['fecha'] = '18-10-2020'
            fila['metricas_procesamiento_json'] = json.dumps({'fecha_recepcion_utc': '2026-10-18T12:00:00Z', 'ocr': '18-10-2020'})
    _escribir(con_guia, filas)
    original = _sha(con_guia['original'])
    reconciliar_bandeja_decisiones(raiz_atlas=con_guia['raiz'], guias_objetivo={GUIA})
    assert sum(d.get('tipo') == 'FECHA_SOSPECHOSA' for d in _bandeja(con_guia)) == 1
    b1 = OperadorB1(con_guia['raiz'], usuario='JAVIER')
    tarjeta = next(d for d in _bandeja(con_guia) if d['tipo'] == 'FECHA_SOSPECHOSA')
    assert b1.atender('fecha-alerta', f"@revision:{tarjeta['decision_id']} la fecha es 18-10-2026")['estado'] == 'PREVIEW_PENDIENTE'
    assert b1.atender('fecha-alerta', 'si')['estado'] == 'EJECUTADA'
    assert _fila_guia(con_guia)['fecha'] == '18-10-2026'
    assert json.loads(_fila_guia(con_guia)['metricas_procesamiento_json'])['ocr'] == '18-10-2020'
    assert _sha(con_guia['original']) == original
    reconciliar_bandeja_decisiones(raiz_atlas=con_guia['raiz'], guias_objetivo={GUIA})
    assert not any(d.get('tipo') == 'FECHA_SOSPECHOSA' for d in _bandeja(con_guia))


# ------------------------------------------------------------ confirmación


def test_sin_confirmacion_no_se_escribe_nada(con_guia):
    antes = _huellas(con_guia)
    b1 = OperadorB1(con_guia["raiz"])
    assert b1.atender("conv-fecha", INSTRUCCION)["estado"] == "PREVIEW_PENDIENTE"
    assert b1.atender("conv-fecha", "no")["estado"] == "CANCELADA"
    assert b1.atender("conv-fecha", "sí")["estado"] == "SIN_PREVIEW_PENDIENTE"
    assert _huellas(con_guia) == antes and _sin_aplicaciones(con_guia)


def test_confirmacion_escribe_solo_la_fecha_con_ledger_auditoria_y_respaldo(con_guia):
    original = _fila_guia(con_guia)
    otras = [f for f in _filas(con_guia) if f["numero_guia"] != GUIA]
    sha_original = _sha(con_guia["original"])
    b1 = OperadorB1(con_guia["raiz"], usuario="JAVIER")
    assert b1.atender("conv-fecha", INSTRUCCION)["estado"] == "PREVIEW_PENDIENTE"
    # Antes del «sí» el dataset no cambió.
    assert _fila_guia(con_guia)["fecha"] == "18-10-2026"
    r = b1.atender("conv-fecha", "sí")
    assert r["estado"] == "EJECUTADA", r
    assert r["mensaje"].startswith("Listo: la guía 482492 quedó con fecha de emisión 19-10-2026 "
                                   "(19 de octubre de 2026) (antes 18-10-2026 (18 de octubre de 2026)).")

    fila = _fila_guia(con_guia)
    assert fila["fecha"] == "19-10-2026"
    for campo in INTOCABLES:
        assert fila[campo] == original[campo], campo
    assert [f for f in _filas(con_guia) if f["numero_guia"] != GUIA] == otras
    # Original documental intacto.
    assert _sha(con_guia["original"]) == sha_original

    ledger = [a for a in _ledger(con_guia) if a.get("campo") == "fecha"]
    assert len(ledger) == 1
    assert ledger[0]["tipo"] == "CORRECCION_DOCUMENTAL_OPERADOR" and ledger[0]["confirmado_por"] == "JAVIER"
    assert ledger[0]["documento"]["archivo"] == ARCHIVO
    assert (ledger[0]["valor_documental"], ledger[0]["valor_corregido"]) == ("18-10-2026", "19-10-2026")
    assert ledger[0]["referencia"] == INSTRUCCION

    auditoria = json.dumps(json.loads((con_guia["actual"] / "acciones_operacionales.json").read_text(encoding="utf-8")),
                           ensure_ascii=False)
    assert "DOCUMENTO_CORREGIR_CAMPO" in auditoria and '"confirmado_por": "JAVIER"' in auditoria
    # Respaldo de la operación: la capa guarda la fila previa para recuperar.
    respaldos = [p for p in con_guia["raiz"].rglob("*") if p.is_file() and "respaldo" in str(p).lower()]
    assert respaldos, "la corrección no dejó respaldo"
    assert any(b"18-10-2026" in p.read_bytes() for p in respaldos)


def test_tarjetas_ajenas_a_la_fecha_siguen_y_reporte_se_regenera(con_guia):
    b1 = OperadorB1(con_guia["raiz"])
    b1.atender("conv-fecha", INSTRUCCION)
    r = b1.atender("conv-fecha", "sí")
    assert r["estado"] == "EJECUTADA", r
    assert con_guia["obra"] in {d["decision_id"] for d in _bandeja(con_guia)}
    reporte = (r["resultado"].get("revalidacion") or {}).get("reporte") or {}
    assert reporte.get("regenerado"), reporte
    viajes = max(con_guia["raiz"].rglob("viajes.csv"), key=lambda p: p.stat().st_mtime)
    with viajes.open(encoding="utf-8-sig", newline="") as archivo:
        viaje = next(v for v in csv.DictReader(archivo, delimiter=";") if v["numero_transporte"] == TRANSPORTE)
    assert viaje["fecha"] in {"19-10-2026", "2026-10-19"}, viaje["fecha"]


def test_correccion_persiste_frente_a_ocr_y_relectura(con_guia):
    b1 = OperadorB1(con_guia["raiz"])
    b1.atender("conv-fecha", INSTRUCCION)
    assert b1.atender("conv-fecha", "sí")["estado"] == "EJECUTADA"
    from atlas_core.reprocesamiento_reparador import (
        CAMPOS_DOCUMENTALES_CONTROLADOS, reparar_documento_focal_con_valores_conocidos,
    )
    intento = reparar_documento_focal_con_valores_conocidos(
        raiz_atlas=con_guia["raiz"], archivo=ARCHIVO, valores={"fecha": "18-10-2026"}, dry_run=False,
        numero_guia=GUIA, campos_adicionales_permitidos=frozenset(CAMPOS_DOCUMENTALES_CONTROLADOS))
    assert intento["campos_bloqueados_por_ledger"] == ["fecha"] and not intento["cambios"]
    fila = _fila_guia(con_guia)
    _promover_relectura(con_guia["dataset"], archivo=ARCHIVO, fila_nueva={**fila, "fecha": "18-10-2026"})
    assert _fila_guia(con_guia)["fecha"] == "19-10-2026"


# ------------------------------------------------------------ decisiones humanas


def test_fecha_fijada_por_decision_de_revision_no_se_sobrescribe(con_guia):
    ruta = con_guia["actual"] / "decisiones_aplicadas.json"
    ruta.write_text(json.dumps({"schema_version": 1, "aplicaciones": [{
        "decision_id": "rev-1", "tipo": "FECHA_REVISADA", "accion": "CONFIRMAR", "campo": "fecha",
        "actor": "JAVIER", "confirmado_por": "JAVIER",
        "documento": {"archivo": ARCHIVO, "numero_guia": GUIA}}]}), encoding="utf-8")
    antes = _huellas(con_guia)
    b1 = OperadorB1(con_guia["raiz"])
    r = b1.atender("conv-fecha", INSTRUCCION)
    assert r["estado"] == "RECHAZADA" and r["codigo"] == "CAMPO_FIJADO_POR_DECISION_HUMANA", r
    assert "ya fue fijada por una decisión de Revisión" in r["mensaje"]
    assert b1.atender("conv-fecha", "sí")["estado"] == "SIN_PREVIEW_PENDIENTE"
    assert _huellas(con_guia) == antes


def test_una_correccion_humana_previa_por_b1_si_se_puede_reemplazar(con_guia):
    b1 = OperadorB1(con_guia["raiz"])
    b1.atender("conv-fecha", INSTRUCCION)
    assert b1.atender("conv-fecha", "sí")["estado"] == "EJECUTADA"
    b1.atender("conv-fecha", "Corrige la fecha de la guía 482492 al 17 de octubre de 2026")
    assert b1.atender("conv-fecha", "sí")["estado"] == "EJECUTADA"
    assert _fila_guia(con_guia)["fecha"] == "17-10-2026"
    assert [a["valor_corregido"] for a in _ledger(con_guia) if a.get("campo") == "fecha"] == ["19-10-2026", "17-10-2026"]


# ------------------------------------------------------------ dependencias


def test_agrupacion_de_viaje_confirmada_bloquea(con_guia):
    from atlas_core.agrupacion_viajes import SCHEMA_VERSION
    (con_guia["actual"] / "agrupaciones_viaje.json").write_text(json.dumps({
        "schema_version": SCHEMA_VERSION,
        "agrupaciones": [{"agrupacion_id": "g1", "estado": "ACTIVA", "transportes": [TRANSPORTE, "0000900009"]}],
    }), encoding="utf-8")
    antes = _huellas(con_guia)
    r = OperadorB1(con_guia["raiz"]).atender("conv-fecha", INSTRUCCION)
    assert r["estado"] == "RECHAZADA" and r["codigo"] == "PRECONDICION_FALLIDA", r
    assert "agrupación de viaje confirmada" in r["mensaje"] and "No se corrigió nada" in r["mensaje"]
    assert _huellas(con_guia) == antes


def test_guias_del_mismo_viaje_con_otra_fecha_se_advierten(con_guia):
    filas = _filas(con_guia)
    filas.append(_fila(OTRA, fecha="18-10-2026"))
    _escribir(con_guia, filas)
    b1 = OperadorB1(con_guia["raiz"])
    r = b1.atender("conv-fecha", INSTRUCCION)
    assert r["estado"] == "PREVIEW_PENDIENTE", r
    assert f"la guía {OTRA} tiene fecha 18-10-2026" in r["mensaje"] and "quedará en revisión" in r["mensaje"]
    assert r["preview"]["afectados"]["guias_del_viaje_con_otra_fecha"] == [{"numero_guia": OTRA, "fecha": "18-10-2026"}]
    # La otra guía nunca se toca.
    assert b1.atender("conv-fecha", "sí")["estado"] == "EJECUTADA"
    assert _fila_guia(con_guia, OTRA)["fecha"] == "18-10-2026"


def test_guias_del_viaje_con_la_misma_fecha_propuesta_no_advierten(con_guia):
    filas = _filas(con_guia)
    filas.append(_fila(OTRA, fecha="19-10-2026"))
    _escribir(con_guia, filas)
    r = OperadorB1(con_guia["raiz"]).atender("conv-fecha", INSTRUCCION)
    assert r["estado"] == "PREVIEW_PENDIENTE" and "quedará en revisión" not in r["mensaje"], r


def test_cambio_en_el_viaje_entre_preview_y_confirmacion_invalida_el_preview(con_guia):
    b1 = OperadorB1(con_guia["raiz"])
    assert b1.atender("conv-fecha", INSTRUCCION)["estado"] == "PREVIEW_PENDIENTE"
    filas = _filas(con_guia)
    filas.append(_fila(OTRA, fecha="18-10-2026"))
    _escribir(con_guia, filas)
    r = b1.atender("conv-fecha", "sí")
    assert r["estado"] != "EJECUTADA", r
    assert _fila_guia(con_guia)["fecha"] == "18-10-2026"


def _asignar(con_guia, patente, desde):
    vehiculo = _vehiculo(patente)
    vehiculo["evidencias"][0]["campos_observados"]["rut_chofer_asociado"] = RUT_ACTIVO
    vehiculo["evidencias"][0]["fecha"] = f"{desde}T00:00:00+00:00"
    (con_guia["cat"] / "vehiculos.json").write_text(json.dumps({"version": 1, "vehiculos": [vehiculo]}),
                                                    encoding="utf-8")


def _patente_aplicada_al_procesar(con_guia):
    filas = _filas(con_guia)
    for fila in filas:
        if fila["numero_guia"] == GUIA:
            fila["metricas_procesamiento_json"] = json.dumps({"patentes_por_asignacion_chofer": {
                "resultado": "RESUELTO", "valor_ocr": {"patente_tracto": "ZZ9999"},
                "valor_aplicado": {"patente_tracto": "KN5439"}}})
    _escribir(con_guia, filas)


def test_patente_aplicada_por_asignacion_que_la_nueva_fecha_no_respalda_bloquea(con_guia):
    _asignar(con_guia, "KN5439", "2026-10-18")
    _patente_aplicada_al_procesar(con_guia)
    antes = _huellas(con_guia)
    r = OperadorB1(con_guia["raiz"]).atender("conv-fecha", "La fecha de emisión de la guía 482492 es 17-10-2026")
    assert r["estado"] == "RECHAZADA" and r["codigo"] == "PRECONDICION_FALLIDA", r
    assert "KN5439" in r["mensaje"] and "asignación" in r["mensaje"] and "18-10-2026" in r["mensaje"]
    assert _huellas(con_guia) == antes


def test_patente_aplicada_por_asignacion_que_sigue_respaldada_no_bloquea(con_guia):
    _asignar(con_guia, "KN5439", "2026-10-18")
    _patente_aplicada_al_procesar(con_guia)
    b1 = OperadorB1(con_guia["raiz"])
    assert b1.atender("conv-fecha", INSTRUCCION)["estado"] == "PREVIEW_PENDIENTE"
    assert b1.atender("conv-fecha", "sí")["estado"] == "EJECUTADA"
    assert _fila_guia(con_guia)["patente_tracto"] == "KN5439"


def test_patente_operacional_proyectada_que_cambia_con_la_fecha_se_advierte(con_guia):
    # La guía imprime otra patente; desde el 19-10 el chofer tiene KN5439
    # asignado. Con fecha 18-10 no se infiere hacia atrás; con 19-10 sí.
    filas = _filas(con_guia)
    for fila in filas:
        if fila["numero_guia"] == GUIA:
            fila["patente_tracto"] = "AB1234"
    _escribir(con_guia, filas)
    _asignar(con_guia, "KN5439", "2026-10-19")
    r = OperadorB1(con_guia["raiz"]).atender("conv-fecha", INSTRUCCION)
    assert r["estado"] == "PREVIEW_PENDIENTE", r
    assert "patente operacional del tracto pasa de AB1234 a KN5439" in r["mensaje"], r["mensaje"]
