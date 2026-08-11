# Bitácora Técnica Cronológica — Proyecto Atlas

Registro técnico, en orden cronológico, de cambios de código sobre el lector de guías. Un bloque por entrada, con archivos modificados, decisión de diseño y validación.

---

## 2026-08-11 — Cierre: migración de endpoint ORS + validación real con credencial

**Rama:** `lector-mvp-guia-nueva` · **Baseline previo:** `ccc777229cbd072b1f89e5d60efbd5620859731a`

### Problema real confirmado

- El adaptador `atlas_core/rutas/openrouteservice.py` apuntaba a `https://api.openrouteservice.org`, host que HeiGIT (operador de OpenRouteService) deprecó el 2026-04-28 en favor de `api.heigit.org`, con apagado definitivo confirmado para el **2026-08-24**. Verificado contra el hilo oficial de anuncio (`ask.openrouteservice.org`) y confirmado en vivo: ambos hosts responden `401 Unauthorized` (no `404`) sin credencial, es decir la ruta nueva ya existe y responde.

### Diseño

- Migración centralizada de 2 constantes de clase en `OpenRouteService`:
  - `URL_GEOCODIFICACION`: `https://api.openrouteservice.org/geocode/search` → `https://api.heigit.org/pelias/v1/search` (la geocodificación migró a la estructura Pelias, no es un simple cambio de dominio).
  - `URL_DIRECCIONES`: `https://api.openrouteservice.org/v2/directions/{perfil}` → `https://api.heigit.org/openrouteservice/v2/directions/{perfil}`.
- Sin cambios de autenticación (misma API key sirve para ambos hosts, confirmado en el anuncio oficial) ni de contrato (`ProveedorRutas`, `ResultadoRuta`, `EstadoRuta` sin tocar) — cambio estrictamente de host/ruta.
- **Configuración de credencial, sin exposición:** `OPENROUTESERVICE_API_KEY` se configuró como variable de entorno de **usuario** de Windows, escrita por Javier directamente con `[Environment]::SetEnvironmentVariable(...,"User")` en su propia terminal — nunca visible para Claude. Para las pruebas reales, la clave se puenteó al proceso hijo dentro de una sola invocación (`$env:OPENROUTESERVICE_API_KEY = [Environment]::GetEnvironmentVariable(...,"User")` inmediatamente antes de invocar Python), sin imprimirla ni guardarla en ningún archivo — necesario porque una variable de usuario recién creada no se propaga a procesos ya en ejecución, solo la lectura directa del registro la ve.

### Validación

- Tests nuevos: 2 en `tests/test_rutas_openrouteservice.py` (`test_direcciones_usa_endpoint_heigit_vigente`, `test_geocodificacion_usa_endpoint_heigit_pelias_vigente`) — fijan el host/ruta vigente con el mismo patrón de transporte simulado que ya usaba el resto del archivo (sin red real), para que una regresión al host deprecado la detecte la suite antes de producción.
- Suite completa: **601 → 603 passed**, 0 failed.
- **Prueba real de credencial** (`driving-hgv`, AZA RENCA → EBEMA SA): `EstadoRuta.RUTA_CALCULADA` (no `SIN_CREDENCIAL`), tiempo de respuesta 1.02s.
- **3 rutas reales**, coordenadas ya existentes en catálogo (`plantas.json`/`destinos_maestros.json`, sin geocodificar de nuevo — AZA COLINA reutiliza la coordenada ya geocodificada para la misma dirección física bajo "ACEROS AZA SA", igual que en RUTAS-EVAL R1):
  | origen | destino | km | min | estado | t (s) |
  |---|---|---|---|---|---|
  | AZA_RENCA | EBEMA SA (Galvarino 8501) | 7.43 | 12.06 | RUTA_CALCULADA | 0.80 |
  | AZA_COLINA | Torres Ocaranza Ltda | 49.70 | 59.87 | RUTA_CALCULADA | 0.80 |
  | AZA_RENCA | DSI Underground Chile SpA | 33.17 | 40.41 | RUTA_CALCULADA | 0.86 |
- **Caché verificado end-to-end** (no solo unitario): `ServicioRutas.confirmar_y_calcular` con `Planta`/`Destino` reales (`AZA RENCA` → `TORRES OCARANZA LTDA`, catálogo real) contra un `RepositorioRutas` apuntando a un archivo de prueba en `Desktop\Atlas\rutas_eval\cache_prueba_rutas.json` (fuera del repo, no se tocó ningún catálogo de producción). 1ª llamada: `RUTA_CALCULADA`, 1 llamada real a ORS (contada con un wrapper que subclasea `OpenRouteService.calcular_ruta`, sin modificar el adaptador). 2ª llamada idéntica: `RESULTADO_DESDE_CACHE`, **0 llamadas nuevas a ORS**, mismo `distancia_km`/`duracion_estimada_min`. Clave lógica confirmada: `planta_id + destino_id + perfil + proveedor + version` (`RepositorioRutas.buscar_vigente`).
- **0 secretos en git**: verificado con `grep` sobre los artefactos guardados (`rutas_eval/*.json`) antes de commitear — sin `Authorization`/`Bearer`/valor de clave en ningún archivo persistido, dentro ni fuera del repo.
- Archivos modificados: `atlas_core/rutas/openrouteservice.py`, `tests/test_rutas_openrouteservice.py`. Sin cambios en `atlas_core/rutas/{modelos,proveedor,servicio,repositorio}.py`, catálogos, Desktop, ni ningún archivo `.env`.

### Continuidad

- **Siguiente bloque:** conectar km/tiempos al flujo real (Desktop, generación de reportes) usando el módulo `atlas_core/rutas/` ya validado con credencial real. No iniciado — explícitamente fuera de alcance de este bloque ("No tocar Desktop todavía. No integrar km en UI todavía.").

---

## 2026-08-11 — Cierre Bloque D1: separar GIRO de obra_destino

**Rama:** `lector-mvp-guia-nueva` · **Baseline previo:** `66d0edabbfd506795dc675f2149e4875dc6fede2`

### Problema real confirmado

- Guía real `464170`. Con cliente/chofer/RUT ya corregidos por C1, `obra_destino` seguía devolviendo `"VENTA AL POR MAYOR D"` (el valor de GIRO) en vez del destino real `"SUPERMERCADO SEÑOR DE LOS MI"`. Diagnóstico previo (bloque anterior) ya había identificado la causa como "la geometría asocia el valor de GIRO como obra/destino".

### Diseño

- **Causa exacta, localizada en `_extraer_asociaciones_geometricas` (`atlas_core/extractor.py`):**
  1. `nominal()` (filtro de candidatos válidos) tenía `"SENOR"` en su lista de exclusión por subcadena — heredada de antes de C1. El candidato correcto de obra_destino, "SUPERMERCADO SEÑOR DE LOS MI", contiene esa palabra y quedaba excluido como candidato, aunque geométricamente fuera el mejor (score 0.147 vs 0.496 del valor de GIRO, verificado con las cajas reales exactas).
  2. Sin ese candidato, el único bloque que sobraba dentro del umbral de puntaje cerca de la etiqueta "OBRA DESTINO" era el valor de GIRO — en la columna vecina de la misma fila (este proveedor AZA imprime SEÑOR(ES)/R.U.T./GIRO/DIRECCION en la columna izquierda y SOLICITANTE/TELEFONO/OBRA DESTINO/COD DESTINATARIO en la derecha, ambas alineadas por fila) — y no existía ninguna regla que impidiera que GIRO ganara por default al ser la única opción restante.
- **Fix Parte B (extensión del fix C1 al lado del candidato):** se removió `"SENOR"` de la tupla `exclusiones` de `nominal()` y se agregó en su lugar `if _es_etiqueta_senor(texto): return False` — ahora solo se descarta un candidato si el bloque completo *es* la etiqueta SEÑOR(ES)/SEÑORES/SEÑOR(IES)/SEÑORIES, no si la palabra aparece dentro de un nombre real más largo. Mismo criterio ya validado en C1 para el lado de la etiqueta.
- **Fix Parte C (GIRO nunca elegible como obra/destino):** nueva `es_etiqueta_giro(item)` (`item["simple"] == "GIRO"`, exacto). Se probó primero una exclusión por **comparación de distancias** (candidato más cerca de GIRO que de la etiqueta destino real → descartado) — **descartada tras fallar en un test unitario minimal**: con GIRO y OBRA DESTINO como columnas vecinas casi equidistantes de sus valores, la diferencia de distancia puede ser de 1-2 px, insuficiente para garantizar la exclusión de forma robusta. Solución final: `_mejor_candidato(etiqueta)` calcula, con la misma `puntuar()` ya existente, cuál sería el candidato de mejor puntaje para una etiqueta dada; se aplica a cada etiqueta GIRO para obtener el conjunto `valores_giro` (por `id()` de objeto, no por texto) y esos candidatos quedan excluidos, por identidad, de la lista de candidatos válidos para `campo == "obra destino"` — sin importar cuán cerca o lejos estén de la etiqueta de destino real. Garantiza estructuralmente que GIRO nunca puede ganar, sin depender de umbrales de proximidad.
- **Bug colateral encontrado y corregido (Parte D de C1, `_extraer_rut_cliente_geometrico`):** al reconstruir un test con las cajas reales exactas de la guía 464170 (en vez de las coordenadas redondeadas usadas en C1), `_extraer_rut_cliente_geometrico` dejó de encontrar el RUT — su ancla `0 < item["y1"] - etiqueta_cliente["y2"]` exige un hueco **estrictamente positivo** entre las etiquetas SEÑOR(ES) y R.U.T., pero en el documento real esas dos filas quedan con cajas exactamente adyacentes (SEÑOR(ES) termina en y=570, R.U.T. empieza en y=570 — gap 0). Este bug ya existía desde C1: el "caso real obligatorio" reportado entonces (`rut_cliente = 83.585.400-0`) se verificó solo contra un test unitario con coordenadas redondeadas que por casualidad tenían un hueco de 3px, nunca contra las cajas reales completas — y el campo "RUT del cliente" ni siquiera se expone en el dict que devuelve `procesar_archivo` (solo se usa internamente para homologar `cliente` vía RUT contra `empresas.json`), por lo que el error pasó inadvertido porque el nombre OCR de EBEMA SA ya coincidía textualmente con el nombre canónico del catálogo. Corregido: `0 <` → `0 <=` (acepta gap cero, cajas adyacentes). Confirmado con las cajas reales completas: `_extraer_rut_cliente_geometrico` ahora sí devuelve `{"valor": "83.585.400-0"}`.
- **Catálogo (Paso 4, solo inspección):** `%LOCALAPPDATA%\Atlas\datos\catalogos_privados\destinos_maestros.json` (schema `{"version_formato":..., "destinos":[...]}`, 47 registros) contiene un destino con `cliente_id` idéntico al de EBEMA SA en `clientes.json` (`fb859a71-d7b7-453f-9f27-34b24eb59139`): dirección `GALVARINO 8501, QUILICURA, CHILE`, ya geocodificada (`lat=-33.370934, lon=-70.716168`, fuente `GEOCODIFICACION_ORS`, `match_type=fallback`, `confidence=0.8`), 34 viajes observados en el período. El `nombre_destino` canónico ahí es la dirección, no el nombre comercial leído por OCR ("SUPERMERCADO SEÑOR DE LOS MI") — homologar obra_destino contra este catálogo por `cliente_id` requeriría cruzar `clientes.json`→`destinos_maestros.json`, una integración nueva no implementada en D1 (el enriquecimiento existente, `_buscar_destino_en_textos` contra `destinos.json` por código de destinatario, no encuentra coincidencia para el código `0002013046` de esta guía — `destinos.json` solo tiene 6 registros — y correctamente se abstiene sin fabricar nada).
- No se tocó PaddleOCR, ni Desktop, ni `buscar_obra_destino()` (camino lineal, sin cambios — mismo criterio que C1 de no reescribir el extractor histórico de una sola línea).

