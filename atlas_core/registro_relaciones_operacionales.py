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
* Diario incremental: el ciclo normal (dataset y reportes publicados) no
  reescribe el registro base; agrega sólo la unión nueva a un segmento
  diario ``registro_relaciones_diario/<AAAAMMDD>.json``. El registro vigente
  es SIEMPRE base + segmentos reproducidos en orden con la misma unión
  idempotente, así que reproducir un segmento ya incorporado (corte a mitad
  de una consolidación, copia en conflicto de Drive) no cambia nada. La
  custodia Cloud sube sólo el segmento del día, no el registro completo.
  La consolidación (``consolidar_diario``) es explícita y controlada.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
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
TIPO_PUBLICADO = "reporte_vigente_publicado"
ESTADO_EN_CURSO = "en_curso"
ESTADO_COMPLETA = "completa"
ESTADO_VERIFICADA = "verificada"
LOTE_MIGRACION = 50
ESPERA_ESCRITURA_S = 5.0
CARPETA_DIARIO = "registro_relaciones_diario"
TIPO_SEGMENTO = "diario_registro_relaciones"
_NOMBRE_SEGMENTO = re.compile(r"^(\d{8})\.json$")
# Datos de observación, no de identidad: no distinguen una fuente de otra.
# ``ruta`` (reporte histórico migrado) tampoco: cada relación aparece en
# cientos de snapshots y una fuente por snapshot haría crecer el registro
# -- que la custodia Cloud sube completo en cada cambio -- sin información
# nueva; el detalle por reporte queda en ``migracion.reportes``.
_CAMPOS_NO_IDENTITARIOS = frozenset({"observado_en", "sha256", "ruta"})

_T = TypeVar("_T")


class RegistroRelacionesError(ValueError):
    codigo = "REGISTRO_ERROR"


class RegistroIlegible(RegistroRelacionesError):
    codigo = "REGISTRO_ILEGIBLE"


class RegistroIncompatible(RegistroRelacionesError):
    codigo = "REGISTRO_INCOMPATIBLE"


class RegistroOcupado(RegistroRelacionesError):
    codigo = "REGISTRO_OCUPADO"


class MigracionNoPreparada(RegistroRelacionesError):
    codigo = "MIGRACION_NO_PREPARADA"


class MigracionNoVerificada(RegistroRelacionesError):
    codigo = "MIGRACION_NO_VERIFICADA"


# --------------------------------------------------------------------------
# Rutas y cerrojos
# --------------------------------------------------------------------------

def ruta_registro(raiz: str | Path) -> Path:
    """Archivo privado, portable y respaldable por Drive; no es la única copia."""
    return Path(raiz) / "catalogos_privados" / "registro_relaciones_operacionales.json"


def ruta_diario(raiz: str | Path) -> Path:
    """Segmentos del diario, junto al registro base (misma custodia)."""
    return Path(raiz) / "catalogos_privados" / CARPETA_DIARIO


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


def _leer_base(raiz: str | Path) -> dict[str, object]:
    """Sólo el registro base (sin diario): copia propia, mutable."""
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


def _segmentos(raiz: str | Path) -> list[Path]:
    """Todo ``*.json`` visible del diario, en orden de nombre. También las
    copias en conflicto de Drive (``20261106 (1).json``): la unión es
    idempotente, así que reproducirlas nunca duplica ni pierde nada."""
    directorio = ruta_diario(raiz)
    try:
        archivos = [p for p in directorio.iterdir() if p.is_file()]
    except FileNotFoundError:
        return []
    except OSError as error:
        raise RegistroIlegible(f"no se puede listar el diario: {error}") from error
    return sorted(
        (p for p in archivos if p.suffix.lower() == ".json" and not p.name.startswith(".")),
        key=lambda p: p.name,
    )


