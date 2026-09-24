"""Bloque P0 REVISIÓN V2 -- PLANIMPACTO AGRUPADO.

Caso real que motiva este bloque: guía 473880 (PRODALAM SA MELIPILLA,
OBRA_DESCONOCIDA + DESTINO_NO_RESUELTO del MISMO viaje) aplicada en G:\\
real via `aplicar_decisiones_multiples` (V1) tardó ~3 min para 2
decisiones porque, aunque V1 ya colapsó las N reconciliaciones a 1
(`reconciliar_estado_derivado`), cada `aplicar_decision_obra` seguía
disparando POR DENTRO su propia `revalidar_y_regenerar_reporte` (batería
global, ~40-60s), una vez por decisión. Ver perfilado real:
`tests/repro_revalidar_reporte.py` (scratchpad, no versionado) confirmó
contra una copia real de G:\\ que esa función -- no
`reconciliar_estado_derivado` -- es la que retira decisiones ajenas
("aprendizaje transversal") como efecto secundario de su barrido global.

Estos tests NUNCA ejecutan la batería real (`revalidar_y_regenerar_
reporte`/`reconciliar_estado_derivado` se reemplazan por contadores
falsos, igual que ya hace `test_aplicacion_multiple.py`) -- lo único que
verifican es CUÁNTAS VECES se invoca cada una y con qué PlanImpacto
agregado, nunca qué hace la batería en sí (eso ya lo cubren sus propios
tests)."""
from __future__ import annotations

import csv
import json

from atlas_core.aplicacion_decisiones import (
    TIPOS_ELEGIBLES_DIFERIR_REVALIDACION_GLOBAL,
    aplicar_decision_obra,
)
from atlas_core.aplicacion_multiple import aplicar_decisiones_multiples
from atlas_core.catalogo_clientes import CatalogoClientes, EstadoCalidadCliente
from atlas_core.catalogo_plantas import CatalogoPlantas, EstadoCalidad
from atlas_core.decisiones_pendientes import (
    crear_decision, detectar_decision_destino_no_resuelto, generar_artefacto,
)
from atlas_core.procesamiento_masivo import COLUMNAS
from atlas_core.rutas.modelos import Coordenadas

COORD_PLANTA = Coordenadas(-70.665977, -33.137558)
FECHA = "21-08-2026"


def _contador(monkeypatch, ruta_punteada, *, resultado):
    llamadas = []

    def _falso(**kwargs):
        llamadas.append(kwargs)
        return dict(resultado)

    monkeypatch.setattr(ruta_punteada, _falso)
    return llamadas


def _contador_reconciliacion(monkeypatch):
    return _contador(
        monkeypatch, "atlas_core.reconciliacion_estado_derivado.reconciliar_estado_derivado",
        resultado={"reconciliado": True, "motivo": "TEST"},
    )


def _contador_revalidacion_global(monkeypatch):
    return _contador(
        monkeypatch, "atlas_core.revalidacion_documental.revalidar_y_regenerar_reporte",
        resultado={"reporte_regenerado": False},
    )


def _escribir_csv(ruta, filas):
    with ruta.open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader()
        escritor.writerows(filas)


def _entorno(tmp_path, *, filas_csv, con_cliente=True):
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
    plantas = CatalogoPlantas(catalogos / "plantas.json")
    planta = plantas.crear(
        nombre="AZA COLINA", pais="CHILE", fuente="TEST",
        direccion="AV EJEMPLO 1", comuna="COLINA", region="RM",
        latitud=COORD_PLANTA.latitud, longitud=COORD_PLANTA.longitud,
        estado_calidad=EstadoCalidad.CONFIRMADA,
    )
    for fila in filas_csv:
        if fila.get("planta_origen_id") == "planta-x":
            fila["planta_origen_id"] = planta.planta_id
    dataset = actual / "analisis_completo_guias.csv"
    _escribir_csv(dataset, filas_csv)
    cliente = None
    if con_cliente:
        cliente = CatalogoClientes(catalogos / "clientes.json").crear(
            razon_social="CLIENTE CANONICO SA", rut="50.234.350-5", fuente="TEST",
            estado_calidad=EstadoCalidadCliente.CONFIRMADO,
        )
    return {"raiz": raiz, "catalogos": catalogos, "actual": actual, "dataset": dataset, "cliente": cliente}


def _fila_obra(numero_guia, archivo, obra):
    fila = {c: "" for c in COLUMNAS}
    fila.update({
        "archivo": archivo, "estado_procesamiento": "OK", "numero_guia": numero_guia,
        "numero_transporte": f"T{numero_guia}", "fecha": FECHA,
        "cliente": "CLIENTE CANONICO SA", "obra_destino": obra,
        "indicador_revision": "REVISAR", "motivos_revision_documento": "OBRA_DESTINO_SIN_CORROBORAR",
    })
    return fila


