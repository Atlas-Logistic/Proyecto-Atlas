"""Bloque R2.5 -- PROPAGACIÓN DE VERDAD OPERACIONAL DESPUÉS DE DECISIÓN
HUMANA. Caso real 464264: Javier confirmó "SODIMAC SA CORONEL" ->
"AV GOLFO DE ARAUCO 3536" (destino canónico confirmado, relación
obra<->destino CONFIRMADA), pero:
  - el viaje conservó 546,8 km / 10 h 22 min calculados para el destino
    ANTERIOR (la geocodificación del destino nuevo quedó ambigua/
    pendiente -- `distancia_km`/`duracion_min`/`proveedor_ruta` nunca se
    invalidaban al reemplazar `despachar_a_crudo`);
  - Desktop mostraba "Destino operacional: No disponible" porque
    `viajes.csv` seguía siendo el snapshot generado ANTES de la decisión
    (nada volvía a llamar `generar_reporte_viajes` fuera de un drop de
    imágenes nuevas);
  - `CONFLICTO_OBRA_DESTINO`/`CONFLICTO_FECHA` con la guía hermana 464265
    (mismo transporte) dejaban el viaje REQUIERE_REVISION sin ninguna
    decisión pendiente ni dependencia técnica detrás -- una revisión
    huérfana.

Clases de prueba (no casos literales): A invalidación inmediata de
derivados de ruta al reemplazar la dependencia base (destino/origen); B
proyección canónica -> operación (destino conocido != destino
geocodificado/ruteado); C recuperación automática de km/tiempo en la
próxima oportunidad de reconciliación; D reconciliación de dataset
desactualizado vs migración/reintento; E reconciliación segura de una
variación ortográfica menor contra una entidad canónica ya CONFIRMADA;
F/G abstención cuando la evidencia no alcanza (nunca inventa); H
idempotencia; I no pérdida de aprendizaje/decisiones/catálogos ajenos."""
from __future__ import annotations

import csv
import json

from atlas_core.aplicacion_decisiones import aplicar_decision_obra
from atlas_core.catalogo_clientes import CatalogoClientes, EstadoCalidadCliente
from atlas_core.catalogo_destinos import CatalogoDestinos, EstadoCalidadDestino
from atlas_core.catalogo_obras_destinos import CatalogoObrasDestinos, EstadoObra, Evidencia, ResultadoEvidencia, TipoEvidencia
from atlas_core.catalogo_plantas import CatalogoPlantas, EstadoCalidad as EstadoCalidadPlanta
from atlas_core.decisiones_pendientes import crear_decision, generar_artefacto
from atlas_core.procesamiento_masivo import COLUMNAS
from atlas_core.revalidacion_documental import (
    invalidar_derivados_ruta,
    revalidar_fecha_documental_por_transporte_compartido_sin_ocr,
    revalidar_obra_destino_sin_ocr,
    revalidar_ruta_sin_destino_calculado_sin_ocr,
)
from atlas_core.rutas.modelos import (
    CandidatoGeocodificacion, Coordenadas, EstadoRuta, ResultadoGeocodificacion, ResultadoRuta,
)


# ============================================================
# Fixtures compartidas
# ============================================================

def _fila_csv(**overrides):
    fila = {c: "" for c in COLUMNAS}
    fila.update({
        "archivo": "g.jpeg", "estado_procesamiento": "OK", "numero_guia": "1",
        "numero_transporte": "351135", "fecha": "31-08-2026",
        "cliente": "SODIMAC SA", "obra_destino": "SODIMAC SA CORONEL",
        "despachar_a_crudo": "DIRECCION ANTIGUA 100",
        "planta_origen_id": "planta-1", "planta_origen_nombre": "PLANTA NORTE",
        "distancia_km": "546.8017", "duracion_min": "621.88", "proveedor_ruta": "openrouteservice",
        "direccion_entrega": "Direccion Antigua 100, Santiago, RM, Chile",
        "localidad_entrega": "Santiago", "region_entrega": "Metropolitana",
        "estado_ruta": "RUTA_CALCULADA", "motivo_ruta": "",
        "estado_entrega": "RESUELTO",
        "indicador_revision": "OK", "estado_documental": "OK", "estado_operacional": "OK",
        "motivos_revision_documento": "",
    })
    fila.update(overrides)
    return fila


