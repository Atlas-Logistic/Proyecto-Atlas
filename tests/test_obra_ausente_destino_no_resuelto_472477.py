"""Bloque OBRA AUSENTE -- cierre del hueco detectado en 472477 (PRODALAM
SA, transporte 0000354870): el documento nunca trajo texto de OBRA
DESTINO (`obra_destino="No encontrado"`, placeholder -- no un texto real
desconocido). Antes de este bloque, `DESTINO_NO_RESUELTO`/
`REGISTRAR_DIRECCION` sólo pedía la dirección; la obra quedaba
"No encontrado" para siempre en catálogo, sin ningún flujo (ni
`OBRA_DESCONOCIDA`, que se abstiene ante un campo genuinamente vacío) que
volviera a preguntarla.

Ahora: cuando `contexto.obra_ausente` es verdadero, `REGISTRAR_DIRECCION`
acepta `nombre_obra_manual` opcional y, si se entrega, registra/canoniza
la obra con el MISMO mecanismo seguro de `OBRA_DESCONOCIDA`/`REGISTRAR`
(`registrar_observacion` -- reutiliza si ya existe, nunca duplica), la
asocia al cliente correcto, registra la dirección y la relación
obra<->destino, y cierra la única tarjeta pendiente -- una sola
interacción humana, sin tarjeta huérfana posterior."""
from __future__ import annotations

import csv
import json

from atlas_core.aplicacion_decisiones import ErrorAplicacionDecision, aplicar_decision_obra
from atlas_core.catalogo_obras_destinos import CatalogoObrasDestinos
from atlas_core.catalogo_plantas import CatalogoPlantas, EstadoCalidad
from atlas_core.decisiones_pendientes import (
    detectar_decision_destino_contaminado_documental,
    detectar_decision_destino_no_resuelto,
    generar_artefacto,
)
from atlas_core.procesamiento_masivo import COLUMNAS
from atlas_core.rutas.modelos import (
    CandidatoGeocodificacion, Coordenadas, EstadoRuta, ResultadoGeocodificacion, ResultadoRuta,
)
from atlas_core.rutas.proveedor import ProveedorRutasSimulado

COORD_AZA_COLINA = Coordenadas(-70.665977, -33.137558)
FECHA = "10-08-2026"


def _fila_472477(**overrides):
    """Perfil real de 472477: cliente resuelto, obra genuinamente ausente
    (nunca extraída -- ni siquiera un texto OCR desconocido), destino
    contaminado (motivo documental, no de ruta -- misma vía que publica
    la tarjeta real en producción)."""
    fila = {c: "" for c in COLUMNAS}
    fila.update({
        "archivo": "472477.jpeg", "estado_procesamiento": "OK", "numero_guia": "472477",
        "numero_transporte": "0000354870", "fecha": FECHA,
        "cliente": "PRODALAM SA", "rut_cliente": "93772000-9", "obra_destino": "No encontrado",
        "indicador_revision": "REVISAR",
        "planta_origen_id": "planta-colina", "planta_origen_nombre": "AZA COLINA",
        "origen_determinado_por": "CONFIRMACION_HUMANA", "evidencia_origen": "DECISION_HUMANA:x",
        "despachar_a_crudo": "", "direccion_entrega": "", "estado_entrega": "",
        "distancia_km": "", "duracion_min": "", "proveedor_ruta": "",
        "estado_ruta": "REQUIERE_REVISION", "motivo_ruta": "",
        "motivos_revision_documento": "MATERIAL_AUSENTE | DESTINO_CONTAMINADO_POR_OTRA_SECCION",
        "estado_documental": "REQUIERE_REVISION", "estado_operacional": "REQUIERE_REVISION",
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
    for fila in filas_csv:
        if fila.get("planta_origen_id") == "planta-colina":
            fila["planta_origen_id"] = planta_colina.planta_id
    dataset = actual / "analisis_completo_guias.csv"
    _escribir_csv(dataset, filas_csv)
    return {"raiz": raiz, "catalogos": catalogos, "actual": actual, "dataset": dataset}


def _cliente_prodalam():
    return {
        "cliente_id": "cliente-prodalam", "razon_social": "PRODALAM SA",
        "nombre_normalizado": "PRODALAM", "nombre_comercial": "", "rut": "93772000-9",
        "aliases": [], "estado_calidad": "CONFIRMADO", "estado_vigencia": "ACTIVO", "fuente": "TEST",
        "observacion": "", "fecha_creacion": "2026-01-01T00:00:00+00:00", "fecha_modificacion": "2026-01-01T00:00:00+00:00",
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
                    Coordenadas(-72.10, -36.60), direccion + ", Chillán, Ñuble, Chile", 1.0,
                    "Chillán", "Ñuble",
                ),),
                "",
            )
        },
        resultado_ruta=ResultadoRuta(EstadoRuta.RUTA_CALCULADA, 410.0, 300.0, "SINTETICO"),
    )


