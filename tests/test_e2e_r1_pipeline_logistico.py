"""Bloque E2E R1: pipeline operacional completo conectado end-to-end.

imagen -> OCR -> extracción -> corroboración -> documento -> viaje ->
planta origen -> DESPACHAR A -> geocodificación -> ORS -> km/min ->
reporte actual -> Desktop UX-R4.

Filosofía verificada por estos tests: INTEGRAR TEMPRANO + ABSTENERSE SI
FALTA EVIDENCIA + un fallo de enriquecimiento logístico NUNCA invalida el
documento/viaje (separación VIAJE vs ENRIQUECIMIENTO LOGÍSTICO).
"""
from __future__ import annotations

import csv

import pytest

from atlas_core.catalogo_plantas import CatalogoPlantas, EstadoCalidad
from atlas_core.gestor_viajes import agrupar_viajes
from atlas_core.procesamiento_masivo import COLUMNAS, procesar_archivo
from atlas_core.reporte_viajes import COLUMNAS_VIAJES, generar_reporte_viajes
from atlas_core.rutas.destino_entrega import resolver_entrega_documento
from atlas_core.rutas.modelos import (
    CandidatoGeocodificacion,
    Coordenadas,
    EstadoRuta,
    ResultadoGeocodificacion,
    ResultadoRuta,
)
from atlas_core.rutas.proveedor import ProveedorRutasSimulado

COORD_AZA_RENCA = Coordenadas(-70.685226, -33.401595)
TEXTOS_ENCABEZADO_RENCA = [
    "ACEROS AZA S A CASA MATRIZ PLANTA RENCA LA UNION 3070 RENCA SANTIAGO CHILE",
    "SEÑOR(ES) : CLIENTE DEMO SA",
    "OBRA DESTINO : OBRA DEMO",
    "DESPACHAR A : AV FORESTAL 1014 CORONEL",
]


@pytest.fixture
def plantas_renca(tmp_path):
    catalogo = CatalogoPlantas(tmp_path / "plantas.json")
    catalogo.crear(
        nombre="AZA RENCA", pais="CHILE", fuente="PRUEBA",
        direccion="LA UNION 3070", comuna="RENCA", region="RM",
        latitud=COORD_AZA_RENCA.latitud, longitud=COORD_AZA_RENCA.longitud,
        estado_calidad=EstadoCalidad.CONFIRMADA,
    )
    return catalogo.listar()


class _ProveedorOCRFalso:
    """Proveedor OCR mínimo para tests, cumple el contrato ProveedorOCR."""

    def __init__(self, texto):
        self._texto = texto

    def leer_texto(self, ruta):
        return self._texto

    def leer_bloques(self, ruta):
        return []

    def leer_focal(self, ruta, caja, allowlist):
        return {"lecturas": []}


# --- resolver_entrega_documento: unidad, sin depender de OCR real ---


def test_sin_proveedor_rutas_no_intenta_red_pero_conserva_despachar_a(plantas_renca):
    resultado = resolver_entrega_documento(TEXTOS_ENCABEZADO_RENCA, plantas_renca, None)
    assert resultado["despachar_a_crudo"]
    assert resultado["planta_origen_nombre"] == "AZA RENCA"
    assert resultado["estado_entrega"] == "SIN_PROVEEDOR_RUTAS"
    assert resultado["distancia_km"] == ""
    assert resultado["estado_ruta"] == ""


def test_planta_ausente_nunca_geocodifica_pero_conserva_despachar_a_crudo():
    """Misma política ya probada en `calcular_ruta_entrega_para_viaje`
    (`test_origen_no_determinado_nunca_geocodifica`): sin planta, nunca se
    gasta una llamada de geocodificación -- pero DESPACHAR A crudo, que es
    lectura local sin red, se conserva igual."""
    proveedor = ProveedorRutasSimulado()
    resultado = resolver_entrega_documento(TEXTOS_ENCABEZADO_RENCA, [], proveedor)
    assert resultado["despachar_a_crudo"]
    assert resultado["planta_origen_id"] == ""
    assert resultado["estado_ruta"] == EstadoRuta.ORIGEN_NO_DETERMINADO.value
    assert proveedor.llamadas_geocodificacion == 0
    assert proveedor.llamadas_ruta == 0


