"""Bloque BARRIDO GENERAL DE PATENTES SOSPECHOSAS -- catch-up FOCAL,
read-only, del catálogo/histórico de vehículos. Nunca hardcodea
equivalencias (nunca "RELSINSKI"->"HELSINSKI" ni "BPHF67"->"BPHR67"
como texto fijo): construye el universo real de patentes (catálogo +
histórico documental), detecta pares sospechosos por distancia de
edición de 1 carácter compatible con `catalogo_vehiculos.
es_confusion_ocr_de_patente` (la MISMA tabla de confusiones OCR ya
calibrada, nunca una nueva), y clasifica cada candidata usando
evidencia real -- nunca por frecuencia baja sola.

Caso real que motivó la calibración de los umbrales de este módulo:
BKYX63 (1 aparición histórica total) vs BKYK63 (15 -- 13 histórico + 2
vigente), mismo chofer/RUT, mismo día -- K/X ya calibrada -> se plegó.
Investigación de este mismo bloque sobre el resto del catálogo real
encontró 3 pares estructuralmente similares (JD8659/JE8659,
PXHH31/PXHH32, JF9565/JF9575) que NO deben plegarse: los primeros dos
tienen AMBOS lados con `procedencia=CONFIRMACION_HUMANA` (Javier
verificó cada patente directamente contra imágenes/guías reales,
incluso registrando explícitamente que son entidades DISTINTAS -- ver
`respaldos/JD8659_Y_REFRESCO_464717_.../LEEME_ROLLBACK.md`); el
tercero no tiene una confusión OCR calibrada entre "6"/"7" y la
evidencia de frecuencia no es suficientemente lopsided -- exactamente
los casos de seguridad B/C que este bloque exige nunca fusionar.

Clasificación (Sección 4 del bloque) -- 4 clases, nunca una quinta
difusa:

- A. OCR_INEQUIVOCO: se pliega a la canónica (mismo mecanismo ya
  existente, `catalogo_fichas._patente_canonica_o_plegada`/
  `_vehiculos_plegables_por_confusion_ocr` -- este módulo sólo informa
  la clasificación, nunca escribe el catálogo).
- B. ERROR_DOCUMENTAL_CONFIRMADO: el valor documental persiste como
  evidencia; se usa la canónica si existe; corresponde una Incidencia
  Documental (fuera del alcance de la detección estructural de este
  módulo -- requiere evidencia de que el documento en sí traía el dato
  incorrecto, no sólo una lectura OCR parecida).
- C. VEHICULO_REAL: entidad independiente, conservada tal cual.
- D. AMBIGUO: no se toca."""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

from atlas_core.catalogo_vehiculos import (
    cargar_catalogo_vehiculos,
    es_confusion_ocr_de_patente,
    normalizar_patente_vehiculo,
)
from atlas_core.procesamiento_masivo import COLUMNAS

_AUSENTES = {"", "No encontrado"}
_ERRORES_CATALOGO_VEHICULOS = (OSError, ValueError)

CLASE_OCR_INEQUIVOCO = "OCR_INEQUIVOCO"
CLASE_ERROR_DOCUMENTAL_CONFIRMADO = "ERROR_DOCUMENTAL_CONFIRMADO"
CLASE_VEHICULO_REAL = "VEHICULO_REAL"
CLASE_AMBIGUO = "AMBIGUO"

# Sección 5/12 del bloque, calibrado sobre evidencia real (nunca
# arbitrario): BKYX63 (1 aparición total) vs BKYK63 (15) -- ratio 15x,
# sospechosa <=2 apariciones. JF9565 (5) vs JF9575 (3) -- ratio 1.67x,
# ninguno se pliega (Sección 12, caso B: dos patentes similares
# realmente usadas por el mismo chofer nunca se fusionan). El piso
# "sospechosa <= 2" viene textual de la Sección 2 del bloque:
# "aparece 1-2 veces mientras otra casi idéntica aparece muchas veces".
_MAX_APARICIONES_SOSPECHOSA = 2
_RATIO_MINIMO_CANDIDATA = 3


