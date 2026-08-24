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

import re

from dataclasses import asdict, dataclass, replace
from datetime import datetime
from typing import Any, Iterable

from atlas_core.catalogo_destinos import Destino
from atlas_core.catalogo_plantas import Planta
from atlas_core.extractor import (
    _despachar_a_lineal_contaminado,
    _extraer_despachar_a_geometrico,
)
from atlas_core.rutas.destino_estructurado import extraer_identificadores_destino
from atlas_core.rutas.geocerca import (
    RADIO_GEOCERCA_KM_PREDETERMINADO,
    coordenada_ruteo_planta,
    distancia_km_haversine,
)
from atlas_core.rutas.modelos import CandidatoGeocodificacion, Coordenadas, EstadoRuta
from atlas_core.rutas.posicion_vehiculo import ProveedorPosicionVehiculo
from atlas_core.rutas.proveedor import ProveedorRutas
from atlas_core.territorio_chile import (
    ESTADO_COMUNA_EXACTA,
    normalizar_comuna,
    normalizar_direccion_con_comunas,
    region_valida,
)

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
    # Bloque TELEMETRÍA T1 -- "TELEMETRIA_GPS" cuando un punto GPS real
    # (breadcrumb) ayudó a descartar candidatos y dejar uno solo coherente;
    # vacío en cualquier otro caso (comportamiento idéntico a antes de
    # este bloque).
    metodo_confirmacion: str = ""

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
            "metodo_confirmacion": self.metodo_confirmacion,
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


def descartar_candidatos_lejos_de_gps(
    candidatos: tuple[CandidatoGeocodificacion, ...],
    punto_gps: Coordenadas | None,
    radio_maximo_km: float,
) -> tuple[CandidatoGeocodificacion, ...]:
    """Bloque TELEMETRÍA T1 -- usa el punto final real de un recorrido GPS
    (breadcrumb de Onelogis u otro proveedor de telemetría) como evidencia
    ADICIONAL para descartar candidatos de geocodificación territorialmente
    incompatibles (caso real 463630: "Coronel, Región del Maule" a ~470 km
    del punto final GPS real se descarta; "Coronel, Región del Biobío" a
    ~7 km se conserva).

    Nunca fabrica una dirección exacta a partir del GPS -- solo DESCARTA;
    la decisión de aceptar el candidato restante sigue en manos de quien
    llama (p. ej. `resolver_destino_entrega`, exigiendo que quede
    exactamente uno). Si el descarte deja la lista vacía o no hay punto
    GPS, se conserva la lista original completa -- nunca inventa
    evidencia donde no la hay."""
    if punto_gps is None or not candidatos:
        return candidatos
    compatibles = tuple(
        c for c in candidatos
        if distancia_km_haversine(punto_gps, c.coordenadas) <= radio_maximo_km
    )
    return compatibles if compatibles else candidatos


def _descartar_lejos_de_todo_el_recorrido(
    candidatos: tuple[CandidatoGeocodificacion, ...],
    puntos_gps: tuple[Coordenadas, ...],
    radio_maximo_km: float,
) -> tuple[CandidatoGeocodificacion, ...]:
    """Variante de `descartar_candidatos_lejos_de_gps` para un RECORRIDO
    completo (varios puntos, no un único `punto_gps_destino` elegido por
    una ventana estrecha) -- conserva un candidato si está dentro del
    radio de AL MENOS UNO de los puntos (evidencia de que el vehículo
    pasó cerca en algún momento de la ventana documental), lo descarta
    sólo si está lejos de TODOS. Mismo radio ya calibrado y en uso en
    producción (`radio_gps_km`/`radio_gps_destino_km`, 50.0 km por
    defecto) -- nunca un umbral nuevo. Misma garantía que la función que
    generaliza: si el descarte deja la lista vacía o no hay puntos, se
    conserva la lista original completa."""
    if not puntos_gps or not candidatos:
        return candidatos
    compatibles = tuple(
        c for c in candidatos
        if any(distancia_km_haversine(p, c.coordenadas) <= radio_maximo_km for p in puntos_gps)
    )
    return compatibles if compatibles else candidatos


def _destino_confirmado_coincide_texto(destino: Destino, despachar_a_crudo: str) -> bool:
    """True si la CALLE del destino CONFIRMADO aparece literalmente
    (normalizada, sin acentos/mayúsculas, nunca fuzzy) dentro del texto
    documental crudo -- misma exigencia conservadora que el resto del
    catálogo (`clave_fisica_destino` nunca es fuzzy). `direccion` en
    `destinos_maestros.json` es "CALLE NÚMERO, COMUNA[, REGIÓN], PAÍS" (el
    propio catálogo la persiste así, ver `migracion_excel_estudio_distancias`)
    -- comparar la cadena COMPLETA fallaría siempre porque el documento
    nunca repite la coletilla ", CHILE"; se usa sólo el primer segmento
    (la calle+número, antes de la primera coma), que es la parte que
    realmente identifica el punto físico. Una dirección vacía nunca
    "coincide" con nada."""
    calle = destino.direccion.split(",", 1)[0]
    calle_normalizada = _texto_normalizado_sin_acentos(calle)
    if not calle_normalizada:
        return False
    return calle_normalizada in _texto_normalizado_sin_acentos(despachar_a_crudo)


def _candidato_respaldado_por_destino_confirmado(
    destino: Destino, candidatos: tuple[CandidatoGeocodificacion, ...],
) -> CandidatoGeocodificacion | None:
    """Entre los candidatos de geocodificación, el que cae dentro de
    `MARGEN_MISMO_LUGAR_KM` (ya calibrado, no nuevo) de las coordenadas
    del destino confirmado -- sólo si es EXACTAMENTE uno (dos candidatos
    igual de cerca del mismo destino confirmado no aportan evidencia de
    cuál es el correcto; se abstiene)."""
    if destino.latitud is None or destino.longitud is None:
        return None
    coordenada_destino = Coordenadas(destino.longitud, destino.latitud)
    coincidencias = [
        c for c in candidatos
        if distancia_km_haversine(coordenada_destino, c.coordenadas) <= MARGEN_MISMO_LUGAR_KM
    ]
    return coincidencias[0] if len(coincidencias) == 1 else None


VIA_CATALOGO_CONFIRMADO = "CATALOGO_CONFIRMADO"
VIA_GPS_DESCARTA_RIVALES = "GPS_DESCARTA_RIVALES"


@dataclass(frozen=True)
class ResultadoDesambiguacionInequivoca:
    """Resultado de intentar resolver, SIN adivinar, una ambigüedad de
    destino ya declarada (`MULTIPLES_UBICACIONES_DISPERSAS`).
    `resuelto=False` es siempre una abstención legítima -- nunca un
    error ni un fallo del mecanismo; simplemente no hay evidencia
    suficientemente fuerte para actuar sin consultar a un humano.

    `identidad_confirmada` (Bloque CONFIRMACIÓN D2, caso real 472037 --
    VICUÑA MACKENNA 655 CONFIRMADA por Javier en Revisión de Atlas, ruta
    seguía sin resolverse): True cuando existe una entrada CONFIRMADA de
    `destinos_maestros.json` cuya `direccion` coincide textualmente
    (`_destino_confirmado_coincide_texto`) con `despachar_a_crudo`,
    **independiente** de si esa entrada tiene coordenadas propias que
    permitan resolver el candidato (Vía A puede fallar por falta de
    coordenadas -- ver docstring del módulo de aplicación de decisiones,
    R16 -- y aun así la IDENTIDAD del destino ya está resuelta). Distingue
    "todavía no sabemos cuál lugar es" (ambigüedad de identidad genuina)
    de "ya sabemos cuál lugar es, sólo falta el punto geográfico exacto"
    (un problema técnico posterior, nunca la misma pregunta otra vez)."""

    resuelto: bool = False
    candidato: CandidatoGeocodificacion | None = None
    motivo: str = ""
    vias: tuple[str, ...] = ()
    identidad_confirmada: bool = False