def test_sin_despachar_a_en_el_documento_no_bloquea_planta(plantas_renca):
    proveedor = ProveedorRutasSimulado()
    resultado = resolver_entrega_documento(
        [TEXTOS_ENCABEZADO_RENCA[0]], plantas_renca, proveedor,
    )
    assert resultado["despachar_a_crudo"] == ""
    assert resultado["estado_entrega"] == "SIN_DATO"
    assert resultado["planta_origen_nombre"] == "AZA RENCA"
    assert proveedor.llamadas_geocodificacion == 0


def test_planta_y_despachar_a_resueltos_ejecuta_ors_driving_hgv(plantas_renca):
    consulta = "AV FORESTAL 1014 CORONEL, Chile"
    proveedor = ProveedorRutasSimulado(
        geocodificaciones={
            consulta: ResultadoGeocodificacion(
                EstadoRuta.REQUIERE_REVISION,
                (CandidatoGeocodificacion(
                    Coordenadas(-73.13, -37.03), "Av. Forestal 1014, Coronel, Biobío", 0.9,
                    "Coronel", "Biobío",
                ),),
                "REQUIERE_CONFIRMACION_HUMANA",
            )
        },
        resultado_ruta=ResultadoRuta(EstadoRuta.RUTA_CALCULADA, 512.3, 380.0, "SINTETICO"),
    )
    resultado = resolver_entrega_documento(
        TEXTOS_ENCABEZADO_RENCA, plantas_renca, proveedor, perfil="driving-hgv",
    )
    assert resultado["estado_ruta"] == EstadoRuta.RUTA_CALCULADA.value
    assert resultado["estado_entrega"] == "RESUELTO"
    assert resultado["distancia_km"] == "512.3"
    assert resultado["duracion_min"] == "380.0"
    assert resultado["localidad_entrega"] == "Coronel"
    assert resultado["region_entrega"] == "Biobío"
    assert proveedor.llamadas_ruta == 1


def test_geocodificacion_contradice_comuna_documental_no_expone_destino_incorrecto(plantas_renca):
    """Bloque F (R4.10), caso real 460807: DESPACHAR A menciona "SAN
    BERNARDO" (comuna Metropolitana) dos veces, pero el geocodificador
    devolvió un único candidato confiado (0.8) en Angol, La Araucanía --
    región completamente distinta. `GEOCODIFICACION_CONTRADICE_COMUNA_
    DOCUMENTAL` ya descartaba la ruta (distancia/tiempo); este fix además
    retira la etiqueta/localidad/región incorrectas de los campos que
    Desktop muestra como destino operacional -- antes de este fix, "Angol"
    seguía llegando a `direccion_entrega` pese a estar marcado REVISAR."""
    textos = [
        "ACEROS AZA S A CASA MATRIZ PLANTA RENCA LA UNION 3070 RENCA SANTIAGO CHILE",
        "SEÑOR(ES) : MATERIALES Y SOLUCIONES SA",
        "OBRA DESTINO : AUSIN SAN BERNARDO",
        "DESPACHAR A : INTERIOR NUEVA O1148 SAN BERNARDO SAN BERNAR",
    ]
    consulta = "INTERIOR NUEVA O1148 SAN BERNARDO SAN BERNAR, Chile"
    proveedor = ProveedorRutasSimulado(
        geocodificaciones={
            consulta: ResultadoGeocodificacion(
                EstadoRuta.REQUIERE_REVISION,
                (CandidatoGeocodificacion(
                    Coordenadas(-72.69, -37.80), "Nueva Rancagua Interior, Angol, AR, Chile", 0.8,
                    "Angol", "De La Araucania",
                ),),
                "REQUIERE_CONFIRMACION_HUMANA",
            )
        },
        resultado_ruta=ResultadoRuta(EstadoRuta.RUTA_CALCULADA, 650.0, 480.0, "SINTETICO"),
    )
    resultado = resolver_entrega_documento(textos, plantas_renca, proveedor)
    assert resultado["estado_ruta"] == EstadoRuta.REQUIERE_REVISION.value
    assert "GEOCODIFICACION_CONTRADICE_COMUNA_DOCUMENTAL" in resultado["motivo_ruta"]
    assert resultado["distancia_km"] == ""
    assert resultado["duracion_min"] == ""
    assert resultado["direccion_entrega"] == ""
    assert resultado["localidad_entrega"] == ""
    assert resultado["region_entrega"] == ""
    # DESPACHAR A crudo (lectura documental local) nunca se pierde.
    assert "SAN BERNARDO" in resultado["despachar_a_crudo"]


