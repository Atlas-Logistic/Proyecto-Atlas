"""Carga y consulta de catálogos maestros locales."""

import json
from pathlib import Path
from typing import Any, Callable, Mapping


Catalogo = Mapping[str, dict[str, Any]]
FuenteCatalogo = Catalogo | str | Path


def normalizar_rut(rut: str) -> str:
    """Elimina formato de un RUT y conserva números y K mayúscula."""
    rut_mayuscula = str(rut or "").upper()
    return "".join(
        caracter for caracter in rut_mayuscula if caracter.isdigit() or caracter == "K"
    )


def normalizar_patente(patente: str) -> str:
    """Elimina espacios de una patente y la convierte a mayúsculas."""
    return "".join(str(patente or "").split()).upper()


def cargar_catalogo_json(ruta: str | Path) -> dict[str, dict[str, Any]]:
    """Carga un catálogo JSON o devuelve un diccionario vacío si no está disponible."""
    ruta_catalogo = Path(ruta)
    if not ruta_catalogo.exists():
        return {}

    try:
        with ruta_catalogo.open("r", encoding="utf-8") as archivo:
            contenido = json.load(archivo)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

    return contenido if isinstance(contenido, dict) else {}


def _obtener_catalogo(fuente: FuenteCatalogo) -> Catalogo:
    if isinstance(fuente, Mapping):
        return fuente
    return cargar_catalogo_json(fuente)


def _buscar_registro(
    fuente: FuenteCatalogo,
    clave: str,
    normalizador: Callable[[str], str],
) -> dict[str, Any] | None:
    catalogo = _obtener_catalogo(fuente)
    clave_normalizada = normalizador(clave)

    registro = catalogo.get(clave_normalizada)
    if isinstance(registro, dict):
        return registro

    for clave_catalogo, registro_catalogo in catalogo.items():
        if (
            normalizador(clave_catalogo) == clave_normalizada
            and isinstance(registro_catalogo, dict)
        ):
            return registro_catalogo

    return None


def _normalizar_codigo(codigo: str) -> str:
    return "".join(str(codigo or "").split()).upper()


def buscar_empresa_por_rut(
    catalogo: FuenteCatalogo, rut: str
) -> dict[str, Any] | None:
    """Busca una empresa por su RUT y devuelve su registro completo."""
    return _buscar_registro(catalogo, rut, normalizar_rut)


def buscar_destino_por_codigo(
    catalogo: FuenteCatalogo, codigo: str
) -> dict[str, Any] | None:
    """Busca un destino por su código y devuelve su registro completo."""
    return _buscar_registro(catalogo, codigo, _normalizar_codigo)


def buscar_chofer_por_rut(
    catalogo: FuenteCatalogo, rut: str
) -> dict[str, Any] | None:
    """Busca un chofer por su RUT y devuelve su registro completo."""
    return _buscar_registro(catalogo, rut, normalizar_rut)


def buscar_vehiculo_por_patente(
    catalogo: FuenteCatalogo, patente: str
) -> dict[str, Any] | None:
    """Busca un vehículo por su patente y devuelve su registro completo."""
    return _buscar_registro(catalogo, patente, normalizar_patente)
