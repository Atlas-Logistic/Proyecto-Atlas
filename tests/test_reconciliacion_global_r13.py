"""Bloque R13 -- reconciliación global post-aprendizaje, general (nunca
hardcodeada por guía/cliente/obra/dirección).

Casos reales que motivan este bloque:
  - 472238/472239 (TORRES OCARANZA LTDA): el cliente aparece dos veces en
    el documento (SEÑOR(ES) y como obra_destino) -- la extracción dejó
    `cliente` genuinamente vacío (CLIENTE_AUSENTE), pero el catálogo YA
    tiene "TORRES OCARANZA LTDA" como cliente CONFIRMADO/ACTIVO. Nunca se
    aprovechó ese cruce.
  - 472099/472163 (VISTA CLARA 2351 CERRILLOS / VIA MORADA 6480 VITACURA):
    Javier confirmó la dirección vía REGISTRAR_DIRECCION, pero el
    proveedor de rutas no pudo geocodificarla -- el aprendizaje
    reutilizable (Destino + relación obra<->destino) sólo se persistía
    cuando la ruta SÍ se calculaba, así que la confirmación humana se
    perdía por completo y la MISMA dirección en otra guía (misma u otra
    obra/cliente) volvía a preguntarse desde cero."""
from __future__ import annotations

import csv
import json

from atlas_core.aplicacion_decisiones import aplicar_decision_obra
from atlas_core.catalogo_clientes import CatalogoClientes, EstadoCalidadCliente
from atlas_core.catalogo_obras_destinos import CatalogoObrasDestinos, Evidencia, ResultadoEvidencia, TipoEvidencia
from atlas_core.decisiones_pendientes import crear_decision, detectar_decisiones_documento, generar_artefacto
from atlas_core.procesamiento_masivo import COLUMNAS
from atlas_core.revalidacion_documental import (
    revalidar_cliente_ausente_por_obra_coincidente_sin_ocr,
    revalidar_y_regenerar_reporte,
)


def _catalogos_base(carpeta):
    for nombre, contenido in {
        "clientes.json": {"version_formato": 1, "clientes": []}, "empresas.json": {},
        "vehiculos.json": {"version": 1, "vehiculos": []},
        "obras_destinos.json": {"version_formato": 1, "obras": [], "relaciones": []},
        "destinos_maestros.json": {"version_formato": 1, "destinos": []},
    }.items():
        (carpeta / nombre).write_text(json.dumps(contenido), encoding="utf-8")


def _fila(**overrides):
    fila = {c: "" for c in COLUMNAS}
    fila.update({
        "archivo": "x.jpeg", "estado_procesamiento": "OK", "numero_guia": "1",
        "numero_transporte": "T1", "fecha": "01-08-2026",
        "indicador_revision": "REVISAR", "planta_origen_id": "planta-1",
    })
    fila.update(overrides)
    return fila


def _pendientes(actual):
    return json.loads((actual / "decisiones_pendientes.json").read_text(encoding="utf-8"))["decisiones"]


# --- 1. CLIENTE_AUSENTE resuelto vía obra coincidente (sin OCR) ---

def test_cliente_ausente_se_resuelve_cuando_obra_coincide_con_cliente_confirmado(tmp_path):
    catalogos = tmp_path / "catalogos"; catalogos.mkdir()
    _catalogos_base(catalogos)
    CatalogoClientes(catalogos / "clientes.json").crear(
        razon_social="TORRES OCARANZA LTDA", rut="50.234.350-5", fuente="TEST",
        estado_calidad=EstadoCalidadCliente.CONFIRMADO,
    )
    dataset = tmp_path / "dataset.csv"
    fila = _fila(
        numero_guia="472238", cliente="No encontrado", obra_destino="TORRES OCARANZA LTDA",
        motivos_revision_documento="CLIENTE_AUSENTE",
    )
    with dataset.open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader(); escritor.writerow(fila)

    resultado = revalidar_cliente_ausente_por_obra_coincidente_sin_ocr(
        ruta_dataset=dataset, carpeta_catalogos=catalogos,
    )
    assert resultado["guias_actualizadas"] == ["472238"]
    with dataset.open(encoding="utf-8-sig") as archivo:
        fila_final = next(csv.DictReader(archivo, delimiter=";"))
    assert fila_final["cliente"] == "TORRES OCARANZA LTDA"
    assert "CLIENTE_AUSENTE" not in fila_final["motivos_revision_documento"]
    assert fila_final["indicador_revision"] == "OK"


