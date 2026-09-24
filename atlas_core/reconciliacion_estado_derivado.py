"""Migraciones ligeras e idempotentes de artefactos operacionales derivados.

No ejecuta OCR, no lee imágenes y no recalcula rutas. El dataset documental y
los catálogos son las fuentes; ``viajes.csv`` y las clasificaciones de ficha
son proyecciones regenerables de esas fuentes.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import shutil
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from atlas_core.almacenamiento_portable import (
    bloqueo_sesion,
    escribir_json_atomico,
    escribir_estado_operacion,
    leer_estado_operacion,
)
from atlas_core.aplicacion_decisiones import LEDGER
from atlas_core.rutas.modelos import EstadoRuta
from atlas_core.decisiones_pendientes import (
    MOTIVOS_DESTINO_NO_RESUELTO,
    NOMBRE_ARTEFACTO,
    _guias_con_direccion_confirmada_por_humano,
    _guias_destino_terminado_por_humano,
    _motivo_ruta_base,
    _obra_esta_ausente,
    clasificar_fallo_tecnico,
    guias_destino_conocido_ruta_pendiente,
)
from atlas_core.frescura_reconciliacion import _sha256_archivo_o_ausente
from atlas_core.mobile import RepositorioEnviosMobile, revalidar_asociacion_mobile_sin_ocr
from atlas_core.reporte_viajes import _sha256_archivo, generar_reporte_viajes
from atlas_core.revalidacion_documental import (
    SEPARADOR_MOTIVOS,
    _indicadores_documentales_coherentes,
    reconciliar_bandeja_decisiones,
    reconciliar_decisiones_destino_no_resuelto,
    reconciliar_segunda_pasada_universal_sin_ocr,
    reconciliar_incidencias_rut_chofer_documental,
    revalidar_chofer_sin_corroborar_por_catalogo_sin_ocr,
    revalidar_destino_contra_comuna_documental_sin_ocr,
    revalidar_destino_propio_respaldado_por_b1_sin_ocr,
    revalidar_destino_rechazado_por_evidencia_b1_sin_ocr,
    revalidar_destinos_confirmados_sin_coordenadas_sin_ocr,
    revalidar_fecha_por_telemetria_de_transporte_compartido_sin_ocr,
    revalidar_indicadores_documentales_sin_ocr,
    revalidar_material_estampado_persistido_sin_ocr,
    revalidar_tipo_carga_sin_ocr,
    recuperar_material_ausente_focal_controlado,
    recuperar_pendientes_desde_replay_traza_ocr_sin_ocr,
    revalidar_motivo_destino_ya_confirmado_sin_ocr,
    revalidar_obra_destino_sin_ocr,
    revalidar_origen_encabezado_no_confiable_sin_ocr,
    revalidar_origen_gps_candidato_unico_sin_contacto_sin_ocr,
    revalidar_origen_por_categoria_sin_candidato_sin_ocr,
    revalidar_origen_por_documento_hermano_de_transporte_sin_ocr,
    revalidar_origen_por_eliminacion_categoria_sin_ocr,
    revalidar_origen_por_historial_de_cliente_sin_ocr,
    revalidar_origen_por_vecinos_temporales_gps_sin_ocr,
    revalidar_origen_vecinos_gps_contra_evidencia_propia_real_sin_ocr,
    revalidar_destino_vacio_confirmado_por_documento_sin_ocr,
    revalidar_ruta_con_destino_confirmado_en_catalogo_sin_ocr,
    revalidar_ruta_por_historial_de_obra_sin_ocr,
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
#
# Subida de 16 a 17 -- CHOFER_SIN_CORROBORAR con ID interno placeholder
# (caso real WLADIMIR AGUILAR, viaje 0000354443, ID `PENDIENTE00000006`):
# se conecta `revalidar_chofer_sin_corroborar_por_catalogo_sin_ocr` a esta
# batería -- retira `CHOFER_SIN_CORROBORAR` de una fila cuya identidad ya
# es inequívoca (nombre exacto = único chofer activo del catálogo) y cuyo
# RUT documental es estructuralmente válido y no contradice ningún RUT
# canónico. Sin subir este número, esas filas quedarían bloqueadas hasta
# que un lote nuevo volviera a procesar el documento.
#
# Subida de 17 a 18 -- GEOGRAFÍA 2B / CICLO DE VIDA DE INCOMPLETO_TECNICO:
# cada pendiente técnico de `pendientes_tecnicos.json` recibe una
# `clase_fallo` (TRANSITORIO / AGOTABLE / DETERMINISTA, ver
# `atlas_core.decisiones_pendientes.clasificar_fallo_tecnico`) y un
# `estado_espera` explícito (ESPERANDO_COOLDOWN / ESPERANDO_PROVEEDOR /
# ESPERANDO_EVIDENCIA_NUEVA / ESPERANDO_ACCION_HUMANA / AGOTADO) con
# `causa_siguiente_accion` y una `proxima_oportunidad` en fecha ISO real
# (ya no el literal fijo). Los reintentos dejan de ser "3 iguales cada
# 24 h para todo": un DETERMINISTA no se reintenta sólo por paso del
# tiempo; un TRANSITORIO usa cooldown corto; `CONFIANZA_INSUFICIENTE`
# deja de quedar huérfano (converge a tarjeta o a evidencia nueva); una
# dirección ya confirmada por un humano nunca vuelve a preguntarse. Sin
# subir este número, los pendientes históricos nunca se reclasificarían
# bajo esta política.
#
# Subida de 18 a 19 -- BLOQUE AUTORIDAD OPERACIONAL / CONVERGENCIA +
# SEGUNDA PASADA UNIVERSAL: la resolución determinista de identidad
# (cliente/obra/vehículo) cambió de reglas. Un error pequeño de OCR ya no
# convierte conocimiento fuertemente establecido en desconocido: si la
# evidencia acumulada (confirmación humana, catálogo canónico, RUT,
# relaciones chofer↔vehículo / cliente↔obra / obra↔destino, ausencia de
# competidor) converge de forma ÚNICA en un canónico dentro de una
# variación pequeña, se resuelve SILENCIOSAMENTE (ver
# `atlas_core.atlas_ia.convergencia` y `procesamiento_masivo._convergencia_
# documental`); y TODA decisión pendiente CLIENTE_CANDIDATO/OBRA_
# DESCONOCIDA/VEHICULO_DESCONOCIDO pasa por una segunda pasada
# (determinista -> B1 con evidencia interna -> validación -> aplicación
# canónica -> regeneración de la bandeja) antes de llegar a Javier (ver
# `procesamiento_masivo._segunda_pasada_universal`).
#
# Subida de 19 a 20 -- causa raíz real: la 19 sólo cableó esas reglas en
# `procesar_carpeta` (ingesta de un lote nuevo). Una operación histórica
# que abre Desktop ejecuta `reconciliar_estado_derivado`, que NO invocaba
# ni `_convergencia_documental` ni `_segunda_pasada_universal` -- migrar a
# 19 marcaba "ya barrido a v19" sin haber aplicado ninguna de las reglas
# nuevas (caso real: 472477 PRODALAM seguía como CLIENTE_CANDIDATO tras
# abrir Desktop post-commit). La 20 conecta `revalidar_convergencia_
# identidad_sin_ocr` y `reconciliar_segunda_pasada_universal_sin_ocr`
# (SIN OCR, SIN red, `orquestador=None`) a la batería de
# `reconciliar_estado_derivado` -- así una operación ya migrada obtiene la
# convergencia en su próxima reconciliación natural, y cualquier RULESET
# futuro que cambie conocimiento derivado se beneficia igual.
#
# Subida de 20 a 21 -- REEVALUACIÓN RETROACTIVA UNIVERSAL: se agrega
# `versiones_capacidades` a `estado_operacion.json` y un trigger nuevo --
# cuando se sube la `version` de un dominio en `atlas_core.capacidades_
# reevaluacion.REGISTRO_CAPACIDADES`, la próxima reconciliación natural
# entra a la batería (que ya reúne todos los revalidadores) para
# reevaluar los pendientes de ESE dominio, y deja traza de qué
# dominio-versión retiró qué. Subir a 21 fuerza el primer barrido + el
# primer estampado de `versiones_capacidades` sobre operaciones ya
# migradas; a partir de ahí el mecanismo es incremental (cada dominio se
# reevalúa sólo cuando SU versión avanza) e idempotente.
#
# Subida de 21 a 22 -- REVISIONES ESTANCADAS por drift de OCR entre
# pasadas: `regenerar_decisiones_persistidas` sólo empataba una tarjeta
# regenerada contra su resolución previa por clave EXACTA (`decision_id`,
# que depende de `valor_documental`, o coincidencia LITERAL de calle).
# Cuando una reextracción posterior varía el texto documental
# ("COMERCIAL A Y B" -> "CONERCIAL A Y B"; el destino real -> "Jefe de
# Adquisiciones ..."), la MISMA pregunta reaparece con otro `decision_id`
# y ninguna de esas claves la reconoce -- la tarjeta sobrevive para
# siempre aunque un humano ya la respondió para esa guía. La 22 agrega
# dos supresiones tolerantes al drift, keyed por `(numero_guia, entidad)`:
# `CLIENTE_CANDIDATO` cuando el ledger tiene un `CONFIRMAR` humano de esa
# guía a la MISMA identidad (y el `cliente` vigente de la fila no
# contradice); `DESTINO_SIN_CONFIRMAR` cuando la obra ya tiene una
# relación obra<->destino CONFIRMADA (nivel CONFIRMACION_HUMANA) cuya
# evidencia cita esa guía y la fila vigente está operacionalmente limpia.
# Casos reales: 472037 (CONERCIAL/COMERCIAL A Y B LTDA), 472008 (AUSIN
# SAN BERNARDO), 472227 (EMPRESA CONST SIGRO). Subir a 22 fuerza el
# barrido sobre operaciones ya migradas; idempotente.
#
# Subida de 22 a 23 -- CIERRE GENERAL DE LOS 9 INCOMPLETO_TECNICO
# (segunda pasada, Codex): tres reglas usadas por esta misma batería
# cambiaron de comportamiento, ninguna nueva en el sentido de "regla que
# antes no corría" -- ya corrían, pero con un defecto real:
# 1. `_huella_ruta` incluía `resultado_atlas_ia_json` (traza diagnóstica,
#    nunca evidencia de ruteo) en el hash de "misma evidencia" --
#    `intentos_misma_evidencia` se reseteaba en cada pasada aunque nada
#    relevante hubiera cambiado, dejando `COORDENADA_NO_CONFIRMADA` sin
#    converger nunca a una tarjeta (472477/472541).
# 2. `_ciclo_vida_pendiente` (rama DETERMINISTA) ahora reconoce que un
#    `motivo`/`estado_ruta` vacíos no significan "nada que preguntar"
#    cuando la obra está ausente y ya hay dirección documental que
#    preguntar junto (`OBRA_AUSENTE_BLOQUEA_RUTEO`, 472623/472624) --
#    antes caía siempre a `MOTIVO_DETERMINISTA_SIN_ACCION_HUMANA_UTIL`.
# 3. `revalidar_destino_vacio_confirmado_por_documento_sin_ocr` (nueva,
#    llamada desde esta batería) reaplica automáticamente un destino ya
#    CONFIRMADO por un humano en el ledger cuando una dependencia previa
#    (origen) que bloqueaba su aplicación histórica ya se resolvió y la
#    fila sigue con `despachar_a_crudo` vacío (472037).
# Una operación ya migrada a 22 nunca reevaluaría estas tres reglas por sí
# sola -- subir a 23 fuerza el primer barrido sobre operaciones ya
# migradas; a partir de ahí, idempotente.
RULESET_VERSION = 24
VERSION_ESTADO_DERIVADO = RULESET_VERSION
NOMBRE_PENDIENTES_TECNICOS = "pendientes_tecnicos.json"
INTERVALO_REINTENTO = timedelta(hours=24)
MAX_REINTENTOS_IGUALES_ARRANQUE = 3

# Bloque P0 INGESTA FOCAL -- ELIMINAR RECONCILIACIÓN DUPLICADA -- caso
# real medido (guía 474197): dos reconciliaciones GLOBALES completas
# corrieron 75s aparte para la misma ingesta, con conteos de salida
# IDÉNTICOS (234/202/1/31) -- prueba de que la segunda no tenía nada
# nuevo que hacer. La causa raíz (Desktop llamando `reconciliar_estado_
# derivado.py` sin alcance justo después de que la ingesta ya reconcilió
# focal) se corrige en su origen (ver `Atlas-Viajes-Desktop-Restaurado`).
# Esta ventana es la protección de respaldo, general para cualquier
# llamador: si YA hay una reconciliación GLOBAL completa muy reciente
# cuyos insumos (dataset + pendientes técnicos + decisiones aplicadas +
# versión de reglas/capacidades) son BYTE IDÉNTICOS a los actuales, la
# repetición no puede producir un resultado distinto -- se omite la
# batería pesada. Nunca compara alcances distintos (ver `_alcance_run`
# más abajo): una corrida FOCAL nunca puede "cubrir" el barrido GLOBAL
# que una corrida GLOBAL posterior necesita hacer de verdad.
VENTANA_IDEMPOTENCIA_RECONCILIACION_COMPLETA = timedelta(seconds=300)

# Bloque GEOGRAFÍA 2B -- cooldown y tope por clase de fallo. Sin daemon:
# el reintento sólo se evalúa dentro de una reconciliación natural
# (Desktop/CLI/operación), pero con un ciclo de vida finito y
# convergente.
COOLDOWN_REINTENTO_TRANSITORIO = timedelta(hours=6)
MAX_REINTENTOS_POR_CLASE = {
    "TRANSITORIO": 5,
    "AGOTABLE": MAX_REINTENTOS_IGUALES_ARRANQUE,
    "DETERMINISTA": 0,
}
ESTADO_ESPERA_COOLDOWN = "ESPERANDO_COOLDOWN"
ESTADO_ESPERA_PROVEEDOR = "ESPERANDO_PROVEEDOR"
ESTADO_ESPERA_EVIDENCIA = "ESPERANDO_EVIDENCIA_NUEVA"
ESTADO_ESPERA_ACCION_HUMANA = "ESPERANDO_ACCION_HUMANA"
ESTADO_ESPERA_AGOTADO = "AGOTADO"


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
    # Bloque BUG intentos_misma_evidencia (Codex 472477/472541) -- causa
    # raíz real: `resultado_atlas_ia_json` NO es evidencia de ruteo -- es
    # la traza diagnóstica de B1 (texto/metadata que puede refrescarse
    # entre pasadas sin que ningún campo de ruteo real haya cambiado).
    # Incluirla en la huella hacía que CUALQUIER cambio de esa traza
    # (aunque `planta_origen_id`/`despachar_a_crudo`/`motivo_ruta`, etc.
    # quedaran idénticos) se leyera como "evidencia nueva": `_registro_
    # pendiente` descartaba `intentos_misma_evidencia`/`ultimo_intento`
    # en cada pasada y el reintento nunca acumulaba -- quedaba
    # perpetuamente en `intentos=0` sin importar cuántas reconciliaciones
    # reales corrieran. La huella ahora depende EXCLUSIVAMENTE de los
    # campos que de verdad determinan si el ruteo puede converger
    # distinto -- ningún campo de diagnóstico/observabilidad.
    campos = (
        "planta_origen_id", "despachar_a_crudo", "cliente", "obra_destino",
        "destino_id", "motivo_ruta",
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
        # Bloque GEOGRAFÍA 2B -- clase de fallo (TRANSITORIO / AGOTABLE /
        # DETERMINISTA). `estado_espera` / `causa_siguiente_accion` /
        # `proxima_oportunidad` (fecha ISO real o null) se completan en
        # `_ciclo_vida_pendiente`, tras el reintento de esta pasada.
        "clase_fallo": clasificar_fallo_tecnico(str(fila.get("motivo_ruta", "")).strip()),
        "proxima_oportunidad": None,
        # Compatibilidad: `escalamiento` se conserva para llamadores/tests
        # previos a 2B; `estado_espera` es la señal canónica desde 2B.
        "escalamiento": "PROXIMA_CORRIDA_GUIAS_REVALIDACION_GLOBAL_B1" if int((mismo or {}).get("intentos_misma_evidencia", 0)) >= MAX_REINTENTOS_IGUALES_ARRANQUE else "REINTENTO_DEPENDENCIA",
    }


def _ciclo_vida_pendiente(
    registro: dict[str, object], *, instante: datetime,
    direccion_confirmada_por_humano: bool, destino_terminado_por_humano: bool,
) -> dict[str, object]:
    """Bloque GEOGRAFÍA 2B -- estado de ciclo de vida explícito de un
    pendiente técnico, calculado tras el reintento de esta pasada. Nunca
    deja un caso en limbo: siempre queda en RESUELTO (fuera de esta lista),
    ESPERANDO_ACCION_HUMANA (con tarjeta real en la bandeja),
    ESPERANDO_COOLDOWN / ESPERANDO_PROVEEDOR / ESPERANDO_EVIDENCIA_NUEVA /
    AGOTADO (condición explícita no humana)."""
    motivo = str(registro.get("motivo_actual", ""))
    clase = clasificar_fallo_tecnico(motivo)
    base = _motivo_ruta_base(motivo)
    intentos = int(registro.get("intentos_misma_evidencia", 0) or 0)
    maximo = MAX_REINTENTOS_POR_CLASE.get(clase, 0)
    cooldown = (
        COOLDOWN_REINTENTO_TRANSITORIO if clase == "TRANSITORIO" else INTERVALO_REINTENTO
    )

    def _resultado(estado: str, causa: str, proxima: str | None) -> dict[str, object]:
        return {
            "clase_fallo": clase,
            "estado_espera": estado,
            "causa_siguiente_accion": causa,
            "proxima_oportunidad": proxima,
        }

    if destino_terminado_por_humano:
        return _resultado(
            ESTADO_ESPERA_AGOTADO, "HUMANO_DECLARO_NO_PUEDE_DETERMINAR", None
        )
    if direccion_confirmada_por_humano:
        # La identidad del destino ya está resuelta por un humano; el
        # geocodificador aún no la ubica -- nunca se vuelve a preguntar.
        return _resultado(
            ESTADO_ESPERA_EVIDENCIA,
            "DIRECCION_CONFIRMADA_POR_HUMANO__GEOCODER_NO_RESUELVE",
            None,
        )
    if clase == "DETERMINISTA":
        if base in MOTIVOS_DESTINO_NO_RESUELTO:
            # `reconciliar_decisiones_destino_no_resuelto` publica la
            # tarjeta accionable en esta misma reconciliación.
            return _resultado(
                ESTADO_ESPERA_ACCION_HUMANA, "CORREGIR_O_CONFIRMAR_DIRECCION", None
            )
        # Bloque BLOQUEO PREVIO AL RUTEO (Codex 472623/472624) -- un
        # `motivo` vacío no siempre significa "nada útil que hacer": el
        # ruteo puede no haberse intentado nunca porque la obra nunca se
        # extrajo del documento -- misma condición exacta que
        # `detectar_decision_destino_no_resuelto` ya reconoce (motivo
        # sintético `OBRA_AUSENTE_BLOQUEA_RUTEO`) para publicar la
        # tarjeta correspondiente. Este bloque sólo alinea la EXPLICACIÓN
        # del pendiente técnico con esa misma realidad -- nunca decide
        # nada por sí solo.
        if not motivo:
            datos = registro.get("datos_disponibles") or {}
            if _obra_esta_ausente(str(datos.get("obra", ""))) and str(datos.get("destino_documental", "")).strip():
                return _resultado(
                    ESTADO_ESPERA_ACCION_HUMANA, "OBRA_AUSENTE_BLOQUEA_RUTEO", None
                )
        return _resultado(
            ESTADO_ESPERA_EVIDENCIA, "MOTIVO_DETERMINISTA_SIN_ACCION_HUMANA_UTIL", None
        )
    if intentos < maximo:
        proxima = None
        ultimo = registro.get("ultimo_intento")
        if ultimo:
            try:
                proxima = (datetime.fromisoformat(str(ultimo)) + cooldown).isoformat()
            except ValueError:
                proxima = None
        causa = (
            "PROVEEDOR_EXTERNO_TEMPORALMENTE_INDISPONIBLE"
            if clase == "TRANSITORIO"
            else "REINTENTO_AUTOMATICO_PENDIENTE"
        )
        return _resultado(ESTADO_ESPERA_COOLDOWN, causa, proxima)
    # Agotó el máximo de su clase.
    if clase == "TRANSITORIO":
        return _resultado(
            ESTADO_ESPERA_PROVEEDOR,
            "PROVEEDOR_EXTERNO_NO_DISPONIBLE_TRAS_MAX_INTENTOS",
            None,
        )
    # AGOTABLE agotado: la tarjeta accionable ya se publica (intentos >=
    # UMBRAL) en la misma reconciliación; si por alguna supresión no
    # existiera, el humano igual es quien puede resolverlo.
    if base in MOTIVOS_DESTINO_NO_RESUELTO or clase == "AGOTABLE":
        return _resultado(
            ESTADO_ESPERA_ACCION_HUMANA, "CORREGIR_O_CONFIRMAR_DIRECCION", None
        )
    return _resultado(
        ESTADO_ESPERA_EVIDENCIA, "SIN_ACCION_AUTOMATICA_NI_HUMANA_DISPONIBLE", None
    )


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
    publicar nada sería un bucle inútil.

    Bloque GEOGRAFÍA 2B -- también entra al bloque una fila cuyo motivo es
    AGOTABLE (`CONFIANZA_INSUFICIENTE`, `COORDENADA_NO_CONFIRMADA`) y que
    YA agotó sus reintentos (`intentos_misma_evidencia >=
    UMBRAL_INTENTOS_TECNICOS_AGOTADOS` en `pendientes_tecnicos.json`) sin
    tarjeta: converge a `DESTINO_NO_RESUELTO` accionable en la misma
    pasada. Una guía cuya dirección un humano ya confirmó nunca cuenta
    (jamás se le publica tarjeta -- queda `ESPERANDO_EVIDENCIA_NUEVA`)."""
    from atlas_core.decisiones_pendientes import (
        MOTIVOS_DESTINO_NO_RESUELTO,
        MOTIVOS_DESTINO_TECNICO_AGOTABLE,
        UMBRAL_INTENTOS_TECNICOS_AGOTADOS,
    )

    guias_destino_terminadas = set(_guias_destino_terminado_por_humano(
        dataset.parent / "decisiones_aplicadas.json"
    ))
    guias_direccion_confirmada = _guias_con_direccion_confirmada_por_humano(
        dataset.parent / "decisiones_aplicadas.json"
    )
    intentos_por_guia: dict[str, int] = {}
    try:
        _pend = json.loads((dataset.parent / NOMBRE_PENDIENTES_TECNICOS).read_text(encoding="utf-8"))
        for _r in _pend.get("pendientes", []) or []:
            _g = str(_r.get("numero_guia", "")).strip()
            if _g:
                intentos_por_guia[_g] = int(_r.get("intentos_misma_evidencia", 0) or 0)
    except (OSError, ValueError, AttributeError):
        pass

    for fila in _pendientes_ruta(dataset, decisiones):
        guia = str(fila.get("numero_guia", "")).strip()
        if guia in guias_destino_terminadas or guia in guias_direccion_confirmada:
            continue
        motivo_base = _motivo_ruta_base(str(fila.get("motivo_ruta", "")))
        if motivo_base in MOTIVOS_DESTINO_NO_RESUELTO:
            return True
        if (
            motivo_base in MOTIVOS_DESTINO_TECNICO_AGOTABLE
            and intentos_por_guia.get(guia, 0) >= UMBRAL_INTENTOS_TECNICOS_AGOTADOS
        ):
            return True
    return False


