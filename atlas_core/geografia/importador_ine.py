"""GEOGRAFÍA 2C.3 -- IMPORTADOR OFFLINE del MAESTRO TERRITORIAL INE
(A4A / geoaddress Chile) -> base geográfica local Atlas.

Herramienta PERIFÉRICA, sólo aprovisionamiento offline:
  * ningún camino de runtime del Motor importa este módulo;
  * en operación Atlas sólo consume el SQLite ya generado
    (``atlas_core.geografia.base_local``), nunca el CSV/ZIP;
  * SÓLO stdlib (``csv``, ``zipfile``) -- NO usa ``osmium`` ni se mezcla
    con el importador OSM.

Entrada: el CSV ``a4a_cl_geoaddress_*.csv`` (o su ``.zip``), columnas
``gid, via, hnum, alias, error, region, clase_urbana, nombre_comuna,
longitude, latitude``. Se procesa en STREAMING (chunks), ~4,2 M filas sin
cargar todo en RAM.

Reglas de seguridad:
  * sólo Región Metropolitana (código de región CUT ``"13"``), resuelta
    por el catálogo territorial existente -- ``TILTIL`` -> ``TIL TIL``
    (13303) sale gratis de la normalización segura;
  * ``via`` -> ``calle_canonica`` TAL CUAL; ``hnum`` -> ``numero`` TAL
    CUAL (se preservan ceros iniciales, letras, rangos);
  * NUNCA infiere ``O``<->``0`` / ``B``<->``8`` ni equivalencias OCR;
  * NUNCA inventa ni interpola coordenadas: una coincidencia exacta
    aporta la coordenada REAL de la fila INE; una calle sin ese número
    NO recibe coordenada;
  * coordenada fuera de Chile / ``(0,0)`` / no numérica -> fila
    descartada (contada), nunca corregida;
  * ``gid`` se conserva en ``ref_externa`` (trazabilidad); ``alias`` se
    conserva pero NUNCA participa en la resolución.

GEOGRAFÍA 2C.4 -- multiplicidad de coordenadas por dirección: NO se
deduplica en la importación. Cada fila INE aceptada se ENVÍA tal cual;
como la PK de ``direcciones`` ahora incluye ``ref_externa`` (= ``gid``),
dos observaciones de la misma ``(comuna, calle, numero)`` con gid
distinto CONVIVEN en la base (auditables por gid). El colapso de
observaciones que representan el mismo punto y el desenlace ``MULTIPLE``
para coordenadas materialmente distintas ocurren en la CONSULTA
(``base_local.consultar``), con un criterio espacial explícito y
determinista (rejilla de ~1e-4°). El importador sólo AUDITA el resultado
(``direcciones_con_multiples_observaciones`` / ``direcciones_multipunto``).
INE sigue SIN conectarse al runtime productivo.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import sqlite3
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Mapping

VERSION_IMPORTADOR_INE = 1
REGION_METROPOLITANA = "13"

# Dataset A4A / geoaddress -- valores por defecto de procedencia (el
# usuario validó estos externamente; sobre-escribibles por CLI).
DATASET_NOMBRE = "a4a_cl_geoaddress"
DATASET_PAQUETE = "pk0004.02"
DATASET_CORTE = "2023-12"
DATASET_AUTORIDAD = "A4A / geoaddress Chile (maestro territorial, base INE)"

_COLUMNAS_ESPERADAS = (
    "gid", "via", "hnum", "alias", "error", "region",
    "clase_urbana", "nombre_comuna", "longitude", "latitude",
)
_N_COLUMNAS = len(_COLUMNAS_ESPERADAS)

# Caja envolvente continental de Chile (holgada) -- descarta coordenadas
# groseramente imposibles sin "corregir" nada.
_LON_MIN, _LON_MAX = -80.0, -66.0
_LAT_MIN, _LAT_MAX = -56.5, -17.0

CLAVES_CONTEO = (
    "filas_csv_leidas", "malformadas", "fuera_de_rm_descartadas",
    "comuna_no_resuelta_descartadas", "coordenada_invalida_descartadas",
    "via_vacia_descartadas", "aceptadas", "filas_enviadas",
    # GEOGRAFÍA 2C.4 -- ya NO existe "colisiones_pk" (ninguna observación
    # se pisa por PK): en su lugar se AUDITA la multiplicidad resultante.
    #   direcciones_con_multiples_observaciones: (comuna, calle, numero)
    #       con >= 2 filas conservadas;
    #   direcciones_multipunto: de esas, las que tienen >= 2 celdas
    #       espaciales distintas -> la consulta devolverá MULTIPLE.
    "direcciones_con_multiples_observaciones", "direcciones_multipunto",
    "filas_en_tabla",
)


def _nuevos_conteos() -> dict[str, int]:
    return {clave: 0 for clave in CLAVES_CONTEO}


# ---------------------------------------------------------------------------
# Lectura del CSV / ZIP -- streaming
# ---------------------------------------------------------------------------


def _abrir_texto(ruta: Path) -> tuple[io.TextIOBase, "zipfile.ZipFile | None", str]:
    """Abre el CSV como flujo de texto UTF-8. Acepta ``.zip`` (toma el
    único ``.csv`` interior). Devuelve ``(flujo, zip_o_None, nombre_csv)``."""
    if ruta.suffix.lower() == ".zip":
        zf = zipfile.ZipFile(ruta)
        internos = [n for n in zf.namelist() if n.lower().endswith(".csv")]
        if len(internos) != 1:
            zf.close()
            raise ValueError(f"el .zip debe contener exactamente 1 .csv (hay {len(internos)})")
        crudo = zf.open(internos[0], "r")
        return io.TextIOWrapper(crudo, encoding="utf-8", newline=""), zf, internos[0]
    return ruta.open("r", encoding="utf-8", newline=""), None, ruta.name


def iter_filas_csv(ruta_csv: str | Path) -> Iterator[list[str]]:
    """Itera las filas de datos del CSV INE (sin cabecera) en streaming."""
    ruta = Path(ruta_csv)
    flujo, zf, _nombre = _abrir_texto(ruta)
    try:
        lector = csv.reader(flujo)
        cabecera = next(lector, None)
        if cabecera is None:
            return
        # cabecera tolerante: sólo se exige el conjunto de nombres.
        if [c.strip().lower() for c in cabecera] != list(_COLUMNAS_ESPERADAS):
            raise ValueError(
                f"cabecera inesperada: {cabecera!r} (esperado {list(_COLUMNAS_ESPERADAS)})"
            )
        for fila in lector:
            yield fila
    finally:
        flujo.close()
        if zf is not None:
            zf.close()


# ---------------------------------------------------------------------------
# Transformación fila INE -> fila para importar_filas
# ---------------------------------------------------------------------------


class _ResolutorComunaRM:
    """Clasifica ``nombre_comuna`` INE -> ``("RM", codigo, canonico)`` /
    ``("OTRA_REGION", "", "")`` / ``("NO_RESUELTA", "", "")``. Todo
    cacheado por nombre (≈300 distintos): una sola normalización del
    catálogo territorial por nombre, aunque el CSV tenga 4,2 M filas."""

    def __init__(self, geografia, region: str) -> None:
        self._geo = geografia
        self._region = region
        self._cache: dict[str, tuple[str, str, str]] = {}

    def clasificar(self, nombre: str) -> tuple[str, str, str]:
        nombre = str(nombre or "").strip()
        if not nombre:
            return ("NO_RESUELTA", "", "")
        cacheado = self._cache.get(nombre)
        if cacheado is not None:
            return cacheado
        from atlas_core.geografia.modelos import EstadoNormalizacion

        salida = ("NO_RESUELTA", "", "")
        decision = self._geo.normalizar(nombre, nivel=self._geo.nivel_geocodificable)
        if (
            decision.estado in (EstadoNormalizacion.EXACTA, EstadoNormalizacion.NORMALIZADA_SEGURA)
            and decision.unidad is not None
        ):
            contexto = self._geo.parametros_geocodificacion(decision.unidad)
            if contexto.codigo_contexto == self._region:
                salida = ("RM", decision.unidad.codigo, decision.unidad.nombre_canonico)
            else:
                salida = ("OTRA_REGION", "", "")
        self._cache[nombre] = salida
        return salida


def _coordenada(lon_txt: str, lat_txt: str) -> tuple[float, float] | None:
    try:
        lon, lat = float(lon_txt), float(lat_txt)
    except (TypeError, ValueError):
        return None
    if lon != lon or lat != lat:  # NaN
        return None
    if not (_LON_MIN <= lon <= _LON_MAX and _LAT_MIN <= lat <= _LAT_MAX):
        return None
    if lon == 0.0 and lat == 0.0:
        return None
    return (lon, lat)


def iter_filas_rm(
    ruta_csv: str | Path,
    *,
    geografia,
    region: str = REGION_METROPOLITANA,
    fuente: str = "INE",
    conteos: dict[str, int] | None = None,
    limite: int | None = None,
) -> Iterator[dict]:
    """Genera filas ``{comuna, calle, numero, lon, lat, fuente,
    ref_externa, alias}`` -- ya limpias y filtradas a la región -- listas
    para ``BaseGeograficaLocalSQLite.importar_filas``. Actualiza
    ``conteos`` in situ. NUNCA lanza por una fila mala: la descarta y la
    cuenta."""
    conteos = conteos if conteos is not None else _nuevos_conteos()
    resolutor = _ResolutorComunaRM(geografia, region)
    emitidas = 0
    for fila in iter_filas_csv(ruta_csv):
        conteos["filas_csv_leidas"] += 1
        if len(fila) != _N_COLUMNAS:
            conteos["malformadas"] += 1
            continue
        gid, via, hnum, alias, _error, _region_txt, _clase, nombre_comuna, lon_txt, lat_txt = fila
        via = via.strip()
        if not via:
            conteos["via_vacia_descartadas"] += 1
            continue
        clase, codigo_comuna, _canonico = resolutor.clasificar(nombre_comuna)
        if clase == "OTRA_REGION":
            conteos["fuera_de_rm_descartadas"] += 1
            continue
        if clase != "RM":
            conteos["comuna_no_resuelta_descartadas"] += 1
            continue
        coords = _coordenada(lon_txt, lat_txt)
        if coords is None:
            conteos["coordenada_invalida_descartadas"] += 1
            continue
        conteos["aceptadas"] += 1
        yield {
            "comuna": codigo_comuna,
            "calle": via,
            "numero": hnum.strip(),
            "lon": coords[0],
            "lat": coords[1],
            "fuente": fuente,
            "ref_externa": f"gid={gid.strip()}" if gid.strip() else "",
            "alias": alias.strip(),
        }
        emitidas += 1
        if limite is not None and emitidas >= limite:
            break


# ---------------------------------------------------------------------------
# Procedencia
# ---------------------------------------------------------------------------


def _sha256(ruta: Path) -> str:
    h = hashlib.sha256()
    with ruta.open("rb") as fh:
        for bloque in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(bloque)
    return h.hexdigest()


def escribir_procedencia(
    ruta_sqlite: Path,
    ruta_csv: Path,
    *,
    region: str,
    region_nombre: str,
    conteos: Mapping[str, int],
    corte: str,
    paquete: str,
    csv_interno: str | None,
) -> Path:
    ruta_proc = ruta_sqlite.with_suffix(ruta_sqlite.suffix + ".procedencia.json")
    contenido = {
        "base": ruta_sqlite.name,
        "generado_en": datetime.now(timezone.utc).isoformat(),
        "importador": "atlas_core.geografia.importador_ine",
        "importador_version": VERSION_IMPORTADOR_INE,
        "region_filtro": region,
        "region_nombre": region_nombre,
        "dataset": {
            "nombre": DATASET_NOMBRE,
            "autoridad": DATASET_AUTORIDAD,
            "paquete": paquete,
            "corte": corte,
            "archivo": ruta_csv.name,
            "csv_interno": csv_interno,
            "ruta_absoluta": str(ruta_csv.resolve()),
            "bytes": ruta_csv.stat().st_size,
            "sha256": _sha256(ruta_csv),
            "modificado_en": datetime.fromtimestamp(
                ruta_csv.stat().st_mtime, timezone.utc
            ).isoformat(),
        },
        "conteos": dict(conteos),
        "nota": (
            "Maestro territorial derivado del proyecto A4A/geoaddress (base "
            "INE). Importador OFFLINE; el Motor en runtime sólo consume este "
            "SQLite, nunca el CSV/ZIP."
        ),
    }
    ruta_proc.write_text(json.dumps(contenido, ensure_ascii=False, indent=2), encoding="utf-8")
    return ruta_proc


# ---------------------------------------------------------------------------
# Auditoría de multiplicidad
# ---------------------------------------------------------------------------


def _escanear_multiplicidad(ruta_sqlite: str | Path) -> dict[str, int]:
    """Recorre ``direcciones`` en STREAMING (ordenada por la clave natural
    ``comuna, calle, numero``) y cuenta, con memoria acotada (sólo el
    grupo en curso):

      * ``con_multiples_observaciones``: direcciones ``(comuna, calle,
        numero)`` con >= 2 filas conservadas (antes se perdían por PK);
      * ``multipunto``: de esas, las que tienen >= 2 celdas espaciales
        distintas segun ``base_local._celda_espacial`` -- coordenadas
        materialmente diferentes que la consulta devolverá como
        ``MULTIPLE``.

    Usa EXACTAMENTE el mismo criterio espacial que ``consultar`` (una
    sola definición de "mismo punto")."""
    from atlas_core.geografia.base_local import _celda_espacial

    ruta = Path(ruta_sqlite)
    if not ruta.exists():
        return {"con_multiples_observaciones": 0, "multipunto": 0}

    con = sqlite3.connect(f"file:{ruta.as_posix()}?mode=ro", uri=True)
    con_multiples = multipunto = 0
    clave_actual: tuple | None = None
    n_filas = 0
    celdas: set[tuple[int, int]] = set()

    def _cerrar_grupo() -> None:
        nonlocal con_multiples, multipunto
        if n_filas >= 2:
            con_multiples += 1
            if len(celdas) >= 2:
                multipunto += 1

    try:
        cursor = con.execute(
            "SELECT codigo_comuna, calle_normalizada, numero, lon, lat"
            " FROM direcciones ORDER BY codigo_comuna, calle_normalizada, numero"
        )
        for cc, calle, numero, lon, lat in cursor:
            clave = (cc, calle, numero)
            if clave != clave_actual:
                if clave_actual is not None:
                    _cerrar_grupo()
                clave_actual = clave
                n_filas = 0
                celdas = set()
            n_filas += 1
            celda = _celda_espacial((lon, lat) if lon is not None and lat is not None else None)
            if celda is not None:
                celdas.add(celda)
        if clave_actual is not None:
            _cerrar_grupo()
    finally:
        con.close()
    return {"con_multiples_observaciones": con_multiples, "multipunto": multipunto}


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


def importar_a_sqlite(
    ruta_csv: str | Path,
    ruta_sqlite: str | Path,
    *,
    region: str = REGION_METROPOLITANA,
    fuente: str = "INE",
    reemplazar: bool = False,
    limite: int | None = None,
    chunk: int = 50_000,
    corte: str = DATASET_CORTE,
    paquete: str = DATASET_PAQUETE,
    escribir_meta: bool = True,
) -> dict[str, int]:
    """Pipeline: CSV/ZIP INE -> filas RM limpias -> ``importar_filas``
    (streaming) -> ``<sqlite>.procedencia.json``. Devuelve los conteos."""
    from atlas_core.geografia import cargar_geografia
    from atlas_core.geografia.base_local import BaseGeograficaLocalSQLite

    ruta_csv = Path(ruta_csv)
    ruta_sqlite = Path(ruta_sqlite)
    if not ruta_csv.exists():
        raise FileNotFoundError(f"no existe el CSV/ZIP INE: {ruta_csv}")

    geografia = cargar_geografia("CL")
    unidad_region = geografia.buscar_por_codigo(region)
    region_nombre = unidad_region.nombre_canonico if unidad_region else region
    conteos = _nuevos_conteos()
    sha_archivo = _sha256(ruta_csv)
    _csv_interno = None
    if ruta_csv.suffix.lower() == ".zip":
        with zipfile.ZipFile(ruta_csv) as zf:
            internos = [n for n in zf.namelist() if n.lower().endswith(".csv")]
            _csv_interno = internos[0] if internos else None

    filas = iter_filas_rm(
        ruta_csv, geografia=geografia, region=region, fuente=fuente,
        conteos=conteos, limite=limite,
    )
    base = BaseGeograficaLocalSQLite(ruta_sqlite)
    meta = {
        "origen": "INE_A4A",
        "dataset_nombre": DATASET_NOMBRE,
        "dataset_paquete": paquete,
        "dataset_corte": corte,
        "dataset_sha256": sha_archivo,
        "region_filtro": region,
        "importado_en": datetime.now(timezone.utc).isoformat(),
    }
    enviadas = base.importar_filas(
        filas, fuente=fuente, reemplazar=reemplazar, meta=meta, chunk=chunk,
    )
    en_tabla = base.contar()
    conteos["filas_enviadas"] = enviadas
    conteos["filas_en_tabla"] = en_tabla
    # Auditoría de multiplicidad (GEOGRAFÍA 2C.4): recorre la tabla en
    # streaming y cuenta las direcciones con varias observaciones y las
    # que además son multipunto -- sin colapsar nada, sin "última fila".
    mult = _escanear_multiplicidad(ruta_sqlite)
    conteos["direcciones_con_multiples_observaciones"] = mult["con_multiples_observaciones"]
    conteos["direcciones_multipunto"] = mult["multipunto"]

    if escribir_meta:
        escribir_procedencia(
            ruta_sqlite, ruta_csv, region=region, region_nombre=region_nombre,
            conteos=conteos, corte=corte, paquete=paquete, csv_interno=_csv_interno,
        )
    return conteos


def contar_dry_run(
    ruta_csv: str | Path,
    *,
    region: str = REGION_METROPOLITANA,
    limite: int | None = None,
) -> dict[str, int]:
    """Recorre el CSV sin escribir nada; sólo devuelve los conteos."""
    from atlas_core.geografia import cargar_geografia

    geografia = cargar_geografia("CL")
    conteos = _nuevos_conteos()
    for _fila in iter_filas_rm(
        ruta_csv, geografia=geografia, region=region, conteos=conteos, limite=limite,
    ):
        pass
    return conteos


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _resumen(conteos: Mapping[str, int]) -> str:
    return " ".join(f"{k}={conteos[k]}" for k in CLAVES_CONTEO if k in conteos)


def _construir_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m atlas_core.geografia.importador_ine",
        description=(
            "Importador OFFLINE del maestro territorial INE (A4A/geoaddress) "
            "-> base geográfica local Atlas (RM). Sólo stdlib; el Motor en "
            "runtime nunca necesita el CSV/ZIP."
        ),
    )
    parser.add_argument("--csv", required=True, metavar="RUTA",
                        help="CSV a4a_cl_geoaddress_*.csv o su .zip")
    parser.add_argument("--salida", metavar="RUTA",
                        help="SQLite destino (por defecto: datos_privados/geografia/base_local_rm_ine.sqlite)")
    parser.add_argument("--region", default=REGION_METROPOLITANA, help="código CUT de región (def. 13 = RM)")
    parser.add_argument("--fuente", default="INE", help="etiqueta de procedencia por fila (def. INE)")
    parser.add_argument("--reemplazar", action="store_true", help="vacía la tabla antes de importar")
    parser.add_argument("--limite", type=int, default=None, help="máx. de filas RM a procesar (pruebas)")
    parser.add_argument("--chunk", type=int, default=50_000, help="tamaño de lote de escritura")
    parser.add_argument("--corte", default=DATASET_CORTE, help=f"corte del dataset (def. {DATASET_CORTE})")
    parser.add_argument("--paquete", default=DATASET_PAQUETE, help=f"paquete del dataset (def. {DATASET_PAQUETE})")
    parser.add_argument("--dry-run", action="store_true", help="no escribe nada; sólo informa conteos")
    parser.add_argument("--json", action="store_true", help="salida en JSON")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _construir_parser().parse_args(argv)
    ruta_csv = Path(args.csv)

    if args.dry_run:
        conteos = contar_dry_run(ruta_csv, region=args.region, limite=args.limite)
        ruta_sqlite = None
    else:
        if args.salida:
            ruta_sqlite = Path(args.salida)
        else:
            from atlas_core.almacenamiento_portable import ruta_datos_privados

            ruta_sqlite = ruta_datos_privados("geografia") / "base_local_rm_ine.sqlite"
        conteos = importar_a_sqlite(
            ruta_csv, ruta_sqlite, region=args.region, fuente=args.fuente,
            reemplazar=args.reemplazar, limite=args.limite, chunk=args.chunk,
            corte=args.corte, paquete=args.paquete,
        )

    if args.json:
        print(json.dumps({
            "salida_sqlite": str(ruta_sqlite) if ruta_sqlite else None,
            "dry_run": bool(args.dry_run),
            "conteos": conteos,
        }, ensure_ascii=False, indent=2))
    else:
        print(_resumen(conteos))
        if ruta_sqlite is not None:
            print(f"sqlite      -> {ruta_sqlite}")
            print(f"procedencia -> {ruta_sqlite}.procedencia.json")
        else:
            print("dry-run: no se escribió nada")
    return 0


if __name__ == "__main__":
    sys.exit(main())
