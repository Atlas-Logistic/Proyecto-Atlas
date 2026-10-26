"""Recuperación independiente del material leído por OCR (26/10/2026).

Caso real: guías con la partida leída como ``BHORMIGON``/``HORMIGON16MM``
quedaron sin material (483106, 483138, 482816, 482771, 482908) o con un
ítem de menos (482247, 482909). ``TRANSPORTE_REVALIDAR`` reextrae TODO el
documento y su reconciliación recalcula ruta/destino/motivos propios del
viaje; aquí sólo se relee el material.

Reutiliza las MISMAS piezas que ``procesar_archivo`` para el material --
``extraer_descripcion_material``, ``clasificar_material``,
``analizar_items_material`` y los tres motivos de material -- sobre la
evidencia original (con la misma decisión de orientación, sin persistir
copias). Sólo escribe ``descripcion_material``, ``tipo_carga``,
``material_items`` (dentro de ``metricas_procesamiento_json``) y los
motivos de material de ``motivos_revision_documento``; nunca rutas,
destinos, identidad, estados, ledger ni bandeja.

Nunca pisa un material correcto: sólo recupera uno ausente, mejora uno
degradado/genérico de la misma familia o completa uno al que le faltaban
ítems (todos los actuales deben seguir presentes). Cualquier decisión del
ledger sobre material o tipo de carga del documento lo deja intacto.
"""
from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from atlas_core.almacenamiento_portable import bloqueo_sesion
from atlas_core.clasificador_material import clasificar_material
from atlas_core.credibilidad_campos import NivelCredibilidad, evaluar_credibilidad_material
from atlas_core.ingesta_pdf import ProveedorPaginaPdf
from atlas_core.material_codigo_sap import analizar_items_material
from atlas_core.orientacion_documental import normalizar_orientacion
from atlas_core.procesamiento_masivo import MotivoRevisionDocumento, extraer_descripcion_material
from atlas_core.revalidacion_documental import _escribir_filas_completas, _leer_filas

SEPARADOR = " | "
MOTIVOS_MATERIAL = (
    MotivoRevisionDocumento.MATERIAL_AUSENTE.value,
    MotivoRevisionDocumento.MATERIAL_POSIBLEMENTE_CONTAMINADO.value,
    MotivoRevisionDocumento.MATERIAL_OCR_NO_CONFIABLE.value,
)
CAMPOS_LEDGER_MATERIAL = frozenset({"descripcion_material", "tipo_carga"})
# Mismo lock de escritura del dataset que la revalidación por transporte.
NOMBRE_LOCK_DATASET = "revalidacion_dataset"
_MARCA_ILEGIBLE = "DETALLE ILEGIBLE"

PROTEGIDO_POR_DECISION = "PROTEGIDO_POR_DECISION"
SIN_EVIDENCIA = "SIN_EVIDENCIA_CONFIABLE"
SE_CONSERVA = "SE_CONSERVA_MATERIAL_ACTUAL"
SIN_CAMBIOS = "SIN_CAMBIOS"
RECUPERAR = "RECUPERAR"          # material ausente
MEJORAR = "MEJORAR"              # material degradado o sólo familia
COMPLETAR = "COMPLETAR"          # faltaban ítems; los actuales se conservan
SINCRONIZAR = "SINCRONIZAR"      # mismo material; tipo/ítems/motivos desalineados
VEREDICTOS_CON_ESCRITURA = frozenset({RECUPERAR, MEJORAR, COMPLETAR, SINCRONIZAR})


class ErrorRecuperacionMaterial(RuntimeError):
    pass


@dataclass(frozen=True)
class LecturaMaterial:
    descripcion: str
    tipo_carga: str
    items: tuple[dict, ...]
    motivos: tuple[str, ...]


