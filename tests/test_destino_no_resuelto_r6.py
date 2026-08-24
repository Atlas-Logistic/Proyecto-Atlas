"""Bloque R6 A/B/E -- ciclo de vida completo post-confirmación de origen:
con planta ya resuelta pero destino bloqueado (documento sin dirección
utilizable, o geocodificando de forma contradictoria/genérica/ambigua),
Atlas genera una decisión `DESTINO_NO_RESUELTO` accionable en vez de
quedarse en "No disponible" en silencio. Un humano escribe la dirección
real; se valida con el mismo mecanismo determinista de geocodificación/
ruta ya existente (nunca se acepta a ciegas). Si la ruta se calcula, la
relación obra<->destino queda CONFIRMADA en el catálogo ya existente --
documentos futuros de la misma obra resuelven solos.

Caso real emblemático: guía 472037 (CRISTOPHER RETAMAL, obra "ING Y CONST
FUNDAMENTA SPA", cliente "COMERCIAL A Y B LTDA"), origen ya confirmado
AZA COLINA, destino sin ningún dato documental (`DESTINO_SIN_DATO`)."""
from __future__ import annotations

import csv
import json

from atlas_core.aplicacion_decisiones import ErrorAplicacionDecision, aplicar_decision_obra
from atlas_core.catalogo_obras_destinos import CatalogoObrasDestinos
from atlas_core.catalogo_plantas import CatalogoPlantas, EstadoCalidad
from atlas_core.decisiones_pendientes import (
    crear_decision, detectar_decision_destino_no_resuelto, generar_artefacto,
)
from atlas_core.procesamiento_masivo import COLUMNAS
from atlas_core.revalidacion_documental import (
    detectar_decisiones_destino_no_resuelto_sin_ocr,
    reconciliar_decisiones_destino_no_resuelto,
)
from atlas_core.rutas.modelos import (
    CandidatoGeocodificacion, Coordenadas, EstadoRuta, ResultadoGeocodificacion, ResultadoRuta,
)
from atlas_core.rutas.proveedor import ProveedorRutasSimulado

COORD_AZA_COLINA = Coordenadas(-70.665977, -33.137558)
FECHA = "21-08-2026"


def _fila_csv(**overrides):
    fila = {c: "" for c in COLUMNAS}
    fila.update({
        "archivo": "472037.jpeg", "estado_procesamiento": "OK", "numero_guia": "472037",
        "numero_transporte": "0000354034", "fecha": FECHA, "chofer": "CRISTOPHER RETAMAL",
        "cliente": "COMERCIAL A Y B LTDA", "obra_destino": "ING Y CONST FUNDAMENTA SPA",
        "patente_tracto": "BPHR67", "indicador_revision": "REVISAR",
        "planta_origen_id": "planta-colina", "planta_origen_nombre": "AZA COLINA",
        "origen_determinado_por": "CONFIRMACION_HUMANA", "evidencia_origen": "DECISION_HUMANA:x",
        "despachar_a_crudo": "", "direccion_entrega": "", "estado_entrega": "SIN_DATO",
        "distancia_km": "", "duracion_min": "", "proveedor_ruta": "",
        "estado_ruta": "REQUIERE_REVISION", "motivo_ruta": "DESTINO_SIN_DATO",
    })
    fila.update(overrides)
    return fila


def _escribir_csv(ruta, filas):
    with ruta.open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader()
        escritor.writerows(filas)


def _leer_csv(ruta):
    with ruta.open("r", newline="", encoding="utf-8-sig") as archivo:
        return list(csv.DictReader(archivo, delimiter=";"))


