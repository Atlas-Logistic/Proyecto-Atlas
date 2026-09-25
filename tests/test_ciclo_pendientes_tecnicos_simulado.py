"""Ciclo automático de PENDIENTE_TECNICO -- operación temporal simulada.

Todas las pruebas corren sobre `tmp_path` con proveedores simulados
inyectados: nunca tocan la operación real, ni ORS/Nominatim/B1 reales.
Complementa `test_mantenimiento_pendientes_tecnicos.py` con los
revalidadores REALES (sin monkeypatch) donde importa demostrar qué se
consulta y qué no.
"""
from __future__ import annotations

import csv
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from atlas_core import mantenimiento_pendientes_tecnicos as mantenimiento
from atlas_core import politica_pendientes_tecnicos as politica
from atlas_core import reconciliacion_estado_derivado as reconciliacion
from atlas_core.catalogo_destinos import CatalogoDestinos, EstadoCalidadDestino
from atlas_core.catalogo_obras_destinos import (
    CatalogoObrasDestinos, Evidencia, ResultadoEvidencia, TipoEvidencia,
)
from atlas_core.catalogo_plantas import CatalogoPlantas, EstadoCalidad
from atlas_core.procesamiento_masivo import COLUMNAS
from atlas_core.reconciliacion_estado_derivado import _huella_ruta
from atlas_core.revalidacion_documental import (
    revalidar_ruta_con_destino_confirmado_en_catalogo_sin_ocr,
)
from atlas_core.revalidacion_reactiva_tecnica import revalidar_tras_cambio_catalogo
from atlas_core.rutas.modelos import EstadoRuta, ResultadoGeocodificacion, ResultadoRuta
from atlas_core.rutas.proveedor import ProveedorRutasSimulado

AHORA = datetime(2026, 9, 25, 14, 0, tzinfo=timezone.utc)
OBRA = "OBRA LAS HORTENSIAS"
DIRECCION = "LAS HORTENSIAS 3800"


def _proveedor() -> ProveedorRutasSimulado:
    """Geocodificación siempre sin candidato: si alguien geocodifica, se
    cuenta; nunca resuelve por esa vía."""
    return ProveedorRutasSimulado(
        geocodificaciones={},
        resultado_ruta=ResultadoRuta(EstadoRuta.RUTA_CALCULADA, 21.3, 33.0, "SINTETICO"),
    )


def _escribir_csv(ruta: Path, filas: list[dict]) -> None:
    with ruta.open("w", encoding="utf-8-sig", newline="") as f:
        escritor = csv.DictWriter(f, fieldnames=COLUMNAS, delimiter=";", extrasaction="ignore")
        escritor.writeheader()
        escritor.writerows(filas)


def _leer_csv(ruta: Path) -> dict[str, dict]:
    with ruta.open(encoding="utf-8-sig", newline="") as f:
        return {r["numero_guia"]: r for r in csv.DictReader(f, delimiter=";")}


def _fila(guia: str, motivo: str, planta_id: str, **extra) -> dict:
    fila = {c: "" for c in COLUMNAS}
    fila.update(
        numero_guia=guia, numero_transporte=f"00003601{guia[-2:]}", archivo=f"{guia}.jpg",
        planta_origen_id=planta_id, planta_origen_nombre="AZA COLINA",
        despachar_a_crudo=DIRECCION, cliente="CLIENTE TEST", obra_destino=OBRA,
        indicador_revision="OK", estado_documental="OK",
        estado_operacional="REQUIERE_REVISION", estado_ruta="REQUIERE_REVISION",
        motivo_ruta=motivo,
    )
    fila.update(extra)
    return fila


