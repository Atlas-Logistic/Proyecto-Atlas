"""Adaptador HTTP de Nominatim (OpenStreetMap), inyectable y sin reintentos
automáticos -- Bloque B1 OBSERVADOR + FALLBACK GEOGRÁFICO.

Geocodificador de RESPALDO ESTRUCTURADO (nunca scraping, nunca una lista
de fuentes web): se consulta SÓLO cuando el proveedor PRINCIPAL
(`OpenRouteService`) deja una dirección ambigua/sin resolver, ANTES de
escalar a investigación B1 compleja (Javier, Bloque D: "Sólo después: B1
investigación compleja"). Estructurado por diseño -- devuelve calle,
número, comuna/localidad, región, país y coordenadas ya separados
(`address.*` de la API pública de Nominatim), nunca texto libre a
parsear con regex propio.

Sin credencial (servicio público) -- el único requisito real es un
`User-Agent` identificable (política de uso de Nominatim: cualquier
consulta sin uno puede ser bloqueada). `pais` restringe la búsqueda al
código ISO de país (mismo criterio que ya usa `OpenRouteService(pais=...)`
-- nunca sin restricción territorial en producción)."""

from __future__ import annotations

import json
import os
import re
import socket
from dataclasses import dataclass
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from atlas_core.rutas.modelos import (
    CandidatoGeocodificacion,
    Coordenadas,
    EstadoRuta,
    ResultadoGeocodificacion,
    ResultadoRuta,
)
from atlas_core.territorio_chile import ESTADO_COMUNA_EXACTA, normalizar_comuna

# Confianza asignada a un candidato de RESPALDO -- deliberadamente fija,
# nunca derivada de `importance` (ese campo de Nominatim mide notoriedad
# de la entidad OSM, no certeza de geocodificación -- un número de casa
# real tiene "importance" naturalmente bajísimo aunque esté bien
# ubicado; usarlo como confianza produciría falsos rechazos). La
# desambiguación real (Vía C, `destino_entrega.
# resolver_destino_con_fallback_estructurado`) ya exige, ANTES de llegar
# aquí, número de calle único + corroboración territorial contra un
# destino CONFIRMADO -- esta confianza sólo necesita superar el umbral
# genérico de aceptación (`UMBRAL_CONFIANZA_MINIMA`), no reemplazar esa
# verificación.
CONFIANZA_CON_NUMERO_DE_CALLE = 0.9
CONFIANZA_SIN_NUMERO_DE_CALLE = 0.2

USER_AGENT_PREDETERMINADO = "AtlasViajes/1.0 (uso operacional interno; geocodificacion de respaldo)"


@dataclass(frozen=True)
class RespuestaHTTP:
    estado: int
    cuerpo: bytes


TransporteHTTP = Callable[[Request, float], RespuestaHTTP]


def _transporte_urllib(solicitud: Request, timeout: float) -> RespuestaHTTP:
    with urlopen(solicitud, timeout=timeout) as respuesta:  # nosec: B310 - URL fija del adaptador
        return RespuestaHTTP(respuesta.status, respuesta.read())


def _localidad_y_region(direccion: dict) -> tuple[str, str]:
    """Deriva localidad/región del universo territorial YA cerrado
    (`territorio_chile.normalizar_comuna`) a partir del primer campo de
    `address` de Nominatim que identifique una comuna real (`suburb` ->
    `city_district` -> `city`/`town`/`village`, en ese orden -- el más
    específico primero). Nunca usa `address.state` directamente (formato
    inconsistente, p. ej. "Región Metropolitana de Santiago" vs
    "Metropolitana" -- se deriva SIEMPRE de la comuna, mismo criterio ya
    usado en el resto del módulo). Sin comuna reconocida, ambos campos
    quedan vacíos -- nunca se inventa una."""
    for campo in ("suburb", "city_district", "city", "town", "village"):
        candidato = str(direccion.get(campo, "")).strip()
        if not candidato:
            continue
        resultado = normalizar_comuna(candidato)
        if resultado.estado == ESTADO_COMUNA_EXACTA and resultado.comuna:
            return resultado.comuna, resultado.region
    return "", ""


def _calle_y_comuna(direccion: str) -> tuple[str, str] | None:
    """Intenta separar 'CALLE NUMERO ... COMUNA' de un texto de consulta ya
    construido -- SOLO si puede identificar, con el catálogo territorial
    cerrado (`normalizar_comuna`, EXACTA, nunca fuzzy), una comuna real en
    los ÚLTIMOS 1-3 tokens del texto (convención habitual de direcciones
    chilenas: la comuna va al final, p. ej. "PDTE. RIESCO 5903, Las
    Condes, Chile"). Devuelve `(calle, comuna)` o `None` si no hay comuna
    reconocible ahí -- en ese caso `geocodificar` usa la búsqueda libre de
    siempre, nunca fuerza una estructura que no está presente."""
    texto = direccion.split(",")[0].strip()
    tokens = texto.split()
    for largo in (3, 2, 1):
        if len(tokens) <= largo:
            continue
        candidato_comuna = " ".join(tokens[-largo:])
        resultado = normalizar_comuna(candidato_comuna)
        if resultado.estado == ESTADO_COMUNA_EXACTA and resultado.comuna:
            calle = " ".join(tokens[:-largo]).strip()
            if calle:
                return calle, resultado.comuna
    return None


