"""G1-C: invalidación territorial de derivados + cierre de supuestos
RM/Chile restantes en el engine genérico.

Cierra el vacío real encontrado en la auditoría integral: G1-B agregó
codigo_pais/codigo_unidad/codigo_contexto a CandidatoGeocodificacion y
ResultadoDestinoEntrega, pero esa identidad territorial por código NUNCA
llegaba a persistirse en el dataset (CAMPOS_ENTREGA_DOCUMENTO no las
incluía) ni participaba de la invalidación R2.5 (CAMPOS_DERIVADOS_RUTA
tampoco). Este bloque completa la tubería -- ResultadoRutaEntrega,
resolver_entrega_documento, revalidar_ruta_sin_destino_calculado_sin_ocr,
la corroboración GPS de origen -- y actualiza `_misma_localidad` para usar
identidad por código en vez de comparación de texto.

También cubre la compatibilidad hacia atrás: el dataset real de
producción no tiene todavía estas 3 columnas nuevas (sin migración
masiva) -- todo punto que valida el esquema del CSV debe seguir aceptando
ese encabezado más corto.
"""
from __future__ import annotations

import csv

from atlas_core.procesamiento_masivo import COLUMNAS, COLUMNAS_PRE_G1C
from atlas_core.revalidacion_documental import (
    CAMPOS_DERIVADOS_RUTA,
    _escribir_filas_completas,
    _leer_filas,
    invalidar_derivados_ruta,
)
from atlas_core.rutas.destino_entrega import (
    CAMPOS_ENTREGA_DOCUMENTO,
    _misma_localidad,
    calcular_ruta_con_planta_conocida,
)
from atlas_core.rutas.modelos import CandidatoGeocodificacion, Coordenadas, EstadoRuta, ResultadoGeocodificacion, ResultadoRuta
from atlas_core.rutas.proveedor import ProveedorRutasSimulado
from atlas_core.catalogo_plantas import EstadoCalidad


# ============================================================
# A) Invalidación territorial -- D1/D2: el código forma parte del
#    invariante R2.5, no sólo el texto legacy.
# ============================================================


def test_campos_entrega_documento_incluye_los_codigos_territoriales():
    assert "codigo_pais" in CAMPOS_ENTREGA_DOCUMENTO
    assert "codigo_unidad" in CAMPOS_ENTREGA_DOCUMENTO
    assert "codigo_contexto" in CAMPOS_ENTREGA_DOCUMENTO


def test_invalidar_derivados_ruta_limpia_tambien_los_codigos_territoriales():
    assert "codigo_pais" in CAMPOS_DERIVADOS_RUTA
    assert "codigo_unidad" in CAMPOS_DERIVADOS_RUTA
    assert "codigo_contexto" in CAMPOS_DERIVADOS_RUTA
    limpio = invalidar_derivados_ruta()
    assert limpio["codigo_pais"] == ""
    assert limpio["codigo_unidad"] == ""
    assert limpio["codigo_contexto"] == ""
    # El texto legacy se sigue limpiando exactamente igual que antes de
    # este bloque -- nunca se reemplaza, se agrega.
    assert limpio["localidad_entrega"] == ""
    assert limpio["region_entrega"] == ""
    assert limpio["distancia_km"] == ""


# ============================================================
# B) `_misma_localidad` -- D3/D4/D5: identidad por código, no por texto.
# ============================================================


def _candidato(localidad="", region="", codigo_pais="", codigo_unidad=""):
    return CandidatoGeocodificacion(
        Coordenadas(-70.6, -33.4), "DEMO", 0.9, localidad, region,
        codigo_pais=codigo_pais, codigo_unidad=codigo_unidad,
    )


def test_D3_mismo_codigo_con_texto_distinto_se_trata_como_la_misma_localidad():
    """Texto crudo distinto (mayúsculas/alias del proveedor), MISMO código
    oficial -> nunca se trata como "otra localidad"."""
    a = _candidato(localidad="Santiago", region="Región Metropolitana", codigo_pais="CL", codigo_unidad="13101")
    b = _candidato(localidad="STGO CENTRO", region="RM", codigo_pais="CL", codigo_unidad="13101")
    assert _misma_localidad(a, b) is True


def test_D4_alias_territorial_equivalente_no_genera_diferencia():
    """Caso de alias real (ver ALIAS_REGIONES en cl.py): dos textos de
    región completamente distintos que resuelven a la MISMA comuna oficial
    (mismo codigo_unidad) siguen siendo la misma localidad."""
    a = _candidato(localidad="Providencia", region="Metropolitana", codigo_pais="CL", codigo_unidad="13123")
    b = _candidato(localidad="Providencia", region="Region Metropolitana de Santiago", codigo_pais="CL", codigo_unidad="13123")
    assert _misma_localidad(a, b) is True


def test_D5_codigo_distinto_es_una_localidad_materialmente_distinta():
    """Aunque el texto de región coincida (misma RM), un código de comuna
    distinto SÍ es una localidad distinta -- nunca se abstiene sólo por
    "misma región"."""
    a = _candidato(localidad="Santiago", region="Metropolitana", codigo_pais="CL", codigo_unidad="13101")
    b = _candidato(localidad="Providencia", region="Metropolitana", codigo_pais="CL", codigo_unidad="13123")
    assert _misma_localidad(a, b) is False


