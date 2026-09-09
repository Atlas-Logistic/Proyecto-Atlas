"""Bloque CIERRE QUIRÚRGICO DE REVISIONES -- dos huecos reales de Revisión
de Atlas antes de operación real:

CASO 1 (464784 / URUGUAY 15): tras REGISTRAR_DIRECCION, el reintento
inmediato puede conservar un motivo geográfico real y estable
(`GEOCODIFICACION_NUMERO_INCOMPATIBLE`). La respuesta humana es terminal
para esa misma pregunta: la tarjeta no reaparece; el fallo técnico queda
explícito en la fila, sin inventar ruta.

CASO 2 (464717 / AMERICAN SCREW CHILE SPA): una tarjeta
`DESTINO_NO_RESUELTO` nacida de "Corregir destino"
(`CORRECCION_MANUAL_LOGISTICA`) no la reconciliaba ninguna vía -- quedaba
viva para siempre aunque el problema real se resolviera después. Ahora
se cierra cuando la fila queda enteramente limpia y la entrega es a la
sede del propio cliente (corroboración positiva del destino).

CASO 3: un `INCOMPLETO_TECNICO` que obtiene ruta, o que se convierte en
revisión humana, deja de mostrarse como pendiente técnico -- circuito ya
correcto, aquí demostrado y protegido.
"""

from __future__ import annotations

import csv
import json

from atlas_core.aplicacion_decisiones import aplicar_decision_obra
from atlas_core.catalogo_clientes import normalizar_nombre_cliente
from atlas_core.catalogo_obras_destinos import normalizar_nombre_obra
from atlas_core.catalogo_plantas import CatalogoPlantas, EstadoCalidad
from atlas_core.decisiones_pendientes import (
    detectar_decision_destino_no_resuelto,
    generar_artefacto,
    regenerar_decisiones_persistidas,
)
from atlas_core.procesamiento_masivo import COLUMNAS
from atlas_core.reconciliacion_estado_derivado import (
    _falta_tarjeta_destino_accionable,
    _pendientes_ruta,
)
from atlas_core.rutas.modelos import (
    CandidatoGeocodificacion,
    Coordenadas,
    EstadoRuta,
    ResultadoGeocodificacion,
    ResultadoRuta,
)
from atlas_core.rutas.proveedor import ProveedorRutasSimulado

