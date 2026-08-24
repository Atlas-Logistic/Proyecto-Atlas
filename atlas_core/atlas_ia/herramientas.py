"""Herramientas read-only de evidencia disponibles para Atlas IA B1."""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from typing import Callable, Iterable, Mapping

from atlas_core.atlas_ia.contratos import ContextoRazonamiento, EvidenciaIA

logger = logging.getLogger(__name__)

ConsultaEvidencia = Callable[[ContextoRazonamiento], tuple[EvidenciaIA, ...]]


@dataclass(frozen=True)
class HerramientaEvidencia:
    nombre: str
    descripcion: str
    consultar: ConsultaEvidencia


def herramienta_documentos_relacionados(
    filas: Iterable[Mapping[str, object]],
) -> HerramientaEvidencia:
    """Expone otras guías del mismo transporte como evidencia, sin decidir."""
    filas_copia = tuple(dict(fila) for fila in filas)

    def consultar(contexto: ContextoRazonamiento) -> tuple[EvidenciaIA, ...]:
        evidencias: list[EvidenciaIA] = []
        for fila in filas_copia:
            guia = str(fila.get("numero_guia", "")).strip()
            transporte = str(fila.get("numero_transporte", "")).strip()
            if not transporte or transporte != contexto.numero_transporte or guia == contexto.numero_guia:
                continue
            valor = str(fila.get(contexto.campo, "")).strip()
            if not valor or valor in ("No encontrado", "NO ENCONTRADO"):
                continue
            evidencias.append(EvidenciaIA(
                identificador=f"documento:{guia}:{contexto.campo}",
                campo=contexto.campo, valor=valor, tipo_fuente="DOCUMENTAL",
                nivel="DOCUMENTAL_DEBIL", a_favor=("MISMO_TRANSPORTE",),
                independencia=0,
                procedencia="atlas_core.atlas_ia.herramientas.documentos_relacionados",
                referencias_fuente=(f"guia={guia};transporte={transporte};relacion=MISMO_TRANSPORTE",),
            ))
        return tuple(evidencias)

    return HerramientaEvidencia(
        nombre="DOCUMENTOS_RELACIONADOS",
        descripcion="Busca valores del mismo campo en otras guías del mismo transporte.",
        consultar=consultar,
    )


# ---------------------------------------------------------------------
# Bloque B1 INVESTIGADOR -- verificación externa real (búsqueda web)
# ---------------------------------------------------------------------

# Límite de búsquedas REALES por invocación de esta herramienta -- nunca
# "Internet por cada guía": bounded, y cada consulta pasa primero por
# caché (`BuscadorWebConCache`) antes de gastar una llamada real.
MAXIMO_CONSULTAS_POR_INVOCACION = 2


def _construir_consultas_investigacion(contexto: ContextoRazonamiento) -> tuple[str, ...]:
    """Regla crítica (Bloque B1 INVESTIGADOR): la dirección NUNCA se
    investiga como string aislado si Atlas ya dispone de contexto
    empresarial/operacional -- se vincula SIEMPRE calle↔empresa↔obra↔
    comuna/región/país desde la PRIMERA consulta, en vez de variantes
    ciegas de la sola dirección. Genérico por construcción: usa
    cualquier campo presente en `identidad_operacional` (obra/cliente),
    nunca hardcodea un nombre de empresa u obra concreto."""
    valor = str(contexto.valor_documental or "").strip()
    if not valor:
        return ()
    obra = str(contexto.identidad_operacional.get("obra_destino", "") or "").strip()
    cliente = str(contexto.identidad_operacional.get("cliente", "") or "").strip()
    consultas: list[str] = []
    if obra and obra.upper() not in ("NO ENCONTRADO", ""):
        consultas.append(f"{valor}, empresa/obra {obra}, Chile -- ¿es una dirección real y en qué comuna?")
    if cliente and cliente.upper() not in ("NO ENCONTRADO", "") and cliente != obra:
        consultas.append(f"{valor}, cliente {cliente}, Región Metropolitana, Chile -- ¿es una dirección real y en qué comuna?")
    if not consultas:
        # Sin obra/cliente utilizable -- único caso donde se investiga la
        # dirección sola, con contexto territorial explícito (nunca sin
        # país/región, ver Bloque TERRITORIAL T1/RESOLUCIÓN R16).
        consultas.append(f"{valor}, Santiago, Región Metropolitana, Chile -- ¿es una dirección real y en qué comuna?")
    return tuple(consultas[:MAXIMO_CONSULTAS_POR_INVOCACION])


def herramienta_verificacion_externa(buscador) -> HerramientaEvidencia:
    """Bloque B1 INVESTIGADOR -- expone búsqueda web REAL (nunca simulada
    durante operación) como herramienta que B1 puede solicitar
    (`HipotesisIA.herramienta_faltante == "VERIFICACION_EXTERNA"`) cuando
    la evidencia interna (catálogos/histórico/documentos hermanos) no
    alcanza. `buscador` es cualquier objeto con `.buscar(consulta) ->
    RespuestaBusquedaWeb` (ver `buscador_web.py`) -- normalmente
    `BuscadorWebConCache`, así que la misma consulta nunca se paga dos
    veces. Nunca decide nada: sólo empaqueta texto+citas reales como
    `EvidenciaIA(tipo_fuente="EXTERNO")` -- B1 es quien las lee, las
    cruza con el resto de la evidencia, y concluye.

    Nunca lanza: un fallo del buscador (sin credencial, sin red, límite
    de cuota) se traduce en `()` -- abstención, nunca evidencia
    fabricada ni una excepción que tumbe el resto del procesamiento."""

    def consultar(contexto: ContextoRazonamiento) -> tuple[EvidenciaIA, ...]:
        consultas = _construir_consultas_investigacion(contexto)
        evidencias: list[EvidenciaIA] = []
        for consulta in consultas:
            try:
                respuesta = buscador.buscar(consulta)
            except Exception as error:  # nunca tumba el procesamiento por una búsqueda fallida
                logger.warning("VERIFICACION_EXTERNA: búsqueda fallida (%s): %s", type(error).__name__, error)
                continue
            if not respuesta.respuesta_texto.strip():
                continue
            identificador = "externo:" + hashlib.sha256(consulta.encode("utf-8")).hexdigest()[:16]
            evidencias.append(EvidenciaIA(
                identificador=identificador, campo=contexto.campo,
                valor=respuesta.respuesta_texto.strip()[:600],
                tipo_fuente="EXTERNO", nivel="EXTERNO_WEB",
                independencia=len(respuesta.citas),
                procedencia="atlas_ia.herramientas.verificacion_externa",
                referencias_fuente=tuple(f"{c.titulo} <{c.url}>" for c in respuesta.citas if c.url) or (respuesta.consulta,),
            ))
        return tuple(evidencias)

    return HerramientaEvidencia(
        nombre="VERIFICACION_EXTERNA",
        descripcion=(
            "Búsqueda web real (Internet), vinculando SIEMPRE dirección con "
            "empresa/obra/comuna cuando ese contexto exista -- nunca la "
            "dirección como string aislado. Máximo "
            f"{MAXIMO_CONSULTAS_POR_INVOCACION} consultas reales por invocación, "
            "cacheadas."
        ),
        consultar=consultar,
    )
