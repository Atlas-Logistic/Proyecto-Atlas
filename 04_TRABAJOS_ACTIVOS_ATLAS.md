# Trabajos activos Atlas

## Calidad de Publicación Operacional — Fase 1

- Estado: COMPLETADA — sin reserva activa.
- Rama: `feature-cobertura-origen-fase1` (continuación directa del Hotfix CSV).
- Causa raíz demostrada con guía real 464260 (y confirmada en otras guías del
  mismo lote real), tres defectos independientes de publicación, ninguno de
  OCR base ni de umbrales:
  1. El extractor lineal captura Cliente/Obra destino por regex sobre el
     párrafo OCR completo, sin límite de columna; cuando EasyOCR fusiona la
     fila de dos columnas en un bloque, la captura arrastra la etiqueta y el
     valor de la columna vecina ("SOLICITANTE ..." dentro de Cliente,
     "DIRECCION ..." dentro de Obra destino). El pipeline ya detectaba y
     corregía esta misma contaminación para Chofer mediante recuperación
     geométrica, pero no para Cliente/Destino.
  2. La etiqueta "CARRO" de patente rampla se reconoce solo con la letra "O";
     cuando EasyOCR la lee como "CARR0" (cero, confusión visual conocida), ni
     la ruta lineal ni la geométrica la reconocen, y el único candidato válido
     de 6 caracteres queda mal asignado al tracto.
  3. `_extraer_cantidad_geometrica` aceptaba cualquier número bajo la etiqueta
     CANTIDAD, incluyendo códigos de producto sin separador de miles cuando
     dos columnas quedan fusionadas en una sola celda OCR, publicando un
     código como si fuera cantidad.
- Corrección (alcance estrictamente acotado a lo autorizado, sin tocar OCR
  base, umbrales, Multicampo, Política, Orquestador, OpenRouteService ni
  lógica específica de una guía):
  1. `_valor_lineal_contaminado` generaliza la detección ya existente para
     Chofer; nuevas `_cliente_lineal_contaminado`/`_obra_destino_lineal_contaminado`
     (con sus tablas de etiquetas ajenas documentadas con evidencia real) se
     integran en `procesamiento_masivo.procesar_archivo` reutilizando la misma
     recuperación geométrica ya congelada, habilitando el reemplazo aunque el
     valor lineal no esté vacío (igual que ya ocurría con Chofer).
  2. Tolerancia determinista de un solo carácter ("O"→"0") en la etiqueta
     "CARR[O0]" en ambas rutas (lineal y geométrica) de extracción de
     patentes; en la ruta lineal se añadió además una exclusión posicional
     para que el mismo tramo de texto ya asignado al carro no vuelva a
     reclamarse como tracto genérico.
  3. `_extraer_cantidad_geometrica` exige el separador de miles documental
     (`\d{1,3}(?:[.]\d{3})+`); ante un número sin ese formato se abstiene en
     vez de publicar un código como cantidad.
- Validación real (guía 464260, reprocesamiento completo con catálogos
  privados reales, antes/después):
  - Cliente: `"SOLICITANTE SALCMON SACX SAX SRUOKON SACK"` →
    `"SRUOKON SACK"` (contaminación eliminada; la calidad del OCR de nombres
    propios queda fuera de alcance, tal como se acordó).
  - Obra destino: `"DIRECCION PAES1D EDO FAEL MOYTALVA 9770"` →
    `"SALCHON SACX SAY"` (misma razón).
  - Patente tracto: `"J54288"` (incorrecto, robado al carro) →
    `"No encontrado"` (abstención correcta; ya no publica el valor del carro).
  - Patente rampla: `"No encontrado"` → `"JF4288"` (recuperada por catálogo
    real de vehículos con distancia 1).
  - Cantidad: `"10002943"` (código de producto publicado como cantidad) →
    `"No encontrado"` (abstención correcta).
  - Chofer y demás campos: sin cambios (`"RodRiGo NAHUELNIR"`, `origen`
    `"AZA RENCA"`).
- Validación real adicional (mismo lote, guías 463774/463936/464145/464206;
  guía de control 463604): cero regresiones — 463604 conserva exactamente
  `patente_tracto="KX5439"`/`patente_rampla="JF6468"` (contiene "CARRO" con
  letra O, no "CARR0") y su Cliente/Destino ya correctos no se ven alterados.
- Validación: 1185/1185 Atlas (11 pruebas nuevas), `compileall` y
  `git diff --check` aprobados.
- Riesgo residual: la limpieza de contaminación expone el texto OCR crudo de
  esa columna, que puede seguir siendo ilegible por calidad de imagen (fuera
  de alcance: no se mejora OCR); ambos campos permanecen sujetos a
  `indicador_revision = REVISAR` cuando corresponde.
- Hallazgo adicional (diagnóstico, sin cambios de código): la pestaña
  "Revisión de destinos" de Atlas Desktop no contiene ni ha contenido, en el
  build actualmente instalado (`app.asar` commit `dbc7568`, versión 1.2.0,
  rama `feature-consolidacion-viajes-1` — el último despliegue de Desktop
  registrado en esta bitácora), ningún componente de mapa/GPS: es un flujo de
  revisión de decisiones sobre un archivo JSON ("bandeja") que el usuario debe
  seleccionar manualmente; mientras no se seleccione, muestra un estado vacío
  por diseño. No se identificó el commit exacto que haya retirado un mapa
  porque el repositorio fuente de `Atlas-Viajes-Desktop` no es accesible desde
  esta sesión y ninguna bitácora del proyecto documenta haber construido un
  mapa para esta pestaña. Detalle completo en el informe de este bloque.
- Próximo bloque recomendado: si se confirma que existió un mapa antes,
  revisar el historial de `Atlas-Viajes-Desktop` alrededor de
  `feature-consolidacion-viajes-1`; si no, generar y cargar manualmente la
  bandeja `revisiones_destinos.json` como paso operacional.

## Hotfix — Incompatibilidad de Esquema en CSV de Reprocesamiento

- Estado: CORREGIDO Y VALIDADO — sin reserva activa.
- Rama: `feature-cobertura-origen-fase1` (continuación directa de Destino).
- Causa raíz demostrada: `resumen_procesamiento_desktop.py::comando_reemplazar`
  mantenía su propia comparación `!=` estricta de encabezados, totalmente
  independiente de `_validar_csv_existente` (la migración aditiva oficial de
  `procesamiento_masivo.py`). Cuando los bloques de Origen y Destino nunca
  tocaron el CSV acumulado real de Desktop (`analisis_completo_guias.csv`,
  última escritura 2026-07-28, 1.177 filas, sin `peso`/`cantidad`/`origen`),
  cualquier reprocesamiento nuevo generaba un CSV con el esquema vigente
  (18 columnas) que nunca podía ser `==` al acumulado (21 columnas, con
  traza histórica) → `ValueError` antes de iniciar OCR. Reproducido
  literalmente con el archivo real.
