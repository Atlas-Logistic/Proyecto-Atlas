# Exclusión local de escritores (Etapa 1, condición C1)

Referencia: `C:\Atlas\pruebas\diseno-publicacion-coherente-20261106\VALIDACION.md`, condición C1.

## Qué garantiza

En un mismo equipo Windows, para cada raíz operacional, **un solo proceso del Motor que use los escritores (`LeaseEscritorOperativo` o `EscritorEquipoUnico`) escribe a la vez**. La garantía cubre toda la sección crítica, no solo la adquisición del lease.

| Pieza | Dónde | Qué hace |
|---|---|---|
| Turno local | `atlas_core/exclusion_local.py` (`TurnoEscritura`) | Bloqueo de 1 byte (`msvcrt.locking`) en `%LOCALAPPDATA%\Atlas\cache\exclusion_local\turno_<sha256(raíz)>.lock`. Pertenece a un **handle del proceso**: no hay hilo propietario y cualquier hilo puede soltarlo. Un único dueño por proceso y raíz, **sin reentrancia**; `soltar()` es idempotente |
| Integración | `LeaseEscritorOperativo.adquirir/cerrar` y `EscritorEquipoUnico.adquirir/cerrar` | El turno se toma **antes** de consultar Cloud y se suelta **al final** de `cerrar()`, después de confirmar la custodia, detener el heartbeat e intentar liberar el lease. PULL, sesión Desktop, B1, mantenimiento (`--tarea-programada`), migración y `estado_confirmado --sembrar` lo heredan sin cambios propios |
| Guardia | Audit hook que se instala al importar `atlas_core` | Defensa adicional, con la cobertura acotada que se detalla más abajo |

## Esperas, fallos y liberación (contrato)

- **Orden.** Físico primero, lógico después: se registra sólo tras bloquear y escribir los datos del dueño. Al soltar se retira primero lo lógico (la guardia ya rechaza) y lo físico se libera en `finally`, con cierre incondicional del handle. Por eso `posee_turno` o `vigente` verdaderos implican el bloqueo concedido por el kernel.
- **Esperas acotadas.** Toda espera es finita. `espera_segundos` infinita, NaN o negativa → `ValueError`.
  - El bloqueo se intenta sin bloquear (`LK_NBLCK`) hasta el plazo pedido.
  - Las transiciones de otros hilos del proceso se esperan como máximo ese plazo más `MARGEN_TRANSICION_SEGUNDOS` (15 s).
- **Ocupado.** Si otro proceso u otra instancia del mismo proceso tiene el turno, `adquirir()` devuelve `False`. En los escritores: `ocupado=True` y `motivo="ESCRITOR_LOCAL_OCUPADO"`, **sin llamar a Cloud**:
  - Desktop reintenta con su espera acotada (150 s).
  - PULL omite el ciclo (`NO_ADQUIRIDO`).
  - Mantenimiento omite la pasada.
- **Sin reentrancia.** Una adquisición anidada de otra instancia recibe `False` (antes fallaba con el 409 de Cloud). La misma instancia, siendo dueña, recibe `True` sin efecto y un único `soltar()` la libera.
- **Fallo del mecanismo.** `open` denegado, caché inaccesible, error de `locking` distinto de "bloqueado", sin espacio para los datos del dueño: `ErrorTurno` (un `OSError`), sin posesión ni handle abierto. Fuera de Windows no hay mecanismo: `ErrorTurno`.
- **Cierre.** `LeaseEscritorOperativo.cerrar()` ejecuta cada paso aunque falle el anterior: custodia, heartbeat, liberación del lease y, al final, el turno. `EscritorEquipoUnico.cerrar()` hace lo mismo con su propio mutex. Si falla `LK_UNLCK`, el handle se cierra igual y se informa `ErrorTurno`.
- **Vigencia.** `vigente` de ambos escritores exige también `turno.vigente`.
- **Hilos.** Cada raíz tiene una transición que serializa `adquirir` y `soltar`, también entre hilos de la misma instancia. La posee un testigo por llamada que se fija dentro del `try` y se borra con una asignación, sin el riesgo de un `Lock` tomado justo antes de una interrupción.

