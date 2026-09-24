"""CLI para procesar masivamente guías de despacho."""

import argparse
import csv
import json
import re
from datetime import date
from pathlib import Path

from atlas_core.procesamiento_masivo import procesar_carpeta
from atlas_core.fuente_catalogos import ErrorFuenteCatalogos, validar_fuente_catalogos
from atlas_core.telemetria.proveedores.onelogis import OnelogisProvider
from atlas_core.telemetria.repositorio import RepositorioTelemetria
from atlas_core.telemetria.servicio import ServicioTelemetria
from atlas_core.almacenamiento_portable import bloqueo_sesion
from atlas_core.decisiones_pendientes import (
    NOMBRE_ARTEFACTO,
    NOMBRE_LOCK_DECISIONES_PENDIENTES,
    _generar_artefacto_sin_lock,
    regenerar_decisiones_persistidas,
)


def fecha_iso(valor: str) -> date:
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", valor) is None:
        raise argparse.ArgumentTypeError(
            f"fecha inválida: {valor!r}; use el formato YYYY-MM-DD"
        )
    try:
        return date.fromisoformat(valor)
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            f"fecha inexistente o inválida: {valor!r}"
        ) from error


def crear_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Procesa recursivamente una carpeta de guías y genera un CSV."
    )
    parser.add_argument("carpeta", type=Path, help="Carpeta que contiene las guías")
    parser.add_argument(
        "--salida",
        type=Path,
        default=Path("output/analisis_guias.csv"),
        help="Ruta del CSV de salida",
    )
    parser.add_argument(
        "--reprocesar",
        action="store_true",
        help="Procesa incluso archivos ya presentes en el CSV",
    )
    parser.add_argument(
        "--fecha-desde",
        type=fecha_iso,
        help="Límite inferior inclusivo para fechas (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--fecha-hasta",
        type=fecha_iso,
        help="Límite superior inclusivo para fechas (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--catalogos",
        type=Path,
        help="Fuente privada validada (o use ATLAS_CATALOGOS_DIR)",
    )
    parser.add_argument(
        "--sin-catalogos",
        action="store_true",
        help="Declara explícitamente un procesamiento sin catálogos",
    )
    parser.add_argument(
        "--sin-telemetria",
        action="store_true",
        help=(
            "Desactiva la resolución de planta de origen por GPS/telemetría "
            "(Onelogis). Sin esta bandera, si hay catálogos disponibles se "
            "intenta siempre -- sin credencial configurada, cada consulta "
            "se abstiene sola (SIN_CREDENCIAL) y el procesamiento continúa "
            "igual que antes."
        ),
    )
    parser.add_argument(
        "--reconciliar-focal",
        action="store_true",
        help=(
            "Bloque P0 INGESTA FOCAL: al terminar, calcula el PlanImpacto de "
            "este lote (guías nuevas + cualquier guía que comparta número de "
            "transporte con ellas) y reconcilia SOLO ese alcance -- publica "
            "reportes/actual y estado_operacion.json (lo que Desktop lee) sin "
            "recorrer ni reintentar el backlog de rutas/identidad/segunda "
            "pasada ajeno a este lote. Sin esta bandera, comportamiento "
            "idéntico a siempre: sólo CSV + bandeja, ninguna reconciliación."
        ),
    )
    return parser