def test_calle_homonima_de_una_comuna_de_otra_region_no_bloquea_un_destino_correcto(plantas_renca):
    """Control crítico -- caso real 472002: DESPACHAR A "GALVARINO 8501
    QUILICURA" -- "Galvarino" es la calle, pero también existe una comuna
    real llamada Galvarino (La Araucanía), ajena a este documento. Con dos
    comunas reales mencionadas (Galvarino, Quilicura), la evidencia
    documental es ambigua -- nunca debe rechazar un geocode correcto a
    Quilicura sólo por esa coincidencia léxica del catálogo territorial."""
    textos = [
        "ACEROS AZA S A CASA MATRIZ PLANTA RENCA LA UNION 3070 RENCA SANTIAGO CHILE",
        "SEÑOR(ES) : EBEMA SA",
        "OBRA DESTINO : EBEMA SA",
        "DESPACHAR A : GALVARINO 8501 QUILICURA",
    ]
    consulta = "GALVARINO 8501 QUILICURA, Chile"
    proveedor = ProveedorRutasSimulado(
        geocodificaciones={
            consulta: ResultadoGeocodificacion(
                EstadoRuta.REQUIERE_REVISION,
                (CandidatoGeocodificacion(
                    Coordenadas(-70.73, -33.36), "Galvarino, Quilicura, RM, Chile", 1.0,
                    "Quilicura", "Metropolitana",
                ),),
                "REQUIERE_CONFIRMACION_HUMANA",
            )
        },
        resultado_ruta=ResultadoRuta(EstadoRuta.RUTA_CALCULADA, 13.1788, 19.058, "SINTETICO"),
    )
    resultado = resolver_entrega_documento(textos, plantas_renca, proveedor)
    assert resultado["estado_ruta"] == EstadoRuta.RUTA_CALCULADA.value
    assert resultado["distancia_km"] == "13.1788"
    assert resultado["direccion_entrega"] == "Galvarino, Quilicura, RM, Chile"
    assert resultado["localidad_entrega"] == "Quilicura"


def test_geocodificacion_ambigua_deja_ruta_en_revision_y_conserva_evidencia(plantas_renca):
    consulta = "AV FORESTAL 1014 CORONEL, Chile"
    proveedor = ProveedorRutasSimulado(
        geocodificaciones={
            consulta: ResultadoGeocodificacion(
                EstadoRuta.RESULTADO_AMBIGUO,
                (
                    CandidatoGeocodificacion(Coordenadas(-73.13, -37.03), "Coronel, Biobío", 0.9),
                    CandidatoGeocodificacion(Coordenadas(-71.5, -34.5), "Coronel, Ohiggins", 0.8),
                ),
                "MULTIPLES_CANDIDATOS",
            )
        },
    )
    resultado = resolver_entrega_documento(TEXTOS_ENCABEZADO_RENCA, plantas_renca, proveedor)
    assert resultado["estado_ruta"] == EstadoRuta.REQUIERE_REVISION.value
    assert "MULTIPLES_UBICACIONES_DISPERSAS" in resultado["motivo_ruta"]
    assert resultado["planta_origen_nombre"] == "AZA RENCA"
    assert proveedor.llamadas_ruta == 0


# --- integración: procesar_archivo persiste las columnas E2E R1 ---


