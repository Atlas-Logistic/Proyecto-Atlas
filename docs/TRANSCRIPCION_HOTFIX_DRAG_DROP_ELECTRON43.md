# Transcripción técnica — Hotfix Drag & Drop Electron 43

El evento drop era correcto: para `464089.jpeg` había un elemento en
`DataTransfer.files`, uno en `DataTransfer.items`, tipo `file`, MIME
`image/jpeg`. La extensión nominal era `.jpeg`, pero el código obtenía la ruta
con `File.path`; Electron 43 devuelve `undefined`. El filtro exigía ruta no
vacía y descartaba el archivo.

La regresión apareció en `e15d294`, actualización de Electron 31.3.1 a 43.2.0.
El último commit funcional de esa línea era `f293e8c`. Existía una corrección en
una rama divergente, pero no formaba parte de la línea desplegada.

La solución usa la API oficial `webUtils.getPathForFile` a través de preload.
La instalación activa resolvió rutas reales para JPEG, JPG y PNG. Una guía JPG
nueva ejecutó OCR y el nombre duplicado `464089.jpeg` activó la detección previa
al diálogo. No se modificaron componentes del motor.
