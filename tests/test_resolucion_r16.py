"""Bloque RESOLUCIÓN R16 -- Atlas agota fuentes razonables ANTES de
rendirse ante `MULTIPLES_UBICACIONES_DISPERSAS`/`SIN_ACCESO_VIAL`, y la
restricción de país (Chile) se aplica también en la reconciliación
retroactiva -- no sólo en el procesamiento en vivo."""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import datetime, timezone

from atlas_core.catalogo_destinos import CatalogoDestinos, Destino, EstadoCalidadDestino
from atlas_core.catalogo_plantas import CatalogoPlantas, EstadoCalidad
from atlas_core.procesamiento_masivo import COLUMNAS, PAIS_OPERACION_PREDETERMINADO
from atlas_core.revalidacion_documental import revalidar_ruta_sin_destino_calculado_sin_ocr
from atlas_core.rutas.destino_entrega import (
    calcular_ruta_con_planta_conocida, resolver_destino_entrega,
)
from atlas_core.rutas.modelos import (
    CandidatoGeocodificacion, Coordenadas, EstadoRuta, ResultadoGeocodificacion, ResultadoRuta,
)
from atlas_core.rutas.proveedor import ProveedorRutasSimulado
from atlas_core.atlas_ia.registro_problemas import detectar_problemas_elegibles

COORD_AZA_COLINA = Coordenadas(-70.669, -33.201)
FECHA = datetime(2026, 1, 1, tzinfo=timezone.utc).isoformat()


def _candidato(lat, lon, etiqueta="Candidato", confianza=0.8, localidad="", region=""):
    return CandidatoGeocodificacion(Coordenadas(lon, lat), etiqueta, confianza, localidad, region)


def _destino_confirmado(direccion, lat=None, lon=None, *, estado_calidad="CONFIRMADO"):
    return Destino(
        destino_id="d-1", cliente_id="", nombre_destino=direccion,
        nombre_normalizado=direccion.upper(), codigo_destino="",
        direccion=direccion, comuna="", region="", pais="CHILE",
        latitud=lat, longitud=lon, aliases=(), estado_calidad=estado_calidad,
        estado_vigencia="ACTIVO", fuente="TEST", observacion="",
        fecha_creacion=FECHA, fecha_modificacion=FECHA,
    )


def _planta(tmp_path):
    plantas = CatalogoPlantas(tmp_path / "plantas.json")
    return plantas.crear(
        nombre="AZA COLINA", pais="CHILE", fuente="TEST",
        direccion="RUTA 5", comuna="COLINA", region="RM",
        latitud=COORD_AZA_COLINA.latitud, longitud=COORD_AZA_COLINA.longitud,
        estado_calidad=EstadoCalidad.CONFIRMADA,
    )


# ---------------------------------------------------------------------
# Parte D -- MULTIPLES_UBICACIONES_DISPERSAS ya no es un final
# automático cuando existe un destino CONFIRMADO que lo desambigua.
# ---------------------------------------------------------------------


def test_multiples_ubicaciones_dispersas_se_resuelve_con_destino_confirmado():
    """Caso real AUSIN SAN BERNARDO (460807/472008): dos candidatos
    dispersos, pero uno coincide con un destino ya CONFIRMADO -- Vía A
    (`resolver_destino_ambiguo_con_evidencia_inequivoca`, existente desde
    Bloque DESTINOS D1, nunca antes conectada aquí) debe resolverlo, sin
    adivinar."""
    proveedor = ProveedorRutasSimulado(geocodificaciones={
        "INTERIOR NUEVA 01148 SAN BERNARDO, Chile": ResultadoGeocodificacion(
            EstadoRuta.RESULTADO_AMBIGUO,
            (
                _candidato(-33.5928, -70.7053, "Interior Nueva 01148, San Bernardo"),
                _candidato(-38.15, -72.35, "Interior Nueva, Otra Comuna Lejana"),
            ),
            "MULTIPLES_CANDIDATOS",
        )
    })
    destinos_confirmados = (
        _destino_confirmado("INTERIOR NUEVA 01148 SAN BERNARDO", -33.5928, -70.7053),
    )
    resultado = resolver_destino_entrega(
        "INTERIOR NUEVA 01148 SAN BERNARDO", proveedor,
        destinos_confirmados=destinos_confirmados,
    )
    assert resultado.estado == "RESUELTO"
    assert resultado.coordenadas == Coordenadas(-70.7053, -33.5928)


def test_multiples_ubicaciones_dispersas_sin_destino_confirmado_sigue_en_revision():
    """Control -- sin ningún destino confirmado que la respalde, la
    ambigüedad real se preserva intacta (nunca se debilita la
    abstención)."""
    proveedor = ProveedorRutasSimulado(geocodificaciones={
        "CALLE X 100, Chile": ResultadoGeocodificacion(
            EstadoRuta.RESULTADO_AMBIGUO,
            (_candidato(-33.0, -70.0, "A"), _candidato(-38.0, -72.0, "B")),
            "MULTIPLES_CANDIDATOS",
        )
    })
    resultado = resolver_destino_entrega("CALLE X 100", proveedor)
    assert resultado.estado == "REVISAR"
    assert resultado.motivo.startswith("MULTIPLES_UBICACIONES_DISPERSAS")