def test_sin_codigo_resuelto_cae_al_criterio_legacy_de_texto():
    """Candidatos sin código (fuera de Chile, o la geografía no pudo
    resolverlo EXACTA) -- comportamiento IDÉNTICO a antes de G1-C: texto
    exacto sin acentos/mayúsculas."""
    a = _candidato(localidad="Coronel", region="Biobío")
    b = _candidato(localidad="CORONEL", region="BIOBIO")
    assert _misma_localidad(a, b) is True
    c = _candidato(localidad="Talcahuano", region="Biobío")
    assert _misma_localidad(a, c) is False


# ============================================================
# C) D7 -- recálculo posterior puede volver a poblar la identidad
#    territorial junto con la ruta.
# ============================================================


def test_D7_recalculo_repuebla_codigo_unidad_junto_con_la_ruta(tmp_path):
    planta = _planta_prueba(tmp_path)
    despachar_a = "SANTA ISABEL 585, SANTIAGO"
    consulta = f"{despachar_a}, Chile"
    geocodificaciones = {
        consulta: ResultadoGeocodificacion(
            EstadoRuta.REQUIERE_REVISION,
            (CandidatoGeocodificacion(
                Coordenadas(-70.63, -33.45), "Santa Isabel 585", 0.8,
                localidad="Santiago", region="Metropolitana",
                codigo_pais="CL", codigo_unidad="13101", codigo_contexto="13",
            ),),
            "REQUIERE_CONFIRMACION_HUMANA",
        )
    }
    proveedor = ProveedorRutasSimulado(
        geocodificaciones=geocodificaciones,
        resultado_ruta=ResultadoRuta(EstadoRuta.RUTA_CALCULADA, 12.3, 25.0, ""),
    )

    resultado = calcular_ruta_con_planta_conocida(
        planta=planta, despachar_a_crudo=despachar_a, proveedor_rutas=proveedor,
    )

    assert resultado.estado_ruta == EstadoRuta.RUTA_CALCULADA.value
    assert resultado.codigo_pais == "CL"
    assert resultado.codigo_unidad == "13101"
    assert resultado.codigo_contexto == "13"


def _planta_prueba(tmp_path):
    from atlas_core.catalogo_plantas import CatalogoPlantas

    catalogo = CatalogoPlantas(tmp_path / "plantas.json")
    return catalogo.crear(
        nombre="AZA COLINA", pais="CHILE", fuente="TEST",
        direccion="AV EJEMPLO 1", comuna="COLINA", region="RM",
        latitud=-33.137558, longitud=-70.665977, estado_calidad=EstadoCalidad.CONFIRMADA,
    )


# ============================================================
# D) Compatibilidad -- dataset real todavía sin las 3 columnas nuevas.
# ============================================================


def test_columnas_pre_g1c_es_exactamente_columnas_sin_los_3_codigos():
    assert set(COLUMNAS) - set(COLUMNAS_PRE_G1C) == {"codigo_pais", "codigo_unidad", "codigo_contexto"}
    assert len(COLUMNAS) == len(COLUMNAS_PRE_G1C) + 3


def test_leer_filas_acepta_encabezado_real_sin_codigos_territoriales(tmp_path):
    """El dataset real de producción tiene EXACTAMENTE este encabezado
    (COLUMNAS_PRE_G1C) hoy -- _leer_filas debe seguir leyéndolo, nunca
    "esquema incompatible", sin que nadie migre nada a mano."""
    ruta = tmp_path / "dataset.csv"
    with ruta.open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS_PRE_G1C, delimiter=";")
        escritor.writeheader()
        escritor.writerow({c: "" for c in COLUMNAS_PRE_G1C} | {"numero_guia": "111111"})

    filas = _leer_filas(ruta)
    assert len(filas) == 1
    assert filas[0]["numero_guia"] == "111111"
    # Los 3 códigos nuevos simplemente no existen todavía en esta fila --
    # nunca se inventa un valor, csv.DictReader los deja ausentes del dict.
    assert "codigo_unidad" not in filas[0]


def test_escribir_filas_completas_migra_el_encabezado_a_columnas_completo(tmp_path):
    """Migración perezosa: en cuanto CUALQUIER escritor real reescribe el
    archivo (vía _escribir_filas_completas, el mismo camino que ya usan
    las 23 revalidaciones _sin_ocr), el encabezado queda actualizado con
    las 3 columnas nuevas -- restval="" para las filas viejas, nunca un
    valor inventado."""
    ruta = tmp_path / "dataset.csv"
    with ruta.open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS_PRE_G1C, delimiter=";")
        escritor.writeheader()
        escritor.writerow({c: "" for c in COLUMNAS_PRE_G1C} | {"numero_guia": "111111"})

    filas = _leer_filas(ruta)
    _escribir_filas_completas(ruta, filas)

    with ruta.open(encoding="utf-8-sig", newline="") as archivo:
        lector = csv.DictReader(archivo, delimiter=";")
        assert list(lector.fieldnames) == COLUMNAS
        fila = next(lector)
        assert fila["codigo_unidad"] == ""
        assert fila["numero_guia"] == "111111"


