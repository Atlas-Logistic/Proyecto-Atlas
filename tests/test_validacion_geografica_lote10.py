"""Bloque VALIDACIÓN GEOGRÁFICA OBLIGATORIA + DESTINOS CONFIRMADOS
COMPLETOS + PUBLICACIÓN DEL DROP -- correcciones detectadas en el lote
real de 10 guías:

- 0000353303/464784: documento "URUGUAY 15 ... LA CISTERNA" (RM), Atlas
  aceptó en silencio una geocodificación en Temuco (Araucanía), 709 km.
- 0000353312/464781: destino CONFIRMADO sin coordenadas -> INCOMPLETO_
  TECNICO transitorio hasta que la reconciliación lo re-geocodifica.
- 0000353055/464715: destino PENDIENTE degradado por OCR ("SAN JOA").
- version_estado_derivado borrado por `generar_reporte_viajes` -> la
  reconciliación siguiente trataba el dataset vigente como migración
  completa v0->N.
"""
import csv
import json

from atlas_core.almacenamiento_portable import escribir_estado_operacion, leer_estado_operacion
from atlas_core.catalogo_destinos import CatalogoDestinos, EstadoCalidadDestino
from atlas_core.procesamiento_masivo import COLUMNAS
from atlas_core.revalidacion_documental import (
    revalidar_destino_contra_comuna_documental_sin_ocr,
    revalidar_destinos_confirmados_sin_coordenadas_sin_ocr,
)
from atlas_core.rutas.destino_entrega import (
    ESTADO_RESUELTO, ESTADO_REVISAR,
    _numero_direccion_incompatible, resolver_destino_entrega_validado,
    texto_destino_degradado,
)
from atlas_core.catalogo_destinos import normalizar_nombre_destino
from atlas_core.rutas.modelos import (
    CandidatoGeocodificacion, Coordenadas, EstadoRuta, ResultadoGeocodificacion, ResultadoRuta,
)
from atlas_core.rutas.proveedor import ProveedorRutasSimulado


class _ProvFijo(ProveedorRutasSimulado):
    """Devuelve SIEMPRE el mismo candidato (confianza alta, un solo
    resultado), sin depender del texto EXACTO de la consulta que
    `resolver_destino_entrega` arma internamente."""

    def __init__(self, *, etiqueta, localidad, region, confianza=0.95):
        super().__init__(resultado_ruta=ResultadoRuta(EstadoRuta.RUTA_CALCULADA, 12.0, 20.0, "SINTETICO"))
        self._cand = CandidatoGeocodificacion(
            Coordenadas(-70.65, -33.5), etiqueta, confianza, localidad, region,
        )

    def geocodificar(self, direccion):
        self.llamadas_geocodificacion += 1
        return ResultadoGeocodificacion(EstadoRuta.REQUIERE_REVISION, (self._cand,), "")

    def geocodificar_estructurado(self, direccion, contexto):
        return self.geocodificar(direccion)


def _prov(direccion, *, etiqueta, localidad, region, confianza=0.95):
    return _ProvFijo(etiqueta=etiqueta, localidad=localidad, region=region, confianza=confianza)


# =====================================================================
# 1) Validación geográfica obligatoria
# =====================================================================

def test_regresion_la_cisterna_no_puede_quedar_resuelta_en_temuco():
    direccion = "URUGUAY 15 SANTIAGO LA CISTERNA"
    prov = _prov(
        direccion, etiqueta="1545 Uruguay, Temuco, AR, Chile",
        localidad="Temuco", region="De La Araucania",
    )
    r = resolver_destino_entrega_validado(direccion, prov, contexto_territorial="Chile")
    assert r.estado == ESTADO_REVISAR
    assert "GEOCODIFICACION_CONTRADICE_COMUNA_DOCUMENTAL" in r.motivo
    assert "La Cisterna" in r.motivo and "Temuco" in r.motivo
    # Nunca expone la localidad/región del punto rechazado.
    assert r.localidad == "" and r.region == ""


def test_comuna_y_region_coincidentes_si_permiten_resolver():
    direccion = "AVDA IRARRAZAVAL 5497 SANTIAGO NUNOA"
    prov = _prov(
        direccion, etiqueta="Av Irarrazaval 5497, Nunoa, RM, Chile",
        localidad="Nunoa", region="Metropolitana",
    )
    r = resolver_destino_entrega_validado(direccion, prov, contexto_territorial="Chile")
    assert r.estado == ESTADO_RESUELTO
    assert r.localidad == "Nunoa"


