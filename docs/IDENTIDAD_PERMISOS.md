# Identidad y permisos por empresa

Usuarios administrativos independientes por empresa. Los permisos se aplican en el backend: en el Motor y en Cloud. Código: `atlas_core/identidad.py` y `usuarios_atlas.py`.

## Roles

| Rol | Dónde vive la cuenta | Puede |
|---|---|---|
| `superadministrador_atlas` | `<unidad>\Atlas_plataforma\usuarios_plataforma.json`, fuera de toda empresa | Crear el primer administrador de una empresa, o reponerlo si la empresa no tiene ninguno activo. Desactivar un administrador. Listar solo los administradores |
| `administrador_empresa` | `catalogos_privados\desktop_usuarios.json` de su empresa | Gestionar usuarios de su empresa: crear, desactivar, reactivar, cambiar rol y restablecer contraseña. Gestionar las cuentas Mobile de sus choferes. Activar la exigencia de identidad. Consultar, corregir y configurar la operación |
| `supervisor` | el mismo registro | Consultar y corregir la operación |
| `chofer` | su cuenta Mobile existente (`usuarios_mobile.json` y D1) | Enviar sus guías. Esto lo aplica el Worker a su sesión Mobile. En el Motor no tiene ningún permiso |

Hay tres reglas que impiden el acceso indiscriminado y el escalamiento de privilegios:

- **Límites del superadministrador.** No tiene ningún permiso operacional. No puede crear un segundo administrador mientras la empresa tenga uno activo. Tampoco puede restablecer la contraseña de un administrador, así que no puede suplantarlo.
- **Límites del administrador.** Solo asigna los roles `administrador_empresa` y `supervisor`. No puede desactivarse a sí mismo ni cambiar su propio rol, de modo que la empresa nunca queda sin administrador.
- **Auditoría.** Cada cambio queda en `auditoria` dentro del registro, con su actor: `plataforma:<u>` o `<empresa>:<u>`.

Los roles `operacion` y `consulta` de la rama de acceso de Desktop se siguen respetando. Equivalen a supervisor y a solo consulta, respectivamente.

## Cómo se aplica

1. **La puerta del proceso.** `atlas_core/__init__.py` ejecuta `identidad.entrar_proceso` después de la guarda de aislamiento. Si el registro de la empresa tiene `exigir_identidad: true`, cada proceso del Motor identifica su punto de entrada en `CAPACIDADES` y exige el permiso que le corresponde:
   - `operacion.consultar`: B1 consultas y Consultas Atlas.
   - `operacion.corregir`: B1 operador, acciones, decisiones y reportes.
   - `operacion.configurar`: migraciones y reconciliación.
   - `usuarios.gestionar`: altas Mobile.

   Los procesos de sistema no necesitan sesión: PULL, mantenimiento, custodia y alta. Un punto de entrada no clasificado se niega; una prueba exige que todo CLI del Motor esté clasificado. Una denegación termina con código **77** y una línea JSON en stderr, por ejemplo `{"error": "PERMISO_DENEGADO", ...}`.
2. **Sesiones.**
   - `usuarios_atlas.py iniciar-sesion` verifica la contraseña (mismo hash pbkdf2 que el Motor) y entrega un secreto de un solo uso. En disco solo queda su huella sha256, en la carpeta local de **esa** empresa: `%LOCALAPPDATA%\Atlas\empresas\<id>\identidad\sesiones`. Las sesiones de plataforma van en `%LOCALAPPDATA%\Atlas_plataforma\sesiones`.
   - El secreto viaja en la variable `ATLAS_SESION`.
   - Una sesión de otra empresa no existe en la carpeta local de esta, y además la guarda de aislamiento impide leer la ajena.
   - En cada uso la sesión se vuelve a comprobar contra el registro. Desactivar, cambiar el rol o restablecer la contraseña la revocan al instante.
   - Tras 5 intentos fallidos hay una espera de 30 segundos.
   - La sesión dura 8 horas; la de plataforma, 1 hora.
