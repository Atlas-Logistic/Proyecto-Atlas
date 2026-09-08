"""Migraciones ligeras e idempotentes de artefactos operacionales derivados.

No ejecuta OCR, no lee imágenes y no recalcula rutas. El dataset documental y
los catálogos son las fuentes; ``viajes.csv`` y las clasificaciones de ficha
son proyecciones regenerables de esas fuentes.
"""
from __future__ import annotations

import csv
import hashlib
import json
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

from atlas_core.almacenamiento_portable import (
    bloqueo_sesion,
    escribir_json_atomico,
    escribir_estado_operacion,
    leer_estado_operacion,
)
from atlas_core.aplicacion_decisiones import LEDGER
from atlas_core.decisiones_pendientes import NOMBRE_ARTEFACTO
from atlas_core.mobile import RepositorioEnviosMobile, revalidar_asociacion_mobile_sin_ocr
from atlas_core.reporte_viajes import _sha256_archivo, generar_reporte_viajes
from atlas_core.revalidacion_documental import (
    SEPARADOR_MOTIVOS,
    _indicadores_documentales_coherentes,
    reconciliar_bandeja_decisiones,
    reconciliar_decisiones_destino_no_resuelto,
    reconciliar_incidencias_rut_chofer_documental,
    revalidar_destino_contra_comuna_documental_sin_ocr,
    revalidar_destinos_confirmados_sin_coordenadas_sin_ocr,
    revalidar_indicadores_documentales_sin_ocr,
    revalidar_material_estampado_persistido_sin_ocr,
    revalidar_motivo_destino_ya_confirmado_sin_ocr,
    revalidar_obra_destino_sin_ocr,
    revalidar_origen_encabezado_no_confiable_sin_ocr,
    revalidar_origen_por_categoria_sin_candidato_sin_ocr,
    revalidar_ruta_con_destino_confirmado_en_catalogo_sin_ocr,
    revalidar_ruta_sin_destino_calculado_sin_ocr,
)