- Corrección: `comando_reemplazar` ahora reutiliza `_validar_csv_existente`
  como única fuente de verdad — se eliminó la comparación paralela. Migra
  ambos CSV (acumulado y reprocesado) de forma atómica y determinista antes
  de fusionar, y fusiona por unión de columnas (sin perder la traza
  histórica ni inventar valores en las columnas nuevas). Las validaciones de
  seguridad (prefijo de 15 columnas, columnas desconocidas o duplicadas)
  se mantienen intactas porque son las mismas de `_validar_csv_existente`.
- Validación real: se migró el CSV acumulado real de producción
  (respaldado antes) — 1.177 filas antes y después, cero diferencias en las
  21 columnas originales, cero valores inventados en las 3 columnas nuevas.
  Se reprodujo el flujo completo de Desktop (`comando_existentes` → OCR real
  → `comando_reemplazar`) con 4 guías reales nunca antes procesadas contra
  una copia del acumulado sin migrar: el merge ya no falla, resultan
  1.177 + 4 = 1.181 filas, cero diferencias en las filas históricas.
- Validación: 1174/1174 Atlas (3 pruebas nuevas), `compileall` y
  `git diff --check` aprobados.
- Riesgo residual: no se pudo confirmar visualmente en la interfaz de
  Desktop porque el ejecutable instalado sigue bloqueado por Smart App
  Control (mismo bloqueo ya documentado en "Logistics UX 1.0", no
  relacionado con este fix); la validación se hizo exhaustivamente en la
  capa Python que Desktop invoca directamente (mismo `carpetaProyectoPython`
  configurado).
- Próximo bloque recomendado: resolver la firma/confianza del ejecutable de
  Desktop para poder validar visualmente en la interfaz.

## Calidad Documental de Destinos — Fase 1

- Estado: COMPLETADA — sin reserva activa.
- Rama: `feature-cobertura-origen-fase1` (continuación directa de Origen).
- Causa raíz demostrada con datos reales, tres defectos independientes en el
  pipeline de Destino (ninguno relacionado con umbrales ni OCR base):
  1. `_orquestar_destino_sombra` cargaba `destinos.json` (catálogo legado
     código→nombre de 6 registros, esquema distinto) en vez de
     `destinos_maestros.json` (47 registros, 3 `CONFIRMADO`, el mismo que usa
     `calcular_rutas_desktop.py`). Demostrado ejecutando el resolver real con
     el mismo input: `NO_RESUELTO` con el catálogo viejo, `CONFIRMADO` con el
     correcto.
  2. `extraer_datos` nunca capturaba los campos documentales `DIRECCION`/
     `COMUNA` (el OCR sí los lee, en la misma línea); el resolver de destino
     nunca los recibía, perdiendo su vía de confirmación más fuerte cuando
     "OBRA DESTINO" es solo el nombre del cliente, no una dirección.
  3. Ningún CLI de producción exponía `campos_controlados_autorizados`, así
     que aunque el resolver confirmara, la Política nunca publicaba Destino.
- Corrección: (1) apuntar el orquestador en sombra a `destinos_maestros.json`;
  (2) extraer `direccion`/`comuna` con el mismo patrón de línea ya usado para
  `obra destino` y pasarlos al resolver; (3) agregar
  `--autorizar-campos-controlados` a `analizar_guias_masivo.py`, plomeado al
  parámetro ya existente, sin tocar la Política. Durante la validación con
  datos reales se encontró y corrigió un cuarto defecto: cuando el resolver en
  sombra no confirmaba nada nuevo pero la publicación estaba autorizada, el
  valor de respaldo era el OCR anterior al enriquecimiento por código
  destinatario, pisando un destino ya correctamente vinculado (464110 real).
  Se corrigió para respaldar siempre con el valor ya enriquecido.
- Además, con evidencia documental real (guía 462429: RUT de PRODALAM SA
  coincide con el cliente confirmado; dirección con número exacto 1610 y
  calle casi idéntica salvo ruido OCR) se promovió a `CONFIRMADO` el destino
  ya existente "ALBERTO PEPPER 1610, RENCA" en el catálogo privado, siguiendo
  el mismo criterio documental ya usado para VISTA CLARA 2351.
- Validación real (9 guías reales, catálogos privados reales,
  `--autorizar-campos-controlados destino`): 462429 pasa de destino sin
  confirmar a `ALBERTO PEPPER 1610` confirmado; 464106 y 464110 conservan
  `VISTA CLARA 2351`; 464089, 464135 y 384674 conservan su texto OCR sin
  confirmar (sin destino catalogado equivalente); 464107, 464108 y 464109
  continúan sin destino por las mismas causas de calidad de imagen ya
  documentadas en el bloque de Origen.
- Impacto operativo real: la guía 462429 (PRODALAM SA) pasa de `PENDIENTE`
  ("origen no informado") a `CALCULADO`: **6,3 km, 11 min**, confirmado con
  una consulta real a OpenRouteService. Es el primer viaje real de esta fase
  que llega a Ruta Calculada gracias a Origen (sprint anterior) + Destino
  (este sprint) combinados.
- Validación: 1172/1172 Atlas (7 pruebas nuevas), `compileall` y
  `git diff --check` aprobados.
- Riesgo residual: solo 3/47 destinos del catálogo real están `CONFIRMADO`;
  42/47 ya tienen dirección y coordenadas pero permanecen `PENDIENTE` sin
  evidencia documental individual — no se promovieron sin esa evidencia. El
  flag de autorización no está conectado a Desktop; solo esta ejecución
  manual lo usó.
- Próximo bloque recomendado: revisar, guía por guía, los 42 destinos
  `PENDIENTE` restantes contra evidencia documental real, y decidir si
  Desktop debe exponer la autorización de Destino de forma controlada.

## Cobertura Operacional de Origen — Fase 1

- Estado: COMPLETADA — sin reserva activa.
- Rama: `feature-cobertura-origen-fase1`.
- Causa raíz demostrada con OCR real (9 guías reales, no simuladas): el
  catálogo privado vigente de plantas ya confirma `AZA RENCA` y `AZA COLINA`
  a la vez; `_resolver_origen_documental` comparaba contra el bloque OCR
  completo del encabezado, que siempre incluye el directorio fijo de
  sucursales (Antofagasta, Temuco, Talcahuano, Colina). Esa doble
  coincidencia anulaba el voto para documentos que en realidad sí traían
  evidencia legible de `AZA RENCA` (464089 y 462429 reales). Una segunda
  causa independiente: el recorte del encabezado usa porcentajes fijos que
  asumen orientación vertical; una foto apaisada sin EXIF útil (464108 real)
  cae sobre la tabla de cantidades y nunca llega a leer el encabezado.
- Corrección: (1) `_resolver_origen_documental` corta los tokens de cada
  lectura en la primera mención tolerante a ruido OCR de "SUCURSAL", antes
  de comparar contra el catálogo — sin ese texto, el comportamiento es
  idéntico al previo; (2) `leer_encabezado_origen_focal` acepta un giro
  opcional y `procesar_archivo` reintenta con 90/180/270 grados solo cuando
  la lectura a 0° no confirma origen, sin costo adicional en el caso típico.
  No se modificó el consenso de 2 lecturas, ningún umbral, ni Multicampo,
  Política, Orquestador, ORS, Desktop u OCR base.
