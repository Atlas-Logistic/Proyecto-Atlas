# Ingreso Mobile con alcance causal — preparado, no instalado

Base operativa verificada antes de editar: 6af7836 (sobre b272104), árbol limpio de CASA. Desarrollo en worktree aislado. PULL Disabled y sin gate durante todo este encargo. No se consumieron envíos ni se restauró la guía afectada.

## Causa reconstruida
El ciclo preservado 22/10/2026 16:18:15–16:26:03 confirmó cuatro envíos y ejecutó reconciliación global de bandeja. Hubo dos ampliaciones independientes:

1. `procesar_y_revalidar_envio_mobile` -> `_regenerar_reporte_tras_envio_mobile` -> `revalidar_y_regenerar_reporte` sin `guias_objetivo`. La batería leyó todas las filas; `revalidar_destino_contra_comuna_documental_sin_ocr` detectó la contradicción de calle de 482188 y retiró once campos derivados de entrega/ruta/códigos geográficos. El fallo de alcance no prueba que el destino antiguo fuera correcto.
2. `cloud_mobile_sync_cliente` -> `reconciliar_bandeja_diferida_mobile` -> `reconciliar_bandeja_decisiones` sin alcance. El resumen durable acredita `ejecutada=true`. La fusión inicial de tarjetas y la reevaluación de asociaciones también recorrían elementos ajenos sin limitar quién podía escribirse.

Las protecciones ya estaban disponibles: `alcance_guias`, lectura/escritura focal del dataset, `guias_objetivo` en la batería/reconciliador y `conservar_decisiones_ajenas`. El ingreso no les entregaba su alcance.

## Cambio mínimo en Motor
Solo `atlas_core/mobile.py` de producción:
- Calcula el cierre causal de documentos canónicos, guías, transportes válidos y vínculos explícitos lote/evidencia. No amplía por chofer, cliente, obra o fecha comunes, ni por transporte placeholder. Compartir tanda no incorpora otro transporte ya identificado: el respaldo de lote alcanza solo hermanos que aún no tienen transporte, y las otras lecturas permanecen como evidencia. La identidad de fila canónica prevalece sobre OCR histórico del reenvío. Un alcance heredado se intersecta, nunca se amplía.
- Pasa guías explícitas al reporte y al reconciliador síncrono/diferido. La pasada diferida mantiene también el contexto focal durante las aplicaciones automáticas anidadas y sigue siendo una sola por unión de solicitudes pendientes, preservando solicitud_id, reintentos y marca de completada únicamente cuando corrió el reconciliador.
- Rodea la fusión inicial de decisiones y las tarjetas del reenvío canónico con el contexto focal existente. Conserva decisiones ajenas incluso si un mantenimiento global las habría retirado/enriquecido.
- Limita los envíos que la asociación puede actualizar. Sigue leyendo las otras filas como evidencia; conserva la convergencia transitiva de lote, la escritura del transporte de hermanas y la segunda publicación si esa convergencia cambia el dataset.
- `revalidar_asociacion_mobile_sin_ocr` conserva su API de mantenimiento sin filtro para callers explícitos de mantenimiento. Las entradas de ingreso pasan siempre envíos causales. No cambia reglas OCR/asociación, ACK, mutex, lease ni el consumidor.

El reporte publicado sigue conteniendo toda la operación. La focalidad restringe revalidación/escritura de filas y tarjetas; no recorta qué viajes puede mostrar el reporte. Sin identidad de guía se usa conjunto vacío, nunca `None` global. Esquema de entrada/salida y estado Mobile se conservan.

