"""Bloque REPROCESAMIENTO REPARADOR -- reparación focal de un lote de
ingesta ya persistido (caso real: lote de 15 imágenes procesado durante
actividad térmica anormal del equipo -- OCR corrupto en varios campos,
17 decisiones pendientes en 10 tarjetas, ninguna aplicada).

Reutiliza el pipeline REAL de extracción
(`atlas_core.procesamiento_masivo.procesar_archivo`) contra las
imágenes ORIGINALES ya conservadas por Atlas
(`atlas_core.evidencia_documental.resolver_ruta_evidencia`) -- nunca un
segundo motor OCR, nunca una copia paralela de la lógica de extracción.

Garantías estructurales de este módulo (nunca reglas "acuérdate de no
hacer X" -- imposibles por construcción):
- Nunca crea una fila nueva para un documento que ya tiene fila --
  siempre localiza y edita la fila EXISTENTE por `archivo`; sólo agrega
  una fila si el documento NUNCA tuvo una (el caso real de "imagen sin
  transporte reconocible" que ahora sí lo encuentra), y sólo si esa
  identidad guía+transporte no existe ya en el dataset (nunca un
  duplicado).
- Nunca aplica una decisión humana ni registra una entidad/alias nueva
  en catálogo: este módulo JAMÁS llama `aplicar_decision_obra` ni
  `CatalogoXxx.crear` (la única vía real de aprendizaje de catálogo en
  todo Atlas, ver auditoría en el informe de este bloque) -- sólo repara
  columnas del dataset documental y deja que la bandeja de decisiones se
  regenere por el mecanismo canónico ya existente
  (`revalidacion_documental.revalidar_y_regenerar_reporte`).
- Un campo con una decisión humana YA en el ledger
  (`decisiones_aplicadas.json`) nunca se toca, sin excepción --
  reutiliza `_hay_decision_humana_para_campo`, el mismo guardián que ya
  usa el replay de trazas OCR.
- Sólo promueve un campo si HOY tiene un motivo de revisión activo que
  lo marca como degradado (ver `CAMPOS_REPARABLES`) -- un campo ya
  limpio (sin motivo) nunca se toca, nunca se sobrescribe "por si
  acaso"."""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from atlas_core.almacenamiento_portable import bloqueo_sesion
from atlas_core.evidencia_documental import paginas_pdf_procesables, resolver_ruta_evidencia
from atlas_core.extractor import _patente_valida
from atlas_core.ingesta_pdf import (
    identificador_pagina_pdf, proveedor_para_documento, separar_identificador_pagina_pdf,
)
from atlas_core.modelos import EstadoValidacion
from atlas_core.ocr_provider import crear_proveedor_ocr
from atlas_core.procesamiento_masivo import (
    COLUMNAS,
    MotivoRevisionDocumento,
    procesar_archivo,
)
from atlas_core.revalidacion_documental import (
    SEPARADOR_MOTIVOS,
    _anotar_recuperacion_p0,
    _escribir_filas_completas,
    _hay_decision_humana_para_campo,
    _indicadores_documentales_coherentes,
    _leer_filas,
    _metricas_recuperacion_p0,
    revalidar_y_regenerar_reporte,
)
from atlas_core.trazabilidad_ocr import ruta_traza_ocr
from atlas_core.validadores import validar_rut_chileno

_AUSENTES = {"", "No encontrado", "REVISAR", "Ilegible"}
_MOTIVO_GUIA = MotivoRevisionDocumento.GUIA_AUSENTE.value
_MOTIVO_TRANSPORTE = MotivoRevisionDocumento.TRANSPORTE_AUSENTE.value
_MOTIVO_TRANSPORTE_SIN_ETIQUETA = MotivoRevisionDocumento.TRANSPORTE_AUSENTE_SIN_ETIQUETA.value
# Caso real 473326: motivos_revision_documento traía sólo
# "GUIA_AUSENTE | TRANSPORTE_AUSENTE | MATERIAL_AUSENTE |
# DOCUMENTO_DEGRADADO" -- chofer/cliente/patente_tracto ya venían con
# texto (basura OCR: "CRISIOPHER RSTAVAR BPHR NETOS" / "PAODALA 0A" /
# "49W0DA"), así que NINGÚN motivo específico de esos campos se había
# activado en la corrida original (no estaban "ausentes" ni fallaron su
# propio validador estructural -- sólo eran incorrectos). Gating por
# motivo específico por campo, solo, deja esos campos fuera para
# siempre. `DOCUMENTO_DEGRADADO` ya es la señal, EXISTENTE y ya
# generada por el pipeline real (nunca inventada aquí), de que la
# extracción completa del documento no es confiable -- cuando está
# presente, se habilita CUALQUIER campo de `CAMPOS_REPARABLES` para
# promoción (siempre sujeto al ledger y al validador estructural de
# cada campo, sin excepción). Un documento SIN este motivo conserva el
# gating estricto por motivo específico de siempre.
_MOTIVO_DOCUMENTO_DEGRADADO = MotivoRevisionDocumento.DOCUMENTO_DEGRADADO.value

# --- Campos reparables -----------------------------------------------
# Cada entrada: campo -> (motivos que lo marcan degradado hoy,
# validador estructural del valor nuevo). Deliberadamente ACOTADO a los
# campos de identidad/relación que el caso real reportó degradados
# (chofer/cliente/obra/destino/patente/guía/transporte) -- nunca
# material/peso/fecha/horarios, que no formaron parte de la
# degradación reportada y cuya reparación queda fuera de este bloque
# focal (ver informe). Extensible: agregar una entrada aquí nunca
# requiere tocar la lógica de reparación misma.
CAMPOS_REPARABLES: dict[str, tuple[tuple[str, ...], object]] = {
    "numero_guia": ((_MOTIVO_GUIA,), lambda v: bool(re.fullmatch(r"\d{5,9}", v))),
    "numero_transporte": (
        (_MOTIVO_TRANSPORTE, _MOTIVO_TRANSPORTE_SIN_ETIQUETA),
        lambda v: bool(re.fullmatch(r"\d{6,}", v)),
    ),
    "chofer": (
        (MotivoRevisionDocumento.CHOFER_AUSENTE.value, MotivoRevisionDocumento.CHOFER_SIN_CORROBORAR.value),
        lambda v: v not in _AUSENTES,
    ),
    "rut_chofer": (
        (MotivoRevisionDocumento.RUT_CHOFER_INVALIDO.value,),
        lambda v: validar_rut_chileno(v).estado == EstadoValidacion.VALIDO,
    ),
    "cliente": (
        (
            MotivoRevisionDocumento.CLIENTE_AUSENTE.value,
            MotivoRevisionDocumento.CLIENTE_SIN_CORROBORAR.value,
            MotivoRevisionDocumento.CLIENTE_POSIBLEMENTE_INVALIDO.value,
            MotivoRevisionDocumento.CLIENTE_NUEVA_ENTIDAD_NO_CATALOGADA.value,
        ),
        lambda v: v not in _AUSENTES,
    ),
    "rut_cliente": (
        (MotivoRevisionDocumento.RUT_CLIENTE_INVALIDO.value,),
        lambda v: validar_rut_chileno(v).estado == EstadoValidacion.VALIDO,
    ),
    "obra_destino": (
        (
            MotivoRevisionDocumento.OBRA_DESTINO_SIN_CORROBORAR.value,
            MotivoRevisionDocumento.OBRA_DESTINO_POSIBLEMENTE_INVALIDA.value,
        ),
        lambda v: v not in _AUSENTES,
    ),
    "despachar_a_crudo": (
        (
            MotivoRevisionDocumento.DESTINO_FRAGMENTO_TRUNCADO.value,
            MotivoRevisionDocumento.DESTINO_CONTAMINADO_POR_OTRA_SECCION.value,
        ),
        lambda v: v not in _AUSENTES,
    ),
    # Caso real 475256: la fila de material quedó fusionada con el membrete.
    # Sólo con el motivo de contaminación ya activo; la reconciliación
    # vuelve a evaluar la credibilidad y recalcula `tipo_carga`.
    "descripcion_material": (
        (MotivoRevisionDocumento.MATERIAL_POSIBLEMENTE_CONTAMINADO.value,),
        lambda v: v not in _AUSENTES,
    ),
    # Horas AZA: sin motivo propio -- se completan si están ausentes o si el
    # documento está degradado; sólo una hora HH:MM válida se promueve.
    "hora_entrada_aza": ((), lambda v: bool(re.fullmatch(r"\d{1,2}:\d{2}", v))),
    "hora_salida_aza": ((), lambda v: bool(re.fullmatch(r"\d{1,2}:\d{2}", v))),
    "patente_tracto": (
        (MotivoRevisionDocumento.PATENTE_SIN_HOMOLOGAR.value, MotivoRevisionDocumento.PATENTE_AMBIGUA.value),
        lambda v: v in _AUSENTES or _patente_valida(v),
    ),
    "patente_rampla": (
        (MotivoRevisionDocumento.PATENTE_SIN_HOMOLOGAR.value, MotivoRevisionDocumento.PATENTE_AMBIGUA.value),
        lambda v: v in _AUSENTES or _patente_valida(v),
    ),
}