- Validación real (reprocesamiento completo, catálogos privados reales, 9
  guías reales): cobertura de origen en la muestra 4/9→7/9. Recuperados
  464089 y 462429 (ambigüedad de catálogo) y 464108 (rotación); sin cambios
  en 464106, 464135, 464110 y 384674 (ya resolvían); 464107 y 464109
  permanecen correctamente en `No encontrado` por desenfoque severo y por
  una omisión de detección OCR de esa línea específica, ninguna corregible
  sin relajar el comportamiento conservador.
- Impacto en rutas: ninguno de los tres documentos recuperados tiene todavía
  un destino `CONFIRMADO`/`ACTIVO` en el catálogo privado vigente (solo 3 de
  47 destinos lo están hoy), por lo que sus viajes siguen `PENDIENTE`; el
  motivo verificado con `calcular_rutas_desktop.calcular_fila` cambia de
  "origen no informado" a "destino no confirmado en catálogo" / "destino no
  informado" — el origen deja de ser el bloqueador. Con una consulta real a
  OpenRouteService confirmé el mecanismo completo: origen ausente con VISTA
  CLARA 2351 confirmado → `PENDIENTE`; con `AZA RENCA` presente → `CALCULADO`,
  16,7 km, 25 min (mismo resultado ya validado para 464106). No se declara un
  número de viajes ni de kilómetros nuevos en Desktop porque ningún documento
  físicamente disponible combina origen recién recuperado con destino ya
  confirmado; ese acoplamiento depende de la calidad documental de Destino,
  un bloque aparte fuera del alcance autorizado en esta sesión.
- Validación: 1165/1165 Atlas (5 pruebas nuevas), `compileall` y
  `git diff --check` aprobados.
- Riesgo residual: 464107 (desenfoque) y 464109 (omisión de detección OCR de
  la línea del encabezado) permanecen sin origen; ningún fix conservador
  puede recuperarlos sin inventar evidencia. El reintento de rotación agrega
  hasta 3 lecturas focales adicionales, mas solo en documentos que ya
  fallaban a 0°.
- Próximo bloque recomendado: Calidad Documental de Destino sobre el
  universo real, para que los orígenes ya recuperados puedan además calcular
  ruta.

## Atlas Benchmark 2.0 — Validación Operacional Masiva del Motor Actual

- Estado: COMPLETADO — sin reserva activa y sin cambios funcionales.
- Corpus actual congelado: 127 imágenes reales únicas por SHA-256, reunidas
  desde muestra oficial, paquetes de validación y entradas Desktop. Se
  descartaron 16 copias byte a byte y no se incluyeron recortes, montajes ni
  capturas derivadas. SHA-256 agregado:
  `eba4594f2f2f4d87861b1720f3f5218840bf748d1d3d9ad641dffb96f5d4a47b`.
- Reprocesamiento completo: 127/127 desde cero con el motor actual, catálogos
  privados vigentes, cero omisiones, cero errores y ningún resultado histórico
  reutilizado.
- Cobertura actual: Cliente 55,91 %, Destino 70,87 %, Chofer 71,65 %,
  Transporte 70,87 %, tracto 55,12 %, rampla 14,96 %, Peso 22,83 %, Cantidad
  29,92 %, Material 22,83 % y Origen 40,94 %.
- Comparación descriptiva contra snapshot: Cliente -5,18 pp; Destino +4,85 pp;
  Chofer +11,24 pp; Transporte +8,85 pp; tracto +46,45 pp; rampla +12,24 pp;
  Peso +22,83 pp; Cantidad +29,92 pp; Material +0,40 pp; Origen +40,94 pp.
  Los universos no son pareados: 1.177 filas históricas frente a 127 originales
  recuperables actuales.
- Viajes: 90 documentos con transporte forman 86 viajes; 7 confirmados, 79 en
  revisión y 37 documentos sin transporte. Consolidación 62,02 % → 70,87 %.
- Rutas reales: 2/86 calculadas por OpenRouteService, ambas 16,7 km y 25 min;
  84 pendientes. Motivos: origen ausente 47, destino no confirmado 29, destino
  ausente 5, destino ambiguo 2 y origen sin coordenadas 1.
- Riesgo metodológico: `confirmado` significa valor presente en un documento
  cuyo indicador global no es `REVISAR`; no equivale a exactitud contra ground
  truth. El corpus actual no dispone de verdad humana completa por campo.
- Próximo bloque recomendado: Cobertura Operacional de Origen — Fase 1, por
  desbloquear potencialmente 47/86 rutas y afectar 75/127 documentos.

## Validación Operacional Masiva — Fase 1

- Estado: COMPLETADA — sin reserva activa y sin cambios funcionales.
- Universo: 1.177 guías reales, todas procesadas sin error, y 574 viajes
  consolidados. El snapshot operacional es del 28-07-2026; no se confunde
  presencia de datos con exactitud contra ground truth.
- Cobertura destacada: Cliente 61,09 %, Destino 66,02 %, Chofer 60,41 %,
  Transporte 62,02 %, tracto 8,67 %, rampla 2,72 %, Material 22,43 % y tipo de
  carga 6,71 %. Origen, Peso y Cantidad no existen en el esquema de este
  snapshot masivo, por lo que su cobertura publicada es 0 %.
- Consolidación: 730/1.177 documentos se asignan por transporte a 574 viajes;
  490 viajes quedan confirmados y 84 en revisión. La invariancia estructural
  conserva 730/730 documentos, pero no sustituye validación semántica humana.
- Kilómetros: 0/574 viajes del snapshot pueden medirse de extremo a extremo
  porque el campo Origen no fue publicado en ese corte histórico.
- Precisión: el corpus masivo no posee ground truth por campo y no autoriza una
  cifra de precisión. La referencia oficial independiente permanece en 48/49
  valores E2E (97,96 %), sin extrapolarla a las 1.177 guías.
- Próximo bloque recomendado: Reprocesamiento Operacional Controlado y Ground
  Truth Estratificado, comenzando por Origen/Transporte/Destino por su efecto
  directo sobre viajes y kilómetros.

## Reconstrucción Estructurada de Campos OCR — Fase 1

- Estado: COMPLETADA — sin reserva activa.
- Patrón: EasyOCR conserva etiqueta y valor en cajas distintas, pero la lectura
  por párrafos pierde su relación. En 464110 incluso divide la etiqueta en
  `COD` + `DESTINATARIO`.
- Se incorporó un reconstructor geométrico reutilizable para código Cliente,
  código Destinatario, número SAP y número Transporte. Exige proximidad,
  alineación, tipado, unicidad y ausencia de otra etiqueta intermedia; ante
  valores distintos se abstiene.
- El código Destinatario sólo publica cuando coincide exactamente con un único
  destino activo y confirmado del maestro. No se modificaron OCR, umbrales,
  Multicampo, Política, Orquestador, ORS ni Desktop UX.
