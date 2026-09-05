"""ATLAS -- Convergencia de pendientes técnicos post lote 2.

Amplía `detectar_decision_destino_no_resuelto` para que motivos técnicos
que hoy dejaban una guía sin ninguna tarjeta en Revisión de Atlas
(`GEOCODIFICACION_DIRECCION_NO_ENCONTRADA`, `DESTINO_REVISAR`) produzcan
`DESTINO_NO_RESUELTO` de inmediato -- son callejones sin salida con la
evidencia ya persistida -- y da efecto real al `escalamiento` que
`reconciliacion_estado_derivado._registro_pendiente` ya declaraba sin
ningún consumidor: `COORDENADA_NO_CONFIRMADA` (candidato ambiguo, no un
callejón sin salida) sólo se convierte en pregunta humana una vez que
`pendientes_tecnicos.json` registra `intentos_misma_evidencia >=
UMBRAL_INTENTOS_TECNICOS_AGOTADOS` -- nunca antes, para no preguntarle a
Javier mientras Atlas todavía tiene un reintento automático razonable por
explotar (caso real 464588: el fix de deduplicación de comuna ya resuelve
solo en el siguiente reintento).

Casos reales que motivan este bloque: 464395 (GEOCODIFICACION_DIRECCION_
NO_ENCONTRADA, proveedor sin cobertura incluso con el texto limpio);
464367/464265 (DESTINO_REVISAR, dejado por
`derivar_estado_ruta_tras_cambio_origen` tras resolverse el origen);
464588 (COORDENADA_NO_CONFIRMADA, ya resuelto por un fix previo -- no debe
generar una pregunta prematura)."""
from __future__ import annotations

import csv
import json

from atlas_core.aplicacion_decisiones import aplicar_decision_obra
from atlas_core.catalogo_plantas import CatalogoPlantas, EstadoCalidad
from atlas_core.decisiones_pendientes import (
    MOTIVOS_DESTINO_NO_RESUELTO,
    MOTIVOS_DESTINO_TECNICO_AGOTABLE,
    UMBRAL_INTENTOS_TECNICOS_AGOTADOS,
    detectar_decision_destino_no_resuelto,
    generar_artefacto,
    regenerar_decisiones_persistidas,
)
from atlas_core.procesamiento_masivo import COLUMNAS
from atlas_core.revalidacion_documental import forzar_decision_correccion_destino
from atlas_core.rutas.modelos import (
    CandidatoGeocodificacion, Coordenadas, EstadoRuta, ResultadoGeocodificacion, ResultadoRuta,
)
from atlas_core.rutas.proveedor import ProveedorRutasSimulado

FECHA = "04-09-2026"


def _fila_csv(**overrides):
    fila = {c: "" for c in COLUMNAS}
    fila.update({
        "archivo": "464740.jpeg", "estado_procesamiento": "OK", "numero_guia": "464740",
        "numero_transporte": "0000353164", "fecha": FECHA, "chofer": "CHOFER TEST",
        "cliente": "CLIENTE TEST", "obra_destino": "OBRA TEST",
        "patente_tracto": "AATT11", "indicador_revision": "REVISAR",
        "planta_origen_id": "planta-colina", "planta_origen_nombre": "AZA COLINA",
        "origen_determinado_por": "CATEGORIA_DESTINO_EXTERNO", "evidencia_origen": "CATEGORIA:x",
        "despachar_a_crudo": "AV. VICUNA MACKENNA 3451 SAN JOAQUIN SAN JOA",
        "direccion_entrega": "", "estado_entrega": "REVISAR",
        "distancia_km": "", "duracion_min": "", "proveedor_ruta": "",
        "estado_ruta": "REQUIERE_REVISION", "motivo_ruta": "MULTIPLES_UBICACIONES_DISPERSAS(5)",
    })
    fila.update(overrides)
    return fila


def _escribir_csv(ruta, filas):
    with ruta.open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader()
        escritor.writerows(filas)


