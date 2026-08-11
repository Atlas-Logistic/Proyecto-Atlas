"""Reportes de viajes compatibles con CSV masivos Atlas de 15 y 21 columnas.

Contrato de entrada:

* ``COLUMNAS_OFICIALES``: las 15 columnas productivas de
  :mod:`atlas_core.procesamiento_masivo`; todas son obligatorias.
* ``COLUMNAS_HISTORICAS``: seis columnas opcionales de trazabilidad usadas por
  el runtime histórico. Se preservan si están presentes.
* Otras columnas adicionales se aceptan y se preservan en
  ``documentos_sin_transporte.csv``. Nunca se inventan valores ausentes.

Los campos se leen siempre como texto, por lo que números de transporte y
guías conservan sus ceros iniciales.
"""

from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from atlas_core.catalogo_clientes import (
    CatalogoClientes,
    EstadoVigenciaCliente,
    normalizar_nombre_cliente,
)
from atlas_core.catalogos import (
    cargar_catalogo_json,
    resolver_nombre_chofer_difuso,
)
from atlas_core.gestor_viajes import EstadoViaje, agrupar_viajes
from atlas_core.procesamiento_masivo import COLUMNAS as COLUMNAS_PROCESAMIENTO


COLUMNAS_OFICIALES = tuple(COLUMNAS_PROCESAMIENTO)
COLUMNAS_HISTORICAS = (
    "numero_guia_fuente",
    "numero_guia_motivo",
    "rut_chofer_estado_validacion",
    "cliente_fuente",
    "obra_destino_fuente",
    "chofer_fuente",
)
COLUMNAS_OBLIGATORIAS = COLUMNAS_OFICIALES
# Alias conservado para consumidores anteriores.
COLUMNAS_ESPERADAS = list(COLUMNAS_OFICIALES + COLUMNAS_HISTORICAS)

ARCHIVOS_SALIDA = (
    "viajes.csv",
    "documentos_sin_transporte.csv",
    "clientes_no_reconocidos.csv",
    "resumen_viajes.md",
    "manifest_reporte_viajes.json",
)
COLUMNAS_CLIENTES_NO_RECONOCIDOS = (
    "cliente",
    "cantidad_apariciones",
    "archivos",
)
COLUMNAS_VIAJES = (
    "viaje_id",
    "numero_transporte",
    "fecha",
    "estado",
    "motivos_revision",
    "cantidad_documentos",
    "documentos",
    "numeros_guia",
    "clientes",
    "obras_destino",
    "origenes",
    "choferes",
    "ruts_chofer",
    "patentes_tracto",
    "patentes_rampla",
    "materiales",
    "tipos_carga",
    "evidencias_documentos",
    "fecha_creacion",
    # Bloque RUTAS R1: enriquecimiento logístico opcional (planta origen +
    # destino canónico + ORS). Agregadas al final -- backward-compatible:
    # sin `calculador_rutas`, quedan vacías y el reporte es idéntico al de
    # antes de este bloque.
    "planta_origen_id",
    "planta_origen_nombre",
    "destino_id",
    "destino_nombre",
    "distancia_km",
    "duracion_min",
    "proveedor_ruta",
    "estado_ruta",
    "motivo_ruta",
    "origen_determinado_por",
    "evidencia_origen",
)


def _sha256_archivo(ruta: Path) -> str:
    digest = hashlib.sha256()
    with ruta.open("rb") as archivo:
        for bloque in iter(lambda: archivo.read(1024 * 1024), b""):
            digest.update(bloque)
    return digest.hexdigest()


def _validar_rutas(origen: Path, salida: Path) -> None:
    if not origen.exists():
        raise FileNotFoundError(f"El CSV de entrada no existe: {origen}")
    if not origen.is_file():
        raise ValueError(f"La entrada no es un archivo: {origen}")
    if salida.exists():
        if not salida.is_dir():
            raise ValueError(f"La salida no es un directorio: {salida}")
        existentes = [nombre for nombre in ARCHIVOS_SALIDA if (salida / nombre).exists()]
        if existentes:
            raise FileExistsError(
                "El directorio de salida ya contiene un reporte anterior: "
                f"{', '.join(existentes)}. Use un directorio nuevo."
            )