def _escribir_csv(ruta, filas):
    with ruta.open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader(); escritor.writerows(filas)


def _leer_csv(ruta):
    with ruta.open(encoding="utf-8-sig", newline="") as archivo:
        return {f["numero_guia"]: f for f in csv.DictReader(archivo, delimiter=";")}


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


def _agregar_planta_real(catalogos):
    """Las revalidaciones de ruta exigen que `planta_origen_id` exista
    de verdad en `plantas.json` (`plantas_por_id.get(...)`) -- crea una
    planta CONFIRMADA/ACTIVA real y devuelve (id, nombre) para usarlos en
    la fila del dataset, en vez de un id sintético que ninguna búsqueda
    real resolvería."""
    planta = CatalogoPlantas(catalogos / "plantas.json").crear(
        nombre="PLANTA NORTE", pais="CHILE", fuente="TEST",
        direccion="CALLE NORTE 100", comuna="COLINA", region="RM",
        latitud=-33.137558, longitud=-70.665977, estado_calidad=EstadoCalidadPlanta.CONFIRMADA,
    )
    return planta.planta_id, planta.nombre


def _publicar(entorno, decision):
    generar_artefacto(
        ruta_dataset=entorno["dataset"], carpeta_catalogos=entorno["catalogos"],
        decisiones=[decision], ruta_salida=entorno["actual"] / "decisiones_pendientes.json",
    )


class _ProveedorFijo:
    """Mismo doble ya usado en test_r2_4_coherencia_ruta_reactiva.py --
    responde siempre el mismo resultado, sin importar la consulta."""

    def __init__(self, resultado_geocodificacion, resultado_ruta=None):
        self._resultado_geocodificacion = resultado_geocodificacion
        self._resultado_ruta = resultado_ruta
        self.nombre = "simulado_fijo"
        self.version = "1"

    def geocodificar(self, direccion):
        return self._resultado_geocodificacion

    def calcular_ruta(self, origen, destino, perfil):
        return self._resultado_ruta


def _proveedor_ambiguo_sin_candidatos_relevantes():
    """Geocodificación de la dirección NUEVA queda genuinamente ambigua
    (varios candidatos dispersos, ninguno con respaldo textual) --
    exactamente el patrón real 464264 (COORDENADA_NO_CONFIRMADA)."""
    candidatos = (
        CandidatoGeocodificacion(Coordenadas(-70.1, -33.1), "Otro Lugar 1, Ránquil, Ñuble, Chile", 0.6, "Ranquil", "Nuble"),
        CandidatoGeocodificacion(Coordenadas(-70.2, -33.2), "Otro Lugar 2, Til Til, RM, Chile", 0.6, "Til Til", "Metropolitana"),
    )
    return _ProveedorFijo(ResultadoGeocodificacion(EstadoRuta.RESULTADO_AMBIGUO, candidatos, "MULTIPLES"), None)


def _proveedor_exitoso():
    candidato = CandidatoGeocodificacion(Coordenadas(-70.65, -33.44), "Direccion Nueva 200, Santiago, RM, Chile", 1.0, "Santiago", "Metropolitana")
    return _ProveedorFijo(
        ResultadoGeocodificacion(EstadoRuta.RESULTADO_AMBIGUO, (candidato,), "CANDIDATO_UNICO"),
        ResultadoRuta(EstadoRuta.RUTA_CALCULADA, 12.3, 20.0, "SINTETICO"),
    )


def _decision_destino_no_resuelto(fila):
    return crear_decision(
        tipo="DESTINO_NO_RESUELTO", entidad="DESTINO", archivo=fila["archivo"],
        numero_guia=fila["numero_guia"], numero_transporte=fila["numero_transporte"],
        campo="despachar_a_crudo", valor_documental=fila["despachar_a_crudo"],
        valor_normalizado="", identidad_resuelta=None,
        candidatos=(), motivos=["MULTIPLES_UBICACIONES_DISPERSAS"],
        evidencias=[{"tipo": "RUTA_BLOQUEADA"}],
        acciones_permitidas=("REGISTRAR_DIRECCION", "NO_PUEDO_DETERMINAR", "POSPONER"),
        contexto={"obra_canonica": fila["obra_destino"], "cliente_canonico": fila["cliente"]},
    )


