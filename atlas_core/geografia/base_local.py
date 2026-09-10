"""GEOGRAFÍA 2C -- BASE GEOGRÁFICA LOCAL (Región Metropolitana primero).

Conocimiento geográfico PROPIO de Atlas, costo incremental $0: un backend
local, persistente y determinista que responde "¿esta calle + número
existe en esta comuna?" con EVIDENCIA ESTRUCTURADA. Nunca es autoridad
ciega -- es UNA fuente de evidencia más, al mismo nivel que un destino ya
CONFIRMADO o la comuna que el propio documento nombra:

  * NUNCA inventa coordenadas -- una fila sin ``lon``/``lat`` reales
    (situación por defecto mientras no exista un PBF importado) devuelve
    ``coordenadas=None``, jamás un centroide;
  * NUNCA acepta un número distinto -- la única equivalencia numérica es
    la regla segura de ceros a la izquierda ya calibrada en GEOGRAFÍA 2A
    (``"0100" == "100"``, ``"0015" == "15"``; ``"15" != "1545"``);
  * preserva el número TAL CUAL se almacenó (``TEXT``), con sus ceros
    iniciales;
  * funciona aunque el archivo aún no exista (sin PBF descargado):
    ``disponible()`` devuelve ``False`` y toda consulta responde
    ``NO_ENCONTRADO`` con motivo explícito -- nunca un ``crash``.

Distingue el desenlace de matcheo del string -- ``EXACTA`` /
``NORMALIZADA`` / ``MULTIPLE`` / ``NO_ENCONTRADO`` (``EstadoConsultaLocal``)
-- y, encima, el desenlace de ALTO NIVEL para el flujo
(``EvidenciaGeoLocal.resultado``): ``DIRECCION_EXACTA`` (calle + número
confirmados, con coordenada real), ``CALLE_CONOCIDA_NUMERO_NO_EN_BASE``
(la calle existe en la comuna pero ese número no -- NUNCA aporta
coordenada), ``CALLE_NO_ENCONTRADA`` y ``MULTIPLE``.

Preparado para OSM y para el maestro territorial INE sin rediseñar el
Motor: el esquema SQLite trae ``lon``/``lat`` opcionales, ``fuente`` y
(GEOGRAFÍA 2C.3) ``ref_externa`` (gid INE / id OSM, trazabilidad) y
``alias`` (alias INE -- se almacena, NUNCA participa en la resolución)
por fila; cualquier importador offline sólo llama a ``importar_filas``,
que consume el iterable en CHUNKS (millones de filas sin cargar todo en
RAM). El contrato público (``BaseGeograficaLocal``) y ``consultar`` no
cambian.

Lo que ESTE bloque NO hace todavía: interpolar numeración, calcular
centroides, y cablear la base en el primer pase productivo / la
revalidación masiva.
"""
from __future__ import annotations

import math
import re
import sqlite3
from dataclasses import dataclass, field, replace
from enum import Enum
from pathlib import Path
from typing import Iterable, Mapping, Protocol, runtime_checkable

from .modelos import EstadoNormalizacion
from .motor import texto_normalizado

NOMBRE_ARCHIVO_PREDETERMINADO = "base_local_rm.sqlite"
# v2 (GEOGRAFÍA 2C.3): + columnas ``ref_externa`` / ``alias``.
VERSION_ESQUEMA = 2
# Tamaño de lote para la escritura en streaming -- millones de filas
# (maestro INE) sin materializar toda la lista en memoria.
TAMANO_CHUNK_IMPORT = 50_000

# Palabras estructurales de dirección que NO discriminan una calle (una
# consulta "CALLE LOS OLMOS" y un registro "LOS OLMOS" son la misma
# calle). Subconjunto deliberadamente pequeño de las de ``cl.py`` --
# sólo los prefijos de vía que en la práctica se anteponen u omiten.
# Ampliar a formas abreviadas ("AVDA" <-> "AVENIDA") es un bloque 2C
# posterior, no esta base mínima.
_PREFIJOS_ESTRUCTURALES = frozenset({
    "CALLE", "AVENIDA", "AV", "AVDA", "PASAJE", "PJE", "CAMINO", "RUTA",
    "DIAGONAL", "COSTANERA", "ALAMEDA",
})

_PATRON_NUMERO = re.compile(r"\b(\d{1,6})\b")