def resolver_destino_ambiguo_con_evidencia_inequivoca(
    despachar_a_crudo: str,
    candidatos_ambiguos: tuple[CandidatoGeocodificacion, ...],
    *,
    breadcrumbs: tuple[Coordenadas, ...] = (),
    destinos_confirmados: Iterable[Destino] = (),
    radio_gps_km: float = 50.0,
) -> ResultadoDesambiguacionInequivoca:
    """Bloque DESTINOS D1 -- intenta resolver, de forma general y sin
    hardcodear ningún caso concreto, una ambigüedad de destino ya
    declarada (`candidatos_ambiguos`: los candidatos de geocodificación
    que `resolver_destino_entrega` no pudo colapsar a uno solo -- YA
    filtrados por soporte textual, ver `_candidatos_con_soporte_textual`).

    Principio (Javier, verbatim): "Atlas puede sugerir. Atlas no debe
    adivinar." -- esta función SÓLO resuelve cuando la evidencia es
    inequívoca; en cualquier otro caso se abstiene explícitamente
    (`resuelto=False`), dejando `MULTIPLES_UBICACIONES_DISPERSAS`
    intacto para que un humano decida. Nunca implementa "elegir el
    candidato más cercano" como regla general -- eso sigue prohibido por
    la regla de negocio del módulo.

    Dos vías independientes, cada una reutilizando exclusivamente
    mecanismos e infraestructura YA EXISTENTES y calibrados -- ningún
    umbral nuevo se define en esta función:

    **Vía A -- catálogo confirmado.** Si existe una entrada de
    `destinos_maestros.json` con `estado_calidad=CONFIRMADO` (nunca
    `PENDIENTE` -- una relación pendiente jamás autoriza una resolución
    automática) cuya `direccion` aparece literalmente dentro del texto
    documental (`_destino_confirmado_coincide_texto`, comparación exacta,
    nunca fuzzy) Y cuyas coordenadas caen dentro de
    `MARGEN_MISMO_LUGAR_KM` (ya calibrado en este mismo módulo) de
    EXACTAMENTE un candidato de geocodificación -- ese candidato queda
    resuelto. Si dos entradas confirmadas distintas respaldan candidatos
    DISTINTOS, es un conflicto real -- se abstiene, nunca elige una al
    azar.

    **Vía B -- GPS descarta a todos los rivales.** Si se entrega el
    recorrido GPS completo de la ventana documental (`breadcrumbs`,
    TODOS los puntos disponibles -- nunca sólo el último punto de un
    recorrido "sustancial" con ventana estrecha, ver limitación conocida
    de T2/`seleccionar_recorrido_operacional` -- y nunca de otro
    día/patente) y, al descartar por el radio YA EXISTENTE (`radio_gps_km`,
    mismo valor que ya usan `resolver_destino_entrega`/
    `calcular_ruta_con_planta_conocida`) contra CADA candidato, sobrevive
    EXACTAMENTE uno -- ese candidato queda resuelto. Esto nunca es "el
    más cercano": un candidato sobrevive por estar DENTRO del radio ya
    calibrado, no por ser relativamente el mejor entre varios lejanos: si
    dos o más candidatos sobreviven el descarte (todos dentro del radio,
    aunque uno esté más cerca que otro), o si ninguno sobrevive (todos
    fuera -- la función de descarte conserva la lista original completa,
    ver `_descartar_lejos_de_todo_el_recorrido`), la función se abstiene.

    Si ambas vías producen una respuesta y DISCREPAN entre sí, se
    abstiene explícitamente (`CATALOGO_Y_GPS_DISCREPAN`) -- nunca se
    prioriza una fuente sobre otra en silencio."""
    texto = str(despachar_a_crudo or "").strip()
    # Bloque CONFIRMACIÓN D2 -- se calcula SIEMPRE, independiente de si
    # Vía A logra resolver un candidato: un destino CONFIRMADO cuya
    # dirección coincide textualmente con `despachar_a_crudo` significa
    # que un humano ya validó esa IDENTIDAD, aunque esa entrada del
    # catálogo no tenga coordenadas propias (p. ej. quedó confirmada sin
    # que la ruta llegara a calcularse -- ver `aplicar_decision_obra`,
    # Bloque R16) y por lo tanto Vía A no pueda respaldar ningún
    # candidato. Nunca decide el candidato -- sólo distingue "identidad
    # ya resuelta" de "identidad todavía ambigua" para el motivo que
    # `resolver_destino_entrega` deja si de todos modos no logra pinchar
    # un único punto.
    identidad_confirmada = texto and any(
        destino.estado_calidad == "CONFIRMADO" and destino.estado_vigencia == "ACTIVO"
        and _destino_confirmado_coincide_texto(destino, texto)
        for destino in destinos_confirmados
    )

    if len(candidatos_ambiguos) < 2:
        return ResultadoDesambiguacionInequivoca(
            motivo="NO_ES_UNA_AMBIGUEDAD_REAL", identidad_confirmada=identidad_confirmada,
        )

    candidato_via_a: CandidatoGeocodificacion | None = None
    conflicto_via_a = False
    if texto:
        for destino in destinos_confirmados:
            if destino.estado_calidad != "CONFIRMADO" or destino.estado_vigencia != "ACTIVO":
                continue
            if not _destino_confirmado_coincide_texto(destino, texto):
                continue
            respaldado = _candidato_respaldado_por_destino_confirmado(destino, candidatos_ambiguos)
            if respaldado is None:
                continue
            if candidato_via_a is not None and respaldado is not candidato_via_a:
                conflicto_via_a = True
            candidato_via_a = respaldado
    if conflicto_via_a:
        return ResultadoDesambiguacionInequivoca(
            motivo="CONFLICTO_ENTRE_DESTINOS_CONFIRMADOS", vias=(VIA_CATALOGO_CONFIRMADO,),
            identidad_confirmada=identidad_confirmada,
        )

    candidato_via_b: CandidatoGeocodificacion | None = None
    if breadcrumbs:
        sobrevivientes = _descartar_lejos_de_todo_el_recorrido(
            candidatos_ambiguos, breadcrumbs, radio_gps_km
        )
        if len(sobrevivientes) == 1 and len(sobrevivientes) < len(candidatos_ambiguos):
            candidato_via_b = sobrevivientes[0]

    if candidato_via_a is not None and candidato_via_b is not None:
        if candidato_via_a is not candidato_via_b:
            return ResultadoDesambiguacionInequivoca(
                motivo="CATALOGO_Y_GPS_DISCREPAN",
                vias=(VIA_CATALOGO_CONFIRMADO, VIA_GPS_DESCARTA_RIVALES),
                identidad_confirmada=identidad_confirmada,
            )
        return ResultadoDesambiguacionInequivoca(
            resuelto=True, candidato=candidato_via_a,
            motivo="CATALOGO_CONFIRMADO_Y_GPS_COINCIDEN",
            vias=(VIA_CATALOGO_CONFIRMADO, VIA_GPS_DESCARTA_RIVALES),
            identidad_confirmada=identidad_confirmada,
        )
    if candidato_via_a is not None:
        return ResultadoDesambiguacionInequivoca(
            resuelto=True, candidato=candidato_via_a,
            motivo="CATALOGO_CONFIRMADO_COINCIDE_GEOCODIFICACION",
            vias=(VIA_CATALOGO_CONFIRMADO,),
            identidad_confirmada=identidad_confirmada,
        )
    if candidato_via_b is not None:
        return ResultadoDesambiguacionInequivoca(
            resuelto=True, candidato=candidato_via_b,
            motivo="GPS_DESCARTA_TODO_RIVAL_FUERA_DE_RADIO",
            vias=(VIA_GPS_DESCARTA_RIVALES,),
            identidad_confirmada=identidad_confirmada,
        )
    return ResultadoDesambiguacionInequivoca(
        motivo="SIN_EVIDENCIA_INEQUIVOCA", identidad_confirmada=identidad_confirmada,
    )


VIA_FALLBACK_ESTRUCTURADO = "FALLBACK_GEOCODER_ESTRUCTURADO"

# Bloque CATCH-UP LOGÍSTICO -- caso real 460807/472008 ("INTERIOR NUEVA
# O1148 SAN BERNARDO"): un patrón OCR real y recurrente pierde/confunde
# el símbolo de numeral ("Nº"/"N°") con una única letra pegada al número
# ("O1148" en vez de "Nº 1148") -- `_PATRON_NUMERO_CALLE` (con `\b` a
# ambos lados) nunca lo detecta como número porque no hay borde de
# palabra entre la letra y los dígitos. Nunca vuelve a leer el
# documento/OCR -- sólo interpreta mejor el texto YA extraído.
_PATRON_NUMERO_CON_PREFIJO_OCR = re.compile(r"\b[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]\d{1,6}\b")


def _numeros_de_calle(texto: str) -> set[str]:
    """Números de calle presentes en `texto` -- tokens numéricos
    completos, MÁS tokens con un único carácter pegado adelante
    (`_PATRON_NUMERO_CON_PREFIJO_OCR`) interpretados por su parte
    numérica (nunca por el prefijo, que un geocodificador estructurado
    tampoco trae en su propio `house_number`)."""
    numeros = set(_PATRON_NUMERO_CALLE.findall(texto))
    numeros.update(token[1:] for token in _PATRON_NUMERO_CON_PREFIJO_OCR.findall(texto))
    return numeros


def _candidato_unico_con_numero_de_calle(
    despachar_a_crudo: str, candidatos: tuple[CandidatoGeocodificacion, ...],
) -> CandidatoGeocodificacion | None:
    """Bloque B1 OBSERVADOR + FALLBACK GEOGRÁFICO -- entre los candidatos
    de un geocodificador de RESPALDO, el ÚNICO cuya etiqueta reproduce
    literalmente el mismo número de calle presente en el texto documental
    -- nunca "el primero" ni "el más cercano". Un número de casa exacto es
    evidencia mucho más específica que un mero nombre de calle/comuna
    (que puede repetirse en decenas de lugares reales de Chile); dos
    candidatos con el mismo número (calles homónimas distintas, cada una
    con esa numeración) siguen sin ser evidencia inequívoca -- se
    abstiene."""
    numeros_documento = _numeros_de_calle(despachar_a_crudo)
    if not numeros_documento:
        return None
    coincidencias = [
        c for c in candidatos
        if _numeros_de_calle(c.etiqueta) & numeros_documento
    ]
    return coincidencias[0] if len(coincidencias) == 1 else None


def _comuna_confirma_candidato(comuna_confirmada: str, comuna_candidato: str) -> bool:
    """True si ambas comunas identifican la MISMA comuna real del
    catálogo territorial cerrado (comparación exacta tras normalizar --
    nunca fuzzy), o si son compatibles bajo el criterio YA calibrado de
    `_comunas_territorialmente_compatibles` (caso "Santiago" como
    ciudad/área metropolitana vs comuna específica, Bloque TERRITORIAL
    T1) -- esa función por sí sola NO cubre "son la misma comuna", sólo
    el caso especial de Santiago; aquí se agrega primero el caso general
    (obvio pero no cubierto ahí) antes de delegar al caso especial."""
    documental = normalizar_comuna(comuna_confirmada)
    candidato = normalizar_comuna(comuna_candidato)
    if (
        documental.estado == ESTADO_COMUNA_EXACTA and candidato.estado == ESTADO_COMUNA_EXACTA
        and documental.comuna == candidato.comuna
    ):
        return True
    return _comunas_territorialmente_compatibles(comuna_confirmada, comuna_candidato)


