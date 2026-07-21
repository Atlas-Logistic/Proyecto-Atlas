# Módulo aislado de Rutas — Atlas

## Alcance

El módulo calcula y conserva rutas entre Plantas y Destinos confirmados sin depender de OCR, extractor, procesamiento masivo, viajes o reportes. La fase actual está preparada para pruebas simuladas: la CLI no habilita OpenRouteService real.

## Arquitectura

- `modelos.py`: estados, coordenadas y resultados validados.
- `proveedor.py`: puerto reemplazable y proveedor simulado.
- `openrouteservice.py`: adaptador HTTP con `urllib.request` y transporte inyectable.
- `repositorio.py`: catálogo JSON privado, versionado, histórico y atómico.
- `servicio.py`: elegibilidad, caché, preparación y confirmación.

El servicio recibe objetos Planta y Destino ya cargados. Solo lee esos objetos; nunca edita sus catálogos.

## Estados

`RUTA_CALCULADA`, `RESULTADO_DESDE_CACHE`, `SIN_CREDENCIAL`, `SIN_CONEXION`, `DIRECCION_NO_ENCONTRADA`, `RESULTADO_AMBIGUO`, `PROVEEDOR_NO_DISPONIBLE`, `LIMITE_CUOTA`, `RESPUESTA_INVALIDA` y `REQUIERE_REVISION`.

Un fallo nunca contiene distancia cero. Una ruta calculada exige distancia y duración finitas y positivas.

## Flujo y confirmación

1. Validar planta `CONFIRMADA` y `ACTIVA`.
2. Validar destino `CONFIRMADO` y `ACTIVO`.
3. Exigir dirección, comuna, región y país en ambos.
4. Buscar ruta vigente por IDs, perfil, proveedor, versión y huellas de dirección.
5. Si existe, devolver `RESULTADO_DESDE_CACHE` sin llamar al proveedor.
6. Si no existe, geocodificar y devolver candidatos para revisión.
7. Calcular y guardar solo con confirmación explícita y coordenadas elegidas.

Si cambia una dirección, su huella deja de coincidir. Al guardar un cálculo nuevo, la ruta vigente anterior pasa a histórica y no se elimina.

## Seguridad

OpenRouteService obtiene la clave exclusivamente de `OPENROUTESERVICE_API_KEY`. La clave no forma parte de resultados, excepciones, JSON ni salida de CLI. La ausencia de variable produce `SIN_CREDENCIAL` antes de invocar transporte.

`.env` y `.env.*` están ignorados; `.env.example` es una plantilla pública vacía. No se deben escribir secretos en ella.

Configuración futura de una sesión PowerShell:

```powershell
$env:OPENROUTESERVICE_API_KEY = "VALOR_CONFIGURADO_MANUALMENTE"
$env:ATLAS_ROUTING_PROVIDER = "openrouteservice"
```

No debe ejecutarse todavía con una clave real.

## CLI simulada

Listar y mostrar:

```powershell
python gestionar_catalogos.py rutas listar
python gestionar_catalogos.py rutas mostrar "RUTA_ID"
```

Preparar candidatos sintéticos sin guardar:

```powershell
python gestionar_catalogos.py rutas calcular --planta-id "PLANTA_ID" --destino-id "DESTINO_ID" --perfil driving-car --proveedor-simulado
```

La confirmación simulada agrega `--confirmar` y las cuatro coordenadas explícitas. Sin `--proveedor-simulado`, la CLI se abstiene. No existe una opción CLI para activar ORS real en esta fase.

## Catálogo privado

`catalogos/rutas.json` se crea únicamente al guardar la primera ruta y está ignorado por Git. La escritura usa un temporal en el mismo directorio, sincronización y reemplazo atómico. Un archivo corrupto se reporta y no se sustituye silenciosamente.

La plantilla pública `catalogos/templates/rutas_ejemplo.json` es totalmente sintética.

## Pruebas

Las pruebas usan `ProveedorRutasSimulado` o un transporte HTTP inyectado. No abren conexiones. Cubren errores de proveedor, validaciones, caché, historial, atomicidad, secretos y compatibilidad de las CLI existentes.

## Cierre de la aplicación

La CLI es un proceso corto: termina al devolver el resultado. No crea servicios residentes, hilos, sesiones persistentes ni procesos de fondo. Para cancelar una ejecución interactiva futura puede usarse `Ctrl+C`; los tiempos de espera finitos evitan esperas indefinidas.

## Cambio de proveedor

Un proveedor nuevo implementa `geocodificar()` y `calcular_ruta()`, declara `nombre` y `version`, y traduce sus respuestas a estados de Atlas. El servicio y el repositorio no dependen de endpoints o autenticación de ORS.

## Limitaciones

- Sin geocodificaciones confirmadas reales.
- Sin prueba externa autorizada.
- Sin restricciones operacionales validadas para vehículos pesados.
- Sin política productiva de cuota o reintentos.
- Sin integración con viajes o reportes.
- La estimación depende del perfil, proveedor, versión y datos viales de la fecha de cálculo.

La prueba piloto real requiere una autorización separada.
