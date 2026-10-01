"""Coordenadas de destino nunca heredadas ni aproximadas (caso Los Trapenses):

1. Convergencia GPS por obra + DIRECCIÓN: el GPS de las entregas a una
   dirección nunca rellena ni rutea otra dirección de la misma obra.
2. POI distintos de una misma comuna, dispersos > 1 km, no se colapsan en
   uno por compartir localidad/región: abstención y ruta pendiente.
3. La comuna confirmada por un humano se conserva aunque la ruta no resuelva.
4. Acción controlada para retirar una coordenada no verificada de un destino
   CONFIRMADO y dejar pendiente la ruta de sus guías.
Datos sintéticos; nunca G: ni red."""
from __future__ import annotations

import csv
import hashlib
import json
from datetime import date

from atlas_core.acciones_operacionales import CapaAccionesOperacionales
from atlas_core.aplicacion_decisiones import aplicar_decision_obra
from atlas_core.catalogo_destinos import CatalogoDestinos, EstadoCalidadDestino
from atlas_core.decisiones_pendientes import detectar_decision_destino_no_resuelto
from atlas_core.revalidacion_documental import revalidar_ruta_por_convergencia_gps_historica_sin_ocr
from atlas_core.rutas.destino_entrega import resolver_destino_entrega
from atlas_core.rutas.modelos import (
    CandidatoGeocodificacion, Coordenadas, EstadoRuta, ResultadoGeocodificacion, ResultadoRuta,
)
from atlas_core.rutas.proveedor import ProveedorRutasSimulado
from atlas_core.telemetria.proveedor import ProveedorTelemetriaSoloCache
from atlas_core.telemetria.repositorio import RepositorioTelemetria
from atlas_core.telemetria.servicio import ServicioTelemetria
from tests.test_acciones_operacionales import entorno  # noqa: F401 -- fixture
from tests.test_destino_no_resuelto_r6 import _cliente_dict, _entorno, _fila_csv as _fila_r6, _leer_csv, _obra_dict, _publicar
from tests.test_final_core_v1 import COORD_AUSIN, _cachear_trip_con_destino, _catalogos, _escribir_csv, _fila_csv

# ------------------------------------------------------------ 2. POI dispersos de una misma comuna


def _poi(nombre, lat, lon, confianza):
    return CandidatoGeocodificacion(Coordenadas(lon, lat), f"{nombre}, Lo Barnechea, RM, Chile", confianza,
                                    "Lo Barnechea", "Metropolitana")


POIS = (_poi("Núcleo Los Trapenses", -33.355291, -70.539768, 0.8),
        _poi("Mall Paseo Los Trapenses", -33.343434, -70.544767, 0.8),
        _poi("Rotonda Los Trapenses", -33.325256, -70.542281, 1.0),
        _poi("Vitamina Los Trapenses", -33.345888, -70.543271, 0.8),
        _poi("Pasaje Los Trapenses", -33.33047, -70.544007, 1.0))


def test_poi_distintos_de_una_comuna_no_se_colapsan_en_rotonda():
    texto = "AV. CAM. LOS TRAPENSES LO BARNECHEA"
    proveedor = ProveedorRutasSimulado(geocodificaciones={
        f"{texto}, Chile": ResultadoGeocodificacion(EstadoRuta.RESULTADO_AMBIGUO, POIS, "MULTIPLES_CANDIDATOS")})
    resultado = resolver_destino_entrega(texto, proveedor)
    assert resultado.estado != "RESUELTO"
    assert resultado.coordenadas is None or (resultado.coordenadas.latitud, resultado.coordenadas.longitud) != (
        -33.325256, -70.542281)
    assert "UBICACIONES_DISPERSAS" in resultado.motivo or "COORDENADA_NO_CONFIRMADA" in resultado.motivo


def test_mismo_rasgo_impreciso_de_una_comuna_sigue_colapsando():
    a = CandidatoGeocodificacion(Coordenadas(-73.163227, -37.002896), "Coronel, BI, Chile", 0.6, "Coronel", "Del Bio-Bio")
    b = CandidatoGeocodificacion(Coordenadas(-73.151, -37.019549), "Coronel, BI, Chile", 0.7, "Coronel", "Del Bio-Bio")
    proveedor = ProveedorRutasSimulado(geocodificaciones={
        "CALLE DEMO CORONEL, Chile": ResultadoGeocodificacion(EstadoRuta.RESULTADO_AMBIGUO, (a, b), "MULTIPLES")})
    assert resolver_destino_entrega("CALLE DEMO CORONEL", proveedor).estado == "RESUELTO"


