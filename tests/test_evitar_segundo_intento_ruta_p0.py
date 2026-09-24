"""Bloque P0 EVITAR SEGUNDO INTENTO DE RUTA -- caso real 473545 (KATEMU
S.A, CRUCERO PERALILLO/LAMPA): el perfilado midió que la MISMA guía
dispara una consulta externa de geocodificación/ruta dos veces dentro de
una sola operación -- una vez inline dentro de `aplicar_decision_obra`
(feedback inmediato, `resultado["ruta_resuelta"]`), otra vez dentro de
la batería diferida (`revalidar_y_regenerar_reporte`) del mismo lote.

`revalidar_ruta_sin_destino_calculado_sin_ocr` ahora expone
`guias_intentadas` (cualquier guía para la que SE LLEGÓ a invocar
`calcular_ruta_con_planta_conocida`, incluso si terminó en
RESULTADO_AMBIGUO/excepción -- la consulta externa ya se pagó) y
`aplicar_decision_obra` usa esa señal EXPLÍCITA -- no una inferencia
indirecta de `planta_origen_id` -- para que el PlanImpacto agregado le
diga a la batería diferida qué guías NO debe reintentar en ESA MISMA
operación. Nunca un cooldown persistente: el set se construye desde
cero en cada llamada a `aplicar_decisiones_multiples`/`aplicar_decision_
obra`, nunca se persiste a disco.

Todos los proveedores son `ProveedorRutasSimulado` (deterministas, sin
red) -- nunca se ejercita OpenRouteService/Nominatim reales aquí."""
from __future__ import annotations

import csv
import json

from atlas_core.aplicacion_decisiones import aplicar_decision_obra
from atlas_core.aplicacion_multiple import aplicar_decisiones_multiples
from atlas_core.catalogo_clientes import CatalogoClientes, EstadoCalidadCliente
from atlas_core.catalogo_plantas import CatalogoPlantas, EstadoCalidad
from atlas_core.decisiones_pendientes import detectar_decision_destino_no_resuelto, generar_artefacto
from atlas_core.procesamiento_masivo import COLUMNAS
from atlas_core.revalidacion_documental import revalidar_y_regenerar_reporte
from atlas_core.rutas.modelos import (
    CandidatoGeocodificacion, Coordenadas, EstadoRuta, ResultadoGeocodificacion, ResultadoRuta,
)
from atlas_core.rutas.proveedor import ProveedorRutasSimulado

COORD_PLANTA = Coordenadas(-70.665977, -33.137558)
FECHA = "21-08-2026"


def _proveedor_ambiguo(direccion: str) -> ProveedorRutasSimulado:
    """Mismo patrón que `_proveedor_direccion_ambigua` de
    `test_destino_no_resuelto_r6.py` -- RESULTADO_AMBIGUO determinista,
    nunca RUTA_CALCULADA (equivalente sintético de CRUCERO PERALILLO)."""
    consulta = f"{direccion}, Chile"
    return ProveedorRutasSimulado(
        geocodificaciones={
            consulta: ResultadoGeocodificacion(
                EstadoRuta.RESULTADO_AMBIGUO,
                (
                    CandidatoGeocodificacion(Coordenadas(-70.6, -33.4), "A", 0.5, "Lampa", "Metropolitana"),
                    CandidatoGeocodificacion(Coordenadas(-70.5, -33.3), "B", 0.5, "Pudahuel", "Metropolitana"),
                ),
                "MULTIPLES_CANDIDATOS",
            )
        },
        resultado_ruta=ResultadoRuta(EstadoRuta.RUTA_CALCULADA, 1.0, 1.0, "SINTETICO"),
    )


def _escribir_csv(ruta, filas):
    with ruta.open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader()
        escritor.writerows(filas)


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
    cliente = CatalogoClientes(catalogos / "clientes.json").crear(
        razon_social="KATEMU S.A.", rut="50.234.350-5", fuente="TEST",
        estado_calidad=EstadoCalidadCliente.CONFIRMADO,
    )
    return {"raiz": raiz, "catalogos": catalogos, "actual": actual, "dataset": dataset, "cliente": cliente}


