"""(A) Política ESPERA TÉCNICA: destino con identidad confirmada por un
humano al que sólo le falta una ubicación ruteable -> no se vuelve a
preguntar; ESPERANDO_EVIDENCIA_NUEVA hasta que cambie el conocimiento.
(B) Cuarentena reversible EN_INVESTIGACION de un documento.

Equivalentes sintéticos de 472541/472647 y 480604. Todo sobre `tmp_path`,
proveedores simulados, sin red; nunca la operación real.
"""
from __future__ import annotations

import csv
import json
from datetime import timedelta
from pathlib import Path

import pytest

from atlas_core import decisiones_pendientes as dp
from atlas_core import procesamiento_masivo as pm
from atlas_core.aplicacion_decisiones import ErrorAplicacionDecision, aplicar_decision_obra
from atlas_core.investigacion_documental import (
    archivos_en_investigacion, leer_registro, levantar_investigacion, poner_en_investigacion,
)
from atlas_core.revalidacion_documental import reconciliar_decisiones_destino_no_resuelto
from test_ciclo_pendientes_tecnicos_simulado import AHORA, Operacion, _escribir_csv, _fila

AGOTABLE = "COORDENADA_NO_CONFIRMADA(5)"
CAUSA = "DIRECCION_CONFIRMADA_POR_HUMANO__GEOCODER_NO_RESUELVE"


@pytest.fixture
def op(tmp_path):
    return Operacion(tmp_path)


def _tarjetas(op: Operacion, guia: str | None = None) -> list[dict]:
    return [d for d in op.decisiones() if guia is None or d["documento"]["numero_guia"] == guia]


def _bytes(ruta: Path) -> bytes | None:
    return ruta.read_bytes() if ruta.is_file() else None


# =============================================================== A. espera técnica

def test_A1_equivalente_472541_agotado_queda_esperando_evidencia_sin_tarjeta(op):
    op.confirmar_destino_de_obra(con_coordenadas=False)
    op.sembrar([_fila("472901", AGOTABLE, op.planta_id)], intentos=2)
    resultado = op.mantener()  # 3er intento AGOTABLE: agota
    assert [e["numero_guia"] for e in resultado["elegibles"]] == ["472901"]
    assert _tarjetas(op) == []
    registro = op.pendientes()["472901"]
    assert registro["estado_espera"] == "ESPERANDO_EVIDENCIA_NUEVA"
    assert registro["causa_siguiente_accion"] == CAUSA
    assert resultado["limbos"]["detectados"] == [] and resultado["tarjetas_publicadas"] == []


def test_A2_equivalente_472647_tarjeta_de_la_politica_anterior_se_retira_y_espera(op, monkeypatch):
    """La tarjeta UBICACION_RUTEABLE ya publicada (política c969d6a) se
    retira en la siguiente regeneración y la guía termina en espera."""
    op.confirmar_destino_de_obra(con_coordenadas=False)
    op.sembrar([_fila("472902", AGOTABLE, op.planta_id)], intentos=3)
    with monkeypatch.context() as parche:  # reproduce la política anterior
        parche.setattr(dp, "guias_destino_confirmado_sin_ubicacion_ruteable", lambda **kw: frozenset())
        from atlas_core import mantenimiento_pendientes_tecnicos as mant
        from atlas_core import reconciliacion_estado_derivado as rec
        parche.setattr(mant, "guias_destino_confirmado_sin_ubicacion_ruteable", lambda **kw: frozenset())
        parche.setattr(rec, "guias_destino_confirmado_sin_ubicacion_ruteable", lambda **kw: frozenset())
        op.mantener()
    (vieja,) = _tarjetas(op, "472902")
    assert vieja["contexto"]["falta"] == "UBICACION_RUTEABLE"

    reconciliar_decisiones_destino_no_resuelto(raiz_atlas=op.raiz, reloj=lambda: AHORA)
    assert _tarjetas(op, "472902") == [], "la regeneración retira la pregunta repetida"
    for minutos in range(0, 6 * 60, 31):  # la guía vuelve a la cola y agota de nuevo
        op.mantener(AHORA + timedelta(minutes=minutos))
    assert _tarjetas(op, "472902") == []
    registro = op.pendientes()["472902"]
    assert (registro["estado_espera"], registro["causa_siguiente_accion"]) == ("ESPERANDO_EVIDENCIA_NUEVA", CAUSA)


