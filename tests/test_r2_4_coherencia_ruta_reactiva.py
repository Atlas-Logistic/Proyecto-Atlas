"""Bloque R2.4 -- COHERENCIA FINAL DE RUTA ANTES DE MOBILE.

Un viaje con destino operacional no puede quedar OK/CONFIRMADO mientras
la dependencia de ruta/km/tiempo siga pendiente -- caso real 464170:
origen se resolvió a AZA COLINA (R2.3) pero el viaje quedó "OK" con
"Ruta aún no calculada" (bug real: la reconciliación de origen ponía OK
apenas limpiaba estado_ruta, sin haber calculado ningún km/tiempo).

Cadena reactiva completa probada aquí, encadenando los dos revalidadores
reales (nunca simulada por separado): origen se resuelve por eliminación
de categoría (R2.3) → el revalidador de ruta (ya existente) intenta
geocodificación/routing con el origen ya resuelto → persiste km/tiempo o
falla con causa -- sin OCR, sin decisión humana ficticia, mecanismo
GENERAL existente en ambos pasos."""
import csv

from atlas_core.catalogo_plantas import CatalogoPlantas, EstadoCalidad
from atlas_core.procesamiento_masivo import COLUMNAS
from atlas_core.revalidacion_documental import (
    revalidar_origen_por_eliminacion_categoria_sin_ocr,
    revalidar_ruta_sin_destino_calculado_sin_ocr,
)
from atlas_core.rutas.modelos import (
    CandidatoGeocodificacion, Coordenadas, EstadoRuta, ResultadoGeocodificacion, ResultadoRuta,
)

COORD_COLINA = Coordenadas(-70.665977, -33.137558)
COORD_RENCA = Coordenadas(-70.685226, -33.401595)


def _catalogos(tmp_path):
    carpeta = tmp_path / "catalogos"
    carpeta.mkdir()
    plantas = CatalogoPlantas(carpeta / "plantas.json")
    colina = plantas.crear(
        nombre="PLANTA NORTE", pais="CHILE", fuente="TEST",
        direccion="CALLE NORTE 100", comuna="COLINA", region="RM",
        latitud=COORD_COLINA.latitud, longitud=COORD_COLINA.longitud,
        estado_calidad=EstadoCalidad.CONFIRMADA, categorias_permitidas=("BARRAS", "ROLLOS"),
    )
    renca = plantas.crear(
        nombre="PLANTA SUR", pais="CHILE", fuente="TEST",
        direccion="CALLE SUR 200", comuna="RENCA", region="RM",
        latitud=COORD_RENCA.latitud, longitud=COORD_RENCA.longitud,
        estado_calidad=EstadoCalidad.CONFIRMADA, categorias_permitidas=("ANGULOS",),
    )
    return carpeta, colina, renca


def _fila_csv(**overrides):
    fila = {c: "" for c in COLUMNAS}
    fila.update({
        "archivo": "g.jpeg", "estado_procesamiento": "OK", "numero_guia": "1",
        "numero_transporte": "T1", "fecha": "31-08-2026",
        "tipo_carga": "BARRAS", "cliente": "CLIENTE EXTERNO", "obra_destino": "CLIENTE EXTERNO",
        "despachar_a_crudo": "CALLE DE UN CLIENTE 500 SANTIAGO",
        "estado_ruta": "ORIGEN_NO_DETERMINADO",
        "motivo_ruta": "CONTRADICCION_OPERACIONAL_ORIGEN[DOCUMENTO=PLANTA_SUR:INCOMPATIBLE]",
        "distancia_km": "", "duracion_min": "",
        "indicador_revision": "OK", "estado_documental": "OK", "estado_operacional": "REQUIERE_REVISION",
    })
    fila.update(overrides)
    return fila


def _escribir_csv(ruta, filas):
    with ruta.open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader()
        escritor.writerows(filas)


def _leer(ruta):
    with ruta.open(encoding="utf-8-sig", newline="") as archivo:
        return list(csv.DictReader(archivo, delimiter=";"))


class _ProveedorFijo:
    """A diferencia de `ProveedorRutasSimulado` (exige que la consulta
    coincida EXACTO con una clave del diccionario -- frágil, la
    normalización interna de `calcular_ruta_con_planta_conocida` no es
    parte del contrato público de este bloque), este doble responde
    SIEMPRE el mismo resultado, sin importar el texto de la consulta --
    lo único relevante para estas pruebas es la reacción de Atlas ante
    éxito/fracaso de geocodificación, nunca el texto exacto consultado."""

    def __init__(self, resultado_geocodificacion, resultado_ruta=None):
        self._resultado_geocodificacion = resultado_geocodificacion
        self._resultado_ruta = resultado_ruta
        self.nombre = "simulado_fijo"
        self.version = "1"

    def geocodificar(self, direccion):
        return self._resultado_geocodificacion

    def calcular_ruta(self, origen, destino, perfil):
        return self._resultado_ruta


