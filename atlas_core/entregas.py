"""Derivación genérica de ENTREGAS/PARADAS de un viaje (Bloque VIAJE
MULTIENTREGA V1).

Un viaje agrupa ``1..N`` documentos por ``numero_transporte``. Compartir
transporte demuestra relación de VIAJE, nunca que dos documentos vayan a la
misma entrega/parada -- un mismo camión puede dejar carga en varias comunas
el mismo día (caso real que lo motivó: transporte ``0000352376``, guías
``464698`` + ``464699`` a una comuna y ``464700`` a otra).

Este módulo deriva -- sin modelo persistente ``Entrega``, sin tocar el
dataset -- cuántas entregas distintas ya son inferibles desde los datos por
documento existentes. Sólo agrupa dos documentos cuando hay evidencia
operacional POSITIVA de que van al mismo destino:

* identidad territorial por código opaco
  (``codigo_pais`` / ``codigo_unidad`` / ``codigo_contexto``), o
* dirección de entrega ya resuelta/geocodificada por el Motor
  (``direccion_entrega`` + ``localidad_entrega``), o
* ``DESPACHAR A`` documental (``despachar_a_crudo``).

y además cliente y obra no se contradicen (ambos presentes y distintos).

Nunca agrupa sólo por ``numero_transporte``. Ante ambigüedad real (un
documento sin ninguna señal de destino utilizable) ese documento forma su
propia entrega -- nunca se fusiona "por descarte". El resultado es
determinista: N puede ser 1, 2, 5 o cualquier cantidad.
"""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING, Sequence

from atlas_core.credibilidad_campos import (
    NivelCredibilidad,
    evaluar_credibilidad_direccion,
    evaluar_credibilidad_entidad_nombre,
    valor_publicable,
)
from atlas_core.catalogo_destinos import _limite_tolerancia_ocr_direccion

if TYPE_CHECKING:  # pragma: no cover - sólo para anotaciones
    from atlas_core.gestor_viajes import DocumentoViaje


_AUSENTES = {"", "no encontrado", "revisar", "ilegible", "no disponible"}


def _presente(valor: object) -> bool:
    texto = str(valor or "").strip()
    return bool(texto) and texto.casefold() not in _AUSENTES


def _clave(valor: object) -> str:
    import unicodedata

    texto = " ".join(str(valor or "").strip().casefold().split())
    sin_acentos = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in sin_acentos if not unicodedata.combining(c))


def _evidencia(documento: "DocumentoViaje", campo: str) -> str:
    evidencia = getattr(documento, "evidencia", None)
    if isinstance(evidencia, dict):
        return str(evidencia.get(campo, "") or "").strip()
    return ""


def _codigo_territorial(documento: "DocumentoViaje") -> str:
    partes = [
        _evidencia(documento, "codigo_pais"),
        _evidencia(documento, "codigo_unidad"),
        _evidencia(documento, "codigo_contexto"),
    ]
    if all(_presente(p) for p in partes):
        return "|".join(_clave(p) for p in partes)
    return ""


def _cliente_identidad(documento: "DocumentoViaje") -> str:
    """RUT de cliente si el dato existe (identidad canónica estable);
    si no, el nombre publicable normalizado."""
    rut = _evidencia(documento, "rut_cliente")
    if _presente(rut):
        return "rut:" + _clave(rut).replace(".", "").replace("-", "")
    nombre = valor_publicable(
        getattr(documento, "cliente", ""), evaluar_credibilidad_entidad_nombre
    )
    return ("nombre:" + _clave(nombre)) if _presente(nombre) else ""


def _obra_identidad(documento: "DocumentoViaje") -> str:
    obra = valor_publicable(
        getattr(documento, "obra_destino", ""), evaluar_credibilidad_entidad_nombre
    )
    return _clave(obra) if _presente(obra) else ""