def test_A3_conocimiento_nuevo_la_vuelve_evaluable(op):
    destino_id = op.confirmar_destino_de_obra(con_coordenadas=False)
    op.sembrar([_fila("472901", AGOTABLE, op.planta_id)], intentos=2)
    op.mantener()
    assert op.pendientes()["472901"]["causa_siguiente_accion"] == CAUSA
    # Llega una coordenada real al catálogo (conocimiento nuevo).
    catalogo = op.catalogos / "destinos_maestros.json"
    contenido = json.loads(catalogo.read_text(encoding="utf-8"))
    for d in contenido["destinos"]:
        if d["destino_id"] == destino_id:
            d.update(latitud=-33.45, longitud=-70.54)
    catalogo.write_text(json.dumps(contenido), encoding="utf-8")
    resultado = op.mantener(AHORA + timedelta(minutes=1))
    assert resultado["elegibles"] == [{"numero_guia": "472901", "causa": "CONOCIMIENTO_CAMBIO", "clase": "AGOTABLE"}]
    assert resultado["resueltas"] == ["472901"]


def test_A3b_evidencia_nueva_de_la_guia_reinicia_sus_intentos(op):
    op.confirmar_destino_de_obra(con_coordenadas=False)
    op.sembrar([_fila("472901", AGOTABLE, op.planta_id)], intentos=2)
    op.mantener()
    with op.dataset.open(encoding="utf-8-sig", newline="") as f:
        filas = list(csv.DictReader(f, delimiter=";"))
    filas[0]["motivo_ruta"] = "COORDENADA_NO_CONFIRMADA(3)"  # otra evidencia de ruteo
    _escribir_csv(op.dataset, filas)
    resultado = op.mantener(AHORA + timedelta(minutes=1))
    assert [e["numero_guia"] for e in resultado["elegibles"]] == ["472901"]
    assert op.pendientes()["472901"]["intentos_misma_evidencia"] == 1


def test_A4_destino_realmente_desconocido_sigue_preguntando(op):
    op.confirmar_destino_de_obra(con_coordenadas=False)
    op.sembrar([_fila("472903", AGOTABLE, op.planta_id, obra_destino="OBRA SIN DESTINO CONOCIDO",
                      despachar_a_crudo="PASAJE SIN UBICAR 12")], intentos=2)
    op.mantener()
    (tarjeta,) = _tarjetas(op, "472903")
    assert tarjeta["tipo"] == "DESTINO_NO_RESUELTO"
    assert "REGISTRAR_DIRECCION" in tarjeta["acciones_permitidas"]


def test_A5_A6_sin_respuesta_humana_ficticia_ni_coordenadas_inventadas(op):
    op.confirmar_destino_de_obra(con_coordenadas=False)
    op.sembrar([_fila("472901", AGOTABLE, op.planta_id)], intentos=2)
    ledger = op.actual / "decisiones_aplicadas.json"
    antes = {n: _bytes(op.catalogos / n) for n in ("destinos_maestros.json", "obras_destinos.json", "clientes.json")}
    ledger_antes = _bytes(ledger)
    for minutos in (0, 31, 62, 24 * 60):
        op.mantener(AHORA + timedelta(minutes=minutos))
    assert _bytes(ledger) == ledger_antes, "ninguna respuesta humana registrada"
    assert {n: _bytes(op.catalogos / n) for n in antes} == antes, "catálogos intactos (sin coordenadas)"
    destinos = json.loads((op.catalogos / "destinos_maestros.json").read_text(encoding="utf-8"))["destinos"]
    assert all(d["latitud"] is None and d["longitud"] is None for d in destinos)


