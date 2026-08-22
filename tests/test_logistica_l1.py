"""Bloque LOGÍSTICA L1 -- cierre de capa logística real: destino
específico preservado (nunca degradado a comuna/ciudad genérica) + km/
tiempo materializados automáticamente cuando origen+destino son
confiables, sin dejar un "No disponible" silencioso cuando el intento
falla."""
import csv
import json

from atlas_core.catalogo_plantas import CatalogoPlantas, EstadoCalidad
from atlas_core.procesamiento_masivo import COLUMNAS
from atlas_core.revalidacion_documental import (
    revalidar_direccion_entrega_degradada_sin_ocr,
    revalidar_ruta_sin_destino_calculado_sin_ocr, revalidar_y_regenerar_reporte,
)
from atlas_core.rutas.destino_entrega import _etiqueta_geocodificada_o_texto_documental
from atlas_core.rutas.modelos import (
    CandidatoGeocodificacion, Coordenadas, EstadoRuta, ResultadoGeocodificacion, ResultadoRuta,
)
from atlas_core.rutas.proveedor import ProveedorRutasSimulado

COORD_AZA_COLINA = Coordenadas(-70.669, -33.201)


def _catalogos(tmp_path):
    carpeta = tmp_path / "catalogos"; carpeta.mkdir()
    plantas = CatalogoPlantas(carpeta / "plantas.json")
    planta = plantas.crear(
        nombre="AZA COLINA", pais="CHILE", fuente="TEST",
        direccion="RUTA 5", comuna="COLINA", region="RM",
        latitud=COORD_AZA_COLINA.latitud, longitud=COORD_AZA_COLINA.longitud,
        estado_calidad=EstadoCalidad.CONFIRMADA,
    )
    return carpeta, planta


def _fila_csv(planta, **overrides):
    fila = {c: "" for c in COLUMNAS}
    fila.update({
        "archivo": "1.jpeg", "estado_procesamiento": "OK", "numero_guia": "1",
        "numero_transporte": "T1", "fecha": "22/08/2026",
        "despachar_a_crudo": "PUERTA DEL SOL 83 LAS CONDES",
        "planta_origen_id": planta.planta_id, "planta_origen_nombre": planta.nombre,
        "origen_determinado_por": "TELEMETRIA_GPS", "evidencia_origen": "GEOCERCA_PLANTA",
        "estado_ruta": "", "motivo_ruta": "",
        "distancia_km": "", "duracion_min": "", "indicador_revision": "OK",
    })
    fila.update(overrides)
    return fila


def _escribir_csv(ruta, filas):
    with ruta.open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader(); escritor.writerows(filas)


def _leer(ruta):
    with ruta.open(encoding="utf-8-sig") as archivo:
        return list(csv.DictReader(archivo, delimiter=";"))


# --- 1. Especificidad del destino -- unidad ---

def test_etiqueta_generica_se_reemplaza_por_texto_documental_con_numero():
    resultado = _etiqueta_geocodificada_o_texto_documental(
        etiqueta="Las Condes, RM, Chile", texto_documental="PUERTA DEL SOL 83 LAS CONDES",
    )
    assert resultado == "PUERTA DEL SOL 83 LAS CONDES"


def test_etiqueta_ya_especifica_se_conserva_tal_cual():
    """Control -- si el geocodificador YA trae número, no hay degradación
    que corregir; se usa la etiqueta del proveedor tal cual."""
    resultado = _etiqueta_geocodificada_o_texto_documental(
        etiqueta="Puerta del Sol 83, Las Condes, RM, Chile", texto_documental="PUERTA DEL SOL 83 LAS CONDES",
    )
    assert resultado == "Puerta del Sol 83, Las Condes, RM, Chile"


def test_texto_documental_sin_numero_no_fuerza_nada():
    """Control -- si el propio documento tampoco trae número, no hay base
    para preferirlo sobre la etiqueta del proveedor."""
    resultado = _etiqueta_geocodificada_o_texto_documental(
        etiqueta="Las Condes, RM, Chile", texto_documental="SECTOR LAS CONDES",
    )
    assert resultado == "Las Condes, RM, Chile"


# --- 2. "No disponible" nunca silencioso -- motivo en blanco se refresca ---

