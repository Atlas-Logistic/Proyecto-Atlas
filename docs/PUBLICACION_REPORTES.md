# Publicación del reporte vigente

Hasta ahora, cada ingreso Mobile, revalidación, acción operacional,
mantenimiento o reconciliación publicaba un `reportes/<carpeta>/viajes.csv`
completo (~7,4 MB) que nunca se borraba: 30-40 por día. Para operar sólo hace
falta el último: Desktop, la exportación MBT, las consultas y Mobile lo leen
mediante `operacion/actual/estado_operacion.json -> reporte_vigente`. Los
anteriores son, además, la única fuente del lector histórico de relaciones
mientras el registro incremental no esté migrado y activado.

## Productores y consumidores

| Productor automático | Carpeta |
|---|---|
| `revalidar_y_regenerar_reporte` (Mobile, decisiones, convergencia, reparador, plan de impacto) | `reporte_mobile_*`, `reporte_revalidacion_*`, ... |
| `acciones_operacionales._regenerar_reporte` | `accion_operacional_*` |
| `mantenimiento_pendientes_tecnicos` | `mantenimiento_tecnico_*` |
| `reconciliacion_estado_derivado` | `reporte_desktop_reconciliado_v*` |
| `aplicacion_decisiones` (destino, convergencia) | `reporte_revalidacion_*` |
| `desktop_operacion` (ingreso Desktop vía Motor) | `reporte_desktop_*` |

Todos pasan por `publicacion_reportes.ruta_reporte_automatico`. Fuera de ese
alcance: `generar_reporte_viajes.py` escribe exactamente donde se le indique, y
el drop de Desktop en `main.js` (archivo protegido) le indica
`reportes/reporte_desktop_<marca>`.

Consumidores del reporte vigente (todos vía `estado_operacion`): Desktop (vista,
firma de cambios, MBT Excel/PDF), consultas, B1, eventos operacionales y Mobile.
El único que recorre `reportes/*/viajes.csv` es el lector histórico de
relaciones (y la migración del registro). La custodia Cloud
(`estado_confirmado`) excluye todo `reportes/`.

## Modos

`reportes/vigentes/publicacion.json` (ausente o inválido = `snapshots`):

- `snapshots`: comportamiento anterior, sin ningún cambio.
- `rotativo`: los productores automáticos publican en
  `reportes/vigentes/<misma carpeta>/`. Desktop no cambia (cada publicación
  sigue teniendo una ruta nueva). Tras publicar, la evidencia de ese
  `viajes.csv` (`evidencias_documentos`, lo mismo que leería el lector
  histórico) se captura en el registro de relaciones con una sola fuente por
  relación, y el consumidor la suma a la de los reportes históricos. Se
  conservan las `conservar` publicaciones más recientes (por defecto 3) y la
  vigente; las demás se borran sólo si su evidencia quedó capturada o
  preservada. Si la captura falla, el reporte se copia como snapshot
  permanente bajo `reportes/`. Si el registro deja de ser legible, los
  productores vuelven solos a `snapshots`.

Snapshot permanente bajo demanda: `python publicacion_reportes.py --raiz <Atlas> --snapshot`.

## Interacción con la custodia Cloud de PULL

Medido con el audit hook real de `estado_confirmado` sobre el mismo escenario
(decisión + 4 ingresos Mobile + 2 revalidaciones):

- `snapshots` (por defecto): las rutas rastreadas son **idénticas** a las de
  CASA `8069ea6` (19 rutas); no se crea el registro. Desplegar en este modo
  no cambia lo que la custodia sube.
- `rotativo`: única ruta rastreada adicional,
  `catalogos_privados/registro_relaciones_operacionales.json`; ningún
  `reportes/` entra en la custodia. Cada cambio del registro se sube completo
  (~700 bytes por relación): ~22-37 MB/día al primer mes y ~270-445 MB/día al
  año con 30-50 relaciones nuevas diarias y ~35 publicaciones. La retención
  de versiones antiguas en R2 depende del Worker, que no está en este
  repositorio: **no está demostrado que sea segura**. El modo rotativo queda
  bloqueado hasta que Cloud confirme retención/limpieza o se decida otra
  ubicación del registro.

## Activación (no ejecutada; bloqueada por la custodia)

0. Resolver la sección anterior (decisión Cloud/Codex).
1. Desplegar el código (rama sobre el registro incremental), integrado con lo
   instalado y con el trabajo de PULL vigente.
2. Comprobar `python migrar_relaciones_operacionales.py --raiz <Atlas> --estado`
   (`legible: true`).
3. `python publicacion_reportes.py --raiz <Atlas> --rotativo --conservar 3`.
4. Verificar `--estado` (`modo_efectivo: rotativo`) y, tras el siguiente
   ingreso Mobile, que `reporte_vigente` empiece por `reportes/vigentes/` y que
   Desktop y MBT carguen normalmente.

Reversión: `python publicacion_reportes.py --raiz <Atlas> --snapshots`. La
evidencia capturada mientras duró el modo rotativo sigue sumándose al lector
histórico. Nada de lo anterior borra ni modifica reportes históricos.