def _validar_segmento(valor: object, nombre: str) -> dict[str, object]:
    if not isinstance(valor, dict):
        raise RegistroIlegible(f"segmento {nombre}: no es un objeto JSON")
    version = valor.get("version")
    if not isinstance(version, int) or isinstance(version, bool):
        raise RegistroIlegible(f"segmento {nombre}: sin versión entera")
    if version != VERSION:
        raise RegistroIncompatible(f"segmento {nombre}: versión {version}; sólo se entiende {VERSION}")
    entradas = valor.get("entradas")
    if valor.get("tipo") != TIPO_SEGMENTO or not isinstance(entradas, list):
        raise RegistroIlegible(f"segmento {nombre}: estructura inválida")
    for entrada in entradas:
        if not (
            isinstance(entrada, dict) and isinstance(entrada.get("empresa"), str)
            and isinstance(entrada.get("observado_en"), str)
            and isinstance(entrada.get("procedencia"), dict)
            and isinstance(entrada["procedencia"].get("tipo"), str)
            and isinstance(entrada.get("relaciones"), list)
            and all(isinstance(r, dict) for r in entrada["relaciones"])
        ):
            raise RegistroIlegible(f"segmento {nombre}: entrada estructuralmente inválida")
    return valor


def _segmento_vacio() -> dict[str, object]:
    return {"version": VERSION, "tipo": TIPO_SEGMENTO, "entradas": []}


def _leer_segmento(ruta: Path) -> dict[str, object]:
    try:
        texto = ruta.read_text(encoding="utf-8")
    except FileNotFoundError:
        return _segmento_vacio()
    except (OSError, UnicodeDecodeError) as error:
        raise RegistroIlegible(f"no se puede leer el segmento {ruta.name}: {error}") from error
    try:
        valor = json.loads(texto)
    except json.JSONDecodeError as error:
        raise RegistroIlegible(f"segmento {ruta.name}: JSON inválido: {error}") from error
    return _validar_segmento(valor, ruta.name)


def _reproducir(registro: dict[str, object], segmentos: Iterable[Mapping[str, object]]) -> None:
    """Aplica los segmentos sobre ``registro`` con la MISMA unión del ciclo
    directo: el resultado equivale a haber escrito cada entrada en el
    registro base, y reproducir dos veces una entrada no cambia nada."""
    indices: dict[str, _Indice] = {}
    for segmento in segmentos:
        for entrada in segmento["entradas"]:
            empresa_id = entrada["empresa"]
            empresa = registro["empresas"].setdefault(empresa_id, {"relaciones": []})
            indice = indices.get(empresa_id)
            if indice is None:
                indice = indices[empresa_id] = _Indice(empresa)
            _unir(empresa, entrada["relaciones"], entrada["procedencia"], ahora=entrada["observado_en"], indice=indice)


def _leer_fresco(raiz: str | Path) -> dict[str, object]:
    """Registro vigente (base + diario): copia propia, leída del disco ahora."""
    registro = _leer_base(raiz)
    _reproducir(registro, [_leer_segmento(p) for p in _segmentos(raiz)])
    return registro


# ruta del base -> (huellas stat de base y segmentos, registro vigente). Nunca se muta.
_MEMORIA: dict[str, tuple[tuple[object, ...], dict[str, object]]] = {}


def _huella_vigente(raiz: str | Path) -> tuple[object, ...]:
    segmentos = []
    for ruta in _segmentos(raiz):
        huella = _huella_archivo(ruta)
        if huella is not None:
            segmentos.append((ruta.name, huella))
    return (_huella_archivo(ruta_registro(raiz)), tuple(segmentos))


def _leer_compartido(raiz: str | Path) -> dict[str, object]:
    """Registro vigente sin reparsear si nada cambió. NO mutar el resultado."""
    clave = str(ruta_registro(raiz))
    huella = _huella_vigente(raiz)
    if huella == (None, ()):
        _MEMORIA.pop(clave, None)
        return _vacio()
    previo = _MEMORIA.get(clave)
    if previo is not None and previo[0] == huella:
        return previo[1]
    registro = _leer_fresco(raiz)
    _MEMORIA[clave] = (huella, registro)
    return registro