# ------------------------------------------------------------ 1. convergencia GPS por dirección


def test_gps_de_la_direccion_a_nunca_rellena_ni_rutea_la_direccion_b_de_la_misma_obra(tmp_path):
    carpeta, planta_colina, planta_renca = _catalogos(tmp_path)
    otra = "CAMINO OTRO 77 SAN BERNARDO"
    dataset = tmp_path / "dataset.csv"
    _escribir_csv(dataset, [
        _fila_csv(numero_guia="460807", fecha="18-08-2026", estado_ruta="RUTA_CALCULADA", motivo_ruta="",
                  planta_origen_id=planta_renca.planta_id),
        _fila_csv(numero_guia="472008", fecha="19-08-2026", estado_ruta="RUTA_CALCULADA", motivo_ruta="",
                  planta_origen_id=planta_colina.planta_id),
        _fila_csv(numero_guia="480000", fecha="20-08-2026", despachar_a_crudo=otra, patente_tracto="ZZ9999",
                  planta_origen_id=planta_colina.planta_id),
    ])
    destinos = CatalogoDestinos(carpeta / "destinos_maestros.json", ruta_clientes=carpeta / "clientes.json")
    destino_a = destinos.crear(cliente_id="", nombre_destino="INTERIOR NUEVA O1148 SAN BERNARDO",
                               direccion="INTERIOR NUEVA O1148 SAN BERNARDO", pais="CHILE", fuente="TEST",
                               estado_calidad=EstadoCalidadDestino.CONFIRMADO)
    destino_b = destinos.crear(cliente_id="", nombre_destino=otra, direccion=otra, pais="CHILE", fuente="TEST",
                               estado_calidad=EstadoCalidadDestino.CONFIRMADO)
    from atlas_core.catalogo_clientes import CatalogoClientes, EstadoCalidadCliente
    from atlas_core.catalogo_obras_destinos import CatalogoObrasDestinos, Evidencia, TipoEvidencia
    cliente = CatalogoClientes(carpeta / "clientes.json").crear(
        razon_social="CLIENTE PRUEBA", rut="50.234.350-5", fuente="TEST", estado_calidad=EstadoCalidadCliente.CONFIRMADO)
    obras = CatalogoObrasDestinos(ruta=carpeta / "obras_destinos.json", ruta_clientes=carpeta / "clientes.json",
                                  ruta_destinos=carpeta / "destinos_maestros.json")
    for destino, guia in ((destino_a, "460807"), (destino_b, "480000")):
        obras.registrar_observacion(
            cliente_id=cliente.cliente_id, nombre_obra="AUSIN SAN BERNARDO", destino_id=destino.destino_id,
            evidencia=Evidencia(tipo=TipoEvidencia.GUIA.value, identificador_fuente=guia, referencia_hash=guia * 8,
                                campos_observados={"obra": "AUSIN SAN BERNARDO"}, fecha="2026-01-01T00:00:00+00:00",
                                actor_proceso="test", resultado="SOPORTA"))
    for relacion in obras.listar_relaciones():
        obras.confirmar_relacion(relacion.relacion_id, actor="test")
    repo = RepositorioTelemetria(carpeta / "telemetria_cache.json")
    for dia in (18, 19):
        _cachear_trip_con_destino(repo, patente="AL1879", fecha_iso=date(2026, 8, dia),
                                  fecha_doc=f"2026-08-{dia}", punto_destino=COORD_AUSIN)
    proveedor = ProveedorRutasSimulado(resultado_ruta=ResultadoRuta(EstadoRuta.RUTA_CALCULADA, 20.0, 30.0, "SINTETICO"))
    resultado = revalidar_ruta_por_convergencia_gps_historica_sin_ocr(
        ruta_dataset=dataset, carpeta_catalogos=carpeta, proveedor_rutas=proveedor,
        servicio_telemetria=ServicioTelemetria(ProveedorTelemetriaSoloCache(nombre="onelogis"), repo))
    assert destino_a.destino_id in resultado["destinos_aprendidos"]  # A aprende de sus propias entregas
    assert destino_b.destino_id not in resultado["destinos_aprendidos"]
    b = destinos.obtener(destino_b.destino_id)
    assert (b.latitud, b.longitud) == (None, None)  # el GPS de A nunca rellena B
    filas = {f["numero_guia"]: f for f in csv.DictReader(dataset.open(encoding="utf-8-sig"), delimiter=";")}
    assert filas["480000"]["estado_ruta"] != "RUTA_CALCULADA"  # ni rutea B al punto de A
    assert "480000" not in resultado["guias_actualizadas"]