- Casos reales: 464106, 463528 y 464110 recuperan código `0001004443` y publican
  `VISTA CLARA 2351`.
- Kilómetros: 464106 pasa de `PENDIENTE` a `CALCULADO`: AZA RENCA → VISTA CLARA
  2351, 16,7 km, 25 min, OpenRouteService; el formateador Desktop lo presenta
  como `Calculada`. 463528 conserva destino canónico y
  permanece pendiente exclusivamente por origen ausente.
- Validación: 1160/1160 Atlas, 49/49 Desktop, `compileall` y
  `git diff --check` aprobados.
- Próximo bloque recomendado: recuperación estructurada y conservadora del
  origen ausente de 463528, sin ampliar la lógica de rutas.

## Normalización Maestra de Destinos Operacionales — Fase 1

- Estado: MAESTRO COMPLETADO; PUBLICACIÓN DOCUMENTAL PENDIENTE — sin reserva activa.
- `VISTA CLARA 2351` queda confirmado para `TORRES OCARANZA LTDA`, código
  destinatario `0001004443`, comuna Cerrillos y Región Metropolitana.
- Coordenadas verificadas en la ficha cartográfica de la entidad: latitud
  `-33.524258`, longitud `-70.7149958`. ORS/Pelias devolvió sólo un centroide de
  calle sin número y ese resultado aproximado fue descartado.
- Reprocesamiento real: 464106 y 463528 conservan en publicación
  `IORRES OCARANZA LIDA/LTDA`. La etiqueta `COD DESTINATARIO` y el valor
  `0001004443` aparecen separados en el OCR, por lo que el enriquecimiento por
  código no enlaza el maestro.
- No se creó un alias con el nombre degradado del Cliente: TORRES OCARANZA tiene
  varios destinos y esa asociación produciría falsos positivos.
- Control de ruta con el destino canónico: AZA RENCA → VISTA CLARA 2351,
  `16,7 km`, `25 min`, OpenRouteService. Flujo real 464106 sigue pendiente por
  destino no publicado; 463528 también carece de origen publicado.
- Validación: 197 pruebas focalizadas y 1154/1154 de regresión completa;
  `compileall` y `git diff --check` aprobados.
- Próximo bloque recomendado: extracción estructurada conservadora del código
  destinatario cuando etiqueta y valor estén separados, sin alterar OCR ni
  umbrales.

## Resolución Canónica de Clientes y Destinos — Fase 1

- Estado: COMPLETADA CON ABSTENCIÓN CORRECTA DE DESTINO — sin reserva activa.
- 464089 permanece estable: `COMERCIAL A Y B LTDA`, confirmado por RUT focal
  `78.634.910-9` y catálogo único.
- 464106: cuatro lecturas focales producen consenso de `50.234.350-5`, válido
  por módulo 11. Se registró exclusivamente el alias documental específico
  `IORRSS OCARANZA` para `TORRES OCARANZA LTDA`; no se añadieron alias parciales
  ni se redujeron umbrales.
- Resultado 464106: Cliente `IORRSS OCARANZA` → `TORRES OCARANZA LTDA` desde el
  Resolver hasta CSV y reporte. Destino conserva `IORRES OCARANZA LIDA` y
  `REVISAR`.
- Caso equivalente 463528: la imagen documenta TORRES OCARANZA LTDA, RUT
  `50.234.350-5` y VISTA CLARA 2351; el reprocesamiento confirma correctamente
  el Cliente con el mecanismo existente.
- Destino VISTA CLARA no avanza: dos guías y el origen histórico indican 2351,
  pero una corrección manual previa fija 2401; el catálogo está `PENDIENTE` y
  no posee coordenadas. Se requiere confirmación documental/manual de la
  dirección correcta y coordenadas exactas antes de calcular rutas.
- Kilómetros: sin cambio; 464106 continúa `PENDIENTE` por “destino no confirmado
  en catálogo”.
- Validación: 1154/1154 Atlas, 49/49 Desktop, catálogo privado válido y cero
  conflictos de manifiesto.
- Próximo bloque recomendado: Calidad Documental de VISTA CLARA 2351/2401 y
  coordenadas, sin consultar Internet hasta autorización expresa.

## Auditoría del Pipeline de Publicación Operacional — Fase 1

- Estado: COMPLETADA CON PENDIENTES DOCUMENTALES — sin reserva activa.
- Guía real 464106: origen vacío → `AZA RENCA`; patentes incorrectas/ausentes
  → tracto `SB6486` y rampla `JF4288`; cantidad ausente → `15.253`; peso
  `15.253` permanece estable.
- Publicación verificada extremo a extremo: `procesamiento_masivo`, CSV,
  `viajes.csv`, JSON `evidencias_documentos`, backend Desktop y consolidado
  frontend conservan los mismos valores.
- Seguridad: patentes requieren rol explícito y coincidencia canónica única;
  origen exige consenso de dos relecturas y una planta activa confirmada;
  cualquier ambigüedad produce abstención.
- Pendientes: Cliente y Destino de 464106 continúan como evidencia OCR parcial;
  no se canonizan porque el RUT observado es inválido y la dirección documental
  2351 contradice el maestro 2401. ORS ya recibe el origen y se abstiene por
  destino no confirmado.
- Regresión: 1154/1154 Atlas y 49/49 Desktop; clientes COMERCIAL A Y B, EBEMA y
  TORRES OCARANZA confirman sólo con RUT válido y exacto; cero relajación de
  umbrales.
- Próximo bloque recomendado: recuperación focal estructurada del RUT de
  Cliente de TORRES OCARANZA, con consenso módulo 11 y sin alias genéricos.

## Hotfix crítico — Drag & Drop Electron 43

- Estado: CORREGIDO Y VALIDADO.
- Causa: desde Electron 32 `File.path` no está disponible; el commit `e15d294`
  actualizó Desktop de Electron 31.3.1 a 43.2.0 sin migrar esa API.
- Corrección: el renderer conserva `DataTransfer.files/items` y obtiene la ruta
  exclusivamente mediante `webUtils.getPathForFile` en el preload aislado.
- Instalación activa: JPEG, JPG y PNG entregan una ruta absoluta, extensión y
  MIME válidos; 42/42 pruebas Desktop aprobadas.
- Guía nueva `384674.jpg`: OCR ejecutado, 1 procesada, 0 omitidas, 0 errores,
  54,15 s. La guía `464089.jpeg` se detecta como duplicada y habilita el diálogo
  con Reutilizar, Reprocesar completamente y Cancelar.
- Integridad: sin cambios en OCR, Sistema Multicampo, Política, kilómetros ni UX.

## Logistics UX 1.0

- Estado: IMPLEMENTADO Y VALIDADO VISUALMENTE; despliegue bloqueado por política
  local de ejecución.
- Desktop presenta un resumen operativo de ruta, distancia destacada, tiempo,
  proveedor, estado y motivo explícito para resultados no calculados.
