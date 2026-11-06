# Exclusión local de escritores (Etapa 1, condición C1)

Referencia: `C:\Atlas\pruebas\diseno-publicacion-coherente-20261106\VALIDACION.md`, condición C1.

## Qué garantiza

En un mismo equipo Windows, para cada raíz operacional, **un solo proceso del Motor que use los escritores (`LeaseEscritorOperativo` o `EscritorEquipoUnico`) escribe a la vez**. La garantía cubre toda la sección crítica, no solo la adquisición del lease.

| Pieza | Dónde | Qué hace |
|---|---|---|
| Turno local | `atlas_core/exclusion_local.py` (`TurnoEscritura`) | Mutex con nombre de Windows `Global\AtlasEscritorTurno-<sha256(raíz)>`. Lo posee un hilo dedicado, así que el turno pertenece al **proceso**. Es reentrante dentro del proceso y `soltar()` es idempotente |
| Integración | `LeaseEscritorOperativo.adquirir/cerrar` y `EscritorEquipoUnico.adquirir/cerrar` | El turno se toma **antes** de consultar Cloud y se suelta **al final** de `cerrar()`, después de confirmar la custodia, detener el heartbeat e intentar liberar el lease. PULL, sesión Desktop, B1, mantenimiento (`--tarea-programada`), migración y `estado_confirmado --sembrar` lo heredan sin cambios propios |
| Guardia | Audit hook que se instala al importar `atlas_core` | Defensa adicional, con la cobertura acotada que se detalla más abajo |

## Esperas, fallos y liberación (contrato)

- **Esperas acotadas.** Toda espera es finita. `espera_segundos` infinita, NaN o negativa → `ValueError`.
  - La espera del mutex dura lo que se pidió más `MARGEN_RESPUESTA_SEGUNDOS` (5 s) para que el hilo dueño responda.
  - La transición de una raíz dentro del proceso tiene un plazo adicional de `PLAZO_LIBERACION_SEGUNDOS` (10 s).
- **Fallo del hilo dueño.** Si fallan la carga de `kernel32`, `CreateMutexW`, `WaitForSingleObject` o `start()`, o si el hilo no responde a tiempo, `adquirir()` lanza `ErrorTurno` (un `OSError`). Nunca lo trata como turno obtenido ni deja al llamador esperando.
  - Si el hilo tardío toma el mutex después, lo libera de inmediato, porque la orden de soltar ya está dada.
- **Ocupado.** Si otro proceso tiene el turno, `adquirir()` devuelve `False`. En los escritores, esto se traduce en `ocupado=True` y `motivo="ESCRITOR_LOCAL_OCUPADO"`, **sin llamar a Cloud**:
  - Desktop reintenta con su espera acotada (150 s).
  - PULL omite el ciclo (`NO_ADQUIRIDO`).
  - Mantenimiento omite la pasada.
- **Cierre.** `LeaseEscritorOperativo.cerrar()` ejecuta cada paso aunque falle el anterior, mediante `try/finally` anidados: custodia, heartbeat, liberación del lease y, al final, el turno. `EscritorEquipoUnico.cerrar()` hace lo mismo con su propio mutex.
  - **El turno se suelta ante cualquier excepción.** La excepción se propaga encadenada; nunca se oculta.
  - Si la liberación del mutex no puede confirmarse, `soltar()` lanza `ErrorTurno`. En ese caso el proceso ya no se considera dueño (la guardia rechaza) y otro proceso verá el mutex ocupado hasta que el hilo termine: falla cerrada, y visible.
- **Hilos y raíces.** Cada raíz tiene su propia transición (`adquirir`/`soltar`), que se mantiene hasta que el mutex quedó tomado o liberado.
  - Otro hilo nunca ve el mutex "a medio soltar"; espera la transición y lo obtiene. Esto corrige el falso "ocupado" que encontró Codex.
  - El registro global solo se toma por instantes, nunca durante una espera ni una E/S. Un hilo nunca sostiene la transición de dos raíces a la vez.
  - Entre procesos, las esperas cruzadas sobre dos raíces terminan dentro de su plazo, sin interbloqueo.

## Interrupción y abandono

- Si el proceso termina por cualquier motivo (`TerminateProcess`, `os._exit`, caída), el kernel libera el mutex. **Nunca queda bloqueado por una interrupción.**
- Una excepción, incluida `KeyboardInterrupt`, dentro de `with TurnoEscritura` o después de tomar el mutex libera el turno y se propaga.
- **Señal de abandono.** Windows solo informa `WAIT_ABANDONED` si otro proceso mantenía el mutex abierto. Por eso el abandono se detecta con un **marcador local** (`%LOCALAPPDATA%\Atlas\cache\exclusion_local\turno_<sha>.json`):
  - Lo escribe y lo borra solo quien posee el mutex.
  - Si existe al adquirir, el dueño anterior terminó sin soltar → `abandonado=True`, y queda anotado en `abandonos.jsonl`.
  - El marcador es **por perfil** (`LOCALAPPDATA`): la señal no cruza usuarios distintos.
  - La **recuperación** de operaciones interrumpidas no forma parte de esta etapa.

## Raíces protegidas y modos

