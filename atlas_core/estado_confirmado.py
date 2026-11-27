"""Custodia del estado operacional confirmado en Cloud (protocolo 2 del lease).

Drive replica archivo por archivo y sin garantía de orden ni de plazo: tras un
relevo de escritor, la copia local puede estar atrasada, a medias, o recibir
más tarde archivos viejos que otro equipo no alcanzó a subir antes de
apagarse. El lease Cloud ya impide escritores simultáneos; esta custodia le
agrega la marca del último estado confirmado:

- Al cerrar su turno, el titular publica en Cloud la huella SHA-256 de cada
  archivo operacional que modificó y sube su contenido (R2, direccionado por
  huella). La confirmación es atómica y exige lease vigente y versión base.
- Al adquirir, y antes de cualquier escritura, el titular alinea su copia
  local con la marca: lo que difiere se restaura desde Cloud. Un contenido
  local nunca confirmado se copia antes a cuarentena local (no se pierde).
  Si no se logra la coincidencia exacta, el lease se libera sin escribir.
- Las escrituras se registran con un audit hook de Python (todas las
  escrituras del Motor ocurren en proceso) y en un diario local, para que un
  apagado inesperado se confirme al volver si nadie confirmó entre medio.
- Diario de recuperación remoto (P0.1): antes de la primera escritura de cada
  ruta, el diario del turno se sube a Cloud (objeto direccionado por huella) y
  su puntero se confirma en la misma marca, bajo la ruta reservada
  ``.atlas_custodia/diarios/<escritor_id>/<epoca>.json``. Queda ligado a la
  empresa (token Cloud y campo empresa_id), a la versión base y al turno
  (época del lease). Si no se logra persistir, la escritura se aborta. Al
  confirmar el turno, el puntero se anula en el mismo lote final; si el equipo
  desaparece, el diario sigue íntegro en Cloud y cualquier otro equipo de la
  empresa lo lee (``--diarios``). Ningún turno anula el diario de otro turno.
- Contenido recuperable (P0.2, diario formato 2): en el patrón temporal +
  os.replace el audit hook lee el temporal ya completo, lo sube a Cloud y lo
  anota en el diario ANTES del reemplazo; los borrados también. Una escritura
  directa (``open("a")``) queda pendiente hasta ``punto_de_control`` tras
  cerrar el archivo. ``--recuperar-turno`` aplica, desde otro escritor y bajo
  lease, el turno caído sólo con lo que hay en Cloud: todo o nada, sin pisar
  versiones posteriores ni perder o duplicar documentos del dataset, y cierra
  ese diario en el mismo lote que confirma los datos.
- Escritor sustituido (P0.3): el estado local del lease no autoriza nada.
  Cada escritura se valida en Cloud (publicación del diario, o renovación
  del lease si no hay nada nuevo que publicar) y exige que el destino tenga
  lo que el turno espera (lo último que escribió o la marca alineada): un
  contenido ajeno traído por Drive no se pisa ni se adopta. Al confirmar se
  publica la huella custodiada al escribir, no la que haya en la raíz.
- Raíz de trabajo aislada (P0.3.1, opt-in con ``raiz_publicada.json`` en la
  carpeta local de la empresa): el Motor escribe en una raíz local fuera de
  Drive; la raíz publicada (Drive) recibe sólo lo que Cloud confirmó (tras
  cada lote) y los reportes/respaldos de turnos confirmados. Ningún dato de
  un turno sin confirmar llega a Drive ni a otro escritor. La raíz publicada
  no se usa para escribir.

`reportes/`, `respaldos/` y `backups/` quedan fuera: cada escritura crea una
carpeta con marca de tiempo única, nunca reemplaza contenido previo.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
import os
import shutil
import sys
import threading
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

PROTOCOLO = 2
EXCLUIDOS_PRIMER_NIVEL = frozenset({
    "reportes", "respaldos", "backups", "_respaldos_desarrollo", "historico_pre_infra_s2", "investigacion",
    ".atlas_custodia",
})
# Rutas de la marca que no son archivos operacionales: nunca se restauran a la
# raíz ni se comparan con ella (diarios de recuperación de los turnos).
PREFIJO_CUSTODIA = ".atlas_custodia/"
CARPETA_DIARIOS = ".atlas_custodia/diarios"
TIPO_DIARIO = "ATLAS_DIARIO_RECUPERACION"
# Formato 2 (P0.2): además de las rutas, la huella del contenido escrito, ya
# subido a Cloud antes de hacerse visible en la raíz. El 1 (acbe227) sólo se lee.
FORMATO_DIARIO = 2
FORMATOS_LEGIBLES = (1, 2)
RUTA_DATASET = "operacion/actual/analisis_completo_guias.csv"
CARPETA_RECUPERACIONES = "operacion/actual/recuperaciones_turno"
# Línea base de la activación: archivos mutables que la operación reescribe.
SEMILLA_CARPETAS = ("operacion/actual", "operacion/procesamiento", "catalogos_privados", "fichas_digitales")
SEMILLA_ENVIOS = "operacion/mobile/envios"
# Lotes chicos: el Worker consulta R2/D1 por elemento y cada solicitud debe
# terminar dentro del timeout del cliente y de los límites por solicitud.
LOTE_CONFIRMACION = 50
LOTE_CONSULTA = 50

log = logging.getLogger(__name__)


class EstadoNoVerificado(RuntimeError):
    """La copia local no coincide con la marca de Cloud: no se escribe."""


class DiarioNoPersistido(EstadoNoVerificado):
    """El diario del turno no quedó en Cloud: la escritura no debe ocurrir."""


class EscritorSustituido(DiarioNoPersistido):
    """El lease de este turno venció o lo tomó otro escritor (P0.3)."""


class ContenidoAjeno(EstadoNoVerificado):
    """El destino ya no contiene lo que este turno escribió o alineó: otro
    escritor (típicamente el anterior, replicado por Drive) lo cambió."""


def es_ruta_custodia(rel: str) -> bool:
    return rel.startswith(PREFIJO_CUSTODIA)


def operacionales(manifiesto: dict) -> dict:
    return {rel: sha for rel, sha in manifiesto.items() if not es_ruta_custodia(rel)}


def ruta_diario(escritor_id: str, epoca: int) -> str:
    return f"{CARPETA_DIARIOS}/{escritor_id}/{int(epoca)}.json"


def serializar_diario(diario: dict) -> bytes:
    return json.dumps(diario, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("ascii")


def interpretar_diario(rel: str, datos: bytes, sha: str) -> dict:
    """Diario remoto íntegro y coherente con su ruta, o EstadoNoVerificado."""
    if hashlib.sha256(datos).hexdigest() != sha:
        raise EstadoNoVerificado(f"diario {rel}: contenido no coincide con su huella")
    try:
        diario = json.loads(datos.decode("ascii"))
    except (UnicodeError, ValueError) as error:
        raise EstadoNoVerificado(f"diario {rel} ilegible: {error}") from error
    campos = {"tipo": str, "formato": int, "empresa_id": str, "escritor_id": str, "epoca": int,
              "lease_sha256": str, "version_base": int, "raiz": str, "abierto_en": str,
              "actualizado_en": str, "rutas": list, "huellas_base": dict}
    if isinstance(diario, dict) and diario.get("formato") == FORMATO_DIARIO:
        campos.update(contenido=dict, pendientes=list, cierra=list, recuperacion=dict)
    if not isinstance(diario, dict) or any(not isinstance(diario.get(c), t) for c, t in campos.items()):
        raise EstadoNoVerificado(f"diario {rel}: estructura inválida")
    if diario["tipo"] != TIPO_DIARIO or diario["formato"] not in FORMATOS_LEGIBLES:
        raise EstadoNoVerificado(f"diario {rel}: tipo o formato desconocido")
    if ruta_diario(diario["escritor_id"], diario["epoca"]) != rel:
        raise EstadoNoVerificado(f"diario {rel}: no corresponde a su turno")
    rutas = diario["rutas"]
    if (not all(isinstance(r, str) and rastreable(r) for r in rutas)
            or sorted(set(rutas)) != rutas or set(diario["huellas_base"]) != set(rutas)):
        raise EstadoNoVerificado(f"diario {rel}: rutas inválidas")
    if diario["formato"] == FORMATO_DIARIO:
        contenido, pendientes = diario["contenido"], diario["pendientes"]
        if (set(contenido) | set(pendientes) != set(rutas) or set(contenido) & set(pendientes)
                or sorted(set(pendientes)) != pendientes
                or not all(s is None or (isinstance(s, str) and len(s) == 64) for s in contenido.values())
                or not all(isinstance(c, str) and c.startswith(CARPETA_DIARIOS + "/") and c != rel for c in diario["cierra"])
                or not all(isinstance(r, str) and rastreable(r) and (s is None or (isinstance(s, str) and len(s) == 64))
                           for r, s in diario["recuperacion"].items())):
            raise EstadoNoVerificado(f"diario {rel}: contenido inválido")
    return diario


def identidades_dataset(datos: bytes) -> set[str]:
    """Columna ``archivo`` del dataset: única y completa, o EstadoNoVerificado."""
    csv.field_size_limit(max(csv.field_size_limit(), 100_000_000))
    try:
        lector = csv.DictReader(io.StringIO(datos.decode("utf-8-sig"), newline=""), delimiter=";", strict=True)
        if not lector.fieldnames or "archivo" not in lector.fieldnames:
            raise ValueError("falta columna archivo")
        resultado = set()
        for fila in lector:
            if None in fila or any(v is None for v in fila.values()):
                raise ValueError("fila incompleta")
            archivo = (fila.get("archivo") or "").strip()
            if not archivo or archivo in resultado:
                raise ValueError("identidad ausente o duplicada")
            resultado.add(archivo)
        return resultado
    except (UnicodeError, csv.Error, ValueError) as error:
        raise EstadoNoVerificado(f"dataset no verificable: {error}") from error


ARCHIVO_PUBLICACION = "raiz_publicada.json"
# Carpetas no custodiadas que el Motor sí lee entre equipos (reporte vigente,
# respaldos de acciones): se publican al confirmar y se traen si faltan.
PUBLICABLES_NO_CUSTODIADOS = ("reportes", "respaldos", "backups")


def ruta_configuracion_publicacion() -> Path:
    from atlas_core.aislamiento_empresas import base_local
    return base_local() / ARCHIVO_PUBLICACION


def configuracion_publicacion() -> dict | None:
    """P0.3.1. ``{"raiz_trabajo", "raiz_publicada"}`` de la empresa del
    proceso, o None (modo anterior: se escribe en la raíz que se reciba)."""
    datos = _leer_json(ruta_configuracion_publicacion(), None)
    if not isinstance(datos, dict):
        return None
    trabajo, publicada = datos.get("raiz_trabajo"), datos.get("raiz_publicada")
    if not (isinstance(trabajo, str) and isinstance(publicada, str) and trabajo and publicada):
        return None
    return {"raiz_trabajo": trabajo, "raiz_publicada": publicada}


def _misma_ruta(a, b) -> bool:
    return os.path.normcase(os.path.abspath(os.fspath(a))).rstrip("\\/") == os.path.normcase(os.path.abspath(os.fspath(b))).rstrip("\\/")


def _publicable_no_custodiado(rel: str) -> bool:
    partes = rel.split("/")
    nombre = partes[-1].lower()
    return (len(partes) >= 2 and partes[0] in PUBLICABLES_NO_CUSTODIADOS and not nombre.endswith(".tmp")
            and not partes[-1].startswith(".atlas_lock_"))


def ruta_local() -> Path:
    # Dentro de LOCALAPPDATA/Atlas/cache: única carpeta local que la sesión
    # Desktop autoriza a escribir además de la raíz y los temporales.
    from atlas_core.aislamiento_empresas import base_local
    return base_local() / "cache" / "estado_confirmado"


def rastreable(rel: str) -> bool:
    partes = rel.split("/")
    if not partes or partes[0] in EXCLUIDOS_PRIMER_NIVEL:
        return False
    nombre = partes[-1]
    bajo = nombre.lower()
    return not (nombre.startswith(".atlas_lock_") or bajo.endswith(".tmp") or nombre.startswith("~$")
                or bajo == "desktop.ini" or ".atlas_restaurar." in nombre)


def sha256_archivo(ruta: Path) -> str:
    h = hashlib.sha256()
    with open(ruta, "rb") as archivo:
        for bloque in iter(lambda: archivo.read(1024 * 1024), b""):
            h.update(bloque)
    return h.hexdigest()


def _leer_json(ruta: Path, defecto):
    try:
        return json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return defecto


def _escribir_json(ruta: Path, datos) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    temporal = ruta.with_name(f"{ruta.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    temporal.write_text(json.dumps(datos, ensure_ascii=False), encoding="utf-8")
    os.replace(temporal, ruta)


class ClienteEstado:
    """Endpoints /api/motor/estado/* del Worker, mismo token que el lease."""

    def __init__(self, base_url: str, token_motor: str, timeout: float) -> None:
        self.base_url = base_url
        self.token_motor = token_motor
        self.timeout = timeout

    def _json(self, ruta, *, method="GET", body=None):
        from atlas_core.escritor_operativo import _json
        return _json(self.base_url, ruta, self.token_motor, method=method, body=body, timeout=self.timeout)

    def manifiesto(self) -> dict:
        return self._json("/api/motor/estado/manifiesto")

    def conocidos(self, consultas: list[list[str]]) -> list[bool]:
        salida: list[bool] = []
        for i in range(0, len(consultas), LOTE_CONSULTA):
            salida += self._json("/api/motor/estado/conocidos", method="POST", body={"consultas": consultas[i:i + LOTE_CONSULTA]})["conocidos"]
        return salida

    def faltantes(self, huellas: list[str]) -> list[str]:
        salida: list[str] = []
        for i in range(0, len(huellas), LOTE_CONSULTA):
            salida += self._json("/api/motor/estado/faltantes", method="POST", body={"sha256": huellas[i:i + LOTE_CONSULTA]})["faltantes"]
        return salida

    def _crudo(self, sha: str, *, method: str, data: bytes | None = None, lease_token: str = "") -> bytes:
        from atlas_core.escritor_operativo import ErrorEscritorOperativo, _url
        headers = {"Authorization": f"Bearer {self.token_motor}", "User-Agent": "Atlas-Estado-Confirmado/1.0",
                   "Content-Type": "application/octet-stream"}
        if lease_token:
            headers["X-Atlas-Lease"] = lease_token
        request = urllib.request.Request(_url(self.base_url, f"/api/motor/estado/objetos/{sha}"), method=method, data=data, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=max(self.timeout, 120.0)) as response:
                return response.read()
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise ErrorEscritorOperativo(f"Cloud estado {method} objeto {sha[:12]}: {error}") from error

    def subir(self, sha: str, datos: bytes, lease_token: str) -> None:
        self._crudo(sha, method="PUT", data=datos, lease_token=lease_token)

    def descargar(self, sha: str) -> bytes:
        return self._crudo(sha, method="GET")

    def confirmar(self, lease_token: str, version_base: int, archivos: list[list]) -> int:
        respuesta = self._json("/api/motor/estado/confirmar", method="POST",
                               body={"lease_token": lease_token, "version_base": version_base, "archivos": archivos})
        if respuesta.get("estado") != "CONFIRMADO":
            raise EstadoNoVerificado("confirmación de estado rechazada")
        return int(respuesta["version"])


_activas: list["CustodiaEstado"] = []
PENDIENTE = "pendiente"
BORRADO = "borrado"
_local = threading.local()


def _dir_fd(valor):
    # Windows informa -1 cuando no hay dir_fd; sólo un descriptor real impide
    # conocer la ruta absoluta.
    return valor if isinstance(valor, int) and valor >= 0 else None


def _auditar(evento, args):
    if not _activas or getattr(_local, "dentro", False):
        return
    if evento == "open":
        ruta, modo, flags = args
        if not ((modo and any(c in modo for c in "wax+")) or
                (flags and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND))):
            return
        # Escritura directa: el contenido final aún no existe (pendiente).
        destinos, dir_fd = [(ruta, PENDIENTE)], None
    elif evento == "os.rename":
        # El origen ya tiene el contenido completo: se custodia antes de que
        # aparezca en el destino (patrón temporal + os.replace del Motor).
        destinos = [(args[1], ("origen", args[0])), (args[0], BORRADO)]
        dir_fd = _dir_fd(args[2]) if _dir_fd(args[2]) is not None else _dir_fd(args[3])
    elif evento in {"os.remove", "os.truncate"}:
        destinos = [(args[0], BORRADO if evento == "os.remove" else PENDIENTE)]
        dir_fd = _dir_fd(args[1]) if len(args) > 1 and evento == "os.remove" else None
    elif evento == "os.rmdir":
        destinos, dir_fd = [], _dir_fd(args[1]) if len(args) > 1 else None
        for custodia in tuple(_activas):
            if dir_fd is not None or custodia.contiene(args[0]):
                custodia.borrado_sin_ruta = True
        return
    else:
        return
    _local.dentro = True
    try:
        for custodia in tuple(_activas):
            if dir_fd is not None:
                custodia.borrado_sin_ruta = True
                continue
            cambios = [(d, efecto) for d, efecto in destinos if d is not None and not isinstance(d, int)]
            if cambios:
                custodia.anotar(cambios)
    finally:
        _local.dentro = False


def punto_de_control_tras_escritura(ruta) -> bool:
    """Para escritores directos ya cerrados: nunca lanza (la escritura ya
    ocurrió; relanzar invitaría a reintentar y duplicar). Si falla, la ruta
    queda pendiente: el turno confirma igual al cerrar, pero otro equipo no
    podrá recuperarlo automáticamente si este equipo se pierde antes."""
    try:
        punto_de_control(ruta)
        return True
    except Exception as error:  # noqa: BLE001
        log.warning("Contenido de %s no custodiado tras escribir; recuperación remota bloqueada: %s", ruta, error)
        return False


def punto_de_control(ruta) -> None:
    """Tras CERRAR una escritura directa (``open("a")``/``open("w")`` sobre la
    ruta final), custodia su contenido ya completo. Sin custodia activa no
    hace nada. Si falla, la excepción se propaga: el llamador no debe dar la
    operación por persistida."""
    if not _activas or getattr(_local, "dentro", False):
        return
    _local.dentro = True
    try:
        for custodia in tuple(_activas):
            if custodia.contiene(ruta):
                custodia.anotar([(ruta, ("origen", ruta))])
    finally:
        _local.dentro = False


sys.addaudithook(_auditar)


class CustodiaEstado:
    def __init__(self, raiz, cliente: ClienteEstado, *, carpeta_local: Path | None = None) -> None:
        from atlas_core.aislamiento_empresas import exigir_raiz_de_proceso
        exigir_raiz_de_proceso(raiz)
        self.raiz = Path(os.path.abspath(raiz))
        self._raiz_norm = os.path.normcase(str(self.raiz)).rstrip("\\/") + os.sep
        self.cliente = cliente
        self.local = carpeta_local or ruta_local()
        self.version = 0
        self.manifiesto: dict[str, str | None] = {}
        self.modificadas: set[str] = set()
        self.borrado_sin_ruta = False
        self.resumen: dict = {}
        self.ajenos_descartados: list[str] = []
        # P0.3.1: raíz de trabajo local (fuera de Drive) y raíz publicada.
        configuracion = configuracion_publicacion()
        self.publicada: Path | None = None
        self._raiz_es_publicada = False
        if configuracion:
            if _misma_ruta(configuracion["raiz_trabajo"], self.raiz):
                self.publicada = Path(configuracion["raiz_publicada"])
            elif _misma_ruta(configuracion["raiz_publicada"], self.raiz):
                self._raiz_es_publicada = True
        self.publicables: set[str] = set()
        self._lease = None
        self._diario: str | None = None
        self._diario_abierto_en = ""
        self._version_turno = 0
        # Contenido custodiado de cada ruta escrita en el turno (huella ya en
        # Cloud, o None si se borró) y rutas cuyo contenido final aún no lo está.
        self.contenido: dict[str, str | None] = {}
        self.pendientes: set[str] = set()
        # Diarios de otros turnos que este turno recupera: se cierran en el
        # mismo lote final que confirma sus datos.
        self._cierra: set[str] = set()
        # Resultado esperado de una recuperación en curso (ruta -> huella).
        self._recuperacion: dict[str, str | None] = {}
        self._cerrojo = threading.Lock()

    # --------------------------------------------------------------- rutas
    @property
    def _ruta_manifiesto(self): return self.local / "manifiesto.json"
    @property
    def _ruta_pendiente(self): return self.local / "pendiente.json"

    def contiene(self, ruta) -> bool:
        return os.path.normcase(os.path.abspath(os.fsdecode(ruta))).startswith(self._raiz_norm)

    def _rel(self, ruta) -> str | None:
        absoluta = os.path.abspath(os.fsdecode(ruta))
        if not os.path.normcase(absoluta).startswith(self._raiz_norm):
            return None
        return os.path.relpath(absoluta, self.raiz).replace(os.sep, "/")

    def _abs(self, rel: str) -> Path:
        return self.raiz.joinpath(*rel.split("/"))

    # ------------------------------------------------------------- huellas
    def _huellas_locales(self, rels) -> dict[str, str | None]:
        """Siempre por contenido: dos escrituras de igual tamaño pueden compartir
        fecha (en Windows, dentro de un mismo tic del reloj), de modo que tamaño
        y fecha no prueban que un archivo siga igual."""
        salida = {}
        for rel in rels:
            ruta = self._abs(rel)
            try:
                ruta.stat()
            except OSError:
                salida[rel] = None
                continue
            salida[rel] = sha256_archivo(ruta) if ruta.is_file() else None
        return salida

    def _cargar_manifiesto(self, version: int) -> dict[str, str | None]:
        cache = _leer_json(self._ruta_manifiesto, {})
        if cache.get("version") == version and isinstance(cache.get("archivos"), dict):
            return cache["archivos"]
        datos = self.cliente.manifiesto()
        if int(datos.get("version", -1)) != version:
            raise EstadoNoVerificado("manifiesto Cloud cambió durante la alineación")
        archivos = {ruta: sha for ruta, sha, _v in datos.get("archivos", [])}
        _escribir_json(self._ruta_manifiesto, {"version": version, "archivos": archivos})
        return archivos

    # ---------------------------------------------------------- alineación
    def _proteger_dataset_local(self, distintos: dict[str, str | None]) -> None:
        """Fail closed before a Cloud alignment can discard local documents."""
        rel = RUTA_DATASET
        if rel not in distintos or not distintos[rel]:
            return
        if self.publicada is not None and self._dataset_de_turno_propio(rel):
            # P0.3.1: la raíz de trabajo no la toca Drive; un dataset local no
            # confirmado sólo puede venir de un turno propio superado, cuyo
            # diario sigue abierto en Cloud. Va a cuarentena (no se pierde).
            log.warning("Estado confirmado: dataset de un turno propio no confirmado va a cuarentena")
            return
        if distintos[rel] in self._contenidos_custodiados(rel):
            # El dataset local es exactamente el que escribió un turno caído
            # (Drive lo trajo) y su contenido ya está en Cloud, nombrado por
            # un diario abierto: alinear no pierde nada, la recuperación del
            # turno lo vuelve a aplicar desde Cloud.
            return
        esperado = self.manifiesto[rel]
        if not esperado:
            raise EstadoNoVerificado("Cloud eliminaria el dataset local; requiere revision")
        remoto = self.cliente.descargar(esperado)
        if hashlib.sha256(remoto).hexdigest() != esperado:
            raise EstadoNoVerificado("dataset Cloud no coincide con su huella")
        if identidades_dataset(self._abs(rel).read_bytes()) - identidades_dataset(remoto):
            raise EstadoNoVerificado("alineacion eliminaria documentos locales; requiere recuperacion")

    def _dataset_de_turno_propio(self, rel: str) -> bool:
        escritor = getattr(self, "_escritor_alineando", "")
        prefijo = f"{CARPETA_DIARIOS}/{escritor}/"
        for diario_rel, sha in self.manifiesto.items():
            if not escritor or not sha or not diario_rel.startswith(prefijo):
                continue
            try:
                if rel in interpretar_diario(diario_rel, self.cliente.descargar(sha), sha)["rutas"]:
                    return True
            except Exception:  # noqa: BLE001 - un diario ilegible no habilita nada
                continue
        return False

    def _contenidos_custodiados(self, rel: str) -> set[str]:
        """Huellas que los diarios abiertos (formato 2) custodian para ``rel``."""
        huellas = set()
        for diario_rel, sha in self.manifiesto.items():
            if not sha or not diario_rel.startswith(CARPETA_DIARIOS + "/"):
                continue
            try:
                diario = interpretar_diario(diario_rel, self.cliente.descargar(sha), sha)
            except Exception:  # noqa: BLE001 - un diario ilegible no habilita nada
                continue
            if diario["formato"] == FORMATO_DIARIO and diario["contenido"].get(rel):
                huellas.add(diario["contenido"][rel])
        return huellas

    def _exigir_custodia_propia(self) -> None:
        """Antes de restaurar nada: un token ajeno volcaría datos de otra empresa."""
        from atlas_core.aislamiento_empresas import ErrorAislamiento, multiempresa_activa, verificar_manifiesto_empresa
        try:
            manifiesto = operacionales(self.manifiesto)
            if multiempresa_activa(self.raiz):
                # La caché local va por versión: con varias empresas, un token
                # ajeno de igual versión pasaría por el manifiesto propio.
                datos = self.cliente.manifiesto()
                manifiesto = operacionales({fila[0]: fila[1] for fila in datos.get("archivos", [])})
            verificar_manifiesto_empresa(self.raiz, manifiesto, self.cliente.descargar)
        except ErrorAislamiento as error:
            raise EstadoNoVerificado(str(error)) from error

    def alinear(self, lease) -> dict:
        """Antes de escribir: copia local == marca Cloud, o EstadoNoVerificado."""
        if self._raiz_es_publicada:
            raise EstadoNoVerificado("esta raíz es la publicada (Drive): sólo recibe datos confirmados; "
                                     "el Motor escribe en la raíz de trabajo")
        self.version = int(lease.marca.get("version") or 0)
        self._escritor_alineando = getattr(lease, "escritor_id", "")
        self.manifiesto = dict(self._cargar_manifiesto(self.version))
        self._exigir_custodia_propia()
        resumen = {"version": self.version, "restaurados": [], "borrados": [], "cuarentena": [], "pendiente_confirmado": 0,
                   "diarios_abiertos": []}
        self._recuperar_pendiente(lease, resumen)
        # Diarios de turnos que nunca confirmaron (equipo apagado o perdido):
        # quedan intactos en Cloud; este turno no los anula ni los adopta.
        resumen["diarios_abiertos"] = sorted(rel for rel, sha in self.manifiesto.items()
                                             if sha and rel.startswith(CARPETA_DIARIOS + "/"))
        if resumen["diarios_abiertos"]:
            log.warning("Estado confirmado: %d diario(s) de recuperación abiertos en Cloud: %s",
                        len(resumen["diarios_abiertos"]), resumen["diarios_abiertos"][:5])
        operacional = operacionales(self.manifiesto)
        locales = self._huellas_locales(operacional)
        distintos = {rel: sha for rel, sha in locales.items() if sha != operacional[rel]}
        if distintos:
            self._proteger_dataset_local(distintos)
            consultas = [[rel, sha] for rel, sha in distintos.items() if sha]
            conocidos = dict(zip((c[0] for c in consultas), self.cliente.conocidos(consultas))) if consultas else {}
            destino_cuarentena = self.local / "cuarentena" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            for rel, sha_local in sorted(distintos.items()):
                if sha_local and not conocidos.get(rel):
                    # Contenido nunca confirmado (escritura fuera de protocolo o
                    # turno caído y superado): se conserva fuera de Drive.
                    copia = destino_cuarentena.joinpath(*rel.split("/"))
                    copia.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(self._abs(rel), copia)
                    resumen["cuarentena"].append(rel)
                esperado = self.manifiesto[rel]
                if esperado is None:
                    self._abs(rel).unlink(missing_ok=True)
                    resumen["borrados"].append(rel)
                else:
                    self._restaurar(rel, esperado)
                    resumen["restaurados"].append(rel)
            if resumen["cuarentena"]:
                log.warning("Estado confirmado: %d archivo(s) local(es) nunca confirmados en cuarentena %s", len(resumen["cuarentena"]), destino_cuarentena)
            locales = self._huellas_locales(operacional)
            residuo = [rel for rel, sha in locales.items() if sha != operacional[rel]]
            if residuo:
                raise EstadoNoVerificado(f"copia local no coincide con la marca Cloud v{self.version}: {residuo[:5]}")
        if self.publicada is not None:
            resumen["traidos_de_publicada"] = self._traer_publicados()
            resumen["publicacion_reintentada"] = self._reintentar_publicacion()
        self.resumen = resumen
        return resumen

    # ------------------------------------------------ publicación (P0.3.1)
    @property
    def _ruta_publicacion_pendiente(self): return self.local / "publicacion_pendiente.json"

    def _escribir_publicada(self, rel: str, datos: bytes | None) -> None:
        destino = self.publicada.joinpath(*rel.split("/"))
        if datos is None:
            destino.unlink(missing_ok=True)
            return
        destino.parent.mkdir(parents=True, exist_ok=True)
        temporal = destino.with_name(f".{destino.name}.atlas_publicar.{os.getpid()}.tmp")
        temporal.write_bytes(datos)
        os.replace(temporal, destino)

    def _publicar(self, pares: list[list]) -> list[str]:
        """Copia a la raíz publicada lo que Cloud YA confirmó: la huella
        confirmada, desde la raíz de trabajo o, si allí hay otra cosa, desde
        Cloud. Nunca falla la confirmación: lo no publicado queda pendiente
        y se reintenta al alinear el próximo turno."""
        if self.publicada is None:
            return []
        fallidas = {}
        for rel, sha in pares:
            if es_ruta_custodia(rel):
                continue
            try:
                datos = None
                if sha is not None:
                    origen = self._abs(rel)
                    datos = origen.read_bytes() if origen.is_file() else b""
                    if hashlib.sha256(datos).hexdigest() != sha:
                        datos = self.cliente.descargar(sha)
                        if hashlib.sha256(datos).hexdigest() != sha:
                            raise EstadoNoVerificado(f"contenido Cloud de {rel} no coincide con su huella")
                self._escribir_publicada(rel, datos)
            except Exception as error:  # noqa: BLE001
                log.warning("Publicación de %s pendiente: %s", rel, error)
                fallidas[rel] = sha
        if fallidas:
            pendiente = _leer_json(self._ruta_publicacion_pendiente, {})
            pendiente = pendiente if isinstance(pendiente, dict) else {}
            _escribir_json(self._ruta_publicacion_pendiente, {**pendiente, **fallidas})
        return sorted(fallidas)

    def _publicar_no_custodiados(self, rels) -> None:
        for rel in sorted(rels):
            origen = self._abs(rel)
            try:
                if origen.is_file():
                    self._escribir_publicada(rel, origen.read_bytes())
            except OSError as error:
                log.warning("Publicación de %s no realizada: %s", rel, error)

    def _reintentar_publicacion(self) -> int:
        pendiente = _leer_json(self._ruta_publicacion_pendiente, None)
        if not isinstance(pendiente, dict) or not pendiente:
            return 0
        self._ruta_publicacion_pendiente.unlink(missing_ok=True)
        # Tras alinear, la raíz de trabajo es la marca vigente: se publica el
        # valor confirmado actual de cada ruta (puede ser más nuevo).
        actuales = operacionales(self.manifiesto)
        pares = [[rel, actuales.get(rel)] for rel in pendiente if isinstance(rel, str) and rel in actuales]
        self._publicar(pares)
        return len(pares)

    def _traer_publicados(self) -> int:
        """Reportes/respaldos de turnos confirmados en otros equipos (sólo
        llegan a la raíz publicada si su turno confirmó): se traen las
        carpetas que falten, sin sobrescribir nada."""
        traidos = 0
        for carpeta in PUBLICABLES_NO_CUSTODIADOS:
            base = self.publicada / carpeta
            try:
                entradas = list(base.iterdir()) if base.is_dir() else []
            except OSError:
                continue
            for entrada in entradas:
                destino = self.raiz / carpeta / entrada.name
                if destino.exists() or entrada.name.lower().endswith(".tmp"):
                    continue
                try:
                    if entrada.is_dir():
                        shutil.copytree(entrada, destino)
                    else:
                        destino.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(entrada, destino)
                    traidos += 1
                except OSError as error:
                    log.warning("No se trajo %s desde la raíz publicada: %s", entrada, error)
        return traidos

    def _restaurar(self, rel: str, sha: str) -> None:
        datos = self.cliente.descargar(sha)
        if hashlib.sha256(datos).hexdigest() != sha:
            raise EstadoNoVerificado(f"contenido Cloud de {rel} no coincide con su huella")
        destino = self._abs(rel)
        destino.parent.mkdir(parents=True, exist_ok=True)
        temporal = destino.with_name(f".{destino.name}.atlas_restaurar.{os.getpid()}.tmp")
        temporal.write_bytes(datos)
        os.replace(temporal, destino)

    def _recuperar_pendiente(self, lease, resumen: dict) -> None:
        pendiente = _leer_json(self._ruta_pendiente, None)
        if not isinstance(pendiente, dict):
            return
        rutas = [r for r in pendiente.get("rutas", []) if isinstance(r, str) and rastreable(r)]
        if (pendiente.get("escritor_id") == lease.escritor_id and pendiente.get("version_base") == self.version
                and pendiente.get("raiz") == str(self.raiz) and rutas):
            # Turno anterior de este mismo equipo caído antes de confirmar y
            # nadie confirmó después: esas escrituras son el estado más nuevo.
            # Su diario remoto se anula en el mismo lote que las confirma.
            # Si ese turno recuperaba diarios ajenos, se cierran sólo si la
            # recuperación quedó completa en la raíz; si no, sus rutas no se
            # confirman y el diario ajeno sigue abierto (se recupera de nuevo).
            diarios = [pendiente.get("diario")]
            recuperacion = pendiente.get("recuperacion") if isinstance(pendiente.get("recuperacion"), dict) else {}
            locales_rec = self._huellas_locales([r for r in recuperacion if rastreable(r)])
            if all(locales_rec.get(r) == s for r, s in recuperacion.items()):
                diarios += list(pendiente.get("cierra") or [])
            else:
                rutas = [r for r in rutas if r not in recuperacion]
            extra = [[d, None] for d in sorted({d for d in diarios if isinstance(d, str) and es_ruta_custodia(d)})
                     if self.manifiesto.get(d)]
            conocidos = pendiente.get("contenido") if isinstance(pendiente.get("contenido"), dict) else {}
            conocidos = {r: s for r, s in conocidos.items()
                         if isinstance(r, str) and (s is None or (isinstance(s, str) and len(s) == 64))}
            resumen["pendiente_confirmado"] = len(self._confirmar_rutas(lease, rutas, extra=extra, conocidos=conocidos))
        # Con la marca ya superada, la alineación pone esos archivos en
        # cuarentena (contenido nunca confirmado) y restaura la versión vigente.
        self._ruta_pendiente.unlink(missing_ok=True)

    # ------------------------------------------------------------ registro
    def iniciar(self, lease) -> None:
        self._lease = lease
        self.modificadas = set()
        self.borrado_sin_ruta = False
        self._diario = None
        self._diario_abierto_en = ""
        self._version_turno = self.version
        self.contenido = {}
        self.pendientes = set()
        self._cierra = set()
        self._recuperacion = {}
        self.publicables = set()
        _activas.append(self)

    def detener(self) -> None:
        if self in _activas:
            _activas.remove(self)
        self._lease = None

    def registrar(self, ruta) -> None:
        """Compatibilidad: una escritura de contenido aún desconocido."""
        self.anotar([(ruta, PENDIENTE)])

    def anotar(self, cambios) -> None:
        """Registra en el diario remoto, ANTES de que ocurra, cada cambio de
        ruta rastreable: ``PENDIENTE`` (escritura directa, contenido final aún
        desconocido), ``BORRADO`` o ``("origen", ruta)``: el archivo cuyo
        contenido completo pasará a la ruta (temporal + os.replace, o el mismo
        archivo en un punto de control). Ese contenido se sube a Cloud antes
        del diario que lo nombra. Si algo falla, la excepción sale del audit
        hook y la escritura no ocurre."""
        entradas = []
        for ruta, efecto in cambios:
            rel = self._rel(ruta)
            if rel is not None and rastreable(rel):
                entradas.append((rel, efecto))
            elif rel is not None and self.publicada is not None and _publicable_no_custodiado(rel) and efecto != BORRADO:
                # Reportes/respaldos del turno: se publican sólo si confirma.
                self.publicables.add(rel)
        if not entradas:
            return
        with self._cerrojo:
            lease = self._lease
            # P0.3: el estado local del lease no basta (puede creerse vigente
            # tras una suspensión o un heartbeat atrasado) y el destino, la
            # raíz que Drive replica, no admite fencing propio. Cada escritura:
            # 1) exige que el destino contenga lo que este turno espera, así
            #    un contenido ajeno traído por Drive nunca se pisa ni se adopta;
            # 2) se valida contra el servidor (publicación del diario o
            #    renovación), que rechaza un lease vencido o sustituido.
            if lease is None or not getattr(lease, "vigente", False):
                raise EscritorSustituido("el turno ya no tiene lease vigente; no se escribe")
            for rel, efecto in entradas:
                self._exigir_contenido_esperado(rel)
            contenido, pendientes, objetos = dict(self.contenido), set(self.pendientes), {}
            for rel, efecto in entradas:
                if efecto == BORRADO:
                    contenido[rel] = None
                    pendientes.discard(rel)
                    continue
                datos = None
                if efecto != PENDIENTE:
                    origen = Path(os.fsdecode(efecto[1]))
                    try:
                        datos = origen.read_bytes() if origen.is_file() else None
                    except OSError:
                        datos = None
                    if datos is None and origen.is_dir():
                        self.borrado_sin_ruta = True
                if datos is None:
                    contenido.pop(rel, None)
                    pendientes.add(rel)
                else:
                    huella = hashlib.sha256(datos).hexdigest()
                    objetos[huella] = datos
                    contenido[rel] = huella
                    pendientes.discard(rel)
            rutas = self.modificadas | {rel for rel, _efecto in entradas}
            if (rutas == self.modificadas and contenido == self.contenido and pendientes == self.pendientes
                    and self._diario):
                # Nada nuevo que publicar: igual se consulta al servidor.
                self._exigir_lease_en_servidor(lease)
                return
            self._publicar_diario(lease, rutas, contenido, pendientes, objetos)
            self.modificadas, self.contenido, self.pendientes = rutas, contenido, pendientes
            self._guardar_pendiente_local(lease)

    def _exigir_lease_en_servidor(self, lease) -> None:
        """La renovación sólo prospera con el token vigente en Cloud y lo
        extiende: tras ella nadie más puede adquirir durante el plazo del
        lease. Vencido o sustituido, la escritura se aborta."""
        renovar = getattr(lease, "renovar", None)
        if renovar is None or not renovar():
            raise EscritorSustituido("Cloud rechazó el lease de este turno (vencido o sustituido); no se escribe")

    def _contenido_esperado(self, rel: str):
        """Lo que la raíz debe contener en ``rel`` según este turno: lo último
        que escribió, o la marca alineada si no la tocó. ``PENDIENTE`` si no
        hay referencia: escritura directa sin contenido custodiado aún, o ruta
        que la marca no conoce (fuera de la semilla; la alineación no la fija)."""
        if rel in self.pendientes:
            return PENDIENTE
        if rel in self.contenido:
            return self.contenido[rel]
        manifiesto = operacionales(self.manifiesto)
        return manifiesto[rel] if rel in manifiesto else PENDIENTE

    def _exigir_contenido_esperado(self, rel: str) -> None:
        esperado = self._contenido_esperado(rel)
        if esperado == PENDIENTE:
            return
        actual = self._huellas_locales([rel])[rel]
        if actual != esperado:
            raise ContenidoAjeno(f"{rel} cambió fuera de este turno (posible escritor anterior vía Drive); no se escribe")

    def _guardar_pendiente_local(self, lease) -> None:
        # Diario local: si el equipo se apaga a mitad, el próximo turno de
        # este mismo equipo sabe qué confirmar o aislar.
        _escribir_json(self._ruta_pendiente, {
            "escritor_id": getattr(lease, "escritor_id", ""), "version_base": self.version,
            "raiz": str(self.raiz), "rutas": sorted(self.modificadas), "diario": self._diario,
            "cierra": sorted(self._cierra), "recuperacion": self._recuperacion, "contenido": self.contenido,
        })

    def _publicar_diario(self, lease, rutas: set[str], contenido: dict | None = None,
                         pendientes: set[str] | None = None, objetos: dict | None = None) -> None:
        from atlas_core.aislamiento_empresas import empresa_de_raiz
        contenido = self.contenido if contenido is None else contenido
        pendientes = self.pendientes if pendientes is None else pendientes
        try:
            ahora = datetime.now(timezone.utc).isoformat(timespec="microseconds")
            self._diario_abierto_en = self._diario_abierto_en or ahora
            ordenadas = sorted(rutas)
            base = operacionales(self.manifiesto)
            epoca = int(getattr(lease, "epoca", 0) or 0)
            diario = {
                "tipo": TIPO_DIARIO, "formato": FORMATO_DIARIO,
                "empresa_id": empresa_de_raiz(self.raiz),
                "escritor_id": lease.escritor_id, "epoca": epoca,
                "lease_sha256": hashlib.sha256(lease.lease_token.encode("utf-8")).hexdigest(),
                "version_base": self._version_turno, "raiz": str(self.raiz),
                "abierto_en": self._diario_abierto_en, "actualizado_en": ahora,
                "rutas": ordenadas, "huellas_base": {r: base.get(r) for r in ordenadas},
                "contenido": {r: contenido[r] for r in ordenadas if r in contenido},
                "pendientes": sorted(pendientes), "cierra": sorted(self._cierra),
                "recuperacion": dict(sorted(self._recuperacion.items())),
            }
            rel = ruta_diario(lease.escritor_id, epoca)
            datos = serializar_diario(diario)
            sha = hashlib.sha256(datos).hexdigest()
            # Primero el contenido y después el diario: un diario nunca nombra
            # lo que Cloud no tiene. Sólo se sube lo que falta (una consulta).
            subir = {**(objetos or {}), sha: datos}
            ausentes = set(self.cliente.faltantes(sorted(subir)))
            for huella in sorted(ausentes - {sha}) + sorted(ausentes & {sha}):
                self.cliente.subir(huella, subir[huella], lease.lease_token)
            # Igual que una confirmación de datos: exige lease vigente y la
            # versión que este turno conoce. Sin éxito no hay escritura.
            self.version = self.cliente.confirmar(lease.lease_token, self.version, [[rel, sha]])
        except Exception as error:  # noqa: BLE001 - cualquier duda: no escribir
            raise DiarioNoPersistido(f"diario de recuperación no persistido en Cloud; no se escribe: {error}") from error
        self._diario = rel
        self.manifiesto[rel] = sha
        _escribir_json(self._ruta_manifiesto, {"version": self.version, "archivos": self.manifiesto})

    # --------------------------------------------------------- confirmación
    def confirmar(self, lease) -> dict:
        rutas = set(self.modificadas)
        if self.borrado_sin_ruta:
            rutas |= {rel for rel, sha in operacionales(self.manifiesto).items() if sha is not None and not self._abs(rel).exists()}
        # El puntero al diario del turno se anula en el mismo lote final: los
        # datos y el cierre del diario quedan confirmados juntos o no quedan.
        cerrar = sorted({d for d in [self._diario, *self._cierra] if d and self.manifiesto.get(d)})
        extra = [[d, None] for d in cerrar]
        self.ajenos_descartados = []
        confirmadas = (self._confirmar_rutas(lease, sorted(rutas), extra=extra, conocidos=self.contenido)
                       if rutas or extra else [])
        self._diario = None
        self._cierra, self._recuperacion = set(), {}
        self._ruta_pendiente.unlink(missing_ok=True)
        self.modificadas = set()
        self.contenido, self.pendientes = {}, set()
        # El turno confirmó: también se publican sus reportes y respaldos.
        publicables, self.publicables = self.publicables, set()
        self._publicar_no_custodiados(publicables)
        return {"version": self.version, "confirmados": len(confirmadas), "ajenos_descartados": self.ajenos_descartados}

    # ------------------------------------------------- recuperación (P0.2)
    def recuperar_turno(self, lease, diario_rel: str, *, aplicar: bool = False) -> dict:
        """Recupera, desde este equipo, un turno de otro escritor que nunca
        confirmó, usando sólo lo que está en Cloud: su diario y el contenido
        custodiado de cada ruta. Sin ``aplicar`` sólo informa.

        Todo o nada. Se bloquea si: el diario no trae contenido (formato 1) o
        tiene rutas sin contenido custodiado; alguna ruta cambió en Cloud
        después de la base del turno (no se pisa una versión posterior); la
        copia local no coincide con Cloud; el dataset resultante perdería o
        duplicaría documentos. Al aplicar, los datos y el cierre del diario
        se confirman en el mismo lote final: un segundo intento ve el diario
        cerrado y no aplica nada (sin duplicados)."""
        from atlas_core.aislamiento_empresas import empresa_de_raiz
        if self not in _activas or self._lease is not lease or not getattr(lease, "vigente", False):
            raise EstadoNoVerificado("recuperar un turno exige lease vigente y custodia alineada")
        datos_marca = self.cliente.manifiesto()
        if int(datos_marca.get("version", -1)) != self.version:
            raise EstadoNoVerificado("la marca Cloud cambió desde la alineación; no se recupera")
        remoto = {r: s for r, s, _v in datos_marca.get("archivos", [])}
        resultado: dict = {"diario": diario_rel, "version": self.version}
        if not diario_rel.startswith(CARPETA_DIARIOS + "/") or diario_rel not in remoto:
            return {**resultado, "estado": "DIARIO_INEXISTENTE"}
        sha_diario = remoto[diario_rel]
        if not sha_diario:
            return {**resultado, "estado": "YA_CERRADO"}
        if diario_rel == self._diario:
            return {**resultado, "estado": "TURNO_PROPIO"}
        diario = interpretar_diario(diario_rel, self.cliente.descargar(sha_diario), sha_diario)
        if diario["empresa_id"] != empresa_de_raiz(self.raiz):
            raise EstadoNoVerificado(f"diario {diario_rel} pertenece a otra empresa: {diario['empresa_id']}")
        resultado.update(escritor_id=diario["escritor_id"], epoca=diario["epoca"], version_base=diario["version_base"],
                         sha256_diario=sha_diario)
        if diario["formato"] != FORMATO_DIARIO:
            return {**resultado, "estado": "BLOQUEADO", "bloqueos": [{"codigo": "DIARIO_SIN_CONTENIDO", "formato": diario["formato"]}]}
        bloqueos: list[dict] = []
        if diario["version_base"] > self.version:
            bloqueos.append({"codigo": "VERSION_INCOMPATIBLE", "version_base": diario["version_base"]})
        if diario["pendientes"]:
            bloqueos.append({"codigo": "CONTENIDO_NO_CUSTODIADO", "rutas": diario["pendientes"]})
        contenido, base = diario["contenido"], diario["huellas_base"]
        actuales = operacionales(remoto)
        interrumpida = sorted(r for r, s in diario["recuperacion"].items()
                              if contenido.get(r, "ausente") != s and actuales.get(r) != s)
        if interrumpida:
            # Ese turno recuperaba a otro y se cortó a mitad: primero se
            # recuperan los diarios que nombra en "cierra".
            bloqueos.append({"codigo": "RECUPERACION_INTERRUMPIDA", "rutas": interrumpida, "diarios": diario["cierra"]})
        rutas, aplicar_rutas, posteriores = [], [], []
        for rel in diario["rutas"]:
            actual = actuales.get(rel)
            if rel in contenido and actual == contenido[rel]:
                accion = "YA_APLICADO"
            elif actual == base[rel]:
                accion = "APLICAR"
                aplicar_rutas.append(rel)
            else:
                accion = "VERSION_POSTERIOR"
                posteriores.append(rel)
            rutas.append({"ruta": rel, "base": base[rel], "actual": actual, "recuperado": contenido.get(rel), "accion": accion})
        resultado["rutas"] = rutas
        if posteriores:
            bloqueos.append({"codigo": "VERSION_POSTERIOR", "rutas": posteriores})
        distintas = [r for r, s in self._huellas_locales(aplicar_rutas).items() if s != actuales.get(r)]
        if distintas:
            bloqueos.append({"codigo": "COPIA_LOCAL_DISTINTA", "rutas": distintas})
        if bloqueos:
            return {**resultado, "estado": "BLOQUEADO", "bloqueos": bloqueos}
        recuperados: dict[str, bytes] = {}
        for rel in aplicar_rutas:
            if contenido[rel]:
                datos = self.cliente.descargar(contenido[rel])
                if hashlib.sha256(datos).hexdigest() != contenido[rel]:
                    raise EstadoNoVerificado(f"contenido Cloud de {rel} no coincide con su huella")
                recuperados[rel] = datos
        if RUTA_DATASET in aplicar_rutas:
            previo = identidades_dataset(self.cliente.descargar(actuales[RUTA_DATASET])) if actuales.get(RUTA_DATASET) else set()
            nuevo = identidades_dataset(recuperados[RUTA_DATASET]) if RUTA_DATASET in recuperados else set()
            if previo - nuevo:
                return {**resultado, "estado": "BLOQUEADO",
                        "bloqueos": [{"codigo": "PERDERIA_DOCUMENTOS", "documentos": sorted(previo - nuevo)[:20]}]}
            resultado["documentos_recuperados"] = sorted(nuevo - previo)
        if not aplicar:
            return {**resultado, "estado": "RECUPERABLE"}

        # Cierre del diario ajeno (y de los que ése recuperaba) junto con los
        # datos, y el resultado completo esperado: ambos quedan en el diario
        # propio antes de la primera escritura. Un corte a mitad nunca cierra
        # el diario ajeno con una recuperación parcial.
        self._cierra |= {diario_rel, *(d for d in diario["cierra"] if remoto.get(d))}
        self._recuperacion = {rel: contenido[rel] for rel in aplicar_rutas}
        escritas = []
        try:
            for rel in aplicar_rutas:
                escritas.append(rel)
                self._escribir_desde_nube(rel, recuperados.get(rel))
        except BaseException:
            # Deshacer: la raíz vuelve a la base confirmada y el turno no
            # cierra el diario ajeno.
            self._cierra, self._recuperacion = set(), {}
            for rel in escritas:
                previo = actuales.get(rel)
                self._escribir_desde_nube(rel, self.cliente.descargar(previo) if previo else None)
            raise
        registro = {"diario": diario_rel, "sha256_diario": sha_diario, "escritor_id": diario["escritor_id"],
                    "epoca": diario["epoca"], "version_base": diario["version_base"], "version_recuperacion": self.version,
                    "recuperado_por": lease.escritor_id, "epoca_recuperacion": int(getattr(lease, "epoca", 0) or 0),
                    "recuperado_en": datetime.now(timezone.utc).isoformat(timespec="seconds"), "rutas": rutas}
        auditoria = self._abs(f"{CARPETA_RECUPERACIONES}/{diario['escritor_id']}__{diario['epoca']}.json")
        auditoria.parent.mkdir(parents=True, exist_ok=True)
        temporal = auditoria.with_name(f".{auditoria.name}.{os.getpid()}.tmp")
        temporal.write_text(json.dumps(registro, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporal, auditoria)
        self.confirmar(lease)
        despues = {r: s for r, s, _v in self.cliente.manifiesto().get("archivos", [])}
        if despues.get(diario_rel) is not None or any(despues.get(r) != contenido[r] for r in aplicar_rutas):
            raise EstadoNoVerificado("la recuperación no quedó confirmada en Cloud")
        return {**resultado, "estado": "RECUPERADO", "version_final": self.version}

    def _escribir_desde_nube(self, rel: str, datos: bytes | None) -> None:
        destino = self._abs(rel)
        if datos is None:
            destino.unlink(missing_ok=True)
            return
        destino.parent.mkdir(parents=True, exist_ok=True)
        temporal = destino.with_name(f".{destino.name}.recuperar.{os.getpid()}.tmp")
        temporal.write_bytes(datos)
        os.replace(temporal, destino)

    def _confirmar_rutas(self, lease, rutas, *, extra: list[list] | None = None,
                         conocidos: dict | None = None) -> list[list]:
        rutas = [r for r in rutas if rastreable(r)]
        locales = self._huellas_locales(rutas)
        # P0.3: lo que este turno escribió (huella custodiada al escribir) es
        # lo que se confirma, aunque la raíz muestre otra cosa: un contenido
        # que apareció después (escritor anterior vía Drive) nunca se adopta.
        conocidos = {r: s for r, s in (conocidos or {}).items() if r in locales}
        ajenos = sorted(r for r, s in conocidos.items() if locales[r] != s)
        if ajenos:
            log.warning("Estado confirmado: %d ruta(s) con contenido ajeno en la raíz; se confirma lo escrito por el turno: %s",
                        len(ajenos), ajenos[:5])
        self.ajenos_descartados = ajenos
        locales.update(conocidos)
        cambios = [[rel, sha] for rel, sha in sorted(locales.items()) if self.manifiesto.get(rel, "ausente") != sha]
        # Una ruta nueva que ya no existe (temporal efímero) no aporta estado.
        cambios = [c for c in cambios if c[1] is not None or c[0] in self.manifiesto]
        extra = [list(par) for par in (extra or []) if es_ruta_custodia(par[0])]
        if not cambios and not extra:
            return []
        # Un borrado observado por el hook es intención del turno; sólo los
        # inferidos de la raíz (unidad quizá desmontada) se recomprueban.
        borrados = [rel for rel, sha in cambios if sha is None and rel not in conocidos]
        if borrados:
            # Google Drive se reinicia solo y desmonta la unidad unos segundos:
            # sin raíz todo parece borrado. Un borrado se confirma sólo si la
            # raíz sigue montada y una segunda comprobación lo ratifica; si no,
            # el diario local queda para el próximo turno.
            self._exigir_raiz_disponible()
            if any(self._huellas_locales(borrados).values()):
                raise EstadoNoVerificado("un archivo dado por borrado sigue en la raíz; no se confirma")
            self._exigir_raiz_disponible()
        huellas = sorted({sha for _rel, sha in cambios if sha})
        for sha in self.cliente.faltantes(huellas) if huellas else []:
            rel = next(r for r, s in cambios if s == sha)
            try:
                datos = self._abs(rel).read_bytes()
            except OSError:
                datos = b""
            if hashlib.sha256(datos).hexdigest() != sha:
                raise EstadoNoVerificado(f"{rel} cambió durante la confirmación")
            self.cliente.subir(sha, datos, lease.lease_token)
        lotes = [cambios[i:i + LOTE_CONFIRMACION] for i in range(0, len(cambios), LOTE_CONFIRMACION)] or [[]]
        lotes[-1] = lotes[-1] + extra
        for lote in lotes:
            self.version = self.cliente.confirmar(lease.lease_token, self.version, lote)
            for rel, sha in lote:
                self.manifiesto[rel] = sha
            _escribir_json(self._ruta_manifiesto, {"version": self.version, "archivos": self.manifiesto})
            # P0.3.1: sólo después de que Cloud confirmó el lote.
            self._publicar(lote)
        return cambios

    def _exigir_raiz_disponible(self) -> None:
        try:
            disponible = self.raiz.is_dir()
        except OSError:
            disponible = False
        if not disponible:
            raise EstadoNoVerificado("raíz operacional no disponible; no se confirman borrados")

    # -------------------------------------------------------------- semilla
    def rutas_semilla(self) -> list[str]:
        rels = []
        for carpeta in SEMILLA_CARPETAS:
            base = self._abs(carpeta)
            if base.is_dir():
                rels += [self._rel(p) for p in base.rglob("*") if p.is_file()]
        envios = self._abs(SEMILLA_ENVIOS)
        if envios.is_dir():
            rels += [self._rel(p) for p in envios.glob("*/envio.json") if p.is_file()]
        return sorted(r for r in rels if r and rastreable(r))

    def sembrar(self, lease) -> dict:
        """Activación: publica la línea base desde el equipo con el estado vigente."""
        return {"version": None, "confirmados": len(self._confirmar_rutas(lease, self.rutas_semilla())), "version_final": self.version}