def _niveles_destino(documento: "DocumentoViaje") -> list[tuple[str, str]]:
    """Señales de destino del documento, de más fuerte a más débil. Cada
    entrada es ``(nombre_nivel, clave_comparable)`` -- sólo se incluyen las
    que traen dato real."""
    niveles: list[tuple[str, str]] = []
    territorial = _codigo_territorial(documento)
    if territorial:
        niveles.append(("territorial", territorial))
    direccion = getattr(documento, "direccion_entrega", "")
    if _presente(direccion):
        localidad = getattr(documento, "localidad_entrega", "")
        clave = _clave(direccion)
        if _presente(localidad):
            clave += "@" + _clave(localidad)
        niveles.append(("direccion_entrega", clave))
    despachar = getattr(documento, "despachar_a_crudo", "")
    if _presente(despachar):
        niveles.append(("despachar_a", _clave(despachar)))
    return niveles


# Bloque VIAJE MULTIENTREGA V1.1 -- caso real 0000359510 (chofer SALOMÓN
# PIZARRO, guías 474285/474286/474287): las tres imprimen el mismo destino
# operacional ("SANTA ISABEL 585 SANTIAGO LAMPA"), pero el OCR de 474285
# leyó "SANTA ISADEL..." (B/D confundidas, visualmente parecidas). Antes
# de este bloque, la comparación de nivel "direccion_entrega"/"despachar_a"
# exigía igualdad EXACTA tras `_clave()` (sólo case/espacios/acentos) --
# ese único carácter bastaba para que Atlas tratara dos documentos del
# MISMO destino como si fueran destinos distintos y dividiera el viaje en
# entregas que no corresponden (DIRECTO -> REPARTO falso).
#
# Reutiliza EXACTAMENTE la misma tolerancia ya usada y aprobada para
# reconocer un destino ya confirmado pese a un typo de OCR
# (`catalogo_destinos.direccion_confirmada_coincide`): sólo sustitución de
# caracteres en la MISMA posición/longitud (nunca inserción ni
# eliminación), escalada por longitud (1 cada ~25 caracteres, tope 2).
# Aplicada aquí de forma SIMÉTRICA entre dos documentos hermanos del mismo
# viaje (en vez de "documento nuevo" contra "calle ya confirmada" del
# catálogo) -- mismo criterio, nunca fuzzy matching abierto: con longitudes
# distintas no hay tolerancia (podría ser una calle realmente distinta,
# más corta o más larga -- no un typo de un solo carácter), y el código
# territorial opaco (nivel "territorial") nunca lleva tolerancia, porque
# no es texto OCR de una dirección sino un identificador exacto.
def _claves_equivalentes_por_tolerancia_ocr(clave_a: str, clave_b: str) -> bool:
    if clave_a == clave_b:
        return True
    if len(clave_a) != len(clave_b):
        return False
    limite = _limite_tolerancia_ocr_direccion(len(clave_a))
    if limite <= 0:
        return False
    distancia = sum(1 for x, y in zip(clave_a, clave_b) if x != y)
    return distancia <= limite


def _destino_compatible(a: "DocumentoViaje", b: "DocumentoViaje") -> bool:
    """True sólo si ambos documentos comparten al menos un nivel de señal
    de destino poblado y coinciden (con tolerancia a un typo de OCR de un
    solo carácter, sólo para direccion_entrega/despachar_a -- ver bloque
    arriba) en el más fuerte de esos niveles compartidos. Sin ningún nivel
    compartido -> NO compatible (nunca se agrupa "por descarte")."""
    niveles_a = dict(_niveles_destino(a))
    niveles_b = dict(_niveles_destino(b))
    for nombre in ("territorial", "direccion_entrega", "despachar_a"):
        if nombre in niveles_a and nombre in niveles_b:
            if nombre == "territorial":
                return niveles_a[nombre] == niveles_b[nombre]
            return _claves_equivalentes_por_tolerancia_ocr(niveles_a[nombre], niveles_b[nombre])
    return False


def _contradice(valor_a: str, valor_b: str) -> bool:
    return bool(valor_a) and bool(valor_b) and valor_a != valor_b


