# Registro de relaciones operacionales

`catalogos_privados/registro_relaciones_operacionales.json` es el registro
portable, atómico e incremental de las relaciones
guía--transporte--chofer--patente. Está dentro de la raíz Atlas, por lo que la
sincronización de Drive lo respalda; no sustituye las fuentes existentes.

El contrato por relación es `numero_guia`, `numero_transporte`, `rut_chofer`,
`patente_tracto` y `patente_rampla`. Cada entrada conserva `fuentes`,
`conflictos` y `confirmaciones_humanas` por separado. Ni la migración ni el
ciclo normal inventan confirmaciones, eligen entre relaciones discrepantes ni
borran fuentes o conflictos.

La separación por empresa está bajo `empresas.<empresa_id>`; el valor por
defecto es `oficina` para compatibilidad, sin implementar multiempresa. La
migración, su verificación y su activación son por empresa.

## Garantías

- **Procedencias estables.** Una fuente se identifica sin `observado_en`,
  `sha256` ni `ruta`: otra regeneración con el mismo dataset (aunque cambie su
  huella) no modifica una relación ya registrada, y la migración guarda una
  sola fuente migrada por relación aunque aparezca en cientos de snapshots
  (el detalle por reporte queda en `migracion.reportes`). Sin relación ni
  fuente nueva no se escribe nada.
- **Sin escrituras antes de migrar.** La regeneración sólo incorpora el
  dataset una vez que la migración de la empresa está `completa` o
  `verificada`; antes informa `registro_relaciones.omitido =
  MIGRACION_NO_COMPLETA` y no crea ni toca el archivo.
- **Diario incremental.** El ciclo normal (dataset tras la migración y
  captura de reportes publicados en modo rotativo) nunca reescribe el
  registro base: agrega sólo la unión nueva al segmento del día
  `catalogos_privados/registro_relaciones_diario/<AAAAMMDD>.json`
  (escritura atómica). El registro vigente es siempre *base + segmentos
  reproducidos en orden de nombre con la misma unión idempotente*; todos
  los lectores (consumidor, estado, verificación, migración) usan esa
  vista. Reproducir un segmento ya incorporado no cambia nada, por eso un
  corte a mitad de la consolidación o una copia en conflicto de Drive
  (`20261106 (1).json`) se reproducen sin duplicar ni perder. Un segmento
  ilegible o de versión desconocida vuelve ilegible el registro completo
  (mismo tratamiento que el base: el consumidor vuelve a los históricos y
  nada se sobrescribe ni se borra). Los segmentos están en una subcarpeta:
  no cambian la firma de catálogos de la batería compartida (igual que en
  modo snapshots).
- **Consolidación controlada.** `--consolidar` (con el escritor de PULL)
  incorpora al base los segmentos de días anteriores a `--hasta` (por
  defecto hoy UTC, el segmento en uso no se toca) y recién después los
  borra; nunca borra uno que cambió tras leerlo. Cada consolidación sube el
  base completo una vez: hacerla mensual o cuando `--estado` muestre más de
  ~30 segmentos.
- **Custodia Cloud.** `catalogos_privados/` está custodiado por PULL: al
  cerrar el turno se sube cada archivo cambiado (R2 direccionado por
  huella), y una escritura fuera de turno se revierte en la siguiente
  alineación. Con el diario, un turno normal sube sólo el segmento del día
  (KB), no el registro completo; el otro equipo recupera los segmentos
  confirmados en su alineación aunque Drive esté atrasado. Por eso
  `migrar_relaciones_operacionales.py` ejecuta `--aplicar`, `--verificar`,
  `--activar` y `--desactivar` con el mismo escritor que PULL y Desktop
  (lease Cloud o equipo único); sin escritor disponible responde código 2 sin
  escribir. `--sin-escritor` es sólo para raíces de prueba.
- **Integridad.** Un registro ausente equivale a vacío. Uno ilegible, de
  versión desconocida o estructuralmente inválido lanza `REGISTRO_ILEGIBLE` /
  `REGISTRO_INCOMPATIBLE`, nunca se sobrescribe, y el consumidor vuelve al
  lector histórico. La regeneración informa
  `registro_relaciones.bloqueado = <código>` sin interrumpirse.
- **Activación controlada.** Hasta que la migración de la empresa esté
  `verificada` **y** `activo`, el consumidor sigue usando
  `_leer_relaciones_historicas_reportadas` (con su cache local). Desactivar
  vuelve a ese lector de inmediato.
- **Migración reanudable e idempotente.** Confirma cada lote de reportes junto
  con su avance (`migracion.reportes`) en una única escritura atómica. Un corte
  pierde, como máximo, el lote en curso; al reanudar, los reportes ya migrados
  con el mismo tamaño no se vuelven a leer. Repetirla no agrega ni reescribe
  nada. Los reportes ilegibles nunca se marcan como migrados y dejan la
  migración `en_curso`.