- Validación visual: guías 462429 (33,2 km/40 min), 464089 (pendiente), 464135
  (destino sin dirección) y 462474 (proveedor no disponible), sin desbordamiento.
- Pruebas: 39/39 Desktop y prueba visual Electron aprobadas.
- El `app.asar` activo contiene el commit `9b67abb7a2b3d6a9ecc98bdf2a644cbdb168eb43`,
  versión `1.2.0`, SHA-256
  `03f0bcddc1e8b3299f31cf973c1fea4266a2fa256706c9b070c1aaefcb5e3892`.
- Bloqueo puntual: Smart App Control impide iniciar el ejecutable no firmado;
  Code Integrity registró el evento 3077 para la política
  `{0283ac0f-fff1-49ae-ada1-8a933130cad6}`. No se modificó el flujo oficial.

## Despliegue controlado de Atlas Desktop

- Estado: COMPLETADO — sin reservas activas.
- Método oficial: `npm run deploy:dev` desde el repositorio Desktop limpio.
- El comando genera metadatos, construye, respalda la instalación activa,
  despliega y valida automáticamente ruta, SHA-256, commit y versión.
- Instalación validada: `C:\Users\corte\Desktop\Atlas Viajes`; versión `1.2.0`,
  commit `3bbd3b277fe1a37652c93d7c22cfbfe7da1e2ac7`, SHA-256 del `app.asar`
  `5e638fa7efa78202e9636b3ed198462d4b21feff397f75abc7ab63045afd418f`.
- Validación 464089: el reprocesamiento real ejecutó OCR, recuperó
  `LEANDRO IOLEDO` y Desktop publicó `LEANDRO TOLEDO` mediante la normalización
  ya existente. El paquete activo contiene el diálogo de duplicados y la opción
  `Reprocesar completamente`.
- Integridad: no se modificaron OCR, Sistema Multicampo, resolvers, catálogos ni
  reglas de negocio.

## Desktop UX — Reprocesamiento Inteligente

- Estado: COMPLETADO en rama `feature-desktop-reprocesamiento-inteligente`.
- Decisión explícita ante nombres ya existentes: reutilizar, reprocesar
  completamente o cancelar.
- Reutilizar conserva el CSV acumulado sin cambios; reprocesar usa una salida
  nueva con `--reprocesar` y reemplaza atómicamente solo las filas seleccionadas.
- Validación real 464089: reutilizar produjo 0 procesados/1 omitido y SHA-256
  idéntico; reprocesar produjo 1 procesado/0 omitidos y recuperó
  `LEANDRO IOLEDO` en la evidencia. Desktop publicó `LEANDRO TOLEDO` mediante
  la normalización de reporte ya existente.
- Integridad: sin cambios en OCR, recuperación geométrica,
  `procesamiento_masivo`, Sistema Multicampo, Política o resolvers.

## Kilómetros visibles en Atlas Desktop — Fase 1

- Estado: COMPLETADO — sin reservas activas.
- Implementación: `viajes.csv` y los catálogos confirmados de Plantas/Destinos
  alimentan el `CalculadorRutas` y el adaptador OpenRouteService ya existentes;
  Desktop consume el resultado mediante un IPC aislado.
- Publicación: distancia, tiempo estimado, estado, proveedor y motivo quedan
  visibles en el panel preparado por Atlas Desktop UX 1.0.
- Seguridad: solo calcula con origen y destino únicos, confirmados, activos,
  con dirección completa y coordenadas canónicas; cualquier ausencia o fallo
  produce `Pendiente` o `No disponible`, nunca métricas vacías o cero.
- Validación: 63/63 pruebas focales Python, 1144/1144 de regresión, 36/36
  pruebas Desktop, prueba visual Electron, build Windows y consulta ORS real
  entre extremos canónicos confirmados (`33,2 km`, `40 min`, `CALCULADA`).
- Integridad: no se modificaron OCR, Orquestador, Política de Activación,
  resolvers, reglas de negocio ni arquitectura multicampo.
- Próximo bloque recomendado: observabilidad operacional de rutas y medición de
  cobertura sobre viajes reales antes de autorizar caché o más proveedores.

## Atlas Desktop UX 1.0 — Fases 1 y 2

- Estado: COMPLETADO — sin reservas activas.
- Repositorio de implementación: `Atlas-Logistic/Atlas-Viajes-Desktop`, rama
  `feature-atlas-desktop-ux-1`.
- UX visible: estado por campo, origen, confianza disponible, corrección
  automática, resumen final, tiempo de procesamiento y porcentaje confirmado.
- Kilómetros: interfaz preparada con distancia, tiempo estimado y proveedor en
  estado explícito `No calculado`/`Pendiente`; no se incorporó cálculo de rutas.
- Integridad: no se modificaron OCR, Orquestador, Política de Activación,
  resolvers, catálogos, reglas de negocio, arquitectura ni infraestructura.
- Validación: 35/35 pruebas Desktop, prueba visual Electron, build Windows,
  `compileall` del motor y `git diff --check`.
- Próximo bloque recomendado: integración de cálculo de kilómetros mediante un
  proveedor encapsulado, manteniendo el placeholder y el contrato visual ya
  preparados.

## OCR Focal Estructurado de RUT de Cliente — Fase 1

- Estado: COMPLETADO — validado sobre corpus E2E oficial.
- Rama: `feature-ocr-focal-rut-cliente-fase1`.
- Alcance: relectura exclusiva de la fila RUT asociada a `SEÑOR(ES)`, cuatro
  variantes, consenso mínimo de dos observaciones, módulo 11 y abstención ante
  conflicto.
- E2E: `REVISAR` 4/12→2/12; 005 y 007 pasan a `OK`; precisión oficial 48/49
  (97,96 %), contradicciones 0 y falsos positivos 0, todos sin cambios.
- Tiempo: corrida oficial 439,647→385,779 s (variación global favorable no
  atribuible); los casos activados aumentan 21,413 s y 24,923 s.
- Riesgo residual: costo focal aproximado de 21–25 s por documento activado;
  002 y 010 permanecen fuera del alcance por causas diferentes.
- Próximo sprint recomendado: validación controlada de recuperación geométrica
  post-resolución para ATLAS-E2E-002.

## Análisis Profundo de los Casos REVISAR — Fase 1

- Estado: COMPLETADO — diagnóstico únicamente, sin correcciones.
- Rama: `analysis-casos-revisar-fase1`.
- Casos: 002 por regla conservadora post-recuperación; 005 y 007 por RUT de
  Cliente truncado sin DV; 010 por bloqueo compuesto de región OCR, evidencia
  de Chofer y catálogo.
- Resultado: Orquestador, Política, Destinos y Materiales no originan las
  revisiones; no se modificó ningún componente funcional.
- Próximo bloque recomendado: OCR focal estructurado de RUT de Cliente, con
  consenso y módulo 11; impacto esperado inmediato 2/4 revisiones.
- Evidencia: `docs/ANALISIS_CASOS_REVISAR_FASE1.md`.

## Activación Controlada de Materiales — Fase 1