def _misma_entrega(a: "DocumentoViaje", b: "DocumentoViaje") -> bool:
    if not _destino_compatible(a, b):
        return False
    if _contradice(_cliente_identidad(a), _cliente_identidad(b)):
        return False
    if _contradice(_obra_identidad(a), _obra_identidad(b)):
        return False
    return True


def _primer_presente(valores: Sequence[str]) -> str:
    for valor in valores:
        if _presente(valor):
            return str(valor).strip()
    return ""


def _consolidar_unico(valores: Sequence[str]) -> str:
    presentes = {_clave(v): str(v).strip() for v in valores if _presente(v)}
    if len(presentes) == 1:
        return next(iter(presentes.values()))
    return ""


def _lista_publicable(documentos, campo: str) -> list[str]:
    vistos: dict[str, str] = {}
    for documento in documentos:
        valor = valor_publicable(
            getattr(documento, campo, ""), evaluar_credibilidad_entidad_nombre
        )
        if _presente(valor):
            vistos.setdefault(_clave(valor), str(valor).strip())
    return sorted(vistos.values(), key=_clave)


def _routing_consolidado(documentos) -> dict[str, str]:
    """Misma idea que ``Viaje._bloque_routing_consolidado`` pero acotada a
    los documentos de UNA entrega: si todos los que informan ruta coinciden,
    se usa ese bloque; si sólo hay un modo de fallo coherente, se conserva
    el diagnóstico sin km/tiempo; ante contradicción real, todo vacío."""
    campos = ("distancia_km", "duracion_min", "proveedor_ruta", "estado_ruta", "motivo_ruta")
    bloques = [
        {campo: str(getattr(d, campo, "") or "").strip() for campo in campos}
        for d in documentos
    ]
    informados = [b for b in bloques if any(b.values())]
    if not informados:
        return {campo: "" for campo in campos}
    firmas = {tuple(b[campo] for campo in campos) for b in informados}
    if len(firmas) == 1:
        return dict(informados[0])
    fallos = {
        (b["estado_ruta"], b["motivo_ruta"])
        for b in informados
        if _clave(b["estado_ruta"]) != "ruta_calculada"
    }
    if len(fallos) == 1:
        estado, motivo = next(iter(fallos))
        return {
            "distancia_km": "", "duracion_min": "", "proveedor_ruta": "",
            "estado_ruta": estado, "motivo_ruta": motivo,
        }
    # Bloque VIAJE MULTIENTREGA V1.1 -- caso real 0000359510: varios
    # documentos calcularon EXITOSAMENTE una ruta (todos RUTA_CALCULADA),
    # pero con resultados numéricos distintos -- porque se calcularon
    # ANTES de reconocerse como la misma entrega (un typo de OCR en la
    # dirección de uno de ellos -- ya tolerado en la identidad de la
    # entrega, ver `_claves_equivalentes_por_tolerancia_ocr` -- generó una
    # geocodificación independiente y ligeramente distinta del MISMO
    # destino real). Nunca se promedia ni se inventa un punto intermedio
    # (NO centroide, NUNCA): si una ruta YA calculada es compartida por la
    # MAYORÍA ESTRICTA de los documentos exitosos de la entrega, se
    # reutiliza esa -- es la que más evidencia independiente ya confirma,
    # nunca una ruta nueva. Ante empate real (ninguna mayoría estricta),
    # Atlas se abstiene igual que siempre: ambigüedad geográfica genuina,
    # nunca se adivina cuál de las rutas ya calculadas es la correcta.
    if not fallos:
        conteo = Counter(tuple(b[campo] for campo in campos) for b in informados)
        firma_mayoritaria, votos = conteo.most_common(1)[0]
        otros_votos = len(informados) - votos
        if votos > otros_votos:
            return dict(zip(campos, firma_mayoritaria))
    return {campo: "" for campo in campos}


