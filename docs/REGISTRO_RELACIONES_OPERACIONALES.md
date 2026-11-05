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

- **Procedencias estables.** Una fuente se identifica sin `observado_en` ni
  `sha256`: otra regeneración con el mismo dataset (aunque cambie su huella)
  no modifica una relación ya registrada. Sin relación ni fuente nueva no se
  escribe nada.
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
equipo es el **único escritor** (PULL/mantenimiento del otro equipo
detenidos o sin escribir la raíz durante la ventana); PULL recuperado y
estable; respaldo verificable de `catalogos_privados/`.

1. Estado y simulación, sin escritura:

   ```powershell
   python migrar_relaciones_operacionales.py --raiz <Atlas> --estado
   python migrar_relaciones_operacionales.py --raiz <Atlas> > simulacion.json
   ```

   Revisar `reportes`, `relaciones_extraidas`, `ilegibles` y
   `registro.legible`. Para comparar con otra auditoría, usar `fuentes[].ruta`
   (relativa, separador `/`) y `sha256`, nunca rutas locales absolutas.

2. Aplicar por lotes (reanudable; si se corta, repetir el mismo comando):

   ```powershell
   python migrar_relaciones_operacionales.py --raiz <Atlas> --aplicar --lote 50
   ```

   Repetir hasta que `estado` sea `completa`, `ilegibles` esté vacío y una
   nueva ejecución informe `procesados = 0`. Código de salida 2 =
   bloqueado (registro ilegible/incompatible u otra migración en curso).

3. Verificar (sólo lectura de reportes; marca `verificada` si todo calza):

   ```powershell
   python migrar_relaciones_operacionales.py --raiz <Atlas> --verificar
   ```

   Exige `ok = true`, `relaciones_ausentes = 0` e `ilegibles = []`. Código
   de salida 1 = no verificada. `no_migrados` lista reportes posteriores cuyas
   relaciones ya llegaron por el dataset; `cambiados`, reportes cuya huella
   cambió (deberían ser inmutables: investigar antes de activar).

4. Activar sólo tras conservar los JSON de los pasos 1–3:

   ```powershell
   python migrar_relaciones_operacionales.py --raiz <Atlas> --activar
   ```

   Reversión: `--desactivar` (el consumidor vuelve a los históricos al
   instante). Los reportes históricos no se borran, mueven ni depuran.

Durante la regeneración normal, el Motor incorpora relaciones desde el
dataset operacional ya validado, sin tocar reportes históricos, esté o no
activado el registro.
