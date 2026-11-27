# Migración coordinada CASA + OFICINA al P0 estructural

Rama `fix/p0-integral-20261127`. Incluye P0.1 a P0.6: diario remoto, recuperación de turnos, escritor sustituido, raíz de trabajo aislada, recuperación automática en el PULL, actualización automática y las correcciones de la validación integral.

**Estado: preparado y ensayado en aislamiento. No activado.** Cada paso con efecto exige `-Aplicar`. Sin ese parámetro, los scripts solo muestran lo que harían.

## Qué cambia en cada equipo

| Antes | Después |
|---|---|
| El Motor escribe directamente en `G:\Mi unidad\Atlas` | El Motor escribe en una raíz de trabajo local, por ejemplo `C:\AtlasTrabajo\Atlas`. G: recibe solo lo que Cloud confirmó |
| Desktop lee G: | Desktop sigue leyendo G:, que ahora solo tiene datos confirmados. Sus acciones (B1, ingreso) se redirigen solas a la raíz de trabajo |
| Atlas se abre con el ejecutable | Atlas se abre con `scripts\iniciar_atlas.ps1`: actualiza Motor y Desktop a la versión publicada, con vuelta atrás si falla, y luego abre Desktop |
| Worker: `protocolo_minimo = 2` | `protocolo_minimo = 3`: ningún Motor anterior obtiene lease |

La tarea programada del PULL no cambia: sigue recibiendo G:, y el Motor la redirige a la raíz de trabajo.

## Instalador por equipo (recomendado)

`instalar_equipo.ps1 -Equipo CASA|OFICINA -Commit <P0> -Rama fix/p0-integral-20261127 [-EscritorEsperado <id>] [-Aplicar]` ejecuta los pasos 1 y 2 de la secuencia en un solo comando. En orden:

1. Identifica el equipo (host, MachineGuid, `escritor_id`). Con `-EscritorEsperado` exige la coincidencia.
2. Respalda y guarda en stash los cambios locales sin commit del Motor, por ejemplo notas, con una copia en `LOCALAPPDATA\Atlas\respaldo-p0-cambios-locales-<fecha>`.
3. Cierra solo el Atlas Viajes instalado.
4. Repite el preflight hasta que no haya un ciclo en curso.
5. Migra con `migrar_equipo.ps1`.
6. Verifica el siguiente ciclo PULL y la custodia.

Los accesos directos productivos ("Atlas Viajes.lnk" del escritorio y del menú Inicio) pasan a ejecutar `iniciar_atlas.ps1` si existe. Si no existe, abren el exe como antes, porque el del escritorio puede sincronizarse por OneDrive a un equipo aún no migrado.

### OFICINA (pendiente)

Mismo commit que CASA, en OFICINA y con el PULL de OFICINA sin correr:

```
git -C C:\Atlas\Proyecto-Atlas fetch origin fix/p0-integral-20261127
git -C C:\Atlas\Proyecto-Atlas worktree add C:\Atlas\migracion-p0 <commit P0>
powershell -NoProfile -ExecutionPolicy Bypass -File C:\Atlas\migracion-p0\scripts\migracion_p0\instalar_equipo.ps1 -Equipo OFICINA -Commit <commit P0> -Rama fix/p0-integral-20261127 -EscritorEsperado pc-13570755-<resto>
(revisar la simulación) ... mismo comando con -Aplicar
git -C C:\Atlas\Proyecto-Atlas worktree remove C:\Atlas\migracion-p0
```

## Secuencia

Ambos equipos se tratan igual. El orden importa solo para el protocolo 3.

1. **Comprobación previa** en cada equipo (solo lectura): `preflight.ps1 -Motor C:\Atlas\Proyecto-Atlas -Raiz "G:\Mi unidad\Atlas" -RaizTrabajo C:\AtlasTrabajo\Atlas -CommitEsperado <instalado>`.
   - Debe decir `LISTO`: Motor limpio, sin procesos del Motor en curso, custodia con 0 distintos, sin diarios abiertos, Desktop presente y 5 GB libres.
