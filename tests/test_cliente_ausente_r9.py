"""Bloque R9 -- CLIENTE_AUSENTE: cierra un hueco real encontrado en el
lote nuevo (guías 472238/472239, mismo transporte 0000354443, cliente
"No encontrado"): `CLIENTE_AUSENTE` es un motivo bloqueante real
(`motivos_revision_documento`) sin NINGUNA decisión asociada -- el
documento quedaba huérfano en REQUIERE_REVISION para siempre, invisible
en Revisión de Atlas. Distinto de CLIENTE_DESCONOCIDO/CLIENTE_CANDIDATO/
ALIAS_CANDIDATO (todos exigen algún texto documental de partida): aquí no
hay ningún nombre que corroborar, sólo un humano puede escribir la razón
social real."""
from __future__ import annotations

import csv
import json

from atlas_core.aplicacion_decisiones import ErrorAplicacionDecision, aplicar_decision_obra
from atlas_core.catalogo_clientes import CatalogoClientes
from atlas_core.decisiones_pendientes import crear_decision, detectar_decision_cliente_ausente, generar_artefacto
from atlas_core.procesamiento_masivo import COLUMNAS
from atlas_core.revalidacion_documental import (
    detectar_decisiones_cliente_ausente_sin_ocr,
    reconciliar_decisiones_cliente_ausente,
)

FECHA = "20-08-2026"


def _fila_csv(**overrides):
    fila = {c: "" for c in COLUMNAS}
    fila.update({
        "archivo": "472238.jpeg", "estado_procesamiento": "OK", "numero_guia": "472238",
        "numero_transporte": "0000354443", "fecha": FECHA, "chofer": "WLADIMIR AGUILAR",
        "cliente": "No encontrado", "obra_destino": "VISTA CLARA 2351 CERRILLOS",
        "indicador_revision": "REVISAR", "motivos_revision_documento": "CLIENTE_AUSENTE",
        "planta_origen_id": "planta-colina", "planta_origen_nombre": "AZA COLINA",
    })
    fila.update(overrides)
    return fila


def _escribir_csv(ruta, filas):
    with ruta.open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader(); escritor.writerows(filas)


def _leer_csv(ruta):
    with ruta.open(encoding="utf-8-sig", newline="") as archivo:
        return {f["archivo"]: f for f in csv.DictReader(archivo, delimiter=";")}


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
        "plantas.json": {"version_formato": 1, "plantas": []},
    }.items():
        (catalogos / nombre).write_text(json.dumps(contenido), encoding="utf-8")
    dataset = actual / "analisis_completo_guias.csv"
    _escribir_csv(dataset, filas_csv)
    return {"raiz": raiz, "catalogos": catalogos, "actual": actual, "dataset": dataset}


def _publicar(entorno, decision):
    generar_artefacto(
        ruta_dataset=entorno["dataset"], carpeta_catalogos=entorno["catalogos"],
        decisiones=[decision], ruta_salida=entorno["actual"] / "decisiones_pendientes.json",
    )


# ============================================================
# Detección (pura)
# ============================================================


def test_genera_decision_para_cliente_genuinamente_ausente():
    decision = detectar_decision_cliente_ausente(archivo="472238.jpeg", fila=_fila_csv())
    assert decision is not None
    assert decision["tipo"] == "CLIENTE_AUSENTE"
    assert set(decision["acciones_permitidas"]) == {"REGISTRAR_CLIENTE_MANUAL", "NO_PUEDO_DETERMINAR", "POSPONER"}


def test_no_genera_decision_si_cliente_tiene_algun_valor():
    """Nombre presente (aunque no corroborable) -- eso lo cubren
    CLIENTE_CANDIDATO/CLIENTE_DESCONOCIDO/ALIAS_CANDIDATO, no este tipo."""
    fila = _fila_csv(cliente="EMPRESA X", motivos_revision_documento="")
    assert detectar_decision_cliente_ausente(archivo="x", fila=fila) is None


def test_no_genera_decision_si_el_motivo_ya_no_esta_presente():
    fila = _fila_csv(motivos_revision_documento="MATERIAL_AUSENTE")
    assert detectar_decision_cliente_ausente(archivo="x", fila=fila) is None


# ============================================================
# Escaneo del dataset completo
# ============================================================


def test_deteccion_de_dataset_completo_caso_real_472238_472239(tmp_path):
    entorno = _entorno(tmp_path, filas_csv=[
        _fila_csv(numero_guia="472238", archivo="472238.jpeg"),
        _fila_csv(numero_guia="472239", archivo="472239.jpeg"),
        _fila_csv(numero_guia="472162", archivo="472162.jpeg", cliente="ACMA SA", motivos_revision_documento=""),
    ])
    candidatas = detectar_decisiones_cliente_ausente_sin_ocr(raiz_atlas=entorno["raiz"])
    assert {c["documento"]["numero_guia"] for c in candidatas} == {"472238", "472239"}


