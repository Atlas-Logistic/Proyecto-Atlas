"""Catálogo Maestro de Destinos asociado al Catálogo Maestro de Clientes."""

from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Callable, Iterable
from uuid import uuid4

from atlas_core.almacenamiento_portable import bloqueo_sesion
from atlas_core.geografia import texto_normalizado
from atlas_core.catalogo_clientes import (
    CatalogoClientes,
    ClienteNoEncontradoError,
    EstadoVigenciaCliente,
)


VERSION_FORMATO = 1
# Bloque CONSISTENCIA OPERACIONAL -- lock físico propio de este catálogo
# (mismo patrón ya establecido para obras_destinos/vehículos/evidencia/
# incidencias/clientes). `crear_o_reutilizar_global` NO lo adquiere
# directamente -- delega enteramente en `editar`/`crear` (que sí lo
# adquieren cada uno), evitando una reentrada del mismo lock no
# reentrante.
NOMBRE_LOCK_CATALOGO_DESTINOS = "catalogo_destinos"


class ErrorCatalogoDestinos(ValueError):
    """Error base del catálogo de destinos."""


class DestinoNoEncontradoError(ErrorCatalogoDestinos):
    """El destino solicitado no existe."""


class DestinoDuplicadoError(ErrorCatalogoDestinos):
    """Ya existe un destino con la misma identidad dentro del cliente."""


class AliasDestinoDuplicadoError(ErrorCatalogoDestinos):
    """El alias ya pertenece a un destino del mismo cliente."""


class ClienteDestinoInvalidoError(ErrorCatalogoDestinos):
    """El cliente asociado no existe o no está activo."""


class CatalogoDestinosCorruptoError(ErrorCatalogoDestinos):
    """El archivo no cumple el contrato del Catálogo Maestro de Destinos."""


class ModificacionDestinoProtegidaError(ErrorCatalogoDestinos):
    """Un destino confirmado requiere una operación manual explícita."""


class EstadoCalidadDestino(str, Enum):
    PENDIENTE = "PENDIENTE"
    CONFIRMADO = "CONFIRMADO"
    REQUIERE_REVISION = "REQUIERE_REVISION"


class EstadoVigenciaDestino(str, Enum):
    ACTIVO = "ACTIVO"
    INACTIVO = "INACTIVO"


class EstadoBusquedaDestino(str, Enum):
    COINCIDENCIA = "COINCIDENCIA"
    SIN_COINCIDENCIA = "SIN_COINCIDENCIA"
    AMBIGUA = "AMBIGUA"


@dataclass(frozen=True)
class ResultadoBusquedaDestino:
    estado: EstadoBusquedaDestino
    destino: "Destino | None" = None
    cantidad_coincidencias: int = 0


def normalizar_nombre_destino(nombre: str) -> str:
    """Normaliza para comparación exacta sin modificar el texto original."""
    return texto_normalizado(nombre)


def _texto_direccion_normalizado(texto: str) -> str:
    return normalizar_nombre_destino(texto)


# Bloque REUTILIZACIÓN DE DESTINO CONFIRMADO CON TOLERANCIA OCR -- caso
# real 472444 (obra "EMPRESA CONST SIGRO", cliente PRODALAM SA): la
# dirección "AVDA IRARRAZAVAL 5497 SANTIAGO NUNOA" ya está CONFIRMADA
# dos veces por Javier (guías 464550, 472227 -- ver `obras_destinos.
# json`), pero la guía 472444 la imprime con un único carácter OCR mal
# leído ("IRABRAZAVAL", R/B visualmente parecidas en el documento
# escaneado). Antes de este bloque, todos los sitios que reutilizan un
# destino ya confirmado (`decisiones_pendientes.py`,
# `procesamiento_masivo.py`, `revalidacion_documental.py`) exigían que
# la calle confirmada apareciera LITERALMENTE dentro del texto
# documental -- un solo carácter distinto bastaba para que Atlas tratara
# una dirección ya conocida como si fuera nueva y generara una revisión
# humana redundante para corregir un typo de OCR, exactamente lo que la
# Sección "normalización contextual antes de preguntar" pide evitar.
#
# La tolerancia sigue siendo deliberadamente estrecha -- nunca "fuzzy
# matching" general (ver comentarios "nunca fuzzy" repetidos en los
# sitios de llamada): sólo sustitución de caracteres en la MISMA
# posición/longitud (nunca inserción ni eliminación, que reordenarían la
# comparación y arriesgarían confundir dos calles reales distintas), y
# sólo quedó habilitada a partir de una longitud mínima -- un fragmento
# corto (p. ej. un número de calle o una palabra corta ambigua) exige
# coincidencia exacta como siempre.
_LONGITUD_MINIMA_TOLERANCIA_OCR_DIRECCION = 10


