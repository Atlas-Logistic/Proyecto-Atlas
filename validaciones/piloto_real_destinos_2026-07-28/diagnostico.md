# Diagnóstico del piloto

## Resultado

- 12 consultas reales únicas.
- 10 abstenciones correctas y 1 contradicción correctamente detectada.
- 1 confirmación correcta: `REAL-011`, LA UNION 3070.
- 0 falsos negativos.
- 0 falsos positivos.
- 1 conjunto de coordenadas aceptado con evidencia completa.
- 3 conjuntos de coordenadas rechazados.
- 12/12 originales conservados.
- 12/12 resultados trazables.
- Repetición: 12/12 desde caché y 0 consultas nuevas.

## Hallazgo sistemático

El proveedor devolvió `Metropolitana` mientras el Ground Truth usa `REGIÓN
METROPOLITANA`. La nueva capa canónica reconoce ambas expresiones como la misma
región y registra la transformación.

En `REAL-011`, ORS devolvió `3070 La Union, Renca, RM, Chile`: contiene calle,
número, comuna y región equivalentes, un único candidato y coordenadas válidas.
Ahora se clasifica `COINCIDENCIA_NORMALIZADA`, se confirma y corrige el falso
negativo anterior.

## Torres Ocaranza

Para `REAL-004`, ORS devolvió `Vista Clara, Santiago, RM, Chile`, sin número 2351
y con comuna distinta de Cerrillos. Se clasifica `CONTRADICCION_COMUNA`; Atlas
conserva `VISTA CLARA 2351`, exige revisión y rechaza las coordenadas. Nunca se
propuso 2401.

## Recomendación

`APTO PARA INTEGRACIÓN OPCIONAL EN MODO REVISIÓN`.

La cobertura aumenta de 0/12 a 1/12 sin falsos positivos. El piloto no autoriza
escritura automática.