def material_desde_lineas(textos: list[str], bloques: list | None = None) -> LecturaMaterial:
    """Material, tipo, ítems y motivos con las reglas de `procesar_archivo`."""
    descripcion = extraer_descripcion_material(textos)
    items = analizar_items_material(descripcion, textos=textos, bloques=bloques)
    motivos = []
    if not descripcion:
        motivos.append(MotivoRevisionDocumento.MATERIAL_AUSENTE.value)
    if evaluar_credibilidad_material(descripcion).nivel != NivelCredibilidad.CONFIABLE:
        motivos.append(MotivoRevisionDocumento.MATERIAL_POSIBLEMENTE_CONTAMINADO.value)
    if any(item.no_confiable for item in items):
        motivos.append(MotivoRevisionDocumento.MATERIAL_OCR_NO_CONFIABLE.value)
    return LecturaMaterial(descripcion, clasificar_material(descripcion).value,
                           tuple(item.como_dict() for item in items), tuple(motivos))


def leer_material(ruta: str | Path, *, proveedor) -> LecturaMaterial:
    """Relee SÓLO el material de la evidencia original. La orientación se
    decide igual que en la ingesta pero sin persistir la copia girada."""
    orientacion = None
    if not isinstance(proveedor, ProveedorPaginaPdf):
        orientacion = normalizar_orientacion(Path(ruta), proveedor.leer_bloques, directorio_persistencia=None)
    try:
        ruta_ocr = orientacion.ruta_ocr if orientacion is not None else Path(ruta)
        textos = proveedor.leer_texto(ruta_ocr)
        bloques = orientacion.bloques if orientacion is not None and orientacion.bloques is not None \
            else proveedor.leer_bloques(ruta_ocr)
        return material_desde_lineas(textos, bloques)
    finally:
        if orientacion is not None:
            orientacion.limpiar()


def _clave(texto: str) -> str:
    plano = unicodedata.normalize("NFKC", str(texto or "")).upper()
    return re.sub(r"\s+", "", plano)


def _items(texto: str) -> list[str]:
    return [p.strip() for p in str(texto or "").split("|") if p.strip()]


def _ausente(texto: str) -> bool:
    return str(texto or "").strip().upper() in ("", "NO ENCONTRADO", "NO DETERMINADO")


def _degradado(texto: str) -> bool:
    """Material presente pero sin detalle utilizable: sólo la familia, el
    marcador de ilegible o una lectura que la credibilidad no publica."""
    return (_MARCA_ILEGIBLE in texto.upper() or not re.search(r"\d", texto)
            or evaluar_credibilidad_material(texto).nivel != NivelCredibilidad.CONFIABLE)


def _misma_familia(actual: str, nuevo: str) -> bool:
    palabras = {p for p in re.findall(r"[A-ZÑ]{4,}", unicodedata.normalize("NFKC", actual).upper())
                if p not in {"DETALLE", "ILEGIBLE"}}
    nuevo = unicodedata.normalize("NFKC", nuevo).upper()
    return bool(palabras) and all(p in nuevo for p in palabras)


def protegido_por_decision(fila: Mapping[str, str], aplicaciones: list[Mapping[str, object]]) -> bool:
    """Cualquier aplicación del ledger sobre material o tipo de carga del
    mismo documento (por archivo, o por guía en ledgers antiguos) gana."""
    archivo, guia = str(fila.get("archivo", "")).strip(), str(fila.get("numero_guia", "")).strip()
    for aplicacion in aplicaciones:
        documento = aplicacion.get("documento") if isinstance(aplicacion, Mapping) else None
        if not isinstance(documento, Mapping) or str(aplicacion.get("campo", "")).strip() not in CAMPOS_LEDGER_MATERIAL:
            continue
        if (archivo and str(documento.get("archivo", "")).strip() == archivo) or (
                guia and str(documento.get("numero_guia", "")).strip() == guia):
            return True
    return False


def motivos_actualizados(actual: str, lectura: LecturaMaterial) -> str:
    """Sólo cambian los motivos de material; el resto conserva su orden."""
    previos = [m.strip() for m in str(actual or "").split("|") if m.strip()]
    resultado = [m for m in previos if m not in MOTIVOS_MATERIAL] + list(lectura.motivos)
    return actual if set(resultado) == set(previos) else SEPARADOR.join(resultado)