def _comuna_candidato_en_texto(texto_documental: str, comuna_candidato: str) -> bool:
    """Bloque CIERRE LOGÍSTICA RESIDUAL -- True si `comuna_candidato`
    coincide (mismo criterio de `_comuna_confirma_candidato`: exacta o
    territorialmente compatible) con ALGUNA de las comunas reales que
    `texto_documental` menciona explícitamente (`_comunas_explicitas`,
    catálogo territorial cerrado, nunca fuzzy). El texto documental ya
    forma parte de la identidad CONFIRMADA (es el mismo texto que
    `_destino_confirmado_coincide_texto` ya usa) -- una comuna que el
    propio documento nombra es evidencia real, nunca inventada."""
    for comuna_mencionada in _comunas_explicitas(texto_documental):
        if _comuna_confirma_candidato(comuna_mencionada, comuna_candidato):
            return True
    return False


_PATRON_PALABRA = re.compile(r"[A-ZÁÉÍÓÚÜÑ]+")


def _texto_menciona_comuna_como_palabra_completa(texto: str, comuna: str) -> bool:
    """True si `comuna` aparece en `texto` como PALABRA COMPLETA (nunca
    substring dentro de otra palabra, nunca fuzzy) -- comparación por
    tokens, no por `in` sobre el string crudo. Sirve para leer evidencia
    YA PERSISTIDA (nunca nueva investigación) en busca de una mención
    territorial reconocible, sin el riesgo de coincidencias espurias de
    un `in` ingenuo (p. ej. "Colina" dentro de otra palabra)."""
    palabras = set(_PATRON_PALABRA.findall(_texto_normalizado_sin_acentos(texto).upper()))
    comuna_normalizada = _texto_normalizado_sin_acentos(comuna).upper()
    tokens_comuna = comuna_normalizada.split()
    if len(tokens_comuna) == 1:
        return comuna_normalizada in palabras
    # Comunas de más de una palabra (p. ej. "SAN BERNARDO"): exige la
    # frase completa como subsecuencia contigua de tokens, no sólo que
    # cada palabra suelta aparezca en cualquier parte del texto.
    return comuna_normalizada in " ".join(_PATRON_PALABRA.findall(_texto_normalizado_sin_acentos(texto).upper()))


def resolver_destino_con_fallback_estructurado(
    despachar_a_crudo: str,
    *,
    proveedor_fallback: ProveedorRutas,
    destinos_confirmados: Iterable[Destino] = (),
    contexto_evidencia_b1: str = "",
) -> ResultadoDesambiguacionInequivoca:
    """Bloque B1 OBSERVADOR + FALLBACK GEOGRÁFICO -- "Vía C": cuando el
    proveedor PRINCIPAL deja una ambigüedad sin resolver y ni Vía A
    (catálogo confirmado) ni Vía B (GPS) tienen evidencia para
    desambiguar, se consulta UN proveedor de geocodificación de RESPALDO
    (sólo uno -- nunca "15 fuentes web", estructurado, restringido a
    Chile, nunca scraping frágil -- ver `NominatimGeocoder`) ANTES de
    escalar a investigación B1 compleja (Javier, Bloque D: "Sólo después:
    B1 investigación compleja").

    Se acepta el candidato del respaldo SÓLO cuando:
    1. es el ÚNICO candidato cuyo número de calle coincide literalmente
       con el texto documental (`_candidato_unico_con_numero_de_calle`
       -- nunca "el primero"/"el más cercano");
    2. Y corrobora contra evidencia YA CONFIRMADA/PERSISTIDA (nunca
       nueva), por cualquiera de estas dos vías equivalentes:
       a) un destino ya CONFIRMADO para esta misma dirección trae comuna
          propia territorialmente compatible con la comuna del
          candidato (mismo criterio ya calibrado, Bloque TERRITORIAL T1);
       b) o la evidencia de B1 YA PERSISTIDA (`contexto_evidencia_b1`,
          nunca una llamada nueva) menciona "Santiago" como ciudad/área
          metropolitana, y esa mención es territorialmente compatible
          con la comuna del candidato (mismo criterio T1 -- "Santiago"
          y una comuna específica de la misma región no son una
          contradicción, ver Bloque VALIDACIÓN TERRITORIAL T2).

    Sin ninguna de las dos corroboraciones, un número de calle
    coincidente por sí solo NO es "evidencia inequívoca" -- podría ser
    una calle homónima en una comuna real distinta (caso conocido:
    nombres de calle que se repiten en Chile) -- se abstiene en vez de
    adivinar, dejando el candidato visible sólo en el motivo técnico para
    que un humano o B1 lo revise si hace falta (Bloque F: "B1 puede
    validar semánticamente el candidato cuando haga falta")."""
    texto = str(despachar_a_crudo or "").strip()
    if not texto:
        return ResultadoDesambiguacionInequivoca(motivo="SIN_TEXTO_DOCUMENTAL")
    identidad_confirmada = any(
        d.estado_calidad == "CONFIRMADO" and d.estado_vigencia == "ACTIVO"
        and _destino_confirmado_coincide_texto(d, texto)
        for d in destinos_confirmados
    )
    if not _numeros_de_calle(texto):
        # Nunca gasta una consulta de red (Bloque J: "no gastar si no
        # hace falta") cuando el propio texto documental no tiene ningún
        # número de calle con el que un candidato del respaldo pudiera
        # siquiera coincidir -- `_candidato_unico_con_numero_de_calle`
        # abstendría igual, pero después de pagar la llamada.
        return ResultadoDesambiguacionInequivoca(
            motivo="SIN_NUMERO_DE_CALLE_EN_TEXTO_DOCUMENTAL",
            identidad_confirmada=identidad_confirmada,
        )
    try:
        resultado_fallback = proveedor_fallback.geocodificar(f"{texto}, Chile")
    except (OSError, ValueError):
        return ResultadoDesambiguacionInequivoca(
            motivo="FALLBACK_ESTRUCTURADO_NO_DISPONIBLE", vias=(VIA_FALLBACK_ESTRUCTURADO,),
            identidad_confirmada=identidad_confirmada,
        )
    candidato = _candidato_unico_con_numero_de_calle(texto, resultado_fallback.candidatos or ())
    if candidato is None:
        return ResultadoDesambiguacionInequivoca(
            motivo="FALLBACK_SIN_CANDIDATO_UNICO", vias=(VIA_FALLBACK_ESTRUCTURADO,),
            identidad_confirmada=identidad_confirmada,
        )
    destino_corroborante = next(
        (
            d for d in destinos_confirmados
            if d.estado_calidad == "CONFIRMADO" and d.estado_vigencia == "ACTIVO"
            and _destino_confirmado_coincide_texto(d, texto) and d.comuna and candidato.localidad
            and _comuna_confirma_candidato(d.comuna, candidato.localidad)
        ),
        None,
    )
    corroborado_por_evidencia_b1 = (
        destino_corroborante is None and candidato.localidad
        # Bloque VALIDACIÓN TERRITORIAL T2 -- caso real 472037: el
        # destino CONFIRMADO no siempre trae comuna estructurada propia
        # (Bloque CONFIRMACIÓN D2 -- se confirmó sin que la ruta llegara
        # a calcularse), pero B1 ya investigó y dejó, en su evidencia YA
        # PERSISTIDA (nunca una llamada nueva), una mención territorial
        # de nivel ciudad/área metropolitana ("Santiago") -- el mismo
        # criterio YA calibrado (`_comunas_territorialmente_compatibles`,
        # Bloque TERRITORIAL T1) ya sabe que "Santiago" como ciudad/área
        # metropolitana es compatible con cualquier comuna real de la
        # MISMA región (p. ej. Maipú, RM) -- nunca exige que coincidan
        # literalmente. Nunca escanea la evidencia buscando cualquier
        # comuna del catálogo (345 nombres, muchos coinciden con
        # palabras comunes del español -- riesgo real de falso positivo,
        # ver `_comunas_explicitas`); se limita, a propósito, a esta
        # única mención de nivel ciudad ya reconocida como caso especial
        # en el resto del sistema.
        and _texto_menciona_comuna_como_palabra_completa(contexto_evidencia_b1, "Santiago")
        and _comunas_territorialmente_compatibles("Santiago", candidato.localidad)
    )
    # Bloque CIERRE LOGÍSTICA RESIDUAL -- casos reales 460807/472008
    # ("...SAN BERNARDO") y 464981 ("...SANTIAGO MAIPU"): la comuna real
    # del candidato a veces ya está escrita, LITERALMENTE, en el propio
    # texto documental confirmado -- evidencia todavía más directa que un
    # destino confirmado aparte o que B1 (es el mismo texto que la
    # identidad ya confirmada). Reutiliza el catálogo territorial cerrado
    # ya existente (`_comunas_explicitas`, nunca fuzzy, nunca una lista
    # propia) -- corrobora si el candidato cae en CUALQUIERA de las
    # comunas reales que el texto menciona explícitamente, incluso si
    # menciona más de una (p. ej. "Santiago" como área metropolitana +
    # "Maipú" como comuna específica -- Bloque TERRITORIAL T1: eso no es
    # una contradicción, son dos niveles del mismo lugar).
    corroborado_por_texto_documental = (
        destino_corroborante is None and not corroborado_por_evidencia_b1 and candidato.localidad
        and _comuna_candidato_en_texto(texto, candidato.localidad)
    )
    if destino_corroborante is None and not corroborado_por_evidencia_b1 and not corroborado_por_texto_documental:
        return ResultadoDesambiguacionInequivoca(
            motivo=f"FALLBACK_SIN_CORROBORACION_TERRITORIAL: {candidato.etiqueta}",
            candidato=candidato, vias=(VIA_FALLBACK_ESTRUCTURADO,),
            identidad_confirmada=identidad_confirmada,
        )
    return ResultadoDesambiguacionInequivoca(
        resuelto=True, candidato=candidato, motivo="FALLBACK_ESTRUCTURADO_CORROBORADO",
        vias=(VIA_FALLBACK_ESTRUCTURADO,), identidad_confirmada=identidad_confirmada,
    )


