"""Representación del descriptor Motor en la custodia de generaciones v1 (Cloud).

Conciliación **pura** entre ``descriptor_generacion`` (contrato Motor v1) y la
API de Cloud ``/api/motor/custodia/v1/generaciones`` (Atlas-Mobile-Cloud
``61c28726``, ``docs/custodia-generaciones-v1.md``). No hace HTTP, no adquiere
lease, no sube objetos, no prepara ni publica: sólo construye y verifica
representaciones en memoria.

El descriptor Cloud v1 es ``{version: 1, empresa_id, generacion_id,
objetos: [{ruta, sha256}]}`` y no transporta tipos, obligatoriedad,
referencias ni vacíos declarados. Para no perder esa semántica, el descriptor
Motor serializado viaja **como un objeto más** de la generación, en
``RUTA_DESCRIPTOR``; Cloud lo verifica por SHA-256 como a cualquier objeto.
Las demás entradas son las fuentes del descriptor Motor, con ``ruta`` igual a
su identidad lógica y ``sha256`` igual a su huella sin prefijo.

Lo que no pertenece al descriptor queda fuera de esta representación:
``lease_token`` y ``version_base`` son estado de custodia; ``PENDIENTE`` y
``PUBLICADA`` son respuestas del protocolo de publicación.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass

from atlas_core.descriptor_generacion import (
    EMPRESAS_LOCALES_NO_CANONICAS, DescriptorPreparado, ErrorDescriptor, Problema, leer_descriptor,
    serializar_descriptor,
)

VERSION_CUSTODIA = 1
VERSIONES_CUSTODIA_COMPATIBLES = frozenset({1})
# Límite de ``descriptorGeneracion`` en el Worker: 1 a 1000 objetos.
MAX_OBJETOS_CUSTODIA = 1000
# Fuera del espacio de identidades Motor (que empiezan por [a-z0-9]): no colisiona.
RUTA_DESCRIPTOR = "_atlas/descriptor_generacion.json"
_CLAVES = ("version", "empresa_id", "generacion_id", "objetos")
_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")
_PATRON_EMPRESA = re.compile(r"^[a-z][a-z0-9-]{1,38}[a-z0-9]$")


@dataclass(frozen=True)
class ProyeccionCustodia:
    """Lo que el llamador necesita para preparar la generación en Cloud.

    ``descriptor_cloud`` son los bytes que Cloud guarda (``JSON.stringify``) y
    ``descriptor_sha256`` el hash que Cloud debe devolver al preparar.
    ``objeto_descriptor`` son los bytes del descriptor Motor, que deben subirse
    como objeto de custodia (``PUT /api/motor/estado/objetos/<sha256>``).
    """
    descriptor_cloud: bytes
    descriptor_sha256: str
    anterior_id: str | None
    objeto_descriptor: bytes
    objeto_descriptor_sha256: str

    def descriptor(self) -> dict:
        """Valor del campo ``descriptor`` de ``POST .../generaciones/preparar``."""
        return json.loads(self.descriptor_cloud)


def _sha256(datos: bytes) -> str:
    return hashlib.sha256(datos).hexdigest()


def _bytes_cloud(empresa_id: str, generacion_id: str, objetos: list[tuple[str, str]]) -> bytes:
    # Igual que JSON.stringify del Worker: claves en este orden, sin espacios.
    # Rutas, empresa e id son ASCII, así que el orden y el escape coinciden con JS.
    cuerpo = {"version": VERSION_CUSTODIA, "empresa_id": empresa_id, "generacion_id": generacion_id,
              "objetos": [{"ruta": r, "sha256": s} for r, s in sorted(objetos)]}
    return json.dumps(cuerpo, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _validar_empresa_custodia(empresa_custodia) -> None:
    if not isinstance(empresa_custodia, str) or not _PATRON_EMPRESA.fullmatch(empresa_custodia) \
            or empresa_custodia in EMPRESAS_LOCALES_NO_CANONICAS:
        raise ErrorDescriptor([Problema("EMPRESA_INVALIDA", "custodia", repr(empresa_custodia))])


def _objetos_esperados(motor: DescriptorPreparado) -> dict[str, str]:
    return {f.identidad: f.huella.removeprefix("sha256:") for f in motor.fuentes}


def proyectar_para_custodia(descriptor: DescriptorPreparado, empresa_custodia: str) -> ProyeccionCustodia:
    """Representa el descriptor Motor en el contrato Cloud v1, sin enviarlo.

    ``empresa_custodia`` es la empresa autenticada por el token Motor
    (``ContextoEmpresa.cloud_id``); no se traduce ni se infiere.
    """
    _validar_empresa_custodia(empresa_custodia)
    objeto = serializar_descriptor(descriptor)
    motor = leer_descriptor(objeto)  # revalidación completa: nada sin verificar sale de aquí
    if motor.empresa_id != empresa_custodia:
        raise ErrorDescriptor([Problema("EMPRESA_INCORRECTA", "custodia",
                                        f"descriptor de {motor.empresa_id!r}, custodia de {empresa_custodia!r}")])
    objetos = list(_objetos_esperados(motor).items())
    if len(objetos) + 1 > MAX_OBJETOS_CUSTODIA:
        raise ErrorDescriptor([Problema("LIMITE_CUSTODIA", "custodia",
                                        f"{len(objetos)} fuentes + descriptor > {MAX_OBJETOS_CUSTODIA} objetos")])
    sha_objeto = _sha256(objeto)
    objetos.append((RUTA_DESCRIPTOR, sha_objeto))
    datos = _bytes_cloud(empresa_custodia, motor.generacion.generacion_id, objetos)
    return ProyeccionCustodia(descriptor_cloud=datos, descriptor_sha256=_sha256(datos),
                              anterior_id=motor.generacion.previa_id, objeto_descriptor=objeto,
                              objeto_descriptor_sha256=sha_objeto)


def verificar_generacion_custodia(descriptor_cloud: Mapping, descriptor_sha256: str, datos_descriptor: bytes,
                                  empresa_custodia: str) -> DescriptorPreparado:
    """Verifica un descriptor devuelto por Cloud contra el descriptor Motor.

    ``descriptor_cloud`` y ``descriptor_sha256`` son los campos de la respuesta
    de ``GET .../generaciones/actual``. ``datos_descriptor`` son los bytes del
    objeto ``RUTA_DESCRIPTOR``, ya descargados por el llamador. Exige
    coincidencia exacta: ninguna fuente de más, de menos ni con otra huella.
    Devuelve el descriptor Motor, que sigue en ``PENDIENTE_PROTOCOLO_OFICIAL``:
    el estado de publicación no se incorpora.
    """
    _validar_empresa_custodia(empresa_custodia)
    if not isinstance(descriptor_cloud, Mapping):
        raise ErrorDescriptor([Problema("FORMATO_INVALIDO", "custodia", "descriptor Cloud no es un objeto")])
    version = descriptor_cloud.get("version")
    if isinstance(version, bool) or version not in VERSIONES_CUSTODIA_COMPATIBLES:
        raise ErrorDescriptor([Problema("VERSION_INCOMPATIBLE", "custodia",
                                        f"versión {version!r}; admitidas {sorted(VERSIONES_CUSTODIA_COMPATIBLES)}")])
    if sorted(descriptor_cloud) != sorted(_CLAVES):
        raise ErrorDescriptor([Problema("FORMATO_INVALIDO", "custodia", f"campos {sorted(descriptor_cloud)}")])
    if descriptor_cloud["empresa_id"] != empresa_custodia:
        raise ErrorDescriptor([Problema("EMPRESA_INCORRECTA", "custodia",
                                        f"descriptor de {descriptor_cloud['empresa_id']!r}")])
    recibidos: dict[str, str] = {}
    problemas: list[Problema] = []
    objetos = descriptor_cloud["objetos"]
    if not isinstance(objetos, list) or not objetos:
        raise ErrorDescriptor([Problema("FORMATO_INVALIDO", "custodia", "objetos debe ser una lista no vacía")])
    for o in objetos:
        if not isinstance(o, Mapping) or sorted(o) != ["ruta", "sha256"] or not isinstance(o["ruta"], str):
            raise ErrorDescriptor([Problema("FORMATO_INVALIDO", "custodia", f"objeto {o!r}"[:120])])
        if not isinstance(o["sha256"], str) or not _SHA256_HEX.fullmatch(o["sha256"]):
            problemas.append(Problema("CONTENIDO_NO_VERIFICABLE", o["ruta"], "sha256 no verificable"))
        elif o["ruta"] in recibidos:
            problemas.append(Problema("IDENTIDAD_DUPLICADA", o["ruta"], "ruta repetida"))
        else:
            recibidos[o["ruta"]] = o["sha256"]
    if problemas:
        raise ErrorDescriptor(problemas)

    sha_objeto = recibidos.pop(RUTA_DESCRIPTOR, None)
    if sha_objeto is None:
        raise ErrorDescriptor([Problema("FUENTE_OBLIGATORIA_AUSENTE", RUTA_DESCRIPTOR,
                                        "la generación no inventaría el descriptor Motor")])
    if not isinstance(datos_descriptor, (bytes, bytearray)) or _sha256(bytes(datos_descriptor)) != sha_objeto:
        raise ErrorDescriptor([Problema("DESCRIPTOR_ALTERADO", RUTA_DESCRIPTOR,
                                        "bytes del descriptor Motor distintos de su sha256 en custodia")])
    motor = leer_descriptor(bytes(datos_descriptor))
    if motor.empresa_id != empresa_custodia:
        raise ErrorDescriptor([Problema("EMPRESA_INCORRECTA", "descriptor", f"descriptor de {motor.empresa_id!r}")])
    if motor.generacion.generacion_id != descriptor_cloud["generacion_id"]:
        raise ErrorDescriptor([Problema("GENERACION_INVALIDA", "custodia",
                                        f"Cloud {descriptor_cloud['generacion_id']!r}, "
                                        f"Motor {motor.generacion.generacion_id!r}")])

    esperados = _objetos_esperados(motor)
    referidas = {r.identidad for f in motor.fuentes for r in f.referencias}
    for ruta in sorted(esperados.keys() - recibidos.keys()):
        problemas.append(Problema("INVENTARIO_INCOMPLETO", ruta, "fuente del descriptor ausente en custodia"))
    for ruta in sorted(recibidos.keys() - esperados.keys()):
        problemas.append(Problema("INVENTARIO_INCONSISTENTE", ruta, "objeto de custodia no inventariado"))
    for ruta in sorted(esperados.keys() & recibidos.keys()):
        if esperados[ruta] != recibidos[ruta]:
            codigo = "REFERENCIA_INCONSISTENTE" if ruta in referidas else "INVENTARIO_INCONSISTENTE"
            problemas.append(Problema(codigo, ruta, "sha256 en custodia distinto de la huella del descriptor"))
    if problemas:
        raise ErrorDescriptor(problemas)
    canonico = _bytes_cloud(empresa_custodia, motor.generacion.generacion_id,
                            list(esperados.items()) + [(RUTA_DESCRIPTOR, sha_objeto)])
    if descriptor_sha256 != _sha256(canonico):
        raise ErrorDescriptor([Problema("DESCRIPTOR_ALTERADO", "custodia",
                                        "descriptor_sha256 no corresponde a la forma canónica Cloud")])
    return motor