def _fila_destino(numero_guia, archivo, *, con_origen=True):
    """DESTINO_NO_RESUELTO con origen YA resuelto (`planta_origen_id`
    poblado) -- el caso real 473545: sólo falta la dirección de
    entrega, exactamente el escenario donde el intento inline SÍ paga
    una consulta externa real (si el origen siguiera vacío, la propia
    `revalidar_ruta_sin_destino_calculado_sin_ocr` se abstiene sola --
    ver sus guards -- y no hay nada que deduplicar)."""
    fila = {c: "" for c in COLUMNAS}
    fila.update({
        "archivo": archivo, "estado_procesamiento": "OK", "numero_guia": numero_guia,
        "numero_transporte": f"T{numero_guia}", "fecha": FECHA,
        "cliente": "KATEMU S.A.", "obra_destino": "KATEMU S.A.",
        "patente_tracto": "BPHR67", "indicador_revision": "REVISAR",
        "planta_origen_id": ("planta-x" if con_origen else ""),
        "planta_origen_nombre": ("AZA COLINA" if con_origen else ""),
        "origen_determinado_por": ("CONFIRMACION_HUMANA" if con_origen else ""),
        "evidencia_origen": ("DECISION_HUMANA:x" if con_origen else ""),
        "despachar_a_crudo": "", "direccion_entrega": "", "estado_entrega": "SIN_DATO",
        "estado_ruta": "REQUIERE_REVISION", "motivo_ruta": "DESTINO_SIN_DATO",
    })
    return fila


def _publicar_decision(ent, decision):
    generar_artefacto(
        ruta_dataset=ent["dataset"], carpeta_catalogos=ent["catalogos"], decisiones=[decision],
        ruta_salida=ent["actual"] / "decisiones_pendientes.json",
    )


def test_a_intento_inline_mas_bateria_diferida_es_un_solo_intento_externo(tmp_path):
    fila = _fila_destino("473545", "473545.jpeg")
    ent = _entorno(tmp_path, filas_csv=[fila])
    decision = detectar_decision_destino_no_resuelto(archivo="473545.jpeg", fila=fila)
    _publicar_decision(ent, decision)

    proveedor = _proveedor_ambiguo("CRUCERO PERALILLO")
    resultado = aplicar_decisiones_multiples(
        raiz_atlas=ent["raiz"],
        solicitudes=[{
            "decision_id": decision["decision_id"], "accion": "REGISTRAR_DIRECCION",
            "direccion_manual": "CRUCERO PERALILLO", "comuna_manual": "LAMPA",
        }],
        proveedor_rutas=proveedor, proveedor_rutas_fallback=proveedor,
    )
    assert resultado.total_aplicadas == 1
    assert resultado.plan_impacto_ejecutado is True
    # Un solo intento externo total para 473545 -- el inline pagó la
    # consulta, la batería diferida la excluyó (nunca la repitió).
    assert proveedor.llamadas_geocodificacion == 1


def test_b_varias_decisiones_de_la_misma_guia_siguen_siendo_un_intento(tmp_path):
    """Aunque el PlanImpacto agregue insumos de MÁS de una decisión para
    la MISMA guía (p. ej. obra+destino del mismo viaje, como 473880),
    la exclusión es un `set` -- agregar la misma guía dos veces no
    dispara un segundo intento ni rompe nada."""
    fila = _fila_destino("473880", "473880.jpeg")
    ent = _entorno(tmp_path, filas_csv=[fila])
    decision = detectar_decision_destino_no_resuelto(archivo="473880.jpeg", fila=fila)
    _publicar_decision(ent, decision)

    proveedor = _proveedor_ambiguo("CRUCERO PERALILLO")
    resultado = aplicar_decisiones_multiples(
        raiz_atlas=ent["raiz"],
        solicitudes=[{
            "decision_id": decision["decision_id"], "accion": "REGISTRAR_DIRECCION",
            "direccion_manual": "CRUCERO PERALILLO", "comuna_manual": "LAMPA",
        }],
        proveedor_rutas=proveedor, proveedor_rutas_fallback=proveedor,
    )
    assert resultado.total_aplicadas == 1
    assert proveedor.llamadas_geocodificacion == 1


