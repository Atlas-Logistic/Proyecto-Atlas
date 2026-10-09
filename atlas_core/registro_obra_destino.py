"""Registro completo de obra nueva: obra + destino en una sola decisión humana.

Caso real 475629 (PRODALAM SA SAN MIGUEL): Javier registró la obra y de
inmediato apareció una segunda tarjeta (`DESTINO_SIN_CONFIRMAR`) para la
dirección que el mismo documento ya traía -- REGISTRAR responde "¿qué obra
es?" y R3.4.2 encadena después "¿a qué destino corresponde?".

Este módulo prepara ambas respuestas para UNA sola vista previa y una sola
acción, sin fusionar las dos validaciones:

* identidad de obra -- exactamente la de `OBRA_DESCONOCIDA`/`REGISTRAR` (nombre
  confirmado/corregido, reutilización global por nombre);
* geografía -- comuna/región validadas contra la evidencia documental de la
  guía (la misma función que persiste el destino), destino global que se
  reutilizaría y ubicación propuesta sólo desde la base territorial INE
  (calle + número exactos). Una coordenada ya guardada que contradice la
  base territorial bloquea la confirmación conjunta: nunca se confirma un
  punto que la evidencia desmiente.

Sólo lectura: nunca escribe catálogos, dataset ni bandeja. La escritura
vive en `aplicacion_decisiones.aplicar_decision_obra`
(`confirmar_destino_conjunto=True`), que vuelve a evaluar con esta misma
función y exige la `huella` de la vista previa que Javier vio.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import re
from pathlib import Path
from typing import Iterable, Mapping

from atlas_core.catalogo_destinos import CatalogoDestinos, EstadoBusquedaDestino
from atlas_core.catalogo_obras_destinos import CatalogoObrasDestinos, normalizar_nombre_obra

# Mismo vocabulario de ausencia que `decisiones_pendientes._AUSENTES`.
_AUSENTES = {"", "No encontrado", "REVISAR", "Ilegible"}

FUENTE_UBICACION_INE = "BASE_TERRITORIAL_INE"
FUENTE_UBICACION_DESTINO_EXISTENTE = "DESTINO_EXISTENTE"
# Distancia a partir de la cual una coordenada ya guardada se considera
# contradicha por la dirección exacta de la base territorial.
DISTANCIA_MAXIMA_COHERENCIA_KM = 1.0

MOTIVO_SIN_DESTINO_DOCUMENTAL = "SIN_DESTINO_DOCUMENTAL"
MOTIVO_RELACION_YA_CONFIRMADA = "RELACION_OBRA_DESTINO_YA_CONFIRMADA"
MOTIVO_RELACION_POR_EVIDENCIA = "RELACION_CONFIRMADA_POR_EVIDENCIA_EXTERNA"
MOTIVO_DESTINO_AMBIGUO = "DESTINO_GLOBAL_AMBIGUO"
MOTIVO_COORDENADA_CONTRADICHA = "COORDENADA_EXISTENTE_CONTRADICE_BASE_TERRITORIAL"

_PATRON_NUMERO_CALLE = re.compile(r"^\d+[A-Z]?$")


def _asegurar_limite_campo_csv() -> None:
    """El dataset operacional conserva evidencia por fila (p. ej.
    `resultado_atlas_ia_json`) que supera el límite por defecto de ``csv``
    (131072 caracteres). El límite es global del proceso: se asegura justo
    antes de cada lectura, sin depender del orden de importación -- mismo
    criterio que `revalidacion_documental`. Nunca lo baja."""
    from atlas_core.procesamiento_masivo import LIMITE_CAMPO_CSV

    if csv.field_size_limit() < LIMITE_CAMPO_CSV:
        csv.field_size_limit(LIMITE_CAMPO_CSV)


class ErrorRegistroObraDestino(ValueError):
    pass


def calle_y_numero(texto: str) -> str:
    """Calle + número de un DESPACHAR A documental: corta tras el primer
    token numérico ("CARLOS VALDOVINOS 1553 SAN MIGUEL SAN MIGUEL" ->
    "CARLOS VALDOVINOS 1553"). Sin número -> "" (la base territorial no
    puede dar una dirección exacta sin número)."""
    tokens = str(texto or "").replace(",", " ").upper().split()
    for indice, token in enumerate(tokens):
        if indice > 0 and _PATRON_NUMERO_CALLE.match(token):
            return " ".join(tokens[: indice + 1])
    return ""


def comuna_region_validadas(
    *, dataset: Path, numero_guia: str, comuna: str, region: str,
) -> tuple[str, str]:
    """Comuna/región que se persistirán para el destino: una comuna mal
    escrita (variante OCR/tipeo) se reemplaza por la comuna válida que
    trae la evidencia documental de ESTA guía; ante ambigüedad se conserva
    tal cual. La región se deriva siempre de una comuna válida (caso real
    475484: sin región se duplicaba el destino global)."""
    comuna_destino = comuna
    region_destino = region
    if not comuna_destino:
        return comuna_destino, region_destino
    from atlas_core.revalidacion_documental import _leer_filas
    from atlas_core.rutas.destino_entrega import (
        comuna_territorial_desde_evidencia, textos_documentales_destino,
    )
    from atlas_core.territorio_chile import normalizar_comuna

    try:
        fila = next((f for f in _leer_filas(dataset) if str(f.get("numero_guia", "")) == numero_guia), None)
    except (OSError, ValueError):
        fila = None
    comuna_valida = comuna_territorial_desde_evidencia(comuna_destino, textos_documentales_destino(fila or {}))
    if comuna_valida and comuna_valida != comuna_destino:
        comuna_destino = comuna_valida
        region_destino = region_destino or str(normalizar_comuna(comuna_valida).region or "")
    if not region_destino:
        region_destino = str(normalizar_comuna(comuna_destino).region or "")
    return comuna_destino, region_destino


def _leer_fila(dataset: Path, numero_guia: str) -> dict[str, str] | None:
    _asegurar_limite_campo_csv()
    try:
        with Path(dataset).open("r", newline="", encoding="utf-8-sig") as archivo:
            for fila in csv.DictReader(archivo, delimiter=";"):
                if str(fila.get("numero_guia", "")).strip() == numero_guia:
                    return dict(fila)
    except (OSError, UnicodeDecodeError):
        return None
    return None


def _distancia_km(lat_a: float, lon_a: float, lat_b: float, lon_b: float) -> float:
    rad = math.radians
    h = (
        math.sin(rad(lat_b - lat_a) / 2) ** 2
        + math.cos(rad(lat_a)) * math.cos(rad(lat_b)) * math.sin(rad(lon_b - lon_a) / 2) ** 2
    )
    return 2 * 6371.0 * math.asin(math.sqrt(h))


def _nombre_obra_registro(decision: Mapping[str, object], nombre_obra_manual: str | None) -> tuple[str, bool]:
    """Mismo nombre que `aplicar_decision_obra` registrará: el corregido por
    Javier, o el canónico de evidencia externa que ya corroboró la
    dirección (en ese caso REGISTRAR confirma solo la relación), o el texto
    documental tal cual."""
    obra_texto = str(decision.get("valor_documental", "")).strip()
    manual = str(nombre_obra_manual or "").strip()
    if manual:
        return manual, False
    if (decision.get("evaluacion_evidencia") or {}).get("resultado") == "RESUELTO_AUTOMATICAMENTE":
        candidato = next(
            (
                c for c in decision.get("candidatos_evidencia") or []
                if "DIRECCION_DOCUMENTAL_CORROBORADA" in (c.get("evidencias") or [])
            ),
            None,
        )
        if candidato is not None:
            canonico = str(candidato.get("valor_canonico") or "").strip()
            return (canonico or obra_texto), True
    return obra_texto, False


def _ubicacion_territorial(base, destino_texto: str, comuna: str) -> dict[str, object] | None:
    if base is None or not comuna:
        return None
    calle = calle_y_numero(destino_texto)
    if not calle:
        return None
    from atlas_core.rutas.destino_entrega import _candidato_geocodificacion_desde_base_local

    candidato = _candidato_geocodificacion_desde_base_local(base, calle, comuna_territorial_conocida=comuna)
    if candidato is None:
        return None
    return {
        "latitud": float(candidato.coordenadas.latitud),
        "longitud": float(candidato.coordenadas.longitud),
        "fuente": FUENTE_UBICACION_INE,
        "precision": "DIRECCION_EXACTA",
        "etiqueta": candidato.etiqueta,
        "comuna": candidato.localidad,
        "region": candidato.region,
    }


def _huella(datos: Mapping[str, object]) -> str:
    return hashlib.sha256(json.dumps(datos, sort_keys=True, ensure_ascii=True).encode("utf-8")).hexdigest()


def evaluar_registro_obra_destino(
    *, decision: Mapping[str, object], carpeta_catalogos: str | Path, ruta_dataset: str | Path,
    nombre_obra_manual: str | None = None, base_geografica_local=None,
) -> dict[str, object]:
    """Vista previa del registro completo de una `OBRA_DESCONOCIDA`.

    `destino.requiere_confirmacion` replica la decisión de
    `decision_destino_para_obra_registrada` (R3.4.2): False si el documento
    no trae destino (CASO C), si la obra ya tiene una relación CONFIRMADA
    única (CASO A) o si la evidencia externa ya corroboró la dirección (el
    propio REGISTRAR confirma la relación). Sólo cuando es True tiene
    sentido la confirmación conjunta."""
    if decision.get("tipo") != "OBRA_DESCONOCIDA":
        raise ErrorRegistroObraDestino("La vista previa conjunta sólo aplica a una obra nueva.")
    contexto = decision.get("contexto") or {}
    documento = decision.get("documento") or {}
    numero_guia = str(documento.get("numero_guia") or "")
    cliente_id = str(contexto.get("cliente_id", ""))
    obra_texto = str(decision.get("valor_documental", "")).strip()
    if not cliente_id or not obra_texto:
        raise ErrorRegistroObraDestino("La decisión no contiene identidad suficiente para aplicar la obra.")
    carpeta = Path(carpeta_catalogos)
    dataset = Path(ruta_dataset)

    nombre_obra, relacion_por_evidencia = _nombre_obra_registro(decision, nombre_obra_manual)
    catalogo_obras = CatalogoObrasDestinos(
        ruta=carpeta / "obras_destinos.json", ruta_clientes=carpeta / "clientes.json",
        ruta_destinos=carpeta / "destinos_maestros.json",
    )
    clave_obra = normalizar_nombre_obra(nombre_obra)
    obra_existente = next(
        (o for o in catalogo_obras.listar_obras() if normalizar_nombre_obra(o.nombre_canonico) == clave_obra),
        None,
    )
    relacion_confirmada = catalogo_obras.resolver_obra_destino_confirmada_global(nombre_obra=nombre_obra)

    destino_texto = str(contexto.get("destino_documental", "")).strip()
    fila = _leer_fila(dataset, numero_guia) if numero_guia else None
    # Mismo origen de comuna/región que `DESTINO_SIN_CONFIRMAR`/`CONFIRMAR`:
    # sólo la localidad de una ruta YA calculada para esta guía.
    ruta_calculada = fila is not None and str(fila.get("estado_ruta", "")).strip() == "RUTA_CALCULADA"
    comuna_fila = str(fila.get("localidad_entrega") or "").strip() if ruta_calculada else ""
    region_fila = str(fila.get("region_entrega") or "").strip() if ruta_calculada else ""
    comuna, region = comuna_region_validadas(
        dataset=dataset, numero_guia=numero_guia, comuna=comuna_fila, region=region_fila,
    )

    motivo_no_requiere = ""
    if destino_texto in _AUSENTES:
        motivo_no_requiere = MOTIVO_SIN_DESTINO_DOCUMENTAL
    elif relacion_confirmada is not None:
        motivo_no_requiere = MOTIVO_RELACION_YA_CONFIRMADA
    elif relacion_por_evidencia:
        motivo_no_requiere = MOTIVO_RELACION_POR_EVIDENCIA
    requiere_confirmacion = not motivo_no_requiere

    destino_existente = None
    ubicacion = None
    validacion_geografica = {"estado": "NO_APLICA", "motivos": []}
    if requiere_confirmacion:
        catalogo_destinos = CatalogoDestinos(carpeta / "destinos_maestros.json", ruta_clientes=carpeta / "clientes.json")
        busqueda = catalogo_destinos.buscar_reutilizable_global(destino_texto, comuna=comuna, region=region)
        territorial = _ubicacion_territorial(base_geografica_local, destino_texto, comuna)
        motivos: list[str] = []
        if busqueda.estado == EstadoBusquedaDestino.AMBIGUA:
            motivos.append(MOTIVO_DESTINO_AMBIGUO)
        elif busqueda.estado == EstadoBusquedaDestino.COINCIDENCIA and busqueda.destino is not None:
            existente = busqueda.destino
            destino_existente = {
                "destino_id": existente.destino_id, "direccion": existente.direccion,
                "comuna": existente.comuna, "region": existente.region,
                "estado_calidad": existente.estado_calidad,
                "latitud": existente.latitud, "longitud": existente.longitud,
            }
            if existente.latitud is not None and existente.longitud is not None:
                # `crear_o_reutilizar_global` nunca sobrescribe una
                # coordenada ya guardada: confirmar el destino la confirma
                # tal cual. Si la base territorial la contradice, no se
                # ofrece confirmarla junto con la obra.
                if territorial is not None and _distancia_km(
                    float(existente.latitud), float(existente.longitud),
                    float(territorial["latitud"]), float(territorial["longitud"]),
                ) > DISTANCIA_MAXIMA_COHERENCIA_KM:
                    motivos.append(MOTIVO_COORDENADA_CONTRADICHA)
                ubicacion = {
                    "latitud": float(existente.latitud), "longitud": float(existente.longitud),
                    "fuente": FUENTE_UBICACION_DESTINO_EXISTENTE,
                    "precision": "CORROBORADA_BASE_TERRITORIAL" if territorial is not None else "SIN_CORROBORACION_TERRITORIAL",
                    "etiqueta": existente.direccion, "comuna": existente.comuna, "region": existente.region,
                }
        if ubicacion is None and territorial is not None:
            ubicacion = territorial
        if motivos:
            estado_geo = "CONFLICTO"
        elif ubicacion is None:
            estado_geo = "SIN_UBICACION_PROPUESTA"
        elif ubicacion["precision"] == "SIN_CORROBORACION_TERRITORIAL":
            estado_geo = "SIN_CORROBORACION_TERRITORIAL"
        else:
            estado_geo = "OK"
        validacion_geografica = {"estado": estado_geo, "motivos": motivos}

    disponible = requiere_confirmacion and validacion_geografica["estado"] != "CONFLICTO"
    if not requiere_confirmacion:
        motivo_no_disponible = motivo_no_requiere
    elif not disponible:
        motivo_no_disponible = validacion_geografica["motivos"][0]
    else:
        motivo_no_disponible = ""

    propuesta = {
        "decision_id": str(decision.get("decision_id", "")),
        "obra": nombre_obra, "cliente_id": cliente_id,
        "destino": destino_texto if requiere_confirmacion else "",
        "comuna": comuna if requiere_confirmacion else "",
        "region": region if requiere_confirmacion else "",
        "destino_existente_id": (destino_existente or {}).get("destino_id"),
        "latitud": (ubicacion or {}).get("latitud"),
        "longitud": (ubicacion or {}).get("longitud"),
        "fuente_ubicacion": (ubicacion or {}).get("fuente"),
        "disponible": disponible,
    }
    return {
        "decision_id": str(decision.get("decision_id", "")),
        "numero_guia": numero_guia,
        "obra": {
            "nombre": nombre_obra, "nombre_documental": obra_texto,
            "obra_existente_id": obra_existente.obra_id if obra_existente is not None else None,
            "es_nueva": obra_existente is None,
        },
        "cliente": {"cliente_id": cliente_id, "razon_social": str(contexto.get("cliente_canonico", ""))},
        "destino": {
            "requiere_confirmacion": requiere_confirmacion,
            "motivo_no_requiere": motivo_no_requiere,
            "direccion": destino_texto if destino_texto not in _AUSENTES else "",
            "comuna": comuna, "region": region,
            "destino_existente": destino_existente,
        },
        "ubicacion": ubicacion,
        "validaciones": {"geografia": validacion_geografica},
        "confirmacion_conjunta_disponible": disponible,
        "motivo_no_disponible": motivo_no_disponible,
        "huella": _huella(propuesta),
    }


def guias_afectadas_por_registro(
    *, ruta_dataset: str | Path, numero_guia: str, nombres_obra: Iterable[str],
) -> tuple[set[str], set[str]]:
    """(guías, transportes) que un registro de obra+destino puede cambiar:
    la guía de la decisión, las guías cuyo `obra_destino` es esa obra
    (texto documental o nombre canónico) y todas las guías de esos mismos
    transportes (el viaje completo). Nada más se revalida."""
    claves = {normalizar_nombre_obra(n) for n in nombres_obra if str(n or "").strip()}
    filas: list[dict[str, str]] = []
    _asegurar_limite_campo_csv()
    try:
        with Path(ruta_dataset).open("r", newline="", encoding="utf-8-sig") as archivo:
            filas = [dict(f) for f in csv.DictReader(archivo, delimiter=";")]
    except (OSError, UnicodeDecodeError):
        return {numero_guia}, set()
    transportes = {
        str(f.get("numero_transporte", "")).strip()
        for f in filas
        if str(f.get("numero_guia", "")).strip() == numero_guia
        or normalizar_nombre_obra(str(f.get("obra_destino", ""))) in claves
    } - {""}
    guias = {numero_guia} | {
        str(f.get("numero_guia", "")).strip()
        for f in filas
        if str(f.get("numero_transporte", "")).strip() in transportes
        or normalizar_nombre_obra(str(f.get("obra_destino", ""))) in claves
    }
    return guias - {""}, transportes


def previsualizar_registro_obra_destino(
    *, raiz_atlas: str | Path, decision_id: str, nombre_obra_manual: str | None = None,
    base_geografica_local=None, cargar_base_territorial: bool = True,
) -> dict[str, object]:
    """Entrada de la vista previa para Desktop: lee la bandeja vigente,
    ubica la decisión y la evalúa. Nunca escribe nada."""
    raiz = Path(raiz_atlas)
    actual = raiz / "operacion" / "actual"
    try:
        bandeja = json.loads((actual / "decisiones_pendientes.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ErrorRegistroObraDestino("No se pudo leer la bandeja vigente.") from error
    coincidencias = [d for d in bandeja.get("decisiones", []) if d.get("decision_id") == str(decision_id).strip()]
    if len(coincidencias) != 1 or coincidencias[0].get("estado") != "PENDIENTE":
        raise ErrorRegistroObraDestino("La decisión ya no está pendiente.")
    if base_geografica_local is None and cargar_base_territorial:
        from atlas_core.geografia.base_local import cargar_base_geografica_local_ine

        base_geografica_local = cargar_base_geografica_local_ine(raiz=raiz)
    evaluacion = evaluar_registro_obra_destino(
        decision=coincidencias[0], carpeta_catalogos=raiz / "catalogos_privados",
        ruta_dataset=actual / "analisis_completo_guias.csv",
        nombre_obra_manual=nombre_obra_manual, base_geografica_local=base_geografica_local,
    )
    return {"ok": True, **evaluacion}


__all__ = [
    "ErrorRegistroObraDestino", "calle_y_numero", "comuna_region_validadas",
    "evaluar_registro_obra_destino", "guias_afectadas_por_registro",
    "previsualizar_registro_obra_destino",
]
