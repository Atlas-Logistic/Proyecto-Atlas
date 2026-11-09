# Aislamiento de datos por empresa

`atlas_core/aislamiento_empresas.py`. Un solo Motor, una raíz operacional por
empresa. Hasta que un punto de entrada lo integre, no cambia el comportamiento
de nada: ningún módulo existente lo importa.

## Modelo

| Empresa | Raíz | Marca | Estado local de máquina |
|---|---|---|---|
| MBT (`mbt`) | la raíz `Atlas` actual, intacta | ninguna | las rutas actuales |
| Otra (`<id>`) | `<padre de Atlas>/Atlas_empresas/<id>` | `catalogos_privados/empresa_identidad.json` | `%LOCALAPPDATA%/Atlas/cache/empresas/<id>` |

Guías, viajes, clientes, choferes, vehículos, documentos y reportes quedan
separados porque viven bajo la raíz: se usan las mismas funciones de
`almacenamiento_portable` con otra `raiz`. Por eso un mismo folio en dos
empresas no colisiona y no hace falta una columna de empresa en cada archivo.

MBT conserva sus identificadores históricos: Cloud `empresa-prueba-javier`,
registro de relaciones `oficina`. No se renombran.

`Atlas_empresas` es hermana de `Atlas` y no hija: así queda fuera de la custodia
Cloud de MBT sin cambiar `estado_confirmado`.

## Garantías

- **Identidad.** `<id>` es inmutable, válido como carpeta y no reservado. Abrir
  exige que la marca coincida. Una raíz marcada no se abre como MBT, y una
  carpeta enlazada a otra no se acepta.
- **Rutas.** `ContextoEmpresa.ruta/exigir_propia` rechazan salir de la raíz.
- **Guarda de proceso.** `activar_guarda`: un proceso, una empresa. Veta abrir,
  listar, crear, renombrar o borrar en otra empresa, también a través de enlaces.
  Lanza `ErrorAislamiento`, que no es `OSError`, para que los lectores que
  toleran `OSError` no conviertan un cruce en "sin datos".
  Límite: `os.stat` no emite evento de auditoría; revela existencia y tamaño de
  rutas ajenas, no su contenido.
- **Cloud.** Cloud deduce la empresa del token y su manifiesto no la declara.
  `verificar_custodia_cloud` se debe llamar antes de alinear: lee la marca
  custodiada y rechaza un token de otra empresa. MBT se reconoce por no tener marca.

## Alta y recuperación

Alta: `inicializar_empresa` y, en el primer turno, `custodia.sembrar(lease)`, que
sube la marca (está en `catalogos_privados`).

Equipo nuevo: `abrir_empresa(..., restauracion=True)`, `verificar_custodia_cloud`,
adquirir el lease (alinea y restaura) y `confirmar_restauracion`.

## Integración pendiente

Ninguno de estos puntos está hecho:

1. **Puntos de entrada del Motor** (`sincronizar_mobile_cloud.py`,
   `desktop_operacion`, CLIs): `contexto_desde_entorno`, `activar_guarda` y
   `verificar_custodia_cloud` antes de `alinear`.
2. **`CustodiaEstado`**: los creadores deben pasar
   `carpeta_local=contexto.carpeta_custodia()`; hoy usan la ruta global.
3. **Estado local aún global**: `escritor_operativo_id.txt`, relevo
   (`escritor_operativo.ruta_relevo_confirmado`), `desktop_operacion.json`,
   `pull_autorizacion.json`, logs `pull_ciclos`, `registro_ciclo_pull`.
4. **Registro de relaciones**: los llamadores usan la empresa por defecto
   `oficina`. Dentro de cada raíz no mezcla datos, pero para otra empresa deben
   pasar `empresa_id=contexto.registro_id`, o `relaciones_si_activo` no lo verá activo.
5. **Cloud (Worker)**: `CLOUD_MOTOR_EMPRESA_ID` es uno solo por despliegue; hace
   falta un token y `empresa_id` por empresa. D1 y R2 ya separan por `empresa_id`.
6. **Tareas PULL**: una por empresa, cada una con `ContextoEmpresa.entorno()`.
7. **Mobile**: el token ya lleva `empresa_id`; falta enrutar cada lease a su raíz.
8. **Desktop y B1**: abrir con el entorno de la empresa elegida. B1 hereda la
   raíz del proceso.
9. **OCR y modelos**: runtimes compartidos y sin datos de empresa; sin cambios.
