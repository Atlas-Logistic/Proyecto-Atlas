# Contrato: estado de operación vigente portable

Bloque: INFRAESTRUCTURA S2.2. Documento versionado en **ambos** repos
(motor: `docs/CONTRATO_ESTADO_OPERACION_PORTABLE.md`; Desktop:
`documentacion/CONTRATO_ESTADO_OPERACION_PORTABLE.md`) — una sola regla,
nunca dos implementaciones que puedan divergir.

## Objetivo

Que cualquier PC con la raíz de Atlas sincronizada por Drive (motor o
Desktop, casa u oficina) pueda descubrir cuál es el reporte/dataset
operacional vigente **sin adivinar** ("la carpeta con timestamp más
reciente" puede seleccionar un reporte incompleto o promover por
accidente algo de `historico_pre_infra_s2\`).

## Ubicación

```
<ATLAS_DATA_DIR>/operacion/actual/estado_operacion.json
```

Un único archivo, pequeño, con escritura atómica (temp-file + rename).
Ausencia del archivo es un **caso válido**: significa que todavía no hay
una operación vigente publicada (por ejemplo, recién migrada la
infraestructura y aún no se importó/generó nada) — nunca se trata como
error.

## Esquema (schema_version 1)

```json
{
  "schema_version": 1,
  "reporte_vigente": "reportes/actual",
  "dataset_operacional": "operacion/procesamiento/analisis_completo_guias.csv",
  "fecha_actualizacion": "2026-08-13T15:00:00+00:00",
  "origen": "oficina"
}
```

- `schema_version` (entero, obligatorio): consumidores que no reconocen
  el valor deben abstenerse (nunca intentar interpretar un esquema que
  no entienden).
- `reporte_vigente` (string, obligatorio): ruta **relativa** a
  `ATLAS_DATA_DIR`, con `/` como separador (`Path.as_posix()` del lado
  Python). Apunta a la carpeta del reporte vigente (la que contiene
  `viajes.csv`, `documentos_sin_transporte.csv`, etc.).
- `dataset_operacional` (string u `null`, opcional): ruta relativa al
  CSV masivo (`analisis_completo_guias.csv`) que originó ese reporte.
- `fecha_actualizacion` (string ISO-8601 con zona horaria, informativo).
- `origen` (string u `null`, informativo): de qué PC/proceso vino la
  última publicación (p. ej. `"oficina"`, `"casa"`) — solo para
  trazabilidad humana, ningún consumidor debe tomar decisiones distintas
  según este valor.

**Cualquier ruta relativa que resuelva fuera de `ATLAS_DATA_DIR` invalida
todo el manifiesto** (nunca se acepta silenciosamente un manifiesto que
apunte fuera de la raíz portable, sea por corrupción o manipulación).

## Quién escribe

El motor Python, al terminar de generar un reporte
(`generar_reporte_viajes.py`), publica/actualiza este manifiesto de
forma *best-effort*: si `--salida`/el CSV de entrada no viven dentro de
`ATLAS_DATA_DIR` (uso local/de desarrollo), simplemente no publica nada
— el reporte se genera exactamente igual que siempre. Implementación:
`atlas_core.almacenamiento_portable.escribir_estado_operacion`.

## Quién lee

Atlas Desktop, al arrancar / al "cargar automático"
(`atlas:cargar-automatico`), prefiere este manifiesto sobre cualquier
valor guardado localmente (`carpetaReportes` en `config_usuario`).
Implementación: `src/estado_operacion.js` →
`leerEstadoOperacion(raizAtlas)`.

## Reglas para cualquier consumidor futuro

1. Nunca reemplazar la lectura del manifiesto por un `glob`/"carpeta más
   reciente por timestamp".
2. Nunca promover automáticamente contenido de
   `historico_pre_infra_s2/` a operación vigente.
3. Un manifiesto ausente, corrupto, con `schema_version` no soportada, o
   con una ruta fuera de la raíz portable, siempre se traduce en un
   estado humano y claro ("no hay una operación activa disponible"),
   nunca en una excepción sin capturar ni una pantalla rota.