def _validar_esquema(columnas: list[str]) -> None:
    repetidas = sorted(c for c, cantidad in Counter(columnas).items() if cantidad > 1)
    if repetidas:
        raise ValueError(
            "Esquema CSV incompatible; columnas repetidas: " + ", ".join(repetidas)
        )
    faltantes = [c for c in COLUMNAS_OBLIGATORIAS if c not in columnas]
    if faltantes:
        raise ValueError(
            "Esquema CSV incompatible; faltan columnas obligatorias: "
            + ", ".join(faltantes)
        )


def _leer_csv_solo_lectura(
    ruta_csv: Path,
) -> tuple[list[dict[str, str]], list[str]]:
    with ruta_csv.open("r", newline="", encoding="utf-8-sig") as archivo:
        lector = csv.reader(archivo, delimiter=";")
        columnas = next(lector, None)
        if not columnas:
            raise ValueError("El CSV está vacío y no contiene encabezado")
        _validar_esquema(columnas)
        filas: list[dict[str, str]] = []
        for valores in lector:
            if len(valores) != len(columnas):
                raise ValueError(
                    f"La fila {lector.line_num} tiene {len(valores)} valores; "
                    f"se esperaban {len(columnas)}"
                )
            filas.append(dict(zip(columnas, valores)))
    return filas, columnas


def _escribir_csv(
    ruta: Path,
    columnas: tuple[str, ...] | list[str],
    filas: list[dict[str, object]],
) -> None:
    with ruta.open("w", newline="", encoding="utf-8-sig") as archivo:
        escritor = csv.DictWriter(
            archivo, fieldnames=list(columnas), delimiter=";", extrasaction="ignore"
        )
        escritor.writeheader()
        escritor.writerows(filas)


_CAMPOS_RUTA_VACIOS = {
    "planta_origen_id": "", "planta_origen_nombre": "",
    "destino_id": "", "destino_nombre": "",
    "distancia_km": "", "duracion_min": "",
    "proveedor_ruta": "", "estado_ruta": "", "motivo_ruta": "",
    "origen_determinado_por": "", "evidencia_origen": "",
}


def _fila_viaje(
    viaje, calculador_rutas: Callable[[object], dict[str, str]] | None = None
) -> dict[str, object]:
    datos = viaje.a_dict()
    campos_ruta = dict(_CAMPOS_RUTA_VACIOS)
    if calculador_rutas is not None:
        resultado = calculador_rutas(viaje)
        if resultado:
            campos_ruta.update({clave: resultado.get(clave, "") for clave in _CAMPOS_RUTA_VACIOS})
    return {
        "viaje_id": datos["viaje_id"],
        "numero_transporte": datos["numero_transporte"],
        "fecha": datos["fecha"],
        "estado": datos["estado"],
        "motivos_revision": " | ".join(datos["motivos_revision"]),
        "cantidad_documentos": len(datos["documentos"]),
        "documentos": " | ".join(datos["documentos"]),
        "numeros_guia": " | ".join(datos["numeros_guia"]),
        "clientes": " | ".join(datos["clientes"]),
        "obras_destino": " | ".join(datos["obras_destino"]),
        "origenes": " | ".join(datos["origenes"]),
        "choferes": " | ".join(datos["choferes"]),
        "ruts_chofer": " | ".join(datos["ruts_chofer"]),
        "patentes_tracto": " | ".join(datos["patentes_tracto"]),
        "patentes_rampla": " | ".join(datos["patentes_rampla"]),
        "materiales": " | ".join(datos["materiales"]),
        "tipos_carga": " | ".join(datos["tipos_carga"]),
        "evidencias_documentos": json.dumps(
            datos["evidencias_documentos"], ensure_ascii=False, sort_keys=True
        ),
        "fecha_creacion": datos["fecha_creacion"],
        **campos_ruta,
    }


