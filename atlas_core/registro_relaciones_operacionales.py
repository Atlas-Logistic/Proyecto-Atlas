"""Registro portable de relaciones guía--transporte--chofer--patentes.

No es un reporte ni un cache: vive en la raíz Atlas sincronizada, se actualiza
por unión idempotente y conserva la procedencia de cada observación.

Garantías:

* Integridad: un registro ausente equivale a vacío; uno ilegible, de versión
  desconocida o estructuralmente inválido lanza ``RegistroIlegible`` /
  ``RegistroIncompatible`` y JAMÁS se interpreta como vacío ni se sobrescribe.
* Procedencias: una fuente se identifica sin ``observado_en`` ni ``sha256``;
  repetir una regeneración no modifica una relación ya registrada.
* Activación: el consumidor operacional sólo abandona los reportes históricos
  cuando la migración de esa empresa está completa, verificada y activada
  (``relaciones_si_activo``). Antes de eso devuelve ``None`` y el llamador usa
  el lector histórico vigente.
* Migración explícita, reanudable e idempotente: confirma por lotes, y cada
  lote guarda relaciones y avance en la MISMA escritura atómica. Un cerrojo
  local de sistema operativo (liberado por el SO si el proceso muere) impide
  dos migraciones simultáneas, y otro cerrojo breve serializa cada escritura,
  que siempre relee el archivo bajo cerrojo: ninguna escritura concurrente
  del mismo equipo se pierde.
* Nunca crea ni modifica ``confirmaciones_humanas``.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable, Iterator, Mapping, TypeVar

from atlas_core.almacenamiento_portable import escribir_json_atomico

VERSION = 1
EMPRESA_LEGADA = "oficina"
CAMPOS = ("numero_guia", "numero_transporte", "rut_chofer", "patente_tracto", "patente_rampla")

TIPO_DATASET = "dataset_operacional"
TIPO_MIGRADO = "reporte_historico_migrado"
ESTADO_EN_CURSO = "en_curso"
ESTADO_COMPLETA = "completa"
ESTADO_VERIFICADA = "verificada"
LOTE_MIGRACION = 50
ESPERA_ESCRITURA_S = 5.0
# Datos de observación, no de identidad: no distinguen una fuente de otra.
_CAMPOS_NO_IDENTITARIOS = frozenset({"observado_en", "sha256"})

_T = TypeVar("_T")


class RegistroRelacionesError(ValueError):
    codigo = "REGISTRO_ERROR"


class RegistroIlegible(RegistroRelacionesError):
    codigo = "REGISTRO_ILEGIBLE"


class RegistroIncompatible(RegistroRelacionesError):
    codigo = "REGISTRO_INCOMPATIBLE"


class RegistroOcupado(RegistroRelacionesError):
    codigo = "REGISTRO_OCUPADO"


class MigracionNoVerificada(RegistroRelacionesError):
    codigo = "MIGRACION_NO_VERIFICADA"


# --------------------------------------------------------------------------
# Rutas y cerrojos
# --------------------------------------------------------------------------

def ruta_registro(raiz: str | Path) -> Path:
    """Archivo privado, portable y respaldable por Drive; no es la única copia."""
    return Path(raiz) / "catalogos_privados" / "registro_relaciones_operacionales.json"


def _directorio_local() -> Path:
    """Fuera de la raíz sincronizada: los cerrojos nunca viajan por Drive."""
    override = os.environ.get("ATLAS_CACHE_DIR")
    if override:
        return Path(override)
    local = os.environ.get("LOCALAPPDATA")
    return (Path(local) if local else Path.home() / "AppData" / "Local") / "Atlas" / "cache"


def ruta_cerrojo(raiz: str | Path, tipo: str) -> Path:
    huella = hashlib.sha256(str(Path(raiz).resolve()).encode("utf-8")).hexdigest()[:16]
    return _directorio_local() / "registro_relaciones" / f"{huella}.{tipo}.lock"


if sys.platform == "win32":
    import msvcrt

    def _bloquear(archivo) -> None:
        archivo.seek(0)
        msvcrt.locking(archivo.fileno(), msvcrt.LK_NBLCK, 1)

    def _desbloquear(archivo) -> None:
        archivo.seek(0)
        msvcrt.locking(archivo.fileno(), msvcrt.LK_UNLCK, 1)
else:  # pragma: no cover - CASA y OFICINA son Windows
    import fcntl

    def _bloquear(archivo) -> None:
        fcntl.flock(archivo.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _desbloquear(archivo) -> None:
        fcntl.flock(archivo.fileno(), fcntl.LOCK_UN)


@contextmanager
def _cerrojo(ruta: Path, espera: float) -> Iterator[None]:
    """Cerrojo exclusivo del SO; si el proceso muere, el SO lo libera."""
    ruta.parent.mkdir(parents=True, exist_ok=True)
    archivo = open(ruta, "a+b")
    try:
        limite = time.monotonic() + max(espera, 0.0)
        while True:
            try:
                _bloquear(archivo)
                break
            except OSError:
                if time.monotonic() >= limite:
                    raise RegistroOcupado(f"cerrojo ocupado: {ruta.name}") from None
                time.sleep(0.05)
        try:
            yield
        finally:
            _desbloquear(archivo)
    finally:
        archivo.close()


# --------------------------------------------------------------------------
# Lectura estricta y en memoria
# --------------------------------------------------------------------------

def _vacio() -> dict[str, object]:
    return {"version": VERSION, "empresas": {}}


def _validar(valor: object) -> dict[str, object]:
    if not isinstance(valor, dict):
        raise RegistroIlegible("el registro no es un objeto JSON")
    version = valor.get("version")
    if not isinstance(version, int) or isinstance(version, bool):
        raise RegistroIlegible("el registro no declara una versión entera")
    if version != VERSION:
        raise RegistroIncompatible(f"versión {version}; esta versión de Atlas sólo entiende {VERSION}")
    empresas = valor.get("empresas")
    if not isinstance(empresas, dict):
        raise RegistroIlegible("'empresas' no es un objeto")
    for empresa_id, empresa in empresas.items():
        if not isinstance(empresa, dict) or not isinstance(empresa.get("relaciones"), list):
            raise RegistroIlegible(f"empresa {empresa_id!r} sin lista de relaciones")
        migracion = empresa.get("migracion")
        if migracion is not None and (
            not isinstance(migracion, dict) or not isinstance(migracion.get("reportes", {}), dict)
        ):
            raise RegistroIlegible(f"empresa {empresa_id!r} con estado de migración inválido")
        for entrada in empresa["relaciones"]:
            if not (
                isinstance(entrada, dict) and isinstance(entrada.get("clave"), str)
                and isinstance(entrada.get("relacion"), dict)
                and all(isinstance(entrada.get(c), list) for c in ("fuentes", "confirmaciones_humanas", "conflictos"))
            ):
                raise RegistroIlegible(f"empresa {empresa_id!r} con una relación estructuralmente inválida")
    return valor


def _huella_archivo(ruta: Path) -> tuple[int, int] | None:
    try:
        info = ruta.stat()
    except FileNotFoundError:
        return None
    except OSError as error:
        raise RegistroIlegible(f"no se puede consultar el registro: {error}") from error
    return (info.st_mtime_ns, info.st_size)


def _leer_fresco(raiz: str | Path) -> dict[str, object]:
    """Copia propia, mutable, leída del disco ahora."""
    ruta = ruta_registro(raiz)
    try:
        texto = ruta.read_text(encoding="utf-8")
    except FileNotFoundError:
        return _vacio()
    except (OSError, UnicodeDecodeError) as error:
        raise RegistroIlegible(f"no se puede leer el registro: {error}") from error
    try:
        valor = json.loads(texto)
    except json.JSONDecodeError as error:
        raise RegistroIlegible(f"JSON inválido: {error}") from error
    return _validar(valor)


# ruta -> (huella stat, registro parseado). Sólo lectura: nunca se muta.
_MEMORIA: dict[str, tuple[tuple[int, int], dict[str, object]]] = {}


def _leer_compartido(raiz: str | Path) -> dict[str, object]:
    """Lectura sin reparsear si el archivo no cambió. NO mutar el resultado."""
    ruta = ruta_registro(raiz)
    clave = str(ruta)
    huella = _huella_archivo(ruta)
    if huella is None:
        _MEMORIA.pop(clave, None)
        return _vacio()
    previo = _MEMORIA.get(clave)
    if previo is not None and previo[0] == huella:
        return previo[1]
    registro = _leer_fresco(raiz)
    _MEMORIA[clave] = (huella, registro)
    return registro


def _modificar(raiz: str | Path, operar: Callable[[dict[str, object]], tuple[bool, _T]], *, espera: float) -> _T:
    """Transacción: cerrojo, relectura fresca, cambio y escritura sólo si cambió."""
    ruta = ruta_registro(raiz)
    with _cerrojo(ruta_cerrojo(raiz, "escritura"), espera):
        registro = _leer_fresco(raiz)
        cambio, resultado = operar(registro)
        if cambio:
            escribir_json_atomico(ruta, registro)
            huella = _huella_archivo(ruta)
            if huella is not None:
                _MEMORIA[str(ruta)] = (huella, registro)
        return resultado


# --------------------------------------------------------------------------
# Unión idempotente
# --------------------------------------------------------------------------

def _clave(relacion: Mapping[str, object]) -> str:
    return "\x1f".join(str(relacion.get(c, "")).strip() for c in CAMPOS)


def _base(relacion: Mapping[str, object]) -> tuple[str, ...]:
    return tuple(str(relacion.get(c, "")) for c in CAMPOS[:3])


def _normalizar(fila: Mapping[str, object]) -> dict[str, str] | None:
    valor = {c: str(fila.get(c, "") or "").strip() for c in CAMPOS}
    # Mismo contrato del lector histórico: no inventa una asociación sin guía y RUT.
    return valor if valor["numero_guia"] and valor["rut_chofer"] else None


def _identidad_fuente(fuente: Mapping[str, object]) -> str:
    return json.dumps(
        {k: v for k, v in fuente.items() if k not in _CAMPOS_NO_IDENTITARIOS},
        ensure_ascii=False, sort_keys=True, default=str,
    )


class _Indice:
    def __init__(self, empresa: Mapping[str, object]) -> None:
        self.por_clave: dict[str, dict[str, object]] = {}
        self.por_base: dict[tuple[str, ...], list[dict[str, object]]] = {}
        for entrada in empresa.get("relaciones", []) if isinstance(empresa, Mapping) else []:
            self.agregar(entrada)

    def agregar(self, entrada: dict[str, object]) -> None:
        self.por_clave[str(entrada["clave"])] = entrada
        self.por_base.setdefault(_base(entrada["relacion"]), []).append(entrada)

    def tiene_fuente(self, clave: str, identidad: str) -> bool:
        entrada = self.por_clave.get(clave)
        return entrada is not None and any(
            isinstance(f, Mapping) and _identidad_fuente(f) == identidad for f in entrada["fuentes"]
        )


def _unir(
    empresa: dict[str, object], relaciones: Iterable[Mapping[str, object]], procedencia: Mapping[str, object],
    *, ahora: str, indice: _Indice,
) -> tuple[int, int]:
    """Nunca cambia una confirmación ni borra conflictos o fuentes."""
    identidad = _identidad_fuente(procedencia)
    agregadas = fuentes_agregadas = 0
    for cruda in relaciones:
        relacion = _normalizar(cruda)
        if relacion is None:
            continue
        clave = _clave(relacion)
        entrada = indice.por_clave.get(clave)
        if entrada is None:
            entrada = {"clave": clave, "relacion": relacion, "fuentes": [], "confirmaciones_humanas": [], "conflictos": []}
            # Valores documentales discrepantes se conservan, nunca se elige
            # uno ni se convierte evidencia en confirmación humana.
            for otra in indice.por_base.get(_base(relacion), []):
                if otra["relacion"] == relacion:
                    continue
                conflicto = {"tipo": "RELACION_DOCUMENTAL_DISCREPANTE", "con": str(otra["clave"])}
                if conflicto not in entrada["conflictos"]:
                    entrada["conflictos"].append(conflicto)
                reciproco = {"tipo": "RELACION_DOCUMENTAL_DISCREPANTE", "con": clave}
                if reciproco not in otra["conflictos"]:
                    otra["conflictos"].append(reciproco)
            empresa["relaciones"].append(entrada)
            indice.agregar(entrada)
            agregadas += 1
        if not indice.tiene_fuente(clave, identidad):
            fuente = dict(procedencia)
            fuente["observado_en"] = fuente.get("observado_en", ahora)
            entrada["fuentes"].append(fuente)
            fuentes_agregadas += 1
    return agregadas, fuentes_agregadas


def _ahora() -> str:
    return datetime.now(timezone.utc).isoformat()


def _relaciones_de(empresa: Mapping[str, object] | None) -> list[dict[str, object]]:
    relaciones = empresa.get("relaciones", []) if isinstance(empresa, Mapping) else []
    return [dict(r["relacion"]) for r in relaciones]


# --------------------------------------------------------------------------
# API operacional
# --------------------------------------------------------------------------

def leer_relaciones(raiz: str | Path, *, empresa_id: str = EMPRESA_LEGADA) -> list[dict[str, object]]:
    """Contenido del registro (cero acceso a reportes). Lanza si es ilegible."""
    return _relaciones_de(_leer_compartido(raiz)["empresas"].get(empresa_id))


def _migracion(empresa: Mapping[str, object] | None) -> dict[str, object]:
    migracion = empresa.get("migracion") if isinstance(empresa, Mapping) else None
    return migracion if isinstance(migracion, dict) else {}


def _activa(empresa: Mapping[str, object] | None) -> bool:
    migracion = _migracion(empresa)
    return migracion.get("estado") == ESTADO_VERIFICADA and migracion.get("activo") is True


def relaciones_si_activo(raiz: str | Path, *, empresa_id: str = EMPRESA_LEGADA) -> list[dict[str, object]] | None:
    """Consumidor operacional. ``None`` = el registro aún no reemplaza a los
    históricos para esa empresa (sin migración verificada y activada, o
    registro ilegible/incompatible): el llamador debe usar el lector
    histórico. Nunca abre reportes."""
    try:
        empresa = _leer_compartido(raiz)["empresas"].get(empresa_id)
    except RegistroRelacionesError:
        return None
    return _relaciones_de(empresa) if _activa(empresa) else None


def incorporar_relaciones(
    raiz: str | Path, relaciones: Iterable[Mapping[str, object]], *, empresa_id: str = EMPRESA_LEGADA,
    procedencia: Mapping[str, object], espera: float = ESPERA_ESCRITURA_S,
) -> dict[str, int]:
    """Unión idempotente; sin relación ni fuente nueva no lee bajo cerrojo ni escribe."""
    lista = [r for r in (_normalizar(x) for x in relaciones) if r is not None]
    empresa_actual = _leer_compartido(raiz)["empresas"].get(empresa_id)
    indice = _Indice(empresa_actual or {})
    identidad = _identidad_fuente(procedencia)
    if all(indice.tiene_fuente(_clave(r), identidad) for r in lista):
        return {"relaciones_agregadas": 0, "fuentes_agregadas": 0, "total": len(indice.por_clave)}

    def operar(registro: dict[str, object]) -> tuple[bool, dict[str, int]]:
        empresa = registro["empresas"].setdefault(empresa_id, {"relaciones": []})
        agregadas, fuentes = _unir(empresa, lista, procedencia, ahora=_ahora(), indice=_Indice(empresa))
        resumen = {"relaciones_agregadas": agregadas, "fuentes_agregadas": fuentes, "total": len(empresa["relaciones"])}
        return bool(agregadas or fuentes), resumen

    return _modificar(raiz, operar, espera=espera)


def _asegurar_limite_csv() -> None:
    """``evidencias_documentos`` supera el límite por defecto (131072). Nunca lo baja."""
    limite = sys.maxsize
    while limite > csv.field_size_limit():
        try:
            csv.field_size_limit(limite)
            return
        except OverflowError:
            limite //= 10


def _filas_csv(contenido: bytes) -> list[dict[str, str]] | None:
    _asegurar_limite_csv()
    try:
        return list(csv.DictReader(io.StringIO(contenido.decode("utf-8-sig"), newline=""), delimiter=";"))
    except (UnicodeDecodeError, csv.Error):
        return None


def incorporar_dataset(raiz: str | Path, dataset: str | Path, *, empresa_id: str = EMPRESA_LEGADA) -> dict[str, int]:
    """Actualización incremental desde la fuente operacional, no desde reportes."""
    ruta = Path(dataset)
    try:
        contenido = ruta.read_bytes()
    except OSError:
        return {"relaciones_agregadas": 0, "fuentes_agregadas": 0, "total": 0}
    filas = _filas_csv(contenido)
    if filas is None:
        return {"relaciones_agregadas": 0, "fuentes_agregadas": 0, "total": 0}
    base = Path(raiz)
    return incorporar_relaciones(raiz, filas, empresa_id=empresa_id, procedencia={
        "tipo": TIPO_DATASET,
        "dataset": ruta.relative_to(base).as_posix() if ruta.is_relative_to(base) else ruta.name,
        "sha256": hashlib.sha256(contenido).hexdigest(),
    })


# --------------------------------------------------------------------------
# Migración explícita, verificación y activación
# --------------------------------------------------------------------------

def _extraer_de_bytes(contenido: bytes) -> list[dict[str, str]] | None:
    filas = _filas_csv(contenido)
    if filas is None:
        return None
    salida: list[dict[str, str]] = []
    for viaje in filas:
        try:
            evidencias = json.loads(str(viaje.get("evidencias_documentos", "") or "[]"))
        except (json.JSONDecodeError, TypeError):
            evidencias = []
        for evidencia in evidencias if isinstance(evidencias, list) else []:
            if isinstance(evidencia, dict):
                normalizada = _normalizar(evidencia)
                if normalizada:
                    salida.append(normalizada)
    return salida


def extraer_reporte_historico(ruta: str | Path) -> list[dict[str, str]] | None:
    """Adaptador de migración explícita. No se importa desde el consumidor."""
    try:
        return _extraer_de_bytes(Path(ruta).read_bytes())
    except OSError:
        return None


def _leer_reporte(ruta: Path) -> tuple[str, int, list[dict[str, str]]] | None:
    """Una sola lectura del archivo: huella, tamaño y relaciones. ``None`` = ilegible."""
    try:
        contenido = ruta.read_bytes()
    except OSError:
        return None
    extraidas = _extraer_de_bytes(contenido)
    if extraidas is None:
        return None
    return hashlib.sha256(contenido).hexdigest(), len(contenido), extraidas


def _rutas_reportes(base: Path) -> list[Path]:
    directorio = base / "reportes"
    if not directorio.is_dir():
        return []
    return sorted(c / "viajes.csv" for c in directorio.iterdir() if c.is_dir() and (c / "viajes.csv").is_file())


def _relativa(base: Path, ruta: Path) -> str:
    return ruta.relative_to(base).as_posix()


def migrar_reportes_historicos(
    raiz: str | Path, *, empresa_id: str = EMPRESA_LEGADA, aplicar: bool = False,
    lote: int = LOTE_MIGRACION, espera: float = ESPERA_ESCRITURA_S,
) -> dict[str, object]:
    """Simula por defecto (sin escribir). ``aplicar=True`` es reanudable e
    idempotente: confirma cada ``lote`` reportes junto con su avance; un
    reporte ya migrado con el mismo tamaño no se vuelve a leer. Los reportes
    ilegibles nunca se marcan migrados y dejan la migración ``en_curso``."""
    base = Path(raiz)
    if not aplicar:
        return _simular(base, empresa_id)
    _leer_compartido(base)  # registro ilegible/incompatible: se detiene antes de leer reportes
    with _cerrojo(ruta_cerrojo(base, "migracion"), 0):
        return _aplicar(base, empresa_id, max(int(lote), 1), espera)


def _simular(base: Path, empresa_id: str) -> dict[str, object]:
    relaciones: dict[str, dict[str, str]] = {}
    fuentes: list[dict[str, object]] = []
    ilegibles: list[str] = []
    for ruta in _rutas_reportes(base):
        relativa = _relativa(base, ruta)
        leido = _leer_reporte(ruta)
        if leido is None:
            ilegibles.append(relativa)
            continue
        sha, _tamano, extraidas = leido
        relaciones.update((_clave(r), r) for r in extraidas)
        fuentes.append({"ruta": relativa, "sha256": sha, "cantidad": len(extraidas)})
    resultado: dict[str, object] = {
        "modo": "simulacion", "reportes": len(fuentes), "relaciones_extraidas": len(relaciones),
        "ilegibles": ilegibles, "fuentes": fuentes,
    }
    try:
        empresa = _leer_compartido(base)["empresas"].get(empresa_id)
        migrados = _migracion(empresa).get("reportes", {})
        resultado["registro"] = {
            "legible": True, "estado": _migracion(empresa).get("estado"),
            "pendientes": sum(1 for f in fuentes if f["ruta"] not in migrados),
        }
    except RegistroRelacionesError as error:
        resultado["registro"] = {"legible": False, "codigo": error.codigo, "detalle": str(error)}
    return resultado


def _aplicar(base: Path, empresa_id: str, lote: int, espera: float) -> dict[str, object]:
    rutas = _rutas_reportes(base)
    migrados_previos = dict(_migracion(_leer_compartido(base)["empresas"].get(empresa_id)).get("reportes", {}))
    ilegibles: list[str] = []
    extraidas_unicas: set[str] = set()
    totales = {"relaciones_agregadas": 0, "fuentes_agregadas": 0, "procesados": 0}
    omitidos = 0
    pendientes: list[tuple[str, str, int, list[dict[str, str]]]] = []

    def confirmar(items: list[tuple[str, str, int, list[dict[str, str]]]], *, final: bool) -> str | None:
        def operar(registro: dict[str, object]) -> tuple[bool, str | None]:
            empresa = registro["empresas"].setdefault(empresa_id, {"relaciones": []})
            migracion = empresa.setdefault("migracion", {})
            reportes = migracion.setdefault("reportes", {})
            ahora = _ahora()
            cambio = False
            if migracion.get("estado") is None:
                migracion.update({"estado": ESTADO_EN_CURSO, "iniciada_en": ahora})
                cambio = True
            indice = _Indice(empresa)
            for relativa, sha, tamano, extraidas in items:
                agregadas, fuentes = _unir(
                    empresa, extraidas, {"tipo": TIPO_MIGRADO, "ruta": relativa, "sha256": sha},
                    ahora=ahora, indice=indice,
                )
                totales["relaciones_agregadas"] += agregadas
                totales["fuentes_agregadas"] += fuentes
                avance = {"sha256": sha, "tamano": tamano, "relaciones": len(extraidas)}
                if reportes.get(relativa) != avance:
                    reportes[relativa] = avance
                    cambio = True
                cambio = cambio or bool(agregadas or fuentes)
            if final and migracion.get("estado") == ESTADO_EN_CURSO and not ilegibles and all(
                _relativa(base, r) in reportes for r in rutas
            ):
                migracion.update({"estado": ESTADO_COMPLETA, "completada_en": ahora})
                cambio = True
            return cambio, migracion.get("estado")

        return _modificar(base, operar, espera=espera)

    for ruta in rutas:
        relativa = _relativa(base, ruta)
        try:
            tamano_actual = ruta.stat().st_size
        except OSError:
            ilegibles.append(relativa)
            continue
        previo = migrados_previos.get(relativa)
        if isinstance(previo, dict) and previo.get("tamano") == tamano_actual:
            omitidos += 1
            continue
        leido = _leer_reporte(ruta)
        if leido is None:
            ilegibles.append(relativa)
            continue
        sha, tamano, extraidas = leido
        extraidas_unicas.update(_clave(r) for r in extraidas)
        pendientes.append((relativa, sha, tamano, extraidas))
        totales["procesados"] += 1
        if len(pendientes) >= lote:
            confirmar(pendientes, final=False)
            pendientes = []
    estado = confirmar(pendientes, final=True)
    return {
        "modo": "aplicar", "reportes": len(rutas) - len(ilegibles), "relaciones_extraidas": len(extraidas_unicas),
        "ilegibles": ilegibles, "omitidos_ya_migrados": omitidos, "procesados": totales["procesados"],
        "relaciones_agregadas": totales["relaciones_agregadas"], "fuentes_agregadas": totales["fuentes_agregadas"],
        "relaciones_registradas": len(leer_relaciones(base, empresa_id=empresa_id)), "estado": estado,
    }


def verificar_migracion(
    raiz: str | Path, *, empresa_id: str = EMPRESA_LEGADA, espera: float = ESPERA_ESCRITURA_S,
) -> dict[str, object]:
    """Relee TODOS los reportes actuales (sólo lectura) y exige que cada
    relación esté en el registro. Si la migración está completa y todo
    calza, la marca ``verificada``; si no, no escribe nada."""
    base = Path(raiz)
    empresa = _leer_compartido(base)["empresas"].get(empresa_id)
    migracion = _migracion(empresa)
    migrados = migracion.get("reportes", {})
    claves = set(_Indice(empresa or {}).por_clave)
    ilegibles: list[str] = []
    cambiados: list[str] = []
    no_migrados: list[str] = []
    ausentes: set[str] = set()
    extraidas_unicas: set[str] = set()
    rutas = _rutas_reportes(base)
    for ruta in rutas:
        relativa = _relativa(base, ruta)
        leido = _leer_reporte(ruta)
        if leido is None:
            ilegibles.append(relativa)
            continue
        sha, _tamano, extraidas = leido
        previo = migrados.get(relativa)
        if not isinstance(previo, dict):
            no_migrados.append(relativa)  # aceptable si el dataset ya aportó sus relaciones
        elif previo.get("sha256") != sha:
            cambiados.append(relativa)
        for relacion in extraidas:
            clave = _clave(relacion)
            extraidas_unicas.add(clave)
            if clave not in claves:
                ausentes.add(clave)
    estado_previo = migracion.get("estado")
    ok = estado_previo in (ESTADO_COMPLETA, ESTADO_VERIFICADA) and not ilegibles and not ausentes
    resultado: dict[str, object] = {
        "ok": ok, "estado_previo": estado_previo, "reportes_leidos": len(rutas) - len(ilegibles),
        "relaciones_extraidas": len(extraidas_unicas), "relaciones_registradas": len(claves),
        "relaciones_ausentes": len(ausentes), "ejemplos_ausentes": sorted(ausentes)[:10],
        "ilegibles": ilegibles, "cambiados": cambiados, "no_migrados": no_migrados,
    }
    if ok and estado_previo == ESTADO_COMPLETA:
        def operar(registro: dict[str, object]) -> tuple[bool, str]:
            actual = _migracion(registro["empresas"].get(empresa_id))
            if actual.get("estado") != ESTADO_COMPLETA:
                return False, str(actual.get("estado"))
            actual.update({"estado": ESTADO_VERIFICADA, "verificada_en": _ahora(), "verificacion": {
                "reportes": resultado["reportes_leidos"], "relaciones_extraidas": len(extraidas_unicas),
                "relaciones_registradas": len(claves),
            }})
            return True, ESTADO_VERIFICADA
        resultado["estado"] = _modificar(base, operar, espera=espera)
    else:
        resultado["estado"] = estado_previo
    return resultado


def _cambiar_activacion(raiz: str | Path, empresa_id: str, activo: bool, espera: float) -> dict[str, object]:
    def operar(registro: dict[str, object]) -> tuple[bool, dict[str, object]]:
        migracion = _migracion(registro["empresas"].get(empresa_id))
        if activo and migracion.get("estado") != ESTADO_VERIFICADA:
            raise MigracionNoVerificada(
                f"empresa {empresa_id!r}: estado {migracion.get('estado')!r}; se requiere migración verificada"
            )
        if not migracion or migracion.get("activo", False) is activo:
            return False, {"empresa": empresa_id, "activo": bool(migracion.get("activo", False)), "cambio": False}
        migracion["activo"] = activo
        migracion["activado_en" if activo else "desactivado_en"] = _ahora()
        return True, {"empresa": empresa_id, "activo": activo, "cambio": True}

    return _modificar(raiz, operar, espera=espera)


def activar_registro(raiz: str | Path, *, empresa_id: str = EMPRESA_LEGADA, espera: float = ESPERA_ESCRITURA_S) -> dict[str, object]:
    """El consumidor deja los históricos sólo desde aquí, y sólo si está verificada."""
    return _cambiar_activacion(raiz, empresa_id, True, espera)


def desactivar_registro(raiz: str | Path, *, empresa_id: str = EMPRESA_LEGADA, espera: float = ESPERA_ESCRITURA_S) -> dict[str, object]:
    """Reversión inmediata: el consumidor vuelve al lector histórico."""
    return _cambiar_activacion(raiz, empresa_id, False, espera)


def estado_registro(raiz: str | Path, *, empresa_id: str = EMPRESA_LEGADA) -> dict[str, object]:
    try:
        empresa = _leer_compartido(raiz)["empresas"].get(empresa_id)
    except RegistroRelacionesError as error:
        return {"legible": False, "codigo": error.codigo, "detalle": str(error), "activo": False}
    migracion = _migracion(empresa)
    return {
        "legible": True, "empresa": empresa_id, "relaciones": len(_relaciones_de(empresa)),
        "estado_migracion": migracion.get("estado"), "activo": _activa(empresa),
        "reportes_migrados": len(migracion.get("reportes", {})),
        **{k: migracion[k] for k in ("iniciada_en", "completada_en", "verificada_en", "verificacion") if k in migracion},
    }