class EstadoConsultaLocal(str, Enum):
    """Desenlace de una consulta a la base local -- mismo vocabulario
    cerrado que el resto de la autoridad geográfica de Atlas."""

    EXACTA = "EXACTA"
    NORMALIZADA = "NORMALIZADA"
    MULTIPLE = "MULTIPLE"
    NO_ENCONTRADO = "NO_ENCONTRADO"


def numero_equivalente_seguro(a: str, b: str) -> bool:
    """``True`` si ``a`` y ``b`` son el MISMO número de casa bajo la única
    equivalencia segura ya calibrada en GEOGRAFÍA 2A: dos tokens
    PURAMENTE numéricos que sólo difieren en ceros a la izquierda
    (``"0100"`` == ``"100"``, ``"0015"`` == ``"15"``).

    Nunca colapsa valores distintos (``"15"`` != ``"1545"``) ni formas
    alfanuméricas (``"0114B"``). La ausencia de número de un lado NUNCA
    es coincidencia (ausencia != igualdad)."""
    a = str(a or "").strip()
    b = str(b or "").strip()
    if not a or not b:
        return False
    if a == b:
        return True
    if a.isdigit() and b.isdigit():
        return int(a) == int(b)
    return False


@dataclass(frozen=True)
class DireccionLocal:
    """Un registro de la base local -- una calle (y opcionalmente un
    número) dentro de una comuna real."""

    codigo_comuna: str
    comuna_canonica: str
    calle_canonica: str
    calle_normalizada: str
    numero: str = ""            # "" -> la base sólo conoce la calle
    numero_coincide: bool = False   # respecto del número consultado
    # (lon, lat) SÓLO si la fila trae coordenadas reales; None mientras
    # no exista un import OSM/INE -- nunca un centroide sintético.
    coordenadas: tuple[float, float] | None = None
    fuente: str = ""
    # GEOGRAFÍA 2C.3 -- trazabilidad. ``ref_externa``: gid INE / id OSM.
    # ``alias``: alias INE (se conserva, NUNCA se usa para resolver).
    ref_externa: str = ""
    alias: str = ""

    def a_dict(self) -> dict[str, object]:
        return {
            "codigo_comuna": self.codigo_comuna,
            "comuna_canonica": self.comuna_canonica,
            "calle_canonica": self.calle_canonica,
            "calle_normalizada": self.calle_normalizada,
            "numero": self.numero,
            "numero_coincide": self.numero_coincide,
            "longitud": self.coordenadas[0] if self.coordenadas else None,
            "latitud": self.coordenadas[1] if self.coordenadas else None,
            "fuente": self.fuente,
            "ref_externa": self.ref_externa,
            "alias": self.alias,
        }


@dataclass(frozen=True)
class EvidenciaGeoLocal:
    """Evidencia estructurada devuelta por la base local. ``resuelto`` NO
    existe a propósito: la base APORTA evidencia, nunca decide la ruta."""

    estado: EstadoConsultaLocal
    consulta: Mapping[str, str] = field(default_factory=dict)
    candidatos: tuple[DireccionLocal, ...] = ()
    disponible: bool = True
    motivo: str = ""
    codigo_comuna: str = ""

    @property
    def encontrada(self) -> bool:
        """La calle fue reconocida en la comuna (exacta o normalizada).
        ``MULTIPLE`` y ``NO_ENCONTRADO`` no cuentan como reconocimiento
        accionable."""
        return self.estado in (EstadoConsultaLocal.EXACTA, EstadoConsultaLocal.NORMALIZADA)

    @property
    def numero_confirmado(self) -> bool:
        """``True`` SÓLO si hay EXACTAMENTE un candidato y su número
        coincide con el consultado bajo la regla segura -- nunca con
        ``MULTIPLE``, nunca aceptando un número distinto, nunca cuando la
        consulta no traía número."""
        return (
            self.encontrada
            and len(self.candidatos) == 1
            and self.candidatos[0].numero_coincide
        )

    @property
    def calle_conocida(self) -> bool:
        """La calle existe en la comuna (aunque el número no esté). NUNCA
        implica dirección resuelta ni coordenada utilizable."""
        return self.encontrada

    @property
    def resultado(self) -> str:
        """Desenlace de alto nivel, vocabulario cerrado (GEOGRAFÍA 2C.3):
        ``DIRECCION_EXACTA`` / ``CALLE_CONOCIDA_NUMERO_NO_EN_BASE`` /
        ``CALLE_NO_ENCONTRADA`` / ``MULTIPLE`` / ``SIN_DATO``."""
        if self.numero_confirmado:
            return "DIRECCION_EXACTA"
        if self.estado == EstadoConsultaLocal.MULTIPLE:
            return "MULTIPLE"
        if self.encontrada:
            return "CALLE_CONOCIDA_NUMERO_NO_EN_BASE"
        if self.motivo == "CALLE_NO_ENCONTRADA_EN_COMUNA":
            return "CALLE_NO_ENCONTRADA"
        return "SIN_DATO"

    def a_dict(self) -> dict[str, object]:
        return {
            "estado": self.estado.value,
            "resultado": self.resultado,
            "consulta": dict(self.consulta),
            "disponible": self.disponible,
            "motivo": self.motivo,
            "codigo_comuna": self.codigo_comuna,
            "encontrada": self.encontrada,
            "calle_conocida": self.calle_conocida,
            "numero_confirmado": self.numero_confirmado,
            "candidatos": [c.a_dict() for c in self.candidatos],
        }


