"""Carga y consulta de catálogos maestros locales."""

import difflib
import json
import logging
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping


Catalogo = Mapping[str, dict[str, Any]]
FuenteCatalogo = Catalogo | str | Path
logger = logging.getLogger(__name__)


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


UMBRAL_NOMBRE_CHOFER_DIFUSO = 0.85
MARGEN_MINIMO_NOMBRE_CHOFER_DIFUSO = 0.05


@dataclass(frozen=True)
class ResultadoCoincidenciaChofer:
    """Decisión trazable y sin efectos laterales del matching de chofer."""

    estado: str
    valor_original: str
    valor_resultado: str
    similitud: float | None = None
    segunda_similitud: float | None = None
    margen: float | None = None


def _normalizar_nombre_chofer(texto: str) -> str:
    texto_mayuscula = " ".join(str(texto or "").strip().upper().split())
    sin_acentos = unicodedata.normalize("NFKD", texto_mayuscula)
    return "".join(
        caracter for caracter in sin_acentos
        if not unicodedata.combining(caracter)
    )


def _similitud_nombre_chofer(a: str, b: str) -> float:
    a_normalizado = _normalizar_nombre_chofer(a)
    b_normalizado = _normalizar_nombre_chofer(b)
    if not a_normalizado or not b_normalizado:
        return 0.0
    return difflib.SequenceMatcher(None, a_normalizado, b_normalizado).ratio()


def resolver_nombre_chofer_difuso(
    catalogo: FuenteCatalogo,
    nombre: str,
    *,
    umbral: float = UMBRAL_NOMBRE_CHOFER_DIFUSO,
    margen_ambiguedad: float = MARGEN_MINIMO_NOMBRE_CHOFER_DIFUSO,
) -> ResultadoCoincidenciaChofer:
    """Resuelve un nombre solo contra choferes activos y se abstiene ante duda."""
    original = str(nombre or "").strip()
    if not original or original == "No encontrado":
        return ResultadoCoincidenciaChofer("SIN_CAMBIO", original, original)

    candidatos: list[tuple[float, str]] = []
    for registro in _obtener_catalogo(catalogo).values():
        if not isinstance(registro, dict) or registro.get("activo", True) is not True:
            continue
        nombre_catalogo = str(registro.get("nombre", "")).strip()
        if nombre_catalogo:
            variantes = [nombre_catalogo]
            aliases = registro.get("aliases", [])
            if isinstance(aliases, list):
                variantes.extend(
                    str(alias).strip() for alias in aliases if str(alias).strip()
                )
            candidatos.append(
                (
                    max(_similitud_nombre_chofer(original, variante) for variante in variantes),
                    nombre_catalogo,
                )
            )

    if not candidatos:
        return ResultadoCoincidenciaChofer("CATALOGO_VACIO", original, original)

    candidatos.sort(key=lambda candidato: (-candidato[0], candidato[1]))
    mejor_similitud, mejor_nombre = candidatos[0]
    segunda_similitud = candidatos[1][0] if len(candidatos) > 1 else None
    margen = (
        mejor_similitud - segunda_similitud
        if segunda_similitud is not None
        else None
    )
    if mejor_similitud < umbral:
        return ResultadoCoincidenciaChofer(
            "DEBAJO_UMBRAL", original, original, mejor_similitud,
            segunda_similitud, margen,
        )

    if margen is not None and margen < margen_ambiguedad:
        return ResultadoCoincidenciaChofer(
            "AMBIGUO", original, original, mejor_similitud,
            segunda_similitud, margen,
        )

    if _normalizar_nombre_chofer(original) == _normalizar_nombre_chofer(mejor_nombre):
        return ResultadoCoincidenciaChofer(
            "SIN_CAMBIO", original, mejor_nombre, mejor_similitud,
            segunda_similitud, margen,
        )
    return ResultadoCoincidenciaChofer(
        "COINCIDENCIA_SEGURA", original, mejor_nombre, mejor_similitud,
        segunda_similitud, margen,
    )


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


def _buscar_cliente_maestro_por_rut(contenido: Any, rut: str) -> dict[str, Any] | None:
    rut_normalizado = normalizar_rut(rut)
    if not rut_normalizado or not isinstance(contenido, dict):
        return None
    for registro in contenido.get("clientes", []):
        if (
            isinstance(registro, dict)
            and registro.get("estado_calidad") == "CONFIRMADO"
            and registro.get("estado_vigencia") == "ACTIVO"
            and normalizar_rut(str(registro.get("rut", ""))) == rut_normalizado
        ):
            return registro
    return None