def _reconciliacion_global_reciente_identica(
    *, raiz: Path, instante, huella_idempotencia_actual: dict[str, object],
) -> str | None:
    """Bloque P0 INGESTA FOCAL -- ver comentario junto a
    `VENTANA_IDEMPOTENCIA_RECONCILIACION_COMPLETA`. Busca el respaldo de
    reconciliación GLOBAL más reciente (mismo `VERSION_ESTADO_DERIVADO`)
    dentro de la ventana y compara su huella BYTE A BYTE contra la
    actual -- cualquier ausencia, error de lectura o discrepancia hace
    que devuelva `None` (comportamiento de siempre: correr la batería).
    Nunca compara contra una corrida FOCAL (ver `alcance` en el
    manifiesto) -- sólo GLOBAL-contra-GLOBAL, el único par donde "mismos
    insumos" garantiza "mismo resultado" sin ambigüedad de alcance."""
    carpeta_respaldos = raiz / "respaldos"
    try:
        candidatos = sorted(
            (
                p for p in carpeta_respaldos.iterdir()
                if p.is_dir()
                and p.name.startswith(f"reconciliacion_estado_derivado_v{VERSION_ESTADO_DERIVADO}_")
            ),
            key=lambda p: p.name,
            reverse=True,
        )
    except OSError:
        return None
    if not candidatos:
        return None
    mas_reciente = candidatos[0]
    try:
        manifest = json.loads((mas_reciente / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if manifest.get("alcance") != "GLOBAL":
        return None
    huella_previa = manifest.get("huella_idempotencia")
    if not isinstance(huella_previa, dict):
        return None
    try:
        completada_en = datetime.fromisoformat(str(manifest.get("creado_en")))
    except ValueError:
        return None
    if instante - completada_en > VENTANA_IDEMPOTENCIA_RECONCILIACION_COMPLETA:
        return None
    if huella_previa == huella_idempotencia_actual:
        return mas_reciente.name
    return None


def _ruta_log_diagnostico_reconciliacion() -> Path:
    """Bloque P0 OBSERVABILIDAD RECONCILIACIÓN FOCAL -- ubicación LOCAL,
    fuera de CUALQUIER `raiz_atlas`/G:\\ (nunca dato operacional, nunca
    escribe en la operación real) -- mismo criterio ya establecido en
    `atlas_core.paddle_runtime.ruta_runtime_paddle`: override explícito
    primero (útil para pruebas), si no `%LOCALAPPDATA%\\Atlas\\
    diagnostico\\` (o `~/AppData/Local` si la variable no existe, p. ej.
    fuera de Windows)."""
    override = os.environ.get("ATLAS_DIAGNOSTICO_DIR")
    if override:
        base = Path(override)
    else:
        local_app_data = os.environ.get("LOCALAPPDATA")
        base = (Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local") / "Atlas" / "diagnostico"
    return base / "reconciliacion_tiempos.jsonl"


def _registrar_diagnostico_reconciliacion(
    *, raiz: Path, guias_objetivo: set[str] | None, instante, resultado: dict[str, object],
) -> None:
    """Bloque P0 OBSERVABILIDAD RECONCILIACIÓN FOCAL -- caso real medido
    (guía 474196): la reconciliación focal tomó ~60s sin que ningún log
    dijera en qué sub-etapa. `tiempos_ms`/`duracion_bateria_completa_ms`
    YA los calcula la función (bloque `_marca_etapa` de arriba) -- esto
    sólo los APPENDEA a un archivo local, nunca mide nada nuevo y nunca
    cambia `resultado`. Estrictamente best-effort: cualquier fallo
    (permisos, disco lleno, ruta inválida) se descarta en silencio --
    el diagnóstico jamás puede impedir ni alterar una reconciliación
    real."""
    try:
        ruta = _ruta_log_diagnostico_reconciliacion()
        ruta.parent.mkdir(parents=True, exist_ok=True)
        linea = {
            "registrado_en_utc": instante.isoformat(),
            "raiz_atlas": str(raiz),
            "alcance": "GLOBAL" if guias_objetivo is None else "FOCAL",
            "guias_objetivo": sorted(guias_objetivo) if guias_objetivo is not None else None,
            "reconciliado": resultado.get("reconciliado"),
            "motivo": resultado.get("motivo"),
            "version": resultado.get("version"),
            "tiempos_ms": resultado.get("tiempos_ms"),
            "duracion_bateria_completa_ms": resultado.get("duracion_bateria_completa_ms"),
        }
        with ruta.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(linea, ensure_ascii=False) + "\n")
    except Exception:
        pass


def reconciliar_estado_derivado(
    *, raiz_atlas: str | Path, reloj=lambda: datetime.now(timezone.utc),
    proveedor_rutas=None, proveedor_rutas_fallback=None,
    guias_excluir_reintento_ruta: set[str] | None = None,
    guias_objetivo: set[str] | None = None,
) -> dict[str, object]:
    """Actualiza una operación antigua una sola vez por RULESET_VERSION.

    `migracion` (más abajo) sólo se dispara si `version_previa <
    RULESET_VERSION` -- CUALQUIER cambio a las reglas de alguno de los
    `revalidar_*_sin_ocr` invocados aquí (no sólo un cambio de esquema de
    los artefactos derivados) exige subir `RULESET_VERSION`; de lo
    contrario, una operación que ya alcanzó la versión vigente nunca
    vuelve a ejecutar la regla corregida hasta que algo MÁS mueva el
    dataset (ver docstring de `RULESET_VERSION`, caso real 472640).

    `guias_excluir_reintento_ruta` (Bloque P0 EVITAR SEGUNDO INTENTO,
    aditivo -- `None` conserva el comportamiento de siempre): guías que
    YA tuvieron un intento real de ruta/geocodificación DENTRO de la
    MISMA operación que llama a esta función (p. ej.
    `aplicar_decisiones_multiples`, que corre esta reconciliación justo
    después de su propia batería diferida) -- se reenvía tal cual a los
    dos revalidadores de ruta de abajo para que ninguno de los dos pague
    una consulta externa redundante por la MISMA guía en la MISMA
    pasada. Nunca un cooldown persistente: vive sólo en esta llamada.

    `guias_objetivo` (Bloque P0 RECONCILIACIÓN FOCAL -- ingesta rápida,
    aditivo, `None` conserva EXACTAMENTE el comportamiento de siempre:
    mantenimiento/reconciliación GLOBAL, recorre y reintenta todo el
    backlog elegible): cuando se entrega, esta reconciliación se vuelve
    FOCAL -- procesa la(s) guía(s) del conjunto (típicamente una guía
    recién ingestada más cualquier otra causalmente afectada por la
    misma operación, ver `atlas_core.procesamiento_masivo.procesar_
    carpeta`) y dejar intacto el resto del backlog pendiente de ruta,
    identidad y segunda pasada -- nunca lo toca, nunca lo excluye
    permanentemente: sigue esperando el próximo ciclo de mantenimiento
    (`guias_objetivo=None`), que conserva capacidad plena de recorrerlo.
    Una guía fuera del scope SÍ se reevalúa igual si la razón es GLOBAL
    de verdad (migración de `RULESET_VERSION`, avance de capacidad de
    dominio) -- el scope nunca oculta ni retrasa esas dos, sólo apaga el
    reintento de backlog por cooldown ordinario. La publicación de
    reporte/estado al final de la función corre igual, focal o global --
    la guía procesada queda visible sin depender de una reconciliación
    global posterior."""
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
    # Bloque GEOGRAFÍA 2B -- guías cuya dirección un humano YA confirmó
    # (REGISTRAR_DIRECCION aplicado) y guías cuya decisión de destino un
    # humano ya cerró de forma terminal (NO_PUEDO_DETERMINAR/NO_CONFIRMAR).
    guias_direccion_confirmada = _guias_con_direccion_confirmada_por_humano(
        actual / "decisiones_aplicadas.json"
    )
    guias_destino_terminado = _guias_destino_terminado_por_humano(
        actual / "decisiones_aplicadas.json"
    )
    migracion = version_previa < RULESET_VERSION

    # Bloque REEVALUACIÓN RETROACTIVA UNIVERSAL -- una mejora declarada en
    # `capacidades_reevaluacion.REGISTRO_CAPACIDADES` (subir la `version`
    # de un dominio) debe poder propagarse automáticamente a los viajes
    # que sigan pendientes de ese dominio, sin esperar un lote nuevo ni un
    # reproceso manual. Se compara contra `versiones_capacidades`
    # persistido; si alguna avanzó, se ENTRA a la batería de abajo (que ya
    # reúne todos los revalidadores). Una migración de `RULESET_VERSION`
    # cuenta como "todas pudieron avanzar" (se re-estampa igual).
    from atlas_core.capacidades_reevaluacion import (
        capacidades_avanzadas as _capacidades_avanzadas,
        dominios_de_motivo_tecnico as _dominios_de_motivo_tecnico,
        resumen_reevaluacion as _resumen_reevaluacion,
        versiones_actuales as _versiones_cap_actuales,
    )
    _versiones_cap_previas = estado_previo.get("versiones_capacidades") or {}
    capacidades_a_reevaluar = _capacidades_avanzadas(_versiones_cap_previas)
    if migracion:
        _act = _versiones_cap_actuales()
        capacidades_a_reevaluar = {
            d: (int(_versiones_cap_previas.get(d, 0) or 0), _act[d]) for d in _act
        }
    _dominios_avanzados = set(capacidades_a_reevaluar)
    por_reintentar = []
    for registro in registros:
        if str(registro["numero_guia"]) in guias_direccion_confirmada:
            # Dirección ya confirmada por un humano: su reintento útil es
            # `revalidar_ruta_con_destino_confirmado_en_catalogo_sin_ocr`
            # (corre siempre, evidencia humana), nunca repetir la misma
            # consulta técnica ni volver a preguntar.
            continue
        motivo_registro = str(registro.get("motivo_actual", ""))
        clase = clasificar_fallo_tecnico(motivo_registro)
        intentos = int(registro["intentos_misma_evidencia"])
        # La CAPACIDAD de un dominio que gobierna este motivo avanzó
        # (p. ej. GEOGRAFIA 2->3: maestro territorial INE v3 activo) --
        # evidencia NUEVA para el pendiente, exactamente como una
        # `migracion` de `RULESET_VERSION` pero acotada a ese dominio: se
        # reintenta UNA vez, sin esperar cooldown. Idempotente -- una vez
        # re-estampada `versiones_capacidades`, `capacidades_a_reevaluar`
        # queda vacío y este reintento no se vuelve a forzar.
        capacidad_del_dominio_avanzo = bool(
            _dominios_avanzados & _dominios_de_motivo_tecnico(motivo_registro)
        )
        # Bloque P0 RECONCILIACIÓN FOCAL -- `guias_objetivo=None` (default,
        # mantenimiento/global) hace que `en_scope` sea SIEMPRE True, así
        # que las dos condiciones de abajo quedan matemáticamente
        # idénticas a como estaban antes de este bloque -- ningún caller
        # existente puede notar la diferencia. Cuando SÍ se entrega
        # `guias_objetivo` (reconciliación focal, p. ej. tras ingestar una
        # guía nueva), una guía FUERA del scope sólo entra a `por_
        # reintentar` por una razón GLOBAL de verdad (`migracion` de
        # `RULESET_VERSION`, o avance de `capacidad_del_dominio_avanzo` --
        # ambas versionadas, deliberadas, poco frecuentes) -- nunca sólo
        # porque su cooldown de reintento venció o porque es su primer
        # intento; eso es exactamente el barrido de backlog no
        # relacionado que esta reconciliación focal no debe hacer. Una
        # guía SIN evidencia nueva y sin causa global simplemente espera
        # al próximo ciclo de mantenimiento/reconciliación global
        # (`guias_objetivo=None`), que sigue disponible sin cambios.
        en_scope = guias_objetivo is None or str(registro["numero_guia"]) in guias_objetivo
        if clase == "DETERMINISTA":
            # Nunca se reintenta sólo por paso del tiempo -- repetir la
            # MISMA consulta con la MISMA evidencia no cambiaría nada (no
            # se gastan 3 intentos idénticos). SÍ se reintenta ante
            # evidencia NUEVA (`intentos == 0`: primer intento, o huella
            # distinta que `_registro_pendiente` reinició), ante un
            # cambio de reglas (`migracion`, una vez por `RULESET_VERSION`)
            # o ante el avance de capacidad de un dominio que lo gobierna.
            if migracion or capacidad_del_dominio_avanzo or (intentos == 0 and en_scope):
                por_reintentar.append(str(registro["numero_guia"]))
            continue
        maximo = MAX_REINTENTOS_POR_CLASE.get(clase, 0)
        cooldown = (
            COOLDOWN_REINTENTO_TRANSITORIO if clase == "TRANSITORIO" else INTERVALO_REINTENTO
        )
        ultimo = registro.get("ultimo_intento")
        vencido = True
        if ultimo:
            try:
                vencido = instante - datetime.fromisoformat(str(ultimo)) >= cooldown
            except ValueError:
                pass
        if capacidad_del_dominio_avanzo or ((intentos < maximo and vencido) and en_scope):
            por_reintentar.append(str(registro["numero_guia"]))
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
    # Bloque P0 INGESTA FOCAL -- ELIMINAR RECONCILIACIÓN DUPLICADA (ver
    # `VENTANA_IDEMPOTENCIA_RECONCILIACION_COMPLETA` arriba). Huella de
    # TODO lo que puede hacer variar el resultado de una corrida GLOBAL:
    # dataset + pendientes técnicos (gobierna `por_reintentar`) +
    # decisiones aplicadas (gobierna `guias_direccion_confirmada`/
    # `guias_destino_terminado`) + versión de reglas/capacidades. Sólo se
    # usa para la comparación de idempotencia de abajo -- nunca sustituye
    # `reporte_desactualizado` (que sigue siendo la señal real de "hay
    # que republicar").
    huella_idempotencia_actual = {
        "dataset_sha256": huella_dataset_actual,
        "pendientes_tecnicos_sha256": _sha256_archivo_o_ausente(ruta_pendientes),
        "decisiones_aplicadas_sha256": _sha256_archivo_o_ausente(actual / "decisiones_aplicadas.json"),
        "version_estado_derivado": version_previa,
        "versiones_capacidades": dict(sorted((estado_previo.get("versiones_capacidades") or {}).items())),
    }
    reconciliacion_global_redundante = None
    if guias_objetivo is None:
        reconciliacion_global_redundante = _reconciliacion_global_reciente_identica(
            raiz=raiz, instante=instante, huella_idempotencia_actual=huella_idempotencia_actual,
        )
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
        and not capacidades_a_reevaluar
    ):
        return {
            "reconciliado": False, "motivo": "VERSION_VIGENTE_SIN_REINTENTO_PENDIENTE",
            "version": version_previa, "pendientes_tecnicos": len(registros),
        }
    if reconciliacion_global_redundante is not None:
        # Bloque P0 INGESTA FOCAL -- ELIMINAR RECONCILIACIÓN DUPLICADA: a
        # diferencia del corte de arriba, éste SÍ puede haber entrado con
        # `por_reintentar` no vacío (backlog con cooldown vencido) -- pero
        # una reconciliación GLOBAL igual de reciente, con la MISMA huella
        # byte a byte, ya demostró que ese backlog no tenía nada resoluble
        # (mismo dataset, mismos pendientes técnicos, mismas decisiones
        # aplicadas -- el resultado no puede ser distinto). El reporte
        # vigente que esa corrida dejó publicado sigue siendo válido; no
        # se toca nada más.
        return {
            "reconciliado": False, "motivo": "IDEMPOTENTE_RECONCILIACION_GLOBAL_RECIENTE_SIN_CAMBIOS",
            "version": version_previa, "pendientes_tecnicos": len(registros),
            "respaldo_referencia": reconciliacion_global_redundante,
        }

    # Bloque MÉTRICAS DE DURACIÓN POR ETAPA -- caso real: "Actualizando
    # operación" tardaba ~70s en Desktop sin que ningún log dijera dónde.
    # `_marca_etapa` es sólo instrumentación (perf_counter, nunca decide
    # nada ni cambia ningún resultado) -- agrupa la batería de abajo en
    # tramos legibles para que una futura regresión de rendimiento sea
    # visible en `tiempos_ms` del resultado, en vez de "algo se puso
    # lento" sin más detalle. `reevaluacion_retroactiva.duracion_ms` antes
    # medía por error TODA la batería (incluidas `reconciliar_segunda_
    # pasada_universal_sin_ocr` y `reconciliar_decisiones_destino_no_
    # resuelto`) en vez de sólo la comparación antes/después que le da
    # nombre -- ver `_t_reeval_comparacion_inicio` más abajo, junto a esa
    # comparación real.
    _t_bateria_inicio = time.perf_counter()
    _t_ultima_marca = [_t_bateria_inicio]
    _tiempos_ms: dict[str, float] = {}
    # Bloque P0 MEMOIZACIÓN -- caché COMPARTIDA por huella de insumos,
    # vive sólo durante ESTA llamada (nunca persiste, nunca se comparte
    # entre invocaciones): `reconciliar_decisiones_destino_no_resuelto`/
    # `reconciliar_bandeja_decisiones`/`reconciliar_segunda_pasada_
    # universal_sin_ocr` llaman cada una, por su cuenta, a `regenerar_
    # decisiones_persistidas` sobre la MISMA lista de decisiones y los
    # MISMOS catálogos/dataset si nada las cambió entre medio -- ver
    # docstring de esa función.
    _cache_regenerar_decisiones: dict[tuple[object, ...], list[dict[str, object]]] = {}

    def _marca_etapa(nombre: str) -> None:
        ahora = time.perf_counter()
        _tiempos_ms[nombre] = round((ahora - _t_ultima_marca[0]) * 1000, 1)
        _t_ultima_marca[0] = ahora

    # Snapshot ANTES (para la traza de reevaluación retroactiva) -- la
    # bandeja de decisiones y los pendientes técnicos tal cual están antes
    # de que la batería de abajo los regenere.
    try:
        _decisiones_antes = json.loads(decisiones.read_text(encoding="utf-8")).get("decisiones", []) if decisiones.is_file() else []
    except (OSError, ValueError):
        _decisiones_antes = []
    try:
        _tecnicos_antes = json.loads(ruta_pendientes.read_text(encoding="utf-8")).get("pendientes", []) if ruta_pendientes.is_file() else []
    except (OSError, ValueError):
        _tecnicos_antes = []

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
            # Bloque P0 INGESTA FOCAL -- ELIMINAR RECONCILIACIÓN DUPLICADA:
            # huella de los insumos AL INICIO de esta corrida (antes de que
            # la batería de abajo mueva nada) + si fue focal o global --
            # ver `_reconciliacion_global_reciente_identica`.
            "alcance": "GLOBAL" if guias_objetivo is None else "FOCAL",
            "huella_idempotencia": huella_idempotencia_actual,
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        # Bloque P1 ELIMINAR DOBLE RECONCILIACIÓN -- si `revalidar_y_
        # regenerar_reporte` (Fase 1, disparada por `aplicar_decision_
        # obra`) YA corrió, hace un instante, las 18 funciones de
        # `FUNCIONES_BATERIA_COMPARTIDA` contra este MISMO dataset +
        # catálogos + ledger + versión de reglas/capacidades -- byte a
        # byte, no por timestamp --, repetirlas aquí es trabajo idéntico
        # tirado a la basura (caso real medido: ~26 s en Fase 1 y otra vez
        # ~27 s en Fase 2 sobre el mismo estado, segundos después). El
        # resto de la batería (recuperación P0, replay OCR, convergencia
        # de identidad, corroboración de chofer por RUT, mobile,
        # `revalidar_ruta_con_destino_confirmado_en_catalogo_sin_ocr` --
        # sin equivalente en Fase 1 -- y las 3 pasadas exclusivas de Fase
        # 2) corre SIEMPRE, sin excepción -- ver `atlas_core.frescura_
        # reconciliacion` para el contrato completo y la auditoría
        # función por función.
        #
        # PELIGRO DE ORDEN (por qué esto NO es una firma calculada una
        # sola vez): varias funciones NO compartidas (`rechazo_evidencia_
        # destino`, `reversion_historial_destino`, `recuperacion_
        # historial_destino`, recuperación P0, convergencia de identidad,
        # RUT de chofer, y el reintento de ruta acotado a `por_
        # reintentar`) corren ANTES o ENTREMEDIO de las 18 llamadas
        # compartidas y SÍ pueden mutar el dataset en esta misma pasada.
        # Si cualquiera de ellas cambia algo, el estado deja de coincidir
        # con lo que Fase 1 firmó -- `_bateria_compartida_sigue_fresca()`
        # relee dataset+catálogos+ledger y RECALCULA la firma cada vez
        # que se llama (nunca una firma congelada al principio), así que
        # una mutación intermedia la invalida automáticamente para TODAS
        # las llamadas compartidas que todavía no corrieron, sin importar
        # cuántas funciones no compartidas se hayan intercalado antes.
        from atlas_core.frescura_reconciliacion import calcular_firma_bateria_compartida

        _firma_publicada_bateria_compartida = estado_previo.get("firma_bateria_compartida")

        def _bateria_compartida_sigue_fresca() -> bool:
            if not _firma_publicada_bateria_compartida:
                return False
            try:
                firma_actual = calcular_firma_bateria_compartida(
                    dataset=dataset, carpeta_catalogos=catalogos, ruta_ledger=actual / LEDGER,
                    ruleset_version=RULESET_VERSION, versiones_capacidades=_versiones_cap_actuales(),
                )
            except OSError:
                return False
            return firma_actual == _firma_publicada_bateria_compartida

        def _sin_cambio_guias() -> dict[str, object]:
            # Forma de retorno verificada por AST contra las 17 de las 18
            # funciones compartidas que devuelven {filas_totales,
            # guias_actualizadas} -- ver `frescura_reconciliacion.py`.
            # `filas_totales` no se lee en ningún punto de esta función
            # (sólo `guias_actualizadas`); se deja en 0 para que sea
            # obvio en un log que la llamada real fue omitida.
            return {"filas_totales": 0, "guias_actualizadas": []}

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
            _revertir_promociones_historial_contaminado,
            revalidar_convergencia_identidad_sin_ocr,
        )
        # Codex 472623/472624 -- un destino que B1 / la validación de
        # evidencia RECHAZÓ explícitamente no puede quedar como
        # RUTA_CALCULADA ni fuente histórica. Corre ANTES de las
        # recuperaciones por historial para que esas filas ya no puedan
        # actuar como evidencia convergente en esta misma pasada.
        rechazo_evidencia_destino = revalidar_destino_rechazado_por_evidencia_b1_sin_ocr(
            ruta_dataset=dataset, ruta_ledger=actual / "decisiones_aplicadas.json",
        )
        # Codex 472477 -- deshace cualquier `despachar_a_crudo` inyectado
        # por la regla vieja (obra placeholder / distinto cliente / un
        # solo transporte), antes de re-evaluar convergencias.
        reversion_historial_destino = _revertir_promociones_historial_contaminado(dataset)
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
        # Codex 472623/472624 -- brecha INVERSA a la de arriba: un destino
        # que B1 propuso con evidencia EXCLUSIVAMENTE propia del documento
        # (nunca de otra guía/catálogo) y sin contradicción, bloqueado sólo
        # por un empaquetado de evidencia vacío -- nunca una evidencia
        # genuinamente insuficiente. Corre DESPUÉS de las dos funciones de
        # arriba (que ya retiraron cualquier valor genuinamente contaminado
        # o rechazado) para que sólo quede evidencia propia y limpia.
        recuperacion_destino_propio = (
            _sin_cambio_guias() if _bateria_compartida_sigue_fresca()
            else revalidar_destino_propio_respaldado_por_b1_sin_ocr(ruta_dataset=dataset)
        )
        _marca_etapa("recuperacion_historial_destino")

        # Bloque AUTORIDAD OPERACIONAL / CONVERGENCIA -- SIN OCR: aplica el
        # mismo criterio determinista que `procesar_archivo` ya corre al
        # final de cada documento (un error pequeño de OCR no convierte
        # conocimiento fuertemente establecido en desconocido) a filas YA
        # PERSISTIDAS, para que una operación histórica se beneficie en la
        # próxima reconciliación natural sin reprocesar imágenes. Corre
        # temprano -- las revalidaciones de abajo y `reconciliar_bandeja_
        # decisiones` deben ver la identidad ya convergida. Nunca inventa
        # (dos candidatos plausibles / variación grande -> no toca la
        # fila), nunca oculta una contradicción documental real, nunca
        # pierde el valor OCR.
        # P0 CONVERGENCIA HISTÓRICA -- el sidecar OCR ya persistido puede
        # recuperar sólo ausencias geométricas seguras (guía/cliente/obra/
        # DESPACHAR A). Nunca OCR nuevo, nunca pisa decisión humana ni un
        # valor existente; deja su propia traza por fila y luego esta misma
        # batería normal decide catálogo, convergencia y pendientes.
        recuperacion_replay = recuperar_pendientes_desde_replay_traza_ocr_sin_ocr(
            raiz_atlas=raiz,
        )
        # MATERIAL no participa del replay. El único OCR posterior real es
        # focal y se limita a dos MATERIAL_AUSENTE con imagen preservada por
        # ciclo; su intento queda marcado para que abrir Desktop de nuevo no
        # transforme la reconciliación en OCR masivo.
        recuperacion_material_focal = recuperar_material_ausente_focal_controlado(
            raiz_atlas=raiz,
        )
        # Un clasificador mejorado debe alcanzar también filas históricas.
        # Es una función pura de descripcion_material y sólo cambia cuando
        # el resultado vigente difiere: idempotente y sin degradar texto.
        try:
            sincronizacion_tipo_carga = revalidar_tipo_carga_sin_ocr(ruta_dataset=dataset)
        except (OSError, ValueError):
            # Igual que el resto de la batería: un artefacto legacy de
            # esquema incompleto no puede impedir la reconciliación ni los
            # demás recuperadores. El revalidador conserva su contrato
            # estricto para sus llamadores directos.
            sincronizacion_tipo_carga = {"filas_totales": 0, "guias_actualizadas": []}
        por_reintentar.extend(recuperacion_replay.get("guias_actualizadas", []))
        por_reintentar.extend(recuperacion_material_focal.get("recuperados", []))
        por_reintentar = list(dict.fromkeys(por_reintentar))

        convergencia_identidad = revalidar_convergencia_identidad_sin_ocr(
            ruta_dataset=dataset, carpeta_catalogos=catalogos, guias_objetivo=guias_objetivo,
        )
        _marca_etapa("recuperacion_p0_y_convergencia_identidad")

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
        limpieza = (
            _sin_cambio_guias() if _bateria_compartida_sigue_fresca()
            else revalidar_motivo_destino_ya_confirmado_sin_ocr(
                ruta_dataset=dataset, carpeta_catalogos=catalogos,
            )
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
        limpieza_geo_contradiccion = (
            _sin_cambio_guias() if _bateria_compartida_sigue_fresca()
            else revalidar_destino_contra_comuna_documental_sin_ocr(ruta_dataset=dataset)
        )
        limpieza_material = (
            _sin_cambio_guias() if _bateria_compartida_sigue_fresca()
            else revalidar_material_estampado_persistido_sin_ocr(ruta_dataset=dataset)
        )
        # Bloque FECHA POR TELEMETRÍA -- caso real 0000354651 (472276/
        # 472277): igual que las dos limpiezas de arriba, existía y estaba
        # probada pero sólo se invocaba desde `revalidar_y_regenerar_
        # reporte` (aplicación de decisión / envío Mobile) -- se conecta
        # también aquí para que `CONFLICTO_FECHA` deje de verse en la
        # PRIMERA carga automática de Desktop, sin esperar una decisión
        # humana no relacionada. Sin OCR, sin red.
        limpieza_fecha_telemetria = (
            _sin_cambio_guias() if _bateria_compartida_sigue_fresca()
            else revalidar_fecha_por_telemetria_de_transporte_compartido_sin_ocr(ruta_dataset=dataset)
        )
        # Bloque ENTREGA A SEDE DEL PROPIO CLIENTE -- caso real 0000353062/
        # 464717 (cliente == obra_destino == "AMERICAN SCREW CHILE SPA",
        # ruta 35 km calculada): `revalidar_obra_destino_sin_ocr` ya retira
        # `OBRA_DESTINO_SIN_CORROBORAR` cuando `obra_destino` normaliza
        # EXACTO al `cliente` de la misma fila ("el mismo hecho dos veces")
        # o cuando el catálogo lo resuelve -- pero SÓLO se invocaba desde
        # `revalidar_y_regenerar_reporte` (decisión / envío Mobile). Aquí
        # se conecta también a la reconciliación de la carga de Desktop /
        # ingreso de un lote. Sin OCR, sin red.
        limpieza_obra_destino = (
            _sin_cambio_guias() if _bateria_compartida_sigue_fresca()
            else revalidar_obra_destino_sin_ocr(
                ruta_dataset=dataset, carpeta_catalogos=catalogos, ruta_ledger=actual / LEDGER,
            )
        )
        _marca_etapa("limpieza_motivos_destino_obra_material_fecha")
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
        limpieza_origen = (
            _sin_cambio_guias() if _bateria_compartida_sigue_fresca()
            else revalidar_origen_encabezado_no_confiable_sin_ocr(ruta_dataset=dataset)
        )
        # Bloque CIERRE ORIGEN GPS -- causa raíz real (472224): hermana de
        # la limpieza de arriba, misma filosofía -- un origen confirmado
        # por `resolver_planta_origen_gps` ANTES del fix que exige
        # contacto temporal real (nunca "único candidato" tratado como
        # sinónimo de "válido") queda con la firma exacta de ese bug para
        # siempre si nadie lo reintenta. Alineado con `revalidar_y_
        # regenerar_reporte` -- mismo orden, misma razón: un viaje no
        # debe obtener distinto origen únicamente por la puerta de
        # entrada (decisión vs. carga automática de Desktop).
        limpieza_origen_gps_candidato_unico = (
            _sin_cambio_guias() if _bateria_compartida_sigue_fresca()
            else revalidar_origen_gps_candidato_unico_sin_contacto_sin_ocr(
                ruta_dataset=dataset, carpeta_catalogos=catalogos,
            )
        )
        # Bloque R2.3 (adición) -- intenta resolver origen por eliminación
        # de categoría (planta documental YA identificada e incompatible)
        # -- misma función que ya usa `revalidar_y_regenerar_reporte`,
        # alineada aquí por el mismo principio de arriba.
        limpieza_origen_eliminacion_categoria = (
            _sin_cambio_guias() if _bateria_compartida_sigue_fresca()
            else revalidar_origen_por_eliminacion_categoria_sin_ocr(
                ruta_dataset=dataset, carpeta_catalogos=catalogos,
            )
        )
        # Bloque ORIGEN V3 -- CONVERGENCIA DE EVIDENCIA ANTES DE PREGUNTAR
        # -- causa raíz sistémica real (lote 2: 464730, 464631, 464529):
        # antes de dejar un origen sin determinar (o de dejarlo así
        # después de revertir un encabezado no confiable, arriba mismo),
        # cruza categoría real de la carga + naturaleza del destino
        # (externo vs. la propia planta) contra el catálogo -- corre
        # ANTES del reintento de ruta para que la misma pasada calcule
        # km/tiempo con el origen ya resuelto.
        limpieza_origen_categoria = (
            _sin_cambio_guias() if _bateria_compartida_sigue_fresca()
            else revalidar_origen_por_categoria_sin_candidato_sin_ocr(
                ruta_dataset=dataset, carpeta_catalogos=catalogos,
            )
        )
        # Bloque CAPABILITY SUITE DE ORIGEN -- corre DESPUÉS de la regla
        # por categoría, a propósito: así un hermano de transporte que
        # la categoría acaba de resolver ya está disponible para
        # propagarse, en la MISMA pasada, a cualquier otro documento del
        # mismo transporte sin categoría propia.
        limpieza_origen_hermano_transporte = (
            _sin_cambio_guias() if _bateria_compartida_sigue_fresca()
            else revalidar_origen_por_documento_hermano_de_transporte_sin_ocr(ruta_dataset=dataset)
        )
        # Bloque CIERRE DE ORQUESTACIÓN -- causa raíz real (472037):
        # un origen que quedó determinado ÚNICAMENTE por `PATRON_
        # VEHICULO_GPS_VECINOS` (evidencia de OTROS viajes del mismo
        # vehículo) nunca debió pisar un conflicto GPS REAL y propio de
        # ESTE documento (dos plantas con solape > 0%, o una detención
        # real). Corre justo antes del patrón de vecinos (más abajo, que
        # es la única función que puede producir esa firma) para que una
        # fila ya corregida por vías más fuertes (arriba) nunca vuelva a
        # quedar mal etiquetada por ese patrón en la MISMA pasada.
        limpieza_origen_vecinos_contra_evidencia_propia = (
            _sin_cambio_guias() if _bateria_compartida_sigue_fresca()
            else revalidar_origen_vecinos_gps_contra_evidencia_propia_real_sin_ocr(ruta_dataset=dataset)
        )
        # Bloque FINAL CORE V1 -- caso real 464981: vecinos temporales GPS
        # del mismo vehículo (ventana de días) -- misma función que ya usa
        # `revalidar_y_regenerar_reporte`, alineada aquí por el mismo
        # principio: un viaje no debe obtener distinto origen únicamente
        # por la puerta de entrada.
        limpieza_origen_vecinos = (
            _sin_cambio_guias() if _bateria_compartida_sigue_fresca()
            else revalidar_origen_por_vecinos_temporales_gps_sin_ocr(ruta_dataset=dataset)
        )
        # Bloque CAPABILITY SUITE DE ORIGEN (caso real 472477) -- última
        # vía automática antes de que el origen quede genuinamente sin
        # resolver: convergencia ABSOLUTA en TODO el historial confiable
        # de este mismo cliente (sin ventana temporal) -- corre DESPUÉS
        # de la regla por categoría, misma razón que en
        # `revalidar_y_regenerar_reporte`.
        limpieza_origen_historial_cliente = (
            _sin_cambio_guias() if _bateria_compartida_sigue_fresca()
            else revalidar_origen_por_historial_de_cliente_sin_ocr(
                ruta_dataset=dataset, carpeta_catalogos=catalogos,
            )
        )
        # Bloque FIX RUT AUSENTE -- caso real 464367 (CARLOS ÑANCUCHEO):
        # un chofer identificado por nombre pero sin RUT documental
        # (ausente o inválido) puede tener RUT canónico confiable en
        # catálogo o en el histórico del propio dataset -- función ya
        # existente y probada, sin flujo automático que la invocara.
        limpieza_rut_chofer = reconciliar_incidencias_rut_chofer_documental(raiz_atlas=raiz, reloj=lambda: instante)
        # Bloque FIX RUT DOCUMENTAL / ID PLACEHOLDER -- caso real WLADIMIR
        # AGUILAR (viaje 0000354443, ID interno `PENDIENTE00000006`): una
        # fila con `CHOFER_SIN_CORROBORAR` cuya identidad YA es inequívoca
        # (nombre exacto, único chofer activo del catálogo) + RUT
        # documental estructuralmente válido nunca se corroboraba porque
        # la corroboración por catálogo derivaba el RUT del ID interno --
        # y un ID placeholder no es un RUT. Sin OCR, sin red; misma lógica
        # que ya usa el pipeline al procesar un documento nuevo.
        limpieza_chofer_corroborado = revalidar_chofer_sin_corroborar_por_catalogo_sin_ocr(raiz_atlas=raiz)
        _marca_etapa("origen_y_chofer")
        # Codex 464784 (URUGUAY 15) -- reutiliza una ruta YA CALCULADA de
        # un documento hermano de la MISMA obra+planta con la MISMA
        # calle+número y comuna explícita sin contradicción, sin volver a
        # geocodificar ni tocar la red. Corre ANTES de los bloques de
        # geocodificación de abajo para que una guía resuelta aquí nunca
        # gaste un intento técnico en el proveedor externo en esta misma
        # pasada.
        recuperacion_ruta_historial_obra = (
            _sin_cambio_guias() if _bateria_compartida_sigue_fresca()
            else revalidar_ruta_por_historial_de_obra_sin_ocr(ruta_dataset=dataset)
        )
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
        limpieza_destino_coords = (
            {"destinos_actualizados": []} if _bateria_compartida_sigue_fresca()
            else revalidar_destinos_confirmados_sin_coordenadas_sin_ocr(
                carpeta_catalogos=catalogos, proveedor_rutas=proveedor_rutas,
            )
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
        # Bloque P2 RUTEO -- cola focal en vez de barrer todo el dataset:
        # `revalidar_ruta_con_destino_confirmado_en_catalogo_sin_ocr` ya
        # soporta `guias_objetivo` (el mismo contrato que ya usa el
        # reintento de ruta más abajo), pero nunca se lo pasaban -- barría
        # las 183 filas reales en cada pasada, incluidas las ~170+ que YA
        # tienen `estado_ruta == RUTA_CALCULADA` y que la función misma
        # descarta en su primera línea (`if estado_ruta == RUTA_CALCULADA:
        # continue`). Acotar aquí replica EXACTAMENTE ese mismo filtro --
        # ninguna fila que la función habría procesado deja de procesarse;
        # sólo se evita la iteración + búsqueda de catálogo de las que de
        # todos modos iba a descartar en la primera línea. Medido: el
        # revalidador más costoso de la batería (~6-7 s), dominado por
        # geocodificación real para las pocas filas que sí califican.
        try:
            guias_ruta_pendiente = {
                str(f.get("numero_guia", "")).strip()
                for f in _leer_filas(dataset)
                if str(f.get("estado_ruta", "")).strip() != EstadoRuta.RUTA_CALCULADA.value
            }
        except (OSError, ValueError):
            guias_ruta_pendiente = None  # ante cualquier duda, sin acotar -- barrido completo de siempre
        # Bloque P0 RECONCILIACIÓN FOCAL -- distinto del "P2 RUTEO" de
        # arriba (ese es un atajo de rendimiento puro, nunca deja de
        # procesar una fila elegible). Esto SÍ acota el universo cuando
        # `guias_objetivo` viene dado (focal): intersección, nunca
        # reemplazo -- una guía fuera del scope y ya con
        # `estado_ruta == RUTA_CALCULADA` seguía sin calificar de todos
        # modos, así que la intersección nunca oculta nada que el P2 de
        # arriba no hubiera descartado igual.
        if guias_objetivo is not None:
            guias_ruta_pendiente = (guias_ruta_pendiente or set()) & guias_objetivo
        limpieza_destino_catalogo = revalidar_ruta_con_destino_confirmado_en_catalogo_sin_ocr(
            ruta_dataset=dataset, carpeta_catalogos=catalogos,
            proveedor_rutas=proveedor_rutas, proveedor_rutas_fallback=proveedor_rutas_fallback,
            guias_objetivo=guias_ruta_pendiente,
            guias_excluir_reintento=guias_excluir_reintento_ruta,
        )
        # Bloque DESTINO HUMANO YA CONFIRMADO (Codex 472037) -- corre
        # ANTES del reintento de ruta de abajo, a propósito: llena
        # `despachar_a_crudo` desde una confirmación humana YA registrada
        # en el ledger que nunca pudo aplicarse porque el origen seguía
        # bloqueado en ese momento -- así el reintento de ruta, en la
        # MISMA pasada, ya tiene con qué intentar geocodificar. Ver
        # docstring de la función para el criterio completo (identidad
        # exacta guía+transporte, nunca sobrescribe un `despachar_a_crudo`
        # ya existente).
        destino_vacio_confirmado = (
            _sin_cambio_guias() if _bateria_compartida_sigue_fresca()
            else revalidar_destino_vacio_confirmado_por_documento_sin_ocr(
                ruta_dataset=dataset, ruta_ledger=actual / LEDGER,
            )
        )
        _marca_etapa("destino_ruta_y_geocoding")
        recuperacion = {"guias_actualizadas": []}
        if por_reintentar:
            recuperacion = revalidar_ruta_sin_destino_calculado_sin_ocr(
                ruta_dataset=dataset, carpeta_catalogos=catalogos,
                proveedor_rutas=proveedor_rutas,
                proveedor_rutas_fallback=proveedor_rutas_fallback,
                guias_objetivo=set(por_reintentar),
                guias_excluir_reintento=guias_excluir_reintento_ruta,
            )
        _marca_etapa("reintento_ruta_acotado_a_por_reintentar")
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
        limpieza_indicadores = (
            _sin_cambio_guias() if _bateria_compartida_sigue_fresca()
            else revalidar_indicadores_documentales_sin_ocr(ruta_dataset=dataset)
        )
        # Mobile debe leer el indicador YA convergido en esta misma
        # pasada. Si corriera antes, una fila con motivos canónicos
        # resueltos pero `indicador_revision` todavía obsoleto seguiría
        # dejando el envío en REQUIERE_REVISION; como el reporte publica
        # después la huella fresca, podría no existir una segunda pasada
        # natural que lo corrigiera.
        limpieza_mobile = revalidar_asociacion_mobile_sin_ocr(
            RepositorioEnviosMobile(raiz_atlas=raiz), dataset=dataset,
        )
        _marca_etapa("indicadores_y_mobile")
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
        evidencia_decisiones = reconciliar_bandeja_decisiones(
            raiz_atlas=raiz, reloj=lambda: instante, cache_memoizacion=_cache_regenerar_decisiones,
        )
        _marca_etapa("bandeja_decisiones_evidencia")
        # Bloque AUTORIDAD OPERACIONAL / SEGUNDA PASADA UNIVERSAL -- SIN
        # OCR, SIN RED: TODA decisión pendiente CLIENTE_CANDIDATO/CLIENTE_
        # DESCONOCIDO/OBRA_DESCONOCIDA/VEHICULO_DESCONOCIDO pasa por
        # convergencia determinista antes de quedar para Javier -- misma
        # oportunidad que un lote nuevo, ahora también para una operación
        # histórica. Corre DESPUÉS de `reconciliar_bandeja_decisiones`
        # (sobre la bandeja ya regenerada/enriquecida) y republica por el
        # mecanismo canónico (filtra contra el ledger: ninguna decisión
        # humana se pierde ni se duplica). `orquestador=None` -> nunca B1
        # aquí (la reconciliación histórica se mantiene determinista).
        archivos_objetivo_focal = None
        if guias_objetivo is not None:
            try:
                archivos_objetivo_focal = {
                    str(f.get("archivo", "")).strip()
                    for f in _leer_filas(dataset)
                    if str(f.get("numero_guia", "")).strip() in guias_objetivo
                    and str(f.get("archivo", "")).strip()
                }
            except (OSError, ValueError):
                archivos_objetivo_focal = None  # ante cualquier duda, sin acotar
        segunda_pasada_historica = reconciliar_segunda_pasada_universal_sin_ocr(
            raiz_atlas=raiz, reloj=lambda: instante,
            archivos_objetivo=archivos_objetivo_focal, cache_memoizacion=_cache_regenerar_decisiones,
        )
        _marca_etapa("segunda_pasada_universal_sin_ocr")
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
        deteccion_destino = reconciliar_decisiones_destino_no_resuelto(
            raiz_atlas=raiz, reloj=lambda: instante, cache_memoizacion=_cache_regenerar_decisiones,
        )
        _marca_etapa("destino_no_resuelto")
        _t_bateria_fin = time.perf_counter()

        # Bloque REEVALUACIÓN RETROACTIVA UNIVERSAL -- traza: qué
        # dominio-versión retiró qué pendiente. La batería de arriba YA
        # regeneró bandeja y pendientes técnicos por el mecanismo
        # canónico; aquí sólo se comparan los snapshots ANTES/DESPUÉS y se
        # atribuye cada retiro al/los dominio(s) que lo gobiernan y
        # avanzaron. Si una capacidad no aportó evidencia, su pendiente
        # sigue en pie (`decisiones_retiradas`=0) -- nunca se inventa.
        # `duracion_ms` mide SÓLO esta comparación (antes medía por error
        # toda la batería de arriba, ver bloque MÉTRICAS DE DURACIÓN POR
        # ETAPA al inicio de la función -- `tiempos_ms`/`duracion_bateria_
        # completa_ms` en el resultado es donde vive ese costo real).
        _t_reeval_comparacion_inicio = time.perf_counter()
        try:
            _decisiones_despues = json.loads(decisiones.read_text(encoding="utf-8")).get("decisiones", []) if decisiones.is_file() else []
        except (OSError, ValueError):
            _decisiones_despues = list(_decisiones_antes)
        try:
            _tecnicos_despues = json.loads(ruta_pendientes.read_text(encoding="utf-8")).get("pendientes", []) if ruta_pendientes.is_file() else []
        except (OSError, ValueError):
            _tecnicos_despues = list(_tecnicos_antes)
        reevaluacion_retroactiva = _resumen_reevaluacion(
            avanzadas=capacidades_a_reevaluar,
            decisiones_antes=_decisiones_antes, decisiones_despues=_decisiones_despues,
            tecnicos_antes=_tecnicos_antes, tecnicos_despues=_tecnicos_despues,
            duracion_ms=round((time.perf_counter() - _t_reeval_comparacion_inicio) * 1000),
        )
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
            # 2B -- el ledger pudo avanzar durante esta reconciliación
            # (una decisión aplicada arriba): se re-lee para el estado de
            # ciclo de vida.
            guias_direccion_confirmada = set(_guias_con_direccion_confirmada_por_humano(
                actual / "decisiones_aplicadas.json"
            ))
            # Bloque SEPARAR CONOCIMIENTO DE DESTINO DE RESOLUCIÓN TÉCNICA
            # DE RUTA -- caso real 464746: una guía con `GEOCODIFICACION_
            # DEMASIADO_GENERICA` cuya obra<->destino ya está CONFIRMADA a
            # nivel humano nunca debe reportar `ESPERANDO_ACCION_HUMANA`
            # en `pendientes_tecnicos.json` -- ninguna tarjeta existe para
            # que un humano actúe (`regenerar_decisiones_persistidas` ya
            # la suprime); el ciclo de vida debe reflejar el mismo hecho.
            try:
                guias_direccion_confirmada |= guias_destino_conocido_ruta_pendiente(
                    carpeta_catalogos=catalogos, ruta_dataset=dataset,
                )
            except (OSError, ValueError, AttributeError):
                pass
            guias_destino_terminado = _guias_destino_terminado_por_humano(
                actual / "decisiones_aplicadas.json"
            )
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
                # Bloque GEOGRAFÍA 2B -- estado de ciclo de vida explícito y
                # convergente: `clase_fallo` + `estado_espera` +
                # `causa_siguiente_accion` + `proxima_oportunidad` (ISO real
                # o null). Ningún pendiente queda "guardado y quizá algún
                # día se arregle".
                registro.update(_ciclo_vida_pendiente(
                    registro, instante=instante,
                    direccion_confirmada_por_humano=guia in guias_direccion_confirmada,
                    destino_terminado_por_humano=guia in guias_destino_terminado,
                ))
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
            _tiempos_ms["post_proceso_pendientes_y_generar_reporte"] = round(
                (time.perf_counter() - _t_bateria_fin) * 1000, 1
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
                # Bloque REEVALUACIÓN RETROACTIVA UNIVERSAL -- se estampan
                # las versiones de capacidad vigentes: la próxima
                # reconciliación no reevalúa un dominio que no avanzó
                # (idempotencia), y una futura mejora (subir una versión)
                # se detecta contra esta foto.
                versiones_capacidades=_versiones_cap_actuales(),
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

    resultado_final = {
        "reconciliado": True,
        "version": VERSION_ESTADO_DERIVADO,
        "respaldo": str(respaldo),
        "reporte_vigente": str(reporte),
        "guias_actualizadas": sorted(
            set(limpieza["guias_actualizadas"])
            | set(limpieza_material["guias_actualizadas"])
            | set(limpieza_origen["guias_actualizadas"])
            | set(limpieza_origen_gps_candidato_unico["guias_actualizadas"])
            | set(limpieza_origen_eliminacion_categoria["guias_actualizadas"])
            | set(limpieza_origen_hermano_transporte["guias_actualizadas"])
            | set(limpieza_origen_vecinos_contra_evidencia_propia["guias_actualizadas"])
            | set(limpieza_origen_vecinos["guias_actualizadas"])
            | set(limpieza_origen_categoria["guias_actualizadas"])
            | set(limpieza_origen_historial_cliente["guias_actualizadas"])
            | set(limpieza_rut_chofer["rut_corregido_en_dataset"])
            | set(limpieza_chofer_corroborado["guias_actualizadas"])
            | set(limpieza_indicadores["guias_actualizadas"])
            | set(limpieza_destino_catalogo["guias_actualizadas"])
            | set(limpieza_geo_contradiccion["guias_actualizadas"])
            | set(limpieza_obra_destino["guias_actualizadas"])
            | set(destino_vacio_confirmado["guias_actualizadas"])
            | set(recuperacion_replay["guias_actualizadas"])
            | set(recuperacion_material_focal["recuperados"])
            | set(sincronizacion_tipo_carga["guias_actualizadas"])
        ),
        "destino_vacio_confirmado_desde_ledger": destino_vacio_confirmado["guias_actualizadas"],
        "destinos_historial_recuperados": recuperacion_historial_destino,
        "destinos_historial_revertidos": reversion_historial_destino,
        "destinos_rechazados_por_evidencia_b1": rechazo_evidencia_destino["guias_actualizadas"],
        "guias_recuperadas": guias_recuperadas,
        "guias_contradiccion_destino_catalogo": limpieza_destino_catalogo["guias_contradiccion"],
        "destinos_coordenadas_completadas": limpieza_destino_coords["destinos_actualizados"],
        "decisiones_destino_no_resuelto_publicadas": deteccion_destino["decisiones_publicadas"],
        "envios_mobile_actualizados": limpieza_mobile["actualizados"],
        "decisiones_aplicadas_automaticamente": evidencia_decisiones["decisiones_aplicadas_automaticamente"],
        "convergencia_identidad_sin_ocr": {
            "filas_convergidas": convergencia_identidad["filas_convergidas"],
            "resoluciones": convergencia_identidad["resoluciones"],
            "contradicciones": convergencia_identidad["contradicciones"],
        },
        "recuperacion_p0": {
            "replay": recuperacion_replay,
            "material_focal": recuperacion_material_focal,
            "tipo_carga": sincronizacion_tipo_carga,
        },
        "segunda_pasada_universal_sin_ocr": segunda_pasada_historica,
        "reevaluacion_retroactiva": reevaluacion_retroactiva,
        "pendientes_tecnicos": len(registros_despues),
        "totales": manifest["totales"],
        "ocr_ejecutado": False,
        "reporte_regenerado_por_dataset_desactualizado": reporte_desactualizado,
        "reporte_regenerado_por_estado_derivado_incoherente": estado_derivado_incoherente,
        # Bloque MÉTRICAS DE DURACIÓN POR ETAPA -- ver comentario al inicio
        # de la función. `tiempos_ms` es aditivo (cada etapa mide sólo lo
        # transcurrido desde la marca anterior); `duracion_bateria_
        # completa_ms` es el total de arriba, útil para comparar contra
        # `reevaluacion_retroactiva.duracion_ms` (que ahora sólo mide su
        # propia comparación, no toda la batería).
        "tiempos_ms": _tiempos_ms,
        "duracion_bateria_completa_ms": round((time.perf_counter() - _t_bateria_inicio) * 1000, 1),
    }
    _registrar_diagnostico_reconciliacion(
        raiz=raiz, guias_objetivo=guias_objetivo, instante=instante, resultado=resultado_final,
    )
    return resultado_final