def _entorno(tmp_path, *, filas_csv, clientes=None, obras=None):
    raiz = tmp_path / "Atlas"
    catalogos = raiz / "catalogos_privados"
    actual = raiz / "operacion" / "actual"
    catalogos.mkdir(parents=True)
    actual.mkdir(parents=True)
    for nombre, contenido in {
        "clientes.json": {"version_formato": 1, "clientes": clientes or []},
        "empresas.json": {},
        "vehiculos.json": {"version": 1, "vehiculos": []},
        "obras_destinos.json": {"version_formato": 1, "obras": obras or [], "relaciones": []},
        "destinos_maestros.json": {"version_formato": 1, "destinos": []},
    }.items():
        (catalogos / nombre).write_text(json.dumps(contenido), encoding="utf-8")
    plantas = CatalogoPlantas(catalogos / "plantas.json")
    planta_colina = plantas.crear(
        nombre="AZA COLINA", pais="CHILE", fuente="TEST",
        direccion="AV EJEMPLO 1", comuna="COLINA", region="RM",
        latitud=COORD_AZA_COLINA.latitud, longitud=COORD_AZA_COLINA.longitud,
        estado_calidad=EstadoCalidad.CONFIRMADA,
    )
    # Las filas dadas usan el sentinela "planta-colina" (fijo, para que las
    # pruebas de detección pura no dependan del catálogo) -- aquí, donde sí
    # hay un catálogo real, se reescribe con el id real recién generado.
    for fila in filas_csv:
        if fila.get("planta_origen_id") == "planta-colina":
            fila["planta_origen_id"] = planta_colina.planta_id
    dataset = actual / "analisis_completo_guias.csv"
    _escribir_csv(dataset, filas_csv)
    return {"raiz": raiz, "catalogos": catalogos, "actual": actual, "dataset": dataset, "planta_colina_id": planta_colina.planta_id}


def _cliente_dict(cliente_id="cliente-ayb"):
    return {
        "cliente_id": cliente_id, "razon_social": "COMERCIAL A Y B LTDA",
        "nombre_normalizado": "COMERCIAL A Y B LTDA", "nombre_comercial": "", "rut": "76086428-5",
        "aliases": [], "estado_calidad": "CONFIRMADO", "estado_vigencia": "ACTIVO", "fuente": "TEST",
        "observacion": "", "fecha_creacion": "2026-01-01T00:00:00+00:00", "fecha_modificacion": "2026-01-01T00:00:00+00:00",
    }


def _obra_dict(obra_id="obra-fundamenta", cliente_id="cliente-ayb"):
    return {
        "obra_id": obra_id, "cliente_id": cliente_id, "nombre_canonico": "ING Y CONST FUNDAMENTA SPA",
        "nombre_normalizado": "ING Y CONST FUNDAMENTA SPA", "aliases_documentales": [],
        "estado": "OBSERVADA", "estado_vigencia": "ACTIVO", "evidencias": [],
        "fecha_creacion": "2026-01-01T00:00:00+00:00", "fecha_modificacion": "2026-01-01T00:00:00+00:00",
    }


def _publicar(entorno, decision):
    generar_artefacto(
        ruta_dataset=entorno["dataset"], carpeta_catalogos=entorno["catalogos"],
        decisiones=[decision], ruta_salida=entorno["actual"] / "decisiones_pendientes.json",
    )


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


def _proveedor_confianza_insuficiente(direccion, *, etiqueta):
    """Bloque CONFIRMACIÓN D2 -- caso real 472044 (PUERTA DEL SOL 83 LAS
    CONDES): un único candidato, pero con confianza por debajo del umbral
    -- el proveedor sólo resolvió hasta nivel comuna (`etiqueta` sin
    número de calle), exactamente el escenario que degradaba el destino
    operacional."""
    consulta = f"{direccion}, Chile"
    return ProveedorRutasSimulado(
        geocodificaciones={
            consulta: ResultadoGeocodificacion(
                EstadoRuta.REQUIERE_REVISION,
                (CandidatoGeocodificacion(
                    Coordenadas(-70.57, -33.41), etiqueta, 0.3, "Las Condes", "Metropolitana",
                ),),
                "",
            )
        },
        resultado_ruta=ResultadoRuta(EstadoRuta.RUTA_CALCULADA, 12.0, 20.0, "SINTETICO"),
    )


