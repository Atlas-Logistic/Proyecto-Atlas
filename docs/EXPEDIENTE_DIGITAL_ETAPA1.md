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

## Base funcional P2 (09/11/2026)

Amplía este mismo módulo (almacén versión 2; un almacén v1 se lee y se convierte al escribir). Prevalece sobre lo
anterior donde difiera. Sin consumidores todavía: sin interfaz, sin CLI, sin notificaciones y sin despliegue.

- **Expediente:** `crear_expediente` da uno por identidad y empresa, con `expediente_id` propio. Vehículo: `vehiculo_id`
  (también se encuentra por patente o alias). Chofer: clave de catálogo más las claves vinculadas en su ficha
  (`referencias_catalogo`). Una clave nueva sin vínculo de ficha es otra identidad: nunca se adivina.
- **Documento:** tipo, `fecha_emision` (opcional), `fecha_vencimiento`, `estado` (ACTIVO / REEMPLAZADO / ANULADO),
  `archivo`, `sha256`. `registrar_documento` acepta `contenido` + `mime_type` (PDF/JPG/PNG, 20 MB, misma validación que
  las licencias) y lo guarda con nombre único en `archivos/expediente/<expediente_id>/`, o `archivo` para referenciar
  uno que ya está en la empresa.
- **Tipos:** base `LICENCIA_CONDUCIR`, `SOAP`, `REVISION_TECNICA`, `PERMISO_CIRCULACION` (obligatorios) y `SEGURO_CARGA`.
  `configurar_tipo_documento` agrega tipos por empresa, con o sin vencimiento y obligatorios o no.
- **Modificaciones:** `actualizar_documento` (fechas, con motivo) y `anular_documento`; cada operación deja evento en
  `historial` con actor, instante y antes/después. Archivo y huella no se editan: otro original es otro documento.
  Anular no reactiva el documento reemplazado.
- **Consulta (sólo lectura):** `consultar_expediente`, `consultar_vencimientos`, `documentos_ausentes`, `estado_expediente`,
  `documentos_por_atender`, `verificar_originales`. Estados: VIGENTE, POR_VENCER (≤ 30 días), VENCIDO, SIN_VENCIMIENTO,
  PENDIENTE_REVISION, FECHA_INVALIDA.
- **Fichas:** los documentos de choferes y vehículos entran en sólo lectura. Sin vencimiento quedan PENDIENTE_REVISION y no
  cubren un obligatorio; `confirmado_por_humano` es falso si el vencimiento vino de OCR automático. Una ficha ilegible es
  error, no ausencia de documentos.
- **Alertas:** `preparar_alertas_vencimiento` devuelve candidatas con `alerta_id` estable; no envía ni persiste nada.
- **Aislamiento:** almacén, originales, tipos y documentos por empresa; un almacén copiado de otra empresa se rechaza.
  El modelo es una raíz por empresa. Si dos empresas comparten raíz, cada llamada debe indicar `carpeta_catalogos`: la
  omisión usaría `<raiz>/catalogos_privados` para ambas.
- **Concurrencia:** `bloqueo_sesion` rechaza al competidor con `SesionOcupadaError`; quien integre debe reintentar.

Pendiente de decidir: migración de licencias de fichas al expediente, entrada CLI/IPC e interfaz, envío de alertas.