# ------------------------------------------------------------ 3. comuna confirmada sin ruta


def test_direccion_y_comuna_confirmadas_se_conservan_aunque_la_ruta_no_resuelva(tmp_path):
    fila = _fila_r6(despachar_a_crudo="CAMINO SIN NUMERO LAS CONDES LAS CO")
    entorno_r6 = _entorno(tmp_path, filas_csv=[fila], clientes=[_cliente_dict()], obras=[_obra_dict()])
    decision = detectar_decision_destino_no_resuelto(archivo="472037.jpeg", fila=fila)
    _publicar(entorno_r6, decision)
    sin_resultado = ProveedorRutasSimulado(resultado_ruta=ResultadoRuta(EstadoRuta.RUTA_CALCULADA, 1.0, 1.0, "X"))
    resultado = aplicar_decision_obra(
        raiz_atlas=entorno_r6["raiz"], decision_id=decision["decision_id"], accion="REGISTRAR_DIRECCION",
        direccion_manual="CAMINO SIN NUMERO", comuna_manual="LAS CONDES",
        proveedor_rutas=sin_resultado, proveedor_rutas_fallback=sin_resultado)
    assert resultado["ruta_resuelta"] is False
    fila_final = _leer_csv(entorno_r6["dataset"])[0]
    assert fila_final["despachar_a_crudo"] == "CAMINO SIN NUMERO"
    assert fila_final["localidad_entrega"] == "LAS CONDES"
    assert fila_final["estado_ruta"] != "RUTA_CALCULADA" and fila_final["distancia_km"] == ""
    if resultado.get("destino_id"):
        destino = CatalogoDestinos(entorno_r6["catalogos"] / "destinos_maestros.json",
                                   ruta_clientes=entorno_r6["catalogos"] / "clientes.json").obtener(resultado["destino_id"])
        assert destino.comuna == "LAS CONDES" and destino.latitud is None


# ------------------------------------------------------------ 4. acción controlada de reparación

DIRECCION, OTRA = "AV. CAM. EL ROBLE", "SAN ANDRES 0100"
PUNTO_AJENO = (-33.375077, -70.527403)


def _preparar(entorno):  # noqa: F811
    destinos = CatalogoDestinos(entorno["cat"] / "destinos_maestros.json", ruta_clientes=entorno["cat"] / "clientes.json")
    contaminado = destinos.crear(cliente_id="", nombre_destino=DIRECCION, direccion=DIRECCION, pais="CHILE",
                                 fuente="TEST", latitud=PUNTO_AJENO[0], longitud=PUNTO_AJENO[1],
                                 estado_calidad=EstadoCalidadDestino.CONFIRMADO)
    legitimo = destinos.crear(cliente_id="", nombre_destino=OTRA, direccion=OTRA, comuna="VITACURA", pais="CHILE",
                              fuente="TEST", latitud=PUNTO_AJENO[0], longitud=PUNTO_AJENO[1],
                              estado_calidad=EstadoCalidadDestino.CONFIRMADO)
    ruta = entorno["dataset"]
    with ruta.open(encoding="utf-8-sig", newline="") as flujo:
        lector = csv.DictReader(flujo, delimiter=";")
        columnas, filas = lector.fieldnames, list(lector)
    for fila in filas:
        fila.update({"despachar_a_crudo": DIRECCION if fila["numero_guia"] == "500001" else OTRA,
                     "estado_ruta": "RUTA_CALCULADA", "motivo_ruta": "", "distancia_km": "30.9",
                     "duracion_min": "40", "proveedor_ruta": "openrouteservice"})
    with ruta.open("w", encoding="utf-8-sig", newline="") as flujo:
        escritor = csv.DictWriter(flujo, fieldnames=columnas, delimiter=";")
        escritor.writeheader()
        escritor.writerows(filas)
    capa = CapaAccionesOperacionales(entorno["raiz"])
    capa.revalidadas = []
    capa._revalidar_guias = lambda guias: capa.revalidadas.append(sorted(guias)) or {"ejecutado": True}
    return destinos, contaminado, legitimo, capa


