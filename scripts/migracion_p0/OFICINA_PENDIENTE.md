# OFICINA: migración P0 pendiente

CASA quedó migrada el 27/11/2026 con el Motor 8d699c1 y luego pasó a **d8059905db728e69e138663ff01ce82d3470d48e**, que es el mismo código más las notas de Codex reconciliadas en COORDINACION.md. OFICINA debe instalar **exactamente ese commit**, no la punta de la rama, que además tiene este documento.

## Hasta migrar: OFICINA no escribe

- **Al encender OFICINA**, antes de abrir Atlas, deshabilitar su tarea PULL. El Motor anterior escribiría directo en G:.
- **No abrir Atlas en OFICINA.** El acceso directo del escritorio puede venir de CASA por OneDrive: en un equipo sin migrar abre Atlas como antes, y eso permitiría escribir.
- **El protocolo 3 sigue sin activar** (decisión de Javier). Es la única barrera técnica que impediría escribir a un Motor anterior.

## Instalación (en OFICINA)

```powershell
git -C C:\Atlas\Proyecto-Atlas fetch origin fix/p0-integral-20261127
git -C C:\Atlas\Proyecto-Atlas worktree add C:\Atlas\migracion-p0 d8059905db728e69e138663ff01ce82d3470d48e
$i = 'C:\Atlas\migracion-p0\scripts\migracion_p0\instalar_equipo.ps1'
# 1) Simulación: identifica el equipo (escritor pc-13570755-...) y muestra todo lo que haría.
powershell -NoProfile -ExecutionPolicy Bypass -File $i -Equipo OFICINA -Commit d8059905db728e69e138663ff01ce82d3470d48e -Rama fix/p0-integral-20261127
# 2) Si el escritor y los accesos directos son los esperados: aplicar exigiendo el escritor completo.
powershell -NoProfile -ExecutionPolicy Bypass -File $i -Equipo OFICINA -Commit d8059905db728e69e138663ff01ce82d3470d48e -Rama fix/p0-integral-20261127 -EscritorEsperado <escritor de la simulación> -Aplicar
git -C C:\Atlas\Proyecto-Atlas worktree remove C:\Atlas\migracion-p0
```

El instalador hace lo mismo que en CASA:

- respalda el Motor (rama remota), la configuración local, `app.asar` y los accesos directos;
- guarda en stash los cambios locales sin commit;
- cierra Atlas, espera el preflight (0 distintos, sin diarios) y pausa el PULL;
- actualiza el Motor y crea la raíz de trabajo `C:\AtlasTrabajo\Atlas` (copia de G:, unos 5 GB);
- reactiva el PULL, redirige los accesos directos y verifica el primer ciclo y la custodia.

Si falla: `revertir_equipo.ps1 -Aplicar` desde el mismo worktree (ver PLAN_MIGRACION_P0.md).

## Después de OFICINA (con ambos equipos verificados)

1. `protocolo_d1.ps1 -Nivel 3` en simulación y luego con `-Aplicar`, desde el repositorio Cloud con wrangler.
2. Publicar la primera versión desde CASA (PLAN_MIGRACION_P0.md, paso 5).
3. Resuelto el 27/11: las notas de Codex ya están en el commit (COORDINACION.md de d805990) y su original exacto en origin/respaldo/notas-codex-coordinacion-20261127. CASA quedó sin cambios locales, así que la actualización automática y la reversión no se bloquean.

## Verificación de referencia (CASA, 27/11)

- Ciclos PULL con código 0, con la raíz redirigida a `C:\AtlasTrabajo\Atlas`.
- Custodia: 0 distintos y sin diarios abiertos.
- G: idéntico a Cloud: 1381 rutas.
- Ingreso manual real de 2 guías desde Desktop por el camino P0, publicado en G: y confirmado.
- Consulta B1 de solo lectura sobre G:.
- El lanzador `iniciar_atlas.ps1` responde `SIN_VERSION_PUBLICADA`.
