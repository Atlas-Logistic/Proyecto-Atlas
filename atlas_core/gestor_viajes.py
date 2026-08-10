"""Agrupación trazable y conservadora de documentos en viajes.

La agrupación usa ``numero_transporte`` como clave, pero nunca resuelve en
silencio contradicciones entre documentos. Los valores originales quedan en
``evidencias_documentos`` para permitir auditorías posteriores.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from enum import Enum
from typing import Callable, Iterable, Mapping
from uuid import NAMESPACE_URL, uuid5


_AUSENTES = {"", "no encontrado", "revisar", "ilegible"}
_PATRON_TRANSPORTE = re.compile(r"^\d+$")


def _valor_presente(valor: object) -> bool:
    texto = str(valor or "").strip()
    return bool(texto) and texto.casefold() not in _AUSENTES


def _clave_normalizada(valor: object) -> str:
    texto = " ".join(str(valor or "").strip().casefold().split())
    sin_acentos = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in sin_acentos if not unicodedata.combining(c))


def _transporte_valido(valor: object) -> bool:
    texto = str(valor or "").strip()
    return _valor_presente(texto) and _PATRON_TRANSPORTE.fullmatch(texto) is not None


def _fecha_para_desktop(valor: object) -> str | None:
    texto = str(valor or "").strip()
    if not _valor_presente(texto):
        return None
    dmy = re.fullmatch(r"(\d{1,2})[-/](\d{1,2})[-/](\d{4})", texto)
    iso = re.fullmatch(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", texto)
    if dmy:
        dia, mes, anio = map(int, dmy.groups())
    elif iso:
        anio, mes, dia = map(int, iso.groups())
    else:
        return None
    try:
        fecha = date(anio, mes, dia)
    except ValueError:
        return None
    return fecha.strftime("%d-%m-%Y")


def _valores_unicos(valores: Iterable[str]) -> list[str]:
    unicos: dict[str, str] = {}
    for valor in valores:
        if _valor_presente(valor):
            unicos.setdefault(_clave_normalizada(valor), str(valor).strip())
    return sorted(unicos.values(), key=_clave_normalizada)


def _valores_compatibles(valores: Iterable[str]) -> bool:
    return len({_clave_normalizada(v) for v in valores if _valor_presente(v)}) <= 1


class EstadoViaje(str, Enum):
    CONFIRMADO = "CONFIRMADO"
    REQUIERE_REVISION = "REQUIERE_REVISION"


class MotivoRevision(str, Enum):
    FECHA_NO_COMPATIBLE_DESKTOP = "FECHA_NO_COMPATIBLE_DESKTOP"
    CONFLICTO_FECHA = "CONFLICTO_FECHA"
    CONFLICTO_CHOFER = "CONFLICTO_CHOFER"
    CONFLICTO_RUT_CHOFER = "CONFLICTO_RUT_CHOFER"
    CONFLICTO_CLIENTE = "CONFLICTO_CLIENTE"
    CONFLICTO_OBRA_DESTINO = "CONFLICTO_OBRA_DESTINO"
    CONFLICTO_ORIGEN = "CONFLICTO_ORIGEN"
    CONFLICTO_PATENTE_TRACTO = "CONFLICTO_PATENTE_TRACTO"
    CONFLICTO_PATENTE_RAMPLA = "CONFLICTO_PATENTE_RAMPLA"


@dataclass(frozen=True)
class DocumentoViaje:
    archivo: str
    numero_guia: str
    cliente: str
    obra_destino: str
    origen: str
    chofer: str
    chofer_original: str
    rut_chofer: str
    patente_tracto: str
    patente_rampla: str
    descripcion_material: str
    tipo_carga: str
    evidencia: dict[str, str]


@dataclass
class Viaje:
    viaje_id: str
    numero_transporte: str
    fecha: str
    documentos: list[DocumentoViaje] = field(default_factory=list)
    estado: EstadoViaje = EstadoViaje.CONFIRMADO
    motivos_revision: list[MotivoRevision] = field(default_factory=list)
    fecha_creacion: str = ""

    @property
    def numeros_guia(self) -> list[str]:
        return _valores_unicos(d.numero_guia for d in self.documentos)

    @property
    def clientes(self) -> list[str]:
        return _valores_unicos(d.cliente for d in self.documentos)

    @property
    def obras_destino(self) -> list[str]:
        return _valores_unicos(d.obra_destino for d in self.documentos)

    @property
    def origenes(self) -> list[str]:
        return _valores_unicos(d.origen for d in self.documentos)

    @property
    def choferes(self) -> list[str]:
        return _valores_unicos(d.chofer for d in self.documentos)

    @property
    def ruts_chofer(self) -> list[str]:
        return _valores_unicos(d.rut_chofer for d in self.documentos)

    @property
    def patentes_tracto(self) -> list[str]:
        return _valores_unicos(d.patente_tracto for d in self.documentos)

    @property
    def patentes_rampla(self) -> list[str]:
        return _valores_unicos(d.patente_rampla for d in self.documentos)

    @property
    def materiales(self) -> list[str]:
        return _valores_unicos(d.descripcion_material for d in self.documentos)

    @property
    def tipos_carga(self) -> list[str]:
        return _valores_unicos(d.tipo_carga for d in self.documentos)

    def a_dict(self) -> dict[str, object]:
        return {
            "viaje_id": self.viaje_id,
            "numero_transporte": self.numero_transporte,
            "fecha": self.fecha,
            "estado": self.estado.value,
            "motivos_revision": [m.value for m in self.motivos_revision],
            "documentos": [d.archivo for d in self.documentos],
            "numeros_guia": self.numeros_guia,
            "clientes": self.clientes,
            "obras_destino": self.obras_destino,
            "origenes": self.origenes,
            "choferes": self.choferes,
            "ruts_chofer": self.ruts_chofer,
            "patentes_tracto": self.patentes_tracto,
            "patentes_rampla": self.patentes_rampla,
            "materiales": self.materiales,
            "tipos_carga": self.tipos_carga,
            "evidencias_documentos": [d.evidencia for d in self.documentos],
            "fecha_creacion": self.fecha_creacion,
        }


def _documento_desde_fila(
    fila: Mapping[str, object],
    *,
    normalizador_chofer: Callable[[str], str] | None,
) -> DocumentoViaje:
    evidencia = {str(clave): str(valor or "") for clave, valor in fila.items()}
    chofer_original = str(fila.get("chofer", "")).strip()
    chofer = (
        normalizador_chofer(chofer_original)
        if normalizador_chofer and _valor_presente(chofer_original)
        else chofer_original
    )
    origen = str(fila.get("origen", fila.get("planta_origen", "")))
    return DocumentoViaje(
        archivo=str(fila.get("archivo", "")).strip(),
        numero_guia=str(fila.get("numero_guia", "")).strip(),
        cliente=str(fila.get("cliente", "")).strip(),
        obra_destino=str(fila.get("obra_destino", "")).strip(),
        origen=origen.strip(),
        chofer=str(chofer).strip(),
        chofer_original=chofer_original,
        rut_chofer=str(fila.get("rut_chofer", "")).strip(),
        patente_tracto=str(fila.get("patente_tracto", "")).strip(),
        patente_rampla=str(fila.get("patente_rampla", "")).strip(),
        descripcion_material=str(fila.get("descripcion_material", "")).strip(),
        tipo_carga=str(fila.get("tipo_carga", "")).strip(),
        evidencia=evidencia,
    )


def _deduplicar_filas(
    filas: Iterable[Mapping[str, object]],
) -> list[Mapping[str, object]]:
    """Evita duplicados exactos y fija un orden independiente de la entrada."""
    unicas: dict[tuple[tuple[str, str], ...], Mapping[str, object]] = {}
    for fila in filas:
        huella = tuple(
            sorted((str(k), str(v or "")) for k, v in fila.items())
        )
        unicas.setdefault(huella, fila)
    return [unicas[huella] for huella in sorted(unicas)]


def agrupar_viajes(
    filas: Iterable[Mapping[str, object]],
    *,
    normalizador_chofer: Callable[[str], str] | None = None,
    reloj: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    generador_id: Callable[[], str] | None = None,
) -> tuple[list[Viaje], list[dict[str, object]]]:
    """Agrupa por transporte y conserva toda contradicción como revisión."""
    grupos: dict[str, list[Mapping[str, object]]] = {}
    sin_transporte: list[dict[str, object]] = []

    for fila in _deduplicar_filas(filas):
        transporte = str(fila.get("numero_transporte", "")).strip()
        if not _transporte_valido(transporte):
            sin_transporte.append(dict(fila))
            continue
        grupos.setdefault(_clave_normalizada(transporte), []).append(fila)

    viajes: list[Viaje] = []
    ahora = reloj().isoformat()
    for clave_transporte, filas_grupo in grupos.items():
        documentos = [
            _documento_desde_fila(
                fila, normalizador_chofer=normalizador_chofer
            )
            for fila in filas_grupo
        ]
        fechas_originales = [str(f.get("fecha", "")).strip() for f in filas_grupo]
        fechas_desktop = [_fecha_para_desktop(valor) for valor in fechas_originales]
        campos_conflicto = (
            (MotivoRevision.CONFLICTO_FECHA, [valor or "" for valor in fechas_desktop]),
            (MotivoRevision.CONFLICTO_CHOFER, [d.chofer for d in documentos]),
            (MotivoRevision.CONFLICTO_RUT_CHOFER, [d.rut_chofer for d in documentos]),
            (MotivoRevision.CONFLICTO_CLIENTE, [d.cliente for d in documentos]),
            (MotivoRevision.CONFLICTO_OBRA_DESTINO, [d.obra_destino for d in documentos]),
            (MotivoRevision.CONFLICTO_ORIGEN, [d.origen for d in documentos]),
            (MotivoRevision.CONFLICTO_PATENTE_TRACTO, [d.patente_tracto for d in documentos]),
            (MotivoRevision.CONFLICTO_PATENTE_RAMPLA, [d.patente_rampla for d in documentos]),
        )
        motivos = [
            motivo for motivo, valores in campos_conflicto
            if not _valores_compatibles(valores)
        ]
        if any(
            _valor_presente(original) and normalizada is None
            for original, normalizada in zip(fechas_originales, fechas_desktop)
        ):
            motivos.append(MotivoRevision.FECHA_NO_COMPATIBLE_DESKTOP)
        fecha = next((valor for valor in fechas_desktop if valor), "")
        identificador = (
            generador_id()
            if generador_id
            else str(uuid5(NAMESPACE_URL, f"atlas:viaje:{clave_transporte}"))
        )
        viajes.append(
            Viaje(
                viaje_id=identificador,
                numero_transporte=str(filas_grupo[0]["numero_transporte"]).strip(),
                fecha=fecha,
                documentos=documentos,
                estado=(
                    EstadoViaje.REQUIERE_REVISION
                    if motivos
                    else EstadoViaje.CONFIRMADO
                ),
                motivos_revision=motivos,
                fecha_creacion=ahora,
            )
        )
    return viajes, sin_transporte