class Operacion:
    """Operación Atlas temporal con catálogos reales en disco."""

    def __init__(self, tmp_path: Path):
        self.raiz = tmp_path / "Atlas"
        self.catalogos = self.raiz / "catalogos_privados"
        self.actual = self.raiz / "operacion" / "actual"
        self.catalogos.mkdir(parents=True)
        self.actual.mkdir(parents=True)
        self.dataset = self.actual / "analisis_completo_guias.csv"
        (self.catalogos / "clientes.json").write_text(json.dumps({"version_formato": 1, "clientes": [{
            "cliente_id": "cliente-test", "razon_social": "CLIENTE TEST",
            "nombre_normalizado": "CLIENTE TEST", "nombre_comercial": "", "rut": "76086428-5",
            "aliases": [], "estado_calidad": "CONFIRMADO", "estado_vigencia": "ACTIVO",
            "fuente": "TEST", "observacion": "",
            "fecha_creacion": "2026-01-01T00:00:00+00:00", "fecha_modificacion": "2026-01-01T00:00:00+00:00",
        }]}), encoding="utf-8")
        (self.catalogos / "destinos_maestros.json").write_text(
            json.dumps({"version_formato": 1, "destinos": []}), encoding="utf-8")
        (self.catalogos / "obras_destinos.json").write_text(
            json.dumps({"version_formato": 1, "obras": [], "relaciones": []}), encoding="utf-8")
        self.planta_id = CatalogoPlantas(self.catalogos / "plantas.json").crear(
            nombre="AZA COLINA", pais="CHILE", fuente="TEST", direccion="AV EJEMPLO 1",
            comuna="COLINA", region="RM", latitud=-33.137558, longitud=-70.665977,
            estado_calidad=EstadoCalidad.CONFIRMADA,
        ).planta_id

    @property
    def destinos(self) -> CatalogoDestinos:
        return CatalogoDestinos(self.catalogos / "destinos_maestros.json",
                                ruta_clientes=self.catalogos / "clientes.json")

    def confirmar_destino_de_obra(self, *, con_coordenadas: bool) -> str:
        """Destino CONFIRMADO + relación obra->destino CONFIRMADA por la API
        pública de los catálogos (nunca JSON a mano)."""
        destino = self.destinos.crear(
            cliente_id="cliente-test", nombre_destino=DIRECCION, direccion=DIRECCION,
            comuna="LA REINA", region="RM", pais="CHILE", fuente="TEST",
            latitud=-33.45 if con_coordenadas else None, longitud=-70.54 if con_coordenadas else None,
            estado_calidad=EstadoCalidadDestino.CONFIRMADO,
        )
        obras = CatalogoObrasDestinos(
            ruta=self.catalogos / "obras_destinos.json", ruta_clientes=self.catalogos / "clientes.json",
            ruta_destinos=self.catalogos / "destinos_maestros.json",
        )
        observacion = obras.registrar_observacion(
            cliente_id="cliente-test", nombre_obra=OBRA, destino_id=destino.destino_id,
            evidencia=Evidencia(
                tipo=TipoEvidencia.GUIA.value, identificador_fuente="semilla",
                referencia_hash="h", campos_observados={"obra": OBRA},
                fecha=AHORA.isoformat(), actor_proceso="TEST",
                resultado=ResultadoEvidencia.SOPORTA.value,
            ),
        )
        obras.confirmar_relacion(observacion.relacion.relacion_id, actor="TEST")
        assert obras.listar_destinos_confirmados_para_obra(nombre_obra=OBRA)
        return destino.destino_id

    def sembrar(self, filas: list[dict], *, minutos: int = 31, intentos: int = 1) -> None:
        _escribir_csv(self.dataset, filas)
        registros = []
        for fila in filas:
            if fila["estado_ruta"] == "RUTA_CALCULADA":
                continue
            registros.append({
                "numero_guia": fila["numero_guia"], "huella_datos": _huella_ruta(fila),
                "huella_conocimiento": self.huella(fila), "motivo_actual": fila["motivo_ruta"],
                "intentos_misma_evidencia": intentos,
                "ultimo_intento": (AHORA - timedelta(minutes=minutos)).isoformat(),
                "historial_resultados": [],
            })
        self.escribir_pendientes(registros)

    def huella(self, fila: dict) -> str:
        return politica.conocimiento_para_guia(
            fila, catalogos=self.catalogos,
            decisiones_aplicadas=self.actual / "decisiones_aplicadas.json",
            version_reglas=reconciliacion.RULESET_VERSION,
            versiones_capacidades=mantenimiento.versiones_actuales(),
        )

    def escribir_pendientes(self, registros: list[dict]) -> None:
        (self.actual / "pendientes_tecnicos.json").write_text(
            json.dumps({"schema_version": 1, "pendientes": registros}), encoding="utf-8")

    def decisiones(self) -> list[dict]:
        ruta = self.actual / "decisiones_pendientes.json"
        if not ruta.is_file():
            return []
        return json.loads(ruta.read_text(encoding="utf-8")).get("decisiones", [])

    def pendientes(self) -> dict[str, dict]:
        datos = json.loads((self.actual / "pendientes_tecnicos.json").read_text(encoding="utf-8"))
        return {p["numero_guia"]: p for p in datos["pendientes"]}

    def mantener(self, instante=AHORA, **kwargs):
        kwargs.setdefault("proveedor_rutas", _proveedor())
        kwargs.setdefault("proveedor_rutas_fallback", _proveedor())
        return mantenimiento.mantener_pendientes_tecnicos(
            raiz_atlas=self.raiz, reloj=lambda: instante, **kwargs)


