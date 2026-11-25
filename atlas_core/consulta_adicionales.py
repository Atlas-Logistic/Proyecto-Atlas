"""Índice de observaciones operacionales por viaje (adicionales, motivos y lugares).

No interpreta preguntas: eso es trabajo exclusivo de
`interpretador_consultas` (un solo intérprete). Este módulo sólo lee el
registro canónico de eventos (`operacion/actual/eventos_operacionales.json`)
y proyecta, por viaje del reporte, lo que el ejecutor único
(`consultas_atlas.ejecutar_consulta_atlas`) necesita para aplicar los
filtros `observacion`, `adicional` y `adicional_estado` y la métrica
`SUM_ADICIONAL`:

- texto normalizado de todas las observaciones activas del viaje (Mobile y
  correcciones humanas registradas por B1);
- estado del adicional: CONFIRMADO (monto inequívoco registrado, o monto
  aprobado por una persona) o PENDIENTE (la observación indica un adicional
  -- la palabra, un retiro/carga fuera de AZA o un importe -- pero el monto
  no quedó registrado de forma inequívoca);
- montos confirmados (sin duplicar el mismo importe repetido en varias
  observaciones del mismo viaje) y monto declarado de los pendientes.

Nunca infiere un monto: un pendiente sigue pendiente aunque el chofer
escriba una cifra en texto libre (se informa como "declarado").
"""
from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Mapping, Sequence

from atlas_core.consultas_atlas import (
    ADICIONAL_CONFIRMADO, ADICIONAL_PENDIENTE, COLUMNA_ADICIONAL_DECLARADO, COLUMNA_ADICIONAL_ESTADO,
    COLUMNA_ADICIONAL_MONTOS, COLUMNA_ADICIONAL_ORIGEN, COLUMNA_ADICIONAL_OTRAS_PENDIENTES, COLUMNA_OBSERVACIONES, COLUMNA_OBSERVACIONES_TEXTO,
    normalizar_observacion,
)

RUTA_EVENTOS = Path("operacion/actual/eventos_operacionales.json")


class FuenteObservacionesNoDisponible(Exception):
    """El registro no existe, es ilegible o contradictorio: nunca se
    responde como si no hubiera observaciones."""


PALABRA_ADICIONAL = r"\bADI(?:C|S|CC|SC|Z)IONAL(?:ES)?\b"
# Importe con forma monetaria inequívoca dentro de una nota libre: con $,
# separador de miles o "mil/lucas". Nunca kilos, kilómetros ni horas.
_IMPORTE_LIBRE = re.compile(
    r"(?<![\d.])(?:\$\s*\d{1,3}(?:[.]\d{3})+|\$\s*\d{4,}|\d{1,3}(?:[.]\d{3})+|\d{1,3}\s*(?:MIL|LUCAS))\b"
    r"(?!\s*(?:KG|KILOS?|KMS?|TON|TONELADAS?|MTS?|METROS?|HRS?|HORAS?)\b)")
_FUERA_DE_AZA = re.compile(r"\bA?FUERA\s+DE\s+AZA\b")
_NEGACION = re.compile(r"\b(?:SIN|NO(?:\s+\w+){0,3})\s+" + PALABRA_ADICIONAL[2:])
_POR_DOCUMENTO = r"\b(?:POR|CADA)\s+(?:GUIA|DOCUMENTO|FOTO)\b"


# --- Helpers compartidos con la escritura de adicionales de B1
# (acciones_operacionales/b1_operador): se conservan sin cambios. ---
def _normalizar(texto):
    return ''.join(c for c in unicodedata.normalize('NFKD', str(texto).upper()) if not unicodedata.combining(c))


_MONTO = r'\$?\s*(?:\d{1,3}(?:[.]\d{3})+|\d+)(?:\s*(?:MIL|LUCAS|PESOS))?'

def _monto(texto):
    t = re.sub(r'\s+', ' ', texto.strip())
    m = re.fullmatch(r'\$?\s*(\d{1,3}(?:[.]\d{3})+|\d+)(?:\s*(MIL|LUCAS|PESOS))?', t)
    if not m:
        return None
    valor = int(m.group(1).replace('.', ''))
    if m.group(2) in ('MIL', 'LUCAS'):
        valor *= 1000
    return valor


# Linea canonica que B1 escribe con motivo libre: "ESTE VIAJE TIENE ADICIONAL DE
# $15.000 POR SEGUNDA VUELTA DEL VIERNES 23/10/2026". Las cifras del motivo
# (fechas) no son importes; B1 nunca guarda un motivo con otro importe, otro
# adicional o un monto por guia, y si una nota los trae no se neutraliza.
_LINEA_CANONICA_CON_MOTIVO = re.compile(
    r'(ESTE VIAJE TIENE ADICIONAL DE \$\d{1,3}(?:[.]\d{3})*) (?P<motivo>(?:POR|DEBIDO A|CORRESPONDIENTE A) .+)')