## Pruebas y límites
La regresión ingresa una guía nueva mediante el pipeline real, con OCR simulado y batería/bandeja reales en una raíz temporal. Valida fila 482188, todas las filas previas, tarjetas presentes/latentes, ledger y catálogos idénticos, más nueva fila y reporte. Las cuatro variantes (síncrono/diferido, con/sin tarjetas previas) fallan sobre 6af7836 y pasan con el cambio.
Otras regresiones: hermana de mismo transporte que sí debe converger; respaldo por lote transitivo; no escribir un envío ajeno; evidencia firmada y reenvío canónico; preferir identidad canónica frente a OCR histórico contradictorio; vacío no global; unión de pendientes; no ampliar contexto heredado; entradas de reporte/bandeja/publicación siempre focales.
Los sustitutos de tres pruebas previas aceptan el nuevo argumento de filtro; conservan sus aserciones de fallos/reintento/convergencia. No se introdujeron fallbacks para evitar el filtro en código productivo.
El ensayo ampliado usa proveedor simulado por defecto y prohíbe `pip install` con el plugin optativo `tests.ensayo_mobile_sin_ocr`: algunas pruebas previas preparaban un runtime Paddle al no sustituir su fábrica. Un primer ensayo se detuvo al detectar esa preparación en un perfil temporal; no se tocó el runtime operativo. No son ensayos OCR ni Cloud reales. Resultado cuantitativo y logs en el informe local del encargo.

## Pendiente antes de instalar/reactivar
Este encargo solo publica. No hacer fast-forward del Motor operativo ni activar la tarea con esta documentación.
1. Revisar diff y alcance causal, especialmente lote multiviaje, reenvíos y vínculos de evidencia, con las reglas de producto existentes. Si hay agrupaciones manuales entre varios transportes, confirmar explícitamente si añaden una relación causal documental; este incremento conserva la identidad por transporte y vínculos Mobile existentes, sin inventar nuevas agrupaciones.
2. Autorizar instalación por separado; comprobar base operativa/árbol/reservas, respaldo y ausencia de procesos activos. Mantener mismo protocolo de exclusividad y controles de RapidOCR ya instalados; verificar integridad de datos/configuración al desplegar.
3. Con exclusividad demostrada frente a OFICINA, emitir autorización nueva y validar una recepción futura controlada, publicación y ACK más un ciclo automático posterior. No reprocesar los cuatro recuperados ni usar 482188 para probarlo. Comparar filas/tarjetas/decisiones ajenas antes/después.
4. Resolver la reparación de 482188 como acción independiente con evidencia humana y vista previa focal. No restaurarla desde snapshot ni confundir pérdida fuera de alcance con validez de la dirección anterior.

Evidencia privada y propuesta separada: C:/Atlas/diagnostico-mobile-20261022/correccion-alcance/REPARACION_482188.md. Sin datos privados de muestras/fotografías incorporados al repositorio; referencia visual de Code intacta.

Resultado final: 17 regresiones nuevas aprobadas; conjunto ampliado 326 aprobadas y 1 excluida en 89.14s. La excluida es `test_m2_origen_mobile_b1_decisiones.py::test_ambiguedad_real_de_origen_desde_mobile_genera_decision_visible` (espera una tarjeta ORIGEN_NO_CONFIRMADO, obtiene cero), reproducida fallando también en worktree base 6af7836 con el mismo proveedor simulado. No se corrigió ni se ocultó como fallo nuevo. El ensayo anterior completo dio 323 aprobadas + esa falla antes de añadir los últimos casos de tanda multiviaje y autoaplicación anidada.

Comando del conjunto: `python -B -m pytest -p tests.ensayo_mobile_sin_ocr` sobre todos los `tests/test_mobile*.py`, más `test_cloud_mobile_sync_cliente.py`, `test_cloud_mobile_recepcion_intercalada.py`, `test_sincronizar_mobile_cloud_escritor.py`, `test_lease_multiequipo.py`, `test_bandeja_alcance_focal_p0.py`, `test_decision_alcance_focal_p0.py`, `test_m2_origen_mobile_b1_decisiones.py`, con `--deselect` del caso previo identificado. Las cuatro variantes principales de la nueva regresión fallaron sobre la base y pasaron corregidas. La copia base contiene solo el test añadido y el plugin de ensayo, no el cambio productivo.

Antes de instalar/reactivar también debe revisarse la visibilidad de la decisión de origen en configuración real o resolverse/aceptarse explícitamente esa limitación previa de la suite. No se declara validado un ciclo productivo futuro ni el cambio automático entre equipos.
