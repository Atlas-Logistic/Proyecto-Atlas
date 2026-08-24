"""Bloque R7 -- Registro universal de tipos de problema elegibles para
Atlas IA B1.

Causa raíz que este módulo corrige: `procesamiento_masivo._ejecutar_ia_
operacional` escalaba a B1 sólo para 4 motivos hardcodeados
(`OBRA_DESTINO_SIN_CORROBORAR`, `CHOFER_SIN_CORROBORAR`,
`PATENTE_SIN_HOMOLOGAR`, `CLIENTE_SIN_CORROBORAR`) -- cualquier otro
problema (destino/ruta, origen, peso, lo que sea) nunca llegaba a B1,
sin importar cuánta evidencia hubiera. El orquestador (`orquestador.py`)
y los contratos (`contratos.py`) YA eran genéricos por diseño (`campo` es
texto libre); el cuello de botella vivía enteramente en ese diccionario
fijo del punto de entrada.

Este módulo reemplaza ese diccionario por un REGISTRO: cada tipo de
problema es un `TipoProblemaIA` (código(s) de motivo que lo activan,
dominio/campo, recolector de evidencia propio, herramientas relevantes,
si puede aplicarse solo o sólo asistir). Agregar un tipo de problema
nuevo es agregar UNA entrada aquí -- nunca tocar el bucle que despacha
(`atlas_core.procesamiento_masivo._escalar_problemas_elegibles_a_b1`).

Ningún tipo de problema aquí ESCRIBE nada directamente -- `aplicar`, si
existe, sólo sabe mutar la `fila` en memoria que ya trae quien llama
(mismo patrón que el código que reemplaza); persistir esa fila sigue
siendo responsabilidad de `procesamiento_masivo`."""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from typing import Callable, Mapping, MutableMapping

from atlas_core.atlas_ia.contratos import ContextoRazonamiento, EvidenciaIA

# `carpeta_catalogos` (keyword, opcional): la mayoría de los recolectores
# la ignoran (evidencia ya persistida en `filas` les basta); el de planta
# origen la necesita para resolver los `planta_id` candidatos contra el
# catálogo real de plantas -- se pasa siempre, cada recolector decide si
# la usa.
RecolectorEvidencia = Callable[..., "tuple[EvidenciaIA, ...]"]
AplicadorPropuesta = Callable[[MutableMapping[str, object], str], None]


def _normalizar_texto(texto: object) -> str:
    valor = unicodedata.normalize("NFD", str(texto or ""))
    return "".join(c for c in valor if unicodedata.category(c) != "Mn").upper()


@dataclass(frozen=True)
class TipoProblemaIA:
    """Un tipo de problema operacional elegible para B1 -- por CONTRATO,
    nunca por instancia hardcodeada en el dispatcher.

    `fuente`: dónde vive el código que activa este tipo --
    "MOTIVO_DOCUMENTAL" (columna `motivos_revision_documento`),
    "MOTIVO_RUTA" (columna `motivo_ruta`, ya normalizada sin el detalle
    parentético/después de ":") u "OTRO" (activador propio, ver
    `activador` opcional más abajo -- p. ej. un motivo compuesto).
    `codigos`: los valores exactos de esa columna que activan este tipo.
    `campo`: el campo de `ContextoRazonamiento`/`EvidenciaIA` -- el mismo
    vocabulario que ya usa el resto de Atlas (nombre de columna del CSV o
    de decisión, nunca uno nuevo inventado aquí).
    `aplicable_automaticamente`: si una hipótesis clase A puede escribirse
    sola en la fila (campos de identidad ya así de hoy); si es False, la
    propuesta sólo alimenta como evidencia adicional una decisión humana
    ya existente (planta origen/destino: nunca se auto-aplica una
    dirección o una planta sin confirmación humana, ver Bloque R5/R6)."""

    codigos: frozenset[str]
    fuente: str
    campo: str
    dominio: str  # etiqueta legible para telemetría, p. ej. "CLIENTE"/"DESTINO"/"PLANTA_ORIGEN"
    herramientas: tuple[str, ...]
    aplicable_automaticamente: bool
    recopilar_evidencia: RecolectorEvidencia
    aplicar: AplicadorPropuesta | None = None


_MOTIVO_RUTA_BASE_SEPARADORES = (":", "(")


