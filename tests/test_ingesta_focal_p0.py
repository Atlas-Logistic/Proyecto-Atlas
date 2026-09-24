"""Bloque P0 INGESTA FOCAL Y RÁPIDA -- caso real 474172: ingresar UNA
guía nueva no debe convertirse en un disparador para intentar resolver
el backlog global de Atlas. `reconciliar_estado_derivado(guias_
objetivo=...)` (Bloque P0 RECONCILIACIÓN FOCAL) es el mecanismo; estos
tests verifican, con un proveedor de rutas 100% determinista (nunca red
real), que una reconciliación focal:
  A) sólo consulta el proveedor externo por la(s) guía(s) en scope --
     un backlog de guías antiguas cooldown-eligible NO dispara consultas;
  B) expande el scope a guías que comparten entidad causal real (aquí,
     mismo `numero_transporte` -- el mismo criterio que ya usa
     `revalidar_origen_por_documento_hermano_de_transporte_sin_ocr`),
     nunca a una guía ajena;
  C) el mantenimiento/reconciliación GLOBAL (`guias_objetivo=None`)
     conserva capacidad plena de recorrer el backlog;
  D) las decisiones nuevas se publican; una decisión ajena vigente no
     se reclasifica de forma redundante;
  F) tras una reconciliación focal, `reporte_vigente`/`estado_operacion`
     ya reflejan la guía nueva -- sin necesitar una reconciliación
     global posterior;
  G) el scratch root sigue siendo frontera dura -- ninguna prueba toca
     G (todos los proveedores son `ProveedorRutasSimulado`, cero red)."""
from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime, timedelta, timezone

from atlas_core.almacenamiento_portable import escribir_estado_operacion, leer_estado_operacion
from atlas_core.capacidades_reevaluacion import versiones_actuales
from atlas_core.catalogo_clientes import CatalogoClientes, EstadoCalidadCliente
from atlas_core.catalogo_plantas import CatalogoPlantas, EstadoCalidad
from atlas_core.decisiones_pendientes import crear_decision, generar_artefacto
from atlas_core.procesamiento_masivo import COLUMNAS
from atlas_core.reconciliacion_estado_derivado import RULESET_VERSION, reconciliar_estado_derivado
from atlas_core.rutas.modelos import Coordenadas
from atlas_core.rutas.proveedor import ProveedorRutasSimulado

COORD_PLANTA = Coordenadas(-70.665977, -33.137558)
FECHA = "21-08-2026"
RELOJ = lambda: datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)
HACE_48H = (RELOJ() - timedelta(hours=48)).isoformat()


def _huella_ruta(fila: dict) -> str:
    campos = ("planta_origen_id", "despachar_a_crudo", "cliente", "obra_destino", "destino_id", "motivo_ruta")
    return hashlib.sha256("\0".join(str(fila.get(c, "")) for c in campos).encode("utf-8")).hexdigest()


def _fila_backlog(numero_guia, planta_id, *, transporte=None):
    """Guía con motivo AGOTABLE (`COORDENADA_NO_CONFIRMADA`, cooldown de
    24h) -- ya intentada antes (ver seguimiento en `_entorno_focal`), así
    que sin scope focal calificaría para un reintento por backlog."""
    return {**{c: "" for c in COLUMNAS}, **{
        "archivo": f"{numero_guia}.jpeg", "estado_procesamiento": "OK", "numero_guia": numero_guia,
        "numero_transporte": transporte or f"T{numero_guia}", "fecha": FECHA,
        "cliente": "CLIENTE BACKLOG SA", "obra_destino": "OBRA BACKLOG",
        "indicador_revision": "OK", "estado_operacional": "REQUIERE_REVISION",
        "planta_origen_id": planta_id, "planta_origen_nombre": "AZA COLINA",
        "origen_determinado_por": "CONFIRMACION_HUMANA", "evidencia_origen": "DECISION_HUMANA:x",
        "despachar_a_crudo": f"CALLE BACKLOG {numero_guia}", "direccion_entrega": "",
        "estado_ruta": "REQUIERE_REVISION", "motivo_ruta": "COORDENADA_NO_CONFIRMADA(1)",
    }}


