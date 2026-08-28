"""Bloque SINCRONIZACIÓN OPERACIONAL 472593 --
`revalidar_origen_por_evidencia_mobile_sin_ocr`: reaplica la política ya
vigente de ORIGEN OPERACIONAL V2 (`atlas_core.rutas.origen_evidencia.
fusionar_evidencia_origen`, sin cambios) sobre filas cuyo origen quedó
determinado SÓLO por el encabezado documental, usando evidencia Mobile
YA persistida (`envio.json`, `planta_origen_informada`) -- sin OCR, sin
GPS nuevo, sin red.

Causa raíz real (guía 472593, envío Mobile
36e7aa53-214e-48b0-a96c-14989b60e9aa): Mobile informó AZA_COLINA,
compatible con la carga documental (BARRAS); el dataset productivo
quedó publicado con AZA RENCA (encabezado societario, incompatible con
BARRAS por regla configurada) porque este documento se procesó antes de
que la fusión Mobile/Documento llegara a correr sobre él."""
from __future__ import annotations

import csv

from atlas_core.catalogo_plantas import CatalogoPlantas, EstadoCalidad
from atlas_core.mobile import RepositorioEnviosMobile
from atlas_core.procesamiento_masivo import COLUMNAS
from atlas_core.revalidacion_documental import revalidar_origen_por_evidencia_mobile_sin_ocr

COORD_COLINA = (-70.6739, -33.1975)
COORD_RENCA = (-70.685226, -33.401595)


def _fila(**overrides):
    fila = {c: "" for c in COLUMNAS}
    fila.update({
        "archivo": "mobile/envio-1/original.jpg", "estado_procesamiento": "OK",
        "numero_guia": "1", "numero_transporte": "T1", "fecha": "01-08-2026",
        "cliente": "CLIENTE GENERICO SA", "rut_cliente": "76.111.111-6",
        "chofer": "CHOFER TEST", "patente_tracto": "AB1234",
        "indicador_revision": "OK", "origen_determinado_por": "DOCUMENTO",
        "evidencia_origen": "ENCABEZADO_GUIA", "tipo_carga": "BARRAS",
    })
    fila.update(overrides)
    return fila


def _escribir_dataset(tmp_path, filas):
    dataset = tmp_path / "dataset.csv"
    with dataset.open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader()
        escritor.writerows(filas)
    return dataset


def _crear_envio(repositorio, envio_id, *, planta_informada):
    repositorio.guardar(envio_id, {
        "schema_version": 1, "envio_id": envio_id, "estado": "ASOCIADO_AUTOMATICAMENTE",
        "foto_original": "original.jpg", "planta_origen_informada": planta_informada,
    })


def _crear_plantas(carpeta, *, nombre_a, categorias_a, nombre_b, categorias_b):
    catalogo = CatalogoPlantas(carpeta / "plantas.json")
    a = catalogo.crear(
        nombre=nombre_a, pais="CHILE", fuente="TEST", estado_calidad=EstadoCalidad.CONFIRMADA,
        categorias_permitidas=categorias_a,
    )
    b = catalogo.crear(
        nombre=nombre_b, pais="CHILE", fuente="TEST", estado_calidad=EstadoCalidad.CONFIRMADA,
        categorias_permitidas=categorias_b,
    )
    return a, b


# ============================================================
# 1. Regresión real -- valores reales de 472593 (AZA/COLINA/RENCA/BARRAS)
# ============================================================