def motivo_ruta_base(motivo_ruta: str) -> str:
    """`motivo_ruta` persistido a veces trae detalle después de ':' o '('
    (p. ej. `GEOCODIFICACION_CONTRADICE_COMUNA_DOCUMENTAL: San != Angol`,
    `MULTIPLES_UBICACIONES_DISPERSAS(5)`) -- el código base es lo único
    que identifica el TIPO de problema; el detalle es evidencia, no
    identidad. Mismo criterio ya usado en
    `atlas_core.decisiones_pendientes.detectar_decision_destino_no_resuelto`."""
    texto = str(motivo_ruta or "").strip()
    for separador in _MOTIVO_RUTA_BASE_SEPARADORES:
        texto = texto.split(separador, 1)[0].strip()
    return texto


# ---------------------------------------------------------------------
# Recolectores de evidencia -- cada uno lee SÓLO lo ya persistido (sin
# OCR, sin red), igual que el resto de los mecanismos "sin_ocr" de Atlas.
# ---------------------------------------------------------------------


def recopilar_evidencia_documentos_relacionados(
    campo: str, señales_minimas: int = 3,
) -> RecolectorEvidencia:
    """Generaliza (Bloque R7) la única fuente de evidencia que
    `_ejecutar_ia_operacional` ya tenía hardcodeada para los 4 motivos
    documentales de siempre: otro documento del MISMO LOTE que comparte
    al menos `señales_minimas` de {fecha, transporte, chofer, patente
    tracto, obra destino} aporta su valor de `campo` como evidencia
    HISTORICA -- nunca copia un valor sin esas señales de vecindad real."""

    def recolectar(
        fila: Mapping[str, object], filas: "list[Mapping[str, object]]", *, carpeta_catalogos=None,
    ) -> tuple[EvidenciaIA, ...]:
        evidencias: list[EvidenciaIA] = []
        for otra in filas:
            if otra is fila or otra.get(campo) in {"", "No encontrado"}:
                continue
            señales = sum((
                otra.get("fecha") == fila.get("fecha"),
                otra.get("numero_transporte") == fila.get("numero_transporte"),
                _normalizar_texto(otra.get("chofer")) == _normalizar_texto(fila.get("chofer")),
                otra.get("patente_tracto") == fila.get("patente_tracto"),
                _normalizar_texto(otra.get("obra_destino")) == _normalizar_texto(fila.get("obra_destino")),
            ))
            if señales >= señales_minimas:
                evidencias.append(EvidenciaIA(
                    identificador=f"documento:{otra.get('archivo')}", campo=campo,
                    valor=str(otra.get(campo)), tipo_fuente="HISTORICO", nivel="DOCUMENTO_RELACIONADO",
                    independencia=1, procedencia="atlas_ia.registro_problemas.documentos_relacionados",
                    referencias_fuente=(str(otra.get("archivo", "")),),
                ))
        return tuple(evidencias)

    return recolectar


def recopilar_evidencia_destino_por_obra_relacionada(
    fila: Mapping[str, object], filas: "list[Mapping[str, object]]", *, carpeta_catalogos=None,
) -> tuple[EvidenciaIA, ...]:
    """Bloque R7 -- dominio DESTINO: otro documento de la MISMA obra
    destino que ya tiene una entrega resuelta (`estado_ruta ==
    RUTA_CALCULADA`, `direccion_entrega` no vacía) aporta esa dirección
    como evidencia HISTORICA. Sin ningún sibling resuelto, no hay
    evidencia -- B1 no tiene nada real con qué razonar y debe abstenerse
    (nunca se fabrica una dirección)."""
    obra = _normalizar_texto(fila.get("obra_destino"))
    if not obra:
        return ()
    evidencias: list[EvidenciaIA] = []
    for otra in filas:
        if otra is fila:
            continue
        if _normalizar_texto(otra.get("obra_destino")) != obra:
            continue
        if str(otra.get("estado_ruta", "")).strip() != "RUTA_CALCULADA":
            continue
        direccion = str(otra.get("direccion_entrega", "")).strip()
        if not direccion:
            continue
        evidencias.append(EvidenciaIA(
            identificador=f"documento:{otra.get('archivo')}:destino", campo="despachar_a_crudo",
            valor=direccion, tipo_fuente="HISTORICO", nivel="OBRA_RELACIONADA",
            independencia=1, procedencia="atlas_ia.registro_problemas.destino_por_obra",
            referencias_fuente=(str(otra.get("archivo", "")),),
        ))
    return tuple(evidencias)