- Estado: COMPLETADA — Sistema Multicampo oficialmente finalizado.
- Rama: `feature-activacion-controlada-materiales-fase1`.
- Configuración: `material` pasó de `SOMBRA` a `PRODUCTIVO_CONTROLADO`; Choferes,
  Clientes y Destinos conservaron sus estados anteriores.
- E2E oficial: 12/12 guías; 2/12 confirmaciones de Materiales, 10/12
  abstenciones, 2/2 aciertos evaluables (100 %), cero falsos positivos, cero
  contradicciones y 4/12 revisiones sin cambios.
- Control: sin autorización conserva OCR; con autorización publica GT-MAT-009
  y GT-MAT-010; rollback a `SOMBRA` probado únicamente por configuración.
- Riesgo residual: cobertura limitada por diez casos sin confirmación canónica;
  el estado controlado exige autorización explícita por ejecución.

## Aliases Controlados de Materiales — Fase 1

- Estado: COMPLETADA — candidato apto para activación controlada.
- Rama: `feature-aliases-controlados-materiales-fase1`.
- Catálogo: se incorporaron exclusivamente `OCR-MAT-002 → GT-MAT-009` y
  `OCR-MAT-003 → GT-MAT-010`; los 15 materiales canónicos permanecen intactos.
- E2E: Materiales pasó de 0/12 a 2/12 confirmaciones y de 12/12 a 10/12
  abstenciones; ambos aciertos fueron por alias exacto, con confianza 1,0 y
  cero contradicciones. Los otros diez casos no cambiaron.
- Calidad: precisión de Materiales 2/2 (100 %) y precisión final 48/49
  (97,96 %) sin disminución; revisiones estables en 4/12.
- Riesgo residual: cobertura limitada por ocho guías sin descripción material
  utilizable y dos variantes multilínea expresamente rechazadas.

## Validación Controlada de Variantes OCR de Materiales — Fase 1

- Estado: COMPLETADA — todavía sin crear alias.
- Rama: `feature-validacion-variantes-ocr-materiales-fase1`.
- Resultado: 4 variantes evaluadas; 2 aprobadas, 2 rechazadas y 0 pendientes.
- Aprobadas: observaciones monomaterial asociadas inequívocamente a
  `GT-MAT-009` y `GT-MAT-010`; frecuencia total 2.
- Rechazadas: dos observaciones multilínea que concatenan dos materiales.
- Impacto máximo esperado de futuros alias exactos: 2/12 confirmaciones de
  Materiales, sin modificar OCR ni resolver.
- Evidencia: `validaciones/validacion_variantes_ocr_materiales_fase1_2026-08-03.json`.

## Catálogo Canónico de Materiales — Fase 1

- Estado: CONSTRUIDO Y VALIDADO — no apto aún para activación controlada.
- Rama: `feature-catalogo-canonico-materiales-fase1`.
- Catálogo: 15 registros derivados 1:1 del Ground Truth aprobado; cero
  duplicados, alias o abreviaciones; todas las entradas poseen evidencia.
- E2E: Materiales permanece 0/12 `CONFIRMADO` y 12/12 `PROPUESTO`; precisión
  global 48/49 y revisiones 4/12 sin cambios; cero contradicciones.
- Diagnóstico: 8/12 guías no entregan descripción material al resolver y las
  cuatro variantes observables no alcanzan coincidencia canónica sin alias.
- Artefacto: `catalogos/materiales.json`, SHA-256
  `7f3f92fac153c02149a2449b6ef8ffc54d3d8a8f0b8435b25fd92a15b73af3cc`.

## Ground Truth de Materiales — Fase 1

- Estado: COMPLETADO — sin crear `materiales.json`.
- Rama: `feature-ground-truth-materiales-fase1`.
- Corpus: 12/12 guías reales con evidencia documental; 19/19 líneas
  confirmadas; 15 materiales únicos; cero pendientes e inferencias.
- OCR: cuatro variantes literales observadas; ninguna fue promovida a alias.
- Calidad: ALTA; cero duplicados inconsistentes y cobertura documental 100 %.
- Artefacto canónico:
  `validaciones/ground_truth_materiales_fase1_2026-08-03.json`.

## Calidad Documental de Destinos — Fase 1

- Estado: COMPLETADA — nueve ubicaciones respaldadas por guías oficiales.
- Rama: `feature-calidad-documental-destinos-fase1`.
- Crecimiento documental: 9 direcciones, 9 comunas y 9 regiones; registros
  priorizados completos 0/9→9/9; cero ubicaciones inferidas.
- E2E: confirmaciones de Destinos 1/12→11/12; abstenciones 11/12→1/12;
  confirmaciones globales 22→32; precisión 48/49 y revisiones 4/12 estables.
- Evidencia versionada sin datos personales:
  `catalogos/manifiesto_calidad_documental_destinos_fase1.json`.

## Cobertura y Calidad de Catálogos Multicampo — Fase 1

- Estado: COMPLETADA — datos privados preservados fuera de Git.
- Rama: `feature-cobertura-calidad-catalogos-multicampo-fase1`.
- Crecimiento: Clientes 18→22 y dos alias demostrados; Destinos 20→29;
  Materiales 0→0 por falta de identidad canónica en el ground truth.
- E2E: precisión global 46/49→48/49; confirmaciones 18→22;
  abstenciones 30→26; revisiones 7/12→4/12; cero contradicciones.
- Seguridad: `COMUNA` no se incorporó como alias; los Destinos sin ubicación
  permanecen incompletos y no se promueven artificialmente.
- Evidencia versionada sin datos personales:
  `catalogos/manifiesto_cobertura_multicampo_fase1.json`.

## Activación Controlada de Destinos — Fase 1

- Estado: IMPLEMENTADA Y VALIDADA — publicación solo con autorización explícita.
- Rama: `feature-activacion-controlada-destinos-fase1`.
- Configuración: Destinos `PRODUCTIVO_CONTROLADO`; Materiales `SOMBRA`;
  Choferes y Clientes conservan `PRODUCTIVO`.
- Rollback: cambiar exclusivamente Destinos a `SOMBRA` conserva el valor OCR,
  aun cuando la ejecución incluya una autorización controlada.
- Evidencia: 128/128 pruebas focalizadas, 1126/1126 de regresión completa y
  100 % de cobertura de líneas de la política.

## Política de Activación Multicampo — Fase 1

- Estado: IMPLEMENTADA Y VALIDADA — sin cambios productivos.
- Rama: `feature-politica-activacion-fase1`.
- Arquitectura: registro inmutable campo → estado operacional y decisión de
  publicación externa al Orquestador y a los resolvers.
- Configuración vigente: Choferes/Clientes `PRODUCTIVO`; Destinos
  `PRODUCTIVO_CONTROLADO`; Materiales `SOMBRA`.
- Seguridad: `PRODUCTIVO_CONTROLADO` exige autorización explícita; los
  registros incompletos, desconocidos o inválidos fallan cerrados.
- Evidencia: 11/11 pruebas específicas, 123/123 focalizadas, 1125/1125 de
  regresión completa y 100 % de cobertura de líneas de la política.

