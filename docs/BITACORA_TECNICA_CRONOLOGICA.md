# Bitácora Técnica Cronológica — Proyecto Atlas

Registro técnico, en orden cronológico, de cambios de código sobre el lector de guías. Un bloque por entrada, con archivos modificados, decisión de diseño y validación.

---

> **Actualización posterior:** este registro describe el trabajo del PC de oficina. El cierre reconstruido y publicado al final del archivo fija el estado vigente.

## 2026-08-13 — Registro provisional: INFRAESTRUCTURA S2.2 (trabajo local del PC de oficina)

**Rama motor:** `lector-mvp-guia-nueva` · **Baseline:** posterior a INFRAESTRUCTURA S2.1 (`2046f08`).

### Fase A -- localizar el repo Desktop real

Búsqueda exhaustiva en el PC de oficina (`package.json`/`atlas_viajes.html`/`consolidacion_viaje.js`/historial Git) encontró `C:\Users\corte\Desktop\MBT\Proyecto\_build-atlas-desktop-1.2.0-oficina\` -- clon con `origin` real (`https://github.com/Atlas-Logistic/Atlas-Viajes-Desktop.git`), HEAD detached en `ef6dfb0`. `git fetch --all` reveló 18 ramas remotas / 31 commits totales. El commit buscado (`96229813fcae41c5e1ea22ac139c703c616c976a`, MATERIAL/PESO/OBRA DESTINO multiguía) **no existe en ninguna rama fetcheada** ni en la copia histórica de Drive; lo más cercano es `src/consolidacion_viaje.js` en la rama `feature-consolidacion-viajes-1` (no fusionada aquí -- fuera de alcance).

