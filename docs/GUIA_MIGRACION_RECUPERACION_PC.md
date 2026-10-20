# Guía P0 — recuperación de Atlas en un computador de reemplazo

## Propósito y límites

Este procedimiento recupera el código y el estado operacional sin ejecutar
OCR, PULL, reconciliación ni acciones sobre datos durante la migración. La
primera ejecución productiva sólo se autoriza después de completar la lista de
validación final.

No copiar tokens, contraseñas, claves privadas ni archivos de credenciales a
esta guía, a Git ni al respaldo de datos.

## Insumos que se deben tener antes de comenzar

1. Acceso a la organización GitHub `Atlas-Logistic` con lectura de los cuatro
   repositorios y, si se requerirá publicar, permisos de escritura.
2. Acceso a la cuenta Google Drive que contiene `Mi unidad/Atlas`, incluida la
   carpeta de respaldo P0 validada. Configurarla en el nuevo PC y esperar la
   sincronización completa antes de restaurar.
3. Acceso administrativo a Cloudflare: Worker de recepción Mobile, D1, R2 y
   secretos del Worker. No recuperar un secreto desde un archivo de código.
4. Los secretos entregados por el responsable mediante un canal aprobado. Los
   valores necesarios se enumeran abajo sólo por nombre.
5. El respaldo `RECUPERACION_P0_20261020_101300_COMPLETO`, su
   `MANIFEST_SHA256.txt`, `METADATA.json`, `VERIFICATION_SHA256.json` y
   `RESTORE_TEST.json`.

## Software base comprobado en oficina

Instalar versiones compatibles antes de instalar dependencias:

- Git 2.55 o posterior compatible.
- Python 3.12 (la instalación de oficina usa 3.12.10).
- Node.js 24 (oficina: 24.19.0) y npm 11 (oficina: 11.17.0).
- Cliente Google Drive para escritorio, con una raíz conocida para Atlas.

Docker no es requisito del arranque actual. `wrangler` se instala como
dependencia local del repositorio Cloud, no como requisito global.

## Código: clonar las ramas resguardadas

En una carpeta de trabajo nueva, clonar sin copiar `.git`, `node_modules`,
entornos virtuales ni archivos de configuración del PC anterior.

| Componente | Repositorio | Rama resguardada | Referencia P0 |
| --- | --- | --- | --- |
| Motor | `Atlas-Logistic/Proyecto-Atlas` | `fix/ingesta-482179` | `4aec668` |
| Desktop | `Atlas-Logistic/Atlas-Viajes-Desktop` | `fix/chofer-nombre-identidad-mobile` | `ecf8e58` |
| Mobile | `Atlas-Logistic/Atlas-Conductores-Mobile` | `fix-mobile-login-ux` | `507c099` |
| Cloud | `Atlas-Logistic/Atlas-Mobile-Cloud` | `feat/sesion-mobile-renovable` | `74c46d6` |

Comprobar para cada clon que `git status --short --branch` no tiene cambios y
que el commit esperado existe. No integrar ramas a `main` ni a Estable durante
la recuperación.

## Instalar dependencias, sin arrancar servicios

### Motor

1. Crear un entorno virtual Python 3.12 exclusivo para el Motor.
2. Instalar `requirements.txt`: EasyOCR, numpy, Pillow, pypdfium2 y pytest.
3. RapidOCR es opcional y debe vivir en un entorno separado. Instalar allí
   `requirements-rapidocr-optional.txt` (`rapidocr-onnxruntime==1.4.4` y
   `onnxruntime==1.31.0`). No mezclarlo con el entorno principal.
4. `requirements-importador-osm.txt` sólo se requiere para importar un PBF de
   OSM; no es necesario para operar con la base local ya restaurada.

### Desktop

1. Ejecutar la instalación reproducible desde `package-lock.json` (por
   ejemplo, `npm ci` usando `npm.cmd` si PowerShell bloquea `npm.ps1`).
2. No iniciar `start`, `preactivacion` ni `build` todavía.
3. Recrear la configuración de rutas con los valores del nuevo equipo; la
   configuración de oficina contiene rutas locales y no debe copiarse sin
   revisión.

### Mobile y Cloud

1. Instalar dependencias del repositorio Mobile según su `package.json` y
   lockfile disponible. No iniciar `dev` ni generar certificados en la etapa
   de recuperación.
2. En Cloud, instalar estrictamente desde `package-lock.json`. El proyecto fija
   `wrangler` 4.143.0 como dependencia de desarrollo; usar el binario local.
3. No ejecutar `deploy`. Antes de cualquier despliegue, comprobar en Cloudflare
   que los bindings de Worker, D1 y R2 existentes son los esperados.

## Restaurar datos desde Google Drive

1. Trabajar contra una copia local aislada del respaldo P0, nunca contra
   `operacion/actual` productivo mientras se valida.
2. Verificar todos los hashes de `MANIFEST_SHA256.txt` antes de promover datos.
   Debe haber 1.611 entradas y cero diferencias.
