"""Publicación del reporte vigente sin un snapshot permanente por cada cambio.

Cada ingreso Mobile, revalidación, acción operacional, mantenimiento o
reconciliación publicaba un ``reportes/<carpeta>/viajes.csv`` completo
(~7,4 MB) que nunca se borraba: 30-40 por día. Sólo el último es necesario
para operar (Desktop, MBT, consultas y Mobile lo leen vía
``estado_operacion.reporte_vigente``). Los anteriores eran, además, la única
fuente del lector histórico de relaciones.

Modos (``reportes/vigentes/publicacion.json``; ausente = ``snapshots``):

* ``snapshots``: exactamente el comportamiento anterior.
* ``rotativo``: los productores automáticos publican en
  ``reportes/vigentes/<misma carpeta>/`` (dentro de ``reportes/``, que la
  custodia Cloud excluye; el lector histórico sólo recorre un nivel y no lo
  ve). Tras publicar, la evidencia de ese ``viajes.csv`` se captura en el
  registro de relaciones, y el consumidor la suma a la de los reportes
  históricos: el lector no pierde nada aunque ya no haya snapshot. Se
  conservan las ``conservar`` publicaciones más recientes y la vigente; las
  demás se podan sólo si su evidencia quedó capturada o preservada. Si la
  captura falla, el reporte se copia como snapshot permanente.

El modo rotativo exige un registro legible; si deja de serlo, los
productores vuelven solos a ``snapshots``. Un snapshot permanente se puede
pedir explícitamente (``snapshot_explicito``) y ``generar_reporte_viajes.py``
sigue escribiendo exactamente donde se le indique. Nunca se tocan los
reportes históricos ya existentes.
"""
from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path

from atlas_core.almacenamiento_portable import escribir_json_atomico, leer_estado_operacion

CARPETA_VIGENTES = "vigentes"
ARCHIVO_CONFIGURACION = "publicacion.json"
MARCADOR = "publicacion_rotativa.json"
MODO_SNAPSHOTS = "snapshots"
MODO_ROTATIVO = "rotativo"
CONSERVAR_DEFECTO = 3
CONSERVAR_MINIMO = 2

log = logging.getLogger(__name__)


def raiz_vigentes(raiz: str | Path) -> Path:
    return Path(raiz) / "reportes" / CARPETA_VIGENTES


def ruta_configuracion(raiz: str | Path) -> Path:
    return raiz_vigentes(raiz) / ARCHIVO_CONFIGURACION


def leer_configuracion(raiz: str | Path) -> dict[str, object]:
    """Ausente o inválida = ``snapshots`` (comportamiento anterior)."""
    defecto: dict[str, object] = {"modo": MODO_SNAPSHOTS, "conservar": CONSERVAR_DEFECTO}
    try:
        valor = json.loads(ruta_configuracion(raiz).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return defecto
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {**defecto, "error": "CONFIGURACION_ILEGIBLE"}
    if not isinstance(valor, dict) or valor.get("modo") not in (MODO_SNAPSHOTS, MODO_ROTATIVO):
        return {**defecto, "error": "CONFIGURACION_INVALIDA"}
    conservar = valor.get("conservar", CONSERVAR_DEFECTO)
    if not isinstance(conservar, int) or isinstance(conservar, bool) or conservar < CONSERVAR_MINIMO:
        return {**defecto, "error": "CONFIGURACION_INVALIDA"}
    return {"modo": valor["modo"], "conservar": conservar}


def _registro_legible(raiz: str | Path) -> bool:
    from atlas_core.registro_relaciones_operacionales import estado_registro
    return bool(estado_registro(raiz).get("legible"))


def modo_efectivo(raiz: str | Path) -> str:
    """Rotativo sólo si está configurado Y el registro puede capturar evidencia."""
    if leer_configuracion(raiz)["modo"] != MODO_ROTATIVO:
        return MODO_SNAPSHOTS
    return MODO_ROTATIVO if _registro_legible(raiz) else MODO_SNAPSHOTS


def ruta_reporte_automatico(raiz: str | Path, nombre_carpeta: str) -> Path:
    """Carpeta de salida para un productor automático del reporte vigente."""
    base = Path(raiz) / "reportes"
    if nombre_carpeta == CARPETA_VIGENTES:
        raise ValueError(f"nombre de carpeta reservado: {nombre_carpeta}")
    if modo_efectivo(raiz) == MODO_ROTATIVO:
        return base / CARPETA_VIGENTES / nombre_carpeta
    return base / nombre_carpeta


def _es_rotativo(raiz: Path, reporte: Path) -> bool:
    try:
        return reporte.resolve().parent == raiz_vigentes(raiz).resolve()
    except OSError:
        return False


def _leer_marcador(carpeta: Path) -> dict[str, object]:
    try:
        valor = json.loads((carpeta / MARCADOR).read_text(encoding="utf-8"))
        return valor if isinstance(valor, dict) else {}
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}


def _ahora() -> str:
    return datetime.now(timezone.utc).isoformat()


def _preservar_como_snapshot(raiz: Path, reporte: Path) -> str | None:
    destino = raiz / "reportes" / reporte.name
    if not destino.exists():
        shutil.copytree(reporte, destino, ignore=shutil.ignore_patterns(MARCADOR))
    return destino.relative_to(raiz).as_posix() if (destino / "viajes.csv").is_file() else None