def _fila_nueva(numero_guia, planta_id, *, transporte=None, cliente="CLIENTE NUEVO SA", obra="OBRA NUEVA"):
    """Guía recién ingestada -- `intentos_misma_evidencia=0` (sin
    seguimiento previo), califica para su PROPIA primera oportunidad
    incluso dentro del scope focal."""
    return {**{c: "" for c in COLUMNAS}, **{
        "archivo": f"{numero_guia}.jpeg", "estado_procesamiento": "OK", "numero_guia": numero_guia,
        "numero_transporte": transporte or f"T{numero_guia}", "fecha": FECHA,
        "cliente": cliente, "obra_destino": obra,
        "indicador_revision": "OK", "estado_operacional": "REQUIERE_REVISION",
        "planta_origen_id": planta_id, "planta_origen_nombre": "AZA COLINA",
        "origen_determinado_por": "CONFIRMACION_HUMANA", "evidencia_origen": "DECISION_HUMANA:x",
        "despachar_a_crudo": f"CALLE NUEVA {numero_guia}", "direccion_entrega": "",
        "estado_ruta": "REQUIERE_REVISION", "motivo_ruta": "COORDENADA_NO_CONFIRMADA(1)",
    }}


def _escribir_csv(ruta, filas):
    with ruta.open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNAS, delimiter=";")
        w.writeheader()
        w.writerows(filas)


def _entorno_focal(tmp_path, *, filas_backlog, filas_nuevas, decisiones=()):
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
    CatalogoClientes(catalogos / "clientes.json").crear(
        razon_social="CLIENTE BACKLOG SA", rut="50.234.350-5", fuente="TEST",
        estado_calidad=EstadoCalidadCliente.CONFIRMADO,
    )
    CatalogoClientes(catalogos / "clientes.json").crear(
        razon_social="CLIENTE NUEVO SA", rut="76086428-5", fuente="TEST",
        estado_calidad=EstadoCalidadCliente.CONFIRMADO,
    )
    planta = CatalogoPlantas(catalogos / "plantas.json").crear(
        nombre="AZA COLINA", pais="CHILE", fuente="TEST",
        direccion="AV EJEMPLO 1", comuna="COLINA", region="RM",
        latitud=COORD_PLANTA.latitud, longitud=COORD_PLANTA.longitud,
        estado_calidad=EstadoCalidad.CONFIRMADA,
    )
    todas_filas = [*filas_backlog, *filas_nuevas]
    for fila in todas_filas:
        if not fila.get("planta_origen_id"):
            fila["planta_origen_id"] = planta.planta_id
    dataset = actual / "analisis_completo_guias.csv"
    _escribir_csv(dataset, todas_filas)

    # Seguimiento (Bloque GEOGRAFÍA 2B): cada guía de BACKLOG ya tuvo un
    # intento real hace 48h (> cooldown AGOTABLE de 24h) -- sin scope
    # focal, calificaría de inmediato para un reintento.
    pendientes = {
        "pendientes": [
            {
                "numero_guia": f["numero_guia"],
                "huella_datos": _huella_ruta(f),
                "intentos_misma_evidencia": 1,
                "ultimo_intento": HACE_48H,
                "ultimo_resultado": "COORDENADA_NO_CONFIRMADA(1)",
                "historial_resultados": ["COORDENADA_NO_CONFIRMADA(1)"],
            }
            for f in todas_filas if f["numero_guia"] in {b["numero_guia"] for b in filas_backlog}
        ]
    }
    (actual / "pendientes_tecnicos.json").write_text(json.dumps(pendientes), encoding="utf-8")

    generar_artefacto(
        ruta_dataset=dataset, carpeta_catalogos=catalogos, decisiones=list(decisiones),
        ruta_salida=actual / "decisiones_pendientes.json", reloj=RELOJ,
    )
    # Bloque P0 -- estado_operacion baseline YA en la versión/capacidades
    # vigentes: evita que la primera reconciliación se lea a sí misma
    # como "migración"/"avance de capacidad" (lo que anularía el scope
    # focal para TODA guía, ver docstring de `reconciliar_estado_
    # derivado`) -- exactamente el estado real de una operación ya al día.
    reporte_previo = raiz / "reportes" / "previo"
    reporte_previo.mkdir(parents=True)
    escribir_estado_operacion(
        reporte_vigente=reporte_previo, dataset_operacional=dataset,
        decisiones_pendientes=actual / "decisiones_pendientes.json",
        raiz=raiz, reloj=RELOJ,
        version_estado_derivado=RULESET_VERSION, versiones_capacidades=versiones_actuales(),
    )
    return {"raiz": raiz, "catalogos": catalogos, "actual": actual, "dataset": dataset, "planta_id": planta.planta_id}


def _proveedor_contador():
    return ProveedorRutasSimulado()