def recopilar_evidencia_origen_por_conflicto_gps(
    fila: Mapping[str, object], filas: "list[Mapping[str, object]]", *, carpeta_catalogos=None,
) -> tuple[EvidenciaIA, ...]:
    """Bloque R7 -- dominio PLANTA ORIGEN: reutiliza EXACTAMENTE los
    candidatos que ya calcula `detectar_decision_origen_no_confirmado`
    (Bloque R5) a partir de `motivo_origen_gps` -- nunca vuelve a
    calcular nada. Sin catálogo de plantas o sin candidatos (evidencia
    GPS demasiado escasa), no hay evidencia para B1 -- misma abstención
    que ya aplica esa función."""
    if carpeta_catalogos is None:
        return ()
    from pathlib import Path

    from atlas_core.catalogo_plantas import CatalogoPlantas
    from atlas_core.decisiones_pendientes import detectar_decision_origen_no_confirmado

    try:
        plantas = CatalogoPlantas(Path(carpeta_catalogos) / "plantas.json").listar()
    except (OSError, ValueError):
        return ()
    decision = detectar_decision_origen_no_confirmado(
        archivo=str(fila.get("archivo", "")), fila=fila, plantas=plantas,
    )
    if decision is None:
        return ()
    return tuple(
        EvidenciaIA(
            identificador=f"planta:{c.get('planta_id')}", campo="planta_origen",
            valor=str(c.get("planta_id")), tipo_fuente="HISTORICO", nivel="GPS_CANDIDATO",
            independencia=1, procedencia="atlas_ia.registro_problemas.origen_por_conflicto_gps",
            referencias_fuente=(str(c.get("planta_nombre", "")), str(c.get("evidencia_resumen", ""))),
        )
        for c in decision.get("candidatos", [])
    )


# ---------------------------------------------------------------------
# Aplicadores -- sólo para tipos `aplicable_automaticamente=True`.
# ---------------------------------------------------------------------


def aplicar_valor_documental_directo(campo: str) -> AplicadorPropuesta:
    """Fábrica de aplicador: escribe `valor` directo en `fila[campo]` --
    mismo efecto que ya tenía `_ejecutar_ia_operacional` para los 4
    campos de identidad documental (nunca usado para planta/destino, ver
    `aplicable_automaticamente=False` en esas entradas)."""
    def aplicar(fila_objetivo: MutableMapping[str, object], valor: str) -> None:
        fila_objetivo[campo] = valor
    return aplicar


# ---------------------------------------------------------------------
# Registro -- agregar un tipo de problema nuevo es agregar UNA entrada
# aquí, nunca tocar el dispatcher.
# ---------------------------------------------------------------------