def test_motivo_ruta_en_blanco_se_refresca_con_causa_real_del_reintento(tmp_path):
    """Caso real (460807/472008/472018/472037/472073/472099/472163): el
    motivo había quedado en blanco (reset por un intento anterior que
    nunca persistió una causa fresca). El reintento aquí falla de nuevo
    (confianza insuficiente) -- pero ahora la causa queda explícita en
    vez de blanco."""
    carpeta, planta = _catalogos(tmp_path)
    dataset = tmp_path / "dataset.csv"
    _escribir_csv(dataset, [_fila_csv(planta)])
    consulta = "PUERTA DEL SOL 83 LAS CONDES, Chile"
    proveedor = ProveedorRutasSimulado(
        geocodificaciones={
            consulta: ResultadoGeocodificacion(
                EstadoRuta.REQUIERE_REVISION,
                (CandidatoGeocodificacion(Coordenadas(-70.57, -33.41), "Las Condes, RM, Chile", 0.3, "Las Condes", "Metropolitana"),),
                "CONFIANZA_BAJA",
            )
        },
        resultado_ruta=ResultadoRuta(EstadoRuta.RUTA_CALCULADA, 20.0, 30.0, "SINTETICO"),
    )
    resultado = revalidar_ruta_sin_destino_calculado_sin_ocr(
        ruta_dataset=dataset, carpeta_catalogos=carpeta, proveedor_rutas=proveedor,
    )
    assert resultado["guias_actualizadas"] == ["1"]
    fila = _leer(dataset)[0]
    assert fila["estado_ruta"] == "REQUIERE_REVISION"
    assert fila["motivo_ruta"] == "CONFIANZA_INSUFICIENTE"
    assert fila["distancia_km"] == ""  # nunca inventa una ruta


def test_motivo_ya_basado_en_evidencia_real_nunca_se_reescribe(tmp_path):
    """Control -- un rechazo YA explicado por evidencia real (comuna
    contradicha) es estable por diseño: un segundo reintento que vuelve a
    fallar (aunque con un motivo técnicamente distinto) no lo sobrescribe."""
    carpeta, planta = _catalogos(tmp_path)
    dataset = tmp_path / "dataset.csv"
    _escribir_csv(dataset, [_fila_csv(
        planta, motivo_ruta="GEOCODIFICACION_CONTRADICE_COMUNA_DOCUMENTAL: Cerrillos != Santiago",
        estado_ruta="REQUIERE_REVISION",
    )])
    consulta = "PUERTA DEL SOL 83 LAS CONDES, Chile"
    proveedor = ProveedorRutasSimulado(
        geocodificaciones={
            consulta: ResultadoGeocodificacion(
                EstadoRuta.REQUIERE_REVISION,
                (CandidatoGeocodificacion(Coordenadas(-70.57, -33.41), "Las Condes, RM, Chile", 0.3, "Las Condes", "Metropolitana"),),
                "CONFIANZA_BAJA",
            )
        },
        resultado_ruta=ResultadoRuta(EstadoRuta.RUTA_CALCULADA, 20.0, 30.0, "SINTETICO"),
    )
    resultado = revalidar_ruta_sin_destino_calculado_sin_ocr(
        ruta_dataset=dataset, carpeta_catalogos=carpeta, proveedor_rutas=proveedor,
    )
    assert resultado["guias_actualizadas"] == []
    fila = _leer(dataset)[0]
    assert fila["motivo_ruta"] == "GEOCODIFICACION_CONTRADICE_COMUNA_DOCUMENTAL: Cerrillos != Santiago"


# --- 2b. Retroactivo: ruta YA calculada con etiqueta degradada de antes ---

def test_direccion_entrega_degradada_se_corrige_sin_tocar_km_ni_ruta(tmp_path):
    """Caso real 472044/472227/472247: la ruta YA fue calculada (antes de
    este bloque) usando la etiqueta genérica del proveedor -- nunca se
    reintenta geocodificación/routing (no hace falta, ya es válida), sólo
    se corrige la ETIQUETA persistida."""
    carpeta, planta = _catalogos(tmp_path)
    dataset = tmp_path / "dataset.csv"
    _escribir_csv(dataset, [_fila_csv(
        planta, despachar_a_crudo="AV IRARRAZAVAL 5497 NUNOA", direccion_entrega="Ñuñoa, RM, Chile",
        localidad_entrega="Ñuñoa", estado_ruta="RUTA_CALCULADA", distancia_km="30.6809", duracion_min="41.09",
    )])
    resultado = revalidar_direccion_entrega_degradada_sin_ocr(ruta_dataset=dataset)
    assert resultado["guias_actualizadas"] == ["1"]
    fila = _leer(dataset)[0]
    assert fila["direccion_entrega"] == "AV IRARRAZAVAL 5497 NUNOA"
    # Nunca toca km/tiempo/localidad -- la ruta ya era válida.
    assert fila["distancia_km"] == "30.6809"
    assert fila["duracion_min"] == "41.09"
    assert fila["localidad_entrega"] == "Ñuñoa"


def test_direccion_entrega_ya_especifica_no_se_toca(tmp_path):
    """Control -- una ruta ya calculada con etiqueta específica (con
    número) no se modifica -- nunca una escritura sin motivo real."""
    carpeta, planta = _catalogos(tmp_path)
    dataset = tmp_path / "dataset.csv"
    _escribir_csv(dataset, [_fila_csv(
        planta, despachar_a_crudo="MARURI 1942 RENCA", direccion_entrega="Maruri 1942, Renca, RM, Chile",
        estado_ruta="RUTA_CALCULADA", distancia_km="16.1517", duracion_min="22.32",
    )])
    resultado = revalidar_direccion_entrega_degradada_sin_ocr(ruta_dataset=dataset)
    assert resultado["guias_actualizadas"] == []