def _nombres_conocidos(carpeta_catalogos: Path) -> set[str]:
    conocidos: set[str] = set()
    empresas = cargar_catalogo_json(carpeta_catalogos / "empresas.json")
    for registro in empresas.values():
        nombre = registro.get("nombre") if isinstance(registro, dict) else None
        if isinstance(nombre, str) and nombre.strip():
            conocidos.add(normalizar_nombre_cliente(nombre))
    for cliente in CatalogoClientes(carpeta_catalogos / "clientes.json").listar():
        if cliente.estado_vigencia != EstadoVigenciaCliente.ACTIVO.value:
            continue
        conocidos.add(normalizar_nombre_cliente(cliente.razon_social))
        conocidos.update(normalizar_nombre_cliente(alias) for alias in cliente.aliases)
    return conocidos


def _construir_clientes_no_reconocidos(
    filas: list[dict[str, str]], carpeta_catalogos: Path
) -> list[dict[str, object]]:
    conocidos = _nombres_conocidos(carpeta_catalogos)
    grupos: dict[str, dict[str, object]] = {}
    for fila in filas:
        texto = fila.get("cliente", "").strip()
        if not texto or texto.casefold() == "no encontrado":
            continue
        clave = normalizar_nombre_cliente(texto)
        if not clave or clave in conocidos:
            continue
        grupo = grupos.setdefault(clave, {"variantes": Counter(), "archivos": []})
        grupo["variantes"][texto] += 1
        grupo["archivos"].append(fila.get("archivo", ""))
    resultado = [
        {
            "cliente": sorted(
                grupo["variantes"],
                key=lambda variante: (
                    -grupo["variantes"][variante],
                    _clave_cliente_orden(variante),
                    variante,
                ),
            )[0],
            "cantidad_apariciones": sum(grupo["variantes"].values()),
            "archivos": " | ".join(sorted(grupo["archivos"])),
        }
        for grupo in grupos.values()
    ]
    return sorted(
        resultado, key=lambda item: (-item["cantidad_apariciones"], item["cliente"])
    )


def _clave_cliente_orden(valor: str) -> str:
    return normalizar_nombre_cliente(valor)


def _normalizador_chofer_desde_catalogo(catalogo):
    """Aplica exactamente el fuzzy conservador aprobado, sin cambiar umbrales."""

    def normalizar(valor: str) -> str:
        decision = resolver_nombre_chofer_difuso(catalogo, valor)
        return (
            decision.valor_resultado
            if decision.estado == "COINCIDENCIA_SEGURA"
            else valor
        )

    return normalizar


def _resumen_markdown(
    viajes,
    sin_transporte,
    clientes_no_reconocidos,
    origen: Path,
    fecha_generacion: str,
) -> str:
    confirmados = [v for v in viajes if v.estado == EstadoViaje.CONFIRMADO]
    revision = [v for v in viajes if v.estado == EstadoViaje.REQUIERE_REVISION]
    motivos = Counter(m.value for viaje in revision for m in viaje.motivos_revision)
    lineas = [
        "# Reporte de viajes",
        "",
        f"Origen: `{origen}`",
        f"Fecha de generación: {fecha_generacion}",
        "",
        "## Resumen",
        "",
        f"- Viajes identificados: {len(viajes)}",
        f"- Viajes confirmados: {len(confirmados)}",
        f"- Viajes que requieren revisión: {len(revision)}",
        f"- Documentos sin transporte: {len(sin_transporte)}",
        f"- Clientes no reconocidos: {len(clientes_no_reconocidos)}",
        "",
    ]
    if motivos:
        lineas.extend(["## Motivos de revisión", ""])
        lineas.extend(f"- {motivo}: {cantidad}" for motivo, cantidad in sorted(motivos.items()))
        lineas.append("")
    lineas.append(
        "El reporte conserva las evidencias originales y no elige silenciosamente "
        "entre valores contradictorios."
    )
    return "\n".join(lineas) + "\n"