# Bloque RECONCILIACIÓN POST-DECISIÓN -- causa raíz real (caso 472640,
# confirmada dos veces): la migración de versión es la ÚNICA señal que hace
# que `reconciliar_estado_derivado` vuelva a barrer una operación que YA
# alcanzó la versión vigente (ver `migracion = version_previa <
# RULESET_VERSION`, más abajo) -- un cambio de REGLAS dentro de una misma
# corrida (p. ej. corregir la corroboración que usa `revalidar_motivo_
# destino_ya_confirmado_sin_ocr`, commit efb2067) sin subir este número
# queda INVISIBLE para cualquier operación que ya migró: `migracion` da
# `False`, y si el dataset no cambió por ningún otro motivo (ninguna
# decisión nueva, ningún reintento de ruta vencido), la reconciliación
# entera se aborta temprano (`VERSION_VIGENTE_SIN_REINTENTO_PENDIENTE`) sin
# ejecutar NINGÚN revalidador -- el fix de reglas nunca llega a correr
# contra datos reales hasta que algo más (una decisión humana nueva)
# vuelva a mover el dataset. Éste es el nombre EXPLÍCITO del número que
# hay que subir cada vez que cambian las reglas de cualquier `revalidar_*_
# sin_ocr` invocado desde `reconciliar_estado_derivado` -- no sólo cuando
# cambia el ESQUEMA de los artefactos derivados (`pendientes_tecnicos.json`,
# etc., el motivo original de esta migración). `VERSION_ESTADO_DERIVADO`
# (persistido en `estado_operacion.json`, nombre de campo ya fijado, nunca
# se renombra) sigue siendo exactamente este mismo número -- RULESET_
# VERSION es sólo el nombre que dice qué dispara la migración: CUALQUIER
# cambio de reglas de reconciliación, no sólo un cambio de esquema.
#
# Subida de 3 a 4 -- causa raíz real: la migración a versión 3 ya había
# corrido (y quedado persistida en `estado_operacion.json`) usando la
# corroboración VIEJA de `revalidar_motivo_destino_ya_confirmado_sin_ocr`
# (sólo destino CONFIRMADO en catálogo) ANTES de que el commit efb2067
# agregara la corroboración por `estado_ruta` ya `RUTA_CALCULADA` -- para
# una obra sin ningún destino en catálogo (472640, DSI UNDERGROUND CHILE
# SPA), la reconciliación NUNCA volvió a intentarlo con la regla nueva,
# porque `version_previa` ya no era menor que 3. Subir a 4 dispara, en la
# PRÓXIMA carga natural de Desktop (nunca un reproceso manual de ninguna
# guía puntual), un barrido completo con TODAS las reglas vigentes.
#
# Subida de 4 a 5 -- causa raíz real (viaje 0000355433, guías 472623/
# 472624): la migración a versión 4 ya había corrido y quedado persistida
# ANTES de que este ticket agregara `revalidar_indicadores_documentales_
# sin_ocr` (convergencia única de `indicador_revision`/`estado_documental`/
# `estado_operacional`) y generalizara `revalidar_asociacion_mobile_sin_
# ocr` para resincronizar `estado` aun con la asociación ya resuelta --
# sin subir este número, ambas correcciones de reglas quedarían
# INVISIBLES para cualquier operación ya migrada a 4 (exactamente este
# caso real), tal como advierte el párrafo de arriba.
#
# Subida de 5 a 6 -- bloque previo al lote 2: se conectan aquí
# `revalidar_origen_encabezado_no_confiable_sin_ocr` (caso real 464367,
# AZA RENCA aceptado desde "CASA MATRIZ PLANTA RENCA") y
# `reconciliar_bandeja_decisiones` (Motor de Evidencia -- homologación de
# patente por similitud/historial, alias por RUT exacto, obra por
# evidencia externa) al flujo automático -- antes, ambas sólo corrían
# detrás de un camino de excepción manual (`aplicar_decision_pendiente.py`,
# sólo tras `DecisionObsoletaError`) o de sus propios tests. Una operación
# que ya migró a la versión 5 nunca volvería a barrerse con estas dos
# reglas nuevas sin subir este número, igual que advierte el párrafo de
# arriba.
#
# Subida de 6 a 7 -- ORIGEN: CONVERGER EVIDENCIA ANTES DE PREGUNTAR
# (lote 2, casos reales 464730/464631/464529): conecta aquí
# `revalidar_origen_por_categoria_sin_candidato_sin_ocr` -- ninguna
# pregunta ORIGEN_NO_CONFIRMADO real desaparece hasta que la próxima
# reconciliación natural corra con la regla nueva; sin subir este
# número, una operación ya en versión 6 nunca la vería.
#
# Subida de 7 a 8 -- CONVERGENCIA DE PENDIENTES TÉCNICOS POST LOTE 2
# (casos reales 464395/464367/464265/464588): `detectar_decision_destino_
# no_resuelto` (atlas_core.decisiones_pendientes) amplía su cobertura de
# motivos (`GEOCODIFICACION_DIRECCION_NO_ENCONTRADA`, `DESTINO_REVISAR`
# inmediatos; `COORDENADA_NO_CONFIRMADA` gated por
# `intentos_misma_evidencia >= UMBRAL_INTENTOS_TECNICOS_AGOTADOS`, la
# misma cuenta que este archivo ya escribe en `pendientes_tecnicos.json`)
# -- así el `escalamiento` que se declara aquí al agotar
# `MAX_REINTENTOS_IGUALES_ARRANQUE` deja de ser observabilidad huérfana y
# pasa a tener un consumidor real (una tarjeta `DESTINO_NO_RESUELTO`
# accionable). Una operación que ya migró a 7 nunca volvería a barrerse
# con esta regla nueva sin subir este número, igual que advierte el
# párrafo de arriba.
#
# Subida de 8 a 9 -- CIERRE REAL DE CONVERGENCIA DE DESTINOS (casos
# reales 464588/464395/464740): conecta aquí `revalidar_ruta_con_destino_
# confirmado_en_catalogo_sin_ocr` -- una dirección ya CONFIRMADA por
# Javier en catálogo (con o sin coordenadas propias) es evidencia más
# fuerte que cualquier reintento de geocodificación fresca, y antes no
# se usaba como fuente autoritativa (sólo como corroboración de un
# candidato que el proveedor ya hubiera devuelto). Corre SIEMPRE que se
# entra a este bloque, nunca gated por el cooldown de reintento técnico
# (evidencia humana distinta, no la misma evidencia técnica reintentada).
# Una operación que ya migró a 8 nunca volvería a barrerse con esta regla
# nueva sin subir este número.
#
# Subida de 9 a 10 -- COHERENCIA DE DESTINO CONSOLIDADO (caso real
# 0000351135, 464264+464265): `Viaje.direccion_entrega`/`localidad_
# entrega`/`region_entrega`/`estado_entrega` (atlas_core.gestor_viajes)
# ahora se abstienen (nunca muestran un destino consolidado como
# resuelto) cuando `_bloque_routing_consolidado` -- el mismo que ya
# gobierna `distancia_km`/`estado_ruta` -- indica que el viaje sigue
# bloqueado. Es una corrección de PRESENTACIÓN del reporte (`viajes.csv`,
# generado por `generar_reporte_viajes`/`gestor_viajes.agrupar_viajes`),
# no una regla de detección/decisión -- pero igual sólo se ve reflejada
# la próxima vez que el reporte se regenera; sin subir este número, una
# operación que ya migró a 9 seguiría publicando la ficha incoherente
# hasta que algún OTRO motivo disparara una regeneración.
#
# Subida de 10 a 11 -- VIAJES MULTIGUÍA/MULTICLIENTE/MULTIOBRA (caso real
# 0000352376, 464698/464699/464700): `gestor_viajes.agrupar_viajes` ya no
# genera `CONFLICTO_CLIENTE`/`CONFLICTO_OBRA_DESTINO` por mera diversidad
# de cliente/obra_destino entre documentos del mismo transporte -- un
# mismo viaje físico puede llevar legítimamente varias entregas a
# clientes/obras distintos (ver docstring de `Viaje.clientes`, ya lo
# reconocía). Igual que la subida anterior, es una corrección de
# CLASIFICACIÓN del reporte (`viajes.csv`) -- sin subir este número, una
# operación que ya migró a 10 seguiría marcando REQUIERE_REVISION en
# silencio para un viaje ya sano.
#
# Subida de 11 a 12 -- VENTANA DE PLANTA COMÚN (caso real 0000356848,
# guías 473210/473209, ambas AZA COLINA; Javier verificó que las dos
# fotos muestran la misma hora de entrada y de salida): `gestor_viajes.
# agrupar_viajes` ya no genera `CONFLICTO_HORA_ENTRADA`/
# `CONFLICTO_HORA_SALIDA` cuando una hora sólo difiere porque una guía
# hermana del mismo transporte+planta la leyó como timbre parcial o mal
# asignado de la MISMA ventana `[E, S]` ya leída completa por otra guía
# (`_ventana_planta_comun` -- nunca inventa ni copia horas; una
# discrepancia real, o plantas distintas, conserva la revisión). Igual
# que las dos subidas anteriores, es una corrección de CLASIFICACIÓN del
# reporte (`viajes.csv`) -- sin subir este número, una operación que ya
# migró a 11 seguiría marcando REQUIERE_REVISION por un conflicto de hora
# falso hasta que algún otro motivo regenerara el reporte.
#
# Subida de 12 a 13 -- VALIDACIÓN GEOGRÁFICA + DESTINOS CONFIRMADOS
# COMPLETOS (lote real de 10 guías): (1) `_comuna_documental_inequivoca`
# ahora colapsa "Santiago" usado como etiqueta de área junto a la comuna
# específica -- una geocodificación en otra región (caso 464784: LA
# CISTERNA -> Temuco) ya NO se acepta en silencio (nuevo motivo
# `GEOCODIFICACION_NUMERO_INCOMPATIBLE` para el número de casa espurio);
# (2) `revalidar_destinos_confirmados_sin_coordenadas_sin_ocr` se conecta
# aquí (antes sólo corría tras una decisión / envío Mobile) para que un
# destino CONFIRMADO sin coordenadas (caso 464781) se complete en la
# misma reconciliación del ingreso, y nunca completa un destino con texto
# degradado por OCR (`texto_destino_degradado`, caso 464715). Sin subir
# este número, una operación ya migrada a 12 seguiría publicando una ruta
# a la ciudad equivocada, o un INCOMPLETO_TECNICO transitorio, hasta que
# algo más regenerara el reporte.
#
# Subida de 13 a 14 -- CIERRE OPERACIONAL DE PENDIENTE_TECNICO (casos
# reales 0000353055/464715 y 0000353062/464717): (1) `reconciliar_
# decisiones_destino_no_resuelto` se conecta a esta batería -- un motivo
# de destino que ya es callejón sin salida (`MOTIVOS_DESTINO_NO_RESUELTO`:
# MULTIPLES_UBICACIONES_DISPERSAS, etc.) genera su tarjeta `DESTINO_NO_
# RESUELTO` accionable de inmediato en la carga/drop, sin esperar 3
# reintentos y sin quedar como INCOMPLETO_TECNICO "que se reintenta
# solo"; (2) `revalidar_obra_destino_sin_ocr` se conecta aquí (antes
# sólo tras decisión / envío Mobile) para retirar `OBRA_DESTINO_SIN_
# CORROBORAR` cuando la obra ES la propia sede del cliente (obra ==
# cliente, sin obra homónima real de otro cliente). Sin subir este
# número, 464715 seguiría sin tarjeta y 464717 seguiría bloqueado hasta
# que algo más regenerara el reporte.
#
# Subida de 14 a 15 -- mismo bloque, segunda corrección: `reconciliar_
# decisiones_destino_no_resuelto` ahora pasa `ruta_dataset` a
# `regenerar_decisiones_persistidas` para que la supresión "la obra ya
# tiene un destino confirmado que coincide con el texto" NO silencie una
# tarjeta cuando el `motivo_ruta` VIGENTE de la fila sigue siendo un
# callejón sin salida de destino (caso real 464715: Javier confirmó "AV.
# VICUÑA MACKENNA 3451 ..." el 17-08, pero ese texto sigue geocodificando
# a múltiples ubicaciones dispersas -- la pregunta sigue viva). Sin subir
# el número, las tarjetas de 464715/464740/464784/464395 seguirían
# suprimidas en una operación ya migrada a 14.
#
# Subida de 15 a 16 -- RECUPERACIÓN DETERMINÍSTICA DE DESTINO POR HISTORIAL
# TAMBIÉN PARA FILAS HISTÓRICAS (caso real 464836 / viaje 0000353361, obra
# == cliente == "AMERICAN SCREW CHILE SPA"): `_resolver_destinos_
# contaminados_por_historial` (procesamiento_masivo) ya reconstruía un
# destino contaminado ("14293816-2 FECHA LLEGADA 17-08-2026") a partir de
# guías hermanas independientes que convergen sin conflicto en un mismo
# destino confiable y una misma ruta ya calculada -- pero SÓLO se invocaba
# al terminar un lote nuevo, con `archivos_procesados_ahora`. Una fila ya
# existente que quedó contaminada antes de que su propio historial
# convergiera nunca volvía a entrar a ese paso. Ahora se conecta a esta
# batería: selecciona las filas con `DESTINO_CONTAMINADO_POR_OTRA_SECCION`
# vigente y aplica EXACTAMENTE sus gates normales (>=2 guías
# independientes, un único destino confiable, una única ruta para el mismo
# origen; cualquier divergencia se abstiene). No crea decisiones, no lee
# OCR, no relaja ningún gate. Sin subir este número, 464836 seguiría con
# su tarjeta `DESTINO_NO_RESUELTO` hasta que un lote nuevo lo incluyera.
RULESET_VERSION = 16
VERSION_ESTADO_DERIVADO = RULESET_VERSION
NOMBRE_PENDIENTES_TECNICOS = "pendientes_tecnicos.json"
INTERVALO_REINTENTO = timedelta(hours=24)
MAX_REINTENTOS_IGUALES_ARRANQUE = 3