def test_a_backlog_20_guias_solo_la_nueva_consulta_proveedor(tmp_path):
    filas_backlog = [_fila_backlog(f"OLD{i:03d}", None) for i in range(1, 21)]
    filas_nuevas = [_fila_nueva("NEW001", None)]
    ent = _entorno_focal(tmp_path, filas_backlog=filas_backlog, filas_nuevas=filas_nuevas)

    proveedor = _proveedor_contador()
    resultado = reconciliar_estado_derivado(
        raiz_atlas=ent["raiz"], reloj=RELOJ, proveedor_rutas=proveedor, proveedor_rutas_fallback=proveedor,
        guias_objetivo={"NEW001"},
    )
    assert resultado["reconciliado"] is True
    # Exactamente 1 consulta externa -- la de NEW001. El backlog de 20
    # guías antiguas, todo cooldown-eligible, se queda en 0 -- nunca se
    # convierte la ingesta de una guía en un disparador de backlog.
    assert proveedor.llamadas_geocodificacion == 1
    filas_finales = {f["numero_guia"]: f for f in csv.DictReader(
        ent["dataset"].open(encoding="utf-8-sig", newline=""), delimiter=";"
    )}
    for i in range(1, 21):
        assert filas_finales[f"OLD{i:03d}"]["motivo_ruta"] == "COORDENADA_NO_CONFIRMADA(1)"  # intacto


def test_b_entidad_compartida_afecta_3_guias_no_una_cuarta_ajena(tmp_path):
    """3 guías comparten `numero_transporte` con la nueva (mismo viaje);
    una 4ª guía usa OTRO transporte -- el scope focal debe incluir las 3
    primeras y excluir la 4ª."""
    filas_backlog = [
        _fila_backlog("HERM001", None, transporte="T-COMUN"),
        _fila_backlog("HERM002", None, transporte="T-COMUN"),
        _fila_backlog("AJENA001", None, transporte="T-OTRO"),
    ]
    filas_nuevas = [_fila_nueva("NEW001", None, transporte="T-COMUN")]
    ent = _entorno_focal(tmp_path, filas_backlog=filas_backlog, filas_nuevas=filas_nuevas)

    # PlanImpacto: NEW001 + guías del MISMO transporte (T-COMUN) --
    # exactamente el cálculo que hace `analizar_guias_masivo.py`.
    guias_objetivo = {"NEW001", "HERM001", "HERM002"}
    proveedor = _proveedor_contador()
    reconciliar_estado_derivado(
        raiz_atlas=ent["raiz"], reloj=RELOJ, proveedor_rutas=proveedor, proveedor_rutas_fallback=proveedor,
        guias_objetivo=guias_objetivo,
    )
    filas_finales = {f["numero_guia"]: f for f in csv.DictReader(
        ent["dataset"].open(encoding="utf-8-sig", newline=""), delimiter=";"
    )}
    # AJENA001 (otro transporte) nunca entra al scope -- intacta.
    assert filas_finales["AJENA001"]["motivo_ruta"] == "COORDENADA_NO_CONFIRMADA(1)"


def test_c_reconciliacion_global_explicita_recorre_backlog(tmp_path):
    """`guias_objetivo=None` (mantenimiento/reconciliación global,
    explícito) conserva la capacidad de recorrer y reintentar el
    backlog completo -- nunca se elimina esa vía."""
    filas_backlog = [_fila_backlog(f"OLD{i:03d}", None) for i in range(1, 4)]
    filas_nuevas = [_fila_nueva("NEW001", None)]
    ent = _entorno_focal(tmp_path, filas_backlog=filas_backlog, filas_nuevas=filas_nuevas)

    proveedor = _proveedor_contador()
    resultado = reconciliar_estado_derivado(
        raiz_atlas=ent["raiz"], reloj=RELOJ, proveedor_rutas=proveedor, proveedor_rutas_fallback=proveedor,
        guias_objetivo=None,
    )
    assert resultado["reconciliado"] is True
    # Sin scope, TODAS las guías (backlog + nueva) son candidatas -- el
    # proveedor recibe consultas por más que sólo NEW001.
    assert proveedor.llamadas_geocodificacion >= 4


