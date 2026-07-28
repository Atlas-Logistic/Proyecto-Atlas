# Validación de integración en modo revisión

Esta carpeta contiene entradas controladas y, después de la demostración, el
resumen reproducible de la bandeja.

- `entrada_piloto_revision.json`: copia explícita de los 12 casos congelados.
- `lote_sintetico_revision.json`: 15 escenarios sin datos reales adicionales.

La demostración usa copias temporales bajo `output/`, respuestas ORS ya
congeladas y `--solo-cache`. No se realizan consultas externas.

## Resultado de la demostración controlada

- Entrada: 12 destinos.
- Evaluados: 12.
- Respuestas desde caché congelada: 12.
- Consultas externas consumidas: 0.
- Casos que requieren decisión humana: 12.
- Estados: 1 `CONFIRMACION_PROPUESTA`, 2 `COINCIDENCIA_PARCIAL`,
  1 `CONTRADICCION_COMUNA` y 8 `RESPUESTA_AMBIGUA`.
- Dos ejecuciones produjeron archivos idénticos byte a byte.
- LA UNION 3070 quedó como `CONFIRMACION_PROPUESTA`.
- VISTA CLARA 2351 se conservó y quedó como `CONTRADICCION_COMUNA`.

Hashes SHA-256:

- entrada: `acfbb...dd147`;
- respuestas ORS congeladas: `b6ce7...94e2e`;
- Ground Truth congelado: `78d92...15a5be`;
- CSV de revisiones: `66999...a693`;
- JSON de revisiones: `3f9a4...f1af`;
- resumen: `6bf10...d108`;
- manifiesto: `4a175...a6d9`.

Los cuatro artefactos finales se encuentran en `demostracion_controlada/`.