# ============================================================
# Clase A -- invalidación inmediata de derivados de ruta (destino)
# ============================================================

def test_A_destino_cambia_y_geocodificacion_falla_invalida_km_tiempo_de_inmediato(tmp_path):
    fila = _fila_csv()
    entorno = _entorno(tmp_path, filas_csv=[fila])
    planta_id, planta_nombre = _agregar_planta_real(entorno["catalogos"])
    fila["planta_origen_id"], fila["planta_origen_nombre"] = planta_id, planta_nombre
    _escribir_csv(entorno["dataset"], [fila])
    decision = _decision_destino_no_resuelto(fila)
    _publicar(entorno, decision)

    resultado = aplicar_decision_obra(
        raiz_atlas=entorno["raiz"], decision_id=decision["decision_id"],
        accion="REGISTRAR_DIRECCION", direccion_manual="AV GOLFO DE ARAUCO 3536",
        proveedor_rutas=_proveedor_ambiguo_sin_candidatos_relevantes(),
    )
    assert resultado["ok"] is True

    fila_final = _leer_csv(entorno["dataset"])["1"]
    # El destino A (546,8 km / 10 h 22 min / openrouteservice) NUNCA
    # sobrevive -- ni siquiera cuando la geocodificación del destino B
    # todavía no puede completarse.
    assert fila_final["distancia_km"] == ""
    assert fila_final["duracion_min"] == ""
    assert fila_final["proveedor_ruta"] == ""
    assert fila_final["direccion_entrega"] == ""
    assert fila_final["localidad_entrega"] == ""
    assert fila_final["region_entrega"] == ""
    assert fila_final["despachar_a_crudo"] == "AV GOLFO DE ARAUCO 3536"


def test_A_destino_cambia_y_geocodificacion_nueva_exitosa_reemplaza_por_completo(tmp_path):
    fila = _fila_csv()
    entorno = _entorno(tmp_path, filas_csv=[fila])
    planta_id, planta_nombre = _agregar_planta_real(entorno["catalogos"])
    fila["planta_origen_id"], fila["planta_origen_nombre"] = planta_id, planta_nombre
    _escribir_csv(entorno["dataset"], [fila])
    decision = _decision_destino_no_resuelto(fila)
    _publicar(entorno, decision)

    aplicar_decision_obra(
        raiz_atlas=entorno["raiz"], decision_id=decision["decision_id"],
        accion="REGISTRAR_DIRECCION", direccion_manual="DIRECCION NUEVA 200 SANTIAGO",
        proveedor_rutas=_proveedor_exitoso(),
    )
    fila_final = _leer_csv(entorno["dataset"])["1"]
    assert fila_final["estado_ruta"] == "RUTA_CALCULADA"
    assert fila_final["distancia_km"] == "12.3"
    assert fila_final["duracion_min"] == "20.0"
    # Nunca queda un residuo del destino ANTERIOR.
    assert "546" not in fila_final["distancia_km"]


# ============================================================
# Clase A (simétrica) -- invalidación al cambiar el ORIGEN
# ============================================================

def test_A_invalidar_derivados_ruta_devuelve_todos_los_campos_vacios():
    campos = invalidar_derivados_ruta()
    for campo in (
        "distancia_km", "duracion_min", "proveedor_ruta",
        "direccion_entrega", "localidad_entrega", "region_entrega",
        "estado_ruta", "motivo_ruta", "estado_entrega",
    ):
        assert campos[campo] == ""


# ============================================================
# Clase B -- proyección canónica -> operación (destino conocido !=
# destino geocodificado/ruteado)
# ============================================================

