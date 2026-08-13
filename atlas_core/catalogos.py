"""Carga y consulta de catálogos maestros locales."""

import difflib
import json
import os
import re
import tempfile
import unicodedata
from dataclasses import dataclass
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


# Confusiones OCR documentadas y de evidencia conocida en el proyecto (no una
# tabla amplia inventada). Cada par es simétrico: una B leída como D o una D
# leída como B se tratan igual.
_CONFUSIONES_OCR_PATENTE_COMUNES = (
    frozenset({"B", "D"}),
    frozenset({"0", "O"}),
    frozenset({"1", "I"}),
    frozenset({"5", "S"}),
    frozenset({"8", "B"}),
)


def _forma_patente_plausible(valor: str) -> bool:
    return bool(re.fullmatch(r"(?=.*[A-Z])(?=.*\d)[A-Z0-9]{6}", valor))


def _diferencia_ocr_unica_y_valida(valor_ocr: str, valor_catalogo: str) -> bool:
    """True si ambos valores difieren en exactamente una posición y esa
    diferencia corresponde a una confusión OCR común y documentada."""
    if len(valor_ocr) != len(valor_catalogo):
        return False
    diferencias = [
        (a, b) for a, b in zip(valor_ocr, valor_catalogo) if a != b
    ]
    if len(diferencias) != 1:
        return False
    a, b = diferencias[0]
    return frozenset({a, b}) in _CONFUSIONES_OCR_PATENTE_COMUNES


@dataclass(frozen=True)
class ResultadoResolucionPatente:
    """Decisión trazable y sin efectos laterales de la homologación de patente."""

    estado: str
    valor_original: str
    valor_resultado: str
    candidatos_ambiguos: tuple[str, ...] = ()


def resolver_patente_canonica(
    catalogo: FuenteCatalogo,
    patente_ocr: str,
    *,
    tipo_esperado: str | None = None,
) -> ResultadoResolucionPatente:
    """Homologa una patente OCR contra el catálogo canónico de vehículos.

    Nunca inventa una patente nueva: solo acepta un valor que ya existe en el
    catálogo, y solo cuando la evidencia es inequívoca:

    A. coincidencia exacta normalizada -> acepta.
    B. alias explícito declarado en el registro del vehículo -> acepta.
    C. corrección OCR conservadora -> acepta solo si hay un único candidato de
       catálogo, con la misma longitud, y la diferencia es de una sola
       posición explicada por una confusión OCR común y documentada
       (B/D, 0/O, 1/I, 5/S, 8/B). Dos o más diferencias, o dos o más
       candidatos igualmente plausibles, nunca se corrigen.

    `tipo_esperado` (p. ej. "TRACTO" o "CARRO") filtra los candidatos de la
    corrección conservadora por el campo `tipo` del registro, cuando ese
    campo existe; reduce falsos positivos entre tracto y carro sin excluir
    catálogos que no declaren `tipo`.

    Se abstiene (devuelve el valor OCR sin cambios) ante catálogo vacío,
    patente vacía/"No encontrado", ambigüedad, o ausencia de candidato.
    """
    original = str(patente_ocr or "").strip()
    if not original or original == "No encontrado":
        return ResultadoResolucionPatente("VACIO", original, original)

    valor_ocr = normalizar_patente(original)
    catalogo_dict = _obtener_catalogo(catalogo)
    if not catalogo_dict:
        return ResultadoResolucionPatente("CATALOGO_VACIO", original, original)

    registros = [
        (normalizar_patente(clave), registro)
        for clave, registro in catalogo_dict.items()
        if isinstance(registro, dict)
    ]

    # A. Coincidencia exacta normalizada.
    for clave_normalizada, _registro in registros:
        if clave_normalizada == valor_ocr:
            return ResultadoResolucionPatente("COINCIDENCIA_EXACTA", original, clave_normalizada)

    # B. Alias explícito declarado en el catálogo (no inferido).
    aliases_encontrados: set[str] = set()
    for clave_normalizada, registro in registros:
        alias = registro.get("alias")
        if not isinstance(alias, list):
            continue
        for candidato_alias in alias:
            if normalizar_patente(str(candidato_alias)) == valor_ocr:
                aliases_encontrados.add(clave_normalizada)
                break
    if len(aliases_encontrados) == 1:
        return ResultadoResolucionPatente("ALIAS", original, next(iter(aliases_encontrados)))
    if len(aliases_encontrados) > 1:
        return ResultadoResolucionPatente(
            "AMBIGUO", original, original, tuple(sorted(aliases_encontrados))
        )

    # C. Corrección OCR conservadora: solo si la forma es plausible y hay un
    # único candidato compatible en el catálogo.
    if not _forma_patente_plausible(valor_ocr):
        return ResultadoResolucionPatente("SIN_CANDIDATO", original, original)

    candidatos: set[str] = set()
    for clave_normalizada, registro in registros:
        if clave_normalizada == valor_ocr:
            continue
        if tipo_esperado is not None:
            tipo_registro = registro.get("tipo")
            if (
                isinstance(tipo_registro, str)
                and tipo_registro.strip().upper() != tipo_esperado.strip().upper()
            ):
                continue
        if _diferencia_ocr_unica_y_valida(valor_ocr, clave_normalizada):
            candidatos.add(clave_normalizada)

    if len(candidatos) == 1:
        return ResultadoResolucionPatente("CORRECCION_OCR_SEGURA", original, next(iter(candidatos)))
    if len(candidatos) > 1:
        return ResultadoResolucionPatente(
            "AMBIGUO", original, original, tuple(sorted(candidatos))
        )
    return ResultadoResolucionPatente("SIN_CANDIDATO", original, original)