# Bloque O2/REVALIDACIÓN POR TRANSPORTE -- distinto de CAMPOS_REPARABLES:
# esos sólo se reexaminan cuando el documento YA trae un motivo de
# degradación que los marca (evita sobreescribir con ruido de una nueva
# pasada de OCR un campo que ya estaba limpio). Un campo aquí es seguro de
# reexaminar SIEMPRE, sin depender de un motivo previo, porque su propia
# función de extracción ya trae una defensa evidencial estricta y
# DETERMINISTA -- sólo cambia cuando esa función encuentra evidencia real
# (confianza baja + corroboración geométrica independiente para
# `peso_kg`, ver Bloque O2 en `extractor._reexaminar_peso_por_baja_
# confianza`), nunca por variación aleatoria entre dos pasadas de OCR. El
# ledger sigue ganando siempre, igual que en CAMPOS_REPARABLES.
CAMPOS_SIEMPRE_REEXAMINADOS: dict[str, object] = {
    "peso_kg": lambda v: v.isdigit(),
}

# Motivos que el extractor deriva del VALOR de un campo sin ser motivos de
# degradación del propio campo (no habilitan su reparación). Si el campo se
# reemplaza, el motivo describía el valor anterior: sobrevive sólo si la
# reextracción lo vuelve a producir para el valor nuevo (caso real 475256:
# peso 61 -> 28061 arrastraba PESO_OPERACIONALMENTE_ATIPICO).
MOTIVOS_DERIVADOS_POR_CAMPO: dict[str, tuple[str, ...]] = {
    "peso_kg": (MotivoRevisionDocumento.PESO_OPERACIONALMENTE_ATIPICO.value,),
}


def _motivos_de_campo(campo: str) -> tuple[str, ...]:
    motivos_degradacion = CAMPOS_REPARABLES.get(campo, ((), None))[0]
    return tuple(motivos_degradacion) + MOTIVOS_DERIVADOS_POR_CAMPO.get(campo, ())


# --- Lectura previa hecha con el OCR de respaldo ------------------------
# Cuando PaddleOCR no está disponible Atlas lee con EasyOCR (fallback), que
# produce valores sintácticamente válidos pero incorrectos sin activar
# ningún motivo (caso real 475256: cliente "410,U0O"). Si la traza OCR
# vigente del documento demuestra esa lectura de respaldo y la relectura
# actual se hizo efectivamente con PaddleOCR, el documento se trata como
# DOCUMENTO_DEGRADADO (mismo mecanismo, mismas garantías: ledger, valores
# ausentes nunca promueven, validador por campo). Tras aplicar la relectura
# se anota en la fila para no volver a tratarla como degradada.
_BACKEND_OCR_RESPALDO = "EasyOCRProvider"
_BACKEND_OCR_PRINCIPAL = "PaddleOCRProvider"
_CLAVE_RELECTURA_OCR_PRINCIPAL = "relectura_ocr_principal"


def _backend_lectura_almacenada(raiz: Path, fila: Mapping[str, str]) -> str | None:
    """Backend OCR de la traza vigente del documento, o None si no hay
    traza que corresponda inequívocamente a este `archivo`."""
    archivo = str(fila.get("archivo", "")).strip()
    if not archivo:
        return None
    ruta = ruta_traza_ocr(raiz / "operacion" / "trazas_ocr", archivo)
    try:
        traza = json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(traza, Mapping) or (traza.get("imagen") or {}).get("referencia") != archivo:
        return None
    nombre = str(((traza.get("ocr") or {}).get("backend") or {}).get("nombre") or "")
    return nombre.rsplit(".", 1)[-1] or None


def _backend_reextraccion(proveedor_documento: object) -> str | None:
    """Backend que REALMENTE leyó la reextracción: un PaddleOCRProvider que
    se degradó a EasyOCR durante la lectura no cuenta como PaddleOCR."""
    from atlas_core.ocr_provider import PaddleOCRProvider

    if isinstance(proveedor_documento, PaddleOCRProvider):
        return _BACKEND_OCR_RESPALDO if proveedor_documento._degradado_a_easyocr else _BACKEND_OCR_PRINCIPAL
    return type(proveedor_documento).__name__ if proveedor_documento is not None else None


def _lectura_previa_por_ocr_de_respaldo(raiz: Path, fila: Mapping[str, str], proveedor_documento: object) -> bool:
    if _metricas_recuperacion_p0(fila).get(_CLAVE_RELECTURA_OCR_PRINCIPAL):
        return False  # esta relectura ya se aplicó una vez
    return (
        _backend_reextraccion(proveedor_documento) == _BACKEND_OCR_PRINCIPAL
        and _backend_lectura_almacenada(raiz, fila) == _BACKEND_OCR_RESPALDO
    )


def _anotar_relectura_ocr_principal(fila: dict[str, str]) -> None:
    _anotar_recuperacion_p0(fila, _CLAVE_RELECTURA_OCR_PRINCIPAL, {
        "version": 1, "backend_previo": _BACKEND_OCR_RESPALDO, "backend_relectura": _BACKEND_OCR_PRINCIPAL,
    })