def _proveedor_exitoso(consulta=""):
    # Un solo candidato, con la MISMA comuna que ya trae el texto
    # documental ("...500 SANTIAGO") y confianza máxima -- mismo patrón
    # ya probado en test_revalidar_ruta_sin_destino_r410.py (el estado
    # final RUTA_CALCULADA lo decide `resolver_destino_entrega_validado`
    # tras validar el candidato contra el texto documental, nunca el
    # EstadoRuta que el geocodificador crudo haya devuelto).
    candidato = CandidatoGeocodificacion(Coordenadas(-70.65, -33.44), "Calle De Un Cliente 500, Santiago, RM, Chile", 1.0, "Santiago", "Metropolitana")
    return _ProveedorFijo(
        ResultadoGeocodificacion(EstadoRuta.RESULTADO_AMBIGUO, (candidato,), "CANDIDATO_UNICO"),
        ResultadoRuta(EstadoRuta.RUTA_CALCULADA, 42.0, 55.0, "SINTETICO"),
    )


def _proveedor_sin_candidatos(consulta=""):
    return _ProveedorFijo(
        ResultadoGeocodificacion(EstadoRuta.DIRECCION_NO_ENCONTRADA, (), "SIN_CANDIDATOS"),
        None,
    )


# ============================================================
# 1/2 -- origen+destino confirmados + ruta faltante ≠ CONFIRMADO
# ============================================================

def test_origen_resuelto_con_ruta_pendiente_no_queda_ok(tmp_path):
    carpeta, colina, renca = _catalogos(tmp_path)
    dataset = tmp_path / "dataset.csv"
    _escribir_csv(dataset, [_fila_csv()])

    revalidar_origen_por_eliminacion_categoria_sin_ocr(ruta_dataset=dataset, carpeta_catalogos=carpeta)

    fila = _leer(dataset)[0]
    assert fila["planta_origen_nombre"] == "PLANTA NORTE"  # origen sí resuelto
    assert fila["estado_operacional"] == "REQUIERE_REVISION"  # pero el viaje NO puede quedar OK todavía


# ============================================================
# 3/4 -- resolución de origen dispara/reconcilia routing; éxito → CONFIRMADO
# ============================================================

def test_cadena_completa_origen_resuelve_y_routing_exitoso_confirma(tmp_path):
    carpeta, colina, renca = _catalogos(tmp_path)
    dataset = tmp_path / "dataset.csv"
    _escribir_csv(dataset, [_fila_csv()])

    revalidar_origen_por_eliminacion_categoria_sin_ocr(ruta_dataset=dataset, carpeta_catalogos=carpeta)
    proveedor = _proveedor_exitoso("CALLE DE UN CLIENTE 500 SANTIAGO, Chile")
    resultado_ruta = revalidar_ruta_sin_destino_calculado_sin_ocr(
        ruta_dataset=dataset, carpeta_catalogos=carpeta, proveedor_rutas=proveedor,
    )

    assert resultado_ruta["guias_actualizadas"] == ["1"]
    fila = _leer(dataset)[0]
    assert fila["estado_ruta"] == "RUTA_CALCULADA"
    assert fila["distancia_km"] == "42.0"
    assert fila["duracion_min"] == "55.0"
    assert fila["estado_operacional"] == "OK"  # recién AHORA, con km/tiempo reales


# ============================================================
# 5/6 -- routing falla → permanece INCOMPLETO_TECNICO (a nivel documento:
# REQUIERE_REVISION sin decisión, nunca OK); recuperación posterior → CONFIRMADO
# ============================================================

def test_routing_falla_permanece_pendiente_nunca_ok(tmp_path):
    carpeta, colina, renca = _catalogos(tmp_path)
    dataset = tmp_path / "dataset.csv"
    _escribir_csv(dataset, [_fila_csv()])

    revalidar_origen_por_eliminacion_categoria_sin_ocr(ruta_dataset=dataset, carpeta_catalogos=carpeta)
    proveedor = _proveedor_sin_candidatos("CALLE DE UN CLIENTE 500 SANTIAGO, Chile")
    revalidar_ruta_sin_destino_calculado_sin_ocr(
        ruta_dataset=dataset, carpeta_catalogos=carpeta, proveedor_rutas=proveedor,
    )

    fila = _leer(dataset)[0]
    assert fila["estado_ruta"] != "RUTA_CALCULADA"
    assert fila["distancia_km"] == ""
    assert fila["estado_operacional"] == "REQUIERE_REVISION", "nunca OK sin km/tiempo real"