def test_regresion_472593_mobile_colina_corrige_encabezado_renca(tmp_path):
    catalogos = tmp_path / "catalogos"; catalogos.mkdir()
    colina, renca = _crear_plantas(
        catalogos, nombre_a="AZA COLINA", categorias_a=("BARRAS", "ROLLOS"),
        nombre_b="AZA RENCA", categorias_b=("ANGULOS",),
    )
    repo = RepositorioEnviosMobile(tmp_path)
    _crear_envio(repo, "36e7aa53-214e-48b0-a96c-14989b60e9aa", planta_informada="AZA_COLINA")

    fila = _fila(
        archivo="mobile/36e7aa53-214e-48b0-a96c-14989b60e9aa/original.jpg",
        numero_guia="472593", numero_transporte="0000355419", cliente="PRODALAM SA",
        rut_cliente="93.772.000-9", planta_origen_id=renca.planta_id, planta_origen_nombre=renca.nombre,
        tipo_carga="BARRAS",
    )
    dataset = _escribir_dataset(tmp_path, [fila])
    resultado = revalidar_origen_por_evidencia_mobile_sin_ocr(
        ruta_dataset=dataset, carpeta_catalogos=catalogos, repositorio=repo,
    )
    assert resultado["guias_actualizadas"] == ["472593"]
    fila_final = list(csv.DictReader(dataset.open(encoding="utf-8-sig"), delimiter=";"))[0]
    assert fila_final["planta_origen_id"] == colina.planta_id
    assert fila_final["planta_origen_nombre"] == "AZA COLINA"
    assert fila_final["origen_determinado_por"] == "MOBILE"
    assert fila_final["evidencia_origen"] == "MOBILE_COMPATIBLE_DOCUMENTO_CONTRADICE_REGLA"


# ============================================================
# 2. Fixture universal -- otro rubro, nombres genéricos
# ============================================================


def test_fixture_universal_distribuidora_sucursal_compatible_corrige_encabezado(tmp_path):
    """Mismo mecanismo, rubro distinto (distribución de alimentos) y
    nombres genéricos -- nada hardcodeado a AZA/COLINA/RENCA/BARRAS."""
    catalogos = tmp_path / "catalogos"; catalogos.mkdir()
    sucursal_norte, sucursal_sur = _crear_plantas(
        catalogos, nombre_a="SUCURSAL NORTE", categorias_a=("REFRIGERADOS", "SECOS"),
        nombre_b="SUCURSAL SUR", categorias_b=("CONGELADOS",),
    )
    repo = RepositorioEnviosMobile(tmp_path)
    _crear_envio(repo, "envio-2", planta_informada="SUCURSAL_NORTE")

    fila = _fila(
        archivo="mobile/envio-2/original.jpg", numero_guia="900002", numero_transporte="T900002",
        cliente="DISTRIBUIDORA GENERICA SPA", planta_origen_id=sucursal_sur.planta_id,
        planta_origen_nombre=sucursal_sur.nombre, tipo_carga="SECOS",
    )
    dataset = _escribir_dataset(tmp_path, [fila])
    resultado = revalidar_origen_por_evidencia_mobile_sin_ocr(
        ruta_dataset=dataset, carpeta_catalogos=catalogos, repositorio=repo,
    )
    assert resultado["guias_actualizadas"] == ["900002"]
    fila_final = list(csv.DictReader(dataset.open(encoding="utf-8-sig"), delimiter=";"))[0]
    assert fila_final["planta_origen_id"] == sucursal_norte.planta_id
    assert fila_final["origen_determinado_por"] == "MOBILE"


# ============================================================
# 3. No-op: Mobile ya coincide con el documento -- nada que cambiar
# ============================================================


def test_sin_cambio_si_mobile_ya_coincide_con_documento(tmp_path):
    catalogos = tmp_path / "catalogos"; catalogos.mkdir()
    norte, _sur = _crear_plantas(
        catalogos, nombre_a="SUCURSAL NORTE", categorias_a=("SECOS",),
        nombre_b="SUCURSAL SUR", categorias_b=("CONGELADOS",),
    )
    repo = RepositorioEnviosMobile(tmp_path)
    _crear_envio(repo, "envio-3", planta_informada="SUCURSAL_NORTE")

    fila = _fila(
        archivo="mobile/envio-3/original.jpg", numero_guia="900003", numero_transporte="T900003",
        planta_origen_id=norte.planta_id, planta_origen_nombre=norte.nombre, tipo_carga="SECOS",
    )
    dataset = _escribir_dataset(tmp_path, [fila])
    resultado = revalidar_origen_por_evidencia_mobile_sin_ocr(
        ruta_dataset=dataset, carpeta_catalogos=catalogos, repositorio=repo,
    )
    assert resultado["guias_actualizadas"] == []


