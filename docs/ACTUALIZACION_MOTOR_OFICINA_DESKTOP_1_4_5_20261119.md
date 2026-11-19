# Actualización preparada: Motor OFICINA para Desktop 1.4.5

## Estado y alcance

Esta es una preparación; no autoriza ni ejecuta instalación, reinicio, cambio
de datos ni activación de tareas. El candidato es `b09bd28` (y su SHA completo
`b09bd28c8af3f64732ec27879db5cc572f4a97ff`). La base instalada declarada de
OFICINA es `918d629808d31c7de0b0c99cf574d87662dc5448`.

`918d629` es ancestro de `b09bd28`, por lo que la promoción propuesta es
lineal y la reversión vuelve exactamente al binario/código anterior. No hay
migración de esquema ni script de datos en este procedimiento.

El candidato habilita para Desktop 1.4.5:

- lectura automática de licencia;
- licencias con múltiples clases;
- corrección humana y auditable de fechas documentales;
- revisión documental simple con confirmación explícita del original.

Mantiene el sobre de ingreso MBT heredado (sin empresa/perfil, normalizado a
`mbt`/`aza`), OCR, viajes y B1. Las validaciones se hicieron únicamente en
`tmp_path` sintético: 95 pruebas de fichas/ingreso y 136 regresiones de OCR,
viajes y B1 aprobadas el 2026-11-19.

## Condiciones antes de ejecutar en OFICINA

1. Autorizar expresamente la ventana y la promoción. No reutilizar esta guía
   para CASA, Desktop, Mobile, Cloud ni PULL.
2. Desde un clon de mantenimiento, comprobar identidad y respaldo remoto:

   ```powershell
   git fetch origin
   git rev-parse b09bd28^{commit}
   git branch -r --contains b09bd28
   git show --no-patch --format=fuller b09bd28
   ```

   Debe resolverse al SHA indicado y existir una rama remota que lo contenga.
   Si no, detenerse: no promover un commit no respaldado.
3. Identificar el worktree real de OFICINA y confirmar que está exactamente en
   `918d629`, sin cambios rastreados. Registrar en la bitácora su ruta, SHA y
   estado; no inferirlos desde este repositorio de preparación.
4. Suspender sólo los escritores que usen ese mismo worktree y esperar que
   terminen. No copiar, reprocesar ni editar datos operacionales. Respaldar la
   referencia actual (`918d629`) y verificar que el respaldo sea recuperable.

## Actualización controlada

1. Con los escritores detenidos, cambiar **solamente el worktree del Motor de
   OFICINA** a un checkout detached del SHA completo de `b09bd28`.
2. Verificar de inmediato:

   ```powershell
   git rev-parse HEAD
   git status --porcelain
   ```

   El primer comando debe coincidir con el SHA del candidato y el segundo no
   debe mostrar cambios rastreados.
3. Reactivar únicamente los escritores que se suspendieron y observar un ciclo
   normal, sin enviar entradas nuevas de prueba ni forzar OCR/PULL/B1.
4. En Desktop 1.4.5, realizar una comprobación de lectura sin guardar sobre una
   ficha no operacional o una copia aprobada: abrir licencia, mostrar clases,
   abrir vista previa de fecha y revisión documental. Sólo una persona
   autorizada puede confirmar/escribir datos reales, bajo su procedimiento
   operativo independiente.

## Reversión

Revertir si falla el arranque, el ingreso MBT, una lectura de ficha, OCR,
viajes o B1; también ante cualquier cambio inesperado de archivos.

1. Detener los mismos escritores y esperar su fin.
2. Confirmar que no hubo una escritura operacional desde la promoción. Si la
   hubo, no hacer rollback de código a ciegas: preservar evidencia y seguir el
   procedimiento de recuperación de datos correspondiente.
3. Restaurar el worktree del Motor de OFICINA a un checkout detached de
   `918d629808d31c7de0b0c99cf574d87662dc5448`.
4. Comprobar `git rev-parse HEAD`, que el árbol esté limpio y que el respaldo
   previo continúa disponible. Reactivar los escritores sólo después de esas
   comprobaciones.
5. Registrar causa, hora, SHA antes/después y evidencia; no eliminar el
   respaldo ni intentar una segunda promoción hasta investigar la causa.

## Riesgos que permanecen

- La evidencia es sintética; no sustituye la comprobación controlada contra la
  instalación de OFICINA en una ventana autorizada.
- La revisión de documentos y corrección de fechas escriben únicamente cuando
  una persona confirma el original. La actualización no debe usarse para
  automatizar confirmaciones.
- La coordinación mantiene advertencias previas sobre publicación/recuperación
  general de B1 y lectores directos. Esta promoción no las resuelve ni amplía
  escrituras de B1.