def test_validar_csv_existente_tolera_y_migra_encabezado_pre_g1c(tmp_path):
    from atlas_core.procesamiento_masivo import _validar_csv_existente

    ruta = tmp_path / "dataset.csv"
    with ruta.open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS_PRE_G1C, delimiter=";")
        escritor.writeheader()
        escritor.writerow({c: "" for c in COLUMNAS_PRE_G1C} | {"numero_guia": "222222"})

    assert _validar_csv_existente(ruta) is True

    with ruta.open(encoding="utf-8-sig", newline="") as archivo:
        lector = csv.DictReader(archivo, delimiter=";")
        assert list(lector.fieldnames) == COLUMNAS


def test_reporte_viajes_no_exige_los_codigos_territoriales_como_obligatorios():
    """La generación de reporte contra el dataset real (sin las 3
    columnas nuevas todavía) no debe romperse -- se tratan como
    opcionales, igual que COLUMNAS_HISTORICAS."""
    from atlas_core.reporte_viajes import COLUMNAS_OBLIGATORIAS, _validar_esquema

    assert "codigo_pais" not in COLUMNAS_OBLIGATORIAS
    assert "codigo_unidad" not in COLUMNAS_OBLIGATORIAS
    assert "codigo_contexto" not in COLUMNAS_OBLIGATORIAS
    _validar_esquema(list(COLUMNAS_PRE_G1C))  # nunca lanza


# ============================================================
# E) D8 -- el engine genérico sigue sin supuestos Chile/RM (ninguno de
#    los archivos de este bloque toca contratos/modelos/motor.py; se
#    reconfirma explícitamente que sigue siendo cierto).
# ============================================================


def test_mobile_append_sobre_dataset_pre_g1c_migra_el_encabezado_y_escribe_bien(tmp_path, monkeypatch):
    """Compatibilidad real: el dataset de producción tiene HOY el
    encabezado COLUMNAS_PRE_G1C. `_escribir_filas` (append puro, nunca
    reescribe el encabezado en disco) NO puede usarse directo sobre un
    archivo así sin corromper el CSV -- procesar_envio_mobile debe migrar
    con una reescritura completa en vez de un append a ciegas."""
    import csv
    import uuid

    from atlas_core.mobile import RepositorioEnviosMobile, procesar_envio_mobile
    import atlas_core.mobile as mobile_modulo

    raiz = tmp_path / "Atlas"
    repo = RepositorioEnviosMobile(raiz)
    envio_id = str(uuid.uuid4())
    repo.recibir(
        envio_id=envio_id, imagen=b"foto", mime="image/jpeg",
        metadata={"chofer_id": "c1", "tipo_novedad": "", "guia_firmada_correo": False, "planta_origen_informada": "AZA_COLINA"},
    )

    dataset = raiz / "operacion" / "actual" / "analisis_completo_guias.csv"
    dataset.parent.mkdir(parents=True, exist_ok=True)
    with dataset.open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS_PRE_G1C, delimiter=";")
        escritor.writeheader()
        escritor.writerow(
            {c: "" for c in COLUMNAS_PRE_G1C} | {"archivo": "mobile/otro/original.jpg", "numero_guia": "800001"}
        )

    monkeypatch.setattr(mobile_modulo, "crear_proveedor_ocr", lambda: object())
    monkeypatch.setattr(
        mobile_modulo, "procesar_archivo",
        lambda ruta, **kw: {
            "numero_guia": "900001", "numero_transporte": "0000900000", "cliente": "SODIMAC SA",
        },
    )

    resultado = procesar_envio_mobile(repo, envio_id, dataset=dataset)

    assert resultado["estado"] != "ERROR", resultado.get("error")
    assert resultado["archivo_dataset"] == f"mobile/{envio_id}/original.jpg"

    with dataset.open(encoding="utf-8-sig", newline="") as archivo:
        lector = csv.DictReader(archivo, delimiter=";")
        assert list(lector.fieldnames) == COLUMNAS
        filas = list(lector)
    assert len(filas) == 2  # la fila vieja se preserva, no se pierde en la migración
    numeros_guia = {f["numero_guia"] for f in filas}
    assert numeros_guia == {"800001", "900001"}


def test_D8_engine_generico_sigue_sin_literales_chile():
    import atlas_core.geografia.motor as motor_modulo
    import atlas_core.geografia.contratos as contratos_modulo
    import atlas_core.geografia.modelos as modelos_modulo

    for modulo in (motor_modulo, contratos_modulo, modelos_modulo):
        texto = open(modulo.__file__, encoding="utf-8").read().upper()
        for prohibido in ("SANTIAGO", "COMUNA", "PROVINCIA", "METROPOLITANA"):
            assert prohibido not in texto, f"{prohibido!r} filtrado al core en {modulo.__name__}"