@pytest.fixture
def op(tmp_path):
    return Operacion(tmp_path)


@pytest.fixture
def espia(monkeypatch):
    """Registra el ORDEN de las etapas sin alterar su comportamiento real."""
    orden: list[tuple[str, frozenset]] = []
    interno = mantenimiento.revalidar_ruta_con_destino_confirmado_en_catalogo_sin_ocr
    externo = mantenimiento.revalidar_ruta_sin_destino_calculado_sin_ocr

    def _interno(**kw):
        orden.append(("interno", frozenset(kw["guias_objetivo"])))
        assert kw["solo_con_coordenadas"] is True
        return interno(**kw)

    def _externo(**kw):
        orden.append(("externo", frozenset(kw["guias_objetivo"])))
        return externo(**kw)

    monkeypatch.setattr(mantenimiento, "revalidar_ruta_con_destino_confirmado_en_catalogo_sin_ocr", _interno)
    monkeypatch.setattr(mantenimiento, "revalidar_ruta_sin_destino_calculado_sin_ocr", _externo)
    return orden


# ---------------------------------------------------------------- política


def test_politica_final_por_clase_es_30_min_con_limites_finitos():
    assert politica.INTERVALO_MAXIMO == timedelta(minutes=30)
    assert reconciliacion.INTERVALO_REINTENTO == timedelta(minutes=30)
    assert reconciliacion.COOLDOWN_REINTENTO_TRANSITORIO == timedelta(minutes=30)
    # Una sola política: selector y ciclo de vida usan los mismos límites.
    assert politica.LIMITES["AGOTABLE"] == reconciliacion.MAX_REINTENTOS_POR_CLASE["AGOTABLE"] == 3
    assert politica.LIMITES["TRANSITORIO"] == reconciliacion.MAX_REINTENTOS_POR_CLASE["TRANSITORIO"] == 5
    assert politica.LIMITES["DETERMINISTA"] == 0


# ------------------------------------------------- 1. AGOTABLE ya no 24 h


def test_1_agotable_elegible_a_los_30_min_no_a_las_24_h(op):
    op.sembrar([_fila("474597", "COORDENADA_NO_CONFIRMADA(5)", op.planta_id)], minutos=0)
    for minutos, esperado in ((29, []), (30, ["474597"]), (60, ["474597"])):
        plan = op.mantener(AHORA + timedelta(minutes=minutos), solo_plan=True)
        assert [e["numero_guia"] for e in plan["elegibles"]] == esperado, minutos


def test_1b_agotable_tiene_limite_finito(op, espia):
    op.sembrar([_fila("474597", "COORDENADA_NO_CONFIRMADA(5)", op.planta_id)],
               minutos=24 * 60, intentos=3)
    assert op.mantener()["elegibles"] == []
    assert espia == []
    # Agotado: la acción humana queda visible como tarjeta, no en la cola.
    assert "474597" not in op.pendientes()
    assert [d["tipo"] for d in op.decisiones() if d["documento"]["numero_guia"] == "474597"] == [
        "DESTINO_NO_RESUELTO"]


# ---------------------------------------------- 2. TRANSITORIO ya no 6 h


def test_2_transitorio_elegible_a_los_30_min_no_a_las_6_h(op):
    op.sembrar([_fila("474597", "GEOCODIFICACION_SIN_CONEXION", op.planta_id)], minutos=0)
    for minutos, esperado in ((29, []), (30, ["474597"])):
        plan = op.mantener(AHORA + timedelta(minutes=minutos), solo_plan=True)
        assert [e["numero_guia"] for e in plan["elegibles"]] == esperado, minutos