`exclusion_local.raices_protegidas()` considera tres fuentes:
- `ATLAS_EXCLUSION_RAICES`: rutas explícitas separadas por `;`.
- `ATLAS_DATA_DIR`, si es compartida.
- La `raiz` de la política de operación (`ATLAS_OPERACION_CONFIG` o `%LOCALAPPDATA%\Atlas\desktop_operacion.json`), si es compartida.

"Compartida" significa UNC, una unidad distinta de C:, OneDrive o Google Drive.

Modos (`ATLAS_EXCLUSION_LOCAL`):
- `exigir` (por defecto): rechaza la escritura.
- `observar`: la anota.
- `desactivada`: no hace nada.

**`observar` y `desactivada` no protegen** (prueba `test_limite_modos_observar_y_desactivada_no_protegen`). Son solo palancas de reversión.

## Cobertura real de la guardia

La guardia compara **rutas textuales** (`abspath` + `normcase`) en los eventos de auditoría de Python que se listan a continuación.

**Cubierto**, demostrado en `test_guardia_cubre_estas_operaciones_por_ruta`:
- `open` en `w`, `a`, `x` y `r+`; `os.open` con `O_CREAT`; `Path.touch` y `write_text`.
- `os.replace` y `os.rename`; `os.remove`; `os.mkdir` y `os.makedirs`; `os.rmdir`.
- `shutil.rmtree`, `shutil.copy`, `shutil.copy2`, `shutil.copytree` y `shutil.move`.
- `os.truncate` (por ruta), `os.chmod`, `os.utime` y `os.link`.

`shutil.copy2` y el respaldo de `shutil.move` usan `_winapi.CopyFile2` nativo en Python 3.12 sobre Windows, sin generar un evento `open`. Estaban **fuera de cobertura en 1364fd1** y ahora se interceptan mediante los eventos `shutil.*` y `_winapi.CopyFile2`.

**No cubierto.** No se afirma protección; cada caso tiene una prueba `test_limite_*`:

| Caso | Prueba |
|---|---|
| **Descriptor abierto antes** (con turno, o antes de importar `atlas_core`): `os.write` y `f.write` sobre un descriptor existente no se auditan | `test_limite_descriptor_abierto_antes_escribe_sin_turno` |
| **Llamadas nativas** (`ctypes` `CreateFileW`/`WriteFile`) | `test_limite_llamada_nativa_escribe_sin_turno` |
| **Alias de ruta**: junction o enlace hacia la raíz y prefijo `\\?\`. Por el mismo motivo tampoco se cubren los nombres cortos 8.3 ni la diferencia entre unidad mapeada y UNC | `test_limite_alias_de_ruta_escribe_sin_turno` |
| **Eventos no listados**, por ejemplo `sqlite3`, que crea y escribe su base sin un `open` auditado | `test_limite_eventos_no_listados_sqlite_escribe_sin_turno` |
| **Procesos ajenos al Motor** (Google Drive, Explorador, Excel, scripts sin `atlas_core`, procesos hijos) | `test_limite_un_proceso_ajeno_al_motor_escribe_aunque_otro_tenga_el_turno` |
| **Otro computador**: el mutex es local | — |
| **Proceso vivo y colgado**: retiene el turno, y los demás fallan cerrado hasta que termina | `test_limite_un_proceso_colgado_retiene_el_turno_hasta_que_termina` |

**Consecuencia.** La exclusión entre escritores del Motor se apoya en el **turno que toman los escritores**, no en la guardia. La guardia evita que código del Motor sin turno escriba por las vías cubiertas.

## Compatibilidad operativa

- Los lectores que Desktop lanza directamente (`b1_consulta_cli`, `consultar_atlas`, `consultar_incidencias_operacionales`, `construir_fichas_catalogos`, `retomar_entradas_desktop --listar`) no escriben y funcionan con `exigir`.
- La sesión Desktop, la pasada PULL completa y el mantenimiento escriben bajo turno.
- **CLIs manuales fuera de Desktop sobre G:** por ejemplo `publicacion_reportes.py`, `crear_usuario_mobile.py`, `reproceso_cuarentena.py` o `servidor_mobile.py`. Con `exigir` fallan cerrados en lugar de escribir sin exclusión. Deben ejecutarse desde Desktop o con un turno.

## Pruebas

- `tests/test_exclusion_local.py`: procesos reales con concurrencia, espera, `taskkill /F`, `os._exit`, excepción, lease vencido en el mismo equipo, equipo único, 3 × 25 ciclos, guardia, modos y reentrancia.
- `tests/test_exclusion_local_flujos.py`: lectores directos de Desktop, sesión Desktop y pasada PULL con `exigir`.
- `tests/test_exclusion_local_fallos.py`: fallos inyectados y límites.
  - Fallos al adquirir: `kernel32`, `CreateMutexW`, hilo que no responde, `start()` y una interrupción después de tomar el mutex.
  - Fallos al soltar: liberación no confirmada.
  - Fallos al cerrar el lease: en la custodia, la liberación, el heartbeat y el propio turno; y al cerrar el equipo único: en `ReleaseMutex`.
  - Carreras: adquisición durante una liberación pausada, espera en una raíz frente a otra raíz, esperas cruzadas entre procesos y 12 hilos × 40 ciclos.
  - Cobertura de la guardia y sus límites.