# ============================================================
# 1. Detección -- señal `obra_ausente` en el contexto
# ============================================================


def test_deteccion_marca_obra_ausente_en_contexto():
    decision = detectar_decision_destino_contaminado_documental(
        archivo="472477.jpeg", fila=_fila_472477(),
    )
    assert decision is not None
    assert decision["contexto"]["obra_ausente"] is True
    assert decision["contexto"]["obra_canonica"] == "No encontrado"


def test_deteccion_no_marca_obra_ausente_cuando_hay_texto_real():
    """Regresión -- una obra con texto documental real (aunque no calce
    con catálogo) nunca activa esta señal."""
    fila = _fila_472477(obra_destino="EMPRESA CONST SIGRO", motivos_revision_documento="")
    fila["motivo_ruta"] = "DESTINO_SIN_DATO"
    decision = detectar_decision_destino_no_resuelto(archivo="472477.jpeg", fila=fila)
    assert decision is not None
    assert "obra_ausente" not in decision["contexto"]


# ============================================================
# 2. Aplicación -- registrar obra + dirección en una sola interacción
# ============================================================


def test_registrar_direccion_con_nombre_obra_manual_cierra_ambos_aprendizajes(tmp_path):
    entorno = _entorno(tmp_path, filas_csv=[_fila_472477()], clientes=[_cliente_prodalam()])
    decision = detectar_decision_destino_contaminado_documental(archivo="472477.jpeg", fila=_fila_472477())
    _publicar(entorno, decision)

    direccion = "PASAJE ISRAEL 1303"
    resultado = aplicar_decision_obra(
        raiz_atlas=entorno["raiz"], decision_id=decision["decision_id"],
        accion="REGISTRAR_DIRECCION", direccion_manual=direccion,
        nombre_obra_manual="PRODALAM BODEGA CHILLAN",
        proveedor_rutas=_proveedor_direccion_valida(direccion),
    )
    assert resultado["ok"] is True
    assert resultado["ruta_resuelta"] is True
    assert resultado["destino_id"]
    assert resultado["relacion_id"]
    assert resultado["obra_id"]

    fila = _leer_csv(entorno["dataset"])[0]
    assert fila["despachar_a_crudo"] == direccion
    assert fila["estado_ruta"] == "RUTA_CALCULADA"
    # La obra queda registrada en la propia fila -- nunca "No encontrado"
    # para siempre.
    assert fila["obra_destino"] == "PRODALAM BODEGA CHILLAN"

    catalogo_obras = CatalogoObrasDestinos(
        ruta=entorno["catalogos"] / "obras_destinos.json",
        ruta_clientes=entorno["catalogos"] / "clientes.json",
        ruta_destinos=entorno["catalogos"] / "destinos_maestros.json",
    )
    relacion_confirmada = catalogo_obras.resolver_obra_destino_confirmada_global(
        nombre_obra="PRODALAM BODEGA CHILLAN",
    )
    assert relacion_confirmada is not None

    # Nunca alía el placeholder "No encontrado" a la obra nueva.
    obra_registrada = next(
        o for o in catalogo_obras.listar_obras() if o.nombre_canonico == "PRODALAM BODEGA CHILLAN"
    )
    assert "No encontrado" not in obra_registrada.aliases_documentales
    assert obra_registrada.cliente_id == "cliente-prodalam"

    # Una sola decisión humana cierra AMBOS aprendizajes -- nunca queda
    # una segunda tarjeta huérfana por la misma obra/dirección.
    bandeja = json.loads((entorno["actual"] / "decisiones_pendientes.json").read_text(encoding="utf-8"))
    assert bandeja["decisiones"] == []