def test_B_destino_operacional_visible_sin_coordenadas_via_despachar_a(tmp_path):
    """`Viaje.despachar_a` (gestor_viajes) debe exponer la dirección
    CONFIRMADA por el humano aunque la ruta siga sin poder calcularse --
    "sé cuál es el destino" no depende de "ya pude geocodificarlo"."""
    from atlas_core.gestor_viajes import agrupar_viajes

    fila = _fila_csv(
        despachar_a_crudo="AV GOLFO DE ARAUCO 3536",
        distancia_km="", duracion_min="", proveedor_ruta="",
        direccion_entrega="", localidad_entrega="", region_entrega="",
        estado_ruta="REQUIERE_REVISION", motivo_ruta="COORDENADA_NO_CONFIRMADA(5)",
        estado_entrega="", estado_operacional="REQUIERE_REVISION",
    )
    viajes, _ = agrupar_viajes([fila])
    assert len(viajes) == 1
    viaje = viajes[0]
    assert viaje.despachar_a == "AV GOLFO DE ARAUCO 3536"
    assert viaje.distancia_km == ""  # km/tiempo genuinamente pendientes
    assert viaje.duracion_min == ""


# ============================================================
# Clase C -- recuperación automática en la próxima oportunidad
# ============================================================

def test_C_reintento_posterior_recupera_km_tiempo_y_cierra_pendiente(tmp_path):
    fila = _fila_csv(
        despachar_a_crudo="DIRECCION NUEVA 200 SANTIAGO",
        distancia_km="", duracion_min="", proveedor_ruta="",
        estado_ruta="", motivo_ruta="", estado_entrega="",
        estado_operacional="REQUIERE_REVISION", indicador_revision="OK", estado_documental="OK",
    )
    entorno = _entorno(tmp_path, filas_csv=[fila])
    planta_id, planta_nombre = _agregar_planta_real(entorno["catalogos"])
    fila["planta_origen_id"], fila["planta_origen_nombre"] = planta_id, planta_nombre
    _escribir_csv(entorno["dataset"], [fila])
    resultado = revalidar_ruta_sin_destino_calculado_sin_ocr(
        ruta_dataset=entorno["dataset"], carpeta_catalogos=entorno["catalogos"],
        proveedor_rutas=_proveedor_exitoso(),
    )
    assert resultado["guias_actualizadas"] == ["1"]
    fila_final = _leer_csv(entorno["dataset"])["1"]
    assert fila_final["estado_ruta"] == "RUTA_CALCULADA"
    assert fila_final["distancia_km"] == "12.3"
    assert fila_final["estado_operacional"] == "OK"


# ============================================================
# Clase D -- reporte desactualizado se regenera aunque no haya
# migración ni reintento de ruta vencido
# ============================================================

def test_D_reporte_se_regenera_cuando_el_dataset_cambio_sin_migracion_ni_reintento(tmp_path, monkeypatch):
    from datetime import datetime, timezone
    from atlas_core.almacenamiento_portable import escribir_estado_operacion
    from atlas_core import reconciliacion_estado_derivado as modulo

    RELOJ_0 = lambda: datetime(2026, 8, 31, 20, 0, 0, tzinfo=timezone.utc)
    RELOJ_1 = lambda: datetime(2026, 8, 31, 20, 0, 1, tzinfo=timezone.utc)
    RELOJ_2 = lambda: datetime(2026, 8, 31, 20, 0, 2, tzinfo=timezone.utc)
    actual = tmp_path / "operacion" / "actual"; actual.mkdir(parents=True)
    dataset = actual / "analisis_completo_guias.csv"
    _escribir_csv(dataset, [_fila_csv()])
    decisiones = actual / "decisiones_pendientes.json"
    decisiones.write_text('{"decisiones": []}', encoding="utf-8")
    reporte_anterior = tmp_path / "reportes" / "anterior"; reporte_anterior.mkdir(parents=True)
    escribir_estado_operacion(
        reporte_vigente=reporte_anterior, dataset_operacional=dataset,
        decisiones_pendientes=decisiones, raiz=tmp_path, reloj=RELOJ_0,
        version_estado_derivado=modulo.VERSION_ESTADO_DERIVADO,
    )
    # Primera pasada: ya en la versión vigente, sin pendientes -- deja
    # publicada la huella del dataset ACTUAL (simula el estado real tras
    # una corrida de reconciliación anterior a cualquier decisión nueva).
    monkeypatch.setattr(modulo, "revalidar_motivo_destino_ya_confirmado_sin_ocr", lambda **k: {"guias_actualizadas": []})
    def reportar(_dataset, salida, **kwargs):
        salida.mkdir(parents=True, exist_ok=True)
        (salida / "viajes.csv").write_text("estado\nCONFIRMADO\n", encoding="utf-8")
        return {"totales": {"viajes": 1}}
    monkeypatch.setattr(modulo, "generar_reporte_viajes", reportar)
    primera = modulo.reconciliar_estado_derivado(raiz_atlas=tmp_path, reloj=RELOJ_0)
    assert primera["reconciliado"] is True

    # Una decisión humana (o cualquier otra escritura) cambia el dataset
    # -- sin ninguna migración pendiente ni reintento de ruta vencido.
    filas_mutadas = _leer_csv(dataset)
    fila_mutada = filas_mutadas["1"]
    fila_mutada["cliente"] = "SODIMAC SA CORONEL CONFIRMADO"
    _escribir_csv(dataset, [fila_mutada])

    segunda = modulo.reconciliar_estado_derivado(raiz_atlas=tmp_path, reloj=RELOJ_1)
    assert segunda["reconciliado"] is True
    assert segunda["reporte_regenerado_por_dataset_desactualizado"] is True

    # Sin ningún cambio adicional, una tercera pasada vuelve a no hacer
    # nada -- nunca regenera de más.
    tercera = modulo.reconciliar_estado_derivado(raiz_atlas=tmp_path, reloj=RELOJ_2)
    assert tercera["reconciliado"] is False


