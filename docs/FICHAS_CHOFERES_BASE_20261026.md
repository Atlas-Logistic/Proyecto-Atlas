# Primera base de fichas digitales de choferes

La identidad principal usa exclusivamente choferes.json: nombre, RUT canónico,
activo/inactivo y alias. `rut_catalogo` es el campo principal de Desktop;
`rut` conserva la respuesta histórica para lectores anteriores. Ningún RUT
observado en una guía sustituye al canónico de la ficha.

Las asignaciones vigentes son una proyección de vehículos CONFIRMADO/ACTIVO
y sus evidencias humanas de soporte, usando la regla vigente del Motor.
Se muestran aparte de los vehículos del historial. Dos patentes vigentes del
mismo tipo se informan como conflicto, no se escoge una. No se escriben
asignaciones, catálogos, viajes, tarjetas ni eventos operacionales.

## Almacén persistente

Ruta: `<raiz>/fichas_digitales/MBT/fichas_documentales.json`.
Empresa confiable fijada por backend: `EMPRESA_ACTUAL=MBT`, igual que el IPC
documental ya instalado; el renderer no selecciona empresa. No se habilita
multiempresa: sólo se conserva el aislamiento del almacén y referencias.

Esquema de versión 2:

```json
{
  "version": 2,
  "empresa": "MBT",
  "revision": 1,
  "plazos_alerta_dias": {},
  "choferes": [{
    "ficha_id": "UUID persistente",
    "referencias_catalogo": ["identificador actual o temporal"],
    "complementarios": {
      "contacto": {"telefono": "", "correo": ""},
      "personales": {"domicilio": "", "fecha_nacimiento": null}
    },
    "documentos": [],
    "historial": [{"accion": "FICHA_CREADA", "actor": "OPERADOR", "fecha": "ISO UTC"}]
  }],
  "vehiculos": []
}
```

Los documentos existentes conservan tipo, clase, vencimiento y ruta relativa;
la migración les agrega documento_id. La colección admite metadatos futuros
sin crear adjuntos. No existe carga ni renovación de archivos en esta etapa.
No se guardan nombre, RUT, activo ni aliases en la ficha complementaria.

Lectura compatible de v1/v2. La migración v1 sólo enlaza documentos por RUT
canónico único del catálogo, no por nombre ni RUT histórico. Documentos sin
vínculo único se conservan en choferes_legacy_sin_vincular; no se adjudican.
Los registros vehiculares y plazos existentes se conservan íntegramente.

## Identidad estable y cambios de clave

El UUID se crea una sola vez mediante mantenimiento explícito y queda
persistido. Las consultas son sólo lectura y jamás inicializan archivos.
Renombrar o corregir el RUT explícito en el mismo registro conserva el UUID.
Un cambio de clave del catálogo requiere un vínculo explícito anterior=actual.
Si existen claves retiradas y nuevas, la inicialización se abstiene hasta que
se indiquen esos vínculos; nunca infiere una persona por coincidencia nominal.
Las claves temporales se aceptan como referencias válidas.

CLI: `inicializar_fichas_choferes.py --raiz-atlas <raiz> --actor <actor>`.
Para una regularización ya realizada por el mecanismo de catálogo autorizado:
`--vinculo PENDIENTE00000006=<nueva-clave>`.
Este comando NO modifica el catálogo ni regulariza el RUT: sólo conserva el
vínculo de la ficha ante un cambio explícito. Conserva referencias anteriores,
contacto, documentos y auditabilidad. Una segunda corrida sin cambios no escribe.

El CLI adquiere la sesión oficial, respaldo previo (o manifiesto de ausencia),
lock propio, valida la revisión/esquema y publica JSON atómico. No participa
en B1 ni altera escritor_operativo/desktop_operacion. No hay nuevo IPC de escritura.

## Validación y despliegue

Pruebas focales: test_fichas_choferes_base.py y test_catalogo_fichas_v2.py.
Ensayar primero sobre copia de los seis insumos del snapshot. Respaldar código,
catálogos de referencia y cualquier almacén anterior antes de inicializar la
raíz real. Publicar Motor y Desktop compatibles, verificar UUID únicos para los
31 registros y las seis claves temporales. Comprobar que catálogo/vehículos y
dataset no cambian. El cálculo y presentación de vigencia no modifica activo.

Siguiente incremento mínimo: una acción documental de carga de licencia con
selección de archivo, clase y vencimiento, vinculada a empresa+ficha_id; debe
copiar el archivo validado, registrar hash/metadatos y auditoría bajo el mismo
escritor. No necesita OCR ni reconciliación de viajes.