@runtime_checkable
class BaseGeograficaLocal(Protocol):
    """Contrato para consultar una base geográfica local. Cualquier
    backend (SQLite hoy, un índice derivado de OSM mañana) que cumpla
    esta forma puede participar en el flujo geográfico sin tocar el
    Motor."""

    nombre: str
    version: str

    def disponible(self) -> bool:
        """``True`` sólo si la base existe y tiene al menos una fila --
        nunca lanza."""
        ...

    def consultar(self, *, comuna: str, calle: str, numero: str = "") -> EvidenciaGeoLocal:
        """Evidencia estructurada para ``comuna`` + ``calle`` (+ ``numero``
        opcional). Nunca lanza; nunca inventa coordenadas; nunca acepta un
        número distinto."""
        ...


def _norma_texto(valor: str) -> str:
    return texto_normalizado(valor)


def _sin_prefijo_estructural(calle_normalizada: str) -> str:
    tokens = calle_normalizada.split()
    if len(tokens) >= 2 and tokens[0] in _PREFIJOS_ESTRUCTURALES:
        return " ".join(tokens[1:])
    return calle_normalizada


def _coordenadas_de_fila(lon: object, lat: object) -> tuple[float, float] | None:
    if lon is None or lat is None:
        return None
    try:
        lon_f = float(lon)
        lat_f = float(lat)
    except (TypeError, ValueError):
        return None
    if not (math.isfinite(lon_f) and math.isfinite(lat_f)):
        return None
    return (lon_f, lat_f)


