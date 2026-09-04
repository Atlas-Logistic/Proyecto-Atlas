"""Bloque CATALOGOS V2 -- fichas completas de entidades (choferes,
clientes, obras/destinos, vehículos), READ-ONLY. Nunca inventa datos:
combina lo que YA existe en los catálogos privados con el histórico
documental ya persistido (`analisis_completo_guias.csv`) en un único
snapshot -- Desktop lo pide UNA vez (al abrir/refrescar Catálogos), no
por cada clic (ver Sección 13 del bloque).

Distingue explícitamente RUT CONFIRMADO (catálogo formal) de RUT
OBSERVADO/HISTÓRICO (consistente en el dataset, pero el catálogo formal
todavía no lo tiene confirmado -- caso real WLADIMIR AGUILAR) y de
CONFLICTO (dos o más valores válidos distintos para la misma entidad --
nunca se elige uno en silencio, ver Sección 11 del bloque). Nunca llama
a B1 ni hace red -- sólo agrega evidencia ya persistida."""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterable, Mapping

from atlas_core.catalogo_clientes import CatalogoClientes, normalizar_nombre_cliente
from atlas_core.catalogo_obras_destinos import CatalogoObrasDestinos, normalizar_nombre_obra
from atlas_core.catalogo_vehiculos import (
    CatalogoVehiculosAusenteError,
    CatalogoVehiculosCorruptoError,
    VehiculoDuplicadoError,
    VersionCatalogoVehiculosDesconocidaError,
    cargar_catalogo_vehiculos,
    es_confusion_ocr_de_patente,
    normalizar_patente_vehiculo,
)
from atlas_core.catalogo_vehiculos_catchup import (
    clasificar_par,
    construir_universo_patentes,
    detectar_pares_sospechosos,
)
from atlas_core.catalogos import _normalizar_nombre_entidad, cargar_catalogo_json
from atlas_core.procesamiento_masivo import COLUMNAS, COLUMNAS_PRE_G1C
from atlas_core.validadores import EstadoValidacion, validar_rut_chileno

_AUSENTES = {"", "No encontrado"}
_ERRORES_CATALOGO_VEHICULOS = (
    CatalogoVehiculosAusenteError, CatalogoVehiculosCorruptoError,
    VersionCatalogoVehiculosDesconocidaError, VehiculoDuplicadoError, OSError, ValueError,
)


def _leer_filas_dataset(raiz_atlas: str | Path) -> list[dict[str, str]]:
    ruta = Path(raiz_atlas) / "operacion" / "actual" / "analisis_completo_guias.csv"
    if not ruta.is_file():
        return []
    try:
        with ruta.open("r", newline="", encoding="utf-8-sig") as archivo:
            lector = csv.DictReader(archivo, delimiter=";")
            encabezado = list(lector.fieldnames or [])
            # COLUMNAS_PRE_G1C (Bloque G1-C): dataset real todavía sin
            # codigo_pais/codigo_unidad/codigo_contexto -- lectura pura,
            # sin riesgo de corromper nada; se acepta igual que COLUMNAS.
            if encabezado and encabezado not in (COLUMNAS, COLUMNAS_PRE_G1C):
                return []  # esquema incompatible (p. ej. fixture reducido) -- nunca se arriesga a leer mal
            return list(lector)
    except (OSError, csv.Error):
        return []


def _clave_fecha(fecha_ddmmyyyy: str) -> str:
    """Convierte "DD-MM-YYYY" a "YYYY-MM-DD" (ordenable) para min/max --
    devuelve "" si no calza el formato, nunca revienta."""
    partes = str(fecha_ddmmyyyy or "").strip().split("-")
    if len(partes) != 3 or not all(p.isdigit() for p in partes):
        return ""
    dia, mes, anio = partes
    if len(anio) != 4:
        return ""
    return f"{anio}-{mes.zfill(2)}-{dia.zfill(2)}"


def _primera_ultima(fechas: Iterable[str]) -> tuple[str, str]:
    claves = sorted(c for c in (_clave_fecha(f) for f in fechas) if c)
    if not claves:
        return "", ""
    return claves[0], claves[-1]


def _rut_valido_o_none(valor: str) -> str | None:
    resultado = validar_rut_chileno(str(valor or "").strip())
    return resultado.valor if resultado.estado == EstadoValidacion.VALIDO else None