3. Restaurar el árbol `data/` respetando su estructura en la raíz configurada
   de Atlas. El respaldo cubre `operacion`, `catalogos_privados` y el reporte
   que referencia `operacion/actual/estado_operacion.json`.
4. Leer `estado_operacion.json` y comprobar que sus rutas relativas de dataset
   y reporte existen dentro de la raíz restaurada. No reemplazar esas rutas por
   una carpeta elegida por fecha.
5. Mantener fuera de la restauración inicial cachés, históricos y respaldos
   anteriores; no son parte del estado vigente P0.

La raíz debe estar disponible mediante `ATLAS_DATA_DIR` o la configuración
equivalente de Desktop. Preferir una ruta estable y documentada; no depender de
la letra `G:` si el cliente Drive del nuevo PC asigna otra letra.

## Configuración y secretos

Configurar valores sólo en el almacén seguro o entorno del nuevo PC. Confirmar
con el responsable si aplica cada uno, sin imprimir sus valores:

- Motor/PULL: `ATLAS_CLOUD_MOTOR_TOKEN`, `ATLAS_CLOUD_MOBILE_URL`,
  `ATLAS_MOBILE_SYNC_TOKEN`, `ATLAS_MOBILE_TOKEN_SECRET`,
  `ATLAS_ONELOGIS_API_KEY`, `ATLAS_DATA_DIR`, `ATLAS_CATALOGOS_DIR`,
  `ATLAS_OCR_PROVIDER`, `ATLAS_RAPIDOCR_PYTHON`.
- Desktop: `ATLAS_DATA_DIR`, `ATLAS_CONFIG_PATH`, `ATLAS_PYTHON`,
  `ATLAS_RAPIDOCR_PYTHON`, `ATLAS_USER_DATA_PATH` cuando corresponda.
- Mobile: `ATLAS_DATA_DIR`, `ATLAS_CONFIG`, `ATLAS_MASTER_CATALOGS`,
  `ATLAS_MOBILE_API_PROXY`; los certificados TLS, si se usan, se recuperan por
  el mecanismo aprobado, no desde Git.
- Cloudflare: `CLOUD_MOBILE_AUTH_SECRET`, `CLOUD_MOTOR_AUTH_SECRET` y los
  identificadores/variables de empresa requeridos por el entorno.

No se deben copiar secretos a `.env.example`, configuraciones versionadas,
capturas de pantalla, tickets públicos ni GitHub.

## Recuperar accesos externos

1. Iniciar sesión en GitHub con una credencial nueva o recuperada mediante el
   administrador de credenciales; confirmar lectura de los cuatro repositorios.
2. Iniciar sesión en Google Drive y comprobar que el respaldo P0 se puede ver
   mediante la web/API, no sólo por la caché local.
3. Con el administrador de Cloudflare, comprobar en modo lectura la cuenta,
   Worker, D1 y R2; cotejar los bindings con `wrangler.toml`. No desplegar ni
   aplicar migraciones durante esta comprobación.

## Recrear la tarea PULL de forma segura

La tarea de oficina usa `wscript.exe` para lanzar un VBS que espera el cierre
del script PowerShell. El script a su vez ejecuta
`sincronizar_mobile_cloud.py --raiz-atlas <raiz-de-Atlas>` y la tarea está
configurada con `MultipleInstances=IgnoreNew`.

En el nuevo PC:

1. Adaptar el lanzador a la ruta nueva de Python 3.12, al entorno aislado de
   RapidOCR y a la raíz de Atlas; guardar los logs en una ruta local nueva.
2. Registrar la tarea con `IgnoreNew` y sin iniciar una ejecución automática al
   crearla.
3. Antes de habilitarla, comprobar en modo lectura que existen datos restaurados,
   secretos, conectividad Cloud y acceso al lease global de escritor.
4. Realizar la primera ejecución sólo con autorización operacional. El PULL ya
   usa lease global: si otro escritor lo posee, no debe existir un fallback que
   escriba localmente.

## Orden de arranque seguro

1. Validar repositorios, dependencias, secretos y hashes del respaldo.
2. Restaurar datos y validar el manifiesto de operación sin abrir Desktop ni
   ejecutar Motor.
3. Configurar Desktop para la nueva raíz y abrirlo sin acciones de
   preactivación, OCR o reconciliación.
4. Verificar Cloud en lectura y la tarea PULL deshabilitada/no ejecutada.
5. Obtener autorización para una primera ejecución PULL; vigilar que sólo haya
   un escritor global y que no se duplique procesamiento.
6. Habilitar la programación periódica únicamente después de esa validación.

## Criterio de cierre

La migración queda lista cuando un responsable confirma: acceso GitHub,
Google Drive y Cloudflare; hashes del respaldo correctos; referencias de
`estado_operacion.json` válidas; rutas del nuevo PC configuradas; y tarea PULL
creada pero no activada hasta la autorización operacional.
