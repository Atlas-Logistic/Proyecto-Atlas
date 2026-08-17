"""R3.4: revalidación de resultados documentales YA procesados contra el
estado VIGENTE de los catálogos, sin ejecutar OCR ni volver a extraer ningún
campo.

Hoy resuelve exactamente un caso concreto y general: una fila cuyo motivo
``OBRA_DESTINO_SIN_CORROBORAR`` quedó obsoleto porque, después de generado
el dataset, la relación obra↔destino global fue confirmada (por la misma
guía o por cualquier otra -- ver R3.3.1/R3.4.1). El resto de la fila
-- todo dato documental -- permanece byte por byte igual.
"""
from __future__ import annotations

import csv
import os
import tempfile
from pathlib import Path

from atlas_core.almacenamiento_portable import bloqueo_sesion
from atlas_core.catalogo_obras_destinos import CatalogoObrasDestinos
from atlas_core.procesamiento_masivo import (
    COLUMNAS,
    MOTIVOS_NO_BLOQUEANTES,
    MotivoRevisionDocumento,
)
from atlas_core.reporte_viajes import generar_reporte_viajes

SEPARADOR_MOTIVOS = " | "
_AUSENTES = {"", "No encontrado"}


def _leer_filas(ruta_csv: Path) -> list[dict[str, str]]:
    with ruta_csv.open("r", newline="", encoding="utf-8-sig") as archivo:
        lector = csv.DictReader(archivo, delimiter=";")
        if lector.fieldnames != COLUMNAS:
            raise ValueError(
                "El dataset tiene un esquema incompatible; se esperaba el encabezado oficial."
            )
        return list(lector)


def _escribir_filas_completas(ruta_csv: Path, filas: list[dict[str, str]]) -> None:
    temporal: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", newline="", encoding="utf-8-sig", dir=ruta_csv.parent,
            prefix=f".{ruta_csv.name}.", suffix=".tmp", delete=False,
        ) as archivo:
            temporal = Path(archivo.name)
            escritor = csv.DictWriter(archivo, fieldnames=COLUMNAS, delimiter=";", extrasaction="ignore")
            escritor.writeheader()
            escritor.writerows(filas)
            archivo.flush()
            os.fsync(archivo.fileno())
        os.replace(temporal, ruta_csv)
    except OSError:
        if temporal is not None:
            temporal.unlink(missing_ok=True)
        raise


def revalidar_obra_destino_sin_ocr(
    *, ruta_dataset: str | Path, carpeta_catalogos: str | Path,
) -> dict[str, object]:
    """Relee cada fila del dataset y reevalúa ÚNICAMENTE el motivo
    ``OBRA_DESTINO_SIN_CORROBORAR`` contra `resolver_obra_destino_confirmada_global`
    (sin cliente_id -- ver R3.4/R3.3.1). Si ahora resuelve, retira el motivo
    de esa fila y recalcula `indicador_revision`; nunca toca ningún otro
    campo. No ejecuta OCR ni vuelve a extraer nada -- sólo lee el dataset ya
    persistido y los catálogos vigentes. Se abstiene fila por fila ante
    cualquier duda (obra ausente/"No encontrado", error de catálogo, etc.)."""
    ruta = Path(ruta_dataset)
    carpeta = Path(carpeta_catalogos)
    catalogo_obras = CatalogoObrasDestinos(
        ruta=carpeta / "obras_destinos.json",
        ruta_clientes=carpeta / "clientes.json",
        ruta_destinos=carpeta / "destinos_maestros.json",
    )
    motivo_objetivo = MotivoRevisionDocumento.OBRA_DESTINO_SIN_CORROBORAR.value

    with bloqueo_sesion(ruta.parent, "revalidacion_dataset"):
        filas = _leer_filas(ruta)
        guias_actualizadas: list[str] = []
        for fila in filas:
            motivos = [m for m in fila.get("motivos_revision_documento", "").split(SEPARADOR_MOTIVOS) if m]
            if motivo_objetivo not in motivos:
                continue
            obra_documental = str(fila.get("obra_destino", "")).strip()
            if obra_documental in _AUSENTES:
                continue
            try:
                resuelto = catalogo_obras.resolver_obra_destino_confirmada_global(
                    nombre_obra=obra_documental
                )
            except (OSError, ValueError):
                continue
            if resuelto is None:
                continue
            motivos = [m for m in motivos if m != motivo_objetivo]
            fila["motivos_revision_documento"] = SEPARADOR_MOTIVOS.join(motivos)
            fila["indicador_revision"] = (
                "REVISAR" if any(m not in MOTIVOS_NO_BLOQUEANTES for m in motivos) else "OK"
            )
            guias_actualizadas.append(str(fila.get("numero_guia", "")))
        if guias_actualizadas:
            _escribir_filas_completas(ruta, filas)

    return {"filas_totales": len(filas), "guias_actualizadas": guias_actualizadas}


def revalidar_y_regenerar_reporte(
    *, raiz_atlas: str | Path, nombre_carpeta_reporte: str, reloj=None,
) -> dict[str, object]:
    """Orquesta la revalidación del dataset y, sólo si algo cambió,
    regenera el reporte oficial (`generar_reporte_viajes`) para que
    `reportes/actual`/Desktop dejen de mostrar un motivo ya resuelto -- sin
    OCR, usando exclusivamente el dataset ya persistido y los catálogos
    vigentes. Publica el nuevo `reporte_vigente` en `estado_operacion.json`
    mediante la misma infraestructura oficial que usa el CLI de reportes."""
    raiz = Path(raiz_atlas)
    actual = raiz / "operacion" / "actual"
    catalogos = raiz / "catalogos_privados"
    dataset = actual / "analisis_completo_guias.csv"

    resultado_revalidacion = revalidar_obra_destino_sin_ocr(
        ruta_dataset=dataset, carpeta_catalogos=catalogos,
    )
    if not resultado_revalidacion["guias_actualizadas"]:
        return {**resultado_revalidacion, "reporte_regenerado": False}

    from atlas_core.almacenamiento_portable import escribir_estado_operacion
    from atlas_core.decisiones_pendientes import NOMBRE_ARTEFACTO

    salida = raiz / "reportes" / nombre_carpeta_reporte
    kwargs = {"carpeta_catalogos": catalogos}
    if reloj is not None:
        kwargs["reloj"] = reloj
    manifest = generar_reporte_viajes(dataset, salida, **kwargs)
    ruta_decisiones = actual / NOMBRE_ARTEFACTO
    escribir_estado_operacion(
        reporte_vigente=salida,
        dataset_operacional=dataset,
        decisiones_pendientes=(ruta_decisiones if ruta_decisiones.is_file() else None),
        raiz=raiz,
    )
    return {**resultado_revalidacion, "reporte_regenerado": True, "reporte_vigente": str(salida)}