def preparar_raiz_trabajo(raiz_publicada, raiz_trabajo) -> dict:
    """P0.3.1: la raíz de trabajo es una copia local, fuera de Drive, de la
    raíz publicada; desde aquí el Motor de este equipo escribe sólo en ella y
    la publicada recibe únicamente lo que Cloud confirma. No escribe en la
    publicada. La primera alineación deja la copia igual a la marca Cloud."""
    publicada, trabajo = Path(os.path.abspath(raiz_publicada)), Path(os.path.abspath(raiz_trabajo))
    if _misma_ruta(publicada, trabajo) or os.path.normcase(str(trabajo)).startswith(os.path.normcase(str(publicada)) + os.sep) \
            or os.path.normcase(str(publicada)).startswith(os.path.normcase(str(trabajo)) + os.sep):
        raise EstadoNoVerificado("la raíz de trabajo y la publicada deben ser carpetas separadas")
    if not publicada.is_dir():
        raise EstadoNoVerificado(f"raíz publicada inexistente: {publicada}")
    copiada = False
    if not trabajo.exists() or not any(trabajo.iterdir()):
        shutil.copytree(publicada, trabajo, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns("*.tmp", ".atlas_lock_*", "desktop.ini", "~$*"))
        copiada = True
    _escribir_json(ruta_configuracion_publicacion(), {"raiz_trabajo": str(trabajo), "raiz_publicada": str(publicada)})
    return {"raiz_trabajo": str(trabajo), "raiz_publicada": str(publicada), "copiada": copiada,
            "configuracion": str(ruta_configuracion_publicacion())}