def test_c_guias_distintas_conservan_cada_una_su_propio_intento(tmp_path, monkeypatch):
    """Dos guías DESTINO_NO_RESUELTO distintas, ambas con origen ya
    resuelto: cada una paga exactamente 1 intento REAL (`calcular_ruta_
    con_planta_conocida`, la unidad de trabajo por guía -- independiente
    de cuántas subconsultas primario/respaldo haga por dentro) -- la
    exclusión de una nunca bloquea a la otra, y ninguna se repite dos
    veces. Se cuenta por guía envolviendo la función real (delega en
    ella) en vez de contar consultas HTTP crudas, cuyo número por
    intento puede variar sin que eso sea el bug que este bloque corrige."""
    fila_a = _fila_destino("473545", "473545.jpeg")
    fila_b = _fila_destino("473546", "473546.jpeg")
    ent = _entorno(tmp_path, filas_csv=[fila_a, fila_b])
    decision_a = detectar_decision_destino_no_resuelto(archivo="473545.jpeg", fila=fila_a)
    decision_b = detectar_decision_destino_no_resuelto(archivo="473546.jpeg", fila=fila_b)
    generar_artefacto(
        ruta_dataset=ent["dataset"], carpeta_catalogos=ent["catalogos"],
        decisiones=[decision_a, decision_b],
        ruta_salida=ent["actual"] / "decisiones_pendientes.json",
    )

    from atlas_core.rutas import destino_entrega

    llamadas_por_guia: dict[str, int] = {}
    original = destino_entrega.calcular_ruta_con_planta_conocida

    def _contador(*, despachar_a_crudo, **kwargs):
        llamadas_por_guia[despachar_a_crudo] = llamadas_por_guia.get(despachar_a_crudo, 0) + 1
        return original(despachar_a_crudo=despachar_a_crudo, **kwargs)

    monkeypatch.setattr(destino_entrega, "calcular_ruta_con_planta_conocida", _contador)

    resultado = aplicar_decisiones_multiples(
        raiz_atlas=ent["raiz"],
        solicitudes=[
            {
                "decision_id": decision_a["decision_id"], "accion": "REGISTRAR_DIRECCION",
                "direccion_manual": "CRUCERO PERALILLO", "comuna_manual": "LAMPA",
            },
            {
                "decision_id": decision_b["decision_id"], "accion": "REGISTRAR_DIRECCION",
                "direccion_manual": "CAMINO RURAL DOS", "comuna_manual": "LAMPA",
            },
        ],
        proveedor_rutas=ProveedorRutasSimulado(), proveedor_rutas_fallback=ProveedorRutasSimulado(),
    )
    assert resultado.total_aplicadas == 2
    # 2 guías, cada una con exactamente 1 intento real -- ni 1 (una guía
    # bloqueando a la otra) ni 4 (cada una repetida por la batería).
    assert llamadas_por_guia == {"CRUCERO PERALILLO": 1, "CAMINO RURAL DOS": 1}


def test_d_operacion_posterior_independiente_puede_reintentar(tmp_path):
    """La exclusión vive sólo dentro de la llamada -- nunca se persiste.
    Una SEGUNDA operación (llamada independiente a `revalidar_y_
    regenerar_reporte`, simulando un ciclo de reconciliación posterior)
    sobre la MISMA guía sí vuelve a intentar, según las reglas
    normales (nunca un cooldown permanente nuevo)."""
    fila = _fila_destino("473545", "473545.jpeg")
    ent = _entorno(tmp_path, filas_csv=[fila])
    decision = detectar_decision_destino_no_resuelto(archivo="473545.jpeg", fila=fila)
    _publicar_decision(ent, decision)

    proveedor = _proveedor_ambiguo("CRUCERO PERALILLO")
    aplicar_decisiones_multiples(
        raiz_atlas=ent["raiz"],
        solicitudes=[{
            "decision_id": decision["decision_id"], "accion": "REGISTRAR_DIRECCION",
            "direccion_manual": "CRUCERO PERALILLO", "comuna_manual": "LAMPA",
        }],
        proveedor_rutas=proveedor, proveedor_rutas_fallback=proveedor,
    )
    assert proveedor.llamadas_geocodificacion == 1

    # Operación NUEVA e independiente -- ningún `guias_excluir_reintento_ruta`
    # se le pasa (no hay lote en curso); debe poder reintentar normalmente.
    revalidar_y_regenerar_reporte(
        raiz_atlas=ent["raiz"], nombre_carpeta_reporte="reporte_operacion_posterior",
        proveedor_rutas=proveedor, proveedor_rutas_fallback=proveedor,
    )
    assert proveedor.llamadas_geocodificacion == 2


