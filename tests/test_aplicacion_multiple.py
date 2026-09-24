"""Bloque P0 REVISIÓN RÁPIDA / APLICACIÓN MÚLTIPLE --
`aplicar_decisiones_multiples`. Reutiliza el mismo fixture mínimo que
`tests/test_aplicacion_decisiones_r33.py` (OBRA_DESCONOCIDA/REGISTRAR,
la decisión más simple que `aplicar_decision_obra` ya sabe aplicar de
punta a punta) para poder construir VARIAS decisiones independientes
(distinto archivo/guía) sin reimplementar reglas de negocio.

`reconciliar_estado_derivado` se reemplaza por un contador falso en
todos los tests -- nunca se ejecuta la batería real aquí (cara incluso
en un dataset sintético, y ya cubierta por sus propios tests); lo único
que este bloque verifica es CUÁNTAS VECES se invoca, no qué hace."""
import json
import os
import time

import pytest

from atlas_core.almacenamiento_portable import SesionOcupadaError
from atlas_core.aplicacion_decisiones import (
    TIEMPO_EXPIRACION_LOCK_APLICAR_DECISION_SEGUNDOS,
    aplicar_decision_obra,
)
from atlas_core.aplicacion_multiple import aplicar_decisiones_multiples
from atlas_core.catalogo_clientes import CatalogoClientes, EstadoCalidadCliente
from atlas_core.catalogo_obras_destinos import CatalogoObrasDestinos
from atlas_core.decisiones_pendientes import crear_decision, generar_artefacto
from atlas_core.procesamiento_masivo import COLUMNAS


def _entorno(tmp_path):
    raiz = tmp_path / "Atlas"; catalogos = raiz / "catalogos_privados"; actual = raiz / "operacion" / "actual"
    catalogos.mkdir(parents=True); actual.mkdir(parents=True)
    for nombre, contenido in {
        "clientes.json": {"version_formato": 1, "clientes": []}, "empresas.json": {},
        "vehiculos.json": {}, "obras_destinos.json": {"version_formato": 1, "obras": [], "relaciones": []},
        "destinos_maestros.json": {"version_formato": 1, "destinos": []},
    }.items():
        (catalogos / nombre).write_text(json.dumps(contenido), encoding="utf-8")
    cliente = CatalogoClientes(catalogos / "clientes.json").crear(
        razon_social="CLIENTE CANONICO SA", rut="50.234.350-5", fuente="TEST",
        estado_calidad=EstadoCalidadCliente.CONFIRMADO,
    )
    return raiz, catalogos, actual, cliente


def _decision_obra(archivo, numero_guia, cliente, obra):
    return crear_decision(
        tipo="OBRA_DESCONOCIDA", entidad="OBRA", archivo=archivo, numero_guia=numero_guia,
        numero_transporte=f"T{numero_guia}", campo="obra_destino", valor_documental=obra,
        valor_normalizado=obra, identidad_resuelta=None, candidatos=(),
        motivos=("OBRA_NO_EXISTE_PARA_CLIENTE",),
        evidencias=({"tipo": "CLIENTE_RESUELTO", "entidad_id": cliente.cliente_id},),
        acciones_permitidas=("REGISTRAR", "NO_REGISTRAR", "POSPONER"),
        contexto={"cliente_id": cliente.cliente_id, "cliente_canonico": cliente.razon_social},
    )