def _modificar(raiz: str | Path, operar: Callable[[dict[str, object]], tuple[bool, _T]], *, espera: float) -> _T:
    """Transacción sobre el registro BASE (migración, verificación,
    activación): cerrojo, relectura fresca, cambio y escritura sólo si
    cambió. El diario no se toca; al leer se reproduce encima."""
    ruta = ruta_registro(raiz)
    with _cerrojo(ruta_cerrojo(raiz, "escritura"), espera):
        _leer_fresco(raiz)  # un segmento ilegible también bloquea: nunca se escribe a ciegas
        registro = _leer_base(raiz)
        cambio, resultado = operar(registro)
        if cambio:
            escribir_json_atomico(ruta, registro)
            _MEMORIA.pop(str(ruta), None)
        return resultado


def _dia(instante: str) -> str:
    return instante[:10].replace("-", "")


def _anotar_diario(
    raiz: str | Path, empresa_id: str, relaciones: list[dict[str, str]], procedencia: Mapping[str, object],
    *, espera: float,
) -> dict[str, int]:
    """Ciclo normal: agrega al segmento del día sólo la unión nueva. El
    registro base no se reescribe; la custodia sube sólo este segmento."""
    with _cerrojo(ruta_cerrojo(raiz, "escritura"), espera):
        vigente = _leer_fresco(raiz)
        empresa = vigente["empresas"].setdefault(empresa_id, {"relaciones": []})
        indice = _Indice(empresa)
        identidad = _identidad_fuente(procedencia)
        nuevas = [r for r in relaciones if not indice.tiene_fuente(_clave(r), identidad)]
        if not nuevas:
            return {"relaciones_agregadas": 0, "fuentes_agregadas": 0, "total": len(indice.por_clave)}
        ahora = _ahora()
        ruta = ruta_diario(raiz) / f"{_dia(ahora)}.json"
        segmento = _leer_segmento(ruta)
        segmento["entradas"].append({
            "empresa": empresa_id, "observado_en": ahora, "procedencia": dict(procedencia), "relaciones": nuevas,
        })
        agregadas, fuentes = _unir(empresa, nuevas, procedencia, ahora=ahora, indice=indice)
        escribir_json_atomico(ruta, segmento)
        _MEMORIA.pop(str(ruta_registro(raiz)), None)
        return {"relaciones_agregadas": agregadas, "fuentes_agregadas": fuentes, "total": len(empresa["relaciones"])}


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

def contenido_vigente(raiz: str | Path) -> dict[str, object]:
    """Registro vigente completo (base + diario), copia propia: auditoría y
    pruebas. Lanza si el base o algún segmento es ilegible."""
    return _leer_fresco(raiz)


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


def requiere_incorporacion_dataset(raiz: str | Path, *, empresa_id: str = EMPRESA_LEGADA) -> bool:
    """La regeneración sólo alimenta el registro una vez completa la
    migración: antes, los snapshots siguen siendo la fuente y no se escribe
    nada. Un registro ilegible devuelve ``True`` para que el intento se
    informe (``REGISTRO_ILEGIBLE``) sin escribir."""
    try:
        empresa = _leer_compartido(raiz)["empresas"].get(empresa_id)
    except RegistroRelacionesError:
        return True
    return _migracion(empresa).get("estado") in (ESTADO_COMPLETA, ESTADO_VERIFICADA)


def incorporar_relaciones(
    raiz: str | Path, relaciones: Iterable[Mapping[str, object]], *, empresa_id: str = EMPRESA_LEGADA,
    procedencia: Mapping[str, object], espera: float = ESPERA_ESCRITURA_S,
) -> dict[str, int]:
    """Unión idempotente; sin relación ni fuente nueva no lee bajo cerrojo ni
    escribe. Lo nuevo va al segmento diario: nunca reescribe el registro base."""
    lista = [r for r in (_normalizar(x) for x in relaciones) if r is not None]
    empresa_actual = _leer_compartido(raiz)["empresas"].get(empresa_id)
    indice = _Indice(empresa_actual or {})
    identidad = _identidad_fuente(procedencia)
    if all(indice.tiene_fuente(_clave(r), identidad) for r in lista):
        return {"relaciones_agregadas": 0, "fuentes_agregadas": 0, "total": len(indice.por_clave)}
    return _anotar_diario(raiz, empresa_id, lista, procedencia, espera=espera)


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


