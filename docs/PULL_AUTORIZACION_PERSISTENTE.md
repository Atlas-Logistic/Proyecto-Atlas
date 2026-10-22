# Autorizacion persistente del consumidor

El gate local `pull_autorizacion.json` es distinto de la credencial Motor y
del lease Cloud temporal. El modo antiguo sin `modo` conserva su vencimiento;
no se convierte implicitamente en persistente.

Para autorizar explicitamente un equipo se usa JSON UTF-8, sin fecha lejana:

```json
{
  "schema_version": 1,
  "modo": "persistente",
  "autor": "Javier",
  "exclusividad_verificada": true,
  "habilitada": true,
  "revocada": false,
  "machine_guid": "IDENTIDAD_LOCAL_WINDOWS"
}
```

`machine_guid` debe coincidir con MachineGuid de Windows y con el perfil
`desktop_operacion.json`. No copiar el gate para habilitar otro computador.
No es un secreto ni reemplaza autenticacion Cloud. Se confia en el usuario
Windows autorizado para administrar esta configuracion, como antes.

El lanzador valida antes del consumo y exporta la ruta del gate al proceso.
El orquestador vuelve a leer gate y perfil mediante el callback existente de
continuidad y la guardia de mutaciones, incluyendo recuperacion de locks
huerfanos. La revocacion impide nuevas escrituras y ACK al siguiente control;
no deshace escrituras ya terminadas. No promete cancelar atomicamente una
operacion del sistema ya iniciada. Borrado, JSON invalido, equipo ajeno,
`revocada:true`, `habilitada:false` o perfil desautorizado fallan cerrado.

Para revocar: editar atomicamente el gate con `revocada:true` o retirarlo.
Para suspender antes de mantenimiento: deshabilitar la unica tarea y esperar
fin de ciclo, sin terminar procesos. Restaurar el gate requiere autorizacion
del responsable. El lease sigue renovandose y venciendo normalmente; errores
de credencial Cloud impiden adquirirlo o invalidan su renovacion. Se conserva
la guardia de perdida de lease y la coordinacion manual/PULL.

Instalar: respaldar gate/config/tarea; impedir nuevos disparos durante el
fast-forward del Motor y esperar cierre; instalar commit probado; emitir gate
persistente para la identidad local; `scripts/pull_pc_nuevo.ps1 -Validar`;
habilitar la tarea existente y comprobar ciclos disparados automaticamente.
La tarea mantiene rutas persistentes en disco y trigger de inicio de sesion;
credencial Motor del usuario debe existir en el entorno de la nueva sesion.

Reversion: suspender y esperar fin; restaurar gate temporal respaldado y
version anterior del Motor con arbol limpio; revalidar antes de habilitar.
Si el gate temporal ya vencio, permanece detenido hasta emitir otra
autorizacion valida. No restaurar datos de guias ni crear segunda tarea.

Limites: requiere equipo encendido, conexion, sesion de usuario, rutas/runtime
validos, credencial vigente y lease adquirido. No resuelve escritores de
OFICINA que ignoren el arbitraje compartido. Antes de encenderlos, impedir su
arranque o verificar que respetan el mismo protocolo.