def test_reconciliar_publica_ambas_en_la_bandeja(tmp_path):
    entorno = _entorno(tmp_path, filas_csv=[
        _fila_csv(numero_guia="472238", archivo="472238.jpeg"),
        _fila_csv(numero_guia="472239", archivo="472239.jpeg"),
    ])
    resultado = reconciliar_decisiones_cliente_ausente(raiz_atlas=entorno["raiz"])
    assert resultado["decisiones_candidatas"] == 2
    assert resultado["decisiones_publicadas"] == 2


# ============================================================
# Aplicación -- REGISTRAR_CLIENTE_MANUAL
# ============================================================


def test_registrar_cliente_manual_crea_cliente_y_resuelve_el_documento(tmp_path):
    entorno = _entorno(tmp_path, filas_csv=[_fila_csv()])
    decision = detectar_decision_cliente_ausente(archivo="472238.jpeg", fila=_fila_csv())
    _publicar(entorno, decision)

    resultado = aplicar_decision_obra(
        raiz_atlas=entorno["raiz"], decision_id=decision["decision_id"],
        accion="REGISTRAR_CLIENTE_MANUAL", razon_social_manual="COMERCIAL NUEVA SPA",
        rut_manual="76086428-5",
    )
    assert resultado["ok"] is True
    assert resultado["cliente_id"]

    clientes = CatalogoClientes(entorno["catalogos"] / "clientes.json").listar()
    assert len(clientes) == 1
    assert clientes[0].razon_social == "COMERCIAL NUEVA SPA"
    assert clientes[0].estado_calidad == "CONFIRMADO"

    fila = _leer_csv(entorno["dataset"])["472238.jpeg"]
    assert fila["cliente"] == "COMERCIAL NUEVA SPA"
    assert "CLIENTE_AUSENTE" not in fila["motivos_revision_documento"]
    assert fila["indicador_revision"] == "OK"

    bandeja = json.loads((entorno["actual"] / "decisiones_pendientes.json").read_text(encoding="utf-8"))
    assert bandeja["decisiones"] == []
    assert (entorno["raiz"] / "operacion" / "actual" / "estado_operacion.json").exists()


def test_registrar_cliente_manual_reutiliza_cliente_ya_existente(tmp_path):
    """Dos documentos del mismo transporte (caso real 472238/472239):
    registrar el mismo nombre dos veces reutiliza el mismo cliente_id, no
    crea un duplicado."""
    entorno = _entorno(tmp_path, filas_csv=[
        _fila_csv(numero_guia="472238", archivo="472238.jpeg"),
        _fila_csv(numero_guia="472239", archivo="472239.jpeg"),
    ])
    decision_238 = detectar_decision_cliente_ausente(archivo="472238.jpeg", fila=_fila_csv(numero_guia="472238", archivo="472238.jpeg"))
    decision_239 = detectar_decision_cliente_ausente(archivo="472239.jpeg", fila=_fila_csv(numero_guia="472239", archivo="472239.jpeg"))
    generar_artefacto(
        ruta_dataset=entorno["dataset"], carpeta_catalogos=entorno["catalogos"],
        decisiones=[decision_238, decision_239], ruta_salida=entorno["actual"] / "decisiones_pendientes.json",
    )

    r1 = aplicar_decision_obra(
        raiz_atlas=entorno["raiz"], decision_id=decision_238["decision_id"],
        accion="REGISTRAR_CLIENTE_MANUAL", razon_social_manual="COMERCIAL NUEVA SPA",
    )
    r2 = aplicar_decision_obra(
        raiz_atlas=entorno["raiz"], decision_id=decision_239["decision_id"],
        accion="REGISTRAR_CLIENTE_MANUAL", razon_social_manual="COMERCIAL NUEVA SPA",
    )
    assert r1["cliente_id"] == r2["cliente_id"]
    clientes = CatalogoClientes(entorno["catalogos"] / "clientes.json").listar()
    assert len(clientes) == 1


def test_registrar_cliente_manual_sin_texto_falla(tmp_path):
    entorno = _entorno(tmp_path, filas_csv=[_fila_csv()])
    decision = detectar_decision_cliente_ausente(archivo="472238.jpeg", fila=_fila_csv())
    _publicar(entorno, decision)
    try:
        aplicar_decision_obra(
            raiz_atlas=entorno["raiz"], decision_id=decision["decision_id"],
            accion="REGISTRAR_CLIENTE_MANUAL", razon_social_manual="   ",
        )
        assert False, "debía lanzar"
    except ErrorAplicacionDecision:
        pass