# ============================================================
# 4. Contradicción real -- ninguna evidencia gana a ciegas
# ============================================================


def test_sin_cambio_ante_contradiccion_real(tmp_path):
    """Ambas plantas incompatibles con la categoría documental: ninguna
    evidencia gana -- se conserva la fila para revisión, nunca se fuerza."""
    catalogos = tmp_path / "catalogos"; catalogos.mkdir()
    norte, sur = _crear_plantas(
        catalogos, nombre_a="SUCURSAL NORTE", categorias_a=("REFRIGERADOS",),
        nombre_b="SUCURSAL SUR", categorias_b=("CONGELADOS",),
    )
    repo = RepositorioEnviosMobile(tmp_path)
    _crear_envio(repo, "envio-4", planta_informada="SUCURSAL_NORTE")

    fila = _fila(
        archivo="mobile/envio-4/original.jpg", numero_guia="900004", numero_transporte="T900004",
        planta_origen_id=sur.planta_id, planta_origen_nombre=sur.nombre, tipo_carga="SECOS",
    )
    dataset = _escribir_dataset(tmp_path, [fila])
    resultado = revalidar_origen_por_evidencia_mobile_sin_ocr(
        ruta_dataset=dataset, carpeta_catalogos=catalogos, repositorio=repo,
    )
    assert resultado["guias_actualizadas"] == []
    fila_final = list(csv.DictReader(dataset.open(encoding="utf-8-sig"), delimiter=";"))[0]
    assert fila_final["planta_origen_id"] == sur.planta_id  # intacta


# ============================================================
# 5. Ruta ya calculada se invalida al cambiar el origen
# ============================================================


def test_invalida_ruta_ya_calculada_al_cambiar_origen(tmp_path):
    catalogos = tmp_path / "catalogos"; catalogos.mkdir()
    norte, sur = _crear_plantas(
        catalogos, nombre_a="SUCURSAL NORTE", categorias_a=("SECOS",),
        nombre_b="SUCURSAL SUR", categorias_b=("CONGELADOS",),
    )
    repo = RepositorioEnviosMobile(tmp_path)
    _crear_envio(repo, "envio-5", planta_informada="SUCURSAL_NORTE")

    fila = _fila(
        archivo="mobile/envio-5/original.jpg", numero_guia="900005", numero_transporte="T900005",
        planta_origen_id=sur.planta_id, planta_origen_nombre=sur.nombre, tipo_carga="SECOS",
        distancia_km="12.34", duracion_min="20.5", proveedor_ruta="openrouteservice",
        estado_ruta="RUTA_CALCULADA",
    )
    dataset = _escribir_dataset(tmp_path, [fila])
    resultado = revalidar_origen_por_evidencia_mobile_sin_ocr(
        ruta_dataset=dataset, carpeta_catalogos=catalogos, repositorio=repo,
    )
    assert resultado["guias_actualizadas"] == ["900005"]
    fila_final = list(csv.DictReader(dataset.open(encoding="utf-8-sig"), delimiter=";"))[0]
    assert fila_final["planta_origen_id"] == norte.planta_id
    assert fila_final["distancia_km"] == ""
    assert fila_final["duracion_min"] == ""
    assert fila_final["proveedor_ruta"] == ""
    assert fila_final["estado_ruta"] == "REQUIERE_REVISION"
    assert fila_final["motivo_ruta"] == "ORIGEN_ACTUALIZADO_PENDIENTE_RECALCULO_RUTA"


# ============================================================
# 6. Nunca revisita GPS/confirmación humana
# ============================================================


