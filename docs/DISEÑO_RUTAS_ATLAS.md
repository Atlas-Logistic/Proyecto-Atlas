# Diseño aislado de rutas y distancias — Atlas

## 1. Propósito y límites

Esta fase define una prueba técnica opcional para calcular distancia y duración por carretera entre una planta confirmada y un destino confirmado. No implementa código, no realiza consultas externas y no se integra con OCR, extracción, procesamiento masivo, viajes ni reportes.

OpenRouteService (ORS) es el primer proveedor propuesto, no una dependencia permanente. Atlas debe conservar su funcionamiento normal cuando no exista credencial, conexión o proveedor disponible.

## 2. Datos disponibles y datos faltantes

Los contratos actuales de Plantas y Destinos ya ofrecen:

- UUID estable de la entidad;
- nombre original y normalizado;
- dirección, comuna, región y país;
- latitud y longitud opcionales, validadas como pareja;
- estado de calidad y vigencia;
- fuente, observación y fechas de auditoría.

Una planta confirmada usa `CONFIRMADA` y `ACTIVA`. Un destino confirmado usa `CONFIRMADO` y `ACTIVO`. Ambos catálogos protegen los registros confirmados: cualquier edición requiere una operación manual explícita.

Para consultar una ruta faltan, según cada registro:

- coordenadas de origen y destino confirmadas por una persona;
- una dirección suficientemente completa y no ambigua cuando no haya coordenadas;
- perfil de ruta explícito, inicialmente `driving-car` o, tras validación funcional, `driving-hgv`;
- identificador y versión del proveedor;
- credencial disponible solo en tiempo de ejecución;
- política de tiempo de espera, reintentos y control de cuota.

La ausencia de coordenadas no es un error del catálogo. Es un estado previo a la geocodificación.

## 3. Arquitectura propuesta

La solución futura debe dividirse en cuatro piezas sin dependencias hacia OCR:

1. **Servicio de aplicación**: valida entidades, consulta caché y coordina confirmaciones.
2. **Puerto `ProveedorRutas`**: contrato interno independiente del proveedor.
3. **Adaptador ORS**: convierte solicitudes y respuestas HTTP al contrato interno.
4. **Repositorio privado de rutas**: persiste únicamente rutas confirmadas mediante escritura atómica; los candidatos geográficos permanecen en memoria.

Contrato conceptual:

```python
class ProveedorRutas(Protocol):
    nombre: str
    version: str

    def geocodificar(self, direccion: DireccionConsulta) -> ResultadoGeocodificacion:
        ...

    def calcular_ruta(
        self,
        origen: Coordenadas,
        destino: Coordenadas,
        perfil: str,
    ) -> ResultadoRuta:
        ...
```

Los objetos de resultado deben contener datos o un estado explícito; nunca deben comunicar un fallo usando distancia o duración cero. El adaptador no debe importar catálogos ni conocer OCR. El servicio de aplicación es el único componente autorizado para leer Plantas, Destinos y el repositorio de rutas.

El orden externo de coordenadas de ORS debe adaptarse de forma explícita: su API emplea pares `[longitud, latitud]`. Internamente Atlas debe usar campos con nombre para impedir inversiones accidentales.

## 4. Estados y decisiones

Estados mínimos:

| Estado | Significado | Persistencia permitida |
|---|---|---|
| `RUTA_CALCULADA` | Ruta válida con distancia y duración positivas | Sí, después de confirmación explícita |
| `SIN_CREDENCIAL` | No existe `OPENROUTESERVICE_API_KEY` | Solo diagnóstico no sensible |
| `SIN_CONEXION` | Tiempo de espera, DNS o conectividad fallida | No como ruta válida |
| `DIRECCION_NO_ENCONTRADA` | El proveedor no devolvió candidatos utilizables | Opcional como intento auditable |
| `RESULTADO_AMBIGUO` | Hay varios candidatos plausibles | No guardar coordenadas automáticamente |
| `PROVEEDOR_NO_DISPONIBLE` | Error del servicio, incompatibilidad o circuito abierto | No como ruta válida |
| `REQUIERE_REVISION` | Resultado geográfico o ruta necesita decisión humana | Sí como borrador privado, nunca como confirmado |

Los errores de autenticación o cuota se traducen a un estado controlado y a un motivo sanitizado, sin registrar cabeceras de autorización ni cuerpos que pudieran contener secretos.

## 5. Reglas del servicio de aplicación

Antes de cualquier consulta, el servicio debe:

1. comprobar que la planta existe, está `CONFIRMADA` y `ACTIVA`;
2. comprobar que el destino existe, está `CONFIRMADO` y `ACTIVO`;
3. construir una dirección canónica sin alterar el texto maestro;
4. calcular las huellas normalizadas de ambas direcciones;
5. buscar una ruta previa con la clave lógica y las mismas huellas;
6. devolver el resultado almacenado si existe, sin consumir cuota;
7. comprobar credencial y disponibilidad solo cuando realmente haga falta consultar.