def _limite_tolerancia_ocr_direccion(longitud: int) -> int:
    """Cantidad máxima de caracteres que pueden diferir por error OCR al
    comparar una calle ya confirmada contra el texto documental de una
    guía nueva -- ver bloque arriba. Escala con la longitud del
    fragmento (una sustitución cada ~25 caracteres, tope 2) porque a
    mayor longitud una coincidencia accidental con una calle real
    distinta es cada vez menos probable; por debajo del mínimo, cero
    tolerancia (coincidencia exacta, comportamiento previo intacto)."""
    if longitud < _LONGITUD_MINIMA_TOLERANCIA_OCR_DIRECCION:
        return 0
    return 1 if longitud <= 25 else 2


_TOKENS_ESTRUCTURALES_DIRECCION = frozenset({
    "CALLE", "AVENIDA", "AV", "AVDA", "CAMINO", "PASAJE", "RUTA", "LOTE", "SITIO", "PARCELA", "KM",
})


def _tokens_direccion(texto: str) -> list[str]:
    return re.findall(r"[A-Z]+|\d+", texto)


def _distancia_edicion_acotada(a: str, b: str, limite: int) -> int:
    """Distancia de edici?n de un token, cortada al l?mite pedido.

    Se usa s?lo sobre UN token largo dentro de una direcci?n ya anclada;
    no es una b?squeda aproximada entre direcciones.
    """
    if abs(len(a) - len(b)) > limite:
        return limite + 1
    anterior = list(range(len(b) + 1))
    for i, caracter_a in enumerate(a, 1):
        actual = [i]
        for j, caracter_b in enumerate(b, 1):
            actual.append(min(anterior[j] + 1, actual[j - 1] + 1, anterior[j - 1] + (caracter_a != caracter_b)))
        if min(actual) > limite:
            return limite + 1
        anterior = actual
    return anterior[-1]


def _token_ocr_limitado(coincidente: str, documental: str) -> bool:
    """Admite UN token no estructural truncado o con error OCR peque?o.

    La variante documental debe conservar al menos seis caracteres y puede
    omitir hasta cuatro del final. Sobre ese prefijo la edici?n queda
    acotada a dos operaciones, suficiente para un truncamiento con lectura
    desplazada, sin habilitar semejanza libre.
    """
    if len(coincidente) < 6 or len(documental) < 6:
        return False
    if len(documental) > len(coincidente) or len(coincidente) - len(documental) > 4:
        return False
    return _distancia_edicion_acotada(coincidente[:len(documental)], documental, 2) <= 2


# Caso real 480676 (AUSIN SAN BERNARDO): la numeración "01148" quedó
# confirmada como "O1148" (letra O inicial leída por OCR en 460807), y el
# tokenizador parte "O1148" en O + 1148 -- las anclas numéricas nunca
# coincidían con "01148". Sólo un token completo "O<dígitos>" se lee como
# "0<dígitos>"; nunca otra letra, nunca una O suelta ni dentro de palabra.
# Caso real 475036/475040 (PRODALAM SA TALCAHUANO): destino confirmado
# "AMERICO VESPUCIO 73O" (O final) vs documental "730" -- la O puede ir en
# cualquier posición de un token completo formado sólo por dígitos y O,
# siempre que tenga al menos un dígito.
_NUMERACION_CON_O_INICIAL = re.compile(r"\b(?=[\dO]*\d)[\dO]*O[\dO]*\b")


def _numeracion_o_como_cero(texto: str) -> str:
    return _NUMERACION_CON_O_INICIAL.sub(lambda coincidencia: coincidencia.group(0).replace("O", "0"), texto)


def _coincide_con_numeracion_o_cero(calle: str, texto: str) -> bool:
    """Misma dirección salvo la O inicial de una numeración leída como 0.

    Exige la calle confirmada COMPLETA, token por token y contigua, dentro
    del texto documental tras la sustitución (nunca subcadena: "01148" no
    coincide con "011489"), con al menos un número y un nombre de vía: no
    hay otra tolerancia encima.
    """
    calle_variante = _numeracion_o_como_cero(calle)
    texto_variante = _numeracion_o_como_cero(texto)
    if calle_variante == calle and texto_variante == texto:
        return False
    tokens = _tokens_direccion(calle_variante)
    if not any(token.isdigit() for token in tokens):
        return False
    if not any(len(token) >= 3 and token not in _TOKENS_ESTRUCTURALES_DIRECCION for token in tokens if token.isalpha()):
        return False
    tokens_texto = _tokens_direccion(texto_variante)
    return any(
        tokens_texto[inicio:inicio + len(tokens)] == tokens
        for inicio in range(len(tokens_texto) - len(tokens) + 1)
    )