class ReporteIlegible(RegistroRelacionesError):
    codigo = "REPORTE_ILEGIBLE"


def capturar_reporte_publicado(
    raiz: str | Path, viajes_csv: str | Path, *, empresa_id: str = EMPRESA_LEGADA,
) -> dict[str, int]:
    """Incorpora la misma evidencia que el lector histórico leería de ese
    ``viajes.csv`` (``evidencias_documentos``), para reportes vigentes que
    no quedan como snapshot permanente. Una sola fuente por relación: la
    identidad es sólo el tipo, así republicar no hace crecer el registro."""
    leido = _leer_reporte(Path(viajes_csv))
    if leido is None:
        raise ReporteIlegible(f"no se puede leer {viajes_csv}")
    sha, _tamano, extraidas = leido
    return incorporar_relaciones(
        raiz, extraidas, empresa_id=empresa_id, procedencia={"tipo": TIPO_PUBLICADO, "sha256": sha},
    )


def relaciones_de_reportes_publicados(
    raiz: str | Path, *, empresa_id: str = EMPRESA_LEGADA,
) -> list[dict[str, object]] | None:
    """Relaciones capturadas de reportes vigentes no conservados como
    snapshot: complementan al lector histórico mientras el registro no esté
    activado. ``None`` si el registro es ilegible o incompatible."""
    try:
        empresa = _leer_compartido(raiz)["empresas"].get(empresa_id)
    except RegistroRelacionesError:
        return None
    relaciones = empresa.get("relaciones", []) if isinstance(empresa, Mapping) else []
    return [
        dict(r["relacion"]) for r in relaciones
        if any(isinstance(f, Mapping) and f.get("tipo") == TIPO_PUBLICADO for f in r["fuentes"])
    ]


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


def _confirmar_avance(
    base: Path, empresa_id: str, items: list[tuple[str, str, int, list[dict[str, str]], int]], *,
    exigidas: list[str] | None, totales: dict[str, int], espera: float,
) -> str | None:
    """Una escritura atómica: relaciones + avance de ``items``
    (``relativa, sha, tamaño, relaciones, cantidad``). Con ``exigidas`` (lista
    de reportes sin ilegibles) marca ``completa`` si todos quedaron migrados."""
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
        for relativa, sha, tamano, extraidas, cantidad in items:
            agregadas, fuentes = _unir(
                empresa, extraidas, {"tipo": TIPO_MIGRADO, "ruta": relativa, "sha256": sha},
                ahora=ahora, indice=indice,
            )
            totales["relaciones_agregadas"] += agregadas
            totales["fuentes_agregadas"] += fuentes
            avance = {"sha256": sha, "tamano": tamano, "relaciones": cantidad}
            if reportes.get(relativa) != avance:
                reportes[relativa] = avance
                cambio = True
            cambio = cambio or bool(agregadas or fuentes)
        if exigidas is not None and migracion.get("estado") == ESTADO_EN_CURSO and all(
            r in reportes for r in exigidas
        ):
            migracion.update({"estado": ESTADO_COMPLETA, "completada_en": ahora})
            cambio = True
        return cambio, migracion.get("estado")

    return _modificar(base, operar, espera=espera)


def _aplicar(base: Path, empresa_id: str, lote: int, espera: float) -> dict[str, object]:
    rutas = _rutas_reportes(base)
    migrados_previos = dict(_migracion(_leer_compartido(base)["empresas"].get(empresa_id)).get("reportes", {}))
    ilegibles: list[str] = []
    extraidas_unicas: set[str] = set()
    totales = {"relaciones_agregadas": 0, "fuentes_agregadas": 0, "procesados": 0}
    omitidos = 0
    pendientes: list[tuple[str, str, int, list[dict[str, str]], int]] = []

    def confirmar(items, *, final: bool) -> str | None:
        exigidas = [_relativa(base, r) for r in rutas] if final and not ilegibles else None
        return _confirmar_avance(base, empresa_id, items, exigidas=exigidas, totales=totales, espera=espera)

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
        pendientes.append((relativa, sha, tamano, extraidas, len(extraidas)))
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