def _resumen_rut_historico(filas: list[dict[str, str]], *, campo_rut: str) -> dict[str, object]:
    """Sección 3/11 del bloque -- nunca elige en silencio entre valores
    válidos distintos. `estado`: "SIN_DATO" (ningún RUT válido en el
    histórico), "OBSERVADO_HISTORICO" (exactamente uno, consistente) o
    "CONFLICTO" (dos o más valores válidos distintos)."""
    vistos: dict[str, int] = {}
    for fila in filas:
        rut = _rut_valido_o_none(fila.get(campo_rut, ""))
        if rut:
            vistos[rut] = vistos.get(rut, 0) + 1
    if not vistos:
        return {"estado": "SIN_DATO", "valor": None, "candidatos": []}
    if len(vistos) == 1:
        (valor,) = vistos
        return {"estado": "OBSERVADO_HISTORICO", "valor": valor, "candidatos": [{"valor": valor, "apariciones": vistos[valor]}]}
    candidatos = sorted(
        [{"valor": v, "apariciones": n} for v, n in vistos.items()],
        key=lambda c: (-c["apariciones"], c["valor"]),
    )
    return {"estado": "CONFLICTO", "valor": None, "candidatos": candidatos}


def _patente_canonica_o_plegada(patente_observada: str, rol: str, vehiculos_por_patente: Mapping[str, object]) -> str:
    """Bloque MICROAJUSTES DESKTOP -- una patente documental que sólo
    difiere de una patente canónica CONFIRMADA/ACTIVA (`vehiculos_por_
    patente` ya viene filtrada por `.homologables()`) en una confusión
    OCR conocida y compatible con el rol observado (TRACTO/CARRO) NUNCA
    se muestra como un segundo vehículo real: se resuelve a la canónica
    (caso real 472339, Cristopher Retamal: BPHF67 es BPHR67 mal leído,
    no un segundo tracto). Nunca se resuelve ante ambigüedad (más de un
    candidato posible) -- se devuelve tal cual, nunca se elige en
    silencio."""
    if patente_observada in vehiculos_por_patente:
        return patente_observada
    candidatos = {
        canonica for canonica, vehiculo in vehiculos_por_patente.items()
        if getattr(vehiculo, "tipo", None) == rol and es_confusion_ocr_de_patente(patente_observada, canonica)
    }
    return next(iter(candidatos)) if len(candidatos) == 1 else patente_observada


# Bloque RELACIONES OPERACIONALES V1 -- umbral genérico, el mismo para
# cualquier tipo de relación (chofer↔vehículo, tracto↔rampla): una
# relación con 3 o más apariciones documentales independientes es
# evidencia operacional consistente ("FUERTE"); con 1 o 2, es real pero
# todavía puntual ("AISLADA") -- nunca se trata como confirmación de
# asignación permanente (ver `buscar_relaciones_*`, más abajo, para el
# uso que le da B1). El corte en 3 replica el criterio ya usado por la
# investigación externa de referencia (Copilot, `atlas_relaciones_
# operacionales_investigacion/`) -- se adopta el UMBRAL, nunca sus CSV:
# cada número de este módulo se recalcula siempre desde
# `analisis_completo_guias.csv`, la única fuente canónica."""
UMBRAL_RELACION_FUERTE = 3


def _nivel_evidencia(apariciones: int) -> str:
    return "FUERTE" if apariciones >= UMBRAL_RELACION_FUERTE else "AISLADA"


def _vehiculos_asociados(filas: list[dict[str, str]], vehiculos_por_patente: Mapping[str, object]) -> list[dict[str, object]]:
    """Sección 4 -- nunca "una patente fija": todas las asociadas,
    tracto y rampla, con apariciones/primera/última -- nunca borra
    histórico aunque el catálogo no las tenga confirmadas. Una patente
    que sólo es una confusión OCR de una canónica confirmada se resuelve
    a esa canónica antes de agregar (ver `_patente_canonica_o_plegada`);
    nunca aparece como un segundo vehículo aparte."""
    por_patente: dict[str, dict[str, object]] = {}
    for fila in filas:
        for campo, rol in (("patente_tracto", "TRACTO"), ("patente_rampla", "CARRO")):
            valor = str(fila.get(campo, "")).strip()
            if not valor or valor in _AUSENTES:
                continue
            patente = _patente_canonica_o_plegada(normalizar_patente_vehiculo(valor), rol, vehiculos_por_patente)
            registro = por_patente.setdefault(patente, {
                "patente": patente, "roles_documentales": set(), "apariciones": 0,
                "fechas": [], "transportes": set(), "guias": set(),
            })
            registro["roles_documentales"].add(rol)
            registro["apariciones"] += 1
            registro["fechas"].append(str(fila.get("fecha", "")))
            transporte = str(fila.get("numero_transporte", "")).strip()
            if transporte and transporte not in _AUSENTES:
                registro["transportes"].add(transporte)
            guia = str(fila.get("numero_guia", "")).strip()
            if guia and guia not in _AUSENTES:
                registro["guias"].add(guia)

    salida = []
    for patente, registro in por_patente.items():
        primera, ultima = _primera_ultima(registro["fechas"])
        vehiculo_catalogo = vehiculos_por_patente.get(patente)
        salida.append({
            "patente": patente,
            "roles_documentales": sorted(registro["roles_documentales"]),
            "apariciones": registro["apariciones"],
            "transportes_distintos": len(registro["transportes"]),
            "primera_aparicion": primera,
            "ultima_aparicion": ultima,
            "guias_soporte": sorted(registro["guias"]),
            "nivel_evidencia": _nivel_evidencia(registro["apariciones"]),
            "tipo_catalogo": vehiculo_catalogo.tipo if vehiculo_catalogo else None,
            "estado_catalogo": vehiculo_catalogo.estado_calidad if vehiculo_catalogo else "SIN_CATALOGAR",
        })
    salida.sort(key=lambda v: (-v["apariciones"], v["patente"]))
    return salida