3. **Escrituras.** El registro se escribe con el escritor oficial (turno local, lease Cloud y custodia), igual que `alta_chofer_mobile`. Así llega a la custodia y a los demás equipos.
4. **Cloud.** `usuarios_atlas.py desactivar-chofer` pone primero `activo=0` en D1, mediante `migrar_usuario_mobile_cloud.py --desactivar`, que solo actúa si el usuario es de esa empresa. Como el Worker valida `activo` en cada petición, también se rechazan las sesiones Mobile ya abiertas. Después marca la cuenta local. La sesión Mobile de un chofer nunca accede a la API del Motor.

## Uso

Todas las órdenes se ejecutan con el entorno de la empresa, como lo hacen Desktop y `alta_empresa.py`. La contraseña se escribe en la primera línea de stdin.

```
usuarios_atlas.py plataforma-inicializar --usuario propietario --nombre "Propietario Atlas"   (una sola vez)
usuarios_atlas.py iniciar-sesion --usuario propietario --plataforma
ATLAS_SESION=<sesión del superadministrador>
  usuarios_atlas.py crear --usuario ana.admin --nombre "Ana" --rol administrador_empresa
ATLAS_SESION=<sesión de ana.admin>
  usuarios_atlas.py exigir-identidad --activar
  usuarios_atlas.py crear --usuario luis.sup --nombre "Luis" --rol supervisor
  usuarios_atlas.py desactivar --usuario luis.sup
  usuarios_atlas.py desactivar-chofer --usuario pedro.chofer
```

Las demás órdenes son `listar`, `reactivar`, `cambiar-rol`, `restablecer-contrasena`, `reactivar-chofer`, `quien-soy` y `cerrar-sesion`.

Mientras una empresa no active la exigencia, nada cambia. Es el caso de MBT hoy. Para activarla hace falta al menos un administrador activo. Una vez activa:

- dar de alta choferes (`alta_chofer_mobile.py`, o `alta_empresa.py` repetido) exige la sesión de un administrador en `ATLAS_SESION`;
- un registro ilegible o copiado de otra empresa bloquea todos los procesos.

## Integración pendiente con Desktop

No se hizo en esta fase porque Codex trabaja en Desktop. La rama `feat/multiempresa-acceso-desktop-20261118` ya lee este mismo registro. Para integrarla falta:

1. Aceptar los roles nuevos en `ROLES`. Hoy acepta solo `consulta` y `operacion`, y con cualquier otro rol cierra.
2. Al ingresar, llamar a `usuarios_atlas.py iniciar-sesion` y pasar `ATLAS_SESION` a los procesos del Motor que lance.
3. Ocultar en la interfaz las funciones que el rol no tiene. Esto es solo comodidad: el Motor igual las niega.

## Límite declarado

Esto protege la frontera de la aplicación: los procesos del Motor y la API de Cloud. Quien administra la cuenta de Windows o el equipo puede leer y editar archivos directamente, y eso lo cubren el sistema operativo y la custodia. Desktop también lee algunos archivos de datos sin pasar por el Motor; esa lectura la controla la sesión de Desktop (integración pendiente) y no el Motor.

No incluye el panel administrativo, la facturación ni las suscripciones.

## Validación

```
.venv\Scripts\python.exe -B scripts\validacion_multiempresa\validar_identidad.py <mundo> <checkout Cloud> <checkout Desktop>
```

Son 62 verificaciones en un entorno sintético, con MBT y Andes ficticias y el Worker real en proceso. Cubren:

- plataforma y arranque;
- límites del superadministrador;
- gestión por el administrador;
- permisos del supervisor y del chofer;
- intentos de escalamiento;
- puerta sin sesión, con sesión inventada y con un punto de entrada no clasificado;
- accesos cruzados entre MBT y Andes;
- revocación: desactivar, reactivar, restablecer la contraseña, bajar de rol y desactivar un chofer en D1 y en Mobile;
- auditoría, custodia sin diferencias, secretos fuera del disco y MBT intacta.