# --- 3. Origen+destino confiables -> km/tiempo automático, sin script manual ---

def test_revalidar_y_regenerar_reporte_materializa_km_tiempo_automaticamente(tmp_path):
    raiz = tmp_path / "Atlas"
    catalogos = raiz / "catalogos_privados"; actual = raiz / "operacion" / "actual"
    (raiz / "reportes").mkdir(parents=True); catalogos.mkdir(parents=True); actual.mkdir(parents=True)
    for nombre, contenido in {
        "clientes.json": {"version_formato": 1, "clientes": []}, "empresas.json": {},
        "vehiculos.json": {"version": 1, "vehiculos": []},
        "obras_destinos.json": {"version_formato": 1, "obras": [], "relaciones": []},
        "destinos_maestros.json": {"version_formato": 1, "destinos": []},
    }.items():
        (catalogos / nombre).write_text(json.dumps(contenido), encoding="utf-8")
    plantas = CatalogoPlantas(catalogos / "plantas.json")
    planta = plantas.crear(
        nombre="AZA COLINA", pais="CHILE", fuente="TEST",
        direccion="RUTA 5", comuna="COLINA", region="RM",
        latitud=COORD_AZA_COLINA.latitud, longitud=COORD_AZA_COLINA.longitud,
        estado_calidad=EstadoCalidad.CONFIRMADA,
    )
    dataset = actual / "analisis_completo_guias.csv"
    _escribir_csv(dataset, [_fila_csv(planta)])
    consulta = "PUERTA DEL SOL 83 LAS CONDES, Chile"
    proveedor = ProveedorRutasSimulado(
        geocodificaciones={
            consulta: ResultadoGeocodificacion(
                EstadoRuta.REQUIERE_REVISION,
                (CandidatoGeocodificacion(Coordenadas(-70.57, -33.41), "Puerta del Sol 83, Las Condes, RM, Chile", 1.0, "Las Condes", "Metropolitana"),),
                "RESUELTO",
            )
        },
        resultado_ruta=ResultadoRuta(EstadoRuta.RUTA_CALCULADA, 18.5, 25.0, "SINTETICO"),
    )
    resultado = revalidar_y_regenerar_reporte(
        raiz_atlas=raiz, nombre_carpeta_reporte="reporte_l1", proveedor_rutas=proveedor,
    )
    assert "1" in resultado["guias_actualizadas"]
    assert resultado["reporte_regenerado"] is True
    fila = _leer(dataset)[0]
    assert fila["distancia_km"] == "18.5"
    assert fila["duracion_min"] == "25.0"
    assert fila["estado_ruta"] == "RUTA_CALCULADA"
    assert fila["direccion_entrega"] == "Puerta del Sol 83, Las Condes, RM, Chile"


def test_sin_acceso_vial_sigue_sin_ruta_causa_correcta(tmp_path):
    """CASO CONTROL -- proveedor confirma que el punto no es enrutable
    (SIN_ACCESO_VIAL, ver Bloque R9): nunca se inventa una ruta ni se
    limpia esa causa real."""
    from atlas_core.rutas.modelos import ResultadoRuta as _ResultadoRuta

    carpeta, planta = _catalogos(tmp_path)
    dataset = tmp_path / "dataset.csv"
    _escribir_csv(dataset, [_fila_csv(planta)])
    consulta = "PUERTA DEL SOL 83 LAS CONDES, Chile"

    class _ProveedorSinAccesoVial(ProveedorRutasSimulado):
        def calcular_ruta(self, *args, **kwargs):
            return ResultadoRuta(EstadoRuta.SIN_ACCESO_VIAL, motivo="SIN_ACCESO_VIAL")

    proveedor = _ProveedorSinAccesoVial(
        geocodificaciones={
            consulta: ResultadoGeocodificacion(
                EstadoRuta.REQUIERE_REVISION,
                (CandidatoGeocodificacion(Coordenadas(-70.57, -33.41), "Puerta del Sol 83, Las Condes, RM, Chile", 1.0, "Las Condes", "Metropolitana"),),
                "RESUELTO",
            )
        },
    )
    resultado = revalidar_ruta_sin_destino_calculado_sin_ocr(
        ruta_dataset=dataset, carpeta_catalogos=carpeta, proveedor_rutas=proveedor,
    )
    fila = _leer(dataset)[0]
    assert fila["distancia_km"] == ""
    assert fila["estado_ruta"] != "RUTA_CALCULADA"
    if resultado["guias_actualizadas"]:
        assert "SIN_ACCESO_VIAL" in fila["motivo_ruta"]
