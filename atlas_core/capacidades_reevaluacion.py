"""Registro canónico de CAPACIDADES por dominio + reevaluación retroactiva.

PRINCIPIO: cuando Atlas mejora una capacidad (extracción, identidad de
cliente, relaciones chofer↔vehículo, catálogos, geografía, ...), esa
mejora debe poder beneficiar AUTOMÁTICAMENTE a todos los viajes que sigan
teniendo problemas -- no sólo a las guías nuevas.

Mecanismo mínimo y general (nunca un framework):
  1. se DECLARA el avance subiendo `version` del dominio en
     `REGISTRO_CAPACIDADES`;
  2. `reconciliar_estado_derivado` compara esas versiones contra las
     persistidas en `estado_operacion.json` (`versiones_capacidades`);
  3. si alguna avanzó, ENTRA a su batería -- que ya reúne TODOS los
     revalidadores `_sin_ocr` existentes + convergencia documental +
     segunda pasada universal + reconciliación de bandeja/técnica -- sin
     ejecutar lógica de dominio nueva ni duplicada;
  4. la bandeja/pendientes técnicos se regeneran por el mecanismo
     canónico de siempre;
  5. se deja traza compacta de qué dominio-versión retiró qué pendiente;
  6. es idempotente: una vez estampadas las versiones, la próxima corrida
     no encuentra avance y no hace trabajo.

Este módulo NO resuelve nada por sí mismo. Si una mejora no aporta
evidencia suficiente, el pendiente permanece.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

# Dominios canónicos -- vocabulario cerrado y explícito.
DOMINIO_CLIENTE = "CLIENTE"
DOMINIO_CHOFER = "CHOFER"
DOMINIO_VEHICULO = "VEHICULO"
DOMINIO_OBRA = "OBRA"
DOMINIO_DESTINO = "DESTINO"
DOMINIO_GEOGRAFIA = "GEOGRAFIA"
DOMINIO_ORIGEN = "ORIGEN"
DOMINIO_MATERIAL = "MATERIAL"
DOMINIO_HORARIOS = "HORARIOS"
DOMINIO_ROUTING = "ROUTING"
DOMINIO_EXTRACCION = "EXTRACCION"
DOMINIO_B1 = "B1"
DOMINIO_CATALOGOS = "CATALOGOS"


@dataclass(frozen=True)
class Capacidad:
    """Declara qué gobierna un dominio y en qué versión está su capacidad.

    Al subir `version`, la próxima reconciliación natural reevalúa los
    pendientes de ese dominio (por sus `tipos_decision` / `motivos_
    documentales` / `motivos_tecnicos`) con los revalidadores ya
    existentes. Nunca se listan funciones nuevas aquí: la batería de
    `reconciliar_estado_derivado` ya las corre todas."""

    dominio: str
    version: int
    descripcion: str
    tipos_decision: frozenset[str] = field(default_factory=frozenset)
    motivos_documentales: frozenset[str] = field(default_factory=frozenset)
    # se comparan como PREFIJO de `motivo_actual` de pendientes_tecnicos
    # (p. ej. "COORDENADA_NO_CONFIRMADA(5)" empieza con
    # "COORDENADA_NO_CONFIRMADA").
    motivos_tecnicos: frozenset[str] = field(default_factory=frozenset)


# NOTA DE VERSIONADO: subir un número aquí es la ÚNICA declaración
# necesaria para que una mejora se propague retroactivamente. Los valores
# 2 reflejan mejoras ya entregadas (Bloque AUTORIDAD OPERACIONAL:
# convergencia de identidad + segunda pasada universal + extracción
# general de OBRA DESTINO); el resto arranca en 1.
REGISTRO_CAPACIDADES: dict[str, Capacidad] = {
    DOMINIO_CLIENTE: Capacidad(
        dominio=DOMINIO_CLIENTE, version=2,
        descripcion="Identidad de cliente: RUT canónico, difuso/alias, confirmaciones humanas, convergencia.",
        tipos_decision=frozenset({"CLIENTE_CANDIDATO", "CLIENTE_DESCONOCIDO", "CLIENTE_AUSENTE", "ALIAS_CANDIDATO"}),
        motivos_documentales=frozenset({
            "CLIENTE_SIN_CORROBORAR", "CLIENTE_AUSENTE", "CLIENTE_NUEVA_ENTIDAD_NO_CATALOGADA",
            "CLIENTE_POSIBLEMENTE_INVALIDO", "RUT_CLIENTE_INVALIDO", "RUT_CLIENTE_CONTRADICE_CATALOGO",
        }),
    ),
    DOMINIO_CHOFER: Capacidad(
        dominio=DOMINIO_CHOFER, version=1,
        descripcion="Identidad de chofer y RUT documental.",
        motivos_documentales=frozenset({"CHOFER_SIN_CORROBORAR", "CHOFER_AUSENTE", "RUT_CHOFER_INVALIDO"}),
    ),
    DOMINIO_VEHICULO: Capacidad(
        dominio=DOMINIO_VEHICULO, version=2,
        descripcion="Relaciones chofer↔vehículo, homologación de patente, convergencia.",
        tipos_decision=frozenset({"VEHICULO_DESCONOCIDO"}),
        motivos_documentales=frozenset({"PATENTE_SIN_HOMOLOGAR", "PATENTE_AMBIGUA"}),
    ),
    DOMINIO_OBRA: Capacidad(
        dominio=DOMINIO_OBRA, version=2,
        descripcion="Extracción/catálogo/relaciones de obra destino y convergencia.",
        tipos_decision=frozenset({"OBRA_DESCONOCIDA"}),
        motivos_documentales=frozenset({"OBRA_DESTINO_SIN_CORROBORAR", "OBRA_DESTINO_POSIBLEMENTE_INVALIDA"}),
    ),
    DOMINIO_DESTINO: Capacidad(
        dominio=DOMINIO_DESTINO, version=1,
        descripcion="Relación obra↔destino confirmada y recuperación de destino.",
        tipos_decision=frozenset({"DESTINO_SIN_CONFIRMAR", "DESTINO_NO_RESUELTO"}),
        motivos_documentales=frozenset({"DESTINO_FRAGMENTO_TRUNCADO", "DESTINO_CONTAMINADO_POR_OTRA_SECCION"}),
    ),
    DOMINIO_GEOGRAFIA: Capacidad(
        dominio=DOMINIO_GEOGRAFIA, version=1,
        descripcion="Geocodificación, resolución de calles/comunas, bases locales.",
        tipos_decision=frozenset({"DESTINO_NO_RESUELTO"}),
        motivos_tecnicos=frozenset({
            "GEOCODIFICACION_DIRECCION_NO_ENCONTRADA", "COORDENADA_NO_CONFIRMADA",
            "CONFIANZA_INSUFICIENTE", "GEOCODIFICACION_NUMERO_INCOMPATIBLE",
            "GEOCODIFICACION_CONTRADICE_COMUNA_DOCUMENTAL", "GEOCODIFICACION_DEMASIADO_GENERICA",
            "MULTIPLES_UBICACIONES_DISPERSAS", "SIN_ACCESO_VIAL", "DESTINO_SIN_DATO",
            "GEOCODIFICACION_FUERA_DE_CHILE", "ESPERANDO_EVIDENCIA_NUEVA",
        }),
    ),
    DOMINIO_ORIGEN: Capacidad(
        dominio=DOMINIO_ORIGEN, version=1,
        descripcion="Planta de origen: GPS, Mobile, catálogo, membrete.",
        tipos_decision=frozenset({"ORIGEN_NO_CONFIRMADO"}),
        motivos_tecnicos=frozenset({
            "CONFLICTO_REAL_EN_VENTANA", "DETENCION_REAL_FUERA_DE_TODA_GEOCERCA",
            "CONTRADICCION_OPERACIONAL_ORIGEN", "ENCABEZADO_GUIA_NO_CONFIABLE",
        }),
    ),
    DOMINIO_MATERIAL: Capacidad(
        dominio=DOMINIO_MATERIAL, version=1,
        descripcion="Descripción/peso de material.",
        motivos_documentales=frozenset({"MATERIAL_AUSENTE", "MATERIAL_POSIBLEMENTE_CONTAMINADO"}),
    ),
    DOMINIO_HORARIOS: Capacidad(
        dominio=DOMINIO_HORARIOS, version=1,
        descripcion="Horas de entrada/salida y permanencia.",
        motivos_documentales=frozenset({"FECHA_SIN_CORROBORAR"}),
    ),
    DOMINIO_ROUTING: Capacidad(
        dominio=DOMINIO_ROUTING, version=1,
        descripcion="Cálculo de ruta/km/tiempo (ORS).",
    ),
    DOMINIO_EXTRACCION: Capacidad(
        dominio=DOMINIO_EXTRACCION, version=2,
        descripcion="Extracción OCR/estructural (obra destino, RUT cliente, contaminación de campos).",
    ),
    DOMINIO_B1: Capacidad(
        dominio=DOMINIO_B1, version=2,
        descripcion="Razonamiento B1 + segunda pasada universal sobre decisiones.",
    ),
    DOMINIO_CATALOGOS: Capacidad(
        dominio=DOMINIO_CATALOGOS, version=1,
        descripcion="Catálogos/ledger/relaciones históricas.",
    ),
}


def versiones_actuales() -> dict[str, int]:
    return {d: c.version for d, c in REGISTRO_CAPACIDADES.items()}


def capacidades_avanzadas(persistidas: Mapping[str, object] | None) -> dict[str, tuple[int, int]]:
    """{dominio: (version_persistida, version_actual)} para los dominios
    cuya capacidad avanzó desde la última reconciliación exitosa.

    Un manifiesto que NUNCA estampó `versiones_capacidades` (dict ausente
    o vacío) devuelve `{}`: el primer barrido lo dispara la migración de
    `RULESET_VERSION` (que además cuenta como "todas pudieron avanzar" y
    deja el primer estampado). A partir de ahí, un dominio que se agregue
    al registro más tarde -- clave ausente en un dict YA estampado --
    cuenta como avance desde 0."""
    if not persistidas:
        return {}
    avanzadas: dict[str, tuple[int, int]] = {}
    for dominio, capacidad in REGISTRO_CAPACIDADES.items():
        previa = persistidas.get(dominio, 0)
        try:
            previa = int(previa)
        except (TypeError, ValueError):
            previa = 0
        if previa < capacidad.version:
            avanzadas[dominio] = (previa, capacidad.version)
    return avanzadas


def _motivo_base(motivo: str) -> str:
    texto = str(motivo or "").strip()
    for sep in (":", "(", "["):
        if sep in texto:
            texto = texto[: texto.index(sep)].strip()
    return texto


def dominios_de_decision(tipo: str) -> frozenset[str]:
    return frozenset(
        d for d, c in REGISTRO_CAPACIDADES.items() if tipo in c.tipos_decision
    )


def dominios_de_motivo_tecnico(motivo: str) -> frozenset[str]:
    base = _motivo_base(motivo)
    return frozenset(
        d for d, c in REGISTRO_CAPACIDADES.items()
        if any(base == m or base.startswith(m) for m in c.motivos_tecnicos)
    )


def resumen_reevaluacion(
    *,
    avanzadas: Mapping[str, tuple[int, int]],
    decisiones_antes: list,
    decisiones_despues: list,
    tecnicos_antes: list,
    tecnicos_despues: list,
    duracion_ms: int,
    errores: list | None = None,
) -> dict[str, object]:
    """Traza compacta y estructurada -- qué mejora reevaluó qué, sin
    dashboard. Atribuye cada decisión/pendiente retirado al/los dominio(s)
    que lo gobiernan y que avanzaron."""
    ids_antes = {str(d.get("decision_id")): d for d in decisiones_antes if isinstance(d, dict)}
    ids_despues = {str(d.get("decision_id")) for d in decisiones_despues if isinstance(d, dict)}
    retiradas = [ids_antes[i] for i in ids_antes if i not in ids_despues]

    guias_tec_antes = {str(p.get("numero_guia")): p for p in tecnicos_antes if isinstance(p, dict)}
    guias_tec_despues = {str(p.get("numero_guia")) for p in tecnicos_despues if isinstance(p, dict)}
    tecnicos_retirados = [guias_tec_antes[g] for g in guias_tec_antes if g not in guias_tec_despues]

    por_dominio: dict[str, dict[str, object]] = {}
    for dominio, (prev, nueva) in sorted(avanzadas.items()):
        cap = REGISTRO_CAPACIDADES[dominio]
        dec_scope_antes = [
            d for d in decisiones_antes
            if isinstance(d, dict) and str(d.get("tipo")) in cap.tipos_decision
        ]
        dec_scope_despues = [
            d for d in decisiones_despues
            if isinstance(d, dict) and str(d.get("tipo")) in cap.tipos_decision
        ]
        tec_scope_antes = [
            p for p in tecnicos_antes
            if isinstance(p, dict) and dominio in dominios_de_motivo_tecnico(p.get("motivo_actual", ""))
        ]
        tec_scope_despues = [
            p for p in tecnicos_despues
            if isinstance(p, dict) and dominio in dominios_de_motivo_tecnico(p.get("motivo_actual", ""))
        ]
        dec_retiradas = [
            d for d in retiradas if str(d.get("tipo")) in cap.tipos_decision
        ]
        tec_retirados = [
            p for p in tecnicos_retirados
            if dominio in dominios_de_motivo_tecnico(p.get("motivo_actual", ""))
        ]
        por_dominio[dominio] = {
            "version_previa": prev, "version_nueva": nueva,
            "descripcion": cap.descripcion,
            "decisiones_en_alcance_antes": len(dec_scope_antes),
            "decisiones_en_alcance_despues": len(dec_scope_despues),
            "decisiones_retiradas": len(dec_retiradas),
            "decisiones_retiradas_guias": sorted(
                str((d.get("documento") or {}).get("numero_guia", "")) for d in dec_retiradas
            ),
            "pendientes_tecnicos_en_alcance_antes": len(tec_scope_antes),
            "pendientes_tecnicos_en_alcance_despues": len(tec_scope_despues),
            "pendientes_tecnicos_retirados": len(tec_retirados),
        }

    return {
        "capacidades_avanzadas": {d: {"previa": p, "nueva": n} for d, (p, n) in sorted(avanzadas.items())},
        "dominios_evaluados": sorted(avanzadas.keys()),
        "viajes_pendientes_evaluados": len(
            {str(d.get("decision_id")) for d in decisiones_antes if isinstance(d, dict)}
        ) + len(guias_tec_antes),
        "decisiones_retiradas_total": len(retiradas),
        "pendientes_tecnicos_retirados_total": len(tecnicos_retirados),
        "sin_cambio": len(decisiones_despues) + len(tecnicos_despues),
        "por_dominio": por_dominio,
        "errores": list(errores or []),
        "duracion_ms": int(duracion_ms),
    }