def test_2b_transitorio_tope_finito_y_proveedor_protegido(op, espia):
    op.sembrar([_fila("474597", "GEOCODIFICACION_SIN_CONEXION", op.planta_id)], minutos=600, intentos=5)
    assert op.mantener()["elegibles"] == []
    assert espia == []
    assert op.pendientes()["474597"]["estado_espera"] == "ESPERANDO_PROVEEDOR"


def test_2c_una_pasada_atiende_un_numero_acotado_de_guias(op, espia):
    filas = [_fila(f"4745{n:02d}", "GEOCODIFICACION_SIN_CONEXION", op.planta_id)
             for n in range(mantenimiento.MAX_GUIAS_POR_PASADA + 5)]
    op.sembrar(filas)
    # La más antigua primero: las 5 últimas quedan con un intento reciente.
    pendientes = op.pendientes()
    for fila in filas[-5:]:
        pendientes[fila["numero_guia"]]["ultimo_intento"] = (AHORA - timedelta(minutes=30)).isoformat()
    op.escribir_pendientes(list(pendientes.values()))
    proveedor = _proveedor()
    resultado = op.mantener(proveedor_rutas=proveedor)
    atendidas = {e["numero_guia"] for e in resultado["elegibles"]}
    assert len(atendidas) == mantenimiento.MAX_GUIAS_POR_PASADA
    assert atendidas.isdisjoint({f["numero_guia"] for f in filas[-5:]})
    assert all(len(guias) <= mantenimiento.MAX_GUIAS_POR_PASADA for _, guias in espia)
    # Las diferidas siguen elegibles en la pasada siguiente (5 min).
    siguiente = op.mantener(AHORA + timedelta(minutes=5), solo_plan=True)
    assert {e["numero_guia"] for e in siguiente["elegibles"]} == {f["numero_guia"] for f in filas[-5:]}


# ------------------------------------------ 3. DETERMINISTA sin polling


def test_3_determinista_no_hace_polling_aunque_pasen_dias(op, espia):
    op.sembrar([_fila("474597", "GEOCODIFICACION_CONTRADICE_COMUNA_DOCUMENTAL", op.planta_id)])
    proveedor = _proveedor()
    contenido = (op.actual / "pendientes_tecnicos.json").read_bytes()
    for dias in (1, 7, 30):
        resultado = op.mantener(AHORA + timedelta(days=dias), proveedor_rutas=proveedor)
        assert resultado["elegibles"] == []
    assert espia == []
    assert proveedor.llamadas_geocodificacion == proveedor.llamadas_ruta == 0
    # Idempotente: ni siquiera reescribe su propio seguimiento.
    op.mantener(AHORA + timedelta(days=31))
    assert (op.actual / "pendientes_tecnicos.json").read_bytes() != b""
    antes = (op.actual / "pendientes_tecnicos.json").read_bytes()
    assert op.mantener(AHORA + timedelta(days=32))["motivo"] == "SIN_ELEGIBLES"
    assert (op.actual / "pendientes_tecnicos.json").read_bytes() == antes
    assert contenido  # sembrado real, no archivo vacío


# ------------------------------- 4. cambio relevante => revalidación focal


def test_4_catalogo_confirmado_revalida_determinista_de_inmediato(op, espia, monkeypatch):
    """Cambio de catálogo: el propio guardado dispara la revalidación
    focal -- sin esperar reloj -- y sólo sobre la guía vinculada."""
    op.sembrar([
        _fila("474597", "GEOCODIFICACION_CONTRADICE_COMUNA_DOCUMENTAL", op.planta_id),
        _fila("474599", "GEOCODIFICACION_CONTRADICE_COMUNA_DOCUMENTAL", op.planta_id,
              despachar_a_crudo="OTRA CALLE 10", obra_destino="OTRA OBRA"),
    ], minutos=1)
    proveedor = _proveedor()
    original = mantenimiento.mantener_pendientes_tecnicos
    monkeypatch.setattr(mantenimiento, "mantener_pendientes_tecnicos", lambda **kw: original(
        **kw, reloj=lambda: AHORA, proveedor_rutas=proveedor, proveedor_rutas_fallback=_proveedor()))

    op.confirmar_destino_de_obra(con_coordenadas=True)

    filas = _leer_csv(op.dataset)
    assert filas["474597"]["estado_ruta"] == "RUTA_CALCULADA"
    assert filas["474599"]["estado_ruta"] == "REQUIERE_REVISION"
    # Dos cambios de conocimiento (destino nuevo; luego relación
    # obra->destino): el primero aún no alcanza internamente y consulta la
    # red UNA vez; el segundo resuelve con la coordenada confirmada.
    assert espia == [
        ("interno", frozenset({"474597"})), ("externo", frozenset({"474597"})),
        ("interno", frozenset({"474597"})),
    ]
    assert proveedor.llamadas_geocodificacion == 1
    assert "474597" not in op.pendientes()