def _proveedor_direccion_ambigua(direccion):
    consulta = f"{direccion}, Chile"
    return ProveedorRutasSimulado(
        geocodificaciones={
            consulta: ResultadoGeocodificacion(
                EstadoRuta.RESULTADO_AMBIGUO,
                (
                    CandidatoGeocodificacion(Coordenadas(-70.6, -33.4), "A", 0.5, "Santiago", "Metropolitana"),
                    CandidatoGeocodificacion(Coordenadas(-70.5, -33.3), "B", 0.5, "Providencia", "Metropolitana"),
                ),
                "MULTIPLES_CANDIDATOS",
            )
        },
        resultado_ruta=ResultadoRuta(EstadoRuta.RUTA_CALCULADA, 1.0, 1.0, "SINTETICO"),
    )


# ============================================================
# Detección (pura)
# ============================================================


def test_genera_decision_destino_sin_dato_caso_real_472037():
    fila = _fila_csv()
    decision = detectar_decision_destino_no_resuelto(archivo="472037.jpeg", fila=fila)
    assert decision is not None
    assert decision["tipo"] == "DESTINO_NO_RESUELTO"
    assert decision["motivos"] == ["DESTINO_SIN_DATO"]
    assert decision["contexto"]["obra_canonica"] == "ING Y CONST FUNDAMENTA SPA"
    assert decision["contexto"]["cliente_canonico"] == "COMERCIAL A Y B LTDA"
    assert set(decision["acciones_permitidas"]) == {"REGISTRAR_DIRECCION", "NO_PUEDO_DETERMINAR", "POSPONER"}


def test_genera_decision_para_cada_motivo_de_destino_reconocido():
    for motivo in (
        "GEOCODIFICACION_CONTRADICE_COMUNA_DOCUMENTAL: San Bernardo != Angol",
        "GEOCODIFICACION_DEMASIADO_GENERICA",
        "MULTIPLES_UBICACIONES_DISPERSAS(5)",
    ):
        fila = _fila_csv(motivo_ruta=motivo)
        decision = detectar_decision_destino_no_resuelto(archivo="x", fila=fila)
        assert decision is not None, motivo


def test_genera_decision_para_sin_acceso_vial_caso_real_472044():
    """Bloque R9 -- distinto de los otros 4: SIN_ACCESO_VIAL es un
    rechazo a nivel de ROUTING (no de geocodificación de destino), así
    que `estado_ruta` queda igual a su propio motivo crudo, nunca
    normalizado a REQUIERE_REVISION -- debe seguir siendo elegible."""
    fila = _fila_csv(estado_ruta="SIN_ACCESO_VIAL", motivo_ruta="SIN_ACCESO_VIAL")
    decision = detectar_decision_destino_no_resuelto(archivo="472044.jpeg", fila=fila)
    assert decision is not None
    assert decision["motivos"] == ["SIN_ACCESO_VIAL"]


def test_no_genera_decision_sin_planta_origen():
    """Ese es un problema de ORIGEN, no de destino -- cubierto por
    detectar_decision_origen_no_confirmado."""
    fila = _fila_csv(planta_origen_id="", planta_origen_nombre="", estado_ruta="ORIGEN_NO_DETERMINADO", motivo_ruta="SIN_EVIDENCIA_GPS")
    assert detectar_decision_destino_no_resuelto(archivo="x", fila=fila) is None


def test_no_genera_decision_con_ruta_ya_calculada():
    fila = _fila_csv(estado_ruta="RUTA_CALCULADA", motivo_ruta="", distancia_km="10.0")
    assert detectar_decision_destino_no_resuelto(archivo="x", fila=fila) is None


def test_no_genera_decision_para_motivo_no_reconocido():
    """Un motivo técnico transitorio (proveedor caído, sin credencial) no
    es una pregunta para un humano."""
    fila = _fila_csv(motivo_ruta="SIN_CREDENCIAL")
    assert detectar_decision_destino_no_resuelto(archivo="x", fila=fila) is None


# ============================================================
# Escaneo del dataset completo
# ============================================================