Una respuesta ambigua detiene el flujo. Ninguna coordenada se copia automáticamente a Plantas o Destinos. Si más adelante se decide incorporarla al catálogo maestro, debe hacerse mediante la CLI existente, con confirmación manual explícita, fuente y observación de auditoría.

## 6. Catálogo privado `catalogos/rutas.json`

El archivo se crea únicamente al confirmar y guardar la primera ruta. Está ignorado por Git, se escribe atómicamente y usa un formato versionado.

La implementación inicial mantiene una colección `rutas`. Cada ruta confirmada conserva las coordenadas seleccionadas y las huellas de ambas direcciones. Los candidatos de geocodificación no se persisten por separado, evitando guardar resultados ambiguos o pendientes.

Ejemplo estructural completamente sintético:

```json
{
  "version_formato": 1,
  "rutas": [
    {
      "ruta_id": "UUID_SINTETICO",
      "planta_id": "PLANTA_ID_SINTETICO",
      "destino_id": "DESTINO_ID_SINTETICO",
      "perfil_ruta": "driving-car",
      "distancia_km": 12.34,
      "duracion_estimada_min": 25.5,
      "coordenadas_origen": {"latitud": -10.0, "longitud": -20.0},
      "coordenadas_destino": {"latitud": -10.1, "longitud": -20.1},
      "proveedor": "openrouteservice",
      "version_proveedor": "VERSION_CONFIGURADA",
      "fecha_calculo": "2026-01-01T00:00:00+00:00",
      "estado": "RUTA_CALCULADA",
      "motivo": "CONFIRMADA_POR_USUARIO_AUTORIZADO",
      "fecha_creacion": "2026-01-01T00:00:00+00:00",
      "fecha_modificacion": "2026-01-01T00:00:00+00:00"
    }
  ]
}
```

La clave lógica de ruta es:

```text
planta_id + destino_id + perfil_ruta + proveedor + version_proveedor
```

Debe existir un índice único sobre esa composición. La huella de dirección debe incluir tipo e ID de entidad, dirección normalizada y proveedor/versión. Un cambio en la dirección invalida la reutilización, pero conserva el historial anterior.

La distancia se recibe en metros y la duración en segundos desde el adaptador, se validan como valores finitos y positivos, y solo entonces se convierten a kilómetros y minutos. Debe conservarse precisión suficiente para auditoría y aplicarse redondeo únicamente al presentar.

## 7. Seguridad de la credencial

La clave se leerá exclusivamente desde:

```text
OPENROUTESERVICE_API_KEY
```

Reglas:

- no incluir valor predeterminado;
- no guardar la clave en código, JSON, documentación, excepciones ni logs;
- no imprimir objetos de solicitud con cabeceras completas;
- enviar la solicitud desde el proceso local o servidor, nunca exponer la clave en un cliente público;
- no crear cuentas ni claves automáticamente;
- devolver `SIN_CREDENCIAL` antes de abrir una conexión si la variable no existe;
- sanitizar errores HTTP y aplicar tiempos de espera finitos.

`.env` ya está ignorado. Antes de implementar debe ampliarse la protección a variantes locales, por ejemplo `.env.*`, conservando una eventual excepción explícita para una plantilla pública sin secretos como `.env.example`. Esta fase no modifica `.gitignore`.

Configuración futura en PowerShell para la sesión actual, sin escribir archivos:

```powershell
$env:OPENROUTESERVICE_API_KEY = "VALOR_PROPORCIONADO_MANUALMENTE"
```

No se debe copiar el valor a historiales, capturas o salidas de diagnóstico. Para persistencia local, el usuario debe escoger posteriormente un mecanismo seguro del sistema operativo; no se define ni ejecuta en esta fase.

## 8. Prueba piloto futura

La prueba controlada se realizará solo después de una nueva autorización:

1. seleccionar por UUID una planta confirmada y activa;
2. seleccionar por UUID un destino confirmado y activo;
3. mostrar la dirección canónica del origen y pedir autorización para consultar;
4. hacer una única geocodificación del origen si no existe caché confirmada;
5. mostrar candidatos, precisión y dirección devuelta para revisión humana;
6. mantener el resultado solo en memoria hasta confirmación;
7. repetir el proceso para el destino;
8. calcular una sola ruta con coordenadas confirmadas y perfil explícito;
9. mostrar proveedor, perfil, distancia y duración, sin guardar;
10. guardar la ruta y las coordenadas elegidas únicamente después de confirmación explícita;
11. repetir la misma solicitud y demostrar que se obtiene desde el catálogo local sin llamadas externas.

La prueba tendrá un presupuesto máximo de tres operaciones externas: dos geocodificaciones y un cálculo de ruta. Cualquier ambigüedad, falta de credencial, error de cuota o fallo de conexión detiene el piloto sin persistir una ruta calculada.

## 9. Cuota, costo y control de tráfico

Consumen cuota externa:

- cada geocodificación enviada al servicio público;
- cada cálculo de Directions;
- cualquier reintento que llegue al proveedor.

Para minimizar consumo:

- geocodificar cada huella de lugar una sola vez y reutilizar únicamente resultados confirmados;
- calcular una combinación lógica de ruta una sola vez;
- consultar el repositorio local antes de comprobar la red;
- prohibir reintentos automáticos de errores deterministas, autenticación, ambigüedad y cuota;
- permitir como máximo un reintento controlado para fallos transitorios, con espera indicada por el proveedor y sin superar el presupuesto del piloto;
- abrir un circuito temporal ante indisponibilidad o cuota agotada.

Los límites numéricos no se fijan en código ni en este documento. Antes del piloto deben consultarse los planes, el panel del usuario y la documentación oficial vigentes. ORS documenta límites diarios y por ventana temporal, cabeceras de cuota y respuestas diferenciadas para agotamiento; Atlas debe detener nuevas consultas ante esas respuestas y conservar el motivo sanitizado.

## 10. Dependencias

`requirements.txt` no contiene actualmente un cliente HTTP general. Hay dos alternativas futuras:

- **Biblioteca estándar `urllib.request`**: cero dependencias nuevas, suficiente para un piloto pequeño, pero requiere más código para serialización, errores y pruebas.
- **`requests`**: dependencia mínima propuesta para un adaptador mantenible, con tiempos de espera explícitos, cabeceras y manejo claro de estados HTTP.

La decisión recomendada para implementación es agregar `requests` con versión compatible y pruebas mediante transporte simulado; no debe instalarse ni agregarse todavía. No es necesario incorporar un SDK de ORS: el puerto interno y un adaptador HTTP pequeño reducen acoplamiento y facilitan cambiar de proveedor.

## 11. Cambio de proveedor

El servicio de aplicación depende únicamente de `ProveedorRutas`. Cada adaptador declara nombre, versión, perfiles soportados y capacidades. La conversión de coordenadas, autenticación, endpoints, errores y estructura de respuesta queda dentro del adaptador.

Para sustituir ORS:

1. implementar el mismo puerto;
2. traducir sus estados al vocabulario de Atlas;
3. registrar proveedor y versión en la clave lógica;
4. ejecutar las mismas pruebas contractuales con respuestas simuladas;
5. conservar rutas históricas del proveedor anterior, sin tratarlas como caché del nuevo.

Una futura instancia propia de ORS puede ser otro adaptador/configuración. La geocodificación de la API pública es un servicio asociado y no forma parte necesariamente de una instalación local de ORS, por lo que esa capacidad debe declararse separadamente.

## 12. Riesgos y mitigaciones

| Riesgo | Mitigación |
|---|---|
| Dirección incompleta o ambigua | Mostrar candidatos y exigir confirmación humana |
| Coordenadas invertidas | Tipos con campos nombrados y adaptación explícita `[lon, lat]` |
| Ruta inapropiada para carga pesada | Perfil configurable; validar `driving-hgv` y restricciones antes de uso operacional |
| Cuota agotada | Caché previa, presupuesto por ejecución, circuito abierto y detención ante cuota |
| Proveedor caído o sin internet | Estados controlados; Atlas continúa sin rutas |
| Filtración de clave | Variable de entorno, redacción de logs y solicitudes solo del lado servidor |
| Datos desactualizados | Huella de dirección y versión del proveedor en las claves lógicas |
| Persistencia prematura | Borrador en memoria y confirmación explícita antes de escribir |
| Distancia interpretada como verdad contractual | Guardar proveedor, perfil, fecha y motivo; tratarla como estimación reproducible |
| Acoplamiento con producción | Módulo independiente sin importaciones desde OCR ni procesamiento masivo |

## 13. Criterios de aceptación para autorizar implementación

- Ninguna importación o cambio en OCR, extractor o procesamiento masivo.
- Catálogos maestros solo se leen durante el cálculo.
- Planta y destino deben estar confirmados y activos.
- Sin clave o internet se obtiene un estado explícito y no una excepción destructiva.
- Ningún secreto aparece en repositorio, catálogo, consola o prueba.
- Geocodificación ambigua nunca se confirma automáticamente.
- Dos ejecuciones idénticas producen una sola consulta efectiva por operación.
- Distancia cero nunca representa un error.
- Persistencia privada, versionada, atómica y protegida por Git.
- Adaptador ORS sustituible mediante pruebas contractuales.
- Piloto limitado a una planta, un destino y tres operaciones externas como máximo.
- Ninguna escritura antes de confirmación humana explícita.

## 14. Referencias oficiales a verificar antes del piloto

- [OpenRouteService — Getting started](https://giscience.github.io/openrouteservice/getting-started)
- [OpenRouteService — API Reference](https://giscience.github.io/openrouteservice/api-reference/)
- [OpenRouteService — Directions Service](https://giscience.github.io/openrouteservice/api-reference/endpoints/directions/)
- [OpenRouteService — Endpoints y servicios incluidos](https://giscience.github.io/openrouteservice/api-reference/endpoints/)
- [OpenRouteService — FAQ de claves, coordenadas y cuota](https://giscience.github.io/openrouteservice/frequently-asked-questions.html)

Estas fuentes deben revisarse nuevamente en la fecha de ejecución porque planes, límites y condiciones pueden cambiar.