def _anclas_fuertes_conservadas(calle: str, texto: str, comuna_confirmada: str) -> bool:
    tokens_calle = _tokens_direccion(calle)
    tokens_texto = _tokens_direccion(texto)
    # N?meros (incluidos lote/sitio) son anclas inviolables: nunca se tolera
    # una sustituci?n de d?gito ni se acepta que falte uno del maestro.
    numeros_calle = [t for t in tokens_calle if t.isdigit()]
    numeros_texto = [t for t in tokens_texto if t.isdigit()]
    if numeros_calle and any(n not in numeros_texto for n in numeros_calle):
        return False
    # Palabras que describen la estructura f?sica tampoco pueden ser OCR
    # tolerante: CALLE/LOTE/PARCELA son evidencia, no decoraci?n nominal.
    estructurales = set(tokens_calle) & _TOKENS_ESTRUCTURALES_DIRECCION
    if not estructurales.issubset(set(tokens_texto)):
        return False
    comuna = normalizar_nombre_destino(comuna_confirmada)
    return not comuna or comuna in texto


def direccion_confirmada_coincide(
    calle_confirmada: str, texto_documental: str, *, comuna_confirmada: str = "",
) -> bool:
    """Corroboraci?n estructurada, conservadora y sin fuzzy matching libre.

    Conserva todas las anclas num?ricas y estructurales. Fuera de ellas admite
    s?lo un token largo, no estructural, con un typo OCR de un car?cter o un
    truncamiento/prefijo corto. La comuna se exige cuando el llamador aporta
    una comuna confirmada. La selecci?n entre varios destinos sigue siendo
    responsabilidad del llamador: m?s de una coincidencia debe abstenerse.
    """
    calle = normalizar_nombre_destino(calle_confirmada)
    texto = normalizar_nombre_destino(texto_documental)
    if not calle or not texto:
        return False
    if calle in texto:
        return True
    if _coincide_con_numeracion_o_cero(calle, texto):
        return True
    if not _anclas_fuertes_conservadas(calle, texto, comuna_confirmada):
        return False

    tokens_calle = _tokens_direccion(calle)
    tokens_texto = _tokens_direccion(texto)
    if not tokens_calle:
        return False
    # La tolerancia nunca puede elegir entre numeraciones distintas ni
    # descansar en el nombre de la obra. Exigimos la misma secuencia de
    # números en todo el texto documental y una vía física identificable.
    numeros_calle = [token for token in tokens_calle if token.isdigit()]
    numeros_texto = [token for token in tokens_texto if token.isdigit()]
    if not numeros_calle or numeros_calle != numeros_texto:
        return False
    vias = {"CALLE", "AVENIDA", "AV", "AVDA", "CAMINO", "PASAJE", "RUTA"}
    if not (set(tokens_calle) & vias):
        return False
    if any(token in vias and token not in tokens_calle for token in tokens_texto):
        return False
    # La ?nica tolerancia se aplica dentro de una secuencia completa de la
    # direcci?n maestra. Todo token salvo uno debe ser exacto; los n?meros y
    # las palabras estructurales ya fueron fijados arriba y nunca pasan aqu?.
    for inicio in range(len(tokens_texto) - len(tokens_calle) + 1):
        tolerados = 0
        anclas_exactas = 0
        for maestro, documental in zip(tokens_calle, tokens_texto[inicio:inicio + len(tokens_calle)]):
            if maestro == documental:
                if maestro.isdigit() or maestro in _TOKENS_ESTRUCTURALES_DIRECCION:
                    anclas_exactas += 1
                continue
            if maestro.isdigit() or maestro in _TOKENS_ESTRUCTURALES_DIRECCION:
                break
            if tolerados or not _token_ocr_limitado(maestro, documental):
                break
            tolerados += 1
        else:
            # La v?a tolerante s?lo existe sobre una direcci?n ya anclada,
            # nunca sobre coincidencia nominal de obra/cliente.
            # Un prefijo recortado exige además lote/sitio/parcela y comuna
            # explícita. La sustitución de longitud igual conserva el umbral
            # anterior (vía + número), para no alterar OCR ya corroborado.
            truncado = any(
                a != b and len(b) < len(a)
                for a, b in zip(tokens_calle, tokens_texto[inicio:inicio + len(tokens_calle)])
            )
            anclas_truncamiento = (
                bool(comuna_confirmada)
                and bool(set(tokens_calle) & {"LOTE", "SITIO", "PARCELA"})
                and anclas_exactas >= 3
            )
            if tolerados == 1 and anclas_exactas >= 2 and (not truncado or anclas_truncamiento):
                return True

    # Separaci?n espuria OCR: conserva la conducta previa s?lo con n?meros
    # exactos y las dem?s anclas ya comprobadas; no introduce aproximaci?n.
    calle_compacta = "".join(calle.split())
    texto_compacto = "".join(texto.split())
    return bool(calle_compacta and calle_compacta in texto_compacto)


