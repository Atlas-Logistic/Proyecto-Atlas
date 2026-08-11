"""Resolución estructurada de destino canónico (Bloque DESTINOS D2).

Prioriza identificadores estables del propio documento -- RUT cliente +
código destinatario, dirección + comuna, obra destino -- sobre el
emparejamiento textual débil de `obra_destino` contra el nombre del
destino. Nunca fabrica un destino: cada nivel exige una coincidencia
exacta y única dentro del cliente ya resuelto; ante cualquier duda, cae al
siguiente nivel y, si ninguno alcanza, se abstiene (DESTINO_NO_HOMOLOGADO)
-- exactamente igual que antes de este bloque.

Jerarquía (más confiable primero), según auditoría real (Fase A/D2, 7
guías) más la auditoría independiente de 31 guías que descartó usar
COD DESTINATARIO como llave autónoma (el mismo código puede repetirse
para el mismo cliente con un DESPACHAR A distinto -- ver
`evaluar_concordancia_despacho`):

  A. cliente (RUT/razón social) + código destinatario exacto -> destino único
  B. cliente + dirección (+ comuna si está disponible) exacta normalizada -> destino único
  C. cliente + alias/nombre exacto ya registrado (incluye obra_destino) -> destino único
  D. nombre/alias exacto sin acotar por cliente (comportamiento histórico
     de `resolver_destino_canonico`, sin cambios)
  E. sin evidencia suficiente -> DESTINO_NO_HOMOLOGADO

La identidad del destino (A-D) responde "a qué obra/domicilio del cliente
pertenece este documento" -- una pregunta de homologación/reporte. Es una
pregunta DISTINTA de "a dónde viajó físicamente el camión en este viaje
puntual", que es lo que importa para ORS. El propio documento declara ese
punto real en el campo DESPACHAR A, que puede diferir del domicilio
registrado del cliente (mismo cliente, mismo código, sitio de entrega
distinto -- caso real documentado: código 0001004443/TORRES OCARANZA con
DESPACHAR A "VISTA CLARA 391" en una guía y "VISTA CLARA 2351" en otra).
`evaluar_concordancia_despacho` hace esa segunda pregunta por separado;
`calcular_ruta_para_viaje` la consulta antes de enrutar.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Iterable

from atlas_core.catalogo_clientes import (
    CatalogoClientes,
    ErrorCatalogoClientes,
    EstadoBusquedaCliente,
    normalizar_rut_cliente,
)
from atlas_core.catalogo_destinos import (
    CatalogoDestinos,
    Destino,
    EstadoBusquedaDestino,
    normalizar_nombre_destino,
)

# Etiquetas conocidas del encabezado AZA que pueden aparecer inmediatamente
# después del valor de un campo capturado -- delimitan dónde termina ese
# valor sin asumir un orden fijo entre etiquetas (el orden varía guía a
# guía por variaciones del layout que Paddle detecta -- ver Fase A).
_ETIQUETAS_CORTE = (
    r"COD\s*[O0]?\s*[I1]?[GC]?[O0]?\.?\s*DESTINATARI[O0]",
    r"DIRECCI[O0]N",
    r"COMUNA",
    r"CIUDAD",
    r"HORA\s+ENTRADA",
    r"HORA\s+SALIDA",
    r"GIRO",
    r"TELEFONO",
    r"R\.?\s*U\.?\s*T\.?",
    r"OBRA\s+DESTINO",
    r"SOLICITANTE",
    r"SE[ÑN]OR",
    r"INDICADOR\s+TRASLADO",
    r"DESPACHAR\s+A",
    r"RETIRA",
    r"RUT\s+CHOFER",
    r"PATENTE",
    r"FECHA\s+SALIDA",
    r"NOMBRE",
)
_LIMITE = "(?:" + "|".join(_ETIQUETAS_CORTE) + ")"

_PATRON_COD_DESTINATARIO = re.compile(
    r"\bC[O0][D0O](?:IG[O0])?\.?\s*D[E3]STINATARI[O0]\b\s*[:\-]?\s*([A-Z0-9_-]+)"
)
_PATRON_DIRECCION = re.compile(
    rf"\bDIRECCI[O0]N\b\s*[:\-]?\s*(.+?)(?=\s+{_LIMITE}\b|$)"
)
_PATRON_COMUNA = re.compile(
    rf"\bCOMUNA\b\s*[:\-]?\s*(.+?)(?=\s+{_LIMITE}\b|$)"
)
_PATRON_DESPACHAR_A = re.compile(
    rf"\bDESPACHAR\s+A\b\s*[:\-]?\s*(.+?)(?=\s+{_LIMITE}\b|$)"
)


def _texto_sin_acentos(texto: str) -> str:
    normalizado = unicodedata.normalize("NFD", texto)
    return "".join(c for c in normalizado if unicodedata.category(c) != "Mn")


@dataclass(frozen=True)
class IdentificadoresDestinoDocumento:
    codigo_destinatario: str | None = None
    direccion: str | None = None
    comuna: str | None = None
    despachar_a: str | None = None


def extraer_identificadores_destino(
    textos: Iterable[str],
) -> IdentificadoresDestinoDocumento:
    """Lee del propio documento (texto OCR de página completa, ya
    disponible -- no requiere una relectura focal) los identificadores
    estructurados de destino. Conservador: si el orden de las etiquetas en
    el documento está degradado por el OCR (layout con recuadros leídos
    fuera de orden), simplemente no captura nada para ese campo en vez de
    arriesgar un valor incorrecto -- el nivel de resolución
    correspondiente cae al siguiente sin romper nada, porque cada nivel
    exige coincidencia exacta contra el catálogo real."""
    texto = _texto_sin_acentos("\n".join(textos).upper())
    texto_una_linea = " ".join(texto.split())

    cod = _PATRON_COD_DESTINATARIO.search(texto_una_linea)
    direccion = _PATRON_DIRECCION.search(texto_una_linea)
    comuna = _PATRON_COMUNA.search(texto_una_linea)
    despacho = _PATRON_DESPACHAR_A.search(texto_una_linea)

    return IdentificadoresDestinoDocumento(
        codigo_destinatario=cod.group(1).strip() if cod else None,
        direccion=direccion.group(1).strip() if direccion else None,
        comuna=comuna.group(1).strip() if comuna else None,
        despachar_a=despacho.group(1).strip() if despacho else None,
    )


def resolver_destino_canonico_estructurado(
    *,
    cliente_texto: str | None,
    obra_destino_texto: str,
    textos_documento: Iterable[str] | None,
    catalogo_destinos: CatalogoDestinos,
    catalogo_clientes: CatalogoClientes,
    rut_cliente_texto: str | None = None,
) -> tuple[Destino | None, str]:
    """Homologa el destino priorizando identificadores estructurados del
    documento sobre el nombre libre de obra_destino, siempre acotado al
    cliente ya resuelto -- nunca compara un código o dirección contra
    destinos de otro cliente. Si el cliente no se resuelve o ninguna señal
    estructurada alcanza, cae exactamente en `resolver_destino_canonico`
    (nivel D), idéntico al usado antes de este bloque -- ningún caller
    existente cambia de comportamiento."""
    # Import local para evitar import circular: enriquecimiento_viaje usa
    # este módulo solo dentro de una función (import perezoso), este
    # módulo usa el resolver histórico de enriquecimiento_viaje a nivel de
    # módulo -- una sola dirección de dependencia "hacia abajo".
    from atlas_core.rutas.enriquecimiento_viaje import (
        resolver_destino_canonico,
        validar_destino_resoluble,
    )

    cliente_id = None
    if cliente_texto:
        resultado_cliente = catalogo_clientes.buscar(str(cliente_texto))
        if resultado_cliente.estado == EstadoBusquedaCliente.COINCIDENCIA:
            candidato = resultado_cliente.cliente
            rut_normalizado = ""
            if rut_cliente_texto:
                try:
                    rut_normalizado = normalizar_rut_cliente(rut_cliente_texto)
                except ErrorCatalogoClientes:
                    rut_normalizado = ""
            if candidato.rut and rut_normalizado and candidato.rut != rut_normalizado:
                # El nombre coincidió pero el RUT del propio documento
                # contradice el RUT ya registrado para ese cliente en el
                # catálogo -- no se acota por cliente (evidencia
                # contradictoria); se degrada al nivel D (global) en vez
                # de arriesgar una identidad de cliente equivocada.
                cliente_id = None
            else:
                cliente_id = candidato.cliente_id

    identificadores = (
        extraer_identificadores_destino(textos_documento)
        if textos_documento is not None
        else IdentificadoresDestinoDocumento()
    )

    if cliente_id is not None:
        destinos_cliente = [
            d
            for d in catalogo_destinos.listar(cliente_id=cliente_id)
            if d.estado_vigencia == "ACTIVO"
        ]

        # Nivel A: RUT/cliente + código destinatario exacto, único.
        if identificadores.codigo_destinatario:
            candidatos = [
                d
                for d in destinos_cliente
                if d.codigo_destino
                and d.codigo_destino == identificadores.codigo_destinatario
            ]
            if len(candidatos) == 1:
                return validar_destino_resoluble(
                    candidatos[0], "RESUELTO_CODIGO_DESTINATARIO"
                )
            if len(candidatos) > 1:
                return None, "DESTINO_AMBIGUO_CODIGO_DESTINATARIO"

        # Nivel B: dirección (+ comuna si se extrajo) exacta normalizada,
        # única, dentro del cliente.
        if identificadores.direccion:
            clave_direccion = normalizar_nombre_destino(identificadores.direccion)
            candidatos = [
                d for d in destinos_cliente if d.nombre_normalizado == clave_direccion
            ]
            if identificadores.comuna:
                clave_comuna = normalizar_nombre_destino(identificadores.comuna)
                candidatos = [
                    d
                    for d in candidatos
                    if not d.comuna
                    or normalizar_nombre_destino(d.comuna) == clave_comuna
                ]
            if len(candidatos) == 1:
                return validar_destino_resoluble(
                    candidatos[0], "RESUELTO_DIRECCION_COMUNA"
                )
            if len(candidatos) > 1:
                return None, "DESTINO_AMBIGUO_DIRECCION"

        # Nivel C: alias/nombre exacto (incluye obra_destino), acotado al
        # cliente ya resuelto -- mismo mecanismo que el nivel D, pero
        # restringido a este cliente en vez de a todo el catálogo.
        texto_obra = str(obra_destino_texto or "").strip()
        if texto_obra and texto_obra.casefold() != "no encontrado":
            resultado_alias = catalogo_destinos.buscar(texto_obra, cliente_id=cliente_id)
            if resultado_alias.estado == EstadoBusquedaDestino.COINCIDENCIA:
                return validar_destino_resoluble(
                    resultado_alias.destino, "RESUELTO_ALIAS_CLIENTE"
                )
            if resultado_alias.estado == EstadoBusquedaDestino.AMBIGUA:
                return None, "DESTINO_AMBIGUO"

    # Nivel D: comportamiento histórico sin acotar por cliente (sin cambios).
    return resolver_destino_canonico(obra_destino_texto, catalogo_destinos)


def evaluar_concordancia_despacho(
    destino: Destino, identificadores: IdentificadoresDestinoDocumento
) -> tuple[bool, str]:
    """Compara el destino canónico ya resuelto (dirección/comuna del
    catálogo, que representa el domicilio registrado del cliente) contra
    el campo DESPACHAR A de este documento puntual -- el punto de entrega
    real declarado para ESTE viaje. Evidencia real (Bloque DESTINOS D2):
    el mismo cliente y el mismo código destinatario pueden repetirse con
    un DESPACHAR A distinto entre guías (incluso en otra región), así que
    la identidad del destino NUNCA implica por sí sola que sus
    coordenadas sean el punto de entrega real de este viaje -- eso se
    verifica aquí, por separado, antes de enrutar.

    Sin evidencia de DESPACHAR A en el documento, no hay con qué
    contradecir el destino ya homologado -- se considera concordante
    (comportamiento igual al histórico, sin este campo)."""
    despacho = str(identificadores.despachar_a or "").strip()
    if not despacho:
        return True, ""
    tokens_despacho = set(normalizar_nombre_destino(despacho).split())
    comuna_destino = normalizar_nombre_destino(destino.comuna)
    tokens_direccion = set(destino.nombre_normalizado.split())
    coincide_comuna = bool(comuna_destino) and comuna_destino in tokens_despacho
    coincide_direccion = bool(tokens_direccion) and bool(
        tokens_direccion & tokens_despacho
    )
    if coincide_comuna or coincide_direccion:
        return True, ""
    return False, "DESPACHO_DIVERGENTE_DEL_DESTINO_CANONICO"