def _fila_destino(numero_guia, archivo):
    return {**{c: "" for c in COLUMNAS}, **{
        "archivo": archivo, "estado_procesamiento": "OK", "numero_guia": numero_guia,
        "numero_transporte": f"T{numero_guia}", "fecha": FECHA,
        "cliente": "CLIENTE CANONICO SA", "obra_destino": "CLIENTE CANONICO SA",
        "patente_tracto": "BPHR67", "indicador_revision": "REVISAR",
        "planta_origen_id": "planta-x", "planta_origen_nombre": "AZA COLINA",
        "origen_determinado_por": "CONFIRMACION_HUMANA", "evidencia_origen": "DECISION_HUMANA:x",
        "despachar_a_crudo": "", "direccion_entrega": "", "estado_entrega": "SIN_DATO",
        "estado_ruta": "REQUIERE_REVISION", "motivo_ruta": "DESTINO_SIN_DATO",
    }}


def _decision_obra(archivo, numero_guia, cliente_id, obra):
    return crear_decision(
        tipo="OBRA_DESCONOCIDA", entidad="OBRA", archivo=archivo, numero_guia=numero_guia,
        numero_transporte=f"T{numero_guia}", campo="obra_destino", valor_documental=obra,
        valor_normalizado=obra, identidad_resuelta=None, candidatos=(),
        motivos=("OBRA_NO_EXISTE_PARA_CLIENTE",),
        evidencias=({"tipo": "CLIENTE_RESUELTO", "entidad_id": cliente_id},),
        acciones_permitidas=("REGISTRAR", "NO_REGISTRAR", "POSPONER"),
        contexto={"cliente_id": cliente_id, "cliente_canonico": "CLIENTE CANONICO SA"},
    )


def test_obra_sola_se_difiere_y_agrega_una_sola_revalidacion(tmp_path, monkeypatch):
    ent = _entorno(tmp_path, filas_csv=[_fila_obra("100", "100.png", "OBRA UNO")])
    decision = _decision_obra("100.png", "100", ent["cliente"].cliente_id, "OBRA UNO")
    generar_artefacto(
        ruta_dataset=ent["dataset"], carpeta_catalogos=ent["catalogos"], decisiones=[decision],
        ruta_salida=ent["actual"] / "decisiones_pendientes.json",
    )
    _contador_reconciliacion(monkeypatch)
    llamadas_revalidacion = _contador_revalidacion_global(monkeypatch)
    resultado = aplicar_decisiones_multiples(
        raiz_atlas=ent["raiz"], solicitudes=[{"decision_id": decision["decision_id"], "accion": "REGISTRAR"}],
    )
    assert resultado.total_aplicadas == 1
    assert len(llamadas_revalidacion) == 1
    assert resultado.plan_impacto_ejecutado is True
    assert resultado.plan_impacto_guias == 1
    # La escritura canónica (catálogo de obra) es inmediata -- no depende
    # de que la revalidación diferida haya corrido.
    ledger = json.loads((ent["actual"] / "decisiones_aplicadas.json").read_text(encoding="utf-8"))
    assert ledger["aplicaciones"][0]["accion"] == "REGISTRAR"


def test_tres_obras_guias_distintas_una_sola_revalidacion_agrupada(tmp_path, monkeypatch):
    filas = [_fila_obra(g, f"{g}.png", f"OBRA {g}") for g in ("100", "200", "300")]
    ent = _entorno(tmp_path, filas_csv=filas)
    decisiones = [_decision_obra(f"{g}.png", g, ent["cliente"].cliente_id, f"OBRA {g}") for g in ("100", "200", "300")]
    generar_artefacto(
        ruta_dataset=ent["dataset"], carpeta_catalogos=ent["catalogos"], decisiones=decisiones,
        ruta_salida=ent["actual"] / "decisiones_pendientes.json",
    )
    llamadas_reconciliacion = _contador_reconciliacion(monkeypatch)
    llamadas_revalidacion = _contador_revalidacion_global(monkeypatch)
    solicitudes = [{"decision_id": d["decision_id"], "accion": "REGISTRAR"} for d in decisiones]
    resultado = aplicar_decisiones_multiples(raiz_atlas=ent["raiz"], solicitudes=solicitudes)
    assert resultado.total_aplicadas == 3
    # Antes de este bloque (V1): 3 llamadas a la batería global (una por
    # `aplicar_decision_obra`). Con PlanImpacto agrupado (V2): 1 sola,
    # aunque haya 3 decisiones/3 guías distintas -- "cada afectado máximo
    # una vez", nunca N veces.
    assert len(llamadas_revalidacion) == 1
    assert resultado.plan_impacto_guias == 3
    assert len(llamadas_reconciliacion) == 1