def _choferes_asociados(filas: list[dict[str, str]]) -> list[dict[str, object]]:
    """Lado simétrico de `_vehiculos_asociados`, visto desde un
    vehículo: uno o varios choferes, cada uno con apariciones/primera/
    última/guías soporte -- nunca "un chofer fijo" (Sección VEHÍCULO del
    bloque RELACIONES OPERACIONALES). `filas` ya viene filtrada a las
    guías de un vehículo puntual (ver `construir_ficha_vehiculo`)."""
    por_chofer: dict[str, dict[str, object]] = {}
    for fila in filas:
        nombre = str(fila.get("chofer", "")).strip()
        if not nombre or nombre in _AUSENTES:
            continue
        registro = por_chofer.setdefault(nombre, {"nombre": nombre, "apariciones": 0, "fechas": [], "guias": set()})
        registro["apariciones"] += 1
        registro["fechas"].append(str(fila.get("fecha", "")))
        guia = str(fila.get("numero_guia", "")).strip()
        if guia and guia not in _AUSENTES:
            registro["guias"].add(guia)

    salida = []
    for nombre, registro in por_chofer.items():
        primera, ultima = _primera_ultima(registro["fechas"])
        salida.append({
            "nombre": nombre, "apariciones": registro["apariciones"],
            "primera_aparicion": primera, "ultima_aparicion": ultima,
            "guias_soporte": sorted(registro["guias"]),
            "nivel_evidencia": _nivel_evidencia(registro["apariciones"]),
        })
    salida.sort(key=lambda c: (-c["apariciones"], c["nombre"]))
    return salida


def _combinaciones_tracto_rampla(
    filas: list[dict[str, str]], vehiculos_por_patente: Mapping[str, object],
) -> list[dict[str, object]]:
    """Bloque RELACIONES OPERACIONALES -- TRACTO↔RAMPLA: la combinación
    real que un mismo documento trae junta (mismo `patente_tracto` +
    `patente_rampla` en la MISMA fila/guía) es evidencia operacional
    -- puede servir para corroborar una lectura OCR débil de una de las
    dos patentes contra la otra, ya conocida (nunca al revés: esto
    sólo agrega evidencia ponderable, nunca sustituye/corrige un dato
    documental por su cuenta). Sólo cuenta filas con AMBAS patentes
    presentes; cada una se resuelve primero a su canónica confirmada si
    es una confusión OCR ya calibrada (mismo criterio que el resto del
    módulo, nunca uno nuevo)."""
    por_par: dict[tuple[str, str], dict[str, object]] = {}
    for fila in filas:
        tracto_doc = str(fila.get("patente_tracto", "")).strip()
        rampla_doc = str(fila.get("patente_rampla", "")).strip()
        if not tracto_doc or tracto_doc in _AUSENTES or not rampla_doc or rampla_doc in _AUSENTES:
            continue
        tracto = _patente_canonica_o_plegada(normalizar_patente_vehiculo(tracto_doc), "TRACTO", vehiculos_por_patente)
        rampla = _patente_canonica_o_plegada(normalizar_patente_vehiculo(rampla_doc), "CARRO", vehiculos_por_patente)
        clave = (tracto, rampla)
        registro = por_par.setdefault(clave, {"tracto": tracto, "rampla": rampla, "apariciones": 0, "fechas": [], "guias": set()})
        registro["apariciones"] += 1
        registro["fechas"].append(str(fila.get("fecha", "")))
        guia = str(fila.get("numero_guia", "")).strip()
        if guia and guia not in _AUSENTES:
            registro["guias"].add(guia)

    salida = []
    for (tracto, rampla), registro in por_par.items():
        primera, ultima = _primera_ultima(registro["fechas"])
        salida.append({
            "tracto": tracto, "rampla": rampla, "apariciones": registro["apariciones"],
            "primera_aparicion": primera, "ultima_aparicion": ultima,
            "guias_soporte": sorted(registro["guias"]),
            "nivel_evidencia": _nivel_evidencia(registro["apariciones"]),
        })
    salida.sort(key=lambda c: (-c["apariciones"], c["tracto"], c["rampla"]))
    return salida