def test_procesar_archivo_persiste_enriquecimiento_logistico_sin_invalidar_documento(
    tmp_path,
):
    carpeta_catalogos = tmp_path / "catalogos"
    carpeta_catalogos.mkdir()
    catalogo = CatalogoPlantas(carpeta_catalogos / "plantas.json")
    catalogo.crear(
        nombre="AZA RENCA", pais="CHILE", fuente="PRUEBA",
        direccion="LA UNION 3070", comuna="RENCA", region="RM",
        latitud=COORD_AZA_RENCA.latitud, longitud=COORD_AZA_RENCA.longitud,
        estado_calidad=EstadoCalidad.CONFIRMADA,
    )
    for archivo in ("empresas.json", "destinos.json", "choferes.json", "vehiculos.json"):
        (carpeta_catalogos / archivo).write_text("{}", encoding="utf-8")

    consulta = "AV FORESTAL 1014 CORONEL, Chile"
    proveedor_rutas = ProveedorRutasSimulado(
        geocodificaciones={
            consulta: ResultadoGeocodificacion(
                EstadoRuta.REQUIERE_REVISION,
                (CandidatoGeocodificacion(Coordenadas(-73.13, -37.03), "Av. Forestal, Coronel", 0.9),),
                "REQUIERE_CONFIRMACION_HUMANA",
            )
        },
        resultado_ruta=ResultadoRuta(EstadoRuta.RUTA_CALCULADA, 512.3, 380.0, "SINTETICO"),
    )
    textos = TEXTOS_ENCABEZADO_RENCA + [
        "RUT 76.111.111-1",
        "RETIRA : CHOFER DEMO",
        "RUT CHOFER 11111111-1",
        "PATENTE ABCD12",
        "Nro. TRANSPORTE 0000123456",
        "HORA ENTRADA 08:00:00",
        "HORA SALIDA 09:00:00",
        "PESO KG. 1.000,00",
    ]
    proveedor_ocr = _ProveedorOCRFalso(textos)

    resultado = procesar_archivo(
        tmp_path / "guia.jpg",
        proveedor=proveedor_ocr,
        carpeta_catalogos=carpeta_catalogos,
        proveedor_rutas=proveedor_rutas,
    )

    assert resultado["planta_origen_nombre"] == "AZA RENCA"
    assert resultado["despachar_a_crudo"]
    assert resultado["estado_ruta"] == EstadoRuta.RUTA_CALCULADA.value
    assert resultado["distancia_km"] == "512.3"
    # Bloque G: un enriquecimiento logístico resuelto (o no) nunca decide
    # `indicador_revision`/`motivos_revision_documento` -- eso sigue
    # gobernado exclusivamente por identidad/corroboración documental.
    assert "estado_ruta" not in resultado["motivos_revision_documento"]
    assert "PLANTA" not in resultado["motivos_revision_documento"]
    for columna in COLUMNAS:
        assert columna in resultado or columna in ("archivo", "estado_procesamiento", "error")


def test_procesar_archivo_planta_no_determinada_no_bloquea_el_documento(tmp_path):
    """Documento sin ningún encabezado de planta conocida: el viaje sigue
    existiendo -- solo el enriquecimiento logístico queda vacío con motivo
    explícito (Fase G)."""
    carpeta_catalogos = tmp_path / "catalogos"
    carpeta_catalogos.mkdir()
    CatalogoPlantas(carpeta_catalogos / "plantas.json")  # catálogo vacío, válido
    for archivo in ("empresas.json", "destinos.json", "choferes.json", "vehiculos.json"):
        (carpeta_catalogos / archivo).write_text("{}", encoding="utf-8")

    textos = [
        "GUIA DE OTRA EMPRESA SIN ENCABEZADO CONOCIDO",
        "SEÑOR(ES) : CLIENTE DEMO SA",
        "DESPACHAR A : CALLE FALSA 123",
        "Nro. TRANSPORTE 0000999999",
    ]
    resultado = procesar_archivo(
        tmp_path / "guia2.jpg",
        proveedor=_ProveedorOCRFalso(textos),
        carpeta_catalogos=carpeta_catalogos,
        proveedor_rutas=ProveedorRutasSimulado(),
    )
    assert resultado["numero_transporte"] == "0000999999"
    assert resultado["planta_origen_id"] == ""
    assert resultado["estado_ruta"] == EstadoRuta.ORIGEN_NO_DETERMINADO.value
    # El documento sigue procesado y con estado propio (no lanza, no se pierde).
    assert resultado["indicador_revision"] in ("OK", "REVISAR")


def test_procesar_archivo_sin_carpeta_catalogos_no_intenta_red(tmp_path):
    """Sin `carpeta_catalogos` (comportamiento histórico), el bloque E2E R1
    completo queda inactivo -- 100% compatible con llamadas anteriores a
    este bloque, columnas presentes pero vacías."""
    textos = ["GUIA SIN CATALOGOS", "DESPACHAR A : CALLE FALSA 123"]
    resultado = procesar_archivo(tmp_path / "guia3.jpg", proveedor=_ProveedorOCRFalso(textos))
    assert resultado["planta_origen_id"] == ""
    assert resultado["despachar_a_crudo"] == ""
    assert resultado["estado_ruta"] == ""


# --- integración: gestor_viajes agrega sin mezclar en conflicto ---


