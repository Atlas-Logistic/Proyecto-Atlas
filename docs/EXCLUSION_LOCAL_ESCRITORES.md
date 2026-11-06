# Exclusión local de escritores (Etapa 1, condición C1)

Referencia: `C:\Atlas\pruebas\diseno-publicacion-coherente-20261106\VALIDACION.md`, condición C1.

## Qué garantiza

En un mismo equipo Windows, para cada raíz operacional, **un solo proceso del Motor escribe a la vez**. La garantía cubre toda la sección crítica, no solo la adquisición del lease.

| Pieza | Dónde | Qué hace |
|---|---|---|
| Turno local | `atlas_core/exclusion_local.py` (`TurnoEscritura`) | Mutex con nombre de Windows `Global\AtlasEscritorTurno-<sha256(raíz)>`. Lo posee un hilo dedicado, así que el turno pertenece al **proceso**. Es reentrante dentro del proceso y `soltar()` es idempotente |
| Integración | `LeaseEscritorOperativo.adquirir/cerrar` y `EscritorEquipoUnico.adquirir/cerrar` | El turno se toma **antes** de consultar Cloud y se suelta **después** de confirmar la custodia y liberar el lease. PULL, sesión Desktop, B1, mantenimiento (`--tarea-programada`), migración y `estado_confirmado --sembrar` lo heredan sin cambios propios |
| Guardia | Audit hook que se instala al importar `atlas_core` (`atlas_core/__init__.py`) | En una raíz protegida, rechaza (`EscrituraSinTurno`) cualquier escritura de un proceso que no tenga el turno: `open` en escritura, `rename`/`replace`, `remove`, `mkdir`, `rmdir`, `rmtree`, `truncate`, `chmod`, `utime`, `link` |

Orden de bloqueo en todos los escritores: primero el turno local, después Cloud o el mutex del equipo único. No hay inversión de orden y, por lo tanto, no hay interbloqueo entre procesos.

Si el turno está ocupado, `adquirir()` devuelve `False` con `ocupado=True` y `motivo="ESCRITOR_LOCAL_OCUPADO"`, **sin llamar a Cloud**.
- Desktop reintenta con su espera acotada actual (150 s).
- PULL omite el ciclo (`NO_ADQUIRIDO`), igual que cuando recibe `ESCRITOR_OCUPADO`.
- Mantenimiento omite la pasada.

## Raíces protegidas

`exclusion_local.raices_protegidas()` considera tres fuentes:
- `ATLAS_EXCLUSION_RAICES`: rutas explícitas separadas por `;`.
- `ATLAS_DATA_DIR`, si es compartida.
- La `raiz` de la política de operación (`ATLAS_OPERACION_CONFIG` o `%LOCALAPPDATA%\Atlas\desktop_operacion.json`), si es compartida.

"Compartida" sigue el mismo criterio que `desktop_operacion.compartida`: UNC, una unidad distinta de C:, OneDrive o Google Drive. Las raíces locales de desarrollo y de pruebas **no** se protegen.

## Modos (`ATLAS_EXCLUSION_LOCAL`)

- `exigir` (por defecto): rechaza la escritura.
- `observar`: permite la escritura y la anota una vez por ruta en `%LOCALAPPDATA%\Atlas\cache\exclusion_local\observaciones.jsonl`. Es la palanca de reversión sin cambiar código.
- `desactivada`: sin guardia. El turno sigue excluyendo a los escritores entre sí.

## Interrupción y abandono

- Si el proceso termina por cualquier motivo (`TerminateProcess`, `os._exit`, caída), el kernel libera el mutex. **Nunca queda bloqueado por una interrupción.**
- Una excepción, incluida `KeyboardInterrupt`, dentro de `with TurnoEscritura` libera el turno.
- **Señal de abandono.** Windows solo informa `WAIT_ABANDONED` si otro proceso mantenía el mutex abierto. Si no era así, el objeto se destruye y el siguiente proceso crea uno nuevo. Por eso el abandono se detecta con un **marcador local** (`cache\exclusion_local\turno_<sha>.json`):
  - Lo escribe y lo borra solo quien posee el mutex.
  - Si existe al adquirir, el dueño anterior terminó sin soltar.
  - Cualquiera de las dos señales deja `abandonado=True` (`turno_abandonado` en los escritores) y se anota en `abandonos.jsonl` con el PID anterior.
  - La **recuperación** de operaciones interrumpidas no forma parte de esta etapa.

## Límites (no se asumen, y varios están demostrados en pruebas)

- **Es cooperativo.** Solo excluye procesos Python que importan `atlas_core`. Un proceso ajeno (Google Drive, el Explorador, Excel, otro programa, un script que no importa `atlas_core`, un subproceso lanzado con `-I`) escribe igual. Prueba: `test_limite_un_proceso_ajeno_al_motor_escribe_aunque_otro_tenga_el_turno`.
- **Es local.** No protege contra escritores de otro computador. Eso sigue a cargo del lease Cloud y de la custodia.
- **Un proceso vivo pero colgado retiene el turno.** Los demás fallan cerrado (no escriben) hasta que ese proceso termina. Prueba: `test_limite_un_proceso_colgado_retiene_el_turno_hasta_que_termina`.
- **La guardia ve solo eventos de auditoría de Python.** Las llamadas directas a Win32 (ctypes `CreateFileW`) y las escrituras de procesos hijos no pasan por ella. Los workers OCR del Motor no escriben en disco.
- **CLIs manuales fuera de Desktop sobre G:** por ejemplo `publicacion_reportes.py`, `crear_usuario_mobile.py`, `reproceso_cuarentena.py` o `servidor_mobile.py`. Con `exigir`, ahora fallan cerrados en lugar de escribir sin exclusión. Deben ejecutarse desde la sesión Desktop o con un turno (`with TurnoEscritura(raiz): ...`).

## Pruebas

- `tests/test_exclusion_local.py`, con procesos Windows reales:
  - Concurrencia, espera bloqueante y terminación por `taskkill /F` y por `os._exit`.
  - Excepción dentro del turno.
  - Lease vencido en el mismo equipo y equipo único frente a lease.
  - 3 procesos × 25 ciclos tipo PULL/Desktop/mantenimiento: sin interbloqueos ni solapamiento.
  - Guardia y modos, reentrancia y liberación tras fallos de Cloud o de custodia.
  - Los límites descritos arriba.
- `tests/test_exclusion_local_flujos.py`, con la guardia en `exigir`:
  - Los lectores que Desktop lanza directamente (`b1_consulta_cli`, `consultar_atlas`, `consultar_incidencias_operacionales`, `construir_fichas_catalogos`, `retomar_entradas_desktop --listar`) funcionan y no escriben.
  - La sesión Desktop y una pasada PULL completa escriben bajo turno y lo sueltan.
  - Con el turno ajeno, ninguna de las dos escribe.