def test_deteccion_de_dataset_completo(tmp_path):
    entorno = _entorno(tmp_path, filas_csv=[
        _fila_csv(numero_guia="1"),
        _fila_csv(numero_guia="2", estado_ruta="RUTA_CALCULADA", motivo_ruta="", distancia_km="5"),
        _fila_csv(numero_guia="3", planta_origen_id="", planta_origen_nombre="", estado_ruta="ORIGEN_NO_DETERMINADO", motivo_ruta="SIN_EVIDENCIA_GPS"),
    ])
    candidatas = detectar_decisiones_destino_no_resuelto_sin_ocr(raiz_atlas=entorno["raiz"])
    assert [c["documento"]["numero_guia"] for c in candidatas] == ["1"]


def test_reconciliar_publica_en_la_bandeja(tmp_path):
    entorno = _entorno(tmp_path, filas_csv=[_fila_csv()])
    resultado = reconciliar_decisiones_destino_no_resuelto(raiz_atlas=entorno["raiz"])
    assert resultado["decisiones_candidatas"] == 1
    assert resultado["decisiones_publicadas"] == 1


# ============================================================
# Aplicación -- REGISTRAR_DIRECCION
# ============================================================


def test_registrar_direccion_exitosa_calcula_ruta_y_aprende_la_relacion(tmp_path):
    entorno = _entorno(
        tmp_path, filas_csv=[_fila_csv()],
        clientes=[_cliente_dict()], obras=[_obra_dict()],
    )
    decision = detectar_decision_destino_no_resuelto(archivo="472037.jpeg", fila=_fila_csv())
    _publicar(entorno, decision)

    direccion = "AVENIDA APOQUINDO 1234"
    resultado = aplicar_decision_obra(
        raiz_atlas=entorno["raiz"], decision_id=decision["decision_id"],
        accion="REGISTRAR_DIRECCION", direccion_manual=direccion,
        proveedor_rutas=_proveedor_direccion_valida(direccion),
    )
    assert resultado["ok"] is True
    assert resultado["ruta_resuelta"] is True
    assert resultado["destino_id"]
    assert resultado["relacion_id"]

    fila = _leer_csv(entorno["dataset"])[0]
    assert fila["estado_ruta"] == "RUTA_CALCULADA"
    assert fila["distancia_km"] == "25.4"
    assert fila["duracion_min"] == "38.2"
    assert fila["despachar_a_crudo"] == direccion

    # Aprendizaje reutilizable: la relación obra<->destino queda CONFIRMADA
    # -- un documento futuro de la misma obra resuelve solo.
    catalogo_obras = CatalogoObrasDestinos(
        ruta=entorno["catalogos"] / "obras_destinos.json",
        ruta_clientes=entorno["catalogos"] / "clientes.json",
        ruta_destinos=entorno["catalogos"] / "destinos_maestros.json",
    )
    assert catalogo_obras.resolver_obra_destino_confirmada_global(
        nombre_obra="ING Y CONST FUNDAMENTA SPA"
    ) is not None

    # La decisión ya no está pendiente.
    bandeja = json.loads((entorno["actual"] / "decisiones_pendientes.json").read_text(encoding="utf-8"))
    assert bandeja["decisiones"] == []

    # Reporte regenerado -- Desktop puede mostrarlo de inmediato.
    assert (entorno["raiz"] / "operacion" / "actual" / "estado_operacion.json").exists()


