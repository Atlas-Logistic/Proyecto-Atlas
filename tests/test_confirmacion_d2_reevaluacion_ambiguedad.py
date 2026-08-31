"""Bloque CONFIRMACIÓN D2 -- caso real 472037 (VICUÑA MACKENNA 655):
Javier confirmó la dirección en Revisión de Atlas (`aplicar_decision_obra`
registra el destino como CONFIRMADO en el catálogo), pero esa
confirmación llega DESPUÉS del reintento de ruta que la propia aplicación
de la decisión dispara -- en ese momento el catálogo confirmado todavía
no existía, así que la fila queda persistida con
`MULTIPLES_UBICACIONES_DISPERSAS(N)`, una etiqueta que ya no es cierta
(implica identidad sin resolver) y que la reconciliación automática
normal nunca reintentaba (motivo estable por diseño).

Este bloque hace `MULTIPLES_UBICACIONES_DISPERSAS` reevaluable en
`revalidar_ruta_sin_destino_calculado_sin_ocr` -- mismo criterio ya usado
para `GEOCODIFICACION_CONTRADICE_COMUNA_DOCUMENTAL`/
`GEOCODIFICACION_FUERA_DE_CHILE` -- para que una fila ya bloqueada se
autocorrija en la siguiente revalidación, sin depender de una nueva
decisión humana ni de una auditoría general."""
from __future__ import annotations

import csv
import json

from atlas_core.catalogo_destinos import CatalogoDestinos, EstadoCalidadDestino
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
        "archivo": "472037.jpeg", "estado_procesamiento": "OK", "numero_guia": "472037",
        "numero_transporte": "0000354034", "fecha": "22/08/2026",
        "despachar_a_crudo": "VICUÑA MACKENNA 655",
        "direccion_entrega": "", "localidad_entrega": "", "region_entrega": "",
        "planta_origen_id": planta.planta_id, "planta_origen_nombre": planta.nombre,
        "origen_determinado_por": "TELEMETRIA_GPS", "evidencia_origen": "GEOCERCA_PLANTA",
        "estado_ruta": "REQUIERE_REVISION", "motivo_ruta": "MULTIPLES_UBICACIONES_DISPERSAS(5)",
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


def _candidato(lat, lon, etiqueta):
    return CandidatoGeocodificacion(Coordenadas(lon, lat), etiqueta, 0.7)


def _proveedor_vicuna_mackenna_dispersa():
    consulta = "VICUÑA MACKENNA 655, Chile"
    return ProveedorRutasSimulado(
        geocodificaciones={
            consulta: ResultadoGeocodificacion(
                EstadoRuta.RESULTADO_AMBIGUO,
                (
                    _candidato(-33.45, -70.60, "Vicuña Mackenna 655, Providencia"),
                    _candidato(-33.60, -70.65, "Vicuña Mackenna 655, La Florida"),
                    _candidato(-36.6, -72.1, "Vicuña Mackenna 655, Chillán"),
                    _candidato(-38.7, -72.6, "Vicuña Mackenna 655, Temuco"),
                    _candidato(-41.5, -72.9, "Vicuña Mackenna 655, Puerto Montt"),
                ),
                "MULTIPLES_CANDIDATOS",
            )
        },
        resultado_ruta=ResultadoRuta(EstadoRuta.RUTA_CALCULADA, 8.4, 15.2, "SINTETICO"),
    )


def test_multiples_ubicaciones_dispersas_se_corrige_a_coordenada_no_confirmada_tras_confirmacion(tmp_path):
    carpeta, planta = _catalogos(tmp_path)
    dataset = tmp_path / "dataset.csv"
    _escribir_csv(dataset, [_fila_csv(planta)])
    # El destino queda CONFIRMADO en el catálogo (Javier ya confirmó la
    # dirección) pero SIN coordenadas propias -- exactamente como lo deja
    # `aplicar_decision_obra` cuando la ruta no llegó a calcularse en el
    # momento de la confirmación (Bloque R16: nunca se persiste una
    # coordenada a medias).
    CatalogoDestinos(carpeta / "destinos_maestros.json", ruta_clientes=carpeta / "clientes.json").crear(
        cliente_id="", nombre_destino="VICUÑA MACKENNA 655", pais="CHILE", fuente="TEST",
        direccion="VICUÑA MACKENNA 655", estado_calidad=EstadoCalidadDestino.CONFIRMADO,
    )
    proveedor = _proveedor_vicuna_mackenna_dispersa()

    resultado = revalidar_ruta_sin_destino_calculado_sin_ocr(
        ruta_dataset=dataset, carpeta_catalogos=carpeta, proveedor_rutas=proveedor,
    )
    assert resultado["guias_actualizadas"] == ["472037"]
    fila = _leer(dataset)[0]
    assert fila["motivo_ruta"] == "COORDENADA_NO_CONFIRMADA(5)"
    assert fila["distancia_km"] == ""  # nunca inventa la ruta sin punto resuelto


