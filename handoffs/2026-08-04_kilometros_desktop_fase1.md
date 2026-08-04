# Handoff — Kilómetros visibles en Atlas Desktop, Fase 1

Fecha: 2026-08-04
Estado: COMPLETADO

## Funcionamiento entregado

Atlas Desktop calcula automáticamente una ruta al cargar el reporte oficial si
el viaje posee un origen y un destino únicos que coinciden con Plantas y
Destinos activos, confirmados, con dirección completa y coordenadas canónicas.
El cálculo reutiliza `CalculadorRutas` y `OpenRouteService`; no existe un
segundo proveedor ni lógica logística en el Sistema Multicampo.

El panel muestra distancia, tiempo estimado, proveedor, estado y motivo. Los
faltantes quedan `Pendiente`; los fallos externos quedan `No disponible`.

## Validación

- OpenRouteService real, extremos canónicos confirmados AZA RENCA → LAS
  VIOLETAS 55: 33,2 km y 40 min.
- Python focal: 63/63; regresión: 1144/1144.
- Desktop: 36/36, prueba visual Electron y build Windows.
- `compileall` y `git diff --check`: aprobados.
- Repositorios: limpios y sincronizados al cierre.

## Continuidad

Antes de incorporar caché o más proveedores se recomienda medir cobertura,
latencia, estados pendientes y disponibilidad ORS sobre viajes reales, sin
persistir información adicional todavía.
