# OFICINA: migración P0 + ficha B1 (P1.1 y P1.2) pendiente

CASA quedó así el 27/11/2026:

- **Motor `9d317407a446cad13b3815d2fd9f624382d0c9b0`**, rama `feat/edicion-ficha-b1-20261127`. Incluye el P0 estructural de `d8059905` sin cambios más la ficha integral B1 (P1.1) y su edición (P1.2).
- **Desktop `app.asar` 38DBCEDE…** (Desktop `3f23a1a`), armado desde el `app.asar` E2C7E61B (Desktop `2914483`) con el parche determinista de `scripts/migracion_p0/desktop_p1`.

OFICINA debe instalar **exactamente ese Motor**, no la punta de la rama, que además tiene este documento y el kit de Desktop. Después instala el mismo `app.asar`.

## Hasta migrar: OFICINA no escribe

- **Al encender OFICINA**, antes de abrir Atlas, deshabilitar su tarea PULL. El Motor anterior escribiría directo en G:.
- **No abrir Atlas en OFICINA.** El acceso directo del escritorio puede venir de CASA por OneDrive: en un equipo sin migrar abre Atlas como antes, y eso permitiría escribir.
- **El protocolo 3 sigue sin activar** (decisión de Javier). Es la única barrera técnica que impediría escribir a un Motor anterior.

## Instalación (en OFICINA)

```powershell
git -C C:\Atlas\Proyecto-Atlas fetch origin feat/edicion-ficha-b1-20261127
git -C C:\Atlas\Proyecto-Atlas worktree add C:\Atlas\migracion-p0 origin/feat/edicion-ficha-b1-20261127
$i = 'C:\Atlas\migracion-p0\scripts\migracion_p0\instalar_equipo.ps1'
$motor = '9d317407a446cad13b3815d2fd9f624382d0c9b0'
# 1) Simulación: identifica el equipo (escritor pc-13570755-...) y muestra todo lo que haría.
powershell -NoProfile -ExecutionPolicy Bypass -File $i -Equipo OFICINA -Commit $motor -Rama feat/edicion-ficha-b1-20261127
# 2) Si el escritor y los accesos directos son los esperados: aplicar exigiendo el escritor completo.
powershell -NoProfile -ExecutionPolicy Bypass -File $i -Equipo OFICINA -Commit $motor -Rama feat/edicion-ficha-b1-20261127 -EscritorEsperado <escritor de la simulación> -Aplicar
# 3) Desktop: simulación y luego aplicar. Exige que el app.asar instalado sea E2C7E61B; si no lo es, se detiene.
$d = 'C:\Atlas\migracion-p0\scripts\migracion_p0\desktop_p1\instalar_desktop.ps1'
powershell -NoProfile -ExecutionPolicy Bypass -File $d
powershell -NoProfile -ExecutionPolicy Bypass -File $d -Aplicar
git -C C:\Atlas\Proyecto-Atlas worktree remove C:\Atlas\migracion-p0
```

El instalador del Motor hace lo mismo que en CASA:

- respalda el Motor (rama remota), la configuración local, `app.asar` y los accesos directos;
- guarda en stash los cambios locales sin commit;
- cierra Atlas, espera el preflight (0 distintos, sin diarios) y pausa el PULL;
- actualiza el Motor (avance rápido) y crea la raíz de trabajo `C:\AtlasTrabajo\Atlas` (copia de G:, unos 5 GB);
- reactiva el PULL, redirige los accesos directos y verifica el primer ciclo y la custodia.

El de Desktop arma el candidato desde el `app.asar` instalado y exige el SHA-256 de CASA (38DBCEDE…). Respalda el anterior en `resources\app.asar.antes-p1-ficha-<fecha>` y lo restaura ante cualquier falla. No toca datos ni el Motor.

**Si el Desktop de OFICINA no es E2C7E61B**, el script se detiene sin cambiar nada. En ese caso hay que pedir revisión: el Motor nuevo funciona con el Desktop anterior, solo que sin la ficha integral.

Si falla el Motor: `revertir_equipo.ps1 -Aplicar` desde el mismo worktree (ver PLAN_MIGRACION_P0.md). Para volver atrás solo Desktop: copiar el respaldo `app.asar.antes-p1-ficha-<fecha>` sobre `app.asar` con Atlas cerrado.

## Después de OFICINA (con ambos equipos verificados)

1. `protocolo_d1.ps1 -Nivel 3` en simulación y luego con `-Aplicar`, desde el repositorio Cloud con wrangler.
2. Publicar la primera versión desde CASA (PLAN_MIGRACION_P0.md, paso 5).
3. Antes del paso 2: en CASA, `C:\Atlas\Proyecto-Atlas` no debe tener cambios sin commit en archivos versionados. La actualización automática y `revertir_equipo.ps1` se niegan a actuar si los hay.

## Verificación de referencia (CASA, 27/11)

- Ciclos PULL con código 0, con la raíz redirigida a `C:\AtlasTrabajo\Atlas`.
- Custodia: 0 distintos y sin diarios abiertos.
- Ingreso manual real de 2 guías desde Desktop por el camino P0, publicado en G: y confirmado.
- Consulta B1 de solo lectura sobre G:; ficha integral por guía y transporte con navegación, original y exportaciones (P1.1 y P1.2).
- El lanzador `iniciar_atlas.ps1` responde `SIN_VERSION_PUBLICADA`.
