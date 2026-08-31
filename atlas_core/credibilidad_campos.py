"""Bloque C1 -- capa GENERAL de credibilidad de campos documentales.

EXTRACCIÓN -> VALIDACIÓN DE CREDIBILIDAD -> si confiable: usar
normalmente -> si dudoso: escalar a B1 (herramienta DOCUMENTOS_
RELACIONADOS, ya universal desde el Bloque U1) -> si B1 corrobora:
usar -> si B1 no corrobora: dejar sin resolver/revisión. Nunca publica
como dato limpio algo estructuralmente absurdo o contaminado por otra
sección del documento -- pero tampoco inventa un reemplazo: el valor
documental crudo SIEMPRE se conserva, sólo cambia si queda marcado
para revisión.

Reutiliza infraestructura general ya existente, nunca duplicada:
- `atlas_core.extractor.etiquetas_estructurales_documento()` -- el
  mismo vocabulario de etiquetas de OTRAS secciones de una guía de
  despacho chilena que ya usa `_despachar_a_lineal_contaminado`/
  `_extraer_despachar_a_geometrico` para DESPACHAR A, generalizado
  aquí a material/obra destino/cliente/dirección.
- `atlas_core.validadores.validar_rut_chileno` -- mismo validador de
  formato RUT que usa el resto de Atlas, nunca un segundo regex de RUT
  paralelo.
- `atlas_core.procesamiento_masivo.PESO_KG_MINIMO_PLAUSIBLE`/
  `PESO_KG_MAXIMO_PLAUSIBLE` -- el rango de EXTRACCIÓN ya existente
  (Bloque O1: rechaza como "No encontrado" un peso fuera de 1-60000kg,
  sanidad de formato). Este módulo agrega un rango más angosto,
  DISTINTO en propósito: "operacionalmente típico para una guía de
  despacho de material a granel" -- un peso legible pero fuera de ese
  rango se conserva y se marca SOSPECHOSO, nunca se reemplaza.

Ningún umbral ni vocabulario aquí referencia una guía, empresa,
transporte, patente o cliente concretos -- señales estructurales
generales (longitud, conteo de etiquetas ajenas, formato, fragmentos)
aplicables a cualquier documento futuro, nunca un parche puntual."""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Iterable

from atlas_core.extractor import _texto_simple, etiquetas_estructurales_documento
from atlas_core.modelos import EstadoValidacion
from atlas_core.validadores import validar_rut_chileno


class NivelCredibilidad(str, Enum):
    CONFIABLE = "CONFIABLE"
    DUDOSO = "DUDOSO"
    INVALIDO = "INVALIDO"


@dataclass(frozen=True)
class ResultadoCredibilidad:
    """`motivo`: código trazable (mismo vocabulario que
    `MotivoRevisionDocumento`, cuando corresponde). `senales`: detalle
    auditable de qué disparó el nivel -- nunca oculto, siempre
    reconstruible."""

    nivel: NivelCredibilidad
    motivo: str = ""
    senales: tuple[str, ...] = ()

    def confiable(self) -> bool:
        return self.nivel == NivelCredibilidad.CONFIABLE


_AUSENTE = {"", "NO ENCONTRADO"}