def _escribir_pendientes_tecnicos(ruta, *, numero_guia, intentos):
    ruta.write_text(json.dumps({
        "schema_version": 1, "actualizado_en": "2026-09-04T22:00:00Z",
        "pendientes": [{
            "numero_guia": numero_guia, "dependencia_fallida": "GEOCODIFICACION_ROUTING",
            "resultado_pendiente": "DIRECCION_ENTREGA_KM_TIEMPO",
            "motivo_actual": "COORDENADA_NO_CONFIRMADA(5)", "reintentable": True,
            "datos_disponibles": {}, "huella_datos": "irrelevante-en-este-test",
            "intentos_misma_evidencia": intentos, "ultimo_intento": "2026-09-04T17:20:57Z",
            "ultimo_resultado": None, "historial_resultados": [],
            "proxima_oportunidad": "ARRANQUE_TRAS_24H_O_CAMBIO_DE_EVIDENCIA",
            "escalamiento": (
                "PROXIMA_CORRIDA_GUIAS_REVALIDACION_GLOBAL_B1"
                if intentos >= UMBRAL_INTENTOS_TECNICOS_AGOTADOS else "REINTENTO_DEPENDENCIA"
            ),
        }],
    }, ensure_ascii=False, indent=2), encoding="utf-8")


# ============================================================
# PRUEBA (a): motivo técnico de geocodificación -> decisión accionable
# ============================================================


def test_geocodificacion_direccion_no_encontrada_es_accionable_de_inmediato():
    """Caso real 464395 -- proveedor sin cobertura incluso con la
    dirección ya limpia: no es una falla técnica transitoria, es un
    callejón sin salida con la evidencia ya persistida -- accionable de
    inmediato, sin esperar ningún reintento."""
    fila = _fila_csv(
        archivo="464395.jpeg", numero_guia="464395", numero_transporte="0000351884",
        despachar_a_crudo="CARMEN MENA 529 SAN MIGUEL SAN MIGUEL",
        motivo_ruta="GEOCODIFICACION_DIRECCION_NO_ENCONTRADA",
    )
    decision = detectar_decision_destino_no_resuelto(archivo="464395.jpeg", fila=fila)
    assert decision is not None
    assert decision["tipo"] == "DESTINO_NO_RESUELTO"
    assert decision["motivos"] == ["GEOCODIFICACION_DIRECCION_NO_ENCONTRADA"]
    assert "GEOCODIFICACION_DIRECCION_NO_ENCONTRADA" in MOTIVOS_DESTINO_NO_RESUELTO


def test_destino_revisar_es_accionable_de_inmediato_caso_real_464367():
    """Caso real 464367 -- origen ya confirmado por Javier (AZA COLINA),
    destino OCR rechazado por Javier: `derivar_estado_ruta_tras_cambio_
    origen` deja `DESTINO_REVISAR`, un motivo genérico sin detalle técnico
    reconstruible. Nunca debe quedar atrapado como INCOMPLETO_TECNICO."""
    fila = _fila_csv(
        archivo="464367.jpeg", numero_guia="464367", numero_transporte="0000351370",
        despachar_a_crudo="TACHA 144 TUNGAY DIAGUILLIN",
        origen_determinado_por="CONFIRMACION_HUMANA", evidencia_origen="DECISION_HUMANA:x",
        motivo_ruta="DESTINO_REVISAR",
    )
    decision = detectar_decision_destino_no_resuelto(archivo="464367.jpeg", fila=fila)
    assert decision is not None
    assert decision["motivos"] == ["DESTINO_REVISAR"]
    # Nunca inventa la dirección: el valor documental rechazado queda
    # expuesto como evidencia, nunca como una propuesta de corrección.
    assert decision["valor_documental"] == "TACHA 144 TUNGAY DIAGUILLIN"


# ============================================================
# PRUEBAS (e)/(f): reintentos y escalamiento -- COORDENADA_NO_CONFIRMADA
# ============================================================


def test_coordenada_no_confirmada_no_genera_decision_mientras_haya_reintento_automatico():
    """PRUEBA (f) -- caso real 464588: mientras `intentos_misma_evidencia`
    no alcanza el umbral, Atlas todavía tiene un reintento automático
    razonable por explotar (el fix de deduplicación de comuna). No se le
    pregunta a Javier de forma prematura."""
    fila = _fila_csv(
        archivo="464588.jpeg", numero_guia="464588", numero_transporte="0000352600",
        despachar_a_crudo="POETA PEDRO PRADO 1548",
        motivo_ruta="COORDENADA_NO_CONFIRMADA(5)",
    )
    for intentos in range(UMBRAL_INTENTOS_TECNICOS_AGOTADOS):
        assert detectar_decision_destino_no_resuelto(
            archivo="464588.jpeg", fila=fila, intentos_misma_evidencia=intentos,
        ) is None, intentos


