"""Bloque H (R4.10): para filas con planta de origen y despachar_a_crudo
ya persistidos pero sin ruta calculada, reintenta con las reglas ya
corregidas -- caso real 464991: "AV PROVIDENCIA 1550 SANTIAGO PROVIDENCIA"
menciona dos comunas reales (Providencia, Santiago), evidencia ambigua que
el código anterior usaba por error para rechazar un geocode válido
(confianza 1.0). Corregida esa ambigüedad, la ruta sí puede calcularse.
"""
import csv
import json

from atlas_core.catalogo_plantas import CatalogoPlantas, EstadoCalidad
from atlas_core.procesamiento_masivo import COLUMNAS
from atlas_core.revalidacion_documental import revalidar_ruta_sin_destino_calculado_sin_ocr
from atlas_core.rutas.modelos import (
    CandidatoGeocodificacion, Coordenadas, EstadoRuta, ResultadoGeocodificacion, ResultadoRuta,
)
from atlas_core.rutas.proveedor import ProveedorRutasSimulado

COORD_AZA_RENCA = Coordenadas(-70.685226, -33.401595)


def _catalogos(tmp_path):
    carpeta = tmp_path / "catalogos"; carpeta.mkdir()
    plantas = CatalogoPlantas(carpeta / "plantas.json")
    planta = plantas.crear(
        nombre="AZA RENCA", pais="CHILE", fuente="TEST",
        direccion="LA UNION 3070", comuna="RENCA", region="RM",
        latitud=COORD_AZA_RENCA.latitud, longitud=COORD_AZA_RENCA.longitud,
        estado_calidad=EstadoCalidad.CONFIRMADA,
    )
    return carpeta, planta


def _fila_csv(planta, **overrides):
    fila = {c: "" for c in COLUMNAS}
    fila.update({
        "archivo": "464991.jpeg", "estado_procesamiento": "OK", "numero_guia": "464991",
        "numero_transporte": "T1", "fecha": "17/08/2026",
        "despachar_a_crudo": "AV PROVIDENCIA 1550 SANTIAGO PROVIDENCIA",
        "direccion_entrega": "Avenida Providencia, Santiago, RM, Chile",
        "localidad_entrega": "", "region_entrega": "",
        "planta_origen_id": planta.planta_id, "planta_origen_nombre": planta.nombre,
        "origen_determinado_por": "TELEMETRIA_GPS", "evidencia_origen": "GEOCERCA_PLANTA",
        "estado_ruta": "REQUIERE_REVISION", "motivo_ruta": "GEOCODIFICACION_CONTRADICE_COMUNA_DOCUMENTAL: Providencia != Santiago",
        "distancia_km": "", "duracion_min": "", "indicador_revision": "OK",
    })
    fila.update(overrides)
    return fila


def _escribir_csv(ruta, filas):
    with ruta.open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader()
        escritor.writerows(filas)


def _leer(ruta):
    with ruta.open(encoding="utf-8-sig") as archivo:
        return list(csv.DictReader(archivo, delimiter=";"))


def _proveedor_providencia_santiago():
    consulta = "AV PROVIDENCIA 1550 SANTIAGO PROVIDENCIA, Chile"
    return ProveedorRutasSimulado(
        geocodificaciones={
            consulta: ResultadoGeocodificacion(
                EstadoRuta.RESULTADO_AMBIGUO,
                (
                    CandidatoGeocodificacion(Coordenadas(-70.634933, -33.436723), "Avenida Providencia, Santiago, RM, Chile", 1.0, "Santiago", "Metropolitana"),
                    CandidatoGeocodificacion(Coordenadas(-70.613218, -33.423876), "1964 Avenida Providencia, Santiago, RM, Chile", 0.8, "Santiago", "Metropolitana"),
                ),
                "MULTIPLES_CANDIDATOS",
            )
        },
        resultado_ruta=ResultadoRuta(EstadoRuta.RUTA_CALCULADA, 8.4, 15.2, "SINTETICO"),
    )


def test_resuelve_caso_real_464991_tras_corregir_la_ambiguedad_de_comuna(tmp_path):
    carpeta, planta = _catalogos(tmp_path)
    dataset = tmp_path / "dataset.csv"
    _escribir_csv(dataset, [_fila_csv(planta)])
    proveedor = _proveedor_providencia_santiago()

    resultado = revalidar_ruta_sin_destino_calculado_sin_ocr(
        ruta_dataset=dataset, carpeta_catalogos=carpeta, proveedor_rutas=proveedor,
    )
    assert resultado["guias_actualizadas"] == ["464991"]
    fila = _leer(dataset)[0]
    assert fila["estado_ruta"] == "RUTA_CALCULADA"
    assert fila["distancia_km"] == "8.4"
    assert fila["duracion_min"] == "15.2"
    assert fila["direccion_entrega"] == "Avenida Providencia, Santiago, RM, Chile"
    assert fila["localidad_entrega"] == "Santiago"