### Validación

- Tests nuevos: 6 en `tests/test_extraer_datos.py` (GIRO ya no confunde con destino real usando geometría de la guía 464170; GIRO nunca se devuelve como obra_destino aunque sea el único bloque cercano; solo GIRO sin etiqueta de destino no inventa nada; obra con palabra SEÑOR no crea etiqueta falsa de cliente; obra_destino ambiguo se abstiene; no-regresión consolidada de cliente/chofer/RUT-cliente junto a obra_destino usando cajas reales completas) + 1 en `tests/test_catalogos.py` (obra_destino ya extraída se homologa a su nombre canónico vía código de destinatario).
- Suite completa: **594 → 601 passed**, 0 failed. Sin necesidad de tocar ningún test ya existente (a diferencia de C1) — este fix no activa ninguna ruta nueva de lectura de bloques que algún test ya mockeara.
- **Validación real, guía `464170`, PaddleOCR GPU real, catálogo activo real (mismo usado en C1, ya con IVAN ROA):**
  - `obra_destino`: `"VENTA AL POR MAYOR D"` → **`"SUPERMERCADO SEÑOR DE LOS MI"`**.
  - `cliente=EBEMA SA`, `chofer=IVAN ROA`, `rut_chofer=10190440-7`, `numero_guia=464170`, `numero_transporte=0000351177` — sin cambios respecto a C1.
  - `indicador_revision`: `REVISAR` (sin cambio; sigue siendo correcto — el documento continúa necesitando recuperación geométrica de varios campos).
  - Viaje agrupado (`agrupar_viajes`): `REQUIERE_REVISION`, motivo `DOCUMENTO_REQUIERE_REVISION` (sin cambio respecto a C1).
- **Validación adicional corta, 4 guías reales con obra_destino ya conocido antes de este fix** (`464511`→ARMACERO MATCO SA, `464493`→EMPRESA CONST SIGRO, `464479`→AMERICAN SCREW CHILE SPA, `464494`→ACEROS COX COMERCIAL SA), reprocesadas con PaddleOCR GPU real + catálogo activo real: **cliente, obra_destino, chofer e indicador_revision idénticos antes/después en las 4** — 0 regresiones.
- Archivos modificados: `atlas_core/extractor.py`, `tests/test_extraer_datos.py`, `tests/test_catalogos.py`. Sin cambios en `atlas_core/procesamiento_masivo.py`, `atlas_core/gestor_viajes.py`, `atlas_core/catalogos.py`, OCR (`atlas_core/ocr.py`, `atlas_core/ocr_provider.py`, `atlas_core/paddle_runtime.py`) ni Desktop.

### Continuidad

- **Siguiente bloque oficial: RUTAS-EVAL / RUTAS R1** — comparación corta de proveedores de ruteo y recuperación de infraestructura de km/tiempos. Insumo directo ya disponible: el destino ahora se extrae correctamente, y `destinos_maestros.json` ya tiene la dirección canónica geocodificada de EBEMA SA (y de otros clientes) lista para homologar por `cliente_id` — esa homologación específicamente queda para ese bloque, no se implementó aquí. No iniciado.

---

## 2026-08-11 — Cierre RUTAS R1: km/tiempos conectados al viaje + auditoría Onelogis

**Rama:** `lector-mvp-guia-nueva` · **Baseline previo:** `5f201d418a3fcd6ee1287d1e05b1335efe87e043`

### Auditoría Onelogis/GPS (Paso 1)

