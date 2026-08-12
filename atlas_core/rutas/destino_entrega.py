"""Resolución de DESTINO DE ENTREGA (Bloque ENTREGAS E1).

Regla de negocio operacional (definida por Javier, **prevalece sobre
inferencias anteriores de D2/D3/D3.1**): `DESPACHAR A` es la fuente
PRINCIPAL y AUTORITATIVA del destino geográfico de la ruta. La ruta debe
ser:

    PLANTA ORIGEN -> DESPACHAR A

nunca:

    PLANTA ORIGEN -> dirección del cliente/sitio registrado

aunque ese sitio esté "confirmado" como identidad comercial en
`destinos_maestros.json` (Bloque D2/D3: `DIRECCION`/`COMUNA`/
`COD DESTINATARIO` identifican el sitio/obra **registrado** contra el
que se emite la guía -- útil para clasificación/recurrencia, nunca como
reemplazo del punto de entrega real).

Auditoría real del bloque E1 (14 guías, 11 lecturas usables de `COMUNA`
+ `DESPACHAR A`): el campo `COMUNA` del formulario **coincide** con la
comuna real de entrega solo quando la entrega cae dentro de la misma
comuna/región que el sitio registrado (~8/11 casos, incluida coincidencia
casual en 2 casos donde la calle exacta de `DESPACHAR A` difiere de
`DIRECCION` pero la comuna sí coincide) -- pero en los 3 casos de entrega
interregional observados (464170: Mejillones/Antofagasta; 464264-465:
Coronel/Biobío; 464367: aparente Ñuble), `COMUNA` siguió mostrando la
comuna RM del sitio registrado, **no** la comuna real de entrega. Por
tanto este módulo **nunca** reutiliza `COMUNA` para geocodificar
`DESPACHAR A` -- geocodifica el texto crudo de `DESPACHAR A` tal cual,
dejando que el proveedor de geocodificación (contexto territorial real,
Chile) determine la localidad.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Iterable

from atlas_core.catalogo_plantas import Planta
from atlas_core.rutas.destino_estructurado import extraer_identificadores_destino
from atlas_core.rutas.geocerca import RADIO_GEOCERCA_KM_PREDETERMINADO, distancia_km_haversine
from atlas_core.rutas.modelos import CandidatoGeocodificacion, Coordenadas, EstadoRuta
from atlas_core.rutas.posicion_vehiculo import ProveedorPosicionVehiculo
from atlas_core.rutas.proveedor import ProveedorRutas

# Confianza mínima (score de Pelias/ORS, 0-1) para aceptar un único
# candidato sin ambigüedad como resuelto. Por debajo de este umbral, o
# sin score informado, se marca REVISAR igual que si hubiera múltiples
# candidatos -- ante duda, abstención, nunca "el más cercano a AZA".
UMBRAL_CONFIANZA_MINIMA = 0.5

# Radio dentro del cual varios candidatos de geocodificación se
# consideran "el mismo lugar real" (p. ej. números de casa vecinos sobre
# la misma calle que Pelias no pudo calzar exacto) en vez de una
# ambigüedad genuina de ubicación. Calibrado con evidencia real (Bloque
# E1): 5 candidatos de "AV. ALMTE. LATORRE 843, MEJILLONES" cayeron
# dentro de ~350 m entre sí (misma cuadra, mismo lado de calle) -- eso
# NO es la ambigüedad que la regla de negocio pide evitar. La ambigüedad
# real a evitar es la de calles homónimas entre comunas/regiones/países
# (p. ej. "SANTA ISABEL 585" devolvió resultados en Perú, Argentina,
# Puerto Rico y DOS puntos distintos dentro de Lampa, RM) -- eso sigue
# marcándose REVISAR sin excepción.
MARGEN_MISMO_LUGAR_KM = 1.0

ESTADO_RESUELTO = "RESUELTO"
ESTADO_REVISAR = "REVISAR"
ESTADO_SIN_DATO = "SIN_DATO"


@dataclass(frozen=True)
class ResultadoDestinoEntrega:
    """Resultado de resolver el punto real de entrega de un viaje.

    `despachar_a_crudo` se preserva siempre tal como aparece en el
    documento -- nunca se descarta, incluso si la geocodificación falla o
    queda en revisión, para no perder la evidencia original.
    """

    despachar_a_crudo: str = ""
    coordenadas: Coordenadas | None = None
    etiqueta_geocodificada: str = ""
    confianza: float | None = None
    estado: str = ESTADO_SIN_DATO
    motivo: str = ""
    # Bloque E2E R1: localidad/región tal como las devuelve el
    # geocodificador (Pelias) para el candidato aceptado -- nunca
    # derivadas de `DIRECCION`/`COMUNA` del sitio registrado (ver regla de
    # negocio del módulo). Vacías si el candidato no las trae o si no hubo
    # candidato aceptado.
    localidad: str = ""
    region: str = ""

    def a_dict(self) -> dict[str, str]:
        return {
            "despachar_a_crudo": self.despachar_a_crudo,
            "longitud_entrega": str(self.coordenadas.longitud) if self.coordenadas else "",
            "latitud_entrega": str(self.coordenadas.latitud) if self.coordenadas else "",
            "etiqueta_geocodificada": self.etiqueta_geocodificada,
            "confianza_geocodificacion": str(self.confianza) if self.confianza is not None else "",
            "estado_destino_entrega": self.estado,
            "motivo_destino_entrega": self.motivo,
            "localidad_entrega": self.localidad,
            "region_entrega": self.region,
        }


def _candidatos_son_el_mismo_lugar(candidatos: tuple[CandidatoGeocodificacion, ...]) -> bool:
    """True si TODOS los candidatos caen dentro de `MARGEN_MISMO_LUGAR_KM`
    del primero -- es decir, representan el mismo lugar real con
    variación de número de casa, no ubicaciones distintas."""
    if len(candidatos) <= 1:
        return True
    base = candidatos[0].coordenadas
    return all(
        distancia_km_haversine(base, c.coordenadas) <= MARGEN_MISMO_LUGAR_KM
        for c in candidatos[1:]
    )


def _mejor_candidato(candidatos: tuple[CandidatoGeocodificacion, ...]) -> CandidatoGeocodificacion:
    """Entre candidatos que ya se determinó que son el mismo lugar real,
    el de mayor confianza informada (nunca el más cercano a ninguna
    referencia externa como una planta AZA)."""
    return max(candidatos, key=lambda c: c.confianza if c.confianza is not None else -1.0)


def resolver_destino_entrega(
    despachar_a_crudo: str | None,
    proveedor_geocodificacion: ProveedorRutas,
    *,
    contexto_territorial: str = "Chile",
) -> ResultadoDestinoEntrega:
    """Geocodifica `DESPACHAR A` -- nunca `DIRECCION`/`COMUNA` del cliente.

    Nunca elige el candidato más cercano a una planta AZA ni a ninguna
    otra referencia -- eso violaría la regla de negocio ("nunca escoger
    una ubicación porque esté más cerca de AZA"). Ante más de un
    candidato, o un único candidato sin confianza suficiente, se
    abstiene (`REVISAR`) en vez de adivinar.
    """
    texto = str(despachar_a_crudo or "").strip()
    if not texto:
        return ResultadoDestinoEntrega(
            despachar_a_crudo="", estado=ESTADO_SIN_DATO, motivo="DESPACHAR_A_NO_INFORMADO"
        )

    consulta = f"{texto}, {contexto_territorial}" if contexto_territorial else texto
    resultado = proveedor_geocodificacion.geocodificar(consulta)

    if resultado.estado == EstadoRuta.RESULTADO_AMBIGUO:
        if _candidatos_son_el_mismo_lugar(resultado.candidatos):
            # Varios candidatos, pero todos caen dentro de
            # MARGEN_MISMO_LUGAR_KM entre sí -- p. ej. Pelias no pudo
            # calzar el número de casa exacto y devolvió vecinos de la
            # misma cuadra. No es la ambigüedad de calles homónimas que
            # la regla de negocio pide evitar (ver docstring del
            # módulo) -- se usa el candidato de mayor confianza.
            candidato = _mejor_candidato(resultado.candidatos)
        else:
            return ResultadoDestinoEntrega(
                despachar_a_crudo=texto, estado=ESTADO_REVISAR,
                motivo=f"MULTIPLES_UBICACIONES_DISPERSAS({len(resultado.candidatos)})",
            )
    elif resultado.estado != EstadoRuta.REQUIERE_REVISION or not resultado.candidatos:
        # Cualquier otro estado (SIN_CREDENCIAL, SIN_CONEXION,
        # DIRECCION_NO_ENCONTRADA, LIMITE_CUOTA, PROVEEDOR_NO_DISPONIBLE,
        # RESPUESTA_INVALIDA, ...) es un fallo de geocodificación, no una
        # decisión de destino -- se preserva el texto crudo y se explica.
        return ResultadoDestinoEntrega(
            despachar_a_crudo=texto, estado=ESTADO_REVISAR,
            motivo=f"GEOCODIFICACION_{resultado.estado.value}",
        )
    else:
        # Un único candidato (REQUIERE_REVISION): sigue exigiendo
        # confianza suficiente antes de darlo por resuelto -- ver abajo.
        candidato = resultado.candidatos[0]

    if candidato.confianza is None or candidato.confianza < UMBRAL_CONFIANZA_MINIMA:
        return ResultadoDestinoEntrega(
            despachar_a_crudo=texto,
            coordenadas=candidato.coordenadas,
            etiqueta_geocodificada=candidato.etiqueta,
            confianza=candidato.confianza,
            estado=ESTADO_REVISAR,
            motivo="CONFIANZA_INSUFICIENTE",
            localidad=candidato.localidad,
            region=candidato.region,
        )
    return ResultadoDestinoEntrega(
        despachar_a_crudo=texto,
        coordenadas=candidato.coordenadas,
        etiqueta_geocodificada=candidato.etiqueta,
        confianza=candidato.confianza,
        estado=ESTADO_RESUELTO,
        motivo="",
        localidad=candidato.localidad,
        region=candidato.region,
    )


CAMPOS_RESULTADO_RUTA_ENTREGA = (
    "planta_origen_id", "planta_origen_nombre",
    "despachar_a_crudo", "direccion_entrega_geocodificada",
    "localidad_entrega", "region_entrega",
    "longitud_entrega", "latitud_entrega", "confianza_geocodificacion",
    "distancia_km", "duracion_min",
    "proveedor_ruta", "estado_ruta", "motivo_ruta",
    "origen_determinado_por", "evidencia_origen",
)


@dataclass(frozen=True)
class ResultadoRutaEntrega:
    """Resultado de una ruta PLANTA ORIGEN -> DESPACHAR A (Bloque E1).

    Deliberadamente sin campos de `destino_id`/`destino_nombre` de
    catálogo: la entrega no es (todavía) una entidad de catálogo, es un
    punto geocodificado en vivo a partir del propio documento -- ver
    Fase E del bloque E1 (propuesta de modelo `destino_entrega`, no
    implementada). Sin caché propia por el mismo motivo (no hay una
    clave de catálogo estable que cachear contra ella todavía).
    """

    planta_origen_id: str = ""
    planta_origen_nombre: str = ""
    despachar_a_crudo: str = ""
    direccion_entrega_geocodificada: str = ""
    localidad_entrega: str = ""
    region_entrega: str = ""
    longitud_entrega: str = ""
    latitud_entrega: str = ""
    confianza_geocodificacion: str = ""
    distancia_km: str = ""
    duracion_min: str = ""
    proveedor_ruta: str = ""
    estado_ruta: str = ""
    motivo_ruta: str = ""
    origen_determinado_por: str = ""
    evidencia_origen: str = ""

    def a_dict(self) -> dict[str, str]:
        return asdict(self)


def calcular_ruta_entrega_para_viaje(
    *,
    despachar_a_crudo: str,
    patente: str | None,
    instante_salida: datetime | None,
    plantas: Iterable[Planta],
    proveedor_posicion: ProveedorPosicionVehiculo | None,
    proveedor_rutas: ProveedorRutas,
    textos_documento: Iterable[str] | None = None,
    perfil: str = "driving-hgv",
    radio_geocerca_km: float = RADIO_GEOCERCA_KM_PREDETERMINADO,
) -> ResultadoRutaEntrega:
    """Orquesta PLANTA ORIGEN -> DESPACHAR A (Bloque E1). Nunca usa
    `DIRECCION`/`COMUNA`/`COD DESTINATARIO` del cliente como destino de
    ruta -- ver regla de negocio en el docstring del módulo. Un fallo en
    cualquier paso deja campos vacíos y un estado/motivo explicativo --
    nunca lanza, nunca inventa, nunca elige el candidato más cercano a
    una planta AZA."""
    # Import perezoso: evita un ciclo de import a nivel de módulo con
    # enriquecimiento_viaje (que a su vez importa este módulo de forma
    # perezosa dentro de `calcular_ruta_para_viaje` -- ver Bloque D2).
    from atlas_core.rutas.enriquecimiento_viaje import resolver_planta_origen

    plantas = list(plantas)

    planta, motivo_origen, determinado_por, evidencia_origen = resolver_planta_origen(
        patente=patente, instante_salida=instante_salida,
        proveedor_posicion=proveedor_posicion, plantas=plantas,
        textos_documento=textos_documento, radio_km=radio_geocerca_km,
    )
    if planta is None:
        return ResultadoRutaEntrega(
            estado_ruta=EstadoRuta.ORIGEN_NO_DETERMINADO.value, motivo_ruta=motivo_origen,
        )
    if planta.latitud is None or planta.longitud is None:
        return ResultadoRutaEntrega(
            estado_ruta=EstadoRuta.ORIGEN_NO_DETERMINADO.value,
            motivo_ruta="PLANTA_SIN_COORDENADAS_EN_CATALOGO",
        )

    entrega = resolver_destino_entrega(despachar_a_crudo, proveedor_rutas)
    if entrega.estado != ESTADO_RESUELTO:
        # Se conserva toda la evidencia parcial ya obtenida (etiqueta,
        # coordenadas, localidad/región, confianza) aunque la geocodificación
        # no haya quedado lo bastante segura para calcular ruta -- Fase J
        # (observabilidad): un motivo explícito sin evidencia no basta para
        # que una persona revise el caso.
        return ResultadoRutaEntrega(
            planta_origen_id=planta.planta_id, planta_origen_nombre=planta.nombre,
            despachar_a_crudo=entrega.despachar_a_crudo,
            direccion_entrega_geocodificada=entrega.etiqueta_geocodificada,
            localidad_entrega=entrega.localidad, region_entrega=entrega.region,
            longitud_entrega=str(entrega.coordenadas.longitud) if entrega.coordenadas else "",
            latitud_entrega=str(entrega.coordenadas.latitud) if entrega.coordenadas else "",
            confianza_geocodificacion=str(entrega.confianza) if entrega.confianza is not None else "",
            estado_ruta=EstadoRuta.REQUIERE_REVISION.value, motivo_ruta=entrega.motivo,
            origen_determinado_por=determinado_por, evidencia_origen=evidencia_origen,
        )

    ruta = proveedor_rutas.calcular_ruta(
        Coordenadas(planta.longitud, planta.latitud), entrega.coordenadas, perfil
    )
    if ruta.estado != EstadoRuta.RUTA_CALCULADA:
        return ResultadoRutaEntrega(
            planta_origen_id=planta.planta_id, planta_origen_nombre=planta.nombre,
            despachar_a_crudo=entrega.despachar_a_crudo,
            direccion_entrega_geocodificada=entrega.etiqueta_geocodificada,
            localidad_entrega=entrega.localidad, region_entrega=entrega.region,
            longitud_entrega=str(entrega.coordenadas.longitud),
            latitud_entrega=str(entrega.coordenadas.latitud),
            confianza_geocodificacion=str(entrega.confianza) if entrega.confianza is not None else "",
            estado_ruta=ruta.estado.value, motivo_ruta=ruta.motivo,
            origen_determinado_por=determinado_por, evidencia_origen=evidencia_origen,
        )
    return ResultadoRutaEntrega(
        planta_origen_id=planta.planta_id, planta_origen_nombre=planta.nombre,
        despachar_a_crudo=entrega.despachar_a_crudo,
        direccion_entrega_geocodificada=entrega.etiqueta_geocodificada,
        localidad_entrega=entrega.localidad, region_entrega=entrega.region,
        longitud_entrega=str(entrega.coordenadas.longitud),
        latitud_entrega=str(entrega.coordenadas.latitud),
        confianza_geocodificacion=str(entrega.confianza) if entrega.confianza is not None else "",
        distancia_km=str(ruta.distancia_km), duracion_min=str(ruta.duracion_estimada_min),
        proveedor_ruta=proveedor_rutas.nombre,
        estado_ruta=ruta.estado.value, motivo_ruta="",
        origen_determinado_por=determinado_por, evidencia_origen=evidencia_origen,
    )


CAMPOS_ENTREGA_DOCUMENTO = (
    "despachar_a_crudo", "direccion_entrega", "localidad_entrega",
    "region_entrega", "estado_entrega",
    "planta_origen_id", "planta_origen_nombre",
    "origen_determinado_por", "evidencia_origen",
    "distancia_km", "duracion_min", "proveedor_ruta",
    "estado_ruta", "motivo_ruta",
)


def resolver_entrega_documento(
    textos: Iterable[str],
    plantas: Iterable[Planta],
    proveedor_rutas: ProveedorRutas | None,
    *,
    perfil: str = "driving-hgv",
) -> dict[str, str]:
    """Orquesta, para UN documento (Bloque E2E R1), lo que hace falta
    persistir por cada guía nueva: `DESPACHAR A` crudo (siempre -- lectura
    local del propio texto OCR, sin red), planta de origen documental, y --
    solo si ambos existen -- geocodificación de `DESPACHAR A` + ruta ORS
    `driving-hgv` (reutiliza `calcular_ruta_entrega_para_viaje`, que ya
    nunca geocodifica si la planta no se determinó -- ver
    `test_origen_no_determinado_nunca_geocodifica`).

    Nunca bloquea el documento: cualquier fallo deja campos vacíos con un
    `estado_ruta`/`motivo_ruta` explicativo en vez de lanzar.
    `proveedor_rutas=None` dejar todo el enriquecimiento de ruta vacío
    (`estado_entrega=SIN_PROVEEDOR_RUTAS` si había `DESPACHAR A` que
    intentar) -- este módulo nunca decide qué proveedor de rutas usar por
    defecto (ver Bloque N, límites multiempresa); quien llama decide si
    conecta un proveedor real o ninguno."""
    textos = list(textos)
    identificadores = extraer_identificadores_destino(textos)
    despachar_a_crudo = (identificadores.despachar_a or "").strip()

    resultado = {campo: "" for campo in CAMPOS_ENTREGA_DOCUMENTO}
    resultado["despachar_a_crudo"] = despachar_a_crudo
    resultado["estado_entrega"] = "SIN_DATO" if not despachar_a_crudo else "NO_INTENTADO"

    plantas = list(plantas)
    from atlas_core.rutas.enriquecimiento_viaje import resolver_planta_origen

    planta, motivo_origen, determinado_por, evidencia_origen = resolver_planta_origen(
        patente=None, instante_salida=None, proveedor_posicion=None,
        plantas=plantas, textos_documento=textos,
    )
    if planta is None:
        resultado["estado_ruta"] = EstadoRuta.ORIGEN_NO_DETERMINADO.value
        resultado["motivo_ruta"] = motivo_origen
        return resultado

    resultado["planta_origen_id"] = planta.planta_id
    resultado["planta_origen_nombre"] = planta.nombre
    resultado["origen_determinado_por"] = determinado_por
    resultado["evidencia_origen"] = evidencia_origen

    if not despachar_a_crudo:
        return resultado
    if proveedor_rutas is None:
        resultado["estado_entrega"] = "SIN_PROVEEDOR_RUTAS"
        return resultado

    ruta_entrega = calcular_ruta_entrega_para_viaje(
        despachar_a_crudo=despachar_a_crudo,
        patente=None, instante_salida=None, plantas=plantas,
        proveedor_posicion=None, proveedor_rutas=proveedor_rutas,
        textos_documento=textos, perfil=perfil,
    )
    resultado["direccion_entrega"] = ruta_entrega.direccion_entrega_geocodificada
    resultado["localidad_entrega"] = ruta_entrega.localidad_entrega
    resultado["region_entrega"] = ruta_entrega.region_entrega
    resultado["distancia_km"] = ruta_entrega.distancia_km
    resultado["duracion_min"] = ruta_entrega.duracion_min
    resultado["proveedor_ruta"] = ruta_entrega.proveedor_ruta
    resultado["estado_ruta"] = ruta_entrega.estado_ruta
    resultado["motivo_ruta"] = ruta_entrega.motivo_ruta
    resultado["estado_entrega"] = (
        "RESUELTO" if ruta_entrega.direccion_entrega_geocodificada else "REVISAR"
    )
    return resultado