# ============================================================
# Clase E -- reconciliación segura de variación ortográfica menor
# contra una entidad canónica ya CONFIRMADA
# ============================================================

def _preparar_obra_confirmada(catalogos, *, cliente_nombre, obra_nombre):
    """Mismo camino REAL de confirmación (nunca un atajo sintético): un
    destino CONFIRMADO + una relación obra<->destino registrada y
    CONFIRMADA -- `confirmar_relacion` es la única vía que promueve la
    obra a `EstadoObra.CONFIRMADA` (ver `CatalogoObrasDestinos.
    confirmar_relacion`)."""
    cliente = CatalogoClientes(catalogos / "clientes.json").crear(
        razon_social=cliente_nombre, fuente="TEST", estado_calidad=EstadoCalidadCliente.CONFIRMADO,
    )
    destino = CatalogoDestinos(catalogos / "destinos_maestros.json", ruta_clientes=catalogos / "clientes.json").crear_o_reutilizar_global(
        nombre_destino=f"DESTINO DE {obra_nombre}", direccion=f"CALLE DE {obra_nombre} 1",
        fuente="TEST", estado_calidad=EstadoCalidadDestino.CONFIRMADO,
    )
    catalogo_obras = CatalogoObrasDestinos(
        ruta=catalogos / "obras_destinos.json", ruta_clientes=catalogos / "clientes.json",
        ruta_destinos=catalogos / "destinos_maestros.json",
    )
    evidencia = Evidencia(
        tipo=TipoEvidencia.GUIA.value, identificador_fuente="0", referencia_hash="0",
        campos_observados={}, fecha="2026-08-31T00:00:00+00:00",
        actor_proceso="TEST", resultado=ResultadoEvidencia.SOPORTA.value,
    )
    resultado = catalogo_obras.registrar_observacion(
        cliente_id=cliente.cliente_id, nombre_obra=obra_nombre,
        destino_id=destino.destino_id, evidencia=evidencia,
    )
    catalogo_obras.confirmar_relacion(resultado.relacion.relacion_id, actor="TEST")
    obra_confirmada = next(
        o for o in catalogo_obras.listar_obras() if o.obra_id == resultado.obra.obra_id
    )
    assert obra_confirmada.estado == EstadoObra.CONFIRMADA.value
    return cliente, obra_confirmada, catalogo_obras