2. **Migrar CASA**: `migrar_equipo.ps1` con los mismos parámetros más `-Commit <P0> -Rama fix/p0-integral-20261127 -Equipo CASA -AccesoDirecto "<ruta del .lnk de Atlas>"`.
   - Correrlo primero sin `-Aplicar`, revisar la salida y luego con `-Aplicar`. Hace:
     - **Respaldos:** rama `origin/respaldo/antes-p0-casa-<fecha>`, copia de la configuración local, `app.asar.antes-p0-<fecha>` y copia del acceso directo.
     - **PULL pausado** durante el cambio.
     - **Motor** actualizado por fast-forward.
     - **Raíz de trabajo** creada como copia de G:, más `raiz_publicada.json`.
     - **Acceso directo** apuntado a `iniciar_atlas.ps1`.
     - **PULL reactivado** y verificación de la custodia.
   - Comprobar dos ciclos PULL con código 0 y abrir Atlas.
3. **Migrar OFICINA** al encenderla, igual que CASA con `-Equipo OFICINA`. Mientras OFICINA siga en el Motor anterior, puede trabajar, porque el protocolo mínimo sigue en 2. Pero ese Motor no aplica las protecciones del P0 y su escritura va directa a G:.
4. **Activar el protocolo 3**, solo con ambos equipos migrados: `protocolo_d1.ps1 -Nivel 3` (simulación) y luego `-Aplicar`. Se ejecuta desde el repositorio Cloud con wrangler y la D1 `atlas-mobile-recepcion-prueba`. Es el mismo mecanismo con que se activó el protocolo 2 el 29/10.
5. **Publicar la primera versión** desde CASA, para que la actualización automática tenga referencia: `python actualizar_atlas.py --publicar --version <fecha> --rama fix/p0-integral-20261127 --commit <P0> --desktop-recursos "%LOCALAPPDATA%\Programs\Atlas Viajes\resources" --nivel-minimo 1 --raiz-atlas "G:\Mi unidad\Atlas"`.

## Reversión segura

El orden es obligatorio:

1. `protocolo_d1.ps1 -Nivel 2 -Aplicar`. Sin esto, un Motor anterior no obtiene lease.
2. En cada equipo, `revertir_equipo.ps1` (simulación y luego `-Aplicar`). Hace:
   - Pausa el PULL.
   - `git reset --keep` al Motor anterior.
   - Archiva `raiz_publicada.json`, así que el Motor vuelve a escribir en G:.
   - Restaura el acceso directo y el `app.asar` si había cambiado.
   - Reactiva el PULL.
   - Si hay una publicación pendiente, se niega: G: estaría atrasado y hay que correr un PULL antes (o usar `-Forzar`).
3. G: ya tiene el último estado confirmado, así que el Motor anterior parte de ahí: en el ensayo dio 0 diferencias. La raíz de trabajo queda en disco para inspección.

## Ensayos en aislamiento (27/11/2026)

- `scripts/validacion_diario_remoto/validar_migracion.py`, 20/20, sobre un equipo sintético con el Motor 48d6096 y el Worker b28d594 real:
  - comprobación previa;
  - simulación sin cambios;
  - migración aplicada, con respaldos verificados;
  - PULL con OCR real publicando en la "Drive";
  - protocolo 3 dejando fuera al Motor anterior;
  - reversión con el Motor anterior trabajando otra vez.
- `scripts/validacion_diario_remoto/validar_integral.py`, 36/36. Ver COORDINACION.md, sección P0.6.

## Costos medidos (`medir_costo_cloud.py`) y proyección MBT

La proyección usa 12 guías al día, dataset de 5,7 MB, foto de 2,6 MB y 43 % Mobile:

| | por guía | por día | por año |
|---|---|---|---|
| Solicitudes Worker | ~157 (ingesta + revalidación) | ~6.100 (un ciclo ocioso: 6) | — |
| Filas D1 de custodia | ~44 | ~530 | ~193.000 |
| R2 de custodia (y subida desde el equipo) | ~41 MB (7 contenidos del dataset + foto) | ~490 MB | ~175 GB |

Sin compactación ni recolección de basura, las filas D1 y R2 crecen sin límite. El manifiesto recorre todas las filas de la empresa. Recomendación antes de un año de operación: compactar en el Worker (historial y objetos sin referencia).

## Riesgos y puntos abiertos

- **Primera instalación:** el actualizador no existe en los Motores actuales, así que esta migración es manual.
- **Verificación de Desktop:** la salud de una versión nueva abre Electron unos segundos en un entorno aislado (sin datos ni credenciales) con depuración local.
- **Equipo detenido:** si en un equipo queda un dataset con documentos que Cloud no tiene y no es de un turno propio, ese equipo se detiene hasta una revisión humana (protección del 26/11).