_PATRON_NUMERO_FINAL = re.compile(r"(\d+)\s*$")


def _numero_final(calle: str) -> str:
    """Número de casa al final de `calle`, si lo hay -- misma convención
    ya usada en todo el sistema (el número siempre va al final del
    segmento de calle). Nunca inventa un número, sólo lo lee del texto ya
    presente."""
    coincidencia = _PATRON_NUMERO_FINAL.search(calle.strip())
    return coincidencia.group(1) if coincidencia else ""


class NominatimGeocoder:
    nombre = "nominatim"
    # Bloque CIERRE LOGÍSTICA RESIDUAL -- v2: la consulta ESTRUCTURADA
    # (`_calle_y_comuna`/`_buscar_estructurada_con_reintento`) cambia
    # materialmente qué candidatos devuelve este proveedor para el MISMO
    # texto de entrada (caso real 472073: "v1" había cacheado un
    # `RESULTADO_AMBIGUO` sin número de calle; la lógica nueva sí lo
    # encuentra). La clave de caché
    # (`atlas_core.rutas.cache_geocodificacion._clave`) incluye la
    # versión exactamente para esto -- subirla es lo que fuerza a
    # re-consultar en vez de servir para siempre un resultado obsoleto.
    version = "v2"
    URL_BUSQUEDA = "https://nominatim.openstreetmap.org/search"

    def __init__(
        self,
        *,
        user_agent: str | None = None,
        timeout: float = 10.0,
        transporte: TransporteHTTP = _transporte_urllib,
        pais: str | None = None,
    ) -> None:
        self._user_agent = (user_agent if user_agent is not None else os.getenv(
            "NOMINATIM_USER_AGENT", USER_AGENT_PREDETERMINADO
        )).strip() or USER_AGENT_PREDETERMINADO
        if timeout <= 0:
            raise ValueError("timeout debe ser positivo")
        self.timeout = timeout
        self._transporte = transporte
        self._pais = (pais or "").strip().lower() or None

    def _solicitar(self, solicitud: Request) -> tuple[EstadoRuta | None, object | None]:
        solicitud.add_header("User-Agent", self._user_agent)
        solicitud.add_header("Accept", "application/json")
        try:
            respuesta = self._transporte(solicitud, self.timeout)
        except HTTPError as error:
            if error.code == 429:
                return EstadoRuta.LIMITE_CUOTA, None
            return EstadoRuta.PROVEEDOR_NO_DISPONIBLE, None
        except (TimeoutError, socket.timeout):
            return EstadoRuta.SIN_CONEXION, None
        except (URLError, OSError):
            return EstadoRuta.SIN_CONEXION, None
        if respuesta.estado == 429:
            return EstadoRuta.LIMITE_CUOTA, None
        if not 200 <= respuesta.estado < 300:
            return EstadoRuta.PROVEEDOR_NO_DISPONIBLE, None
        try:
            return None, json.loads(respuesta.cuerpo.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return EstadoRuta.RESPUESTA_INVALIDA, None

    def _consultar(self, parametros: dict) -> tuple[EstadoRuta | None, tuple[CandidatoGeocodificacion, ...] | None]:
        """Ejecuta una consulta ya armada (estructurada o libre) y la
        traduce a candidatos -- nunca decide sola cuál forma de consulta
        usar, sólo la ejecuta."""
        if self._pais:
            parametros = {**parametros, "countrycodes": self._pais}
        url = f"{self.URL_BUSQUEDA}?{urlencode(parametros)}"
        estado, datos = self._solicitar(Request(url, method="GET"))
        if estado:
            return estado, None
        try:
            if not isinstance(datos, list):
                raise TypeError
            candidatos_lista: list[CandidatoGeocodificacion] = []
            for item in datos:
                direccion_item = item.get("address", {}) if isinstance(item.get("address"), dict) else {}
                numero = str(direccion_item.get("house_number", "")).strip()
                calle = str(direccion_item.get("road", "")).strip()
                etiqueta = f"{calle} {numero}".strip() if numero else (calle or str(item.get("display_name", "")).strip())
                localidad, region = _localidad_y_region(direccion_item)
                confianza = CONFIANZA_CON_NUMERO_DE_CALLE if numero else CONFIANZA_SIN_NUMERO_DE_CALLE
                candidatos_lista.append(CandidatoGeocodificacion(
                    Coordenadas(float(item["lon"]), float(item["lat"])),
                    etiqueta, confianza, localidad, region,
                ))
            return None, tuple(candidatos_lista)
        except (KeyError, TypeError, ValueError, IndexError):
            return EstadoRuta.RESPUESTA_INVALIDA, None

    def geocodificar(self, direccion: str) -> ResultadoGeocodificacion:
        if not str(direccion).strip():
            return ResultadoGeocodificacion(
                EstadoRuta.DIRECCION_NO_ENCONTRADA, motivo="DIRECCION_VACIA"
            )
        # Bloque CIERRE LOGÍSTICA RESIDUAL -- casos reales 472073/472163
        # (PDTE. RIESCO 5903 LAS CONDES / VIA MORADA 6480 VITACURA): la
        # búsqueda LIBRE (`q=`, un solo campo de texto) de Nominatim no
        # siempre encuentra el punto exacto -- verificado en vivo: para
        # estas dos direcciones devolvía sólo segmentos de calle SIN
        # número. La búsqueda ESTRUCTURADA (`street=`/`city=`, la misma
        # API pública, un modo de consulta distinto y MÁS preciso cuando
        # se conoce la comuna) SÍ encuentra el número exacto -- verificado
        # en vivo contra las mismas dos direcciones. Se detecta la comuna
        # con el MISMO catálogo territorial cerrado ya usado en todo el
        # sistema (`normalizar_comuna`, nunca fuzzy) -- si no hay comuna
        # reconocible, se usa directamente la búsqueda libre de siempre
        # (comportamiento idéntico a antes de este bloque).
        estructurada = _calle_y_comuna(direccion)
        if estructurada is not None:
            calle, comuna = estructurada
            candidatos_estructurados = self._buscar_estructurada_con_reintento(calle, comuna)
            if candidatos_estructurados is not None:
                return self._resultado_desde_candidatos(candidatos_estructurados)
            # Sin resultado estructurado útil (comuna no cubierta en OSM
            # con ese nivel de detalle, número inexistente, o error
            # técnico) -- se agota también la búsqueda libre antes de
            # rendirse, nunca se abandona tras un solo intento.
        estado, candidatos = self._consultar({
            "q": direccion, "format": "jsonv2", "addressdetails": "1", "limit": "8",
        })
        if estado:
            return ResultadoGeocodificacion(estado, motivo=estado.value)
        return self._resultado_desde_candidatos(candidatos or ())

    def _buscar_estructurada_con_reintento(
        self, calle: str, comuna: str,
    ) -> tuple[CandidatoGeocodificacion, ...] | None:
        """Bloque CIERRE LOGÍSTICA RESIDUAL -- caso real 472073 (PDTE.
        RIESCO 5903 LAS CONDES): verificado en vivo que la consulta
        estructurada con la calle COMPLETA a veces no encuentra el número
        exacto cuando el texto documental usa una forma abreviada
        ("PDTE." en vez de "Presidente") que el índice de Nominatim no
        reconoce como equivalente -- pero la MISMA consulta SÍ lo
        encuentra si se reduce el texto a sus últimas palabras ("RIESCO
        5903" ya alcanza un único resultado exacto). Nunca inventa un
        nombre de calle nuevo -- sólo prueba subconjuntos cada vez más
        cortos del mismo texto documental ya presente, de derecha a
        izquierda (el número siempre va al final; la parte que sobra al
        principio es la que puede estar abreviada o ser prescindible).
        Se detiene en el primer intento que produce un único candidato
        con el número buscado -- nunca elige entre varios named a ciegas.
        Devuelve `None` si ningún intento estructurado fue útil."""
        numero = _numero_final(calle)
        tokens = calle.split()
        for inicio in range(len(tokens)):
            calle_intento = " ".join(tokens[inicio:]).strip()
            if not calle_intento:
                continue
            estado, candidatos = self._consultar({
                "street": calle_intento, "city": comuna, "format": "jsonv2",
                "addressdetails": "1", "limit": "8",
            })
            if estado is not None or not candidatos:
                continue
            if numero:
                candidatos = tuple(c for c in candidatos if numero in c.etiqueta)
            if len(candidatos) == 1:
                return candidatos
        return None

    def _resultado_desde_candidatos(
        self, candidatos: tuple[CandidatoGeocodificacion, ...],
    ) -> ResultadoGeocodificacion:
        if not candidatos:
            return ResultadoGeocodificacion(
                EstadoRuta.DIRECCION_NO_ENCONTRADA, motivo="SIN_CANDIDATOS"
            )
        if len(candidatos) > 1:
            return ResultadoGeocodificacion(
                EstadoRuta.RESULTADO_AMBIGUO, candidatos, "MULTIPLES_CANDIDATOS"
            )
        return ResultadoGeocodificacion(
            EstadoRuta.REQUIERE_REVISION, candidatos, "REQUIERE_CONFIRMACION_HUMANA"
        )

    def calcular_ruta(self, origen: Coordenadas, destino: Coordenadas, perfil: str) -> ResultadoRuta:
        """Nominatim es SÓLO geocodificador de respaldo -- nunca calcula
        rutas (eso sigue siendo responsabilidad exclusiva de
        `OpenRouteService`, el único proveedor de ruteo del sistema).
        Este método existe únicamente para cumplir el protocolo
        `ProveedorRutas` -- ningún camino del pipeline lo invoca."""
        return ResultadoRuta(EstadoRuta.PROVEEDOR_NO_DISPONIBLE, motivo="NOMINATIM_NO_CALCULA_RUTAS")