def tras_publicar_reporte_vigente(raiz: str | Path, reporte: str | Path) -> dict[str, object]:
    """Gancho de ``escribir_estado_operacion``: no hace nada fuera de
    ``reportes/vigentes``. Captura una vez la evidencia del reporte y poda."""
    raiz, reporte = Path(raiz), Path(reporte)
    if not _es_rotativo(raiz, reporte) or not (reporte / "viajes.csv").is_file():
        return {"aplica": False}
    marcador = _leer_marcador(reporte)
    if not (marcador.get("capturado") or marcador.get("preservado_en")):
        from atlas_core.registro_relaciones_operacionales import RegistroRelacionesError, capturar_reporte_publicado
        marcador = {"publicado_en": marcador.get("publicado_en") or _ahora()}
        try:
            marcador.update({"capturado": True, **capturar_reporte_publicado(raiz, reporte / "viajes.csv")})
        except (RegistroRelacionesError, OSError, ValueError) as error:
            # Sin captura, la evidencia queda donde el lector histórico la lee.
            marcador.update({"capturado": False, "motivo": getattr(error, "codigo", type(error).__name__)})
            try:
                marcador["preservado_en"] = _preservar_como_snapshot(raiz, reporte)
            except OSError as error_copia:
                marcador["error_preservacion"] = str(error_copia)
        escribir_json_atomico(reporte / MARCADOR, marcador)
    return {"aplica": True, **marcador, "poda": podar_vigentes(raiz)}


def podar_vigentes(raiz: str | Path, *, conservar: int | None = None) -> dict[str, object]:
    """Borra publicaciones rotativas antiguas, nunca la vigente, nunca una sin
    evidencia capturada/preservada, nunca nada fuera de ``reportes/vigentes``."""
    raiz = Path(raiz)
    conservar = max(int(conservar or leer_configuracion(raiz)["conservar"]), CONSERVAR_MINIMO)
    directorio = raiz_vigentes(raiz)
    estado = leer_estado_operacion(raiz=raiz) or {}
    vigente = str(estado.get("reporte_vigente") or "")
    actual = (raiz / vigente).resolve() if vigente else None
    publicadas = []
    for carpeta in directorio.iterdir() if directorio.is_dir() else []:
        marcador = _leer_marcador(carpeta) if carpeta.is_dir() else {}
        if marcador:
            publicadas.append((str(marcador.get("publicado_en", "")), carpeta.name, carpeta, marcador))
    publicadas.sort(reverse=True)
    conservadas, borradas, retenidas = [], [], []
    for indice, (_fecha, nombre, carpeta, marcador) in enumerate(publicadas):
        if indice < conservar or carpeta.resolve() == actual:
            conservadas.append(nombre)
        elif not (marcador.get("capturado") or marcador.get("preservado_en")):
            retenidas.append(nombre)  # su evidencia sólo existe aquí: nunca se borra
        else:
            try:
                shutil.rmtree(carpeta)
                borradas.append(nombre)
            except OSError:  # p. ej. un lector la tiene abierta: se reintenta en la próxima publicación
                retenidas.append(nombre)
    return {"conservadas": conservadas, "borradas": borradas, "retenidas": retenidas}


def configurar(raiz: str | Path, *, modo: str, conservar: int = CONSERVAR_DEFECTO) -> dict[str, object]:
    """Cambia el modo (reversible). Rotativo exige un registro legible."""
    if modo not in (MODO_SNAPSHOTS, MODO_ROTATIVO):
        raise ValueError(f"modo desconocido: {modo}")
    if not isinstance(conservar, int) or conservar < CONSERVAR_MINIMO:
        raise ValueError(f"conservar debe ser >= {CONSERVAR_MINIMO}")
    if modo == MODO_ROTATIVO and not _registro_legible(raiz):
        raise ValueError("REGISTRO_ILEGIBLE: el modo rotativo necesita capturar evidencia en el registro")
    escribir_json_atomico(ruta_configuracion(raiz), {
        "version": 1, "modo": modo, "conservar": conservar, "actualizado_en": _ahora(),
    })
    return estado_publicacion(raiz)


def snapshot_explicito(raiz: str | Path, *, reloj=lambda: datetime.now(timezone.utc)) -> Path:
    """Copia permanente del reporte vigente, sólo cuando se pide."""
    raiz = Path(raiz)
    estado = leer_estado_operacion(raiz=raiz) or {}
    vigente = raiz / str(estado.get("reporte_vigente") or "")
    if not estado.get("reporte_vigente") or not (vigente / "viajes.csv").is_file():
        raise FileNotFoundError("no hay un reporte vigente publicado")
    destino = raiz / "reportes" / f"snapshot_{reloj().strftime('%Y%m%d_%H%M%S_%f')}"
    shutil.copytree(vigente, destino, ignore=shutil.ignore_patterns(MARCADOR))
    return destino


def estado_publicacion(raiz: str | Path) -> dict[str, object]:
    configuracion = leer_configuracion(raiz)
    directorio = raiz_vigentes(raiz)
    rotativas = [c.name for c in directorio.iterdir() if c.is_dir()] if directorio.is_dir() else []
    return {
        **configuracion, "modo_efectivo": modo_efectivo(raiz), "registro_legible": _registro_legible(raiz),
        "publicaciones_rotativas": len(rotativas),
    }