def test_e_resultado_ambiguo_nunca_se_convierte_en_exito(tmp_path):
    fila = _fila_destino("473545", "473545.jpeg")
    ent = _entorno(tmp_path, filas_csv=[fila])
    decision = detectar_decision_destino_no_resuelto(archivo="473545.jpeg", fila=fila)
    _publicar_decision(ent, decision)

    proveedor = _proveedor_ambiguo("CRUCERO PERALILLO")
    resultado_aplicacion = aplicar_decision_obra(
        raiz_atlas=ent["raiz"], decision_id=decision["decision_id"], accion="REGISTRAR_DIRECCION",
        direccion_manual="CRUCERO PERALILLO", comuna_manual="LAMPA",
        proveedor_rutas=proveedor, proveedor_rutas_fallback=proveedor,
    )
    assert resultado_aplicacion["ok"] is True
    assert resultado_aplicacion["ruta_resuelta"] is False

    with (ent["dataset"]).open(encoding="utf-8-sig", newline="") as fh:
        fila_final = next(csv.DictReader(fh, delimiter=";"))
    assert fila_final["estado_ruta"] != EstadoRuta.RUTA_CALCULADA.value
    # La dirección documental confirmada por el humano persiste (Bloque
    # R6) -- pero nunca se inventa una ruta/coordenada a partir de un
    # candidato ambiguo.
    assert fila_final["despachar_a_crudo"] == "CRUCERO PERALILLO"


def test_f_plan_impacto_agrupado_sigue_una_sola_bateria_global_por_lote(tmp_path, monkeypatch):
    """Regresión directa del bloque anterior (PlanImpacto agrupado V2):
    este cambio NO debe convertir la única `revalidar_y_regenerar_
    reporte` agregada del lote en varias -- sigue siendo 1, sin importar
    cuántas guías queden excluidas de reintento."""
    filas = [_fila_destino(g, f"{g}.jpeg") for g in ("473545", "473546")]
    ent = _entorno(tmp_path, filas_csv=filas)
    decisiones = [
        detectar_decision_destino_no_resuelto(archivo=f"{g}.jpeg", fila=f)
        for g, f in (("473545", filas[0]), ("473546", filas[1]))
    ]
    generar_artefacto(
        ruta_dataset=ent["dataset"], carpeta_catalogos=ent["catalogos"], decisiones=decisiones,
        ruta_salida=ent["actual"] / "decisiones_pendientes.json",
    )

    llamadas_revalidacion = []

    def _contador_revalidacion(**kwargs):
        llamadas_revalidacion.append(kwargs)
        return {"reporte_regenerado": False}

    llamadas_reconciliacion = []

    def _contador_reconciliacion(**kwargs):
        llamadas_reconciliacion.append(kwargs)
        return {"reconciliado": True, "motivo": "TEST"}

    monkeypatch.setattr(
        "atlas_core.revalidacion_documental.revalidar_y_regenerar_reporte", _contador_revalidacion,
    )
    monkeypatch.setattr(
        "atlas_core.reconciliacion_estado_derivado.reconciliar_estado_derivado", _contador_reconciliacion,
    )
    resultado = aplicar_decisiones_multiples(
        raiz_atlas=ent["raiz"],
        solicitudes=[
            {
                "decision_id": decisiones[0]["decision_id"], "accion": "REGISTRAR_DIRECCION",
                "direccion_manual": "CRUCERO PERALILLO", "comuna_manual": "LAMPA",
            },
            {
                "decision_id": decisiones[1]["decision_id"], "accion": "REGISTRAR_DIRECCION",
                "direccion_manual": "CAMINO RURAL DOS", "comuna_manual": "LAMPA",
            },
        ],
        # Los intentos INLINE (dentro de `aplicar_decision_obra`, nunca
        # monkeypatchados arriba) siguen corriendo de verdad -- un
        # `ProveedorRutasSimulado` vacío responde determinista para
        # CUALQUIER dirección (ver su fallback sintético), nunca red real.
        proveedor_rutas=ProveedorRutasSimulado(), proveedor_rutas_fallback=ProveedorRutasSimulado(),
    )
    assert resultado.total_aplicadas == 2
    assert len(llamadas_revalidacion) == 1
    assert len(llamadas_reconciliacion) == 1
    kwargs_revalidacion = llamadas_revalidacion[0]
    assert kwargs_revalidacion["guias_excluir_reintento_ruta"] == {"473545", "473546"}