# --------------------------------------------------------------------------
# Migración en dos fases: lectura sin escritor, escritura breve con escritor
# --------------------------------------------------------------------------
# Leer ~1.600 reportes (5,6 GiB en Drive) lleva horas. Los reportes están
# fuera de la custodia y no cambian: leerlos no necesita el lease. Sólo la
# escritura del registro (``catalogos_privados``, custodiado) lo necesita, y
# es una única escritura atómica de segundos. Así PULL sigue operando durante
# la lectura y el lease se toma sólo para escribir.

def ruta_plan_migracion(raiz: str | Path, empresa_id: str = EMPRESA_LEGADA) -> Path:
    """Avance de la lectura, local y fuera de Drive (nunca se custodia)."""
    huella = hashlib.sha256(str(Path(raiz).resolve()).encode("utf-8")).hexdigest()[:16]
    return _directorio_local() / "registro_relaciones" / f"{huella}.{empresa_id}.plan_migracion.json"


def _guardar_plan(ruta: Path, plan: Mapping[str, object]) -> None:
    """Escritura atómica local (nunca bajo la raíz Atlas ni su custodia)."""
    ruta.parent.mkdir(parents=True, exist_ok=True)
    temporal = ruta.with_name(f"{ruta.name}.{os.getpid()}.tmp")
    temporal.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
    os.replace(temporal, ruta)


def _leer_plan(ruta: Path, empresa_id: str) -> dict[str, object]:
    vacio: dict[str, object] = {"version": 1, "empresa": empresa_id, "reportes": {}, "relaciones": []}
    try:
        plan = json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return vacio
    if (not isinstance(plan, dict) or plan.get("version") != 1 or plan.get("empresa") != empresa_id
            or not isinstance(plan.get("reportes"), dict) or not isinstance(plan.get("relaciones"), list)):
        return vacio
    return plan


def preparar_migracion(
    raiz: str | Path, *, empresa_id: str = EMPRESA_LEGADA, lote: int = LOTE_MIGRACION,
) -> dict[str, object]:
    """Fase 1, SIN escritor y sin escribir la raíz: lee los reportes aún no
    migrados y guarda el avance cada ``lote`` en un plan local (fuera de
    Drive). Un corte pierde a lo sumo el lote en curso; repetir reanuda.
    Cada relación queda con el primer reporte (en orden) que la trae: la
    misma fuente migrada que dejaría ``migrar_reportes_historicos``."""
    base = Path(raiz)
    _leer_compartido(base)  # registro ilegible/incompatible: se detiene antes de leer reportes
    ruta_plan = ruta_plan_migracion(base, empresa_id)
    with _cerrojo(ruta_cerrojo(base, "migracion"), 0):
        migrados = _migracion(_leer_compartido(base)["empresas"].get(empresa_id)).get("reportes", {})
        plan = _leer_plan(ruta_plan, empresa_id)
        conocidas = {_clave(e["relacion"]) for e in plan["relaciones"]}
        rutas = _rutas_reportes(base)
        ilegibles: list[str] = []
        leidos = omitidos = 0
        for ruta in rutas:
            relativa = _relativa(base, ruta)
            try:
                tamano_actual = ruta.stat().st_size
            except OSError:
                ilegibles.append(relativa)
                continue
            previo = migrados.get(relativa) or plan["reportes"].get(relativa)
            if isinstance(previo, dict) and previo.get("tamano") == tamano_actual:
                omitidos += 1
                continue
            leido = _leer_reporte(ruta)
            if leido is None:
                ilegibles.append(relativa)
                continue
            sha, tamano, extraidas = leido
            plan["reportes"][relativa] = {"sha256": sha, "tamano": tamano, "relaciones": len(extraidas)}
            for relacion in extraidas:
                clave = _clave(relacion)
                if clave not in conocidas:
                    conocidas.add(clave)
                    plan["relaciones"].append({"relacion": relacion, "ruta": relativa, "sha256": sha})
            leidos += 1
            if leidos % max(int(lote), 1) == 0:
                _guardar_plan(ruta_plan, plan)
        plan["rutas"] = [_relativa(base, r) for r in rutas]
        plan["ilegibles"] = ilegibles
        _guardar_plan(ruta_plan, plan)
    return {
        "modo": "preparar", "reportes": len(rutas) - len(ilegibles), "leidos": leidos,
        "omitidos_ya_migrados": omitidos, "pendientes_de_aplicar": len(plan["reportes"]),
        "relaciones_extraidas": len(plan["relaciones"]), "ilegibles": ilegibles, "plan": str(ruta_plan),
    }