@dataclass(frozen=True)
class _InfoPatente:
    patente: str
    roles: frozenset[str] = frozenset()
    apariciones: int = 0
    choferes: frozenset[str] = frozenset()
    ruts: frozenset[str] = frozenset()
    fechas: tuple[str, ...] = ()
    en_catalogo: bool = False
    tipo_catalogo: str | None = None
    procedencia: str = ""
    confirmado_por: str = ""


@dataclass(frozen=True)
class ClasificacionPatente:
    patente_sospechosa: str
    patente_candidata: str
    clase: str
    razon: str
    evidencia: tuple[str, ...] = field(default_factory=tuple)

    def a_dict(self) -> dict[str, object]:
        return {
            "patente_sospechosa": self.patente_sospechosa, "patente_candidata": self.patente_candidata,
            "clase": self.clase, "razon": self.razon, "evidencia": list(self.evidencia),
        }


def _leer_filas(ruta_dataset: Path) -> list[dict[str, str]]:
    if not ruta_dataset.is_file():
        return []
    try:
        with ruta_dataset.open("r", newline="", encoding="utf-8-sig") as archivo:
            lector = csv.DictReader(archivo, delimiter=";")
            if lector.fieldnames and list(lector.fieldnames) != COLUMNAS:
                return []
            return list(lector)
    except (OSError, csv.Error):
        return []


def _leer_filas_historico(ruta_dataset: Path) -> list[dict[str, str]]:
    """Igual que `_leer_filas`, pero sin exigir el esquema completo
    (`COLUMNAS`) -- archivos históricos/experimentales más antiguos
    (Sección 1: sólo como señal adicional, nunca escritos ni tratados
    como el dataset vigente) pueden tener columnas de menos. Los únicos
    campos que este módulo lee (`patente_tracto`/`patente_rampla`/
    `chofer`/`rut_chofer`/`fecha`) igual se leen correctamente vía
    `DictReader` mientras existan, sin importar el resto del esquema."""
    if not ruta_dataset.is_file():
        return []
    try:
        with ruta_dataset.open("r", newline="", encoding="utf-8-sig") as archivo:
            return list(csv.DictReader(archivo, delimiter=";"))
    except (OSError, csv.Error):
        return []


def construir_universo_patentes(
    *, filas: list[dict[str, str]], filas_historicas: list[dict[str, str]] = (),
    vehiculos_por_patente: Mapping[str, object] | None = None,
) -> dict[str, _InfoPatente]:
    """Sección 1 del bloque -- une catálogo + histórico documental
    (vigente y, si se entrega, un histórico adicional más amplio) en un
    único universo de patentes con sus señales objetivas (Sección 2):
    apariciones, chofer(es)/RUT, fechas, rol documental."""
    vehiculos_por_patente = vehiculos_por_patente or {}
    acumulado: dict[str, dict[str, object]] = {}

    def _acumular(fila: Mapping[str, str]) -> None:
        for campo, rol in (("patente_tracto", "TRACTO"), ("patente_rampla", "CARRO")):
            valor = str(fila.get(campo, "")).strip()
            if not valor or valor in _AUSENTES:
                continue
            patente = normalizar_patente_vehiculo(valor)
            registro = acumulado.setdefault(patente, {
                "roles": set(), "apariciones": 0, "choferes": set(), "ruts": set(), "fechas": [],
            })
            registro["roles"].add(rol)
            registro["apariciones"] += 1
            chofer = str(fila.get("chofer", "")).strip()
            if chofer and chofer not in _AUSENTES:
                registro["choferes"].add(chofer)
            rut = str(fila.get("rut_chofer", "")).strip()
            if rut and rut not in _AUSENTES:
                registro["ruts"].add(rut)
            fecha = str(fila.get("fecha", "")).strip()
            if fecha and fecha not in _AUSENTES:
                registro["fechas"].append(fecha)

    for fila in filas:
        _acumular(fila)
    for fila in filas_historicas:
        _acumular(fila)

    for patente, vehiculo in vehiculos_por_patente.items():
        acumulado.setdefault(patente, {"roles": set(), "apariciones": 0, "choferes": set(), "ruts": set(), "fechas": []})

    universo: dict[str, _InfoPatente] = {}
    for patente, registro in acumulado.items():
        vehiculo = vehiculos_por_patente.get(patente)
        universo[patente] = _InfoPatente(
            patente=patente, roles=frozenset(registro["roles"]), apariciones=registro["apariciones"],
            choferes=frozenset(registro["choferes"]), ruts=frozenset(registro["ruts"]),
            fechas=tuple(registro["fechas"]), en_catalogo=vehiculo is not None,
            tipo_catalogo=getattr(vehiculo, "tipo", None) if vehiculo is not None else None,
            procedencia=getattr(vehiculo, "procedencia", "") if vehiculo is not None else "",
            confirmado_por=getattr(vehiculo, "confirmado_por", "") if vehiculo is not None else "",
        )
    return universo