def test_registrar_direccion_sigue_ambigua_no_inventa_una_ruta_pero_si_aprende_la_direccion(tmp_path):
    """Bloque R13 -- caso real 472099/472163 (VISTA CLARA 2351 CERRILLOS /
    VIA MORADA 6480 VITACURA): "¿es correcta esta dirección?" (confirmación
    humana) y "¿el proveedor externo puede geocodificarla?" (limitación de
    terceros) son dos preguntas distintas. Antes, el aprendizaje
    reutilizable (Destino + relación obra<->destino) sólo se persistía
    cuando la ruta SÍ se calculaba -- si el proveedor no podía ubicarla
    (ambigua, genérica, comuna contradicha), la confirmación humana se
    perdía por completo y la MISMA dirección en otra guía volvía a
    preguntarse desde cero. Ahora el aprendizaje persiste siempre que un
    humano confirma explícitamente, calcule o no la ruta -- km/tiempo
    siguen sin inventarse jamás (eso sigue exigiendo geocodificación real)."""
    entorno = _entorno(
        tmp_path, filas_csv=[_fila_csv()],
        clientes=[_cliente_dict()], obras=[_obra_dict()],
    )
    decision = detectar_decision_destino_no_resuelto(archivo="472037.jpeg", fila=_fila_csv())
    _publicar(entorno, decision)

    direccion = "DIRECCION AMBIGUA 1"
    resultado = aplicar_decision_obra(
        raiz_atlas=entorno["raiz"], decision_id=decision["decision_id"],
        accion="REGISTRAR_DIRECCION", direccion_manual=direccion,
        proveedor_rutas=_proveedor_direccion_ambigua(direccion),
    )
    assert resultado["ok"] is True
    assert resultado["ruta_resuelta"] is False
    # El aprendizaje reutilizable SÍ se persiste -- caso real corregido.
    assert resultado["destino_id"] is not None
    assert resultado["relacion_id"] is not None

    fila = _leer_csv(entorno["dataset"])[0]
    # Nunca inventa km/tiempo sin geocodificación real -- invariante intacto.
    assert fila["distancia_km"] == ""
    assert fila["duracion_min"] == ""
    # La dirección que escribió el humano igual queda registrada -- el
    # próximo reintento (revalidar_ruta_sin_destino_calculado_sin_ocr) la
    # usa sin tener que volver a pedirla.
    assert fila["despachar_a_crudo"] == direccion

    catalogo_obras = CatalogoObrasDestinos(
        ruta=entorno["catalogos"] / "obras_destinos.json",
        ruta_clientes=entorno["catalogos"] / "clientes.json",
        ruta_destinos=entorno["catalogos"] / "destinos_maestros.json",
    )
    # La relación obra<->destino queda CONFIRMADA globalmente -- otra guía
    # (misma u otra obra/cliente) con la misma obra ya no vuelve a
    # preguntar, aunque el proveedor de rutas siga sin poder geocodificarla.
    assert catalogo_obras.resolver_obra_destino_confirmada_global(
        nombre_obra="ING Y CONST FUNDAMENTA SPA"
    ) is not None


def test_registrar_direccion_confirmada_nunca_queda_degradada_por_etiqueta_vieja(tmp_path):
    """Bloque CONFIRMACIÓN D2 -- caso real 472044 (PUERTA DEL SOL 83 LAS
    CONDES): la fila ya traía, de un intento ANTERIOR, `direccion_entrega`
    degradada a nivel comuna ("Las Condes, RM, Chile") -- nadie la
    limpiaba al confirmar una dirección nueva. Javier confirma "PUERTA DEL
    SOL 83 LAS CONDES"; el proveedor sigue sin poder geocodificarla con
    confianza suficiente (limitación real, no inventa). El destino
    operacional (columna `direccion_entrega`, y el nombre/dirección del
    Destino recién CONFIRMADO en el catálogo) debe reflejar la dirección
    que Javier confirmó -- nunca la etiqueta vieja de comuna."""
    fila = _fila_csv(
        despachar_a_crudo="PUERTA DEL SOL 83", direccion_entrega="Las Condes, RM, Chile",
        localidad_entrega="Las Condes", region_entrega="Metropolitana",
        estado_ruta="REQUIERE_REVISION", motivo_ruta="GEOCODIFICACION_DEMASIADO_GENERICA",
    )
    entorno = _entorno(tmp_path, filas_csv=[fila], clientes=[_cliente_dict()], obras=[_obra_dict()])
    decision = detectar_decision_destino_no_resuelto(archivo="472037.jpeg", fila=fila)
    _publicar(entorno, decision)

    direccion = "PUERTA DEL SOL 83 LAS CONDES"
    resultado = aplicar_decision_obra(
        raiz_atlas=entorno["raiz"], decision_id=decision["decision_id"],
        accion="REGISTRAR_DIRECCION", direccion_manual=direccion,
        proveedor_rutas=_proveedor_confianza_insuficiente(direccion, etiqueta="Las Condes, RM, Chile"),
    )
    assert resultado["ok"] is True
    assert resultado["ruta_resuelta"] is False

    fila_final = _leer_csv(entorno["dataset"])[0]
    # La etiqueta degradada vieja ya no sobrevive -- un candidato
    # rechazado nunca se expone como destino operacional (Bloque F).
    assert fila_final["direccion_entrega"] == ""
    assert fila_final["despachar_a_crudo"] == direccion

    catalogo_obras = CatalogoObrasDestinos(
        ruta=entorno["catalogos"] / "obras_destinos.json",
        ruta_clientes=entorno["catalogos"] / "clientes.json",
        ruta_destinos=entorno["catalogos"] / "destinos_maestros.json",
    )
    relacion = catalogo_obras.resolver_obra_destino_confirmada_global(
        nombre_obra="ING Y CONST FUNDAMENTA SPA"
    )
    assert relacion is not None
    destino_confirmado = relacion.destino
    # El destino aprendido debe llevar la dirección CONFIRMADA por
    # Javier -- nunca la etiqueta de comuna descartada.
    assert destino_confirmado.direccion == direccion
    assert destino_confirmado.nombre_destino == direccion