def test_coordenada_no_confirmada_genera_decision_al_agotar_reintentos():
    """PRUEBA (e) -- el escalamiento al agotar los reintentos con la misma
    evidencia debe tener efecto real: al llegar a
    `UMBRAL_INTENTOS_TECNICOS_AGOTADOS`, se convierte en una acción humana
    de destino, conservando el diagnóstico técnico (`intentos_misma_
    evidencia`) en la evidencia de la tarjeta."""
    fila = _fila_csv(
        archivo="464588.jpeg", numero_guia="464588", numero_transporte="0000352600",
        despachar_a_crudo="POETA PEDRO PRADO 1548",
        motivo_ruta="COORDENADA_NO_CONFIRMADA(5)",
    )
    decision = detectar_decision_destino_no_resuelto(
        archivo="464588.jpeg", fila=fila, intentos_misma_evidencia=UMBRAL_INTENTOS_TECNICOS_AGOTADOS,
    )
    assert decision is not None
    assert decision["motivos"] == ["COORDENADA_NO_CONFIRMADA"]
    assert decision["evidencias"][0]["intentos_misma_evidencia"] == UMBRAL_INTENTOS_TECNICOS_AGOTADOS
    assert "COORDENADA_NO_CONFIRMADA" in MOTIVOS_DESTINO_TECNICO_AGOTABLE
    assert "COORDENADA_NO_CONFIRMADA" not in MOTIVOS_DESTINO_NO_RESUELTO


def test_ruta_ya_calculada_no_genera_decision_pese_a_reintentos_agotados():
    """Si el reintento automático SÍ resolvió (ruta ya calculada antes de
    llegar aquí), nunca se genera una pregunta humana -- sin importar
    cuántos intentos previos quedaron registrados."""
    fila = _fila_csv(
        estado_ruta="RUTA_CALCULADA", motivo_ruta="", distancia_km="10.0", duracion_min="15",
    )
    assert detectar_decision_destino_no_resuelto(
        archivo="x", fila=fila, intentos_misma_evidencia=UMBRAL_INTENTOS_TECNICOS_AGOTADOS,
    ) is None


# ============================================================
# Integración -- regenerar_decisiones_persistidas lee `pendientes_tecnicos.json`
# ============================================================


def _entorno_sweep(tmp_path, *, intentos, motivo="COORDENADA_NO_CONFIRMADA(5)"):
    actual = tmp_path / "operacion" / "actual"
    catalogos = tmp_path / "catalogos_privados"
    actual.mkdir(parents=True)
    catalogos.mkdir(parents=True)
    for nombre, contenido in {
        "clientes.json": {"version_formato": 1, "clientes": []},
        "empresas.json": {},
        "vehiculos.json": {"version": 1, "vehiculos": []},
        "obras_destinos.json": {"version_formato": 1, "obras": [], "relaciones": []},
        "destinos_maestros.json": {"version_formato": 1, "destinos": []},
    }.items():
        (catalogos / nombre).write_text(json.dumps(contenido), encoding="utf-8")
    dataset = actual / "analisis_completo_guias.csv"
    _escribir_csv(dataset, [_fila_csv(motivo_ruta=motivo)])
    _escribir_pendientes_tecnicos(actual / "pendientes_tecnicos.json", numero_guia="464740", intentos=intentos)
    return dataset, catalogos


def test_regenerar_decisiones_persistidas_respeta_intentos_de_pendientes_tecnicos_json(tmp_path):
    """PRUEBA (f) -- el barrido real (`regenerar_decisiones_persistidas`,
    invocado por `reconciliar_bandeja_decisiones` en cada reconciliación
    automática) debe leer `pendientes_tecnicos.json` del mismo directorio
    que el dataset -- nunca generar la tarjeta antes de que el escalamiento
    lo declare agotado."""
    dataset, catalogos = _entorno_sweep(tmp_path, intentos=UMBRAL_INTENTOS_TECNICOS_AGOTADOS - 1)
    vigentes = regenerar_decisiones_persistidas(decisiones=[], carpeta_catalogos=catalogos, ruta_dataset=dataset)
    assert vigentes == []