def test_4b_intervencion_humana_en_ledger_despierta_solo_esa_guia(op):
    op.sembrar([
        _fila("474597", "GEOCODIFICACION_CONTRADICE_COMUNA_DOCUMENTAL", op.planta_id),
        _fila("474599", "GEOCODIFICACION_CONTRADICE_COMUNA_DOCUMENTAL", op.planta_id),
    ])
    assert op.mantener(solo_plan=True)["elegibles"] == []
    (op.actual / "decisiones_aplicadas.json").write_text(json.dumps({"aplicaciones": [{
        "decision_id": "d-1", "tipo": "CORREGIR_COMUNA", "documento": {"numero_guia": "474597"},
    }]}), encoding="utf-8")
    assert op.mantener(solo_plan=True)["elegibles"] == [
        {"numero_guia": "474597", "causa": "CONOCIMIENTO_CAMBIO", "clase": "DETERMINISTA"},
    ]


def test_4c_cambio_de_reglas_o_capacidad_despierta_determinista(op, monkeypatch):
    op.sembrar([_fila("474597", "GEOCODIFICACION_CONTRADICE_COMUNA_DOCUMENTAL", op.planta_id)])
    assert op.mantener(solo_plan=True)["elegibles"] == []
    monkeypatch.setattr(mantenimiento, "RULESET_VERSION", reconciliacion.RULESET_VERSION + 1)
    assert [e["causa"] for e in op.mantener(solo_plan=True)["elegibles"]] == ["CONOCIMIENTO_CAMBIO"]


def test_4d_enganche_de_catalogo_nunca_rompe_el_guardado(op, monkeypatch):
    op.sembrar([_fila("474597", "COORDENADA_NO_CONFIRMADA(5)", op.planta_id)], minutos=1)

    def _explota(**_kw):
        raise RuntimeError("proveedor caído")

    monkeypatch.setattr(mantenimiento, "mantener_pendientes_tecnicos", _explota)
    destino_id = op.confirmar_destino_de_obra(con_coordenadas=True)
    assert op.destinos.obtener(destino_id).latitud == -33.45
    resultado = revalidar_tras_cambio_catalogo(op.catalogos / "destinos_maestros.json",
                                               destino=op.destinos.obtener(destino_id))
    assert resultado["motivo"] == "ERROR_REVALIDACION_REACTIVA"


# ------------------------------- 5. conocimiento interno antes que la red


def test_5_interno_resuelve_sin_geocodificar_y_sin_etapa_externa(op, espia):
    op.confirmar_destino_de_obra(con_coordenadas=True)
    op.sembrar([_fila("474597", "GEOCODIFICACION_SIN_CONEXION", op.planta_id)])
    principal, respaldo = _proveedor(), _proveedor()
    resultado = op.mantener(proveedor_rutas=principal, proveedor_rutas_fallback=respaldo)
    assert resultado["resueltas"] == ["474597"]
    assert espia == [("interno", frozenset({"474597"}))]
    assert principal.llamadas_geocodificacion == respaldo.llamadas_geocodificacion == 0
    assert principal.llamadas_ruta == 1


def test_5b_interno_precede_a_la_red_cuando_no_alcanza(op, espia):
    op.sembrar([_fila("474597", "GEOCODIFICACION_SIN_CONEXION", op.planta_id)])
    op.mantener()
    assert [etapa for etapa, _ in espia] == ["interno", "externo"]


