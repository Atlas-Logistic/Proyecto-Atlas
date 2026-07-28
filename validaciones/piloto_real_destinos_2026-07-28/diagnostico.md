# Diagnóstico del piloto

## Resultado

- 12 consultas reales únicas.
- 11 abstenciones correctas.
- 1 falso negativo: `REAL-011`, LA UNION 3070.
- 0 falsos positivos.
- 0 coordenadas aceptadas automáticamente.
- 4 conjuntos de coordenadas propuestos y rechazados.
- 12/12 originales conservados.
- 12/12 resultados trazables.
- Repetición: 12/12 desde caché y 0 consultas nuevas.

## Hallazgo sistemático

El proveedor devolvió `Metropolitana` mientras el Ground Truth usa `REGIÓN
METROPOLITANA`. El adaptador productivo exige igualdad normalizada exacta y
clasificó cuatro respuestas como `CONTRADICCION_REGION`. La evaluación humana
controlada considera ambas expresiones equivalentes.

En `REAL-011`, ORS devolvió `3070 La Union, Renca, RM, Chile`: contiene todos los
componentes de la dirección y la comuna correcta, pero el alias regional provocó
abstención. Se clasifica como falso negativo. No produjo escritura ni aceptación
de coordenadas.

## Torres Ocaranza

Para `REAL-004`, ORS devolvió `Vista Clara, Santiago, RM, Chile`, sin número 2351
y con comuna distinta de Cerrillos. Atlas conservó `VISTA CLARA 2351` y exigió
revisión. No se aceptaron coordenadas y nunca se propuso 2401.

## Recomendación

`APTO PARA INTEGRACIÓN OPCIONAL EN MODO REVISIÓN`.

Antes de aumentar cobertura conviene normalizar alias humanos de región mediante
una mejora separada y probada. El piloto no autoriza escritura automática.
