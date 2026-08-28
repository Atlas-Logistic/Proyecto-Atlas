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
# Bloque SIMPLIFICAR/AVANZAR A B1 -- herramientas de investigación de
# ORIGEN para B1: sólo se activan cuando la evidencia DIRECTA (GPS
# contemporáneo a la ventana documental, Mobile inequívoco) no alcanzó
# para resolver -- ver `atlas_core.telemetria.seleccion_recorrido.
# resolver_planta_origen_gps`, que resuelve solo con esa evidencia
# directa y nunca llega a B1 si ya concluyó. Caso real motivador:
# 472647/472648 (transporte 0000355231) -- sin GPS OneLogis útil, sin
# Mobile útil, membrete corporativo inválido como evidencia (ver Bloque
# CORRECCIÓN ESTRUCTURAL DE ORIGEN DOCUMENTAL AZA) -- B1 debe poder
# investigar historial y catálogo por sí mismo, nunca una receta fija.
# ---------------------------------------------------------------------


def herramienta_evidencia_historial_origen(
    filas: Iterable[Mapping[str, object]],
) -> HerramientaEvidencia:
    """Expone, como evidencia, TODAS las guías del dataset cuyo origen ya
    quedó determinado por evidencia INDEPENDIENTE (GPS, Mobile o
    confirmación humana -- nunca por el membrete/`DOCUMENTO`, que ya se
    sabe poco confiable). Nunca precalcula "el patrón" (correlatividad de
    número de guía, coincidencia de material, de chofer, de vehículo,
    etc.) -- eso es exactamente lo que B1 debe descubrir por su cuenta a
    partir de los hechos crudos que aquí se entregan (guía, transporte,
    fecha, patente, chofer, cliente, obra, tipo de carga/material), nunca
    una conclusión ya masticada. `valor` es siempre el nombre de la
    planta -- la única forma en que B1 puede proponerla (ver
    `validadores.validar_hipotesis_multicampo`, exige que la propuesta
    aparezca literalmente como `valor` de alguna evidencia)."""
    filas_copia = tuple(dict(fila) for fila in filas)
    ORIGENES_INDEPENDIENTES = ("TELEMETRIA_GPS", "MOBILE", "CONFIRMACION_HUMANA")

    def consultar(contexto: ContextoRazonamiento) -> tuple[EvidenciaIA, ...]:
        evidencias: list[EvidenciaIA] = []
        for fila in filas_copia:
            guia = str(fila.get("numero_guia", "")).strip()
            if not guia or guia == contexto.numero_guia:
                continue
            if str(fila.get("origen_determinado_por", "")).strip() not in ORIGENES_INDEPENDIENTES:
                continue
            planta_nombre = str(fila.get("planta_origen_nombre", "")).strip()
            if not planta_nombre:
                continue
            evidencias.append(EvidenciaIA(
                identificador=f"historial_origen:{guia}",
                campo="planta_origen", valor=planta_nombre,
                tipo_fuente="HISTORICO", nivel="ORIGEN_CONFIRMADO_INDEPENDIENTE",
                a_favor=(str(fila.get("origen_determinado_por", "")).strip(),),
                independencia=1,
                procedencia="atlas_core.atlas_ia.herramientas.evidencia_historial_origen",
                referencias_fuente=(
                    f"guia={guia}", f"transporte={fila.get('numero_transporte', '')}",
                    f"fecha={fila.get('fecha', '')}", f"patente_tracto={fila.get('patente_tracto', '')}",
                    f"chofer={fila.get('chofer', '')}", f"cliente={fila.get('cliente', '')}",
                    f"obra_destino={fila.get('obra_destino', '')}",
                    f"tipo_carga={fila.get('tipo_carga', '')}",
                    f"descripcion_material={fila.get('descripcion_material', '')}",
                ),
            ))
        return tuple(evidencias)

    return HerramientaEvidencia(
        nombre="EVIDENCIA_HISTORIAL_ORIGEN",
        descripcion=(
            "Lista otras guías del dataset con origen ya confirmado por evidencia "
            "independiente (GPS, Mobile o confirmación humana), con sus datos "
            "operacionales crudos (fecha, patente, chofer, cliente, material, número "
            "de guía/transporte) -- nunca un patrón ya calculado; investigar "
            "correlaciones (numeración, material, vehículo, chofer, etc.) es tarea "
            "de quien razona, no de esta herramienta."
        ),
        consultar=consultar,
    )