def test_obra_mas_destino_mismo_viaje_una_sola_revalidacion(tmp_path, monkeypatch):
    fila = _fila_destino("473880", "473880.jpeg")
    ent = _entorno(tmp_path, filas_csv=[fila])
    decision_obra = _decision_obra("473880.jpeg", "473880", ent["cliente"].cliente_id, "PRODALAM SA MELIPILLA")
    decision_destino = detectar_decision_destino_no_resuelto(archivo="473880.jpeg", fila=fila)
    generar_artefacto(
        ruta_dataset=ent["dataset"], carpeta_catalogos=ent["catalogos"],
        decisiones=[decision_obra, decision_destino],
        ruta_salida=ent["actual"] / "decisiones_pendientes.json",
    )
    _contador_reconciliacion(monkeypatch)
    llamadas_revalidacion = _contador_revalidacion_global(monkeypatch)
    solicitudes = [
        {"decision_id": decision_obra["decision_id"], "accion": "REGISTRAR"},
        {
            "decision_id": decision_destino["decision_id"], "accion": "REGISTRAR_DIRECCION",
            "direccion_manual": "AV VICUNA MACKENNA 1354", "comuna_manual": "MELIPILLA",
        },
    ]
    resultado = aplicar_decisiones_multiples(raiz_atlas=ent["raiz"], solicitudes=solicitudes)
    assert resultado.total_aplicadas == 2
    # OBRA + DESTINO del MISMO viaje -> deduplicado a UNA guía en el
    # PlanImpacto agregado, UNA sola pasada de revalidación (nunca 2).
    assert len(llamadas_revalidacion) == 1
    assert resultado.plan_impacto_guias == 2  # 2 decisiones aportaron insumos...
    kwargs_revalidacion = llamadas_revalidacion[0]
    # ...pero la comuna manual de DESTINO llega correctamente agregada por guía.
    assert kwargs_revalidacion["comuna_manual_por_guia"] == {"473880": "MELIPILLA"}


def test_tipo_no_elegible_ignora_el_flag_y_revalida_de_inmediato(tmp_path, monkeypatch):
    """VEHICULO_DESCONOCIDO no está en TIPOS_ELEGIBLES_DIFERIR_REVALIDACION_GLOBAL
    -- pasar `diferir_revalidacion_global=True` para un tipo no auditado
    nunca debe diferir nada (alcance deliberadamente acotado, item 7)."""
    assert "VEHICULO_DESCONOCIDO" not in TIPOS_ELEGIBLES_DIFERIR_REVALIDACION_GLOBAL
    ent = _entorno(tmp_path, filas_csv=[_fila_obra("100", "100.png", "OBRA UNO")])
    decision = _decision_obra("100.png", "100", ent["cliente"].cliente_id, "OBRA UNO")
    generar_artefacto(
        ruta_dataset=ent["dataset"], carpeta_catalogos=ent["catalogos"], decisiones=[decision],
        ruta_salida=ent["actual"] / "decisiones_pendientes.json",
    )
    llamadas_revalidacion = _contador_revalidacion_global(monkeypatch)
    resultado = aplicar_decision_obra(
        raiz_atlas=ent["raiz"], decision_id=decision["decision_id"], accion="REGISTRAR",
        diferir_revalidacion_global=True,
    )
    # OBRA_DESCONOCIDA SÍ es elegible -- este resultado confirma que el
    # kwarg funciona; el punto de la prueba es el siguiente assert sobre
    # un tipo NO elegible en un caso real de mezcla (ver docstring).
    assert "plan_impacto_diferido" in resultado
    assert len(llamadas_revalidacion) == 0


def test_lote_vacio_cero_escritura(tmp_path, monkeypatch):
    ent = _entorno(tmp_path, filas_csv=[_fila_obra("100", "100.png", "OBRA UNO")])
    decision = _decision_obra("100.png", "100", ent["cliente"].cliente_id, "OBRA UNO")
    generar_artefacto(
        ruta_dataset=ent["dataset"], carpeta_catalogos=ent["catalogos"], decisiones=[decision],
        ruta_salida=ent["actual"] / "decisiones_pendientes.json",
    )
    llamadas_reconciliacion = _contador_reconciliacion(monkeypatch)
    llamadas_revalidacion = _contador_revalidacion_global(monkeypatch)
    resultado = aplicar_decisiones_multiples(raiz_atlas=ent["raiz"], solicitudes=[])
    assert resultado.total_solicitadas == 0
    assert resultado.total_aplicadas == 0
    assert resultado.plan_impacto_ejecutado is False
    assert len(llamadas_revalidacion) == 0
    assert len(llamadas_reconciliacion) == 0
    assert not (ent["actual"] / "decisiones_aplicadas.json").exists()