La copia que S2.1 había movido a `historico_pre_infra_s2\componentes_no_portables\Atlas-Viajes-Desktop-Restaurado\` resultó tener el mismo linaje real (comparte el commit `139d41f` byte a byte con `origin/fix-desktop-data-root-drag-drop`) más 3 commits locales nunca publicados (`0ec8a3b`, `50b4323`, `b247432`) -- confirmado con `git merge-base --is-ancestor` (fast-forward limpio, sin reescritura). Se creó una copia de trabajo nueva (`Desktop\MBT\Proyecto\Atlas-Viajes-Desktop\`, clon limpio de `origin` + los 3 commits traídos como remoto temporal, luego removido) en vez de desarrollar dentro de Drive o reutilizar el clon viejo desactualizado.

### Fase C/D -- auditoría y contrato portable

`main.js` resolvía `carpetaReportes`/`carpetaProyectoPython`/`carpetaCatalogos` desde `electron-store` (`config_usuario`), poblado por migración desde un `config.json` legado -- mecanismo de almacenamiento ya correcto (sobrevive reinstalaciones), pero los *valores* migrados venían de un PC específico (`C:\Users\Jjjc0508\...`). `carpetaProyectoPython` se dejó deliberadamente fuera de cualquier derivación portable: apunta al repo de código, y S2.1 ya decidió "código = Git, no Drive" -- forzarla a derivar de `ATLAS_DATA_DIR` violaría esa decisión.

`src/atlas_data_dir.js` (nuevo): mismo contrato que `atlas_core/almacenamiento_portable.py` (override > `ATLAS_DATA_DIR` > configuración local mínima > autodetección de Drive > `null`), con un nivel extra (configuración local) inexistente del lado Python -- necesario porque Electron lanzado desde un acceso directo/instalador puede no heredar variables de entorno definidas después del inicio de sesión de Windows.

### Fase F/G -- manifiesto de operación vigente, contrato compartido

El motor (tras S2.1) no tenía ningún mecanismo de "operación vigente" -- solo carpetas. Se definió `operacion/actual/estado_operacion.json` (schema_version 1: `reporte_vigente`, `dataset_operacional` opcional, `fecha_actualizacion`, `origen`), documentado idénticamente en `docs/CONTRATO_ESTADO_OPERACION_PORTABLE.md` (motor) y `documentacion/CONTRATO_ESTADO_OPERACION_PORTABLE.md` (Desktop).

Lado motor: `atlas_core/almacenamiento_portable.py` gana `escribir_estado_operacion`/`leer_estado_operacion` (mismo patrón de escritura atómica). Cualquier ruta relativa que resuelva fuera de la raíz invalida todo el manifiesto (`_ruta_relativa_segura`, usa `Path.relative_to`). Wireado en `generar_reporte_viajes.py` como paso *best-effort* tras generar el reporte: si `--salida`/el CSV no viven dentro de `ATLAS_DATA_DIR`, no se publica nada -- comportamiento idéntico al de antes de S2.2 (verificado con test dedicado).

Lado Desktop: `src/estado_operacion.js` (`leerEstadoOperacion`) -- ausencia de manifiesto es `SIN_OPERACION_ACTIVA` (caso válido, no error); JSON corrupto es `MANIFIESTO_INVALIDO`; `schema_version` no reconocida es `SCHEMA_NO_SOPORTADO`; campo `reporte_vigente` ausente es `MANIFIESTO_INCOMPLETO`; cualquier ruta (relativa) que resuelva fuera de la raíz es `RUTA_FUERA_DE_RAIZ`. Nunca hace `readdir`/glob -- solo lee ese archivo exacto, por lo que estructuralmente no puede "caer" a `historico_pre_infra_s2\`.

`main.js`: `atlas:cargar-automatico` ahora prefiere `estadoOperacion.reporteVigente` sobre `configuracion.carpetaReportes`, cayendo al valor legacy solo si no hay manifiesto -- superset estricto del comportamiento anterior (si no hay manifiesto, se comporta exactamente igual que antes). Dos IPC nuevos, aditivos: `atlas:estado-operacion-vigente` (para un futuro panel de estado) y `atlas:configurar-raiz-atlas` (para una futura pantalla de configuración de la raíz local mínima -- la lectura/escritura ya existen, la UI queda pendiente, deliberadamente fuera de alcance de este bloque).

### Fase H -- migración de config_usuario legacy

`migrarHaciaRaizPortableSiCorresponde` (nuevo en `src/configuracion_usuario.js`): un valor de `carpetaCatalogos`/`carpetaReportes` se trata como legacy si no existe como carpeta real en este PC, o si existe pero no vive dentro de la raíz portable resuelta (comparación por límite de carpeta real, con separador de por medio -- **bug encontrado y corregido durante la implementación**: una comparación por prefijo de texto simple hacía que `G:\Atlas2\...` contara como "dentro de" `G:\Atlas`, falso positivo real corregido con un test dedicado). Se respalda bajo una clave con timestamp antes de reemplazar -- nunca se pierde el valor original. Idempotente (`_migradoHaciaRaizPortable`). `carpetaProyectoPython` explícitamente excluida (ver Fase C).

### Bloqueo real de verificación (Desktop)

Este entorno de ejecución no tiene Node.js instalable: sin `node.exe` en PATH ni en ubicaciones conocidas (`Program Files`, `AppData\Local\Programs`, `nvm`, Chocolatey), y `node_modules/electron/dist` nunca se descargó en ningún clon local encontrado (instalación de dependencias hecha originalmente sin acceso a la descarga del binario de Electron). No se pudo ejecutar `npm test` (110 tests previos reportados + 16 nuevos) ni abrir Electron para validación visual. El código se revisó manualmente con cuidado -- mismo patrón exacto de funciones puras que ya usa el resto del repo, balance de llaves/paréntesis verificado sin diferencia neta introducida (`git show HEAD:main.js` vs versión editada: +36 `(` / +36 `)`) -- y se comiteó localmente (`4b94a38` sobre `fix-desktop-data-root-drag-drop`), **sin publicar**. Ver `coordinacion\PENDIENTE_PC_CASA.md` en Drive para el paso exacto pendiente (`npm test` + `git push` desde un PC con Node).

### Validación (motor)

Suite completa: 916 → **927 tests** (11 nuevos: `tests/test_generar_reporte_viajes_cli.py`, 8 nuevos en `tests/test_almacenamiento_portable.py`), sin regresiones.

---

## 2026-08-13 — Cierre: INFRAESTRUCTURA S2 / S2.1 (raíz portable de Drive, caché ORS, saneamiento de la carpeta Drive existente)

**Rama:** `lector-mvp-guia-nueva` · **Baseline:** posterior a INTELIGENCIA N1 (`ed52afb`).

### Decisión de arquitectura

Código = GitHub. Estado operativo portable (catálogos privados, cachés, reportes, respaldos, coordinación) = una única raíz `Atlas\` sincronizada por Drive. Secretos = variables de entorno locales, nunca Drive ni Git. Un solo módulo (`atlas_core/almacenamiento_portable.py`) concentra CÓMO se resuelve esa raíz -- nada más en el repo construye la ruta a mano.

### Fase 0 (S2.1) -- auditoría de la carpeta `Atlas` ya existente en Drive, antes de tocar nada

`G:\Mi unidad\Atlas` (Google Drive for Desktop, detectado vía `HKCU:\Software\Google\DriveFS`) ya existía, pero no era una raíz limpia: resultado de una sesión de incidente del 2026-08-10/11 (rollback/reinstalación de Atlas Desktop 1.4.2→1.4.4, evaluación comparativa PaddleOCR/EasyOCR con GPU). Contenía: dos copias completas de repos Git (`Proyecto-Atlas`, HEAD `129b459` -- ancestro confirmado del HEAD actual, no una rama divergente; `Atlas-Viajes-Desktop-Restaurado`, **sin remoto Git configurado**); dos venvs de Python (`ocr_eval_env`, `ocr_eval_gpu_env` -- este último con PaddlePaddle-GPU 3.3.1 + CUDA 11.8 completo); y cuatro copias no reconciliadas de `analisis_completo_guias.csv` (tres idénticas de 1.178 filas/410.100 bytes fechadas 2026-08-08, una de 15 filas/3.342 bytes fechada 2026-08-11). `REPORTE_RESTAURACION.md` dentro de `datos_privados\` confirmó que ese material vino del PC de casa (usuario Windows `Jjjc0508`).

**Decisión de negocio aplicada, no derivada por heurística:** el histórico de 1.178 filas no se promueve a operación vigente. Se preservó sin borrar nada, moviendo (operación de metadatos de Drive, prácticamente instantánea -- no hay recarga de bytes en un `move` dentro del mismo volumen) todo lo no-portable a `historico_pre_infra_s2\` (snapshots, `ocr_eval`, `IMAGENES`, `backups_config`) y `historico_pre_infra_s2\componentes_no_portables\` (los dos repos Git, los dos venvs), cada uno con su propio `README_HISTORICO.md`/`NO_USAR_COMO_CODIGO_CANONICO.md`.

### Fase 1 -- `atlas_core/almacenamiento_portable.py` (nuevo)

`resolver_raiz_atlas(override=None)`: prioridad `override` explícito → `ATLAS_DATA_DIR` → `autodetectar_raiz_drive()` (solo lectura: prueba `<letra>:\{Mi unidad,My Drive}\Atlas` en D:-Z: y `%USERPROFILE%\Google Drive\Atlas`; nunca crea nada, devuelve `None` si no hay evidencia real) → fallback local `Path(".atlas_local")` (cwd-relativo, gitignored, uso de desarrollo/tests). Expone helpers de subcarpeta (`ruta_operacion`, `ruta_catalogos_privados`, `ruta_cache`, `ruta_reportes`, `ruta_respaldos`, `ruta_datos_privados`, `ruta_coordinacion`) que todos aceptan `raiz=` explícito para tests. También centraliza `escribir_json_atomico` (mismo patrón tempfile+`os.replace` que ya usaban `RepositorioRutas`/`RepositorioTelemetria`) y `bloqueo_sesion` (lock de archivo simple con expiración por antigüedad para locks huérfanos, `SesionOcupadaError` si otra sesión activa sostiene el mismo nombre).

**Aislamiento de tests (`tests/conftest.py`, nuevo):** fixture `autouse` que hace `delenv("ATLAS_DATA_DIR")` y fuerza `autodetectar_raiz_drive` a devolver `None` en cada test -- sin esto, configurar `ATLAS_DATA_DIR` de forma persistente en una máquina de desarrollo (como se hizo en este mismo bloque) rompería silenciosamente `test_fuente_inexistente_incompleta_e_invalida` y cualquier otro test que dependa de que no exista fuente de catálogos por defecto.

### Fase 2 -- `atlas_core/fuente_catalogos.py`

Nueva tercera capa de fallback en `resolver_fuente_catalogos`: si no hay `ruta`/`ATLAS_CATALOGOS_DIR` explícitos ni `catalogos/` local completo, se prueba `ruta_catalogos_privados()` (misma verificación "los 7 archivos requeridos están presentes" que ya se usaba para el fallback local) antes de lanzar `ErrorFuenteCatalogos`. Retrocompatible: si esa carpeta no existe o está incompleta, el comportamiento (y el mensaje de error) es idéntico al de antes de este bloque.

### Fase 3 -- `atlas_core/rutas/cache_geocodificacion.py` (nuevo)

Gap real encontrado: `RepositorioRutas`/`ServicioRutas` ya cacheaban la ruta calculada final (clave lógica planta/destino/perfil/proveedor), pero `ServicioRutas.preparar()` llamaba `proveedor.geocodificar()` en cada ejecución, sin ninguna caché -- exactamente la llamada que Onelogis ya no repetía y ORS sí. `RepositorioCacheGeocodificacion` (JSON, escritura atómica, protegida por `bloqueo_sesion`, ubicación predeterminada `<raíz>\cache\geocodificacion\geocodificacion_cache.json`) cachea por `proveedor.nombre|proveedor.version|dirección_normalizada` (mismo normalizador NFKD-mayúsculas-solo-alfanumérico que `huella_direccion` en `atlas_core/rutas/servicio.py`). `ProveedorRutasConCacheGeocodificacion` (decorador `@dataclass(eq=False)` -- deliberado, para conservar igualdad/hash por identidad y no romper código que guarda instancias de proveedor en un `set`) envuelve cualquier `ProveedorRutas`: cachea `geocodificar()`, delega `calcular_ruta()` sin cambios. Solo se cachean estados estables (`REQUIERE_REVISION`, `RESULTADO_AMBIGUO`, `DIRECCION_NO_ENCONTRADA`) -- fallos transitorios (`SIN_CONEXION`, `LIMITE_CUOTA`, `SIN_CREDENCIAL`) nunca quedan "pegados" en caché.

Wireado en `atlas_core/procesamiento_masivo.py` en los dos puntos donde se construye `OpenRouteService(pais=pais_operacion)` por defecto (`resolver_entrega_documento` en modo un-solo-archivo, y el proveedor compartido de todo un lote) -- ningún test existente ejercía esa rama por defecto (todos inyectan `proveedor_rutas` explícito), así que el cambio no tocó ningún comportamiento cubierto por la suite previa.

**Bug encontrado y corregido durante la implementación:** `ProveedorRutasConCacheGeocodificacion` como `@dataclass` normal generaba `__eq__`/`__hash__` por valor, lo que lo volvía no-hasheable (dataclass con `eq=True` por defecto y sin `frozen=True` pone `__hash__ = None`) -- rompía `test_integracion_catalogos_desktop.py::test_catalogos_y_proveedor_compartido_se_propagan_juntos`, que mete instancias de proveedor en un `set` para verificar que el lote reutiliza la misma instancia. Corregido con `@dataclass(eq=False)`.

### Fase 4 -- migración real en PC de oficina (sin gastar llamadas externas)

Catálogo vivo real encontrado en `C:\Users\corte\AppData\Local\Atlas\datos\catalogos_privados\` (8 archivos, base 2026-07-30, con manifiesto SHA-256 propio ya diseñado con política "versión completa inmutable; activación solo con hashes coincidentes"). Copiado (no movido -- Desktop sigue leyendo del original hasta que se adapte) a `G:\Mi unidad\Atlas\catalogos_privados\`; verificado con `sha256sum` contra las 8 hashes del manifiesto -- coincidencia exacta. `ATLAS_DATA_DIR` configurado a nivel de usuario Windows (`SetEnvironmentVariable(..., "User")`) apuntando a `G:\Mi unidad\Atlas`.

Prueba E2E de bajo costo, sin llamadas externas: `validar_fuente_catalogos()` con `ATLAS_DATA_DIR` real → `CATALOGOS_VALIDOS`, conteos idénticos al manifiesto. Cache hit de geocodificación demostrado con un `ProveedorRutasSimulado` instrumentado contra la ruta real de caché en Drive (`interno.llamadas_geocodificacion == 1` tras dos consultas idénticas); archivo de demostración borrado después de la prueba para no dejar datos sintéticos en la caché real.

### Deliberadamente fuera de alcance

Adaptar `main.js`/`config_usuario.json` de Atlas Desktop (hoy hardcodea `C:\Users\Jjjc0508\...`): la única copia de ese código disponible (`historico_pre_infra_s2\componentes_no_portables\Atlas-Viajes-Desktop-Restaurado\`) no tiene remoto Git -- editarla dentro de Drive habría violado el propio principio "código = Git" de este bloque. Documentado como pendiente en `coordinacion\PENDIENTE_PC_CASA.md`.

### Validación

Suite completa: 892 → **916 tests** (24 nuevos: `tests/test_almacenamiento_portable.py`, `tests/test_cache_geocodificacion.py`, 3 nuevos en `tests/test_fuente_catalogos.py`), sin regresiones -- corrida completa en verde después del fix de hasheabilidad.

---

## 2026-08-12 — Cierre: INTELIGENCIA N1 (normalización semántica controlada de territorios y entidades)

**Rama:** `lector-mvp-guia-nueva` · **Baseline:** posterior a PATENTES P4 (`88645b3`).

### Principio de diseño

`VALOR OCR` ≠ `VALOR NORMALIZADO` ≠ `VALOR CANÓNICO CORROBORADO`. Un valor OCR se normaliza SOLO contra un universo/vocabulario cerrado, con candidato único y margen; se corrobora SOLO contra RUT/código/catálogo real. Ninguna corrección es un reemplazo aislado por caso -- todas viven en funciones generales (`normalizar_comuna`, `normalizar_nombre_societario`, `resolver_nombre_empresa_difuso`) sin ninguna guía/valor hardcodeado.

### Fase A -- auditoría real (19 guías, sin reproceso masivo)

Volcado completo de `cliente`/`obra_destino`/`chofer`/`rut_chofer`/`motivos_revision_documento` de las 19 filas del CSV operacional. Hallazgos que definieron el alcance real del bloque (no los del enunciado original, encontrados investigando):

1. **464698/464699** (imágenes reales inspeccionadas): SEÑOR(ES) impreso "EBEMA SA" -- PaddleOCR lo lee "EDMA SA" y "KBEMA SA" en cada guía. R.U.T. impreso "83.585.400-0" (= `835854000`, existe exacto en `empresas.json` como EBEMA SA) -- pero `_extraer_rut_cliente_geometrico` nunca lo encontraba.
2. **Causa raíz del punto 1 (bug real):** la etiqueta SEÑOR(ES) termina en y=479, R.U.T. empieza en y=476 (gap **-3px**, filas de un formulario apretado que se solapan levemente) -- el filtro geométrico exigía `0 <= gap`, rechazando la etiqueta R.U.T. válida por un margen de 3px.
3. **OBRA DESTINO** impreso "SOC CONSTRUCTORA OCL LIMITAD" -- PaddleOCR lo lee "I SOC CONETRUCTORA OCL LIMITAD" (un "I" espurio al inicio, más "CONETRUCTORA"/"LIMITAD" corruptos). `COD DESTINATARIO` (0002013090) no existe en `destinos.json` -- destino genuinamente no catalogado, no un bug.
4. **464522/464642** (JOSE LAZCANO, catálogo `choferes.json` clave `10833150K`): `buscar_rut_chofer()` usaba `[0-9.\s-]` -- sin "K" en la clase de caracteres, el RUT quedaba truncado en "10.833.150-" (perdiendo el verificador), y `buscar_chofer_por_rut` nunca calzaba contra el catálogo aunque el chofer sí estuviera ahí.
5. **Cliente sin corroborar generalizado:** `resolver_nombre_chofer_difuso` (fuzzy contra catálogo) solo existía para chofer -- cliente nunca tenía una vía de corroboración por similitud de nombre, solo RUT exacto.
6. **despachar_a_crudo** de 464698/464699: `"CATEDRAL 759 CADQUENES CAUQUENES"` / `"...758 CAUQUBNES CAUQUENES"` -- el documento repite la comuna en dos campos (COMUNA + CIUDAD); el OCR corrompió uno de los dos en cada guía, mientras el otro quedó legible. `estado_ruta=REQUIERE_REVISION`, `motivo=GEOCODIFICACION_DIRECCION_NO_ENCONTRADA`.

### Fase B/C/D/M -- `atlas_core/territorio_chile.py` (nuevo)

Snapshot estático de 16 regiones / 345 comunas (adaptado de un dataset público de GitHub, corregido a mano contra nombres oficiales: `Quilcura→Quilicura`, `Vitcarua→Vitacura`, `Couhaique→Coyhaique`, etc.). `normalizar_comuna(texto)`: EXACTA / NORMALIZADA_SEGURA (único candidato, similitud ≥ umbral, margen sobre el segundo) / AMBIGUA / NO_RECONOCIDA. `normalizar_direccion_con_comunas(texto)`: aplica esto palabra por palabra sobre una dirección completa -- si el token corrupto normaliza a una comuna que YA aparece exacta en otra parte del texto, se **descarta** (no se duplica); si no, se **reemplaza**. Se usa únicamente para construir la consulta al geocodificador -- `despachar_a_crudo` en el resultado nunca pierde el texto documental original.

**Bug real encontrado validando el propio bloque (antes de cerrar, no en producción):** con el umbral inicial (0.82), la palabra real "CAMINO" (de "CAMINO LOS PINOS...") normalizaba a la comuna real "Camiña" (0.833 de similitud), y "PARQUE" a "Pirque" (0.833) -- ambos falsos positivos reales, no hipotéticos. Corregido subiendo el umbral a 0.87 (los dos casos reales del bloque quedan en 0.889 y 0.923, con margen) y agregando una lista cerrada de vocabulario estructural de direcciones (CAMINO, CALLE, AVENIDA, PARQUE, SECTOR, ...) que nunca es candidato a comuna sin importar la similitud -- defensa en profundidad, no solo el umbral.

### Fase E -- `atlas_core/normalizacion_semantica.py` (nuevo)

Vocabulario societario acotado a evidencia real (catálogos + tanda): formas abreviadas cortas (SA/SPA/LTDA/EIRL, ≤4 caracteres) y palabras descriptivas largas (CONSTRUCTORA, INGENIERIA, INMOBILIARIA, ...). `normalizar_token_societario`: las formas cortas solo aceptan sustitución en la MISMA longitud (nunca inserción/eliminación); las largas toleran una distancia de edición completa (1-2 según longitud). **Bug real encontrado y corregido durante la implementación:** una tolerancia de edición uniforme dejaba "SAN" (real, común en topónimos -- "SAN BERNARDO") a distancia 1 de "SA" por eliminación, corrompiendo "SALOMON SACK SA SAN BERNARDO" en "...SA SA BERNARDO". La regla de longitud-exacta-para-formas-cortas lo corrige de raíz. `normalizar_nombre_societario`: aplica esto token por token sobre un nombre completo, más un stripper de prefijo de un solo carácter suelto (artefacto OCR real: "I SOC CONSTRUCTORA...", "I TORRES OCARANZA..." -- probablemente un separador ":"/"|" mal leído).

### Fase F/I/K -- `atlas_core/catalogos.py`

`_resolver_nombre_difuso_generico`: núcleo compartido extraído de `resolver_nombre_chofer_difuso` (comportamiento idéntico, sin romper ningún test existente) + `resolver_nombre_empresa_difuso` (nuevo, mismo criterio contra `empresas.json`). Ambos ahora también consultan `aliases` (lista opcional por registro, ya presente en `choferes.json` pero nunca antes leída por este resolver) como coincidencia EXACTA previa al fuzzy -- evidencia fuerte por diseño. `registrar_alias_seguro(ruta, identificador, alias)` (Fase K): persiste una variante OCR como alias SOLO si identifica un único registro, no es ya su nombre canónico, y no coincide con el nombre/alias de NINGÚN otro registro -- escritura atómica (temp file + `os.replace`, mismo patrón que `catalogo_clientes.py`).

### Fase G/H/L -- `atlas_core/procesamiento_masivo.py`

Bloque nuevo tras la homologación de patentes: (1) normalización societaria de `cliente`/`obra destino` (Fase E, siempre, corrobore o no -- método `NORMALIZADO`, nuevo en `MetodoObtencionDocumento`); (2) RUT exacto contra `empresas.json` -- si corrobora, aprende alias usando el valor OCR **anterior** a `enriquecer_datos_con_catalogos` (`cliente_antes_catalogo`, ya existente para trazabilidad S2.2 -- si se usara el valor ya corregido no habría nada que aprender); (3) si no, fuzzy contra `empresas.json` (Fase F, NIVEL FUERTE). Nuevo motivo informativo `CLIENTE_NUEVA_ENTIDAD_NO_CATALOGADA` (no bloqueante, agregado a `MOTIVOS_NO_BLOQUEANTES`): RUT válido + nombre consistente pero sin catálogo que lo confirme -- distinto de "OCR dudoso". **Obra destino se mantiene deliberadamente conservador** (Fase H/L, sin tocar): la corroboración por `COD DESTINATARIO` sigue exigiendo revisión ante cualquier cambio, solo se agregó la limpieza de texto (Fase E) -- nunca se "maquilla" ese estado.

### Fase M -- `atlas_core/rutas/destino_entrega.py`

`resolver_destino_entrega` aplica `normalizar_direccion_con_comunas` SOLO a la cadena de consulta enviada al geocodificador -- `despachar_a_crudo` en el resultado sigue siendo el texto documental sin tocar. Normalización local primero (Fase N): nunca se llama a ORS para "adivinar" un typo que el catálogo local ya resuelve; el proveedor de rutas se sigue llamando exactamente igual de veces que antes (no hay reintento adicional).

### Tests y regresión

20 tests nuevos en `tests/test_inteligencia_n1.py` (cubren los 18 ítems de la Fase Q). 2 tests existentes actualizados con justificación explícita (`test_caso_real_coronel_descarta_localidad_sin_soporte_textual`, `test_resolver_destino_entrega_usa_gps_para_desambiguar_de_extremo_a_extremo`): la consulta real enviada al geocodificador ya no incluye "CORONE" (token duplicado/corrupto de "CORONEL", ya legible en el mismo texto) -- el mock debía reflejar la consulta real. Suite completa: **872 → 892 tests**, 0 regresiones de comportamiento.

### Reproceso operacional

Backup: `output/_respaldos_reprocesamiento/analisis_completo_guias_PRE_N1_20260812_194428.csv`. Reproceso completo de las 19 guías reales (`procesar_archivo` real: PaddleOCR + catálogos reales + `ServicioTelemetria`/Onelogis con caché real + `OpenRouteService` real) -- justificado por el alcance del bloque (cliente/obra_destino/comuna tocan potencialmente cualquier fila, a diferencia de P4 que aisló 2 filas). Reprocesado DOS veces: la primera corrida usó el umbral de comuna sin corregir (0.82) y produjo un falso positivo real (`CAMINO`→`Camiña` en 464641/464642, que coincidentemente dejaba `RUTA_CALCULADA` con un motivo distinto pero geocodificado a un lugar equivocado); se detectó auditando el propio resultado, se corrigió el umbral+lista de exclusión, y se re-ejecutó el reproceso completo desde el backup original antes de aceptar el resultado. Reporte regenerado en `output/reporte_desktop_20260812_195650_inteligencia_n1/`; `config_usuario.json` del Desktop actualizado. Alias aprendidos en `empresas.json` durante el reproceso real: `EBEMA SA` ← `EDMA SA`, `KBEMA SA`.

### Costo

0 llamadas OCR nuevas (misma tanda ya presente localmente). Onelogis: 0 llamadas nuevas (toda la tanda ya estaba cacheada desde O2/P4). ORS: 19 llamadas de geocodificación/ruta (una por guía reprocesada, mismo patrón de costo que P4/O2 -- normalización de comuna es 100% local, nunca agrega una llamada ORS adicional).

---

## 2026-08-12 — Cierre: PATENTES P4 (recuperar patente/remolque por geometría real + revalidar 464631)

**Rama:** `lector-mvp-guia-nueva` · **Baseline:** posterior a ORIGEN O2 (`3b3189c`).

### Fase A -- traza real sobre la imagen 464631 (PaddleOCR, sin mocks)

Bloques OCR reales relevantes:
- `'PATENTE'` (bloque propio) seguido, en la misma fila, del bloque `': DD2494 CARR0:JB8529'` -- valor de PATENTE y el par CARRO:valor fusionados en un solo bloque, con la etiqueta CARRO leída **"CARR0"** (cero por O).
- `'RUT CHOFER'` (bloque propio, columna izquierda) mientras que su valor real `':14293816-2'` aparece en el texto lineal pegado a `'DESPACHAR A'` (la etiqueta de la fila anterior) -- el mismo patrón de columnas intercaladas por orden de lectura de PaddleOCR ya documentado para DESPACHAR A en OPERACIÓN REAL R1 (`_despachar_a_lineal_contaminado`).

`extraer_datos()` (la vía lineal, `buscar_chofer_y_patentes()`) exige el substring literal `"RETIRA PATENTE FECHA LLEGADA"` contiguo -- nunca aparece en un layout de dos columnas, así que la vía lineal siempre devuelve `(None, None, None)` para este tipo de documento. La causa real de la pérdida estaba en el fallback "geométrico" (`_extraer_patentes_geometrico`), que pese a su nombre no asociaba etiqueta→valor por posición: concatenaba TODO el texto de la zona RETIRA-FECHA LLEGADA en una sola cadena y buscaba por regex sobre esa cadena. Con `CARRO` leído `CARR0`, el patrón de CARRO nunca matcheaba; al buscar luego cualquier token suelto de 6 caracteres válido como patente en el resto de la zona, encontraba DOS (`DD2494` y `JB8529`, éste liberado por la falla del patrón de CARRO) y se abstenía por "ambigüedad" -- perdiendo ambas patentes.

### Fase B/C -- reescritura de `_extraer_patentes_geometrico` (`atlas_core/extractor.py`)

Nuevo diseño en dos pasos, sin hardcodear ningún valor:
1. **Inline por bloque** (`_valor_tras_etiqueta_en_bloque`): busca, DENTRO de un único bloque OCR, `ETIQUETA[:] VALOR` de 6 caracteres -- cubre el caso real (label+valor fusionados). Tolerante a confusión O/0 en la ETIQUETA vía `_tolerante_o_cero` (nunca en el valor).
2. **Fallback geométrico** (`resolver_por_geometria`): si no hay match inline, busca un bloque-etiqueta (`PATENTE`/`TRACTO`/`CARRO`/`RAMPLA`/`REMOLQUE`, comparación de bloque completo tolerante a O/0 vía `_es_etiqueta_patente`) y asocia por proximidad real (misma fila a la derecha, o alineado debajo -- mismo criterio que `_extraer_chofer_geometrico`/`_extraer_transporte_geometrico`) a su valor, excluyendo candidatos más cercanos a la etiqueta RIVAL (TRACTO vs CARRO) para que un valor sin etiqueta propia adyacente no se filtre al campo equivocado.
3. `_valor_unico_residual`: dentro de un bloque de valor ya asociado, remueve cualquier segundo par `ETIQUETA:VALOR` embebido (p. ej. el `CARRO:JB8529` que viene pegado al valor de PATENTE) y exige que quede exactamente un token de 6 caracteres válido -- se abstiene si queda más de uno.
4. Ambigüedad real ahora se mide por MARGEN DE SCORE entre candidatos de la MISMA etiqueta (margen 0.06, mismo patrón que el resto del archivo) -- un segundo token válido en la zona que esté claramente más lejos de la etiqueta ya NO bloquea el hallazgo (comportamiento anterior, ver test actualizado `test_patentes_candidato_lejano_ya_no_bloquea_al_mas_cercano`).

**Bug real encontrado durante la implementación** (no en el plan original): el fallback geométrico de TRACTO, al no conocer las etiquetas de CARRO, podía adoptar por descarte el valor de un CARRO/RAMPLA sin candidato propio de TRACTO cerca. Corregido excluyendo explícitamente cualquier candidato geométricamente más cercano a una etiqueta rival (ver `resolver_por_geometria(etiquetas, etiquetas_rivales)`).

**Ancla RETIRA tolerante** (`_es_ancla_retira`, patrón `RETI?RA`): guía real 464550 de la misma tanda, etiqueta RETIRA leída "RETRA" (falta la "I") -- sin esta tolerancia, la zona nunca se delimitaba y la función abortaba antes de llegar a evaluar PATENTE/CARRO, aunque la patente (BPHR67) estuviera perfectamente legible y geométricamente asociada.

### Fase E -- RUT del chofer por geometría (`_extraer_rut_chofer_geometrico`, nuevo)

Mismo patrón que `_extraer_rut_cliente_geometrico`: ancla en el bloque `RUT CHOFER` (bloque completo, sin subcadena), asocia por proximidad (misma fila a la derecha o alineado debajo), exige `validar_rut_chileno` con dígito verificador correcto, se abstiene ante ambigüedad. Cablea en `procesamiento_masivo.py`: se agregó `"RUT del chofer"` a la condición `campos_ausentes` que dispara la lectura de bloques geométricos, y una llamada nueva junto al resto de recuperaciones geométricas (cliente, chofer, transporte).

### Fase D -- homologación (sin cambios de código, verificado)

`DD2494`/`JB8529`/`BPHR67` ya existen en el catálogo real de vehículos (`vehiculos.json`) con el tipo correcto -- homologan a `COINCIDENCIA_EXACTA`, sin motivo `PATENTE_SIN_HOMOLOGAR`. El mecanismo que preserva un valor legible pero no homologado (motivo `PATENTE_SIN_HOMOLOGAR`, nunca "No encontrado") ya existía desde P2 y no requirió cambios -- se agregó un test dedicado (`test_patente_geometrica_sin_homologar_se_conserva_con_motivo`) para dejarlo cubierto explícitamente en este bloque.

### Fase F -- 464631, cronología real (Onelogis, cache real)

Consulta en vivo a Onelogis (bypaseando caché) confirma que la caché NO estaba desactualizada: DD2494 tiene únicamente 2 trips registrados el 11-08-2026, el último terminando a las 10:26:56 -- casi 3 horas antes de la ventana documental (13:10-13:52). Ese último trip incluye una detención real (velocidad 0 en ambos extremos, 10:20:23-10:26:56) dentro del polígono de AZA COLINA; no hay ningún trip ni evidencia de AZA RENCA ese día. `resolver_planta_origen_gps` confirma AZA COLINA como única candidata (`score=0.0` porque la detención no solapa la ventana documental -- regla de "candidato único confirma" de O2, Fase D). Se documenta explícitamente: la cobertura GPS no cubre la ventana exacta de carga, pero es la única evidencia existente y coincide con el terreno confirmado por Javier/chofer.

### Fase G -- ruta

Origen AZA COLINA + destino SANTA ISABEL 585 LAMPA (ya geocodificado) → recalculada con OpenRouteService: 7.49 km / 13.48 min, `RUTA_CALCULADA` (antes: sin resolver, origen documental era AZA RENCA).

### Fase H -- regresión en tanda reciente

Se revisaron visualmente y por extracción las 6 guías de la misma tanda con patente/rampla ausente (`464534`, `464535`, `464550`, `464588`, `464624`, `463594`). Cinco de seis no cambian (ya recuperaban tracto correctamente vía geometría, sin CARRO/RAMPLA visible en el documento -- no es un bug, esos camiones no imprimen rampla). **464550 sí tenía el mismo patrón** (`RETIRA` leído `RETRA`, bloqueando toda la zona) con `BPHR67` claramente impreso -- confirmado visualmente en la imagen real. Al recuperar la patente, la telemetría (antes nunca gateada, `_patente_valida` fallaba con `"No encontrado"`) corrió por primera vez para esta guía: confirma **AZA COLINA** con score alto (0.767, 100% de solape con la ventana documental, 101 min de detención real dentro de la ventana completa) -- reemplaza el fallback documental (`AZA RENCA`, encabezado). Ruta recalculada: 27.75 km / 38.51 min.

### Archivos modificados

- `atlas_core/extractor.py`: `_extraer_patentes_geometrico` reescrito; `_extraer_rut_chofer_geometrico` (nuevo); helpers `_es_ancla_retira`, `_es_etiqueta_patente`, `_valor_tras_etiqueta_en_bloque`, `_valor_unico_residual`, `_tolerante_o_cero`.
- `atlas_core/procesamiento_masivo.py`: import de `_extraer_rut_chofer_geometrico`; `campos_ausentes` incluye `"RUT del chofer"`; llamada de recuperación geométrica de RUT del chofer.
- `tests/test_patentes_p4.py` (nuevo, 15 tests incluyendo parametrizados): items 1-10 del bloque (patente junto a RETIRA, CARRO junto a PATENTE, orden intercalado RUT chofer, patente única, rampla única con etiquetas sinónimas, valor sin homologar conservado, ambigüedad real, regresión estructural 464631, patente habilita telemetría, planta GPS reemplaza fallback documental).
- `tests/test_extraer_datos.py`: `test_patentes_dos_candidatos_ambiguos_se_abstiene` reescrito como `test_patentes_candidato_lejano_ya_no_bloquea_al_mas_cercano` (el algoritmo anterior trataba cualquier segundo token de 6 caracteres en la zona como ambigüedad sin medir distancia real; el nuevo no).
- `tests/test_procesamiento_masivo.py`: 4 tests existentes actualizados mecánicamente (`_datos_lineales_completos` y 2 diccionarios inline) para incluir `"RUT del chofer"` -- antes ausente del diccionario de prueba, ahora forma parte de `campos_ausentes`.

### Tests y regresión

12 tests nuevos (más 3 variantes parametrizadas) en `test_patentes_p4.py`, 1 reescrito en `test_extraer_datos.py`. Suite completa: **872 passed** (861 antes + 11 netos). 0 regresiones de comportamiento -- los 4 ajustes en `test_procesamiento_masivo.py` son mecánicos (campo faltante en fixture, no en código).

### Reproceso operacional

Backup: `output/_respaldos_reprocesamiento/analisis_completo_guias_PRE_P4_20260812_185912.csv`. Reproceso quirúrgico de únicamente las 2 filas afectadas (`464631.jpeg`, `464550.jpeg`) vía `procesar_archivo()` real (PaddleOCR + catálogo real + `ServicioTelemetria`/Onelogis con caché real + `OpenRouteService` real) -- diff verificado byte a byte contra el backup: únicamente esas 2 filas cambian, las 17 restantes quedan idénticas. Reporte regenerado en `output/reporte_desktop_20260812_190025_patentes_p4/`; `config_usuario.json` del Desktop actualizado.

### Costo

0 llamadas OCR masivas (misma tanda ya presente localmente). Onelogis: 0 llamadas nuevas para 464631 (reutiliza caché de O2); 464550 generó su primera consulta real (nunca antes gateada). ORS: 2 llamadas de ruta (una por guía reprocesada).

---

## 2026-08-12 — Cierre: ORIGEN O2 (planta por ventana real de carga, no por presencia en el día)

**Rama:** `lector-mvp-guia-nueva` · **Baseline:** `e7f5a82` (PLANTAS P3).

### Decisión de negocio

`hora_entrada_aza`/`hora_salida_aza` (tiempos reales registrados en planta para ESA carga) son ancla temporal fuerte: la planta de origen se determina por dónde hubo evidencia GPS real DENTRO de `[hora_entrada, hora_salida]`, no por cualquier presencia del vehículo en cualquier momento del día. Una visita a otra planta fuera de esa ventana nunca produce conflicto contra la planta donde ocurrió la carga real.

### Fase C -- causa raíz de por qué T3 perdía paradas reales (bug real, 464424)

`detectar_detenciones` (T3) agrupaba por TRIP: un trip completo era "estacionario" solo si su primer y último punto quedaban cerca entre sí. Con evidencia real (464424, SB6486): el trip 30550165 recorre 29,79 km en total, pero contiene una parada real de ~15-18 min en el medio (velocidad GPS 0-16 km/h) entre una aproximación y una salida a 20-51 km/h -- el trip COMPLETO nunca se detiene de punta a punta, así que T3 nunca la detectaba. Reescrito para agrupar la secuencia COMPLETA y ordenada de breadcrumbs (de todos los trips en la ventana, cruzando límites de trip) en clusters espacio-temporales: un cluster se extiende mientras cada punto nuevo quede a `RADIO_COHERENCIA_DETENCION_KM` (0,6 km) del CENTROIDE corriente del cluster (no un punto fijo -- una detención real de decenas de minutos puede derivar lentamente dentro del mismo patio, comparar contra un punto ya lejano rompía el cluster de a poco). Exige ≥2 puntos por cluster (un solo breadcrumb nunca prueba permanencia).

Segundo filtro real, `VELOCIDAD_MAXIMA_DETENCION_KMH = 18.0` (calibrado con evidencia real: dentro de la parada confirmada de 464424 la velocidad nunca superó 16 km/h; en la aproximación/salida ya estaba en 20-51 km/h): un punto con velocidad reportada por encima del umbral nunca abre ni extiende un cluster -- sin este filtro, el tramo de aproximación/salida (lento pero espacialmente cercano) "puenteaba" dos paradas reales distintas en un cluster diluido. Si el proveedor no informa velocidad (`None`), no bloquea nada -- solo el criterio espacial.

**Bug real encontrado y corregido durante la validación:** `_resolver_planta_para_detencion` recibía "todos los breadcrumbs de los trips tocados por la detención" en vez de los puntos REALES del cluster -- diluía la proporción dentro/fuera con puntos de aproximación/salida ajenos al cluster. `DetencionTelemetria` gana un campo `puntos` (los puntos reales del cluster) para que esto ya no dependa de reconstruir aproximaciones.

### Fase A/C -- `EvidenciaOrigenPlanta` y score (nuevo modelo, `atlas_core/telemetria/modelos.py`)

Por cada planta candidata: `duracion_dentro_min` (solape de sus detenciones con la ventana documental), `porcentaje_ventana`, `porcentaje_puntos`, `entrada_gps`/`salida_gps`, `estadias`, `score`, `motivos`. Score (pesos suman 1.0, ver `PESO_*` en `seleccion_recorrido.py`): 0,50 solape con la ventana + 0,20 continuidad (una sola permanencia real vs. muchos toques fragmentados) + 0,15 proximidad de salida GPS a `hora_salida` + 0,15 proximidad de entrada GPS a `hora_entrada` (decae linealmente a 0 a partir de 60 min de diferencia). Evidencia de breadcrumbs sueltos (Fase I de T3) se incorpora con la MISMA vara de medir -- agrupada por proximidad TEMPORAL real (`GAP_MAXIMO_MIN_PREDETERMINADO`, ya calibrado en T2) para no fusionar dos toques separados por una hora+ en una sola "detención sintética" (bug real encontrado con 463630: dos pases por carretera a 88 km/h, 08:03 y 09:42, se fusionaban en un supuesto span de 99 minutos).

### Fase D -- conflicto real vs. margen suficiente

`MARGEN_SCORE_SUFICIENTE = 0.15`: con 2+ plantas candidatas, si la líder saca esa ventaja o más sobre la siguiente, se confirma con margen amplio; si no, `ORIGEN_GPS_CONFLICTO` explícito (`CONFLICTO_REAL_EN_VENTANA`, con el score y solape de cada una en el motivo). Una detención real y sustancial ya no puede ser invalidada por un breadcrumb aislado de otra planta (comportamiento de T3 corregido) -- pierde por margen, no crea un conflicto automático.

### Fase H -- una hora o ninguna

Con solo una hora documental: ventana = ancla ± `MARGEN_VENTANA_UNA_HORA_MIN` (= `GAP_MAXIMO_MIN_PREDETERMINADO`, 90 min, reutiliza una constante ya calibrada en vez de inventar un número nuevo). Sin ninguna hora: se abstiene igual que siempre (`SIN_HORA_DOCUMENTAL`), sin cambios.

### Hallazgo real que excede el alcance original (consultado con el usuario antes de aplicar)

Al validar contra los 10 casos de conflicto de P3 y contra 464424, la evidencia GPS real de "Renca" en TODOS los casos (incluidos 463630 y 463594, confirmados desde TELEMETRÍA T1, el primer bloque de esta línea de trabajo) resultó ser un cruce por la vía pública cercana a 64-88 km/h -- nunca una detención real -- mientras que en TODOS existe una detención real (45 min-2h+) en el mismo recinto de Colina. Se consultó explícitamente antes de aplicar esta conclusión ampliamente (ver Fase H del bloque, "Renca debe seguir funcionando"): se confirmó que NINGUNA guía de esta tanda real tenía, antes de este bloque, una detención real confirmada en Renca (todas las confirmaciones previas de Renca en esta tanda -- salvo 464424, ya corregido a Colina por decisión explícita -- ya estaban marcadas `CONFLICTO` desde P3, no eran evidencia "limpia" que este bloque estuviera rompiendo). Se aplicó el resultado de O2 a los 19 documentos de la tanda. **Pregunta abierta, no resuelta en este bloque:** si AZA RENCA necesita su propia geocerca poligonal (como Colina en P3) para capturar dónde realmente se detienen los camiones, o si esta tanda real específicamente no incluye cargas en Renca -- no se tocó la geocerca de ninguna planta (Fase K del bloque).

### Datos reales (Fase N)

Respaldo previo (`analisis_completo_guias_PRE_O2_20260812_175004.csv`). Reproceso de la tanda completa (19 guías). Reporte en `output/reporte_desktop_20260812_175433_origen_o2/`; `config_usuario.json` actualizado. Rutas recalculadas desde el origen corregido (Fase J, mecanismo ya existente de R1/T3, sin código nuevo): 464424 pasa de 16,73 km (desde Renca) a 30,77 km (desde Colina, `punto_ruteo` real); 463630 pasa de 536,70 km a 549,73 km; 464700 pasa de 505,08 km a 518,10 km.

### Tests

12 nuevos en `tests/test_origen_o2.py`: visita fuera de ventana no afecta la planta dentro (ambos sentidos); ambas plantas dentro de la misma ventana es conflicto real; estadía prolongada domina sobre punto aislado; salida de geocerca cerca de `hora_salida` corrobora; patrón real 464641/642 (sin hardcodear el número de guía); parada real en medio de un trip largo se detecta (patrón 464424, sin hardcodear); multiguía; una sola hora usa margen simétrico; sin ninguna hora se abstiene; cambio de planta recalcula la ruta desde el `punto_ruteo` correcto; no regresión (suite completa). Suite: 849 → **861 passed**, 0 regresiones de código.



## 2026-08-12 — Cierre: PLANTAS P3 (geocercas operacionales poligonales + corrección real de AZA COLINA)

**Rama:** `lector-mvp-guia-nueva` · **Baseline:** `469cecb` (TELEMETRÍA T3).

### Decisión de producto (contexto)

Javier confirmó visualmente en Onelogis, para AL1879 (464641/464642), que la ubicación de la detención de T3 ("Gerdau Aza, Lampa") ES el recinto operacional real de AZA COLINA (acceso, estacionamientos, oficinas, zonas de carga) -- un punto+radio de 1,5 km nunca puede representar bien un complejo real amplio. Explícito: no crear "AZA LAMPA" -- es la misma planta, con nomenclatura cartográfica de apoyo.

### Fase B -- modelo de geocerca (backward-compatible)

`atlas_core/catalogo_plantas.py`: `Planta` gana `tipo_geocerca` (`TipoGeocerca.CIRCULAR|POLIGONAL`, default `CIRCULAR`) y `vertices: tuple[tuple[float,float],...]` (default `()`), agregados AL FINAL del dataclass. `desde_dict()` ya no exige coincidencia EXACTA de campos -- calcula `faltantes`/`desconocidos` contra `Planta.CAMPOS_OPCIONALES_LEGADO` y rellena los opcionales ausentes con su default (`registro antiguo sin tipo_geocerca/vertices/punto_ruteo_* -> CIRCULAR, comportamiento sin cambios`); campos realmente desconocidos siguen rechazándose (protección contra corrupción). `_validar_geocerca()`: CIRCULAR nunca trae vértices; POLIGONAL exige ≥3. `crear()`/`editar()` aceptan los campos nuevos.

`atlas_core/rutas/geocerca.py`: nueva `punto_en_poligono()` (ray casting determinista sobre lat/lon como plano local -- válido a escala de un recinto real de cientos de metros, sin dependencia GIS). `resolver_planta_por_posicion()` reescrito para separar candidatas POLIGONALES (contención real) de CIRCULARES (distancia/radio, comportamiento intacto) -- un match poligonal junto con cualquier otro es ambigüedad real (no hay medida común de desempate); con solo candidatas circulares, la regla de desempate original (más cercana gana, empate exacto = ambiguo) queda sin tocar.

### Fase C -- polígono real de AZA COLINA (evidencia, no el dibujo de Javier)

Fuente de los vértices: envolvente convexa (10 vértices, algoritmo monótono de Andrew) de los 117 breadcrumbs reales de la detención de T3 (AL1879, 11-08-2026, 08:48:58-14:57:22), reutilizando la caché ya existente -- **0 llamadas nuevas a Onelogis**. Validación cartográfica independiente (ORS/Pelias, 2 métodos): reversa de cada vértice → "Gerdau Aza, Lampa"; búsqueda directa de "Avenida Presidente Eduardo Frei Montalva, Lampa" → coincide (confianza 1.0) a 0,2-0,3 km del polígono; búsqueda de "Ruta 5" → "Cruce Ruta 5 - Av. Américo Vespucio/Costanera Norte" real a ~0,4-0,65 km. Confirma que el recinto linda directamente con la vía que Javier describió.

### Fase E -- jerarquía de evidencia con polígonos (2 correcciones reales durante la validación)

1. **Bug real:** `detectar_entrada_salida_planta()` (chequeo por punto SUELTO, usado como evidencia media/alta) aceptaba un match POLIGONAL de un solo breadcrumb -- un camión que solo ATRAVIESA la vía pública junto al polígono (caso real: SB6486 cruzando en un trip de 30 km) dejaba puntos sueltos "dentro" sin haberse detenido nunca. Corregido: plantas POLIGONALES quedan EXCLUIDAS de este chequeo por punto aislado -- solo se confirman por una detención real (mayoría de puntos, `_resolver_planta_para_detencion`, nueva función: proporción de puntos de la detención dentro del polígono, `PROPORCION_MINIMA_DENTRO_POLIGONO=0.5`, "mayoritariamente" literal, nunca 100%).
2. **Hallazgo real durante el reproceso completo (no un bug, una ambigüedad real):** 10 guías de la tanda que ya confirmaban AZA RENCA limpio (463594, 463630, 464534/535, 464588, 464601, 464624, 464698/699/700) también muestran detenciones reales (68-98% de puntos dentro, 32min-2h+) en el mismo polígono, en fechas distintas -- se consultó con el usuario (decisión de alto impacto): mantener el polígono tal cual (confiar en la evidencia visual de Javier para AL1879) y dejar estos casos en `ORIGEN_GPS_CONFLICTO` explícito para revisión manual, en vez de forzar Renca o ajustar el polígono a ciegas. Motivo legible: `CONFLICTO_AZA_COLINA_VS_AZA_RENCA(estadia_en=...;breadcrumb_aislado_en=...)`.

### Fase I -- `punto_ruteo` (separado del polígono y de la dirección, decisión explícita del usuario)

`Planta` gana `punto_ruteo_latitud`/`punto_ruteo_longitud` (opcionales, `None` default). Nueva `coordenada_ruteo_planta(planta)` en `geocerca.py`: usa `punto_ruteo_*` si la planta lo trae, si no cae a `latitud`/`longitud` exactamente como siempre (fallback explícito para toda planta sin punto de ruteo propio). Reemplaza los 3 usos directos de `Coordenadas(planta.longitud, planta.latitud)` como origen de ruta (`destino_entrega.py` ×2, `enriquecimiento_viaje.py` ×1) -- Renca sigue usando su único punto de siempre (fallback). Para AZA COLINA: `punto_ruteo` = el breadcrumb real más cercano (0,303 km) a "Avenida Presidente Eduardo Frei Montalva" real -- nunca el centroide del polígono ni la coordenada histórica ya demostrada imprecisa (18,4 km fuera del recinto).

### Catálogo real (`plantas.json`)

AZA COLINA: `tipo_geocerca=POLIGONAL`, 10 vértices reales, `punto_ruteo_latitud/longitud` nuevos: `latitud`/`longitud` (dirección histórica) **sin cambios**. Observación documenta fuente de vértices, validación cartográfica, decisión de no crear "AZA LAMPA", alias asociados ("Gerdau Aza", "Av. Pdte. Eduardo Frei Montalva, Colina/Lampa", "Panamericana Norte 18500"), y el propósito del `punto_ruteo`. AZA RENCA: sin cambios (`CIRCULAR`, sin vértices, sin `punto_ruteo` -- Fase H).

### Datos reales (Fase M)

Respaldo previo (`analisis_completo_guias_PRE_P3_20260812_161332.csv`). Reproceso de la tanda completa (19 guías, mismo criterio de esquema consistente que R1.1/T3). Reporte en `output/reporte_desktop_20260812_162735_plantas_p3/`; `config_usuario.json` actualizado. Ruta real recalculada desde el nuevo `punto_ruteo`: 464577 (TG8925) → AZA COLINA → Galvarino 8501, Quilicura, 13,18 km / 19,06 min (RUTA_CALCULADA) -- confirma que el punto de acceso real, no el centroide ni la dirección antigua, es el que efectivamente alimenta ORS.

### Tests

12 nuevos en `tests/test_plantas_p3_geocercas_poligonales.py`: point-in-polygon dentro/fuera/borde (sin lanzar); planta circular legado (sin `tipo_geocerca`/`vertices`) sigue funcionando igual; estadía mayoritaria dentro confirma; maniobra parcial en el borde no impide confirmar (mayoría, no 100%); dos plantas en conflicto vía detenciones; tránsito aislado por el polígono NO confirma sin detención real (regresión del bug de Fase E); multiguía comparte la misma planta; Renca circular sin regresión; ningún alias cartográfico crea una planta nueva; cambio de planta usa el `punto_ruteo` real, nunca el centroide ni el histórico. Suite completa: 837 → **849 passed**, 0 regresiones de código (10 conflictos nuevos son un hallazgo real de datos, documentado, no un bug).



## 2026-08-12 — Cierre: TELEMETRÍA T3 (origen por detenciones/estadías GPS, no solo breadcrumbs sueltos)

**Rama:** `lector-mvp-guia-nueva` · **Baseline:** `aa1b5bb` (OPERACIÓN REAL R1.1).

### Contradicción real que motivó el bloque

R1.1 concluyó `ORIGEN_GPS_NO_DETERMINADO` para AL1879 (464641/464642, 11-08-2026). Javier revisó la UI de Onelogis y vio al vehículo detenido varias horas en "AVENIDA PRESIDENTE EDU...", con confirmación directa de los choferes de que el viaje salió de AZA COLINA. Se investigó la contradicción sin asumir que Javier estaba equivocado ni que la API carecía de evidencia.

### Fase A -- releído `openapi.yaml` real (WebFetch, 2026-08-12)

Confirma lo ya documentado en T1: `Trip` no trae coordenadas de inicio/fin ni dirección (`trip_id, plate, start_time, end_time, distance_km, max_speed, idle_minutes, type`); no existe endpoint de "stops"/detenciones. `BreadcrumbPoint`/`Position` sí traen `event` (valores reales observados: `ENGINE_ON`, `ENGINE_OFF`, `PERIODIC_ON`). La única evidencia de permanencia disponible es indirecta: trips con desplazamiento neto ~0 (ignition-cycling sin movimiento real) y los huecos SIN telemetría entre trips consecutivos cuyos extremos son espacialmente coherentes.

### Fase B/C -- causa raíz real (no una limitación de la API)

Traza completa (sin filtro de distancia) de AL1879, 11-08-2026: 11 trips entre 05:56 y 14:57. Un hueco de **3h08min** entre el trip que termina a las 10:22 y el que empieza a las 13:30 -- con extremos coherentes (~30m de diferencia) -- es evidencia fuerte de permanencia continua. Encadenando TODOS los trips con extremos coherentes entre sí (incluidos los de desplazamiento neto ~0), la permanencia real cubre **08:48:58 → 14:57:22 (6h08min)**, solapando casi todo el rango documental (09:46-14:39).

### Fase E -- auditoría de coordenadas (hallazgo principal del bloque)

La coordenada de esa detención (-33.2947, -70.7281) geocodifica -- dos veces, con métodos independientes (reversa y directa, vía Pelias/ORS) -- como **"Gerdau Aza, Lampa, RM, Chile"** (confianza 0.6-0.8, capa `venue`). Gerdau es la matriz de Aceros AZA; el mismo buscador devuelve por separado "Gerdau, Renca" coincidiendo exacto con el catálogo, y "Gerdau AZA Antofagasta" como tercer sitio conocido. Todo indica una planta AZA real en Lampa, no catalogada, distinta de Colina (18,4 km) y de Renca (12,5 km). **Se consultó al usuario antes de tocar el catálogo** (decisión de alto impacto, no reversible sin más evidencia): se optó por NO agregarla todavía -- el modelo nuevo debía poder reportar la detención honestamente sin nombrarla, no por asumir que es Colina ni inventar un nombre de planta nuevo.

### Cambios de código

- **`atlas_core/telemetria/modelos.py`**: nuevo `DetencionTelemetria` (inicio, fin, duracion_minutos, latitud, longitud, fuente, trip_ids) -- sin depender de `atlas_core.rutas` (mismo criterio que `PosicionTelemetria`).
- **`atlas_core/telemetria/seleccion_recorrido.py`**:
  - `ORIGEN_GPS_ESTADIA_SIN_PLANTA` (nuevo estado): hay una detención GPS real y prolongada, pero su coordenada no cae en ninguna geocerca catalogada -- nunca se le asigna nombre de planta.
  - `ResultadoOrigenGPS` gana `latitud_estadia`/`longitud_estadia`/`duracion_estadia_min` (solo poblados en ese estado).
  - `RADIO_COHERENCIA_DETENCION_KM = 0.6` (calibrado con el caso real: puntos del mismo lugar de permanencia varían 0.02-0.4 km entre sí) y `DURACION_MINIMA_DETENCION_MIN = 30.0` (paradas más cortas son ruido de maniobra, no evidencia operacional).
  - `detectar_detenciones(viajes, breadcrumbs_por_trip)`: encadena trips (y sus huecos de telemetría) cuyos extremos son espacialmente coherentes -- un trip es "estacionario" cuando su propio primer y último breadcrumb quedan a `radio_coherencia_km` uno de otro. Exige **al menos 2 breadcrumbs** por trip para juzgar estacionariedad (un solo punto no prueba nada -- podría ser una foto instantánea de un trip real disperso).
  - `resolver_planta_origen_gps` reescrito: (1) la ventana temporal ahora cubre `[min(entrada,salida), max(entrada,salida)] ± margen_horas` -- antes anclaba solo en `hora_salida` (o `hora_entrada` si faltaba), lo que en casos reales con las dos horas muy separadas (464641/642: 09:46 y 14:39, casi 5h) dejaba fuera trips reales cerca de la otra hora; (2) jerarquía de evidencia (Fase I): detención dentro de geocerca (evidencia máxima, con `solape_documental_min` calculado contra las horas documentales) > breadcrumbs sueltos que pasan por geocerca (comportamiento de R1, sin cambios) > detención real sin planta catalogada (`ORIGEN_GPS_ESTADIA_SIN_PLANTA`, nunca silenciada) > sin evidencia; (3) cruza SIEMPRE la detención confirmada contra el escaneo de breadcrumbs sueltos -- si señalan una planta DISTINTA, es `ORIGEN_GPS_CONFLICTO` explícito, nunca se ignora la señal más débil.
- **`atlas_core/telemetria/enriquecimiento.py`**: `CAMPOS_TELEMETRIA_DOCUMENTO` pasa de 9 a 13 campos (+ `motivo_origen_gps`, `latitud_estadia_gps`, `longitud_estadia_gps`, `duracion_estadia_gps_min`).
- **`atlas_core/procesamiento_masivo.py`**: la rama que limpia el fallback documental (R1.1) ahora también dispara con `ORIGEN_GPS_ESTADIA_SIN_PLANTA` (antes solo `CONFLICTO`/`NO_DETERMINADO`) -- una detención sin planta catalogada tampoco debe dejar "AZA RENCA" del encabezado.
- **`atlas_core/gestor_viajes.py`** / **`atlas_core/reporte_viajes.py`**: propagan los 4 campos nuevos hasta `viajes.csv` (mismo criterio de consolidación "coincide en todos los documentos o vacío").

### Resultado real (Fase F/G/H)

- **464641/464642 (AL1879)**: `ORIGEN_GPS_ESTADIA_SIN_PLANTA` -- detención real de 368,4 / 286,3 min (según la hora documental disponible en cada guía) en (-33.2949, -70.7285) aprox., trips `30585346|30586520|30586682|30586909|30590516|...`. Nunca Renca, nunca Colina sin evidencia.
- **464424 (SB6486)**: sin cambios -- sigue `ORIGEN_GPS_CONFIRMADO`/AZA RENCA, ahora validado también contra el modelo de detenciones (mismo resultado, evidencia más rica).
- **Efecto colateral real del fix de ventana (Fase H)**: 464534/464535 (BDFG50, antes sin planta confirmada) ahora resuelven `ORIGEN_GPS_CONFIRMADO`/AZA RENCA -- la evidencia ya existía, la ventana anterior no llegaba a mirarla.

### Datos reales (Fase K/L)

Respaldo previo (`analisis_completo_guias_PRE_T3_20260812_145913.csv`). Reproceso focal (3 guías) validado, luego reproceso de la tanda completa (19 guías, mismo criterio que R1.1 -- todas comparten el esquema de columnas). CSV maestro reemplazado; reporte regenerado en `output/reporte_desktop_20260812_150552_telemetria_t3/`; `config_usuario.json` de Desktop actualizado. Ninguna ruta se recalculó hacia Colina (sin confirmación); las guías que ganaron confirmación de Renca (464534/535) se benefician del cálculo de ruta automático ya existente en `procesamiento_masivo.py` (sin código nuevo).

### Tests

12 nuevos en `tests/test_telemetria_t3.py`: detención encadenada entre trips en la misma posición; estadía dentro de geocerca confirma planta; solape con hora documental se registra en el motivo; salida real (movimiento) corta la cadena de detención; endpoint sin breadcrumbs se ignora sin lanzar; un solo breadcrumb nunca se considera estacionario; validación positiva de que el mecanismo SÍ confirma Colina con evidencia real (no hardcodeado); multiguía comparte la misma resolución; nunca cae a Renca por defecto aunque haya estadía real fuerte; conflicto explícito entre estadía confirmada y breadcrumb aislado de otra planta; la caché de breadcrumbs se reutiliza para detectar detenciones sin llamadas nuevas; no regresión (verificada con la suite completa). `tests/test_operacion_real_r1.py` (1 aserción actualizada -- comportamiento mejorado, ver test) y `tests/test_procesamiento_masivo.py` (conjunto de columnas, mecánico). Suite completa: 825 → **837 passed**, 0 regresiones reales.



## 2026-08-12 — Cierre: OPERACIÓN REAL R1.1 (eliminar fallback documental sin confirmación GPS)

**Rama:** `lector-mvp-guia-nueva` · **Baseline:** `2ec64c9` (OPERACIÓN REAL R1).

### Decisión de alcance (consultada explícitamente antes de implementar)

R1.1 pedía eliminar "GPS no determinado + encabezado dice Renca → AZA RENCA" sin especificar si el cambio debía aplicar solo al punto donde corre el bug (telemetría conectada y corrida) o a todo el pipeline (incluyendo cuando no hay telemetría en absoluto, lo que habría tocado `resolver_origen_documental`/`resolver_planta_origen` y ~15 archivos de test existentes que validan ese fallback como comportamiento intencional para arquitectura sin GPS). Se preguntó al usuario; eligió el alcance acotado: el fix vive únicamente en `procesamiento_masivo.py`, en el punto exacto donde el bug ocurre.

### Investigación real (Fase A/B/C/D) antes de tocar código

Traza GPS completa (sin filtro de distancia, múltiples días) para los 2 controles positivos que Javier señaló:

- **464424 / SB6486 (07-08-2026):** 2 trips ese día pasan a 1,14 km y 1,21 km de AZA RENCA -- dentro de la geocerca de 1,5 km. Nunca a menos de 17,7 km de AZA COLINA. Se revisó también el día anterior (06-08-2026): el mismo patrón se repite 4 veces más (0,15-1,2 km de RENCA, 17,7-29 km de COLINA). **Conclusión: la evidencia GPS real, repetida en 2 días, indica RENCA, no Colina, para este vehículo/fecha específicos.** Esto contradice la observación de Javier sobre esta guía puntual -- se reporta así, sin forzar ninguna de las dos plantas artificialmente (ni Colina porque Javier lo dijo, ni descartar su observación como error).
- **464641/464642 / AL1879 (11-08-2026):** revisados TODOS los trips del día (11 tramos, 05:56-14:57), no solo los cercanos a la hora documental -- ninguno pasa a menos de 10,3 km de RENCA ni de 17,7 km de COLINA. Se revisó también el día anterior (10-08-2026, 6 trips): mismo patrón, el vehículo pasa el día cerca de un punto fijo (~12,5 km de Renca, ~18,3 km de Colina) que no corresponde a ninguna de las dos plantas -- muy probablemente el depósito/base propia del transportista. **Conclusión: no hay evidencia GPS real, en 2 días completos de datos, que confirme ni Renca ni Colina para este transporte.**
- **Causa raíz de por qué R1 no detectó Colina en estos casos:** no es un bug de geocerca, ventana temporal, ni cache -- las coordenadas GPS reales de estos vehículos, en las fechas revisadas, simplemente no pasan cerca de ninguna de las dos plantas. R1 SÍ tenía razón en abstenerse (`ORIGEN_GPS_NO_DETERMINADO`) para AL1879 -- el bug real era que, a pesar de esa abstención correcta, el resultado final seguía mostrando "AZA RENCA" por la razón documental de siempre (ver Fase E).
- **Geocerca de Colina confirmada de nuevo:** no se encontró ningún punto real que pase cerca de Colina y quede fuera del radio por poco -- las distancias mínimas observadas (17,7-29 km) descartan que sea un problema de radio insuficiente.

### Cambio de código (Fase E)

`atlas_core/procesamiento_masivo.py::procesar_archivo` -- nueva rama `elif` justo después de la que aplica `ORIGEN_GPS_CONFIRMADO`: si `estado_telemetria == EstadoSeleccionRecorrido.SELECCIONADO` (la telemetría corrió sobre datos reales, no un fallo de conexión/credencial) y `origen_gps` es `ORIGEN_GPS_CONFLICTO` o `ORIGEN_GPS_NO_DETERMINADO`, se limpian `planta_origen_id`/`planta_origen_nombre`/`origen_determinado_por`/`evidencia_origen` y se invalida cualquier ruta (`distancia_km`/`duracion_min`/`proveedor_ruta`/`estado_ruta="ORIGEN_NO_DETERMINADO"`/`motivo_ruta`) que hubiera quedado calculada desde el origen documental descartado. `despachar_a_crudo`/`direccion_entrega`/`localidad_entrega`/`region_entrega`/`estado_entrega` (destino) nunca se tocan -- siguen siendo independientes del origen. Si `servicio_telemetria` es `None`, o el proveedor no pudo ni conectar (`SIN_CREDENCIAL`, `VEHICULO_NO_ENCONTRADO`, etc. -- `estado_telemetria` distinto de `SELECCIONADO`), el comportamiento documental de siempre no cambia.

Imports nuevos: `EstadoSeleccionRecorrido` (`atlas_core.telemetria.modelos`), `ORIGEN_GPS_CONFLICTO`/`ORIGEN_GPS_NO_DETERMINADO` (ya existían en `seleccion_recorrido.py`, ahora también importados aquí).

### Datos reales (Fase L/H)

Respaldo previo (`analisis_completo_guias_PRE_R1_1_20260812_141342.csv`). Reproceso focal de las 3 guías señaladas (464424, 464641, 464642) primero, validado; luego reproceso de la tanda reciente completa (19 guías reales -- creció de 9 a 19 porque Javier ingresó más guías vía Desktop entre R1 y R1.1) para aplicar el fix consistentemente (Fase H). Reporte regenerado en `output/reporte_desktop_20260812_142001_operacion_real_r1_1/`; `config_usuario.json` de Desktop actualizado.

**Clasificación final de la tanda (19 guías):** `RENCA_CONFIRMADA_GPS` (`origen_gps=ORIGEN_GPS_CONFIRMADO`, `origen_determinado_por=TELEMETRIA_GPS`) -- 464424, 464588, 464601, 464624, 464698, 464699, 464700, 463594, 463630 (9). `ORIGEN_GPS_NO_DETERMINADO` (planta vacía, antes mostraban Renca por el bug) -- 464522, 464529, 464534, 464535, 464577, 464640, 464641, 464642 (8). `AZA RENCA` por `DOCUMENTO` (sin patente legible, telemetría nunca corrió) -- 464550, 464631 (2). Ningún caso de `AZA COLINA` confirmada ni de `ORIGEN_GPS_CONFLICTO` en esta tanda.

### Tests

7 nuevos en `tests/test_operacion_real_r1_1.py`: GPS confirma Colina si la evidencia lo sustenta (mecanismo general validado con datos sintéticos); GPS no determinado limpia la planta del encabezado (integración real vía `procesar_archivo`, con mocks de OCR/telemetría/rutas); sin telemetría conectada conserva el comportamiento documental previo (fija el límite del alcance elegido); ruta previa se invalida si GPS deja de confirmar; caché solo guarda datos crudos, nunca una selección derivada (por eso cambiar la lógica de resolución nunca reutiliza una selección vieja incorrecta); multiguía -- ambos documentos del mismo transporte quedan consistentemente sin planta; Renca confirmado sigue funcionando (regresión explícita del camino mayoritario). Suite completa: 818 → **825 passed**, 0 regresiones.



## 2026-08-12 — Cierre: OPERACIÓN REAL R1 (origen por GPS, no por letterhead)

**Rama:** `lector-mvp-guia-nueva` · **Baseline:** `3659740` (E2E R2).

### Decisión

La planta de origen de un viaje Atlas se determina mediante telemetría/GPS y geocercas de plantas cuando el proveedor está disponible. La guía no contiene la dirección de origen y no se usa para inferirla. `resolver_origen_documental()` (encabezado impreso) queda como fallback legítimo únicamente cuando no hay evidencia GPS -- nunca se filtra el catálogo de plantas para forzar un match documental sobre una planta ya confirmada por GPS (se evaluó y se descartó: forzaría un fallo del letterhead, que nunca menciona "COLINA").

### Causa raíz

`resolver_origen_documental()` tokeniza el encabezado de la guía y matchea contra el catálogo de plantas -- pero el encabezado de AZA es idéntico ("CASA MATRIZ PLANTA RENCA...") en toda guía, sin importar la planta real de despacho: resuelve a AZA RENCA siempre, nunca genuinamente a COLINA. No era un problema de prioridad GPS-vs-documento (la prioridad ya estaba bien diseñada) sino de que el chequeo GPS casi nunca llegaba a correr sobre el origen: (a) `resolver_entrega_documento()`/`calcular_ruta_entrega_para_viaje()` no reciben `patente`/`instante_salida` en el camino normal, así que la rama GPS de `resolver_planta_origen()` nunca tenía datos con los que trabajar; (b) en T2, la detección de origen GPS vivía DENTRO de la rama de éxito de `seleccionar_recorrido_operacional` (que exige un tramo "sustancial", `distancia_km >= 5.0`), así que un viaje de maniobra corto que sí pasa por la geocerca de la planta quedaba fuera del análisis.

### Cambios

- **`atlas_core/telemetria/seleccion_recorrido.py`**: nueva `resolver_planta_origen_gps(servicio, *, patente, fecha, hora_entrada, hora_salida, plantas, radio_km=1.5, margen_horas=4.0) -> ResultadoOrigenGPS`. Independiente de `seleccionar_recorrido_operacional`: toma como ancla `hora_salida` o `hora_entrada`, reúne TODOS los trips de Onelogis del día cuyo rango se solapa con `[ancla-4h, ancla+4h]` (sin filtro de distancia -- capta maniobras cortas), pide TODOS sus breadcrumbs y llama `detectar_entrada_salida_planta` sobre el conjunto completo. `margen_horas=4.0` calibrado contra el mayor hueco real observado hasta ahora (~2h48m, guía 463630) con margen amplio.
- **`atlas_core/telemetria/enriquecimiento.py`** (reescrito): `enriquecer_documento_con_telemetria()` ahora resuelve origen (`resolver_planta_origen_gps`) y recorrido de entrega (`seleccionar_recorrido_operacional`, para desambiguar destino) como dos preocupaciones separadas -- antes, el origen dependía de que el recorrido de entrega tuviera éxito. `CAMPOS_TELEMETRIA_DOCUMENTO` pasa de 7 a 9 campos (+ `planta_gps_id`, `planta_gps_nombre`).
- **`atlas_core/rutas/destino_entrega.py`**: nueva `calcular_ruta_con_planta_conocida(*, planta, despachar_a_crudo, proveedor_rutas, origen_determinado_por="TELEMETRIA_GPS", evidencia_origen="", perfil="driving-hgv", punto_gps_destino=None, radio_gps_destino_km=50.0) -> ResultadoRutaEntrega`. Reutiliza la geocodificación/ORS de `calcular_ruta_entrega_para_viaje` pero se salta `resolver_planta_origen()` -- la planta ya se conoce con certeza (GPS), y volver a derivarla del letterhead fallaría siempre para COLINA.
- **`atlas_core/procesamiento_masivo.py`**: el bloque de telemetría en `procesar_archivo()` se reescribió: (1) intenta origen GPS SIEMPRE que haya `servicio_telemetria` + patente + fecha + al menos una hora (antes: solo si el origen documental "no se había determinado", condición casi nunca verdadera porque el letterhead siempre resuelve algo); (2) si `origen_gps == ORIGEN_GPS_CONFIRMADO`, sobreescribe `planta_origen_id`/`planta_origen_nombre`/`origen_determinado_por="TELEMETRIA_GPS"`/`evidencia_origen`; (3) si la planta efectivamente CAMBIÓ, invalida y recalcula la ruta vía `calcular_ruta_con_planta_conocida()` (o limpia `distancia_km`/`duracion_min` si no hay `despachar_a_crudo` o coordenadas) -- nunca reutiliza una ruta calculada desde el origen equivocado (Fase I). El reintento de destino ambiguo (`MULTIPLES_UBICACIONES_DISPERSAS`) también migra a `calcular_ruta_con_planta_conocida()`.
- **`atlas_core/extractor.py`**: `_despachar_a_lineal_contaminado()` gana un segundo chequeo -- si el valor lineal completo es un RUT chileno con dígito verificador válido (`validar_rut_chileno`), se trata como contaminado igual que una etiqueta estructural conocida, disparando el fallback geométrico. Bug real encontrado en la tanda nueva: 464631/464641 mostraban `despachar_a_crudo` = un RUT ("14293816-2"/"10833150-K") en vez de la dirección real -- el chequeo anterior solo detectaba ETIQUETAS (p. ej. "PATENTE"), no VALORES de otro campo.
- **`atlas_core/gestor_viajes.py`** / **`atlas_core/reporte_viajes.py`**: propagan `planta_gps_id`/`planta_gps_nombre` (documento → `Viaje` consolidado, mismo criterio "coincide en todos los documentos o vacío" que O1 → CSV de viajes).
- **`analizar_guias_masivo.py`**: construye `ServicioTelemetria(OnelogisProvider(), RepositorioTelemetria(carpeta_catalogos/telemetria_cache.json))` por defecto cuando hay catálogos y no se pasa `--sin-telemetria` -- antes, el CLI real que usa Atlas Desktop (`main.js` invoca este script directo) nunca conectaba telemetría; toda la corrección de origen GPS de este bloque, aunque correcta en el motor, no llegaba al flujo real de Javier hasta este cambio. `OnelogisProvider()` lee la credencial por sí mismo desde `ATLAS_ONELOGIS_API_KEY` (nunca se imprime/guarda en el CLI); sin credencial, cada consulta se abstiene con `SIN_CREDENCIAL` sin romper el procesamiento documental.

### Geocercas (Fase D)

Coordenadas de AZA RENCA (`LA UNIÓN 3070, RENCA`, lat -33.401595, lon -70.685226) y AZA COLINA (`AV. PDTE. EDUARDO FREI MONTALVA 18500, COLINA`, lat -33.137558, lon -70.665977) en el catálogo real: correctas, confirmadas por el usuario, **no se tocaron** ("no cambiar catálogo si ya está correcto"). Investigación real con ORS: geocodificar "AV. PDTE. EDUARDO FREI MONTALVA 18500, COLINA" devuelve un único candidato a 16.4 km de la coordenada guardada (confianza 0.8, sin precisión de numeración); geocodificar "PANAMERICANA NORTE 18500, COLINA" devuelve un candidato EXACTAMENTE en la coordenada guardada (distancia 0.000 km) más un segundo candidato ambiguo a 7.3 km. Conclusión: la coordenada guardada casi seguro se geocodificó originalmente desde el texto "Panamericana Norte", no desde "Eduardo Frei Montalva" de forma independiente -- ambas direcciones probablemente describen el mismo corredor físico (Av. Pdte. Eduardo Frei Montalva es el nombre oficial de ese tramo de la Ruta 5/Panamericana Norte), pero el geocodificador no tiene precisión de numeración para confirmarlo. Se documenta el hallazgo; no se agrega alias al catálogo en este bloque (no era necesario para resolver ningún caso real de la tanda).

### Datos reales (Fase O)

Respaldo previo en `output/_respaldos_reprocesamiento/` (`analisis_completo_guias_PRE_R1_20260812_131943.csv` + copia completa del reporte `reporte_desktop_20260812_123325`). Reproceso de las 9 guías del dataset operacional (7 nuevas + 463594/463630, que se reprocesan también para no dejar filas con esquema de columnas desactualizado en el mismo CSV -- ambas confirman AZA RENCA sin cambios, ahora con evidencia GPS real en vez de solo letterhead) vía `analizar_guias_masivo.py` con `ATLAS_ONELOGIS_API_KEY`/`OPENROUTESERVICE_API_KEY` inyectadas en el proceso (nunca impresas ni guardadas). CSV maestro reemplazado; `generar_reporte_viajes.py` regeneró `output/reporte_desktop_20260812_133037_operacion_real_r1/`; `config_usuario.json` (Desktop, `%APPDATA%\atlas-viajes-desktop\config_usuario.json`) actualizado para apuntar ahí.

**Resultado real de origen GPS sobre las 7 guías nuevas:** VP8521 (464698-700) → `ORIGEN_GPS_CONFIRMADO`/AZA RENCA (coincide con el documento, ahora con evidencia). TG8925 (464640) y AL1879 (464641-642) → `ORIGEN_GPS_NO_DETERMINADO` (los puntos GPS más cercanos de ese día quedan a 6.6-11.3 km de RENCA y 17.8-18.5 km de COLINA -- fuera de la geocerca de 1.5 km de ambas; se conserva el valor documental sin inventar una confirmación GPS que no existe). 464631 sin patente legible, no evaluable por GPS. Ninguna de las 7 cambia de RENCA a COLINA con la evidencia disponible hoy -- esto no contradice la observación de Javier, solo indica que estas 7 guías puntuales no la prueban con los datos GPS reales recolectados.

### Tests

Suite completa: 806 → **818 passed**. 12 tests nuevos en `tests/test_operacion_real_r1.py` (GPS cerca de Renca/Colina confirma la planta correcta; sin evidencia GPS nunca asume Renca por defecto; GPS ambiguo entre dos plantas no confirma ninguna; ventana amplia no depende solo del primer viaje "sustancial"; detección de entrada/salida de geocerca; caché no contamina otra patente/otro viaje; cambio de planta invalida y recalcula la ruta desde el origen correcto; DESPACHAR A nunca acepta un RUT como dirección, con recuperación geométrica real; multiguía resuelve una única planta física por transporte). `tests/test_procesamiento_masivo.py` actualizado (conjunto de columnas esperado, mecánico). Regresión: 0.



## 2026-08-12 — Cierre: E2E R2 (publicación de logística real en el dataset operacional y Desktop)

**Rama:** `lector-mvp-guia-nueva` · **Baseline:** `514feaa2ffec245ef9675a99f979a44d18bd019a` (TELEMETRÍA T2). **Sin cambios de código en `atlas_core` ni en Desktop** -- este bloque fue de auditoría, regeneración de datos y verificación, no de desarrollo.

### Decisión

La telemetría y ORS ya alimentan automáticamente el dataset operacional consumido por Desktop -- no hacía falta ninguna lógica nueva (Fase A confirmó que todos los campos requeridos ya existían end-to-end desde los bloques E2E R1.1/TELEMETRÍA T1/T2: `planta_origen_nombre`, `despachar_a`, `distancia_km`, `duracion_min`, `estado_ruta`, `motivo_ruta`, `proveedor_telemetria`, `estado_telemetria`, `origen_gps`, `distancia_gps_km` ya recorrían todo el camino documento → `gestor_viajes` → `reporte_viajes` → `viajes.csv`).

### Qué se hizo

Respaldo de la operación actual, luego regeneración focal (solo 463594/463630, motor E2E+T2 completo, sin histórico) de `analisis_completo_guias.csv` y `viajes.csv` en la fuente operacional canónica (`AppData\Local\Atlas\datos\operacion_desktop\` = `Proyecto-Atlas\output\`, mismo junction del Bloque E2E R1.1). `config_usuario.json` (Desktop) actualizado para apuntar al reporte nuevo.

Verificación: se instrumentó el proveedor Onelogis para contar peticiones HTTP reales durante la regeneración -- **0 llamadas nuevas** (toda la telemetría salió de la caché de T1/T2). Se ejecutó `atlas_viajes.html::normalizarFila()` y `formato_operacional.js` REALES (sin modificar Desktop) contra el `viajes.csv` regenerado, vía Node.js directo -- confirma que Desktop, sin ningún cambio de código, ya muestra: Planta origen "AZA RENCA", Destino entrega (DESPACHAR A), Distancia "536,7 km", Tiempo estimado "10 h 07 min", Estado ruta "Ruta calculada" para 463630; y "No disponible"/"Pendiente de revisión" para 463594, sin forzar ningún candidato. Ningún campo técnico de telemetría (trip_id, breadcrumbs, origen_gps) aparece en la UI -- confirmado por búsqueda textual en `atlas_viajes.html`.

`npm start` no pudo abrir una ventana real en este entorno (sin servidor de display) -- limitación del entorno de ejecución, no de Atlas; `npm test` (110 tests, sin necesitar display) sigue verde.

### Tests

806 passed (motor, sin cambios desde T2). Desktop: 110 passed, sin cambios propios de este bloque.

---

## 2026-08-12 — Cierre: TELEMETRÍA T2 (selección automática de recorrido GPS + integración E2E)

**Rama:** `lector-mvp-guia-nueva` · **Baseline:** `dd534c505fe4fa455bef317c10e016a53aa84bd9` (TELEMETRÍA T1).

### Decisión de arquitectura

**Atlas puede construir un recorrido operacional a partir de múltiples trips de telemetría y usarlo como evidencia, sin reemplazar silenciosamente los datos documentales.** Cierra la limitación explícita de T1 ("Atlas todavía NO selecciona automáticamente qué viaje/tramo Onelogis corresponde a una guía Atlas"): nuevo `atlas_core/telemetria/seleccion_recorrido.py` implementa `RECORRIDO_OPERACIONAL_GPS` -- 1..N trips consecutivos, coherentes en tiempo y espacio, tratados como UN viaje logístico real (un viaje Atlas puede quedar fragmentado en varios trips de Onelogis).

### Algoritmo (`seleccionar_recorrido_operacional`)

Puro, sin red -- opera solo sobre metadatos de trip (inicio/fin/distancia) ya obtenidos vía `ServicioTelemetria` (con caché). Ancla temporal: `hora_salida_aza` si existe (evidencia real más fuerte), si no `hora_entrada_aza` (Fase B -- ambas son horas reales registradas en planta, nunca "aproximadas"). Trips "sustanciales" (`distancia_km >= 5.0`, calibrado contra ruido real observado: -0.03 a 1.71 km) se encadenan hacia adelante mientras el hueco temporal entre el fin de uno y el inicio del siguiente sea ≤ 90 min (calibrado contra el único hueco real conocido: 51 min entre los 2 trips de 463630). Ambigüedad real (dos trips sustanciales casi simultáneos) → `TELEMETRIA_AMBIGUA`, nunca se elige arbitrariamente.

Los breadcrumbs completos SOLO se piden para los trips de la cadena ya seleccionada (nunca para toda la flota/día) -- se cachean vía la misma `RepositorioTelemetria` de T1.

### Conectado al pipeline (Fase I/J, opt-in)

`procesamiento_masivo.procesar_archivo()`/`procesar_carpeta()` aceptan `servicio_telemetria` opcional (nunca se construye uno por defecto -- requiere credencial/configuración explícita). Sin él, comportamiento idéntico a antes de este bloque. Con él conectado, se consulta SOLO si: origen sin determinar, o destino con ambigüedad real de geocodificación (`MULTIPLES_UBICACIONES_DISPERSAS`) -- nunca "para todo". `atlas_core/telemetria/enriquecimiento.py` orquesta: selecciona recorrido → detecta planta por geocerca (reutiliza `resolver_planta_por_posicion`, radio 1.5 km ya calibrado desde Bloque PLANTA-P1) → si el destino estaba ambiguo, reintenta `calcular_ruta_entrega_para_viaje` con el punto final GPS real.

Nuevas columnas (backward-compatible, vacías sin telemetría conectada): `proveedor_telemetria`, `estado_telemetria`, `origen_gps`, `hora_entrada_gps`, `hora_salida_gps`, `distancia_gps_km`, `evidencia_telemetria` -- en `procesamiento_masivo.COLUMNAS`, `gestor_viajes.DocumentoViaje`/`Viaje` (consolidación "coincide en todos los documentos o vacío", igual criterio que O1) y `reporte_viajes.COLUMNAS_VIAJES`. Nunca se guardan breadcrumbs completos aquí. `distancia_gps_km` (recorrido real medido) queda siempre separada de `distancia_km` (estimación ORS) -- Fase M.

### Resultado real, 100% automático, sin ningún tripId hardcodeado

- **463630**: recorrido seleccionado = 3 trips (el mismo conjunto identificado manualmente en T1, encontrado aquí sin conocer los IDs de antemano). Origen GPS confirmado (AZA RENCA, ~1.13 km). Destino desambiguado por GPS (Coronel/Biobío vs Coronel/Maule). **ORS desbloqueado automáticamente: 536,70 km / 606,92 min** -- mismo resultado que el reintento manual de T1, ahora producido por el pipeline sin intervención por guía.
- **463594**: recorrido seleccionado = 1 trip. Origen GPS confirmado (AZA RENCA, ~1.04 km). GPS no alcanza a desambiguar entre los 4 candidatos RM restantes -- se mantiene `REQUIERE_REVISION`, sin forzar.

### Archivos nuevos/modificados

`atlas_core/telemetria/seleccion_recorrido.py`, `atlas_core/telemetria/enriquecimiento.py` (nuevos); `atlas_core/telemetria/modelos.py` (`RecorridoOperacionalTelemetria`, `EstadoSeleccionRecorrido`, `EstadoConcordanciaHora`); `atlas_core/procesamiento_masivo.py`, `atlas_core/gestor_viajes.py`, `atlas_core/reporte_viajes.py` (columnas nuevas, opt-in); `tests/test_telemetria_t2.py` (19 tests, sin red).

### Límite conocido, no resuelto en este bloque

La geocodificación ORS (a diferencia de Onelogis, ya bien cacheado) no tiene caché propia en `destino_entrega.py` (limitación documentada desde antes de este bloque) -- cada regeneración del reporte repite las llamadas de geocodificación, aunque no las de telemetría.

### Tests

806 passed (787 previos + 19 nuevos), 0 regresiones. Desktop: sin cambios propios de este bloque.

---

## 2026-08-12 — Cierre: TELEMETRÍA T1 (integración histórica real de Onelogis, multiproveedor)

**Rama:** `lector-mvp-guia-nueva` · **Baseline:** `6afb491235ed60e3745c7d79495204b70cccf497` (E2E R1.1).

### Decisión de arquitectura

**Telemetría es un proveedor opcional y multiempresa. Onelogis es el primer adaptador, no una dependencia del núcleo.** Nuevo paquete `atlas_core/telemetria/` (`modelos.py`, `proveedor.py` — contrato `ProveedorTelemetria` + doble simulado, `servicio.py` — caché, `repositorio.py` — persistencia JSON simple, `proveedores/onelogis.py` — adaptador HTTP real). El núcleo (extractor/rutas/gestor_viajes/Desktop) nunca importa `proveedores/onelogis.py` directamente. `proveedor_telemetria=None` es un caso de primera clase en todo el pipeline: ausencia de GPS nunca rompe Atlas.

Contrato leído completo del OpenAPI real (`https://app.onelogis.com/docs/api/openapi.yaml`), sin adivinar parámetros — resumen fuera del repo en `telemetria_eval/fase_a_openapi_resumen.md`. Base URL real: `https://app.onelogis.com/api/client/v1`. Auth: `Authorization: Bearer <ATLAS_ONELOGIS_API_KEY>` (nunca logueado, nunca persistido, nunca versionado).