def generar_reporte_viajes(
    ruta_csv: str | Path,
    directorio_salida: str | Path,
    *,
    carpeta_catalogos: str | Path = "catalogos",
    reloj: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    calculador_rutas: Callable[[object], dict[str, str]] | None = None,
) -> dict[str, object]:
    """Agrupa viajes sin modificar la entrada ni sobrescribir otro reporte.

    `calculador_rutas` (Bloque RUTAS R1, opcional): función que recibe un
    `Viaje` y devuelve el enriquecimiento de ruta (ver
    `atlas_core.rutas.calcular_ruta_para_viaje`/`ResultadoEnriquecimientoRuta.a_dict`).
    Sin este parámetro (comportamiento por defecto, sin cambios), las
    columnas de ruta quedan vacías -- 100% compatible con reportes previos
    a este bloque.
    """
    origen = Path(ruta_csv)
    salida = Path(directorio_salida)
    _validar_rutas(origen, salida)
    sha_antes = _sha256_archivo(origen)
    filas, columnas_entrada = _leer_csv_solo_lectura(origen)
    sha_despues = _sha256_archivo(origen)
    if sha_antes != sha_despues:
        raise RuntimeError("El CSV cambió durante la lectura; se aborta el reporte")

    catalogos = Path(carpeta_catalogos)
    normalizador = _normalizador_chofer_desde_catalogo(
        cargar_catalogo_json(catalogos / "choferes.json")
    )
    instante = reloj()
    viajes, sin_transporte = agrupar_viajes(
        filas, normalizador_chofer=normalizador, reloj=lambda: instante
    )
    no_reconocidos = _construir_clientes_no_reconocidos(filas, catalogos)
    fecha_generacion = instante.isoformat()

    salida.mkdir(parents=True, exist_ok=True)
    _escribir_csv(
        salida / "viajes.csv",
        COLUMNAS_VIAJES,
        [_fila_viaje(viaje, calculador_rutas) for viaje in viajes],
    )
    _escribir_csv(
        salida / "documentos_sin_transporte.csv",
        columnas_entrada,
        sin_transporte,
    )
    _escribir_csv(
        salida / "clientes_no_reconocidos.csv",
        COLUMNAS_CLIENTES_NO_RECONOCIDOS,
        no_reconocidos,
    )
    (salida / "resumen_viajes.md").write_text(
        _resumen_markdown(
            viajes, sin_transporte, no_reconocidos, origen, fecha_generacion
        ),
        encoding="utf-8",
    )

    confirmados = [v for v in viajes if v.estado == EstadoViaje.CONFIRMADO]
    revision = [v for v in viajes if v.estado == EstadoViaje.REQUIERE_REVISION]
    manifest = {
        "version_reporte": "reporte-viajes-v2",
        "fecha_generacion": fecha_generacion,
        "origen": {"ruta": str(origen), "sha256": sha_despues},
        "esquema_entrada": {
            "columnas": columnas_entrada,
            "tipo": (
                "HISTORICO_21"
                if all(c in columnas_entrada for c in COLUMNAS_HISTORICAS)
                else "OFICIAL_15"
            ),
        },
        "totales": {
            "filas_leidas": len(filas),
            "viajes": len(viajes),
            "viajes_confirmados": len(confirmados),
            "viajes_requieren_revision": len(revision),
            "documentos_sin_transporte": len(sin_transporte),
            "clientes_no_reconocidos": len(no_reconocidos),
        },
        "salidas": list(ARCHIVOS_SALIDA[:-1]),
    }
    (salida / "manifest_reporte_viajes.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest
