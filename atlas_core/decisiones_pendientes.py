"""Contrato R3.1 de decisiones pendientes, separado del resultado documental.

El módulo sólo observa resultados y catálogos. Nunca aplica decisiones ni
modifica catálogos; la única escritura permitida es el artefacto versionado.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping

from atlas_core.almacenamiento_portable import escribir_json_atomico
from atlas_core.catalogo_clientes import (
    CatalogoClientes,
    EstadoCalidadCliente,
    EstadoVigenciaCliente,
    normalizar_nombre_cliente,
    normalizar_rut_cliente,
)
from atlas_core.catalogo_destinos import normalizar_nombre_destino
from atlas_core.catalogo_obras_destinos import (
    CatalogoObrasDestinos,
    EstadoObra,
    EstadoVigencia,
    normalizar_nombre_obra,
)
from atlas_core.catalogo_plantas import Planta
from atlas_core.catalogo_vehiculos import (
    _diferencia_ocr_segura,
    cargar_catalogo_vehiculos,
    normalizar_patente_vehiculo,
    resolver_patente,
)
from atlas_core.catalogos import (
    buscar_empresa_por_rut,
    cargar_catalogo_json,
    normalizar_rut,
    resolver_nombre_cliente_difuso,
)
from atlas_core.evidencia_entidades import ConfirmacionIdentidad
from atlas_core.motor_evidencia_clientes import evaluar_evidencia_cliente
from atlas_core.motor_evidencia_obras import evaluar_evidencia_obra, resolver_obra_por_variacion_ortografica_menor
from atlas_core.rutas.geocerca import coordenada_ruteo_planta, distancia_km_haversine
from atlas_core.rutas.modelos import Coordenadas
from atlas_core.validadores import EstadoValidacion, validar_rut_chileno
from atlas_core.verificacion_externa import EvidenciaExterna


SCHEMA_VERSION = 1
NOMBRE_ARTEFACTO = "decisiones_pendientes.json"
TIPOS_SOPORTADOS = frozenset({
    "VEHICULO_DESCONOCIDO", "CLIENTE_DESCONOCIDO", "CLIENTE_CANDIDATO",
    "OBRA_DESCONOCIDA", "DESTINO_SIN_CONFIRMAR", "ALIAS_CANDIDATO",
    "ORIGEN_NO_CONFIRMADO", "DESTINO_NO_RESUELTO", "CLIENTE_AUSENTE",
})
_AUSENTES = {"", "No encontrado", "REVISAR", "Ilegible"}

# R3.2/R3.2.1: pregunta operacional única para una entidad realmente
# desconocida -- registrarla, no registrarla o decidir después. Se usa tal
# cual para OBRA_DESCONOCIDA, VEHICULO_DESCONOCIDO y CLIENTE_DESCONOCIDO.
ACCIONES_ENTIDAD_DESCONOCIDA = ("REGISTRAR", "NO_REGISTRAR", "POSPONER")
TIPOS_ENTIDAD_DESCONOCIDA = frozenset({
    "OBRA_DESCONOCIDA", "VEHICULO_DESCONOCIDO", "CLIENTE_DESCONOCIDO",
})
# R3.4: para DESTINO_SIN_CONFIRMAR la entidad (obra) ya se conoce; lo único
# pendiente es confirmar la relación obra<->destino -- pregunta distinta a
# "registrar una entidad nueva", por eso usa su propio set de acciones.
ACCIONES_DESTINO_SIN_CONFIRMAR = ("CONFIRMAR", "NO_CONFIRMAR", "POSPONER")
# Bloque CLIENTE_CANDIDATO (R4.8) -- tipo reservado en TIPOS_SOPORTADOS desde
# R3.1 y nunca implementado hasta ahora. Distinto de ALIAS_CANDIDATO (que
# exige RUT exacto como anclaje) y de CLIENTE_DESCONOCIDO (registrar una
# entidad genuinamente nueva): aquí el nombre documental coincide -- difuso
# o por alias, mismo motor ya calibrado para chofer/empresa -- con un
# cliente YA CONFIRMADO/ACTIVO, pero el documento no trae un RUT que lo
# corrobore. Mismas tres acciones que DESTINO_SIN_CONFIRMAR (confirmar/
# rechazar/posponer una relación ya sugerida, no registrar nada nuevo).
ACCIONES_CLIENTE_CANDIDATO = ("CONFIRMAR", "NO_CONFIRMAR", "POSPONER")
# Coincidencias de `resolver_nombre_cliente_difuso`/`resolver_nombre_empresa_difuso`
# que representan evidencia real de identidad, no una adivinanza -- mismo
# set ya usado en `procesamiento_masivo.py` para corroboración cruzada.
_ESTADOS_NOMBRE_SEGUROS = {"SIN_CAMBIO", "ALIAS", "COINCIDENCIA_SEGURA"}
# Bloque ORIGEN D1: distinta otra vez -- aquí no se registra ni se confirma
# una entidad de catálogo, se elige entre plantas YA CONOCIDAS cuál es el
# origen canónico de ESTE documento/viaje. "NO_PUEDO_DETERMINAR" es
# deliberadamente distinto de "POSPONER": un humano que ya miró la
# evidencia y no puede decidir no debe volver a recibir la misma pregunta
# mientras la evidencia no cambie (ver `crear_decision`/`_decision_id`,
# la evidencia forma parte del hash -- nueva evidencia, nueva pregunta).
ACCIONES_ORIGEN_NO_CONFIRMADO = (
    "CONFIRMAR_PLANTA", "SELECCIONAR_OTRA_PLANTA", "NO_PUEDO_DETERMINAR", "POSPONER",
)

# Bloque R6 A/B/E -- distinta de DESTINO_SIN_CONFIRMAR (que confirma/rechaza
# un valor YA OBSERVADO en el documento) y de ORIGEN_NO_CONFIRMADO (elige
# entre plantas YA CONOCIDAS): aquí, con origen ya resuelto, el documento
# no trae ninguna dirección de entrega utilizable (ausente, o geocodifica
# de forma contradictoria/demasiado genérica/ambigua) y Atlas agotó toda
# fuente automática (documento, obra, histórico, relación confirmada,
# catálogos) sin encontrar una dirección confiable. "REGISTRAR_DIRECCION"
# es la única acción que aporta un dato nuevo -- un humano escribe la
# dirección real de entrega, que se valida con el MISMO mecanismo
# determinista de geocodificación/ruta ya existente (nunca se acepta a
# ciegas). "NO_PUEDO_DETERMINAR" es terminal, igual que en
# ORIGEN_NO_CONFIRMADO: no vuelve a preguntar mientras la evidencia no
# cambie.
ACCIONES_DESTINO_NO_RESUELTO = ("REGISTRAR_DIRECCION", "NO_PUEDO_DETERMINAR", "POSPONER")

# Motivos de `motivo_ruta` que representan, específicamente, un problema de
# DESTINO (nunca de origen) con evidencia documental insuficiente o
# contradictoria -- el conjunto que hoy puede producir la ruta de un
# documento real (`resolver_destino_entrega_validado`/
# `calcular_ruta_con_planta_conocida`/`resolver_entrega_documento`).
# Deliberadamente una lista cerrada y explícita, no "cualquier
# REQUIERE_REVISION": un estado de ruta nuevo, no reconocido aquí, se trata
# como evidencia insuficiente para preguntar (mismo criterio conservador
# que `detectar_decision_origen_no_confirmado`), nunca como oportunidad
# automática de generar una pregunta.
MOTIVOS_DESTINO_NO_RESUELTO = frozenset({
    "DESTINO_SIN_DATO",
    "GEOCODIFICACION_CONTRADICE_COMUNA_DOCUMENTAL",
    "GEOCODIFICACION_DEMASIADO_GENERICA",
    "MULTIPLES_UBICACIONES_DISPERSAS",
    # Bloque R9 -- caso real 472044: el punto geocodificado no tiene
    # acceso vial cercano (evidencia real de imprecisión del destino,
    # nunca una falla técnica del proveedor -- ver
    # atlas_core.rutas.openrouteservice/EstadoRuta.SIN_ACCESO_VIAL).
    "SIN_ACCESO_VIAL",
    # Bloque RESOLUCIÓN R18 -- caso real 472037 (VICUÑA MACKENNA 655):
    # un candidato geocodificado fuera de Chile (Bloque TERRITORIAL T1)
    # es exactamente el mismo tipo de problema de DESTINO que los demás
    # -- evidencia insuficiente/contradictoria, nunca una falla técnica
    # externa. Sin esta entrada, el documento quedaba bloqueado sin
    # ninguna decisión accionable en Revisión de Atlas -- mismo criterio
    # ya aplicado a la elegibilidad de B1 (Bloque R16,
    # atlas_ia.registro_problemas).
    "GEOCODIFICACION_FUERA_DE_CHILE",
})


def _evidencia_externa_resumida(evidencias: list) -> tuple[str, tuple[str, ...]]:
    """Bloque B1 EXPOSICIÓN -- traduce evidencia `EXTERNO` (Bloque B1
    INVESTIGADOR) a un resumen compacto para la tarjeta de Revisión de
    Atlas -- nunca un dump de URLs. `referencias_fuente` ya trae
    "Título <url>" (ver `atlas_ia.herramientas.herramienta_verificacion_
    externa`); aquí sólo se cuenta y se recortan los títulos."""
    externas = [e for e in evidencias if isinstance(e, dict) and e.get("tipo_fuente") == "EXTERNO"]
    if not externas:
        return "", ()
    total_fuentes = sum(len(e.get("referencias_fuente") or []) for e in externas) or len(externas)
    plural = "s" if total_fuentes != 1 else ""
    resumen = f"Evidencia externa: {total_fuentes} fuente{plural} concordante{plural}"
    fuentes: list[str] = []
    for evidencia in externas:
        for referencia in (evidencia.get("referencias_fuente") or [])[:2]:
            titulo = str(referencia).split(" <", 1)[0].strip()
            if titulo and titulo not in fuentes:
                fuentes.append(titulo)
    return resumen, tuple(fuentes[:4])


def _propuesta_b1_confirmable(valor_propuesto: str, valor_documental: str) -> bool:
    """Bloque B1 EXPOSICIÓN -- `valor_propuesto` sólo es "confirmable con
    un clic" si tiene forma de dato real (nunca "Sí"/"No"/una palabra
    suelta que a veces devuelve el modelo cuando el problema no era
    literalmente proponer un valor) -- con un número (probable número de
    calle) o compartiendo texto real con lo documental. Conservador a
    propósito: cuando hay duda, se cae al flujo existente de "Registrar
    dirección" -- nunca se ofrece "Confirmar" sobre algo dudoso."""
    valor = str(valor_propuesto or "").strip()
    if len(valor) < 8:
        return False
    if re.search(r"\d", valor):
        return True
    tokens_doc = {t for t in re.findall(r"[A-ZÁÉÍÓÚÜÑ0-9]{4,}", str(valor_documental or "").upper())}
    tokens_val = {t for t in re.findall(r"[A-ZÁÉÍÓÚÜÑ0-9]{4,}", valor.upper())}
    return bool(tokens_doc & tokens_val)


def resumen_hallazgo_b1(fila: Mapping[str, str], *, dominio: str, campo: str) -> dict[str, object] | None:
    """Bloque B1 EXPOSICIÓN -- lee `resultado_atlas_ia_json` (YA
    persistido por `procesamiento_masivo._ejecutar_ia_operacional`,
    misma fuente de verdad, nunca una memoria paralela) y traduce el
    resultado de B1 a lenguaje operacional para una tarjeta de Revisión
    de Atlas. `None` si B1 nunca se llamó para este dominio, o si se
    llamó pero no dejó ni explicación ni evidencia externa (caso 7:
    B1 realmente se abstuvo sin nada útil que mostrar)."""
    crudo = str(fila.get("resultado_atlas_ia_json", "")).strip()
    if not crudo:
        return None
    try:
        trazas = json.loads(crudo)
    except (TypeError, ValueError):
        return None
    if not isinstance(trazas, list):
        return None
    traza = next(
        (
            t for t in trazas if isinstance(t, dict)
            and t.get("dominio") == dominio and t.get("campo") == campo and t.get("llamada_realizada")
        ),
        None,
    )
    if traza is None:
        return None
    hipotesis = traza.get("hipotesis") or {}
    explicacion = str(hipotesis.get("explicacion", "")).strip()
    contexto_final = traza.get("contexto_final") or {}
    evidencias = contexto_final.get("evidencias")
    resumen_evidencia, fuentes = _evidencia_externa_resumida(evidencias if isinstance(evidencias, list) else [])
    if not explicacion and not resumen_evidencia:
        return None
    valor_documental = str(fila.get(campo, ""))
    valor_propuesto = str(hipotesis.get("valor_propuesto", "")).strip()
    confirmable = _propuesta_b1_confirmable(valor_propuesto, valor_documental)
    estado = str(traza.get("estado", ""))
    clasificacion = str(traza.get("clasificacion", ""))
    if estado == "BLOQUEADO_POR_VALIDACION":
        motivo_no_autoaplicable = "La evidencia encontrada no cumple el formato exacto que Atlas exige para aplicarse sola -- necesita su confirmación."
    elif clasificacion == "C_ABSTENCION":
        motivo_no_autoaplicable = "Atlas investigó, pero la evidencia encontrada no alcanza para confirmar el destino por sí sola."
    elif clasificacion == "B_ASISTENCIA":
        motivo_no_autoaplicable = "La evidencia es fuerte, pero Atlas nunca aplica un destino nuevo sin confirmación humana."
    else:
        motivo_no_autoaplicable = "Atlas no puede confirmar este destino por sí solo con la evidencia disponible."
    return {
        "b1_resumen_hallazgo": explicacion,
        "b1_propuesta": valor_propuesto if confirmable else "",
        "b1_evidencia_resumida": resumen_evidencia,
        "b1_fuentes_resumidas": list(fuentes),
        "b1_motivo_no_autoaplicable": motivo_no_autoaplicable,
        "b1_pregunta_humana": (
            "¿Confirma que este es el destino correcto?" if confirmable
            else "¿Puede indicar la dirección real de entrega?"
        ),
    }