def _patentes_con_evidencia_vigente(filas: list[dict[str, str]]) -> set[str]:
    vistas: set[str] = set()
    for fila in filas:
        for campo in ("patente_tracto", "patente_rampla"):
            valor = str(fila.get(campo, "")).strip()
            if valor and valor not in _AUSENTES:
                vistas.add(normalizar_patente_vehiculo(valor))
    return vistas


def _vehiculos_plegables_por_confusion_ocr(
    vehiculos_por_patente: Mapping[str, object], filas: list[dict[str, str]],
) -> set[str]:
    """Bloque PULIDO OPERACIONAL -- un vehículo CONFIRMADO/ACTIVO del
    catálogo (`vehiculos_por_patente` ya viene filtrada por
    `.homologables()`) que (a) NUNCA aparece en el histórico vigente
    (ninguna fila del dataset actual lo documenta) y (b) es una
    confusión OCR inequívoca -- un único candidato, del mismo tipo
    (TRACTO/CARRO) -- de OTRA patente canónica que SÍ tiene evidencia
    real en el vigente, se considera un duplicado espurio de migración/
    OCR: no se lista como entidad de vehículo independiente (caso real
    "BKYX63" -- catálogo legacy, sin ninguna guía vigente que lo
    respalde -- resuelto a "BKYK63", con evidencia real y consistente).
    Nunca se pliega ante ambigüedad (2+ candidatos posibles); nunca muta
    el catálogo ni borra su evidencia -- sigue existiendo internamente,
    sólo deja de mostrarse como entidad aparte."""
    con_evidencia = _patentes_con_evidencia_vigente(filas)
    plegables: set[str] = set()
    for patente, vehiculo in vehiculos_por_patente.items():
        if patente in con_evidencia:
            continue
        candidatos = {
            otra for otra, otro_vehiculo in vehiculos_por_patente.items()
            if otra != patente and otra in con_evidencia
            and getattr(otro_vehiculo, "tipo", None) == getattr(vehiculo, "tipo", None)
            and es_confusion_ocr_de_patente(patente, otra)
        }
        if len(candidatos) == 1:
            plegables.add(patente)
    return plegables


def _top(contador: Mapping[str, int], n: int = 5) -> list[dict[str, object]]:
    ordenado = sorted(contador.items(), key=lambda kv: (-kv[1], kv[0]))[:n]
    return [{"nombre": nombre, "apariciones": cantidad} for nombre, cantidad in ordenado]


def _historico_entidad(filas_entidad: list[dict[str, str]], *, campo_contraparte: str | None = None, campo_planta: str = "planta_origen_nombre") -> dict[str, object]:
    guias = {str(f.get("numero_guia", "")) for f in filas_entidad if f.get("numero_guia") not in _AUSENTES}
    primera, ultima = _primera_ultima(str(f.get("fecha", "")) for f in filas_entidad)
    contraparte: dict[str, int] = {}
    if campo_contraparte:
        for f in filas_entidad:
            valor = str(f.get(campo_contraparte, "")).strip()
            if valor and valor not in _AUSENTES:
                contraparte[valor] = contraparte.get(valor, 0) + 1
    plantas: dict[str, int] = {}
    for f in filas_entidad:
        valor = str(f.get(campo_planta, "")).strip()
        if valor and valor not in _AUSENTES:
            plantas[valor] = plantas.get(valor, 0) + 1
    return {
        "numero_guias": len(guias), "primera_aparicion": primera, "ultima_aparicion": ultima,
        "frecuentes": _top(contraparte) if campo_contraparte else [],
        "plantas_frecuentes": _top(plantas),
    }


