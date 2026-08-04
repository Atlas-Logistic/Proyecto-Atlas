"""Calcula rutas Desktop con catálogos confirmados y el proveedor ORS existente."""

from __future__ import annotations

import argparse
import csv
import json
import unicodedata
from pathlib import Path
from typing import Iterable

from atlas_core.catalogo_destinos import CatalogoDestinos, Destino
from atlas_core.catalogo_plantas import CatalogoPlantas, Planta
from atlas_core.rutas import (
    CalculadorRutas,
    EstadoCalculoRuta,
    OpenRouteService,
    SolicitudCalculoRuta,
)
from atlas_core.rutas.proveedor import ProveedorRutas


def _normalizar(valor: object) -> str:
    texto = unicodedata.normalize("NFKD", str(valor or "").strip())
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return " ".join(texto.upper().split())


def _unico(valor: object) -> tuple[str | None, str | None]:
    valores = list(dict.fromkeys(
        parte.strip() for parte in str(valor or "").split("|") if parte.strip()
    ))
    if not valores:
        return None, "NO_INFORMADO"
    if len(valores) > 1:
        return None, "MULTIPLES_VALORES"
    return valores[0], None


def _indice_plantas(plantas: Iterable[Planta]) -> dict[str, list[Planta]]:
    indice: dict[str, list[Planta]] = {}
    for planta in plantas:
        if planta.estado_calidad != "CONFIRMADA" or planta.estado_vigencia != "ACTIVA":
            continue
        indice.setdefault(_normalizar(planta.nombre), []).append(planta)
    return indice


def _indice_destinos(destinos: Iterable[Destino]) -> dict[str, list[Destino]]:
    indice: dict[str, list[Destino]] = {}
    for destino in destinos:
        if destino.estado_calidad != "CONFIRMADO" or destino.estado_vigencia != "ACTIVO":
            continue
        for nombre in (destino.nombre_destino, *destino.aliases):
            indice.setdefault(_normalizar(nombre), []).append(destino)
    return indice


def _respuesta(
    viaje_id: str,
    estado: str,
    motivo: str,
    *,
    proveedor: str = "openrouteservice",
    distancia_km: float | None = None,
    duracion: str = "",
) -> dict[str, object]:
    return {
        "viaje_id": viaje_id,
        "estado": estado,
        "distancia_km": distancia_km,
        "tiempo_estimado": duracion or "Pendiente",
        "proveedor": proveedor,
        "motivo": motivo,
    }


def _pendiente(viaje_id: str, motivo: str) -> dict[str, object]:
    mensajes = {
        "ORIGEN_NO_INFORMADO": "origen no informado",
        "ORIGEN_MULTIPLES_VALORES": "origen ambiguo",
        "ORIGEN_NO_CONFIRMADO": "origen no confirmado en catálogo",
        "ORIGEN_DIRECCION_INCOMPLETA": "origen sin dirección completa",
        "ORIGEN_SIN_COORDENADAS": "coordenadas de origen inexistentes",
        "DESTINO_NO_INFORMADO": "destino no informado",
        "DESTINO_MULTIPLES_VALORES": "destino ambiguo",
        "DESTINO_NO_CONFIRMADO": "destino no confirmado en catálogo",
        "DESTINO_DIRECCION_INCOMPLETA": "destino sin dirección completa",
        "DESTINO_SIN_COORDENADAS": "coordenadas de destino inexistentes",
    }
    return _respuesta(viaje_id, "PENDIENTE", mensajes[motivo])


def _entidad_unica(indice: dict[str, list[object]], nombre: str) -> object | None:
    candidatos = indice.get(_normalizar(nombre), [])
    return candidatos[0] if len(candidatos) == 1 else None


def _direccion_valida(entidad: object) -> bool:
    return all(str(getattr(entidad, campo, "") or "").strip()
               for campo in ("direccion", "comuna", "region", "pais"))