def test_cliente_ausente_sin_obra_coincidente_se_abstiene(tmp_path):
    """Control -- cliente realmente ausente (obra no coincide con ningún
    cliente conocido) sigue generando revisión."""
    catalogos = tmp_path / "catalogos"; catalogos.mkdir()
    _catalogos_base(catalogos)
    CatalogoClientes(catalogos / "clientes.json").crear(
        razon_social="OTRA EMPRESA SA", rut="76.111.222-8", fuente="TEST",
        estado_calidad=EstadoCalidadCliente.CONFIRMADO,
    )
    dataset = tmp_path / "dataset.csv"
    fila = _fila(
        numero_guia="1", cliente="No encontrado", obra_destino="OBRA GENERICA SIN RELACION",
        motivos_revision_documento="CLIENTE_AUSENTE",
    )
    with dataset.open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader(); escritor.writerow(fila)

    resultado = revalidar_cliente_ausente_por_obra_coincidente_sin_ocr(
        ruta_dataset=dataset, carpeta_catalogos=catalogos,
    )
    assert resultado["guias_actualizadas"] == []
    with dataset.open(encoding="utf-8-sig") as archivo:
        fila_final = next(csv.DictReader(archivo, delimiter=";"))
    assert fila_final["cliente"] == "No encontrado"
    assert "CLIENTE_AUSENTE" in fila_final["motivos_revision_documento"]


def test_cliente_ya_presente_no_se_toca_por_este_mecanismo(tmp_path):
    """Control -- un cliente ya leído (aunque dudoso) nunca pasa por esta
    vía: CLIENTE_SIN_CORROBORAR es un dominio distinto."""
    catalogos = tmp_path / "catalogos"; catalogos.mkdir()
    _catalogos_base(catalogos)
    CatalogoClientes(catalogos / "clientes.json").crear(
        razon_social="TORRES OCARANZA LTDA", rut="50.234.350-5", fuente="TEST",
        estado_calidad=EstadoCalidadCliente.CONFIRMADO,
    )
    dataset = tmp_path / "dataset.csv"
    fila = _fila(
        numero_guia="1", cliente="TORRES OKARANSA LTDA", obra_destino="TORRES OCARANZA LTDA",
        motivos_revision_documento="CLIENTE_SIN_CORROBORAR",
    )
    with dataset.open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader(); escritor.writerow(fila)
    resultado = revalidar_cliente_ausente_por_obra_coincidente_sin_ocr(
        ruta_dataset=dataset, carpeta_catalogos=catalogos,
    )
    assert resultado["guias_actualizadas"] == []


# --- 2. E2E: la decisión CLIENTE_AUSENTE desaparece de la bandeja ---

def test_e2e_decision_cliente_ausente_desaparece_de_la_bandeja_tras_reconciliar(tmp_path):
    raiz = tmp_path / "Atlas"
    catalogos = raiz / "catalogos_privados"; actual = raiz / "operacion" / "actual"
    (raiz / "reportes").mkdir(parents=True); catalogos.mkdir(parents=True); actual.mkdir(parents=True)
    _catalogos_base(catalogos)
    CatalogoClientes(catalogos / "clientes.json").crear(
        razon_social="TORRES OCARANZA LTDA", rut="50.234.350-5", fuente="TEST",
        estado_calidad=EstadoCalidadCliente.CONFIRMADO,
    )
    dataset = actual / "analisis_completo_guias.csv"
    fila = _fila(
        archivo="472238.jpeg", numero_guia="472238", numero_transporte="T-472238",
        cliente="No encontrado", obra_destino="TORRES OCARANZA LTDA",
        motivos_revision_documento="CLIENTE_AUSENTE",
    )
    with dataset.open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader(); escritor.writerow(fila)
    decision = crear_decision(
        tipo="CLIENTE_AUSENTE", entidad="CLIENTE", archivo="472238.jpeg", numero_guia="472238",
        numero_transporte="T-472238", campo="cliente", valor_documental="", valor_normalizado="",
        identidad_resuelta=None, candidatos=(), motivos=("CLIENTE_AUSENTE",),
        evidencias=(), acciones_permitidas=("REGISTRAR_CLIENTE_MANUAL", "NO_PUEDO_DETERMINAR", "POSPONER"),
    )
    generar_artefacto(ruta_dataset=dataset, carpeta_catalogos=catalogos, decisiones=[decision], ruta_salida=actual / "decisiones_pendientes.json")
    assert len(_pendientes(actual)) == 1

    resultado = revalidar_y_regenerar_reporte(raiz_atlas=raiz, nombre_carpeta_reporte="reporte_r13")
    assert "472238" in resultado["guias_actualizadas"]
    assert resultado.get("bandeja_republicada") is True
    # La decisión ya no está pendiente -- el motivo que la originó se retiró.
    assert _pendientes(actual) == []


