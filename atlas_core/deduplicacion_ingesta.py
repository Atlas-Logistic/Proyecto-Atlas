"""Núcleo puro y no integrado para deduplicar ingestas documentales.

No lee directorios, no publica decisiones y no modifica Mobile/Desktop. La
confirmación humana se representa en el ledger; jamás se infiere sólo desde
una huella perceptual o desde guía/transporte.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from hashlib import sha256
from io import BytesIO
import re
from typing import Iterable, Mapping

from PIL import Image, ImageOps, UnidentifiedImageError


VERSION_HASH_PERCEPTUAL = "dhash-v1"


class ClasificacionDuplicado(str, Enum):
    NUEVO = "NUEVO"
    DUPLICADO_EXACTO = "DUPLICADO_EXACTO"
    CANDIDATO_DUPLICADO = "CANDIDATO_DUPLICADO"
    DUPLICADO_CONFIRMADO = "DUPLICADO_CONFIRMADO"


def sha256_binario(contenido: bytes) -> str:
    """Huella estable de los bytes recibidos, independiente de su nombre."""
    return sha256(contenido).hexdigest()


@dataclass(frozen=True)
class HuellaPerceptual:
    version: str
    valor_hex: str


def hash_perceptual(contenido: bytes) -> HuellaPerceptual:
    """Calcula dHash v1 de 64 bits sobre imagen orientada y en escala de grises."""
    try:
        with Image.open(BytesIO(contenido)) as origen:
            imagen = ImageOps.exif_transpose(origen).convert("L").resize((9, 8))
            # Pillow 14 retirará ``getdata``; se conserva el fallback para
            # instalaciones antiguas que Atlas todavía pueda tener.
            obtener_pixeles = getattr(imagen, "get_flattened_data", imagen.getdata)
            pixeles = list(obtener_pixeles())
    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError("contenido no es una imagen válida para hash perceptual") from exc
    bits = 0
    for fila in range(8):
        inicio = fila * 9
        for columna in range(8):
            bits = (bits << 1) | int(pixeles[inicio + columna] > pixeles[inicio + columna + 1])
    return HuellaPerceptual(VERSION_HASH_PERCEPTUAL, f"{bits:016x}")


def distancia_perceptual(a: HuellaPerceptual, b: HuellaPerceptual) -> int | None:
    """Distancia Hamming; versiones distintas son deliberadamente incomparables."""
    if a.version != b.version:
        return None
    try:
        return (int(a.valor_hex, 16) ^ int(b.valor_hex, 16)).bit_count()
    except ValueError as exc:
        raise ValueError("huella perceptual hexadecimal inválida") from exc


@dataclass(frozen=True)
class EvidenciaIngesta:
    ingesta_id: str
    nombre_archivo: str
    imagen_sha256: str
    numero_guia: str = ""
    numero_transporte: str = ""
    perceptual: HuellaPerceptual | None = None


@dataclass(frozen=True)
class EntradaLedgerIngesta:
    ingesta_id: str
    nombre_archivo: str
    imagen_sha256: str
    clasificacion: ClasificacionDuplicado
    numero_guia: str = ""
    numero_transporte: str = ""
    perceptual: HuellaPerceptual | None = None
    ingesta_canonica_id: str = ""
    motivo: str = ""

    def a_dict(self) -> dict[str, object]:
        salida = asdict(self)
        salida["clasificacion"] = self.clasificacion.value
        return salida


def validar_entrada_ledger(entrada: EntradaLedgerIngesta) -> None:
    if not entrada.ingesta_id.strip() or not entrada.nombre_archivo.strip():
        raise ValueError("ingesta_id y nombre_archivo son obligatorios")
    if len(entrada.imagen_sha256) != 64 or any(c not in "0123456789abcdef" for c in entrada.imagen_sha256.lower()):
        raise ValueError("imagen_sha256 inválido")
    if entrada.perceptual is not None:
        if not entrada.perceptual.version or not entrada.perceptual.valor_hex:
            raise ValueError("huella perceptual incompleta")
        int(entrada.perceptual.valor_hex, 16)
    requiere_canonica = entrada.clasificacion in {
        ClasificacionDuplicado.DUPLICADO_EXACTO,
        ClasificacionDuplicado.DUPLICADO_CONFIRMADO,
    }
    if requiere_canonica and not entrada.ingesta_canonica_id.strip():
        raise ValueError("un duplicado confirmado requiere ingesta canónica")
    if entrada.ingesta_canonica_id == entrada.ingesta_id:
        raise ValueError("una ingesta no puede referenciarse a sí misma")


def validar_ledger_ingestas(entradas: Iterable[EntradaLedgerIngesta]) -> None:
    lista = list(entradas)
    ids = {entrada.ingesta_id for entrada in lista}
    if len(ids) != len(lista):
        raise ValueError("ingesta_id duplicado en ledger")
    for entrada in lista:
        validar_entrada_ledger(entrada)
        if entrada.ingesta_canonica_id and entrada.ingesta_canonica_id not in ids:
            raise ValueError("la ingesta canónica no existe en el ledger")


def entrada_ledger_desde_dict(valor: Mapping[str, object]) -> EntradaLedgerIngesta:
    """Adaptador de lectura; no accede a disco ni tolera estados ambiguos."""
    perceptual_cruda = valor.get("perceptual")
    perceptual = None
    if perceptual_cruda is not None:
        if not isinstance(perceptual_cruda, Mapping):
            raise ValueError("perceptual debe ser objeto o null")
        perceptual = HuellaPerceptual(
            version=str(perceptual_cruda.get("version", "")),
            valor_hex=str(perceptual_cruda.get("valor_hex", "")),
        )
    try:
        clasificacion = ClasificacionDuplicado(str(valor.get("clasificacion", "")))
    except ValueError as exc:
        raise ValueError("clasificacion de ledger inválida") from exc
    entrada = EntradaLedgerIngesta(
        ingesta_id=str(valor.get("ingesta_id", "")),
        nombre_archivo=str(valor.get("nombre_archivo", "")),
        imagen_sha256=str(valor.get("imagen_sha256", "")),
        clasificacion=clasificacion,
        numero_guia=str(valor.get("numero_guia", "")),
        numero_transporte=str(valor.get("numero_transporte", "")),
        perceptual=perceptual,
        ingesta_canonica_id=str(valor.get("ingesta_canonica_id", "")),
        motivo=str(valor.get("motivo", "")),
    )
    validar_entrada_ledger(entrada)
    return entrada


def clasificar_ingesta(
    candidata: EvidenciaIngesta,
    existentes: Iterable[EvidenciaIngesta],
    *, umbral_perceptual: int = 6,
) -> ClasificacionDuplicado:
    """Clasifica sin promover candidatos a duplicado confirmado.

    Una coincidencia binaria es concluyente. Una cercanía perceptual sólo
    propone revisión; guía y transporte sin evidencia visual no cambian un
    documento a duplicado.
    """
    if umbral_perceptual < 0:
        raise ValueError("umbral_perceptual no puede ser negativo")
    for existente in existentes:
        if candidata.imagen_sha256 == existente.imagen_sha256:
            return ClasificacionDuplicado.DUPLICADO_EXACTO
    if candidata.perceptual is None:
        return ClasificacionDuplicado.NUEVO
    for existente in existentes:
        if existente.perceptual is None:
            continue
        distancia = distancia_perceptual(candidata.perceptual, existente.perceptual)
        if distancia is not None and distancia <= umbral_perceptual:
            return ClasificacionDuplicado.CANDIDATO_DUPLICADO
    return ClasificacionDuplicado.NUEVO


def clasificar_reingesta_documental(
    *, numero_guia: object, numero_transporte: object,
    identidades_existentes: Iterable[tuple[object, object]],
) -> ClasificacionDuplicado:
    """Detecta una reingesta sólo por identidad documental completa y válida.

    Es independiente de hashes perceptuales y de la capa de ingreso. Guías
    hermanas comparten transporte legítimamente y una guía con transporte
    contradictorio debe seguir el flujo normal.
    """
    guia = str(numero_guia or "").strip()
    transporte = str(numero_transporte or "").strip()
    if not re.fullmatch(r"\d{5,8}", guia) or not re.fullmatch(r"\d{10}", transporte):
        return ClasificacionDuplicado.NUEVO
    for guia_existente, transporte_existente in identidades_existentes:
        if guia == str(guia_existente or "").strip() and transporte == str(transporte_existente or "").strip():
            return ClasificacionDuplicado.DUPLICADO_CONFIRMADO
    return ClasificacionDuplicado.NUEVO