def test_regenerar_decisiones_persistidas_publica_al_agotar_intentos(tmp_path):
    """PRUEBA (e) -- con el escalamiento ya agotado, el mismo barrido SÍ
    publica la tarjeta -- ningún caso queda detenido en silencio tras el
    tercer intento."""
    dataset, catalogos = _entorno_sweep(tmp_path, intentos=UMBRAL_INTENTOS_TECNICOS_AGOTADOS)
    vigentes = regenerar_decisiones_persistidas(decisiones=[], carpeta_catalogos=catalogos, ruta_dataset=dataset)
    assert len(vigentes) == 1
    assert vigentes[0]["tipo"] == "DESTINO_NO_RESUELTO"
    assert vigentes[0]["motivos"] == ["COORDENADA_NO_CONFIRMADA"]
    assert vigentes[0]["documento"]["numero_guia"] == "464740"


# ============================================================
# PRUEBA (g): idempotencia -- reconciliar de nuevo no duplica decisiones
# ============================================================


def test_regenerar_decisiones_persistidas_es_idempotente(tmp_path):
    dataset, catalogos = _entorno_sweep(tmp_path, intentos=UMBRAL_INTENTOS_TECNICOS_AGOTADOS)
    primera = regenerar_decisiones_persistidas(decisiones=[], carpeta_catalogos=catalogos, ruta_dataset=dataset)
    assert len(primera) == 1

    # La segunda pasada recibe exactamente lo que la primera dejó vigente
    # (el mismo insumo que usaría `reconciliar_bandeja_decisiones` en la
    # siguiente reconciliación automática) -- no debe crecer ni cambiar de
    # identidad.
    segunda = regenerar_decisiones_persistidas(decisiones=primera, carpeta_catalogos=catalogos, ruta_dataset=dataset)
    assert len(segunda) == 1
    assert segunda[0]["decision_id"] == primera[0]["decision_id"]

    # Publicar dos veces tampoco duplica -- misma garantía ya existente de
    # `generar_artefacto` (dedup contra el ledger por `decision_id`),
    # ejercida aquí sobre el flujo ampliado.
    salida = dataset.parent / "decisiones_pendientes.json"
    generar_artefacto(
        ruta_dataset=dataset, carpeta_catalogos=catalogos, decisiones=primera, ruta_salida=salida,
    )
    generar_artefacto(
        ruta_dataset=dataset, carpeta_catalogos=catalogos, decisiones=segunda, ruta_salida=salida,
    )
    bandeja = json.loads(salida.read_text(encoding="utf-8"))
    assert len(bandeja["decisiones"]) == 1


# ============================================================
# PRUEBA (b)/(c)/(d): "Corregir destino" desde Logística (fuera de
# Revisión de Atlas) -- Bloque CORRECCIÓN HUMANA DE DESTINO
# ============================================================


COORD_AZA_COLINA = Coordenadas(-70.665977, -33.137558)


def _entorno_forzar(tmp_path, *, fila_extra=None):
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
    planta = CatalogoPlantas(catalogos / "plantas.json").crear(
        nombre="AZA COLINA", pais="CHILE", fuente="TEST",
        direccion="AV EJEMPLO 1", comuna="COLINA", region="RM",
        latitud=COORD_AZA_COLINA.latitud, longitud=COORD_AZA_COLINA.longitud,
        estado_calidad=EstadoCalidad.CONFIRMADA,
    )
    fila = _fila_csv(
        archivo="464740.jpeg", numero_guia="464740", numero_transporte="0000353164",
        planta_origen_id=planta.planta_id,
        # Caso real 464740 -- un viaje que YA parecía correcto (ruta
        # calculada) hasta que Javier descubre, fuera de Revisión de
        # Atlas, que el destino operacional es el equivocado.
        despachar_a_crudo="DIRECCION VIEJA INCORRECTA 123",
        estado_ruta="RUTA_CALCULADA", motivo_ruta="", distancia_km="99.9", duracion_min="120",
    )
    if fila_extra:
        fila.update(fila_extra)
    dataset = actual / "analisis_completo_guias.csv"
    _escribir_csv(dataset, [fila])
    return {
        "raiz": raiz, "catalogos": catalogos, "actual": actual, "dataset": dataset,
        "planta_id": planta.planta_id, "fila": fila,
    }