def test_santiago_como_etiqueta_de_area_no_bloquea_la_comuna_especifica():
    # "SANTIAGO MAIPU": Santiago es la ciudad, Maipú la comuna -- y el
    # resultado geocodificado en Maipú (misma región) NO es contradicción.
    direccion = "CAMINO A MELIPILLA 10800 SANTIAGO MAIPU"
    prov = _prov(
        direccion, etiqueta="Camino a Melipilla 10800, Maipu, RM, Chile",
        localidad="Maipu", region="Metropolitana",
    )
    r = resolver_destino_entrega_validado(direccion, prov, contexto_territorial="Chile")
    assert r.estado == ESTADO_RESUELTO


def test_numero_de_casa_incompatible_por_orden_de_magnitud_degrada():
    assert _numero_direccion_incompatible("URUGUAY 15 LA CISTERNA", "1545 Uruguay, Temuco") is True
    assert _numero_direccion_incompatible("PDTE RIESCO 5903 LAS CONDES", "Av Pdte Riesco 5903") is False
    assert _numero_direccion_incompatible("SIN NUMERO DOCUMENTAL", "Calle X 1234") is False  # ausencia != contradicción
    assert _numero_direccion_incompatible("CALLE 920 MAIPU", "Calle 5903") is False  # 3 vs 4 dígitos, no se degrada


def test_numero_incompatible_via_resolver_validado():
    direccion = "MOLINA 12 RENCA"
    prov = _prov(direccion, etiqueta="Molina 1234, Renca, RM, Chile", localidad="Renca", region="Metropolitana")
    r = resolver_destino_entrega_validado(direccion, prov, contexto_territorial="Chile")
    assert r.estado == ESTADO_REVISAR
    assert "GEOCODIFICACION_NUMERO_INCOMPATIBLE" in r.motivo


# --- limpieza retroactiva (sin red) ---

def _fila(**ov):
    f = {c: "" for c in COLUMNAS}
    f.update(ov)
    return f


def _escribir(ruta, filas):
    with ruta.open("w", newline="", encoding="utf-8-sig") as a:
        w = csv.DictWriter(a, fieldnames=COLUMNAS, delimiter=";")
        w.writeheader()
        w.writerows(filas)


def test_revalidacion_retroactiva_retira_la_ruta_a_temuco(tmp_path):
    ds = tmp_path / "ds.csv"
    _escribir(ds, [
        _fila(numero_guia="464784", despachar_a_crudo="URUGUAY 15 SANTIAGO LA CISTERNA",
              direccion_entrega="1545 Uruguay, Temuco, AR, Chile", localidad_entrega="Temuco",
              region_entrega="De La Araucania", estado_ruta="RUTA_CALCULADA",
              distancia_km="709.08", duracion_min="787.1"),
        _fila(numero_guia="464780", despachar_a_crudo="AVDA IRARRAZAVAL 5497 SANTIAGO NUNOA",
              direccion_entrega="Av Irarrazaval, Nunoa, RM, Chile", localidad_entrega="Nunoa",
              region_entrega="Metropolitana", estado_ruta="RUTA_CALCULADA",
              distancia_km="30.6", duracion_min="41.0"),
    ])
    res = revalidar_destino_contra_comuna_documental_sin_ocr(ruta_dataset=ds)
    assert res["guias_actualizadas"] == ["464784"]
    filas = {r["numero_guia"]: r for r in csv.DictReader(ds.open(encoding="utf-8-sig"), delimiter=";")}
    assert filas["464784"]["direccion_entrega"] == ""
    assert filas["464784"]["distancia_km"] == ""
    assert filas["464784"]["estado_ruta"] == "REQUIERE_REVISION"
    assert "GEOCODIFICACION_CONTRADICE_COMUNA_DOCUMENTAL" in filas["464784"]["motivo_ruta"]
    # control intacto
    assert filas["464780"]["distancia_km"] == "30.6"


# =====================================================================
# 2) Destinos confirmados completos / degradados
# =====================================================================

def test_texto_destino_degradado_detecta_solo_el_patron_truncado():
    assert texto_destino_degradado("AV. VICUNA MACKENNA 3451 SAN JOAQUIN SAN JOA") is True
    for limpio in (
        "PDTE. RIESCO 5903 LAS CONDES LAS CONDES",
        "RICARDO MORALES 3369 SAN MIGUEL SAN MIGUEL",
        "AV. VICUNA MACKENNA 3451, SAN JOAQUIN",
        "SANTA ISABEL 585 SANTIAGO LAMPA",
    ):
        assert texto_destino_degradado(limpio) is False


def _catalogo_destinos(tmp_path):
    cat = tmp_path / "catalogos_privados"
    cat.mkdir()
    (cat / "clientes.json").write_text(json.dumps({"version_formato": 1, "clientes": []}), encoding="utf-8")
    (cat / "destinos_maestros.json").write_text(json.dumps({"version_formato": 1, "destinos": []}), encoding="utf-8")
    return cat, CatalogoDestinos(cat / "destinos_maestros.json", ruta_clientes=cat / "clientes.json")


