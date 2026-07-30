"""Resolución aislada y conservadora de material + tipo de carga."""

from __future__ import annotations

import difflib
import re
import unicodedata
from dataclasses import dataclass
from types import MappingProxyType
from typing import Iterable, Mapping

from atlas_core.clasificador_material import TipoCarga
from atlas_core.inteligencia.contrato_multicampo import EstadoResolucion
from atlas_core.inteligencia.politica_confianza_material import (
    POLITICA_CONFIANZA_MATERIAL_V1, PoliticaConfianzaMaterial, ViaDecisionMaterial,
)
from atlas_core.inteligencia.snapshot_catalogo_materiales import (
    InstantaneaCatalogoMateriales, crear_snapshot_catalogo_materiales,
)

TIPOS = frozenset(item.value for item in TipoCarga)
_FORMAS_BARRAS = re.compile(r"\b(?:BARRAS?|PERFILES?)\b")
_FORMAS_ROLLOS = re.compile(r"\b(?:ROLLOS?|BOBINAS?|ALAMBRON)\b")
_GENERICO = frozenset({"MATERIAL", "ACERO", "FIERRO", "PRODUCTO"})
_NO_MATERIAL = re.compile(
    r"^\s*(?:\d+(?:[.,]\d+)?\s*(?:KG|KGS|TON|TONS|TM|UN|UND|M|MM)?|"
    r"(?:KG|KGS|TON|TONS|TM|UN|UND|M|MM)|[A-Z]{0,3}\d{4,}[A-Z0-9-]*)\s*$",
    re.I,
)


@dataclass(frozen=True)
class CandidatoMaterial:
    valor_original: str
    contexto: str = "MATERIAL"
    documento_id: str = ""
    calidad: float = 1.0

    def __post_init__(self) -> None:
        if not 0 <= self.calidad <= 1:
            raise ValueError("calidad fuera de rango")


@dataclass(frozen=True)
class ResultadoResolucionMaterial:
    descripcion_material_original: str
    lineas_material_originales: tuple[str, ...]
    tipo_carga_original: str
    material_canonico: str | None
    id_material_canonico: str | None
    materiales_canonicos: tuple[str, ...]
    ids_materiales_canonicos: tuple[str, ...]
    tipo_carga_canonico: str | None
    estado_resolucion: EstadoResolucion
    confianza: float
    razones: tuple[str, ...]
    contradicciones: tuple[str, ...]
    requiere_revision: bool
    via_decision: str
    version_catalogo: str
    trazabilidad: Mapping[str, tuple[str, ...]]

    def __post_init__(self) -> None:
        object.__setattr__(self, "trazabilidad", MappingProxyType(dict(self.trazabilidad)))


def normalizar_material(valor: object) -> str:
    texto = unicodedata.normalize("NFD", str(valor or "").upper())
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return " ".join(re.findall(r"[A-Z0-9]+", texto))


def _tipo_texto(valor: object) -> str | None:
    normal = normalizar_material(valor)
    if normal in TIPOS:
        return normal
    return None


def _formas(lineas: Iterable[str]) -> tuple[bool, bool, bool]:
    normalizadas = tuple(normalizar_material(x) for x in lineas)
    barras = any(_FORMAS_BARRAS.search(x) for x in normalizadas)
    rollos = any(_FORMAS_ROLLOS.search(x) for x in normalizadas)
    misma_linea = any(
        _FORMAS_BARRAS.search(x) and _FORMAS_ROLLOS.search(x)
        for x in normalizadas
    )
    return barras, rollos, misma_linea


