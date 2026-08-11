# Handoff — Proyecto Atlas

Estado de traspaso para quien retome el trabajo. Se actualiza al cierre de cada bloque.

---

## 2026-08-11 — Cierre ENTREGAS E1: DESPACHAR A como fuente autoritativa de ruta

- **Rama:** `lector-mvp-guia-nueva`. Baseline anterior: `8b59951a9662c88747fa2e09504acbb09a740188`.
- **REGLA DE NEGOCIO OFICIAL, importante para quien retome esto (prevalece sobre D2/D3/D3.1):** la ruta SIEMPRE debe ser `PLANTA ORIGEN → DESPACHAR A`. `SEÑOR(ES)` es solo el comprador; `OBRA DESTINO` es el proyecto/receptor (puede no tener nada que ver con el nombre del comprador); `DIRECCION`/`COMUNA`/`COD DESTINATARIO` identifican el sitio/obra **registrado**, útiles para identidad comercial (D2/D3) pero **nunca** para reemplazar `DESPACHAR A` como destino de ruta. Ver docstring completo en `atlas_core/rutas/destino_entrega.py` y la bitácora técnica para el texto íntegro de la definición de Javier.
- **Auditoría de COMUNA (hecha antes de tocar código de reglas, como se pidió):** el campo `COMUNA` del formulario NO es confiable para entregas interregionales -- sigue mostrando la comuna del sitio registrado, no la real (confirmado con 3 casos reales: Mejillones, Coronel, Ñuble). Decisión: nunca reutilizar `COMUNA` para geocodificar `DESPACHAR A`.
- **Nuevo módulo `atlas_core/rutas/destino_entrega.py`:** `resolver_destino_entrega()` geocodifica `DESPACHAR A` con abstención ante ambigüedad real (nombres de calle homónimos entre comunas/regiones/países) -- pero distingue eso de "varios candidatos que son el mismo lugar" (números de casa vecinos que Pelias no calzó exacto), usando distancia Haversine (margen 1 km) para no abstenerse innecesariamente. `calcular_ruta_entrega_para_viaje()` orquesta planta origen (reutiliza D2 sin cambios) + esta geocodificación + cálculo de ruta directo (**sin caché todavía** -- una entrega no es una entidad de catálogo, ver Fase E de D3.1). Nunca elige el candidato más cercano a una planta AZA.
- **`calcular_ruta_para_viaje` (D2, basada en catálogo) NO se tocó** -- es una función nueva y aditiva; ambos caminos coexisten (identidad/reporte vs. ruta real).
- **Validación real con ORS, caso ejemplo oficial (guía 464170):** AZA RENCA → "AV. ALMTE. LATORRE 843, MEJILLONES" = **1433.2 km / ~24 horas** -- confirma en la práctica que la ruta correcta es radicalmente distinta de lo que el catálogo (Galvarino 8501, ~7 km) habría sugerido. Un segundo caso (Torres Ocaranza) converge con la cifra ya conocida del catálogo (16.73 vs 16.68 km) cuando `DESPACHAR A` y el sitio registrado coinciden -- validación cruzada de que ambos caminos son consistentes quando corresponde. Un tercer caso (Armacero, "Santa Isabel") se abstuvo correctamente por ambigüedad real de geocodificación (nombre de calle común, resultados en Perú/Argentina/Puerto Rico).
- Suite final: **655 → 665 tests** (10 nuevos). 0 regresiones. No se tocó Desktop, ORS (solo lectura/geocodificación ya existente), ni `destinos_maestros.json`.
- **Pendiente real remanente:** el filtro territorial de la geocodificación es solo texto libre ("... , Chile") -- no un filtro de país estricto (`boundary.country`), por eso nombres de calle comunes (p. ej. "Santa Isabel") devuelven resultados internacionales y se abstienen más de lo ideal. Diseñar el catálogo `destino_entrega` (propuesto en D3.1, no implementado) permitiría cachear entregas ya confirmadas en vez de geocodificar en vivo cada vez.
- **Próximo bloque oficial pendiente (registrado desde D3):** OPERACIÓN O1 — PESO + HORA ENTRADA + HORA SALIDA. No iniciado.

---

## 2026-08-11 — Cierre DESTINOS D3.1: auditoría semántica DIRECCION vs DESPACHAR A + revert controlado