class BaseGeograficaLocalSQLite:
    """Backend SQLite -- persistente, portable y testeable.

    * archivo ausente o vacío -> ``disponible() == False`` y toda consulta
      es ``NO_ENCONTRADO`` (``BASE_LOCAL_NO_PROVISIONADA``);
    * lectura por conexión ``mode=ro`` (uri) -- una consulta JAMÁS crea el
      archivo;
    * ``importar_filas`` es el ÚNICO camino de escritura -- lo usará el
      importador OSM/PBF del próximo bloque sin cambiar nada aquí.
    """

    nombre = "base_local_rm"
    version = f"sqlite-v{VERSION_ESQUEMA}"

    _DDL = (
        "CREATE TABLE IF NOT EXISTS meta ("
        " clave TEXT PRIMARY KEY, valor TEXT NOT NULL);",
        "CREATE TABLE IF NOT EXISTS direcciones ("
        " codigo_comuna     TEXT NOT NULL,"
        " calle_normalizada TEXT NOT NULL,"
        " numero            TEXT NOT NULL DEFAULT '',"
        " calle_canonica    TEXT NOT NULL,"
        " comuna_canonica   TEXT NOT NULL DEFAULT '',"
        " lon               REAL,"
        " lat               REAL,"
        " fuente            TEXT NOT NULL DEFAULT '',"
        " ref_externa       TEXT NOT NULL DEFAULT '',"
        " alias             TEXT NOT NULL DEFAULT '',"
        " PRIMARY KEY (codigo_comuna, calle_normalizada, numero));",
        # Índice de "calle conocida en la comuna" (prefijo comuna+calle).
        # La consulta por comuna+calle+número usa directamente la PK.
        "CREATE INDEX IF NOT EXISTS ix_direcciones_comuna_calle"
        " ON direcciones (codigo_comuna, calle_normalizada);",
    )
    # Columnas agregadas después de v1 -- se añaden por ALTER a una base
    # antigua abierta sin ``--reemplazar`` (nunca se pierde lo ya escrito).
    _COLUMNAS_V2 = ("ref_externa", "alias")

    def __init__(self, ruta: str | Path | None = None) -> None:
        if ruta is not None:
            self.ruta = Path(ruta)
        else:
            from atlas_core.almacenamiento_portable import ruta_datos_privados

            self.ruta = ruta_datos_privados("geografia") / NOMBRE_ARCHIVO_PREDETERMINADO
        self._conn_lectura: sqlite3.Connection | None = None
        # Expresiones SELECT para las columnas v2, tolerando una base v1
        # (``''`` literal en su lugar). Se resuelve en la 1ª lectura.
        self._select_v2: str | None = None

    # ---- disponibilidad -------------------------------------------------

    def disponible(self) -> bool:
        return self.contar() > 0

    def contar(self) -> int:
        """Número de filas en ``direcciones`` (0 si la base no existe o no
        es legible). Nunca lanza."""
        if not self.ruta.exists():
            return 0
        try:
            fila = self._conexion_lectura().execute(
                "SELECT COUNT(*) FROM direcciones"
            ).fetchone()
        except sqlite3.Error:
            return 0
        return int(fila[0]) if fila else 0

    # ---- consulta -----------------------------------------------------

    def consultar(self, *, comuna: str, calle: str, numero: str = "") -> EvidenciaGeoLocal:
        comuna = str(comuna or "").strip()
        calle = str(calle or "").strip()
        numero = str(numero or "").strip()
        consulta = {"comuna": comuna, "calle": calle, "numero": numero}

        if not self.disponible():
            return EvidenciaGeoLocal(
                EstadoConsultaLocal.NO_ENCONTRADO, consulta,
                disponible=False, motivo="BASE_LOCAL_NO_PROVISIONADA",
            )
        if not calle:
            return EvidenciaGeoLocal(
                EstadoConsultaLocal.NO_ENCONTRADO, consulta, motivo="CALLE_NO_INFORMADA",
            )

        resuelta = self._resolver_comuna(comuna)
        if resuelta is None:
            return EvidenciaGeoLocal(
                EstadoConsultaLocal.NO_ENCONTRADO, consulta, motivo="COMUNA_NO_RESUELTA",
            )
        codigo_comuna, comuna_canonica = resuelta

        try:
            conn = self._conexion_lectura()
        except sqlite3.Error:
            return EvidenciaGeoLocal(
                EstadoConsultaLocal.NO_ENCONTRADO, consulta,
                disponible=False, motivo="BASE_LOCAL_NO_LEGIBLE",
            )

        calle_norm = _norma_texto(calle)
        filas = self._filas_por_calle(conn, codigo_comuna, calle_norm)
        normalizada = False
        if not filas:
            # Reintento seguro: quita un prefijo de vía no discriminante
            # de la consulta ("CALLE LOS OLMOS" -> "LOS OLMOS").
            calle_alt = _sin_prefijo_estructural(calle_norm)
            if calle_alt != calle_norm:
                filas = self._filas_por_calle(conn, codigo_comuna, calle_alt)
                normalizada = bool(filas)

        if not filas:
            return EvidenciaGeoLocal(
                EstadoConsultaLocal.NO_ENCONTRADO, consulta,
                motivo="CALLE_NO_ENCONTRADA_EN_COMUNA", codigo_comuna=codigo_comuna,
            )

        candidatos = tuple(self._fila_a_direccion(f, numero) for f in filas)
        estado_calle = (
            EstadoConsultaLocal.NORMALIZADA
            if normalizada or not self._alguna_calle_verbatim(calle, filas)
            else EstadoConsultaLocal.EXACTA
        )

        if not numero:
            # Sin número consultado: la evidencia es a nivel de calle.
            if len(candidatos) == 1:
                return EvidenciaGeoLocal(
                    estado_calle, consulta, candidatos,
                    motivo="CALLE_RECONOCIDA_SIN_NUMERO_CONSULTADO", codigo_comuna=codigo_comuna,
                )
            return EvidenciaGeoLocal(
                EstadoConsultaLocal.MULTIPLE, consulta, candidatos,
                motivo="CALLE_RECONOCIDA_CON_MULTIPLES_REGISTROS", codigo_comuna=codigo_comuna,
            )

        coincidentes = tuple(c for c in candidatos if c.numero_coincide)
        if len(coincidentes) == 1:
            return EvidenciaGeoLocal(
                estado_calle, consulta, coincidentes,
                motivo="DIRECCION_CON_NUMERO_CONFIRMADO", codigo_comuna=codigo_comuna,
            )
        if len(coincidentes) > 1:
            return EvidenciaGeoLocal(
                EstadoConsultaLocal.MULTIPLE, consulta, coincidentes,
                motivo="NUMERO_EN_MULTIPLES_REGISTROS", codigo_comuna=codigo_comuna,
            )

        # Cero coincidencias de número: la CALLE existe en la comuna pero
        # ese número no está en la base. NUNCA se devuelve un número
        # distinto como coincidencia, NUNCA se marca la dirección como
        # resuelta y NUNCA se expone la coordenada de OTRO número como si
        # fuera la del consultado -- los candidatos van SIN coordenada
        # (evidencia de "calle conocida", no un punto). Se prefieren los
        # registros de sólo-calle (``numero == ""``); si no hay, se
        # listan los numerados sólo como contexto (número visible, sin
        # ``numero_coincide`` y sin coordenada).
        contexto_calle = tuple(
            replace(c, coordenadas=None) for c in (
                tuple(c for c in candidatos if not c.numero) or candidatos
            )
        )
        return EvidenciaGeoLocal(
            estado_calle, consulta, contexto_calle,
            motivo="CALLE_CONOCIDA_NUMERO_NO_EN_BASE", codigo_comuna=codigo_comuna,
        )

    # ---- import (único camino de escritura) --------------------------

    def importar_filas(
        self,
        filas: Iterable[Mapping[str, object]],
        *,
        fuente: str = "",
        reemplazar: bool = False,
        meta: Mapping[str, object] | None = None,
        chunk: int = TAMANO_CHUNK_IMPORT,
    ) -> int:
        """Puebla la base consumiendo ``filas`` en STREAMING (lotes de
        ``chunk``: millones de filas sin materializar todo en RAM).

        Cada fila requiere ``comuna`` (nombre o código CUT) y ``calle``;
        acepta ``numero`` (str, se preservan ceros iniciales),
        ``lon``/``lat`` (sólo se guardan si ambos son finitos), ``fuente``,
        ``ref_externa`` (gid INE / id OSM) y ``alias``. Una comuna no
        resoluble o una calle no normalizable abortan con ``ValueError``
        -- el importador debe entregar filas ya limpias. Devuelve el
        número de filas escritas (``INSERT OR REPLACE``; una colisión de
        PK cuenta igual).

        ``reemplazar=True`` vacía ``direcciones`` antes de insertar.
        ``meta`` persiste pares clave/valor de procedencia en la tabla
        ``meta`` (p. ej. corte del dataset, paquete, sha256)."""
        from atlas_core.geografia import cargar_geografia

        geografia = cargar_geografia("CL")
        cache_comuna: dict[str, tuple[str, str]] = {}

        def _preparar(cruda: Mapping[str, object]) -> tuple:
            comuna_valor = str(cruda.get("comuna", "")).strip()
            calle_valor = str(cruda.get("calle", "")).strip()
            if not calle_valor:
                raise ValueError("cada fila requiere 'calle'")
            resuelta = cache_comuna.get(comuna_valor)
            if resuelta is None:
                resuelta = self._resolver_comuna(comuna_valor, geografia=geografia)
                if resuelta is None:
                    raise ValueError(f"comuna no resoluble en fila: {comuna_valor!r}")
                cache_comuna[comuna_valor] = resuelta
            codigo_comuna, comuna_canonica = resuelta
            calle_norm = _norma_texto(calle_valor)
            if not calle_norm:
                raise ValueError(f"'calle' no normalizable: {calle_valor!r}")
            coords = _coordenadas_de_fila(cruda.get("lon"), cruda.get("lat"))
            return (
                codigo_comuna, calle_norm, str(cruda.get("numero", "")).strip(),
                calle_valor, comuna_canonica,
                coords[0] if coords else None, coords[1] if coords else None,
                str(cruda.get("fuente", "") or fuente).strip(),
                str(cruda.get("ref_externa", "")).strip(),
                str(cruda.get("alias", "")).strip(),
            )

        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.ruta))
        insert = (
            "INSERT OR REPLACE INTO direcciones"
            " (codigo_comuna, calle_normalizada, numero, calle_canonica,"
            "  comuna_canonica, lon, lat, fuente, ref_externa, alias)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
        )
        total = 0
        try:
            # Base regenerable: se prioriza velocidad de carga; si se
            # interrumpe, se vuelve a correr con --reemplazar.
            conn.execute("PRAGMA journal_mode = MEMORY")
            conn.execute("PRAGMA synchronous = OFF")
            for sentencia in self._DDL:
                conn.execute(sentencia)
            columnas = {fila[1] for fila in conn.execute("PRAGMA table_info(direcciones)")}
            for columna in self._COLUMNAS_V2:
                if columna not in columnas:
                    conn.execute(
                        f"ALTER TABLE direcciones ADD COLUMN {columna} TEXT NOT NULL DEFAULT ''"
                    )
            if reemplazar:
                conn.execute("DELETE FROM direcciones")
            lote: list[tuple] = []
            for cruda in filas:
                lote.append(_preparar(cruda))
                if len(lote) >= chunk:
                    conn.executemany(insert, lote)
                    conn.commit()
                    total += len(lote)
                    lote.clear()
            if lote:
                conn.executemany(insert, lote)
                total += len(lote)
            conn.execute(
                "INSERT OR REPLACE INTO meta (clave, valor) VALUES ('version_esquema', ?)",
                (str(VERSION_ESQUEMA),),
            )
            for clave, valor in dict(meta or {}).items():
                conn.execute(
                    "INSERT OR REPLACE INTO meta (clave, valor) VALUES (?, ?)",
                    (str(clave), str(valor)),
                )
            conn.commit()
        finally:
            conn.close()
        self._cerrar_lectura()
        return total

    def cerrar(self) -> None:
        self._cerrar_lectura()

    # ---- internos ---------------------------------------------------

    def _conexion_lectura(self) -> sqlite3.Connection:
        if self._conn_lectura is None:
            uri = f"file:{self.ruta.as_posix()}?mode=ro"
            self._conn_lectura = sqlite3.connect(uri, uri=True)
        return self._conn_lectura

    def _cerrar_lectura(self) -> None:
        if self._conn_lectura is not None:
            try:
                self._conn_lectura.close()
            except sqlite3.Error:
                pass
            self._conn_lectura = None
        self._select_v2 = None

    def _expr_columnas_v2(self, conn: sqlite3.Connection) -> str:
        """Devuelve ``ref_externa, alias`` si la tabla los tiene, o
        ``'' AS ref_externa, '' AS alias`` en una base v1 -- así una base
        anterior a GEOGRAFÍA 2C.3 sigue siendo consultable sin re-importar."""
        if self._select_v2 is None:
            try:
                columnas = {fila[1] for fila in conn.execute("PRAGMA table_info(direcciones)")}
            except sqlite3.Error:
                columnas = set()
            self._select_v2 = ", ".join(
                col if col in columnas else f"'' AS {col}" for col in self._COLUMNAS_V2
            )
        return self._select_v2

    def _filas_por_calle(self, conn: sqlite3.Connection, codigo_comuna: str, calle_norm: str) -> list[tuple]:
        return conn.execute(
            "SELECT codigo_comuna, calle_normalizada, numero, calle_canonica,"
            f" comuna_canonica, lon, lat, fuente, {self._expr_columnas_v2(conn)}"
            " FROM direcciones WHERE codigo_comuna = ? AND calle_normalizada = ?"
            " ORDER BY numero",
            (codigo_comuna, calle_norm),
        ).fetchall()

    @staticmethod
    def _alguna_calle_verbatim(calle_consultada: str, filas: list[tuple]) -> bool:
        objetivo = " ".join(str(calle_consultada or "").split()).casefold()
        return any(
            " ".join(str(f[3] or "").split()).casefold() == objetivo for f in filas
        )

    @staticmethod
    def _fila_a_direccion(fila: tuple, numero_consultado: str) -> DireccionLocal:
        cc, calle_norm, numero, calle_can, comuna_can, lon, lat, fuente, ref_externa, alias = fila
        return DireccionLocal(
            codigo_comuna=str(cc),
            comuna_canonica=str(comuna_can or ""),
            calle_canonica=str(calle_can or ""),
            calle_normalizada=str(calle_norm or ""),
            numero=str(numero or ""),
            numero_coincide=bool(numero_consultado)
            and numero_equivalente_seguro(str(numero or ""), numero_consultado),
            coordenadas=_coordenadas_de_fila(lon, lat),
            fuente=str(fuente or ""),
            ref_externa=str(ref_externa or ""),
            alias=str(alias or ""),
        )

    @staticmethod
    def _resolver_comuna(comuna: str, *, geografia=None) -> tuple[str, str] | None:
        comuna = str(comuna or "").strip()
        if not comuna:
            return None
        if geografia is None:
            from atlas_core.geografia import cargar_geografia

            geografia = cargar_geografia("CL")
        directa = geografia.buscar_por_codigo(comuna)
        if directa is not None and directa.nivel == geografia.nivel_geocodificable:
            return directa.codigo, directa.nombre_canonico
        decision = geografia.normalizar(comuna, nivel=geografia.nivel_geocodificable)
        if (
            decision.estado in (EstadoNormalizacion.EXACTA, EstadoNormalizacion.NORMALIZADA_SEGURA)
            and decision.unidad is not None
        ):
            return decision.unidad.codigo, decision.unidad.nombre_canonico
        return None