def _reparar_campos_documento(
    fila: Mapping[str, str], extraido: Mapping[str, object], aplicaciones: list[Mapping[str, object]],
    *, documento_degradado: bool,
) -> list[CambioCampo]:
    """Compara `fila` (persistida) contra `extraido` (reextracción real vía
    `procesar_archivo`) y devuelve sólo los cambios seguros -- misma lógica
    para cualquier llamador (lote completo o un transporte puntual, ver
    `revalidar_documentos_por_transporte`), nunca duplicada."""
    archivo_id = str(fila.get("archivo", ""))
    motivos_actuales = {
        m.strip() for m in str(fila.get("motivos_revision_documento", "")).split(SEPARADOR_MOTIVOS) if m.strip()
    }
    cambios: list[CambioCampo] = []
    for campo, (motivos_degradacion, es_valido) in CAMPOS_REPARABLES.items():
        # Un campo hoy AUSENTE no es un dato limpio: la reextracción real
        # puede completarlo (nunca sobrescribe un valor presente sin motivo).
        ausente = str(fila.get(campo, "")).strip() in _AUSENTES
        if not documento_degradado and not ausente and not (motivos_actuales & set(motivos_degradacion)):
            continue  # campo hoy limpio y documento no degradado -- nunca se toca
        if _hay_decision_humana_para_campo(aplicaciones, fila=fila, campo=campo):
            continue  # el ledger siempre gana
        valor_nuevo = str(extraido.get(campo, "")).strip()
        valor_actual = str(fila.get(campo, "")).strip()
        if not valor_nuevo or valor_nuevo == valor_actual or not es_valido(valor_nuevo):
            continue
        cambios.append(CambioCampo(archivo_id, str(fila.get("numero_guia", "")), campo, valor_actual, valor_nuevo))
    # El RUT es parte de la identidad del chofer: si esta misma reextracción
    # repara el chofer, su RUT viaja con él -- dejar el anterior mezclaría
    # dos identidades en la fila (caso real 475256: JOSE LAZCANO junto al
    # RUT de un cuerpo mal leído). Mismo ledger y validador de siempre.
    campos_cambiados = {c.campo for c in cambios}
    if "chofer" in campos_cambiados and "rut_chofer" not in campos_cambiados:
        _, rut_valido = CAMPOS_REPARABLES["rut_chofer"]
        rut_nuevo = str(extraido.get("rut_chofer", "")).strip()
        rut_actual = str(fila.get("rut_chofer", "")).strip()
        if (
            rut_nuevo
            and rut_nuevo != rut_actual
            and rut_valido(rut_nuevo)
            and not _hay_decision_humana_para_campo(aplicaciones, fila=fila, campo="rut_chofer")
        ):
            cambios.append(CambioCampo(archivo_id, str(fila.get("numero_guia", "")), "rut_chofer", rut_actual, rut_nuevo))
    # La permanencia se deriva de las horas AZA: si una hora cambia, la
    # permanencia de esa misma reextracción la acompaña.
    if campos_cambiados & {"hora_entrada_aza", "hora_salida_aza"}:
        permanencia_nueva = str(extraido.get("permanencia_minutos", "")).strip()
        permanencia_actual = str(fila.get("permanencia_minutos", "")).strip()
        if (
            permanencia_nueva.isdigit()
            and permanencia_nueva != permanencia_actual
            and not _hay_decision_humana_para_campo(aplicaciones, fila=fila, campo="permanencia_minutos")
        ):
            cambios.append(CambioCampo(
                archivo_id, str(fila.get("numero_guia", "")), "permanencia_minutos", permanencia_actual, permanencia_nueva,
            ))
    for campo, es_valido in CAMPOS_SIEMPRE_REEXAMINADOS.items():
        if _hay_decision_humana_para_campo(aplicaciones, fila=fila, campo=campo):
            continue  # el ledger siempre gana, también aquí
        valor_nuevo = str(extraido.get(campo, "")).strip()
        valor_actual = str(fila.get(campo, "")).strip()
        if not valor_nuevo or valor_nuevo == valor_actual or not es_valido(valor_nuevo):
            continue
        cambios.append(CambioCampo(archivo_id, str(fila.get("numero_guia", "")), campo, valor_actual, valor_nuevo))
    return cambios


def _aplicar_cambios_a_fila(
    fila: dict[str, str], cambios: list[CambioCampo], *, motivos_reextraccion: str = "",
) -> None:
    """Escribe `cambios` en `fila` (en memoria) y recalcula los 3
    indicadores documentales coherentes -- mismo criterio para cualquier
    llamador, nunca duplicado.

    Los motivos de degradación de un campo reemplazado describían el valor
    ANTERIOR. El valor nuevo trae su propia evaluación, hecha por las
    reglas de siempre en la reextracción (`motivos_reextraccion`, la
    columna `motivos_revision_documento` que devolvió `procesar_archivo`):
    si ésta sigue marcando el campo (caso real 474708: la obra corregida
    sigue OBRA_DESTINO_SIN_CORROBORAR), el motivo se conserva; sólo se
    retira cuando el valor nuevo ya no lo tiene."""
    if not cambios:
        return
    motivos_actuales = {
        m.strip() for m in str(fila.get("motivos_revision_documento", "")).split(SEPARADOR_MOTIVOS) if m.strip()
    }
    motivos_valor_nuevo = {
        m.strip() for m in str(motivos_reextraccion or "").split(SEPARADOR_MOTIVOS) if m.strip()
    }
    campos_cambiados = {c.campo for c in cambios}
    for cambio in cambios:
        fila[cambio.campo] = cambio.valor_nuevo
    motivos_campos_cambiados = {m for campo in campos_cambiados for m in _motivos_de_campo(campo)}
    motivos_restantes = sorted(
        (motivos_actuales - motivos_campos_cambiados) | (motivos_valor_nuevo & motivos_campos_cambiados)
    )
    fila["motivos_revision_documento"] = SEPARADOR_MOTIVOS.join(motivos_restantes)
    indicador, documental, operacional = _indicadores_documentales_coherentes(
        motivos_restantes, str(fila.get("estado_ruta", "")).strip(),
    )
    fila["indicador_revision"] = indicador
    fila["estado_documental"] = documental
    fila["estado_operacional"] = operacional


@dataclass(frozen=True)
class CambioCampo:
    archivo: str
    numero_guia: str
    campo: str
    valor_anterior: str
    valor_nuevo: str


@dataclass(frozen=True)
class DocumentoReparado:
    archivo: str
    numero_guia_antes: str
    numero_guia_despues: str
    fila_nueva: bool  # documento que antes no tenía ninguna fila (rescatado)
    cambios: tuple[CambioCampo, ...]
    motivo_no_reparado: str = ""  # imagen no encontrada / OCR falló / sin fila y sin identidad nueva