- **Rama:** `lector-mvp-guia-nueva`. Baseline anterior: `7c070a81ff4884556625516aae5785744954c93f`.
- **Objetivo cerrado:** auditar si las 4 confirmaciones de D3 eran evidencia de entrega real o solo de un domicilio/sitio registrado del cliente.
- **Hallazgo importante para quien retome esto — DIRECCION ≠ lugar de entrega:** en el formulario AZA, `DIRECCION`/`COMUNA`/`COD DESTINATARIO` identifican el sitio/obra **registrado** contra el que se emite la guía (puede variar entre guías del mismo cliente), mientras que `DESPACHAR A` es el que mejor representa dónde llegó realmente el camión en ese viaje. Con evidencia real (14 guías, 9 con lectura limpia de ambos campos): **~44-50% de divergencia** entre ambos — no es un caso aislado (incluye un caso interregional: Sodimac, Renca vs Coronel). D2 ya protegía el enrutado con `evaluar_concordancia_despacho`; D3.1 confirma que el fenómeno es frecuente, no una excepción rara.
- **2 confirmaciones de D3 revertidas a `PENDIENTE`** (tras confirmación explícita del usuario, respaldo previo verificado): EBEMA SA/Galvarino 8501 (su única guía real con `DESPACHAR A` observado diverge — Mejillones vs Quilicura) y SALOMÓN SACK SA/Camino Los Pinos 3396 (0 evidencia de `DESPACHAR A`, las 3 guías de ground truth usadas en D3 no relevan ese campo). Ninguna dirección/comuna/región/código/coordenada se tocó ni se perdió evidencia — el motivo queda documentado en `observacion`/`fuente` de cada registro.
- **2 confirmaciones de D3 se mantienen, con evidencia reforzada:** ARMACERO MATCO SA/Santa Isabel 585 y ACEROS COX COMERCIAL SA/Camino Lo Ruiz 2901 — ambas con 2 guías reales independientes donde `DESPACHAR A` concuerda exactamente con el destino.
- **Catálogo real ahora:** 47 destinos, **6 CONFIRMADO** / 41 `PENDIENTE`. Respaldo previo al revert: `C:\Users\Jjjc0508\Desktop\Atlas\backups_catalogos\20260811_pre_revert_d31\`.
- **Propuesta de modelo pendiente de decisión (no implementada):** separar `destinos_maestros.json` (sitio/obra registrado) de un futuro catálogo `destinos_entrega` (punto real, ganado solo por `DESPACHAR A` concordante) — diseño documentado en el reporte del bloque, no ejecutado.
- Suite: **655 tests**, sin cambios (este bloque no tocó código ni tests, solo el catálogo real y bitácoras).
- **Próximo bloque oficial: OPERACIÓN O1 — PESO + HORA ENTRADA + HORA SALIDA.** No iniciado.

---

## 2026-08-11 — Cierre DESTINOS D3: confirmación humana asistida de destinos frecuentes

- **Rama:** `lector-mvp-guia-nueva`. Baseline anterior: `54f484f043f203926ce5ad4a56c8babda1e90f89`.
- **Objetivo cerrado:** aumentar destinos `CONFIRMADO` (43 `PENDIENTE`/4 `CONFIRMADO` al empezar) solo con evidencia real, sin bajar el estándar de seguridad de D2.
- **Fuente nueva importante para quien retome esto:** `datos_privados/ground_truth/validacion_atlas_30_guias_v1.xlsx` — 30 guías reales validadas a mano (cliente, RUT, código destinatario, dirección, comuna, ciudad), no usado en bloques anteriores. Requiere `openpyxl` (se instaló en este bloque, agregarlo a dependencias si se automatiza su lectura).
- **Hallazgo relevante:** el ground truth confirma con datos humanos independientes que el mismo cliente+código puede tener direcciones de entrega distintas entre guías (Torres Ocaranza, guías 390486 vs 428701) — refuerza la decisión de D2 de no tratar el código destinatario como llave autónoma.
- **4 destinos confirmados** (criterio: ≥2 documentos independientes concordantes en cliente+dirección+comuna, más estricto que el mínimo pedido): ARMACERO MATCO SA/Santa Isabel 585 (94 viajes históricos), EBEMA SA/Galvarino 8501 (34), ACEROS COX COMERCIAL SA/Camino Lo Ruiz 2901 (20), SALOMÓN SACK SA/Camino Los Pinos 3396 (3, pero 3 guías independientes de ground truth). Catálogo ahora: 8 `CONFIRMADO` / 39 `PENDIENTE`.
- **1 candidato marcado `CORREGIR DATOS` sin tocar todavía:** AMERICAN SCREW CHILE SPA — la dirección en catálogo ("CAMINO A MELIPILA 10800") tiene una probable falta de ortografía (comparado con 2 fuentes reales que muestran "MELIPILLA"/"MELIPELLA") y le faltan coordenadas — no se corrigió en este bloque para no mezclar corrección con confirmación.
- **0 destinos interregionales en el catálogo hoy** (los 47 son RM) — el ground truth reveló viajes reales a Temuco y Coronel que aún no tienen destino en el catálogo. No se fabricó ninguno.
- **Confirmación 100% no destructiva:** verificado campo por campo (test dedicado) que `CatalogoDestinos.editar()` con `modificacion_manual=True` solo cambió `estado_calidad`/`fuente`/`observacion` en los 4 destinos — dirección/comuna/región/código/coordenadas intactos.
- **3 rutas reales desbloqueadas, ORS real:** AZA RENCA→Armacero/Santa Isabel 585 (12.97 km/19.7 min), AZA RENCA→Aceros Cox/Camino Lo Ruiz 2901 (2 guías reales, 0.09 km — domicilios contiguos, resultado real). La guía 464170 (EBEMA, destino ya confirmado) **sigue bloqueada** por el gate de concordancia `DESPACHAR A` de D2 — prueba de que confirmar identidad no relaja la protección por viaje individual.
- Suite final: **643 → 655 tests** (12 nuevos). 0 regresiones. Sin cambios de código de producción — D3 es puramente confirmación de datos usando la maquinaria ya construida en D2.
- **Respaldo antes de tocar el catálogo:** `C:\Users\Jjjc0508\Desktop\Atlas\backups_catalogos\20260811_pre_confirmacion_d3\destinos_maestros.json`, verificado por checksum.
- **Artefactos de esta revisión:** `C:\Users\Jjjc0508\Desktop\Atlas\destinos_revision\` (ranking completo de 47 destinos con evidencia cruzada + 10 fichas de revisión con recomendación individual).
- **Próximo bloque oficial: OPERACIÓN O1 — PESO + HORA ENTRADA + HORA SALIDA.** No iniciado.

---

## 2026-08-11 — Cierre DESTINOS D2: resolución canónica de destino estructurada

- **Rama:** `lector-mvp-guia-nueva`. Baseline anterior: `3f28e4cc6876253dc8a528dbd9ef8651e5daa7e7`.
- **Objetivo cerrado:** la verificación final de rutas del bloque anterior mostró que casi ninguna guía real homologaba destino, porque `obra_destino` (texto OCR, nombre comercial) casi nunca coincide con `nombre_destino` en el catálogo (poblado con direcciones). Este bloque prioriza identificadores estructurados del propio documento (`COD DESTINATARIO`, `DIRECCION`, `COMUNA`) sobre ese emparejamiento textual débil.
- **Nuevo módulo `atlas_core/rutas/destino_estructurado.py`**, no invasivo: `resolver_destino_canonico_estructurado(...)` con jerarquía A (código destinatario) → B (dirección+comuna) → C (alias acotado a cliente) → D (comportamiento histórico global, sin cambios) → abstención. `calcular_ruta_para_viaje` gana 3 parámetros opcionales (`cliente_texto`, `catalogo_clientes`, `rut_cliente_texto`) — sin ellos, comportamiento **idéntico** a antes de este bloque.
- **Corrección de rumbo importante a mitad de bloque (evidencia externa validada con datos propios):** `COD DESTINATARIO` NO es una llave segura por sí sola — el mismo código/cliente puede tener un `DESPACHAR A` (punto de entrega real de ESE viaje) distinto del domicilio registrado. Se agregó `evaluar_concordancia_despacho`: un destino resuelto por identidad se contrasta contra `DESPACHAR A` antes de llamar a ORS; si diverge, `REQUIERE_REVISION`/`DESPACHO_DIVERGENTE_DEL_DESTINO_CANONICO` en vez de una ruta silenciosamente incorrecta.
- **Caso 464170 (el que motivó este bloque) queda cerrado y explicado:** homologa por identidad a EBEMA SA/Galvarino 8501 (Quilicura, RM), pero su `DESPACHAR A` real es Mejillones (Región de Antofagasta, ~1.400 km de distancia) — **no** se calcula una ruta automática para esa guía; queda correctamente en revisión.
- **1 viaje real end-to-end, identidad 100% resuelta por código/dirección/concordancia, sin destino inyectado:** guía 464424, TORRES OCARANZA LTDA (destino ya `CONFIRMADO`) → AZA RENCA → Vista Clara 2351 = **16.68 km / 24.53 min** (ORS real). El `cliente` de esta guía puntual no lo extrae el pipeline (falla preexistente y ajena a este bloque, confirmada con `extraer_datos()` puro); se usó el texto literal que trae el propio documento como diagnóstico, declarado explícitamente como tal.
- Suite final: **629 → 643 tests** (14 nuevos). 0 regresiones.
- **Pendiente real remanente:** la mayoría de destinos reales del catálogo siguen `PENDIENTE` (no `CONFIRMADO`) — bloquean el cálculo de ruta por diseño hasta confirmación humana explícita, no por un límite de este bloque. El extractor lineal de `cliente`/`obra_destino` sigue fallando en algunas guías (ajeno a destinos, requeriría bloque propio). No se tocó ORS, Desktop, ni ningún extractor.

---

## 2026-08-11 — Cierre: migración de endpoint ORS + validación real con credencial

- **Rama:** `lector-mvp-guia-nueva`. Baseline anterior: `ccc777229cbd072b1f89e5d60efbd5620859731a`.
- **Endpoint ORS migrado, URGENTE para quien retome esto:** `api.openrouteservice.org` se apaga el **24-ago-2026** (anuncio oficial HeiGIT, 28-abr-2026). El adaptador (`atlas_core/rutas/openrouteservice.py`) ahora usa `api.heigit.org`: direcciones en `/openrouteservice/v2/directions/{perfil}`, geocodificación migró de `/geocode/search` a la estructura Pelias `/pelias/v1/search`. Misma API key sirve para ambos hosts, sin cambio de credencial ni de contrato (`ProveedorRutas` intacto).
- **`OPENROUTESERVICE_API_KEY` ya está configurada** como variable de entorno de **usuario** de Windows en este PC (no de sistema, no en `.env` del repo). Configurada directamente por Javier en su propia terminal — el valor nunca pasó por Claude en ningún momento (ni se pidió pegarlo en el chat, ni se registró, ni se escribió en archivo alguno).
- **Nota técnica para quien retome esto:** una variable de entorno de **usuario** recién creada con `[Environment]::SetEnvironmentVariable(...,"User")` no se propaga automáticamente al bloque de entorno de un proceso/shell ya en ejecución (solo la ve `[Environment]::GetEnvironmentVariable(...,"User")`, que lee directo del registro). Para que un proceso hijo (p. ej. `python`) la vea vía `os.getenv(...)`, hace falta puentearla explícitamente en la misma invocación: `$env:OPENROUTESERVICE_API_KEY = [Environment]::GetEnvironmentVariable("OPENROUTESERVICE_API_KEY","User")` antes de lanzar el proceso — o reiniciar la sesión/terminal.
- **Validación real, con credencial real, perfil `driving-hgv`:**
  - Prueba mínima (AZA RENCA → EBEMA SA): `RUTA_CALCULADA` (no `SIN_CREDENCIAL`).
  - 3 rutas reales, coordenadas ya existentes en catálogo (sin geocodificar de nuevo): AZA_RENCA→EBEMA SA/Galvarino 8501 (7.43 km, 12.1 min), AZA_COLINA→Torres Ocaranza Ltda (49.70 km, 59.9 min), AZA_RENCA→DSI Underground Chile SpA (33.17 km, 40.4 min). Tiempos de respuesta 0.80-0.86s.
  - **Caché (`RepositorioRutas`) verificado end-to-end** vía `ServicioRutas.confirmar_y_calcular`: primera consulta AZA_RENCA→Torres Ocaranza → `RUTA_CALCULADA` (1 llamada real a ORS, contada con un wrapper de conteo, sin tocar el adaptador); segunda consulta idéntica → `RESULTADO_DESDE_CACHE`, **0 llamadas nuevas a ORS**, mismo `distancia_km`/`duracion_estimada_min` que la primera. Clave lógica confirmada: `planta_id + destino_id + perfil + proveedor + version`.
- Suite final: **603/603 tests** (601 → 603, 2 nuevos que fijan el host vigente y evitan una regresión silenciosa al host deprecado).
- **0 secretos en git** — el repo solo tiene el cambio de host (2 constantes) y los 2 tests nuevos; ningún archivo de credenciales, `.env` real, ni valor de clave fue tocado o creado dentro del repo.
- **Próximo bloque:** conectar km/tiempos al flujo real (Desktop, reportes) — explícitamente no iniciado en este bloque.

---

## 2026-08-11 — Cierre Bloque D1: separar GIRO de obra_destino

- **Rama:** `lector-mvp-guia-nueva`. Baseline anterior: `66d0edabbfd506795dc675f2149e4875dc6fede2`.
- **Objetivo cerrado:** `obra_destino` seguía devolviendo el valor de GIRO (`"VENTA AL POR MAYOR D"`) en la guía real `464170`, en vez del destino real (`"SUPERMERCADO SEÑOR DE LOS MI"`) — prerrequisito directo del próximo frente RUTAS/KM/TIEMPOS.
- **Causa exacta en `_extraer_asociaciones_geometricas` (`atlas_core/extractor.py`):** (1) `nominal()` rechazaba cualquier candidato que contuviera la subcadena "SEÑOR" — incluyendo el propio nombre real del destino, que casualmente contiene esa palabra; (2) sin ese candidato, GIRO (columna vecina, misma fila que OBRA DESTINO — patrón de formulario en dos columnas de este proveedor AZA) quedaba como única opción restante y ganaba por defecto, sin ninguna regla que lo excluyera.
- **Fix, general y sin heurísticas de guía:**
  - `nominal()` ya no descarta por subcadena "SEÑOR"; en su lugar descarta solo si el bloque completo *es* la etiqueta SEÑOR(ES) vía `_es_etiqueta_senor` (mismo criterio que C1 ya usa para la etiqueta, ahora aplicado también al lado del candidato).
  - Nueva identificación explícita de GIRO (`es_etiqueta_giro`) y de "cuál sería el propio valor de GIRO" (`_mejor_candidato`, misma función `puntuar` que usa el resto de la lógica): ese bloque queda excluido, por identidad, de competir como candidato de `obra_destino`. **Deliberadamente no se implementó por comparación de distancias** (primer intento, descartado): en este documento GIRO y OBRA DESTINO son columnas vecinas casi equidistantes de sus respectivos valores, y una comparación de distancia bruta puede perder por márgenes de 1-2 px — la exclusión por identidad es exacta y no depende de umbrales.
- **Bug colateral encontrado y corregido durante la validación con cajas reales exactas:** `_extraer_rut_cliente_geometrico` (C1, Parte D) nunca se activaba en producción real — exigía gap **estrictamente positivo** entre las etiquetas SEÑOR(ES) y R.U.T., pero PaddleOCR entrega esas dos filas con cajas exactamente adyacentes (gap 0) en este documento. El reporte de cierre de C1 afirmó erróneamente `rut_cliente = 83.585.400-0` como validado en el pipeline real — en realidad esa verificación se hizo solo con coordenadas de test redondeadas que evitaban el caso límite por casualidad, y el campo ni siquiera se expone en el dict que devuelve `procesar_archivo`. Corregido (`>` → `>=`) y confirmado ahora con las cajas reales completas.
- **Catálogo (solo inspección, sin conectar nada nuevo):** el destino real de EBEMA SA existe en `%LOCALAPPDATA%\Atlas\datos\catalogos_privados\destinos_maestros.json` — registro con `cliente_id` que coincide exactamente con el de EBEMA SA en `clientes.json`, dirección `GALVARINO 8501, QUILICURA, CHILE` ya geocodificada (lat/lon, `GEOCODIFICACION_ORS`, confidence 0.8, match_type=fallback). El nombre canónico ahí es la dirección, no "SUPERMERCADO SEÑOR DE LOS MI" — homologar por `cliente_id` cruzando catálogos es una integración nueva, fuera de alcance de D1; queda para RUTAS.
- **Caso real validado, guía `464170`, PaddleOCR GPU, catálogo activo real:** `obra_destino`: `"VENTA AL POR MAYOR D"` → **`"SUPERMERCADO SEÑOR DE LOS MI"`**. `cliente=EBEMA SA`, `chofer=IVAN ROA` (homologado), `rut_chofer=10190440-7` sin cambios respecto a C1.
- **Validación adicional corta (4 guías reales, destino ya conocido antes de este fix): `464511`, `464493`, `464479`, `464494`** — cliente/obra_destino/chofer/indicador_revision idénticos antes y después, 0 regresiones.
- Suite final: **601/601 tests** (594 → 601).
- **Próximo bloque oficial: RUTAS-EVAL / RUTAS R1** — comparación corta de proveedores y recuperación de infraestructura de km/tiempos, usando como insumo el destino ya recuperado por este bloque y la dirección canónica ya geocodificada encontrada en `destinos_maestros.json`. No iniciado.

---

## 2026-08-11 — Cierre PLANTA-P1: resolución real de planta origen

- **Rama:** `lector-mvp-guia-nueva`. Baseline anterior: `1a108038fa5a3f7cfe25c13189051980ae8294f9`.
- **Onelogis histórico, IMPORTANTE — no repetir la auditoría desde cero:** Javier confirmó manualmente (cuenta propia, navegación normal) que Onelogis **sí** tiene histórico de viajes/recorridos consultable por fecha. Eso no está en duda. Lo que se auditó y sigue siendo cierto es que **la integración técnica de Atlas** (`Atlas-Viajes-Desktop-Restaurado/src/gps_logic.js` + `main.js`, endpoint propio `.../gps/ultimas-posiciones`) no expone ese histórico — solo última posición. Se buscó también públicamente (sitio `onelogis.com`) sin encontrar documentación de API. **No se intentó** adivinar rutas de endpoint contra el sistema en vivo ni automatizar el navegador de Onelogis (fuera de alcance explícito). Para desbloquear el GPS histórico de verdad hace falta que Javier revise, dentro de su cuenta Onelogis, si existe una sección de API/integraciones/exportación, o contacte a su soporte — eso no es algo que se pueda determinar por auditoría de código.
- **Fallback documental — nuevo módulo `atlas_core/rutas/origen_documental.py`:** adaptación de `_resolver_origen_documental` (rama remota `origin/feature-cobertura-origen-fase1`, commit `2c5c764`, validado 7/9 real). Diferencia clave respecto al original: el original releía un recorte focal del encabezado con `lector.readtext()` de EasyOCR directo (mismo problema de acoplamiento que otros focales ya migrados); la versión nueva opera sobre `textos` de página completa (mismo `texto` que ya produce PaddleOCR en el flujo normal) — no hace falta relectura focal aparte porque Paddle ya lee el encabezado con confianza alta. Conserva intacta la lógica de corte antes de "SUCURSAL" (evita que el directorio de sucursales de toda guía AZA contamine el voto) y la exigencia de planta única sin ambigüedad.
- **`atlas_core/rutas/enriquecimiento_viaje.py`:** `resolver_planta_origen` ahora implementa la jerarquía GPS → documento → no determinado, y devuelve un 4-tuple `(planta, motivo, determinado_por, evidencia)` — **cambio de firma respecto a RUTAS R1** (era 2-tuple); el único call-site externo (un test) se actualizó. Política de conflicto: si el GPS determina una planta, esa gana siempre — el documento solo se consulta cuando el GPS no resuelve nada, nunca para desempatar. Fix defensivo añadido: si la planta determinada no tiene coordenadas cargadas en catálogo, se trata como `ORIGEN_NO_DETERMINADO` (motivo `PLANTA_SIN_COORDENADAS_EN_CATALOGO`) en vez de lanzar una excepción — este caso era real (ver corrección de catálogo abajo).
- **`ResultadoEnriquecimientoRuta`** gana el campo `evidencia_origen` (para GPS: timestamp+distancia a la geocerca; para documento: `"ENCABEZADO_GUIA"`). Propagado también a `reporte_viajes.py` (`COLUMNAS_VIAJES` y `_CAMPOS_RUTA_VACIOS`), backward-compatible igual que el resto de columnas de ruta.
- **Corrección de catálogo (con respaldo previo en `Desktop\Atlas\backups_catalogos\20260811_104321_pre_coordenadas_aza_colina\`):** `AZA COLINA` en `plantas.json` no tenía `latitud`/`longitud` cargadas desde antes de este bloque (bloqueaba cualquier cálculo de ruta real con ese origen, incluso con la planta ya determinada). Se completó reutilizando la coordenada ya geocodificada vía ORS para la misma dirección física (presente en `destinos_maestros.json` bajo "ACEROS AZA SA", ya usada como workaround en RUTAS R1) — `lat=-33.137558, lon=-70.665977` (ORS fallback, confidence 0.6, nivel calle/comuna, documentado así en la observación del registro). Editado vía `CatalogoPlantas.editar()` (API validada, no edición JSON manual), verificado releyendo desde disco tras escribir.
- **Validación real (12 guías AZA reales disponibles hoy, PaddleOCR real):** el set histórico original de 9 guías (`464089`, `462429`, `464106-464110`, `464259`) **no está disponible como archivo de imagen en este equipo** — se usó el set real actualmente accesible en `output/_entrantes_desktop` (12 guías, todas AZA, todas con "CASA MATRIZ PLANTA RENCA" legible en el encabezado real). Resultado: **11/12 resueltas correctamente a AZA RENCA, 1/12 (`464493.jpeg`) se abstuvo en vez de arriesgar** — causa diagnosticada: en esa guía específica, Paddle leyó "Sucursal" como "ursal"/"Cursal" (perdió el prefijo "Su"/"S"), fuera de la tolerancia de edición-1 + diferencia de longitud ≤1 del corte — el corte nunca se activó, "COLINA" del directorio de sucursales quedó en el texto comparado, y al aparecer junto con "RENCA" generó ambigüedad real (2 coincidencias) → abstención correcta, no un bug. **0 asignaciones incorrectas.**
- **Fase E, conectado a ORS real + caché real:** AZA RENCA (documento, guía real `464170`) → Torres Ocaranza Ltda = **16.68 km / 24.53 min** (coincide exactamente con el mismo par calculado en RUTAS R1 vía GPS inyectado — buena señal cruzada). AZA COLINA (documento, patrón real de encabezado AZA) → Prodalam SA = **41.31 km / 47.35 min**. Repetir el primer par → `RESULTADO_DESDE_CACHE`, mismo resultado, 0 llamadas nuevas a ORS.
- Suite final: **618 → 629 tests** (10 nuevos en Fase F + 1 test defensivo de la Fase E). 0 regresiones.
- **0 secretos**: verificado con `grep` sobre todos los artefactos de `rutas_eval/` antes de commitear.
- **Próximo bloque, si se decide perseguir GPS histórico real:** que Javier confirme desde su cuenta Onelogis si existe una vía de API/exportación oficial. Sin eso, el mecanismo documental ya implementado es la vía de producción para AZA RENCA (validada); ampliar la validación real a más guías de AZA COLINA (solo se probó con patrón sintético, no con una imagen real de guía Colina — no había ninguna disponible en este equipo) sigue pendiente.

---

## 2026-08-11 — Cierre RUTAS R1: km/tiempos conectados al viaje + auditoría Onelogis

- **Rama:** `lector-mvp-guia-nueva`. Baseline anterior: `5f201d418a3fcd6ee1287d1e05b1335efe87e043`.
- **Auditoría Onelogis, importante para quien retome esto:** la integración GPS/Onelogis real vive en `Atlas-Viajes-Desktop-Restaurado/src/gps_logic.js` (función `obtenerUltimasPosicionesGps`, consumida por `main.js` vía IPC `atlas:gps-obtener-posiciones`, configurada en `gps_config.json`/electron-store con `url`+`apiKey`). Devuelve un array `vehiculos` con `{patente, estado, latitude, longitude, speed, timestamp}` — **solo la última posición conocida de cada patente**, refrescada cada 30s mientras la pestaña GPS del Desktop está abierta. **No existe ningún endpoint ni archivo en todo el repo/backup que exponga histórico de posiciones por fecha/hora.** Esto es estructural: para una guía ya procesada (workflow normal, no en tiempo real), no hay forma de consultar "dónde estaba la patente X cuando salió" con la integración actual. Confirmado también que la documentación propia del proyecto (`docs/CATALOGO_TRANSPORTISTAS_ATLAS.md`) ya marca cualquier ampliación de Onelogis como sujeta a autorización + auditoría de privacidad independiente.
- **Nuevos módulos (`atlas_core/rutas/`):**
  - `posicion_vehiculo.py`: contrato `ProveedorPosicionVehiculo` (`obtener_posicion(patente, instante) -> ResultadoPosicionVehiculo`) + doble simulado `ProveedorPosicionVehiculoSimulado` (mismo patrón que `ProveedorRutasSimulado`). **No hay adaptador real** todavía — no existe capacidad histórica real contra la cual conectarlo.
  - `geocerca.py`: `resolver_planta_por_posicion(posicion, plantas, radio_km)` — distancia Haversine, radio conservador `1.5 km` (propuesto, no calibrado contra datos reales — no existen posiciones históricas reales para calibrarlo). AZA Renca/Colina están a decenas de km entre sí (confirmado con ORS real), por lo que este radio nunca genera ambigüedad entre ambas.
  - `enriquecimiento_viaje.py`: orquestador `calcular_ruta_para_viaje(...)` = destino canónico (`resolver_destino_canonico`, reutiliza `CatalogoDestinos.buscar()` ya existente sobre `destinos_maestros.json`, exige `ACTIVO` + coordenadas dentro de un rango geográfico plausible de RM `lat∈[-34.5,-32.5], lon∈[-71.5,-70.0]` — excluye de forma general, no por nombre, los registros "SAN MIGUEL" con coordenada errónea de RUTAS-EVAL R1) → planta de origen (`resolver_planta_origen`, exige GPS dentro de geocerca **y** timestamp a menos de 2h del instante de salida, si no: `ORIGEN_NO_DETERMINADO`) → `ServicioRutas.confirmar_y_calcular(perfil="driving-hgv")` ya existente (caché incluido). Nunca lanza: cualquier fallo en cualquier paso devuelve campos vacíos + `estado_ruta`/`motivo_ruta` explicativos.
- **`atlas_core/rutas/modelos.py`:** 2 estados nuevos en `EstadoRuta`: `ORIGEN_NO_DETERMINADO`, `DESTINO_NO_VALIDO`.
- **`atlas_core/reporte_viajes.py`:** `COLUMNAS_VIAJES` gana 10 columnas al final (`planta_origen_id`, `planta_origen_nombre`, `destino_id`, `destino_nombre`, `distancia_km`, `duracion_min`, `proveedor_ruta`, `estado_ruta`, `motivo_ruta`, `origen_determinado_por`); `generar_reporte_viajes()` gana un parámetro opcional `calculador_rutas: Callable[[Viaje], dict] | None = None` — sin él (default), columnas vacías, reporte idéntico a antes de este bloque. Desktop **no se tocó**.
- **Validación real (catálogo activo real, `%LOCALAPPDATA%\Atlas\datos\catalogos_privados`, ORS real, `driving-hgv`), 3 viajes:**
  1. **EBEMA SA / Galvarino 8501**: planta AZA RENCA determinada (posición GPS **inyectada/simulada** para esta prueba — ver nota abajo), destino homologado, pero `ServicioRutas` bloquea correctamente con `REQUIERE_REVISION`/`DESTINO_NO_CONFIRMADO` porque el destino real de EBEMA sigue `estado_calidad=PENDIENTE` en el catálogo — **no se fuerza ni se relaja esa salvaguarda ya existente**.
  2. **Torres Ocaranza Ltda / Vista Clara 2351** (destino `CONFIRMADO`): AZA RENCA → **16.68 km / 24.53 min**, `RUTA_CALCULADA`. Repetir la misma consulta (otra "guía", mismo transporte/destino/perfil/proveedor/versión) → `RESULTADO_DESDE_CACHE`, mismo resultado, **0 llamadas nuevas a ORS**.
  3. **Mismo destino que el viaje 2, patente sin dato GPS**: `ORIGEN_NO_DETERMINADO`/`GPS_SIN_DATOS`, sin llamar a ORS, viaje sigue válido.
- **Nota sobre "planta detectada por GPS" en la prueba real:** dado que no existe consulta histórica real (ver auditoría), el viaje 2 usa una posición GPS **inyectada** (coordenada real de AZA Renca, marcada explícitamente como `simulado_demo_geocerca`) para demostrar que el mecanismo de resolución completo (geocerca → ServicioRutas → caché) funciona correctamente de punta a punta con datos reales de catálogo y ORS real — **no** es una determinación en tiempo real de dónde estuvo un camión histórico. Para eso hace falta el siguiente bloque.
- Suite final: **603 → 618 tests** (15 nuevos: 13 en `test_rutas_enriquecimiento_viaje.py`, 2 en `test_reporte_viajes.py`; 1 assertion existente en `test_rutas_modelos.py` actualizada para los 2 estados nuevos). 0 regresiones.
- **0 secretos**: verificado con `grep` sobre `rutas_eval/*.json` y `viajes.csv` de prueba antes de commitear.
- **Siguiente bloque obligatorio: PLANTA-P1 / ONELOGIS.** Antes de mostrar km/min automáticos en Desktop hace falta: (a) confirmar con Onelogis si existe o puede habilitarse un endpoint histórico de posiciones por patente+fecha/hora (hoy no existe en la integración auditada), o (b) definir una estrategia alternativa de determinación de planta (p. ej. evidencia documental — existe un resolver `_resolver_origen_documental` con 7/9 de cobertura real en la rama remota no fusionada `origin/feature-cobertura-origen-fase1`, ver nota técnica). Sin uno de los dos, `planta_origen` seguirá cayendo mayormente en `ORIGEN_NO_DETERMINADO` para guías procesadas después del hecho — correcto y seguro, pero no automático.

---

## 2026-08-11 — Cierre Bloque C1: cliente + chofer nuevo + propagación de REVISAR al viaje

- **Rama:** `lector-mvp-guia-nueva`. Baseline anterior: `129b459d936d6d05ae0615cc93fa8842440f4d3a`.
- **Objetivo cerrado:** caso real guía `464170` — `cliente` vacío y chofer `NO HOMOLOGADO` con OCR correcto (`SEÑOR(ES): EBEMA SA`, `RETIRA: IVAN ROA`, `RUT CHOFER: 10190440-7`), viaje `CONFIRMADO` en silencio con esos campos vacíos. Diagnóstico previo ya cerrado; C1 corrige las causas.
- **Fuente de catálogos activa real, importante para quien retome esto:** NO es ninguna de las carpetas `Desktop\Atlas\Atlas-Viajes-*-Rollback-*` (son respaldos/snapshots). La fuente que el Desktop instalado usa de verdad está en `config_usuario.json` del electron-store (`%APPDATA%\atlas-viajes-desktop\config_usuario.json`, `modoCatalogos: OBLIGATORIO`) y apunta a `%LOCALAPPDATA%\Atlas\datos\catalogos_privados`. Ahí se hizo el alta de IVAN ROA, no en el repo.
- **Cambios en `atlas_core/extractor.py`:** `_normalizar_acentos()` centraliza Ñ→N (antes solo `_texto_simple` lo hacía; `texto_busqueda` de `extraer_datos` y `normalizar_cliente`/`normalizar_obra_destino` no); `_es_etiqueta_senor()` exige que el bloque completo (no una subcadena) sea la etiqueta SEÑOR(ES)/SEÑORES/SEÑOR(IES)/SEÑORIES, usado por `_extraer_asociaciones_geometricas`; nueva `_extraer_rut_cliente_geometrico()` (zona SEÑOR(ES)/R.U.T., valida con `validar_rut_chileno`, se abstiene ante ambigüedad); `buscar_rut_chofer()` ahora tolera `:` entre la etiqueta y el valor.
- **`atlas_core/procesamiento_masivo.py`:** `RUT del cliente` se agregó a `campos_ausentes` y se conecta `_extraer_rut_cliente_geometrico` como fallback, mismo patrón que cliente/obra/chofer/transporte/patentes.
- **`atlas_core/gestor_viajes.py`:** nuevo `MotivoRevision.DOCUMENTO_REQUIERE_REVISION` — si cualquier documento del viaje trae `indicador_revision=REVISAR`, el viaje no puede quedar `CONFIRMADO`, independiente de si hay o no contradicciones con otros documentos del mismo transporte (esos conflictos existentes se preservan intactos).
- **IVAN ROA dado de alta** en el catálogo activo real como chofer canónico (RUT `10190440-7`, sin alias — es nuevo real, confirmado por Javier). Respaldo íntegro previo en `Desktop\Atlas\backups_catalogos\20260811_063918_pre_alta_ivan_roa\`.
- **Caso real validado, guía `464170`, PaddleOCR GPU, catálogo activo real:**
  - Antes: `cliente=No encontrado`, `rut_cliente=No encontrado`, `chofer=IVAN ROA` (sin homologar), `rut_chofer=No encontrado`, viaje `CONFIRMADO` sin motivo.
  - Después: `cliente=EBEMA SA`, `rut_cliente=83.585.400-0`, `chofer=IVAN ROA` (homologado exacto contra catálogo), `rut_chofer=10190440-7`, viaje `REQUIERE_REVISION` (motivo `DOCUMENTO_REQUIERE_REVISION`, legítimo: el documento siguió necesitando recuperación geométrica).
- Suite final: **594/594 tests** (581 → 594). 0 regresiones (las 4 fallas transitorias durante el desarrollo eran fixtures de `test_procesamiento_masivo.py` que no incluían `RUT del cliente`; se actualizaron sin tocar su intención original).
- **Pendiente conocido, no bloqueante:** `obra_destino` sigue devolviendo el valor de GIRO (`"VENTA AL POR MAYOR D"`) en vez del destino real (`"SUPERMERCADO SEÑOR DE LOS MI"`) — mismo tipo de colisión geométrica que motivó C1, pero en el campo obra_destino, no cliente.
- **Próximo bloque oficial: DESTINO D1** — corregir `obra_destino`/GIRO, prerrequisito directo de rutas/KM/tiempos. No iniciado; no se tocó nada de ese frente en C1.

---

## 2026-08-10 — Cierre Patentes P2: homologación conservadora contra catálogo de vehículos

- **Rama:** `lector-mvp-guia-nueva`. Baseline anterior: `0021bde59a9bb2f7b18462377ea6634d5cade781`.
- **Objetivo cerrado:** homologación canónica de patentes contra el catálogo de vehículos (`vehiculos.json`, vía `carpeta_catalogos`), nueva función `resolver_patente_canonica` en `atlas_core/catalogos.py`, wireada en `procesar_archivo`.
- **Jerarquía:** (A) coincidencia exacta normalizada, (B) alias explícito declarado en el catálogo, (C) corrección OCR conservadora — solo con un único candidato, misma longitud, y una única diferencia posicional explicada por una confusión OCR documentada (B/D, 0/O, 1/I, 5/S, 8/B). Nunca crea una patente nueva.
- **Caso real confirmado, guía `464511`:** `patente_tracto` `SD6486 → SB6486` (corrección OCR conservadora, catálogo real); `patente_rampla` `JF4288 → JF4288` (coincidencia exacta, sin cambios). **La corrección no está hardcodeada por archivo** — surge de la jerarquía general aplicada contra el catálogo real.
- **Política de abstención:** ambigüedad → conserva el valor OCR y marca `REVISAR`; sin catálogo → no inventa nada.
- PaddleOCR, Desktop y generación de reportes no se tocaron — Desktop y reportes reciben el valor homologado automáticamente al consumir el dict de `procesar_archivo`.
- Suite final: **581/581 tests** (566 → 581).
- **Frente de patentes (P1 + P2) queda cerrado.** No hay un próximo microbloque de patentes definido.

---

## 2026-08-10 — Cierre Patentes P1: recuperación geométrica de patentes compatible con Paddle

- **Rama:** `lector-mvp-guia-nueva`. Baseline anterior: `0bcb43ca56e5ab1cdc6f596bb80af225ce234739`.
- **Problema resuelto:** `patente_tracto`/`patente_carro` volvían `"No encontrado"` con salida Paddle porque la extracción original exigía la frase contigua `"RETIRA PATENTE FECHA LLEGADA"`, y Paddle reparte esas etiquetas en bloques/líneas separados. Se agregó `_extraer_patentes_geometrico` (`atlas_core/extractor.py`), nueva función geométrica que ancla en la zona RETIRA–FECHA LLEGADA por coordenadas, activa solo como *fallback* cuando la lectura lineal ya devolvió "No encontrado". **PaddleOCR no se tocó.**
- **Camino histórico EasyOCR preservado:** `buscar_chofer_y_patentes()` (lectura lineal por frase contigua) no se modificó.
- **Alcance deliberadamente acotado:** P1 recupera el valor OCR disponible, no lo corrige. La guía real `464511` recupera `patente_tracto = SD6486` (el valor que Paddle realmente lee, con una B leída como D) y `patente_rampla = JF4288` (correcto); no se corrige `SD6486` a `SB6486`.
- Suite final: **566/566 tests** (556 → 566).
- No se tocó Desktop ni la generación de reportes — ambos consumen el dict que devuelve `procesar_archivo`, así que reciben el valor recuperado automáticamente sin cambios propios.
- **Próximo microbloque pendiente:** homologación de patente OCR contra catálogo de vehículos (ejemplo `SD6486 → SB6486`), sin alterar el OCR. No iniciado.

---

## 2026-08-10 — Integración Desktop ↔ Motor Paddle cerrada

- **Rama:** `lector-mvp-guia-nueva`. Baseline anterior: `e61c04af4081b3d52761ad7928291bd88b6a83d2`.
- Atlas Viajes Desktop 1.4.3 y el motor vuelven a compartir el contrato histórico `--catalogos <ruta>`. También se admite `ATLAS_CATALOGOS_DIR`; fuentes incompletas, inexistentes o compuestas solo por plantillas `.example` se rechazan.
- `resumen_procesamiento_desktop.py` fue recuperado desde Git y verificado contra su blob histórico. `generar_reporte_viajes.py`, `atlas_core/gestor_viajes.py` y `atlas_core/reporte_viajes.py` también fueron recuperados desde la línea histórica compatible y validados contra el HEAD actual.
- La propagación de catálogos fue fusionada selectivamente con M2. **PaddleOCR continúa como proveedor principal**, GPU activa en este PC, proveedor único reutilizado por lote y EasyOCR disponible como fallback.
- Suite final: **556/556 tests**.
- Prueba manual end-to-end exitosa: Desktop procesó la guía real `464511`, obtuvo transporte `0000352449`, fecha `10-08-2026`, cliente `ARMACERO MATCO SA` y chofer `RODRIGO NAHUELÑIR`; el viaje se mostró correctamente en Atlas Viajes 1.4.3 con estado OK.
- Los 574 viajes operativos no fueron reprocesados ni modificados durante las pruebas técnicas aisladas.
- **Próximo frente:** RECUPERACIÓN UX HISTÓRICA del Desktop. No iniciar cambios del motor como parte de ese frente. Antes de considerar perdido un archivo o comportamiento, revisar `G:\Mi unidad\BACKUP_PRE_FORMATEO_20260808`.

---

## 2026-08-10 — Cierre Bloque M2: runtime Paddle portable + activación batch (pendiente de tu aprobación final)

- **Rama:** `lector-mvp-guia-nueva`. **Sin commit, sin push** — a la espera de que apruebes antes de cerrar formalmente (a diferencia de M1, aquí no hice el commit todavía porque me pediste el reporte de los 10 puntos primero).
- **Runtime portable resuelto:** `%LOCALAPPDATA%\Atlas\runtime\paddleocr` (variable de entorno `ATLAS_PADDLE_RUNTIME` disponible como override de desarrollo). Ya no depende de `ocr_eval_gpu_env` ni de ninguna ruta de este PC — confirmado por tests y por `grep` sobre la validación real.
- **`procesar_carpeta` ya activa PaddleOCR en el flujo real de lote** — antes de este bloque solo `procesar_archivo` sabía usar un proveedor; ahora la CLI real (`analizar_guias_masivo.py`) lo hace por defecto, con un único proveedor por ejecución.
- **Validado con una instalación real desde cero** (no simulada): el bootstrap completo tomó 209 s. Una corrida corta real de 4 guías con la CLI real confirmó GPU seleccionada automáticamente, un solo mensaje de proveedor activo (no uno por imagen), y resultados correctos.
- **No se corrieron las 30 imágenes de nuevo** — decisión deliberada, ya justificada: la lógica de extracción no cambió respecto a M1 (que sí las validó completas), este bloque solo tocaba la resolución de runtime y la activación en `procesar_carpeta`.
- **Nota de rendimiento para quien lea las métricas de una primera corrida en una máquina nueva:** el primer uso de un runtime recién creado es notablemente más lento (antivirus escaneando binarios nuevos, cachés fríos) — no lo tomes como el rendimiento real; una segunda corrida ya estabiliza.
- **Hallazgo fuera de alcance:** apareció un archivo no rastreado `resumen_procesamiento_desktop.py` en la raíz del repo, que yo no creé ni toqué — queda ahí, sin explicación, fuera de este commit. Alguien debería revisar de dónde salió.
- Suite: 482 → **501 tests**, todos verdes.
- **Siguiente decisión pendiente:** no hay un bloque M3 definido todavía. Con M1+M2, PaddleOCR queda como motor principal, portable, activo en el flujo real, con EasyOCR de fallback — el trabajo de integración de este frente queda esencialmente completo salvo lo que decidas priorizar después (p. ej. confirmar el camino CPU puro en una máquina sin GPU, que sigue pendiente desde M1).

---

## 2026-08-10 — Cierre Bloque M1: proveedor OCR + PaddleOCR integrado (APROBADO)

- **Rama:** `lector-mvp-guia-nueva`. Commit hecho y pusheado a `origin/lector-mvp-guia-nueva` (ver SHA en el mensaje de cierre de esa sesión).
- **Decisión de cierre: PaddleOCR queda aprobado como motor OCR principal de Atlas. EasyOCR queda como fallback temporal**, no eliminado — sigue siendo el proveedor si Paddle no está disponible, y sigue siendo el camino usado por defecto en el código cuando no se pasa `proveedor=` explícitamente.
- **Precisión importante para quien retome esto:** "integrado" significa que la infraestructura (`ProveedorOCR`, `EasyOCRProvider`, `PaddleOCRProvider`, selección GPU/CPU, `numero_guia` robusto, focal generalizado) está lista, testeada (482 tests) y validada con una corrida real de las 30 guías — **no** que `procesar_carpeta` (el punto de entrada real de la CLI/lote) ya construya y use un `PaddleOCRProvider` por defecto. `procesar_carpeta` todavía no recibe ni pasa ningún `proveedor` — sigue llamando a `procesar_archivo` solo con `lector_ocr` (EasyOCR). Conectar el proveedor Paddle al flujo de lote real (`procesar_carpeta`/CLI) sigue pendiente y no se hizo en M1.
- **numero_guia recuperado:** 2/30 → 29/30, reutilizando `decidir_bloques_ocr` (ya existía) conectado al proveedor activo.
- **`IMG-20250930-WA0047.jpg` (número de guía):** discrepancia editorial de ground truth pendiente (410627 documentado vs 410267 que la imagen realmente muestra, según la observación original del validador) — no cuenta como fallo de Atlas, no bloqueó el cierre.
- **PaddleOCR corre en proceso completamente aislado**, nunca en el entorno principal — sus ~55 dependencias no tocan `requirements.txt` ni el venv de producción.
- **Selección GPU/CPU automática**, sin GPU hardcodeada. GPU real confirmada en este PC (3.03 s/imagen). **Portabilidad CPU explícitamente diferida**: no se corrió otro benchmark completo de 30 imágenes en CPU en este cierre — se validará con una prueba corta en el PC de oficina en un momento posterior.
- **Riesgo principal pendiente, con nombre:** `PaddleOCRProvider` apunta hoy a una ruta fija de este equipo (`C:\Users\Jjjc0508\Desktop\Atlas\ocr_eval_gpu_env`), creada para el bloque de evaluación — no es arquitectura de despliegue definitiva.
- **`IMG-20260512-WA0027.jpg` queda `REVISAR`** por la guarda documental — su fecha sigue siendo incorrecta, la guarda no la corrige, solo evita que pase como dato confiable.
- Suite: 458 → **482 tests**, todos verdes.
- **Próximo bloque oficial: M2 — runtime Paddle reproducible/portable** (reemplazar la ruta fija del venv por algo que no dependa de este equipo específico). No iniciado todavía.

---

## 2026-08-10 — Cierre Bloque Fechas F2 (con gate de confianza)

- **Rama:** `lector-mvp-guia-nueva`.
- **F2 completado y auditado:** recuperación OCR focal de FECHA DE EMISIÓN (recorte + 4 variantes, mismo mecanismo que transporte), disparada solo cuando la lectura global devuelve "No encontrado". El consenso exige ≥2 variantes coincidentes **y** que todas ellas tengan confianza ≥ `CONFIANZA_MINIMA_FECHA_FOCAL = 0.70`; si no, se abstiene.
- **Por qué existe el gate de confianza:** la primera versión (solo conteo, sin confianza) recuperó `IMG-20250930-WA0047.jpg` correctamente, pero también produjo un valor **incorrecto** en `IMG-20250930-WA0046.jpg` (3 de 4 variantes coincidieron en el mismo dígito mal leído). Auditar la confianza real de EasyOCR mostró una separación clara: los votos del caso incorrecto tenían confianza mínima 0.47; los del caso correcto, 0.95. Con el gate de 0.70, `WA0046` ahora se abstiene correctamente en vez de arriesgar el valor.
- **⚠️ El umbral 0.70 está validado sobre una muestra real limitada** (7 imágenes con caja geométrica, de las cuales solo 2 llegaron a tener consenso por conteo). El margen observado es amplio, pero esto **no demuestra que 0.70 generalice** a otros documentos o lotes. Antes de tratarlo como calibración definitiva, hace falta más muestra.
- **Estado final de la muestra real de 30 guías (OCR ejecutado de nuevo, dos veces, sin reutilizar corpus anterior):** 14/30 → **15/30** exactas. 1 recuperación correcta (`WA0047`), **0 recuperaciones incorrectas, 0 degradaciones** de los 14 aciertos previos.
- De los 15 fallos restantes: 6 dispararon focal y se abstuvieron correctamente (sin caja clara o sin consenso suficiente), 9 nunca encontraron ancla geométrica para "FECHA DE EMISION" en esta corrida (imágenes con degradación severa o donde la etiqueta no se leyó en absoluto).
- **Próximo bloque oficial: NO es seguir afinando EasyOCR.** Es **OCR-EVAL** — benchmark controlado de motores OCR alternativos, usando las muestras reales ya existentes (`Atlas\datos_privados\muestra_fechas_30` y su ground truth), para decidir si el techo actual (15/30, con la mayoría de fallos por degradación de imagen o pérdida total del valor en el OCR de página completa) es un límite del motor OCR en uso, no del pipeline de extracción.

---

## 2026-08-10 — Cierre Bloque Fechas F1

- **Rama:** `lector-mvp-guia-nueva`.
- **F1 completado:** guarda de plausibilidad temporal por defecto (2015–2035) en `extraer_fecha`, aplicada solo cuando no se entrega `fecha_desde`/`fecha_hasta` explícito.
- **Estado de la muestra real de 30 guías:** 14/30 exactas. **16/30 siguen sin acierto exacto.** De esos 16, 3 ahora fallan de forma segura (`"No encontrado"` en vez de una fecha con año absurdo como `7029`, `7025` o `1024`); los otros 13 no cambiaron con este bloque.
- **Evidencia previa (diagnóstico del mismo bloque de trabajo, antes de F1):** sobre las 16 fallas originales, se buscó la fecha real exacta (en todo formato) en el texto OCR crudo completo de cada imagen. En **0 de 16** casos la fecha correcta estaba presente en el OCR — es decir, los 16 errores originales nacen antes del extractor, en el OCR/calidad de imagen, no en la lógica de selección o prioridad de `extraer_fecha`.
- **Próximo bloque oficial:** mejora de OCR focal/adaptativa específicamente sobre la región de FECHA DE EMISIÓN (no tocar `extraer_fecha`; el cuello de botella está antes, en la lectura). No se ha iniciado.

### Para retomar

- Ground truth y muestra real viven fuera del repo, en `C:\Users\Jjjc0508\Desktop\Atlas\datos_privados\` (`muestra_fechas_30\`, `ground_truth\validacion_atlas_30_guias_v1.xlsx`) — no están versionados por diseño (datos privados de clientes).
- Bitácora ejecutiva: `docs/BITACORA_EJECUTIVA.md`. Bitácora técnica: `docs/BITACORA_TECNICA_CRONOLOGICA.md`.
- Baseline de tests: `python -m pytest -q` → 441 passed.