# ---------------------------------------------------------------------
# Parte F -- SIN_ACCESO_VIAL intenta un punto CONFIRMADO distinto antes
# de rendirse, nunca inventa una coordenada nueva.
# ---------------------------------------------------------------------


@dataclass
class _ProveedorRutaPorDestino:
    """Doble de prueba: la respuesta de `calcular_ruta` depende del punto
    de DESTINO exacto -- permite simular que el centroide degradado no
    tiene acceso vial pero el punto confirmado por catálogo sí."""

    geocodificaciones: dict[str, ResultadoGeocodificacion]
    respuestas_por_destino: dict[tuple[float, float], ResultadoRuta]
    respuesta_defecto: ResultadoRuta
    nombre: str = "simulado_condicional"
    version: str = "1"

    def geocodificar(self, direccion: str) -> ResultadoGeocodificacion:
        return self.geocodificaciones[direccion]

    def calcular_ruta(self, origen: Coordenadas, destino: Coordenadas, perfil: str) -> ResultadoRuta:
        clave = (round(destino.longitud, 4), round(destino.latitud, 4))
        return self.respuestas_por_destino.get(clave, self.respuesta_defecto)


def test_sin_acceso_vial_se_recupera_con_destino_confirmado_distinto(tmp_path):
    """Caso real 472044/472073/472163: el geocodificador sólo resolvió un
    centroide de comuna (sin acceso vial); un destino ya CONFIRMADO para
    la misma dirección, con OTRA coordenada (calle real, no centroide),
    sí tiene acceso -- se reintenta con esa evidencia real, nunca con una
    coordenada inventada."""
    planta = _planta(tmp_path)
    centroide = Coordenadas(-70.5, -33.4)
    punto_confirmado = Coordenadas(-70.55, -33.42)
    proveedor = _ProveedorRutaPorDestino(
        geocodificaciones={
            "PUERTA DEL SOL 83 LAS CONDES, Chile": ResultadoGeocodificacion(
                EstadoRuta.REQUIERE_REVISION,
                (CandidatoGeocodificacion(centroide, "Las Condes, RM, Chile", 0.6, "Las Condes", "Metropolitana"),),
                "RESUELTO",
            )
        },
        respuestas_por_destino={
            (round(centroide.longitud, 4), round(centroide.latitud, 4)):
                ResultadoRuta(EstadoRuta.SIN_ACCESO_VIAL, motivo="SIN_ACCESO_VIAL"),
            (round(punto_confirmado.longitud, 4), round(punto_confirmado.latitud, 4)):
                ResultadoRuta(EstadoRuta.RUTA_CALCULADA, 12.0, 20.0, "SINTETICO"),
        },
        respuesta_defecto=ResultadoRuta(EstadoRuta.SIN_ACCESO_VIAL, motivo="SIN_ACCESO_VIAL"),
    )
    destinos_confirmados = (
        _destino_confirmado(
            "PUERTA DEL SOL 83 LAS CONDES", punto_confirmado.latitud, punto_confirmado.longitud,
        ),
    )
    resultado = calcular_ruta_con_planta_conocida(
        planta=planta, despachar_a_crudo="PUERTA DEL SOL 83 LAS CONDES", proveedor_rutas=proveedor,
        destinos_confirmados=destinos_confirmados,
    )
    assert resultado.estado_ruta == EstadoRuta.RUTA_CALCULADA.value
    assert resultado.distancia_km == "12.0"
    assert resultado.metodo_confirmacion_destino == "CATALOGO_CONFIRMADO_SIN_ACCESO_VIAL"


def test_sin_acceso_vial_sin_destino_confirmado_se_conserva(tmp_path):
    """Control -- sin ningún destino confirmado que aporte otro punto,
    `SIN_ACCESO_VIAL` se conserva con su causa explícita, nunca se
    inventa un snap vial."""
    planta = _planta(tmp_path)
    centroide = Coordenadas(-70.5, -33.4)
    proveedor = _ProveedorRutaPorDestino(
        geocodificaciones={
            "PUERTA DEL SOL 83 LAS CONDES, Chile": ResultadoGeocodificacion(
                EstadoRuta.REQUIERE_REVISION,
                (CandidatoGeocodificacion(centroide, "Las Condes, RM, Chile", 0.6, "Las Condes", "Metropolitana"),),
                "RESUELTO",
            )
        },
        respuestas_por_destino={},
        respuesta_defecto=ResultadoRuta(EstadoRuta.SIN_ACCESO_VIAL, motivo="SIN_ACCESO_VIAL"),
    )
    resultado = calcular_ruta_con_planta_conocida(
        planta=planta, despachar_a_crudo="PUERTA DEL SOL 83 LAS CONDES", proveedor_rutas=proveedor,
    )
    assert resultado.estado_ruta == EstadoRuta.SIN_ACCESO_VIAL.value
    assert resultado.motivo_ruta == "SIN_ACCESO_VIAL"