def resumen_observacion_operacional(fila: Mapping[str, str]) -> dict[str, object] | None:
    """Bloque B1 OBSERVADOR -- lee la traza OBSERVACIONAL que
    `procesamiento_masivo._ejecutar_ia_operacional` deja en
    `resultado_atlas_ia_json` para una guía que el Motor resolvió SIN
    ningún problema elegible (0 llamadas LLM) -- misma fuente de verdad
    que `resumen_hallazgo_b1`, nunca una memoria paralela. Permite que
    B1 (o cualquier código futuro) consulte "¿qué pasó con esta guía?"
    sin tener que reprocesarla ni volver a razonar nada. `None` si la
    fila no trae ninguna traza (nunca procesada, o procesada antes de
    este bloque -- comportamiento idéntico a `resumen_hallazgo_b1` en el
    mismo caso)."""
    crudo = str(fila.get("resultado_atlas_ia_json", "")).strip()
    if not crudo:
        return None
    try:
        trazas = json.loads(crudo)
    except (TypeError, ValueError):
        return None
    if not isinstance(trazas, list):
        return None
    traza = next(
        (t for t in trazas if isinstance(t, dict) and t.get("dominio") == "CICLO_GUIA"), None,
    )
    if traza is None:
        return None
    return {
        "resultado_motor": str(traza.get("resultado_motor", "")),
        "resumen": dict(traza.get("resumen") or {}),
    }


def detectar_decision_destino_no_resuelto(
    *, archivo: str, fila: Mapping[str, str],
) -> dict[str, object] | None:
    """Bloque R6 A/B/E: genera una pregunta `DESTINO_NO_RESUELTO` para UN
    documento YA PROCESADO cuyo origen ya está resuelto (`planta_origen_id`
    presente -- preguntar por destino antes de tener origen no aporta nada)
    pero cuya ruta quedó bloqueada por un problema de DESTINO reconocido
    (ver `MOTIVOS_DESTINO_NO_RESUELTO`). Opera exclusivamente sobre columnas
    YA PERSISTIDAS (`fila`) -- nunca OCR, nunca red.

    Se abstiene (`None`) cuando:
    - ya hay ruta calculada (`estado_ruta == RUTA_CALCULADA`) -- nada que
      preguntar;
    - no hay planta de origen todavía -- ese es un problema de ORIGEN,
      cubierto aparte por `detectar_decision_origen_no_confirmado`;
    - el motivo de ruta no es uno de los reconocidos como "problema de
      destino" (p. ej. `ORIGEN_NO_DETERMINADO`, o cualquier motivo técnico
      transitorio como proveedor caído/sin credencial -- eso no es una
      pregunta para un humano, es un problema de infraestructura)."""
    if not str(fila.get("planta_origen_id", "")).strip():
        return None
    motivo_ruta = str(fila.get("motivo_ruta", "")).strip()
    motivo_base = motivo_ruta.split(":", 1)[0].split("(", 1)[0].strip()
    estado_ruta = str(fila.get("estado_ruta", "")).strip()
    # Bloque R9 -- los 4 motivos originales (rechazo de destino/
    # geocodificación) siempre normalizan `estado_ruta` a
    # "REQUIERE_REVISION" (ver `resolver_destino_entrega`/`_validado`).
    # Un rechazo a nivel de ROUTING (p. ej. `SIN_ACCESO_VIAL`, caso real
    # 472044) en cambio deja `estado_ruta` igual a su propio motivo crudo
    # -- se acepta también esa forma, nunca una lista fija de estados
    # nueva por cada motivo.
    if estado_ruta not in ("REQUIERE_REVISION", motivo_base):
        return None
    if motivo_base not in MOTIVOS_DESTINO_NO_RESUELTO:
        return None
    documento = fila.get("numero_guia", ""), fila.get("numero_transporte", "")
    evidencias = [{
        "tipo": "RUTA_BLOQUEADA", "motivo_ruta": motivo_ruta,
        "despachar_a_crudo": str(fila.get("despachar_a_crudo", "")),
        "planta_origen_nombre": str(fila.get("planta_origen_nombre", "")),
    }]
    contexto = {
        "obra_canonica": str(fila.get("obra_destino", "")),
        "cliente_canonico": str(fila.get("cliente", "")),
        "planta_origen_id": str(fila.get("planta_origen_id", "")),
    }
    # Bloque B1 EXPOSICIÓN -- si B1 (Bloque B1 INVESTIGADOR) ya investigó
    # este mismo problema y dejó una explicación/evidencia útil en
    # `resultado_atlas_ia_json` (misma fuente de verdad, nunca una
    # memoria paralela), se traduce y se adjunta al contexto -- Desktop
    # la usa para mostrar qué encontró Atlas en vez de un mensaje
    # genérico. Sin resultado B1 útil, `contexto` queda exactamente
    # como antes (caso 7: sin hipótesis, flujo sin cambios).
    hallazgo = resumen_hallazgo_b1(fila, dominio="DESTINO", campo="despachar_a_crudo")
    if hallazgo:
        contexto.update(hallazgo)
    return crear_decision(
        tipo="DESTINO_NO_RESUELTO", entidad="DESTINO", archivo=str(archivo),
        numero_guia=str(documento[0]), numero_transporte=str(documento[1]),
        campo="despachar_a_crudo", valor_documental=str(fila.get("despachar_a_crudo", "")),
        valor_normalizado="", identidad_resuelta=None,
        candidatos=(), motivos=[motivo_base],
        evidencias=evidencias, acciones_permitidas=ACCIONES_DESTINO_NO_RESUELTO,
        contexto=contexto,
    )

# Bloque R9 -- distinto de CLIENTE_DESCONOCIDO/CLIENTE_CANDIDATO/
# ALIAS_CANDIDATO (los tres exigen ALGÚN texto documental de partida,
# `cliente_documental not in _AUSENTES`): aquí el campo "cliente" está
# genuinamente vacío -- ningún nombre que registrar, corroborar ni
# comparar. Caso real 472238/472239: `CLIENTE_AUSENTE` (motivo
# bloqueante en `motivos_revision_documento`) nunca tenía ninguna
# decisión asociada -- el documento quedaba huérfano en REQUIERE_REVISION
# para siempre, invisible en Revisión de Atlas. La única acción que
# aporta un dato nuevo es que un humano escriba la razón social real
# (mirando el documento físico) -- "REGISTRAR_CLIENTE_MANUAL".
ACCIONES_CLIENTE_AUSENTE = ("REGISTRAR_CLIENTE_MANUAL", "NO_PUEDO_DETERMINAR", "POSPONER")


def detectar_decision_cliente_ausente(
    *, archivo: str, fila: Mapping[str, str],
) -> dict[str, object] | None:
    """Bloque R9: genera una pregunta `CLIENTE_AUSENTE` para UN documento
    YA PROCESADO cuyo campo cliente quedó genuinamente vacío (nunca para
    un nombre presente pero no corroborable -- eso ya lo cubren
    CLIENTE_CANDIDATO/CLIENTE_DESCONOCIDO/ALIAS_CANDIDATO). Opera
    exclusivamente sobre columnas YA PERSISTIDAS (`fila`) -- nunca OCR,
    nunca red. Se abstiene si el cliente ya trae algún valor (incluso
    dudoso) o si el motivo bloqueante ya se resolvió."""
    if str(fila.get("cliente", "")).strip() not in _AUSENTES:
        return None
    motivos = {m.strip() for m in str(fila.get("motivos_revision_documento", "")).split("|") if m.strip()}
    if "CLIENTE_AUSENTE" not in motivos:
        return None
    documento = fila.get("numero_guia", ""), fila.get("numero_transporte", "")
    return crear_decision(
        tipo="CLIENTE_AUSENTE", entidad="CLIENTE", archivo=str(archivo),
        numero_guia=str(documento[0]), numero_transporte=str(documento[1]),
        campo="cliente", valor_documental="",
        valor_normalizado="", identidad_resuelta=None,
        candidatos=(), motivos=("CLIENTE_AUSENTE",),
        evidencias=({"tipo": "CAMPO_VACIO", "campo": "cliente"},),
        acciones_permitidas=ACCIONES_CLIENTE_AUSENTE,
    )


# Bloque VEHÍCULO D1 -- cuando una patente documental (probable error de
# OCR o del mandante) no homologa con ningún vehículo del catálogo, PERO
# el mismo RUT de chofer ya tiene, en otro documento del dataset, una
# patente CONFIRMADA/ACTIVA distinta, esas dos acciones se SUMAN a las
# tres ya existentes de `ACCIONES_ENTIDAD_DESCONOCIDA` (nunca las
# reemplazan: seguir pudiendo registrar la lectura tal cual, o no
# registrar nada, sigue siendo válido). Nunca autocorrige -- ver
# `sugerir_vehiculos_por_chofer`.
ACCIONES_PATENTE_SUGERIDA = ("USAR_PATENTE_EXISTENTE", "SELECCIONAR_OTRA_PATENTE")

# Radio dentro del cual una detención real sin planta identificada
# (`ORIGEN_GPS_ESTADIA_SIN_PLANTA`) se considera candidata plausible para
# SUGERIR una planta a un humano -- deliberadamente más amplio que el
# umbral usado para RESOLVER automáticamente (proporción de puntos dentro
# del polígono, o el radio de geocerca circular ya calibrado): una
# sugerencia para revisión humana nunca decide por sí sola, así que puede
# permitirse más candidatos plausibles sin ningún riesgo de adivinar. Se
# reutiliza el mismo valor (50.0 km) ya usado en todo
# `atlas_core.rutas.destino_entrega` como radio genérico de relevancia GPS
# -- no es un umbral nuevo, es el mismo ya establecido en este código base,
# reutilizado para un propósito distinto (sugerir, nunca resolver).
RADIO_CANDIDATO_ORIGEN_SUGERIDO_KM = 50.0

_PATRON_CONFLICTO_ORIGEN = re.compile(r"([A-Za-z0-9_]+):score=([\d.]+),solape=([\d.]+)%")


def _sha256(ruta: Path) -> str:
    digest = hashlib.sha256()
    with ruta.open("rb") as archivo:
        for bloque in iter(lambda: archivo.read(1024 * 1024), b""):
            digest.update(bloque)
    return digest.hexdigest().upper()