def _cargar_vehiculos_por_patente(raiz_atlas: str | Path) -> dict[str, object]:
    try:
        vehiculos = cargar_catalogo_vehiculos(Path(raiz_atlas) / "catalogos_privados" / "vehiculos.json").homologables()
    except _ERRORES_CATALOGO_VEHICULOS:
        return {}
    return {v.patente_canonica: v for v in vehiculos}


def construir_ficha_chofer(*, identificador: str, registro_catalogo: Mapping[str, object], filas: list[dict[str, str]], vehiculos_por_patente: Mapping[str, object]) -> dict[str, object]:
    nombre_canonico = str(registro_catalogo.get("nombre", "")).strip()
    aliases = [str(a) for a in (registro_catalogo.get("aliases") or [])]
    nombres_reconocidos = {_normalizar_nombre_entidad(n) for n in [nombre_canonico, *aliases] if n}
    filas_chofer = [f for f in filas if _normalizar_nombre_entidad(str(f.get("chofer", ""))) in nombres_reconocidos]

    rut_confirmado = None
    if not identificador.upper().startswith("PENDIENTE") and len(identificador) >= 2:
        candidato = validar_rut_chileno(f"{identificador[:-1]}-{identificador[-1]}")
        if candidato.estado == EstadoValidacion.VALIDO:
            rut_confirmado = candidato.valor

    rut = (
        {"estado": "CONFIRMADO", "valor": rut_confirmado, "candidatos": [{"valor": rut_confirmado, "apariciones": None}]}
        if rut_confirmado else _resumen_rut_historico(filas_chofer, campo_rut="rut_chofer")
    )

    return {
        "tipo": "CHOFER",
        "identificador": identificador,
        "nombre_canonico": nombre_canonico,
        "aliases": aliases,
        "activo": bool(registro_catalogo.get("activo", True)),
        "observacion_catalogo": str(registro_catalogo.get("observacion", "")).strip(),
        "rut": rut,
        "vehiculos": _vehiculos_asociados(filas_chofer, vehiculos_por_patente),
        "combinaciones_tracto_rampla": _combinaciones_tracto_rampla(filas_chofer, vehiculos_por_patente),
        "historico": _historico_entidad(filas_chofer, campo_contraparte="cliente"),
        "guias_relacionadas": sorted({str(f.get("numero_guia", "")) for f in filas_chofer if f.get("numero_guia") not in _AUSENTES}),
    }


def construir_ficha_cliente(*, cliente, filas: list[dict[str, str]]) -> dict[str, object]:
    claves = {normalizar_nombre_cliente(n) for n in [cliente.razon_social, *cliente.aliases] if n}
    filas_cliente = [f for f in filas if normalizar_nombre_cliente(str(f.get("cliente", ""))) in claves]
    return {
        "tipo": "CLIENTE",
        "identificador": cliente.cliente_id,
        "nombre_canonico": cliente.razon_social,
        "rut": {"estado": "CONFIRMADO", "valor": cliente.rut} if cliente.rut else {"estado": "SIN_DATO", "valor": None},
        "aliases": list(cliente.aliases),
        "estado_calidad": cliente.estado_calidad,
        "estado_vigencia": cliente.estado_vigencia,
        "historico": _historico_entidad(filas_cliente, campo_contraparte="obra_destino"),
        "guias_relacionadas": sorted({str(f.get("numero_guia", "")) for f in filas_cliente if f.get("numero_guia") not in _AUSENTES}),
    }


def construir_ficha_obra(*, obra, catalogo_obras: CatalogoObrasDestinos, clientes_por_id: Mapping[str, object], filas: list[dict[str, str]]) -> dict[str, object]:
    claves = {normalizar_nombre_obra(n) for n in [obra.nombre_canonico, *obra.aliases_documentales] if n}
    filas_obra = [f for f in filas if normalizar_nombre_obra(str(f.get("obra_destino", ""))) in claves]
    cliente = clientes_por_id.get(obra.cliente_id)
    try:
        destinos = catalogo_obras.listar_destinos_confirmados_para_obra(nombre_obra=obra.nombre_canonico)
    except (ValueError, OSError):
        destinos = []
    return {
        "tipo": "OBRA",
        "identificador": obra.obra_id,
        "nombre_canonico": obra.nombre_canonico,
        "cliente": cliente.razon_social if cliente else None,
        "aliases": list(obra.aliases_documentales),
        "estado": obra.estado,
        "estado_vigencia": obra.estado_vigencia,
        "destinos": [
            {
                "direccion": d.direccion, "comuna": d.comuna, "region": d.region,
                "latitud": d.latitud, "longitud": d.longitud, "estado_calidad": d.estado_calidad,
                "fuente": d.fuente,
            }
            for d in destinos
        ],
        "historico": _historico_entidad(filas_obra),
        "guias_relacionadas": sorted({str(f.get("numero_guia", "")) for f in filas_obra if f.get("numero_guia") not in _AUSENTES}),
    }


