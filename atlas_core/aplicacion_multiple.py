"""Bloque P0 REVISIÓN RÁPIDA / APLICACIÓN MÚLTIPLE -- caso real: Javier
aplicando histórico MBT en lotes de 15, "Aplicar decisión" tarda ~2 min
por tarjeta porque cada aplicación individual dispara, además de
`aplicar_decision_obra` (necesaria e insustituible: es la que realmente
escribe la decisión), una reconciliación operacional completa
(`reconciliar_estado_derivado`, la batería completa de revalidadores --
ver perfilado real, ~55-60s contra el dataset actual) que Desktop
dispara en segundo plano tras CADA tarjeta y que bloquea la siguiente
acción mientras corre.

V1 (bloque original de este módulo) agrupó la parte fácil y segura:
aplicar N decisiones seguidas paga N aplicaciones (cada una necesaria,
cada una escribe su propia decisión) pero UNA sola
`reconciliar_estado_derivado` al final, nunca N. Prueba real (473880,
2 decisiones OBRA+DESTINO): quedó en ~3 min -- mejor que N
reconciliaciones, pero `aplicar_decision_obra` TODAVÍA dispara, por
DENTRO de cada una de las N aplicaciones, su propia pasada completa de
`revalidar_y_regenerar_reporte` (misma batería global, ~40-60s) para
CUALQUIER decisión que cierre (ver `TIPOS_ELEGIBLES_DIFERIR_
REVALIDACION_GLOBAL`/`diferir_revalidacion_global` en
`aplicacion_decisiones.py`) -- la redundancia real que quedaba.

V2 (PLANIMPACTO AGRUPADO, este bloque) cierra esa brecha SIN
reimplementar ninguna regla: para los tipos ya auditados
(OBRA_DESCONOCIDA/DESTINO_NO_RESUELTO), cada `aplicar_decision_obra` del
lote se llama con `diferir_revalidacion_global=True` -- sigue
escribiendo su propio catálogo/ledger/bandeja exactamente igual, pero
NO corre su propia batería; en cambio devuelve, en
`plan_impacto_diferido`, los mismos insumos (comuna humana / guía a
excluir de reintento) que antes se perdían al recalcularse N veces
independientes. `_construir_plan_impacto_agrupado` deduplica esos
insumos de TODAS las decisiones diferidas del lote en un solo mapa; si
el lote aplicó al menos una, se llama UNA vez a
`revalidar_y_regenerar_reporte` (la misma función de siempre, sin
adaptador ni lógica nueva) con el plan agregado -- nunca una vez por
decisión. Recién después corre, como en V1, la única
`reconciliar_estado_derivado` de cierre del lote (que además puede
saltarse su propia batería compartida si la firma que acaba de publicar
la revalidación agregada sigue fresca -- ver Bloque P1 en
`reconciliacion_estado_derivado.py`).

Decisiones de otros tipos (no auditados para diferir) conservan el
camino de siempre -- cada una sigue disparando su propia
`revalidar_y_regenerar_reporte` dentro de `aplicar_decision_obra`, sin
cambio de comportamiento ni de riesgo.

Nunca aplica una decisión que dejó de estar vigente (recorre el propio
JSON persistido en el momento de arrancar el lote); nunca aborta el
resto del lote porque una decisión falló -- cada resultado es explícito
por decisión (nunca una desaparición silenciosa); cancelar antes de
enviar (lote vacío) nunca escribe nada."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from atlas_core.almacenamiento_portable import SesionOcupadaError
from atlas_core.aplicacion_decisiones import (
    TIPOS_ELEGIBLES_DIFERIR_REVALIDACION_GLOBAL,
    DecisionObsoletaError,
    ErrorAplicacionDecision,
    aplicar_decision_obra,
)

# Mismo contrato de kwargs que `aplicar_decision_obra` -- nunca se
# reinventa qué campos existen por tipo de decisión, sólo se reenvían tal
# cual los que la solicitud haya incluido.
_CAMPOS_APLICACION = (
    "accion", "tipo_vehiculo", "planta_id_elegida", "patente_elegida", "motivo_rechazo",
    "direccion_manual", "comuna_manual", "razon_social_manual", "rut_manual",
    "nombre_obra_manual", "cliente_correccion_manual", "rut_chofer_elegido",
)


@dataclass(frozen=True)
class ResultadoItemMultiple:
    decision_id: str
    archivo: str
    numero_guia: str
    tipo: str
    accion: str
    aplicada: bool
    motivo: str = ""
    mensaje: str = ""

    def a_dict(self) -> dict[str, object]:
        return {
            "decision_id": self.decision_id, "archivo": self.archivo,
            "numero_guia": self.numero_guia, "tipo": self.tipo, "accion": self.accion,
            "aplicada": self.aplicada, "motivo": self.motivo, "mensaje": self.mensaje,
        }


@dataclass(frozen=True)
class ResultadoAplicacionMultiple:
    resultados: list[ResultadoItemMultiple] = field(default_factory=list)
    total_solicitadas: int = 0
    total_aplicadas: int = 0
    reconciliacion_ejecutada: bool = False
    reconciliacion_motivo: str = ""
    # PLANIMPACTO AGRUPADO (V2) -- observabilidad de la revalidación focal
    # agregada: cuántas decisiones diferidas (OBRA_DESCONOCIDA/
    # DESTINO_NO_RESUELTO) entraron al plan y si de verdad se ejecutó una
    # única `revalidar_y_regenerar_reporte` agregada para todas ellas.
    plan_impacto_ejecutado: bool = False
    plan_impacto_guias: int = 0
    plan_impacto_duracion_ms: float = 0.0

    def a_dict(self) -> dict[str, object]:
        return {
            "resultados": [r.a_dict() for r in self.resultados],
            "total_solicitadas": self.total_solicitadas,
            "total_aplicadas": self.total_aplicadas,
            "reconciliacion_ejecutada": self.reconciliacion_ejecutada,
            "reconciliacion_motivo": self.reconciliacion_motivo,
            "plan_impacto_ejecutado": self.plan_impacto_ejecutado,
            "plan_impacto_guias": self.plan_impacto_guias,
            "plan_impacto_duracion_ms": self.plan_impacto_duracion_ms,
        }


def _leer_decisiones_vigentes(raiz: Path) -> dict[str, dict]:
    ruta = raiz / "operacion" / "actual" / "decisiones_pendientes.json"
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return {
        str(d.get("decision_id")): d
        for d in datos.get("decisiones", [])
        if isinstance(d, dict) and d.get("estado") == "PENDIENTE"
    }


def _construir_plan_impacto_agrupado(
    planes_diferidos: list[dict[str, object]],
) -> tuple[dict[str, str], set[str]]:
    """Deduplica los insumos que cada `aplicar_decision_obra` diferida
    habría reenviado, cada una por su cuenta, a su propia
    `revalidar_y_regenerar_reporte` -- ver `comuna_manual_por_guia`/
    `guias_excluir_reintento_ruta` en el docstring de esa función. Nunca
    reinterpreta el valor: sólo agrupa por guía. Dos decisiones del mismo
    lote nunca deberían proponer una comuna distinta para la MISMA guía
    (cada una es dueña de su propio documento); si ocurriera, se conserva
    la última del lote en el orden de aplicación -- nunca se descarta el
    lote completo por eso."""
    comuna_manual_por_guia: dict[str, str] = {}
    guias_excluir_reintento_ruta: set[str] = set()
    for plan in planes_diferidos:
        numero_guia = str(plan.get("numero_guia") or "").strip()
        if not numero_guia:
            continue
        comuna = plan.get("comuna_manual")
        if comuna:
            comuna_manual_por_guia[numero_guia] = str(comuna)
        if plan.get("excluir_reintento_ruta"):
            guias_excluir_reintento_ruta.add(numero_guia)
    return comuna_manual_por_guia, guias_excluir_reintento_ruta


def aplicar_decisiones_multiples(
    *, raiz_atlas: str | Path, solicitudes: list[dict[str, object]],
    actor: str = "JAVIER_DESKTOP", reloj=None, proveedor_rutas: object = None,
    proveedor_rutas_fallback: object = None,
) -> ResultadoAplicacionMultiple:
    """Aplica cada solicitud (mismo contrato que `aplicar_decision_obra`,
    con `decision_id` obligatorio) en el orden recibido. Reutiliza
    `aplicar_decision_obra` sin modificar sus reglas/validaciones (incluida
    su auto-reparación de `dataset_sha256` cuando una decisión anterior de
    este mismo lote ya movió el dataset -- Bloque R11, sin mecanismo
    paralelo).

    PLANIMPACTO AGRUPADO (V2, ver docstring del módulo): para los tipos
    auditados (`TIPOS_ELEGIBLES_DIFERIR_REVALIDACION_GLOBAL`), cada
    aplicación se pide con `diferir_revalidacion_global=True` -- sigue
    escribiendo su propia decisión, sólo pospone su batería global. Los
    insumos que devuelve (`plan_impacto_diferido`) se agregan y, si el
    lote aplicó al menos uno, se revalida UNA vez con el plan conjunto.
    Recién después, y SÓLO SI algo se aplicó de verdad, se reconcilia el
    estado derivado UNA vez al final -- nunca una vez por decisión (V1,
    conservado tal cual)."""
    raiz = Path(raiz_atlas)
    reloj = reloj or (lambda: datetime.now(timezone.utc))
    vigentes_iniciales = _leer_decisiones_vigentes(raiz)
    resultados: list[ResultadoItemMultiple] = []
    algo_aplicado = False
    planes_diferidos: list[dict[str, object]] = []
    for solicitud in solicitudes:
        decision_id = str(solicitud.get("decision_id", "")).strip()
        decision_inicial = vigentes_iniciales.get(decision_id)
        documento = (decision_inicial or {}).get("documento") or {}
        archivo = str(documento.get("archivo", ""))
        numero_guia = str(documento.get("numero_guia", ""))
        tipo = str((decision_inicial or {}).get("tipo", ""))
        accion = str(solicitud.get("accion", ""))
        if decision_inicial is None:
            resultados.append(ResultadoItemMultiple(
                decision_id=decision_id, archivo=archivo, numero_guia=numero_guia,
                tipo=tipo, accion=accion, aplicada=False,
                motivo="La decisión ya no estaba vigente al iniciar la aplicación agrupada "
                       "(fue aplicada o quedó obsoleta antes de este lote).",
            ))
            continue
        kwargs = {campo: solicitud.get(campo) for campo in _CAMPOS_APLICACION}
        diferir = tipo in TIPOS_ELEGIBLES_DIFERIR_REVALIDACION_GLOBAL
        try:
            resultado = aplicar_decision_obra(
                raiz_atlas=raiz, decision_id=decision_id, actor=actor, reloj=reloj,
                proveedor_rutas=proveedor_rutas, proveedor_rutas_fallback=proveedor_rutas_fallback,
                diferir_revalidacion_global=diferir, **kwargs,
            )
            resultados.append(ResultadoItemMultiple(
                decision_id=decision_id, archivo=archivo, numero_guia=numero_guia,
                tipo=tipo, accion=accion, aplicada=True,
                mensaje=str(resultado.get("mensaje", "")),
            ))
            algo_aplicado = True
            plan = resultado.get("plan_impacto_diferido")
            if isinstance(plan, dict):
                planes_diferidos.append(plan)
        except (DecisionObsoletaError, ErrorAplicacionDecision) as error:
            resultados.append(ResultadoItemMultiple(
                decision_id=decision_id, archivo=archivo, numero_guia=numero_guia,
                tipo=tipo, accion=accion, aplicada=False, motivo=str(error),
            ))
        except SesionOcupadaError:
            # Bloque P0 RECUPERACIÓN TRANSACCIONAL -- caso real 0000359449:
            # antes de este fix, un `SesionOcupadaError` (lock legítimamente
            # ocupado, o huérfano-pero-todavía-dentro-de-su-ventana) en
            # CUALQUIER ítem del lote escapaba del `try` de arriba sin
            # capturar -- abortaba el `for` entero, dejando SIN INTENTAR el
            # resto de las solicitudes del lote Y sin correr NUNCA el cierre
            # de abajo (`revalidar_y_regenerar_reporte`/`reconciliar_estado_
            # derivado`) para lo que SÍ se había aplicado hasta ahí. Cada
            # `aplicar_decision_obra` sigue siendo transaccional por su
            # cuenta (revierte sus propios catálogos si falla a mitad,
            # Fase 2 "Regla absoluta") -- este ítem puntual simplemente
            # queda "no aplicada, reintentar" (nunca se inventa que sí se
            # aplicó) y el lote CONTINÚA con el resto, preservando el
            # cierre agregado para las que sí se pudieron aplicar.
            resultados.append(ResultadoItemMultiple(
                decision_id=decision_id, archivo=archivo, numero_guia=numero_guia,
                tipo=tipo, accion=accion, aplicada=False,
                motivo="Otra operación de Atlas está escribiendo esta misma decisión en este momento. "
                       "Vuelve a intentar esta tarjeta en unos segundos.",
            ))

    plan_impacto_ejecutado = False
    plan_impacto_guias = 0
    plan_impacto_duracion_ms = 0.0
    # Bloque P0 EVITAR SEGUNDO INTENTO -- disponible fuera del `if` de
    # abajo: `reconciliar_estado_derivado` (la reconciliación única de
    # cierre del lote, más abajo) también corre revalidadores de ruta
    # propios -- ninguna guía que ya tuvo su intento real en ESTA
    # operación (inline o batería diferida) debe pagar otra consulta ahí.
    guias_excluir_reintento_ruta: set[str] = set()
    if planes_diferidos:
        comuna_manual_por_guia, guias_excluir_reintento_ruta = _construir_plan_impacto_agrupado(planes_diferidos)
        from atlas_core.revalidacion_documental import revalidar_y_regenerar_reporte
        instante = reloj()
        nombre_carpeta = f"reporte_revalidacion_plan_impacto_{instante.strftime('%Y%m%d_%H%M%S_%f')}"
        _t0 = time.perf_counter()
        revalidar_y_regenerar_reporte(
            raiz_atlas=raiz, nombre_carpeta_reporte=nombre_carpeta, reloj=reloj,
            proveedor_rutas=proveedor_rutas, proveedor_rutas_fallback=proveedor_rutas_fallback,
            comuna_manual_por_guia=comuna_manual_por_guia or None,
            guias_excluir_reintento_ruta=guias_excluir_reintento_ruta or None,
        )
        plan_impacto_duracion_ms = round((time.perf_counter() - _t0) * 1000, 1)
        plan_impacto_ejecutado = True
        plan_impacto_guias = len(planes_diferidos)

    reconciliacion_ejecutada = False
    reconciliacion_motivo = ""
    if algo_aplicado:
        from atlas_core.reconciliacion_estado_derivado import reconciliar_estado_derivado
        resultado_reconciliacion = reconciliar_estado_derivado(
            raiz_atlas=raiz, reloj=reloj,
            guias_excluir_reintento_ruta=guias_excluir_reintento_ruta or None,
        )
        reconciliacion_ejecutada = bool(resultado_reconciliacion.get("reconciliado"))
        reconciliacion_motivo = str(resultado_reconciliacion.get("motivo", ""))

    return ResultadoAplicacionMultiple(
        resultados=resultados,
        total_solicitadas=len(solicitudes),
        total_aplicadas=sum(1 for r in resultados if r.aplicada),
        reconciliacion_ejecutada=reconciliacion_ejecutada,
        reconciliacion_motivo=reconciliacion_motivo,
        plan_impacto_ejecutado=plan_impacto_ejecutado,
        plan_impacto_guias=plan_impacto_guias,
        plan_impacto_duracion_ms=plan_impacto_duracion_ms,
    )