def test_no_puedo_determinar_es_terminal_y_no_toca_el_dataset(tmp_path):
    entorno = _entorno(tmp_path, filas_csv=[_fila_csv()])
    decision = detectar_decision_cliente_ausente(archivo="472238.jpeg", fila=_fila_csv())
    _publicar(entorno, decision)
    fila_antes = _leer_csv(entorno["dataset"])["472238.jpeg"]

    resultado = aplicar_decision_obra(
        raiz_atlas=entorno["raiz"], decision_id=decision["decision_id"], accion="NO_PUEDO_DETERMINAR",
    )
    assert resultado["ok"] is True
    fila_despues = _leer_csv(entorno["dataset"])["472238.jpeg"]
    assert fila_antes == fila_despues

    resultado_reconciliado = reconciliar_decisiones_cliente_ausente(raiz_atlas=entorno["raiz"])
    assert resultado_reconciliado["decisiones_publicadas"] == 0


# ============================================================
# Bloque URGENTE -- BUG NameError 'MOTIVOS_NO_BLOQUEANTES' (caso real
# 464265, motivos_revision_documento con MÁS de un motivo simultáneo:
# "OBRA_DESTINO_SIN_CORROBORAR | CLIENTE_AUSENTE"). El fixture por
# defecto de este archivo (_fila_csv, un solo motivo CLIENTE_AUSENTE)
# nunca disparaba esto: tras .discard("CLIENTE_AUSENTE") el set queda
# VACÍO, y `any(... for m in motivos_fila)` sobre un generador vacío
# nunca llega a evaluar el cuerpo (nunca toca MOTIVOS_NO_BLOQUEANTES) --
# exactamente por qué los tests existentes no detectaron el NameError.
# Esta regresión usa DOS motivos a la vez, como el caso real, para
# atravesar de verdad la rama que fallaba.
# ============================================================

def test_registrar_cliente_manual_con_otro_motivo_simultaneo_no_lanza_nameerror(tmp_path):
    """Caso real 464265: CLIENTE_AUSENTE conviviendo con
    OBRA_DESTINO_SIN_CORROBORAR -- tras resolver CLIENTE_AUSENTE, el otro
    motivo sigue bloqueante (indicador_revision debe seguir REVISAR, no
    OK), y la evaluación de MOTIVOS_NO_BLOQUEANTES debe ejecutarse de
    verdad, sin NameError."""
    fila = _fila_csv(motivos_revision_documento="OBRA_DESTINO_SIN_CORROBORAR | CLIENTE_AUSENTE")
    entorno = _entorno(tmp_path, filas_csv=[fila])
    decision = detectar_decision_cliente_ausente(archivo="472238.jpeg", fila=fila)
    _publicar(entorno, decision)

    resultado = aplicar_decision_obra(
        raiz_atlas=entorno["raiz"], decision_id=decision["decision_id"],
        accion="REGISTRAR_CLIENTE_MANUAL", razon_social_manual="SODIMAC SA",
    )

    assert resultado["ok"] is True
    fila_final = _leer_csv(entorno["dataset"])["472238.jpeg"]
    assert fila_final["cliente"] == "SODIMAC SA"
    assert "CLIENTE_AUSENTE" not in fila_final["motivos_revision_documento"]
    assert "OBRA_DESTINO_SIN_CORROBORAR" in fila_final["motivos_revision_documento"]
    # El otro motivo sigue siendo bloqueante -- nunca queda OK en falso.
    assert fila_final["indicador_revision"] == "REVISAR"
    assert fila_final["estado_documental"] == "REQUIERE_REVISION"

    bandeja = json.loads((entorno["actual"] / "decisiones_pendientes.json").read_text(encoding="utf-8"))
    assert bandeja["decisiones"] == []  # CLIENTE_AUSENTE se retiró tras el éxito


def test_registrar_cliente_manual_con_motivo_no_bloqueante_restante_queda_ok(tmp_path):
    """Control -- si lo único que queda es un motivo NO bloqueante
    (MOTIVOS_NO_BLOQUEANTES), sí debe quedar OK -- confirma que la
    constante recién importada se usa con la semántica correcta, no sólo
    que no truena."""
    fila = _fila_csv(motivos_revision_documento="MATERIAL_AUSENTE | CLIENTE_AUSENTE")
    entorno = _entorno(tmp_path, filas_csv=[fila])
    decision = detectar_decision_cliente_ausente(archivo="472238.jpeg", fila=fila)
    _publicar(entorno, decision)

    aplicar_decision_obra(
        raiz_atlas=entorno["raiz"], decision_id=decision["decision_id"],
        accion="REGISTRAR_CLIENTE_MANUAL", razon_social_manual="SODIMAC SA",
    )

    fila_final = _leer_csv(entorno["dataset"])["472238.jpeg"]
    assert fila_final["indicador_revision"] == "OK"
    assert fila_final["estado_documental"] == "OK"