def test_E_variacion_ortografica_menor_se_reconcilia_contra_obra_confirmada(tmp_path):
    entorno = _entorno(
        tmp_path,
        filas_csv=[_fila_csv(
            numero_guia="2", archivo="2.jpeg", cliente="SODIMAC SA",
            obra_destino="SODIMAC SA COROBEL",  # variación de un solo dígito/letra de CORONEL
            motivos_revision_documento="OBRA_DESTINO_SIN_CORROBORAR",
            despachar_a_crudo="", distancia_km="", duracion_min="", proveedor_ruta="",
            estado_ruta="", motivo_ruta="", direccion_entrega="", localidad_entrega="", region_entrega="",
            indicador_revision="REVISAR", estado_documental="REQUIERE_REVISION",
        )],
    )
    _, obra_confirmada, catalogo_obras = _preparar_obra_confirmada(
        entorno["catalogos"], cliente_nombre="SODIMAC SA", obra_nombre="SODIMAC SA CORONEL",
    )

    resultado_revalidacion = revalidar_obra_destino_sin_ocr(
        ruta_dataset=entorno["dataset"], carpeta_catalogos=entorno["catalogos"],
    )
    assert resultado_revalidacion["guias_actualizadas"] == ["2"]
    fila_final = _leer_csv(entorno["dataset"])["2"]
    assert fila_final["obra_destino"] == "SODIMAC SA CORONEL"
    assert "OBRA_DESTINO_SIN_CORROBORAR" not in fila_final["motivos_revision_documento"]
    # Aprendizaje reutilizable: el texto documental corrupto queda como
    # alias de la obra confirmada.
    obra_tras = next(o for o in catalogo_obras.listar_obras() if o.obra_id == obra_confirmada.obra_id)
    assert "SODIMAC SA COROBEL" in obra_tras.aliases_documentales


# ============================================================
# Clase F/G -- abstención cuando la evidencia no alcanza (fecha)
# ============================================================

def test_F_fecha_sin_evidencia_de_lote_no_se_corrige(tmp_path):
    entorno = _entorno(tmp_path, filas_csv=[
        _fila_csv(numero_guia="1", archivo="1.jpeg", numero_transporte="T1", fecha="05-08-2026"),
        _fila_csv(numero_guia="2", archivo="2.jpeg", numero_transporte="T1", fecha="05-08-2024"),
    ])
    resultado = revalidar_fecha_documental_por_transporte_compartido_sin_ocr(ruta_dataset=entorno["dataset"])
    assert resultado["guias_actualizadas"] == []
    filas = _leer_csv(entorno["dataset"])
    assert filas["1"]["fecha"] == "05-08-2026"
    assert filas["2"]["fecha"] == "05-08-2024"  # ninguna corrección inventada


def test_G_fecha_con_evidencia_de_lote_suficiente_se_reconcilia(tmp_path):
    filas_csv = [
        _fila_csv(numero_guia="1", archivo="1.jpeg", numero_transporte="T1", fecha="05-08-2026"),
        _fila_csv(numero_guia="2", archivo="2.jpeg", numero_transporte="T1", fecha="05-08-2024"),
    ] + [
        _fila_csv(numero_guia=str(n), archivo=f"{n}.jpeg", numero_transporte=f"T{n}", fecha="10-08-2026")
        for n in range(3, 9)
    ]
    entorno = _entorno(tmp_path, filas_csv=filas_csv)
    resultado = revalidar_fecha_documental_por_transporte_compartido_sin_ocr(ruta_dataset=entorno["dataset"])
    assert resultado["guias_actualizadas"] == ["2"]
    filas = _leer_csv(entorno["dataset"])
    assert filas["1"]["fecha"] == "05-08-2026"
    assert filas["2"]["fecha"] == "05-08-2026"  # se reconcilia con el patrón dominante del lote


def test_G_fecha_dia_distinto_nunca_se_corrige_automaticamente(tmp_path):
    """Una diferencia de día/mes NUNCA es "un solo dígito de OCR" para
    este bloque -- ahí la ambigüedad es real y debe quedar para una
    decisión humana explícita, nunca una corrección silenciosa."""
    filas_csv = [
        _fila_csv(numero_guia="1", archivo="1.jpeg", numero_transporte="T1", fecha="05-08-2026"),
        _fila_csv(numero_guia="2", archivo="2.jpeg", numero_transporte="T1", fecha="06-08-2026"),
    ] + [
        _fila_csv(numero_guia=str(n), archivo=f"{n}.jpeg", numero_transporte=f"T{n}", fecha="10-08-2026")
        for n in range(3, 9)
    ]
    entorno = _entorno(tmp_path, filas_csv=filas_csv)
    resultado = revalidar_fecha_documental_por_transporte_compartido_sin_ocr(ruta_dataset=entorno["dataset"])
    assert resultado["guias_actualizadas"] == []