def _mejor_candidato(candidatos: tuple[CandidatoGeocodificacion, ...]) -> CandidatoGeocodificacion:
    """Entre candidatos que ya se determinó que son el mismo lugar real,
    el de mayor confianza informada (nunca el más cercano a ninguna
    referencia externa como una planta AZA)."""
    return max(candidatos, key=lambda c: c.confianza if c.confianza is not None else -1.0)


_PATRON_NUMERO_CALLE = re.compile(r"\b\d{1,6}\b")
# Bloque FIX DE ACEPTACION -- caso real 472247 ("CAMINO A MELIFILLA
# 1OBOD SANTIAGO MAIPU": el OCR mezcló letras dentro del número de casa,
# "1OBOD" en vez de algo como "10800" -- ni un dígito puro ni el patrón
# ya cubierto de "una letra pegada ADELANTE de dígitos" que
# `_PATRON_NUMERO_CON_PREFIJO_OCR` (más abajo) ya reconoce para
# `_numeros_de_calle`). Un token corto (2-6 caracteres) que MEZCLA
# dígitos y letras en cualquier posición sigue ocupando, con altísima
# probabilidad, el lugar de un número de casa/local ruidoso por OCR --
# nunca decodifica ni asume qué número real es, sólo reconoce la FORMA
# (mismo principio barato que el resto de este proxy).
_PATRON_TOKEN_ALFANUMERICO_CORTO = re.compile(r"\b[A-Za-zÁÉÍÓÚÜÑáéíóúüñ0-9]{2,6}\b")


def _trae_numero_calle(texto: str) -> bool:
    """Proxy barato y genérico de "tiene una dirección específica" --
    al menos un token numérico de 1-6 dígitos (número de casa/local), o
    un token corto que mezcla dígitos y letras (número de casa
    corrompido por OCR, caso real 472247). Nunca depende de un formato
    fijo ni de nombres de comuna concretos, nunca compara ni decodifica
    el valor -- sólo su forma."""
    if _PATRON_NUMERO_CALLE.search(texto):
        return True
    return any(
        any(c.isdigit() for c in token) and any(c.isalpha() for c in token)
        for token in _PATRON_TOKEN_ALFANUMERICO_CORTO.findall(texto)
    )


def _etiqueta_geocodificada_o_texto_documental(*, etiqueta: str, texto_documental: str) -> str:
    """Bloque LOGÍSTICA L1 -- jerarquía de especificidad del destino
    (dirección específica > comuna > ciudad > región > país): el
    proveedor de geocodificación a veces sólo puede resolver hasta nivel
    comuna (p. ej. "Las Condes, RM, Chile" cuando el documento trae
    "PUERTA DEL SOL 83 LAS CONDES") -- esa etiqueta sigue siendo válida
    para VALIDAR territorialmente y para las coordenadas de ruteo, pero
    nunca debe reemplazar una dirección con calle+número ya disponible en
    el propio documento como destino OPERACIONAL mostrado/persistido.
    Comparación barata (presencia de número de calle), nunca compara
    nombres de calle ni depende de una lista de comunas."""
    if _trae_numero_calle(texto_documental) and not _trae_numero_calle(etiqueta):
        return texto_documental
    return etiqueta


# --- Bloque FIX FINAL DE ACEPTACION -- caso real 472247/472212 --------
#
# "CAMINO A MELIFILLA 1OBOD SANTIAGO MAIPU" es específico (tiene forma
# de dirección con número, `_trae_numero_calle` ya lo preserva sobre una
# etiqueta genérica), pero el propio OCR corrompió DOS de sus tokens
# (nombre de calle + número). Atlas no necesita "leer" el OCR para
# corregirlo: otro documento del MISMO cliente (464981, misma obra real)
# ya trae la MISMA dirección sin ruido -- "CAMINO A MELIPILLA 10800
# SANTIAGO MAIPU". Comparar contra ese documento hermano (o contra un
# destino ya CONFIRMADO compatible) es evidencia real, nunca un mapeo de
# caracteres inventado ("MELIFILLA -> MELIPILLA" no existe en ningún
# lado del código -- se descubre comparando textos, no traduciéndolos).

_PATRON_TOKEN_DIRECCION = re.compile(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ0-9]+")


def _tokens_direccion(texto: str) -> tuple[str, ...]:
    return tuple(t.upper() for t in _PATRON_TOKEN_DIRECCION.findall(str(texto or "")))


def _token_con_ruido_ocr(token: str) -> bool:
    """Mismo criterio que `_trae_numero_calle` para "número corrompido"
    -- dígitos y letras mezclados en un token corto."""
    return 2 <= len(token) <= 6 and any(c.isdigit() for c in token) and any(c.isalpha() for c in token)


def _cantidad_tokens_con_ruido_ocr(texto: str) -> int:
    return sum(1 for token in _tokens_direccion(texto) if _token_con_ruido_ocr(token))


def _variante_documental_mas_limpia(candidato: str, objetivo: str) -> bool:
    """True si `candidato` es una variante de la MISMA dirección que
    `objetivo` (misma cantidad de tokens, la mayoría idénticos -- nunca
    menos de la mitad, para no confundir direcciones genuinamente
    distintas) y tiene MENOS ruido OCR que `objetivo`. Comparación
    puramente estructural (cantidad y posición de tokens iguales/
    distintos) -- nunca decodifica ni traduce ningún token."""
    tokens_candidato = _tokens_direccion(candidato)
    tokens_objetivo = _tokens_direccion(objetivo)
    if not tokens_candidato or len(tokens_candidato) != len(tokens_objetivo):
        return False
    diferencias = sum(1 for a, b in zip(tokens_candidato, tokens_objetivo) if a != b)
    if diferencias == 0:
        return False  # idéntico -- nada que ganar
    if len(tokens_candidato) - diferencias < len(tokens_candidato) / 2:
        return False  # menos de la mitad coincide -- no es la misma dirección
    return _cantidad_tokens_con_ruido_ocr(candidato) < _cantidad_tokens_con_ruido_ocr(objetivo)


def resolver_direccion_canonica_mas_limpia(*, texto_objetivo: str, candidatos: Iterable[str]) -> str | None:
    """Bloque FIX FINAL DE ACEPTACION -- entre `candidatos` (documentos
    hermanos del mismo cliente/obra, o direcciones de destinos ya
    CONFIRMADOS compatibles), busca una variante de la MISMA dirección
    con MENOS ruido OCR que `texto_objetivo`.

    Bloque SEGURIDAD (mismo principio ya calibrado para obras -- ver
    `resolver_obra_por_variacion_ortografica_menor`): sólo actúa si
    `texto_objetivo` en sí tiene ruido detectable (nunca toca un texto
    ya limpio); entre los candidatos compatibles, prefiere los que
    quedan SIN ningún ruido; si sobrevive más de una variante DISTINTA
    igualmente limpia, se abstiene -- nunca elige arbitrariamente entre
    dos direcciones reales parecidas ("dirección realmente nueva -> no
    sustituir por parecido débil")."""
    objetivo = str(texto_objetivo or "").strip()
    if not objetivo or _cantidad_tokens_con_ruido_ocr(objetivo) == 0:
        return None
    compatibles = [
        candidato for candidato in (str(c or "").strip() for c in candidatos)
        if candidato and _variante_documental_mas_limpia(candidato, objetivo)
    ]
    if not compatibles:
        return None
    limpios = [c for c in compatibles if _cantidad_tokens_con_ruido_ocr(c) == 0]
    fuente = limpios if limpios else compatibles
    unicos = set(fuente)
    if len(unicos) != 1:
        return None
    return next(iter(unicos))


_PATRON_TOKEN_SANTIAGO = re.compile(r"(?i)\bSANTIAGO\b")


def _texto_geocodificable_sin_etiqueta_ciudad_santiago(texto: str) -> str:
    """Bloque RESOLUCIÓN R17 -- casos reales 472018 (CAMINO LOS PINOS 3396
    SANTIAGO SAN BERNARDO) y 464981 (CAMINO A MELIPILLA 10800 SANTIAGO
    MAIPU): cuando el texto documental YA menciona, con el catálogo
    territorial cerrado, una comuna real DISTINTA de "Santiago", el token
    "SANTIAGO" que aparece junto a ella es, con altísima probabilidad, la
    etiqueta de CIUDAD/ÁREA METROPOLITANA que el propio documento repite
    (mismo principio ya establecido en `_comunas_territorialmente_
    compatibles`, Bloque TERRITORIAL T1 -- "Santiago" y una comuna
    específica de la misma región no son una contradicción, son dos
    niveles territoriales del mismo lugar) -- nunca un segundo componente
    real de la calle. Enviado tal cual al geocodificador, ese token
    compite como si fuera una comuna real distinta y dispersa candidatos
    (verificado: 5 candidatos -> 1 al quitarlo para 472018). Se elimina
    SÓLO el token "SANTIAGO" -- nunca ningún otro texto -- y SÓLO cuando
    el catálogo ya identificó, en el propio texto, al menos otra comuna
    real distinta; si "Santiago" es la ÚNICA comuna mencionada, se
    conserva intacta (podría ser genuinamente la comuna real). Nunca toca
    el texto ALMACENADO (`despachar_a_crudo`) -- sólo la consulta que se
    envía al proveedor de geocodificación."""
    comunas = _comunas_explicitas(texto)
    if "Santiago" not in comunas or len(comunas) < 2:
        return texto
    return " ".join(_PATRON_TOKEN_SANTIAGO.sub(" ", texto).split())