def test_destino_confirmado_sin_coords_se_completa_con_coords_comuna_region(tmp_path):
    cat, catalogo = _catalogo_destinos(tmp_path)
    creado = catalogo.crear(
        cliente_id="", nombre_destino="PDTE. RIESCO 5903, LAS CONDES", pais="CHILE", fuente="TEST",
        direccion="PDTE. RIESCO 5903, LAS CONDES", comuna="LAS CONDES", region="RM",
        estado_calidad=EstadoCalidadDestino.CONFIRMADO,
    )
    prov = _prov(
        "PDTE. RIESCO 5903, LAS CONDES",
        etiqueta="Av Pdte Riesco 5903, Las Condes, RM, Chile",
        localidad="Las Condes", region="Metropolitana",
    )
    res = revalidar_destinos_confirmados_sin_coordenadas_sin_ocr(carpeta_catalogos=cat, proveedor_rutas=prov)
    assert res["destinos_actualizados"] == [creado.destino_id]
    d = catalogo.listar()[0]
    assert d.latitud is not None and d.longitud is not None


def test_destino_confirmado_con_texto_degradado_NO_se_completa_a_ciegas(tmp_path):
    cat, catalogo = _catalogo_destinos(tmp_path)
    catalogo.crear(
        cliente_id="", nombre_destino="AV. VICUNA MACKENNA 3451 SAN JOAQUIN SAN JOA", pais="CHILE", fuente="TEST",
        direccion="AV. VICUNA MACKENNA 3451 SAN JOAQUIN SAN JOA",
        estado_calidad=EstadoCalidadDestino.CONFIRMADO,
    )
    prov = _prov(
        "AV. VICUNA MACKENNA 3451 SAN JOAQUIN SAN JOA",
        etiqueta="algo, Alguna Comuna, RM, Chile", localidad="Alguna Comuna", region="Metropolitana",
    )
    res = revalidar_destinos_confirmados_sin_coordenadas_sin_ocr(carpeta_catalogos=cat, proveedor_rutas=prov)
    assert res["destinos_actualizados"] == []
    assert prov.llamadas_geocodificacion == 0
    d = catalogo.listar()[0]
    assert d.latitud is None and d.longitud is None


# =====================================================================
# 3) Publicación / reconciliación del drop
# =====================================================================

def _raiz_con_manifiesto(tmp_path, *, version):
    raiz = tmp_path / "Atlas"
    actual = raiz / "operacion" / "actual"
    actual.mkdir(parents=True)
    dataset = actual / "analisis_completo_guias.csv"
    dataset.write_text("numero_guia;estado_operacional\n1;OK\n", encoding="utf-8")
    reporte = raiz / "reportes" / "rep_v"
    reporte.mkdir(parents=True)
    escribir_estado_operacion(
        reporte_vigente=reporte, dataset_operacional=dataset, raiz=raiz,
        version_estado_derivado=version, dataset_sha256="abc",
    )
    return raiz, dataset, reporte


def test_escribir_estado_operacion_arrastra_version_si_no_se_pasa(tmp_path):
    raiz, dataset, _ = _raiz_con_manifiesto(tmp_path, version=13)
    reporte2 = raiz / "reportes" / "rep_crudo"
    reporte2.mkdir(parents=True)
    # Publicador que NO conoce la versión (p. ej. generar_reporte_viajes.py).
    escribir_estado_operacion(
        reporte_vigente=reporte2, dataset_operacional=dataset, raiz=raiz, dataset_sha256="def",
    )
    estado = leer_estado_operacion(raiz=raiz)
    assert estado["version_estado_derivado"] == 13, "no se puede degradar a v0 -> migración falsa"
    assert estado["reporte_vigente"].endswith("rep_crudo")


def test_reconciliar_dataset_vigente_no_es_migracion_completa(tmp_path):
    from atlas_core import reconciliacion_estado_derivado as modulo
    raiz, dataset, _ = _raiz_con_manifiesto(tmp_path, version=modulo.RULESET_VERSION)
    # Un publicador sin versión (como el reporte crudo del drop) publica de nuevo:
    reporte2 = raiz / "reportes" / "rep_crudo"
    reporte2.mkdir(parents=True)
    escribir_estado_operacion(
        reporte_vigente=reporte2, dataset_operacional=dataset, raiz=raiz,
        dataset_sha256=modulo._sha256_archivo(dataset),
    )
    res = modulo.reconciliar_estado_derivado(raiz_atlas=raiz)
    # version arrastrada => NO migración => sin reintento/incoherencia/sha
    # desactualizado, la reconciliación no re-barre nada.
    assert res["reconciliado"] is False
    assert res["motivo"] == "VERSION_VIGENTE_SIN_REINTENTO_PENDIENTE"