def _leer_filas(ruta: Path) -> list[dict[str, str]]:
    with ruta.open("r", newline="", encoding="utf-8-sig") as archivo:
        return list(csv.DictReader(archivo, delimiter=";"))


def _guias_humanas(decisiones: Path) -> set[str]:
    try:
        contenido = json.loads(decisiones.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    return {
        str((d.get("documento") or {}).get("numero_guia", "")).strip()
        for d in contenido.get("decisiones", []) if d.get("estado") == "PENDIENTE"
    }


def _huella_ruta(fila: dict[str, str]) -> str:
    campos = (
        "planta_origen_id", "despachar_a_crudo", "cliente", "obra_destino",
        "destino_id", "motivo_ruta", "resultado_atlas_ia_json",
    )
    return hashlib.sha256("\0".join(str(fila.get(c, "")) for c in campos).encode("utf-8")).hexdigest()


def _cargar_seguimiento(ruta: Path) -> dict[str, dict[str, object]]:
    try:
        contenido = json.loads(ruta.read_text(encoding="utf-8"))
        return {str(p["numero_guia"]): p for p in contenido.get("pendientes", [])}
    except (OSError, ValueError, KeyError, TypeError):
        return {}


def _pendientes_ruta(dataset: Path, decisiones: Path) -> list[dict[str, str]]:
    # Bloque ORIGEN V3 -- CONVERGENCIA DE EVIDENCIA ANTES DE PREGUNTAR:
    # `estado_ruta==""` con `planta_origen_id` YA presente es exactamente
    # el estado que dejan los revalidadores de origen por categoría
    # (éste y su hermano R2.3, `revalidar_origen_por_eliminacion_
    # categoria_sin_ocr`) -- origen resuelto, ruta todavía sin calcular.
    # Excluirlo aquí (como antes) dejaba estas filas fuera de la única
    # cola de reintento que corre en la carga automática de Desktop
    # (`reconciliar_estado_derivado`, la otra vía --
    # `revalidar_y_regenerar_reporte` -- sólo corre dentro de una
    # aplicación de decisión o de un envío Mobile, nunca sólo al abrir
    # Desktop): origen resuelto, pero sin ninguna vía automática que
    # calculara nunca su ruta. Una fila persistida SIEMPRE llega a este
    # dataset con un `estado_ruta` real (nunca "" de fábrica) -- "" sólo
    # existe porque un revalidador lo dejó así a propósito, esperando
    # este mismo reintento.
    humanas = _guias_humanas(decisiones)
    return [
        f for f in _leer_filas(dataset)
        if str(f.get("numero_guia", "")).strip() not in humanas
        and str(f.get("indicador_revision", "")).strip() == "OK"
        and str(f.get("estado_ruta", "")).strip() != "RUTA_CALCULADA"
        and str(f.get("planta_origen_id", "")).strip()
        and str(f.get("despachar_a_crudo", "")).strip()
    ]


def _registro_pendiente(fila: dict[str, str], previo: dict[str, object] | None) -> dict[str, object]:
    huella = _huella_ruta(fila)
    mismo = previo if previo and previo.get("huella_datos") == huella else None
    return {
        "numero_guia": str(fila.get("numero_guia", "")).strip(),
        "dependencia_fallida": "GEOCODIFICACION_ROUTING",
        "resultado_pendiente": "DIRECCION_ENTREGA_KM_TIEMPO",
        "motivo_actual": str(fila.get("motivo_ruta", "")).strip(),
        "reintentable": True,
        "datos_disponibles": {
            "planta_origen_id": str(fila.get("planta_origen_id", "")).strip(),
            "destino_documental": str(fila.get("despachar_a_crudo", "")).strip(),
            "cliente": str(fila.get("cliente", "")).strip(),
            "obra": str(fila.get("obra_destino", "")).strip(),
            "evidencia_b1_persistida": bool(str(fila.get("resultado_atlas_ia_json", "")).strip()),
        },
        "huella_datos": huella,
        "intentos_misma_evidencia": int((mismo or {}).get("intentos_misma_evidencia", 0)),
        "ultimo_intento": (mismo or {}).get("ultimo_intento"),
        "ultimo_resultado": (mismo or {}).get("ultimo_resultado"),
        "historial_resultados": list((mismo or {}).get("historial_resultados", [])),
        "proxima_oportunidad": "ARRANQUE_TRAS_24H_O_CAMBIO_DE_EVIDENCIA",
        "escalamiento": "PROXIMA_CORRIDA_GUIAS_REVALIDACION_GLOBAL_B1" if int((mismo or {}).get("intentos_misma_evidencia", 0)) >= MAX_REINTENTOS_IGUALES_ARRANQUE else "REINTENTO_DEPENDENCIA",
    }


_ESTADOS_REVISION = {"REVISAR", "REQUIERE_REVISION"}


def _estado_derivado_incoherente(dataset: Path) -> bool:
    """``True`` si alguna fila del dataset arrastra un estado de revisión
    TÉCNICO que ya no corresponde: `indicador_revision`/`estado_documental`/
    `estado_operacional` persistidos siguen pidiendo revisión, pero la
    coherencia canónica (`motivos_revision_documento` YA reconciliado +
    `estado_ruta` YA calculado -- misma fuente y mismo criterio que
    `revalidar_indicadores_documentales_sin_ocr`) da `OK` para ese mismo
    campo.

    Es exactamente el estado que deja "el pendiente técnico se fijó cuando
    todavía faltaba routing y la ruta se resolvió en una reconciliación
    posterior, sin que nadie volviera a derivar el estado del
    documento/viaje" (caso real 0000356332). Esta señal existe para que
    esa fila NO quede stale hasta que algún OTRO motivo (una decisión
    humana, un envío Mobile, una migración de `RULESET_VERSION`) vuelva a
    mover el dataset -- igual que `reporte_desactualizado`, pero para la
    incoherencia INTERNA de una fila, no para el reporte publicado.

    Sólo mira en la dirección de CONVERGER (revisión stale -> OK): nunca
    marca incoherente una fila que pide MENOS revisión que la canónica
    (esa dirección la resuelve, bidireccional,
    `revalidar_indicadores_documentales_sin_ocr` cuando ya se entra al
    bloque por cualquier otra vía) -- así un motivo humano/documental real
    (p. ej. `OBRA_DESTINO_SIN_CORROBORAR`, caso 0000356848) mantiene su
    fila en revisión y jamás dispara esto. No lee OCR ni recalcula rutas:
    sólo relee el dataset ya persistido."""
    try:
        filas = _leer_filas(dataset)
    except (OSError, ValueError):
        return False
    for fila in filas:
        motivos = [m for m in str(fila.get("motivos_revision_documento", "")).split(SEPARADOR_MOTIVOS) if m]
        estado_ruta = str(fila.get("estado_ruta", "")).strip()
        coherentes = _indicadores_documentales_coherentes(motivos, estado_ruta)
        for campo, coherente in zip(
            ("indicador_revision", "estado_documental", "estado_operacional"), coherentes,
        ):
            if str(fila.get(campo, "")).strip() in _ESTADOS_REVISION and coherente == "OK":
                return True
    return False


def _falta_tarjeta_destino_accionable(dataset: Path, decisiones: Path) -> bool:
    """``True`` si alguna fila ya es un callejón de DESTINO reconocido
    (`motivo_ruta` base en `MOTIVOS_DESTINO_NO_RESUELTO`: número
    incompatible, contradice comuna, múltiples ubicaciones, etc.) -- origen
    resuelto, ruta sin calcular -- pero NO tiene todavía una decisión
    `DESTINO_NO_RESUELTO` pendiente que la vuelva accionable en Revisión de
    Atlas.

    Bloque CIERRE QUIRÚRGICO DE REVISIONES -- caso real 464784 (URUGUAY 15):
    Javier registró la dirección, el reintento inmediato la reconcilió a un
    motivo real y estable (`GEOCODIFICACION_NUMERO_INCOMPATIBLE`), pero la
    tarjeta quedó suprimida por "la obra ya tiene destino CONFIRMADO" --
    dejando la fila como pendiente técnico invisible que NUNCA se
    autorresuelve (el proveedor seguirá devolviendo 1545). `reconciliar_
    estado_derivado` abortaba antes de llegar a `reconciliar_decisiones_
    destino_no_resuelto` porque `migracion`/`por_reintentar`/`reporte_
    desactualizado`/`estado_derivado_incoherente` daban todos `False`.
    Este disparador -- misma clase que `estado_derivado_incoherente` --
    hace entrar al bloque para que esa tarjeta se publique.
    `_pendientes_ruta` ya excluye guías humanas, filas con ruta calculada
    y filas sin planta/despachar_a, así que sólo se mira lo que de verdad
    quedó atrapado. Idempotente: una vez publicada la tarjeta,
    `_guias_humanas` la incluye y este disparador deja de verla. Una guía
    cuya tarjeta de destino ya fue resuelta de forma TERMINAL por un
    humano (`NO_PUEDO_DETERMINAR`/`NO_CONFIRMAR` en el ledger --
    `reconciliar_decisiones_destino_no_resuelto` nunca la republicaría) se
    excluye también: reintentar la reconciliación en cada carga sin poder
    publicar nada sería un bucle inútil."""
    from atlas_core.decisiones_pendientes import MOTIVOS_DESTINO_NO_RESUELTO

    guias_destino_terminadas: set[str] = set()
    try:
        _ledger = json.loads((dataset.parent / "decisiones_aplicadas.json").read_text(encoding="utf-8"))
        for _ap in _ledger.get("aplicaciones", []) or []:
            if _ap.get("tipo") == "DESTINO_NO_RESUELTO" and _ap.get("accion") in {
                "NO_PUEDO_DETERMINAR", "NO_CONFIRMAR",
            }:
                _g = str((_ap.get("documento") or {}).get("numero_guia", "")).strip()
                if _g:
                    guias_destino_terminadas.add(_g)
    except (OSError, ValueError):
        pass

    for fila in _pendientes_ruta(dataset, decisiones):
        if str(fila.get("numero_guia", "")).strip() in guias_destino_terminadas:
            continue
        motivo_base = str(fila.get("motivo_ruta", "")).split(":", 1)[0].split("(", 1)[0].strip()
        if motivo_base in MOTIVOS_DESTINO_NO_RESUELTO:
            return True
    return False


def reconciliar_estado_derivado(
    *, raiz_atlas: str | Path, reloj=lambda: datetime.now(timezone.utc),
    proveedor_rutas=None, proveedor_rutas_fallback=None,
) -> dict[str, object]:
    """Actualiza una operación antigua una sola vez por RULESET_VERSION.

    `migracion` (más abajo) sólo se dispara si `version_previa <
    RULESET_VERSION` -- CUALQUIER cambio a las reglas de alguno de los
    `revalidar_*_sin_ocr` invocados aquí (no sólo un cambio de esquema de
    los artefactos derivados) exige subir `RULESET_VERSION`; de lo
    contrario, una operación que ya alcanzó la versión vigente nunca
    vuelve a ejecutar la regla corregida hasta que algo MÁS mueva el
    dataset (ver docstring de `RULESET_VERSION`, caso real 472640)."""
    raiz = Path(raiz_atlas)
    actual = raiz / "operacion" / "actual"
    dataset = actual / "analisis_completo_guias.csv"
    catalogos = raiz / "catalogos_privados"
    estado_previo = leer_estado_operacion(raiz=raiz) or {}
    version_previa = int(estado_previo.get("version_estado_derivado", 0) or 0)
    if not dataset.is_file():
        return {"reconciliado": False, "motivo": "SIN_DATASET", "version": version_previa}

    instante = reloj().astimezone(timezone.utc)
    sello = instante.strftime("%Y%m%d_%H%M%S_%f")
    respaldo = raiz / "respaldos" / f"reconciliacion_estado_derivado_v{VERSION_ESTADO_DERIVADO}_{sello}"
    reporte = raiz / "reportes" / f"reporte_desktop_reconciliado_v{VERSION_ESTADO_DERIVADO}_{sello}"
    estado_ruta = actual / "estado_operacion.json"
    decisiones = actual / NOMBRE_ARTEFACTO
    ruta_pendientes = actual / NOMBRE_PENDIENTES_TECNICOS
    seguimiento_previo = _cargar_seguimiento(ruta_pendientes)
    pendientes_antes = _pendientes_ruta(dataset, decisiones)
    registros = [_registro_pendiente(f, seguimiento_previo.get(str(f.get("numero_guia", "")))) for f in pendientes_antes]
    por_reintentar = []
    for registro in registros:
        ultimo = registro.get("ultimo_intento")
        vencido = True
        if ultimo:
            try:
                vencido = instante - datetime.fromisoformat(str(ultimo)) >= INTERVALO_REINTENTO
            except ValueError:
                pass
        if registro["intentos_misma_evidencia"] < MAX_REINTENTOS_IGUALES_ARRANQUE and vencido:
            por_reintentar.append(str(registro["numero_guia"]))
    migracion = version_previa < RULESET_VERSION
    # Bloque R2.5 -- PROYECCIÓN CANÓNICA -> OPERACIÓN: caso real 464264
    # (decisión humana aplicada; "Revisión de Atlas" ya reflejaba 0
    # decisiones, pero `viajes.csv` seguía siendo el snapshot generado
    # ANTES de la decisión -- Desktop mostraba "Destino operacional: No
    # disponible" y el km/tiempo del destino ANTERIOR indefinidamente,
    # porque nada volvía a llamar `generar_reporte_viajes` fuera de un
    # drop de imágenes nuevas). El dataset puede cambiar por muchas vías
    # que no son "migración" ni "reintento de ruta vencido" (cualquier
    # decisión humana vía `aplicar_decision_obra`, cualquier revalidación
    # `_sin_ocr`) -- comparar la huella del dataset contra la huella que
    # el ÚLTIMO `reporte_vigente` publicado registró es la señal general,
    # sin polling: se evalúa en la misma oportunidad de reconciliación
    # natural que ya dispara cada carga de Desktop.
    huella_dataset_actual = _sha256_archivo(dataset)
    reporte_desactualizado = huella_dataset_actual != estado_previo.get("dataset_sha256")
    # Bloque CONVERGENCIA DE ESTADO TÉCNICO STALE -- causa raíz real (viaje
    # 0000356332, guías 477145/477146): un pendiente técnico
    # (`estado_documental`/`estado_operacional` = `REQUIERE_REVISION`) se
    # fijó cuando todavía faltaba routing; una reconciliación posterior
    # resolvió origen+ruta (`estado_ruta` = `RUTA_CALCULADA`, sin motivo
    # documental real), pero el estado derivado del documento/viaje quedó
    # sin recalcular y ninguna vía automática lo tocaba: `migracion` da
    # `False` (versión ya vigente), `por_reintentar` está vacío (la ruta
    # YA está calculada, `_pendientes_ruta` la excluye) y
    # `reporte_desactualizado` da `False` (el dataset no volvió a cambiar
    # tras la última publicación). La fila quedaba stale hasta que algún
    # OTRO motivo moviera el dataset. `_estado_derivado_incoherente` es la
    # misma clase de disparador que `reporte_desactualizado`, pero para la
    # incoherencia INTERNA de una fila -- al entrar al bloque,
    # `revalidar_indicadores_documentales_sin_ocr` (más abajo, AL FINAL)
    # converge los tres campos desde lo canónico y se republica el
    # reporte; el viaje deja de ser `INCOMPLETO_TECNICO`. Idempotente: una
    # vez convergida, la siguiente corrida ya no lo detecta.
    estado_derivado_incoherente = _estado_derivado_incoherente(dataset)
    # Bloque CIERRE QUIRÚRGICO DE REVISIONES -- caso real 464784: una fila
    # que ya es un callejón de DESTINO reconocido pero sin tarjeta
    # accionable todavía (quedó como pendiente técnico invisible) también
    # debe hacer entrar al bloque -- `reconciliar_decisiones_destino_no_
    # resuelto` (AL FINAL) publica su tarjeta. Misma clase de disparador
    # que `estado_derivado_incoherente`; idempotente.
    falta_tarjeta_destino = _falta_tarjeta_destino_accionable(dataset, decisiones)
    if (
        not migracion and not por_reintentar and not reporte_desactualizado
        and not estado_derivado_incoherente and not falta_tarjeta_destino
    ):
        return {
            "reconciliado": False, "motivo": "VERSION_VIGENTE_SIN_REINTENTO_PENDIENTE",
            "version": version_previa, "pendientes_tecnicos": len(registros),
        }

    with bloqueo_sesion(actual, "reconciliacion_estado_derivado"):
        # Bloque CONSISTENCIA OPERACIONAL, Fase 2 -- este lock ya NO
        # protege el dataset (sus escritores reales son las
        # revalidaciones `_sin_ocr` de abajo, cada una atómica y
        # protegida por su PROPIO lock común, "revalidacion_dataset" --
        # ver más abajo). Sigue existiendo para que dos reconciliaciones
        # completas no corran en paralelo pisándose sus propios
        # artefactos (`pendientes_tecnicos.json`, la carpeta de reporte,
        # `estado_operacion.json`) -- una transacción de negocio, igual
        # que el lock exterior de `aplicar_decision_obra`.
        respaldo.mkdir(parents=True, exist_ok=False)
        # El respaldo se conserva como AUDITORÍA/histórico -- NUNCA como
        # fuente para restaurar el dataset a ciegas (ver la Regla
        # absoluta del bloque: nunca reponer una copia vieja del dataset
        # si otro escritor real pudo haberlo modificado desde el
        # snapshot). `estado_operacion.json` tampoco se restaura desde
        # acá -- ver por qué en el `except` de más abajo.
        shutil.copy2(dataset, respaldo / dataset.name)
        if estado_ruta.is_file():
            shutil.copy2(estado_ruta, respaldo / estado_ruta.name)
        if decisiones.is_file():
            shutil.copy2(decisiones, respaldo / decisiones.name)
        if ruta_pendientes.is_file():
            shutil.copy2(ruta_pendientes, respaldo / ruta_pendientes.name)
        (respaldo / "manifest.json").write_text(json.dumps({
            "version_origen": version_previa,
            "version_destino": VERSION_ESTADO_DERIVADO,
            "creado_en": instante.isoformat(),
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        # Un documento ya existente puede haber quedado contaminado antes
        # de que el historial independiente convergiera. La recuperación
        # determinística ya usada al terminar un lote nuevo debe correr
        # también durante la reconciliación: selecciona sólo filas con el
        # motivo documental vigente y aplica exactamente sus gates normales
        # (dos guías independientes, un único destino confiable y una única
        # ruta para el mismo origen). No crea decisiones ni usa OCR.
        from atlas_core.procesamiento_masivo import (
            MotivoRevisionDocumento,
            _resolver_destinos_contaminados_por_historial,
        )
        with dataset.open("r", newline="", encoding="utf-8-sig") as archivo_dataset:
            archivos_destino_contaminado = {
                str(fila.get("archivo", "")).strip()
                for fila in csv.DictReader(archivo_dataset, delimiter=";")
                if str(fila.get("archivo", "")).strip()
                and MotivoRevisionDocumento.DESTINO_CONTAMINADO_POR_OTRA_SECCION.value
                in {
                    motivo.strip()
                    for motivo in str(fila.get("motivos_revision_documento", "")).split("|")
                    if motivo.strip()
                }
            }
        recuperacion_historial_destino = _resolver_destinos_contaminados_por_historial(
            dataset, archivos_destino_contaminado,
        )

        # Bloque RECONCILIACIÓN POST-DECISIÓN -- caso real 472640: estas
        # tres revalidaciones NUNCA leen OCR ni recalculan ruta -- sólo
        # reconcilian flags/estados derivados YA obsoletos contra reglas
        # ya vigentes (motivo documental de destino ya confirmado por una
        # decisión humana o por catálogo; material que en verdad fusiona
        # varios ítems reales o trae un sello pegado; asociación/estado de
        # un envío Mobile cuyo propio documento ya tiene fila fresca en el
        # dataset). Antes corrían SÓLO durante una migración de versión
        # (`if migracion:`) -- la primera vez que Javier confirmó una
        # dirección real (472640) y Atlas recalculó km/tiempo
        # correctamente, el viaje seguía mostrando "Pendiente técnico" y
        # el envío Mobile seguía "sin asociación" pidiendo "Confirmar
        # viaje", porque nada volvía a mirar estos tres flags en la MISMA
        # reconciliación que ya corre automáticamente en cada carga de
        # Desktop. Corren siempre que se entra a este bloque (migración,
        # reintento de ruta vencido, o simplemente el dataset avanzó por
        # cualquier decisión humana) -- nunca sólo una vez por versión.
        limpieza = revalidar_motivo_destino_ya_confirmado_sin_ocr(
            ruta_dataset=dataset, carpeta_catalogos=catalogos,
        )
        # Bloque VALIDACIÓN GEOGRÁFICA OBLIGATORIA -- caso real 464784: un
        # destino ya persistido cuya localidad geocodificada contradice la
        # comuna documental inequívoca (LA CISTERNA vs Temuco), o cuyo
        # número de casa es incompatible por orden de magnitud, se retira
        # (nunca se deja un viaje CONFIRMADO con km/tiempo a la ciudad
        # equivocada). `revalidar_y_regenerar_reporte` ya lo hacía; aquí
        # se conecta también a la reconciliación de la carga de Desktop
        # (única vía del ingreso de un lote). Sin OCR, sin red -- sólo
        # columnas ya escritas.
        limpieza_geo_contradiccion = revalidar_destino_contra_comuna_documental_sin_ocr(ruta_dataset=dataset)
        limpieza_material = revalidar_material_estampado_persistido_sin_ocr(ruta_dataset=dataset)
        # Bloque ENTREGA A SEDE DEL PROPIO CLIENTE -- caso real 0000353062/
        # 464717 (cliente == obra_destino == "AMERICAN SCREW CHILE SPA",
        # ruta 35 km calculada): `revalidar_obra_destino_sin_ocr` ya retira
        # `OBRA_DESTINO_SIN_CORROBORAR` cuando `obra_destino` normaliza
        # EXACTO al `cliente` de la misma fila ("el mismo hecho dos veces")
        # o cuando el catálogo lo resuelve -- pero SÓLO se invocaba desde
        # `revalidar_y_regenerar_reporte` (decisión / envío Mobile). Aquí
        # se conecta también a la reconciliación de la carga de Desktop /
        # ingreso de un lote. Sin OCR, sin red.
        limpieza_obra_destino = revalidar_obra_destino_sin_ocr(
            ruta_dataset=dataset, carpeta_catalogos=catalogos, ruta_ledger=actual / LEDGER,
        )
        # Bloque CORRECCIÓN ESTRUCTURAL DE ORIGEN DOCUMENTAL AZA -- causa
        # raíz real (464367): un origen que quedó determinado ÚNICAMENTE
        # por `evidencia_origen="ENCABEZADO_GUIA"` (membrete/casa matriz
        # societaria, nunca la planta real de despacho) nunca se
        # revertía sola -- esta función existía y estaba probada, pero
        # ningún flujo automático la invocaba. Corre ANTES del reintento
        # de ruta y de la convergencia de indicadores de abajo, para que
        # un origen recién invalidado (vuelve a `ORIGEN_NO_DETERMINADO`)
        # se refleje de inmediato en `estado_operacional`, nunca con un
        # ciclo de rezago.
        limpieza_origen = revalidar_origen_encabezado_no_confiable_sin_ocr(ruta_dataset=dataset)
        # Bloque ORIGEN V3 -- CONVERGENCIA DE EVIDENCIA ANTES DE PREGUNTAR
        # -- causa raíz sistémica real (lote 2: 464730, 464631, 464529):
        # antes de dejar un origen sin determinar (o de dejarlo así
        # después de revertir un encabezado no confiable, arriba mismo),
        # cruza categoría real de la carga + naturaleza del destino
        # (externo vs. la propia planta) contra el catálogo -- corre
        # ANTES del reintento de ruta para que la misma pasada calcule
        # km/tiempo con el origen ya resuelto.
        limpieza_origen_categoria = revalidar_origen_por_categoria_sin_candidato_sin_ocr(
            ruta_dataset=dataset, carpeta_catalogos=catalogos,
        )
        # Bloque FIX RUT AUSENTE -- caso real 464367 (CARLOS ÑANCUCHEO):
        # un chofer identificado por nombre pero sin RUT documental
        # (ausente o inválido) puede tener RUT canónico confiable en
        # catálogo o en el histórico del propio dataset -- función ya
        # existente y probada, sin flujo automático que la invocara.
        limpieza_rut_chofer = reconciliar_incidencias_rut_chofer_documental(raiz_atlas=raiz, reloj=lambda: instante)
        # Bloque DESTINOS CONFIRMADOS COMPLETOS -- causa raíz real
        # (0000353312/464781): un destino CONFIRMADO en catálogo cuya
        # confirmación nunca llegó a geocodificar queda con `lat/lon`
        # None, así que cada guía a esa obra re-geocodifica en la carga de
        # Desktop y su 1er reporte la muestra INCOMPLETO_TECNICO hasta que
        # `revalidar_ruta_con_destino_confirmado_en_catalogo_sin_ocr` (más
        # abajo) la resuelve. Esta función ya existía y estaba probada,
        # pero SÓLO se invocaba desde `revalidar_y_regenerar_reporte`
        # (aplicación de decisión / envío Mobile), nunca desde la
        # reconciliación de la carga de Desktop -- que es exactamente
        # donde el ingreso de un lote la necesita. Corre ANTES del bloque
        # de catálogo de abajo, para que ese ya use las coordenadas recién
        # completadas. Nunca completa un destino con texto degradado por
        # OCR (`texto_destino_degradado`, caso 464715).
        limpieza_destino_coords = revalidar_destinos_confirmados_sin_coordenadas_sin_ocr(
            carpeta_catalogos=catalogos, proveedor_rutas=proveedor_rutas,
        )
        # Bloque CIERRE REAL DE CONVERGENCIA DE DESTINOS -- causa raíz
        # real (464588/464395/464740): una dirección ya CONFIRMADA por
        # Javier en catálogo (con o sin coordenadas propias) es evidencia
        # MÁS fuerte que cualquier reintento de geocodificación fresca --
        # corre SIEMPRE que se entra a este bloque (mismo criterio que
        # las revalidaciones de arriba), nunca gated por el cooldown de
        # `por_reintentar`/`MAX_REINTENTOS_IGUALES_ARRANQUE` (ese cooldown
        # gobierna reintentos de la MISMA evidencia técnica -- esta es
        # evidencia DISTINTA, ya humana, que debe converger en cuanto
        # exista, sin esperar 24h). Corre ANTES del reintento de ruta de
        # abajo para que una fila que converge aquí nunca vuelva a
        # gastar un intento técnico en el proveedor externo en la misma
        # pasada.
        limpieza_destino_catalogo = revalidar_ruta_con_destino_confirmado_en_catalogo_sin_ocr(
            ruta_dataset=dataset, carpeta_catalogos=catalogos,
            proveedor_rutas=proveedor_rutas, proveedor_rutas_fallback=proveedor_rutas_fallback,
        )
        recuperacion = {"guias_actualizadas": []}
        if por_reintentar:
            recuperacion = revalidar_ruta_sin_destino_calculado_sin_ocr(
                ruta_dataset=dataset, carpeta_catalogos=catalogos,
                proveedor_rutas=proveedor_rutas,
                proveedor_rutas_fallback=proveedor_rutas_fallback,
                guias_objetivo=set(por_reintentar),
            )
        # Bloque CONVERGENCIA DE ESTADO -- causa raíz sistémica real (viaje
        # 0000355433, guías 472623/472624): esta reconciliación (y también
        # `revalidar_y_regenerar_reporte`, la otra vía por la que un motivo
        # puede retirarse, p. ej. patente ya homologada) puede dejar
        # `motivos_revision_documento`/`estado_ruta` ya al día pero
        # `indicador_revision`/`estado_documental`/`estado_operacional`
        # desincronizados -- cada revalidación de motivo (arriba, y las que
        # corren fuera de este archivo) reimplementaba ese cálculo por su
        # cuenta, algunas de forma incompleta. Corre AL FINAL, una sola vez,
        # sobre el estado YA definitivo de esta pasada (después del retiro
        # de motivos Y del reintento de ruta) -- nunca decide si un motivo
        # sigue vigente, sólo hace que los tres campos deriven siempre de
        # esa misma fuente ya canónica.
        limpieza_indicadores = revalidar_indicadores_documentales_sin_ocr(ruta_dataset=dataset)
        # Mobile debe leer el indicador YA convergido en esta misma
        # pasada. Si corriera antes, una fila con motivos canónicos
        # resueltos pero `indicador_revision` todavía obsoleto seguiría
        # dejando el envío en REQUIERE_REVISION; como el reporte publica
        # después la huella fresca, podría no existir una segunda pasada
        # natural que lo corrigiera.
        limpieza_mobile = revalidar_asociacion_mobile_sin_ocr(
            RepositorioEnviosMobile(raiz_atlas=raiz), dataset=dataset,
        )
        # Bloque MOTOR DE EVIDENCIA -- causa raíz real (T2MN86/J35478,
        # 464529 alias TORRES OCARANEA): `reconciliar_bandeja_decisiones`
        # (catálogo + similitud OCR calibrada + historial RUT/transporte
        # para patentes; RUT exacto para alias; evidencia externa
        # oficial/corporativa para obras) existía completo y probado,
        # pero sólo se invocaba detrás de un camino de excepción manual
        # (`aplicar_decision_pendiente.py`, sólo tras
        # `DecisionObsoletaError`). Corre AL FINAL de esta pasada, sobre
        # el dataset YA reconciliado arriba (motivos/ruta/origen/mobile),
        # para que la evidencia que usa (p. ej. `estado_ruta` ya
        # `RUTA_CALCULADA`) sea la vigente. Nunca inventa ni relaja sus
        # propios umbrales -- reutiliza exactamente el mismo mecanismo ya
        # probado (Fases 1-4), incluida su auto-resolución acotada
        # (`MAX_ITERACIONES_AUTO_RESOLUCION`) para los tipos de decisión
        # donde la evidencia YA alcanza el nivel más alto sin ambigüedad.
        evidencia_decisiones = reconciliar_bandeja_decisiones(raiz_atlas=raiz, reloj=lambda: instante)
        # Bloque PENDIENTES TÉCNICOS ACCIONABLES -- caso real 0000353055/
        # 464715 (MULTIPLES_UBICACIONES_DISPERSAS): los motivos de destino
        # que YA son un callejón sin salida con la evidencia actual
        # (`MOTIVOS_DESTINO_NO_RESUELTO`: dispersas, contradice comuna,
        # número incompatible, fuera de Chile, sin dato, genérica, sin
        # acceso vial, contradice catálogo confirmado, DESTINO_REVISAR)
        # generan su tarjeta `DESTINO_NO_RESUELTO` INMEDIATAMENTE, sin
        # esperar 3 reintentos. `reconciliar_decisiones_destino_no_resuelto`
        # ya existía y es idempotente (`regenerar_decisiones_persistidas`
        # + `_generar_artefacto_sin_lock` deduplican por `decision_id`
        # determinista y nunca resucitan una decisión ya cerrada en el
        # ledger), pero SÓLO se invocaba desde `revalidar_y_regenerar_
        # reporte` (decisión / envío Mobile). Corre AL FINAL, sobre el
        # dataset YA reconciliado, ANTES de generar el reporte -- así el
        # viaje aparece REQUIERE_REVISION con tarjeta, nunca
        # INCOMPLETO_TECNICO "que se reintenta solo".
        deteccion_destino = reconciliar_decisiones_destino_no_resuelto(raiz_atlas=raiz, reloj=lambda: instante)
        # A partir de acá el dataset YA tiene los cambios de las
        # revalidaciones de arriba -- cada una es atómica y ya quedó
        # protegida por su propio lock común del dataset al escribir; NO
        # se revierten pase lo que pase con lo que sigue (son
        # revalidaciones canónicas, siempre seguras de conservar, igual
        # que cualquier otra corrida de `revalidar_y_regenerar_reporte`).
        try:
            filas_despues = {str(f.get("numero_guia", "")): f for f in _leer_filas(dataset)}
            guias_recuperadas = [
                guia for guia in por_reintentar
                if str(filas_despues.get(guia, {}).get("estado_ruta", "")) == "RUTA_CALCULADA"
            ]
            pendientes_despues = _pendientes_ruta(dataset, decisiones)
            registros_despues = []
            for fila in pendientes_despues:
                guia = str(fila.get("numero_guia", ""))
                registro = _registro_pendiente(fila, seguimiento_previo.get(guia))
                if guia in por_reintentar:
                    registro["intentos_misma_evidencia"] = int(registro["intentos_misma_evidencia"]) + 1
                    registro["ultimo_intento"] = instante.isoformat()
                    registro["ultimo_resultado"] = str(filas_despues[guia].get("motivo_ruta", "")) or "SIN_CAMBIO"
                    historial = list(registro["historial_resultados"])[-9:]
                    historial.append({"fecha": instante.isoformat(), "resultado": registro["ultimo_resultado"]})
                    registro["historial_resultados"] = historial
                registros_despues.append(registro)
            escribir_json_atomico(ruta_pendientes, {
                "schema_version": 1, "actualizado_en": instante.isoformat(),
                "pendientes": registros_despues,
            })

            # Bloque CONSISTENCIA OPERACIONAL, Sección 3 -- publicación
            # VERSIONADA: se captura la huella del dataset YA
            # RECONCILIADO (fresca, después de las revalidaciones de
            # arriba) justo ANTES de generar el reporte, y se vuelve a
            # comprobar justo DESPUÉS -- si algo más (una decisión
            # humana, un reproceso, otra revalidación) cambió el dataset
            # mientras `generar_reporte_viajes` corría, este reporte YA
            # NO corresponde al dataset vigente: nunca se publica como
            # `reporte_vigente` -- se descarta la carpeta recién creada
            # (huérfana, nunca "vigente") y se retorna sin publicar. El
            # próximo ciclo natural de reconciliación (ya se dispara en
            # cada carga de Desktop, idempotente) converge con el
            # dataset ya estable.
            huella_para_publicar = _sha256_archivo(dataset)
            manifest = generar_reporte_viajes(
                dataset, reporte, carpeta_catalogos=catalogos,
                ruta_ledger=actual / LEDGER, reloj=lambda: instante,
            )
            if _sha256_archivo(dataset) != huella_para_publicar:
                shutil.rmtree(reporte, ignore_errors=True)
                return {
                    "reconciliado": False, "motivo": "DATASET_AVANZO_DURANTE_RECONCILIACION",
                    "version": version_previa,
                    "guias_actualizadas": limpieza["guias_actualizadas"],
                    "guias_recuperadas": guias_recuperadas,
                    "pendientes_tecnicos": len(registros_despues),
                }
            escribir_estado_operacion(
                reporte_vigente=reporte,
                dataset_operacional=dataset,
                decisiones_pendientes=(decisiones if decisiones.is_file() else None),
                raiz=raiz,
                reloj=lambda: instante,
                origen="RECONCILIACION_ESTADO_DERIVADO",
                version_estado_derivado=VERSION_ESTADO_DERIVADO,
                dataset_sha256=huella_para_publicar,
            )
        except Exception:
            # Bloque CONSISTENCIA OPERACIONAL -- el dataset NUNCA se
            # restaura acá (Regla absoluta: sus cambios, si los hubo,
            # vienen de revalidaciones ya atómicas y protegidas por su
            # propio lock -- siempre seguras de conservar, nunca "un
            # snapshot viejo" que reponer). `estado_operacion.json`
            # tampoco necesita restaurarse: con la publicación versionada
            # de arriba, `escribir_estado_operacion` corre COMPLETO
            # (atómico) sólo al final, o no corre en absoluto -- un
            # fallo acá jamás lo deja a medio escribir ni lo pisa con
            # datos viejos. Sólo se limpia la carpeta de reporte a medio
            # generar, si llegó a crearse -- nunca queda huérfana como
            # "vigente".
            if reporte.exists():
                shutil.rmtree(reporte, ignore_errors=True)
            raise

    return {
        "reconciliado": True,
        "version": VERSION_ESTADO_DERIVADO,
        "respaldo": str(respaldo),
        "reporte_vigente": str(reporte),
        "guias_actualizadas": sorted(
            set(limpieza["guias_actualizadas"])
            | set(limpieza_material["guias_actualizadas"])
            | set(limpieza_origen["guias_actualizadas"])
            | set(limpieza_origen_categoria["guias_actualizadas"])
            | set(limpieza_rut_chofer["rut_corregido_en_dataset"])
            | set(limpieza_indicadores["guias_actualizadas"])
            | set(limpieza_destino_catalogo["guias_actualizadas"])
            | set(limpieza_geo_contradiccion["guias_actualizadas"])
            | set(limpieza_obra_destino["guias_actualizadas"])
        ),
        "destinos_historial_recuperados": recuperacion_historial_destino,
        "guias_recuperadas": guias_recuperadas,
        "guias_contradiccion_destino_catalogo": limpieza_destino_catalogo["guias_contradiccion"],
        "destinos_coordenadas_completadas": limpieza_destino_coords["destinos_actualizados"],
        "decisiones_destino_no_resuelto_publicadas": deteccion_destino["decisiones_publicadas"],
        "envios_mobile_actualizados": limpieza_mobile["actualizados"],
        "decisiones_aplicadas_automaticamente": evidencia_decisiones["decisiones_aplicadas_automaticamente"],
        "pendientes_tecnicos": len(registros_despues),
        "totales": manifest["totales"],
        "ocr_ejecutado": False,
        "reporte_regenerado_por_dataset_desactualizado": reporte_desactualizado,
        "reporte_regenerado_por_estado_derivado_incoherente": estado_derivado_incoherente,
    }