def evidencia_local_para_direccion(
    base: BaseGeograficaLocal | None,
    texto_direccion: str,
    *,
    comuna: str = "",
) -> EvidenciaGeoLocal:
    """Adaptador de FLUJO: interpreta un ``DESPACHAR A`` crudo (calle +
    número + a veces comuna al final) y consulta la base local. Es el
    punto por el que la base "participa como evidencia" antes de que el
    flujo geográfico declare un fallo agotado.

    Nunca lanza: sin ``base`` o con la base no provisionada devuelve
    ``NO_ENCONTRADO``. ``comuna`` explícita (p. ej. la localidad de un
    candidato del geocodificador de respaldo) tiene prioridad sobre la
    que pudiera venir incrustada en el texto."""
    texto = str(texto_direccion or "").strip()
    comuna_final = str(comuna or "").strip()
    consulta_vacia = {"comuna": comuna_final, "calle": texto, "numero": ""}
    if base is None:
        return EvidenciaGeoLocal(
            EstadoConsultaLocal.NO_ENCONTRADO, consulta_vacia,
            disponible=False, motivo="SIN_BASE_LOCAL",
        )
    if not texto:
        return EvidenciaGeoLocal(
            EstadoConsultaLocal.NO_ENCONTRADO, consulta_vacia, motivo="SIN_TEXTO_DOCUMENTAL",
        )

    from atlas_core.geografia import cargar_geografia

    geografia = cargar_geografia("CL")
    numero_match = _PATRON_NUMERO.search(texto)
    numero = numero_match.group(1) if numero_match else ""

    base_calle = texto.split(",")[0]
    if not comuna_final:
        tokens = base_calle.split()
        for largo in (3, 2, 1):
            if len(tokens) <= largo:
                continue
            candidato = " ".join(tokens[-largo:])
            decision = geografia.normalizar(candidato, nivel=geografia.nivel_geocodificable)
            if decision.estado == EstadoNormalizacion.EXACTA and decision.unidad is not None:
                comuna_final = decision.unidad.nombre_canonico
                base_calle = " ".join(tokens[:-largo]).strip() or base_calle
                break
    else:
        # Quita la comuna del final del segmento de calle si está pegada.
        objetivo = _norma_texto(comuna_final)
        tokens = base_calle.split()
        for largo in (3, 2, 1):
            if len(tokens) > largo and _norma_texto(" ".join(tokens[-largo:])) == objetivo:
                base_calle = " ".join(tokens[:-largo]).strip() or base_calle
                break

    calle = base_calle
    if numero:
        calle = _PATRON_NUMERO.sub(" ", calle, count=1)
    calle = " ".join(calle.split())

    return base.consultar(comuna=comuna_final, calle=calle, numero=numero)
