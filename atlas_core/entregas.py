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

from typing import TYPE_CHECKING, Sequence

from atlas_core.credibilidad_campos import (
    evaluar_credibilidad_entidad_nombre,
    valor_publicable,
)

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


def _destino_compatible(a: "DocumentoViaje", b: "DocumentoViaje") -> bool:
    """True sólo si ambos documentos comparten al menos un nivel de señal
    de destino poblado y coinciden en el más fuerte de esos niveles
    compartidos. Sin ningún nivel compartido -> NO compatible (nunca se
    agrupa "por descarte")."""
    niveles_a = dict(_niveles_destino(a))
    niveles_b = dict(_niveles_destino(b))
    for nombre in ("territorial", "direccion_entrega", "despachar_a"):
        if nombre in niveles_a and nombre in niveles_b:
            return niveles_a[nombre] == niveles_b[nombre]
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
    return {campo: "" for campo in campos}


def _entrega_a_dict(documentos) -> dict[str, object]:
    routing = _routing_consolidado(documentos)
    return {
        "numeros_guia": sorted(
            {d.numero_guia.strip() for d in documentos if _presente(d.numero_guia)}
        ),
        "clientes": _lista_publicable(documentos, "cliente"),
        "obras_destino": _lista_publicable(documentos, "obra_destino"),
        "destino_operacional": _primer_presente(
            [getattr(d, "direccion_entrega", "") for d in documentos]
        )
        or _primer_presente([getattr(d, "despachar_a_crudo", "") for d in documentos]),
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
