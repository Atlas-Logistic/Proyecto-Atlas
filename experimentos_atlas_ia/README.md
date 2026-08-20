# Experimentos Atlas IA

Área de evaluación/experimentos de Atlas IA -- **deliberadamente fuera de
`operacion/actual`**. Nada de lo que se ejecuta aquí modifica Drive, el
ledger, los catálogos ni `viajes.csv`. Todas las llamadas a un proveedor
real de IA se hacen en **shadow mode**: se registra el resultado, nunca
se aplica.

## `lote_vehiculos_a2.py` (Bloque A2)

Runner de experimento para el vertical vehículos/patentes. Construye
`ContextoRazonamiento` reales -- evidencia real, vía el Motor
determinista ya en producción (`evaluar_evidencia_patente`) -- para un
lote curado de casos históricos reales (ver `CASOS_REALES_VEHICULOS` en
el propio archivo), llama a un `ProveedorModeloIA` real en shadow, valida
cada hipótesis con `atlas_core.atlas_ia.validadores` y persiste el
resultado.

Ejecutar (requiere `ANTHROPIC_API_KEY` configurada como variable de
entorno -- ver más abajo):

```
python experimentos_atlas_ia/lote_vehiculos_a2.py
```

Sin la credencial, el script se detiene de forma limpia con un mensaje
explicando exactamente qué configurar -- nunca falla con una traza
confusa ni intenta adivinar una credencial.

## Formato del artefacto (`resultados/*.json`)

Un array JSON de objetos `ResultadoShadow.a_dict()`
(`atlas_core.atlas_ia.contratos.ResultadoShadow`), cada uno con:

- `caso_id`, `contexto` (campo, valor documental, RUT, guía, transporte,
  evidencia completa considerada, resultado/explicación del Motor
  determinista),
- `hipotesis` (`hipotesis_id`, resultado, valor propuesto, evidencia
  usada/en contra, explicación, proveedor, modelo, metadata -- incluye
  `usage`/tokens si el proveedor los entrega),
- `validacion` (aceptada/motivo de rechazo de los validadores A1),
- `resultado_motor` (duplicado directo, para comparar sin abrir
  `contexto`),
- `ground_truth_humano` (si se conoce -- nunca se le entrega al modelo,
  sólo se usa para comparar después de que responda).

Los resultados de cada corrida real (`resultados/*.json`, salvo
`.gitkeep`) están excluidos de git (`.gitignore`) porque contienen
evidencia real de guías (RUT, patentes, nombres de chofer) -- el runner y
el formato sí se versionan.

## Credencial

`ANTHROPIC_API_KEY` se configura como variable de entorno de **usuario**
de Windows, en la propia terminal de quien la configura -- nunca pegada
en un chat, nunca escrita en el repo ni en Drive. Mismo mecanismo ya
usado para `OPENROUTESERVICE_API_KEY`/`ATLAS_ONELOGIS_API_KEY` (ver
`docs/BITACORA_TECNICA_CRONOLOGICA.md`):

```powershell
[Environment]::SetEnvironmentVariable("ANTHROPIC_API_KEY", "<la clave>", "User")
```

Después de configurarla, abrir una terminal nueva (una variable de
usuario recién creada no se propaga a procesos ya en ejecución).
