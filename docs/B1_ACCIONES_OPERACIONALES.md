# Capa canónica de acciones operacionales (B1 / operador)

Módulo: `atlas_core/acciones_operacionales.py` · CLI: `acciones_operacionales_cli.py`
Pruebas: `tests/test_acciones_operacionales.py` (sólo fixtures sintéticas).

B1 nunca edita CSV/JSON/catálogos. Pide una **acción tipada**, recibe un
**preview**, y sólo una confirmación que cite el **token** de ese preview la ejecuta.

```
acción tipada → preview(token) → confirmación → ejecutar → reconciliar
→ revalidar afectados → auditar → resultado
```

Esta capa no interpreta lenguaje natural: la traducción orden → acción tipada es
responsabilidad del llamador (B1), en un bloque posterior.

## API

```python
capa = CapaAccionesOperacionales(raiz_atlas)
capa.previsualizar(accion, parametros, actor="B1", origen="B1", referencia="...")
capa.ejecutar(token, actor="B1", origen="B1", confirmado_por="JAVIER")
capa.auditoria()
catalogo_acciones()        # contrato serializable: acciones, riesgo, parámetros
```

- `origen`: `HUMANO` | `B1` | `SISTEMA`.
- Los parámetros son un objeto con un esquema estricto por acción: un parámetro
  desconocido → `PARAMETRO_NO_PERMITIDO`; tipos/formatos inválidos → `PARAMETRO_INVALIDO`.
  No se aceptan rutas, comandos ni SQL; la raíz se fija al construir la capa.
- El ejecutor usa **sólo** los parámetros guardados con el preview.

## Acciones y riesgo

| Acción | Riesgo | Servicio canónico reutilizado |
|---|---|---|
| `CHOFER_CONSULTAR`, `OBRA_CONSULTAR`, `DECISION_CONSULTAR` | LECTURA | lectura de catálogos/bandeja |
| `CHOFER_CAMBIAR_ESTADO` | OPERACIONAL_REVERSIBLE | `catalogos.cambiar_estado_chofer` |
| `CHOFER_AGREGAR_ALIAS` | OPERACIONAL_REVERSIBLE | `catalogos.registrar_alias_seguro` |
| `CHOFER_ASIGNAR_VEHICULO` | OPERACIONAL_REVERSIBLE | `asociar_chofer_a_vehiculo_confirmado` + retiro focal de `operaciones_conversacionales` |
| `OBRA_REGISTRAR` | OPERACIONAL_REVERSIBLE | `CatalogoObrasDestinos.registrar_observacion` |
| `OBRA_CORREGIR` | OPERACIONAL_REVERSIBLE | `CatalogoObrasDestinos.actualizar_identidad_obra` |
| `DESTINO_REGISTRAR` | OPERACIONAL_REVERSIBLE | `CatalogoDestinos.crear_o_reutilizar_global` |
| `OBRA_VINCULAR_DESTINO` | OPERACIONAL_REVERSIBLE | `registrar_observacion` + `confirmar_relacion` |
| `DOCUMENTO_CORREGIR_CAMPO` | OPERACIONAL_REVERSIBLE | `reparar_documento_focal_con_valores_conocidos` |
| `DECISION_APLICAR` | OPERACIONAL_REVERSIBLE | `aplicar_decision_obra` |
| `TRANSPORTE_REVALIDAR` | SENSIBLE | `revalidar_documentos_por_transporte` |
| `ENTIDAD_ELIMINAR`, `EVIDENCIA_ELIMINAR`, `HISTORIAL_ELIMINAR` | DESTRUCTIVA | siempre rechazadas |

Autonomía: LECTURA → automática; OPERACIONAL_REVERSIBLE → exige `confirmado_por`
(humano); SENSIBLE → sólo `origen=HUMANO` + `autorizacion_sensible=True`;
DESTRUCTIVA → `ACCION_PROHIBIDA`.

## Preview

`estado` (`PREVIEW` | `SIN_CAMBIOS` | `RESULTADO` | `RECHAZADA`), `token`, `accion`,
`riesgo`, `autonomia_b1`, `entidad`, `valor_actual`, `valor_propuesto`, `afectados`,
`consecuencias`, `revalidaciones`, `requiere_confirmacion`, `huella_base`,
`idempotency_key`, `expira_en` (30 min). Un preview `SIN_CAMBIOS` no tiene token.

## Ejecución

1. Bloqueo `acciones_operacionales` (más los bloqueos propios de cada servicio).
2. Se vuelve a planificar y se compara la huella del estado base **de la entidad
   afectada**; si cambió → `PREVIEW_OBSOLETO` con `preview_nuevo` (nada se escribe).
   Cambios ajenos a la entidad no invalidan el preview.
3. Respaldo focal en `respaldos/acciones_operacionales/<fecha>_<token>/`;
   ante cualquier fallo del servicio se restaura y se audita `FALLIDA`.
4. Escritura por el servicio canónico.
5. Reconciliación: `reconciliar_bandeja_decisiones` (sin OCR). Para
   correcciones documentales, además, retiro de tarjetas que sigan preguntando
   por el valor anterior del campo.
6. Revalidación sólo de lo afectado (revalidación reactiva de catálogo, retiro
   focal de vehículo, mantenimiento focal de la guía, reporte de viajes derivado).
7. Auditoría append-only en `operacion/actual/acciones_operacionales.json`:
   actor, origen, confirmado_por, acción, parámetros, antes, después, referencia,
   timestamp, resultado, respaldo.

Idempotencia: reejecutar un token ya ejecutado devuelve el resultado guardado sin
escribir; pedir de nuevo una acción ya aplicada devuelve `SIN_CAMBIOS`.

Una corrección documental queda protegida en `decisiones_aplicadas.json` con tipo
`CORRECCION_DOCUMENTAL_OPERADOR`: el replay OCR/reparador la respeta, y sólo otra
corrección del operador puede reemplazarla (una decisión de Revisión siempre gana).