def herramienta_evidencia_catalogo_plantas(plantas: Iterable[object]) -> HerramientaEvidencia:
    """Expone el catálogo de plantas vivas (CONFIRMADA+ACTIVA) como
    evidencia informativa -- incluidas las categorías de material que
    cada una tiene permitidas, cuando el catálogo las trae. Nunca aplica
    la regla por software (eso seguiría siendo
    `atlas_core.rutas.origen_evidencia.evaluar_compatibilidad_planta_
    categoria`, usada por la evidencia DIRECTA/determinista) -- aquí es
    sólo un hecho más que B1 puede leer y sopesar junto al resto,
    consistente con la política de sistema (categoría/catálogo no es
    garantía absoluta para un caso puntual, punto 6)."""
    plantas_lista = tuple(plantas)

    def consultar(contexto: ContextoRazonamiento) -> tuple[EvidenciaIA, ...]:
        evidencias: list[EvidenciaIA] = []
        for planta in plantas_lista:
            if getattr(planta, "estado_calidad", "") != "CONFIRMADA" or getattr(planta, "estado_vigencia", "") != "ACTIVA":
                continue
            categorias = tuple(getattr(planta, "categorias_permitidas", ()) or ())
            evidencias.append(EvidenciaIA(
                identificador=f"catalogo_planta:{getattr(planta, 'planta_id', '')}",
                campo="planta_origen", valor=str(getattr(planta, "nombre", "")),
                tipo_fuente="CATALOGO", nivel="CATALOGO_PLANTA_VIVA",
                a_favor=tuple(f"categoria_permitida={c}" for c in categorias),
                procedencia="atlas_core.atlas_ia.herramientas.evidencia_catalogo_plantas",
                referencias_fuente=(
                    f"comuna={getattr(planta, 'comuna', '')}",
                    f"direccion={getattr(planta, 'direccion', '')}",
                ),
            ))
        return tuple(evidencias)

    return HerramientaEvidencia(
        nombre="EVIDENCIA_CATALOGO_PLANTAS",
        descripcion=(
            "Lista las plantas vivas del catálogo (CONFIRMADA+ACTIVA) con sus "
            "categorías de material permitidas, cuando el catálogo las trae -- "
            "conocimiento operacional disponible, nunca una garantía absoluta para "
            "este caso puntual."
        ),
        consultar=consultar,
    )


# ---------------------------------------------------------------------
# Bloque B1 INVESTIGADOR -- verificación externa real (búsqueda web)
# ---------------------------------------------------------------------

# Límite de búsquedas REALES por invocación de esta herramienta -- nunca
# "Internet por cada guía": bounded, y cada consulta pasa primero por
# caché (`BuscadorWebConCache`) antes de gastar una llamada real.
MAXIMO_CONSULTAS_POR_INVOCACION = 2


_AUSENTE = {"", "NO ENCONTRADO"}

# Campos cuyo `valor_documental` YA ES una dirección (nunca un nombre de
# empresa/obra/persona) -- sólo para estos tiene sentido preguntar "¿es
# una dirección real?". Cualquier otro campo (obra_destino, cliente,
# chofer, etc.) trae un NOMBRE/IDENTIDAD, nunca una dirección -- ver
# Bloque OBRA/DESTINO V2.
_CAMPOS_DIRECCION = {"despachar_a_crudo", "direccion_entrega"}


