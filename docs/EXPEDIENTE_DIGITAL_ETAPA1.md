# Expediente digital de choferes y vehículos -- etapa 1 (28/10/2026)

Módulo `atlas_core/expediente_digital.py`: base persistente y vista derivada. Sin interfaz, alertas, carga de
archivos ni Mobile. No modifica catálogos, fichas, B1, viajes ni OCR. Sin despliegue (sin consumidores aún).

- **Identidad:** sólo referencias a los catálogos existentes (clave de `choferes.json`, `vehiculo_id` de
  `vehiculos.json`); se valida que la identidad exista y sea única. Nunca copia nombre, RUT ni patente.
- **Tipos:** chofer `LICENCIA_CONDUCIR`; vehículo `REVISION_TECNICA`, `SOAP`, `PERMISO_CIRCULACION`. Cada
  documento: `documento_id`, tipo, `fecha_vencimiento` (AAAA-MM-DD), `archivo` (referencia relativa
  `archivos/...` de la empresa; no se copia ni abre), `sha256` opcional, actor, `registrado_en`.
- **Almacén:** `fichas_digitales/<EMPRESA>/expediente_documentos.json` (versión 1, `revision`), misma
  validación de empresa que las fichas de choferes; escritura atómica bajo bloqueo; append-only: un documento
  nuevo del mismo tipo e identidad marca el anterior `reemplazado_por`.
- **Vista derivada:** `estado_expediente(raiz, empresa, hoy)` → documentos vigentes con `estado_vencimiento`
  (VENCIDO / POR_VENCER ≤ 30 días / VIGENTE) y `dias_para_vencer`; nunca se persiste.
  `documentos_por_atender` devuelve vencidos y próximos (base para alertas futuras). Incluye en sólo lectura
  las licencias ya registradas en `fichas_documentales.json`; si el expediente registra una para el mismo
  chofer, prevalece la del expediente.

## Siguiente etapa (no iniciada)

CLI/IPC de lectura y registro con preview y confirmación, carga y validación de archivos (reutilizar la de
licencias de `fichas_choferes`), interfaz en Desktop, alertas y decidir la migración de las licencias de fichas
al expediente.

## Integración etapa 2A (28/10/2026)

Integrado sobre 198c5c9 sin cambios de código. La licencia de conducir se sigue escribiendo sólo con
`fichas_choferes.registrar_licencia_chofer` en `fichas_documentales.json` (botón de Desktop): fuente única,
sin almacén paralelo. `estado_expediente` la lee en sólo lectura (verificado contra una licencia escrita por
ese escritor: sólo la vigente, separada por empresa, mismo estado de vencimiento que Desktop) y
`expediente_documentos.json` no se crea. `registrar_documento` queda sin consumidores hasta decidir SOAP,
revisión técnica y permiso de circulación y la migración de licencias.
