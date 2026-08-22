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

from dataclasses import asdict, dataclass
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
    suficientemente fuerte para actuar sin consultar a un humano."""

    resuelto: bool = False
    candidato: CandidatoGeocodificacion | None = None
    motivo: str = ""
    vias: tuple[str, ...] = ()


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
    if len(candidatos_ambiguos) < 2:
        return ResultadoDesambiguacionInequivoca(motivo="NO_ES_UNA_AMBIGUEDAD_REAL")

    texto = str(despachar_a_crudo or "").strip()
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
            motivo="CONFLICTO_ENTRE_DESTINOS_CONFIRMADOS", vias=(VIA_CATALOGO_CONFIRMADO,)
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
            )
        return ResultadoDesambiguacionInequivoca(
            resuelto=True, candidato=candidato_via_a,
            motivo="CATALOGO_CONFIRMADO_Y_GPS_COINCIDEN",
            vias=(VIA_CATALOGO_CONFIRMADO, VIA_GPS_DESCARTA_RIVALES),
        )
    if candidato_via_a is not None:
        return ResultadoDesambiguacionInequivoca(
            resuelto=True, candidato=candidato_via_a,
            motivo="CATALOGO_CONFIRMADO_COINCIDE_GEOCODIFICACION",
            vias=(VIA_CATALOGO_CONFIRMADO,),
        )
    if candidato_via_b is not None:
        return ResultadoDesambiguacionInequivoca(
            resuelto=True, candidato=candidato_via_b,
            motivo="GPS_DESCARTA_TODO_RIVAL_FUERA_DE_RADIO",
            vias=(VIA_GPS_DESCARTA_RIVALES,),
        )
    return ResultadoDesambiguacionInequivoca(motivo="SIN_EVIDENCIA_INEQUIVOCA")


def _mejor_candidato(candidatos: tuple[CandidatoGeocodificacion, ...]) -> CandidatoGeocodificacion:
    """Entre candidatos que ya se determinó que son el mismo lugar real,
    el de mayor confianza informada (nunca el más cercano a ninguna
    referencia externa como una planta AZA)."""
    return max(candidatos, key=lambda c: c.confianza if c.confianza is not None else -1.0)


_PATRON_NUMERO_CALLE = re.compile(r"\b\d{1,6}\b")


def _trae_numero_calle(texto: str) -> bool:
    """Proxy barato y genérico de "tiene una dirección específica" --
    al menos un token numérico de 1-6 dígitos (número de casa/local).
    Nunca depende de un formato fijo ni de nombres de comuna concretos."""
    return bool(_PATRON_NUMERO_CALLE.search(texto))


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


def resolver_destino_entrega(
    despachar_a_crudo: str | None,
    proveedor_geocodificacion: ProveedorRutas,
    *,
    contexto_territorial: str = "Chile",
    punto_gps_referencia: Coordenadas | None = None,
    radio_gps_km: float = 50.0,
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
    """
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
    consulta = (
        f"{texto_geocodificable}, {contexto_territorial}" if contexto_territorial else texto_geocodificable
    )
    resultado = proveedor_geocodificacion.geocodificar(consulta)
    corroborado_por_gps = False

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

    etiqueta_final = _etiqueta_geocodificada_o_texto_documental(etiqueta=candidato.etiqueta, texto_documental=texto)
    if candidato.confianza is None or candidato.confianza < UMBRAL_CONFIANZA_MINIMA:
        return ResultadoDestinoEntrega(
            despachar_a_crudo=texto,
            coordenadas=candidato.coordenadas,
            etiqueta_geocodificada=etiqueta_final,
            confianza=candidato.confianza,
            estado=ESTADO_REVISAR,
            motivo="CONFIANZA_INSUFICIENTE",
            localidad=candidato.localidad,
            region=candidato.region,
            metodo_confirmacion="TELEMETRIA_GPS" if corroborado_por_gps else "",
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
        metodo_confirmacion="TELEMETRIA_GPS" if corroborado_por_gps else "",
    )


def resolver_destino_entrega_validado(
    despachar_a_crudo: str | None,
    proveedor_geocodificacion: ProveedorRutas,
    *,
    contexto_territorial: str = "Chile",
    punto_gps_referencia: Coordenadas | None = None,
    radio_gps_km: float = 50.0,
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
    )
    if resultado.estado != ESTADO_RESUELTO:
        return resultado
    comuna_documental = _comuna_documental_inequivoca(despachar_a_crudo or "")
    if (
        comuna_documental and resultado.localidad
        and _texto_normalizado_sin_acentos(comuna_documental)
        != _texto_normalizado_sin_acentos(resultado.localidad)
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


def _comuna_explicita(texto: str) -> str:
    """Detecta sólo comunas exactas expresadas en la dirección OCR."""
    tokens = re.findall(r"[A-ZÁÉÍÓÚÜÑ]+", str(texto or "").upper())
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
    -- ver `_comuna_documental_inequivoca`."""
    tokens = re.findall(r"[A-ZÁÉÍÓÚÜÑ]+", str(texto or "").upper())
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