## Orquestador Multicampo — Fase 1

- Estado: AUDITADO Y APROBADO PARA INTEGRACIÓN — modo sombra, sin reemplazar el flujo existente.
- Rama: `feature-orquestador-multicampo-fase1`.
- Reserva Codex: LIBERADA; ningún archivo o módulo reservado.
- Restricciones: no modificar resolvers, políticas, snapshots, producción,
  Desktop, catálogos ni reglas de negocio.
- Implementación: `acfe3f19854043fa5c824a14e50a47618b7c3a35`;
  auditoría de cierre con 14/14 pruebas específicas, 92,3 % de cobertura del
  orquestador, 193/193 de los seis resolvers y 1102/1102 de regresión completa.
- Corrección de auditoría: los adaptadores que devuelven un resumen inválido
  o asociado a otro campo quedan aislados como fallo del campo.

## Resolución Inteligente de Destinos — Fase 1

- Estado: COMPLETADO EN MODO SOMBRA — listo para auditoría.
- Rama: `feature-resolucion-inteligente-destinos-fase1`.
- Integración: `procesamiento_masivo` compone una solicitud de Destinos usando
  exclusivamente las interfaces públicas del Orquestador congelado.
- Seguridad: conserva la salida OCR/productiva; registra estado, vía,
  confianza y contradicciones; un fallo del resolver queda aislado.
- Evidencia: 4/4 pruebas de integración, 54/54 específicas y de contrato,
  92,3 % de cobertura del resolver y 1106/1106 de regresión completa.

## Resolución Inteligente de Materiales — Fase 1

- Estado: COMPLETADO EN MODO SOMBRA — listo para auditoría.
- Rama: `feature-resolucion-inteligente-materiales-fase1`.
- Integración: `procesamiento_masivo` compone una solicitud de Materiales
  usando exclusivamente las interfaces públicas del Orquestador congelado.
- Seguridad: conserva descripción y tipo de carga productivos; registra
  estado, vía, confianza y contradicciones; un fallo queda aislado.
- Evidencia: 4/4 pruebas de integración, 36/36 específicas y de contrato,
  96,6 % de cobertura del resolver y 1110/1110 de regresión completa.

## Auditoría Integral del Sistema Multicampo

- Estado: COMPLETADA — requiere una decisión final de política de activación.
- Rama: `audit-sistema-multicampo-integral`.
- Resultado técnico: composición conjunta, contratos, inmutabilidad y
  aislamiento aprobados para Choferes, Clientes, Destinos y Materiales.
- Hallazgo: Destinos y Materiales son sombra pura, mientras Choferes y
  Clientes conservan publicación productiva preexistente en
  `procesamiento_masivo`; el estado de activación no es homogéneo.
- Evidencia: 3/3 pruebas integrales, 138/138 de núcleo y resolvers,
  1113/1113 de regresión completa; cobertura entre 81,6 % y 94,4 %.
- Pendiente: definir explícitamente si Choferes/Clientes vuelven a sombra o si
  se autoriza como política la activación gradual antes de certificar producción.

> Nota (Claude, 2026-08-01): este archivo es una copia local, dentro del
> repositorio, del archivo de coordinación entre herramientas. La copia
> canónica y compartida vive en Google Drive:
> `Contexto compartido Atlas/04_TRABAJOS_ACTIVOS_ATLAS.md`, junto con
> `01_BITACORA_CRONOLOGICA_ATLAS.md` y `02_REGLAS_DE_COORDINACION.md`.
> Mantener ambas sincronizadas manualmente hasta que se decida si esta
> copia local debe eliminarse o formalizarse.

## Bloque 1C.1 + 1D.1 — Motor multicampo

- Estado: COMPLETADO E INTEGRADO — ya en `main` (commit de merge `8f40e93`)
- Rama de trabajo: fix-motor-multicampo-1c1-1d1
- Rama de integración: main
- Fecha de cierre: 2026-07-31

### Resumen técnico
- La revisión independiente confirmó que la resolución de vehículo ya no confirma silenciosamente una patente genérica incompatible.
- La revisión independiente confirmó que la resolución de destino ya no confirma una compatibilidad cliente-destino incorrecta.
- El comportamiento correcto queda en REQUIERE_REVISION con contradicción cuando la evidencia es incompatible.

### Evidencia de cierre
- 4 pruebas adversariales aprobadas.
- 79 pruebas de regresión aprobadas.
- Sin regresiones funcionales detectadas en la superficie multicampo revisada.
- Revisión de seguridad independiente adicional (Claude, 2026-08-01): 1079/1079 pruebas de la suite completa, sin marcadores de conflicto ni problemas de compilación. Ver `handoffs/2026-08-01_claude_revision_seguridad_merge_main_lector_mvp.md` en Drive.

### Handoff
- Cierre técnico del bloque ejecutado sin modificar datos reales ni introducir nuevas funcionalidades.
- **Ya integrado en `main`** — no queda pendiente de integración.

## Bloque Lector Focal Adaptativo – Fase 1 (Relectura de campos numéricos)

- Estado: COMPLETADO E INTEGRADO — ya en `main` (commit `824c4ff`)
- Rama de trabajo: main (trabajado directo sobre main, sin rama aislada)
- Rama de integración: main
- Fecha de cierre: 2026-07-31

### Resumen técnico
- Se implementó la relectura focal controlada sobre recortes de transporte.
- La segunda lectura se evalúa antes de incorporarse como evidencia de consenso.
- Se descartan lecturas idénticas o degradadas, y solo se conservan conflictos relevantes o evidencia útil.
- No se modificó la política de decisión del consenso; se preserva la compatibilidad con extractor.py y procesamiento_masivo.py.

### Evidencia de cierre
- 244 pruebas aprobadas.
- 1 warning no bloqueante.
- Exit code 0.
- Revisión de seguridad independiente adicional (Claude, 2026-08-01): sin hallazgos en esta revisión más liviana; observación operativa (no bug): la relectura duplica las llamadas de OCR sobre el recorte de transporte — medir impacto real en procesamiento masivo, ya anotado abajo como seguimiento.

### Seguimientos no bloqueantes
- Evolucionar el evaluador de evidencia hacia comparaciones semánticas además de literales.
- Validar el lector focal adaptativo mediante pruebas E2E con imágenes reales.
- Medir el impacto en rendimiento sobre procesamiento masivo.

### Handoff
- Cierre técnico del bloque ejecutado sin modificar la política de consenso ni introducir cambios en el contrato del flujo.
- **Ya integrado en `main`** — no queda pendiente de integración.

## Resolución Inteligente de Choferes – Fase 1

- Estado: **EN CURSO — código todavía SIN COMMITEAR, con un defecto conocido pendiente de corregir antes de cerrar el bloque**
- Rama de trabajo: main (trabajado directo sobre main, sin rama aislada; cambios sin commitear en `atlas_core/procesamiento_masivo.py` y `tests/test_procesamiento_masivo.py`)
- Rama de integración: main (pendiente el commit)
- Fecha de cierre: **todavía no cerrado** (la fecha `2026-08-01` que decía antes esta sección era incorrecta — el trabajo se hizo el 2026-07-31 por la noche, hora de Chile, y sigue sin commitear)

