"""Aislamiento de datos por empresa: una raíz por empresa, un solo Motor.

Atlas ya pasa ``raiz`` a todo su almacenamiento, de modo que la frontera de
aislamiento es la raíz operacional: guías, viajes, clientes, choferes,
vehículos, documentos y reportes viven bajo ella y una empresa nunca abre la
raíz de otra.

* **MBT** conserva exactamente su raíz, sus rutas locales y sus datos. No se le
  escribe marca ni se le crea nada.
* **Otra empresa** vive en ``<carpeta de Atlas>/../Atlas_empresas/<id>``:
  carpeta hermana, fuera de la raíz de MBT y por tanto fuera de su custodia
  Cloud y de ``rastreable``. Se identifica con una marca custodiada
  (``catalogos_privados/empresa_identidad.json``), que viaja con la
  recuperación desde Cloud y no contiene rutas absolutas.

Las violaciones lanzan ``ErrorAislamiento`` (``RuntimeError``, no ``OSError``):
varios lectores del Motor convierten ``OSError`` en "sin datos" y un cruce de
empresas no debe pasar en silencio.

``entrar_proceso`` corre al importar ``atlas_core``: ninguna CLI puede saltarse
la frontera. Mientras no exista ``Atlas_empresas`` y no se pida otra empresa,
MBT sigue exactamente igual: sin guarda y con las mismas rutas locales.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import threading
from dataclasses import dataclass
from functools import lru_cache, wraps
from pathlib import Path

from atlas_core import almacenamiento_portable as ap

EMPRESA_MBT = "mbt"
# Identificadores históricos de MBT: se conservan tal cual, sólo se nombran.
CLOUD_MBT = "empresa-prueba-javier"
REGISTRO_MBT = "oficina"

CARPETA_EMPRESAS = "Atlas_empresas"
RUTA_MARCA = "catalogos_privados/empresa_identidad.json"
VERSION_MARCA = 1
VARIABLE_EMPRESA = "ATLAS_EMPRESA_ID"
VARIABLE_RAIZ_MBT = "ATLAS_RAIZ_MBT"
VARIABLE_TOKEN = "ATLAS_CLOUD_MOTOR_TOKEN"

_PATRON_ID = re.compile(r"^[a-z][a-z0-9-]{1,38}[a-z0-9]$")
_RESERVADOS = frozenset({
    EMPRESA_MBT, REGISTRO_MBT, CLOUD_MBT, "atlas", "empresas", "con", "prn", "aux", "nul",
    *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10)),
})
_EVENTOS_UNA_RUTA = frozenset({
    "open", "os.listdir", "os.scandir", "os.mkdir", "os.rmdir", "os.remove", "os.truncate", "os.chmod", "os.utime",
})
_EVENTOS_DOS_RUTAS = frozenset({"os.rename", "os.link", "os.symlink"})
# Consultas de metadatos: no emiten evento de auditoría y delatarían existencia,
# tamaño o fechas de archivos ajenos; se interceptan directamente.
_SONDAS_OS = ("stat", "lstat", "access", "readlink")
_SONDAS_PATH = ("exists", "lexists", "isfile", "isdir", "islink", "ismount", "isjunction", "getsize", "getmtime",
                "getatime", "getctime")


class ErrorAislamiento(RuntimeError):
    def __init__(self, codigo: str, detalle: str = "") -> None:
        super().__init__(f"{codigo}: {detalle}" if detalle else codigo)
        self.codigo = codigo


def validar_empresa_id(empresa_id: str) -> str:
    """Identificador estable e inmutable: minúsculas, válido como carpeta y clave."""
    if not isinstance(empresa_id, str) or not _PATRON_ID.fullmatch(empresa_id):
        raise ErrorAislamiento("EMPRESA_ID_INVALIDO", repr(empresa_id))
    if empresa_id in _RESERVADOS or empresa_id.split(".")[0] in _RESERVADOS:
        raise ErrorAislamiento("EMPRESA_ID_RESERVADO", empresa_id)
    return empresa_id


def empresa_proceso() -> str:
    return os.environ.get(VARIABLE_EMPRESA, "").strip() or EMPRESA_MBT


def base_local(empresa_id: str | None = None) -> Path:
    """Equivalente por empresa de ``%LOCALAPPDATA%/Atlas``: MBT, la misma de siempre."""
    empresa = empresa_id or empresa_proceso()
    base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".local") / "Atlas"
    return base if empresa == EMPRESA_MBT else base / "empresas" / validar_empresa_id(empresa)


def empresa_de_raiz(raiz: str | os.PathLike) -> str:
    """Empresa dueña de una raíz, por su posición; no hace E/S."""
    ruta = Path(raiz)
    return ruta.name if ruta.parent.name.lower() == CARPETA_EMPRESAS.lower() else EMPRESA_MBT


def registro_id_de_raiz(raiz: str | os.PathLike) -> str:
    """Clave del registro de relaciones: ``oficina`` es exclusiva de MBT."""
    empresa = empresa_de_raiz(raiz)
    return REGISTRO_MBT if empresa == EMPRESA_MBT else empresa


def por_empresa_de_raiz(funcion):
    """Completa ``empresa_id=None`` con la empresa dueña de la raíz (primer argumento)."""
    from inspect import signature
    parametros = list(signature(funcion).parameters)
    posicion = parametros.index("empresa_id")
    @wraps(funcion)
    def envoltura(raiz, *args, **kwargs):
        if len(args) >= posicion:  # pasado por posición
            if args[posicion - 1] is None:
                args = (*args[:posicion - 1], registro_id_de_raiz(raiz), *args[posicion:])
        elif kwargs.get("empresa_id") is None:
            kwargs["empresa_id"] = registro_id_de_raiz(raiz)
        return funcion(raiz, *args, **kwargs)
    return envoltura


def _norm_real(texto: str) -> str:
    try:
        return os.path.normcase(os.path.realpath(texto))
    except (OSError, ValueError):
        return os.path.normcase(os.path.abspath(texto))


_norm_cache = lru_cache(maxsize=8192)(_norm_real)


def _norm(ruta: str | os.PathLike) -> str:
    return _norm_cache(os.fspath(ruta))


def _dentro(ruta_norm: str, raiz_norm: str) -> bool:
    return ruta_norm == raiz_norm or ruta_norm.startswith(raiz_norm.rstrip(os.sep) + os.sep)


def _base_empresas(raiz_mbt: Path) -> Path:
    return Path(raiz_mbt).parent / CARPETA_EMPRESAS


def _leer_marca(raiz: Path) -> dict | None:
    """``None`` si no hay marca; una marca ilegible nunca equivale a ausente."""
    ruta = raiz.joinpath(*RUTA_MARCA.split("/"))
    try:
        contenido = ruta.read_bytes()
    except FileNotFoundError:
        return None
    return _interpretar_marca(contenido)


def _interpretar_marca(contenido: bytes) -> dict:
    try:
        marca = json.loads(contenido.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ErrorAislamiento("MARCA_ILEGIBLE", str(error)) from error
    if not isinstance(marca, dict) or marca.get("version") != VERSION_MARCA or not isinstance(marca.get("empresa_id"), str):
        raise ErrorAislamiento("MARCA_ILEGIBLE", "estructura desconocida")
    return marca


@dataclass(frozen=True)
class ContextoEmpresa:
    """Identidad y rutas de UNA empresa. No hay API para llegar a otra."""

    empresa_id: str
    raiz: Path
    raiz_mbt: Path
    cloud_id: str | None
    registro_id: str

    @property
    def es_mbt(self) -> bool:
        return self.empresa_id == EMPRESA_MBT

    # Mismas funciones que usa el Motor: un solo esquema de carpetas.
    def operacion(self, subcarpeta: str = "") -> Path:
        return ap.ruta_operacion(subcarpeta, raiz=self.raiz)

    def catalogos(self) -> Path:
        return ap.ruta_catalogos_privados(raiz=self.raiz)

    def reportes(self, subcarpeta: str = "actual") -> Path:
        return ap.ruta_reportes(subcarpeta, raiz=self.raiz)

    def respaldos(self) -> Path:
        return ap.ruta_respaldos(raiz=self.raiz)

    def datos_privados(self, subcarpeta: str = "") -> Path:
        return ap.ruta_datos_privados(subcarpeta, raiz=self.raiz)

    def ruta(self, relativa: str) -> Path:
        """Ruta bajo la raíz propia; rechaza cualquier salida de ella."""
        if os.path.isabs(relativa) or Path(relativa).drive:
            raise ErrorAislamiento("RUTA_FUERA_DE_EMPRESA", relativa)
        return self.exigir_propia(self.raiz.joinpath(*Path(relativa).parts))

    def exigir_propia(self, ruta: str | os.PathLike) -> Path:
        if not _dentro(_norm(ruta), _norm(self.raiz)):
            raise ErrorAislamiento("RUTA_FUERA_DE_EMPRESA", os.fspath(ruta))
        return Path(ruta)

    # Estado local de máquina, fuera de la raíz sincronizada.
    def _local(self) -> Path:
        return base_local(self.empresa_id)

    def carpeta_custodia(self) -> Path:
        """Para ``CustodiaEstado(carpeta_local=...)``."""
        if self.es_mbt:
            from atlas_core.estado_confirmado import ruta_local
            return ruta_local()
        return self._local() / "cache" / "estado_confirmado"

    def entorno(self) -> dict[str, str]:
        """Variables para lanzar un proceso del Motor de esta empresa."""
        entorno = {ap.VARIABLE_ENTORNO: str(self.raiz), VARIABLE_EMPRESA: self.empresa_id,
                   VARIABLE_RAIZ_MBT: str(self.raiz_mbt)}
        if not self.es_mbt:
            local = self._local()
            entorno.update({
                "ATLAS_CATALOGOS_DIR": str(self.catalogos()),
                "ATLAS_CACHE_DIR": str(local / "cache"),
                "ATLAS_DIAGNOSTICO_DIR": str(local / "diagnostico"),
                "ATLAS_PULL_LOG_DIR": str(local / "logs" / "pull_ciclos"),
                "ATLAS_OPERACION_CONFIG": str(local / "desktop_operacion.json"),
                "ATLAS_PULL_AUTORIZACION": str(local / "pull_autorizacion.json"),
            })
        return entorno


def _contexto_mbt(raiz_mbt: Path) -> ContextoEmpresa:
    marca = _leer_marca(raiz_mbt)
    if marca is not None:
        raise ErrorAislamiento("RAIZ_DE_OTRA_EMPRESA", str(marca.get("empresa_id")))
    return ContextoEmpresa(EMPRESA_MBT, raiz_mbt, raiz_mbt, CLOUD_MBT, REGISTRO_MBT)


def _validar_raiz_mbt(raiz_mbt: str | os.PathLike) -> Path:
    raiz = Path(raiz_mbt)
    if CARPETA_EMPRESAS.lower() in (p.lower() for p in Path(os.path.realpath(raiz)).parts):
        raise ErrorAislamiento("RAIZ_MBT_INVALIDA", str(raiz))
    return raiz


def _raiz_otra_empresa(raiz_mbt: Path, empresa_id: str) -> Path:
    """Exige que la carpeta sea realmente la de esa empresa (sin enlace a otra)."""
    base = _base_empresas(raiz_mbt)
    raiz = base / empresa_id
    if os.path.lexists(raiz) and _norm(raiz) != os.path.normcase(os.path.join(os.path.realpath(base), empresa_id)):
        raise ErrorAislamiento("RAIZ_ENLAZADA", str(raiz))
    return raiz


def abrir_empresa(raiz_mbt: str | os.PathLike, empresa_id: str, *, restauracion: bool = False) -> ContextoEmpresa:
    """Contexto verificado. Nunca escribe, salvo crear la raíz vacía en restauración.

    ``restauracion=True`` admite una raíz sin marca sólo para recuperar desde
    Cloud: exige luego ``verificar_custodia_cloud`` y ``confirmar_restauracion``.
    """
    raiz_mbt = _validar_raiz_mbt(raiz_mbt)
    if empresa_id == EMPRESA_MBT:
        return _contexto_mbt(raiz_mbt)
    validar_empresa_id(empresa_id)
    raiz = _raiz_otra_empresa(raiz_mbt, empresa_id)
    if restauracion:
        raiz.mkdir(parents=True, exist_ok=True)
    elif not raiz.is_dir():
        raise ErrorAislamiento("EMPRESA_INEXISTENTE", empresa_id)
    marca = _leer_marca(raiz)
    if marca is None and not restauracion:
        raise ErrorAislamiento("EMPRESA_SIN_MARCA", empresa_id)
    if marca is not None and marca["empresa_id"] != empresa_id:
        raise ErrorAislamiento("RAIZ_DE_OTRA_EMPRESA", f"{empresa_id} != {marca['empresa_id']}")
    return ContextoEmpresa(empresa_id, raiz, raiz_mbt, (marca or {}).get("cloud_id"), empresa_id)


def confirmar_restauracion(contexto: ContextoEmpresa) -> ContextoEmpresa:
    """Tras alinear con Cloud: la marca debe haber llegado y ser la esperada."""
    return abrir_empresa(contexto.raiz_mbt, contexto.empresa_id)


def listar_empresas(raiz_mbt: str | os.PathLike) -> list[str]:
    raiz_mbt = _validar_raiz_mbt(raiz_mbt)
    base, empresas = _base_empresas(raiz_mbt), [EMPRESA_MBT]
    if base.is_dir():
        for entrada in sorted(base.iterdir()):
            if entrada.is_dir() and _leer_marca(entrada) is not None:
                empresas.append(entrada.name)
    return empresas


def inicializar_empresa(raiz_mbt: str | os.PathLike, empresa_id: str, *, nombre: str, cloud_id: str) -> ContextoEmpresa:
    """Alta explícita. Idempotente con los mismos datos; jamás toca a MBT."""
    raiz_mbt = _validar_raiz_mbt(raiz_mbt)
    validar_empresa_id(empresa_id)
    if not isinstance(cloud_id, str) or not cloud_id.strip():
        raise ErrorAislamiento("CLOUD_ID_INVALIDO", repr(cloud_id))
    if cloud_id == CLOUD_MBT:
        raise ErrorAislamiento("CLOUD_ID_EN_USO", cloud_id)
    raiz = _raiz_otra_empresa(raiz_mbt, empresa_id)
    for otra in listar_empresas(raiz_mbt)[1:]:
        if otra != empresa_id and abrir_empresa(raiz_mbt, otra).cloud_id == cloud_id:
            raise ErrorAislamiento("CLOUD_ID_EN_USO", cloud_id)
    marca = _leer_marca(raiz) if raiz.is_dir() else None
    if marca is not None:
        if marca["empresa_id"] != empresa_id or marca.get("cloud_id") != cloud_id:
            raise ErrorAislamiento("EMPRESA_YA_DEFINIDA", empresa_id)
        return abrir_empresa(raiz_mbt, empresa_id)
    if raiz.is_dir() and any(raiz.iterdir()):
        raise ErrorAislamiento("RAIZ_CON_DATOS_SIN_MARCA", empresa_id)
    ap.escribir_json_atomico(raiz.joinpath(*RUTA_MARCA.split("/")), {
        "version": VERSION_MARCA, "empresa_id": empresa_id, "nombre": nombre, "cloud_id": cloud_id,
    })
    return abrir_empresa(raiz_mbt, empresa_id)


def contexto_desde_entorno() -> ContextoEmpresa:
    """Sin ``ATLAS_EMPRESA_ID`` es MBT, igual que hoy (y rechaza una raíz ajena)."""
    empresa_id = os.environ.get(VARIABLE_EMPRESA, "").strip() or EMPRESA_MBT
    if empresa_id == EMPRESA_MBT:
        return abrir_empresa(ap.resolver_raiz_atlas(), EMPRESA_MBT)
    raiz_mbt = os.environ.get(VARIABLE_RAIZ_MBT, "").strip()
    if not raiz_mbt:
        raise ErrorAislamiento("ENTORNO_INCOMPLETO", VARIABLE_RAIZ_MBT)
    contexto = abrir_empresa(raiz_mbt, empresa_id)
    if _norm(ap.resolver_raiz_atlas()) != _norm(contexto.raiz):
        raise ErrorAislamiento("RAIZ_DE_OTRA_EMPRESA", str(ap.resolver_raiz_atlas()))
    return contexto


def verificar_custodia_cloud(contexto: ContextoEmpresa, cliente) -> dict[str, object]:
    """Antes de alinear o restaurar. Cloud deduce la empresa del token y su
    manifiesto no la declara: un token equivocado volcaría datos ajenos."""
    datos = cliente.manifiesto()
    archivos = {fila[0]: fila[1] for fila in datos.get("archivos", [])}
    return verificar_manifiesto_empresa(contexto.raiz, archivos, cliente.descargar)


def verificar_manifiesto_empresa(raiz: str | os.PathLike, manifiesto: dict, descargar) -> dict[str, object]:
    """El manifiesto debe pertenecer a la empresa dueña de ``raiz``."""
    empresa_id = empresa_de_raiz(raiz)
    archivos = {ruta: huella for ruta, huella in manifiesto.items() if huella}
    huella = archivos.get(RUTA_MARCA)
    if empresa_id == EMPRESA_MBT:
        if huella:
            raise ErrorAislamiento("CUSTODIA_AJENA", "la custodia pertenece a otra empresa")
        return {"estado": "COINCIDE", "archivos": len(archivos)}
    if not huella:
        if archivos:
            raise ErrorAislamiento("CUSTODIA_AJENA", "custodia con datos y sin marca de empresa")
        return {"estado": "VACIA", "archivos": 0}
    local = Path(raiz).joinpath(*RUTA_MARCA.split("/"))
    try:
        contenido = local.read_bytes()
    except FileNotFoundError:
        contenido = b""
    if hashlib.sha256(contenido).hexdigest() != huella:
        contenido = descargar(huella)
    if hashlib.sha256(contenido).hexdigest() != huella:
        raise ErrorAislamiento("CUSTODIA_NO_VERIFICABLE", "la marca no coincide con su huella")
    marca = _interpretar_marca(contenido)
    if marca["empresa_id"] != empresa_id:
        raise ErrorAislamiento("CUSTODIA_AJENA", str(marca["empresa_id"]))
    return {"estado": "COINCIDE", "archivos": len(archivos)}


# ----------------------------------------------------- guarda del proceso
_guarda: dict | None = None
_hilo = threading.local()


def _vetada(ruta: object, *, sonda: bool = False) -> bool:
    if isinstance(ruta, bytes):
        ruta = os.fsdecode(ruta)
    if not isinstance(ruta, (str, os.PathLike)) or getattr(_hilo, "dentro", False):
        return False
    guarda = _guarda
    _hilo.dentro = True  # realpath usa lstat: sin reentrada
    try:
        normal = _norm(ruta)
    finally:
        _hilo.dentro = False
    if any(_dentro(normal, propia) for propia in guarda["propias"]):
        return False
    # Los ancestros de lo propio no revelan nada de otra empresa.
    if sonda and any(_dentro(propia, normal) for propia in guarda["propias"]):
        return False
    return any(_dentro(normal, vetada) for vetada in guarda["vetadas"])


def _gancho(evento: str, argumentos: tuple) -> None:
    if _guarda is None:
        return
    if evento == "os.mkdir":  # crear lo propio crea sus ancestros si faltan
        if _vetada(argumentos[0], sonda=True):
            raise ErrorAislamiento("ACCESO_ENTRE_EMPRESAS", f"{_guarda['empresa_id']}: {argumentos[0]!r}")
        return
    if evento in _EVENTOS_UNA_RUTA:
        rutas = argumentos[:1]
    elif evento in _EVENTOS_DOS_RUTAS:
        rutas = argumentos[:2]
    else:
        return
    for ruta in rutas:
        if _vetada(ruta):
            raise ErrorAislamiento("ACCESO_ENTRE_EMPRESAS", f"{_guarda['empresa_id']}: {ruta!r}")


def activar_guarda(contexto: ContextoEmpresa) -> None:
    """Un proceso, una empresa. Irreversible (los audit hooks no se retiran)."""
    global _guarda
    if _guarda is not None:
        if _guarda["empresa_id"] != contexto.empresa_id:
            raise ErrorAislamiento("PROCESO_DE_OTRA_EMPRESA", _guarda["empresa_id"])
        return
    local = base_local(EMPRESA_MBT)
    if contexto.es_mbt:
        propias = [_norm(contexto.raiz)]
        vetadas = [_norm(_base_empresas(contexto.raiz_mbt)), _norm(local / "empresas")]
    else:
        # En la carpeta local de MBT sólo se comparten los runtimes de OCR.
        propias = [_norm(contexto.raiz), _norm(base_local(contexto.empresa_id)), _norm(local / "runtime")]
        vetadas = [_norm(_base_empresas(contexto.raiz_mbt)), _norm(contexto.raiz_mbt), _norm(local)]
    _guarda = {"empresa_id": contexto.empresa_id, "cloud_id": contexto.cloud_id, "propias": propias, "vetadas": vetadas}
    sys.addaudithook(_gancho)
    _instalar_sondas()


def _envolver_sonda(original, nombre: str):
    @wraps(original)
    def sonda(ruta, *args, **kwargs):
        if _vetada(ruta, sonda=True):
            raise ErrorAislamiento("ACCESO_ENTRE_EMPRESAS", f"{_guarda['empresa_id']}: {nombre} {ruta!r}")
        return original(ruta, *args, **kwargs)
    return sonda


def _instalar_sondas() -> None:
    for modulo, nombres in ((os, _SONDAS_OS), (os.path, _SONDAS_PATH)):
        for nombre in nombres:
            original = getattr(modulo, nombre, None)
            if original is not None:
                setattr(modulo, nombre, _envolver_sonda(original, nombre))


def multiempresa_activa(raiz: str | os.PathLike) -> bool:
    """Hay más de una empresa que separar (con MBT sola no se hace nada extra)."""
    return _guarda is not None or empresa_de_raiz(raiz) != EMPRESA_MBT or _base_empresas(Path(raiz)).is_dir()


def exigir_raiz_de_proceso(raiz: str | os.PathLike) -> None:
    """Con guarda activa, ``raiz`` debe ser exactamente la de la empresa del proceso."""
    if _guarda is not None and _norm(raiz) != _guarda["propias"][0]:
        raise ErrorAislamiento("RAIZ_DE_OTRA_EMPRESA", f"{_guarda['empresa_id']}: {os.fspath(raiz)}")


def exigir_lease_empresa(empresa_cloud: object) -> None:
    """Un documento de Cloud sólo entra a la raíz de su empresa. Sin guarda
    (MBT sin otras empresas) no hay nada que separar y no cambia nada."""
    if _guarda is not None and empresa_cloud != _guarda["cloud_id"]:
        raise ErrorAislamiento("LEASE_DE_OTRA_EMPRESA", f"{_guarda['empresa_id']}: {empresa_cloud!r}")


def entrar_proceso() -> ContextoEmpresa | None:
    """Se ejecuta al importar ``atlas_core``. Falla cerrado ante un entorno ambiguo."""
    if empresa_proceso() != EMPRESA_MBT:
        contexto = contexto_desde_entorno()
        # La credencial general es la de MBT: sin la propia, sin token.
        token = os.environ.get(f"{VARIABLE_TOKEN}__{contexto.empresa_id.upper().replace('-', '_')}", "").strip()
        # Sólo lo que difiere: Desktop lanza consultas con os.putenv prohibido y
        # ya entrega el entorno completo.
        for clave, valor in contexto.entorno().items():
            if os.environ.get(clave) != valor:
                os.environ[clave] = valor
        if os.environ.get(VARIABLE_TOKEN, "") != token:
            if token:
                os.environ[VARIABLE_TOKEN] = token
            else:
                os.environ.pop(VARIABLE_TOKEN, None)
        activar_guarda(contexto)
        return contexto
    raiz = ap.resolver_raiz_atlas()
    _validar_raiz_mbt(raiz)
    if not _base_empresas(raiz).is_dir():
        if _leer_marca(raiz) is not None:
            raise ErrorAislamiento("RAIZ_DE_OTRA_EMPRESA", str(raiz))
        return None
    contexto = abrir_empresa(raiz, EMPRESA_MBT)
    activar_guarda(contexto)
    return contexto
