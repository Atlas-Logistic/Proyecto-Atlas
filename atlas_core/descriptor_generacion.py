"""Descriptor preparado de una generación operacional (contrato v1).

Constructor **puro y determinista**: recibe del llamador un inventario
explícito de fuentes y objetos ya identificados por huella y devuelve un
descriptor serializable, versionado y verificable. No lee archivos
operacionales, no consulta Cloud ni custodia, no escribe nada y no publica.

Tres conceptos separados (ver ``docs/DESCRIPTOR_GENERACION.md``):

* **Descriptor preparado** (este módulo): inventario completo y verificado
  de lo que *debería* formar una generación. Su ``completitud`` es siempre
  ``PENDIENTE_PROTOCOLO_OFICIAL``; nunca puede declararse completo.
* **Generación publicada**: la transición única ``PENDIENTE -> COMPLETA``
  que apunta a un descriptor; pertenece al protocolo oficial de publicación.
* **Estado de custodia**: versión, lease, objetos durables y retención;
  pertenece a la custodia. Ninguno de sus campos entra en el descriptor.

Una fuente inexistente nunca equivale a una colección vacía: cada tipo debe
declararse con su número exacto de objetos, y el vacío (``0``) sólo se admite
como declaración explícita en los tipos donde es legítimo.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

ESQUEMA = "atlas.descriptor_generacion"
VERSION_CONTRATO = 1
VERSIONES_COMPATIBLES = frozenset({1})
CLASE = "DESCRIPTOR_PREPARADO"
# El descriptor no puede afirmar su completitud: sólo el protocolo oficial de
# publicación la confirma, fuera de este documento.
COMPLETITUD = "PENDIENTE_PROTOCOLO_OFICIAL"
ALGORITMO_HUELLA = "sha256"
HUELLA_VACIA = "sha256:" + hashlib.sha256(b"").hexdigest()

RELACION_PROPIA = "PROPIA"
RELACION_GLOBAL = "COMPARTIDA_GLOBAL"


@dataclass(frozen=True)
class ReglaTipo:
    """Cardinalidad de un tipo de fuente dentro de una generación."""
    minimo: int
    maximo: int | None
    obligatorio: bool
    admite_global: bool = False


# Inventario de tipos v1. Los tipos de archivo único con estado propio
# (dataset, ledger, bandeja, agrupaciones, registro de investigación...) son
# obligatorios: su archivo vacío sigue siendo un objeto con huella.
TIPOS: Mapping[str, ReglaTipo] = {
    "IDENTIDAD_EMPRESA": ReglaTipo(1, 1, True),
    "DATASET_OPERACIONAL": ReglaTipo(1, 1, True),
    "LEDGER_DECISIONES": ReglaTipo(1, 1, True),
    "DECISIONES_HUMANAS": ReglaTipo(1, 1, True),
    "BANDEJA_REVISION": ReglaTipo(1, 1, True),
    "AGRUPACIONES_CONFIRMADAS": ReglaTipo(1, 1, True),
    "REGISTRO_INVESTIGACION": ReglaTipo(1, 1, True),
    "CUARENTENA": ReglaTipo(0, None, False),
    "EVIDENCIA_DOCUMENTAL": ReglaTipo(0, None, False),
    "CATALOGO": ReglaTipo(1, None, True, admite_global=True),
    "ASIGNACIONES": ReglaTipo(1, None, True),
}

# ``empresa_id`` es la identidad canónica de custodia: ``ContextoEmpresa.cloud_id``,
# la misma que Cloud deduce del token Motor. Los identificadores locales de MBT
# no lo son y se rechazan en vez de traducirse.
EMPRESAS_LOCALES_NO_CANONICAS = frozenset({"mbt", "oficina"})
# MBT opera sin ``catalogos_privados/empresa_identidad.json``: en su custodia
# una marca indica empresa ajena (``aislamiento_empresas.verificar_manifiesto_empresa``).
# Su ausencia se declara explícitamente con 0. Debe coincidir con
# ``aislamiento_empresas.CLOUD_MBT`` (lo verifica una prueba).
EMPRESAS_SIN_MARCA = frozenset({"empresa-prueba-javier"})
_REGLA_SIN_MARCA = ReglaTipo(0, 0, False)


def regla_tipo(tipo: str, empresa_id: str) -> ReglaTipo | None:
    """Regla del tipo para esa empresa; ``None`` si el tipo es desconocido."""
    if tipo == "IDENTIDAD_EMPRESA" and empresa_id in EMPRESAS_SIN_MARCA:
        return _REGLA_SIN_MARCA
    return TIPOS.get(tipo)

# Campos que pertenecen a la publicación o a la custodia: no pueden aparecer
# en el descriptor ni en los metadatos de sus fuentes.
CAMPOS_PROTOCOLO = frozenset({
    "estado", "estado_publicacion", "completa", "completo", "completitud", "publicada", "publicado",
    "publicacion", "custodia", "version_custodia", "marca_custodia", "lease", "lease_token", "confirmada",
    "confirmado", "confirmacion", "confirmado_en", "publicado_en",
})
_FRAGMENTOS_CREDENCIAL = ("token", "secret", "secreto", "password", "contrasena", "contraseña", "clave",
                          "credencial", "authorization", "api_key", "apikey", "cookie", "bearer")

_PATRON_EMPRESA = re.compile(r"^[a-z][a-z0-9-]{1,38}[a-z0-9]$")
_PATRON_IDENTIDAD = re.compile(r"^[a-z0-9][a-z0-9._-]*(/[a-z0-9][a-z0-9._-]*)*$")
_PATRON_GENERACION = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
_PATRON_CLAVE_META = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_PATRON_HUELLA = re.compile(r"^sha256:[0-9a-f]{64}$")
_PATRON_RUTA_ABSOLUTA = re.compile(r"^(?:[A-Za-z]:[\\/]|[\\/]|file:|[a-z][a-z0-9+.-]*://)")
_MAX_IDENTIDAD = 256
_MAX_VALOR_META = 512

CODIGOS = frozenset({
    "FORMATO_INVALIDO", "VERSION_INCOMPATIBLE", "EMPRESA_AUSENTE", "EMPRESA_INVALIDA", "EMPRESA_INCORRECTA",
    "GENERACION_INVALIDA", "TIPO_DESCONOCIDO", "IDENTIDAD_INVALIDA", "IDENTIDAD_DUPLICADA",
    "IDENTIDAD_CONTRADICTORIA", "OBJETO_SIN_HUELLA", "CONTENIDO_NO_VERIFICABLE", "CAMPO_PROHIBIDO",
    "OBLIGATORIEDAD_INCONSISTENTE", "FUENTE_OBLIGATORIA_AUSENTE", "INVENTARIO_INCOMPLETO",
    "INVENTARIO_INCONSISTENTE", "REFERENCIA_INCONSISTENTE", "REFERENCIA_ENTRE_EMPRESAS",
    "DESCRIPTOR_AUTODECLARADO", "DESCRIPTOR_ALTERADO",
})


@dataclass(frozen=True, order=True)
class Problema:
    codigo: str
    sujeto: str
    detalle: str


class ErrorDescriptor(ValueError):
    """Inventario o descriptor rechazado; ``problemas`` en orden determinista."""

    def __init__(self, problemas: Iterable[Problema]):
        self.problemas = tuple(sorted(set(problemas)))
        self.codigos = frozenset(p.codigo for p in self.problemas)
        primero = self.problemas[0] if self.problemas else Problema("FORMATO_INVALIDO", "", "sin detalle")
        self.codigo = primero.codigo
        super().__init__("; ".join(f"{p.codigo}[{p.sujeto}]: {p.detalle}" for p in self.problemas[:10]))


# ------------------------------------------------------------------ entrada
@dataclass(frozen=True)
class Referencia:
    """Dependencia de un objeto sobre otro del mismo inventario, por huella."""
    identidad: str
    huella: str
    empresa_id: str | None


@dataclass(frozen=True)
class ObjetoFuente:
    identidad: str
    tipo: str
    huella: str | None
    empresa_id: str | None
    obligatorio: bool
    tamano: int | None = None
    metadatos: Mapping[str, Any] = field(default_factory=dict)
    referencias: tuple[Referencia, ...] = ()
    relacion: str = RELACION_PROPIA


@dataclass(frozen=True)
class GeneracionSolicitada:
    """Identidad propuesta; la asignación definitiva requiere conciliación con custodia."""
    generacion_id: str
    secuencia: int
    previa_id: str | None = None


@dataclass(frozen=True)
class Inventario:
    version_contrato: int
    empresa_id: str | None
    generacion: GeneracionSolicitada
    # Número exacto de objetos por tipo según la enumeración oficial del llamador.
    declaracion: Mapping[str, int]
    objetos: tuple[ObjetoFuente, ...]


# ------------------------------------------------------------------- salida
@dataclass(frozen=True)
class DescriptorPreparado:
    empresa_id: str
    generacion: GeneracionSolicitada
    declaracion: tuple[tuple[str, int], ...]
    fuentes: tuple[ObjetoFuente, ...]
    huella_descriptor: str
    version_contrato: int = VERSION_CONTRATO

    @property
    def completitud(self) -> str:
        return COMPLETITUD

    def fuente(self, identidad: str) -> ObjetoFuente:
        for objeto in self.fuentes:
            if objeto.identidad == identidad:
                return objeto
        raise KeyError(identidad)

    def como_dict(self) -> dict:
        cuerpo = _cuerpo(self.empresa_id, self.generacion, self.declaracion, self.fuentes)
        cuerpo["huella_descriptor"] = self.huella_descriptor
        return cuerpo


# ---------------------------------------------------------------- canónico
def _canonico(valor: Any) -> bytes:
    return json.dumps(valor, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def _huella(datos: bytes) -> str:
    return "sha256:" + hashlib.sha256(datos).hexdigest()


def _fuente_dict(o: ObjetoFuente) -> dict:
    return {
        "identidad": o.identidad, "tipo": o.tipo, "huella": o.huella, "tamano": o.tamano,
        "empresa_id": o.empresa_id, "relacion": o.relacion, "obligatorio": o.obligatorio,
        "metadatos": dict(sorted(o.metadatos.items())),
        "referencias": [{"identidad": r.identidad, "huella": r.huella, "empresa_id": r.empresa_id}
                        for r in o.referencias],
    }


def _cuerpo(empresa_id, generacion, declaracion, fuentes) -> dict:
    tamanos = [o.tamano for o in fuentes if o.tamano is not None]
    return {
        "esquema": ESQUEMA, "version_contrato": VERSION_CONTRATO, "clase": CLASE,
        "completitud": COMPLETITUD, "algoritmo_huella": ALGORITMO_HUELLA, "empresa_id": empresa_id,
        "generacion": {"id": generacion.generacion_id, "secuencia": generacion.secuencia,
                       "previa_id": generacion.previa_id},
        "declaracion": dict(declaracion),
        "fuentes": [_fuente_dict(o) for o in fuentes],
        "resumen": {"objetos": len(fuentes), "obligatorios": sum(o.obligatorio for o in fuentes),
                    "bytes_declarados": sum(tamanos), "tamanos_desconocidos": len(fuentes) - len(tamanos)},
    }


# -------------------------------------------------------------- validación
def _es_entero(valor) -> bool:
    return isinstance(valor, int) and not isinstance(valor, bool)


def _empresa_valida(empresa_id) -> bool:
    return isinstance(empresa_id, str) and bool(_PATRON_EMPRESA.fullmatch(empresa_id))


def _validar_huella(huella, sujeto: str, problemas: list) -> bool:
    if huella is None or (isinstance(huella, str) and not huella.strip()):
        problemas.append(Problema("OBJETO_SIN_HUELLA", sujeto, "sin huella de contenido"))
        return False
    if not isinstance(huella, str) or not _PATRON_HUELLA.fullmatch(huella):
        problemas.append(Problema("CONTENIDO_NO_VERIFICABLE", sujeto, f"huella no verificable {huella!r}"))
        return False
    return True


def _clave_prohibida(clave: str) -> str | None:
    bajo = clave.lower()
    if bajo in CAMPOS_PROTOCOLO:
        return "campo reservado al protocolo de publicación o custodia"
    if any(f in bajo for f in _FRAGMENTOS_CREDENCIAL):
        return "posible credencial"
    return None


def _validar_metadatos(o: ObjetoFuente, problemas: list) -> None:
    if not isinstance(o.metadatos, Mapping):
        problemas.append(Problema("FORMATO_INVALIDO", o.identidad, "metadatos debe ser un mapa"))
        return
    for clave, valor in o.metadatos.items():
        if not isinstance(clave, str) or not _PATRON_CLAVE_META.fullmatch(clave):
            problemas.append(Problema("FORMATO_INVALIDO", o.identidad, f"clave de metadato {clave!r}"))
            continue
        motivo = _clave_prohibida(clave)
        if motivo:
            problemas.append(Problema("CAMPO_PROHIBIDO", o.identidad, f"{clave}: {motivo}"))
            continue
        if valor is not None and not isinstance(valor, (str, bool, int)):
            problemas.append(Problema("FORMATO_INVALIDO", o.identidad, f"{clave}: valor no escalar"))
        elif isinstance(valor, str):
            if len(valor) > _MAX_VALOR_META:
                problemas.append(Problema("FORMATO_INVALIDO", o.identidad, f"{clave}: valor demasiado largo"))
            elif _PATRON_RUTA_ABSOLUTA.match(valor.strip()):
                problemas.append(Problema("CAMPO_PROHIBIDO", o.identidad, f"{clave}: ruta absoluta o URL"))


def _validar_objeto(o, empresa_id: str, problemas: list) -> bool:
    """Valida un objeto aislado. Devuelve False si no puede indexarse por identidad."""
    if not isinstance(o, ObjetoFuente):
        problemas.append(Problema("FORMATO_INVALIDO", "", f"objeto de tipo {type(o).__name__}"))
        return False
    ident = o.identidad
    if not isinstance(ident, str) or len(ident) > _MAX_IDENTIDAD or not _PATRON_IDENTIDAD.fullmatch(ident):
        problemas.append(Problema("IDENTIDAD_INVALIDA", str(ident)[:80],
                                  "identidad lógica: minúsculas, segmentos con '/', sin rutas locales"))
        return False
    regla = regla_tipo(o.tipo, empresa_id) if isinstance(o.tipo, str) else None
    if regla is None:
        problemas.append(Problema("TIPO_DESCONOCIDO", ident, f"tipo {o.tipo!r}"))
    elif regla is _REGLA_SIN_MARCA:
        problemas.append(Problema("EMPRESA_INCORRECTA", ident,
                                  "esta empresa opera sin marca; una marca indica custodia ajena"))
    _validar_huella(o.huella, ident, problemas)
    if o.tamano is not None and (not _es_entero(o.tamano) or o.tamano < 0):
        problemas.append(Problema("CONTENIDO_NO_VERIFICABLE", ident, f"tamaño {o.tamano!r}"))
    elif o.tamano not in (None, 0) and o.huella == HUELLA_VACIA:
        problemas.append(Problema("CONTENIDO_NO_VERIFICABLE", ident, "huella de contenido vacío con tamaño > 0"))
    elif o.tamano == 0 and isinstance(o.huella, str) and _PATRON_HUELLA.fullmatch(o.huella) and o.huella != HUELLA_VACIA:
        problemas.append(Problema("CONTENIDO_NO_VERIFICABLE", ident, "tamaño 0 con huella de contenido no vacío"))
    if not isinstance(o.obligatorio, bool):
        problemas.append(Problema("FORMATO_INVALIDO", ident, "obligatorio debe ser booleano"))
    elif regla is not None and regla.obligatorio and not o.obligatorio:
        problemas.append(Problema("OBLIGATORIEDAD_INCONSISTENTE", ident, f"{o.tipo} es obligatorio"))
    # Relación con la empresa.
    if o.relacion == RELACION_PROPIA:
        if o.empresa_id is None:
            problemas.append(Problema("EMPRESA_AUSENTE", ident, "objeto propio sin empresa"))
        elif o.empresa_id != empresa_id:
            problemas.append(Problema("EMPRESA_INCORRECTA", ident, f"pertenece a {o.empresa_id!r}"))
    elif o.relacion == RELACION_GLOBAL:
        if regla is not None and not regla.admite_global:
            problemas.append(Problema("EMPRESA_INCORRECTA", ident, f"{o.tipo} no admite fuentes globales"))
        if o.empresa_id is not None:
            problemas.append(Problema("EMPRESA_INCORRECTA", ident, "fuente global con empresa asignada"))
    else:
        problemas.append(Problema("FORMATO_INVALIDO", ident, f"relación {o.relacion!r}"))
    _validar_metadatos(o, problemas)
    if not isinstance(o.referencias, tuple) or not all(isinstance(r, Referencia) for r in o.referencias):
        problemas.append(Problema("FORMATO_INVALIDO", ident, "referencias debe ser tupla de Referencia"))
    return True


def _validar_referencias(o: ObjetoFuente, indice: Mapping[str, ObjetoFuente], empresa_id: str,
                         problemas: list) -> None:
    vistas: dict[str, str] = {}
    for ref in o.referencias:
        sujeto = f"{o.identidad}->{ref.identidad}"
        if ref.empresa_id != empresa_id:
            problemas.append(Problema("REFERENCIA_ENTRE_EMPRESAS", sujeto, f"empresa {ref.empresa_id!r}"))
            continue
        if not _validar_huella(ref.huella, sujeto, problemas):
            continue
        if ref.identidad == o.identidad:
            problemas.append(Problema("REFERENCIA_INCONSISTENTE", sujeto, "autorreferencia"))
            continue
        if ref.identidad in vistas and vistas[ref.identidad] != ref.huella:
            problemas.append(Problema("REFERENCIA_INCONSISTENTE", sujeto, "dos huellas para la misma referencia"))
            continue
        vistas[ref.identidad] = ref.huella
        destino = indice.get(ref.identidad)
        if destino is None:
            problemas.append(Problema("REFERENCIA_INCONSISTENTE", sujeto, "objeto referido fuera del inventario"))
        elif destino.relacion == RELACION_PROPIA and destino.empresa_id != empresa_id:
            problemas.append(Problema("REFERENCIA_ENTRE_EMPRESAS", sujeto, "objeto referido de otra empresa"))
        elif destino.huella != ref.huella:
            problemas.append(Problema("REFERENCIA_INCONSISTENTE", sujeto, "huella referida distinta de la inventariada"))
        elif o.obligatorio and not destino.obligatorio:
            problemas.append(Problema("OBLIGATORIEDAD_INCONSISTENTE", sujeto,
                                      "fuente obligatoria depende de un objeto opcional"))


def _validar_generacion(g, problemas: list) -> None:
    if not isinstance(g, GeneracionSolicitada):
        problemas.append(Problema("GENERACION_INVALIDA", "", "generación ausente"))
        return
    if not isinstance(g.generacion_id, str) or not _PATRON_GENERACION.fullmatch(g.generacion_id):
        problemas.append(Problema("GENERACION_INVALIDA", str(g.generacion_id)[:80], "identificador de generación"))
    if not _es_entero(g.secuencia) or g.secuencia < 1:
        problemas.append(Problema("GENERACION_INVALIDA", str(g.generacion_id)[:80], f"secuencia {g.secuencia!r}"))
    if g.previa_id is not None:
        if not isinstance(g.previa_id, str) or not _PATRON_GENERACION.fullmatch(g.previa_id):
            problemas.append(Problema("GENERACION_INVALIDA", str(g.previa_id)[:80], "generación previa"))
        elif g.previa_id == g.generacion_id:
            problemas.append(Problema("GENERACION_INVALIDA", g.generacion_id, "generación previa igual a la actual"))
        if _es_entero(g.secuencia) and g.secuencia == 1:
            problemas.append(Problema("GENERACION_INVALIDA", str(g.generacion_id)[:80],
                                      "secuencia 1 no puede tener generación previa"))
    elif _es_entero(g.secuencia) and g.secuencia > 1:
        problemas.append(Problema("GENERACION_INVALIDA", str(g.generacion_id)[:80],
                                  "secuencia > 1 exige generación previa"))


def _validar_declaracion(declaracion, conteo: Mapping[str, int], empresa_id: str, problemas: list) -> None:
    if not isinstance(declaracion, Mapping):
        problemas.append(Problema("INVENTARIO_INCOMPLETO", "", "sin declaración de tipos"))
        return
    for tipo in declaracion:
        if tipo not in TIPOS:
            problemas.append(Problema("TIPO_DESCONOCIDO", str(tipo), "tipo declarado desconocido"))
    for tipo in TIPOS:
        regla = regla_tipo(tipo, empresa_id)
        presentes = conteo.get(tipo, 0)
        if tipo not in declaracion:
            codigo = "FUENTE_OBLIGATORIA_AUSENTE" if regla.obligatorio else "INVENTARIO_INCOMPLETO"
            problemas.append(Problema(codigo, tipo, "tipo no declarado; la ausencia no equivale a vacío"))
            continue
        declarado = declaracion[tipo]
        if not _es_entero(declarado) or declarado < 0:
            problemas.append(Problema("INVENTARIO_INCOMPLETO", tipo, f"declaración {declarado!r}"))
            continue
        if declarado < regla.minimo or (regla.obligatorio and declarado == 0):
            problemas.append(Problema("FUENTE_OBLIGATORIA_AUSENTE", tipo, f"declarados {declarado}, mínimo {regla.minimo}"))
        elif regla.maximo is not None and declarado > regla.maximo:
            problemas.append(Problema("INVENTARIO_INCONSISTENTE", tipo, f"declarados {declarado}, máximo {regla.maximo}"))
        if presentes < declarado:
            codigo = "FUENTE_OBLIGATORIA_AUSENTE" if regla.obligatorio and presentes < regla.minimo else "INVENTARIO_INCOMPLETO"
            problemas.append(Problema(codigo, tipo, f"declarados {declarado}, presentes {presentes}"))
        elif presentes > declarado:
            problemas.append(Problema("INVENTARIO_INCONSISTENTE", tipo, f"declarados {declarado}, presentes {presentes}"))


# ------------------------------------------------------------- API pública
def construir_descriptor(inventario: Inventario) -> DescriptorPreparado:
    """Valida el inventario completo y devuelve el descriptor preparado.

    Rechaza con ``ErrorDescriptor`` cualquier problema; nunca devuelve un
    descriptor parcial. El orden de entrada de objetos, referencias,
    metadatos y declaración no altera el resultado.
    """
    problemas: list[Problema] = []
    if not isinstance(inventario, Inventario):
        raise ErrorDescriptor([Problema("FORMATO_INVALIDO", "", "se esperaba Inventario")])
    if inventario.version_contrato not in VERSIONES_COMPATIBLES or not _es_entero(inventario.version_contrato):
        raise ErrorDescriptor([Problema("VERSION_INCOMPATIBLE", "inventario",
                                        f"versión {inventario.version_contrato!r}; admitidas {sorted(VERSIONES_COMPATIBLES)}")])
    empresa_id = inventario.empresa_id
    if empresa_id is None or (isinstance(empresa_id, str) and not empresa_id.strip()):
        raise ErrorDescriptor([Problema("EMPRESA_AUSENTE", "inventario", "empresa no indicada")])
    if not _empresa_valida(empresa_id):
        raise ErrorDescriptor([Problema("EMPRESA_INVALIDA", "inventario", repr(empresa_id))])
    if empresa_id in EMPRESAS_LOCALES_NO_CANONICAS:
        raise ErrorDescriptor([Problema("EMPRESA_INVALIDA", "inventario",
                                        f"{empresa_id!r} es local; usar la identidad de custodia (cloud_id)")])
    _validar_generacion(inventario.generacion, problemas)
    if not isinstance(inventario.objetos, (tuple, list)):
        raise ErrorDescriptor([Problema("FORMATO_INVALIDO", "inventario", "objetos debe ser una secuencia")])

    indice: dict[str, ObjetoFuente] = {}
    conteo: dict[str, int] = {}
    for o in inventario.objetos:
        if not _validar_objeto(o, empresa_id, problemas):
            continue
        previo = indice.get(o.identidad)
        if previo is not None:
            codigo = "IDENTIDAD_DUPLICADA" if previo == o else "IDENTIDAD_CONTRADICTORIA"
            problemas.append(Problema(codigo, o.identidad, "identidad repetida en el inventario"))
            continue
        indice[o.identidad] = o
        if isinstance(o.tipo, str) and o.tipo in TIPOS:
            conteo[o.tipo] = conteo.get(o.tipo, 0) + 1
    for o in indice.values():
        if isinstance(o.referencias, tuple):
            _validar_referencias(o, indice, empresa_id, problemas)
    _validar_declaracion(inventario.declaracion, conteo, empresa_id, problemas)
    if problemas:
        raise ErrorDescriptor(problemas)

    fuentes = tuple(
        ObjetoFuente(
            identidad=o.identidad, tipo=o.tipo, huella=o.huella, empresa_id=o.empresa_id,
            obligatorio=o.obligatorio, tamano=o.tamano, metadatos=dict(sorted(o.metadatos.items())),
            referencias=tuple(sorted(set(o.referencias), key=lambda r: (r.identidad, r.huella))),
            relacion=o.relacion)
        for o in sorted(indice.values(), key=lambda x: x.identidad))
    declaracion = tuple(sorted((t, int(n)) for t, n in inventario.declaracion.items()))
    cuerpo = _cuerpo(empresa_id, inventario.generacion, declaracion, fuentes)
    return DescriptorPreparado(empresa_id=empresa_id, generacion=inventario.generacion,
                               declaracion=declaracion, fuentes=fuentes,
                               huella_descriptor=_huella(_canonico(cuerpo)))


def serializar_descriptor(descriptor: DescriptorPreparado) -> bytes:
    """JSON canónico UTF-8 (claves ordenadas, sin espacios). Mismo descriptor -> mismos bytes."""
    return _canonico(descriptor.como_dict())


def leer_descriptor(datos: bytes) -> DescriptorPreparado:
    """Lee y **revalida por completo** un descriptor serializado.

    Rechaza esquemas o versiones no admitidas, cualquier pretensión de
    completitud o campo de publicación/custodia, y contenido alterado.
    """
    try:
        bruto = json.loads(datos.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, AttributeError) as exc:
        raise ErrorDescriptor([Problema("FORMATO_INVALIDO", "descriptor", f"JSON ilegible: {exc}")]) from None
    if not isinstance(bruto, dict):
        raise ErrorDescriptor([Problema("FORMATO_INVALIDO", "descriptor", "se esperaba un objeto JSON")])
    if bruto.get("esquema") != ESQUEMA:
        raise ErrorDescriptor([Problema("FORMATO_INVALIDO", "descriptor", f"esquema {bruto.get('esquema')!r}")])
    version = bruto.get("version_contrato")
    if not _es_entero(version) or version not in VERSIONES_COMPATIBLES:
        raise ErrorDescriptor([Problema("VERSION_INCOMPATIBLE", "descriptor",
                                        f"versión {version!r}; admitidas {sorted(VERSIONES_COMPATIBLES)}")])
    reservados = sorted(k for k in bruto if k.lower() in CAMPOS_PROTOCOLO and k != "completitud")
    if bruto.get("clase") != CLASE or bruto.get("completitud") != COMPLETITUD or reservados:
        raise ErrorDescriptor([Problema("DESCRIPTOR_AUTODECLARADO", "descriptor",
                                        "sólo el protocolo oficial de publicación confirma completitud "
                                        f"(clase={bruto.get('clase')!r}, completitud={bruto.get('completitud')!r}, "
                                        f"campos={reservados})")])
    esperadas = {"esquema", "version_contrato", "clase", "completitud", "algoritmo_huella", "empresa_id",
                 "generacion", "declaracion", "fuentes", "resumen", "huella_descriptor"}
    if set(bruto) != esperadas or bruto.get("algoritmo_huella") != ALGORITMO_HUELLA:
        raise ErrorDescriptor([Problema("FORMATO_INVALIDO", "descriptor",
                                        f"campos {sorted(set(bruto) ^ esperadas)}")])
    try:
        g = bruto["generacion"]
        inventario = Inventario(
            version_contrato=version, empresa_id=bruto["empresa_id"],
            generacion=GeneracionSolicitada(g["id"], g["secuencia"], g["previa_id"]),
            declaracion=dict(bruto["declaracion"]),
            objetos=tuple(
                ObjetoFuente(
                    identidad=f["identidad"], tipo=f["tipo"], huella=f["huella"], empresa_id=f["empresa_id"],
                    obligatorio=f["obligatorio"], tamano=f["tamano"], metadatos=dict(f["metadatos"]),
                    referencias=tuple(Referencia(r["identidad"], r["huella"], r["empresa_id"])
                                      for r in f["referencias"]),
                    relacion=f["relacion"])
                for f in bruto["fuentes"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise ErrorDescriptor([Problema("FORMATO_INVALIDO", "descriptor", f"estructura: {exc!r}")]) from None
    descriptor = construir_descriptor(inventario)
    if descriptor.huella_descriptor != bruto["huella_descriptor"] or serializar_descriptor(descriptor) != datos:
        raise ErrorDescriptor([Problema("DESCRIPTOR_ALTERADO", "descriptor",
                                        "huella o forma canónica no coinciden con el contenido")])
    return descriptor


def verificar_contenido(objeto: ObjetoFuente, datos: bytes) -> None:
    """Comprueba en memoria que ``datos`` corresponde a la huella y tamaño declarados."""
    if not isinstance(datos, (bytes, bytearray)):
        raise ErrorDescriptor([Problema("CONTENIDO_NO_VERIFICABLE", objeto.identidad, "contenido no binario")])
    problemas = []
    if _huella(bytes(datos)) != objeto.huella:
        problemas.append(Problema("CONTENIDO_NO_VERIFICABLE", objeto.identidad, "huella distinta"))
    if objeto.tamano is not None and len(datos) != objeto.tamano:
        problemas.append(Problema("CONTENIDO_NO_VERIFICABLE", objeto.identidad,
                                  f"tamaño {len(datos)} != {objeto.tamano}"))
    if problemas:
        raise ErrorDescriptor(problemas)


def huella_contenido(datos: bytes) -> str:
    """Huella en el formato del contrato (``sha256:<hex>``), calculada en memoria."""
    return _huella(bytes(datos))
