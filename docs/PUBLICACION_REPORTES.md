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
- `rotativo` (antes del diario, `f90a922`): única ruta rastreada adicional,
  `catalogos_privados/registro_relaciones_operacionales.json`, subida
  completa (~700 bytes por relación) en cada turno con un cambio: ~22-37
  MB/día al primer mes y ~270-445 MB/día al año. Bloqueaba el modo
  rotativo porque R2 conserva cada versión completa.
- `rotativo` con diario incremental: la captura escribe sólo el segmento
  del día `catalogos_privados/registro_relaciones_diario/<AAAAMMDD>.json`;
  el registro base no cambia. Medido con `CustodiaEstado` real (audit
  hook, R2 simulado por huella) sobre un registro migrado de 2.000
  relaciones (1,4 MB) y 15 turnos en 3 días con una relación nueva por
  turno: **monolítico 15 subidas / 21,1 MB; diario 15 subidas / 18,6 KB**
  (`tests/test_registro_relaciones_diario_p0.py`). Lo subido por turno ya no
  depende del tamaño del registro sino de lo nuevo del día; cada
  consolidación (mensual) sube el base completo una vez. Ningún `reportes/`
  entra en la custodia.

Volumen real medido (solo lectura de `G:`, 06/11/2026): 1.597 snapshots,
5,58 GiB; últimos 15 días 361 reportes (~24/día, ~190 MB/día). De esos, 339
(94 %) son de productores automáticos que el modo rotativo redirige; el
resto son `reporte_desktop_*` del drop de Desktop (`main.js`, protegido) y
reportes manuales.

## Activación (no ejecutada)

0. Con el diario, la custodia ya no sube el registro completo por turno.
   Antes de activar: desplegar el mismo código en CASA y OFICINA (una
   versión sin diario no vería los segmentos) y confirmar con Cloud/Codex
   que el crecimiento de R2 por segmento (KB/día) es aceptable.
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