def _cargar_manifiesto(raiz: Path, *, nombre_lote: str | None) -> tuple[str, list[dict[str, str]]]:
    """Localiza el lote por MANIFIESTO persistido -- nunca por
    adivinación (nunca "las últimas N filas del CSV", nunca "los
    archivos modificados hoy"). `nombre_lote=None` toma el manifiesto
    con `ingresado_en_utc` más reciente entre TODOS los persistidos
    (soporta selección múltiple de Desktop en una sola carpeta temporal,
    ver `_persistir_manifiesto_seleccion_desktop`)."""
    carpeta = raiz / "operacion" / "actual" / "manifiestos_ingesta"
    if not carpeta.is_dir():
        raise FileNotFoundError(f"No existe carpeta de manifiestos de ingesta: {carpeta}")
    if nombre_lote is not None:
        ruta = carpeta / f"{nombre_lote}.json"
        if not ruta.is_file():
            raise FileNotFoundError(f"No existe el manifiesto del lote {nombre_lote!r}: {ruta}")
        candidatos = [ruta]
    else:
        candidatos = sorted(carpeta.glob("*.json"))
        if not candidatos:
            raise FileNotFoundError(f"No hay ningún manifiesto de ingesta en {carpeta}")

    mejor_ruta: Path | None = None
    mejor_instante = ""
    mejor_contenido: dict | None = None
    for ruta in candidatos:
        try:
            contenido = json.loads(ruta.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        seleccion = contenido.get("seleccion") or []
        instante = max((str(e.get("ingresado_en_utc", "")) for e in seleccion), default="")
        if nombre_lote is not None or instante > mejor_instante:
            mejor_ruta, mejor_instante, mejor_contenido = ruta, instante, contenido
            if nombre_lote is not None:
                break
    if mejor_contenido is None or mejor_ruta is None:
        raise FileNotFoundError(f"Ningún manifiesto de ingesta en {carpeta} es legible")
    seleccion = [dict(e) for e in (mejor_contenido.get("seleccion") or [])]
    if not seleccion:
        raise ValueError(f"El manifiesto {mejor_ruta.name} no tiene ninguna imagen registrada")
    return str(mejor_contenido.get("lote", mejor_ruta.stem)), seleccion


FILA_NO_ENCONTRADA = "FILA_NO_ENCONTRADA"
FILA_AMBIGUA = "FILA_AMBIGUA"
FILA_CONTRADICE_GUIA = "FILA_CONTRADICE_GUIA"


def _ruta_normalizada(valor: object) -> str:
    return str(valor or "").strip().replace("\\", "/").strip("/")


def _es_documento_mobile(archivo: object) -> bool:
    return _ruta_normalizada(archivo).lower().startswith("mobile/")


def _resolver_fila_por_archivo(
    filas: list[dict[str, str]], archivo: str, *, numero_guia: str = "",
) -> tuple[dict[str, str] | None, str]:
    """Fila EXACTA del documento `archivo`, o (None, motivo) si no hay una única.

    1. Ruta relativa completa (identificador de Atlas, p. ej.
       ``mobile/<uuid>/original.jpg`` o ``<marca>/<archivo>``).
    2. Sólo si el llamador dio un nombre SIN carpeta (nombre de origen del
       manifiesto de lote): nombre de archivo, siempre que identifique una
       única fila y nunca una fila Mobile -- todas las capturas Mobile se
       llaman ``original.jpg`` (caso real: una corrección de una guía Mobile
       caía en la primera fila Mobile del dataset).
    3. Si el llamador conoce la guía objetivo y la fila no es de esa guía:
       abstención. Nunca se elige "la primera" de varias.
    """
    objetivo = _ruta_normalizada(archivo)
    if not objetivo:
        return None, FILA_NO_ENCONTRADA
    candidatas = [f for f in filas if _ruta_normalizada(f.get("archivo")) == objetivo]
    if not candidatas and "/" not in objetivo:
        candidatas = [f for f in filas
                      if Path(_ruta_normalizada(f.get("archivo"))).name == objetivo
                      and not _es_documento_mobile(f.get("archivo"))]
        if any(_es_documento_mobile(f.get("archivo")) and Path(_ruta_normalizada(f.get("archivo"))).name == objetivo
               for f in filas):
            return None, FILA_AMBIGUA
    if not candidatas:
        return None, FILA_NO_ENCONTRADA
    if len(candidatas) > 1:
        return None, FILA_AMBIGUA
    fila = candidatas[0]
    guia = str(numero_guia or "").strip()
    if guia and str(fila.get("numero_guia", "")).strip() != guia:
        return None, FILA_CONTRADICE_GUIA
    return fila, ""


def _fila_por_archivo(
    filas: list[dict[str, str]], nombre_archivo: str, *, numero_guia: str = "",
) -> dict[str, str] | None:
    """Compatibilidad: la fila única de `_resolver_fila_por_archivo` o None."""
    return _resolver_fila_por_archivo(filas, nombre_archivo, numero_guia=numero_guia)[0]


def _expandir_paginas_pdf(
    raiz: Path, seleccion: list[dict[str, str]], filas: list[dict[str, str]],
) -> list[dict[str, str]]:
    """El manifiesto de ingesta registra el ARCHIVO seleccionado (p. ej.
    ``lote.pdf``), pero el dataset guarda una fila por PÁGINA
    (``lote.pdf::pagina=0001``). Cada entrada que es un PDF se reemplaza
    por una entrada por página -- las del manifiesto del PDF más las que ya
    tienen fila -- para que el resto del reparador trate cada página como
    un documento, igual que una imagen. Imágenes: sin cambios."""
    salida: list[dict[str, str]] = []
    for entrada in seleccion:
        nombre = str(entrada.get("nombre_archivo", "")).strip()
        paginas_con_fila = {
            pagina
            for fila in filas
            for referencia, pagina in [separar_identificador_pagina_pdf(str(fila.get("archivo", "")))]
            if pagina is not None and Path(referencia).name == nombre
        }
        paginas_pdf = paginas_pdf_procesables(raiz, nombre) if nombre else None
        if paginas_pdf is None and not paginas_con_fila:
            salida.append(entrada)
            continue
        paginas = sorted(set(paginas_pdf or ()) | paginas_con_fila)
        if not paginas:
            salida.append({**entrada, "_pdf_sin_paginas": "1"})
            continue
        salida.extend({**entrada, "nombre_archivo": identificador_pagina_pdf(nombre, n)} for n in paginas)
    return salida


def reprocesar_lote_reparador(
    *,
    raiz_atlas: str | Path,
    nombre_lote: str | None = None,
    dry_run: bool = True,
    lector_ocr: object = None,
    proveedor: object = None,
) -> dict[str, object]:
    """Modo REPROCESAMIENTO_REPARADOR -- ver docstring del módulo para
    las garantías estructurales. `dry_run=True` (default, EXPLÍCITO):
    calcula y reporta todo, no escribe nada -- ni el dataset, ni la
    bandeja, ni dispara reconciliación. Sólo con `dry_run=False` se
    persisten los cambios y corre `revalidar_y_regenerar_reporte` al
    final (reconciliación canónica ya existente, nunca una nueva)."""
    raiz = Path(raiz_atlas)
    actual = raiz / "operacion" / "actual"
    dataset = actual / "analisis_completo_guias.csv"
    catalogos = raiz / "catalogos_privados"
    ledger = actual / "decisiones_aplicadas.json"
    t_inicio = time.perf_counter()

    nombre_lote_resuelto, seleccion = _cargar_manifiesto(raiz, nombre_lote=nombre_lote)

    # Caso real lote 20260916_151401: sin esto, `procesar_archivo` caía al
    # camino EasyOCR legacy por defecto (proveedor=None) -- un motor
    # DISTINTO del PaddleOCR GPU ya validado (ver bloque de diagnóstico
    # previo) -- nunca reproducía la evidencia superior ya demostrada
    # manualmente para estas mismas imágenes. Mismo proveedor compartido
    # para todo el lote, mismo patrón que ya usa `procesar_carpeta`
    # (`proveedor_compartido = crear_proveedor_ocr()` una sola vez).
    proveedor_propio = proveedor is None and lector_ocr is None
    if proveedor_propio:
        proveedor = crear_proveedor_ocr()

    try:
        aplicaciones = json.loads(ledger.read_text(encoding="utf-8")).get("aplicaciones", [])
        aplicaciones = [a for a in aplicaciones if isinstance(a, Mapping)]
    except (OSError, ValueError):
        aplicaciones = []

    try:
        decisiones_json = json.loads((actual / "decisiones_pendientes.json").read_text(encoding="utf-8"))
        decisiones_antes = list(decisiones_json.get("decisiones", []))
    except (OSError, ValueError):
        decisiones_antes = []

    with bloqueo_sesion(dataset.parent, "revalidacion_dataset"):
        try:
            filas = _leer_filas(dataset)
        except (OSError, ValueError):
            filas = []
        identidades_existentes = {
            (str(f.get("numero_guia", "")).strip(), str(f.get("numero_transporte", "")).strip())
            for f in filas
        }

        documentos: list[DocumentoReparado] = []
        filas_nuevas: list[dict[str, str]] = []
        tiempos_por_imagen: list[float] = []

        for entrada in _expandir_paginas_pdf(raiz, seleccion, filas):
            t_imagen = time.perf_counter()
            nombre_archivo = str(entrada.get("nombre_archivo", "")).strip()
            if not nombre_archivo:
                continue
            if entrada.get("_pdf_sin_paginas"):
                # PDF sin ninguna página procesable (cifrado/corrupto/vacío):
                # nunca se le pasa el PDF crudo al OCR.
                documentos.append(DocumentoReparado(
                    archivo=nombre_archivo, numero_guia_antes="", numero_guia_despues="",
                    fila_nueva=False, cambios=(), motivo_no_reparado="PDF_SIN_PAGINAS_PROCESABLES",
                ))
                continue
            fila, motivo_fila = _resolver_fila_por_archivo(filas, nombre_archivo)
            if motivo_fila in {FILA_AMBIGUA, FILA_CONTRADICE_GUIA}:
                # Varias filas posibles: nunca se elige una ni se crea otra.
                documentos.append(DocumentoReparado(
                    archivo=nombre_archivo, numero_guia_antes="", numero_guia_despues="",
                    fila_nueva=False, cambios=(), motivo_no_reparado=motivo_fila,
                ))
                continue
            archivo_id = str(fila.get("archivo", nombre_archivo)) if fila is not None else nombre_archivo

            evidencia = resolver_ruta_evidencia(raiz, archivo_id)
            if evidencia.ruta is None:
                documentos.append(DocumentoReparado(
                    archivo=archivo_id, numero_guia_antes=str((fila or {}).get("numero_guia", "")),
                    numero_guia_despues=str((fila or {}).get("numero_guia", "")), fila_nueva=False,
                    cambios=(), motivo_no_reparado=f"IMAGEN_{evidencia.ubicacion}",
                ))
                continue

            try:
                proveedor_documento, lector_documento = proveedor_para_documento(
                    ruta_texto_pdf=evidencia.ruta_texto_pdf, proveedor=proveedor, lector_ocr=lector_ocr,
                )
                extraido = dict(procesar_archivo(
                    evidencia.ruta, lector_ocr=lector_documento, proveedor=proveedor_documento,
                    carpeta_catalogos=catalogos,
                ))
            except Exception as exc:  # cada documento es una unidad independiente
                documentos.append(DocumentoReparado(
                    archivo=archivo_id, numero_guia_antes=str((fila or {}).get("numero_guia", "")),
                    numero_guia_despues=str((fila or {}).get("numero_guia", "")), fila_nueva=False,
                    cambios=(), motivo_no_reparado=f"ERROR_REPROCESO:{type(exc).__name__}",
                ))
                tiempos_por_imagen.append(time.perf_counter() - t_imagen)
                continue

            if fila is None:
                # Bloque 3 (rescate) -- el documento NUNCA tuvo fila
                # (caso real "sin transporte reconocible"). Sólo se
                # promueve a fila nueva si la reextracción SÍ resolvió
                # guía+transporte Y esa identidad no existe todavía --
                # nunca un duplicado, nunca una fila a medias.
                guia_nueva = str(extraido.get("numero_guia", "")).strip()
                transporte_nuevo = str(extraido.get("numero_transporte", "")).strip()
                identidad = (guia_nueva, transporte_nuevo)
                if (
                    guia_nueva and transporte_nuevo
                    and CAMPOS_REPARABLES["numero_guia"][1](guia_nueva)
                    and CAMPOS_REPARABLES["numero_transporte"][1](transporte_nuevo)
                    and identidad not in identidades_existentes
                ):
                    nueva_fila = {columna: str(extraido.get(columna, "")) for columna in COLUMNAS}
                    nueva_fila["archivo"] = archivo_id
                    filas_nuevas.append(nueva_fila)
                    identidades_existentes.add(identidad)
                    documentos.append(DocumentoReparado(
                        archivo=archivo_id, numero_guia_antes="", numero_guia_despues=guia_nueva,
                        fila_nueva=True, cambios=(
                            CambioCampo(archivo_id, guia_nueva, "numero_guia", "", guia_nueva),
                            CambioCampo(archivo_id, guia_nueva, "numero_transporte", "", transporte_nuevo),
                        ),
                    ))
                else:
                    documentos.append(DocumentoReparado(
                        archivo=archivo_id, numero_guia_antes="", numero_guia_despues=guia_nueva,
                        fila_nueva=False, cambios=(),
                        motivo_no_reparado="SIN_FILA_Y_SIN_IDENTIDAD_NUEVA_VALIDA",
                    ))
                tiempos_por_imagen.append(time.perf_counter() - t_imagen)
                continue

            # Bloque 4/5 -- reparación campo por campo de una fila YA
            # existente: sólo promueve lo degradado (o siempre reexaminado,
            # ver CAMPOS_SIEMPRE_REEXAMINADOS), nunca lo ya limpio; el
            # ledger siempre gana. Lógica compartida (nunca duplicada) con
            # `revalidar_documentos_por_transporte`.
            motivos_actuales = {
                m.strip() for m in str(fila.get("motivos_revision_documento", "")).split(SEPARADOR_MOTIVOS) if m.strip()
            }
            relectura_ocr_principal = _lectura_previa_por_ocr_de_respaldo(raiz, fila, proveedor_documento)
            documento_degradado = _MOTIVO_DOCUMENTO_DEGRADADO in motivos_actuales or relectura_ocr_principal
            cambios = _reparar_campos_documento(
                fila, extraido, aplicaciones, documento_degradado=documento_degradado,
            )
            guia_antes = str(fila.get("numero_guia", ""))
            _aplicar_cambios_a_fila(
                fila, cambios, motivos_reextraccion=str(extraido.get("motivos_revision_documento", "")),
            )
            if relectura_ocr_principal and cambios:
                _anotar_relectura_ocr_principal(fila)
            documentos.append(DocumentoReparado(
                archivo=archivo_id, numero_guia_antes=guia_antes,
                numero_guia_despues=str(fila.get("numero_guia", "")),
                fila_nueva=False, cambios=tuple(cambios),
            ))
            tiempos_por_imagen.append(time.perf_counter() - t_imagen)

        if not dry_run and (any(d.cambios for d in documentos) or filas_nuevas):
            _escribir_filas_completas(dataset, filas + filas_nuevas)

    if proveedor_propio and hasattr(proveedor, "cerrar"):
        proveedor.cerrar()

    reconciliacion: dict[str, object] | None = None
    if not dry_run and (any(d.cambios for d in documentos) or filas_nuevas):
        # Bloque 8/9 -- reconciliación canónica YA existente (nunca una
        # nueva): re-deriva motivos/indicadores, republica el reporte y
        # regenera la bandeja de decisiones -- retira sola cualquier
        # tarjeta cuyo motivo ya no exista, conserva las que sigan
        # siendo ambiguas. Nunca aplica ninguna decisión ni B1 (esa
        # maquinaria vive sólo en `reconciliar_estado_derivado`, nunca
        # se invoca desde aquí).
        reconciliacion = revalidar_y_regenerar_reporte(
            raiz_atlas=raiz, nombre_carpeta_reporte=f"reporte_reparador_{nombre_lote_resuelto}_{int(time.time())}",
        )

    try:
        decisiones_despues = list(json.loads(
            (actual / "decisiones_pendientes.json").read_text(encoding="utf-8")
        ).get("decisiones", [])) if not dry_run else decisiones_antes
    except (OSError, ValueError):
        decisiones_despues = decisiones_antes

    duracion_total_ms = round((time.perf_counter() - t_inicio) * 1000, 1)
    return {
        "lote": nombre_lote_resuelto,
        "dry_run": dry_run,
        "documentos_en_manifiesto": len(seleccion),
        "documentos_reprocesados": len(documentos),
        "documentos": [
            {
                "archivo": d.archivo, "numero_guia_antes": d.numero_guia_antes,
                "numero_guia_despues": d.numero_guia_despues, "fila_nueva": d.fila_nueva,
                "motivo_no_reparado": d.motivo_no_reparado,
                "cambios": [
                    {"campo": c.campo, "antes": c.valor_anterior, "despues": c.valor_nuevo}
                    for c in d.cambios
                ],
            }
            for d in documentos
        ],
        "campos_cambiados_total": sum(len(d.cambios) for d in documentos),
        "documentos_sin_reparar": [d.archivo for d in documentos if d.motivo_no_reparado],
        "decisiones_pendientes_antes": len(decisiones_antes),
        "decisiones_pendientes_despues": len(decisiones_despues) if not dry_run else None,
        "reconciliacion": reconciliacion,
        "tiempo_total_ms": duracion_total_ms,
        "tiempo_promedio_por_imagen_ms": (
            round(sum(tiempos_por_imagen) / len(tiempos_por_imagen) * 1000, 1) if tiempos_por_imagen else 0.0
        ),
    }


# Bloque CIERRE FOCAL PIZARRO+TORRES (473442/473316) y ASIGNACIONES
# CANÓNICAS CHOFER->VEHÍCULO (473546/Salomón Pizarro, 11 viajes) --
# persistir valores YA conocidos de forma auditable (reextracción focal
# real, o -- para patente_tracto/patente_rampla -- una asignación
# operacional canónica que Javier ya entregó explícitamente, ver
# `convergencia_identidad_conocida.py`), SIN volver a correr OCR (a
# diferencia de `reprocesar_lote_reparador`, que siempre reprocesa la
# imagen original). Reutiliza exactamente las mismas garantías:
# validador estructural por campo, el ledger siempre gana, nunca
# aprende catálogo, nunca crea filas/duplicados, escritura atómica vía
# `_escribir_filas_completas`. `valores` sólo puede tocar las claves de
# `CAMPOS_FOCALES_CONOCIDOS` -- cualquier otra clave se ignora
# explícitamente, nunca un campo no autorizado por el llamador.
CAMPOS_FOCALES_CONOCIDOS: dict[str, object] = {
    "cliente": lambda v: v not in _AUSENTES,
    "rut_cliente": lambda v: validar_rut_chileno(v).estado == EstadoValidacion.VALIDO,
    "codigo_cliente": lambda v: v not in _AUSENTES,
    "cod_destinatario": lambda v: v not in _AUSENTES,
    "obra_destino": lambda v: v not in _AUSENTES,
    "despachar_a_crudo": lambda v: v not in _AUSENTES,
    "patente_tracto": lambda v: v not in _AUSENTES and _patente_valida(v),
    "patente_rampla": lambda v: v not in _AUSENTES and _patente_valida(v),
    # Caso 480715: número AZA completo, nunca un fragmento OCR -- más
    # estricto que `CAMPOS_REPARABLES` (\d{6,}) porque aquí no hay
    # reextracción que lo respalde, sólo el valor aportado por el operador.
    "numero_transporte": lambda v: bool(re.fullmatch(r"[0-9]{10}", v)),
}

# Motivos que cada campo puede retirar al promoverse -- mismo criterio
# que `CAMPOS_REPARABLES`. `codigo_cliente`/`cod_destinatario` no tienen
# motivo propio en `MotivoRevisionDocumento` (bloque P0 cerrado, nunca
# se les agregó uno) -- persistirlos nunca retira nada por sí solo, sólo
# documenta el valor. `patente_tracto`/`patente_rampla` sí retiran su
# motivo documental cuando aplica -- la pregunta `VEHICULO_DESCONOCIDO`
# en sí la retira, aparte, el bloque de convergencia de identidades
# conocidas (`regenerar_decisiones_persistidas`), nunca este módulo.
_MOTIVOS_POR_CAMPO_FOCAL_CONOCIDO: dict[str, tuple[str, ...]] = {
    "cliente": (
        MotivoRevisionDocumento.CLIENTE_AUSENTE.value,
        MotivoRevisionDocumento.CLIENTE_SIN_CORROBORAR.value,
        MotivoRevisionDocumento.CLIENTE_POSIBLEMENTE_INVALIDO.value,
        MotivoRevisionDocumento.CLIENTE_NUEVA_ENTIDAD_NO_CATALOGADA.value,
    ),
    "rut_cliente": (MotivoRevisionDocumento.RUT_CLIENTE_INVALIDO.value,),
    "obra_destino": (
        MotivoRevisionDocumento.OBRA_DESTINO_SIN_CORROBORAR.value,
        MotivoRevisionDocumento.OBRA_DESTINO_POSIBLEMENTE_INVALIDA.value,
    ),
    "despachar_a_crudo": (
        MotivoRevisionDocumento.DESTINO_FRAGMENTO_TRUNCADO.value,
        MotivoRevisionDocumento.DESTINO_CONTAMINADO_POR_OTRA_SECCION.value,
    ),
    "codigo_cliente": (),
    "cod_destinatario": (),
    "patente_tracto": (
        MotivoRevisionDocumento.PATENTE_SIN_HOMOLOGAR.value,
        MotivoRevisionDocumento.PATENTE_AMBIGUA.value,
    ),
    "patente_rampla": (
        MotivoRevisionDocumento.PATENTE_SIN_HOMOLOGAR.value,
        MotivoRevisionDocumento.PATENTE_AMBIGUA.value,
    ),
    "numero_transporte": (_MOTIVO_TRANSPORTE, _MOTIVO_TRANSPORTE_SIN_ETIQUETA),
}


def duplicados_guia_transporte(
    filas: list[dict[str, str]], *, archivo: str, numero_guia: str, numero_transporte: str,
) -> list[str]:
    """Archivos de OTRAS filas con la misma identidad guía+transporte --
    la misma identidad que `reprocesar_lote_reparador` nunca duplica."""
    guia, transporte = str(numero_guia).strip(), str(numero_transporte).strip()
    return sorted(
        str(f.get("archivo", "")) for f in filas
        if str(f.get("archivo", "")) != archivo
        and str(f.get("numero_guia", "")).strip() == guia
        and str(f.get("numero_transporte", "")).strip() == transporte
    )


def reparar_documento_focal_con_valores_conocidos(
    *, raiz_atlas: str | Path, archivo: str, valores: Mapping[str, str], dry_run: bool = True,
    reconciliar: bool = True, tipos_ledger_superables: frozenset[str] = frozenset(),
    numero_guia: str = "", superar_resoluciones_automaticas: bool = False,
) -> dict[str, object]:
    """Persiste, para UN documento puntual ya identificado por
    `archivo`, valores YA conocidos de una reextracción real (nunca
    vueltos a inferir aquí -- el llamador los aporta ya verificados).
    `dry_run=True` (default): calcula y reporta, no escribe nada.

    `reconciliar=False` (capa de acciones operacionales): el llamador
    asume la reconciliación FOCAL de lo afectado en vez de la global
    `revalidar_y_regenerar_reporte`. `tipos_ledger_superables`: tipos de
    aplicación del ledger que NO bloquean el campo -- sólo para que una
    corrección explícita del operador pueda reemplazar a otra corrección
    explícita del operador; una decisión de Revisión sigue ganando.
    `superar_resoluciones_automaticas`: una aplicación del ledger hecha por
    Atlas o B1 (no por una persona) no bloquea el campo -- caso real 474708:
    una SELECCIONAR_OTRA_PATENTE de ATLAS_AUTOMATICO impedía que la
    corrección humana confirmada (DOCUMENTO_CORREGIR_CAMPO) la reemplazara.

    `archivo` debe identificar UNA fila (ruta completa; ver
    `_resolver_fila_por_archivo`); con `numero_guia` la fila además debe
    ser de esa guía. Si no, ValueError y nada se escribe."""
    raiz = Path(raiz_atlas)
    actual = raiz / "operacion" / "actual"
    dataset = actual / "analisis_completo_guias.csv"
    ledger = actual / "decisiones_aplicadas.json"
    t_inicio = time.perf_counter()

    try:
        aplicaciones = json.loads(ledger.read_text(encoding="utf-8")).get("aplicaciones", [])
        aplicaciones = [a for a in aplicaciones if isinstance(a, Mapping)
                        and str(a.get("tipo", "")) not in tipos_ledger_superables]
        if superar_resoluciones_automaticas:
            from atlas_core.decisiones_pendientes import _actor_es_humano
            aplicaciones = [a for a in aplicaciones if _actor_es_humano(a.get("actor"))]
    except (OSError, ValueError):
        aplicaciones = []

    with bloqueo_sesion(dataset.parent, "revalidacion_dataset"):
        filas = _leer_filas(dataset)
        fila, motivo_fila = _resolver_fila_por_archivo(filas, archivo, numero_guia=numero_guia)
        if fila is None:
            raise ValueError(f"{motivo_fila}: no hay una única fila persistida para archivo={archivo!r}"
                             + (f" y guía {numero_guia}" if numero_guia else ""))
        archivo_id = str(fila.get("archivo", archivo))

        motivos_actuales = {
            m.strip() for m in str(fila.get("motivos_revision_documento", "")).split(SEPARADOR_MOTIVOS) if m.strip()
        }
        cambios: list[CambioCampo] = []
        campos_ignorados: list[str] = []
        campos_bloqueados_ledger: list[str] = []
        duplicados: list[str] = []
        for campo, valor_nuevo_crudo in valores.items():
            if campo not in CAMPOS_FOCALES_CONOCIDOS:
                campos_ignorados.append(campo)  # nunca toca un campo no autorizado
                continue
            if _hay_decision_humana_para_campo(aplicaciones, fila=fila, campo=campo):
                campos_bloqueados_ledger.append(campo)  # el ledger siempre gana
                continue
            es_valido = CAMPOS_FOCALES_CONOCIDOS[campo]
            valor_nuevo = str(valor_nuevo_crudo).strip()
            valor_actual = str(fila.get(campo, "")).strip()
            if not valor_nuevo or valor_nuevo == valor_actual or not es_valido(valor_nuevo):
                continue
            if campo == "numero_transporte":
                duplicados = duplicados_guia_transporte(
                    filas, archivo=archivo_id, numero_guia=str(fila.get("numero_guia", "")),
                    numero_transporte=valor_nuevo,
                )
                if duplicados:
                    continue  # nunca crea un duplicado guía+transporte
            cambios.append(CambioCampo(archivo_id, str(fila.get("numero_guia", "")), campo, valor_actual, valor_nuevo))

        if duplicados:
            cambios = []  # bloqueo total: ni siquiera los demás campos del mismo pedido
        if cambios:
            for cambio in cambios:
                fila[cambio.campo] = cambio.valor_nuevo
            motivos_resueltos = {
                m for campo, motivos_campo in _MOTIVOS_POR_CAMPO_FOCAL_CONOCIDO.items()
                for m in motivos_campo
                if campo in {c.campo for c in cambios}
            }
            motivos_restantes = [m for m in sorted(motivos_actuales) if m not in motivos_resueltos]
            fila["motivos_revision_documento"] = SEPARADOR_MOTIVOS.join(motivos_restantes)
            indicador, documental, operacional = _indicadores_documentales_coherentes(
                motivos_restantes, str(fila.get("estado_ruta", "")).strip(),
            )
            fila["indicador_revision"] = indicador
            fila["estado_documental"] = documental
            fila["estado_operacional"] = operacional
            if not dry_run:
                _escribir_filas_completas(dataset, filas)

    reconciliacion: dict[str, object] | None = None
    if not dry_run and cambios and reconciliar:
        reconciliacion = revalidar_y_regenerar_reporte(
            raiz_atlas=raiz,
            nombre_carpeta_reporte=f"reporte_reparador_focal_{archivo_id.replace('/', '_')}_{int(time.time())}",
        )

    return {
        "archivo": archivo_id,
        "numero_guia": str(fila.get("numero_guia", "")),
        "dry_run": dry_run,
        "campos_solicitados": list(valores.keys()),
        "campos_ignorados_no_autorizados": campos_ignorados,
        "campos_bloqueados_por_ledger": campos_bloqueados_ledger,
        "duplicados_guia_transporte": duplicados,
        "cambios": [
            {"campo": c.campo, "antes": c.valor_anterior, "despues": c.valor_nuevo} for c in cambios
        ],
        "campos_cambiados_total": len(cambios),
        "reconciliacion": reconciliacion,
        "tiempo_total_ms": round((time.perf_counter() - t_inicio) * 1000, 1),
    }


# Bloque REVALIDACIÓN POR TRANSPORTE -- caso real 0000359510 (chofer
# SALOMÓN PIZARRO): tras corregir una causa sistémica del Motor (Bloque
# O2, defensa evidencial de peso), Atlas no tenía forma reusable de
# revalidar un viaje YA persistido y conocido sin (a) reprocesar el LOTE
# de ingesta entero (`reprocesar_lote_reparador`, riesgo real de tocar
# documentos no relacionados que compartieron esa misma ingesta) o (b)
# editar el CSV/JSON a mano (exactamente lo que este módulo existe para
# evitar). Este es ese mecanismo mínimo: reprocesa EXCLUSIVAMENTE los
# documentos de UN `numero_transporte` (parámetro -- nunca hardcodeado),
# reutilizando el mismo pipeline real y las mismas garantías que arriba.
def revalidar_documentos_por_transporte(
    *,
    raiz_atlas: str | Path,
    numero_transporte: str,
    dry_run: bool = True,
    lector_ocr: object = None,
    proveedor: object = None,
) -> dict[str, object]:
    """Revalida TODOS los documentos ya persistidos de UN
    `numero_transporte`, reextrayéndolos contra su imagen ORIGINAL vía
    `procesamiento_masivo.procesar_archivo` (mismo pipeline real, nunca un
    segundo motor OCR) y aplicando exactamente las mismas garantías que
    `reprocesar_lote_reparador` -- ver docstring del módulo:

    - sólo promueve un campo ya degradado hoy (o siempre reexaminado, ver
      `CAMPOS_SIEMPRE_REEXAMINADOS`), nunca uno ya limpio;
    - el ledger (`decisiones_aplicadas.json`) siempre gana, sin excepción;
    - nunca crea fila nueva ni duplica nada -- sólo EDITA filas que ya
      existen para este transporte;
    - localiza y edita EXCLUSIVAMENTE las filas cuyo `numero_transporte`
      coincide -- ningún otro transporte/viaje del dataset se lee
      modificado ni se reescribe.

    `dry_run=True` (default, EXPLÍCITO): calcula y reporta, no escribe
    nada -- ni el dataset, ni dispara reconciliación. Sólo con
    `dry_run=False` se persiste y corre la reconciliación canónica YA
    existente (`revalidar_y_regenerar_reporte` -- nunca una nueva),
    exactamente igual que el resto de este módulo: regenera el reporte
    oficial y la bandeja de decisiones a partir del dataset ya corregido,
    nunca aplica ninguna decisión ni aprende catálogo por sí sola.

    `numero_transporte` es un parámetro obligatorio -- este mecanismo es
    genérico para cualquier transporte futuro, no un script puntual."""
    raiz = Path(raiz_atlas)
    actual = raiz / "operacion" / "actual"
    dataset = actual / "analisis_completo_guias.csv"
    catalogos = raiz / "catalogos_privados"
    ledger = actual / "decisiones_aplicadas.json"
    t_inicio = time.perf_counter()

    numero_transporte = str(numero_transporte).strip()
    if not numero_transporte:
        raise ValueError("numero_transporte es obligatorio")

    proveedor_propio = proveedor is None and lector_ocr is None
    if proveedor_propio:
        proveedor = crear_proveedor_ocr()

    try:
        aplicaciones = json.loads(ledger.read_text(encoding="utf-8")).get("aplicaciones", [])
        aplicaciones = [a for a in aplicaciones if isinstance(a, Mapping)]
    except (OSError, ValueError):
        aplicaciones = []

    documentos: list[DocumentoReparado] = []

    with bloqueo_sesion(dataset.parent, "revalidacion_dataset"):
        try:
            filas = _leer_filas(dataset)
        except (OSError, ValueError):
            filas = []

        # Filtra por referencia -- cada dict de `filas_del_transporte` ES
        # el mismo objeto que vive en `filas`; mutarlo aquí (Bloque 4/5
        # abajo) se refleja en `filas` sin tocar ninguna otra fila, así
        # que `_escribir_filas_completas(dataset, filas)` más abajo
        # persiste el dataset COMPLETO con sólo estas filas cambiadas.
        filas_del_transporte = [
            f for f in filas if str(f.get("numero_transporte", "")).strip() == numero_transporte
        ]

        for fila in filas_del_transporte:
            archivo_id = str(fila.get("archivo", "")).strip()
            evidencia = resolver_ruta_evidencia(raiz, archivo_id)
            if evidencia.ruta is None:
                documentos.append(DocumentoReparado(
                    archivo=archivo_id, numero_guia_antes=str(fila.get("numero_guia", "")),
                    numero_guia_despues=str(fila.get("numero_guia", "")), fila_nueva=False,
                    cambios=(), motivo_no_reparado=f"IMAGEN_{evidencia.ubicacion}",
                ))
                continue

            try:
                proveedor_documento, lector_documento = proveedor_para_documento(
                    ruta_texto_pdf=evidencia.ruta_texto_pdf, proveedor=proveedor, lector_ocr=lector_ocr,
                )
                extraido = dict(procesar_archivo(
                    evidencia.ruta, lector_ocr=lector_documento, proveedor=proveedor_documento,
                    carpeta_catalogos=catalogos,
                ))
            except Exception as exc:  # cada documento es una unidad independiente
                documentos.append(DocumentoReparado(
                    archivo=archivo_id, numero_guia_antes=str(fila.get("numero_guia", "")),
                    numero_guia_despues=str(fila.get("numero_guia", "")), fila_nueva=False,
                    cambios=(), motivo_no_reparado=f"ERROR_REPROCESO:{type(exc).__name__}",
                ))
                continue

            motivos_actuales = {
                m.strip() for m in str(fila.get("motivos_revision_documento", "")).split(SEPARADOR_MOTIVOS) if m.strip()
            }
            relectura_ocr_principal = _lectura_previa_por_ocr_de_respaldo(raiz, fila, proveedor_documento)
            documento_degradado = _MOTIVO_DOCUMENTO_DEGRADADO in motivos_actuales or relectura_ocr_principal
            cambios = _reparar_campos_documento(
                fila, extraido, aplicaciones, documento_degradado=documento_degradado,
            )
            guia_antes = str(fila.get("numero_guia", ""))
            _aplicar_cambios_a_fila(
                fila, cambios, motivos_reextraccion=str(extraido.get("motivos_revision_documento", "")),
            )
            if relectura_ocr_principal and cambios:
                _anotar_relectura_ocr_principal(fila)
            documentos.append(DocumentoReparado(
                archivo=archivo_id, numero_guia_antes=guia_antes,
                numero_guia_despues=str(fila.get("numero_guia", "")),
                fila_nueva=False, cambios=tuple(cambios),
            ))

        if not dry_run and any(d.cambios for d in documentos):
            _escribir_filas_completas(dataset, filas)

    if proveedor_propio and hasattr(proveedor, "cerrar"):
        proveedor.cerrar()

    reconciliacion: dict[str, object] | None = None
    if not dry_run and any(d.cambios for d in documentos):
        reconciliacion = revalidar_y_regenerar_reporte(
            raiz_atlas=raiz,
            nombre_carpeta_reporte=f"reporte_revalidacion_transporte_{numero_transporte}_{int(time.time())}",
        )

    return {
        "numero_transporte": numero_transporte,
        "dry_run": dry_run,
        "documentos_encontrados": len(filas_del_transporte),
        "documentos_reprocesados": len(documentos),
        "documentos": [
            {
                "archivo": d.archivo, "numero_guia_antes": d.numero_guia_antes,
                "numero_guia_despues": d.numero_guia_despues,
                "motivo_no_reparado": d.motivo_no_reparado,
                "cambios": [
                    {"campo": c.campo, "antes": c.valor_anterior, "despues": c.valor_nuevo}
                    for c in d.cambios
                ],
            }
            for d in documentos
        ],
        "campos_cambiados_total": sum(len(d.cambios) for d in documentos),
        "documentos_sin_reparar": [d.archivo for d in documentos if d.motivo_no_reparado],
        "reconciliacion": reconciliacion,
        "tiempo_total_ms": round((time.perf_counter() - t_inicio) * 1000, 1),
    }
