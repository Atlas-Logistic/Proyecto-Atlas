"""Verificador de referencia del contrato Cloud v2 — SOLO PARA PRUEBAS.

Implementación Python independiente de las secciones 1-3 de
``docs/contrato-cloud-v2-inventarios.md`` (Atlas-Mobile-Cloud ``79de408``),
escrita a partir del texto del contrato y contrastada con los vectores
publicados por Codex (``vectores_cloud_v2.json``) y con su modelo Node.

No es el adaptador Motor-Cloud v2: no hace E/S ni HTTP, no se importa desde
``atlas_core`` y no debe moverse allí. Sirve para demostrar que el descriptor
Motor v2 puede representarse y comprobarse con este contrato, y para fijar las
reglas que el futuro adaptador en ``descriptor_custodia.py`` deberá cumplir.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

VERSION = 2
RUTA_DESCRIPTOR = "_atlas/descriptor_generacion.json"
OBJETOS_POR_PARTE = 100
MAX_BYTES_PARTE = 65536
MAX_ENTERO = 2 ** 53 - 1
MAX_RUTA = 256
PATRON_EMPRESA = re.compile(r"^[a-z][a-z0-9-]{1,38}[a-z0-9]$")
PATRON_GENERACION = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
PATRON_RUTA = re.compile(r"^[a-z0-9][a-z0-9._-]*(/[a-z0-9][a-z0-9._-]*)*$")
PATRON_SHA = re.compile(r"^[0-9a-f]{64}$")
CLAVES_CABECERA = ("anterior_id", "empresa_id", "generacion_id", "numero_objetos", "numero_partes",
                   "raiz_partes", "sha_descriptor_motor", "version")
CLAVES_PARTE = ("cantidad", "empresa_id", "generacion_id", "indice", "objetos", "version")
CLAVES_OBJETO = ("ruta", "sha256")


class ErrorCloudV2(Exception):
    def __init__(self, codigo: str, detalle: str = ""):
        super().__init__(f"{codigo}: {detalle}")
        self.codigo = codigo
        self.detalle = detalle


# ------------------------------------------------------------------ primitivas
def canonico(valor) -> bytes:
    """§1: UTF-8 sin BOM ni espacios, claves ordenadas por bytes ASCII."""
    return json.dumps(valor, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False).encode("ascii")


def sha256_hex(datos: bytes) -> str:
    return hashlib.sha256(datos).hexdigest()


def hash_dominio(dominio: str, datos: bytes) -> bytes:
    """§3: H(ASCII("atlas-custodia-v2/<dominio>") || 0x00 || datos)."""
    return hashlib.sha256(b"atlas-custodia-v2/" + dominio.encode("ascii") + b"\x00" + datos).digest()


def hoja(parte: bytes) -> bytes:
    return hash_dominio("parte", parte)


def _nodo(a: bytes, b: bytes) -> bytes:
    return hash_dominio("nodo", a + b)


def raiz(hojas: Sequence[bytes]) -> bytes:
    """Pares consecutivos; el último nodo impar se promueve sin duplicarse."""
    if not hojas:
        raise ErrorCloudV2("FORMATO_INVALIDO", "árbol sin hojas")
    nivel = list(hojas)
    while len(nivel) > 1:
        nivel = [_nodo(nivel[i], nivel[i + 1]) if i + 1 < len(nivel) else nivel[i]
                 for i in range(0, len(nivel), 2)]
    return nivel[0]


def prueba_merkle(hojas: Sequence[bytes], indice: int) -> list[tuple[str, bytes]]:
    """Hermanos por nivel con su lado ('I' izquierdo / 'D' derecho); niveles sin hermano se omiten.

    El contrato no fija todavía la forma serializada de la prueba; ésta es sólo
    una representación de referencia para comprobar la regla de promoción.
    """
    nivel, pos, prueba = list(hojas), indice, []
    while len(nivel) > 1:
        hermano = pos ^ 1
        if hermano < len(nivel):
            prueba.append(("I" if hermano < pos else "D", nivel[hermano]))
        nivel = [_nodo(nivel[i], nivel[i + 1]) if i + 1 < len(nivel) else nivel[i]
                 for i in range(0, len(nivel), 2)]
        pos //= 2
    return prueba


def verificar_prueba_merkle(h: bytes, indice: int, total: int, prueba: Sequence[tuple[str, bytes]],
                            raiz_esperada: bytes) -> bool:
    """Recalcula la raíz con el índice y el total comprometidos; rechaza pruebas sobrantes o truncadas."""
    if not (0 <= indice < total):
        return False
    actual, pos, ancho, k = h, indice, total, 0
    while ancho > 1:
        hermano = pos ^ 1
        if hermano < ancho:
            if k >= len(prueba):
                return False
            lado, valor = prueba[k]
            k += 1
            if lado != ("I" if hermano < pos else "D"):
                return False
            actual = _nodo(valor, actual) if lado == "I" else _nodo(actual, valor)
        pos //= 2
        ancho = (ancho + 1) // 2
    return k == len(prueba) and actual == raiz_esperada


# --------------------------------------------------------------- construcción
@dataclass(frozen=True)
class GeneracionV2:
    cabecera: dict
    cabecera_bytes: bytes
    partes_bytes: tuple[bytes, ...]
    objetos: tuple[tuple[str, str], ...]
    huella: str

    @property
    def hojas(self) -> list[bytes]:
        return [hoja(p) for p in self.partes_bytes]


def _validar_identidades(empresa, generacion, anterior) -> None:
    if not isinstance(empresa, str) or not PATRON_EMPRESA.fullmatch(empresa):
        raise ErrorCloudV2("EMPRESA_INVALIDA", repr(empresa))
    if not isinstance(generacion, str) or not PATRON_GENERACION.fullmatch(generacion):
        raise ErrorCloudV2("GENERACION_INVALIDA", repr(generacion))
    if anterior is not None and (not isinstance(anterior, str) or not PATRON_GENERACION.fullmatch(anterior)
                                 or anterior == generacion):
        raise ErrorCloudV2("GENERACION_INVALIDA", f"anterior {anterior!r}")


def _validar_objeto(ruta, sha) -> None:
    if not isinstance(ruta, str) or len(ruta.encode("ascii", "replace")) > MAX_RUTA or not (
            ruta == RUTA_DESCRIPTOR or PATRON_RUTA.fullmatch(ruta)):
        raise ErrorCloudV2("RUTA_INVALIDA", repr(ruta)[:80])
    if not isinstance(sha, str) or not PATRON_SHA.fullmatch(sha):
        raise ErrorCloudV2("SHA_INVALIDO", repr(ruta)[:80])


def construir(empresa: str, generacion: str, anterior: str | None,
              objetos: Iterable[tuple[str, str]]) -> GeneracionV2:
    _validar_identidades(empresa, generacion, anterior)
    lista = sorted(objetos)
    if not lista:
        raise ErrorCloudV2("CONTEO_INCORRECTO", "inventario vacío")
    vistos = set()
    for ruta, sha in lista:
        _validar_objeto(ruta, sha)
        if ruta in vistos:
            raise ErrorCloudV2("IDENTIDAD_DUPLICADA", ruta)
        vistos.add(ruta)
    if RUTA_DESCRIPTOR not in vistos:
        raise ErrorCloudV2("DESCRIPTOR_AUSENTE", RUTA_DESCRIPTOR)
    partes = []
    for i in range(0, len(lista), OBJETOS_POR_PARTE):
        grupo = lista[i:i + OBJETOS_POR_PARTE]
        datos = canonico({"cantidad": len(grupo), "empresa_id": empresa, "generacion_id": generacion,
                          "indice": len(partes), "objetos": [{"ruta": r, "sha256": s} for r, s in grupo],
                          "version": VERSION})
        if len(datos) > MAX_BYTES_PARTE:
            raise ErrorCloudV2("PARTE_EXCEDIDA", f"{len(datos)} bytes")
        partes.append(datos)
    cabecera = {"anterior_id": anterior, "empresa_id": empresa, "generacion_id": generacion,
                "numero_objetos": len(lista), "numero_partes": len(partes),
                "raiz_partes": raiz([hoja(p) for p in partes]).hex(),
                "sha_descriptor_motor": dict(lista)[RUTA_DESCRIPTOR], "version": VERSION}
    cb = canonico(cabecera)
    return GeneracionV2(cabecera, cb, tuple(partes), tuple(lista), hash_dominio("cabecera", cb).hex())


# --------------------------------------------------------------- verificación
def _sin_duplicadas(pares):
    d = {}
    for k, v in pares:
        if k in d:
            raise ErrorCloudV2("FORMATO_INVALIDO", f"clave duplicada {k!r}")
        d[k] = v
    return d


def _cargar(datos: bytes, claves: tuple[str, ...], sujeto: str) -> dict:
    if not isinstance(datos, (bytes, bytearray)):
        raise ErrorCloudV2("FORMATO_INVALIDO", f"{sujeto}: no son bytes")
    try:
        valor = json.loads(bytes(datos).decode("ascii"), object_pairs_hook=_sin_duplicadas)
    except ValueError as exc:      # incluye UnicodeDecodeError; ErrorCloudV2 de claves duplicadas pasa
        raise ErrorCloudV2("FORMATO_INVALIDO", f"{sujeto}: {exc}") from None
    if not isinstance(valor, dict):
        raise ErrorCloudV2("FORMATO_INVALIDO", f"{sujeto}: no es objeto")
    version = valor.get("version")
    if type(version) is not int or version != VERSION:
        raise ErrorCloudV2("VERSION_INCOMPATIBLE", f"{sujeto}: versión {version!r}")
    if tuple(sorted(valor)) != claves:
        raise ErrorCloudV2("FORMATO_INVALIDO", f"{sujeto}: campos {sorted(valor)}")
    if canonico(valor) != bytes(datos):
        raise ErrorCloudV2("NO_CANONICO", sujeto)
    return valor


def _entero(valor, minimo: int) -> bool:
    return type(valor) is int and minimo <= valor <= MAX_ENTERO


def verificar(cabecera_bytes: bytes, partes_bytes: Sequence[bytes], empresa: str, *,
              huella_esperada: str | None = None, generacion_esperada: str | None = None) -> GeneracionV2:
    """Verificación completa de una generación v2: todas las partes, una sola vez, en orden.

    El lector fija ``(empresa, generacion_id, huella)``. Cualquier desvío lanza
    ``ErrorCloudV2``; nunca se devuelve un inventario parcial.
    """
    c = _cargar(cabecera_bytes, CLAVES_CABECERA, "cabecera")
    if c["empresa_id"] != empresa:
        raise ErrorCloudV2("EMPRESA_INCORRECTA", f"cabecera de {c['empresa_id']!r}")
    _validar_identidades(c["empresa_id"], c["generacion_id"], c["anterior_id"])
    if generacion_esperada is not None and c["generacion_id"] != generacion_esperada:
        raise ErrorCloudV2("GENERACION_INCORRECTA", c["generacion_id"])
    if not _entero(c["numero_objetos"], 1) or not _entero(c["numero_partes"], 1):
        raise ErrorCloudV2("CONTEO_INCORRECTO", "conteos de cabecera")
    for campo in ("raiz_partes", "sha_descriptor_motor"):
        if not isinstance(c[campo], str) or not PATRON_SHA.fullmatch(c[campo]):
            raise ErrorCloudV2("FORMATO_INVALIDO", campo)
    huella = hash_dominio("cabecera", bytes(cabecera_bytes)).hex()
    if huella_esperada is not None and huella != huella_esperada:
        raise ErrorCloudV2("HUELLA_INCORRECTA", huella)
    if c["numero_partes"] != -(-c["numero_objetos"] // OBJETOS_POR_PARTE):
        raise ErrorCloudV2("CONTEO_INCORRECTO", "numero_partes != ceil(numero_objetos/100)")
    if len(partes_bytes) < c["numero_partes"]:
        raise ErrorCloudV2("PARTE_AUSENTE", f"{len(partes_bytes)} de {c['numero_partes']}")
    if len(partes_bytes) > c["numero_partes"]:
        raise ErrorCloudV2("PARTE_SOBRANTE", f"{len(partes_bytes)} de {c['numero_partes']}")

    objetos: list[tuple[str, str]] = []
    for i, datos in enumerate(partes_bytes):
        if len(datos) > MAX_BYTES_PARTE:
            raise ErrorCloudV2("PARTE_EXCEDIDA", f"parte {i}")
        p = _cargar(datos, CLAVES_PARTE, f"parte {i}")
        if p["empresa_id"] != empresa:
            raise ErrorCloudV2("EMPRESA_INCORRECTA", f"parte {i} de {p['empresa_id']!r}")
        if p["generacion_id"] != c["generacion_id"]:
            raise ErrorCloudV2("GENERACION_INCORRECTA", f"parte {i}")
        if not _entero(p["indice"], 0) or p["indice"] != i:
            raise ErrorCloudV2("ORDEN_INCORRECTO", f"posición {i}, índice {p['indice']!r}")
        lista = p["objetos"]
        if not isinstance(lista, list) or not _entero(p["cantidad"], 1) or p["cantidad"] != len(lista) \
                or p["cantidad"] > OBJETOS_POR_PARTE \
                or (i < c["numero_partes"] - 1 and p["cantidad"] != OBJETOS_POR_PARTE):
            raise ErrorCloudV2("CONTEO_INCORRECTO", f"parte {i}")
        for o in lista:
            if not isinstance(o, dict) or tuple(sorted(o)) != CLAVES_OBJETO:
                raise ErrorCloudV2("FORMATO_INVALIDO", f"objeto en parte {i}")
            _validar_objeto(o["ruta"], o["sha256"])
            if objetos and o["ruta"] == objetos[-1][0]:
                raise ErrorCloudV2("IDENTIDAD_DUPLICADA", o["ruta"])
            if objetos and o["ruta"] < objetos[-1][0]:
                raise ErrorCloudV2("ORDEN_INCORRECTO", o["ruta"])
            objetos.append((o["ruta"], o["sha256"]))
    if len(objetos) != c["numero_objetos"]:
        raise ErrorCloudV2("CONTEO_INCORRECTO", f"{len(objetos)} objetos, cabecera {c['numero_objetos']}")
    descriptor = [s for r, s in objetos if r == RUTA_DESCRIPTOR]
    if len(descriptor) != 1:
        raise ErrorCloudV2("DESCRIPTOR_AUSENTE", RUTA_DESCRIPTOR)
    if descriptor[0] != c["sha_descriptor_motor"]:
        raise ErrorCloudV2("DESCRIPTOR_INCONSISTENTE", "sha del objeto != sha_descriptor_motor")
    if raiz([hoja(bytes(p)) for p in partes_bytes]).hex() != c["raiz_partes"]:
        raise ErrorCloudV2("RAIZ_INCORRECTA", "las partes no corresponden a raiz_partes")
    return GeneracionV2(c, bytes(cabecera_bytes), tuple(bytes(p) for p in partes_bytes), tuple(objetos), huella)