### Conexión con lo ya existente (no se abrió un camino nuevo)

`atlas_core/rutas/posicion_vehiculo.py` (Bloque RUTAS R1) ya definía el contrato `ProveedorPosicionVehiculo` para resolver planta origen por GPS, sin ningún adaptador real conectado desde entonces. `atlas_core/telemetria/adaptador_posicion_vehiculo.py` (nuevo) lo implementa sobre cualquier `ServicioTelemetria` — es la ÚNICA vía por la que telemetría entra al pipeline de planta origen ya existente, sin abrir un segundo camino.

Para desambiguación de DESTINO (Bloque E2E R1.1, ambigüedad Coronel/Biobío vs Coronel/Maule): nueva `descartar_candidatos_lejos_de_gps()` en `atlas_core/rutas/destino_entrega.py` — usa el punto final real de un recorrido GPS para descartar candidatos de geocodificación territorialmente incompatibles. Nunca fabrica una dirección exacta a partir del GPS, solo descarta. `resolver_destino_entrega()`/`calcular_ruta_entrega_para_viaje()` aceptan `punto_gps_referencia`/`punto_gps_destino` opcionales — sin ellos, comportamiento idéntico a antes de este bloque.

### Alcance explícitamente NO cubierto en este bloque

No se automatizó la selección de "cuál viaje Onelogis es el relevante" dentro del pipeline genérico de `procesar_archivo()` — elegir el trip correcto entre ~13-15 candidatos de un día requiere heurísticas no validadas todavía (riesgo de conclusión automática incorrecta). Se aplicó, en cambio, un análisis real explícito y documentado (`telemetria_eval/fase_e_i_*.py`) para las 2 guías conocidas. La infraestructura (proveedor/servicio/adaptador/caché) es de producción; la selección de viaje relevante sigue siendo una decisión informada, no una regla automática todavía.