def _tres_decisiones(tmp_path):
    raiz, catalogos, actual, cliente = _entorno(tmp_path)
    dataset = actual / "analisis_completo_guias.csv"
    import csv
    filas = []
    for numero_guia, archivo, obra in (
        ("100", "100.png", "OBRA UNO"), ("200", "200.png", "OBRA DOS"), ("300", "300.png", "OBRA TRES"),
    ):
        fila = {c: "" for c in COLUMNAS}
        fila.update({
            "archivo": archivo, "estado_procesamiento": "OK", "numero_guia": numero_guia,
            "numero_transporte": f"T{numero_guia}", "fecha": "01-08-2026",
            "cliente": "CLIENTE CANONICO SA", "obra_destino": obra,
            "indicador_revision": "REVISAR", "motivos_revision_documento": "OBRA_DESTINO_SIN_CORROBORAR",
        })
        filas.append(fila)
    with dataset.open("w", newline="", encoding="utf-8-sig") as archivo_csv:
        escritor = csv.DictWriter(archivo_csv, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader()
        for fila in filas:
            escritor.writerow(fila)
    decisiones = [
        _decision_obra("100.png", "100", cliente, "OBRA UNO"),
        _decision_obra("200.png", "200", cliente, "OBRA DOS"),
        _decision_obra("300.png", "300", cliente, "OBRA TRES"),
    ]
    generar_artefacto(
        ruta_dataset=dataset, carpeta_catalogos=catalogos, decisiones=decisiones,
        ruta_salida=actual / "decisiones_pendientes.json",
    )
    return raiz, catalogos, actual, cliente, decisiones


def _contador_reconciliacion(monkeypatch):
    llamadas = []

    def _falso(*, raiz_atlas, reloj=None, proveedor_rutas=None, proveedor_rutas_fallback=None,
               guias_excluir_reintento_ruta=None):
        llamadas.append(raiz_atlas)
        return {"reconciliado": True, "motivo": "TEST"}

    monkeypatch.setattr("atlas_core.reconciliacion_estado_derivado.reconciliar_estado_derivado", _falso)
    return llamadas


def test_tres_decisiones_de_tres_guias_distintas_se_aplican_todas(tmp_path, monkeypatch):
    raiz, catalogos, actual, cliente, decisiones = _tres_decisiones(tmp_path)
    llamadas = _contador_reconciliacion(monkeypatch)
    solicitudes = [{"decision_id": d["decision_id"], "accion": "REGISTRAR"} for d in decisiones]
    resultado = aplicar_decisiones_multiples(raiz_atlas=raiz, solicitudes=solicitudes)
    assert resultado.total_solicitadas == 3
    assert resultado.total_aplicadas == 3
    assert all(r.aplicada for r in resultado.resultados)
    assert [r.archivo for r in resultado.resultados] == ["100.png", "200.png", "300.png"]


def test_dejar_una_sin_seleccionar_no_la_toca(tmp_path, monkeypatch):
    raiz, catalogos, actual, cliente, decisiones = _tres_decisiones(tmp_path)
    _contador_reconciliacion(monkeypatch)
    solicitudes = [{"decision_id": decisiones[0]["decision_id"], "accion": "REGISTRAR"}]
    resultado = aplicar_decisiones_multiples(raiz_atlas=raiz, solicitudes=solicitudes)
    assert resultado.total_aplicadas == 1
    pendientes = json.loads((actual / "decisiones_pendientes.json").read_text(encoding="utf-8"))["decisiones"]
    ids_pendientes = {d["decision_id"] for d in pendientes}
    assert decisiones[1]["decision_id"] in ids_pendientes
    assert decisiones[2]["decision_id"] in ids_pendientes


def test_una_reconciliacion_unica_para_todo_el_lote_no_una_por_decision(tmp_path, monkeypatch):
    raiz, catalogos, actual, cliente, decisiones = _tres_decisiones(tmp_path)
    llamadas = _contador_reconciliacion(monkeypatch)
    solicitudes = [{"decision_id": d["decision_id"], "accion": "REGISTRAR"} for d in decisiones]
    aplicar_decisiones_multiples(raiz_atlas=raiz, solicitudes=solicitudes)
    assert len(llamadas) == 1


def test_decision_ya_no_vigente_se_reporta_sin_abortar_el_resto(tmp_path, monkeypatch):
    raiz, catalogos, actual, cliente, decisiones = _tres_decisiones(tmp_path)
    _contador_reconciliacion(monkeypatch)
    # La primera ya se aplicó por fuera del lote (p. ej. otra pestaña) --
    # deja de estar PENDIENTE antes de que arranque la aplicación múltiple.
    aplicar_decision_obra(raiz_atlas=raiz, decision_id=decisiones[0]["decision_id"], accion="REGISTRAR")
    solicitudes = [{"decision_id": d["decision_id"], "accion": "REGISTRAR"} for d in decisiones]
    resultado = aplicar_decisiones_multiples(raiz_atlas=raiz, solicitudes=solicitudes)
    assert resultado.total_solicitadas == 3
    assert resultado.total_aplicadas == 2
    primero = next(r for r in resultado.resultados if r.decision_id == decisiones[0]["decision_id"])
    assert primero.aplicada is False
    assert "vigente" in primero.motivo.lower() or "obsolet" in primero.motivo.lower()
    assert all(r.aplicada for r in resultado.resultados if r.decision_id != decisiones[0]["decision_id"])


def test_ninguna_aplicada_no_dispara_reconciliacion(tmp_path, monkeypatch):
    raiz, catalogos, actual, cliente, decisiones = _tres_decisiones(tmp_path)
    llamadas = _contador_reconciliacion(monkeypatch)
    solicitudes = [{"decision_id": "id-inexistente", "accion": "REGISTRAR"}]
    resultado = aplicar_decisiones_multiples(raiz_atlas=raiz, solicitudes=solicitudes)
    assert resultado.total_aplicadas == 0
    assert len(llamadas) == 0
    assert resultado.reconciliacion_ejecutada is False


def test_resultado_nunca_desaparece_una_decision_silenciosamente(tmp_path, monkeypatch):
    raiz, catalogos, actual, cliente, decisiones = _tres_decisiones(tmp_path)
    _contador_reconciliacion(monkeypatch)
    solicitudes = [{"decision_id": d["decision_id"], "accion": "REGISTRAR"} for d in decisiones]
    solicitudes.append({"decision_id": "id-inexistente", "accion": "REGISTRAR"})
    resultado = aplicar_decisiones_multiples(raiz_atlas=raiz, solicitudes=solicitudes)
    assert resultado.total_solicitadas == 4
    assert len(resultado.resultados) == 4
    ids_reportados = {r.decision_id for r in resultado.resultados}
    assert "id-inexistente" in ids_reportados
    assert all(d["decision_id"] in ids_reportados for d in decisiones)


# ============================================================
# Bloque P0 RECUPERACIÓN TRANSACCIONAL -- caso real 0000359449: Javier
# aplicó un lote de 5 decisiones de destino; el proceso murió a mitad
# (cierre forzado del PC), dejando un lock huérfano
# (`.atlas_lock_aplicar_decision_obra`, PID ya muerto) y el lote
# incompleto -- 1 decisión terminal y consistente, 4 sin aplicar. Estas
# pruebas cubren: interrupción real durante el lote, recuperación
# idempotente, lock activo real (nunca se ignora), lock huérfano
# (se autorepara), y que el CLI nunca expone un traceback por esto.
# ============================================================

def test_interrupcion_durante_el_lote_no_aborta_el_resto_ni_pierde_el_cierre(tmp_path, monkeypatch):
    """Caso real: la 2da de 3 decisiones choca con un lock ocupado
    (`SesionOcupadaError`) -- antes de este fix, eso escapaba del `try`
    del lote entero y abortaba TODO lo que quedaba, incluida la
    reconciliación de cierre para lo que sí se había aplicado. Ahora el
    lote sigue con la 3ra, y la reconciliación de cierre SÍ corre para
    las 2 que se aplicaron de verdad."""
    raiz, catalogos, actual, cliente, decisiones = _tres_decisiones(tmp_path)
    llamadas = _contador_reconciliacion(monkeypatch)

    import atlas_core.aplicacion_multiple as modulo_multiple
    real = modulo_multiple.aplicar_decision_obra
    id_bloqueada = decisiones[1]["decision_id"]

    def aplicar_con_bloqueo_simulado(*, decision_id, **kwargs):
        if decision_id == id_bloqueada:
            raise SesionOcupadaError("simulado -- otra operación sostiene el lock")
        return real(decision_id=decision_id, **kwargs)

    monkeypatch.setattr(modulo_multiple, "aplicar_decision_obra", aplicar_con_bloqueo_simulado)

    solicitudes = [{"decision_id": d["decision_id"], "accion": "REGISTRAR"} for d in decisiones]
    resultado = aplicar_decisiones_multiples(raiz_atlas=raiz, solicitudes=solicitudes)

    assert resultado.total_solicitadas == 3
    assert resultado.total_aplicadas == 2  # la 1ra y la 3ra, nunca abortadas por la 2da
    por_id = {r.decision_id: r for r in resultado.resultados}
    assert por_id[decisiones[0]["decision_id"]].aplicada is True
    assert por_id[decisiones[2]["decision_id"]].aplicada is True
    bloqueada = por_id[id_bloqueada]
    assert bloqueada.aplicada is False
    assert "intenta" in bloqueada.motivo.lower() or "operación" in bloqueada.motivo.lower()
    # El cierre del lote SÍ corrió -- no se perdió por la interrupción de
    # un solo ítem.
    assert len(llamadas) == 1
    assert resultado.reconciliacion_ejecutada is True

    # La decisión bloqueada sigue PENDIENTE de verdad -- nunca se marcó
    # como aplicada sin haberlo hecho.
    pendientes = json.loads((actual / "decisiones_pendientes.json").read_text(encoding="utf-8"))["decisiones"]
    assert id_bloqueada in {d["decision_id"] for d in pendientes if d["estado"] == "PENDIENTE"}


def test_reintento_del_lote_es_idempotente_y_completa_lo_pendiente(tmp_path, monkeypatch):
    """Tras la interrupción simulada de arriba, un reintento del MISMO
    lote (mismas 3 solicitudes, sin el bloqueo esta vez -- exactamente lo
    que Javier haría al volver a intentar desde Revisión de Atlas) debe
    completar la que había quedado pendiente y NUNCA duplicar las 2 que
    ya se habían aplicado de verdad en el primer intento (esas ya no
    están vigentes en la bandeja -- `aplicar_decisiones_multiples` las
    reporta como "ya no vigentes", nunca las reintenta a ciegas; el
    catálogo es la fuente de verdad de que no se duplicaron)."""
    raiz, catalogos, actual, cliente, decisiones = _tres_decisiones(tmp_path)
    _contador_reconciliacion(monkeypatch)

    import atlas_core.aplicacion_multiple as modulo_multiple
    real = modulo_multiple.aplicar_decision_obra
    id_bloqueada = decisiones[1]["decision_id"]

    def aplicar_con_bloqueo_simulado(*, decision_id, **kwargs):
        if decision_id == id_bloqueada:
            raise SesionOcupadaError("simulado")
        return real(decision_id=decision_id, **kwargs)

    monkeypatch.setattr(modulo_multiple, "aplicar_decision_obra", aplicar_con_bloqueo_simulado)
    solicitudes = [{"decision_id": d["decision_id"], "accion": "REGISTRAR"} for d in decisiones]
    aplicar_decisiones_multiples(raiz_atlas=raiz, solicitudes=solicitudes)

    # Reintento real -- sin el bloqueo simulado esta vez.
    monkeypatch.setattr(modulo_multiple, "aplicar_decision_obra", real)
    resultado_reintento = aplicar_decisiones_multiples(raiz_atlas=raiz, solicitudes=solicitudes)

    assert resultado_reintento.total_aplicadas == 1  # sólo la que había quedado pendiente
    por_id = {r.decision_id: r for r in resultado_reintento.resultados}
    assert por_id[id_bloqueada].aplicada is True
    # Las 2 ya aplicadas en el primer intento no se reintentan a ciegas --
    # ya no están vigentes en la bandeja (idempotencia a nivel de lote).
    assert por_id[decisiones[0]["decision_id"]].aplicada is False
    assert por_id[decisiones[2]["decision_id"]].aplicada is False

    obras = CatalogoObrasDestinos(
        ruta=catalogos / "obras_destinos.json", ruta_clientes=catalogos / "clientes.json",
        ruta_destinos=catalogos / "destinos_maestros.json",
    ).listar_obras()
    # Decisiones ya aplicadas no se duplican: exactamente 3 obras, una por
    # cada decisión real -- nunca 4, nunca 6.
    assert len(obras) == 3
    assert sorted(o.nombre_canonico for o in obras) == ["OBRA DOS", "OBRA TRES", "OBRA UNO"]


def test_lock_activo_real_nunca_se_ignora(tmp_path, monkeypatch):
    """Un lock RECIÉN adquirido (bien dentro de su ventana de vigencia)
    representa una operación real en curso -- `aplicar_decision_obra`
    debe respetarlo y nunca proceder como si no existiera."""
    raiz, catalogos, actual, cliente, decisiones = _tres_decisiones(tmp_path)
    ruta_lock = actual / ".atlas_lock_aplicar_decision_obra"
    ruta_lock.write_text(json.dumps({"pid": 999999, "host": "otro-pc", "adquirido_en": time.time()}), encoding="utf-8")

    with pytest.raises(SesionOcupadaError):
        aplicar_decision_obra(raiz_atlas=raiz, decision_id=decisiones[0]["decision_id"], accion="REGISTRAR")

    # El lock sigue ahí -- nunca se borró un lock activo real.
    assert ruta_lock.is_file()
    # Y la decisión sigue intacta -- nada se aplicó por encima del lock.
    obras = CatalogoObrasDestinos(
        ruta=catalogos / "obras_destinos.json", ruta_clientes=catalogos / "clientes.json",
        ruta_destinos=catalogos / "destinos_maestros.json",
    ).listar_obras()
    assert obras == []


def test_lock_huerfano_se_autorepara_sin_intervencion_manual(tmp_path):
    """Caso real 0000359449: un lock de un proceso que murió (Desktop
    cerrado a la fuerza, corte de energía) no debe exigir que alguien
    investigue PIDs y borre el archivo a mano -- pasada su ventana de
    vigencia (`TIEMPO_EXPIRACION_LOCK_APLICAR_DECISION_SEGUNDOS`), debe
    autorepararse solo en el siguiente intento."""
    raiz, catalogos, actual, cliente, decisiones = _tres_decisiones(tmp_path)
    ruta_lock = actual / ".atlas_lock_aplicar_decision_obra"
    edad_huerfana = TIEMPO_EXPIRACION_LOCK_APLICAR_DECISION_SEGUNDOS + 30
    ruta_lock.write_text(json.dumps({"pid": 999999, "host": "pc-muerto", "adquirido_en": time.time() - edad_huerfana}), encoding="utf-8")
    tiempo_viejo = time.time() - edad_huerfana
    os.utime(ruta_lock, (tiempo_viejo, tiempo_viejo))

    # Nunca debe lanzar SesionOcupadaError -- el lock huérfano se
    # reemplaza solo, sin ninguna intervención manual.
    resultado = aplicar_decision_obra(raiz_atlas=raiz, decision_id=decisiones[0]["decision_id"], accion="REGISTRAR")
    assert resultado["ok"] is True

    obras = CatalogoObrasDestinos(
        ruta=catalogos / "obras_destinos.json", ruta_clientes=catalogos / "clientes.json",
        ruta_destinos=catalogos / "destinos_maestros.json",
    ).listar_obras()
    assert len(obras) == 1
    assert obras[0].nombre_canonico == "OBRA UNO"


def test_cli_decision_individual_no_expone_traceback_ante_lock_ocupado(tmp_path, monkeypatch, capsys):
    """UX: `SesionOcupadaError` debe convertirse en un mensaje operacional
    comprensible por stdout (JSON válido), nunca un traceback Python por
    stderr sin ninguna línea de salida parseable para Desktop."""
    import aplicar_decision_pendiente as cli
    import sys

    def siempre_ocupado(**kwargs):
        raise SesionOcupadaError("simulado")

    monkeypatch.setattr(cli, "aplicar_decision_obra", siempre_ocupado)
    monkeypatch.setattr(sys, "argv", [
        "aplicar_decision_pendiente.py", "--raiz-atlas", str(tmp_path),
        "--decision-id", "cualquiera", "--accion", "REGISTRAR",
    ])

    cli.main()  # nunca debe lanzar -- debe imprimir JSON y retornar normalmente.

    salida = capsys.readouterr().out.strip()
    resultado = json.loads(salida)  # si esto lanza, el CLI no emitió JSON válido.
    assert resultado["ok"] is False
    assert "traceback" not in resultado["error"].lower()
    assert "intenta" in resultado["error"].lower() or "operación" in resultado["error"].lower()


def test_cli_lote_no_expone_traceback_ante_lock_ocupado(tmp_path, monkeypatch, capsys):
    """Mismo criterio UX que arriba, para el CLI de lote -- caso residual
    donde el lock ya estaba ocupado antes de procesar el primer ítem del
    lote (`aplicar_decisiones_multiples` ya maneja el caso POR ÍTEM
    dentro del lote, ver ese módulo)."""
    import aplicar_decisiones_multiples as cli
    import io
    import sys

    def siempre_ocupado(**kwargs):
        raise SesionOcupadaError("simulado")

    monkeypatch.setattr(cli, "aplicar_decisiones_multiples", siempre_ocupado)
    monkeypatch.setattr(sys, "argv", ["aplicar_decisiones_multiples.py", "--raiz-atlas", str(tmp_path)])
    monkeypatch.setattr(sys, "stdin", io.StringIO("[]"))

    cli.main()

    salida = capsys.readouterr().out.strip()
    resultado = json.loads(salida)
    assert resultado["total_aplicadas"] == 0
    assert "traceback" not in resultado["reconciliacion_motivo"].lower()
    assert "intenta" in resultado["reconciliacion_motivo"].lower() or "operación" in resultado["reconciliacion_motivo"].lower()
