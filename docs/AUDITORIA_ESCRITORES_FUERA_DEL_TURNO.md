# Auditoría: escritores fuera del turno oficial

**Base y alcance**
* Motor `ed84c94`; Desktop instalado en CASA `app.asar` SHA-256 `b091419b…` (leído sin
  modificarlo). Su `instalacion_consulta.js`, `operacion_desktop.js` y `consulta_python.py` son
  idénticos al repositorio Desktop `59abac1`.
* Sólo lectura de código. La configuración de CASA se leyó en sólo lectura: las claves no
  secretas de la política, los nombres de variables de entorno y las tareas programadas.
* Pruebas sintéticas aisladas: `tests/test_auditoria_escritores_turno.py`, 13 pruebas.
* No se corrigió nada ni se tocó G:, Cloud u OFICINA.

## 1. Mecanismos reales (siguiendo el flujo hasta la escritura)

| Mecanismo | Dónde | Qué comprueba | Límites verificados |
| --- | --- | --- | --- |
| **Guardia de exclusión** (audit hook) | `atlas_core/__init__.py` la instala al importar `atlas_core`; `exclusion_local._guardia` (`:499`), `raices_protegidas` (`:446`) | Rechaza (`EscrituraSinTurno`) toda escritura `open`/rename/mkdir/remove/`shutil.copyfile`/`CopyFile2` en una **raíz protegida** si el proceso no **posee el turno local** (`posee_turno`, `:416`). | Sólo comprueba el **turno local, no el lease**. Las raíces protegidas son `ATLAS_EXCLUSION_RAICES`, más `ATLAS_DATA_DIR` y la raíz de la política (`LOCALAPPDATA\Atlas\desktop_operacion.json`) **si son compartidas** (`compartida`, `:109`). Compara la ruta **textual** (`abspath`, sin resolver alias). Sólo actúa en procesos que importan `atlas_core`. |
| **Turno local + lease Cloud** | `LeaseEscritorOperativo`; `vigente` (`escritor_operativo.py:159`) | Exclusión entre escritores gobernados, local y entre PCs. | Al perder el lease sólo se marca `_perdido` (`:299`); **el turno local sigue tomado**, así que la guardia sigue permitiendo escribir. |
| **Sesión Desktop** | `desktop_operacion.sesion` (`:126`), hook `_auditar` (`:79-103`), `ejecutar` (`:296`), scripts en el mismo proceso con `runpy` (`_cli`, `:220`), lista `ESCRITORES` (`:27`) | Turno + lease. El hook bloquea `open`/rename/mkdir/remove si `vigente` es falso y rechaza procesos externos. | El hook **no audita `shutil.copyfile` ni `_winapi.CopyFile2`**: `shutil.copy2` en Windows no emite `open` de escritura. |
| **PULL** | `sincronizar_mobile_cloud.ejecutar_pull_con_escritor`; `guardia_pull.proteger_escrituras` (`:38`) | Lease por pasada; el hook bloquea al perder el lease. | Mismo hueco que la sesión Desktop con `CopyFile2`. |
| **Desktop instalado, proceso Electron** | `instalacion_consulta.js`: `proteger(fs)` (`:157`) y `cp[api]=throw` (`:161`), **incondicionales**; `comprobar` bloquea `G:\`, `C:\Atlas\Proyecto-Atlas` y las raíces configuradas (`:31-41`) | Electron no puede escribir en G: (salvo `exportaciones`) ni lanzar procesos, salvo el canal gobernado y el de consulta. | Sólo protege el `app.asar` que lo contiene. |
| **Lectores de Desktop** | `ejecutarConsulta` (`instalacion_consulta.js:164`) + `consulta_python.py` (`solo_lectura`, `:23`) | Sólo lanza los lectores de la lista, y `retomar` sólo con `--listar`. En Python bloquea `open` de escritura, `os.*`, procesos y sockets. | **No bloquea `shutil.copyfile` ni `_winapi.CopyFile2`.** |

**Estado de CASA verificado en sólo lectura:**
* La política `LOCALAPPDATA\Atlas\desktop_operacion.json` existe, con `raiz = G:\Mi unidad\Atlas`,
  `habilitada` y `autorizada` en `true` y `modo_escritor = lease_cloud`. Por eso, en el perfil
  de Javier, cualquier proceso Python del Motor trata G: como raíz protegida, y Desktop opera en
  modo «preparado» (canal gobernado).
* No hay `ATLAS_EXCLUSION_*` ni `ATLAS_DATA_DIR` definidas.
* La tarea «Atlas Mantenimiento tecnico» está deshabilitada; usa `--tarea-programada`
  (`ejecutar_mantenimiento_pendientes_tecnicos.ps1:35`).
* No había procesos `python.exe` en ejecución.

## 2. Matriz

| # | Camino (punto de entrada real) | Fuente afectada | Protección | Clasificación | Evidencia |
| --- | --- | --- | --- | --- | --- |
| A1 | **Electron legado**: `atlas:procesar-imagenes` → `procesarImagenesDesktop` rama no preparada → `fs.mkdirSync` + `fs.copyFileSync` a `operacion/entradas/<marca>` (`main.js` instalado `:1388`, `:1399-1411`) | evidencia (entradas), luego dataset vía los scripts | Con política habilitada no se entra en esa rama (`:1402`). Si se entrara, `instalacion_consulta.js` bloquea mkdir, copia, escritura y procesos. | **PROTEGIDO** en CASA (instalado `b091419b`) | `test_ruta_legada_electron_bloqueada_por_modo_consulta`; lectura de `main.js` y `operacion_desktop.js:11-14` |
| A2 | Mismo camino en **OFICINA** | ídem | Depende de su `app.asar` y su política | **NO VERIFICADO** | No se intervino OFICINA |
| B1 | **Retomar lote** desde Desktop: `atlas:retomar-entrada-desktop` (`:1457`) → `ejecutarPython(['retomar_entradas_desktop.py','--lote',…])` | entradas, dataset, bandeja | Preparado: `ejecutarPython` deriva a `operacionDesktop.ejecutar` (`:1253-1256`), es decir turno + lease + sesión. No preparado: `ejecutarConsulta` rechaza `--lote` (`instalacion_consulta.js:166`). | **PROTEGIDO** (CASA) | lectura del código instalado |
| B2 | `retomar_entradas_desktop.py` **a mano** | ídem | Sólo la guardia (`entradas_desktop.py:148` toma `bloqueo_sesion`, no el turno) | **PROTEGIDO condicional** (ver C1) | igual que C1 |
| C1 | **CLIs manuales sin gobierno propio**: `reproceso_cuarentena.py`, `aplicar_decision_pendiente.py` (fuera de Desktop), `analizar_guias_masivo.py`, `reprocesar_lote_reparador.py`, `investigacion_documental.py`, `investigar_revision_b1.py`, `operaciones_conversacionales_cli.py`, `migrar_destinos_globales.py`, `migrar_observaciones_a_eventos.py`, `asociar_evidencias_pdf_existentes.py`, `alta_mobile_lote.py`, `crear_usuario_mobile.py`, `inicializar_fichas_choferes.py`, `perfilar_aplicacion_decision.py`, `atlas.py`, `mantener_pendientes_tecnicos.py` **sin** `--tarea-programada` (`:69`) | dataset, ledger, bandeja, catálogos, fichas, evidencia | Sólo la guardia de exclusión | **PROTEGIDO condicional**: bloquea la **primera** escritura en la raíz sin dejar nada parcial, siempre que se cumplan las condiciones de C2 y C3 | `test_cli_manual_sin_turno_bloqueado` (3 CLIs reales: lock, dataset y bandeja intactos); `test_escritor_real_sin_turno_bloqueado_por_la_guardia` |
| C2 | Proceso del Motor **sin política ni raíz declarada**: otro usuario o perfil, tarea con otra cuenta, `LOCALAPPDATA` distinto, OFICINA sin política | todas | Ninguna: `raices_protegidas()` vacío | **VULNERABLE** (demostrado en sintético; en CASA no ocurre con el perfil de Javier) | `test_vulnerable_proceso_sin_politica_ni_raiz_declarada` |
| C3 | Ruta por **alias** (junction, enlace, unidad `subst`, UNC frente a letra) | todas | La guardia compara texto, sin `realpath` | **VULNERABLE** (demostrado con junction; riesgo práctico bajo, requiere crear el alias) | `test_vulnerable_alias_por_junction` |
| C4 | `migrar_relaciones_operacionales.py --sin-escritor` (`:72`) | registros de relaciones y catálogos | La guardia lo bloquea en la raíz protegida (el flag no la evade) | **PROTEGIDO condicional** | `test_cli_manual_sin_turno_bloqueado[migrar…]` |
| D1 | **CLIs con lease propio que sólo comprueban al inicio**: `migrar_relaciones_operacionales._con_escritor` (`:46-55`), `mantener_pendientes_tecnicos.pasada_programada` (`:42-55`, la tarea programada) | relaciones; dataset, bandeja, pendientes técnicos | Turno + lease al inicio. Si el lease se pierde, el turno local queda, la guardia permite y nada vuelve a comprobar. | **VULNERABLE** (demostrado: escribe con `vigente == False`) | `test_vulnerable_cli_con_escritor_sigue_escribiendo_tras_perder_el_lease` |
| D2 | CLIs con lease que sí comprueban: `recuperar_envio_mobile_error.py` (`proteger_escrituras`, `:43`), `revalidar_transporte.py` (`puede_escribir`, `:47`, `:61`), `alta_chofer_mobile.py` (`_exigir_vigente` antes de cada grupo, `:183`, `:187`) | envíos, dataset; choferes y usuarios | Lease al inicio y comprobación durante la operación | **PROTEGIDO** (parcial en `alta_chofer`: entre dos comprobaciones; con el hueco `CopyFile2` de E1) | lectura de código |
| E1 | **Sesión Desktop y PULL tras perder el lease** | todas | El hook bloquea `open`/rename; **no** `shutil.copyfile`/`CopyFile2` | **VULNERABLE** (demostrado; impacto bajo: las `copy2` del código hacia la raíz van a temporales o respaldos, p. ej. `acciones_operacionales.py:4336` seguido de `os.replace`, que sí se bloquea) | `test_sesion_desktop_tras_perdida_de_lease`, `test_pull_tras_perdida_de_lease` |
| E2 | **Interrupción entre escrituras** (lease perdido a mitad de operación) | dataset, ledger, bandeja | El bloqueo detiene la operación **después** de la primera escritura | **Escritura parcial demostrada** (no es un camino fuera del turno; confirma el estado `INTERRUMPIDA` del diseño) | mismas pruebas: `primera` escrita, `segunda` bloqueada |
| F1 | **`servidor_mobile.py`** (HTTP local previo a Cloud): `do_POST` (`:227`) → `RepositorioEnviosMobile.recibir` (`:284`) → procesar y revalidar (dataset, bandeja), con varios hilos y sin turno ni lease | envíos Mobile, dataset, bandeja | Sólo la guardia. Ninguna tarea, script ni Desktop lo lanza (`exclusividad_equipo.py:43` lo vigila como proceso). | **PROTEGIDO condicional** en CASA (como C1); su uso en OFICINA está **NO VERIFICADO** | búsqueda de lanzadores; `tasklist` sin procesos |
| F2 | `sincronizar_mobile.py` (sincronización local previa) | envíos, dataset | Sólo la guardia | **PROTEGIDO condicional** | censo |
| G1 | **`plantas.json`**: `gestionar_catalogos.py plantas agregar/editar/desactivar` → `CatalogoPlantas.crear/editar/desactivar` → `_escribir` (`catalogo_plantas.py:258`, `:313`, `:403`, `:451`) | catálogo de plantas | Desde Desktop, gobernado (`gestionar_catalogos.py` está en `ESCRITORES`); a mano, sólo la guardia. La ruta por defecto `catalogos/plantas.json` es relativa al directorio de trabajo (`gestionar_catalogos.py:29`). | **PROTEGIDO condicional** | lectura de código |
| G2 | **`rutas.json`**: `gestionar_catalogos.py rutas calcular` → `RepositorioRutas.guardar` (`rutas/repositorio.py:54`, `:94`; `gestionar_catalogos.py:426`) | catálogo de rutas | ídem (relativa por defecto, `:32`) | **PROTEGIDO condicional** | ídem |
| G3 | **`empresas.json`** | catálogo de empresas | **No hay escritor** en el Motor (`atlas_core` ni scripts) ni en Desktop (`catalog_status.js` sólo lee) | **NO VERIFICADO**: escritor no localizado; cualquier cambio viene de fuera del Motor | búsqueda completa |
| H1 | **`operacion/procesamiento/`** | (en la semilla de custodia) | **No hay código** del Motor ni de Desktop que construya o escriba esa ruta | **NO VERIFICADO**: escritor no localizado | búsqueda completa |
| H2 | **`fichas_digitales/`**: `fichas_choferes` (`inicializar_almacen` `:281`, `registrar_licencia_chofer` `:340`), `expediente_digital`, `revision_vehiculo_mobile`, `correccion_fechas_documentales` | fichas y expediente | Desde Desktop (`registrar_licencia_chofer.py` con `sesion`; los demás en `ESCRITORES`) y PULL (licencias), gobernados. `inicializar_fichas_choferes.py` sólo a mano, con la guardia. | **PROTEGIDO** (Desktop/PULL) / **PROTEGIDO condicional** (manual) | censo; `registrar_licencia_chofer.py:19` |
| I1 | **Lectores de Desktop** (`consultar_atlas`, `b1_consulta`, `construir_fichas_catalogos`, `retomar --listar`) bajo `consulta_python.py` | (no deberían escribir) | Bloquea `open` de escritura y `os.*`; **no** las copias `shutil` | **VULNERABLE** (demostrado: una copia `shutil.copy2` pasa). Riesgo teórico: no se encontró un lector actual que copie. | `test_envoltorio_solo_consulta_bloquea_escrituras_salvo_copias` |
| J1 | **Procesos ajenos al Motor**: cliente Drive, Explorador, PowerShell, agentes, Drive web | todas | Ninguna: la guardia es un hook de Python dentro del Motor (lo declara su docstring, `exclusion_local.py:45-52`) | **VULNERABLE por diseño** (fuera del alcance del turno) | docstring y C2 |
| K1 | Modo **equipo único** | — | Mutex local sin Cloud | No activo en CASA (`modo_escritor = lease_cloud`) | política leída |

Además se verificó que con turno la escritura procede (`test_con_turno_la_escritura_procede`) y
que un segundo proceso no obtiene el turno ni escribe mientras otro lo tiene
(`test_competencia_con_turno_activo`).

**Simultaneidad con PULL:**
* PULL toma turno + lease en cada pasada.
* Un CLI manual sin turno queda bloqueado (C1).
* Un CLI con lease espera `ESCRITOR_OCUPADO`; la sesión Desktop espera hasta 150 s.
* Electron legado está bloqueado.

Sólo pueden escribir **a la vez que PULL**: C2, C3 y J1, y D1 o E1 después de perder el lease (cuando
otro equipo ya pudo tomarlo).

## 3. Prioridades

| Prioridad | Camino | Impacto | Por qué |
| --- | --- | --- | --- |
| **1** | **D1**: CLIs con lease que no vuelven a comprobar (tarea de mantenimiento, migraciones) | dataset, bandeja, relaciones, con dos escritores entre PCs | Demostrado. Ocurre ante un corte de red o de Cloud, sin error humano. |
| **2** | **C2**: proceso del Motor sin política ni raíz declarada | todas las fuentes | Demostrado. Basta otro perfil o una tarea de otra cuenta. OFICINA no está verificada. |
| **3** | **J1 / G3 / H1**: escritores ajenos o no localizados (`empresas.json`, `operacion/procesamiento`) | catálogos y estado sin trazabilidad | Hoy no se sabe quién escribe. |
| 4 | **C3**: alias de ruta | todas | Demostrado, pero requiere crear el alias. |
| 5 | **E1 / I1**: copias `CopyFile2` tras perder el lease o desde lectores | bajo (temporales y respaldos) | Demostrado; no hay copia operacional en el código actual. |
| — | **A2 / F1**: Desktop y servidor Mobile en OFICINA | — | Verificar antes de concluir. |

## 4. Punto mínimo de guardia propuesto (sin implementar)

| Camino | Punto mínimo | Por qué ahí |
| --- | --- | --- |
| D1 | Envolver `operacion()` en `guardia_pull.proteger_escrituras(raiz, lambda: escritor.vigente)` dentro de `migrar_relaciones_operacionales._con_escritor` y de `mantener_pendientes_tecnicos.pasada_programada`, como ya hace `recuperar_envio_mobile_error.py:43`. | Reutiliza un mecanismo existente y probado; no toca locks ni el lease. |
| C2 | En `exclusion_local.raices_protegidas`: proteger también la raíz operacional que el proceso resuelve (`almacenamiento_portable.resolver_raiz_atlas()` o `ContextoEmpresa.raiz`) cuando es compartida, aunque falten política y `ATLAS_DATA_DIR`. | Es el único punto común a todo proceso del Motor. |
| C3 | En `exclusion_local._guardia` y `normalizar_raiz`: comparar con `os.path.realpath` (destino y raíces) además de la ruta textual. | Cierra junction, enlaces y `subst` sin cambiar la semántica. |
| E1 | Agregar `shutil.copyfile` y `_winapi.CopyFile2` (destino `args[1]`) a los eventos de `desktop_operacion._auditar` (`:79`) y `guardia_pull._auditar` (`:10`). | La guardia de exclusión ya los reconoce (`_destinos`); falta en los hooks del lease. |
| I1 | Agregar esos dos eventos a `consulta_python.solo_lectura` (Desktop: requiere un encargo Desktop). | Mismo hueco en el envoltorio de lectura. |
| J1 / G3 / H1 | No hay punto en el Motor. Revisar en sólo lectura el historial de revisiones de Drive de `empresas.json` y de `operacion/procesamiento/`, o preguntar a Javier, y documentar su escritor. | No se diseñan locks nuevos; primero hay que localizarlo. |
| A2 / F1 | Leer en sólo lectura el `app.asar` y la política de OFICINA (SHA, `habilitada`, `autorizada`, `raiz`) y la lista de tareas. | No requiere cambios. |

## 5. Limitaciones

* **Escenarios sintéticos.** La raíz protegida se simuló con una carpeta cuyo nombre contiene
  «Google Drive», la misma regla `compartida` que reconoce G:. No se probó contra G: real ni con
  el cliente de Drive. **Que la guardia bloquee en G: real queda inferido**, por código y
  configuración, **no demostrado** allí.
* El lease se simuló: el turno local es real y la pérdida del lease es un indicador falso,
  porque las pruebas no usan Cloud.
* El censo de CLIs es estático: lista de `ESCRITORES`, búsqueda de lease o sesión y patrones de
  escritura. Un script marcado «escritura posible» puede no escribir en la raíz, pero eso no
  cambia su protección, que es la guardia.
* No se verificó OFICINA, ni el comportamiento de Windows con otra cuenta real, ni las
  ejecuciones bajo SYSTEM.
* La equivalencia entre el Desktop instalado y el repositorio vale para
  `instalacion_consulta.js`, `operacion_desktop.js` y `consulta_python.py`. `main.js` instalado
  difiere en 80 líneas, ninguna en los caminos auditados (procesar imágenes, retomar,
  `ejecutarPython`).
