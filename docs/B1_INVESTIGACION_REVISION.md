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