def _fila_base(archivo, numero_transporte, **overrides):
    fila = {columna: "" for columna in COLUMNAS}
    fila.update({
        "archivo": archivo, "estado_procesamiento": "PROCESADO", "error": "",
        "numero_guia": "1", "numero_transporte": numero_transporte, "fecha": "01-01-2026",
        "chofer": "CHOFER X", "rut_chofer": "11.111.111-1",
        "cliente": "CLIENTE X", "obra_destino": "OBRA X",
        "patente_tracto": "ABCD12", "patente_rampla": "No encontrado",
        "descripcion_material": "MATERIAL", "tipo_carga": "BARRAS",
        "indicador_revision": "OK",
    })
    fila.update(overrides)
    return fila


def test_agrupar_viajes_consolida_planta_y_ruta_cuando_coinciden():
    filas = [
        _fila_base(
            "a.jpg", "0000111111",
            planta_origen_id="p1", planta_origen_nombre="AZA RENCA",
            despachar_a_crudo="AV FORESTAL 1014", distancia_km="512.3",
            duracion_min="380.0", estado_ruta="RUTA_CALCULADA",
        ),
    ]
    viajes, _ = agrupar_viajes(filas)
    assert len(viajes) == 1
    datos = viajes[0].a_dict()
    assert datos["planta_origen_nombre"] == "AZA RENCA"
    assert datos["despachar_a"] == "AV FORESTAL 1014"
    assert datos["distancia_km"] == "512.3"
    assert datos["estado_ruta"] == "RUTA_CALCULADA"


def test_agrupar_viajes_no_mezcla_planta_cuando_documentos_discrepan():
    filas = [
        _fila_base(
            "a.jpg", "0000222222",
            planta_origen_nombre="AZA RENCA", distancia_km="512.3",
        ),
        _fila_base(
            "b.jpg", "0000222222",
            planta_origen_nombre="AZA COLINA", distancia_km="40.0",
        ),
    ]
    viajes, _ = agrupar_viajes(filas)
    assert len(viajes) == 1
    datos = viajes[0].a_dict()
    # Ante conflicto real entre documentos del mismo viaje, nunca se elige
    # uno arbitrariamente -- igual criterio que hora_entrada_aza/peso.
    assert datos["planta_origen_nombre"] == ""
    assert datos["distancia_km"] == ""


# --- integración: generar_reporte_viajes expone los campos UX-R4 sin ORS ---


def test_generar_reporte_viajes_expone_campos_ux_r4_desde_csv_sin_llamar_ors(tmp_path):
    """El reporte se genera a partir de columnas ya calculadas por
    documento (Bloque E2E R1) -- `generar_reporte_viajes` nunca vuelve a
    golpear ORS/geocodificación, ni con ni sin `calculador_rutas`."""
    carpeta_catalogos = tmp_path / "catalogos"
    carpeta_catalogos.mkdir()
    for archivo in ("empresas.json", "destinos.json", "choferes.json", "vehiculos.json"):
        (carpeta_catalogos / archivo).write_text("{}", encoding="utf-8")

    csv_entrada = tmp_path / "analisis_completo_guias.csv"
    fila = _fila_base(
        "a.jpg", "0000333333",
        planta_origen_id="p1", planta_origen_nombre="AZA RENCA",
        despachar_a_crudo="AV FORESTAL 1014", direccion_entrega="Av. Forestal, Coronel",
        distancia_km="512.3", duracion_min="380.0",
        proveedor_ruta="openrouteservice", estado_ruta="RUTA_CALCULADA",
    )
    with csv_entrada.open("w", newline="", encoding="utf-8-sig") as manejador:
        escritor = csv.DictWriter(manejador, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader()
        escritor.writerow(fila)

    salida = tmp_path / "reporte"
    manifest = generar_reporte_viajes(csv_entrada, salida, carpeta_catalogos=carpeta_catalogos)
    assert manifest["totales"]["viajes"] == 1

    with (salida / "viajes.csv").open("r", newline="", encoding="utf-8-sig") as manejador:
        filas = list(csv.DictReader(manejador, delimiter=";"))
    assert len(filas) == 1
    viaje = filas[0]
    assert viaje["planta_origen_nombre"] == "AZA RENCA"
    assert viaje["despachar_a"] == "AV FORESTAL 1014"
    assert viaje["distancia_km"] == "512.3"
    assert viaje["duracion_min"] == "380.0"
    assert viaje["estado_ruta"] == "RUTA_CALCULADA"
    for columna in ("despachar_a", "direccion_entrega", "localidad_entrega", "region_entrega", "estado_entrega"):
        assert columna in COLUMNAS_VIAJES