## Interrupción y abandono

- Si el proceso termina por cualquier motivo, el kernel libera el bloqueo. Los hijos no lo conservan: el handle no es heredable.
- Una excepción, incluida `KeyboardInterrupt`, en cualquier punto de `adquirir` o `soltar` deja el turno sin posesión ni bloqueo, y se propaga.
- **Señal de abandono.** El archivo guarda los datos del dueño mientras lo posee (se sobrescriben sin vaciarlo antes) y se vacía al soltar. Si al adquirir no está vacío → `abandonado=True`, anotado en `abandonos.jsonl`.
  - Es por perfil (`LOCALAPPDATA`).
  - Puede dar falsos positivos (terminación tras retirar el registro y antes de vaciar), nunca falsos negativos para dueños registrados.
  - La **recuperación** de operaciones interrumpidas no forma parte de esta etapa.

**Límites declarados, no demostrables más allá de esto:**

| Límite | Consecuencia |
|---|---|
| Una interrupción asíncrona DENTRO del propio bloque de limpieza | Puede saltarse el cierre explícito. Lo lógico sigue sin indicar posesión; el handle se cierra al liberarse su última referencia o al terminar el proceso, y una traza retenida puede demorarlo |
| Usuarios de Windows distintos | No se excluyen: el archivo es por perfil. PULL y Desktop corren como `corte`. Ubicarlo en `%ProgramData%` sería una decisión aparte |
| Liberación diferida | Windows puede demorar el desbloqueo tras la terminación abrupta de un proceso. Medido 0,05–0,08 s, sin cota garantizada: el siguiente puede ver "ocupado" brevemente |
| `locking` informa EACCES también por acceso denegado | Se ve como "ocupado", falla cerrado hasta agotar el plazo |
| Afinidad de hilo del mutex propio de `EscritorEquipoUnico` | Anterior a esta etapa y fuera de alcance |

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
| **Otro computador**: el bloqueo es local | — |
| **Proceso vivo y colgado**: retiene el turno, y los demás fallan cerrado hasta que termina | `test_limite_un_proceso_colgado_retiene_el_turno_hasta_que_termina` |

**Consecuencia.** La exclusión entre escritores del Motor se apoya en el **turno que toman los escritores**, no en la guardia. La guardia evita que código del Motor sin turno escriba por las vías cubiertas.

## Compatibilidad operativa

- Los lectores que Desktop lanza directamente (`b1_consulta_cli`, `consultar_atlas`, `consultar_incidencias_operacionales`, `construir_fichas_catalogos`, `retomar_entradas_desktop --listar`) no escriben y funcionan con `exigir`.
- La sesión Desktop, la pasada PULL completa y el mantenimiento escriben bajo turno.
- **CLIs manuales fuera de Desktop sobre G:** por ejemplo `publicacion_reportes.py`, `crear_usuario_mobile.py`, `reproceso_cuarentena.py` o `servidor_mobile.py`. Con `exigir` fallan cerrados en lugar de escribir sin exclusión. Deben ejecutarse desde Desktop o con un turno.

## Pruebas

- `tests/test_exclusion_local.py`: procesos reales con concurrencia, espera, `taskkill /F`, `os._exit`, excepción, lease vencido en el mismo equipo, equipo único, 3 × 25 ciclos, guardia, modos y ausencia de reentrancia.
- `tests/test_exclusion_local_flujos.py`: lectores directos de Desktop, sesión Desktop y pasada PULL con `exigir`.
- `tests/test_exclusion_local_fallos.py`: cierre del lease y del equipo único con excepciones, esperas entre raíces, cobertura de la guardia y sus límites.
- `tests/test_exclusion_local_bloqueo.py`: F1-F4 de la revisión de b4d0de2; interrupción y terminación en cada punto crítico; solapamiento de intervalos QPC entre procesos; concurrencia de una misma instancia y de 12 hilos; soltar desde otro hilo; herencia a hijos; errores del sistema; pérdida forzada del turno en los escritores.