### Resumen técnico
- Se conectó `resolver_chofer_rut` (Motor Multicampo) al flujo principal de `procesamiento_masivo.py`.
- La política pretende ser conservadora: confirma solo cuando la evidencia es fuerte, preserva el valor OCR cuando la evidencia es débil o contradictoria y marca revisión cuando no alcanza el umbral.

### ⚠️ Defecto real encontrado en revisión de seguridad (Claude, 2026-08-01) — corregir antes de cerrar
La lógica de `requiere_revision` fuerza revisión manual **incluso cuando el chofer se confirma correctamente** (`EstadoResolucion.CONFIRMADO`), si el nombre canónico coincide textualmente con el OCR — que es el caso común de un OCR limpio. Reproducido con `resolver_chofer_rut` real (no simulado): un caso `CONFIRMADO` con nombre y RUT exactos queda igual marcado para revisión que uno donde el chofer no se pudo identificar. Esto contradice el objetivo declarado ("ya no depende del fuzzy matcher... confirma solo cuando la evidencia es fuerte"). Detalle completo y reproducción exacta:
`handoffs/2026-08-01_claude_revision_seguridad_merge_main_lector_mvp.md` (Drive, carpeta "Contexto compartido Atlas").

### Evidencia de cierre (parcial — pendiente corregir el defecto de arriba antes de considerar esto cerrado)
- 130 pruebas aprobadas (no cubren el caso del defecto encontrado).
- 1 warning no bloqueante.
- Exit code 0.

### Seguimientos no bloqueantes
- Añadir contexto adicional de cliente, destino y vehículo para mejorar la resolución cuando el RUT es débil o ausente.
- Registrar historial de evidencia de resolución para auditoría y aprendizaje.
- Reducir los casos que terminan en REVISAR sin incrementar falsos positivos.

### Handoff
- **No commitear como "cerrado" hasta corregir el defecto de `requiere_revision` descrito arriba.**
- Una vez corregido, commitear los cambios de `procesamiento_masivo.py`/`test_procesamiento_masivo.py` antes de considerar el bloque integrado.

## Resolución Inteligente de Clientes – Fase 1

- Estado: COMPLETADO E INTEGRADO — listo para publicación en `main`
- Rama de trabajo: main
- Rama de integración: main
- Fecha de cierre: 2026-08-01

### Resumen técnico
- `resolucion_cliente.py` quedó como único punto de decisión para identidad de cliente dentro del flujo principal.
- `procesamiento_masivo.py` ahora propaga `REVISAR` para cualquier estado no confirmado del contrato multicampo.
- `enriquecer_datos_con_catalogos` dejó definitivamente de resolver identidad de cliente y quedó limitado a campos auxiliares.
- Se eliminaron restos de la ruta migrada y se amplió la cobertura de integración para contradicción, ambigüedad, propuesta y no resuelto.

### Evidencia de cierre
- 164 pruebas aprobadas.
- 1 warning no bloqueante.
- Exit code 0.
- Segunda auditoría independiente aprobada: el bloque puede pasar a cierre técnico, integración y publicación.

### Seguimientos no bloqueantes
- `extractor.py` mantiene fallbacks históricos por número de guía que precargan cliente y RUT. No constituyen una segunda ruta de decisión, pero deberán revisarse en futuras fases de unificación.

### Handoff
- No abrir todavía el bloque de Destinos hasta confirmar que Clientes quedó completamente integrado y publicado en `origin/main`.

## Consolidación Inteligente de Viajes — Fase 1

- Estado: COMPLETADO.
- Desktop: commit `5acbed0`, rama `feature-consolidacion-viajes-1`.
- Resultado: el número de transporte identifica visualmente un único viaje; se muestran cantidad y listado de guías, totales disponibles y detalle documental por guía.
- Validación: 46/46 pruebas Desktop, prueba visual Electron y viajes históricos de 2, 3 y 5 documentos.
- Integridad: no se modificaron OCR, Sistema Multicampo, Política, resolvers, OpenRouteService ni reglas documentales.
- Despliegue activo: versión 1.2.0, commit `5acbed0e08e2a0547104c30c62b85fe0e5026e4e`, `app.asar` SHA-256 `17ce3bb5e4cd257411fba7bcc817ee50016cc0602580e2995969c1428d3557e8`.

## UX Operacional Atlas — Fase 1

- Estado: COMPLETADO.
- Desktop: implementación `ccdbd7a`, matriz visual `dbc7568`.
- Resultado: resumen principal reducido a fecha, guías, cliente, chofer, material y estado; detalle ordenado como observaciones, viaje consolidado, logística, inteligencia y datos auxiliares.
- Validación: 49/49 pruebas Desktop y matriz visual de viaje simple, multiguía, confirmado y en revisión.
- Integridad: cambio exclusivamente presentacional; motor, OCR, Multicampo, Política, resolvers, catálogos, ORS y procesamiento masivo permanecen intactos.
- Despliegue activo: versión 1.2.0, commit `dbc75685bf433beb365f339902f2c89eb45a5dad`, `app.asar` SHA-256 `5bfdfbcf6d7f6bb443340069f2042455ebbca487a39931530ef2778504535891`.

## Calidad de Datos Operacionales — Fase 1

- Estado: COMPLETADO CON PENDIENTES AISLADOS.
- Mejoras: Cliente canónico y peso documental publicados extremo a extremo.
- Caso real: guía 464089 pasa de `COMERCIAL` a `COMERCIAL A Y B LTDA` mediante RUT focal `78.634.910-9`, consenso, módulo 11 y prefijo canónico único; peso `14.947,000` preservado en CSV y reporte.
- Seguridad: `COMERCIAL` no fue agregado como alias; prefijos ambiguos continúan en `REQUIERE_REVISION`; las 15 columnas oficiales permanecen congeladas y `peso` es evidencia adicional compatible.
- Validación: 168 focalizadas, 1148/1148 regresión Atlas y 49/49 Desktop.
- Pendientes: Destinos parciales; patentes 464106 (`SB6486`/`JF4288`); cantidad independiente; materiales OCR no canónicos; origen vacío antes del cálculo de kilómetros.
## Hotfix regresión Chofer — guía 464089

- Estado: COMPLETADO en la rama de hotfix.
- Rama: `hotfix-regresion-chofer-464089`.
- Fecha: 2026-08-04.
- Alcance: restaurar la publicación de la recuperación geométrica conservadora
  cuando la extracción lineal entrega `No encontrado`.
- Validación: 120/120 pruebas de `procesamiento_masivo` aprobadas; la guía 464089
  recupera el Chofer y los casos conservadores permanecen en `REVISAR`.
- Integridad: sin cambios en OCR, recuperador geométrico, resolvers, Desktop,
  Política de Activación, Sistema Multicampo ni catálogos.