# --- 3. Destino/relación reutilizable independiente de la geocodificación ---

def _proveedor_direccion_ambigua(direccion):
    class _ProveedorAmbiguo:
        def calcular_ruta(self, *args, **kwargs):
            from atlas_core.rutas.modelos import EstadoRuta, ResultadoRuta
            return ResultadoRuta(estado=EstadoRuta.DIRECCION_AMBIGUA, distancia_km=None, duracion_minutos=None, proveedor="test")
    return _ProveedorAmbiguo()


def test_destino_confirmado_sin_geocodificar_se_reutiliza_para_otro_cliente(tmp_path):
    """Parte B + E combinadas: Javier confirma una dirección para OBRA X
    con CLIENTE A (el proveedor de rutas no logra geocodificarla). Una
    guía nueva de la MISMA obra con un CLIENTE DISTINTO (B) no debe volver
    a preguntar -- la obra es global, nunca está casada a un cliente."""
    from atlas_core.decisiones_pendientes import detectar_decision_destino_no_resuelto

    raiz = tmp_path / "Atlas"
    catalogos = raiz / "catalogos_privados"; actual = raiz / "operacion" / "actual"
    (raiz / "reportes").mkdir(parents=True); catalogos.mkdir(parents=True); actual.mkdir(parents=True)
    _catalogos_base(catalogos)
    cliente_a = CatalogoClientes(catalogos / "clientes.json").crear(
        razon_social="CLIENTE A SA", rut="76.111.111-6", fuente="TEST", estado_calidad=EstadoCalidadCliente.CONFIRMADO,
    )
    CatalogoClientes(catalogos / "clientes.json").crear(
        razon_social="CLIENTE B SA", rut="76.222.222-1", fuente="TEST", estado_calidad=EstadoCalidadCliente.CONFIRMADO,
    )
    obra = CatalogoObrasDestinos(
        ruta=catalogos / "obras_destinos.json", ruta_clientes=catalogos / "clientes.json",
        ruta_destinos=catalogos / "destinos_maestros.json",
    ).registrar_observacion(
        cliente_id=cliente_a.cliente_id, nombre_obra="OBRA COMPARTIDA",
        evidencia=Evidencia(
            tipo=TipoEvidencia.GUIA.value, identificador_fuente="1", referencia_hash="a" * 64,
            campos_observados={"obra": "OBRA COMPARTIDA"}, fecha="2026-01-01T00:00:00+00:00",
            actor_proceso="TEST", resultado=ResultadoEvidencia.SOPORTA.value,
        ),
    ).obra

    dataset = actual / "analisis_completo_guias.csv"
    fila_a = _fila(
        archivo="1.jpeg", numero_guia="1", numero_transporte="T1", cliente="CLIENTE A SA",
        obra_destino="OBRA COMPARTIDA", despachar_a_crudo="", motivo_ruta="DESTINO_SIN_DATO",
        estado_ruta="REQUIERE_REVISION",
    )
    with dataset.open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader(); escritor.writerow(fila_a)
    decision_a = detectar_decision_destino_no_resuelto(archivo="1.jpeg", fila=fila_a)
    generar_artefacto(ruta_dataset=dataset, carpeta_catalogos=catalogos, decisiones=[decision_a], ruta_salida=actual / "decisiones_pendientes.json")

    direccion = "DIRECCION AMBIGUA REAL 123"
    resultado = aplicar_decision_obra(
        raiz_atlas=raiz, decision_id=decision_a["decision_id"], accion="REGISTRAR_DIRECCION",
        direccion_manual=direccion, proveedor_rutas=_proveedor_direccion_ambigua(direccion),
    )
    assert resultado["ok"] is True
    assert resultado["ruta_resuelta"] is False
    assert resultado["destino_id"] is not None  # aprendizaje persistido pese a no geocodificar

    # Guía B, MISMA obra, cliente DISTINTO -- nunca debe generar una nueva
    # pregunta de destino (la obra es global, no casada a un cliente).
    fila_b = _fila(
        archivo="2.jpeg", numero_guia="2", numero_transporte="T2", cliente="CLIENTE B SA",
        obra_destino="OBRA COMPARTIDA", despachar_a_crudo="", motivo_ruta="DESTINO_SIN_DATO",
        estado_ruta="REQUIERE_REVISION",
    )
    decision_b = detectar_decision_destino_no_resuelto(archivo="2.jpeg", fila=fila_b)
    assert decision_b is not None  # Motor sí detecta el problema crudo...
    # ...pero `resolver_obra_destino_confirmada_global` (sin cliente_id) ya
    # sabe que esta obra global tiene una relación confirmada -- exactamente
    # el mecanismo que `revalidar_obra_destino_sin_ocr` usa para no volver
    # a preguntar.
    catalogo_obras = CatalogoObrasDestinos(
        ruta=catalogos / "obras_destinos.json", ruta_clientes=catalogos / "clientes.json",
        ruta_destinos=catalogos / "destinos_maestros.json",
    )
    assert catalogo_obras.resolver_obra_destino_confirmada_global(nombre_obra="OBRA COMPARTIDA") is not None