def test_registrar_direccion_sin_texto_falla(tmp_path):
    entorno = _entorno(tmp_path, filas_csv=[_fila_csv()])
    decision = detectar_decision_destino_no_resuelto(archivo="472037.jpeg", fila=_fila_csv())
    _publicar(entorno, decision)
    try:
        aplicar_decision_obra(
            raiz_atlas=entorno["raiz"], decision_id=decision["decision_id"],
            accion="REGISTRAR_DIRECCION", direccion_manual="   ",
        )
        assert False, "debía lanzar"
    except ErrorAplicacionDecision:
        pass


def test_no_puedo_determinar_es_terminal_y_no_toca_el_dataset(tmp_path):
    entorno = _entorno(tmp_path, filas_csv=[_fila_csv()])
    decision = detectar_decision_destino_no_resuelto(archivo="472037.jpeg", fila=_fila_csv())
    _publicar(entorno, decision)
    fila_antes = _leer_csv(entorno["dataset"])[0]

    resultado = aplicar_decision_obra(
        raiz_atlas=entorno["raiz"], decision_id=decision["decision_id"], accion="NO_PUEDO_DETERMINAR",
    )
    assert resultado["ok"] is True
    fila_despues = _leer_csv(entorno["dataset"])[0]
    assert fila_antes == fila_despues

    # No vuelve a preguntar mientras la evidencia no cambie.
    candidatas = detectar_decisiones_destino_no_resuelto_sin_ocr(raiz_atlas=entorno["raiz"])
    assert len(candidatas) == 1  # la detección sigue viendo el problema...
    resultado_reconciliado = reconciliar_decisiones_destino_no_resuelto(raiz_atlas=entorno["raiz"])
    assert resultado_reconciliado["decisiones_publicadas"] == 0  # ...pero el ledger la filtra


def test_aplicacion_es_idempotente(tmp_path):
    entorno = _entorno(
        tmp_path, filas_csv=[_fila_csv()],
        clientes=[_cliente_dict()], obras=[_obra_dict()],
    )
    decision = detectar_decision_destino_no_resuelto(archivo="472037.jpeg", fila=_fila_csv())
    _publicar(entorno, decision)
    direccion = "AVENIDA APOQUINDO 1234"
    proveedor = _proveedor_direccion_valida(direccion)

    primero = aplicar_decision_obra(
        raiz_atlas=entorno["raiz"], decision_id=decision["decision_id"],
        accion="REGISTRAR_DIRECCION", direccion_manual=direccion, proveedor_rutas=proveedor,
    )
    assert primero.get("idempotente") is not True

    segundo = aplicar_decision_obra(
        raiz_atlas=entorno["raiz"], decision_id=decision["decision_id"],
        accion="REGISTRAR_DIRECCION", direccion_manual=direccion, proveedor_rutas=proveedor,
    )
    assert segundo["idempotente"] is True