def aplicar_migracion_preparada(
    raiz: str | Path, *, empresa_id: str = EMPRESA_LEGADA, espera: float = ESPERA_ESCRITURA_S,
) -> dict[str, object]:
    """Fase 2, CON escritor: una sola escritura atómica del registro base con
    lo leído en la fase 1. No abre reportes. Marca ``completa`` sólo si no
    hubo ilegibles y todos los reportes listados quedaron migrados. Después
    retira el plan local (repetir no agrega nada)."""
    base = Path(raiz)
    ruta_plan = ruta_plan_migracion(base, empresa_id)
    with _cerrojo(ruta_cerrojo(base, "migracion"), 0):
        plan = _leer_plan(ruta_plan, empresa_id)
        if "rutas" not in plan:
            raise MigracionNoPreparada(f"sin plan completo en {ruta_plan}: ejecutar la preparación")
        por_reporte: dict[str, list[dict[str, str]]] = {}
        for entrada in plan["relaciones"]:
            por_reporte.setdefault(entrada["ruta"], []).append(entrada["relacion"])
        items = [
            (relativa, avance["sha256"], avance["tamano"], por_reporte.get(relativa, []), avance["relaciones"])
            for relativa, avance in sorted(plan["reportes"].items())
        ]
        totales = {"relaciones_agregadas": 0, "fuentes_agregadas": 0}
        exigidas = None if plan.get("ilegibles") else list(plan["rutas"])
        estado = _confirmar_avance(base, empresa_id, items, exigidas=exigidas, totales=totales, espera=espera)
        ruta_plan.unlink(missing_ok=True)
    return {
        "modo": "aplicar", "reportes_aplicados": len(items), "ilegibles": plan.get("ilegibles", []),
        **totales, "relaciones_registradas": len(leer_relaciones(base, empresa_id=empresa_id)), "estado": estado,
    }


def leer_verificacion(
    raiz: str | Path, *, empresa_id: str = EMPRESA_LEGADA,
) -> tuple[dict[str, object], set[str]]:
    """Fase de lectura de la verificación, SIN escritor ni escritura: relee
    todos los reportes. Devuelve el resultado y las claves exigidas."""
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
    return resultado, extraidas_unicas


def marcar_verificada(
    raiz: str | Path, resultado: dict[str, object], exigidas: set[str], *,
    empresa_id: str = EMPRESA_LEGADA, espera: float = ESPERA_ESCRITURA_S,
) -> dict[str, object]:
    """Fase de escritura de la verificación (CON escritor; no abre reportes).
    Bajo cerrojo vuelve a exigir, sobre el registro vigente de ESTE momento
    (p. ej. tras la alineación de la custodia), estado ``completa`` y todas
    las claves leídas; si algo no calza, no escribe."""
    resultado = dict(resultado)
    if not (resultado["ok"] and resultado["estado_previo"] == ESTADO_COMPLETA):
        resultado["estado"] = resultado["estado_previo"]
        return resultado
    base = Path(raiz)

    def operar(registro: dict[str, object]) -> tuple[bool, str]:
        actual = _migracion(registro["empresas"].get(empresa_id))
        if actual.get("estado") != ESTADO_COMPLETA:
            return False, str(actual.get("estado"))
        claves = set(_Indice(_leer_fresco(base)["empresas"].get(empresa_id) or {}).por_clave)
        faltan = exigidas - claves
        if faltan:
            resultado.update({"ok": False, "relaciones_ausentes": len(faltan), "ejemplos_ausentes": sorted(faltan)[:10]})
            return False, ESTADO_COMPLETA
        actual.update({"estado": ESTADO_VERIFICADA, "verificada_en": _ahora(), "verificacion": {
            "reportes": resultado["reportes_leidos"], "relaciones_extraidas": len(exigidas),
            "relaciones_registradas": len(claves),
        }})
        return True, ESTADO_VERIFICADA

    resultado["estado"] = _modificar(base, operar, espera=espera)
    return resultado