- **Búsqueda:** `grep -rli onelogis` sobre todo `Desktop\Atlas` (repo + Desktop app + backup) más `git log --all -i -S"onelogis"`. Hallazgo: `Atlas-Viajes-Desktop-Restaurado/src/gps_logic.js` (función `obtenerUltimasPosicionesGps`), consumida desde `main.js` (IPC `atlas:gps-obtener-posiciones`, `atlas:gps-estado-configuracion`, `atlas:gps-configurar`) y renderizada en `src/gps_ui.js` (mapa Leaflet, pestaña GPS del Desktop). Configuración persistida vía electron-store (`gps_config.json`: `url` + `apiKey`, ya detectada en un bloque anterior de este mismo día).
- **Esquema real de datos, por bloque `vehiculo`:** `{patente, estado, latitude, longitude, speed, timestamp}`; `estado !== "REPORTADO"` implica sin dato reciente. **Es exclusivamente snapshot de última posición** — la UI hace polling cada 30s (`INTERVALO_REFRESCO_MS`) mientras la pestaña está abierta; no hay parámro de fecha/rango en la llamada (`GET .../gps/ultimas-posiciones`, sin query de tiempo) ni ningún otro archivo/endpoint de histórico en todo el árbol (`grep` de "historico"/"historial"/"timeseries" sin resultados relevantes; sin código de backend/Lambda en el repo).
- **Conclusión:** Onelogis está integrado y funcionando, pero la única capacidad disponible es "dónde está el camión ahora", no "dónde estaba a las X". Para el flujo real de Atlas (guías OCR'd después del hecho, no en tiempo real), esto significa que la resolución de planta por GPS **no puede alimentarse con datos históricos reales hoy** — es una limitación estructural de la integración actual, no del código de este bloque.
- **Hallazgo adicional (contexto, no usado en este bloque):** existe una rama remota `origin/feature-cobertura-origen-fase1` (divergente de `lector-mvp-guia-nueva` desde antes de `61958f2`, con 54 archivos de test vs. los actuales) que contiene `_resolver_origen_documental`/`leer_encabezado_origen_focal` — un resolver de planta **documental** (lee qué sucursal AZA imprime la propia guía en su encabezado, no GPS), con cobertura real reportada 7/9 en su commit de cierre (`2c5c764`). No fusionado, no portado en este bloque (fuera de alcance: este bloque es específicamente sobre Onelogis/GPS, y fusionar esa rama implicaría reconciliar mucha lógica de cliente/chofer/destino divergente de C1/D1). Queda documentado como insumo directo para el próximo bloque de origen.

### Diseño

- **`atlas_core/rutas/posicion_vehiculo.py`** (nuevo): `EstadoPosicionVehiculo` (`POSICION_ENCONTRADA`/`SIN_DATOS`/`PROVEEDOR_NO_DISPONIBLE`), `ResultadoPosicionVehiculo` (estado, coordenadas, timestamp_gps, proveedor, motivo), protocolo `ProveedorPosicionVehiculo` (`obtener_posicion(patente, instante) -> ResultadoPosicionVehiculo`) y doble `ProveedorPosicionVehiculoSimulado` (mismo patrón que `ProveedorRutasSimulado` en `atlas_core/rutas/proveedor.py`). Sin adaptador real: no hay endpoint histórico contra el cual construirlo honestamente.
- **`atlas_core/rutas/geocerca.py`** (nuevo): `distancia_km_haversine` + `resolver_planta_por_posicion(posicion, plantas, radio_km=1.5)`. Ordena candidatas por distancia; se abstiene (`FUERA_DE_GEOCERCA`) si ninguna cae dentro del radio, o (`AMBIGUO_ENTRE_PLANTAS`) si dos quedan empatadas a la distancia mínima. Radio `1.5 km` es un valor de partida conservador, **no calibrado contra posiciones reales** (no existen, ver auditoría) — documentado explícitamente como tal en el código. AZA Renca/Colina están separadas por decenas de km reales (confirmado con ORS), por lo que el radio nunca las confunde entre sí.
- **`atlas_core/rutas/enriquecimiento_viaje.py`** (nuevo), tres funciones:
  - `resolver_destino_canonico(texto, catalogo_destinos)`: reutiliza `CatalogoDestinos.buscar()` (ya existente en `atlas_core/catalogo_destinos.py`, sin duplicar lógica de matching) sobre `destinos_maestros.json` (mismo formato `Destino`/`version_formato=1` que `CatalogoDestinos` ya sabe leer — confirmado comparando campos). Exige `COINCIDENCIA` exacta (nunca texto OCR no homologado), `estado_vigencia=ACTIVO`, coordenadas presentes y dentro de `RANGO_LATITUD_RM=(-34.5,-32.5)` / `RANGO_LONGITUD_RM=(-71.5,-70.0)` — un rango geográfico general, no una exclusión por nombre de comuna, que de forma natural excluye los 4 registros "SAN MIGUEL" con coordenada errónea (`lat=-30.81`, zona de Ovalle) detectados en RUTAS-EVAL R1, sin hardcodear ese caso particular.
  - `resolver_planta_origen(patente, instante_salida, proveedor_posicion, plantas, radio_km)`: sin patente, instante o proveedor → `SIN_EVIDENCIA_GPS`. Con proveedor, valida `POSICION_ENCONTRADA`, parsea `timestamp_gps` (ISO) y exige que esté a menos de `VENTANA_MAXIMA_POSICION_GPS=2h` del instante de salida (si no: `POSICION_GPS_DEMASIADO_ANTIGUA`; si el timestamp no es parseable: `POSICION_GPS_SIN_TIMESTAMP_VALIDO`), y solo entonces aplica la geocerca. Nunca infiere por ruta más corta.
  - `calcular_ruta_para_viaje(...)`: orquesta ambas resoluciones y, solo si ambas tienen éxito, llama a `ServicioRutas.confirmar_y_calcular(planta, destino, "driving-hgv", ...)` (ya existente, con caché de `RepositorioRutas` incluido sin cambios). Devuelve siempre un `ResultadoEnriquecimientoRuta` (nunca lanza) con `estado_ruta`/`motivo_ruta` explicativos ante cualquier fallo en cualquier paso — un error de ruta nunca invalida el viaje que lo llama.
- **`atlas_core/rutas/modelos.py`:** 2 miembros nuevos en `EstadoRuta`: `ORIGEN_NO_DETERMINADO`, `DESTINO_NO_VALIDO`.
- **`atlas_core/reporte_viajes.py`:** `COLUMNAS_VIAJES` gana 10 columnas al final (`planta_origen_id`, `planta_origen_nombre`, `destino_id`, `destino_nombre`, `distancia_km`, `duracion_min`, `proveedor_ruta`, `estado_ruta`, `motivo_ruta`, `origen_determinado_por`). `_fila_viaje()` y `generar_reporte_viajes()` ganan un parámetro opcional `calculador_rutas: Callable[[Viaje], dict[str,str]] | None = None`; sin él, las 10 columnas nuevas quedan vacías (`_CAMPOS_RUTA_VACIOS`) — el reporte generado es byte-idéntico en contenido al de antes de este bloque salvo por esas columnas vacías. Desktop no se tocó.
- **`atlas_core/rutas/__init__.py`:** exporta los símbolos nuevos, mismo criterio que los ya existentes.

### Validación

- Tests nuevos: 13 en `tests/test_rutas_enriquecimiento_viaje.py` (geocerca Renca/Colina/fuera-de-rango, GPS demasiado antiguo, planta+destino válidos → ORS real vía doble simulado, segunda ejecución → caché sin nueva llamada, destino inválido parametrizado en 4 casos → no llama ORS, Onelogis sin datos → no falla, sin proveedor de posición → no falla, km/min persistidos + perfil `driving-hgv` capturado) + 2 en `tests/test_reporte_viajes.py` (columnas de ruta vacías sin `calculador_rutas` = no regresión, propagación completa con `calculador_rutas` inyectado + verificación de ausencia de secretos en el CSV resultante). 1 assertion existente ajustada en `tests/test_rutas_modelos.py` (`test_estados_minimos_estan_disponibles`) para incluir los 2 estados nuevos.
- Suite completa: **603 → 618 passed**, 0 failed.
- **Validación real** (catálogo activo real `%LOCALAPPDATA%\Atlas\datos\catalogos_privados`, ORS real vía `api.heigit.org`, clave puenteada de proceso sin exponerla, `driving-hgv`), 3 viajes + 1 repetición:
  | viaje | destino | planta | km | min | estado | motivo |
  |---|---|---|---|---|---|---|
  | 1 | EBEMA SA / Galvarino 8501 | AZA RENCA (GPS inyectado) | — | — | `REQUIERE_REVISION` | `DESTINO_NO_CONFIRMADO` (salvaguarda ya existente de `ServicioRutas`, destino real aún `PENDIENTE`) |
  | 2 | Torres Ocaranza Ltda / Vista Clara 2351 | AZA RENCA (GPS inyectado) | 16.68 | 24.53 | `RUTA_CALCULADA` | — |
  | 3 | mismo que 2 | — (patente sin GPS) | — | — | `ORIGEN_NO_DETERMINADO` | `GPS_SIN_DATOS` |
  | repetición de 2 | igual | igual | 16.68 (idéntico) | 24.53 (idéntico) | `RESULTADO_DESDE_CACHE` | — |
- **Nota de honestidad técnica:** el "GPS" de los viajes 1/2 es una posición **inyectada** (coordenada real de AZA Renca, proveedor `simulado_demo_geocerca`), no una consulta histórica real a Onelogis — porque esa capacidad no existe hoy (ver auditoría). Demuestra que el mecanismo end-to-end (geocerca → destino canónico → ORS real → caché) funciona correctamente con datos y ORS reales; no demuestra determinación automática de origen para una guía histórica real.
- **0 secretos**: `grep` sobre `rutas_eval/resultado_rutas_r1_prueba_real.json`, `rutas_eval/cache_rutas_r1_real.json` y el `viajes.csv` de prueba, sin coincidencias de `authorization`/`bearer`/`api_key`.
- Archivos modificados: `atlas_core/reporte_viajes.py`, `atlas_core/rutas/__init__.py`, `atlas_core/rutas/modelos.py`, `tests/test_reporte_viajes.py`, `tests/test_rutas_modelos.py`. Archivos nuevos: `atlas_core/rutas/enriquecimiento_viaje.py`, `atlas_core/rutas/geocerca.py`, `atlas_core/rutas/posicion_vehiculo.py`, `tests/test_rutas_enriquecimiento_viaje.py`. Sin cambios en `atlas_core/gestor_viajes.py`, `atlas_core/rutas/{modelos con excepción de EstadoRuta,proveedor,servicio,repositorio,openrouteservice}.py`, catálogos, ni Desktop.

### Continuidad

- **Siguiente bloque obligatorio: PLANTA-P1 / ONELOGIS.** Sin una fuente real de posición histórica (o una alternativa documental, ver `_resolver_origen_documental` en `origin/feature-cobertura-origen-fase1`), `planta_origen` seguirá resolviendo `ORIGEN_NO_DETERMINADO` para la gran mayoría de guías reales procesadas después del hecho — comportamiento correcto y seguro (no hay km/min fabricados), pero no automático. No se debe mostrar km/min en Desktop hasta resolver esto.

---

## 2026-08-11 — Cierre Bloque C1: cliente + chofer nuevo + propagación de REVISAR al viaje

**Rama:** `lector-mvp-guia-nueva` · **Baseline previo:** `129b459d936d6d05ae0615cc93fa8842440f4d3a`

### Problema real confirmado

- Guía real `464170`, transporte `0000351177`. PaddleOCR real leía correctamente `SEÑOR(ES): EBEMA SA`, `R.U.T.:83.585.400-0`, `RETIRA: IVAN ROA`, `RUT CHOFER:10190440-7` — pero `cliente` y `rut_cliente` quedaban `"No encontrado"`, `chofer` quedaba sin homologar y el viaje agregado (`agrupar_viajes`) quedaba `CONFIRMADO` sin motivo pese al documento `REVISAR`.
- Diagnóstico ya cerrado en la sesión previa identificó seis causas puntuales (Ñ no normalizada en `buscar_cliente`, colisión de etiqueta geométrica SEÑOR con nombres de destino, ausencia de extracción genérica de RUT cliente, IVAN ROA no catalogado, y `agrupar_viajes` ignorando `indicador_revision`).

### Diseño

- **`atlas_core/extractor.py`:**
  - `_normalizar_acentos(texto)`: reemplaza Á/É/Í/Ó/Ú/Ñ (mayúscula y minúscula) por su forma sin tilde. Centraliza una normalización que antes vivía duplicada e inconsistente: `_texto_simple` sí incluía Ñ→N, pero `texto_busqueda` (usado por `buscar_cliente`/`buscar_obra_destino`/`buscar_rut_chofer` vía regex lineal) y `normalizar_cliente`/`normalizar_obra_destino` no. `_texto_simple` y esas tres funciones ahora llaman al mismo helper.
  - `_es_etiqueta_senor(texto_simple)`: `re.fullmatch(r"SENOR(?:\(ES\)|\(IES\)|ES|IES)?", texto_simple)` — el bloque OCR completo (ya normalizado) debe **ser** la etiqueta, no solo contenerla. Reemplaza el `re.search(r"\bSENOR(?:ES|IES)?\b", ...)` que usaba `_extraer_asociaciones_geometricas`, el cual disparaba (falso positivo) sobre cualquier bloque que contuviera la palabra "SEÑOR" en cualquier posición — caso real: el propio nombre del destino "SUPERMERCADO SEÑOR DE LOS MI" (aparece dos veces, en SOLICITANTE y OBRA DESTINO) generaba una etiqueta de cliente falsa cuyo candidato más cercano ("ORDEN DE COMPRA") quedaba a solo 0.045 de score de la decisión correcta — por debajo del margen de ambigüedad (0.06) del algoritmo, forzando abstención total aunque "EBEMA SA" ya fuera el mejor candidato real.
  - `_extraer_rut_cliente_geometrico(bloques)`: nueva función geométrica, mismo patrón ancla→zona→candidato que `_extraer_chofer_geometrico`/`_extraer_transporte_geometrico`. Ubica una etiqueta `SEÑOR(ES)` (vía `_es_etiqueta_senor`), busca una etiqueta `R.U.T.`/`RUT` inmediatamente debajo (misma columna x, gap vertical acotado), y solo acepta como candidato un valor a su derecha que sea un **RUT chileno válido** (dígito verificador correcto, vía `validar_rut_chileno`). Se abstiene si hay cero o más de un candidato válido distinto — nunca inventa un RUT ni depende de ningún nombre de cliente hardcodeado.
  - `buscar_rut_chofer()`: el regex `r"RUT\s*CHOFER\s*([0-9.\s-]{7,15})"` no toleraba el `:` que PaddleOCR deja pegado al valor cuando la etiqueta y el valor caen en líneas OCR separadas (`"RUT CHOFER\n:10190440-7"`); se agregó `:?` opcional entre la etiqueta y el valor. Genérico, no depende de ningún RUT/chofer particular.
- **`atlas_core/procesamiento_masivo.py`:** `RUT del cliente` se agregó a la condición `campos_ausentes`; dentro del mismo bloque `try` de recuperación geométrica (después de recuperar cliente/obra destino, antes de chofer), se llama `_extraer_rut_cliente_geometrico(bloques_guia)` y, si devuelve valor, se asigna a `datos["RUT del cliente"]` y se marca `recuperacion_geometrica = True` (mismo criterio de todas las recuperaciones geométricas: fuerza `indicador_revision = "REVISAR"`). El `enriquecer_datos_con_catalogos` que ya se re-ejecutaba al final del bloque de catálogos (P2, sin cambios) recoge automáticamente ese RUT recién recuperado y fija el nombre canónico del cliente desde `empresas.json` — sin lógica nueva de canonicalización, reutiliza la ya existente.
- **`atlas_core/gestor_viajes.py`:** nuevo `MotivoRevision.DOCUMENTO_REQUIERE_REVISION` y helper `_documento_marca_revision(fila)` (`str(fila.get("indicador_revision","")).strip().casefold() == "revisar"`). Dentro de `agrupar_viajes`, además de los `campos_conflicto` ya existentes (comparación entre documentos), se agrega este motivo si **cualquier** documento del grupo trae `indicador_revision=REVISAR` — independiente de si hay o no conflictos entre documentos. Antes, `indicador_revision` no se leía en ningún punto de esta función; un transporte de un solo documento nunca podía generar contradicción consigo mismo y quedaba `CONFIRMADO` sin importar su propio estado.
- **Catálogo (fuera del repo):** fuente activa real identificada vía `%APPDATA%\atlas-viajes-desktop\config_usuario.json` (electron-store del Desktop instalado) → `%LOCALAPPDATA%\Atlas\datos\catalogos_privados\choferes.json`. Se agregó el registro `"101904407": {"nombre": "IVAN ROA", "activo": true}` (RUT normalizado como clave, mismo esquema exacto de los 28 registros existentes, sin `aliases` — chofer nuevo real, no alias, confirmado por Javier). Validado: RUT con dígito verificador correcto, clave y nombre únicos, JSON parseable tras escritura.

### Validación

- Tests nuevos: 4 en `tests/test_extraer_datos.py` (SEÑOR(ES) con Ñ real resuelve cliente lineal; "SUPERMERCADO SEÑOR DE LOS MI" no se interpreta como etiqueta; RUT cliente genérico recupera 83.585.400-0; RUT cliente ambiguo se abstiene) + 1 corolario (`buscar_rut_chofer` tolera `:` pegado al valor); 3 en `tests/test_catalogos.py` (IVAN ROA resuelve exacto por RUT; RUT 10190440-7 asocia IVAN ROA vía enriquecimiento; EBEMA SA ya catalogada resuelve a su nombre canónico); 1 en `tests/test_catalogos.py` (fuzzy no reescribe IVAN ROA hacia otro chofer similar); 4 en `tests/test_gestor_viajes.py` (documento REVISAR fuerza REQUIERE_REVISION; documento OK simple puede quedar CONFIRMADO; conflicto multiguía persiste con documentos OK; conflicto y documento REVISAR coexisten sin eliminarse mutuamente).
- Fixtures existentes actualizadas (no tests nuevos): 3 en `tests/test_procesamiento_masivo.py` (`test_procesar_archivo_no_reemplaza_valores_lineales_correctos`, `test_procesar_archivo_preserva_chofer_lineal_limpio`, y el helper compartido `_datos_lineales_completos` usado por 2 tests más) — no incluían `RUT del cliente`, lo que ahora disparaba lectura de bloques que esos tests explícitamente verifican que no ocurra; se agregó el campo sin tocar la intención original de cada test.
- 1 assertion existente ajustada en `tests/test_gestor_viajes.py` (`test_conflictos_multiples_se_declaran_juntos_sin_perder_evidencia`): el set de "todos los motivos posibles" ahora también excluye `DOCUMENTO_REQUIERE_REVISION` además de `FECHA_NO_COMPATIBLE_DESKTOP`, porque ese escenario no fija `indicador_revision` en ninguna fila.
- Suite completa: **581 → 594 passed**, 0 failed.
- **Validación real, guía `464170`, PaddleOCR GPU real, catálogo activo real (`%LOCALAPPDATA%\Atlas\datos\catalogos_privados`, ya con IVAN ROA agregado):**
  - `numero_guia=464170`, `numero_transporte=0000351177` (sin cambio).
  - `cliente`: `No encontrado` → **`EBEMA SA`**.
  - `RUT del cliente`: `No encontrado` → **`83.585.400-0`** (formato canónico con puntos, vía `empresas.json`).
  - `chofer`: `IVAN ROA` (ya se leía, sin homologar) → **`IVAN ROA`** (homologado exacto contra catálogo).
  - `rut_chofer`: `No encontrado` → **`10190440-7`** (sin puntos — mismo formato histórico que `buscar_rut_chofer()` ya usaba para otros choferes, no una regresión).
  - `indicador_revision`: `REVISAR` → `REVISAR` (sin cambio; causa legítima vigente: el documento siguió necesitando recuperación geométrica de cliente/RUT cliente/chofer).
  - Viaje agrupado (`agrupar_viajes`): `CONFIRMADO` sin motivo → **`REQUIERE_REVISION`, motivo `DOCUMENTO_REQUIERE_REVISION`**.
  - `obra_destino` sin cambio (`"VENTA AL POR MAYOR D"`, incorrecto) — explícitamente fuera de alcance de C1.
- Archivos modificados: `atlas_core/extractor.py`, `atlas_core/procesamiento_masivo.py`, `atlas_core/gestor_viajes.py`, `tests/test_extraer_datos.py`, `tests/test_catalogos.py`, `tests/test_gestor_viajes.py`, `tests/test_procesamiento_masivo.py`. Catálogo real modificado fuera del repo: `%LOCALAPPDATA%\Atlas\datos\catalogos_privados\choferes.json` (respaldo previo en `Desktop\Atlas\backups_catalogos\20260811_063918_pre_alta_ivan_roa\`). Sin cambios en OCR (`atlas_core/ocr.py`, `atlas_core/ocr_provider.py`, `atlas_core/paddle_runtime.py`) ni en `atlas_core/catalogos.py`/`atlas_core/reporte_viajes.py`/`generar_reporte_viajes.py`.

### Continuidad

- **Siguiente bloque oficial: DESTINO D1** — corregir `obra_destino` (hoy resuelve al valor de GIRO en vez del destino real, misma familia de colisión geométrica que motivó C1 pero en otro campo), prerrequisito directo para rutas/KM/tiempos. No iniciado.

---

## 2026-08-10 — Cierre Patentes P2: homologación conservadora contra catálogo de vehículos

**Rama:** `lector-mvp-guia-nueva` · **Baseline previo:** `0021bde59a9bb2f7b18462377ea6634d5cade781`

### Objetivo

P1 ya recuperaba `patente_tracto`/`patente_carro` con salida Paddle, pero devolvía el valor OCR crudo tal cual (p. ej. `SD6486`), sin resolver su identidad canónica. P2 resuelve únicamente esa identidad, contra la fuente canónica de vehículos privados ya integrada vía `carpeta_catalogos` (`vehiculos.json`), sin tocar Paddle, sin cambiar regex de OCR, sin tocar Desktop ni la generación de reportes.

### Diseño

- Nueva función `resolver_patente_canonica(catalogo, patente_ocr, *, tipo_esperado=None)` en `atlas_core/catalogos.py`, junto a un dataclass `ResultadoResolucionPatente(estado, valor_original, valor_resultado, candidatos_ambiguos)` trazable (mismo patrón que `ResultadoCoincidenciaChofer`/`resolver_nombre_chofer_difuso`).
- Jerarquía de resolución, en orden:
  - **A. Coincidencia exacta normalizada** — el valor OCR ya está en el catálogo (mismo comportamiento que la normalización de formato ya existente en `enriquecer_datos_con_catalogos`).
  - **B. Alias explícito declarado en el catálogo** — si el registro del vehículo trae un campo `"alias": [...]`, se acepta un valor OCR que coincida con un alias, sin inferir nada no declarado.
  - **C. Corrección OCR conservadora** — se acepta solo si: (1) el valor OCR tiene forma plausible de patente chilena (`_forma_patente_plausible`, mismo patrón `[A-Z0-9]{6}` con al menos una letra y un dígito que ya usa el extractor); (2) hay un único candidato de catálogo con la misma longitud; (3) la diferencia es de **una sola posición**, explicada por una confusión OCR común y documentada — `_CONFUSIONES_OCR_PATENTE_COMUNES = {B/D, 0/O, 1/I, 5/S, 8/B}` (tabla deliberadamente pequeña y con evidencia, no una heurística amplia); (4) no hay un segundo candidato igualmente plausible. Dos o más diferencias, o dos o más candidatos, nunca se corrigen.
  - `tipo_esperado` (`"TRACTO"`/`"CARRO"`) filtra los candidatos de la corrección conservadora por el campo `tipo` del registro, cuando existe, para que una patente de tracto nunca se homologue accidentalmente contra un carro y viceversa.
  - Nunca crea una patente que no exista ya en el catálogo.
- `atlas_core/procesamiento_masivo.py` (`procesar_archivo`): dentro del bloque `if carpeta_catalogos is not None:` (después de `enriquecer_datos_con_catalogos`, para cubrir el valor final sea cual sea su origen — lectura lineal o recuperación geométrica P1), se carga `vehiculos.json` y se llama `resolver_patente_canonica` para `patente del tracto` (tipo `TRACTO`) y `patente del carro` (tipo `CARRO`):
  - `COINCIDENCIA_EXACTA` → aplica el valor, sin marcar revisión adicional (mismo comportamiento silencioso que ya existía).
  - `ALIAS` / `CORRECCION_OCR_SEGURA` → aplica el valor homologado y marca `homologacion_patente = True` (fuerza `indicador_revision = "REVISAR"`, mismo criterio que toda recuperación no literal en el proyecto).
  - `AMBIGUO` → conserva el valor OCR sin cambios y también marca `homologacion_patente = True` (mantener valor OCR + REVISAR, tal como pide el contrato).
  - `SIN_CANDIDATO` / `CATALOGO_VACIO` / `VACIO` → sin cambios, sin marca adicional.
  - Todo el bloque envuelto en `try/except` (mismo patrón que el resto de fallbacks): un problema de catálogo nunca invalida el procesamiento principal.

### Validación

- Caso real obligatorio, guía `464511`, catálogo real (`vehiculos.json` con `SB6486`/`JF4288`): **`patente_tracto` `SD6486` → `SB6486`** (corrección OCR conservadora, único candidato, diferencia B/D en una posición); **`patente_rampla` `JF4288` → `JF4288`** (coincidencia exacta, sin cambios). Resto de campos (`numero_guia`, `numero_transporte`, `fecha`, `chofer`, `cliente`) sin cambios respecto al resultado post-P1.
- La corrección `SD6486 → SB6486` no está hardcodeada por archivo/nombre de guía: surge exclusivamente de la jerarquía general de `resolver_patente_canonica` aplicada contra el contenido real del catálogo.
- Tests específicos: 11 unitarios de `resolver_patente_canonica` en `tests/test_catalogos.py` (exacto, alias, `SD6486→SB6486` con catálogo real simulado, rampla exacta sin modificar, candidato ambiguo → abstención, dos diferencias → no corregir, patente desconocida → conserva, `"NO_APLICA"` preservado sin inventar, `"No encontrado"` no se toca, sin catálogo/catálogo inexistente → no inventa, filtro por `tipo_esperado` entre tracto y carro) + 4 de integración end-to-end en `tests/test_procesamiento_masivo.py` (homologación real con catálogo escrito en disco, ambigüedad mantiene OCR + `REVISAR`, sin `carpeta_catalogos` no homologa, P1 geométrico + P2 homologación encadenados sobre la misma guía sin interferencia — no regresión de P1).
- Suite completa: **566 → 581 passed**.
- Archivos modificados: `atlas_core/catalogos.py`, `atlas_core/procesamiento_masivo.py`, `tests/test_catalogos.py`, `tests/test_procesamiento_masivo.py`. Sin cambios en OCR (`atlas_core/ocr.py`, `atlas_core/ocr_provider.py`, `atlas_core/paddle_runtime.py`, `atlas_core/extractor.py`), Desktop (`resumen_procesamiento_desktop.py`, `atlas_core/gestor_viajes.py`) ni reportes (`generar_reporte_viajes.py`, `atlas_core/reporte_viajes.py`) — ambos reciben el valor homologado únicamente porque consumen el dict que devuelve `procesar_archivo`.

### Continuidad

- Frente de patentes (P1 + P2) queda cerrado. No hay un microbloque siguiente de patentes definido.

---

## 2026-08-10 — Cierre Patentes P1: adaptar extractor a salida Paddle sin tocar OCR

**Rama:** `lector-mvp-guia-nueva` · **Baseline previo:** `0bcb43ca56e5ab1cdc6f596bb80af225ce234739`

### Problema real confirmado

- Guía real `464511`: tracto real `SB6486`, rampla real `JF4288`. Paddle entrega `PATENTE\n:SD6486 CARRO:JF4288` (B leída como D — error de reconocimiento, no de extracción).
- `buscar_chofer_y_patentes()` buscaba `texto_busqueda.find("RETIRA PATENTE FECHA LLEGADA")` como frase contigua; Paddle reparte esas etiquetas en bloques/líneas separados, por lo que el `find` nunca coincidía y la función retornaba `(None, None, None)` de inmediato. `patente_tracto`/`patente_carro` quedaban en `"No encontrado"`.

### Diseño

- `buscar_chofer_y_patentes()` (lectura lineal, formato histórico EasyOCR contiguo) **no se modificó** — sigue siendo la vía primaria en `extraer_datos`.
- Se movieron `patente_valida`/`normalizar_patente` (antes anidadas dentro de `extraer_datos`) a funciones de módulo `_patente_valida`/`_normalizar_patente`, sin cambiar su lógica, para reutilizarlas desde la nueva función geométrica.
- Nueva función `_extraer_patentes_geometrico(bloques)` en `atlas_core/extractor.py`, siguiendo el mismo patrón ancla→zona→candidato ya usado por `_extraer_chofer_geometrico`/`_extraer_transporte_geometrico`/`_extraer_fecha_geometrico`:
  - Ancla en bloques `RETIRA` (inicio) y `FECHA LLEGADA`/`LLEGADA` (fin) por coordenada Y; sin ancla `RETIRA`, se abstiene.
  - Define la zona geométrica entre ambas anclas (con margen de 15px; sin ancla de cierre, usa un margen conservador de 260px) y concatena solo los bloques dentro de esa zona en orden de lectura — tolerante a que Paddle fragmente las etiquetas en bloques distintos, sin requerir una frase contigua.
  - Extrae `CARRO`/`RAMPLA` con `\b(?:CARRO|RAMPLA)\s*:?\s*([A-Z0-9]{6})\b`; el resto de la zona (sin ese fragmento ni las etiquetas RETIRA/PATENTE/FECHA/LLEGADA) se escanea en busca de un token de 6 caracteres con forma de patente para el tracto.
  - Abstención conservadora: candidato fuera de la zona (no se incluye), o dos candidatos válidos para el mismo campo (ambigüedad) → no se resuelve ese campo.
  - **No corrige el valor OCR** (no convierte `SD6486` en `SB6486`): esa homologación queda fuera de alcance de P1 deliberadamente.
- `atlas_core/procesamiento_masivo.py` (`procesar_archivo`): se agregó `patente del tracto`/`patente del carro` a la condición `campos_ausentes` y se conectó `_extraer_patentes_geometrico` como *fallback* dentro del mismo bloque `try` que ya usan cliente/destino/chofer/transporte, activo solo si el campo sigue `"No encontrado"` tras la lectura lineal. Cualquier recuperación marca `recuperacion_patentes = True`, que fuerza `indicador_revision = "REVISAR"` (mismo criterio que las demás recuperaciones geométricas). No se tocó Desktop ni la generación de reportes — ambos consumen el dict que devuelve `procesar_archivo`, así que reciben el valor recuperado automáticamente.

### Validación

- Tests específicos: 8 escenarios geométricos unitarios (secuencia real Paddle con valor+CARRO en un solo bloque, etiquetas y valores en bloques separados, candidato fuera de zona → rechazo, dos candidatos ambiguos → abstención, solo tracto, solo carro, sin ancla RETIRA → abstención, no interferencia con extracción de chofer) + 1 regresión del formato histórico EasyOCR contiguo (`probar_guia5`, guía real SB6486/JF4288) + 1 integración end-to-end en `procesar_archivo` con bloques reales tipo Paddle.
- Suite completa: **556 → 566 passed**.
- Validación con la guía real `464511` (PaddleOCR real, GPU, sin mocks): **antes** `patente_tracto = "No encontrado"`, `patente_rampla = "No encontrado"`; **después** `patente_tracto = "SD6486"`, `patente_rampla = "JF4288"`. Resto de campos (`numero_guia`, `numero_transporte`, `fecha`, `chofer`, `cliente`) sin cambios. Confirmado mediante `git stash`/`git stash pop` comparando el mismo procesamiento real antes y después del cambio — **0 regresiones**.
- Archivos modificados: `atlas_core/extractor.py`, `atlas_core/procesamiento_masivo.py`, `tests/test_extraer_datos.py`, `tests/test_procesamiento_masivo.py`. Sin cambios en OCR (`atlas_core/ocr.py`, `atlas_core/ocr_provider.py`, `atlas_core/paddle_runtime.py`), Desktop (`resumen_procesamiento_desktop.py`, `atlas_core/gestor_viajes.py`) ni reportes (`generar_reporte_viajes.py`, `atlas_core/reporte_viajes.py`).

### Continuidad

- **Siguiente microbloque pendiente:** homologación de patente OCR contra catálogo de vehículos (ejemplo `SD6486 → SB6486`), sin alterar el OCR. No iniciado — es un problema de resolución/catálogo distinto al de extracción resuelto en P1.

---

## 2026-08-10 — Cierre integración Atlas Viajes Desktop ↔ Motor sobre Paddle M2

**Rama:** `lector-mvp-guia-nueva` · **Baseline previo:** `e61c04af4081b3d52761ad7928291bd88b6a83d2`

### Recuperación histórica selectiva

- `resumen_procesamiento_desktop.py` fue recuperado sin reconstrucción desde la historia Git; su blob `0b603a48be6af95370707a409bad5e3e0f711014` coincide con el original validado.
- El contrato coordinado se reconstruyó tomando como referencia el commit motor `9d65933171c79d52a6e780213bc0a9593154b3a7` y el commit Desktop `40d9c71f23872b60f4bbee36d9654af27a0a0019`, sin cherry-pick ni reemplazo de archivos M2.
- Se recuperaron selectivamente `atlas_core/fuente_catalogos.py`, `atlas_core/gestor_viajes.py`, `atlas_core/reporte_viajes.py` y `generar_reporte_viajes.py`, junto con sus pruebas relevantes.

### Contrato e integración actual

- `analizar_guias_masivo.py` acepta `--catalogos`, conserva `--salida`, `--reprocesar`, `--fecha-desde` y `--fecha-hasta`, y resuelve la fuente en orden: ruta explícita, `ATLAS_CATALOGOS_DIR`, o carpeta productiva local únicamente si contiene los siete archivos canónicos. Una ruta ausente/incompleta falla de forma explícita; los `*.example.json` no califican.
- `procesar_carpeta(..., carpeta_catalogos=...)` propaga la fuente a cada `procesar_archivo` sin alterar la creación/reutilización del `ProveedorOCR`. La recuperación geométrica y el enriquecimiento canónico comparten la misma fuente privada.
- La integración selectiva preserva M1/M2: PaddleOCR continúa como motor principal; el proveedor se crea una sola vez por lote; GPU/CPU/fallback permanecen sin cambios.

### Validación

- Suite completa: **501 → 556 passed**.
- Prueba CLI aislada de una sola guía: PaddleOCR `device=gpu`, catálogos válidos, 1 procesada, 0 errores y salida CSV correcta.
- Sanity check del generador restaurado: reporte completo de una guía con `viajes.csv`, `documentos_sin_transporte.csv`, `clientes_no_reconocidos.csv`, `resumen_viajes.md` y `manifest_reporte_viajes.json`, sin modificar el reporte operativo de 574 viajes.
- Prueba manual end-to-end confirmada por el usuario en Atlas Viajes 1.4.3: guía `464511` → transporte `0000352449`, fecha `10-08-2026`, cliente `ARMACERO MATCO SA`, chofer `RODRIGO NAHUELÑIR`; viaje visible en UI, estado OK.

### Continuidad

El próximo frente Desktop es **RECUPERACIÓN UX HISTÓRICA**, no cambios del motor. Antes de reconstruir cualquier elemento, consultar `G:\Mi unidad\BACKUP_PRE_FORMATEO_20260808`.

---

## 2026-08-10 — Bloque M2: runtime Paddle portable + activación en flujo batch

**Rama:** `lector-mvp-guia-nueva` · **HEAD previo:** `3304a4667d605da3dd9768ca246a3272e099c463 feat: integrar paddleocr como proveedor principal`

### Problemas que atacaba este bloque

1. `PaddleOCRProvider` apuntaba a `C:\Users\Jjjc0508\Desktop\Atlas\ocr_eval_gpu_env` — ruta fija de este PC, no portable.
2. `procesar_carpeta`/la CLI no construían ni pasaban ningún `ProveedorOCR` — PaddleOCR estaba integrado como infraestructura pero no activo en el flujo real de lote.

### Archivo nuevo

**`atlas_core/paddle_runtime.py`**: resuelve la ubicación del runtime (`ruta_runtime_paddle()` — prioridad: variable de entorno `ATLAS_PADDLE_RUNTIME` > `%LOCALAPPDATA%\Atlas\runtime\paddleocr`, sin nombre de usuario ni Desktop hardcodeados en el código, solo en la documentación explicando que no se depende de ello). `runtime_valido()` comprueba una marca de versión (`.version`) sin ejecutar nada. `asegurar_runtime_paddle()` crea el venv con `python -m venv`, instala `paddlepaddle-gpu==3.3.1` (índice `cu118`) si hay GPU NVIDIA o `paddlepaddle==3.3.1` si no, más `paddleocr==3.7.0`, y escribe la marca de versión — solo si el runtime no es ya válido. Nunca toca drivers ni CUDA del sistema.

### Archivos modificados

**`atlas_core/ocr_provider.py`**: se eliminaron las constantes `RUTA_VENV_PADDLE`/`RUTA_PYTHON_PADDLE` (apuntaban a `ocr_eval_gpu_env`). `PaddleOCRProvider` gana un parámetro `ruta_python` opcional (override para tests/uso avanzado); sin él, `_asegurar_proceso()` resuelve la ruta vía `asegurar_runtime_paddle()` en el momento de arrancar el proceso, no al construir el objeto. `crear_proveedor_ocr()` ahora también `print()`-ea (además de loguear) qué proveedor y dispositivo quedó activo, o por qué cayó a EasyOCR — visible en la CLI aunque no haya logging configurado.

**`atlas_core/procesamiento_masivo.py`**: `procesar_carpeta` gana un parámetro `proveedor`. Nueva lógica de `ejecutar()`: si se entrega `lector_ocr` explícito, camino EasyOCR directo sin cambios (compatibilidad); si no, se construye **un solo** proveedor vía `crear_proveedor_ocr()` (o se reutiliza el `proveedor` explícito recibido) para todo el lote, pasado a cada `procesar_archivo(..., proveedor=...)`. El import de `crear_lector_ocr` se conserva sin usar en el cuerpo del módulo, solo para no romper tests existentes que lo monkeypatchean.

**Sin cambios:** `procesar_archivo` (ya aceptaba `proveedor` desde M1), focal de fecha/transporte (ya usan el proveedor activo desde M1 — este bloque solo confirma que efectivamente comparten la misma instancia, no crean otra), regex de `extraer_fecha`, F1, guarda documental.

### Tests

- `tests/test_paddle_runtime.py` (11 nuevos): resolución de ruta con `LOCALAPPDATA` sin usuario hardcodeado, override por variable de entorno, fallback a `Path.home()`; `runtime_valido()` en sus tres casos; `asegurar_runtime_paddle()` no reinstala si ya es válido, instala build GPU si hay NVIDIA, instala build CPU si no, devuelve `None` si la instalación falla — todo con `subprocess.run` mockeado, ninguna instalación real; verificación de que el módulo no menciona `ocr_eval_gpu_env` ni la ruta del usuario.
- `tests/test_ocr_provider.py` (+7 respecto a M1): selección de dispositivo GPU/CPU de `PaddleOCRProvider` (y que no consulta GPU si el dispositivo viene explícito); mensajes visibles en consola tanto en éxito (`print` con el device) como en fallback a EasyOCR; el test de "venv no existe" de M1 se separó en dos (`asegurar_runtime_paddle` devuelve `None` vs. el `python.exe` resuelto no existe en disco) para reflejar el nuevo mecanismo de resolución; verificación de ausencia de `ocr_eval_gpu_env`/usuario hardcodeado.
- `tests/test_procesamiento_masivo.py`: `test_crea_lector_una_vez_y_lo_reutiliza` → reemplazado por `test_procesar_carpeta_crea_proveedor_una_vez_y_lo_reutiliza` (comportamiento intencionalmente distinto: el default ahora es el proveedor, no `crear_lector_ocr`); `test_lector_inyectado_no_crea_otro` → renombrado `test_lector_inyectado_no_crea_proveedor` (mismo comportamiento, nueva aserción); `test_proveedor_inyectado_se_reutiliza_sin_crear_otro` nuevo.
- **Importante:** un intento inicial de correr `tests/test_ocr_provider.py` antes de terminar de mockear todo disparó una instalación real accidental (creó un venv parcial en `%LOCALAPPDATA%\Atlas\runtime\paddleocr`) — se detectó, se abortó el proceso y se borró el venv parcial antes de continuar. Se agregó `_prohibir_bootstrap_real()` en los tests: cualquier llamada real a `asegurar_runtime_paddle()` no mockeada falla ruidosamente en vez de instalar algo de verdad.

### Validación

- Tests específicos: 19 nuevos, todos verdes (con timeout de seguridad en cada corrida, por precaución tras el incidente anterior).
- Suite completa: `482 → 501 passed`.
- **Bootstrap real (no mockeado):** `asegurar_runtime_paddle()` ejecutado de verdad — creó el venv, instaló `paddlepaddle-gpu==3.3.1` (GPU detectada) y `paddleocr==3.7.0` en `C:\Users\Jjjc0508\AppData\Local\Atlas\runtime\paddleocr` en 209.4 s. `runtime_valido()` confirmó `True` después.
- **Batch corto real (CLI real, `analizar_guias_masivo.py`, 4 imágenes reales):** `[Atlas OCR] Proveedor activo: PaddleOCR (device=gpu)` impreso **una sola vez** (no por imagen) — confirma un solo proveedor por ejecución, GPU seleccionada automáticamente, sin fallback silencioso. 4/4 procesados, 0 errores. Resultados verificados contra lo ya conocido: número de guía y fecha correctos en las 4 imágenes.
- Primera corrida: 190.5 s (47.6 s/imagen). Segunda corrida (mismo lote, runtime ya "tibio"): 42.0 s (10.5 s/imagen) — confirma que la primera fue sobrecarga de arranque (antivirus/caché), no un problema de la lógica.
- No se re-ejecutaron las 30 imágenes — la extracción ya se validó exhaustivamente en M1 sobre el mismo `procesar_archivo`+proveedor; este bloque solo cambiaba la resolución de ruta y la activación en `procesar_carpeta`, ambas ya confirmadas con el batch corto real.
- `grep` sobre los logs y el CSV de esta validación: cero menciones a `ocr_eval_gpu_env`.

### Estado de cierre

`git status` antes de commit: 4 rutas modificadas (`atlas_core/ocr_provider.py`, `atlas_core/procesamiento_masivo.py`, `tests/test_ocr_provider.py`, `tests/test_procesamiento_masivo.py`) + 2 nuevas (`atlas_core/paddle_runtime.py`, `tests/test_paddle_runtime.py`) + bitácoras/handoff. **Sin commit, sin push** — pendiente de revisión.

**Nota fuera de alcance:** se encontró un archivo no rastreado `resumen_procesamiento_desktop.py` en la raíz del repo que este bloque no creó ni modificó — no se tocó, se deja fuera del commit, y se reporta como hallazgo.

---

## 2026-08-10 — Bloque M1: proveedor OCR + compatibilidad de extractores (CERRADO)

**Rama:** `lector-mvp-guia-nueva` · **HEAD previo:** `ddf4309c7bebc80704b733c0517da700666e93b6 feat: agregar recuperacion focal conservadora de fecha`

### Decisiones de cierre

- **PaddleOCR aprobado como motor principal**; `EasyOCRProvider` queda como fallback temporal (automático si Paddle no está disponible, y siempre disponible explícitamente vía `crear_proveedor_ocr("easyocr")`).
- No se ejecutó otro benchmark completo de 30 imágenes en CPU en este cierre — la portabilidad CPU se confirmará después con una prueba corta en el PC de oficina. No bloquea el cierre.
- `IMG-20250930-WA0047.jpg`: el desacuerdo entre `410627` (ground truth) y `410267` (lo que la imagen realmente muestra, según la propia observación del validador original en el Excel) se registra como discrepancia editorial de ground truth pendiente, no como fallo de `decidir_bloques_ocr` ni de Atlas.
- **Riesgo principal pendiente, explícito:** `PaddleOCRProvider` apunta hoy a `RUTA_VENV_PADDLE = C:\Users\Jjjc0508\Desktop\Atlas\ocr_eval_gpu_env` (constante en `atlas_core/ocr_provider.py`) — un venv creado para el bloque de evaluación, no una ruta de despliegue definitiva. El siguiente bloque oficial (**M2**) debe reemplazar esto por un runtime reproducible/portable, no atado a una ruta específica de este equipo.

### Contexto

Bloque de implementación (decisión de migrar a PaddleOCR ya tomada en evaluaciones previas, no se re-evalúa aquí). Objetivo: integrar PaddleOCR detrás de una abstracción, sin romper EasyOCR, resolviendo las dos incompatibilidades ya diagnosticadas (`numero_guia` frágil a adyacencia textual; recuperación focal acoplada a `easyocr.Reader`).

**Hallazgo relevante antes de implementar:** `atlas_core/experimento_numero_guia_contextual.py::decidir_bloques_ocr` (ya usado por `procesar_archivo`) es un mecanismo ancla→marcador→candidato **agnóstico al motor OCR** que ya tolera bloques intermedios entre "GUIA"/"DESPACHO"/"ELECTRONICA". Una prueba directa con los bloques de PaddleOCR (sin cambiar nada) ya recuperaba 29/30 — la "regresión" medida en el bloque de evaluación anterior fue un hueco del arnés de esa evaluación (no invocaba `decidir_bloques_ocr`), no una limitación real de Atlas. Esto simplificó el alcance de M1: no hizo falta escribir un extractor geométrico nuevo para `numero_guia`, solo conectar `decidir_bloques_ocr` al proveedor activo.

### Archivos nuevos

- **`atlas_core/ocr_provider.py`**: contrato `ProveedorOCR` (Protocol): `leer_texto`, `leer_bloques`, `leer_focal`. `EasyOCRProvider` envuelve las funciones existentes de `atlas_core.ocr` sin cambiarlas. `PaddleOCRProvider` ejecuta PaddleOCR en un **proceso aislado** (venv externo `C:\Users\Jjjc0508\Desktop\Atlas\ocr_eval_gpu_env`, el mismo ya validado en el bloque OCR-EVAL GPU — el wheel `paddlepaddle-gpu` corre igual en CPU pasando `device="cpu"`, así que un solo venv basta para ambos casos), comunicándose por un protocolo JSON línea a línea sobre stdin/stdout con un proceso worker persistente (no se recarga el modelo por imagen). `_gpu_nvidia_disponible()` detecta GPU vía `nvidia-smi` sin hardcodear ningún modelo. `crear_proveedor_ocr(preferido="paddleocr")` selecciona el proveedor y cae a `EasyOCRProvider` si Paddle no está disponible (venv ausente, worker no arranca, etc.) — `ProveedorOCRNoDisponible` es la excepción de señalización para ese fallback.
- **`atlas_core/paddleocr_worker.py`**: script standalone (solo stdlib + paddleocr + Pillow/numpy, **cero imports de atlas_core**) que corre bajo el intérprete del venv aislado. Replica el recorte/margen/4-variantes de `_leer_region_focal` (duplicado necesario por el aislamiento de proceso — si el recorte/margen cambia en `atlas_core/ocr.py`, este archivo debe actualizarse a mano, queda documentado en su docstring). Aplica `enable_mkldnn=False` cuando `device="cpu"` (workaround de Fase 0 de OCR-EVAL).

### Archivos modificados

**`atlas_core/procesamiento_masivo.py`:**
- `procesar_archivo` gana un parámetro opcional `proveedor: ProveedorOCR | None = None`. Sin él, el comportamiento es **exactamente el mismo de antes** (EasyOCR directo vía `lector_ocr`) — confirmado por test explícito y por la suite completa sin cambios. Con él, tres closures internas (`_leer_texto`, `_leer_bloques`, `_leer_focal`) enrutan cada llamada de OCR (texto completo, bloques, focal de fecha/transporte) al proveedor en vez de a `leer_texto_imagen`/`leer_bloques_imagen`/`_leer_transporte_focal`/`_leer_fecha_focal` directos.
- Import de `ALLOWLIST_FECHA`/`ALLOWLIST_TRANSPORTE` desde `atlas_core.ocr` para pasarlos explícitamente al proveedor en las llamadas focales (antes vivían implícitos dentro de `_leer_transporte_focal`/`_leer_fecha_focal`).
- **Guarda documental nueva:** `CAMPOS_GUARDA_DOCUMENTAL` (numero_guia, numero_transporte, cliente, obra_destino, chofer, patente_tracto, patente_carro) + `UMBRAL_CAMPOS_FALTANTES_DOCUMENTO_DEGRADADO = 5` + `_documento_degradado(datos, descripcion)`: si ≥5 de esos 8 indicadores (7 campos + descripción) vuelven vacíos a la vez, se suma a `requiere_revision`. Nunca cambia un valor ni descarta una fecha ya encontrada — solo empuja el indicador hacia `REVISAR`.

**Sin cambios:** regex de `extraer_fecha`, F1 (guarda de plausibilidad), F2 (consenso de confianza), extractores lineales/geométricos existentes, contrato `BloqueOCR`, `requirements.txt`, entorno Python principal.

### Tests

- `tests/test_ocr_provider.py` (16 nuevos): contrato `EasyOCRProvider` (delegación a `leer_texto_imagen`/`leer_bloques_imagen`/`_leer_region_focal`, lector creado una sola vez); contrato `PaddleOCRProvider` con proceso mockeado (texto/bloques/focal vía protocolo JSON, error de una imagen no mata el proceso, `ProveedorOCRNoDisponible` si el worker no arranca o el venv no existe); selección de proveedor (`easyocr` explícito nunca toca Paddle; Paddle disponible se usa; Paddle no disponible cae a EasyOCR); detección de GPU sin `nvidia-smi`.
- `tests/test_procesamiento_masivo.py` (8 nuevos): `numero_guia` con etiqueta fragmentada en bloques (caso real de Paddle) recuperado vía proveedor; `numero_guia` sin marcador cercano se abstiene; fecha focal vía proveedor; transporte focal vía proveedor; `_documento_degradado` activa con muchos campos faltantes / no activa con pocos (tests puros); `procesar_archivo` con documento degradado queda `REVISAR`; `procesar_archivo` sin `proveedor` conserva exactamente el comportamiento anterior (ancla de no-regresión).

### Validación

- Tests específicos: 24 nuevos, todos verdes.
- Suite completa: `458 → 482 passed`.
- Validación real: `procesar_archivo(ruta, proveedor=proveedor)` con un `PaddleOCRProvider` **real** (proceso vivo, GPU real, sin mocks) sobre las 30 imágenes:
  - `numero_guia`: **2/30 → 29/30** (el único caso restante, `IMG-20250930-WA0047.jpg`, es la disputa de ground truth ya documentada en el Excel original: "la validación manual anterior indicó guía 410627; la imagen muestra 410267").
  - `fecha`: 27/30 (sin cambio respecto a la evaluación previa).
  - `numero_transporte` 28/30, `cliente` 21/25, `obra_destino` 12/27, `chofer` 15/23, `descripción_material` 24/25, `tipo_carga` 24/29 — todos iguales a la evaluación previa, sin regresiones. (Nota: el primer cálculo de `descripcion_material` en el script de validación dio 0/25 por un comparador equivocado en el script — no en Atlas —, corregido antes de reportar; con el comparador correcto da 24/25, igual que antes.)
  - `IMG-20260512-WA0027.jpg`: `indicador_revision = REVISAR` confirmado.
  - Proveedor real creado: `PaddleOCRProvider` (no cayó a fallback). Tiempo: 90.9 s para 30 imágenes (3.03 s/imagen), consistente con uso real de GPU.
  - Camino CPU: implementado y cubierto por tests (incluye `enable_mkldnn=False`), pero no se re-ejecutó un benchmark completo de 30 imágenes en CPU dentro de este bloque — se apoya en la validación de Fase 0/OCR-EVAL CPU ya hecha sobre el mismo camino de código, que no cambió.

### Estado de cierre

`git status` previo al commit: working tree con 2 rutas modificadas (`atlas_core/procesamiento_masivo.py`, `tests/test_procesamiento_masivo.py`) y 3 rutas nuevas (`atlas_core/ocr_provider.py`, `atlas_core/paddleocr_worker.py`, `tests/test_ocr_provider.py`), más las 3 bitácoras/handoff. **Sin commit, sin push** — pendiente de revisión.

---

## 2026-08-10 — Bloque Fechas F2: recuperación OCR focal de FECHA DE EMISIÓN (cerrado, con gate de confianza)

**Rama:** `lector-mvp-guia-nueva` · **HEAD previo:** `61958f2718452916b4a8d6fc4807903067355c81 feat: agregar plausibilidad temporal a fechas`

### Contexto

Diagnóstico previo (mismo bloque de trabajo) sobre los 16 fallos de fecha de la muestra real concluyó: 0/16 atribuibles a `extraer_fecha`, todos originados en OCR/calidad de imagen; ~11/16 con probabilidad razonable de beneficiarse de una relectura focal (recorte + realce), reutilizando el mismo mecanismo ya en producción para número de transporte.

### Implementación

**`atlas_core/ocr.py`:**
- Extraído `_leer_region_focal(ruta_imagen, caja, lector, allowlist)`: mismo recorte con margen + 4 variantes (original, grises, ampliada 2x LANCZOS, ampliada 2x con contraste) que antes vivía hardcodeado dentro de `_leer_transporte_focal`.
- `_leer_transporte_focal` ahora delega en el helper con `ALLOWLIST_TRANSPORTE = "0123456789OoDdQqIl| .-"` (el mismo string de siempre) — **sin cambio funcional**, confirmado por test que compara ambas rutas byte a byte.
- `_leer_fecha_focal` nuevo, delega en el mismo helper con `ALLOWLIST_FECHA = "0123456789-/ "` — solo dígitos, separadores de fecha y espacio; sin letras de confusión (no se justificaban para este caso).

**`atlas_core/extractor.py`:**
- `_extraer_fecha_geometrico(bloques)` nuevo, mismo patrón que `_extraer_transporte_geometrico`: localiza la etiqueta `FECHA DE EMISION` (tolerante a "FECHA EMISION" / "EMISION" sola por fragmentación de bloques), puntúa candidatos a la derecha/abajo, excluye candidatos más cercanos a una etiqueta rival (`FECHA SALIDA`/`FECHA LLEGADA`/"SALIDA"/"LLEGADA"), y se abstiene (devuelve `{}`) ante ambigüedad (margen 0.06, igual que transporte). Devuelve `{valor, caja, confianza}` — no valida el contenido, solo localiza la zona a recortar.

**`atlas_core/procesamiento_masivo.py`:**
- `_valor_fecha_a_date(valor)` nuevo: convierte un valor ya devuelto por `extraer_fecha` a `date` comparable (soporta DD-MM-YYYY, DD/MM/YYYY, YYYY-MM-DD, YYYY/MM/DD), solo para comparar variantes focales entre sí — no reimplementa ni toca el reconocimiento de `extraer_fecha`.
- `procesar_archivo`: se calcula `fecha_actual = extraer_fecha(textos, ...)` una vez; si ya es distinta de `"No encontrado"` se conserva tal cual y **la ruta focal nunca se ejecuta**. Si es `"No encontrado"`: reutiliza `bloques_guia` si ya se cargó (o lo carga), llama `_extraer_fecha_geometrico`; si no hay caja, se abstiene; si hay caja, ejecuta `_leer_fecha_focal` (4 variantes) y corre `extraer_fecha` (sin tocar sus regex) sobre el texto de cada variante — F1 (guarda de plausibilidad) se aplica automáticamente en cada una de esas llamadas, sin código adicional. Cualquier recuperación focal marca `fecha_recuperada_focal = True`, que se suma a `requiere_revision` (mismo criterio que las demás recuperaciones geométricas/focales del archivo).

**Sin cambios:** regex de `extraer_fecha`, `validar_fecha`, `_clasificar_contexto_fecha`, criterio de selección `min()`, guarda de plausibilidad de F1 (se reutiliza tal cual).

### Auditoría de consenso (F2.1/F2.2, previa al cierre)

La primera versión del consenso agrupaba resultados válidos por fecha comparable y aceptaba con solo `len(votos) >= 2`, sin mirar confianza. Validación real sobre las 30 guías con esa versión: 14/30 → 15/30, pero **1 de las 2 convergencias fue un valor incorrecto** (`IMG-20250930-WA0046.jpg`: 3 de 4 variantes —`original`, `grises`, `ampliada_2x`— coincidieron en `10-09-2025`, dígito de día mal leído; real: `2025-09-30`).

Se auditó el campo `confianza` que `_leer_region_focal` ya calculaba pero el consenso ignoraba (mínimo de las confianzas de los segmentos detectados por variante, metodología ya existente en el código, no inventada para esta auditoría), sobre las 7 imágenes reales donde el localizador geométrico encontró caja:
- Votos del consenso **incorrecto** (`WA0046`): confianzas 0.818 / 0.825 / 0.466 → mínima 0.466.
- Votos del único consenso **correcto** (`WA0047`, `30-09-2025`): confianzas 0.953 / 0.981 → mínima 0.953.
- Margen amplio entre ambos (0.47–0.95): cualquier umbral en ese rango separa los dos casos observados.

### Cambio de cierre: gate de confianza

- Constante nueva `CONFIANZA_MINIMA_FECHA_FOCAL = 0.70`, documentada junto a las constantes de F1, con nota explícita de que está validada sobre muestra limitada y no prueba suficiencia general del OCR.
- El agrupamiento por fecha comparable ahora guarda `(valor, confianza)` por voto. `coincidencias` solo incluye un grupo de fecha si `len(votos) >= 2` **y** `all(confianza >= CONFIANZA_MINIMA_FECHA_FOCAL for cada voto del grupo)` — un voto con confianza `None` (sin segmentos detectados) no puede satisfacer el umbral, así que nunca aporta a un consenso aceptado. Se acepta solo si exactamente un grupo de fecha cumple ambas condiciones.
- Nada más del flujo cambió: no se tocaron regex de `extraer_fecha`, F1, ni cuándo se dispara el focal.

### Tests

- `tests/test_extraer_datos.py` (7 nuevos, del F2 original): candidato a la derecha, candidato debajo, etiqueta ausente, sin candidato, dos candidatos equivalentes → abstención, prioriza EMISIÓN sobre SALIDA cercana, rechaza candidato más cercano a SALIDA que a EMISIÓN.
- `tests/test_ocr.py` (3 nuevos, del F2 original): `_leer_transporte_focal` conserva su allowlist exacto sin cambios; el helper genérico reproduce byte a byte el comportamiento de transporte; `_leer_fecha_focal` usa el allowlist mínimo (incluye `/`, sin letras).
- `tests/test_procesamiento_masivo.py` (7 nuevos en total): fecha global válida → focal nunca se dispara; 2 votos con ambas confianzas ≥0.70 → acepta; **3 votos coincidentes donde uno tiene confianza <0.70 (reproduce `WA0046`) → abstiene**; 2 votos con confianza exactamente 0.70 → acepta (límite inclusive); variantes discordantes → sigue "No encontrado"; candidato focal con año absurdo → descartado por F1 automáticamente; sin caja geométrica → se abstiene sin llamar al focal.
- 2 tests preexistentes (no relacionados con fecha) ajustaron su dato de entrada: usaban `leer_texto_imagen` → `[]`, lo que ahora también deja la fecha en "No encontrado" y dispara la nueva ruta focal — se les agregó una fecha global válida en el texto simulado para preservar su intención original (probar preservación de valores lineales, no fecha).

### Validación final

- Tests específicos del bloque: 7 (procesamiento_masivo) + 7 (extractor) + 3 (ocr) = 17 nuevos en total, todos verdes.
- Suite completa: `441 → 458 passed`.
- Validación real sobre las 30 guías, **OCR ejecutado de nuevo** (dos veces: antes y después del gate de confianza, ninguna reutilizó corpus anterior), llamando a `procesar_archivo` de producción real:
  - Exactitud: **14/30 → 15/30**.
  - Recuperado: `IMG-20250930-WA0047.jpg` → `30-09-2025` (correcto).
  - `IMG-20250930-WA0046.jpg`: ahora `"No encontrado"` (antes era el valor incorrecto `10-09-2025`) — el gate de confianza lo descartó correctamente.
  - **0 recuperaciones incorrectas nuevas. 0 degradaciones de los 14 aciertos previos.**
  - Focal disparado: 7/16 fallos previos (sin cambio, el gate no afecta cuándo se dispara). Convergieron: 1 (antes 2). Se abstuvieron: 6 (antes 5).
  - Tiempo total de la corrida final: 1385.5 s (~23.1 min) para 30 imágenes, pipeline completo de `procesar_archivo` (no solo fecha).

### Estado de cierre

`git status` previo al commit: working tree con 6 rutas de código/tests modificadas (`atlas_core/extractor.py`, `atlas_core/ocr.py`, `atlas_core/procesamiento_masivo.py`, `tests/test_extraer_datos.py`, `tests/test_ocr.py`, `tests/test_procesamiento_masivo.py`) más las 3 bitácoras/handoff.

---

## 2026-08-10 — Bloque Fechas F1: guarda de plausibilidad temporal

**Rama:** `lector-mvp-guia-nueva` · **HEAD previo:** `cab3837 feat: integrar matching difuso conservador de chofer`

### Contexto

Diagnóstico previo (mismo bloque de trabajo) midió el comportamiento real de `extraer_fecha` sobre la muestra histórica de 30 guías (`Atlas\datos_privados\muestra_fechas_30`, ground truth en `Atlas\datos_privados\ground_truth\validacion_atlas_30_guias_v1.xlsx`), ejecutando OCR real (EasyOCR) + `extraer_fecha` sin modificar código: **14/30 exactas**. Búsqueda del texto real en el OCR crudo de los 16 fallos confirmó que en **0 de 16** casos el extractor perdió un candidato correcto disponible — los 16 fallos nacen antes del extractor, en el OCR/calidad de imagen. De esos 16, 3 devolvían un valor con año calendario-imposible en la práctica (`7029`, `7025`, `1024`), aceptado porque `extraer_fecha` no acota el año cuando no se entrega rango explícito.

### Implementación

**`atlas_core/procesamiento_masivo.py`:**
- Constantes nuevas: `ANIO_MINIMO_PLAUSIBLE = 2015`, `ANIO_MAXIMO_PLAUSIBLE = 2035`, `FECHA_MINIMA_PLAUSIBLE`, `FECHA_MAXIMA_PLAUSIBLE`. Centralizadas como constantes de módulo, no hardcodeadas dentro de los regex de `extraer_fecha`.
- Función nueva `_limites_temporales_efectivos(fecha_desde, fecha_hasta) -> tuple[date, date]`: si un límite viene `None`, se completa con la guarda por defecto; si viene explícito, se usa tal cual. **Un límite explícito prevalece por completo sobre el default — no se intersecta con él** (un `fecha_desde`/`fecha_hasta` explícito más amplio que 2015–2035 sigue aceptando años fuera de ese rango).
- `extraer_fecha` calcula `fecha_desde_efectiva`/`fecha_hasta_efectiva` una sola vez al inicio y las usa en ambas pasadas (estricta y tolerante), reemplazando los chequeos `is not None` dispersos por una sola comparación contra los límites ya resueltos.
- Sin cambios en: regex de reconocimiento, `_clasificar_contexto_fecha` (prioridad EMISIÓN>SALIDA>LLEGADA), `_normalizaciones_fecha_unicas`, criterio de selección `min()`, contrato de retorno (sigue devolviendo el valor original, no ISO).

**`tests/test_procesamiento_masivo.py`:**
- Actualizados intencionalmente (comportamiento cambiado a propósito, no regresión):
  - `test_fecha_sin_rango_conserva_comportamiento_de_etapa_uno` → renombrado `test_fecha_sin_rango_descarta_anio_operacionalmente_absurdo`; `extraer_fecha(["FECHA DE EMISIÓN 01-07-7025"])` pasa de esperar `"01-07-7025"` a esperar `"No encontrado"`.
  - `test_procesar_archivo_sin_rango_conserva_compatibilidad` → renombrado `test_procesar_archivo_sin_rango_descarta_anio_operacionalmente_absurdo`; mismo cambio de expectativa vía `procesar_archivo`.
- Tests nuevos (8):
  - `test_fecha_sin_rango_acepta_anio_normal_de_la_muestra` — fecha típica 2025-2026 sin rango sigue aceptándose.
  - `test_fecha_sin_rango_limite_inferior_plausible_es_aceptado` — año 2015 exacto (límite inferior) se acepta.
  - `test_fecha_sin_rango_limite_superior_plausible_es_aceptado` — año 2035 exacto (límite superior) se acepta.
  - `test_fecha_sin_rango_anio_fuera_del_rango_plausible_se_descarta` (parametrizado: 2014 y 2036) — un año fuera del rango por defecto se descarta.
  - `test_fecha_con_rango_explicito_mas_amplio_que_el_default_prevalece` — rango explícito 1990–2099 acepta año 2040, fuera del default; confirma que el explícito no se intersecta con el default.
  - `test_fecha_con_rango_explicito_mas_estrecho_que_el_default_prevalece` — rango explícito más angosto que el default sigue mandando.
  - `test_fecha_sin_rango_candidato_absurdo_y_plausible_elige_el_plausible` — dos candidatos en el mismo texto, uno con año absurdo y otro plausible; se elige el plausible.

### Validación

- `python -m pytest -q` dirigido a los tests del bloque: **12 passed**.
- `python -m pytest -q` suite completa: **433 → 441 passed** (8 tests nuevos, 0 tests rotos fuera de los 2 actualizados intencionalmente).
- Validación sobre las 30 guías reales: se reutilizó el texto OCR ya capturado en la corrida de diagnóstico (mismas imágenes, mismo motor EasyOCR, sin recalcular OCR) y se re-ejecutó únicamente `extraer_fecha` con el código nuevo:
  - Exactitud: **14/30 antes → 14/30 después** (sin cambio).
  - Degradaciones (acierto que pasa a fallo): **0**.
  - Casos que cambiaron de fecha falsa silenciosa a `"No encontrado"`: **3** — `IMG-20250625-WA0039.jpg` (`15-06-7029`→`No encontrado`), `IMG-20250626-WA0019.jpg` (`28-06-7025`→`No encontrado`), `IMG-20250701-WA0007.jpg` (`01-07-1024`→`No encontrado`).
  - Los 27 resultados restantes (14 aciertos + 13 fallas por OCR degradado) quedaron valor por valor idénticos.

### Estado de cierre

`git status`: `lector-mvp-guia-nueva`, sincronizado con `origin`, working tree con exactamente 5 rutas modificadas/nuevas: `atlas_core/procesamiento_masivo.py`, `tests/test_procesamiento_masivo.py`, `docs/BITACORA_EJECUTIVA.md`, `docs/BITACORA_TECNICA_CRONOLOGICA.md`, `docs/HANDOFF_ATLAS.md`.