def resolver_destino_entrega(
    despachar_a_crudo: str | None,
    proveedor_geocodificacion: ProveedorRutas,
    *,
    contexto_territorial: str = "Chile",
    punto_gps_referencia: Coordenadas | None = None,
    radio_gps_km: float = 50.0,
    destinos_confirmados: Iterable[Destino] = (),
    proveedor_geocodificacion_fallback: ProveedorRutas | None = None,
    contexto_evidencia_b1: str = "",
) -> ResultadoDestinoEntrega:
    """Geocodifica `DESPACHAR A` -- nunca `DIRECCION`/`COMUNA` del cliente.

    Nunca elige el candidato más cercano a una planta AZA ni a ninguna
    otra referencia -- eso violaría la regla de negocio ("nunca escoger
    una ubicación porque esté más cerca de AZA"). Ante más de un
    candidato, o un único candidato sin confianza suficiente, se
    abstiene (`REVISAR`) en vez de adivinar.

    `punto_gps_referencia` (Bloque TELEMETRÍA T1, opcional): punto final
    real de un recorrido GPS (breadcrumb de telemetría) -- si se entrega,
    se usa como evidencia ADICIONAL para descartar candidatos
    territorialmente incompatibles (ver `descartar_candidatos_lejos_de_gps`)
    antes de decidir si la ambigüedad es real. Nunca sustituye la
    geocodificación ni fabrica una dirección -- solo descarta.

    `destinos_confirmados` (Bloque RESOLUCIÓN R16, opcional): catálogo de
    destinos ya CONFIRMADOS -- si la ambigüedad persiste después de los
    descartes anteriores, se intenta resolver con evidencia inequívoca ya
    existente (`resolver_destino_ambiguo_con_evidencia_inequivoca`, Bloque
    DESTINOS D1 -- función ya probada, nunca antes conectada a este
    módulo). Nunca "el candidato más cercano": sólo actúa cuando el
    catálogo confirmado o el recorrido GPS completo dejan exactamente un
    candidato compatible; en cualquier otro caso, la ambigüedad
    `MULTIPLES_UBICACIONES_DISPERSAS` se preserva intacta para revisión
    humana/B1, exactamente igual que antes de este bloque.

    `proveedor_geocodificacion_fallback` (Bloque B1 OBSERVADOR + FALLBACK
    GEOGRÁFICO, opcional): un ÚNICO geocodificador de respaldo
    estructurado (nunca varios, nunca scraping) -- se consulta SÓLO si
    Vía A/Vía B tampoco resolvieron, ANTES de rendirse ante
    `MULTIPLES_UBICACIONES_DISPERSAS`/`COORDENADA_NO_CONFIRMADA` (ver
    `resolver_destino_con_fallback_estructurado`, "Vía C"). Nunca se
    llama si el proveedor principal ya resolvió sin ambigüedad -- "sólo
    si A falla" (Javier)."""
    texto = str(despachar_a_crudo or "").strip()
    if not texto:
        return ResultadoDestinoEntrega(
            despachar_a_crudo="", estado=ESTADO_SIN_DATO, motivo="DESPACHAR_A_NO_INFORMADO"
        )

    # Bloque INTELIGENCIA N1 (Fase D/M) -- limpia, SOLO para la consulta al
    # geocodificador, un token de comuna corrupto por OCR cuando el
    # catálogo territorial local ya lo resuelve sin ambigüedad (p. ej. dos
    # campos del documento repiten la comuna -- uno legible, otro
    # corrompido -- caso real "CATEDRAL 759 CADQUENES CAUQUENES" ->
    # "CATEDRAL 759 CAUQUENES"). `despachar_a_crudo` en el resultado
    # siempre conserva el texto documental original tal cual -- esta
    # limpieza nunca reemplaza la evidencia, solo evita que un typo
    # bloquee la geocodificación cuando el propio catálogo local ya lo
    # resolvería (normalización local primero, nunca ORS para corregir
    # un typo que el catálogo ya resuelve -- Fase N).
    texto_geocodificable = normalizar_direccion_con_comunas(texto)
    # Bloque RESOLUCIÓN R17 -- ver docstring de la función: quita SÓLO
    # para la consulta un token "SANTIAGO" redundante cuando el texto ya
    # trae otra comuna real distinta.
    texto_geocodificable = _texto_geocodificable_sin_etiqueta_ciudad_santiago(texto_geocodificable)
    consulta = (
        f"{texto_geocodificable}, {contexto_territorial}" if contexto_territorial else texto_geocodificable
    )
    resultado = proveedor_geocodificacion.geocodificar(consulta)
    corroborado_por_gps = False
    metodo_confirmacion_fallback = ""

    if resultado.estado == EstadoRuta.RESULTADO_AMBIGUO:
        # Bloque E2E R1.1 -- antes de decidir si hay ambigüedad real,
        # descarta candidatos sin ningún respaldo textual en el propio
        # DESPACHAR A (p. ej. "Ránquil" cuando el documento dice
        # "...CORONEL"). Nunca inventa evidencia: si ninguno tiene
        # respaldo, sigue con el conjunto completo (comportamiento
        # idéntico al de antes de este bloque).
        candidatos_relevantes = _candidatos_con_soporte_textual(resultado.candidatos, texto)
        # Bloque TELEMETRÍA T1 -- evidencia GPS real (opcional), descarta
        # candidatos territorialmente incompatibles con el recorrido real.
        if punto_gps_referencia is not None:
            antes = candidatos_relevantes
            candidatos_relevantes = descartar_candidatos_lejos_de_gps(
                candidatos_relevantes, punto_gps_referencia, radio_gps_km
            )
            corroborado_por_gps = candidatos_relevantes != antes
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
            # Bloque RESOLUCIÓN R16 -- antes de rendirse ante
            # `MULTIPLES_UBICACIONES_DISPERSAS`, agota la evidencia
            # INEQUÍVOCA ya disponible (nunca "el más cercano"): catálogo
            # de destinos CONFIRMADOS para la misma obra/cliente, o el
            # punto GPS real de este mismo recorrido como único breadcrumb
            # disponible aquí (ver docstring del parámetro). Si ninguna vía
            # produce una respuesta inequívoca, la abstención original se
            # preserva sin cambios.
            breadcrumbs = (punto_gps_referencia,) if punto_gps_referencia is not None else ()
            desambiguacion = resolver_destino_ambiguo_con_evidencia_inequivoca(
                texto, candidatos_relevantes,
                breadcrumbs=breadcrumbs, destinos_confirmados=destinos_confirmados,
                radio_gps_km=radio_gps_km,
            )
            if desambiguacion.resuelto and desambiguacion.candidato is not None:
                candidato = desambiguacion.candidato
                corroborado_por_gps = corroborado_por_gps or VIA_GPS_DESCARTA_RIVALES in desambiguacion.vias
            elif proveedor_geocodificacion_fallback is not None and (
                fallback := resolver_destino_con_fallback_estructurado(
                    texto, proveedor_fallback=proveedor_geocodificacion_fallback,
                    destinos_confirmados=destinos_confirmados,
                    contexto_evidencia_b1=contexto_evidencia_b1,
                )
            ).resuelto and fallback.candidato is not None:
                # Bloque B1 OBSERVADOR + FALLBACK GEOGRÁFICO -- "Vía C",
                # sólo se consulta cuando A/B ya fallaron ("sólo si A
                # falla"). El candidato, si corrobora, sigue pasando por
                # los MISMOS controles de abajo (territorio/confianza) --
                # nunca un camino paralelo con reglas propias.
                candidato = fallback.candidato
                metodo_confirmacion_fallback = "FALLBACK_ESTRUCTURADO_CORROBORADO"
            else:
                # Bloque CONFIRMACIÓN D2 -- caso real 472037 (VICUÑA
                # MACKENNA 655): Javier ya confirmó esta dirección en
                # Revisión de Atlas (`identidad_confirmada`, ver
                # docstring de `ResultadoDesambiguacionInequivoca`) pero
                # ninguna vía logró pinchar un único punto geográfico
                # entre los candidatos dispersos. `MULTIPLES_UBICACIONES_
                # DISPERSAS` implica que la IDENTIDAD del destino sigue
                # sin resolver -- eso ya no es cierto, y repetirlo
                # contradice una decisión humana ya aplicada (nunca debe
                # volver a sonar como si Atlas no supiera qué dirección
                # es). El problema real ahora es puramente geográfico/
                # técnico -- no está en `MOTIVOS_DESTINO_NO_RESUELTO`
                # (`decisiones_pendientes.py`), así que nunca vuelve a
                # generar una pregunta para Javier sobre algo que ya
                # respondió.
                motivo_base = (
                    "COORDENADA_NO_CONFIRMADA" if desambiguacion.identidad_confirmada
                    else "MULTIPLES_UBICACIONES_DISPERSAS"
                )
                return ResultadoDestinoEntrega(
                    despachar_a_crudo=texto, estado=ESTADO_REVISAR,
                    motivo=f"{motivo_base}({len(resultado.candidatos)})",
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

    # Bloque TERRITORIAL T1 -- caso real 472037 (VICUÑA MACKENNA 655):
    # descubierto al corregir el falso positivo de comuna -- sin ninguna
    # comuna documental que contradecir, el resultado del geocodificador
    # se aceptaba tal cual, y en este caso real el proveedor resolvió a
    # "Córdoba" (Argentina) -- una confusión real del propio proveedor
    # con una localidad homónima fuera de Chile, nunca detectada porque
    # nada validaba la REGIÓN devuelta contra el universo cerrado de
    # regiones chilenas (Atlas opera en Chile, ver docstring de
    # `territorio_chile`). Reutiliza el mismo catálogo territorial ya
    # existente (`region_valida`) -- nunca una lista propia de países o
    # regiones extranjeras a excluir. Protección independiente de la
    # comparación de comuna: corre siempre que se opera en contexto
    # Chile, exista o no evidencia documental de comuna.
    if (
        str(contexto_territorial or "").strip().casefold() == "chile"
        and candidato.region and not region_valida(candidato.region)
    ):
        return ResultadoDestinoEntrega(
            despachar_a_crudo=texto,
            coordenadas=candidato.coordenadas,
            etiqueta_geocodificada="",
            confianza=candidato.confianza,
            estado=ESTADO_REVISAR,
            motivo=f"GEOCODIFICACION_FUERA_DE_CHILE: {candidato.region}",
            localidad="", region="",
            metodo_confirmacion=metodo_confirmacion_fallback or ("TELEMETRIA_GPS" if corroborado_por_gps else ""),
        )
    etiqueta_final = _etiqueta_geocodificada_o_texto_documental(etiqueta=candidato.etiqueta, texto_documental=texto)
    if candidato.confianza is None or candidato.confianza < UMBRAL_CONFIANZA_MINIMA:
        # Bloque CATCH-UP LOGÍSTICO -- caso real 472044: un ÚNICO
        # candidato con confianza insuficiente (nunca ambiguo -- Pelias
        # sólo resolvió hasta nivel comuna/país) es exactamente el mismo
        # problema que la ambigüedad para efectos del fallback: "sólo si
        # A falla" cubre CUALQUIER forma de que A falle, no sólo la
        # ambigüedad de varios candidatos. Mismas reglas de corroboración
        # que Vía C ya exige en el camino ambiguo (número único +
        # catálogo confirmado o evidencia B1 ya persistida) -- nunca un
        # camino paralelo más permisivo.
        if proveedor_geocodificacion_fallback is not None and (
            fallback_unico := resolver_destino_con_fallback_estructurado(
                texto, proveedor_fallback=proveedor_geocodificacion_fallback,
                destinos_confirmados=destinos_confirmados,
                contexto_evidencia_b1=contexto_evidencia_b1,
            )
        ).resuelto and fallback_unico.candidato is not None:
            candidato = fallback_unico.candidato
            etiqueta_final = _etiqueta_geocodificada_o_texto_documental(
                etiqueta=candidato.etiqueta, texto_documental=texto,
            )
            metodo_confirmacion_fallback = "FALLBACK_ESTRUCTURADO_CORROBORADO"
        else:
            return ResultadoDestinoEntrega(
                despachar_a_crudo=texto,
                coordenadas=candidato.coordenadas,
                etiqueta_geocodificada=etiqueta_final,
                confianza=candidato.confianza,
                estado=ESTADO_REVISAR,
                motivo="CONFIANZA_INSUFICIENTE",
                localidad=candidato.localidad,
                region=candidato.region,
                metodo_confirmacion=metodo_confirmacion_fallback or ("TELEMETRIA_GPS" if corroborado_por_gps else ""),
            )
    return ResultadoDestinoEntrega(
        despachar_a_crudo=texto,
        coordenadas=candidato.coordenadas,
        etiqueta_geocodificada=etiqueta_final,
        confianza=candidato.confianza,
        estado=ESTADO_RESUELTO,
        motivo="",
        localidad=candidato.localidad,
        region=candidato.region,
        metodo_confirmacion=metodo_confirmacion_fallback or ("TELEMETRIA_GPS" if corroborado_por_gps else ""),
    )


def _comunas_territorialmente_compatibles(comuna_documental: str, comuna_geocodificada: str) -> bool:
    """Bloque TERRITORIAL T1 -- caso real 472238/472239 (VISTA CLARA 2351
    CERRILLOS): "Santiago" se usa a menudo -- tanto en el propio
    documento como en la respuesta del geocodificador -- como etiqueta
    de CIUDAD/ÁREA METROPOLITANA, no como la comuna específica "Santiago"
    (Región Metropolitana también tiene una comuna con ese nombre exacto,
    lo que agrava la confusión). Que un lado diga "Cerrillos" y el otro
    "Santiago" NO es una contradicción real -- son dos niveles
    territoriales distintos describiendo el mismo lugar, mientras ambos
    pertenezcan a la misma región. Reutiliza el catálogo territorial ya
    existente (`normalizar_comuna`, comuna -> región) -- nunca una lista
    propia de "comunas del Gran Santiago" a mantener aparte. Cualquier
    otra discrepancia entre dos comunas reales (regiones distintas, o
    misma región sin que ninguna sea "Santiago") sigue siendo una
    contradicción real -- caso real 460807: "San Bernardo" vs "Angol"
    (regiones distintas, ninguna es "Santiago") sigue bloqueada."""
    documental = normalizar_comuna(comuna_documental)
    geocodificada = normalizar_comuna(comuna_geocodificada)
    if (
        documental.estado != ESTADO_COMUNA_EXACTA or geocodificada.estado != ESTADO_COMUNA_EXACTA
        or documental.region != geocodificada.region
    ):
        return False
    return "SANTIAGO" in (
        _texto_normalizado_sin_acentos(documental.comuna or "").upper(),
        _texto_normalizado_sin_acentos(geocodificada.comuna or "").upper(),
    )


def resolver_destino_entrega_validado(
    despachar_a_crudo: str | None,
    proveedor_geocodificacion: ProveedorRutas,
    *,
    contexto_territorial: str = "Chile",
    punto_gps_referencia: Coordenadas | None = None,
    radio_gps_km: float = 50.0,
    destinos_confirmados: Iterable[Destino] = (),
    proveedor_geocodificacion_fallback: ProveedorRutas | None = None,
    contexto_evidencia_b1: str = "",
) -> ResultadoDestinoEntrega:
    """Bloque F (destinos degradados/absurdos) -- igual que
    `resolver_destino_entrega`, con una validación adicional: un resultado
    RESUELTO nunca se acepta sólo porque el proveedor respondió con
    confianza suficiente, se contrasta contra la evidencia documental
    disponible. Si el propio `despachar_a_crudo` menciona de forma
    INEQUÍVOCA (`_comuna_documental_inequivoca` -- exactamente una comuna
    real distinta identificada, nunca varias en conflicto; ver su
    docstring, caso real 472002 "GALVARINO 8501 QUILICURA") una comuna del
    catálogo territorial cerrado (345 comunas/16 regiones, sin fuzzy) que
    CONTRADICE la localidad devuelta por el geocodificador -- caso real
    460807: el documento dice "SAN BERNARDO" dos veces, sin ninguna otra
    comuna mencionada, el proveedor devolvió "Angol, La Araucanía" -- se
    rechaza (`REVISAR`/`GEOCODIFICACION_CONTRADICE_COMUNA_DOCUMENTAL`)
    ANTES de calcular ninguna ruta, en vez de calcularla y descartarla
    después. Coordenadas/confianza se conservan como evidencia técnica de
    auditoría; etiqueta/localidad/región del destino rechazado NUNCA se
    exponen -- nunca aceptar un destino degradado sólo porque hubo alguna
    respuesta. Sin mención inequívoca de comuna en el texto (ausente, o
    ambigua entre dos comunas reales), no hay evidencia documental segura
    con la que contradecir -- se acepta igual que antes (nunca fabrica
    evidencia donde no la hay, ni arriesga un falso rechazo por una
    ambigüedad léxica del propio catálogo territorial)."""
    resultado = resolver_destino_entrega(
        despachar_a_crudo, proveedor_geocodificacion,
        contexto_territorial=contexto_territorial,
        punto_gps_referencia=punto_gps_referencia, radio_gps_km=radio_gps_km,
        destinos_confirmados=destinos_confirmados,
        proveedor_geocodificacion_fallback=proveedor_geocodificacion_fallback,
        contexto_evidencia_b1=contexto_evidencia_b1,
    )
    if resultado.estado != ESTADO_RESUELTO:
        return resultado
    comuna_documental = _comuna_documental_inequivoca(despachar_a_crudo or "")
    if (
        comuna_documental and resultado.localidad
        and _texto_normalizado_sin_acentos(comuna_documental)
        != _texto_normalizado_sin_acentos(resultado.localidad)
        and not _comunas_territorialmente_compatibles(comuna_documental, resultado.localidad)
    ):
        return ResultadoDestinoEntrega(
            despachar_a_crudo=resultado.despachar_a_crudo,
            coordenadas=resultado.coordenadas,
            etiqueta_geocodificada="",
            confianza=resultado.confianza,
            estado=ESTADO_REVISAR,
            motivo=(
                "GEOCODIFICACION_CONTRADICE_COMUNA_DOCUMENTAL: "
                f"{comuna_documental} != {resultado.localidad}"
            ),
            localidad="", region="",
            metodo_confirmacion=resultado.metodo_confirmacion,
        )
    return resultado


CAMPOS_RESULTADO_RUTA_ENTREGA = (
    "planta_origen_id", "planta_origen_nombre",
    "despachar_a_crudo", "direccion_entrega_geocodificada",
    "localidad_entrega", "region_entrega",
    "longitud_entrega", "latitud_entrega", "confianza_geocodificacion",
    "distancia_km", "duracion_min",
    "proveedor_ruta", "estado_ruta", "motivo_ruta",
    "origen_determinado_por", "evidencia_origen",
    "metodo_confirmacion_destino",
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
    metodo_confirmacion_destino: str = ""

    def a_dict(self) -> dict[str, str]:
        return asdict(self)


def _reintentar_ruta_sin_acceso_vial_con_destino_confirmado(
    *,
    ruta: "ResultadoRuta",
    entrega: ResultadoDestinoEntrega,
    coordenada_origen: Coordenadas,
    proveedor_rutas: ProveedorRutas,
    perfil: str,
    despachar_a_crudo: str,
    destinos_confirmados: Iterable[Destino],
    proveedor_geocodificacion_fallback: ProveedorRutas | None = None,
    contexto_evidencia_b1: str = "",
) -> tuple["ResultadoRuta", ResultadoDestinoEntrega]:
    """Bloque RESOLUCIÓN R16 -- Parte F (`SIN_ACCESO_VIAL`): investigado
    contra 3 casos reales (472044/472073/472163) -- el punto que ORS
    rechaza casi nunca es "la calle no existe": el geocodificador no
    encontró coincidencia a nivel de calle y devolvió sólo un centroide
    de comuna (confianza baja, sin número de calle), que efectivamente
    puede caer sin ningún acceso vial cercano. Si existe un destino ya
    CONFIRMADO (evidencia humana o externa previa -- nunca un candidato
    nuevo, nunca inventado aquí) cuya dirección coincide LITERALMENTE con
    el texto documental (mismo criterio exacto que Vía A,
    `_destino_confirmado_coincide_texto`) y cuyas coordenadas son
    DISTINTAS del centroide que falló, se reintenta el ruteo desde ese
    punto ya confirmado. Si el reintento también falla, o no hay ningún
    destino confirmado que coincida, `SIN_ACCESO_VIAL` se conserva con su
    causa explícita -- nunca se inventa un snap vial ni una coordenada."""
    if ruta.estado != EstadoRuta.SIN_ACCESO_VIAL or entrega.coordenadas is None:
        return ruta, entrega
    texto = str(despachar_a_crudo or "")
    for destino in destinos_confirmados:
        if destino.estado_calidad != "CONFIRMADO" or destino.estado_vigencia != "ACTIVO":
            continue
        if destino.latitud is None or destino.longitud is None:
            continue
        if not _destino_confirmado_coincide_texto(destino, texto):
            continue
        coordenada_confirmada = Coordenadas(destino.longitud, destino.latitud)
        if distancia_km_haversine(coordenada_confirmada, entrega.coordenadas) <= MARGEN_MISMO_LUGAR_KM:
            continue  # mismo punto que ya falló -- no aporta evidencia nueva
        ruta_reintentada = proveedor_rutas.calcular_ruta(coordenada_origen, coordenada_confirmada, perfil)
        if ruta_reintentada.estado == EstadoRuta.RUTA_CALCULADA:
            entrega_actualizada = replace(
                entrega,
                coordenadas=coordenada_confirmada,
                etiqueta_geocodificada=destino.direccion or entrega.etiqueta_geocodificada,
                localidad=destino.comuna or entrega.localidad,
                region=destino.region or entrega.region,
                metodo_confirmacion="CATALOGO_CONFIRMADO_SIN_ACCESO_VIAL",
            )
            return ruta_reintentada, entrega_actualizada
    # Bloque CATCH-UP LOGÍSTICO -- caso real 472073 (PDTE. RIESCO 5903 LAS
    # CONDES): un destino ya CONFIRMADO puede traer comuna/región propias
    # pero SIN coordenadas (Bloque CONFIRMACIÓN D2 -- se confirmó sin que
    # la ruta llegara a calcularse) -- el bucle de arriba nunca puede
    # usarlo (exige `latitud`/`longitud` ya presentes). Mismo mecanismo
    # que ya resolvió 472037 (Vía C, mismas reglas de corroboración
    # -- catálogo confirmado con comuna, o evidencia B1 ya persistida) --
    # reutilizado aquí, nunca una ruta paralela nueva.
    if proveedor_geocodificacion_fallback is not None:
        fallback = resolver_destino_con_fallback_estructurado(
            texto, proveedor_fallback=proveedor_geocodificacion_fallback,
            destinos_confirmados=destinos_confirmados, contexto_evidencia_b1=contexto_evidencia_b1,
        )
        if (
            fallback.resuelto and fallback.candidato is not None
            and distancia_km_haversine(fallback.candidato.coordenadas, entrega.coordenadas) > MARGEN_MISMO_LUGAR_KM
        ):
            ruta_reintentada = proveedor_rutas.calcular_ruta(
                coordenada_origen, fallback.candidato.coordenadas, perfil,
            )
            if ruta_reintentada.estado == EstadoRuta.RUTA_CALCULADA:
                entrega_actualizada = replace(
                    entrega,
                    coordenadas=fallback.candidato.coordenadas,
                    etiqueta_geocodificada=_etiqueta_geocodificada_o_texto_documental(
                        etiqueta=fallback.candidato.etiqueta, texto_documental=texto,
                    ),
                    localidad=fallback.candidato.localidad or entrega.localidad,
                    region=fallback.candidato.region or entrega.region,
                    metodo_confirmacion="FALLBACK_ESTRUCTURADO_SIN_ACCESO_VIAL",
                )
                return ruta_reintentada, entrega_actualizada
    return ruta, entrega


def calcular_ruta_con_planta_conocida(
    *,
    planta: Planta,
    despachar_a_crudo: str,
    proveedor_rutas: ProveedorRutas,
    origen_determinado_por: str = "TELEMETRIA_GPS",
    evidencia_origen: str = "",
    perfil: str = "driving-hgv",
    punto_gps_destino: Coordenadas | None = None,
    radio_gps_destino_km: float = 50.0,
    destinos_confirmados: Iterable[Destino] = (),
    proveedor_geocodificacion_fallback: ProveedorRutas | None = None,
    contexto_evidencia_b1: str = "",
) -> ResultadoRutaEntrega:
    """Bloque OPERACIÓN REAL R1 -- calcula PLANTA ORIGEN -> DESPACHAR A
    cuando la planta YA se conoce con certeza (p. ej. confirmada por GPS)
    y no hace falta -- ni conviene -- volver a derivarla documentalmente
    (`resolver_planta_origen` no sirve aquí: el encabezado de la guía
    siempre menciona la misma planta matriz, sin importar desde cuál
    despachó realmente el camión -- ver `calcular_ruta_entrega_para_viaje`,
    que SÍ deriva la planta, para el camino normal donde no hay
    corroboración GPS todavía). Reutiliza exactamente la misma lógica de
    geocodificación/ORS que `calcular_ruta_entrega_para_viaje` -- solo se
    salta el paso de resolución de origen."""
    coordenada_origen = coordenada_ruteo_planta(planta)
    if coordenada_origen is None:
        return ResultadoRutaEntrega(
            planta_origen_id=planta.planta_id, planta_origen_nombre=planta.nombre,
            estado_ruta=EstadoRuta.ORIGEN_NO_DETERMINADO.value,
            motivo_ruta="PLANTA_SIN_COORDENADAS_EN_CATALOGO",
            origen_determinado_por=origen_determinado_por, evidencia_origen=evidencia_origen,
        )

    entrega = resolver_destino_entrega_validado(
        despachar_a_crudo, proveedor_rutas,
        punto_gps_referencia=punto_gps_destino, radio_gps_km=radio_gps_destino_km,
        destinos_confirmados=destinos_confirmados,
        proveedor_geocodificacion_fallback=proveedor_geocodificacion_fallback,
        contexto_evidencia_b1=contexto_evidencia_b1,
    )
    if entrega.estado != ESTADO_RESUELTO:
        # Bloque F (destinos degradados/absurdos): un destino RECHAZADO
        # (confianza insuficiente, ambiguo, etc.) nunca debe exponerse como
        # si fuera el destino operacional -- antes de este fix,
        # `direccion_entrega_geocodificada`/`localidad`/`region` seguían
        # llevando la etiqueta descartada (p. ej. "Chile" a confianza 0.1)
        # hasta la columna que Desktop muestra como "Destino operacional".
        # Las coordenadas/confianza SÍ se conservan -- son evidencia técnica
        # de auditoría (Fase J), nunca "el destino", y `motivo_ruta` ya
        # explica por qué se descartó.
        return ResultadoRutaEntrega(
            planta_origen_id=planta.planta_id, planta_origen_nombre=planta.nombre,
            despachar_a_crudo=entrega.despachar_a_crudo,
            longitud_entrega=str(entrega.coordenadas.longitud) if entrega.coordenadas else "",
            latitud_entrega=str(entrega.coordenadas.latitud) if entrega.coordenadas else "",
            confianza_geocodificacion=str(entrega.confianza) if entrega.confianza is not None else "",
            estado_ruta=EstadoRuta.REQUIERE_REVISION.value, motivo_ruta=entrega.motivo,
            origen_determinado_por=origen_determinado_por, evidencia_origen=evidencia_origen,
            metodo_confirmacion_destino=entrega.metodo_confirmacion,
        )

    ruta = proveedor_rutas.calcular_ruta(
        coordenada_origen, entrega.coordenadas, perfil
    )
    ruta, entrega = _reintentar_ruta_sin_acceso_vial_con_destino_confirmado(
        ruta=ruta, entrega=entrega, coordenada_origen=coordenada_origen,
        proveedor_rutas=proveedor_rutas, perfil=perfil,
        despachar_a_crudo=despachar_a_crudo, destinos_confirmados=destinos_confirmados,
        proveedor_geocodificacion_fallback=proveedor_geocodificacion_fallback,
        contexto_evidencia_b1=contexto_evidencia_b1,
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
            origen_determinado_por=origen_determinado_por, evidencia_origen=evidencia_origen,
            metodo_confirmacion_destino=entrega.metodo_confirmacion,
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
        origen_determinado_por=origen_determinado_por, evidencia_origen=evidencia_origen,
        metodo_confirmacion_destino=entrega.metodo_confirmacion,
    )


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
    punto_gps_destino: Coordenadas | None = None,
    radio_gps_destino_km: float = 50.0,
    destinos_confirmados: Iterable[Destino] = (),
) -> ResultadoRutaEntrega:
    """Orquesta PLANTA ORIGEN -> DESPACHAR A (Bloque E1). Nunca usa
    `DIRECCION`/`COMUNA`/`COD DESTINATARIO` del cliente como destino de
    ruta -- ver regla de negocio en el docstring del módulo. Un fallo en
    cualquier paso deja campos vacíos y un estado/motivo explicativo --
    nunca lanza, nunca inventa, nunca elige el candidato más cercano a
    una planta AZA.

    `punto_gps_destino` (Bloque TELEMETRÍA T1, opcional): punto final real
    de un recorrido GPS -- quien llama decide cómo obtenerlo (este módulo
    nunca golpea un proveedor de telemetría directamente, ver límites
    multiempresa). Si se entrega, ayuda a descartar candidatos de
    geocodificación territorialmente incompatibles ante ambigüedad (ver
    `resolver_destino_entrega`)."""
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
    coordenada_origen = coordenada_ruteo_planta(planta)
    if coordenada_origen is None:
        return ResultadoRutaEntrega(
            estado_ruta=EstadoRuta.ORIGEN_NO_DETERMINADO.value,
            motivo_ruta="PLANTA_SIN_COORDENADAS_EN_CATALOGO",
        )

    entrega = resolver_destino_entrega_validado(
        despachar_a_crudo, proveedor_rutas,
        punto_gps_referencia=punto_gps_destino, radio_gps_km=radio_gps_destino_km,
        destinos_confirmados=destinos_confirmados,
    )
    if entrega.estado != ESTADO_RESUELTO:
        # Bloque F: coordenadas/confianza SÍ se conservan (evidencia
        # técnica de auditoría, Fase J -- `motivo_ruta` ya explica por qué
        # se descartó), pero la ETIQUETA/localidad/región de un destino
        # RECHAZADO nunca se expone como si fuera el destino operacional --
        # ver `calcular_ruta_con_planta_conocida` (mismo criterio, casos
        # reales 460807/472008: "Angol"/"Chile" a confianza insuficiente o
        # contradiciendo la comuna documental seguían llegando a Desktop).
        return ResultadoRutaEntrega(
            planta_origen_id=planta.planta_id, planta_origen_nombre=planta.nombre,
            despachar_a_crudo=entrega.despachar_a_crudo,
            longitud_entrega=str(entrega.coordenadas.longitud) if entrega.coordenadas else "",
            latitud_entrega=str(entrega.coordenadas.latitud) if entrega.coordenadas else "",
            confianza_geocodificacion=str(entrega.confianza) if entrega.confianza is not None else "",
            estado_ruta=EstadoRuta.REQUIERE_REVISION.value, motivo_ruta=entrega.motivo,
            origen_determinado_por=determinado_por, evidencia_origen=evidencia_origen,
            metodo_confirmacion_destino=entrega.metodo_confirmacion,
        )

    ruta = proveedor_rutas.calcular_ruta(
        coordenada_origen, entrega.coordenadas, perfil
    )
    ruta, entrega = _reintentar_ruta_sin_acceso_vial_con_destino_confirmado(
        ruta=ruta, entrega=entrega, coordenada_origen=coordenada_origen,
        proveedor_rutas=proveedor_rutas, perfil=perfil,
        despachar_a_crudo=despachar_a_crudo, destinos_confirmados=destinos_confirmados,
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
            metodo_confirmacion_destino=entrega.metodo_confirmacion,
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
        metodo_confirmacion_destino=entrega.metodo_confirmacion,
    )


CAMPOS_ENTREGA_DOCUMENTO = (
    "despachar_a_crudo", "direccion_entrega", "localidad_entrega",
    "region_entrega", "estado_entrega",
    "planta_origen_id", "planta_origen_nombre",
    "origen_determinado_por", "evidencia_origen",
    "distancia_km", "duracion_min", "proveedor_ruta",
    "estado_ruta", "motivo_ruta",
)


_PATRON_NUMERO_DIRECCION = re.compile(r"\d+")


def _texto_candidato_a_comuna(texto: str) -> str:
    """Bloque TERRITORIAL T1 -- causa raíz real de "VICUÑA MACKENNA" leído
    como comuna "Vicuña" (472037): una dirección chilena convencional
    sigue el orden CALLE NÚMERO COMUNA -- la comuna, cuando el documento
    la trae, va DESPUÉS del número. Escanear el texto COMPLETO en busca
    de una comuna (como hacía este módulo antes) trata el nombre de una
    calle como un conjunto de tokens sueltos sin distinguir su posición:
    "Vicuña" es, de forma completamente real, una comuna de la región de
    Coquimbo -- pero aquí es sólo la primera palabra de una calle
    compuesta ("Vicuña Mackenna"), nunca una mención de comuna. Restringir
    la búsqueda al texto que sigue al ÚLTIMO número reconocible excluye
    por construcción el nombre de la calle, sin ninguna lista de nombres
    compuestos que mantener. Sin ningún número reconocible en el texto
    (p. ej. un OCR que fusionó letra y dígitos, caso real 460807
    "O1148" -- igual contiene el dígito "1148", así que esto no lo
    afecta; sólo direcciones verdaderamente sin ningún dígito), se
    conserva el texto completo -- mismo comportamiento de siempre, nunca
    se debilita una protección real por falta de evidencia posicional."""
    coincidencias = list(_PATRON_NUMERO_DIRECCION.finditer(str(texto or "")))
    return texto[coincidencias[-1].end():] if coincidencias else (texto or "")


def _comuna_explicita(texto: str) -> str:
    """Detecta sólo comunas exactas expresadas en la dirección OCR."""
    tokens = re.findall(r"[A-ZÁÉÍÓÚÜÑ]+", _texto_candidato_a_comuna(texto).upper())
    for largo in range(min(4, len(tokens)), 0, -1):
        for inicio in range(len(tokens) - largo + 1):
            resultado = normalizar_comuna(" ".join(tokens[inicio:inicio + largo]))
            if resultado.estado == ESTADO_COMUNA_EXACTA and resultado.comuna:
                return resultado.comuna
    return ""


def _comunas_explicitas(texto: str) -> tuple[str, ...]:
    """Todas las comunas DISTINTAS del catálogo territorial cerrado que
    aparecen como frase exacta en `texto` (sin fuzzy) -- a diferencia de
    `_comuna_explicita` (que se detiene en la primera coincidencia por
    ventana más larga), aquí se recogen TODAS las que aparecen, para
    poder distinguir una mención inequívoca de una genuinamente ambigua
    -- ver `_comuna_documental_inequivoca`. Restringido al texto después
    del último número (ver `_texto_candidato_a_comuna`) -- nunca busca
    comuna dentro del nombre de la calle."""
    tokens = re.findall(r"[A-ZÁÉÍÓÚÜÑ]+", _texto_candidato_a_comuna(texto).upper())
    encontradas: list[str] = []
    for largo in range(min(4, len(tokens)), 0, -1):
        for inicio in range(len(tokens) - largo + 1):
            resultado = normalizar_comuna(" ".join(tokens[inicio:inicio + largo]))
            if resultado.estado == ESTADO_COMUNA_EXACTA and resultado.comuna and resultado.comuna not in encontradas:
                encontradas.append(resultado.comuna)
    return tuple(encontradas)


def _comuna_documental_inequivoca(texto: str) -> str:
    """Bloque F -- una comuna documental sólo sirve como evidencia para
    CONTRADECIR un resultado de geocodificación cuando el texto la
    menciona de forma INEQUÍVOCA: exactamente una comuna real distinta
    identificada, nunca varias en conflicto.

    Caso real 472002 ("GALVARINO 8501 QUILICURA"): "Galvarino" es aquí el
    nombre de la CALLE, no la comuna -- pero también existe una comuna
    real llamada Galvarino (La Araucanía), completamente ajena a este
    documento; "Quilicura" (la comuna real de entrega, ya geocodificada
    correctamente) es la otra mención. Con dos comunas reales en el mismo
    texto, no hay forma determinista y segura de saber cuál es la comuna
    de entrega -- se abstiene (cadena vacía) en vez de arriesgarse a
    rechazar un destino correcto por una ambigüedad léxica del propio
    catálogo territorial (dos comunas reales que comparten nombre con una
    calle). Con una sola comuna mencionada (caso real 460807: "SAN
    BERNARDO" repetido, ninguna otra comuna en el texto), la evidencia sí
    es inequívoca y puede contradecir con seguridad."""
    comunas = _comunas_explicitas(texto)
    return comunas[0] if len(comunas) == 1 else ""


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
    # Bloque F: la contradicción contra la comuna documental (p. ej.
    # "Angol" cuando el documento dice "SAN BERNARDO") ya se valida DENTRO
    # de `calcular_ruta_entrega_para_viaje` -- vía
    # `resolver_destino_entrega_validado`, ANTES de calcular ninguna ruta
    # -- así que `ruta_entrega` ya llega limpia (sin etiqueta/localidad/
    # región cuando hubo contradicción, con `motivo_ruta` explicando por
    # qué). No se repite la regla aquí -- un solo lugar, sin arquitectura
    # paralela.
    return resultado
