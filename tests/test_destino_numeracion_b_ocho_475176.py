"""Caso real 475176 (EBEMA SA, transporte 0000361792).

La obra EBEMA SA tiene confirmado por Javier el destino "GALVARINO 8501,
QUILICURA". El OCR del DESPACHAR A leyó "GALVARINO B501 QUILICURA": el
geocodificador sólo devolvió el centroide de Quilicura y la fila quedó
RUTA_CALCULADA hacia ese centroide, mostrando el texto corrupto. Sólo una B
inicial de una numeración de 3+ dígitos se lee como 8, y sólo bajo la calle
confirmada completa; la ruta ya calculada se re-ancla al destino confirmado
conservando `despachar_a_crudo`.
"""
from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field

from atlas_core.catalogo_destinos import coincide_solo_por_numeracion_ocr, direccion_confirmada_coincide
from atlas_core.catalogo_plantas import CatalogoPlantas, EstadoCalidad
from atlas_core.procesamiento_masivo import COLUMNAS
from atlas_core.revalidacion_documental import revalidar_ruta_con_destino_confirmado_en_catalogo_sin_ocr
from atlas_core.rutas.modelos import Coordenadas, EstadoRuta, ResultadoRuta
from atlas_core.rutas.proveedor import ProveedorRutasSimulado

CONFIRMADO = "GALVARINO 8501"
DOCUMENTAL_475176 = "GALVARINO B501 QUILICURA"
DIRECCION_CANONICA = "GALVARINO 8501, QUILICURA, CHILE"
COORD_DESTINO = Coordenadas(-70.716168, -33.370934)
COORD_CENTROIDE_QUILICURA = Coordenadas(-70.728749, -33.365227)


# --- 1. B501 <-> 8501 bajo la calle confirmada completa ---

def test_b_inicial_de_numeracion_coincide_con_ocho():
    assert direccion_confirmada_coincide(CONFIRMADO, DOCUMENTAL_475176)
    assert direccion_confirmada_coincide(CONFIRMADO, DOCUMENTAL_475176, comuna_confirmada="QUILICURA")
    # Simétrico: maestro corrupto, documento limpio.
    assert direccion_confirmada_coincide("GALVARINO B501", "GALVARINO 8501 QUILICURA")
    assert coincide_solo_por_numeracion_ocr(CONFIRMADO, DOCUMENTAL_475176, comuna_confirmada="QUILICURA")


# --- 2. controles negativos: nunca fusiona números/direcciones distintas ---

def test_b_no_fusiona_otros_numeros_ni_otras_calles():
    for documental in (
        "GALVARINO B502 QUILICURA",      # otro número tras la B
        "GALVARINO B50 QUILICURA",       # numeración más corta
        "GALVARINO 501 QUILICURA",       # sin la B: otro número
        "GALVARINO B5010 QUILICURA",     # contiene 8501 pero es otro número
        "GALVARINO D501 QUILICURA",      # otra letra: no se tolera
        "GALVARINO 501B QUILICURA",      # B final: numeración real con letra
        "GALVARINO B 501 QUILICURA",     # B suelta
        "GALVAN B501 QUILICURA",         # otra calle, mismo número
        "B501 QUILICURA",                # sin calle
    ):
        assert not direccion_confirmada_coincide(CONFIRMADO, documental), documental
        assert not coincide_solo_por_numeracion_ocr(CONFIRMADO, documental), documental


def test_b_exige_la_comuna_confirmada_cuando_se_aporta():
    assert not direccion_confirmada_coincide(CONFIRMADO, "GALVARINO B501 RENCA", comuna_confirmada="QUILICURA")


def test_letra_b_con_pocos_digitos_no_se_convierte():
    # "B12" (block/depto) nunca se lee como 812.
    assert not direccion_confirmada_coincide("PASAJE ALFA 812", "PASAJE ALFA B12 MAIPU")


def test_coincidencia_literal_no_es_solo_por_tolerancia():
    assert not coincide_solo_por_numeracion_ocr(CONFIRMADO, "GALVARINO 8501 QUILICURA")


# --- 3. revalidación focal: ruta ya calculada al centroide se re-ancla ---