def _decision_id(*, tipo: str, documento: Mapping[str, str], campo: str,
                 valor_documental: str, evidencias: list[dict[str, object]]) -> str:
    identidad = {
        "schema_version": SCHEMA_VERSION,
        "tipo": tipo,
        "documento": dict(documento),
        "campo": campo,
        "valor_documental": valor_documental,
        "evidencias": evidencias,
    }
    serializado = json.dumps(
        identidad, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(serializado).hexdigest()


def crear_decision(
    *, tipo: str, entidad: str, archivo: str, numero_guia: str,
    numero_transporte: str, campo: str, valor_documental: str,
    valor_normalizado: str, identidad_resuelta: dict[str, object] | None,
    candidatos: Iterable[Mapping[str, object]], motivos: Iterable[str],
    evidencias: Iterable[Mapping[str, object]], acciones_permitidas: Iterable[str],
    contexto: dict[str, object] | None = None,
    tipo_resolucion: str | None = None,
    tipo_vehiculo_propuesto: str | None = None,
) -> dict[str, object]:
    """`contexto` (R3.1.3, opcional y aditivo): identidad de una entidad DE
    APOYO que Motor ya resolvió antes de emitir la decisión -- distinta de
    `identidad_resuelta`, que es la identidad de la propia entidad del
    campo (`valor_documental`). No participa en `decision_id`: la entidad
    de apoyo ya queda capturada en `evidencias` (p. ej. CLIENTE_RESUELTO),
    así que agregar/quitar sólo su nombre legible aquí no cambia qué
    pregunta representa la decisión."""
    if tipo not in TIPOS_SOPORTADOS:
        raise ValueError(f"tipo de decisión no soportado: {tipo}")
    documento = {
        "archivo": str(archivo),
        "numero_guia": str(numero_guia),
        "numero_transporte": str(numero_transporte),
    }
    evidencias_lista = [dict(evidencia) for evidencia in evidencias]
    decision = {
        "decision_id": _decision_id(
            tipo=tipo, documento=documento, campo=campo,
            valor_documental=str(valor_documental), evidencias=evidencias_lista,
        ),
        "estado": "PENDIENTE",
        "tipo": tipo,
        "entidad": entidad,
        "documento": documento,
        "campo": campo,
        "valor_documental": str(valor_documental),
        "valor_normalizado": str(valor_normalizado),
        "identidad_resuelta": identidad_resuelta,
        "contexto": dict(contexto) if contexto is not None else None,
        "candidatos": [dict(candidato) for candidato in candidatos],
        "motivos": [str(motivo) for motivo in motivos],
        "evidencias": evidencias_lista,
        "acciones_permitidas": [str(accion) for accion in acciones_permitidas],
    }
    if tipo == "VEHICULO_DESCONOCIDO":
        decision["tipo_resolucion"] = tipo_resolucion
        decision["tipo_vehiculo_propuesto"] = tipo_vehiculo_propuesto
    return decision


def _patente_documental_valida(valor: object) -> bool:
    patente = normalizar_patente_vehiculo(str(valor or ""))
    return bool(re.fullmatch(r"(?=.*[A-Z])(?=.*\d)[A-Z0-9]{6}", patente))


def actualizar_contrato_vehiculos_persistidos(
    decisiones: Iterable[Mapping[str, object]],
) -> list[dict[str, object]]:
    """Añade la clasificación R3.6.1 sin resolver ni descartar preguntas."""
    salida = [dict(d) for d in decisiones]
    documentos_con_rampla_valida = {
        tuple(sorted((d.get("documento") or {}).items()))
        for d in salida
        if d.get("tipo") == "VEHICULO_DESCONOCIDO"
        and d.get("campo") == "patente_rampla"
        and _patente_documental_valida(d.get("valor_documental"))
    }
    for decision in salida:
        if decision.get("tipo") != "VEHICULO_DESCONOCIDO":
            continue
        campo = decision.get("campo")
        documento = tuple(sorted((decision.get("documento") or {}).items()))
        if campo == "patente_rampla":
            decision["tipo_resolucion"] = "INEQUIVOCO"
            decision["tipo_vehiculo_propuesto"] = "CARRO"
        elif campo == "patente_tracto":
            # Bug real encontrado en producción (MOTOR DE EVIDENCIA FASE 3):
            # `documentos_con_rampla_valida` sólo mira las decisiones
            # `patente_rampla` TODAVÍA PENDIENTES en esta misma corrida --
            # si la decisión hermana de rampla ya se resolvió y salió de
            # la bandeja (caso real: 464265, rampla resuelta en el bloque
            # anterior), el tracto perdía su clasificación INEQUIVOCO y
            # dejaba de filtrar candidatos por tipo, permitiendo que una
            # patente CARRO apareciera como candidata para un campo
            # TRACTO. Una vez INEQUIVOCO/TRACTO, la clasificación nunca
            # se degrada -- sólo puede confirmarse o mantenerse, jamás
            # perderse porque un hermano ya fue respondido.
            si_ya_era_tracto_inequivoco = decision.get("tipo_vehiculo_propuesto") == "TRACTO"
            if documento in documentos_con_rampla_valida or si_ya_era_tracto_inequivoco:
                decision["tipo_resolucion"] = "INEQUIVOCO"
                decision["tipo_vehiculo_propuesto"] = "TRACTO"
            else:
                decision["tipo_resolucion"] = "REQUIERE_CONFIRMACION_HUMANA"
                decision["tipo_vehiculo_propuesto"] = None
    return salida


# Bloque VEHÍCULO E1 -- Motor de Evidencia de Vehículos. Primera capa de
# razonamiento determinista (NUNCA IA generativa/LLM) que combina señales
# YA existentes en el sistema -- catálogo, historial documental del
# dataset, confirmaciones humanas ya registradas, la corrección OCR ya
# calibrada de `resolver_patente` -- para explicar, con evidencia
# nombrada y auditable, por qué Atlas considera (o no) una patente
# candidata cuando la lectura documental no homologa. Nunca decide "por
# puntaje": cada candidata expone qué señales la respaldan y qué
# conflictos tiene; la clasificación final es una jerarquía de
# precedencia explicable, no una suma de pesos inventados.
NIVEL_CONFIRMACION_HUMANA = "CONFIRMACION_HUMANA"
NIVEL_DOCUMENTAL_INDEPENDIENTE = "DOCUMENTAL_INDEPENDIENTE"
NIVEL_DOCUMENTAL_DEBIL = "DOCUMENTAL_DEBIL"
_ORDEN_NIVEL_EVIDENCIA = {
    NIVEL_CONFIRMACION_HUMANA: 0, NIVEL_DOCUMENTAL_INDEPENDIENTE: 1, NIVEL_DOCUMENTAL_DEBIL: 2,
}

RESULTADO_RESUELTO_AUTOMATICAMENTE = "RESUELTO_AUTOMATICAMENTE"
RESULTADO_SUGERENCIA_HUMANA = "SUGERENCIA_HUMANA"
RESULTADO_ABSTENCION = "ABSTENCION"


def _transportes_por_patente_de_chofer(
    *, campo: str, filas: Iterable[Mapping[str, object]], rut_normalizado: str,
) -> dict[str, dict[str, set[str]]]:
    """Para cada patente observada del mismo RUT en `campo`, agrupa las
    guías por `numero_transporte` -- REGLA CRÍTICA (caso real Carlos
    Simón): la independencia de una evidencia se mide en TRANSPORTES
    distintos, nunca en documentos sueltos. Varios documentos del MISMO
    transporte son el mismo evento operacional (p. ej. 3 fotos de guías
    de un solo despacho) -- un mandante puede repetir el mismo error en
    cada una sin que eso sume tres verificaciones independientes.
    Repetición no equivale a independencia."""
    resultado: dict[str, dict[str, set[str]]] = {}
    for fila in filas:
        if normalizar_rut(str(fila.get("rut_chofer", ""))) != rut_normalizado:
            continue
        if str(fila.get("estado_procesamiento", "")).strip() != "OK":
            continue
        patente = normalizar_patente_vehiculo(str(fila.get(campo, "")))
        if not patente:
            continue
        transporte = str(fila.get("numero_transporte", "")).strip()
        guia = str(fila.get("numero_guia", "")).strip()
        resultado.setdefault(patente, {}).setdefault(transporte, set()).add(guia)
    return resultado


def _vehiculos_confirmados_para_rut(
    *, rut_normalizado: str, tipo_esperado: str | None, vehiculos: Iterable[object],
) -> set[str]:
    """Patentes CONFIRMADO/ACTIVO cuya evidencia de confirmación humana
    quedó explícitamente asociada a este RUT (`rut_chofer_asociado`, ver
    `confirmar_vehiculo`) -- nunca inferido: sólo lo que un humano ya
    dejó dicho explícitamente al confirmar ese vehículo."""
    resultado: set[str] = set()
    for v in vehiculos:
        if tipo_esperado and v.tipo != tipo_esperado:
            continue
        for e in v.evidencias:
            if (
                e.tipo == "CONFIRMACION_HUMANA"
                and normalizar_rut(str(e.campos_observados.get("rut_chofer_asociado", ""))) == rut_normalizado
            ):
                resultado.add(v.patente_canonica)
                break
    return resultado


def _razon_legible_candidato(*, patente: str, evidencias: tuple[str, ...], conflictos: tuple[str, ...], valor_documental: str) -> str:
    frases_evidencia = {
        "RUT_CHOFER_COINCIDE": "corresponde al mismo chofer/RUT",
        "TIPO_COMPATIBLE": "es un tipo de vehículo compatible",
        "CONFIRMACION_HUMANA_ASOCIADA_AL_CHOFER": "fue confirmada directamente por un humano para este chofer",
        "SIMILITUD_OCR_CALIBRADA": f"difiere de \"{valor_documental}\" en un solo carácter, dentro de las confusiones OCR ya conocidas",
    }
    frases_conflicto = {
        "OCR_ACTUAL_DIFIERE": f"el OCR de este documento leyó \"{valor_documental}\", un valor distinto",
        "TIPO_NO_DETERMINADO_SIN_CONFIRMACION": "el tipo de vehículo esperado en este documento todavía no está confirmado",
        # Bloque R11 -- honesto sobre la ausencia de historial de ESTE
        # chofer/RUT cuando la única evidencia es la similitud OCR contra
        # el catálogo completo (caso real 472247/JE4288 -> JF4288): nunca
        # se etiqueta como "RUT_CHOFER_COINCIDE" algo que no corroboró
        # ningún documento de este chofer.
        "SIN_HISTORIAL_PARA_ESTE_RUT": "ningún otro documento de este chofer corrobora esta patente todavía",
    }
    razones = [frases_evidencia[e] for e in evidencias if e in frases_evidencia]
    razones += [f"corroborada por {e.split('(')[1].rstrip(')')} transporte(s) independiente(s)" for e in evidencias if e.startswith("CORROBORACION_TRANSPORTE_INDEPENDIENTE")]
    if any(e == "CORROBORACION_MISMO_TRANSPORTE" for e in evidencias):
        razones.append("aparece en otro documento del mismo transporte (no es una fuente independiente)")
    texto = f"Atlas considera \"{patente}\" porque " + "; ".join(razones) + "." if razones else f"Atlas encontró \"{patente}\" sin evidencia suficiente."
    if conflictos:
        texto += " Sin embargo, " + "; ".join(frases_conflicto.get(c, c) for c in conflictos) + "."
    return texto


def evaluar_evidencia_patente(
    *, campo: str, valor_documental: str, rut_chofer: str, tipo_esperado: str | None,
    numero_transporte_actual: str, filas: Iterable[Mapping[str, object]], vehiculos: Iterable[object],
) -> dict[str, object]:
    """Bloque VEHÍCULO E1 -- combina, de forma determinista y auditable,
    todas las señales ya disponibles en el sistema para explicar (nunca
    autocorregir) una patente documental que no homologa con el
    catálogo. Devuelve SIEMPRE uno de tres resultados:

    - `RESUELTO_AUTOMATICAMENTE`: existe una única candidata con
      evidencia de más alto nivel (`CONFIRMACION_HUMANA` -- un humano ya
      confirmó explícitamente esa patente PARA este mismo chofer/RUT) y
      ninguna otra candidata compite en ese mismo nivel. Esta
      clasificación es puramente informativa/explicativa -- NUNCA aplica
      nada por sí sola; la escritura sigue exigiendo la acción humana ya
      existente (`USAR_PATENTE_EXISTENTE`/`SELECCIONAR_OTRA_PATENTE`).
    - `SUGERENCIA_HUMANA`: existe evidencia real pero no alcanza el
      nivel anterior sin ambigüedad (un único candidato documental, o
      candidatos empatados en el mismo nivel -- nunca se elige entre
      ellos arbitrariamente).
    - `ABSTENCION`: no hay ningún candidato con evidencia relevante.

    Bloque R11: además del historial de este chofer/RUT, también se
    consideran patentes CONFIRMADAS/ACTIVAS de todo el catálogo cuya única
    diferencia con el valor documental es una confusión OCR calibrada
    (`_diferencia_ocr_segura`) -- sólo cuando el tipo de vehículo esperado
    ya es INEQUIVOCO (nunca sin tipo conocido). Nunca alcanzan
    `RESUELTO_AUTOMATICAMENTE` por sí solas (ese nivel exige evidencia de
    `CONFIRMACION_HUMANA` asociada al RUT, que estas no tienen) -- siempre
    quedan como `SUGERENCIA_HUMANA`, auditables (`SIN_HISTORIAL_PARA_ESTE_RUT`
    como conflicto explícito), y compiten entre sí igual que cualquier otra
    candidata si más de una patente del catálogo calza.

    Nunca usa repetición documental como prueba de verdad (un mandante
    puede repetir el mismo error en cada documento de un único
    transporte -- ver `_transportes_por_patente_de_chofer`), nunca
    convierte similitud de texto en autocorrección por sí sola (la
    corrección OCR seguro-calibrada de `resolver_patente`/
    `_diferencia_ocr_segura` es sólo UNA evidencia adicional entre
    varias, nunca decide sola)."""
    rut_normalizado = normalizar_rut(rut_chofer)
    valor_norm = normalizar_patente_vehiculo(str(valor_documental or ""))
    if not rut_normalizado or not valor_norm:
        return {
            "resultado": RESULTADO_ABSTENCION, "candidatos": [],
            "explicacion": "Sin RUT de chofer o valor documental disponible -- no hay evidencia con la que razonar.",
        }

    vehiculos = list(vehiculos)
    filas = list(filas)
    transportes_por_patente = _transportes_por_patente_de_chofer(
        campo=campo, filas=filas, rut_normalizado=rut_normalizado,
    )
    confirmadas_para_rut = _vehiculos_confirmados_para_rut(
        rut_normalizado=rut_normalizado, tipo_esperado=tipo_esperado, vehiculos=vehiculos,
    )
    homologables_por_patente = {
        v.patente_canonica: v for v in vehiculos
        if v.estado_calidad == "CONFIRMADO" and v.estado_vigencia == "ACTIVO"
    }

    # Bloque R11 -- caso real 472247 (Rodrigo Nahuelñir, JE4288 -> JF4288):
    # hasta este bloque, un chofer SIN ningún documento hermano (ni en este
    # dataset ni en el ledger) nunca podía recibir ninguna candidata --
    # `_diferencia_ocr_segura` ya existía como señal, pero sólo se
    # evaluaba sobre candidatas que YA venían del historial de RUT, nunca
    # ampliaba el universo por sí sola. Ahora también se consideran las
    # patentes CONFIRMADAS/ACTIVAS de TODO el catálogo que difieren del
    # valor documental en una única confusión OCR calibrada -- sólo
    # cuando el tipo de vehículo esperado ya es INEQUIVOCO (nunca a
    # ciegas, sin tipo conocido: demasiado universo, demasiado riesgo de
    # ambigüedad). Si más de una patente del catálogo compite en este
    # nivel, ninguna gana sola -- misma regla de empate ya vigente más
    # abajo (nunca elige por Atlas).
    patentes_ocr_similares = (
        {
            patente for patente, vehiculo in homologables_por_patente.items()
            if vehiculo.tipo == tipo_esperado and _diferencia_ocr_segura(valor_norm, patente)
        }
        if tipo_esperado else set()
    )

    patentes_candidatas = (set(transportes_por_patente) | confirmadas_para_rut | patentes_ocr_similares) - {valor_norm}
    candidatos: list[dict[str, object]] = []
    for patente in sorted(patentes_candidatas):
        vehiculo = homologables_por_patente.get(patente)
        if vehiculo is None:
            continue  # no confirmado/activo -- ruido documental, no candidata real
        if tipo_esperado and vehiculo.tipo != tipo_esperado:
            continue  # tipo incompatible -- nunca gana, aunque tenga otra evidencia

        transportes = transportes_por_patente.get(patente, {})
        independientes = {t for t in transportes if t and t != numero_transporte_actual}
        n_independientes = len(independientes)
        guias = sorted({g for grupo in transportes.values() for g in grupo})
        referencias_fuente = [
            {
                "numero_guia": guia,
                "numero_transporte": transporte,
                "relacion_evento": (
                    "MISMO_TRANSPORTE" if transporte == numero_transporte_actual
                    else "TRANSPORTE_INDEPENDIENTE"
                ),
            }
            for transporte, guias_transporte in sorted(transportes.items())
            for guia in sorted(guias_transporte)
        ]

        tiene_historial_rut = bool(transportes) or patente in confirmadas_para_rut
        evidencias: list[str] = (["RUT_CHOFER_COINCIDE"] if tiene_historial_rut else []) + ["TIPO_COMPATIBLE"]
        conflictos: list[str] = ["OCR_ACTUAL_DIFIERE"]
        if not tiene_historial_rut:
            conflictos.append("SIN_HISTORIAL_PARA_ESTE_RUT")
        if not tipo_esperado:
            conflictos.append("TIPO_NO_DETERMINADO_SIN_CONFIRMACION")
        if n_independientes >= 1:
            evidencias.append(f"CORROBORACION_TRANSPORTE_INDEPENDIENTE({n_independientes})")
        elif transportes:
            evidencias.append("CORROBORACION_MISMO_TRANSPORTE")
        es_confirmacion_directa = patente in confirmadas_para_rut
        if es_confirmacion_directa:
            evidencias.append("CONFIRMACION_HUMANA_ASOCIADA_AL_CHOFER")
        if _diferencia_ocr_segura(valor_norm, patente):
            evidencias.append("SIMILITUD_OCR_CALIBRADA")

        if es_confirmacion_directa:
            nivel = NIVEL_CONFIRMACION_HUMANA
        elif n_independientes >= 1:
            nivel = NIVEL_DOCUMENTAL_INDEPENDIENTE
        else:
            nivel = NIVEL_DOCUMENTAL_DEBIL

        candidatos.append({
            "patente": patente, "vehiculo_id": vehiculo.vehiculo_id, "tipo_vehiculo": vehiculo.tipo,
            "nivel": nivel, "evidencias": tuple(evidencias), "conflictos": tuple(conflictos),
            "guias": guias, "transportes_independientes": n_independientes,
            "referencias_fuente": referencias_fuente,
            "razon_legible": _razon_legible_candidato(
                patente=patente, evidencias=tuple(evidencias), conflictos=tuple(conflictos), valor_documental=valor_documental,
            ),
            # Compatibilidad con el contrato ya publicado (Bloque VEHÍCULO D1):
            # mismas claves que ya consumen aplicar_decision_obra/Desktop.
            "evidencia_resumen": _razon_legible_candidato(
                patente=patente, evidencias=tuple(evidencias), conflictos=tuple(conflictos), valor_documental=valor_documental,
            ),
        })

    candidatos.sort(key=lambda c: (_ORDEN_NIVEL_EVIDENCIA[c["nivel"]], -c["transportes_independientes"], c["patente"]))

    if not candidatos:
        return {
            "resultado": RESULTADO_ABSTENCION, "candidatos": [],
            "explicacion": f"No puedo determinarlo con seguridad: ningún vehículo confirmado/activo asociado a este RUT tiene evidencia relevante para \"{valor_documental}\".",
        }

    mejor_nivel = candidatos[0]["nivel"]
    competidores_mejor_nivel = [c for c in candidatos if c["nivel"] == mejor_nivel]
    # Bloque VEHÍCULO E2 -- caso real 472339 (Cristopher Retamal, RUT
    # 17576134-9): OCR leyó "BPHF67"; el chofer tiene DOS transportes
    # independientes previos (472037, 472227) con "BPHR67" -- evidencia
    # DOCUMENTAL_INDEPENDIENTE genuina, no repetición del mismo documento
    # -- y "BPHF67"/"BPHR67" difieren en una única confusión OCR
    # calibrada. Antes de este bloque, DOCUMENTAL_INDEPENDIENTE nunca
    # podía resolver solo (sólo CONFIRMACION_HUMANA lo hacía), así que
    # esta patente quedaba siempre en SUGERENCIA_HUMANA aunque no hubiera
    # ningún candidato competidor.
    #
    # Se agrega DOCUMENTAL_INDEPENDIENTE como segundo nivel que también
    # puede resolver solo -- pero SÓLO cuando, además de ser el único
    # candidato en el nivel más alto, el propio candidato trae
    # `SIMILITUD_OCR_CALIBRADA`: el valor documental de ESTE documento
    # tiene que ser una lectura OCR plausible del canónico, no sólo "un
    # vehículo que este chofer usó alguna vez". Esto es deliberado --
    # evita que un histórico viejo se imponga cuando el chofer
    # simplemente cambió de vehículo (la patente nueva, genuina, no se
    # parece a ninguna anterior y por lo tanto nunca gana
    # `SIMILITUD_OCR_CALIBRADA` contra sí misma).
    resuelve_automaticamente = len(competidores_mejor_nivel) == 1 and (
        mejor_nivel == NIVEL_CONFIRMACION_HUMANA
        or (
            mejor_nivel == NIVEL_DOCUMENTAL_INDEPENDIENTE
            and "SIMILITUD_OCR_CALIBRADA" in competidores_mejor_nivel[0]["evidencias"]
        )
    )
    if resuelve_automaticamente:
        resultado = RESULTADO_RESUELTO_AUTOMATICAMENTE
        explicacion = candidatos[0]["razon_legible"]
    else:
        resultado = RESULTADO_SUGERENCIA_HUMANA
        if len(competidores_mejor_nivel) > 1:
            nombres = ", ".join(f'"{c["patente"]}"' for c in competidores_mejor_nivel)
            explicacion = f"Hay {len(competidores_mejor_nivel)} candidatas con evidencia comparable ({nombres}) -- Atlas no elige entre ellas, requiere confirmación humana."
        else:
            explicacion = candidatos[0]["razon_legible"]

    return {"resultado": resultado, "candidatos": candidatos, "explicacion": explicacion}


def sugerir_vehiculos_por_chofer(
    *, rut_chofer: str, campo: str, valor_documental: str,
    filas: Iterable[Mapping[str, object]], vehiculos: Iterable[object],
) -> list[dict[str, object]]:
    """Envoltorio de compatibilidad (Bloque VEHÍCULO D1, ya publicado):
    devuelve sólo la lista de `candidatos` del motor de evidencia
    (Bloque VEHÍCULO E1, `evaluar_evidencia_patente`), sin `tipo_esperado`
    ni `numero_transporte_actual` (se asumen desconocidos -- comportamiento
    más permisivo que el motor completo, preservado para no romper
    llamadores existentes)."""
    resultado = evaluar_evidencia_patente(
        campo=campo, valor_documental=valor_documental, rut_chofer=rut_chofer,
        tipo_esperado=None, numero_transporte_actual="",
        filas=filas, vehiculos=vehiculos,
    )
    return [dict(c) for c in resultado["candidatos"]]


def enriquecer_decisiones_vehiculo(
    *, decisiones: Iterable[Mapping[str, object]],
    filas: Iterable[Mapping[str, object]], vehiculos: Iterable[object],
) -> list[dict[str, object]]:
    """Bloque VEHÍCULO D1/E1 -- añade `candidatos`/acciones adicionales a
    decisiones `VEHICULO_DESCONOCIDO` YA generadas (nunca las crea desde
    cero: reutiliza exactamente lo que `detectar_decisiones_documento` ya
    produjo). Decisiones de otros tipos pasan sin cambios. Usa el motor
    de evidencia completo (`evaluar_evidencia_patente`), con `tipo_esperado`
    tomado de `tipo_vehiculo_propuesto` (ya calculado por
    `actualizar_contrato_vehiculos_persistidos`) y el `numero_transporte`
    real del documento -- nunca se abstiene de aplicar el filtro de tipo
    ni de excluir el propio transporte como "evidencia independiente".

    SIEMPRE recalcula (nunca se detiene sólo porque la decisión ya trae
    `candidatos` de una corrida anterior): el catálogo puede haber ganado
    una confirmación humana nueva (p. ej. una patente recién confirmada y
    asociada a este RUT de chofer) desde la última vez que se enriqueció
    esta misma decisión, y esa evidencia nueva debe reflejarse la próxima
    vez que se reconcilie la bandeja -- sin esto, una decisión que ya
    tenía candidatos documentales débiles quedaría congelada para
    siempre en esa clasificación, aunque después aparezca una
    confirmación humana directa. `decision_id` no depende de `candidatos`
    (ver `_decision_id`/`crear_decision`), así que recalcularlos nunca
    resucita una decisión ya cerrada en el ledger ni le cambia identidad.
    Idempotente: recalcular con los mismos datos produce el mismo
    resultado."""
    filas = list(filas)
    vehiculos = list(vehiculos)
    filas_por_guia: dict[str, dict[str, object]] = {}
    for fila in filas:
        guia = str(fila.get("numero_guia", ""))
        if guia and guia not in filas_por_guia:
            filas_por_guia[guia] = fila

    salida: list[dict[str, object]] = []
    for decision_original in decisiones:
        decision = dict(decision_original)
        if decision.get("tipo") == "VEHICULO_DESCONOCIDO":
            documento = decision.get("documento") or {}
            guia = str(documento.get("numero_guia", ""))
            transporte = str(documento.get("numero_transporte", ""))
            fila = filas_por_guia.get(guia)
            rut = str(fila.get("rut_chofer", "")).strip() if fila else ""
            if rut:
                evaluacion = evaluar_evidencia_patente(
                    campo=str(decision.get("campo", "")), valor_documental=str(decision.get("valor_documental", "")),
                    rut_chofer=rut, tipo_esperado=decision.get("tipo_vehiculo_propuesto"),
                    numero_transporte_actual=transporte, filas=filas, vehiculos=vehiculos,
                )
                sugeridos = evaluacion["candidatos"]
                decision["candidatos"] = sugeridos
                decision["evaluacion_evidencia"] = {
                    "resultado": evaluacion["resultado"], "explicacion": evaluacion["explicacion"],
                }
                # Base limpia -- nunca acumula sobre acciones ya agregadas
                # en una corrida anterior (evita duplicados y permite que
                # unas candidatas que desaparecieron también retiren las
                # acciones que ya no corresponden).
                base = [a for a in (decision.get("acciones_permitidas") or ACCIONES_ENTIDAD_DESCONOCIDA) if a not in ACCIONES_PATENTE_SUGERIDA]
                if sugeridos:
                    nuevas = [a for a in ACCIONES_PATENTE_SUGERIDA if a not in base]
                    if "POSPONER" in base:
                        indice = base.index("POSPONER")
                        base[indice:indice] = nuevas
                    else:
                        base.extend(nuevas)
                decision["acciones_permitidas"] = base
        salida.append(decision)
    return salida


def rut_documental_de_decision_cliente(decision: Mapping[str, object]) -> str:
    """Extrae el RUT documental crudo que `detectar_decisiones_documento`
    ya guardó en `evidencias` (tipo `RUT_EXACTO`/`RUT_VALIDO`) de una
    decisión `CLIENTE_DESCONOCIDO`/`ALIAS_CANDIDATO` -- el CSV consolidado
    NO retiene RUT de cliente por guía (sólo el nombre ya resuelto), así
    que ésta es la única fuente disponible al reconciliar la bandeja."""
    for evidencia in decision.get("evidencias") or ():
        if evidencia.get("tipo") in ("RUT_EXACTO", "RUT_VALIDO") and evidencia.get("campo") == "rut_cliente":
            return str(evidencia.get("valor", ""))
    return ""


def enriquecer_decisiones_cliente(
    *, decisiones: Iterable[Mapping[str, object]], clientes: Iterable[object],
    confirmaciones: Iterable[ConfirmacionIdentidad] = (),
    evidencia_externa_por_clave: Mapping[str, tuple[EvidenciaExterna, ...]] | None = None,
) -> list[dict[str, object]]:
    """Bloque MOTOR DE EVIDENCIA FASE 3 -- enriquece decisiones
    `CLIENTE_DESCONOCIDO`/`ALIAS_CANDIDATO` YA generadas por
    `detectar_decisiones_documento` (nunca las crea desde cero, nunca
    reemplaza `_identidad_cliente_por_rut`) con la clasificación completa
    del motor de evidencia -- puramente informativo (`evaluacion_evidencia`/
    `candidatos_evidencia`), nunca cambia qué acciones puede aplicar el
    humano: `ALIAS_CANDIDATO` ya tiene `CONFIRMAR_ALIAS` para vincular la
    canónica sugerida (ver `aplicar_decision_obra`, que ahora usa la
    evidencia para decidir SI además registra una Incidencia Documental).
    SIEMPRE recalcula (mismo motivo que `enriquecer_decisiones_vehiculo`:
    una confirmación humana nueva debe reflejarse la próxima vez que se
    reconcilie la bandeja, no quedar congelada)."""
    evidencia_externa_por_clave = evidencia_externa_por_clave or {}
    confirmaciones = list(confirmaciones)
    salida: list[dict[str, object]] = []
    for decision_original in decisiones:
        decision = dict(decision_original)
        if decision.get("entidad") == "CLIENTE" and decision.get("tipo") in ("CLIENTE_DESCONOCIDO", "ALIAS_CANDIDATO"):
            rut_doc = rut_documental_de_decision_cliente(decision)
            documental = str(decision.get("valor_documental", ""))
            evidencia_externa = evidencia_externa_por_clave.get(normalizar_nombre_cliente(documental), ())
            evaluacion = evaluar_evidencia_cliente(
                razon_social_documental=documental, rut_documental=rut_doc,
                numero_guia=str((decision.get("documento") or {}).get("numero_guia", "")),
                numero_transporte=str((decision.get("documento") or {}).get("numero_transporte", "")),
                clientes=clientes, confirmaciones=confirmaciones, evidencia_externa=evidencia_externa,
            )
            decision["evaluacion_evidencia"] = {"resultado": evaluacion.resultado, "explicacion": evaluacion.explicacion}
            decision["candidatos_evidencia"] = [c.a_dict() for c in evaluacion.candidatos]
        salida.append(decision)
    return salida


def enriquecer_decisiones_obra(
    *, decisiones: Iterable[Mapping[str, object]], obras: Iterable[object],
    evidencia_externa_por_clave: Mapping[str, tuple[EvidenciaExterna, ...]] | None = None,
) -> list[dict[str, object]]:
    """Mismo patrón que `enriquecer_decisiones_cliente`, para
    `OBRA_DESCONOCIDA`. `obras` es la lista completa del catálogo -- se
    filtra aquí por `contexto.cliente_id` de cada decisión (misma obra
    global, evidencia por cliente)."""
    evidencia_externa_por_clave = evidencia_externa_por_clave or {}
    obras = list(obras)
    salida: list[dict[str, object]] = []
    for decision_original in decisiones:
        decision = dict(decision_original)
        if decision.get("tipo") == "OBRA_DESCONOCIDA":
            contexto = decision.get("contexto") or {}
            cliente_id = str(contexto.get("cliente_id", ""))
            documental = str(decision.get("valor_documental", ""))
            obras_mismo_cliente = tuple(
                o for o in obras
                if getattr(o, "cliente_id", None) == cliente_id and getattr(o, "estado_vigencia", None) == "ACTIVO"
            )
            evidencia_externa = evidencia_externa_por_clave.get(normalizar_nombre_obra(documental), ())
            # Bloque 472339/CASA HELSINSKI -- la misma dirección
            # documental ya resuelta que `OBRA_DESCONOCIDA` transporta
            # para poder generar, después de REGISTRAR, la pregunta de
            # destino (`decision_destino_para_obra_registrada`); acá se
            # reutiliza como corroboración cruzada contra evidencia
            # externa, nunca se vuelve a resolver ni a leer el documento.
            evaluacion = evaluar_evidencia_obra(
                nombre_documental=documental, obras_confirmadas_mismo_cliente=obras_mismo_cliente,
                evidencia_externa=evidencia_externa,
                direccion_documental_resuelta=str(contexto.get("destino_documental", "")),
            )
            decision["evaluacion_evidencia"] = {"resultado": evaluacion.resultado, "explicacion": evaluacion.explicacion}
            decision["candidatos_evidencia"] = [c.a_dict() for c in evaluacion.candidatos]
        salida.append(decision)
    return salida


def _identidad_cliente_por_rut(carpeta: Path, rut: str):
    try:
        normalizado = normalizar_rut_cliente(rut)
        coincidencias = [
            cliente for cliente in CatalogoClientes(carpeta / "clientes.json").listar()
            if cliente.rut == normalizado
            and cliente.estado_calidad == EstadoCalidadCliente.CONFIRMADO.value
            and cliente.estado_vigencia == EstadoVigenciaCliente.ACTIVO.value
        ]
        return coincidencias[0] if len(coincidencias) == 1 else None
    except (OSError, ValueError):
        return None


def _decisiones_obra_para_cliente(
    *, carpeta: Path, cliente_id: str, cliente_razon_social: str,
    cliente_aliases: Iterable[str], obra_texto: str, despachar_a_documental: str,
    comunes: Mapping[str, str],
) -> list[dict[str, object]]:
    """Bloque OBRA_DESCONOCIDA/DESTINO_SIN_CONFIRMAR -- extraído de
    `detectar_decisiones_documento` (R4.8) para poder reutilizarse tal
    cual desde la reconciliación `sin_ocr` que encadena la pregunta de
    obra/destino DESPUÉS de que un `CLIENTE_CANDIDATO` se confirma (ver
    `revalidacion_documental.detectar_decisiones_obra_para_cliente_confirmado_sin_ocr`).
    Recibe la identidad de cliente YA RESUELTA (por RUT en la corrida
    original, o por confirmación humana posterior) -- nunca decide
    identidad, sólo la pregunta de obra/destino que depende de ella."""
    decisiones: list[dict[str, object]] = []
    if obra_texto in _AUSENTES:
        return decisiones
    try:
        catalogo_obras = CatalogoObrasDestinos(
            ruta=carpeta / "obras_destinos.json",
            ruta_clientes=carpeta / "clientes.json",
            ruta_destinos=carpeta / "destinos_maestros.json",
        )
        clave = normalizar_nombre_obra(obra_texto)
        # R3.3.1: obra = identidad GLOBAL -- la búsqueda ya NO filtra por
        # cliente_id. Una obra observada antes para cualquier cliente se
        # reconoce igual para éste (comparación exacta normalizada,
        # sin fuzzy).
        obras = [
            obra for obra in catalogo_obras.listar_obras()
            if obra.estado_vigencia == EstadoVigencia.ACTIVO.value
            and clave in {
                normalizar_nombre_obra(obra.nombre_canonico),
                *(normalizar_nombre_obra(alias) for alias in obra.aliases_documentales),
            }
        ]
        # R3.2: si el valor documental de "obra" es, en realidad, el
        # propio cliente ya reconocido (comparación exacta normalizada,
        # sin fuzzy -- misma normalización que ya usa este bloque para
        # `clave`), no hay ninguna obra nueva que preguntar: es el mismo
        # hecho dos veces, no dos entidades. Genérico para cualquier
        # cliente, sin hardcode.
        claves_cliente = {
            normalizar_nombre_obra(cliente_razon_social),
            *(normalizar_nombre_obra(alias) for alias in cliente_aliases),
        }
        # Bloque FIX DE ACEPTACION -- caso real 460861 (SALOMON SACK SA
        # SAN BERNGARDO vs la obra ya CONFIRMADA "SALOMON SACK SA SAN
        # BERNARDO"): antes de concluir "obra nueva", se compara contra
        # las obras ya CONFIRMADAS de ESTE MISMO cliente (contexto como
        # evidencia auxiliar, Bloque SEGURIDAD) usando una variación
        # ortográfica/OCR MÍNIMA de un solo token
        # (`resolver_obra_por_variacion_ortografica_menor` --
        # deliberadamente estrecho, nunca "fuzzy matching" agresivo; se
        # abstiene solo si hay más de un candidato plausible). Sólo se
        # intenta cuando la comparación exacta de arriba (incluye alias
        # ya aprendidos) y la comparación cliente==obra ya fallaron --
        # nunca reemplaza esas vías, sólo se agrega después de ellas.
        if not obras and clave not in claves_cliente:
            obras_confirmadas_mismo_cliente = tuple(
                obra for obra in catalogo_obras.listar_obras()
                if obra.cliente_id == cliente_id
                and obra.estado == EstadoObra.CONFIRMADA.value
                and obra.estado_vigencia == EstadoVigencia.ACTIVO.value
            )
            obra_por_variacion = resolver_obra_por_variacion_ortografica_menor(
                nombre_documental=obra_texto,
                obras_confirmadas_mismo_cliente=obras_confirmadas_mismo_cliente,
            )
            if obra_por_variacion is not None:
                obras = [obra_por_variacion]
        if not obras and clave in claves_cliente:
            pass
        elif not obras:
            decisiones.append(crear_decision(
                tipo="OBRA_DESCONOCIDA", entidad="OBRA", campo="obra_destino",
                valor_documental=obra_texto, valor_normalizado=clave,
                identidad_resuelta=None, candidatos=(),
                motivos=("OBRA_NO_EXISTE_PARA_CLIENTE",),
                evidencias=({"tipo": "CLIENTE_RESUELTO", "entidad_id": cliente_id},),
                acciones_permitidas=ACCIONES_ENTIDAD_DESCONOCIDA,
                # R3.1.3: nombre legible de la identidad de cliente que
                # YA resolvió Motor (misma fuente que `identidad_cliente`
                # más arriba, nunca inferido de `obra_texto`) -- se
                # conserva como evidencia operacional de quién observó
                # esta obra, no como su propietario.
                # R3.4.2: `destino_documental` (dirección ya resuelta por
                # `resolver_entrega_documento`, la misma fuente que ya usa
                # DESTINO_SIN_CONFIRMAR más abajo) viaja aquí también --
                # la obra todavía no existe, así que hoy no puede
                # generarse la pregunta de destino, pero cuando Javier
                # REGISTRE esta obra, `aplicar_decision_obra` la necesita
                # para poder generar el siguiente paso sin volver a leer
                # el documento (ver decision_destino_para_obra_registrada).
                contexto={
                    "cliente_id": cliente_id,
                    "cliente_canonico": cliente_razon_social,
                    "destino_documental": str(despachar_a_documental or "").strip(),
                },
                **comunes,
            ))
        elif len(obras) > 1:
            # Ambigüedad global (no debería ocurrir tras la migración a
            # unicidad global -- ver CatalogoObrasDestinos): Atlas se
            # abstiene en vez de adivinar cuál es la obra correcta.
            pass
        # Bloque FIX DE ACEPTACION -- se consulta con el nombre CANÓNICO
        # de la obra ya resuelta (`obras[0]`), nunca con `obra_texto` sin
        # procesar: cuando la obra se resolvió por variación ortográfica
        # menor (arriba), `obra_texto` sigue siendo el texto documental
        # ORIGINAL (con el typo) -- una búsqueda exacta con ese texto
        # fallaría de nuevo y generaría una pregunta de destino
        # redundante pese a que la obra (y, en este caso real, la ruta)
        # ya están resueltas.
        elif catalogo_obras.resolver_obra_destino_confirmada(
            cliente_id=cliente_id, nombre_obra=obras[0].nombre_canonico
        ) is None:
            obra = obras[0]
            destino_texto = str(despachar_a_documental or "").strip()
            # R3.4: la obra ya se conoce (identidad_resuelta); lo único
            # pendiente es confirmar la relación con ESTE destino. El
            # valor de la decisión pasa a ser el destino documental (lo
            # que Atlas todavía no sabe), no la obra (lo que ya sabe) --
            # `contexto` transporta cliente y obra ya resueltos, tal como
            # ya usa OBRA_DESCONOCIDA para el cliente.
            decisiones.append(crear_decision(
                tipo="DESTINO_SIN_CONFIRMAR", entidad="RELACION_OBRA_DESTINO",
                campo="destino_entrega",
                valor_documental=destino_texto or obra_texto,
                valor_normalizado=(
                    normalizar_nombre_destino(destino_texto) if destino_texto else clave
                ),
                identidad_resuelta={
                    "entidad_id": obra.obra_id,
                    "valor_canonico": obra.nombre_canonico,
                },
                candidatos=(), motivos=("OBRA_SIN_RELACION_CONFIRMADA_UNICA",),
                evidencias=({"tipo": "OBRA_IDENTIFICADA", "entidad_id": obra.obra_id},),
                acciones_permitidas=ACCIONES_DESTINO_SIN_CONFIRMAR,
                contexto={
                    "cliente_id": cliente_id,
                    "cliente_canonico": cliente_razon_social,
                    "obra_id": obra.obra_id,
                    "obra_canonica": obra.nombre_canonico,
                    "destino_documental": destino_texto,
                },
                **comunes,
            ))
    except (OSError, ValueError):
        pass
    return decisiones


def detectar_decisiones_documento(
    *, archivo: str, datos: Mapping[str, object], carpeta_catalogos: str | Path,
    cliente_documental_original: str = "", despachar_a_documental: str = "",
) -> list[dict[str, object]]:
    """Detecta incertidumbres por el estado final, no por la ruta OCR usada."""
    carpeta = Path(carpeta_catalogos)
    guia = str(datos.get("número de guía", ""))
    transporte = str(datos.get("número de transporte", ""))
    comunes = {"archivo": archivo, "numero_guia": guia, "numero_transporte": transporte}
    decisiones: list[dict[str, object]] = []
    rampla_documental_valida = _patente_documental_valida(datos.get("patente del carro", ""))
    # R4: mismo catálogo que ya carga `resolver_patente` más abajo, leído
    # una sola vez aquí -- sólo para poder mirar el TIPO de una identidad ya
    # exacta antes de decidir el filtro, nunca para elegir entre candidatos.
    try:
        vehiculos_por_patente_tracto = {
            v.patente_canonica: v
            for v in cargar_catalogo_vehiculos(carpeta / "vehiculos.json").homologables()
        }
    except (OSError, ValueError):
        vehiculos_por_patente_tracto = {}

    for campo, clave_dato, tipo_esperado in (
        ("patente_tracto", "patente del tracto", "TRACTO"),
        ("patente_rampla", "patente del carro", "CARRO"),
    ):
        valor = str(datos.get(clave_dato, "")).strip()
        if valor in _AUSENTES:
            continue
        # R4 (paridad con `procesamiento_masivo.procesar_archivo` P2 y con
        # `revalidar_patente_sin_homologar_sin_ocr`): una patente_tracto
        # AISLADA (sin rampla documental) puede ser un TRACTO articulado o
        # un CAMION_RIGIDO -- las otras dos capas del pipeline ya tratan
        # ambos tipos como compatibles con ese rol documental. Antes de
        # este fix, sólo esta función seguía filtrando por TRACTO exclusivo,
        # así que una patente YA CONFIRMADA como CAMION_RIGIDO (documento ya
        # homologado a OK por P2) volvía a generar aquí una decisión
        # VEHICULO_DESCONOCIDO -- Revisión de Atlas contradiciendo a Viajes
        # para el mismo documento en la misma corrida. Se resuelve primero
        # SIN restricción de tipo (sólo para leer la identidad EXACTA ya
        # conocida, nunca para elegir entre varias) y sólo si esa identidad
        # exacta es TRACTO o CAMION_RIGIDO se usa como filtro efectivo --
        # nunca se afloja el filtro para una coincidencia ambigua ni para
        # aceptar CARRO en este campo.
        tipo_efectivo = tipo_esperado
        if campo == "patente_tracto" and not rampla_documental_valida:
            identidad_sin_tipo = resolver_patente(carpeta / "vehiculos.json", valor)
            vehiculo_exacto = vehiculos_por_patente_tracto.get(identidad_sin_tipo.valor_resultado)
            if (
                identidad_sin_tipo.estado in {"COINCIDENCIA_EXACTA", "ALIAS"}
                and vehiculo_exacto is not None
                and vehiculo_exacto.tipo in {"TRACTO", "CAMION_RIGIDO"}
            ):
                tipo_efectivo = vehiculo_exacto.tipo
        resultado = resolver_patente(
            carpeta / "vehiculos.json", valor, tipo_esperado=tipo_efectivo
        )
        if resultado.estado in {"SIN_CANDIDATO", "CATALOGO_VACIO"}:
            # R3.2: "esta patente no está registrada en Atlas" es toda la
            # pregunta -- Atlas no conoce la entidad, así que sólo tiene
            # sentido Registrar/No registrar (regla de Javier). Una posible
            # corrección OCR contra una patente YA existente (estado
            # CORRECCION_OCR_SEGURA de resolver_patente) es un caso distinto
            # que hoy no genera ninguna decisión -- deliberadamente no se
            # mezcla aquí; quedaría para un tipo de decisión futuro y
            # específico.
            decisiones.append(crear_decision(
                tipo="VEHICULO_DESCONOCIDO", entidad="VEHICULO", campo=campo,
                valor_documental=valor, valor_normalizado=resultado.valor_resultado,
                identidad_resuelta=None, candidatos=(),
                motivos=("SIN_VEHICULO_CONFIRMADO_COMPATIBLE",),
                evidencias=({"tipo": "OCR_DOCUMENTAL", "campo": campo, "valor": valor},),
                acciones_permitidas=ACCIONES_ENTIDAD_DESCONOCIDA,
                tipo_resolucion=(
                    "INEQUIVOCO" if campo == "patente_rampla" or rampla_documental_valida
                    else "REQUIERE_CONFIRMACION_HUMANA"
                ),
                tipo_vehiculo_propuesto=(
                    "CARRO" if campo == "patente_rampla"
                    else ("TRACTO" if rampla_documental_valida else None)
                ),
                **comunes,
            ))

    cliente_final = str(datos.get("cliente", "")).strip()
    cliente_documental = str(cliente_documental_original or cliente_final).strip()
    rut_cliente = str(datos.get("RUT del cliente", "")).strip()
    cliente = _identidad_cliente_por_rut(carpeta, rut_cliente)
    rut_valido = validar_rut_chileno(rut_cliente).estado == EstadoValidacion.VALIDO
    identidad_cliente = None
    if cliente is not None:
        identidad_cliente = {
            "entidad_id": cliente.cliente_id,
            "valor_canonico": cliente.razon_social,
            "rut": cliente.rut,
        }
        claves_confirmadas = {
            normalizar_nombre_cliente(cliente.razon_social),
            *(normalizar_nombre_cliente(alias) for alias in cliente.aliases),
        }
        if (
            cliente_documental not in _AUSENTES
            and normalizar_nombre_cliente(cliente_documental) not in claves_confirmadas
        ):
            decisiones.append(crear_decision(
                tipo="ALIAS_CANDIDATO", entidad="CLIENTE", campo="cliente",
                valor_documental=cliente_documental,
                valor_normalizado=normalizar_nombre_cliente(cliente_documental),
                identidad_resuelta=identidad_cliente,
                candidatos=(identidad_cliente,), motivos=("RUT_EXACTO_ALIAS_NO_CONFIRMADO",),
                evidencias=({"tipo": "RUT_EXACTO", "campo": "rut_cliente", "valor": rut_cliente},),
                acciones_permitidas=("CONFIRMAR_ALIAS", "RECHAZAR", "POSPONER"),
                **comunes,
            ))
    elif rut_valido and cliente_documental not in _AUSENTES:
        empresas = cargar_catalogo_json(carpeta / "empresas.json")
        empresa = buscar_empresa_por_rut(empresas, rut_cliente)
        if empresa is not None:
            canonico = str(empresa.get("nombre", "")).strip()
            alias_confirmados = [str(x) for x in empresa.get("aliases", [])]
            claves = {normalizar_nombre_cliente(canonico), *(
                normalizar_nombre_cliente(alias) for alias in alias_confirmados
            )}
            if normalizar_nombre_cliente(cliente_documental) not in claves:
                identidad = {
                    "entidad_id": normalizar_rut_cliente(rut_cliente),
                    "valor_canonico": canonico,
                    "rut": normalizar_rut_cliente(rut_cliente),
                    "catalogo": "empresas.json",
                }
                decisiones.append(crear_decision(
                    tipo="ALIAS_CANDIDATO", entidad="CLIENTE", campo="cliente",
                    valor_documental=cliente_documental,
                    valor_normalizado=normalizar_nombre_cliente(cliente_documental),
                    identidad_resuelta=identidad, candidatos=(identidad,),
                    motivos=("RUT_EXACTO_ALIAS_NO_CONFIRMADO",),
                    evidencias=({"tipo": "RUT_EXACTO", "campo": "rut_cliente", "valor": rut_cliente},),
                    acciones_permitidas=("CONFIRMAR_ALIAS", "RECHAZAR", "POSPONER"),
                    **comunes,
                ))
        else:
            # R3.2: cliente realmente nuevo (RUT válido, no existe en ningún
            # catálogo maestro) -- Registrar/No registrar, nada más.
            decisiones.append(crear_decision(
                tipo="CLIENTE_DESCONOCIDO", entidad="CLIENTE", campo="cliente",
                valor_documental=cliente_documental,
                valor_normalizado=normalizar_nombre_cliente(cliente_documental),
                identidad_resuelta=None, candidatos=(),
                motivos=("RUT_VALIDO_NO_EXISTE_EN_CATALOGO_MAESTRO",),
                evidencias=({"tipo": "RUT_VALIDO", "campo": "rut_cliente", "valor": rut_cliente},),
                acciones_permitidas=ACCIONES_ENTIDAD_DESCONOCIDA,
                **comunes,
            ))
    elif cliente_documental not in _AUSENTES:
        # R4.8 -- Bloque CLIENTE_CANDIDATO: sin RUT corroborable (ausente o
        # con dígito verificador inválido), Atlas no puede confirmar
        # identidad por RUT -- pero el motivo documental `CLIENTE_SIN_CORROBORAR`
        # SÍ requiere intervención humana, y silenciarlo aquí (como antes de
        # este bloque) dejaba ese motivo sin ninguna ruta accionable en
        # Revisión de Atlas -- caso real 472037/464981. Si el nombre
        # documental coincide (difuso o por alias, mismo motor ya calibrado
        # para chofer/`empresas.json`, nunca una heurística nueva) con un
        # cliente YA CONFIRMADO/ACTIVO, se presenta esa coincidencia como
        # pregunta -- nunca se autoconfirma (nombre solo, sin RUT, nunca es
        # prueba suficiente en este módulo). Si no hay ningún candidato
        # claro, se abstiene -- el motivo documental queda como revisión no
        # accionable, honesto en vez de forzar una sugerencia sin evidencia.
        try:
            clientes_confirmados = [
                c for c in CatalogoClientes(carpeta / "clientes.json").listar()
                if c.estado_calidad == EstadoCalidadCliente.CONFIRMADO.value
                and c.estado_vigencia == EstadoVigenciaCliente.ACTIVO.value
            ]
        except (OSError, ValueError):
            clientes_confirmados = []
        coincidencia = resolver_nombre_cliente_difuso(clientes_confirmados, cliente_documental)
        if coincidencia.estado in _ESTADOS_NOMBRE_SEGUROS:
            candidato = next(
                (c for c in clientes_confirmados if c.razon_social == coincidencia.valor_resultado), None,
            )
            if candidato is not None:
                identidad_candidata = {
                    "entidad_id": candidato.cliente_id,
                    "valor_canonico": candidato.razon_social,
                    "rut": candidato.rut,
                }
                decisiones.append(crear_decision(
                    tipo="CLIENTE_CANDIDATO", entidad="CLIENTE", campo="cliente",
                    valor_documental=cliente_documental,
                    valor_normalizado=normalizar_nombre_cliente(cliente_documental),
                    identidad_resuelta=identidad_candidata,
                    candidatos=(identidad_candidata,),
                    motivos=("NOMBRE_SIN_RUT_CORROBORABLE",),
                    evidencias=({
                        "tipo": "NOMBRE_" + coincidencia.estado, "campo": "cliente",
                        "valor": cliente_documental,
                    },),
                    acciones_permitidas=ACCIONES_CLIENTE_CANDIDATO,
                    **comunes,
                ))

    obra_texto = str(datos.get("obra destino", "")).strip()
    if identidad_cliente is not None:
        decisiones.extend(_decisiones_obra_para_cliente(
            carpeta=carpeta, cliente_id=cliente.cliente_id,
            cliente_razon_social=cliente.razon_social, cliente_aliases=cliente.aliases,
            obra_texto=obra_texto, despachar_a_documental=despachar_a_documental,
            comunes=comunes,
        ))
    return decisiones


def detectar_decision_origen_no_confirmado(
    *, archivo: str, fila: Mapping[str, str], plantas: Iterable[Planta],
) -> dict[str, object] | None:
    """Bloque ORIGEN D1: genera una pregunta `ORIGEN_NO_CONFIRMADO` para UN
    documento YA PROCESADO cuya planta de origen quedó sin determinar --
    SÓLO cuando existe evidencia GPS real y suficiente para formular una
    sugerencia útil. Opera exclusivamente sobre columnas YA PERSISTIDAS en
    el dataset (`fila`) y el catálogo de plantas -- nunca OCR, nunca red,
    nunca vuelve a consultar telemetría.

    Se abstiene (devuelve `None`, no genera ninguna pregunta) en dos
    familias de caso, deliberadamente:
    - el documento YA tiene origen (`planta_origen_id` presente) -- nada
      que preguntar;
    - la evidencia GPS es demasiado escasa para ofrecer siquiera un
      candidato razonable (p. ej. `SIN_HISTORICO`, `NINGUN_PUNTO_DENTRO_DE_GEOCERCA`
      sin ninguna coordenada de estadía, o cualquier motivo no reconocido)
      -- caso real 464479/464529: 1 solo trip/5 puntos GPS ese día, sin
      relación con ninguna planta. Preguntarle a Javier sin nada que
      mostrarle sería la misma adivinanza que se le prohíbe a Atlas, sólo
      que delegada a un humano sin necesidad.

    Reconoce dos formas de evidencia YA CALCULADA por el pipeline
    existente (nunca inventa un cálculo nuevo):
    1. `motivo_origen_gps` empieza con `CONFLICTO_REAL_EN_VENTANA` (Fase D
       de `resolver_planta_origen_gps`) -- ya trae, en el propio texto,
       cada planta candidata con su `score`/`solape` ya calculados; se
       parsean tal cual, sin recalcular nada. Caso real: 464730 (AZA
       COLINA Y AZA RENCA, ambas con evidencia real).
    2. `motivo_origen_gps` empieza con `DETENCION_REAL_FUERA_DE_TODA_GEOCERCA`
       (Fase K) -- ya trae la coordenada de la detención real
       (`latitud_estadia_gps`/`longitud_estadia_gps`) y su duración. Se
       ofrece como candidata cualquier planta CONFIRMADA+ACTIVA dentro de
       `RADIO_CANDIDATO_ORIGEN_SUGERIDO_KM`. Casos reales: 464717, 464892
       (ambos AZA COLINA, con evidencia real aunque por debajo del umbral
       de resolución automática)."""
    if str(fila.get("estado_ruta", "")).strip() != "ORIGEN_NO_DETERMINADO":
        return None
    if str(fila.get("planta_origen_id", "")).strip():
        return None  # ya tiene origen -- nada que preguntar

    motivo_origen_gps = str(fila.get("motivo_origen_gps", "")).strip()
    plantas_activas = [
        p for p in plantas
        if getattr(p, "estado_calidad", "") == "CONFIRMADA" and getattr(p, "estado_vigencia", "") == "ACTIVA"
    ]
    candidatos: list[dict[str, object]] = []
    motivo_decision = ""

    if motivo_origen_gps.startswith("CONFLICTO_REAL_EN_VENTANA"):
        motivo_decision = "ORIGEN_GPS_CONFLICTO"
        for nombre_token, score, solape in _PATRON_CONFLICTO_ORIGEN.findall(motivo_origen_gps):
            nombre_normalizado = nombre_token.replace("_", " ").strip().upper()
            planta = next(
                (p for p in plantas_activas if p.nombre.strip().upper() == nombre_normalizado), None,
            )
            if planta is None:
                continue
            candidatos.append({
                "planta_id": planta.planta_id, "planta_nombre": planta.nombre,
                "evidencia_resumen": f"score={score}, solape con la ventana documental={solape}%",
            })
    elif motivo_origen_gps.startswith("DETENCION_REAL_FUERA_DE_TODA_GEOCERCA"):
        motivo_decision = "ORIGEN_GPS_ESTADIA_SIN_PLANTA"
        try:
            lat = float(fila.get("latitud_estadia_gps", ""))
            lon = float(fila.get("longitud_estadia_gps", ""))
        except (TypeError, ValueError):
            return None
        duracion = str(fila.get("duracion_estadia_gps_min", "")).strip()
        punto = Coordenadas(lon, lat)
        cercanas: list[tuple[float, Planta]] = []
        for planta in plantas_activas:
            coordenada_planta = coordenada_ruteo_planta(planta)
            if coordenada_planta is None:
                continue
            distancia = distancia_km_haversine(punto, coordenada_planta)
            if distancia <= RADIO_CANDIDATO_ORIGEN_SUGERIDO_KM:
                cercanas.append((distancia, planta))
        cercanas.sort(key=lambda par: par[0])
        for distancia, planta in cercanas:
            candidatos.append({
                "planta_id": planta.planta_id, "planta_nombre": planta.nombre,
                "evidencia_resumen": (
                    f"detención real de {duracion} min, a {round(distancia, 1)} km de esta planta"
                ),
            })
    else:
        return None  # otro motivo (SIN_HISTORICO, NINGUN_PUNTO_DENTRO_DE_GEOCERCA, etc.) -- evidencia insuficiente

    if not candidatos:
        return None

    documento = fila.get("numero_guia", ""), fila.get("numero_transporte", "")
    evidencias = [{
        "tipo": "GPS_ORIGEN",
        "motivo_origen_gps": motivo_origen_gps,
        "estado_telemetria": str(fila.get("estado_telemetria", "")),
        "evidencia_telemetria": str(fila.get("evidencia_telemetria", "")),
        "duracion_estadia_gps_min": str(fila.get("duracion_estadia_gps_min", "")),
    }]
    return crear_decision(
        tipo="ORIGEN_NO_CONFIRMADO", entidad="ORIGEN", archivo=str(archivo),
        numero_guia=str(documento[0]), numero_transporte=str(documento[1]),
        campo="planta_origen", valor_documental="",
        valor_normalizado="", identidad_resuelta=None,
        candidatos=candidatos, motivos=[motivo_decision],
        evidencias=evidencias, acciones_permitidas=ACCIONES_ORIGEN_NO_CONFIRMADO,
    )


def decision_destino_para_obra_registrada(
    *, obra, cliente_id: str, cliente_canonico: str, destino_documental: str,
    documento: Mapping[str, object] | None, catalogo_obras: CatalogoObrasDestinos,
) -> dict[str, object] | None:
    """R3.4.2: cierra el ciclo OBRA_DESCONOCIDA -> DESTINO_SIN_CONFIRMAR.

    Cuando `detectar_decisiones_documento` emitió OBRA_DESCONOCIDA, la obra
    todavía no existía -- por eso no pudo generar también la pregunta de
    destino (ese bloque exige `obras` no vacío). Una vez que la obra queda
    registrada (`obra` ya resuelta, con `obra_id`), esta función reconstruye
    exactamente esa pregunta pendiente, usando SÓLO datos ya observados y
    persistidos (`destino_documental`, capturado en el `contexto` de la
    decisión original en el momento del procesamiento) -- sin OCR, sin volver
    a leer el documento ni el dataset.

    CASO A -- destino ya corroborable: si la relación obra<->destino global
    ya puede resolverse sin decisión adicional (p.ej. la obra resultó
    coincidir por nombre con una obra ya CONFIRMADA con una única relación
    CONFIRMADA), se abstiene -- no hay pregunta redundante que hacer.

    CASO B -- confirmación humana: si hay destino documental, genera la
    decisión DESTINO_SIN_CONFIRMAR (idéntica en forma a la que habría
    emitido `detectar_decisiones_documento` si la obra ya hubiera existido).

    CASO C -- información insuficiente: si no hay destino documental
    capturado (ausente, o decisión persistida antes de este cambio y por
    tanto sin el campo), se abstiene -- nunca inventa un destino que el
    documento no trajo.
    """
    try:
        if catalogo_obras.resolver_obra_destino_confirmada_global(
            nombre_obra=obra.nombre_canonico
        ) is not None:
            return None  # CASO A: ya corroborada, nada que preguntar
    except (OSError, ValueError):
        pass
    destino_texto = str(destino_documental or "").strip()
    if destino_texto in _AUSENTES:
        return None  # CASO C: sin destino documental, no se inventa nada
    comunes = {
        "archivo": str((documento or {}).get("archivo", "")),
        "numero_guia": str((documento or {}).get("numero_guia", "")),
        "numero_transporte": str((documento or {}).get("numero_transporte", "")),
    }
    return crear_decision(
        tipo="DESTINO_SIN_CONFIRMAR", entidad="RELACION_OBRA_DESTINO",
        campo="destino_entrega", valor_documental=destino_texto,
        valor_normalizado=normalizar_nombre_destino(destino_texto),
        identidad_resuelta={"entidad_id": obra.obra_id, "valor_canonico": obra.nombre_canonico},
        candidatos=(), motivos=("OBRA_SIN_RELACION_CONFIRMADA_UNICA",),
        evidencias=({"tipo": "OBRA_IDENTIFICADA", "entidad_id": obra.obra_id},),
        acciones_permitidas=ACCIONES_DESTINO_SIN_CONFIRMAR,
        contexto={
            "cliente_id": cliente_id, "cliente_canonico": cliente_canonico,
            "obra_id": obra.obra_id, "obra_canonica": obra.nombre_canonico,
            "destino_documental": destino_texto,
        },
        **comunes,
    )


def regenerar_decisiones_persistidas(
    *, decisiones: Iterable[Mapping[str, object]], carpeta_catalogos: str | Path,
    ids_resueltos: Iterable[str] = (), ruta_dataset: str | Path | None = None,
) -> list[dict[str, object]]:
    """R3.2.1: reclasifica decisiones YA PERSISTIDAS (p. ej. las de un
    artefacto `decisiones_pendientes.json` generado antes de R3.2) sin volver
    a leer datos documentales ni ejecutar OCR.

    Fuente de verdad: el propio contenido de cada decisión (`valor_documental`,
    `contexto`, `evidencias`) más una lectura read-only de catálogos para
    validar que la identidad de apoyo siga vigente. No inventa nada que la
    decisión no traiga ya: una `OBRA_DESCONOCIDA` sin `contexto` (artefactos
    previos a R3.1.3) se conserva sin filtrar -- no hay base para decidir
    cliente==obra sin ese dato.

    Efectos:
    - Cliente==obra (comparación exacta normalizada): la decisión se
      descarta -- Atlas ya conoce el hecho, no hay pregunta que hacer.
    - Para las decisiones de entidad realmente desconocida que se conservan
      (OBRA_DESCONOCIDA, VEHICULO_DESCONOCIDO, CLIENTE_DESCONOCIDO),
      `acciones_permitidas` se normaliza a REGISTRAR/NO_REGISTRAR/POSPONER,
      reemplazando códigos R3.1 (ASOCIAR_EXISTENTE, CONFIRMAR_NUEVO,
      REGISTRAR_OBSERVACION, ...).
    - El contexto canónico de apoyo se refresca por ID desde los catálogos
      vigentes cuando existe. `decision_id` no cambia para las decisiones
      conservadas: su identidad (tipo, documento, campo, valor_documental,
      evidencias) es la misma de antes; contexto y hashes no forman parte de
      esa identidad.

    `ruta_dataset` (Bloque R13, opcional y aditivo -- compatible hacia
    atrás): si se entrega, descarta ADEMÁS cualquier decisión cuyo
    `motivos` declarado sea íntegramente un código de
    `MotivoRevisionDocumento` (obra/cliente/patente/etc. -- nunca un
    motivo interno propio de la decisión, como
    `OBRA_SIN_RELACION_CONFIRMADA_UNICA` o
    `SIN_VEHICULO_CONFIRMADO_COMPATIBLE`, que no viven en esa columna)
    que YA NO está presente en `motivos_revision_documento` de la fila
    actual de ese documento -- caso real 472238/472239: una revalidación
    `sin_ocr` (p. ej. `revalidar_cliente_ausente_por_obra_coincidente_
    sin_ocr`) puede retirar el motivo del dataset sin que este mecanismo
    lo supiera nunca, dejando la tarjeta de Revisión de Atlas huérfana
    indefinidamente. Genérico por construcción -- cualquier tipo de
    decisión futuro cuyo motivo coincida con la columna documental queda
    cubierto automáticamente, sin agregar un caso por tipo."""
    carpeta = Path(carpeta_catalogos)
    motivos_por_guia: dict[str, set[str]] | None = None
    codigos_motivo_documental: frozenset[str] = frozenset()
    # Bloque RESOLUCIÓN R19 -- caso real 472037: cuando una revalidación
    # `sin_ocr` refresca `motivo_ruta` (p. ej. `GEOCODIFICACION_FUERA_
    # DE_CHILE` -> `MULTIPLES_UBICACIONES_DISPERSAS`, tras corregir un
    # bug de caché), la evidencia que originó la decisión `DESTINO_NO_
    # RESUELTO` ya publicada queda desactualizada -- `crear_decision`
    # incluye el `motivo_ruta` crudo en su hash, así que un motivo fresco
    # produce un `decision_id` DISTINTO en la próxima detección, dejando
    # la tarjeta VIEJA huérfana junto a una nueva (una dirección visible
    # dos veces, con una razón obsoleta). Mismo criterio exacto que el
    # bloque de arriba (R13), aplicado a `motivo_ruta` en vez de
    # `motivos_revision_documento`.
    motivo_ruta_por_guia: dict[str, str] | None = None
    # Bloque B1 EXPOSICIÓN -- fila completa por guía (misma lectura de
    # arriba, sin un segundo paso por el CSV) para poder refrescar el
    # hallazgo B1 (`resumen_hallazgo_b1`) de una decisión `DESTINO_NO_
    # RESUELTO` YA PUBLICADA -- si no se refrescara aquí, una decisión
    # publicada ANTES de que B1 investigara se quedaría con el contexto
    # viejo (sin hallazgo) para siempre, porque `decision_id` no cambia
    # sólo por eso (el hallazgo no participa del hash) y la próxima
    # detección quedaría descartada como duplicado por `generar_artefacto`.
    filas_por_guia: dict[str, dict[str, str]] | None = None
    if ruta_dataset is not None:
        import csv as _csv

        from atlas_core.atlas_ia.registro_problemas import motivo_ruta_base as _motivo_ruta_base
        from atlas_core.procesamiento_masivo import MotivoRevisionDocumento as _MotivoRevisionDocumento
        codigos_motivo_documental = frozenset(m.value for m in _MotivoRevisionDocumento)
        motivos_por_guia = {}
        motivo_ruta_por_guia = {}
        filas_por_guia = {}
        try:
            with Path(ruta_dataset).open("r", newline="", encoding="utf-8-sig") as _archivo:
                for _fila in _csv.DictReader(_archivo, delimiter=";"):
                    _guia = str(_fila.get("numero_guia", "")).strip()
                    if not _guia:
                        continue
                    motivos_por_guia[_guia] = {
                        m.strip() for m in str(_fila.get("motivos_revision_documento", "")).split("|") if m.strip()
                    }
                    motivo_ruta_por_guia[_guia] = _motivo_ruta_base(str(_fila.get("motivo_ruta", "")))
                    filas_por_guia[_guia] = dict(_fila)
        except (OSError, UnicodeDecodeError):
            motivos_por_guia = None
            motivo_ruta_por_guia = None
            filas_por_guia = None
    try:
        clientes_por_id = {c.cliente_id: c for c in CatalogoClientes(carpeta / "clientes.json").listar()}
    except (OSError, ValueError):
        clientes_por_id = {}

    ids_terminales = {str(valor) for valor in ids_resueltos}
    try:
        catalogo_obras = CatalogoObrasDestinos(
            ruta=carpeta / "obras_destinos.json",
            ruta_clientes=carpeta / "clientes.json",
            ruta_destinos=carpeta / "destinos_maestros.json",
        )
        obras_existentes = catalogo_obras.listar_obras()
    except (OSError, ValueError):
        catalogo_obras = None
        obras_existentes = []
    try:
        patentes_homologables = {
            v.patente_canonica
            for v in cargar_catalogo_vehiculos(carpeta / "vehiculos.json").homologables()
        }
    except (OSError, ValueError):
        patentes_homologables = set()
    decisiones_lista = actualizar_contrato_vehiculos_persistidos(decisiones)
    resultado: list[dict[str, object]] = []
    for original in decisiones_lista:
        decision = dict(original)
        if str(decision.get("decision_id", "")) in ids_terminales:
            continue
        if motivos_por_guia is not None:
            motivos_decision = {str(m) for m in (decision.get("motivos") or [])}
            if motivos_decision and motivos_decision <= codigos_motivo_documental:
                numero_guia_decision = str((decision.get("documento") or {}).get("numero_guia", ""))
                motivos_fila = motivos_por_guia.get(numero_guia_decision)
                if motivos_fila is not None and not (motivos_decision & motivos_fila):
                    continue  # el motivo que originó esta decisión ya no está en el dataset
        tipo = decision.get("tipo")
        contexto = dict(decision.get("contexto") or {})
        cliente_id_contexto = str(contexto.get("cliente_id") or "")
        cliente_vigente_contexto = clientes_por_id.get(cliente_id_contexto)
        if cliente_vigente_contexto is not None:
            contexto["cliente_canonico"] = cliente_vigente_contexto.razon_social
            decision["contexto"] = contexto

        if tipo == "OBRA_DESCONOCIDA":
            cliente_canonico = contexto.get("cliente_canonico")
            cliente_id = contexto.get("cliente_id")
            if cliente_canonico:
                claves_cliente = {normalizar_nombre_obra(str(cliente_canonico))}
                cliente_vigente = clientes_por_id.get(str(cliente_id)) if cliente_id else None
                if cliente_vigente is not None:
                    claves_cliente.add(normalizar_nombre_obra(cliente_vigente.razon_social))
                    claves_cliente.update(
                        normalizar_nombre_obra(alias) for alias in cliente_vigente.aliases
                    )
                obra_texto = str(decision.get("valor_documental", ""))
                if normalizar_nombre_obra(obra_texto) in claves_cliente:
                    continue  # cliente==obra: no hay obra nueva que preguntar
                # R3.3.1: obra = identidad GLOBAL -- ya no se filtra por
                # cliente_id. Si la obra ya existe para CUALQUIER cliente
                # (p. ej. otro cliente la registró después de que este
                # artefacto se generó), se descarta la pregunta.
                obra_coincidente = next(
                    (
                        o for o in obras_existentes
                        if o.estado_vigencia == EstadoVigencia.ACTIVO.value
                        and normalizar_nombre_obra(obra_texto) in {
                            normalizar_nombre_obra(o.nombre_canonico),
                            *(normalizar_nombre_obra(alias) for alias in o.aliases_documentales),
                        }
                    ),
                    None,
                )
                if obra_coincidente is not None:
                    # R3.4.2: la obra ya no es la pregunta -- pero puede
                    # faltar la pregunta de destino que
                    # `detectar_decisiones_documento` no pudo generar en su
                    # momento porque, cuando se procesó este documento, la
                    # obra todavía no existía. `generar_artefacto` filtra
                    # después contra el ledger, así que una decisión ya
                    # terminal (CONFIRMAR/NO_CONFIRMAR) nunca resucita aquí.
                    if catalogo_obras is not None:
                        siguiente = decision_destino_para_obra_registrada(
                            obra=obra_coincidente,
                            cliente_id=str(cliente_id or ""),
                            cliente_canonico=str(cliente_canonico or obra_coincidente.nombre_canonico),
                            destino_documental=contexto.get("destino_documental", ""),
                            documento=decision.get("documento"),
                            catalogo_obras=catalogo_obras,
                        )
                        if siguiente is not None:
                            resultado.append(siguiente)
                    continue

        if tipo == "DESTINO_SIN_CONFIRMAR":
            # R3.4: si la obra referenciada ya tiene una relación CONFIRMADA
            # con algún destino (global -- sin exigir cliente), la pregunta
            # ya quedó resuelta -- por esta guía o por cualquier otra.
            entidad_id = (decision.get("identidad_resuelta") or {}).get("entidad_id")
            obra_canonica = (decision.get("contexto") or {}).get("obra_canonica")
            nombre_obra = str(obra_canonica or "")
            if not nombre_obra and entidad_id:
                obra_actual = next((o for o in obras_existentes if o.obra_id == entidad_id), None)
                nombre_obra = obra_actual.nombre_canonico if obra_actual is not None else ""
            if nombre_obra and catalogo_obras is not None and catalogo_obras.resolver_obra_destino_confirmada_global(
                nombre_obra=nombre_obra
            ) is not None:
                continue
            obra_actual = next((o for o in obras_existentes if o.obra_id == entidad_id), None)
            if obra_actual is not None:
                identidad = dict(decision.get("identidad_resuelta") or {})
                identidad.update({
                    "entidad_id": obra_actual.obra_id,
                    "valor_canonico": obra_actual.nombre_canonico,
                })
                decision["identidad_resuelta"] = identidad
                contexto.update({
                    "obra_id": obra_actual.obra_id,
                    "obra_canonica": obra_actual.nombre_canonico,
                })
                decision["contexto"] = contexto

        if tipo == "DESTINO_NO_RESUELTO":
            # Bloque RESOLUCIÓN R19 -- caso real 472037: si `motivo_ruta`
            # de la fila actual ya no coincide (por código base) con el
            # motivo que originó ESTA decisión, la evidencia quedó
            # obsoleta -- se descarta; si el problema de destino sigue
            # vigente con causa fresca, la próxima detección publica una
            # tarjeta nueva con evidencia al día (nunca deja dos tarjetas
            # para la misma guía, una viva y una fantasma).
            if motivo_ruta_por_guia is not None:
                numero_guia_decision = str((decision.get("documento") or {}).get("numero_guia", ""))
                motivos_decision_ruta = {str(m) for m in (decision.get("motivos") or [])}
                motivo_actual_fila = motivo_ruta_por_guia.get(numero_guia_decision)
                if (
                    motivos_decision_ruta and motivo_actual_fila is not None
                    and motivo_actual_fila not in motivos_decision_ruta
                ):
                    continue
            # Bloque B1 EXPOSICIÓN -- refresca el hallazgo B1 de una
            # decisión YA PUBLICADA: si B1 investigó DESPUÉS de que esta
            # tarjeta se publicó (`resultado_atlas_ia_json` cambió), el
            # contexto viejo (sin hallazgo, o con uno desactualizado) se
            # reemplaza -- `decision_id` no cambia por esto (el hallazgo
            # nunca participa del hash), así que nunca aparece como una
            # tarjeta duplicada.
            if filas_por_guia is not None:
                numero_guia_decision = str((decision.get("documento") or {}).get("numero_guia", ""))
                fila_actual = filas_por_guia.get(numero_guia_decision)
                for clave in tuple(contexto):
                    if clave.startswith("b1_"):
                        del contexto[clave]
                if fila_actual is not None:
                    hallazgo = resumen_hallazgo_b1(
                        fila_actual, dominio="DESTINO", campo=str(decision.get("campo", "despachar_a_crudo")),
                    )
                    if hallazgo:
                        contexto.update(hallazgo)
                decision["contexto"] = contexto
            # Bloque R13 -- caso real 472238/472239 (VISTA CLARA 2351
            # CERRILLOS, misma obra que 472099, ya confirmada por Javier):
            # "¿es correcta esta dirección?" ya tiene respuesta humana
            # (la obra global ya tiene una relación CONFIRMADA con algún
            # destino) -- no hace falta preguntarlo otra vez sólo porque
            # el proveedor de rutas siga sin poder geocodificarla (eso
            # sigue visible aparte, vía `estado_ruta`/`motivo_ruta` en el
            # reporte, nunca oculto). Mismo criterio ya usado arriba para
            # DESTINO_SIN_CONFIRMAR -- global, sin exigir cliente_id.
            #
            # Bloque RESOLUCIÓN R18 -- causa raíz real de una supresión
            # FALSA (caso real 472044, obra "EMPRESA CONSTRUCTORA MENA Y"):
            # una obra puede despachar a MÁS DE UN destino real distinto
            # (esta misma obra ya tenía "CAM. EL NOVICIADO LAMPA LAMPA"
            # confirmado para OTRA guía, mientras ÉSTA trae "PUERTA DEL SOL
            # 83 LAS CONDES" -- un lugar completamente distinto). Suprimir
            # sólo porque la obra TIENE alguna relación confirmada,
            # cualquiera sea, silenciaba una pregunta genuina sobre una
            # dirección que Javier NUNCA confirmó. Ahora sólo se suprime
            # cuando el destino confirmado coincide LITERALMENTE (mismo
            # criterio exacto que Vía A,
            # `rutas.destino_entrega._destino_confirmado_coincide_texto`)
            # con el texto documental de ESTA decisión -- si no coincide,
            # sigue siendo una pregunta real y distinta.
            #
            # Bloque REGENERACIÓN B1 -- causa raíz real de la reaparición
            # de 460807/472008 (familia AUSIN SAN BERNARDO): dos
            # confirmaciones humanas/de evidencia DISTINTAS (Bloques R13 y
            # R19) sobre variantes de texto OCR de la MISMA dirección real
            # dejaron a la obra con DOS relaciones CONFIRMADAS -- evidencia
            # REDUNDANTE, nunca una contradicción. `resolver_obra_destino_
            # confirmada_global` exige EXACTAMENTE una relación confirmada
            # (correcto para elegir UN destino operacional a usar en
            # rutas), así que ante dos empezó a devolver `None` -- "no hay
            # relación confirmada" es lo opuesto de lo que pasó realmente
            # (hay DOS). Se reemplaza por `listar_destinos_confirmados_
            # para_obra` (sin exigir unicidad) y se suprime si CUALQUIERA
            # de los destinos confirmados coincide literalmente -- nunca
            # sólo "el primero" ni "el más nuevo".
            obra_canonica_destino = str((decision.get("contexto") or {}).get("obra_canonica", ""))
            if obra_canonica_destino and catalogo_obras is not None:
                texto_documental = normalizar_nombre_destino(str(decision.get("valor_documental", "")))
                destinos_confirmados_obra = catalogo_obras.listar_destinos_confirmados_para_obra(
                    nombre_obra=obra_canonica_destino
                )
                if any(
                    (calle := normalizar_nombre_destino(destino.direccion.split(",", 1)[0]))
                    and calle in texto_documental
                    for destino in destinos_confirmados_obra
                ):
                    continue

        if tipo == "VEHICULO_DESCONOCIDO":
            patente = normalizar_patente_vehiculo(str(decision.get("valor_documental") or ""))
            if patente in patentes_homologables:
                continue

        if tipo in TIPOS_ENTIDAD_DESCONOCIDA:
            # Bloque VEHÍCULO D1 -- si esta decisión ya trae `candidatos`
            # (sugerencia por asociación histórica de RUT, ver
            # `enriquecer_decisiones_vehiculo`), las acciones adicionales
            # se conservan -- nunca se pierden sólo porque OTRA decisión
            # no relacionada se aplicó y disparó esta regeneración (ver
            # `aplicar_decision_obra`, que llama esta función tras CADA
            # aplicación exitosa).
            base = list(ACCIONES_ENTIDAD_DESCONOCIDA)
            if tipo == "VEHICULO_DESCONOCIDO" and decision.get("candidatos"):
                indice = base.index("POSPONER") if "POSPONER" in base else len(base)
                base[indice:indice] = [a for a in ACCIONES_PATENTE_SUGERIDA if a not in base]
            decision["acciones_permitidas"] = base
        elif tipo == "DESTINO_SIN_CONFIRMAR":
            decision["acciones_permitidas"] = list(ACCIONES_DESTINO_SIN_CONFIRMAR)

        resultado.append(decision)
    return resultado


def generar_artefacto(
    *, ruta_dataset: str | Path, carpeta_catalogos: str | Path,
    decisiones: Iterable[Mapping[str, object]], ruta_salida: str | Path | None = None,
    reloj=lambda: datetime.now(timezone.utc),
) -> dict[str, object]:
    dataset = Path(ruta_dataset)
    catalogos = Path(carpeta_catalogos)
    salida = Path(ruta_salida) if ruta_salida is not None else dataset.parent / NOMBRE_ARTEFACTO
    hashes = {}
    for clave, nombre in {
        "clientes": "clientes.json", "vehiculos": "vehiculos.json",
        "obras_destinos": "obras_destinos.json",
        "destinos_maestros": "destinos_maestros.json",
    }.items():
        ruta = catalogos / nombre
        hashes[clave] = _sha256(ruta) if ruta.is_file() else None
    ids_terminales: set[str] = set()
    ruta_ledger = salida.parent / "decisiones_aplicadas.json"
    try:
        ledger = json.loads(ruta_ledger.read_text(encoding="utf-8"))
        ids_terminales = {
            str(item.get("decision_id", "")) for item in ledger.get("aplicaciones", [])
            if item.get("accion") in {
                "REGISTRAR", "NO_REGISTRAR", "CONFIRMAR", "NO_CONFIRMAR",
                # Bloque ORIGEN D1: "NO_PUEDO_DETERMINAR" es terminal como
                # "NO_CONFIRMAR" -- un humano ya miró esta evidencia exacta
                # (forma parte del decision_id) y no pudo decidir; no debe
                # volver a preguntarse lo mismo mientras la evidencia no
                # cambie. "CONFIRMAR_PLANTA"/"SELECCIONAR_OTRA_PLANTA" son
                # terminales igual que "CONFIRMAR". Bloque VEHÍCULO D1:
                # "USAR_PATENTE_EXISTENTE"/"SELECCIONAR_OTRA_PATENTE" son
                # terminales por el mismo motivo -- confirmación humana
                # sobre evidencia ya vista.
                "CONFIRMAR_PLANTA", "SELECCIONAR_OTRA_PLANTA", "NO_PUEDO_DETERMINAR",
                "USAR_PATENTE_EXISTENTE", "SELECCIONAR_OTRA_PATENTE",
            }
        }
    except (OSError, json.JSONDecodeError, AttributeError):
        pass
    decisiones_unicas: list[dict[str, object]] = []
    ids_vistos: set[str] = set()
    for decision_original in decisiones:
        decision = dict(decision_original)
        decision_id = str(decision.get("decision_id", ""))
        if decision_id in ids_terminales:
            continue
        if decision_id and decision_id in ids_vistos:
            continue
        if decision_id:
            ids_vistos.add(decision_id)
        decisiones_unicas.append(decision)
    artefacto = {
        "schema_version": SCHEMA_VERSION,
        "generado_en": reloj().astimezone(timezone.utc).isoformat(),
        "dataset_sha256": _sha256(dataset),
        "catalogos_sha256": hashes,
        "decisiones": decisiones_unicas,
    }
    escribir_json_atomico(salida, artefacto)
    return artefacto