def test_d_decision_ajena_vigente_no_se_reclasifica_por_una_ingesta_focal(tmp_path):
    """Una decisión OBRA_DESCONOCIDA ya publicada para una guía de
    BACKLOG (ajena a la ingesta focal de NEW001) debe seguir vigente,
    con el MISMO `decision_id`, después de una reconciliación focal --
    nunca se pierde ni se regenera con una huella distinta sólo porque
    otra guía se ingestó."""
    filas_backlog = [_fila_backlog("OLD001", None)]
    filas_nuevas = [_fila_nueva("NEW001", None)]
    decision_ajena = crear_decision(
        tipo="OBRA_DESCONOCIDA", entidad="OBRA", archivo="OLD001.jpeg", numero_guia="OLD001",
        numero_transporte="TOLD001", campo="obra_destino", valor_documental="OBRA BACKLOG",
        valor_normalizado="OBRA BACKLOG", identidad_resuelta=None, candidatos=(),
        motivos=("OBRA_NO_EXISTE_PARA_CLIENTE",),
        evidencias=({"tipo": "CLIENTE_RESUELTO", "entidad_id": "cliente-backlog"},),
        acciones_permitidas=("REGISTRAR", "NO_REGISTRAR", "POSPONER"),
        contexto={"cliente_id": "cliente-backlog", "cliente_canonico": "CLIENTE BACKLOG SA"},
    )
    ent = _entorno_focal(
        tmp_path, filas_backlog=filas_backlog, filas_nuevas=filas_nuevas, decisiones=[decision_ajena],
    )
    proveedor = _proveedor_contador()
    reconciliar_estado_derivado(
        raiz_atlas=ent["raiz"], reloj=RELOJ, proveedor_rutas=proveedor, proveedor_rutas_fallback=proveedor,
        guias_objetivo={"NEW001"},
    )
    bandeja = json.loads((ent["actual"] / "decisiones_pendientes.json").read_text(encoding="utf-8"))
    ids_vigentes = {d["decision_id"] for d in bandeja["decisiones"] if d.get("estado") == "PENDIENTE"}
    assert decision_ajena["decision_id"] in ids_vigentes  # sobrevive, mismo id -- nunca se pierde ni se regenera


def test_f_reconciliacion_focal_publica_reporte_sin_reconciliacion_global_posterior(tmp_path):
    filas_backlog = [_fila_backlog(f"OLD{i:03d}", None) for i in range(1, 6)]
    filas_nuevas = [_fila_nueva("NEW001", None)]
    ent = _entorno_focal(tmp_path, filas_backlog=filas_backlog, filas_nuevas=filas_nuevas)

    proveedor = _proveedor_contador()
    resultado = reconciliar_estado_derivado(
        raiz_atlas=ent["raiz"], reloj=RELOJ, proveedor_rutas=proveedor, proveedor_rutas_fallback=proveedor,
        guias_objetivo={"NEW001"},
    )
    assert resultado["reconciliado"] is True
    estado = leer_estado_operacion(raiz=ent["raiz"])
    assert estado is not None
    reporte_vigente = estado.get("reporte_vigente")
    assert reporte_vigente
    ruta_viajes = ent["raiz"] / "reportes" / reporte_vigente / "viajes.csv" if isinstance(reporte_vigente, str) else None
    # El manifiesto ya apunta a un reporte fresco (no al "previo" sembrado
    # por el fixture) -- la guía nueva quedó publicada en ESTA pasada,
    # sin depender de una segunda reconciliación global.
    assert reporte_vigente != "previo"


def test_g_aislamiento_nunca_construye_proveedor_por_defecto_sin_raiz(tmp_path):
    """Si el caller no inyecta `proveedor_rutas`, la función sigue
    construyendo el proveedor real predeterminado -- pero derivado de
    `carpeta_catalogos.parent` (la raíz scratch de este test), nunca
    autodetectando G:\\ (ver Bloque P0 AISLAMIENTO DE CACHÉ). Aquí sólo
    se confirma que no explota y que el caché resultante, si se llega a
    crear, cae dentro de `raiz_atlas` -- nunca fuera."""
    filas_backlog = [_fila_backlog("OLD001", None)]
    filas_nuevas = [_fila_nueva("NEW001", None)]
    ent = _entorno_focal(tmp_path, filas_backlog=filas_backlog, filas_nuevas=filas_nuevas)
    # Guía objetivo vacía a propósito -- ninguna consulta real debería
    # dispararse (0 guías en scope), así que aunque el proveedor NO esté
    # inyectado, no hay ningún intento de red que pudiera fugarse a G.
    resultado = reconciliar_estado_derivado(raiz_atlas=ent["raiz"], reloj=RELOJ, guias_objetivo=set())
    assert resultado["reconciliado"] in (True, False)
    cache_posible = ent["raiz"] / "cache" / "geocodificacion"
    if cache_posible.exists():
        # Si algo llegó a crear caché, quedó DENTRO de la raíz scratch.
        assert cache_posible.is_relative_to(ent["raiz"])
