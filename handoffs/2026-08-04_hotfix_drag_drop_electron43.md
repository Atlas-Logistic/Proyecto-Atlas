# Handoff — Hotfix Drag & Drop Electron 43

## Causa y corrección

`e15d294` actualizó Electron 31.3.1 a 43.2.0. `File.path` pasó a ser indefinido,
aunque `DataTransfer.files` y `items` seguían conteniendo el archivo correcto.
El filtro descartaba todas las entradas antes del IPC.

El hotfix usa `webUtils.getPathForFile` desde preload y conserva aislamiento del
renderer. No se tocó OCR ni lógica de negocio.

## Evidencia

- JPEG/JPG/PNG reales: ruta absoluta y MIME correctos en el paquete instalado.
- 42/42 pruebas Desktop.
- Guía nueva `384674.jpg`: OCR 1/1, cero errores, 54,15 s.
- Duplicado `464089.jpeg`: detectado y dirigido al diálogo de reprocesamiento.
