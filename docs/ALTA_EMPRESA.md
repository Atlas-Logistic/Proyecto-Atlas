# Alta integral de una empresa

Este procedimiento incorpora una empresa nueva a Atlas, junto a MBT y a las que ya existan. Es un comando único, `alta_empresa.py`, y se puede repetir sin riesgo. Cada paso usa el mecanismo que ya tiene Atlas, y ninguno toca MBT ni otra empresa.

## 1. Preparar el plan

El plan es un archivo JSON. No lleva secretos.

```json
{
  "version": 1,
  "empresa_id": "transportes-andes",
  "nombre": "Transportes Andes",
  "cloud_id": "cloud-transportes-andes",
  "catalogos_iniciales": "C:\\Atlas\\altas\\andes\\catalogos",
  "choferes_mobile": [
    {"usuario": "luis.reyes", "rut": "12.345.678-5", "nombre": "LUIS REYES"}
  ]
}
```

- **`empresa_id`**: el identificador permanente. Va en minúsculas, con números y guiones. No puede ser `mbt`.
- **`nombre`**: el nombre que Desktop muestra en el menú «Empresa».
- **`cloud_id`**: el identificador de la empresa en Cloud (D1/R2). Es único. El de MBT no se puede usar.
- **`catalogos_iniciales`** (opcional): una carpeta con `choferes.json`, `vehiculos.json`, `clientes.json`, `destinos_maestros.json`, `obras_destinos.json`, `empresas.json`, `plantas.json` o `rutas.json`. Cada archivo debe tener el mismo formato que el del Motor. Solo se usa para los catálogos que aún no existan. `usuarios_mobile.json` no se admite: las cuentas se crean con `choferes_mobile`.
- **`choferes_mobile`**: un chofer nuevo se agrega al catálogo y recibe su cuenta. Si el chofer ya está en el catálogo, solo se crea su cuenta.

## 2. Revisar sin escribir

```
cd C:\Atlas\Proyecto-Atlas
.venv\Scripts\python.exe alta_empresa.py --plan C:\Atlas\altas\andes.json --raiz-mbt "G:\Mi unidad\Atlas" --revisar
```

## 3. Ejecutar

```
.venv\Scripts\python.exe alta_empresa.py --plan C:\Atlas\altas\andes.json --raiz-mbt "G:\Mi unidad\Atlas" [--autorizar-pull-horas 8] [--instalar-tarea-pull]
```

El comando pide en consola la contraseña inicial de cada chofer que la necesite, y la pide dos veces. La contraseña nunca va en argumentos ni en archivos.

| Paso | Qué hace (mecanismo existente) | Dónde escribe |
|---|---|---|
| `registro` | Marca de la empresa (`aislamiento_empresas.inicializar_empresa`), desde un proceso de alta de esa empresa | `G:\Mi unidad\Atlas_empresas\<id>\catalogos_privados\empresa_identidad.json` |
| `estructura` | Crea las carpetas y los catálogos base o iniciales que falten, con el turno local | raíz de la empresa |
| `credencial` | Token Motor propio, aleatorio, que no se muestra | perfil Windows `ATLAS_CLOUD_MOTOR_TOKEN__<ID>` |
| `pull-config` | Política `lease_cloud` de la empresa | `%LOCALAPPDATA%\Atlas\empresas\<id>\desktop_operacion.json` |
| `pull-autorizacion` | Solo con `--autorizar-pull-horas N`: autorización temporal de Javier | `...\empresas\<id>\pull_autorizacion.json` |
| `pull-tarea` | Plan de la tarea `Atlas PULL <id>`; con `--instalar-tarea-pull`, se registra deshabilitada | Programador de tareas |
| `cloud` | Comprueba que el Worker reconoce el token. Solo lectura | — |
| `custodia` | Línea base Cloud (`estado_confirmado --sembrar`) bajo el lease de la empresa | D1/R2 de la empresa |
| `mobile:<usuario>` | Ver detalle abajo | catálogos de la empresa y D1 |
| `registro-desktop`, `verificar` | Comprobación final: marca visible para Desktop, catálogos completos, custodia sin diferencias | — |

