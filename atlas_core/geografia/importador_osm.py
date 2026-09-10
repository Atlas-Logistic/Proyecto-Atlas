"""GEOGRAFÍA 2C.2 -- IMPORTADOR OFFLINE OSM/PBF -> base local Atlas.

Herramienta PERIFÉRICA: transforma un extracto OpenStreetMap de la Región
Metropolitana (``.osm``/``.xml`` sin dependencias, o ``.osm.pbf`` /
``.pbf`` / ``.osm.bz2`` con ``osmium``) en filas para
``BaseGeograficaLocalSQLite.importar_filas``.

NO forma parte del runtime del Motor:
  * ningún camino de operación importa este módulo;
  * en operación Atlas sólo necesita el SQLite ya generado -- nunca el
    PBF ni ``osmium``;
  * la dependencia ``osmium`` está AISLADA en
    ``requirements-importador-osm.txt`` y sólo se toca al leer un PBF
    real; si falta, el error es explícito y apunta a ese archivo.

Reglas de seguridad (heredadas de GEOGRAFÍA 2C.1):
  * NUNCA inventa números ni coordenadas -- si OSM no trae
    ``addr:housenumber`` la fila queda con ``numero=""``; si el objeto no
    es un nodo con posición propia, ``lon``/``lat`` van ``None`` (jamás un
    centroide calculado);
  * NUNCA infiere ``B<->8`` / ``O<->0`` ni ninguna equivalencia OCR --
    ``addr:housenumber`` se preserva TAL CUAL (sólo ``"S/N"`` y variantes
    explícitas de "sin número" se colapsan a ``""``);
  * sólo Región Metropolitana (código de región CUT ``"13"``);
  * duplicados EXACTOS (misma comuna+calle+número+coordenada) se colapsan
    de forma determinista;
  * varias direcciones reales distintas (números o calles distintos) se
    conservan como filas separadas -- son candidatos, no se colapsan;
  * una colisión de clave (misma comuna+calle+número, coordenada distinta)
    se resuelve SIEMPRE igual: gana la que tiene coordenada; a igualdad,
    el menor ``(lat, lon, referencia_osm)``.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator, Mapping

from .motor import texto_normalizado

VERSION_IMPORTADOR = 1
REGION_METROPOLITANA = "13"

# Extensiones que se leen SIN dependencias (XML de OSM plano).
_EXT_XML = (".osm", ".xml")
# Extensiones que exigen ``osmium`` (pyosmium).
_EXT_PBF = (".pbf", ".osm.pbf", ".osm.bz2")

# Claves OSM de las que se puede leer la comuna, en orden de preferencia.
_CLAVES_COMUNA = ("addr:city", "addr:municipality", "addr:suburb", "addr:province")

# Valores de ``addr:housenumber`` que significan "sin número" -- se
# colapsan a "" (nunca se inventa un número). Comparación normalizada.
_SIN_NUMERO = frozenset({"SN", "S N", "S NRO", "S NUM", "S NUMERO", "SIN NUMERO", "SIN N"})


class DependenciaImportadorFaltante(RuntimeError):
    """La librería para leer PBF no está instalada. Es dependencia SÓLO
    del importador, nunca del Motor."""


@dataclass(frozen=True)
class ElementoOSM:
    """Un objeto OSM ya leído, reducido a lo mínimo para direcciones."""

    referencia: str                       # "node/123", "way/456"
    tags: Mapping[str, str]
    lon: float | None = None
    lat: float | None = None


@dataclass
class ResultadoImportacion:
    filas: list[dict]
    conteos: dict[str, int]
    lector: str

    def resumen(self) -> str:
        c = self.conteos
        return (
            f"lector={self.lector} escaneados={c['objetos_escaneados']} "
            f"con_direccion={c['con_direccion']} rm={c['rm_pre_consolidacion']} "
            f"fuera_rm={c['fuera_de_rm_descartadas']} "
            f"comuna_no_resuelta={c['comuna_no_resuelta_descartadas']} "
            f"dup_exactos={c['duplicados_exactos_colapsados']} "
            f"colisiones={c['colisiones_clave_resueltas']} filas={c['filas_escritas']}"
        )


# ---------------------------------------------------------------------------
# Transformación pura -- sin I/O, sin dependencias externas
# ---------------------------------------------------------------------------


def _coordenada_valida(lon: object, lat: object) -> tuple[float, float] | None:
    if lon is None or lat is None:
        return None
    try:
        lon_f, lat_f = float(lon), float(lat)
    except (TypeError, ValueError):
        return None
    if not (math.isfinite(lon_f) and math.isfinite(lat_f)):
        return None
    if not (-180.0 <= lon_f <= 180.0 and -90.0 <= lat_f <= 90.0):
        return None
    if lon_f == 0.0 and lat_f == 0.0:      # Null Island -- nunca es un dato real
        return None
    return (lon_f, lat_f)


def normalizar_numero_osm(valor: object) -> str:
    """``addr:housenumber`` -> número de casa seguro. Preserva TAL CUAL
    (ceros iniciales, letras, rangos "123-125"); sólo colapsa las formas
    explícitas de "sin número" a "". NUNCA cambia un carácter por otro."""
    texto = str(valor or "").strip()
    if not texto:
        return ""
    if texto_normalizado(texto) in _SIN_NUMERO:
        return ""
    return texto


def _comuna_cruda(tags: Mapping[str, str]) -> str:
    for clave in _CLAVES_COMUNA:
        valor = str(tags.get(clave, "")).strip()
        if valor:
            return valor
    return ""


def fila_cruda_desde_elemento(elemento: ElementoOSM) -> dict | None:
    """Extrae ``{calle, numero, comuna_cruda, lon, lat, fuente,
    referencia}`` de un ``ElementoOSM``, o ``None`` si no aporta una
    dirección utilizable (sin ``addr:street``)."""
    tags = elemento.tags or {}
    calle = str(tags.get("addr:street", "")).strip()
    if not calle:
        return None
    comuna_cruda = _comuna_cruda(tags)
    if not comuna_cruda:
        return None
    coords = _coordenada_valida(elemento.lon, elemento.lat)
    return {
        "calle": calle,
        "numero": normalizar_numero_osm(tags.get("addr:housenumber")),
        "comuna_cruda": comuna_cruda,
        "lon": coords[0] if coords else None,
        "lat": coords[1] if coords else None,
        "fuente": f"OSM {elemento.referencia}",
        "referencia": elemento.referencia,
    }


def _clave_orden_colision(fila: dict) -> tuple:
    tiene_coord = fila["lon"] is not None and fila["lat"] is not None
    return (
        0 if tiene_coord else 1,
        fila["lat"] if fila["lat"] is not None else math.inf,
        fila["lon"] if fila["lon"] is not None else math.inf,
        fila["referencia"],
    )


def consolidar_filas_rm(
    filas_crudas: Iterable[dict], *, geografia, region: str = REGION_METROPOLITANA,
) -> tuple[list[dict], dict[str, int]]:
    """Resuelve comuna, filtra a ``region``, colapsa duplicados exactos y
    resuelve colisiones de clave -- todo de forma determinista. Devuelve
    ``(filas_listas_para_importar_filas, conteos)``.

    Cada fila de salida: ``{comuna (código CUT), calle, numero, lon, lat,
    fuente}`` -- exactamente lo que ``importar_filas`` acepta."""
    conteos = {
        "con_direccion": 0,
        "rm_pre_consolidacion": 0,
        "fuera_de_rm_descartadas": 0,
        "comuna_no_resuelta_descartadas": 0,
        "duplicados_exactos_colapsados": 0,
        "colisiones_clave_resueltas": 0,
    }
    cache_comuna: dict[str, tuple[str, str] | None] = {}

    def _resolver(nombre: str) -> tuple[str, str] | None:
        if nombre in cache_comuna:
            return cache_comuna[nombre]
        decision = geografia.normalizar(nombre, nivel=geografia.nivel_geocodificable)
        from atlas_core.geografia.modelos import EstadoNormalizacion

        resuelto: tuple[str, str] | None = None
        if (
            decision.estado in (EstadoNormalizacion.EXACTA, EstadoNormalizacion.NORMALIZADA_SEGURA)
            and decision.unidad is not None
        ):
            contexto = geografia.parametros_geocodificacion(decision.unidad)
            if contexto.codigo_contexto == region:
                resuelto = (decision.unidad.codigo, contexto.codigo_contexto)
            else:
                resuelto = ("__FUERA_REGION__", contexto.codigo_contexto)
        cache_comuna[nombre] = resuelto
        return resuelto

    # 1) resolver comuna + filtrar región
    filtradas: list[dict] = []
    for fila in filas_crudas:
        conteos["con_direccion"] += 1
        resuelto = _resolver(fila["comuna_cruda"])
        if resuelto is None:
            conteos["comuna_no_resuelta_descartadas"] += 1
            continue
        codigo_comuna, _region = resuelto
        if codigo_comuna == "__FUERA_REGION__":
            conteos["fuera_de_rm_descartadas"] += 1
            continue
        filtradas.append({**fila, "codigo_comuna": codigo_comuna})

    # 2) colapsar duplicados EXACTOS (misma comuna+calle+numero+coordenada)
    def _lon_r(v):
        return None if v is None else round(v, 7)

    exactos: "OrderedDict[tuple, dict]" = OrderedDict()
    for fila in filtradas:
        calle_norm = texto_normalizado(fila["calle"])
        clave_exacta = (
            fila["codigo_comuna"], calle_norm, fila["numero"],
            _lon_r(fila["lon"]), _lon_r(fila["lat"]),
        )
        if clave_exacta in exactos:
            conteos["duplicados_exactos_colapsados"] += 1
            # determinismo: se queda la de menor referencia_osm
            if fila["referencia"] < exactos[clave_exacta]["referencia"]:
                exactos[clave_exacta] = {**fila, "calle_norm": calle_norm}
        else:
            exactos[clave_exacta] = {**fila, "calle_norm": calle_norm}

    # 3) resolver colisiones de clave (misma comuna+calle+numero, coord distinta)
    por_clave: "OrderedDict[tuple, list[dict]]" = OrderedDict()
    for fila in exactos.values():
        clave = (fila["codigo_comuna"], fila["calle_norm"], fila["numero"])
        por_clave.setdefault(clave, []).append(fila)

    consolidadas: list[dict] = []
    for clave, grupo in por_clave.items():
        if len(grupo) > 1:
            conteos["colisiones_clave_resueltas"] += len(grupo) - 1
            grupo = sorted(grupo, key=_clave_orden_colision)
        elegida = grupo[0]
        consolidadas.append({
            "comuna": elegida["codigo_comuna"],
            "calle": elegida["calle"],
            "numero": elegida["numero"],
            "lon": elegida["lon"],
            "lat": elegida["lat"],
            "fuente": elegida["fuente"],
        })

    # 4) orden de salida totalmente determinista
    consolidadas.sort(key=lambda f: (
        f["comuna"], texto_normalizado(f["calle"]), f["numero"], f["fuente"],
    ))
    conteos["rm_pre_consolidacion"] = len(filtradas)
    return consolidadas, conteos


# ---------------------------------------------------------------------------
# Lectura OSM -- XML plano (stdlib) y PBF (osmium, dependencia aislada)
# ---------------------------------------------------------------------------


def _tipo_de_ruta(ruta: Path) -> str:
    nombre = ruta.name.lower()
    if nombre.endswith(_EXT_PBF):
        return "pbf"
    if nombre.endswith(_EXT_XML):
        return "xml"
    raise ValueError(
        f"extensión no reconocida: {ruta.name!r} "
        f"(esperado {' / '.join(_EXT_XML + _EXT_PBF)})"
    )


def iter_elementos_xml(ruta: Path) -> Iterator[ElementoOSM]:
    """Lee un ``.osm``/``.xml`` de OSM en streaming con la stdlib -- sin
    ninguna dependencia. Sólo nodos (con posición propia) y ways (sin
    geometría: ``lon``/``lat`` van ``None``, nunca un centroide)."""
    import xml.etree.ElementTree as ET

    contexto = ET.iterparse(str(ruta), events=("end",))
    for _evento, elemento in contexto:
        etiqueta = elemento.tag
        if etiqueta not in ("node", "way"):
            if etiqueta in ("nd", "member", "tag"):
                continue
            elemento.clear()
            continue
        tags = {
            hijo.get("k"): hijo.get("v")
            for hijo in elemento.findall("tag")
            if hijo.get("k") is not None
        }
        ident = elemento.get("id", "")
        if etiqueta == "node":
            lon = elemento.get("lon")
            lat = elemento.get("lat")
            yield ElementoOSM(f"node/{ident}", tags, lon, lat)
        else:
            yield ElementoOSM(f"way/{ident}", tags, None, None)
        elemento.clear()


def _osmium_o_error():
    try:
        import osmium  # type: ignore
    except ImportError as exc:  # pragma: no cover - depende del entorno
        raise DependenciaImportadorFaltante(
            "Leer un PBF requiere la librería 'osmium' (pyosmium), que NO es "
            "dependencia del Motor en runtime.\n"
            "Instálala SÓLO para el importador:\n"
            "    pip install -r requirements-importador-osm.txt\n"
            "Alternativa sin dependencias: exporta el extracto a .osm XML "
            "(p. ej. `osmconvert region.osm.pbf -o=region.osm`) y pásalo con "
            "--pbf region.osm."
        ) from exc
    return osmium


def iter_elementos_pbf(ruta: Path) -> Iterator[ElementoOSM]:  # pragma: no cover - requiere osmium
    """Lee un ``.osm.pbf`` con ``osmium`` (dependencia aislada del
    importador). Sólo nodos con posición y ways sin geometría."""
    osmium = _osmium_o_error()

    elementos: list[ElementoOSM] = []

    class _Handler(osmium.SimpleHandler):
        def node(self, n):
            tags = {t.k: t.v for t in n.tags}
            if "addr:street" not in tags:
                return
            lon = lat = None
            try:
                if n.location.valid():
                    lon, lat = n.location.lon, n.location.lat
            except (ValueError, RuntimeError):
                lon = lat = None
            elementos.append(ElementoOSM(f"node/{n.id}", tags, lon, lat))

        def way(self, w):
            tags = {t.k: t.v for t in w.tags}
            if "addr:street" not in tags:
                return
            elementos.append(ElementoOSM(f"way/{w.id}", tags, None, None))

    _Handler().apply_file(str(ruta), locations=False)
    yield from elementos


def iter_elementos(ruta: Path) -> Iterator[ElementoOSM]:
    tipo = _tipo_de_ruta(ruta)
    if tipo == "xml":
        return iter_elementos_xml(ruta)
    return iter_elementos_pbf(ruta)


def _lector_de_ruta(ruta: Path) -> str:
    if _tipo_de_ruta(ruta) == "xml":
        return "xml.etree (stdlib)"
    try:
        osmium = _osmium_o_error()
        return f"osmium {getattr(osmium, 'version', getattr(osmium, '__version__', '?'))}"
    except DependenciaImportadorFaltante:
        return "osmium (no instalado)"


# ---------------------------------------------------------------------------
# Pipeline completo
# ---------------------------------------------------------------------------


def construir_filas_desde_osm(
    ruta_osm: str | Path, *, region: str = REGION_METROPOLITANA, limite: int | None = None,
) -> ResultadoImportacion:
    """Lee un extracto OSM y devuelve las filas listas para
    ``importar_filas`` más los conteos de procedencia. No escribe nada."""
    from atlas_core.geografia import cargar_geografia

    ruta = Path(ruta_osm)
    if not ruta.exists():
        raise FileNotFoundError(f"no existe el extracto OSM: {ruta}")

    geografia = cargar_geografia("CL")
    escaneados = 0
    crudas: list[dict] = []
    for elemento in iter_elementos(ruta):
        escaneados += 1
        fila = fila_cruda_desde_elemento(elemento)
        if fila is not None:
            crudas.append(fila)
            if limite is not None and len(crudas) >= limite:
                break

    consolidadas, conteos = consolidar_filas_rm(crudas, geografia=geografia, region=region)
    conteos = {"objetos_escaneados": escaneados, **conteos, "filas_escritas": len(consolidadas)}
    return ResultadoImportacion(consolidadas, conteos, _lector_de_ruta(ruta))


def _sha256(ruta: Path) -> str:
    h = hashlib.sha256()
    with ruta.open("rb") as archivo:
        for bloque in iter(lambda: archivo.read(1024 * 1024), b""):
            h.update(bloque)
    return h.hexdigest()


def escribir_procedencia(
    ruta_sqlite: Path, ruta_osm: Path, resultado: ResultadoImportacion, *,
    region: str, region_nombre: str, fuente_etiqueta: str,
) -> Path:
    ruta_proc = ruta_sqlite.with_suffix(ruta_sqlite.suffix + ".procedencia.json")
    contenido = {
        "base": ruta_sqlite.name,
        "generado_en": datetime.now(timezone.utc).isoformat(),
        "importador": "atlas_core.geografia.importador_osm",
        "importador_version": VERSION_IMPORTADOR,
        "region_filtro": region,
        "region_nombre": region_nombre,
        "fuente_etiqueta": fuente_etiqueta,
        "fuente": {
            "archivo": ruta_osm.name,
            "ruta_absoluta": str(ruta_osm.resolve()),
            "lector": resultado.lector,
            "bytes": ruta_osm.stat().st_size,
            "sha256": _sha256(ruta_osm),
            "modificado_en": datetime.fromtimestamp(
                ruta_osm.stat().st_mtime, timezone.utc
            ).isoformat(),
        },
        "conteos": resultado.conteos,
        "nota": (
            "Datos derivados de OpenStreetMap (ODbL). Importador offline; el "
            "Motor en runtime sólo consume este SQLite, nunca el PBF ni osmium."
        ),
    }
    ruta_proc.write_text(
        json.dumps(contenido, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return ruta_proc


def importar_a_sqlite(
    ruta_osm: str | Path,
    ruta_sqlite: str | Path,
    *,
    region: str = REGION_METROPOLITANA,
    fuente: str = "OSM",
    reemplazar: bool = False,
    limite: int | None = None,
    escribir_meta: bool = True,
) -> ResultadoImportacion:
    """Pipeline completo: OSM -> filas -> ``BaseGeograficaLocalSQLite.
    importar_filas`` -> ``<sqlite>.procedencia.json``."""
    from atlas_core.geografia.base_local import BaseGeograficaLocalSQLite

    ruta_osm = Path(ruta_osm)
    ruta_sqlite = Path(ruta_sqlite)
    resultado = construir_filas_desde_osm(ruta_osm, region=region, limite=limite)

    base = BaseGeograficaLocalSQLite(ruta_sqlite)
    escritas = base.importar_filas(resultado.filas, fuente=fuente, reemplazar=reemplazar)
    resultado.conteos["filas_escritas"] = escritas

    if escribir_meta:
        try:
            from atlas_core.geografia import cargar_geografia

            geografia = cargar_geografia("CL")
            unidad = geografia.buscar_por_codigo(region)
            region_nombre = unidad.nombre_canonico if unidad else region
        except Exception:  # pragma: no cover - defensivo
            region_nombre = region
        escribir_procedencia(
            ruta_sqlite, ruta_osm, resultado,
            region=region, region_nombre=region_nombre, fuente_etiqueta=fuente,
        )
    return resultado


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _construir_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m atlas_core.geografia.importador_osm",
        description=(
            "Importador OFFLINE OSM/PBF -> base geográfica local Atlas (RM). "
            "Periférico: el Motor en runtime nunca necesita PBF ni osmium."
        ),
    )
    parser.add_argument(
        "--pbf", required=True, metavar="RUTA",
        help="extracto OSM: .osm/.xml (sin dependencias) o .osm.pbf/.pbf/.osm.bz2 (requiere osmium)",
    )
    parser.add_argument(
        "--salida", metavar="RUTA",
        help="SQLite destino (por defecto: datos_privados/geografia/base_local_rm.sqlite)",
    )
    parser.add_argument("--region", default=REGION_METROPOLITANA, help="código CUT de región (def. 13 = RM)")
    parser.add_argument("--fuente", default="OSM", help="etiqueta de procedencia por fila (def. OSM)")
    parser.add_argument("--reemplazar", action="store_true", help="vacía la tabla antes de importar")
    parser.add_argument("--limite", type=int, default=None, help="máx. de objetos con dirección a procesar (pruebas)")
    parser.add_argument("--dry-run", action="store_true", help="no escribe nada; sólo informa conteos")
    parser.add_argument("--json", action="store_true", help="salida en JSON")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _construir_parser().parse_args(argv)
    ruta_osm = Path(args.pbf)

    if args.dry_run:
        resultado = construir_filas_desde_osm(ruta_osm, region=args.region, limite=args.limite)
        ruta_sqlite = None
    else:
        if args.salida:
            ruta_sqlite = Path(args.salida)
        else:
            from atlas_core.almacenamiento_portable import ruta_datos_privados
            from atlas_core.geografia.base_local import NOMBRE_ARCHIVO_PREDETERMINADO

            ruta_sqlite = ruta_datos_privados("geografia") / NOMBRE_ARCHIVO_PREDETERMINADO
        resultado = importar_a_sqlite(
            ruta_osm, ruta_sqlite, region=args.region, fuente=args.fuente,
            reemplazar=args.reemplazar, limite=args.limite,
        )

    if args.json:
        print(json.dumps({
            "salida_sqlite": str(ruta_sqlite) if ruta_sqlite else None,
            "dry_run": bool(args.dry_run),
            "lector": resultado.lector,
            "conteos": resultado.conteos,
        }, ensure_ascii=False, indent=2))
    else:
        print(resultado.resumen())
        if ruta_sqlite is not None:
            print(f"sqlite   -> {ruta_sqlite}")
            print(f"procedencia -> {ruta_sqlite}.procedencia.json")
        else:
            print("dry-run: no se escribió nada")
    return 0


if __name__ == "__main__":
    sys.exit(main())
