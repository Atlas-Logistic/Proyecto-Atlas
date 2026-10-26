"""Recuperación del número de guía leído por OCR, sin revalidar el viaje (26/10/2026).

Casos reales 483169/483170/483211 (Mobile, RapidOCR): el encabezado se leyó
"GUIADEDESPACHO" y el número "N483169"; la guía quedó "No encontrado"
aunque el documento lo imprime. ``TRANSPORTE_REVALIDAR`` reextrae todo el
documento (obra, material, ruta, origen, motivos de patente...); aquí sólo
se relee el número de guía con el MISMO extractor de ``procesar_archivo``
(patrón lineal y, si falta, el geométrico), sobre la evidencia original con
la misma decisión de orientación y sin persistir copias.

Sólo escribe ``numero_guia``, retira ``GUIA_AUSENTE`` de los motivos y
recalcula ``indicador_revision``/``estado_documental``/``estado_operacional``
con las reglas de ``procesar_archivo`` sobre los motivos y la ruta YA
persistidos (nunca recalcula la ruta). Nunca reemplaza un número existente,
nunca toma un número de transporte y se abstiene si el número ya pertenece
a otro documento del dataset.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Mapping

from atlas_core.almacenamiento_portable import bloqueo_sesion
from atlas_core.extractor import _es_candidato_numero_guia_valido, _extraer_numero_guia_geometrico, extraer_datos
from atlas_core.ingesta_pdf import ProveedorPaginaPdf
from atlas_core.orientacion_documental import normalizar_orientacion
from atlas_core.procesamiento_masivo import MOTIVOS_NO_BLOQUEANTES, MotivoRevisionDocumento, _ruta_pendiente_de_resolucion
from atlas_core.revalidacion_documental import _escribir_filas_completas, _leer_filas

SEPARADOR = " | "
GUIAS_SIN_NUMERO = frozenset({"", "NO ENCONTRADO"})
CAMPOS_ESCRITOS = frozenset({"numero_guia", "motivos_revision_documento", "indicador_revision",
                             "estado_documental", "estado_operacional"})
NOMBRE_LOCK_DATASET = "revalidacion_dataset"

RECUPERAR = "RECUPERAR"
SIN_EVIDENCIA = "SIN_EVIDENCIA_DOCUMENTAL"
YA_TIENE_NUMERO = "YA_TIENE_NUMERO"
DUPLICADO = "NUMERO_DE_OTRO_DOCUMENTO"


class ErrorRecuperacionGuia(RuntimeError):
    pass


def numero_desde_lectura(textos: list[str], bloques: list | None) -> str:
    """Número de guía con las reglas de `procesar_archivo`: patrón lineal
    y, si no encuentra, el geométrico. '' si no hay uno válido."""
    lineal = str(extraer_datos(textos).get("número de guía", "") or "").strip()
    if lineal.upper() not in GUIAS_SIN_NUMERO and _es_candidato_numero_guia_valido(lineal):
        return lineal
    if bloques:
        geometrico = str(_extraer_numero_guia_geometrico(
            [b if hasattr(b, "texto") else SimpleNamespace(**b) for b in bloques]).get("valor") or "")
        if _es_candidato_numero_guia_valido(geometrico):
            return geometrico
    return ""


def leer_numero_guia(ruta: str | Path, *, proveedor) -> str:
    orientacion = None
    if not isinstance(proveedor, ProveedorPaginaPdf):
        orientacion = normalizar_orientacion(Path(ruta), proveedor.leer_bloques, directorio_persistencia=None)
    try:
        ruta_ocr = orientacion.ruta_ocr if orientacion is not None else Path(ruta)
        textos = proveedor.leer_texto(ruta_ocr)
        bloques = orientacion.bloques if orientacion is not None and orientacion.bloques is not None \
            else proveedor.leer_bloques(ruta_ocr)
        return numero_desde_lectura(textos, bloques)
    finally:
        if orientacion is not None:
            orientacion.limpiar()


def evaluar_recuperacion(
    fila: Mapping[str, str], numero: str, filas: list[Mapping[str, str]],
) -> tuple[str, dict[str, str]]:
    if str(fila.get("numero_guia", "")).strip().upper() not in GUIAS_SIN_NUMERO:
        return YA_TIENE_NUMERO, {}
    if not numero or numero == str(fila.get("numero_transporte", "")).strip():
        return SIN_EVIDENCIA, {}
    if any(str(f.get("numero_guia", "")).strip() == numero and f.get("archivo") != fila.get("archivo") for f in filas):
        return DUPLICADO, {}
    motivos = [m.strip() for m in str(fila.get("motivos_revision_documento", "")).split("|")
               if m.strip() and m.strip() != MotivoRevisionDocumento.GUIA_AUSENTE.value]
    requiere_revision = any(m not in MOTIVOS_NO_BLOQUEANTES for m in motivos)
    valores = {
        "numero_guia": numero,
        "motivos_revision_documento": SEPARADOR.join(motivos),
        "indicador_revision": "REVISAR" if requiere_revision else "OK",
        "estado_documental": "REQUIERE_REVISION" if requiere_revision else "OK",
        "estado_operacional": ("REQUIERE_REVISION" if requiere_revision
                               or _ruta_pendiente_de_resolucion(fila.get("estado_ruta", "")) else "OK"),
    }
    return RECUPERAR, {c: v for c, v in valores.items() if str(fila.get(c, "")) != v}


def aplicar_en_dataset(dataset: Path, *, archivo: str, fila_base: Mapping[str, str], valores: Mapping[str, str]) -> None:
    """Escribe SÓLO `valores` en la fila `archivo`, bajo el lock del dataset,
    si la fila sigue igual que en el preview y el número sigue libre."""
    if set(valores) - CAMPOS_ESCRITOS:
        raise ErrorRecuperacionGuia(f"campos no autorizados: {sorted(set(valores) - CAMPOS_ESCRITOS)}")
    with bloqueo_sesion(dataset.parent, NOMBRE_LOCK_DATASET):
        filas = _leer_filas(dataset)
        objetivo = [f for f in filas if str(f.get("archivo", "")) == archivo]
        if len(objetivo) != 1:
            raise ErrorRecuperacionGuia(f"el documento {archivo} no es único en el dataset ({len(objetivo)})")
        if dict(objetivo[0]) != dict(fila_base):
            raise ErrorRecuperacionGuia("la fila cambió desde el preview; no se escribe")
        numero = valores.get("numero_guia", "")
        if any(str(f.get("numero_guia", "")).strip() == numero for f in filas if f is not objetivo[0]):
            raise ErrorRecuperacionGuia(f"la guía {numero} ya pertenece a otro documento; no se escribe")
        objetivo[0].update(valores)
        _escribir_filas_completas(dataset, filas)