def test_destino_no_resuelto_de_otra_guia_desaparece_cuando_la_obra_ya_tiene_relacion_confirmada(tmp_path):
    """Caso real 472238/472239 (VISTA CLARA 2351 CERRILLOS, misma obra que
    472099, ya confirmada): la tarjeta DESTINO_NO_RESUELTO de una guía
    DISTINTA de la misma obra debe desaparecer sin nueva respuesta
    humana -- el proveedor de rutas puede seguir sin geocodificarla (eso
    es un problema aparte, nunca oculto), pero la pregunta "¿es correcta
    esta dirección?" ya tiene respuesta humana real."""
    from atlas_core.decisiones_pendientes import (
        detectar_decision_destino_no_resuelto, regenerar_decisiones_persistidas,
    )

    raiz = tmp_path / "Atlas"
    catalogos = raiz / "catalogos_privados"; actual = raiz / "operacion" / "actual"
    (raiz / "reportes").mkdir(parents=True); catalogos.mkdir(parents=True); actual.mkdir(parents=True)
    _catalogos_base(catalogos)
    cliente = CatalogoClientes(catalogos / "clientes.json").crear(
        razon_social="TORRES OCARANZA LTDA", rut="50.234.350-5", fuente="TEST", estado_calidad=EstadoCalidadCliente.CONFIRMADO,
    )
    CatalogoObrasDestinos(
        ruta=catalogos / "obras_destinos.json", ruta_clientes=catalogos / "clientes.json",
        ruta_destinos=catalogos / "destinos_maestros.json",
    ).registrar_observacion(
        cliente_id=cliente.cliente_id, nombre_obra="TORRES OCARANZA LTDA",
        evidencia=Evidencia(
            tipo=TipoEvidencia.GUIA.value, identificador_fuente="472099", referencia_hash="a" * 64,
            campos_observados={"obra": "TORRES OCARANZA LTDA"}, fecha="2026-01-01T00:00:00+00:00",
            actor_proceso="TEST", resultado=ResultadoEvidencia.SOPORTA.value,
        ),
    )
    dataset = actual / "analisis_completo_guias.csv"
    fila_confirmada = _fila(
        archivo="472099.jpeg", numero_guia="472099", numero_transporte="T-472099",
        cliente="TORRES OCARANZA LTDA", obra_destino="TORRES OCARANZA LTDA",
        despachar_a_crudo="", motivo_ruta="DESTINO_SIN_DATO", estado_ruta="REQUIERE_REVISION",
    )
    fila_hermana = _fila(
        archivo="472238.jpeg", numero_guia="472238", numero_transporte="T-472238",
        cliente="No encontrado", obra_destino="TORRES OCARANZA LTDA",
        despachar_a_crudo="VISTA CLARA 2351 CERRILLOS",
        motivo_ruta="GEOCODIFICACION_CONTRADICE_COMUNA_DOCUMENTAL: Cerrillos != Santiago",
        estado_ruta="REQUIERE_REVISION",
    )
    with dataset.open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader(); escritor.writerow(fila_confirmada); escritor.writerow(fila_hermana)
    decision_confirmada = detectar_decision_destino_no_resuelto(archivo="472099.jpeg", fila=fila_confirmada)
    decision_hermana = detectar_decision_destino_no_resuelto(archivo="472238.jpeg", fila=fila_hermana)
    generar_artefacto(
        ruta_dataset=dataset, carpeta_catalogos=catalogos, decisiones=[decision_confirmada, decision_hermana],
        ruta_salida=actual / "decisiones_pendientes.json",
    )

    resultado = aplicar_decision_obra(
        raiz_atlas=raiz, decision_id=decision_confirmada["decision_id"], accion="REGISTRAR_DIRECCION",
        direccion_manual="VISTA CLARA 2351 CERRILLOS", proveedor_rutas=_proveedor_direccion_ambigua("VISTA CLARA 2351 CERRILLOS"),
    )
    assert resultado["ok"] is True
    assert resultado["destino_id"] is not None

    pendientes = _pendientes(actual)
    tipos_restantes = [(d["tipo"], d["documento"]["numero_guia"]) for d in pendientes]
    assert ("DESTINO_NO_RESUELTO", "472238") not in tipos_restantes