def construir_ficha_vehiculo(
    *, vehiculo, filas: list[dict[str, str]], vehiculos_por_patente: Mapping[str, object],
    patentes_ambiguas: frozenset[str] = frozenset(),
) -> dict[str, object]:
    """Las guías cuya patente documental es una confusión OCR de esta
    canónica (ver `_patente_canonica_o_plegada`) se incluyen igual --
    nunca faltan relaciones/histórico sólo porque el documento tenía un
    error de lectura ya resuelto en la ficha del chofer.

    Bloque CATÁLOGOS VEHÍCULOS -- SEPARAR CONFIRMADOS: `clasificacion_
    visual` (Sección 1 del bloque) usa exclusivamente evidencia real ya
    disponible en el catálogo -- nunca inventa un estado nuevo:
    CONFIRMADO si el catálogo persistente dice `estado_calidad=CONFIRMADO`,
    hubo confirmación humana explícita (`confirmado_por`/`procedencia`) O
    evidencia operacional real (al menos una guía relacionada);
    AMBIGUO si el barrido de patentes sospechosas (`patentes_ambiguas`,
    Sección 6 del bloque) todavía no encuentra corroboración suficiente
    para esta patente puntual (caso real JF9565/JF9575); OBSERVADO en
    cualquier otro caso (calidad todavía observada/candidata, sin evidencia
    operacional vigente ni ambigüedad detectada)."""
    patente = vehiculo.patente_canonica
    filas_vehiculo = [
        f for f in filas
        if _patente_canonica_o_plegada(normalizar_patente_vehiculo(str(f.get("patente_tracto", ""))), "TRACTO", vehiculos_por_patente) == patente
        or _patente_canonica_o_plegada(normalizar_patente_vehiculo(str(f.get("patente_rampla", ""))), "CARRO", vehiculos_por_patente) == patente
    ]
    choferes_asociados = _choferes_asociados(filas_vehiculo)
    # Bloque RELACIONES OPERACIONALES -- TRACTO↔RAMPLA: combinaciones
    # observadas de TODO el histórico (nunca sólo las filas de este
    # vehículo, que ya son sólo un lado del par) que involucran esta
    # patente, en cualquiera de los dos roles (tracto o rampla).
    combinaciones_tracto_rampla = [
        c for c in _combinaciones_tracto_rampla(filas, vehiculos_por_patente)
        if patente in (c["tracto"], c["rampla"])
    ]
    primera, ultima = _primera_ultima(str(f.get("fecha", "")) for f in filas_vehiculo)
    guias_relacionadas = sorted({str(f.get("numero_guia", "")) for f in filas_vehiculo if f.get("numero_guia") not in _AUSENTES})

    # La calidad del catálogo es conocimiento persistente. La operación
    # activa sólo aporta histórico/conteos y nunca puede degradar una
    # entidad confirmada cuando el lote vigente está vacío.
    confirmacion_humana = bool(vehiculo.confirmado_por) or vehiculo.procedencia == "CONFIRMACION_HUMANA"
    if confirmacion_humana:
        clasificacion_visual = "CONFIRMADO"
    elif patente in patentes_ambiguas:
        clasificacion_visual = "AMBIGUO"
    elif vehiculo.estado_calidad == "CONFIRMADO":
        clasificacion_visual = "CONFIRMADO"
    elif guias_relacionadas:
        clasificacion_visual = "CONFIRMADO"
    else:
        clasificacion_visual = "OBSERVADO"

    return {
        "tipo": "VEHICULO",
        "identificador": vehiculo.vehiculo_id,
        "patente": patente,
        "tipo_vehiculo": vehiculo.tipo,
        "estado_calidad": vehiculo.estado_calidad,
        "estado_vigencia": vehiculo.estado_vigencia,
        "procedencia": vehiculo.procedencia,
        "clasificacion_visual": clasificacion_visual,
        "aliases": list(vehiculo.aliases),
        "confirmado_por": vehiculo.confirmado_por,
        "choferes_asociados": choferes_asociados,
        "combinaciones_tracto_rampla": combinaciones_tracto_rampla,
        "primera_aparicion": primera,
        "ultima_aparicion": ultima,
        "guias_relacionadas": guias_relacionadas,
    }