def detectar_pares_sospechosos(universo: Mapping[str, _InfoPatente]) -> list[tuple[str, str]]:
    """Sección 2/3 del bloque -- candidatos: dos patentes del universo
    que difieren en exactamente un carácter (mismo largo) Y comparten al
    menos un rol documental compatible (TRACTO/CARRO) -- nunca compara
    patentes de rol incompatible (Sección 12, caso C)."""
    patentes = sorted(universo)
    pares: list[tuple[str, str]] = []
    for i in range(len(patentes)):
        for j in range(i + 1, len(patentes)):
            a, b = patentes[i], patentes[j]
            if len(a) != len(b):
                continue
            diferencias = [k for k in range(len(a)) if a[k] != b[k]]
            if len(diferencias) != 1:
                continue
            info_a, info_b = universo[a], universo[b]
            if info_a.roles and info_b.roles and not (info_a.roles & info_b.roles):
                continue  # roles documentados y sin intersección -- nunca compatibles (Sección 12, caso C)
            pares.append((a, b))
    return pares


def clasificar_par(par: tuple[str, str], universo: Mapping[str, _InfoPatente]) -> ClasificacionPatente:
    """Sección 4/5 del bloque -- decide, para un par sospechoso, cuál
    lado (si alguno) es la canónica y en qué clase queda el otro.
    Nunca elige a ciegas por frecuencia: una patente con
    `procedencia=CONFIRMACION_HUMANA` es intocable (Sección 12, caso B
    real: JD8659/JE8659, PXHH31/PXHH32)."""
    a, b = par
    info_a, info_b = universo[a], universo[b]
    # La de menor evidencia es la candidata a "sospechosa"; en empate,
    # orden alfabético (determinista, nunca aleatorio).
    baja, alta = (info_a, info_b) if (info_a.apariciones, a) <= (info_b.apariciones, b) else (info_b, info_a)

    if baja.confirmado_por or baja.procedencia == "CONFIRMACION_HUMANA":
        return ClasificacionPatente(
            patente_sospechosa=baja.patente, patente_candidata=alta.patente, clase=CLASE_VEHICULO_REAL,
            razon=(
                f'"{baja.patente}" tiene confirmación humana explícita en el catálogo '
                f"(procedencia={baja.procedencia!r}, confirmado_por={baja.confirmado_por!r}) -- "
                "nunca se pliega, aunque estructuralmente se parezca a otra patente."
            ),
            evidencia=("CONFIRMACION_HUMANA_EN_CATALOGO",),
        )
    if not es_confusion_ocr_de_patente(baja.patente, alta.patente):
        return ClasificacionPatente(
            patente_sospechosa=baja.patente, patente_candidata=alta.patente, clase=CLASE_AMBIGUO,
            razon=(
                f'"{baja.patente}"/"{alta.patente}" difieren en un carácter, pero esa diferencia no es una '
                "confusión OCR calibrada -- nunca se trata como error de lectura sin esa evidencia."
            ),
            evidencia=("DIFERENCIA_NO_CALIBRADA",),
        )

    evidencia_convergente = bool(baja.ruts & alta.ruts) or bool(baja.choferes & alta.choferes)
    lopsided = baja.apariciones <= _MAX_APARICIONES_SOSPECHOSA and (
        alta.apariciones >= _RATIO_MINIMO_CANDIDATA * max(baja.apariciones, 1)
    )
    if evidencia_convergente and lopsided:
        return ClasificacionPatente(
            patente_sospechosa=baja.patente, patente_candidata=alta.patente, clase=CLASE_OCR_INEQUIVOCO,
            razon=(
                f'"{baja.patente}" ({baja.apariciones} aparición{"es" if baja.apariciones != 1 else ""}) es una '
                f'confusión OCR calibrada de "{alta.patente}" ({alta.apariciones} apariciones), con chofer/RUT en '
                "común -- único candidato, sin alternativa plausible."
            ),
            evidencia=("CONFUSION_OCR_CALIBRADA", "CONTEXTO_CONVERGENTE", "FRECUENCIA_LOPSIDED"),
        )
    return ClasificacionPatente(
        patente_sospechosa=baja.patente, patente_candidata=alta.patente, clase=CLASE_AMBIGUO,
        razon=(
            f'"{baja.patente}"/"{alta.patente}" comparten una confusión OCR calibrada, pero la evidencia no '
            "converge lo suficiente (sin chofer/RUT en común, o ambos lados tienen evidencia real propia) -- "
            "podrían ser dos vehículos reales distintos usados por el mismo contexto."
        ),
        evidencia=("CONFUSION_OCR_CALIBRADA",) + (("CONTEXTO_CONVERGENTE",) if evidencia_convergente else ()),
    )