def calcular_fila(
    fila: dict[str, str],
    *,
    plantas: dict[str, list[Planta]],
    destinos: dict[str, list[Destino]],
    calculador: CalculadorRutas,
) -> dict[str, object]:
    viaje_id = str(fila.get("viaje_id", "")).strip()
    nombre_origen, error_origen = _unico(fila.get("origenes"))
    if error_origen:
        return _pendiente(viaje_id, f"ORIGEN_{error_origen}")
    planta = _entidad_unica(plantas, nombre_origen or "")
    if planta is None:
        return _pendiente(viaje_id, "ORIGEN_NO_CONFIRMADO")
    if not _direccion_valida(planta):
        return _pendiente(viaje_id, "ORIGEN_DIRECCION_INCOMPLETA")
    if planta.latitud is None or planta.longitud is None:
        return _pendiente(viaje_id, "ORIGEN_SIN_COORDENADAS")

    nombre_destino, error_destino = _unico(fila.get("obras_destino"))
    if error_destino:
        return _pendiente(viaje_id, f"DESTINO_{error_destino}")
    destino = _entidad_unica(destinos, nombre_destino or "")
    if destino is None:
        return _pendiente(viaje_id, "DESTINO_NO_CONFIRMADO")
    if not _direccion_valida(destino):
        return _pendiente(viaje_id, "DESTINO_DIRECCION_INCOMPLETA")
    if destino.latitud is None or destino.longitud is None:
        return _pendiente(viaje_id, "DESTINO_SIN_COORDENADAS")

    resultado = calculador.calcular(SolicitudCalculoRuta(
        planta=planta.nombre,
        planta_confirmada=True,
        coordenadas_origen={"latitud": planta.latitud, "longitud": planta.longitud},
        destino=destino.nombre_destino,
        destino_confirmado=True,
        coordenadas_destino={"latitud": destino.latitud, "longitud": destino.longitud},
        proveedor=calculador.proveedor.nombre,
        evidencia={"viaje_id": viaje_id, "fuente": "catalogos_confirmados"},
    ))
    if resultado.estado is EstadoCalculoRuta.CALCULADA:
        return _respuesta(
            viaje_id, "CALCULADO", "ruta calculada",
            proveedor=resultado.proveedor,
            distancia_km=round(float(resultado.distancia_kilometros), 1),
            duracion=resultado.duracion_legible,
        )
    motivos = {
        EstadoCalculoRuta.CREDENCIAL_NO_DISPONIBLE: "credencial del proveedor no disponible",
        EstadoCalculoRuta.PROVEEDOR_NO_DISPONIBLE: "proveedor no disponible",
        EstadoCalculoRuta.ERROR_PROVEEDOR: "proveedor no disponible",
    }
    return _respuesta(
        viaje_id,
        "NO_DISPONIBLE" if resultado.estado in motivos else "PENDIENTE",
        motivos.get(resultado.estado, "ruta pendiente de revisión"),
        proveedor=resultado.proveedor,
    )


def calcular_rutas(
    ruta_viajes: Path,
    carpeta_catalogos: Path,
    *,
    proveedor: ProveedorRutas | None = None,
) -> list[dict[str, object]]:
    with ruta_viajes.open("r", newline="", encoding="utf-8-sig") as archivo:
        filas = list(csv.DictReader(archivo, delimiter=";"))
    plantas = _indice_plantas(CatalogoPlantas(carpeta_catalogos / "plantas.json").listar())
    destinos = _indice_destinos(CatalogoDestinos(
        carpeta_catalogos / "destinos_maestros.json",
        ruta_clientes=carpeta_catalogos / "clientes.json",
    ).listar())
    calculador = CalculadorRutas(proveedor or OpenRouteService())
    return [
        calcular_fila(fila, plantas=plantas, destinos=destinos, calculador=calculador)
        for fila in filas
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--viajes", type=Path, required=True)
    parser.add_argument("--catalogos", type=Path, required=True)
    argumentos = parser.parse_args()
    print(json.dumps(
        {"resultados": calcular_rutas(argumentos.viajes, argumentos.catalogos)},
        ensure_ascii=False,
    ))


if __name__ == "__main__":
    main()