def verificar_migracion(
    raiz: str | Path, *, empresa_id: str = EMPRESA_LEGADA, espera: float = ESPERA_ESCRITURA_S,
) -> dict[str, object]:
    """Relee TODOS los reportes actuales (sólo lectura) y exige que cada
    relación esté en el registro. Si la migración está completa y todo
    calza, la marca ``verificada``; si no, no escribe nada."""
    resultado, exigidas = leer_verificacion(raiz, empresa_id=empresa_id)
    return marcar_verificada(raiz, resultado, exigidas, empresa_id=empresa_id, espera=espera)


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


def consolidar_diario(
    raiz: str | Path, *, hasta: str | None = None, espera: float = ESPERA_ESCRITURA_S,
) -> dict[str, object]:
    """Consolidación controlada: incorpora al registro base los segmentos de
    días anteriores a ``hasta`` (AAAAMMDD; por defecto hoy UTC, así el
    segmento en uso no se toca) más cualquier copia con nombre no diario, y
    recién después los borra. Un corte entre la escritura del base y el
    borrado sólo deja segmentos ya incorporados, cuya reproducción no cambia
    nada. Con un segmento ilegible se detiene sin escribir ni borrar."""
    limite = hasta or _dia(_ahora())
    with _cerrojo(ruta_cerrojo(raiz, "migracion"), 0), _cerrojo(ruta_cerrojo(raiz, "escritura"), espera):
        vigente = _leer_fresco(raiz)
        elegidos = [
            p for p in _segmentos(raiz)
            if (coincide := _NOMBRE_SEGMENTO.match(p.name)) is None or coincide.group(1) < limite
        ]
        if not elegidos:
            return {"consolidados": [], "relaciones": _contar(vigente), "base_reescrito": False}
        huellas = {p: _huella_archivo(p) for p in elegidos}
        base = _leer_base(raiz)
        _reproducir(base, [_leer_segmento(p) for p in elegidos])
        escribir_json_atomico(ruta_registro(raiz), base)
        _MEMORIA.pop(str(ruta_registro(raiz)), None)
        borrados, conservados = [], []
        for ruta in elegidos:
            # Nunca borra un segmento que cambió después de leerlo.
            if _huella_archivo(ruta) == huellas[ruta]:
                ruta.unlink(missing_ok=True)
                borrados.append(ruta.name)
            else:
                conservados.append(ruta.name)
        return {
            "consolidados": borrados, "conservados": conservados, "relaciones": _contar(base), "base_reescrito": True,
        }


def _contar(registro: Mapping[str, object]) -> dict[str, int]:
    return {e: len(v.get("relaciones", [])) for e, v in registro["empresas"].items()}


def _estado_diario(raiz: str | Path) -> dict[str, object]:
    segmentos = _segmentos(raiz)
    tamanos = [h[1] for h in (_huella_archivo(p) for p in segmentos) if h is not None]
    return {"segmentos": len(segmentos), "bytes": sum(tamanos), "nombres": [p.name for p in segmentos]}


def estado_registro(raiz: str | Path, *, empresa_id: str = EMPRESA_LEGADA) -> dict[str, object]:
    try:
        empresa = _leer_compartido(raiz)["empresas"].get(empresa_id)
        diario = _estado_diario(raiz)
    except RegistroRelacionesError as error:
        return {"legible": False, "codigo": error.codigo, "detalle": str(error), "activo": False}
    migracion = _migracion(empresa)
    return {
        "legible": True, "empresa": empresa_id, "relaciones": len(_relaciones_de(empresa)),
        "estado_migracion": migracion.get("estado"), "activo": _activa(empresa),
        "reportes_migrados": len(migracion.get("reportes", {})), "diario": diario,
        **{k: migracion[k] for k in ("iniciada_en", "completada_en", "verificada_en", "verificacion") if k in migracion},
    }