# Bloque VIAJE MULTIENTREGA V1.1 -- caso real 0000359510: `_primer_presente`
# toma literalmente el primer documento de la entrega en el orden en que
# llegó -- que resultó ser justo el que trae el typo de OCR ("SANTA
# ISADEL..."), mostrando como destino operacional de la PARADA un valor
# minoritario mientras el resto de la consolidación (ruta/`direccion_
# entrega` a nivel de viaje, ver `_routing_consolidado` arriba y
# `Viaje._campo_ruta_consolidado`) ya presenta la dirección real compartida
# por la mayoría. Mismo criterio en los tres lugares, nunca una regla
# paralela distinta: con MAYORÍA ESTRICTA se presenta ese valor exacto
# (nunca uno inventado ni promediado); sin mayoría estricta (empate o un
# único documento), se conserva el comportamiento previo -- el primer valor
# presente -- para no dejar de mostrar un destino que sí existe.
#
# P0 D2 -- INVARIANTE: un candidato de destino rechazado, de baja
# confianza o contradictorio nunca puede reaparecer como destino
# operacional por consolidación/mayoría entre documentos. La versión
# original de este bloque votaba sobre el texto crudo de TODOS los
# `direccion_entrega` presentes sin filtrar por credibilidad -- dos
# documentos agrupados en la misma entrega por evidencia territorial
# fuerte (código opaco, `_destino_compatible`) pueden traer un
# `direccion_entrega` DUDOSO/INVÁLIDO (fragmento truncado o contaminado
# por otra sección, ver `credibilidad_campos.evaluar_credibilidad_
# direccion`) que nunca debería ganar sólo por aparecer más veces. Se
# vota únicamente entre los valores CONFIABLES (mismo criterio ya usado
# por `Viaje.despachar_a`); un valor rechazado/dudoso jamás entra a la
# cuenta, gane o no la mayoría.
def _destino_operacional_consolidado(documentos) -> str:
    valores_presentes = [
        str(v).strip() for v in (getattr(d, "direccion_entrega", "") for d in documentos)
        if _presente(v)
    ]
    valores_confiables = [
        v for v in valores_presentes
        if evaluar_credibilidad_direccion(v).nivel == NivelCredibilidad.CONFIABLE
    ]
    if valores_confiables:
        conteo = Counter(_clave(v) for v in valores_confiables)
        clave_mayoritaria, votos = conteo.most_common(1)[0]
        if votos > len(valores_confiables) - votos:
            return next(v for v in valores_confiables if _clave(v) == clave_mayoritaria)
        return valores_confiables[0]
    return _primer_presente([getattr(d, "despachar_a_crudo", "") for d in documentos])


def _entrega_a_dict(documentos) -> dict[str, object]:
    routing = _routing_consolidado(documentos)
    return {
        "numeros_guia": sorted(
            {d.numero_guia.strip() for d in documentos if _presente(d.numero_guia)}
        ),
        "clientes": _lista_publicable(documentos, "cliente"),
        "obras_destino": _lista_publicable(documentos, "obra_destino"),
        "destino_operacional": _destino_operacional_consolidado(documentos),
        "localidad_entrega": _consolidar_unico(
            [getattr(d, "localidad_entrega", "") for d in documentos]
        ),
        "region_entrega": _consolidar_unico(
            [getattr(d, "region_entrega", "") for d in documentos]
        ),
        "distancia_km": routing["distancia_km"],
        "duracion_min": routing["duracion_min"],
        "proveedor_ruta": routing["proveedor_ruta"],
        "estado_ruta": routing["estado_ruta"],
        "motivo_ruta": routing["motivo_ruta"],
    }


def derivar_entregas(documentos: Sequence["DocumentoViaje"]) -> list[dict[str, object]]:
    """Deriva la lista de entregas/paradas de un viaje a partir de sus
    documentos. Devuelve al menos una entrega por cada viaje con documentos;
    con un solo destino inferible, la lista tiene un único elemento (el
    llamador mantiene entonces la presentación compacta de siempre)."""
    documentos = list(documentos)
    if not documentos:
        return []

    grupos: list[list["DocumentoViaje"]] = []
    for documento in documentos:
        for grupo in grupos:
            if all(_misma_entrega(documento, miembro) for miembro in grupo):
                grupo.append(documento)
                break
        else:
            grupos.append([documento])

    return [_entrega_a_dict(grupo) for grupo in grupos]
