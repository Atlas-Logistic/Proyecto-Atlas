# Aislamiento de datos por empresa

**Estado: integrado en el Motor, NO completado como soporte multiempresa.** Quedan
componentes (ver "Pendiente") que deben cerrarse antes de operar una segunda empresa.

`atlas_core/aislamiento_empresas.py`. Un solo Motor, una raíz por empresa.

## Modelo

| Empresa | Raíz | Marca | Estado local |
|---|---|---|---|
| MBT (`mbt`) | `Atlas`, intacta | ninguna | `%LOCALAPPDATA%/Atlas` |
| Otra (`<id>`) | `<padre de Atlas>/Atlas_empresas/<id>` | `catalogos_privados/empresa_identidad.json` | `%LOCALAPPDATA%/Atlas/empresas/<id>` |

Guías, viajes, clientes, choferes, vehículos, documentos y reportes quedan
separados por la raíz: un mismo folio, cliente o RUT en dos empresas no colisiona.
MBT conserva `empresa-prueba-javier` (Cloud) y `oficina` (registro).

## Entrada

`atlas_core/__init__.py` llama a `entrar_proceso`, de modo que ninguna CLI puede
saltarse la frontera y los subprocesos heredan la empresa por entorno.

- Sin `ATLAS_EMPRESA_ID` y sin `Atlas_empresas`: **MBT exactamente igual**, sin guarda,
  sin envolturas de `os.stat` y con las mismas rutas.
- Sin `ATLAS_EMPRESA_ID` y con `Atlas_empresas`: MBT con guarda.
- Con `ATLAS_EMPRESA_ID`: exige `ATLAS_RAIZ_MBT` y `ATLAS_DATA_DIR` coherentes; fija
  cache, diagnóstico, logs, configuración y autorización de esa empresa, y cambia el
  token a `ATLAS_CLOUD_MOTOR_TOKEN__<ID>`. Sin token propio queda **sin** token, nunca
  con el de MBT.
- Un entorno ambiguo aborta al importar.

PULL: `pull_pc_nuevo.ps1 -Empresa <id>`; sin `-Empresa`, el flujo actual.

## Guarda

Un proceso, una empresa. Veta abrir, listar, crear, renombrar, borrar y también
consultar metadatos (`os.stat`, `lstat`, `access`, `readlink`, `os.path.exists`,
`isfile`, `isdir`, `getsize`, `getmtime`...), también a través de enlaces. Lanza
`ErrorAislamiento`, que no es `OSError`, para que los lectores que toleran `OSError`
no conviertan un cruce en "sin datos". Solo se permiten los ancestros de lo propio.
Una empresa no accede a la carpeta local de MBT salvo `runtime` (OCR compartido).

**Límite:** es una guarda dentro del proceso. No intercepta código nativo que abra
archivos por su cuenta (p. ej. `cv2.imread`, `ctypes`) ni los workers de OCR, que
corren en otro runtime y reciben rutas de un proceso ya guardado. Una barrera
absoluta exigiría usuario de Windows o ACL por empresa.

## Cloud

Cloud deduce la empresa del token. `CustodiaEstado` exige la raíz del proceso, usa la
carpeta local de la empresa y, antes de restaurar, comprueba la marca del manifiesto.
Con varias empresas consulta siempre el manifiesto real: la caché local va por versión
y un token ajeno de igual versión pasaría por el manifiesto propio.
El cliente Mobile rechaza un lease de otra empresa antes de descargar.

## Worker (validado en aislado, sin desplegar)

Rama `p2/multiempresa-worker-aislado-20261109` del Worker, sobre el commit desplegado
`b39e3bd`. Añade el secreto opcional `CLOUD_MOTOR_TOKENS_JSON`
(`{"<sha256 del token>": "<empresa_id>"}`). Sin él, el Worker es idéntico. Todas las
consultas D1 y claves R2 ya filtraban por `empresa_id`.

## Recuperación

Alta: `inicializar_empresa` y `custodia.sembrar(lease)` en el primer turno.
Equipo nuevo: `abrir_empresa(..., restauracion=True)`, lease (verifica y restaura) y
`confirmar_restauracion`.

## Pendiente antes de operar otra empresa

1. **Worker:** desplegar `CLOUD_MOTOR_TOKENS_JSON`, decisión productiva no tomada.
2. **Desktop (Electron):** sin selector de empresa; `main.js` (protegido) no fija
   `ATLAS_EMPRESA_ID`/`ATLAS_RAIZ_MBT` y su configuración de usuario es única.
3. **Tarea programada:** `instalar_tarea_pull.ps1` y `actualizar_equipo_relevo.ps1`
   instalan una sola tarea, sin `-Empresa`.
4. **Mobile:** `nombre_usuario` es único global y el login no pide empresa. Es seguro
   (no mezcla), pero dos empresas no pueden repetir usuario; hay que definir el alta.
5. **`crear_usuario_mobile.py`:** alta de usuarios por empresa sin definir.
6. **OCR y código nativo:** ver el límite de la guarda.
7. **OFICINA:** requiere el mismo código antes de que existan otras empresas.
8. **Datos base:** una empresa nueva no recibe `datos_privados/geografia` ni catálogos
   (por diseño); falta definir su carga inicial.