UMBRAL_NOMBRE_CHOFER_DIFUSO = 0.85
MARGEN_MINIMO_NOMBRE_CHOFER_DIFUSO = 0.05
UMBRAL_NOMBRE_EMPRESA_DIFUSO = 0.85
MARGEN_MINIMO_NOMBRE_EMPRESA_DIFUSO = 0.05


@dataclass(frozen=True)
class ResultadoCoincidenciaChofer:
    """Decisión trazable y sin efectos laterales del matching de chofer."""

    estado: str
    valor_original: str
    valor_resultado: str
    similitud: float | None = None


# Alias de ResultadoCoincidenciaChofer -- Bloque INTELIGENCIA N1: el
# resolver difuso ahora es genérico (chofer y empresa comparten la misma
# forma de resultado); se conserva el nombre histórico para no romper
# `resolver_nombre_chofer_difuso` (usado en ~10 archivos de test).
ResultadoCoincidenciaEntidad = ResultadoCoincidenciaChofer


def _normalizar_nombre_chofer(texto: str) -> str:
    texto_mayuscula = " ".join(str(texto or "").strip().upper().split())
    sin_acentos = unicodedata.normalize("NFKD", texto_mayuscula)
    return "".join(
        caracter for caracter in sin_acentos
        if not unicodedata.combining(caracter)
    )


# Alias genérico -- misma normalización sirve para nombre de persona o de
# empresa (mayúsculas, sin acentos, espacios colapsados).
_normalizar_nombre_entidad = _normalizar_nombre_chofer


def _similitud_nombre_chofer(a: str, b: str) -> float:
    a_normalizado = _normalizar_nombre_chofer(a)
    b_normalizado = _normalizar_nombre_chofer(b)
    if not a_normalizado or not b_normalizado:
        return 0.0
    return difflib.SequenceMatcher(None, a_normalizado, b_normalizado).ratio()