def verificar_sin_escribir(raiz, cliente: ClienteEstado, *, carpeta_local: Path | None = None) -> dict:
    """Sólo lectura: cuántos archivos locales difieren de la marca vigente."""
    custodia = CustodiaEstado(raiz, cliente, carpeta_local=carpeta_local)
    datos = cliente.manifiesto()
    completo = {ruta: sha for ruta, sha, _v in datos.get("archivos", [])}
    manifiesto = operacionales(completo)
    locales = custodia._huellas_locales(manifiesto)
    distintos = sorted(rel for rel, sha in locales.items() if sha != manifiesto[rel])
    return {"version": datos.get("version"), "protocolo_minimo": datos.get("protocolo_minimo"),
            "archivos": len(manifiesto), "distintos": len(distintos), "ejemplos": distintos[:10],
            "diarios_abiertos": sorted(r for r, s in completo.items() if s and r.startswith(CARPETA_DIARIOS + "/"))}


def leer_diarios_remotos(cliente: ClienteEstado, *, empresa_id: str | None = None) -> dict:
    """Sólo lectura, desde cualquier equipo de la empresa: los diarios de
    recuperación abiertos en Cloud, descargados y verificados por huella.

    ``vigente`` indica que nadie confirmó después de la última actualización
    del diario: las escrituras de ese turno serían el estado más nuevo."""
    datos = cliente.manifiesto()
    version = int(datos.get("version", -1))
    diarios = []
    for rel, sha, version_publicacion in datos.get("archivos", []):
        if not sha or not rel.startswith(CARPETA_DIARIOS + "/"):
            continue
        diario = interpretar_diario(rel, cliente.descargar(sha), sha)
        if empresa_id is not None and diario["empresa_id"] != empresa_id:
            raise EstadoNoVerificado(f"diario {rel} pertenece a otra empresa: {diario['empresa_id']}")
        diarios.append({"ruta": rel, "sha256": sha, "version_publicacion": int(version_publicacion),
                        "vigente": int(version_publicacion) == version, "diario": diario})
    return {"version": version, "diarios": diarios}


