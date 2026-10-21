# Canal manual Desktop — 21/10/2026

desktop_operacion_cli.py recibe JSON por stdin. `ingresar` conserva originales, crea lote único, usa el procesador canónico con reconciliación focal, genera reporte y devuelve un resultado sólo si no hay filas ERROR. `script` limita la ejecución a CLIs de revisión expresamente enumerados, conservando stdin y argv.

Raíces compartidas: lease global de escritor antes de cualquier escritura y durante toda la transacción. Ausencia de token, ocupación o pérdida de lease fallan cerrado; no se ejecuta PULL. Raíces locales físicamente independientes pueden operar sin PULL ni red. Auditoría limita escrituras a raíz operacional, temporales y modelos configurados; conserva los locks de dataset del Motor.

35 pruebas focales/regresión aprobadas (7 nuevas de sesión y 28 de deduplicación/recuperación/ingesta focal). Aplicación instalada probada con PDF/PNG, viaje 0000990001 y revisión real sobre datos aislados.

En JAVO falta ATLAS_CLOUD_MOTOR_TOKEN para arbitrar G: con oficina y falta autorización de Javier para la primera escritura real. No hacen falta credenciales Mobile/Onelogis ni acceso administrativo Cloudflare para esta función. No se activó PULL ni se modificaron datos productivos.
