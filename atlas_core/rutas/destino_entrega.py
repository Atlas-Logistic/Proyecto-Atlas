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
from typing import Any, Iterable

from atlas_core.catalogo_plantas import Planta
from atlas_core.extractor import (
    _despachar_a_lineal_contaminado,
    _extraer_despachar_a_geometrico,
)
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


def _texto_normalizado_sin_acentos(texto: str) -> str:
    import unicodedata

    normalizado = unicodedata.normalize("NFD", str(texto or "").upper())
    return "".join(c for c in normalizado if unicodedata.category(c) != "Mn")


def _misma_localidad(a: CandidatoGeocodificacion, b: CandidatoGeocodificacion) -> bool:
    """True si ambos candidatos declaran la MISMA localidad+región (Pelias
    ya los nombró igual) -- caso real Coronel/Biobío: dos candidatos del
    mismo lugar real a ~2 km entre sí (fuera del margen de distancia de
    `_candidatos_son_el_mismo_lugar`, que asume variación de número de
    casa, no de localidad completa). Nunca compara localidades distintas
    por cercanía -- solo por igualdad textual exacta (sin acentos/mayúsculas)."""
    localidad_a = _texto_normalizado_sin_acentos(a.localidad)
    localidad_b = _texto_normalizado_sin_acentos(b.localidad)
    region_a = _texto_normalizado_sin_acentos(a.region)
    region_b = _texto_normalizado_sin_acentos(b.region)
    if not localidad_a or not region_a or not localidad_b or not region_b:
        return False
    return localidad_a == localidad_b and region_a == region_b


def _candidatos_son_el_mismo_lugar(candidatos: tuple[CandidatoGeocodificacion, ...]) -> bool:
    """True si TODOS los candidatos caen dentro de `MARGEN_MISMO_LUGAR_KM`
    del primero (variación de número de casa) O TODOS declaran la misma
    localidad+región exacta (Bloque E2E R1.1 -- ver `_misma_localidad`,
    caso real Coronel/Biobío) -- en cualquier caso, el mismo lugar real,
    no ubicaciones distintas."""
    if len(candidatos) <= 1:
        return True
    base = candidatos[0]
    if all(
        distancia_km_haversine(base.coordenadas, c.coordenadas) <= MARGEN_MISMO_LUGAR_KM
        for c in candidatos[1:]
    ):
        return True
    return all(_misma_localidad(base, c) for c in candidatos[1:])


def _candidatos_con_soporte_textual(
    candidatos: tuple[CandidatoGeocodificacion, ...], texto_original: str,
) -> tuple[CandidatoGeocodificacion, ...]:
    """Bloque E2E R1.1 -- descarta candidatos cuya localidad/región
    declarada NO aparece mencionada en ningún lugar del propio DESPACHAR A
    (p. ej. "Ránquil" cuando el documento dice "...CORONEL" -- Pelias
    ofrece un vecino administrativo sin ningún respaldo textual). Nunca
    reduce a una lista vacía: si NINGÚN candidato tiene respaldo textual
    (p. ej. Pelias no devolvió localidad/región en ninguno), se conservan
    todos -- este filtro solo AYUDA a desambiguar, nunca fabrica evidencia
    donde no la hay. Funciona para cualquier localidad/región (RM,
    Coronel, Temuco, Mejillones, ...), no compara contra una lista fija de
    nombres chilenos."""
    texto_normalizado = _texto_normalizado_sin_acentos(texto_original)

    def _tiene_soporte(candidato: CandidatoGeocodificacion) -> bool:
        for campo in (candidato.localidad, candidato.region):
            for palabra in _texto_normalizado_sin_acentos(campo).split():
                if len(palabra) >= 4 and palabra in texto_normalizado:
                    return True
        return False

    con_soporte = tuple(c for c in candidatos if _tiene_soporte(c))
    return con_soporte if con_soporte else candidatos


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
        # Bloque E2E R1.1 -- antes de decidir si hay ambigüedad real,
        # descarta candidatos sin ningún respaldo textual en el propio
        # DESPACHAR A (p. ej. "Ránquil" cuando el documento dice
        # "...CORONEL"). Nunca inventa evidencia: si ninguno tiene
        # respaldo, sigue con el conjunto completo (comportamiento
        # idéntico al de antes de este bloque).
        candidatos_relevantes = _candidatos_con_soporte_textual(resultado.candidatos, texto)
        if _candidatos_son_el_mismo_lugar(candidatos_relevantes):
            # Varios candidatos, pero todos caen dentro de
            # MARGEN_MISMO_LUGAR_KM entre sí, o todos declaran la misma
            # localidad+región -- p. ej. Pelias no pudo calzar el número
            # de casa exacto y devolvió vecinos de la misma cuadra/zona.
            # No es la ambigüedad de calles homónimas que la regla de
            # negocio pide evitar (ver docstring del módulo) -- se usa el
            # candidato de mayor confianza.
            candidato = _mejor_candidato(candidatos_relevantes)
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
    bloques: Iterable[Any] | None = None,
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
    conecta un proveedor real o ninguno.

    `bloques` (Bloque E2E R1.1, opcional -- coordenadas OCR de la misma
    imagen): la extracción lineal de DESPACHAR A (regex sobre texto ya
    unido en una sola línea) puede absorber la etiqueta/valor de OTRO
    campo estructural cuando PaddleOCR intercala columnas en su orden de
    lectura (caso real guía 463594: "DESPACHAR A" quedó seguido, en el
    texto lineal, por "PATENTE : BDFG50"). Si el valor lineal está vacío o
    contaminado (ver `_despachar_a_lineal_contaminado`) y se entregan
    `bloques`, se reintenta por posición real en la imagen
    (`_extraer_despachar_a_geometrico`) -- nunca por el orden de lectura."""
    textos = list(textos)
    identificadores = extraer_identificadores_destino(textos)
    despachar_a_crudo = (identificadores.despachar_a or "").strip()

    if bloques is not None and (
        not despachar_a_crudo or _despachar_a_lineal_contaminado(despachar_a_crudo)
    ):
        try:
            decision_geometrica = _extraer_despachar_a_geometrico(list(bloques))
        except Exception:
            decision_geometrica = {}
        candidato_geometrico = str(decision_geometrica.get("valor") or "").strip()
        if candidato_geometrico and not _despachar_a_lineal_contaminado(candidato_geometrico):
            despachar_a_crudo = candidato_geometrico

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