# ============================================================
# Clase H -- idempotencia
# ============================================================

def test_H_revalidacion_fecha_es_idempotente(tmp_path):
    filas_csv = [
        _fila_csv(numero_guia="1", archivo="1.jpeg", numero_transporte="T1", fecha="05-08-2026"),
        _fila_csv(numero_guia="2", archivo="2.jpeg", numero_transporte="T1", fecha="05-08-2024"),
    ] + [
        _fila_csv(numero_guia=str(n), archivo=f"{n}.jpeg", numero_transporte=f"T{n}", fecha="10-08-2026")
        for n in range(3, 9)
    ]
    entorno = _entorno(tmp_path, filas_csv=filas_csv)
    primera = revalidar_fecha_documental_por_transporte_compartido_sin_ocr(ruta_dataset=entorno["dataset"])
    segunda = revalidar_fecha_documental_por_transporte_compartido_sin_ocr(ruta_dataset=entorno["dataset"])
    assert primera["guias_actualizadas"] == ["2"]
    assert segunda["guias_actualizadas"] == []


def test_H_aplicar_decision_destino_es_idempotente_ante_reintento(tmp_path):
    fila = _fila_csv()
    entorno = _entorno(tmp_path, filas_csv=[fila])
    decision = _decision_destino_no_resuelto(fila)
    _publicar(entorno, decision)

    primero = aplicar_decision_obra(
        raiz_atlas=entorno["raiz"], decision_id=decision["decision_id"],
        accion="REGISTRAR_DIRECCION", direccion_manual="DIRECCION NUEVA 200 SANTIAGO",
        proveedor_rutas=_proveedor_exitoso(),
    )
    segundo = aplicar_decision_obra(
        raiz_atlas=entorno["raiz"], decision_id=decision["decision_id"],
        accion="REGISTRAR_DIRECCION", direccion_manual="DIRECCION NUEVA 200 SANTIAGO",
        proveedor_rutas=_proveedor_exitoso(),
    )
    assert primero["ok"] is True
    assert segundo == {"ok": True, "idempotente": True, "accion": "REGISTRAR_DIRECCION", "mensaje": "Esta decisión ya fue aplicada."}


# ============================================================
# Clase I -- no pérdida de aprendizaje/decisiones/catálogos ajenos
# ============================================================

def test_I_reconciliacion_obra_no_toca_otras_filas_ni_otros_campos(tmp_path):
    fila_afectada = _fila_csv(
        numero_guia="2", archivo="2.jpeg", cliente="SODIMAC SA", obra_destino="SODIMAC SA COROBEL",
        motivos_revision_documento="OBRA_DESTINO_SIN_CORROBORAR",
        despachar_a_crudo="ALGO", distancia_km="", duracion_min="",
        estado_ruta="", motivo_ruta="",
        indicador_revision="REVISAR", estado_documental="REQUIERE_REVISION",
    )
    fila_ajena = _fila_csv(
        numero_guia="9", archivo="9.jpeg", cliente="OTRO CLIENTE", obra_destino="OTRA OBRA CUALQUIERA",
        motivos_revision_documento="",
    )
    entorno = _entorno(tmp_path, filas_csv=[fila_afectada, fila_ajena])
    _preparar_obra_confirmada(
        entorno["catalogos"], cliente_nombre="SODIMAC SA", obra_nombre="SODIMAC SA CORONEL",
    )

    revalidar_obra_destino_sin_ocr(ruta_dataset=entorno["dataset"], carpeta_catalogos=entorno["catalogos"])

    filas_finales = _leer_csv(entorno["dataset"])
    assert filas_finales["2"]["obra_destino"] == "SODIMAC SA CORONEL"
    # La fila ajena (otro cliente, ninguna relación con esta obra) queda
    # exactamente igual, byte por byte en sus campos relevantes.
    assert filas_finales["9"]["obra_destino"] == "OTRA OBRA CUALQUIERA"
    assert filas_finales["9"]["cliente"] == "OTRO CLIENTE"