def test_nunca_revisita_origen_gps_o_confirmacion_humana(tmp_path):
    catalogos = tmp_path / "catalogos"; catalogos.mkdir()
    norte, sur = _crear_plantas(
        catalogos, nombre_a="SUCURSAL NORTE", categorias_a=("SECOS",),
        nombre_b="SUCURSAL SUR", categorias_b=("CONGELADOS",),
    )
    repo = RepositorioEnviosMobile(tmp_path)
    _crear_envio(repo, "envio-6", planta_informada="SUCURSAL_NORTE")
    _crear_envio(repo, "envio-7", planta_informada="SUCURSAL_NORTE")

    fila_gps = _fila(
        archivo="mobile/envio-6/original.jpg", numero_guia="900006", numero_transporte="T900006",
        planta_origen_id=sur.planta_id, planta_origen_nombre=sur.nombre, tipo_carga="SECOS",
        origen_determinado_por="TELEMETRIA_GPS",
    )
    fila_humana = _fila(
        archivo="mobile/envio-7/original.jpg", numero_guia="900007", numero_transporte="T900007",
        planta_origen_id=sur.planta_id, planta_origen_nombre=sur.nombre, tipo_carga="SECOS",
        origen_determinado_por="CONFIRMACION_HUMANA",
    )
    dataset = _escribir_dataset(tmp_path, [fila_gps, fila_humana])
    resultado = revalidar_origen_por_evidencia_mobile_sin_ocr(
        ruta_dataset=dataset, carpeta_catalogos=catalogos, repositorio=repo,
    )
    assert resultado["guias_actualizadas"] == []


# ============================================================
# 7. Preserva transporte/RUT/cliente/foto -- sólo campos de origen/ruta
# ============================================================


def test_preserva_transporte_rut_cliente_y_no_toca_otras_filas(tmp_path):
    catalogos = tmp_path / "catalogos"; catalogos.mkdir()
    norte, sur = _crear_plantas(
        catalogos, nombre_a="SUCURSAL NORTE", categorias_a=("SECOS",),
        nombre_b="SUCURSAL SUR", categorias_b=("CONGELADOS",),
    )
    repo = RepositorioEnviosMobile(tmp_path)
    _crear_envio(repo, "envio-8", planta_informada="SUCURSAL_NORTE")

    fila_objetivo = _fila(
        archivo="mobile/envio-8/original.jpg", numero_guia="900008", numero_transporte="T900008",
        cliente="CLIENTE OCHO SA", rut_cliente="76.222.222-2", chofer="JUAN PEREZ",
        patente_tracto="XY9876", planta_origen_id=sur.planta_id, planta_origen_nombre=sur.nombre,
        tipo_carga="SECOS",
    )
    otra_fila = _fila(
        archivo="mobile/envio-9/original.jpg", numero_guia="900009", numero_transporte="T900009",
        planta_origen_id=norte.planta_id, planta_origen_nombre=norte.nombre,
        origen_determinado_por="CONFIRMACION_HUMANA",
    )
    dataset = _escribir_dataset(tmp_path, [fila_objetivo, otra_fila])
    resultado = revalidar_origen_por_evidencia_mobile_sin_ocr(
        ruta_dataset=dataset, carpeta_catalogos=catalogos, repositorio=repo,
    )
    assert resultado["guias_actualizadas"] == ["900008"]

    filas = {f["numero_guia"]: f for f in csv.DictReader(dataset.open(encoding="utf-8-sig"), delimiter=";")}
    objetivo = filas["900008"]
    assert objetivo["numero_transporte"] == "T900008"
    assert objetivo["cliente"] == "CLIENTE OCHO SA"
    assert objetivo["rut_cliente"] == "76.222.222-2"
    assert objetivo["chofer"] == "JUAN PEREZ"
    assert objetivo["patente_tracto"] == "XY9876"
    assert objetivo["archivo"] == "mobile/envio-8/original.jpg"
    assert filas["900009"]["planta_origen_id"] == norte.planta_id  # otra fila, intacta
