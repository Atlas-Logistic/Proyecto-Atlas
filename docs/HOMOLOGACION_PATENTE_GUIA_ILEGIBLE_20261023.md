# Homologación de patente con guía ilegible (caso real 482995, 23/10/2026)

## Regresión
Envío Mobile ae70a62b (Salomón Pizarro, RUT 18091588-5, tracto TG8925, rampla impresa "JF9557"; Javier
confirma JF9575). La guía se leyó "No encontrado". `enriquecer_decisiones_vehiculo` localizaba la fila del
documento por número de guía y tomaba la PRIMERA fila con esa guía: 473316, de José Lazcano. La patente se
evaluó con RUT e historial ajenos (candidatas JB6878/JK2501) y quedó una tarjeta VEHICULO_DESCONOCIDO en vez
de homologar al carro confirmado del propio chofer. Con la guía ya legible (482995) la misma regla resolvía
JF9575 (CONFIRMACION_HUMANA, distancia 2).

## Corrección
La fila se identifica por `archivo` (único; archivos repetidos no eligen fila). Sin archivo, la guía sólo se
usa si es legible y corresponde a una sola fila. Sin fila inequívoca no hay evaluación: la tarjeta queda para
revisión humana. Sin cambios en las tolerancias ni en los niveles de evidencia.

## Tolerancia vigente (sin cambios)
Sustitución de un carácter y transposición de dos adyacentes (2 posiciones) según nivel:
CONFIRMACION_HUMANA hasta 2, documental hasta 1; varios candidatos plausibles -> revisión humana.
Omisión/adición de un carácter (distinto largo) nunca se consideró cercana; no forma parte de esta regresión.

## Pendiente observado (fuera de alcance)
`regenerar_decisiones_persistidas` también busca filas por guía para destino/obra/origen/cliente; con guías
ilegibles o repetidas puede leer la fila de otro documento.

## Pruebas
`tests/test_homologacion_patente_guia_ilegible_482995.py`: base 5/6 fallan, corregido 6/6.
