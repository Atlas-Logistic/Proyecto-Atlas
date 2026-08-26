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
from atlas_core.catalogos import _normalizar_nombre_entidad, cargar_catalogo_json
from atlas_core.procesamiento_masivo import COLUMNAS
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
            if lector.fieldnames and list(lector.fieldnames) != COLUMNAS:
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
                "fechas": [], "transportes": set(),
            })
            registro["roles_documentales"].add(rol)
            registro["apariciones"] += 1
            registro["fechas"].append(str(fila.get("fecha", "")))
            transporte = str(fila.get("numero_transporte", "")).strip()
            if transporte and transporte not in _AUSENTES:
                registro["transportes"].add(transporte)

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
            "tipo_catalogo": vehiculo_catalogo.tipo if vehiculo_catalogo else None,
            "estado_catalogo": vehiculo_catalogo.estado_calidad if vehiculo_catalogo else "SIN_CATALOGAR",
        })
    salida.sort(key=lambda v: (-v["apariciones"], v["patente"]))
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


def construir_ficha_vehiculo(*, vehiculo, filas: list[dict[str, str]], vehiculos_por_patente: Mapping[str, object]) -> dict[str, object]:
    """Las guías cuya patente documental es una confusión OCR de esta
    canónica (ver `_patente_canonica_o_plegada`) se incluyen igual --
    nunca faltan relaciones/histórico sólo porque el documento tenía un
    error de lectura ya resuelto en la ficha del chofer."""
    patente = vehiculo.patente_canonica
    filas_vehiculo = [
        f for f in filas
        if _patente_canonica_o_plegada(normalizar_patente_vehiculo(str(f.get("patente_tracto", ""))), "TRACTO", vehiculos_por_patente) == patente
        or _patente_canonica_o_plegada(normalizar_patente_vehiculo(str(f.get("patente_rampla", ""))), "CARRO", vehiculos_por_patente) == patente
    ]
    choferes: dict[str, int] = {}
    for f in filas_vehiculo:
        nombre = str(f.get("chofer", "")).strip()
        if nombre and nombre not in _AUSENTES:
            choferes[nombre] = choferes.get(nombre, 0) + 1
    primera, ultima = _primera_ultima(str(f.get("fecha", "")) for f in filas_vehiculo)
    return {
        "tipo": "VEHICULO",
        "identificador": vehiculo.vehiculo_id,
        "patente": patente,
        "tipo_vehiculo": vehiculo.tipo,
        "estado_calidad": vehiculo.estado_calidad,
        "estado_vigencia": vehiculo.estado_vigencia,
        "aliases": list(vehiculo.aliases),
        "confirmado_por": vehiculo.confirmado_por,
        "choferes_asociados": _top(choferes, n=10),
        "primera_aparicion": primera,
        "ultima_aparicion": ultima,
        "guias_relacionadas": sorted({str(f.get("numero_guia", "")) for f in filas_vehiculo if f.get("numero_guia") not in _AUSENTES}),
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
    fichas_vehiculos = [
        construir_ficha_vehiculo(vehiculo=v, filas=filas, vehiculos_por_patente=vehiculos_por_patente)
        for patente, v in vehiculos_por_patente.items() if patente not in plegables
    ]
    fichas_vehiculos.sort(key=lambda f: f["patente"])

    return {
        "choferes": fichas_choferes, "clientes": fichas_clientes,
        "obras": fichas_obras, "vehiculos": fichas_vehiculos,
    }