def test_no_toca_fila_ya_ruta_calculada(tmp_path):
    carpeta, planta = _catalogos(tmp_path)
    fila = _fila_csv(planta, estado_ruta="RUTA_CALCULADA", distancia_km="22.9", duracion_min="33.0")
    dataset = tmp_path / "dataset.csv"
    _escribir_csv(dataset, [fila])
    resultado = revalidar_ruta_sin_destino_calculado_sin_ocr(
        ruta_dataset=dataset, carpeta_catalogos=carpeta, proveedor_rutas=_proveedor_providencia_santiago(),
    )
    assert resultado["guias_actualizadas"] == []


def test_no_toca_fila_sin_planta_origen(tmp_path):
    """Caso real 464981 (ORIGEN_NO_DETERMINADO): sin planta, nunca se
    intenta geocodificar ni calcular ruta."""
    carpeta, planta = _catalogos(tmp_path)
    fila = _fila_csv(planta, planta_origen_id="", planta_origen_nombre="")
    dataset = tmp_path / "dataset.csv"
    _escribir_csv(dataset, [fila])
    proveedor = _proveedor_providencia_santiago()
    resultado = revalidar_ruta_sin_destino_calculado_sin_ocr(
        ruta_dataset=dataset, carpeta_catalogos=carpeta, proveedor_rutas=proveedor,
    )
    assert resultado["guias_actualizadas"] == []
    assert proveedor.llamadas_geocodificacion == 0


def test_no_inventa_resultado_cuando_sigue_habiendo_una_contradiccion_real(tmp_path):
    """Control -- caso real 460807 (comuna inequívoca "San Bernardo" vs
    "Angol"): el reintento vuelve a fallar exactamente igual, la fila
    queda intacta."""
    carpeta, planta = _catalogos(tmp_path)
    fila = _fila_csv(
        planta, numero_guia="460807",
        despachar_a_crudo="INTERIOR NUEVA O1148 SAN BERNARDO SAN BERNAR",
        direccion_entrega="", localidad_entrega="", region_entrega="",
    )
    dataset = tmp_path / "dataset.csv"
    _escribir_csv(dataset, [fila])
    consulta = "INTERIOR NUEVA O1148 SAN BERNARDO SAN BERNAR, Chile"
    proveedor = ProveedorRutasSimulado(
        geocodificaciones={
            consulta: ResultadoGeocodificacion(
                EstadoRuta.REQUIERE_REVISION,
                (CandidatoGeocodificacion(Coordenadas(-72.69, -37.80), "Nueva Rancagua Interior, Angol, AR, Chile", 0.8, "Angol", "De La Araucania"),),
                "REQUIERE_CONFIRMACION_HUMANA",
            )
        },
        resultado_ruta=ResultadoRuta(EstadoRuta.RUTA_CALCULADA, 650.0, 480.0, "SINTETICO"),
    )
    resultado = revalidar_ruta_sin_destino_calculado_sin_ocr(
        ruta_dataset=dataset, carpeta_catalogos=carpeta, proveedor_rutas=proveedor,
    )
    assert resultado["guias_actualizadas"] == []
    fila_final = _leer(dataset)[0]
    assert fila_final["distancia_km"] == ""
    assert fila_final["direccion_entrega"] == ""


def test_usa_proveedor_real_por_defecto_sin_lanzar_sin_credencial(tmp_path):
    """Sin proveedor inyectado, construye OpenRouteService()+caché real --
    sin credencial configurada se abstiene sola (SIN_CREDENCIAL), nunca
    lanza ni bloquea la revalidación de otras filas."""
    carpeta, planta = _catalogos(tmp_path)
    dataset = tmp_path / "dataset.csv"
    _escribir_csv(dataset, [_fila_csv(planta)])
    import os
    valor_previo = os.environ.pop("OPENROUTESERVICE_API_KEY", None)
    try:
        resultado = revalidar_ruta_sin_destino_calculado_sin_ocr(
            ruta_dataset=dataset, carpeta_catalogos=carpeta,
        )
        assert resultado["guias_actualizadas"] == []
    finally:
        if valor_previo is not None:
            os.environ["OPENROUTESERVICE_API_KEY"] = valor_previo