def test_A7_sin_bucle_ni_republicacion_en_pasadas_sucesivas(op):
    op.confirmar_destino_de_obra(con_coordenadas=False)
    op.sembrar([_fila("472901", AGOTABLE, op.planta_id)], intentos=2)
    op.mantener()
    # Una pasada de convergencia: sólo el campo legado `escalamiento` se
    # recalcula a partir de los intentos ya agotados (comportamiento previo).
    op.mantener(AHORA + timedelta(minutes=1))
    pendientes = (op.actual / "pendientes_tecnicos.json").read_bytes()
    for minutos in (5, 31, 60, 24 * 60):
        resultado = op.mantener(AHORA + timedelta(minutes=minutos))
        assert resultado["motivo"] == "SIN_ELEGIBLES"
        assert resultado["tarjetas_publicadas"] == [] and resultado["limbos"]["detectados"] == []
    assert (op.actual / "pendientes_tecnicos.json").read_bytes() == pendientes
    assert _tarjetas(op) == []


# =================================================================== B. cuarentena

DOC_Q = "480999.jpeg"
DOC_OTRO = "480998.jpeg"
TRANSPORTE = "0000369999"


def _decision(decision_id: str, tipo: str, archivo: str, guia: str, **extra) -> dict:
    return {
        "decision_id": decision_id, "estado": "PENDIENTE", "tipo": tipo, "entidad": extra.pop("entidad", "CLIENTE"),
        "documento": {"archivo": archivo, "numero_guia": guia, "numero_transporte": TRANSPORTE},
        "campo": extra.pop("campo", "cliente"), "valor_documental": extra.pop("valor", "PRODALAM SA"),
        "valor_normalizado": "", "identidad_resuelta": None, "contexto": extra.pop("contexto", None),
        "candidatos": [], "motivos": extra.pop("motivos", ["RUT_VALIDO_NO_EXISTE_EN_CATALOGO_MAESTRO"]),
        "evidencias": [], "acciones_permitidas": extra.pop("acciones", ["REGISTRAR", "NO_REGISTRAR", "POSPONER"]),
    }


@pytest.fixture
def doc(op):
    """480604 sintético (CLIENTE_DESCONOCIDO + DESTINO_NO_RESUELTO) y otro
    documento del MISMO viaje/cliente/chofer con su propia decisión."""
    filas = [
        _fila("No encontrado", "", op.planta_id, archivo=DOC_Q, numero_transporte=TRANSPORTE,
              estado_ruta="RUTA_CALCULADA", distancia_km="12.44", rut_cliente="16.762.301-8"),
        _fila("480998", "", op.planta_id, archivo=DOC_OTRO, numero_transporte=TRANSPORTE,
              estado_ruta="RUTA_CALCULADA"),
    ]
    _escribir_csv(op.dataset, filas)
    lote = op.raiz / "operacion" / "entradas" / "L1"
    lote.mkdir(parents=True)
    (lote / DOC_Q).write_bytes(b"foto girada sintetica")
    (lote / DOC_OTRO).write_bytes(b"otra foto")
    decisiones = [
        _decision("d-cliente-q", "CLIENTE_DESCONOCIDO", DOC_Q, "No encontrado"),
        _decision("d-destino-q", "DESTINO_NO_RESUELTO", DOC_Q, "No encontrado", entidad="DESTINO",
                  campo="despachar_a_crudo", valor="", motivos=["DESTINO_CONTAMINADO_POR_OTRA_SECCION"],
                  contexto={"obra_canonica": "No encontrado", "cliente_canonico": "PRODALAM SA", "obra_ausente": True},
                  acciones=["REGISTRAR_DIRECCION", "NO_PUEDO_DETERMINAR", "POSPONER"]),
        _decision("d-cliente-otro", "CLIENTE_DESCONOCIDO", DOC_OTRO, "480998"),
    ]
    dp.generar_artefacto(ruta_dataset=op.dataset, carpeta_catalogos=op.catalogos, decisiones=decisiones,
                         reloj=lambda: AHORA)
    return op


def _ids(op) -> list[str]:
    return sorted(d["decision_id"] for d in op.decisiones())


def _poner(op, **kw):
    return poner_en_investigacion(raiz_atlas=op.raiz, archivo=kw.get("archivo", DOC_Q), actor="CODEX",
                                  motivo="Evidencia contaminada por orientación", referencia_investigacion="INV-1",
                                  reloj=lambda: AHORA)