def test_multiples_ubicaciones_dispersas_se_resuelve_con_fallback_estructurado_corroborado(tmp_path):
    """Bloque B1 OBSERVADOR + FALLBACK GEOGRÁFICO -- variante idealizada
    del caso real 472037: a diferencia de la producción real (donde el
    destino confirmado no tiene comuna propia registrada, ver Bloque
    CONFIRMACIÓN D2 y `tests/test_fallback_geografico_estructurado.py`),
    aquí SÍ hay una comuna confirmada que corrobora al candidato único
    del respaldo -- la fila debe terminar con ruta CALCULADA de punta a
    punta (geocoding -> routing -> km/tiempo), vía `revalidar_ruta_sin_
    destino_calculado_sin_ocr` end-to-end, sin ninguna decisión humana
    nueva."""
    carpeta, planta = _catalogos(tmp_path)
    dataset = tmp_path / "dataset.csv"
    _escribir_csv(dataset, [_fila_csv(planta)])
    CatalogoDestinos(carpeta / "destinos_maestros.json", ruta_clientes=carpeta / "clientes.json").crear(
        cliente_id="", nombre_destino="VICUÑA MACKENNA 655", pais="CHILE", fuente="TEST",
        direccion="VICUÑA MACKENNA 655", comuna="Providencia",
        estado_calidad=EstadoCalidadDestino.CONFIRMADO,
    )
    proveedor = _proveedor_vicuna_mackenna_dispersa()
    fallback = ProveedorRutasSimulado(geocodificaciones={
        "VICUÑA MACKENNA 655, Chile": ResultadoGeocodificacion(
            EstadoRuta.RESULTADO_AMBIGUO,
            (
                CandidatoGeocodificacion(Coordenadas(-70.60, -33.44), "Vicuña Mackenna 655", 0.9, "Providencia", "Metropolitana"),
                CandidatoGeocodificacion(Coordenadas(-70.65, -33.10), "Vicuña Mackenna", 0.2, "Colina", "Metropolitana"),
            ),
            "MULTIPLES_CANDIDATOS",
        )
    }, resultado_ruta=ResultadoRuta(EstadoRuta.RUTA_CALCULADA, 15.0, 22.0, "SINTETICO"))

    resultado = revalidar_ruta_sin_destino_calculado_sin_ocr(
        ruta_dataset=dataset, carpeta_catalogos=carpeta, proveedor_rutas=proveedor,
        proveedor_rutas_fallback=fallback,
    )
    assert resultado["guias_actualizadas"] == ["472037"]
    fila = _leer(dataset)[0]
    assert fila["estado_ruta"] == "RUTA_CALCULADA"
    assert fila["estado_operacional"] == "OK"
    # El routing real (km/tiempo) lo calcula el proveedor PRINCIPAL
    # (ORS) hacia el punto que Vía C determinó -- Nominatim es sólo
    # geocodificador de respaldo, nunca calcula rutas.
    assert fila["distancia_km"] == "8.4"
    assert fila["duracion_min"] == "15.2"
    assert fila["localidad_entrega"] == "Providencia"


