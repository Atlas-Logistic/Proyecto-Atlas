# B1: expediente de investigación de revisiones

Ejecutar desde `Proyecto-Atlas`:

```powershell
python investigar_revision_b1.py NUMERO_GUIA --salida expediente.json
```

La entrada toma la fila vigente del dataset y resuelve el original con el
resolvedor documental de Atlas. Reutiliza trazas OCR existentes; si no hay
lectura geométrica útil, relee el original con el proveedor OCR configurado.
Reutiliza los recolectores por dominio, el orquestador B1, los catálogos y la
herramienta `VERIFICACION_EXTERNA` con su caché y URLs. Investiga obra,
destino y material cuando hay motivos elegibles.

El expediente separa hechos documentales, hechos de Atlas, historial,
historial observado, evidencia externa, contradicciones, inferencias, propuesta, nivel de
evidencia, acción, confirmación humana y motivo de abstención. Conserva la
ruta y SHA-256 del original y los identificadores de evidencia. Una propuesta
histórica que contradice `DESPACHAR A` del original queda bloqueada. Un valor
OCR marcado como contaminado no se considera resuelto sólo porque B1 lo
repita. Dos candidatos históricos sin original resolutivo causan abstención.

Esta ruta no invoca aplicadores ni actualiza dataset, catálogos, ledger,
bandeja o rutas. Puede actualizar la caché regenerable de búsqueda web.
Toda propuesta sigue requiriendo confirmación humana. La salida del CLI es
un artefacto local, elegido con `--salida`; no se publica automáticamente.

La investigación externa existente usa OpenRouter Sonar cuando hay
`OPENROUTER_API_KEY`. Si falta o falla, el expediente conserva el motivo de
abstención. Las respuestas de búsqueda son evidencia de exploración con
URLs; una respuesta resumida del proveedor no confirma por sí sola la
identidad de una obra ni el número exacto de una dirección.

## Investigación adaptativa

`atlas_core.atlas_ia.candidatos_externos` usa el buscador y la caché web
existentes. La primera consulta pide candidatos estructurados a partir de
obra, dirección OCR y comuna documental. Las siguientes consultas se forman
con los candidatos encontrados para corroborar cada dirección, hasta tres
consultas por expediente. Cada consulta conserva la incertidumbre que buscó
resolver, el resultado y el error si lo hubo.

Un candidato contiene los campos originales devueltos por la búsqueda y se
vincula sólo a URLs citadas. Atlas abre la página pública y exige que calle,
número y comuna aparezcan juntos en el texto fuente. Conserva el fragmento
original del buscador y el fragmento verificado de la página. Si la página
no puede leerse o no contiene los anclajes, queda `NO_VERIFICABLE`.

La comparación usa los estados `COINCIDE`, `COMPATIBLE`, `CONTRADICE`,
`NO_APORTA` y `NO_VERIFICABLE`. Para `PROPUESTA_RESOLUBLE` exige dos dominios
independientes verificados que relacionen la misma entidad con la dirección;
calle, número OCR y comuna deben ser compatibles con el original. Un RUT
verificado contradictorio, número limpio contradictorio o comuna distinta
bloquean. La tolerancia OCR de un número alfanumérico sólo produce
`COMPATIBLE`, nunca identidad confirmada por sí sola. Si dos direcciones
cubren todos los anclajes, se abstiene. El historial observado no vence al
original. La propuesta sigue siendo de sólo lectura y requiere confirmación
humana antes de cualquier cambio productivo.

Si OpenRouter falla, esta ruta puede mostrar búsquedas anteriores de la
caché como evidencia externa de contexto, sin convertirlas en candidatos
verificados. El material no dispara búsqueda web: usa el original, OCR y
evidencia documental/Atlas existentes.