def _resolver_nombre_difuso_generico(
    catalogo: FuenteCatalogo,
    nombre: str,
    *,
    umbral: float,
    margen_ambiguedad: float,
    filtro_registro: Callable[[dict[str, Any]], bool] | None = None,
) -> ResultadoCoincidenciaChofer:
    """Núcleo compartido de resolución difusa contra un catálogo genérico
    (Bloque INTELIGENCIA N1, Fase F -- "resolver general" reutilizado por
    chofer y empresa/cliente, mismo criterio de evidencia para ambos).

    Antes de cualquier fuzzy, revisa `aliases` (lista opcional por
    registro, ya presente en `choferes.json` pero hasta ahora nunca
    consultada por este resolver): una coincidencia EXACTA contra un
    alias conocido es evidencia fuerte por diseño (fue confirmada alguna
    vez) -- no necesita pasar el umbral difuso. Dos registros distintos
    con el mismo alias exacto son una ambigüedad real -- se abstiene.

    Se abstiene (nunca adivina) si: no hay candidato sobre el umbral, o
    el mejor candidato no tiene margen suficiente sobre el segundo."""
    original = str(nombre or "").strip()
    if not original or original == "No encontrado":
        return ResultadoCoincidenciaChofer("SIN_CAMBIO", original, original)

    registros = [
        registro
        for registro in _obtener_catalogo(catalogo).values()
        if isinstance(registro, dict) and (filtro_registro is None or filtro_registro(registro))
    ]

    original_normalizado = _normalizar_nombre_entidad(original)
    coincidencias_alias: set[str] = set()
    for registro in registros:
        nombre_catalogo = str(registro.get("nombre", "")).strip()
        aliases = registro.get("aliases")
        if not isinstance(aliases, list) or not nombre_catalogo:
            continue
        for alias in aliases:
            if _normalizar_nombre_entidad(str(alias)) == original_normalizado:
                coincidencias_alias.add(nombre_catalogo)
                break
    if len(coincidencias_alias) == 1:
        return ResultadoCoincidenciaChofer("ALIAS", original, next(iter(coincidencias_alias)))
    if len(coincidencias_alias) > 1:
        return ResultadoCoincidenciaChofer("AMBIGUO", original, original)

    candidatos: list[tuple[float, str]] = []
    for registro in registros:
        nombre_catalogo = str(registro.get("nombre", "")).strip()
        if nombre_catalogo:
            candidatos.append((_similitud_nombre_chofer(original, nombre_catalogo), nombre_catalogo))

    if not candidatos:
        return ResultadoCoincidenciaChofer("CATALOGO_VACIO", original, original)

    candidatos.sort(key=lambda candidato: (-candidato[0], candidato[1]))
    mejor_similitud, mejor_nombre = candidatos[0]
    if mejor_similitud < umbral:
        return ResultadoCoincidenciaChofer(
            "DEBAJO_UMBRAL", original, original, mejor_similitud
        )

    if len(candidatos) > 1:
        segunda_similitud = candidatos[1][0]
        if mejor_similitud - segunda_similitud < margen_ambiguedad:
            return ResultadoCoincidenciaChofer(
                "AMBIGUO", original, original, mejor_similitud
            )

    if _normalizar_nombre_entidad(original) == _normalizar_nombre_entidad(mejor_nombre):
        return ResultadoCoincidenciaChofer(
            "SIN_CAMBIO", original, original, mejor_similitud
        )
    return ResultadoCoincidenciaChofer(
        "COINCIDENCIA_SEGURA", original, mejor_nombre, mejor_similitud
    )


def resolver_nombre_chofer_difuso(
    catalogo: FuenteCatalogo,
    nombre: str,
    *,
    umbral: float = UMBRAL_NOMBRE_CHOFER_DIFUSO,
    margen_ambiguedad: float = MARGEN_MINIMO_NOMBRE_CHOFER_DIFUSO,
) -> ResultadoCoincidenciaChofer:
    """Resuelve un nombre solo contra choferes activos y se abstiene ante duda."""
    return _resolver_nombre_difuso_generico(
        catalogo, nombre, umbral=umbral, margen_ambiguedad=margen_ambiguedad,
        filtro_registro=lambda registro: registro.get("activo", True) is True,
    )