_ENTRADAS: tuple[TipoProblemaIA, ...] = (
    # Los 4 motivos documentales ya existentes desde antes de este bloque
    # -- comportamiento idéntico, ahora expresado como datos, no como un
    # diccionario fijo dentro del dispatcher.
    TipoProblemaIA(
        codigos=frozenset({"OBRA_DESTINO_SIN_CORROBORAR"}), fuente="MOTIVO_DOCUMENTAL",
        campo="obra_destino", dominio="OBRA_DESTINO", herramientas=("DOCUMENTOS_RELACIONADOS",),
        aplicable_automaticamente=True,
        recopilar_evidencia=recopilar_evidencia_documentos_relacionados("obra_destino"),
        aplicar=aplicar_valor_documental_directo("obra_destino"),
    ),
    TipoProblemaIA(
        codigos=frozenset({"CHOFER_SIN_CORROBORAR"}), fuente="MOTIVO_DOCUMENTAL",
        campo="rut_chofer", dominio="CHOFER", herramientas=("DOCUMENTOS_RELACIONADOS",),
        aplicable_automaticamente=True,
        recopilar_evidencia=recopilar_evidencia_documentos_relacionados("rut_chofer"),
        aplicar=aplicar_valor_documental_directo("rut_chofer"),
    ),
    TipoProblemaIA(
        codigos=frozenset({"PATENTE_SIN_HOMOLOGAR"}), fuente="MOTIVO_DOCUMENTAL",
        campo="patente_tracto", dominio="PATENTE", herramientas=("DOCUMENTOS_RELACIONADOS",),
        aplicable_automaticamente=True,
        recopilar_evidencia=recopilar_evidencia_documentos_relacionados("patente_tracto"),
        aplicar=aplicar_valor_documental_directo("patente_tracto"),
    ),
    # Bloque R12 -- caso real 472247 (Rodrigo Nahuelñir, JE4288): el mismo
    # código `PATENTE_SIN_HOMOLOGAR` se dispara igual quando el campo roto
    # es `patente_rampla`, no `patente_tracto` -- hasta este bloque
    # `REGISTRO_PROBLEMAS_IA` sólo podía guardar UNA entrada por código
    # (colisión de clave), así que B1 nunca evaluaba la rampla en
    # absoluto. Ahora el registro admite varias entradas por código (ver
    # `detectar_problemas_elegibles`) -- agregar este segundo campo no
    # tocó el dispatcher, sólo el registro.
    TipoProblemaIA(
        codigos=frozenset({"PATENTE_SIN_HOMOLOGAR"}), fuente="MOTIVO_DOCUMENTAL",
        campo="patente_rampla", dominio="PATENTE", herramientas=("DOCUMENTOS_RELACIONADOS",),
        aplicable_automaticamente=True,
        recopilar_evidencia=recopilar_evidencia_documentos_relacionados("patente_rampla"),
        aplicar=aplicar_valor_documental_directo("patente_rampla"),
    ),
    # Bloque R12 -- ambigüedad real de patente (>1 candidato igual de
    # plausible, ver `catalogo_vehiculos.resolver_patente`): nunca se
    # auto-aplica (la ambigüedad ya es la señal de que Motor no puede
    # elegir solo), pero B1 sí puede aportar evidencia de documentos
    # relacionados para desempatar -- cubre ambos campos por el mismo
    # motivo de colisión que PATENTE_SIN_HOMOLOGAR arriba.
    TipoProblemaIA(
        codigos=frozenset({"PATENTE_AMBIGUA"}), fuente="MOTIVO_DOCUMENTAL",
        campo="patente_tracto", dominio="PATENTE", herramientas=("DOCUMENTOS_RELACIONADOS",),
        aplicable_automaticamente=False,
        recopilar_evidencia=recopilar_evidencia_documentos_relacionados("patente_tracto"),
    ),
    TipoProblemaIA(
        codigos=frozenset({"PATENTE_AMBIGUA"}), fuente="MOTIVO_DOCUMENTAL",
        campo="patente_rampla", dominio="PATENTE", herramientas=("DOCUMENTOS_RELACIONADOS",),
        aplicable_automaticamente=False,
        recopilar_evidencia=recopilar_evidencia_documentos_relacionados("patente_rampla"),
    ),
    TipoProblemaIA(
        codigos=frozenset({"CLIENTE_SIN_CORROBORAR"}), fuente="MOTIVO_DOCUMENTAL",
        campo="cliente", dominio="CLIENTE", herramientas=("DOCUMENTOS_RELACIONADOS",),
        aplicable_automaticamente=True,
        recopilar_evidencia=recopilar_evidencia_documentos_relacionados("cliente"),
        aplicar=aplicar_valor_documental_directo("cliente"),
    ),
    # Bloque R12 -- caso real 472238/472239 (CLIENTE_AUSENTE, Bloque R9):
    # tiene decisión humana accionable (`REGISTRAR_CLIENTE_MANUAL`) desde
    # R9, pero nunca tuvo entrada en este registro -- B1 nunca evaluaba
    # este dominio pese a ser plenamente accionable. Mismo patrón que
    # CLIENTE_SIN_CORROBORAR: si otro documento del mismo transporte ya
    # trae el cliente, se corrobora solo; si no hay evidencia, Javier
    # sigue viendo la pregunta tal cual.
    TipoProblemaIA(
        codigos=frozenset({"CLIENTE_AUSENTE"}), fuente="MOTIVO_DOCUMENTAL",
        campo="cliente", dominio="CLIENTE", herramientas=("DOCUMENTOS_RELACIONADOS",),
        aplicable_automaticamente=True,
        recopilar_evidencia=recopilar_evidencia_documentos_relacionados("cliente"),
        aplicar=aplicar_valor_documental_directo("cliente"),
    ),
    # Bloque R12 -- CHOFER_AUSENTE (nombre de chofer ausente; distinto de
    # CHOFER_SIN_CORROBORAR, que ya cubre el RUT dudoso). Mismo patrón.
    TipoProblemaIA(
        codigos=frozenset({"CHOFER_AUSENTE"}), fuente="MOTIVO_DOCUMENTAL",
        campo="chofer", dominio="CHOFER", herramientas=("DOCUMENTOS_RELACIONADOS",),
        aplicable_automaticamente=True,
        recopilar_evidencia=recopilar_evidencia_documentos_relacionados("chofer"),
        aplicar=aplicar_valor_documental_directo("chofer"),
    ),
    # Bloque R12 -- FECHA_SIN_CORROBORAR (lectura geométrica difiere de la
    # lineal, ninguna corroborada) -- otro documento del mismo transporte
    # con fecha ya resuelta es evidencia real.
    TipoProblemaIA(
        codigos=frozenset({"FECHA_SIN_CORROBORAR"}), fuente="MOTIVO_DOCUMENTAL",
        campo="fecha", dominio="FECHA", herramientas=("DOCUMENTOS_RELACIONADOS",),
        aplicable_automaticamente=True,
        recopilar_evidencia=recopilar_evidencia_documentos_relacionados("fecha"),
        aplicar=aplicar_valor_documental_directo("fecha"),
    ),
    # Bloque R12 -- MATERIAL_AUSENTE (informativo/no bloqueante, pero
    # igualmente elegible para completar el campo si hay evidencia real).
    TipoProblemaIA(
        codigos=frozenset({"MATERIAL_AUSENTE"}), fuente="MOTIVO_DOCUMENTAL",
        campo="descripcion_material", dominio="MATERIAL", herramientas=("DOCUMENTOS_RELACIONADOS",),
        aplicable_automaticamente=True,
        recopilar_evidencia=recopilar_evidencia_documentos_relacionados("descripcion_material"),
        aplicar=aplicar_valor_documental_directo("descripcion_material"),
    ),
    # Bloque R12 -- CLIENTE_NUEVA_ENTIDAD_NO_CATALOGADA (informativo/no
    # bloqueante): RUT válido pero identidad genuinamente no catalogada --
    # nunca se auto-aplica (sería inventar una identidad a partir de texto
    # repetido, no corroborarla), pero B1 puede aportar evidencia para que
    # un humano registre con más contexto si corresponde.
    TipoProblemaIA(
        codigos=frozenset({"CLIENTE_NUEVA_ENTIDAD_NO_CATALOGADA"}), fuente="MOTIVO_DOCUMENTAL",
        campo="cliente", dominio="CLIENTE", herramientas=("DOCUMENTOS_RELACIONADOS",),
        aplicable_automaticamente=False,
        recopilar_evidencia=recopilar_evidencia_documentos_relacionados("cliente"),
    ),
    # Bloque R7 -- dominio nuevo: DESTINO (motivos ya definidos en Bloque
    # R6, `decisiones_pendientes.MOTIVOS_DESTINO_NO_RESUELTO`). Nunca se
    # auto-aplica -- sólo alimenta, como evidencia adicional, la decisión
    # DESTINO_NO_RESUELTO que ya existe (confirmación humana obligatoria).
    TipoProblemaIA(
        codigos=frozenset({
            "DESTINO_SIN_DATO", "GEOCODIFICACION_CONTRADICE_COMUNA_DOCUMENTAL",
            "GEOCODIFICACION_DEMASIADO_GENERICA", "MULTIPLES_UBICACIONES_DISPERSAS",
            # Bloque R9 -- caso real 472044.
            "SIN_ACCESO_VIAL",
            # Bloque RESOLUCIÓN R16 -- caso real 472037: un candidato fuera
            # de Chile tampoco es "nada que razonar" -- un documento
            # hermano de la misma obra ya resuelto en Chile sigue siendo
            # evidencia real de dónde debería quedar el destino correcto.
            "GEOCODIFICACION_FUERA_DE_CHILE",
        }),
        fuente="MOTIVO_RUTA", campo="despachar_a_crudo", dominio="DESTINO",
        herramientas=("DOCUMENTOS_RELACIONADOS",), aplicable_automaticamente=False,
        recopilar_evidencia=recopilar_evidencia_destino_por_obra_relacionada,
    ),
    # Bloque R7 -- dominio nuevo: PLANTA ORIGEN (Bloque R5, `motivo_origen_
    # gps` con conflicto real entre plantas, o detención real sin planta
    # identificada -- mismos dos motivos crudos que ya reconoce
    # `detectar_decision_origen_no_confirmado`). Tampoco se auto-aplica --
    # alimenta la decisión ORIGEN_NO_CONFIRMADO existente.
    TipoProblemaIA(
        codigos=frozenset({"CONFLICTO_REAL_EN_VENTANA", "DETENCION_REAL_FUERA_DE_TODA_GEOCERCA"}),
        fuente="MOTIVO_ORIGEN_GPS",
        campo="planta_origen", dominio="PLANTA_ORIGEN", herramientas=(),
        aplicable_automaticamente=False,
        recopilar_evidencia=recopilar_evidencia_origen_por_conflicto_gps,
    ),
)