COORD_PLANTA = Coordenadas(-70.665977, -33.137558)
FECHA = "10-08-2026"


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def _fila(**overrides):
    fila = {c: "" for c in COLUMNAS}
    fila.update({
        "archivo": "464784.jpeg", "estado_procesamiento": "OK", "numero_guia": "464784",
        "numero_transporte": "0000353303", "fecha": FECHA, "chofer": "CHOFER TEST",
        "cliente": "EASY RETAIL SA", "obra_destino": "CONSTRUCTORA ALTIUS SPA",
        "patente_tracto": "BPHR67", "indicador_revision": "OK",
        "estado_documental": "OK", "estado_operacional": "REQUIERE_REVISION",
        "planta_origen_id": "planta-1", "planta_origen_nombre": "PLANTA TEST",
        "origen_determinado_por": "CONFIRMACION_HUMANA", "evidencia_origen": "DECISION_HUMANA:x",
        "despachar_a_crudo": "URUGUAY 15", "direccion_entrega": "", "estado_entrega": "REVISAR",
        "distancia_km": "", "duracion_min": "", "proveedor_ruta": "",
        "estado_ruta": "REQUIERE_REVISION", "motivo_ruta": "GEOCODIFICACION_CONTRADICE_COMUNA_DOCUMENTAL: La Cisterna != Temuco",
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


def _cliente(nombre, cliente_id):
    return {
        "cliente_id": cliente_id, "razon_social": nombre,
        "nombre_normalizado": normalizar_nombre_cliente(nombre),
        "nombre_comercial": "", "rut": "76086428-5", "aliases": [], "estado_calidad": "CONFIRMADO",
        "estado_vigencia": "ACTIVO", "fuente": "TEST", "observacion": "",
        "fecha_creacion": "2026-01-01T00:00:00+00:00", "fecha_modificacion": "2026-01-01T00:00:00+00:00",
    }


def _obra(nombre, obra_id, cliente_id):
    return {
        "obra_id": obra_id, "cliente_id": cliente_id, "nombre_canonico": nombre,
        "nombre_normalizado": normalizar_nombre_obra(nombre), "aliases_documentales": [], "estado": "OBSERVADA",
        "estado_vigencia": "ACTIVO", "evidencias": [],
        "fecha_creacion": "2026-01-01T00:00:00+00:00", "fecha_modificacion": "2026-01-01T00:00:00+00:00",
    }


def _entorno(tmp_path, filas, *, obras=None, clientes=None):
    # Por defecto se siembra la obra/cliente de `_fila` (CONSTRUCTORA
    # ALTIUS SPA / EASY RETAIL SA) para que `aplicar_decision_obra`/
    # REGISTRAR_DIRECCION cree una relación obra<->destino CONFIRMADA real
    # (el escenario 464784).
    if obras is None:
        obras = [_obra("CONSTRUCTORA ALTIUS SPA", "obra-altius", "cli-easy")]
    if clientes is None:
        clientes = [_cliente("EASY RETAIL SA", "cli-easy")]
    raiz = tmp_path / "Atlas"
    catalogos = raiz / "catalogos_privados"
    actual = raiz / "operacion" / "actual"
    catalogos.mkdir(parents=True)
    actual.mkdir(parents=True)
    for nombre, contenido in {
        "clientes.json": {"version_formato": 1, "clientes": list(clientes)},
        "empresas.json": {},
        "vehiculos.json": {"version": 1, "vehiculos": []},
        "obras_destinos.json": {"version_formato": 1, "obras": list(obras), "relaciones": []},
        "destinos_maestros.json": {"version_formato": 1, "destinos": []},
    }.items():
        (catalogos / nombre).write_text(json.dumps(contenido), encoding="utf-8")
    planta = CatalogoPlantas(catalogos / "plantas.json").crear(
        nombre="PLANTA TEST", pais="CHILE", fuente="TEST", direccion="AV 1", comuna="COLINA",
        region="RM", latitud=COORD_PLANTA.latitud, longitud=COORD_PLANTA.longitud,
        estado_calidad=EstadoCalidad.CONFIRMADA,
    )
    for fila in filas:
        if fila.get("planta_origen_id") == "planta-1":
            fila["planta_origen_id"] = planta.planta_id
    dataset = actual / "analisis_completo_guias.csv"
    _escribir_csv(dataset, filas)
    return {"raiz": raiz, "catalogos": catalogos, "actual": actual, "dataset": dataset, "planta_id": planta.planta_id}


def _publicar(entorno, *decisiones):
    generar_artefacto(
        ruta_dataset=entorno["dataset"], carpeta_catalogos=entorno["catalogos"],
        decisiones=list(decisiones), ruta_salida=entorno["actual"] / "decisiones_pendientes.json",
    )


def _bandeja(entorno):
    return json.loads((entorno["actual"] / "decisiones_pendientes.json").read_text(encoding="utf-8"))["decisiones"]


class _ProveedorFijo:
    """Devuelve el MISMO candidato geocodificado para cualquier consulta
    (en estas pruebas sólo se geocodifica una dirección) -- la validación
    real de comuna/número la aplica después `resolver_destino_entrega_
    validado`, que es justo lo que se quiere ejercitar."""

    def __init__(self, *, etiqueta, comuna, region="Metropolitana",
                 estado_geo=EstadoRuta.REQUIERE_REVISION, ruta=EstadoRuta.RUTA_CALCULADA,
                 km=25.4, minutos=38.2):
        self._geo = ResultadoGeocodificacion(
            estado_geo,
            (CandidatoGeocodificacion(Coordenadas(-70.66, -33.50), etiqueta, 1.0, comuna, region),),
            "",
        )
        self.resultado_ruta = ResultadoRuta(ruta, km, minutos, "SINTETICO")
        self.nombre = "simulado"
        self.version = "1"
        self.llamadas_geocodificacion = 0
        self.llamadas_ruta = 0

    def geocodificar(self, direccion):
        self.llamadas_geocodificacion += 1
        return self._geo

    def geocodificar_estructurado(self, direccion, contexto):
        return self.geocodificar(direccion)

    def calcular_ruta(self, origen, destino, perfil):
        self.llamadas_ruta += 1
        return self.resultado_ruta


def _proveedor(direccion, *, etiqueta, comuna, **kw):
    return _ProveedorFijo(etiqueta=etiqueta, comuna=comuna, **kw)


def _decision_registrada(entorno, fila):
    """Publica DESTINO_NO_RESUELTO y devuelve su decision_id."""
    decision = detectar_decision_destino_no_resuelto(
        archivo=str(fila.get("archivo")), fila=fila, carpeta_catalogos=entorno["catalogos"],
    )
    assert decision is not None
    _publicar(entorno, decision)
    return decision["decision_id"]


# ==========================================================================
# CASO 1 -- decisión humana de dirección: reintento inmediato
# ==========================================================================

# 1. decisión humana de dirección dispara reintento inmediato de geocod/routing
# 4. ruta válida posterior actualiza estado/km/tiempo

def test_registrar_direccion_dispara_reintento_inmediato_y_ruta_valida_cierra_la_revision(tmp_path):
    entorno = _entorno(tmp_path, [_fila()])
    decision_id = _decision_registrada(entorno, _fila())

    resultado = aplicar_decision_obra(
        raiz_atlas=entorno["raiz"], decision_id=decision_id, accion="REGISTRAR_DIRECCION",
        direccion_manual="URUGUAY 15", comuna_manual="LA CISTERNA",
        proveedor_rutas=_proveedor(
            "URUGUAY 15", etiqueta="Uruguay 15, La Cisterna, RM, Chile", comuna="La Cisterna",
        ),
    )
    assert resultado["ok"] is True
    # 4 -- la ruta se resolvió en el MISMO ciclo y actualizó km/tiempo/estado.
    assert resultado["ruta_resuelta"] is True
    fila = _leer_csv(entorno["dataset"])[0]
    assert fila["estado_ruta"] == "RUTA_CALCULADA"
    assert fila["distancia_km"] == "25.4"
    assert fila["duracion_min"] == "38.2"
    assert fila["despachar_a_crudo"] == "URUGUAY 15"
    # la revisión queda cerrada
    assert _bandeja(entorno) == []


# 2. resultado geográfico anterior incompatible no bloquea para siempre la
#    dirección humana  (se persiste el aprendizaje aunque el proveedor falle)
# 3. sigue rechazándose un candidato que contradiga la comuna humana

def test_comuna_humana_rechaza_candidato_contradictorio_pero_persiste_la_direccion(tmp_path):
    entorno = _entorno(tmp_path, [_fila()])
    decision_id = _decision_registrada(entorno, _fila())

    resultado = aplicar_decision_obra(
        raiz_atlas=entorno["raiz"], decision_id=decision_id, accion="REGISTRAR_DIRECCION",
        direccion_manual="URUGUAY 15", comuna_manual="LA CISTERNA",
        # El proveedor insiste en Temuco -- contradice la comuna humana.
        proveedor_rutas=_proveedor("URUGUAY 15", etiqueta="Uruguay 15, Temuco, Araucania, Chile", comuna="Temuco"),
    )
    assert resultado["ok"] is True
    # 3 -- nunca se acepta Temuco para LA CISTERNA: la ruta NO se resuelve.
    assert resultado["ruta_resuelta"] is False
    fila = _leer_csv(entorno["dataset"])[0]
    assert fila["estado_ruta"] != "RUTA_CALCULADA"
    assert fila["distancia_km"] == "" and fila["duracion_min"] == ""
    # 2 -- la dirección/relación humana SÍ queda aprendida (no se pierde por
    # el fallo del proveedor): el próximo reintento la reutiliza.
    assert resultado["destino_id"] is not None
    assert resultado["relacion_id"] is not None
    assert fila["despachar_a_crudo"] == "URUGUAY 15"


# 8. La confirmación humana de dirección es terminal para esa pregunta,
#    aun si geocodificación/routing siguen bloqueados. El estado técnico
#    permanece en la fila, sin ruta inventada ni nueva tarjeta humana.

def test_tras_registrar_direccion_sin_ruta_no_reabre_la_misma_tarjeta_y_conserva_fallo_tecnico(tmp_path):
    fila_comuna_ok_numero_no = _fila(
        motivo_ruta="GEOCODIFICACION_NUMERO_INCOMPATIBLE: 15 != 1545",
    )
    entorno = _entorno(tmp_path, [fila_comuna_ok_numero_no])
    decision_id = _decision_registrada(entorno, fila_comuna_ok_numero_no)

    # Javier registra la dirección; el proveedor sólo encuentra "1545"
    # (número incompatible) -- confirma el Destino en catálogo pero NO rutea.
    resultado = aplicar_decision_obra(
        raiz_atlas=entorno["raiz"], decision_id=decision_id, accion="REGISTRAR_DIRECCION",
        direccion_manual="URUGUAY 15", comuna_manual="LA CISTERNA",
        proveedor_rutas=_proveedor("URUGUAY 15", etiqueta="Uruguay 1545, La Cisterna, RM, Chile", comuna="La Cisterna"),
    )
    assert resultado["ok"] is True
    assert resultado["ruta_resuelta"] is False
    assert resultado["destino_id"] is not None  # Destino CONFIRMADO creado, sin lat/lon

    dataset = entorno["dataset"]
    decisiones = entorno["actual"] / "decisiones_pendientes.json"

    # La pregunta ya fue respondida por Javier: aunque el proveedor no
    # encuentre un punto utilizable, no vuelve a pedir la misma dirección.
    fresca = detectar_decision_destino_no_resuelto(
        archivo="464784.jpeg", fila=_leer_csv(dataset)[0], carpeta_catalogos=entorno["catalogos"],
    )
    assert fresca is not None
    fila_tras = _leer_csv(dataset)[0]
    assert fila_tras["estado_ruta"] != "RUTA_CALCULADA"
    assert fila_tras["motivo_ruta"].startswith("GEOCODIFICACION_NUMERO_INCOMPATIBLE")
    assert fila_tras["distancia_km"] == "" and fila_tras["duracion_min"] == ""
    assert fila_tras["direccion_entrega"] == "URUGUAY 15"
    assert fila_tras["localidad_entrega"] == "LA CISTERNA"

    _publicar(entorno, fresca)
    assert _bandeja(entorno) == []

    correccion_posterior = dict(fresca)
    correccion_posterior["decision_id"] = "correccion-posterior-464784"
    _publicar(entorno, correccion_posterior)
    assert [d["decision_id"] for d in _bandeja(entorno)] == ["correccion-posterior-464784"]


def test_tarjeta_de_guia_hermana_se_suprime_aunque_su_fila_siga_en_callejon(tmp_path):
    """Bloque GEOGRAFÍA 2B -- una dirección que un humano YA confirmó
    (REGISTRAR_DIRECCION aplicado) nunca vuelve a preguntarse, aunque el
    geocodificador siga sin ubicarla: la tarjeta se suprime tanto para la
    guía que el humano respondió (464784) como para una guía hermana
    (999999). El fallo de ruteo deja de ser una "tarjeta falsa" y pasa a
    verse como pendiente técnico explícito (`estado_espera=
    ESPERANDO_EVIDENCIA_NUEVA` en `pendientes_tecnicos.json`)."""
    fila_a = _fila(archivo="464784.jpeg", numero_guia="464784", despachar_a_crudo="URUGUAY 15",
                   motivo_ruta="GEOCODIFICACION_NUMERO_INCOMPATIBLE: 15 != 1545")
    fila_b = _fila(archivo="999999.jpeg", numero_guia="999999", numero_transporte="0000353999",
                   despachar_a_crudo="URUGUAY 15",
                   motivo_ruta="GEOCODIFICACION_CONTRADICE_COMUNA_DOCUMENTAL: La Cisterna != Temuco")
    entorno = _entorno(tmp_path, [fila_a, fila_b])
    id_a = _decision_registrada(entorno, fila_a)
    decision_b = detectar_decision_destino_no_resuelto(
        archivo="999999.jpeg", fila=fila_b, carpeta_catalogos=entorno["catalogos"],
    )
    _publicar(entorno, detectar_decision_destino_no_resuelto(archivo="464784.jpeg", fila=fila_a, carpeta_catalogos=entorno["catalogos"]), decision_b)

    aplicar_decision_obra(
        raiz_atlas=entorno["raiz"], decision_id=id_a, accion="REGISTRAR_DIRECCION",
        direccion_manual="URUGUAY 15", comuna_manual="LA CISTERNA",
        proveedor_rutas=_proveedor("URUGUAY 15", etiqueta="Uruguay 1545, La Cisterna, RM, Chile", comuna="La Cisterna"),
    )

    dataset = entorno["dataset"]
    frescas = [
        detectar_decision_destino_no_resuelto(archivo=f["archivo"], fila=f, carpeta_catalogos=entorno["catalogos"])
        for f in _leer_csv(dataset)
    ]
    frescas = [d for d in frescas if d is not None]
    restantes = regenerar_decisiones_persistidas(
        decisiones=frescas, carpeta_catalogos=entorno["catalogos"], ruta_dataset=dataset,
    )
    guias = {d["documento"]["numero_guia"] for d in restantes}
    assert "464784" not in guias    # 2B: el humano ya confirmó -> no se re-pregunta
    assert "999999" not in guias    # guía hermana -> R13 la suprime


# ==========================================================================
# CASO 2 -- decisión pendiente obsoleta de "Corregir destino"
# ==========================================================================

def _tarjeta_correccion_manual(guia="464717", *, cliente, obra):
    return {
        "decision_id": f"cm-{guia}",
        "estado": "PENDIENTE",
        "tipo": "DESTINO_NO_RESUELTO",
        "entidad": "DESTINO",
        "documento": {"archivo": f"{guia}.jpeg", "numero_guia": guia, "numero_transporte": "0000353062"},
        "campo": "despachar_a_crudo",
        "valor_documental": "CAMINO A MELIPILLA 10800 SANTIAGO MAIPU",
        "valor_normalizado": "",
        "identidad_resuelta": None,
        "contexto": {"obra_canonica": obra, "cliente_canonico": cliente},
        "candidatos": [],
        "motivos": ["CORRECCION_MANUAL_LOGISTICA"],
        "evidencias": [{"tipo": "RUTA_BLOQUEADA", "motivo_ruta": "", "origen_pregunta": "CORRECCION_MANUAL_LOGISTICA"}],
        "acciones_permitidas": ["REGISTRAR_DIRECCION", "NO_PUEDO_DETERMINAR", "POSPONER"],
    }


# 5. decisión pendiente obsoleta se cierra cuando el problema ya está resuelto

def test_correccion_manual_logistica_se_cierra_cuando_la_entrega_es_a_sede_propia_y_la_fila_esta_limpia(tmp_path):
    fila = _fila(
        archivo="464717.jpeg", numero_guia="464717", numero_transporte="0000353062",
        cliente="AMERICAN SCREW CHILE SPA", obra_destino="AMERICAN SCREW CHILE SPA",
        despachar_a_crudo="CAMINO A MELIPILLA 10800 SANTIAGO MAIPU",
        indicador_revision="OK", estado_documental="OK", estado_operacional="OK",
        estado_entrega="RESUELTO", estado_ruta="RUTA_CALCULADA", motivo_ruta="",
        distancia_km="35.3246", duracion_min="49.43", motivos_revision_documento="",
    )
    entorno = _entorno(tmp_path, [fila])
    tarjeta = _tarjeta_correccion_manual(cliente="AMERICAN SCREW CHILE SPA", obra="AMERICAN SCREW CHILE SPA")

    restantes = regenerar_decisiones_persistidas(
        decisiones=[tarjeta], carpeta_catalogos=entorno["catalogos"], ruta_dataset=entorno["dataset"],
    )
    assert restantes == []  # la tarjeta obsoleta se retira


def test_destino_resuelto_con_ruta_retira_tarjeta_contaminada_y_conserva_ocr_en_la_entrada(tmp_path):
    ocr = "14293816-2 FECHA LLEGADA 17-08-2026"
    fila = _fila(
        archivo="464836.jpeg", numero_guia="464836", numero_transporte="0000353361",
        cliente="AMERICAN SCREW CHILE SPA", obra_destino="AMERICAN SCREW CHILE SPA",
        despachar_a_crudo=ocr, direccion_entrega="CAMINO A MELIPILLA 10800",
        indicador_revision="OK", estado_operacional="OK", estado_ruta="RUTA_CALCULADA",
        distancia_km="35.3246", duracion_min="49.43", motivos_revision_documento="",
    )
    entorno = _entorno(tmp_path, [fila])
    tarjeta = _tarjeta_correccion_manual("464836", cliente="AMERICAN SCREW CHILE SPA", obra="AMERICAN SCREW CHILE SPA")
    tarjeta["valor_documental"] = ocr
    tarjeta["motivos"] = ["DESTINO_CONTAMINADO_POR_OTRA_SECCION"]
    restantes = regenerar_decisiones_persistidas(
        decisiones=[tarjeta], carpeta_catalogos=entorno["catalogos"], ruta_dataset=entorno["dataset"],
    )
    assert restantes == []
    assert tarjeta["valor_documental"] == ocr


def test_dos_tarjetas_destino_equivalentes_se_fusionan_y_conflicto_activo_permanece(tmp_path):
    fila = _fila(
        archivo="464836.jpeg", numero_guia="464836", numero_transporte="0000353361",
        despachar_a_crudo="OCR CONTAMINADO", indicador_revision="REVISAR",
        estado_operacional="REQUIERE_REVISION", estado_ruta="REQUIERE_REVISION",
        motivo_ruta="GEOCODIFICACION_DIRECCION_NO_ENCONTRADA",
    )
    entorno = _entorno(tmp_path, [fila])
    primera = _tarjeta_correccion_manual("464836", cliente="CLIENTE", obra="OBRA")
    primera.update({"valor_documental": "OCR CONTAMINADO", "motivos": ["DESTINO_CONTAMINADO_POR_OTRA_SECCION"]})
    segunda = dict(primera); segunda["decision_id"] = "otra"; segunda["motivos"] = ["GEOCODIFICACION_DIRECCION_NO_ENCONTRADA"]
    restantes = regenerar_decisiones_persistidas(
        decisiones=[primera, segunda], carpeta_catalogos=entorno["catalogos"], ruta_dataset=entorno["dataset"],
    )
    assert len(restantes) == 1
    assert set(restantes[0]["motivos"]) == {"DESTINO_CONTAMINADO_POR_OTRA_SECCION", "GEOCODIFICACION_DIRECCION_NO_ENCONTRADA"}


# 6. NO se cierra una decisión cuyo problema siga vigente

def test_correccion_manual_logistica_no_se_cierra_si_la_ruta_sigue_sin_calcularse(tmp_path):
    fila = _fila(
        archivo="464717.jpeg", numero_guia="464717", numero_transporte="0000353062",
        cliente="AMERICAN SCREW CHILE SPA", obra_destino="AMERICAN SCREW CHILE SPA",
        indicador_revision="OK", estado_operacional="REQUIERE_REVISION",
        estado_ruta="REQUIERE_REVISION", motivo_ruta="GEOCODIFICACION_DEMASIADO_GENERICA",
    )
    entorno = _entorno(tmp_path, [fila])
    tarjeta = _tarjeta_correccion_manual(cliente="AMERICAN SCREW CHILE SPA", obra="AMERICAN SCREW CHILE SPA")
    restantes = regenerar_decisiones_persistidas(
        decisiones=[tarjeta], carpeta_catalogos=entorno["catalogos"], ruta_dataset=entorno["dataset"],
    )
    assert [d["decision_id"] for d in restantes] == ["cm-464717"]


def test_correccion_manual_logistica_no_se_cierra_si_la_entrega_no_es_a_sede_propia(tmp_path):
    """Ruta calculada pero destino sólo corroborado por geocode (obra !=
    cliente) -- podría seguir siendo el destino equivocado que Javier vino
    a corregir. La tarjeta se conserva hasta que él actúe."""
    fila = _fila(
        archivo="464717.jpeg", numero_guia="464717", numero_transporte="0000353062",
        cliente="EASY RETAIL SA", obra_destino="CONSTRUCTORA ALTIUS SPA",
        indicador_revision="OK", estado_documental="OK", estado_operacional="OK",
        estado_ruta="RUTA_CALCULADA", motivo_ruta="", distancia_km="10", duracion_min="15",
    )
    entorno = _entorno(tmp_path, [fila])
    tarjeta = _tarjeta_correccion_manual(cliente="EASY RETAIL SA", obra="CONSTRUCTORA ALTIUS SPA")
    restantes = regenerar_decisiones_persistidas(
        decisiones=[tarjeta], carpeta_catalogos=entorno["catalogos"], ruta_dataset=entorno["dataset"],
    )
    assert [d["decision_id"] for d in restantes] == ["cm-464717"]


# ==========================================================================
# CASO 3 -- pendientes técnicos resueltos / convertidos
# ==========================================================================

# 7. INCOMPLETO_TECNICO resuelto deja de mostrarse como pendiente

def test_pendiente_tecnico_con_ruta_calculada_desaparece_de_la_cola(tmp_path):
    fila_ok = _fila(
        numero_guia="A1", estado_ruta="RUTA_CALCULADA", motivo_ruta="", distancia_km="10",
        duracion_min="12", indicador_revision="OK",
    )
    fila_pendiente = _fila(
        numero_guia="A2", estado_ruta="REQUIERE_REVISION", motivo_ruta="COORDENADA_NO_CONFIRMADA(2)",
        despachar_a_crudo="ALGUNA CALLE 5", indicador_revision="OK",
    )
    entorno = _entorno(tmp_path, [fila_ok, fila_pendiente])
    decisiones = entorno["actual"] / "decisiones_pendientes.json"
    decisiones.write_text(json.dumps({"decisiones": []}), encoding="utf-8")

    guias = [f["numero_guia"] for f in _pendientes_ruta(entorno["dataset"], decisiones)]
    assert "A1" not in guias           # ruta calculada -> fuera de la cola
    assert "A2" in guias               # sin ruta -> sigue en la cola (reintentable)


def test_falta_tarjeta_destino_dispara_y_luego_es_idempotente(tmp_path):
    """El disparador `_falta_tarjeta_destino_accionable`: una fila que ya es
    un callejón de DESTINO pero sin tarjeta accionable hace entrar al
    bloque de reconciliación; una vez publicada la tarjeta (la guía pasa a
    ser "humana"), deja de dispararse -- idempotente."""
    fila = _fila(
        numero_guia="464784", estado_ruta="REQUIERE_REVISION",
        motivo_ruta="GEOCODIFICACION_NUMERO_INCOMPATIBLE: 15 != 1545",
        despachar_a_crudo="URUGUAY 15", indicador_revision="OK",
    )
    entorno = _entorno(tmp_path, [fila])
    decisiones = entorno["actual"] / "decisiones_pendientes.json"
    decisiones.write_text(json.dumps({"decisiones": []}), encoding="utf-8")

    assert _falta_tarjeta_destino_accionable(entorno["dataset"], decisiones) is True

    _publicar(entorno, detectar_decision_destino_no_resuelto(
        archivo="464784.jpeg", fila=fila, carpeta_catalogos=entorno["catalogos"],
    ))
    assert _falta_tarjeta_destino_accionable(entorno["dataset"], decisiones) is False


def test_falta_tarjeta_destino_no_dispara_para_una_guia_ya_terminada_por_humano(tmp_path):
    """Si Javier ya cerró la tarjeta de destino de forma TERMINAL
    (`NO_PUEDO_DETERMINAR` en el ledger), el disparador NO debe volver a
    pedir una reconciliación completa en cada carga -- nunca podría
    publicar nada (bucle inútil)."""
    fila = _fila(
        numero_guia="464784", estado_ruta="REQUIERE_REVISION",
        motivo_ruta="GEOCODIFICACION_NUMERO_INCOMPATIBLE: 15 != 1545",
        despachar_a_crudo="URUGUAY 15", indicador_revision="OK",
    )
    entorno = _entorno(tmp_path, [fila])
    (entorno["actual"] / "decisiones_pendientes.json").write_text(json.dumps({"decisiones": []}), encoding="utf-8")
    (entorno["actual"] / "decisiones_aplicadas.json").write_text(json.dumps({
        "schema_version": 1,
        "aplicaciones": [{
            "tipo": "DESTINO_NO_RESUELTO", "accion": "NO_PUEDO_DETERMINAR",
            "documento": {"numero_guia": "464784"},
        }],
    }), encoding="utf-8")
    assert _falta_tarjeta_destino_accionable(
        entorno["dataset"], entorno["actual"] / "decisiones_pendientes.json"
    ) is False


# 9. refresh / reconciliación repetida es idempotente

def test_regenerar_decisiones_persistidas_es_idempotente(tmp_path):
    fila_784 = _fila(
        archivo="464784.jpeg", numero_guia="464784",
        motivo_ruta="GEOCODIFICACION_NUMERO_INCOMPATIBLE: 15 != 1545",
    )
    fila_717 = _fila(
        archivo="464717.jpeg", numero_guia="464717", numero_transporte="0000353062",
        cliente="AMERICAN SCREW CHILE SPA", obra_destino="AMERICAN SCREW CHILE SPA",
        indicador_revision="OK", estado_documental="OK", estado_operacional="OK",
        estado_ruta="RUTA_CALCULADA", motivo_ruta="", distancia_km="35", duracion_min="49",
    )
    entorno = _entorno(tmp_path, [fila_784, fila_717])
    id_784 = _decision_registrada(entorno, fila_784)
    aplicar_decision_obra(
        raiz_atlas=entorno["raiz"], decision_id=id_784, accion="REGISTRAR_DIRECCION",
        direccion_manual="URUGUAY 15", comuna_manual="LA CISTERNA",
        proveedor_rutas=_proveedor("URUGUAY 15", etiqueta="Uruguay 1545, La Cisterna, RM, Chile", comuna="La Cisterna"),
    )
    tarjeta_cm = _tarjeta_correccion_manual(cliente="AMERICAN SCREW CHILE SPA", obra="AMERICAN SCREW CHILE SPA")
    frescas = [
        d for d in (
            detectar_decision_destino_no_resuelto(archivo=f["archivo"], fila=f, carpeta_catalogos=entorno["catalogos"])
            for f in _leer_csv(entorno["dataset"])
        ) if d is not None
    ]
    entrada = [*frescas, tarjeta_cm]

    primera = regenerar_decisiones_persistidas(
        decisiones=entrada, carpeta_catalogos=entorno["catalogos"], ruta_dataset=entorno["dataset"],
    )
    segunda = regenerar_decisiones_persistidas(
        decisiones=entrada, carpeta_catalogos=entorno["catalogos"], ruta_dataset=entorno["dataset"],
    )
    tercera = regenerar_decisiones_persistidas(
        decisiones=primera, carpeta_catalogos=entorno["catalogos"], ruta_dataset=entorno["dataset"],
    )
    ids_1 = sorted(d["decision_id"] for d in primera)
    assert ids_1 == sorted(d["decision_id"] for d in segunda)
    assert ids_1 == sorted(d["decision_id"] for d in tercera)
    # 2B: 464784 ya fue confirmada por un humano -> su tarjeta NO se
    # re-publica (queda ESPERANDO_EVIDENCIA_NUEVA); la CORRECCION_MANUAL
    # obsoleta también se retira. La reconciliación repetida es idempotente.
    guias = {d["documento"]["numero_guia"] for d in primera}
    assert "464784" not in guias
    assert "cm-464717" not in {d["decision_id"] for d in primera}