def main(argv=None) -> int:
    import argparse
    from atlas_core.escritor_operativo import lease_desde_entorno
    parser = argparse.ArgumentParser(description="Estado operacional confirmado en Cloud (protocolo 2).")
    parser.add_argument("--raiz-atlas", required=True)
    accion = parser.add_mutually_exclusive_group(required=True)
    accion.add_argument("--sembrar", action="store_true", help="Activación: publica la línea base bajo lease (sólo el equipo con el estado vigente)")
    accion.add_argument("--verificar", action="store_true", help="Sólo lectura: compara la copia local con la marca vigente")
    accion.add_argument("--diarios", action="store_true", help="Sólo lectura: diarios de recuperación abiertos en Cloud, verificados")
    accion.add_argument("--recuperar-turno", metavar="DIARIO",
                        help="Bajo lease: recupera el turno caído de otro escritor desde Cloud (vista previa salvo --aplicar)")
    parser.add_argument("--aplicar", action="store_true", help="Con --recuperar-turno: aplica y confirma la recuperación")
    accion.add_argument("--preparar-raiz-trabajo", metavar="RAIZ_PUBLICADA",
                        help="P0.3.1, sin lease: crea --raiz-atlas como raíz de trabajo local desde la raíz publicada (Drive)")
    args = parser.parse_args(argv)
    if args.aplicar and not args.recuperar_turno:
        parser.error("--aplicar sólo acompaña a --recuperar-turno")
    if args.preparar_raiz_trabajo:
        print(json.dumps(preparar_raiz_trabajo(args.preparar_raiz_trabajo, args.raiz_atlas), ensure_ascii=False))
        return 0
    lease = lease_desde_entorno(raiz=args.raiz_atlas)
    if lease is None:
        parser.error("Falta ATLAS_CLOUD_MOTOR_TOKEN")
    if args.verificar:
        print(json.dumps(verificar_sin_escribir(args.raiz_atlas, lease.custodia.cliente), ensure_ascii=False))
        return 0
    if args.diarios:
        from atlas_core.aislamiento_empresas import empresa_de_raiz
        cliente = lease.custodia.cliente
        print(json.dumps(leer_diarios_remotos(cliente, empresa_id=empresa_de_raiz(args.raiz_atlas)), ensure_ascii=False))
        return 0
    if args.recuperar_turno:
        with lease:
            if not lease.adquirir():
                print(json.dumps({"estado": "SIN_LEASE", "motivo": lease.motivo or "ESCRITOR_OCUPADO"}))
                return 1
            resultado = lease.custodia.recuperar_turno(lease, args.recuperar_turno, aplicar=args.aplicar)
        print(json.dumps(resultado, ensure_ascii=False))
        return 0 if resultado["estado"] in {"RECUPERABLE", "RECUPERADO", "YA_CERRADO"} else 3
    with lease:
        if not lease.adquirir():
            print(json.dumps({"sembrado": False, "motivo": lease.motivo or "ESCRITOR_OCUPADO"}))
            return 1
        resultado = lease.custodia.sembrar(lease)
    print(json.dumps({"sembrado": True, **resultado}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    # Ejecutado con -m: delegar al módulo importado, el mismo que usa el lease
    # (un segundo audit hook y una segunda lista de custodias no registran nada).
    from atlas_core.estado_confirmado import main as _main
    raise SystemExit(_main())
