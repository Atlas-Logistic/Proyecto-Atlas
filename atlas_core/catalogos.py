"""Carga y consulta de catálogos maestros locales."""

import json
import re
import unicodedata
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


def _texto_sin_acentos(texto: str) -> str:
    texto_normalizado = unicodedata.normalize("NFD", texto)
    return "".join(
        caracter for caracter in texto_normalizado if unicodedata.category(caracter) != "Mn"
    )


def _buscar_destino_en_textos(
    textos: list[str], catalogo: Catalogo
) -> dict[str, Any] | None:
    texto_ocr = _texto_sin_acentos("\n".join(textos).upper())
    patron = re.compile(
        r"\bC[O0][D0O](?:IG[O0])?\.?\s+D[E3]STINATARI[O0]\b"
        r"\s*[:\-]?\s*([A-Z0-9_-]+)"
    )

    for coincidencia in patron.finditer(texto_ocr):
        destino = buscar_destino_por_codigo(catalogo, coincidencia.group(1))
        if destino is not None:
            return destino

    return None


def enriquecer_datos_con_catalogos(
    datos: dict[str, str],
    textos: list[str],
    carpeta_catalogos: str | Path = "catalogos",
) -> dict[str, str]:
    """Corrige datos OCR usando catálogos locales sin modificar esos archivos."""
    carpeta = Path(carpeta_catalogos)
    empresas = cargar_catalogo_json(carpeta / "empresas.json")
    destinos = cargar_catalogo_json(carpeta / "destinos.json")
    choferes = cargar_catalogo_json(carpeta / "choferes.json")
    vehiculos = cargar_catalogo_json(carpeta / "vehiculos.json")

    datos_enriquecidos = datos.copy()

    empresa = buscar_empresa_por_rut(empresas, datos.get("RUT del cliente", ""))
    if empresa is not None:
        nombre_empresa = empresa.get("nombre")
        if isinstance(nombre_empresa, str) and nombre_empresa.strip():
            datos_enriquecidos["cliente"] = nombre_empresa.strip()

    chofer = buscar_chofer_por_rut(choferes, datos.get("RUT del chofer", ""))
    if chofer is not None:
        nombre_chofer = chofer.get("nombre")
        if isinstance(nombre_chofer, str) and nombre_chofer.strip():
            datos_enriquecidos["chofer"] = nombre_chofer.strip()

    destino = _buscar_destino_en_textos(textos, destinos)
    if destino is not None:
        nombre_destino = destino.get("nombre")
        if isinstance(nombre_destino, str) and nombre_destino.strip():
            datos_enriquecidos["obra destino"] = nombre_destino.strip()

    for campo_patente in ("patente del tracto", "patente del carro"):
        patente = datos.get(campo_patente, "")
        if buscar_vehiculo_por_patente(vehiculos, patente) is not None:
            patente_normalizada = normalizar_patente(patente)
            if patente_normalizada:
                datos_enriquecidos[campo_patente] = patente_normalizada

    return datos_enriquecidos