@dataclass
class _ProveedorQueRegistra(ProveedorRutasSimulado):
    destinos_ruteados: list = field(default_factory=list)

    def calcular_ruta(self, origen, destino, perfil):
        self.destinos_ruteados.append(destino)
        return super().calcular_ruta(origen, destino, perfil)


def _entorno(tmp_path, filas):
    raiz = tmp_path / "Atlas"
    catalogos = raiz / "catalogos_privados"
    actual = raiz / "operacion" / "actual"
    catalogos.mkdir(parents=True)
    actual.mkdir(parents=True)
    fecha = "2026-08-14T00:00:00+00:00"
    evidencia_humana = {
        "tipo": "CONFIRMACION_HUMANA", "identificador_fuente": "CONFIRMACION_HUMANA_TEST",
        "referencia_hash": "", "campos_observados": {"decision": "CONFIRMADA"}, "fecha": fecha,
        "actor_proceso": "JAVIER_MBT", "resultado": "SOPORTA",
    }
    cliente = {
        "cliente_id": "cliente-ebema", "razon_social": "EBEMA SA", "nombre_normalizado": "EBEMA",
        "nombre_comercial": "", "rut": "83585400-0", "aliases": [], "estado_calidad": "CONFIRMADO",
        "estado_vigencia": "ACTIVO", "fuente": "TEST", "observacion": "",
        "fecha_creacion": fecha, "fecha_modificacion": fecha,
    }
    destino = {
        "destino_id": "destino-galvarino", "cliente_id": "cliente-ebema", "nombre_destino": CONFIRMADO,
        "nombre_normalizado": CONFIRMADO, "codigo_destino": "", "direccion": DIRECCION_CANONICA,
        "comuna": "QUILICURA", "region": "RM", "pais": "CHILE",
        "latitud": COORD_DESTINO.latitud, "longitud": COORD_DESTINO.longitud, "aliases": [],
        "estado_calidad": "PENDIENTE", "estado_vigencia": "ACTIVO", "fuente": "TEST", "observacion": "",
        "fecha_creacion": fecha, "fecha_modificacion": fecha,
    }
    obra = {
        "obra_id": "obra-ebema", "cliente_id": "cliente-ebema", "nombre_canonico": "EBEMA SA",
        "nombre_normalizado": "EBEMA SA", "aliases_documentales": [], "estado": "CONFIRMADA",
        "estado_vigencia": "ACTIVO", "evidencias": [evidencia_humana],
        "fecha_creacion": fecha, "fecha_modificacion": fecha,
    }
    relacion = {
        "relacion_id": "rel-ebema", "obra_id": "obra-ebema", "destino_id": "destino-galvarino",
        "estado": "CONFIRMADA", "evidencias": [evidencia_humana], "fuente_confirmacion": "CONFIRMACION_HUMANA_TEST",
        "confirmado_por": "JAVIER_MBT", "fecha_confirmacion": fecha, "observaciones": "",
        "fecha_creacion": fecha, "fecha_modificacion": fecha,
    }
    for nombre, contenido in {
        "clientes.json": {"version_formato": 1, "clientes": [cliente]},
        "destinos_maestros.json": {"version_formato": 1, "destinos": [destino]},
        "obras_destinos.json": {"version_formato": 1, "obras": [obra], "relaciones": [relacion]},
    }.items():
        (catalogos / nombre).write_text(json.dumps(contenido), encoding="utf-8")
    planta = CatalogoPlantas(catalogos / "plantas.json").crear(
        nombre="AZA COLINA", pais="CHILE", fuente="TEST", direccion="AV EJEMPLO 1", comuna="COLINA",
        region="RM", latitud=-33.137558, longitud=-70.665977, estado_calidad=EstadoCalidad.CONFIRMADA,
    )
    dataset = actual / "analisis_completo_guias.csv"
    with dataset.open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader()
        for overrides in filas:
            fila = {c: "" for c in COLUMNAS}
            fila.update({
                "estado_procesamiento": "OK", "cliente": "EBEMA SA", "obra_destino": "EBEMA SA",
                "indicador_revision": "OK", "estado_documental": "OK", "estado_operacional": "OK",
                "planta_origen_id": planta.planta_id, "planta_origen_nombre": "AZA COLINA",
                "estado_entrega": "RESUELTO", "localidad_entrega": "Quilicura",
                "region_entrega": "Metropolitana", "distancia_km": "13.4103",
                "duracion_min": "20.288333333333334", "proveedor_ruta": "openrouteservice",
                "estado_ruta": "RUTA_CALCULADA", "motivo_ruta": "",
            })
            fila.update(overrides)
            escritor.writerow(fila)
    return dataset, catalogos


