# Registro de relaciones operacionales

`catalogos_privados/registro_relaciones_operacionales.json` es el registro
portable, atómico e incremental de las relaciones
guía--transporte--chofer--patente. Está dentro de la raíz Atlas, por lo que la
sincronización de Drive lo respalda; no sustituye las fuentes existentes.

El contrato por relación es `numero_guia`, `numero_transporte`, `rut_chofer`,
`patente_tracto` y `patente_rampla`. Cada entrada conserva fuentes, conflictos
y `confirmaciones_humanas` separado. La migración no inventa confirmaciones ni
selecciona relaciones discrepantes.

La separación por empresa está bajo `empresas.<empresa_id>`; el valor actual
por defecto es `oficina` para compatibilidad, sin implementar multiempresa.

## Migración y activación

Primero ejecutar, sobre una copia o raíz autorizada:

```powershell
python migrar_relaciones_operacionales.py --raiz <Atlas>
```

El resultado de simulación informa reportes, relaciones únicas e ilegibles. La
aplicación sólo procede si no hay reportes ilegibles:

```powershell
python migrar_relaciones_operacionales.py --raiz <Atlas> --aplicar
```

Luego se compara `relaciones_extraidas` con `relaciones_registradas`, se
repite `--aplicar` (debe agregar cero) y se conserva el informe. Sólo entonces
se autoriza activar el consumidor en esa raíz. Durante una reconciliación
normal, el Motor consulta exclusivamente este registro; no existe fallback a
`reportes/*/viajes.csv`. Cada regeneración exitosa incorpora relaciones desde
el dataset operacional ya validado, sin tocar reportes históricos.