def clave_fisica_destino(direccion: str, comuna: str = "", region: str = "") -> tuple[str, str, str]:
    """Clave global exacta y conservadora; nunca fuzzy."""
    direccion_n = _texto_direccion_normalizado(direccion)
    if not direccion_n:
        raise ErrorCatalogoDestinos("dirección insuficiente para una identidad física")
    return direccion_n, normalizar_nombre_destino(comuna), normalizar_nombre_destino(region)


def _ahora_utc() -> datetime:
    return datetime.now(timezone.utc)


def _obligatorio(valor: str, campo: str) -> str:
    limpio = str(valor or "").strip()
    if not limpio:
        raise ErrorCatalogoDestinos(f"{campo} es obligatorio")
    return limpio


def _opcional(valor: str | None) -> str:
    return str(valor or "").strip()


def _validar_coordenadas(
    latitud: float | None, longitud: float | None
) -> tuple[float | None, float | None]:
    if (latitud is None) != (longitud is None):
        raise ErrorCatalogoDestinos("latitud y longitud deben informarse juntas")
    if latitud is not None and not -90 <= latitud <= 90:
        raise ErrorCatalogoDestinos("latitud debe estar entre -90 y 90")
    if longitud is not None and not -180 <= longitud <= 180:
        raise ErrorCatalogoDestinos("longitud debe estar entre -180 y 180")
    return latitud, longitud


def _validar_fecha(valor: str, campo: str) -> None:
    try:
        fecha = datetime.fromisoformat(valor)
    except (TypeError, ValueError) as error:
        raise ErrorCatalogoDestinos(f"{campo} debe ser una fecha ISO válida") from error
    if fecha.tzinfo is None:
        raise ErrorCatalogoDestinos(f"{campo} debe incluir zona horaria")


@dataclass(frozen=True)
class Destino:
    destino_id: str
    cliente_id: str
    nombre_destino: str
    nombre_normalizado: str
    codigo_destino: str
    direccion: str
    comuna: str
    region: str
    pais: str
    latitud: float | None
    longitud: float | None
    aliases: tuple[str, ...]
    estado_calidad: str
    estado_vigencia: str
    fuente: str
    observacion: str
    fecha_creacion: str
    fecha_modificacion: str

    def a_dict(self) -> dict[str, object]:
        datos = asdict(self)
        datos["aliases"] = list(self.aliases)
        return datos

    @classmethod
    def desde_dict(cls, datos: object) -> "Destino":
        if not isinstance(datos, dict):
            raise CatalogoDestinosCorruptoError("cada destino debe ser un objeto JSON")
        campos = set(cls.__dataclass_fields__)
        if set(datos) != campos or not isinstance(datos.get("aliases"), list):
            raise CatalogoDestinosCorruptoError("campos de destino incompatibles")
        try:
            destino = cls(**{**datos, "aliases": tuple(datos["aliases"])})
            _validar_destino(destino)
        except (TypeError, ErrorCatalogoDestinos) as error:
            raise CatalogoDestinosCorruptoError(str(error)) from error
        return destino


def _claves_identidad(destino: Destino) -> set[str]:
    return {
        normalizar_nombre_destino(valor)
        for valor in [destino.nombre_destino, *destino.aliases]
        if _opcional(valor)
    }


def _validar_destino(destino: Destino) -> None:
    _obligatorio(destino.destino_id, "destino_id")
    # `cliente_id` queda como procedencia histórica opcional; no es identidad.
    nombre = _obligatorio(destino.nombre_destino, "nombre_destino")
    if destino.nombre_normalizado != normalizar_nombre_destino(nombre):
        raise ErrorCatalogoDestinos("nombre_normalizado no corresponde a nombre_destino")
    _obligatorio(destino.pais, "pais")
    _obligatorio(destino.fuente, "fuente")
    try:
        EstadoCalidadDestino(destino.estado_calidad)
        EstadoVigenciaDestino(destino.estado_vigencia)
    except ValueError as error:
        raise ErrorCatalogoDestinos("estado de calidad o vigencia no permitido") from error
    _validar_coordenadas(destino.latitud, destino.longitud)
    claves_alias = [normalizar_nombre_destino(alias) for alias in destino.aliases]
    if any(not clave for clave in claves_alias):
        raise ErrorCatalogoDestinos("los alias no pueden estar vacíos")
    if len(claves_alias) != len(set(claves_alias)):
        raise ErrorCatalogoDestinos("el destino contiene alias duplicados")
    if destino.nombre_normalizado in claves_alias:
        raise ErrorCatalogoDestinos("un alias no puede duplicar el nombre del destino")
    _validar_fecha(destino.fecha_creacion, "fecha_creacion")
    _validar_fecha(destino.fecha_modificacion, "fecha_modificacion")