def _leer(dataset):
    with dataset.open("r", newline="", encoding="utf-8-sig") as archivo:
        return {f["numero_guia"]: f for f in csv.DictReader(archivo, delimiter=";")}


def test_475176_ruta_al_centroide_se_reancla_al_destino_confirmado(tmp_path):
    dataset, catalogos = _entorno(tmp_path, [
        {"archivo": "475176.jpeg", "numero_guia": "475176", "numero_transporte": "0000361792",
         "despachar_a_crudo": DOCUMENTAL_475176, "direccion_entrega": DOCUMENTAL_475176},
    ])
    proveedor = _ProveedorQueRegistra(
        resultado_ruta=ResultadoRuta(EstadoRuta.RUTA_CALCULADA, 13.1788, 19.5, "TEST"),
    )

    resultado = revalidar_ruta_con_destino_confirmado_en_catalogo_sin_ocr(
        ruta_dataset=dataset, carpeta_catalogos=catalogos, proveedor_rutas=proveedor,
        proveedor_rutas_fallback=ProveedorRutasSimulado(), guias_objetivo={"475176"},
    )

    assert resultado["guias_actualizadas"] == ["475176"]
    assert proveedor.destinos_ruteados == [COORD_DESTINO]
    fila = _leer(dataset)["475176"]
    assert fila["despachar_a_crudo"] == DOCUMENTAL_475176  # evidencia OCR intacta
    assert fila["direccion_entrega"] == DIRECCION_CANONICA
    assert fila["localidad_entrega"] == "QUILICURA"
    assert fila["distancia_km"] == "13.1788"
    assert fila["estado_ruta"] == "RUTA_CALCULADA"
    assert fila["estado_operacional"] == "OK"

    # Idempotente: ya anclada al canónico, no vuelve a rutear.
    segunda = revalidar_ruta_con_destino_confirmado_en_catalogo_sin_ocr(
        ruta_dataset=dataset, carpeta_catalogos=catalogos, proveedor_rutas=proveedor,
        proveedor_rutas_fallback=ProveedorRutasSimulado(), guias_objetivo={"475176"},
    )
    assert segunda["guias_actualizadas"] == []
    assert len(proveedor.destinos_ruteados) == 1


def test_ruta_calculada_con_texto_literal_u_otro_numero_no_se_toca(tmp_path):
    dataset, catalogos = _entorno(tmp_path, [
        {"archivo": "1.jpeg", "numero_guia": "1", "despachar_a_crudo": "GALVARINO 8501 QUILICURA",
         "direccion_entrega": "GALVARINO 8501 QUILICURA"},
        {"archivo": "2.jpeg", "numero_guia": "2", "despachar_a_crudo": "GALVARINO B502 QUILICURA",
         "direccion_entrega": "GALVARINO B502 QUILICURA"},
        {"archivo": "3.jpeg", "numero_guia": "3", "despachar_a_crudo": "GALVARINO 501 QUILICURA",
         "direccion_entrega": "GALVARINO 501 QUILICURA"},
    ])
    antes = _leer(dataset)
    proveedor = _ProveedorQueRegistra()

    resultado = revalidar_ruta_con_destino_confirmado_en_catalogo_sin_ocr(
        ruta_dataset=dataset, carpeta_catalogos=catalogos, proveedor_rutas=proveedor,
        proveedor_rutas_fallback=ProveedorRutasSimulado(),
    )

    assert resultado["guias_actualizadas"] == []
    assert resultado["guias_contradiccion"] == []
    assert proveedor.destinos_ruteados == []
    assert _leer(dataset) == antes