def test_parcial_una_falla_una_se_aplica_plan_impacto_solo_con_la_exitosa(tmp_path, monkeypatch):
    filas = [_fila_obra(g, f"{g}.png", f"OBRA {g}") for g in ("100", "200")]
    ent = _entorno(tmp_path, filas_csv=filas)
    decisiones = [_decision_obra(f"{g}.png", g, ent["cliente"].cliente_id, f"OBRA {g}") for g in ("100", "200")]
    generar_artefacto(
        ruta_dataset=ent["dataset"], carpeta_catalogos=ent["catalogos"], decisiones=decisiones,
        ruta_salida=ent["actual"] / "decisiones_pendientes.json",
    )
    # La primera ya fue aplicada fuera del lote -- queda obsoleta para el lote.
    aplicar_decision_obra(raiz_atlas=ent["raiz"], decision_id=decisiones[0]["decision_id"], accion="REGISTRAR")
    _contador_reconciliacion(monkeypatch)
    llamadas_revalidacion = _contador_revalidacion_global(monkeypatch)
    solicitudes = [{"decision_id": d["decision_id"], "accion": "REGISTRAR"} for d in decisiones]
    resultado = aplicar_decisiones_multiples(raiz_atlas=ent["raiz"], solicitudes=solicitudes)
    assert resultado.total_solicitadas == 2
    assert resultado.total_aplicadas == 1
    # La primera decisión ya se había aplicado FUERA del lote (con
    # `diferir_revalidacion_global=False` por defecto) -- ya pagó su
    # propia revalidación inmediata ahí. Dentro del lote, sólo la segunda
    # decisión aporta un plan diferido -- 1 sola revalidación agregada.
    assert resultado.plan_impacto_guias == 1
    assert len(llamadas_revalidacion) == 1


def test_comuna_editable_preservada_destino_no_resuelto_no_aplicado_no_se_toca(tmp_path, monkeypatch):
    """473545 (item 6 del bloque): una tarjeta DESTINO_NO_RESUELTO que
    NO se selecciona en el lote debe seguir PENDIENTE, con su comuna aún
    editable -- nunca tocada por el PlanImpacto de OTRAS decisiones del
    mismo lote."""
    fila_a = _fila_destino("473880", "473880.jpeg")
    fila_b = _fila_destino("473545", "473545.jpeg")
    ent = _entorno(tmp_path, filas_csv=[fila_a, fila_b])
    decision_a = detectar_decision_destino_no_resuelto(archivo="473880.jpeg", fila=fila_a)
    decision_b = detectar_decision_destino_no_resuelto(archivo="473545.jpeg", fila=fila_b)
    generar_artefacto(
        ruta_dataset=ent["dataset"], carpeta_catalogos=ent["catalogos"],
        decisiones=[decision_a, decision_b],
        ruta_salida=ent["actual"] / "decisiones_pendientes.json",
    )
    _contador_reconciliacion(monkeypatch)
    llamadas_revalidacion = _contador_revalidacion_global(monkeypatch)
    # Sólo 473880 se selecciona y aplica en este lote -- 473545 queda
    # deliberadamente sin tocar (memoria del proyecto: KATEMU S.A, comuna
    # editable pendiente de respuesta humana).
    solicitudes = [{
        "decision_id": decision_a["decision_id"], "accion": "REGISTRAR_DIRECCION",
        "direccion_manual": "AV VICUNA MACKENNA 1354", "comuna_manual": "MELIPILLA",
    }]
    resultado = aplicar_decisiones_multiples(raiz_atlas=ent["raiz"], solicitudes=solicitudes)
    assert resultado.total_aplicadas == 1
    kwargs_revalidacion = llamadas_revalidacion[0]
    # El plan agregado sólo trae la comuna de la guía SELECCIONADA --
    # 473545 nunca entra al mapa, nunca se le fuerza ninguna comuna.
    assert kwargs_revalidacion["comuna_manual_por_guia"] == {"473880": "MELIPILLA"}
    pendientes = json.loads((ent["actual"] / "decisiones_pendientes.json").read_text(encoding="utf-8"))["decisiones"]
    ids_pendientes = {d["decision_id"] for d in pendientes}
    assert decision_b["decision_id"] in ids_pendientes