# Bloque R12: varias entradas pueden compartir el mismo (fuente, código)
# -- p. ej. PATENTE_SIN_HOMOLOGAR/PATENTE_AMBIGUA activan tanto para
# patente_tracto como para patente_rampla. Antes una clave sólo guardaba
# la ÚLTIMA entrada agregada (colisión silenciosa: la primera se perdía
# sin aviso -- causa raíz real de que B1 nunca evaluara patente_rampla,
# caso 472247). Ahora cada clave guarda una TUPLA de entradas.
REGISTRO_PROBLEMAS_IA: dict[tuple[str, str], tuple[TipoProblemaIA, ...]] = {}
for _entrada in _ENTRADAS:
    for _codigo in _entrada.codigos:
        _clave = (_entrada.fuente, _codigo)
        REGISTRO_PROBLEMAS_IA[_clave] = REGISTRO_PROBLEMAS_IA.get(_clave, ()) + (_entrada,)


# Motivos que son, por diseño, fallas puramente estructurales/externas --
# nunca hay nada que razonar (documento sin identificador, degradación
# total, proveedor de ruta caído, etc.). Explícitos, no una lista cerrada
# disfrazada de universal: cualquier motivo NO reconocido aquí NI
# registrado arriba (`REGISTRO_PROBLEMAS_IA`) se trata igual como
# "evidencia insuficiente para preguntar" (mismo criterio ya usado en
# `detectar_decision_origen_no_confirmado`), nunca como técnico por
# omisión -- ver `clasificar_motivo_no_registrado` más abajo, el único
# punto que decide esto para CUALQUIER fuente (documental/ruta/origen
# GPS), así que un motivo nuevo mañana nunca queda en silencio.
MOTIVOS_RUTA_TECNICOS_NO_ELEGIBLES = frozenset({
    "SIN_CREDENCIAL", "SIN_CONEXION", "PROVEEDOR_NO_DISPONIBLE",
    "LIMITE_CUOTA", "RESPUESTA_INVALIDA", "DIRECCION_NO_ENCONTRADA",
    "PLANTA_SIN_COORDENADAS_EN_CATALOGO",
})