def test_5c_destino_confirmado_sin_coordenada_se_abstiene_no_contradice(op):
    op.confirmar_destino_de_obra(con_coordenadas=False)
    _escribir_csv(op.dataset, [_fila("474597", "COORDENADA_NO_CONFIRMADA(5)", op.planta_id)])
    proveedor = _proveedor()
    resultado = revalidar_ruta_con_destino_confirmado_en_catalogo_sin_ocr(
        ruta_dataset=op.dataset, carpeta_catalogos=op.catalogos,
        proveedor_rutas=proveedor, proveedor_rutas_fallback=_proveedor(),
        guias_objetivo={"474597"}, solo_con_coordenadas=True,
    )
    assert resultado["guias_actualizadas"] == resultado["guias_contradiccion"] == []
    assert _leer_csv(op.dataset)["474597"]["motivo_ruta"] == "COORDENADA_NO_CONFIRMADA(5)"
    assert proveedor.llamadas_geocodificacion == 0


# ------------------------- 6. sin evidencia nueva no se multiplican llamadas


def test_6_agotable_sin_evidencia_nueva_nunca_repite_red(op, espia):
    op.sembrar([_fila("474597", "COORDENADA_NO_CONFIRMADA(5)", op.planta_id)], intentos=0)
    proveedor, respaldo = _proveedor(), _proveedor()
    for paso in range(0, 24 * 60, 5):  # un día de tarea cada 5 min
        op.mantener(AHORA + timedelta(minutes=paso), proveedor_rutas=proveedor,
                    proveedor_rutas_fallback=respaldo)
    assert proveedor.llamadas_geocodificacion == respaldo.llamadas_geocodificacion == 0
    assert all(etapa == "interno" for etapa, _ in espia)
    assert len(espia) == 3  # límite AGOTABLE, luego converge
    # Convergencia: sale de la cola técnica hacia una tarjeta humana.
    assert "474597" not in op.pendientes()
    decisiones = json.loads((op.actual / "decisiones_pendientes.json").read_text(encoding="utf-8"))
    assert [d["tipo"] for d in decisiones["decisiones"]
            if d["documento"]["numero_guia"] == "474597"] == ["DESTINO_NO_RESUELTO"]


def test_6b_transitorio_llamadas_acotadas_en_un_dia(op, espia):
    op.sembrar([_fila("474597", "GEOCODIFICACION_SIN_CONEXION", op.planta_id)], intentos=0)
    for paso in range(0, 24 * 60, 5):
        op.mantener(AHORA + timedelta(minutes=paso))
    externos = [g for etapa, g in espia if etapa == "externo"]
    assert len(externos) == 5  # tope TRANSITORIO, nunca 288 pasadas
    assert op.pendientes()["474597"]["estado_espera"] == "ESPERANDO_PROVEEDOR"


# ------------------------------------------- 7. concurrencia / idempotencia


def test_7_elegibilidad_se_recalcula_bajo_lock(op, espia, monkeypatch):
    """Selección fuera del lock (solo_plan) vs. dentro: si otro proceso
    resolvió la guía entre medio, el mantenimiento no la intenta."""
    op.sembrar([_fila("474597", "COORDENADA_NO_CONFIRMADA(5)", op.planta_id)])
    assert op.mantener(solo_plan=True)["elegibles"]
    original = mantenimiento.bloqueo_sesion

    def _bloqueo_y_otro_proceso_resuelve(directorio, nombre, **kw):
        filas = _leer_csv(op.dataset)
        filas["474597"].update(estado_ruta="RUTA_CALCULADA", motivo_ruta="", estado_operacional="OK")
        _escribir_csv(op.dataset, list(filas.values()))
        return original(directorio, nombre, **kw)

    monkeypatch.setattr(mantenimiento, "bloqueo_sesion", _bloqueo_y_otro_proceso_resuelve)
    resultado = op.mantener()
    assert espia == []
    assert resultado["elegibles"] == []


def test_7b_decision_humana_en_curso_no_compite(op, espia):
    op.sembrar([_fila("474597", "COORDENADA_NO_CONFIRMADA(5)", op.planta_id)])
    (op.actual / ".atlas_lock_aplicar_decision_obra").write_text("{}", encoding="utf-8")
    assert op.mantener()["motivo"] == "DECISION_EN_CURSO"
    assert espia == []