def generar_reporte_catchup_patentes(
    *, raiz_atlas: str | Path, rutas_dataset_historico: tuple[str | Path, ...] = (),
) -> dict[str, object]:
    """Sección 11 del bloque -- orquesta 1-4 contra los datos reales de
    `raiz_atlas` y devuelve el reporte interno: patentes revisadas,
    sospechosas, y su clasificación completa. Nunca escribe nada --
    read-only. `rutas_dataset_historico` es opcional (Sección 1: "no
    revisar imágenes masivamente todavía" -- pero si ya existe un CSV
    histórico más amplio ya persistido, se puede sumar como señal
    adicional, igual que se hizo manualmente para BKYX63)."""
    raiz = Path(raiz_atlas)
    dataset = raiz / "operacion" / "actual" / "analisis_completo_guias.csv"
    filas = _leer_filas(dataset)
    filas_historicas: list[dict[str, str]] = []
    for ruta_extra in rutas_dataset_historico:
        filas_historicas.extend(_leer_filas_historico(Path(ruta_extra)))

    try:
        vehiculos = cargar_catalogo_vehiculos(raiz / "catalogos_privados" / "vehiculos.json").homologables()
    except _ERRORES_CATALOGO_VEHICULOS:
        vehiculos = ()
    vehiculos_por_patente = {v.patente_canonica: v for v in vehiculos}

    universo = construir_universo_patentes(
        filas=filas, filas_historicas=filas_historicas, vehiculos_por_patente=vehiculos_por_patente,
    )
    pares = detectar_pares_sospechosos(universo)
    clasificaciones = [clasificar_par(par, universo) for par in pares]

    conteo_por_clase: dict[str, int] = {}
    for c in clasificaciones:
        conteo_por_clase[c.clase] = conteo_por_clase.get(c.clase, 0) + 1

    return {
        "patentes_revisadas": len(universo),
        "pares_sospechosos": len(pares),
        "conteo_por_clase": conteo_por_clase,
        "clasificaciones": [c.a_dict() for c in clasificaciones],
    }