def test_B1_B8_cuarentena_retira_ambas_tarjetas_y_no_toca_otro_documento(doc):
    assert _ids(doc) == ["d-cliente-otro", "d-cliente-q", "d-destino-q"]
    resultado = _poner(doc)
    assert resultado["ok"] and not resultado["idempotente"]
    assert sorted(resultado["decisiones_retenidas"]) == ["d-cliente-q", "d-destino-q"]
    assert _ids(doc) == ["d-cliente-otro"], "otro documento del mismo viaje/cliente intacto"
    (registro,) = leer_registro(doc.raiz)["registros"]
    assert registro["estado"] == "ACTIVA" and registro["archivo"] == DOC_Q
    assert registro["actor"] == "CODEX" and registro["motivo"] and registro["referencia_investigacion"] == "INV-1"
    assert registro["activada_en"] == AHORA.isoformat() and len(registro["sha256_evidencia"]) == 64
    assert archivos_en_investigacion(doc.raiz) == {DOC_Q}


def test_B2_B3_sin_aprendizaje_ni_cambios_en_dataset_catalogos_ledger(doc):
    rutas = [doc.dataset, doc.actual / "decisiones_aplicadas.json",
             *(doc.catalogos / n for n in ("clientes.json", "destinos_maestros.json", "obras_destinos.json"))]
    antes = [_bytes(r) for r in rutas]
    _poner(doc)
    levantar_investigacion(raiz_atlas=doc.raiz, archivo=DOC_Q, actor="CODEX", motivo="fin", reloj=lambda: AHORA)
    assert [_bytes(r) for r in rutas] == antes


def test_B4_regeneracion_y_detectores_no_republican(doc):
    _poner(doc)
    (registro,) = leer_registro(doc.raiz)["registros"]
    retenidas = registro["decisiones_retenidas"]
    regeneradas = dp.regenerar_decisiones_persistidas(
        decisiones=retenidas, carpeta_catalogos=doc.catalogos, ruta_dataset=doc.dataset)
    assert regeneradas == []
    dp.generar_artefacto(ruta_dataset=doc.dataset, carpeta_catalogos=doc.catalogos,
                         decisiones=[*doc.decisiones(), *retenidas], reloj=lambda: AHORA)
    reconciliar_decisiones_destino_no_resuelto(raiz_atlas=doc.raiz, reloj=lambda: AHORA)
    # (la regeneración completa puede descartar la decisión sintética del
    # otro documento; lo que importa es que las retenidas no vuelvan)
    assert not {"d-cliente-q", "d-destino-q"} & set(_ids(doc))


def test_B5_aplicar_y_b1_respetan_la_cuarentena(doc, monkeypatch):
    _poner(doc)
    with pytest.raises(ErrorAplicacionDecision, match="investigación"):
        aplicar_decision_obra(raiz_atlas=doc.raiz, decision_id="d-cliente-q", accion="REGISTRAR")
    vistas: list[str] = []
    monkeypatch.setattr(pm, "_fila_requiere_atencion_operacional", lambda fila: vistas.append(fila["archivo"]) or False)
    pm._ejecutar_ia_operacional(doc.dataset, {DOC_Q, DOC_OTRO}, object(), doc.catalogos)
    assert vistas == [DOC_OTRO], "B1 nunca evalúa el documento en investigación"
    filas_historial: list = []

    class _Herramienta:
        nombre = "EVIDENCIA_HISTORIAL_ORIGEN"

    def _espia(filas, *a, **k):
        filas_historial.extend(filas)
        return _Herramienta()

    monkeypatch.setattr("atlas_core.atlas_ia.herramientas.herramienta_evidencia_historial_origen", _espia)
    with doc.dataset.open(encoding="utf-8-sig", newline="") as f:
        filas = list(csv.DictReader(f, delimiter=";"))
    try:
        pm._herramientas_b1_disponibles(filas=filas, carpeta_catalogos=doc.catalogos)
    except Exception:
        pass  # sólo importa qué filas recibió la herramienta de historial
    assert filas_historial and all(f["archivo"] != DOC_Q for f in filas_historial)