def _proveedor_direccion_valida(direccion):
    consulta = f"{direccion}, Chile"
    return ProveedorRutasSimulado(
        geocodificaciones={
            consulta: ResultadoGeocodificacion(
                EstadoRuta.REQUIERE_REVISION,
                (CandidatoGeocodificacion(
                    Coordenadas(-70.634933, -33.436723), direccion + ", Santiago, RM, Chile", 1.0,
                    "Santiago", "Metropolitana",
                ),),
                "",
            )
        },
        resultado_ruta=ResultadoRuta(EstadoRuta.RUTA_CALCULADA, 25.4, 38.2, "SINTETICO"),
    )


def test_forzar_correccion_destino_publica_decision_aunque_ruta_ya_calculada(tmp_path):
    """PRUEBA (b) -- caso real 464740 fuera del contexto de este bloque
    (aquí como ejemplo genérico): Javier descubre un destino erróneo por
    fuera de Revisión de Atlas -- ninguna evidencia técnica bloqueaba la
    ruta (`estado_ruta=RUTA_CALCULADA`), así que el detector automático
    nunca habría generado esta pregunta. "Corregir destino" (Logística)
    la publica igual, a pedido explícito del humano."""
    entorno = _entorno_forzar(tmp_path)
    resultado = forzar_decision_correccion_destino(raiz_atlas=entorno["raiz"], numero_guia="464740")
    assert resultado["ok"] is True
    decision = resultado["decision"]
    assert decision["tipo"] == "DESTINO_NO_RESUELTO"
    assert decision["motivos"] == ["CORRECCION_MANUAL_LOGISTICA"]
    assert "REGISTRAR_DIRECCION" in decision["acciones_permitidas"]
    # El texto rechazado nunca queda oculto -- sigue siendo la evidencia
    # documental de la propia tarjeta.
    assert decision["valor_documental"] == "DIRECCION VIEJA INCORRECTA 123"

    bandeja = json.loads((entorno["actual"] / "decisiones_pendientes.json").read_text(encoding="utf-8"))
    assert len(bandeja["decisiones"]) == 1
    assert bandeja["decisiones"][0]["decision_id"] == decision["decision_id"]


def test_forzar_correccion_destino_es_idempotente(tmp_path):
    """PRUEBA (g) -- abrir "Corregir destino" dos veces sin que el
    documento cambie nunca duplica la tarjeta."""
    entorno = _entorno_forzar(tmp_path)
    primera = forzar_decision_correccion_destino(raiz_atlas=entorno["raiz"], numero_guia="464740")
    segunda = forzar_decision_correccion_destino(raiz_atlas=entorno["raiz"], numero_guia="464740")
    assert primera["decision"]["decision_id"] == segunda["decision"]["decision_id"]
    bandeja = json.loads((entorno["actual"] / "decisiones_pendientes.json").read_text(encoding="utf-8"))
    assert len(bandeja["decisiones"]) == 1


def test_forzar_correccion_destino_con_motivo_tecnico_real_no_duplica_la_decision_automatica(tmp_path):
    """Regresión real detectada en vivo (464367, demostración visual de
    "Corregir destino"): si la fila YA tiene un motivo técnico real y
    reconocido (aquí, GEOCODIFICACION_DIRECCION_NO_ENCONTRADA), forzar la
    pregunta desde Logística debe producir el MISMO `decision_id` que
    generaría el detector automático -- nunca una segunda tarjeta para el
    mismo problema (el bug real: `evidencias[0]["origen_pregunta"]` se
    agregaba siempre que `forzar=True`, cambiando el hash aunque ya
    existiera un motivo técnico real)."""
    entorno = _entorno_forzar(tmp_path, fila_extra={
        "estado_ruta": "REQUIERE_REVISION", "motivo_ruta": "GEOCODIFICACION_DIRECCION_NO_ENCONTRADA",
        "distancia_km": "", "duracion_min": "",
    })
    fila_actual = dict(entorno["fila"])
    fila_actual.update({
        "estado_ruta": "REQUIERE_REVISION", "motivo_ruta": "GEOCODIFICACION_DIRECCION_NO_ENCONTRADA",
        "distancia_km": "", "duracion_min": "",
    })
    automatica = detectar_decision_destino_no_resuelto(
        archivo="464740.jpeg", fila=fila_actual, carpeta_catalogos=entorno["catalogos"],
    )
    forzada = forzar_decision_correccion_destino(raiz_atlas=entorno["raiz"], numero_guia="464740")
    assert forzada["ok"] is True
    if automatica is not None:
        assert forzada["decision"]["decision_id"] == automatica["decision_id"]
    assert forzada["decision"]["motivos"] == ["GEOCODIFICACION_DIRECCION_NO_ENCONTRADA"]
    assert "origen_pregunta" not in forzada["decision"]["evidencias"][0]

    # Publicar dos veces (la segunda simula reabrir "Corregir destino")
    # nunca deja dos tarjetas para la misma guía.
    forzar_decision_correccion_destino(raiz_atlas=entorno["raiz"], numero_guia="464740")
    bandeja = json.loads((entorno["actual"] / "decisiones_pendientes.json").read_text(encoding="utf-8"))
    guias_destino = [
        (d.get("documento") or {}).get("numero_guia") for d in bandeja["decisiones"] if d["tipo"] == "DESTINO_NO_RESUELTO"
    ]
    assert guias_destino.count("464740") == 1