# Bloque R12 -- equivalente documental de `MOTIVOS_RUTA_TECNICOS_NO_
# ELEGIBLES`: el documento carece del sustrato mínimo para que B1 razone
# nada (sin identificador que agrupar, o degradado en general) -- nunca
# "evidencia insuficiente de un campo puntual", una categoría distinta.
MOTIVOS_DOCUMENTALES_TECNICOS_NO_ELEGIBLES = frozenset({
    "GUIA_AUSENTE", "TRANSPORTE_AUSENTE", "DOCUMENTO_DEGRADADO",
})


def clasificar_motivo_no_registrado(*, fuente: str, codigo: str) -> str:
    """Bloque R12 -- único punto de decisión para CUALQUIER código
    (documental, ruta u origen GPS) que `REGISTRO_PROBLEMAS_IA` todavía
    no reconoce -- incluido cualquier motivo que se agregue mañana sin
    haber sido registrado aquí todavía. Nunca un bypass silencioso: se
    clasifica como técnico/estructural (nada que razonar, por diseño) o
    como evidencia insuficiente (razonable en principio, simplemente
    todavía sin adaptador propio) -- el mismo criterio de dos niveles que
    ya usaba `motivo_ruta`, generalizado a las tres fuentes."""
    if fuente == "MOTIVO_RUTA" and codigo in MOTIVOS_RUTA_TECNICOS_NO_ELEGIBLES:
        return "FALLA_TECNICA_EXTERNA_SIN_RAZONAMIENTO_POSIBLE"
    if fuente == "MOTIVO_DOCUMENTAL" and codigo in MOTIVOS_DOCUMENTALES_TECNICOS_NO_ELEGIBLES:
        return "FALLA_ESTRUCTURAL_SIN_RAZONAMIENTO_POSIBLE"
    return "EVIDENCIA_INSUFICIENTE_PARA_FORMULAR_PREGUNTA"