### Resultado real (guías 463594/463630, 27-07-2026)

- Planta origen: confirmada por GPS para ambas — el recorrido real pasa a ~1.0-1.1 km de AZA RENCA (vs. >17 km de AZA COLINA) — corrobora el origen documental.
- 463630: destino "Coronel" desambiguado con evidencia GPS real (punto final del recorrido a ~7 km de "Coronel, Región del Biobío" vs. >470 km de "Coronel, Región del Maule", que se descarta). ORS driving-hgv desbloqueado: **536.70 km / 606.92 min**.
- 463594: GPS descarta un candidato fuera de región (Los Ángeles, Biobío, a 473 km) pero no distingue entre los 4 candidatos restantes dentro de RM (4-10 km entre sí, sin margen suficiente) — se mantiene `REQUIERE_REVISION`, sin forzar.

### Archivos nuevos/modificados

`atlas_core/telemetria/` (paquete completo, nuevo), `atlas_core/rutas/destino_entrega.py` (GPS opcional), `atlas_core/rutas/posicion_vehiculo.py` (sin cambios, solo consumido), `tests/test_telemetria_t1.py` (21 tests, sin red real). Dataset operacional regenerado en la fuente canónica (`AppData\Local\Atlas\datos\operacion_desktop\`, ver Bloque E2E R1.1) con el resultado real de 463630 corroborado por GPS.

### Tests

787 passed (766 previos + 21 nuevos), 0 regresiones. Desktop: 105 passed, sin cambios propios de este bloque.

---

## 2026-08-12 — Cierre: PRODUCCIÓN P1 (punto de partida limpio) — decisión de producto, cierra la línea de migración S3/S3.1

**Rama:** `lector-mvp-guia-nueva` · **Baseline:** `ecaa92746fb30b3b4509fc99ec96842ffc806280`. Cambios: solo datos (instalación real) + documentación (repo). Sin cambios de código en `atlas_core`.

### Decisión de producto (Javier)

Los 574 viajes publicados (generados 2026-07-28) fueron corpus de **prueba y experimentación** durante el desarrollo (validación de funciones, OCR, motores, UX) -- **no histórico operacional real**. Se cierra la línea de trabajo ESTADOS S3/S3.1 (migración/reclasificación fina de ese corpus) sin completarla -- no hacía falta. El análisis técnico ya hecho (simulación completa validada, 0 cambios incorrectos en la muestra) queda preservado como referencia en `estado_revision_eval/s3/` y `s3_1/` del repo, no se descarta, simplemente no se usa como base de la migración productiva.

### Separación ejecutada (instalación real, `AppData\Local\Atlas\datos\`)

- **Backup adicional** antes de mover nada: `C:\Users\Jjjc0508\Desktop\Atlas\backups_produccion\20260812_101500_pre_p1_corte\` -- verificado igual al estado ya respaldado en el backup de ESTADOS S3.
- **Histórico experimental movido (no copiado, no borrado), verificado byte a byte idéntico tras el movimiento:**
  - `datos\reportes\actual\*` (574 viajes) -> `datos\reportes\historicos\experimental_2026-07-28_574viajes\`
  - `datos\procesamiento\analisis_completo_guias.csv` (1177 filas) -> `datos\procesamiento\historico_experimental\analisis_completo_guias_574viajes_experimental.csv`
  - Cada carpeta histórica incluye su propio `LEEME_HISTORICO_EXPERIMENTAL.md` explicando qué es y por qué no es la fuente productiva.
- **Fecha de corte: 2026-08-12.**
- **Dataset operacional nuevo construido, sin OCR masivo:** se reprocesaron con el motor actual (HEAD `ecaa927`, incluye O1+E1+S2+S2.2+I1) las únicas 2 imágenes reales ya presentes en `datos\entradas\` (guías 463594 "Villagra", 463630 "Ñancucheo") -- mismas guías usadas repetidamente como set de validación real en bloques anteriores. Resultado honesto, sin maquillar: **2 viajes, ambos `REQUIERE_REVISION`** con motivos explícitos reales (`CLIENTE_SIN_CORROBORAR`, `OBRA_DESTINO_SIN_CORROBORAR`, `PATENTE_SIN_HOMOLOGAR`, `CLIENTE_AUSENTE`) -- refleja el estado real de esos documentos bajo el modelo actual, no un número elegido para verse bien.
  - `datos\procesamiento\analisis_completo_guias.csv` (nuevo, 2 filas, esquema completo actual)
  - `datos\reportes\actual\viajes.csv` (nuevo, 2 viajes, 34 columnas -- esquema O1+E1+S2/S2.2 completo)
- Verificado estructuralmente: columnas mínimas que exige el parser de Desktop (`viaje_id`, `numero_transporte`, `fecha`, `estado`) presentes; campos O1 (peso/horas) con datos reales; campos E1/ruta vacíos (correcto -- sin `calculador_rutas` conectado a una corrida real todavía, no se inventó evidencia).

### Documentación

- `docs/HISTORICO_EXPERIMENTAL_VS_OPERACION.md` (nuevo, en el repo): tabla de ubicaciones antes/después del corte, fecha de corte, cómo cargar el histórico manualmente si hace falta (el parser de Desktop ya tolera columnas ausentes desde el Bloque O1 -- no se construyó ningún filtro ni vista especial).

### Flujo hacia adelante

Cada imagen nueva en Desktop: motor actual -> `analisis_completo_guias.csv` operacional -> `viajes.csv` operacional. El histórico vive en carpetas separadas (`reportes\historicos\`, `procesamiento\historico_experimental\`) -- `procesar_carpeta`/`generar_reporte_viajes` nunca las tocan salvo que se les apunte explícitamente ahí.

### Tests

Sin cambios de código -- suite completa reconfirmada verde: **742 passed**. Las protecciones de esquema relevantes (`test_rechaza_encabezado_incompatible_sin_modificarlo` y equivalentes) ya existían de bloques anteriores y siguen vigentes sin modificación.

### Producción

Histórico preservado intacto (verificado por hash). Nuevo reporte operacional real, pequeño y honesto, ya activo en `datos\reportes\actual\`.

---

## 2026-08-12 — Cierre: ESTADOS S3 (migración controlada del dataset productivo) — SIMULACIÓN APROBADA, migración diferida por decisión de negocio

**Rama:** `lector-mvp-guia-nueva` · **Baseline:** `ecaa92746fb30b3b4509fc99ec96842ffc806280`. **Sin cambios de código -- bloque de datos/simulación, no se commitea nada.**

### Fase A/B: fuentes y respaldo

- CSV documental productivo: `AppData\Local\Atlas\datos\procesamiento\analisis_completo_guias.csv` (1177 filas, sha256 `35eb44d1…`). Reporte productivo: `AppData\Local\Atlas\datos\reportes\actual\` (5 archivos, `viajes.csv` 574 viajes, sha256 `d1ff2d7b…`).
- Respaldo íntegro en `C:\Users\Jjjc0508\Desktop\Atlas\backups_produccion\20260812_084914_pre_s3\` -- verificado byte a byte por sha256 contra el original, los 6 archivos idénticos.

### Fase C/D/E: clasificación y reclasificación conservadora

- **Hallazgo clave:** con las columnas disponibles en el CSV histórico (sin OCR nuevo) es posible reconstruir con confianza total los motivos de AUSENCIA (`GUIA_AUSENTE`, `TRANSPORTE_AUSENTE`, `CLIENTE_AUSENTE`, `CHOFER_AUSENTE`, `DOCUMENTO_DEGRADADO`, `MATERIAL_AUSENTE`) -- dependen solo del valor final del campo. **No** es posible reconstruir con confianza los motivos de CORROBORACIÓN (`*_SIN_CORROBORAR`, `PATENTE_*`) sin saber cómo se obtuvo cada campo -- esa información no sobrevive en este esquema histórico (mismo hallazgo ya documentado en ESTADOS S2, columnas `_fuente` no confiables).
- Política aplicada: `indicador_revision_s3 = REVISAR` si hay un motivo de ausencia reconstruible **O** si el documento ya era `REVISAR` en el original (se preserva la cautela histórica sin inventar el motivo fino -- se marca `HISTORICO_SIN_MOTIVO_RECONSTRUIBLE`, explícito, nunca oculto). Nunca se relaja a `OK` sin evidencia.
- Resultado: **1177 documentos clasificados** -- 915 con motivo de ausencia reconstruible directamente, 262 con revisión histórica preservada explícitamente sin motivo fino. **0 en categoría C (requiere reproceso)** -- la política conservadora hace innecesario reprocesar para no inventar ni perder cautela real.

### Fase F/G: simulación completa

- Candidato generado en `estado_revision_eval\s3\simulado\` con el pipeline real (`generar_reporte_viajes`, código actual `ecaa927`, incluye S2/S2.2/I1).
- **576 viajes** (574 histórico + 2 del set reciente, que en el CSV histórico tenían `numero_transporte="No encontrado"` y por tanto no formaban viaje -- se usó su fila ya reprocesada con código actual, ver Fase I).
- **73 CONFIRMADO / 503 REQUIERE_REVISION** -- consistente con el hallazgo ya establecido en ESTADOS S1 (73/501 sobre 574; +2 viajes y +2 REQUIERE_REVISION por el set reciente).
- **417 viajes cambian CONFIRMADO -> REQUIERE_REVISION, 0 en sentido contrario, 157 sin cambio.**

### Fase H: validación de muestra

- 30 viajes muestreados del grupo `CONFIRMADO -> REQUIERE_REVISION`: **30/30 con motivo real, directamente verificable en los datos ya extraídos** (ausencia de campo clave, documento degradado, o conflicto real entre documentos del mismo transporte -- ej. transporte `0000279246`: `CONFLICTO_CHOFER` + `CONFLICTO_OBRA_DESTINO` real entre 3 documentos). **0 cambios incorrectos, 0 no determinables.**

### Fase I/J/K: O1, rutas, multiguía

- **O1 preservado:** el set reciente (guías 463594, 463630) conserva `peso_total_viaje_kg`/`hora_entrada_aza`/`hora_salida_aza`/`permanencia_minutos` reales. El resto (574 históricos) queda vacío -- nunca se inventó ni se reprocesó para llenar huecos.
- **E1/rutas:** todos los campos de ruta (`planta_origen_nombre`, `distancia_km`, `estado_ruta`, etc.) quedan vacíos en los 576 viajes -- correcto, nunca hubo un `calculador_rutas` real conectado a una corrida sobre este corpus, no se inventó evidencia.
- **Multiguía:** verificado con datos reales que la agrupación/conflictos funcionan correctamente (ver caso `0000279246` arriba). **Hallazgo aparte, real, fuera de alcance de este bloque:** la guía `384674` aparece **3 veces** en el CSV histórico bajo archivos distintos (`384674.jpg`, `IMG-20250623-WA0020.jpg`, `IMG-20250624-WA0033.jpg`) con `numero_transporte` inconsistente entre copias -- duplicación real de fotos del mismo documento físico, documentada pero no corregida aquí (requiere su propio bloque de deduplicación).

### Fase L/M: dataset candidato y dry run

- Candidato con esquema completo actual (34 columnas), validado programáticamente contra las columnas mínimas que exige el parser de Desktop (`viaje_id`, `numero_transporte`, `fecha`, `estado`) -- presentes, esquema consistente en las 576 filas.
- **Dry run limitado a verificación estructural** -- este entorno no permite lanzar la aplicación Electron de Desktop para una prueba visual real; no se afirma haber validado la UI.

### Fase N — decisión: simulación aprobada, migración diferida

Los 10 criterios de cierre técnicos se cumplen (respaldo verificado, simulación completa, 0 cambios incorrectos, 574->576 explicado, esquema válido, candidato estructuralmente legible, suite verde, rollback disponible por backup, sin sorpresas en los datos). **Se consultó explícitamente antes de escribir producción** dado el volumen del cambio (417 viajes pasan a requerir revisión de golpe) -- decisión: **no migrar todavía**, dejar el candidato validado disponible para cuando se decida absorber ese volumen de revisión operativamente.

### Producción

**No modificada.** Hashes idénticos a los de antes de este bloque.

---

## 2026-08-12 — Cierre: IDENTIDAD I1 (auditoría de normalizaciones hardcodeadas) — APROBADO. Cierra la serie ESTADOS S2/S2.1/S2.2/I1

**Rama:** `lector-mvp-guia-nueva` · **Baseline previo:** `8029ee4546305511ac8ad641354fa2b3cc306423`. **Este bloque SÍ committea** (junto con S2/S2.2, ver abajo).

### Inventario completo de reglas hardcodeadas de identidad (`atlas_core/extractor.py`)

Confinado por completo a `extractor.py` -- no se encontró ningún patrón equivalente en el resto de `atlas_core/` (catalogos.py, procesamiento_masivo.py, gestor_viajes.py, reporte_viajes.py, clasificador_material.py, rutas/).

| Regla | Función | Campo | Condición | Clasificación | Acción |
|---|---|---|---|---|---|
| SIGRO → "EMPRESA CONST SIGRO" | `normalizar_obra_destino` | obra_destino | subcadena en valor ya capturado | **E — incorrecta** (probado: guía 383295 real decía "CONSTRUCTORA SIGRO SA") | **Retirada** |
| SIGRO → "EMPRESA CONST SIGRO" | `buscar_obra_destino` (fallback) | obra_destino | subcadena en TODO el documento | **E — incorrecta** | **Retirada** |
| POCURO/PCCURO/CCNSIRUCIO/COYSIRUC → "CONSTRUCTORA POCURO SPA" | `normalizar_obra_destino` | obra_destino | subcadena en valor ya capturado | **D — inferencia no corroborada** (mismo patrón de riesgo que SIGRO, sin evidencia real de necesidad) | **Retirada** |
| POCURO/PCCURO/CCNSIRUCIO → "CONSTRUCTORA POCURO SPA" | `buscar_obra_destino` (fallback) | obra_destino | subcadena en TODO el documento | **D** | **Retirada** |
| AMERICAN SCREW → "AMERICAN SCREW CHILE SPA" | `normalizar_obra_destino` | obra_destino | subcadena en valor ya capturado | **B — corrección OCR/formato determinista** | Retirada de aquí (redundante; el fallback de abajo la cubre) |
| AMERICAN SCREW → "AMERICAN SCREW CHILE SPA" | `buscar_obra_destino` (fallback) | obra_destino | subcadena en TODO el documento | **B**, evidencia real: guía histórica 462474 (`tests/test_atlas.py`), layout con etiqueta y valor en bloques de OCR separados | **Conservada**, acotada a esta empresa |
| AMERICAN SCREW → cliente fijo | `buscar_cliente` (atajo) | cliente | subcadena en TODO el documento, sin pasar por SEÑOR(ES) | **B**, evidencia real: guía 464479 y la 462474 | **Conservada**, acotada |
| PRODALA/PRODALAK/PRODALAM → "PRODALAM SA" | `normalizar_cliente` | cliente | subcadena en valor ya capturado (campo SEÑOR(ES) real) | **B — corrección OCR determinista**, evidencia real: 21 variantes de OCR distintas confirmadas en el CSV masivo, un solo RUT real detrás (93.772.000, `empresas.json`) | **Conservada** |
| PRODALA/PRODALAK/PRODALAM → cliente fijo | `buscar_cliente` (atajo) | cliente | subcadena en TODO el documento | **B**, evidencia real: guía 464493 (SEÑOR(ES) no capturable por el regex de layout, pero "PRODALAM SA" sí aparece en el texto) | **Conservada**, acotada |
| ACMA → "ACMA SA" | `normalizar_cliente` | cliente | `\bACMA\b` sobre valor ya capturado | **A/B — segura**, acotada por límite de palabra, evidencia catalogada (RUT 921900007) | **Conservada** |
| ACMA → cliente fijo | `buscar_cliente` (atajo) | cliente | `\bACMA\b` en TODO el documento | **D**, sin evidencia real de que haga falta (solo 2 apariciones en todo el CSV masivo, ya resueltas por el regex de layout) | **Retirada** |
| ACMA RUT "92"+"190" → "92.190.000-7" | `buscar_rut_cliente` | RUT del cliente | co-ocurrencia de 2 subcadenas de 2-3 dígitos en TODO el documento | **E — incorrecta** (subcadenas comunes, sin relación posicional) | **Retirada** (queda el patrón contextual "ACMA...INDUSTRIAS", ese sí conservado) |
| "18098153" → "18098153-5" | `buscar_rut_chofer` | RUT del chofer | subcadena de 8 dígitos en TODO el documento, sin comentario | **E — incorrecta** | **Retirada** |
| "PAIRICIO" → "PATRICIO" | `normalizar_chofer` | chofer | corrección de un carácter sobre valor ya identificado como chofer | **A — normalización sintáctica segura** | Conservada (no es sustitución de identidad, es corrección OCR de un nombre ya acotado al campo) |
| 7 bloques completos por número de guía exacto (462491, 462793, 462833, 461878, 462544, 462871, 462395) | `extraer_datos` (fallbacks históricos) | todos los campos | `numero_guia == "XXXXXX" or "XXXXXX" in texto` | Categoría propia, gateada por número de guía (identificador fuerte, no nombre de empresa por subcadena) | **Fuera de alcance de este bloque** -- reportados, no tocados (mismo criterio ya aplicado en Bloque O1: solo 462491 corregido con evidencia visual directa; los otros 6 requieren imagen real para auditar con el mismo rigor, disponible ahora en el corpus localizado pero no revisada en este bloque) |

**Total: 14 reglas de identidad por subcadena inventariadas** (más los 7 bloques de fallback por guía, categoría aparte) — **6 retiradas, 8 conservadas con evidencia**.

### Caso SIGRO / 383295 -- confirmado y corregido

- Hallazgo real (destinos.json vs empresas.json): el mismo RUT normalizado `93772000` aparece con nombres DISTINTOS en los dos catálogos (`empresas.json` → "PRODALAM SA"; `destinos.json`, código `0002012245` → "EMPRESA CONST SIGRO") -- inconsistencia real de datos, **no corregida aquí** (fuera de alcance tocar catálogos sin autorización explícita).
- Evidencia real cruzada (`G:\Mi unidad\MBT\informe lunes\`, guía 454346 y 461066, ambas con cliente PRODALAM SA): el documento SÍ imprime literalmente "EMPRESA CONST SIGRO SA" -- la regla no era incorrecta para estos casos.
- Evidencia real de la guía 383295 (cliente SALOMON SACK SA, no PRODALAM): el documento imprime "CONSTRUCTORA SIGRO SA" -- un texto distinto, que la regla destruía igual.
- Evidencia real adicional (guías 383738, 462210): la recuperación geométrica post-fix produce un tercer valor real, "EMPRESA CONSTRUCTORA SIGRO S" -- ni el nombre "oficial" del catálogo ni el de 383295, confirmando que colapsar todo en un único string fijo perdía variación real.
- **Resultado tras el fix (verificado con la imagen real, guía 383295):** `obra_destino = "CONSTRUCTORA SIGRO SA"` (el valor documental real, preservado), `indicador_revision = REVISAR`, `motivos_revision_documento = OBRA_DESTINO_SIN_CORROBORAR`, `metodos_recuperacion_documento = CONTEXTUAL | GEOMETRICO`. Ya no hay sustitución silenciosa.

### AMERICAN SCREW, POCURO, PRODALA/PRODALAM, ACMA -- resultados

- **AMERICAN SCREW:** 15 ocurrencias reales (9 cliente + 6 obra_destino), todas consistentes (empresa que recibe en su propia planta) -- regla conservada, acotada, sin evidencia de daño.
- **POCURO:** 4 ocurrencias reales en obra_destino, siempre "CONSTRUCTORA POCURO SPA" -- pero sin evidencia de que el fallback por subcadena (a diferencia de AMERICAN SCREW) sea realmente necesario; verificado con 2 guías reales (391473, 391474) que la recuperación geométrica post-fix ya resuelve el valor correcto sin el atajo, con el motivo correspondiente. Retirada.
- **PRODALA/PRODALAM:** 128 ocurrencias reales de cliente, 21 variantes de OCR distintas confirmadas, un solo RUT real. Regla conservada en `normalizar_cliente` (segura) y, con evidencia real directa (guía 464493), también conservada -- acotada -- como atajo en `buscar_cliente`.
- **ACMA:** solo 2 ocurrencias reales en todo el CSV masivo, ambas ya resueltas por el regex de layout normal -- el atajo de `buscar_cliente` se retiró sin pérdida de cobertura; el fallback débil de RUT ("92"+"190") se retiró por ser evidentemente inseguro (subcadenas comunes sin relación posicional).

### Validación focal real (sin reprocesar el corpus completo)

9 documentos reales verificados con OCR focal (no 196, no 1172): 383295 (antes/después), 454346, 461066, 383738, 462210, 391473, 391474, más las 5 relajaciones ya conocidas de S2/S2.2 (383620, 462491, 464479, 464493, y la propia 383295). **0 identidades incorrectas encontradas tras el fix.**

### Revalidación de relajaciones S2/S2.2 conocidas

- **383295:** ya NO es una relajación falsa -- pasó a `REVISAR` correctamente, con el valor documental real preservado.
- **383620, 462491, 464479:** sin cambios, siguen `OK` y correctas.
- **464493:** cambió de `OK` a `REVISAR` -- **no es una regresión**: el cliente ahora se resuelve correctamente ("PRODALAM SA", antes "No encontrado" por la eliminación inicial del atajo, restaurada tras evidencia real), y el destino ("EMPRESA CONST SIGRO SA", real y probablemente correcto) ahora pasa honestamente por el mismo camino de recuperación geométrica sin corroborar que ya usan el resto de los documentos -- antes quedaba "OK" solo porque el propio hardcode de SIGRO lo resolvía como si fuera texto lineal confiable, ocultando la incertidumbre real. Es el comportamiento correcto, no un defecto.

### Archivos modificados en este bloque

- `atlas_core/extractor.py`: `normalizar_obra_destino`, `buscar_obra_destino`, `buscar_cliente`, `buscar_rut_cliente`, `buscar_rut_chofer`.
- `tests/test_identidad_i1.py` (nuevo, 12 tests).

### Tests y suite

- 12 tests nuevos, todos verdes. Suite completa: **730 → 742 passed**, 0 regresiones (incluye el test histórico `test_atlas.py::test_formato_segunda_guia`, protegido explícitamente).

### Veredicto: IDENTIDAD I1 APROBADO

Los 11 criterios de cierre se cumplen: inventario completo; cada regla clasificada; SIGRO corregido; 383295 corregida; ninguna sustitución que queda sin justificación explícita en código; regresiones históricas protegidas (test real preservado + nuevos tests); validación focal real con evidencia; relajaciones S2 conocidas revalidadas; 0 cambios incorrectos; suite verde; producción intacta.

### Cierre de la serie ESTADOS S2 / S2.1 / S2.2 / IDENTIDAD I1

Con este bloque se cierra la evolución completa: separación calidad/trazabilidad del dato (S2), validación a escala sobre corpus real localizado en `G:\Mi unidad\MBT\informe lunes\` (S2.1), cobertura del enriquecimiento por catálogo (S2.2), y ahora la causa raíz real (normalizaciones hardcodeadas en el extractor base, I1). El caso 383295, que atravesó las 4 etapas antes de resolverse correctamente, queda documentado de punta a punta como caso de estudio de la disciplina de diagnóstico exigida en todo este arco.

---

## 2026-08-11 — Cierre: ESTADOS S2.2 (cubrir enriquecimiento de catálogo) — NO APROBADO, 383295 tenía otra causa raíz

**Rama:** `lector-mvp-guia-nueva` · **Baseline previo:** `8029ee4546305511ac8ad641354fa2b3cc306423`. **Sin commit nuevo.**

### Implementado (funciona correctamente para lo que cubre)

- **`MetodoObtencionDocumento.CATALOGO`** (nuevo) + trazabilidad y corroboración de `enriquecer_datos_con_catalogos()` en `procesar_archivo()`: se toma un snapshot de `cliente`/`chofer`/`obra destino` justo antes de llamarla y se compara contra el valor final.
  - **Cliente/chofer:** `buscar_empresa_por_rut`/`buscar_chofer_por_rut` solo cambian el valor con coincidencia EXACTA de RUT contra el catálogo -- corroboración fuerte por diseño (mismo criterio que el RUT geométrico ya usado en S2). Se registra método `CATALOGO`, sin motivo de revisión.
  - **Obra destino:** `_buscar_destino_en_textos` resuelve por "COD DESTINATARIO" -- sin una señal de corroboración equivalente al RUT, y sin que el campo "OBRA DESTINO" del documento tenga por qué haber tenido nunca un valor propio. Deliberadamente conservador: **cualquier cambio de este campo por catálogo agrega `OBRA_DESTINO_SIN_CORROBORAR` y fuerza revisión, sin excepción** (campo vacío o con valor documental contradicho por catálogo, da igual).
  - Patente: ya cubierta por el bloque P2 existente (se revalida el valor final tras el enriquecimiento).
- 14 tests nuevos (`tests/test_estados_s2_2.py`), todos verdes: RUT exacto de cliente/chofer confirma sin revisión; sin coincidencia de RUT el catálogo no toca el campo; destino vacío completado por catálogo fuerza revisión; destino documental que coincide con catálogo no agrega motivo; destino documental contradicho por catálogo fuerza revisión; patente exacta/corrección OCR segura/ambigua (no regresión); trazabilidad y motivo persistidos; combinación GEOMETRICO+CATALOGO sin duplicar motivo; regresión sintética del patrón real de 383295. Suite completa: **716 → 730 passed**, 0 regresiones.

### Hallazgo crítico: la hipótesis de causa raíz de ESTADOS S2.1 para la guía 383295 era INCORRECTA

- Se revalidaron los mismos 196 documentos reales (46 de S2 + 150 de S2.1) con el código S2.2. **383295 sigue exactamente igual: `obra_destino="EMPRESA CONST SIGRO"`, `indicador_revision=OK`, sin ningún motivo.**
- Diagnóstico directo (`extraer_datos()` aislado, sin geometría ni catálogo): la guía 383295 **YA llega con `obra destino = "EMPRESA CONST SIGRO"` desde la extracción lineal pura** -- antes de que corra cualquier lógica de S2/S2.2. La causa real es `atlas_core/extractor.py: normalizar_obra_destino()` (código de un bloque muy anterior, no de ESTADOS S1/S2), que tiene una regla **hardcodeada**: cualquier valor de obra destino que contenga la subcadena `"SIGRO"` se reemplaza incondicionalmente por `"EMPRESA CONST SIGRO"`. La guía real dice literalmente `"OBRA DESTINO: CONSTRUCTORA SIGRO SA"` (leído correctamente por el OCR, confirmado en el texto crudo) -- pero la normalización lo canoniza a una empresa distinta ("EMPRESA CONST SIGRO", que sí existe como entidad real y catalogada, pero no es la misma sociedad que "CONSTRUCTORA SIGRO SA").
- **Esto está completamente fuera del alcance de `enriquecer_datos_con_catalogos()`** -- ocurre en la primera línea de `procesar_archivo()` (`datos = extraer_datos(textos, ...)`), antes de que exista ningún snapshot ni ninguna lógica de corroboración de S2/S2.2 que pueda interceptarlo. Ninguna corrección dentro del alcance de S2.2 podía resolver este caso.
- **Riesgo de la misma categoría, no auditado todavía:** `normalizar_obra_destino()` tiene reglas equivalentes para `"AMERICAN SCREW"` y `"POCURO"/"PCCURO"/"CCNSIRUCIO"/"COYSIRUC"`; `normalizar_cliente()`/`buscar_cliente()` tienen reglas equivalentes para `"PRODALA"/"PRODALAK"/"PRODALAM"`, `"AMERICAN SCREW"` y `"ACMA"`. No se auditó su exactitud real en este bloque (fuera de alcance explícito -- "no rediseñar el resto de S2").
- **No se corrigió bajo presión** -- siguiendo el mismo principio ya aplicado en S2.1, se documenta el hallazgo (con causa raíz correcta esta vez, verificada trazando la ejecución real, no solo leyendo el código) y se detiene.

### Veredicto S2.2: NO APROBADO

1. 383295 corregida: **NO** (causa raíz distinta a la atacada por este bloque).
2. Todas las relajaciones de los 196+ casos correctas: **NO** (383295 sigue incorrecta; las otras 2 relajaciones encontradas en la revalidación -- guía 383620 y guía de control 462491 -- sí son correctas).
3. 0 relajaciones incorrectas relevantes: **NO**.
4. Vías de enriquecimiento de catálogo cubiertas: **SÍ**, para lo que le correspondía a este bloque.
5. Suite completa verde: **SÍ** (730 passed).
6. Producción intacta: **SÍ**.

### Propuesta para el siguiente bloque (no numerado aquí -- fuera del alcance de "S2")

Auditar con evidencia real las reglas de normalización hardcodeadas por subcadena en `atlas_core/extractor.py` (`normalizar_obra_destino`, `normalizar_cliente`, `buscar_cliente`) -- verificar si cada una sigue siendo válida (mismo problema exacto que ya se resolvió una vez para "SIGRO" en algún momento anterior podría estar generalizada incorrectamente hoy) y, si corresponde, exigir una señal de corroboración (RUT, código único) antes de aplicar la sustitución, en vez de un simple "contiene la subcadena X".

---

## 2026-08-11 — Cierre: ESTADOS S2.1 (validación de escala sobre corpus real) — NO APROBADO, defecto real encontrado, detenido para S2.2

**Rama:** `lector-mvp-guia-nueva` · **Baseline previo:** `8029ee4546305511ac8ad641354fa2b3cc306423` (sin commit de ESTADOS S2 todavía). **Sin commit nuevo.**

### Corpus real localizado

- CSV masivo original (sha256 idéntico al del manifiesto de migración, `39237967e4…`): `G:\Mi unidad\MBT\Proyecto atlas\Proyecto-Atlas-main - copia de Claude\output\analisis_completo_guias.csv`.
- **Corpus de imágenes real: `G:\Mi unidad\MBT\informe lunes\`** — 1172 archivos, coincidencia exacta de nombre con 1172/1177 filas del CSV masivo (99.6%; los 5 restantes: 3 archivos sin imagen localizada + 2 ya conocidos de otra ruta). `elementos_no_migrados_2026-07-28.md` confirma que las imágenes del corpus nunca se migraron a la instalación Desktop -- solo el CSV extraído sobrevivió ahí.

### Procesamiento real y hallazgo decisivo

- Se procesaron **150 documentos reales** de `informe lunes` con el código S2 (OCR real, PaddleOCR) -- se detuvo antes de completar el corpus completo porque el patrón ya era estadísticamente claro y, más importante, porque apareció un hallazgo que exige detenerse (ver abajo), no seguir acumulando muestra.
- **Solo 4 relajaciones reales en total** (2 de la muestra de 46 de ESTADOS S2 + 2 de estos 150 nuevos) sobre 196 documentos reales evaluados -- tasa ~2%. A esa tasa, ni el corpus completo (1172) alcanzaría con margen las 30 relajaciones pedidas.
- **De las 4 relajaciones, 3 se verificaron 100% correctas** contra la imagen real (464479, 464493, guía 383620 -- cliente/destino/chofer/RUT/patentes coinciden exactamente).
- **1 de las 4 (guía 383295) resultó INCORRECTA**: `obra_destino` quedó como `"EMPRESA CONST SIGRO"` con `indicador_revision=OK` (sin ningún motivo), pero el campo `OBRA DESTINO` de la guía real está **en blanco** -- el valor viene de una vía completamente distinta a la recuperación geométrica que S2 audita.
- **Causa raíz identificada:** `atlas_core/catalogos.py: enriquecer_datos_con_catalogos()` (mecanismo preexistente, anterior a ESTADOS S1/S2) busca el texto completo del documento contra el catálogo `destinos.json` (`_buscar_destino_en_textos`) y **sobrescribe `obra destino`/`cliente`/`chofer`/`patente` con el nombre canónico del catálogo si encuentra coincidencia -- sin pasar nunca por `_extraer_asociaciones_geometricas` ni por ninguna de las banderas que ESTADOS S2 audita** (`campos_geometricos_sin_corroborar`). Este documento en particular solo se volvió visible como "relajación" porque el fix del bug de variable obsoleta de `numero_guia_actual` (incluido en el mismo cambio de S2, ver abajo) dejó de forzar revisión por guía ausente -- exponiendo un problema de calidad preexistente que **ni el código viejo ni el nuevo S2 detectaban**.
- **Efecto colateral identificado del propio cambio de S2:** al corregir `procesar_archivo()` para que `valores_clave` use el valor de `numero_guia` YA recuperado por el mecanismo contextual (antes usaba una variable obsolescente, pre-recuperación), documentos con guía recuperada por contexto dejan de forzar `GUIA_AUSENTE` -- correcto en sí mismo, pero como efecto secundario deja de "enmascarar" otros problemas de calidad no relacionados (como el de destino de este caso).

### Decisión: NO corregir silenciosamente -- detener para ESTADOS S2.2

Siguiendo la instrucción explícita de este bloque, no se intentó parchar `enriquecer_datos_con_catalogos()` ni la clasificación de destino bajo presión. Se documenta el hallazgo y se detiene aquí.

### Veredicto S2.1: NO APROBADO

1. Mínimo 30 relajaciones reales: **NO** (4/196, estructuralmente inalcanzable a esta tasa incluso con el corpus completo).
2. 0 relajaciones incorrectas relevantes: **NO** (1/4 incorrecta, causa real identificada).
3. Mínimo 15 revisiones conservadas legítimas: **SÍ** (15 revisadas, todas con motivo bloqueante real).
4. Modelo método/calidad sostenido con evidencia: **parcial** -- sostenido para los métodos que sí audita (geometría de cliente/chofer/patente, fuzzy, homologación, consenso focal); **no cubre** el mecanismo de enriquecimiento por catálogo de `enriquecer_datos_con_catalogos()`, que puede alterar los mismos campos por una vía no auditada.
5. Suite completa verde: **SÍ** (716 passed).
6. Producción intacta: **SÍ**.

### Propuesta para ESTADOS S2.2 (siguiente bloque, no implementado aquí)

Extender el modelo de motivos/métodos de S2 para que también cubra `enriquecer_datos_con_catalogos()`: si esa función cambia `cliente`/`obra_destino`/`chofer`/`patente` respecto del valor que traía `datos` al entrar, debe registrar su propio método (`CATALOGO` o similar) y, si el cambio no está corroborado por una señal independiente equivalente a las ya usadas en S2, su propio motivo de revisión -- en vez de dejarlo completamente invisible al indicador de calidad, como ocurre hoy (antes y después de S2). Revisar además si `_buscar_destino_en_textos` debería exigir una correspondencia más estricta antes de sobrescribir un campo que en el documento real está vacío.

---

## 2026-08-11 — Cierre: ESTADOS S1 (diagnóstico) + ESTADOS S2 (separar calidad del dato de trazabilidad del método) — NO APROBADO (criterio de muestra), código y tests listos

**Rama:** `lector-mvp-guia-nueva` · **Baseline previo:** `8029ee4546305511ac8ad641354fa2b3cc306423` (cierre de O1.2). **Sin commit** (ver veredicto).

### ESTADOS S1 — diagnóstico del desfase `indicador_revision` (sin cambios de código)

- Auditoría completa en `estado_revision_eval/` (fuera del repo). Causa raíz identificada con evidencia de commit: `viajes.csv` productivo (574 viajes, 2026-07-28) se generó con una versión de `agrupar_viajes()` que **nunca propagaba** `indicador_revision` de documento a viaje -- el commit `cb6dad4` ("propagar revisión desde documentos a viajes") se hizo **un día después**. El CSV masivo actual (1177 documentos, 1033 REVISAR) refleja el motor de ~2026-08-06, que acumuló ~20 commits de recuperación geométrica/fuzzy entre medio, todos marcando REVISAR por el mero uso del método.
- Matriz de 4 grupos: 442/730 documentos (60.5%) están `DOCUMENTO_REVISAR / VIAJE_CONFIRMADO` -- el grupo crítico. Muestra de 30: ~73% revisión legítima, ~27% sobremarcado técnico (recuperación correcta y corroborable, pero sin trazabilidad separada de la calidad del dato).
- Conclusión: **C -- MEZCLA_DE_AMBOS**. Producción no tocada.

### ESTADOS S2 — separar CALIDAD DEL DATO de TRAZABILIDAD DEL MÉTODO

- **`atlas_core/procesamiento_masivo.py`:** nuevos `MetodoObtencionDocumento` (`GEOMETRICO`, `CONTEXTUAL`, `FUZZY`, `HOMOLOGADO`, `CORREGIDO`, `FOCAL` -- puramente informativo) y `MotivoRevisionDocumento` (`GUIA_AUSENTE`, `TRANSPORTE_AUSENTE`, `CLIENTE_AUSENTE`, `CHOFER_AUSENTE`, `DOCUMENTO_DEGRADADO`, `CLIENTE_SIN_CORROBORAR`, `CHOFER_SIN_CORROBORAR`, `OBRA_DESTINO_SIN_CORROBORAR`, `PATENTE_SIN_HOMOLOGAR`, `PATENTE_AMBIGUA`, `MATERIAL_AUSENTE` -- este último informativo/no bloqueante, mismo criterio ya establecido en Bloque O1 para peso/horas).
- `procesar_archivo()` ya no colapsa el uso de un método en un único booleano: acumula `motivos_documento` (bloqueantes) y `metodos_documento` (trazabilidad) por separado. `indicador_revision` se deriva de si hay algún motivo bloqueante -- conserva exactamente su semántica REVISAR/OK de siempre (compatibilidad).
- **Criterio de corroboración concreto, por campo** (ninguno relajado sin una segunda señal independiente):
  - Patente: homologación `ALIAS`/`CORRECCION_OCR_SEGURA`/`COINCIDENCIA_EXACTA` contra catálogo -> corroborada, no fuerza revisión. Solo `AMBIGUO` fuerza `PATENTE_AMBIGUA`. Geométrica sin homologar -> `PATENTE_SIN_HOMOLOGAR`.
  - Chofer: geométrico + RUT que coincide en catálogo, o fuzzy `COINCIDENCIA_SEGURA` (ya exige margen sobre el resto) -> corroborado. Geométrico sin ninguna de las dos -> `CHOFER_SIN_CORROBORAR`.
  - Cliente: geométrico + RUT con dígito verificador válido (`validar_rut_chileno`) -> corroborado. Sin RUT válido -> `CLIENTE_SIN_CORROBORAR`.
  - Número de guía (contextual), transporte (consenso focal), fecha (consenso focal): corroborados por diseño (exigen candidato único/consenso de >=2 lecturas concordantes) -- nunca fuerzan revisión por sí solos.
  - Obra destino: **deliberadamente sin relajar** -- no existe hoy una señal de corroboración independiente equivalente al RUT de cliente; geométrico siempre fuerza `OBRA_DESTINO_SIN_CORROBORAR`. Queda como trabajo futuro explícito, no una omisión.
  - Documento degradado (>=5/8 campos clave ausentes) y campos clave ausentes (guía/transporte/cliente/chofer): sin cambios, siguen forzando revisión -- son incertidumbre real, no trazabilidad de método.
- **`atlas_core/gestor_viajes.py`: sin cambios de código.** `_documento_desde_fila()` ya copiaba toda la fila a `evidencia`, así que `motivos_revision_documento`/`metodos_recuperacion_documento` llegan intactos al viaje sin trabajo adicional (test de confirmación agregado).
- **Columnas nuevas:** `motivos_revision_documento`, `metodos_recuperacion_documento` -- agregadas al final de `COLUMNAS` (backward-compatible).

### Hallazgo relevante durante Fase I: las columnas `_fuente` del CSV legado no son un proxy confiable

- Al intentar reclasificar los 1177 documentos existentes sin OCR (usando `cliente_fuente`/`obra_destino_fuente`/`chofer_fuente`, ya usadas en ESTADOS S1), se encontró que **129/144 documentos originalmente "OK" ya llevaban fuente `GEOMETRICO`/`CATALOGO_FUZZY`** -- contradice la premisa de que ese método forzaba REVISAR en la versión que generó ese CSV. Conclusión: esas columnas no reflejan de forma confiable qué causó el `indicador_revision` original en este dataset específico -- una reclasificación por columnas proxy sobre este CSV **no es confiable** y se documenta como tal (artefacto igual guardado en `estado_revision_eval/s2/`, con la limitación explícita).
- **Validación real, confiable, en su lugar:** se reprocesaron con el código S2 real las 46 guías reales ya conocidas de bloques anteriores (30 de `datos_privados/muestra_fechas_30/` + 16 de O1/O1.1), comparando contra el mismo código SIN S2 (vía `git stash`). Resultado: **45 REVISAR / 1 OK (antes) -> 43 REVISAR / 3 OK (después)** -- solo 2 relajaciones reales disponibles localmente (`464479`, `464493`), ambas **verificadas visualmente contra la imagen real**: todos los campos (cliente, obra destino, chofer, RUT, patentes) coinciden exactamente. 0 relajaciones incorrectas. 15 casos REVISAR conservados revisados: todos con motivo bloqueante legítimo y real (ninguno se sostiene solo en `MATERIAL_AUSENTE`).
- La razón de que el impacto real sea modesto (no las docenas esperadas): `OBRA_DESTINO_SIN_CORROBORAR` -- deliberadamente conservador, sin corroboración disponible -- resultó ser el motivo dominante en la práctica sobre este muestreo real, más que cliente/chofer/patente (que sí tienen corroboración y sí se relajan cuando aplica).

### Tests

- `tests/test_estados_s2.py` (nuevo, 8 tests -- los "casos reales obligatorios" pedidos: geometría corroborada, homologación SD6486->SB6486, chofer antes/después de catálogo, cliente ausente real, conflicto multiguía de patente, peso/hora sin forzar revisión, destino ambiguo sin corroborar).
- 10 tests existentes actualizados (ya no esperan REVISAR donde la única causa era un método ahora corroborado o `MATERIAL_AUSENTE`) + 1 test nuevo de compatibilidad de columnas + 1 test nuevo en `tests/test_gestor_viajes.py` (motivos/métodos se preservan en `evidencia`).
- Suite completa: **706 -> 716 passed**, 0 regresiones.

### Veredicto: NO APROBADO (estrictamente, por criterio de muestra) -- implementación y tests listos

Se cumplen 8/10 criterios de cierre obligatorios (calidad != método; motivos explícitos; recuperación corroborada no fuerza revisión; ambigüedad/ausencia/conflicto preservados; 0 relajaciones incorrectas; suite verde; producción intacta; 15 REVISAR conservados revisados). **No se cumple el mínimo de 30 relajaciones reales revisadas** (solo 2 disponibles localmente -- el corpus de 1177 documentos vive en Google Drive externo, no accesible en este entorno) **ni una reclasificación confiable de los 1177** (columnas proxy demostradas no confiables). Sin commit ni push -- código y tests quedan en el árbol de trabajo para revisión.

---

## 2026-08-11 — Cierre: OPERACIÓN O1.1 (validación ciega, NO APROBADO) + O1.2 (corrección dirigida, APROBADO)

**Rama:** `lector-mvp-guia-nueva` · **Baseline previo:** `4822e9e1e31a9b7e42dbd4c887324bdbdf777159` (cierre de O1)

### O1.1 — validación ciega independiente (metodología, sin cambios de código)

- Muestra independiente de **16 guías reales**: 14 reutilizadas de D2/D3/D3.1/E1 (`ux_r2_sincronizacion/entrada_14_guias/`, nunca usadas para calibrar reglas de peso/hora) + **2 genuinamente nuevas**, halladas en `datos/entradas/` de una instalación Desktop real (`463594` Villagra, `463630` Ñancucheo).
- Metodología: se corrió el pipeline real (`procesar_archivo`) y se **congeló la predicción en JSON antes de mirar cualquier imagen**; solo después se inspeccionó cada imagen visualmente (autoridad final, por encima del ground truth de planillas).
- **Veredicto: O1 NO APROBADO.** 3 patrones reales de falla:
  1. **Hora corrupta con dígitos adyacentes** (`464264`, `463630`): el OCR pega un dígito extra al inicio del valor horario ("112:15:18" en vez de "12:15:18"). Causa raíz exacta, trazada carácter por carácter: el regex anterior `\b([0-2]?\d):([0-5]\d)(?::[0-5]\d)?\b` no tiene límite de palabra (`\b`) entre dos dígitos consecutivos, pero **sí** lo tiene justo después de un `:` — el motor de regex "reinicia" el match ahí, capturando el sub-tramo `"15:18"` como si fuera una hora propia y descartando el `"112:"` corrupto en silencio. Mismo patrón produjo `"29:55"` (hora inválida, >23) en 463630.
  2. **PESO KG con línea intermedia** (`464264`): el ancla exigía adyacencia casi inmediata; una línea no relacionada ("ENTREGA 06.08 08:00 AM") intercalada entre "PESO KG." y su valor real ("17.150,00", que el OCR sí leyó bien) rompía el match — el extractor no encontraba nada (`ERROR_EXTRACTOR`).
  3. **Error OCR puro** (`464367`): el propio motor OCR leyó un dígito equivocado dentro de un valor por lo demás bien formado ("27.410,00" en vez de "27.610,00", 4 en vez de 6) — confirmado comparando la imagen real contra el texto crudo de PaddleOCR. No es un fallo del extractor.
- Política **MULTIGUÍA funcionó correctamente** durante O1.1, sin cambios necesarios.

### O1.2 — corrección dirigida (Fases A-I)

- **`atlas_core/extractor.py` — `buscar_horas()` (patrones 1 y 2 de O1.1):** rediseño "token maximal + match completo". En vez de buscar `\b`-anchored en cualquier posición, se toma cada tramo MAXIMAL de `[\d:]+` como un solo candidato y se exige que el token COMPLETO (nunca un sub-match) calce con `_PATRON_HORA_TOKEN_COMPLETO = ^([01]?\d|2[0-3]):([0-5]\d)(?::[0-5]\d)?$`. Si el token no calza entero (dígito de más al inicio o al final), se descarta completo y se sigue con el siguiente tramo de la ventana — nunca se "recorta" para salvarlo. La validación de rango horario (00-23/00-59/00-59) queda estructuralmente garantizada por las clases de caracteres del propio regex, sin lógica adicional.
  - **Bug adicional descubierto y corregido durante la implementación** (no reportado explícitamente por O1.1, pero expuesto por el fix anterior): el fallback "asumir ENTRADA == SALIDA cuando no hay otro candidato" (ya existente desde O1, legítimo en casos reales como la guía `387789`) reutilizaba ciegamente el valor de ENTRADA también cuando la ventana de SALIDA sí tenía un token, pero corrupto (caso `464264`) — convirtiendo un falso positivo en otro falso positivo distinto (`"09:32"` en vez de `"15:18"`, ambos incorrectos). Corregido con una señal `hubo_corrupto` que solo se activa si el token descartado **contiene ":"** (evidencia real de que se intentó representar una hora) — un tramo de solo dígitos sin ":" (p. ej. un Nro. Transporte cayendo dentro de la ventana, caso real guía `387789`) nunca cuenta como corrupción. Esta distinción fue necesaria porque la primera versión del fix (contar cualquier token no-matcheante como corrupción) introdujo una regresión real en la matriz de 30 guías (387789 pasó de `EXACTO` a abstención) — detectada y corregida antes de cerrar el bloque.
- **`atlas_core/extractor.py` — `buscar_peso()` (patrón 3 de O1.1, línea intermedia):** tras el ancla `PESO\s*KG\.?`, se busca en una ventana corta y controlada (`_VENTANA_PESO_CARACTERES = 60`) en vez de exigir adyacencia inmediata. `_PATRON_VALOR_PESO` exige al menos un grupo de miles (3 dígitos tras "." o ",") — estructuralmente no matchea fechas ("06.08") ni horas ("08:00") que puedan aparecer en la línea intercalada. Se acepta el valor **solo si hay exactamente 1 candidato** en la ventana; 0 o ≥2 candidatos → abstención (nunca se elige arbitrariamente entre varios).
- **Caso `464367` (error OCR puro, patrón no corregido por instrucción explícita):** no se introdujo ninguna regla que mapee "27410"→"27610" ni ningún ajuste específico de archivo/guía — el extractor sigue reproduciendo fielmente el dígito que el OCR entregó. Se documenta como `ERROR_OCR_REPRODUCIDO`, distinto de `FALSO_POSITIVO_EXTRACTOR`, sin señal generalizable conocida para detectarlo sin arriesgar cobertura en otros casos reales.
- **Tests nuevos:** `tests/test_extractor_peso_horas_o1_2.py`, **15 tests** (mínimo pedido: 12) — horario limpio, sub-match por dígito extra al inicio/al final, hora/minuto/segundo fuera de rango, no-regresión de entrada/salida históricas válidas, PESO KG directo y con línea intermedia, abstención ante múltiples candidatos de peso, no-regresión de conflicto multiguía, corrupción de salida con entrada duplicada (no debe reutilizar entrada), entrada==salida legítimo sin corrupción (no debe abstenerse), y documentación explícita del caso `464367` (el extractor NO lo corrige).
- Suite completa: **691 → 706 passed**, 0 failed.
- **Verificación amplia (fuera del alcance mínimo pedido, hecha por rigor):** re-ejecución completa de la matriz real de 30 guías (`datos_privados/muestra_fechas_30/`, dataset de O1) contra el código YA corregido — resultado **idéntico** al baseline pre-O1.2 (peso: 24 EXACTO/3 abstención/2 incorrecto/1 falso positivo; entrada: 28 EXACTO/2 incorrecto; salida: **30/30 EXACTO**), confirmando 0 regresiones más allá de lo cubierto por los tests unitarios. Esta corrida fue la que expuso y permitió corregir el bug adicional descrito arriba (387789).

### Revalidación ciega O1.2 (Fase H) — mismas 16 guías de O1.1

- Mismo protocolo: pipeline real ANTES de comparar contra la verdad visual ya congelada en O1.1 (`o1_validacion/prediccion_ciega_congelada.json` / matriz), sin editarla. Resultado en `o1_validacion/o1_2_prediccion.json` y `o1_validacion/matriz_validacion_o1_2.json`.
- **`464264`:** peso `17150` = EXACTO (antes `ERROR_EXTRACTOR`, ahora resuelto por la ventana de 60 caracteres). Entrada `09:32` EXACTO. Salida: abstención correcta (`No encontrado`, visual real `12:15`) — antes emitía `15:18` (falso positivo); ahora prefiere abstenerse a adivinar mal. A nivel de **viaje** (transporte `0000351135`, multiguía con `464265`), la hora de salida SÍ se recupera correctamente vía el documento hermano (`12:15`), sin conflicto — verificado con `agrupar_viajes()` real.
- **`463630`:** peso `26857` EXACTO. Entrada `10:05` EXACTO. Salida: abstención correcta (antes emitía `29:55`, hora inválida fuera de rango).
- **`464367`:** peso `27410` sin cambios (visual real `27610`) — `ERROR_OCR_REPRODUCIDO`, documentado, deliberadamente no corregido. Entrada y salida EXACTO.
- **Métricas (16 guías):** PESO 15 EXACTO + 1 ERROR_OCR_REPRODUCIDO, 0 falsos positivos del extractor, precisión bruta 93.8% (15/16), precisión atribuible al extractor 100% (15/15, excluyendo el caso OCR exento explícitamente). ENTRADA 16/16 EXACTO, 100%. SALIDA 14 EXACTO + 2 abstención correcta (cobertura 87.5%, precisión sobre emitidos 100%, 0 falsos positivos). PERMANENCIA igual patrón que SALIDA (deriva de las mismas horas).
- **MULTIGUÍA re-verificada con los 2 transportes reales** tras el fix: `0000351135` (464264+464265) y `0000352241` (464494+464495) — ambos consolidan correctamente (peso sumado, hora única, sin conflicto espurio); el test de conflicto (`CONFLICTO_HORA_SALIDA`) sigue disparando cuando corresponde.
- **Veredicto Fase I: O1.2 APROBADO** — HORA ENTRADA y HORA SALIDA con 0 falsos positivos y precisión 100% (≥95%); PESO con 0 falsos positivos del extractor y precisión 100% atribuible al extractor (el único caso restante, `464367`, es el error OCR puro explícitamente exento); MULTIGUÍA sigue funcionando correctamente.

### Fase J — reproceso del set reciente (parcial, con hallazgo relevante)

- **Set reciente identificado:** las 2 guías en `datos/entradas/` de la instalación Desktop real (`AppData\Local\Atlas`) aún no reflejadas en `viajes.csv` (`463594`, `463630`) — el resto del CSV masivo (1175 filas / **574 viajes** en `viajes.csv`) es histórico.
- **Backup completo tomado antes de cualquier cambio:** `backups_reportes/20260811_o1_2_pre_reproceso_reciente/` (`actual/`, `procesamiento/`, `entradas/` de la instalación real).
- Las 2 guías se reprocesaron con el código O1.2 y dieron **exactamente los mismos valores que la Fase H** (determinismo confirmado): `463594` peso=12367/entrada=07:31/salida=09:26/perm=115; `463630` peso=26857/entrada=10:05/salida=abstención correcta/perm=No determinada.
- **Hallazgo que detuvo la regeneración completa de `viajes.csv` en producción:** el CSV masivo actual (`analisis_completo_guias.csv`, generado por bloques posteriores de homologación de patentes — commits `0021bde`/`129b459`) tiene **1033/1177 documentos con `indicador_revision="REVISAR"`**, mientras el `viajes.csv` en producción hoy solo refleja **84/574 viajes en `REQUIERE_REVISION`** — un desfase preexistente entre el CSV masivo (más reciente/estricto) y el reporte publicado (más antiguo), **no causado por O1.2 y fuera de su alcance**. Regenerar el reporte completo con el código actual habría reclasificado ~400 viajes ya confirmados como "requiere revisión" — un efecto colateral grande, ajeno al objetivo de este bloque. **No se sobrescribió el `viajes.csv` de producción.** Confirmado con el usuario antes de intentar cualquier escritura sobre el archivo real.
- Recomendación explícita para un bloque futuro y separado: investigar y reconciliar ese desfase (probablemente requiere decidir si el criterio "REVISAR" post-homologación de patentes debe re-evaluar los 574 viajes ya confirmados, o si necesita su propia migración) antes de intentar de nuevo una regeneración completa de `viajes.csv`.

### Archivos modificados

- `atlas_core/extractor.py` (`buscar_horas()`, `buscar_peso()`, patrones `_PATRON_HORA_TOKEN_COMPLETO`/`_PATRON_VALOR_PESO`/`_VENTANA_PESO_CARACTERES` nuevos).
- Tests: `tests/test_extractor_peso_horas_o1_2.py` (nuevo, 15 tests).
- Sin cambios: Desktop (código), ORS, Onelogis, `atlas_core/rutas/`, catálogos, `atlas_core/procesamiento_masivo.py`, `atlas_core/gestor_viajes.py`, `atlas_core/reporte_viajes.py` (todos de O1, no tocados en O1.2).

---

## 2026-08-11 — Cierre: OPERACIÓN O1, peso + hora entrada/salida + permanencia en planta

**Rama:** `lector-mvp-guia-nueva` · **Baseline previo:** `660e5b2f912f9a803c33b94cdb2e60ad98de4293`

### Problema real confirmado

- `atlas_core/extractor.py` ya calculaba `datos["peso"]`, `datos["hora de entrada"]`, `datos["hora de salida"]` desde bloques anteriores (`buscar_peso()`, `buscar_horas()`), pero **`procesar_archivo()` nunca los incluía en su dict de salida** — se perdían antes de llegar al CSV masivo, al reporte o a `viajes.csv`.
- Auditoría real (30 guías con ground truth humano, `datos_privados/muestra_fechas_30/`, mismo dataset ya usado para calibrar `CONFIANZA_MINIMA_FECHA_FOCAL`): con el `buscar_peso()` anterior, solo **2/30** guías resolvían un peso (25/30 `No encontrado`, 3/30 con valor incorrecto). Causas exactas diagnosticadas:
  1. **Anchor roto:** el regex exigía `PESO\s*KG\s*-?\s*(...)` sin tolerar el "." de "KG." ni el ":" antes del valor -- el layout real casi siempre trae ambos entre la etiqueta y el número.
  2. **Prioridad semántica invertida:** cuando sí matcheaba algo, priorizaba "PESO BRUTO" (camión+carga) sobre "PESO KG" (neto) -- confirmado incorrecto con evidencia real (ver semántica abajo).
- `buscar_horas()` (span de texto entre "HORA ENTRADA"/"HORA SALIDA") acertaba en la mayoría de casos, pero fallaba silenciosamente -- sin señal de error -- cuando el layout de Paddle scramblea los recuadros (caso real guía 383548: el valor real de ENTRADA queda pegado a la etiqueta "HORA SALIDA", produciendo una salida incorrecta sin ningún aviso).

### Semántica de PESO (Fase B, con evidencia real)

- **"PESO KG" es el peso NETO operacional de la carga/documento** -- verificado numéricamente en múltiples guías (`PESO KG = Peso Bruto - Tara`, exacto) y confirmado visualmente contra la imagen real de la guía 464170/462491: catálogo/fallback anterior usaba "12.242,000" (Peso Bruto), el valor real impreso en "PESO KG." es "3.282,00".
- "PESO BRUTO" (camión + carga) y "TARA" (camión vacío) nunca son el peso operacional -- no se usan como principal.

### Auditoría real y hallazgo sobre la calidad del ground truth (Fase A/K)

- 30 guías con ground truth humano (`ground_truth_30_guias.json`, mismo Excel de D3) + verificación visual directa (`Read` sobre la imagen) de cada discrepancia antes de aceptarla como error de Atlas.
- **6 guías con error real de transcripción en el propio ground truth**, confirmado visualmente contra la imagen original en cada caso:
  - `410266`: el ground truth copió las horas/peso de la fila vecina (`429061`) -- la imagen real muestra `10:08:00`/`12:27:32`/`3.100,00`.
  - El archivo etiquetado `410627` en el ground truth es en realidad la guía **`410267`** (visible en la propia imagen).
  - `452388`: marcado "ilegible" (`None`) en el ground truth -- la imagen es perfectamente legible: `10:36:00`/`12:18:27`/`3.024,00`.
  - `410925`: ground truth transcribió "25.454297" (formato imposible) -- el valor real impreso es "25.618,00".
  - `461523`: ground truth transcribió "1997" pese a marcar la imagen como "perfecta" -- el valor real impreso es "10.606,00".
  - `462598`: marcado `None` por calidad de imagen borrosa en otras zonas -- el campo PESO KG específico es legible: "28.421,00".
- Tras corregir estas 6 discrepancias con evidencia visual: peso ~26/30 exacto (3 abstenciones seguras por OCR degradado -- "P" de "PESO" perdida, o un dígito insertado que la validación de rango descarta -- 0 valores incorrectos), horas ~28/30 exacto (2 confusiones de un solo dígito del propio OCR, ej. "11:56"→"11:58").

### Diseño e implementación

- **`atlas_core/extractor.py`:**
  - `buscar_peso()`: reordenado (PESO KG primero, BRUTO como último recurso) y el anchor ahora tolera "KG." + salto de línea + ":" antes del valor: `PESO\s*KG\.?\s*[:\-]?\s*([0-9][0-9.,]{1,14})`. Devuelve el valor crudo tal cual -- la normalización a kg numérico vive en `procesamiento_masivo.py`.
  - `buscar_horas()`: reescrito con `hora_mas_cercana(etiqueta, excluir=None)`, acotado a la zona de encabezado (antes de "CANTIDAD", límite estable observado en todo el muestreo). Para SALIDA, descarta explícitamente un candidato idéntico al ya asignado a ENTRADA y sigue buscando uno distinto en la misma ventana -- corrige el caso real de intercambio silencioso (guía 383548) sin perder el caso real donde ambas horas genuinamente coinciden (guía 387789, verificado con ground truth).
  - Corregido un valor histórico incorrecto en el fallback hardcodeado de la guía `462491` (`"12.242,000"` → `"3.282,00"`, con evidencia visual directa). **Los otros 6 fallbacks hardcodeados históricos (462793, 462833, 461878, 462544, 462871, 462395) no se tocaron** -- no hay imagen real disponible en este entorno para verificarlos individualmente con el mismo rigor; se documenta como límite de alcance explícito, no como corrección omitida por descuido.
- **`atlas_core/procesamiento_masivo.py`:**
  - `_normalizar_peso_kg()`: tolera que el OCR confunda "." y "," como separador de miles (caso real: "6,971,00" en vez de "6.971,00") -- separa por grupos, descarta el último grupo si son puros ceros de 2-3 dígitos (los decimales, siempre observados en cero). Valida rango operativo plausible `1-60000` kg (generoso a propósito) -- descarta automáticamente el caso real de dígito insertado por OCR ("127.983" kg, imposible para un camión).
  - `_calcular_permanencia_minutos()`: `salida - entrada` en minutos; si `salida < entrada`, **nunca asume +24h automáticamente** -- devuelve `"No determinada"` (motivo trazable en el propio valor, sin degradar `indicador_revision`).
  - `COLUMNAS` gana 4 columnas al final: `peso_kg`, `hora_entrada_aza`, `hora_salida_aza`, `permanencia_minutos`. `procesar_archivo()` las incluye en su dict de salida -- **ausencia de estos datos nunca participa en `requiere_revision`** (decisión explícita de Fase I: no degradar documentos que antes de este bloque quedaban OK).
- **`atlas_core/gestor_viajes.py`** (Fase H, política multi-guía con evidencia real):
  - `DocumentoViaje` gana `peso_kg`, `hora_entrada_aza`, `hora_salida_aza`, `permanencia_minutos` (por documento, preservados en `evidencia` como el resto de campos).
  - `Viaje.peso_total_viaje_kg`: suma de `peso_kg` de todos los documentos, **solo si todos aportan un valor numérico válido** -- evidencia real (transporte `0000297304`, 3 guías): cada documento trae el peso parcial de su propia línea de material (códigos distintos: `6.971`, `3.100`, `4.256` kg) -- sumar no duplica.
  - `Viaje.hora_entrada_aza`/`hora_salida_aza`: consolidadas solo si todas las horas válidas presentes coinciden (`_valores_unicos` ya existente, reutilizado). Dos motivos nuevos en `MotivoRevision`: `CONFLICTO_HORA_ENTRADA`, `CONFLICTO_HORA_SALIDA` -- si difieren, nunca se elige una arbitrariamente.
  - `Viaje.permanencia_minutos`: derivada de las horas ya consolidadas, nunca promedia permanencias de documentos individuales.
- **`atlas_core/reporte_viajes.py`:** `COLUMNAS_VIAJES` gana `peso_total_viaje_kg`, `hora_entrada_aza`, `hora_salida_aza`, `permanencia_minutos` al final; `_fila_viaje()` los propaga directo desde `Viaje.a_dict()` (sin callback opcional -- a diferencia de las columnas de ruta, estos campos no dependen de un servicio externo). `COLUMNAS_OFICIALES` (= `procesamiento_masivo.COLUMNAS`) ahora exige estas 4 columnas como obligatorias en el CSV de entrada -- un CSV generado con el pipeline anterior a este bloque debe reprocesarse, no puede alimentar `generar_reporte_viajes()` directamente (mismo contrato de esquema estricto que ya regía para cualquier otra columna oficial faltante).

### Validación real multi-guía (Fase L)

- **Transporte `0000279246`** (guías `384674`, `384675`): pesos parciales `7.756` + `7.945` = **`15.701` kg**; horas coincidentes `10:30`/`12:48` → permanencia **138 min**.
- **Transporte `0000297304`** (guías `410265`, `410266`, `410267`): pesos parciales `6.971` + `3.100` + `4.256` = **`14.327` kg**; horas coincidentes `10:08`/`12:27` → permanencia **139 min**.
- Ambos ejecutados con el pipeline real completo (`procesar_archivo` + `agrupar_viajes`), sin inyectar nada.

### Validación

- Tests nuevos: **26** (`tests/test_extractor_peso_horas_o1.py` -- 14; `tests/test_gestor_viajes.py` -- 7 nuevos + 2 casos añadidos al parametrize existente; `tests/test_reporte_viajes.py` -- 3; `tests/test_procesamiento_masivo.py` -- 1; ajuste de 1 test existente con el set de columnas ampliado, y corrección de 1 valor de test que afirmaba el bug de PESO BRUTO como comportamiento esperado).
- Suite completa: **665 → 691 passed**, 0 failed, 0 regresiones.

### Archivos modificados

- `atlas_core/extractor.py`, `atlas_core/procesamiento_masivo.py`, `atlas_core/gestor_viajes.py`, `atlas_core/reporte_viajes.py`.
- Tests: `tests/test_extractor_peso_horas_o1.py` (nuevo), `tests/test_extraer_datos.py`, `tests/test_procesamiento_masivo.py`, `tests/test_gestor_viajes.py`, `tests/test_reporte_viajes.py`.
- Sin cambios: Desktop, ORS, Onelogis, `atlas_core/rutas/` (E1/D2/D3 intactos).

---

## 2026-08-11 — Cierre: ENTREGAS E1, DESPACHAR A como fuente autoritativa de ruta

**Rama:** `lector-mvp-guia-nueva` · **Baseline previo:** `8b59951a9662c88747fa2e09504acbb09a740188`

### Decisión de arquitectura/producto (registro formal)

Definición operacional entregada por Javier, **prevalece sobre inferencias anteriores de D2/D3/D3.1**:

1. `SEÑOR(ES)` = comprador. No implica que los materiales se entreguen en sus instalaciones.
2. `OBRA DESTINO` = obra/proyecto/receptor al que están destinados los materiales. Puede tener un nombre completamente distinto de `SEÑOR(ES)` -- nunca exigir coincidencia.
3. **`DESPACHAR A` = dirección física real de entrega. Es la fuente PRINCIPAL y AUTORITATIVA del destino geográfico de la ruta.** La ruta debe ser `PLANTA ORIGEN → DESPACHAR A`, nunca `PLANTA ORIGEN → dirección del cliente/sitio registrado` cuando `DESPACHAR A` esté disponible.
4. `COMUNA` (campo del formulario): no asumir que corresponde universalmente a la comuna de entrega -- auditar antes de usar (ver más abajo).
5. `COD DESTINATARIO`/`DIRECCION`/otros campos estructurados: siguen siendo evidencia válida de identidad/relación comercial (siguen sirviendo a D2/D3), pero **nunca reemplazan `DESPACHAR A` como punto final de una ruta**.
6. Aprendizaje futuro permitido: una combinación recurrente `cliente + obra_destino + despachar_a` puede aprenderse y reutilizarse -- pero la **primera** confirmación de una entrega debe venir siempre de evidencia real de `DESPACHAR A`, nunca de la dirección del comprador.

### Fase A/B del bloque -- auditoría de COMUNA (requisito explícito antes de implementar cualquier regla de comuna)

- Se completó la lectura OCR real de las 4 guías del set de 14 que aún faltaban por consolidar en un solo lugar comparativo (ya auditadas individualmente en D3/D3.1): confirmado con las 14, 11 con lectura usable de `COMUNA` + `DESPACHAR A`.
- **Resultado:** `COMUNA` coincide con la comuna real de entrega en ~8/11 lecturas (incluyendo 2 coincidencias "casuales" donde la calle exacta de `DESPACHAR A` difiere de `DIRECCION` pero la comuna sí coincide) -- pero en los 3 casos de entrega interregional (`464170`→Mejillones/Antofagasta, `464264`/`464265`→Coronel/Biobío, `464367`→aparente Ñuble), `COMUNA` siguió mostrando la comuna RM del sitio registrado, **no** la real. Conclusión operacional: `COMUNA` es *coincidentemente* confiable solo para entregas intra-comuna/región del sitio registrado, y activamente engañosa para las interregionales -- que son precisamente las que más importan corregir (mayor error de distancia). **Decisión: nunca reutilizar `COMUNA` para geocodificar `DESPACHAR A`; geocodificar el texto crudo de `DESPACHAR A` directamente**, dejando que el proveedor de geocodificación determine la localidad con contexto territorial real.

### Diseño e implementación

- **Nuevo módulo `atlas_core/rutas/destino_entrega.py`** (no reemplaza `destino_estructurado.py` de D2 -- lo complementa; identidad comercial y destino de ruta son preguntas distintas, ver D3.1):
  - `resolver_destino_entrega(despachar_a_crudo, proveedor_geocodificacion, *, contexto_territorial="Chile")`: geocodifica `DESPACHAR A` vía `ProveedorRutas.geocodificar()` (interfaz ya existente desde RUTAS-EVAL R1, reutilizada sin cambios). Preserva siempre el texto crudo original.
  - **Refinamiento de ambigüedad con evidencia real:** el primer intento (cualquier `RESULTADO_AMBIGUO` -> `REVISAR`) resultó en falsos positivos reales -- "AV. ALMTE. LATORRE 843, MEJILLONES" devolvió 5 candidatos, todos confianza 1.0, todos dentro de ~350 m entre sí (Pelias no calzó el número exacto de casa, devolvió vecinos de la misma cuadra). Se agregó `_candidatos_son_el_mismo_lugar()` (distancia Haversine, reutiliza `geocerca.distancia_km_haversine` ya existente, margen `MARGEN_MISMO_LUGAR_KM=1.0`): si TODOS los candidatos caen dentro del margen del primero, se usa el de mayor confianza (`_mejor_candidato`, nunca el más cercano a AZA); si no, sigue siendo `REVISAR` (`MULTIPLES_UBICACIONES_DISPERSAS`). Caso real confirmado de ambigüedad genuina: "SANTA ISABEL 585" devolvió resultados en Perú, Argentina, Puerto Rico y **dos puntos distintos** dentro de Lampa, RM -- correctamente `REVISAR`.
  - Confianza mínima (`UMBRAL_CONFIANZA_MINIMA=0.5`) para aceptar un único candidato no ambiguo -- por debajo, también `REVISAR`.
  - `calcular_ruta_entrega_para_viaje(...)`: orquesta `resolver_planta_origen` (reutilizado sin cambios de `enriquecimiento_viaje.py`, import perezoso para evitar ciclo) -> `resolver_destino_entrega` -> `proveedor_rutas.calcular_ruta()` directo (**sin la capa de caché de `ServicioRutas`/`RepositorioRutas`** -- esa caché indexa por `destino_id` de catálogo, y una entrega geocodificada en vivo no es todavía una entidad de catálogo; ver Fase E de D3.1, propuesta de modelo `destino_entrega` no implementada). Nunca lanza; un fallo en cualquier paso deja `estado_ruta`/`motivo_ruta` explicativos.
  - Función completamente nueva, aditiva -- **`calcular_ruta_para_viaje` (D2, catálogo) no se modificó**; ambos caminos coexisten para propósitos distintos (identidad/reporte vs. ruta real).

### Validación

- Tests nuevos: **10** en `tests/test_rutas_destino_entrega.py` -- sin dato, candidato único con/sin confianza suficiente, ambigüedad real (nunca elige el más cercano a AZA), candidatos dispersos-pero-cercanos resueltos como el mismo lugar (caso real Mejillones), fallo de geocodificación preserva el texto crudo, ruta real end-to-end, origen no determinado nunca geocodifica, entrega ambigua nunca calcula ruta.
- Suite completa: **655 → 665 passed**, 0 failed, 0 regresiones.
- **Validación real (ORS real, catálogo de plantas real, sin inyectar nada):**
  - **464170 (caso ejemplo oficial):** AZA RENCA → "AV. ALMTE. LATORRE 843, MEJILLONES" = **1433.2 km / 1441.08 min (~24 h)**, confianza 1.0. Confirma que la ruta correcta es radicalmente distinta de lo que el catálogo (Galvarino 8501, Quilicura) habría dado.
  - **464424 (Torres Ocaranza):** 16.73 km / 24.6 min -- converge con la cifra ya conocida por el camino de catálogo (16.68 km/24.53 min, D2/D3), validación cruzada de que ambos caminos son consistentes cuando `DESPACHAR A` y el sitio registrado coinciden.
  - **464511 (Armacero):** `REQUIERE_REVISION`/`MULTIPLES_UBICACIONES_DISPERSAS` -- "Santa Isabel" es un nombre de calle común, Pelias devolvió resultados internacionales; abstención correcta, limitación conocida (ver pendientes).

### Archivos modificados

- Nuevo: `atlas_core/rutas/destino_entrega.py`, `tests/test_rutas_destino_entrega.py`.
- Modificado: `atlas_core/rutas/__init__.py` (exports nuevos).
- Sin cambios: `atlas_core/rutas/openrouteservice.py`, `atlas_core/rutas/servicio.py`, `atlas_core/rutas/enriquecimiento_viaje.py`, `atlas_core/rutas/destino_estructurado.py`, extractores, Desktop, `destinos_maestros.json`.

---

## 2026-08-11 — Cierre: DESTINOS D3.1, auditoría semántica DIRECCION vs DESPACHAR A + revert controlado

**Rama:** `lector-mvp-guia-nueva` · **Baseline previo:** `7c070a81ff4884556625516aae5785744954c93f`

### Auditoría (solo lectura)

- Se completó la lectura OCR real de las 4 guías del set de 14 que aún no se habían auditado (`464265`, `464367`, `464395`, `464488`), llegando a las 14 con imagen disponible en el repo, todas con `DIRECCION`/`COMUNA`/`COD DESTINATARIO`/`DESPACHAR A` extraídos.
- **Hallazgo central:** de las 14, 9 tuvieron lectura limpia de `DIRECCION` y `DESPACHAR A` simultáneamente. **5 concordantes** (`464424`, `464479`, `464494`, `464495`, `464511`), **4 divergentes** (`464170` EBEMA→Mejillones vs Quilicura; `464395` Ingemeta→Carmen Mena 529 vs Santa Rosa 5587, mismo cliente, dos sitios registrados distintos observados en dos guías; `464264`/`464265` Sodimac→Coronel vs Renca, **interregional**; `464488` Easy Retail→misma comuna, calle distinta). Conclusión: `DIRECCION`/`COMUNA`/`COD DESTINATARIO` identifican el sitio/obra **registrado** contra el que se emite la guía, no necesariamente el punto físico de entrega — that campo es `DESPACHAR A`. Consistente con, y más granular que, el hallazgo ya usado por D2 (`evaluar_concordancia_despacho`).
- Auditoría de las 4 confirmaciones de D3 cruzando específicamente evidencia de `DESPACHAR A` (no solo repetición de `DIRECCION`+`COMUNA` como hizo D3): Armacero (2/2 guías con `DESPACHAR A` concordante: `464511`, `464489`) y Aceros Cox (2/2: `464494`, `464495`) quedan con evidencia de entrega real doble e independiente. Ebema (1 sola observación de `DESPACHAR A` disponible, y **diverge**) y Salomón Sack (0 observaciones de `DESPACHAR A` — el ground truth usado en D3 no releva ese campo) quedan sin evidencia positiva de entrega.

### Revert ejecutado (tras confirmación explícita del usuario, tool `AskUserQuestion`)

- Respaldo previo: `C:\Users\Jjjc0508\Desktop\Atlas\backups_catalogos\20260811_pre_revert_d31\destinos_maestros.json`, verificado por checksum contra el catálogo real antes de tocar nada.
- `CatalogoDestinos.editar(..., modificacion_manual=True, estado_calidad=PENDIENTE, fuente=..., observacion=...)` sobre `32d67fec-...` (EBEMA/Galvarino 8501) y `c25be79a-...` (Salomón Sack/Camino Los Pinos 3396) — únicos campos modificados: `estado_calidad`, `fuente` (marca `REVERSION_DESTINOS_D3.1_2026-08-11+AUDITORIA_SEMANTICA_SIN_EVIDENCIA_DESPACHO`) y `observacion` (motivo apendiado, sin borrar el texto de confirmación de D3 ni el de la migración original). Dirección/comuna/región/código/coordenadas verificados idénticos antes/después.
- Catálogo tras el revert: recargado sin `CatalogoDestinosCorruptoError`, 47 destinos, **6 CONFIRMADO** (los 4 originales + Armacero + Aceros Cox) / **41 PENDIENTE**.
- Suite: **655 passed**, sin cambios — este bloque no tocó ningún archivo de código de producción ni de tests (solo el catálogo real, fuera del repo, y las bitácoras).

### Archivos modificados

- Dato: `%LOCALAPPDATA%\Atlas\datos\catalogos_privados\destinos_maestros.json` (2 destinos `CONFIRMADO`→`PENDIENTE`, con respaldo verificado).
- Repo: solo `docs/BITACORA_EJECUTIVA.md`, `docs/BITACORA_TECNICA_CRONOLOGICA.md`, `docs/HANDOFF_ATLAS.md`. 0 código, 0 tests.
- Artefactos nuevos fuera del repo: `rutas_eval/d31_evidencia_real_faltante.json` (OCR real de las 4 guías completadas).

---

## 2026-08-11 — Cierre: DESTINOS D3, confirmación humana asistida de destinos frecuentes

**Rama:** `lector-mvp-guia-nueva` · **Baseline previo:** `54f484f043f203926ce5ad4a56c8babda1e90f89`

### Problema real confirmado

- `destinos_maestros.json` real: 47 destinos, 43 `PENDIENTE`, 4 `CONFIRMADO`. El gate de calidad de `ServicioRutas` (ya existente, sin tocar) bloquea el cálculo de ORS para cualquier destino `PENDIENTE` — correcto por diseño, pero deja casi todas las guías reales sin ruta.

### Fuentes de evidencia nuevas

- **`datos_privados/ground_truth/validacion_atlas_30_guias_v1.xlsx`** (hoja "Datos guías"): 30 guías reales con `CLIENTE`, `RUT CLIENTE`, `CÓDIGO DESTINATARIO`, `DIRECCIÓN DESTINO`, `COMUNA`, `CIUDAD` transcritos y validados a mano — no usado en bloques anteriores. Requirió instalar `openpyxl` (no estaba en el entorno).
- Hallazgo relevante para la jerarquía de D2: dos filas (guías `390486` y `428701`), mismo cliente (TORRES OCARANZA LTDA) y mismo código destinatario (`0001004443`), muestran direcciones de entrega distintas ("VISTA CLARA 391" vs "VISTA CLARA 2351") — confirma con datos humanos independientes la razón por la que D2 dejó de tratar el código como llave autónoma.
- Cruce de campos detectó una inconsistencia de transcripción: para EBEMA SA, el ground truth registra "CÓDIGO DESTINATARIO" = `0001001424`, pero ese valor coincide con el campo *distinto* "Código Cliente" visible en el encabezado de la guía real 464170 — el código real de `COD DESTINATARIO` en esa guía es `0002013046`. Documentado, no usado como evidencia de código para EBEMA en este bloque.

### Ranking (Fase A)

- Fuente primaria: campo `observacion` de cada destino migrado (`"N viajes en el periodo 01/04/2026-30/06/2026"`, dato real del Excel de origen). Cruzado automáticamente (normalización con `unicodedata`, comparación cliente+dirección+comuna) contra el ground truth y contra la evidencia OCR real ya recolectada en D2 más 2 guías nuevas de este bloque (464494, 464495 — ACEROS COX COMERCIAL SA).
- Top por frecuencia: ARMACERO MATCO SA/Santa Isabel 585 (94), EBEMA SA/Galvarino 8501 (34), AGF ACEROS DE CHILE SPA/Panamericana Norte 22650 (23), ACEROS COX COMERCIAL SA/Camino Lo Ruiz 2901 (20), AMERICAN SCREW CHILE SPA/Camino a Melipila 10800 (19, sin coordenadas).
- Artefactos completos: `C:\Users\Jjjc0508\Desktop\Atlas\destinos_revision\ranking_destinos_pendientes.json` (47 destinos con evidencia cruzada) y `fichas_lote_10.md` (10 fichas completas con recomendación individual).

### Fase B/C — validación geográfica y de región

- Confirmados los 4 registros "SAN MIGUEL" con coordenada errónea ya conocida (`lat=-30.81, lon=-70.60`, zona de Ovalle/Coquimbo, ~370 km de RM) -- ninguno estaba en el lote de 10, se documentan igual por instrucción explícita.
- Detectado (no corregido, fuera de este cliente/lote): varios destinos de la zona industrial de Renca (ACEROS COX y SODIMAC en "Camino Lo Ruiz"; ACMA SA en "Maruri", dos números distintos) comparten coordenada exacta entre sí — geocodificación a nivel de calle, no de número, un límite de precisión conocido del proceso de migración, no un error de identidad.
- Los 47 destinos actuales son región RM (uno con el texto "REGIÓN METROPOLITANA" en vez de "RM" — inconsistencia de formato en un registro ya `CONFIRMADO` de un bloque anterior, no tocado aquí). El ground truth reveló viajes reales interregionales (Temuco, Coronel) sin destino correspondiente todavía en el catálogo -- no se fabricó ninguno, documentado como brecha real para un bloque futuro.

### Fase D/E/F/G — evidencia, fichas y confirmación

- Criterio aplicado (más estricto que el mínimo pedido por el enunciado): **confirmar solo con ≥2 documentos independientes** (nunca el agregado de migración por sí solo) concordantes en cliente+dirección+comuna.
- Respaldo previo verificado por checksum: `C:\Users\Jjjc0508\Desktop\Atlas\backups_catalogos\20260811_pre_confirmacion_d3\destinos_maestros.json`.
- **4 destinos confirmados** vía `CatalogoDestinos.editar(..., modificacion_manual=True, estado_calidad=CONFIRMADO, fuente=..., observacion=...)` — nunca edición manual del JSON. Solo cambian `estado_calidad`, `fuente` (marca `CONFIRMACION_DESTINOS_D3_2026-08-11+EVIDENCIA_MULTIPLE_INDEPENDIENTE`, mismo patrón ya usado por Torres Ocaranza en un bloque anterior) y `observacion` (evidencia apendiada, preservando el texto original de migración) — dirección/comuna/región/código/coordenadas verificados idénticos antes/después, campo por campo, en el propio script de confirmación.
- 1 candidato (AMERICAN SCREW CHILE SPA) separado explícitamente como `CORREGIR DATOS`: 3 grafías distintas de la misma dirección real entre catálogo/OCR real/ground truth (posible error de tipeo heredado de la migración) + coordenadas ausentes — no confirmado ni corregido en este bloque, para no mezclar corrección de datos con confirmación en la misma operación.

### Fase H — rutas reales

- **AZA RENCA → ARMACERO MATCO SA/Santa Isabel 585** (guía real 464511): `RUTA_CALCULADA`, 12.969 km / 19.71 min.
- **AZA RENCA → ACEROS COX COMERCIAL SA/Camino Lo Ruiz 2901** (guías reales 464494 y 464495): `RUTA_CALCULADA`, 0.086 km / 0.13 min (segunda consulta → `RESULTADO_DESDE_CACHE`) — distancia real muy corta porque ambos domicilios están en el mismo tramo de la zona industrial de Renca, no es un error.
- **AZA RENCA → EBEMA SA/Galvarino 8501** (guía real 464170, destino ya confirmado): sigue en `REQUIERE_REVISION`/`DESPACHO_DIVERGENTE_DEL_DESTINO_CANONICO` — el gate de concordancia de D2 protege el viaje individual independientemente del estado de confirmación del destino, exactamente como se diseñó.
- No hubo ningún destino interregional confirmable en el lote (0 candidatos regionales `PENDIENTE` existían en el catálogo) — el requisito condicional de Fase H ("si algún destino regional queda confirmado") no aplicó; no se fabricó ninguno.

### Validación

- Tests nuevos: **12** en `tests/test_destinos_d3_confirmacion.py` -- destino RM válido por comuna+región, mismo nombre de calle en cliente/comuna/región distinta no colisiona (abstención, nunca elección arbitraria), coordenadas fuera de rango rechazadas, código destinatario concordante resuelve, `DESPACHAR A` divergente bloquea la ruta aun con destino confirmado, destino `PENDIENTE` no enruta, destino `CONFIRMADO`+concordante calcula ruta real, confirmar preserva dirección/comuna/región/código/coordenadas (verificado campo por campo), el catálogo sigue siendo válido (recarga sin `CatalogoDestinosCorruptoError`) tras confirmar, no regresión de la resolución global sin cliente (D1/D2) y de extracción/concordancia (D2).
- Suite completa: **643 → 655 passed**, 0 failed, 0 regresiones.

### Archivos modificados

- Nuevo: `tests/test_destinos_d3_confirmacion.py`.
- Sin cambios de código de producción -- D3 reutiliza `atlas_core/rutas/destino_estructurado.py` y `enriquecimiento_viaje.py` de D2 tal cual.
- Dato: `%LOCALAPPDATA%\Atlas\datos\catalogos_privados\destinos_maestros.json` (4 destinos `PENDIENTE`→`CONFIRMADO`, con respaldo previo verificado).
- Artefactos nuevos fuera del repo: `C:\Users\Jjjc0508\Desktop\Atlas\destinos_revision\` (ranking + fichas), `C:\Users\Jjjc0508\Desktop\Atlas\backups_catalogos\20260811_pre_confirmacion_d3\`.

---

## 2026-08-11 — Cierre: DESTINOS D2, resolución canónica de destino estructurada

**Rama:** `lector-mvp-guia-nueva` · **Baseline previo:** `3f28e4cc6876253dc8a528dbd9ef8651e5daa7e7`

### Problema real confirmado

- La verificación final de rutas (bloque anterior) mostró que `resolver_destino_canonico` (emparejamiento por nombre/alias contra `destinos_maestros.json`) fallaba con `DESTINO_NO_HOMOLOGADO` para prácticamente cualquier guía real, porque `obra_destino` (texto OCR, casi siempre un nombre comercial o de sitio de obra) casi nunca coincide textualmente con `nombre_destino` en el catálogo (que está poblado con direcciones, migradas desde un Excel de estudio de distancias, no desde el texto de las guías).
- Auditoría de 7 guías reales (`464170`, `464511`, `464489`, `464491`, `464493`, `464264`, `464424`) mostró que el propio documento AZA trae, además de `OBRA DESTINO`, los campos `COD DESTINATARIO`, `DIRECCION` y `COMUNA` -- y que `DIRECCION`+`COMUNA` coinciden **exactamente** (tras normalizar) con `nombre_destino`+`comuna` del catálogo en los casos con OCR limpio. El campo `codigo_destino` del catálogo (vacío en 46/47 registros migrados) coincide exactamente con `COD DESTINATARIO` cuando existe (validado con Torres Ocaranza, guía 464424: mismo código `0001004443` que la observación ya registrada en el catálogo, documentada desde otra guía histórica, 464106).
- Corrección de rumbo con evidencia externa (auditoría independiente de 31 guías, Codex): `COD DESTINATARIO` no es una llave autónoma segura -- el mismo código/cliente puede repetirse con `DESPACHAR A` (punto de entrega real de ESE viaje) distinto, incluso en otra región (caso documentado: `0001004443`/Torres Ocaranza con `DESPACHAR A` "VISTA CLARA 391" en una guía y "VISTA CLARA 2351" en otra). Confirmado con evidencia propia adicional: guía 464170 (EBEMA SA) homologa correctamente por dirección a GALVARINO 8501 (Quilicura, RM), pero su `DESPACHAR A` real es "AV. ALMTE. LATORRE 843, MEJILLONES" (Región de Antofagasta) -- domicilio registrado y punto de entrega real de este viaje son lugares físicamente distintos.

### Diseño

- **Nuevo módulo `atlas_core/rutas/destino_estructurado.py`** (no reemplaza nada existente):
  - `extraer_identificadores_destino(textos)`: lee `COD DESTINATARIO`, `DIRECCION`, `COMUNA`, `DESPACHAR A` del texto OCR de página completa ya disponible (mismo texto usado por `resolver_origen_documental`), con regex de límite genérico (un conjunto de etiquetas conocidas marca dónde termina cada valor, sin asumir un orden fijo entre etiquetas -- el orden varía guía a guía). Conservador: si el layout viene degradado por el OCR (etiquetas fuera de orden real, no solo reordenadas), simplemente no captura el campo -- nunca arriesga un valor.
  - `resolver_destino_canonico_estructurado(...)`: jerarquía **A.** cliente (RUT si se informa, cruzado contra el RUT ya registrado del cliente -- una contradicción de RUT no acota por cliente) + código destinatario exacto y único → **B.** dirección (+comuna si se extrajo) exacta normalizada y única → **C.** alias/nombre acotado al cliente (`CatalogoDestinos.buscar(..., cliente_id=...)`) → **D.** comportamiento histórico global sin cambios (`resolver_destino_canonico`, delegado tal cual). Cada nivel exige coincidencia única; ante 0 o >1 candidatos, cae al siguiente o se abstiene -- nunca fabrica ni "desempata".
  - `evaluar_concordancia_despacho(destino, identificadores)`: contrasta el destino ya resuelto (identidad/homologación) contra `DESPACHAR A` (punto de entrega real de este viaje) por solape de tokens normalizados (dirección o comuna). Sin `DESPACHAR A` en el documento, se considera concordante (compatible con el comportamiento previo a este campo).
  - **Refactor sin cambio de comportamiento** en `enriquecimiento_viaje.py`: se extrajo `validar_destino_resoluble` (vigencia/coordenadas/rango RM) de `resolver_destino_canonico`, reutilizado ahora por ambos caminos de resolución -- ningún camino nuevo puede saltarse esos controles.
  - `calcular_ruta_para_viaje` gana 3 parámetros opcionales (`cliente_texto`, `catalogo_clientes`, `rut_cliente_texto`, todos `None` por defecto): sin ellos, comportamiento **100% idéntico** a antes de este bloque (nivel D global). Con ellos, resuelve por identidad estructurada y, si el destino resuelve pero `DESPACHAR A` diverge materialmente, devuelve `REQUIERE_REVISION`/`DESPACHO_DIVERGENTE_DEL_DESTINO_CANONICO` **antes** de intentar resolver origen/ORS -- nunca calcula una ruta sobre una identidad de destino sin confirmar contra el punto de entrega real.
  - Import circular evitado con imports perezosos (dentro de función) en ambas direcciones: `destino_estructurado` usa `enriquecimiento_viaje` solo dentro de `resolver_destino_canonico_estructurado`; `enriquecimiento_viaje` usa `destino_estructurado` solo dentro de `calcular_ruta_para_viaje`.

### Validación

- Tests nuevos: **14** en `tests/test_rutas_destino_estructurado.py` -- código exacto, código desconocido cae a dirección, obra_destino sin coincidencia dentro del cliente abstiene, dirección+comuna exacta, alias acotado a cliente, ambigüedad real (entre clientes distintos, la única alcanzable -- `CatalogoDestinos` ya impide duplicados dentro de un mismo cliente en la escritura), cliente no resuelto cae al nivel D histórico, RUT contradictorio no acota por cliente, ruta real calculada con destino confirmado y despacho concordante, destino PENDIENTE bloquea la ruta (gate existente, sin tocar), despacho divergente bloquea la ruta aunque el destino resuelva, extracción robusta a 2 órdenes de etiquetas reales distintos, extracción de `DESPACHAR A`, concordancia por defecto sin evidencia de despacho.
- Suite completa: **629 → 643 passed**, 0 failed, 0 regresiones.
- **Validación real (catálogo activo real, 7 guías reales, ORS real):**
  - 464170 (EBEMA SA): identidad resuelve (`RESUELTO_DIRECCION_COMUNA` → GALVARINO 8501), pero `DESPACHO_DIVERGENTE_DEL_DESTINO_CANONICO` (Mejillones vs Quilicura) -- correctamente **no** calcula ruta.
  - 464511 (ARMACERO MATCO SA): identidad resuelve (`RESUELTO_DIRECCION_COMUNA` → SANTA ISABEL 585), concordancia con `DESPACHAR A` **sí**, planta AZA RENCA resuelta por documento -- bloqueado por `DESTINO_NO_CONFIRMADO` (destino aún `PENDIENTE`, gate de calidad existente funcionando como se diseñó).
  - 464424 (TORRES OCARANZA LTDA, destino ya `CONFIRMADO`): identidad resuelve por código destinatario, concordancia con `DESPACHAR A` **sí**, planta AZA RENCA por documento → **ruta real ORS: 16.683 km / 24.53 min**. Cliente de esta guía en particular no lo extrae el pipeline lineal ni el fallback geométrico (falla preexistente y ajena a este bloque, confirmada con `extraer_datos()` puro sin catálogos) -- se usó el texto literal `SEÑOR(ES)` del propio documento como entrada de cliente, documentado explícitamente como diagnóstico, no como sustitución de destino.
  - Otras 4 guías (464489, 464491, 464493, 464264): abstención correcta (`DESTINO_NO_HOMOLOGADO`) por OCR degradado o catálogo aún sin ese destino -- 0 asignaciones incorrectas.

### Archivos modificados

- Nuevo: `atlas_core/rutas/destino_estructurado.py`, `tests/test_rutas_destino_estructurado.py`.
- Modificados: `atlas_core/rutas/enriquecimiento_viaje.py` (refactor `validar_destino_resoluble` + parámetros opcionales en `calcular_ruta_para_viaje`), `atlas_core/rutas/__init__.py` (exports nuevos).
- Sin cambios: `atlas_core/rutas/openrouteservice.py`, `atlas_core/rutas/servicio.py` (ORS y el gate de confirmación no se tocaron), extractores (`atlas_core/extractor.py`), Desktop.

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

## 2026-08-11 — Cierre PLANTA-P1: resolución real de planta origen

**Rama:** `lector-mvp-guia-nueva` · **Baseline previo:** `1a108038fa5a3f7cfe25c13189051980ae8294f9`

### Fase A — Auditoría Onelogis histórico (revisión con aclaración de Javier)

- Se re-auditó `gps_logic.js`/`main.js`/`gps_config.json`/`atlas_viajes.html` buscando explícitamente `history`, `historical`, `trips`, `viajes`, `recorrido`, `positions`, `tracking`, `route`, `fechaDesde`, `fechaHasta` — sin resultados nuevos más allá de lo ya documentado en RUTAS R1 (solo `.../gps/ultimas-posiciones`). Búsqueda repetida en `G:\...\BACKUP_PRE_FORMATEO_20260808` — sin resultados.
- Javier confirmó (uso manual de su cuenta Onelogis) que la plataforma sí ofrece histórico de viajes por fecha. Se investigó si existe documentación pública de API de Onelogis (`WebSearch`/`WebFetch` sobre `onelogis.com`) — sin resultados (sitio bloquea `WebFetch`, sin documentación de API indexada públicamente).
- **No se intentó** probar rutas de endpoint no confirmadas contra el sistema en producción, ni automatizar el navegador de Onelogis — ambos explícitamente fuera de alcance. Conclusión: la capacidad existe en la plataforma Onelogis, pero no hay evidencia técnica de que la integración actual de Atlas (ni ninguna alternativa segura de descubrir desde este entorno) pueda consumirla hoy. Queda como gestión pendiente de Javier (revisar su cuenta/soporte Onelogis).

### Fase B — Inspección de `_resolver_origen_documental` (`origin/feature-cobertura-origen-fase1`)

- Leído vía `git show` (sin cherry-pick, sin restaurar archivos) el código completo: `_distancia_token` (Levenshtein acotado a diferencia de longitud ≤1), `_tokens_encabezado_origen` (corta tokens antes de la primera mención tolerante de "SUCURSAL"), `_resolver_origen_documental` (exige que TODOS los tokens del nombre de una planta CONFIRMADA/ACTIVA aparezcan entre los tokens observados, con distancia ≤1 cada uno; exige consenso ≥2 de N lecturas y planta única — 0 o ≥2 candidatas → abstención).
- Señales: nombre de planta impreso en el propio encabezado de la guía ("CASA MATRIZ PLANTA <NOMBRE>"). Precisión real reportada en el commit de cierre (`2c5c764`): 9 guías reales, cobertura 4/9 → 7/9, **0 falsos positivos** — los 2 casos sin resolver (464107, 464109) fueron por desenfoque/omisión de OCR, no por error de lógica. Generaliza correctamente Renca/Colina (compara contra CUALQUIER planta CONFIRMADA/ACTIVA del catálogo, no hardcodea nombres) — el propio caso que motivó el fix (`2c5c764`) es que el catálogo real confirma ambas plantas a la vez y el directorio de sucursales (que menciona "Colina") generaba una segunda coincidencia sin el corte "SUCURSAL".
- **Cambio necesario para adaptar a HEAD actual:** `leer_encabezado_origen_focal` (la función que RELEE el encabezado) llama `lector.readtext(..., detail=0, paragraph=False)` — API específica de `easyocr.Reader`, no soportada por `PaddleOCRProvider` (mismo patrón de acoplamiento ya diagnosticado y resuelto para fecha/transporte focal en bloques anteriores). **No se portó esa función.** En su lugar, se comprobó (con la guía real `464170`, ya usada en C1/D1) que el encabezado del emisor ya aparece dentro del texto de página completa que entrega PaddleOCR con confianza alta (`CASAMATRIZPLANTARENCA`, línea 5 del OCR real) — por lo que la relectura focal resulta innecesaria con el proveedor actual. Solo se adaptó/portó la lógica pura de texto (`_distancia_token`, `_tokens_encabezado_origen`, `_resolver_origen_documental`), operando sobre `textos` de página completa en vez de sobre 3 variantes de un recorte focal.

### Fase C — Estrategia elegida: `DOCUMENTAL_PRINCIPAL_GPS_TIEMPO_REAL`

- GPS histórico no disponible técnicamente hoy (Fase A) → no puede ser la vía principal. Evidencia documental ya validada (7/9 real, 0 falsos positivos, general por catálogo) → vía principal. GPS (última posición) queda disponible como señal de mayor prioridad SOLO cuando hay evidencia (patente+instante+proveedor+geocerca+ventana temporal), útil sobre todo para procesamiento cercano al instante real de salida, no para reprocesamiento histórico.

### Diseño (Fase C/E, implementación)

- **`atlas_core/rutas/origen_documental.py`** (nuevo): `resolver_origen_documental(textos, plantas)` — puerto de la lógica pura descrita en Fase B, con `_normalizar`/`_distancia_token`/`_tokens_encabezado_origen` propios (sin depender de `atlas_core.procesamiento_masivo`, evita acoplar el módulo aislado de rutas al extractor). Acepta cualquier objeto `planta` con atributos `nombre`/`estado_calidad`/`estado_vigencia` (duck typing vía `getattr`, compatible con `atlas_core.catalogo_plantas.Planta`).
- **`atlas_core/rutas/enriquecimiento_viaje.py`:**
  - `resolver_planta_origen` reestructurado: tramo GPS extraído a `_resolver_planta_por_gps` (misma lógica de RUTAS R1, sin cambios de comportamiento); si GPS no resuelve y se entrega `textos_documento`, se intenta `resolver_origen_documental`. **Política de conflicto conservadora:** el GPS, si resuelve, gana siempre — el documento nunca se evalúa si el GPS ya tuvo éxito (cortocircuito explícito en el código, no una regla de "votación"). **Cambio de firma:** devuelve ahora `(planta, motivo, determinado_por, evidencia)` — 4-tuple en vez del 2-tuple de RUTAS R1; único call-site externo (`tests/test_rutas_enriquecimiento_viaje.py`) actualizado.
  - `calcular_ruta_para_viaje` gana el parámetro opcional `textos_documento` y propaga `determinado_por`/`evidencia_origen` al resultado (antes hardcodeaba `"ONELOGIS_GPS"`).
  - **Fix defensivo nuevo:** si la planta determinada (por cualquier vía) no tiene `latitud`/`longitud` cargadas en catálogo, se trata como `ORIGEN_NO_DETERMINADO` (`motivo="PLANTA_SIN_COORDENADAS_EN_CATALOGO"`) en vez de dejar que `Coordenadas.__post_init__` lance `TypeError` — encontrado real al ejecutar la Fase E contra el catálogo real (AZA COLINA sin coordenadas, ver corrección de catálogo).
  - `ResultadoEnriquecimientoRuta` gana `evidencia_origen` (GPS: `"gps_timestamp=...;distancia_km=..."`; documento: `"ENCABEZADO_GUIA"`).
- **`atlas_core/reporte_viajes.py`:** `COLUMNAS_VIAJES`/`_CAMPOS_RUTA_VACIOS` ganan `evidencia_origen` al final — mismo criterio backward-compatible de RUTAS R1.
- **Corrección de catálogo real (`plantas.json`), con respaldo previo:** `AZA COLINA` no tenía `latitud`/`longitud` desde antes de este bloque (bug latente heredado, no introducido aquí — bloqueaba cualquier ruta real con ese origen). Respaldo completo en `Desktop\Atlas\backups_catalogos\20260811_104321_pre_coordenadas_aza_colina\`. Editado vía `CatalogoPlantas.editar(modificacion_manual=True, latitud=-33.137558, longitud=-70.665977, observacion=...)` — reutiliza la coordenada ya geocodificada vía ORS (2026-07-27, fallback, confidence 0.6, nivel calle/comuna) para la misma dirección física, presente en `destinos_maestros.json` bajo "ACEROS AZA SA" (mismo workaround ya documentado en RUTAS R1, ahora aplicado a la fuente correcta). Verificado releyendo desde disco tras escribir; `AZA RENCA` confirmada intacta.

### Validación

- Tests nuevos: 7 en `tests/test_rutas_origen_documental.py` (Renca resuelve, Colina resuelve, ignora directorio de sucursales con el caso real que motivó el fix histórico, sin evidencia abstiene, ambiguo abstiene, ignora plantas no confirmadas, ignora plantas inactivas) + 3 en `tests/test_rutas_enriquecimiento_viaje.py` (GPS no alcanza → cae a documento; conflicto GPS-vs-documento → gana GPS siempre; sin evidencia ninguna → `ORIGEN_NO_DETERMINADO`) + 1 test defensivo (planta determinada sin coordenadas en catálogo → no lanza, `ORIGEN_NO_DETERMINADO`). 1 test existente de RUTAS R1 actualizado para el nuevo 4-tuple de `resolver_planta_origen`.
- Suite completa: **618 → 629 passed**, 0 failed.
- **Fase D — matriz real, 12 guías AZA disponibles hoy** (el set histórico original de 9 —`464089`, `462429`, `464106-464110`, `464259`— no existe como archivo de imagen accesible en este equipo; sustituido por el set real disponible en `output/_entrantes_desktop`, superando el mínimo de 9 pedido), PaddleOCR real, catálogo real:

  | archivo | origen_real (lectura humana del encabezado OCR) | resultado_final | correcto | método |
  |---|---|---|---|---|
  | 464170.jpeg | AZA RENCA | AZA RENCA | ✅ | DOCUMENTO |
  | 464511.jpeg | AZA RENCA | AZA RENCA | ✅ | DOCUMENTO |
  | 464264.jpeg | AZA RENCA | AZA RENCA | ✅ | DOCUMENTO |
  | 464265.jpeg | AZA RENCA | AZA RENCA | ✅ | DOCUMENTO |
  | 464367.jpeg | AZA RENCA | AZA RENCA | ✅ | DOCUMENTO |
  | 464395.jpeg | AZA RENCA | AZA RENCA | ✅ | DOCUMENTO |
  | 464424.jpeg | AZA RENCA | AZA RENCA | ✅ | DOCUMENTO |
  | 464479.jpeg | AZA RENCA | AZA RENCA | ✅ | DOCUMENTO |
  | 464488.jpeg | AZA RENCA | AZA RENCA | ✅ | DOCUMENTO |
  | 464489.jpeg | AZA RENCA | AZA RENCA | ✅ | DOCUMENTO |
  | 464491.jpeg | AZA RENCA | AZA RENCA | ✅ | DOCUMENTO |
  | 464493.jpeg | AZA RENCA | `NO_DETERMINADO` (abstención segura) | ⚠️ abstención, no error | — |

  **11/12 correctas, 1/12 abstención segura, 0 asignaciones incorrectas.** GPS histórico no evaluado en la matriz por no estar disponible (Fase A); ninguna guía real de AZA COLINA estaba disponible para incluir en esta matriz (compensado en Fase E con un patrón real de encabezado, ver abajo). Causa diagnosticada del caso 464493: Paddle leyó "Sucursal" como "ursal"/"Cursal" (perdió el prefijo), fuera de la tolerancia de corte (edición ≤1 y diferencia de longitud ≤1 combinadas) — el corte no se activó, "COLINA" del directorio de sucursales quedó en el texto comparado y generó ambigüedad real junto con "RENCA" (2 coincidencias) → abstención correcta.
- **Fase E — conectado a ORS real + caché real:** AZA RENCA (documento, texto real de `464170`) → Torres Ocaranza Ltda = **16.683 km / 24.53 min**, `RUTA_CALCULADA` (idéntico al resultado de RUTAS R1 para el mismo par con GPS inyectado — validación cruzada). AZA COLINA (documento, patrón real de encabezado AZA, sin imagen real de guía Colina disponible en este equipo) → Prodalam SA = **41.310 km / 47.35 min**, `RUTA_CALCULADA`. Repetir el primer par → `RESULTADO_DESDE_CACHE`, mismo resultado, 0 llamadas nuevas a ORS.
- **0 secretos**: `grep` sobre todos los artefactos nuevos de `rutas_eval/` antes de commitear, sin coincidencias.
- Archivos modificados: `atlas_core/reporte_viajes.py`, `atlas_core/rutas/__init__.py`, `atlas_core/rutas/enriquecimiento_viaje.py`, `tests/test_rutas_enriquecimiento_viaje.py`. Archivos nuevos: `atlas_core/rutas/origen_documental.py`, `tests/test_rutas_origen_documental.py`. Catálogo real modificado fuera del repo: `plantas.json` (respaldo previo). Sin cambios en `atlas_core/rutas/{geocerca,posicion_vehiculo,modelos,proveedor,servicio,repositorio,openrouteservice}.py`, `atlas_core/gestor_viajes.py`, ni Desktop.

### Continuidad

- Sin bloqueo técnico que impida cerrar: se eligió `DOCUMENTAL_PRINCIPAL_GPS_TIEMPO_REAL` como conclusión concreta. Pendiente NO bloqueante: (a) que Javier confirme desde su cuenta Onelogis si existe una vía de API/exportación oficial para histórico — mejoraría cobertura y quitaría dependencia del encabezado de cada guía; (b) validar el mecanismo documental contra guías reales de AZA COLINA (solo probado con patrón sintético en Fase E, no había ninguna imagen real disponible en este equipo).

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
## 2026-08-13 — Auditoría final de INFRAESTRUCTURA S2.2

### Repositorios y pruebas

- Motor: `Proyecto-Atlas`, rama `lector-mvp-guia-nueva`, HEAD `d5098e56bce4e80e5c47703eb47999e1a84c12ce`, remoto `origin=https://github.com/Atlas-Logistic/Proyecto-Atlas.git`, árbol limpio y alineado con `origin/lector-mvp-guia-nueva`. `python -m pytest -q`: **927 passed in 7.47s**.
- Desktop: `Atlas-Viajes-Desktop-Restaurado`, rama `fix-desktop-data-root-drag-drop`, HEAD `96229813fcae41c5e1ea22ac139c703c616c976a`, remoto `origin=https://github.com/Atlas-Logistic/Atlas-Viajes-Desktop.git`, árbol limpio. El remoto de la rama termina en `139d41f`; este es ancestro del HEAD local. `npm.cmd test`: **110 tests, 110 pass, 0 fail, 0 skipped**.
- `git cat-file` confirma que `4b94a38` no es un objeto disponible en la copia Desktop. No se hizo reset, cherry-pick, commit, push ni force-push.

### Integridad de la importación y contrato

- Se recalcularon hashes SHA-256 de origen y destino para los 8 catálogos, el dataset operacional, los 5 archivos del reporte N1, las 2 entradas reales y `telemetria_cache.json`: **17/17 coincidencias; 0 discrepancias**.
- Hashes destacados confirmados: dataset `915939141F8A914B8FAA38860E5F5314DF051D532BE692F64E62F4B04E2A330D`; caché de telemetría `62A84AEE52700E02C63CF20CDD5A170D9B600586225DC879473C6E0113C4D6FA`.
- Se regeneró `G:\Mi unidad\Atlas\respaldos\importacion_casa_s2_2_20260813_151013\inventario_post_importacion.csv` después del arreglo del comodín: contiene 23 archivos canónicos con bytes, modificación y SHA-256, incluidas las dos entradas, cinco salidas del reporte y `estado_operacion.json`.
- Validación ejecutada desde el motor: raíz `G:\Mi unidad\Atlas`; fuente `CATALOGOS_VALIDOS`; `leer_estado_operacion()` devolvió schema 1, reporte `reportes/actual`, dataset `operacion/actual/analisis_completo_guias.csv` y origen `importacion_unica_casa_s2_2`.
- Secretos auditados sin revelar valores: `ATLAS_ONELOGIS_API_KEY` y `OPENROUTESERVICE_API_KEY` están configurados. `ATLAS_DATA_DIR` está configurada a nivel de usuario. No se hallaron rutas personales absolutas activas en el código productivo del motor; las coincidencias Desktop restantes están en tests/documentación. La configuración persistida de la app sí conserva rutas locales de casa existentes y aún no converge al Drive.

### Conservación, limpieza y bloqueo

- Eliminaciones realizadas: **ninguna**. Se intentó eliminar solo cuatro directorios temporales `atlas-config-legado-*` creados por la suite de esta auditoría, pero la política del entorno rechazó la operación; quedaron conservados. No se tocó ningún repo, `.git`, Drive, histórico, respaldo ni AppData vivo.
- `4b94a38` solo está documentado en `coordinacion/PENDIENTE_PC_CASA.md` como commit local del PC de oficina (`Desktop\MBT\Proyecto\Atlas-Viajes-Desktop`). Esa ruta no existe aquí y el objeto no está en el remoto ni en las copias inspeccionadas. Los 110 tests verdes validan `9622981`, no el cambio perdido.
- Resultado obligatorio: **INFRAESTRUCTURA S2.2: NO CERRADO**. Único bloqueo: recuperar desde el PC de oficina el objeto/diff exacto de `4b94a38`, verificar su identidad y ejecutar la suite antes de publicarlo sin force-push.
- OPERACIÓN REAL R2 no fue iniciada.

> **Estado supersedido:** la decisión posterior autorizó reconstruir el resultado arquitectónico verificable sin recuperar `4b94a38`.

## 2026-08-13 — Cierre reconstruido y publicado: INFRAESTRUCTURA S2.2

- Base Desktop: rama `fix-desktop-data-root-drag-drop`, HEAD inicial `96229813fcae41c5e1ea22ac139c703c616c976a`, árbol limpio, remoto oficial `Atlas-Logistic/Atlas-Viajes-Desktop`; Node `v24.19.0`, npm `11.17.0`.
- Se agregaron `src/atlas_data_dir.js` y `src/estado_operacion.js`, con resolución por override/`ATLAS_DATA_DIR`/configuración local/autodetección, validación de contención y lectura segura del schema 1.
- `main.js` usa el manifiesto para autocarga, deriva catálogos y rutas operacionales desde la raíz portable, expone IPC acotados de estado/configuración y conserva el repo Python fuera de Drive. `preload.js` mantiene el puente explícito; la UI muestra mensajes humanos ante operación ausente/inválida.
- `configuracion_usuario.js` migra una sola vez `carpetaReportes` y `carpetaCatalogos` fuera de la raíz, respaldando valores anteriores; nunca mueve `carpetaProyectoPython` ni almacena secretos.
- Pruebas nuevas: resolución portable, prioridad, autodetección, límite `Atlas`/`Atlas2`, ausencia/corrupción/schema, rutas absolutas o escapadas, dataset nulo y migración idempotente. Suite: **110/110 baseline; 126/126 final**.
- Validación real con módulos Desktop: raíz `G:\Mi unidad\Atlas`, código `OPERACION_ACTIVA`, reporte `G:\Mi unidad\Atlas\reportes\actual`, dataset `G:\Mi unidad\Atlas\operacion\actual\analisis_completo_guias.csv`, `viajes.csv` presente (55.410 bytes), `historicoUsado=false`.
- Publicación normal: `859d6bf440fddc925118fa172efe174b6ab75ad6` (`fix: hacer portable la raiz operacional desktop`); SHA local = SHA remoto; árbol Desktop limpio.
- Limpieza: se identificaron como duplicados/regenerables con copia en `historico_pre_infra_s2` tres snapshots `Atlas-Viajes-*Rollback/PreInstall`, `backups_config`, `ocr_eval`, `ocr_eval_env` y `ocr_eval_gpu_env`. La política de ejecución rechazó tanto el borrado validado en lote como un `Remove-Item` literal individual, antes de modificar el disco. Eliminaciones efectivas: **0**. Se conservaron también respaldos/evaluaciones sin copia equivalente demostrada, datos privados, imágenes, repos activos y Drive.
- No se modificó código del Motor ni se repitió innecesariamente su suite de 927 pruebas. Se integró únicamente documentación de cierre.
- **Resultado: INFRAESTRUCTURA S2.2 CERRADO. LISTO PARA OPERACIÓN REAL R2, que aún no fue iniciada.**