def main() -> None:
    parser = crear_parser()
    argumentos = parser.parse_args()
    if (
        argumentos.fecha_desde is not None
        and argumentos.fecha_hasta is not None
        and argumentos.fecha_desde > argumentos.fecha_hasta
    ):
        parser.error("--fecha-desde no puede ser posterior a --fecha-hasta")
    try:
        estado_catalogos = validar_fuente_catalogos(
            argumentos.catalogos,
            permitir_sin_catalogos=argumentos.sin_catalogos,
        )
    except ErrorFuenteCatalogos as error:
        parser.error(str(error))

    servicio_telemetria = None
    if estado_catalogos.ruta is not None and not argumentos.sin_telemetria:
        # La planta de origen real de un viaje se determina por GPS/geocercas
        # (Bloque OPERACIÓN REAL R1) -- la guía no trae la dirección de la
        # planta y no debe usarse para inferirla (ver `origen_documental.py`).
        # `OnelogisProvider()` lee la credencial desde la variable de entorno
        # `ATLAS_ONELOGIS_API_KEY` por sí mismo (nunca se imprime ni se
        # guarda aquí); si falta, cada consulta se abstiene con
        # SIN_CREDENCIAL y el procesamiento documental sigue igual que
        # siempre -- esta bandera nunca puede romper un procesamiento.
        servicio_telemetria = ServicioTelemetria(
            OnelogisProvider(),
            RepositorioTelemetria(Path(estado_catalogos.ruta) / "telemetria_cache.json"),
        )

    resumen = procesar_carpeta(
        argumentos.carpeta,
        argumentos.salida,
        reprocesar=argumentos.reprocesar,
        fecha_desde=argumentos.fecha_desde,
        fecha_hasta=argumentos.fecha_hasta,
        carpeta_catalogos=estado_catalogos.ruta,
        servicio_telemetria=servicio_telemetria,
    )
    if estado_catalogos.ruta is not None and Path(argumentos.salida).is_file():
        # Bloque BUG: PÉRDIDA DE DECISIÓN PENDIENTE AL AGREGAR OTRA GUÍA AL
        # MISMO VIAJE -- causa raíz real: este CLI publicaba la bandeja con
        # ÚNICAMENTE las decisiones detectadas en ESTE lote (`resumen
        # ["decisiones_pendientes"]`, sólo de los archivos NUEVOS que
        # `procesar_carpeta` acaba de procesar -- los ya presentes en el CSV
        # se omiten, ver `_archivos_ya_procesados`) -- nunca leía la bandeja
        # YA PERSISTIDA antes de sobrescribirla, así que cada corrida
        # (p.ej. Desktop arrastrando una guía nueva al mismo viaje que otra
        # ya tenía decisiones pendientes legítimas) descartaba en silencio
        # TODO lo que hubiera antes. Caso real: 472647 (2 decisiones ya
        # auditadas) perdidas al agregar 472648 al mismo transporte.
        # Mismo patrón ya correcto en `atlas_core.mobile.procesar_envio_
        # mobile`/`revalidar_y_regenerar_reporte` (nunca pisan la bandeja,
        # siempre la funden con lo ya persistido). Se reconcilia además con
        # `regenerar_decisiones_persistidas` -- así, si evidencia real de
        # ESTE mismo lote (u otra ya vigente) demuestra que una decisión
        # anterior quedó resuelta, se retira igual que en cualquier otra
        # vía oficial; si no hay ninguna razón demostrable, sobrevive
        # intacta. `generar_artefacto` deduplica por `decision_id` y filtra
        # contra el ledger -- nunca resucita una ya cerrada ni duplica una
        # ya vigente.
        ruta_artefacto = Path(argumentos.salida).parent / NOMBRE_ARTEFACTO
        # Bloque CONSISTENCIA OPERACIONAL -- leer la bandeja FRESCA +
        # fusionar + publicar es UNA sola sección crítica bajo el lock
        # común de decisiones (mismo patrón que
        # `procesar_envio_mobile`/las `reconciliar_decisiones_*`): leer
        # antes del lock dejaría la fusión racy frente a otro publicador
        # concurrente (Mobile, una decisión aplicada desde Desktop).
        with bloqueo_sesion(ruta_artefacto.parent, NOMBRE_LOCK_DECISIONES_PENDIENTES):
            decisiones_previas: list[dict[str, object]] = []
            try:
                decisiones_previas = json.loads(ruta_artefacto.read_text(encoding="utf-8")).get("decisiones", [])
            except (OSError, json.JSONDecodeError):
                pass
            decisiones_reconciliadas = regenerar_decisiones_persistidas(
                decisiones=[*decisiones_previas, *resumen.get("decisiones_pendientes", [])],
                carpeta_catalogos=estado_catalogos.ruta,
                ruta_dataset=argumentos.salida,
            )
            artefacto = _generar_artefacto_sin_lock(
                ruta_dataset=argumentos.salida,
                carpeta_catalogos=estado_catalogos.ruta,
                decisiones=decisiones_reconciliadas,
                ruta_salida=ruta_artefacto,
            )
        print(f"Decisiones pendientes: {len(artefacto['decisiones'])}")

        if argumentos.reconciliar_focal:
            # Bloque P0 INGESTA FOCAL -- corre DESPUÉS de publicar la
            # bandeja de arriba, a propósito: recién ahí
            # `decisiones_pendientes.json` en disco ya incluye las
            # decisiones nuevas de este lote (OBRA_DESCONOCIDA/etc,
            # detectadas SOLO durante `procesar_archivo` -- la
            # reconciliación no las vuelve a descubrir por su cuenta;
            # DESTINO_NO_RESUELTO sí se re-detecta sola, pero se deja
            # todo al mismo mecanismo para no bifurcar el camino).
            #
            # PlanImpacto = guías genuinamente nuevas de este lote +
            # cualquier guía que comparta `numero_transporte` con ellas
            # (mismo viaje -- el criterio de "afectada causalmente" que
            # ya usa el resto del sistema, p. ej. `revalidar_origen_por_
            # documento_hermano_de_transporte_sin_ocr`). Nunca el
            # backlog de rutas/identidad/segunda pasada ajeno -- ese
            # sigue disponible vía `reconciliar_estado_derivado.py`
            # (mantenimiento/reconciliación global explícita).
            from atlas_core.reconciliacion_estado_derivado import reconciliar_estado_derivado

            with open(argumentos.salida, encoding="utf-8-sig", newline="") as _fh:
                _filas_lote = list(csv.DictReader(_fh, delimiter=";"))
            archivos_nuevos = set(resumen.get("archivos_procesados_ahora", []))
            guias_nuevas = {
                str(f.get("numero_guia", "")).strip()
                for f in _filas_lote
                if str(f.get("archivo", "")).strip() in archivos_nuevos
                and str(f.get("numero_guia", "")).strip()
            }
            transportes_afectados = {
                str(f.get("numero_transporte", "")).strip()
                for f in _filas_lote
                if str(f.get("numero_guia", "")).strip() in guias_nuevas
                and str(f.get("numero_transporte", "")).strip()
            }
            guias_afectadas = set(guias_nuevas) | {
                str(f.get("numero_guia", "")).strip()
                for f in _filas_lote
                if str(f.get("numero_transporte", "")).strip() in transportes_afectados
                and str(f.get("numero_guia", "")).strip()
            }
            if guias_afectadas:
                raiz_reconciliacion = Path(estado_catalogos.ruta).parent
                resultado_reconciliacion = reconciliar_estado_derivado(
                    raiz_atlas=raiz_reconciliacion, guias_objetivo=guias_afectadas,
                )
                print(
                    f"Reconciliación focal: {len(guias_afectadas)} guía(s) en alcance "
                    f"({len(guias_nuevas)} nueva(s) + {len(guias_afectadas) - len(guias_nuevas)} "
                    f"afectada(s) por transporte compartido) -- "
                    f"reconciliado={resultado_reconciliacion.get('reconciliado')}"
                )
    print("\nResumen final")
    print(f"Total encontrados: {resumen['encontrados']}")
    print(f"Procesados: {resumen['procesados']}")
    print(f"Omitidos: {resumen['omitidos']}")
    print(f"Errores: {resumen['errores']}")
    print(f"Barras: {resumen['barras']}")
    print(f"Rollos: {resumen['rollos']}")
    print(f"Mixtos: {resumen['mixtos']}")
    print(f"No determinados: {resumen['no_determinados']}")
    print(f"Tiempo total: {resumen['tiempo_total_segundos']:.2f} segundos")
    print(
        "Promedio por archivo: "
        f"{resumen['promedio_segundos_archivo']:.2f} segundos"
    )


if __name__ == "__main__":
    main()