def test_otras_decisiones_pendientes_quedan_intactas_al_resolver_una(tmp_path):
    """Aplicar una decisión nunca debe tocar otra decisión pendiente no
    relacionada (mismo principio que exige la prueba real de las 3
    decisiones: resolver 464265 no puede afectar a 464264)."""
    fila_238 = _fila_csv(
        numero_guia="472238", archivo="472238.jpeg",
        motivos_revision_documento="OBRA_DESTINO_SIN_CORROBORAR | CLIENTE_AUSENTE",
    )
    fila_239 = _fila_csv(
        numero_guia="472239", archivo="472239.jpeg", cliente="OTRO CLIENTE YA CONOCIDO",
        motivos_revision_documento="",
    )
    entorno = _entorno(tmp_path, filas_csv=[fila_238, fila_239])
    decision_238 = detectar_decision_cliente_ausente(archivo="472238.jpeg", fila=fila_238)
    decision_otra = crear_decision(
        tipo="OBRA_DESCONOCIDA", entidad="OBRA", archivo="472239.jpeg",
        numero_guia="472239", numero_transporte="0000354443", campo="obra_destino",
        valor_documental="OBRA X", valor_normalizado="OBRA X", identidad_resuelta=None,
        candidatos=(), motivos=("OBRA_NO_CATALOGADA",), evidencias=({"tipo": "SIN_COINCIDENCIA"},),
        acciones_permitidas=("REGISTRAR", "NO_REGISTRAR", "POSPONER"),
    )
    generar_artefacto(
        ruta_dataset=entorno["dataset"], carpeta_catalogos=entorno["catalogos"],
        decisiones=[decision_238, decision_otra], ruta_salida=entorno["actual"] / "decisiones_pendientes.json",
    )

    aplicar_decision_obra(
        raiz_atlas=entorno["raiz"], decision_id=decision_238["decision_id"],
        accion="REGISTRAR_CLIENTE_MANUAL", razon_social_manual="SODIMAC SA",
    )

    bandeja = json.loads((entorno["actual"] / "decisiones_pendientes.json").read_text(encoding="utf-8"))
    tipos_restantes = {d["tipo"] for d in bandeja["decisiones"]}
    assert tipos_restantes == {"OBRA_DESCONOCIDA"}  # la otra decisión sigue intacta, PENDIENTE


def test_reintento_tras_error_no_duplica_aprendizaje(tmp_path):
    """Idempotencia razonable: si la MISMA razón social se registra dos
    veces (p. ej. un reintento tras un fallo previo), no debe crear un
    segundo cliente -- mismo mecanismo ya probado en
    test_registrar_cliente_manual_reutiliza_cliente_ya_existente, ahora
    con el motivo compuesto real."""
    fila = _fila_csv(motivos_revision_documento="OBRA_DESTINO_SIN_CORROBORAR | CLIENTE_AUSENTE")
    entorno = _entorno(tmp_path, filas_csv=[fila])
    decision = detectar_decision_cliente_ausente(archivo="472238.jpeg", fila=fila)
    _publicar(entorno, decision)

    aplicar_decision_obra(
        raiz_atlas=entorno["raiz"], decision_id=decision["decision_id"],
        accion="REGISTRAR_CLIENTE_MANUAL", razon_social_manual="SODIMAC SA",
    )
    clientes_tras_primer_intento = CatalogoClientes(entorno["catalogos"] / "clientes.json").listar()
    assert len(clientes_tras_primer_intento) == 1

    # La decisión ya se retiró de la bandeja -- reaplicar el mismo
    # decision_id (simula un reintento/doble clic tras la resolución) no
    # debe, bajo ninguna circunstancia (ni error ni éxito silencioso),
    # crear un segundo cliente -- el mecanismo de deduplicación por
    # nombre normalizado ya cubre esto (ClienteDuplicadoError -> se
    # reutiliza el existente), incluso si `aplicar_decision_obra` no
    # rechaza explícitamente un decision_id ya resuelto.
    try:
        aplicar_decision_obra(
            raiz_atlas=entorno["raiz"], decision_id=decision["decision_id"],
            accion="REGISTRAR_CLIENTE_MANUAL", razon_social_manual="SODIMAC SA",
        )
    except ErrorAplicacionDecision:
        pass
    clientes_final = CatalogoClientes(entorno["catalogos"] / "clientes.json").listar()
    assert len(clientes_final) == 1, "un reintento nunca debe duplicar el aprendizaje ya persistido"