def _buscar_destino_maestro_en_textos(
    textos: list[str], contenido: Any
) -> dict[str, Any] | None:
    if not isinstance(contenido, dict):
        return None
    texto_ocr = _texto_sin_acentos("\n".join(textos).upper())
    codigos = {
        str(registro.get("codigo_destino", "")).strip().upper(): registro
        for registro in contenido.get("destinos", [])
        if isinstance(registro, dict)
        and registro.get("estado_vigencia") == "ACTIVO"
        and registro.get("estado_calidad") in {"CONFIRMADO", "CONFIRMADO_DOCUMENTAL"}
        and str(registro.get("codigo_destino", "")).strip()
    }
    patron = re.compile(
        r"\bC[O0][D0O](?:IG[O0])?\.?\s+D[E3]STINATARI[O0]\b"
        r"\s*[:\-]?\s*([A-Z0-9_-]+)"
    )
    for coincidencia in patron.finditer(texto_ocr):
        registro = codigos.get(coincidencia.group(1).upper())
        if registro is not None:
            return registro
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
    clientes_maestros = cargar_catalogo_json(carpeta / "clientes.json")
    destinos_maestros = cargar_catalogo_json(carpeta / "destinos_maestros.json")
    choferes = cargar_catalogo_json(carpeta / "choferes.json")
    vehiculos = cargar_catalogo_json(carpeta / "vehiculos.json")

    datos_enriquecidos = datos.copy()

    empresa = buscar_empresa_por_rut(empresas, datos.get("RUT del cliente", ""))
    cliente_maestro = _buscar_cliente_maestro_por_rut(
        clientes_maestros, datos.get("RUT del cliente", "")
    )
    if cliente_maestro is not None:
        razon_social = cliente_maestro.get("razon_social")
        if isinstance(razon_social, str) and razon_social.strip():
            datos_enriquecidos["cliente"] = razon_social.strip()
    elif empresa is not None:
        nombre_empresa = empresa.get("nombre")
        if isinstance(nombre_empresa, str) and nombre_empresa.strip():
            datos_enriquecidos["cliente"] = nombre_empresa.strip()

    nombre_ocr = str(datos.get("chofer", "")).strip()
    decision_nombre = resolver_nombre_chofer_difuso(choferes, nombre_ocr)
    chofer = buscar_chofer_por_rut(choferes, datos.get("RUT del chofer", ""))
    nombre_por_rut = (
        str(chofer.get("nombre", "")).strip()
        if isinstance(chofer, dict) else ""
    )
    if decision_nombre.estado in {"COINCIDENCIA_SEGURA", "SIN_CAMBIO"} and (
        decision_nombre.similitud is not None
    ):
        datos_enriquecidos["chofer"] = decision_nombre.valor_resultado
        if nombre_por_rut and _normalizar_nombre_chofer(nombre_por_rut) != _normalizar_nombre_chofer(
            decision_nombre.valor_resultado
        ):
            logger.warning(
                "conflicto-chofer-nombre-rut-v1 nombre=%s rut=%s; se conserva "
                "la decisión fuzzy segura y se requiere revisión",
                decision_nombre.valor_resultado, nombre_por_rut,
            )
    elif nombre_por_rut:
        datos_enriquecidos["chofer"] = nombre_por_rut

    destino = _buscar_destino_maestro_en_textos(textos, destinos_maestros)
    if destino is not None:
        nombre_destino = destino.get("nombre_destino")
        if isinstance(nombre_destino, str) and nombre_destino.strip():
            datos_enriquecidos["obra destino"] = nombre_destino.strip()
    else:
        destino = _buscar_destino_en_textos(textos, destinos)
    if destino is not None:
        nombre_destino = destino.get("nombre_destino", destino.get("nombre"))
        if isinstance(nombre_destino, str) and nombre_destino.strip():
            datos_enriquecidos["obra destino"] = nombre_destino.strip()

    for campo_patente in ("patente del tracto", "patente del carro"):
        patente = datos.get(campo_patente, "")
        if buscar_vehiculo_por_patente(vehiculos, patente) is not None:
            patente_normalizada = normalizar_patente(patente)
            if patente_normalizada:
                datos_enriquecidos[campo_patente] = patente_normalizada

    return datos_enriquecidos