def resolver_nombre_empresa_difuso(
    catalogo: FuenteCatalogo,
    nombre: str,
    *,
    umbral: float = UMBRAL_NOMBRE_EMPRESA_DIFUSO,
    margen_ambiguedad: float = MARGEN_MINIMO_NOMBRE_EMPRESA_DIFUSO,
) -> ResultadoCoincidenciaChofer:
    """Resuelve un nombre de cliente/empresa contra `empresas.json` --
    mismo criterio de evidencia que `resolver_nombre_chofer_difuso`
    (Bloque INTELIGENCIA N1, Fase F/I): único candidato, sobre el umbral,
    con margen sobre el segundo. Nunca inventa una identidad nueva --
    ante un cliente genuinamente no catalogado, se abstiene
    (`DEBAJO_UMBRAL`/`CATALOGO_VACIO`), dejando el valor documental
    intacto para que quien reciba el resultado decida si corresponde
    registrarlo como entidad nueva."""
    return _resolver_nombre_difuso_generico(
        catalogo, nombre, umbral=umbral, margen_ambiguedad=margen_ambiguedad,
    )


def registrar_alias_seguro(
    ruta_catalogo: str | Path, identificador: str, alias_nuevo: str
) -> bool:
    """Persiste `alias_nuevo` (una variante OCR ya vista) en el registro
    `identificador` de un catálogo simple (`choferes.json`/`empresas.json`,
    dict clave->registro con lista opcional `aliases`) -- Bloque
    INTELIGENCIA N1, Fase K (aprendizaje controlado, no machine learning).

    Solo escribe si TODAS estas condiciones se cumplen (evidencia fuerte,
    sin conflicto, trazable):
    - el catálogo existe y `identificador` identifica exactamente un
      registro;
    - `alias_nuevo` no es vacío ni ya coincide (normalizado) con el
      nombre canónico de ESE registro (no hay nada que aprender);
    - `alias_nuevo` no coincide (normalizado) con el nombre NI con
      ningún alias de NINGÚN OTRO registro del catálogo (evita que la
      misma corrupción OCR quede apuntando a dos entidades distintas).

    Devuelve True si se agregó, False si no había nada que hacer o si
    surgió cualquier conflicto -- nunca lanza por una condición de
    negocio, solo por error de E/S al escribir."""
    ruta = Path(ruta_catalogo)
    catalogo = cargar_catalogo_json(ruta)
    if identificador not in catalogo or not isinstance(catalogo[identificador], dict):
        return False

    registro = catalogo[identificador]
    nombre_canonico = str(registro.get("nombre", "")).strip()
    alias_normalizado = _normalizar_nombre_entidad(alias_nuevo)
    if not alias_normalizado or not nombre_canonico:
        return False
    if alias_normalizado == _normalizar_nombre_entidad(nombre_canonico):
        return False  # ya es el nombre canónico, no es un alias nuevo

    for clave, otro_registro in catalogo.items():
        if not isinstance(otro_registro, dict):
            continue
        valores_existentes = [str(otro_registro.get("nombre", ""))]
        aliases_existentes = otro_registro.get("aliases")
        if isinstance(aliases_existentes, list):
            valores_existentes.extend(str(a) for a in aliases_existentes)
        if any(_normalizar_nombre_entidad(v) == alias_normalizado for v in valores_existentes):
            if clave == identificador:
                return False  # ya registrado en este mismo registro
            return False  # pertenece a otro registro -- conflicto, no se aprende

    aliases_actuales = registro.get("aliases")
    aliases_actuales = list(aliases_actuales) if isinstance(aliases_actuales, list) else []
    aliases_actuales.append(str(alias_nuevo).strip())
    catalogo[identificador] = {**registro, "aliases": aliases_actuales}

    temporal: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="\n", dir=ruta.parent,
            prefix=f".{ruta.name}.", suffix=".tmp", delete=False,
        ) as archivo:
            temporal = Path(archivo.name)
            json.dump(catalogo, archivo, ensure_ascii=False, indent=2)
            archivo.write("\n")
            archivo.flush()
            os.fsync(archivo.fileno())
        os.replace(temporal, ruta)
    except OSError:
        if temporal is not None:
            temporal.unlink(missing_ok=True)
        raise
    return True


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
