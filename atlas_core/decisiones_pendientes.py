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
    EstadoVigencia,
    normalizar_nombre_obra,
)
from atlas_core.catalogo_plantas import Planta
from atlas_core.catalogo_vehiculos import cargar_catalogo_vehiculos, normalizar_patente_vehiculo, resolver_patente
from atlas_core.catalogos import buscar_empresa_por_rut, cargar_catalogo_json
from atlas_core.rutas.geocerca import coordenada_ruteo_planta, distancia_km_haversine
from atlas_core.rutas.modelos import Coordenadas
from atlas_core.validadores import EstadoValidacion, validar_rut_chileno


SCHEMA_VERSION = 1
NOMBRE_ARTEFACTO = "decisiones_pendientes.json"
TIPOS_SOPORTADOS = frozenset({
    "VEHICULO_DESCONOCIDO", "CLIENTE_DESCONOCIDO", "CLIENTE_CANDIDATO",
    "OBRA_DESCONOCIDA", "DESTINO_SIN_CONFIRMAR", "ALIAS_CANDIDATO",
    "ORIGEN_NO_CONFIRMADO",
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
        elif campo == "patente_tracto" and documento in documentos_con_rampla_valida:
            decision["tipo_resolucion"] = "INEQUIVOCO"
            decision["tipo_vehiculo_propuesto"] = "TRACTO"
        elif campo == "patente_tracto":
            decision["tipo_resolucion"] = "REQUIERE_CONFIRMACION_HUMANA"
            decision["tipo_vehiculo_propuesto"] = None
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

    for campo, clave_dato, tipo_esperado in (
        ("patente_tracto", "patente del tracto", "TRACTO"),
        ("patente_rampla", "patente del carro", "CARRO"),
    ):
        valor = str(datos.get(clave_dato, "")).strip()
        if valor in _AUSENTES:
            continue
        resultado = resolver_patente(
            carpeta / "vehiculos.json", valor, tipo_esperado=tipo_esperado
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

    obra_texto = str(datos.get("obra destino", "")).strip()
    if identidad_cliente is not None and obra_texto not in _AUSENTES:
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
                normalizar_nombre_obra(cliente.razon_social),
                *(normalizar_nombre_obra(alias) for alias in cliente.aliases),
            }
            if not obras and clave in claves_cliente:
                pass
            elif not obras:
                decisiones.append(crear_decision(
                    tipo="OBRA_DESCONOCIDA", entidad="OBRA", campo="obra_destino",
                    valor_documental=obra_texto, valor_normalizado=clave,
                    identidad_resuelta=None, candidatos=(),
                    motivos=("OBRA_NO_EXISTE_PARA_CLIENTE",),
                    evidencias=({"tipo": "CLIENTE_RESUELTO", "entidad_id": cliente.cliente_id},),
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
                        "cliente_id": cliente.cliente_id,
                        "cliente_canonico": cliente.razon_social,
                        "destino_documental": str(despachar_a_documental or "").strip(),
                    },
                    **comunes,
                ))
            elif len(obras) > 1:
                # Ambigüedad global (no debería ocurrir tras la migración a
                # unicidad global -- ver CatalogoObrasDestinos): Atlas se
                # abstiene en vez de adivinar cuál es la obra correcta.
                pass
            elif catalogo_obras.resolver_obra_destino_confirmada(
                cliente_id=cliente.cliente_id, nombre_obra=obra_texto
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
                        "cliente_id": cliente.cliente_id,
                        "cliente_canonico": cliente.razon_social,
                        "obra_id": obra.obra_id,
                        "obra_canonica": obra.nombre_canonico,
                        "destino_documental": destino_texto,
                    },
                    **comunes,
                ))
        except (OSError, ValueError):
            pass
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
    ids_resueltos: Iterable[str] = (),
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
    """
    carpeta = Path(carpeta_catalogos)
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

        if tipo == "VEHICULO_DESCONOCIDO":
            patente = normalizar_patente_vehiculo(str(decision.get("valor_documental") or ""))
            if patente in patentes_homologables:
                continue

        if tipo in TIPOS_ENTIDAD_DESCONOCIDA:
            decision["acciones_permitidas"] = list(ACCIONES_ENTIDAD_DESCONOCIDA)
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
                # terminales igual que "CONFIRMAR".
                "CONFIRMAR_PLANTA", "SELECCIONAR_OTRA_PLANTA", "NO_PUEDO_DETERMINAR",
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