def test_472037_real_evidencia_b1_ya_persistida_corrobora_maipu_y_calcula_ruta(tmp_path):
    """Bloque VALIDACIÓN TERRITORIAL T2 -- caso real 472037 EXACTO:
    destino confirmado SIN comuna propia (igual que en Drive real), pero
    con `resultado_atlas_ia_json` (evidencia B1 YA PERSISTIDA, nunca una
    llamada nueva) mencionando "Santiago" -- `revalidar_ruta_sin_destino_
    calculado_sin_ocr` debe extraerla, corroborar el candidato único del
    respaldo (Maipú, misma región RM) y llegar a RUTA_CALCULADA de punta
    a punta, sin ninguna decisión humana nueva ni investigación nueva."""
    carpeta, planta = _catalogos(tmp_path)
    dataset = tmp_path / "dataset.csv"
    resultado_atlas_ia_json = json.dumps([{
        "campo": "despachar_a_crudo", "dominio": "DESTINO", "elegible_ia": True,
        "llamada_realizada": True, "estado": "BLOQUEADO_POR_VALIDACION", "clasificacion": "B_ASISTENCIA",
        "hipotesis": {
            "campo": "despachar_a_crudo",
            "explicacion": (
                "Los dos registros externos consultados confirman que la dirección "
                'Vicuña Mackenna 655 existe y está asociada al proyecto "Vicuña Mackenna 655" '
                "en Santiago."
            ),
            "valor_propuesto": "Vicuña Mackenna 655", "resultado": "PROPUESTA",
        },
        "contexto_final": {
            "campo": "despachar_a_crudo",
            "evidencias": [{
                "tipo_fuente": "EXTERNO", "campo": "despachar_a_crudo",
                "referencias_fuente": ["Fundamenta <https://www.fundamenta.cl/urban>"],
                "valor": "Sí: Vicuña Mackenna 655 aparece como dirección del proyecto en Santiago.",
            }],
        },
    }])
    _escribir_csv(dataset, [_fila_csv(planta, resultado_atlas_ia_json=resultado_atlas_ia_json)])
    CatalogoDestinos(carpeta / "destinos_maestros.json", ruta_clientes=carpeta / "clientes.json").crear(
        cliente_id="", nombre_destino="VICUÑA MACKENNA 655", pais="CHILE", fuente="TEST",
        direccion="VICUÑA MACKENNA 655", estado_calidad=EstadoCalidadDestino.CONFIRMADO,
        # sin comuna -- exactamente como quedó el destino real de 472037
    )
    proveedor = _proveedor_vicuna_mackenna_dispersa()
    fallback = ProveedorRutasSimulado(geocodificaciones={
        "VICUÑA MACKENNA 655, Chile": ResultadoGeocodificacion(
            EstadoRuta.RESULTADO_AMBIGUO,
            (CandidatoGeocodificacion(Coordenadas(-70.7578666, -33.5212618), "Pasaje Vicuña Mackenna 655", 0.9, "Maipú", "Metropolitana"),),
            "MULTIPLES_CANDIDATOS",
        )
    }, resultado_ruta=ResultadoRuta(EstadoRuta.RUTA_CALCULADA, 25.0, 35.0, "SINTETICO"))

    resultado = revalidar_ruta_sin_destino_calculado_sin_ocr(
        ruta_dataset=dataset, carpeta_catalogos=carpeta, proveedor_rutas=proveedor,
        proveedor_rutas_fallback=fallback,
    )
    assert resultado["guias_actualizadas"] == ["472037"]
    fila = _leer(dataset)[0]
    assert fila["estado_ruta"] == "RUTA_CALCULADA"
    # El routing real (km/tiempo) lo calcula el proveedor PRINCIPAL (ORS)
    # hacia el punto que Vía C determinó -- Nominatim es sólo
    # geocodificador de respaldo, nunca calcula rutas.
    assert fila["distancia_km"] == "8.4"
    assert fila["duracion_min"] == "15.2"
    assert fila["localidad_entrega"] == "Maipú"


def test_multiples_ubicaciones_dispersas_sin_confirmacion_se_mantiene_estable(tmp_path):
    """Control -- sin ningún destino CONFIRMADO en el catálogo (la
    situación normal, sin intervención humana), el motivo sigue siendo
    estable: nunca se reescribe ni se reintenta de forma ruidosa."""
    carpeta, planta = _catalogos(tmp_path)
    dataset = tmp_path / "dataset.csv"
    _escribir_csv(dataset, [_fila_csv(planta)])
    proveedor = _proveedor_vicuna_mackenna_dispersa()

    resultado = revalidar_ruta_sin_destino_calculado_sin_ocr(
        ruta_dataset=dataset, carpeta_catalogos=carpeta, proveedor_rutas=proveedor,
    )
    assert resultado["guias_actualizadas"] == []
    fila = _leer(dataset)[0]
    assert fila["motivo_ruta"] == "MULTIPLES_UBICACIONES_DISPERSAS(5)"