def test_forzar_correccion_destino_sin_origen_confirmado_se_abstiene(tmp_path):
    """Único caso real de abstención con `forzar=True`: sin planta de
    origen confirmada, preguntar por destino no aporta nada -- Javier debe
    resolver el origen primero (Revisión de Atlas), nunca un atajo que se
    lo salte."""
    entorno = _entorno_forzar(tmp_path, fila_extra={"planta_origen_id": "", "planta_origen_nombre": ""})
    resultado = forzar_decision_correccion_destino(raiz_atlas=entorno["raiz"], numero_guia="464740")
    assert resultado["ok"] is False
    assert not (entorno["actual"] / "decisiones_pendientes.json").exists()


def test_forzar_correccion_destino_documento_inexistente(tmp_path):
    entorno = _entorno_forzar(tmp_path)
    resultado = forzar_decision_correccion_destino(raiz_atlas=entorno["raiz"], numero_guia="999999")
    assert resultado["ok"] is False


def test_corregir_destino_desde_logistica_invalida_derivados_y_recalcula_en_el_mismo_ciclo(tmp_path):
    """PRUEBAS (c)/(d) -- de punta a punta: la corrección manual publica
    la decisión ("Corregir destino"), y aplicarla con REGISTRAR_DIRECCION
    (el mismo backend ya usado por cualquier DESTINO_NO_RESUELTO,
    "no duplicar maquinaria existente") invalida el km/tiempo VIEJO
    (99.9 km / 120 min de una dirección que ya sabíamos incorrecta) y
    calcula/persiste el nuevo en el mismo ciclo -- nunca una mezcla del
    destino viejo con la ruta nueva, ni viceversa."""
    entorno = _entorno_forzar(tmp_path)
    publicacion = forzar_decision_correccion_destino(raiz_atlas=entorno["raiz"], numero_guia="464740")
    assert publicacion["ok"] is True
    decision_id = publicacion["decision"]["decision_id"]

    direccion_corregida = "AVENIDA APOQUINDO 1234"
    resultado = aplicar_decision_obra(
        raiz_atlas=entorno["raiz"], decision_id=decision_id,
        accion="REGISTRAR_DIRECCION", direccion_manual=direccion_corregida,
        proveedor_rutas=_proveedor_direccion_valida(direccion_corregida),
    )
    assert resultado["ok"] is True
    assert resultado["ruta_resuelta"] is True

    fila = _leer_csv(entorno["dataset"])[0]
    assert fila["despachar_a_crudo"] == direccion_corregida
    assert fila["estado_ruta"] == "RUTA_CALCULADA"
    # La ruta VIEJA (de la dirección incorrecta) nunca sobrevive mezclada
    # con el destino nuevo.
    assert fila["distancia_km"] == "25.4"
    assert fila["duracion_min"] == "38.2"

    # La decisión ya no está pendiente, y el reporte/estado_operacion se
    # regeneró en el mismo ciclo.
    bandeja = json.loads((entorno["actual"] / "decisiones_pendientes.json").read_text(encoding="utf-8"))
    assert bandeja["decisiones"] == []
    assert (entorno["actual"] / "estado_operacion.json").exists()


def _leer_csv(ruta):
    with ruta.open("r", newline="", encoding="utf-8-sig") as archivo:
        return list(csv.DictReader(archivo, delimiter=";"))