def _filas(entorno):  # noqa: F811
    with entorno["dataset"].open(encoding="utf-8-sig", newline="") as flujo:
        return {f["numero_guia"]: f for f in csv.DictReader(flujo, delimiter=";")}


def _sha(ruta):
    return hashlib.sha256(ruta.read_bytes()).hexdigest()


def test_retirar_coordenada_no_verificada_deja_ruta_pendiente_sin_tocar_otro_destino(entorno):  # noqa: F811
    destinos, contaminado, legitimo, capa = _preparar(entorno)
    antes = {n: _sha(p) for n, p in (("dataset", entorno["dataset"]),
                                     ("destinos", entorno["cat"] / "destinos_maestros.json"))}
    otra_antes = _filas(entorno)["500002"]
    preview = capa.previsualizar("DESTINO_RETIRAR_COORDENADA_NO_VERIFICADA",
                                 {"destino_id": contaminado.destino_id, "guias": ["500001"], "comuna": "Las Condes",
                                  "referencia": "prueba"}, actor="REPARACION", origen="HUMANO", referencia="prueba")
    assert preview["estado"] == "PREVIEW", preview
    assert {n: _sha(p) for n, p in (("dataset", entorno["dataset"]),
                                    ("destinos", entorno["cat"] / "destinos_maestros.json"))} == antes
    r = capa.ejecutar(preview["token"], actor="REPARACION", origen="HUMANO", confirmado_por="JAVIER")
    assert r["estado"] == "APLICADA", r
    reparado = destinos.obtener(contaminado.destino_id)
    assert (reparado.latitud, reparado.longitud) == (None, None)
    assert reparado.comuna == "LAS CONDES" and reparado.direccion == DIRECCION and reparado.estado_calidad == "CONFIRMADO"
    assert "COORDENADA_RETIRADA_NO_VERIFICADA" in reparado.observacion
    intacto = destinos.obtener(legitimo.destino_id)
    assert (intacto.latitud, intacto.longitud, intacto.comuna) == (*PUNTO_AJENO, "VITACURA")
    filas = _filas(entorno)
    objetivo = filas["500001"]
    assert objetivo["despachar_a_crudo"] == DIRECCION and objetivo["localidad_entrega"] == "LAS CONDES"
    assert (objetivo["estado_ruta"], objetivo["motivo_ruta"]) == ("REQUIERE_REVISION", "COORDENADA_NO_CONFIRMADA")
    assert objetivo["distancia_km"] == objetivo["duracion_min"] == objetivo["proveedor_ruta"] == ""
    assert filas["500002"] == otra_antes  # otra guía intacta
    assert capa.revalidadas == [["500001"]]  # revalidación focal sólo de la guía reparada
    auditoria = capa.auditoria()[-1]
    assert auditoria["accion"] == "DESTINO_RETIRAR_COORDENADA_NO_VERIFICADA" and auditoria["confirmado_por"] == "JAVIER"


def test_guia_con_otra_direccion_se_rechaza_sin_escribir(entorno):  # noqa: F811
    _destinos, contaminado, _legitimo, capa = _preparar(entorno)
    sha = _sha(entorno["dataset"])
    preview = capa.previsualizar("DESTINO_RETIRAR_COORDENADA_NO_VERIFICADA",
                                 {"destino_id": contaminado.destino_id, "guias": ["500002"]},
                                 actor="REPARACION", origen="HUMANO")
    assert preview["estado"] == "RECHAZADA" and preview["codigo"] == "PRECONDICION_FALLIDA"
    assert _sha(entorno["dataset"]) == sha and capa.auditoria() == []