def _construir_consultas_investigacion(contexto: ContextoRazonamiento) -> tuple[str, ...]:
    """Regla crítica (Bloque B1 INVESTIGADOR): la dirección NUNCA se
    investiga como string aislado si Atlas ya dispone de contexto
    empresarial/operacional -- se vincula SIEMPRE calle↔empresa↔obra↔
    comuna/región/país desde la PRIMERA consulta, en vez de variantes
    ciegas de la sola dirección. Genérico por construcción: usa
    cualquier campo presente en `identidad_operacional` (obra/cliente/
    dirección de entrega), nunca hardcodea un nombre de empresa u obra
    concreto.

    Bloque OBRA/DESTINO V2 -- causa raíz real (caso 472593): esta
    función asumía que `contexto.valor_documental` SIEMPRE era una
    dirección ("¿es una dirección real?"), pero para
    OBRA_DESTINO_SIN_CORROBORAR (`campo="obra_destino"`) ese valor es un
    NOMBRE de empresa/obra ("EMPRESA CONST SIGRO"), nunca una dirección
    -- la pregunta resultante ("¿es 'EMPRESA CONST SIGRO' una dirección
    real?") no tenía sentido y sólo traía el domicilio corporativo
    genérico de esa empresa (identidad, no relación). La pregunta
    correcta para un NOMBRE es sobre la RELACIÓN con la dirección de
    entrega YA CONOCIDA (`identidad_operacional["direccion_entrega"]`,
    la misma fuente autoritativa de destino que ya usa
    `atlas_core.rutas.destino_entrega` -- DESPACHAR A, nunca la sede
    corporativa del cliente/receptor): "¿existe evidencia de que
    [nombre] tenga/haya tenido una obra/proyecto/sucursal/destino
    operacional relacionado con [dirección]?" -- nunca "¿es [nombre]
    una dirección?". Sólo los campos que SÍ son direcciones
    (`_CAMPOS_DIRECCION`) conservan la pregunta original."""
    valor = str(contexto.valor_documental or "").strip()
    if not valor:
        return ()
    obra = str(contexto.identidad_operacional.get("obra_destino", "") or "").strip()
    cliente = str(contexto.identidad_operacional.get("cliente", "") or "").strip()
    direccion = str(contexto.identidad_operacional.get("direccion_entrega", "") or "").strip()
    consultas: list[str] = []

    if contexto.campo.lower() in _CAMPOS_DIRECCION:
        # `valor` ya es una dirección -- comportamiento histórico, sin
        # cambios: vincularla a la obra/cliente conocidos, nunca
        # investigarla sola.
        if obra and obra.upper() not in _AUSENTE:
            consultas.append(f"{valor}, empresa/obra {obra}, Chile -- ¿es una dirección real y en qué comuna?")
        if cliente and cliente.upper() not in _AUSENTE and cliente != obra:
            consultas.append(f"{valor}, cliente {cliente}, Región Metropolitana, Chile -- ¿es una dirección real y en qué comuna?")
        if not consultas:
            # Sin obra/cliente utilizable -- único caso donde se investiga
            # la dirección sola, con contexto territorial explícito
            # (nunca sin país/región, ver Bloque TERRITORIAL T1/
            # RESOLUCIÓN R16).
            consultas.append(f"{valor}, Santiago, Región Metropolitana, Chile -- ¿es una dirección real y en qué comuna?")
    else:
        # `valor` es un NOMBRE (empresa/obra/destino) -- la pregunta es
        # sobre la RELACIÓN con la dirección de entrega ya conocida,
        # nunca sobre si el nombre "es una dirección".
        if direccion and direccion.upper() not in _AUSENTE:
            consultas.append(
                f"¿Existe evidencia pública de que \"{valor}\" tenga o haya tenido una obra, proyecto, "
                f"sucursal o destino operacional relacionado con la dirección \"{direccion}\", Chile? "
                "Responde específicamente sobre esa relación (obra/entrega), no sólo sobre la sede "
                "corporativa general de la empresa."
            )
        if cliente and cliente.upper() not in _AUSENTE and cliente != valor:
            consultas.append(
                f"¿Existe evidencia pública de una relación operacional (obra, proyecto, despacho, cliente) "
                f"entre \"{valor}\" y \"{cliente}\", Chile?"
            )
        if not consultas:
            # Sin dirección ni cliente con qué relacionar el nombre --
            # último recurso: identidad general de la entidad (nunca se
            # inventa una dirección/relación que no se puede preguntar).
            consultas.append(f"\"{valor}\", empresa o proyecto, Chile -- ¿qué evidencia pública existe?")

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
            # Bloque VERIFICACIÓN EXTERNA B1 V1 (Sección 5 -- trazabilidad):
            # `EvidenciaIA` no tiene un campo `fecha` propio (contrato
            # compartido por todas las fuentes, no sólo externas -- no se
            # amplía sólo para esta), pero la fecha/hora REAL de la
            # consulta (`respuesta.fecha`, nunca la de la caché) sigue
            # siendo obligatoria de conservar -- se agrega como una
            # referencia más, mismo lugar donde ya viven las citas/URLs.
            referencias = tuple(f"{c.titulo} <{c.url}>" for c in respuesta.citas if c.url) or (respuesta.consulta,)
            evidencias.append(EvidenciaIA(
                identificador=identificador, campo=contexto.campo,
                valor=respuesta.respuesta_texto.strip()[:600],
                tipo_fuente="EXTERNO", nivel="EXTERNO_WEB",
                independencia=len(respuesta.citas),
                procedencia="atlas_ia.herramientas.verificacion_externa",
                referencias_fuente=(*referencias, f"consultado_en={respuesta.fecha}"),
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