def test_7c_reintento_inmediato_no_duplica_intento(op, espia):
    op.sembrar([_fila("474597", "COORDENADA_NO_CONFIRMADA(5)", op.planta_id)])
    op.mantener()
    op.mantener()
    op.mantener(AHORA + timedelta(minutes=1))
    assert len(espia) == 1
    assert op.pendientes()["474597"]["intentos_misma_evidencia"] == 2


# ------------------------------------------- 8. resuelta deja de ser elegible


def test_8_guia_resuelta_sale_de_la_cola_y_no_vuelve(op, espia):
    op.confirmar_destino_de_obra(con_coordenadas=True)
    op.sembrar([_fila("474597", "COORDENADA_NO_CONFIRMADA(5)", op.planta_id)])
    assert op.mantener()["resueltas"] == ["474597"]
    assert "474597" not in op.pendientes()
    for minutos in (30, 60, 24 * 60):
        assert op.mantener(AHORA + timedelta(minutes=minutos))["elegibles"] == []
    assert len(espia) == 1


# ------------------------------------------------- 9. reinicio del proceso


def test_9_reinicio_retoma_vencidos_desde_disco(op, espia):
    op.sembrar([
        _fila("474597", "COORDENADA_NO_CONFIRMADA(5)", op.planta_id),
        _fila("474598", "GEOCODIFICACION_SIN_CONEXION", op.planta_id),
    ], minutos=0)
    op.mantener(AHORA)  # nada vencido todavía
    # "Reinicio": sin estado en memoria, sólo lo persistido; el PC estuvo
    # apagado 3 horas.
    politica._CACHE_JSON.clear()
    resultado = op.mantener(AHORA + timedelta(hours=3))
    assert {e["numero_guia"] for e in resultado["elegibles"]} == {"474597", "474598"}


# ---------------------------------- 10. el comando focal no reprocesa viajes


def test_10_sin_cambios_no_regenera_reporte_ni_toca_otras_filas(op, monkeypatch):
    resuelta = _fila("474600", "", op.planta_id, estado_ruta="RUTA_CALCULADA",
                     estado_operacional="OK", distancia_km="10", duracion_min="20")
    op.sembrar([_fila("474597", "COORDENADA_NO_CONFIRMADA(5)", op.planta_id), resuelta])
    reportes = []
    monkeypatch.setattr(mantenimiento, "generar_reporte_viajes", lambda *a, **k: reportes.append(a))
    objetivos = []
    original = mantenimiento.reconciliar_decisiones_destino_no_resuelto
    monkeypatch.setattr(mantenimiento, "reconciliar_decisiones_destino_no_resuelto",
                        lambda **kw: objetivos.append(kw["guias_objetivo"]) or original(**kw))
    antes = op.dataset.read_bytes()
    resultado = op.mantener()
    assert resultado["ejecutado"] is True and resultado["reporte_regenerado"] is False
    assert reportes == []
    assert objetivos == [{"474597"}]
    assert op.dataset.read_bytes() == antes


def test_10b_resolucion_regenera_reporte_una_vez(op, monkeypatch):
    op.confirmar_destino_de_obra(con_coordenadas=True)
    op.sembrar([_fila("474597", "COORDENADA_NO_CONFIRMADA(5)", op.planta_id)])
    reportes = []

    def _reporte(_dataset, salida, **_kw):
        reportes.append(salida)
        salida.mkdir(parents=True)
        return {"totales": {}}

    monkeypatch.setattr(mantenimiento, "generar_reporte_viajes", _reporte)
    resultado = op.mantener()
    assert resultado["reporte_regenerado"] is True and len(reportes) == 1
    assert op.mantener(AHORA + timedelta(minutes=5))["motivo"] == "SIN_ELEGIBLES"
    assert len(reportes) == 1


def test_10c_solo_plan_es_read_only(op):
    op.sembrar([_fila("474597", "COORDENADA_NO_CONFIRMADA(5)", op.planta_id)])
    antes = {p.name: p.read_bytes() for p in op.actual.iterdir()}
    assert op.mantener(solo_plan=True)["elegibles"]
    assert {p.name: p.read_bytes() for p in op.actual.iterdir()} == antes
