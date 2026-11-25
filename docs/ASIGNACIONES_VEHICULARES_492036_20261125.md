# Asignaciones vehiculares: revisión de la guía 492036

Diagnóstico de lectura sobre Motor `a1c7a8d`, sin OCR nuevo ni escritura
operacional. La copia local de trabajo está en
`C:/Atlas/pruebas/asignaciones-vehiculares-20261125/foto`.

## Resultado

La guía del 24/11/2026 identifica a Luis Reyes. El catálogo confirma desde
antes de esa fecha el tracto `KN5439` y la rampla `JF6468`. El original y su
traza OCR muestran `KN5439` y `JF6768`, respectivamente. La fila documental
vigente y el reporte vigente muestran `KN5439` y `JF6468`; la bandeja copiada
no contiene tarjetas, incluida ninguna tarjeta de patente de esta guía.
El original copiado coincide con el original operativo por SHA-256
`1897d2690a73a1bb9662fa700f9d3b7db7de77145110cbe9fdeee4928afe9fc0`.

No se observó un incumplimiento de la regla solicitada para esta guía, por
lo que no se modificó código ni se revalidaron o alteraron datos reales. La
métrica histórica de asignación registra la lectura `JF6768` con resultado
`ABSTENCION`, mientras la fila ya contiene `JF6468`; no demuestra por qué ni
cuándo se produjo la corrección posterior. La lectura está conservada en la
traza OCR; no atribuir esa corrección a la regla de asignación sin evidencia.

## Alcance de la comprobación

En una copia de 861 filas, el resolutor identificó 62 discrepancias aplicables
de patente por asignación (10 ramplas y 4 tractos ausentes, 44 ramplas y 3
tractos desconocidos, y 1 tracto conocido), y proyectó la asignación. Dos
discrepancias adicionales con asignación aplicable no se proyectan por existir
decisiones humanas sobre esos campos; la precedencia humana es intencional.
La función de incidencias devuelve 73 sustituciones en total, incluidas las
registradas durante el procesamiento, por lo que ese número no equivale a 73
filas distintas. Las asignaciones posteriores a la fecha de la guía y los
casos sin identidad o asignación unívoca no se infieren hacia atrás.

La copia no es una instantánea transaccional: después de copiar se compararon
las huellas del dataset, bandeja, ledger y catálogos de choferes y vehículos
con las fuentes y eran iguales. El reporte se consultó por separado. Esta
medición no prueba que todas las guías históricas tengan evidencia suficiente
ni que la atribución de cada corrección histórica sea completa.

Las suites sintéticas `test_patentes_asignacion_vigente_p0.py` y
`test_patentes_asignacion_chofer.py` aprobaron: 37 pruebas. No se intervino
extracción de direcciones, comunas o rutas. Esta entrega es documental y no
requiere instalación de Motor.