_PATRON_FECHA_TOKEN = re.compile(r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b")
_PATRON_RUT_TOKEN = re.compile(r"\b\d{1,2}\.?\d{3}\.?\d{3}-[\dkK]\b")


def _etiquetas_ajenas_presentes(texto_simple: str) -> tuple[str, ...]:
    """Etiquetas estructurales (de CUALQUIER otra sección) presentes como
    palabra/frase completa dentro de `texto_simple` -- nunca una
    subcadena parcial (evita que "TRANSPORTE" dispare dentro de una
    palabra más larga que sólo la contiene por casualidad)."""
    encontradas = []
    for etiqueta in etiquetas_estructurales_documento():
        if re.search(r"(?<![A-Z0-9])" + re.escape(etiqueta) + r"(?![A-Z0-9])", texto_simple):
            encontradas.append(etiqueta)
    return tuple(encontradas)


# ---------------------------------------------------------------------
# MATERIAL -- descripción libre, pero nunca un bloque completo de otras
# secciones del documento.
# ---------------------------------------------------------------------

UMBRAL_LONGITUD_MATERIAL_DUDOSO = 90
UMBRAL_LONGITUD_MATERIAL_INVALIDO = 160
MINIMO_ETIQUETAS_AJENAS_INVALIDO = 2

MOTIVO_MATERIAL_CONTAMINADO = "MATERIAL_POSIBLEMENTE_CONTAMINADO"

# `extraer_descripcion_material` puede unir varios ítems reales de un
# mismo documento con " | " (varias medidas/calidades despachadas
# juntas -- observado en producción, p. ej. "ANGULO 25X25X3MM 6M
# A270ES (N) | ANGULO 50X50X5MM 6M A270ES (N) | ..."). La longitud
# TOTAL de ese texto crece con el número de ítems reales, sin que eso
# sea contaminación -- la señal de longitud debe medir cada ítem
# individual (el ítem más largo), nunca el texto ya unido completo.
_SEPARADOR_ITEMS_MATERIAL = "|"


def evaluar_credibilidad_material(valor: object) -> ResultadoCredibilidad:
    """Un material razonable trae descripción/medida/calidad/código/
    dimensiones -- nunca un bloque que mezcla etiquetas de OTRAS
    secciones (fecha de emisión, señor(es), RUT, dirección, comuna,
    transportista, ...) ni una longitud propia de un párrafo completo
    del documento. Varios ítems reales unidos con "|" son legítimos
    (ver `_SEPARADOR_ITEMS_MATERIAL`) -- la longitud se evalúa por
    ítem, nunca sobre el texto ya unido completo."""
    texto = str(valor or "").strip()
    if _texto_simple(texto) in _AUSENTE:
        return ResultadoCredibilidad(NivelCredibilidad.CONFIABLE)

    texto_simple = _texto_simple(texto)
    etiquetas = _etiquetas_ajenas_presentes(texto_simple)
    tiene_rut = bool(_PATRON_RUT_TOKEN.search(texto))
    tiene_fecha = bool(_PATRON_FECHA_TOKEN.search(texto))
    longitud_mayor_item = max(
        (len(item.strip()) for item in texto.split(_SEPARADOR_ITEMS_MATERIAL) if item.strip()),
        default=len(texto),
    )

    senales_fuertes: list[str] = []
    if longitud_mayor_item > UMBRAL_LONGITUD_MATERIAL_INVALIDO:
        senales_fuertes.append("LONGITUD_EXCESIVA")
    if len(etiquetas) >= MINIMO_ETIQUETAS_AJENAS_INVALIDO:
        senales_fuertes.append("ETIQUETAS_DE_OTRAS_SECCIONES:" + ",".join(etiquetas))
    if tiene_rut and tiene_fecha:
        senales_fuertes.append("MEZCLA_RUT_Y_FECHA")
    if senales_fuertes:
        return ResultadoCredibilidad(
            NivelCredibilidad.INVALIDO, motivo=MOTIVO_MATERIAL_CONTAMINADO, senales=tuple(senales_fuertes),
        )

    senales_moderadas: list[str] = []
    if longitud_mayor_item > UMBRAL_LONGITUD_MATERIAL_DUDOSO:
        senales_moderadas.append("LONGITUD_ATIPICA")
    if etiquetas:
        senales_moderadas.append("ETIQUETA_DE_OTRA_SECCION:" + ",".join(etiquetas))
    if senales_moderadas:
        return ResultadoCredibilidad(
            NivelCredibilidad.DUDOSO, motivo=MOTIVO_MATERIAL_CONTAMINADO, senales=tuple(senales_moderadas),
        )
    return ResultadoCredibilidad(NivelCredibilidad.CONFIABLE)


# ---------------------------------------------------------------------
# ENTIDAD (obra_destino / cliente como NOMBRE) -- una etiqueta
# documental genérica o un RUT crudo nunca son, por sí solos, una razón
# social u obra confirmada.
# ---------------------------------------------------------------------

# Sustantivos genéricos de un documento logístico chileno que, SOLOS
# (sin ningún calificador propio), nunca constituyen una razón social u
# obra real -- vocabulario general de dominio, nunca el nombre de una
# empresa/obra concreta.
PALABRAS_GENERICAS_SIN_ENTIDAD = frozenset({
    "TRANSPORTE", "TRANSPORTES", "CLIENTE", "PROVEEDOR", "DESTINO",
    "OBRA", "DESPACHO", "DOCUMENTO", "GUIA", "EMPRESA", "SOCIEDAD",
    "COMPANIA", "SUCURSAL", "BODEGA", "RECEPTOR", "REMITENTE", "OBRAS",
})
LONGITUD_MINIMA_ENTIDAD = 3

MOTIVO_ENTIDAD_ETIQUETA_GENERICA = "VALOR_ES_ETIQUETA_GENERICA_NO_ENTIDAD"
MOTIVO_ENTIDAD_FRAGMENTO_CORTO = "FRAGMENTO_DEMASIADO_CORTO"
MOTIVO_ENTIDAD_RUT_CRUDO = "VALOR_ES_RUT_CRUDO_SIN_RAZON_SOCIAL"


def evaluar_credibilidad_entidad_nombre(valor: object) -> ResultadoCredibilidad:
    """Para campos que deben contener el NOMBRE de una entidad (obra
    destino, cliente) -- nunca una etiqueta documental genérica sola, un
    fragmento demasiado corto para identificar nada, ni un RUT crudo
    haciendo de razón social."""
    texto = str(valor or "").strip()
    if _texto_simple(texto) in _AUSENTE:
        return ResultadoCredibilidad(NivelCredibilidad.CONFIABLE)

    texto_simple = _texto_simple(texto)
    if texto_simple in PALABRAS_GENERICAS_SIN_ENTIDAD:
        return ResultadoCredibilidad(
            NivelCredibilidad.DUDOSO, motivo=MOTIVO_ENTIDAD_ETIQUETA_GENERICA,
            senales=(f"PALABRA_GENERICA:{texto_simple}",),
        )
    if len(texto_simple) < LONGITUD_MINIMA_ENTIDAD:
        return ResultadoCredibilidad(
            NivelCredibilidad.DUDOSO, motivo=MOTIVO_ENTIDAD_FRAGMENTO_CORTO, senales=("LONGITUD_INSUFICIENTE",),
        )
    resultado_rut = validar_rut_chileno(texto)
    if resultado_rut.estado == EstadoValidacion.VALIDO:
        return ResultadoCredibilidad(
            NivelCredibilidad.DUDOSO, motivo=MOTIVO_ENTIDAD_RUT_CRUDO, senales=("FORMATO_RUT",),
        )
    # Señal general (no sólo el RUT ya bien formateado): una razón
    # social/obra es, por naturaleza, TEXTO -- un valor con casi ninguna
    # letra (sólo dígitos/puntuación, más como mucho el dígito
    # verificador "K", típico de un RUT que el OCR desalineó con un
    # espacio de más y ya no calza con el formato estricto) nunca es un
    # nombre de entidad utilizable, corrompido o no. Umbral de 2 letras
    # (nunca 1) para no confundir precisamente ese dígito verificador
    # con "sí es texto". Aplica a cualquier campo de nombre, nunca a un
    # RUT concreto.
    if sum(1 for caracter in texto if caracter.isalpha()) < 2:
        return ResultadoCredibilidad(
            NivelCredibilidad.DUDOSO, motivo=MOTIVO_ENTIDAD_RUT_CRUDO, senales=("SIN_LETRAS_PARECE_RUT_O_NUMERO",),
        )
    return ResultadoCredibilidad(NivelCredibilidad.CONFIABLE)


# ---------------------------------------------------------------------
# DIRECCIÓN / DESTINO -- un fragmento truncado (una sola palabra corta)
# nunca es un destino operacional confirmado.
# ---------------------------------------------------------------------

LONGITUD_MINIMA_FRAGMENTO_DIRECCION = 5

MOTIVO_DESTINO_FRAGMENTO = "DESTINO_FRAGMENTO_TRUNCADO"
MOTIVO_DESTINO_CONTAMINADO = "DESTINO_CONTAMINADO_POR_OTRA_SECCION"


def evaluar_credibilidad_direccion(valor: object) -> ResultadoCredibilidad:
    texto = str(valor or "").strip()
    if _texto_simple(texto) in _AUSENTE:
        return ResultadoCredibilidad(NivelCredibilidad.CONFIABLE)

    texto_simple = _texto_simple(texto)
    tokens = texto_simple.split()
    if len(tokens) <= 1 and len(texto_simple) < LONGITUD_MINIMA_FRAGMENTO_DIRECCION:
        return ResultadoCredibilidad(
            NivelCredibilidad.DUDOSO, motivo=MOTIVO_DESTINO_FRAGMENTO, senales=("UN_SOLO_TOKEN_CORTO",),
        )

    etiquetas = _etiquetas_ajenas_presentes(texto_simple)
    resultado_rut = validar_rut_chileno(texto) if _PATRON_RUT_TOKEN.fullmatch(texto) else None
    if etiquetas or (resultado_rut is not None and resultado_rut.estado == EstadoValidacion.VALIDO):
        senales = tuple(f"ETIQUETA:{e}" for e in etiquetas) or ("FORMATO_RUT",)
        return ResultadoCredibilidad(
            NivelCredibilidad.INVALIDO, motivo=MOTIVO_DESTINO_CONTAMINADO, senales=senales,
        )
    return ResultadoCredibilidad(NivelCredibilidad.CONFIABLE)


# ---------------------------------------------------------------------
# PESO -- legible pero operacionalmente atípico: se conserva, se marca
# sospechoso, nunca se reemplaza por otro valor inventado (promedio,
# heurística, etc.).
# ---------------------------------------------------------------------

# Distinto del rango de EXTRACCIÓN ya existente (`PESO_KG_MINIMO_
# PLAUSIBLE`/`PESO_KG_MAXIMO_PLAUSIBLE` en `procesamiento_masivo.py`,
# 1-60000kg -- sanidad de formato/OCR). Este es más angosto y expresa
# "típico para una guía de despacho de material a granel", nunca una
# guía puntual.
UMBRAL_MINIMO_PESO_OPERACIONALMENTE_TIPICO_KG = 150.0
UMBRAL_MAXIMO_PESO_OPERACIONALMENTE_TIPICO_KG = 45000.0

MOTIVO_PESO_ATIPICO = "PESO_OPERACIONALMENTE_ATIPICO"


def evaluar_credibilidad_peso(peso_kg: object) -> ResultadoCredibilidad:
    texto = str(peso_kg if peso_kg is not None else "").strip()
    if texto in ("", "No encontrado", "No determinada"):
        return ResultadoCredibilidad(NivelCredibilidad.CONFIABLE)
    try:
        valor = float(texto)
    except (TypeError, ValueError):
        # Formato ilegible: no es asunto de esta capa (ya se maneja como
        # "No encontrado" en la extracción) -- nunca se opina sobre algo
        # que ni siquiera parece un número.
        return ResultadoCredibilidad(NivelCredibilidad.CONFIABLE)
    if valor <= 0:
        return ResultadoCredibilidad(NivelCredibilidad.CONFIABLE)
    if (
        valor < UMBRAL_MINIMO_PESO_OPERACIONALMENTE_TIPICO_KG
        or valor > UMBRAL_MAXIMO_PESO_OPERACIONALMENTE_TIPICO_KG
    ):
        return ResultadoCredibilidad(
            NivelCredibilidad.DUDOSO, motivo=MOTIVO_PESO_ATIPICO, senales=(f"PESO_KG={valor:g}",),
        )
    return ResultadoCredibilidad(NivelCredibilidad.CONFIABLE)


# ---------------------------------------------------------------------
# Bloque P1 -- SEPARACIÓN evidencia OCR / dato operacional publicable.
#
# C1 (bloque anterior) sólo marcaba un motivo trazable (`motivos_
# revision_documento`) -- el valor DUDOSO/INVÁLIDO seguía siendo el
# mismo que terminaba publicado en Viajes/reportes, exactamente el
# "error con falsa seguridad" que P1 cierra. `valor_publicable` es el
# ÚNICO punto que decide qué se muestra como dato operacional: nunca
# borra el valor documental (sigue disponible íntegro donde ya vivía
# -- `evidencia`/CSV crudo, ver `atlas_core.gestor_viajes.
# DocumentoViaje.evidencia`), sólo decide si ESE valor puede
# presentarse como limpio, o si corresponde reemplazarlo (en la salida
# publicada, nunca en el dato interno) por uno recuperado de evidencia
# independiente o por `VALOR_NO_DETERMINADO`.
# ---------------------------------------------------------------------

VALOR_NO_DETERMINADO = "NO DETERMINADO"


def valor_publicable(
    valor: object, evaluador: Callable[[object], ResultadoCredibilidad],
    candidatos_recuperacion: Iterable[object] = (),
) -> str:
    """DETECTAR -> INVESTIGAR -> RESOLVER SI HAY EVIDENCIA -> ABSTENERSE
    SI NO (nunca "detectar -> publicar basura + warning"):

    1. Si `valor` ya es CONFIABLE (o está ausente -- la ausencia no es
       asunto de esta función, ver `*_AUSENTE`), se publica tal cual.
    2. Si no, se intenta recuperación determinista con evidencia
       INDEPENDIENTE real: el primer valor de `candidatos_recuperacion`
       (p. ej. el mismo campo en documentos hermanos del mismo viaje/
       transporte -- nunca inventado) que resulte CONFIABLE se publica
       en su lugar. Sólo tiene sentido para campos que son, por
       naturaleza, un hecho compartido del viaje (cliente/obra/destino
       documental) -- nunca para un campo por-documento como el
       material (cada documento puede traer una carga distinta; no se
       le pasan candidatos).
    3. Si ninguna recuperación determinista alcanza, se publica
       `VALOR_NO_DETERMINADO` -- nunca el valor dudoso/inválido crudo.
       (B1, cuando corrobora con evidencia suficientemente fuerte
       -- clasificación A, ver `atlas_ia.orquestador._clasificar_
       propuesta` -- ya escribió el valor operacional directo en el
       propio dataset durante el procesamiento, así que en ese caso
       `valor` mismo ya llega CONFIABLE aquí y cae en el paso 1; esta
       función no vuelve a invocar a B1.)"""
    texto = str(valor or "").strip()
    if texto in _AUSENTE or texto == "No encontrado":
        return texto
    if evaluador(texto).nivel == NivelCredibilidad.CONFIABLE:
        return texto
    for candidato in candidatos_recuperacion:
        candidato_texto = str(candidato or "").strip()
        if not candidato_texto or candidato_texto in _AUSENTE or candidato_texto == "No encontrado":
            continue
        if evaluador(candidato_texto).nivel == NivelCredibilidad.CONFIABLE:
            return candidato_texto
    return VALOR_NO_DETERMINADO