def detectar_problemas_elegibles(fila: Mapping[str, object]) -> list[tuple[TipoProblemaIA, str]]:
    """Recorre TODAS las fuentes de motivo de una fila y devuelve los
    tipos de problema registrados que aplican -- `(tipo, codigo_activador)`
    por cada match (un mismo código puede producir más de una entrada,
    ver `REGISTRO_PROBLEMAS_IA`). Nunca requiere tocar este bucle para
    sumar un tipo de problema nuevo; sólo se extiende
    `REGISTRO_PROBLEMAS_IA`."""
    encontrados: list[tuple[TipoProblemaIA, str]] = []
    motivos_documentales = {m.strip() for m in str(fila.get("motivos_revision_documento", "")).split("|") if m.strip()}
    for codigo in motivos_documentales:
        for tipo in REGISTRO_PROBLEMAS_IA.get(("MOTIVO_DOCUMENTAL", codigo), ()):
            encontrados.append((tipo, codigo))
    codigo_ruta = motivo_ruta_base(str(fila.get("motivo_ruta", "")))
    if codigo_ruta:
        for tipo_ruta in REGISTRO_PROBLEMAS_IA.get(("MOTIVO_RUTA", codigo_ruta), ()):
            encontrados.append((tipo_ruta, codigo_ruta))
    codigo_origen = motivo_ruta_base(str(fila.get("motivo_origen_gps", "")))
    if codigo_origen:
        for tipo_origen in REGISTRO_PROBLEMAS_IA.get(("MOTIVO_ORIGEN_GPS", codigo_origen), ()):
            encontrados.append((tipo_origen, codigo_origen))
    return encontrados


def codigos_residuales_no_registrados(fila: Mapping[str, object]) -> list[tuple[str, str]]:
    """Bloque R12 -- complemento exacto de `detectar_problemas_elegibles`:
    todo código presente en CUALQUIERA de las tres fuentes que NO tiene
    ninguna entrada en `REGISTRO_PROBLEMAS_IA` -- devuelve
    `(fuente, codigo)` por cada uno. Este es el mecanismo que garantiza
    que ningún código, hoy o futuro, pase en silencio: el dispatcher
    (`procesamiento_masivo._ejecutar_ia_operacional`) registra una
    entrada explícita (`clasificar_motivo_no_registrado`) para cada uno
    de estos, en vez de simplemente omitirlos."""
    residuales: list[tuple[str, str]] = []
    motivos_documentales = {m.strip() for m in str(fila.get("motivos_revision_documento", "")).split("|") if m.strip()}
    for codigo in sorted(motivos_documentales):
        if not REGISTRO_PROBLEMAS_IA.get(("MOTIVO_DOCUMENTAL", codigo)):
            residuales.append(("MOTIVO_DOCUMENTAL", codigo))
    codigo_ruta = motivo_ruta_base(str(fila.get("motivo_ruta", "")))
    if codigo_ruta and not REGISTRO_PROBLEMAS_IA.get(("MOTIVO_RUTA", codigo_ruta)):
        residuales.append(("MOTIVO_RUTA", codigo_ruta))
    codigo_origen = motivo_ruta_base(str(fila.get("motivo_origen_gps", "")))
    if codigo_origen and not REGISTRO_PROBLEMAS_IA.get(("MOTIVO_ORIGEN_GPS", codigo_origen)):
        residuales.append(("MOTIVO_ORIGEN_GPS", codigo_origen))
    return residuales
