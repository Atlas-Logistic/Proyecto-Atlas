# Integración de destinos en modo revisión

## Propósito

El modo revisión conecta una fuente explícita de destinos con el motor
inteligente y produce una bandeja para decisión humana. Es un flujo de lectura:
nunca modifica el archivo de entrada, no persiste coordenadas y no escribe en
catálogos.

Una propuesta del motor no es una decisión. Las decisiones humanas futuras
(`CONFIRMAR_PROPUESTA`, `RECHAZAR_PROPUESTA`, `CORREGIR_MANUALMENTE`,
`POSPONER` y `MARCAR_NO_RECONOCIDO`) tienen un contrato separado y todavía no
producen escrituras.

## Entradas

Se admite una ruta explícita a JSON o CSV UTF-8, con o sin BOM. No existen rutas
personales ni nombres predeterminados de catálogo.

Campos mínimos:

- `destino_id`
- `cliente_id` opcional
- `direccion`
- `comuna`
- `region`
- `pais`
- `latitud` y `longitud` opcionales, siempre juntas
- `estado_actual`
- `autorizacion_consulta_externa`
- `campos_autorizados`

El registro original completo se conserva internamente para calcular su huella.
Los campos adicionales no se infieren ni se eliminan de esa huella.

## Salidas

La ruta separada de salida contiene:

- `revisiones_destinos.csv`, UTF-8 con BOM y separador `;`;
- `revisiones_destinos.json`;
- `resumen_revision_destinos.json`;
- `manifiesto_ejecucion.json`.

Los valores originales y externos permanecen en columnas distintas. Ninguna
acción posible se llama `ACEPTAR_AUTOMATICAMENTE`.

## Ejecución segura

El comportamiento predeterminado no permite red y fija el máximo en cero:

```powershell
python revision_destinos.py `
  --entrada C:\ruta\explicita\destinos.json `
  --salida C:\ruta\separada\bandeja
```

Para reprocesar respuestas congeladas, todavía sin red:

```powershell
python revision_destinos.py `
  --entrada C:\ruta\copia_temporal.json `
  --salida C:\ruta\salida_temporal `
  --permitir-consultas `
  --max-consultas 0 `
  --solo-cache `
  --proveedor respuestas-congeladas `
  --respuestas-congeladas C:\ruta\respuestas_ors_congeladas.json
```

Parámetros:

- `--entrada`
- `--salida`
- `--permitir-consultas`
- `--max-consultas`
- `--usar-cache` / `--no-usar-cache`
- `--solo-cache`
- `--timeout`
- `--proveedor`
- `--respuestas-congeladas`
- `--fecha-evaluacion`, opcional para reproducción determinista

La mera presencia de `OPENROUTESERVICE_API_KEY` no activa consultas.

## Estados

La bandeja distingue sin cambios, confirmación o coordenadas propuestas,
coincidencia parcial, contradicciones de dirección/número/comuna/región,
respuesta ambigua, ausencia de resultados, consulta no autorizada, error del
proveedor y revisión general.

Toda propuesta y toda coordenada nueva requieren decisión humana.

## Seguridad y modo sin internet

- SHA-256 del origen antes y después.
- Lectura sin archivos temporales junto a la fuente.
- Salida en otra ruta.
- Fallos aislados por registro.
- Credenciales y datos sensibles excluidos.
- Caché congelado reproducible.
- Orden estable por `destino_id`.
- Sin conexión con Desktop, viajes o raíz única.

Si falta credencial, autorización, proveedor o cuota, los originales se
conservan y el lote continúa.

## Limitaciones

- No existe interfaz gráfica.
- No se escriben decisiones humanas.
- El caché productivo persistente todavía no está implementado.
- Los resultados ambiguos no seleccionan automáticamente un candidato.
- El modo revisión no reemplaza el Ground Truth ni autoriza cambios masivos.