class CatalogoDestinos:
    """Administra destinos y valida su cliente al crear o reasignar."""

    def __init__(
        self,
        ruta: str | Path = "catalogos/destinos.json",
        *,
        ruta_clientes: str | Path = "catalogos/clientes.json",
        reloj: Callable[[], datetime] = _ahora_utc,
        generador_id: Callable[[], object] = uuid4,
    ) -> None:
        self.ruta = Path(ruta)
        self.ruta_clientes = Path(ruta_clientes)
        self._reloj = reloj
        self._generador_id = generador_id

    def listar(self, *, cliente_id: str | None = None) -> list[Destino]:
        destinos = self._leer()
        if cliente_id is None:
            return destinos
        buscado = str(cliente_id).strip()
        return [destino for destino in destinos if destino.cliente_id == buscado]

    def obtener(self, destino_id: str) -> Destino:
        destinos = self._leer()
        return destinos[self._indice(destinos, destino_id)]

    def buscar(
        self, texto: str, *, cliente_id: str | None = None
    ) -> ResultadoBusquedaDestino:
        clave = normalizar_nombre_destino(_obligatorio(texto, "texto"))
        destinos = [d for d in self.listar() if d.estado_vigencia == EstadoVigenciaDestino.ACTIVO.value]
        coincidencias = [destino for destino in destinos if clave in _claves_identidad(destino)]
        if len(coincidencias) == 1:
            return ResultadoBusquedaDestino(
                EstadoBusquedaDestino.COINCIDENCIA, coincidencias[0], 1
            )
        if len(coincidencias) > 1:
            return ResultadoBusquedaDestino(
                EstadoBusquedaDestino.AMBIGUA, None, len(coincidencias)
            )
        return ResultadoBusquedaDestino(EstadoBusquedaDestino.SIN_COINCIDENCIA)

    def resolver_direccion_global(self, direccion: str, *, comuna: str = "", region: str = "") -> ResultadoBusquedaDestino:
        clave = clave_fisica_destino(direccion, comuna, region)
        coincidencias = [d for d in self.listar() if d.estado_vigencia == EstadoVigenciaDestino.ACTIVO.value and clave_fisica_destino(d.direccion, d.comuna, d.region) == clave]
        if len(coincidencias) == 1:
            return ResultadoBusquedaDestino(EstadoBusquedaDestino.COINCIDENCIA, coincidencias[0], 1)
        if len(coincidencias) > 1:
            return ResultadoBusquedaDestino(EstadoBusquedaDestino.AMBIGUA, None, len(coincidencias))
        return ResultadoBusquedaDestino(EstadoBusquedaDestino.SIN_COINCIDENCIA)

    def crear_o_reutilizar_global(
        self, *, nombre_destino: str, direccion: str, comuna: str = "", region: str = "",
        pais: str = "CHILE", fuente: str, latitud: float | None = None, longitud: float | None = None,
        estado_calidad: EstadoCalidadDestino | str = EstadoCalidadDestino.PENDIENTE,
    ) -> Destino:
        resuelto = self.resolver_direccion_global(direccion, comuna=comuna, region=region)
        if resuelto.estado == EstadoBusquedaDestino.COINCIDENCIA:
            destino = resuelto.destino
            # Bloque RESOLUCIÓN R16 -- una dirección global ya existente
            # (misma clave física) que un llamador confirma ahora con
            # evidencia humana/externa nueva debe promoverse a CONFIRMADO
            # -- nunca quedarse en PENDIENTE para siempre sólo porque ya
            # existía. Nunca DEGRADA un destino (sólo promueve PENDIENTE/
            # REQUIERE_REVISION -> CONFIRMADO; jamás CONFIRMADO -> otra
            # cosa aquí), y sólo agrega coordenadas cuando el destino
            # existente aún no las tenía -- nunca sobrescribe una
            # coordenada ya presente con una nueva silenciosamente.
            estado_calidad_valor = EstadoCalidadDestino(estado_calidad).value
            necesita_coordenadas = (
                latitud is not None and longitud is not None
                and destino.latitud is None and destino.longitud is None
            )
            if (
                estado_calidad_valor == EstadoCalidadDestino.CONFIRMADO.value
                and destino.estado_calidad != EstadoCalidadDestino.CONFIRMADO.value
            ) or necesita_coordenadas:
                destino = self.editar(
                    destino.destino_id, modificacion_manual=True,
                    estado_calidad=(
                        EstadoCalidadDestino.CONFIRMADO
                        if estado_calidad_valor == EstadoCalidadDestino.CONFIRMADO.value else None
                    ),
                    latitud=latitud if necesita_coordenadas else None,
                    longitud=longitud if necesita_coordenadas else None,
                )
            return destino
        if resuelto.estado == EstadoBusquedaDestino.AMBIGUA:
            raise ErrorCatalogoDestinos("dirección global ambigua")
        return self.crear(
            cliente_id="", nombre_destino=nombre_destino, direccion=direccion, comuna=comuna,
            region=region, pais=pais, fuente=fuente, latitud=latitud, longitud=longitud,
            estado_calidad=estado_calidad,
        )

    def crear(
        self,
        *,
        cliente_id: str,
        nombre_destino: str,
        pais: str,
        fuente: str,
        codigo_destino: str = "",
        direccion: str = "",
        comuna: str = "",
        region: str = "",
        latitud: float | None = None,
        longitud: float | None = None,
        aliases: Iterable[str] = (),
        estado_calidad: EstadoCalidadDestino | str = EstadoCalidadDestino.PENDIENTE,
        observacion: str = "",
    ) -> Destino:
        with bloqueo_sesion(self.ruta.parent, NOMBRE_LOCK_CATALOGO_DESTINOS):
            destinos = self._leer()
            cliente_limpio = self._validar_cliente_activo(cliente_id) if str(cliente_id or "").strip() else ""
            nombre = _obligatorio(nombre_destino, "nombre_destino")
            latitud, longitud = _validar_coordenadas(latitud, longitud)
            instante = self._instante_iso()
            destino = Destino(
                destino_id=str(self._generador_id()),
                cliente_id=cliente_limpio,
                nombre_destino=nombre,
                nombre_normalizado=normalizar_nombre_destino(nombre),
                codigo_destino=_opcional(codigo_destino),
                direccion=_opcional(direccion),
                comuna=_opcional(comuna),
                region=_opcional(region),
                pais=_obligatorio(pais, "pais"),
                latitud=latitud,
                longitud=longitud,
                aliases=tuple(_obligatorio(alias, "alias") for alias in aliases),
                estado_calidad=EstadoCalidadDestino(estado_calidad).value,
                estado_vigencia=EstadoVigenciaDestino.ACTIVO.value,
                fuente=_obligatorio(fuente, "fuente"),
                observacion=_opcional(observacion),
                fecha_creacion=instante,
                fecha_modificacion=instante,
            )
            _validar_destino(destino)
            self._validar_duplicado(destinos, destino)
            destinos.append(destino)
            self._escribir(destinos)
        from atlas_core.revalidacion_reactiva_tecnica import revalidar_tras_cambio_catalogo
        revalidar_tras_cambio_catalogo(self.ruta, destino=destino)
        return destino

    def editar(
        self,
        destino_id: str,
        *,
        modificacion_manual: bool = False,
        cliente_id: str | None = None,
        nombre_destino: str | None = None,
        codigo_destino: str | None = None,
        direccion: str | None = None,
        comuna: str | None = None,
        region: str | None = None,
        pais: str | None = None,
        latitud: float | None = None,
        longitud: float | None = None,
        limpiar_coordenadas: bool = False,
        estado_calidad: EstadoCalidadDestino | str | None = None,
        fuente: str | None = None,
        observacion: str | None = None,
    ) -> Destino:
        with bloqueo_sesion(self.ruta.parent, NOMBRE_LOCK_CATALOGO_DESTINOS):
            destinos = self._leer()
            indice = self._indice(destinos, destino_id)
            actual = destinos[indice]
            self._proteger(actual, modificacion_manual)
            cliente_nuevo = actual.cliente_id if cliente_id is None else (self._validar_cliente_activo(cliente_id) if str(cliente_id).strip() else "")
            nombre = actual.nombre_destino if nombre_destino is None else _obligatorio(nombre_destino, "nombre_destino")
            if limpiar_coordenadas:
                if latitud is not None or longitud is not None:
                    raise ErrorCatalogoDestinos("no combine limpiar_coordenadas con coordenadas")
                latitud_nueva = longitud_nueva = None
            elif latitud is None and longitud is None:
                latitud_nueva, longitud_nueva = actual.latitud, actual.longitud
            else:
                latitud_nueva, longitud_nueva = _validar_coordenadas(latitud, longitud)
            editado = Destino(
                destino_id=actual.destino_id,
                cliente_id=cliente_nuevo,
                nombre_destino=nombre,
                nombre_normalizado=normalizar_nombre_destino(nombre),
                codigo_destino=actual.codigo_destino if codigo_destino is None else _opcional(codigo_destino),
                direccion=actual.direccion if direccion is None else _opcional(direccion),
                comuna=actual.comuna if comuna is None else _opcional(comuna),
                region=actual.region if region is None else _opcional(region),
                pais=actual.pais if pais is None else _obligatorio(pais, "pais"),
                latitud=latitud_nueva,
                longitud=longitud_nueva,
                aliases=actual.aliases,
                estado_calidad=actual.estado_calidad if estado_calidad is None else EstadoCalidadDestino(estado_calidad).value,
                estado_vigencia=actual.estado_vigencia,
                fuente=actual.fuente if fuente is None else _obligatorio(fuente, "fuente"),
                observacion=actual.observacion if observacion is None else _opcional(observacion),
                fecha_creacion=actual.fecha_creacion,
                fecha_modificacion=self._instante_iso(),
            )
            _validar_destino(editado)
            self._validar_duplicado(destinos, editado, excluir_id=actual.destino_id)
            destinos[indice] = editado
            self._escribir(destinos)
        from atlas_core.revalidacion_reactiva_tecnica import revalidar_tras_cambio_catalogo
        revalidar_tras_cambio_catalogo(self.ruta, destino=editado)
        return editado

    def confirmar_coordenada_canonica(
        self, destino_id: str, *, latitud: float, longitud: float,
        actor: str, referencia: str,
    ) -> Destino:
        """Persiste una coordenada sólo por acto explícito y auditable.
        La autoridad queda en los campos ya canónicos del Destino: fuente,
        observación y fecha de modificación; no se crea otro catálogo."""
        actual = self.obtener(destino_id)
        actor = _obligatorio(actor, "actor")
        referencia = _obligatorio(referencia, "referencia")
        nota = (
            "COORDENADA_CANONICA_CONFIRMADA "
            f"actor={actor}; referencia={referencia}; fuente_previa={actual.fuente}"
        )
        return self.editar(
            destino_id, modificacion_manual=True, latitud=latitud, longitud=longitud,
            fuente="COORDENADA_CANONICA_CONFIRMADA", observacion=nota,
        )

    def promover_coordenada_canonica_evidencia_fuerte(
        self, destino_id: str, *, latitud: float, longitud: float,
        proveedor: str, referencia: str,
    ) -> Destino:
        """Persiste sólo una promoción automática previamente evaluada.

        No confirma identidad: exige que el destino ya fuera CONFIRMADO y
        deja una procedencia distinta de la confirmación humana para que la
        auditoría pueda distinguir ambos actos.
        """
        actual = self.obtener(destino_id)
        if actual.estado_calidad != EstadoCalidadDestino.CONFIRMADO.value:
            raise ErrorCatalogoDestinos("un destino no confirmado no puede promover coordenada automática")
        if actual.latitud is not None or actual.longitud is not None:
            raise ErrorCatalogoDestinos("un destino con coordenada existente no puede sobrescribirse automáticamente")
        proveedor = _obligatorio(proveedor, "proveedor")
        referencia = _obligatorio(referencia, "referencia")
        nota = (
            "COORDENADA_CANONICA_EVIDENCIA_FUERTE "
            f"proveedor={proveedor}; referencia={referencia}; fuente_previa={actual.fuente}"
        )
        return self.editar(
            destino_id, modificacion_manual=True, latitud=latitud, longitud=longitud,
            fuente="COORDENADA_CANONICA_EVIDENCIA_FUERTE", observacion=nota,
        )

    def agregar_alias(
        self, destino_id: str, alias: str, *, modificacion_manual: bool = False
    ) -> Destino:
        with bloqueo_sesion(self.ruta.parent, NOMBRE_LOCK_CATALOGO_DESTINOS):
            destinos = self._leer()
            indice = self._indice(destinos, destino_id)
            actual = destinos[indice]
            self._proteger(actual, modificacion_manual)
            editado = replace(
                actual,
                aliases=(*actual.aliases, _obligatorio(alias, "alias")),
                fecha_modificacion=self._instante_iso(),
            )
            _validar_destino(editado)
            self._validar_duplicado(
                destinos, editado, excluir_id=actual.destino_id, error_alias=True
            )
            destinos[indice] = editado
            self._escribir(destinos)
        from atlas_core.revalidacion_reactiva_tecnica import revalidar_tras_cambio_catalogo
        revalidar_tras_cambio_catalogo(self.ruta, destino=editado)
        return editado

    def desactivar(
        self, destino_id: str, *, modificacion_manual: bool = False
    ) -> Destino:
        with bloqueo_sesion(self.ruta.parent, NOMBRE_LOCK_CATALOGO_DESTINOS):
            destinos = self._leer()
            indice = self._indice(destinos, destino_id)
            actual = destinos[indice]
            self._proteger(actual, modificacion_manual)
            if actual.estado_vigencia == EstadoVigenciaDestino.INACTIVO.value:
                return actual
            editado = replace(
                actual,
                estado_vigencia=EstadoVigenciaDestino.INACTIVO.value,
                fecha_modificacion=self._instante_iso(),
            )
            destinos[indice] = editado
            self._escribir(destinos)
            return editado

    def _validar_cliente_activo(self, cliente_id: str) -> str:
        buscado = _obligatorio(cliente_id, "cliente_id")
        try:
            cliente = CatalogoClientes(self.ruta_clientes).obtener(buscado)
        except ClienteNoEncontradoError as error:
            raise ClienteDestinoInvalidoError("cliente_id no existe") from error
        if cliente.estado_vigencia != EstadoVigenciaCliente.ACTIVO.value:
            raise ClienteDestinoInvalidoError("cliente_id está inactivo")
        return cliente.cliente_id

    @staticmethod
    def _proteger(destino: Destino, modificacion_manual: bool) -> None:
        if destino.estado_calidad == EstadoCalidadDestino.CONFIRMADO.value and not modificacion_manual:
            raise ModificacionDestinoProtegidaError(
                "El destino está confirmado; use una modificación manual explícita"
            )

    def _instante_iso(self) -> str:
        instante = self._reloj()
        if instante.tzinfo is None:
            instante = instante.replace(tzinfo=timezone.utc)
        return instante.astimezone(timezone.utc).isoformat()

    def _leer(self) -> list[Destino]:
        if not self.ruta.exists():
            return []
        try:
            with self.ruta.open("r", encoding="utf-8") as archivo:
                contenido = json.load(archivo)
        except (OSError, json.JSONDecodeError) as error:
            raise CatalogoDestinosCorruptoError(f"No se pudo leer el catálogo: {error}") from error
        if not isinstance(contenido, dict) or contenido.get("version_formato") != VERSION_FORMATO:
            raise CatalogoDestinosCorruptoError("raíz o versión de formato no compatible")
        registros = contenido.get("destinos")
        if not isinstance(registros, list):
            raise CatalogoDestinosCorruptoError("destinos debe ser una lista")
        destinos = [Destino.desde_dict(registro) for registro in registros]
        ids = [destino.destino_id for destino in destinos]
        if len(ids) != len(set(ids)):
            raise CatalogoDestinosCorruptoError("el catálogo contiene IDs duplicados")
        try:
            for destino in destinos:
                self._validar_duplicado(destinos, destino, excluir_id=destino.destino_id)
        except ErrorCatalogoDestinos as error:
            raise CatalogoDestinosCorruptoError(str(error)) from error
        return destinos

    def _escribir(self, destinos: Iterable[Destino]) -> None:
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        contenido = {
            "version_formato": VERSION_FORMATO,
            "destinos": [destino.a_dict() for destino in destinos],
        }
        temporal: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", newline="\n", dir=self.ruta.parent,
                prefix=f".{self.ruta.name}.", suffix=".tmp", delete=False,
            ) as archivo:
                temporal = Path(archivo.name)
                json.dump(contenido, archivo, ensure_ascii=False, indent=2)
                archivo.write("\n")
                archivo.flush()
                os.fsync(archivo.fileno())
            os.replace(temporal, self.ruta)
        except OSError:
            if temporal is not None:
                temporal.unlink(missing_ok=True)
            raise

    @staticmethod
    def _indice(destinos: list[Destino], destino_id: str) -> int:
        buscado = str(destino_id or "").strip()
        for indice, destino in enumerate(destinos):
            if destino.destino_id == buscado:
                return indice
        raise DestinoNoEncontradoError(f"No existe el destino {buscado!r}")

    @staticmethod
    def _validar_duplicado(
        destinos: Iterable[Destino], candidato: Destino, *, excluir_id: str | None = None,
        error_alias: bool = False,
    ) -> None:
        for existente in destinos:
            if existente.destino_id == excluir_id:
                continue
            if candidato.estado_vigencia != EstadoVigenciaDestino.ACTIVO.value or existente.estado_vigencia != EstadoVigenciaDestino.ACTIVO.value:
                continue
            # Compatibilidad V1: los nombres/codigos/aliases no pueden chocar
            # dentro de una misma procedencia historica. Entre clientes no
            # definen identidad fisica y una busqueda textual se abstiene.
            if candidato.cliente_id and candidato.cliente_id == existente.cliente_id:
                if _claves_identidad(candidato) & _claves_identidad(existente):
                    error = AliasDestinoDuplicadoError if error_alias else DestinoDuplicadoError
                    raise error("El nombre, codigo o alias ya identifica otro destino")
            if (
                candidato.direccion and existente.direccion
                and _texto_direccion_normalizado(candidato.direccion)
                == _texto_direccion_normalizado(existente.direccion)
                and normalizar_nombre_destino(candidato.comuna)
                == normalizar_nombre_destino(existente.comuna)
                and normalizar_nombre_destino(candidato.region)
                == normalizar_nombre_destino(existente.region)
            ):
                raise DestinoDuplicadoError("La dirección ya pertenece a otro destino global activo")