def metricas_actualizadas(actual: str, lectura: LecturaMaterial) -> str:
    try:
        metricas = json.loads(actual or "{}")
    except ValueError as error:
        raise ErrorRecuperacionMaterial("metricas_procesamiento_json ilegible") from error
    if not isinstance(metricas, dict):
        raise ErrorRecuperacionMaterial("metricas_procesamiento_json no es un objeto")
    if metricas.get("material_items", []) == list(lectura.items):
        return actual
    if lectura.items:
        metricas["material_items"] = list(lectura.items)
    else:
        metricas.pop("material_items", None)
    return json.dumps(metricas, ensure_ascii=False, sort_keys=True)


def evaluar_recuperacion(
    fila: Mapping[str, str], lectura: LecturaMaterial, aplicaciones: list[Mapping[str, object]],
) -> tuple[str, dict[str, str]]:
    """(veredicto, valores nuevos de la fila). Sin valores si no se escribe."""
    if protegido_por_decision(fila, aplicaciones):
        return PROTEGIDO_POR_DECISION, {}
    nuevo = lectura.descripcion
    if not nuevo or evaluar_credibilidad_material(nuevo).nivel != NivelCredibilidad.CONFIABLE:
        return SIN_EVIDENCIA, {}
    actual = str(fila.get("descripcion_material", "") or "").strip()
    claves_actuales = [_clave(i) for i in _items(actual)]
    claves_nuevas = [_clave(i) for i in _items(nuevo)]
    if _ausente(actual):
        veredicto = RECUPERAR
    elif claves_actuales == claves_nuevas:
        veredicto = SINCRONIZAR
    elif set(claves_actuales) < set(claves_nuevas):
        veredicto = COMPLETAR
    elif _degradado(actual) and _misma_familia(actual, nuevo):
        veredicto = MEJORAR
    else:
        return SE_CONSERVA, {}
    descripcion = actual if veredicto == SINCRONIZAR else nuevo
    lectura_final = lectura if veredicto != SINCRONIZAR else material_coherente(lectura, descripcion)
    valores = {
        "descripcion_material": descripcion,
        "tipo_carga": lectura_final.tipo_carga,
        "metricas_procesamiento_json": metricas_actualizadas(fila.get("metricas_procesamiento_json", ""), lectura_final),
        "motivos_revision_documento": motivos_actualizados(fila.get("motivos_revision_documento", ""), lectura_final),
    }
    cambios = {c: v for c, v in valores.items() if str(fila.get(c, "")) != v}
    return (veredicto, cambios) if cambios else (SIN_CAMBIOS, {})


def material_coherente(lectura: LecturaMaterial, descripcion: str) -> LecturaMaterial:
    """Mismo material con otra grafía: el texto publicado se conserva y el
    tipo se clasifica sobre él; ítems y motivos son los de la lectura."""
    return LecturaMaterial(descripcion, clasificar_material(descripcion).value, lectura.items, lectura.motivos)


def aplicar_en_dataset(
    dataset: Path, *, archivo: str, fila_base: Mapping[str, str], valores: Mapping[str, str],
) -> dict[str, tuple[str, str]]:
    """Escribe SÓLO `valores` en la fila `archivo`, bajo el lock del dataset,
    si la fila sigue exactamente como en el preview; si no, no escribe."""
    no_permitidos = set(valores) - {"descripcion_material", "tipo_carga", "metricas_procesamiento_json",
                                    "motivos_revision_documento"}
    if no_permitidos:
        raise ErrorRecuperacionMaterial(f"campos no autorizados: {sorted(no_permitidos)}")
    with bloqueo_sesion(dataset.parent, NOMBRE_LOCK_DATASET):
        filas = _leer_filas(dataset)
        objetivo = [f for f in filas if str(f.get("archivo", "")) == archivo]
        if len(objetivo) != 1:
            raise ErrorRecuperacionMaterial(f"el documento {archivo} no es único en el dataset ({len(objetivo)})")
        if dict(objetivo[0]) != dict(fila_base):
            raise ErrorRecuperacionMaterial("la fila cambió desde el preview; no se escribe")
        cambios = {c: (str(objetivo[0].get(c, "")), v) for c, v in valores.items()}
        objetivo[0].update(valores)
        _escribir_filas_completas(dataset, filas)
    return cambios