def test_reutiliza_obra_ya_existente_en_catalogo_en_vez_de_duplicar(tmp_path):
    obra_previa = {
        "obra_id": "obra-prodalam-chillan", "cliente_id": "cliente-prodalam",
        "nombre_canonico": "PRODALAM BODEGA CHILLAN", "nombre_normalizado": "PRODALAM BODEGA CHILLAN",
        "aliases_documentales": [], "estado": "OBSERVADA", "estado_vigencia": "ACTIVO", "evidencias": [],
        "fecha_creacion": "2026-01-01T00:00:00+00:00", "fecha_modificacion": "2026-01-01T00:00:00+00:00",
    }
    entorno = _entorno(
        tmp_path, filas_csv=[_fila_472477()], clientes=[_cliente_prodalam()], obras=[obra_previa],
    )
    decision = detectar_decision_destino_contaminado_documental(archivo="472477.jpeg", fila=_fila_472477())
    _publicar(entorno, decision)

    direccion = "PASAJE ISRAEL 1303"
    resultado = aplicar_decision_obra(
        raiz_atlas=entorno["raiz"], decision_id=decision["decision_id"],
        accion="REGISTRAR_DIRECCION", direccion_manual=direccion,
        nombre_obra_manual="PRODALAM BODEGA CHILLAN",
        proveedor_rutas=_proveedor_direccion_valida(direccion),
    )
    assert resultado["obra_id"] == "obra-prodalam-chillan"

    catalogo_obras = CatalogoObrasDestinos(
        ruta=entorno["catalogos"] / "obras_destinos.json",
        ruta_clientes=entorno["catalogos"] / "clientes.json",
        ruta_destinos=entorno["catalogos"] / "destinos_maestros.json",
    )
    obras_con_ese_nombre = [
        o for o in catalogo_obras.listar_obras() if o.nombre_canonico == "PRODALAM BODEGA CHILLAN"
    ]
    assert len(obras_con_ese_nombre) == 1  # nunca duplica


def test_registrar_direccion_sin_nombre_obra_manual_mantiene_comportamiento_previo(tmp_path):
    """Backward-compat -- `nombre_obra_manual` es opcional: sin él, la
    dirección se registra igual que antes y la obra sigue sin catalogar
    (ningún dato se inventa)."""
    entorno = _entorno(tmp_path, filas_csv=[_fila_472477()], clientes=[_cliente_prodalam()])
    decision = detectar_decision_destino_contaminado_documental(archivo="472477.jpeg", fila=_fila_472477())
    _publicar(entorno, decision)

    direccion = "PASAJE ISRAEL 1303"
    resultado = aplicar_decision_obra(
        raiz_atlas=entorno["raiz"], decision_id=decision["decision_id"],
        accion="REGISTRAR_DIRECCION", direccion_manual=direccion,
        proveedor_rutas=_proveedor_direccion_valida(direccion),
    )
    assert resultado["ok"] is True
    assert resultado["obra_id"] is None

    fila = _leer_csv(entorno["dataset"])[0]
    assert fila["despachar_a_crudo"] == direccion
    assert fila["obra_destino"] == "No encontrado"  # nunca se inventa


def test_nombre_obra_manual_rechazado_si_la_obra_no_esta_ausente(tmp_path):
    """Criterio 7 -- nunca se relaja para un texto de obra REAL (aunque no
    calce con catálogo): ese caso sigue siendo terreno de OBRA_DESCONOCIDA."""
    fila = _fila_472477(obra_destino="EMPRESA CONST SIGRO", motivos_revision_documento="")
    fila["motivo_ruta"] = "DESTINO_SIN_DATO"
    entorno = _entorno(tmp_path, filas_csv=[fila], clientes=[_cliente_prodalam()])
    decision = detectar_decision_destino_no_resuelto(archivo="472477.jpeg", fila=fila)
    assert "obra_ausente" not in decision["contexto"]
    _publicar(entorno, decision)

    try:
        aplicar_decision_obra(
            raiz_atlas=entorno["raiz"], decision_id=decision["decision_id"],
            accion="REGISTRAR_DIRECCION", direccion_manual="ALGUNA DIRECCION 100",
            nombre_obra_manual="OTRO NOMBRE CUALQUIERA",
            proveedor_rutas=_proveedor_direccion_valida("ALGUNA DIRECCION 100"),
        )
        assert False, "debía rechazar nombre_obra_manual cuando la obra no está ausente"
    except ErrorAplicacionDecision:
        pass