def test_destino_no_resuelto_sin_obra_confirmada_conserva_la_decision(tmp_path):
    """Control -- sin ninguna relación confirmada para la obra, la
    tarjeta sigue pendiente (nunca desaparece sin causa)."""
    from atlas_core.decisiones_pendientes import regenerar_decisiones_persistidas

    catalogos = tmp_path / "catalogos"; catalogos.mkdir()
    _catalogos_base(catalogos)
    decision = {
        "decision_id": "d1", "tipo": "DESTINO_NO_RESUELTO", "entidad": "DESTINO",
        "documento": {"archivo": "1.jpeg", "numero_guia": "1", "numero_transporte": "T1"},
        "campo": "despachar_a_crudo", "valor_documental": "CALLE X 123", "valor_normalizado": "",
        "identidad_resuelta": None, "contexto": {"obra_canonica": "OBRA SIN RELACION", "cliente_canonico": "No encontrado"},
        "candidatos": [], "motivos": ["DESTINO_SIN_DATO"], "evidencias": [],
        "acciones_permitidas": ["REGISTRAR_DIRECCION", "NO_PUEDO_DETERMINAR", "POSPONER"],
    }
    restantes = regenerar_decisiones_persistidas(decisiones=[decision], carpeta_catalogos=catalogos)
    assert len(restantes) == 1


def test_destino_realmente_nuevo_sigue_generando_decision(tmp_path):
    """Control -- una dirección/obra genuinamente nueva sigue preguntando."""
    from atlas_core.decisiones_pendientes import detectar_decision_destino_no_resuelto
    fila = _fila(
        numero_guia="9", numero_transporte="T9", cliente="CLIENTE NUEVO",
        obra_destino="OBRA NUNCA VISTA", despachar_a_crudo="", motivo_ruta="DESTINO_SIN_DATO",
        estado_ruta="REQUIERE_REVISION",
    )
    decision = detectar_decision_destino_no_resuelto(archivo="9.jpeg", fila=fila)
    assert decision is not None