def test_recuperacion_posterior_confirma_automaticamente(tmp_path):
    """Reintento con un proveedor que ahora SÍ resuelve -- sin tocar nada
    manualmente, sin Javier, sin OCR."""
    carpeta, colina, renca = _catalogos(tmp_path)
    dataset = tmp_path / "dataset.csv"
    _escribir_csv(dataset, [_fila_csv()])
    revalidar_origen_por_eliminacion_categoria_sin_ocr(ruta_dataset=dataset, carpeta_catalogos=carpeta)
    revalidar_ruta_sin_destino_calculado_sin_ocr(
        ruta_dataset=dataset, carpeta_catalogos=carpeta,
        proveedor_rutas=_proveedor_sin_candidatos("CALLE DE UN CLIENTE 500 SANTIAGO, Chile"),
    )
    assert _leer(dataset)[0]["estado_operacional"] == "REQUIERE_REVISION"

    revalidar_ruta_sin_destino_calculado_sin_ocr(
        ruta_dataset=dataset, carpeta_catalogos=carpeta,
        proveedor_rutas=_proveedor_exitoso("CALLE DE UN CLIENTE 500 SANTIAGO, Chile"),
    )

    fila = _leer(dataset)[0]
    assert fila["estado_ruta"] == "RUTA_CALCULADA"
    assert fila["estado_operacional"] == "OK"


# ============================================================
# 7/8/9 -- idempotencia, sin OCR, sin decisión humana ficticia
# ============================================================

def test_idempotente_no_reescribe_si_ya_esta_completo(tmp_path):
    carpeta, colina, renca = _catalogos(tmp_path)
    dataset = tmp_path / "dataset.csv"
    _escribir_csv(dataset, [_fila_csv()])
    revalidar_origen_por_eliminacion_categoria_sin_ocr(ruta_dataset=dataset, carpeta_catalogos=carpeta)
    revalidar_ruta_sin_destino_calculado_sin_ocr(
        ruta_dataset=dataset, carpeta_catalogos=carpeta,
        proveedor_rutas=_proveedor_exitoso("CALLE DE UN CLIENTE 500 SANTIAGO, Chile"),
    )

    r_origen_2 = revalidar_origen_por_eliminacion_categoria_sin_ocr(ruta_dataset=dataset, carpeta_catalogos=carpeta)
    r_ruta_2 = revalidar_ruta_sin_destino_calculado_sin_ocr(
        ruta_dataset=dataset, carpeta_catalogos=carpeta,
        proveedor_rutas=_proveedor_exitoso("CALLE DE UN CLIENTE 500 SANTIAGO, Chile"),
    )

    assert r_origen_2["guias_actualizadas"] == []
    assert r_ruta_2["guias_actualizadas"] == []  # ya RUTA_CALCULADA -- se salta por diseño


def test_ninguna_llamada_toca_ocr_ni_genera_decision_ficticia(tmp_path):
    """No hay ningún parámetro de imagen/OCR en ninguna de las dos
    funciones -- ambas operan exclusivamente sobre el CSV ya persistido.
    Tampoco crean ninguna decisión: sólo escriben columnas del dataset."""
    import inspect
    from atlas_core import decisiones_pendientes as dp

    firma_origen = inspect.signature(revalidar_origen_por_eliminacion_categoria_sin_ocr)
    firma_ruta = inspect.signature(revalidar_ruta_sin_destino_calculado_sin_ocr)
    for firma in (firma_origen, firma_ruta):
        assert "imagen" not in firma.parameters
        assert "ocr" not in " ".join(firma.parameters).lower()

    carpeta, colina, renca = _catalogos(tmp_path)
    dataset = tmp_path / "dataset.csv"
    _escribir_csv(dataset, [_fila_csv()])
    llamado = []
    original = dp.crear_decision
    dp.crear_decision = lambda *a, **k: (llamado.append(1), original(*a, **k))[1]
    try:
        revalidar_origen_por_eliminacion_categoria_sin_ocr(ruta_dataset=dataset, carpeta_catalogos=carpeta)
        revalidar_ruta_sin_destino_calculado_sin_ocr(
            ruta_dataset=dataset, carpeta_catalogos=carpeta,
            proveedor_rutas=_proveedor_exitoso("CALLE DE UN CLIENTE 500 SANTIAGO, Chile"),
        )
    finally:
        dp.crear_decision = original
    assert llamado == [], "ninguna de las dos funciones debe crear una decisión humana"