def construir_snapshot_fichas(*, raiz_atlas: str | Path) -> dict[str, object]:
    """Punto de entrada único -- un solo recorrido del dataset, un
    snapshot completo de las 4 entidades. Nunca hace red ni llama B1."""
    raiz = Path(raiz_atlas)
    carpeta = raiz / "catalogos_privados"
    filas = _leer_filas_dataset(raiz)
    vehiculos_por_patente = _cargar_vehiculos_por_patente(raiz)

    choferes_json = cargar_catalogo_json(carpeta / "choferes.json")
    fichas_choferes = [
        construir_ficha_chofer(identificador=str(ident), registro_catalogo=registro, filas=filas, vehiculos_por_patente=vehiculos_por_patente)
        for ident, registro in choferes_json.items()
        if isinstance(registro, dict)
    ]
    fichas_choferes.sort(key=lambda f: f["nombre_canonico"])

    try:
        clientes = CatalogoClientes(carpeta / "clientes.json").listar()
    except (ValueError, OSError):
        clientes = []
    fichas_clientes = [construir_ficha_cliente(cliente=c, filas=filas) for c in clientes]
    fichas_clientes.sort(key=lambda f: f["nombre_canonico"])
    clientes_por_id = {c.cliente_id: c for c in clientes}

    try:
        catalogo_obras = CatalogoObrasDestinos(
            ruta=carpeta / "obras_destinos.json", ruta_clientes=carpeta / "clientes.json",
            ruta_destinos=carpeta / "destinos_maestros.json",
        )
        obras = catalogo_obras.listar_obras()
    except (ValueError, OSError):
        catalogo_obras, obras = None, []
    fichas_obras = [
        construir_ficha_obra(obra=o, catalogo_obras=catalogo_obras, clientes_por_id=clientes_por_id, filas=filas)
        for o in obras
    ] if catalogo_obras is not None else []
    fichas_obras.sort(key=lambda f: f["nombre_canonico"])

    plegables = _vehiculos_plegables_por_confusion_ocr(vehiculos_por_patente, filas)
    # Bloque CATÁLOGOS VEHÍCULOS -- SEPARAR CONFIRMADOS: patentes AMBIGUO
    # se detectan SÓLO entre las que ya sobrevivieron el pliegue OCR de
    # arriba (nunca se recalcula BPHF67/BKYX63 -- ya resueltas y
    # excluidas -- con evidencia débil, lo que las volvería a marcar
    # ambiguas por error). Sin filas documentales (`filas=()`): sólo
    # compara metadatos de catálogo (confirmación humana, confusión OCR
    # calibrada) -- mismo motor ya usado para el barrido general
    # (`catalogo_vehiculos_catchup`), nunca uno nuevo.
    vehiculos_visibles = {k: v for k, v in vehiculos_por_patente.items() if k not in plegables}
    universo_visible = construir_universo_patentes(filas=[], vehiculos_por_patente=vehiculos_visibles)
    patentes_ambiguas: set[str] = set()
    for par in detectar_pares_sospechosos(universo_visible):
        clasificacion = clasificar_par(par, universo_visible)
        if clasificacion.clase == "AMBIGUO":
            # Ninguno de los dos lados es claramente canónico -- ambos
            # quedan "Por verificar" (Sección 6 del bloque), nunca sólo
            # uno con el otro tratado como ganador implícito.
            patentes_ambiguas.update(par)
    patentes_ambiguas = frozenset(patentes_ambiguas)
    fichas_vehiculos = [
        construir_ficha_vehiculo(
            vehiculo=v, filas=filas, vehiculos_por_patente=vehiculos_por_patente, patentes_ambiguas=patentes_ambiguas,
        )
        for patente, v in vehiculos_por_patente.items() if patente not in plegables
    ]
    fichas_vehiculos.sort(key=lambda f: f["patente"])

    return {
        "choferes": fichas_choferes, "clientes": fichas_clientes,
        "obras": fichas_obras, "vehiculos": fichas_vehiculos,
    }