def test_B6_levantar_devuelve_las_decisiones_a_evaluacion(doc, monkeypatch):
    _poner(doc)
    recibidas: list[str] = []
    original = dp.regenerar_decisiones_persistidas
    monkeypatch.setattr(dp, "regenerar_decisiones_persistidas",
                        lambda **kw: recibidas.extend(d["decision_id"] for d in kw["decisiones"]) or original(**kw))
    resultado = levantar_investigacion(raiz_atlas=doc.raiz, archivo=DOC_Q, actor="CODEX", motivo="investigación cerrada",
                                       reloj=lambda: AHORA)
    assert resultado["ok"] and not resultado["idempotente"]
    assert {"d-cliente-q", "d-destino-q"} <= set(recibidas), "las retenidas se re-evalúan"
    assert set(resultado["decisiones_reevaluadas"]) <= {"d-cliente-q", "d-destino-q"}
    assert archivos_en_investigacion(doc.raiz) == frozenset()
    (registro,) = leer_registro(doc.raiz)["registros"]
    assert registro["estado"] == "LEVANTADA" and registro["levantada_por"] == "CODEX"
    assert registro["decisiones_retenidas"], "la trazabilidad se conserva"


def test_B6b_sin_cuarentena_vuelven_a_publicarse(doc):
    _poner(doc)
    levantar_investigacion(raiz_atlas=doc.raiz, archivo=DOC_Q, actor="CODEX", motivo="fin", reloj=lambda: AHORA)
    (registro,) = leer_registro(doc.raiz)["registros"]
    dp.generar_artefacto(ruta_dataset=doc.dataset, carpeta_catalogos=doc.catalogos,
                         decisiones=[*doc.decisiones(), *registro["decisiones_retenidas"]], reloj=lambda: AHORA)
    assert {"d-cliente-q", "d-destino-q"} <= set(_ids(doc))


def test_B7_idempotencia_poner_y_levantar(doc):
    primero = _poner(doc)
    bandeja = (doc.actual / "decisiones_pendientes.json").read_bytes()
    segundo = _poner(doc)
    assert segundo["idempotente"] and segundo["cuarentena_id"] == primero["cuarentena_id"]
    assert (doc.actual / "decisiones_pendientes.json").read_bytes() == bandeja
    assert len(leer_registro(doc.raiz)["registros"]) == 1
    levantar_investigacion(raiz_atlas=doc.raiz, archivo=DOC_Q, actor="CODEX", motivo="fin", reloj=lambda: AHORA)
    otra_vez = levantar_investigacion(raiz_atlas=doc.raiz, archivo=DOC_Q, actor="CODEX", motivo="fin",
                                      reloj=lambda: AHORA)
    assert otra_vez["idempotente"]
    assert [r["estado"] for r in leer_registro(doc.raiz)["registros"]] == ["LEVANTADA"]


def test_B9_hash_distinto_con_el_mismo_nombre_no_queda_en_cuarentena(doc):
    _poner(doc)
    (doc.raiz / "operacion" / "entradas" / "L1" / DOC_Q).write_bytes(b"OTRO documento con el mismo nombre")
    assert archivos_en_investigacion(doc.raiz) == frozenset()
    dp.generar_artefacto(ruta_dataset=doc.dataset, carpeta_catalogos=doc.catalogos,
                         decisiones=[*doc.decisiones(), _decision("d-nuevo", "CLIENTE_DESCONOCIDO", DOC_Q, "481000")],
                         reloj=lambda: AHORA)
    assert "d-nuevo" in _ids(doc)


def test_B_documento_inexistente_o_datos_incompletos_no_crean_cuarentena(doc):
    assert _poner(doc, archivo="no_existe.jpeg")["motivo"] == "DOCUMENTO_NO_ENCONTRADO_EN_DATASET"
    sin_actor = poner_en_investigacion(raiz_atlas=doc.raiz, archivo=DOC_Q, actor="", motivo="m",
                                       referencia_investigacion="")
    assert sin_actor["ok"] is False
    assert leer_registro(doc.raiz)["registros"] == []


def test_B_evidencia_en_investigacion_no_se_mueve_a_resuelta(doc):
    from atlas_core.evidencia_documental import mover_evidencia_resuelta_sin_revision_pendiente

    _poner(doc)
    movidos = mover_evidencia_resuelta_sin_revision_pendiente(
        doc.raiz, decisiones_pendientes={"decisiones": doc.decisiones()}, reloj=lambda: AHORA)["movidos"]
    assert DOC_Q not in movidos
    assert (doc.raiz / "operacion" / "entradas" / "L1" / DOC_Q).is_file()
