# Aislamiento de la configuracion operativa durante pytest

Cambio exclusivamente en infraestructura de pruebas. Ningun archivo de
atlas_core, CLI productivo, Desktop, autorizacion ni controles de exclusividad
se modifico. No se procesaron guias ni se ejecuto PULL productivo.

## Rutas identificadas

El fixture previo solo eliminaba ATLAS_DATA_DIR/token Cloud y desactivaba
la autodeteccion de Drive; no aislaba el perfil local del usuario.

| Consumidor productivo llamado por tests | Ruta local por defecto | Cobertura focal |
|---|---|---|
| desktop_operacion.sesion | LOCALAPPDATA/Atlas/cache (ignora ATLAS_CACHE_DIR) | test_desktop_operacion |
| exclusividad_equipo.ruta_politica | LOCALAPPDATA/Atlas/desktop_operacion.json (fallback sin ATLAS_OPERACION_CONFIG) | test_exclusividad_equipo |
| revalidacion_documental._ruta_cache_relaciones_historicas | LOCALAPPDATA/Atlas/cache; fallback Path.home | test_cache_relaciones_historicas_p0 y lectura_robusta |
| reconciliacion_estado_derivado._ruta_log_diagnostico_reconciliacion | LOCALAPPDATA/Atlas/diagnostico; fallback Path.home | test_diagnostico_reconciliacion_p0, test_ingesta_focal_p0 |
| escritor_operativo.ruta_identidad_escritor | LOCALAPPDATA/Atlas/escritor_operativo_id.txt; fallback ~/.local | test_escritor_operativo |
| registro_ciclo_pull.directorio_ciclos | LOCALAPPDATA/Atlas/logs/pull_ciclos; fallback ~/.local | test_registro_ciclo_pull |
| paddle_runtime.ruta_runtime_paddle | LOCALAPPDATA/Atlas/runtime/paddleocr; fallback Path.home | test_paddle_runtime |

Los tests de cache y diagnostico solo configuraban overrides en algunos
casos; otros tests alcanzaban estos consumidores indirectamente. Se confirmo
la falta de aislamiento, pero no hay evidencia suficiente para atribuir a una
prueba concreta el borrado de la autorizacion del 21/10.

## Cambio

- pytest_configure crea un perfil temporal ANTES de coleccionar/importar
  los modulos de tests. Sustituye LOCALAPPDATA, APPDATA, USERPROFILE, HOME,
  HOMEDRIVE y HOMEPATH, ademas de los overrides cache/diagnostico/politica/
  runtime/logs. Reemplaza overrides heredados; nunca copia la autorizacion real.
- Una fixture autouse crea otro perfil temporal por test, separado del
  tmp_path que usa cada caso. De este modo no contamina assertions que esperan
  un tmp_path vacio, ni comparte archivos entre tests.
- Los hijos Python heredan ese entorno, incluso cuando no cargan pytest.
  Si el test elimina los overrides Atlas, LOCALAPPDATA sigue siendo temporal;
  si elimina LOCALAPPDATA, Path.home tambien sigue apuntando al perfil temporal.
- Un audit hook SOLO instalado por conftest protege el directorio Atlas real
  capturado antes de cambiar el entorno, incluidos sus fallbacks de home.
  Rechaza escrituras, borrados, reemplazos, renombrados, chmod/utime y rmtree,
  tambien sobre sus directorios padres. Permite leer. Sigue activo hasta salir
  del proceso, incluidos callbacks atexit. No cambia permisos del operador.
- Al cerrar pytest se elimina el perfil de sesion y se restaura el entorno
  heredado. Los perfiles por test quedan en la gestion temporal de pytest.
- El test de resolucion de runtime que usaba C:/Users/cualquiera ahora usa
  tmp_path; mantiene la comprobacion del contrato de rutas.

## Regresion y evidencia

Nueva prueba inicia otro pytest con un perfil real SIMULADO y escribible,
una autorizacion sentinela y overrides heredados apuntando incorrectamente a
esa carpeta. Verifica aislamiento durante coleccion, por test y en Python -I;
ejercita fallbacks sin overrides y sin LOCALAPPDATA, cache de sesion Desktop
e identidad de escritor. Intenta ocho mutaciones sobre la sentinela, todas
rechazadas por la proteccion (sin depender de un atributo de solo lectura).
Confirma que solo queda la autorizacion original, con igual SHA-256 y mtime.
Todo ocurre bajo temporales; no intenta esas mutaciones sobre datos reales.

Validacion final: 86 tests focales aprobados en 14.98 s, incluyendo nueva
regresion, Desktop CLI/progreso, exclusividad Windows entre procesos,
cache/diagnostico, runtime, identidad del escritor, logs y alcance focal.

La autorizacion REAL se leyo antes/despues desde un proceso externo a pytest,
con la ruta original guardada previamente. Resultado identico:

- desktop_operacion.json existe, 321 bytes.
- SHA-256: 8bf4232b93d7c77d4c302fadf50f9c5abdda89972aa5029640e95f0819a21cf1.
- st_mtime_ns = st_ctime_ns = 1792591968141917700.
- Atributos Windows: 33, sin cambios. No se quito el atributo de solo lectura.

Evidencia local: .pytest_temp_config_integridad/antes.json y despues.json
(ignorados por Git, sin contenido de la autorizacion). No se versiona ningun
archivo operativo. El diff productivo es vacio; los tests de exclusividad
siguen ejerciendo los mismos controles reales con datos sinteticos.