# ============================================================
# Bloque RELACIONES OPERACIONALES -- consulta puntual para B1
# ============================================================
#
# `construir_snapshot_fichas` sirve a Desktop (un snapshot completo, una
# vez por apertura de Catálogos). B1 necesita lo opuesto: UNA ficha
# puntual, por nombre de chofer reconocido o por patente, con la MISMA
# evidencia (nunca un criterio ni un cálculo paralelo -- reutiliza
# `construir_snapshot_fichas` y sólo filtra el resultado).
#
# Ejemplo de uso pensado (ver ticket): nombre de chofer reconocido -> RUT
# -> vehículos históricos -> combinaciones tracto/rampla -> frecuencia/
# recencia -> contraste contra una lectura OCR dudosa. El contraste en
# sí (decidir si una patente OCR corresponde a una ya asociada) es
# responsabilidad de quien llama (B1, o `evaluar_evidencia_patente` en
# `decisiones_pendientes.py`) -- esta función sólo entrega la evidencia
# ya agregada, nunca decide ni corrige nada por su cuenta.


def buscar_relaciones_chofer(
    *, raiz_atlas: str | Path, nombre: str = "", rut: str = "",
) -> dict[str, object] | None:
    """Busca la ficha de UN chofer por nombre reconocido (canónico o
    alias, normalizado igual que el resto del módulo) o por RUT
    (cualquier formato válido). `None` si ninguno calza -- nunca inventa
    ni aproxima por similitud de texto.

    Devuelve la misma ficha completa que ya consume Desktop: `rut`,
    `vehiculos` (histórico chofer→patente, con `apariciones`/
    `primera_aparicion`/`ultima_aparicion`/`guias_soporte`/
    `nivel_evidencia`), `combinaciones_tracto_rampla` (histórico de
    pares tracto+rampla que este chofer condujo juntos) e `historico`.

    Nunca confirma nada por su cuenta: quien consuma el resultado
    (B1 incluido) trata `nivel_evidencia`/`apariciones` como evidencia
    ponderable, nunca como una corrección ya aplicada."""
    nombre_normalizado = _normalizar_nombre_entidad(nombre) if nombre else ""
    rut_normalizado = _rut_valido_o_none(rut) if rut else None
    if not nombre_normalizado and not rut_normalizado:
        return None
    snapshot = construir_snapshot_fichas(raiz_atlas=raiz_atlas)
    for ficha in snapshot["choferes"]:
        if rut_normalizado and ficha["rut"].get("valor") == rut_normalizado:
            return ficha
        if nombre_normalizado:
            nombres_ficha = {_normalizar_nombre_entidad(n) for n in [ficha["nombre_canonico"], *ficha["aliases"]]}
            if nombre_normalizado in nombres_ficha:
                return ficha
    return None


def buscar_relaciones_vehiculo(*, raiz_atlas: str | Path, patente: str) -> dict[str, object] | None:
    """Busca la ficha de UN vehículo por patente (cualquier variante ya
    resuelta a su canónica confirmada -- ver `_patente_canonica_o_
    plegada`; una patente que sólo existe como confusión OCR de otra ya
    catalogada devuelve la ficha de la canónica). `None` si no hay
    ningún vehículo catalogado que calce.

    Devuelve la misma ficha completa que ya consume Desktop:
    `choferes_asociados` (histórico vehículo→chofer, con `apariciones`/
    `primera_aparicion`/`ultima_aparicion`/`guias_soporte`/
    `nivel_evidencia`) y `combinaciones_tracto_rampla`.

    Si `patente` no calza exacto con ninguna canónica pero es una
    confusión OCR calibrada e inequívoca de una que sí lo es (misma
    regla ya usada por `resolver_patente`/`catalogo_vehiculos.py` --
    nunca un criterio nuevo), devuelve la ficha de esa canónica. Esto es
    precisamente el caso de uso de B1 (Sección B1 del ticket): contrastar
    una lectura documental dudosa contra la evidencia ya conocida."""
    patente_normalizada = normalizar_patente_vehiculo(patente)
    if not patente_normalizada:
        return None
    snapshot = construir_snapshot_fichas(raiz_atlas=raiz_atlas)
    for ficha in snapshot["vehiculos"]:
        if ficha["patente"] == patente_normalizada:
            return ficha
    from atlas_core.catalogo_vehiculos import resolver_patente
    try:
        resultado = resolver_patente(Path(raiz_atlas) / "catalogos_privados" / "vehiculos.json", patente_normalizada)
    except _ERRORES_CATALOGO_VEHICULOS:
        return None  # mismo criterio que `_cargar_vehiculos_por_patente` -- nunca revienta por un catálogo corrupto/ausente
    if resultado.estado in ("COINCIDENCIA_EXACTA", "ALIAS", "CORRECCION_OCR_SEGURA") and resultado.valor_resultado != patente_normalizada:
        for ficha in snapshot["vehiculos"]:
            if ficha["patente"] == resultado.valor_resultado:
                return ficha
    return None