def _sin_motivo_canonico(nota):
    """Nota normalizada sin el motivo de sus lineas canonicas de adicional."""
    lineas = []
    for linea in nota.split('\n'):
        m = _LINEA_CANONICA_CON_MOTIVO.fullmatch(linea.strip())
        motivo = m.group('motivo') if m else ''
        if m and not re.search(r'\$|\b(?:MIL|LUCAS|PESOS|ADICIONAL(?:ES)?)\b|\b(?:POR|CADA)\s+(?:GUIA|DOCUMENTO|FOTO)\b',
                               motivo):
            linea = m.group(1)
        lineas.append(linea)
    return '\n'.join(lineas)


def monto_a_entero(texto: str) -> int | None:
    return _monto(str(texto))


def clasificar_observacion(evento: Mapping[str, object]) -> tuple[str, int | None, int | None]:
    """(estado, monto_confirmado, monto_declarado) de UNA observación.

    estado: '' (no indica adicional), CONFIRMADO o PENDIENTE."""
    aprobado = evento.get("monto_aprobado")
    if isinstance(aprobado, (int, float)) and not isinstance(aprobado, bool) and aprobado > 0:
        return ADICIONAL_CONFIRMADO, int(aprobado), None
    nota = normalizar_observacion(evento.get("nota") or "")
    if not nota:
        return "", None, None
    menciones = len(re.findall(PALABRA_ADICIONAL, nota))
    if menciones == 1 and _NEGACION.search(nota):
        return "", None, None
    limpio = _sin_motivo_canonico(nota)
    importes = _IMPORTE_LIBRE.findall(limpio)
    if not menciones and not importes and not _FUERA_DE_AZA.search(nota):
        return "", None, None
    declarado = monto_a_entero(importes[0]) if len(importes) == 1 else None
    if evento.get("naturaleza") != "MARCA_VIAJE" or re.search(_POR_DOCUMENTO, limpio):
        return ADICIONAL_PENDIENTE, None, None
    hallados = re.findall(PALABRA_ADICIONAL + r"\s+(?:DE|POR|ES DE)\s*(" + _MONTO + r")", limpio)
    if len(hallados) == 1 and menciones == 1:
        resto = limpio.replace(hallados[0], "", 1)
        if not re.search(r"\d", resto):
            return ADICIONAL_CONFIRMADO, monto_a_entero(hallados[0]), None
    return ADICIONAL_PENDIENTE, None, declarado


def _origen(evento: Mapping[str, object]) -> str:
    procedencias = evento.get("procedencias") if isinstance(evento.get("procedencias"), list) else []
    primera = procedencias[0] if procedencias and isinstance(procedencias[0], dict) else {}
    origen = str(primera.get("origen") or "").upper()
    if origen.startswith("MOBILE"):
        return "Mobile"
    if origen:
        return "Registro humano (B1)"
    return "Registro"


def leer_eventos(raiz_atlas: str | Path | None) -> list[dict]:
    no_disponible = ("No puedo verificar observaciones ni adicionales: no está disponible el registro "
                     "de observaciones operacionales.")
    if raiz_atlas is None:
        raise FuenteObservacionesNoDisponible(no_disponible)
    ruta = Path(raiz_atlas) / RUTA_EVENTOS
    if not ruta.is_file():
        raise FuenteObservacionesNoDisponible(no_disponible)
    try:
        documento = json.loads(ruta.read_text(encoding="utf-8-sig"))
        if not isinstance(documento, dict) or documento.get("schema_version") != 1 or not isinstance(documento.get("eventos"), list):
            raise ValueError("registro incompatible")
        eventos = documento["eventos"]
        if not all(isinstance(e, dict) for e in eventos):
            raise ValueError("evento invalido")
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise FuenteObservacionesNoDisponible(
            "No puedo verificar observaciones ni adicionales: el registro de observaciones no está disponible "
            "o es ilegible.") from error
    return eventos


def _transportes_de(fila: Mapping[str, str]) -> set[str]:
    return {t.strip() for t in (str(fila.get("numero_transporte") or ""), *str(fila.get("transportes_aza") or "").split("|"))
            if t.strip()}


