# Verificación externa de destinos

Fecha de revisión documental: 2026-07-28.

## Fuentes oficiales revisadas

- Geocoder Endpoint (Pelias alojado por HeiGIT):
  https://giscience.github.io/openrouteservice/api-reference/endpoints/geocoder/
- Endpoints y separación entre ORS y servicios públicos incluidos:
  https://giscience.github.io/openrouteservice/api-reference/endpoints/
- Códigos HTTP y errores:
  https://giscience.github.io/openrouteservice/api-reference/error-codes
- Restricciones de la API:
  https://openrouteservice.org/restrictions/
- FAQ sobre orden `[longitud, latitud]`, cuotas 403/429 y uso de claves:
  https://giscience.github.io/openrouteservice/frequently-asked-questions.html
- API pública e ingreso a documentación interactiva:
  https://api.openrouteservice.org/
- Anuncio oficial de migración del host público a `api.heigit.org`:
  https://ask.openrouteservice.org/t/deprecating-api-openrouteservice-org-in-favour-of-api-heigit-org/7912

La documentación vigente identifica la geocodificación como Pelias, alojada
por HeiGIT y disponible sólo en la API pública. El adaptador usa el host vigente
`api.heigit.org/pelias/v1/search`, GeoJSON en orden longitud/latitud y
autenticación en cabecera. La clave nunca forma parte de la URL registrada.

## Flujo

1. Recibir `SolicitudVerificacionDestino` inmutable.
2. Exigir autorización externa explícita.
3. Aplicar lista positiva: dirección, comuna, región y país.
4. Construir consulta e identificador normalizados.
5. Consultar caché opcional y límite local.
6. Ejecutar un único GET con timeout configurable.
7. Validar HTTP, JSON, GeoJSON, coordenadas y cantidad de candidatos.
8. Comparar comuna y región esperadas.
9. Devolver `ResultadoVerificacionDestino` estructurado.
10. Convertirlo, si contiene un candidato válido, en `Evidencia` de tipo
    `VERIFICACION_EXTERNA`.

ORS nunca escribe datos ni sobrescribe valores. El motor recibe evidencia, no
detalles HTTP.

## Estados

`VERIFICADA`, `COINCIDENCIA_PARCIAL`, `CONTRADICCION_COMUNA`,
`CONTRADICCION_REGION`, `SIN_RESULTADOS`, `CREDENCIAL_NO_DISPONIBLE`,
`CUOTA_AGOTADA`, `TIMEOUT`, `ERROR_PROVEEDOR`, `DATOS_INSUFICIENTES`,
`CONSULTA_NO_AUTORIZADA` y `REVISAR`.

Una coincidencia aproximada requiere revisión. Comuna o región diferentes
producen contradicción. Varios candidatos producen `REVISAR`; sus apoyos no se
suman como fuentes independientes. Coordenadas inválidas se descartan.

## Privacidad y seguridad

No se envían imagen, RUT, chofer, patente, transporte, guía ni contexto
adicional. `OPENROUTESERVICE_API_KEY` se lee sólo del entorno y se coloca en la
cabecera de la solicitud. No aparece en URL, resultados, errores, caché,
evidencia, pruebas ni documentación.

## Caché, cuotas y funcionamiento sin internet

La caché en memoria usa SHA-256 de la consulta normalizada, TTL configurable y
puede desactivarse. No persiste en datos productivos. El límite local impide
superar el número configurado de consultas. HTTP 403/429 se traduce a cuota
agotada; timeout y demás errores se controlan sin romper el motor.

Sin autorización, datos mínimos, credencial o conexión, Atlas continúa y
conserva el valor original.

## Limitaciones

No hay conexión con catálogos, viajes, reportes o Desktop. No se persisten
coordenadas ni resultados. Antes de usar destinos reales se requiere revisión
independiente, autorización por registro, política de retención, evaluación
ciega, confirmación humana para contradicciones y monitoreo de cuota/calidad.