- **Concurrencia.** Un cerrojo local del sistema operativo (en
  `%LOCALAPPDATA%\Atlas\cache\registro_relaciones`, nunca en Drive, liberado
  por el SO si el proceso muere) impide dos migraciones simultáneas en el
  mismo equipo. Cada escritura toma otro cerrojo breve y relee el archivo
  bajo cerrojo, así que una regeneración durante la migración no se pierde.
  **Entre equipos no hay cerrojo**: ver el procedimiento.
- **Lecturas.** El consumidor no abre reportes; el registro parseado se
  conserva en memoria mientras su `mtime`/tamaño no cambie. Cada reporte se
  lee una sola vez por pasada (huella y relaciones de la misma lectura).

## Procedimiento de migración real (no ejecutado)

Requisitos previos: código desplegado en el equipo que hará la migración; ese
equipo es el **único escritor** (hoy CASA; OFICINA apagada); PULL recuperado
y estable; respaldo verificable de `catalogos_privados/`. **No hace falta
detener PULL**: la migración y la verificación leen los reportes sin tomar
el escritor y lo toman sólo para una escritura atómica de segundos (PULL, si
coincide, responde `ESCRITOR_OCUPADO` en ese ciclo y sigue en el próximo).

1. Estado y simulación, sin escritura (≈3 min en CASA, 06/11: 1.607
   reportes, 836 relaciones, 0 ilegibles):

   ```powershell
   python migrar_relaciones_operacionales.py --raiz <Atlas> --estado
   python migrar_relaciones_operacionales.py --raiz <Atlas> > simulacion.json
   ```

   Revisar `reportes`, `relaciones_extraidas`, `ilegibles` y
   `registro.legible`. Para comparar con otra auditoría, usar `fuentes[].ruta`
   (relativa, separador `/`) y `sha256`, nunca rutas locales absolutas.

2. Aplicar (dos fases en un comando; reanudable):

   ```powershell
   python migrar_relaciones_operacionales.py --raiz <Atlas> --aplicar --lote 50
   ```

   Fase 1 **sin escritor**: lee los reportes aún no migrados y guarda el
   avance cada `--lote` en un plan local
   (`%LOCALAPPDATA%\Atlas\cache\registro_relaciones\*.plan_migracion.json`,
   nunca en Drive ni en la custodia). Fase 2 **con escritor**: una sola
   escritura atómica del registro base (no abre reportes) y borra el plan.
   Si el escritor está ocupado sale con código 2 y conserva el plan:
   repetir el comando no relee lo ya leído. Repetir hasta que `estado` sea
   `completa` e `ilegibles` esté vacío. Los reportes que aparecen durante
   la lectura no son exigidos: llegan por el dataset y la verificación los
   admite como `no_migrados`.

3. Verificar (lectura sin escritor; marca con escritor):

   ```powershell
   python migrar_relaciones_operacionales.py --raiz <Atlas> --verificar
   ```

   Relee todos los reportes sin escritor; si todo calza, toma el escritor y
   vuelve a exigir, sobre el registro ya alineado con Cloud, estado
   `completa` y todas las relaciones leídas antes de marcar `verificada`.
   Exige `ok = true`, `relaciones_ausentes = 0` e `ilegibles = []`. Código
   de salida 1 = no verificada. `no_migrados` lista reportes posteriores cuyas
   relaciones ya llegaron por el dataset; `cambiados`, reportes cuya huella
   cambió (deberían ser inmutables: investigar antes de activar).

4. Activar sólo tras conservar los JSON de los pasos 1–3:

   ```powershell
   python migrar_relaciones_operacionales.py --raiz <Atlas> --activar
   ```

   Reversión: `--desactivar` (el consumidor vuelve a los históricos al
   instante). **La reversión sólo es completa donde existen los reportes
   históricos** (Drive de CASA/OFICINA): un equipo reinstalado sin
   `reportes/` obtiene todo del registro mientras está activo, y nada del
   lector histórico tras desactivar. Por eso los reportes históricos no se
   borran, mueven ni depuran mientras la reversión deba ser posible.

Validación aislada (Worker real `b39e3bd` con D1 SQLite y R2 en memoria,
lease, custodia y CLI reales; `C:/Atlas/pruebas/cierre-diario-20261106`):
con el flujo anterior los 3 ciclos de PULL durante la lectura recibieron
`ESCRITOR_OCUPADO`; con dos fases los 3 adquirieron y el escritor se tomó
0,13 s. Un equipo reinstalado sin `reportes/` recuperó las 2.408 relaciones
(2.401 históricas + dataset + diario) idénticas a CASA, con migración
`verificada` y `activo`; la consolidación propagó el borrado de los
segmentos y las relaciones no cambiaron.

Una vez completa la migración, la regeneración normal incorpora relaciones
desde el dataset operacional ya validado, sin tocar reportes históricos;
antes de eso no escribe el registro.
