# Transcripción técnica — Despliegue controlado de Atlas Desktop

Se confirmó que la instalación utilizada por el usuario conservaba un build
anterior aunque el código de reprocesamiento ya había sido publicado. Para
cerrar esa discrepancia se incorporó un único comando oficial de despliegue de
desarrollo: `npm run deploy:dev`.

El comando exige un repositorio limpio, embebe commit y versión, construye la
distribución Windows, valida el `app.asar`, detiene exclusivamente la instalación
objetivo, conserva respaldo y configuración, despliega, relanza y vuelve a
validar el artefacto activo. La versión también queda visible en el pie de la
interfaz.

La instalación verificada corresponde al commit
`3bbd3b277fe1a37652c93d7c22cfbfe7da1e2ac7`, versión `1.2.0`, con SHA-256
`5e638fa7efa78202e9636b3ed198462d4b21feff397f75abc7ab63045afd418f`.

La guía real 464089 se reprocesó en 49,66 segundos: 1 procesado, 0 omitidos,
Chofer OCR `LEANDRO IOLEDO`. El reporte publica el canónico existente
`LEANDRO TOLEDO`, que quedó visible en Atlas Desktop. No se modificó ningún
componente del motor.