# ---------------------------------------------------------------------
# Parte B/E -- restricción de país Chile también en la reconciliación
# retroactiva (causa raíz real del caso 472037: Córdoba, Argentina).
# ---------------------------------------------------------------------


def test_revalidacion_retroactiva_construye_proveedor_restringido_a_chile(tmp_path, monkeypatch):
    capturado = {}

    class _OpenRouteServiceEspia:
        def __init__(self, *, pais=None, **kwargs):
            capturado["pais"] = pais

        nombre = "openrouteservice"
        version = "1"

        def geocodificar(self, direccion):
            return ResultadoGeocodificacion(EstadoRuta.SIN_CREDENCIAL)

        def calcular_ruta(self, origen, destino, perfil):
            return ResultadoRuta(EstadoRuta.SIN_CREDENCIAL)

    import atlas_core.rutas.openrouteservice as mod_ors
    monkeypatch.setattr(mod_ors, "OpenRouteService", _OpenRouteServiceEspia)

    carpeta = tmp_path / "catalogos"; carpeta.mkdir()
    planta = CatalogoPlantas(carpeta / "plantas.json").crear(
        nombre="AZA COLINA", pais="CHILE", fuente="TEST",
        direccion="RUTA 5", comuna="COLINA", region="RM",
        latitud=COORD_AZA_COLINA.latitud, longitud=COORD_AZA_COLINA.longitud,
        estado_calidad=EstadoCalidad.CONFIRMADA,
    )
    dataset = tmp_path / "dataset.csv"
    fila = {c: "" for c in COLUMNAS}
    fila.update({
        "archivo": "1.jpeg", "estado_procesamiento": "OK", "numero_guia": "1",
        "numero_transporte": "T1", "fecha": "22/08/2026",
        "despachar_a_crudo": "CALLE X 100",
        "planta_origen_id": planta.planta_id, "planta_origen_nombre": planta.nombre,
        "estado_ruta": "SIN_CREDENCIAL", "motivo_ruta": "SIN_CREDENCIAL",
    })
    with dataset.open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";")
        escritor.writeheader(); escritor.writerow(fila)

    revalidar_ruta_sin_destino_calculado_sin_ocr(ruta_dataset=dataset, carpeta_catalogos=carpeta)
    assert capturado["pais"] == PAIS_OPERACION_PREDETERMINADO == "CL"


# ---------------------------------------------------------------------
# Parte H -- GEOCODIFICACION_FUERA_DE_CHILE es elegible para B1 (nunca
# NO_ELEGIBLE_IA sólo porque el geocodificador inicial se equivocó).
# ---------------------------------------------------------------------


def test_geocodificacion_fuera_de_chile_es_elegible_para_b1():
    fila = {"motivo_ruta": "GEOCODIFICACION_FUERA_DE_CHILE: Cordoba", "motivos_revision_documento": "", "motivo_origen_gps": ""}
    encontrados = detectar_problemas_elegibles(fila)
    dominios = {tipo.dominio for tipo, _codigo in encontrados}
    assert "DESTINO" in dominios


# ---------------------------------------------------------------------
# Catálogo -- confirmar una dirección ya existente la PROMUEVE (nunca la
# deja PENDIENTE para siempre) y completa coordenadas ausentes sin
# sobrescribir unas ya presentes.
# ---------------------------------------------------------------------


def test_crear_o_reutilizar_global_promueve_pendiente_a_confirmado(tmp_path):
    catalogo = CatalogoDestinos(tmp_path / "destinos.json", ruta_clientes=tmp_path / "clientes.json")
    pendiente = catalogo.crear(
        cliente_id="", nombre_destino="CALLE X 100", direccion="CALLE X 100",
        pais="CHILE", fuente="TEST",
    )
    assert pendiente.estado_calidad == "PENDIENTE"
    confirmado = catalogo.crear_o_reutilizar_global(
        nombre_destino="CALLE X 100", direccion="CALLE X 100", fuente="TEST2",
        latitud=-33.4, longitud=-70.6, estado_calidad=EstadoCalidadDestino.CONFIRMADO,
    )
    assert confirmado.destino_id == pendiente.destino_id
    assert confirmado.estado_calidad == "CONFIRMADO"
    assert confirmado.latitud == -33.4 and confirmado.longitud == -70.6


def test_crear_o_reutilizar_global_nunca_sobrescribe_coordenadas_existentes(tmp_path):
    catalogo = CatalogoDestinos(tmp_path / "destinos.json", ruta_clientes=tmp_path / "clientes.json")
    original = catalogo.crear(
        cliente_id="", nombre_destino="CALLE X 100", direccion="CALLE X 100",
        pais="CHILE", fuente="TEST", latitud=-33.1, longitud=-70.1,
        estado_calidad=EstadoCalidadDestino.CONFIRMADO,
    )
    reutilizado = catalogo.crear_o_reutilizar_global(
        nombre_destino="CALLE X 100", direccion="CALLE X 100", fuente="TEST2",
        latitud=-99.0, longitud=-99.0, estado_calidad=EstadoCalidadDestino.CONFIRMADO,
    )
    assert reutilizado.destino_id == original.destino_id
    assert reutilizado.latitud == -33.1 and reutilizado.longitud == -70.1