El paso `mobile:<usuario>` hace lo siguiente:

1. Comprueba en D1 que el nombre de usuario no pertenezca a otra empresa.
2. Ejecuta `alta_chofer_mobile.py` con el escritor oficial.
3. Publica la cuenta en D1 con `migrar_usuario_mobile_cloud.py`.
4. Prueba el ingreso.

Códigos de salida:

- **0**: alta completa.
- **3**: falta un paso humano.
- **2**: error. Lo ya hecho se conserva. Hay que corregir la causa y repetir.

Cada ejecución deja un registro sin secretos en `%LOCALAPPDATA%\Atlas\empresas\<id>\alta\`.

## 4. Paso humano en Cloud (código 3)

La primera vez, el paso `cloud` queda PENDIENTE porque el Worker todavía no conoce el token. El comando imprime una línea como esta, que también queda en `alta\cloud_motor_token.json`:

```
{"<sha256 del token>": "cloud-transportes-andes"}
```

1. Agregue esa entrada al secreto `CLOUD_MOTOR_TOKENS_JSON` del Worker, **conservando las entradas existentes**, con `wrangler secret put CLOUD_MOTOR_TOKENS_JSON`.
2. Repita el mismo comando del paso 3. Esta vez se completan `custodia`, `mobile` y `verificar`.

Atlas nunca escribe ese secreto por su cuenta.

## 5. Garantías

- **Idempotencia.** Repetir el comando completa lo que falte y no cambia lo hecho. Nada se reemplaza: una configuración PULL distinta, un `cloud_id` distinto para la misma empresa o un usuario de otro chofer dan error, y no se escribe nada.
- **Aislamiento.**
  - Cada paso corre en un proceso con el entorno de la empresa, con su guarda activa.
  - El orquestador no importa `atlas_core` y no pasa a la empresa ninguna variable `ATLAS_*` de MBT.
  - El proceso de alta (`ATLAS_EMPRESA_ALTA=<id>`) solo puede listar `Atlas_empresas` y leer las marcas de las demás empresas, para no repetir un `cloud_id`. No puede leer sus datos ni escribir en ellas.
  - Los procesos normales siguen sin ver ninguna otra empresa.
- **Usuarios Mobile.** D1 es una sola tabla para todas las empresas. El UPSERT nunca modifica la fila de un usuario de otra empresa, y después se vuelve a leer la fila para comprobarlo.
- **Escrituras protegidas.** En una raíz compartida (Drive), todas las escrituras pasan por el turno local y, una vez sembrada la custodia, por el escritor oficial.

## 6. Pendientes fuera de este procedimiento

- Cargar la geografía y los catálogos operativos reales. `catalogos_iniciales` solo copia archivos ya preparados.
- Configurar la empresa en OFICINA. Allí la empresa aparece por su marca, pero el token se registra en cada PC.
- Las plantas AZA están fijas en la PWA y en el Worker.
- El rótulo de exportación.
- Los usuarios de acceso a Desktop (rama `feat/multiempresa-acceso-desktop-20261118`, no integrada).

## 7. Validación

Prueba de punta a punta en un entorno sintético con el Worker real en proceso, sin G:, sin Cloudflare y sin MBT real:

```
.venv\Scripts\python.exe -B scripts\validacion_multiempresa\validar_alta.py <mundo> <checkout Atlas-Mobile-Cloud> <checkout Desktop>
```

Cubre 37 verificaciones:

- revisión sin escritura;
- alta con el token aún desconocido para Cloud (PENDIENTE);
- paso humano y repetición que completa el alta;
- tercera repetición idempotente;
- login, envío y PULL reales de la empresa;
- rechazos: usuario homónimo de otra empresa, `cloud_id` repetido, `mbt`, escritura sin turno;
- alta de una tercera empresa;
- MBT byte a byte idéntica y barrido de marcadores.