def indexar_observaciones(viajes: Sequence[Mapping[str, str]], eventos: Sequence[Mapping[str, object]]):
    """Devuelve `(filas, diagnostico)`: una fila por viaje único del
    reporte con las columnas virtuales de observaciones, y cuántas
    observaciones con adicional no se pudieron vincular a un viaje."""
    por_id: dict[str, dict] = {}
    orden: list[str] = []
    por_transporte: dict[str, set[str]] = {}
    for v in viajes:
        vid = str(v.get("viaje_id") or "").strip()
        if not vid:
            raise FuenteObservacionesNoDisponible("No puedo vincular observaciones: el reporte tiene viajes sin identidad.")
        if vid in por_id:
            if {k: x for k, x in por_id[vid].items()} != dict(v):
                raise FuenteObservacionesNoDisponible(
                    "No puedo contar viajes únicos: el reporte tiene identidades contradictorias.")
            continue
        por_id[vid] = dict(v)
        orden.append(vid)
        for t in _transportes_de(v):
            por_transporte.setdefault(t, set()).add(vid)

    vistos: dict[str, Mapping[str, object]] = {}
    textos: dict[str, list[str]] = {}
    notas: dict[str, list[str]] = {}
    confirmados: dict[str, dict[int, str]] = {}
    pendientes: dict[str, list[tuple[int | None, str]]] = {}
    sin_vinculo = 0
    for evento in eventos:
        if evento.get("estado") != "ACTIVO":
            continue
        evento_id = str(evento.get("evento_id") or "").strip()
        if evento_id:
            anterior = vistos.get(evento_id)
            if anterior is not None:
                if anterior != evento:
                    raise FuenteObservacionesNoDisponible(
                        "El registro contiene eventos contradictorios con la misma identidad; "
                        "no puedo responder con fiabilidad.")
                continue
            vistos[evento_id] = evento
        nota = str(evento.get("nota") or "").strip()
        estado, monto, declarado = clasificar_observacion(evento)
        if not nota and not estado:
            continue
        vid = str(evento.get("viaje_id") or "").strip()
        transporte = str(evento.get("numero_transporte") or "").strip()
        if not vid:
            candidatos = por_transporte.get(transporte, set())
            vid = next(iter(candidatos)) if len(candidatos) == 1 else ""
        fila = por_id.get(vid)
        if fila is None or (transporte and transporte not in _transportes_de(fila)):
            if estado:
                sin_vinculo += 1
            continue
        if nota:
            textos.setdefault(vid, []).append(normalizar_observacion(nota))
            notas.setdefault(vid, []).append(" ".join(nota.split()))
        if estado == ADICIONAL_CONFIRMADO:
            confirmados.setdefault(vid, {}).setdefault(monto, _origen(evento))
        elif estado == ADICIONAL_PENDIENTE:
            pendientes.setdefault(vid, []).append((declarado, _origen(evento)))

    filas = []
    for vid in orden:
        fila = por_id[vid]
        fila[COLUMNA_OBSERVACIONES] = "\n".join(textos.get(vid, []))
        fila[COLUMNA_OBSERVACIONES_TEXTO] = " / ".join(notas.get(vid, []))
        fila[COLUMNA_ADICIONAL_ESTADO] = fila[COLUMNA_ADICIONAL_MONTOS] = ""
        fila[COLUMNA_ADICIONAL_DECLARADO] = fila[COLUMNA_ADICIONAL_ORIGEN] = ""
        fila[COLUMNA_ADICIONAL_OTRAS_PENDIENTES] = ""
        if vid in confirmados:
            fila[COLUMNA_ADICIONAL_ESTADO] = ADICIONAL_CONFIRMADO
            fila[COLUMNA_ADICIONAL_MONTOS] = "|".join(str(m) for m in sorted(confirmados[vid]))
            fila[COLUMNA_ADICIONAL_ORIGEN] = ", ".join(sorted(set(confirmados[vid].values())))
            fila[COLUMNA_ADICIONAL_OTRAS_PENDIENTES] = str(len(pendientes.get(vid, []))) if vid in pendientes else ""
        elif vid in pendientes:
            declarados = {d for d, _ in pendientes[vid] if d}
            fila[COLUMNA_ADICIONAL_ESTADO] = ADICIONAL_PENDIENTE
            fila[COLUMNA_ADICIONAL_DECLARADO] = str(next(iter(declarados))) if len(declarados) == 1 else ""
            fila[COLUMNA_ADICIONAL_ORIGEN] = ", ".join(sorted({o for _, o in pendientes[vid]}))
        filas.append(fila)
    return filas, {"observaciones_adicional_sin_vinculo": sin_vinculo, "eventos": len(eventos)}


def vocabulario_observaciones(filas: Sequence[Mapping[str, str]]) -> frozenset[str]:
    """Palabras presentes en las observaciones vinculadas: el intérprete
    las usa para reconocer términos de observación (lugar, motivo)."""
    palabras: set[str] = set()
    for fila in filas:
        palabras.update(re.findall(r"[A-Z0-9]+", str(fila.get(COLUMNA_OBSERVACIONES) or "")))
    return frozenset(palabras)