def resolver_material_tipo_carga(
    descripcion_material_ocr: object = "",
    tipo_carga_ocr: object = "",
    catalogo_materiales=(),
    *,
    lineas_ocr: Iterable[CandidatoMaterial | Mapping[str, object] | str] = (),
    politica: PoliticaConfianzaMaterial = POLITICA_CONFIANZA_MATERIAL_V1,
    contexto: Mapping[str, object] | None = None,
) -> ResultadoResolucionMaterial:
    original = "" if descripcion_material_ocr is None else str(descripcion_material_ocr)
    tipo_original = "" if tipo_carga_ocr is None else str(tipo_carga_ocr)
    candidatos: list[CandidatoMaterial] = []
    if original:
        candidatos.extend(CandidatoMaterial(linea) for linea in original.splitlines())
    for item in lineas_ocr:
        if isinstance(item, CandidatoMaterial):
            candidatos.append(item)
        elif isinstance(item, Mapping):
            candidatos.append(CandidatoMaterial(**item))
        else:
            candidatos.append(CandidatoMaterial(str(item)))
    lineas = tuple(c.valor_original for c in candidatos)
    razones = ["OCR_ORIGINAL_CONSERVADO", "SIN_ESCRITURA_CATALOGO"]
    contradicciones: list[str] = []
    documentos = {c.documento_id for c in candidatos if c.documento_id}
    if len(documentos) > 1:
        contradicciones.append("MULTIPLES_DOCUMENTOS_VISIBLES")
    utiles = [
        c for c in candidatos
        if normalizar_material(c.contexto) in {"", "MATERIAL", "DESCRIPCION MATERIAL"}
        and normalizar_material(c.valor_original)
        and not _NO_MATERIAL.fullmatch(c.valor_original)
    ]
    snapshot = catalogo_materiales if isinstance(
        catalogo_materiales, InstantaneaCatalogoMateriales
    ) else crear_snapshot_catalogo_materiales(catalogo_materiales)
    indices: dict[str, list[tuple[str, Mapping[str, object], str]]] = {}
    for identificador, registro in snapshot.registros.items():
        for clase, clave in (
            ("EXACTO", registro.get("descripcion_oficial", "")),
            *(("ALIAS", x) for x in registro.get("aliases", ())),
            *(("ABREVIACION", x) for x in registro.get("abreviaciones", ())),
        ):
            normal = normalizar_material(clave)
            if normal:
                indices.setdefault(normal, []).append((identificador, registro, clase))
    resueltos: list[tuple[str, Mapping[str, object], str]] = []
    fuzzy: list[tuple[float, str, Mapping[str, object]]] = []
    for candidato in utiles:
        normal = normalizar_material(candidato.valor_original)
        if normal in _GENERICO:
            continue
        matches = indices.get(normal, [])
        if len(matches) == 1:
            resueltos.append(matches[0])
        elif len(matches) > 1:
            contradicciones.append("MATERIAL_CATALOGO_AMBIGUO")
        elif len(normal) >= 5:
            ranking = []
            for identificador, registro in snapshot.registros.items():
                valores = [registro.get("descripcion_oficial", ""), *registro.get("aliases", ())]
                puntaje = max(difflib.SequenceMatcher(None, normal, normalizar_material(v)).ratio() for v in valores)
                ranking.append((puntaje, identificador, registro))
            ranking.sort(key=lambda x: (-x[0], x[1]))
            if ranking:
                segundo = ranking[1][0] if len(ranking) > 1 else 0
                if ranking[0][0] >= politica.umbral_fuzzy and ranking[0][0] - segundo >= politica.margen_fuzzy:
                    fuzzy.append(ranking[0])
    explicito = _tipo_texto(tipo_original)
    barras, rollos, misma_linea = _formas(c.valor_original for c in utiles)
    derivado = "MIXTO" if barras and rollos else "BARRAS" if barras else "ROLLOS" if rollos else None
    if misma_linea:
        contradicciones.append("DOS_FORMAS_EN_MISMA_LINEA")
    if explicito and derivado and explicito != derivado:
        contradicciones.append("TIPO_CARGA_CONTRADICTORIO")
    tipo = explicito or derivado
    if fuzzy and not resueltos:
        candidato_tipo = str(fuzzy[0][2].get("tipo_carga", ""))
        if explicito and candidato_tipo == explicito:
            resueltos.append((fuzzy[0][1], fuzzy[0][2], "FUZZY_MAS_TIPO"))
        else:
            razones.append("FUZZY_AISLADO_NO_CONFIRMA")
    unicos = {item[0]: item for item in resueltos}
    if any(str(r.get("estado_vigencia", "")) != "ACTIVO" for _, r, _ in unicos.values()):
        contradicciones.append("MATERIAL_INACTIVO")
    if any(str(r.get("estado_calidad", "")) != "CONFIRMADO" for _, r, _ in unicos.values()):
        contradicciones.append("CALIDAD_NO_CONFIRMADA")
    if unicos and any(c.calidad < politica.calidad_minima for c in utiles):
        contradicciones.append("OCR_BAJA_CALIDAD")
    tipos_catalogo = {str(r.get("tipo_carga", "")) for _, r, _ in unicos.values() if r.get("tipo_carga")}
    if tipo and tipos_catalogo and tipo not in tipos_catalogo and not (tipo == "MIXTO" and len(tipos_catalogo) > 1):
        contradicciones.append("MATERIAL_TIPO_INCOMPATIBLE")
    nombres = tuple(str(r.get("descripcion_oficial", "")) for _, r, _ in unicos.values())
    ids = tuple(unicos)
    if contradicciones:
        estado, via, confianza = EstadoResolucion.REQUIERE_REVISION, ViaDecisionMaterial.CONTRADICCION, 0.0
    elif nombres:
        clases = {clase for _, _, clase in unicos.values()}
        if len(nombres) > 1:
            via = ViaDecisionMaterial.COMPUESTO
        elif "FUZZY_MAS_TIPO" in clases:
            via = ViaDecisionMaterial.FUZZY_MAS_TIPO
        elif "ABREVIACION" in clases:
            via = ViaDecisionMaterial.ABREVIACION
        elif "ALIAS" in clases:
            via = ViaDecisionMaterial.ALIAS
        else:
            via = ViaDecisionMaterial.EXACTO
        estado, confianza = EstadoResolucion.CONFIRMADO, min((c.calidad for c in utiles), default=1.0)
    elif tipo:
        estado, via, confianza = EstadoResolucion.PROPUESTO, ViaDecisionMaterial.NO_RESUELTO, 0.75 if explicito else 0.70
    else:
        estado, via, confianza = EstadoResolucion.NO_RESUELTO, ViaDecisionMaterial.NO_RESUELTO, 0.0
    return ResultadoResolucionMaterial(
        original, lineas, tipo_original,
        nombres[0] if len(nombres) == 1 else (" | ".join(nombres) if nombres else None),
        ids[0] if len(ids) == 1 else None, nombres, ids, tipo, estado, confianza,
        tuple(razones), tuple(dict.fromkeys(contradicciones)),
        estado is not EstadoResolucion.CONFIRMADO, via.value, snapshot.version,
        {"documentos": tuple(sorted(documentos)), "contexto_ignorado": tuple(sorted((contexto or {}).keys()))},
    )
